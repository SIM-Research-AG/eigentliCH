"""Tests for the three-body EDM, including the two-body consistency check of section 0.3."""

import numpy as np
import pytest

from macrofield.model.edm import (
    ClosureMode,
    EDMParameters,
    balanced_growth_solution,
    derivatives,
    genreith_residual,
    identity_residuals,
    investment_share,
    p_p_identity_implied_y_dot,
    simulate,
    two_body_residual,
)

# A late-cycle developed economy, in consistent arbitrary currency units. These are test fixtures
# chosen to exercise the algebra, not data, and nothing here reaches the model as input.
STATE = (100.0, 90.0, 210.0)

# The balanced-growth ray, where K_R = Y so that r = 0. See balanced_growth_solution.
BALANCED_STATE = (100.0, 100.0, 210.0)


def constant_params(stimulus: float = 0.0, **overrides: float) -> EDMParameters:
    """Return a constant-parameter set for algebraic tests."""
    values = {"p_s": 0.22, "p_p": 0.045, "p_b": 0.035, "alpha": 0.6}
    values.update(overrides)
    return EDMParameters(stimulus=stimulus, **values)


class TestInvestmentShare:
    def test_matches_definition(self):
        assert investment_share(STATE) == pytest.approx(1.0 - 90.0 / 100.0)

    def test_undefined_at_zero_output(self):
        with pytest.raises(ZeroDivisionError):
            investment_share((0.0, 90.0, 210.0))


class TestEquationsOfMotion:
    def test_matches_section_0_2_term_by_term(self):
        """The right-hand side must reproduce section 0.2 exactly, written out independently."""
        params = constant_params(stimulus=7.0)
        y, k_r, k_i = STATE
        p = params.at(0.0)
        r = 1.0 - k_r / y

        expected_k_r_dot = (1.0 - p.alpha) * p.p_s * y + p.p_p * k_r + r * k_i
        expected_k_i_dot = p.alpha * p.p_s * y + p.p_p * k_i - r * k_i + p.stimulus
        expected_y_dot = (p.p_b - p.p_s) * y + expected_k_r_dot - p.p_p * k_r + p.stimulus

        got = derivatives(0.0, STATE, params, ClosureMode.AS_WRITTEN)
        assert got[0] == pytest.approx(expected_y_dot)
        assert got[1] == pytest.approx(expected_k_r_dot)
        assert got[2] == pytest.approx(expected_k_i_dot)

    def test_identity_closed_mode_halves_the_output_equation(self):
        """Imposing the p_p definition collapses the Y equation to ((p_b - p_s) Y + S) / 2."""
        params = constant_params(stimulus=7.0)
        p = params.at(0.0)
        got = derivatives(0.0, STATE, params, ClosureMode.IDENTITY_CLOSED)
        assert got[0] == pytest.approx(0.5 * ((p.p_b - p.p_s) * STATE[0] + p.stimulus))

    def test_capital_equations_are_closure_invariant(self):
        """Neither capital equation refers to Y_dot, so the closure mode cannot change them."""
        params = constant_params(stimulus=7.0)
        as_written = derivatives(0.0, STATE, params, ClosureMode.AS_WRITTEN)
        closed = derivatives(0.0, STATE, params, ClosureMode.IDENTITY_CLOSED)
        assert as_written[1] == pytest.approx(closed[1])
        assert as_written[2] == pytest.approx(closed[2])

    def test_time_varying_parameters_are_evaluated_at_t(self):
        params = EDMParameters(
            p_s=lambda t: 0.20 + 0.01 * t,
            p_p=0.045,
            p_b=0.035,
            alpha=0.6,
        )
        assert params.at(0.0).p_s == pytest.approx(0.20)
        assert params.at(2.0).p_s == pytest.approx(0.22)


