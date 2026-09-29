"""Orchestration: the only module that touches the store, the upstream clients and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and
never calls out. The run lifecycle:

1. Resolve the request against ``config.yaml`` (optimism level, calibration).
2. Compute the idempotency key from the three input artefact ids, the optimism level, the
   economies, the calibration's content hash, the engine version and the contract versions.
   The ``regime_id`` is ``RGM-`` plus the hash of that key (decided 27.09.2026), so identical
   inputs always give the identical id.
3. If an artefact already exists for that key, answer with the run that made it. Free.
4. Otherwise record a run, fetch the three inputs, check that they stem from one datafeed
   snapshot (a mismatch is warned and recorded, not refused: AGG-04), run the model, store.

A run that cannot finish is recorded as ``failed`` with the reason, not retried silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from importlib import metadata
from typing import Any, Optional

import numpy as np
from pydantic import ValidationError

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import model_card
from . import scenario as sc
from . import store as st
from .clients import ArtefactClient, UpstreamError, checksum
from .contracts import (
    CONTRACT_VERSIONS,
    STORED,
    AggregationRunRequest,
    Calibration,
    CoverageReport,
    CycleState,
    EconomyOption,
    EconomyRegime,
    MarketCoverage,
    MarketRegime,
    MacroState,
    MarketRiskSignal,
    ModelCard,
    OptimismScale,
    Provenance,
    Reading,
    Regime,
    RunAccepted,
    RunStatus,
    ScenarioAccepted,
    ScenarioListed,
    ScenarioPolicyInfo,
    ScenarioProvenance,
    ScenarioRequest,
)
from .engine import EngineError, _tuple, describe, mean_state, modal_state, run_model
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


class Unavailable(RuntimeError):
    """An upstream engine is needed and is not there."""


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def regime_id_for(idempotency_key: str) -> str:
    """``RGM-`` + hash of the idempotency key (Engine Building Guide section 4)."""
    return f"RGM-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:16]}"


class Service:
    def __init__(self, settings: Settings, store: st.Store, mrs: ArtefactClient[MarketRiskSignal],
                 cycle: ArtefactClient[CycleState], macrofield: ArtefactClient[MacroState]):
        self.settings = settings
        self.store = store
        self.mrs = mrs
        self.cycle = cycle
        self.macrofield = macrofield
        self.started = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    def startup(self) -> None:
        """Create tables, write the seed calibrations, and check the active one exists."""
        self.store.initialise()
        with self.store.session() as conn:
            for cal in seeds.SEEDS:
                try:
                    st.put_calibration(conn, version=cal.version,
                                       calibration_hash=seeds.calibration_hash(cal),
                                       parent_version=cal.parent_version,
                                       payload_json=seeds.canonical_json(cal))
                except st.StoreConflict as exc:
                    raise st.StoreError(
                        f"seed calibration {cal.version} in calibration.py no longer matches "
                        "the stored one. Seeds are immutable: give the change a new version."
                    ) from exc
            if st.get_calibration(conn, self.settings.active_calibration) is None:
                raise st.StoreError(
                    f"config.yaml names active calibration {self.settings.active_calibration!r}, "
                    "which is not in the store"
                )

    # -- standard endpoints ------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self, allowlist: dict[str, Any]) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
        return {
            "engine": ENGINE,
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": self.settings.active_calibration,
            "calibration_versions": versions,
            "default_optimism": self.settings.default_optimism,
            "allowlist": allowlist,
            "upstream": {"mrs": self.settings.mrs_url, "cycle": self.settings.cycle_url,
                         "macrofield": self.settings.macrofield_url},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
        }

    # -- calibration -------------------------------------------------------

    def calibration(self, version: Optional[str] = None) -> Calibration:
        version = version or self.settings.active_calibration
        with self.store.session() as conn:
            payload = st.get_calibration(conn, version)
        if payload is None:
            raise NotFound(f"no calibration {version!r}")
        return Calibration.model_validate_json(payload)

    def calibration_versions(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_calibrations(conn)
        return [{**r, "active": r["version"] == self.settings.active_calibration} for r in rows]

    def propose_calibration(self, proposal: Calibration) -> tuple[Calibration, bool]:
        """Store a new version. Returns (calibration, created)."""
        with self.store.session() as conn:
            if proposal.parent_version and st.get_calibration(conn, proposal.parent_version) is None:
                raise InvalidRequest(f"parent_version {proposal.parent_version!r} does not exist")
            try:
                created = st.put_calibration(
                    conn, version=proposal.version,
                    calibration_hash=seeds.calibration_hash(proposal),
                    parent_version=proposal.parent_version,
                    payload_json=seeds.canonical_json(proposal),
                )
            except st.StoreConflict as exc:
                raise Conflict(str(exc)) from exc
        return proposal, created

    # -- runs --------------------------------------------------------------

    def _optimism(self, request: AggregationRunRequest) -> OptimismScale:
        return request.optimism_scale or self.settings.default_optimism  # type: ignore[return-value]

    def idempotency_key(self, request: AggregationRunRequest, cal: Calibration) -> str:
        return content_id("IDK", {
            "mrs_artefact_id": request.mrs_artefact_id,
            "cycle_artefact_id": request.cycle_artefact_id,
            "macro_artefact_id": request.macro_artefact_id,
            "optimism_scale": self._optimism(request),
            "economies": None if request.economies is None else list(request.economies),
            "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        })

    def submit(self, request: AggregationRunRequest) -> RunAccepted:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        key = self.idempotency_key(request, cal)
        rid = regime_id_for(key)

        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded", artefact_id=done["artefact_id"],
                               regime_id=rid, idempotency_key=key, cached=True)

        started_at = st.utc_now()
        run_id = content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                    "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, status="running",
                          started_at=started_at, request_json=request.model_dump_json())
        try:
            artefact = self._execute(request, cal, key, rid)
        except (UpstreamError, EngineError, ValidationError) as exc:
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", coverage_json=None, provenance_json=None,
                              error=f"{type(exc).__name__}: {exc}")
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None, regime_id=None,
                               idempotency_key=key, cached=False)

        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=artefact.artefact_id, regime_id=rid, idempotency_key=key,
                            contract_version=artefact.contract_version,
                            payload_json=artefact.model_dump_json(context=STORED))
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0,
                          artefact_id=artefact.artefact_id,
                          warnings_json=json.dumps(list(artefact.coverage.warnings)),
                          coverage_json=artefact.coverage.model_dump_json(),
                          provenance_json=artefact.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=artefact.artefact_id,
                           regime_id=rid, idempotency_key=key, cached=False)

    def _execute(self, request: AggregationRunRequest, cal: Calibration, key: str, rid: str) -> Regime:
        mrs = self.mrs.artefact(request.mrs_artefact_id)
        cycle = self.cycle.artefact(request.cycle_artefact_id)
        macro = self.macrofield.artefact(request.macro_artefact_id)
        optimism = self._optimism(request)
        return build_regime(mrs, cycle, macro, cal, optimism, key, rid, request.economies)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
            regime = None
            if row is not None and row["artefact_id"]:
                payload = st.get_artefact(conn, row["artefact_id"])
                regime = None if payload is None else json.loads(payload)["regime_id"]
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            wall_clock_ms=row["wall_clock_ms"],
            request=AggregationRunRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"], regime_id=regime,
            warnings=tuple(json.loads(row["warnings_json"])),
            coverage=(CoverageReport.model_validate_json(row["coverage_json"])
                      if row["coverage_json"] else None),
            provenance=(Provenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"],
        )

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, max(1, min(limit, 500)))
        out = []
        for r in rows:
            req = json.loads(r.pop("request_json"))
            out.append({**r, "optimism_scale": req.get("optimism_scale"),
                        "calibration_version": req.get("calibration_version")})
        return out

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> Regime:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        return Regime.model_validate_json(payload)

    def regime(self, regime_id: str) -> Regime:
        with self.store.session() as conn:
            payload = st.get_artefact_by_regime(conn, regime_id)
        if payload is None:
            raise NotFound(f"no regime {regime_id!r}")
        return Regime.model_validate_json(payload)

    def path(self, regime_id: str, economy: Optional[str] = None) -> dict[str, Any]:
        """``date -> state`` per economy and market (mean-nearest state; modal beside it)."""
        r = self.regime(regime_id)
        rows = [("economy", e.code, e.state, e.modal_state) for e in r.economies] + \
               [("market", m.code, m.state, m.modal_state) for m in r.markets]
        if economy is not None:
            rows = [x for x in rows if x[1] == economy]
            if not rows:
                raise NotFound(f"regime {regime_id} carries no economy or market {economy!r}")
        return {"regime_id": r.regime_id, "optimism_scale": r.optimism_scale, "dates": r.dates,
                "paths": [{"kind": kind, "code": code,
                           "path": [{"date": d, "state": s, "modal_state": m}
                                    for d, s, m in zip(r.dates, states, modal) if s is not None]}
                          for kind, code, states, modal in rows],
                "notice": r.notice}

    def distribution(self, regime_id: str, date: Optional[str] = None,
                     economy: Optional[str] = None) -> dict[str, Any]:
        """The 25-state distribution at one date (default: the last date) per economy and market."""
        r = self.regime(regime_id)
        t = self._date_index(r, date)
        rows = [("economy", e.code, e.distribution[t]) for e in r.economies] + \
               [("market", m.code, m.distribution[t]) for m in r.markets]
        if economy is not None:
            rows = [x for x in rows if x[1] == economy]
            if not rows:
                raise NotFound(f"regime {regime_id} carries no economy or market {economy!r}")
        return {"regime_id": r.regime_id, "date": r.dates[t], "n_states": r.n_states,
                "optimism_scale": r.optimism_scale,
                "distributions": [{"kind": kind, "code": code, "distribution": d}
                                  for kind, code, d in rows],
                "notice": r.notice}

    def current(self, regime_id: str) -> dict[str, Any]:
        r = self.regime(regime_id)
        out = {"regime_id": r.regime_id, "optimism_scale": r.optimism_scale,
               "economies": [{"code": e.code, "name": e.name,
                              **(e.current.model_dump() if e.current else {"state": None})}
                             for e in r.economies],
               "markets": [{"code": m.code, **(m.current.model_dump() if m.current else {"state": None})}
                           for m in r.markets],
               "notice": r.notice}
        if r.provenance.scenario is not None:          # additive, scenario Regimes only (AGG-21)
            out["scenario"] = r.provenance.scenario.model_dump(mode="json")
        return out

    def contributions(self, regime_id: str, economy: str, date: Optional[str] = None) -> dict[str, Any]:
        """Each input's contribution to each state at one date, before and after the optimism
        shift: ``weight * component``; the three sum to the combined distribution before the
        shift."""
        r = self.regime(regime_id)
        try:
            e = r.economy(economy)
        except KeyError as exc:
            raise NotFound(f"regime {regime_id} carries no economy {economy!r}") from exc
        t = self._date_index(r, date)
        if e.distribution[t] is None:
            return {"regime_id": r.regime_id, "economy": economy, "date": r.dates[t], "assessed": False}
        if r.provenance.scenario is not None and r.dates[t] >= r.provenance.scenario.projected_from:
            # A projected month is the .m file's step towards the policy's target, not a blend of
            # inputs, so there is nothing to decompose (AGG-20).
            return {"regime_id": r.regime_id, "economy": economy, "date": r.dates[t], "assessed": True,
                    "projected": True, "scenario": r.provenance.scenario.model_dump(mode="json"),
                    "optimism_scale": r.optimism_scale, "contributions": {},
                    "distribution": e.distribution[t], "notice": r.notice}
        year = e.macro_year[t]
        i = e.years.index(year)
        parts = {
            "macro": (e.weight_macro[t], e.macro_layer[i]),
            "market": (e.weight_market[t], e.market[t]),
            "cycle": (e.weight_cycle[t], e.cycle_layer[i]),
        }
        contributions = {}
        for name, (w, comp) in parts.items():
            contributions[name] = {
                "weight": w, "component": comp,
                "contribution": None if comp is None or not w else [w * p for p in comp],
            }
        return {"regime_id": r.regime_id, "economy": economy, "date": r.dates[t], "assessed": True,
                "macro_year": year, "carried": e.carried[t],
                "macro_weights": e.macro_weights[i], "tilts": e.tilts[i],
                "optimism_scale": r.optimism_scale, "optimism_shift": r.provenance.optimism_shift,
                "contributions": contributions, "distribution": e.distribution[t],
                "notice": r.notice}

    def model_card(self, economy: Optional[str] = None) -> ModelCard:
        """The aggregation layer explained on one economy (``GET /model``): the latest Regime at
        the default optimism level (else the latest), and the three input artefacts it names."""
        done = [r for r in self.runs(500) if r["status"] == "succeeded" and r["artefact_id"]]
        if not done:
            raise NotFound("aggregation has no successful run yet; POST /run first")
        pick = next((r for r in done if r.get("optimism_scale") in (None, "default")), done[0])
        regime = self.artefact(pick["artefact_id"])
        up = regime.provenance.upstream
        try:
            mrs = self.mrs.artefact(up["mrs:artefact"])
            cycle = self.cycle.artefact(up["cycle:artefact"])
            macro = self.macrofield.artefact(up["macrofield:artefact"])
        except UpstreamError as exc:
            raise Unavailable(f"the Regime's inputs cannot be read: {exc}") from exc
        codes = [e.code for e in regime.economies]
        code = economy or ("US" if "US" in codes else codes[0])
        if code not in codes:
            raise InvalidRequest(f"{code!r} is not in regime {regime.regime_id}; it carries {codes}")
        cal = self.calibration(regime.provenance.calibration_version)
        return model_card.build(regime, mrs, cycle, macro, cal, code,
                                [EconomyOption(code=e.code, name=e.name) for e in regime.economies])

    # -- scenario Regimes (AGG-19 to AGG-22) --------------------------------

    @staticmethod
    def scenario_policies() -> list[ScenarioPolicyInfo]:
        return [ScenarioPolicyInfo(policy=p, case=spec.case, label_en=spec.label_en, label_de=spec.label_de,
                                   description_en=spec.description_en, description_de=spec.description_de,
                                   target_mix=dict(zip(sc.MIX_PHASES, spec.target_mix)))
                for p, spec in sc.POLICIES.items()]

    @staticmethod
    def scenario_key(base: Regime, policy: str) -> str:
        """The base regime_id, the policy, the base's calibration hash, and every version (AGG-21)."""
        return content_id("IDK", {
            "scenario": policy,
            "base_regime_id": base.regime_id,
            "calibration_hash": base.provenance.calibration_hash,
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
            "scenario_rule": sc.SCENARIO_RULE_VERSION,
            "template_sha256": sc.TEMPLATE_SHA256,
            "horizon_months": sc.HORIZON_MONTHS,
        })

    def create_scenario(self, request: ScenarioRequest) -> ScenarioAccepted:
        """Derive, store and index the scenario Regime; the same request twice is answered from
        the store."""
        base = self.regime(request.base_regime_id)
        if base.provenance.scenario is not None:
            raise InvalidRequest(f"{base.regime_id} is itself a scenario Regime "
                                 f"({base.provenance.scenario.policy} on {base.provenance.scenario.base_regime_id}); "
                                 "derive scenarios from an issued Regime")
        key = self.scenario_key(base, request.policy)
        rid = regime_id_for(key)
        with self.store.session() as conn:
            existing = st.get_artefact_by_regime(conn, rid)
            if existing is not None:
                st.put_scenario(conn, regime_id=rid, artefact_id=json.loads(existing)["artefact_id"],
                                base_regime_id=base.regime_id, policy=request.policy)
                return ScenarioAccepted(regime_id=rid, cached=True, policy=request.policy,
                                        base_regime_id=base.regime_id)
        cal = self.calibration(base.provenance.calibration_version)
        try:
            regime = build_scenario_regime(base, request.policy, cal.reading, key, rid)
        except (EngineError, ValidationError, ValueError) as exc:
            raise InvalidRequest(f"cannot derive the {request.policy} scenario from {base.regime_id}: {exc}") from exc
        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=regime.artefact_id, regime_id=rid, idempotency_key=key,
                            contract_version=regime.contract_version, payload_json=regime.model_dump_json(context=STORED))
            st.put_scenario(conn, regime_id=rid, artefact_id=regime.artefact_id,
                            base_regime_id=base.regime_id, policy=request.policy)
        return ScenarioAccepted(regime_id=rid, cached=False, policy=request.policy, base_regime_id=base.regime_id)

    def scenarios(self, base: Optional[str] = None) -> list[ScenarioListed]:
        with self.store.session() as conn:
            rows = st.list_scenarios(conn, base)
        return [ScenarioListed(**r) for r in rows]

    @staticmethod
    def _date_index(r: Regime, date: Optional[str]) -> int:
        if date is None:
            assessed = [k for k in range(len(r.dates))
                        if any(e.distribution[k] is not None for e in r.economies)]
            if not assessed:
                raise NotFound(f"regime {r.regime_id} assesses no date")
            return assessed[-1]
        matches = [k for k, d in enumerate(r.dates) if d == date or d.startswith(date)]
        if not matches:
            raise NotFound(f"regime {r.regime_id} has no date {date!r} "
                           f"(range {r.dates[0]} to {r.dates[-1]})")
        return matches[-1]


