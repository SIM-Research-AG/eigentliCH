"""Orchestration: the only module that touches the store, the upstream clients and the model together.

``api.py`` routes here and nowhere else. ``POST /run``:

1. Resolves the calibration (the request's, else the active one) and reads the sheet, its request and the lbs
   records it names (3.8). Builds the findings (pure) and keys them (3.9); a key already stored is reused.
2. With an Allocation, reads pcp, aggregation and fmre, checks them (3.8, LBSIM-14, LBSIM-15), resolves the
   stated plan and the horizon, keys the paths and simulates them (pure, seconds). A key already stored is reused.
3. Records the outlook run (``kind outlook``, synchronous), supersedes the client's older plan runs, and queues
   the plan run (``kind plan``) for the workers unless ``optimise`` is ``no``.

The API process never imports ``lbsim.optim`` or casadi (LBSIM-03): the plan is computed by ``lbsim.worker``.
"""

from __future__ import annotations

import json
import re
import time
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from typing import Any, Optional

from . import ENGINE, ENGINE_VERSION
from . import calibration as seeds
from . import store as st
from . import upstream as U
from .adapter import AdapterError
from .clients import Upstream
from .contracts import (CONTRACT_VERSIONS, NOTICE, UPSTREAM_CONTRACTS, Calibration, LbsRequest, LbsSheet,
                        LifeBalanceFindings, LifeBalanceOutlook, LifeBalancePaths, LifeBalancePlan,
                        LifeBalanceSimRequest, NotMade, OptimiseRequest, PlanOutlook, Progress, RequestedBy,
                        RunAccepted, RunStatus, ValidationReport, Words)
from .errors import Conflict, InvalidRequest, LbsimError, NotFound
from .fast.build import build_findings
from .ids import content_id
from .paths.build import build_paths, fan, paths_key
from .paths.household import PlanError, StatedPlan, stated_plan
from .plan import plan_key
from .settings import ROOT, Settings

KINDS = {"LSF": ("findings", LifeBalanceFindings), "LSP": ("paths", LifeBalancePaths),
         "LSO": ("plan", LifeBalancePlan)}

NOT_MADE_TEXT = {
    "no_allocation": Words(de="Ohne Allokation gibt es keine simulierten Verläufe und keine Planrechnung.",
                           en="Without an allocation there are no simulated paths and no plan calculation."),
    "draft_market": Words(de="Diese Kalibrierung bildet den Entwurf nach und simuliert keine Verläufe auf einer "
                             "Allokation.",
                          en="This calibration reproduces the draft and simulates no paths on an allocation."),
    "not_requested": Words(de="Eine Planrechnung wurde nicht verlangt.",
                           en="No plan calculation was asked for."),
    "no_goal": Words(de="Kein datiertes Ziel liegt im Horizont, also hat die Planrechnung nichts zu finanzieren.",
                     en="No dated goal lies within the horizon, so the plan calculation has nothing to fund."),
}

PLAN_REASON = {
    "timed_out": Words(de="Die Planrechnung hat die zwei Stunden überschritten und liefert deshalb keine Zahlen.",
                       en="The plan calculation ran past its two hours and therefore gives no figures."),
    "superseded": Words(de="Eine neuere Rechnung für diesen Haushalt hat diese Planrechnung ersetzt.",
                        en="A newer calculation for this household replaced this plan calculation."),
    "cancelled": Words(de="Die Planrechnung wurde abgebrochen.", en="The plan calculation was cancelled."),
    "solver": Words(de="Die Planrechnung hat für diesen Haushalt kein verlässliches Ergebnis gefunden.",
                    en="The plan calculation found no reliable result for this household."),
    "upstream": Words(de="Die Grundlagen der Planrechnung haben sich geändert; eine neue Rechnung ist nötig.",
                      en="The inputs of the plan calculation have changed; a new calculation is needed."),
}
WAITING = Words(de="Für die Planrechnung fehlt eine Allokation auf der heutigen Einschätzung.",
                en="The plan calculation waits for an allocation on the current assessment.")


