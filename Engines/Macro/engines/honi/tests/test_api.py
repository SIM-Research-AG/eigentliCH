"""The HTTP surface, against a real store in a throwaway schema and a mock datafeed."""

from __future__ import annotations

import pytest

from honi.calibration import DEFAULT
from honi.contracts import CONTRACT_VERSIONS, INDICES, NOTICE, HoNIScores

from .conftest import RAW_ID


@pytest.fixture(scope="module")
def SNAPSHOT(datafeed) -> str:
    """The production input: datafeed's filled snapshot."""
    return datafeed["filled"]


@pytest.fixture(scope="module")
def first_run(client, SNAPSHOT):
    r = client.post("/run", json={"snapshot_id": SNAPSHOT})
    assert r.status_code == 200, r.text
    return r.json()


class TestStandardEndpoints:
    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok" and body["engine_version"] == "honi@1.1.0"
        assert body["uptime_s"] >= 0

    def test_meta_reports_versions_and_the_allowlist(self, client):
        body = client.get("/meta").json()
        assert body["contract_versions"] == CONTRACT_VERSIONS
        assert body["calibration_version"] == "1.1.0"
        assert {"1.1.0", "1.0.0", "0.1.0-matlab"} <= set(body["calibration_versions"])
        assert body["allowlist"]["ok"] is True
        assert body["allowlist"]["packages"]["psycopg"]["admitted_by"].startswith("D-05")

    def test_the_password_never_leaves_the_engine(self, client, settings):
        text = client.get("/meta").text
        assert settings.database.password and settings.database.password not in text

    def test_contracts_publish_a_schema_for_every_model(self, client):
        body = client.get("/contracts").json()
        assert body["HoNIScores"]["version"] == "honi-scores@1.1.0"
        assert body["Panel"]["direction"] == "in"
        assert all("properties" in v["schema"] for v in body.values())

    def test_calibration_defaults_to_the_active_version(self, client):
        assert client.get("/calibration").json()["version"] == "1.1.0"
        assert client.get("/calibration", params={"version": "0.1.0-matlab"}).json()[
            "missing_policy"] == "score_worst"
        assert client.get("/calibration", params={"version": "7.7.7"}).status_code == 404