def build_regime(mrs: MarketRiskSignal, cycle: CycleState, macro: MacroState, cal: Calibration,
                 optimism: OptimismScale, key: str, rid: str,
                 economies: Optional[tuple[str, ...]] = None) -> Regime:
    """The model plus provenance and the snapshot checks. Pure apart from hashing."""
    warnings: list[str] = []
    snapshots = {"mrs": mrs.provenance.snapshot_id, "cycle": cycle.provenance.snapshot_id,
                 "macrofield": macro.provenance.snapshot_id}
    mismatch = len(set(snapshots.values())) > 1
    if mismatch:
        warnings.append("the inputs do not stem from one datafeed snapshot ("
                        + ", ".join(f"{k} {v}" for k, v in snapshots.items())
                        + "); accepted and recorded (AGG-04), not refused")
    cycle_reads = cycle.provenance.upstream.get("macrofield:artefact")
    if cycle_reads and cycle_reads != macro.artefact_id:
        warnings.append(f"the cycle state read macrofield artefact {cycle_reads}, not the macro state "
                        f"{macro.artefact_id} this run combines it with")

    out = run_model(mrs, cycle, macro, cal, optimism, economies)
    if not out.economies:
        raise EngineError("no economy is carried by all three inputs: "
                          + "; ".join(f"{k}: {v}" for k, v in out.economies_skipped.items()))
    warnings.extend(out.warnings)
    assessed = [d for k, d in enumerate(out.dates)
                if any(e.distribution[k] is not None for e in out.economies)]
    if not assessed:
        raise EngineError("no month is assessed: the macro years and the market risk signal's "
                          "months do not overlap")
    coverage = CoverageReport(economies=out.economy_coverage, markets=out.market_coverage,
                              economies_skipped=out.economies_skipped, snapshot_mismatch=mismatch,
                              warnings=tuple(warnings))
    upstream = {
        "mrs:artefact": mrs.artefact_id, "mrs:snapshot": mrs.provenance.snapshot_id,
        "mrs:calibration": mrs.provenance.calibration_version, "mrs:sha256": checksum(mrs),
        "cycle:artefact": cycle.artefact_id, "cycle:snapshot": cycle.provenance.snapshot_id,
        "cycle:calibration": cycle.provenance.calibration_version, "cycle:sha256": checksum(cycle),
        "macrofield:artefact": macro.artefact_id, "macrofield:snapshot": macro.provenance.snapshot_id,
        "macrofield:calibration": macro.provenance.calibration_version,
        "macrofield:sha256": checksum(macro),
    }
    provenance = Provenance(
        snapshot_id=mrs.provenance.snapshot_id, as_of=assessed[-1], upstream=upstream,
        engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS,
        calibration_version=cal.version, calibration_hash=seeds.calibration_hash(cal),
        idempotency_key=key, regime_id=rid, optimism_scale=optimism,
        optimism_shift=cal.optimism.shift(optimism),
    )
    body = dict(regime_id=rid, optimism_scale=optimism, dates=out.dates, economies=out.economies,
                markets=out.markets, coverage=coverage, provenance=provenance)
    draft = Regime(artefact_id="", **body)
    return Regime(artefact_id=content_id("AGG", draft.model_dump(mode="json")), **body)


