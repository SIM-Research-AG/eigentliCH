"""Orchestration: the only module that touches both the store and the rules in ``engine``.

``api.py`` and the bootstrap both go through here, so an HTTP ingest and a bootstrap
ingest are the same code path and obey the same immutability rule.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from importlib import metadata
from typing import Any, Optional

from pydantic import ValidationError

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import store as st
from .contracts import (
    CONTRACT_VERSIONS,
    Calibration,
    Country,
    CoverageReport,
    ImportConversion,
    Panel,
    PanelRequest,
    RunAccepted,
    RunStatus,
    SeriesDefinition,
    SeriesSpec,
    Snapshot,
    SnapshotIn,
    month_index,
)
from .engine import assemble, axis, checksum, consumption_share_check, coverage, panel_of
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


class Service:
    def __init__(self, settings: Settings, store: st.Store):
        self.settings = settings
        self.store = store
        self.started = time.monotonic()

    # -- lifecycle -----------------------------------------------------------

    def startup(self) -> None:
        self.store.initialise()
        with self.store.session() as conn:
            for cal in seeds.SEEDS:
                try:
                    st.put_calibration(conn, version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                                       parent_version=cal.parent_version, payload_json=seeds.canonical_json(cal))
                except st.StoreConflict as exc:
                    raise st.StoreError(f"seed calibration {cal.version} changed; give it a new version") from exc
            if st.get_calibration(conn, self.settings.active_calibration) is None:
                raise st.StoreError(f"active calibration {self.settings.active_calibration!r} is not in the store")

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self) -> dict[str, Any]:
        with self.store.session() as conn:
            counts = st.table_counts(conn)
            versions = [r["version"] for r in st.list_calibrations(conn)]
        return {"engine": ENGINE, "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
                "calibration_version": self.settings.active_calibration, "calibration_versions": versions,
                "allowlist": allowlist_report(), "store": {**self.store.config.describe(), "counts": counts},
                "admin_ingest": self.settings.admin_token is not None,
                "config_sources": list(self.settings.sources)}

    # -- calibration -----------------------------------------------------------

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

    # -- registry (tables country and series) -----------------------------------

    def countries(self) -> list[Country]:
        with self.store.session() as conn:
            rows = st.get_countries(conn)
        return [Country(code=r["code"], name=r["name"], iso3=r["iso3"], matlab=r["matlab_field"]) for r in rows]

    def series_specs(self) -> list[SeriesSpec]:
        with self.store.session() as conn:
            rows = st.get_series_specs(conn)
        return [SeriesSpec(series_id=r["series_id"], category=r["category"], unit=r["unit"], period=r["period"],
                           indices=tuple(json.loads(r["indices_json"])), matlab_sheet=r["matlab_sheet"],
                           matlab_column=r["matlab_column"], zero_is_a_value=bool(r["zero_is_a_value"]),
                           description=r["description"])
                for r in rows]

    def seed_registry(self, countries: list[Country], series: list[SeriesSpec]) -> tuple[int, list[str]]:
        """Insert missing registry rows. The database wins: a differing row is kept and reported.
        Returns (rows added, differences)."""
        have_c = {c.code: c for c in self.countries()}
        have_s = {s.series_id: s for s in self.series_specs()}
        added, differ = 0, []
        with self.store.session() as conn:
            for c in countries:
                if c.code in have_c:
                    if have_c[c.code] != c:
                        differ.append(f"country {c.code}: database {have_c[c.code].model_dump()} kept")
                    continue
                added += st.insert_country(conn, code=c.code, name=c.name, iso3=c.iso3, matlab_field=c.matlab)
            for s in series:
                if s.series_id in have_s:
                    have = have_s[s.series_id]
                    if not have.description and s.description:
                        st.describe_series(conn, series_id=s.series_id, description=s.description)
                        have = have.model_copy(update={"description": s.description})
                    if have != s:
                        differ.append(f"series {s.series_id}: database version kept")
                    continue
                added += st.insert_series(conn, series_id=s.series_id, category=s.category, unit=s.unit,
                                          period=s.period, indices_json=json.dumps(list(s.indices)),
                                          matlab_sheet=s.matlab_sheet, matlab_column=s.matlab_column,
                                          zero_is_a_value=s.zero_is_a_value, description=s.description)
        return added, differ

    def check_fills(self) -> list[str]:
        """Fill candidates in config.yaml that name something the registry does not hold."""
        codes = {c.code for c in self.countries()}
        ids = {s.series_id for s in self.series_specs()}
        return [f"fill {f.country}/{f.series}: unregistered country or series"
                for f in self.settings.fills
                if f.country not in codes or f.series not in ids or (f.anchor and f.anchor not in ids)]

    def put_conversions(self, snapshot_id: str, conversions: dict[str, dict[str, int]]) -> bool:
        """Record the importer's counts for a snapshot, once. False if already recorded."""
        with self.store.session() as conn:
            if st.has_conversions(conn, snapshot_id):
                return False
            st.put_conversions(conn, snapshot_id, [
                (*key.split("/", 1), c.get("nan", 0), c.get("leading_zero", 0), c.get("trailing_zero", 0),
                 c.get("interior_zero", 0), c.get("placeholder", 0))
                for key, c in sorted(conversions.items())])
        return True

    def conversions(self, snapshot_id: str) -> list[ImportConversion]:
        self.snapshot(snapshot_id)
        with self.store.session() as conn:
            return [ImportConversion(**r) for r in st.get_conversions(conn, snapshot_id)]

    # -- snapshots -------------------------------------------------------------

    def ingest(self, snapshot: SnapshotIn, calibration_version: Optional[str] = None) -> tuple[Snapshot, bool]:
        """Write a snapshot. Returns (manifest, created). The same content again is a no-op;
        different content under a used id is refused."""
        codes = {c.code for c in self.countries()}
        ids = {s.series_id for s in self.series_specs()}
        unknown = sorted({f"{s.definition.country}/{s.definition.series_id}" for s in snapshot.series
                          if s.definition.country not in codes or s.definition.series_id not in ids})
        if unknown:
            raise InvalidRequest(f"unregistered country or series: {unknown[:5]}")
        panel = panel_of(snapshot)
        digest = checksum(panel)
        with self.store.session() as conn:
            existing = st.snapshot_checksum(conn, snapshot.snapshot_id)
            if existing is not None:
                if existing != digest:
                    raise Conflict(f"snapshot {snapshot.snapshot_id} exists with different content; "
                                   "snapshots are immutable, give the new one a new id")
                return Snapshot.model_validate_json(st.get_manifest(conn, snapshot.snapshot_id)), False
            if snapshot.parent_id and st.snapshot_checksum(conn, snapshot.parent_id) is None:
                raise InvalidRequest(f"parent snapshot {snapshot.parent_id!r} does not exist")
            manifest = Snapshot(
                snapshot_id=snapshot.snapshot_id, parent_id=snapshot.parent_id, source=snapshot.source,
                primary_source=snapshot.primary_source, as_of=snapshot.as_of, built_at=st.utc_now(),
                calibration_version=calibration_version or self.settings.active_calibration,
                first_date=snapshot.first_date, last_date=snapshot.last_date,
                countries=tuple(sorted({s.definition.country for s in snapshot.series})),
                series=tuple(sorted({s.definition.series_id for s in snapshot.series})),
                cells_present=sum(len(s.cells) for s in snapshot.series),
                checksum=digest, note=snapshot.note, fills=snapshot.fills,
                market=snapshot.market)
            st.put_snapshot(
                conn, snapshot_id=snapshot.snapshot_id, parent_id=snapshot.parent_id, checksum=digest,
                manifest_json=manifest.model_dump_json(),
                definitions=[(s.definition.country, s.definition.series_id, s.definition.model_dump_json())
                             for s in snapshot.series],
                cells=[(s.definition.country, s.definition.series_id, c.date, c.value, c.flag, c.source)
                       for s in snapshot.series for c in s.cells])
        return manifest, True

    def snapshots(self) -> list[Snapshot]:
        with self.store.session() as conn:
            return [Snapshot.model_validate_json(m) for m in st.list_manifests(conn)]

    def snapshot(self, snapshot_id: str) -> Snapshot:
        with self.store.session() as conn:
            payload = st.get_manifest(conn, snapshot_id)
        if payload is None:
            raise NotFound(f"no snapshot {snapshot_id!r}")
        return Snapshot.model_validate_json(payload)

    def series(self, snapshot_id: Optional[str] = None, country: Optional[str] = None,
               category: Optional[str] = None, index: Optional[str] = None) -> list[SeriesDefinition]:
        snapshot_id = snapshot_id or self._latest()
        self.snapshot(snapshot_id)
        with self.store.session() as conn:
            defs = [SeriesDefinition.model_validate_json(p) for p in st.get_definitions(conn, snapshot_id)]
        return [d for d in defs if (not country or d.country == country)
                and (not category or d.category == category) and (not index or index in d.indices)]

    def _latest(self) -> str:
        snaps = self.snapshots()
        if not snaps:
            raise NotFound("the store holds no snapshot yet. Run: python -m datafeed bootstrap")
        return snaps[0].snapshot_id

    # -- panels ------------------------------------------------------------------

    def panel(self, request: PanelRequest) -> Panel:
        manifest = self.snapshot(request.snapshot_id)
        series = request.series or manifest.series
        countries = request.countries or manifest.countries
        unknown = [s for s in series if s not in manifest.series] + \
                  [c for c in countries if c not in manifest.countries]
        if unknown:
            raise InvalidRequest(f"not in snapshot {manifest.snapshot_id}: {unknown}")
        first = max(manifest.first_date, request.start) if request.start else manifest.first_date
        last = min(manifest.last_date, request.end) if request.end else manifest.last_date
        if month_index(first) > month_index(last):
            raise InvalidRequest("the requested window holds no month of the snapshot")
        dates = axis(first, last)
        with self.store.session() as conn:
            rows = st.get_cells(conn, manifest.snapshot_id, series=series, countries=countries,
                                start=dates[0], end=dates[-1])
            defs = {(d.country, d.series_id): d for d in
                    (SeriesDefinition.model_validate_json(p) for p in st.get_definitions(conn, manifest.snapshot_id))}
        cells: dict[tuple[str, str], dict[str, tuple]] = {}
        for country, series_id, date, value, flag, source in rows:
            cells.setdefault((country, series_id), {})[date] = (value, flag, source)
        keys = [(c, s) for c in countries for s in series if (c, s) in defs]
        return assemble(snapshot_id=manifest.snapshot_id, as_of=manifest.as_of,
                        primary_source=manifest.primary_source, dates=dates,
                        units={k: defs[k].unit for k in keys}, cells=cells, keys=keys)

    def coverage(self, snapshot_id: str) -> CoverageReport:
        panel = self.panel(PanelRequest(snapshot_id=snapshot_id))
        return CoverageReport(snapshot_id=snapshot_id, rows=coverage(panel),
                              plausibility=consumption_share_check(
                                  panel, self.calibration().consumption_share_bounds))

    # -- runs: a materialised panel is the artefact ------------------------------

    def submit(self, request: PanelRequest) -> RunAccepted:
        manifest = self.snapshot(request.snapshot_id)
        key = content_id("IDK", {"request": request.model_dump(mode="json"), "checksum": manifest.checksum,
                                 "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS})
        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
        if done:
            return RunAccepted(run_id=done["run_id"], status="succeeded", artefact_id=done["artefact_id"],
                               idempotency_key=key, cached=True)
        started_at = st.utc_now()
        run_id = content_id("RUN", {"key": key, "at": started_at, "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, started_at=started_at,
                          request_json=request.model_dump_json())
        try:
            panel = self.panel(request)
        except (InvalidRequest, NotFound, ValidationError) as exc:
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", wall_clock_ms=(time.perf_counter() - t0) * 1e3,
                              artefact_id=None, warnings_json="[]", coverage_json=None, provenance_json=None,
                              error=f"{type(exc).__name__}: {exc}")
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None, idempotency_key=key, cached=False)
        artefact_id = content_id("PNL", panel.model_dump(mode="json"))
        report = CoverageReport(snapshot_id=panel.snapshot_id, rows=coverage(panel))
        provenance = {"snapshot_id": panel.snapshot_id, "snapshot_checksum": manifest.checksum,
                      "engine_version": ENGINE_VERSION, "idempotency_key": key,
                      "calibration_version": manifest.calibration_version, "as_of": manifest.as_of}
        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=artefact_id, idempotency_key=key,
                            contract_version=panel.contract_version, payload_json=panel.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", wall_clock_ms=(time.perf_counter() - t0) * 1e3,
                          artefact_id=artefact_id, warnings_json=json.dumps(_warnings(report)),
                          coverage_json=report.model_dump_json(), provenance_json=json.dumps(provenance),
                          error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=artefact_id,
                           idempotency_key=key, cached=False)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=PanelRequest.model_validate_json(row["request_json"]), artefact_id=row["artefact_id"],
            warnings=tuple(json.loads(row["warnings_json"])),
            coverage=CoverageReport.model_validate_json(row["coverage_json"]) if row["coverage_json"] else None,
            provenance=json.loads(row["provenance_json"]) if row["provenance_json"] else None,
            error=row["error"])

    def artefact(self, artefact_id: str) -> Panel:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no artefact {artefact_id!r}")
        return Panel.model_validate_json(payload)

    def public_fetches(self) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return st.public_fetches(conn)




def _warnings(report: CoverageReport) -> list[str]:
    missing = sum(r.missing for r in report.rows)
    public = sum(r.from_public_sources for r in report.rows)
    out = []
    if missing:
        out.append(f"{missing} cells are missing")
    if public:
        out.append(f"{public} cells come from public sources, not the primary feed")
    return out


ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})
ADMITTED = {"psycopg": "D-05: the Guide mandates PostgreSQL; a driver is unavoidable"}


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
        packages[name] = {"requirement": requirement, "installed": installed,
                          "allowed": name in ALLOWLIST, "admitted_by": ADMITTED.get(name)}
    return {"ok": all(p["allowed"] or p["admitted_by"] for p in packages.values()), "packages": packages}
