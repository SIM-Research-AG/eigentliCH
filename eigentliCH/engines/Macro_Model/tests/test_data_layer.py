"""Tests for the data layer: provenance, integrity, cache, manifest and quantity assembly.

The integrity tests are the ones brief section 2 requires: the build must fail if any placeholder,
dummy or obviously synthetic value reaches the model inputs.
"""

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from macrofield.data.integrity import (
    SENTINEL_VALUES,
    Severity,
    SyntheticDataError,
    check_consistency,
    check_model_inputs,
    check_series,
    detect_synthetic_patterns,
)
from macrofield.data.loaders import (
    LoaderError,
    assemble_financial_capital,
    determine_window,
    extend_capital_ratio_by_perpetual_inventory,
    extend_capital_stock_by_perpetual_inventory,
    numeric_derivative,
    resolve_depreciation_rate,
    to_ratio_of_gdp,
)
from macrofield.data.manifest import (
    MANIFEST_VERSION,
    Cache,
    CacheError,
    Manifest,
    OfflineError,
    request_key,
)
from macrofield.data.provenance import (
    Basis,
    Frequency,
    ProvenanceRecord,
    Reliability,
    Series,
    Valuation,
    align,
)

TODAY = dt.date(2026, 7, 27)


def record(
    identifier="TEST.ID",
    basis=Basis.NOMINAL,
    currency="USD",
    reliability=Reliability.PUBLISHED,
    frequency=Frequency.ANNUAL,
    source="Test Source",
    valuation=None,
) -> ProvenanceRecord:
    if valuation is None:
        valuation = Valuation.MARKET if currency is not None else Valuation.NOT_APPLICABLE
    return ProvenanceRecord(
        source=source,
        dataset="Test dataset",
        identifier=identifier,
        url="https://example.invalid/series",
        retrieved_on=TODAY,
        units="current US dollars",
        basis=basis,
        frequency=frequency,
        currency=currency,
        valuation=valuation,
        reliability=reliability,
        licence="test licence",
    )


def series(name="Y", values=None, years=None, **kwargs) -> Series:
    """A plausible, non-synthetic economic series unless overridden."""
    if values is None:
        # Irregular growth, so the synthetic detectors stay quiet.
        values = [100.0, 103.7, 106.2, 111.9, 114.3, 119.8, 121.4, 128.6, 133.1, 139.7]
    if years is None:
        years = list(range(2010, 2010 + len(values)))
    data = pd.Series(values, index=pd.Index(years, name="year"), name=name)
    return Series(name=name, values=data, provenance=record(**kwargs))


class TestProvenanceRecord:
    def test_monetary_series_must_state_a_currency(self):
        with pytest.raises(ValueError, match="declares no currency"):
            ProvenanceRecord(
                source="s",
                dataset="d",
                identifier="i",
                url="u",
                retrieved_on=TODAY,
                units="dollars",
                basis=Basis.NOMINAL,
                frequency=Frequency.ANNUAL,
                currency=None,
            )

    def test_unitless_series_needs_no_currency(self):
        unitless = ProvenanceRecord(
            source="s",
            dataset="d",
            identifier="i",
            url="u",
            retrieved_on=TODAY,
            units="ratio",
            basis=Basis.UNITLESS,
            frequency=Frequency.ANNUAL,
        )
        assert unitless.currency is None
        assert unitless.valuation is Valuation.NOT_APPLICABLE

    def test_monetary_series_must_state_its_valuation(self):
        """PPP and market-rate series both look like real US dollars, so the distinction must be
        declared rather than inferred."""
        with pytest.raises(ValueError, match="valuation"):
            ProvenanceRecord(
                source="s",
                dataset="d",
                identifier="i",
                url="u",
                retrieved_on=TODAY,
                units="2017 US dollars",
                basis=Basis.REAL,
                frequency=Frequency.ANNUAL,
                currency="USD",
            )

    def test_requires_a_source_and_identifier(self):
        with pytest.raises(ValueError, match="source and an identifier"):
            ProvenanceRecord(
                source="",
                dataset="d",
                identifier="",
                url="u",
                retrieved_on=TODAY,
                units="u",
                basis=Basis.UNITLESS,
                frequency=Frequency.ANNUAL,
            )

    def test_transformations_accumulate_in_order(self):
        first = record().with_transformation("a", "did a")
        second = first.with_transformation("b", "did b")
        assert [t.operation for t in second.transformations] == ["a", "b"]

    def test_round_trips_through_a_dict(self):
        original = record().with_transformation("scale", "multiplied by 0.01")
        restored = ProvenanceRecord.from_dict(original.as_dict())
        assert restored == original

    def test_frequency_knows_its_annual_rate(self):
        assert Frequency.ANNUAL.per_year == 1.0
        assert Frequency.QUARTERLY.per_year == 4.0


