"""Tests for the phase 2 fallbacks: carry on where the programme used to refuse, and label what is invented.

Two blockers, two fallbacks:

- a projection that will not integrate to the requested horizon,
- an economy whose saturation axis has never reached the capital-cycle anchor.

Both invent values, which is what the control board needs and is only acceptable because the invented parts
carry `Provenance.EXTRAPOLATED` or `ASSUMED`. Most of these tests are therefore about the labelling as much
as about the numbers.
"""

import inspect

import numpy as np
import pytest

from macrofield.control import Provenance
from macrofield.model.cycles import (
    CycleError,
    anchor_capital_cycle,
    anchor_capital_cycle_by_projection,
)
from macrofield.projection import _extend_log_linear, _mean_log_growth


class TestLogGrowthHelpers:
    def test_the_mean_growth_of_a_clean_exponential_is_its_rate(self):
        years = np.arange(30, dtype=float)
        assert _mean_log_growth(100.0 * np.exp(0.03 * years)) == pytest.approx(0.03)

    def test_a_window_limits_the_growth_estimate_to_the_tail(self):
        values = np.concatenate([100.0 * np.exp(0.01 * np.arange(20)),
                                 100.0 * np.exp(0.01 * 19) * np.exp(0.20 * np.arange(1, 6))])
        assert _mean_log_growth(values, window=5) > 0.15
        assert _mean_log_growth(values) < 0.10

    def test_a_non_positive_series_has_no_log_growth(self):
        assert np.isnan(_mean_log_growth(np.array([1.0, 0.0, -1.0])))

    def test_the_extension_compounds_the_given_rate_from_the_anchor(self):
        out = _extend_log_linear(anchor=200.0, rate=0.05, periods=3)
        assert out[0] == pytest.approx(200.0 * np.exp(0.05))
        assert out[-1] == pytest.approx(200.0 * np.exp(0.15))

    def test_a_non_finite_rate_holds_the_level(self):
        """Better a flat continuation than a NaN tail on a chart."""
        out = _extend_log_linear(anchor=200.0, rate=float("nan"), periods=3)
        assert np.allclose(out, 200.0)

    def test_no_periods_is_an_empty_extension(self):
        assert _extend_log_linear(1.0, 0.01, 0).size == 0


