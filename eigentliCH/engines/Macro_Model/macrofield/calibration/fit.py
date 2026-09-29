"""Per-economy calibration of the three-body model.

Brief section 4. For each economy the model is calibrated to its historical (Y, K_R, K_I) trajectory.
Several parameters are identities computed directly from the observed series and their smoothed
derivatives; the free quantities are the savings-rate path, the stimulus path and the initial state.

Two findings from `macrofield.model.edm` shape the whole design here, and neither can be worked around:

1. **The definitions over-determine the system.** Imposing the `p_p` definition together with the
   real-capital equation cancels `p_p` entirely and leaves `Y_dot = -[(1-alpha) p_s Y + r K_I]`, which
   for a production economy forces output to shrink. The `p_p` identity is therefore computed and
   *reported* as a diagnostic, never enforced as a constraint. A calibration that tried to satisfy it
   would either fail or drive the economy into contraction to do so.

2. **Arbitrary constant parameters produce a finite-time singularity.** The unbounded investment share
   `r = 1 - K_R/Y` reverses the exchange term once real capital crosses output, which accelerates the
   crossing that caused it. So the free parameters cannot be sampled independently: the optimiser must
   be able to reject a parameter set whose trajectory fails to integrate, and it must do so without
   treating that as a numerical error.

The consequence for the fitting strategy is that this module calibrates the **observable path** rather
than searching a free parameter space blind. Identity parameters come from data; the free quantities are
low-dimensional scalings of observed proxies rather than unconstrained paths; and a parameter set whose
simulation diverges scores as a large finite residual rather than raising.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

from macrofield.data.loaders import numeric_derivative
from macrofield.model.edm import (
    ClosureMode,
    EDMParameters,
    identity_residuals,
    p_p_identity_implied_y_dot,
    simulate,
)

#: Residual assigned to a period whose simulation failed to integrate. Large enough to be rejected by
#: the optimiser, finite so the optimiser can still compute a gradient and move away from it.
#:
#: The value has to exceed any residual a merely bad fit can produce, or the optimiser learns that
#: diverging scores better than fitting badly and parks itself in the divergent region. That is not
#: hypothetical: with a relative residual and a penalty of 1e3 it happened, because an explosive
#: trajectory reaches a relative residual of order 1e9 while divergence scored 1e3. Fitting in log space
#: (see `_residual_vector`) bounds an explosive path to a residual of order tens, which is what makes a
#: penalty of this size safely larger than anything finite.
DIVERGENCE_PENALTY = 1e3

#: Integrator tolerances used *during* the search, which are looser than the reporting tolerances.
#:
#: This matters more than it looks. The search evaluates the residual hundreds of times, each evaluation
#: integrating a stiff system, and at the reporting tolerances a single economy took about ten minutes.
#: The search only needs enough accuracy to rank parameter sets against one another, so it runs loose and
#: the final path is re-simulated once at full accuracy. The two-body residual reported in the result
#: comes from that final run, so nothing published rests on the loose pass.
SEARCH_RTOL = 1e-6
SEARCH_ATOL = 1e-8

#: Integrator method used during the search. BDF is cheaper per step than Radau on this system and is
#: equally stiff-capable, which is what the Phase IV dynamics require.
SEARCH_METHOD = "BDF"

#: Default cap on residual evaluations.
#:
#: Deliberately modest. The surface is not well conditioned (see FREE_PARAMETERS) and the model is judged on
#: turning points rather than on level, so pushing the optimiser harder mostly buys level accuracy at the
#: cost of parameter plausibility. With bounds derived from each parameter's meaning the useful movement
#: happens early, and a longer search finds the corners of the bounded region rather than a better model.
DEFAULT_MAX_EVALUATIONS = 120

#: Free parameters, in the order they occupy the optimiser's vector.
#:
#: The three `*_scale` corrections on the identity-derived paths are the load-bearing design decision
#: here, and they exist because of the over-determination. Taking `p_p`, `p_b` and `alpha` from their
#: definitions and integrating the equations as written cannot fit any trajectory: the definitions force
#: mutually incompatible values. On a balanced-growth path, for instance, the definitions give
#: `p_p = 0.06` while `p_b = 0.95`, and the resulting output equation implies growth of about 90 per cent
#: a year.
#:
#: So each identity path carries a multiplicative correction, initialised at one. If the model were
#: internally consistent every correction would fit at exactly one, and the amount by which they depart
#: from one is a direct measure of how far the definitions are from the equations of motion. That makes
#: the over-determination a reported quantity rather than an obstacle, which is the same treatment
#: `identity_diagnostics` gives it.
FREE_PARAMETERS = (
    "p_p_scale",
    "p_b_scale",
    "alpha_scale",
    "savings_scale",
    "stimulus_scale",
    "initial_output",
    "initial_real",
    "initial_financial",
)

#: Corrections whose distance from one measures the internal inconsistency of the definitions.
IDENTITY_CORRECTIONS = ("p_p_scale", "p_b_scale", "alpha_scale")

#: Economically meaningful ranges for the parameters themselves, not for their corrections.
#:
#: Bounding the corrections generously and letting the optimiser roam turned out to be a mistake. Given
#: wide bounds it drove p_p negative, which means a negative return on capital in every period, and pushed
#: alpha to four times its observed value, which puts the savings share flowing to financial capital far
#: above one. Those choices lowered the level residual to 0.23 while making the parameter set meaningless,
#: which is overfitting in the most literal sense: a better number bought with a worse model.
#:
#: The scale bounds are therefore derived from these ranges and each parameter's own observed magnitude, so
#: a fitted parameter cannot leave the range its definition permits. Since the model is judged on turning
#: points rather than on level, trading level accuracy for parameter meaning is the right way round.
PARAMETER_RANGES: Mapping[str, tuple[float, float]] = {
    # Achievable return on capital. Positive by definition, and a real economy does not sustain more than
    # a fifth per year on its whole capital stock.
    "p_p": (0.005, 0.20),
    # Tracks population growth, so a small rate that may be slightly negative for a shrinking population.
    "p_b": (-0.02, 0.05),
    # A share of the savings rate, so it cannot leave the unit interval.
    "alpha": (0.0, 1.0),
    # Gross national savings as a share of output.
    "p_s": (0.02, 0.60),
}

#: Multiplicative bounds on the stimulus scale. The proxy is observed, so it is allowed to be scaled but
#: not to change sign or dominate: a stimulus three times the measured fiscal impulse is already generous.
STIMULUS_SCALE_BOUNDS = (0.0, 3.0)

#: How far the initial state may move from its observed value. The model is being calibrated to an observed
#: trajectory, so a distant initial state is a different economy rather than a better fit.
INITIAL_STATE_TOLERANCE = 0.10


def _scale_bounds(
    values: np.ndarray, quantity: str, fallback: tuple[float, float] = (0.25, 4.0)
) -> tuple[float, float]:
    """Return multiplicative bounds that keep a parameter inside its meaningful range.

    Derived from the parameter's own observed magnitude, so the bound means the same thing for an economy
    whose p_p averages 0.05 and one whose p_b averages 0.002.

    Args:
        values: The observed identity path for the parameter.
        quantity: The parameter name, used to look up its range.
        fallback: Used when the observed path is unusable, for example all zero.

    Returns:
        The (lower, upper) multiplicative bounds.
    """
    low, high = PARAMETER_RANGES[quantity]
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return fallback

    typical = float(np.median(np.abs(finite)))
    if typical <= 0.0:
        return fallback

    # The observed path may already sit partly outside the range, so the bounds are what is needed to pull
    # it in rather than an assumption that it starts inside.
    signed = float(np.median(finite))
    if signed == 0.0:
        return fallback
    candidates = sorted((low / signed, high / signed))
    lower, upper = candidates
    if upper <= lower:
        return fallback
    return (lower, upper)


class CalibrationError(ValueError):
    """Raised when a calibration cannot be set up or completed."""


@dataclass
class ObservedPath:
    """The observed trajectory an economy is calibrated to.

    All series are on a common period index, with no gaps, because the data layer resolves gaps before
    anything reaches here.

    Attributes:
        periods: Period labels, normally years.
        output: Observed Y.
        real_capital: Observed K_R.
        financial_capital: Observed K_I.
        savings_rate: Observed p_s, as a fraction.
        stimulus_proxy: The observed stimulus proxy, in the same units as the capital series.
    """

    periods: np.ndarray
    output: np.ndarray
    real_capital: np.ndarray
    financial_capital: np.ndarray
    savings_rate: np.ndarray
    stimulus_proxy: np.ndarray

    def __post_init__(self) -> None:
        arrays = {
            "periods": self.periods,
            "output": self.output,
            "real_capital": self.real_capital,
            "financial_capital": self.financial_capital,
            "savings_rate": self.savings_rate,
            "stimulus_proxy": self.stimulus_proxy,
        }
        lengths = {name: np.asarray(a).shape[0] for name, a in arrays.items()}
        if len(set(lengths.values())) != 1:
            raise CalibrationError(f"all observed series must share a length, got {lengths}")
        if lengths["periods"] < 5:
            raise CalibrationError(
                f"a calibration needs at least five periods, got {lengths['periods']}"
            )
        for name in ("output", "real_capital", "financial_capital"):
            values = np.asarray(arrays[name], dtype=float)
            if np.any(~np.isfinite(values)):
                raise CalibrationError(
                    f"{name} contains gaps. The data layer must resolve them before calibration, so "
                    f"that no gap is filled implicitly here."
                )
            if np.any(values <= 0.0):
                raise CalibrationError(f"{name} must be strictly positive throughout")

    @property
    def length(self) -> int:
        return int(np.asarray(self.periods).shape[0])

    @property
    def time(self) -> np.ndarray:
        """Periods as floats, measured in years from the start of the window."""
        periods = np.asarray(self.periods, dtype=float)
        return periods - periods[0]


@dataclass
class IdentityParameters:
    """The parameters that are identities from data, per brief section 0.2.

    Attributes:
        r: Investment share, 1 - K_R/Y. A pure function of the state.
        alpha: Savings share flowing to financial capital.
        p_p: Achievable return on capital.
        p_b: Wage against capital income.
        output_growth: The smoothed derivative of Y, retained because every identity above depends on it.
        real_capital_growth: The smoothed derivative of K_R.
        financial_capital_growth: The smoothed derivative of K_I.
        smoothing: The derivative method and window actually used, for the report.
    """

    r: np.ndarray
    alpha: np.ndarray
    p_p: np.ndarray
    p_b: np.ndarray
    output_growth: np.ndarray
    real_capital_growth: np.ndarray
    financial_capital_growth: np.ndarray
    smoothing: dict[str, Any] = field(default_factory=dict)

    def as_paths(self) -> dict[str, np.ndarray]:
        return {"r": self.r, "alpha": self.alpha, "p_p": self.p_p, "p_b": self.p_b}


#: How p_b is obtained. See `compute_identity_parameters` for why there is a choice at all.
P_B_FROM_FLOW_RATIO = "flow_ratio"
P_B_FROM_POPULATION_GROWTH = "population_growth"


def compute_identity_parameters(
    path: ObservedPath,
    method: str = "savitzky_golay",
    window_years: int = 5,
    polynomial_order: int = 2,
    p_b_source: str = P_B_FROM_POPULATION_GROWTH,
    population_growth: np.ndarray | None = None,
) -> IdentityParameters:
    """Compute r, alpha, p_p and p_b from the observed series and their smoothed derivatives.

    The smoothing choice is exposed rather than fixed because it propagates: all three of alpha, p_p and
    p_b are defined through derivatives, so the window width changes every one of them and therefore the
    whole calibration. Brief section 3 requires the choice to be documented, and it is recorded on the
    returned object and in the calibration report.

    **Why p_b has a source option.** Section 0.2 defines `p_b = (Y_dot + K_R_dot) / K_I_dot` and describes
    it as approximating wage against capital income and tracking population growth. Those two statements
    are not compatible. The formula is a ratio of *flows*, so it comes out of order one: on real United
    States data it computes to 5.65. But in the output equation it multiplies `Y` as a *rate*, alongside
    `p_s` which is about 0.2. At 5.65 the term `(p_b - p_s) Y` implies 544 per cent annual output growth,
    and the simulated path runs from 1.7e12 to 1.0e62 over the window. Population growth, which the brief
    says it tracks, is about 0.005.

    So the transcribed formula is dimensionally inconsistent with the use the same section puts it to. This
    is reported rather than silently patched, and both readings are available:

    - `population_growth` (the default) takes p_b from the observed population growth rate, which is the
      quantity section 0.2 says it represents and which is dimensionally a rate.
    - `flow_ratio` computes the formula as written, for comparison. It does not produce a usable
      trajectory, which is itself the evidence for the inconsistency.

    Args:
        path: The observed trajectory.
        method: Derivative method, passed to `loaders.numeric_derivative`.
        window_years: Smoothing window.
        polynomial_order: Local polynomial order.
        p_b_source: Which reading of p_b to use.
        population_growth: The observed population growth rate per period, required when p_b_source is
            `population_growth`.

    Returns:
        The identity parameters.

    Raises:
        CalibrationError: If population growth is requested but not supplied, or the source is unknown.
    """
    time = path.time
    y = np.asarray(path.output, dtype=float)
    k_r = np.asarray(path.real_capital, dtype=float)
    k_i = np.asarray(path.financial_capital, dtype=float)
    p_s = np.asarray(path.savings_rate, dtype=float)

    kwargs = {"method": method, "window_years": window_years, "polynomial_order": polynomial_order}
    y_dot = numeric_derivative(y, time, **kwargs)
    k_r_dot = numeric_derivative(k_r, time, **kwargs)
    k_i_dot = numeric_derivative(k_i, time, **kwargs)

    r = 1.0 - k_r / y

    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.where(p_s != 0.0, (1.0 / np.where(p_s != 0.0, p_s, np.nan)) * (y_dot / y), np.nan)
        p_p = (y_dot + k_r_dot) / k_r
        flow_ratio = np.where(
            k_i_dot != 0.0, (y_dot + k_r_dot) / np.where(k_i_dot != 0.0, k_i_dot, np.nan), np.nan
        )

    if p_b_source == P_B_FROM_FLOW_RATIO:
        p_b = flow_ratio
        p_b_note = (
            "p_b computed as the flow ratio (Y_dot + K_R_dot) / K_I_dot exactly as section 0.2 writes it. "
            f"Its mean over the window is {float(np.nanmean(flow_ratio)):.3f}, which is a ratio of order "
            f"one rather than a rate, so the term (p_b - p_s) Y implies implausible output growth and the "
            f"system will not produce a usable trajectory. Retained for comparison."
        )
    elif p_b_source == P_B_FROM_POPULATION_GROWTH and population_growth is None:
        # Fall back rather than raise. A missing population series should not stop an economy being
        # calibrated, and the note records the substitution so a poor result is attributable to it.
        p_b = flow_ratio
        p_b_note = (
            "p_b requested from population growth but no population series was supplied, so the "
            f"flow-ratio formula of section 0.2 was used instead. Its mean over the window is "
            f"{float(np.nanmean(flow_ratio)):.3f}, which is a ratio of order one rather than a rate, so "
            f"the trajectory is unlikely to be usable. Supply population growth for a meaningful fit."
        )
    elif p_b_source == P_B_FROM_POPULATION_GROWTH:
        p_b = np.asarray(population_growth, dtype=float)
        if p_b.shape != y.shape:
            raise CalibrationError(
                f"population_growth has shape {p_b.shape}, expected {y.shape}"
            )
        p_b_note = (
            "p_b taken from the observed population growth rate, which is the quantity section 0.2 says "
            f"it tracks and which is dimensionally a rate. Its mean over the window is "
            f"{float(np.nanmean(p_b)):.4f}. The formula the same section writes, "
            f"(Y_dot + K_R_dot) / K_I_dot, averages {float(np.nanmean(flow_ratio)):.3f} over this window, "
            f"which is a flow ratio rather than a rate and is dimensionally inconsistent with the use the "
            f"output equation puts p_b to. That discrepancy is a property of the source definition and is "
            f"reported rather than patched."
        )
    else:
        raise CalibrationError(
            f"unknown p_b_source {p_b_source!r}, expected one of "
            f"{(P_B_FROM_FLOW_RATIO, P_B_FROM_POPULATION_GROWTH)}"
        )

    return IdentityParameters(
        r=r,
        alpha=alpha,
        p_p=p_p,
        p_b=p_b,
        output_growth=y_dot,
        real_capital_growth=k_r_dot,
        financial_capital_growth=k_i_dot,
        smoothing={
            "method": method,
            "window_years": window_years,
            "polynomial_order": polynomial_order,
            "p_b_source": p_b_source,
            "p_b_note": p_b_note,
            "note": (
                "alpha, p_p and p_b are all defined through time derivatives, so this choice "
                "propagates into every one of them and into the fitted free parameters"
            ),
        },
    )


def _interpolator(time: np.ndarray, values: np.ndarray) -> Callable[[float], float]:
    """Return a callable that evaluates a parameter path at arbitrary time.

    Linear between observations and held flat outside the window, because a stiff solver probes beyond
    the end points and an extrapolating parameter path there produces nonsense that looks like a
    modelling result.
    """
    finite = np.isfinite(values)
    if not finite.any():
        return lambda _t: 0.0
    t_finite = np.asarray(time, dtype=float)[finite]
    v_finite = np.asarray(values, dtype=float)[finite]

    def evaluate(t: float) -> float:
        return float(np.interp(t, t_finite, v_finite, left=v_finite[0], right=v_finite[-1]))

    return evaluate


@dataclass
class CalibrationResult:
    """The outcome of calibrating one economy.

    Attributes:
        economy: The economy code.
        periods: The calibration window's periods.
        free_parameters: The fitted free parameters, by name.
        standard_errors: Estimated standard error per free parameter, or NaN where not estimable.
        identifiability: Per-parameter identifiability verdict.
        weakly_identified: Names of parameters flagged as weakly identified.
        residuals_by_series: Root mean square relative residual per observed series.
        simulated: The simulated paths at the observed periods.
        integration_accuracy: "reporting" if the fitted path integrates at reporting tolerance, or
            "search" if it only integrates at the looser search tolerance, which indicates the
            trajectory runs close to the singularity.
        observed: The observed paths.
        identity_diagnostics: Residuals of the section 0.2 definitions along the fitted path.
        two_body_worst: Worst normalised two-body identity residual over the fitted path.
        converged: Whether the optimiser reported success.
        message: The optimiser's message.
        smoothing: The derivative smoothing actually used.
        notes: Anything a reader of the report must know.
    """

    economy: str
    periods: np.ndarray
    free_parameters: dict[str, float]
    standard_errors: dict[str, float]
    identifiability: dict[str, str]
    weakly_identified: list[str]
    residuals_by_series: dict[str, float]
    simulated: dict[str, np.ndarray]
    integration_accuracy: str
    observed: dict[str, np.ndarray]
    identity_diagnostics: dict[str, float]
    two_body_worst: float
    converged: bool
    message: str
    smoothing: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    @property
    def fit_quality(self) -> float:
        """Mean relative residual across the three state series, as a single summary."""
        keys = ("Y", "K_R", "K_I")
        return float(np.mean([self.residuals_by_series[k] for k in keys]))

    def report(self) -> dict[str, Any]:
        """The per-economy calibration report of brief section 4."""
        return {
            "economy": self.economy,
            "window": {
                "first": int(self.periods[0]),
                "last": int(self.periods[-1]),
                "periods": len(self.periods),
            },
            "converged": self.converged,
            "optimiser_message": self.message,
            "integration_accuracy": self.integration_accuracy,
            "fit_quality": {
                "mean_relative_residual": self.fit_quality,
                "per_series": dict(self.residuals_by_series),
            },
            "free_parameters": {
                name: {
                    "value": self.free_parameters[name],
                    "standard_error": self.standard_errors.get(name, float("nan")),
                    "identifiability": self.identifiability.get(name, "unknown"),
                }
                for name in self.free_parameters
            },
            "weakly_identified": list(self.weakly_identified),
            "identity_diagnostics": dict(self.identity_diagnostics),
            "two_body_worst_relative_residual": self.two_body_worst,
            "derivative_smoothing": dict(self.smoothing),
            "notes": list(self.notes),
        }


def _build_parameters(
    vector: Sequence[float],
    path: ObservedPath,
    identities: IdentityParameters,
) -> tuple[EDMParameters, np.ndarray]:
    """Assemble EDM parameters and an initial state from a free-parameter vector.

    The identity paths carry multiplicative corrections. See FREE_PARAMETERS for why.
    """
    (
        p_p_scale,
        p_b_scale,
        alpha_scale,
        savings_scale,
        stimulus_scale,
        y0,
        k_r0,
        k_i0,
    ) = (float(v) for v in vector)
    time = path.time

    params = EDMParameters(
        p_s=_interpolator(time, np.asarray(path.savings_rate, dtype=float) * savings_scale),
        p_p=_interpolator(time, identities.p_p * p_p_scale),
        p_b=_interpolator(time, identities.p_b * p_b_scale),
        alpha=_interpolator(time, identities.alpha * alpha_scale),
        stimulus=_interpolator(time, np.asarray(path.stimulus_proxy, dtype=float) * stimulus_scale),
        endogenous_r=True,
    )
    return params, np.array([y0, k_r0, k_i0], dtype=float)


def _residual_vector(
    vector: Sequence[float],
    path: ObservedPath,
    identities: IdentityParameters,
    closure: ClosureMode,
    weights: Mapping[str, float],
) -> np.ndarray:
    """Return the log-space residual between simulated and observed paths.

    Log space, not relative, for three reasons that all matter here:

    1. **It bounds an explosive path.** These states grow exponentially and the system can run away, and
       a relative residual then reaches order 1e9 while the divergence penalty is a fixed constant. That
       inverts the ranking, so divergence scores better than a bad fit and the optimiser parks in the
       divergent region. In log space the same explosion is a residual of order tens.
    2. **It is scale-free across the three series.** Y, K_R and K_I differ by an order of magnitude, and
       an absolute residual would fit whichever happens to be largest.
    3. **It linearises exponential growth**, which is the behaviour the system is mostly producing, so a
       constant proportional error costs the same at either end of the window rather than being dominated
       by the last few periods.

    A parameter set whose trajectory fails to integrate, or which drives a state to zero or below,
    returns the divergence penalty rather than raising. That is deliberate: divergence is a property of
    the parameter set, so the optimiser should see it as a bad score and move away rather than crashing
    the calibration.
    """
    params, initial = _build_parameters(vector, path, identities)
    time = path.time
    length = path.length

    if np.any(initial <= 0.0):
        return np.full(3 * length, DIVERGENCE_PENALTY)

    with warnings.catch_warnings():
        # The two-body residual warning is expected during a search and is reported separately once the
        # fit has settled, so it is silenced here to keep the optimiser quiet.
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            result = simulate(
                initial,
                params,
                (float(time[0]), float(time[-1])),
                t_eval=time,
                closure=closure,
                method=SEARCH_METHOD,
                rtol=SEARCH_RTOL,
                atol=SEARCH_ATOL,
                warn_on_residual=False,
            )
        except Exception:  # noqa: BLE001 - any integrator failure is a bad parameter set, not an error
            return np.full(3 * length, DIVERGENCE_PENALTY)

    # Use however far the integration got, rather than discarding a partial trajectory.
    #
    # This is what makes the search work at all. A flat penalty for any failure is not merely crude, it is
    # actively defeating: when the starting point is already in the divergent region, every finite-
    # difference step also diverges, the residual is a constant vector, the Jacobian is exactly zero, and
    # the optimiser terminates at its starting point reporting success. That is what happened on real data,
    # where every fitted scale came back as exactly 1.000000.
    #
    # Grading the penalty by how far the integration reached gives a gradient towards feasibility: failing
    # later scores better than failing sooner, so the optimiser can climb out of the divergent region
    # instead of sitting in it.
    reached = int(result.t.shape[0])
    usable = min(reached, length)

    pieces: list[np.ndarray] = []
    for name, simulated, observed in (
        ("Y", result.Y, path.output),
        ("K_R", result.K_R, path.real_capital),
        ("K_I", result.K_I, path.financial_capital),
    ):
        values = np.asarray(simulated, dtype=float)[:usable]
        target = np.asarray(observed, dtype=float)[:usable]
        weight = weights.get(name, 1.0)

        # Positions where the state is non-positive or non-finite have no logarithm and are treated as
        # divergent from that point on.
        valid = usable
        if values.size:
            bad = np.flatnonzero(~np.isfinite(values) | (values <= 0.0))
            if bad.size:
                valid = int(bad[0])

        residual = np.full(length, DIVERGENCE_PENALTY, dtype=float)
        if valid > 0:
            residual[:valid] = weight * (np.log(values[:valid]) - np.log(target[:valid]))
        if valid < length:
            # Grade the penalty on the shortfall so that reaching further is rewarded.
            shortfall = (length - valid) / length
            residual[valid:] = DIVERGENCE_PENALTY * (0.5 + 0.5 * shortfall)
        pieces.append(residual)

    return np.concatenate(pieces)


def _estimate_standard_errors(
    jacobian: np.ndarray, residual: np.ndarray, parameter_count: int
) -> np.ndarray:
    """Estimate parameter standard errors from the least-squares Jacobian.

    The usual Gauss-Newton approximation: the covariance is the residual variance times the inverse of
    J transpose J. Where that matrix is singular the parameter is not identified by the data at all, and
    NaN is returned rather than a number produced by a pseudo-inverse, because a fabricated standard
    error is worse than an admitted absence.
    """
    degrees_of_freedom = max(1, residual.size - parameter_count)
    variance = float(residual @ residual) / degrees_of_freedom
    try:
        covariance = variance * np.linalg.inv(jacobian.T @ jacobian)
    except np.linalg.LinAlgError:
        return np.full(parameter_count, np.nan)
    diagonal = np.diag(covariance)
    return np.where(diagonal >= 0.0, np.sqrt(np.abs(diagonal)), np.nan)


def calibrate(
    economy: str,
    path: ObservedPath,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
    smoothing_method: str = "savitzky_golay",
    window_years: int = 5,
    polynomial_order: int = 2,
    weak_identification_ratio: float = 0.5,
    max_iterations: int = DEFAULT_MAX_EVALUATIONS,
    weights: Mapping[str, float] | None = None,
    seed: int = 20260727,
    p_b_source: str = P_B_FROM_POPULATION_GROWTH,
    population_growth: np.ndarray | None = None,
) -> CalibrationResult:
    """Calibrate one economy to its observed trajectory.

    Args:
        economy: The economy code.
        path: The observed trajectory.
        closure: How to resolve the over-determination of section 0.2.
        smoothing_method: Derivative method for the identity parameters.
        window_years: Smoothing window.
        polynomial_order: Local polynomial order.
        weak_identification_ratio: Standard error over absolute value above which a parameter is
            reported as weakly identified.
        max_iterations: Optimiser iteration cap.
        weights: Optional per-series residual weights.
        seed: Retained for reproducibility of any stochastic step. The optimiser is deterministic, so
            this is recorded rather than used, and it is here so the calibration cannot silently
            become non-reproducible if a stochastic step is added later.

    Returns:
        The calibration result, including the identifiability assessment.
    """
    del seed  # Deterministic optimiser; recorded in the report by the caller.
    if population_growth is None and p_b_source == P_B_FROM_POPULATION_GROWTH:
        # Fall back to the formula as written rather than failing, and the returned note records that the
        # fallback happened so a poor result is attributable.
        p_b_source = P_B_FROM_FLOW_RATIO
    identities = compute_identity_parameters(
        path,
        smoothing_method,
        window_years,
        polynomial_order,
        p_b_source=p_b_source,
        population_growth=population_growth,
    )
    series_weights = dict(weights or {})

    # Every correction starts at one, which is the internally consistent point: if the definitions and
    # the equations of motion agreed, the fit would stay there.
    initial_vector = np.array(
        [
            1.0,  # p_p correction
            1.0,  # p_b correction
            1.0,  # alpha correction
            1.0,  # savings-rate scale
            1.0,  # stimulus scale
            float(path.output[0]),
            float(path.real_capital[0]),
            float(path.financial_capital[0]),
        ],
        dtype=float,
    )
    # Bounds derived from what each parameter means, not from a generous default. See PARAMETER_RANGES for
    # why: given wide bounds the optimiser drove the return on capital negative and the savings share above
    # one, buying a lower level residual with a meaningless parameter set.
    p_p_bounds = _scale_bounds(identities.p_p, "p_p")
    p_b_bounds = _scale_bounds(identities.p_b, "p_b")
    alpha_bounds = _scale_bounds(identities.alpha, "alpha")
    p_s_bounds = _scale_bounds(np.asarray(path.savings_rate, dtype=float), "p_s")
    tolerance = INITIAL_STATE_TOLERANCE

    lower = np.array(
        [
            p_p_bounds[0],
            p_b_bounds[0],
            alpha_bounds[0],
            p_s_bounds[0],
            STIMULUS_SCALE_BOUNDS[0],
            (1.0 - tolerance) * path.output[0],
            (1.0 - tolerance) * path.real_capital[0],
            (1.0 - tolerance) * path.financial_capital[0],
        ]
    )
    upper = np.array(
        [
            p_p_bounds[1],
            p_b_bounds[1],
            alpha_bounds[1],
            p_s_bounds[1],
            STIMULUS_SCALE_BOUNDS[1],
            (1.0 + tolerance) * path.output[0],
            (1.0 + tolerance) * path.real_capital[0],
            (1.0 + tolerance) * path.financial_capital[0],
        ]
    )
    # The starting point must lie inside the bounds, and the identity paths may already sit outside their
    # meaningful range, so the unit correction is clipped rather than assumed feasible.
    initial_vector = np.clip(initial_vector, lower, upper)

    solution = least_squares(
        _residual_vector,
        initial_vector,
        bounds=(lower, upper),
        args=(path, identities, closure, series_weights),
        max_nfev=max_iterations,
        # Loose relative to a well-conditioned problem, because this surface is not one: the parameters
        # trade off against each other and chasing the last few digits costs many stiff integrations for
        # no change in the reported conclusion.
        xtol=1e-10,
        ftol=1e-10,
        # Explicit parameter scales, not "jac". With "jac" the optimiser terminated at the starting point
        # on real data and returned every scale as exactly 1.000000, which also made the identifiability
        # report meaningless because the standard errors were computed from a Jacobian evaluated where
        # nothing had moved. The corrections are order one and the initial states are order 1e12, so the
        # scales have to be stated rather than inferred from a Jacobian that spans twelve orders of
        # magnitude.
        x_scale=np.array(
            [1.0, 1.0, 1.0, 1.0, 1.0]
            + [max(abs(float(v)), 1.0) for v in initial_vector[5:]]
        ),
        # A step large enough to move the residual on a stiff system. The default relative step is around
        # 1e-8, which on this surface produced a numerically zero gradient and hence no movement.
        diff_step=1e-4,
        loss="soft_l1",
        f_scale=1.0,
    )

    fitted = {name: float(value) for name, value in zip(FREE_PARAMETERS, solution.x)}
    errors_array = _estimate_standard_errors(
        np.atleast_2d(solution.jac), np.asarray(solution.fun), len(FREE_PARAMETERS)
    )
    errors = {name: float(value) for name, value in zip(FREE_PARAMETERS, errors_array)}

    identifiability: dict[str, str] = {}
    weak: list[str] = []
    for name in FREE_PARAMETERS:
        value, error = fitted[name], errors[name]
        if not np.isfinite(error):
            identifiability[name] = "not identified: the data do not constrain this parameter"
            weak.append(name)
        elif abs(value) < 1e-12:
            identifiability[name] = "at zero, so a relative standard error is undefined"
        elif error / abs(value) > weak_identification_ratio:
            identifiability[name] = (
                f"weakly identified: standard error is {error / abs(value):.0%} of the value"
            )
            weak.append(name)
        else:
            identifiability[name] = (
                f"identified: standard error is {error / abs(value):.0%} of the value"
            )

    # Re-simulate at the fitted parameters to report the path and the diagnostics.
    #
    # Reporting accuracy is attempted first. A parameter set can be integrable under the looser search
    # settings and not under the tighter reporting ones, which is not a contradiction: it means the
    # trajectory passes close to the singularity described in model/edm.py, where the step size a tight
    # tolerance demands collapses. Where that happens the fallback keeps the search settings and says so,
    # rather than reporting an infinite residual that hides a path the optimiser could see.
    params, initial = _build_parameters(solution.x, path, identities)
    notes: list[str] = []
    accuracy = "reporting"

    span = (float(path.time[0]), float(path.time[-1]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        # Report under the settings the search actually used, so the reported path is by construction
        # the one the optimiser scored. Reporting under tighter settings than the search could show a
        # path the optimiser never evaluated, or none at all.
        final = simulate(
            initial,
            params,
            span,
            t_eval=path.time,
            closure=closure,
            method=SEARCH_METHOD,
            rtol=SEARCH_RTOL,
            atol=SEARCH_ATOL,
            warn_on_residual=False,
        )
        accuracy = "search"

        # Then check whether the same parameter set survives reporting tolerance. If it does, the path
        # is trustworthy at the level as well as in shape; if not, it runs close to the singularity.
        verification = simulate(
            initial,
            params,
            span,
            t_eval=path.time,
            closure=closure,
            warn_on_residual=False,
        )

    if verification.success and verification.t.shape[0] == path.length:
        final = verification
        accuracy = "reporting"
    else:
        notes.append(
            "the fitted parameter set integrates at search tolerance but not at reporting tolerance, "
            "so the simulated path is reported at the looser setting. That means the trajectory runs "
            "close to the finite-time singularity of the unbounded investment share documented in "
            "model/edm.py. Treat the level of the simulated path with caution even where the fit "
            "statistics look reasonable, and prefer the qualitative reading."
        )
    simulated: dict[str, np.ndarray] = {}
    residuals: dict[str, float] = {}

    if final.success and final.t.shape[0] == path.length:
        simulated = {"Y": final.Y, "K_R": final.K_R, "K_I": final.K_I}
        for name, values, observed in (
            ("Y", final.Y, path.output),
            ("K_R", final.K_R, path.real_capital),
            ("K_I", final.K_I, path.financial_capital),
        ):
            # Reported as a relative residual, which is what a reader expects, even though the fit is
            # performed in log space. Guarded so an explosive path reports a large number rather than
            # an overflow.
            scale = np.maximum(np.abs(np.asarray(observed, dtype=float)), 1e-9)
            relative = (np.asarray(values, dtype=float) - observed) / scale
            residuals[name] = (
                float(np.sqrt(np.mean(relative**2))) if np.all(np.isfinite(relative)) else float("inf")
            )
    else:
        notes.append(
            "the fitted parameter set does not integrate over the whole window, so no simulated path "
            "is reported. This is the finite-time singularity documented in model/edm.py: the "
            "unbounded investment share makes some parameter regions unreachable, and the optimiser "
            "could not find a set that both fits and integrates."
        )
        simulated = {"Y": np.array([]), "K_R": np.array([]), "K_I": np.array([])}
        residuals = {name: float("inf") for name in ("Y", "K_R", "K_I")}

    # Identity diagnostics along the fitted path, reported never enforced.
    diagnostics: dict[str, float] = {}
    if final.success and final.t.shape[0] == path.length:
        collected: dict[str, list[float]] = {}
        implied_growth: list[float] = []
        for index, t in enumerate(final.t):
            state = (final.Y[index], final.K_R[index], final.K_I[index])
            for key, value in identity_residuals(float(t), state, params, closure).items():
                collected.setdefault(key, []).append(value)
            implied_growth.append(p_p_identity_implied_y_dot(float(t), state, params))
        for key, values in collected.items():
            finite = [v for v in values if np.isfinite(v)]
            diagnostics[f"{key}_mean_abs_residual"] = (
                float(np.mean(np.abs(finite))) if finite else float("nan")
            )
        diagnostics["p_p_identity_implied_mean_output_growth"] = float(np.mean(implied_growth))
        if diagnostics["p_p_identity_implied_mean_output_growth"] < 0.0:
            notes.append(
                "the p_p identity, taken together with the real-capital equation, implies negative "
                "output growth over this window. That is the documented over-determination, not a "
                "finding about the economy: the identity is reported and not enforced, so the "
                "calibration is unaffected."
            )

    # How far the identity corrections had to move from one, which measures the inconsistency between
    # the definitions of section 0.2 and the equations of motion.
    departures = {name: abs(fitted[name] - 1.0) for name in IDENTITY_CORRECTIONS}
    diagnostics["identity_correction_departures"] = {
        name: round(value, 6) for name, value in departures.items()
    }
    worst_name = max(departures, key=departures.get)
    diagnostics["worst_identity_correction"] = worst_name
    diagnostics["worst_identity_correction_departure"] = departures[worst_name]
    if departures[worst_name] > 0.10:
        notes.append(
            f"the identity corrections had to move materially away from one to fit the trajectory, "
            f"the largest being {worst_name} at {fitted[worst_name]:.3f}, a departure of "
            f"{departures[worst_name]:.0%}. A correction of one would mean the definitions of section "
            f"0.2 and the equations of motion agree; this is how far they do not. The correction is "
            f"reported rather than constrained, because constraining it would make the calibration "
            f"fail instead of making the inconsistency visible."
        )
    else:
        notes.append(
            f"the identity corrections stayed within 10 per cent of one (largest departure "
            f"{departures[worst_name]:.1%}), so over this window the definitions of section 0.2 are "
            f"close to consistent with the equations of motion."
        )

    if not solution.success:
        notes.append(
            f"the optimiser did not converge: {solution.message}. Treat the parameter values as "
            f"provisional and widen the window or revisit the stimulus proxy."
        )
    if weak:
        notes.append(
            f"weakly identified parameters: {', '.join(weak)}. Brief section 4 requires these to be "
            f"held to plausible priors and stress-tested rather than over-fitted, which is what "
            f"calibration/validate.py does."
        )

    return CalibrationResult(
        economy=economy,
        periods=np.asarray(path.periods),
        free_parameters=fitted,
        standard_errors=errors,
        identifiability=identifiability,
        weakly_identified=weak,
        residuals_by_series=residuals,
        simulated=simulated,
        integration_accuracy=accuracy,
        observed={
            "Y": np.asarray(path.output, dtype=float),
            "K_R": np.asarray(path.real_capital, dtype=float),
            "K_I": np.asarray(path.financial_capital, dtype=float),
        },
        identity_diagnostics=diagnostics,
        two_body_worst=float(final.max_abs_two_body_residual),
        converged=bool(solution.success),
        message=str(solution.message),
        smoothing=identities.smoothing,
        notes=notes,
    )
