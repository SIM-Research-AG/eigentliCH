"""The numerical primitives, tested against the MATLAB conventions they reproduce."""

from __future__ import annotations

import math

import pytest

from engines.fund_map import numerics as num


class TestSpread:
    def test_std_uses_the_n_minus_one_normalisation(self):
        # Population std of [1,2,3,4] is 1.118; sample std is 1.291. MATLAB defaults to
        # the sample form and the published figures depend on it.
        assert num.std([1, 2, 3, 4]) == pytest.approx(1.2909944487358056)

    def test_std_refuses_a_single_observation(self):
        with pytest.raises(ValueError):
            num.std([1.0])

    def test_standardise_refuses_a_constant_series(self):
        with pytest.raises(ValueError, match="constant"):
            num.standardise([2.0] * 10)


class TestTrimmedMean:
    def test_trims_from_both_tails(self):
        assert num.trimmed_mean(list(range(20)), 0.2) == pytest.approx(9.5)

    def test_resists_a_one_sided_outlier(self):
        clean = list(range(20))
        dirty = clean[:-1] + [10_000]
        assert num.trimmed_mean(dirty, 0.2) == num.trimmed_mean(clean, 0.2)

    def test_zero_trim_is_the_plain_mean(self):
        values = [1.0, 2.0, 30.0]
        assert num.trimmed_mean(values, 0.0) == pytest.approx(num.mean(values))

    def test_rejects_a_proportion_of_a_half_or_more(self):
        with pytest.raises(ValueError):
            num.trimmed_mean([1.0, 2.0], 0.5)


class TestDetrending:
    def test_linear_residuals_of_a_straight_line_are_zero(self):
        ys = [3.0 + 2.0 * (i + 1) for i in range(40)]
        assert max(abs(r) for r in num.polyfit1_residuals(ys)) < 1e-9

    def test_linear_residuals_sum_to_zero(self):
        ys = [math.sin(i) + 0.1 * i for i in range(50)]
        assert abs(sum(num.polyfit1_residuals(ys))) < 1e-9

    def test_exponential_fit_recovers_a_clean_exponential(self):
        ys = [2.5 * math.exp(0.013 * (i + 1)) for i in range(150)]
        assert max(abs(r) for r in num.expfit1_residuals(ys)) < 1e-9

    def test_exponential_fit_beats_a_linear_one_on_curved_data(self):
        """The reason debt saturation is de-trended exponentially rather than linearly."""
        ys = [1.2 * math.exp(0.02 * (i + 1)) for i in range(150)]
        exp_sse = sum(r * r for r in num.expfit1_residuals(ys))
        lin_sse = sum(r * r for r in num.polyfit1_residuals(ys))
        assert exp_sse < lin_sse * 1e-6

    def test_exponential_fit_requires_positive_values(self):
        with pytest.raises(ValueError, match="positive"):
            num.expfit1_residuals([1.0, -1.0, 2.0])


class TestMovingWindow:
    def test_trailing_window_never_sees_the_future(self):
        rising = list(range(10))
        falling = list(range(10))[::-1]
        # A trailing window of the same magnitudes gives the same spread either way,
        # but the point is the shape: element i depends only on i-2..i.
        assert num.movstd_trailing(rising, 2)[3] == pytest.approx(num.std([1, 2, 3]))
        assert num.movstd_trailing(falling, 2)[3] == pytest.approx(num.std([8, 7, 6]))

    def test_the_first_element_is_zero_not_nan(self):
        assert num.movstd_trailing([5.0, 6.0, 7.0], 2)[0] == 0.0

    def test_the_window_shrinks_at_the_start(self):
        out = num.movstd_trailing([0.0, 2.0, 4.0, 6.0], 2)
        assert out[1] == pytest.approx(num.std([0.0, 2.0]))
        assert out[2] == pytest.approx(num.std([0.0, 2.0, 4.0]))
        assert out[3] == pytest.approx(num.std([2.0, 4.0, 6.0]))


class TestPchip:
    XS = [1.0, 2.0, 3.0, 4.0, 5.0]
    GRID = [0.6 + 0.2 * i for i in range(25)]

    def test_reproduces_its_knots_exactly(self):
        ys = [0.0, 0.1, 0.15, 0.9, 1.0]
        out = num.pchip_eval(self.XS, ys, self.XS)
        assert out == pytest.approx(ys, abs=1e-15)

    def test_is_exact_on_a_straight_line_including_outside_the_hull(self):
        out = num.pchip_eval(self.XS, [1.0, 2.0, 3.0, 4.0, 5.0], self.GRID)
        assert out == pytest.approx(self.GRID, abs=1e-12)

    def test_preserves_monotonicity_inside_the_hull(self):
        """The property that makes pchip the right choice over a cubic spline.

        A spline through these knots overshoots between states 3 and 4 and invents a
        return reversal that is not in the data.
        """
        ys = [0.0, 0.1, 0.15, 0.9, 1.0]
        inside = [v for q, v in zip(self.GRID, num.pchip_eval(self.XS, ys, self.GRID))
                  if 1.0 <= q <= 5.0]
        assert all(b >= a - 1e-12 for a, b in zip(inside, inside[1:]))

    def test_flattens_at_a_local_extremum(self):
        """Opposing secants set the derivative to zero, so no overshoot past a peak."""
        ys = [0.0, 1.0, 0.0, 1.0, 0.0]
        out = num.pchip_eval(self.XS, ys, [q for q in self.GRID if 1.0 <= q <= 5.0])
        assert max(out) <= 1.0 + 1e-12
        assert min(out) >= 0.0 - 1e-12

    def test_extrapolates_outside_the_hull(self):
        """Documented behaviour, relied on by the calibration and labelled in the output."""
        ys = [0.0, 0.1, 0.15, 0.9, 1.0]
        out = num.pchip_eval(self.XS, ys, [0.6, 5.4])
        assert out[0] < ys[0]
        assert out[1] < ys[-1]  # the end cubic turns over past the last knot

    def test_rejects_unsorted_knots(self):
        with pytest.raises(ValueError, match="strictly increasing"):
            num.pchip_eval([1.0, 3.0, 2.0], [1.0, 2.0, 3.0], [1.5])


class TestEmpiricalDistribution:
    def test_centile_counts_ties_at_half_weight(self):
        # The `nless + 0.5 * nequal` device the reference uses.
        assert num.centile_of([1, 2, 2, 3], 2) == pytest.approx(100 * (1 + 1.0) / 4)

    def test_percentile_uses_the_matlab_placement(self):
        """MATLAB places order statistics at 100*(i-0.5)/n; numpy at 100*i/(n-1).

        They disagree in the tails, which is where the quantile bridge does its most
        consequential work, so the convention is pinned.
        """
        sample = [10.0, 20.0, 30.0, 40.0]
        # Positions are 12.5, 37.5, 62.5, 87.5.
        assert num.percentile(sample, 12.5) == pytest.approx(10.0)
        assert num.percentile(sample, 50.0) == pytest.approx(25.0)
        assert num.percentile(sample, 87.5) == pytest.approx(40.0)

    def test_percentile_clamps_outside_the_order_statistics(self):
        sample = [10.0, 20.0, 30.0, 40.0]
        assert num.percentile(sample, 0.0) == 10.0
        assert num.percentile(sample, 100.0) == 40.0
