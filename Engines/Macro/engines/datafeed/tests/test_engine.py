"""Unit and property tests for the pure rules (Engine Building Guide section 6.2).

The engine page's properties: panel alignment never invents a value; every carried cell is
flagged; plus the fill rules: a fit that does not hold is refused, and a fill never
touches a primary cell.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, strategies as st

from datafeed.engine import (
    apply_annual,
    assemble,
    axis,
    cell_sources,
    consumption_share_check,
    coverage,
    december_values,
    fit_level,
    fit_rate,
    spans,
)
from datafeed.etl.matlab import to_gaps

DATES = axis("2018-01-31", "2021-06-30")


class TestAxis:
    def test_month_ends_including_leap_years(self):
        assert axis("2020-01-31", "2020-03-31") == ("2020-01-31", "2020-02-29", "2020-03-31")

    def test_spans_break_on_gaps_and_on_a_change_of_source(self):
        s = spans(DATES[:6], ["a", "a", None, "a", "b", "b"])
        assert [(x.source, x.first, x.last) for x in s] == [
            ("a", DATES[0], DATES[1]), ("a", DATES[3], DATES[3]), ("b", DATES[4], DATES[5])]


cells_strategy = st.dictionaries(st.sampled_from(DATES), st.floats(-1e9, 1e9, allow_nan=False),
                                 max_size=len(DATES))


class TestAssembly:
    @given(cells_strategy)
    def test_assembly_never_invents_a_value(self, stored):
        cells = {("AA", "s"): {d: (v, "observed", "p") for d, v in stored.items()}}
        panel = assemble(snapshot_id="x", as_of="2021-06-30", primary_source="p", dates=DATES,
                         units={}, cells=cells, keys=[("AA", "s")])
        s = panel.series[0]
        for d, v, f in zip(panel.dates, s.values, s.flags):
            assert (v is None) == (d not in stored)
            assert v is None or v == stored[d]
            assert (f == "missing") == (d not in stored)

    def test_a_requested_series_with_nothing_stored_is_all_missing(self):
        panel = assemble(snapshot_id="x", as_of="2021-06-30", primary_source="p", dates=DATES,
                         units={}, cells={}, keys=[("AA", "s")])
        assert set(panel.series[0].flags) == {"missing"}


class TestFits:
    def test_a_level_fit_recovers_the_scale(self):
        cand = {y: 10.0 * (1.05 ** y) for y in range(2000, 2010)}
        prim = {y: v * 1e-3 for y, v in cand.items()}
        fit = fit_level(prim, cand, min_overlap=5, tolerance=0.01)
        assert fit.accepted and fit.scale == pytest.approx(1e-3) and fit.deviation < 1e-12

    def test_a_level_fit_refuses_a_drifting_ratio(self):
        cand = {y: 100.0 for y in range(2000, 2010)}
        prim = {y: 100.0 * (1 + 0.05 * (y - 2000)) for y in cand}      # drifts by 45%
        fit = fit_level(prim, cand, min_overlap=5, tolerance=0.10)
        assert not fit.accepted and "deviates" in fit.reason

    def test_too_little_overlap_is_refused_before_fitting(self):
        fit = fit_level({2000: 1.0, 2001: 1.0}, {2000: 1.0, 2001: 1.0}, min_overlap=5, tolerance=0.1)
        assert not fit.accepted and "overlapping" in fit.reason

    def test_a_rate_fit_recovers_a_steady_offset(self):
        cand = {y: 0.60 + 0.001 * (y % 3) for y in range(2000, 2012)}
        prim = {y: v - 0.015 for y, v in cand.items()}
        fit = fit_rate(prim, cand, min_overlap=5, tolerance=0.001)
        assert fit.accepted and fit.offset == pytest.approx(-0.015)

    @given(st.lists(st.floats(0.1, 1e6), min_size=5, max_size=20), st.floats(1e-6, 1e6))
    def test_an_exact_rescaling_always_fits(self, values, k):
        cand = {2000 + i: v for i, v in enumerate(values)}
        fit = fit_level({y: v * k for y, v in cand.items()}, cand, min_overlap=5, tolerance=1e-9)
        assert fit.accepted and fit.scale == pytest.approx(k)


class TestApply:
    def test_a_fill_goes_to_december_and_carries_into_the_next_year(self):
        out = apply_annual(DATES, {}, {2019: 7.0}, "pub", carry_months=11)
        assert out.cells["2019-12-31"] == (7.0, "observed", "pub")
        assert out.cells["2020-11-30"] == (7.0, "carried", "pub")
        assert "2020-12-31" not in out.cells
        assert (out.years, out.observed, out.carried) == ((2019,), 1, 11)

    def test_a_fill_never_overwrites_a_primary_cell(self):
        stored = {"2019-12-31": (1.0, "observed", "bbg"), "2020-03-31": (2.0, "observed", "bbg")}
        out = apply_annual(DATES, stored, {2019: 9.0, 2020: 9.0}, "pub", carry_months=11)
        assert out.cells["2019-12-31"] == (1.0, "observed", "bbg")
        assert out.cells["2020-12-31"] == (9.0, "observed", "pub")
        assert out.years == (2020,)

    def test_carrying_stops_at_the_next_present_cell(self):
        stored = {"2020-03-31": (2.0, "observed", "bbg")}
        out = apply_annual(DATES, stored, {2019: 9.0}, "pub", carry_months=11)
        assert out.cells["2020-02-29"][1] == "carried"
        assert out.cells["2020-03-31"] == (2.0, "observed", "bbg")
        assert "2020-04-30" not in out.cells

    @given(st.dictionaries(st.integers(2017, 2021), st.floats(-1e6, 1e6, allow_nan=False)),
           cells_strategy, st.integers(0, 11))
    def test_every_filled_cell_is_flagged_and_sourced(self, annual, primary, carry):
        stored = {d: (v, "observed", "bbg") for d, v in primary.items()}
        out = apply_annual(DATES, stored, annual, "pub", carry_months=carry)
        for d, cell in out.cells.items():
            if d in stored:
                assert cell == stored[d]
            else:
                assert cell[2] == "pub" and cell[1] in ("observed", "carried")
                assert (cell[1] == "observed") == d.endswith("-12-31")
        assert out.carried <= carry * len(out.years)


class TestCoverageAndPlausibility:
    def test_coverage_counts_public_cells(self):
        cells = {("AA", "s"): {"2019-12-31": (1.0, "observed", "p"), "2020-12-31": (2.0, "observed", "pub"),
                               "2021-01-31": (2.0, "carried", "pub")}}
        panel = assemble(snapshot_id="x", as_of="2021-06-30", primary_source="p", dates=DATES,
                         units={}, cells=cells, keys=[("AA", "s")])
        row = coverage(panel)[0]
        assert (row.observed, row.carried, row.from_public_sources) == (2, 1, 2)
        assert cell_sources(panel, panel.series[0]).count("pub") == 2

    def test_a_consumption_share_above_one_is_reported(self):
        cells = {("AA", "consumer.household_consumption"): {"2019-12-31": (400.0, "observed", "p")},
                 ("AA", "production.gdp_nominal"): {"2019-12-31": (100.0, "observed", "p")}}
        panel = assemble(snapshot_id="x", as_of="2021-06-30", primary_source="p", dates=DATES, units={},
                         cells=cells, keys=list(cells))
        found = consumption_share_check(panel, (0.2, 0.9))
        assert found and found[0].country == "AA"

    def test_december_values(self):
        assert december_values(DATES, {"2019-12-31": (5.0, "observed", "p"),
                                       "2019-11-30": (4.0, "observed", "p")}) == {2019: 5.0}


class TestZeroRule:
    def test_leading_and_trailing_zeros_are_gaps(self):
        values, counts = to_gaps(np.array([0, 0, 1, 2, 0]), zero_is_a_value=True)
        assert values == [None, None, 1.0, 2.0, None]
        assert (counts["leading_zero"], counts["trailing_zero"]) == (2, 1)

    def test_interior_zeros_survive_only_in_rate_series(self):
        x = np.array([1.0, 0.0, 2.0])
        assert to_gaps(x, zero_is_a_value=True)[0] == [1.0, 0.0, 2.0]
        assert to_gaps(x, zero_is_a_value=False)[0] == [1.0, None, 2.0]

    def test_nan_is_a_gap(self):
        assert to_gaps(np.array([np.nan, 3.0]), zero_is_a_value=False)[0] == [None, 3.0]
