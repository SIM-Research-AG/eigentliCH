"""Tests for the phase classifier, section 0.5.

The fixtures include the scale problem the module documents: an advanced economy on the chapter 10
proxies has K_R/Y near 3 and K_I/Y near 5, which is why the K_R-based conditions saturate and the
credit axis carries the discrimination.
"""

import numpy as np
import pytest

from macrofield.model.phases import Phase, PhaseThresholds, classify_sequence


class TestLatchedExitFromSaturation:
    """The phase becomes Foundation only when saturation reaches that level. Otherwise it sits in Saturation.

    Directed by the author on 2026-07-28. `classify_period` is stateless, so on a falling path it read
    Build-up as soon as saturation crossed back under the Phase 3 ceiling: on United States projected data it
    reported Build-up at 2.31 in the first projected period. That is wrong about the framework. Phase 4 is the
    reordering, and an economy part-way through a correction has not returned to Build-up; the reordering ends
    when the capital base has actually come down to the Foundation level.
    """

    @staticmethod
    def falling(values):
        """A path where only saturation moves, with capital and output held so K_R/K_I stays healthy."""
        n = len(values)
        return dict(
            saturation=list(values),
            real_capital=[2.0] * n,
            financial_capital=[1.0] * n,
            output=[1.0] * n,
        )

    def test_a_falling_path_is_held_in_saturation_until_the_foundation_level(self):
        path = self.falling([4.0, 3.0, 2.3, 1.7, 1.2, 0.9])
        phases = [c.phase for c in classify_sequence(**path)]
        assert phases[:5] == [Phase.SATURATION] * 5, "it must not read Build-up on the way down"
        assert phases[-1] is Phase.FOUNDATION

    def test_the_only_transition_is_into_foundation(self):
        path = self.falling([4.0, 3.0, 2.3, 1.7, 1.2, 0.9])
        phases = [c.phase for c in classify_sequence(**path)]
        changes = [i for i in range(1, len(phases)) if phases[i] is not phases[i - 1]]
        assert len(changes) == 1
        assert phases[changes[0]] is Phase.FOUNDATION

    def test_the_hold_is_explained_in_the_rules(self):
        path = self.falling([4.0, 2.3])
        held = classify_sequence(**path)[1]
        assert any("has not yet reached the Foundation level" in rule for rule in held.rules_fired)

    def test_reaching_foundation_says_the_reordering_is_complete(self):
        path = self.falling([4.0, 0.9])
        done = classify_sequence(**path)[1]
        assert any("reordering is complete" in rule for rule in done.rules_fired)

    def test_ordinary_classification_resumes_after_foundation(self):
        """Once the reordering is over the cycle restarts, so the latch stops governing.

        The exact band a rising path climbs into depends on K_R/Y as well as saturation, which is not what
        this is about. What matters is that the latch is released: the phase is no longer pinned to
        Saturation, and it responds to saturation again.
        """
        path = self.falling([4.0, 0.9, 1.5, 2.6])
        phases = [c.phase for c in classify_sequence(**path)]
        assert phases[0] is Phase.SATURATION
        assert phases[1] is Phase.FOUNDATION
        assert Phase.SATURATION not in phases[2:], "the latch must not re-pin a recovering path"
        assert phases[2] is not Phase.FOUNDATION, "a rising ratio must move off Foundation"

    def test_a_path_that_never_enters_saturation_is_unaffected(self):
        """The latch changes nothing about entry, only about the exit."""
        values = [0.5, 1.5, 2.6]
        path = self.falling(values)
        sequence = classify_sequence(**path)
        from macrofield.model.phases import classify_period

        for index, value in enumerate(values):
            alone = classify_period(
                saturation=value, real_capital=2.0, financial_capital=1.0, output=1.0
            )
            assert sequence[index].phase is alone.phase

    def test_the_real_to_financial_route_into_saturation_also_latches(self):
        """Phase 4 can be entered on K_R/K_I alone, and that entry must latch the same way."""
        phases = [
            c.phase
            for c in classify_sequence(
                saturation=[2.0, 2.0, 0.5],
                real_capital=[0.5, 2.0, 2.0],
                financial_capital=[1.0, 1.0, 1.0],
                output=[1.0, 1.0, 1.0],
            )
        ]
        assert phases[0] is Phase.SATURATION
        assert phases[1] is Phase.SATURATION, "held, even though K_R/K_I recovered"
        assert phases[2] is Phase.FOUNDATION

    def test_it_agrees_with_classify_period_where_nothing_is_latched(self):
        from macrofield.model.phases import classify_period

        values = [0.5, 1.5, 2.6]
        path = self.falling(values)
        sequence = classify_sequence(**path)
        for index, value in enumerate(values):
            alone = classify_period(
                saturation=value, real_capital=2.0, financial_capital=1.0, output=1.0
            )
            assert sequence[index].phase is alone.phase

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(ValueError, match="share a length"):
            classify_sequence(
                saturation=[1.0, 2.0], real_capital=[1.0], financial_capital=[1.0], output=[1.0]
            )

    def test_the_threshold_is_the_configured_foundation_ceiling(self):
        tight = PhaseThresholds(foundation_saturation_ceiling=0.5)
        path = self.falling([4.0, 0.9])
        assert classify_sequence(**path, thresholds=tight)[1].phase is Phase.SATURATION
        loose = PhaseThresholds(foundation_saturation_ceiling=1.0)
        assert classify_sequence(**path, thresholds=loose)[1].phase is Phase.FOUNDATION