class TestSeries:
    def test_rejects_duplicate_periods(self):
        values = pd.Series([1.0, 2.0], index=[2020, 2020])
        with pytest.raises(ValueError, match="duplicate periods"):
            Series(name="Y", values=values, provenance=record())

    def test_rejects_unsorted_periods(self):
        values = pd.Series([1.0, 2.0], index=[2021, 2020])
        with pytest.raises(ValueError, match="sorted by period"):
            Series(name="Y", values=values, provenance=record())

    def test_transformation_is_recorded_and_does_not_mutate(self):
        original = series()
        scaled = original.scaled(0.01, "percent to ratio")
        assert scaled.values.iloc[0] == pytest.approx(1.0)
        assert original.values.iloc[0] == pytest.approx(100.0)
        assert scaled.provenance.transformations[-1].operation == "scale"

    def test_restriction_records_the_window(self):
        restricted = series().restricted_to(2012, 2015)
        assert restricted.first_period == 2012
        assert restricted.last_period == 2015
        assert "restrict_window" in [t.operation for t in restricted.provenance.transformations]


class TestGapReport:
    def test_no_gaps_in_a_complete_series(self):
        assert not series().gap_report().has_gaps

    def test_finds_an_interior_gap(self):
        values = pd.Series(
            [100.0, np.nan, np.nan, 110.0], index=[2020, 2021, 2022, 2023]
        )
        report = Series("Y", values, record()).gap_report()
        assert report.has_gaps
        assert report.longest_interior_gap == 2
        assert report.interior_gaps == ((2021, 2022),)
        assert report.leading_missing == 0
        assert report.trailing_missing == 0

    def test_distinguishes_leading_and_trailing_from_interior(self):
        """A trailing gap is an extrapolation question, not an interpolation one, so they must not be
        conflated."""
        values = pd.Series([np.nan, 100.0, np.nan], index=[2020, 2021, 2022])
        report = Series("Y", values, record()).gap_report()
        assert report.leading_missing == 1
        assert report.trailing_missing == 1
        assert report.interior_gaps == ()

    def test_detects_a_hole_against_the_expected_range(self):
        values = pd.Series([100.0, 110.0], index=[2020, 2023])
        report = Series("Y", values, record()).gap_report()
        assert report.missing_periods == (2021, 2022)


class TestSyntheticDetection:
    """Brief section 2: a placeholder, dummy or obviously synthetic value must fail the build."""

    def test_accepts_a_plausible_series(self):
        assert detect_synthetic_patterns(series()).ok

    def test_rejects_a_constant_series(self):
        constant = series(values=[100.0] * 10)
        report = detect_synthetic_patterns(constant)
        assert not report.ok
        assert any("constant" in f.check for f in report.failures)

    def test_rejects_all_zeros(self):
        report = detect_synthetic_patterns(series(values=[0.0] * 10))
        assert not report.ok
        assert any("all zero" in f.check for f in report.failures)

    def test_rejects_a_perfectly_linear_ramp(self):
        ramp = series(values=[100.0 + 5.0 * i for i in range(10)])
        report = detect_synthetic_patterns(ramp)
        assert not report.ok
        assert any("linear" in f.check for f in report.failures)

    def test_rejects_a_perfectly_exponential_series(self):
        geometric = series(values=[100.0 * 1.03**i for i in range(10)])
        report = detect_synthetic_patterns(geometric)
        assert not report.ok
        assert any("exponential" in f.check for f in report.failures)

    @pytest.mark.parametrize("sentinel", SENTINEL_VALUES)
    def test_rejects_missing_value_sentinels(self, sentinel):
        values = [100.0, 103.7, sentinel, 111.9, 114.3, 119.8, 121.4]
        report = detect_synthetic_patterns(series(values=values))
        assert not report.ok
        assert any("sentinel" in f.check for f in report.failures)

    def test_rejects_a_hand_typed_placeholder_sequence(self):
        values = [87.3, 1.0, 2.0, 3.0, 4.0, 5.0, 93.1]
        report = detect_synthetic_patterns(series(values=values))
        assert not report.ok
        assert any("placeholder" in f.check for f in report.failures)

    def test_warns_on_implausibly_round_values(self):
        values = [100.0, 105.0, 110.0, 113.0, 121.0, 126.0, 130.0, 137.0, 141.0, 149.0, 152.0]
        report = detect_synthetic_patterns(series(values=values))
        # Not linear, so not a failure, but every value is whole.
        assert report.ok
        assert any("round" in f.check for f in report.warnings)

    def test_rejects_an_entirely_missing_series(self):
        values = pd.Series([np.nan, np.nan], index=[2020, 2021])
        report = detect_synthetic_patterns(Series("Y", values, record()))
        assert not report.ok

    def test_short_series_is_not_judged_by_the_statistical_checks(self):
        report = detect_synthetic_patterns(series(values=[100.0, 103.0, 107.0]))
        assert report.ok
        assert any("too short" in f.check for f in report.findings)


