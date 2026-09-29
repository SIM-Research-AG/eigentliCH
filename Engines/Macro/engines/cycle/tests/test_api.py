"""The HTTP surface, against a real store in a throwaway schema and a live datafeed."""

from __future__ import annotations

import pytest

from cycle.contracts import CONTRACT_VERSIONS, NOTICE, PHASES, CycleState


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
        assert body["status"] == "ok" and body["engine_version"] == "cycle@1.0.0"

    def test_meta_reports_versions_and_the_allowlist(self, client):
        body = client.get("/meta").json()
        assert body["contract_versions"] == CONTRACT_VERSIONS
        assert body["calibration_version"] == "1.3.0"
        assert {"1.0.0", "1.1.0", "1.2.0", "1.3.0"} <= set(body["calibration_versions"])
        assert body["allowlist"]["ok"] is True
        assert body["allowlist"]["packages"]["psycopg"]["admitted_by"].startswith("C-02")

    def test_the_password_never_leaves_the_engine(self, client, settings):
        text = client.get("/meta").text
        assert settings.database.password and settings.database.password not in text

    def test_contracts_publish_a_schema_for_every_model(self, client):
        body = client.get("/contracts").json()
        assert body["CycleState"]["version"] == "cycle-state@1.2.0"
        assert body["CycleRunRequest"]["direction"] == "in"
        assert all("properties" in v["schema"] for v in body.values())

    def test_calibration(self, client):
        assert client.get("/calibration").json()["version"] == "1.3.0"
        assert client.get("/calibration", params={"version": "1.0.0"}).json()["parent_version"] is None
        assert client.get("/calibration", params={"version": "7.7.7"}).status_code == 404
        active = [v["version"] for v in client.get("/calibration/versions").json() if v["active"]]
        assert active == ["1.3.0"]


class TestRun:
    def test_a_run_succeeds_and_publishes_an_artefact(self, first_run):
        assert first_run["status"] == "succeeded" and first_run["cached"] is False
        assert first_run["artefact_id"].startswith("CYS-")

    def test_re_running_is_free(self, client, first_run, SNAPSHOT):
        again = client.post("/run", json={"snapshot_id": SNAPSHOT}).json()
        assert again["cached"] is True and again["artefact_id"] == first_run["artefact_id"]

    def test_fewer_economies_is_a_different_run(self, client, first_run, SNAPSHOT):
        other = client.post("/run", json={"snapshot_id": SNAPSHOT, "economies": ["US", "CH"]}).json()
        assert other["status"] == "succeeded" and other["idempotency_key"] != first_run["idempotency_key"]
        a = client.get(f"/artefacts/{other['artefact_id']}").json()
        assert [e["code"] for e in a["economies"]] == ["US", "CH"]

    def test_run_status_carries_coverage_provenance_and_warnings(self, client, first_run, SNAPSHOT):
        status = client.get(f"/runs/{first_run['run_id']}").json()
        assert status["status"] == "succeeded" and status["wall_clock_ms"] > 0
        assert status["coverage"]["economies"] == 16
        assert status["provenance"]["snapshot_id"] == SNAPSHOT
        assert status["provenance"]["upstream"]["datafeed:panel_sha256"]
        assert status["provenance"]["upstream"]["macrofield:artefact"] == "MFS-6183873b127fcd58"
        assert status["coverage"]["unidentified"] == []       # 1.1.0 places every cycle
        assert status["provenance"]["calibration_version"] == "1.3.0"

    def test_the_artefact_validates_and_carries_the_notice(self, client, first_run):
        body = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        a = CycleState.model_validate(body)
        assert a.notice == NOTICE and len(a.cycles) == 5

    def test_naming_the_macrofield_artefact_is_the_same_run(self, client, first_run, SNAPSHOT):
        named = client.post("/run", json={"snapshot_id": SNAPSHOT,
                                          "macrofield_artefact_id": "MFS-6183873b127fcd58"}).json()
        assert named["cached"] is True and named["artefact_id"] == first_run["artefact_id"]
        other = client.post("/run", json={"snapshot_id": SNAPSHOT, "macrofield_artefact_id": "MFS-none"}).json()
        assert other["status"] == "failed"

    def test_1_0_0_ignores_macrofield(self, client, SNAPSHOT):
        r = client.post("/run", json={"snapshot_id": SNAPSHOT, "calibration_version": "1.0.0", "project": False}).json()
        prov = client.get(f"/runs/{r['run_id']}").json()["provenance"]
        assert not any(k.startswith("macrofield:") for k in prov["upstream"])

    def test_the_artefact_is_projected_to_macrofields_horizon(self, client, first_run):
        a = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        assert a["observed_until"] == 2025 and a["projected_until"] == 2039 and a["years"][-1] == 2039
        status = client.get(f"/runs/{first_run['run_id']}").json()
        assert status["provenance"]["upstream"]["macrofield:projection_horizon"] == "2039"

    def test_project_false_is_another_run_without_a_projection(self, client, first_run, SNAPSHOT):
        r = client.post("/run", json={"snapshot_id": SNAPSHOT, "project": False}).json()
        assert r["idempotency_key"] != first_run["idempotency_key"]
        a = client.get(f"/artefacts/{r['artefact_id']}").json()
        assert a["projected_until"] is None and a["years"][-1] == a["observed_until"]

    def test_unknown_inputs_are_refused(self, client):
        assert client.post("/run", json={"snapshot_id": "nope"}).json()["status"] == "failed"
        assert client.post("/run", json={"snapshot_id": "x", "economies": ["ZZ"]}).status_code == 422
        assert client.post("/run", json={"snapshot_id": "x", "calibration_version": "7.7.7"}).status_code == 422
        assert client.get("/artefacts/CYS-0000").status_code == 404


