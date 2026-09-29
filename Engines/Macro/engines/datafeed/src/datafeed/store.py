"""Persistence in PostgreSQL. psycopg, no ORM, no migrations.

The store knows nothing about fitting or alignment. It keeps source files, public
responses, snapshots (manifest, series definitions, present cells), calibrations, panel
artefacts and runs. Every data table is append-only in the database itself.

Cells go in through ``COPY``: a snapshot is some eighty thousand rows, and the bootstrap
should take seconds, not minutes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterable, Iterator, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

from .settings import DatabaseConfig


class StoreError(RuntimeError):
    pass


class StoreConflict(ValueError):
    pass


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
                f"cannot reach PostgreSQL at {self.config.redacted_url()}: {exc}. Start it with "
                "`docker compose up -d` in Projects\\PostgreSQL, then `python -m datafeed init-db`."
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
        with psycopg.connect(self.config.conninfo(dbname=self.config.maintenance_dbname),
                             autocommit=True) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                            (self.config.dbname,)).fetchone():
                return False
            conn.execute(f'CREATE DATABASE "{self.config.dbname}"')
            return True

    def initialise(self) -> None:
        ddl = resources.files("datafeed").joinpath("schema.sql").read_text(encoding="utf-8")
        with self.session() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.config.schema}")
            conn.execute(f"SET search_path TO {self.config.schema}, public")
            conn.execute(ddl)

    def drop_schema(self) -> None:
        with self.session() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {self.config.schema} CASCADE")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get_countries(conn) -> list[dict[str, Any]]:
    return conn.execute("SELECT code, name, iso3, matlab_field FROM country ORDER BY code").fetchall()


def get_series_specs(conn) -> list[dict[str, Any]]:
    return conn.execute("SELECT series_id, category, unit, period, indices_json, matlab_sheet, "
                        "matlab_column, zero_is_a_value, description FROM series ORDER BY series_id").fetchall()


def insert_country(conn, *, code: str, name: str, iso3: str, matlab_field: Optional[str]) -> bool:
    """Insert if absent. False if the code already exists (the database wins)."""
    cur = conn.execute("INSERT INTO country (code, name, iso3, matlab_field, updated_at) "
                       "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING",
                       (code, name, iso3, matlab_field, utc_now()))
    return cur.rowcount == 1


def insert_series(conn, *, series_id: str, category: str, unit: str, period: str, indices_json: str,
                  matlab_sheet: Optional[str], matlab_column: Optional[int], zero_is_a_value: bool,
                  description: str = "") -> bool:
    cur = conn.execute("INSERT INTO series (series_id, category, unit, period, indices_json, matlab_sheet, "
                       "matlab_column, zero_is_a_value, description, updated_at) "
                       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (series_id) DO NOTHING",
                       (series_id, category, unit, period, indices_json, matlab_sheet, matlab_column,
                        int(zero_is_a_value), description, utc_now()))
    return cur.rowcount == 1


def describe_series(conn, *, series_id: str, description: str) -> bool:
    """Write a description where the registry row has none. The database wins where it holds text."""
    cur = conn.execute("UPDATE series SET description = %s, updated_at = %s "
                       "WHERE series_id = %s AND description = ''", (description, utc_now(), series_id))
    return cur.rowcount == 1


def put_conversions(conn, snapshot_id: str, rows: Iterable[tuple]) -> None:
    """(country, series_id, nan, leading_zero, trailing_zero, interior_zero, placeholder)."""
    with conn.cursor().copy("COPY series_conversion (snapshot_id, country, series_id, nan, leading_zero, "
                            "trailing_zero, interior_zero, placeholder) FROM STDIN") as copy:
        for r in rows:
            copy.write_row((snapshot_id, *r))


def get_conversions(conn, snapshot_id: str) -> list[dict[str, Any]]:
    return conn.execute("SELECT country, series_id, nan, leading_zero, trailing_zero, interior_zero, placeholder "
                        "FROM series_conversion WHERE snapshot_id = %s ORDER BY country, series_id",
                        (snapshot_id,)).fetchall()


def has_conversions(conn, snapshot_id: str) -> bool:
    return conn.execute("SELECT 1 FROM series_conversion WHERE snapshot_id = %s LIMIT 1",
                        (snapshot_id,)).fetchone() is not None


# ---------------------------------------------------------------------------
# Source files and public responses
# ---------------------------------------------------------------------------

def put_source_file(conn, *, name: str, sha256: str, byte_size: int, origin: str, note: str = "") -> None:
    conn.execute(
        "INSERT INTO source_file (name, sha256, byte_size, loaded_at, origin, note) "
        "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (name, sha256, byte_size, utc_now(), origin, note))


def put_public_fetch(conn, *, fetch_id: str, provider: str, code: str, country: str, url: str,
                     fetched_at: str, response_sha256: str, values: dict[int, float]) -> bool:
    """Store one public response. False if those exact bytes are already stored."""
    if conn.execute("SELECT 1 FROM public_fetch WHERE fetch_id = %s", (fetch_id,)).fetchone():
        return False
    conn.execute(
        "INSERT INTO public_fetch (fetch_id, provider, code, country, url, fetched_at, response_sha256) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (fetch_id, provider, code, country, url, fetched_at, response_sha256))
    with conn.cursor().copy("COPY public_value (fetch_id, year, value) FROM STDIN") as copy:
        for year, value in sorted(values.items()):
            copy.write_row((fetch_id, year, value))
    return True


def latest_public(conn, *, provider: str, code: str, country: str) -> Optional[tuple[str, dict[int, float]]]:
    row = conn.execute(
        "SELECT fetch_id FROM public_fetch WHERE provider = %s AND code = %s AND country = %s "
        "ORDER BY fetched_at DESC, fetch_id LIMIT 1", (provider, code, country)).fetchone()
    if row is None:
        return None
    values = conn.execute("SELECT year, value FROM public_value WHERE fetch_id = %s ORDER BY year",
                          (row["fetch_id"],)).fetchall()
    return row["fetch_id"], {r["year"]: r["value"] for r in values}


def public_fetches(conn) -> list[dict[str, Any]]:
    return conn.execute("SELECT fetch_id, provider, code, country, url, fetched_at, response_sha256 "
                        "FROM public_fetch ORDER BY provider, code, country, fetched_at").fetchall()


def public_values(conn, fetch_id: str) -> dict[int, float]:
    rows = conn.execute("SELECT year, value FROM public_value WHERE fetch_id = %s ORDER BY year",
                        (fetch_id,)).fetchall()
    return {r["year"]: r["value"] for r in rows}


def put_market_fetch(conn, *, fetch_id: str, provider: str, code: str, url: str, fetched_at: str,
                     response_sha256: str, values: dict[str, float]) -> bool:
    """Store one market response (DF-18). False if those exact bytes are already stored."""
    if conn.execute("SELECT 1 FROM market_fetch WHERE fetch_id = %s", (fetch_id,)).fetchone():
        return False
    conn.execute(
        "INSERT INTO market_fetch (fetch_id, provider, code, url, fetched_at, response_sha256) "
        "VALUES (%s, %s, %s, %s, %s, %s)", (fetch_id, provider, code, url, fetched_at, response_sha256))
    with conn.cursor().copy("COPY market_value (fetch_id, date, value) FROM STDIN") as copy:
        for date, value in sorted(values.items()):
            copy.write_row((fetch_id, date, value))
    return True


def latest_market(conn, *, provider: str, code: str) -> Optional[tuple[str, dict[str, float]]]:
    row = conn.execute(
        "SELECT fetch_id FROM market_fetch WHERE provider = %s AND code = %s "
        "ORDER BY fetched_at DESC, fetch_id LIMIT 1", (provider, code)).fetchone()
    if row is None:
        return None
    rows = conn.execute("SELECT date, value FROM market_value WHERE fetch_id = %s ORDER BY date",
                        (row["fetch_id"],)).fetchall()
    return row["fetch_id"], {r["date"]: r["value"] for r in rows}


def market_fetches(conn) -> list[dict[str, Any]]:
    return conn.execute("SELECT fetch_id, provider, code, url, fetched_at, response_sha256 "
                        "FROM market_fetch ORDER BY provider, code, fetched_at").fetchall()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def snapshot_checksum(conn, snapshot_id: str) -> Optional[str]:
    row = conn.execute("SELECT checksum FROM snapshot WHERE snapshot_id = %s", (snapshot_id,)).fetchone()
    return None if row is None else row["checksum"]


def put_snapshot(conn, *, snapshot_id: str, parent_id: Optional[str], checksum: str,
                 manifest_json: str, definitions: Iterable[tuple[str, str, str]],
                 cells: Iterable[tuple[str, str, str, float, str, str]]) -> None:
    conn.execute("INSERT INTO snapshot (snapshot_id, parent_id, checksum, built_at, manifest_json) "
                 "VALUES (%s, %s, %s, %s, %s)", (snapshot_id, parent_id, checksum, utc_now(), manifest_json))
    cur = conn.cursor()
    with cur.copy("COPY series_definition (snapshot_id, country, series_id, payload_json) FROM STDIN") as copy:
        for country, series_id, payload in definitions:
            copy.write_row((snapshot_id, country, series_id, payload))
    with cur.copy("COPY observation (snapshot_id, country, series_id, date, value, flag, source) "
                  "FROM STDIN") as copy:
        for country, series_id, date, value, flag, source in cells:
            copy.write_row((snapshot_id, country, series_id, date, value, flag, source))


def get_manifest(conn, snapshot_id: str) -> Optional[str]:
    row = conn.execute("SELECT manifest_json FROM snapshot WHERE snapshot_id = %s", (snapshot_id,)).fetchone()
    return None if row is None else row["manifest_json"]


def list_manifests(conn) -> list[str]:
    return [r["manifest_json"] for r in conn.execute(
        "SELECT manifest_json FROM snapshot ORDER BY built_at DESC, snapshot_id DESC").fetchall()]


def get_definitions(conn, snapshot_id: str) -> list[str]:
    return [r["payload_json"] for r in conn.execute(
        "SELECT payload_json FROM series_definition WHERE snapshot_id = %s ORDER BY country, series_id",
        (snapshot_id,)).fetchall()]


def get_cells(conn, snapshot_id: str, *, series: Sequence[str] = (), countries: Sequence[str] = (),
              start: Optional[str] = None, end: Optional[str] = None) -> list[tuple]:
    sql = ["SELECT country, series_id, date, value, flag, source FROM observation WHERE snapshot_id = %s"]
    params: list[Any] = [snapshot_id]
    if series:
        sql.append("AND series_id = ANY(%s)"); params.append(list(series))
    if countries:
        sql.append("AND country = ANY(%s)"); params.append(list(countries))
    if start:
        sql.append("AND date >= %s"); params.append(start)
    if end:
        sql.append("AND date <= %s"); params.append(end)
    with conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
        return cur.execute(" ".join(sql), params).fetchall()


# ---------------------------------------------------------------------------
# Calibrations, artefacts, runs (the same shape in every engine)
# ---------------------------------------------------------------------------

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


def put_artefact(conn, *, artefact_id: str, idempotency_key: str, contract_version: str, payload_json: str) -> None:
    conn.execute("INSERT INTO artefact (artefact_id, idempotency_key, contract_version, created_at, payload_json) "
                 "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                 (artefact_id, idempotency_key, contract_version, utc_now(), payload_json))


def get_artefact(conn, artefact_id: str) -> Optional[str]:
    row = conn.execute("SELECT payload_json FROM artefact WHERE artefact_id = %s", (artefact_id,)).fetchone()
    return None if row is None else row["payload_json"]


_RUN = ("run_id, idempotency_key, status, started_at, finished_at, wall_clock_ms, request_json, "
        "artefact_id, warnings_json, coverage_json, provenance_json, error")


def insert_run(conn, *, run_id: str, idempotency_key: str, started_at: str, request_json: str) -> None:
    conn.execute("INSERT INTO run (run_id, idempotency_key, status, started_at, request_json) "
                 "VALUES (%s, %s, 'running', %s, %s)", (run_id, idempotency_key, started_at, request_json))


def finish_run(conn, *, run_id: str, status: str, wall_clock_ms: float, artefact_id: Optional[str],
               warnings_json: str, coverage_json: Optional[str], provenance_json: Optional[str],
               error: Optional[str]) -> None:
    conn.execute("UPDATE run SET status = %s, finished_at = %s, wall_clock_ms = %s, artefact_id = %s, "
                 "warnings_json = %s, coverage_json = %s, provenance_json = %s, error = %s WHERE run_id = %s",
                 (status, utc_now(), wall_clock_ms, artefact_id, warnings_json, coverage_json,
                  provenance_json, error, run_id))


def get_run(conn, run_id: str) -> Optional[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN} FROM run WHERE run_id = %s", (run_id,)).fetchone()


def succeeded_run_for_key(conn, key: str) -> Optional[dict[str, Any]]:
    return conn.execute(f"SELECT {_RUN} FROM run WHERE idempotency_key = %s AND status = 'succeeded' "
                        "ORDER BY started_at, run_id LIMIT 1", (key,)).fetchone()


def table_counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in ("country", "series", "snapshot", "observation", "series_conversion", "public_fetch",
                      "calibration", "artefact", "run")}
