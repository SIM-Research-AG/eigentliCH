"""The store's boundary, tested rather than described (Engine Building Guide 7.7, 7.8, 8.2, 8.7), and the
concurrency the browser produces (Engine Build Instruction section 8: TestClient serialises requests, a
test bench fires several at once).

Runs against the real server as the real ``pcp`` role.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import psycopg
import pytest

from pcp.settings import load
from pcp.store import Store

from .conftest import aggregation_transport, fmre_transport, instruments, run_body, stamped_return_set


def _conn():
    return psycopg.connect(load().database.conninfo(), autocommit=True)


@pytest.mark.parametrize("schema", ["datafeed", "aggregation", "fmre", "mrs", "honi", "public"])
def test_the_pcp_role_cannot_write_outside_its_schema(schema):
    with _conn() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"CREATE TABLE {schema}.pcp_boundary_probe (x int)")


def test_the_pcp_role_owns_its_schema():
    with _conn() as conn:
        owner = conn.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
                             (load().database.schema,)).fetchone()[0]
    assert owner == "pcp"


def test_no_single_precision_column():
    """Guide 7.8: every float is DOUBLE PRECISION, never REAL."""
    with _conn() as conn:
        rows = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = %s AND data_type = 'real'", (load().database.schema,)).fetchall()
        tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                              (load().database.schema,)).fetchone()[0]
    assert tables >= 3, "the sweep saw no tables: information_schema hides what the role cannot see"
    assert rows == []


def test_every_table_states_its_purpose():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r'", (load().database.schema,)).fetchall()
    assert rows and all(desc for _, desc in rows), rows


def test_artefacts_and_calibrations_are_append_only(settings, client):
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("DELETE FROM calibration")


def test_a_concurrent_burst_is_served():
    """The opening burst of a test bench: the same run and the reads, from a thread pool, against a real
    server socket (not TestClient)."""
    import socket
    import threading
    import time

    import uvicorn

    from pcp.api import create_app

    base = load()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = replace(base, port=port, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))
    app = create_app(settings, aggregation_transport(), fmre_transport(stamped_return_set()))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    body = run_body({"client": "burst", "name": "balanced", "target_curve": [0.02] * 25,
                     "universe": sorted(i["instrument_id"] for i in instruments()), "max_single_position": 0.15,
                     "regime_market": "global"})
    try:
        deadline = time.time() + 30
        while not server.started:
            assert time.time() < deadline, "the server did not start"
            time.sleep(0.05)
        with ThreadPoolExecutor(max_workers=8) as pool:
            runs = list(pool.map(lambda _: httpx.post(f"{url}/run", json=body, timeout=120).json(), range(6)))
            reads = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  ["/health", "/meta", "/contracts", "/calibration", "/constraints"] * 2))
        assert all(r["status"] == "succeeded" for r in runs), runs
        assert len({r["artefact_id"] for r in runs}) == 1
        assert set(reads) == {200}
        aid = runs[0]["artefact_id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = [f"/allocation/{aid}", f"/allocation/{aid}/map", f"/allocation/{aid}/roles",
                     f"/allocation/{aid}/diagnostics", f"/artefacts/{aid}"]
            codes = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code, paths * 2))
        assert set(codes) == {200}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        Store(settings.database).drop_schema()
