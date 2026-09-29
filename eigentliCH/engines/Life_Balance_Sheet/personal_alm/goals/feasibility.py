"""Feasibility as a chance constraint (spec §8 / book Chapter 8).

For each goal k we require P(trajectory enters the region by the deadline) ≥ 1−ε.
No closed form exists for a system this coupled, so we estimate it by Monte Carlo:
simulate M futures under the candidate policy and count the fraction that succeed
(eq. 8.2). The estimator carries its own standard error.

For the optimiser we will constrain the CVaR of the shortfall instead of the raw
probability (eq. 8.3–8.4): CVaR is convex and conservative, so CVaR_{1−ε}[−g] ≤ 0
implies feasibility at confidence 1−ε while penalising *how badly* a plan fails.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.fiscal import DEFAULT_FISCAL, FiscalModel
from ..model.params import Params
from ..model.state import State
from ..sim.montecarlo import ControlPolicy, simulate
from .goals import Goal


@dataclass
class FeasibilityResult:
    goal: str
    p_hat: float          # MC estimate of P(goal)
    se: float             # standard error of the estimate
    n_scenarios: int
    slacks: np.ndarray    # terminal (or best-over-path) slack per scenario

    @property
    def ci95(self) -> tuple[float, float]:
        lo = max(0.0, self.p_hat - 1.96 * self.se)
        hi = min(1.0, self.p_hat + 1.96 * self.se)
        return lo, hi

    def meets(self, epsilon: float) -> bool:
        return self.p_hat >= 1.0 - epsilon


def _evaluate(traj, policy: ControlPolicy, goal: Goal, p: Params) -> float:
    """Slack achieved by a single trajectory, per the goal's mode."""
    n = len(traj.states) - 1
    if goal.mode == "at_deadline":
        st = traj.states[-1]
        u = policy(max(n - 1, 0), st)
        return goal.slack(st, p, u)
    # by_deadline: best (max) slack reached at any step up to the deadline.
    best = -np.inf
    for k, st in enumerate(traj.states):
        u = policy(min(k, n - 1), st)
        best = max(best, goal.slack(st, p, u))
    return float(best)


def feasibility(
    x0: State,
    policy: ControlPolicy,
    goal: Goal,
    p: Params | None = None,
    *,
    n_scenarios: int | None = None,
    seed: int = 0,
    fiscal: FiscalModel = DEFAULT_FISCAL,
    dt: float | None = None,
) -> FeasibilityResult:
    """Estimate P(goal) by simulating M scenarios under `policy`.

    Uses a spawned SeedSequence so the shock draws are reproducible and, crucially,
    *shared across policies* when the same `seed` is passed — common random numbers
    (spec §16.3), so the optimiser compares candidate policies like with like.

    `dt` overrides the integration step (default p.dt). A coarser step trades a
    little accuracy for speed — used by the interactive app on long horizons.
    """
    p = p or Params()
    M = n_scenarios or p.M
    step_dt = dt or p.dt
    n_steps = max(1, int(round(goal.horizon_years / step_dt)))
    child_seeds = np.random.SeedSequence(seed).spawn(M)

    slacks = np.empty(M)
    for m in range(M):
        rng = np.random.default_rng(child_seeds[m])
        traj = simulate(x0, policy, p, n_steps, rng=rng, fiscal=fiscal, dt=step_dt)
        slacks[m] = _evaluate(traj, policy, goal, p)

    p_hat = float(np.mean(slacks >= 0.0))
    se = float(np.sqrt(p_hat * (1.0 - p_hat) / M))
    return FeasibilityResult(goal=goal.name, p_hat=p_hat, se=se,
                             n_scenarios=M, slacks=slacks)


# --- CVaR surrogate (Rockafellar–Uryasev, spec §8.3–8.4) -------------------------

def cvar(losses: np.ndarray, epsilon: float) -> float:
    """CVaR at confidence level (1−ε): the expected loss in the worst ε tail.

    Sample estimator — average of the worst ⌈ε·M⌉ losses, which coincides with the
    Rockafellar–Uryasev minimiser value on the empirical distribution.
    """
    losses = np.asarray(losses, dtype=float)
    M = losses.size
    k = max(1, int(np.ceil(epsilon * M)))
    worst = np.sort(losses)[::-1][:k]
    return float(worst.mean())


def cvar_shortfall(slacks: np.ndarray, epsilon: float) -> float:
    """CVaR_{1−ε}[−g] — the quantity the optimiser constrains to ≤ 0 (eq. 8.4).

    ≤ 0 is a conservative certificate that P(g ≥ 0) ≥ 1 − ε.
    """
    return cvar(-np.asarray(slacks, dtype=float), epsilon)


def cvar_feasible(result: FeasibilityResult, epsilon: float) -> bool:
    """Does the CVaR surrogate certify feasibility at confidence 1−ε?"""
    return cvar_shortfall(result.slacks, epsilon) <= 0.0