def iso_seconds_since(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    return round((datetime.now(timezone.utc) - datetime.fromisoformat(text)).total_seconds(), 3)


@dataclass
class Inputs:
    """Everything a run reads, read once."""

    calibration: Calibration
    sheet: LbsSheet
    sheet_raw: dict[str, Any]
    request: LbsRequest
    records: dict[str, dict[str, Any]]
    findings: LifeBalanceFindings
    bundle: Optional[U.MarketBundle] = None
    plan: Optional[StatedPlan] = None


class Service:
    def __init__(self, settings: Settings, store: st.Store, upstream: Optional[Upstream] = None):
        self.settings = settings
        self.store = store
        self.upstream = upstream or Upstream.from_config(settings.upstream)
        self.started = time.monotonic()

    # -- lifecycle ------------------------------------------------------------------------------------------

    def startup(self) -> None:
        self.store.initialise()
        with self.store.session() as conn:
            for cal in seeds.SEEDS:
                try:
                    st.put_calibration(conn, version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                                       parent_version=cal.parent_version, payload_json=seeds.canonical_json(cal))
                except st.StoreConflict as exc:
                    raise st.StoreError(f"seed calibration {cal.version} in calibration.py no longer matches the "
                                        "stored one. Seeds are immutable: give the change a new version.") from exc
            if st.get_calibration(conn, self.settings.active_calibration) is None:
                raise st.StoreError(f"config.yaml names active calibration {self.settings.active_calibration!r}, "
                                    "which is not in the store")

    def requeue_stale(self) -> list[tuple[str, str]]:
        o = self.settings.optimiser
        with self.store.session() as conn:
            return st.requeue_stale(conn, stale_after_s=o.stale_after_s, max_attempts=o.max_attempts)

    # -- standard ---------------------------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
            queue = conn.execute("SELECT status, count(*) AS n FROM run WHERE kind = 'plan' GROUP BY status"
                                 ).fetchall()
        return {"engine": ENGINE, "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
                "upstream_contracts": UPSTREAM_CONTRACTS, "calibration_version": self.settings.active_calibration,
                "calibration_versions": versions, "allowlist": allowlist_report(),
                "upstream": self.upstream.describe(), "store": {**self.store.config.describe(), "counts": counts},
                "plan_queue": {r["status"]: r["n"] for r in queue},
                "simulation": self.settings.simulation.__dict__, "optimiser": self.settings.optimiser.__dict__,
                "config_sources": list(self.settings.sources), "notice": NOTICE}

    def calibration(self, version: Optional[str] = None) -> Calibration:
        version = version or self.settings.active_calibration
        with self.store.session() as conn:
            payload = st.get_calibration(conn, version)
        if payload is None:
            raise NotFound(f"lbsim has no calibration {version!r}.")
        return Calibration.model_validate_json(payload)

    def calibration_versions(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_calibrations(conn)
        return [{**r, "active": r["version"] == self.settings.active_calibration} for r in rows]

    def propose_calibration(self, proposal: Calibration) -> tuple[Calibration, bool]:
        with self.store.session() as conn:
            if proposal.parent_version and st.get_calibration(conn, proposal.parent_version) is None:
                raise InvalidRequest(f"The parent calibration {proposal.parent_version!r} does not exist.")
            try:
                created = st.put_calibration(conn, version=proposal.version,
                                             calibration_hash=seeds.calibration_hash(proposal),
                                             parent_version=proposal.parent_version,
                                             payload_json=seeds.canonical_json(proposal))
            except st.StoreConflict as exc:
                raise Conflict(f"Calibration {proposal.version} already exists with other figures; a changed "
                               "calibration is a new version.") from exc
        return proposal, created

    # -- reading and computing --------------------------------------------------------------------------------

    def _calibration_for(self, version: Optional[str]) -> Calibration:
        try:
            return self.calibration(version)
        except NotFound as exc:
            raise InvalidRequest(exc.message) from exc

    def read_findings(self, sheet_id: str, client_ref: str, cal: Calibration) -> Inputs:
        sheet, raw, req, records = self.upstream.read_sheet(sheet_id, client_ref)
        try:
            findings = build_findings(sheet, req.request, records, cal, sheet_sha256=_sha(raw),
                                      lbs_url=self.upstream.lbs.url)
        except AdapterError as exc:
            raise InvalidRequest(f"lbsim cannot read this Life Balance Sheet: {exc}.") from exc
        return Inputs(calibration=cal, sheet=sheet, sheet_raw=raw, request=req.request, records=records,
                      findings=findings)

    def read_market(self, inputs: Inputs, allocation_id: str, scenarios: Optional[tuple[str, ...]]
                    ) -> U.MarketBundle:
        up, cal = self.upstream, inputs.calibration
        alloc_raw = up.pcp.allocation(allocation_id)
        alloc = U.check_allocation(alloc_raw, client_ref=inputs.sheet.client_ref, sheet=inputs.sheet,
                                   currencies=cal.behaviour.currencies)
        base_raw = up.aggregation.regime(alloc.regime_id)
        base = U.check_base_regime(base_raw, alloc)
        chosen = U.choose_scenarios(up.aggregation.scenarios(), alloc.regime_id, scenarios)
        # fmre computes a ReturnSet on request (about a second each): the Regimes are read side by side.
        jobs: dict[tuple[str, str], Any] = {("set", "base"): (up.fmre.return_set, alloc.regime_id),
                                            ("infl", "base"): (up.fmre.inflation, alloc.regime_id)}
        if alloc.basis != "nominal":
            jobs[("check", "base")] = (lambda rid: up.fmre.return_set(rid, alloc.basis), alloc.regime_id)
        if chosen:
            jobs[("policies", "")] = (lambda _: up.aggregation.policies(), "")
        for k, rid in chosen.items():
            jobs[("regime", k)] = (up.aggregation.regime, rid)
            jobs[("set", k)] = (up.fmre.return_set, rid)
            jobs[("infl", k)] = (up.fmre.inflation, rid)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {key: pool.submit(fn, arg) for key, (fn, arg) in jobs.items()}
            got = {key: fut.result() for key, fut in futures.items()}
        policies = got.get(("policies", ""), [])
        scen_raw = {k: got[("regime", k)] for k in chosen}
        sets = {"base": got[("set", "base")], **{k: got[("set", k)] for k in chosen}}
        check = got.get(("check", "base"), sets["base"])
        infl = {"base": got[("infl", "base")], **{k: got[("infl", k)] for k in chosen}}
        return U.assemble(allocation=alloc, allocation_raw=alloc_raw, base_regime=base, base_regime_raw=base_raw,
                          scenario_ids=chosen, scenario_regimes_raw=scen_raw, policies_raw=policies,
                          return_sets_raw=sets, check_set_raw=check, inflation_raw=infl,
                          accept_ipt=self.settings.upstream.accept_ipt)

    def resolve_plan(self, inputs: Inputs, request: LifeBalanceSimRequest) -> StatedPlan:
        sim = self.settings.simulation
        try:
            return stated_plan(inputs.sheet, inputs.request, inputs.records, inputs.calibration, inputs.findings,
                               income_path=request.income_path, horizon_years=request.horizon_years,
                               max_horizon_years=sim.max_horizon_years, reference_age=sim.reference_age,
                               steps_per_year=sim.steps_per_year)
        except PlanError as exc:
            raise InvalidRequest(str(exc)) from exc

    def _store_artefact(self, conn, art, kind: str) -> None:
        st.put_artefact(conn, artefact_id=art.artefact_id, kind=kind, client_ref=art.client_ref,
                        life_balance_sheet_id=art.life_balance_sheet_id,
                        idempotency_key=art.provenance.idempotency_key, contract_version=art.contract_version,
                        payload_json=art.model_dump_json())

    # -- POST /run ----------------------------------------------------------------------------------------------

    def run(self, request: LifeBalanceSimRequest) -> RunAccepted:
        t0 = time.perf_counter()
        sim = self.settings.simulation
        cal = self._calibration_for(request.calibration_version)
        inputs = self.read_findings(request.life_balance_sheet_id, request.client_ref, cal)
        findings = inputs.findings
        n_paths = request.n_paths or sim.n_paths
        seed = sim.default_seed if request.seed is None else request.seed
        not_made: list[NotMade] = []
        paths_key_: Optional[str] = None
        if request.allocation_id is None:
            not_made += [NotMade(artefact="paths", reason="no_allocation", text=NOT_MADE_TEXT["no_allocation"]),
                         NotMade(artefact="plan", reason="no_allocation", text=NOT_MADE_TEXT["no_allocation"])]
        elif cal.behaviour.market != "allocation":
            not_made += [NotMade(artefact="paths", reason="draft_market", text=NOT_MADE_TEXT["draft_market"]),
                         NotMade(artefact="plan", reason="draft_market", text=NOT_MADE_TEXT["draft_market"])]
        else:
            inputs.bundle = self.read_market(inputs, request.allocation_id, request.scenarios)
            inputs.plan = self.resolve_plan(inputs, request)
            paths_key_ = paths_key(findings, inputs.bundle, horizon_years=inputs.plan.horizon_years,
                                   n_paths=n_paths, seed=seed, income_path=inputs.plan.income_path)

        cached = True
        with self.store.session() as conn:
            if st.artefact_by_key(conn, findings.provenance.idempotency_key) is None:
                cached = False
                self._store_artefact(conn, findings, "findings")
            paths = None
            if paths_key_ is not None:
                row = st.artefact_by_key(conn, paths_key_)
                if row is not None:
                    paths = LifeBalancePaths.model_validate_json(row["payload_json"])
        if paths_key_ is not None and paths is None:
            cached = False
            paths = build_paths(findings, inputs.plan, inputs.bundle, cal, n_paths=n_paths, seed=seed)
            with self.store.session() as conn:
                self._store_artefact(conn, paths, "paths")

        resolved = {"n_paths": n_paths, "seed": seed, "calibration_version": cal.version,
                    "horizon_years": inputs.plan.horizon_years if inputs.plan else None,
                    "income_path": inputs.plan.income_path if inputs.plan else None,
                    "scenarios": [r.key for r in inputs.bundle.regimes[1:]] if inputs.bundle else None}
        key = paths_key_ or findings.provenance.idempotency_key
        now = st.utc_now()
        run_id = content_id("RUN", {"key": key, "at": now, "nonce": uuid.uuid4().hex})
        plan_run_id = None
        plan_key_ = None
        if paths is not None:
            plan_key_ = plan_key(paths, findings.provenance.idempotency_key, cal, seed)
        artefact_ids = tuple(a for a in (findings.artefact_id, paths.artefact_id if paths else None) if a)
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, kind="outlook", status="running", idempotency_key=key,
                          client_ref=request.client_ref, life_balance_sheet_id=request.life_balance_sheet_id,
                          request={"request": request.model_dump(mode="json"), "resolved": resolved},
                          requested_by_kind="system", requested_by_ref="run", budget_s=sim.run_budget_s,
                          queued_at=now, started_at=now)
            st.finish_run(conn, run_id=run_id, status="succeeded", artefact_ids=artefact_ids,
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0)
            st.supersede(conn, client_ref=request.client_ref, keep_key=plan_key_)
            if paths is not None:
                if not inputs.plan.goals:
                    not_made.append(NotMade(artefact="plan", reason="no_goal", text=NOT_MADE_TEXT["no_goal"]))
                elif request.optimise == "background":
                    plan_run_id, _, _ = self._queue_plan(conn, paths=paths, findings=findings, key=plan_key_,
                                                         seed=seed, requested_by=RequestedBy(kind="system",
                                                                                             ref="run"))
                else:
                    not_made.append(NotMade(artefact="plan", reason="not_requested",
                                            text=NOT_MADE_TEXT["not_requested"]))
        return RunAccepted(run_id=run_id, kind="outlook", status="succeeded", idempotency_key=key, cached=cached,
                           findings_artefact_id=findings.artefact_id,
                           paths_artefact_id=paths.artefact_id if paths else None, plan_run_id=plan_run_id,
                           not_made=tuple(not_made))

    def _queue_plan(self, conn, *, paths: LifeBalancePaths, findings: LifeBalanceFindings, key: str, seed: int,
                    requested_by: RequestedBy) -> tuple[str, str, bool]:
        """The plan run for ``key``: a succeeded one (cached), a queued or running one as it is, else a new one.
        Returns ``(run_id, status, cached)``."""
        for r in st.runs_for_key(conn, key, "plan"):
            if r["status"] == "succeeded":
                return r["run_id"], "succeeded", True
            if r["status"] in ("queued", "running"):
                return r["run_id"], r["status"], False
        now = st.utc_now()
        run_id = content_id("RUN", {"key": key, "at": now, "nonce": uuid.uuid4().hex})
        st.insert_run(conn, run_id=run_id, kind="plan", status="queued", idempotency_key=key,
                      client_ref=paths.client_ref, life_balance_sheet_id=paths.life_balance_sheet_id,
                      request={"paths_artefact_id": paths.artefact_id, "findings_artefact_id": findings.artefact_id,
                               "seed": int(seed), "calibration_version": paths.calibration_version},
                      requested_by_kind=requested_by.kind, requested_by_ref=requested_by.ref,
                      budget_s=self.settings.optimiser.budget_s, queued_at=now)
        return run_id, "queued", False

    # -- POST /optimise -----------------------------------------------------------------------------------------

    def optimise(self, request: OptimiseRequest) -> RunAccepted:
        paths = self.paths(request.paths_artefact_id)
        findings = self.findings(paths.findings_artefact_id)
        cal = self.calibration(paths.calibration_version)
        seed = paths.seed if request.seed is None else request.seed
        key = plan_key(paths, findings.provenance.idempotency_key, cal, seed)
        with self.store.session() as conn:
            run_id, status, cached = self._queue_plan(conn, paths=paths, findings=findings, key=key, seed=seed,
                                                      requested_by=request.requested_by)
        return RunAccepted(run_id=run_id, kind="plan", status=status, idempotency_key=key, cached=cached,
                           findings_artefact_id=findings.artefact_id, paths_artefact_id=paths.artefact_id,
                           plan_run_id=run_id)

    def cancel(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
            if row is None:
                raise NotFound(f"lbsim has no run {run_id}.")
            if row["kind"] != "plan":
                raise Conflict("Only a plan calculation can be cancelled; an outlook run finishes at once.")
            if row["status"] in ("succeeded", "failed"):
                raise Conflict("This plan calculation has already finished and cannot be cancelled.")
            st.request_cancel(conn, run_id)
        return self.run_status(run_id)

    # -- POST /validate -----------------------------------------------------------------------------------------

    def validate(self, request: LifeBalanceSimRequest) -> ValidationReport:
        problems: list[Words] = []
        try:
            cal = self._calibration_for(request.calibration_version)
            inputs = self.read_findings(request.life_balance_sheet_id, request.client_ref, cal)
        except (InvalidRequest, Conflict) as exc:
            return ValidationReport(ok=False, client_ref=request.client_ref,
                                    life_balance_sheet_id=request.life_balance_sheet_id,
                                    calibration_version=request.calibration_version,
                                    problems=(Words(de=exc.message, en=exc.message),))
        f = inputs.findings
        not_made: list[NotMade] = []
        if request.allocation_id is None:
            not_made.append(NotMade(artefact="paths", reason="no_allocation", text=NOT_MADE_TEXT["no_allocation"]))
        elif cal.behaviour.market != "allocation":
            not_made.append(NotMade(artefact="paths", reason="draft_market", text=NOT_MADE_TEXT["draft_market"]))
        else:
            try:
                inputs.bundle = self.read_market(inputs, request.allocation_id, request.scenarios)
                plan = self.resolve_plan(inputs, request)
                if not plan.goals:
                    not_made.append(NotMade(artefact="plan", reason="no_goal", text=NOT_MADE_TEXT["no_goal"]))
            except (InvalidRequest, Conflict) as exc:
                problems.append(Words(de=exc.message, en=exc.message))
        if request.optimise == "no":
            not_made.append(NotMade(artefact="plan", reason="not_requested", text=NOT_MADE_TEXT["not_requested"]))
        return ValidationReport(ok=not problems, client_ref=request.client_ref,
                                life_balance_sheet_id=request.life_balance_sheet_id, calibration_version=cal.version,
                                problems=tuple(problems), gate=f.gate, unchecked=f.unchecked,
                                assumptions=f.assumptions, not_made=tuple(not_made))

    # -- reads ----------------------------------------------------------------------------------------------------

    def artefact(self, artefact_id: str):
        prefix = artefact_id.split("-", 1)[0]
        if prefix not in KINDS:
            raise NotFound(f"lbsim has no artefact {artefact_id}; its ids start with LSF-, LSP- or LSO-.")
        with self.store.session() as conn:
            row = st.get_artefact(conn, artefact_id)
        if row is None:
            raise NotFound(f"lbsim has no artefact {artefact_id}.")
        return KINDS[prefix][1].model_validate_json(row["payload_json"])

    def findings(self, artefact_id: str) -> LifeBalanceFindings:
        return self._typed(artefact_id, "LSF")

    def paths(self, artefact_id: str) -> LifeBalancePaths:
        return self._typed(artefact_id, "LSP")

    def plan(self, artefact_id: str) -> LifeBalancePlan:
        return self._typed(artefact_id, "LSO")

    def _typed(self, artefact_id: str, prefix: str):
        if not artefact_id.startswith(prefix + "-"):
            raise NotFound(f"{artefact_id} is not a {KINDS[prefix][0]} artefact.")
        return self.artefact(artefact_id)

    def fan(self, artefact_id: str, *, regime: str, basis: str, series: str) -> dict[str, Any]:
        if basis not in ("nominal", "real"):
            raise InvalidRequest("The basis is nominal or real.")
        paths = self.paths(artefact_id)
        try:
            return fan(paths, regime=regime, basis=basis, series=series)
        except KeyError as exc:
            what = str(exc.args[0])
            if what.startswith("regime:"):
                raise NotFound(f"These paths have no Regime {regime!r}.") from exc
            raise NotFound(f"These paths have no series {series!r}.") from exc

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"lbsim has no run {run_id}.")
        return status_of(row)

    def runs(self, *, client_ref: Optional[str] = None, kind: Optional[str] = None, status: Optional[str] = None,
             limit: int = 100) -> list[RunStatus]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, client_ref=client_ref, kind=kind, status=status,
                                limit=max(1, min(limit, 500)))
        return [status_of(r) for r in rows]

    def outlook(self, client_ref: str, life_balance_sheet_id: Optional[str] = None) -> LifeBalanceOutlook:
        with self.store.session() as conn:
            sheet_id = life_balance_sheet_id or st.latest_sheet_for_client(conn, client_ref)
            if sheet_id is None:
                raise NotFound("lbsim has no outlook for this client yet.")
            runs = [r for r in st.outlook_runs_for_sheet(conn, sheet_id)
                    if r["client_ref"] == client_ref and r["status"] == "succeeded"]
            if not runs:
                raise NotFound("lbsim has no outlook for this Life Balance Sheet yet.")
            last = runs[0]
            ids = json.loads(last["artefact_ids_json"])
            arts = {}
            for aid in ids:
                row = st.get_artefact(conn, aid)
                if row is not None:
                    arts[row["kind"]] = KINDS[aid.split("-", 1)[0]][1].model_validate_json(row["payload_json"])
            plan_runs = st.plan_runs_for_sheet(conn, sheet_id)
        findings, paths = arts.get("findings"), arts.get("paths")
        req = json.loads(last["request_json"]).get("request") or {}
        if paths is None:
            reason = WAITING if req.get("allocation_id") is None else NOT_MADE_TEXT["draft_market"]
            state = "waiting_for_allocation" if req.get("allocation_id") is None else "not_possible"
            plan = PlanOutlook(state=state, reason=reason)
        else:
            mine = [r for r in plan_runs
                    if json.loads(r["request_json"]).get("paths_artefact_id") == paths.artefact_id]
            plan = self._plan_outlook(mine)
        return LifeBalanceOutlook(client_ref=client_ref, life_balance_sheet_id=sheet_id, findings=findings,
                                  paths=paths, plan=plan)

    def _plan_outlook(self, runs: list[dict[str, Any]]) -> PlanOutlook:
        if not runs:
            return PlanOutlook(state="not_requested", reason=NOT_MADE_TEXT["not_requested"])
        done = next((r for r in runs if r["status"] == "succeeded"), None)
        if done is not None:
            ids = json.loads(done["artefact_ids_json"])
            art = self.plan(ids[0]) if ids else None
            return PlanOutlook(state="ready", run=status_of(done), artefact=art)
        active = next((r for r in runs if r["status"] in ("queued", "running")), None)
        if active is not None:
            return PlanOutlook(state="calculating", run=status_of(active),
                               elapsed_s=iso_seconds_since(active["started_at"] or active["queued_at"]),
                               budget_s=active["budget_s"])
        last = runs[0]
        return PlanOutlook(state="not_possible", run=status_of(last),
                           reason=PLAN_REASON.get(last["failure_kind"] or "solver", PLAN_REASON["solver"]))


