"""The curator's store: schema ``eigentlich``, read and written directly as role ``curator`` (C-16).

The contract is ``eigentliCH_Engines/eigentlich/SCHEMA.md``. Every rule that matters (append-only
tables, set-once columns, a revoked curator cannot act, content versions max+1, one terminal
approval event, a linear parameter-set chain, engine runs forward only) is enforced by the database;
this module only issues the SQL the contract documents and turns a refusal into a status code. It
never deletes: role ``curator`` holds no DELETE privilege, and nothing here asks for one.

One connection per unit of work, closed afterwards; ``search_path`` is set to the configured schema
on connect, so tests can point the same code at a throwaway ``t_<hex>`` schema. Nothing here logs a
value (answers and facts may be K3).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .settings import CuratorDb


class Unavailable(Exception):
    """The store cannot be reached or is not configured (HTTP 503)."""


class Refused(Exception):
    """The database refused a write or a read; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class NotFound(Refused):
    def __init__(self, detail: str):
        super().__init__(404, detail)


def _refusal(exc: psycopg.Error) -> Refused:
    """Map a database error to an HTTP status, keeping the database's own message (SCHEMA.md 1)."""
    diag = getattr(exc, "diag", None)
    message = (diag.message_primary if diag is not None and diag.message_primary else str(exc)).strip()
    state = getattr(exc, "sqlstate", None) or ""
    if state == "42501":                                   # no privilege: the role's boundary
        return Refused(403, f"refused by the database (no privilege): {message}")
    if state == "P0001":                                   # a rule raised by a trigger
        return Refused(403 if "revoked" in message else 409, message)
    if state == "23505":
        return Refused(409, message)
    if state[:2] in ("23", "22"):                          # check, foreign key, not null, bad value
        return Refused(422, message)
    return Refused(500, message)


