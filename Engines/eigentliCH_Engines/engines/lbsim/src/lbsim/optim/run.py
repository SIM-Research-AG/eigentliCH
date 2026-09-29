"""``solve``: a ``PlanProblem`` in, a ``PlanOutcome`` out (the draft's ``cases.run_case`` for lbsim).

1. The household from the adapter's submission (the draft's ``onboarding`` reading: the state with its
   mid-scale defaults, ``Params`` through the fast half's own ``_params_from`` so the plan and the findings read
   one parameter set), the goals as ``GoalSpec``, the grid and the market from the calibration.
2. The two-phase multistart solve with the redraw rule, under the run's clock.
3. The out-of-sample chance from the injected ``simulate`` (B2's Monte Carlo) at ``seed + 500 000``.

A run that did not converge, timed out or was cancelled returns ``status = "failed"`` with its
``failure_kind`` and no figures. ``undetermined`` (the draft's non-converged outcome) is ``failed`` /
``solver``.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Optional

import casadi as ca
import numpy as np

from ..calibration import tables
from ..fast import gameplan as _gameplan
from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from . import market as mk
from . import types as T
from .grid import Grid, build as build_grid
from .problem import Budget, Market, SolveFailed, SolveResult, Stopped, solve_case
from .spec import GoalSpec

#: The draft's state defaults for capitals the submission leaves open (``onboarding._STATE_DEFAULTS``).
STATE_DEFAULTS: dict[str, float] = {"E": 0.5, "N": 0.5, "H": 0.8}
#: The productive week the time shares are read against (``tau x 100 hours``, section 3.4).
PRODUCTIVE_WEEK_HOURS = 100.0
OUT_OF_SAMPLE_OFFSET = 500_000
REDRAW_STEP = 1_000


class ProblemError(ValueError):
    """The problem cannot be put to the optimiser (a gap in the inputs, not a solver failure)."""


# --- the inputs ----------------------------------------------------------------------------------------------

def household(problem: T.PlanProblem) -> tuple[State, Params]:
    """The initial state and the parameters, as the draft's converter and the fast half read the submission."""
    sub = problem.submission
    state = dict(sub.get("state") or {})
    if state.get("age") is None:
        raise ProblemError("the submission states no age; the optimiser's pension gates and earning decline read it")
    caps = {k: float(state[k]) if state.get(k) is not None else v for k, v in STATE_DEFAULTS.items()}
    x0 = State.individual(W_L=float(state.get("W_L") or 0.0), W_R=float(state.get("W_R") or 0.0),
                          D=float(state.get("D") or 0.0), E=caps["E"], N=caps["N"], H=caps["H"],
                          age=float(state["age"]), W_res=float(state.get("W_res") or 0.0),
                          W_hol=float(state.get("W_hol") or 0.0), W_P=float(state.get("W_P") or 0.0),
                          W_3a=float(state.get("W_3a") or 0.0))
    with tables(problem.calibration):
        p = _gameplan._params_from(dict(sub))
    return x0, p


def _epsilon(confidence: float) -> float:
    return max(0.01, min(0.5, 1.0 - float(confidence)))


def goal_spec(g: T.GoalInput, grid: Grid) -> GoalSpec:
    eps = _epsilon(g.confidence)
    if g.measure is None:
        if g.kind not in ("fi", "home", "company", "retirement"):
            raise ProblemError(f"goal {g.goal_id} has neither a measure nor a draft kind")
        return GoalSpec(kind=g.kind, horizon_years=float(g.horizon_years), epsilon=eps, params=dict(g.params))
    if g.amount_basis == "today":
        target = g.target_real_chf if g.target_real_chf is not None else g.target_nominal_chf
    else:
        target = g.target_nominal_chf
    if target is None or not math.isfinite(float(target)) or float(target) < 0:
        raise ProblemError(f"goal {g.goal_id} has no usable target")
    # The zero-return allowance beyond the cap: the requirement at the cap is ``max(0, target - saving x years)``,
    # as B2's Monte Carlo reads it (a negative planned saving raises it above the target).
    extra = min(float(target), float(g.planned_saving_chf_per_year) * grid.beyond(float(g.horizon_years)))
    return GoalSpec(kind="measure", horizon_years=float(g.horizon_years), epsilon=eps,
                    params={"measure": g.measure, "target": float(target), "basis": g.amount_basis,
                            "lbsim_kind": g.kind, "extra": extra})


