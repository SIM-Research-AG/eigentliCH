"""Versioned content: max+1 per key, under concurrency, from the backend and from the cockpit."""

from __future__ import annotations

import threading
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from eigentlich import store

from .conftest import connect, minimal_questionnaire


def _key() -> str:
    return f"reference/test-{uuid.uuid4().hex[:8]}"


def test_versions_count_up_and_record_who_saved(db, make_client, make_curator):
    key, c, cur = _key(), make_client(), make_curator()
    assert store.save_content(db, key=key, kind="reference", body={"a": 1}, saved_by_kind="seed", saved_by_ref="t") == 1
    assert store.save_content(db, key=key, kind="reference", body={"a": 2}, saved_by_kind="client",
                              saved_by_ref=c["id"]) == 2
    assert store.save_content(db, key=key, kind="reference", body={"a": 3}, saved_by_kind="curator",
                              saved_by_ref=cur["id"], note="Korrektur") == 3
    assert store.content_current(db, key)["body"] == {"a": 3}
    assert store.content_version(db, key, 1)["body"] == {"a": 1}
    assert [(h["version"], h["saved_by_kind"]) for h in store.content_history(db, key)] == \
        [(1, "seed"), (2, "client"), (3, "curator")]


def test_a_caller_chosen_version_must_be_the_next(db):
    key = _key()
    store.save_content(db, key=key, kind="reference", body={}, saved_by_kind="seed", saved_by_ref="t")
    with pytest.raises(psycopg.errors.RaiseException, match="next version is 2"):
        db.execute("INSERT INTO content_record (key, version, kind, body, saved_by_kind, saved_by_ref) "
                   "VALUES (%s, 5, 'reference', '{}', 'seed', 't')", (key,))


def test_the_kind_of_a_key_is_fixed(db):
    key = f"reference/test-{uuid.uuid4().hex[:8]}"
    store.save_content(db, key=key, kind="reference", body={}, saved_by_kind="seed", saved_by_ref="t")
    with pytest.raises(psycopg.errors.RaiseException, match="cannot make it knowledge"):
        store.save_content(db, key=key, kind="knowledge", body={"front_matter": {}, "markdown": ""},
                           saved_by_kind="seed", saved_by_ref="t")


@pytest.mark.parametrize("key,kind,body", [
    ("questionnaire/x", "questionnaire", {"no": "questions"}),
    ("scoring/x", "scoring_map", {"map": {}}),
    ("knowledge/x", "knowledge", {"markdown": "x"}),
    ("reference/x", "questionnaire", {"questions": []}),
    ("Reference/X", "reference", {}),
])
def test_body_shape_and_key_are_checked(db, key, kind, body):
    with pytest.raises(psycopg.errors.CheckViolation):
        store.save_content(db, key=key, kind=kind, body=body, saved_by_kind="seed", saved_by_ref="t")


def test_a_questionnaire_with_a_repeated_question_key_is_refused(db):
    body = minimal_questionnaire()
    body["questions"].append(dict(body["questions"][0]))
    with pytest.raises(psycopg.errors.RaiseException, match="repeated"):
        store.save_content(db, key=f"questionnaire/t-{uuid.uuid4().hex[:6]}", kind="questionnaire", body=body,
                           saved_by_kind="seed", saved_by_ref="t")


def test_a_client_or_curator_save_must_name_a_real_one(db):
    with pytest.raises(psycopg.errors.RaiseException, match="no client"):
        store.save_content(db, key=_key(), kind="reference", body={}, saved_by_kind="client", saved_by_ref="nobody")


def test_concurrent_saves_queue_and_number_without_gaps(settings, st):
    """Twelve saves to one key from twelve connections at once: versions 1..12, none lost, none failed."""
    key, n = _key(), 12
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    versions: list[int] = []
    lock = threading.Lock()

    def save(i: int) -> None:
        try:
            with connect(settings) as conn:
                barrier.wait(timeout=20)
                v = conn.execute("SELECT save_content(%s, 'reference', %s, 'seed', 't') AS v",
                                 (key, Jsonb({"i": i}))).fetchone()["v"]
                conn.commit()
            with lock:
                versions.append(v)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    assert sorted(versions) == list(range(1, n + 1))
    with st.session() as conn:
        assert conn.execute("SELECT count(*) AS n FROM content_record WHERE key = %s", (key,)).fetchone()["n"] == n


def test_the_curator_saves_a_questionnaire_version(settings, db, make_curator):
    cur = make_curator()
    s = settings.database.schema
    key = f"questionnaire/c-{uuid.uuid4().hex[:6]}"
    store.save_content(db, key=key, kind="questionnaire", body=minimal_questionnaire(), saved_by_kind="seed",
                       saved_by_ref="t")
    db.commit()
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        body = conn.execute(f"SELECT body FROM {s}.content_current WHERE key = %s", (key,)).fetchone()["body"]
        body["questions"][0]["question"]["de"] = "In welchem Kanton wohnen Sie?"
        v = conn.execute(f"SELECT {s}.save_content(%s, 'questionnaire', %s, 'curator', %s, 'Wortlaut') AS v",
                         (key, Jsonb(body), cur["id"])).fetchone()["v"]
    assert v == 2
