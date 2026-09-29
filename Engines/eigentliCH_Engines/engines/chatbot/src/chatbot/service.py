"""Orchestration: the only module that touches the store and the model.

``api.py`` routes to this module and nothing else; ``engine.py`` is called from here and never calls out.
A question:

1. Resolves the calibration and computes the idempotency key from the whole request (question, language,
   grounding, client facts, history), the calibration's content hash, the model's name and host, the
   prompt version and hash, and the engine and contract versions. The model is not deterministic, so the
   key cannot promise the same text from a second call; it promises the same *stored* answer: a key
   already answered is answered again from the store, free, and the model is not called (CHB-06).
2. Refuses without a model call only a question with no word in it (CHB-19). A question without grounding
   is answered, from general knowledge (CHB-18).
3. Asks the model for ``{status, from_notes, general, cited}`` under guided decoding. A reply that is not
   that object, or that leaves the language, is redrafted up to ``generation.attempts`` times; then the run
   fails. ``status`` ``out_of_domain`` or ``unintelligible`` is a refusal (``not_covered``) with the
   calibration's fixed text.
4. Composes the reader's text: the part from the notes, then the general part under the calibration's
   marking line (``basis`` says which). Repairs presentation and orthography, keeps only citations of given
   notes, and checks every number in the answer against the sources it was allowed to use.

Concurrent identical requests in one process wait for the first (a lock per key), so the model is called
once; across processes the unique key in the store settles it (``store.put_artefact``).
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
from . import engine
from . import store as st
from .contracts import (
    CONTRACT_VERSIONS,
    NOTICE,
    Calibration,
    ChatAnswer,
    ChatRequest,
    ModelUse,
    Provenance,
    RunAccepted,
    RunStatus,
)
from .settings import ROOT, Settings
from .spark7 import ModelError, ModelUnavailable, Spark7Client, Warmer


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidRequest(ValueError):
    pass


class Unavailable(RuntimeError):
    """The model is needed and cannot answer now."""


class BadModelOutput(RuntimeError):
    """The model answered, and nothing usable came of it."""


class RunFailed(RuntimeError):
    """A run was recorded as failed; the message is its error."""

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
    def __init__(self, settings: Settings, store: st.Store, model: Spark7Client):
        self.settings = settings
        self.store = store
        self.model = model
        self.warmer = Warmer(model, settings.model.warmup_interval_s)
        self.started = time.monotonic()
        self._locks = _KeyLocks()

    # -- lifecycle ---------------------------------------------------------

    def startup(self, warmup: bool = True) -> None:
        """Create tables, write the seed calibrations, check the active one exists, start the warm-up."""
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

    # -- standard endpoints ------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "engine": ENGINE, "engine_version": ENGINE_VERSION,
                "uptime_s": round(time.monotonic() - self.started, 3), "model": self.settings.model.model,
                "model_display_name": self.settings.model.display_name, "warmup": self.warmer.status()}

    def meta(self, allowlist: dict[str, Any]) -> dict[str, Any]:
        with self.store.session() as conn:
            versions = [r["version"] for r in st.list_calibrations(conn)]
            counts = st.table_counts(conn)
        return {
            "engine": ENGINE, "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": self.settings.active_calibration, "calibration_versions": versions,
            "prompt_version": engine.PROMPT_VERSION, "prompt_hash": self.prompt_hash(),
            "allowlist": allowlist,
            "model": {**self.settings.model.describe(self.settings.env), "warmup_status": self.warmer.status()},
            "store": {**self.store.config.describe(), "counts": counts},
            "config_sources": list(self.settings.sources),
        }

    def model_status(self) -> dict[str, Any]:
        """``GET /model``: a live probe of the model service (``/v1/models``)."""
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

    def prompt_hash(self) -> str:
        return engine.prompt_hash(self.settings.model.display_name)

    @staticmethod
    def request_hash(request: ChatRequest) -> str:
        body = request.model_dump(mode="json", exclude={"calibration_version"})
        return engine.content_id("REQ", body)

    def idempotency_key(self, request: ChatRequest, cal: Calibration) -> str:
        m = self.settings.model
        return engine.content_id("IDK", {
            "request": self.request_hash(request), "calibration_hash": seeds.calibration_hash(cal),
            "model": m.model, "model_host": urlparse(m.base_url).hostname, "prompt_version": engine.PROMPT_VERSION,
            "prompt_hash": self.prompt_hash(), "engine_version": ENGINE_VERSION,
            "contract_versions": CONTRACT_VERSIONS,
        })

    # -- runs --------------------------------------------------------------

    def submit(self, request: ChatRequest) -> RunAccepted:
        try:
            cal = self.calibration(request.calibration_version)
        except NotFound as exc:
            raise InvalidRequest(str(exc)) from exc
        if cal.general is None:
            raise InvalidRequest(f"calibration {cal.version} predates general answers (CHB-18) and is not run by "
                                 f"this engine version; use {self.settings.active_calibration} or a later one")
        try:
            engine.check_limits(request, cal)
            engine.recent_history(request.history, cal)
        except engine.EngineError as exc:
            raise InvalidRequest(str(exc)) from exc
        key = self.idempotency_key(request, cal)
        lock = self._locks.acquire(key)
        try:
            return self._submit_locked(request, cal, key)
        finally:
            self._locks.release(key, lock)

    def _submit_locked(self, request: ChatRequest, cal: Calibration, key: str) -> RunAccepted:
        with self.store.session() as conn:
            done = st.succeeded_run_for_key(conn, key)
            stored = st.artefact_for_key(conn, key) if done is None else None
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
        if stored is not None:
            # Another process stored an answer under this key and its run is not finished yet: this run is
            # answered with that answer and records it, without a model call.
            answer = self.artefact(stored)
            self._finish(run_id, t0, answer)
            return RunAccepted(run_id=run_id, status="succeeded", artefact_id=stored, idempotency_key=key,
                               cached=True)
        try:
            answer = self._execute(request, cal, key)
        except (Unavailable, BadModelOutput, engine.EngineError, ValidationError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            with self.store.session() as conn:
                st.finish_run(conn, run_id=run_id, status="failed", finished_at=st.utc_now(),
                              wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=None,
                              warnings_json="[]", provenance_json=None, error=error)
            raise RunFailed(run_id, key, error, type(exc)) from exc

        with self.store.session() as conn:
            winner = st.put_artefact(
                conn, artefact_id=answer.artefact_id, idempotency_key=key, contract_version=answer.contract_version,
                language=answer.language, model=answer.model, prompt_version=answer.prompt_version,
                refused=answer.refused, unverified_count=len(answer.unverified_numbers),
                latency_ms=answer.latency_ms, payload_json=answer.model_dump_json())
        lost = winner != answer.artefact_id
        if lost:
            answer = self.artefact(winner)
        self._finish(run_id, t0, answer)
        return RunAccepted(run_id=run_id, status="succeeded", artefact_id=answer.artefact_id, idempotency_key=key,
                           cached=lost)

    def _finish(self, run_id: str, t0: float, answer: ChatAnswer) -> None:
        with self.store.session() as conn:
            st.finish_run(conn, run_id=run_id, status="succeeded", finished_at=st.utc_now(),
                          wall_clock_ms=(time.perf_counter() - t0) * 1000.0, artefact_id=answer.artefact_id,
                          warnings_json=json.dumps(list(answer.warnings)),
                          provenance_json=answer.provenance.model_dump_json(), error=None)

    def answer(self, request: ChatRequest) -> ChatAnswer:
        """``POST /answer``: :meth:`submit`, returning the answer itself."""
        accepted = self.submit(request)
        return self.artefact(accepted.artefact_id or "")

    def _execute(self, request: ChatRequest, cal: Calibration, key: str) -> ChatAnswer:
        lang = request.language
        markers = engine.client_markers(request.question, lang, cal)
        route = "client_situation" if markers else "population_fact"
        use_facts = bool(markers) and bool(request.client_facts)
        history = engine.recent_history(request.history, cal)
        assistant = self.settings.model.display_name
        general = cal.general[lang] if cal.general else None
        if general is None:
            raise engine.EngineError(f"calibration {cal.version} has no general texts")
        warnings: list[str] = []
        if request.client_facts and not use_facts:
            warnings.append("the client facts were not shown to the model: the question is not about the client")

        base = dict(question=request.question, language=lang, route=route, prompt_version=engine.PROMPT_VERSION,
                    model_display_name=assistant, notice=f"Composed by {assistant}. {NOTICE}")
        prov = dict(engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS,
                    calibration_version=cal.version, calibration_hash=seeds.calibration_hash(cal),
                    idempotency_key=key, request_hash=self.request_hash(request),
                    grounding_ids=tuple(g.id for g in request.grounding),
                    grounding_hash=engine.content_id("GRD", [g.model_dump(mode="json") for g in request.grounding]),
                    client_fact_keys=tuple(f.key for f in request.client_facts), client_facts_used=use_facts,
                    history_turns_used=len(history))

        if not engine.intelligible(request.question):
            return _seal(ChatAnswer(
                artefact_id="", answer=general.unintelligible.format(assistant=assistant), cited_ids=(), numbers=(),
                unverified_numbers=(), refused=True, refusal_code="not_covered",
                refusal_reason="unintelligible: the question has no word in it", warnings=tuple(warnings),
                model=None, latency_ms=0.0, provenance=Provenance(model=None, **prov), **base))

        g = cal.generation
        latency = 0.0
        reply: Optional[engine.Reply] = None
        completion = None
        problems: list[str] = []
        attempts = 0
        retry_language = False
        for attempts in range(1, g.attempts + 1):
            messages = engine.build_messages(request, cal, use_client_facts=use_facts, retry_language=retry_language,
                                             assistant=assistant)
            try:
                completion = self.model.complete(messages, max_tokens=g.max_tokens, temperature=g.temperature,
                                                 seed=g.seed, response_format=engine.response_format())
            except ModelUnavailable as exc:
                raise Unavailable(str(exc)) from exc
            except ModelError as exc:
                raise BadModelOutput(str(exc)) from exc
            latency += completion.latency_ms
            try:
                candidate = engine.parse_reply(completion.text)
            except engine.ReplyError as exc:
                problems.append(f"draft {attempts}: {exc} (finish_reason {completion.finish_reason})")
                continue
            drift = engine.drifted(candidate.from_notes + candidate.general)
            if drift:
                problems.append(f"draft {attempts}: {drift} characters left the language")
                retry_language = True
                continue
            reply = candidate
            break
        if reply is None or completion is None:
            raise BadModelOutput("no usable draft: " + "; ".join(problems))
        warnings.extend(f"redrafted: {p}" for p in problems)

        model_use = ModelUse(service=self.settings.model.service, host=urlparse(self.settings.model.base_url).hostname
                             or "", model=completion.model, prompt_version=engine.PROMPT_VERSION,
                             prompt_hash=self.prompt_hash(), finish_reason=completion.finish_reason,
                             attempts=attempts, first_byte_ms=completion.first_byte_ms,
                             prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens)
        provenance = Provenance(model=model_use, **prov)

        if reply.status != "answer":
            outside = reply.status == "out_of_domain"
            text = general.out_of_domain if outside else general.unintelligible
            reason = ("out_of_domain: the model found the question outside the system's domain" if outside
                      else "unintelligible: the model could not understand the question")
            return _seal(ChatAnswer(
                artefact_id="", answer=text.format(assistant=assistant), cited_ids=(), numbers=(),
                unverified_numbers=(), refused=True, refusal_code="not_covered", refusal_reason=reason,
                warnings=tuple(warnings), model=completion.model, latency_ms=latency, provenance=provenance, **base))

        composed = engine.compose(reply, lang, [n.id for n in request.grounding],
                                  general.label.format(assistant=assistant))
        if not request.grounding:
            warnings.append("no grounding notes were sent: the answer is a general assessment")
        warnings.extend(composed.warnings)
        if composed.basis != "grounded":
            warnings.append("part or all of the answer is a general assessment, not drawn from the grounding notes")
        if completion.finish_reason == "length":
            warnings.append("the model stopped at the token limit; the answer may be cut short")
        sources = engine.sources_for(request, cal, use_client_facts=use_facts, history=history)
        numbers, unverified = engine.check_numbers(composed.text, sources, cal)
        if unverified:
            warnings.append(f"{len(unverified)} number(s) in the answer match no source: {', '.join(unverified)}")
        return _seal(ChatAnswer(
            artefact_id="", answer=composed.text, cited_ids=composed.cited, numbers=numbers,
            unverified_numbers=unverified, refused=False, basis=composed.basis,
            warnings=tuple(dict.fromkeys(warnings)), model=completion.model, latency_ms=latency,
            provenance=provenance, **base))

    def run_status(self, run_id: str) -> RunStatus:
        with self.store.session() as conn:
            row = st.get_run(conn, run_id)
        if row is None:
            raise NotFound(f"no run {run_id!r}")
        return RunStatus(
            run_id=row["run_id"], status=row["status"], idempotency_key=row["idempotency_key"],
            started_at=row["started_at"], finished_at=row["finished_at"], wall_clock_ms=row["wall_clock_ms"],
            request=ChatRequest.model_validate_json(row["request_json"]), artefact_id=row["artefact_id"],
            warnings=tuple(json.loads(row["warnings_json"])),
            provenance=Provenance.model_validate_json(row["provenance_json"]) if row["provenance_json"] else None,
            error=row["error"])

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            rows = st.list_runs(conn, max(1, min(limit, 500)))
        out = []
        for r in rows:
            req = json.loads(r.pop("request_json"))
            out.append({**r, "question": req["question"][:200], "request_language": req["language"],
                        "grounding_ids": [g["id"] for g in req.get("grounding", [])]})
        return out

    def artefact(self, artefact_id: str) -> ChatAnswer:
        with self.store.session() as conn:
            payload = st.get_artefact(conn, artefact_id)
        if payload is None:
            raise NotFound(f"no answer {artefact_id!r}")
        return ChatAnswer.model_validate_json(payload)


def _seal(draft: ChatAnswer) -> ChatAnswer:
    """The answer with its content id."""
    body = draft.model_dump(mode="json", exclude={"artefact_id"})
    return draft.model_copy(update={"artefact_id": engine.content_id("CHB", body)})


#: Engine Building Guide section 3. Normalised distribution names.
ALLOWLIST = frozenset({"fastapi", "uvicorn", "pydantic", "numpy", "pandas", "scipy", "pyarrow", "pyyaml",
                       "httpx", "pytest", "hypothesis"})

#: Runtime dependencies outside the allowlist, each with the decision that admits it.
ADMITTED = {"psycopg": "CHB-02: the Guide mandates PostgreSQL; a driver is unavoidable (as pcp PCP-02)"}


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
