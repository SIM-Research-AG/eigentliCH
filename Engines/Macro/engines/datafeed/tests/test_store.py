"""The store and its configuration, directly."""

from __future__ import annotations

import pytest

from datafeed.settings import ConfigError, load

EXACTING = -0.18721989171442346


def test_tables_live_in_the_engine_schema(service, built):
    with service.store.session() as conn:
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                            (built.database.schema,)).fetchall()
    assert {r["table_name"] for r in rows} == {
        "country", "series", "source_file", "public_fetch", "public_value", "market_fetch", "market_value",
        "snapshot",
        "series_definition", "observation", "series_conversion", "calibration", "artefact", "run"}


def test_no_column_is_single_precision(service, built):
    with service.store.session() as conn:
        assert conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = %s "
                            "AND data_type = 'real'", (built.database.schema,)).fetchall() == []


def test_a_float_round_trips_exactly(service):
    with service.store.session() as conn:
        conn.execute("INSERT INTO run (run_id, idempotency_key, status, started_at, request_json, "
                     "wall_clock_ms) VALUES ('RUN-p', 'k', 'running', 't', '{}', %s)", (EXACTING,))
        assert conn.execute("SELECT wall_clock_ms FROM run WHERE run_id = 'RUN-p'").fetchone()[
            "wall_clock_ms"] == EXACTING


def test_bootstrapping_twice_changes_nothing(built, service):
    from datafeed.etl.bootstrap import main
    before = [(s.snapshot_id, s.checksum) for s in service.snapshots()]
    assert main(["--frozen", "--offline"], built) == 0
    assert [(s.snapshot_id, s.checksum) for s in service.snapshots()] == before


class TestConfig:
    @pytest.mark.parametrize("bad", ["x; DROP", "1abc", ""])
    def test_a_schema_must_be_an_identifier(self, bad):
        with pytest.raises(ConfigError):
            load(overrides={"database": {"schema": bad}})

    def test_environment_beats_the_file(self, monkeypatch):
        monkeypatch.setenv("DATAFEED_PORT", "9111")
        monkeypatch.setenv("DATAFEED_DB_SCHEMA", "other")
        s = load()
        assert s.port == 9111 and s.database.schema == "other"

    def test_the_committed_config_holds_no_secret(self):
        from datafeed.settings import ROOT, _read_yaml
        tree = _read_yaml(ROOT / "config.yaml")
        assert "password" not in tree["database"]

    def test_a_fill_for_an_unknown_series_is_reported(self, built):
        from dataclasses import replace

        from datafeed.service import Service
        from datafeed.settings import FillSpec
        from datafeed.store import Store
        bad = replace(built, fills=(FillSpec(country="US", series="x.y", provider="worldbank", code="Z", mode="level"),))
        assert Service(bad, Store(bad.database)).check_fills() == ["fill US/x.y: unregistered country or series"]
