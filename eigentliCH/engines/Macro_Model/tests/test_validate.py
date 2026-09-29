"""Tests for validation, section 5.

The primary criteria are turning points and direction, not level, per the author's guidance that the
model does not have to fit perfectly but must get the trend and especially the turning points right.
"""

import numpy as np
import pytest

from macrofield.calibration.validate import (
    DEFAULT_MIN_PROMINENCE,
    AnalogueOverlay,
    Direction,
    ResolutionPath,
    assess_trend,
    directional_accuracy,
    find_turning_points,
    growth_correlation,
    overlay_analogue,
    phase_four_scenarios,
    score_turning_points,
)


def cycle(periods: int = 40, period_length: float = 10.0, phase: float = 0.0, trend: float = 0.0):
    """A sinusoid, optionally with trend, whose turning points are known by construction."""
    t = np.arange(periods, dtype=float)
    return np.sin(2.0 * np.pi * t / period_length + phase) + trend * t


class TestFindTurningPoints:
    def test_finds_the_expected_number_in_a_sinusoid(self):
        points = find_turning_points(cycle(periods=41, period_length=10.0))
        # Four full cycles gives four peaks and four troughs, allowing for the end points.
        assert 6 <= len(points) <= 9

    def test_identifies_both_directions(self):
        points = find_turning_points(cycle())
        directions = {p.direction for p in points}
        assert directions == {Direction.PEAK, Direction.TROUGH}

    def test_peak_sits_at_a_local_maximum(self):
        values = cycle(periods=41, period_length=10.0)
        for point in find_turning_points(values):
            if point.direction is Direction.PEAK and 0 < point.index < len(values) - 1:
                assert values[point.index] >= values[point.index - 1]
                assert values[point.index] >= values[point.index + 1]

    def test_returns_period_labels(self):
        years = list(range(1980, 1980 + 41))
        points = find_turning_points(cycle(periods=41), periods=years)
        assert all(p.period in years for p in points)

    def test_ignores_wobbles_below_the_prominence_floor(self):
        """Counting wobbles inflates the hit rate and the false-positive rate until neither means
        anything."""
        rng = np.random.default_rng(20260727)
        noisy = cycle(periods=41, period_length=10.0) + 0.01 * rng.normal(size=41)
        strict = find_turning_points(noisy, min_prominence=0.2)
        permissive = find_turning_points(noisy, min_prominence=0.001)
        assert len(strict) <= len(permissive)

    def test_a_monotone_series_has_no_turning_points(self):
        assert find_turning_points(np.arange(20, dtype=float)) == []

    def test_a_flat_series_has_no_turning_points(self):
        assert find_turning_points(np.full(20, 3.0)) == []

    def test_too_short_a_series_returns_nothing(self):
        assert find_turning_points([1.0, 2.0]) == []

    def test_rejects_mismatched_labels(self):
        with pytest.raises(ValueError, match="period labels"):
            find_turning_points(cycle(periods=10), periods=list(range(5)))


class TestScoreTurningPoints:
    def test_an_identical_path_matches_every_turn(self):
        values = cycle(periods=41, period_length=10.0)
        score = score_turning_points(values, values)
        assert score.hit_rate == pytest.approx(1.0)
        assert score.missed == []
        assert score.spurious == []
        assert score.mean_absolute_lead_lag == pytest.approx(0.0)

    def test_a_lagged_path_is_matched_with_a_negative_lead(self):
        values = cycle(periods=41, period_length=10.0)
        lagged = np.roll(values, 1)
        score = score_turning_points(values, lagged, tolerance_periods=2)
        assert score.matched
        assert score.mean_lead_lag < 0.0  # simulated turns later than observed

    def test_an_early_path_is_matched_with_a_positive_lead(self):
        """Turning early is the useful direction, so the sign convention must make that positive."""
        values = cycle(periods=41, period_length=10.0)
        early = np.roll(values, -1)
        score = score_turning_points(values, early, tolerance_periods=2)
        assert score.matched
        assert score.mean_lead_lag > 0.0

    def test_a_far_shifted_path_misses_everything(self):
        values = cycle(periods=41, period_length=10.0)
        opposite = cycle(periods=41, period_length=10.0, phase=np.pi)
        score = score_turning_points(values, opposite, tolerance_periods=1)
        assert score.hit_rate < 0.5

    def test_a_flat_simulation_misses_every_turn_and_invents_none(self):
        values = cycle(periods=41, period_length=10.0)
        score = score_turning_points(values, np.full(41, 0.0))
        assert score.hit_rate == pytest.approx(0.0)
        assert score.spurious == []
        assert len(score.missed) == score.observed_count

    def test_one_simulated_turn_cannot_be_credited_twice(self):
        """Otherwise a single spike would score as finding several nearby observed turns."""
        observed = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        simulated = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        score = score_turning_points(observed, simulated, tolerance_periods=4)
        assert len(score.matched) <= 1

    def test_hit_rate_is_undefined_with_no_observed_turns(self):
        score = score_turning_points(np.arange(20, dtype=float), np.arange(20, dtype=float))
        assert np.isnan(score.hit_rate)

    def test_report_is_serialisable(self):
        values = cycle(periods=41, period_length=10.0)
        payload = score_turning_points(values, values).as_dict()
        for key in ("hit_rate", "matched", "missed", "spurious", "mean_lead_lag_periods"):
            assert key in payload


