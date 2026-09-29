"""The store's boundary, tested rather than described (Engine Building Guide 7.7, 7.8, 8.2, 8.7), and the
concurrency a browser produces, against a real server socket (TestClient serialises requests).

Runs against the real server as the real ``chatbot`` role.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
import uvicorn

from chatbot.settings import load

from .conftest import drop, request_body, settings_for
from .standin import Reply, answer_json

GOOD = answer_json("Mit Pensionskasse dürfen Sie 2026 höchstens CHF 7'258 einzahlen.", ["N1"])


def _conn():
    return psycopg.connect(load().database.conninfo(), autocommit=True)


@pytest.mark.parametrize("schema", ["report", "lbs", "pcp", "fmre", "aggregation", "public"])
def test_the_chatbot_role_cannot_write_outside_its_schema(schema):
    with _conn() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"CREATE TABLE {schema}.chatbot_boundary_probe (x int)")


def test_the_chatbot_role_owns_its_schema():
    with _conn() as conn:
        owner = conn.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
                             (load().database.schema,)).fetchone()[0]
    assert owner == "chatbot"


def test_no_single_precision_column(settings, client):
    """Guide 7.8: every float is DOUBLE PRECISION, never REAL. Swept over the schema the tests built."""
    with _conn() as conn:
        rows = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = %s AND data_type = 'real'", (settings.database.schema,)).fetchall()
        floats = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
                              "AND data_type = 'double precision'", (settings.database.schema,)).fetchone()[0]
        tables = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                              (settings.database.schema,)).fetchone()[0]
    assert tables == 3 and floats >= 2, "the sweep saw no tables or no floats"
    assert rows == []


def test_every_table_states_its_purpose(settings, client):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r'", (settings.database.schema,)).fetchall()
    assert len(rows) == 3 and all(desc for _, desc in rows), rows


def test_answers_and_calibrations_are_append_only(settings, client, spark):
    spark.queue(Reply(content=GOOD))
    client.post("/run", json=request_body(question="Anhängen: Wie viel darf ich 2026 einzahlen?"))
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        for sql in ("DELETE FROM calibration", "UPDATE calibration SET created_at = 'x'", "DELETE FROM artefact",
                    "UPDATE artefact SET refused = NOT refused"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(sql)


def _serve(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        assert time.time() < deadline, "the server did not start"
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"


def test_a_concurrent_burst_calls_the_model_once(standin):
    """Six identical questions at once and the reads, from a thread pool, against a real socket: one model
    call, one stored answer, every caller handed it."""
    from chatbot.api import create_app

    standin.reset()
    standin.responder = lambda body: Reply(content=GOOD, chunk_delay_s=0.02)
    settings = settings_for(standin.url)
    server, thread, url = _serve(create_app(settings))
    body = request_body(question="Ansturm: Wie viel darf ich 2026 einzahlen?")
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            runs = list(pool.map(lambda _: httpx.post(f"{url}/run", json=body, timeout=60).json(), range(6)))
            reads = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  ["/health", "/meta", "/contracts", "/calibration", "/runs"] * 2))
        assert all(r["status"] == "succeeded" for r in runs), runs
        assert len({r["artefact_id"] for r in runs}) == 1
        assert sum(not r["cached"] for r in runs) == 1
        assert len(standin.chat_requests()) == 1
        assert set(reads) == {200}
        aid = runs[0]["artefact_id"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda p: httpx.get(f"{url}{p}", timeout=60).status_code,
                                  [f"/artefacts/{aid}", f"/runs/{runs[0]['run_id']}"] * 4))
        assert set(codes) == {200}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        drop(settings)


def test_two_processes_answering_one_key_store_one_answer(standin):
    """Two engine instances on one schema (as two processes would be) answer the same question at the same
    moment. The model is not deterministic, so they get different texts; the unique key keeps the first and
    both callers are handed it (CHB-06)."""
    from chatbot.api import create_app
    from fastapi.testclient import TestClient

    standin.reset()
    counter = {"n": 0}
    lock = threading.Lock()

    def responder(body):
        with lock:
            counter["n"] += 1
            n = counter["n"]
        return Reply(content=answer_json(f"Entwurf {n}: höchstens CHF 7'258 im Jahr 2026.", ["N1"]), delay_s=0.3)

    standin.responder = responder
    settings = settings_for(standin.url)
    body = request_body(question="Zwei Prozesse: Wie viel darf ich 2026 einzahlen?")
    try:
        with TestClient(create_app(settings)) as a, TestClient(create_app(settings)) as b:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ra, rb = pool.map(lambda c: c.post("/run", json=body).json(), (a, b))
            assert ra["artefact_id"] == rb["artefact_id"] and ra["status"] == rb["status"] == "succeeded"
            assert sorted([ra["cached"], rb["cached"]]) == [False, True]
            assert counter["n"] == 2
            with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
                conn.execute(f"SET search_path TO {settings.database.schema}")
                assert conn.execute("SELECT count(*) FROM artefact").fetchone()[0] == 1
    finally:
        drop(settings)
