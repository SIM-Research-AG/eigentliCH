"""The three-body economic dynamics model (EDM).

Implements the equations of motion of section 0.2 of the build brief, which follow the
field-theoretic derivation in *Capital Saturation* chapters 7.5 to 8.1 and extend Genreith's
two-body macroeconomic field theory to three coupled bodies.

State variables, per economy:

    Y     gross domestic product, the real economy proxy (prices times volume)
    K_R   real capital
    K_I   financial capital

Net capital is K = K_R + K_I. The debt side and the capital side are identities in a fractional
money system: one agent's asset and return claim is another's debt and interest payment. The model
therefore treats them as interchangeable, which is what licenses assembling K_I from credit
aggregates (see macrofield/data/loaders.py, where K_I is built).

Equations of motion:

    Y_dot   = (p_b - p_s) Y + K_R_dot - p_p K_R + S
    K_R_dot = (1 - alpha) p_s Y + p_p K_R + r K_I
    K_I_dot = alpha p_s Y + p_p K_I - r K_I + S

with

    r     = 1 - K_R / Y                  investment share, financial into real
    alpha = (1 / p_s) (Y_dot / Y)        share of the savings rate flowing to financial capital
    p_p   = Y_dot / K_R + K_R_dot / K_R  achievable return on capital
    p_b   = (Y_dot + K_R_dot) / K_I_dot  wage versus capital income, tracks population growth

p_s is the savings rate. S is the exogenous stimulus injection, attributed to financial capital
because it is normally financed by new debt (fiscal deficit, central-bank balance-sheet expansion,
or net new credit).

Two structural properties of this system are documented in docs/MODEL_SPEC.md and are load-bearing
for calibration. Both are consequences of the equations, not implementation choices:

1. Summing the two capital equations gives K_R_dot + K_I_dot = p_s Y + p_p K + S exactly. Genreith's
   unmodified two-body reduction, K_dot = p_s Y + p_p K, is therefore recovered only where S = 0.
   See two_body_residual and genreith_residual below.

2. The four definitions above over-determine the three equations of motion. Imposing the p_p
   definition on the Y equation collapses it to Y_dot = ((p_b - p_s) Y + S) / 2, and imposing the
   alpha definition forces alpha p_s Y = Y_dot identically. The two closure modes this implies are
   exposed as ClosureMode below, and the identity residuals are reported as diagnostics rather than
   assumed away.
"""

from __future__ import annotations

import enum
import warnings
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
from scipy.integrate import solve_ivp

#: Index of each state variable in the state vector.
IDX_Y, IDX_KR, IDX_KI = 0, 1, 2

#: Names of the state variables, in state-vector order.
STATE_NAMES = ("Y", "K_R", "K_I")

#: A parameter is either a constant or a function of time.
ParamPath = float | Callable[[float], float]


class ClosureMode(enum.Enum):
    """How the over-determination of section 0.2 is resolved.

    See docs/MODEL_SPEC.md section 2 and the module docstring, property 2.
    """

    #: Integrate the three equations as written, with p_b, p_p, alpha, p_s and S supplied as
    #: exogenous paths (from data identities or from calibration). The four definitions then hold
    #: only to the extent that the supplied paths are mutually consistent, and the residuals are
    #: reported as diagnostics. This is the default because it is what the brief specifies.
    AS_WRITTEN = "as_written"

    #: Substitute the p_p definition into the Y equation, which reduces it to
    #: Y_dot = ((p_b - p_s) Y + S) / 2. Note carefully what this does and does not achieve: it makes
    #: the Y equation consistent with the p_p definition, but it does not make the supplied p_p
    #: satisfy that definition, because p_p cancels out of the joint system (see
    #: p_p_identity_implied_y_dot). Provided as a consistency reduction, not as the model of record.
    IDENTITY_CLOSED = "identity_closed"


def _evaluate(param: ParamPath, t: float) -> float:
    """Evaluate a parameter that may be a constant or a callable of time."""
    return float(param(t)) if callable(param) else float(param)


