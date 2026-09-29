"""Forward projection: the calibrated model run past the end of the window. Pure.

A conditional, structural forecast: an economy at this saturation, with these fitted parameters,
evolves along a path of this shape if the last observed conditions persist, or as the forward
levers set them. Direction is its strongest reading; the timing of a turn is its weakest, so
dates are to be quoted as ranges and re-derived from the current data, never carried forward.

How it runs (follows ``Macro_Model/macrofield/projection.py``):

* **Parameters forward.** p_p, p_b, alpha, p_s and S are carried past the window by
  ``hold_last`` (the final observed value) or ``extend_trend`` (the mean change of the last five,
  clipped so it cannot change sign), with the fitted corrections applied as in the fit.
* **Levers act forward.** A stimulus or savings lever multiplies the projected path year by
  year; it never rescales the observed window, which would be a counterfactual about the past.
* **From the observed end state**, not the fitted one: the level fit is imperfect by design, and
  starting from the fit would put the projection where the model ended up.
* **Horizon search.** Where the path runs into the finite-time singularity of the unbounded
  investment share, the longest horizon that integrates is found by binary search and the rest is
  a straight line in logs: level from where the model got to, slope from the economy's observed
  history. Those years are flagged ``extrapolated`` and are not a model consequence.
* **One phase sequence.** The observed end state and the projection are classified together,
  starting from the latched phase at the window end, so an economy in the reordering stays there
  until saturation reaches the Foundation level.
* **Both Phase IV resolutions** when the projection ends above the band: debt deflation (the
  numerator falls) and hyperinflation (the denominator rises). The model does not choose.

From calibration 1.4.0 (review R-005, decided 28.09.2026) a calibration with a ``crisis``
section replaces the last point, and the path no longer runs far above its limit:

* **Soft ceiling.** From ``damping_onset`` (3.5, the balanced band's upper bound) the growth of
  saturation is damped on a sine arc in logs, dx/dt = g sqrt(1 - u^2) with u the position
  between the onset and the policy's turn level, so the path bends and arrives at the turn level
  with zero slope in finite time. No clamp: a path whose growth fades before it gets there simply
  stays below. Each policy turns at its own position in the band (4.5 to 5.5 around 5.0):
  depression early and low, deferral late and high.
* **Crisis, then reset.** At the turn the path follows the selected policy of ``Scenario_SAA.m``
  through the acute crisis (60 months): nominal output follows the policy's price level (real
  output flat), financial claims are written down by its defaults and valuations, so saturation
  corrects through the numerator, the denominator or both (resolution.py). It then declines to
  the reset target (the Foundation level) over the reset period (35 years) on a half-cosine in
  logs, with output growing at its observed rate and K_R/Y returning to its early-phase level
  on the same curve.
* **Re-integration.** From the reset state the model runs again with early-phase parameters
  (the window years in Phase 1 or 2, else its first five), under the same ceiling.
* **All four policies** are computed as ``ResolutionScenario`` views; the main path follows the
  one selected (``resolution_policy``, a run and ``/project`` parameter). The phase is 4 through
  crisis and reset (the reordering is over when the reset is), then classified afresh.

From calibration 1.5.0 (TB-08, TB-27) the model itself integrates to the horizon:

* **Bounded investment share.** The fit and the projection run the equations with
  r = max(0, 1 - K_R/Y) (dynamics.py), so there is no finite-time singularity; the horizon search
  and the log-linear tail remain as a fallback.
* **Parameters within their ranges.** Every parameter carried forward, and every post-reset
  early-phase parameter, is held inside ``Calibration.parameter_ranges``; a held parameter is
  named in the notes. With alpha in [0, 1] the savings flow into K_I cannot drain it through
  zero (JP and BD did under 1.4.0).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from . import resolution as policy_paths
from .contracts import (
    Calibration,
    ControlSpec,
    CrisisReset,
    EconomyState,
    Projection,
    ProjectedTransition,
    ResolutionScenario,
    SaturationCeiling,
    Turn,
)
from .dynamics import Parameters, simulate
from .phases import classify_sequence


class ProjectionError(ValueError):
    """A projection cannot be produced. The message says why."""


@dataclass(frozen=True)
class Settings:
    horizon: int
    parameter_mode: str
    stimulus: ControlSpec
    savings: ControlSpec
    deflation_capital_decline: float
    inflation_output_growth: float
    #: Project to this calendar year (R-005); overrides ``horizon`` when set.
    horizon_until: Optional[int] = None
    #: The policy the main path follows at the turn (R-005); ``None`` for a calibration without
    #: a crisis section.
    resolution_policy: Optional[str] = None


def lever(spec: ControlSpec, years: np.ndarray) -> np.ndarray:
    """One multiplier per projected year."""
    out = np.full(years.shape, float(spec.base))
    if spec.mode == "constant":
        return out
    start, target = float(spec.start_year), float(spec.target)
    if spec.mode == "step":
        out[years >= start] = target
        return out
    end = float(spec.end_year)
    if spec.mode == "ramp":
        if end == start:
            out[years >= start] = target
            return out
        rising = (years >= start) & (years <= end)
        out[rising] = spec.base + (target - spec.base) * (years[rising] - start) / (end - start)
        out[years > end] = target
        return out
    out[(years >= start) & (years <= end)] = target   # pulse
    return out


def forward(values: np.ndarray, mode: str, horizon: int) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ProjectionError("a parameter path has no finite values to carry forward")
    last = float(finite[-1])
    if mode == "hold_last" or finite.size < 6:
        return np.full(horizon, last)
    step = float(np.mean(np.diff(finite[-6:])))
    extended = last + step * np.arange(1, horizon + 1)
    return np.clip(extended, 0.0, None) if last >= 0.0 else np.clip(extended, None, 0.0)


def _step_hold(values: np.ndarray):
    padded = np.concatenate(([values[0]], values))

    def evaluate(t: float) -> float:
        return float(padded[int(np.clip(np.floor(t), 0, padded.size - 1))])

    return evaluate


def _arr(path) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in path], dtype=float)


def _mean_log_growth(values: np.ndarray, window: Optional[int] = None) -> float:
    series = np.asarray(values, dtype=float)
    if window is not None:
        series = series[-min(window, series.size):]
    if series.size < 2 or not np.all(series > 0.0):
        return float("nan")
    return float(np.mean(np.diff(np.log(series))))


def directional_accuracy(observed: np.ndarray, simulated: np.ndarray) -> Optional[float]:
    """Share of years in which the simulated change has the sign of the observed change."""
    o, s = np.diff(observed), np.diff(simulated)
    ok = np.isfinite(o) & np.isfinite(s)
    return float(np.mean(np.sign(o[ok]) == np.sign(s[ok]))) if ok.any() else None


# ---------------------------------------------------------------------------
# Integration and the horizon search
# ---------------------------------------------------------------------------

#: (p_s, p_p, p_b, alpha, stimulus) over ``horizon`` years, first entry = first projected year.
ParameterArrays = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def within_ranges(cal: Calibration, p_s: np.ndarray, p_p: np.ndarray, p_b: np.ndarray,
                  alpha: np.ndarray) -> tuple[tuple[np.ndarray, ...], dict[str, tuple[float, float]]]:
    """(p_s, p_p, p_b, alpha) held inside the calibration's meaningful ranges where
    ``projection.parameters_within_ranges`` is set (TB-27), and {name: (value, held value)} at
    the first year each had to be held. Otherwise the arrays unchanged and {}."""
    arrays = {"p_s": p_s, "p_p": p_p, "p_b": p_b, "alpha": alpha}
    if not cal.projection.parameters_within_ranges:
        return tuple(arrays.values()), {}
    held: dict[str, tuple[float, float]] = {}
    out = []
    for name, values in arrays.items():
        values = np.asarray(values, dtype=float)
        bounds = cal.parameter_ranges[name]
        clipped = np.clip(values, bounds.lower, bounds.upper)
        moved = np.flatnonzero(clipped != values)
        if moved.size:
            held[name] = (float(values[moved[0]]), float(clipped[moved[0]]))
        out.append(clipped)
    return tuple(out), held


def _window_parameters(state: EconomyState, s: Settings, years: np.ndarray,
                       cal: Optional[Calibration] = None,
                       held: Optional[dict] = None) -> ParameterArrays:
    """The fitted parameters carried past the window, with the levers applied; held inside
    their ranges where ``cal`` says so (those held are written to ``held``)."""
    fitted = state.fit.free_parameters
    ids = state.identities
    mode, horizon = s.parameter_mode, years.size
    p_p = forward(_arr(ids.p_p), mode, horizon) * fitted["p_p_scale"]
    p_b = forward(_arr(ids.p_b), mode, horizon) * fitted["p_b_scale"]
    alpha = forward(_arr(ids.alpha), mode, horizon) * fitted["alpha_scale"]
    p_s = (forward(_arr(state.inputs.p_s), mode, horizon) * fitted["savings_scale"]
           * lever(s.savings, years))
    stim = (forward(_arr(state.inputs.S), mode, horizon) * fitted["stimulus_scale"]
            * lever(s.stimulus, years))
    if cal is not None:
        (p_s, p_p, p_b, alpha), moved = within_ranges(cal, p_s, p_p, p_b, alpha)
        if held is not None:
            held.update(moved)
    return p_s, p_p, p_b, alpha, stim


def _run(initial: tuple[float, float, float], arrays: ParameterArrays, cal: Calibration,
         horizon: int):
    """(Y, K_R, K_I) for ``horizon`` years from ``initial``, or None where it does not integrate."""
    p_s, p_p, p_b, alpha, stim = (a[:horizon] for a in arrays)
    params = Parameters(p_s=_step_hold(p_s), p_p=_step_hold(p_p), p_b=_step_hold(p_b),
                        alpha=_step_hold(alpha), stimulus=_step_hold(stim))
    t = np.arange(0.0, horizon + 1.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            sim = simulate(initial, params, (0.0, float(horizon)), t_eval=t, closure=cal.closure,
                           method=cal.integrator.method, rtol=cal.integrator.rtol,
                           atol=cal.integrator.atol, share=cal.share_form)
        except ValueError:
            return None
    if not sim.success or sim.reached != t.size:
        return None
    # A state at or below zero has no economic meaning (and no logarithm): the path has left the
    # domain of the model even if the solver kept going, exactly as the fit treats it.
    if not (np.all(sim.Y > 0.0) and np.all(sim.K_R > 0.0) and np.all(sim.K_I > 0.0)):
        return None
    return sim.Y[1:], sim.K_R[1:], sim.K_I[1:]


def _integrate(state: EconomyState, cal: Calibration, s: Settings, horizon: int):
    """(years, Y, K_R, K_I) for ``horizon`` years, or None where it does not integrate."""
    years = np.arange(state.years[-1] + 1, state.years[-1] + horizon + 1, dtype=float)
    initial = (state.observed.Y[-1], state.observed.K_R[-1], state.observed.K_I[-1])
    out = _run(initial, _window_parameters(state, s, years, cal), cal, horizon)
    if out is None:
        return None
    return (years.astype(int),) + out


def _search(attempt: Callable[[int], object], horizon: int, max_attempts: int,
            attempts: list[int]):
    """(best, reached): the full horizon if it integrates, else the longest one found by
    binary search within ``max_attempts``; (None, 0) where nothing integrates."""
    best, reached = attempt(horizon), horizon
    if best is None:
        low, high, best, reached = 1, horizon - 1, None, 0
        while low <= high and len(attempts) < max_attempts:
            mid = (low + high) // 2
            out = attempt(mid)
            if out is None:
                high = mid - 1
            else:
                best, reached, low = out, mid, mid + 1
    return best, reached


def _tail(state: EconomyState, cal: Calibration, bases: tuple[np.ndarray, ...], missing: int,
          notes: Optional[list[str]]) -> tuple[np.ndarray, ...]:
    """Extend Y, K_R, K_I by ``missing`` years on a straight line in logs, slope from the
    observed history; the divergence notes go to ``notes``."""
    pc = cal.projection
    observed = {"Y": _arr(state.observed.Y), "K_R": _arr(state.observed.K_R),
                "K_I": _arr(state.observed.K_I)}
    tails = []
    for name, base in zip(("Y", "K_R", "K_I"), bases):
        historical = _mean_log_growth(observed[name])
        rate = historical if np.isfinite(historical) else 0.0
        if base.size == 0:
            raise ProjectionError("nothing to extrapolate from")
        tails.append(np.concatenate([base, base[-1] * np.exp(rate * np.arange(1, missing + 1))]))
        diverging = _mean_log_growth(base, pc.extrapolation_window)
        if (notes is not None and np.isfinite(diverging) and np.isfinite(historical)
                and abs(diverging) > 3 * abs(historical)):
            notes.append(f"{name} was growing at {diverging:+.1%} a year when the integration "
                         f"stopped against an observed {historical:+.1%}; the tail uses the "
                         "observed rate")
    return tuple(tails)


def scenarios(start_year: int, capital_ratio: float, target: float, horizon: int,
              decline: float, growth: float) -> tuple[ResolutionScenario, ...]:
    """Both Phase IV resolutions from a starting capital-to-output ratio above the target."""
    years = tuple(range(start_year, start_year + horizon + 1))
    steps = np.arange(horizon + 1, dtype=float)
    deflation = np.maximum(capital_ratio * np.power(1.0 - decline, steps), target)
    inflation = np.maximum(capital_ratio / np.power(1.0 + growth, steps), target)
    return (
        ResolutionScenario(
            name="debt_deflation", years=years, capital_ratio=tuple(float(v) for v in deflation),
            mechanism=(f"capital is destroyed at {decline:.0%} a year while output is held flat, "
                       "so the ratio corrects through the numerator"),
            asset_implication=("financial claims fall in nominal terms; cash and high-quality "
                               "sovereign debt hold value best, real assets fall less than "
                               "financial ones")),
        ResolutionScenario(
            name="hyperinflation", years=years, capital_ratio=tuple(float(v) for v in inflation),
            mechanism=(f"nominal output rises at {growth:.0%} a year while capital is held flat "
                       "in nominal terms, so the ratio corrects through the denominator"),
            asset_implication=("financial claims are destroyed in real terms; value-preserving "
                               "real assets outperform")),
    )


def _settings_dict(s: Settings, horizon: int) -> dict[str, object]:
    out: dict[str, object] = {"horizon": horizon, "parameter_mode": s.parameter_mode,
                              "stimulus": s.stimulus.model_dump(), "savings": s.savings.model_dump(),
                              "deflation_capital_decline": s.deflation_capital_decline,
                              "inflation_output_growth": s.inflation_output_growth}
    if s.horizon_until is not None:
        out["horizon_until"] = s.horizon_until
    if s.resolution_policy is not None:
        out["resolution_policy"] = s.resolution_policy
    return out


def project(state: EconomyState, cal: Calibration, s: Settings) -> Projection:
    """Project one economy. Unavailable, with the reason, where nothing can be continued."""
    horizon = s.horizon
    if s.horizon_until is not None and state.years:
        horizon = int(s.horizon_until) - int(state.years[-1])
    settings = _settings_dict(s, horizon)
    if state.status != "ok" or state.fit is None:
        return Projection(status="unavailable", reason="the economy itself is unavailable",
                          settings=settings)
    if horizon < 1:
        return Projection(status="unavailable", settings=settings,
                          reason=f"the window already ends in {state.years[-1]}, at or after the "
                                 f"horizon year {s.horizon_until}")
    reproduces = state.simulated is not None
    if not reproduces and cal.projection.require_integrable_fit:
        return Projection(
            status="unavailable", settings=settings, fit_reproduces_window=False,
            reason=("the calibration produced no integrable path over the window, so there is "
                    "nothing to continue: a projection from a model that cannot reproduce the "
                    "observed window would be arithmetic, not a forecast"))

    pc = cal.projection
    attempts: list[int] = []
    cache: dict[int, object] = {}

    def attempt(h: int):
        if h not in cache:
            attempts.append(h)
            cache[h] = _integrate(state, cal, s, h)
        return cache[h]

    best, reached = _search(attempt, horizon, pc.max_horizon_attempts, attempts)
    if best is None:
        return Projection(
            status="unavailable", settings=settings, requested_horizon=horizon,
            reason=(f"no horizon integrates (tried {sorted(attempts)}), so there is nothing to "
                    "extrapolate from"))

    years, y, k_r, k_i = (np.asarray(a) for a in best)
    notes: list[str] = [
        "read the direction and the order of events, not the dates: turn timing is the weakest "
        "part of this output and must be re-derived from the current data, never carried forward"]
    held: dict[str, tuple[float, float]] = {}
    _window_parameters(state, s, np.arange(state.years[-1] + 1, state.years[-1] + horizon + 1,
                                           dtype=float), cal, held)
    if held:
        notes.append("parameters carried forward are held inside their meaningful ranges (TB-27): "
                     + "; ".join(f"{name} {value:.4g} held at {bound:g}"
                                 for name, (value, bound) in held.items()))
    if cal.share_form == "bounded":
        above = np.flatnonzero(np.asarray(k_r) > np.asarray(y))
        if above.size:
            notes.append(f"real capital reaches output in {int(years[above[0]])}; from there the "
                         "bounded investment share holds r at zero (financial capital stops flowing "
                         "into real capital) where the written r = 1 - K_R/Y would turn negative "
                         "and run into a finite-time singularity (TB-27)")
    if not reproduces:
        notes.insert(0, "WEAK EVIDENCE: the calibrated equations do not reproduce this economy's "
                        "observed window (they run into the finite-time singularity), so this "
                        "projection rests on fitted parameters the window does not confirm. It "
                        "starts from the observed end state and is shown so every economy has a "
                        "forward path; read it as a direction under the fitted parameters only")
    missing = horizon - reached
    extrapolated = np.zeros(horizon, dtype=bool)
    if missing > 0:
        y, k_r, k_i = _tail(state, cal, (y, k_r, k_i), missing, notes)
        years = np.arange(state.years[-1] + 1, state.years[-1] + horizon + 1)
        extrapolated[reached:] = True
        notes.append(f"the model integrated {reached} of {horizon} years; the remaining "
                     f"{missing} are a straight line in logs (level from the integrated end, slope "
                     "from the observed history), not a model consequence")

    # The saturation axis is not a state variable: it is carried by the observed credit share of
    # K_I at the window end, which under the assembly is 1 / capital scale.
    share = state.inputs.saturation[-1] * state.observed.Y[-1] / state.observed.K_I[-1]

    if pc.crisis is not None:
        return _project_with_ceiling(state, cal, s, horizon, settings, reproduces, notes,
                                     years, y, k_r, k_i, reached, extrapolated, share)

    saturation = share * k_i / y
    real_to_financial = k_r / k_i
    capital_saturation = (k_r + k_i) / y

    t = cal.phases
    end_latched = state.diagnostics.phase[-1] == 4
    seq_sat = np.concatenate(([state.inputs.saturation[-1]], saturation))
    seq_kr = np.concatenate(([state.observed.K_R[-1]], k_r))
    seq_ki = np.concatenate(([state.observed.K_I[-1]], k_i))
    seq_y = np.concatenate(([state.observed.Y[-1]], y))
    # The commercial-bank share is not a state variable either: held at its last value.
    last_share = state.inputs.commercial_bank_share[-1] if state.inputs.commercial_bank_share else None
    shares = None if last_share is None else np.full(seq_sat.shape, last_share)
    latched, _ = classify_sequence(seq_sat, seq_kr, seq_ki, seq_y, t, start_latched=end_latched,
                                   commercial_share=shares)
    phases = [c.phase for c in latched]
    transitions = tuple(
        ProjectedTransition(year=int(years[i - 1]), from_phase=phases[i - 1], to_phase=phases[i],
                            saturation=float(saturation[i - 1]),
                            real_to_financial=float(real_to_financial[i - 1]),
                            extrapolated=bool(extrapolated[i - 1]))
        for i in range(1, len(phases)) if phases[i] != phases[i - 1])

    resolution: tuple[ResolutionScenario, ...] = ()
    if capital_saturation[-1] > t.balanced_band.upper:
        resolution = scenarios(int(years[-1]), float(capital_saturation[-1]),
                               t.balanced_band.upper, horizon, s.deflation_capital_decline,
                               s.inflation_output_growth)
        notes.append(f"the projected capital-to-output ratio ends at {capital_saturation[-1]:.2f}, "
                     f"above the band's upper bound of {t.balanced_band.upper:.2f}, so both Phase IV "
                     "resolution paths are shown; the model does not choose between them")

    to_float = lambda a: tuple(float(v) for v in a)  # noqa: E731
    return Projection(
        status="ok", from_year=state.years[-1], years=tuple(int(v) for v in years),
        Y=to_float(y), K_R=to_float(k_r), K_I=to_float(k_i), saturation=to_float(saturation),
        real_to_financial=to_float(real_to_financial),
        capital_saturation=to_float(capital_saturation), phase=tuple(phases[1:]),
        extrapolated=tuple(bool(v) for v in extrapolated), requested_horizon=horizon,
        integrated_years=reached, fit_reproduces_window=reproduces,
        transitions=transitions, scenarios=resolution,
        directional_accuracy=_accuracy(state, reproduces), settings=settings,
        assumptions=_assumptions(s), notes=tuple(notes),
    )


def _accuracy(state: EconomyState, reproduces: bool) -> dict[str, Optional[float]]:
    return {name: (directional_accuracy(_arr(getattr(state.observed, name)),
                                        _arr(getattr(state.simulated, name)))
                   if reproduces else None)
            for name in ("Y", "K_R", "K_I")}


def _assumptions(s: Settings) -> tuple[str, ...]:
    levers = [f"{name} lever {spec.mode}" for name, spec in (("stimulus", s.stimulus),
                                                             ("savings", s.savings))
              if not spec.is_identity]
    return (
        f"parameters carried forward by {s.parameter_mode}: this answers where the economy goes "
        "if the last observed conditions persist" + (f", with {', '.join(levers)}" if levers else ""),
        "the fitted identity corrections are held at their calibrated values",
        "the credit share of financial capital is held at its observed end value, because the "
        "saturation axis is not a state variable of the system",
    )


# ---------------------------------------------------------------------------
# R-005: soft ceiling, crisis, reset, re-integration
# ---------------------------------------------------------------------------

def bend(start: float, unbounded: np.ndarray, onset: float, level: float
         ) -> tuple[np.ndarray, Optional[int]]:
    """The saturation path under the soft ceiling, and the index of the turn (or None).

    Year by year the unbounded path's log growth g is applied to x = log saturation, damped
    above ``onset``: dx/dt = g sqrt(1 - u^2), u = (x - log onset) / (log level - log onset).
    With g constant over the year this is a sine arc, solved exactly: the path bends and meets
    ``level`` with zero slope in finite time, which is the turn. Falling growth is not damped.
    A path that starts at or above ``level`` and rises turns in its first year, where it is.
    The returned path ends at the turn.
    """
    x_on, x_top = math.log(onset), math.log(level)
    width = x_top - x_on
    x = math.log(start)
    previous = start
    out: list[float] = []
    for k, raw in enumerate(np.asarray(unbounded, dtype=float)):
        g = math.log(raw) - math.log(previous)
        previous = raw
        if g <= 0.0:
            x += g
            out.append(math.exp(x))
            continue
        if x >= x_top:
            out.append(math.exp(x))
            return np.array(out), k
        remaining = 1.0
        if x < x_on:
            need = (x_on - x) / g
            if need >= 1.0:
                x += g
                out.append(math.exp(x))
                continue
            x, remaining = x_on, 1.0 - need
        theta = math.asin(min(1.0, (x - x_on) / width)) + g * remaining / width
        if theta >= math.pi / 2.0:
            out.append(level)
            return np.array(out), k
        x = x_on + width * math.sin(theta)
        out.append(math.exp(x))
    return np.array(out), None


def reset_target(state: EconomyState, cal: Calibration) -> tuple[float, int, str]:
    """(level, years, source) of the reset for this economy."""
    spec = cal.projection.crisis.reset
    override = spec.overrides.get(state.code)
    if override is not None:
        return override.level, override.years or spec.years, f"override: {override.reason}"
    return (spec.foundation_fraction * cal.phases.foundation_saturation_ceiling, spec.years,
            f"Foundation level ({spec.foundation_fraction:g} x the Foundation ceiling of "
            f"{cal.phases.foundation_saturation_ceiling:g})")


def early_phase_parameters(state: EconomyState, crisis: CrisisReset
                           ) -> tuple[dict[str, float], str]:
    """Mean fitted parameters over the window's early-phase years, and which years they are,
    with the mean K_R/Y (normalised) the reset returns the economy to."""
    phases = state.diagnostics.phase
    years = [i for i, p in enumerate(phases) if p in (1, 2)]
    if len(years) >= 3:
        which = f"the {len(years)} window years in Phase 1 or 2"
    else:
        years = list(range(min(crisis.early_phase_years, len(phases))))
        which = f"the first {len(years)} window years (fewer than three in Phase 1 or 2)"
    fitted = state.fit.free_parameters

    def mean(path, scale: float) -> float:
        values = _arr(path)
        chosen = values[years]
        chosen = chosen[np.isfinite(chosen)]
        if chosen.size == 0:
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                raise ProjectionError("a parameter path has no finite values")
            return float(finite[0]) * scale
        return float(np.mean(chosen)) * scale

    ratio = _arr(state.observed.K_R) / _arr(state.observed.Y)
    return {
        "real_capital_ratio": mean(ratio, 1.0),
        "p_p": mean(state.identities.p_p, fitted["p_p_scale"]),
        "p_b": mean(state.identities.p_b, fitted["p_b_scale"]),
        "alpha": mean(state.identities.alpha, fitted["alpha_scale"]),
        "p_s": mean(state.inputs.p_s, fitted["savings_scale"]),
        "stimulus_share": mean(state.inputs.stimulus_share, fitted["stimulus_scale"]),
    }, which


@dataclass
class _Path:
    """A projected path under construction, one entry per projected year."""

    y: list[float] = field(default_factory=list)
    k_r: list[float] = field(default_factory=list)
    saturation: list[float] = field(default_factory=list)
    segment: list[str] = field(default_factory=list)
    forced_phase: list[Optional[int]] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)

    def add(self, y: float, k_r: float, sat: float, segment: str,
            phase: Optional[int] = None) -> None:
        self.y.append(float(y)); self.k_r.append(float(k_r)); self.saturation.append(float(sat))
        self.segment.append(segment); self.forced_phase.append(phase)

    def __len__(self) -> int:
        return len(self.y)


def _policy_path(state: EconomyState, cal: Calibration, s: Settings, horizon: int,
                 policy_id: str, years: np.ndarray, y: np.ndarray, k_r: np.ndarray,
                 unbounded: np.ndarray, reached: int, share: float,
                 notes: Optional[list[str]]) -> _Path:
    """The full projected path under one policy: ceiling, turn, crisis, reset, re-integration,
    repeated until the horizon is filled."""
    pc = cal.projection
    ceiling: SaturationCeiling = pc.saturation_ceiling
    crisis: CrisisReset = pc.crisis
    policy = crisis.policies[policy_id]
    level = ceiling.turn_level(policy.turn_position)
    crisis_years = crisis.months // 12
    drivers = policy_paths.paths(policy, crisis.months)
    target, reset_years, target_source = reset_target(state, cal)
    growth = _mean_log_growth(_arr(state.observed.Y))
    growth = growth if np.isfinite(growth) else 0.0

    out = _Path()
    # The current segment: the model path from a start state, and how far it integrated.
    seg_y, seg_kr, seg_unbounded = y, k_r, unbounded
    seg_start_sat = float(state.inputs.saturation[-1])
    seg_reached = reached
    seg_kind = ("model", "extrapolated")
    while len(out) < horizon:
        bent, turn = bend(seg_start_sat, seg_unbounded, ceiling.damping_onset, level)
        upto = len(bent) if turn is None else turn + 1
        for i in range(upto):
            if len(out) >= horizon:
                break
            out.add(seg_y[i], seg_kr[i], bent[i], seg_kind[0] if i < seg_reached else seg_kind[1])
        if turn is None or len(out) >= horizon:
            break
        k = len(out) - 1                               # index of the turn year
        turn_sat, turn_y, turn_kr = out.saturation[k], out.y[k], out.k_r[k]
        # -- acute crisis: nominal output at the policy's price level, claims written down
        for j in range(1, crisis_years + 1):
            m = 12 * j - 1
            price = float(drivers["price_level"][m])
            sat = turn_sat * float(drivers["defaults"][m]) * float(drivers["valuations"][m]) / price
            if len(out) < horizon:
                out.add(turn_y * price, turn_kr * price, sat, "crisis", 4)
        m_end = crisis.months - 1
        price_end = float(drivers["price_level"][m_end])
        crisis_end = (turn_sat * float(drivers["defaults"][m_end])
                      * float(drivers["valuations"][m_end]) / price_end)
        # -- reset: half-cosine in logs to the target; output at its observed rate; K_R/Y back
        #    to its early-phase level on the same curve (near the singularity K_R/Y runs above
        #    one, where r = 1 - K_R/Y < 0 and the equations cannot integrate)
        goal = min(target, crisis_end)
        early, which = early_phase_parameters(state, crisis)
        y_end, ratio_end = turn_y * price_end, turn_kr / turn_y
        ratio_goal = early["real_capital_ratio"]
        reset_path = []
        for i in range(1, reset_years + 1):
            w = 0.5 * (1.0 - math.cos(math.pi * i / reset_years))
            sat = math.exp(math.log(crisis_end) + (math.log(goal) - math.log(crisis_end)) * w)
            ratio = math.exp(math.log(ratio_end) + (math.log(ratio_goal) - math.log(ratio_end)) * w)
            y_i = y_end * math.exp(growth * i)
            reset_path.append((y_i, ratio * y_i, sat))
            if len(out) < horizon:
                out.add(y_i, ratio * y_i, sat, "reset", 4)
        turn_year = int(years[k])
        out.turns.append(Turn(
            policy=policy_id, year=turn_year, level=float(turn_sat), turn_level=float(level),
            in_extrapolation=out.segment[k] in ("extrapolated", "post_reset_extrapolated"),
            crisis_months=crisis.months, crisis_end_year=turn_year + crisis_years,
            crisis_end_level=float(crisis_end), reset_years=reset_years,
            reset_end_year=turn_year + crisis_years + reset_years, reset_target=float(goal),
            reset_target_source=target_source))
        remaining = horizon - len(out)
        if remaining <= 0:
            break
        # -- re-integration from the reset state with early-phase parameters
        y0, kr0, sat0 = reset_path[-1]
        post_years = years[len(out):len(out) + remaining].astype(float)
        (e_ps, e_pp, e_pb, e_alpha), early_held = within_ranges(
            cal, np.full(remaining, early["p_s"]) * lever(s.savings, post_years),
            np.full(remaining, early["p_p"]), np.full(remaining, early["p_b"]),
            np.full(remaining, early["alpha"]))
        arrays = (e_ps, e_pp, e_pb, e_alpha,
                  np.full(remaining, early["stimulus_share"] * y0) * lever(s.stimulus, post_years))
        initial = (y0, kr0, sat0 * y0 / share)
        cache: dict[int, object] = {}
        tried: list[int] = []

        def attempt(h: int):
            if h not in cache:
                tried.append(h)
                cache[h] = _run(initial, arrays, cal, h)
            return cache[h]

        best, got = _search(attempt, remaining, pc.max_horizon_attempts, tried)
        if best is None:
            base = (np.array([y0]), np.array([kr0]), np.array([initial[2]]))
            ty, tkr, tki = _tail(state, cal, base, remaining, None)
            ty, tkr, tki = ty[1:], tkr[1:], tki[1:]
            got = 0
        else:
            ty, tkr, tki = best
            if got < remaining:
                ty, tkr, tki = _tail(state, cal, (ty, tkr, tki), remaining - got, None)
        if notes is not None:
            notes.append(f"after the reset ({turn_year + crisis_years + reset_years}) the model "
                         f"runs again with early-phase parameters ({which}); it integrated {got} "
                         f"of {remaining} years" + ("" if got == remaining else
                                                    ", the rest is a log-linear tail")
                         + ("" if not early_held else "; held inside their ranges: " + "; ".join(
                             f"{name} {value:.4g} at {bound:g}"
                             for name, (value, bound) in early_held.items())))
        seg_y, seg_kr, seg_unbounded = ty, tkr, share * tki / ty
        seg_start_sat, seg_reached = sat0, got
        seg_kind = ("post_reset", "post_reset_extrapolated")
    return out


def _project_with_ceiling(state: EconomyState, cal: Calibration, s: Settings, horizon: int,
                          settings: dict, reproduces: bool, notes: list[str], years: np.ndarray,
                          y: np.ndarray, k_r: np.ndarray, k_i: np.ndarray, reached: int,
                          extrapolated: np.ndarray, share: float) -> Projection:
    """R-005: the projection under the soft ceiling with the selected policy on the main path
    and all four policies as scenario views."""
    pc = cal.projection
    crisis, ceiling, t = pc.crisis, pc.saturation_ceiling, cal.phases
    selected = s.resolution_policy or crisis.default_policy
    years = np.asarray(years, dtype=int)
    unbounded = share * k_i / y

    last_share = state.inputs.commercial_bank_share[-1] if state.inputs.commercial_bank_share else None
    end_latched = state.diagnostics.phase[-1] == 4

    def phases_of(path: _Path) -> list[int]:
        """Latched from the window end up to the first turn, 4 through crisis and reset, then
        classified afresh from the first post-reset year."""
        sat = np.array(path.saturation)
        kr = np.array(path.k_r)
        yy = np.array(path.y)
        ki = sat * yy / share
        out: list[int] = []
        start, latched_start = 0, end_latched
        prefix = (state.inputs.saturation[-1], state.observed.K_R[-1], state.observed.K_I[-1],
                  state.observed.Y[-1])
        i = 0
        while i < len(path):
            if path.forced_phase[i] is not None:
                out.append(int(path.forced_phase[i]))
                i += 1
                continue
            j = i
            while j < len(path) and path.forced_phase[j] is None:
                j += 1
            if i == 0:
                seq = [np.concatenate(([prefix[0]], sat[i:j])), np.concatenate(([prefix[1]], kr[i:j])),
                       np.concatenate(([prefix[2]], ki[i:j])), np.concatenate(([prefix[3]], yy[i:j]))]
                shares = None if last_share is None else np.full(seq[0].shape, last_share)
                latched, _ = classify_sequence(*seq, t, start_latched=latched_start,
                                               commercial_share=shares)
                out.extend(c.phase for c in latched[1:])
            else:
                shares = None if last_share is None else np.full(j - i, last_share)
                latched, _ = classify_sequence(sat[i:j], kr[i:j], ki[i:j], yy[i:j], t,
                                               start_latched=False, commercial_share=shares)
                out.extend(c.phase for c in latched)
            i = j
        return out

    def label(policy_id: str) -> str:
        return f"crisis and reset ({policy_id})"

    paths: dict[str, _Path] = {}
    for policy_id in crisis.policies:
        paths[policy_id] = _policy_path(state, cal, s, horizon, policy_id, years, y, k_r,
                                        unbounded, reached, share,
                                        notes if policy_id == selected else None)

    main = paths[selected]
    sat = np.array(main.saturation)
    yy, kr = np.array(main.y), np.array(main.k_r)
    ki = sat * yy / share
    phases = phases_of(main)
    segment = tuple(main.segment)
    after_turn = [False] * horizon
    if main.turns:
        first = int(np.searchsorted(years, main.turns[0].year))
        for i in range(first + 1, horizon):
            after_turn[i] = True
    flagged = np.array([seg in ("extrapolated", "post_reset_extrapolated") for seg in segment])
    real_to_financial = kr / ki
    capital_saturation = (kr + ki) / yy
    seq_phase = [int(state.diagnostics.phase[-1])] + phases
    transitions = tuple(
        ProjectedTransition(year=int(years[i - 1]), from_phase=seq_phase[i - 1],
                            to_phase=seq_phase[i], saturation=float(sat[i - 1]),
                            real_to_financial=float(real_to_financial[i - 1]),
                            extrapolated=bool(flagged[i - 1]))
        for i in range(1, len(seq_phase)) if seq_phase[i] != seq_phase[i - 1])

    views = []
    for policy_id, path in paths.items():
        spec = crisis.policies[policy_id]
        drivers = policy_paths.paths(spec, crisis.months)
        common = dict(
            name=policy_id, label=spec.label, mechanism=spec.mechanism,
            asset_implication=spec.asset_implication, corrects_through=spec.corrects_through,
            target_mix=spec.target_mix,
            inflation=tuple(float(v) for v in drivers["inflation"]),
            defaults=tuple(float(v) for v in drivers["defaults"]),
            valuations=tuple(float(v) for v in drivers["valuations"]),
            price_level=tuple(float(v) for v in drivers["price_level"]))
        if not path.turns:
            views.append(ResolutionScenario(years=(), capital_ratio=(), **common))
            continue
        first = int(np.searchsorted(years, path.turns[0].year))
        p_sat = np.array(path.saturation)
        p_y, p_kr = np.array(path.y), np.array(path.k_r)
        p_ki = p_sat * p_y / share
        p_phase = phases_of(path)
        views.append(ResolutionScenario(
            years=tuple(int(v) for v in years[first:]),
            capital_ratio=tuple(float(v) for v in ((p_kr + p_ki) / p_y)[first:]),
            saturation=tuple(float(v) for v in p_sat[first:]),
            phase=tuple(p_phase[first:]), segment=tuple(path.segment[first:]),
            turn=path.turns[0], **common))

    display_until = pc.display_until
    lower = tuple(bool(display_until is not None and int(v) > display_until) for v in years)
    if main.turns:
        tu = main.turns[0]
        notes.append(
            f"soft ceiling: growth damped from {ceiling.damping_onset:g}; under {selected} the path "
            f"turns in {tu.year} at {tu.level:.2f} (policy turn level {tu.turn_level:.2f}, band "
            f"{ceiling.lower:g} to {ceiling.upper:g})" + (", in the extrapolated tail" if tu.in_extrapolation else "")
            + f"; {crisis.months}-month {selected} crisis to {tu.crisis_end_level:.2f} in "
            f"{tu.crisis_end_year}, then a {tu.reset_years}-year reset to {tu.reset_target:.2f} by "
            f"{tu.reset_end_year}. Years after the turn are model-derived crisis and reset, not "
            "extrapolation")
    else:
        notes.append(f"soft ceiling: growth damped from {ceiling.damping_onset:g}; under {selected} "
                     f"the path does not reach its turn level of "
                     f"{ceiling.turn_level(crisis.policies[selected].turn_position):.2f} by "
                     f"{int(years[-1])}")
    if display_until is not None and any(lower):
        notes.append(f"years after {display_until} carry a lower-confidence label: the model runs "
                     f"to {int(years[-1])} for planning over that period, views show {display_until} "
                     "by default")

    to_float = lambda a: tuple(float(v) for v in a)  # noqa: E731
    return Projection(
        status="ok", from_year=state.years[-1], years=tuple(int(v) for v in years),
        Y=to_float(yy), K_R=to_float(kr), K_I=to_float(ki), saturation=to_float(sat),
        real_to_financial=to_float(real_to_financial),
        capital_saturation=to_float(capital_saturation), phase=tuple(phases),
        extrapolated=tuple(bool(v) for v in flagged), requested_horizon=horizon,
        integrated_years=reached, fit_reproduces_window=reproduces,
        transitions=transitions, scenarios=tuple(views),
        directional_accuracy=_accuracy(state, reproduces), settings=settings,
        assumptions=_assumptions(s) + (
            f"at the turn the path follows the {selected} policy of Scenario_SAA.m: nominal output "
            "at the policy's price level with real output flat, financial claims written down by "
            "its defaults and valuations; over the reset output grows at its observed rate and K_R/Y "
            "returns to its early-phase level",),
        notes=tuple(notes),
        resolution_policy=selected, segment=segment,
        segment_label=tuple(label(selected) if a else None for a in after_turn),
        lower_confidence=lower, display_until=display_until, turns=tuple(main.turns),
        ceiling=ceiling, unbounded_saturation=to_float(unbounded),
    )


def settings_from(cal: Calibration, horizon: Optional[int] = None,
                  parameter_mode: Optional[str] = None,
                  stimulus: Optional[ControlSpec] = None, savings: Optional[ControlSpec] = None,
                  deflation_capital_decline: Optional[float] = None,
                  inflation_output_growth: Optional[float] = None,
                  resolution_policy: Optional[str] = None,
                  horizon_until: Optional[int] = None) -> Settings:
    """Settings from the calibration's defaults and any overrides. An explicit ``horizon``
    (years) wins over the calibration's ``horizon_until``; an explicit ``horizon_until`` wins
    over both. ``resolution_policy`` only applies to a calibration with a crisis section."""
    d = cal.projection
    until = horizon_until if horizon_until is not None else (None if horizon else d.horizon_until)
    policy = None
    if d.crisis is not None:
        policy = resolution_policy or d.crisis.default_policy
    return Settings(
        horizon=horizon or d.horizon,
        parameter_mode=parameter_mode or d.parameter_mode,
        stimulus=stimulus or ControlSpec(),
        savings=savings or ControlSpec(),
        deflation_capital_decline=deflation_capital_decline or d.deflation_capital_decline,
        inflation_output_growth=inflation_output_growth or d.inflation_output_growth,
        horizon_until=until,
        resolution_policy=policy,
    )