def build_scenario_regime(base: Regime, policy: str, reading: Reading, key: str, rid: str) -> Regime:
    """A scenario Regime (AGG-19, AGG-20): the base Regime's history up to its ``as_of``, then
    ``HORIZON_MONTHS`` projected months in which each economy's latest distribution moves step by
    step, as ``Scenario_SAA.m`` moves ``MRS_start``, to the policy's target. The last month, the
    target reached, is the Regime's last date and ``as_of``, and every economy is assessed on it, so
    a consumer that reads the latest month where all its economies are assessed (pcp) reads the
    scenario. The optimism level stays the base's and shifts only the history: the target is the
    policy's own reading (AGG-20). Markets are blended from the projected economies with the base's
    weights, by the base's rule (every weighted economy assessed). Pure apart from hashing."""
    if base.provenance.scenario is not None:
        raise EngineError(f"{base.regime_id} is already a scenario Regime")
    horizon = sc.HORIZON_MONTHS
    cut = base.dates.index(base.provenance.as_of) + 1
    history = base.dates[:cut]
    projected = sc.month_ends_after(history[-1], horizon)
    dates = tuple(history) + tuple(projected)
    target = sc.target_distribution(policy)
    spec = sc.POLICIES[policy]
    none = (None,) * horizon
    note = (f"scenario {policy} ({spec.label_en}, Scenario_SAA.m case {spec.case}): from {projected[0]} the "
            f"latest distribution moves in {horizon} monthly steps to the policy's target, reached on "
            f"{projected[-1]}; history up to {history[-1]} is {base.regime_id}")

    economies: list[EconomyRegime] = []
    rows_by: dict[str, np.ndarray] = {}
    for e in base.economies:
        last = next((k for k in range(cut - 1, -1, -1) if e.distribution[k] is not None), None)
        if last is None:
            raise EngineError(f"{e.code} is assessed on no month of {base.regime_id}")
        path = sc.step_path(np.asarray(e.distribution[last], dtype=float), target, horizon)
        rows_by[e.code] = path
        economies.append(EconomyRegime(**{
            **{f: getattr(e, f) for f in EconomyRegime.model_fields},
            "distribution": e.distribution[:cut] + tuple(_tuple(p) for p in path),
            "state": e.state[:cut] + tuple(mean_state(p) for p in path),
            "modal_state": e.modal_state[:cut] + tuple(modal_state(p) for p in path),
            "macro_year": e.macro_year[:cut] + none,
            "carried": e.carried[:cut] + (False,) * horizon,
            "weight_macro": e.weight_macro[:cut] + none,
            "weight_market": e.weight_market[:cut] + none,
            "weight_cycle": e.weight_cycle[:cut] + none,
            "market": e.market[:cut] + none,
            "current": describe(path[-1], reading, projected[-1]),
            "notes": tuple(e.notes) + (f"{note} (start: its distribution of {base.dates[last]})",),
        }))

    markets: list[MarketRegime] = []
    market_cov: list[MarketCoverage] = []
    base_cov = {m.code: m for m in base.coverage.markets}
    for m in base.markets:
        blended: list[Optional[np.ndarray]] = []
        for k in range(horizon):
            if any(c not in rows_by for c in m.weights):
                blended.append(None)
                continue
            acc = np.zeros(sc.N_STATES)
            for c, w in m.weights.items():
                acc += w * rows_by[c][k]
            blended.append(acc / acc.sum())
        dist = m.distribution[:cut] + tuple(_tuple(r) for r in blended)
        last = next((k for k in range(len(dates) - 1, -1, -1) if dist[k] is not None), None)
        markets.append(MarketRegime(
            code=m.code, weights=dict(m.weights), distribution=dist,
            state=m.state[:cut] + tuple(None if r is None else mean_state(r) for r in blended),
            modal_state=m.modal_state[:cut] + tuple(None if r is None else modal_state(r) for r in blended),
            current=None if last is None else describe(np.asarray(dist[last]), reading, dates[last])))
        assessed = sum(d is not None for d in dist)
        absent = base_cov[m.code].economies_absent if m.code in base_cov else ()
        market_cov.append(MarketCoverage(code=m.code, economies_absent=absent, dates_assessed=assessed,
                                         dates_unassessed=len(dates) - assessed))

    coverage = CoverageReport(
        economies=tuple(c.model_copy(update={"dates_assessed": c.dates_assessed + horizon})
                        if c.code in rows_by else c for c in base.coverage.economies),
        markets=tuple(market_cov),
        economies_skipped=dict(base.coverage.economies_skipped),
        snapshot_mismatch=base.coverage.snapshot_mismatch,
        warnings=tuple(base.coverage.warnings) + (
            f"scenario Regime: {horizon} projected months ({projected[0]} to {projected[-1]}) under the "
            f"{policy} policy of Scenario_SAA.m on {base.regime_id}; {projected[-1]}, the target reached, "
            "represents the scenario (AGG-20)",),
    )
    scenario = ScenarioProvenance(
        policy=policy, base_regime_id=base.regime_id, base_artefact_id=base.artefact_id,
        horizon_months=horizon, template_sha256=sc.TEMPLATE_SHA256,
        target_mix=dict(zip(sc.MIX_PHASES, spec.target_mix)), base_as_of=history[-1],
        projected_from=projected[0], scenario_date=projected[-1], rule_version=sc.SCENARIO_RULE_VERSION)
    prov = {f: getattr(base.provenance, f) for f in Provenance.model_fields}
    prov.update(as_of=projected[-1], idempotency_key=key, regime_id=rid, scenario=scenario,
                upstream={**base.provenance.upstream, "scenario:base_regime": base.regime_id,
                          "scenario:base_artefact": base.artefact_id, "scenario:policy": policy,
                          "scenario:template_sha256": sc.TEMPLATE_SHA256})
    provenance = Provenance(**prov)
    body = dict(regime_id=rid, optimism_scale=base.optimism_scale, dates=dates, economies=tuple(economies),
                markets=tuple(markets), coverage=coverage, provenance=provenance)
    draft = Regime(artefact_id="", **body)
    # the derived inflation fields (AGG-24) are not hashed: the id of every scenario Regime issued
    # before them stays
    return Regime(artefact_id=content_id("AGG", draft.model_dump(mode="json", context=STORED)), **body)


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "AGG-02: the Guide mandates PostgreSQL; a driver is unavoidable (as honi D-05)"}


def allowlist_report() -> dict[str, Any]:
    """Runtime dependencies from pyproject.toml, checked against the allowlist."""
    with (ROOT / "pyproject.toml").open("rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]
    packages = {}
    for requirement in declared:
        name = re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        packages[name] = {"requirement": requirement, "installed": installed,
                          "allowed": name in ALLOWLIST, "admitted_by": ADMITTED.get(name)}
    ok = all(p["allowed"] or p["admitted_by"] for p in packages.values())
    return {"ok": ok, "packages": packages}