@dataclass
class EDMParameters:
    """Parameters of the three-body system.

    Each parameter may be a constant or a callable of time, so that paths estimated from data
    (p_p, p_b, alpha) and fitted paths (p_s, S) can be mixed freely.

    Attributes:
        p_s: Savings rate. Taken from data (gross national savings rate) or fitted.
        p_p: Achievable return on capital. An identity from data per section 0.2.
        p_b: Wage versus capital income ratio. An identity from data per section 0.2.
        alpha: Share of the savings rate flowing to financial capital. An identity from data.
        stimulus: The exogenous injection S. Attributed to financial capital.
        endogenous_r: If true (the default) r is computed from the state as 1 - K_R / Y at each
            step, which is exact because r is a pure function of the state. If false, r is taken
            from the r_path parameter, which is then required.
        r_path: An exogenous path for r, used only when endogenous_r is false.
    """

    p_s: ParamPath
    p_p: ParamPath
    p_b: ParamPath
    alpha: ParamPath
    stimulus: ParamPath = 0.0
    endogenous_r: bool = True
    r_path: ParamPath | None = None

    def __post_init__(self) -> None:
        if not self.endogenous_r and self.r_path is None:
            raise ValueError(
                "r_path is required when endogenous_r is false. r = 1 - K_R / Y is a pure "
                "function of the state, so the endogenous form is preferred unless you are "
                "deliberately overriding it with an observed series."
            )

    def at(self, t: float) -> "EDMParametersAt":
        """Evaluate every parameter at time t."""
        return EDMParametersAt(
            p_s=_evaluate(self.p_s, t),
            p_p=_evaluate(self.p_p, t),
            p_b=_evaluate(self.p_b, t),
            alpha=_evaluate(self.alpha, t),
            stimulus=_evaluate(self.stimulus, t),
        )


@dataclass(frozen=True)
class EDMParametersAt:
    """Parameter values at a single instant."""

    p_s: float
    p_p: float
    p_b: float
    alpha: float
    stimulus: float


def investment_share(state: Sequence[float]) -> float:
    """Return r = 1 - K_R / Y, the share of financial capital flowing into real capital.

    A pure function of the state, per section 0.2.
    """
    y, k_r = float(state[IDX_Y]), float(state[IDX_KR])
    if y == 0.0:
        raise ZeroDivisionError("r = 1 - K_R / Y is undefined at Y = 0")
    return 1.0 - k_r / y


def derivatives(
    t: float,
    state: Sequence[float],
    params: EDMParameters,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
) -> np.ndarray:
    """Return the derivative vector (Y_dot, K_R_dot, K_I_dot) at time t.

    This is the right-hand side passed to the integrator. It is written to be safe to call at
    arbitrary t and state, because a stiff solver will probe both.

    Args:
        t: Time, in the units of the calibration window (years).
        state: The state vector (Y, K_R, K_I).
        params: The parameters, evaluated at t internally.
        closure: How to resolve the over-determination of section 0.2.

    Returns:
        The derivative vector as a length-3 array, ordered (Y, K_R, K_I).
    """
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    p = params.at(t)
    r = investment_share(state) if params.endogenous_r else _evaluate(params.r_path, t)

    # The two capital equations are unaffected by the closure mode: nothing in them refers to
    # Y_dot, so they can be evaluated directly.
    k_r_dot = (1.0 - p.alpha) * p.p_s * y + p.p_p * k_r + r * k_i
    k_i_dot = p.alpha * p.p_s * y + p.p_p * k_i - r * k_i + p.stimulus

    if closure is ClosureMode.AS_WRITTEN:
        y_dot = (p.p_b - p.p_s) * y + k_r_dot - p.p_p * k_r + p.stimulus
    elif closure is ClosureMode.IDENTITY_CLOSED:
        # Imposing p_p = (Y_dot + K_R_dot) / K_R in the Y equation gives p_p K_R = Y_dot + K_R_dot,
        # so Y_dot = (p_b - p_s) Y + K_R_dot - (Y_dot + K_R_dot) + S, hence 2 Y_dot = (p_b - p_s) Y + S.
        y_dot = 0.5 * ((p.p_b - p.p_s) * y + p.stimulus)
    else:  # pragma: no cover - enum is exhaustive
        raise ValueError(f"unknown closure mode: {closure!r}")

    return np.array([y_dot, k_r_dot, k_i_dot], dtype=float)


