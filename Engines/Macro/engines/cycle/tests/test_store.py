"""The store and its configuration, tested directly."""

from __future__ import annotations

import os

import psycopg
import pytest

from cycle.calibration import DEFAULT, calibration_hash, canonical_json
from cycle.settings import ConfigError, load
from cycle.store import Store, put_artefact, put_calibration

#: Not representable in single precision: a REAL column would round it.
EXACTING = -0.18721989171442346


@pytest.fixture(scope="module")
def store(settings):
    s = Store(settings.database)
    s.initialise()
    return s


class TestSchema:
    def test_initialise_is_idempotent(self, store):
        store.initialise()
        store.initialise()

    def test_tables_live_in_the_engine_schema(self, store, settings):
        with store.session() as conn:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (settings.database.schema,)).fetchall()
        assert {r["table_name"] for r in rows} == {"calibration", "artefact", "run"}

    def test_no_column_is_single_precision(self, store, settings):
        with store.session() as conn:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND data_type = 'real'",
                (settings.database.schema,)).fetchall()
        assert rows == []

    def test_a_float_round_trips_exactly(self, store):
        with store.session() as conn:
            conn.execute("INSERT INTO run (run_id, idempotency_key, status, started_at, "
                         "request_json, wall_clock_ms) VALUES ('RUN-x', 'k', 'running', 't', '{}', %s)",
                         (EXACTING,))
            back = conn.execute("SELECT wall_clock_ms FROM run WHERE run_id = 'RUN-x'").fetchone()
        assert back["wall_clock_ms"] == EXACTING


class TestAppendOnly:
    def test_a_calibration_cannot_be_updated_or_deleted(self, store):
        with store.session() as conn:
            put_calibration(conn, version=DEFAULT.version, calibration_hash=calibration_hash(DEFAULT),
                            parent_version=None, payload_json=canonical_json(DEFAULT))
        for sql in ("UPDATE calibration SET payload_json = '{}'", "DELETE FROM calibration"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                with store.session() as conn:
                    conn.execute(sql)

    def test_an_artefact_cannot_be_updated_or_deleted(self, store):
        with store.session() as conn:
            put_artefact(conn, artefact_id="CYS-t", idempotency_key="IDK-t",
                         contract_version="cycle-scores@1.0.0", payload_json="{}")
        for sql in ("UPDATE artefact SET payload_json = '[]'", "DELETE FROM artefact"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                with store.session() as conn:
                    conn.execute(sql)

    def test_writing_the_same_artefact_twice_is_harmless(self, store):
        with store.session() as conn:
            put_artefact(conn, artefact_id="CYS-t", idempotency_key="IDK-t",
                         contract_version="cycle-scores@1.0.0", payload_json="{}")


class TestConfig:
    def test_the_url_never_shows_the_password(self, settings):
        assert settings.database.password not in settings.database.redacted_url()
        assert "password" not in settings.database.describe() or \
            settings.database.describe().get("password") is None

    @pytest.mark.parametrize("bad", ["cycle; DROP TABLE x", "1abc", "a-b", ""])
    def test_a_schema_must_be_a_plain_identifier(self, bad):
        with pytest.raises(ConfigError):
            load(overrides={"database": {"schema": bad}})

    def test_environment_beats_the_file(self, monkeypatch):
        monkeypatch.setenv("CYCLE_PORT", "9123")
        monkeypatch.setenv("CYCLE_DB_SCHEMA", "elsewhere")
        s = load()
        assert s.port == 9123 and s.database.schema == "elsewhere"
        assert "env: CYCLE_DB_SCHEMA" in s.sources

    def test_a_database_url_overrides_the_connection(self, monkeypatch):
        monkeypatch.setenv("CYCLE_DATABASE_URL",
                           "postgresql://u:p%40ss@db.example:6543/other?sslmode=require")
        db = load().database
        assert (db.host, db.port, db.dbname, db.user, db.password, db.sslmode) == \
            ("db.example", 6543, "other", "u", "p@ss", "require")

    def test_the_committed_config_holds_no_password(self):
        from cycle.settings import ROOT, _read_yaml

        assert "password" not in (_read_yaml(ROOT / "config.yaml").get("database") or {})

    def test_economies_must_be_unique(self):
        with pytest.raises(ConfigError, match="twice"):
            load(overrides={"run": {"economies": ["US", "US"]}})


def test_no_test_touches_the_real_schema(settings):
    assert settings.database.schema.startswith("t_")
    assert os.environ.get("CYCLE_DB_SCHEMA") is None
