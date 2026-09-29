"""Orchestration: the only module that touches the store and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and never calls out.
lbs has no upstream engine: everything it reads is in the request. A run:

1. Resolves the calibration (the request's, else the active one from ``config.yaml``) and computes the
   idempotency key from the request, the calibration's content hash and the engine and contract versions.
   A key already answered is answered again, free.
2. Builds the sheet with the pure engine. Every missing input is a gap on the sheet; an unapproved record
   is a ``not_available`` section. Neither fails the run: a sheet with gaps is the honest sheet.
3. Stores the LifeBalanceSheet (append-only, by content hash) and the run.
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
from . import engine
from . import store as st
from .contracts import (
    CONTRACT_VERSIONS,
    FACTS_ADDED_1_4,
    ArtefactRequest,
    Calibration,
    Gap,
    LifeBalanceSheet,
    LifeBalanceSheetRequest,
    NotAvailable,
    Provenance,
    RunAccepted,
    RunStatus,
    ValidationReport,
)
from .settings import ROOT, Settings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def request_hash(request: LifeBalanceSheetRequest) -> str:
    """The request's content, without the calibration choice (which the key carries resolved). A goal's unstated
    ``contribution_share`` (additive since lbs@1.2.0, LBS-29), ``amount_basis`` and ``mandate.contribution_indexed``
    (since lbs@1.3.0, LBS-31) are left out, so a request that does not use them hashes as it did before. So are a
    person's unstated ``earning_power`` and the six ``facts`` added with it (since lbs@1.4.0, LBS-39)."""
    payload = request.model_dump(mode="json", exclude={"calibration_version"})
    for goal in payload["goals"]:
        if goal.get("contribution_share") is None:
            goal.pop("contribution_share", None)
        if goal.get("amount_basis") is None:  # lbs@1.3.0, LBS-31
            goal.pop("amount_basis", None)
    if payload.get("mandate") is not None and payload["mandate"].get("contribution_indexed") is None:
        payload["mandate"].pop("contribution_indexed", None)
    for person in (payload.get("household") or {}).get("persons", ()):
        if person.get("earning_power") is None:  # lbs@1.4.0, LBS-39
            person.pop("earning_power", None)
    for name in FACTS_ADDED_1_4:
        if payload["facts"].get(name) is None:  # lbs@1.4.0, LBS-39
            payload["facts"].pop(name, None)
    return content_id("REQ", payload)


