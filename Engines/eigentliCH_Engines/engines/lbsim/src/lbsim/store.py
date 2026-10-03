"""Persistence in PostgreSQL (schema and role ``lbsim``, spec 3.10). psycopg, no ORM, no migrations.

The store knows nothing about the model. It keeps calibrations (append-only, by version), artefacts (append-only,
by content hash, unique on idempotency key), runs (a state machine: the synchronous outlook runs and the queue of
plan runs) and run events (append-only, one per transition). Payloads are the canonical JSON of their contract,
so a round trip is exact.

The plan queue: a worker claims the highest-priority, oldest queued plan run with ``SELECT ... FOR UPDATE SKIP
LOCKED``, so any number of workers share one queue without handing a run out twice. Timestamps are fixed-width
ISO-8601 UTC text (milliseconds), so they order as text.

One connection per unit of work, opened on demand and closed afterwards.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import resources
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row

from .settings import DatabaseConfig

PRIORITY = {"curator": 2, "client": 1, "system": 0}


class StoreError(RuntimeError):
    """The store is unreachable or not initialised. The message says what to run."""


class StoreConflict(ValueError):
    """A write would change something that is append-only."""


def utc_now(offset_s: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat(timespec="milliseconds")


def parse_time(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


def dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class Store:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    def connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.config.conninfo(), row_factory=dict_row)
        except psycopg.OperationalError as exc:
            raise StoreError(
                f"cannot reach PostgreSQL at {self.config.redacted_url()}: {exc}. Start it with `docker compose up "
                "-d` in Projects\\PostgreSQL; the lbsim role and schema are provisioned by "
                "Instruments/store/provision.py.") from exc
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
        """Create the schema's tables. Idempotent."""
        ddl = resources.files("lbsim").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.schema}")
            conn.execute(f"SET search_path TO {self.config.schema}, public")
            conn.execute(ddl)

    def drop_schema(self) -> None:
        with self.session() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {self.config.schema} CASCADE")


# -- calibrations -----------------------------------------------------------------------------------------

def put_calibration(conn, *, version: str, calibration_hash: str, parent_version: Optional[str],
                    payload_json: str) -> bool:
    row = conn.execute("SELECT calibration_hash FROM calibration WHERE version = %s", (version,)).fetchone()
    if row is not None:
        if row["calibration_hash"] != calibration_hash:
            raise StoreConflict(f"calibration {version} already exists with different parameters")
        return False
    conn.execute("INSERT INTO calibration (version, calibration_hash, parent_version, created_at, payload_json) "
                 "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
                 (version, calibration_hash, parent_version, utc_now(), payload_json))
    return True


def get_calibration(conn, version: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM calibration WHERE version = %s", (version,)).fetchone()
    return None if row is None else row["payload_json"]


def list_calibrations(conn) -> list[dict[str, Any]]:
    return conn.execute("SELECT version, calibration_hash, parent_version, created_at FROM calibration "
                        "ORDER BY created_at, version").fetchall()


# -- artefacts --------------------------------------------------------------------------------------------

def put_artefact(conn, *, artefact_id: str, kind: str, client_ref: str, life_balance_sheet_id: str,
                 idempotency_key: str, contract_version: str, payload_json: str) -> bool:
    """Insert an artefact. A concurrent identical run writes the identical row, so a conflict is not an error."""
    cur = conn.execute(
        "INSERT INTO artefact (artefact_id, kind, client_ref, life_balance_sheet_id, idempotency_key, "
        "contract_version, created_at, payload_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (artefact_id, kind, client_ref, life_balance_sheet_id, idempotency_key, contract_version, utc_now(),
         payload_json))
    return cur.rowcount == 1


def get_artefact(conn, artefact_id: str) -> Optional[dict[str, Any]]:
    return conn.execute("SELECT artefact_id, kind, client_ref, life_balance_sheet_id, idempotency_key, created_at, "
                        "payload_json FROM artefact WHERE artefact_id = %s", (artefact_id,)).fetchone()


def artefact_by_key(conn, idempotency_key: str) -> Optional[dict[str, Any]]:
    return conn.execute("SELECT artefact_id, kind, payload_json FROM artefact WHERE idempotency_key = %s",
                        (idempotency_key,)).fetchone()


def latest_sheet_for_client(conn, client_ref: str) -> Optional[str]:
    """The sheet of the client's newest outlook run (the newest sheet lbsim was asked about)."""
    row = conn.execute("SELECT life_balance_sheet_id FROM run WHERE client_ref = %s AND kind = 'outlook' "
                       "ORDER BY queued_at DESC, run_id DESC LIMIT 1", (client_ref,)).fetchone()
    return None if row is None else row["life_balance_sheet_id"]


