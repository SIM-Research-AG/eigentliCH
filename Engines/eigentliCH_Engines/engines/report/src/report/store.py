"""Report persistence in PostgreSQL. psycopg, no ORM, no migrations.

The store knows nothing about the model. It keeps three things: calibrations (append-only, by version),
reports (append-only; one *complete* report per idempotency key, any number of incomplete ones) and runs
(one row per attempt). Payloads are stored as the canonical JSON of their contract, so a round trip is exact.

One connection per request, opened on demand and closed afterwards. Nothing is shared between threads.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row

from .settings import DatabaseConfig

TABLES = ("calibration", "artefact", "run")


#: The advisory lock ``initialise()`` holds while it applies ``schema.sql`` (one key per engine).
SCHEMA_LOCK = "report.schema"


class StoreError(RuntimeError):
    """The store is unreachable or not initialised. The message says what to run."""


class StoreConflict(ValueError):
    """A write would change something that is append-only."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    def connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.config.conninfo(), row_factory=dict_row)
        except psycopg.OperationalError as exc:
            raise StoreError(
                f"cannot reach PostgreSQL at {self.config.redacted_url()}: {exc}. "
                "Start it with `docker compose up -d` in Projects\\PostgreSQL."
            ) from exc
        conn.execute(f"SET search_path TO {self.config.schema}, public")
        conn.commit()
        return conn

    @contextmanager
    def session(self) -> Iterator[psycopg.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialise(self) -> None:
        ddl = resources.files("report").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            # Several processes start together (the API and its workers, or a restart of the container).
            # The lock queues them, so two never apply the DDL at once: without it PostgreSQL can deadlock on
            # pg_proc. Transaction-level, so the commit or rollback at the end of the session releases it.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SCHEMA_LOCK,))
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.schema}")
            conn.execute(f"SET search_path TO {self.config.schema}, public")
            conn.execute(ddl)

    def drop_schema(self) -> None:
        with self.session() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {self.config.schema} CASCADE")


# -- calibrations -------------------------------------------------------------

def put_calibration(conn: psycopg.Connection, *, version: str, calibration_hash: str,
                    parent_version: Optional[str], payload_json: str) -> bool:
    row = conn.execute("SELECT calibration_hash FROM calibration WHERE version = %s", (version,)).fetchone()
    if row is not None:
        if row["calibration_hash"] != calibration_hash:
            raise StoreConflict(f"calibration {version} already exists with different parameters")
        return False
    conn.execute(
        "INSERT INTO calibration (version, calibration_hash, parent_version, created_at, payload_json) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
        (version, calibration_hash, parent_version, utc_now(), payload_json))
    return True


def get_calibration(conn: psycopg.Connection, version: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM calibration WHERE version = %s", (version,)).fetchone()
    return None if row is None else row["payload_json"]


def list_calibrations(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute("SELECT version, calibration_hash, parent_version, created_at FROM calibration "
                        "ORDER BY created_at, version").fetchall()


# -- reports --------------------------------------------------------------------

def put_artefact(conn: psycopg.Connection, *, artefact_id: str, idempotency_key: str, complete: bool,
                 client_ref: str, kind: str, language: str, previous_report_id: Optional[str],
                 contract_version: str, payload_json: str) -> str:
    """Insert a report and return the id stored for it.

    A complete report is unique per key: if another process stored one first, that one is returned and this
    one is not stored (REP-08). An identical payload (same id) is not a conflict. An incomplete report is
    always kept, for the record."""
    row = conn.execute(
        "INSERT INTO artefact (artefact_id, idempotency_key, complete, client_ref, kind, language, "
        "previous_report_id, contract_version, created_at, payload_json) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING artefact_id",
        (artefact_id, idempotency_key, complete, client_ref, kind, language, previous_report_id, contract_version,
         utc_now(), payload_json)).fetchone()
    if row is not None:
        return row["artefact_id"]
    if conn.execute("SELECT 1 FROM artefact WHERE artefact_id = %s", (artefact_id,)).fetchone():
        return artefact_id
    existing = complete_for_key(conn, idempotency_key)
    if existing is None:
        raise StoreConflict(f"report {artefact_id} could not be stored")
    return existing


def complete_for_key(conn: psycopg.Connection, idempotency_key: str) -> Optional[str]:
    row = conn.execute("SELECT artefact_id FROM artefact WHERE idempotency_key = %s AND complete",
                       (idempotency_key,)).fetchone()
    return None if row is None else row["artefact_id"]


def get_artefact(conn: psycopg.Connection, artefact_id: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM artefact WHERE artefact_id = %s", (artefact_id,)).fetchone()
    return None if row is None else row["payload_json"]


def list_reports(conn: psycopg.Connection, client_ref: Optional[str], limit: int) -> list[dict[str, Any]]:
    sql = ("SELECT artefact_id, client_ref, kind, language, complete, previous_report_id, created_at "
           "FROM artefact")
    args: tuple[Any, ...] = ()
    if client_ref:
        sql += " WHERE client_ref = %s"
        args = (client_ref,)
    return conn.execute(sql + " ORDER BY created_at DESC, artefact_id LIMIT %s", args + (limit,)).fetchall()


# -- runs -------------------------------------------------------------------------

_RUN_COLUMNS = ("run_id, idempotency_key, status, started_at, finished_at, wall_clock_ms, request_json, "
                "artefact_id, warnings_json, provenance_json, error")


def insert_run(conn: psycopg.Connection, *, run_id: str, idempotency_key: str, status: str, started_at: str,
               request_json: str) -> None:
    conn.execute("INSERT INTO run (run_id, idempotency_key, status, started_at, request_json) "
                 "VALUES (%s, %s, %s, %s, %s)", (run_id, idempotency_key, status, started_at, request_json))


def finish_run(conn: psycopg.Connection, *, run_id: str, status: str, finished_at: str, wall_clock_ms: float,
               artefact_id: Optional[str], warnings_json: str, provenance_json: Optional[str],
               error: Optional[str]) -> None:
    conn.execute("UPDATE run SET status = %s, finished_at = %s, wall_clock_ms = %s, artefact_id = %s, "
                 "warnings_json = %s, provenance_json = %s, error = %s WHERE run_id = %s",
                 (status, finished_at, wall_clock_ms, artefact_id, warnings_json, provenance_json, error, run_id))


def get_run(conn: psycopg.Connection, run_id: str) -> Optional[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE run_id = %s", (run_id,)).fetchone()


def complete_run_for_key(conn: psycopg.Connection, idempotency_key: str) -> Optional[dict[str, Any]]:
    """The first successful run for a key that published a complete report: the one a repeat is answered
    with. A run that published a report without its prose is not a cache hit (REP-07)."""
    return conn.execute(
        f"SELECT r.{_RUN_COLUMNS.replace(', ', ', r.')} FROM run r JOIN artefact a ON a.artefact_id = r.artefact_id "
        "WHERE r.idempotency_key = %s AND r.status = 'succeeded' AND a.complete "
        "ORDER BY r.started_at, r.run_id LIMIT 1", (idempotency_key,)).fetchone()


def list_runs(conn: psycopg.Connection, limit: int) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT r.run_id, r.status, r.started_at, r.finished_at, r.wall_clock_ms, r.artefact_id, a.client_ref, "
        "a.kind, a.language, a.complete, r.error, r.request_json "
        "FROM run r LEFT JOIN artefact a ON a.artefact_id = r.artefact_id "
        "ORDER BY r.started_at DESC, r.run_id LIMIT %s", (limit,)).fetchall()


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in TABLES}


def dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