def p_p_identity_implied_y_dot(
    t: float,
    state: Sequence[float],
    params: EDMParameters,
) -> float:
    """Return the output growth that the p_p definition and the K_R equation jointly imply.

    This function exists to make an over-determination explicit rather than leave it to be
    discovered during calibration. The p_p definition of section 0.2 is

        p_p K_R = Y_dot + K_R_dot

    and the real-capital equation of motion is

        K_R_dot = (1 - alpha) p_s Y + p_p K_R + r K_I

    Substituting the second into the first cancels p_p entirely and leaves

        Y_dot = - [ (1 - alpha) p_s Y + r K_I ]

    So the p_p definition is not a statement about p_p at all once the equation of motion is
    imposed. It is a constraint linking output growth to the savings flow and the investment flow,
    and no choice of p_p can satisfy or violate it.

    The constraint has a substantive consequence. For a production economy, where K_R / Y < 1 and
    therefore r > 0, every term on the right is positive, so the constraint forces Y_dot < 0. The
    p_p identity is thus compatible with a growing production economy only where r < 0, that is
    where K_R > Y, which section 0.5 calls a financial economy. Calibration must therefore treat the
    p_p definition as a diagnostic to be reported rather than a constraint to be enforced, which is
    what calibration/fit.py does.

    Returns:
        The implied Y_dot. Compare against the simulated Y_dot to size the inconsistency.
    """
    y, k_i = float(state[IDX_Y]), float(state[IDX_KI])
    p = params.at(t)
    r = investment_share(state) if params.endogenous_r else _evaluate(params.r_path, t)
    return -((1.0 - p.alpha) * p.p_s * y + r * k_i)


def two_body_residual(
    t: float,
    state: Sequence[float],
    params: EDMParameters,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
) -> float:
    """Return the residual of the stimulus-inclusive two-body identity.

    The identity is K_R_dot + K_I_dot = p_s Y + p_p K + S with K = K_R + K_I, which follows
    algebraically from the two capital equations. The residual is zero by construction, so a
    non-zero value indicates an implementation error or integrator drift, not a modelling question.

    See docs/MODEL_SPEC.md section 2.
    """
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    p = params.at(t)
    d = derivatives(t, state, params, closure)
    capital_flow = d[IDX_KR] + d[IDX_KI]
    return capital_flow - (p.p_s * y + p.p_p * (k_r + k_i) + p.stimulus)


def genreith_residual(
    t: float,
    state: Sequence[float],
    params: EDMParameters,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
) -> float:
    """Return the residual against Genreith's unmodified two-body equation.

    The reduction is K_dot = p_s Y + p_p K with K = K_R + K_I, and it recovers Genreith exactly
    only where the stimulus vanishes. The residual therefore equals S, which is the consistency
    check of section 0.3 read literally. A run with a live stimulus path will show a residual of
    exactly S, and that is the model behaving correctly, not a failure.

    See docs/MODEL_SPEC.md section 2.
    """
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    p = params.at(t)
    d = derivatives(t, state, params, closure)
    capital_flow = d[IDX_KR] + d[IDX_KI]
    return capital_flow - (p.p_s * y + p.p_p * (k_r + k_i))


