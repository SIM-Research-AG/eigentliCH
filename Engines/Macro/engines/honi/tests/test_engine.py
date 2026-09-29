"""Unit and property tests for the pure core (Engine Building Guide section 6.2).

The properties named on the engine page: the ramp is monotone within a segment, the tent
peaks exactly at the mid-point, both are bounded to [1, 5], and NaN propagates rather than
scoring 1. Plus the aggregation rules: re-weighting over missing indices, the sector
threshold, and per-year rescaling.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume, given, settings, strategies as st
from pydantic import ValidationError

from honi.calibration import DEFAULT, MATLAB
from honi.contracts import INDICES, Calibration, IndexSpec, Panel, Window
from honi.engine import (
    REQUIRED_SERIES,
    EngineError,
    annualise,
    growth,
    ramp,
    ratio,
    rescale_rows,
    resolve_years,
    run_model,
    score_annual,
    tent,
    trailing_mean,
    trend_min_obs,
    trend_stats,
)

finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)


@st.composite
def triples(draw):
    a, b, c = sorted(draw(st.lists(finite, min_size=3, max_size=3, unique=True)))
    assume(b - a > 1e-6 and c - b > 1e-6)
    return a, b, c


# ---------------------------------------------------------------------------
# Transfer functions
# ---------------------------------------------------------------------------

class TestRamp:
    def test_anchor_points(self):
        rng = (-0.10, -0.035, 0.0)
        assert ramp(np.array([-0.2, -0.10, -0.035, 0.0, 0.1]), rng).tolist() == \
            pytest.approx([1.0, 1.0, 2.5, 5.0, 5.0])

    def test_a_descending_range_inverts_the_direction(self):
        rng = (1.2, 1.0, 0.3)                                 # government debt: less is more
        assert ramp(np.array([1.5, 1.2, 1.0, 0.3, 0.1]), rng).tolist() == \
            pytest.approx([1.0, 1.0, 2.5, 5.0, 5.0])

    def test_nan_and_infinity_propagate(self):
        out = ramp(np.array([np.nan, np.inf, -np.inf]), (0.0, 1.0, 2.0))
        assert np.isnan(out).all()

    @given(triples(), st.lists(finite, min_size=2, max_size=50), st.booleans())
    def test_bounded_and_monotone(self, rng, xs, descending):
        if descending:
            rng = rng[::-1]
        x = np.sort(np.array(xs))
        y = ramp(x, rng)
        assert ((y >= 1.0) & (y <= 5.0)).all()
        steps = np.diff(y)
        assert (steps >= -1e-9).all() if not descending else (steps <= 1e-9).all()


class TestTent:
    def test_peaks_exactly_at_the_mid_point(self):
        for rng in [(0.3, 0.7, 1.2), (0.0, 0.008, 0.015), (0.1, 0.5, 5.0)]:
            assert tent(np.array([rng[1]]), rng)[0] == 5.0

    def test_one_at_and_beyond_the_ends(self):
        assert tent(np.array([-1.0, 0.3, 1.2, 9.0]), (0.3, 0.7, 1.2)).tolist() == \
            pytest.approx([1.0, 1.0, 1.0, 1.0])

    @given(triples(), st.lists(finite, min_size=1, max_size=50))
    def test_bounded_rising_then_falling(self, rng, xs):
        x = np.sort(np.array(xs))
        y = tent(x, rng)
        assert ((y >= 1.0) & (y <= 5.0)).all()
        below, above = x <= rng[1], x >= rng[1]
        assert (np.diff(y[below]) >= -1e-9).all()
        assert (np.diff(y[above]) <= 1e-9).all()

    @given(triples())
    def test_nan_propagates(self, rng):
        assert np.isnan(tent(np.array([np.nan]), rng)).all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_the_first_growth_rate_is_missing_not_zero(self):
        g = growth(np.array([[100.0], [110.0], [99.0]]))
        assert np.isnan(g[0, 0])
        assert g[1:, 0] == pytest.approx([0.10, -0.10])

    def test_division_by_zero_is_missing(self):
        assert np.isnan(ratio(np.array([1.0, 0.0]), np.array([0.0, 0.0]))).all()

    def test_growth_from_zero_is_missing(self):
        assert np.isnan(growth(np.array([[0.0], [5.0]]))[1, 0])

    def test_trailing_mean_shrinks_at_the_start_and_skips_gaps(self):
        x = np.array([[1.0], [2.0], [np.nan], [4.0], [5.0], [6.0]])
        out = trailing_mean(x, window=5, min_obs=1)[:, 0]
        assert out.tolist() == pytest.approx([1.0, 1.5, 1.5, 7 / 3, 3.0, 17 / 4])

    def test_trailing_mean_honours_the_minimum_count(self):
        x = np.array([[1.0], [np.nan], [np.nan]])
        out = trailing_mean(x, window=2, min_obs=2)[:, 0]
        assert np.isnan(out).all()

    @given(st.lists(st.lists(st.one_of(finite, st.just(float("nan"))), min_size=3, max_size=3),
                    min_size=1, max_size=10))
    def test_rescaled_rows_span_one_to_five(self, rows):
        m = rescale_rows(np.array(rows))
        for raw, out in zip(np.array(rows), m):
            present = np.isfinite(raw)
            assert np.array_equal(np.isnan(out), ~present)
            if present.sum() >= 2 and raw[present].max() > raw[present].min():
                assert out[present].min() == pytest.approx(1.0)
                assert out[present].max() == pytest.approx(5.0)

    def test_a_constant_row_rescales_to_the_floor(self):
        assert rescale_rows(np.array([[2.0, 2.0, 2.0]])).tolist() == [[1.0, 1.0, 1.0]]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def raw_block(years=3, countries=4, seed=7) -> dict[str, np.ndarray]:
    """Plausible raw values: each index drawn inside its own calibration range."""
    rng = np.random.default_rng(seed)
    out = {}
    for spec in DEFAULT.indices:
        lo, hi = sorted((spec.range[0], spec.range[2]))
        out[spec.name] = rng.uniform(lo, hi, size=(years, countries))
    return out


class TestAggregation:
    def test_a_missing_index_is_dropped_and_the_sector_reweighted(self):
        raw = raw_block()
        raw["budget_balance"][0, 0] = np.nan
        cal = DEFAULT.model_copy(update={"rescale_sectors": False, "rescale_national": False})
        out = score_annual([2020, 2021, 2022], list("ABCD"), raw, np.zeros((3, 4)), cal)
        others = [n for n, s in INDICES.items() if s == "financial" and n != "budget_balance"]
        expected = np.mean([out.index_scores[n][0, 0] for n in others])
        assert out.sectors["financial"][0, 0] == pytest.approx(expected)
        dropped = [d for d in out.coverage.dropped if d.country == "A" and d.year == 2020]
        assert dropped[0].indices_missing == ("budget_balance",) and dropped[0].scored

    def test_a_sector_below_the_threshold_is_left_unscored(self):
        raw = raw_block()
        for name in ("budget_balance", "monetary_supply", "government_debt"):
            raw[name][1, 2] = np.nan
        out = score_annual([2020, 2021, 2022], list("ABCD"), raw, np.zeros((3, 4)), DEFAULT)
        assert np.isnan(out.sectors["financial"][1, 2])
        assert np.isnan(out.national[1, 2])
        assert out.coverage.sectors_unscored == 1 and out.coverage.national_unscored == 1

    def test_the_matlab_policy_scores_a_gap_as_worst_but_still_reports_it(self):
        raw = raw_block()
        raw["labour_force"][2, 3] = np.nan
        out = score_annual([2020, 2021, 2022], list("ABCD"), raw, np.zeros((3, 4)), MATLAB)
        assert out.index_scores["labour_force"][2, 3] == 1.0
        assert out.coverage.index_cells_missing == 1
        assert out.coverage.dropped[0].indices_missing == ("labour_force",)

    @settings(max_examples=30, deadline=None)
    @given(st.integers(min_value=0, max_value=10_000))
    def test_the_best_country_scores_five_and_the_worst_one_every_year(self, seed):
        out = score_annual([2020, 2021, 2022], list("ABCD"), raw_block(seed=seed),
                           np.zeros((3, 4)), DEFAULT)
        for row in out.national:
            if np.nanmax(row) > np.nanmin(row):
                assert np.nanmax(row) == pytest.approx(5.0)
                assert np.nanmin(row) == pytest.approx(1.0)

    def test_without_rescaling_the_national_score_is_the_weighted_sector_mean(self):
        cal = DEFAULT.model_copy(update={"rescale_sectors": False, "rescale_national": False})
        out = score_annual([2020], list("ABCD"), raw_block(years=1), np.zeros((1, 4)), cal)
        expected = np.mean([out.sectors[s] for s in ("financial", "international", "real")], axis=0)
        assert out.national == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Annualisation and the whole model
# ---------------------------------------------------------------------------

def tiny_panel(first=(2019, 11), months=27, value=lambda t: 1.0 + t) -> Panel:
    dates, (y, m) = [], first
    for _ in range(months):
        dates.append(f"{y:04d}-{m:02d}-28")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    series = [{"country": c, "series_id": s, "values": [value(t) for t in range(months)],
               "flags": ["observed"] * months}
              for c in ("AA", "BB") for s in REQUIRED_SERIES]
    return Panel(snapshot_id="t", as_of="2022-01-31", primary_source="bloomberg", dates=dates, series=series)


class TestAnnualisation:
    def test_year_end_takes_december(self):
        a = annualise(tiny_panel(), ["AA", "BB"], "year_end")
        assert a.years == (2019, 2020, 2021)
        assert a.data["fx.reserves"][:, 0].tolist() == [2.0, 14.0, 26.0]

    def test_mean_needs_the_whole_calendar_year(self):
        a = annualise(tiny_panel(), ["AA", "BB"], "mean")
        assert a.years == (2020, 2021)
        assert a.data["fx.reserves"][0, 0] == pytest.approx(np.mean(np.arange(3, 15)))

    def test_a_missing_december_is_missing_not_carried(self):
        p = tiny_panel()
        s = p.series[0]
        values = list(s.values); flags = list(s.flags)
        values[13], flags[13] = None, "missing"                      # December 2020
        p = p.model_copy(update={"series": (s.model_copy(update={"values": tuple(values),
                                                                 "flags": tuple(flags)}),
                                            *p.series[1:])})
        a = annualise(p, ["AA", "BB"], "year_end")
        assert np.isnan(a.data[s.series_id][1, 0])


class TestRunModel:
    def test_an_absent_country_fails_loudly(self, panel):
        with pytest.raises(EngineError, match="ZZ"):
            run_model(panel, DEFAULT, ["US", "ZZ"], None, 20)

    def test_a_window_outside_the_snapshot_fails_loudly(self):
        with pytest.raises(EngineError, match="outside"):
            resolve_years((2006, 2007, 2008), Window(start_year=2000, end_year=2007), 20)

    def test_the_window_slices_without_changing_values(self, panel):
        countries = ["US", "CN", "DE", "BR"]
        full = run_model(panel, DEFAULT, countries, None, 20)
        part = run_model(panel, DEFAULT, countries, Window(start_year=2015, end_year=2019), 20)
        rows = [full.years.index(y) for y in part.years]
        assert part.years == (2015, 2016, 2017, 2018, 2019)
        assert np.array_equal(part.national, full.national[rows], equal_nan=True)


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

class TestContracts:
    def test_a_tent_needs_an_ascending_triple(self):
        with pytest.raises(ValidationError):
            IndexSpec(name="market_cap", kind="tent", range=(1.2, 0.7, 0.3), weight=1)

    def test_a_ramp_needs_a_strictly_monotone_triple(self):
        with pytest.raises(ValidationError):
            IndexSpec(name="labour_force", kind="ramp", range=(0.5, 0.9, 0.7), weight=1)

    def test_a_calibration_must_define_every_index(self):
        with pytest.raises(ValidationError, match="fifteen"):
            Calibration(version="9.0.0", indices=DEFAULT.indices[:-1],
                        sector_weights=DEFAULT.sector_weights)

    def test_sector_weights_must_sum_to_one(self):
        with pytest.raises(ValidationError, match="sum to 1"):
            Calibration(version="9.0.0", indices=DEFAULT.indices,
                        sector_weights={"financial": 0.5, "international": 0.5, "real": 0.5})

    def test_panel_dates_must_be_consecutive(self):
        with pytest.raises(ValidationError, match="consecutive"):
            Panel(snapshot_id="x", as_of="2020-01-01", dates=("2020-01-31", "2020-03-31"),
                  series=())

    def test_a_missing_cell_must_be_flagged_missing(self):
        with pytest.raises(ValidationError, match="missing exactly"):
            Panel(snapshot_id="x", as_of="2020-01-01", dates=("2020-01-31",),
                  series=[{"country": "AA", "series_id": "s", "values": [None],
                           "flags": ["observed"]}])


class TestTrends:
    YEARS = list(range(2010, 2026))

    def column(self, values):
        return [[v] for v in values]

    def test_a_straight_line_has_its_slope_and_change(self):
        m = self.column([1.0 + 0.25 * k for k in range(16)])
        t = trend_stats(m, self.YEARS, 2025, 10)
        assert t["slope"][0] == pytest.approx(0.25, abs=1e-12)
        assert t["change"][0] == pytest.approx(2.5, abs=1e-12)  # 2025 against 2015
        assert t["base"][0] == pytest.approx(2.25) and t["latest"][0] == pytest.approx(4.75)
        assert t["n"] == (10,)

    def test_level_z_uses_the_window_only(self):
        values = [100.0] * 6 + [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]  # the window is 2016-2025
        t = trend_stats(self.column(values), self.YEARS, 2025, 10)
        window = np.arange(1, 11, dtype=float)
        assert t["level_z"][0] == pytest.approx((10 - window.mean()) / window.std(ddof=1), abs=1e-12)

    def test_missing_stays_missing(self):
        values = [None] * 16
        values[-1] = 3.0
        t = trend_stats(self.column(values), self.YEARS, 2025, 10)
        assert t["slope"] == (None,) and t["level_z"] == (None,) and t["change"] == (None,)
        assert t["latest"] == (3.0,) and t["n"] == (1,)

    def test_a_flat_window_has_no_z_score(self):
        t = trend_stats(self.column([2.0] * 16), self.YEARS, 2025, 10)
        assert t["slope"][0] == 0.0 and t["level_z"] == (None,)

    def test_below_min_obs_there_is_no_slope(self):
        values = [None] * 16
        for k in (-1, -2, -3, -4):
            values[k] = float(k)
        assert trend_min_obs(10) == 5
        t = trend_stats(self.column(values), self.YEARS, 2025, 10)
        assert t["slope"] == (None,) and t["n"] == (4,)

    def test_the_base_year_may_fall_before_the_artefact(self):
        t = trend_stats(self.column([1.0] * 16), self.YEARS, 2015, 10)
        assert t["base"] == (None,) and t["change"] == (None,) and t["n"] == (6,)

    def test_a_year_outside_the_artefact_is_refused(self):
        with pytest.raises(EngineError, match="not in the artefact"):
            trend_stats(self.column([1.0] * 16), self.YEARS, 2030, 10)
        with pytest.raises(EngineError, match="at least 3"):
            trend_stats(self.column([1.0] * 16), self.YEARS, 2025, 2)

    @given(st.lists(st.one_of(finite, st.none()), min_size=16, max_size=16),
           st.floats(min_value=-5, max_value=5), st.floats(min_value=-5, max_value=5),
           st.integers(min_value=3, max_value=16))
    def test_slope_and_z_are_invariant_the_right_way_under_an_affine_map(self, values, a, b, window):
        """slope(a + b x) = b slope(x); z(a + b x) = sign(b) z(x); n is unchanged."""
        assume(abs(b) > 1e-3)
        mapped = [None if v is None else a + b * v for v in values]
        t0 = trend_stats(self.column(values), self.YEARS, 2025, window)
        t1 = trend_stats(self.column(mapped), self.YEARS, 2025, window)
        assert t0["n"] == t1["n"]
        if t0["slope"][0] is not None and t1["slope"][0] is not None:
            assert t1["slope"][0] == pytest.approx(b * t0["slope"][0], rel=1e-6, abs=1e-3)
        if t0["level_z"][0] is not None and t1["level_z"][0] is not None:
            assert t1["level_z"][0] == pytest.approx(np.sign(b) * t0["level_z"][0], rel=1e-6, abs=1e-6)
