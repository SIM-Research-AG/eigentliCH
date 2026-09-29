"""The 12 month forward measurement: an instrument's profile at the calibration's horizon.

**Why this exists (review R-003, decision D-02).** The role calibration measures *annual*
returns in the years classified into each phase. The cascade measured *monthly* returns in
the months tagged with each state. For most assets the two agree in sign; for a hedge they
do not. The same crisis months give gold -12.51 % over the month and a double-digit gain
over the following year, which is how a protection asset came out losing in crisis.
D-02 settles the horizon: an instrument's return in a state is measured over the 12 months
that follow a month in that state.

**The measurement.**

1. Every month with a signal is tagged with its calibration state, and so with its phase.
2. The window for a tagged month ``t`` is the 12 months ``t+1 .. t+12``: the state is read
   at the end of ``t`` and what follows is attributed to it. The window starts after the
   tagged month so that no month's own return is counted as its own forecast. A window
   with any month missing is dropped, never filled.
3. The window's value is the sum of the 12 monthly log returns -- an annual log return,
   the unit the calibration and every profile use.
4. Windows start every month, so they **overlap**: twelve consecutive crisis months give
   twelve windows sharing eleven months each, which is about one year of independent
   evidence, not twelve. The honest count is therefore reported as ``n_obs``:
   :func:`effective_observations`, the number of distinct months the windows cover,
   divided by 12. For one contiguous run that is ``(months + 11) / 12``, about months / 12;
   for months scattered years apart it approaches one per window, because those windows
   share nothing. The sufficiency floor of six applies to that count.
5. **Estimation is per phase, not per state, exactly as the calibration does it.** About
   240 signal months over 25 states leaves most states with no independent year at all;
   over five phases the measured phases carry six to sixteen effective years each. The
   five phase values are then read onto the 25 states by the calibration's own pchip, so
   an instrument's curve and its role's curve are built the same way and can be compared.
6. A phase below the floor is filled from D2's scaled role shape (``shape-scaled``),
   anchored on the phases this instrument did measure: the fill keeps the instrument's
   level and D2's amplitude, and takes only the *difference between phases* from the role.
   With no D2 fit (too little history) the phase is seeded from the role. Either way the
   label says so, and the band of five states around a filled knot carries the fill's
   label rather than ``interpolated``.

**The smoothing step (FMRE-22, the default estimator since 29 September 2026).**
:func:`smooth_forward` takes the result above and passes a light, shape-preserving smoother
across neighbouring states: :data:`SMOOTHING_PASSES` passes of the binomial kernel
(1/4, 1/2, 1/4), the two end states padded with themselves. Two guards keep it honest:

* **No phase value moves by more than** :data:`SMOOTHING_TOLERANCE` (one percentage point
  of annual log return). Where the kernel would move a knot further, the excess is taken
  back and the correction is spread linearly to the neighbouring knots, so the curve is
  not re-kinked at the knot.
* **No state changes sign.** A state the smoother would carry across zero keeps its
  unsmoothed value, so the smoother never invents a sign change and never removes one.

The pchip through five phase values already has its extrema at the knots; the kernel
mostly rounds the steepest stretches between them (the largest single step between
neighbouring states) and the extrapolated tails. The mean step is bounded below by the
distance between the phase values themselves, which the tolerance keeps: a light
smoother cannot, and should not, flatten what was measured. States resting on the
instrument's own measurement are labelled ``forward-12m-smoothed``; a filled band keeps its
``shape-scaled`` (or ``seed``) label, the weaker fact. A smoothed state reports as
``n_obs`` the effective independent years of the phase whose band it lies in (it is not a
fill, so it cannot report zero). The unsmoothed profile and the five
measured phase values stay on the result (``unsmoothed``, ``phases``). A profile with no
measured phase at all (no history) is the role seed and is not smoothed, so it stays an
exact copy of the role's curve.

Pure functions; no storage, no currency. The caller chooses the series and converts it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from engines.fund_map import numerics as num
from engines.fund_map.calibrate import (
    METHOD_STRENGTH,
    PHASE_KNOTS,
    STATE_COUNT,
    SUFFICIENCY_FLOOR,
    TRIM_FRACTION,
    TRIM_SWITCH,
    Method,
    state_axis,
    state_methods,
)
from engines.fund_map.estimate import EstimatedProfile, ShapeFit
from engines.fund_map.phases import PHASE_NAMES
from engines.fund_map.roles import RoleProfile
from engines.fund_map.state_map import StateMap

#: D-02: the horizon on which the role calibration is measured.
FORWARD_HORIZON_MONTHS = 12

#: States per phase band on the 25-state grid.
STATES_PER_PHASE = STATE_COUNT // len(PHASE_KNOTS)

#: FMRE-22: passes of the binomial kernel (1/4, 1/2, 1/4) across neighbouring states.
#: Two is "light": each state then draws on at most two neighbours either side, with
#: weights 6/16, 4/16 and 1/16.
SMOOTHING_PASSES = 2

#: FMRE-22: the most the smoother may move any phase value (the knots, states 3, 8, 13,
#: 18, 23), as an annual log return. One percentage point.
SMOOTHING_TOLERANCE = 0.01

#: Zero-based positions of the five phase knots on the 25-state grid.
KNOT_INDEX = tuple(p * STATES_PER_PHASE + STATES_PER_PHASE // 2
                   for p in range(len(PHASE_KNOTS)))


def phase_of_state(state: int) -> int:
    """Zero-based phase index of a 1-based calibration state (1..5 crisis ... 21..25 boom)."""
    return (state - 1) // STATES_PER_PHASE


def add_months(period: str, months: int) -> str:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + (month - 1) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass(frozen=True)
class ForwardWindow:
    """One tagged month and the 12 months that followed it."""

    start: str          # the tagged month, YYYY-MM
    state: int          # its calibration state, 1..25
    phase: int          # its phase, 0 = crisis .. 4 = boom
    value: float        # log return over start+1 .. start+12


@dataclass(frozen=True)
class PhaseForward:
    """What one phase knot rests on."""

    phase: int
    windows: int        # complete windows starting in this phase (overlapping)
    n_eff: int          # effective independent years, see effective_observations
    value: float        # the knot value that went into the profile
    method: Method


@dataclass(frozen=True)
class Smoothing:
    """What the smoothing step did to one profile (FMRE-22)."""

    passes: int
    tolerance: float
    #: after - before at the five phase knots; never more than ``tolerance`` in size.
    knot_shift: tuple[float, ...]
    #: 1-based states held at their unsmoothed value because smoothing would have
    #: carried them across zero.
    held: tuple[int, ...]


@dataclass(frozen=True)
class ForwardResult:
    profile: EstimatedProfile
    phases: tuple[PhaseForward, ...]
    windows: tuple[ForwardWindow, ...]
    amplitude: float | None       # D2's k, when a phase had to be filled from the shape
    #: Set by :func:`smooth_forward`: the profile before smoothing, and what it did.
    unsmoothed: EstimatedProfile | None = None
    smoothing: Smoothing | None = None


def forward_windows(
    returns: Mapping[str, float],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
    *,
    horizon: int = FORWARD_HORIZON_MONTHS,
) -> list[ForwardWindow]:
    """Every tagged month whose following ``horizon`` months are all present."""
    out: list[ForwardWindow] = []
    for period in sorted(signal_by_period):
        following = [add_months(period, i + 1) for i in range(horizon)]
        values = [returns.get(p) for p in following]
        if any(v is None or v <= -1.0 for v in values):
            continue
        state = state_map.state_for(signal_by_period[period])
        out.append(ForwardWindow(
            start=period, state=state, phase=phase_of_state(state),
            value=math.fsum(math.log1p(v) for v in values),  # type: ignore[arg-type]
        ))
    return out


def effective_observations(starts: Sequence[str], *,
                           horizon: int = FORWARD_HORIZON_MONTHS) -> int:
    """Independent years behind a set of overlapping windows.

    The distinct months the windows cover, divided by the horizon and rounded down. Two
    windows that share no month are two observations; twelve that share eleven months
    each are about one. Never more than the number of windows.
    """
    covered: set[str] = set()
    for start in starts:
        covered.update(add_months(start, i + 1) for i in range(horizon))
    return min(len(starts), len(covered) // horizon)


def estimate_forward(
    instrument_id: str,
    role: str,
    returns: Mapping[str, float],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
    role_profile: RoleProfile,
    *,
    fit: ShapeFit | None = None,
) -> ForwardResult:
    """Build one instrument's 25-state profile from 12 month forward returns."""
    windows = forward_windows(returns, signal_by_period, state_map)
    phases = len(PHASE_KNOTS)
    by_phase: list[list[ForwardWindow]] = [[] for _ in range(phases)]
    for w in windows:
        by_phase[w.phase].append(w)

    knot_values: list[float | None] = [None] * phases
    knot_methods: list[Method] = [Method.INSUFFICIENT] * phases
    knot_counts: list[int] = [0] * phases
    n_windows = [len(b) for b in by_phase]
    n_eff = [effective_observations([w.start for w in b]) for b in by_phase]

    for p in range(phases):
        values = [w.value for w in by_phase[p]]
        if n_eff[p] < SUFFICIENCY_FLOOR:
            continue
        if n_eff[p] >= TRIM_SWITCH:
            knot_values[p] = num.trimmed_mean(values, TRIM_FRACTION)
            knot_methods[p] = Method.DATA_DRIVEN_TRIMMED
        else:
            knot_values[p] = num.mean(values)
            knot_methods[p] = Method.DATA_DRIVEN
        knot_counts[p] = n_eff[p]

    # Fill the phases that did not clear the floor.
    role_phases = list(role_profile.phase_means)
    centre = num.mean(role_phases)
    deviation = [v - centre for v in role_phases]
    measured = [p for p in range(phases) if knot_values[p] is not None]
    amplitude: float | None = None
    if len(measured) < phases:
        if fit is not None:
            amplitude = fit.amplitude
            if measured:
                anchor = num.mean([knot_values[p] - amplitude * deviation[p]  # type: ignore[operator]
                                   for p in measured])
            else:
                anchor = fit.level
            for p in range(phases):
                if knot_values[p] is None:
                    knot_values[p] = anchor + amplitude * deviation[p]
                    knot_methods[p] = Method.SHAPE_SCALED
                    knot_counts[p] = fit.observations
        else:
            for p in range(phases):
                if knot_values[p] is None:
                    knot_values[p] = role_phases[p]
                    knot_methods[p] = Method.SEED

    knots = [float(v) for v in knot_values]  # type: ignore[arg-type]
    profile = num.pchip_eval(list(PHASE_KNOTS), knots, state_axis())

    methods = list(state_methods(knot_methods))
    counts = [0] * STATE_COUNT
    for p in range(phases):
        band = range(p * STATES_PER_PHASE, (p + 1) * STATES_PER_PHASE)
        if knot_methods[p] in (Method.SHAPE_SCALED, Method.SEED):
            for i in band:
                methods[i] = knot_methods[p]
                counts[i] = knot_counts[p] if knot_methods[p] is Method.SHAPE_SCALED else 0
        else:
            centre_state = p * STATES_PER_PHASE + STATES_PER_PHASE // 2
            counts[centre_state] = knot_counts[p]

    coverage = min(methods, key=METHOD_STRENGTH.index)
    estimated = EstimatedProfile(
        instrument_id=instrument_id,
        role=role,
        n_obs_total=len(windows),
        profile_by_state=tuple(profile),
        methods_by_state=tuple(methods),
        n_obs_by_state=tuple(counts),
        # Windows that existed in a phase too thin to measure, kept as a diagnostic in the
        # same way the cascade keeps its sub-floor bucket counts. Reported at the knot.
        n_obs_discarded_by_state=tuple(
            n_windows[phase_of_state(s + 1)]
            if (s % STATES_PER_PHASE == STATES_PER_PHASE // 2
                and knot_methods[phase_of_state(s + 1)] in (Method.SHAPE_SCALED, Method.SEED))
            else 0
            for s in range(STATE_COUNT)
        ),
        borrowed_from=None,
        match_score=None,
        coverage=coverage,
    )
    return ForwardResult(
        profile=estimated,
        phases=tuple(
            PhaseForward(p, n_windows[p], n_eff[p], knots[p], knot_methods[p])
            for p in range(phases)
        ),
        windows=tuple(windows),
        amplitude=amplitude,
    )


