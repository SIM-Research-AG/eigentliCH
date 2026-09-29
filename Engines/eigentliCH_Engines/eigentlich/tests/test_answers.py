"""Answers name the version they answered; one is current per question; superseding is the only update."""

from __future__ import annotations

import threading

import psycopg
import pytest
from psycopg.types.json import Jsonb

from eigentlich import store

from .conftest import connect


def _put(conn, client_id, key, version, question="canton", value="Bern", by="client"):
    return store.put_answer(conn, client_id=client_id, questionnaire_key=key, content_version=version,
                            question_key=question, value=value, answered_by_kind=by, answered_by_ref=client_id)


def test_a_new_answer_supersedes_the_current_one(db, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    first = _put(db, c["id"], key, v, value="Bern")
    second = _put(db, c["id"], key, v, value="Zug")
    rows = store.get_answers(db, c["id"], key, include_history=True)
    assert [(r["id"], r["value"], r["superseded_by_id"]) for r in rows] == \
        [(first["id"], "Bern", second["id"]), (second["id"], "Zug", None)]
    assert [r["value"] for r in store.get_answers(db, c["id"], key)] == ["Zug"]


def test_two_current_answers_to_one_question_are_refused(db, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    _put(db, c["id"], key, v)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("INSERT INTO answer (client_id, questionnaire_key, content_version, question_key, value, "
                   "answered_by_kind, answered_by_ref) VALUES (%s, %s, %s, 'canton', %s, 'client', %s)",
                   (c["id"], key, v, Jsonb("Zug"), c["id"]))


def test_an_answer_names_a_question_of_that_version(db, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    with pytest.raises(psycopg.errors.RaiseException, match="has no question"):
        _put(db, c["id"], key, v, question="not_asked")


def test_an_answer_names_a_questionnaire(db, make_client):
    c = make_client()
    store.save_content(db, key="reference/answers-test", kind="reference", body={"x": 1}, saved_by_kind="seed",
                       saved_by_ref="t")
    with pytest.raises(psycopg.errors.RaiseException, match="not a questionnaire"):
        _put(db, c["id"], "reference/answers-test", 1)


def test_an_answer_to_an_older_version_stands(db, make_client, questionnaire):
    """The client opened version 1; a curator saved version 2 meanwhile. The answer names version 1."""
    c = make_client()
    key, v1 = questionnaire()
    body = store.content_current(db, key)["body"]
    v2 = store.save_content(db, key=key, kind="questionnaire", body=body, saved_by_kind="seed", saved_by_ref="t")
    a = _put(db, c["id"], key, v1)
    assert (v1, v2) == (1, 2) and a["content_version"] == 1


def test_the_question_class_raises_the_row_class(db, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    assert _put(db, c["id"], key, v, question="health", value=0.85)["data_class"] == 3
    assert _put(db, c["id"], key, v, question="income", value=90000)["data_class"] == 2


def test_the_value_of_an_answer_cannot_change(db, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    a = _put(db, c["id"], key, v)
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be changed"):
        db.execute("UPDATE answer SET value = '\"Zug\"' WHERE id = %s", (a["id"],))


def test_concurrent_answers_leave_exactly_one_current(settings, st, make_client, questionnaire):
    c = make_client()
    key, v = questionnaire()
    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def answer(i: int) -> None:
        try:
            with connect(settings) as conn:
                barrier.wait(timeout=20)
                _put(conn, c["id"], key, v, question="income", value=i)
                conn.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=answer, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    with st.session() as conn:
        rows = store.get_answers(conn, c["id"], key, include_history=True)
    assert len(rows) == n
    assert sum(r["superseded_at"] is None for r in rows) == 1
    assert sum(r["superseded_by_id"] is not None for r in rows) == n - 1


def test_the_curator_answers_on_the_clients_behalf(settings, make_client, make_curator, questionnaire):
    c, cur = make_client(), make_curator()
    key, v = questionnaire()
    s = settings.database.schema
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        row = conn.execute(f"INSERT INTO {s}.answer (client_id, questionnaire_key, content_version, question_key, value, "
                           f"answered_by_kind, answered_by_ref) VALUES (%s, %s, %s, 'health', '0.7', 'curator', %s) "
                           f"RETURNING data_class", (c["id"], key, v, cur["id"])).fetchone()
    assert row["data_class"] == 3