class TestAssumedCapitalAnchor:
    """Where an economy has not reached 3.5, solve the trend for when it would.

    The author's instruction of 2026-07-28. The guard is the interesting half: assuming *when* an economy
    reaches saturation extrapolates a rising trend, and assuming *that* it will against a falling one is a
    different and much weaker claim.
    """

    @staticmethod
    def rising(first: float, last: float, years: int = 30, start: int = 1995):
        periods = np.arange(start, start + years)
        return periods, np.linspace(first, last, years)

    def test_a_rising_trend_gives_a_provisional_anchor(self):
        periods, saturation = self.rising(1.5, 3.0)
        assumed = anchor_capital_cycle_by_projection(periods, saturation)
        assert assumed.anchored
        assert assumed.assumed
        assert assumed.reference_year > periods[-1], "the crossing must be in the future"

    def test_the_provisional_anchor_carries_assumed_provenance(self):
        """This is the whole reason the fallback is acceptable."""
        periods, saturation = self.rising(1.5, 3.0)
        assumed = anchor_capital_cycle_by_projection(periods, saturation)
        assert assumed.provenance is Provenance.ASSUMED
        assert assumed.provenance.is_invented

    def test_an_observed_crossing_is_not_marked_assumed(self):
        periods, saturation = self.rising(1.5, 4.0)
        observed = anchor_capital_cycle(periods, saturation)
        assert observed.anchored
        assert not observed.assumed
        assert observed.provenance is Provenance.DERIVED
        assert not observed.provenance.is_invented

    def test_the_crossing_solves_the_fitted_trend(self):
        """A clean straight line must give the crossing exactly."""
        periods = np.arange(2000, 2021)
        saturation = 2.0 + 0.05 * (periods - 2000)  # reaches 3.5 thirty years in, so 2030
        assumed = anchor_capital_cycle_by_projection(periods, saturation, trend_window=21)
        assert assumed.reference_year == pytest.approx(2030.0)

    def test_the_position_follows_from_the_provisional_crossing(self):
        periods = np.arange(2000, 2021)
        saturation = 2.0 + 0.05 * (periods - 2000)
        assumed = anchor_capital_cycle_by_projection(periods, saturation, trend_window=21)
        # 2020 is ten years before the crossing, which the anchor places at 90 years in.
        assert float(assumed.years_into_cycle[-1]) == pytest.approx(80.0)

    def test_a_falling_trend_is_refused_rather_than_assumed(self):
        """Germany and India are the live cases: both below 3.5 and both trending down."""
        periods, saturation = self.rising(3.0, 2.5)
        assumed = anchor_capital_cycle_by_projection(periods, saturation)
        assert not assumed.anchored
        assert assumed.reference_year is None
        assert any("not approaching the anchor" in note for note in assumed.notes)

    def test_a_flat_trend_is_refused(self):
        periods = np.arange(2000, 2021)
        assumed = anchor_capital_cycle_by_projection(periods, np.full(periods.size, 2.4))
        assert not assumed.anchored

    def test_a_crossing_centuries_out_is_refused(self):
        """Arithmetically a crossing, analytically nothing."""
        periods = np.arange(2000, 2021)
        saturation = 2.0 + 0.0005 * (periods - 2000)  # reaches 3.5 in three thousand years
        assumed = anchor_capital_cycle_by_projection(periods, saturation, trend_window=21)
        assert not assumed.anchored
        assert any("arithmetic rather than a position" in note for note in assumed.notes)

    def test_the_trend_window_sensitivity_is_stated(self):
        """The answer moves with the window, so the output has to say so."""
        periods, saturation = self.rising(1.5, 3.0)
        assumed = anchor_capital_cycle_by_projection(periods, saturation)
        assert any("moves with the trend window" in note for note in assumed.notes)

    def test_the_window_actually_changes_the_answer(self):
        """A curved approach gives different crossings from different windows, which is the point."""
        periods = np.arange(2000, 2025)
        saturation = 2.0 + 0.9 * ((periods - 2000) / 24.0) ** 2
        short = anchor_capital_cycle_by_projection(periods, saturation, trend_window=5)
        long = anchor_capital_cycle_by_projection(periods, saturation, trend_window=25)
        assert short.reference_year != pytest.approx(long.reference_year)

    def test_it_says_the_position_is_an_assumption_not_a_measurement(self):
        periods, saturation = self.rising(1.5, 3.0)
        assumed = anchor_capital_cycle_by_projection(periods, saturation)
        joined = " ".join(assumed.notes)
        assert "ASSUMED" in joined
        assert "not a measurement" in joined

    def test_too_little_data_is_refused(self):
        assumed = anchor_capital_cycle_by_projection(np.array([2020]), np.array([2.0]))
        assert not assumed.anchored
        assert any("fewer than two finite" in note for note in assumed.notes)

    def test_mismatched_lengths_are_an_error(self):
        with pytest.raises(CycleError, match="share a shape"):
            anchor_capital_cycle_by_projection(np.arange(5), np.ones(4))


