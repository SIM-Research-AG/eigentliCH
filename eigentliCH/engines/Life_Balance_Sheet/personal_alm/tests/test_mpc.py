"""MPC runtime (spec Â§16.4 step 5): end-to-end receding-horizon loop, and
confirmation that re-planning recovers from an injected shock."""

import pytest

from personal_alm.model.controls import Control
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.optim.mpc import apply_control, run_mpc

P = Params()


def _nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


def _admissible(u: Control, atol: float = 1e-2) -> bool:
    taus = [u.tau_Y, u.tau_E, u.tau_N, u.tau_H]
    return (all(t >= -atol for t in taus)
            and sum(taus) <= 1.0 + atol
            and all(getattr(u, k) >= -1.0 for k in ("C", "m_E", "m_N", "p_A"))
            and -atol <= u.theta <= 1.0 + atol)


def test_adherence_filter_is_identity():
    """SEAM 5: the applied action equals the recommendation exactly (v1)."""
    named = dict(tau_Y=0.4, tau_E=0.1, tau_N=0.1, tau_H=0.2,
                 C=90_000, m_E=1_000, m_N=2_000, p_A=5_000, theta=0.3)
    u = apply_control(named)
    assert isinstance(u, Control)
    assert (u.tau_Y, u.C, u.theta) == (0.4, 90_000, 0.3)


@pytest.mark.slow
def test_mpc_runs_and_emits_admissible_actions():
    out = run_mpc(_nicolas_45(), start_age=45.0, target_age=45.75, params=P,
                  step_years=0.25, epsilon=0.10, M_opt=12, M_eval=200, seed=1)
    assert len(out) == 3
    for o in out:
        assert _admissible(o.action)
        assert 0.0 <= o.p_fi_oos <= 1.0
        assert o.exchange_rate.winner in ("networking", "overtime")
        assert o.lever  # a plain-language lever string is always emitted


@pytest.mark.slow
def test_horizon_recedes_toward_deadline():
    """Ages advance by the re-solve cadence up to (not past) the deadline."""
    out = run_mpc(_nicolas_45(), start_age=45.0, target_age=45.75, params=P,
                  step_years=0.25, epsilon=0.10, M_opt=12, M_eval=200, seed=1)
    ages = [round(o.age, 2) for o in out]
    assert ages == [45.0, 45.25, 45.5]


@pytest.mark.slow
def test_replanning_recovers_from_a_shock():
    """A market crash halving liquid wealth should make the next re-solve cut
    consumption to protect the goal, after which wealth rebuilds."""
    def crash(state: State) -> State:
        s = state.copy()
        s.wealth.W_L *= 0.5
        return s

    # A longer horizon with more restarts leaves a feasible plan post-crash, so the
    # loop genuinely recovers rather than falling back to a floored action.
    out = run_mpc(_nicolas_45(), start_age=45.0, target_age=49.0, params=P,
                  step_years=0.5, epsilon=0.10, M_opt=12, M_eval=200, seed=1,
                  n_starts=3, interventions={1: crash})

    # The shock lands: liquid wealth drops between the observing period and the next.
    assert out[2].state.wealth.W_L < out[1].state.wealth.W_L

    # Recovery: the loop re-plans and rebuilds liquid wealth over later periods.
    assert out[-1].state.wealth.W_L > out[2].state.wealth.W_L

    # Every applied action stays admissible throughout (the projection safeguard holds).
    for o in out:
        u = o.action
        taus = [u.tau_Y, u.tau_E, u.tau_N, u.tau_H]
        assert all(t >= -1e-2 for t in taus) and sum(taus) <= 1.01
        assert -1e-2 <= u.theta <= 1.01
