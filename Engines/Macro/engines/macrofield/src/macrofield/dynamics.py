"""The three-body equations of motion. Pure.

State, per economy: Y (output), K_R (real capital), K_I (financial capital). Net capital is
K = K_R + K_I. The system (brief section 0.2, *Capital Saturation* chapters 7.5 to 8.1):

    Y_dot   = (p_b - p_s) Y + K_R_dot - p_p K_R + S
    K_R_dot = (1 - alpha) p_s Y + p_p K_R + r K_I
    K_I_dot = alpha p_s Y + p_p K_I - r K_I + S

    r = 1 - K_R / Y    investment share, financial into real; a pure function of the state

p_s is the savings rate, p_p the achievable return on capital, p_b tracks population growth,
alpha is the share of savings flowing to financial capital, S the exogenous stimulus, which
enters financial capital because it is normally debt financed.

Two structural facts shape everything downstream and are reported, not hidden:

1. Summing the capital equations gives K_R_dot + K_I_dot = p_s Y + p_p K + S exactly, so
   Genreith's two-body form K_dot = p_s Y + p_p K holds only where S = 0. The residual against
   the stimulus-inclusive identity is zero by construction (a non-zero value is integrator
   drift); the residual against Genreith equals S.
2. The four definitions of r, alpha, p_p and p_b over-determine the three equations. Imposing
   the p_p definition on the Y equation collapses it to Y_dot = ((p_b - p_s) Y + S) / 2, which is
   the ``identity_closed`` mode. ``as_written`` integrates the equations with the parameter paths
   supplied and reports the definitions' residuals as diagnostics.

3. The finite-time singularity (TB-08, TB-27). Y_dot - K_R_dot = (p_b - p_s) Y - p_p K_R + S, so
   real capital outgrows output whenever p_p + p_s > p_b + S / Y, which holds in every economy:
   K_R passes Y within a few projected years. Past that point r = 1 - K_R/Y is negative and
   unbounded, the flow r K_I drains output, a falling Y makes r more negative still, and Y
   reaches zero in finite time while K_I explodes. Every projection that stopped short of its
   horizon under calibrations up to 1.4.0 stopped there (K_R/Y above 1e5 at the last step), and
   so did the six fits that did not integrate over their window.

   ``share="bounded"`` (calibration 1.5.0) uses r = max(0, 1 - K_R/Y): the written definition
   wherever K_R <= Y, and no reversal past it (financial capital stops flowing into real capital
   once real capital has reached output: real investment saturates). With 0 <= r <= 1 the
   right-hand side grows at most linearly in the state, so a solution exists over every horizon
   for every parameter value; with alpha in [0, 1] and S >= 0 the positive orthant is invariant
   as well (Y_dot >= 0 at Y = 0, K_R_dot >= 0 at K_R = 0, K_I_dot >= 0 at K_I = 0). Both are
   property-tested (tests/test_integrability.py).

The arithmetic follows ``Macro_Model/macrofield/model/edm.py`` operation for operation, so a
simulation with the share as written reproduces the golden reference bit for bit on the same
numerical stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Sequence

import numpy as np
from scipy.integrate import solve_ivp

Closure = Literal["as_written", "identity_closed"]
#: The investment share: as written (unbounded below) or bounded at zero (TB-27).
Share = Literal["as_written", "bounded"]
ParamPath = Callable[[float], float]

IDX_Y, IDX_KR, IDX_KI = 0, 1, 2


@dataclass(frozen=True)
class Parameters:
    """Parameter paths, each a callable of time in years from the window start."""

    p_s: ParamPath
    p_p: ParamPath
    p_b: ParamPath
    alpha: ParamPath
    stimulus: ParamPath


def investment_share(y: float, k_r: float, share: Share = "as_written") -> float:
    if y == 0.0:
        raise ZeroDivisionError("r = 1 - K_R / Y is undefined at Y = 0")
    r = 1.0 - k_r / y
    if share == "bounded" and r < 0.0:
        return 0.0
    return r


def derivatives(t: float, state: Sequence[float], params: Parameters,
                closure: Closure = "as_written", share: Share = "as_written") -> np.ndarray:
    """(Y_dot, K_R_dot, K_I_dot) at time t. Safe at any t and state a stiff solver probes."""
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    p_s, p_p, p_b = float(params.p_s(t)), float(params.p_p(t)), float(params.p_b(t))
    alpha, stimulus = float(params.alpha(t)), float(params.stimulus(t))
    r = investment_share(y, k_r, share)

    k_r_dot = (1.0 - alpha) * p_s * y + p_p * k_r + r * k_i
    k_i_dot = alpha * p_s * y + p_p * k_i - r * k_i + stimulus
    if closure == "as_written":
        y_dot = (p_b - p_s) * y + k_r_dot - p_p * k_r + stimulus
    elif closure == "identity_closed":
        y_dot = 0.5 * ((p_b - p_s) * y + stimulus)
    else:  # pragma: no cover - Literal is exhaustive
        raise ValueError(f"unknown closure {closure!r}")
    return np.array([y_dot, k_r_dot, k_i_dot], dtype=float)


def two_body_residual(t: float, state: Sequence[float], params: Parameters,
                      closure: Closure = "as_written", share: Share = "as_written") -> float:
    """K_R_dot + K_I_dot - (p_s Y + p_p K + S). Zero by construction, for either share."""
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    d = derivatives(t, state, params, closure, share)
    flow = d[IDX_KR] + d[IDX_KI]
    return flow - (float(params.p_s(t)) * y + float(params.p_p(t)) * (k_r + k_i)
                   + float(params.stimulus(t)))


def genreith_residual(t: float, state: Sequence[float], params: Parameters,
                      closure: Closure = "as_written", share: Share = "as_written") -> float:
    """K_dot - (p_s Y + p_p K). Equals S: Genreith is recovered only without stimulus."""
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    d = derivatives(t, state, params, closure, share)
    flow = d[IDX_KR] + d[IDX_KI]
    return flow - (float(params.p_s(t)) * y + float(params.p_p(t)) * (k_r + k_i))


def p_p_implied_output_growth(t: float, state: Sequence[float], params: Parameters,
                              share: Share = "as_written") -> float:
    """The Y_dot that the p_p definition and the K_R equation jointly force.

    Substituting K_R_dot = (1 - alpha) p_s Y + p_p K_R + r K_I into p_p K_R = Y_dot + K_R_dot
    cancels p_p and leaves Y_dot = -[(1 - alpha) p_s Y + r K_I], negative for any production
    economy (r > 0). That is why the p_p definition is a diagnostic here, never a constraint.
    """
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    r = investment_share(y, k_r, share)
    return -((1.0 - float(params.alpha(t))) * float(params.p_s(t)) * y + r * k_i)


def identity_residuals(t: float, state: Sequence[float], params: Parameters,
                       closure: Closure = "as_written",
                       share: Share = "as_written") -> dict[str, float]:
    """Residual of each section 0.2 definition, in the units of the defined quantity. ``r`` is
    the bounded share's departure from the definition (zero as written and wherever K_R <= Y)."""
    y, k_r, _ = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    d = derivatives(t, state, params, closure, share)
    y_dot, k_r_dot, k_i_dot = d[IDX_Y], d[IDX_KR], d[IDX_KI]
    p_s = float(params.p_s(t))
    nan = float("nan")
    return {
        "p_p": float(params.p_p(t)) - (y_dot + k_r_dot) / k_r if k_r != 0.0 else nan,
        "p_b": float(params.p_b(t)) - (y_dot + k_r_dot) / k_i_dot if k_i_dot != 0.0 else nan,
        "alpha": (float(params.alpha(t)) - (1.0 / p_s) * (y_dot / y)
                  if p_s != 0.0 and y != 0.0 else nan),
        "r": (investment_share(y, k_r, share) - investment_share(y, k_r)
              if share == "bounded" else 0.0),
    }