from macrofield import config as config_module
from macrofield.model.phases import (
    EconomyType,
    Phase,
    PhaseThresholds,
    classify_period,
    classify_timeline,
    phase_four_entry_indicator,
)


class TestThresholdsFromConfig:
    def test_loads_the_stated_values_from_defaults(self):
        thresholds = PhaseThresholds.from_config(config_module.load())
        assert thresholds.foundation_saturation_ceiling == 1.0
        # Raised from 3.0 to 3.5 so the Phase 3 ceiling matches the balanced band's upper bound. At 3.0 an
        # economy could read as inside the band and past the ceiling at once. See config/defaults.yaml.
        assert thresholds.optimisation_saturation_ceiling == 3.5
        assert thresholds.saturation_real_to_financial_ceiling == 1.0
        assert thresholds.balanced_band == (2.5, 3.5)


class TestPhaseSelection:
    def test_foundation_on_low_saturation(self):
        # An early-development economy: low credit, real capital dominant over financial.
        result = classify_period(
            saturation=0.6, real_capital=80.0, financial_capital=60.0, output=100.0
        )
        assert result.phase is Phase.FOUNDATION
        assert result.economy_type is EconomyType.PRODUCTION

    def test_build_up_when_still_a_production_economy(self):
        # Real capital still exceeds financial capital, so the terminal condition does not fire.
        result = classify_period(
            saturation=1.8, real_capital=90.0, financial_capital=80.0, output=100.0
        )
        assert result.phase is Phase.BUILD_UP
        assert result.economy_type is EconomyType.PRODUCTION

    def test_optimisation_once_past_the_production_boundary(self):
        result = classify_period(
            saturation=2.4, real_capital=140.0, financial_capital=130.0, output=100.0
        )
        assert result.phase is Phase.OPTIMISATION
        assert result.economy_type is EconomyType.FINANCIAL

    def test_saturation_on_the_real_to_financial_crossing(self):
        """The scale-invariant Phase 4 condition, which is what fires for advanced economies."""
        result = classify_period(
            saturation=2.4, real_capital=300.0, financial_capital=500.0, output=100.0
        )
        assert result.phase is Phase.SATURATION
        assert result.real_to_financial == pytest.approx(0.6)

    def test_saturation_on_high_credit_alone(self):
        """Above the Phase 3 ceiling the economy is in Phase 4 even with real capital dominant."""
        result = classify_period(
            saturation=3.4, real_capital=200.0, financial_capital=150.0, output=100.0
        )
        assert result.phase is Phase.SATURATION

    def test_phase_four_takes_precedence_over_a_lower_condition(self):
        """The brief's conditions overlap, so precedence matters: Phase 4 is terminal."""
        # Saturation below the Foundation ceiling, but real capital already below financial.
        result = classify_period(
            saturation=0.5, real_capital=100.0, financial_capital=400.0, output=100.0
        )
        assert result.phase is Phase.SATURATION

    def test_records_the_rule_that_fired(self):
        result = classify_period(
            saturation=0.6, real_capital=80.0, financial_capital=60.0, output=100.0
        )
        assert len(result.rules_fired) == 1
        assert "0.60" in result.rules_fired[0] or "0.600" in result.rules_fired[0]


