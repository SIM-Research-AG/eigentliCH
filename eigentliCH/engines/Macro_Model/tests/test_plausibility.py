"""Tests for the plausibility checks, which catch real-but-wrong data.

The India equity market capitalisation reading that prompted this module is used as a fixture, so the
module is pinned against the case it exists for.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from macrofield.data.plausibility import (
    EXPECTED_RANGES,
    RANGES_BY_QUANTITY,
    ExpectedRange,
    check_expected_range,
    check_for_jumps,
    check_plausibility,
    check_ratio_against_components,
    summarise,
)
from macrofield.data.provenance import Basis, Frequency, ProvenanceRecord, Series, Valuation

TODAY = dt.date(2026, 7, 27)


def unitless_series(name: str, values, years=None) -> Series:
    if years is None:
        years = list(range(2010, 2010 + len(values)))
    return Series(
        name=name,
        values=pd.Series(values, index=pd.Index(years, name="year"), name=name),
        provenance=ProvenanceRecord(
            source="Test Source",
            dataset="Test dataset",
            identifier=f"TEST.{name}",
            url="https://example.invalid",
            retrieved_on=TODAY,
            units="ratio",
            basis=Basis.UNITLESS,
            frequency=Frequency.ANNUAL,
        ),
    )


class TestRangeDefinitions:
    def test_every_range_records_its_source(self):
        """An untraceable bound hardens into a fact, so a source is mandatory."""
        for bound in EXPECTED_RANGES:
            assert bound.source, bound.quantity

    def test_every_range_is_ordered(self):
        for bound in EXPECTED_RANGES:
            assert bound.low < bound.high, bound.quantity
            if bound.impossible_below is not None:
                assert bound.impossible_below <= bound.low, bound.quantity
            if bound.impossible_above is not None:
                assert bound.impossible_above >= bound.high, bound.quantity

    def test_quantities_are_unique(self):
        names = [b.quantity for b in EXPECTED_RANGES]
        assert len(names) == len(set(names))

    def test_the_model_quantities_are_covered(self):
        for quantity in ("K_R_over_Y", "K_I_over_Y", "saturation", "p_s", "depreciation_rate"):
            assert quantity in RANGES_BY_QUANTITY


class TestExpectedRange:
    def test_a_normal_series_passes_quietly(self):
        report = check_expected_range(unitless_series("saturation", [2.4, 2.5, 2.6, 2.55]))
        assert report.ok
        assert not report.warnings

    def test_warns_outside_the_ordinary_range(self):
        report = check_expected_range(unitless_series("saturation", [2.4, 2.5, 5.2]))
        assert report.ok  # a warning, not a failure
        assert any("outside the expected range" in f.check for f in report.warnings)

    def test_the_warning_records_where_the_range_came_from(self):
        report = check_expected_range(unitless_series("saturation", [5.2]))
        assert any("BIS" in f.detail for f in report.warnings)

    def test_the_warning_says_a_breach_may_be_the_interesting_case(self):
        """The framework's thesis is that economies leave the ordinary range, so the check must not read
        as an instruction to discard the value."""
        report = check_expected_range(unitless_series("saturation", [5.2]))
        assert any("interesting case" in f.detail for f in report.warnings)

    def test_fails_on_an_impossible_value(self):
        report = check_expected_range(unitless_series("K_R_over_Y", [3.3, -1.0]))
        assert not report.ok
        assert any("impossible value" in f.check for f in report.failures)

    def test_fails_on_an_impossibly_high_value(self):
        report = check_expected_range(unitless_series("p_s", [0.2, 4.0]))
        assert not report.ok

    def test_reports_when_no_range_is_configured(self):
        report = check_expected_range(unitless_series("some_new_quantity", [1.0, 2.0]))
        assert report.ok
        assert any("no expected range configured" in f.check for f in report.findings)

    def test_an_explicit_range_overrides_the_default(self):
        bound = ExpectedRange("saturation", low=0.0, high=10.0, source="test override")
        report = check_expected_range(unitless_series("saturation", [5.2]), bound)
        assert not report.warnings

    def test_an_empty_series_is_not_judged(self):
        empty = Series(
            name="saturation",
            values=pd.Series([np.nan], index=[2020]),
            provenance=unitless_series("saturation", [1.0]).provenance,
        )
        assert check_expected_range(empty).ok


class TestTheIndiaCase:
    """The reading that prompted this module: 267 per cent of GDP where published figures are near 130."""

    def test_the_india_equity_reading_is_flagged(self):
        series = unitless_series(
            "equity_market_cap_over_Y",
            [0.75, 0.88, 0.95, 1.05, 1.20, 1.31, 2.67],
        )
        report = check_expected_range(series)
        assert any("outside the expected range" in f.check for f in report.warnings)

    def test_the_integrity_checks_alone_would_have_passed_it(self):
        """Demonstrates the gap this module fills: the series is real, moving and unremarkable."""
        from macrofield.data.integrity import detect_synthetic_patterns

        series = unitless_series(
            "equity_market_cap_over_Y",
            [0.75, 0.88, 0.95, 1.05, 1.20, 1.31, 2.67],
        )
        assert detect_synthetic_patterns(series).ok

    def test_the_jump_check_also_catches_it(self):
        """Two independent checks catch the same reading, which is the point of having both."""
        series = unitless_series(
            "equity_market_cap_over_Y",
            [0.70, 0.75, 0.80, 0.88, 0.95, 1.05, 1.10, 1.20, 1.31, 2.67],
        )
        report = check_for_jumps(series)
        assert any("abrupt level change" in f.check for f in report.warnings)


class TestJumpDetection:
    def test_a_smooth_series_passes(self):
        values = [2.0 + 0.05 * i for i in range(12)]
        assert not check_for_jumps(unitless_series("saturation", values)).warnings

    def test_detects_a_units_change(self):
        """A hundred-fold jump is what a percent-against-ratio mix-up looks like mid-series."""
        values = [2.0, 2.1, 2.2, 2.15, 2.25, 2.3, 2.35, 2.4, 240.0, 245.0]
        report = check_for_jumps(unitless_series("saturation", values))
        assert any("abrupt level change" in f.check for f in report.warnings)

    def test_scales_to_the_series_own_variability(self):
        """A volatile series should not fire on changes that are normal for it."""
        volatile = [0.02, -0.05, 0.06, -0.04, 0.05, -0.06, 0.04, -0.03, 0.05, -0.05]
        assert not check_for_jumps(unitless_series("output_growth", volatile)).warnings

    def test_short_series_is_not_judged(self):
        assert not check_for_jumps(unitless_series("saturation", [2.0, 9.0])).findings

    def test_a_flat_series_is_not_judged(self):
        """No typical change means no scale to compare against, so the check declines to fire."""
        assert not check_for_jumps(unitless_series("saturation", [2.0] * 10)).findings


class TestRatioAgainstComponents:
    def _components(self):
        numerator = unitless_series("K_R", [300.0, 320.0, 330.0])
        denominator = unitless_series("Y", [100.0, 100.0, 110.0])
        return numerator, denominator

    def test_a_correct_ratio_passes(self):
        numerator, denominator = self._components()
        ratio = unitless_series("K_R_over_Y", [3.0, 3.2, 3.0])
        assert check_ratio_against_components(ratio, numerator, denominator).ok

    def test_detects_a_ratio_built_from_the_wrong_pair(self):
        numerator, denominator = self._components()
        wrong = unitless_series("K_R_over_Y", [3.0, 3.2, 5.0])
        report = check_ratio_against_components(wrong, numerator, denominator)
        assert not report.ok
        assert any("does not match its components" in f.check for f in report.failures)

    def test_only_overlapping_periods_are_compared(self):
        """An extended ratio legitimately runs past its components."""
        numerator, denominator = self._components()
        extended = unitless_series("K_R_over_Y", [3.0, 3.2, 3.0, 2.95, 2.9])
        assert check_ratio_against_components(extended, numerator, denominator).ok

    def test_warns_when_there_is_no_overlap(self):
        numerator, denominator = self._components()
        disjoint = unitless_series("K_R_over_Y", [3.0, 3.1], years=[2030, 2031])
        report = check_ratio_against_components(disjoint, numerator, denominator)
        assert any("no overlap" in f.check for f in report.warnings)


class TestCombined:
    def test_runs_every_check_over_a_set(self):
        report = check_plausibility(
            [
                unitless_series("saturation", [2.4, 2.5, 2.6]),
                unitless_series("p_s", [0.2, 0.21, 0.22]),
            ]
        )
        assert report.ok

    def test_summary_separates_impossible_from_questionable(self):
        report = check_plausibility(
            [
                unitless_series("saturation", [5.2]),
                unitless_series("p_s", [4.0]),
            ]
        )
        summary = summarise(report)
        assert summary["impossible"]
        assert summary["questionable"]
        assert summary["verdict"] == "impossible values present"

    def test_summary_lists_unbounded_quantities(self):
        report = check_plausibility([unitless_series("novel_quantity", [1.0, 2.0])])
        assert "novel_quantity" in summarise(report)["unbounded_quantities"]

    def test_a_clean_set_reports_no_impossible_values(self):
        report = check_plausibility([unitless_series("saturation", [2.4, 2.5])])
        assert summarise(report)["verdict"] == "no impossible values"
