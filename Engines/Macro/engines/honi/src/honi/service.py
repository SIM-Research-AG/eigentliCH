"""Orchestration: the only module that touches the store, the upstream client and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and
never calls out. The run lifecycle:

1. Resolve the request against ``config.yaml`` (peer set, window, calibration).
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
from .clients import DatafeedClient, UpstreamError, panel_checksum
from .contracts import (
    CONTRACT_VERSIONS,
    INDICES,
    SECTORS,
    Calibration,
    CountryRef,
    CountryScores,
    CoverageReport,
    HoNIRunRequest,
    HoNIScores,
    HoNITrends,
    EconomyOption,
    IndexView,
    ModelCard,
    PeerStats,
    Provenance,
    RunAccepted,
    RunStatus,
)
from .engine import (INDICATORS, REQUIRED_SERIES, EngineError, as_matrix, peer_stats,
                     plausibility_exclusions, run_model, trends)
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
    def __init__(self, settings: Settings, store: st.Store, datafeed: DatafeedClient):
        self.settings = settings
        self.store = store
        self.datafeed = datafeed
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
            "upstream": {"datafeed": self.settings.datafeed_url},
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

    def ranges(self, version: Optional[str] = None) -> dict[str, Any]:
        cal = self.calibration(version)
        definitions = {d.name: d for d in INDICATORS}
        return {
            "calibration_version": cal.version,
            "indices": [
                {"index": s.name, "sector": s.sector, "kind": s.kind, "range": list(s.range),
                 "weight": s.weight, "definition": definitions[s.name].definition,
                 "inputs": list(definitions[s.name].inputs)}
                for s in cal.indices
            ],
        }

    # -- runs --------------------------------------------------------------

    def _resolve(self, request: HoNIRunRequest) -> tuple[tuple[str, ...], Calibration, dict[str, str]]:
        countries = request.countries or self.settings.default_countries
        try:
            registry = {c.code: c.name for c in self.datafeed.countries()}
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        unknown = [c for c in countries if c not in registry]
        if unknown:
            raise InvalidRequest(f"unknown country codes {unknown}; see datafeed GET /countries")
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        return tuple(countries), cal, registry

    def idempotency_key(self, request: HoNIRunRequest, countries: Sequence[str],
                        cal: Calibration) -> str:
        window = (request.window.model_dump() if request.window
                  else {"last_years": self.settings.default_window_years})
        return content_id("IDK", {
            "snapshot_id": request.snapshot_id,
            "countries": list(countries),
            "window": window,
            "calibration_hash": seeds.calibration_hash(cal),
            "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        })

    def submit(self, request: HoNIRunRequest) -> RunAccepted:
        countries, cal, names = self._resolve(request)
        key = self.idempotency_key(request, countries, cal)

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
            artefact, warnings = self._execute(request, countries, cal, key, names)
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

    def _execute(self, request: HoNIRunRequest, countries: Sequence[str], cal: Calibration,
                 key: str, names: dict[str, str]) -> tuple[HoNIScores, list[str]]:
        gate = self.datafeed.coverage(request.snapshot_id)
        excluded = plausibility_exclusions(gate, cal)
        panel = self.datafeed.panel(request.snapshot_id, REQUIRED_SERIES, countries)
        out = run_model(panel, cal, countries, request.window, self.settings.default_window_years,
                        excluded)

        provenance = Provenance(
            snapshot_id=panel.snapshot_id,
            as_of=panel.as_of,
            upstream={"datafeed:snapshot": panel.snapshot_id,
                      "datafeed:panel_sha256": panel_checksum(panel)},
            engine_version=ENGINE_VERSION,
            contract_versions=CONTRACT_VERSIONS,
            calibration_version=cal.version,
            calibration_hash=seeds.calibration_hash(cal),
            idempotency_key=key,
        )
        body = dict(
            years=out.years,
            countries=tuple(CountryRef(code=c, name=names[c]) for c in countries),
            national=as_matrix(out.national),
            sectors={k: as_matrix(v) for k, v in out.sectors.items()},
            index_scores={k: as_matrix(v) for k, v in out.index_scores.items()},
            index_raw={k: as_matrix(v) for k, v in out.index_raw.items()},
            capital_saturation=as_matrix(out.capital_saturation),
            coverage=out.coverage,
            provenance=provenance,
        )
        draft = HoNIScores(artefact_id="", **body)
        artefact_id = content_id("HNS", draft.model_dump(mode="json"))
        artefact = HoNIScores(artefact_id=artefact_id, **body)
        return artefact, _warnings(cal, out.coverage)

    # -- the model card -------------------------------------------------------

    def model_card(self, economy: Optional[str] = None,
                   calibration_version: Optional[str] = None) -> ModelCard:
        """HoNI explained on one economy's data (``GET /model``): the whole model on the default
        peer set and datafeed's current snapshot, shown for that economy."""
        countries = list(self.settings.default_countries)
        code = economy or ("US" if "US" in countries else countries[0])
        if code not in countries:
            raise InvalidRequest(f"{code!r} is not in the peer set {countries}")
        try:
            names = {c.code: c.name for c in self.datafeed.countries()}
            snapshot = self.datafeed.current_snapshot()
            gate = self.datafeed.coverage(snapshot)
            panel = self.datafeed.panel(snapshot, REQUIRED_SERIES, countries)
        except UpstreamError as exc:
            raise Unavailable(str(exc)) from exc
        try:
            cal = self.calibration(calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        try:
            return model_card.build(panel, cal, code, names, countries, plausibility_exclusions(gate, cal),
                                    self.settings.default_window_years)
        except EngineError as exc:
            raise InvalidRequest(str(exc)) from exc

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"],
            idempotency_key=row["idempotency_key"], started_at=row["started_at"],
            finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=HoNIRunRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"], warnings=tuple(json.loads(row["warnings_json"])),
            coverage=(CoverageReport.model_validate_json(row["coverage_json"])
                      if row["coverage_json"] else None),
            provenance=(Provenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"],
        )

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> HoNIScores:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        return HoNIScores.model_validate_json(payload)

    def scores(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        return {"artefact_id": a.artefact_id, "years": a.years, "countries": a.countries,
                "national": a.national, "notice": a.notice}

    def saturation(self, artefact_id: str) -> dict[str, Any]:
        a = self.artefact(artefact_id)
        return {"artefact_id": a.artefact_id, "years": a.years, "countries": a.countries,
                "capital_saturation": a.capital_saturation, "notice": a.notice}

    def country(self, artefact_id: str, code: str) -> CountryScores:
        a = self.artefact(artefact_id)
        codes = [c.code for c in a.countries]
        if code not in codes:
            raise NotFound(f"country {code!r} is not in artefact {artefact_id}")
        j = codes.index(code)
        column = lambda m: tuple(row[j] for row in m)  # noqa: E731
        cal = self.calibration(a.provenance.calibration_version)
        return CountryScores(
            artefact_id=a.artefact_id,
            country=a.countries[j],
            years=a.years,
            national=column(a.national),
            sectors={s: column(a.sectors[s]) for s in SECTORS},
            indices=tuple(IndexView(index=name, sector=INDICES[name], kind=cal.spec(name).kind,
                                    score=column(a.index_scores[name]),
                                    raw=column(a.index_raw[name])) for name in INDICES),
            capital_saturation=column(a.capital_saturation),
        )

    def peer_stats(self, artefact_id: str) -> PeerStats:
        a = self.artefact(artefact_id)
        return PeerStats(artefact_id=a.artefact_id, rows=peer_stats(a))

    def trends(self, artefact_id: str, window: int = 10, year: Optional[int] = None) -> HoNITrends:
        a = self.artefact(artefact_id)
        try:
            return trends(a, window, year)
        except EngineError as exc:
            raise InvalidRequest(str(exc)) from exc


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "D-05: the Guide mandates PostgreSQL; a driver is unavoidable"}


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
    if cal.missing_policy == "score_worst":
        out.append(f"calibration {cal.version} scores missing data as 1 (defect 9.1, kept for "
                   "reconciliation with MATLAB); not for publication")
    if coverage.sectors_reweighted:
        out.append(f"{coverage.sectors_reweighted} sector scores were re-weighted over missing indices")
    if coverage.sectors_unscored:
        out.append(f"{coverage.sectors_unscored} sector scores were left unscored: fewer than "
                   f"{cal.min_indices_per_sector} indices present")
    if coverage.national_unscored:
        out.append(f"{coverage.national_unscored} national scores are missing")
    if coverage.public_fills:
        pairs = {(f.country, f.series_id) for f in coverage.public_fills}
        out.append(f"{len(pairs)} input series are partly or wholly filled from public sources "
                   "by datafeed (see coverage.public_fills)")
    if coverage.excluded:
        out.append(f"{len(coverage.excluded)} country indices were dropped on datafeed's "
                   "plausibility findings (see coverage.excluded)")
    absent = [m for m in coverage.missing_series if m.missing_months == m.total_months]
    if absent:
        out.append(f"{len(absent)} country series are absent from the snapshot altogether")
    return out