def the_market(problem: T.PlanProblem) -> Market:
    cal = problem.calibration
    if cal.behaviour.market == "draft":
        return Market("draft")
    if problem.market.kind != "allocation":
        raise ProblemError("calibration %s reads the market from the Allocation, and the problem carries none"
                           % cal.version)
    if abs(cal.market.wage_pass_through - 1.0) > 1e-12 or abs(cal.market.spending_pass_through - 1.0) > 1e-12:
        raise ProblemError("the optimiser runs in today's francs and supports a pass-through of 1.0 only")
    return Market("allocation", inputs=problem.market, prop=cal.property)


def the_grid(problem: T.PlanProblem) -> Grid:
    opt = problem.optimiser
    h = max(float(g.horizon_years) for g in problem.goals)
    if h <= 0:
        raise ProblemError("every goal lies in the past; there is nothing to plan for")
    cap = None
    if opt.grid_rule == "variable":
        # The calibration's cap (1.3.0 on) and the run's (config.yaml): the tighter one holds.
        caps = [float(problem.max_solve_horizon_years)]
        if getattr(opt, "max_solve_horizon_years", None) is not None:
            caps.append(float(opt.max_solve_horizon_years))
        cap = min(caps)
    return build_grid(h, opt.grid, opt.grid_rule, cap=cap)


# --- the result ------------------------------------------------------------------------------------------------

def project_admissible(u0: dict) -> dict:
    """The draft's ``mpc._project_admissible``: a no-op on a converged solve, a safeguard otherwise."""
    d = dict(u0)
    taus = [max(0.0, d[k]) for k in ("tau_Y", "tau_E", "tau_N", "tau_H")]
    total = sum(taus)
    if total > 1.0:
        taus = [t / total for t in taus]
    d["tau_Y"], d["tau_E"], d["tau_N"], d["tau_H"] = taus
    for k in ("m_E", "m_N", "p_A"):
        d[k] = max(0.0, d[k])
    d["C"] = max(1_000.0, d["C"])
    d["theta"] = min(1.0, max(0.0, d["theta"]))
    return d


def control_path(res: SolveResult, grid: Grid, market: Market, horizon_years: float) -> T.ControlPath:
    steps = tuple(T.ControlStep(t_years=float(grid.times[k]), dt_years=float(grid.dts[k]),
                                controls={n: float(v) for n, v in project_admissible(u).items()})
                  for k, u in enumerate(res.u_path))
    return T.ControlPath(steps=steps, horizon_years=float(horizon_years),
                         money_basis="today_indexed" if market.kind == "allocation" else "nominal")


def saving_now(x0: State, u: dict, p: Params) -> float:
    """What the first period adds to liquid wealth before any market return: the drift of W_L without the
    market (income, pensions, rents less consumption, spends, interest, contributions and taxes)."""
    ctl = Control(**{k: u[k] for k in T.CONTROL_NAMES})
    return float(mk.numpy_drift(x0, ctl, mk.no_market_params(p))[0])


def action_now(x0: State, u: dict, p: Params) -> T.ActionNow:
    return T.ActionNow(
        work_share=u["tau_Y"],
        learning_hours_per_week=u["tau_E"] * PRODUCTIVE_WEEK_HOURS,
        network_hours_per_week=u["tau_N"] * PRODUCTIVE_WEEK_HOURS,
        rest_hours_per_week=u["tau_H"] * PRODUCTIVE_WEEK_HOURS,
        consumption_chf_per_year=u["C"],
        saving_chf_per_year=saving_now(x0, u, p),
        education_spend_chf_per_year=u["m_E"],
        network_spend_chf_per_year=u["m_N"],
        amortisation_chf_per_year=u["p_A"],
    )


def _ipopt_version() -> Optional[str]:
    """CasADi does not report the IPOPT build it bundles (3.7.2 ships IPOPT 3.14 in the wheel), so the record says
    None rather than a guess; ``casadi_version`` pins it."""
    return None


def _failed(kind: str, error: str, budget: Budget, seeds: list[int], diagnostics: dict[str, Any]) -> T.PlanOutcome:
    return T.PlanOutcome(status="failed", failure_kind=kind, result=None, error=error,
                         wall_clock_s=round(budget.elapsed(), 3), seeds_used=tuple(seeds),
                         diagnostics=diagnostics)


