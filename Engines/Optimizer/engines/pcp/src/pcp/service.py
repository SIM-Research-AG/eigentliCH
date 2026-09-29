"""Orchestration: the only module that touches the store, the upstream clients and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and never calls out.
A run:

1. Resolves the request against ``config.yaml`` (speed mode, calibration) and computes the idempotency key
   from the regime id, the return set id, the mandate, its reporting currency, its basis (when real), the
   month, the speed mode, the calibration's content hash and the engine and contract versions. A key already answered is answered
   again, free.
2. Reads the Regime from ``aggregation``, the ReturnSet in the mandate's currency and on its basis, and the
   instrument register from ``fmre``, and refuses, before any solve (every refusal names its reason):
   * a ``return_set_id`` other than the one ``fmre`` serves;
   * a ReturnSet whose ``regime_id`` is not the requested one, including one that carries none: strict,
     no interim acceptance (owner, 28.09.2026, PCP-11; Engine Building Guide section 4);
   * a ReturnSet measured in another currency than the mandate's, including one that states none: strict,
     like the ``regime_id`` rule (PCP-18, PCP-19). The one exception is fmre's hard-currency fallback on a
     real set (PCP-23): accepted only when its ``from`` is the mandate's currency and its ``to`` the served
     one, and then stated on the Allocation; a fallback that does not match is refused;
   * a ReturnSet on another basis than the mandate's (a set that states none is nominal), or a real set whose
     deflator labels a state ``not_computable`` (PCP-22);
   * profiles in another unit than the mandate's curve, or a horizon other than one year;
   * a universe instrument ``fmre`` does not publish, or one that cannot be classified;
   * a mandate that is structurally infeasible.
3. Blends the client's regime distribution, solves, and publishes an Allocation only from a converged solve
   whose raw weights meet the budget (Manual section 22: nothing is published from an unconverged solve).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Optional

import numpy as np
from pydantic import ValidationError

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import constraints as cons
from . import engine
from . import store as st
from .clients import (AggregationClient, FmreClient, NotComputableUpstream, NotFoundUpstream, UpstreamError,
                      checksum)
from .contracts import (
    CONTRACT_VERSIONS,
    Allocation,
    Calibration,
    Coverage,
    Curves,
    Diagnostics,
    InstrumentWeight,
    Mandate,
    PCPRunRequest,
    PortfolioMap,
    Provenance,
    Regime,
    ReturnSet,
    RunAccepted,
    RunStatus,
    ValidationReport,
    check_fallback,
)
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


class Unavailable(RuntimeError):
    """An upstream engine is needed and is not there."""


class Refused(ValueError):
    """The inputs are valid on their own and cannot be optimised together. The message says why."""


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def mandate_id(mandate: Mandate) -> str:
    return content_id("MAN", mandate.model_dump(mode="json"))


def served_currency(rs: ReturnSet) -> Optional[str]:
    """The currency a ReturnSet states its instrument profiles are measured in, or ``None``.

    fmre's structured ``provenance.currency`` wins when it is there. fmre does not publish one yet: until it
    does, pcp reads the opt-in note fmre writes on every converted set (``... in currency=CHF; ...``, PCP-19).
    A set whose field and notes disagree, or whose notes name more than one currency, states none.
    """
    field, noted = rs.provenance.currency, rs.provenance.noted_currencies()
    if field is not None:
        return field if not noted or noted == (field,) else None
    return noted[0] if len(noted) == 1 else None


def served_basis(rs: ReturnSet) -> str:
    """The basis a ReturnSet states its instrument profiles are on. A set without ``provenance.basis`` is
    nominal: fmre's default, and every set it served before the real view (PCP-22)."""
    return rs.provenance.basis if rs.provenance.basis is not None else "nominal"