class TestCapitalCycleRestart:
    """A completed reordering restarts the cycle.

    The consequence of the phase rule of 2026-07-28: the reordering ends when saturation reaches the
    Foundation level, and at that point the economy is at the start of a new cycle rather than the end of the
    old one. Without the restart the anchor stayed at the last observed crossing and kept reporting the
    economy decades late for a correction it had already been through.
    """

    def test_the_restart_is_the_first_foundation_after_a_saturation(self):
        from macrofield.model.cycles import reordering_end

        labels = ["Optimisation", "Saturation and reordering", "Saturation and reordering", "Foundation"]
        assert reordering_end(labels) == 3

    def test_foundation_without_a_prior_saturation_is_not_a_restart(self):
        """An unsaturated economy has not been through a reordering, so nothing restarts."""
        from macrofield.model.cycles import reordering_end

        assert reordering_end(["Foundation", "Build-up", "Optimisation"]) is None

    def test_a_path_that_never_reaches_foundation_has_no_restart(self):
        from macrofield.model.cycles import reordering_end

        assert reordering_end(["Saturation and reordering"] * 5) is None

    def test_without_a_restart_the_count_grows_without_bound(self):
        from macrofield.model.cycles import years_into_capital_cycle

        years = np.arange(2010, 2041)
        into = years_into_capital_cycle(years, 2013.5, 90.0, 90.0)
        assert into[-1] > 90.0, "the old behaviour: past the cycle's end and still counting"

    def test_the_restart_puts_the_economy_early_in_a_new_cycle(self):
        from macrofield.model.cycles import years_into_capital_cycle

        years = np.arange(2010, 2041)
        into = years_into_capital_cycle(years, 2013.5, 90.0, 90.0, restart_year=2030)
        at_restart = int(np.flatnonzero(years == 2030)[0])
        assert into[at_restart] == pytest.approx(0.0)
        assert into[-1] == pytest.approx(10.0)
        assert (into[at_restart:] < 90.0).all(), "after the restart it must not read as overdue"

    def test_periods_before_the_restart_are_unchanged(self):
        from macrofield.model.cycles import years_into_capital_cycle

        years = np.arange(2010, 2041)
        plain = years_into_capital_cycle(years, 2013.5, 90.0, 90.0)
        restarted = years_into_capital_cycle(years, 2013.5, 90.0, 90.0, restart_year=2030)
        before = years < 2030
        assert np.allclose(plain[before], restarted[before])

    def test_the_board_reports_the_restart(self):
        source = inspect.getsource(
            __import__("macrofield.cockpit.server", fromlist=["server"]).create_app
        )
        assert '"capital_reanchor"' in source
        assert "reordering is complete and the capital cycle restarts there" in source


class TestAnchoredFromConfigFallback:
    def test_the_assumption_is_off_by_default(self, ):
        """An ordinary run reports an economy as unanchored rather than quietly assuming a future."""
        from macrofield import config as config_module
        from macrofield.model.cycles import anchored_from_config

        periods = np.arange(1995, 2025)
        saturation = np.linspace(1.5, 3.0, periods.size)  # rising, but never reaching 3.5
        settings = config_module.load()

        default = anchored_from_config(settings, periods, saturation)
        assert not default["capital"].anchored

        opted_in = anchored_from_config(settings, periods, saturation, assume_capital_crossing=True)
        assert opted_in["capital"].anchored
        assert opted_in["capital"].assumed

    def test_the_observed_failure_is_carried_alongside_the_assumption(self):
        """A reader has to see why the real anchor failed, not only what was assumed instead."""
        from macrofield import config as config_module
        from macrofield.model.cycles import anchored_from_config

        periods = np.arange(1995, 2025)
        saturation = np.linspace(1.5, 3.0, periods.size)
        settings = config_module.load()
        capital = anchored_from_config(
            settings, periods, saturation, assume_capital_crossing=True
        )["capital"]
        joined = " ".join(capital.notes)
        assert "never reaches the anchor" in joined
        assert "ASSUMED" in joined

    def test_an_economy_with_a_real_crossing_is_unaffected_by_the_flag(self):
        from macrofield import config as config_module
        from macrofield.model.cycles import anchored_from_config

        periods = np.arange(1995, 2025)
        saturation = np.linspace(1.5, 4.0, periods.size)
        settings = config_module.load()
        with_flag = anchored_from_config(
            settings, periods, saturation, assume_capital_crossing=True
        )["capital"]
        assert with_flag.anchored
        assert not with_flag.assumed
