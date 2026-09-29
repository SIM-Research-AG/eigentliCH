"""Build the dashboard data for a case by running the engine.

One function, `build_data(case)`, runs the full pipeline (optimiser → feasibility →
projection) and returns a JSON-serialisable dict the front end renders. Works for
every archetype; FI cases additionally carry the drawable-wealth requirement.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from ..cases import Case, _binding
from ..goals.feasibility import feasibility
from ..model.dynamics import (
    income, income_tax, mu_P, net_cash_to_liquid, sigma_P, wealth_tax,
)
from ..optim.mpc import _project_admissible, apply_control
from ..optim.problem import solve_case
from ..sim.montecarlo import constant_policy, simulate, step
from ..ui.output import fi_drawable_requirement, plain_language_action, saving_rate

_GOAL_LABEL = {
    "fi": "Financial independence",
    "home": "Home purchase",
    "company": "Company founding",
    "retirement": "Retirement funding",
}


def _goal_block(case: Case, g, policy, p, *, M_eval: int, M_curve: int,
                eval_dt: float, curve_points: int, seed: int) -> dict:
    """Per-goal result: probability, binding constraint, and the P(goal)-by-age curve."""
    conf = 1.0 - g.epsilon
    feas = feasibility(case.x0, policy, g.to_goal(), p,
                       n_scenarios=M_eval, seed=seed + 1, dt=eval_dt)

    n_deadline = max(1, int(round(g.horizon_years / p.dt)))
    terminal = simulate(case.x0, policy, p, n_deadline).final
    binding = _binding(g, terminal, policy(0, case.x0), p)   # constant policy → any index

    span = g.horizon_years + (8.0 if g.kind == "fi" else 2.0)
    ages = _year_grid(case.age + 1.0, case.age + span, max_points=curve_points)
    curve, crossing = [], None
    for a in ages:
        gg = replace(g, horizon_years=a - case.age).to_goal()
        q = feasibility(case.x0, policy, gg, p, n_scenarios=M_curve,
                        seed=seed + 1, dt=eval_dt).p_hat
        curve.append({"age": a, "p": q})
        if crossing is None and q >= conf:
            crossing = a

    return {
        "kind": g.kind, "goal_label": _GOAL_LABEL[g.kind], "confidence": conf,
        "deadline_age": case.age + g.horizon_years, "horizon": g.horizon_years,
        "p_goal": feas.p_hat, "binding": binding,
        "curve": curve, "crossing_age": crossing,
        "required": (fi_drawable_requirement(case.x0, p, g.params.get("G"))
                     if g.kind == "fi" else None),
    }


def build_data(case: Case, *, M_opt: int = 12, M_eval: int = 300,
               M_curve: int = 150, n_starts: int = 2, seed: int = 0) -> dict:
    p = case.params()
    goals_all = case.goals
    primary = goals_all[0]
    horizon_max = max(g.horizon_years for g in goals_all)

    # Interactive speed. The solve dominates (the MC is cheap), so keep the NLP
    # small — ~10 steps regardless of horizon — and cap iterations so a hard or
    # infeasible case fails fast (seconds) instead of grinding to the iteration
    # limit. The MC step is coarsened a little on long horizons too.
    dt_opt = max(0.5, horizon_max / 10.0)
    eval_dt = 0.5 if horizon_max > 8.0 else 0.25
    curve_points = 6 if horizon_max > 8.0 else 7

    # One optimisation for the whole plan; every goal contributes a CVaR constraint.
    res = solve_case(case.x0, primary, extra_goals=goals_all[1:], params=p,
                     psi=case.psi, dt_opt=dt_opt, M=M_opt, seed=seed,
                     n_starts=n_starts, max_iter=250)
    action = apply_control(_project_admissible(res.u0))
    policy = constant_policy(action)

    goal_blocks = [_goal_block(case, g, policy, p, M_eval=M_eval, M_curve=M_curve,
                               eval_dt=eval_dt, curve_points=curve_points, seed=seed)
                   for g in goals_all]

    # Shared wealth projection to the latest deadline.
    span = horizon_max + (8.0 if primary.kind == "fi" else 2.0)
    n_proj = max(1, int(round(span / p.dt)))
    traj = simulate(case.x0, policy, p, n_proj)
    proj = []
    for a in _year_grid(case.age, case.age + span, max_points=20):
        idx = min(int(round((a - case.age) / p.dt)), len(traj.states) - 1)
        st = traj.states[idx]
        proj.append({"age": a, "net_worth": st.net_worth,
                     "drawable": st.wealth.drawable(h_res=p.h_res),
                     "required": fi_drawable_requirement(st, p, primary.params.get("G"))
                                 if primary.kind == "fi" else None,
                     "E": st.person.E.aggregate(), "N": st.person.N, "H": st.person.H})

    # Taxes at the current state under the applied action (visible, not hidden).
    Y0 = income(case.x0, action, p)
    # Let share only (step 3, 3 August 2026): this feeds the displayed tax figure, and taxing phantom rent on a
    # residence would have overstated the tax bill as visibly as it overstated income.
    ay0 = p.y_R * case.x0.wealth.W_inv + p.y_hol * case.x0.wealth.W_hol
    interest0 = p.i * case.x0.wealth.D
    inc_tax = income_tax(Y0 + ay0 - interest0, p)
    wea_tax = wealth_tax(case.x0.net_worth, p)
    taxes = {"income": inc_tax, "wealth": wea_tax, "total": inc_tax + wea_tax,
             "effective_pct": round(100 * (inc_tax + wea_tax) / max(Y0 + ay0, 1.0), 1),
             "gross_inflow": Y0 + ay0}

    # Investment strategy summary (mock — a detailed strategy links in later).
    th = action.theta
    strategy = {"theta": th, "risky_pct": round(th * 100), "safe_pct": round((1 - th) * 100),
                "exp_return_pct": round(mu_P(th, p) * 100, 1),
                "exp_vol_pct": round(sigma_P(th, p) * 100, 1)}

    # Planned action schedule over the horizon (roll the plan forward deterministically).
    schedule, xs = [], case.x0.copy()
    for k, ud in enumerate(res.u_path):
        u = apply_control(_project_admissible(ud))
        schedule.append({
            "age": round(case.age + k * res.dt_opt, 1), "span": round(res.dt_opt, 2),
            "work": u.tau_Y, "learn": u.tau_E, "network": u.tau_N, "rest": u.tau_H,
            "consume": u.C, "invest_per_year": net_cash_to_liquid(xs, u, p),
            "theta": u.theta, "m_E": u.m_E, "m_N": u.m_N, "p_A": u.p_A,
            "income": income(xs, u, p) + p.y_R * xs.wealth.W_inv + p.y_hol * xs.wealth.W_hol,
        })
        xs = step(xs, u, p, dt=res.dt_opt)

    data = {
        "id": _slug(case.name), "name": case.name, "persona": case.persona,
        "age": case.age, "calibrated": case.calibrated, "notes": case.notes,
        # `outcome` travels with `success` from 5 August 2026 (M79 -> P8), because `success = False` alone cannot
        # say whether the solver broke or the goal is out of reach. **The schedule below is still built on this
        # path**, and on `goal_not_fundable` it is phase 1's funding-maximising trajectory rather than a plan for
        # this household's life. The client path withholds it (`report.py` blocks and `prose.py` refuses); this
        # internal dashboard does not yet, and that is recorded as open in PLAN_2026-08 rather than half-fixed
        # here.
        "success": res.success,
        "outcome": res.stats.get("outcome", "plan" if res.success else "undetermined"),
        "shortfall": res.stats.get("shortfall_annual"),
        "net_worth": case.x0.net_worth,
        "drawable": case.x0.wealth.drawable(h_res=p.h_res),
        "action": {k: float(v) for k, v in res.u0.items()},
        "action_text": plain_language_action(case.x0, action, p),
        "saving_pct": round(saving_rate(case.x0, action, p) * 100),
        "costates": {"E": res.costates.lam_E, "N": res.costates.lam_N, "H": res.costates.lam_H},
        "exchange": {"winner": res.exchange_rate.winner,
                     "ratio": res.exchange_rate.ratio, "dominant": res.exchange_rate.dominant},
        "taxes": taxes, "strategy": strategy, "schedule": schedule,
        "projection": proj,
        "goals": goal_blocks,
    }
    data.update(goal_blocks[0])          # primary goal fields at top level (back-compat)
    return data


def _year_grid(lo: float, hi: float, *, max_points: int) -> list[float]:
    span = max(1.0, hi - lo)
    step = max(1.0, round(span / (max_points - 1)))
    ages, a = [], lo
    while a <= hi + 1e-9:
        ages.append(round(a, 1))
        a += step
    return ages


def _slug(name: str) -> str:
    return name.lower().split()[0].replace("&", "and")
