"""The eigentlich store in PostgreSQL: connections, initialisation and the repository the backend uses.

psycopg and one ``schema.sql``; no ORM, no migrations framework (owner decision, Build Instruction 9.1).
The rules that matter (append-only, C-09, content versioning, set-once columns, revoked curators) are
enforced by the database itself, so they hold for the cockpit's direct writes as role ``curator`` as
much as for this code. The functions here are the convenient path, not the enforcement.

Connections: one per unit of work, opened on demand and closed afterwards (``Store.session``). Nothing
is shared between threads. Repository functions take an open connection and never commit; the caller's
``session()`` commits or rolls back.

Logging: nothing here logs values. K3 values (health, submissions) never reach a log line (C-04).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib import resources
from typing import Any, Iterator, Mapping, Optional, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .settings import DatabaseConfig

#: The advisory lock ``initialise()`` holds while it applies ``schema.sql``.
SCHEMA_LOCK = "eigentlich.schema"


class StoreError(RuntimeError):
    """The store is unreachable or not initialised. The message says what to run."""


class NotFound(LookupError):
    """A named row does not exist."""


#: The tables schema.sql creates, in dependency order. Tests and ``show`` read this list; a table
#: added to schema.sql and not here fails ``test_every_table_is_listed``.
TABLES: tuple[str, ...] = (
    "curator", "client", "consent", "content_record", "answer", "submission",
    "curator_session", "curator_session_event", "decision",
    "household", "household_member", "position", "goal", "goal_funding", "goal_owner", "client_fact",
    "decision_position", "decision_goal", "decision_household", "decision_household_member",
    "decision_client_fact",
    "thread", "thread_message", "report_request", "report", "approval_request", "approval_event",
    "parameter_set", "engine_run", "migration_run",
)

VIEWS: tuple[str, ...] = (
    "scoring_bind_check",
    "content_current", "answer_current", "thread_state", "report_request_state", "approval_state",
    "parameter_set_current", "client_overview",
)

#: The plan tables of C-09 and the columns a plan change may write.
PLAN_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "household": ("id", "composition_as_of", "stated_by", "closed_on", "succeeds_household_id", "data_class"),
    "household_member": ("id", "household_id", "client_id", "label", "kind", "joined_on", "left_on", "data_class"),
    "position": ("id", "client_id", "role", "capital_type", "label", "description", "magnitude", "magnitude_unit",
                 "tags", "time_basis", "started_on", "active", "liquidity", "stock_kind", "owner", "data_class"),
    "goal": ("id", "client_id", "name", "target_amount", "target_date", "safety", "liquidity_need",
             "volatility_tolerance", "horizon", "flexibility", "template", "frozen_at", "occupancy", "active",
             "contribution_share", "amount_basis", "data_class"),
    "client_fact": ("id", "client_id", "stated_key", "stated_value", "stated_on", "stated_by", "superseded_on",
                    "data_class"),
}

_JSON_COLUMNS = {"tags", "stated_value", "value", "body", "request", "sources", "unverified_numbers",
                 "options_considered", "payload", "mapping_report", "detail", "reconciliation"}


#: Columns named like a JSON column that are text in their table. ``thread_message.body`` is text, while
#: ``content_record.body`` and ``parameter_set.body`` are jsonb: adapting it as JSON stored every message
#: with JSON quotes (found by the app's thread tests, EIG-37).
_TEXT_COLUMNS = {("thread_message", "body")}


def _adapt(column: str, value: Any, table: str = "") -> Any:
    if (table, column) in _TEXT_COLUMNS:
        return value
    return Jsonb(value) if column in _JSON_COLUMNS and value is not None else value


class Store:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    # -- connections -------------------------------------------------------

    def connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.config.conninfo(), row_factory=dict_row)
        except psycopg.OperationalError as exc:
            raise StoreError(
                f"cannot reach PostgreSQL at {self.config.redacted_url()}: {exc}. "
                "Start it with `docker compose up -d` in Projects\\PostgreSQL, and provision the roles once "
                "with `python -m store.provision` in Projects\\Engines\\Instruments."
            ) from exc
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.config.schema)))
        conn.commit()
        return conn

    @contextmanager
    def session(self) -> Iterator[psycopg.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- lifecycle ---------------------------------------------------------

    def initialise(self) -> None:
        """Create the schema's tables, functions, triggers and views. Idempotent.

        The schema itself must exist and be owned by this role (provisioning creates ``eigentlich``;
        the tests create their throwaway ``t_<hex>``). ``CREATE SCHEMA IF NOT EXISTS`` covers the latter.
        """
        ddl = resources.files("eigentlich").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            # The app and the init-db command may apply the schema at the same moment; the lock queues them, so
            # PostgreSQL never sees two at once (they can deadlock on pg_proc). Released at commit or rollback.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SCHEMA_LOCK,))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.config.schema)))
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.config.schema)))
            conn.execute(ddl)

    def drop_schema(self) -> None:
        with self.session() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.config.schema)))


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _insert(conn: psycopg.Connection, table: str, values: Mapping[str, Any],
            returning: str = "*") -> dict[str, Any]:
    cols = [c for c, v in values.items() if v is not None]
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)), sql.SQL(returning))
    return conn.execute(query, [_adapt(c, values[c], table) for c in cols]).fetchone()


def _update(conn: psycopg.Connection, table: str, row_id: str, values: Mapping[str, Any],
            key: str = "id") -> dict[str, Any]:
    if not values:
        raise ValueError("nothing to update")
    query = sql.SQL("UPDATE {} SET {} WHERE {} = %s RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in values),
        sql.Identifier(key))
    row = conn.execute(query, [*(_adapt(c, v, table) for c, v in values.items()), row_id]).fetchone()
    if row is None:
        raise NotFound(f"no {table} {row_id}")
    return row


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"]
            for t in TABLES}


# ---------------------------------------------------------------------------
# Curators and clients
# ---------------------------------------------------------------------------

def create_curator(conn, *, display_name: str, email: Optional[str] = None, role_label: Optional[str] = None,
                   fictional: bool = False, created_by_kind: str = "operator") -> dict[str, Any]:
    return _insert(conn, "curator", {"display_name": display_name, "email": email, "role_label": role_label,
                                     "fictional": fictional, "created_by_kind": created_by_kind})


def list_curators(conn, *, in_service_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE revoked_at IS NULL" if in_service_only else ""
    return conn.execute(f"SELECT * FROM curator {where} ORDER BY display_name, id").fetchall()


def revoke_curator(conn, curator_id: str, reason: str) -> dict[str, Any]:
    return _update(conn, "curator", curator_id, {"revoked_at": datetime.now().astimezone(), "revoked_reason": reason})


def create_client(conn, *, display_name: str, age_at_registration: int, locale: str = "de-CH",
                  created_by_kind: str = "client", created_by_ref: Optional[str] = None,
                  stage_hint: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "client", {"display_name": display_name, "age_at_registration": age_at_registration,
                                    "locale": locale, "created_by_kind": created_by_kind,
                                    "created_by_ref": created_by_ref, "stage_hint": stage_hint})


def get_client(conn, client_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM client WHERE id = %s", (client_id,)).fetchone()
    if row is None:
        raise NotFound(f"no client {client_id}")
    return row


def list_clients(conn, *, include_archived: bool = False) -> list[dict[str, Any]]:
    """The client picker: every client with its open counts (view client_overview)."""
    where = "" if include_archived else "WHERE archived_at IS NULL"
    return conn.execute(f"SELECT * FROM client_overview {where} ORDER BY display_name, id").fetchall()


def update_client(conn, client_id: str, **values: Any) -> dict[str, Any]:
    return _update(conn, "client", client_id, values)


def grant_consent(conn, *, client_id: str, purpose: str, document_version: str,
                  granted_at: Optional[datetime] = None, notes: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "consent", {"client_id": client_id, "purpose": purpose, "document_version": document_version,
                                     "granted_at": granted_at or datetime.now().astimezone(), "notes": notes})


def withdraw_consent(conn, consent_id: str) -> dict[str, Any]:
    return _update(conn, "consent", consent_id, {"withdrawn_at": datetime.now().astimezone()})


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def content_current(conn, key: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM content_current WHERE key = %s", (key,)).fetchone()
    if row is None:
        raise NotFound(f"no content {key}")
    return row


def content_version(conn, key: str, version: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM content_record WHERE key = %s AND version = %s", (key, version)).fetchone()
    if row is None:
        raise NotFound(f"no content {key}@{version}")
    return row


def content_keys(conn, kind: Optional[str] = None) -> list[dict[str, Any]]:
    """Every key with its latest version, kind, who saved it and when."""
    if kind:
        return conn.execute("SELECT key, version, kind, saved_by_kind, saved_by_ref, saved_at FROM content_current "
                            "WHERE kind = %s ORDER BY key", (kind,)).fetchall()
    return conn.execute("SELECT key, version, kind, saved_by_kind, saved_by_ref, saved_at FROM content_current "
                        "ORDER BY key").fetchall()


def content_history(conn, key: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT key, version, kind, saved_by_kind, saved_by_ref, saved_at, note FROM content_record "
                        "WHERE key = %s ORDER BY version", (key,)).fetchall()


def save_content(conn, *, key: str, kind: str, body: Any, saved_by_kind: str, saved_by_ref: str,
                 note: Optional[str] = None) -> int:
    """Save a new version; returns its number (max+1, assigned by the database under a lock)."""
    return conn.execute("SELECT save_content(%s, %s, %s, %s, %s, %s) AS v",
                        (key, kind, Jsonb(body), saved_by_kind, saved_by_ref, note)).fetchone()["v"]


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def put_answer(conn, *, client_id: str, questionnaire_key: str, content_version: int, question_key: str,
               value: Any, answered_by_kind: str, answered_by_ref: str,
               answered_at: Optional[datetime] = None) -> dict[str, Any]:
    """Record an answer, superseding the current one for the same question. Serialised per client."""
    with conn.transaction():
        if conn.execute("SELECT 1 FROM client WHERE id = %s FOR NO KEY UPDATE", (client_id,)).fetchone() is None:
            raise NotFound(f"no client {client_id}")
        old = conn.execute(
            "UPDATE answer SET superseded_at = now() WHERE client_id = %s AND questionnaire_key = %s "
            "AND question_key = %s AND superseded_at IS NULL RETURNING id",
            (client_id, questionnaire_key, question_key)).fetchone()
        new = _insert(conn, "answer", {
            "client_id": client_id, "questionnaire_key": questionnaire_key, "content_version": content_version,
            "question_key": question_key, "value": value, "answered_by_kind": answered_by_kind,
            "answered_by_ref": answered_by_ref, "answered_at": answered_at})
        if old is not None:
            _update(conn, "answer", old["id"], {"superseded_by_id": new["id"]})
        return new


def get_answers(conn, client_id: str, questionnaire_key: str, *, include_history: bool = False) -> list[dict[str, Any]]:
    view = "answer" if include_history else "answer_current"
    return conn.execute(f"SELECT * FROM {view} WHERE client_id = %s AND questionnaire_key = %s "
                        "ORDER BY question_key, seq", (client_id, questionnaire_key)).fetchall()


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

def open_thread(conn, *, client_id: str, opened_by_kind: str, opened_by_ref: str,
                subject: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "thread", {"client_id": client_id, "subject": subject, "opened_by_kind": opened_by_kind,
                                    "opened_by_ref": opened_by_ref})


def add_message(conn, *, thread_id: str, author_kind: str, author_ref: str, body: str, language: str,
                sources: Sequence[Any] = (), model: Optional[str] = None, chatbot_artefact_id: Optional[str] = None,
                unverified_numbers: Sequence[Any] = (), in_reply_to_id: Optional[str] = None,
                basis: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "thread_message", {
        "thread_id": thread_id, "author_kind": author_kind, "author_ref": author_ref, "body": body,
        "language": language, "sources": list(sources), "model": model, "chatbot_artefact_id": chatbot_artefact_id,
        "unverified_numbers": list(unverified_numbers), "in_reply_to_id": in_reply_to_id, "basis": basis})


def close_thread(conn, thread_id: str, *, closed_by_kind: str, closed_by_ref: str) -> dict[str, Any]:
    return _update(conn, "thread", thread_id, {"closed_at": datetime.now().astimezone(),
                                               "closed_by_kind": closed_by_kind, "closed_by_ref": closed_by_ref})


def list_threads(conn, client_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM thread_state WHERE client_id = %s ORDER BY created_at DESC, id",
                        (client_id,)).fetchall()


def thread_messages(conn, thread_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM thread_message WHERE thread_id = %s ORDER BY seq",
                        (thread_id,)).fetchall()


# ---------------------------------------------------------------------------
# Report requests and reports
# ---------------------------------------------------------------------------

def request_report(conn, *, client_id: str, kind: str, requested_by_kind: str, requested_by_ref: str,
                   language: str, note: Optional[str] = None, basis: Optional[str] = None,
                   scenario: Optional[str] = None) -> dict[str, Any]:
    """``basis`` (``nominal`` or ``real``; None is nominal) and ``scenario`` (a scenario Regime asked for; None is
    the base Regime) are stored only when given (EIG-62, EIG-63)."""
    values = {"client_id": client_id, "kind": kind, "requested_by_kind": requested_by_kind,
              "requested_by_ref": requested_by_ref, "language": language, "note": note}
    if basis is not None:
        values["basis"] = basis
    if scenario is not None:
        values["scenario"] = scenario
    return _insert(conn, "report_request", values)


def withdraw_report_request(conn, request_id: str) -> dict[str, Any]:
    return _update(conn, "report_request", request_id, {"withdrawn_at": datetime.now().astimezone()})


def add_report(conn, *, request_id: str, client_id: str, report_artefact_id: str, body_html: str,
               lbs_artefact_id: Optional[str] = None, allocation_artefact_id: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "report", {"request_id": request_id, "client_id": client_id,
                                    "report_artefact_id": report_artefact_id, "body_html": body_html,
                                    "lbs_artefact_id": lbs_artefact_id, "allocation_artefact_id": allocation_artefact_id})


def report_requests(conn, client_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM report_request_state WHERE client_id = %s ORDER BY created_at DESC, id",
                        (client_id,)).fetchall()


def get_report(conn, report_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM report WHERE id = %s", (report_id,)).fetchone()
    if row is None:
        raise NotFound(f"no report {report_id}")
    return row


# ---------------------------------------------------------------------------
# Approval (only on the client's request)
# ---------------------------------------------------------------------------

def request_approval(conn, *, client_id: str, item_kind: str, item_id: str,
                     note: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "approval_request", {"client_id": client_id, "item_kind": item_kind, "item_id": item_id,
                                              "requested_by": client_id, "note": note})


def approval_event(conn, *, request_id: str, event: str, actor_kind: str, actor_ref: str,
                   note: Optional[str] = None, revision_item_id: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "approval_event", {"request_id": request_id, "event": event, "actor_kind": actor_kind,
                                            "actor_ref": actor_ref, "note": note, "revision_item_id": revision_item_id})


def approvals(conn, *, client_id: Optional[str] = None, state: Optional[str] = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    if client_id:
        clauses.append("client_id = %s")
        params.append(client_id)
    if state:
        clauses.append("state = %s")
        params.append(state)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(f"SELECT * FROM approval_state {where} ORDER BY created_at, id", params).fetchall()


# ---------------------------------------------------------------------------
# Parameter sets and engine runs
# ---------------------------------------------------------------------------

def finalise_parameter_set(conn, *, client_id: str, engine: str, contract_version: str, body: Mapping[str, Any],
                           finalised_by: str, note: Optional[str] = None) -> dict[str, Any]:
    """Append a set superseding the current one for this client and engine, if any."""
    with conn.transaction():
        conn.execute("SELECT 1 FROM client WHERE id = %s FOR NO KEY UPDATE", (client_id,))
        current = conn.execute("SELECT id FROM parameter_set_current WHERE client_id = %s AND engine = %s",
                               (client_id, engine)).fetchone()
        return _insert(conn, "parameter_set", {
            "client_id": client_id, "engine": engine, "contract_version": contract_version, "body": dict(body),
            "finalised_by": finalised_by, "supersedes_id": current["id"] if current else None, "note": note})


def current_parameter_set(conn, client_id: str, engine: str) -> Optional[dict[str, Any]]:
    return conn.execute("SELECT * FROM parameter_set_current WHERE client_id = %s AND engine = %s",
                        (client_id, engine)).fetchone()


def start_engine_run(conn, *, client_id: str, engine: str, request: Any, requested_by_kind: str,
                     requested_by_ref: str, parameter_set_id: Optional[str] = None) -> dict[str, Any]:
    return _insert(conn, "engine_run", {"client_id": client_id, "engine": engine, "request": request,
                                        "requested_by_kind": requested_by_kind, "requested_by_ref": requested_by_ref,
                                        "parameter_set_id": parameter_set_id})


def mark_engine_run_running(conn, run_row_id: str, *, run_id: Optional[str] = None) -> dict[str, Any]:
    return _update(conn, "engine_run", run_row_id, {"status": "running", "run_id": run_id,
                                                    "started_at": datetime.now().astimezone()})


def finish_engine_run(conn, run_row_id: str, *, status: str, artefact_id: Optional[str] = None,
                      error: Optional[str] = None, run_id: Optional[str] = None) -> dict[str, Any]:
    if status not in ("succeeded", "failed"):
        raise ValueError(f"a run finishes as succeeded or failed, not {status!r}")
    values: dict[str, Any] = {"status": status, "artefact_id": artefact_id, "error": error,
                              "finished_at": datetime.now().astimezone()}
    if run_id is not None:
        values["run_id"] = run_id
    return _update(conn, "engine_run", run_row_id, values)


def engine_runs(conn, client_id: str, engine: Optional[str] = None) -> list[dict[str, Any]]:
    if engine:
        return conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = %s ORDER BY created_at DESC",
                            (client_id, engine)).fetchall()
    return conn.execute("SELECT * FROM engine_run WHERE client_id = %s ORDER BY created_at DESC",
                        (client_id,)).fetchall()


# ---------------------------------------------------------------------------
# The plan (C-09)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """What is decided. ``client_id`` is required for a live decision."""

    client_id: str
    author: str                    # client | curator | system
    question: str
    choice: str
    author_ref: Optional[str] = None
    options_considered: Sequence[Any] = field(default_factory=list)
    reasoning: Optional[str] = None
    curator_session_id: Optional[str] = None
    corrects_id: Optional[str] = None


class PlanChange:
    """Writes plan rows under one decision, inside the transaction that wrote the decision."""

    def __init__(self, conn: psycopg.Connection, decision: dict[str, Any]):
        self.conn = conn
        self.decision = decision
        self.decision_id: str = decision["id"]

    def _check(self, table: str, values: Mapping[str, Any]) -> None:
        if table not in PLAN_COLUMNS:
            raise ValueError(f"{table} is not a plan table")
        unknown = set(values) - set(PLAN_COLUMNS[table])
        if unknown:
            raise ValueError(f"{table}: unknown or protected columns {sorted(unknown)}")

    def insert(self, table: str, **values: Any) -> dict[str, Any]:
        self._check(table, values)
        return _insert(self.conn, table, {**values, "decision_id": self.decision_id})

    def update(self, table: str, row_id: str, **values: Any) -> dict[str, Any]:
        self._check(table, values)
        return _update(self.conn, table, row_id, {**values, "decision_id": self.decision_id})

    def deactivate(self, table: str, row_id: str) -> dict[str, Any]:
        if table not in ("position", "goal"):
            raise ValueError(f"{table} has no active flag; close or supersede it instead")
        return self.update(table, row_id, active=False)

    def state_fact(self, *, client_id: str, stated_key: str, stated_value: Any, stated_on: date,
                   stated_by: str, data_class: Optional[int] = None) -> dict[str, Any]:
        """A new current fact for the key, superseding the current one (dated ``stated_on``)."""
        current = self.conn.execute(
            "SELECT id FROM client_fact WHERE client_id = %s AND stated_key = %s AND superseded_on IS NULL",
            (client_id, stated_key)).fetchone()
        if current is not None:
            self.update("client_fact", current["id"], superseded_on=stated_on)
        values = {"client_id": client_id, "stated_key": stated_key, "stated_value": stated_value,
                  "stated_on": stated_on, "stated_by": stated_by}
        if data_class is not None:
            values["data_class"] = data_class
        return self.insert("client_fact", **values)

    def _link_goal(self, goal_id: str) -> None:
        self.conn.execute("INSERT INTO decision_goal (decision_id, goal_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                          (self.decision_id, goal_id))

    def set_goal_funding(self, goal_id: str, position_id: str, *, active: bool = True) -> None:
        self._link_goal(goal_id)
        self.conn.execute("INSERT INTO goal_funding (goal_id, position_id, active) VALUES (%s, %s, %s) "
                          "ON CONFLICT (goal_id, position_id) DO UPDATE SET active = EXCLUDED.active",
                          (goal_id, position_id, active))

    def set_goal_owner(self, goal_id: str, household_member_id: str, *, active: bool = True) -> None:
        self._link_goal(goal_id)
        self.conn.execute("INSERT INTO goal_owner (goal_id, household_member_id, active) VALUES (%s, %s, %s) "
                          "ON CONFLICT (goal_id, household_member_id) DO UPDATE SET active = EXCLUDED.active",
                          (goal_id, household_member_id, active))


@contextmanager
def plan_change(conn: psycopg.Connection, *, decision: Decision) -> Iterator[PlanChange]:
    """Write the decision and the plan rows in one transaction (C-09).

    The database refuses a plan write whose decision was written in another transaction, so this is a
    convenience, not the guard. Nested inside an open transaction it uses a savepoint; the decision's
    transaction id is the top-level one either way.
    """
    with conn.transaction():
        row = _insert(conn, "decision", {
            "client_id": decision.client_id, "author": decision.author, "author_ref": decision.author_ref,
            "question": decision.question, "options_considered": list(decision.options_considered),
            "choice": decision.choice, "reasoning": decision.reasoning,
            "curator_session_id": decision.curator_session_id, "corrects_id": decision.corrects_id})
        yield PlanChange(conn, row)


def plan_of(conn, client_id: str, *, include_inactive: bool = False) -> dict[str, list[dict[str, Any]]]:
    """The client's plan rows: positions, goals, facts (current), households they belong to."""
    active = "" if include_inactive else " AND active"
    return {
        "positions": conn.execute(f"SELECT * FROM position WHERE client_id = %s{active} ORDER BY created_at, id",
                                  (client_id,)).fetchall(),
        "goals": conn.execute(f"SELECT * FROM goal WHERE client_id = %s{active} ORDER BY created_at, id",
                              (client_id,)).fetchall(),
        "facts": conn.execute("SELECT * FROM client_fact WHERE client_id = %s AND superseded_on IS NULL "
                              "ORDER BY stated_key", (client_id,)).fetchall(),
        "households": conn.execute(
            "SELECT h.* FROM household h WHERE EXISTS (SELECT 1 FROM household_member m "
            "WHERE m.household_id = h.id AND m.client_id = %s) ORDER BY h.created_at, h.id", (client_id,)).fetchall(),
    }