@dataclass(frozen=True)
class Simulation:
    t: np.ndarray
    Y: np.ndarray
    K_R: np.ndarray
    K_I: np.ndarray
    success: bool
    message: str
    #: Worst |two-body residual| over the path, relative to max(|K_R + K_I|, 1).
    two_body_worst_relative: float
    genreith_residual: np.ndarray

    @property
    def reached(self) -> int:
        return int(self.t.shape[0])


def simulate(initial_state: Sequence[float], params: Parameters, t_span: tuple[float, float],
             t_eval: np.ndarray, closure: Closure = "as_written", method: str = "Radau",
             rtol: float = 1e-8, atol: float = 1e-10, share: Share = "as_written") -> Simulation:
    """Integrate over ``t_span``. A stiff method by default: Phase IV dynamics stiffen."""
    initial = np.asarray(initial_state, dtype=float)
    if initial.shape != (3,):
        raise ValueError(f"initial_state must be (Y, K_R, K_I), got shape {initial.shape}")
    if not np.all(initial > 0.0):
        raise ValueError("initial_state must be strictly positive: r is undefined at Y = 0")

    solution = solve_ivp(
        fun=lambda t, s: derivatives(t, s, params, closure, share),
        t_span=t_span, y0=initial, t_eval=t_eval, method=method, rtol=rtol, atol=atol,
        dense_output=False,
    )
    two_body = np.array([two_body_residual(t, solution.y[:, i], params, closure, share)
                         for i, t in enumerate(solution.t)])
    genreith = np.array([genreith_residual(t, solution.y[:, i], params, closure, share)
                         for i, t in enumerate(solution.t)])
    scale = np.maximum(np.abs(solution.y[IDX_KR] + solution.y[IDX_KI]), 1.0)
    normalised = np.abs(two_body) / scale
    return Simulation(
        t=solution.t, Y=solution.y[IDX_Y], K_R=solution.y[IDX_KR], K_I=solution.y[IDX_KI],
        success=bool(solution.success), message=str(solution.message),
        two_body_worst_relative=float(np.max(normalised)) if normalised.size else 0.0,
        genreith_residual=genreith,
    )


def balanced_growth_solution(initial_state: Sequence[float], p_p: float,
                             t: np.ndarray) -> dict[str, np.ndarray]:
    """Closed form on the balanced-growth ray: every state grows as exp(p_p t).

    Holds when S = 0, p_s -> 0, K_R = Y initially (so r = 0) and p_b = p_p (so r stays 0).
    The limiting case the test suite integrates against.
    """
    y0, k_r0, k_i0 = (float(v) for v in initial_state)
    if abs(k_r0 - y0) > 1e-9 * max(abs(y0), 1.0):
        raise ValueError("balanced growth needs K_R = Y at the initial state")
    growth = np.exp(p_p * (np.asarray(t, dtype=float) - float(t[0])))
    return {"Y": y0 * growth, "K_R": k_r0 * growth, "K_I": k_i0 * growth}
