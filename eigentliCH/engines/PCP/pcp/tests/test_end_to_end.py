"""End to end against the real published contracts, plus determinism.

These run against whatever the two upstream programmes have actually published, and skip when they have
not. That is deliberate: an end-to-end test built on fixtures proves the code paths join up but not that
the contracts agree, and the contracts agreeing is the thing most likely to break.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pcp.model.constraints import build_constraints
from pcp.model.objective import curve_objective
from pcp.model.optimiser_curve import solve_curve
from pcp.pipeline import PipelineError, diagnostics, prepare, run
from pcp.reporting import export_result, render_brief, result_payload

#: The suite's own fixture, not a demo client.
#:
#: This used to be `Beisheim_Beisheim_Mandate`, one of the institutional mandates seeded from the legacy
#: Controller workbook. Those were deleted on 2026-08-02 and this test broke, which exposed the real problem
#: rather than causing it: the Optimiser's end-to-end test depended on an artefact it did not own and which
#: nothing guaranteed would stay. `fixture_balanced.yaml` is hand-authored, stable across Regime republishes,
#: and exists for this test alone — see its header for why its target curve is 2%.
MANDATE = "fixture_balanced"


@pytest.fixture(scope="module")
def prepared(config, real_regime_dir, real_returnset_path, mandates_dir):
    try:
        return prepare(
            MANDATE,
            config,
            regime_dir=real_regime_dir,
            returnset_path=real_returnset_path,
            mandates_dir=mandates_dir,
        )
    except PipelineError as error:
        pytest.skip(f"the published contracts do not currently support a run: {error}")


@pytest.fixture(scope="module")
def result(config, prepared):
    return run(MANDATE, config, inputs=prepared)


class TestContractsAgree:
    def test_the_returnset_was_estimated_under_the_regime_being_optimised(self, prepared):
        """The binding rule. If this fails the two producers are out of step, which is the failure this
        whole wiring exercise exists to make impossible."""
        assert prepared.returnset.regime_id == prepared.regime.regime_id

    def test_the_regime_is_monthly_with_a_live_crisis_tail(self, prepared):
        assert prepared.regime.period == "M"
        assert prepared.regime.n_periods > 12
        assert prepared.regime.crisis_tail() > 0.0

    def test_every_universe_member_carries_its_classification(self, prepared):
        for block in prepared.blocks:
            assert block.region_geo
            assert block.region_scope
            assert block.currency
            assert block.asset_class
            assert block.home_scenario
            assert block.economic_phase

    def test_geography_and_signal_scope_are_not_the_same_field(self, prepared):
        """If the ReturnSet had merged them, every region_geo would be a scope value."""
        scopes = {"Europe", "Americas", "Asia", "Sino", "Global"}
        geographies = {b.region_geo for b in prepared.blocks}
        assert geographies - scopes, "region_geo looks like a signal scope, not a geography"

    def test_the_units_are_annualised_decimals(self, prepared):
        assert prepared.returnset.values_unit == "annualised_decimal"
        # Sanity on magnitude: a decimal profile stays well inside a factor of ten.
        assert np.abs(prepared.bb).max() < 5.0


class TestRun:
    def test_the_weights_sum_to_one_and_are_non_negative(self, result):
        weights = result.current.weights
        assert weights.sum() == pytest.approx(1.0)
        assert (weights >= -1e-9).all()

    def test_the_mandate_is_feasible(self, result):
        assert result.current.conditions_met == "yes"
        assert result.ok

    def test_every_constraint_is_satisfied(self, prepared, result):
        slack = prepared.system.b - prepared.system.a @ result.current.weights
        assert slack.min() > -1e-6, f"a constraint is violated by {-slack.min():.2e}"

    def test_the_position_cap_is_respected(self, prepared, result):
        assert result.current.weights.max() <= prepared.mandate.max_single_position + 1e-6

    def test_a_pinned_position_is_held_at_its_weight(self, prepared, result):
        for bb_id, pinned in prepared.mandate.fixed_allocations.items():
            position = list(result.current.bb_ids).index(bb_id)
            assert result.current.weights[position] == pytest.approx(pinned, abs=1e-6)

    def test_the_portfolio_map_totals_the_weights(self, result):
        assert result.current.portfolio_map.sum() == pytest.approx(1.0)

    def test_the_role_allocation_totals_the_weights(self, result):
        assert sum(result.current.role_allocation.values()) == pytest.approx(1.0)

    def test_every_stamp_is_present(self, result):
        for value in (
            result.regime_id, result.regime_timeline_id, result.return_set_id,
            result.returnset_model_version, result.universe_version, result.engine_version,
            result.idempotency_key, result.trace_id, result.as_of,
        ):
            assert value

    def test_the_solution_is_at_least_as_good_as_the_start_point(self, prepared, result):
        """A sanity check on the solve: the optimiser must improve on a feasible reference point."""
        n = len(prepared.blocks)
        reference = np.full(n, 1.0 / n)
        at_reference = curve_objective(
            reference, prepared.bb, prepared.mandate.target_curve, result.current.regime
        )
        assert result.current.objective_value <= at_reference + 1e-6


class TestDeterminism:
    def test_the_same_inputs_give_the_same_allocation(self, config, prepared):
        first = run(MANDATE, config, inputs=prepared)
        second = run(MANDATE, config, inputs=prepared)
        assert first.idempotency_key == second.idempotency_key
        assert first.trace_id == second.trace_id
        np.testing.assert_allclose(first.current.weights, second.current.weights, atol=0.0, rtol=0.0)

    def test_re_reading_the_inputs_gives_the_same_allocation(
        self, config, real_regime_dir, real_returnset_path, mandates_dir
    ):
        """Determinism must survive re-reading from disk, not only re-solving in memory."""
        first = run(
            MANDATE, config, regime_dir=real_regime_dir, returnset_path=real_returnset_path,
            mandates_dir=mandates_dir,
        )
        second = run(
            MANDATE, config, regime_dir=real_regime_dir, returnset_path=real_returnset_path,
            mandates_dir=mandates_dir,
        )
        assert first.idempotency_key == second.idempotency_key
        np.testing.assert_allclose(first.current.weights, second.current.weights)

    def test_the_solver_start_point_is_fixed(self, config, prepared):
        """Two solves from the fixed start must agree exactly, with no seeded randomness anywhere."""
        regime = prepared.regime.current()
        a = solve_curve(prepared.bb, prepared.mandate.target_curve, regime, prepared.system, config)
        b = solve_curve(prepared.bb, prepared.mandate.target_curve, regime, prepared.system, config)
        np.testing.assert_array_equal(a.raw_weights, b.raw_weights)


class TestBacktest:
    def test_a_backtest_solves_one_period_per_month(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, backtest_months=6)
        assert len(result.allocations) == 6
        assert [a.period for a in result.allocations] == list(prepared.regime.dates[-6:])

    def test_every_backtest_period_sums_to_one(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, backtest_months=4)
        for allocation in result.allocations:
            assert allocation.weights.sum() == pytest.approx(1.0)

    def test_a_request_longer_than_the_regime_is_clipped_and_reported(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, backtest_months=10_000)
        assert len(result.allocations) <= prepared.regime.n_periods
        assert any("ceiling" in note or "Regime covers" in note for note in result.notes)


class TestMeanVarianceComparison:
    def test_it_runs_and_is_labelled_a_comparison(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, optimiser="mv")
        assert result.optimiser == "mv"
        assert result.current.weights.sum() == pytest.approx(1.0)
        assert any("not the model of record" in note for note in result.notes)

    def test_it_says_its_covariance_is_not_a_time_series_covariance(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, optimiser="mv")
        assert any("time-series covariance" in note for note in result.notes)

    def test_it_respects_the_same_constraints(self, config, prepared):
        result = run(MANDATE, config, inputs=prepared, optimiser="mv")
        slack = prepared.system.b - prepared.system.a @ result.current.weights
        assert slack.min() > -1e-6

    def test_it_produces_a_different_allocation_from_the_curve_fit(self, config, prepared):
        """If the two agreed exactly the comparison would be telling us nothing."""
        curve = run(MANDATE, config, inputs=prepared, optimiser="curve")
        mv = run(MANDATE, config, inputs=prepared, optimiser="mv")
        assert not np.allclose(curve.current.weights, mv.current.weights, atol=1e-6)


class TestReporting:
    def test_the_payload_carries_the_stamps_and_the_disclaimer(self, config, prepared, result):
        payload = result_payload(result, config, diagnostics(prepared, result, config))
        header = payload["header"]
        for key in (
            "regime_id", "return_set_id", "engine_version", "idempotency_key", "trace_id",
            "universe_version", "values_unit", "disclaimer", "label",
        ):
            assert header[key]
        assert header["label"] == "model-derived"
        assert "not investment advice" in header["disclaimer"].lower()

    def test_the_payload_is_json_serialisable(self, config, prepared, result):
        payload = result_payload(result, config, diagnostics(prepared, result, config))
        json.dumps(payload)

    def test_a_backtest_payload_labels_every_path(self, config, prepared):
        backtested = run(MANDATE, config, inputs=prepared, backtest_months=3)
        payload = result_payload(backtested, config)
        assert payload["header"]["backtest_label"] == "model-derived"
        assert all(row["label"] == "model-derived" for row in payload["timeline"])

    def test_the_brief_reads_the_binding_condition_before_the_numbers(self, config, prepared, result):
        text = render_brief(result, config, diagnostics(prepared, result, config))
        assert text.index("Whether it is feasible") < text.index("The allocation")
        assert text.index("What binds") < text.index("The allocation")

    def test_the_brief_carries_the_disclaimer_and_the_label(self, config, prepared, result):
        text = render_brief(result, config, diagnostics(prepared, result, config))
        assert "not investment advice" in text.lower()
        assert "Model-derived" in text

    def test_export_writes_json_csv_and_brief(self, config, prepared, result, tmp_path):
        written = export_result(
            result, config, directory=tmp_path, diagnostics=diagnostics(prepared, result, config)
        )
        assert set(written) == {"json", "csv", "brief"}
        for path in written.values():
            assert path.exists() and path.stat().st_size > 0

    def test_the_csv_carries_the_stamps_as_comments(self, config, prepared, result, tmp_path):
        written = export_result(
            result, config, directory=tmp_path, diagnostics=diagnostics(prepared, result, config)
        )
        text = written["csv"].read_text(encoding="utf-8")
        assert "# regime_id:" in text
        assert "# disclaimer:" in text


class TestFailuresAreHandled:
    def test_an_unknown_mandate_is_a_clear_failure(self, config, real_regime_dir, mandates_dir):
        with pytest.raises(PipelineError, match="no mandate matches"):
            prepare("NoSuchMandate", config, regime_dir=real_regime_dir, mandates_dir=mandates_dir)

    def test_an_unpublished_market_scope_names_the_fix(self, config, real_regime_dir, mandates_dir):
        with pytest.raises(PipelineError, match="macrofield regime"):
            prepare(
                MANDATE, config, market="Atlantis", regime_dir=real_regime_dir,
                mandates_dir=mandates_dir,
            )

    def test_a_mismatched_returnset_is_refused(
        self, config, prepared, real_regime_dir, mandates_dir, tmp_path
    ):
        """Point the run at a Regime the ReturnSet was not estimated under."""
        others = [
            p for p in real_regime_dir.glob("*.json")
            if json.loads(p.read_text(encoding="utf-8"))["current"]["regime_id"]
            != prepared.returnset.regime_id
        ]
        if not others:
            pytest.skip("only one Regime is published, so no mismatch can be constructed")
        with pytest.raises(PipelineError, match="regime_id mismatch"):
            prepare(
                MANDATE, config, market=others[0].stem, regime_dir=real_regime_dir,
                mandates_dir=mandates_dir,
            )
