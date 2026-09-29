"""The objective: asymmetric squared shortfall, summed over instruments before squaring. Pure.

For weights ``x`` (n), instrument profiles ``BB`` (n by 25), the mandate's target curve ``C`` (25) and the
regime distribution ``M`` (25)::

    y = sum over states i of ( sum over instruments j of max( C[i] - M[i] * x[j] * BB[j, i], 0 ) )^2

The form of the draft and of ``curveoptcalc.m`` line 18, chosen by the owner on 28.09.2026 (PCP-03). Three
properties that a rewrite easily loses:

* the shortfall is summed over instruments *before* squaring, not squared per instrument;
* only the downside counts: exceeding the target in a state costs nothing, so the crisis tail of the
  Regime dominates and must not be smoothed upstream;
* each instrument's contribution is scaled by the regime weight of the state, not compared as a portfolio
  total. A zero-weight instrument therefore still contributes its full target to every state where the
  target is positive: the objective has a floor that grows with the universe (draft D28), reported on every
  Allocation as ``objective_floor`` and ``weight_leverage``.

The gradient is exact, not numerical (Manual section 15.2): at a kink, the sub-gradient with the term
treated as inactive. ``profile_scale`` multiplies every profile value inside the objective (calibration).
"""

from __future__ import annotations

import numpy as np


def _arrays(x, bb, c, m, scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    weights = np.asarray(x, dtype=float).ravel()
    profiles = np.asarray(bb, dtype=float) * float(scale)
    target = np.asarray(c, dtype=float).ravel()
    regime = np.asarray(m, dtype=float).ravel()
    n, states = profiles.shape
    if weights.shape != (n,) or target.shape != (states,) or regime.shape != (states,):
        raise ValueError(f"shapes do not agree: x {weights.shape}, BB {profiles.shape}, C {target.shape}, "
                         f"M {regime.shape}")
    return weights, profiles, target, regime


def shortfall_by_state(x, bb, c, m, scale: float = 1.0) -> np.ndarray:
    """Per state, the summed positive shortfall before squaring (length 25)."""
    weights, profiles, target, regime = _arrays(x, bb, c, m, scale)
    contribution = regime[None, :] * profiles * weights[:, None]
    return np.maximum(target[None, :] - contribution, 0.0).sum(axis=0)


def objective(x, bb, c, m, scale: float = 1.0) -> float:
    return float(np.sum(shortfall_by_state(x, bb, c, m, scale) ** 2))


def gradient(x, bb, c, m, scale: float = 1.0) -> np.ndarray:
    """``dy/dx_j = sum_i 2 S_i (-M_i BB_ji) [term active]``, the inactive sub-gradient at a kink."""
    weights, profiles, target, regime = _arrays(x, bb, c, m, scale)
    contribution = regime[None, :] * profiles * weights[:, None]
    gap = target[None, :] - contribution
    active = gap > 0.0
    per_state = np.where(active, gap, 0.0).sum(axis=0)
    derivative = np.where(active, -(regime[None, :] * profiles), 0.0)
    return 2.0 * (derivative * per_state[None, :]).sum(axis=1)


def floor(bb, c, m, scale: float = 1.0) -> float:
    """The objective with nothing allocated: the part no weighting can reach (draft D28)."""
    profiles = np.asarray(bb, dtype=float)
    return objective(np.zeros(profiles.shape[0]), profiles, c, m, scale)


def achieved_curve(x, bb) -> np.ndarray:
    """``x'BB``, what the portfolio returns per state. Not the quantity the objective compares."""
    return np.asarray(x, dtype=float).ravel() @ np.asarray(bb, dtype=float)