def status_of(row: dict[str, Any]) -> RunStatus:
    progress = json.loads(row["progress_json"]) if row.get("progress_json") else None
    prog = None
    if progress:
        try:
            prog = Progress(**{k: progress[k] for k in ("phase", "start", "of", "seed_attempt", "elapsed_s")})
        except (KeyError, ValueError, TypeError):
            prog = None
    return RunStatus(run_id=row["run_id"], kind=row["kind"], status=row["status"], failure_kind=row["failure_kind"],
                     idempotency_key=row["idempotency_key"],
                     requested_by=RequestedBy(kind=row["requested_by_kind"], ref=row["requested_by_ref"]),
                     queued_at=row["queued_at"], started_at=row["started_at"], finished_at=row["finished_at"],
                     wall_clock_ms=row["wall_clock_ms"], budget_s=row["budget_s"], progress=prog,
                     request=json.loads(row["request_json"]), artefact_ids=tuple(json.loads(row["artefact_ids_json"])),
                     error=row["error"])


def _sha(payload: Any) -> str:
    from .ids import sha256  # noqa: PLC0415
    return sha256(payload)


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow", "pyyaml", "httpx",
                       "pytest", "hypothesis"})
ADMITTED = {"psycopg": "as LBS-02: the Guide mandates PostgreSQL; a driver is unavoidable",
            "casadi": "LBSIM-02: the optimiser's NLP (IPOPT inside the wheel); imported only by the plan workers"}


def allowlist_report() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]
    packages = {}
    for requirement in declared:
        name = re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        packages[name] = {"requirement": requirement, "installed": installed, "allowed": name in ALLOWLIST,
                          "admitted_by": ADMITTED.get(name)}
    return {"ok": all(p["allowed"] or p["admitted_by"] for p in packages.values()), "packages": packages}


__all__ = ["Service", "status_of", "allowlist_report", "LbsimError"]
