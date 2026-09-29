"""The schema as built: it loads (twice), every object is listed, commented and classified, no float is
single precision, and every function pins its search_path."""

from __future__ import annotations

import pytest

from eigentlich.store import TABLES, VIEWS, Store


def _catalog(conn, schema: str, kinds: tuple[str, ...]) -> set[str]:
    rows = conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = %s AND c.relkind = ANY(%s)", (schema, list(kinds))).fetchall()
    return {r["relname"] for r in rows}


def test_schema_loads_twice(settings, st):
    Store(settings.database).initialise()   # the fixture loaded it once; a second load changes nothing
    with st.session() as conn:
        assert _catalog(conn, settings.database.schema, ("r",)) == set(TABLES)


def test_every_table_and_view_is_listed(settings, db):
    assert _catalog(db, settings.database.schema, ("r",)) == set(TABLES)
    assert _catalog(db, settings.database.schema, ("v",)) == set(VIEWS)


def test_no_single_precision_column(settings, db):
    """Every float is DOUBLE PRECISION, never REAL."""
    real = db.execute("SELECT table_name, column_name FROM information_schema.columns "
                      "WHERE table_schema = %s AND data_type = 'real'", (settings.database.schema,)).fetchall()
    floats = db.execute("SELECT table_name || '.' || column_name AS c FROM information_schema.columns "
                        "WHERE table_schema = %s AND data_type = 'double precision'",
                        (settings.database.schema,)).fetchall()
    tables = db.execute("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = %s",
                        (settings.database.schema,)).fetchone()["n"]
    assert tables >= len(TABLES), "the sweep saw too few tables: information_schema hides what the role cannot see"
    assert {f["c"] for f in floats} == {"position.magnitude", "goal.target_amount", "goal.contribution_share"}
    assert real == []


def test_every_table_and_view_states_its_purpose(settings, db):
    rows = db.execute("SELECT c.relname, c.relkind, obj_description(c.oid) AS d FROM pg_class c "
                      "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind IN ('r', 'v')",
                      (settings.database.schema,)).fetchall()
    assert len(rows) == len(TABLES) + len(VIEWS)
    assert all(r["d"] and r["d"].startswith("eigentlich: ") for r in rows), [r["relname"] for r in rows if not r["d"]]


def test_every_table_carries_a_data_class(settings, db):
    rows = db.execute("SELECT table_name FROM information_schema.columns WHERE table_schema = %s "
                      "AND column_name = 'data_class' AND data_type = 'smallint'", (settings.database.schema,)).fetchall()
    assert {r["table_name"] for r in rows} >= set(TABLES)


@pytest.mark.parametrize("table", TABLES)
def test_data_class_is_bounded(settings, db, table):
    """K0..K3 and a per-table floor, enforced by CHECK."""
    checks = db.execute(
        "SELECT pg_get_constraintdef(c.oid) AS d FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = %s AND t.relname = %s AND c.contype = 'c'",
        (settings.database.schema, table)).fetchall()
    assert any("data_class" in c["d"] for c in checks), table


def test_every_function_pins_its_search_path(settings, db):
    """A trigger fired by the cockpit must resolve this schema's tables whatever its session's search_path."""
    rows = db.execute("SELECT p.proname, p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                      "WHERE n.nspname = %s", (settings.database.schema,)).fetchall()
    assert len(rows) >= 15
    unpinned = [r["proname"] for r in rows
                if not any(c == f"search_path={settings.database.schema}" for c in (r["proconfig"] or []))]
    assert unpinned == []


def test_timestamps_are_timestamptz(settings, db):
    rows = db.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s "
                      "AND data_type = 'timestamp without time zone'", (settings.database.schema,)).fetchall()
    assert rows == []


def test_json_is_jsonb(settings, db):
    rows = db.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = %s "
                      "AND data_type = 'json'", (settings.database.schema,)).fetchall()
    assert rows == []