class TestDeclaredReliability:
    def test_synthetic_always_fails(self):
        report = check_series(series(reliability=Reliability.SYNTHETIC))
        assert not report.ok
        assert any("synthetic" in f.check for f in report.failures)

    def test_synthetic_cannot_be_opted_into(self):
        """There is deliberately no flag that admits a synthetic series."""
        report = check_series(
            series(reliability=Reliability.SYNTHETIC),
            allow_derived=True,
            allow_interpolated=True,
        )
        assert not report.ok

    def test_derived_fails_unless_permitted(self):
        assert not check_series(series(reliability=Reliability.DERIVED)).ok
        assert check_series(series(reliability=Reliability.DERIVED), allow_derived=True).ok

    def test_interpolated_fails_unless_permitted(self):
        assert not check_series(series(reliability=Reliability.INTERPOLATED)).ok
        assert check_series(
            series(reliability=Reliability.INTERPOLATED), allow_interpolated=True
        ).ok

    def test_permitted_derived_series_is_recorded_as_information(self):
        report = check_series(series(reliability=Reliability.DERIVED), allow_derived=True)
        assert any(f.severity is Severity.INFO for f in report.findings)


class TestCheckModelInputs:
    def test_passes_clean_inputs(self):
        report = check_model_inputs([series("Y"), series("K_R")])
        assert report.ok

    def test_raises_on_a_synthetic_input(self):
        with pytest.raises(SyntheticDataError, match="integrity problem"):
            check_model_inputs([series("Y"), series("K_R", reliability=Reliability.SYNTHETIC)])

    def test_error_names_the_offending_series(self):
        with pytest.raises(SyntheticDataError, match="K_R"):
            check_model_inputs([series("K_R", values=[7.0] * 10)])

    def test_strict_mode_promotes_warnings_to_failures(self):
        round_values = [100.0, 105.0, 110.0, 113.0, 121.0, 126.0, 130.0, 137.0, 141.0, 149.0, 152.0]
        assert check_model_inputs([series(values=round_values)]).ok
        with pytest.raises(SyntheticDataError):
            check_model_inputs([series(values=round_values)], strict=True)


class TestConsistency:
    def test_mixed_currencies_fail(self):
        report = check_consistency([series("Y", currency="USD"), series("K_R", currency="EUR")])
        assert not report.ok
        assert any("currencies" in f.check for f in report.failures)

    def test_mixed_nominal_and_real_fail(self):
        report = check_consistency(
            [series("Y", basis=Basis.NOMINAL), series("K_R", basis=Basis.REAL)]
        )
        assert not report.ok
        assert any("nominal and real" in f.check for f in report.failures)

    def test_mixed_frequencies_fail(self):
        report = check_consistency(
            [
                series("Y", frequency=Frequency.ANNUAL),
                series("K_R", frequency=Frequency.QUARTERLY),
            ]
        )
        assert not report.ok
        assert any("frequencies" in f.check for f in report.failures)

    def test_unknown_basis_fails(self):
        report = check_consistency(
            [series("Y"), series("K_R", basis=Basis.UNKNOWN, currency="USD")]
        )
        assert not report.ok
        assert any("basis not stated" in f.check for f in report.failures)

    def test_consistent_series_pass(self):
        assert check_consistency([series("Y"), series("K_R")]).ok

    def test_a_unitless_series_does_not_trip_the_currency_check(self):
        report = check_consistency(
            [series("Y"), series("saturation", basis=Basis.UNITLESS, currency=None)]
        )
        assert report.ok

    def test_mixing_ppp_and_market_valuation_fails(self):
        """The hazard the currency and basis checks miss. Penn World Table capital stocks are PPP
        converted; World Bank GDP is at market rates. Both are real US dollars, so nothing else
        catches it, yet the ratio would be meaningless."""
        report = check_consistency(
            [
                series("Y", basis=Basis.REAL, currency="USD", valuation=Valuation.MARKET),
                series("K_R", basis=Basis.REAL, currency="USD", valuation=Valuation.PPP),
            ]
        )
        assert not report.ok
        assert any("PPP and market-rate" in f.check for f in report.failures)

    def test_the_currency_and_basis_checks_alone_would_have_passed_that_pair(self):
        """Demonstrates why the valuation field was needed: the pair is identical on every other axis."""
        market = series("Y", basis=Basis.REAL, currency="USD", valuation=Valuation.MARKET)
        ppp = series("K_R", basis=Basis.REAL, currency="USD", valuation=Valuation.PPP)
        assert market.provenance.currency == ppp.provenance.currency
        assert market.provenance.basis is ppp.provenance.basis
        assert market.provenance.frequency is ppp.provenance.frequency

    def test_two_ppp_series_are_consistent(self):
        report = check_consistency(
            [
                series("K_R", basis=Basis.REAL, currency="USD", valuation=Valuation.PPP),
                series("Y_ppp", basis=Basis.REAL, currency="USD", valuation=Valuation.PPP),
            ]
        )
        assert report.ok


class TestAlign:
    def test_inner_join_keeps_only_shared_periods(self):
        first = series("Y", values=[1.0, 2.0, 3.0], years=[2020, 2021, 2022])
        second = series("K_R", values=[4.0, 5.0], years=[2021, 2022])
        aligned = align([first, second], how="inner")
        assert list(aligned["Y"].index) == [2021, 2022]

    def test_rejects_duplicate_quantity_names(self):
        with pytest.raises(ValueError, match="duplicate quantity names"):
            align([series("Y"), series("Y")])


