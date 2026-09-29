"""Tests for cycle decomposition and phase synchrony, section 0.9."""

import numpy as np
import pytest

from macrofield import config as config_module
from macrofield.model.cycles import (
    MINIMUM_PERIODS_IN_SAMPLE,
    CycleBand,
    CycleError,
    anchor_capital_cycle,
    anchored_from_config,
    bands_from_config,
    decompose,
    detect_synchrony,
    extract_cycle,
    fixed_hegemonic_cycle,
    fixed_innovation_cycle,
    interference_members,
    spectrum,
)


def sine(years: int, period: float, phase: float = 0.0, amplitude: float = 1.0) -> np.ndarray:
    """An annual sine wave of a given period, for recovering a known answer."""
    t = np.arange(years, dtype=float)
    return amplitude * np.sin(2.0 * np.pi * t / period + phase)


class TestCycleBand:
    def test_band_brackets_the_prior(self):
        band = CycleBand.from_prior("credit", 18.0, band_fraction=0.4)
        assert band.low_period == pytest.approx(10.8)
        assert band.high_period == pytest.approx(25.2)
        assert band.low_period < band.prior_period < band.high_period

    def test_explicit_band_takes_its_prior_as_the_midpoint(self):
        band = CycleBand.from_explicit("innovation", 40.0, 54.0)
        assert band.prior_period == pytest.approx(47.0)

    def test_rejects_a_non_positive_prior(self):
        with pytest.raises(CycleError, match="positive prior period"):
            CycleBand.from_prior("credit", 0.0)

    @pytest.mark.parametrize("fraction", [0.0, 1.0, 1.5, -0.2])
    def test_rejects_an_out_of_range_band_fraction(self, fraction):
        with pytest.raises(CycleError, match="band_fraction"):
            CycleBand.from_prior("credit", 18.0, band_fraction=fraction)

    def test_rejects_an_inverted_explicit_band(self):
        with pytest.raises(CycleError, match="low_period below high_period"):
            CycleBand.from_explicit("innovation", 54.0, 40.0)


class TestBandsFromConfig:
    def test_only_the_short_cycles_are_band_passed(self):
        """The three long cycles are anchored instead, on the author's instructions of 2026-07-27 and
        2026-08-02.

        They cannot be estimated from any national-accounts sample: innovation needs about 94 years, capital
        about 180 and hegemonic about 260. Band-passing them returned a component that was not an estimate of
        them, which is why they were previously reported as unidentifiable and dropped out of synchrony.

        The fundamental pulse joined the band-pass set on 2026-08-02 so the cycle layer could carry all six
        cycles. It is a short cycle rather than a long one, but it sits near the annual sampling limit, which
        is why it takes an explicit narrowed band and is classified `marginal` downstream.
        """
        bands = bands_from_config(config_module.load())
        assert [b.name for b in bands] == ["fundamental_pulse", "business", "credit"]

    def test_priors_match_the_source_frequency_analysis(self):
        bands = {b.name: b for b in bands_from_config(config_module.load())}
        assert bands["business"].prior_period == pytest.approx(7.0)
        assert bands["credit"].prior_period == pytest.approx(18.0)

    def test_the_innovation_observed_band_is_retained_for_reference(self):
        """The 40 to 54 band is no longer band-passed, but it is what the anchored period is drawn from,
        so it must stay in the priors rather than being deleted along with the extraction."""
        priors = config_module.load().get("cycles.priors")
        assert priors["innovation_observed_band_years"] == [40.0, 54.0]
        assert priors["innovation_years"] == pytest.approx(36.0)

    def test_the_anchored_innovation_period_comes_from_the_observed_band(self):
        """The author supplied the trough and not the period, so the period is the observed band's
        midpoint, which is what bands_from_config used before. Changing it moves the phase."""
        anchored = config_module.load().get("cycles.anchored")
        low, high = config_module.load().get("cycles.priors")["innovation_observed_band_years"]
        assert anchored["innovation"]["period_years"] == pytest.approx((low + high) / 2.0)


