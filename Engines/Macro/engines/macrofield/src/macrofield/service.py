"""Orchestration: the only module that touches the store and the model together.

``api.py`` routes here and nowhere else; ``engine.py`` is called from here and never calls
out. The run lifecycle:

1. Resolve the request (snapshot, economies, calibration).
2. Idempotency key from the snapshot id, the economies, the calibration's content hash, the
   engine version and the contract versions.
3. A succeeded run for that key answers at once (``cached``). A queued or running one is joined.
4. Otherwise a run is queued and executed in the background: one economy calibration takes tens
   of seconds, so ``POST /run`` returns ``queued`` and ``GET /runs/{run_id}`` reports progress.
   Economies are spread over ``run.max_workers`` processes; the engine is deterministic, so the
   artefact does not depend on how many.

A run that cannot finish is recorded ``failed`` with the reason, never retried silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import tomllib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from typing import Any, Optional

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import data_need as need
from . import model_card
from . import projection
from . import snapshot as snap
from . import store as st
from .contracts import (
    CONTRACT_VERSIONS,
    Calibration,
    CoverageReport,
    DataNeed,
    EconomySpec,
    EconomyOption,
    EconomyState,
    ModelCard,
    Projection,
    ProjectionRequest,
    Provenance,
    RunAccepted,
    RunStatus,
    MacroRunRequest,
    MacroState,
)
from .assembly import member_key
from .engine import coverage, run_economy
from .settings import ROOT, Settings
from .sources import CATALOGUE


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def _wanted(spec: EconomySpec) -> list[tuple[str, str, str]]:
    """(series_id, area, engine key) for every catalogue series this economy can use.

    An aggregate economy also gets each member's PWT series, keyed ``series@member``.
    """
    out = []
    for s in CATALOGUE:
        area = {"world_bank": spec.world_bank, "bis": spec.bis, "pwt": spec.pwt,
                "bundesbank": spec.bank_area, "jst": spec.world_bank,
                "imf": spec.world_bank}[s.source]
        if area is not None:
            out.append((s.series_id, area, s.series_id))
        if s.source == "pwt":
            out.extend((s.series_id, m, member_key(s.series_id, m)) for m in spec.pwt_members)
    return out


class Service:
    def __init__(self, settings: Settings, store: st.Store):
        self.settings = settings
        self.store = store
        self.started = time.monotonic()
        # One run at a time: a run already uses every worker process it is allowed.
        self._runs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="macrofield-run")
        self._submit_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def startup(self) -> None:
        """Create tables, write the seed calibrations, fail runs orphaned by a restart."""
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
                        f"seed calibration {cal.version} in calibration.py no longer matches the "
                        "stored one. Seeds are immutable: give the change a new version.") from exc
            if st.get_calibration(conn, self.settings.active_calibration) is None:
                raise st.StoreError(f"config.yaml names active calibration "
                                    f"{self.settings.active_calibration!r}, which is not stored")
            st.fail_orphaned_runs(conn)

    def shutdown(self) -> None:
        self._runs.shutdown(wait=False, cancel_futures=True)

    def load_snapshot(self, raw: Optional[Path] = None) -> dict[str, Any]:
        """Load the frozen raw folder into the store. Idempotent: a known snapshot is skipped."""
        loaded = snap.load(raw or self.settings.raw_dir)
        with self.store.session() as conn:
            if st.snapshot_exists(conn, loaded.snapshot_id):
                return {"snapshot_id": loaded.snapshot_id, "created": False,
                        "notes": list(loaded.notes)}
            count = st.put_snapshot(conn, snapshot_id=loaded.snapshot_id,
                                    frozen_on=loaded.frozen_on,
                                    manifest_json=st.dumps(loaded.manifest),
                                    files=loaded.manifest["files"], observations=loaded.rows)
        return {"snapshot_id": loaded.snapshot_id, "created": True, "observations": count,
                "notes": list(loaded.notes)}

    # -- standard endpoints ------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
        return {
            "engine": ENGINE,
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": self.settings.active_calibration,
            "calibration_versions": versions,
            "allowlist": allowlist_report(),
            "store": {**self.store.config.describe(), "counts": counts},
            "run": {"max_workers": self.settings.max_workers},
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
        """Store a new version. Returns (calibration, created). Never changes the active one."""
        with self.store.session() as conn:
            if proposal.parent_version and st.get_calibration(conn, proposal.parent_version) is None:
                raise InvalidRequest(f"parent_version {proposal.parent_version!r} does not exist")
            try:
                created = st.put_calibration(
                    conn, version=proposal.version,
                    calibration_hash=seeds.calibration_hash(proposal),
                    parent_version=proposal.parent_version,
                    payload_json=seeds.canonical_json(proposal))
            except st.StoreConflict as exc:
                raise Conflict(str(exc)) from exc
        return proposal, created

    # -- runs --------------------------------------------------------------

    @staticmethod
    def _policy(cal: Calibration, requested: Optional[str]) -> Optional[str]:
        """The resolution policy a run or what-if uses: the requested one, else the
        calibration's default; ``None`` for a calibration without a crisis section, which
        refuses an explicit policy rather than ignoring it."""
        crisis = cal.projection.crisis
        if crisis is None:
            if requested is not None:
                raise InvalidRequest(f"calibration {cal.version} has no resolution policies "
                                     "(they start with 1.4.0); omit resolution_policy")
            return None
        return requested or crisis.default_policy

    def _resolve(self, request: MacroRunRequest) -> tuple[tuple[str, ...], Calibration, dict]:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        registered = [e.code for e in cal.economies]
        codes = tuple(request.economies or registered)
        unknown = [c for c in codes if c not in registered]
        if unknown:
            raise InvalidRequest(f"calibration {cal.version} registers no economy {unknown}")
        with self.store.session() as conn:
            snapshot = st.get_snapshot(conn, request.snapshot_id)
        if snapshot is None:
            raise InvalidRequest(f"no snapshot {request.snapshot_id!r}; load one with "
                                 "`python -m macrofield load` and see GET /snapshots")
        return codes, cal, snapshot

    def idempotency_key(self, snapshot_id: str, codes: tuple[str, ...], cal: Calibration,
                        resolution_policy: Optional[str] = None) -> str:
        payload = {
            "snapshot_id": snapshot_id,
            "economies": list(codes),
            "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        }
        if resolution_policy is not None:
            payload["resolution_policy"] = resolution_policy
        return content_id("IDK", payload)

    def submit(self, request: MacroRunRequest, *, wait: bool = False) -> RunAccepted:
        codes, cal, snapshot = self._resolve(request)
        policy = self._policy(cal, request.resolution_policy)
        key = self.idempotency_key(request.snapshot_id, codes, cal, policy)

        with self._submit_lock:
            with self.store.session() as conn:
                done = st.succeeded_run_for_key(conn, key)
                active = None if done else st.active_run_for_key(conn, key)
                if done is None and active is None:
                    started_at = st.utc_now()
                    run_id = content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                                "nonce": time.perf_counter_ns()})
                    st.insert_run(conn, run_id=run_id, idempotency_key=key, status="queued",
                                  started_at=started_at, request_json=request.model_dump_json())
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded",
                               artefact_id=done["artefact_id"], idempotency_key=key, cached=True)
        if active is not None:
            return RunAccepted(run_id=active["run_id"], status=active["status"],
                               artefact_id=None, idempotency_key=key, cached=False)

        future = self._runs.submit(self._execute, run_id, codes, cal, snapshot, key, policy)
        if wait:
            future.result()
            status = self.run_status(run_id)
            return RunAccepted(run_id=run_id, status=status.status,
                               artefact_id=status.artefact_id, idempotency_key=key, cached=False)
        return RunAccepted(run_id=run_id, status="queued", artefact_id=None,
                           idempotency_key=key, cached=False)

    def _observations(self, snapshot_id: str, specs: list[EconomySpec]) -> dict[str, dict]:
        wanted = {(s, a) for spec in specs for s, a, _ in _wanted(spec)}
        with self.store.session() as conn:
            found = st.observations(conn, snapshot_id, wanted)
        return {spec.code: {key: found[(s, a)] for s, a, key in _wanted(spec) if (s, a) in found}
                for spec in specs}

    def _states(self, specs: list[EconomySpec], obs: dict[str, dict],
                cal: Calibration, policy: Optional[str] = None) -> list[EconomyState]:
        workers = min(self.settings.max_workers, len(specs))
        if workers <= 1:
            return [run_economy(spec, obs[spec.code], cal, policy) for spec in specs]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_economy, spec, obs[spec.code], cal, policy)
                       for spec in specs]
            return [f.result() for f in futures]

    def _execute(self, run_id: str, codes: tuple[str, ...], cal: Calibration,
                 snapshot: dict[str, Any], key: str, policy: Optional[str] = None) -> None:
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.mark_running(conn, run_id)
            files = st.snapshot_files(conn, snapshot["snapshot_id"])
        try:
            specs = [cal.economy(c) for c in codes]
            obs = self._observations(snapshot["snapshot_id"], specs)
            states = self._states(specs, obs, cal, policy)
            report = coverage(codes, states)
            provenance = Provenance(
                snapshot_id=snapshot["snapshot_id"], as_of=snapshot["frozen_on"],
                sources={f["path"]: f["sha256"] for f in files},
                engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS,
                calibration_version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                idempotency_key=key, resolution_policy=policy)
            draft = MacroState(artefact_id="", economies=tuple(states), coverage=report,
                                   provenance=provenance)
            artefact = draft.model_copy(update={
                "artefact_id": content_id("MFS", draft.model_dump(mode="json"))})
            MacroState.model_validate(artefact.model_dump())
        except Exception as exc:  # noqa: BLE001 - a failed run records its reason
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0,
                              artefact_id=None, warnings_json="[]", coverage_json=None,
                              provenance_json=None, error=f"{type(exc).__name__}: {exc}")
            return

        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=artefact.artefact_id, idempotency_key=key,
                            contract_version=artefact.contract_version,
                            payload_json=artefact.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0,
                          artefact_id=artefact.artefact_id,
                          warnings_json=json.dumps(_warnings(states)),
                          coverage_json=report.model_dump_json(),
                          provenance_json=provenance.model_dump_json(), error=None)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            wall_clock_ms=row["wall_clock_ms"],
            request=MacroRunRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"], warnings=tuple(json.loads(row["warnings_json"])),
            coverage=(CoverageReport.model_validate_json(row["coverage_json"])
                      if row["coverage_json"] else None),
            provenance=(Provenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"],
        )

    def runs(self, limit: int) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return st.list_runs(conn, max(1, min(limit, 200)))

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> MacroState:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        return MacroState.model_validate_json(payload)

    def economy(self, artefact_id: str, code: str) -> EconomyState:
        a = self.artefact(artefact_id)
        try:
            return a.economy(code)
        except KeyError as exc:
            raise NotFound(f"economy {code!r} is not in artefact {artefact_id}") from exc

    def model_card(self, economy: Optional[str] = None) -> ModelCard:
        """The model explained on one economy (``GET /model``), read from the latest successful
        run: the fit takes too long to repeat for a page, and the artefact holds every step."""
        with self.store.session() as conn:
            done = [r for r in st.list_runs(conn, 200) if r["status"] == "succeeded" and r["artefact_id"]]
        if not done:
            raise NotFound("macrofield has no successful run yet; POST /run first")
        state = self.artefact(done[0]["artefact_id"])
        ok = [e for e in state.economies if e.status == "ok"]
        if not ok:
            raise NotFound(f"no economy is available in run {state.artefact_id}")
        code = economy or ("US" if any(e.code == "US" for e in ok) else ok[0].code)
        chosen = next((e for e in ok if e.code == code), None)
        if chosen is None:
            raise InvalidRequest(f"{code!r} is not available in run {state.artefact_id}; available: "
                                 f"{[e.code for e in ok]}")
        cal = self.calibration(state.provenance.calibration_version)
        return model_card.build(state, chosen, cal, [EconomyOption(code=e.code, name=e.name) for e in ok])

    def current(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        return {
            "artefact_id": a.artefact_id,
            "calibration_version": a.provenance.calibration_version,
            "economies": [
                {"code": e.code, "name": e.name, "status": e.status,
                 **({"current": e.current.model_dump()} if e.current else {"reason": e.reason})}
                for e in a.economies],
            "notice": a.notice,
        }

    def project(self, request: ProjectionRequest) -> Projection:
        """A what-if projection on a stored artefact: recomputed, not stored, deterministic."""
        state = self.economy(request.artefact_id, request.economy)
        a = self.artefact(request.artefact_id)
        cal = self.calibration(a.provenance.calibration_version)
        settings = projection.settings_from(
            cal, horizon=request.horizon, parameter_mode=request.parameter_mode,
            stimulus=request.stimulus, savings=request.savings,
            deflation_capital_decline=request.deflation_capital_decline,
            inflation_output_growth=request.inflation_output_growth,
            resolution_policy=self._policy(cal, request.resolution_policy),
            horizon_until=request.horizon_until)
        return projection.project(state, cal, settings)

    def snapshots(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return st.list_snapshots(conn)

    def data_need(self, snapshot_id: Optional[str], version: Optional[str]) -> DataNeed:
        cal = self.calibration(version)
        with self.store.session() as conn:
            if snapshot_id is None:
                listed = st.list_snapshots(conn)
                snapshot_id = listed[-1]["snapshot_id"] if listed else None
            if snapshot_id is not None and st.get_snapshot(conn, snapshot_id) is None:
                raise NotFound(f"no snapshot {snapshot_id!r}")
            present = st.present_series(conn, snapshot_id) if snapshot_id else []
        return need.build(cal, present)


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "D-05 (honi): the Guide mandates PostgreSQL; a driver is unavoidable"}


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
    return {"ok": all(p["allowed"] or p["admitted_by"] for p in packages.values()),
            "packages": packages}


#: An economy whose last year trails the latest by more than this is flagged as stale.
STALE_YEARS = 3


def _warnings(states: list[EconomyState]) -> list[str]:
    out = []
    unavailable = [s.code for s in states if s.status == "unavailable"]
    if unavailable:
        out.append(f"unavailable, see coverage for the reason: {', '.join(unavailable)}")
    ok = [s for s in states if s.status == "ok" and s.fit is not None]
    if ok:
        latest = max(s.years[-1] for s in ok)
        stale = [f"{s.code} ({s.years[-1]})" for s in ok if s.years[-1] < latest - STALE_YEARS]
        if stale:
            out.append(f"current state more than {STALE_YEARS} years behind {latest}: "
                       f"{', '.join(stale)}; see the economy's notes for the binding series")
    for label, members in (
        ("fit did not converge", [s.code for s in ok if not s.fit.converged]),
        ("simulated path only at search tolerance", [s.code for s in ok
                                                     if s.fit.integration_accuracy == "search"]),
        ("no simulated path (finite-time singularity)", [s.code for s in ok
                                                         if s.fit.integration_accuracy == "none"]),
        ("real-capital ratio extended past PWT", [
            s.code for s in ok if s.inputs and any(s.inputs.real_capital_ratio_extended)]),
    ):
        if members:
            out.append(f"{label}: {', '.join(members)}")
    return out
