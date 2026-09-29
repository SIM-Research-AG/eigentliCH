"""Orchestration: the only module that touches the store, the upstream engines and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` and ``render.py`` are called from here and
never call out. A report:

1. Resolves the calibration and computes the idempotency key from the request (client, kind, language, the
   source artefact ids, the previous report, the display facts, whether prose is wanted, and for a revision
   the revised report and the curator's note, REP-25), the calibration's
   content hash, and, when prose is wanted, the model's name and host and the prompt version and hash. Source
   artefacts are content-addressed and append-only upstream, so their ids stand for their content (REP-11).
   A key already answered by a complete report is answered again from the store, free (REP-07).
2. Reads every source from its engine and refuses, before anything is written, an artefact that is not
   there, one that breaks its contract, one about another client, and an update whose previous report is
   missing or another client's, and a revision whose revised report is missing or another client's (every
   refusal names its reason).
3. Extracts the facts (the code owns every figure), adds the changes for an update, and lays out the
   sections in their fixed order.
4. Asks the model for each section's connecting sentences, checks each draft, and redrafts; if the model
   cannot be reached the report is still produced, without prose, with a warning, and marked incomplete, so
   a repeat of the request tries again.
5. Renders the HTML and stores the report.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tomllib
from importlib import metadata
from typing import Any, Optional
from urllib.parse import urlparse

from pydantic import ValidationError

from . import ENGINE, ENGINE_VERSION, calibration as seeds
from . import engine, render
from . import vocabulary as voc
from . import store as st
from .clients import EngineClient, NotFoundUpstream, UpstreamError
from .contracts import (
    CONTRACT_VERSIONS,
    Calibration,
    Fact,
    ModelUse,
    Report,
    ReportProvenance,
    ReportRequest,
    RunAccepted,
    RunStatus,
    Section,
    SourceUse,
)
from .settings import ROOT, Settings
from .spark7 import ModelError, ModelUnavailable, Spark7Client, Warmer


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


class Refused(ValueError):
    """The request is valid, and the engine cannot report on it as asked. The message says why."""


class Unavailable(RuntimeError):
    """An upstream engine is needed and is not there."""


class RunFailed(RuntimeError):
    def __init__(self, run_id: str, idempotency_key: str, error: str, kind: type[Exception]):
        super().__init__(error)
        self.run_id = run_id
        self.idempotency_key = idempotency_key
        self.kind = kind


class _KeyLocks:
    """One lock per idempotency key, created on demand, dropped when nobody holds it."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, list[Any]] = {}

    def acquire(self, key: str) -> threading.Lock:
        with self._guard:
            entry = self._locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
            lock = entry[0]
        lock.acquire()
        return lock

    def release(self, key: str, lock: threading.Lock) -> None:
        lock.release()
        with self._guard:
            entry = self._locks.get(key)
            if entry is not None:
                entry[1] -= 1
                if entry[1] <= 0:
                    del self._locks[key]


