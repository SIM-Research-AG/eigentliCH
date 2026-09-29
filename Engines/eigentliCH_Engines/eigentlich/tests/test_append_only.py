"""Append-only tables refuse UPDATE and DELETE, whoever asks; mutable records change only where allowed."""

from __future__ import annotations

import psycopg
import pytest

from eigentlich import store

from . import world

#: (table, key column, world key, a column to try to change)
APPEND_ONLY = [
    ("decision", "id", "decision", "choice"),
    ("content_record", "key", "questionnaire", "note"),
    ("thread_message", "id", "message", "body"),
    ("approval_event", "id", "approval_event", "note"),
    ("approval_request", "id", "approval_request", "note"),
    ("curator_session_event", "id", "session_event", "actor"),
    ("curator_session", "id", "session", "opened_from"),
    ("parameter_set", "id", "parameter_set", "note"),
    ("report", "id", "report", "body_html"),
    ("submission", "id", "submission", "note"),
    ("migration_run", "id", "migration_run", "source_path"),
    ("decision_position", "position_id", "position", "data_class"),
    ("decision_goal", "goal_id", "goal", "data_class"),
    ("decision_household", "household_id", "household", "data_class"),
    ("decision_household_member", "household_member_id", "household_member", "data_class"),
    ("decision_client_fact", "client_fact_id", "fact", "data_class"),
]


@pytest.fixture(scope="module")
def w(st):
    return world.build(st)


@pytest.mark.parametrize("table,key,ref,column", APPEND_ONLY, ids=[a[0] for a in APPEND_ONLY])
def test_update_is_refused(st, w, table, key, ref, column):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with st.session() as conn:
            value = "3" if column == "data_class" else "changed"
            conn.execute(f"UPDATE {table} SET {column} = %s WHERE {key} = %s", (value, w[ref]))


@pytest.mark.parametrize("table,key,ref,column", APPEND_ONLY, ids=[a[0] for a in APPEND_ONLY])
def test_delete_is_refused(st, w, table, key, ref, column):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with st.session() as conn:
            conn.execute(f"DELETE FROM {table} WHERE {key} = %s", (w[ref],))


@pytest.mark.parametrize("table,ref", [("client", "client"), ("curator", "curator"), ("consent", "consent"),
                                       ("answer", "answer"), ("thread", "thread"), ("report_request", "report_request"),
                                       ("engine_run", "engine_run")])
def test_mutable_records_are_never_deleted(st, w, table, ref):
    with pytest.raises(psycopg.errors.RaiseException, match="never deleted"):
        with st.session() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = %s", (w[ref],))


@pytest.mark.parametrize("table,column,value", [
    ("client", "age_at_registration", 50), ("client", "created_by_kind", "curator"),
    ("curator", "fictional", True), ("consent", "purpose", "other"),
    ("answer", "value", '"Zug"'), ("thread", "client_id", None), ("report_request", "kind", "update"),
])
def test_immutable_columns_refuse_change(st, w, table, column, value):
    ref = {"client": "client", "curator": "curator", "consent": "consent", "answer": "answer", "thread": "thread",
           "report_request": "report_request"}[table]
    if column == "client_id":
        value = w["partner"]
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be changed"):
        with st.session() as conn:
            conn.execute(f"UPDATE {table} SET {column} = %s WHERE id = %s", (value, w[ref]))


def test_editable_columns_change_and_set_once_columns_set_once(st, w):
    with st.session() as conn:
        store.update_client(conn, w["client"], display_name="Neu", stage_hint="aufbau")
        store.withdraw_consent(conn, w["consent"])
    with pytest.raises(psycopg.errors.RaiseException, match="set once"):
        with st.session() as conn:
            store.withdraw_consent(conn, w["consent"])
