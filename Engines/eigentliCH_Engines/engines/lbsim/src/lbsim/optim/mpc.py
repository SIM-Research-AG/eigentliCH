"""Model-predictive control runtime (spec §12 / book Chapter 10, Appendix C): the draft's ``optim/mpc.py``.

    initialise x <- observed state
    for each period:
        (u*, costates) <- solve the finite horizon to the goal's deadline      # §11 Route A
        apply only u*[0]                                                       # the one action
        x <- observe the new state                                             # real data or a simulated step
        emit the period's output (the chance, the action, the exchange rate, a warning)

lbsim port (agent C): the loop, the adherence filter and the projection are the draft's. Two things are injected
instead of imported, because lbsim does not carry the draft's ``sim/montecarlo`` and ``goals/feasibility``:
``score(x, action, remaining_years, period)`` gives the period's out-of-sample chance (B2's Monte Carlo in the
engine; None reports the in-sample chance), and ``observe(x, action, period, rng)`` advances one period (default:
the draft's Euler-Maruyama step on ``lbsim.model`` at the model's monthly step, under the draft's market). The grid
of each period's solve is the calibration's rule for the remaining horizon, as in ``solve``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np

from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from . import market as mk
from .grid import build as build_grid
from .problem import DRAFT_MARKET, Budget, Costates, ExchangeRate, Market, SolveResult, solve_case
from .run import project_admissible
from .spec import GoalSpec


def apply_control(u0: dict) -> Control:
    """SEAM 5: the adherence filter. v1 is the identity: the action is taken exactly."""
    return Control(**u0)


@dataclass
class PeriodOutput:
    period: int
    age: float
    state: State
    action: Control
    p_goal: float
    p_goal_basis: str          # "out_of_sample" (score given) or "in_sample"
    costates: Costates
    exchange_rate: ExchangeRate
    solve_ok: bool
    warning: Optional[str]
    lever: str


Observer = Callable[[State, Control, int, np.random.Generator], State]
Scorer = Callable[[State, Control, float, int], float]


def default_observe(step_years: float, p: Params) -> Observer:
    """One real period through the draft's dynamics with noise, at the model's own step."""
    n = max(1, int(round(step_years / p.dt)))

    def observe(state: State, control: Control, period: int, rng: np.random.Generator) -> State:
        x = state
        for _ in range(n):
            z = rng.standard_normal(2)
            zR = p.rho_WR * z[0] + np.sqrt(max(0.0, 1.0 - p.rho_WR ** 2)) * z[1]
            v = mk.numpy_euler_step(x, control, p, p.dt, (z[0], zR))
            v[0], v[1], v[2] = max(0.0, v[0]), max(0.0, v[1]), max(0.0, v[2])
            v[3], v[4] = max(0.0, v[3]), max(0.0, v[4])
            v[5] = min(p.K_H, max(0.0, v[5]))
            x = mk.state_from_vector(v)
        return x

    return observe


def run_mpc(
    x0: State,
    goal: GoalSpec,
    *,
    start_age: float,
    target_age: float,
    params: Params | None = None,
    market: Market = DRAFT_MARKET,
    grid_rungs=((10.0, 0.5), (1000.0, 1.0)),
    grid_rule: str = "draft_single_step",
    step_years: float = 0.25,
    psi: float = 1.0,
    bequest_weight: float = 0.10,
    M_opt: int = 16,
    seed: int = 0,
    n_starts: int = 2,
    max_iter: int = 3000,
    observe: Observer | None = None,
    score: Scorer | None = None,
    interventions: dict[int, Callable[[State], State]] | None = None,
    max_periods: int = 40,
    budget: Budget | None = None,
) -> list[PeriodOutput]:
    """The receding-horizon loop from ``start_age`` toward the goal at ``target_age``. The horizon recedes to the
    fixed deadline; each period's solve uses ``seed + period`` (the draft's rule)."""
    p = params or Params()
    observe = observe or default_observe(step_years, p)
    interventions = interventions or {}
    rng = np.random.default_rng(seed)
    conf = 1.0 - goal.epsilon
    out: list[PeriodOutput] = []
    x = x0.copy()
    age = start_age
    period = 0
    while age < target_age - 1e-9 and period < max_periods:
        remaining = target_age - age
        if grid_rule == "draft_single_step":
            # The draft's loop: one step of min(0.5, remaining) years.
            eff_dt = min(0.5, remaining)
            rungs = ((1e9, eff_dt),)
        else:
            rungs = grid_rungs
        grid = build_grid(remaining, rungs, grid_rule)
        g = replace(goal, horizon_years=remaining)
        res: SolveResult = solve_case(x, g, grid=grid, params=p, market=market, psi=psi,
                                      bequest_weight=bequest_weight, M=M_opt, seed=seed + period,
                                      n_starts=n_starts, max_iter=max_iter, budget=budget)
        action = apply_control(project_admissible(res.u0))
        if score is not None:
            p_goal, basis = float(score(x, action, remaining, period)), "out_of_sample"
        else:
            p_goal, basis = float(res.p_fi_insample), "in_sample"
        warning = None
        if not res.success:
            warning = f"solve did not converge at age {age:.2f}; action projected to the admissible set"
        elif p_goal < conf:
            warning = f"P(goal) {p_goal:.0%} below target {conf:.0%} at age {age:.2f}"
        lever = (f"an hour of {res.exchange_rate.winner} is worth "
                 f"~{res.exchange_rate.ratio:.1f}x the alternative toward the goal")
        out.append(PeriodOutput(period=period, age=age, state=x.copy(), action=action, p_goal=p_goal,
                                p_goal_basis=basis, costates=res.costates, exchange_rate=res.exchange_rate,
                                solve_ok=res.success, warning=warning, lever=lever))
        x = observe(x, action, period, rng)
        if period in interventions:
            x = interventions[period](x)
        age += step_years
        period += 1
    return out
