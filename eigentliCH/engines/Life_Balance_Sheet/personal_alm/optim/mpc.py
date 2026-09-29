"""Model-predictive control runtime (spec §12 / book Chapter 10, Appendix C).

    initialise x ← observed state
    for each period:
        active ← goals not yet met and not past deadline
        (u*, costates) ← solve_finite_horizon(x, active, horizon)   # §11 Route A
        apply only u*[0]                                            # the one action
        x ← observe new state                                      # real data or a sim step
        emit consumer output (P(goal), action, exchange rate, warning)

The horizon recedes toward the fixed goal deadline (§12): from age 45 targeting
age 50, period k solves over the remaining 5 − k·Δt years. The applied control
passes through `apply_control` — the identity adherence filter (SEAM 5); a
P(action taken) model wraps this one call site later (Chapter 20 §5).

Each period reports the *out-of-sample* P(FI): the optimiser's in-sample figure
is re-estimated by Monte Carlo on the applied action over the numpy simulator, so
the number the consumer sees is honest rather than the value the plan optimised.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..goals.feasibility import feasibility
from ..goals.goals import fi_goal
from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from ..sim.montecarlo import constant_policy, simulate
from .problem import Costates, ExchangeRate, SolveResult, solve_fi


def apply_control(u0: dict) -> Control:
    """SEAM 5: adherence filter. v1 is the identity — the recommended action is
    taken exactly. A P(action-taken) model wraps this later."""
    return Control(**u0)


def _project_admissible(u0: dict) -> dict:
    """Project a control onto the admissible set (spec §4). A runtime safeguard:
    a non-converged solve can return an out-of-bounds iterate, and the loop must
    never apply an inadmissible action. When the solve converged this is a no-op."""
    d = dict(u0)
    taus = [max(0.0, d[k]) for k in ("tau_Y", "tau_E", "tau_N", "tau_H")]
    total = sum(taus)
    if total > 1.0:
        taus = [t / total for t in taus]   # scale back into the simplex
    d["tau_Y"], d["tau_E"], d["tau_N"], d["tau_H"] = taus
    for k in ("m_E", "m_N", "p_A"):
        d[k] = max(0.0, d[k])
    d["C"] = max(1_000.0, d["C"])
    d["theta"] = min(1.0, max(0.0, d["theta"]))
    return d


@dataclass
class PeriodOutput:
    period: int
    age: float
    state: State
    action: Control
    p_fi_oos: float          # out-of-sample P(FI) under the applied action
    costates: Costates
    exchange_rate: ExchangeRate
    solve_ok: bool
    warning: str | None
    lever: str


# observe: (state, control, period, rng) → next observed state.
Observer = Callable[[State, Control, int, np.random.Generator], State]


def _default_observe(step_years: float, p: Params) -> Observer:
    """Advance one real period through the true dynamics with noise (spec §12:
    'real data if available, else simulate one step')."""
    n = max(1, int(round(step_years / p.dt)))

    def observe(state: State, control: Control, period: int,
                rng: np.random.Generator) -> State:
        return simulate(state, constant_policy(control), p, n, rng=rng).final

    return observe


def run_mpc(
    x0: State,
    *,
    start_age: float,
    target_age: float,
    params: Params | None = None,
    step_years: float = 0.25,
    epsilon: float = 0.10,
    psi: float = 1.0,
    bequest_weight: float = 0.10,
    dt_opt: float = 0.5,
    M_opt: int = 16,
    M_eval: int = 400,
    seed: int = 0,
    n_starts: int = 2,
    observe: Observer | None = None,
    interventions: dict[int, Callable[[State], State]] | None = None,
    max_periods: int = 40,
) -> list[PeriodOutput]:
    """Run the receding-horizon loop from start_age toward the goal at target_age.

    `interventions[k]` (optional) transforms the state just after it is observed at
    the end of period k — used to inject shocks and confirm the loop recovers
    (spec §16.4 step 5).
    """
    p = params or Params()
    observe = observe or _default_observe(step_years, p)
    interventions = interventions or {}
    rng = np.random.default_rng(seed)
    conf = 1.0 - epsilon

    out: list[PeriodOutput] = []
    x = x0.copy()
    age = start_age
    period = 0

    while age < target_age - 1e-9 and period < max_periods:
        remaining = target_age - age
        eff_dt = min(dt_opt, remaining)

        res: SolveResult = solve_fi(
            x, horizon_years=remaining, params=p, epsilon=epsilon,
            psi=psi, bequest_weight=bequest_weight, dt_opt=eff_dt,
            M=M_opt, seed=seed + period, n_starts=n_starts,
        )
        action = apply_control(_project_admissible(res.u0))

        # Honest out-of-sample P(FI) under the applied action over the remaining horizon.
        goal = fi_goal(G=p.G, swr=p.swr, h_res=p.h_res,
                       horizon_years=remaining, epsilon=epsilon)
        feas = feasibility(x, constant_policy(action), goal, p,
                           n_scenarios=M_eval, seed=1_000 + period)
        p_fi = feas.p_hat

        warning = None
        if not res.success:
            warning = (f"solve did not converge at age {age:.2f}; action projected "
                       f"to the admissible set")
        elif p_fi < conf:
            warning = (f"P(FI) {p_fi:.0%} below target {conf:.0%} at age {age:.2f}")
        lever = (f"an hour of {res.exchange_rate.winner} is worth "
                 f"~{res.exchange_rate.ratio:.1f}× the alternative toward FI")

        out.append(PeriodOutput(
            period=period, age=age, state=x.copy(), action=action,
            p_fi_oos=p_fi, costates=res.costates, exchange_rate=res.exchange_rate,
            solve_ok=res.success, warning=warning, lever=lever,
        ))

        # Advance one real period, then apply any scheduled shock.
        x = observe(x, action, period, rng)
        if period in interventions:
            x = interventions[period](x)

        age += step_years
        period += 1

    return out
