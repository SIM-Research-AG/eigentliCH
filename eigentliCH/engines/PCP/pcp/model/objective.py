"""The asymmetric squared-shortfall objective: the model of record.

For candidate weights `x` (length n), the instrument profile matrix `BB` (n by 25, row j is instrument
j's per-state return profile), the mandate target curve `C` (length 25) and the Regime weight vector `M`
(length 25):

    y = sum over states i of  ( sum over instruments j of  max( C[i] - M[i] * x[j] * BB[j,i], 0 ) )^2

Per regime state, sum the positive shortfall of each instrument's regime-scaled contribution below the
mandate target, square that summed shortfall, then sum across states. Minimise y.

**Three properties of this form that matter, and are easy to lose in a rewrite.**

*The shortfall is summed over instruments before squaring.* `(sum_j max(...))^2`, not
`sum_j (max(...))^2`. Squaring per instrument and then summing is a different objective with a different
optimum, and it is the mistake a careless simplification makes.

*Only the downside is penalised.* `max(., 0)` clips at zero, so exceeding the target in a state costs
nothing. This is what makes the method something other than a least-squares curve fit, and it is why the
crisis tail of the Regime cannot be smoothed away upstream: the states where the target is hardest to
meet are precisely the ones that dominate.

*Each instrument's contribution is scaled by the regime weight `M[i]`, not by a portfolio total.* The
comparison in state i is between the mandate target and `M[i] * x[j] * BB[j,i]` per instrument. A live
regime therefore reweights which states the fit is judged in.

Taken from `curveoptcalc.m` line 18. The commented `sum((C-yhold).^2)` on line 17 of that file is not the
active objective and is not implemented here.
"""

from __future__ import annotations

import numpy as np


def _validate(x: np.ndarray, bb: np.ndarray, c: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, ...]:
    weights = np.asarray(x, dtype=float).ravel()
    profiles = np.asarray(bb, dtype=float)
    target = np.asarray(c, dtype=float).ravel()
    regime = np.asarray(m, dtype=float).ravel()

    if profiles.ndim != 2:
        raise ValueError(f"BB must be two-dimensional (instruments by states), got shape {profiles.shape}")
    n, states = profiles.shape
    if weights.shape != (n,):
        raise ValueError(
            f"x has {weights.shape[0]} weights against {n} instruments in BB"
        )
    if target.shape != (states,):
        raise ValueError(
            f"the target curve has {target.shape[0]} points against {states} states in BB"
        )
    if regime.shape != (states,):
        raise ValueError(
            f"the regime vector has {regime.shape[0]} weights against {states} states in BB"
        )
    return weights, profiles, target, regime


def shortfall_by_state(
    x: np.ndarray,
    bb: np.ndarray,
    c: np.ndarray,
    m: np.ndarray,
) -> np.ndarray:
    """The summed positive shortfall per state, before squaring.

    Length 25. Reported alongside a result because it says *where* on the regime axis a portfolio fails
    to reach the mandate, which the single objective number cannot.
    """
    weights, profiles, target, regime = _validate(x, bb, c, m)
    # contribution[j, i] = M[i] * x[j] * BB[j, i]
    contribution = regime[None, :] * profiles * weights[:, None]
    return np.maximum(target[None, :] - contribution, 0.0).sum(axis=0)


def curve_objective(
    x: np.ndarray,
    bb: np.ndarray,
    c: np.ndarray,
    m: np.ndarray,
) -> float:
    """The objective value to minimise."""
    per_state = shortfall_by_state(x, bb, c, m)
    return float(np.sum(per_state ** 2))


def curve_objective_gradient(
    x: np.ndarray,
    bb: np.ndarray,
    c: np.ndarray,
    m: np.ndarray,
) -> np.ndarray:
    """The analytic gradient of the objective.

    With `S_i` the summed shortfall in state i, and the instrument-state term active where
    `C[i] - M[i] * x[j] * BB[j,i] > 0`:

        dy/dx_j = sum over i of  2 * S_i * ( -M[i] * BB[j,i] ) * active[j,i]

    Supplied rather than left to a finite-difference approximation for two reasons. The objective is
    piecewise quadratic with kinks where a term enters or leaves the active set, and a finite difference
    that straddles a kink reports a slope that belongs to neither side. And an exact gradient cuts the
    function evaluations per iteration from n+1 to one, which on a 54-instrument universe is the
    difference between a responsive cockpit and a slow one.

    At a kink the sub-gradient with the term treated as inactive is returned. The objective is convex, so
    any sub-gradient is a valid descent direction.
    """
    weights, profiles, target, regime = _validate(x, bb, c, m)
    contribution = regime[None, :] * profiles * weights[:, None]
    gap = target[None, :] - contribution
    active = gap > 0.0
    per_state = np.where(active, gap, 0.0).sum(axis=0)

    # d(term)/dx_j = -M[i] * BB[j,i] where active, else 0.
    derivative = np.where(active, -(regime[None, :] * profiles), 0.0)
    return 2.0 * (derivative * per_state[None, :]).sum(axis=1)


def achieved_curve(x: np.ndarray, bb: np.ndarray) -> np.ndarray:
    """The portfolio's own return profile: `x' BB`, length 25.

    Note that this is *not* the quantity the objective compares against the target. The objective scales
    each instrument by the regime weight per state, so the achieved curve and the target curve can differ
    while the fit is still optimal for the live regime. Reported because it is what the portfolio is
    expected to return per state, which is the question a reader of the allocation actually has.
    """
    weights = np.asarray(x, dtype=float).ravel()
    profiles = np.asarray(bb, dtype=float)
    if weights.shape[0] != profiles.shape[0]:
        raise ValueError(
            f"x has {weights.shape[0]} weights against {profiles.shape[0]} instruments in BB"
        )
    return weights @ profiles
