"""``lbsim.optim.solve`` around the NLP: the clock, cancelling, progress, the seeds, the redraw rule (M79), the
out-of-sample chance from the injected Monte Carlo, and no figure from a run that did not finish.

These run in the default lane: the ones that touch IPOPT stop it within seconds, the rest stub the solver.
"""

from __future__ import annotations

import time

import pytest

from optim_helpers import ACTIVE_SEED, SEED, StandInSimulate, never, no_deadline, quiet, sample_problem
from lbsim.optim import problem as prob
from lbsim.optim import run
from lbsim.optim import solve
from lbsim.optim.problem import Costates, ExchangeRate, SolveResult

PROGRESS_KEYS = {"phase", "start", "of", "seed_attempt", "elapsed_s"}


def _no_figures(out, kind: str, sim: StandInSimulate) -> None:
    assert out.status == "failed" and out.failure_kind == kind
    assert out.result is None, "no figure may leave a run that did not finish"
    assert not sim.calls, "the out-of-sample Monte Carlo must not run for a stopped solve"
    assert out.error and out.error[0].isupper() and out.error.endswith(".")


# --- the clock ----------------------------------------------------------------------------------------------------

def test_a_deadline_already_passed_times_out_before_any_solve():
    sim, events = StandInSimulate(), []
    out = solve(sample_problem(horizon=3.0, extra=False), simulate=sim, deadline=time.monotonic() - 1.0,
                should_cancel=never, progress=events.append)
    _no_figures(out, "timed_out", sim)
    assert events == []


def test_a_deadline_inside_a_solve_is_enforced_by_ipopt_and_gives_timed_out():
    """``ipopt.max_wall_time`` is the time left: a solve that cannot finish in it is stopped, and the run is
    ``timed_out`` with no figures."""
    sim, events = StandInSimulate(), []
    problem = sample_problem(goal_years=10.0, horizon=10.0, extra=False)
    t0 = time.monotonic()
    out = solve(problem, simulate=sim, deadline=time.monotonic() + 1.0, should_cancel=never,
                progress=events.append)
    _no_figures(out, "timed_out", sim)
    assert out.seeds_used == (problem.seed,), "the seed the stopped solve ran on is recorded"
    assert time.monotonic() - t0 < 60.0, "the budget must stop the run, not the end of the solve"
    assert events and set(events[0]) == PROGRESS_KEYS and events[0]["phase"] == "restore"


# --- cancelling and progress -------------------------------------------------------------------------------------

def test_a_cancel_before_the_start_gives_cancelled():
    sim = StandInSimulate()
    out = solve(sample_problem(horizon=3.0, extra=False), simulate=sim, deadline=no_deadline(),
                should_cancel=lambda: True, progress=quiet)
    _no_figures(out, "cancelled", sim)


def test_a_cancel_is_honoured_between_ipopt_solves():
    """A newer sheet cancels a running plan at the next checkpoint: after the solve in progress, before the
    next one starts."""
    sim, events, flag = StandInSimulate(), [], {"cancel": False}

    def progress(e):
        events.append(e)
        flag["cancel"] = True          # asked for while the first solve runs

    out = solve(sample_problem(horizon=3.0, extra=False), simulate=sim, deadline=no_deadline(),
                should_cancel=lambda: flag["cancel"], progress=progress)
    _no_figures(out, "cancelled", sim)
    assert len(events) == 1 and set(events[0]) == PROGRESS_KEYS
    assert events[0] == {**events[0], "phase": "restore", "start": 1, "of": 2, "seed_attempt": 0}


