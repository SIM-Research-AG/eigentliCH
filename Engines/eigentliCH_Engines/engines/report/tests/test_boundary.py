"""The store's boundary, tested rather than described (Engine Building Guide 7.7, 7.8, 8.2, 8.7), and the
concurrency a browser produces, against a real server socket.

Runs against the real server as the real ``report`` role.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
import uvicorn

from report.settings import load

from .conftest import Upstream, drop, echo, request_body, settings_for


def _conn():
    return psycopg.connect(load().database.conninfo(), autocommit=True)


@pytest.mark.parametrize("schema", ["chatbot", "lbs", "pcp", "fmre", "aggregation", "public"])
def test_the_report_role_cannot_write_outside_its_schema(schema):
    with _conn() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"CREATE TABLE {schema}.report_boundary_probe (x int)")


@pytest.mark.parametrize("schema", ["lbs", "pcp", "chatbot"])
def test_the_report_role_cannot_read_another_engines_tables(schema):
    """The report reads upstream artefacts over HTTP only (Guide section 1), never from their schema."""
    with _conn() as conn:
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)).fetchall()
        for (table,) in tables:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT 1 FROM {schema}.{table} LIMIT 1")


def test_the_report_role_owns_its_schema():
    with _conn() as conn:
        owner = conn.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
                             (load().database.schema,)).fetchone()[0]
    assert owner == "report"


def test_no_single_precision_column(settings, client):
    with _conn() as conn:
        rows = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = %s AND data_type = 'real'", (settings.database.schema,)).fetchall()
        floats = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
                              "AND data_type = 'double precision'", (settings.database.schema,)).fetchone()[0]
        tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                              (settings.database.schema,)).fetchone()[0]
    assert tables == 3 and floats >= 1, "the sweep saw no tables or no floats"
    assert rows == []


def test_every_table_states_its_purpose(settings, client):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r'", (settings.database.schema,)).fetchall()
    assert len(rows) == 3 and all(desc for _, desc in rows), rows


def test_reports_and_calibrations_are_append_only(settings, client, spark):
    client.post("/run", json=request_body(prose=False))
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        for sql in ("DELETE FROM calibration", "UPDATE calibration SET created_at = 'x'", "DELETE FROM artefact",
                    "UPDATE artefact SET complete = NOT complete"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(sql)


def test_one_complete_report_per_key(settings, client):
    """The partial unique index: a second complete report under a used key is refused by the store itself."""
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        key, client_ref = conn.execute("SELECT idempotency_key, client_ref FROM artefact WHERE complete LIMIT 1").fetchone()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO artefact (artefact_id, idempotency_key, complete, client_ref, kind, language, "
                         "contract_version, created_at, payload_json) VALUES "
                         "('REP-probe', %s, true, %s, 'report', 'de', 'report@1.0.0', 'x', '{}')", (key, client_ref))


def _serve(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        assert time.time() < deadline, "the server did not start"
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"


def test_a_concurrent_burst_writes_one_report(standin):
    """Six identical requests at once and the reads, against a real socket: one report, the prose asked for
    once per section, every caller handed the same id."""
    from report.api import create_app

    standin.reset()
    standin.responder = echo
    settings = settings_for(standin.url)
    server, thread, url = _serve(create_app(settings, Upstream().transports()))
    body = request_body(display_facts=[{"key": "name", "label": "Kundin", "value": "Ansturm", "source": "t"}])
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            runs = list(pool.map(lambda _: httpx.post(f"{url}/run", json=body, timeout=120).json(), range(6)))
            reads = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  ["/health", "/meta", "/contracts", "/calibration", "/runs", "/reports"] * 2))
        assert all(r["status"] == "succeeded" for r in runs), runs
        assert len({r["artefact_id"] for r in runs}) == 1 and sum(not r["cached"] for r in runs) == 1
        assert set(reads) == {200}
        report = httpx.get(f"{url}/artefacts/{runs[0]['artefact_id']}", timeout=60).json()
        slots = sum(1 for s in report["sections"] if s["prose_status"] == "verified")
        assert slots >= 5 and len(standin.chat_requests()) == slots
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  [f"/artefacts/{runs[0]['artefact_id']}", f"/reports/{runs[0]['artefact_id']}/html",
                                   f"/runs/{runs[0]['run_id']}"] * 3))
        assert set(codes) == {200}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        drop(settings)


def test_two_processes_producing_one_key_store_one_complete_report(standin):
    """Two engine instances on one schema produce the same report at the same moment; the model is not
    deterministic in general, so their prose may differ. The store keeps the first complete one and both
    callers are handed it (REP-08)."""
    from fastapi.testclient import TestClient

    from report.api import create_app

    standin.reset()
    counter = {"n": 0}
    lock = threading.Lock()

    def responder(body):
        with lock:
            counter["n"] += 1
        reply = echo(body)
        reply.delay_s = 0.05
        return reply

    standin.responder = responder
    settings = settings_for(standin.url)
    body = request_body(display_facts=[{"key": "name", "label": "Kundin", "value": "Zwei", "source": "t"}])
    try:
        with TestClient(create_app(settings, Upstream().transports())) as a, \
                TestClient(create_app(settings, Upstream().transports())) as b:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ra, rb = pool.map(lambda c: c.post("/run", json=body).json(), (a, b))
        assert ra["artefact_id"] == rb["artefact_id"] and ra["status"] == rb["status"] == "succeeded"
        with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
            conn.execute(f"SET search_path TO {settings.database.schema}")
            assert conn.execute("SELECT count(*) FROM artefact WHERE complete").fetchone()[0] == 1
    finally:
        drop(settings)