class Service:
    def __init__(self, settings: Settings, store: st.Store, upstream: dict[str, EngineClient], model: Spark7Client):
        self.settings = settings
        self.store = store
        self.upstream = upstream
        self.model = model
        self.warmer = Warmer(model, settings.model.warmup_interval_s)
        self.started = time.monotonic()
        self._locks = _KeyLocks()

    # -- lifecycle ---------------------------------------------------------

    def startup(self, warmup: bool = True) -> None:
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
        if warmup and self.settings.model.warmup_enabled:
            self.warmer.start()

    def shutdown(self) -> None:
        self.warmer.stop()
        self.model.close()
        for client in self.upstream.values():
            client.close()

    # -- standard endpoints ------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3), "model": self.settings.model.model,
                "warmup": self.warmer.status()}

    def meta(self, allowlist: dict[str, Any]) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
        return {
            "engine": ENGINE, "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": self.settings.active_calibration, "calibration_versions": versions,
            "prompt_version": engine.PROMPT_VERSION, "prompt_hash": engine.prompt_hash(),
            "sections": list(engine.SECTION_KEYS), "allowlist": allowlist,
            "upstream": {name: c.base_url for name, c in self.upstream.items()},
            "model": {**self.settings.model.describe(self.settings.env), "warmup_status": self.warmer.status()},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
        }

    def model_status(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            served = self.model.models()
        except (ModelUnavailable, ModelError) as exc:
            return {"reachable": False, "error": f"{type(exc).__name__}: {exc}",
                    "ms": round((time.perf_counter() - t0) * 1000.0, 1),
                    **self.settings.model.describe(self.settings.env)}
        return {"reachable": True, "serves_configured_model": self.settings.model.model in served,
                "served": served, "ms": round((time.perf_counter() - t0) * 1000.0, 1),
                **self.settings.model.describe(self.settings.env)}

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

    # -- keys ----------------------------------------------------------------

    @staticmethod
    def request_id(request: ReportRequest) -> str:
        payload = request.model_dump(mode="json", exclude={"calibration_version"})
        # The revision fields (REP-25) enter the id only when given, so every request without them keeps the id
        # (and the key) it had before they existed.
        for field in ("revision_of", "revision_note"):
            if payload.get(field) is None:
                payload.pop(field, None)
        return engine.content_id("RRQ", payload)

    def _model_use(self) -> ModelUse:
        m = self.settings.model
        return ModelUse(service=m.service, host=urlparse(m.base_url).hostname or "", model=m.model,
                        prompt_version=engine.PROMPT_VERSION, prompt_hash=engine.prompt_hash())

    def idempotency_key(self, request: ReportRequest, cal: Calibration) -> str:
        return engine.content_id("IDK", {
            "request": self.request_id(request), "calibration_hash": seeds.calibration_hash(cal),
            "model": self._model_use().model_dump() if request.prose else None,
            "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
        })

    # -- runs --------------------------------------------------------------

    def submit(self, request: ReportRequest) -> RunAccepted:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        key = self.idempotency_key(request, cal)
        lock = self._locks.acquire(key)
        try:
            return self._submit_locked(request, cal, key)
        finally:
            self._locks.release(key, lock)

    def _submit_locked(self, request: ReportRequest, cal: Calibration, key: str) -> RunAccepted:
        with self.store.session() as conn:
            done = st.complete_run_for_key(conn, key)
        if done is not None:
            return RunAccepted(run_id=done["run_id"], status="succeeded", artefact_id=done["artefact_id"],
                               idempotency_key=key, cached=True)
        started_at = st.utc_now()
        run_id = engine.content_id("RUN", {"idempotency_key": key, "started_at": started_at,
                                           "nonce": time.perf_counter_ns()})
        t0 = time.perf_counter()
        with self.store.session() as conn:
            st.insert_run(conn, run_id=run_id, idempotency_key=key, status="running", started_at=started_at,
                          request_json=request.model_dump_json())
        try:
            report = self._execute(request, cal, key)
        except (Refused, Unavailable, engine.EngineError, ValidationError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", provenance_json=None, error=error)
            raise RunFailed(run_id, key, error, type(exc)) from exc
        with self.store.session() as conn:
            winner = st.put_artefact(conn, artefact_id=report.artefact_id, idempotency_key=key,
                                     complete=report.complete, client_ref=report.client_ref, kind=report.kind,
                                     language=report.language, previous_report_id=report.previous_report_id,
                                     contract_version=report.contract_version, payload_json=report.model_dump_json())
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=winner,
                          warnings_json=json.dumps(list(report.warnings)),
                          provenance_json=report.provenance.model_dump_json(), error=None)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=winner, idempotency_key=key,
                           cached=winner != report.artefact_id)

    def report(self, request: ReportRequest) -> Report:
        """``POST /report``: :meth:`submit`, returning the report itself."""
        return self.artefact(self.submit(request).artefact_id or "")

    # -- producing a report -------------------------------------------------

    def _sources(self, request: ReportRequest) -> list[Any]:
        fetched = []
        for ref in request.sources:
            client = self.upstream.get(ref.engine)
            if client is None:
                raise Refused(f"no extractor for engine {ref.engine!r}")
            try:
                got = client.fetch(ref.artefact_id)
            except NotFoundUpstream as exc:
                raise Refused(str(exc)) from exc
            except UpstreamError as exc:
                raise Unavailable(str(exc)) from exc
            about = got.extractor.client_ref(got.artefact)
            if about is not None and about != request.client_ref:
                raise Refused(f"{ref.engine} artefact {ref.artefact_id} is about client {about!r}, not "
                              f"{request.client_ref!r}; a report never draws on another client's artefact")
            fetched.append(got)
        return fetched

    def _previous(self, request: ReportRequest) -> Optional[Report]:
        if request.previous_report_id is None:
            return None
        try:
            previous = self.artefact(request.previous_report_id)
        except NotFound as exc:
            raise Refused(f"the previous report {request.previous_report_id!r} does not exist") from exc
        if previous.client_ref != request.client_ref:
            raise Refused(f"the previous report {previous.artefact_id} is about another client")
        return previous

    def _revised(self, request: ReportRequest) -> Optional[Report]:
        """The report a revision revises: it must exist and be this client's (REP-25, as REP-10)."""
        if request.revision_of is None:
            return None
        try:
            revised = self.artefact(request.revision_of)
        except NotFound as exc:
            raise Refused(f"the revised report {request.revision_of!r} does not exist") from exc
        if revised.client_ref != request.client_ref:
            raise Refused(f"the revised report {revised.artefact_id} is about another client")
        return revised

    def _execute(self, request: ReportRequest, cal: Calibration, key: str) -> Report:
        lang = request.language
        fetched = self._sources(request)
        previous = self._previous(request)
        self._revised(request)
        request_id = self.request_id(request)

        facts: list[Fact] = []
        for got in fetched:
            facts.extend(got.extractor.extract(got.artefact, cal, lang))
        dated = [(got.extractor.as_of(got.artefact), got.engine, got.artefact.artefact_id,
                  got.extractor.contract_version) for got in fetched]
        facts.append(engine.as_of_fact(dated, lang))
        if previous is not None:
            facts = engine.change_facts(previous, facts, lang) + facts
        facts.extend(engine.source_date_facts(dated, previous, lang))
        facts.extend(engine.caller_facts(request.display_facts, request_id, lang))
        facts.extend(engine.revision_facts(request.revision_note, request_id, lang))

        # Subjects named for readers (REP-20): generic names from the lbs sheet, the caller's names on the page.
        subject_names: dict[str, str] = {}
        for got in fetched:
            if got.engine == "lbs":
                subject_names.update(engine.lbs_subjects(got.artefact, lang))
        facts = [_resolve_mandate(f, subject_names) for f in facts]
        names = voc.display_names(request.display_facts, subject_names)

        warnings: list[str] = []
        notes: list[str] = []
        assistant = self.settings.model.display_name
        sections: list[Section] = []
        degraded: Optional[str] = None
        by = {f.fact_id: f for f in facts}
        for key_, ids in engine.sections_for(facts):
            title = engine.section_title(key_, lang)
            section_facts = [by[i] for i in ids]
            if not request.prose:
                sections.append(Section(key=key_, title=title, fact_ids=ids, prose_status="not_requested"))
                continue
            if key_ not in cal.slots:
                sections.append(Section(key=key_, title=title, fact_ids=ids, prose_status="no_slot"))
                continue
            if degraded is not None:
                sections.append(Section(key=key_, title=title, fact_ids=ids, prose_status="unavailable",
                                        prose_note=degraded))
                continue
            section, degraded = self._prose(key_, title, ids, section_facts, cal, lang)
            sections.append(section)
            if section.prose_status == "flagged":
                warnings.append(f"the prose of section {key_!r} is withheld: it quotes "
                                f"{', '.join(section.unverified_numbers)}, which match none of its facts")
                notes.append(voc.page_note("prose_withheld", lang, title=title))
        if degraded is not None:
            warnings.insert(0, f"the connecting prose is missing ({degraded}). The report stands without it; asking "
                               "again tries again.")
            notes.insert(0, voc.page_note("prose_missing", lang, assistant=assistant))

        provenance = ReportProvenance(
            engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS, calibration_version=cal.version,
            calibration_hash=seeds.calibration_hash(cal), idempotency_key=key, request_id=request_id,
            sources=tuple(SourceUse(engine=g.engine, artefact_id=g.artefact.artefact_id,
                                    contract_version=g.extractor.contract_version, sha256=g.sha256, url=g.url)
                          for g in fetched),
            previous_report_id=request.previous_report_id,
            model=self._model_use() if request.prose else None)
        as_of = str(by["sources.as_of"].value) if "sources.as_of" in by else ""
        client_name = next((str(f.value) for f in request.display_facts if f.key == "name"), None)
        title = render.plain_title(lang, request.kind, client_name)
        html = render.render(lang=lang, kind=request.kind, title=title, facts=facts, sections=sections,
                             warnings=notes, provenance=provenance, calibration_version=cal.version,
                             engine_version=ENGINE_VERSION, assistant=assistant, names=names)
        body = dict(client_ref=request.client_ref, kind=request.kind, language=lang, title=title,
                    previous_report_id=request.previous_report_id, revision_of=request.revision_of,
                    revision_note=request.revision_note, as_of=as_of, facts=tuple(facts),
                    sections=tuple(sections), complete=degraded is None, warnings=tuple(warnings), html=html,
                    provenance=provenance)
        draft = Report(artefact_id="", **body)
        return Report(artefact_id=engine.content_id("REP", draft.model_dump(mode="json", exclude={"artefact_id"})),
                      **body)

    def _prose(self, key: str, title: str, ids: tuple[str, ...], facts: list[Fact], cal: Calibration,
               lang: str) -> tuple[Section, Optional[str]]:
        """One section's connecting sentences, checked. Returns the section and, if the model could not be
        reached, the reason (which stops prose for the rest of the report)."""
        g = cal.prose
        messages = engine.prose_messages(title, facts, cal.slots[key][lang], lang)
        last = Section(key=key, title=title, fact_ids=ids, prose_status="rejected", prose_note="no draft")
        for attempt in range(1, g.attempts + 1):
            try:
                done = self.model.complete(messages, max_tokens=g.max_tokens, temperature=g.temperature, seed=g.seed)
            except (ModelUnavailable, ModelError) as exc:
                reason = f"{type(exc).__name__}: {exc}"
                return Section(key=key, title=title, fact_ids=ids, prose_status="unavailable", prose_note=reason,
                               prose_attempts=attempt), reason
            text = engine.clean(done.text, lang)
            why = engine.reject_reason(text, lang, cal)
            if why:
                last = Section(key=key, title=title, fact_ids=ids, prose_status="rejected", prose_model=done.model,
                               prose_attempts=attempt, prose_note=why)
                continue
            bad = engine.unverified_numbers(text, facts, cal)
            last = Section(key=key, title=title, fact_ids=ids, prose=text,
                           prose_status="flagged" if bad else "verified", prose_model=done.model,
                           unverified_numbers=bad, prose_attempts=attempt,
                           prose_note=("numbers match none of the section's facts" if bad else None))
            if not bad:
                break
        return last, None

    # -- reads ------------------------------------------------------------------

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=ReportRequest.model_validate_json(row["request_json"]), artefact_id=row["artefact_id"],
            warnings=tuple(json.loads(row["warnings_json"])),
            provenance=(ReportProvenance.model_validate_json(row["provenance_json"])
                        if row["provenance_json"] else None),
            error=row["error"])

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, max(1, min(limit, 500)))
        out = []
        for r in rows:
            req = json.loads(r.pop("request_json"))
            out.append({**r, "request_client_ref": req["client_ref"], "request_kind": req["kind"],
                        "sources": [f"{s['engine']}:{s['artefact_id']}" for s in req["sources"]]})
        return out

    def artefact(self, artefact_id: str) -> Report:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no report {artefact_id!r}")
        return Report.model_validate_json(payload)

    def reports(self, client_ref: Optional[str], limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return st.list_reports(conn, client_ref, max(1, min(limit, 500)))


def _resolve_mandate(fact: Fact, subject_names: dict[str, str]) -> Fact:
    """pcp's mandate built from an lbs proposal is named ``lbs-<goal_id>``: shown as that goal (REP-20)."""
    if fact.fact_id != "pcp.mandate_name" or not isinstance(fact.value, str):
        return fact
    m = re.match(r"^lbs-(.+)$", fact.value)
    goal = subject_names.get(f"goal:{m.group(1)}") if m else None
    return fact.model_copy(update={"display": goal}) if goal else fact


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow", "pyyaml",
                       "httpx", "pytest", "hypothesis"})

ADMITTED = {"psycopg": "REP-02: the Guide mandates PostgreSQL; a driver is unavoidable (as pcp PCP-02)"}


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