class TestFixedHegemonicCycle:
    """The hegemonic cycle is supplied, with a high in 1945: the UK-to-US succession's completion.

    The only anchor pinned to a peak rather than a trough, which is the thing most likely to be broken by a
    later edit, so the sign convention is asserted directly rather than inferred from a synchrony result.
    """

    def test_the_peak_is_where_the_component_tops_out(self):
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(years, peak_year=1945, period_years=130.0)
        component = cycle.estimate.component
        assert years[int(np.argmax(component))] == 1945
        assert component[int(np.argmax(component))] == pytest.approx(1.0)
        assert cycle.estimate.phase[list(years).index(1945)] == pytest.approx(0.0)

    def test_the_trough_is_half_a_period_from_the_peak(self):
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(years, peak_year=1945, period_years=130.0)
        component = cycle.estimate.component
        assert years[int(np.argmin(component))] == 2010
        assert component[int(np.argmin(component))] == pytest.approx(-1.0)

    def test_1929_is_on_the_rising_limb_and_not_a_trough(self):
        """The load-bearing caveat on this anchor, asserted so it cannot quietly stop being true.

        The 1929 crash lies inside the supplied 1914-to-1945 succession interval, and a reader may reasonably
        expect the deepest dislocation of the era to sit at the slowest cycle's low. It does not: it is
        sixteen years before the peak, rising, at about +0.72. The distance between those two statements is
        why the module computes interference between cycles rather than reading one of them.
        """
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(years, peak_year=1945, period_years=130.0)
        at_1929 = cycle.estimate.component[list(years).index(1929)]
        assert at_1929 == pytest.approx(0.7156, abs=5e-5)
        assert at_1929 > 0.0, "1929 must not read as a hegemonic trough"
        assert at_1929 < cycle.estimate.component[list(years).index(1945)]

    def test_the_succession_interval_is_the_final_quarter_of_the_ascent(self):
        """1914 lands within a whisker of the rising zero crossing, which is what makes anchoring on the
        succession's *completion* coherent: the interval is the last quarter of the climb, from the point the
        new order becomes viable to the point it is consolidated. 31 of 130 years is 23.8%."""
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(
            years, peak_year=1945, period_years=130.0, succession_from=1914, succession_to=1945
        )
        at_1914 = cycle.estimate.component[list(years).index(1914)]
        assert at_1914 == pytest.approx(0.0724, abs=5e-5)
        assert (1945 - 1914) / 130.0 == pytest.approx(0.2385, abs=5e-4)
        assert any("1914" in note and "1945" in note for note in cycle.notes)

    def test_today_mirrors_1929(self):
        """An arithmetical consequence of the anchoring rather than a claim about the world, and worth an
        assertion because it is the kind of thing a reader will check: 2026 is as far past the 2010 trough as
        1929 was short of the 1945 peak, so the two carry the same magnitude with opposite signs."""
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(years, peak_year=1945, period_years=130.0)
        component = cycle.estimate.component
        at_1929 = component[list(years).index(1929)]
        at_2026 = component[list(years).index(2026)]
        assert at_2026 == pytest.approx(-at_1929, abs=1e-9)
        assert at_2026 < 0.0

    def test_the_amplitude_is_not_invented(self):
        years = np.arange(1900, 2061)
        cycle = fixed_hegemonic_cycle(years, peak_year=1945, period_years=130.0)
        assert np.allclose(cycle.estimate.amplitude, 1.0)
        assert any("amplitude is normalised to one" in note for note in cycle.notes)

    def test_a_non_positive_period_is_refused(self):
        with pytest.raises(CycleError, match="hegemonic period must be positive"):
            fixed_hegemonic_cycle(np.arange(1900, 2000), peak_year=1945, period_years=0.0)

    def test_it_is_built_from_config_but_kept_out_of_interference(self):
        """Built and excluded are different things, and the config says so separately.

        A cycle absent from the interference measure must still be *available*, or its phase becomes
        unreportable as a side effect of a decision about fragility.
        """
        config = config_module.load()
        anchored = anchored_from_config(config, np.arange(1900, 2061))
        assert "hegemonic" in anchored
        assert anchored["hegemonic"].anchored
        assert anchored["hegemonic"].period_years == pytest.approx(130.0)
        assert anchored["hegemonic"].reference_year == pytest.approx(1945.0)

        members = interference_members(config, anchored)
        assert "hegemonic" not in members, "the fragility window must not have gained a contributor"
        assert "innovation" in members

    def test_the_configured_anchor_is_the_succession_the_author_supplied(self):
        settings = config_module.load().get("cycles.anchored")["hegemonic"]
        assert settings["succession_from"] == 1914
        assert settings["succession_to"] == 1945
        assert settings["peak_year"] == 1945
        assert settings["in_interference"] is False
        # the period stays the source frequency analysis's, not a new number
        assert settings["period_years"] == pytest.approx(
            config_module.load().get("cycles.priors")["hegemonic_years"]
        )


