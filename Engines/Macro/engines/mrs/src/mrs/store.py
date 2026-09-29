"""Artefact persistence in PostgreSQL. psycopg, no ORM, no migrations.

The store knows nothing about the model. It keeps three things: calibrations (append-only,
by version), artefacts (append-only, by content hash, unique on idempotency key) and runs
(one row per attempt), plus the recorded MATLAB output it is reconciled against. Payloads are stored as the canonical JSON of their contract, so a
round trip is exact: Python writes the shortest repr of a float and reads the same float
back.

One connection per request, opened on demand and closed afterwards. Nothing is shared
between threads, so the concurrent opening burst of the test bench is safe.
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


class StoreError(RuntimeError):
    """The store is unreachable or not initialised. The message says what to run."""


class StoreConflict(ValueError):
    """A write would change something that is append-only."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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
                "Start it with `docker compose up -d` in Projects\\PostgreSQL, and create "
                "the database once with `python -m mrs init-db`."
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

    # -- lifecycle ---------------------------------------------------------

    def create_database(self) -> bool:
        """CREATE DATABASE if it does not exist. Returns True if it was created."""
        maintenance = self.config.conninfo(dbname=self.config.maintenance_dbname)
        with psycopg.connect(maintenance, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                                  (self.config.dbname,)).fetchone()
            if exists:
                return False
            conn.execute(f'CREATE DATABASE "{self.config.dbname}"')
            return True

    def initialise(self) -> None:
        """Create the schema and tables. Idempotent."""
        ddl = resources.files("mrs").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.schema}")
            conn.execute(f"SET search_path TO {self.config.schema}, public")
            conn.execute(ddl)

    def stale(self) -> Optional[str]:
        """Why the tables in the schema predate this engine version, or ``None``.

        v0.1.0 stored Regime artefacts with a ``regime_id`` column; CREATE TABLE IF NOT
        EXISTS cannot change an existing table, so such a store must be rebuilt.
        """
        with self.session() as conn:
            row = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = %s "
                "AND table_name = 'artefact' AND column_name = 'regime_id'",
                (self.config.schema,)).fetchone()
        if row is not None:
            return (f"schema {self.config.schema} holds the v0.1.0 tables (artefact.regime_id). "
                    "Rebuild it with `python -m mrs init-db --rebuild`.")
        return None

    def rebuild(self) -> list[str]:
        """Drop this engine's tables (and its trigger function) in its own schema, then
        create them afresh. The schema itself, its owner and its grants are left alone."""
        dropped = []
        with self.session() as conn:
            for table in _TABLES:
                exists = conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = %s "
                    "AND table_name = %s", (self.config.schema, table)).fetchone()
                if exists:
                    conn.execute(f"DROP TABLE {self.config.schema}.{table} CASCADE")
                    dropped.append(table)
            conn.execute(f"DROP FUNCTION IF EXISTS {self.config.schema}.refuse_change() CASCADE")
        self.initialise()
        return dropped


#: Every table this engine owns, children first.
_TABLES = ("run", "artefact", "calibration", "reference_signal", "reference_source")


# ---------------------------------------------------------------------------
# Calibrations
# ---------------------------------------------------------------------------

def put_calibration(conn: psycopg.Connection, *, version: str, calibration_hash: str,
                    parent_version: Optional[str], payload_json: str) -> bool:
    """Insert a calibration. True if new, False if the identical version already exists.

    Raises :class:`StoreConflict` if the version exists with different content.
    """
    row = conn.execute("SELECT calibration_hash FROM calibration WHERE version = %s",
                       (version,)).fetchone()
    if row is not None:
        if row["calibration_hash"] != calibration_hash:
            raise StoreConflict(f"calibration {version} already exists with different parameters")
        return False
    conn.execute(
        "INSERT INTO calibration (version, calibration_hash, parent_version, created_at, payload_json) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
        (version, calibration_hash, parent_version, utc_now(), payload_json),
    )
    return True


def get_calibration(conn: psycopg.Connection, version: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM calibration WHERE version = %s",
                       (version,)).fetchone()
    return None if row is None else row["payload_json"]


def list_calibrations(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT version, calibration_hash, parent_version, created_at FROM calibration "
        "ORDER BY created_at, version"
    ).fetchall()


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------

