"""Unit and property tests of the model (engine page section 5).

The two properties the engine page names are tested on real and on generated inputs:

* each cycle is in **exactly one phase per year** (or has no position, visibly);
* phases **follow the declared order**: every year-on-year step moves forward through
  ``PHASES`` (a cycle faster than four years may skip one), and a step that does not is
  reported in ``order_breaks``, never hidden.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings as hsettings, strategies as st
from pydantic import ValidationError

from cycle.calibration import CAPITAL_AGGRESSIVE, CAPITAL_INVERTED, CREDIT_LOWS, DEFAULT, HISTORICAL_RESETS, RESETS
from cycle.contracts import PHASES, STATE_COUNT, Calibration, CycleSpec, phase_of
from cycle.engine import (
    anchor_capital_cycle,
    anchor_capital_cycle_by_projection,
    bin_centre,
    cf_filter,
    cycle_distribution,
    fixed_cycle,
    output_growth,
    run_economy,
    run_model,
    trailing_span,
)

ECONOMIES = ["BR", "CH", "CN", "EU", "IN", "ID", "MY", "PH", "TH", "GB", "US", "JP", "BD", "VN", "DE", "ES"]


@pytest.fixture(scope="module")
def built(panel):
    return run_model(panel, DEFAULT, ECONOMIES, {c: c for c in ECONOMIES})


def _forward_steps(prev: str, now: str) -> int:
    return (PHASES.index(now) - PHASES.index(prev)) % 4


def assert_order(years, track):
    breaks = set(track.order_breaks)
    for i in range(1, len(years)):
        a, b = track.phase[i - 1], track.phase[i]
        if a is None or b is None or years[i] in breaks:
            continue
        assert _forward_steps(a, b) in (0, 1, 2), (track.cycle, years[i], a, b)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

class TestPhases:
    @given(st.floats(-50, 50, allow_nan=False))
    def test_every_angle_is_in_exactly_one_phase(self, angle):
        assert phase_of(angle) in PHASES
        assert phase_of(angle) == phase_of(angle + 2 * math.pi)

    def test_the_quadrants(self):
        assert [phase_of(a) for a in (-math.pi, -1.0, 0.0, 2.0, math.pi)] == [
            "recovery", "expansion", "slowdown", "contraction", "recovery"]

    def test_real_data_every_cycle_has_one_phase_or_none_per_year(self, built):
        for e in built.economies:
            for t in e.cycles:
                assert len(t.phase) == len(built.years)
                assert all(p is None or p in PHASES for p in t.phase)
                if not t.identifiable:
                    assert set(t.phase) == {None}

    def test_real_data_phases_follow_the_declared_order(self, built):
        for e in built.economies:
            for t in e.cycles:
                assert_order(built.years, t)
                if t.anchored:
                    assert t.order_breaks == ()

    @hsettings(max_examples=40, deadline=None)
    @given(st.integers(0, 10_000), st.integers(16, 60))
    def test_generated_inputs_follow_the_order(self, seed, n):
        rng = np.random.default_rng(seed)
        years = list(range(2000, 2000 + n))
        nominal = np.exp(np.cumsum(0.03 + 0.02 * rng.standard_normal(n)))
        saturation = 2.0 + np.cumsum(0.1 * rng.standard_normal(n))
        inputs = {"output_growth": output_growth(nominal, np.zeros(n), True),
                  "saturation_change": (np.full(n, np.nan), None)}
        result = run_economy(years, inputs, saturation, DEFAULT)
        from cycle.engine import economy_contract
        e = economy_contract("XX", "X", years, result)     # validates every track
        for t in e.cycles:
            assert_order(years, t)
        for row in e.layer:
            assert row is not None and abs(sum(row) - 1) < 1e-12 and min(row) >= 0

    def test_a_clean_sinusoid_never_steps_backwards(self):
        years = list(range(1960, 2020))
        t = np.arange(60.0)
        g = 0.02 + 0.01 * np.sin(2 * np.pi * t / 7.0)
        result = run_economy(years, {"output_growth": (g, (0, 59)), "saturation_change": (g, (0, 59))},
                             np.full(60, np.nan), DEFAULT)
        business = next(x for x in result.tracks if x.spec.name == "business")
        assert business.identifiable
        from cycle.engine import order_breaks
        assert order_breaks(years, business.phase) == ()


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

class TestInputs:
    def test_output_growth_is_the_drafts_gradient_of_log_real_output(self):
        rng = np.random.default_rng(3)
        nominal = np.exp(np.cumsum(rng.normal(0.05, 0.02, 20)))
        cpi = rng.normal(0.02, 0.01, 20)
        real = nominal / np.cumprod(np.r_[1.0, 1.0 + cpi[1:]])
        got, span = output_growth(nominal, cpi, True)
        assert span == (0, 19)
        np.testing.assert_allclose(got, np.gradient(np.log(real)), atol=1e-13)

    def test_a_gap_shortens_the_sample_and_is_never_filled(self):
        nominal = np.exp(np.arange(20) * 0.03)
        cpi = np.zeros(20)
        cpi[6] = np.nan
        got, span = output_growth(nominal, cpi, True)
        assert span == (6, 19)
        assert np.isnan(got[:6]).all() and np.isfinite(got[6:]).all()

    def test_trailing_span(self):
        assert trailing_span(np.array([1, np.nan, 2, 3, np.nan])) == (2, 3)
        assert trailing_span(np.array([np.nan, np.nan])) is None


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

class TestCycles:
    def test_cf_filter_matches_statsmodels(self):
        sm = pytest.importorskip("statsmodels.tsa.filters.cf_filter")
        rng = np.random.default_rng(7)
        for n in (8, 20, 61):
            x = rng.normal(size=n).cumsum()
            np.testing.assert_allclose(cf_filter(x, 4.2, 9.8), sm.cffilter(x, 4.2, 9.8, drift=False)[0],
                                       atol=1e-12)

    def test_a_short_sample_leaves_the_credit_cycle_unidentified(self, built):
        for e in built.economies:
            credit = next(t for t in e.cycles if t.cycle == "credit")
            assert not credit.identifiable and credit.confidence is None
            assert "needed to identify it" in credit.notes[0]

    def test_innovation_is_global_and_low_in_2032(self):
        years = np.arange(2000.0, 2041.0)
        c = fixed_cycle("innovation", years, 2032.0, 47.0, at="trough", band_fraction=0.4)
        i = list(years).index(2032.0)
        assert c.estimate.component[i] == pytest.approx(-1.0)
        assert phase_of(float(c.estimate.phase[i])) == "recovery"
        assert c.years_into_cycle[i] == 0.0

    def test_capital_anchors_on_the_last_upward_crossing(self):
        years = np.arange(2000.0, 2010.0)
        sat = np.array([3.0, 3.6, 3.2, 3.3, 3.4, 3.45, 3.6, 3.7, 3.8, 3.9])
        c = anchor_capital_cycle("capital", years, sat, 3.5, 90.0, 90.0, 0.4)
        assert c.anchored and c.reference_year == pytest.approx(2005 + 0.05 / 0.15)
        assert c.years_into_cycle[-1] == pytest.approx(2009 - c.reference_year + 90.0)

    def test_capital_is_not_anchored_without_a_crossing(self):
        years = np.arange(2000.0, 2010.0)
        c = anchor_capital_cycle("capital", years, np.full(10, 4.0), 3.5, 90.0, 90.0, 0.4)
        assert not c.anchored and "never reaches" in c.notes[0]

    def test_a_projected_anchor_is_marked_assumed_and_a_falling_trend_is_refused(self):
        years = np.arange(2000.0, 2010.0)
        rising = anchor_capital_cycle_by_projection("capital", years, np.linspace(2.0, 3.0, 10), 3.5,
                                                    90.0, 90.0, 10, 120.0, 0.4)
        assert rising.anchored and rising.assumed
        falling = anchor_capital_cycle_by_projection("capital", years, np.linspace(3.0, 2.0, 10), 3.5,
                                                     90.0, 90.0, 10, 120.0, 0.4)
        assert not falling.anchored

    def test_capital_is_oriented_to_the_cautious_end(self, built):
        us = next(e for e in built.economies if e.code == "US")
        capital = next(t for t in us.cycles if t.cycle == "capital")
        i = next(i for i, v in enumerate(capital.level) if v is not None)
        assert capital.bin_centre[i] == pytest.approx(bin_centre(-capital.level[i]))


# ---------------------------------------------------------------------------
# The 25-bin layer
# ---------------------------------------------------------------------------

class TestLayer:
    @given(st.floats(1, 25), st.floats(0.5, 8), st.floats(-0.95, 0.95))
    def test_every_kernel_is_a_distribution_with_its_mode_at_the_centre(self, centre, width, skew):
        d = cycle_distribution(centre, width, skew)
        assert d.size == STATE_COUNT and abs(d.sum() - 1) < 1e-12 and (d >= 0).all()
        assert abs(int(np.argmax(d)) + 1 - centre) <= 1.0

    def test_trough_mid_and_peak(self):
        assert [bin_centre(x) for x in (-1, 0, 1)] == [1.0, 13.0, 25.0]

    def test_every_year_is_placed_on_the_production_snapshot(self, built):
        assert built.coverage.layer_cells_unplaced == 0
        for e in built.economies:
            for row in e.layer:
                assert abs(sum(row) - 1) < 1e-12


# ---------------------------------------------------------------------------
# Calibration and determinism
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_the_seed_is_the_five_nested_cycles(self):
        assert [c.name for c in DEFAULT.cycles] == [
            "fundamental_pulse", "business", "credit", "innovation", "capital"]

    @pytest.mark.parametrize("bad", [
        dict(name="x", kind="estimated", period_years=7.0),
        dict(name="x", kind="anchored_trough", period_years=7.0),
        dict(name="x", kind="anchored_peak", period_years=7.0, anchor_year=1945.0, input="output_growth"),
        dict(name="x", kind="anchored_saturation", period_years=90.0, anchor_saturation=3.5),
        dict(name="x", kind="estimated", period_years=3.0, input="output_growth", band=(1.5, 4.0)),
        dict(name="X Y", kind="estimated", period_years=7.0, input="output_growth"),
    ])
    def test_a_cycle_must_fit_its_kind(self, bad):
        with pytest.raises(ValidationError):
            CycleSpec(**bad)

    def test_names_are_unique(self):
        with pytest.raises(ValidationError):
            Calibration(version="9.0.0", cycles=(DEFAULT.cycles[0], DEFAULT.cycles[0]))

    def test_a_hegemonic_cycle_can_be_added_outside_interference(self, panel):
        heg = CycleSpec(name="hegemonic", kind="anchored_peak", anchor_year=1945.0, period_years=130.0,
                        in_interference=False)
        cal = Calibration.model_validate({**DEFAULT.model_dump(), "version": "9.0.0",
                                          "cycles": [*DEFAULT.model_dump()["cycles"], heg.model_dump()]})
        out = run_model(panel, cal, ["US"], {"US": "US"})
        us = out.economies[0]
        assert "hegemonic" not in us.interference_members
        h = next(t for t in us.cycles if t.cycle == "hegemonic")
        assert h.bin_centre[-1] is not None

    def test_same_inputs_same_output(self, panel, built):
        again = run_model(panel, DEFAULT, ECONOMIES, {c: c for c in ECONOMIES})
        assert again == built


class TestHistoricalResets:
    def test_every_economy_is_anchored_on_its_reset(self, panel, macro):
        out = run_model(panel, HISTORICAL_RESETS, ECONOMIES, {c: c for c in ECONOMIES}, macro)
        assert set(RESETS) == set(ECONOMIES)
        for e in out.economies:
            capital = next(t for t in e.cycles if t.cycle == "capital")
            assert capital.anchored and not capital.assumed and capital.confidence == "supplied"
            assert capital.reference_year == RESETS[e.code] + 90.0
            assert capital.years_into_cycle[-1] == 2025 - RESETS[e.code]
            assert capital.order_breaks == ()
        assert not any(u.cycle == "capital" for u in out.coverage.unidentified)
        # The resets replace the saturation anchor, so a missing saturation is no longer a gap.
        assert not any(g.input == "saturation" for g in out.coverage.input_gaps)

    def test_china_peaks_in_2038(self, panel, macro):
        cn = run_model(panel, HISTORICAL_RESETS, ["CN"], {"CN": "CN"}, macro).economies[0]
        capital = next(t for t in cn.cycles if t.cycle == "capital")
        assert capital.reference_year == 2038.0 and capital.years_into_cycle[-1] == 77.0
        assert capital.phase[-1] == "expansion"          # rising toward its peak

    def test_rise_fall_is_low_at_the_reset_peaks_at_90_and_resets_at_130(self):
        from cycle.engine import rise_fall_phase
        years = np.arange(1948.0, 2210.0)
        phase, into = rise_fall_phase(years, 1948.0, 90.0, 130.0)
        at = lambda y: float(phase[list(years).index(y)])  # noqa: E731
        assert at(1948.0) == pytest.approx(-math.pi) and at(2038.0) == pytest.approx(0.0)
        assert at(2078.0) == pytest.approx(-math.pi) and into[list(years).index(2078.0)] == 0.0
        assert [phase_of(at(y)) for y in (1950.0, 2000.0, 2040.0, 2070.0)] == [
            "recovery", "expansion", "slowdown", "contraction"]
        from cycle.engine import order_breaks
        assert order_breaks([int(y) for y in years], phase) == ()

    def test_the_capital_cycle_is_130_years_under_1_1_0(self):
        capital = HISTORICAL_RESETS.spec("capital")
        assert (capital.shape, capital.period_years, capital.years_into_cycle_at_anchor) == ("rise_fall", 130.0, 90.0)
        assert DEFAULT.spec("capital").shape == "cosine"

    def test_resets_belong_to_the_saturation_anchor_only(self):
        with pytest.raises(ValidationError):
            CycleSpec(name="x", kind="anchored_trough", anchor_year=2032.0, period_years=47.0,
                      resets={"CN": 1948.0})

    def test_credit_is_anchored_on_each_economys_crisis(self, panel, macro):
        out = run_model(panel, HISTORICAL_RESETS, ECONOMIES, {c: c for c in ECONOMIES}, macro)
        assert set(CREDIT_LOWS) == set(ECONOMIES)
        years = list(out.years)
        for e in out.economies:
            credit = next(t for t in e.cycles if t.cycle == "credit")
            assert credit.kind == "anchored_trough" and credit.confidence == "supplied"
            assert credit.reference_year == CREDIT_LOWS[e.code] and "credit" in e.interference_members
            low = CREDIT_LOWS[e.code]
            if low in years:
                assert credit.level[years.index(low)] == pytest.approx(-1.0)
                assert credit.phase[years.index(low)] == "recovery"
            assert credit.order_breaks == ()
        assert out.coverage.unidentified == ()

    def test_an_economy_without_an_anchor_year_has_no_position(self, panel):
        spec = CycleSpec(name="credit", kind="anchored_trough", period_years=18.0, anchor_years={"US": 2009.0})
        cal = Calibration.model_validate({**DEFAULT.model_dump(), "version": "9.0.0", "cycles": [
            spec.model_dump() if c.name == "credit" else c.model_dump() for c in DEFAULT.cycles]})
        out = run_model(panel, cal, ["US", "CH"], {"US": "US", "CH": "CH"})
        us, ch = ({t.cycle: t for t in e.cycles}["credit"] for e in out.economies)
        assert us.identifiable and not ch.identifiable
        assert "no anchor year" in ch.notes[0]

    def test_1_0_0_is_unchanged(self, built):
        assert sum(1 for e in built.economies for t in e.cycles if t.cycle == "capital" and t.anchored) == 5



class TestMacrofieldOutput:
    def test_the_active_calibration_needs_macrofield(self, panel):
        from cycle.engine import EngineError
        with pytest.raises(EngineError, match="reads macrofield"):
            run_model(panel, HISTORICAL_RESETS, ["US"], {"US": "US"})

    def test_the_axis_reaches_back_to_macrofields_first_year(self, panel, macro):
        out = run_model(panel, HISTORICAL_RESETS, ["US", "CH"], {"US": "US", "CH": "CH"}, macro)
        assert out.years[0] == 1972 and out.years[-1] == 2025
        us = {t.cycle: t for t in out.economies[0].cycles}
        assert us["business"].sample_years == 53.0 and us["business"].confidence == "measured"

    def test_growth_is_the_drafts_gradient_of_log_current_usd_output(self, macro):
        from cycle.engine import macrofield_output_growth
        years, y = macro["US"]
        got, span = macrofield_output_growth(np.array(y, dtype=float))
        assert span == (0, len(y) - 1)
        np.testing.assert_allclose(got, np.gradient(np.log(np.array(y, dtype=float))), atol=0)

    def test_a_short_trailing_run_falls_back_to_the_longest(self, panel, macro):
        out = run_model(panel, HISTORICAL_RESETS, ["IN"], {"IN": "IN"}, macro)
        years = list(out.years)
        business = {t.cycle: t for t in out.economies[0].cycles}["business"]
        assert business.identifiable and "longest gap-free span" in " ".join(business.notes)
        assert business.phase[years.index(2018)] is not None and business.phase[years.index(2022)] is None

    def test_longest_span(self):
        from cycle.engine import longest_span
        assert longest_span(np.array([1, 2, np.nan, 1, 2, 3, np.nan, 5])) == (3, 5)
        assert longest_span(np.array([1, np.nan, 2])) == (2, 2)
        assert longest_span(np.array([np.nan])) is None

    def test_1_0_0_reads_no_macrofield(self, panel):
        out = run_model(panel, DEFAULT, ["US"], {"US": "US"})
        assert out.years == tuple(range(2006, 2026))



class TestCapitalRiskReading:
    def test_1_2_0_reads_the_capital_peak_as_aggressive(self, panel, macro):
        cal = CAPITAL_AGGRESSIVE
        assert cal.spec("capital").orientation == 1 and HISTORICAL_RESETS.spec("capital").orientation == -1
        before = run_model(panel, HISTORICAL_RESETS, ["US", "VN"], {"US": "US", "VN": "VN"}, macro)
        after = run_model(panel, cal, ["US", "VN"], {"US": "US", "VN": "VN"}, macro)
        for b, a in zip(before.economies, after.economies):
            cb = {t.cycle: t for t in b.cycles}["capital"]
            ca = {t.cycle: t for t in a.cycles}["capital"]
            assert ca.phase == cb.phase and ca.level == cb.level          # the cycle itself is unchanged
            assert ca.bin_centre[-1] == pytest.approx(26.0 - cb.bin_centre[-1])   # mirrored on the axis
        us = {t.cycle: t for t in after.economies[0].cycles}["capital"]
        assert us.bin_centre[-1] > 24                                     # 92 years in: near the peak, aggressive

    def test_only_the_capital_orientation_differs(self):
        a, b = HISTORICAL_RESETS.model_dump(), CAPITAL_AGGRESSIVE.model_dump()
        for x, y in zip(a["cycles"], b["cycles"]):
            if x["name"] != "capital":
                assert x == y
            else:
                assert {k for k in x if x[k] != y[k]} == {"orientation", "source"}



class TestCapitalInverted:
    def test_fall_rise_peaks_at_the_reset_and_bottoms_at_saturation(self):
        from cycle.engine import order_breaks, rise_fall_phase
        years = np.arange(1948.0, 2210.0)
        phase, _ = rise_fall_phase(years, 1948.0, 90.0, 130.0, inverted=True)
        at = lambda y: float(phase[list(years).index(y)])  # noqa: E731
        assert math.cos(at(1948.0)) == pytest.approx(1.0) and math.cos(at(2038.0)) == pytest.approx(-1.0)
        assert math.cos(at(2078.0)) == pytest.approx(1.0)
        assert [phase_of(at(y)) for y in (1960.0, 2010.0, 2050.0, 2070.0)] == [
            "slowdown", "contraction", "recovery", "expansion"]
        assert order_breaks([int(y) for y in years], phase) == ()

    def test_1_3_0_puts_a_saturated_economy_back_at_the_cautious_end(self, panel, macro):
        e3 = {"US": "US", "CN": "CN"}
        v11 = run_model(panel, HISTORICAL_RESETS, list(e3), e3, macro)
        v13 = run_model(panel, CAPITAL_INVERTED, list(e3), e3, macro)
        for a, b in zip(v11.economies, v13.economies):
            ca = {t.cycle: t for t in a.cycles}["capital"]
            cb = {t.cycle: t for t in b.cycles}["capital"]
            assert cb.level[-1] == pytest.approx(-ca.level[-1])              # the curve is mirrored
            assert cb.bin_centre[-1] == pytest.approx(ca.bin_centre[-1])     # the axis reading is 1.1.0's
            assert a.layer_mean_bin[-1] == pytest.approx(b.layer_mean_bin[-1])
        us = {t.cycle: t for t in v13.economies[0].cycles}["capital"]
        assert us.phase[-1] == "recovery" and us.bin_centre[-1] < 2       # just past its low



class TestProjection:
    def test_anchored_cycles_run_to_the_horizon_and_estimated_ones_stop(self, panel, macro):
        out = run_model(panel, CAPITAL_INVERTED, ["US", "CN"], {"US": "US", "CN": "CN"}, macro, horizon=2039)
        years = list(out.years)
        assert out.observed_until == 2025 and out.projected_until == 2039 and years[-1] == 2039
        for e in out.economies:
            tracks = {t.cycle: t for t in e.cycles}
            for name in ("innovation", "credit", "capital"):
                assert tracks[name].phase[-1] is not None, (e.code, name)
                assert tracks[name].order_breaks == ()
            for name in ("fundamental_pulse", "business"):
                assert all(p is None for p in tracks[name].phase[years.index(2025):])
            assert e.layer[-1] is not None and abs(sum(e.layer[-1]) - 1) < 1e-12
        # the projection does not move a single observed figure
        base = run_model(panel, CAPITAL_INVERTED, ["US", "CN"], {"US": "US", "CN": "CN"}, macro)
        n = len(base.years)
        for a, b in zip(base.economies, out.economies):
            for ta, tb in zip(a.cycles, b.cycles):
                assert ta.phase == tb.phase[:n] and ta.level == tb.level[:n]
        assert base.coverage.input_gaps == out.coverage.input_gaps

    def test_no_horizon_no_projection(self, panel, macro):
        out = run_model(panel, CAPITAL_INVERTED, ["US"], {"US": "US"}, macro)
        assert out.projected_until is None and out.years[-1] == out.observed_until == 2025


class TestAnchoredSuperposition:
    """R-004 / C-25: the aggregate continues into the projection over the anchored cycles only."""

    ANCHORED = ("credit", "innovation", "capital")

    @staticmethod
    def _expected(e, years, weights):
        tracks = {t.cycle: t for t in e.cycles}
        comps = {n: np.array([np.nan if v is None else v for v in tracks[n].component]) for n in weights}
        covered = np.logical_and.reduce([np.isfinite(c) for c in comps.values()])
        idx = np.flatnonzero(covered)
        s = slice(idx[0], idx[-1] + 1)
        total = sum(weights[n] * comps[n][s] for n in weights)          # unit amplitude, unscaled
        out = np.full(len(years), np.nan)
        out[s] = total / sum(weights.values())
        return out

    def test_it_runs_to_the_horizon_where_the_full_superposition_stops(self, panel, macro):
        out = run_model(panel, CAPITAL_INVERTED, ECONOMIES, {c: c for c in ECONOMIES}, macro, horizon=2039)
        years = list(out.years)
        for e in out.economies:
            assert e.anchored_members == self.ANCHORED, e.code
            assert all(v is not None and -1.0 - 1e-12 <= v <= 1.0 + 1e-12 for v in e.superposition_anchored), e.code
            assert all(v is None for v in e.superposition[years.index(2025):]), e.code
            got = np.array([np.nan if v is None else v for v in e.superposition_anchored])
            want = self._expected(e, years, {n: 1.0 for n in self.ANCHORED})
            assert np.allclose(got, want, atol=1e-12, equal_nan=True), e.code
            assert any("anchored superposition covers 1972 to 2039" in n for n in e.notes), e.code

    def test_the_weights_are_re_normalised_over_the_anchored_members(self, panel, macro):
        weights = {"fundamental_pulse": 5.0, "business": 3.0, "credit": 2.0, "innovation": 1.0, "capital": 1.0}
        cal = CAPITAL_INVERTED.model_copy(update={"cycles": tuple(
            c.model_copy(update={"superposition_weight": weights[c.name]}) for c in CAPITAL_INVERTED.cycles)})
        out = run_model(panel, cal, ["US"], {"US": "US"}, macro, horizon=2039)
        e = out.economies[0]
        got = np.array([np.nan if v is None else v for v in e.superposition_anchored])
        want = self._expected(e, list(out.years), {n: weights[n] for n in self.ANCHORED})
        assert np.allclose(got, want, atol=1e-12, equal_nan=True)
        assert "credit 0.5, innovation 0.25, capital 0.25" in e.notes[-1]

    def test_it_does_not_depend_on_the_horizon(self, panel, macro):
        a = run_model(panel, CAPITAL_INVERTED, ["US", "BR"], {"US": "US", "BR": "BR"}, macro, horizon=2039)
        b = run_model(panel, CAPITAL_INVERTED, ["US", "BR"], {"US": "US", "BR": "BR"}, macro, horizon=2080)
        n = len(a.years)
        for x, y in zip(a.economies, b.economies):
            assert x.superposition_anchored == y.superposition_anchored[:n], x.code
            assert x.superposition == y.superposition[:n], x.code
            tracks = {t.cycle: t for t in y.cycles}
            assert all(tracks[c].order_breaks == () for c in self.ANCHORED), x.code

    def test_the_published_field_is_the_engines_array(self, panel, macro):
        from cycle.engine import economy_contract, prepare_inputs, year_axis, annualise
        annual = annualise(panel, ["US"], CAPITAL_INVERTED.annualisation)
        years = year_axis(annual, macro, 2039)
        saturation, inputs = prepare_inputs(annual, CAPITAL_INVERTED, macro, years)
        result = run_economy(years, inputs[0], saturation[:, 0], CAPITAL_INVERTED, "US")
        e = economy_contract("US", "US", years, result)
        assert list(e.superposition_anchored) == [float(v) for v in result.superposition_anchored]
        assert [v for v in e.superposition if v is not None] == \
            [float(v) for v in result.superposition if np.isfinite(v)]