class TestPerpetualInventoryExtension:
    def _stock_and_flows(self):
        stock = series("K_R", values=[300.0, 311.0, 319.0], years=[2018, 2019, 2020])
        flows = series("gfcf", values=[62.0, 64.0, 61.0, 67.0, 71.0], years=[2018, 2019, 2020, 2021, 2022])
        return stock, flows

    def test_extends_by_the_recursion(self):
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        assert extended.last_period == 2022
        expected_2021 = 0.95 * 319.0 + 67.0
        assert extended.values.loc[2021] == pytest.approx(expected_2021)
        assert extended.values.loc[2022] == pytest.approx(0.95 * expected_2021 + 71.0)

    def test_published_values_are_untouched(self):
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        assert extended.values.loc[2020] == pytest.approx(319.0)

    def test_result_is_marked_derived(self):
        """So that the integrity check refuses it unless a caller opts in."""
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        assert extended.provenance.reliability is Reliability.DERIVED
        assert not check_series(extended).ok
        assert check_series(extended, allow_derived=True).ok

    def test_records_the_rate_and_the_range(self):
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        detail = extended.provenance.transformations[-1].detail
        assert "0.05" in detail
        assert "2020 to 2022" in detail

    def test_refuses_to_extend_across_a_gap_in_investment(self):
        """Extending over a missing flow would be an interpolation in disguise."""
        stock = series("K_R", values=[300.0, 311.0], years=[2018, 2019])
        flows = series("gfcf", values=[62.0, 64.0, 71.0], years=[2018, 2019, 2022])
        with pytest.raises(LoaderError, match="missing for"):
            extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05, through_period=2022)

    @pytest.mark.parametrize("rate", [0.0, 1.0, -0.1, 1.5])
    def test_rejects_an_impossible_depreciation_rate(self, rate):
        stock, flows = self._stock_and_flows()
        with pytest.raises(LoaderError, match="depreciation rate"):
            extend_capital_stock_by_perpetual_inventory(stock, flows, rate)

    def test_rejects_inconsistent_currency(self):
        stock = series("K_R", values=[300.0, 311.0], years=[2018, 2019], currency="USD")
        flows = series("gfcf", values=[62.0, 64.0, 61.0], years=[2018, 2019, 2020], currency="EUR")
        with pytest.raises(LoaderError, match="not consistent"):
            extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)

    def test_returns_unchanged_when_nothing_to_extend(self):
        stock, flows = self._stock_and_flows()
        unchanged = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05, through_period=2019)
        assert unchanged.last_period == 2020

    def test_published_depreciation_rate_is_preferred_over_the_prior(self):
        """Penn World Table publishes delta per country per year, and it is the rate the source itself
        used to build the stock being extended."""
        stock, flows = self._stock_and_flows()
        published = series(
            "depreciation_rate",
            values=[0.041, 0.042, 0.043, 0.044, 0.045],
            years=[2018, 2019, 2020, 2021, 2022],
            basis=Basis.UNITLESS,
            currency=None,
        )
        extended = extend_capital_stock_by_perpetual_inventory(
            stock, flows, 0.05, published_depreciation=published
        )
        # 2021 must use the published 0.044, not the 0.05 prior.
        assert extended.values.loc[2021] == pytest.approx(0.956 * 319.0 + 67.0)
        detail = extended.provenance.transformations[-1].detail
        assert "published rate for 2021" in detail

    def test_the_prior_is_used_only_where_no_published_rate_exists(self):
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        detail = extended.provenance.transformations[-1].detail
        assert "configured prior" in detail

    def test_every_applied_rate_is_recorded(self):
        stock, flows = self._stock_and_flows()
        extended = extend_capital_stock_by_perpetual_inventory(stock, flows, 0.05)
        detail = extended.provenance.transformations[-1].detail
        assert "2021:" in detail
        assert "2022:" in detail