def newest_outlook_per_client(conn, limit: int = 30) -> list[dict[str, Any]]:
    """The test bench's picker: each client's newest succeeded outlook run, newest first."""
    return conn.execute(
        "SELECT * FROM (SELECT DISTINCT ON (client_ref) client_ref, life_balance_sheet_id, request_json, "
        "artefact_ids_json, queued_at FROM run WHERE kind = 'outlook' AND status = 'succeeded' "
        "ORDER BY client_ref, queued_at DESC, run_id DESC) AS newest ORDER BY queued_at DESC LIMIT %s",
        (limit,)).fetchall()


# -- runs -------------------------------------------------------------------------------------------------

_RUN_COLUMNS = ("run_id, kind, status, failure_kind, idempotency_key, client_ref, life_balance_sheet_id, "
                "request_json, requested_by_kind, requested_by_ref, priority, budget_s, queued_at, started_at, "
                "finished_at, heartbeat_at, wall_clock_ms, attempts, worker, cancel_requested, progress_json, "
                "artefact_ids_json, error")


def event(conn, run_id: str, name: str, detail: Optional[dict[str, Any]] = None) -> None:
    conn.execute("INSERT INTO run_event (run_id, at, event, detail_json) VALUES (%s, %s, %s, %s)",
                 (run_id, utc_now(), name, dumps(detail or {})))


def insert_run(conn, *, run_id: str, kind: str, status: str, idempotency_key: str, client_ref: str,
               life_balance_sheet_id: str, request: dict[str, Any], requested_by_kind: str,
               requested_by_ref: Optional[str], budget_s: Optional[float], queued_at: Optional[str] = None,
               started_at: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO run (run_id, kind, status, idempotency_key, client_ref, life_balance_sheet_id, request_json, "
        "requested_by_kind, requested_by_ref, priority, budget_s, queued_at, started_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (run_id, kind, status, idempotency_key, client_ref, life_balance_sheet_id, dumps(request), requested_by_kind,
         requested_by_ref, PRIORITY[requested_by_kind], budget_s, queued_at or utc_now(), started_at))
    event(conn, run_id, status, {"kind": kind, "requested_by": requested_by_kind})


def finish_run(conn, *, run_id: str, status: str, failure_kind: Optional[str] = None,
               artefact_ids: tuple[str, ...] = (), error: Optional[str] = None,
               wall_clock_ms: Optional[float] = None, only_if_status: Optional[tuple[str, ...]] = None) -> bool:
    """Finish a run. ``only_if_status``: only from one of these states (a run finished elsewhere stays as it is)."""
    sql = ("UPDATE run SET status = %s, failure_kind = %s, finished_at = %s, artefact_ids_json = %s, error = %s, "
           "wall_clock_ms = COALESCE(%s, wall_clock_ms) WHERE run_id = %s")
    args: list[Any] = [status, failure_kind, utc_now(), dumps(list(artefact_ids)), error, wall_clock_ms, run_id]
    if only_if_status:
        sql += " AND status = ANY(%s)"
        args.append(list(only_if_status))
    cur = conn.execute(sql, args)
    if cur.rowcount:
        event(conn, run_id, status if failure_kind is None else f"{status}:{failure_kind}",
              {"error": error} if error else {})
    return cur.rowcount == 1


