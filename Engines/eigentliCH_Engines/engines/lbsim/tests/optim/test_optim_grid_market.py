"""The grid (section 5), the in-sample scenarios of the market adapter (LBSIM-07), and the handshake types."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from optim_helpers import ACTIVE_SEED, SEED, SEED_1_2, sample_market
from lbsim.calibration import SEED_1_3
from lbsim.optim.grid import build
from lbsim.optim.market import sample_allocation
from lbsim.optim.types import ControlPath, ControlStep, PlanOutcome


# --- the grid ------------------------------------------------------------------------------------------------

def _variable(h: float, cap: float = 20.0):
    """1.1.0 and 1.2.0's grid: 0.5-year steps to 10 years, 1-year steps to the 20-year cap."""
    return build(h, SEED_1_2.optimiser.grid, "variable", cap=cap)


def test_1_3_0_solves_10_years_on_half_year_steps():
    """DECISIONS O-18 (owner, 29.09.2026): 500 iterations, a 10-year solve horizon."""
    o = SEED_1_3.optimiser
    assert (SEED_1_3.version, o.max_iter, o.max_solve_horizon_years) == ("1.3.0", 500, 10.0)
    g = build(27.0, o.grid, o.grid_rule, cap=o.max_solve_horizon_years)
    assert g.dts == (0.5,) * 20 and g.times[-1] == 10.0 and g.capped
    assert g.goal_node(27.0) == 20 and g.beyond(27.0) == 17.0 and g.beyond(3.0) == 0.0
    short = build(3.0, o.grid, o.grid_rule, cap=o.max_solve_horizon_years)
    assert short.dts == (0.5,) * 6 and not short.capped


def test_the_calibration_cap_and_the_run_cap_the_tighter_holds():
    from optim_helpers import sample_problem
    from lbsim.optim import run
    import dataclasses

    p13 = sample_problem()                                   # 1.3.0: the calibration says 10
    assert run.the_grid(p13).times[-1] == 10.0
    assert run.the_grid(dataclasses.replace(p13, max_solve_horizon_years=5.0)).times[-1] == 5.0
    p12 = sample_problem(calibration=SEED_1_2)               # 1.2.0: no calibration cap, the run's 20
    assert run.the_grid(p12).times[-1] == 20.0


def test_a_20_year_horizon_is_30_steps():
    g = _variable(20.0)
    assert g.dts == (0.5,) * 20 + (1.0,) * 10
    assert g.times[-1] == 20.0 and g.K == 30 and not g.capped


def test_a_40_year_horizon_is_capped_at_20_years():
    g = _variable(40.0)
    assert g.K == 30 and g.solved_years == 20.0 and g.total_years == 40.0 and g.capped
    assert g.beyond(27.0) == 7.0 and g.beyond(12.0) == 0.0
    assert g.goal_node(27.0) == 30


def test_the_config_cap_can_be_lower_than_the_grid():
    g = _variable(40.0, cap=15.0)
    assert g.times[-1] == 15.0 and g.K == 25


@pytest.mark.parametrize("h, K, end", [(3.0, 6, 3.0), (7.3, 15, 7.5), (7.2, 14, 7.0), (10.0, 20, 10.0),
                                       (12.4, 22, 12.0), (12.6, 23, 13.0), (0.2, 1, 0.5)])
def test_the_variable_grid_ends_at_the_nearest_node(h, K, end):
    g = _variable(h)
    assert g.K == K and g.times[-1] == pytest.approx(end)


def test_goals_sit_at_their_nearest_node():
    g = _variable(20.0)
    assert g.goal_node(3.0) == 6 and g.times[6] == 3.0
    assert g.goal_node(15.0) == 25 and g.times[25] == 15.0
    assert g.goal_node(0.1) == 1
    assert g.times[g.goal_node(10.4)] == 10.0