class TestCycleEndpoints:
    def test_cycles(self, client, first_run):
        body = client.get(f"/cycles/{first_run['artefact_id']}").json()
        assert body["cycles"] == ["fundamental_pulse", "business", "credit", "innovation", "capital"]
        assert body["phase_order"] == list(PHASES)
        us = next(e for e in body["economies"] if e["code"] == "US")
        assert len(us["cycles"]) == 5 and len(us["cycles"][0]["phase"]) == len(body["years"])

    def test_current(self, client, first_run):
        body = client.get(f"/cycles/{first_run['artefact_id']}/current").json()
        assert body["year"] == 2025
        us = next(e for e in body["economies"] if e["code"] == "US")
        assert {c["cycle"]: c["year"] for c in us["cycles"]}["business"] == 2024   # macrofield ends 2024
        for e in body["economies"]:
            innovation = next(c for c in e["cycles"] if c["cycle"] == "innovation")
            assert innovation["phase"] == "contraction" and innovation["year"] == 2025
            capital = next(c for c in e["cycles"] if c["cycle"] == "capital")
            assert capital["phase"] is not None and capital["confidence"] == "supplied"
            credit = next(c for c in e["cycles"] if c["cycle"] == "credit")
            assert credit["phase"] is not None and credit["confidence"] == "supplied"

    def test_unknown_artefact(self, client):
        assert client.get("/cycles/CYS-0000/current").status_code == 404


class TestCalibrationProposals:
    def test_propose_is_append_only(self, client):
        cal = client.get("/calibration").json()
        new = {**cal, "version": "1.3.1", "parent_version": "1.3.0", "skew_coefficient": 0.0}
        assert client.put("/calibration", json=new).status_code == 201
        assert client.put("/calibration", json=new).status_code == 200
        assert client.put("/calibration", json={**new, "skew_coefficient": 0.1}).status_code == 409
        assert client.put("/calibration", json={**new, "version": "1.0.2", "parent_version": "9.9.9"}
                          ).status_code == 422


class TestModelCard:
    """GET /model: the model explained on one economy's data (model-card@1.0.0)."""

    @pytest.fixture(scope="class")
    def card(self, client):
        r = client.get("/model", params={"economy": "US"})
        assert r.status_code == 200, r.text
        return r.json()

    def test_it_names_the_inputs_the_steps_and_the_outputs(self, card):
        assert card["contract_version"] == "model-card@1.0.0" and "ModelCard" not in CONTRACT_VERSIONS
        assert card["economy"]["code"] == "US" and any(o["code"] == "US" for o in card["economies"])
        keys = [i["key"] for i in card["inputs"]]
        assert keys[:6] == ["production.gdp_nominal", "inflation.cpi_yoy", "debt.corporate_gdp",
                            "debt.government_gdp", "debt.household_gdp", "debt.financial_sector"]
        assert "macrofield.Y" in keys, "the active calibration reads macrofield's output"
        steps = [s["key"] for s in card["steps"]]
        assert steps == ["annual", "saturation", "growth", "bandpass", "anchored", "levels", "phases",
                         "superposition", "layer"]
        assert all(s["text"] and all(f.strip() for f in s["formulas"]) for s in card["steps"])
        assert card["outputs"] and card["output_charts"]
        assert card["notice"] == NOTICE

    def test_its_numbers_are_the_runs_numbers(self, client, card):
        """The card re-runs the engine for one economy; it must agree with a normal run on the
        same snapshot, cell for cell."""
        snapshot = card["data"].split()[2]
        run = client.post("/run", json={"snapshot_id": snapshot, "economies": ["US"]}).json()
        a = client.get(f"/artefacts/{run['artefact_id']}").json()
        us = a["economies"][0]
        levels = next(s for s in card["steps"] if s["key"] == "levels")["charts"][0]
        assert levels["x"] == a["years"]
        for series, track in zip(levels["series"], us["cycles"]):
            assert series["y"] == track["level"]
        mean = card["output_charts"][0]["series"][0]["y"]
        assert mean == us["layer_mean_bin"]

    def test_a_distribution_in_the_card_sums_to_one(self, card):
        layer = next(s for s in card["steps"] if s["key"] == "layer")
        mix = next(x for x in layer["charts"][0]["series"] if x["name"] == "Mix")
        assert abs(sum(mix["y"]) - 1.0) < 1e-12 and len(mix["y"]) == 25

    def test_unknown_economy_is_refused(self, client):
        assert client.get("/model", params={"economy": "XX"}).status_code == 422


