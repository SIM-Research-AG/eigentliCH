"""Migration of the real prototype SQLite file into a throwaway schema, reconciled against the file itself."""

from __future__ import annotations

import sqlite3

import pytest

from eigentlich import migrate, seed, store

from .conftest import drop_schema, make_schema


def _source_counts(path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return {t.source: conn.execute(f'SELECT count(*) FROM "{t.source}"').fetchone()[0] for t in migrate.MIGRATED}
    finally:
        conn.close()


@pytest.fixture(scope="module")
def migrated(settings, st):
    before = migrate.sha256(settings.migrate_from)
    with st.session() as conn:
        seed.seed(conn, settings.prototype_root)
    with st.session() as conn:
        report = migrate.migrate(conn, settings.migrate_from)
    return {"report": report, "sha_before": before}


def test_every_migrated_table_holds_exactly_the_source_rows(settings, db, migrated):
    counts = _source_counts(settings.migrate_from)
    target = store.table_counts(db)
    for t in migrate.MIGRATED:
        assert target[t.target] == counts[t.source], t.source
    assert counts["members"] == 83 and counts["decisions"] == 518 and counts["onboarding_answers"] == 547


def test_the_reconciliation_lists_every_source_table(settings, migrated):
    conn = sqlite3.connect(f"file:{settings.migrate_from.as_posix()}?mode=ro", uri=True)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                        "AND name NOT LIKE 'sqlite_%'")}
    conn.close()
    rows = migrated["report"]["tables"]
    assert {r["source"] for r in rows} == names
    for r in rows:
        if r["target"]:
            assert r["source_count"] == r["migrated"] == r["target_total"] and r["skipped"] == 0
        else:
            assert r["migrated"] == 0 and r["skipped"] == r["source_count"] and r["reason"]


def test_the_source_file_is_untouched(settings, migrated):
    assert migrate.sha256(settings.migrate_from) == migrated["sha_before"]


def test_migrated_decisions_carry_the_migration_transaction(db, migrated):
    run = db.execute("SELECT txid FROM migration_run").fetchone()
    txids = db.execute("SELECT DISTINCT txid, origin FROM decision").fetchall()
    assert [(t["txid"], t["origin"]) for t in txids] == [(run["txid"], "migration")]
    assert run["txid"] == migrated["report"]["txid"]


def test_every_plan_row_names_a_decision_that_covered_it(db, migrated):
    for table, link, col in (("position", "decision_position", "position_id"), ("goal", "decision_goal", "goal_id"),
                             ("household", "decision_household", "household_id"),
                             ("household_member", "decision_household_member", "household_member_id"),
                             ("client_fact", "decision_client_fact", "client_fact_id")):
        n = db.execute(f"SELECT count(*) AS n FROM {table} x WHERE NOT EXISTS (SELECT 1 FROM {link} l "
                       f"WHERE l.decision_id = x.decision_id AND l.{col} = x.id)").fetchone()["n"]
        assert n == 0, table


def test_members_become_clients_and_curators_lose_their_passwords(db, migrated):
    assert db.execute("SELECT count(*) AS n FROM decision WHERE author = 'member'").fetchone()["n"] == 0
    assert db.execute("SELECT count(*) AS n FROM client WHERE source_member_id = id AND created_by_kind = 'migration'"
                      ).fetchone()["n"] == 83
    cols = {r["column_name"] for r in db.execute("SELECT column_name FROM information_schema.columns "
                                                 "WHERE table_schema = current_schema() AND table_name = 'curator'")}
    assert not cols & {"password_hash", "password_salt", "iterations", "must_change"}
    assert db.execute("SELECT count(*) AS n FROM curator WHERE revoked_at IS NOT NULL").fetchone()["n"] == 3


def test_onboarding_answers_name_questionnaire_version_1(db, migrated):
    rows = db.execute("SELECT questionnaire_key, content_version, answered_by_kind, count(*) AS n FROM answer "
                      "GROUP BY 1, 2, 3").fetchall()
    assert [(r["questionnaire_key"], r["content_version"], r["answered_by_kind"], r["n"]) for r in rows] == \
        [("questionnaire/onboarding", 1, "migration", 547)]
    assert db.execute("SELECT count(*) AS n FROM answer WHERE question_key = 'health' AND data_class <> 3"
                      ).fetchone()["n"] == 0


def test_a_second_run_writes_nothing(settings, st, migrated):
    with st.session() as conn:
        before = store.table_counts(conn)
    with pytest.raises(migrate.AlreadyMigrated):
        with st.session() as conn:
            migrate.migrate(conn, settings.migrate_from)
    with st.session() as conn:
        assert store.table_counts(conn) == before


def test_a_migrated_plan_is_changed_like_any_other(db, migrated):
    """After migration C-09 holds as before: a change needs a new decision."""
    pos = db.execute("SELECT id, client_id FROM position LIMIT 1").fetchone()
    with store.plan_change(db, decision=store.Decision(client_id=pos["client_id"], author="curator",
                                                       question="Betrag?", choice="korrigiert")) as ch:
        ch.update("position", pos["id"], label="korrigiert")
    db.rollback()


def test_a_non_empty_target_is_refused(settings):
    other = make_schema()
    try:
        st = store.Store(other.database)
        with st.session() as conn:
            seed.seed(conn, other.prototype_root)
            store.create_client(conn, display_name="Schon da", age_at_registration=30)
        with pytest.raises(migrate.MigrationError, match="not empty"):
            with st.session() as conn:
                migrate.migrate(conn, other.migrate_from)
        with st.session() as conn:
            assert conn.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 0
    finally:
        drop_schema(other)


def test_a_target_without_seeded_content_is_refused(settings):
    other = make_schema()
    try:
        with pytest.raises(migrate.MigrationError, match="seed"):
            with store.Store(other.database).session() as conn:
                migrate.migrate(conn, other.migrate_from)
    finally:
        drop_schema(other)


def test_an_unknown_source_table_fails_the_run(settings, tmp_path):
    import shutil
    copy = tmp_path / "copy.db"
    shutil.copyfile(settings.migrate_from, copy)
    conn = sqlite3.connect(copy)
    conn.execute("CREATE TABLE surprise (x int)")
    conn.commit()
    conn.close()
    with pytest.raises(migrate.MigrationError, match="surprise"):
        migrate.classify(migrate.open_source(copy))
