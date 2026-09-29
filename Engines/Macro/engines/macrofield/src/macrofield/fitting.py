"""Per-economy calibration of the three-body system to its observed path. Pure.

The identity parameters (r, alpha, p_p, p_b) come from the observed series and their smoothed
derivatives. The free parameters are eight: a multiplicative correction on each of the three
identity paths p_p, p_b and alpha, a scale on the savings rate and on the stimulus proxy, and
the initial state (Y, K_R, K_I) within a tolerance of its observed value.

Why corrections rather than free paths. The definitions over-determine the system (see
dynamics.py), so integrating them as written fits nothing. If the definitions and the equations
agreed, every correction would fit at exactly one; how far each departs from one is a direct,
reported measure of the inconsistency. Bounds come from each parameter's meaningful range, not a
generous default, because given room the optimiser buys level accuracy with a meaningless
parameter set (negative return on capital, savings shares above one).

Why log space and a graded divergence penalty. The states grow exponentially and some parameter
sets reach a finite-time singularity. Log residuals bound an explosive path to order tens, so a
fixed penalty stays larger than any finite misfit; grading the penalty by how far the
integration got gives the optimiser a gradient out of the divergent region instead of a flat
floor on which it stops where it started.

From calibration 1.5.0 (TB-27) the fit integrates the equations with the bounded investment
share, r = max(0, 1 - K_R/Y), the same equations the projection runs. There is then no
finite-time singularity to fall into (dynamics.py), and on the current snapshot every window
integrates at reporting tolerance, the six that did not under 1.4.0 (BR, CH, TH, JP, DE, ES)
included. The divergence penalty stays for states that leave the positive domain.

The procedure follows ``Macro_Model/macrofield/calibration/fit.py`` step for step; every setting comes from
the :class:`~macrofield.contracts.Calibration` instead of module constants.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

from .contracts import Calibration
from .dynamics import (
    Parameters,
    identity_residuals,
    p_p_implied_output_growth,
    simulate,
)

FREE_PARAMETERS = ("p_p_scale", "p_b_scale", "alpha_scale", "savings_scale", "stimulus_scale",
                   "initial_output", "initial_real", "initial_financial")
IDENTITY_CORRECTIONS = ("p_p_scale", "p_b_scale", "alpha_scale")


class FitError(ValueError):
    """The observed path cannot be calibrated as given. The message says why."""


@dataclass(frozen=True)
class ObservedPath:
    periods: np.ndarray
    output: np.ndarray
    real_capital: np.ndarray
    financial_capital: np.ndarray
    savings_rate: np.ndarray
    stimulus: np.ndarray

    def __post_init__(self) -> None:
        n = {len(a) for a in (self.periods, self.output, self.real_capital,
                              self.financial_capital, self.savings_rate, self.stimulus)}
        if len(n) != 1:
            raise FitError("every observed series must share a length")
        if len(self.periods) < 5:
            raise FitError(f"a calibration needs at least five periods, got {len(self.periods)}")
        for name in ("output", "real_capital", "financial_capital"):
            values = getattr(self, name)
            if np.any(~np.isfinite(values)) or np.any(values <= 0.0):
                raise FitError(f"{name} must be finite and strictly positive throughout")

    @property
    def length(self) -> int:
        return int(self.periods.shape[0])

    @property
    def time(self) -> np.ndarray:
        periods = np.asarray(self.periods, dtype=float)
        return periods - periods[0]


# ---------------------------------------------------------------------------
# Identities from data
# ---------------------------------------------------------------------------

def numeric_derivative(values: np.ndarray, times: np.ndarray, method: str, window_years: int,
                       polynomial_order: int) -> np.ndarray:
    """Smoothed first derivative. Savitzky-Golay by default: no moving-average phase shift.

    The smoothing choice propagates into alpha, p_p and p_b and so into the whole fit, which is
    why it is part of the calibration rather than fixed here.
    """
    series = np.asarray(values, dtype=float)
    t = np.asarray(times, dtype=float)
    if series.size < 3:
        raise FitError(f"a derivative needs at least three observations, got {series.size}")
    if np.any(~np.isfinite(series)):
        raise FitError("cannot differentiate across a gap")
    if method == "central_difference":
        return np.gradient(series, t)
    window = int(window_years)
    if window % 2 == 0:
        window += 1
    window = min(window, series.size if series.size % 2 == 1 else series.size - 1)
    if window <= polynomial_order:
        raise FitError(f"a smoothing window of {window} is too short for order {polynomial_order}")
    spacing = float(np.median(np.diff(t)))
    if spacing <= 0.0:
        raise FitError("periods must increase")
    return savgol_filter(series, window_length=window, polyorder=polynomial_order, deriv=1,
                         delta=spacing)


@dataclass(frozen=True)
class Identities:
    r: np.ndarray
    alpha: np.ndarray
    p_p: np.ndarray
    p_b: np.ndarray
    p_b_flow_ratio: np.ndarray
    p_b_source: str


def identities(path: ObservedPath, population_growth: np.ndarray | None,
               cal: Calibration) -> Identities:
    """r, alpha, p_p and p_b on the observed path.

    p_b is written in section 0.2 as the flow ratio (Y_dot + K_R_dot) / K_I_dot, which is of
    order one, while the Y equation uses p_b as a rate beside p_s. At the flow ratio the system
    explodes (the old CLI path reached Y = 1e62). The default is therefore observed population
    growth, the quantity the same section says p_b tracks; the flow ratio is always reported.
    Without a population series the flow ratio is used and the note says so.
    """
    d = cal.derivative
    kw = dict(method=d.method, window_years=d.window_years, polynomial_order=d.polynomial_order)
    t = path.time
    y, k_r, k_i, p_s = path.output, path.real_capital, path.financial_capital, path.savings_rate
    y_dot = numeric_derivative(y, t, **kw)
    k_r_dot = numeric_derivative(k_r, t, **kw)
    k_i_dot = numeric_derivative(k_i, t, **kw)

    r = 1.0 - k_r / y
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.where(p_s != 0.0, (1.0 / np.where(p_s != 0.0, p_s, np.nan)) * (y_dot / y),
                         np.nan)
        p_p = (y_dot + k_r_dot) / k_r
        flow_ratio = np.where(k_i_dot != 0.0,
                              (y_dot + k_r_dot) / np.where(k_i_dot != 0.0, k_i_dot, np.nan),
                              np.nan)

    if cal.p_b_source == "population_growth" and population_growth is not None:
        p_b, source = np.asarray(population_growth, dtype=float), "population_growth"
        if p_b.shape != y.shape:
            raise FitError("population growth is not aligned to the observed path")
    else:
        p_b, source = flow_ratio, "flow_ratio"
    return Identities(r=r, alpha=alpha, p_p=p_p, p_b=p_b, p_b_flow_ratio=flow_ratio,
                      p_b_source=source)


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------

def _scale_bounds(values: np.ndarray, low: float, high: float,
                  fallback: tuple[float, float] = (0.25, 4.0)) -> tuple[float, float]:
    """Multiplicative bounds that keep a parameter inside [low, high] at its median level."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return fallback
    if float(np.median(np.abs(finite))) <= 0.0:
        return fallback
    signed = float(np.median(finite))
    if signed == 0.0:
        return fallback
    lower, upper = sorted((low / signed, high / signed))
    return fallback if upper <= lower else (lower, upper)


