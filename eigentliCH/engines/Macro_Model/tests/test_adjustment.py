"""Tests for the standardising adjustments.

The invariant, asserted as a property rather than claimed in a docstring: no adjustment this programme can
produce is capable of changing a growth rate, a direction, or a turning point. Level scaling is the only
operation offered, and drift adjustment is deliberately not implemented.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from macrofield.calibration.validate import (
    directional_accuracy,
    find_turning_points,
    growth_correlation,
    score_turning_points,
)
from macrofield.data.adjustment import (
    ADJUSTMENT_PRIORS,
    ADJUSTMENTS_ARE_DYNAMICS_NEUTRAL,
    AdjustmentError,
    SeriesAdjustment,
    apply,
    apply_priors,
    prior_range_for,
    standardise,
    sweep_level_adjustment,
)
from macrofield.data.integrity import check_series
from macrofield.data.provenance import (
    Basis,
    Frequency,
    ProvenanceRecord,
    Reliability,
    Series,
    Valuation,
)

TODAY = dt.date(2026, 7, 27)


def cyclical_series(name: str = "Y", periods: int = 40) -> Series:
    """A growing series with genuine turning points in its growth rate."""
    t = np.arange(periods, dtype=float)
    values = 100.0 * np.exp(0.025 * t) * (1.0 + 0.08 * np.sin(2.0 * np.pi * t / 9.0))
    return Series(
        name=name,
        values=pd.Series(values, index=pd.Index(1985 + t.astype(int), name="year"), name=name),
        provenance=ProvenanceRecord(
            source="Test Source",
            dataset="Test dataset",
            identifier=f"TEST.{name}",
            url="https://example.invalid",
            retrieved_on=TODAY,
            units="current US dollars",
            basis=Basis.NOMINAL,
            frequency=Frequency.ANNUAL,
            currency="USD",
            valuation=Valuation.MARKET,
        ),
    )


LEVEL_ONLY = SeriesAdjustment(
    level_scale=0.85,
    rationale="test adjustment representing the imputation and FISIM overstatement of output",
    source="Capital Saturation section 10.6",
    prior_range=(0.80, 1.00),
)


class TestDriftIsNotAvailable:
    """Drift adjustment was ruled out, so it must be absent rather than defaulted or guarded.

    An option that must never be used is better removed than guarded: leaving it reachable would mean
    every downstream reader had to check whether it had been applied.
    """

    def test_no_drift_parameter_exists(self):
        with pytest.raises(TypeError):
            SeriesAdjustment(drift_per_year=0.01, rationale="r", source="s")

    def test_the_adjustment_exposes_no_drift_attribute(self):
        assert not hasattr(SeriesAdjustment(), "drift_per_year")

    def test_no_prior_carries_a_drift(self):
        for quantity, prior in ADJUSTMENT_PRIORS.items():
            assert not hasattr(prior, "drift_per_year"), quantity

    def test_every_adjustment_reports_itself_as_dynamics_neutral(self):
        assert SeriesAdjustment().is_dynamics_neutral is True
        assert LEVEL_ONLY.is_dynamics_neutral is True

    def test_the_serialised_form_records_neutrality_without_a_drift_field(self):
        payload = LEVEL_ONLY.as_dict()
        assert payload["dynamics_neutral"] is True
        assert "drift_per_year" not in payload


class TestAdjustmentsAreDynamicsNeutral:
    """The invariant the whole design rests on."""

    def test_the_invariant_is_declared(self):
        assert ADJUSTMENTS_ARE_DYNAMICS_NEUTRAL is True

    @pytest.mark.parametrize("scale", [0.5, 0.8, 0.95, 1.05, 1.3, 2.0, 10.0])
    def test_no_permitted_scale_can_change_the_dynamics(self, scale):
        """A property test across the range of scales, not a single example."""
        original = cyclical_series()
        adjustment = SeriesAdjustment(
            level_scale=scale, rationale="property test", source="test"
        )
        adjusted = apply(original, adjustment)
        a, b = original.values.to_numpy(), adjusted.values.to_numpy()

        growth_a, growth_b = np.diff(a) / a[:-1], np.diff(b) / b[:-1]
        assert np.allclose(growth_a, growth_b)
        assert directional_accuracy(a, b) == pytest.approx(1.0)

        turns_a = find_turning_points(growth_a)
        turns_b = find_turning_points(growth_b)
        assert [t.index for t in turns_a] == [t.index for t in turns_b]
        assert [t.direction for t in turns_a] == [t.direction for t in turns_b]

    def test_growth_rates_are_identical(self):
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        a = original.values.to_numpy()
        b = adjusted.values.to_numpy()
        assert np.allclose(np.diff(a) / a[:-1], np.diff(b) / b[:-1])

    def test_turning_points_land_in_the_same_periods(self):
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        a = original.values.to_numpy()
        b = adjusted.values.to_numpy()
        original_turns = find_turning_points(np.diff(a) / a[:-1])
        adjusted_turns = find_turning_points(np.diff(b) / b[:-1])
        assert [t.index for t in original_turns] == [t.index for t in adjusted_turns]
        assert [t.direction for t in original_turns] == [t.direction for t in adjusted_turns]

    def test_directional_accuracy_is_perfect_against_the_original(self):
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        assert directional_accuracy(
            original.values.to_numpy(), adjusted.values.to_numpy()
        ) == pytest.approx(1.0)

    def test_turning_point_hit_rate_is_perfect_against_the_original(self):
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        a, b = original.values.to_numpy(), adjusted.values.to_numpy()
        score = score_turning_points(np.diff(a) / a[:-1], np.diff(b) / b[:-1])
        assert score.hit_rate == pytest.approx(1.0)
        assert score.spurious == []

    def test_growth_correlation_is_one(self):
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        assert growth_correlation(
            original.values.to_numpy(), adjusted.values.to_numpy()
        ) == pytest.approx(1.0)

    def test_but_the_level_does_change(self):
        """Otherwise the adjustment would be doing nothing at all."""
        original = cyclical_series()
        adjusted = apply(original, LEVEL_ONLY)
        assert adjusted.values.iloc[0] == pytest.approx(0.85 * original.values.iloc[0])

    def test_and_ratios_between_series_change_which_is_the_point(self):
        """A level adjustment does real work: it moves K_R/Y and the saturation axis."""
        output = cyclical_series("Y")
        capital = cyclical_series("K_R")
        before = float((capital.values / output.values).iloc[-1])
        after = float((capital.values / apply(output, LEVEL_ONLY).values).iloc[-1])
        assert after > before


class TestTransformationLog:
    def test_it_records_neutrality_by_construction(self):
        adjusted = apply(cyclical_series(), LEVEL_ONLY)
        detail = adjusted.provenance.transformations[-1].detail
        assert "Dynamics-neutral by construction" in detail

    def test_it_records_the_scale_applied(self):
        adjusted = apply(cyclical_series(), LEVEL_ONLY)
        assert "0.85" in adjusted.provenance.transformations[-1].detail


class TestAdjustmentValidation:
    def test_identity_is_the_default(self):
        assert SeriesAdjustment().is_identity

    def test_identity_needs_no_rationale(self):
        SeriesAdjustment()  # must not raise

    def test_a_real_adjustment_must_state_its_rationale(self):
        with pytest.raises(AdjustmentError, match="rationale"):
            SeriesAdjustment(level_scale=0.9)

    def test_a_real_adjustment_must_state_its_source(self):
        with pytest.raises(AdjustmentError, match="where its magnitude comes from"):
            SeriesAdjustment(level_scale=0.9, rationale="because")

    def test_rejects_a_non_positive_scale(self):
        with pytest.raises(AdjustmentError, match="must be positive"):
            SeriesAdjustment(level_scale=0.0, rationale="r", source="s")

    def test_rejects_a_scale_outside_its_own_prior(self):
        with pytest.raises(AdjustmentError, match="outside its own declared prior"):
            SeriesAdjustment(
                level_scale=1.5, rationale="r", source="s", prior_range=(0.8, 1.0)
            )

    def test_rejects_a_non_finite_scale(self):
        with pytest.raises(AdjustmentError, match="finite"):
            SeriesAdjustment(level_scale=float("inf"), rationale="r", source="s")


class TestApply:
    def test_identity_returns_the_series_unchanged(self):
        original = cyclical_series()
        assert apply(original, SeriesAdjustment()) is original

    def test_an_adjusted_series_is_marked_derived(self):
        """So the integrity gate refuses it unless the caller opts in."""
        adjusted = apply(cyclical_series(), LEVEL_ONLY)
        assert adjusted.provenance.reliability is Reliability.DERIVED
        assert not check_series(adjusted).ok
        assert check_series(adjusted, allow_derived=True).ok

    def test_the_rationale_and_source_reach_the_log(self):
        adjusted = apply(cyclical_series(), LEVEL_ONLY)
        detail = adjusted.provenance.transformations[-1].detail
        assert "FISIM" in detail
        assert "section 10.6" in detail

    def test_a_note_warns_that_the_level_is_not_published(self):
        adjusted = apply(cyclical_series(), LEVEL_ONLY)
        assert any("not the published level" in note for note in adjusted.provenance.notes)


class TestPriors:
    def test_every_prior_is_the_identity_by_default(self):
        """Priors document what could be adjusted, they do not quietly adjust anything."""
        for quantity, prior in ADJUSTMENT_PRIORS.items():
            assert prior.is_identity, quantity

    def test_every_prior_carries_a_rationale_and_a_source(self):
        for quantity, prior in ADJUSTMENT_PRIORS.items():
            assert prior.rationale, quantity
            assert prior.source, quantity

    def test_every_prior_declares_a_range(self):
        for quantity, prior in ADJUSTMENT_PRIORS.items():
            assert prior.prior_range is not None, quantity
            low, high = prior.prior_range
            assert low <= 1.0 <= high, quantity

    def test_the_output_prior_points_downwards(self):
        """Book section 10.6: alternative estimates run 10 to 20 per cent below official GDP."""
        low, high = prior_range_for("Y")
        assert low < 1.0
        assert high == pytest.approx(1.0)

    def test_the_real_capital_prior_points_upwards(self):
        """Book section 10.3: excluding land and resources understates the productive stock."""
        low, high = prior_range_for("K_R")
        assert low == pytest.approx(1.0)
        assert high > 1.0

    def test_an_undocumented_quantity_raises_rather_than_inventing_a_range(self):
        with pytest.raises(AdjustmentError, match="no adjustment prior is documented"):
            prior_range_for("some_new_quantity")

    def test_apply_priors_changes_nothing_without_overrides(self):
        original = [cyclical_series("Y"), cyclical_series("K_R")]
        adjusted, applied = apply_priors(original)
        assert all(a is o for a, o in zip(adjusted, original))
        assert all(adj.is_identity for adj in applied.values())

    def test_apply_priors_honours_an_override(self):
        adjusted, applied = apply_priors([cyclical_series("Y")], {"Y": LEVEL_ONLY})
        assert adjusted[0].values.iloc[0] == pytest.approx(85.0, rel=1e-6)
        assert applied["Y"].level_scale == 0.85


class TestStandardise:
    def test_rebases_to_the_reference_value(self):
        rebased = standardise(cyclical_series(), reference_period=1985, reference_value=100.0)
        assert rebased.values.loc[1985] == pytest.approx(100.0)

    def test_is_dynamics_neutral(self):
        original = cyclical_series()
        rebased = standardise(original)
        a, b = original.values.to_numpy(), rebased.values.to_numpy()
        assert np.allclose(np.diff(a) / a[:-1], np.diff(b) / b[:-1])

    def test_puts_two_different_scales_on_one_axis(self):
        small = cyclical_series("Y")
        large = apply(cyclical_series("K_I"), SeriesAdjustment(
            level_scale=1000.0, rationale="test", source="test", prior_range=(1.0, 1000.0)
        ))
        assert standardise(small).values.iloc[0] == pytest.approx(
            standardise(large).values.iloc[0]
        )

    def test_records_the_new_units(self):
        rebased = standardise(cyclical_series(), reference_period=1990)
        assert "index" in rebased.provenance.units

    def test_rejects_an_absent_reference_period(self):
        with pytest.raises(AdjustmentError, match="not observed"):
            standardise(cyclical_series(), reference_period=1900)


class TestSweep:
    def test_reports_the_spread_across_the_prior(self):
        # A saturation ratio whose denominator is being adjusted.
        result = sweep_level_adjustment(
            "Y", lambda scale: 2.5 / scale, steps=5, label="saturation ratio"
        )
        assert len(result.scales) == 5
        assert len(result.values) == 5
        assert result.values[0] > result.values[-1]

    def test_a_stable_conclusion_reads_as_robust(self):
        result = sweep_level_adjustment("Y", lambda _scale: 3.0, steps=4)
        assert "robust" in result.verdict

    def test_a_sensitive_conclusion_reads_as_binding(self):
        result = sweep_level_adjustment("Y", lambda scale: 1.0 / (scale**8), steps=4)
        assert "binding constraint" in result.verdict

    def test_always_reports_dynamics_as_unchanged(self):
        """A level sweep cannot change the dynamic criteria, and the result must say so."""
        result = sweep_level_adjustment("Y", lambda scale: 2.5 / scale, steps=3)
        assert result.dynamics_unchanged is True

    def test_rejects_too_few_steps(self):
        with pytest.raises(AdjustmentError, match="at least two steps"):
            sweep_level_adjustment("Y", lambda _s: 1.0, steps=1)

    def test_is_serialisable(self):
        payload = sweep_level_adjustment("Y", lambda scale: 2.5 / scale, steps=3).as_dict()
        for key in ("quantity", "level_scales", "values", "dynamics_unchanged", "verdict"):
            assert key in payload
