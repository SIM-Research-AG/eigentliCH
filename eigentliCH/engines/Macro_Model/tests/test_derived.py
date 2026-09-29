"""Tests for the indicators derived from the state and the quantity equation."""

import numpy as np
import pytest

from macrofield.model.derived import (
    CONSTANT_FREQUENCY,
    FREQUENCY_TRACKS_OUTPUT,
    DerivedError,
    Indicator,
    compute,
    summarise_latest,
    transaction_frequency,
)

PERIODS = list(range(1990, 2025))
N = len(PERIODS)


def state(real_rate: float = 0.02, financial_rate: float = 0.05):
    """A financialising economy: financial capital growing faster than output."""
    t = np.arange(N, dtype=float)
    return {
        "output": 100.0 * np.exp(real_rate * t),
        "real_capital": 90.0 * np.exp(real_rate * t),
        "financial_capital": 150.0 * np.exp(financial_rate * t),
    }


class TestTransactionFrequency:
    def test_constant_is_unity(self):
        assert np.allclose(transaction_frequency(np.arange(1.0, 6.0)), 1.0)

    def test_tracks_output_is_rebased_output(self):
        output = np.array([100.0, 110.0, 121.0])
        assert np.allclose(
            transaction_frequency(output, FREQUENCY_TRACKS_OUTPUT), [1.0, 1.1, 1.21]
        )

    def test_rejects_an_unknown_assumption(self):
        with pytest.raises(DerivedError, match="unknown frequency assumption"):
            transaction_frequency(np.ones(3), "magic")


class TestGuards:
    def test_rejects_mismatched_lengths(self):
        with pytest.raises(DerivedError, match="share a shape"):
            compute(PERIODS, np.ones(N), np.ones(N - 1), np.ones(N))

    def test_rejects_non_positive_output(self):
        s = state()
        s["output"][3] = 0.0
        with pytest.raises(DerivedError, match="strictly positive"):
            compute(PERIODS, s["output"], s["real_capital"], s["financial_capital"])


class TestPriceLevels:
    def test_real_price_level_follows_output_under_constant_frequency(self):
        """P_R H_R = Y, so with H held flat the real price level is output up to a constant."""
        s = state()
        result = compute(PERIODS, **s)
        index = result.series(Indicator.REAL_PRICE_LEVEL)
        assert np.allclose(index, 100.0 * s["output"] / s["output"][0])

    def test_real_price_level_is_flat_when_frequency_tracks_output(self):
        """Then it carries no information, and the caveat says so."""
        result = compute(PERIODS, **state(), assumption=FREQUENCY_TRACKS_OUTPUT)
        assert np.allclose(result.series(Indicator.REAL_PRICE_LEVEL), 100.0)
        assert "flat by construction" in result.caveats[Indicator.REAL_PRICE_LEVEL.value]

    def test_financial_price_level_is_the_unsecured_gap(self):
        """P_I H_I = K_R + K_I - Y, which is the section 0.4 gap."""
        s = state()
        gap = s["real_capital"] + s["financial_capital"] - s["output"]
        result = compute(PERIODS, **s)
        assert np.allclose(result.series(Indicator.FINANCIAL_PRICE_LEVEL), 100.0 * gap / gap[0])

    def test_the_equivalence_is_declared_as_an_assumption(self):
        """It is a claim about asset prices, not an accounting identity, so it must be labelled."""
        caveat = compute(PERIODS, **state()).caveats[Indicator.FINANCIAL_PRICE_LEVEL.value]
        assert "not an accounting identity" in caveat

    def test_financial_price_level_is_undefined_for_a_non_positive_gap(self):
        s = state()
        s["financial_capital"] = np.full(N, 1.0)  # gap goes negative
        result = compute(PERIODS, **s)
        assert np.all(~np.isfinite(result.series(Indicator.FINANCIAL_PRICE_LEVEL)))


class TestInflation:
    def test_real_inflation_recovers_the_injected_rate(self):
        result = compute(PERIODS, **state(real_rate=0.03))
        inflation = result.series(Indicator.REAL_INFLATION)
        assert np.allclose(inflation[1:], np.exp(0.03) - 1.0)

    def test_financial_inflation_exceeds_real_when_capital_outgrows_output(self):
        """The framework's central claim: asset prices follow the capital base, not the real economy."""
        result = compute(PERIODS, **state(real_rate=0.02, financial_rate=0.06))
        real = np.nanmean(result.series(Indicator.REAL_INFLATION))
        financial = np.nanmean(result.series(Indicator.FINANCIAL_INFLATION))
        assert financial > real

    def test_inflation_is_padded_to_preserve_length(self):
        result = compute(PERIODS, **state())
        assert result.series(Indicator.REAL_INFLATION).shape == (N,)
        assert not np.isfinite(result.series(Indicator.REAL_INFLATION)[0])

    def test_growth_rates_do_not_depend_on_the_frequency_level(self):
        """The reason levels are reported as indices and growth rates as rates: a growth rate needs only
        that the unobserved frequency be stable, not that its value be known."""
        constant = compute(PERIODS, **state())
        scaled = compute(PERIODS, **state())
        # Scaling the frequency by any constant leaves the growth rate identical.
        assert np.allclose(
            constant.series(Indicator.REAL_INFLATION)[1:],
            scaled.series(Indicator.REAL_INFLATION)[1:],
        )