class TestTwoBodyConsistency:
    """Section 0.3. See docs/MODEL_SPEC.md section 2 for why there are two forms."""

    @pytest.mark.parametrize("stimulus", [0.0, 5.0, -3.0, 42.5])
    @pytest.mark.parametrize("closure", list(ClosureMode))
    def test_stimulus_inclusive_identity_is_exact(self, stimulus, closure):
        """K_R_dot + K_I_dot = p_s Y + p_p K + S holds identically, for any stimulus."""
        params = constant_params(stimulus=stimulus)
        assert two_body_residual(0.0, STATE, params, closure) == pytest.approx(0.0, abs=1e-12)

    def test_genreith_reduction_is_exact_at_zero_stimulus(self):
        """With S = 0 the system reduces to Genreith's K_dot = p_s Y + p_p K exactly."""
        params = constant_params(stimulus=0.0)
        assert genreith_residual(0.0, STATE, params) == pytest.approx(0.0, abs=1e-12)

    @pytest.mark.parametrize("stimulus", [5.0, -3.0, 42.5])
    def test_genreith_residual_equals_the_stimulus(self, stimulus):
        """With a live stimulus the Genreith residual is exactly S, not a numerical error."""
        params = constant_params(stimulus=stimulus)
        assert genreith_residual(0.0, STATE, params) == pytest.approx(stimulus)

    def test_identity_holds_along_a_simulated_path(self):
        """The residual must stay at zero through an integration, not only at the initial state.

        Uses the balanced-growth ray, because an arbitrary constant-parameter set drives the system
        to a finite-time singularity (see TestFiniteTimeSingularity) and there is then no path along
        which to check anything.
        """
        params = EDMParameters(p_s=1e-12, p_p=0.03, p_b=0.03, alpha=0.0, stimulus=0.0)
        result = simulate(BALANCED_STATE, params, (0.0, 20.0), t_eval=np.linspace(0.0, 20.0, 81))
        assert result.success
        assert result.max_abs_two_body_residual < 1e-9
        assert np.allclose(result.genreith_residual, 0.0, atol=1e-9)

    def test_residual_stays_exact_along_a_path_with_live_stimulus(self):
        """With a stimulus the two-body residual stays zero while the Genreith residual equals S."""
        stimulus = 1.5
        params = EDMParameters(p_s=1e-12, p_p=0.03, p_b=0.03, alpha=0.0, stimulus=stimulus)
        result = simulate(BALANCED_STATE, params, (0.0, 10.0), t_eval=np.linspace(0.0, 10.0, 41))
        assert result.success
        assert result.max_abs_two_body_residual < 1e-9
        assert np.allclose(result.genreith_residual, stimulus)


class TestOverDetermination:
    """The four definitions of section 0.2 over-determine the three equations of motion."""

    def test_identity_closed_mode_applies_the_reduced_output_equation(self):
        """What IDENTITY_CLOSED guarantees is the reduced Y equation, nothing more."""
        params = constant_params(stimulus=3.0)
        p = params.at(0.0)
        got = derivatives(0.0, STATE, params, ClosureMode.IDENTITY_CLOSED)
        assert got[0] == pytest.approx(0.5 * ((p.p_b - p.p_s) * STATE[0] + p.stimulus))

    def test_p_p_cancels_out_of_the_joint_system(self):
        """The p_p identity plus the K_R equation imply a Y_dot that does not depend on p_p."""
        low = constant_params(p_p=0.01)
        high = constant_params(p_p=0.09)
        assert p_p_identity_implied_y_dot(0.0, STATE, low) == pytest.approx(
            p_p_identity_implied_y_dot(0.0, STATE, high)
        )

    def test_p_p_identity_forces_contraction_in_a_production_economy(self):
        """With K_R / Y < 1 every term in the implied Y_dot is positive, so Y_dot must be negative."""
        params = constant_params()
        assert investment_share(STATE) > 0.0  # a production economy, per section 0.5
        assert p_p_identity_implied_y_dot(0.0, STATE, params) < 0.0

    def test_p_p_identity_permits_growth_in_a_financial_economy(self):
        """With K_R > Y the investment share turns negative and the constraint permits growth."""
        financial_state = (100.0, 300.0, 500.0)
        params = constant_params()
        assert investment_share(financial_state) < 0.0  # a financial economy, per section 0.5
        assert p_p_identity_implied_y_dot(0.0, financial_state, params) > 0.0

    def test_identity_closed_mode_does_not_satisfy_the_p_p_definition(self):
        """Because p_p cancels, no closure mode can make the supplied p_p satisfy its definition."""
        params = constant_params(stimulus=3.0)
        residuals = identity_residuals(0.0, STATE, params, ClosureMode.IDENTITY_CLOSED)
        assert abs(residuals["p_p"]) > 1e-6


class TestIdentityResiduals:
    def test_as_written_mode_reports_a_non_zero_p_p_residual(self):
        """Under AS_WRITTEN the supplied p_p comes from data and need not match the simulated
        derivatives. The residual is a diagnostic, and it must be surfaced rather than hidden."""
        params = constant_params(stimulus=3.0)
        residuals = identity_residuals(0.0, STATE, params, ClosureMode.AS_WRITTEN)
        assert abs(residuals["p_p"]) > 1e-6

    def test_endogenous_r_has_zero_residual_by_construction(self):
        params = constant_params()
        assert identity_residuals(0.0, STATE, params)["r"] == 0.0


