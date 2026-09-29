"""Solve the curve fit: minimise the asymmetric squared shortfall under the mandate's constraints.

SLSQP, with `trust-constr` as a fallback. The start point is fixed at `0.5 * ones(n)`, reproducing the
reference implementation, which is what makes a run a pure function of its inputs.

That start point sums to `n/2` and therefore violates the budget equality for any universe of more than
two instruments. It is kept because it is what the reference used and because it is deterministic; SLSQP
projects onto the feasible set on its first iterations. It is a deliberate choice, not an oversight
(decisions.md D20).

`conditions_met` is recorded from the raw solution *before* renormalisation, because renormalised weights
always sum to one and reading only those would hide an infeasible mandate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from scipy.optimize import LinearConstraint, minimize

from pcp.config import Config
from pcp.model.constraints import ConstraintSystem
from pcp.model.objective import curve_objective, curve_objective_gradient


@dataclass(frozen=True, slots=True)
class SolveResult:
    """One solve.

    Attributes:
        weights: The renormalised weights, summing to one.
        raw_weights: The solver's own solution, before renormalisation.
        objective_value: The objective at `raw_weights`.
        conditions_met: "yes" if the raw weights summed to one at the configured rounding, else "no".
        status: A short readable status.
        method: The method that produced the solution.
        iterations: Iterations used.
        success: The solver's own success flag.
        notes: Anything a reader must know, including a fallback having been used.
    """

    weights: np.ndarray
    raw_weights: np.ndarray
    objective_value: float
    conditions_met: str
    status: str
    method: str
    iterations: int
    success: bool
    notes: tuple[str, ...] = ()


def solve_curve(
    bb: np.ndarray,
    target_curve: np.ndarray,
    regime: np.ndarray,
    system: ConstraintSystem,
    config: Config,
    speed: str = "exact",
) -> SolveResult:
    """Minimise the objective subject to the mandate's constraints.

    Args:
        bb: Instrument profile matrix, n by 25, in universe order.
        target_curve: The mandate's 25-point objective curve.
        regime: The 25-length regime distribution for the period being solved.
        system: The assembled constraints.
        config: Loaded configuration, for the solver settings.
        speed: "fast" or "exact".

    Returns:
        The solve.
    """
    profiles = np.asarray(bb, dtype=float)
    n = profiles.shape[0]
    if system.n_instruments != n:
        raise ValueError(
            f"the constraint system is built for {system.n_instruments} instruments but BB has {n}"
        )

    speeds = dict(config.get("solver.speeds"))
    if speed not in speeds:
        raise ValueError(f"unknown speed {speed!r}; configured: {sorted(speeds)}")
    settings = speeds[speed]
    ftol = float(settings["ftol"])
    maxiter = int(settings["maxiter"])

    start_value = float(config.get("solver.start_value"))
    x0 = np.full(n, start_value, dtype=float)

    bounds = list(zip(system.lower_bounds.tolist(), system.upper_bounds.tolist()))

    def objective(x: np.ndarray) -> float:
        return curve_objective(x, profiles, target_curve, regime)

    def gradient(x: np.ndarray) -> np.ndarray:
        return curve_objective_gradient(x, profiles, target_curve, regime)

    notes: list[str] = []

    primary = str(config.get("solver.method"))
    constraints_slsqp = [
        # The budget equality.
        {"type": "eq", "fun": lambda x: float(np.sum(x) - 1.0), "jac": lambda x: np.ones_like(x)},
        # b - A x >= 0.
        {
            "type": "ineq",
            "fun": lambda x: system.b - system.a @ x,
            "jac": lambda x: -system.a,
        },
    ]

    outcome = minimize(
        objective,
        x0,
        jac=gradient,
        method=primary,
        bounds=bounds,
        constraints=constraints_slsqp,
        options={"ftol": ftol, "maxiter": maxiter},
    )
    method_used = primary

    if not outcome.success:
        fallback = str(config.get("solver.fallback_method"))
        notes.append(
            f"{primary} did not converge ({outcome.message.strip()}), so {fallback} was used. The "
            f"reported allocation is the fallback's solution."
        )
        linear = [
            LinearConstraint(np.ones((1, n)), lb=1.0, ub=1.0),
            LinearConstraint(system.a, lb=-np.inf, ub=system.b),
        ]
        fallback_outcome = minimize(
            objective,
            x0,
            jac=gradient,
            method=fallback,
            bounds=bounds,
            constraints=linear,
            options={"gtol": ftol, "xtol": ftol, "maxiter": maxiter},
        )
        if fallback_outcome.success or fallback_outcome.fun < outcome.fun:
            outcome = fallback_outcome
            method_used = fallback
        else:
            notes.append(
                f"{fallback} did not converge either ({fallback_outcome.message.strip()}). The "
                f"allocation below is the best point found and should not be treated as optimal."
            )

    raw = np.asarray(outcome.x, dtype=float)

    decimals = int(config.get("solver.conditions_met_decimals"))
    conditions_met = "yes" if round(float(raw.sum()), decimals) == 1 else "no"

    total = float(raw.sum())
    if total <= 0.0:
        raise ValueError(
            "the solver returned weights summing to zero or less, so they cannot be normalised. The "
            "mandate is very likely infeasible; check the feasibility notes."
        )
    weights = raw / total

    if conditions_met == "no":
        notes.append(
            f"the solver's raw weights summed to {total:.6f} rather than one, so the budget equality was "
            f"not met within the recorded tolerance. The reported weights are renormalised, which makes "
            f"them sum to one but does not make the mandate feasible. Read conditions_met before the "
            f"weights."
        )

    return SolveResult(
        weights=weights,
        raw_weights=raw,
        objective_value=float(outcome.fun),
        conditions_met=conditions_met,
        status=str(outcome.message).strip(),
        method=method_used,
        iterations=int(getattr(outcome, "nit", 0) or 0),
        success=bool(outcome.success),
        notes=tuple(notes),
    )
