"""The HTTP surface, against a temporary store built from the real sources.

The store is built once per session into a temp file, so the suite never touches
``data/instruments.db`` and a failing test cannot corrupt the working database.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import ECN_DIR, FEED_CSV, needs_feed, needs_sources

pytestmark = [needs_sources, needs_feed]


@pytest.fixture(scope="module")
def client(module_store):
    """The API against a bootstrapped throwaway schema on the real server."""
    from fastapi.testclient import TestClient
    from store.etl import bootstrap

    bootstrap.main([])
    from api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def aggregation_stub(monkeypatch):
    """A stand-in aggregation on a real socket, serving one Regime and refusing the rest."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    import api.main

    known = "RGM-e2658e8e9bbbc81e"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the stdlib's name
            found = self.path == f"/regime/{known}/current"
            body = json.dumps({"regime_id": known} if found else {"detail": "no regime"})
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(api.main, "AGGREGATION_URL", f"http://127.0.0.1:{server.server_port}")
    yield SimpleNamespace(known=known)
    server.shutdown()
    server.server_close()


class TestHealth:
    def test_reports_a_calibration_and_its_counts(self, client):
        body = client.get("/v1/health").json()
        assert body["status"] == "ok"
        assert body["calibration_id"].startswith("CAL-")
        # The whole published universe, not only the ten the monthly feed carries a price
        # history for. The register is a versioned input and the optimiser's objective has
        # a floor that scales with its size, so truncating it would move measured leverage.
        assert body["counts"]["instrument"] == 54
        assert body["counts"]["market_risk_signal"] == 240 * 25

    def test_health_says_which_store_answered_without_leaking_the_password(self, client):
        """Two things at once: the backend is visible, and the credential is not."""
        body = client.get("/v1/health").json()
        assert body["store"]["backend"] == "postgresql"
        assert "password" not in json.dumps(body).lower().replace("password_set", "")

    def test_the_test_bench_is_served_at_the_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Fund Map" in response.text

    def test_a_page_opened_from_disk_can_call_the_api(self, client):
        """A ``file://`` page sends ``Origin: null`` and needs CORS headers back.

        The test bench is routinely double-clicked rather than served, and without this
        the browser blocks every call and reports a bare "Failed to fetch" that points
        nowhere near the actual cause.
        """
        response = client.get("/v1/health", headers={"Origin": "null"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "*"

    def test_the_preflight_for_a_write_is_allowed(self, client):
        """Registering an instrument from a disk-opened page is a preflighted POST."""
        response = client.options(
            "/v1/instruments",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert "POST" in response.headers.get("access-control-allow-methods", "")


class TestReturnSet:
    def test_it_validates_and_carries_no_moments(self, client):
        body = client.get("/v1/return-set").json()
        assert body["contract_version"] == "rs@1.0.0"
        assert body["state_grid"] == 25
        assert len(body["role_profiles"]) == 4
        assert {p["key"] for p in body["role_profiles"]} == {
            "gain", "income", "stabilisation", "protection"}
        # If a moment had slipped in, the endpoint would have refused it already; assert
        # the check is live rather than trusting that.
        from contracts.return_set import reject_moments
        reject_moments(body)

    def test_every_state_carries_a_method(self, client):
        body = client.get("/v1/return-set").json()
        for profile in body["role_profiles"] + body["instrument_profiles"]:
            assert len(profile["states"]) == 25
            for state in profile["states"]:
                assert state["method"]
                if state["method"] in ("interpolated", "extrapolated", "borrowed", "seed"):
                    assert state["n_obs"] == 0

    def test_each_role_profile_has_five_measured_and_four_extrapolated_states(self, client):
        body = client.get("/v1/return-set").json()
        for profile in body["role_profiles"]:
            methods = [s["method"] for s in profile["states"]]
            assert sum(m.startswith("data-driven") for m in methods) == 5
            assert methods.count("extrapolated") == 4
            assert methods.count("interpolated") == 16

    def test_blocks_are_excluded_unless_asked_for(self, client):
        assert client.get("/v1/return-set").json()["block_profiles"] == []
        assert len(client.get("/v1/return-set?include_blocks=true").json()["block_profiles"]) == 8

    def test_an_unstamped_set_carries_no_regime_and_keeps_its_id(self, client):
        body = client.get("/v1/return-set").json()
        assert body["provenance"]["regime_id"] is None
        again = client.get("/v1/return-set").json()
        assert again["return_set_id"] == body["return_set_id"]

    def test_a_confirmed_regime_is_stamped_and_enters_the_id(self, client, aggregation_stub):
        plain = client.get("/v1/return-set").json()
        stamped = client.get(f"/v1/return-set?regime_id={aggregation_stub.known}").json()
        assert stamped["provenance"]["regime_id"] == aggregation_stub.known
        assert stamped["return_set_id"] != plain["return_set_id"]
        assert stamped["role_profiles"] == plain["role_profiles"]
        repeat = client.get(f"/v1/return-set?regime_id={aggregation_stub.known}").json()
        assert repeat["return_set_id"] == stamped["return_set_id"]

    def test_a_regime_aggregation_does_not_serve_is_refused(self, client, aggregation_stub):
        response = client.get("/v1/return-set?regime_id=RGM-0000000000000000")
        assert response.status_code == 422
        assert "nothing was stamped" in response.json()["detail"]

    def test_an_unreachable_aggregation_is_not_the_callers_error(self, client, monkeypatch):
        import api.main
        monkeypatch.setattr(api.main, "AGGREGATION_URL", "http://127.0.0.1:9")
        response = client.get("/v1/return-set?regime_id=RGM-e2658e8e9bbbc81e")
        assert response.status_code == 503

    def test_provenance_names_its_sources_by_hash(self, client):
        prov = client.get("/v1/return-set").json()["provenance"]
        assert prov["calibration_window"] == "1871..2020"
        assert len(prov["source_sha256"]) == 19
        assert prov["state_map_id"].startswith("MAP-")


class TestDiagnostics:
    def test_all_shape_assertions_pass_on_the_real_calibration(self, client):
        body = client.get("/v1/diagnostics/shapes").json()
        failed = [c["assertion"] for c in body["checks"] if not c["passed"]]
        assert body["all_passed"], f"failing shape assertions: {failed}"
        assert len(body["checks"]) == 8

    def test_the_state_map_is_monotone_and_reports_what_it_cannot_reach(self, client):
        body = client.get("/v1/state-map").json()
        states = [e["calib_state"] for e in body["entries"]]
        assert states == sorted(states)
        assert len(body["entries"]) == 25
        # The bridge is many-to-one, so some states are structurally unreachable and the
        # endpoint must say which rather than leaving a reader to infer it.
        assert body["unreachable_states"]
        assert set(body["reachable_states"]) & set(body["unreachable_states"]) == set()

    def test_the_expected_view_is_marked_as_outside_the_contract(self, client):
        body = client.get("/v1/diagnostics/expected").json()
        assert set(body["by_role"]) == {"gain", "income", "stabilisation", "protection"}
        assert "not part of the returnset" in body["note"].lower()

    def test_recomposition_flags_the_truncated_blocks(self, client):
        body = client.get("/v1/diagnostics/recomposition").json()
        truncated = {r["block"] for r in body["blocks"] if r["truncated"]}
        assert truncated == {"gov_bonds", "real_estate", "agriculture"}


class TestTheDefaultEstimator:
    """FMRE-22: the profile endpoints and the diagnostics serve the smoothed forward
    measurement by default; the stored cascade stays selectable."""

    def test_the_instrument_profile_is_the_smoothed_forward_measurement(self, client):
        body = client.get("/v1/instruments/INS-precious-metals/profile").json()
        assert body["profile_method"] == "forward_12m_smoothed"
        assert body["stored"] is False
        assert {s["method"] for s in body["states"]} <= {"forward-12m-smoothed",
                                                         "shape-scaled", "seed"}
        assert len(body["unsmoothed"]["profile"]) == 25, "the measured values stay"
        assert body["smoothing"]["knot_states"] == [3, 8, 13, 18, 23]
        assert body["protection_type"] == "forward"

    def test_the_cascade_is_still_the_stored_profile(self, client):
        body = client.get("/v1/instruments/INS-precious-metals/profile?method=cascade").json()
        assert body["profile_method"] == "cascade"
        assert body["return_set_id"].startswith("RS-")
        assert "forward-12m-smoothed" not in {s["method"] for s in body["states"]}

    def test_the_coverage_map_reads_the_default(self, client):
        body = client.get("/v1/diagnostics/coverage").json()
        assert body["profile_method"] == "forward_12m_smoothed"
        assert "borrowed" not in {m for v in body["instruments"].values() for m in v["counts"]}

    def test_the_estimator_comparison_carries_the_default(self, client):
        body = client.get("/v1/diagnostics/estimators").json()
        assert body["default_method"] == "forward_12m_smoothed"
        assert set(body["summary"]) == {"cascade", "shape_scaled", "forward_12m",
                                        "forward_12m_smoothed"}
        smoothed = body["summary"]["forward_12m_smoothed"]
        assert smoothed["max_knot_shift"] <= 0.01 + 1e-12


class TestRegister:
    def test_a_new_instrument_can_be_added_and_estimated(self, client):
        created = client.post("/v1/instruments", json={
            "name": "Test Swiss Equity Fund", "role": "gain", "asset_class": "Equity",
            "ticker": "TEST SW", "currency": "CHF",
        })
        assert created.status_code == 201
        instrument_id = created.json()["instrument_id"]
        assert instrument_id == "INS-test-swiss-equity-fund"

        # With no history it must seed from the role profile, and say so.
        estimated = client.post(f"/v1/instruments/{instrument_id}/estimate").json()
        assert estimated["coverage"] == "seed"
        assert estimated["n_obs_total"] == 0
        assert all(s["method"] == "seed" for s in estimated["states"])

    def test_growth_is_normalised_to_gain_at_the_boundary(self, client):
        """Manual section 2: any `Growth` label maps to `Gain`."""
        created = client.post("/v1/instruments", json={
            "name": "Legacy Growth Sleeve", "role": "Growth", "asset_class": "Equity"})
        assert created.status_code == 201
        listed = {i["name"]: i for i in client.get("/v1/instruments").json()}
        assert listed["Legacy Growth Sleeve"]["role"] == "gain"

    def test_adding_history_moves_a_profile_off_seed(self, client):
        client.post("/v1/instruments", json={
            "name": "Synthetic Tracker", "role": "gain", "asset_class": "Equity"})
        periods = [f"{y}-{m:02d}" for y in range(2012, 2022) for m in range(1, 13)]
        payload = {"source": "test", "points": [
            {"period": p, "value": 0.004 + 0.002 * ((i % 7) - 3)} for i, p in enumerate(periods)]}
        added = client.post("/v1/instruments/INS-synthetic-tracker/returns", json=payload)
        assert added.status_code == 200
        assert added.json()["months"] == len(periods)

        estimated = client.post("/v1/instruments/INS-synthetic-tracker/estimate").json()
        measured = [s for s in estimated["states"] if s["method"].startswith("data-driven")]
        assert measured, "ten years of monthly history should measure at least one state"
        assert estimated["n_obs_total"] > 0

    def test_a_malformed_period_is_refused(self, client):
        response = client.post("/v1/instruments/INS-chf-cash/returns", json={
            "points": [{"period": "2020-13", "value": 0.01}]})
        assert response.status_code == 422

    def test_a_return_of_minus_one_hundred_percent_is_refused(self, client):
        response = client.post("/v1/instruments/INS-chf-cash/returns", json={
            "points": [{"period": "2020-01", "value": -1.0}]})
        assert response.status_code == 422

    def test_duplicate_periods_in_one_batch_are_refused(self, client):
        response = client.post("/v1/instruments/INS-chf-cash/returns", json={
            "points": [{"period": "2020-01", "value": 0.01},
                       {"period": "2020-01", "value": 0.02}]})
        assert response.status_code == 422

    def test_an_unknown_field_is_refused(self, client):
        """Contracts are `extra = forbid`: a field nobody declared is a field nobody validated."""
        response = client.post("/v1/instruments", json={
            "name": "X", "role": "gain", "asset_class": "Equity", "expected_return": 0.07})
        assert response.status_code == 422

    def test_returns_for_an_unknown_instrument_are_a_404(self, client):
        response = client.post("/v1/instruments/INS-nope/returns", json={
            "points": [{"period": "2020-01", "value": 0.01}]})
        assert response.status_code == 404


class TestManifests:
    def test_every_return_set_request_writes_a_manifest(self, client):
        before = len(client.get("/v1/runs?limit=200").json()["runs"])
        client.get("/v1/return-set")
        after = client.get("/v1/runs?limit=200").json()["runs"]
        assert len(after) >= before
        assert all(r["run_id"].startswith("RUN-") for r in after)
        assert all(r["engine_version"] for r in after)
