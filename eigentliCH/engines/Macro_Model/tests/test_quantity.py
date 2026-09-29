"""Tests for the extended quantity equation and the unsecured-asset diagnostics, section 0.4."""

import numpy as np
import pytest

from macrofield.model.quantity import (
    check_financial_price_stability,
    diagnose_unsecured_assets,
    implied_financial_price_volume,
    unsecured_assets,
    unsecured_assets_ratio,
)


class TestUnsecuredAssets:
    def test_matches_the_definition(self):
        k_r = np.array([90.0, 95.0])
        k_i = np.array([210.0, 230.0])
        y = np.array([100.0, 105.0])
        assert np.allclose(unsecured_assets(k_r, k_i, y), [200.0, 220.0])

    def test_is_zero_when_capital_exactly_covers_output(self):
        """K_R + K_I = Y is the boundary at which no financial value is uncovered."""
        assert unsecured_assets(np.array([40.0]), np.array([60.0]), np.array([100.0]))[0] == 0.0

    def test_ratio_is_scale_free(self):
        """Doubling every quantity must leave the ratio unchanged, so it compares across economies."""
        small = unsecured_assets_ratio(np.array([90.0]), np.array([210.0]), np.array([100.0]))
        large = unsecured_assets_ratio(np.array([180.0]), np.array([420.0]), np.array([200.0]))
        assert small[0] == pytest.approx(large[0])

    def test_rejects_mismatched_shapes(self):
        with pytest.raises(ValueError, match="must share a shape"):
            unsecured_assets(np.array([90.0, 95.0]), np.array([210.0]), np.array([100.0]))

    def test_ratio_rejects_zero_output(self):
        with pytest.raises(ZeroDivisionError):
            unsecured_assets_ratio(np.array([90.0]), np.array([210.0]), np.array([0.0]))

    def test_implied_financial_price_volume_equals_the_gap(self):
        """The fundamental relation makes P_I H_I identical to the gap by construction."""
        k_r, k_i, y = np.array([90.0]), np.array([210.0]), np.array([100.0])
        assert implied_financial_price_volume(k_r, k_i, y) == pytest.approx(
            unsecured_assets(k_r, k_i, y)
        )


class TestUnsecuredAssetSignatures:
    def test_detects_the_phase_three_acceleration(self):
        """A convex path must fire the acceleration indicator once the run length is met."""
        y = np.full(10, 100.0)
        k_r = np.full(10, 90.0)
        # A quadratic in K_I gives a constant positive second difference.
        k_i = 200.0 + np.arange(10.0) ** 2
        diagnostics = diagnose_unsecured_assets(k_r, k_i, y, acceleration_periods=3)
        assert diagnostics.first_acceleration_index is not None
        assert diagnostics.accelerating[-1]

    def test_does_not_fire_on_a_linear_path(self):
        """Steady growth is not acceleration, so the indicator must stay silent."""
        y = np.full(10, 100.0)
        k_r = np.full(10, 90.0)
        k_i = 200.0 + 5.0 * np.arange(10.0)
        diagnostics = diagnose_unsecured_assets(k_r, k_i, y, acceleration_periods=3)
        assert diagnostics.first_acceleration_index is None
        assert not diagnostics.accelerating.any()

    def test_requires_a_sustained_run_not_a_single_period(self):
        """One noisy period must not fire the transition indicator."""
        y = np.full(8, 100.0)
        k_r = np.full(8, 90.0)
        # A single convex kink in an otherwise linear path.
        k_i = np.array([200.0, 205.0, 210.0, 220.0, 225.0, 230.0, 235.0, 240.0])
        diagnostics = diagnose_unsecured_assets(k_r, k_i, y, acceleration_periods=3)
        assert diagnostics.first_acceleration_index is None

    def test_detects_the_phase_four_collapse(self):
        y = np.full(6, 100.0)
        k_r = np.full(6, 90.0)
        k_i = np.array([300.0, 320.0, 330.0, 280.0, 220.0, 150.0])
        diagnostics = diagnose_unsecured_assets(k_r, k_i, y)
        assert diagnostics.first_collapse_index == 3
        assert diagnostics.collapsing[-1]

    def test_difference_arrays_align_with_the_input_periods(self):
        """Padding must keep every array the input length so indices line up with periods."""
        y = np.full(5, 100.0)
        k_r = np.full(5, 90.0)
        k_i = 200.0 + np.arange(5.0)
        diagnostics = diagnose_unsecured_assets(k_r, k_i, y)
        assert diagnostics.level.shape == (5,)
        assert diagnostics.growth.shape == (5,)
        assert diagnostics.acceleration.shape == (5,)
        assert np.isnan(diagnostics.growth[0])
        assert np.isnan(diagnostics.acceleration[:2]).all()


class TestFinancialPriceStability:
    def test_divergence_reduces_to_output_less_real_capital(self):
        """Documented equivalence: because the implied quantity is K_R + K_I - Y, the divergence is
        Y - K_R. The test pins the equivalence so the docstring cannot drift from the code."""
        k_r = np.array([90.0, 120.0])
        k_i = np.array([210.0, 230.0])
        y = np.array([100.0, 105.0])
        check = check_financial_price_stability(k_r, k_i, y)
        assert np.allclose(check.divergence, y - k_r)

    def test_fires_when_the_relative_divergence_exceeds_the_tolerance(self):
        k_r = np.array([90.0])
        k_i = np.array([100.0])
        y = np.array([50.0])
        # Divergence is 50 - 90 = -40 on an observed stock of 100, so 40 percent.
        check = check_financial_price_stability(k_r, k_i, y, tolerance=0.1)
        assert check.diverging[0]
        assert check.first_divergence_index == 0

    def test_stays_silent_inside_the_tolerance(self):
        k_r = np.array([100.0])
        k_i = np.array([200.0])
        y = np.array([105.0])
        # Divergence is 5 on 200, so 2.5 percent.
        check = check_financial_price_stability(k_r, k_i, y, tolerance=0.1)
        assert not check.diverging[0]
        assert check.first_divergence_index is None