class TestRun:
    def test_a_run_succeeds_and_publishes_an_artefact(self, first_run):
        assert first_run["status"] == "succeeded" and first_run["cached"] is False
        assert first_run["artefact_id"].startswith("HNS-")
        assert first_run["idempotency_key"].startswith("IDK-")

    def test_re_running_is_free(self, client, first_run, SNAPSHOT):
        again = client.post("/run", json={"snapshot_id": SNAPSHOT}).json()
        assert again["cached"] is True
        assert again["run_id"] == first_run["run_id"]
        assert again["artefact_id"] == first_run["artefact_id"]

    def test_a_different_calibration_is_a_different_run(self, client, first_run, SNAPSHOT):
        other = client.post("/run", json={"snapshot_id": SNAPSHOT,
                                          "calibration_version": "0.1.0-matlab"}).json()
        assert other["idempotency_key"] != first_run["idempotency_key"]
        status = client.get(f"/runs/{other['run_id']}").json()
        assert any("not for publication" in w for w in status["warnings"])

    def test_run_status_carries_coverage_and_provenance(self, client, first_run):
        status = client.get(f"/runs/{first_run['run_id']}").json()
        assert status["status"] == "succeeded" and status["wall_clock_ms"] > 0
        assert status["coverage"]["country_years"] == 19 * 16
        prov = status["provenance"]
        assert prov["calibration_version"] == "1.1.0"
        assert prov["label"] == "model-derived" and prov["regime_id"] is None
        assert len(prov["upstream"]["datafeed:panel_sha256"]) == 64

    def test_the_artefact_is_the_contract(self, client, first_run):
        body = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        artefact = HoNIScores.model_validate(body)
        assert artefact.notice == NOTICE
        assert artefact.provenance.idempotency_key == first_run["idempotency_key"]
        assert len(artefact.years) == 19 and artefact.years[0] == 2007 and len(artefact.countries) == 16

    def test_a_missing_snapshot_is_a_failed_run_with_the_reason(self, client):
        accepted = client.post("/run", json={"snapshot_id": "no-such-snapshot"}).json()
        assert accepted["status"] == "failed" and accepted["artefact_id"] is None
        status = client.get(f"/runs/{accepted['run_id']}").json()
        assert "no snapshot" in status["error"]

    def test_a_window_outside_the_snapshot_fails_the_run(self, client, SNAPSHOT):
        accepted = client.post("/run", json={"snapshot_id": SNAPSHOT,
                                             "window": {"start_year": 1990, "end_year": 2000}}).json()
        assert accepted["status"] == "failed"
        assert "outside" in client.get(f"/runs/{accepted['run_id']}").json()["error"]

    @pytest.mark.parametrize("body, fragment", [
        ({"countries": ["US", "XX"]}, "unknown country"),
        ({"calibration_version": "8.8.8"}, "no calibration"),
    ])
    def test_a_bad_request_is_refused_before_any_run(self, client, body, fragment, SNAPSHOT):
        r = client.post("/run", json={"snapshot_id": SNAPSHOT, **body})
        assert r.status_code == 422 and fragment in r.text

    def test_an_unknown_field_is_refused(self, client, SNAPSHOT):
        assert client.post("/run", json={"snapshot_id": SNAPSHOT, "speed": "fast"}).status_code == 422

    def test_unknown_ids_are_404(self, client):
        assert client.get("/runs/RUN-0000000000000000").status_code == 404
        assert client.get("/artefacts/HNS-0000000000000000").status_code == 404


class TestDatafeedGate:
    def test_public_fills_are_reported(self, client, first_run):
        status = client.get(f"/runs/{first_run['run_id']}").json()
        fills = {(f["country"], f["series_id"]) for f in status["coverage"]["public_fills"]}
        assert ("BD", "production.gdp_nominal") in fills and ("VN", "consumer.household_consumption") in fills
        assert any("public sources" in w for w in status["warnings"])

    def test_implausible_inputs_are_excluded_not_scored_worst(self, client):
        """On the raw snapshot datafeed still flags consumption units; the gate drops the index."""
        run = client.post("/run", json={"snapshot_id": RAW_ID}).json()
        status = client.get(f"/runs/{run['run_id']}").json()
        excluded = {(e["country"], e["index"]) for e in status["coverage"]["excluded"]}
        assert {("IN", "consumption_dependency"), ("GB", "consumption_dependency")} <= excluded
        artefact = client.get(f"/artefacts/{run['artefact_id']}").json()
        j = [c["code"] for c in artefact["countries"]].index("GB")
        assert all(row[j] is None for row in artefact["index_scores"]["consumption_dependency"])

    def test_the_production_snapshot_needs_no_exclusion(self, client, first_run):
        """datafeed's DF-16 replacements put consumption in GDP's unit for all 16 countries."""
        status = client.get(f"/runs/{first_run['run_id']}").json()
        assert status["coverage"]["excluded"] == []
        artefact = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        scores = artefact["index_scores"]["consumption_dependency"]
        assert all(any(row[j] is not None for row in scores) for j in range(16))

    def test_calibration_1_0_0_has_no_gate(self, client, SNAPSHOT):
        r = client.post("/run", json={"snapshot_id": SNAPSHOT, "calibration_version": "1.0.0"}).json()
        assert client.get(f"/runs/{r['run_id']}").json()["coverage"]["excluded"] == []

    def test_the_raw_snapshot_has_no_public_fills(self, client):
        r = client.post("/run", json={"snapshot_id": RAW_ID}).json()
        assert client.get(f"/runs/{r['run_id']}").json()["coverage"]["public_fills"] == []