def _interpolator(time: np.ndarray, values: np.ndarray) -> Callable[[float], float]:
    """Linear between observations, flat outside: a stiff solver probes past the ends."""
    finite = np.isfinite(values)
    if not finite.any():
        return lambda _t: 0.0
    t_finite = np.asarray(time, dtype=float)[finite]
    v_finite = np.asarray(values, dtype=float)[finite]

    def evaluate(t: float) -> float:
        return float(np.interp(t, t_finite, v_finite, left=v_finite[0], right=v_finite[-1]))

    return evaluate


def _parameters(vector: np.ndarray, path: ObservedPath,
                ids: Identities) -> tuple[Parameters, np.ndarray]:
    p_p_s, p_b_s, alpha_s, savings_s, stimulus_s, y0, k_r0, k_i0 = (float(v) for v in vector)
    t = path.time
    params = Parameters(
        p_s=_interpolator(t, np.asarray(path.savings_rate, dtype=float) * savings_s),
        p_p=_interpolator(t, ids.p_p * p_p_s),
        p_b=_interpolator(t, ids.p_b * p_b_s),
        alpha=_interpolator(t, ids.alpha * alpha_s),
        stimulus=_interpolator(t, np.asarray(path.stimulus, dtype=float) * stimulus_s),
    )
    return params, np.array([y0, k_r0, k_i0], dtype=float)


def _residuals(vector: np.ndarray, path: ObservedPath, ids: Identities,
               cal: Calibration) -> np.ndarray:
    params, initial = _parameters(vector, path, ids)
    t, n, s = path.time, path.length, cal.search
    penalty = s.divergence_penalty
    if np.any(initial <= 0.0):
        return np.full(3 * n, penalty)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            sim = simulate(initial, params, (float(t[0]), float(t[-1])), t_eval=t,
                           closure=cal.closure, method=s.method, rtol=s.rtol, atol=s.atol,
                           share=cal.share_form)
        except Exception:  # noqa: BLE001 - any integrator failure is a bad parameter set
            return np.full(3 * n, penalty)

    usable = min(sim.reached, n)
    pieces = []
    for simulated, observed in ((sim.Y, path.output), (sim.K_R, path.real_capital),
                                (sim.K_I, path.financial_capital)):
        values = np.asarray(simulated, dtype=float)[:usable]
        target = np.asarray(observed, dtype=float)[:usable]
        valid = usable
        if values.size:
            bad = np.flatnonzero(~np.isfinite(values) | (values <= 0.0))
            if bad.size:
                valid = int(bad[0])
        residual = np.full(n, penalty, dtype=float)
        if valid > 0:
            residual[:valid] = np.log(values[:valid]) - np.log(target[:valid])
        if valid < n:
            shortfall = (n - valid) / n
            residual[valid:] = penalty * (0.5 + 0.5 * shortfall)
        pieces.append(residual)
    return np.concatenate(pieces)