class TestScaleSaturationIsReported:
    def test_advanced_economy_proxies_report_saturated_conditions(self):
        """With K_R/Y near 3 the K_R-based conditions cannot discriminate, and the classifier must
        say so rather than let a reader assume they contributed."""
        result = classify_period(
            saturation=2.55, real_capital=300.0, financial_capital=500.0, output=100.0
        )
        assert result.saturated_conditions
        assert any("production-economy ceiling" in note for note in result.saturated_conditions)
        assert any("Phase 3 real-capital ceiling" in note for note in result.saturated_conditions)

    def test_low_intensity_economy_reports_no_saturated_conditions(self):
        result = classify_period(
            saturation=0.6, real_capital=80.0, financial_capital=60.0, output=100.0
        )
        assert result.saturated_conditions == []


class TestBalancedBandAndDistances:
    @pytest.mark.parametrize(
        "saturation,expected", [(2.4, False), (2.5, True), (3.0, True), (3.5, True), (3.6, False)]
    )
    def test_balanced_band_membership_is_inclusive(self, saturation, expected):
        result = classify_period(
            saturation=saturation, real_capital=200.0, financial_capital=150.0, output=100.0
        )
        assert result.in_balanced_band is expected

    def test_distances_are_signed_with_negative_meaning_passed(self):
        result = classify_period(
            saturation=2.55, real_capital=300.0, financial_capital=500.0, output=100.0
        )
        # Foundation ceiling of 1.0 is well behind, so the distance is negative.
        assert result.distance_to_boundaries["foundation_ceiling"] < 0.0
        # The Phase 3 ceiling of 3.0 is still ahead.
        assert result.distance_to_boundaries["optimisation_ceiling"] > 0.0
        # K_R/K_I of 0.6 is below the ceiling of 1.0, so that distance is negative.
        assert result.distance_to_boundaries["real_to_financial_ceiling"] < 0.0


class TestGuards:
    @pytest.mark.parametrize("output", [0.0, -5.0])
    def test_rejects_non_positive_output(self, output):
        with pytest.raises(ValueError, match="Y must be positive"):
            classify_period(
                saturation=2.0, real_capital=90.0, financial_capital=200.0, output=output
            )

    def test_rejects_non_positive_financial_capital(self):
        with pytest.raises(ValueError, match="K_I must be positive"):
            classify_period(
                saturation=2.0, real_capital=90.0, financial_capital=0.0, output=100.0
            )


class TestTimeline:
    def test_locates_the_transition(self):
        periods = np.arange(2000, 2006)
        # Credit rises steadily through the Phase 3 ceiling at 3.0.
        saturation = np.array([1.5, 2.0, 2.5, 2.9, 3.1, 3.3])
        real_capital = np.full(6, 140.0)
        financial_capital = np.full(6, 130.0)
        output = np.full(6, 100.0)

        timeline = classify_timeline(
            periods, saturation, real_capital, financial_capital, output
        )
        assert timeline.current.phase is Phase.SATURATION
        assert len(timeline.transitions) == 1
        index, from_phase, to_phase = timeline.transitions[0]
        assert index == 4
        assert from_phase is Phase.OPTIMISATION
        assert to_phase is Phase.SATURATION
        assert timeline.phases.tolist() == [3, 3, 3, 3, 4, 4]

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="must share a length"):
            classify_timeline(
                np.arange(3), np.ones(3), np.ones(2), np.ones(3), np.ones(3)
            )

    def test_rejects_an_empty_path(self):
        empty = np.array([])
        with pytest.raises(ValueError, match="empty path"):
            classify_timeline(empty, empty, empty, empty, empty)


class TestPhaseFourEntryIndicator:
    def test_finds_the_crossing(self):
        ratio = np.array([1.5, 1.2, 1.05, 0.95, 0.8])
        assert phase_four_entry_indicator(ratio) == 3

    def test_returns_none_when_never_crossed(self):
        assert phase_four_entry_indicator(np.array([1.5, 1.4, 1.2])) is None