class TestEngineSpecificReads:
    def test_scores_is_the_national_matrix(self, client, first_run):
        body = client.get(f"/scores/{first_run['artefact_id']}").json()
        assert len(body["national"]) == 19 and all(len(r) == 16 for r in body["national"])
        assert body["notice"] == NOTICE

    def test_one_country(self, client, first_run):
        body = client.get(f"/scores/{first_run['artefact_id']}/countries/CH").json()
        assert body["country"] == {"code": "CH", "name": "Switzerland"}
        assert [i["index"] for i in body["indices"]] == list(INDICES)
        assert set(body["sectors"]) == {"financial", "international", "real"}
        assert client.get(f"/scores/{first_run['artefact_id']}/countries/XX").status_code == 404

    def test_saturation(self, client, first_run):
        body = client.get(f"/saturation/{first_run['artefact_id']}").json()
        assert len(body["capital_saturation"]) == 19

    def test_ranges_list_the_fifteen_triples(self, client):
        body = client.get("/ranges").json()
        assert len(body["indices"]) == 15
        debt = next(i for i in body["indices"] if i["index"] == "government_debt")
        assert debt["kind"] == "ramp" and debt["range"] == [1.2, 1.0, 0.3]

    def test_peer_stats_cover_every_index_year_and_basis(self, client, first_run):
        body = client.get(f"/peer-stats/{first_run['artefact_id']}").json()
        assert len(body["rows"]) == 15 * 19 * 2
        row = next(r for r in body["rows"] if r["basis"] == "score" and r["n"] > 1)
        assert row["min"] <= row["p25"] <= row["median"] <= row["p75"] <= row["max"]

    def test_trends_cover_every_published_series(self, client, first_run):
        body = client.get(f"/trends/{first_run['artefact_id']}?window=10").json()
        assert body["contract_version"] == "honi-trends@1.0.0"
        assert body["year"] == 2025 and body["base_year"] == 2015 and body["first_year"] == 2016
        keys = [s["key"] for s in body["series"]]
        assert keys[:5] == ["national", "financial", "international", "real", "capital_saturation"]
        assert len(keys) == 5 + 2 * 15 and len(set(keys)) == len(keys)
        national = body["series"][0]
        scores = client.get(f"/scores/{first_run['artefact_id']}").json()
        assert national["latest"] == scores["national"][-1], "latest is the published value, unchanged"
        assert all(len(s["slope"]) == 16 for s in body["series"])
        assert client.get(f"/trends/{first_run['artefact_id']}?year=2019&window=5").json()["base_year"] == 2014
        assert client.get(f"/trends/{first_run['artefact_id']}?year=1999").status_code == 422
        assert client.get(f"/trends/{first_run['artefact_id']}?window=2").status_code == 422
        assert client.get("/trends/HNS-nope").status_code == 404

    def test_the_test_bench_is_served_at_the_root(self, client):
        r = client.get("/")
        assert r.status_code == 200 and "Health of Nations" in r.text