class TestFixedInnovationCycle:
    """The innovation cycle is supplied, identically for every economy, with a low in 2032."""

    def test_the_trough_is_where_the_component_bottoms_out(self):
        years = np.arange(2000, 2061)
        cycle = fixed_innovation_cycle(years, trough_year=2032, period_years=47.0)
        component = cycle.estimate.component
        assert years[int(np.argmin(component))] == 2032
        assert component[int(np.argmin(component))] == pytest.approx(-1.0)

    def test_the_phase_convention_matches_the_band_pass_one(self):
        """extract_cycle takes phase 0 at the component's peak, so a trough must sit at plus or minus pi.

        If these disagreed, an anchored cycle and an estimated one would be compared on different phase
        conventions and every synchrony verdict involving a long cycle would be wrong.
        """
        years = np.arange(2000, 2061)
        cycle = fixed_innovation_cycle(years, trough_year=2032, period_years=47.0)
        at_trough = float(cycle.estimate.phase[int(np.flatnonzero(years == 2032)[0])])
        assert abs(abs(at_trough) - np.pi) < 1e-9

        reference = extract_cycle(sine(120, 20.0), CycleBand.from_prior("test", 20.0))
        peak = int(np.argmax(reference.component))
        assert abs(float(reference.phase[peak])) < 0.2

    def test_the_period_is_the_supplied_one_not_an_estimate(self):
        cycle = fixed_innovation_cycle(np.arange(2000, 2061), trough_year=2032, period_years=47.0)
        assert cycle.estimate.estimated_period == pytest.approx(47.0)
        assert cycle.period_years == pytest.approx(47.0)

    def test_the_amplitude_is_normalised_and_says_so(self):
        """The anchor gives a position, not a size, and claiming a size would invent one."""
        cycle = fixed_innovation_cycle(np.arange(2000, 2061), trough_year=2032, period_years=47.0)
        assert np.allclose(cycle.estimate.amplitude, 1.0)
        assert any("normalised to one" in note for note in cycle.notes)

    def test_it_is_identical_across_economies(self):
        """A global technological cycle takes the same phase everywhere, which is the whole reason it is
        supplied rather than estimated per country."""
        years = np.arange(1990, 2041)
        first = fixed_innovation_cycle(years, trough_year=2032, period_years=47.0)
        second = fixed_innovation_cycle(years, trough_year=2032, period_years=47.0)
        assert np.allclose(first.estimate.phase, second.estimate.phase)

    def test_it_is_usable_by_the_synchrony_analysis(self):
        """The point of anchoring is to stop the long cycles dropping out of synchrony."""
        cycle = fixed_innovation_cycle(np.arange(1990, 2041), trough_year=2032, period_years=47.0)
        assert cycle.estimate.identifiable
        assert cycle.estimate.phase is not None

    def test_rejects_a_non_positive_period(self):
        with pytest.raises(CycleError, match="must be positive"):
            fixed_innovation_cycle(np.arange(2000, 2010), trough_year=2032, period_years=0.0)


