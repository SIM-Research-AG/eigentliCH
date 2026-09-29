"""The HTTP surface against a real PostgreSQL store and a real (bootstrapped) datafeed.

A production run reads datafeed's market layer, the default snapshot of these settings; a
``matlab`` run reads the raw snapshot. Nothing here talks to the live datafeed on 8001.
"""

from __future__ import annotations

import math

import psycopg
import pytest

from mrs.contracts import INDICATORS, SEGMENTS, MarketRiskSignal

from .conftest import RAW_ID


def _run(client, **body):
    r = client.post("/run", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def first(client):
    return _run(client)


@pytest.fixture(scope="module")
def signal(client, first) -> dict:
    return client.get(f"/artefacts/{first['artefact_id']}").json()


def test_health_meta_contracts(client):
    assert client.get("/health").json()["engine"] == "mrs"
    meta = client.get("/meta").json()
    assert meta["allowlist"]["ok"] is True
    assert meta["calibration_version"] == "2.0.0"
    assert set(meta["calibration_versions"]) == {"2.0.0", "2.0.0-matlab"}
    contracts = client.get("/contracts").json()
    assert contracts["MarketRiskSignal"]["version"] == "mrs-signal@1.0.0"
    assert contracts["MRSRunRequest"] == {**contracts["MRSRunRequest"], "version": "mrs-run@2.0.0",
                                          "direction": "in"}
    assert "TAASignal(taa)" not in contracts and "Regime" not in contracts


def test_run_succeeds_and_is_cached(client, first, settings):
    assert set(first) == {"run_id", "status", "artefact_id", "idempotency_key", "cached"}
    assert first["status"] == "succeeded" and first["cached"] is False
    assert first["artefact_id"].startswith("MRS-") and len(first["artefact_id"]) == 20
    again = _run(client, snapshot_id=settings.snapshot_id, calibration_version="2.0.0")
    assert again["cached"] is True and again["artefact_id"] == first["artefact_id"]
    assert again["run_id"] == first["run_id"]


def test_the_artefact_is_the_contract(signal, datafeed):
    s = MarketRiskSignal.model_validate(signal)
    assert s.contract_version == "mrs-signal@1.0.0" and s.n_states == 25
    assert s.indicator_names == INDICATORS and s.segment_names == SEGMENTS
    assert len(s.dates) == 241 and s.dates[0] == "2006-01-31" and s.dates[-1] == "2026-01-31"
    assert len(s.economies) == 16
    us = s.economy("US")
    assert us.name == "United States"
    p = s.provenance
    assert p.regime_id is None and p.label == "model-derived"
    assert p.snapshot_id == datafeed["market"] and p.calibration_version == "2.0.0"
    assert set(p.upstream) == {"datafeed"} and len(p.upstream["datafeed"]) == 64
    assert "Not investment advice" in s.notice
    for key in ("markets", "optimism_scale", "regime_id"):
        assert key not in signal
    # The artefact id is the content hash of the payload.
    from mrs.service import content_id
    draft = MarketRiskSignal.model_validate({**signal, "artefact_id": "MRS-draft"})
    assert content_id("MRS", draft.model_dump(mode="json")) == s.artefact_id


def test_production_signal_reads_sensibly(signal):
    s = MarketRiskSignal.model_validate(signal)
    cov = {e.code: e for e in s.coverage.economies}
    assert s.coverage.indicator_mode == "production" and s.coverage.missing_policy == "reweight"
    us = s.economy("US")
    # Warm-up: nothing before 24 + 12 + 12 months; the last month is assessed.
    assert all(v is None for v in us.state[:45]) and us.state[-1] is not None
    assert cov["US"].first_assessed is not None and cov["US"].last_assessed == s.dates[-1]
    for e in s.economies:
        for d in e.distribution:
            assert d is None or abs(math.fsum(d) - 1.0) <= 1e-12
    # BD and VN have no BIS effective exchange rate; that shows in coverage, not as zeros.
    assert "fx.neer_broad" in cov["BD"].inputs_missing
    assert "yields.high_yield_ytw" not in cov["US"].inputs_missing


def test_runs_listing_is_newest_first(client, first, settings):
    matlab = _run(client, snapshot_id=RAW_ID, calibration_version="2.0.0-matlab")
    assert matlab["status"] == "succeeded", client.get(f"/runs/{matlab['run_id']}").json()
    rows = client.get("/runs", params={"limit": 5}).json()
    assert rows[0]["run_id"] == matlab["run_id"]
    assert set(rows[0]) == {"run_id", "status", "artefact_id", "snapshot_id",
                            "calibration_version", "finished_at"}
    assert rows[0]["snapshot_id"] == RAW_ID and rows[0]["calibration_version"] == "2.0.0-matlab"
    assert any(r["run_id"] == first["run_id"] for r in rows)
    assert len(client.get("/runs", params={"limit": 1}).json()) == 1
    s = MarketRiskSignal.model_validate(client.get(f"/artefacts/{matlab['artefact_id']}").json())
    assert s.coverage.indicator_mode == "matlab"
    assert all(e.dates_unassessed == 0 for e in s.coverage.economies)
    status = client.get(f"/runs/{matlab['run_id']}").json()
    assert any("for reconciliation" in w for w in status["warnings"])


def test_run_status_carries_coverage_and_provenance(client, first, settings):
    status = client.get(f"/runs/{first['run_id']}").json()
    assert status["status"] == "succeeded" and status["artefact_id"] == first["artefact_id"]
    assert status["snapshot_id"] == settings.snapshot_id
    assert status["provenance"]["regime_id"] is None
    assert status["coverage"]["economies"]


def test_signal_endpoints(client, first, signal):
    aid = first["artefact_id"]
    d = client.get(f"/signal/{aid}/distribution", params={"economy": ["US", "CH"]}).json()
    assert d["date"] == signal["dates"][-1] and set(d["economies"]) == {"US", "CH"}
    us = d["economies"]["US"]
    assert abs(sum(us["distribution"]) - 1.0) < 1e-12 and 1 <= us["state"] <= 25
    early = client.get(f"/signal/{aid}/distribution", params={"date": signal["dates"][0]}).json()
    assert all(v["distribution"] is None for v in early["economies"].values())

    seg = client.get(f"/signal/{aid}/segments", params={"economy": "US"}).json()
    assert list(seg["economies"]) == ["US"] and set(seg["economies"]["US"]) == set(SEGMENTS)
    assert len(seg["economies"]["US"]["business_cycle"]) == len(signal["dates"])

    current = client.get(f"/signal/{aid}/current").json()
    assert len(current["economies"]) == 16
    row = next(e for e in current["economies"] if e["code"] == "US")
    assert row["date"] == signal["dates"][-1] and set(row["segments"]) == set(SEGMENTS)
    assert "Not investment advice" in current["notice"]


def test_not_found(client, first):
    aid = first["artefact_id"]
    assert client.get("/artefacts/MRS-0000000000000000").status_code == 404
    assert client.get("/runs/RUN-nope").status_code == 404
    assert client.get(f"/signal/{aid}/distribution", params={"date": "1999-01-31"}).status_code == 404
    assert client.get(f"/signal/{aid}/segments", params={"economy": "XX"}).status_code == 404
    assert client.get("/signal/MRS-0000000000000000/current").status_code == 404


def test_unknown_snapshot_is_404_and_recorded(client):
    r = client.post("/run", json={"snapshot_id": "no-such-snapshot"})
    assert r.status_code == 404 and "no-such-snapshot" in r.json()["detail"]
    failed = client.get("/runs", params={"limit": 1}).json()[0]
    assert failed["status"] == "failed" and failed["snapshot_id"] == "no-such-snapshot"


def test_production_on_the_raw_snapshot_fails_loudly(client):
    """The raw snapshot has no Cboe SKEW or BIS NEER: the production calibration refuses it."""
    r = _run(client, snapshot_id=RAW_ID, calibration_version="2.0.0")
    assert r["status"] == "failed" and r["artefact_id"] is None
    error = client.get(f"/runs/{r['run_id']}").json()["error"]
    assert "volatility.skew" in error


def test_old_requests_are_refused(client):
    r = client.post("/run", json={"macro_artefact_id": "MFS-x", "taa_artefact_id": "TAA-x"})
    assert r.status_code == 422
    r = client.post("/run", json={"optimism_scale": "rogue"})
    assert r.status_code == 422


def test_unknown_calibration_is_a_request_error(client):
    assert client.post("/run", json={"calibration_version": "7.7.7"}).status_code == 422


def test_calibration_put_is_versioned_and_immutable(client):
    base = client.get("/calibration").json()
    proposal = {**base, "version": "2.1.0", "parent_version": "2.0.0", "min_segments": 4,
                "note": "all four segments required"}
    assert client.put("/calibration", json=proposal).status_code == 201
    assert client.put("/calibration", json=proposal).status_code == 200
    assert client.put("/calibration", json={**proposal, "min_segments": 2}).status_code == 409
    assert client.get("/calibration", params={"version": "2.1.0"}).json()["min_segments"] == 4
    versions = {v["version"]: v for v in client.get("/calibration/versions").json()}
    assert versions["2.0.0"]["active"] and not versions["2.1.0"]["active"]
    assert client.put("/calibration", json={**proposal, "version": "2.2.0",
                                            "optimism": {"default": 0.4}}).status_code == 422


def test_store_is_append_only(client, first, settings):
    schema = settings.database.schema
    with psycopg.connect(settings.database.conninfo(), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(f"DELETE FROM {schema}.artefact WHERE artefact_id = %s",
                         (first["artefact_id"],))
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(f"UPDATE {schema}.calibration SET created_at = 'x'")


def test_no_single_precision_columns(client, settings):
    with psycopg.connect(settings.database.conninfo()) as conn:
        rows = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND data_type = 'real'", (settings.database.schema,)).fetchall()
    assert rows == []


def test_every_table_states_its_purpose(client, settings):
    with psycopg.connect(settings.database.conninfo()) as conn:
        rows = conn.execute(
            "SELECT c.relname, obj_description(c.oid, 'pg_class') FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r'", (settings.database.schema,)).fetchall()
    assert rows and all(purpose for _, purpose in rows)


def test_a_v010_store_is_refused_until_rebuilt(settings):
    """init-db --rebuild: drops this engine's tables in its own schema and recreates them."""
    import uuid
    from dataclasses import replace

    from mrs.service import Service
    from mrs.store import Store, StoreError
    from mrs.clients import DatafeedClient

    schema = f"t_{uuid.uuid4().hex[:12]}"
    cfg = replace(settings.database, schema=schema)
    try:
        with psycopg.connect(cfg.conninfo(), autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
            conn.execute(f"CREATE TABLE {schema}.artefact (artefact_id TEXT PRIMARY KEY, "
                         "regime_id TEXT NOT NULL)")
        store = Store(cfg)
        service = Service(replace(settings, database=cfg), store, DatafeedClient(settings.datafeed_url))
        with pytest.raises(StoreError, match="--rebuild"):
            service.startup()
        assert "artefact" in store.rebuild()
        service.startup()
        assert store.stale() is None
    finally:
        with psycopg.connect(cfg.conninfo(), autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


# ---- the model card -----------------------------------------------------------

def test_model_card_names_every_step(client):
    r = client.get("/model", params={"economy": "US"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["contract_version"] == "model-card@1.0.0"
    assert [s["key"] for s in card["steps"]] == ["standardise", "business_cycle", "investment", "market_behaviour",
                                                 "market_stress", "segments", "binning", "kernels", "distribution"]
    assert all(i["name"] and i["unit"] for i in card["inputs"])
    assert all(f.strip() for s in card["steps"] for f in s["formulas"])


def test_model_card_numbers_are_the_runs_numbers(client, signal):
    """The card runs the engine for one economy on the default snapshot; a normal run on it
    must publish the same segments and states for that economy."""
    card = client.get("/model", params={"economy": "US"}).json()
    us = next(e for e in signal["economies"] if e["code"] == "US")
    segments = next(s for s in card["steps"] if s["key"] == "segments")["charts"][0]
    assert segments["x"] == signal["dates"]
    for series, name in zip(segments["series"], SEGMENTS):
        assert series["y"] == us["segments"][name]
    states = card["output_charts"][0]["series"][0]["y"]
    assert states == [None if s is None else float(s) for s in us["state"]]


def test_model_card_unknown_economy_is_refused(client):
    assert client.get("/model", params={"economy": "XX"}).status_code == 422