def deflator_summary(rs: ReturnSet) -> tuple[str, dict[str, int], Optional[str]]:
    """fmre's deflator on a real set (its ``Deflator``: ``currency``, ``index``, ``method``, ``labels`` per
    state, ``hard_currency_fallback``, ``scenario``), as reported: ``(what, label -> number of states,
    hard-currency fallback)``. Read as fmre publishes it, never recomputed (PCP-22)."""
    d = rs.provenance.deflator or {}
    counts: dict[str, int] = {}
    for label in d.get("labels") or ():
        counts[str(label)] = counts.get(str(label), 0) + 1
    what = " ".join(str(d[k]) for k in ("currency", "index") if d.get(k)) or "no deflator stated"
    if d.get("method"):
        what += f" ({d['method']})"
    if d.get("scenario"):
        what += f", scenario {d['scenario']}"
    fb = d.get("hard_currency_fallback")
    if isinstance(fb, dict):
        fallback = (f"{fb.get('from', '?')} to {fb.get('to', '?')}"
                    + (f", states {fb['states']}" if fb.get("states") else "")
                    + (f": {fb['reason']}" if fb.get("reason") else ""))
    else:
        fallback = str(fb) if fb else None
    return what, counts, fallback


def accepted_fallback(rs: ReturnSet, mandate: Mandate, served: Optional[str]) -> Optional[dict[str, Any]]:
    """PCP-23: the currency check with fmre's hard-currency fallback (decision 5 of the real view).

    When the mandate's currency's inflation leaves fmre's band (-20 % to +100 %) in a state, fmre measures the
    real set in CHF, then USD, and says so: ``provenance.currency`` is the hard currency and
    ``provenance.deflator.hard_currency_fallback`` is ``{from, to, states, reason}``. Such a set is accepted
    only when the mandate and the set are real, ``from`` is the mandate's currency, ``to`` the served one, and
    the deflator's currency (when stated) the served one. Returns the fallback as fmre wrote it, ``None`` when
    the set is in the mandate's currency without one; raises :class:`Refused` on every other mismatch.
    """
    fb = (rs.provenance.deflator or {}).get("hard_currency_fallback")
    if served == mandate.currency and fb is None:
        return None
    rid = rs.return_set_id
    if served != mandate.currency and (fb is None or mandate.basis != "real" or served_basis(rs) != "real"):
        raise Refused(
            f"ReturnSet {rid} is measured in {served or 'no stated currency'}, not the mandate's "
            f"{mandate.currency}; a ReturnSet in another currency than the mandate's is refused (PCP-18)"
            + ("; fmre has not stated a currency on this set (the unconverted source-currency default "
               "states none)" if served is None else "")
            + ("; these are fmre's unconverted source-currency profiles" if served == "source" else "")
            + ("; it states no hard-currency fallback, the only case another currency is accepted in (PCP-23)"
               if fb is None and mandate.basis == "real" and served not in (None, "source") else "")
            + ("; a hard-currency fallback is accepted on a real mandate and a real set only (PCP-23)"
               if fb is not None else ""))
    what = f"ReturnSet {rid} states a hard-currency fallback {fb!r}"
    if not isinstance(fb, dict):
        raise Refused(f"{what}, not fmre's {{from, to, states, reason}}; refused (PCP-23)")
    try:
        check_fallback(fb)
    except ValueError as exc:
        raise Refused(f"{what}: {exc}; refused (PCP-23)") from exc
    if fb["from"] != mandate.currency:
        raise Refused(f"{what} from {fb['from']}, not from the mandate's {mandate.currency}; only a fallback "
                      "from the mandate's currency is accepted (PCP-23)")
    if fb["to"] != served:
        raise Refused(f"{what} to {fb['to']}, but the set is measured in {served or 'no stated currency'}; "
                      "the fallback's currency must be the one the set is measured in (PCP-23)")
    deflated_in = (rs.provenance.deflator or {}).get("currency")
    if deflated_in is not None and deflated_in != served:
        raise Refused(f"ReturnSet {rid} is measured in {served} but deflated in {deflated_in}; a hard-currency "
                      "fallback is accepted only when both are the fallback's currency (PCP-23)")
    return fb


