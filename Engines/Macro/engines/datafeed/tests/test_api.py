"""The HTTP surface against a bootstrapped throwaway store."""

from __future__ import annotations

import pytest

from datafeed.contracts import CONTRACT_VERSIONS
from datafeed.etl.bootstrap import FROZEN_RAW, read_frozen

from .conftest import RAW_ID


class TestStandard:
    def test_health_and_meta(self, client, built):
        assert client.get("/health").json()["engine_version"] == "datafeed@1.0.0"
        meta = client.get("/meta").json()
        assert meta["contract_versions"] == CONTRACT_VERSIONS and meta["allowlist"]["ok"]
        assert meta["store"]["counts"]["snapshot"] == 3     # raw, filled, market (DF-18)
        assert built.database.password not in client.get("/meta").text

    def test_contracts(self, client):
        body = client.get("/contracts").json()
        assert body["Panel"]["version"] == "panel@1.1.0" and body["SnapshotIn"]["direction"] == "in"

    def test_calibration(self, client):
        cal = client.get("/calibration").json()
        assert cal["version"] == "1.0.0" and cal["annual_carry_months"] == 11
        body = {**cal, "version": "1.1.0", "parent_version": "1.0.0", "level_tolerance": 0.05}
        assert client.put("/calibration", json=body).status_code == 201
        assert client.put("/calibration", json=body).status_code == 200
        assert client.put("/calibration", json={**body, "rate_tolerance": 0.5}).status_code == 409

    def test_run_materialises_a_panel_and_caches_it(self, client):
        body = {"snapshot_id": RAW_ID, "series": ["inflation.cpi_yoy"], "countries": ["US", "CH"]}
        first = client.post("/run", json=body).json()
        again = client.post("/run", json=body).json()
        assert first["status"] == "succeeded" and again["cached"] and again["run_id"] == first["run_id"]
        panel = client.get(f"/artefacts/{first['artefact_id']}").json()
        assert [s["country"] for s in panel["series"]] == ["US", "CH"]
        status = client.get(f"/runs/{first['run_id']}").json()
        assert status["provenance"]["snapshot_id"] == RAW_ID

    def test_a_run_on_an_unknown_snapshot_is_404(self, client):
        assert client.post("/run", json={"snapshot_id": "nope"}).status_code == 404


class TestSnapshots:
    def test_listing_newest_first(self, client, filled_id):
        ids = [s["snapshot_id"] for s in client.get("/snapshots").json()]
        assert len(ids) == 3 and ids[1:] == [filled_id, RAW_ID]
        assert ids[0].startswith(filled_id + ".market-")

    def test_the_filled_manifest_lists_every_candidate(self, client, filled_id):
        m = client.get(f"/snapshots/{filled_id}").json()
        assert m["parent_id"] == RAW_ID and len(m["fills"]) == 17
        assert sum(f["accepted"] for f in m["fills"]) == 11

    def test_admin_ingest_is_off_without_a_token(self, client):
        assert client.post("/snapshots", json=read_frozen(FROZEN_RAW).model_dump(mode="json")).status_code == 403

    def test_admin_ingest_with_a_token(self, client, monkeypatch):
        monkeypatch.setenv("DATAFEED_ADMIN_TOKEN", "s3cret")
        raw = read_frozen(FROZEN_RAW).model_dump(mode="json")
        assert client.post("/snapshots", json=raw).status_code == 401
        assert client.post("/snapshots", json=raw, headers={"X-Admin-Token": "wrong"}).status_code == 401
        assert client.post("/snapshots", json=raw, headers={"X-Admin-Token": "s3cret"}).status_code == 200
        raw["note"] = "changed"
        raw["series"] = raw["series"][:-1]
        assert client.post("/snapshots", json=raw, headers={"X-Admin-Token": "s3cret"}).status_code == 409


class TestReads:
    def test_panel_filters(self, client):
        p = client.get("/panel", params=[("snapshot_id", RAW_ID), ("series", "yields.govt_10y"),
                                         ("countries", "US"), ("start", "2020-01-31"),
                                         ("end", "2020-12-31")]).json()
        assert len(p["dates"]) == 12 and len(p["series"]) == 1 and p["contract_version"] == "panel@1.1.0"

    def test_panel_carries_public_sources(self, client, filled_id):
        p = client.get("/panel", params=[("snapshot_id", filled_id), ("series", "production.gdp_nominal"),
                                         ("countries", "BD")]).json()
        sources = {s["source"] for s in p["series"][0]["source_spans"]}
        assert sources == {"bloomberg", "worldbank:NY.GDP.MKTP.CN"}

    @pytest.mark.parametrize("params, code", [
        ([("snapshot_id", "nope")], 404),
        ([("snapshot_id", RAW_ID), ("series", "not.a.series")], 422),
        ([("snapshot_id", RAW_ID), ("countries", "XX")], 422),
        ([("snapshot_id", RAW_ID), ("start", "2030-01-31")], 422),
    ])
    def test_bad_panel_requests(self, client, params, code):
        assert client.get("/panel", params=params).status_code == code

    def test_series_registry(self, client):
        defs = client.get("/series", params={"snapshot_id": RAW_ID, "index": "consumption_power"}).json()
        assert {d["series_id"] for d in defs} == {"consumer.wage_growth", "inflation.cpi_yoy"}
        one = client.get("/series/money.broad_money", params={"country": "US", "snapshot_id": RAW_ID}).json()
        assert one[0]["pull_code"] == "OEUSMBAH Index"
        assert client.get("/series/nope").status_code == 404

    def test_coverage_and_public(self, client, filled_id):
        cov = client.get("/coverage", params={"snapshot_id": filled_id}).json()
        assert len(cov["rows"]) == 16 * 44 and cov["plausibility"] == []
        assert len(client.get("/public").json()) == 21
