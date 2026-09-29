"""Orchestration: the only module that touches the store, the upstream client and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and
never calls out. The run lifecycle:

1. Resolve the request against ``config.yaml`` (economies, calibration) and, when the
   calibration reads macrofield, the macrofield artefact (the request's, or the latest).
2. Compute the idempotency key from the resolved inputs, the calibration's content hash,
   the engine version and the contract versions.
3. If an artefact already exists for that key, answer with the run that made it. Free.
4. Otherwise record a run, fetch the panel, run the model, store the artefact.

A run that cannot finish is recorded as ``failed`` with the reason, not retried silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from importlib import metadata
from typing import Any, Optional, Sequence

from pydantic import ValidationError

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import model_card
from . import store as st
from .clients import DatafeedClient, MacrofieldClient, UpstreamError, panel_checksum, state_checksum
from .contracts import (
    CONTRACT_VERSIONS,
    STORED_CYCLE_STATES,
    _CycleStateBase,
    PHASES,
    Calibration,
    CoverageReport,
    CurrentCycle,
    CurrentEconomy,
    CurrentPhases,
    CycleRunRequest,
    CycleState,
    EconomyOption,
    ModelCard,
    Provenance,
    RunAccepted,
    RunStatus,
)
from .engine import REQUIRED_SERIES, EngineError, reads_macrofield, run_model
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


class Unavailable(RuntimeError):
    """An upstream engine is needed before a run can even be recorded, and is not there."""


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


class Service:
    def __init__(self, settings: Settings, store: st.Store, datafeed: DatafeedClient,
                 macrofield: Optional[MacrofieldClient] = None):
        self.settings = settings
        self.store = store
        self.datafeed = datafeed
        self.macrofield = macrofield or MacrofieldClient(settings.macrofield_url, settings.macrofield_timeout_s)
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
            "allowlist": allowlist,
            "upstream": {"datafeed": self.settings.datafeed_url, "macrofield": self.settings.macrofield_url},
            "reads": list(REQUIRED_SERIES),
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

    def _project(self, request: CycleRunRequest) -> bool:
        return self.settings.default_project if request.project is None else request.project

    def _macrofield_artefact(self, request: CycleRunRequest, cal: Calibration) -> Optional[str]:
        """The MacroState this run reads (its output, or its projection horizon), or None when
        the run needs neither."""
        if not reads_macrofield(cal) and not self._project(request):
            return None
        if request.macrofield_artefact_id:
            return request.macrofield_artefact_id
        try:
            return self.macrofield.latest_artefact_id()
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc

    def _resolve(self, request: CycleRunRequest) -> tuple[tuple[str, ...], Calibration, dict[str, str]]:
        economies = request.economies or self.settings.default_economies
        try:
            registry = {c.code: c.name for c in self.datafeed.countries()}
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        unknown = [c for c in economies if c not in registry]
        if unknown:
            raise InvalidRequest(f"unknown country codes {unknown}; see datafeed GET /countries")
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        return tuple(economies), cal, registry

    def idempotency_key(self, request: CycleRunRequest, economies: Sequence[str], cal: Calibration,
                        macrofield_artefact: Optional[str] = None) -> str:
        return content_id("IDK", {
            "snapshot_id": request.snapshot_id,
            "macrofield_artefact_id": macrofield_artefact,
            "project": self._project(request),
            "economies": list(economies),
            "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        })

    def submit(self, request: CycleRunRequest) -> RunAccepted:
        economies, cal, names = self._resolve(request)
        mf_artefact = self._macrofield_artefact(request, cal)
        key = self.idempotency_key(request, economies, cal, mf_artefact)

        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded",
                               artefact_id=done["artefact_id"], idempotency_key=key, cached=True)

        started_at = st.utc_now()
        run_id = content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                    "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, status="running",
                          started_at=started_at, request_json=request.model_dump_json())

        try:
            artefact, warnings = self._execute(request, economies, cal, key, names, mf_artefact)
        except (UpstreamError, EngineError, ValidationError) as exc:
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", coverage_json=None, provenance_json=None,
                              error=f"{type(exc).__name__}: {exc}")
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None,
                               idempotency_key=key, cached=False)

        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=artefact.artefact_id, idempotency_key=key,
                            contract_version=artefact.contract_version,
                            payload_json=artefact.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0,
                          artefact_id=artefact.artefact_id, warnings_json=json.dumps(warnings),
                          coverage_json=artefact.coverage.model_dump_json(),
                          provenance_json=artefact.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=artefact.artefact_id,
                           idempotency_key=key, cached=False)

    def _execute(self, request: CycleRunRequest, economies: Sequence[str], cal: Calibration,
                 key: str, names: dict[str, str],
                 mf_artefact: Optional[str] = None) -> tuple[CycleState, list[str]]:
        panel = self.datafeed.panel(request.snapshot_id, REQUIRED_SERIES, economies)
        upstream = {"datafeed:snapshot": panel.snapshot_id, "datafeed:panel_sha256": panel_checksum(panel)}
        macro = horizon = None
        if mf_artefact is not None:
            state = self.macrofield.state(mf_artefact)
            if reads_macrofield(cal):
                macro = {e.code: (e.years, e.observed.Y) for e in state.economies
                         if e.status == "ok" and e.observed is not None and e.code in economies}
            if self._project(request):
                ends = [e.projection.years[-1] for e in state.economies
                        if e.code in economies and e.projection is not None and e.projection.years]
                horizon = max(ends) if ends else None
                if horizon is not None:
                    upstream["macrofield:projection_horizon"] = str(horizon)
            upstream.update({"macrofield:artefact": state.artefact_id,
                             "macrofield:snapshot": state.provenance.snapshot_id,
                             "macrofield:calibration": state.provenance.calibration_version,
                             "macrofield:state_sha256": state_checksum(state)})
        out = run_model(panel, cal, economies, names, macro, horizon)
        provenance = Provenance(
            snapshot_id=panel.snapshot_id,
            as_of=panel.as_of,
            upstream=upstream,
            engine_version=ENGINE_VERSION,
            contract_versions=CONTRACT_VERSIONS,
            calibration_version=cal.version,
            calibration_hash=seeds.calibration_hash(cal),
            idempotency_key=key,
        )
        body = dict(years=out.years, observed_until=out.observed_until, projected_until=out.projected_until,
                    cycles=cal.cycles, economies=out.economies, coverage=out.coverage, provenance=provenance)
        draft = CycleState(artefact_id="", **body)
        artefact = CycleState(artefact_id=content_id("CYS", draft.model_dump(mode="json")), **body)
        return artefact, _warnings(artefact)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"],
            idempotency_key=row["idempotency_key"], started_at=row["started_at"],
            finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=CycleRunRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"], warnings=tuple(json.loads(row["warnings_json"])),
            coverage=(CoverageReport.model_validate_json(row["coverage_json"])
                      if row["coverage_json"] else None),
            provenance=(Provenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"],
        )

    # -- the model card -------------------------------------------------------

    def model_card(self, economy: Optional[str] = None,
                   calibration_version: Optional[str] = None) -> ModelCard:
        """The model explained on one economy's data (``GET /model``), from what the store
        holds today: datafeed's current snapshot and macrofield's latest run."""
        try:
            registry = {c.code: c.name for c in self.datafeed.countries()}
            snapshot = self.datafeed.current_snapshot()
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        codes = [c for c in self.settings.default_economies if c in registry]
        code = economy or ("US" if "US" in codes else codes[0])
        if code not in registry:
            raise InvalidRequest(f"unknown country code {code!r}; see datafeed GET /countries")
        try:
            cal = self.calibration(calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        request = CycleRunRequest(snapshot_id=snapshot, economies=(code,))
        macro = horizon = None
        try:
            panel = self.datafeed.panel(snapshot, REQUIRED_SERIES, [code])
            mf_artefact = self._macrofield_artefact(request, cal)
            if mf_artefact is not None:
                state = self.macrofield.state(mf_artefact)
                if reads_macrofield(cal):
                    macro = {e.code: (e.years, e.observed.Y) for e in state.economies
                             if e.status == "ok" and e.observed is not None and e.code == code}
                if self._project(request):
                    ends = [e.projection.years[-1] for e in state.economies
                            if e.code == code and e.projection is not None and e.projection.years]
                    horizon = max(ends) if ends else None
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        options = [EconomyOption(code=c, name=registry[c]) for c in codes]
        try:
            return model_card.build(panel, cal, code, registry[code], options, macro or None, horizon)
        except EngineError as exc:
            raise InvalidRequest(str(exc)) from exc

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> "_CycleStateBase":
        """A stored artefact as it was published (C-26): read through the model of the contract
        version it was stored under, so a 1.1.0 artefact comes back as 1.1.0 and a 1.2.0 one as
        1.2.0. New runs publish ``CycleState`` (1.2.0)."""
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        version = json.loads(payload).get("contract_version")
        model = STORED_CYCLE_STATES.get(version)
        if model is None:
            raise EngineError(f"artefact {artefact_id} is stored under {version!r}, which this engine "
                              f"cannot read (known: {', '.join(STORED_CYCLE_STATES)})")
        return model.model_validate_json(payload)

    def cycles(self, artefact_id: str) -> dict[str, Any]:
        """The cycles per economy per year: phase, angle, level and confidence."""
        a = self.artefact(artefact_id)
        return {
            "artefact_id": a.artefact_id, "years": a.years, "phase_order": a.phase_order,
            "cycles": [c.name for c in a.cycles],
            "economies": [{"code": e.code, "name": e.name, "cycles": [
                {"cycle": t.cycle, "confidence": t.confidence, "phase": t.phase,
                 "angle": t.angle, "level": t.level} for t in e.cycles]} for e in a.economies],
            "notice": a.notice,
        }

    def current(self, artefact_id: str) -> CurrentPhases:
        """Each cycle's phase in the last observed year it has one, per economy (never a
        projected year)."""
        a = self.artefact(artefact_id)
        final = a.observed_until
        last = a.years.index(final)
        economies = []
        for e in a.economies:
            cycles = []
            for t in e.cycles:
                i = next((k for k in range(last, -1, -1) if t.phase[k] is not None), None)
                cycles.append(CurrentCycle(
                    cycle=t.cycle, year=None if i is None else a.years[i],
                    phase=None if i is None else t.phase[i], angle=None if i is None else t.angle[i],
                    level=None if i is None else t.level[i], confidence=t.confidence,
                    years_into_cycle=None if i is None else t.years_into_cycle[i],
                    bin_centre=None if i is None else t.bin_centre[i]))
            # The superposition ends where its members' spans end (with macrofield, a year before
            # the panel), so "current" for it is the last year it covers.
            k = next((k for k in range(last, -1, -1) if e.alignment[k] is not None), None)
            economies.append(CurrentEconomy(
                code=e.code, name=e.name, cycles=tuple(cycles), layer_mean_bin=e.layer_mean_bin[last],
                alignment=None if k is None else e.alignment[k],
                in_synchrony_window=k is not None and any(w.end_year == a.years[k] for w in e.synchrony_windows)))
        return CurrentPhases(artefact_id=a.artefact_id, year=final, phase_order=PHASES,
                             economies=tuple(economies))


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "C-02: the Guide mandates PostgreSQL; a driver is unavoidable (as honi D-05)"}


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


def _warnings(a: CycleState) -> list[str]:
    out = []
    cov = a.coverage
    if cov.unidentified:
        by_cycle: dict[str, int] = {}
        for u in cov.unidentified:
            by_cycle[u.cycle] = by_cycle.get(u.cycle, 0) + 1
        out.append("cycles without a position (see coverage.unidentified): "
                   + ", ".join(f"{k} in {v} of {cov.economies} economies" for k, v in sorted(by_cycle.items())))
    if cov.input_gaps:
        out.append(f"{len(cov.input_gaps)} economy inputs have years they do not cover "
                   "(see coverage.input_gaps); those years carry no estimated phase")
    assumed = sorted({f"{e.code}:{t.cycle}" for e in a.economies for t in e.cycles if t.assumed})
    if assumed:
        out.append(f"anchored on an assumed, projected crossing: {', '.join(assumed)}")
    breaks = sum(len(t.order_breaks) for e in a.economies for t in e.cycles)
    if breaks:
        out.append(f"{breaks} year steps in which a phase moved backwards (see order_breaks)")
    if cov.layer_cells_unplaced:
        out.append(f"{cov.layer_cells_unplaced} economy-years have no cycle on the 25-bin axis")
    if cov.public_fills:
        pairs = {(f.country, f.series_id) for f in cov.public_fills}
        out.append(f"{len(pairs)} input series are partly or wholly filled from public sources "
                   "by datafeed (see coverage.public_fills)")
    return out