def decisions_of(conn, client_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT * FROM decision WHERE client_id = %s ORDER BY seq", (client_id,)).fetchall()


# ---------------------------------------------------------------------------
# Erasure (R-231): the one path that deletes
# ---------------------------------------------------------------------------

#: Written into a household member row that stays because the household has other client members.
REDACTED = "[gelöscht auf Antrag]"


def erase_client(conn: psycopg.Connection, client_id: str) -> dict[str, int]:
    """Remove one client's material, in one transaction, as the owning role (R-231).

    The setting ``eigentlich.erasure_client`` (SET LOCAL) names the client; every guard in schema.sql lets
    the owner delete that client's rows while it is set, and nothing else. What stays, and why:

    * a household the client shared with another client stays, with the client's member row redacted;
      rows of it that rested on the erased client's decisions are re-attributed to a ``system`` decision
      of the remaining client, written in this transaction (C-09 still holds afterwards);
    * curator sessions keep their audit, with the client reference nulled (the audit is the curator's);
    * content versions the client saved stay (the content is shared), with ``saved_by_ref`` redacted.

    Returns rows removed per table.
    """
    removed: dict[str, int] = {}

    def delete(table: str, where: str, params: Sequence[Any]) -> None:
        cur = conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        if cur.rowcount:
            removed[table] = removed.get(table, 0) + cur.rowcount

    with conn.transaction():
        get_client(conn, client_id)
        conn.execute("SELECT set_config('eigentlich.erasure_client', %s, true)", (client_id,))
        hh = conn.execute(
            "SELECT h.id, (SELECT min(o.client_id) FROM household_member o WHERE o.household_id = h.id "
            "AND o.client_id IS NOT NULL AND o.client_id <> %s) AS other FROM household h WHERE EXISTS "
            "(SELECT 1 FROM household_member m WHERE m.household_id = h.id AND m.client_id = %s)",
            (client_id, client_id)).fetchall()
        solely = [h["id"] for h in hh if h["other"] is None]
        shared = {h["id"]: h["other"] for h in hh if h["other"] is not None}
        mine = "(SELECT id FROM decision WHERE client_id = %s)"

        # Shared households: re-attribute rows written under this client's decisions, then redact.
        for household_id, other in shared.items():
            system = _insert(conn, "decision", {
                "client_id": other, "author": "system", "author_ref": "erasure",
                "question": "Ein Haushaltsmitglied hat die Löschung seiner Daten verlangt.",
                "choice": "Der Haushalt bleibt bestehen; der Eintrag des Mitglieds ist geschwärzt.",
                "options_considered": []})
            conn.execute(f"UPDATE household SET decision_id = %s WHERE id = %s AND decision_id IN {mine}",
                         (system["id"], household_id, client_id))
            conn.execute(f"UPDATE household_member SET decision_id = %s WHERE household_id = %s AND decision_id IN {mine}",
                         (system["id"], household_id, client_id))
            conn.execute("UPDATE household_member SET client_id = NULL, label = %s, decision_id = %s "
                         "WHERE household_id = %s AND client_id = %s", (REDACTED, system["id"], household_id, client_id))

        delete("approval_event", "request_id IN (SELECT id FROM approval_request WHERE client_id = %s)", (client_id,))
        delete("approval_request", "client_id = %s", (client_id,))
        delete("report", "client_id = %s", (client_id,))
        delete("report_request", "client_id = %s", (client_id,))
        delete("thread_message", "thread_id IN (SELECT id FROM thread WHERE client_id = %s)", (client_id,))
        delete("thread", "client_id = %s", (client_id,))
        delete("engine_run", "client_id = %s", (client_id,))
        delete("parameter_set", "client_id = %s", (client_id,))
        conn.execute("UPDATE answer SET superseded_by_id = NULL WHERE client_id = %s AND superseded_by_id IS NOT NULL",
                     (client_id,))
        delete("answer", "client_id = %s", (client_id,))
        delete("submission", "client_id = %s", (client_id,))
        delete("consent", "client_id = %s", (client_id,))
        own_goals = "(SELECT id FROM goal WHERE client_id = %s)"
        own_positions = "(SELECT id FROM position WHERE client_id = %s)"
        solely_members = "(SELECT id FROM household_member WHERE household_id = ANY(%s))"
        delete("goal_funding", f"goal_id IN {own_goals} OR position_id IN {own_positions}", (client_id, client_id))
        delete("goal_owner", f"goal_id IN {own_goals} OR household_member_id IN {solely_members}", (client_id, solely))
        delete("decision_goal", f"goal_id IN {own_goals} OR decision_id IN {mine}", (client_id, client_id))
        delete("decision_position", f"position_id IN {own_positions} OR decision_id IN {mine}", (client_id, client_id))
        delete("decision_client_fact", f"client_fact_id IN (SELECT id FROM client_fact WHERE client_id = %s) "
               f"OR decision_id IN {mine}", (client_id, client_id))
        delete("decision_household_member", f"household_member_id IN {solely_members} OR decision_id IN {mine}",
               (solely, client_id))
        delete("decision_household", f"household_id = ANY(%s) OR decision_id IN {mine}", (solely, client_id))
        delete("goal", "client_id = %s", (client_id,))
        delete("position", "client_id = %s", (client_id,))
        delete("client_fact", "client_id = %s", (client_id,))
        delete("household_member", "household_id = ANY(%s)", (solely,))
        delete("household", "id = ANY(%s)", (solely,))
        conn.execute("UPDATE curator_session SET client_id = NULL WHERE client_id = %s", (client_id,))
        conn.execute("UPDATE content_record SET saved_by_ref = %s WHERE saved_by_kind = 'client' AND saved_by_ref = %s",
                     (REDACTED, client_id))
        # Decisions last, corrections before what they correct.
        while True:
            cur = conn.execute("DELETE FROM decision d WHERE d.client_id = %s AND NOT EXISTS "
                               "(SELECT 1 FROM decision c WHERE c.corrects_id = d.id)", (client_id,))
            if not cur.rowcount:
                break
            removed["decision"] = removed.get("decision", 0) + cur.rowcount
        delete("client", "id = %s", (client_id,))
        conn.execute("SELECT set_config('eigentlich.erasure_client', '', true)")
    return removed


def dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