class TestAnchorCapitalCycle:
    """Reaching 3.5 credit to GDP means 90 years into the capital cycle."""

    @staticmethod
    def rising(start: int, years: int, first: float, last: float):
        periods = np.arange(start, start + years)
        return periods, np.linspace(first, last, years)

    def test_the_anchor_is_the_crossing_year(self):
        periods, saturation = self.rising(1970, 51, 1.5, 4.0)
        cycle = anchor_capital_cycle(periods, saturation)
        assert cycle.anchored
        index = int(np.flatnonzero(saturation >= 3.5)[0])
        # The crossing is interpolated, so it lands between the last year below and the first at or above.
        assert periods[index - 1] <= cycle.reference_year <= periods[index]

    def test_the_crossing_is_interpolated_within_the_year(self):
        """Snapping to an annual observation would quantise the cycle position for no reason."""
        periods = np.array([2000, 2001])
        # 3.5 sits one quarter of the way from 3.4 to 3.8.
        cycle = anchor_capital_cycle(periods, np.array([3.4, 3.8]))
        assert cycle.reference_year == pytest.approx(2000.25)

    def test_the_anchor_year_is_ninety_years_into_the_cycle(self):
        periods = np.array([2000, 2001])
        cycle = anchor_capital_cycle(periods, np.array([3.4, 3.8]))
        at_anchor = np.interp(cycle.reference_year, periods, cycle.years_into_cycle)
        assert at_anchor == pytest.approx(90.0)

    def test_an_economy_past_the_anchor_reads_as_overdue(self):
        """The reading the anchoring exists to produce: how far past the reordering point an economy is."""
        periods, saturation = self.rising(1970, 55, 1.5, 4.2)
        cycle = anchor_capital_cycle(periods, saturation)
        assert float(cycle.years_into_cycle[-1]) > 90.0

    def test_phase_zero_sits_at_the_crossing(self):
        """Saturation peaks at the crossing and the reordering follows, so that is the cycle's peak."""
        periods = np.array([2000, 2001])
        cycle = anchor_capital_cycle(periods, np.array([3.4, 3.8]))
        phase_at_anchor = np.interp(cycle.reference_year, periods, cycle.estimate.phase)
        assert abs(phase_at_anchor) < 1e-9

    def test_refuses_to_anchor_an_economy_that_never_reaches_the_ratio(self):
        """Germany and India sit below 3.5, and placing a 90-year cycle without the anchor is a guess."""
        periods, saturation = self.rising(1970, 51, 1.2, 2.8)
        cycle = anchor_capital_cycle(periods, saturation)
        assert not cycle.anchored
        assert cycle.reference_year is None
        assert cycle.years_into_cycle is None
        assert not cycle.estimate.identifiable
        assert any("never reaches the anchor" in note for note in cycle.notes)
        assert any("2.80" in note for note in cycle.notes), "the peak reached must be reported"

    def test_the_last_crossing_wins_and_the_others_are_reported(self):
        """A position is a statement about the current cycle, not an average over past ones."""
        periods = np.arange(2000, 2010)
        saturation = np.array([3.0, 3.6, 3.2, 3.1, 3.0, 3.4, 3.9, 4.0, 4.1, 4.2])
        cycle = anchor_capital_cycle(periods, saturation)
        assert cycle.anchored
        assert cycle.reference_year > 2004
        assert any("2 times" in note for note in cycle.notes)

    def test_a_downward_crossing_is_not_an_anchor(self):
        """The anchor marks reaching saturation, so only upward crossings count."""
        periods = np.arange(2000, 2005)
        cycle = anchor_capital_cycle(periods, np.array([4.0, 3.8, 3.4, 3.0, 2.8]))
        assert not cycle.anchored

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(CycleError, match="share a shape"):
            anchor_capital_cycle(np.arange(5), np.ones(4))