class TestRatioSpaceExtension:
    """The preferred extension route: every input unitless, so no valuation conversion arises."""

    def _inputs(self):
        ratio = series(
            "K_R_over_Y",
            values=[3.30, 3.34, 3.36],
            years=[2017, 2018, 2019],
            basis=Basis.UNITLESS,
            currency=None,
        )
        share = series(
            "investment_share",
            values=[0.21, 0.215, 0.22, 0.218, 0.223],
            years=[2017, 2018, 2019, 2020, 2021],
            basis=Basis.UNITLESS,
            currency=None,
        )
        growth = series(
            "output_growth",
            values=[0.023, 0.029, 0.023, -0.028, 0.059],
            years=[2017, 2018, 2019, 2020, 2021],
            basis=Basis.UNITLESS,
            currency=None,
        )
        return ratio, share, growth

    def test_applies_the_ratio_recursion(self):
        ratio, share, growth = self._inputs()
        extended = extend_capital_ratio_by_perpetual_inventory(ratio, share, growth, 0.05)
        expected_2020 = (1.0 - 0.05) * 3.36 / (1.0 - 0.028) + 0.218
        assert extended.values.loc[2020] == pytest.approx(expected_2020)

    def test_contraction_raises_the_capital_ratio(self):
        """Falling output with steady investment must raise K_R/Y. This is the behaviour that makes the
        ratio route economically meaningful rather than merely convenient."""
        ratio, share, growth = self._inputs()
        extended = extend_capital_ratio_by_perpetual_inventory(ratio, share, growth, 0.05)
        assert extended.values.loc[2020] > extended.values.loc[2019]

    def test_published_values_are_untouched(self):
        ratio, share, growth = self._inputs()
        extended = extend_capital_ratio_by_perpetual_inventory(ratio, share, growth, 0.05)
        assert extended.values.loc[2019] == pytest.approx(3.36)

    def test_result_is_marked_derived(self):
        ratio, share, growth = self._inputs()
        extended = extend_capital_ratio_by_perpetual_inventory(ratio, share, growth, 0.05)
        assert extended.provenance.reliability is Reliability.DERIVED
        assert not check_series(extended).ok
        assert check_series(extended, allow_derived=True).ok

    def test_records_every_step(self):
        ratio, share, growth = self._inputs()
        extended = extend_capital_ratio_by_perpetual_inventory(ratio, share, growth, 0.05)
        detail = extended.provenance.transformations[-1].detail
        assert "2020: delta=" in detail
        assert "g=-0.0280" in detail
        assert "no currency" in detail

    def test_prefers_the_published_depreciation_rate(self):
        ratio, share, growth = self._inputs()
        published = series(
            "depreciation_rate",
            values=[0.046, 0.047],
            years=[2019, 2020],
            basis=Basis.UNITLESS,
            currency=None,
        )
        extended = extend_capital_ratio_by_perpetual_inventory(
            ratio, share, growth, 0.05, published_depreciation=published
        )
        expected = (1.0 - 0.047) * 3.36 / (1.0 - 0.028) + 0.218
        assert extended.values.loc[2020] == pytest.approx(expected)

    @pytest.mark.parametrize("bad_input", ["ratio", "share", "growth"])
    def test_rejects_a_series_that_is_not_unitless(self, bad_input):
        """The whole point of this route is that nothing carries a currency."""
        ratio, share, growth = self._inputs()
        monetary = series("bad", values=[1.0, 2.0, 3.0], years=[2017, 2018, 2019])
        args = {"ratio": ratio, "share": share, "growth": growth}
        args[bad_input] = monetary
        with pytest.raises(LoaderError, match="must be unitless"):
            extend_capital_ratio_by_perpetual_inventory(
                args["ratio"], args["share"], args["growth"], 0.05
            )

    def test_refuses_to_extend_across_a_gap(self):
        ratio, share, growth = self._inputs()
        gapped = series(
            "investment_share",
            values=[0.21, 0.22, 0.223],
            years=[2017, 2019, 2021],
            basis=Basis.UNITLESS,
            currency=None,
        )
        with pytest.raises(LoaderError, match="missing for"):
            extend_capital_ratio_by_perpetual_inventory(
                ratio, gapped, growth, 0.05, through_period=2021
            )

    def test_rejects_growth_that_wipes_out_output(self):
        ratio, share, _ = self._inputs()
        impossible = series(
            "output_growth",
            values=[0.02, 0.02, 0.02, -1.0],
            years=[2017, 2018, 2019, 2020],
            basis=Basis.UNITLESS,
            currency=None,
        )
        with pytest.raises(LoaderError, match="makes the ratio recursion undefined"):
            extend_capital_ratio_by_perpetual_inventory(ratio, share, impossible, 0.05)

    def test_returns_unchanged_when_nothing_to_extend(self):
        ratio, share, growth = self._inputs()
        unchanged = extend_capital_ratio_by_perpetual_inventory(
            ratio, share, growth, 0.05, through_period=2019
        )
        assert unchanged.last_period == 2019
        assert unchanged.provenance.reliability is Reliability.PUBLISHED


class TestResolveDepreciationRate:
    def _published(self):
        return series(
            "depreciation_rate",
            values=[0.040, 0.045],
            years=[2018, 2019],
            basis=Basis.UNITLESS,
            currency=None,
        )

    def test_uses_the_published_rate_for_the_period(self):
        rate, origin = resolve_depreciation_rate(self._published(), 0.05, 2019)
        assert rate == pytest.approx(0.045)
        assert "published rate for 2019" in origin

    def test_carries_the_last_published_rate_forward(self):
        """The source's rate for a neighbouring year beats a hand-set constant."""
        rate, origin = resolve_depreciation_rate(self._published(), 0.05, 2024)
        assert rate == pytest.approx(0.045)
        assert "carried forward" in origin

    def test_falls_back_to_the_prior_before_the_published_range(self):
        rate, origin = resolve_depreciation_rate(self._published(), 0.05, 2010)
        assert rate == pytest.approx(0.05)
        assert "configured prior" in origin

    def test_falls_back_to_the_prior_when_nothing_is_published(self):
        rate, origin = resolve_depreciation_rate(None, 0.05, 2021)
        assert rate == pytest.approx(0.05)
        assert "configured prior" in origin

    def test_rejects_an_impossible_resolved_rate(self):
        stock = series("K_R", values=[300.0, 311.0, 319.0], years=[2018, 2019, 2020])
        flows = series("gfcf", values=[62.0, 64.0, 61.0, 67.0], years=[2018, 2019, 2020, 2021])
        bad = series(
            "depreciation_rate",
            values=[1.4, 1.5],
            years=[2020, 2021],
            basis=Basis.UNITLESS,
            currency=None,
        )
        with pytest.raises(LoaderError, match="not a proper fraction"):
            extend_capital_stock_by_perpetual_inventory(
                stock, flows, 0.05, published_depreciation=bad
            )


