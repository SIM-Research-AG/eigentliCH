"""Orchestration: the only module that touches the store, datafeed and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` and ``indicators.py`` are
called from here and never call out. The run lifecycle:

1. Resolve the snapshot (the request's, or ``upstream.snapshot_id`` from ``config.yaml``)
   and the calibration (the request's, or the active one).
2. Compute the idempotency key from the snapshot id, the calibration's content hash, the
   engine version and the contract versions. datafeed snapshots are immutable, so the id
   pins the input; the panel's sha256 is recorded in the provenance.
3. If an artefact already exists for that key, answer with the run that made it. Free: no
   call to datafeed.
4. Otherwise record a run, read the panel through datafeed's coverage gate, run the model
   and store the ``MarketRiskSignal``.

``mrs`` publishes at zero optimism shift and stamps ``regime_id: null`` (MRS-13).
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
from . import store as st
from .clients import DatafeedClient, UpstreamError
from .contracts import (
    CONTRACT_VERSIONS,
    SEGMENTS,
    Calibration,
    CoverageReport,
    EconomyOption,
    InputReport,
    InputSeries,
    MarketRiskSignal,
    MRSRunRequest,
    ModelCard,
    Panel,
    Provenance,
    RunAccepted,
    RunStatus,
    RunSummary,
)
from .engine import EconomyInput, EngineError, run_model
from .indicators import series_needed
from .inputs import matlab_view, matrix
from .series import PUBLIC_SERIES_IDS, REQUIRED_SERIES
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def content_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_digest(payload)}"


class Service:
    def __init__(self, settings: Settings, store: st.Store, datafeed: DatafeedClient):
        self.settings = settings
        self.store = store
        self.datafeed = datafeed
        self.started = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    def startup(self) -> None:
        """Create tables, write the seed calibrations, and check the active one exists."""
        self.store.initialise()
        reason = self.store.stale()
        if reason:
            raise st.StoreError(reason)
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
            "upstream": {"datafeed": self.settings.datafeed_url,
                         "snapshot_id": self.settings.snapshot_id},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
        }

    # -- input: datafeed's panel -------------------------------------------

    def market_panel(self, snapshot_id: Optional[str] = None) -> tuple[Panel, str]:
        """The input series of one datafeed snapshot (default: ``config.yaml``), live.

        The coverage report is read first, as the gate: an unknown snapshot, or one that
        does not carry every ``M_TS`` series ``mrs`` reads, fails there before the panel is
        fetched. The public replacements (``PUBLIC_SERIES``) are added when the snapshot
        carries them: the market layer does, a raw snapshot cannot.
        """
        snapshot_id = snapshot_id or self.settings.snapshot_id
        carried = self._gate(snapshot_id)
        return self.datafeed.panel(snapshot_id, self._wanted(carried))

    def _gate(self, snapshot_id: str) -> set[str]:
        try:
            coverage = self.datafeed.coverage(snapshot_id)
        except UpstreamError as exc:
            if "has no snapshot" in str(exc):
                raise NotFound(str(exc)) from exc
            raise
        carried = {r.series_id for r in coverage.rows}
        absent = [s for s in REQUIRED_SERIES if s not in carried]
        if absent:
            raise UpstreamError(f"datafeed snapshot {snapshot_id!r} does not carry {absent}")
        return carried

    @staticmethod
    def _wanted(carried: set[str]) -> tuple[str, ...]:
        return REQUIRED_SERIES + tuple(s for s in PUBLIC_SERIES_IDS if s in carried)

    def input_report(self, snapshot_id: Optional[str] = None) -> InputReport:
        snapshot_id = snapshot_id or self.settings.snapshot_id
        panel, sha = self.market_panel(snapshot_id)
        coverage = self.datafeed.coverage(snapshot_id)
        countries = tuple(sorted({s.country for s in panel.series}))
        wanted = self._wanted({r.series_id for r in coverage.rows})
        rows = [r for r in coverage.rows if r.series_id in wanted]
        series = []
        for series_id in wanted:
            mine = [r for r in rows if r.series_id == series_id]
            with_data = tuple(sorted(r.country for r in mine if r.observed + r.carried > 0))
            series.append(InputSeries(
                series_id=series_id, countries_with_data=with_data,
                countries_without_data=tuple(c for c in countries if c not in with_data),
                observed=sum(r.observed for r in mine), carried=sum(r.carried for r in mine),
                missing=sum(r.missing for r in mine),
                from_public_sources=sum(r.from_public_sources for r in mine)))
        return InputReport(
            snapshot_id=snapshot_id, as_of=panel.as_of, first_date=panel.dates[0],
            last_date=panel.dates[-1], months=len(panel.dates), countries=countries,
            panel_sha256=sha, series=tuple(series),
            plausibility=tuple(f"{f.country}: {f.check}: {f.detail}" for f in coverage.plausibility))

    # -- the model card -------------------------------------------------------

    def model_card(self, economy: Optional[str] = None,
                   calibration_version: Optional[str] = None) -> ModelCard:
        """The model explained on one economy's data (``GET /model``): the engine's own
        functions on the configured snapshot, for that economy."""
        cal = self.calibration(calibration_version)
        panel, _ = self.market_panel()
        needed = series_needed(cal.indicators)
        absent = [s for s in needed if s not in {x.series_id for x in panel.series}]
        if absent:
            raise UpstreamError(f"calibration {cal.version} reads {absent}, which the snapshot does not carry")
        names = {c.code: c.name for c in self.datafeed.countries()}
        countries = sorted({s.country for s in panel.series})
        code = economy or ("US" if "US" in countries else countries[0])
        if code not in countries:
            raise InvalidRequest(f"unknown economy {code!r}; the snapshot carries {countries}")
        try:
            return model_card.build(panel, cal, code, names.get(code, code),
                                    [EconomyOption(code=c, name=names.get(c, c)) for c in countries])
        except EngineError as exc:
            raise InvalidRequest(str(exc)) from exc

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

    def idempotency_key(self, snapshot_id: str, cal: Calibration) -> str:
        return content_id("IDK", {
            "snapshot_id": snapshot_id,
            "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        })

    def submit(self, request: MRSRunRequest) -> RunAccepted:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        snapshot_id = request.snapshot_id or self.settings.snapshot_id
        key = self.idempotency_key(snapshot_id, cal)

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
                          snapshot_id=snapshot_id, calibration_version=cal.version,
                          started_at=started_at, request_json=request.model_dump_json())

        try:
            artefact, warnings = self._execute(snapshot_id, cal, key)
        except NotFound as exc:
            self._fail(run_id, t0, exc)
            raise
        except (UpstreamError, EngineError, ValidationError) as exc:
            self._fail(run_id, t0, exc)
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None,
                               idempotency_key=key, cached=False)

        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=artefact.artefact_id, idempotency_key=key,
                            snapshot_id=snapshot_id, calibration_version=cal.version,
                            contract_version=artefact.contract_version,
                            payload_json=artefact.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0,
                          artefact_id=artefact.artefact_id, warnings_json=json.dumps(warnings),
                          coverage_json=artefact.coverage.model_dump_json(),
                          provenance_json=artefact.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=artefact.artefact_id,
                           idempotency_key=key, cached=False)

    def _fail(self, run_id: str, t0: float, exc: Exception) -> None:
        with self.store.session() as conn:
            st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                          warnings_json="[]", coverage_json=None, provenance_json=None,
                          error=f"{type(exc).__name__}: {exc}")

    def _execute(self, snapshot_id: str, cal: Calibration,
                 key: str) -> tuple[MarketRiskSignal, list[str]]:
        panel, sha = self.market_panel(snapshot_id)
        needed = series_needed(cal.indicators)
        served = {s.series_id for s in panel.series}
        absent = [s for s in needed if s not in served]
        if absent:
            raise UpstreamError(f"calibration {cal.version} reads {absent}, which datafeed "
                                f"snapshot {snapshot_id!r} does not carry")
        names = {c.code: c.name for c in self.datafeed.countries()}
        countries = sorted({s.country for s in panel.series})
        warnings: list[str] = []
        if cal.indicators.mode == "matlab":
            conversions = self.datafeed.conversions(snapshot_id)
            views = {sid: matlab_view(panel, sid, countries, conversions) for sid in needed}
            warnings.append(f"calibration {cal.version} reproduces MATLAB (full-sample "
                            "normalisation, gaps as 0, a missing segment as column 1); "
                            "for reconciliation, not for publication")
            if any(f != "observed" for s in panel.series for f in s.flags if f != "missing"):
                warnings.append(f"snapshot {snapshot_id!r} carries cells that are not "
                                "Bloomberg's; the matlab calibration only reproduces MATLAB on "
                                "a raw snapshot")
        else:
            views = {sid: matrix(panel, sid, countries) for sid in needed}
        economies = [EconomyInput(code=c, name=names.get(c, c),
                                  series={sid: np.asarray(views[sid][:, j]) for sid in needed})
                     for j, c in enumerate(countries)]
        out = run_model(panel.dates, economies, cal)

        provenance = Provenance(
            snapshot_id=snapshot_id,
            as_of=panel.as_of,
            upstream={"datafeed": sha},
            engine_version=ENGINE_VERSION,
            contract_versions=CONTRACT_VERSIONS,
            calibration_version=cal.version,
            calibration_hash=seeds.calibration_hash(cal),
            idempotency_key=key,
        )
        body = dict(dates=panel.dates, economies=out.economies, coverage=out.coverage,
                    provenance=provenance)
        draft = MarketRiskSignal(artefact_id="MRS-draft", **body)
        artefact = MarketRiskSignal(artefact_id=content_id("MRS", draft.model_dump(mode="json")),
                                    **body)
        return artefact, warnings + _warnings(cal, out.coverage)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"],
            idempotency_key=row["idempotency_key"], snapshot_id=row["snapshot_id"],
            calibration_version=row["calibration_version"], started_at=row["started_at"],
            finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=MRSRunRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"],
            warnings=tuple(json.loads(row["warnings_json"])),
            coverage=(CoverageReport.model_validate_json(row["coverage_json"])
                      if row["coverage_json"] else None),
            provenance=(Provenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"],
        )

    def runs(self, limit: int = 20) -> list[RunSummary]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, limit)
        return [RunSummary(**r) for r in rows]

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> MarketRiskSignal:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        return MarketRiskSignal.model_validate_json(payload)

    def _economies(self, s: MarketRiskSignal, economies: Optional[list[str]]):
        try:
            return [s.economy(c) for c in economies] if economies else list(s.economies)
        except KeyError as exc:
            raise NotFound(f"{exc.args[0]!r} is not in artefact {s.artefact_id}") from exc

    def distribution(self, artefact_id: str, date: Optional[str] = None,
                     economies: Optional[list[str]] = None) -> dict[str, Any]:
        s = self.artefact(artefact_id)
        date = date or s.dates[-1]
        if date not in s.dates:
            raise NotFound(f"artefact {artefact_id} has no date {date!r}; it covers "
                           f"{s.dates[0]} to {s.dates[-1]} at month ends")
        i = s.dates.index(date)
        return {"artefact_id": s.artefact_id, "date": date, "n_states": s.n_states,
                "economies": {e.code: {"distribution": e.distribution[i], "state": e.state[i],
                                       "raw_mass": e.raw_mass[i]}
                              for e in self._economies(s, economies)},
                "notice": s.notice}

    def segments(self, artefact_id: str, economies: Optional[list[str]] = None) -> dict[str, Any]:
        s = self.artefact(artefact_id)
        return {"artefact_id": s.artefact_id, "dates": s.dates,
                "segment_names": s.segment_names,
                "economies": {e.code: e.segments for e in self._economies(s, economies)},
                "notice": s.notice}

    def current(self, artefact_id: str, economies: Optional[list[str]] = None) -> dict[str, Any]:
        """The latest assessed month per economy."""
        s = self.artefact(artefact_id)
        out = []
        for e in self._economies(s, economies):
            i = next((k for k in range(len(s.dates) - 1, -1, -1) if e.state[k] is not None), None)
            if i is None:
                out.append({"code": e.code, "name": e.name, "date": None, "state": None,
                            "distribution": None, "segments": None})
                continue
            out.append({"code": e.code, "name": e.name, "date": s.dates[i], "state": e.state[i],
                        "distribution": e.distribution[i],
                        "segments": {k: e.segments[k][i] for k in SEGMENTS}})
        return {"artefact_id": s.artefact_id, "economies": out, "notice": s.notice}


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "honi D-05: the Guide mandates PostgreSQL; a driver is unavoidable"}


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


def _warnings(cal: Calibration, coverage: CoverageReport) -> list[str]:
    out = []
    gaps = sum(sum(e.segment_gaps.values()) for e in coverage.economies)
    if gaps and cal.missing_policy == "reweight":
        out.append(f"{gaps} segment readings were missing and their weight re-distributed "
                   "(see coverage.economies[].segment_gaps)")
    never = [e.code for e in coverage.economies if e.dates_assessed == 0]
    if never:
        out.append(f"never assessed: {', '.join(never)}")
    unassessed = [e.code for e in coverage.economies if e.dates_unassessed and e.dates_assessed]
    if unassessed:
        out.append(f"{len(unassessed)} economies have unassessed dates (fewer than "
                   f"{cal.min_segments} segments): {', '.join(unassessed)}")
    empty = sorted({s for e in coverage.economies for s in e.inputs_missing})
    if empty:
        out.append(f"input series with no data for some economies: {', '.join(empty)} "
                   "(see coverage.economies[].inputs_missing)")
    return out
