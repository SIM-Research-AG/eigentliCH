"""The solve: SLSQP with the exact gradient, ``trust-constr`` as the fallback. Pure.

A deterministic solve from a fixed starting point (Manual section 15.2): every weight starts at
``solver.start_value`` (0.5, the draft's and MATLAB's). That point violates the budget for more than two
instruments; SLSQP projects onto the feasible set in its first iterations (draft D20). If SLSQP fails, the
fallback runs and is kept when it succeeds or reaches a lower objective. No multi-start.

The raw solution is returned as it is. Renormalising and the budget check are the caller's, from the raw
weights (Manual section 15.2).

:func:`rescue` is the engine-level fallback of PCP-21, outside the calibration: it runs only when the
calibrated solve above has not produced an acceptable solution (unconverged, raw weights off the budget, or a
row, the budget or a bound breached by more than ``constraints.FEASIBILITY_TOL``). It starts from the
phase-1 point (feasible, as far inside the binding rows as the block allows) with the exact settings, on the
rows the budget and the per-instrument bounds do not already imply (the same feasible set; SLSQP's subproblem
degenerates on the implied ones), SLSQP first, then ``trust-constr``, and keeps the first acceptable one. A solve the calibrated path settles is
never touched, so every golden case reproduces unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import LinearConstraint, minimize

from . import objective as obj
from .constraints import FEASIBILITY_TOL, ConstraintSystem, max_violation
from .contracts import SolverSpec


@dataclass(frozen=True)
class Solve:
    raw_weights: np.ndarray
    objective: float
    method: str
    status: str
    iterations: int
    success: bool
    notes: tuple[str, ...]


def _minimise(method: str, f, g, x0: np.ndarray, bounds, a: np.ndarray, b: np.ndarray, ftol: float,
              maxiter: int):
    n = x0.shape[0]
    if method == "SLSQP":
        ineq = [{"type": "ineq", "fun": lambda x: b - a @ x, "jac": lambda x: -a}] if a.shape[0] else []
        return minimize(
            f, x0, jac=g, method="SLSQP", bounds=bounds,
            constraints=[{"type": "eq", "fun": lambda x: float(np.sum(x) - 1.0), "jac": lambda x: np.ones_like(x)}]
            + ineq,
            options={"ftol": ftol, "maxiter": maxiter})
    linear = [LinearConstraint(np.ones((1, n)), lb=1.0, ub=1.0)]
    if a.shape[0]:
        linear.append(LinearConstraint(a, lb=-np.inf, ub=b))
    return minimize(f, x0, jac=g, method="trust-constr", bounds=bounds, constraints=linear,
                    options={"gtol": ftol, "xtol": ftol, "maxiter": maxiter})


def rescue(bb: np.ndarray, target: np.ndarray, regime: np.ndarray, system: ConstraintSystem,
           spec: SolverSpec, start: np.ndarray, scale: float = 1.0) -> Solve:
    """The engine-level fallback (PCP-21): from the feasible ``start``, exact settings, SLSQP then
    ``trust-constr``; the first converged solution within ``FEASIBILITY_TOL`` of every row, the budget and
    every bound is kept. Unsuccessful when neither is."""
    profiles = np.asarray(bb, dtype=float)
    settings = spec.speeds.get("exact") or max(spec.speeds.values(), key=lambda s: s.maxiter)
    bounds = list(zip(system.lower_bounds.tolist(), system.upper_bounds.tolist()))
    x0 = np.clip(np.asarray(start, dtype=float), system.lower_bounds, system.upper_bounds)

    def f(x: np.ndarray) -> float:
        return obj.objective(x, profiles, target, regime, scale)

    def g(x: np.ndarray) -> np.ndarray:
        return obj.gradient(x, profiles, target, regime, scale)

    a, b = system.reduced()
    notes: list[str] = []
    last = None
    for method in (spec.method, spec.fallback_method):
        outcome = _minimise(method, f, g, x0, bounds, a, b, settings.ftol, settings.maxiter)
        breach = max_violation(outcome.x, system)
        if outcome.success and breach <= FEASIBILITY_TOL:
            notes.append(f"{method} from a feasible start with the exact settings, on the {a.shape[0]} rows the budget "
                         "and the bounds do not already imply, converged (PCP-21)")
            return Solve(raw_weights=np.asarray(outcome.x, dtype=float), objective=float(outcome.fun),
                         method=method, status=str(outcome.message).strip(),
                         iterations=int(getattr(outcome, "nit", 0) or 0), success=True, notes=tuple(notes))
        notes.append(f"{method} from a feasible start with the exact settings did not settle "
                     f"({str(outcome.message).strip()}; largest breach {breach:.2e})")
        last = (method, outcome)
    method, outcome = last  # type: ignore[misc]
    return Solve(raw_weights=np.asarray(outcome.x, dtype=float), objective=float(outcome.fun), method=method,
                 status=str(outcome.message).strip(), iterations=int(getattr(outcome, "nit", 0) or 0),
                 success=False, notes=tuple(notes))


def solve(bb: np.ndarray, target: np.ndarray, regime: np.ndarray, system: ConstraintSystem,
          spec: SolverSpec, speed: str, scale: float = 1.0) -> Solve:
    profiles = np.asarray(bb, dtype=float)
    n = profiles.shape[0]
    settings = spec.speeds[speed]
    x0 = np.full(n, spec.start_value, dtype=float)
    bounds = list(zip(system.lower_bounds.tolist(), system.upper_bounds.tolist()))

    def f(x: np.ndarray) -> float:
        return obj.objective(x, profiles, target, regime, scale)

    def g(x: np.ndarray) -> np.ndarray:
        return obj.gradient(x, profiles, target, regime, scale)

    notes: list[str] = []
    outcome = minimize(
        f, x0, jac=g, method=spec.method, bounds=bounds,
        constraints=[{"type": "eq", "fun": lambda x: float(np.sum(x) - 1.0), "jac": lambda x: np.ones_like(x)},
                     {"type": "ineq", "fun": lambda x: system.b - system.a @ x, "jac": lambda x: -system.a}],
        options={"ftol": settings.ftol, "maxiter": settings.maxiter},
    )
    method = spec.method
    if not outcome.success:
        notes.append(f"{spec.method} did not converge ({str(outcome.message).strip()}); "
                     f"{spec.fallback_method} was tried")
        fallback = minimize(
            f, x0, jac=g, method=spec.fallback_method, bounds=bounds,
            constraints=[LinearConstraint(np.ones((1, n)), lb=1.0, ub=1.0),
                         LinearConstraint(system.a, lb=-np.inf, ub=system.b)],
            options={"gtol": settings.ftol, "xtol": settings.ftol, "maxiter": settings.maxiter},
        )
        if fallback.success or fallback.fun < outcome.fun:
            outcome, method = fallback, spec.fallback_method
        else:
            notes.append(f"{spec.fallback_method} did not converge either "
                         f"({str(fallback.message).strip()})")
    return Solve(raw_weights=np.asarray(outcome.x, dtype=float), objective=float(outcome.fun),
                 method=method, status=str(outcome.message).strip(),
                 iterations=int(getattr(outcome, "nit", 0) or 0), success=bool(outcome.success),
                 notes=tuple(notes))
