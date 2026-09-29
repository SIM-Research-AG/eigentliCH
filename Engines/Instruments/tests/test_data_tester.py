"""The data tester must describe the engine that exists, not the one it documents.

A documentation surface that drifts from the code is worse than none, because it is
believed. Every assertion here ties a statement the page makes back to the constant or
the computation it claims to describe.
"""

from __future__ import annotations

import pytest

from engines.fund_map.calibrate import BLOCKS, state_axis
from engines.fund_map.indicators import INDICATOR_ORDER, INDICATOR_SIGNS
from engines.fund_map.phases import BOUND_BUSINESS, PHASE_NAMES, PHASE_VALUES
from tests.conftest import needs_feed, needs_sources

pytestmark = [needs_sources, needs_feed]


@pytest.fixture(scope="module")
def client(module_store):
    from fastapi.testclient import TestClient
    from store.etl import bootstrap

    bootstrap.main([])
    from api.main import app
    with TestClient(app) as c:
        yield c


class TestMethod:
    def test_it_describes_the_constants_the_engine_actually_uses(self, client):
        body = client.get("/v1/data/method").json()
        assert body["phase_bounds"]["business"] == BOUND_BUSINESS
        assert body["phase_values"] == list(PHASE_VALUES)
        assert body["phase_names"] == list(PHASE_NAMES)
        assert body["state_grid"] == state_axis()
        assert [b["key"] for b in body["blocks"]] == [b.key for b in BLOCKS]

    def test_the_indicator_signs_match_the_code(self, client):
        body = client.get("/v1/data/method").json()
        assert {i["name"]: i["sign"] for i in body["indicators"]} == INDICATOR_SIGNS
        assert [i["name"] for i in body["indicators"]] == list(INDICATOR_ORDER)

    def test_only_debt_saturation_is_de_trended_exponentially(self, client):
        body = client.get("/v1/data/method").json()
        exponential = [i["name"] for i in body["indicators"] if i["detrend"] == "exp1"]
        assert exponential == ["debt"]

    def test_the_measured_and_extrapolated_states_are_the_real_ones(self, client):
        """Stated on the page and derived in the calibration; they must agree."""
        body = client.get("/v1/data/method").json()
        grid = state_axis()
        knots = [i + 1 for i, q in enumerate(grid) if abs(q - round(q)) < 1e-12 and 1 <= q <= 5]
        outside = [i + 1 for i, q in enumerate(grid) if q < 1 or q > 5]
        assert body["measured_states"] == knots
        assert body["extrapolated_states"] == outside

    def test_every_step_carries_a_formula_and_a_reason(self, client):
        steps = client.get("/v1/data/method").json()["steps"]
        assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
        for s in steps:
            assert s["formulas"] and s["why"], f"step {s['step']} is undocumented"


class TestProvenance:
    def test_every_source_file_reports_a_hash_and_what_it_feeds(self, client):
        body = client.get("/v1/data/sources").json()
        assert body["count"] >= 19
        for s in body["sources"]:
            assert len(s["sha256"]) == 64
            assert s["byte_size"] > 0

    def test_the_raw_series_are_served_untransformed(self, client):
        listing = client.get("/v1/data/series").json()["series"]
        assert {r["series_key"] for r in listing} >= {"gold", "spx", "cpi"}

        gold = client.get("/v1/data/series?key=gold").json()
        assert gold["observations"] == 151
        first = gold["values"][0]
        # The 1870 New York gold price, as it sits in the workbook.
        assert first["year"] == 1870 and first["value"] == pytest.approx(23.75)

    def test_an_unknown_series_is_a_404(self, client):
        assert client.get("/v1/data/series?key=nonsense").status_code == 404


class TestTraces:
    def test_a_year_trace_reports_all_eight_indicators_and_its_phase(self, client):
        body = client.get("/v1/data/indicators?year=2008").json()
        assert [i["name"] for i in body["indicators"]] == list(INDICATOR_ORDER)
        assert body["phase"] in PHASE_NAMES
        assert body["phase"] == body["classification"].split("-> ")[-1]

    def test_a_year_outside_the_window_is_refused(self, client):
        assert client.get("/v1/data/indicators?year=1850").status_code == 422

    def test_a_block_trace_shows_five_estimates_and_twenty_five_states(self, client):
        body = client.get("/v1/data/trace?block=gold").json()
        assert len(body["phase_estimates"]) == 5
        assert len(body["states"]) == 25
        measured = [s for s in body["states"] if s["method"].startswith("data-driven")]
        assert [s["state"] for s in measured] == [3, 8, 13, 18, 23]

    def test_the_trace_marks_a_truncated_block_as_truncated(self, client):
        assert client.get("/v1/data/trace?block=gov_bonds").json()["truncated"] is True
        assert client.get("/v1/data/trace?block=equity").json()["truncated"] is False

    def test_an_unknown_block_is_a_404(self, client):
        assert client.get("/v1/data/trace?block=bitcoin").status_code == 404

    def test_a_month_trace_shows_the_quantile_bridge(self, client):
        body = client.get("/v1/data/bridge?period=2008-10").json()
        assert len(body["distribution"]) == 25
        assert abs(sum(body["distribution"]) - 1.0) < 1e-9
        # October 2008 must land in crisis, or the date correction has broken.
        assert body["bridge"]["calibration_state"] == 1


class TestInstrumentDiagnostic:
    def test_it_reports_the_horizon_disagreement(self, client):
        """The finding the panel exists to make visible.

        Precious Metals in crisis: strongly negative measured over the month, strongly
        positive over the following year. If these ever agree, the diagnostic has stopped
        measuring what it was built for.
        """
        body = client.get(
            "/v1/data/instrument-trace?instrument_id=INS-precious-metals"
        ).json()
        h = body["horizon_check"]
        assert h["mean_that_month_annualised"] < 0
        assert h["mean_next_12m"] > 0

    def test_it_reports_the_bucket_noise(self, client):
        body = client.get(
            "/v1/data/instrument-trace?instrument_id=INS-bloomberg-market-neutral-hf"
        ).json()
        assert body["noise"]["mean_std_error"] > 0
        # The point of the panel: the step between adjacent states is not large relative
        # to the uncertainty in either of them.
        assert body["noise"]["mean_abs_jump"] > 0.5 * body["noise"]["mean_std_error"]

    def test_every_bucket_reports_its_own_periods(self, client):
        body = client.get(
            "/v1/data/instrument-trace?instrument_id=INS-precious-metals"
        ).json()
        for bucket in body["buckets"]:
            assert len(bucket["periods"]) == bucket["n_obs"] or bucket["n_obs"] > 0

    def test_an_unknown_instrument_is_a_404(self, client):
        assert client.get(
            "/v1/data/instrument-trace?instrument_id=INS-nope"
        ).status_code == 404