class TestFinancialCapitalAssembly:
    def test_prefers_the_chapter_ten_measure(self):
        assembled = assemble_financial_capital(
            consolidated_assets=series("financial_assets", values=[500.0, 520.0, 545.0], years=[2020, 2021, 2022]),
            total_credit=series("credit", values=[250.0, 260.0, 271.0], years=[2020, 2021, 2022]),
            listed_equity=series("equity", values=[200.0, 210.0, 219.0], years=[2020, 2021, 2022]),
        )
        assert assembled.measure == "consolidated_financial_assets"
        assert assembled.series.values.iloc[0] == pytest.approx(500.0)

    def test_falls_back_to_credit_plus_equity(self):
        assembled = assemble_financial_capital(
            consolidated_assets=None,
            total_credit=series("credit", values=[250.0, 260.0, 271.0], years=[2020, 2021, 2022]),
            listed_equity=series("equity", values=[200.0, 210.0, 219.0], years=[2020, 2021, 2022]),
        )
        assert assembled.measure == "credit_plus_listed_equity"
        assert assembled.series.values.iloc[0] == pytest.approx(450.0)

    def test_fallback_records_that_it_is_not_like_for_like(self):
        assembled = assemble_financial_capital(
            consolidated_assets=None,
            total_credit=series("credit", values=[250.0, 260.0, 271.0], years=[2020, 2021, 2022]),
            listed_equity=series("equity", values=[200.0, 210.0, 219.0], years=[2020, 2021, 2022]),
        )
        assert any("not like for like" in note for note in assembled.notes)

    def test_fallback_documents_the_double_counting_exclusion(self):
        assembled = assemble_financial_capital(
            consolidated_assets=None,
            total_credit=series("credit", values=[250.0, 260.0, 271.0], years=[2020, 2021, 2022]),
            listed_equity=series("equity", values=[200.0, 210.0, 219.0], years=[2020, 2021, 2022]),
        )
        assert any("double counts" in note for note in assembled.series.provenance.notes)

    def test_fails_when_neither_measure_is_available(self):
        with pytest.raises(LoaderError, match="cannot be assembled"):
            assemble_financial_capital(None, None, None)

    def test_fallback_rejects_inconsistent_components(self):
        with pytest.raises(LoaderError, match="not consistent"):
            assemble_financial_capital(
                consolidated_assets=None,
                total_credit=series("credit", values=[250.0, 260.0, 271.0], years=[2020, 2021, 2022], currency="USD"),
                listed_equity=series("equity", values=[200.0, 210.0, 219.0], years=[2020, 2021, 2022], currency="EUR"),
            )


class TestSaturationConversion:
    def test_percent_to_ratio_is_logged(self):
        percent = series(
            "credit_to_gdp",
            values=[240.0, 250.0, 261.0, 255.0, 258.0, 262.0],
            basis=Basis.UNITLESS,
            currency=None,
        )
        ratio = to_ratio_of_gdp(percent, "saturation")
        assert ratio.values.iloc[0] == pytest.approx(2.40)
        assert ratio.name == "saturation"
        assert "percent of GDP to a ratio" in ratio.provenance.transformations[-1].detail

    def test_rejects_a_monetary_series(self):
        with pytest.raises(LoaderError, match="must be unitless"):
            to_ratio_of_gdp(series("credit", basis=Basis.NOMINAL), "saturation")


class TestWindow:
    def test_takes_the_overlap(self):
        first = series("Y", values=[1.0, 2.0, 3.0], years=[2018, 2019, 2020])
        second = series("K_R", values=[4.0, 5.0, 6.0], years=[2019, 2020, 2021])
        assert determine_window([first, second]) == (2019, 2020)

    def test_configured_window_narrows_the_overlap(self):
        s = series("Y", values=[1.0, 2.0, 3.0, 4.0], years=[2018, 2019, 2020, 2021])
        assert determine_window([s], configured_start=2019, configured_end=2020) == (2019, 2020)

    def test_rejects_a_configured_start_before_the_data(self):
        s = series("Y", values=[1.0, 2.0], years=[2019, 2020])
        with pytest.raises(LoaderError, match="before the data begins"):
            determine_window([s], configured_start=2015)

    def test_rejects_a_configured_end_after_the_data(self):
        s = series("Y", values=[1.0, 2.0], years=[2019, 2020])
        with pytest.raises(LoaderError, match="after the data ends"):
            determine_window([s], configured_end=2030)

    def test_rejects_non_overlapping_series(self):
        first = series("Y", values=[1.0, 2.0], years=[2010, 2011])
        second = series("K_R", values=[3.0, 4.0], years=[2020, 2021])
        with pytest.raises(LoaderError, match="do not overlap"):
            determine_window([first, second])