class CuratorStore:
    def __init__(self, config: CuratorDb):
        self.config = config

    # ---- connection ---------------------------------------------------------------------

    def connect(self) -> psycopg.Connection:
        c = self.config
        if not c.configured:
            raise Unavailable("the curator's database password is not configured: put curator_db.password "
                              "in cockpit/config.local.yaml or set COCKPIT_CURATOR_DB_PASSWORD")
        try:
            conn = psycopg.connect(host=c.host, port=c.port, dbname=c.dbname, user=c.user, password=c.password,
                                   connect_timeout=c.connect_timeout, row_factory=dict_row,
                                   application_name="sim-tech cockpit (curator)")
        except psycopg.OperationalError as exc:
            raise Unavailable(f"the curator store at {c.host}:{c.port}/{c.dbname} is not reachable: "
                              f"{str(exc).strip().splitlines()[0] if str(exc).strip() else exc}") from exc
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(c.schema)))
        conn.commit()
        return conn

    @contextmanager
    def session(self) -> Iterator[psycopg.Connection]:
        """One unit of work: committed on success, rolled back on any error."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except psycopg.Error as exc:
            conn.rollback()
            raise _refusal(exc) from exc
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _all(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        with self.session() as conn:
            return conn.execute(query, params).fetchall()

    def _one(self, query: str, params: Any = None) -> Optional[dict[str, Any]]:
        with self.session() as conn:
            return conn.execute(query, params).fetchone()

    def status(self) -> dict[str, Any]:
        out = {**self.config.public(), "ok": False, "error": None}
        try:
            with self.session() as conn:
                row = conn.execute(
                    "SELECT current_user AS role, (SELECT count(*) FROM client) AS clients, "
                    "(SELECT count(*) FROM curator WHERE revoked_at IS NULL) AS curators_in_service, "
                    "(SELECT count(*) FROM content_current) AS content_keys").fetchone()
            out.update(ok=True, **row)
        except (Unavailable, Refused) as exc:
            out["error"] = str(exc)
        return out

    # ---- people -------------------------------------------------------------------------

    def curators(self) -> list[dict[str, Any]]:
        return self._all("SELECT id, display_name, role_label, fictional, revoked_at, revoked_at IS NULL AS in_service "
                         "FROM curator ORDER BY revoked_at IS NOT NULL, display_name")

    def clients(self, q: str = "", open_only: bool = False, archived: bool = False) -> list[dict[str, Any]]:
        where, params = ["TRUE"], []
        if not archived:
            where.append("archived_at IS NULL")
        if q:
            where.append("(display_name ILIKE %s OR id ILIKE %s)")
            params += [f"%{q}%", f"{q}%"]
        if open_only:
            where.append("(threads_awaiting_answer > 0 OR approvals_awaiting_curator > 0 OR report_requests_open > 0)")
        return self._all(f"SELECT * FROM client_overview WHERE {' AND '.join(where)} "
                         "ORDER BY threads_awaiting_answer DESC, approvals_awaiting_curator DESC, "
                         "report_requests_open DESC, display_name", params)

    def client(self, client_id: str) -> dict[str, Any]:
        """Everything the Client page shows, in one read."""
        with self.session() as conn:
            q = lambda query, *p: conn.execute(query, p or None).fetchall()  # noqa: E731
            head = conn.execute("SELECT * FROM client_overview WHERE id = %s", (client_id,)).fetchone()
            if head is None:
                raise NotFound(f"no client {client_id}")
            answers = q("""
                SELECT a.id, a.questionnaire_key, a.content_version, a.question_key, a.value, a.answered_at,
                       a.answered_by_kind, a.answered_by_ref, a.data_class, cc.version AS current_version,
                       qq.question -> 'question' AS question, qq.question ->> 'section' AS section,
                       (qq.question ->> 'order') AS question_order, qq.question -> 'options' AS options
                  FROM answer_current a
                  JOIN content_record cr ON cr.key = a.questionnaire_key AND cr.version = a.content_version
                  LEFT JOIN content_current cc ON cc.key = a.questionnaire_key
                  LEFT JOIN LATERAL (SELECT e AS question FROM jsonb_array_elements(cr.body -> 'questions') e
                                      WHERE e ->> 'key' = a.question_key LIMIT 1) qq ON true
                 WHERE a.client_id = %s ORDER BY a.questionnaire_key, a.seq""", client_id)
            households = q("""
                SELECT h.* FROM household h
                 WHERE h.id IN (SELECT household_id FROM household_member WHERE client_id = %s)
                 ORDER BY h.created_at""", client_id)
            members = q("""
                SELECT m.id, m.household_id, m.client_id, m.label, m.kind, m.joined_on, m.left_on
                  FROM household_member m
                 WHERE m.household_id IN (SELECT household_id FROM household_member WHERE client_id = %s)
                 ORDER BY m.household_id, m.created_at""", client_id)
            positions = q("""SELECT id, role, capital_type, label, description, magnitude, magnitude_unit, liquidity,
                                    stock_kind, time_basis, started_on, active, tags, decision_id
                               FROM position WHERE client_id = %s ORDER BY active DESC, role, created_at""", client_id)
            goals = q("""SELECT id, name, target_amount, target_date, safety, liquidity_need, volatility_tolerance,
                                horizon, flexibility, template, occupancy, frozen_at, active, decision_id
                           FROM goal WHERE client_id = %s ORDER BY active DESC, created_at""", client_id)
            facts = q("""SELECT id, stated_key, stated_value, stated_on, stated_by, data_class
                           FROM client_fact WHERE client_id = %s AND superseded_on IS NULL
                          ORDER BY stated_key""", client_id)
            threads = q("SELECT * FROM thread_state WHERE client_id = %s ORDER BY last_message_at DESC NULLS FIRST, "
                        "created_at DESC", client_id)
            messages = q("""SELECT m.id, m.thread_id, m.seq, m.author_kind, m.author_ref, m.body, m.language, m.sources,
                                   m.model, m.chatbot_artefact_id, m.unverified_numbers, m.in_reply_to_id, m.created_at,
                                   cu.display_name AS author_name
                              FROM thread_message m JOIN thread t ON t.id = m.thread_id
                              LEFT JOIN curator cu ON m.author_kind = 'curator' AND cu.id = m.author_ref
                             WHERE t.client_id = %s ORDER BY m.thread_id, m.seq""", client_id)
            requests = q("SELECT * FROM report_request_state WHERE client_id = %s ORDER BY created_at DESC", client_id)
            reports = q("""SELECT id, seq, request_id, report_artefact_id, lbs_artefact_id, allocation_artefact_id,
                                  created_at FROM report WHERE client_id = %s ORDER BY seq DESC""", client_id)
            approvals = q("SELECT * FROM approval_state WHERE client_id = %s ORDER BY created_at DESC", client_id)
            runs = q("""SELECT id, engine, parameter_set_id, requested_by_kind, requested_by_ref, run_id, artefact_id,
                               status, error, created_at, started_at, finished_at, request
                          FROM engine_run WHERE client_id = %s ORDER BY created_at DESC""", client_id)
            psets = q("""SELECT p.*, NOT EXISTS (SELECT 1 FROM parameter_set s WHERE s.supersedes_id = p.id) AS current,
                                cu.display_name AS finalised_by_name
                           FROM parameter_set p LEFT JOIN curator cu ON cu.id = p.finalised_by
                          WHERE p.client_id = %s ORDER BY p.finalised_at DESC""", client_id)
        by_thread: dict[str, list[dict[str, Any]]] = {}
        for m in messages:
            by_thread.setdefault(m["thread_id"], []).append(m)
        for t in threads:
            t["messages"] = by_thread.get(t["id"], [])
        return {"client": head, "answers": answers, "households": households, "members": members,
                "positions": positions, "goals": goals, "facts": facts, "threads": threads,
                "report_requests": requests, "reports": reports, "approvals": approvals, "engine_runs": runs,
                "parameter_sets": psets}

    @staticmethod
    def _in_service(conn: psycopg.Connection, curator_id: str) -> None:
        cur = conn.execute("SELECT revoked_at FROM curator WHERE id = %s", (curator_id,)).fetchone()
        if cur is None:
            raise Refused(422, f"no curator {curator_id}")
        if cur["revoked_at"] is not None:
            raise Refused(403, f"curator {curator_id} is revoked and cannot act (A161)")

    def acting(self, client_id: str, curator_id: str) -> None:
        """Check, before a call the cockpit does not write itself (C-20), that the client exists and the
        acting curator is in service; raises as a refused write would."""
        with self.session() as conn:
            if conn.execute("SELECT 1 FROM client WHERE id = %s", (client_id,)).fetchone() is None:
                raise NotFound(f"no client {client_id}")
            self._in_service(conn, curator_id)

    def in_service(self, curator_id: str) -> None:
        """Check, before a write to an engine that concerns no client (C-32), that the acting curator
        exists and is in service; raises as a refused write would."""
        with self.session() as conn:
            self._in_service(conn, curator_id)

    def latest_run(self, client_id: str, engine: str) -> Optional[dict[str, Any]]:
        """The client's most recent ``engine_run`` for this engine, whoever requested it."""
        return self._one("""SELECT id, engine, parameter_set_id, requested_by_kind, requested_by_ref, run_id, artefact_id,
                                   status, error, created_at, started_at, finished_at, request
                              FROM engine_run WHERE client_id = %s AND engine = %s
                             ORDER BY created_at DESC, id DESC LIMIT 1""", (client_id, engine))

    def recent_runs(self, client_id: str, engine: str, limit: int = 20) -> list[dict[str, Any]]:
        """The client's newest ``engine_run`` rows for this engine, newest first (an lbsim call records
        two: the fast run and the plan run, C-34)."""
        return self._all("""SELECT id, engine, parameter_set_id, requested_by_kind, requested_by_ref, run_id, artefact_id,
                                   status, error, created_at, started_at, finished_at, request
                              FROM engine_run WHERE client_id = %s AND engine = %s
                             ORDER BY created_at DESC, id DESC LIMIT %s""", (client_id, engine, limit))

    def open_session(self, client_id: str, curator_id: str, opened_from: str = "cockpit") -> dict[str, Any]:
        """C-10 audit: a curator opened this client's material. Append-only, both rows."""
        with self.session() as conn:
            self._in_service(conn, curator_id)
            s = conn.execute("INSERT INTO curator_session (client_id, curator_id, opened_from) VALUES (%s, %s, %s) "
                             "RETURNING *", (client_id, curator_id, opened_from)).fetchone()
            conn.execute("INSERT INTO curator_session_event (session_id, kind, actor, detail) VALUES (%s, 'opened', %s, %s)",
                         (s["id"], curator_id, Jsonb({"page": "client"})))
            return s

    # ---- threads ------------------------------------------------------------------------

    def answer_thread(self, thread_id: str, curator_id: str, body: str, language: str = "de",
                      in_reply_to_id: Optional[str] = None, close: bool = False) -> dict[str, Any]:
        with self.session() as conn:
            if in_reply_to_id is None:  # reply to the thread's last client message, if any
                last = conn.execute("SELECT id FROM thread_message WHERE thread_id = %s AND author_kind = 'client' "
                                    "ORDER BY seq DESC LIMIT 1", (thread_id,)).fetchone()
                in_reply_to_id = last["id"] if last else None
            m = conn.execute("""INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id)
                                VALUES (%s, 'curator', %s, %s, %s, %s) RETURNING *""",
                             (thread_id, curator_id, body, language, in_reply_to_id)).fetchone()
            if close:
                self._close(conn, thread_id, curator_id)
            return m

    def close_thread(self, thread_id: str, curator_id: str) -> dict[str, Any]:
        with self.session() as conn:
            return self._close(conn, thread_id, curator_id)

    @staticmethod
    def _close(conn: psycopg.Connection, thread_id: str, curator_id: str) -> dict[str, Any]:
        row = conn.execute("UPDATE thread SET closed_at = now(), closed_by_kind = 'curator', closed_by_ref = %s "
                           "WHERE id = %s RETURNING *", (curator_id, thread_id)).fetchone()
        if row is None:
            raise NotFound(f"no thread {thread_id}")
        return row

    # ---- reports ------------------------------------------------------------------------

    def report(self, report_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM report WHERE id = %s", (report_id,))
        if row is None:
            raise NotFound(f"no report {report_id}")
        return row

    # ---- approvals ----------------------------------------------------------------------

    def approvals(self, state: Optional[str] = "awaiting_curator") -> list[dict[str, Any]]:
        where = "WHERE a.state = %s" if state else ""
        return self._all(f"""
            SELECT a.*, c.display_name AS client_name,
                   m.body AS item_body, m.thread_id AS item_thread_id, m.model AS item_model,
                   r.report_artefact_id AS item_report_artefact_id, r.request_id AS item_request_id
              FROM approval_state a JOIN client c ON c.id = a.client_id
              LEFT JOIN thread_message m ON a.item_kind = 'answer' AND m.id = a.item_id
              LEFT JOIN report r ON a.item_kind IN ('report', 'update') AND r.id = a.item_id
              {where} ORDER BY a.created_at""", (state,) if state else None)

    def approve(self, request_id: str, curator_id: str, note: Optional[str] = None) -> dict[str, Any]:
        with self.session() as conn:
            return conn.execute("""INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, note)
                                   VALUES (%s, 'approved', 'curator', %s, %s) RETURNING *""",
                                (request_id, curator_id, note)).fetchone()

    def revise(self, request_id: str, curator_id: str, note: Optional[str] = None, body: Optional[str] = None,
               revision_item_id: Optional[str] = None, language: str = "de") -> dict[str, Any]:
        """Send a revision. For an AI-drafted answer the corrected answer is written here, as a curator
        message in the same thread, and named in the event (one transaction). For a report or update the
        revised report is produced by the backend; the curator names it (``revision_item_id``)."""
        with self.session() as conn:
            q = conn.execute("SELECT * FROM approval_request WHERE id = %s", (request_id,)).fetchone()
            if q is None:
                raise NotFound(f"no approval request {request_id}")
            if q["item_kind"] == "answer" and revision_item_id is None:
                if not (body or "").strip():
                    raise Refused(422, "a revision of an answer needs the corrected answer")
                ai = conn.execute("SELECT thread_id FROM thread_message WHERE id = %s", (q["item_id"],)).fetchone()
                revision_item_id = conn.execute(
                    """INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id)
                       VALUES (%s, 'curator', %s, %s, %s, %s) RETURNING id""",
                    (ai["thread_id"], curator_id, body, language, q["item_id"])).fetchone()["id"]
            if revision_item_id is None:
                raise Refused(422, "name the revised report (revision_item_id); the backend produces it")
            return conn.execute("""INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, revision_item_id, note)
                                   VALUES (%s, 'revision_sent', 'curator', %s, %s, %s) RETURNING *""",
                                (request_id, curator_id, revision_item_id, note)).fetchone()

    # ---- parameter sets and engine runs -------------------------------------------------

    def parameter_sets(self, client_id: str, engine: str = "pcp") -> list[dict[str, Any]]:
        return self._all("""SELECT p.*, NOT EXISTS (SELECT 1 FROM parameter_set s WHERE s.supersedes_id = p.id) AS current
                              FROM parameter_set p WHERE p.client_id = %s AND p.engine = %s
                             ORDER BY p.finalised_at DESC""", (client_id, engine))

    def parameter_set(self, set_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM parameter_set WHERE id = %s", (set_id,))
        if row is None:
            raise NotFound(f"no parameter set {set_id}")
        return row

    def current_parameter_set(self, client_id: str, engine: str = "pcp") -> Optional[dict[str, Any]]:
        return self._one("SELECT * FROM parameter_set_current WHERE client_id = %s AND engine = %s",
                         (client_id, engine))

    def finalise(self, client_id: str, engine: str, contract_version: str, body: dict[str, Any],
                 curator_id: str, note: Optional[str] = None) -> dict[str, Any]:
        """Append a parameter set that supersedes the current one (SCHEMA.md 7). Two concurrent
        finalisations cannot fork the chain: the unique indexes refuse the second."""
        with self.session() as conn:
            return conn.execute("""
                INSERT INTO parameter_set (client_id, engine, contract_version, body, finalised_by, supersedes_id, note)
                SELECT %s, %s, %s, %s, %s,
                       (SELECT id FROM parameter_set_current WHERE client_id = %s AND engine = %s), %s
                RETURNING *""", (client_id, engine, contract_version, Jsonb(body), curator_id, client_id, engine,
                                 note)).fetchone()

    def start_run(self, client_id: str, engine: str, request: dict[str, Any], curator_id: str,
                  parameter_set_id: Optional[str] = None) -> dict[str, Any]:
        with self.session() as conn:
            return conn.execute("""
                INSERT INTO engine_run (client_id, engine, parameter_set_id, request, requested_by_kind, requested_by_ref)
                VALUES (%s, %s, %s, %s, 'curator', %s) RETURNING *""",
                                (client_id, engine, parameter_set_id, Jsonb(request), curator_id)).fetchone()

    def engine_run(self, run_row_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM engine_run WHERE id = %s", (run_row_id,))
        if row is None:
            raise NotFound(f"no engine run {run_row_id}")
        return row

    def advance_run(self, run_row_id: str, status: str, run_id: Optional[str] = None,
                    artefact_id: Optional[str] = None, error: Optional[str] = None) -> dict[str, Any]:
        """Move a run forward (queued -> running -> succeeded | failed); the database refuses anything else."""
        terminal = status in ("succeeded", "failed")
        with self.session() as conn:
            row = conn.execute("""
                UPDATE engine_run SET status = %s, run_id = coalesce(%s, run_id), artefact_id = coalesce(%s, artefact_id),
                       error = coalesce(%s, error),
                       started_at = CASE WHEN %s <> 'queued' THEN coalesce(started_at, now()) ELSE started_at END,
                       finished_at = CASE WHEN %s THEN now() ELSE finished_at END
                 WHERE id = %s RETURNING *""", (status, run_id, artefact_id, error, status, terminal,
                                                run_row_id)).fetchone()
        if row is None:
            raise NotFound(f"no engine run {run_row_id}")
        return row

    # ---- content ------------------------------------------------------------------------

    def content_keys(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        where = "WHERE kind = %s" if kind else ""
        return self._all(f"""
            SELECT key, version, kind, saved_by_kind, saved_by_ref, saved_at, note,
                   CASE WHEN kind = 'questionnaire' THEN jsonb_array_length(body -> 'questions') END AS questions,
                   cu.display_name AS saved_by_name
              FROM content_current LEFT JOIN curator cu ON saved_by_kind = 'curator' AND cu.id = saved_by_ref
              {where} ORDER BY kind, key""", (kind,) if kind else None)

    def content_versions(self, key: str) -> list[dict[str, Any]]:
        rows = self._all("""SELECT r.key, r.version, r.kind, r.saved_by_kind, r.saved_by_ref, r.saved_at, r.note,
                                   cu.display_name AS saved_by_name
                              FROM content_record r LEFT JOIN curator cu ON r.saved_by_kind = 'curator' AND cu.id = r.saved_by_ref
                             WHERE r.key = %s ORDER BY r.version DESC""", (key,))
        if not rows:
            raise NotFound(f"no content {key}")
        return rows

    def content_version(self, key: str, version: Optional[int] = None) -> dict[str, Any]:
        if version is None:
            row = self._one("SELECT * FROM content_current WHERE key = %s", (key,))
        else:
            row = self._one("SELECT * FROM content_record WHERE key = %s AND version = %s", (key, version))
        if row is None:
            raise NotFound(f"no content {key}" + (f" version {version}" if version else ""))
        return row

    def save_content(self, key: str, kind: str, body: dict[str, Any], curator_id: str,
                     note: Optional[str] = None) -> int:
        """A new version (max+1) through the documented function ``save_content()``."""
        with self.session() as conn:
            return conn.execute("SELECT save_content(%s, %s, %s, 'curator', %s, %s) AS version",
                                (key, kind, Jsonb(body), curator_id, note)).fetchone()["version"]

    def bind_check(self, mismatches_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE status <> 'ok'" if mismatches_only else ""
        return self._all(f"SELECT * FROM scoring_bind_check {where} ORDER BY scoring_key, bind_index")
