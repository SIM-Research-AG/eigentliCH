"""The consumer app's orchestration: store reads and writes, engine calls, and the jobs that wait on engines.

Routing lives in ``api.py``, engine callers in ``clients.py``, the repository in ``store.py``. Every function
here names the client it acts for; there is no sign-in (owner decision, 9.1), so the client id arrives with
each request and every row reached through it is checked to belong to that client.

**Engine calls never hold a database transaction open.** A call is recorded as an ``engine_run`` (queued,
running) and committed, the engine is called, and the outcome and the rows it produces are written in a
second transaction. An engine that is down leaves the run ``failed`` with the reason, the request open, and
a retry possible; nothing is written in its place (EIG-31).

**Jobs.** Drafting an answer and producing a report can take minutes (spark7 streams). They run on a small
thread pool; the browser polls. The in-flight state and the last failure of each job are kept in memory;
the truth (a message was written, a report exists, a request is open) is always the store's.

**lbs runs by itself** (owner decision 29.09.2026, EIG-47). Every change of a client's plan or answers made
through the app schedules a balance-sheet run for that client (for a household change, for every client of
the household), debounced (``app.lbs_auto.debounce_s``, 5 s): a new change within the wait restarts it, and a
client has at most one run at a time; a change during a run makes one more run after it. Each run is an
``engine_run`` as every other, requested by ``system`` / ``AUTO_REF``. Opening the home page schedules one too
when the plan or the answers changed after the client's last lbs run (a curator's change in the cockpit).
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional

import psycopg
from psycopg import sql

from . import contracts as c
from . import gaps, grounding, inputs, questionnaires as qn, store
from .appsettings import AppSettings
from .clients import ChatbotClient, EngineError, EngineRefused, EngineUnavailable, LbsClient, ReportClient
from .inputs import MEMBER_ORDER
from .store import Decision, NotFound, Store

APP = "eigentlich-app"
APP_VERSION = "1.2.0"

#: ``engine_run.requested_by_ref`` of the automatic lbs runs (``requested_by_kind = 'system'``).
AUTO_REF = "eigentlich-app:auto"
BACKFILL_REF = "eigentlich-app:lbs-backfill"

ROLES = ("growth", "income", "stabilisation", "protection")
CAPITAL_TYPES = ("human", "financial")

#: The house's role names (``reference/roles``, reviewed by the owner on 30.08.2026), used only when that record
#: is missing, so that a page never falls back to lbs's English names (EIG-56).
ROLE_NAMES = {
    "growth": {"human": {"de": "Wachstum", "en": "Growth"}, "financial": {"de": "Wertsteigerung", "en": "Gain"}},
    "income": {"human": {"de": "Einkommen", "en": "Income"}, "financial": {"de": "Einkommen", "en": "Income"}},
    "stabilisation": {"human": {"de": "Stabilisierung", "en": "Stabilisation"},
                      "financial": {"de": "Stabilisierung", "en": "Stabilisation"}},
    "protection": {"human": {"de": "Absicherung", "en": "Protection"},
                   "financial": {"de": "Absicherung", "en": "Protection"}},
}


class Conflict(RuntimeError):
    """The request cannot be carried out in the present state; the message says what would allow it."""


class Invalid(ValueError):
    """The request is malformed or refused by a rule; the message names it."""


class Forbidden(PermissionError):
    """The named actor may not do this (a curator who does not exist or is revoked)."""


def _today() -> date:
    return date.today()


def _lang(language: Optional[str]) -> str:
    return "en" if (language or "").lower().startswith("en") else "de"


def _text(value: Any, language: str) -> Optional[str]:
    if isinstance(value, dict):
        return value.get(language) or value.get("de") or next(iter(value.values()), None)
    return value


@dataclass
class Job:
    state: str                     # running | failed | done
    started_at: float
    error: Optional[str] = None
    engine: Optional[str] = None
    finished_at: Optional[float] = None

    def public(self) -> dict[str, Any]:
        return {"state": self.state, "error": self.error, "engine": self.engine,
                "started_at": datetime.fromtimestamp(self.started_at).astimezone().isoformat()}


class Service:
    def __init__(self, settings: AppSettings, st: Store, lbs: LbsClient, chatbot: ChatbotClient,
                 report: ReportClient, workers: int = 8):
        self.settings = settings
        self.store = st
        self.lbs = lbs
        self.chatbot = chatbot
        self.report = report
        self.started = time.monotonic()
        self._jobs: dict[tuple[str, str], Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eigentlich-job")
        self._auto: dict[str, dict[str, Any]] = {}      # client -> {timer, running, again, due_at}
        self._closing = False

    def close(self) -> None:
        with self._lock:
            self._closing = True
            timers = [a["timer"] for a in self._auto.values() if a.get("timer")]
        for timer in timers:
            timer.cancel()
        self._pool.shutdown(wait=True)
        for client in (self.lbs, self.chatbot, self.report):
            client.close()

    # ------------------------------------------------------------------ standard

    def health(self) -> dict[str, Any]:
        try:
            with self.store.session() as conn:
                conn.execute("SELECT 1 FROM client LIMIT 1")
            db = "ok"
        except Exception as exc:  # noqa: BLE001 - health reports, it does not raise
            db = f"unreachable: {type(exc).__name__}"
        t = self.settings.timeouts.health_s
        engines = {"lbs": self.lbs.health(t), "chatbot": self.chatbot.health(t), "report": self.report.health(t)}
        return {"status": "ok" if db == "ok" else "degraded", "app": APP, "app_version": APP_VERSION,
                "store": db, "engines": engines, "sign_in": False,
                "uptime_s": round(time.monotonic() - self.started, 3)}

    def meta(self) -> dict[str, Any]:
        with self.store.session() as conn:
            counts = store.table_counts(conn)
            keys = store.content_keys(conn, "questionnaire")
        return {"app": APP, "app_version": APP_VERSION, "contract_versions": c.CONTRACT_VERSIONS,
                "settings": self.settings.describe(), "questionnaires": keys, "counts": counts,
                "sign_in": False, "notice": c.NOTICE}

    # ------------------------------------------------------------------ jobs

    def _job(self, kind: str, key: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get((kind, key))

    def _schedule(self, kind: str, key: str, fn: Callable[[], None], wait: bool) -> Job:
        with self._lock:
            job = self._jobs.get((kind, key))
            if job is not None and job.state == "running":
                return job
            job = Job(state="running", started_at=time.time())
            self._jobs[(kind, key)] = job

        def run() -> None:
            try:
                fn()
                job.state, job.error = "done", None
            except EngineError as exc:
                job.state, job.error, job.engine = "failed", str(exc), exc.engine
            except Exception as exc:  # noqa: BLE001 - a job reports its failure to the page
                job.state, job.error = "failed", f"{type(exc).__name__}: {exc}"
            job.finished_at = time.time()

        if wait:
            run()
        else:
            self._pool.submit(run)
        return job

    # ------------------------------------------------------------------ automatic lbs runs (EIG-47)

    def schedule_lbs(self, *client_ids: str) -> None:
        """Run lbs for these clients once the debounce wait passes without a further change."""
        auto = self.settings.lbs_auto
        if not auto.enabled:
            return
        for client_id in dict.fromkeys(client_ids):
            with self._lock:
                if self._closing:
                    return
                state = self._auto.setdefault(client_id, {"timer": None, "running": False, "again": False})
                if state["timer"] is not None:
                    state["timer"].cancel()
                timer = threading.Timer(auto.debounce_s, self._auto_due, args=(client_id,))
                timer.daemon = True
                state["timer"], state["due_at"] = timer, time.time() + auto.debounce_s
                timer.start()

    def _auto_due(self, client_id: str) -> None:
        with self._lock:
            state = self._auto.get(client_id)
            if state is None or self._closing:
                return
            state["timer"] = None
            if state["running"]:
                state["again"] = True                  # one more run once the current one is done
                return
            state["running"] = True
        try:
            self._pool.submit(self._auto_run, client_id)
        except RuntimeError:                           # the pool is shutting down
            with self._lock:
                state["running"] = False

    def _auto_run(self, client_id: str) -> None:
        while True:
            try:
                self.run_balance_sheet(client_id, requested_by=("system", AUTO_REF))
            except Exception:  # noqa: BLE001 - the failure is the engine_run's error; nothing else to tell
                pass
            with self._lock:
                state = self._auto[client_id]
                if state["again"] and not self._closing:
                    state["again"] = False
                    continue
                state["running"] = False
                return

    def lbs_pending(self, client_id: str) -> Optional[str]:
        """``scheduled`` or ``running`` while an automatic run is on its way for the client, else None."""
        with self._lock:
            state = self._auto.get(client_id)
            if not state:
                return None
            if state["running"]:
                return "running"
            return "scheduled" if state["timer"] is not None else None

    # ------------------------------------------------------------------ engine runs

    def _engine_call(self, client_id: str, engine: str, request: Any, call: Callable[[], tuple[Any, str, Optional[str]]],
                     requested_by: tuple[str, str] | None = None) -> tuple[Any, dict[str, Any]]:
        """Record the run, call, record the outcome. ``call`` returns (result, artefact_id, run_id)."""
        kind, ref = requested_by or ("client", client_id)
        with self.store.session() as conn:
            run = store.start_engine_run(conn, client_id=client_id, engine=engine, request=c.dump(request),
                                         requested_by_kind=kind, requested_by_ref=ref)
            store.mark_engine_run_running(conn, run["id"])
        try:
            result, artefact_id, run_id = call()
        except EngineError as exc:
            with self.store.session() as conn:
                store.finish_engine_run(conn, run["id"], status="failed", error=str(exc)[:2000])
            raise
        except Exception as exc:
            with self.store.session() as conn:
                store.finish_engine_run(conn, run["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
            raise
        with self.store.session() as conn:
            row = store.finish_engine_run(conn, run["id"], status="succeeded", artefact_id=artefact_id, run_id=run_id)
        return result, row

    # ------------------------------------------------------------------ clients (the picker)

    def list_clients(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            return store.list_clients(conn, include_archived=include_archived)

    def create_client(self, *, display_name: str, age_at_registration: int, locale: str = "de-CH") -> dict[str, Any]:
        with self.store.session() as conn:
            row = store.create_client(conn, display_name=display_name.strip(), age_at_registration=age_at_registration,
                                      locale=locale, created_by_kind="client")
        return row

    def get_client(self, client_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            row = conn.execute("SELECT * FROM client_overview WHERE id = %s", (client_id,)).fetchone()
        if row is None:
            raise NotFound(f"no client {client_id}")
        return row

    def update_client(self, client_id: str, **values: Any) -> dict[str, Any]:
        allowed = {k: v for k, v in values.items() if k in ("display_name", "locale") and v is not None}
        if not allowed:
            raise Invalid("nothing to change: display_name or locale")
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            return store.update_client(conn, client_id, **allowed)

    # ------------------------------------------------------------------ questionnaires

    def _key(self, name: str) -> str:
        if name not in qn.NAMES:
            raise NotFound(f"no questionnaire {name!r}; there are {sorted(qn.NAMES)}")
        return qn.NAMES[name]

    def _goal_templates(self, conn) -> list[dict[str, Any]]:
        try:
            body = store.content_current(conn, "reference/goal-templates")["body"]
            templates = body.get("templates") if isinstance(body, dict) else body
            if isinstance(templates, list) and templates:
                return templates
        except NotFound:
            pass
        return qn.GOAL_TEMPLATES

    def questionnaire(self, client_id: str, name: str, language: str = "de") -> dict[str, Any]:
        key = self._key(name)
        lang = _lang(language)
        with self.store.session() as conn:
            client = store.get_client(conn, client_id)
            content = store.content_current(conn, key)
            rows = store.get_answers(conn, client_id, key)
            templates = self._goal_templates(conn)
            saver = None
            if content["saved_by_kind"] == "client":
                who = conn.execute("SELECT display_name FROM client WHERE id = %s", (content["saved_by_ref"],)).fetchone()
                saver = who["display_name"] if who else None
            elif content["saved_by_kind"] == "curator":
                who = conn.execute("SELECT display_name FROM curator WHERE id = %s", (content["saved_by_ref"],)).fetchone()
                saver = who["display_name"] if who else None
        body = content["body"]
        answers = {r["question_key"]: r["value"] for r in rows}
        return {
            "key": key, "name": name, "version": content["version"], "language": lang,
            "saved_by_kind": content["saved_by_kind"], "saved_by_name": saver, "saved_at": content["saved_at"],
            "note": content["note"], "sections": body.get("sections") or [],
            "questions": qn.ordered(body),
            "answers": {r["question_key"]: {"value": r["value"], "content_version": r["content_version"],
                                            "answered_at": r["answered_at"], "answered_by_kind": r["answered_by_kind"]}
                        for r in rows},
            "asked": {q["key"]: qn.is_asked(q, answers) for q in body.get("questions") or []},
            "next_question_key": qn.next_question(body, answers),
            "goal_templates": templates,
            "onboarding_completed_at": client["onboarding_completed_at"],
            "can_complete": name == "onboarding" and client["onboarding_completed_at"] is None
                            and bool(answers.get("employment_position")),
        }

    def put_answer(self, client_id: str, name: str, question_key: str, *, value: Any,
                   content_version: int) -> dict[str, Any]:
        key = self._key(name)
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            try:
                content = store.content_version(conn, key, content_version)
            except NotFound as exc:
                raise Invalid(f"{key} has no version {content_version}") from exc
            try:
                q = qn.question(content["body"], question_key)
            except KeyError as exc:
                raise NotFound(f"{key}@{content_version} has no question {question_key!r}") from exc
            stored = qn.check(q, value)
            row = store.put_answer(conn, client_id=client_id, questionnaire_key=key, content_version=content_version,
                                   question_key=question_key, value=stored, answered_by_kind="client",
                                   answered_by_ref=client_id)
            restated = self._restate_from_answer(conn, client_id, q, stored)
        self.schedule_lbs(client_id)
        return {"id": row["id"], "question_key": question_key, "value": row["value"],
                "questionnaire_key": key, "content_version": row["content_version"], "answered_at": row["answered_at"],
                "restated_fact": restated}

    @staticmethod
    def _current_fact(conn, client_id: str, key: str) -> Optional[dict[str, Any]]:
        return conn.execute("SELECT * FROM client_fact WHERE client_id = %s AND stated_key = %s "
                            "AND superseded_on IS NULL", (client_id, key)).fetchone()

    def _restate_from_answer(self, conn, client_id: str, q: dict[str, Any], value: Any) -> Optional[str]:
        """A stated fact wins over an answer (inputs.py). A question that fills a fact (``fills.entity =
        member_fact``) answered again restates that fact, under the client's decision (C-09, EIG-54), so the
        new answer reaches lbs. Nothing when the client has no such fact yet (the answer is read then) or it
        already says the same. The decision names the key, not the value (a K3 value stays out of it)."""
        fills = q.get("fills") or {}
        if fills.get("entity") != "member_fact":
            return None
        fact_key = fills.get("key") or q["key"]
        current = self._current_fact(conn, client_id, fact_key)
        if current is None or current["stated_value"] == value:
            return None
        with store.plan_change(conn, decision=Decision(
                client_id=client_id, author="client", author_ref=client_id,
                question=f"Die festgehaltene Angabe «{fact_key}» nachführen?", choice="Ja, wie neu beantwortet",
                reasoning="Im Fragebogen neu beantwortet; die festgehaltene Angabe folgt der Antwort.")) as ch:
            ch.state_fact(client_id=client_id, stated_key=fact_key, stated_value=value, stated_on=_today(),
                          stated_by="client", data_class=current["data_class"])
        return fact_key

    def restate_fact(self, client_id: str, key: str, *, value: Any, reasoning: Optional[str] = None) -> dict[str, Any]:
        """State a fact anew (``PUT .../facts/{key}``, EIG-54), under the client's decision (C-09). A key the
        onboarding fills is checked against that question (its options, its range) and keeps its class; any
        other key must be a plain key and is K2 unless the current fact says otherwise."""
        if not re.fullmatch(r"[a-z0-9_]{1,64}", key or ""):
            raise Invalid("a fact key is lower-case letters, digits and underscores")
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            body = store.content_current(conn, qn.NAMES["onboarding"])["body"]
            q = next((x for x in body.get("questions") or [] if (x.get("fills") or {}).get("entity") == "member_fact"
                      and ((x.get("fills") or {}).get("key") or x["key"]) == key), None)
            if value in (None, "", [], {}):
                raise Invalid("an empty value is not stated")
            stored = qn.check(q, value) if q is not None else value
            current = self._current_fact(conn, client_id, key)
            if current is not None and current["stated_value"] == stored:
                return {"fact": current, "changed": False}
            declared = str(((q or {}).get("fills") or {}).get("data_class") or (q or {}).get("data_class") or "")
            klass = current["data_class"] if current is not None else (
                int(declared[1:]) if declared[:1] == "K" and declared[1:].isdigit() else 2)
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Die Angabe «{key}» festhalten?", choice="Ja, so festhalten",
                    reasoning=reasoning)) as ch:
                fact = ch.state_fact(client_id=client_id, stated_key=key, stated_value=stored, stated_on=_today(),
                                     stated_by="client", data_class=klass)
        self.schedule_lbs(client_id)
        return {"fact": fact, "changed": True}

    def content_history(self, name: str) -> list[dict[str, Any]]:
        key = self._key(name)
        with self.store.session() as conn:
            rows = store.content_history(conn, key)
            names = {}
            for r in rows:
                table = {"client": "client", "curator": "curator"}.get(r["saved_by_kind"])
                if table:
                    who = conn.execute(sql.SQL("SELECT display_name FROM {} WHERE id = %s").format(sql.Identifier(table)),
                                       (r["saved_by_ref"],)).fetchone()
                    names[r["version"]] = who["display_name"] if who else None
        return [{**r, "saved_by_name": names.get(r["version"])} for r in rows]

    def edit_content(self, client_id: str, name: str, *, base_version: int, question_key: str,
                     edit: dict[str, Any], note: Optional[str] = None) -> dict[str, Any]:
        """A new version of the shared questionnaire, saved by this client (owner decision 9.1).

        Serialised with every other save of the key (the trigger's own advisory lock, taken first), and
        refused when someone saved a newer version since ``base_version`` was read: the editor reloads.
        """
        key = self._key(name)
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s || '.content_record:' || %s, 0))",
                         (self.store.config.schema, key))
            current = store.content_current(conn, key)
            if current["version"] != base_version:
                raise Conflict(f"{key} is at version {current['version']} now (you edited {base_version}); "
                               "reload and edit again")
            try:
                body = qn.apply_edit(current["body"], question_key, edit)
            except KeyError as exc:
                raise NotFound(f"{key} has no question {question_key!r}") from exc
            except ValueError as exc:
                raise Invalid(str(exc)) from exc
            version = store.save_content(conn, key=key, kind="questionnaire", body=body, saved_by_kind="client",
                                         saved_by_ref=client_id,
                                         note=(note or f"Frage {question_key} bearbeitet")[:500])
        return {"key": key, "version": version, "question_key": question_key}

    # ------------------------------------------------------------------ onboarding completion

    def complete_onboarding(self, client_id: str) -> dict[str, Any]:
        """The prototype's ``onboarding.complete`` (R-102): household, the first position, the first goal
        and the stated facts, each under a decision, in one transaction (C-09)."""
        key = qn.NAMES["onboarding"]
        today = _today()
        with self.store.session() as conn:
            client = conn.execute("SELECT * FROM client WHERE id = %s FOR UPDATE", (client_id,)).fetchone()
            if client is None:
                raise NotFound(f"no client {client_id}")
            if client["onboarding_completed_at"] is not None:
                raise Conflict("the first conversation is already complete; change the plan from the plan page")
            rows = store.get_answers(conn, client_id, key)
            given = {r["question_key"]: r["value"] for r in rows}
            label = given.get("employment_position")
            if not isinstance(label, str) or not label.strip():
                raise Conflict("the first question («Womit verdienen Sie heute Ihr Geld?») is not answered yet")
            content = store.content_current(conn, key)["body"]
            created: dict[str, Any] = {}

            hh_answer = given.get("household_composition")
            has_household = self._current_household(conn, client_id) is not None
            if isinstance(hh_answer, dict) and hh_answer.get("adults") and not has_household:
                adults = [str(a) for a in hh_answer["adults"]]
                dependants = [str(d) for d in hh_answer.get("dependants") or []]
                as_of = date.fromisoformat(hh_answer["as_of"]) if hh_answer.get("as_of") else today
                with store.plan_change(conn, decision=Decision(
                        client_id=client_id, author="client", author_ref=client_id,
                        question="Wer gehört zum Haushalt, für den dieser Plan gilt?",
                        choice=", ".join(adults + dependants),
                        reasoning="Aus dem Erstgespräch übernommen.")) as ch:
                    hh = ch.insert("household", composition_as_of=as_of, stated_by="client")
                    me = ch.insert("household_member", household_id=hh["id"], client_id=client_id, label=adults[0],
                                   kind="adult")
                    for a in adults[1:]:
                        ch.insert("household_member", household_id=hh["id"], label=a, kind="adult")
                    for d in dependants:
                        ch.insert("household_member", household_id=hh["id"], label=d, kind="dependant")
                    created["household"] = hh["id"]
                    created["member"] = me["id"]

            magnitude = given.get("employment_magnitude")
            hours = given.get("employment_time_basis")
            goal = given.get("first_goal") if isinstance(given.get("first_goal"), dict) else (
                {"name": given["first_goal"], "template": None} if isinstance(given.get("first_goal"), str) else None)
            goal_name = (goal or {}).get("name")
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question="Was aus dem Erstgespräch wird als Plan festgehalten?",
                    choice=f"Erste Position: {label.strip()}" + (f". Erstes Ziel: {goal_name}" if goal_name else ""),
                    reasoning="Aus den Antworten des Erstgesprächs übernommen.")) as ch:
                unit = None
                if isinstance(magnitude, (int, float)):
                    unit = (qn.question(content, "employment_magnitude").get("fills") or {}).get("magnitude_unit") \
                        or "chf_per_year"
                pos = ch.insert("position", client_id=client_id, role="income", capital_type="human",
                                label=label.strip(), magnitude=float(magnitude) if unit else None, magnitude_unit=unit,
                                time_basis=f"{hours:g} Std./Woche" if isinstance(hours, (int, float)) else None)
                created["position"] = pos["id"]
                if goal_name:
                    g = ch.insert("goal", client_id=client_id, name=goal_name, template=goal.get("template"))
                    created["goal"] = g["id"]
                    member = created.get("member") or self._my_member_id(conn, client_id)
                    if member:
                        ch.set_goal_owner(g["id"], member)
                facts = []
                for q in content.get("questions") or []:
                    fills = q.get("fills") or {}
                    if fills.get("entity") != "member_fact" or q["key"] not in given:
                        continue
                    klass = fills.get("data_class") or q.get("data_class") or "K2"
                    ch.state_fact(client_id=client_id, stated_key=fills.get("key") or q["key"],
                                  stated_value=given[q["key"]], stated_on=today, stated_by="client",
                                  data_class=int(str(klass)[1:]) if str(klass).startswith("K") else 2)
                    facts.append(fills.get("key") or q["key"])
                created["facts"] = facts
                created["decision"] = ch.decision_id
            store.update_client(conn, client_id, onboarding_completed_at=datetime.now().astimezone())
        self.schedule_lbs(client_id)
        return created

    # ------------------------------------------------------------------ the plan (C-09)

    @staticmethod
    def _current_household(conn, client_id: str) -> Optional[dict[str, Any]]:
        return conn.execute(
            "SELECT h.* FROM household h JOIN household_member m ON m.household_id = h.id "
            "WHERE m.client_id = %s AND m.left_on IS NULL AND h.closed_on IS NULL "
            "ORDER BY h.created_at DESC, h.id LIMIT 1", (client_id,)).fetchone()

    def _my_member_id(self, conn, client_id: str) -> Optional[str]:
        hh = self._current_household(conn, client_id)
        if hh is None:
            return None
        row = conn.execute("SELECT id FROM household_member WHERE household_id = %s AND client_id = %s",
                           (hh["id"], client_id)).fetchone()
        return row["id"] if row else None

    def plan(self, client_id: str, language: str = "de") -> dict[str, Any]:
        lang = _lang(language)
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            p = store.plan_of(conn, client_id, include_inactive=True)
            hh = self._current_household(conn, client_id)
            members = conn.execute(MEMBER_ORDER, (hh["id"], client_id)).fetchall() if hh else []
            goal_ids = [g["id"] for g in p["goals"]]
            funding = conn.execute("SELECT goal_id, position_id FROM goal_funding WHERE active AND goal_id = ANY(%s)",
                                   (goal_ids,)).fetchall()
            roles = self._roles(conn)
            onboarding = store.content_current(conn, qn.NAMES["onboarding"])["body"]
        fact_labels = {}
        for q in onboarding.get("questions") or []:
            fills = q.get("fills") or {}
            if fills.get("entity") == "member_fact":
                fact_labels[fills.get("key") or q["key"]] = _text(q.get("question"), lang)
        partner = next((m for m in members if m["client_id"] != client_id and m["kind"] == "adult"), None)
        cells = []
        for role in ROLES:
            for cap in CAPITAL_TYPES:
                display, definition = self._role_text(roles, role, cap, lang)
                cells.append({"role": role, "capital_type": cap, "display": display, "definition": definition,
                              "positions": [x for x in p["positions"] if x["role"] == role and x["capital_type"] == cap]})
        goals = [{**g, "kind": inputs.goal_kind(g),
                  "funded_by": [f["position_id"] for f in funding if f["goal_id"] == g["id"]]} for g in p["goals"]]
        dated = [g for g in p["goals"] if g["active"] and g["target_amount"] and g["target_date"]]
        return {"household": hh, "members": members, "cells": cells, "roles": list(ROLES),
                "positions": p["positions"], "goals": goals, "facts": p["facts"], "fact_labels": fact_labels,
                # the first other adult: whose positions can be marked as the partner's (EIG-53)
                "partner": partner["label"] if partner else None,
                # more than one goal with an amount and a date: each is asked its share of the saving (EIG-59)
                "shares_asked": len(dated) > 1,
                "shares_total": round(sum(g["contribution_share"] or 0 for g in p["goals"] if g["active"]), 6)}

    def _roles(self, conn) -> dict[str, Any]:
        try:
            body = store.content_current(conn, "reference/roles")["body"]
            return {r["key"]: r for r in body.get("roles") or []}
        except NotFound:
            return {}

    @staticmethod
    def _role_text(roles: dict[str, Any], role: str, cap: str, lang: str) -> tuple[str, Optional[str]]:
        """A role's name and definition for one kind of capital in the reader's language, from
        ``reference/roles`` (the house's names, EIG-56). lbs's ``gain`` is the record's ``growth``. Never lbs's
        own English text, and never another language's: a text missing in ``lang`` is left out."""
        key = "growth" if role == "gain" else role
        spec = roles.get(key) or {}
        display = ((spec.get("display") or {}).get(cap) or {})
        definition = ((spec.get("definition") or {}).get(cap) or {})
        name = (display.get(lang) if isinstance(display, dict) else None) \
            or ROLE_NAMES.get(key, {}).get(cap, {}).get(lang) or key
        text = definition.get(lang) if isinstance(definition, dict) else None
        return name, text or None

    def decisions(self, client_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            return conn.execute("SELECT * FROM decision WHERE client_id = %s ORDER BY seq DESC LIMIT %s",
                                (client_id, limit)).fetchall()

    def set_household(self, client_id: str, *, adults: list[str], dependants: list[str],
                      as_of: Optional[date] = None, reasoning: Optional[str] = None) -> dict[str, Any]:
        """A new composition: the current household is closed and a new one succeeds it (EIG-07), under one
        decision. The client is the first adult; a member who is another client keeps their record when
        their label is kept."""
        adults = [a.strip() for a in adults if a and a.strip()]
        dependants = [d.strip() for d in dependants if d and d.strip()]
        if not adults:
            raise Invalid("a household has at least one adult: you")
        as_of = as_of or _today()
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            old = self._current_household(conn, client_id)
            linked = {}
            if old:
                for m in conn.execute("SELECT * FROM household_member WHERE household_id = %s AND left_on IS NULL",
                                      (old["id"],)).fetchall():
                    if m["client_id"] and m["client_id"] != client_id:
                        linked[m["label"]] = m["client_id"]
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question="Wer gehört zum Haushalt?", choice=", ".join(adults + dependants),
                    reasoning=reasoning)) as ch:
                if old:
                    ch.update("household", old["id"], closed_on=max(as_of, old["composition_as_of"]))
                hh = ch.insert("household", composition_as_of=as_of, stated_by="client",
                               succeeds_household_id=old["id"] if old else None)
                ch.insert("household_member", household_id=hh["id"], client_id=client_id, label=adults[0], kind="adult")
                for a in adults[1:]:
                    ch.insert("household_member", household_id=hh["id"], client_id=linked.get(a), label=a, kind="adult")
                for d in dependants:
                    ch.insert("household_member", household_id=hh["id"], label=d, kind="dependant")
                decision_id = ch.decision_id
        # A household change applies to both partners (EIG-39): so does the new balance sheet.
        self.schedule_lbs(client_id, *linked.values())
        return {"household": hh["id"], "decision": decision_id}

    _POSITION_FIELDS = ("role", "capital_type", "label", "description", "magnitude", "magnitude_unit", "time_basis",
                        "started_on", "liquidity", "stock_kind", "owner")

    def _position_values(self, values: dict[str, Any]) -> dict[str, Any]:
        out = {k: values[k] for k in self._POSITION_FIELDS if k in values}
        if "owner" in out:
            # Whose position it is (EIG-53): the client (stored as NULL, as before) or the partner.
            if out["owner"] not in (None, "", "client", "partner"):
                raise Invalid("a position belongs to the client or the partner")
            out["owner"] = "partner" if out["owner"] == "partner" else None
        if "magnitude" in out and out["magnitude"] is None:
            out["magnitude_unit"] = None
        if out.get("magnitude_unit") != "chf" and "magnitude_unit" in out:
            out["stock_kind"] = None
        if "started_on" in out and isinstance(out["started_on"], str):
            out["started_on"] = date.fromisoformat(out["started_on"]) if out["started_on"] else None
        return out

    def create_position(self, client_id: str, values: dict[str, Any]) -> dict[str, Any]:
        row = self._position_values(values)
        for need in ("role", "capital_type", "label"):
            if not row.get(need):
                raise Invalid(f"a position needs {need}")
        tags = {"vessel": values["vessel"]} if values.get("vessel") in inputs.VESSELS else {}
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Position «{row['label']}» erfassen?", choice="Ja, erfassen",
                    reasoning=values.get("reasoning"))) as ch:
                pos = ch.insert("position", client_id=client_id, tags=tags, **row)
        self.schedule_lbs(client_id)
        return pos

    def _own(self, conn, table: str, row_id: str, client_id: str) -> dict[str, Any]:
        row = conn.execute(sql.SQL("SELECT * FROM {} WHERE id = %s FOR UPDATE").format(sql.Identifier(table)),
                           (row_id,)).fetchone()
        if row is None or row["client_id"] != client_id:
            raise NotFound(f"no {table} {row_id} of this client")
        return row

    @staticmethod
    def _changes(old: dict[str, Any], new: dict[str, Any]) -> str:
        parts = []
        for k, v in new.items():
            if old.get(k) != v:
                parts.append(f"{k}: {old.get(k) if old.get(k) is not None else '—'} → {v if v is not None else '—'}")
        return "; ".join(parts) or "keine Änderung"

    def update_position(self, client_id: str, position_id: str, values: dict[str, Any]) -> dict[str, Any]:
        row = self._position_values(values)
        with self.store.session() as conn:
            old = self._own(conn, "position", position_id, client_id)
            if "vessel" in values:
                tags = dict(old["tags"] or {})
                if values["vessel"] in inputs.VESSELS:
                    tags["vessel"] = values["vessel"]
                else:
                    tags.pop("vessel", None)
                row["tags"] = tags
            if not row:
                raise Invalid("nothing to change")
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Position «{old['label']}» ändern?", choice=self._changes(old, row),
                    reasoning=values.get("reasoning"))) as ch:
                result = ch.update("position", position_id, **row)
        self.schedule_lbs(client_id)
        return result

    def set_position_active(self, client_id: str, position_id: str, active: bool,
                            reasoning: Optional[str] = None) -> dict[str, Any]:
        with self.store.session() as conn:
            old = self._own(conn, "position", position_id, client_id)
            if old["active"] == active:
                raise Conflict("the position is already " + ("in" if active else "out of") + " the plan")
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Position «{old['label']}» " + ("wieder in den laufenden Plan?" if active
                                                              else "aus dem laufenden Plan nehmen?"),
                    choice="Ja", reasoning=reasoning)) as ch:
                result = ch.update("position", position_id, active=active)
        self.schedule_lbs(client_id)
        return result

    _GOAL_FIELDS = ("name", "target_amount", "target_date", "safety", "liquidity_need", "volatility_tolerance",
                    "horizon", "flexibility", "template", "occupancy", "contribution_share")

    def _goal_values(self, values: dict[str, Any]) -> dict[str, Any]:
        out = {k: values[k] for k in self._GOAL_FIELDS if k in values}
        if "target_date" in out and isinstance(out["target_date"], str):
            out["target_date"] = date.fromisoformat(out["target_date"]) if out["target_date"] else None
        share = out.get("contribution_share")
        if share is not None and (isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 1):
            raise Invalid("a goal's share of the yearly saving is between 0 and 1 (0 to 100 %)")
        return out

    @staticmethod
    def _check_shares(conn, client_id: str, goal_id: Optional[str], share: Optional[float]) -> None:
        """The active goals' shares of the one yearly saving sum to at most 1 (EIG-59): lbs refuses more, so
        the app refuses it first, naming the sum. The client row is locked, so two saves cannot both pass."""
        conn.execute("SELECT 1 FROM client WHERE id = %s FOR UPDATE", (client_id,))
        rows = conn.execute("SELECT id, contribution_share FROM goal WHERE client_id = %s AND active "
                            "AND contribution_share IS NOT NULL", (client_id,)).fetchall()
        total = sum(r["contribution_share"] for r in rows if r["id"] != goal_id) + (share or 0.0)
        if total > 1 + 1e-9:
            raise Invalid(f"the goals' shares of the yearly saving would sum to {total * 100:.0f} %; "
                          "together at most 100 %")

    def _fund(self, conn, ch, client_id: str, goal_id: str, position_ids: Optional[list[str]]) -> None:
        if position_ids is None:
            return
        mine = {r["id"] for r in conn.execute("SELECT id FROM position WHERE client_id = %s", (client_id,)).fetchall()}
        unknown = set(position_ids) - mine
        if unknown:
            raise NotFound(f"no position {sorted(unknown)[0]} of this client")
        current = {r["position_id"] for r in conn.execute(
            "SELECT position_id FROM goal_funding WHERE goal_id = %s AND active", (goal_id,)).fetchall()}
        for pid in set(position_ids) - current:
            ch.set_goal_funding(goal_id, pid, active=True)
        for pid in current - set(position_ids):
            ch.set_goal_funding(goal_id, pid, active=False)

    def create_goal(self, client_id: str, values: dict[str, Any]) -> dict[str, Any]:
        row = self._goal_values(values)
        if not (row.get("name") or "").strip():
            raise Invalid("a goal needs a name")
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            self._check_shares(conn, client_id, None, row.get("contribution_share"))
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Ziel «{row['name']}» erfassen?", choice="Ja, erfassen",
                    reasoning=values.get("reasoning"))) as ch:
                goal = ch.insert("goal", client_id=client_id, **row)
                member = self._my_member_id(conn, client_id)
                if member:
                    ch.set_goal_owner(goal["id"], member)
                self._fund(conn, ch, client_id, goal["id"], values.get("funded_by"))
        self.schedule_lbs(client_id)
        return goal

    def update_goal(self, client_id: str, goal_id: str, values: dict[str, Any]) -> dict[str, Any]:
        row = self._goal_values(values)
        with self.store.session() as conn:
            old = self._own(conn, "goal", goal_id, client_id)
            funded = values.get("funded_by")
            if not row and funded is None:
                raise Invalid("nothing to change")
            if old["active"] and "contribution_share" in row:
                self._check_shares(conn, client_id, goal_id, row["contribution_share"])
            choice = self._changes(old, row) if row else "Finanzierung angepasst"
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Ziel «{old['name']}» ändern?", choice=choice,
                    reasoning=values.get("reasoning"))) as ch:
                result = ch.update("goal", goal_id, **row) if row else old
                self._fund(conn, ch, client_id, goal_id, funded)
        self.schedule_lbs(client_id)
        return result

    def set_goal_active(self, client_id: str, goal_id: str, active: bool, reasoning: Optional[str] = None) -> dict[str, Any]:
        with self.store.session() as conn:
            old = self._own(conn, "goal", goal_id, client_id)
            if old["active"] == active:
                raise Conflict("the goal is already " + ("active" if active else "inactive"))
            if active:
                self._check_shares(conn, client_id, goal_id, old["contribution_share"])
            with store.plan_change(conn, decision=Decision(
                    client_id=client_id, author="client", author_ref=client_id,
                    question=f"Ziel «{old['name']}» " + ("wieder verfolgen?" if active else "nicht mehr verfolgen?"),
                    choice="Ja", reasoning=reasoning)) as ch:
                result = ch.update("goal", goal_id, active=active)
        self.schedule_lbs(client_id)
        return result

    # ------------------------------------------------------------------ the balance sheet (lbs)

    def curator_in_service(self, curator_id: str) -> dict[str, Any]:
        """The curator, or Forbidden: a curator who does not exist or is revoked cannot act (A161)."""
        with self.store.session() as conn:
            row = conn.execute("SELECT id, display_name, revoked_at FROM curator WHERE id = %s", (curator_id,)).fetchone()
        if row is None:
            raise Forbidden(f"no curator {curator_id}")
        if row["revoked_at"] is not None:
            raise Forbidden(f"curator {curator_id} is revoked and cannot act (A161)")
        return row

    def run_balance_sheet(self, client_id: str, requested_by: tuple[str, str] | None = None,
                          curator_id: Optional[str] = None) -> dict[str, Any]:
        """One lbs run. The requester recorded on the engine_run is the client (the app's button), a curator
        named by ``curator_id`` (the cockpit's button; refused unless in service), or ``requested_by``
        (the automatic runs and the backfill: ``system``)."""
        if curator_id is not None:
            self.curator_in_service(curator_id)
            requested_by = ("curator", curator_id)
        with self.store.session() as conn:
            gathered = inputs.gather(conn, client_id)
        request, dropped = inputs.build(gathered, _today())

        def call():
            accepted = self.lbs.run(request)
            if accepted.status != "succeeded" or not accepted.artefact_id:
                raise EngineRefused("lbs", f"lbs could not build the balance sheet (run {accepted.run_id}, "
                                           f"{accepted.status})")
            return accepted, accepted.artefact_id, accepted.run_id

        accepted, run = self._engine_call(client_id, "lbs", request, call, requested_by=requested_by)
        return {"artefact_id": accepted.artefact_id, "engine_run_id": run["id"], "cached": accepted.cached,
                "dropped": dropped}

    def _names(self, conn, client_id: str) -> dict[str, dict[str, str]]:
        """The names the client gave the things lbs refers to by id: goals, positions, household members
        (``p1`` the client, then the others in the order the request was built)."""
        goals = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM goal WHERE client_id = %s",
                                                          (client_id,)).fetchall()}
        positions = {r["id"]: r["label"] for r in conn.execute("SELECT id, label FROM position WHERE client_id = %s",
                                                               (client_id,)).fetchall()}
        persons: dict[str, str] = {}
        hh = self._current_household(conn, client_id)
        if hh:
            members = conn.execute(MEMBER_ORDER, (hh["id"], client_id)).fetchall()
            me = [m for m in members if m["client_id"] == client_id]
            others = [m for m in members if m["client_id"] != client_id]
            for i, m in enumerate(me[:1] + others, start=1 if me else 2):
                persons[f"p{i}"] = m["label"]
        return {"goals": goals, "positions": positions, "persons": persons}

    @staticmethod
    def _changed_at(conn, client_id: str) -> Optional[datetime]:
        """When the client's plan or answers last changed: the latest decision or answer."""
        return conn.execute(
            "SELECT greatest((SELECT max(created_at) FROM decision WHERE client_id = %s), "
            "(SELECT max(created_at) FROM answer WHERE client_id = %s)) AS at", (client_id, client_id)).fetchone()["at"]

    def balance_sheet(self, client_id: str, schedule_if_stale: bool = False, language: str = "de") -> dict[str, Any]:
        """The latest sheet lbs made for this client, fetched from lbs. ``available`` false says why.
        ``age_s`` is how old the sheet is; ``pending`` names an automatic run on its way. With
        ``schedule_if_stale`` (the home page), a change after the client's last lbs run schedules one. The
        grid's role names and definitions are the house's, in ``language`` (EIG-56), never lbs's English."""
        lang = _lang(language)
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            run = conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = 'lbs' AND status = 'succeeded' "
                               "ORDER BY finished_at DESC LIMIT 1", (client_id,)).fetchone()
            last_failed = conn.execute(
                "SELECT error, finished_at FROM engine_run WHERE client_id = %s AND engine = 'lbs' AND status = 'failed' "
                "ORDER BY finished_at DESC LIMIT 1", (client_id,)).fetchone()
            changed = self._changed_at(conn, client_id)
            last_any = conn.execute("SELECT max(created_at) AS at FROM engine_run WHERE client_id = %s AND engine = 'lbs'",
                                    (client_id,)).fetchone()["at"]
        # A change the app did not see (the cockpit's) and no lbs run since, successful or not: run once.
        if schedule_if_stale and changed is not None and (last_any is None or changed > last_any) \
                and self.lbs_pending(client_id) is None:
            self.schedule_lbs(client_id)
        pending = self.lbs_pending(client_id)
        if run is None:
            return {"available": False, "reason": "not_run", "last_failure": last_failed, "pending": pending}
        try:
            sheet = self.lbs.sheet_raw(run["artefact_id"])
        except EngineError as exc:
            return {"available": False, "reason": "engine", "error": str(exc), "artefact_id": run["artefact_id"],
                    "made_at": run["finished_at"], "pending": pending}
        age = (datetime.now(run["finished_at"].tzinfo) - run["finished_at"]).total_seconds()
        with self.store.session() as conn:
            names = self._names(conn, client_id)
            roles = self._roles(conn)
        grid = []
        for cell in sheet.get("grid") or []:
            if isinstance(cell, dict):
                display, definition = self._role_text(roles, str(cell.get("role")), str(cell.get("capital_type")), lang)
                cell = {**cell, "display": display, "definition": definition}
            grid.append(cell)
        sheet = {**sheet, "grid": grid}
        mandate = ((run["request"] or {}).get("mandate") or {}).get("goal_id")
        missing = gaps.describe(list(sheet.get("gaps") or []), mandate_goal=mandate, **names)
        return {"available": True, "artefact_id": run["artefact_id"], "made_at": run["finished_at"],
                "age_s": round(max(age, 0.0), 1), "pending": pending, "missing": missing,
                "requested_by_kind": run["requested_by_kind"],
                "plan_changed_since": bool(changed and changed > run["created_at"]),
                "sheet": {k: sheet.get(k) for k in ("artefact_id", "as_of", "grid", "totals", "gaps", "household",
                                                    "calibration_version", "notice")}}

    # ------------------------------------------------------------------ threads

    def _thread(self, conn, client_id: str, thread_id: str, lock: bool = False) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM thread WHERE id = %s" + (" FOR UPDATE" if lock else ""), (thread_id,)).fetchone()
        if row is None or row["client_id"] != client_id:
            raise NotFound(f"no thread {thread_id} of this client")
        return row

    def threads(self, client_id: str) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            rows = store.list_threads(conn, client_id)
            waiting = {a["item_id"]: a["state"] for a in store.approvals(conn, client_id=client_id)
                       if a["item_kind"] == "answer"}
            spark = conn.execute("SELECT m.thread_id, m.id FROM thread_message m JOIN thread t ON t.id = m.thread_id "
                                 "WHERE t.client_id = %s AND m.author_kind = 'spark7'", (client_id,)).fetchall()
        out = []
        for r in rows:
            states = [waiting[s["id"]] for s in spark if s["thread_id"] == r["id"] and s["id"] in waiting]
            job = self._job("draft", r["id"])
            out.append({**r, "awaiting_curator": "awaiting_curator" in states,
                        "draft": job.public() if job and job.state != "done" else None})
        return out

    def thread(self, client_id: str, thread_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            t = self._thread(conn, client_id, thread_id)
            state = conn.execute("SELECT state FROM thread_state WHERE id = %s", (thread_id,)).fetchone()["state"]
            messages = store.thread_messages(conn, thread_id)
            approvals = {a["item_id"]: a for a in store.approvals(conn, client_id=client_id) if a["item_kind"] == "answer"}
            curators = {r["id"]: r["display_name"] for r in conn.execute(
                "SELECT id, display_name FROM curator WHERE id = ANY(%s)",
                ([m["author_ref"] for m in messages if m["author_kind"] == "curator"],)).fetchall()}
        revisions = {a["revision_item_id"]: a["item_id"] for a in approvals.values() if a["revision_item_id"]}
        out = []
        for m in messages:
            a = approvals.get(m["id"])
            out.append({**m, "author_name": curators.get(m["author_ref"]) if m["author_kind"] == "curator" else None,
                        "approval": a, "revises": revisions.get(m["id"])})
        job = self._job("draft", thread_id)
        return {**t, "state": state, "messages": out, "draft": job.public() if job else None}

    def ask(self, client_id: str, *, question: str, language: str = "de", subject: Optional[str] = None,
            wait: bool = False) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise Invalid("the question is empty")
        if len(question) > 2000:
            raise Invalid("a question has at most 2000 characters")
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            t = store.open_thread(conn, client_id=client_id, opened_by_kind="client", opened_by_ref=client_id,
                                  subject=(subject or question[:120]).strip())
            m = store.add_message(conn, thread_id=t["id"], author_kind="client", author_ref=client_id, body=question,
                                  language=_lang(language))
        self.draft(client_id, t["id"], wait=wait)
        return {"thread_id": t["id"], "message_id": m["id"]}

    def add_client_message(self, client_id: str, thread_id: str, *, body: str, language: str = "de",
                           wait: bool = False) -> dict[str, Any]:
        body = (body or "").strip()
        if not body:
            raise Invalid("the message is empty")
        if len(body) > 2000:
            raise Invalid("a message has at most 2000 characters")
        with self.store.session() as conn:
            self._thread(conn, client_id, thread_id)
            try:
                m = store.add_message(conn, thread_id=thread_id, author_kind="client", author_ref=client_id,
                                      body=body, language=_lang(language))
            except psycopg.errors.RaiseException as exc:
                raise Conflict(str(exc).split("\n")[0]) from exc
        self.draft(client_id, thread_id, wait=wait)
        return {"thread_id": thread_id, "message_id": m["id"]}

    def close_thread(self, client_id: str, thread_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            t = self._thread(conn, client_id, thread_id)
            if t["closed_at"] is not None:
                raise Conflict("the thread is already closed")
            return store.close_thread(conn, thread_id, closed_by_kind="client", closed_by_ref=client_id)

    def draft(self, client_id: str, thread_id: str, wait: bool = False) -> dict[str, Any]:
        """Ask spark7 (the chatbot engine) to draft an answer to the thread's latest client message."""
        with self.store.session() as conn:
            t = self._thread(conn, client_id, thread_id)
            if t["closed_at"] is not None:
                raise Conflict("the thread is closed")
        job = self._schedule("draft", thread_id, lambda: self._draft(client_id, thread_id), wait)
        return job.public()

    def _client_facts(self, conn, client_id: str) -> list[c.ClientFact]:
        client = store.get_client(conn, client_id)
        facts = [c.ClientFact(key="age", label="Alter bei der Registrierung", value=float(client["age_at_registration"]),
                              source="Kundenakte")]
        stated = {f["stated_key"]: f for f in store.plan_of(conn, client_id)["facts"]}
        answers = {a["question_key"]: a["value"] for key in qn.NAMES.values()
                   for a in store.get_answers(conn, client_id, key)}
        for key, label in (("canton", "Wohnkanton"), ("civil_status", "Zivilstand")):
            value = stated[key]["stated_value"] if key in stated else answers.get(key)
            if isinstance(value, str) and value.strip():
                facts.append(c.ClientFact(key=key, label=label, value=value.strip()[:200],
                                          source="Plan" if key in stated else "Fragebogen"))
        return facts

    def _sheet_facts(self, run: dict[str, Any], have: set[str]) -> list[c.ClientFact]:
        """For a question about the asker (EIG-51): what the latest balance sheet says about them, as client
        facts the answer may use: the three human-capital scores, the household income, the household. A sheet
        lbs cannot hand over now adds nothing (the question is answered without it)."""
        try:
            sheet = self.lbs.sheet_raw(run["artefact_id"])
        except EngineError:
            return []
        source = f"Lebensbilanz vom {run['finished_at']:%d.%m.%Y}"
        out: list[c.ClientFact] = []
        labels = {"E": "Fachwissen (E, 0 bis 1)", "N": "Berufliches Netzwerk (N, 0 bis 1)",
                  "H": "Belastbarkeit (H, 0 bis 1)"}
        people = sheet.get("human_capital") or []
        me = next((p for p in people if isinstance(p, dict) and p.get("person_id") == "p1"), None)
        for key in ("E", "N", "H"):
            value = ((me or {}).get(key) or {}).get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append(c.ClientFact(key=f"human_capital_{key}", label=labels[key], value=float(value), source=source))
        income = (sheet.get("totals") or {}).get("household_income")
        if isinstance(income, (int, float)) and not isinstance(income, bool):
            out.append(c.ClientFact(key="household_income", label="Haushaltseinkommen pro Jahr (CHF)",
                                    value=float(income), source=source))
        hh = sheet.get("household") or {}
        if hh.get("stated"):
            adults, dependants = len(hh.get("adults") or []), len(hh.get("dependants") or [])
            out.append(c.ClientFact(key="household", label="Haushalt",
                                    value=f"{adults} Erwachsene, {dependants} Angehörige", source=source))
        return [f for f in out if f.key not in have]

    def _draft(self, client_id: str, thread_id: str) -> None:
        with self.store.session() as conn:
            messages = store.thread_messages(conn, thread_id)
            clients_msgs = [m for m in messages if m["author_kind"] == "client"]
            if not clients_msgs or messages[-1]["author_kind"] != "client":
                return                                   # nothing unanswered
            last = clients_msgs[-1]
            notes = conn.execute("SELECT * FROM content_current WHERE kind = 'knowledge' ORDER BY key").fetchall()
            facts = self._client_facts(conn, client_id)
            alias_row = conn.execute("SELECT body FROM content_current WHERE key = 'reference/search-aliases'").fetchone()
            aliases = grounding.alias_groups(alias_row["body"]) if alias_row else []
            sheet_run = conn.execute("SELECT artefact_id, finished_at FROM engine_run WHERE client_id = %s AND engine = 'lbs' "
                                     "AND status = 'succeeded' ORDER BY finished_at DESC LIMIT 1", (client_id,)).fetchone()
        g = self.settings.grounding
        chosen = grounding.choose(last["body"], notes, max_notes=g.max_notes, max_chars_per_note=g.max_chars_per_note,
                                  min_score=g.min_score, language=_lang(last["language"]), aliases=aliases,
                                  floor=g.floor, fallback_notes=g.fallback_notes)
        if grounding.about_the_asker(last["body"]) and sheet_run:
            facts = facts + self._sheet_facts(sheet_run, {f.key for f in facts})
        history = []
        for m in messages[:-1]:
            text = m["body"] if len(m["body"]) <= 2000 else m["body"][:1990] + " […]"
            history.append(c.Turn(role="user" if m["author_kind"] == "client" else "assistant", content=text))
        request = c.ChatRequest(question=last["body"][:2000], language=_lang(last["language"]),
                                grounding=tuple(x.note for x in chosen), client_facts=tuple(facts),
                                history=tuple(history[-6:]))

        def call():
            answer = self.chatbot.answer(request)
            return answer, answer.artefact_id, None

        answer, run = self._engine_call(client_id, "chatbot", request, call)
        by_id = {x.note.id: x for x in chosen}
        sources = [by_id[i].source() for i in answer.cited_ids if i in by_id]
        with self.store.session() as conn:
            self._thread(conn, client_id, thread_id, lock=True)
            already = conn.execute("SELECT 1 FROM thread_message WHERE thread_id = %s AND author_kind = 'spark7' "
                                   "AND in_reply_to_id = %s", (thread_id, last["id"])).fetchone()
            if already:
                return
            store.add_message(conn, thread_id=thread_id, author_kind="spark7", author_ref="chatbot", body=answer.answer,
                              language=answer.language, sources=sources,
                              model=answer.model or f"none ({answer.refusal_code or 'no model call'})",
                              chatbot_artefact_id=answer.artefact_id, unverified_numbers=list(answer.unverified_numbers),
                              in_reply_to_id=last["id"], basis=None if answer.refused else answer.basis)

    # ------------------------------------------------------------------ approval (only on the client's request)

    def approvals(self, client_id: str) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            return store.approvals(conn, client_id=client_id)

    def request_approval(self, client_id: str, *, item: str, item_id: str, note: Optional[str] = None) -> dict[str, Any]:
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            if item == "answer":
                kind = "answer"
            elif item in ("report", "update"):
                row = conn.execute("SELECT q.kind FROM report r JOIN report_request q ON q.id = r.request_id "
                                   "WHERE r.id = %s AND r.client_id = %s", (item_id, client_id)).fetchone()
                if row is None:
                    raise NotFound(f"no report {item_id} of this client")
                kind = row["kind"]
            else:
                raise Invalid("an approval is asked for an answer or a report")
            existing = conn.execute("SELECT * FROM approval_state WHERE item_kind = %s AND item_id = %s",
                                    (kind, item_id)).fetchone()
            if existing:
                raise Conflict(f"approval was already asked for this item ({existing['state']})")
            try:
                with conn.transaction():
                    return store.request_approval(conn, client_id=client_id, item_kind=kind, item_id=item_id, note=note)
            except psycopg.errors.RaiseException as exc:
                raise NotFound(str(exc).split("\n")[0]) from exc
            except psycopg.errors.UniqueViolation as exc:
                raise Conflict("approval was already asked for this item") from exc

    def withdraw_approval(self, client_id: str, approval_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            a = conn.execute("SELECT * FROM approval_state WHERE id = %s", (approval_id,)).fetchone()
            if a is None or a["client_id"] != client_id:
                raise NotFound(f"no approval request {approval_id} of this client")
            if a["state"] != "awaiting_curator":
                raise Conflict(f"the request is {a['state']}; only a waiting request can be withdrawn")
            try:
                with conn.transaction():
                    return store.approval_event(conn, request_id=approval_id, event="withdrawn", actor_kind="client",
                                                actor_ref=client_id)
            except psycopg.errors.UniqueViolation as exc:
                raise Conflict("the curator decided in the meantime") from exc

    # ------------------------------------------------------------------ reports

    def reports(self, client_id: str) -> list[dict[str, Any]]:
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            requests = store.report_requests(conn, client_id)
            rows = conn.execute("SELECT id, seq, request_id, report_artefact_id, lbs_artefact_id, allocation_artefact_id, "
                                "created_at FROM report WHERE client_id = %s ORDER BY seq DESC", (client_id,)).fetchall()
            approvals = {a["item_id"]: a for a in store.approvals(conn, client_id=client_id)
                         if a["item_kind"] in ("report", "update")}
        revisions = {a["revision_item_id"]: a["item_id"] for a in approvals.values() if a["revision_item_id"]}
        out = []
        for q in requests:
            reps = [{**r, "approval": approvals.get(r["id"]), "revises": revisions.get(r["id"])}
                    for r in rows if r["request_id"] == q["id"]]
            job = self._job("report", q["id"])
            out.append({**q, "reports": reps, "job": job.public() if job and job.state != "done" else None})
        return out

    def report_html(self, client_id: str, report_id: str) -> str:
        with self.store.session() as conn:
            row = conn.execute("SELECT body_html, client_id FROM report WHERE id = %s", (report_id,)).fetchone()
        if row is None or row["client_id"] != client_id:
            raise NotFound(f"no report {report_id} of this client")
        return row["body_html"]

    def request_report(self, client_id: str, *, kind: str, language: str = "de", note: Optional[str] = None,
                       wait: bool = False) -> dict[str, Any]:
        if kind not in ("report", "update"):
            raise Invalid("kind is report or update")
        with self.store.session() as conn:
            store.get_client(conn, client_id)
            if kind == "update" and conn.execute("SELECT 1 FROM report WHERE client_id = %s LIMIT 1",
                                                 (client_id,)).fetchone() is None:
                raise Conflict("an update states the changes since an earlier report; ask for a report first")
            req = store.request_report(conn, client_id=client_id, kind=kind, requested_by_kind="client",
                                       requested_by_ref=client_id, language=_lang(language), note=note)
        job = self.produce(client_id, req["id"], wait=wait)
        return {"request_id": req["id"], "job": job}

    def withdraw_report_request(self, client_id: str, request_id: str) -> dict[str, Any]:
        with self.store.session() as conn:
            q = conn.execute("SELECT * FROM report_request_state WHERE id = %s", (request_id,)).fetchone()
            if q is None or q["client_id"] != client_id:
                raise NotFound(f"no report request {request_id} of this client")
            if q["state"] != "open":
                raise Conflict(f"the request is {q['state']}; only an open request can be withdrawn")
            try:
                with conn.transaction():
                    return store.withdraw_report_request(conn, request_id)
            except psycopg.errors.RaiseException as exc:
                raise Conflict(str(exc).split("\n")[0]) from exc

    def produce(self, client_id: str, request_id: str, *, wait: bool = False, revision: bool = False,
                revision_note: Optional[str] = None, revision_of: Optional[str] = None) -> dict[str, Any]:
        """Produce the report for an open request (or, with ``revision``, a new report for a fulfilled one:
        the path a curator's revision takes, SCHEMA.md 4.1). A revision names the report it revises (the
        request's latest, or ``revision_of``) and carries the curator's note to the report engine (EIG-57), so
        the engine makes a new artefact instead of answering from its cache."""
        note = (revision_note or "").strip() or None
        if (note or revision_of) and not revision:
            raise Invalid("a revision note or revision_of belongs to a revision (revision=true)")
        with self.store.session() as conn:
            q = conn.execute("SELECT * FROM report_request_state WHERE id = %s", (request_id,)).fetchone()
            if q is None or q["client_id"] != client_id:
                raise NotFound(f"no report request {request_id} of this client")
            if q["state"] == "withdrawn":
                raise Conflict("the request was withdrawn")
            if q["state"] == "fulfilled" and not revision:
                raise Conflict("the report exists; a new one for the same request is a revision")
            revised = None
            if revision:
                revised = conn.execute(
                    "SELECT id, report_artefact_id FROM report WHERE request_id = %s AND (%s::text IS NULL OR id = %s) "
                    "ORDER BY seq DESC LIMIT 1", (request_id, revision_of, revision_of)).fetchone()
                if revised is None and revision_of:
                    raise NotFound(f"no report {revision_of} of this request")
        of = revised["report_artefact_id"] if revised else None
        job = self._schedule("report", request_id,
                             lambda: self._produce(client_id, request_id, revision, of, note if of else None), wait)
        return job.public()

    def _produce(self, client_id: str, request_id: str, revision: bool, revision_of: Optional[str] = None,
                 revision_note: Optional[str] = None) -> None:
        with self.store.session() as conn:
            q = conn.execute("SELECT * FROM report_request WHERE id = %s", (request_id,)).fetchone()
            previous = conn.execute("SELECT report_artefact_id FROM report WHERE client_id = %s AND request_id <> %s "
                                    "ORDER BY seq DESC LIMIT 1", (client_id, request_id)).fetchone()
            pcp = conn.execute("SELECT artefact_id FROM engine_run WHERE client_id = %s AND engine = 'pcp' "
                               "AND status = 'succeeded' ORDER BY finished_at DESC LIMIT 1", (client_id,)).fetchone()
        if q["kind"] == "update" and previous is None:
            raise Conflict("an update needs an earlier report of this client")
        sheet = self.run_balance_sheet(client_id)
        sources = [c.SourceRef(engine="lbs", artefact_id=sheet["artefact_id"])]
        if pcp:
            sources.append(c.SourceRef(engine="pcp", artefact_id=pcp["artefact_id"]))
        request = c.ReportRequest(client_ref=client_id, kind=q["kind"], language=_lang(q["language"]),
                                  sources=tuple(sources),
                                  previous_report_id=previous["report_artefact_id"] if q["kind"] == "update" else None,
                                  revision_of=revision_of, revision_note=revision_note)

        def call():
            rep = self.report.report(request)
            return rep, rep.artefact_id, None

        rep, run = self._engine_call(client_id, "report", request, call)
        with self.store.session() as conn:
            conn.execute("SELECT 1 FROM report_request WHERE id = %s FOR UPDATE", (request_id,))
            if not revision and conn.execute("SELECT 1 FROM report WHERE request_id = %s", (request_id,)).fetchone():
                return
            store.add_report(conn, request_id=request_id, client_id=client_id, report_artefact_id=rep.artefact_id,
                             body_html=rep.html, lbs_artefact_id=sheet["artefact_id"],
                             allocation_artefact_id=pcp["artefact_id"] if pcp else None)

    # ------------------------------------------------------------------ home

    def home(self, client_id: str, language: str = "de") -> dict[str, Any]:
        lang = _lang(language)
        client = self.get_client(client_id)
        summary = {}
        for name in qn.NAMES:
            q = self.questionnaire(client_id, name, lang)
            by_key = {x["key"]: x for x in q["questions"]}
            nxt = q["next_question_key"]
            summary[name] = {
                "version": q["version"], "next_question_key": nxt,
                "next_question": _text(by_key[nxt].get("question"), lang) if nxt else None,
                "answered": [{"key": k, "question": _text(by_key[k].get("question"), lang) if k in by_key else k,
                              "section": by_key.get(k, {}).get("section"), "value": a["value"]}
                             for k, a in q["answers"].items()],
                "sections": q["sections"],
            }
        threads = self.threads(client_id)
        reports = self.reports(client_id)
        approvals = self.approvals(client_id)
        open_items = {
            "onboarding_open": client["onboarding_completed_at"] is None,
            "threads_awaiting_answer": [t for t in threads if t["state"] == "awaiting_answer"],
            "drafts_failed": [t for t in threads if t.get("draft") and t["draft"]["state"] == "failed"],
            "approvals_awaiting_curator": [a for a in approvals if a["state"] == "awaiting_curator"],
            "report_requests_open": [r for r in reports if r["state"] == "open"],
        }
        return {"client": client, "questionnaires": summary, "open": open_items,
                "balance_sheet": self.balance_sheet(client_id, schedule_if_stale=True, language=lang)}

    # ------------------------------------------------------------------ backfill (EIG-47)

    def lbs_backfill(self, *, limit: Optional[int] = None, dry_run: bool = False,
                     progress: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
        """One lbs run for every client (archived included) that has no successful lbs run yet, one after
        the other. Refuses to start when lbs does not answer its health probe, so a down engine leaves no
        failed runs behind."""
        with self.store.session() as conn:
            todo = [r["id"] for r in conn.execute(
                "SELECT c.id FROM client c WHERE NOT EXISTS (SELECT 1 FROM engine_run r WHERE r.client_id = c.id "
                "AND r.engine = 'lbs' AND r.status = 'succeeded') ORDER BY c.created_at, c.id").fetchall()]
        if limit is not None:
            todo = todo[:limit]
        out: dict[str, Any] = {"clients": len(todo), "succeeded": [], "failed": {}, "dry_run": dry_run}
        if dry_run or not todo:
            return out
        health = self.lbs.health(self.settings.timeouts.health_s)
        if not health["reachable"]:
            raise EngineUnavailable("lbs", f"lbs is not reachable at {health['url']}; nothing was run")
        for client_id in todo:
            try:
                self.run_balance_sheet(client_id, requested_by=("system", BACKFILL_REF))
                out["succeeded"].append(client_id)
                if progress:
                    progress(f"{client_id} ok")
            except EngineError as exc:
                out["failed"][client_id] = str(exc)
                if progress:
                    progress(f"{client_id} failed: {exc}")
        return out