class TestAnchoredFromConfig:
    def test_builds_all_three_long_cycles_from_the_default_config(self):
        """Three since 2026-08-02, when the hegemonic succession was anchored on the UK-to-US transition.

        This test asserted two until then. It is the count that matters rather than the names: a cycle silently
        dropping out of the anchored set is how a phase becomes unreportable without anyone noticing.
        """
        periods = np.arange(1970, 2025)
        saturation = np.linspace(1.5, 4.0, periods.size)
        anchored = anchored_from_config(config_module.load(), periods, saturation)
        assert set(anchored) == {"innovation", "capital", "hegemonic"}
        assert anchored["innovation"].reference_year == pytest.approx(2032.0)
        assert anchored["hegemonic"].reference_year == pytest.approx(1945.0)
        assert anchored["capital"].anchored

    def test_omits_only_the_capital_cycle_when_no_saturation_axis_is_supplied(self):
        """The anchor is the whole content of the capital cycle, so a default would be an invention.

        The other two need no data at all — they are supplied structure applied identically to every economy —
        so they must still be built here.
        """
        anchored = anchored_from_config(config_module.load(), np.arange(1970, 2025))
        assert set(anchored) == {"innovation", "hegemonic"}

    def test_only_the_hegemonic_cycle_is_excluded_from_interference(self):
        """The fragility window's membership is a separate decision from what is anchored, and exactly one
        cycle currently differs between the two. If a second ever does, that is a finding."""
        periods = np.arange(1970, 2025)
        saturation = np.linspace(1.5, 4.0, periods.size)
        config = config_module.load()
        anchored = anchored_from_config(config, periods, saturation)
        members = set(interference_members(config, anchored))
        assert set(anchored) - members == {"hegemonic"}


class TestIdentifiability:
    def test_recovers_a_known_period(self):
        series = sine(400, 18.0)
        estimate = extract_cycle(series, CycleBand.from_prior("credit", 18.0))
        assert estimate.identifiable
        assert estimate.estimated_period == pytest.approx(18.0, rel=0.15)

    def test_a_short_sample_cannot_identify_a_long_cycle(self):
        """The capital cycle needs roughly two centuries of annual data. No national accounts series
        provides that, so it must be reported unidentifiable rather than filtered anyway."""
        series = sine(60, 90.0)
        estimate = extract_cycle(series, CycleBand.from_prior("capital", 90.0))
        assert not estimate.identifiable
        assert estimate.component is None
        assert estimate.estimated_period is None
        assert any("at least" in note for note in estimate.notes)

    def test_the_identifiability_threshold_is_two_periods(self):
        band = CycleBand.from_prior("business", 7.0)
        just_short = extract_cycle(sine(13, 7.0), band)
        just_long = extract_cycle(sine(15, 7.0), band)
        assert not just_short.identifiable
        assert just_long.identifiable
        assert MINIMUM_PERIODS_IN_SAMPLE == 2.0

    def test_rejects_non_finite_values(self):
        """Gaps belong to the data layer, where they are flagged, not silently filled here."""
        series = sine(100, 18.0)
        series[10] = np.nan
        with pytest.raises(CycleError, match="non-finite"):
            extract_cycle(series, CycleBand.from_prior("credit", 18.0))

    def test_rejects_a_two_dimensional_input(self):
        with pytest.raises(CycleError, match="one-dimensional"):
            extract_cycle(np.zeros((10, 2)), CycleBand.from_prior("credit", 18.0))

    def test_rejects_an_unknown_method(self):
        with pytest.raises(CycleError, match="unknown extraction method"):
            extract_cycle(sine(100, 18.0), CycleBand.from_prior("credit", 18.0), method="magic")

    def test_hodrick_prescott_records_that_it_is_not_band_limited(self):
        estimate = extract_cycle(
            sine(100, 18.0), CycleBand.from_prior("credit", 18.0), method="hodrick_prescott"
        )
        assert estimate.identifiable
        assert any("not restricted to this cycle's band" in note for note in estimate.notes)