def identity_residuals(
    t: float,
    state: Sequence[float],
    params: EDMParameters,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
) -> dict[str, float]:
    """Return the residual of each definition in section 0.2, as a diagnostic.

    Under ClosureMode.AS_WRITTEN the supplied p_p, p_b and alpha paths come from data and need not
    be exactly consistent with the simulated derivatives. These residuals quantify that
    inconsistency, and the calibration report surfaces them. Under IDENTITY_CLOSED the p_p and
    alpha residuals vanish by construction.

    Residuals are returned in the units of the defined quantity, so they are directly comparable to
    the parameter values themselves.
    """
    y, k_r, k_i = (float(state[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    p = params.at(t)
    d = derivatives(t, state, params, closure)
    y_dot, k_r_dot, k_i_dot = d[IDX_Y], d[IDX_KR], d[IDX_KI]

    residuals: dict[str, float] = {}

    # p_p = Y_dot / K_R + K_R_dot / K_R
    if k_r != 0.0:
        residuals["p_p"] = p.p_p - (y_dot + k_r_dot) / k_r
    else:
        residuals["p_p"] = float("nan")

    # p_b = (Y_dot + K_R_dot) / K_I_dot
    if k_i_dot != 0.0:
        residuals["p_b"] = p.p_b - (y_dot + k_r_dot) / k_i_dot
    else:
        residuals["p_b"] = float("nan")

    # alpha = (1 / p_s) (Y_dot / Y)
    if p.p_s != 0.0 and y != 0.0:
        residuals["alpha"] = p.alpha - (1.0 / p.p_s) * (y_dot / y)
    else:
        residuals["alpha"] = float("nan")

    # r = 1 - K_R / Y, exact when endogenous.
    if params.endogenous_r:
        residuals["r"] = 0.0
    else:
        residuals["r"] = _evaluate(params.r_path, t) - investment_share(state)

    return residuals


@dataclass
class SimulationResult:
    """The outcome of a simulation run.

    Attributes:
        t: Times at which the solution was evaluated, in years.
        Y: The GDP path.
        K_R: The real capital path.
        K_I: The financial capital path.
        two_body_residual: The stimulus-inclusive identity residual at each step. Zero by
            construction, so it measures integrator drift and implementation error.
        genreith_residual: The residual against Genreith's unmodified reduction at each step. Equal
            to the stimulus path S.
        closure: The closure mode used.
        success: Whether the integrator reported success.
        message: The integrator's status message.
        max_abs_two_body_residual: Convenience summary, the worst absolute two-body residual,
            normalised by the scale of the capital flow so that it is comparable across economies.
    """

    t: np.ndarray
    Y: np.ndarray
    K_R: np.ndarray
    K_I: np.ndarray
    two_body_residual: np.ndarray
    genreith_residual: np.ndarray
    closure: ClosureMode
    success: bool
    message: str
    max_abs_two_body_residual: float = field(default=0.0)

    @property
    def K(self) -> np.ndarray:
        """Net capital, K = K_R + K_I."""
        return self.K_R + self.K_I

    @property
    def capital_saturation(self) -> np.ndarray:
        """Total capital over GDP, the quantity HoNI expresses as a percentage."""
        return self.K / self.Y

    def as_dict(self) -> dict[str, np.ndarray]:
        """Return the state paths keyed by name, for export."""
        return {"t": self.t, "Y": self.Y, "K_R": self.K_R, "K_I": self.K_I}


def simulate(
    initial_state: Sequence[float],
    params: EDMParameters,
    t_span: tuple[float, float],
    t_eval: np.ndarray | None = None,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
    method: str = "Radau",
    rtol: float = 1e-8,
    atol: float = 1e-10,
    residual_tolerance: float = 1e-6,
    warn_on_residual: bool = True,
) -> SimulationResult:
    """Integrate the three-body system over t_span.

    A stiff-capable implicit method is the default because Phase IV dynamics stiffen: once
    K_R / K_I falls below one the financial-capital equation self-reinforces and explicit methods
    lose their step size.

    Args:
        initial_state: The initial (Y, K_R, K_I).
        params: The parameters.
        t_span: The (start, end) of the integration, in years.
        t_eval: Times at which to report the solution. Defaults to the integrator's own steps.
        closure: How to resolve the over-determination of section 0.2.
        method: A scipy.integrate.solve_ivp method. Radau and BDF are both stiff-capable.
        rtol: Relative tolerance passed to the integrator.
        atol: Absolute tolerance passed to the integrator.
        residual_tolerance: The relative tolerance above which the two-body residual is reported as
            a breach. Compared against the residual normalised by the capital flow scale.
        warn_on_residual: Whether to emit a warning when the residual tolerance is breached. The
            brief requires a runtime warning rather than a hard failure, so that a run producing
            diagnostics is not lost to an assertion.

    Returns:
        The simulation result, including the residual paths.

    Raises:
        ValueError: If the initial state is not strictly positive, since Y = 0 makes r undefined
            and the ratios that drive every diagnostic are meaningless at zero.
    """
    initial = np.asarray(initial_state, dtype=float)
    if initial.shape != (3,):
        raise ValueError(f"initial_state must have three elements (Y, K_R, K_I), got {initial.shape}")
    if not np.all(initial > 0.0):
        raise ValueError(
            "initial_state must be strictly positive. r = 1 - K_R / Y is undefined at Y = 0 and "
            "the capital ratios that drive the phase classifier are meaningless at zero."
        )

    solution = solve_ivp(
        fun=lambda t, s: derivatives(t, s, params, closure),
        t_span=t_span,
        y0=initial,
        t_eval=t_eval,
        method=method,
        rtol=rtol,
        atol=atol,
        dense_output=False,
    )

    two_body = np.array(
        [two_body_residual(t, solution.y[:, i], params, closure) for i, t in enumerate(solution.t)]
    )
    genreith = np.array(
        [genreith_residual(t, solution.y[:, i], params, closure) for i, t in enumerate(solution.t)]
    )

    # Normalise the residual by the scale of the capital flow so the tolerance means the same thing
    # for a large and a small economy.
    scale = np.maximum(np.abs(solution.y[IDX_KR] + solution.y[IDX_KI]), 1.0)
    normalised = np.abs(two_body) / scale
    worst = float(np.max(normalised)) if normalised.size else 0.0

    if worst > residual_tolerance and warn_on_residual:
        warnings.warn(
            f"two-body identity residual reached {worst:.3e} relative, above the tolerance of "
            f"{residual_tolerance:.3e}. The identity is exact algebraically, so this indicates "
            f"integrator drift or an inconsistent parameterisation, and the run should be treated "
            f"as unreliable.",
            RuntimeWarning,
            stacklevel=2,
        )

    return SimulationResult(
        t=solution.t,
        Y=solution.y[IDX_Y],
        K_R=solution.y[IDX_KR],
        K_I=solution.y[IDX_KI],
        two_body_residual=two_body,
        genreith_residual=genreith,
        closure=closure,
        success=bool(solution.success),
        message=str(solution.message),
        max_abs_two_body_residual=worst,
    )


#: Tolerance within which the balanced-growth preconditions must hold.
BALANCED_GROWTH_TOLERANCE = 1e-9


def balanced_growth_solution(
    initial_state: Sequence[float],
    p_p: float,
    t: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return the exact analytic solution on the balanced-growth ray of the three-body system.

    The system admits a closed-form solution under three conditions, which together make every
    ratio constant so that r does not drift:

    1. Zero stimulus, S = 0.
    2. A negligible savings flow, p_s -> 0, so that the p_s Y terms vanish.
    3. K_R = Y at the initial state, so that r = 1 - K_R / Y = 0, and p_b = p_p, so that Y and K_R
       grow at the same rate and r therefore stays at zero.

    Under these conditions the equations of motion reduce to

        K_R_dot = p_p K_R
        K_I_dot = p_p K_I          (the r K_I exchange term vanishes with r = 0)
        Y_dot   = p_b Y = p_p Y    (the K_R_dot and p_p K_R terms cancel)

    so all three state variables, and therefore net capital, grow as exp(p_p t). This is the
    exponential solution the source derives, and it is the limiting case the brief asks to be tested
    in section 7.

    The conditions matter. Without them the system does not admit balanced growth at moderate rates,
    because the exchange term r K_I is large whenever an economy carries substantial financial
    capital: at K_I = 2 Y and r = 0.1 it directs 20 percent of GDP into real capital each year,
    which forces real capital growth far above any plausible steady rate and drives K_R / Y through
    one. Past that crossing r changes sign, the exchange reverses, and the system reaches a
    finite-time singularity. That behaviour is a property of the unbounded r, and it is why
    calibration constrains the parameter paths jointly rather than sampling them independently.

    Args:
        initial_state: The initial (Y, K_R, K_I), which must satisfy K_R = Y.
        p_p: The return on capital, which sets the common exponential rate.
        t: The times at which to evaluate.

    Returns:
        A mapping with the analytic Y, K_R, K_I and K paths at the requested times.

    Raises:
        ValueError: If the initial state is off the balanced-growth ray.
    """
    initial = np.asarray(initial_state, dtype=float)
    y0, k_r0, k_i0 = (float(initial[i]) for i in (IDX_Y, IDX_KR, IDX_KI))
    if abs(k_r0 - y0) > BALANCED_GROWTH_TOLERANCE * max(abs(y0), 1.0):
        raise ValueError(
            f"balanced growth requires K_R = Y at the initial state so that r = 0, got "
            f"K_R = {k_r0} and Y = {y0}"
        )
    growth = np.exp(p_p * (np.asarray(t, dtype=float) - float(t[0])))
    return {
        "Y": y0 * growth,
        "K_R": k_r0 * growth,
        "K_I": k_i0 * growth,
        "K": (k_r0 + k_i0) * growth,
    }