class TestAggregateOnTheBench:
    """R-004: the bench's aggregate line is the published field, read from GET /artefacts/{id}."""

    def test_the_artefact_carries_the_aggregate_and_its_anchored_continuation(self, client, first_run):
        a = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        assert a["contract_version"] == "cycle-state@1.2.0"
        years = a["years"]
        for e in a["economies"]:
            full = [y for y, v in zip(years, e["superposition"]) if v is not None]
            assert full and full[-1] <= a["observed_until"], e["code"]
            assert e["anchored_members"] == ["credit", "innovation", "capital"], e["code"]
            assert e["superposition_anchored"][-1] is not None and len(e["superposition_anchored"]) == len(years)

    def test_it_matches_the_engine_to_the_stored_precision(self, client):
        """The model card runs engine.py for one economy; the artefact the bench reads must carry
        the same numbers, float for float."""
        card = client.get("/model", params={"economy": "US"}).json()
        snapshot = card["data"].split()[2]
        run = client.post("/run", json={"snapshot_id": snapshot, "economies": ["US"]}).json()
        us = client.get(f"/artefacts/{run['artefact_id']}").json()["economies"][0]
        chart = next(s for s in card["steps"] if s["key"] == "superposition")["charts"][0]
        series = {s["name"]: s["y"] for s in chart["series"]}
        assert series["Superposition"] == us["superposition"]
        assert series["Anchored cycles only"] == us["superposition_anchored"]

    def test_the_bench_plots_the_published_fields_unaltered(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / "testbench" / "index.html").read_text(encoding="utf-8")
        body = html[html.index("function aggregateTraces"):html.index("function renderCycles")]
        assert 'y: e.superposition, name: "aggregate"' in body
        assert "e.superposition_anchored.map((v, i) => i > after ? v : null)" in body
        assert "y: e.alignment" in html and "e.synchrony_windows.map" in html


class TestStoredVersions:
    """C-26: a stored artefact is served as it was published. The fixture is a real stored
    ``cycle-state@1.1.0`` artefact of the ``cycle`` schema (28.09.2026), trimmed to US and CN."""

    @pytest.fixture(scope="class")
    def stored(self, client, settings):
        import json
        from pathlib import Path

        from cycle import store as st
        from cycle.store import Store
        frozen = json.loads((Path(__file__).resolve().parent.parent / "golden"
                             / "cycle_state_1.1.0_CYS-c6a5185ec9c743a0.json").read_text(encoding="utf-8"))
        payload = frozen["payload"]
        assert payload["contract_version"] == "cycle-state@1.1.0"
        assert "superposition_anchored" not in payload["economies"][0]
        with Store(settings.database).session() as conn:
            st.put_artefact(conn, artefact_id=payload["artefact_id"], idempotency_key="IDK-stored-1.1.0",
                            contract_version=payload["contract_version"], payload_json=json.dumps(payload))
        return payload

    def test_a_1_1_0_artefact_reads_back_unchanged(self, client, stored):
        r = client.get(f"/artefacts/{stored['artefact_id']}")
        assert r.status_code == 200, r.text
        assert r.json() == stored

    def test_the_cycle_views_read_it_too(self, client, stored):
        assert client.get(f"/cycles/{stored['artefact_id']}").status_code == 200
        current = client.get(f"/cycles/{stored['artefact_id']}/current")
        assert current.status_code == 200 and current.json()["year"] == stored["observed_until"]

    def test_a_new_run_publishes_1_2_0(self, client, first_run):
        a = client.get(f"/artefacts/{first_run['artefact_id']}").json()
        assert a["contract_version"] == "cycle-state@1.2.0" and "superposition_anchored" in a["economies"][0]
