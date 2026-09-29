"""C-09 in PostgreSQL: every write to a plan table names a decision written in the same transaction.

The prototype could hold this only for writes through SQLAlchemy (its db.py says so); here the database
refuses a raw INSERT, a raw UPDATE and a stale decision alike, for the backend and the cockpit.
"""

from __future__ import annotations

import psycopg
import pytest

from eigentlich import store
from eigentlich.store import Decision

from .conftest import TODAY, connect, plan_position


def _decision(conn, client_id: str) -> str:
    return conn.execute("INSERT INTO decision (client_id, author, question, choice) VALUES (%s, 'client', 'q', 'c') "
                        "RETURNING id", (client_id,)).fetchone()["id"]


def _position_sql(conn, client_id: str, decision_id: str) -> dict:
    return conn.execute("INSERT INTO position (client_id, role, capital_type, label, decision_id) "
                        "VALUES (%s, 'income', 'human', 'Lohn', %s) RETURNING *", (client_id, decision_id)).fetchone()


def test_a_plan_insert_with_a_decision_in_the_same_transaction_is_accepted(st, make_client):
    c = make_client()
    with st.session() as conn:
        d = _decision(conn, c["id"])
        p = _position_sql(conn, c["id"], d)
    with st.session() as conn:
        links = conn.execute("SELECT decision_id FROM decision_position WHERE position_id = %s", (p["id"],)).fetchall()
    assert [l["decision_id"] for l in links] == [d]


def test_a_plan_insert_with_a_decision_from_another_transaction_is_refused(st, make_client):
    c = make_client()
    with st.session() as conn:
        old = _decision(conn, c["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="C-09"):
        with st.session() as conn:
            _position_sql(conn, c["id"], old)


def test_a_plan_insert_naming_no_decision_is_refused(st, make_client):
    c = make_client()
    with pytest.raises((psycopg.errors.RaiseException, psycopg.errors.NotNullViolation)):
        with st.session() as conn:
            conn.execute("INSERT INTO position (client_id, role, capital_type, label) VALUES (%s, 'income', 'human', 'x')",
                         (c["id"],))
    with pytest.raises(psycopg.errors.RaiseException, match="does not exist"):
        with st.session() as conn:
            _position_sql(conn, c["id"], "0" * 32)


def test_an_update_needs_a_new_decision(st, make_client):
    c = make_client()
    with st.session() as conn:
        p = plan_position(conn, c["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="C-09"):
        with st.session() as conn:
            conn.execute("UPDATE position SET magnitude = 1 WHERE id = %s", (p["id"],))
    with st.session() as conn:
        d = _decision(conn, c["id"])
        conn.execute("UPDATE position SET magnitude = 1, decision_id = %s WHERE id = %s", (d, p["id"]))
    with st.session() as conn:
        n = conn.execute("SELECT count(*) AS n FROM decision_position WHERE position_id = %s", (p["id"],)).fetchone()["n"]
    assert n == 2, "both decisions are recorded as having covered the row"


@pytest.mark.parametrize("table", ["position", "goal", "household", "household_member", "client_fact"])
def test_plan_rows_are_never_deleted(st, make_client, table):
    c = make_client()
    with st.session() as conn:
        with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="q", choice="c")) as ch:
            hh = ch.insert("household", composition_as_of=TODAY, stated_by="client")
            rows = {
                "position": ch.insert("position", client_id=c["id"], role="income", capital_type="human", label="x"),
                "goal": ch.insert("goal", client_id=c["id"], name="Ziel"),
                "household": hh,
                "household_member": ch.insert("household_member", household_id=hh["id"], client_id=c["id"],
                                              label="ich", kind="adult"),
                "client_fact": ch.state_fact(client_id=c["id"], stated_key="canton", stated_value="Zug",
                                             stated_on=TODAY, stated_by="client"),
            }
    with pytest.raises(psycopg.errors.RaiseException, match="never deleted"):
        with st.session() as conn:
            with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="q",
                                                           choice="delete")):
                conn.execute(f"DELETE FROM {table} WHERE id = %s", (rows[table]["id"],))


def test_the_decision_must_belong_to_the_same_client(st, make_client):
    a, b = make_client(), make_client()
    with pytest.raises(psycopg.errors.RaiseException, match="belongs to client"):
        with st.session() as conn:
            d = _decision(conn, a["id"])
            _position_sql(conn, b["id"], d)


