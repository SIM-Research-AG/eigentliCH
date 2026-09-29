"""The objective, verified by arithmetic rather than against another implementation.

There is no MATLAB to reconcile against (decisions.md D0), so the objective's correctness rests on cases
whose value can be worked out by hand and checked by reading. The three properties that a careless
rewrite loses each get their own test: the shortfall is summed before squaring, only the downside is
penalised, and each instrument is scaled by the regime weight of the state.
"""

from __future__ import annotations

import numpy as np
import pytest

from pcp.model.objective import (
    achieved_curve,
    curve_objective,
    curve_objective_gradient,
    shortfall_by_state,
)


class TestHandComputed:
    def test_two_instruments_two_states(self):
        """Worked through by hand.

        BB = [[0.10, 0.20],
              [0.30, 0.40]]      two instruments, two states
        x  = [0.5, 0.5]
        C  = [0.50, 0.10]
        M  = [1.0, 0.5]

        State 0: contributions are M0*x0*BB[0,0] = 1.0*0.5*0.10 = 0.05
                                   M0*x1*BB[1,0] = 1.0*0.5*0.30 = 0.15
                 shortfalls        max(0.50-0.05, 0) = 0.45
                                   max(0.50-0.15, 0) = 0.35
                 summed            0.80          squared 0.6400

        State 1: contributions are M1*x0*BB[0,1] = 0.5*0.5*0.20 = 0.05
                                   M1*x1*BB[1,1] = 0.5*0.5*0.40 = 0.10
                 shortfalls        max(0.10-0.05, 0) = 0.05
                                   max(0.10-0.10, 0) = 0.00
                 summed            0.05          squared 0.0025

        y = 0.6400 + 0.0025 = 0.6425
        """
        bb = np.array([[0.10, 0.20], [0.30, 0.40]])
        x = np.array([0.5, 0.5])
        c = np.array([0.50, 0.10])
        m = np.array([1.0, 0.5])

        per_state = shortfall_by_state(x, bb, c, m)
        assert per_state == pytest.approx([0.80, 0.05])
        assert curve_objective(x, bb, c, m) == pytest.approx(0.6425)

    def test_shortfall_is_summed_before_squaring(self):
        """The distinguishing property. Squaring per instrument then summing gives a different number.

        From the case above: summing first gives 0.80^2 + 0.05^2 = 0.6425. Squaring first would give
        (0.45^2 + 0.35^2) + (0.05^2 + 0.00^2) = 0.2025 + 0.1225 + 0.0025 = 0.3275.
        """
        bb = np.array([[0.10, 0.20], [0.30, 0.40]])
        x = np.array([0.5, 0.5])
        c = np.array([0.50, 0.10])
        m = np.array([1.0, 0.5])

        assert curve_objective(x, bb, c, m) == pytest.approx(0.6425)
        assert curve_objective(x, bb, c, m) != pytest.approx(0.3275)

    def test_only_the_downside_is_penalised(self):
        """Exceeding the target in a state costs nothing, so an improvement above it cannot change y."""
        bb = np.array([[1.0, 1.0]])
        x = np.array([1.0])
        m = np.array([1.0, 1.0])

        # Target below the contribution in both states: no shortfall anywhere.
        assert curve_objective(x, bb, np.array([0.5, 0.5]), m) == pytest.approx(0.0)
        # Raising the contribution further still costs nothing.
        assert curve_objective(x, np.array([[5.0, 5.0]]), np.array([0.5, 0.5]), m) == pytest.approx(0.0)

    def test_a_symmetric_fit_would_disagree(self):
        """A least-squares fit would penalise overshoot. This objective must not."""
        bb = np.array([[2.0]])
        x = np.array([1.0])
        c = np.array([1.0])
        m = np.array([1.0])
        # Contribution 2.0 against a target of 1.0: overshoot by 1.0, and no cost.
        assert curve_objective(x, bb, c, m) == pytest.approx(0.0)

    def test_the_regime_scales_each_contribution(self):
        """A state carrying no regime weight contributes its full target as shortfall.

        With M[i] = 0 the contribution is zero regardless of the weights, so the shortfall is C[i] per
        instrument. That is the specified form: the regime scales the contribution, not the target.
        """
        bb = np.array([[1.0], [1.0]])
        x = np.array([0.5, 0.5])
        c = np.array([0.30])
        m = np.array([0.0])
        # Two instruments, each short by 0.30, summed to 0.60, squared to 0.36.
        assert curve_objective(x, bb, c, m) == pytest.approx(0.36)

    def test_zero_weights_leave_the_full_target_short(self):
        bb = np.array([[0.5, 0.5]])
        x = np.array([0.0])
        c = np.array([0.20, 0.10])
        m = np.array([1.0, 1.0])
        assert curve_objective(x, bb, c, m) == pytest.approx(0.20 ** 2 + 0.10 ** 2)