def fallback_warning(fb: dict[str, Any]) -> str:
    """The plain-words statement every Allocation and ValidationReport on a hard-currency fallback carries."""
    return (f"real, measured in {fb['to']} because {fb['from']} inflation left the computable band (fmre's "
            f"-20 % to +100 %) in states {fb['states']}: every return figure in this Allocation is real "
            f"{fb['to']}, not real {fb['from']}, and the mandate's real target curve is fitted against the real "
            f"{fb['to']} profiles. fmre: {fb['reason']} (PCP-23)")


@dataclass(frozen=True)
class Prepared:
    """Everything a solve needs, after every check that does not need a solution."""

    calibration: Calibration
    regime: Regime
    return_set: ReturnSet
    names: dict[str, str]
    coverage: dict[str, str]
    sources: dict[str, dict[str, str]]
    problem: engine.Problem
    blend: engine.BlendedRegime
    warnings: tuple[str, ...]
    #: The currency every return figure is measured in: the mandate's, or the hard currency (PCP-23).
    currency: str = "CHF"
    #: fmre's ``{from, to, states, reason}`` when the set is on a hard-currency fallback (PCP-23).
    hard_currency_fallback: Optional[dict[str, Any]] = None


class Service:
    def __init__(self, settings: Settings, store: st.Store, aggregation: AggregationClient, fmre: FmreClient):
        self.settings = settings
        self.store = store
        self.aggregation = aggregation
        self.fmre = fmre
        self.started = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    def startup(self) -> None:
        """Create tables, write the seed calibrations, and check the active one exists."""
        self.store.initialise()
        with self.store.session() as conn:
            for cal in seeds.SEEDS:
                try:
                    st.put_calibration(conn, version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                                       parent_version=cal.parent_version, payload_json=seeds.canonical_json(cal))
                except st.StoreConflict as exc:
                    raise st.StoreError(
                        f"seed calibration {cal.version} in calibration.py no longer matches the stored one. "
                        "Seeds are immutable: give the change a new version.") from exc
            if st.get_calibration(conn, self.settings.active_calibration) is None:
                raise st.StoreError(f"config.yaml names active calibration {self.settings.active_calibration!r}, "
                                    "which is not in the store")

    # -- standard endpoints ------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self, allowlist: dict[str, Any]) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
        return {
            "engine": ENGINE, "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": self.settings.active_calibration, "calibration_versions": versions,
            "default_speed": self.settings.default_speed, "allowlist": allowlist,
            "upstream": {"aggregation": self.settings.aggregation_url, "fmre": self.settings.fmre_url},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
        }

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
        with self.store.session() as conn:
            if proposal.parent_version and st.get_calibration(conn, proposal.parent_version) is None:
                raise InvalidRequest(f"parent_version {proposal.parent_version!r} does not exist")
            try:
                created = st.put_calibration(conn, version=proposal.version,
                                             calibration_hash=seeds.calibration_hash(proposal),
                                             parent_version=proposal.parent_version,
                                             payload_json=seeds.canonical_json(proposal))
            except st.StoreConflict as exc:
                raise Conflict(str(exc)) from exc
        return proposal, created

    # -- preparing a run ---------------------------------------------------

    def _speed(self, request: PCPRunRequest) -> str:
        return request.speed_mode or self.settings.default_speed

    def prepare(self, request: PCPRunRequest) -> Prepared:
        """Read every input and run every check that needs no solution. Raises :class:`Refused`,
        :class:`InvalidRequest` or :class:`Unavailable`."""
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        m = request.mandate
        try:
            regime = self.aggregation.regime(request.regime_id)
        except NotFoundUpstream as exc:
            raise Refused(f"aggregation has no regime {request.regime_id!r}") from exc
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        try:
            rs = self.fmre.return_set(request.regime_id, m.currency, m.basis)
            register = {r.instrument_id: r for r in self.fmre.instruments()}
        except NotComputableUpstream as exc:
            raise Refused(f"fmre states the real view in {m.currency} is not_computable: {exc}; a real mandate "
                          "cannot be fitted without it (PCP-22)") from exc
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc

        if rs.return_set_id != request.return_set_id:
            raise Refused(f"fmre serves ReturnSet {rs.return_set_id}, not {request.return_set_id}; fmre serves "
                          "its current set only, so the request must name that one")
        if rs.provenance.regime_id != request.regime_id:
            stamped = rs.provenance.regime_id
            raise Refused(
                f"ReturnSet {rs.return_set_id} was estimated under regime_id {stamped!r}, not "
                f"{request.regime_id!r}; a ReturnSet whose regime_id differs from the Regime it is optimised "
                "against is refused (Engine Building Guide section 4)"
                + ("; fmre has not stamped a regime_id on this set" if stamped is None else ""))
        served = served_currency(rs)
        hard_fb = accepted_fallback(rs, m, served)       # PCP-18, PCP-19, PCP-23: raises on a mismatch
        basis = served_basis(rs)
        if basis != m.basis:
            raise Refused(
                f"ReturnSet {rs.return_set_id} is on the {basis} basis, not the mandate's {m.basis}; the target "
                f"curve is {m.basis} and a ReturnSet on another basis is refused (PCP-22)"
                + ("; fmre states no basis on this set, which counts as nominal"
                   if rs.provenance.basis is None else ""))
        if m.basis == "real":
            _, counts, _ = deflator_summary(rs)
            if counts.get("not_computable"):
                raise Refused(f"ReturnSet {rs.return_set_id}'s deflator labels {counts['not_computable']} states "
                              "not_computable: no real view is defined there, so the real target curve cannot be "
                              "fitted (PCP-22)")
        if abs(m.horizon_years - 1.0) > 1e-12:
            raise Refused(f"the mandate's horizon is {m.horizon_years} years; the profiles are annual and pcp "
                          "does not compound them to another horizon")

        profiles = {p.key: p for p in rs.instrument_profiles if p.kind == "instrument"}
        missing = [i for i in m.universe if i not in profiles or i not in register]
        if missing:
            raise Refused(f"fmre publishes no active instrument profile for {missing}")
        units = {profiles[i].unit for i in m.universe}
        if units != {m.curve_unit}:
            raise Refused(f"the profiles are in {sorted(units)} but the mandate's curve is in {m.curve_unit!r}; "
                          "the fit would be off by the unit ratio")

        ids = tuple(m.universe)
        attrs, sources = [], {}
        for iid in ids:
            a, s = engine.raw_attributes(register[iid], cal.classification.get(iid))
            attrs.append(a)
            sources[iid] = s
        labels, scenarios, esg, problems = engine.classify(attrs, ids, cal)
        if problems:
            raise Refused("the universe cannot be classified: " + "; ".join(problems))

        try:
            weights = engine.economy_weights(regime, m.regime_weights, m.regime_market)
            blend = engine.blend_regime(regime, weights, request.date)
        except engine.EngineError as exc:
            raise Refused(str(exc)) from exc

        problem = engine.Problem(
            ids=ids, labels=labels, home_scenarios=scenarios, esg=esg,
            profiles=np.asarray([[s.value for s in profiles[i].states] for i in ids], dtype=float),
            target=np.asarray(m.target_curve, dtype=float), regime=blend.vector,
            bounds={d: {label: (b.lower, b.upper) for label, b in cats.items()} for d, cats in m.bounds.items()},
            esg_min=m.esg_min, max_single_position=m.max_single_position,
            fixed=tuple(m.fixed_allocations.get(i, 0.0) for i in ids))
        warnings: list[str] = []
        if hard_fb is not None:
            warnings.append(fallback_warning(hard_fb))
        if m.basis == "real":
            what, counts, fallback = deflator_summary(rs)
            labels = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no per-state labels stated"
            warnings.append(f"real basis: the target curve and every profile are net of inflation, deflated by "
                            f"fmre with {what}; states: {labels}"
                            + (f"; hard-currency fallback {fallback}" if fallback else "") + " (PCP-22)")
        if len(set(esg)) == 1:
            warnings.append(f"every instrument carries the same ESG score ({esg[0]}), so the ESG row cannot "
                            "discriminate (PCP-06)")
        return Prepared(calibration=cal, regime=regime, return_set=rs,
                        names={i: register[i].name for i in ids},
                        coverage={i: profiles[i].coverage for i in ids}, sources=sources, problem=problem,
                        blend=blend, warnings=tuple(warnings), currency=served,
                        hard_currency_fallback=hard_fb)

    def validate(self, request: PCPRunRequest) -> ValidationReport:
        """``POST /validate``: every check short of solving. Problems are reported, not raised."""
        mid = mandate_id(request.mandate)
        base = dict(mandate_id=mid, regime_id=request.regime_id, return_set_id=request.return_set_id,
                    currency=request.mandate.currency, basis=request.mandate.basis)
        try:
            prepared = self.prepare(request)
        except Refused as exc:
            return ValidationReport(ok=False, date=None, universe_size=len(request.mandate.universe),
                                    constraint_rows=0, problems=(str(exc),), **base)
        try:
            system = engine.constraint_system(prepared.problem, prepared.calibration)
        except ValueError as exc:
            return ValidationReport(ok=False, date=prepared.blend.date, universe_size=len(prepared.problem.ids),
                                    constraint_rows=0, problems=(str(exc),), **base)
        problems = system.feasibility_problems()
        return ValidationReport(ok=not problems, date=prepared.blend.date,
                                universe_size=len(prepared.problem.ids), constraint_rows=system.n_rows,
                                problems=tuple(problems), notes=prepared.warnings,
                                hard_currency_fallback=prepared.hard_currency_fallback, **base)

    # -- runs --------------------------------------------------------------

    def idempotency_key(self, request: PCPRunRequest, cal: Calibration) -> str:
        payload = {
            "regime_id": request.regime_id, "return_set_id": request.return_set_id,
            "mandate": request.mandate.model_dump(mode="json"), "currency": request.mandate.currency,
            "date": request.date,
            "speed_mode": self._speed(request), "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
        }
        # PCP-22: the basis enters explicitly (and through the mandate and fmre's return_set_id) when real; a
        # nominal request keeps the key it had before the field existed. PCP-23: a hard-currency fallback enters
        # through the return_set_id, which fmre derives from the asked currency, the served one and the fallback
        # (its identity ``deflator.fallback``); it is only known once fmre answers, after the key is looked up.
        if request.mandate.basis != "nominal":
            payload["basis"] = request.mandate.basis
        return content_id("IDK", payload)

    def submit(self, request: PCPRunRequest) -> RunAccepted:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        key = self.idempotency_key(request, cal)
        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded", artefact_id=done["artefact_id"],
                               regime_id=request.regime_id, idempotency_key=key, cached=True)

        started_at = st.utc_now()
        run_id = content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                    "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, status="running", started_at=started_at,
                          request_json=request.model_dump_json())
        try:
            allocation = self._execute(request, key)
        except (Refused, Unavailable, engine.EngineError, ValidationError, ValueError) as exc:
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", coverage_json=None, provenance_json=None,
                              error=f"{type(exc).__name__}: {exc}")
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None, regime_id=request.regime_id,
                               idempotency_key=key, cached=False)

        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=allocation.artefact_id, regime_id=allocation.regime_id,
                            return_set_id=allocation.return_set_id, mandate_id=allocation.mandate_id,
                            idempotency_key=key, contract_version=allocation.contract_version,
                            payload_json=allocation.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=allocation.artefact_id,
                          warnings_json=json.dumps(list(allocation.coverage.warnings)),
                          coverage_json=allocation.coverage.model_dump_json(),
                          provenance_json=allocation.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=allocation.artefact_id,
                           regime_id=request.regime_id, idempotency_key=key, cached=False)

    def _execute(self, request: PCPRunRequest, key: str) -> Allocation:
        prepared = self.prepare(request)
        speed = self._speed(request)
        outcome = engine.optimise(prepared.problem, prepared.calibration, speed)
        return build_allocation(request, prepared, outcome, speed, key)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        request = PCPRunRequest.model_validate_json(row["request_json"])
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=request, artefact_id=row["artefact_id"], regime_id=request.regime_id,
            warnings=tuple(json.loads(row["warnings_json"])),
            coverage=Coverage.model_validate_json(row["coverage_json"]) if row["coverage_json"] else None,
            provenance=Provenance.model_validate_json(row["provenance_json"]) if row["provenance_json"] else None,
            error=row["error"])

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, max(1, min(limit, 500)))
        out = []
        for r in rows:
            req = json.loads(r.pop("request_json"))
            out.append({**r, "client": req["mandate"]["client"], "mandate": req["mandate"]["name"],
                        "speed_mode": req.get("speed_mode"), "calibration_version": req.get("calibration_version")})
        return out

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> Allocation:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no allocation {artefact_id!r}")
        return Allocation.model_validate_json(payload)

    def allocation_map(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        return {"artefact_id": a.artefact_id, "regime_id": a.regime_id, **a.portfolio_map.model_dump(),
                "notice": a.notice}

    def allocation_roles(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        role_bounds = {}
        mandate_bounds = self._request_for(a).mandate.bounds.get("role", {})
        for role in a.weights_by_role:
            b = mandate_bounds.get(role)
            role_bounds[role] = {"lower": b.lower if b else 0.0, "upper": b.upper if b else 1.0}
        return {"artefact_id": a.artefact_id, "regime_id": a.regime_id, "weights_by_role": a.weights_by_role,
                "bounds": role_bounds, "notice": a.notice}

    def allocation_diagnostics(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        return {"artefact_id": a.artefact_id, "regime_id": a.regime_id, "raw_weight_sum": a.raw_weight_sum,
                "budget_met": a.budget_met, **a.diagnostics.model_dump(), "coverage": a.coverage.model_dump(),
                "notice": a.notice}

    def _request_for(self, allocation: Allocation) -> PCPRunRequest:
        with self.store.session() as conn:
            row = conn.execute("SELECT request_json FROM run WHERE artefact_id = %s ORDER BY started_at LIMIT 1",
                               (allocation.artefact_id,)).fetchone()
        if row is None:
            raise NotFound(f"no run published allocation {allocation.artefact_id!r}")
        return PCPRunRequest.model_validate_json(row["request_json"])

    def constraints(self, version: Optional[str] = None) -> dict[str, Any]:
        """``GET /constraints``: the 75-row block as the calibration lays it out, bounds at their defaults."""
        cal = self.calibration(version)
        rows = cons.layout(cal.vocabularies)
        return {"calibration_version": cal.version, "n_rows": len(rows),
                "rows": [r.model_dump() for r in rows],
                "starts": {d: next(r.row for r in rows if r.dimension == d)
                           for d in dict.fromkeys(r.dimension for r in rows)},
                "notice": "Floor then ceiling per bucket; ESG (row 57) is a floor only (Manual section 15.2)."}


def build_allocation(request: PCPRunRequest, prepared: Prepared, outcome: engine.Outcome, speed: str,
                     key: str) -> Allocation:
    """The Allocation from one solve. Refuses an unconverged or budget-breaking solution."""
    if not outcome.solve.success:
        tried = "; ".join(outcome.solve.notes)
        raise engine.EngineError(f"the solve did not converge ({outcome.solve.status}); nothing is published "
                                 "from an unconverged solve (Manual section 22). The mandate passed the joint "
                                 "feasibility check, so this is the solver's failure, not an infeasible mandate"
                                 + (f". Tried: {tried}" if tried else ""))
    if not outcome.budget_met:
        raise engine.EngineError(f"the mandate is infeasible: the solver's raw weights sum to {outcome.raw_sum:.6f}, "
                                 "not one; renormalising would hide it (Manual section 15.2)")
    m, cal, p = request.mandate, prepared.calibration, prepared.problem
    weak = set(cal.weak_methods)
    weak_share = float(sum(w for w, i in zip(outcome.weights, p.ids) if prepared.coverage[i] in weak))
    warnings = list(prepared.warnings) + list(outcome.notes)
    if weak_share > 0:
        warnings.append(f"{weak_share:.1%} of the weight is on instruments whose profiles rest on borrowed or "
                        "seeded values (PCP-07)")
    mid = mandate_id(m)
    regime, rs = prepared.regime, prepared.return_set
    upstream = {"aggregation:artefact": regime.artefact_id,
                "aggregation:calibration": regime.provenance.calibration_version,
                "aggregation:optimism": regime.optimism_scale, "aggregation:sha256": checksum(regime),
                "fmre:return_set": rs.return_set_id, "fmre:calibration": rs.provenance.calibration_id,
                "fmre:engine": rs.engine_version, "fmre:currency": served_currency(rs) or "",
                "fmre:sha256": checksum(rs)}
    if m.basis != "nominal":        # PCP-22: a nominal Allocation keeps its bytes
        what, _, fallback = deflator_summary(rs)
        upstream.update({"fmre:basis": served_basis(rs), "fmre:deflator": what,
                         "fmre:hard_currency_fallback": fallback or ""})
    currency = prepared.currency        # the mandate's, or the hard currency of a fallback (PCP-23)
    provenance = Provenance(
        regime_id=request.regime_id, return_set_id=rs.return_set_id, currency=currency, basis=m.basis,
        hard_currency_fallback=prepared.hard_currency_fallback,
        snapshot_id=regime.provenance.snapshot_id,
        as_of=regime.provenance.as_of, date=prepared.blend.date, upstream=upstream,
        regime_weights=prepared.blend.weights, regime_market=m.regime_market, mandate_id=mid,
        engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS, calibration_version=cal.version,
        calibration_hash=seeds.calibration_hash(cal), idempotency_key=key, speed_mode=speed)
    body = dict(
        regime_id=request.regime_id, return_set_id=rs.return_set_id, currency=currency, basis=m.basis,
        mandate_id=mid,
        client=m.client,
        mandate_name=m.name, date=prepared.blend.date, speed_mode=speed, calibration_version=cal.version,
        instruments=tuple(InstrumentWeight(instrument_id=i, name=prepared.names[i], role=p.labels["role"][j],
                                           weight=float(outcome.weights[j]), raw_weight=float(outcome.raw_weights[j]),
                                           coverage=prepared.coverage[i]) for j, i in enumerate(p.ids)),
        raw_weight_sum=outcome.raw_sum, budget_met=outcome.budget_met, weights_by_role=outcome.by_role,
        portfolio_map=PortfolioMap(roles=cal.vocabularies.role, scenarios=cal.vocabularies.scenario,
                                   grid=outcome.grid),
        curves=Curves(target=tuple(float(v) for v in p.target), achieved=tuple(float(v) for v in outcome.achieved),
                      shortfall_by_state=tuple(float(v) for v in outcome.shortfall),
                      regime=tuple(float(v) for v in p.regime)),
        diagnostics=Diagnostics(objective=outcome.objective, objective_floor=outcome.floor,
                                weight_leverage=outcome.leverage, solver_method=outcome.solve.method,
                                solver_status=outcome.solve.status, iterations=outcome.solve.iterations,
                                success=outcome.solve.success, constraint_rows=outcome.rows,
                                binding=outcome.binding, exposures=outcome.exposures, esg=outcome.esg,
                                notes=outcome.notes),
        coverage=Coverage(profile_methods=dict(prepared.coverage), weight_on_weak_profiles=weak_share,
                          warnings=tuple(dict.fromkeys(warnings))),
        provenance=provenance,
    )
    draft = Allocation(artefact_id="", **body)
    return Allocation(artefact_id=content_id("PCP", draft.model_dump(mode="json")), **body)


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "PCP-02: the Guide mandates PostgreSQL; a driver is unavoidable (as honi D-05)"}


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
    return {"ok": all(p["allowed"] or p["admitted_by"] for p in packages.values()), "packages": packages}