def smooth_profile(
    values: Sequence[float],
    *,
    passes: int = SMOOTHING_PASSES,
    tolerance: float = SMOOTHING_TOLERANCE,
) -> tuple[list[float], tuple[int, ...]]:
    """The light smoother over the 25 states, with its two guards (FMRE-22).

    Returns the smoothed values and the 1-based states held back at their input value
    because the kernel would have changed their sign.
    """
    original = [float(v) for v in values]
    n = len(original)
    smoothed = list(original)
    for _ in range(passes):
        padded = [smoothed[0], *smoothed, smoothed[-1]]
        smoothed = [0.25 * padded[i] + 0.5 * padded[i + 1] + 0.25 * padded[i + 2]
                    for i in range(n)]

    # Guard 1: take back whatever the kernel moved a knot beyond the tolerance, and spread
    # that correction linearly between knots (constant beyond the outer ones).
    correction_at_knot = []
    for k in KNOT_INDEX:
        moved = smoothed[k] - original[k]
        allowed = max(-tolerance, min(tolerance, moved))
        correction_at_knot.append(allowed - moved)
    correction = [0.0] * n
    for i in range(n):
        if i <= KNOT_INDEX[0]:
            correction[i] = correction_at_knot[0]
        elif i >= KNOT_INDEX[-1]:
            correction[i] = correction_at_knot[-1]
        else:
            j = max(q for q in range(len(KNOT_INDEX)) if KNOT_INDEX[q] <= i)
            t = (i - KNOT_INDEX[j]) / (KNOT_INDEX[j + 1] - KNOT_INDEX[j])
            correction[i] = correction_at_knot[j] * (1 - t) + correction_at_knot[j + 1] * t
    out = [a + b for a, b in zip(smoothed, correction)]

    # Guard 2: no state crosses zero. Holding the input value keeps every sign change
    # where the measurement put it, and invents none.
    held = []
    for i in range(n):
        if (original[i] > 0) != (out[i] > 0) or (original[i] < 0) != (out[i] < 0):
            out[i] = original[i]
            held.append(i + 1)
    return out, tuple(held)


