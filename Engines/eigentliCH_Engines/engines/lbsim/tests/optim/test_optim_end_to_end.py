"""``solve`` end to end on B1's sample household (slow: real IPOPT solves).

- a plan under calibration 1.0.0 (the draft's market) and under the active one (the allocation market), with the
  out-of-sample chance from the injected Monte Carlo (a stand-in; the engine's is B2's);
- an unfundable goal is determined on its draw and not redrawn (M79);
- the 20-year case: the sample's 27-year horizon capped at 20 years (30 steps), its retirement goal beyond the
  cap as the zero-return terminal requirement, inside the 120-minute budget;
- the receding-horizon loop (the draft's ``test_mpc``), briefly.
"""

from __future__ import annotations

import dataclasses
import json
import time

import pytest

from optim_helpers import (ACTIVE_SEED, OPTIM_GOLDEN, SEED, StandInSimulate, never, no_deadline, quiet,
                           sample_problem, with_optimiser)
from lbsim.optim import solve

pytestmark = pytest.mark.slow

BUDGET_S = 120 * 60


def _check_plan(out, problem, sim):
    assert out.status == "succeeded", (out.failure_kind, out.error, out.diagnostics)
    r = out.result
    assert r.outcome == "solved"
    assert len(sim.calls) == 1 and r.chance.out_of_sample == sim.chance
    assert r.chance.seed_out == problem.seed + 500_000
    assert r.seeds_used[-1] == problem.seed + 500_000
    a = r.action_now
    assert 0.0 <= a.work_share <= 0.70 + 1e-6 and a.rest_hours_per_week >= 5.0 - 1e-4
    assert a.consumption_chf_per_year >= 1_000.0 - 1e-6
    assert 0.0 <= r.chance.in_sample <= 1.0
    return r


def test_the_draft_market_under_1_0_0_plans_or_redraws_then_reports_nothing():
    """Under 1.0.0 the draft's market and tilt. The draft itself certifies few households (its M87: publishable
    and meeting the confidence in 0 of 24 cells), and on the sample household the three draws come back
    undetermined. So this holds the rule either way: a plan with the injected out-of-sample chance, or a pathology
    redrawn at ``seed + 1000 k`` three times and then a failed run with no figures and no simulation."""
    problem = sample_problem(calibration=SEED, horizon=3.0, extra=False)
    sim = StandInSimulate()
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    if out.status == "succeeded":
        r = _check_plan(out, problem, sim)
        assert r.control_path.money_basis == "nominal"
        assert all(-1e-6 <= s.controls["theta"] <= 1.0 + 1e-6 for s in r.control_path.steps), "the draft's tilt"
    else:
        assert out.failure_kind == "solver" and out.result is None and not sim.calls
        assert out.diagnostics["outcome"] == "undetermined"
        assert out.seeds_used == tuple(problem.seed + 1_000 * k for k in range(SEED.optimiser.seed_retries))


def test_a_plan_under_the_active_calibration_on_the_allocation_market():
    """The allocation market certifies a plan for the sample household. Solved at the draft's test budget of
    3000 IPOPT iterations (``test_optim``'s ``solve_fi`` default): at the calibration's 400 (the draft's
    ``run_case``) the phase-2 solves reach a funded point and stop at the limit on every draw (measured
    29.09.2026: they need 2000 to 2700 iterations), which the next test holds."""
    problem = sample_problem(horizon=3.0, extra=False)
    problem = dataclasses.replace(problem, calibration=with_optimiser(ACTIVE_SEED, max_iter=3000, seed_retries=1))
    sim = StandInSimulate()
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    r = _check_plan(out, problem, sim)
    assert r.control_path.money_basis == "today_indexed"
    assert all(abs(s.controls["theta"] - 1.0) < 1e-6 for s in r.control_path.steps), "theta is fixed at 1"
    assert r.solver.grid == (0.5,) * 6 and r.horizon.beyond_cap_rule is None
    assert out.diagnostics["in_sample_cvar"] <= 1e-3 + 1e-6, "the certified plan meets the CVaR bound"


