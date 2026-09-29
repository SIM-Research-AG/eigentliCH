"""The store's boundary, tested rather than described (Engine Building Guide 7.7, 7.8, 8.2, 8.7), and the
concurrency a browser produces (TestClient serialises requests; a test bench fires several at once).

Runs against the real server as the real ``lbs`` role.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import psycopg
import pytest

from lbs.settings import load
from lbs.store import Store

from .conftest import sample_request


def _conn():
    return psycopg.connect(load().database.conninfo(), autocommit=True)


def _foreign_schemas() -> list[str]:
    with _conn() as conn:
        rows = conn.execute("SELECT nspname FROM pg_namespace WHERE nspname <> 'information_schema' "
                            "ORDER BY 1").fetchall()
    own = load().database.schema
    return [r[0] for r in rows if not r[0].startswith(("pg_", "t_")) and r[0] != own]


@pytest.mark.parametrize("schema", _foreign_schemas())
def test_the_lbs_role_cannot_write_outside_its_schema(schema):
    with _conn() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f'CREATE TABLE "{schema}".lbs_boundary_probe (x int)')


def test_the_lbs_role_owns_its_schema():
    with _conn() as conn:
        owner = conn.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
                             (load().database.schema,)).fetchone()[0]
    assert owner == "lbs"


def test_no_single_precision_column(settings, client):
    """Guide 7.8: every float is DOUBLE PRECISION, never REAL. Swept over the schema the suite provisioned."""
    schema = settings.database.schema
    with _conn() as conn:
        rows = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = %s AND data_type = 'real'", (schema,)).fetchall()
        tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                              (schema,)).fetchone()[0]
        doubles = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
                               "AND data_type = 'double precision'", (schema,)).fetchone()[0]
    assert tables >= 3, "the sweep saw no tables: information_schema hides what the role cannot see"
    assert rows == [] and doubles >= 1


def test_every_table_states_its_purpose(settings, client):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r'", (settings.database.schema,)).fetchall()
    assert len(rows) == 3 and all(desc and desc.startswith("lbs:") for _, desc in rows), rows


@pytest.mark.parametrize("statement", ["DELETE FROM calibration", "UPDATE calibration SET parent_version = NULL",
                                       "DELETE FROM artefact", "UPDATE artefact SET client_ref = 'x'"])
def test_artefacts_and_calibrations_are_append_only(settings, client, statement):
    client.post("/run", json=sample_request(client_ref="append-only"))
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(statement)


def test_a_concurrent_burst_is_served():
    """The opening burst of a test bench: the same run and the reads, from a thread pool, against a real
    server socket (not TestClient)."""
    import uvicorn

    from lbs.api import create_app

    base = load()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = replace(base, port=port, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    body = sample_request(client_ref="burst")
    try:
        deadline = time.time() + 30
        while not server.started:
            assert time.time() < deadline, "the server did not start"
            time.sleep(0.05)
        with ThreadPoolExecutor(max_workers=8) as pool:
            runs = list(pool.map(lambda _: httpx.post(f"{url}/run", json=body, timeout=60).json(), range(8)))
            reads = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  ["/health", "/meta", "/contracts", "/calibration", "/records", "/runs"] * 2))
        assert all(r["status"] == "succeeded" for r in runs), runs
        assert len({r["artefact_id"] for r in runs}) == 1 and len({r["idempotency_key"] for r in runs}) == 1
        assert set(reads) == {200}
        aid = runs[0]["artefact_id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = [f"/sheet/{aid}", f"/sheet/{aid}/grid", f"/sheet/{aid}/mandate", f"/sheet/{aid}/gaps",
                     f"/artefacts/{aid}"]
            codes = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code, paths * 2))
        assert set(codes) == {200}
        with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
            conn.execute(f"SET search_path TO {settings.database.schema}")
            assert conn.execute("SELECT count(*) FROM artefact").fetchone()[0] == 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        Store(settings.database).drop_schema()
