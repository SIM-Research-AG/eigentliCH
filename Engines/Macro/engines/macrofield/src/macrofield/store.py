"""Persistence in PostgreSQL. psycopg, no ORM, no migrations.

The store knows nothing about the model. It keeps the static data (snapshots, their source
files, observations), calibrations, artefacts and runs. Everything but the run log is
append-only, enforced by triggers in schema.sql. Payloads are the canonical JSON of their
contract, so a round trip is exact.

One connection per unit of work, opened on demand and closed afterwards; nothing is shared
between threads. Same shape as the ``honi`` engine's store.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterable, Iterator, Optional

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

    def connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.config.conninfo(), row_factory=dict_row)
        except psycopg.OperationalError as exc:
            raise StoreError(
                f"cannot reach PostgreSQL at {self.config.redacted_url()}: {exc}. Start it with "
                "`docker compose up -d` in Projects\\PostgreSQL, and create the database once "
                "with `python -m macrofield init-db`."
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
        ddl = resources.files("macrofield").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.schema}")
            conn.execute(f"SET search_path TO {self.config.schema}, public")
            conn.execute(ddl)
            put_series_registry(conn)

    def drop_schema(self) -> None:
        with self.session() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {self.config.schema} CASCADE")


def put_series_registry(conn: psycopg.Connection) -> None:
    """Publish ``sources.CATALOGUE`` as the ``series_registry`` table (the code is the definition)."""
    from .sources import CATALOGUE

    now = utc_now()
    ids = [s.series_id for s in CATALOGUE]
    for s in CATALOGUE:
        conn.execute(
            "INSERT INTO series_registry (series_id, provider, code, description, units, frequency, "
            "model_role, lead_lag, scale_critical, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (series_id) DO UPDATE SET provider = EXCLUDED.provider, code = EXCLUDED.code, "
            "description = EXCLUDED.description, units = EXCLUDED.units, frequency = EXCLUDED.frequency, "
            "model_role = EXCLUDED.model_role, lead_lag = EXCLUDED.lead_lag, "
            "scale_critical = EXCLUDED.scale_critical, updated_at = EXCLUDED.updated_at "
            "WHERE (series_registry.provider, series_registry.code, series_registry.description, "
            "series_registry.units, series_registry.frequency, series_registry.model_role, "
            "series_registry.lead_lag, series_registry.scale_critical) IS DISTINCT FROM "
            "(EXCLUDED.provider, EXCLUDED.code, EXCLUDED.description, EXCLUDED.units, EXCLUDED.frequency, "
            "EXCLUDED.model_role, EXCLUDED.lead_lag, EXCLUDED.scale_critical)",
            (s.series_id, s.source, s.identifier, s.description, s.units, s.native_frequency, s.index_block,
             s.leading_concurrent_lagging, s.scale_critical, now))
    conn.execute("DELETE FROM series_registry WHERE NOT (series_id = ANY(%s))", (ids,))


# ---------------------------------------------------------------------------
# Snapshots and observations
# ---------------------------------------------------------------------------

def snapshot_exists(conn: psycopg.Connection, snapshot_id: str) -> bool:
    return conn.execute("SELECT 1 FROM snapshot WHERE snapshot_id = %s",
                        (snapshot_id,)).fetchone() is not None


def put_snapshot(conn: psycopg.Connection, *, snapshot_id: str, frozen_on: str,
                 manifest_json: str, files: Iterable[dict[str, Any]],
                 observations: Iterable[tuple[str, str, int, Optional[float], str]]) -> int:
    """Write a snapshot, its files and its observations in the caller's transaction.

    ``observations`` are (series_id, area, year, value, source_path). Returns the row count.
    """
    conn.execute("INSERT INTO snapshot (snapshot_id, frozen_on, loaded_at, manifest_json) "
                 "VALUES (%s, %s, %s, %s)", (snapshot_id, frozen_on, utc_now(), manifest_json))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO source_file (snapshot_id, path, sha256, bytes, url, retrieved_on, origin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(snapshot_id, f["path"], f["sha256"], f["bytes"], f["url"], f["retrieved_on"],
              f["origin"]) for f in files],
        )
    count = 0
    with conn.cursor().copy(
        "COPY observation (snapshot_id, series_id, area, year, value, source_path) FROM STDIN"
    ) as copy:
        for series_id, area, year, value, path in observations:
            copy.write_row((snapshot_id, series_id, area, year, value, path))
            count += 1
    return count


def list_snapshots(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT s.snapshot_id, s.frozen_on, s.loaded_at, "
        "(SELECT count(*) FROM source_file f WHERE f.snapshot_id = s.snapshot_id) AS files, "
        "(SELECT count(*) FROM observation o WHERE o.snapshot_id = s.snapshot_id) AS observations "
        "FROM snapshot s ORDER BY s.loaded_at, s.snapshot_id"
    ).fetchall()


def get_snapshot(conn: psycopg.Connection, snapshot_id: str) -> Optional[dict[str, Any]]:
    return conn.execute("SELECT snapshot_id, frozen_on, loaded_at FROM snapshot "
                        "WHERE snapshot_id = %s", (snapshot_id,)).fetchone()


def snapshot_files(conn: psycopg.Connection, snapshot_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT path, sha256, bytes, url, retrieved_on, origin FROM source_file "
                        "WHERE snapshot_id = %s ORDER BY path", (snapshot_id,)).fetchall()


def observations(conn: psycopg.Connection, snapshot_id: str,
                 wanted: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[int, Optional[float]]]:
    """``{(series_id, area): {year: value}}`` for the requested pairs that exist."""
    pairs = sorted(set(wanted))
    if not pairs:
        return {}
    rows = conn.execute(
        "SELECT o.series_id, o.area, o.year, o.value FROM observation o "
        "JOIN unnest(%s::text[], %s::text[]) AS w(series_id, area) "
        "ON o.series_id = w.series_id AND o.area = w.area "
        "WHERE o.snapshot_id = %s ORDER BY o.series_id, o.area, o.year",
        ([p[0] for p in pairs], [p[1] for p in pairs], snapshot_id),
    ).fetchall()
    out: dict[tuple[str, str], dict[int, Optional[float]]] = {}
    for r in rows:
        out.setdefault((r["series_id"], r["area"]), {})[r["year"]] = r["value"]
    return out


def present_series(conn: psycopg.Connection, snapshot_id: str) -> list[tuple[str, str]]:
    """(series_id, area) pairs with at least one published value in the snapshot."""
    rows = conn.execute("SELECT DISTINCT series_id, area FROM observation "
                        "WHERE snapshot_id = %s AND value IS NOT NULL", (snapshot_id,)).fetchall()
    return [(r["series_id"], r["area"]) for r in rows]


# ---------------------------------------------------------------------------
# Calibrations
# ---------------------------------------------------------------------------

def put_calibration(conn: psycopg.Connection, *, version: str, calibration_hash: str,
                    parent_version: Optional[str], payload_json: str) -> bool:
    """True if new, False if the identical version exists. StoreConflict if it differs."""
    row = conn.execute("SELECT calibration_hash FROM calibration WHERE version = %s",
                       (version,)).fetchone()
    if row is not None:
        if row["calibration_hash"] != calibration_hash:
            raise StoreConflict(f"calibration {version} already exists with different parameters")
        return False
    conn.execute(
        "INSERT INTO calibration (version, calibration_hash, parent_version, created_at, "
        "payload_json) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
        (version, calibration_hash, parent_version, utc_now(), payload_json),
    )
    return True


def get_calibration(conn: psycopg.Connection, version: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM calibration WHERE version = %s",
                       (version,)).fetchone()
    return None if row is None else row["payload_json"]


def list_calibrations(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute("SELECT version, calibration_hash, parent_version, created_at "
                        "FROM calibration ORDER BY created_at, version").fetchall()


# ---------------------------------------------------------------------------
# Artefacts and runs
# ---------------------------------------------------------------------------

def put_artefact(conn: psycopg.Connection, *, artefact_id: str, idempotency_key: str,
                 contract_version: str, payload_json: str) -> None:
    conn.execute(
        "INSERT INTO artefact (artefact_id, idempotency_key, contract_version, created_at, "
        "payload_json) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (artefact_id, idempotency_key, contract_version, utc_now(), payload_json),
    )


def get_artefact(conn: psycopg.Connection, artefact_id: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM artefact WHERE artefact_id = %s",
                       (artefact_id,)).fetchone()
    return None if row is None else row["payload_json"]


_RUN_COLUMNS = ("run_id, idempotency_key, status, started_at, finished_at, wall_clock_ms, "
                "request_json, artefact_id, warnings_json, coverage_json, provenance_json, error")


def insert_run(conn: psycopg.Connection, *, run_id: str, idempotency_key: str, status: str,
               started_at: str, request_json: str) -> None:
    conn.execute("INSERT INTO run (run_id, idempotency_key, status, started_at, request_json) "
                 "VALUES (%s, %s, %s, %s, %s)",
                 (run_id, idempotency_key, status, started_at, request_json))


def mark_running(conn: psycopg.Connection, run_id: str) -> None:
    conn.execute("UPDATE run SET status = 'running' WHERE run_id = %s AND status = 'queued'",
                 (run_id,))


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


def succeeded_run_for_key(conn: psycopg.Connection, key: str) -> Optional[dict[str, Any]]:
    """The first successful run for a key: the one a cached request is answered with."""
    return conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM run WHERE idempotency_key = %s AND status = 'succeeded' "
        "ORDER BY started_at, run_id LIMIT 1", (key,)).fetchone()


def active_run_for_key(conn: psycopg.Connection, key: str) -> Optional[dict[str, Any]]:
    """A queued or running run for a key, so an identical request joins it instead of racing."""
    return conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM run WHERE idempotency_key = %s "
        "AND status IN ('queued', 'running') ORDER BY started_at, run_id LIMIT 1",
        (key,)).fetchone()


def fail_orphaned_runs(conn: psycopg.Connection) -> int:
    """Runs left queued or running by a previous process can never finish; say so."""
    cur = conn.execute(
        "UPDATE run SET status = 'failed', finished_at = %s, "
        "error = 'the engine stopped before this run finished' "
        "WHERE status IN ('queued', 'running')", (utc_now(),))
    return cur.rowcount


def list_runs(conn: psycopg.Connection, limit: int) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT run_id, idempotency_key, status, started_at, finished_at, wall_clock_ms, "
        "artefact_id FROM run ORDER BY started_at DESC, run_id LIMIT %s", (limit,)).fetchall()


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in ("snapshot", "source_file", "observation", "calibration", "artefact", "run")}