def _standard_errors(jacobian: np.ndarray, residual: np.ndarray, k: int) -> np.ndarray:
    """Gauss-Newton: residual variance times inv(J'J). NaN where J'J is singular."""
    dof = max(1, residual.size - k)
    variance = float(residual @ residual) / dof
    try:
        covariance = variance * np.linalg.inv(jacobian.T @ jacobian)
    except np.linalg.LinAlgError:
        return np.full(k, np.nan)
    diagonal = np.diag(covariance)
    return np.where(diagonal >= 0.0, np.sqrt(np.abs(diagonal)), np.nan)


@dataclass
class FitOutcome:
    free_parameters: dict[str, float]
    standard_errors: dict[str, float]
    identifiability: dict[str, str]
    weakly_identified: list[str]
    converged: bool
    message: str
    evaluations: int
    integration_accuracy: str
    simulated: dict[str, np.ndarray] | None
    residuals: dict[str, float]
    two_body_worst: float
    identity_diagnostics: dict[str, float]
    identity_corrections: dict[str, float]
    notes: list[str] = field(default_factory=list)


def fit(path: ObservedPath, ids: Identities, cal: Calibration) -> FitOutcome:
    """Calibrate one economy. Deterministic: the same inputs give the same numbers."""
    ranges, s, tol = cal.parameter_ranges, cal.search, cal.initial_state_tolerance
    p_p_b = _scale_bounds(ids.p_p, ranges["p_p"].lower, ranges["p_p"].upper)
    p_b_b = _scale_bounds(ids.p_b, ranges["p_b"].lower, ranges["p_b"].upper)
    alpha_b = _scale_bounds(ids.alpha, ranges["alpha"].lower, ranges["alpha"].upper)
    p_s_b = _scale_bounds(np.asarray(path.savings_rate, dtype=float), ranges["p_s"].lower,
                          ranges["p_s"].upper)
    y0, kr0, ki0 = (float(path.output[0]), float(path.real_capital[0]),
                    float(path.financial_capital[0]))
    lower = np.array([p_p_b[0], p_b_b[0], alpha_b[0], p_s_b[0], cal.stimulus_scale.lower,
                      (1.0 - tol) * path.output[0], (1.0 - tol) * path.real_capital[0],
                      (1.0 - tol) * path.financial_capital[0]])
    upper = np.array([p_p_b[1], p_b_b[1], alpha_b[1], p_s_b[1], cal.stimulus_scale.upper,
                      (1.0 + tol) * path.output[0], (1.0 + tol) * path.real_capital[0],
                      (1.0 + tol) * path.financial_capital[0]])
    start = np.clip(np.array([1.0, 1.0, 1.0, 1.0, 1.0, y0, kr0, ki0], dtype=float),
                    lower, upper)

    solution = least_squares(
        _residuals, start, bounds=(lower, upper), args=(path, ids, cal),
        max_nfev=s.max_evaluations, xtol=s.xtol, ftol=s.ftol,
        # Explicit scales: corrections are order one, initial states order 1e12.
        x_scale=np.array([1.0] * 5 + [max(abs(float(v)), 1.0) for v in start[5:]]),
        diff_step=s.diff_step, loss=s.loss, f_scale=s.f_scale,
    )

    fitted = {name: float(v) for name, v in zip(FREE_PARAMETERS, solution.x)}
    errors_arr = _standard_errors(np.atleast_2d(solution.jac), np.asarray(solution.fun),
                                  len(FREE_PARAMETERS))
    errors = {name: float(v) for name, v in zip(FREE_PARAMETERS, errors_arr)}
    identifiability, weak = {}, []
    for name in FREE_PARAMETERS:
        value, error = fitted[name], errors[name]
        if not np.isfinite(error):
            identifiability[name] = "not identified: the data do not constrain this parameter"
            weak.append(name)
        elif abs(value) < 1e-12:
            identifiability[name] = "at zero, so a relative standard error is undefined"
        elif error / abs(value) > cal.weak_identification_ratio:
            identifiability[name] = (
                f"weakly identified: standard error is {error / abs(value):.0%} of the value")
            weak.append(name)
        else:
            identifiability[name] = (
                f"identified: standard error is {error / abs(value):.0%} of the value")

    # Report the path the search scored; upgrade to reporting tolerance when it integrates there.
    params, initial = _parameters(solution.x, path, ids)
    span = (float(path.time[0]), float(path.time[-1]))
    notes: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        final = simulate(initial, params, span, t_eval=path.time, closure=cal.closure,
                         method=s.method, rtol=s.rtol, atol=s.atol, share=cal.share_form)
        accuracy = "search"
        verification = simulate(initial, params, span, t_eval=path.time, closure=cal.closure,
                                method=cal.integrator.method, rtol=cal.integrator.rtol,
                                atol=cal.integrator.atol, share=cal.share_form)
    bounded = cal.share_form == "bounded"
    if verification.success and verification.reached == path.length:
        final, accuracy = verification, "reporting"
    else:
        notes.append(
            "the fitted parameters integrate at search tolerance but not at reporting tolerance, "
            + ("so the reporting integrator could not follow the path; "
               if bounded else
               "so the simulated path runs close to the finite-time singularity of the unbounded "
               "investment share; ")
            + "prefer the qualitative reading to the level")

    integrable = final.success and final.reached == path.length
    simulated: dict[str, np.ndarray] | None = None
    residuals: dict[str, float] = {}
    diagnostics: dict[str, float] = {}
    if integrable:
        simulated = {"Y": final.Y, "K_R": final.K_R, "K_I": final.K_I}
        for name, values, observed in (("Y", final.Y, path.output),
                                       ("K_R", final.K_R, path.real_capital),
                                       ("K_I", final.K_I, path.financial_capital)):
            scale = np.maximum(np.abs(np.asarray(observed, dtype=float)), 1e-9)
            relative = (np.asarray(values, dtype=float) - observed) / scale
            residuals[name] = (float(np.sqrt(np.mean(relative ** 2)))
                               if np.all(np.isfinite(relative)) else float("inf"))
        collected: dict[str, list[float]] = {}
        implied: list[float] = []
        for i, t in enumerate(final.t):
            state = (final.Y[i], final.K_R[i], final.K_I[i])
            for key, value in identity_residuals(float(t), state, params, cal.closure,
                                                 cal.share_form).items():
                collected.setdefault(key, []).append(value)
            implied.append(p_p_implied_output_growth(float(t), state, params, cal.share_form))
        for key, values in collected.items():
            finite = [v for v in values if np.isfinite(v)]
            diagnostics[f"{key}_mean_abs_residual"] = (float(np.mean(np.abs(finite)))
                                                       if finite else float("nan"))
        diagnostics["p_p_identity_implied_mean_output_growth"] = float(np.mean(implied))
        if diagnostics["p_p_identity_implied_mean_output_growth"] < 0.0:
            notes.append(
                "the p_p identity with the real-capital equation implies negative output growth "
                "over this window: the documented over-determination, not a finding about the "
                "economy. It is reported and not enforced")
    else:
        accuracy = "none"
        residuals = {name: float("inf") for name in ("Y", "K_R", "K_I")}
        notes.append(
            "the fitted parameters do not integrate over the whole window, so no simulated path "
            "is reported " + ("(a state left the positive domain)" if bounded else
                              "(finite-time singularity of the unbounded investment share)"))

    if bounded and simulated is not None:
        ratio = np.asarray(final.K_R, dtype=float) / np.asarray(final.Y, dtype=float)
        above = int(np.sum(ratio > 1.0))
        if above:
            notes.append(
                f"the simulated real capital exceeds output in {above} of {path.length} window "
                f"years (K_R/Y up to {float(np.max(ratio)):.2f}), where the bounded investment share "
                "holds r at zero instead of the written 1 - K_R/Y (TB-27)")
    corrections = {name: abs(fitted[name] - 1.0) for name in IDENTITY_CORRECTIONS}
    worst = max(corrections, key=corrections.get)
    if corrections[worst] > cal.identity_correction_note:
        notes.append(
            f"the identity corrections moved materially from one, the largest {worst} at "
            f"{fitted[worst]:.3f}: this is how far the section 0.2 definitions and the equations "
            "of motion disagree on this window")
    if not solution.success:
        notes.append(f"the optimiser did not converge: {solution.message}")
    if weak:
        notes.append(f"weakly identified parameters: {', '.join(weak)}")

    return FitOutcome(
        free_parameters=fitted, standard_errors=errors, identifiability=identifiability,
        weakly_identified=weak, converged=bool(solution.success), message=str(solution.message),
        evaluations=int(solution.nfev), integration_accuracy=accuracy, simulated=simulated,
        residuals=residuals, two_body_worst=float(final.two_body_worst_relative),
        identity_diagnostics=diagnostics, identity_corrections=corrections, notes=notes,
    )
