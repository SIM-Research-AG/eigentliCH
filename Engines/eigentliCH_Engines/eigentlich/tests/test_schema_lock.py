"""Applying the schema from several processes at once (ENGINE_CHANGES item 3, applied to the app as to lbsim).

The app applies ``schema.sql`` at start-up (item 6) and ``init-db`` applies it too; two at the same moment could
deadlock in PostgreSQL on ``pg_proc``. ``Store.initialise()`` takes a transaction-level advisory lock first, so
they queue. Everything here runs on a fresh throwaway ``t_`` schema of its own.
"""

from __future__ import annotations

import threading
import uuid

import psycopg
import pytest

from eigentlich.settings import load, with_schema
from eigentlich.store import SCHEMA_LOCK, TABLES, Store

from .conftest import drop_schema


@pytest.fixture()
def fresh():
    s = with_schema(load(), f"t_{uuid.uuid4().hex[:12]}")
    yield s
    drop_schema(s)


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
        t.join(timeout=180)
    assert not any(t.is_alive() for t in threads), "a schema application did not finish"
    return errors


def test_four_at_once_none_fails(fresh):
    # the first round creates the schema; the later ones replace its functions, triggers and views
    for _ in range(3):
        errors = _together(fresh.database)
        assert not errors, [f"{type(e).__name__}: {e}" for e in errors]
    with Store(fresh.database).session() as conn:
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (fresh.database.schema,))}
    assert tables == set(TABLES)


def test_initialise_waits_for_the_lock(fresh):
    Store(fresh.database).initialise()
    holder = psycopg.connect(fresh.database.conninfo())
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SCHEMA_LOCK,))
        done = threading.Event()
        t = threading.Thread(target=lambda: (Store(fresh.database).initialise(), done.set()))
        t.start()
        assert not done.wait(1.0), "initialise() ran while another session held the schema lock"
        holder.rollback()  # ends the transaction, which releases the lock
        assert done.wait(60), "initialise() did not proceed once the lock was released"
        t.join(timeout=60)
    finally:
        holder.close()