def test_an_impossible_problem_is_a_failed_run_with_a_sentence():
    import dataclasses
    p = sample_problem(horizon=3.0, extra=False)
    bad = dataclasses.replace(p, goal=dataclasses.replace(p.goal, target_nominal_chf=None, target_real_chf=None))
    sim = StandInSimulate()
    out = solve(bad, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    _no_figures(out, "solver", sim)


# --- the redraw rule (M79) ---------------------------------------------------------------------------------------

def _canned(outcome: str, *, K: int, success: bool, cvar: float = 0.0, s_star: float = -0.2) -> SolveResult:
    u = dict(tau_Y=0.45, tau_E=0.02, tau_N=0.03, tau_H=0.20, C=90_000.0, m_E=1_000.0, m_N=500.0, p_A=0.0,
             theta=1.0)
    return SolveResult(u0=dict(u), costates=Costates(1e-5, 0.4, 0.3, 0.5),
                       exchange_rate=ExchangeRate("g", 0.2, 0.1), p_fi_insample=0.93, cvar_shortfall=cvar,
                       objective=-1.0, success=success,
                       stats={"outcome": outcome, "return_status": "Solve_Succeeded", "iter_count": 42,
                              "s_star": s_star, "cvar_bound": 1e-3, "restore_converged": True},
                       u_path=[dict(u) for _ in range(K)], dts=(0.5,) * K)


@pytest.mark.parametrize("outcome, calls", [("undetermined", 3), ("goal_not_fundable", 1), ("plan", 1)])
def test_redraws_only_for_solver_pathology_never_for_an_unfundable_goal(monkeypatch, outcome, calls):
    seen = []

    def fake_once(x0, goal, *, seed, seed_attempt, **kw):
        seen.append((seed, seed_attempt))
        return _canned(outcome, K=6, success=outcome == "plan")

    monkeypatch.setattr(prob, "_solve_case_once", fake_once)
    res = prob.solve_case(None, None, grid=None, seed=77, seed_retries=3)
    assert seen == [(77 + 1_000 * k, k) for k in range(calls)]
    assert res.stats["seeds_tried"] == [s for s, _ in seen]


# --- the out-of-sample chance comes from the injected Monte Carlo ----------------------------------------------

def _stub_solve_case(monkeypatch, outcome: str, **kw):
    problem = sample_problem(horizon=3.0, extra=False)
    K = run.the_grid(problem).K
    captured = {}

    def fake(x0, goal, **kwargs):
        captured.update(kwargs)
        res = _canned(outcome, K=K, success=outcome == "plan", **kw)
        res.stats.update(seed=kwargs["seed"], seed_attempt=0, seeds_tried=[kwargs["seed"]])
        return res

    monkeypatch.setattr(run, "solve_case", fake)
    return problem, captured


def test_the_out_of_sample_chance_is_the_injected_simulation(monkeypatch):
    problem, captured = _stub_solve_case(monkeypatch, "plan")
    sim = StandInSimulate(chance=0.8765, shortfall=4321.0)
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    assert out.status == "succeeded" and out.failure_kind is None
    r = out.result
    assert len(sim.calls) == 1
    call = sim.calls[0]
    assert call["problem"] is problem
    assert call["seed"] == problem.seed + 500_000 == r.chance.seed_out
    assert call["n_paths"] == ACTIVE_SEED.optimiser.M_eval == r.chance.n_out_of_sample
    assert r.chance.out_of_sample == 0.8765 and r.shortfall_cvar_chf == 4321.0
    assert r.chance.in_sample == 0.93
    assert r.seeds_used == (problem.seed, problem.seed + 500_000)
    # The solver was driven with the calibration's settings and the in-sample seed.
    opt = ACTIVE_SEED.optimiser
    assert (captured["M"], captured["n_starts"], captured["restore_starts"], captured["max_iter"],
            captured["seed_retries"], captured["cvar_tol"], captured["seed"], captured["seed_step"]) == (
        opt.M_opt, opt.n_starts, opt.restore_starts, opt.max_iter, opt.seed_retries, opt.cvar_tol, problem.seed,
        1_000)
    assert captured["market"].kind == "allocation"
    # The controls handed to the Monte Carlo are the plan's, step by step on the grid, in today's francs.
    path = call["controls"]
    assert path is r.control_path and path.money_basis == "today_indexed"
    assert [s.t_years for s in path.steps] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    a = r.action_now
    assert a.learning_hours_per_week == pytest.approx(2.0) and a.rest_hours_per_week == pytest.approx(20.0)
    assert a.consumption_chf_per_year == 90_000.0 and a.work_share == 0.45
    assert r.outcome == "solved" and r.reachable is None
    assert r.horizon.solved_years == 3.0 and r.horizon.beyond_cap_rule is None


def test_a_n_out_of_sample_in_the_problem_is_used(monkeypatch):
    import dataclasses
    problem, _ = _stub_solve_case(monkeypatch, "plan")
    sim = StandInSimulate()
    solve(dataclasses.replace(problem, n_out_of_sample=2000), simulate=sim, deadline=no_deadline(),
          should_cancel=never, progress=quiet)
    assert sim.calls[0]["n_paths"] == 2000


def test_an_undetermined_solve_is_a_failed_run_without_figures(monkeypatch):
    problem, _ = _stub_solve_case(monkeypatch, "undetermined")
    sim = StandInSimulate()
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    _no_figures(out, "solver", sim)
    assert out.diagnostics["outcome"] == "undetermined"


def test_an_unfundable_goal_states_what_is_reachable(monkeypatch):
    problem, _ = _stub_solve_case(monkeypatch, "goal_not_fundable", s_star=0.25)
    sim = StandInSimulate(chance=0.31)
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    r = out.result
    assert r.outcome == "goal_not_fundable" and r.chance.out_of_sample == 0.31
    target = problem.goal.target_real_chf        # the sample's home goal is stated in today's francs
    assert r.reachable.amount_chf == pytest.approx(0.75 * target)
    assert r.reachable.at_confidence == pytest.approx(0.90)


def test_the_draft_market_under_1_0_0_hands_over_nominal_controls(monkeypatch):
    problem = sample_problem(calibration=SEED, horizon=3.0, extra=False)
    K = run.the_grid(problem).K

    def fake(x0, goal, **kwargs):
        res = _canned("plan", K=K, success=True)
        res.stats.update(seed=kwargs["seed"], seed_attempt=0, seeds_tried=[kwargs["seed"]])
        assert kwargs["market"].kind == "draft"
        return res

    monkeypatch.setattr(run, "solve_case", fake)
    sim = StandInSimulate()
    out = solve(problem, simulate=sim, deadline=no_deadline(), should_cancel=never, progress=quiet)
    assert out.result.control_path.money_basis == "nominal"