@pytest.mark.parametrize("h, dt, K", [(5.0, 0.5, 10), (10.0, 0.5, 20), (12.0, 1.0, 12), (7.3, 0.5, 15)])
def test_the_draft_rule_is_one_step_for_the_whole_horizon(h, dt, K):
    g = build(h, SEED.optimiser.grid, SEED.optimiser.grid_rule)
    assert set(g.dts) == {dt} and g.K == K and not g.capped
    assert g.goal_node(h) == max(1, min(K, int(round(h / dt))))
    assert g.beyond(h + 5) == 0.0, "the draft rule has no cap and so no terminal requirement"


# --- the scenarios ---------------------------------------------------------------------------------------------

def test_the_scenarios_are_reproducible_and_seeded():
    m, dts = sample_market(), (0.5,) * 20 + (1.0,) * 10
    a = sample_allocation(m, ACTIVE_SEED.property, dts, 14, 7)
    b = sample_allocation(m, ACTIVE_SEED.property, dts, 14, 7)
    c = sample_allocation(m, ACTIVE_SEED.property, dts, 14, 1007)
    assert np.array_equal(a.r, b.r) and np.array_equal(a.growth, b.growth)
    assert not np.array_equal(a.state, c.state)


def test_one_state_per_simulated_year():
    m, dts = sample_market(), (0.5,) * 20 + (1.0,) * 10
    s = sample_allocation(m, ACTIVE_SEED.property, dts, 50, 3)
    for k in range(0, 20, 2):
        assert np.array_equal(s.state[:, k], s.state[:, k + 1]), "the two half-years of a year share a state"
    r_s = np.asarray(m.log_returns)
    assert np.allclose(s.r, r_s[s.state])
    assert s.level.shape == (50, 31) and np.all(s.level[:, 0] == 1.0)
    assert np.allclose(s.level[:, 1:], np.exp(np.cumsum(s.infl, axis=1)))


def test_the_draws_follow_the_year_distribution():
    m = sample_market()
    s = sample_allocation(m, ACTIVE_SEED.property, (1.0,), 40_000, 11)
    freq = np.bincount(s.state[:, 0], minlength=25) / 40_000
    assert np.max(np.abs(freq - np.asarray(m.state_distribution[0]))) < 0.01


def test_property_growth_follows_the_calibration():
    m = sample_market()
    prop = ACTIVE_SEED.property
    s = sample_allocation(m, prop, (1.0,) * 5, 20_000, 5)
    pi = np.asarray(m.log_inflation)[s.state]
    det = prop.nominal_log_growth + prop.inflation_beta * (pi - prop.inflation_anchor_log) - 0.5 * prop.sigma ** 2
    resid = s.growth - det
    assert abs(resid.mean()) < 0.01 and abs(resid.std() - prop.sigma) < 0.005


# --- the handshake -----------------------------------------------------------------------------------------------

def test_importing_the_optimiser_package_does_not_load_casadi():
    """LBSIM-03: B2's API process imports ``lbsim.optim`` for its types and never loads casadi."""
    code = ("import sys; import lbsim.optim, lbsim.optim.types, lbsim.optim.grid, lbsim.optim.market, "
            "lbsim.optim.goals; from lbsim.optim import solve, PlanProblem, PlanOutcome, ControlPath; "
            "print('casadi' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_a_failed_outcome_carries_no_figures_and_a_succeeded_one_does():
    with pytest.raises(ValueError):
        PlanOutcome(status="failed", failure_kind=None)
    with pytest.raises(ValueError):
        PlanOutcome(status="succeeded")
    assert PlanOutcome(status="failed", failure_kind="timed_out").result is None


def test_a_control_path_answers_by_time_and_holds_the_last_step():
    steps = (ControlStep(0.0, 0.5, {"C": 1.0}), ControlStep(0.5, 0.5, {"C": 2.0}), ControlStep(1.0, 1.0, {"C": 3.0}))
    path = ControlPath(steps=steps, horizon_years=5.0, money_basis="today_indexed")
    assert [path.at(t)["C"] for t in (0.0, 0.49, 0.5, 1.2, 1.99, 2.0, 4.5)] == [1.0, 1.0, 2.0, 3.0, 3.0, 3.0, 3.0]