class TestNumericDerivative:
    def test_recovers_the_slope_of_a_line(self):
        years = np.arange(2000, 2020, dtype=float)
        values = 3.0 * years - 5000.0
        derivative = numeric_derivative(values, years)
        assert np.allclose(derivative, 3.0, atol=1e-8)

    def test_central_difference_matches_gradient(self):
        years = np.arange(2000, 2010, dtype=float)
        values = np.array([1.0, 4.0, 9.0, 16.0, 25.0, 36.0, 49.0, 64.0, 81.0, 100.0])
        derivative = numeric_derivative(values, years, method="central_difference")
        assert np.allclose(derivative, np.gradient(values, years))

    def test_smoothing_reduces_the_variance_of_a_noisy_derivative(self):
        rng = np.random.default_rng(20260727)
        years = np.arange(1980, 2020, dtype=float)
        values = 2.0 * (years - 1980.0) + rng.normal(0.0, 1.0, years.size)
        smooth = numeric_derivative(values, years, window_years=7)
        raw = numeric_derivative(values, years, method="central_difference")
        assert np.var(smooth) < np.var(raw)

    def test_refuses_to_differentiate_across_a_gap(self):
        years = np.arange(2000, 2010, dtype=float)
        values = np.arange(10, dtype=float)
        values[4] = np.nan
        with pytest.raises(LoaderError, match="gaps"):
            numeric_derivative(values, years)

    def test_rejects_an_unknown_method(self):
        with pytest.raises(LoaderError, match="unknown derivative method"):
            numeric_derivative(np.arange(5.0), np.arange(5.0), method="magic")

    def test_rejects_a_window_too_small_for_the_polynomial(self):
        with pytest.raises(LoaderError, match="too small for a polynomial"):
            numeric_derivative(
                np.arange(10.0), np.arange(10.0), window_years=3, polynomial_order=5
            )


class TestSecondDerivative:
    """The gold module's first driver is the acceleration of financial capital, so order 2 is needed."""

    def test_recovers_the_curvature_of_a_quadratic(self):
        years = np.arange(2000, 2020, dtype=float)
        values = 2.0 * (years - 2000.0) ** 2 + 5.0 * (years - 2000.0) + 1.0
        second = numeric_derivative(values, years, order=2)
        assert np.allclose(second, 4.0, atol=1e-6)

    def test_the_second_derivative_of_a_line_vanishes(self):
        years = np.arange(2000, 2020, dtype=float)
        second = numeric_derivative(3.0 * years - 5000.0, years, order=2)
        assert np.allclose(second, 0.0, atol=1e-8)

    def test_a_varying_curvature_survives_better_than_by_differentiating_twice(self):
        """Why `order=2` rather than calling the function on its own output.

        Differentiating twice applies the smoothing filter twice, and that damps a *varying* curvature.
        The case that matters is a cycle: the credit impulse is the acceleration of financial capital,
        which oscillates. Tested on an 18-year sinusoid, the credit cycle's own prior period.

        Note the trade-off runs the other way for a *constant* curvature, where the second smoothing pass
        costs no bias and the double route is the more accurate of the two. That is not the case this is
        used for, which is why the argument is stated in terms of attenuation rather than noise.
        """
        years = np.arange(0.0, 60.0)
        omega = 2.0 * np.pi / 18.0
        values = np.sin(omega * years)
        truth = -(omega**2) * np.sin(omega * years)

        direct = numeric_derivative(values, years, window_years=11, order=2)
        twice = numeric_derivative(
            numeric_derivative(values, years, window_years=11), years, window_years=11
        )

        interior = slice(11, -11)
        error = lambda a: float(np.sqrt(np.mean((a[interior] - truth[interior]) ** 2)))
        amplitude = lambda a: float(np.max(np.abs(a[interior])))

        assert error(direct) < error(twice)
        # The double route loses more than a third of the amplitude the direct route keeps.
        assert amplitude(twice) < 0.7 * amplitude(direct)

    def test_central_difference_applies_the_gradient_twice(self):
        years = np.arange(2000, 2010, dtype=float)
        values = np.arange(10, dtype=float) ** 2
        second = numeric_derivative(values, years, method="central_difference", order=2)
        assert np.allclose(second, np.gradient(np.gradient(values, years), years))

    def test_refuses_an_order_the_polynomial_cannot_carry(self):
        """A first-order polynomial has a zero second derivative everywhere, so the result would be
        identically zero rather than visibly wrong. That must be an error, not a silent flat line."""
        with pytest.raises(LoaderError, match="needs a local polynomial of at least"):
            numeric_derivative(np.arange(20.0) ** 2, np.arange(20.0), polynomial_order=1, order=2)

    def test_rejects_an_order_below_one(self):
        with pytest.raises(LoaderError, match="at least one"):
            numeric_derivative(np.arange(10.0), np.arange(10.0), order=0)


