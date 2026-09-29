"""Feasibility layer (spec §16.4 step 3): verify MC probabilities move sensibly
with controls and state, and that the CVaR surrogate is conservative."""

import numpy as np
import pytest

from personal_alm.goals.feasibility import (
    cvar,
    cvar_feasible,
    cvar_shortfall,
    feasibility,
)
from personal_alm.goals.goals import company_goal, fi_goal, home_goal, retirement_goal
from personal_alm.model.controls import Control
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.sim.montecarlo import constant_policy

P = Params()


def _nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


def _policy(C: float):
    return constant_policy(Control(tau_Y=0.45, tau_E=0.05, tau_N=0.10, tau_H=0.20,
                                   C=C, m_E=5_000, m_N=10_000, p_A=60_000, theta=0.40))


def _fi():
    return fi_goal(G=P.G, swr=P.swr, h_res=P.h_res, horizon_years=5.0, epsilon=0.10)


# --- MC probability moves sensibly ------------------------------------------------

def test_pfi_decreases_with_consumption():
    """Spending more lowers drawable-wealth accumulation, so P(FI) falls."""
    lo = feasibility(_nicolas_45(), _policy(60_000), _fi(), P, n_scenarios=400, seed=42)
    hi = feasibility(_nicolas_45(), _policy(150_000), _fi(), P, n_scenarios=400, seed=42)
    assert lo.p_hat > hi.p_hat
    assert 0.0 < hi.p_hat < lo.p_hat < 1.0   # both in the interior


def test_pfi_increases_with_liquid_wealth():
    goal = _fi()
    probs = []
    for WL in (0.3e6, 0.6e6, 1.0e6, 1.5e6):
        x = State.individual(W_L=WL, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)
        probs.append(feasibility(x, _policy(120_000), goal, P, n_scenarios=400, seed=42).p_hat)
    assert all(b > a for a, b in zip(probs, probs[1:]))   # strictly increasing


def test_standard_error_shrinks_like_sqrt_m():
    r100 = feasibility(_nicolas_45(), _policy(120_000), _fi(), P, n_scenarios=100, seed=7)
    r1600 = feasibility(_nicolas_45(), _policy(120_000), _fi(), P, n_scenarios=1600, seed=7)
    # SE ~ 1/√M: 16× the scenarios ⇒ roughly 4× tighter.
    assert r1600.se < r100.se / 3.0


def test_common_random_numbers_are_reproducible():
    a = feasibility(_nicolas_45(), _policy(120_000), _fi(), P, n_scenarios=200, seed=99)
    b = feasibility(_nicolas_45(), _policy(120_000), _fi(), P, n_scenarios=200, seed=99)
    assert np.array_equal(a.slacks, b.slacks)   # identical shocks under the same seed


# --- CVaR surrogate ---------------------------------------------------------------

def test_cvar_is_worst_tail_average():
    losses = np.arange(1.0, 11.0)          # 1..10
    # Worst 20% = the two largest = {10, 9} → mean 9.5.
    assert cvar(losses, epsilon=0.2) == pytest.approx(9.5)
    # ε → whole sample is just the mean.
    assert cvar(losses, epsilon=1.0) == pytest.approx(losses.mean())


def test_cvar_certifies_feasibility_conservatively():
    """A clearly-funded state: CVaR_{1−ε}[−g] ≤ 0, and it implies P(FI) ≥ 1−ε."""
    rich = State.individual(W_L=2.0e6, W_R=5.0e6, D=1.0e6, E=0.90, N=0.90, H=0.75, W_res=1.0e6)
    r = feasibility(rich, _policy(120_000), _fi(), P, n_scenarios=1000, seed=42)
    assert cvar_shortfall(r.slacks, epsilon=0.10) <= 0.0
    assert cvar_feasible(r, epsilon=0.10)
    # Conservative direction: the certificate implies the frequency bound.
    assert r.meets(epsilon=0.10)


def test_cvar_flags_infeasible_marginal_case():
    """Nicolas's actual state is marginal: P(FI) < 0.90, and CVaR > 0 flags it —
    the quantitative version of the book's 'plan against ~52–53, not 50'."""
    r = feasibility(_nicolas_45(), _policy(120_000), _fi(), P, n_scenarios=1000, seed=42)
    assert not r.meets(epsilon=0.10)
    assert cvar_shortfall(r.slacks, epsilon=0.10) > 0.0


# --- The other goal archetypes (region sanity) -----------------------------------

def _u():
    return Control(tau_Y=0.5, tau_E=0.1, tau_N=0.2, tau_H=0.2,
                   C=60_000, m_E=2_000, m_N=2_000, p_A=0, theta=0.4)


def test_company_goal_is_the_binding_intersection():
    goal = company_goal(B_buffer=200_000, N_min=0.6, E_min=0.7, horizon_years=3.0)
    # Expertise clears, buffer clears, but network lags → slack < 0 (network binds).
    lagging = State.individual(W_L=300_000, W_R=0, D=0, E=0.85, N=0.40, H=0.8)
    assert goal.slack(lagging, P, _u()) < 0
    ready = State.individual(W_L=300_000, W_R=0, D=0, E=0.85, N=0.75, H=0.8)
    assert goal.slack(ready, P, _u()) > 0


def test_home_goal_serviceability_can_bind_over_deposit():
    goal = home_goal(price=400_000, horizon_years=8.0)
    # Deposit met (W_L ≥ 80k) but income too low to service → slack < 0.
    deposit_ok_income_low = State.individual(W_L=90_000, W_R=0, D=0, E=0.2, N=0.1, H=0.9)
    low_earn = Control(tau_Y=0.2, tau_E=0.2, tau_N=0.1, tau_H=0.2,
                       C=20_000, m_E=0, m_N=0, p_A=0, theta=0.3)
    assert goal.slack(deposit_ok_income_low, P, low_earn) < 0


def test_retirement_funding_ratio_sign():
    goal = retirement_goal(G_ret=80_000, years_in_retirement=25.0, horizon_years=7.0)
    underfunded = State.individual(W_L=200_000, W_R=300_000, D=0, E=0.8, N=0.7, H=0.7)
    wellfunded = State.individual(W_L=2.5e6, W_R=1.0e6, D=0, E=0.8, N=0.7, H=0.7)
    assert goal.slack(underfunded, P, _u()) < 0
    assert goal.slack(wellfunded, P, _u()) > 0
