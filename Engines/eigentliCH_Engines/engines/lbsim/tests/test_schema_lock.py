"""Applying the schema from several processes at once (ENGINE_CHANGES item 3, DECISIONS LBSIM-20).

The API and every worker apply ``schema.sql`` at start-up. Without a lock, two at the same moment could deadlock
in PostgreSQL on ``pg_proc`` (01.10.2026, three workers started together). ``Store.initialise()`` now takes a
transaction-level advisory lock first, so they queue. Everything here runs on a throwaway ``t_`` schema.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace

import psycopg
import pytest

from lbsim.settings import load
from lbsim.store import SCHEMA_LOCK, Store


@pytest.fixture()
def database():
    s = load()
    db = replace(s.database, schema=f"t_{uuid.uuid4().hex[:12]}")
    yield db
    assert db.schema.startswith("t_")
    Store(db).drop_schema()


def _together(database, n: int = 4) -> list[BaseException]:
    """``n`` threads, each with its own Store and connection, apply the schema at the same moment."""
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def apply() -> None:
        store = Store(database)
        try:
            barrier.wait(timeout=30)
            store.initialise()
        except BaseException as exc:  # noqa: BLE001 - collected and reported by the test
            errors.append(exc)

    threads = [threading.Thread(target=apply) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in threads), "a schema application did not finish"
    return errors


def test_four_at_once_none_fails(database):
    # the first round creates the schema; the later ones replace the functions and triggers, where the deadlock was
    for _ in range(5):
        errors = _together(database)
        assert not errors, [f"{type(e).__name__}: {e}" for e in errors]
    with Store(database).session() as conn:
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (database.schema,))}
    assert {"calibration", "artefact", "run", "run_event"} <= tables


def test_initialise_waits_for_the_lock(database):
    Store(database).initialise()
    holder = psycopg.connect(database.conninfo())
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SCHEMA_LOCK,))
        done = threading.Event()
        t = threading.Thread(target=lambda: (Store(database).initialise(), done.set()))
        t.start()
        assert not done.wait(1.0), "initialise() ran while another session held the schema lock"
        holder.rollback()  # ends the transaction, which releases the lock
        assert done.wait(30), "initialise() did not proceed once the lock was released"
        t.join(timeout=30)
    finally:
        holder.close()