def get_run(conn, run_id: str) -> Optional[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE run_id = %s", (run_id,)).fetchone()


def list_runs(conn, *, client_ref: Optional[str] = None, kind: Optional[str] = None, status: Optional[str] = None,
              limit: int = 100) -> list[dict[str, Any]]:
    where, args = [], []
    for col, val in (("client_ref", client_ref), ("kind", kind), ("status", status)):
        if val is not None:
            where.append(f"{col} = %s")
            args.append(val)
    sql = f"SELECT {_RUN_COLUMNS} FROM run" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY queued_at DESC, run_id DESC LIMIT %s"
    return conn.execute(sql, [*args, limit]).fetchall()


def runs_for_key(conn, idempotency_key: str, kind: str) -> list[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE idempotency_key = %s AND kind = %s "
                        "ORDER BY queued_at DESC, run_id DESC", (idempotency_key, kind)).fetchall()


def plan_runs_for_sheet(conn, life_balance_sheet_id: str) -> list[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE life_balance_sheet_id = %s AND kind = 'plan' "
                        "ORDER BY queued_at DESC, run_id DESC", (life_balance_sheet_id,)).fetchall()


def outlook_runs_for_sheet(conn, life_balance_sheet_id: str) -> list[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE life_balance_sheet_id = %s AND kind = 'outlook' "
                        "ORDER BY queued_at DESC, run_id DESC", (life_balance_sheet_id,)).fetchall()


def supersede(conn, *, client_ref: str, keep_key: Optional[str]) -> list[str]:
    """A newer outlook run for the client: every queued plan run on another key fails ``superseded`` now, and every
    running one is asked to stop at its next checkpoint. Returns the run ids touched."""
    touched = []
    rows = conn.execute("SELECT run_id, status, idempotency_key FROM run WHERE client_ref = %s AND kind = 'plan' "
                        "AND status IN ('queued', 'running') FOR UPDATE", (client_ref,)).fetchall()
    for r in rows:
        if keep_key is not None and r["idempotency_key"] == keep_key:
            continue
        if r["status"] == "queued":
            finish_run(conn, run_id=r["run_id"], status="failed", failure_kind="superseded",
                       error="A newer Life Balance Sheet or allocation for this client replaced this plan calculation "
                             "before it started.", only_if_status=("queued",))
        else:
            conn.execute("UPDATE run SET cancel_requested = 'superseded' WHERE run_id = %s AND status = 'running'",
                         (r["run_id"],))
            event(conn, r["run_id"], "supersede_requested")
        touched.append(r["run_id"])
    return touched


def request_cancel(conn, run_id: str) -> Optional[str]:
    """Cancel a plan run: a queued one now, a running one at its next checkpoint. Returns the run's status after."""
    row = conn.execute("SELECT status FROM run WHERE run_id = %s FOR UPDATE", (run_id,)).fetchone()
    if row is None:
        return None
    if row["status"] == "queued":
        finish_run(conn, run_id=run_id, status="failed", failure_kind="cancelled",
                   error="Cancelled before it started.", only_if_status=("queued",))
        return "failed"
    if row["status"] == "running":
        conn.execute("UPDATE run SET cancel_requested = 'cancelled' WHERE run_id = %s", (run_id,))
        event(conn, run_id, "cancel_requested")
    return row["status"]


def claim_next(conn, worker: str) -> Optional[dict[str, Any]]:
    """The next plan run for this worker: curator first, then the oldest. ``FOR UPDATE SKIP LOCKED``."""
    row = conn.execute(
        "SELECT run_id FROM run WHERE kind = 'plan' AND status = 'queued' "
        "ORDER BY priority DESC, queued_at, run_id LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
    if row is None:
        return None
    now = utc_now()
    conn.execute("UPDATE run SET status = 'running', started_at = %s, heartbeat_at = %s, worker = %s, "
                 "attempts = attempts + 1, cancel_requested = NULL WHERE run_id = %s",
                 (now, now, worker, row["run_id"]))
    event(conn, row["run_id"], "running", {"worker": worker})
    return get_run(conn, row["run_id"])


def heartbeat(conn, run_id: str, worker: str) -> Optional[dict[str, Any]]:
    """Beat, and read back whether the run was asked to stop or taken from this worker."""
    conn.execute("UPDATE run SET heartbeat_at = %s WHERE run_id = %s AND status = 'running' AND worker = %s",
                 (utc_now(), run_id, worker))
    return conn.execute("SELECT status, worker, cancel_requested FROM run WHERE run_id = %s", (run_id,)).fetchone()


def set_progress(conn, run_id: str, progress: dict[str, Any]) -> None:
    conn.execute("UPDATE run SET progress_json = %s WHERE run_id = %s AND status = 'running'",
                 (dumps(progress), run_id))


def requeue_stale(conn, *, stale_after_s: float, max_attempts: int) -> list[tuple[str, str]]:
    """Running plan runs whose heartbeat stopped: back to the queue while they have attempts left, else failed.
    Returns ``(run_id, new status)`` pairs."""
    threshold = utc_now(-stale_after_s)
    rows = conn.execute("SELECT run_id, attempts FROM run WHERE kind = 'plan' AND status = 'running' AND "
                        "(heartbeat_at IS NULL OR heartbeat_at < %s) FOR UPDATE SKIP LOCKED", (threshold,)).fetchall()
    out = []
    for r in rows:
        if r["attempts"] < max_attempts:
            conn.execute("UPDATE run SET status = 'queued', worker = NULL, started_at = NULL, heartbeat_at = NULL, "
                         "progress_json = NULL WHERE run_id = %s", (r["run_id"],))
            event(conn, r["run_id"], "requeued", {"attempts": r["attempts"], "reason": "heartbeat stopped"})
            out.append((r["run_id"], "queued"))
        else:
            finish_run(conn, run_id=r["run_id"], status="failed", failure_kind="solver",
                       error=f"The worker stopped {r['attempts']} times while calculating this plan; it is not tried "
                             "again.", only_if_status=("running",))
            out.append((r["run_id"], "failed"))
    return out


def events_for(conn, run_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT event_id, at, event, detail_json FROM run_event WHERE run_id = %s ORDER BY event_id",
                        (run_id,)).fetchall()


def table_counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in ("calibration", "artefact", "run", "run_event")}