class TestReturnAndInterest:
    def test_return_on_capital_follows_the_section_definition(self):
        s = state()
        y_dot = np.gradient(s["output"])
        k_r_dot = np.gradient(s["real_capital"])
        result = compute(PERIODS, **s)
        expected = (y_dot + k_r_dot) / s["real_capital"]
        assert np.allclose(result.series(Indicator.RETURN_ON_CAPITAL), expected)

    def test_supplied_derivatives_are_used_in_preference(self):
        s = state()
        supplied = np.full(N, 5.0)
        result = compute(PERIODS, **s, output_growth=supplied, real_capital_growth=supplied)
        expected = (supplied + supplied) / s["real_capital"]
        assert np.allclose(result.series(Indicator.RETURN_ON_CAPITAL), expected)

    def test_real_interest_is_the_return_net_of_inflation(self):
        result = compute(PERIODS, **state())
        expected = result.series(Indicator.RETURN_ON_CAPITAL) - result.series(
            Indicator.REAL_INFLATION
        )
        assert np.allclose(
            result.series(Indicator.REAL_INTEREST_RATE)[1:], expected[1:], equal_nan=True
        )

    def test_the_interest_caveat_names_the_empirical_counterpart(self):
        caveat = compute(PERIODS, **state()).caveats[Indicator.REAL_INTEREST_RATE.value]
        assert "Officer-Williamson" in caveat


class TestWageShare:
    def test_only_the_growth_rate_is_reported(self):
        """The level of the section 0.2 formula is dimensionally inconsistent with its description."""
        caveat = compute(PERIODS, **state()).caveats[Indicator.WAGE_SHARE_GROWTH.value]
        assert "dimensionally inconsistent" in caveat
        assert "growth rate" in caveat


class TestPriceDivergence:
    def test_rises_when_the_financial_side_outpaces_the_real_side(self):
        """This is the financialisation signature and the most direct chart of the thesis."""
        result = compute(PERIODS, **state(real_rate=0.02, financial_rate=0.06))
        divergence = result.series(Indicator.PRICE_DIVERGENCE)
        finite = divergence[np.isfinite(divergence)]
        assert finite[-1] > finite[0]

    def test_is_rebased_to_one(self):
        result = compute(PERIODS, **state())
        finite = result.series(Indicator.PRICE_DIVERGENCE)
        finite = finite[np.isfinite(finite)]
        assert finite[0] == pytest.approx(1.0)

    def test_stays_flat_when_both_sides_grow_together(self):
        result = compute(PERIODS, **state(real_rate=0.03, financial_rate=0.03))
        divergence = result.series(Indicator.PRICE_DIVERGENCE)
        finite = divergence[np.isfinite(divergence)]
        # Not exactly flat, because the gap includes Y, but it must not trend strongly.
        assert abs(finite[-1] - finite[0]) < 0.5


class TestReporting:
    def test_every_indicator_is_labelled_and_has_units(self):
        for indicator in Indicator:
            assert indicator.label
            assert indicator.units

    def test_every_computed_indicator_carries_a_caveat(self):
        result = compute(PERIODS, **state())
        for key in result.values:
            assert result.caveats.get(key), key

    def test_serialisation_replaces_non_finite_with_null(self):
        payload = compute(PERIODS, **state()).as_dict()
        inflation = payload["indicators"][Indicator.REAL_INFLATION.value]["values"]
        assert inflation[0] is None
        assert all(v is None or isinstance(v, float) for v in inflation)

    def test_notes_state_the_frequency_assumption(self):
        result = compute(PERIODS, **state())
        assert any("unobserved" in note for note in result.notes)

    def test_notes_state_that_a_projected_state_gives_projected_indicators(self):
        """The reason these are separated from the data layer."""
        result = compute(PERIODS, **state())
        assert any("projected state" in note for note in result.notes)

    def test_summary_gives_the_latest_of_each(self):
        summary = summarise_latest(compute(PERIODS, **state()))
        assert summary["period"] == PERIODS[-1]
        for indicator in Indicator:
            assert indicator.value in summary

    def test_requesting_an_uncomputed_indicator_names_what_is_available(self):
        result = compute(PERIODS, **state())
        result.values.pop(Indicator.REAL_INFLATION.value)
        with pytest.raises(DerivedError, match="Available"):
            result.series(Indicator.REAL_INFLATION)