class TestDirectionalAccuracy:
    def test_identical_paths_score_one(self):
        values = cycle()
        assert directional_accuracy(values, values) == pytest.approx(1.0)

    def test_inverted_paths_score_zero(self):
        values = cycle()
        assert directional_accuracy(values, -values) == pytest.approx(0.0)

    def test_a_coin_toss_scores_near_a_half(self):
        rng = np.random.default_rng(20260727)
        a = rng.normal(size=400)
        b = rng.normal(size=400)
        assert 0.4 < directional_accuracy(a, b) < 0.6

    def test_undefined_for_mismatched_lengths(self):
        assert np.isnan(directional_accuracy(np.arange(5.0), np.arange(6.0)))


class TestGrowthCorrelation:
    def test_levels_of_two_exponentials_would_flatter_the_model(self):
        """The reason growth is used rather than levels: level correlation is near one regardless."""
        t = np.arange(40, dtype=float)
        a = np.exp(0.03 * t)
        b = np.exp(0.05 * t)
        level_correlation = float(np.corrcoef(a, b)[0, 1])
        assert level_correlation > 0.95  # uninformative
        # Growth rates are constant here, so the correlation is undefined rather than flattering.
        assert np.isnan(growth_correlation(a, b))

    def test_detects_agreement_in_growth(self):
        rng = np.random.default_rng(20260727)
        shocks = rng.normal(0.02, 0.01, size=60)
        a = 100.0 * np.cumprod(1.0 + shocks)
        b = 200.0 * np.cumprod(1.0 + shocks)
        assert growth_correlation(a, b) > 0.99

    def test_detects_disagreement_in_growth(self):
        rng = np.random.default_rng(1)
        a = 100.0 * np.cumprod(1.0 + rng.normal(0.02, 0.01, size=60))
        b = 100.0 * np.cumprod(1.0 + rng.normal(0.02, 0.01, size=60))
        assert abs(growth_correlation(a, b)) < 0.5


class TestAssessTrend:
    def test_turning_points_are_the_primary_report(self):
        values = 100.0 * np.exp(0.02 * np.arange(40)) * (1.0 + 0.1 * cycle(periods=40))
        verdict = assess_trend("K_I", values, values, periods=list(range(1980, 2020)))
        payload = verdict.as_dict()
        assert "turning_points" in payload["primary"]
        assert "level_relative_residual" in payload["secondary"]

    def test_a_perfect_path_reads_as_finding_every_turn(self):
        values = 100.0 * np.exp(0.02 * np.arange(40)) * (1.0 + 0.1 * cycle(periods=40))
        verdict = assess_trend("K_I", values, values)
        assert verdict.turning_points.hit_rate == pytest.approx(1.0)
        assert verdict.directional_accuracy == pytest.approx(1.0)
        assert "found" in verdict.verdict

    def test_a_level_offset_does_not_destroy_the_turning_point_score(self):
        """The point of the author's guidance: a wrong level with the right turns must still score well."""
        base = 100.0 * np.exp(0.02 * np.arange(40)) * (1.0 + 0.1 * cycle(periods=40))
        offset = base * 1.5  # 50 per cent too high throughout
        verdict = assess_trend("K_I", base, offset)
        assert verdict.turning_points.hit_rate == pytest.approx(1.0)
        assert verdict.level_residual > 0.4  # level is badly wrong
        assert verdict.directional_accuracy == pytest.approx(1.0)

    def test_growth_detection_is_the_default_because_levels_only_rise(self):
        rising = 100.0 * np.exp(0.02 * np.arange(30))
        on_growth = assess_trend("Y", rising, rising, on_growth_rates=True)
        on_level = assess_trend("Y", rising, rising, on_growth_rates=False)
        # A monotone level has no turns at all, so level detection finds nothing to judge.
        assert on_level.turning_points.observed_count == 0
        assert np.isnan(on_level.turning_points.hit_rate)
        assert isinstance(on_growth.turning_points.observed_count, int)

    def test_an_empty_simulation_is_reported_not_crashed(self):
        verdict = assess_trend("Y", [1.0, 2.0, 3.0], [])
        assert "nothing can be judged" in verdict.verdict
        assert np.isinf(verdict.level_residual)

    def test_verdict_names_the_direction_of_the_timing_error(self):
        values = 100.0 * np.exp(0.02 * np.arange(40)) * (1.0 + 0.1 * cycle(periods=40))
        late = np.roll(values, 2)
        verdict = assess_trend("K_I", values, late, tolerance_periods=3)
        assert "early" in verdict.verdict or "late" in verdict.verdict