class TestDecompose:
    def test_separates_two_superposed_cycles(self):
        series = sine(400, 7.0) + sine(400, 18.0)
        bands = [CycleBand.from_prior("business", 7.0), CycleBand.from_prior("credit", 18.0)]
        estimates = decompose(series, bands)
        assert estimates["business"].estimated_period == pytest.approx(7.0, rel=0.2)
        assert estimates["credit"].estimated_period == pytest.approx(18.0, rel=0.2)

    def test_the_short_cycles_are_identifiable_on_a_realistic_sample(self):
        """A 60-year annual sample supports the pulse, business and credit cycles and nothing longer.

        The three long cycles are not in the band-pass set at all, which is the point: on this sample they
        would each be reported as unidentifiable, and that verdict is what the anchoring replaces.

        Identifiability is asserted only for business and credit. The fundamental pulse clears the
        two-periods-in-sample floor comfortably on 60 years, so it will report identifiable — but that floor
        is about sample *length* and says nothing about sampling *rate*, which is the pulse's actual problem.
        `test_cycle_bins.py` covers that: at 3.6 intervals per period it is classified marginal regardless of
        how identifiable this function calls it.
        """
        series = sine(60, 3.6) + sine(60, 7.0) + sine(60, 18.0)
        estimates = decompose(series, bands_from_config(config_module.load()))
        assert set(estimates) == {"fundamental_pulse", "business", "credit"}
        assert estimates["business"].identifiable
        assert estimates["credit"].identifiable

    def test_band_passing_a_long_cycle_would_still_refuse(self):
        """The identifiability guard is not weakened by the long cycles leaving the band-pass set.

        Anchoring them is a decision about where they are positioned, not a licence to band-pass them from
        a sample that cannot support it.
        """
        from macrofield.model.cycles import CycleBand

        series = sine(60, 7.0)
        estimates = decompose(series, [CycleBand.from_prior("capital", 90.0)])
        assert not estimates["capital"].identifiable
        assert "at least 180.0 years" in " ".join(estimates["capital"].notes)


class TestSpectrum:
    def test_peak_sits_at_the_injected_period(self):
        periods, power = spectrum(sine(400, 18.0))
        assert periods[int(np.argmax(power))] == pytest.approx(18.0, rel=0.2)

    def test_periods_are_returned_in_increasing_order(self):
        periods, _ = spectrum(sine(200, 18.0))
        assert np.all(np.diff(periods) > 0.0)

    def test_rejects_too_short_a_sample(self):
        with pytest.raises(CycleError, match="at least 8 observations"):
            spectrum(np.zeros(4))