class TestCache:
    def test_writes_and_reads_a_payload(self, tmp_path):
        cache = Cache(tmp_path)
        key = request_key("World Bank", "NY.GDP.MKTP.CD", country="USA")
        cache.write(key, b'{"a": 1}', "https://example.invalid", "json", retrieved_on=TODAY)
        payload, entry = cache.read(key)
        assert payload == b'{"a": 1}'
        assert entry.retrieved_on == TODAY

    def test_request_key_is_order_independent(self):
        assert request_key("s", "i", a=1, b=2) == request_key("s", "i", b=2, a=1)

    def test_request_key_distinguishes_parameters(self):
        assert request_key("s", "i", start=1960) != request_key("s", "i", start=1990)

    def test_verifies_payload_integrity(self, tmp_path):
        cache = Cache(tmp_path)
        key = request_key("s", "i")
        entry = cache.write(key, b"original", "u", "json", retrieved_on=TODAY)
        assert cache.verify(key)
        entry.path.write_bytes(b"tampered")
        assert not cache.verify(key)

    def test_reports_stale_keys(self, tmp_path):
        cache = Cache(tmp_path)
        key = request_key("s", "i")
        cache.write(key, b"x", "u", "json", retrieved_on=dt.date(2026, 1, 1))
        assert cache.stale_keys(90, today=TODAY) == [key]
        assert cache.stale_keys(365, today=TODAY) == []

    def test_missing_key_raises(self, tmp_path):
        with pytest.raises(CacheError, match="nothing cached"):
            Cache(tmp_path).read("absent")

    def test_detects_an_index_without_its_payload(self, tmp_path):
        cache = Cache(tmp_path)
        key = request_key("s", "i")
        entry = cache.write(key, b"x", "u", "json", retrieved_on=TODAY)
        entry.path.unlink()
        with pytest.raises(CacheError, match="payload file"):
            cache.read(key)

    def test_offline_mode_names_what_is_missing(self, tmp_path):
        cache = Cache(tmp_path, offline=True)
        with pytest.raises(OfflineError, match="World Bank GDP"):
            cache.require_offline("key", "World Bank GDP for USA")

    def test_index_survives_a_reopen(self, tmp_path):
        key = request_key("s", "i")
        Cache(tmp_path).write(key, b"x", "u", "json", retrieved_on=TODAY)
        assert Cache(tmp_path).has(key)


class TestManifest:
    def test_records_a_series_with_its_provenance(self):
        manifest = Manifest()
        manifest.record("us", series("Y"))
        assert "us/Y" in manifest.entries
        assert manifest.provenance_of("us", "Y").identifier == "TEST.ID"

    def test_round_trips_through_disk(self, tmp_path):
        manifest = Manifest(config_sources=["config/defaults.yaml"], notes=["offline run"])
        manifest.record("us", series("Y"))
        path = tmp_path / "manifest.json"
        manifest.write(path)
        restored = Manifest.read(path)
        assert restored.entries.keys() == manifest.entries.keys()
        assert restored.notes == ["offline run"]

    def test_serialisation_is_byte_stable(self, tmp_path):
        """Brief section 7 requires offline runs to be bit-reproducible, so writing the same manifest
        twice must produce identical bytes."""
        manifest = Manifest()
        manifest.record("us", series("Y"))
        manifest.record("cn", series("K_R"))
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        manifest.write(first)
        manifest.write(second)
        assert first.read_bytes() == second.read_bytes()

    def test_series_are_sorted_regardless_of_insertion_order(self, tmp_path):
        forward, backward = Manifest(), Manifest()
        forward.record("us", series("Y"))
        forward.record("cn", series("K_R"))
        backward.record("cn", series("K_R"))
        backward.record("us", series("Y"))
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        forward.write(a)
        backward.write(b)
        assert a.read_bytes() == b.read_bytes()

    def test_rejects_a_manifest_from_another_format_version(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({"manifest_version": MANIFEST_VERSION + 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            Manifest.read(path)

    def test_unknown_series_raises_with_the_available_keys(self):
        manifest = Manifest()
        manifest.record("us", series("Y"))
        with pytest.raises(KeyError, match="Recorded"):
            manifest.provenance_of("us", "K_I")

    def test_summary_counts_reliabilities_and_gaps(self):
        manifest = Manifest()
        manifest.record("us", series("Y"))
        manifest.record("us", series("K_R", reliability=Reliability.DERIVED))
        gapped = pd.Series([1.0, np.nan, 3.0], index=[2020, 2021, 2022])
        manifest.record("us", Series("K_I", gapped, record()))
        summary = manifest.summary()
        assert summary["series_count"] == 3
        assert summary["reliability_counts"]["derived"] == 1
        assert "us/K_I" in summary["series_with_gaps"]