def test_at_the_calibrated_400_iterations_the_run_plans_or_reports_nothing():
    """The active calibration as shipped (``max_iter`` 400): a certified plan, or three draws (``seed + 1000 k``) and a failed run with no
    figures. On the sample household (29.09.2026) it is the second."""
    problem = sample_problem(horizon=3.0, extra=False)
    sim = StandInSimulate()
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    if out.status == "succeeded":
        _check_plan(out, problem, sim)
    else:
        assert out.failure_kind == "solver" and out.result is None and not sim.calls
        assert out.seeds_used == tuple(problem.seed + 1_000 * k for k in range(ACTIVE_SEED.optimiser.seed_retries))


def test_an_unfundable_goal_is_determined_on_its_draw_and_not_redrawn():
    """M79: redraw exists for solver pathology; a goal the model cannot fund is not shopped across draws."""
    problem = sample_problem(horizon=3.0, extra=False, goal_target=5_000_000.0)
    sim = StandInSimulate(chance=0.0)
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    assert out.status == "succeeded", (out.failure_kind, out.error, out.diagnostics)
    r = out.result
    assert r.outcome == "goal_not_fundable"
    assert r.seeds_used == (problem.seed, problem.seed + 500_000), "exactly one in-sample draw, then the OOS seed"
    assert out.diagnostics["seed_attempt"] == 0 and out.diagnostics["restore_converged"] is True
    assert 0.0 < r.reachable.amount_chf < 5_000_000.0 and r.reachable.at_confidence == pytest.approx(0.90)
    assert r.chance.out_of_sample == 0.0


def test_the_20_year_case_finishes_inside_the_budget():
    """Section 5: 0.5-year steps to 10 years, 1-year steps to 20, the cap at 20; a goal at 27 years is the
    zero-return terminal requirement. Measured wall clock written to ``golden/optim/twenty_year_run.json``."""
    problem = sample_problem()
    assert problem.horizon_years == 27.0 and problem.extra_goals[0].horizon_years == 27.0
    sim, events = StandInSimulate(), []
    t0 = time.monotonic()
    out = solve(problem, simulate=sim, deadline=time.monotonic() + BUDGET_S, should_cancel=never,
                progress=events.append)
    wall = time.monotonic() - t0
    record = {"wall_clock_s": round(wall, 1), "status": out.status, "failure_kind": out.failure_kind,
              "solves": out.diagnostics.get("solves"), "grid": out.diagnostics.get("grid"),
              "outcome": out.result.outcome if out.result else None,
              "measured_by": "tests/optim/test_optim_end_to_end.py::test_the_20_year_case_finishes_inside_the_budget"}
    (OPTIM_GOLDEN / "twenty_year_run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    assert wall < BUDGET_S
    assert out.failure_kind != "timed_out", "the 20-year case must finish inside the 120-minute budget"
    assert out.diagnostics["grid"] == [0.5] * 20 + [1.0] * 10
    if out.result is not None:
        assert out.result.horizon.solved_years == 20.0 and out.result.horizon.total_years == 27.0
        assert out.result.horizon.beyond_cap_rule == "zero_return_terminal"
        assert len(out.result.control_path.steps) == 30


def test_the_receding_horizon_loop_emits_admissible_actions():
    """The draft's ``test_mpc``: three quarterly re-solves toward a deadline nine months out."""
    from lbsim.model.params import Params
    from lbsim.model.state import State
    from lbsim.optim.mpc import run_mpc
    from lbsim.optim.spec import GoalSpec

    x0 = State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)
    p = Params()
    goal = GoalSpec(kind="fi", horizon_years=0.75, epsilon=0.10, params=dict(G=p.G, swr=p.swr, h_res=p.h_res))
    out = run_mpc(x0, goal, start_age=45.0, target_age=45.75, params=p, step_years=0.25, M_opt=12, seed=1)
    assert [round(o.age, 2) for o in out] == [45.0, 45.25, 45.5]
    for o in out:
        u = o.action
        taus = [u.tau_Y, u.tau_E, u.tau_N, u.tau_H]
        assert all(t >= -1e-2 for t in taus) and sum(taus) <= 1.01 and -1e-2 <= u.theta <= 1.01
        assert 0.0 <= o.p_goal <= 1.0 and o.lever
        assert o.exchange_rate.winner in ("networking", "overtime", "undetermined")