def test_a_caller_cannot_forge_the_transaction_id(st, make_client):
    c = make_client()
    with st.session() as conn:
        old = conn.execute("SELECT txid_current() AS t").fetchone()["t"]
    with st.session() as conn:
        d = conn.execute("INSERT INTO decision (client_id, author, question, choice, txid) "
                         "VALUES (%s, 'client', 'q', 'c', %s) RETURNING txid", (c["id"], old)).fetchone()
        now = conn.execute("SELECT txid_current() AS t").fetchone()["t"]
    assert d["txid"] == now != old


def test_goal_funding_needs_a_decision_linked_to_the_goal(st, make_client):
    c = make_client()
    with st.session() as conn:
        p = plan_position(conn, c["id"])
        with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="q", choice="c")) as ch:
            g = ch.insert("goal", client_id=c["id"], name="Ziel")
    with pytest.raises(psycopg.errors.RaiseException, match="C-09"):
        with st.session() as conn:
            _decision(conn, c["id"])    # a decision in this transaction, but not linked to the goal
            conn.execute("INSERT INTO goal_funding (goal_id, position_id) VALUES (%s, %s)", (g["id"], p["id"]))
    with st.session() as conn:
        with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="fund", choice="ja")) as ch:
            ch.set_goal_funding(g["id"], p["id"])
        with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="unfund", choice="nein")) as ch:
            ch.set_goal_funding(g["id"], p["id"], active=False)
    with st.session() as conn:
        assert conn.execute("SELECT active FROM goal_funding WHERE goal_id = %s", (g["id"],)).fetchone()["active"] is False


def test_a_decision_cannot_be_linked_after_its_transaction(st, make_client):
    c = make_client()
    with st.session() as conn:
        p = plan_position(conn, c["id"])
        d = _decision(conn, c["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="same transaction"):
        with st.session() as conn:
            conn.execute("INSERT INTO decision_position (decision_id, position_id) VALUES (%s, %s)", (d, p["id"]))


def test_plan_change_nested_in_an_open_transaction_uses_the_top_level_transaction(st, make_client):
    c = make_client()
    with st.session() as conn:
        conn.execute("SELECT 1")
        with conn.transaction():                 # an outer savepoint the caller opened
            p = plan_position(conn, c["id"])
    with st.session() as conn:
        assert conn.execute("SELECT count(*) AS n FROM position WHERE id = %s", (p["id"],)).fetchone()["n"] == 1


def test_one_current_fact_per_key(st, make_client):
    c = make_client()
    with st.session() as conn:
        for canton in ("Bern", "Zug"):
            with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="Kanton?",
                                                           choice=canton)) as ch:
                ch.state_fact(client_id=c["id"], stated_key="canton", stated_value=canton, stated_on=TODAY,
                              stated_by="client")
        facts = conn.execute("SELECT stated_value, superseded_on FROM client_fact WHERE client_id = %s "
                             "ORDER BY created_at", (c["id"],)).fetchall()
    assert [f["stated_value"] for f in facts] == ["Bern", "Zug"]
    assert facts[0]["superseded_on"] == TODAY and facts[1]["superseded_on"] is None


def test_the_curator_writes_a_plan_change_directly(settings, make_client, make_curator):
    """The cockpit's path: decision and plan row in one transaction, as role curator, qualified names."""
    c, cur = make_client(), make_curator()
    s = settings.database.schema
    with connect(settings, as_curator=True, search_path=False) as conn:
        with conn.transaction():
            d = conn.execute(f"INSERT INTO {s}.decision (client_id, author, author_ref, question, choice) "
                             f"VALUES (%s, 'curator', %s, 'Lohn erfassen?', 'Ja') RETURNING id",
                             (c["id"], cur["id"])).fetchone()["id"]
            conn.execute(f"INSERT INTO {s}.position (client_id, role, capital_type, label, decision_id) "
                         f"VALUES (%s, 'income', 'human', 'Lohn', %s)", (c["id"], d))
        with pytest.raises(psycopg.errors.RaiseException, match="C-09"):
            with conn.transaction():
                conn.execute(f"UPDATE {s}.position SET label = 'x' WHERE client_id = %s", (c["id"],))


def test_a_plan_row_cannot_move_to_another_client(st, make_client):
    a, b = make_client(), make_client()
    with st.session() as conn:
        p = plan_position(conn, a["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be changed"):
        with st.session() as conn:
            d = _decision(conn, b["id"])
            conn.execute("UPDATE position SET client_id = %s, decision_id = %s WHERE id = %s", (b["id"], d, p["id"]))
