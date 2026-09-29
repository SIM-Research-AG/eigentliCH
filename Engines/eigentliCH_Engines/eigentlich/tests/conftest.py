"""Shared fixtures.

* **A real PostgreSQL server**, no fallback. Unreachable means the run stops with the remedy; it never goes
  green by skipping the store.
* **A throwaway schema per test module**, ``t_<hex>``, created and dropped as the real ``eigentlich`` role,
  never the real schema. The teardown asserts it dropped exactly that schema and its default privileges.
* **The curator role, granted in the throwaway schema exactly as provisioning grants it in ``eigentlich``**
  (``Instruments/store/provision.py``): USAGE on the schema; SELECT, INSERT, UPDATE on all tables; USAGE,
  SELECT on all sequences; and the same two default privileges for tables created later.
* **Revert hook (dev/verify_regressions.py only).** When ``EIGENTLICH_TEST_REVERT`` holds SQL, it runs in each
  throwaway schema right after ``schema.sql``: that is how a regression test is shown to fail once its fix is
  reverted. Unset in every normal run.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable, Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from eigentlich import store
from eigentlich.settings import Settings, load, with_schema
from eigentlich.store import Decision, Store

REVERT_VAR = "EIGENTLICH_TEST_REVERT"


def pytest_configure(config):
    target = load().database
    try:
        with psycopg.connect(target.conninfo(), connect_timeout=5):
            pass
    except Exception as exc:  # noqa: BLE001
        raise pytest.UsageError(
            f"cannot reach PostgreSQL at {target.redacted_url()}: {exc}\n"
            "  The suite runs against a real server; there is no fallback.\n"
            "  Start it:  docker compose up -d   (in Projects\\PostgreSQL)\n"
            "  Provision the roles once:  python -m store.provision   (in Projects\\Engines\\Instruments)"
        ) from exc


def grant_curator(conn: psycopg.Connection, schema: str, curator_role: str) -> None:
    """The grants provisioning gives the curator on schema `eigentlich`, applied to `schema`."""
    s, r = sql.Identifier(schema), sql.Identifier(curator_role)
    owner = sql.Identifier(conn.execute("SELECT current_user AS u").fetchone()["u"])
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(s, r))
    conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}").format(s, r))
    conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(s, r))
    conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT, INSERT, UPDATE ON TABLES "
                         "TO {}").format(owner, s, r))
    conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT USAGE, SELECT ON SEQUENCES "
                         "TO {}").format(owner, s, r))


def make_schema() -> Settings:
    settings = with_schema(load(), f"t_{uuid.uuid4().hex[:12]}")
    st = Store(settings.database)
    st.initialise()
    revert = os.environ.get(REVERT_VAR)
    with st.session() as conn:
        if revert:
            conn.execute(revert)
        grant_curator(conn, settings.database.schema, settings.curator.user)
    return settings


def drop_schema(settings: Settings) -> None:
    schema = settings.database.schema
    assert schema.startswith("t_") and schema != "eigentlich", f"refusing to drop {schema!r}"
    st = Store(settings.database)
    with psycopg.connect(settings.database.conninfo(), autocommit=True, row_factory=dict_row) as conn:
        oid = conn.execute("SELECT oid FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()["oid"]
        others = conn.execute("SELECT count(*) AS n FROM pg_namespace WHERE nspname <> %s", (schema,)).fetchone()["n"]
    st.drop_schema()
    with psycopg.connect(settings.database.conninfo(), autocommit=True, row_factory=dict_row) as conn:
        assert conn.execute("SELECT count(*) AS n FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM pg_namespace WHERE nspname <> %s",
                            (schema,)).fetchone()["n"] == others, "the teardown dropped something else"
        assert conn.execute("SELECT count(*) AS n FROM pg_default_acl WHERE defaclnamespace = %s",
                            (oid,)).fetchone()["n"] == 0, "default privileges outlived their schema"


@pytest.fixture(scope="module")
def settings() -> Iterator[Settings]:
    s = make_schema()
    yield s
    drop_schema(s)


@pytest.fixture(scope="module")
def st(settings) -> Store:
    return Store(settings.database)


@pytest.fixture()
def db(st) -> Iterator[psycopg.Connection]:
    """A connection as `eigentlich`, committed on success."""
    with st.session() as conn:
        yield conn


def connect(settings: Settings, *, as_curator: bool = False, autocommit: bool = False,
            search_path: bool = True) -> psycopg.Connection:
    """A raw connection. The curator's has the default search_path unless asked otherwise, as the cockpit's
    would, so tests that rely on it must qualify names."""
    cfg = settings.database
    if as_curator:
        conn = psycopg.connect(cfg.conninfo(user=settings.curator.user, password=settings.curator.password),
                               autocommit=autocommit, row_factory=dict_row)
    else:
        conn = psycopg.connect(cfg.conninfo(), autocommit=autocommit, row_factory=dict_row)
    if search_path:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(cfg.schema)))
        if not autocommit:
            conn.commit()
    return conn


@pytest.fixture()
def curator_db(settings) -> Iterator[psycopg.Connection]:
    conn = connect(settings, as_curator=True, autocommit=True, search_path=False)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_client(st) -> Callable[..., dict[str, Any]]:
    def make(**over) -> dict[str, Any]:
        with st.session() as conn:
            return store.create_client(conn, **{"display_name": "Test Client", "age_at_registration": 40, **over})
    return make


@pytest.fixture()
def make_curator(st) -> Callable[..., dict[str, Any]]:
    def make(**over) -> dict[str, Any]:
        with st.session() as conn:
            return store.create_curator(conn, **{"display_name": f"Curator {uuid.uuid4().hex[:6]}", **over})
    return make


def minimal_questionnaire(questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"version": "test@1.0.0", "questions": questions or [
        {"key": "canton", "order": 1, "type": "choice",
         "options": [{"value": "Bern", "label": {"de": "Bern"}}, {"value": "Zug", "label": {"de": "Zug"}}],
         "question": {"de": "Wohnkanton?"}},
        {"key": "health", "order": 2, "type": "number", "min": 0, "max": 1,
         "fills": {"entity": "member_fact", "key": "health", "data_class": "K3"}, "question": {"de": "Belastbarkeit?"}},
        {"key": "income", "order": 3, "type": "number", "question": {"de": "Einkommen?"}},
    ]}


@pytest.fixture()
def questionnaire(st) -> Callable[[str], int]:
    """Save a small questionnaire under a fresh key; returns (key, version)."""
    def make(key: str | None = None) -> tuple[str, int]:
        key = key or f"questionnaire/test-{uuid.uuid4().hex[:8]}"
        with st.session() as conn:
            v = store.save_content(conn, key=key, kind="questionnaire", body=minimal_questionnaire(),
                                   saved_by_kind="seed", saved_by_ref="tests")
        return key, v
    return make


def plan_position(conn: psycopg.Connection, client_id: str, **over) -> dict[str, Any]:
    """One position under a fresh decision, through the store."""
    with store.plan_change(conn, decision=Decision(client_id=client_id, author="client", question="Position?",
                                                   choice="Ja")) as change:
        return change.insert("position", **{"client_id": client_id, "role": "income", "capital_type": "human",
                                            "label": "Anstellung", "magnitude": 90000.0,
                                            "magnitude_unit": "chf_per_year", **over})


TODAY = date(2026, 9, 28)


@contextmanager
def refused(conn: psycopg.Connection, exc, match: str | None = None) -> Iterator[None]:
    """Expect the database to refuse, inside a savepoint, so the connection's transaction carries on."""
    with pytest.raises(exc, match=match):
        with conn.transaction():
            yield
