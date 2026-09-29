"""Stand-in solvers with the signature of ``lbsim.optim.solve`` (the handshake with agent C), for the harness tests.

They build their answer from C's own dataclasses (``lbsim.optim.types``, no casadi), so the worker is tested against
the real field names. ``quick`` returns a plan from constant controls and lbsim's Monte Carlo; ``sleepy`` works until
it is told to stop or its deadline passes, as a long IPOPT run would, checking ``should_cancel`` between "solves".
"""

from __future__ import annotations

import time

from lbsim.optim import types as T


def _path(problem, controls: dict) -> "T.ControlPath":
    cap = min(float(problem.horizon_years), float(problem.max_solve_horizon_years))
    steps, t = [], 0.0
    while t < cap - 1e-9:
        dt = 0.5 if t < 10 - 1e-9 else 1.0
        dt = min(dt, cap - t)
        steps.append(T.ControlStep(t_years=t, dt_years=dt, controls=dict(controls)))
        t += dt
    return T.ControlPath(steps=tuple(steps), horizon_years=float(problem.horizon_years), money_basis="today_indexed")


def constant_controls(problem) -> dict:
    raw = problem.submission.get("raw") or {}
    return {"tau_Y": 0.42, "tau_E": 0.0, "tau_N": 0.02, "tau_H": 0.2, "C": float(raw.get("spend_now") or 80_000.0),
            "m_E": 0.0, "m_N": 0.0, "p_A": 0.0, "theta": 1.0}


def quick(problem, *, simulate, deadline, should_cancel, progress):
    progress({"phase": "restore", "start": 1, "of": 2, "seed_attempt": 0, "elapsed_s": 0.0})
    if should_cancel():
        return T.PlanOutcome(status="failed", failure_kind="cancelled", error="Cancelled.")
    path = _path(problem, constant_controls(problem))
    seed_out = int(problem.seed) + 500_000
    n = int(problem.n_out_of_sample or problem.calibration.optimiser.M_eval)
    sim = simulate(problem, path, n, seed_out)
    solved = path.steps[-1].t_years + path.steps[-1].dt_years
    u = path.steps[0].controls
    result = T.PlanResult(
        outcome="solved", goal_id=problem.goal.goal_id, goal_kind=problem.goal.kind,
        confidence=problem.goal.confidence, extra_goals=tuple(g.goal_id for g in problem.extra_goals),
        action_now=T.ActionNow(work_share=u["tau_Y"], learning_hours_per_week=100 * u["tau_E"],
                               network_hours_per_week=100 * u["tau_N"], rest_hours_per_week=100 * u["tau_H"],
                               consumption_chf_per_year=u["C"], saving_chf_per_year=10_000.0,
                               education_spend_chf_per_year=u["m_E"], network_spend_chf_per_year=u["m_N"],
                               amortisation_chf_per_year=u["p_A"]),
        chance=T.PlanChance(in_sample=sim["chance"], out_of_sample=sim["chance"], n_out_of_sample=n,
                            seed_out=seed_out),
        shortfall_cvar_chf=float(sim["shortfall_cvar_chf"]), reachable=None,
        exchange_rate=T.ExchangeRate(winner="undetermined", ratio=None, dominant=None),
        costates=T.Costates(W=1e-5, E=0.4, N=0.3, H=0.2), control_path=path,
        horizon=T.PlanHorizon(solved_years=solved, total_years=float(problem.horizon_years),
                              beyond_cap_rule="zero_return_terminal" if solved < problem.horizon_years else None),
        solver=T.SolverRecord(return_status="Solve_Succeeded", iterations=1, wall_clock_s=0.01,
                              seed=int(problem.seed), seed_attempt=0, M_opt=problem.calibration.optimiser.M_opt,
                              grid=tuple(s.dt_years for s in path.steps), casadi_version="stand-in",
                              ipopt_version=None),
        seeds_used=(int(problem.seed), seed_out))
    return T.PlanOutcome(status="succeeded", result=result, wall_clock_s=0.01,
                         seeds_used=(int(problem.seed), seed_out), diagnostics={"out_of_sample": sim})


def sleepy(problem, *, simulate, deadline, should_cancel, progress):
    start = time.monotonic()
    k = 0
    while True:
        if should_cancel():
            return T.PlanOutcome(status="failed", failure_kind="cancelled", error="Stopped at a checkpoint.")
        if time.monotonic() > deadline:
            return T.PlanOutcome(status="failed", failure_kind="timed_out", error="Past the deadline.")
        k += 1
        progress({"phase": "best_life", "start": k, "of": 10**6, "seed_attempt": 0,
                  "elapsed_s": time.monotonic() - start})
        time.sleep(0.05)


def raises(problem, **_):
    raise RuntimeError("the stand-in solver broke")