class TestCalibrationVersions:
    def proposal(self, version: str, **changes) -> dict:
        body = DEFAULT.model_copy(update={"version": version, "parent_version": "1.0.0",
                                          "note": "test", **changes}).model_dump(mode="json")
        return body

    def test_a_proposal_creates_a_new_version(self, client):
        r = client.put("/calibration", json=self.proposal("1.6.0", min_indices_per_sector=4))
        assert r.status_code == 201 and r.json()["version"] == "1.6.0"
        assert client.get("/calibration").json()["version"] == "1.1.0", "proposing never activates"

    def test_proposing_the_identical_version_again_is_harmless(self, client):
        body = self.proposal("1.2.0")
        assert client.put("/calibration", json=body).status_code == 201
        assert client.put("/calibration", json=body).status_code == 200

    def test_a_used_version_cannot_be_changed(self, client):
        client.put("/calibration", json=self.proposal("1.3.0"))
        r = client.put("/calibration", json=self.proposal("1.3.0", rescale_national=False))
        assert r.status_code == 409

    def test_a_seed_cannot_be_overwritten(self, client):
        body = self.proposal("1.0.0", min_indices_per_sector=5)
        body["parent_version"] = None
        assert client.put("/calibration", json=body).status_code == 409

    def test_an_unknown_parent_is_refused(self, client):
        body = self.proposal("1.4.0")
        body["parent_version"] = "0.0.1"
        assert client.put("/calibration", json=body).status_code == 422

    def test_a_new_version_can_be_run(self, client, SNAPSHOT):
        client.put("/calibration", json=self.proposal("1.5.0", annualisation="mean"))
        r = client.post("/run", json={"snapshot_id": SNAPSHOT, "calibration_version": "1.5.0"}).json()
        assert r["status"] == "succeeded"
        versions = {v["version"]: v for v in client.get("/calibration/versions").json()}
        assert versions["1.1.0"]["active"] and not versions["1.5.0"]["active"]


def test_without_datafeed_a_run_is_refused_with_503(settings):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from honi.api import create_app
    offline = replace(settings, datafeed_url="http://127.0.0.1:9", datafeed_timeout_s=2)
    with TestClient(create_app(offline)) as c:
        r = c.post("/run", json={"snapshot_id": RAW_ID})
    assert r.status_code == 503 and "unreachable" in r.text


class TestModelCard:
    """GET /model: HoNI explained on one economy's data (model-card@1.0.0)."""

    @pytest.fixture(scope="class")
    def card(self, client):
        r = client.get("/model", params={"economy": "US"})
        assert r.status_code == 200, r.text
        return r.json()

    def test_it_names_the_inputs_the_steps_and_the_outputs(self, card):
        from honi.engine import REQUIRED_SERIES
        assert card["contract_version"] == "model-card@1.0.0" and "ModelCard" not in CONTRACT_VERSIONS
        assert [i["key"] for i in card["inputs"]] == list(REQUIRED_SERIES)
        assert all(i["name"] and i["unit"] for i in card["inputs"])
        assert [s["key"] for s in card["steps"]] == ["annual", "indicators", "scoring", "sectors",
                                                     "rescale", "national", "saturation"]
        indicators = next(s for s in card["steps"] if s["key"] == "indicators")
        assert len(indicators["charts"]) == len(INDICES)
        assert card["notice"] == NOTICE

    def test_its_numbers_are_the_runs_numbers(self, client, card):
        """The card runs the model on the default peer set; a normal run on the same snapshot
        must publish the same national and index scores for the economy."""
        snapshot = card["data"].split()[2]
        run = client.post("/run", json={"snapshot_id": snapshot}).json()
        a = client.get(f"/artefacts/{run['artefact_id']}").json()
        j = [c["code"] for c in a["countries"]].index("US")
        out = card["output_charts"][0]
        assert out["x"] == a["years"]
        assert out["series"][0]["y"] == [row[j] for row in a["national"]]
        heat = next(s for s in card["steps"] if s["key"] == "scoring")["charts"][0]
        for row, index in zip(heat["z"], INDICES):
            assert row == [r[j] for r in a["index_scores"][index]]

    def test_a_transfer_curve_passes_through_its_anchors(self, card):
        scoring = next(s for s in card["steps"] if s["key"] == "scoring")
        budget = scoring["charts"][1]      # budget_balance: ramp (-0.10, -0.035, 0)
        curve = dict(zip(budget["x"], budget["series"][0]["y"]))
        assert (curve[-0.1], curve[-0.035], curve[0.0]) == (1.0, 2.5, 5.0)

    def test_unknown_economy_is_refused(self, client):
        assert client.get("/model", params={"economy": "XX"}).status_code == 422