def put_artefact(conn: psycopg.Connection, *, artefact_id: str, idempotency_key: str,
                 snapshot_id: str, calibration_version: str, contract_version: str,
                 payload_json: str) -> None:
    """Insert an artefact. A concurrent identical run writes the identical row, so a
    conflict is not an error."""
    conn.execute(
        "INSERT INTO artefact (artefact_id, idempotency_key, snapshot_id, calibration_version, "
        "contract_version, created_at, payload_json) VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (artefact_id, idempotency_key, snapshot_id, calibration_version, contract_version,
         utc_now(), payload_json),
    )


def get_artefact(conn: psycopg.Connection, artefact_id: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM artefact WHERE artefact_id = %s",
                       (artefact_id,)).fetchone()
    return None if row is None else row["payload_json"]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

_RUN_COLUMNS = ("run_id, idempotency_key, status, snapshot_id, calibration_version, started_at, "
                "finished_at, wall_clock_ms, request_json, artefact_id, warnings_json, "
                "coverage_json, provenance_json, error")


def insert_run(conn: psycopg.Connection, *, run_id: str, idempotency_key: str, status: str,
               snapshot_id: str, calibration_version: str, started_at: str,
               request_json: str) -> None:
    conn.execute(
        "INSERT INTO run (run_id, idempotency_key, status, snapshot_id, calibration_version, "
        "started_at, request_json) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (run_id, idempotency_key, status, snapshot_id, calibration_version, started_at,
         request_json),
    )


def finish_run(conn: psycopg.Connection, *, run_id: str, status: str, finished_at: str,
               wall_clock_ms: float, artefact_id: Optional[str], warnings_json: str,
               coverage_json: Optional[str], provenance_json: Optional[str],
               error: Optional[str]) -> None:
    conn.execute(
        "UPDATE run SET status = %s, finished_at = %s, wall_clock_ms = %s, artefact_id = %s, "
        "warnings_json = %s, coverage_json = %s, provenance_json = %s, error = %s "
        "WHERE run_id = %s",
        (status, finished_at, wall_clock_ms, artefact_id, warnings_json, coverage_json,
         provenance_json, error, run_id),
    )


def get_run(conn: psycopg.Connection, run_id: str) -> Optional[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN_COLUMNS} FROM run WHERE run_id = %s", (run_id,)).fetchone()


def succeeded_run_for_key(conn: psycopg.Connection, idempotency_key: str) -> Optional[dict[str, Any]]:
    """The first successful run for a key: the one a cached request is answered with."""
    return conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM run WHERE idempotency_key = %s AND status = 'succeeded' "
        "ORDER BY started_at, run_id LIMIT 1",
        (idempotency_key,),
    ).fetchone()


def list_runs(conn: psycopg.Connection, limit: int) -> list[dict[str, Any]]:
    """The most recent runs, newest first (insertion order)."""
    return conn.execute(
        "SELECT run_id, status, artefact_id, snapshot_id, calibration_version, finished_at "
        "FROM run ORDER BY seq DESC LIMIT %s", (limit,)).fetchall()


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in ("calibration", "artefact", "run", "reference_source", "reference_signal")}


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def put_reference_signal(conn: psycopg.Connection, *, manifest: dict[str, Any], rows: list,
                         months: int) -> tuple[str, bool]:
    """Insert a signal export. Returns (source_id, created). Loading the same file twice is a
    no-op; a different file is a new source."""
    source_id = "REF-" + manifest["sha256"][:16]
    if conn.execute("SELECT 1 FROM reference_source WHERE sha256 = %s",
                    (manifest["sha256"],)).fetchone():
        return source_id, False
    conn.execute(
        "INSERT INTO reference_source (source_id, kind, url, file_name, sha256, byte_size, "
        "produced_by, optimism, pairs_with, pairs_with_sha256, first_date, months, loaded_at, note) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (source_id, manifest["kind"], manifest["url"], manifest["file_name"], manifest["sha256"],
         manifest["byte_size"], manifest["produced_by"], manifest["optimism"],
         manifest["pairs_with"], manifest["pairs_with_sha256"], min(r.date for r in rows),
         months, utc_now(), manifest.get("note", "")),
    )
    with conn.cursor() as cur:
        with cur.copy("COPY reference_signal (source_id, segment, economy, matlab_name, is_blend, "
                      "month_index, date, probs) FROM STDIN") as copy:
            for r in rows:
                copy.write_row((source_id, r.segment, r.economy, r.matlab_name, r.is_blend,
                                r.month_index, r.date, list(r.probs)))
    return source_id, True