class TestLimitingCases:
    """Section 7 of the brief: with S = 0 and constant parameters the system must reduce to the
    analytic exponential solution the source derives."""

    def test_balanced_growth_reduces_to_the_exponential(self):
        p_p = 0.05
        params = EDMParameters(p_s=1e-12, p_p=p_p, p_b=p_p, alpha=0.0, stimulus=0.0)
        t_eval = np.linspace(0.0, 10.0, 101)
        result = simulate(BALANCED_STATE, params, (0.0, 10.0), t_eval=t_eval)
        assert result.success

        expected = balanced_growth_solution(BALANCED_STATE, p_p, t_eval)
        assert np.allclose(result.Y, expected["Y"], rtol=1e-6)
        assert np.allclose(result.K_R, expected["K_R"], rtol=1e-6)
        assert np.allclose(result.K_I, expected["K_I"], rtol=1e-6)
        assert np.allclose(result.K, expected["K"], rtol=1e-6)

    def test_balanced_growth_holds_the_investment_share_at_zero(self):
        """The ray is only balanced if r stays at zero, which requires p_b = p_p."""
        p_p = 0.05
        params = EDMParameters(p_s=1e-12, p_p=p_p, p_b=p_p, alpha=0.0, stimulus=0.0)
        result = simulate(BALANCED_STATE, params, (0.0, 10.0), t_eval=np.linspace(0.0, 10.0, 51))
        assert np.allclose(result.K_R / result.Y, 1.0, rtol=1e-8)

    def test_balanced_growth_solution_rejects_states_off_the_ray(self):
        with pytest.raises(ValueError, match="balanced growth requires"):
            balanced_growth_solution(STATE, 0.05, np.array([0.0, 1.0]))

    def test_zero_parameters_conserve_net_capital(self):
        params = EDMParameters(p_s=0.0, p_p=0.0, p_b=0.0, alpha=0.0, stimulus=0.0)
        # With r = 1 - K_R / Y non-zero, capital still moves between the two bodies, but the total
        # must be conserved because p_s Y + p_p K + S is zero.
        result = simulate(STATE, params, (0.0, 5.0), t_eval=np.linspace(0.0, 5.0, 51))
        assert result.success
        assert np.allclose(result.K, result.K[0], rtol=1e-8)


class TestFiniteTimeSingularity:
    """An arbitrary constant-parameter set does not produce a usable trajectory.

    This is a property of the model, and it is documented here because it constrains calibration:
    the parameter paths cannot be sampled independently of one another. The mechanism is the
    unbounded investment share r = 1 - K_R / Y. Once K_R crosses Y the exchange term r K_I changes
    sign, which accelerates the crossing it followed from, and the system reaches a singularity in
    finite time.
    """

    def test_plausible_constant_parameters_reach_a_singularity(self):
        params = constant_params(stimulus=2.0)
        result = simulate(STATE, params, (0.0, 20.0), warn_on_residual=False)
        assert not result.success
        assert "step size" in result.message
        # The algebra stays exact right up to the singularity, so the failure is dynamical rather
        # than an implementation error.
        assert result.max_abs_two_body_residual < 1e-9

    def test_the_investment_share_crosses_zero_before_the_singularity(self):
        params = constant_params(stimulus=2.0)
        result = simulate(STATE, params, (0.0, 20.0), warn_on_residual=False)
        ratio = result.K_R / result.Y
        assert ratio[0] < 1.0 < ratio[-1]


class TestSimulateGuards:
    @pytest.mark.parametrize("bad", [(0.0, 90.0, 210.0), (-1.0, 90.0, 210.0), (100.0, 0.0, 210.0)])
    def test_rejects_non_positive_initial_state(self, bad):
        with pytest.raises(ValueError, match="strictly positive"):
            simulate(bad, constant_params(), (0.0, 1.0))

    def test_rejects_wrong_length_initial_state(self):
        with pytest.raises(ValueError, match="three elements"):
            simulate((100.0, 90.0), constant_params(), (0.0, 1.0))

    def test_requires_r_path_when_r_is_exogenous(self):
        with pytest.raises(ValueError, match="r_path is required"):
            EDMParameters(p_s=0.2, p_p=0.04, p_b=0.03, alpha=0.5, endogenous_r=False)

    def test_exogenous_r_is_used_when_supplied(self):
        params = EDMParameters(
            p_s=0.22, p_p=0.045, p_b=0.035, alpha=0.6, endogenous_r=False, r_path=0.5
        )
        y, k_r, k_i = STATE
        p = params.at(0.0)
        expected = (1.0 - p.alpha) * p.p_s * y + p.p_p * k_r + 0.5 * k_i
        assert derivatives(0.0, STATE, params)[1] == pytest.approx(expected)


class TestSimulationResult:
    def test_derived_properties(self):
        params = constant_params()
        result = simulate(STATE, params, (0.0, 1.0), t_eval=np.array([0.0, 1.0]))
        assert result.K[0] == pytest.approx(STATE[1] + STATE[2])
        assert result.capital_saturation[0] == pytest.approx((STATE[1] + STATE[2]) / STATE[0])
        assert set(result.as_dict()) == {"t", "Y", "K_R", "K_I"}