def idempotency_key(request: LifeBalanceSheetRequest, cal: Calibration) -> str:
    return content_id("IDK", {"request_hash": request_hash(request), "calibration_hash": seeds.calibration_hash(cal),
                              "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS})


def build_sheet(request: LifeBalanceSheetRequest, cal: Calibration) -> LifeBalanceSheet:
    """The LifeBalanceSheet for one request under one calibration. Pure: the same inputs give the same bytes."""
    body, gaps, uses = engine.build(request, cal)
    provenance = Provenance(engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS,
                            calibration_version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                            idempotency_key=idempotency_key(request, cal), request_hash=request_hash(request),
                            as_of=request.as_of, records=uses)
    fields = dict(client_ref=request.client_ref, as_of=request.as_of, calibration_version=cal.version, gaps=gaps,
                  provenance=provenance, **body)
    draft = LifeBalanceSheet(artefact_id="", **fields)
    return LifeBalanceSheet(artefact_id=content_id("LBS", draft.model_dump(mode="json")), **fields)


def sections_of(sheet: LifeBalanceSheet) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("risk_profile", "mandate_proposal", "couple_cap"):
        value = getattr(sheet, name)
        out[name] = value.reason if isinstance(value, NotAvailable) else "available"
    for p in sheet.pensions:
        out[f"pensions.{p.person_id}.ahv"] = p.ahv.reason if isinstance(p.ahv, NotAvailable) else "available"
        out[f"pensions.{p.person_id}.bvg"] = p.bvg.reason if isinstance(p.bvg, NotAvailable) else "available"
    for h in sheet.human_capital:
        out[f"human_capital.{h.person_id}.earning_power"] = h.earning_power.reason
    return out


class Service:
    def __init__(self, settings: Settings, store: st.Store):
        self.settings = settings
        self.store = store
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
            "allowlist": allowlist, "upstream": {},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
            "notice": "Model-derived research output. Not investment advice.",
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

    def records(self, version: Optional[str] = None) -> dict[str, Any]:
        """``GET /records``: each content record's approval state in a calibration."""
        cal = self.calibration(version)
        out = {}
        for name, record in sorted(cal.records.items()):
            about = record.get("_about") or {}
            out[name] = {"approved": engine.approved(record), "provisional": about.get("provisional", True),
                         "published_by": about.get("published_by"), "decided_on": about.get("decided_on"),
                         "effective_from": about.get("effective_from")}
        return {"calibration_version": cal.version, "records": out}

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

    # -- validate and run --------------------------------------------------

    def _calibration_for(self, request: LifeBalanceSheetRequest) -> Calibration:
        """The request's calibration, and the checks on the request that need it (LBS-39)."""
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        problems = engine.earning_power_problems(request, cal)
        if problems:
            raise InvalidRequest("; ".join(problems))
        return cal

    def validate(self, request: LifeBalanceSheetRequest) -> ValidationReport:
        """``POST /validate``: every gap and every unavailable section, without storing anything."""
        try:
            cal = self._calibration_for(request)
        except InvalidRequest as exc:
            return ValidationReport(ok=False, client_ref=request.client_ref,
                                    calibration_version=request.calibration_version, problems=(str(exc),), gaps=(),
                                    sections={})
        sheet = build_sheet(request, cal)
        return ValidationReport(ok=True, client_ref=request.client_ref, calibration_version=cal.version,
                                problems=(), gaps=sheet.gaps, sections=sections_of(sheet))

    def submit(self, request: LifeBalanceSheetRequest) -> RunAccepted:
        cal = self._calibration_for(request)
        key = idempotency_key(request, cal)
        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded", artefact_id=done["artefact_id"],
                               idempotency_key=key, cached=True)
        started_at = st.utc_now()
        run_id = content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                    "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, status="running", started_at=started_at,
                          request_json=request.model_dump_json())
        try:
            sheet = build_sheet(request, cal)
        except (engine.EngineError, ValidationError, ValueError) as exc:
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", coverage_json=None, provenance_json=None,
                              error=f"{type(exc).__name__}: {exc}")
            return RunAccepted(run_id=run_id, status="failed", artefact_id=None, idempotency_key=key, cached=False)
        with self.store.session() as conn:
            st.put_artefact(conn, artefact_id=sheet.artefact_id, client_ref=sheet.client_ref,
                            request_hash=sheet.provenance.request_hash, idempotency_key=key,
                            contract_version=sheet.contract_version, payload_json=sheet.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=sheet.artefact_id,
                          warnings_json=json.dumps([g.model_dump() for g in sheet.gaps]),
                          coverage_json=json.dumps(sections_of(sheet)),
                          provenance_json=sheet.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=sheet.artefact_id, idempotency_key=key,
                           cached=False)

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=LifeBalanceSheetRequest.model_validate_json(row["request_json"]),
            artefact_id=row["artefact_id"], gaps=tuple(Gap(**g) for g in json.loads(row["warnings_json"])),
            provenance=Provenance.model_validate_json(row["provenance_json"]) if row["provenance_json"] else None,
            error=row["error"])

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, max(1, min(limit, 500)))
        out = []
        for r in rows:
            req = json.loads(r.pop("request_json"))
            out.append({**r, "client_ref": req["client_ref"], "as_of": req["as_of"],
                        "calibration_version": req.get("calibration_version")})
        return out

    # -- artefacts and engine specific reads -------------------------------

    def artefact(self, artefact_id: str) -> LifeBalanceSheet:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no life balance sheet {artefact_id!r}")
        return LifeBalanceSheet.model_validate_json(payload)

    def artefact_request(self, artefact_id: str) -> ArtefactRequest:
        """``GET /artefacts/{artefact_id}/request`` (LBS-40): the request the sheet was built from, from the run
        that built it (``run.request_json``). Its hash is recomputed and must equal the sheet's."""
        with self.store.session() as conn:
            row = st.request_for_artefact(conn, artefact_id)
        if row is None:
            raise NotFound(f"no life balance sheet {artefact_id!r}")
        request = LifeBalanceSheetRequest.model_validate_json(row["request_json"])
        digest = request_hash(request)
        if digest != row["request_hash"]:
            raise Conflict(f"the stored request of sheet {artefact_id} hashes to {digest}, not to the sheet's "
                           f"{row['request_hash']}; the sheet cannot be traced to its request")
        return ArtefactRequest(artefact_id=artefact_id, request_hash=digest, request=request)

    def section(self, artefact_id: str, name: str) -> dict[str, Any]:
        sheet = self.artefact(artefact_id)
        views = {
            "grid": lambda s: {"grid": [c.model_dump(mode="json") for c in s.grid],
                               "totals": s.totals.model_dump(mode="json")},
            "human-capital": lambda s: {"human_capital": [h.model_dump(mode="json") for h in s.human_capital]},
            "pensions": lambda s: {"pensions": [p.model_dump(mode="json") for p in s.pensions],
                                   "couple_cap": s.couple_cap.model_dump(mode="json")},
            "findings": lambda s: {"property": [p.model_dump(mode="json") for p in s.property],
                                   "liquidity": [p.model_dump(mode="json") for p in s.liquidity],
                                   "retirement": [p.model_dump(mode="json") for p in s.retirement],
                                   "observations": [p.model_dump(mode="json") for p in s.observations]},
            "mandate": lambda s: {"mandate_proposal": s.mandate_proposal.model_dump(mode="json"),
                                  "risk_profile": s.risk_profile.model_dump(mode="json")},
            "gaps": lambda s: {"gaps": [g.model_dump(mode="json") for g in s.gaps], "sections": sections_of(s)},
        }
        if name not in views:
            raise NotFound(f"no section {name!r}; known: {sorted(views)}")
        return {"artefact_id": sheet.artefact_id, "client_ref": sheet.client_ref, "as_of": sheet.as_of.isoformat(),
                **views[name](sheet), "notice": sheet.notice}


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow",
                       "pyyaml", "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "LBS-02: the Guide mandates PostgreSQL; a driver is unavoidable (as pcp PCP-02)"}


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