class TestGradient:
    """The analytic gradient must agree with a central difference away from the kinks."""

    @staticmethod
    def _numeric(x, bb, c, m, step=1e-7):
        out = np.zeros_like(x, dtype=float)
        for j in range(x.size):
            up, down = x.astype(float).copy(), x.astype(float).copy()
            up[j] += step
            down[j] -= step
            out[j] = (curve_objective(up, bb, c, m) - curve_objective(down, bb, c, m)) / (2 * step)
        return out

    def test_agrees_with_a_central_difference(self):
        rng = np.random.default_rng(20260728)
        bb = rng.normal(0.05, 0.2, size=(6, 25))
        c = np.linspace(-0.4, 0.3, 25)
        m = np.full(25, 1.0 / 25)
        x = np.full(6, 1.0 / 6)

        analytic = curve_objective_gradient(x, bb, c, m)
        numeric = self._numeric(x, bb, c, m)
        assert analytic == pytest.approx(numeric, abs=1e-4)

    def test_a_state_with_no_shortfall_contributes_nothing(self):
        """Where the target is already met, the derivative through that state is zero."""
        bb = np.array([[10.0]])
        x = np.array([1.0])
        c = np.array([0.1])
        m = np.array([1.0])
        assert curve_objective_gradient(x, bb, c, m) == pytest.approx([0.0])

    def test_the_gradient_points_downhill(self):
        """Raising a weight that reduces shortfall must have a negative partial derivative."""
        bb = np.array([[0.5], [0.5]])
        x = np.array([0.1, 0.1])
        c = np.array([1.0])
        m = np.array([1.0])
        assert np.all(curve_objective_gradient(x, bb, c, m) < 0.0)


class TestAchievedCurve:
    def test_is_the_weighted_profile(self):
        bb = np.array([[1.0, 2.0], [3.0, 4.0]])
        x = np.array([0.25, 0.75])
        assert achieved_curve(x, bb) == pytest.approx([0.25 * 1 + 0.75 * 3, 0.25 * 2 + 0.75 * 4])

    def test_is_not_the_quantity_the_objective_compares(self):
        """Stated as a test so the distinction is not lost: the objective scales by the regime, the
        achieved curve does not, so the two differ whenever the regime is not uniform at one."""
        bb = np.array([[0.4, 0.4]])
        x = np.array([1.0])
        c = np.array([0.4, 0.4])
        m = np.array([0.5, 0.5])

        assert achieved_curve(x, bb) == pytest.approx([0.4, 0.4])
        # The achieved curve meets the target exactly, yet the objective is non-zero because the regime
        # halves each contribution.
        assert curve_objective(x, bb, c, m) > 0.0


class TestValidation:
    def test_a_weight_count_mismatch_is_refused(self):
        with pytest.raises(ValueError, match="weights against"):
            curve_objective(np.zeros(3), np.zeros((2, 25)), np.zeros(25), np.zeros(25))

    def test_a_target_length_mismatch_is_refused(self):
        with pytest.raises(ValueError, match="target curve"):
            curve_objective(np.zeros(2), np.zeros((2, 25)), np.zeros(24), np.zeros(25))

    def test_a_regime_length_mismatch_is_refused(self):
        with pytest.raises(ValueError, match="regime vector"):
            curve_objective(np.zeros(2), np.zeros((2, 25)), np.zeros(25), np.zeros(24))