def solve(problem: T.PlanProblem, *, simulate: Callable[[T.PlanProblem, T.ControlPath, int, int], dict],
          deadline: float, should_cancel: Callable[[], bool], progress: Callable[[dict], None]) -> T.PlanOutcome:
    budget = Budget(deadline=deadline, should_cancel=should_cancel, progress=progress)
    opt = problem.optimiser
    seeds: list[int] = []
    diagnostics: dict[str, Any] = {}
    try:
        budget.check()
        x0, p = household(problem)
        grid = the_grid(problem)
        market = the_market(problem)
        primary = goal_spec(problem.goal, grid)
        extras = [goal_spec(g, grid) for g in problem.extra_goals]
    except Stopped as stop:
        return _failed(stop.kind, str(stop), budget, seeds, diagnostics)
    except ProblemError as exc:
        return _failed("solver", f"The plan calculation could not start: {exc}.", budget, seeds, diagnostics)

    diagnostics["grid"] = list(grid.dts)
    diagnostics["market"] = market.kind
    try:
        res = solve_case(x0, primary, grid=grid, params=p, extra_goals=extras, market=market,
                         M=opt.M_opt, n_starts=opt.n_starts, restore_starts=opt.restore_starts,
                         cvar_tol=opt.cvar_tol, seed_retries=opt.seed_retries, max_iter=opt.max_iter,
                         seed=int(problem.seed), seed_step=REDRAW_STEP, budget=budget)
    except Stopped as stop:
        return _failed(stop.kind, str(stop), budget, list(budget.seeds), diagnostics)
    except SolveFailed as exc:
        diagnostics["solve_failed"] = str(exc)
        return _failed("solver", "The optimiser could not start from any of its warm starts; no figures are "
                                 "reported.", budget, list(budget.seeds), diagnostics)

    st = res.stats
    seeds.extend(int(s) for s in st.get("seeds_tried", [st.get("seed", problem.seed)]))
    diagnostics.update({k: st.get(k) for k in ("outcome", "return_status", "iter_count", "s_star", "cvar_bound",
                                                "restore_converged", "seed", "seed_attempt",
                                                "seed_attempts_exhausted")})
    diagnostics["solves"] = st.get("solves", [])
    diagnostics["in_sample_cvar"] = res.cvar_shortfall
    outcome = st.get("outcome", "plan" if res.success else "undetermined")
    if outcome == "undetermined":
        return _failed("solver", "The optimiser did not converge on this household, so no figures are reported.",
                       budget, seeds, diagnostics)

    try:
        budget.check()
        path = control_path(res, grid, market, problem.horizon_years)
        n_oos = int(problem.n_out_of_sample or opt.M_eval)
        seed_out = int(problem.seed) + OUT_OF_SAMPLE_OFFSET
        seeds.append(seed_out)
        sim = simulate(problem, path, n_oos, seed_out)
        budget.check()
    except Stopped as stop:
        return _failed(stop.kind, str(stop), budget, seeds, diagnostics)

    u0 = project_admissible(res.u0)
    target = float(primary.params["target"]) if primary.kind == "measure" else None
    reachable = None
    if outcome == "goal_not_fundable":
        s_star = max(0.0, float(st.get("s_star") or 0.0))
        if target is not None:
            amount = max(0.0, target * (1.0 - s_star))
        else:
            from .problem import _stated_amount, amount_deficit  # noqa: PLC0415
            stated = _stated_amount(primary, p)
            amount = max(0.0, stated - amount_deficit(primary.kind, stated, s_star))
        reachable = T.Reachable(amount_chf=amount, at_confidence=1.0 - primary.epsilon)
    xr = res.exchange_rate
    exchange = T.ExchangeRate(
        winner=xr.winner, ratio=None if xr.winner == "undetermined" else float(xr.ratio),
        dominant=(("tau_N" if xr.winner == "networking" else "tau_Y") if xr.dominant and xr.determined else None))
    horizon = T.PlanHorizon(
        solved_years=float(grid.times[-1]), total_years=float(problem.horizon_years),
        beyond_cap_rule="zero_return_terminal" if (grid.rule == "variable" and (
            float(problem.horizon_years) > grid.times[-1] + 1e-9
            or any(grid.beyond(g.horizon_years) > 0 for g in problem.goals))) else None)
    solver = T.SolverRecord(return_status=str(st.get("return_status")), iterations=int(st.get("iter_count", -1)),
                            wall_clock_s=round(budget.elapsed(), 3), seed=int(st.get("seed", problem.seed)),
                            seed_attempt=int(st.get("seed_attempt", 0)), M_opt=int(opt.M_opt),
                            grid=tuple(float(d) for d in grid.dts), casadi_version=ca.__version__,
                            ipopt_version=_ipopt_version())
    result = T.PlanResult(
        outcome="solved" if outcome == "plan" else "goal_not_fundable",
        goal_id=problem.goal.goal_id, goal_kind=problem.goal.kind, confidence=1.0 - primary.epsilon,
        extra_goals=tuple(g.goal_id for g in problem.extra_goals),
        action_now=action_now(x0, u0, p),
        chance=T.PlanChance(in_sample=float(res.p_fi_insample), out_of_sample=float(sim["chance"]),
                            n_out_of_sample=n_oos, seed_out=seed_out),
        shortfall_cvar_chf=float(sim["shortfall_cvar_chf"]),
        reachable=reachable,
        exchange_rate=exchange,
        costates=T.Costates(W=res.costates.lam_W, E=res.costates.lam_E, N=res.costates.lam_N,
                            H=res.costates.lam_H),
        control_path=path, horizon=horizon, solver=solver, seeds_used=tuple(seeds))
    diagnostics["out_of_sample"] = {k: sim.get(k) for k in ("chance", "n_reached", "shortfall_cvar_chf")}
    return T.PlanOutcome(status="succeeded", result=result, wall_clock_s=round(budget.elapsed(), 3),
                         seeds_used=tuple(seeds), diagnostics=diagnostics)