class TestSynchrony:
    def _estimates(self, phases: dict[str, float], years: int = 400):
        """Decompose a series per cycle, each injected at a chosen phase."""
        specs = {"business": 7.0, "credit": 18.0, "innovation": 47.0}
        estimates = {}
        for name, period in specs.items():
            series = sine(years, period, phase=phases[name])
            band = (
                CycleBand.from_explicit("innovation", 40.0, 54.0)
                if name == "innovation"
                else CycleBand.from_prior(name, period)
            )
            estimates[name] = extract_cycle(series, band)
        return estimates

    def test_detects_a_window_when_cycles_are_in_phase(self):
        years = 400
        estimates = self._estimates({"business": 0.0, "credit": 0.0, "innovation": 0.0}, years)
        result = detect_synchrony(np.arange(years), estimates, minimum_cycles_in_phase=3)
        assert result.windows
        assert all(len(w.cycles_in_phase) >= 3 for w in result.windows)

    def test_pairwise_differences_are_reported_for_every_pair(self):
        estimates = self._estimates({"business": 0.0, "credit": 1.0, "innovation": 2.0})
        result = detect_synchrony(np.arange(400), estimates, minimum_cycles_in_phase=2)
        assert len(result.pairwise_phase_difference) == 3  # three cycles, three pairs

    def test_windows_carry_period_labels_not_only_indices(self):
        years = 400
        estimates = self._estimates({"business": 0.0, "credit": 0.0, "innovation": 0.0}, years)
        periods = np.arange(1600, 1600 + years)
        result = detect_synchrony(periods, estimates, minimum_cycles_in_phase=3)
        assert result.windows
        window = result.windows[0]
        assert window.start_period >= 1600
        assert window.end_period <= 1600 + years - 1
        assert window.start_period <= window.end_period

    def test_excludes_unidentifiable_cycles_and_says_so(self):
        years = 60
        estimates = self._estimates(
            {"business": 0.0, "credit": 0.0, "innovation": 0.0}, years
        )
        result = detect_synchrony(np.arange(years), estimates, minimum_cycles_in_phase=2)
        assert "innovation" in result.excluded_cycles
        assert any("too short to identify" in note for note in result.notes)

    def test_a_single_identifiable_cycle_cannot_yield_a_verdict(self):
        """Reporting no window here would read as 'the cycles are out of phase', which it is not."""
        estimates = {"credit": extract_cycle(sine(60, 18.0), CycleBand.from_prior("credit", 18.0))}
        result = detect_synchrony(np.arange(60), estimates)
        assert result.windows == []
        assert result.current_window is None
        assert any("cannot be assessed" in note for note in result.notes)

    def test_rejects_a_phase_length_mismatch(self):
        estimates = self._estimates({"business": 0.0, "credit": 0.0, "innovation": 0.0})
        with pytest.raises(CycleError, match="phase values"):
            detect_synchrony(np.arange(10), estimates)

    def test_the_only_dates_in_the_cycle_config_are_declared_anchors(self):
        """Brief section 0.14, as it now stands after the author's instruction of 2026-07-27.

        The rule that mattered was never "no digits that look like a year". It was that the programme must
        not encode a dated conclusion *of its own* and pass it off as computed. An anchor the author
        supplies is an input, with the same standing as `stock_gold.calibration_anchor_year`.

        So the test is no longer that the cycles config is free of dates. It is that every date in it sits
        under `anchored`, carries a source, and is therefore visible as a supplied input rather than a
        recomputed finding. A date appearing anywhere else in the section would be the thing 0.14 forbids.
        """
        section = config_module.load().section("cycles").as_dict()
        anchored = section.pop("anchored")

        rest = str(section)
        for forbidden in ("2029", "2030", "2031", "2032", "2033", "2034"):
            assert forbidden not in rest, (
                f"{forbidden} appears in the cycles config outside `anchored`, which is where a supplied "
                f"anchor must live so that it cannot be mistaken for a computed window"
            )

        # Every anchor declares where it came from, so no date is anonymous.
        assert anchored["innovation"]["trough_year"] == 2032
        for name, entry in anchored.items():
            assert entry.get("source"), f"the {name} anchor carries no source"

    def test_the_synchronisation_window_is_still_computed(self):
        """The anchors supply two phases. They do not supply the window, which remains a computation.

        This is the distinction the previous test was protecting, so it is worth asserting directly: move
        the anchored phases and the detected window moves with them.
        """
        from macrofield.model.cycles import fixed_innovation_cycle

        years = np.arange(1980, 2040)
        near = fixed_innovation_cycle(years, trough_year=2032, period_years=47.0)
        far = fixed_innovation_cycle(years, trough_year=2000, period_years=47.0)

        estimates = {"credit": extract_cycle(sine(years.size, 18.0), CycleBand.from_prior("credit", 18.0))}
        with_near = detect_synchrony(
            years, dict(estimates, innovation=near.estimate), minimum_cycles_in_phase=2
        )
        with_far = detect_synchrony(
            years, dict(estimates, innovation=far.estimate), minimum_cycles_in_phase=2
        )
        assert [(w.start_period, w.end_period) for w in with_near.windows] != [
            (w.start_period, w.end_period) for w in with_far.windows
        ]

    def test_tolerance_widens_the_detected_windows(self):
        years = 400
        estimates = self._estimates({"business": 0.0, "credit": 0.4, "innovation": 0.8}, years)
        tight = detect_synchrony(
            np.arange(years), estimates, phase_tolerance_radians=0.05, minimum_cycles_in_phase=3
        )
        loose = detect_synchrony(
            np.arange(years), estimates, phase_tolerance_radians=1.5, minimum_cycles_in_phase=3
        )
        tight_span = sum(w.end_index - w.start_index + 1 for w in tight.windows)
        loose_span = sum(w.end_index - w.start_index + 1 for w in loose.windows)
        assert loose_span >= tight_span