#: Labels that rest on the instrument's own forward measurement and become
#: ``forward-12m-smoothed``; a fill keeps its own, weaker label.
_MEASURED = (Method.DATA_DRIVEN, Method.DATA_DRIVEN_TRIMMED, Method.INTERPOLATED,
             Method.EXTRAPOLATED)


def smooth_forward(
    result: ForwardResult,
    *,
    passes: int = SMOOTHING_PASSES,
    tolerance: float = SMOOTHING_TOLERANCE,
) -> ForwardResult:
    """The default estimator: the 12 month forward measurement, lightly smoothed."""
    before = result.profile
    if not any(p.method in (Method.DATA_DRIVEN, Method.DATA_DRIVEN_TRIMMED)
               for p in result.phases):
        # Nothing measured: the role seed (or a pure fill), left exactly as it is.
        return replace(result, unsmoothed=before,
                       smoothing=Smoothing(passes, tolerance, (0.0,) * len(KNOT_INDEX), ()))
    values, held = smooth_profile(before.profile_by_state, passes=passes, tolerance=tolerance)
    methods = tuple(Method.FORWARD_SMOOTHED if m in _MEASURED else m
                    for m in before.methods_by_state)
    # A smoothed state is not a fill, so it names the evidence it rests on: the
    # effective independent years of the phase whose band it lies in. A filled band keeps
    # the fill's count.
    n_eff = {p.phase: p.n_eff for p in result.phases}
    counts = tuple(n_eff[phase_of_state(i + 1)] if m is Method.FORWARD_SMOOTHED else c
                   for i, (m, c) in enumerate(zip(methods, before.n_obs_by_state)))
    after = replace(
        before,
        profile_by_state=tuple(values),
        methods_by_state=methods,
        n_obs_by_state=counts,
        coverage=min(methods, key=METHOD_STRENGTH.index),
    )
    shift = tuple(values[k] - before.profile_by_state[k] for k in KNOT_INDEX)
    return replace(result, profile=after, unsmoothed=before,
                   smoothing=Smoothing(passes, tolerance, shift, held))


def phase_label(phase: int) -> str:
    return PHASE_NAMES[phase]