# --- a stand-in Monte Carlo for tests and for a worker without B2's (not the engine's) -------------------------

def reference_simulate(problem: T.PlanProblem, controls: T.ControlPath, n_paths: int, seed: int) -> dict:
    """A plain per-path simulation of the NLP's own step under ``controls`` for the primary goal: the draft's
    market on the draft's step, or the allocation market on the adapted step, at the NLP's grid. It exists so the
    optimiser can be tested and diagnosed on its own; the engine's out-of-sample chance is B2's Monte Carlo."""
    x0, p = household(problem)
    grid = the_grid(problem)
    market = the_market(problem)
    goal = goal_spec(problem.goal, grid)
    kg = grid.goal_node(goal.horizon_years)
    import casadi as _ca  # noqa: PLC0415
    from . import symbolic as sym  # noqa: PLC0415
    xs, us = _ca.SX.sym("x", sym.NX), _ca.SX.sym("u", sym.NU)
    lv = _ca.SX.sym("lv")
    slack_f = _ca.Function("slack", [xs, us, lv], [goal.symbolic_slack(xs, us, p, level=lv)])
    x0v = mk.state_vector(x0, p)
    if market.kind == "allocation":
        scen = mk.sample_allocation(market.inputs, market.prop, grid.dts, n_paths, seed)
        levels = scen.level
        p_nm = mk.no_market_params(p)
        r_, i_, g_ = _ca.SX.sym("r"), _ca.SX.sym("i"), _ca.SX.sym("g")
        steps = {dt: _ca.Function("s", [xs, us, r_, i_, g_], [sym.allocation_step(xs, us, p_nm, dt, r=r_, infl=i_,
                                                                                  growth=g_)])
                 for dt in set(grid.dts)}
    else:
        from .problem import _sample_shocks  # noqa: PLC0415
        Z = _sample_shocks(n_paths, grid.K, p.rho_WR, seed)
        levels = np.ones((n_paths, grid.K + 1))
        zs = _ca.SX.sym("z", 2)
        steps = {dt: _ca.Function("s", [xs, us, zs], [sym.euler_step(xs, us, zs, p, dt)]) for dt in set(grid.dts)}
    slacks = np.zeros(n_paths)
    for m in range(n_paths):
        xv = x0v.copy()
        for k in range(kg):
            uv = [controls.steps[k].controls[n] for n in T.CONTROL_NAMES]
            dt = grid.dts[k]
            if market.kind == "allocation":
                xv = np.array(steps[dt](xv, uv, scen.r[m, k], scen.infl[m, k], scen.growth[m, k])).flatten()
            else:
                xv = np.array(steps[dt](xv, uv, Z[m, k])).flatten()
        uv = [controls.steps[kg - 1].controls[n] for n in T.CONTROL_NAMES]
        slacks[m] = float(slack_f(xv, uv, levels[m, kg]))
    reached = slacks >= 0
    losses = np.sort(-slacks)[::-1]
    n_tail = max(1, int(math.ceil(goal.epsilon * n_paths)))
    cvar = float(np.mean(losses[:n_tail]))
    scale = float(goal.params["target"]) if goal.kind == "measure" else 1.0
    return {"chance": float(np.mean(reached)), "n_reached": int(reached.sum()),
            "shortfall_cvar_chf": max(0.0, cvar) * scale, "stand_in": True}
