"""The store's boundary, tested rather than described: what `eigentlich` and `curator` can and cannot do.

Runs against the real server as the real roles. The curator's grants in the throwaway schema are the ones
provisioning gives it on `eigentlich` (conftest.grant_curator); the real schema's grants are checked too.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from eigentlich.settings import load
from eigentlich.store import TABLES, VIEWS

from . import world
from .conftest import connect

OTHER_SCHEMAS = ["datafeed", "pcp", "lbs", "report", "chatbot", "public"]


def _admin_free(user_conninfo: str) -> psycopg.Connection:
    return psycopg.connect(user_conninfo, autocommit=True, row_factory=dict_row)


# -- role eigentlich ------------------------------------------------------------------------------------

@pytest.mark.parametrize("schema", OTHER_SCHEMAS)
def test_the_eigentlich_role_cannot_write_outside_its_schema(schema):
    with _admin_free(load().database.conninfo()) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.SQL("CREATE TABLE {}.eigentlich_boundary_probe (x int)").format(sql.Identifier(schema)))


def test_the_eigentlich_role_owns_its_schema():
    with _admin_free(load().database.conninfo()) as conn:
        owner = conn.execute("SELECT nspowner::regrole::text AS o FROM pg_namespace WHERE nspname = 'eigentlich'"
                             ).fetchone()["o"]
    assert owner == "eigentlich"


# -- role curator ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def w(st):
    return world.build(st, tag="boundary")


@pytest.mark.parametrize("table", TABLES)
def test_the_curator_can_read_every_table(settings, curator_db, table):
    curator_db.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(
        sql.Identifier(settings.database.schema), sql.Identifier(table)))


@pytest.mark.parametrize("view", VIEWS)
def test_the_curator_can_read_every_view(settings, curator_db, view):
    curator_db.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(
        sql.Identifier(settings.database.schema), sql.Identifier(view)))


@pytest.mark.parametrize("table,key,ref", [("client", "id", "client"), ("position", "id", "position"),
                                           ("decision", "id", "decision"), ("content_record", "key", "questionnaire"),
                                           ("answer", "id", "answer"), ("curator", "id", "curator"),
                                           ("goal_funding", "goal_id", "goal"), ("submission", "id", "submission")])
def test_the_curator_cannot_delete(settings, curator_db, w, table, key, ref):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        curator_db.execute(sql.SQL("DELETE FROM {}.{} WHERE {} = %s").format(
            sql.Identifier(settings.database.schema), sql.Identifier(table), sql.Identifier(key)), (w[ref],))


def test_the_curator_cannot_truncate(settings, curator_db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        curator_db.execute(sql.SQL("TRUNCATE {}.thread").format(sql.Identifier(settings.database.schema)))


def test_the_curator_can_insert_and_update(settings, curator_db, w):
    s = sql.Identifier(settings.database.schema)
    row = curator_db.execute(sql.SQL("INSERT INTO {}.client (display_name, age_at_registration, created_by_kind, "
                                     "created_by_ref) VALUES ('Vom Cockpit', 52, 'curator', %s) RETURNING id").format(s),
                             (w["curator"],)).fetchone()
    curator_db.execute(sql.SQL("UPDATE {}.client SET display_name = 'Vom Cockpit, korrigiert' WHERE id = %s").format(s),
                       (row["id"],))


def test_the_curator_cannot_create_tables(settings, curator_db):
    for schema in (settings.database.schema, "eigentlich", "public"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            curator_db.execute(sql.SQL("CREATE TABLE {}.curator_probe (x int)").format(sql.Identifier(schema)))


def test_the_curator_cannot_create_a_schema(curator_db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        curator_db.execute("CREATE SCHEMA curator_probe")


@pytest.mark.parametrize("schema", ["datafeed", "pcp", "lbs", "report", "chatbot"])
def test_the_curator_cannot_touch_another_schema(curator_db, schema):
    table = curator_db.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relkind = 'r' LIMIT 1", (schema,)).fetchone()
    if table is None:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            curator_db.execute(sql.SQL("CREATE TABLE {}.curator_probe (x int)").format(sql.Identifier(schema)))
        return
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        curator_db.execute(sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(sql.Identifier(schema),
                                                                         sql.Identifier(table["relname"])))


def test_the_curator_cannot_stand_the_guards_down(settings, w):
    """Setting the erasure switch does nothing for a role that does not own the schema."""
    s = sql.Identifier(settings.database.schema)
    with connect(settings, as_curator=True, search_path=False) as conn:
        conn.execute("SELECT set_config('eigentlich.erasure_client', %s, false)", (w["client"],))
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql.SQL("UPDATE {}.decision SET choice = 'x' WHERE id = %s").format(s), (w["decision"],))
        conn.rollback()
        conn.execute("SELECT set_config('eigentlich.erasure_client', %s, false)", (w["client"],))
        with pytest.raises(psycopg.errors.RaiseException, match="C-09"):
            conn.execute(sql.SQL("UPDATE {}.position SET label = 'x' WHERE id = %s").format(s), (w["position"],))


def test_the_curator_cannot_drop_or_alter(settings, curator_db):
    s = sql.Identifier(settings.database.schema)
    for statement in ("DROP TABLE {}.thread", "ALTER TABLE {}.thread ADD COLUMN x int",
                      "DROP TRIGGER decision_append_only ON {}.decision"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            curator_db.execute(sql.SQL(statement).format(s))


# -- the real schema ------------------------------------------------------------------------------------

def _real():
    return _admin_free(load().database.conninfo())


def test_the_real_schema_is_initialised_and_commented():
    with _real() as conn:
        rows = conn.execute("SELECT c.relname, obj_description(c.oid) AS d FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid = c.relnamespace WHERE n.nspname = 'eigentlich' AND c.relkind IN ('r', 'v')"
                            ).fetchall()
    names = {r["relname"] for r in rows}
    assert names >= set(TABLES) | set(VIEWS), "run `python -m eigentlich init-db` first"
    assert all(r["d"] for r in rows)


def test_the_real_schema_has_no_single_precision_column():
    with _real() as conn:
        rows = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = 'eigentlich' AND data_type = 'real'").fetchall()
        tables = conn.execute("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = 'eigentlich'"
                              ).fetchone()["n"]
    assert tables >= len(TABLES)
    assert rows == []


@pytest.mark.parametrize("table", TABLES)
def test_provisioning_grants_the_curator_select_insert_update_but_not_delete(table):
    """Provisioning's default privileges reached the tables init-db created in the real schema."""
    with _real() as conn:
        p = conn.execute("SELECT has_table_privilege('curator', %(t)s, 'SELECT') AS s, "
                         "has_table_privilege('curator', %(t)s, 'INSERT') AS i, "
                         "has_table_privilege('curator', %(t)s, 'UPDATE') AS u, "
                         "has_table_privilege('curator', %(t)s, 'DELETE') AS d, "
                         "has_table_privilege('curator', %(t)s, 'TRUNCATE') AS tr",
                         {"t": f"eigentlich.{table}"}).fetchone()
    assert (p["s"], p["i"], p["u"], p["d"], p["tr"]) == (True, True, True, False, False)