class TestPhaseFourScenarios:
    def test_both_paths_are_produced(self):
        scenarios = phase_four_scenarios(2025, 4.5)
        assert set(scenarios) == {ResolutionPath.DEBT_DEFLATION, ResolutionPath.HYPERINFLATION}

    def test_both_paths_reduce_the_ratio(self):
        scenarios = phase_four_scenarios(2025, 4.5)
        for scenario in scenarios.values():
            assert scenario.capital_ratio[-1] < scenario.capital_ratio[0]

    def test_both_converge_towards_the_target(self):
        scenarios = phase_four_scenarios(2025, 4.5, target_ratio=3.0, horizon=40)
        for scenario in scenarios.values():
            assert scenario.capital_ratio[-1] == pytest.approx(3.0, abs=0.01)

    def test_the_mechanisms_are_opposite_and_stated(self):
        scenarios = phase_four_scenarios(2025, 4.5)
        deflation = scenarios[ResolutionPath.DEBT_DEFLATION]
        inflation = scenarios[ResolutionPath.HYPERINFLATION]
        assert "numerator" in deflation.mechanism
        assert "denominator" in inflation.mechanism

    def test_the_asset_implications_are_opposite(self):
        scenarios = phase_four_scenarios(2025, 4.5)
        assert "cash" in scenarios[ResolutionPath.DEBT_DEFLATION].asset_implication
        assert "real assets" in scenarios[ResolutionPath.HYPERINFLATION].asset_implication

    def test_every_scenario_carries_the_projection_label(self):
        for scenario in phase_four_scenarios(2025, 4.5).values():
            assert scenario.label == "illustrative, model-derived"

    def test_refuses_to_invent_a_correction_that_is_not_implied(self):
        """A ratio already inside the band implies no Phase IV correction, so projecting one would be
        manufacturing a crisis."""
        with pytest.raises(ValueError, match="inventing a crisis"):
            phase_four_scenarios(2025, 2.8, target_ratio=3.0)

    def test_rejects_a_zero_horizon(self):
        with pytest.raises(ValueError, match="at least one period"):
            phase_four_scenarios(2025, 4.5, horizon=0)

    def test_faster_deflation_corrects_sooner(self):
        slow = phase_four_scenarios(2025, 4.5, deflation_capital_decline=0.03)
        fast = phase_four_scenarios(2025, 4.5, deflation_capital_decline=0.12)
        assert (
            fast[ResolutionPath.DEBT_DEFLATION].capital_ratio[5]
            < slow[ResolutionPath.DEBT_DEFLATION].capital_ratio[5]
        )


class TestAnalogueOverlay:
    def _series(self):
        current = list(range(2005, 2026))
        analogue = list(range(1915, 1930))
        return current, analogue

    def test_aligns_on_the_supplied_reference_periods(self):
        current, analogue = self._series()
        overlay = overlay_analogue(
            "germany_1920s",
            current,
            list(np.linspace(2.0, 4.5, len(current))),
            analogue,
            list(np.linspace(2.2, 5.0, len(analogue))),
            current_reference=2020,
            analogue_reference=1920,
        )
        assert overlay.aligned_offset == 100
        assert overlay.analogue_periods[0] == 2015

    def test_carries_the_analogue_label(self):
        current, analogue = self._series()
        overlay = overlay_analogue(
            "germany_1920s",
            current,
            list(np.linspace(2.0, 4.5, len(current))),
            analogue,
            list(np.linspace(2.2, 5.0, len(analogue))),
            2020,
            1920,
        )
        assert overlay.label == "historical analogue, not a prediction"

    def test_reports_shape_similarity(self):
        current, analogue = self._series()
        overlay = overlay_analogue(
            "germany_1920s",
            current,
            list(np.linspace(2.0, 4.5, len(current))),
            analogue,
            list(np.linspace(2.2, 5.0, len(analogue))),
            2020,
            1920,
        )
        assert np.isfinite(overlay.similarity)

    def test_rejects_a_reference_outside_the_series(self):
        current, analogue = self._series()
        with pytest.raises(ValueError, match="current reference"):
            overlay_analogue(
                "x", current, [1.0] * len(current), analogue, [1.0] * len(analogue), 1999, 1920
            )

    def test_rejects_an_analogue_reference_outside_the_analogue(self):
        current, analogue = self._series()
        with pytest.raises(ValueError, match="analogue reference"):
            overlay_analogue(
                "x", current, [1.0] * len(current), analogue, [1.0] * len(analogue), 2020, 1800
            )

    def test_is_serialisable(self):
        current, analogue = self._series()
        payload = overlay_analogue(
            "germany_1920s",
            current,
            list(np.linspace(2.0, 4.5, len(current))),
            analogue,
            list(np.linspace(2.2, 5.0, len(analogue))),
            2020,
            1920,
        ).as_dict()
        assert payload["label"] == "historical analogue, not a prediction"
        assert "shape_correlation" in payload
