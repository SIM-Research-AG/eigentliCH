"""The cycle model: pure functions, no I/O, no HTTP, no clock.

A port of the first draft, ``Macro_Model/macrofield/model/cycles.py`` (decomposition,
frequency estimation, phase synchrony, anchored cycles) and ``cycle_bins.py`` (each cycle
on the 25-bin axis), onto datafeed's panel. Everything a figure depends on arrives as an
argument, so the same inputs give the same output, bit for bit.

Pipeline, per economy::

    Panel (monthly)  ->  annualise  ->  real output growth, capital saturation
                     ->  estimated cycles: Christiano-Fitzgerald band-pass, analytic signal
                         anchored cycles:  phase from a supplied trough, peak or crossing
                     ->  phase per year (recovery, expansion, slowdown, contraction)
                     ->  superposition and synchrony windows over the interference members
                     ->  each cycle as a kernel on the 25-bin axis, mixed linearly

Where the port departs from the draft it does so on purpose, and the reason is in
``DECISIONS.md``. In short:

* Inputs come from datafeed by name, annualised at December (C-03, C-04).
* A gap is never filled: an estimated cycle uses the trailing contiguous span of its input,
  and years outside it carry no phase (C-05).
* A cycle with no position is left off the 25-bin axis instead of voiding the year (C-09).
* The Christiano-Fitzgerald filter is reimplemented in numpy; statsmodels is not on the
  allowlist. The golden test reconciles it against statsmodels (C-06).

Phase convention (from the draft): the phase angle is taken in the cycle's own variable,
0 at its peak and plus or minus pi at its trough.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np
from scipy.signal import hilbert, welch

from .contracts import (
    STATE_COUNT,
    Calibration,
    CoverageReport,
    CycleSpec,
    CycleTrack,
    EconomyCycles,
    InputGap,
    Panel,
    PublicFill,
    SynchronyWindow,
    Unidentified,
    phase_of,
)

#: The six series the cycle model reads, by name.
REQUIRED_SERIES: tuple[str, ...] = (
    "production.gdp_nominal",   # output
    "inflation.cpi_yoy",        # deflator
    "debt.corporate_gdp",       # capital saturation (as honi)
    "debt.government_gdp",
    "debt.household_gdp",
    "debt.financial_sector",
)

#: Annual data. Every period and frequency below is in years.
SAMPLING_PER_YEAR = 1.0

CLASS_MARGINAL = "marginal"
CLASS_ASSUMED = "assumed"
CLASS_SUPPLIED = "supplied"
CLASS_MEASURED = "measured"


class EngineError(ValueError):
    """The inputs cannot produce a publishable result. The message says why."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnnualPanel:
    """Annual values, one years-by-economies array per series."""

    years: tuple[int, ...]
    economies: tuple[str, ...]
    data: Mapping[str, np.ndarray]


def annualise(panel: Panel, economies: Sequence[str], method: str) -> AnnualPanel:
    """Reduce the monthly panel to calendar years, as honi does.

    ``year_end`` takes the December cell. ``mean`` takes the mean of the twelve months and
    is missing if any month is. Only calendar years whose December lies on the panel's
    date axis are produced, so a partial final year never appears.
    """
    months = [(int(d[:4]), int(d[5:7])) for d in panel.dates]

    def complete(year: int) -> bool:
        return method == "year_end" or (year, 1) >= months[0]

    years = tuple(y for y, m in months if m == 12 and complete(y))
    if not years:
        raise EngineError("the panel covers no complete calendar year")

    lookup = {(s.country, s.series_id): s.values for s in panel.series}
    data: dict[str, np.ndarray] = {}
    for series_id in REQUIRED_SERIES:
        monthly = np.full((len(months), len(economies)), np.nan)
        for j, code in enumerate(economies):
            values = lookup.get((code, series_id))
            if values is not None:
                monthly[:, j] = [np.nan if v is None else v for v in values]
        annual = np.full((len(years), len(economies)), np.nan)
        for i, year in enumerate(years):
            december = months.index((year, 12))
            if method == "year_end":
                annual[i] = monthly[december]
            else:
                block = monthly[december - 11: december + 1]
                annual[i] = np.where(np.isnan(block).any(axis=0), np.nan, block.mean(axis=0))
        data[series_id] = annual
    return AnnualPanel(years=years, economies=tuple(economies), data=data)


def _finite(x: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(x), x, np.nan)


def capital_saturation(s: Mapping[str, np.ndarray]) -> np.ndarray:
    """Corporate + government + household debt (% GDP) + financial-sector debt / GDP.

    The same definition as honi's capital saturation, so both engines read one axis.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        financial = _finite(s["debt.financial_sector"] / s["production.gdp_nominal"])
    return _finite(s["debt.corporate_gdp"] + s["debt.government_gdp"] + s["debt.household_gdp"]
                   + financial)


def trailing_span(values: np.ndarray) -> Optional[tuple[int, int]]:
    """``(first, last)`` of the trailing run of finite values, inclusive; None if empty.

    The run ends at the last finite value, so a missing final year shortens it."""
    finite = np.isfinite(np.asarray(values, dtype=float))
    if not finite.any():
        return None
    last = int(np.flatnonzero(finite)[-1])
    first = last
    while first > 0 and finite[first - 1]:
        first -= 1
    return first, last


def longest_span(values: np.ndarray) -> Optional[tuple[int, int]]:
    """``(first, last)`` of the longest run of finite values, inclusive (the latest on a tie)."""
    finite = np.isfinite(np.asarray(values, dtype=float))
    best, start = None, None
    for i, ok in enumerate(list(finite) + [False]):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if best is None or (i - 1 - start) >= (best[1] - best[0]):
                best = (start, i - 1)
            start = None
    return best


def _only(values: np.ndarray, span: Optional[tuple[int, int]], before: int = 0) -> np.ndarray:
    """``values`` with everything outside ``span`` (widened by ``before`` years) set missing."""
    out = np.full(np.shape(values), np.nan)
    if span is not None:
        lo = max(0, span[0] - before)
        out[lo: span[1] + 1] = np.asarray(values, dtype=float)[lo: span[1] + 1]
    return out


def _log_growth(nominal: np.ndarray, cpi: np.ndarray, deflate: bool) -> np.ndarray:
    y = np.asarray(nominal, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_y = np.log(np.where(y > 0.0, y, np.nan))
        g = np.full(y.shape, np.nan)
        g[1:] = log_y[1:] - log_y[:-1]
        if deflate:
            c = np.asarray(cpi, dtype=float)[1:]
            g[1:] -= np.log1p(np.where(c > -1.0, c, np.nan))
    return g


def longest_inputs(nominal: np.ndarray, cpi: np.ndarray, deflate: bool, saturation: np.ndarray,
                   mf_output: np.ndarray) -> dict:
    """Each cycle input computed on its longest gap-free run instead of its trailing one: the
    fallback for a trailing run too short to identify a cycle."""
    g_span = longest_span(_log_growth(nominal, cpi, deflate))
    with np.errstate(divide="ignore", invalid="ignore"):
        log_mf = np.log(np.where(np.asarray(mf_output, float) > 0.0, mf_output, np.nan))
    return {
        "output_growth": output_growth(_only(nominal, g_span, before=1), _only(cpi, g_span), deflate),
        "saturation_change": saturation_change(_only(saturation, longest_span(saturation))),
        "macrofield_output_growth": macrofield_output_growth(_only(mf_output, longest_span(log_mf))),
    }


def output_growth(nominal: np.ndarray, cpi: np.ndarray, deflate: bool) -> tuple[np.ndarray, Optional[tuple[int, int]]]:
    """The draft's input, ``np.gradient(log(real output))``, on the trailing span it exists.

    Year-on-year log growth ``g[t] = ln Y[t] - ln Y[t-1] - ln(1 + cpi[t])`` is formed first,
    so a gap in the deflator stays local. On the trailing contiguous run of ``g`` the log
    real level is rebuilt and differentiated with ``np.gradient``, exactly as the draft
    differentiated its real output path. Outside that span the result is NaN.
    """
    y = np.asarray(nominal, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_y = np.log(np.where(y > 0.0, y, np.nan))
        g = np.full(y.shape, np.nan)
        g[1:] = log_y[1:] - log_y[:-1]
        if deflate:
            g[1:] -= np.log1p(np.where(np.asarray(cpi, float)[1:] > -1.0, np.asarray(cpi, float)[1:], np.nan))
    out = np.full(y.shape, np.nan)
    span = trailing_span(g)
    if span is None:
        return out, None
    first, last = span[0] - 1, span[1]                 # levels start one year before growth
    level = np.concatenate([[0.0], np.cumsum(g[span[0]: span[1] + 1])])
    out[first: last + 1] = np.gradient(level)
    return out, (first, last)


def macrofield_output_growth(output: np.ndarray) -> tuple[np.ndarray, Optional[tuple[int, int]]]:
    """The draft's input exactly: ``np.gradient(log Y)`` of macrofield's output in current US
    dollars, not deflated, on its trailing contiguous span."""
    y = np.asarray(output, dtype=float)
    out = np.full(y.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_y = np.log(np.where(y > 0.0, y, np.nan))
    span = trailing_span(log_y)
    if span is None or span[1] - span[0] < 1:
        return out, None
    out[span[0]: span[1] + 1] = np.gradient(log_y[span[0]: span[1] + 1])
    return out, span


def saturation_change(saturation: np.ndarray) -> tuple[np.ndarray, Optional[tuple[int, int]]]:
    """``np.gradient`` of capital saturation on its trailing contiguous span."""
    s = np.asarray(saturation, dtype=float)
    out = np.full(s.shape, np.nan)
    span = trailing_span(s)
    if span is None or span[1] - span[0] < 1:
        return out, None
    out[span[0]: span[1] + 1] = np.gradient(s[span[0]: span[1] + 1])
    return out, span


# ---------------------------------------------------------------------------
# Band-pass extraction (cycles.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CycleBand:
    name: str
    prior_period: float
    low_period: float
    high_period: float

    @classmethod
    def from_prior(cls, name: str, prior_period: float, band_fraction: float) -> "CycleBand":
        return cls(name, float(prior_period), float(prior_period) * (1.0 - band_fraction),
                   float(prior_period) * (1.0 + band_fraction))

    @classmethod
    def from_explicit(cls, name: str, low_period: float, high_period: float) -> "CycleBand":
        return cls(name, float((low_period + high_period) / 2.0), float(low_period), float(high_period))


def band_for(spec: CycleSpec, band_fraction: float) -> CycleBand:
    if spec.band is not None:
        return CycleBand.from_explicit(spec.name, *spec.band)
    return CycleBand.from_prior(spec.name, spec.period_years, band_fraction)


def cf_filter(x: np.ndarray, low: float, high: float, drift: bool = False) -> np.ndarray:
    """Christiano-Fitzgerald asymmetric random-walk band-pass filter; returns the cycle.

    Transcribed from ``statsmodels.tsa.filters.cf_filter.cffilter`` (0.14), index for
    index, so that it agrees with the draft to rounding (golden layer A checks it).
    """
    if low < 2:
        raise EngineError("low must be >= 2")
    x = np.asarray(x, dtype=float)
    nobs = x.size
    a = 2 * np.pi / high
    b = 2 * np.pi / low
    if drift:
        x = x - np.arange(nobs) * (x[-1] - x[0]) / (nobs - 1.0)
    J = np.arange(1, nobs + 1)
    Bj = (np.sin(b * J) - np.sin(a * J)) / (np.pi * J)
    B0 = (b - a) / np.pi
    Bj = np.r_[B0, Bj]
    y = np.zeros(nobs)
    for i in range(nobs):
        B = -0.5 * Bj[0] - np.sum(Bj[1:-i - 2])
        A = -Bj[0] - np.sum(Bj[1:-i - 2]) - np.sum(Bj[1:i]) - B
        y[i] = (Bj[0] * x[i] + np.dot(Bj[1:-i - 2], x[i + 1:-1]) + B * x[-1]
                + np.dot(Bj[1:i], x[1:i][::-1]) + A * x[0])
    return y


@dataclass
class CycleEstimate:
    """One cycle on the sample it was estimated from (arrays are the sample's length)."""

    name: str
    band: CycleBand
    identifiable: bool
    component: Optional[np.ndarray] = None
    estimated_period: Optional[float] = None
    amplitude: Optional[np.ndarray] = None
    phase: Optional[np.ndarray] = None
    sample_years: float = 0.0
    notes: list[str] = field(default_factory=list)


def _dominant_period(component: np.ndarray, sampling_per_year: float, band: CycleBand) -> Optional[float]:
    """The dominant period of a component by Welch's spectrum, restricted to the band."""
    length = component.size
    if length < 8:
        return None
    segment = min(length, max(8, length // 2))
    frequencies, power = welch(component, fs=sampling_per_year, nperseg=segment)
    positive = frequencies > 0.0
    frequencies, power = frequencies[positive], power[positive]
    if frequencies.size == 0:
        return None
    periods = 1.0 / frequencies
    inside = (periods >= band.low_period) & (periods <= band.high_period)
    if not inside.any():
        return None
    return float(periods[inside][int(np.argmax(power[inside]))])


def extract_cycle(values: np.ndarray, band: CycleBand, sampling_per_year: float = 1.0,
                  minimum_periods_in_sample: float = 2.0) -> CycleEstimate:
    """Band-pass one cycle, or say why it cannot be identified on this sample."""
    series = np.asarray(values, dtype=float)
    if series.ndim != 1 or np.any(~np.isfinite(series)):
        raise EngineError(f"{band.name}: the input must be a finite one-dimensional series")
    sample_years = series.size / float(sampling_per_year)
    required = minimum_periods_in_sample * band.prior_period
    if sample_years < required:
        return CycleEstimate(
            name=band.name, band=band, identifiable=False, sample_years=sample_years,
            notes=[f"the sample spans {sample_years:.1f} years but the {band.name} cycle has a prior "
                   f"period of {band.prior_period:.1f} years, so at least {required:.1f} years are "
                   f"needed to identify it. No estimate is produced: a band-pass filter would return "
                   f"a component regardless, and it would not be an estimate of this cycle."],
        )
    component = cf_filter(series, low=band.low_period * sampling_per_year,
                          high=band.high_period * sampling_per_year, drift=False)
    analytic = hilbert(component)
    return CycleEstimate(
        name=band.name, band=band, identifiable=True, component=component,
        estimated_period=_dominant_period(component, sampling_per_year, band),
        amplitude=np.abs(analytic), phase=np.angle(analytic), sample_years=sample_years,
    )


def _wrap(angle: np.ndarray) -> np.ndarray:
    """Wrap an angle to [-pi, pi)."""
    return (np.asarray(angle, dtype=float) + np.pi) % (2.0 * np.pi) - np.pi


# ---------------------------------------------------------------------------
# Anchored cycles (cycles.py)
# ---------------------------------------------------------------------------

@dataclass
class AnchoredCycle:
    """A long cycle positioned from supplied structure. Arrays are the window's length."""

    name: str
    estimate: CycleEstimate
    period_years: float
    reference_year: Optional[float]
    years_into_cycle: Optional[np.ndarray]
    anchored: bool
    assumed: bool = False
    notes: list[str] = field(default_factory=list)


_UNIT_AMPLITUDE = ("the amplitude is normalised to one. The anchor gives the position in the cycle, "
                   "not its size, and scaling it to the data would be inventing an amplitude.")


def _anchored_estimate(name: str, band: CycleBand, phase: np.ndarray, sample_years: float,
                       period_years: float, notes: Sequence[str]) -> CycleEstimate:
    return CycleEstimate(name=name, band=band, identifiable=True, component=np.cos(phase),
                         estimated_period=float(period_years), amplitude=np.ones_like(phase),
                         phase=_wrap(phase), sample_years=sample_years, notes=list(notes))


def fixed_cycle(name: str, years: np.ndarray, anchor_year: float, period_years: float, *,
                at: str, band_fraction: float, national: bool = False) -> AnchoredCycle:
    """A cycle pinned to a supplied trough (phase pi) or peak (phase 0). ``at`` is ``"trough"``
    or ``"peak"``. Global (identical for every economy) unless ``national``."""
    offset = np.pi if at == "trough" else 0.0
    phase = 2.0 * np.pi * (years - float(anchor_year)) / float(period_years) + offset
    scope = ("for this economy" if national else
             f"and applied identically to every economy: a {period_years:g}-year cycle cannot be "
             "estimated from a national-accounts sample")
    notes = [
        f"the {name} cycle is not estimated. It is anchored on a {'low' if at == 'trough' else 'high'} "
        f"in {anchor_year:g} with a period of {period_years:g} years, supplied by the author {scope}.",
        _UNIT_AMPLITUDE,
    ]
    return AnchoredCycle(
        name=name,
        estimate=_anchored_estimate(name, CycleBand.from_prior(name, period_years, band_fraction),
                                    phase, float(years.size), period_years, notes),
        period_years=float(period_years), reference_year=float(anchor_year),
        years_into_cycle=np.mod(years - float(anchor_year), float(period_years)),
        anchored=True, notes=notes,
    )


def _unanchored(name: str, band: CycleBand, period: float, n: int, note: str) -> AnchoredCycle:
    return AnchoredCycle(name=name, estimate=CycleEstimate(name, band, False, sample_years=float(n), notes=[note]),
                         period_years=float(period), reference_year=None, years_into_cycle=None,
                         anchored=False, notes=[note])


def anchor_capital_cycle(name: str, years: np.ndarray, saturation: np.ndarray, anchor_saturation: float,
                         years_into_cycle_at_anchor: float, period_years: float,
                         band_fraction: float) -> AnchoredCycle:
    """Date the capital cycle from the last upward crossing of ``anchor_saturation``,
    interpolated within the year. No crossing, no position: nothing is extrapolated."""
    values = np.asarray(saturation, dtype=float)
    band = CycleBand.from_prior(name, float(period_years), band_fraction)
    finite = np.isfinite(values)
    crossings: list[float] = []
    for index in range(1, years.size):
        if not (finite[index - 1] and finite[index]):
            continue
        below, now = values[index - 1], values[index]
        if below < anchor_saturation <= now:
            span = now - below
            fraction = (anchor_saturation - below) / span if span else 0.0
            crossings.append(float(years[index - 1] + fraction * (years[index] - years[index - 1])))

    if not crossings:
        peak = float(np.nanmax(values)) if finite.any() else float("nan")
        return _unanchored(name, band, period_years, years.size,
                           f"the {name} cycle is not anchored: capital saturation peaks at {peak:.2f} over "
                           f"this window and never reaches the anchor of {anchor_saturation:.2f}, which is "
                           f"what would date the cycle. No position is reported, because placing a "
                           f"{period_years:g}-year cycle from a {years.size}-year sample without the anchor "
                           f"would be a guess.")

    reference = crossings[-1]
    phase = 2.0 * np.pi * (years - reference) / float(period_years)
    notes = [
        f"the {name} cycle is not estimated. It is anchored on capital saturation crossing "
        f"{anchor_saturation:.2f} in {reference:.1f}, which the author places at "
        f"{years_into_cycle_at_anchor:g} years into a {period_years:g}-year cycle.",
        "phase zero sits at the crossing, where saturation peaks and the reordering occurs.",
        _UNIT_AMPLITUDE,
    ]
    if len(crossings) > 1:
        notes.append(f"saturation crossed {anchor_saturation:.2f} {len(crossings)} times, at "
                     f"{', '.join(f'{c:.1f}' for c in crossings)}. The last crossing is used.")
    return AnchoredCycle(
        name=name,
        estimate=_anchored_estimate(name, band, phase, float(years.size), period_years, notes),
        period_years=float(period_years), reference_year=reference,
        years_into_cycle=years - reference + float(years_into_cycle_at_anchor),
        anchored=True, notes=notes,
    )


def rise_fall_phase(years: np.ndarray, start: float, rise_years: float,
                    period_years: float, inverted: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Phase of an asymmetric cycle and the years into it: low (-pi) at ``start``, a linear
    rise to the peak (0) at ``start + rise_years``, a linear fall back to the low (pi, the
    next start) at ``start + period_years``. ``inverted`` swaps peak and low: peak (0) at
    ``start``, a fall to the low (pi) at ``start + rise_years``, a rise back to the peak at
    ``start + period_years``. The phase only moves forward either way."""
    into = np.mod(np.asarray(years, dtype=float) - float(start), float(period_years))
    first, second = float(rise_years), float(period_years) - float(rise_years)
    if inverted:
        phase = np.where(into < first, np.pi * into / first, -np.pi + np.pi * (into - first) / second)
    else:
        phase = np.where(into < first, -np.pi + np.pi * into / first, np.pi * (into - first) / second)
    return phase, into


def anchor_capital_on_reset(name: str, years: np.ndarray, reset_year: float,
                            years_into_cycle_at_anchor: float, period_years: float,
                            band_fraction: float, shape: str = "cosine",
                            origin: str = "a historical reset, supplied by the author") -> AnchoredCycle:
    """Date the capital cycle from a reset, year 0; the cycle peaks (phase 0)
    ``years_into_cycle_at_anchor`` years later. With ``rise_fall`` the reset is the low and the
    next reset comes ``period_years`` after it."""
    reference = float(reset_year) + float(years_into_cycle_at_anchor)
    if shape == "rise_fall":
        phase, into = rise_fall_phase(years, reset_year, years_into_cycle_at_anchor, period_years)
        shape_note = (f"The reset is the low; the cycle rises for {years_into_cycle_at_anchor:g} years to "
                      f"its peak in {reference:g}, then falls to the next reset in "
                      f"{float(reset_year) + float(period_years):g}.")
    elif shape == "fall_rise":
        phase, into = rise_fall_phase(years, reset_year, years_into_cycle_at_anchor, period_years, inverted=True)
        shape_note = (f"The reset is the peak; the cycle falls for {years_into_cycle_at_anchor:g} years to "
                      f"its low, saturation, in {reference:g}, then rises to the next reset in "
                      f"{float(reset_year) + float(period_years):g}.")
    else:
        phase = 2.0 * np.pi * (years - reference) / float(period_years)
        into = years - float(reset_year)
        shape_note = f"It peaks (phase zero) in {reference:g}."
    notes = [
        f"the {name} cycle is not estimated. Year 0 is {origin}, in {reset_year:g}. {shape_note}",
        _UNIT_AMPLITUDE,
    ]
    return AnchoredCycle(
        name=name, estimate=_anchored_estimate(name, CycleBand.from_prior(name, float(period_years), band_fraction),
                                               phase, float(years.size), period_years, notes),
        period_years=float(period_years), reference_year=reference,
        years_into_cycle=into, anchored=True, notes=notes,
    )


def anchor_capital_cycle_by_projection(name: str, years: np.ndarray, saturation: np.ndarray,
                                       anchor_saturation: float, years_into_cycle_at_anchor: float,
                                       period_years: float, trend_window: int,
                                       maximum_years_ahead: float, band_fraction: float) -> AnchoredCycle:
    """Anchor an economy that has not reached the ratio on when its recent linear trend
    would. Marked ``assumed``. A flat or falling trend, or a crossing too far out, is
    refused rather than invented."""
    values = np.asarray(saturation, dtype=float)
    band = CycleBand.from_prior(name, float(period_years), band_fraction)
    finite = np.isfinite(values)
    if finite.sum() < 2:
        return _unanchored(name, band, period_years, years.size,
                           "capital saturation has fewer than two finite observations, so no trend can be fitted")
    window = min(int(trend_window), int(finite.sum()))
    slope, intercept = np.polyfit(years[finite][-window:], values[finite][-window:], 1)
    latest_year, latest_value = float(years[finite][-1]), float(values[finite][-1])
    if slope <= 0.0:
        return _unanchored(name, band, period_years, years.size,
                           f"the {name} cycle is not anchored, even provisionally: saturation stands at "
                           f"{latest_value:.2f} against an anchor of {anchor_saturation:.2f}, and its trend "
                           f"over the last {window} years is {slope:+.4f} a year, so it is not approaching it.")
    crossing = (float(anchor_saturation) - float(intercept)) / float(slope)
    if crossing - latest_year > float(maximum_years_ahead):
        return _unanchored(name, band, period_years, years.size,
                           f"the {name} cycle is not anchored: the trend reaches {anchor_saturation:.2f} only in "
                           f"{crossing:.0f}, {crossing - latest_year:.0f} years after {latest_year:.0f}.")
    phase = 2.0 * np.pi * (years - crossing) / float(period_years)
    into = years - crossing + float(years_into_cycle_at_anchor)
    notes = [
        f"the {name} cycle is ASSUMED, not anchored on an observed crossing. Saturation stands at "
        f"{latest_value:.2f} and has never reached {anchor_saturation:.2f}; the crossing is solved from "
        f"the trend of the last {window} years, {slope:+.4f} a year, giving {crossing:.1f}.",
        f"the position is therefore {float(into[-1]):.0f} years into a {period_years:g}-year cycle, on "
        f"that assumption. It moves with the trend window.",
        _UNIT_AMPLITUDE,
    ]
    cycle = AnchoredCycle(
        name=name, estimate=_anchored_estimate(name, band, phase, float(years.size), period_years, notes),
        period_years=float(period_years), reference_year=crossing, years_into_cycle=into,
        anchored=True, assumed=True, notes=notes,
    )
    return cycle


# ---------------------------------------------------------------------------
# Superposition and synchrony (cycles.py)
# ---------------------------------------------------------------------------

def _unit_amplitude(component: np.ndarray) -> np.ndarray:
    values = np.asarray(component, dtype=float)
    peak = float(np.nanmax(np.abs(values))) if values.size else 0.0
    return values / peak if peak > 0.0 else np.zeros_like(values)


def superpose(components: Mapping[str, np.ndarray], weights: Mapping[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Weighted sum of unit-amplitude components (``total``, in [-1, 1]) and their
    ``alignment``: |sum| over the sum of magnitudes, NaN where every component is at zero."""
    usable = {name: _unit_amplitude(c) for name, c in components.items()}
    applied = {name: float(weights.get(name, 1.0)) for name in usable}
    total_weight = sum(applied.values())
    if total_weight <= 0.0:
        raise EngineError("the superposition weights sum to zero")
    stacked = np.vstack([usable[name] * applied[name] for name in usable])
    total = stacked.sum(axis=0) / total_weight
    magnitudes = np.abs(stacked).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        alignment = np.where(magnitudes > 1e-12,
                             np.abs(stacked.sum(axis=0)) / np.where(magnitudes > 0, magnitudes, 1.0), np.nan)
    return total, alignment


@dataclass(frozen=True)
class Window:
    start_index: int
    end_index: int
    cycles: tuple[str, ...]
    mean_absolute_phase_spread: float


def detect_synchrony(phases: Mapping[str, np.ndarray], tolerance: float, minimum: int) -> list[Window]:
    """Runs of periods in which at least ``minimum`` cycles are mutually within ``tolerance``
    of an anchor cycle. The draft's greedy rule, unchanged: per period, anchor on each cycle
    in turn, keep the largest group (ties to the tighter spread)."""
    names = sorted(phases)
    if len(names) < 2:
        return []
    n = next(iter(phases.values())).size
    synchronised = np.zeros(n, dtype=bool)
    in_phase: list[list[str]] = []
    spreads = np.full(n, np.nan)
    for index in range(n):
        at = {name: float(phases[name][index]) for name in names}
        best: list[str] = []
        best_spread = np.inf
        for anchor in names:
            group = [name for name in names
                     if abs(float(_wrap(np.array([at[name] - at[anchor]]))[0])) <= tolerance]
            if len(group) < 2:
                continue
            differences = [abs(float(_wrap(np.array([at[a] - at[b]]))[0]))
                           for i, a in enumerate(group) for b in group[i + 1:]]
            spread = float(np.mean(differences)) if differences else 0.0
            if len(group) > len(best) or (len(group) == len(best) and spread < best_spread):
                best, best_spread = group, spread
        in_phase.append(sorted(best))
        if len(best) >= minimum:
            synchronised[index] = True
            spreads[index] = best_spread

    windows: list[Window] = []
    start: Optional[int] = None
    for index in range(n + 1):
        active = bool(synchronised[index]) if index < n else False
        if active and start is None:
            start = index
        elif not active and start is not None:
            end = index - 1
            members = tuple(sorted({name for i in range(start, end + 1) for name in in_phase[i]}))
            windows.append(Window(start, end, members, float(np.nanmean(spreads[start: end + 1]))))
            start = None
    return windows


# ---------------------------------------------------------------------------
# The 25-bin axis (cycle_bins.py)
# ---------------------------------------------------------------------------

def bin_centre(level: float, state_count: int = STATE_COUNT) -> float:
    """A level in [-1, 1] onto the one-based axis: trough 1, mid 13, peak 25."""
    value = float(level)
    if not -1.0 - 1e-9 <= value <= 1.0 + 1e-9:
        raise EngineError(f"a cycle level must lie in [-1, 1], got {value}")
    value = min(1.0, max(-1.0, value))
    return 1.0 + (state_count - 1) * (value + 1.0) / 2.0


def classify(*, identifiable: bool, periods_in_sample: Optional[float], anchored: bool, assumed: bool,
             intervals_per_period: Optional[float], minimum_intervals: float) -> str:
    """Which confidence class a cycle falls in. Worst class wins."""
    if intervals_per_period is not None and intervals_per_period < minimum_intervals:
        return CLASS_MARGINAL
    if anchored:
        return CLASS_ASSUMED if assumed else CLASS_SUPPLIED
    if not identifiable or not periods_in_sample:
        return CLASS_MARGINAL
    return CLASS_MEASURED


def width_for(confidence: str, periods_in_sample: Optional[float], widths) -> float:
    """Kernel width in bins. Measured: ``base * sqrt(reference / periods)``, clamped."""
    if confidence == CLASS_MEASURED:
        observed = float(periods_in_sample or widths.measured_reference_periods)
        if observed <= 0.0:
            return widths.measured_max
        return float(min(widths.measured_max, max(widths.measured_min,
                     widths.measured_base * np.sqrt(widths.measured_reference_periods / observed))))
    return float({CLASS_SUPPLIED: widths.supplied, CLASS_ASSUMED: widths.assumed,
                  CLASS_MARGINAL: widths.marginal}[confidence])


def normalised_velocity(level: float, previous_level: float, period_years: float, step_years: float = 1.0) -> float:
    """Rate of change of the level over the fastest a unit cosine of this period moves."""
    if period_years <= 0.0 or step_years <= 0.0:
        return 0.0
    rate = (float(level) - float(previous_level)) / float(step_years)
    fastest = 2.0 * np.pi / float(period_years)
    return float(min(1.0, max(-1.0, rate / fastest)))


def cycle_distribution(centre: float, width: float, skew: float = 0.0,
                       state_count: int = STATE_COUNT) -> np.ndarray:
    """Split-normal kernel over the bins: same mode, the aggressive side wider when
    ``skew`` is positive, the cautious side when negative. Normalised."""
    if width <= 0.0:
        raise EngineError(f"a cycle kernel needs a positive width, got {width}")
    if not -0.95 <= skew <= 0.95:
        raise EngineError(f"the skew must lie in [-0.95, 0.95], got {skew}")
    bins = np.arange(1, state_count + 1, dtype=float)
    sigma = np.where(bins <= centre, width * (1.0 - skew), width * (1.0 + skew))
    kernel = np.exp(-0.5 * ((bins - centre) / sigma) ** 2)
    return kernel / kernel.sum()


@dataclass(frozen=True)
class Placement:
    name: str
    level: float
    centre: float
    width: float
    skew: float
    velocity: float
    distribution: np.ndarray


def place(name: str, level: float, period_years: float, width: float, skew_coefficient: float,
          previous_level: Optional[float], step_years: float = 1.0) -> Placement:
    """One cycle on the axis as a distribution (``cycle_bins.place``)."""
    centre = bin_centre(level)
    velocity = 0.0
    if previous_level is not None:
        velocity = normalised_velocity(level, previous_level, period_years, step_years)
    skew = float(min(0.95, max(-0.95, float(skew_coefficient) * velocity)))
    return Placement(name, float(level), centre, width, skew, velocity,
                     cycle_distribution(centre, width, skew))


def mix(placements: Sequence[Placement], weights: Mapping[str, float]) -> Optional[np.ndarray]:
    """Linear mixture of the placed kernels. Never multiplicative: a log pool would let one
    cycle's near-zero annihilate tail weight another keeps alive. None if nothing to mix."""
    if not placements:
        return None
    used = np.array([float(weights.get(p.name, 1.0)) for p in placements])
    if used.sum() <= 0.0:
        return None
    mixed = used @ np.vstack([p.distribution for p in placements])
    return mixed / mixed.sum()


# ---------------------------------------------------------------------------
# One economy
# ---------------------------------------------------------------------------

@dataclass
class Track:
    """A cycle over the whole window: arrays have one entry per year, NaN where no position."""

    spec: CycleSpec
    identifiable: bool
    anchored: bool
    assumed: bool
    component: np.ndarray
    phase: np.ndarray
    amplitude: np.ndarray
    period_years: Optional[float]      # dominant estimated period, or the anchor period
    reference_year: Optional[float]
    years_into_cycle: np.ndarray
    sample_years: float
    notes: list[str]


def _pad(values: Optional[np.ndarray], n: int, offset: int) -> np.ndarray:
    out = np.full(n, np.nan)
    if values is not None:
        v = np.atleast_1d(np.asarray(values, dtype=float))
        out[offset: offset + v.size] = v
    return out


def build_tracks(years: Sequence[int], inputs: Mapping[str, tuple[np.ndarray, Optional[tuple[int, int]]]],
                 saturation: np.ndarray, cal: Calibration, code: str = "") -> list[Track]:
    """Every calibrated cycle for one economy (``code`` selects its historical reset, if any)."""
    periods = np.asarray(years, dtype=float)
    n = periods.size
    tracks: list[Track] = []
    for spec in cal.cycles:
        if spec.kind == "estimated":
            band = band_for(spec, cal.band_fraction)
            values, span = inputs[spec.input]
            kind_of_span = "trailing"

            def estimate_on(vals, sp):
                if sp is None:
                    return CycleEstimate(spec.name, band, False, notes=[
                        f"{spec.input} has no finite values for this economy, so the {spec.name} cycle "
                        "cannot be estimated"])
                return extract_cycle(vals[sp[0]: sp[1] + 1], band, SAMPLING_PER_YEAR, cal.minimum_periods_in_sample)

            estimate = estimate_on(values, span)
            fallback = inputs.get("@longest", {}).get(spec.input)
            if not estimate.identifiable and fallback is not None and fallback[1] not in (None, span):
                alternative = estimate_on(*fallback)
                if alternative.identifiable:
                    estimate, (values, span), kind_of_span = alternative, fallback, "longest"
            offset = 0 if span is None else span[0]
            notes = list(estimate.notes)
            if kind_of_span == "longest":
                notes.append(f"the trailing contiguous span of {spec.input} is too short to identify the "
                             f"{spec.name} cycle, so it is estimated on the longest gap-free span instead")
            if span is not None and (span[0] > 0 or span[1] < n - 1):
                notes.append(f"estimated on {years[span[0]]} to {years[span[1]]} only: the {kind_of_span} "
                             f"contiguous span of {spec.input}; other years carry no phase")
            tracks.append(Track(
                spec=spec, identifiable=estimate.identifiable, anchored=False, assumed=False,
                component=_pad(estimate.component, n, offset), phase=_pad(estimate.phase, n, offset),
                amplitude=_pad(estimate.amplitude, n, offset),
                period_years=estimate.estimated_period, reference_year=None,
                years_into_cycle=np.full(n, np.nan), sample_years=estimate.sample_years, notes=notes))
            continue

        if spec.kind in ("anchored_trough", "anchored_peak"):
            year = spec.anchor_years.get(code, spec.anchor_year)
            if year is None:
                cycle = _unanchored(spec.name, CycleBand.from_prior(spec.name, spec.period_years, cal.band_fraction),
                                    spec.period_years, n,
                                    f"the {spec.name} cycle has no anchor year for this economy, so it has no position")
            else:
                cycle = fixed_cycle(spec.name, periods, year, spec.period_years,
                                    at="trough" if spec.kind == "anchored_trough" else "peak",
                                    band_fraction=cal.band_fraction, national=code in spec.anchor_years)
        elif code in spec.resets:
            cycle = anchor_capital_on_reset(spec.name, periods, spec.resets[code],
                                            spec.years_into_cycle_at_anchor, spec.period_years, cal.band_fraction,
                                            spec.shape)
        else:
            cycle = anchor_capital_cycle(spec.name, periods, saturation, spec.anchor_saturation,
                                         spec.years_into_cycle_at_anchor, spec.period_years, cal.band_fraction)
            if cycle.anchored and spec.shape in ("rise_fall", "fall_rise"):
                # The crossing marks the peak; the asymmetric shape is dated from the reset it implies.
                cycle = anchor_capital_on_reset(
                    spec.name, periods, cycle.reference_year - spec.years_into_cycle_at_anchor,
                    spec.years_into_cycle_at_anchor, spec.period_years, cal.band_fraction, spec.shape,
                    origin=f"the reset implied by saturation crossing {spec.anchor_saturation:g} "
                           f"{spec.years_into_cycle_at_anchor:g} years later")
            if not cycle.anchored and cal.assume_capital_crossing:
                observed = cycle
                cycle = anchor_capital_cycle_by_projection(
                    spec.name, periods, saturation, spec.anchor_saturation, spec.years_into_cycle_at_anchor,
                    spec.period_years, cal.assume_trend_window, cal.assume_maximum_years_ahead,
                    cal.band_fraction)
                cycle.notes = list(observed.notes) + list(cycle.notes)
        e = cycle.estimate
        tracks.append(Track(
            spec=spec, identifiable=e.identifiable, anchored=cycle.anchored, assumed=cycle.assumed,
            component=_pad(e.component, n, 0), phase=_pad(e.phase, n, 0), amplitude=_pad(e.amplitude, n, 0),
            period_years=cycle.period_years if cycle.anchored else None,
            reference_year=cycle.reference_year, years_into_cycle=_pad(cycle.years_into_cycle, n, 0),
            sample_years=e.sample_years, notes=list(cycle.notes)))
    return tracks


def _layer_period(track: Track) -> float:
    """The period a track is placed with (``cycle_bins.layer_from_cycles``)."""
    if track.anchored:
        return float(track.spec.period_years)
    # The band's prior: the explicit band's midpoint, else the configured period.
    prior = sum(track.spec.band) / 2.0 if track.spec.band else track.spec.period_years
    return float(track.period_years or prior)


def confidence_of(track: Track, cal: Calibration) -> Optional[str]:
    if not track.identifiable:
        return None
    period = _layer_period(track)
    return classify(identifiable=track.identifiable,
                    periods_in_sample=(track.sample_years / period) if period > 0 else None,
                    anchored=track.anchored, assumed=track.assumed,
                    intervals_per_period=(period / 1.0), minimum_intervals=cal.minimum_intervals_per_period)


@dataclass
class EconomyResult:
    tracks: list[Track]
    confidence: dict[str, Optional[str]]
    placements: list[dict[str, Placement]]            # per year, by cycle
    layer: list[Optional[np.ndarray]]
    superposition: np.ndarray
    alignment: np.ndarray
    members: tuple[str, ...]
    windows: list[Window]
    notes: list[str]
    #: The superposition over the anchored members only (C-25), and those members.
    superposition_anchored: Optional[np.ndarray] = None
    anchored_members: tuple[str, ...] = ()


def run_economy(years: Sequence[int], inputs, saturation: np.ndarray, cal: Calibration,
                code: str = "") -> EconomyResult:
    n = len(years)
    tracks = build_tracks(years, inputs, saturation, cal, code)
    confidence = {t.spec.name: confidence_of(t, cal) for t in tracks}
    notes: list[str] = []

    # -- the 25-bin layer, year by year ------------------------------------
    widths = {t.spec.name: width_for(confidence[t.spec.name], t.sample_years / _layer_period(t), cal.widths)
              for t in tracks if confidence[t.spec.name] is not None}
    weights = {t.spec.name: t.spec.layer_weight for t in tracks}
    placements: list[dict[str, Placement]] = []
    layer: list[Optional[np.ndarray]] = []
    for i in range(n):
        placed: dict[str, Placement] = {}
        for t in tracks:
            if not t.identifiable or not np.isfinite(t.phase[i]):
                continue
            o = float(t.spec.orientation)
            level = o * float(np.cos(t.phase[i]))
            previous = o * float(np.cos(t.phase[i - 1])) if i >= 1 and np.isfinite(t.phase[i - 1]) else None
            placed[t.spec.name] = place(t.spec.name, level, _layer_period(t), widths[t.spec.name],
                                        cal.skew_coefficient, previous)
        placements.append(placed)
        layer.append(mix(list(placed.values()), weights))
    never = [t.spec.name for t in tracks if not t.identifiable]
    if never:
        notes.append(f"not on the 25-bin axis in any year, having no position: {', '.join(never)}")

    # -- superposition and synchrony over the interference members -----------
    members = [t for t in tracks if t.spec.in_interference and t.identifiable]
    held_out = [t.spec.name for t in tracks if not t.spec.in_interference]
    if held_out:
        notes.append(f"placed on the axis but held out of the superposition and synchrony by calibration: "
                     f"{', '.join(held_out)}")
    superposition = np.full(n, np.nan)
    alignment = np.full(n, np.nan)
    windows: list[Window] = []
    if members:
        covered = np.logical_and.reduce([np.isfinite(t.component) for t in members])
        span = trailing_span(np.where(covered, 0.0, np.nan))
        if span is not None:
            s = slice(span[0], span[1] + 1)
            total, align = superpose({t.spec.name: t.component[s] for t in members},
                                     {t.spec.name: t.spec.superposition_weight for t in members})
            superposition[s], alignment[s] = total, align
            windows = [Window(w.start_index + span[0], w.end_index + span[0], w.cycles,
                              w.mean_absolute_phase_spread)
                       for w in detect_synchrony({t.spec.name: t.phase[s] for t in members},
                                                 cal.phase_tolerance_radians, cal.minimum_cycles_in_phase)]
            if span != (0, n - 1):
                notes.append(f"superposition and synchrony cover {years[span[0]]} to {years[span[1]]}, the "
                             "years every member has a position in")
        if len(members) < 2:
            notes.append(f"only {len(members)} cycle can enter the synchrony analysis, so no window can be "
                         "found. This is not a finding that the cycles are out of phase.")
        unidentified = [t.spec.name for t in tracks if t.spec.in_interference and not t.identifiable]
        if unidentified:
            notes.append(f"the superposition and synchrony are over {', '.join(t.spec.name for t in members)} "
                         f"only; without a position: {', '.join(unidentified)}")
    else:
        notes.append("no interference member has a position, so there is no superposition. This is not a "
                     "finding that the cycles cancel.")
    anchored, superposition_anchored = anchored_superposition(years, members, notes)
    return EconomyResult(tracks, confidence, placements, layer, superposition, alignment,
                         tuple(t.spec.name for t in members), windows, notes,
                         superposition_anchored, anchored)


def anchored_superposition(years: Sequence[int], members: Sequence[Track],
                           notes: list[str]) -> tuple[tuple[str, ...], np.ndarray]:
    """The superposition over the anchored interference members only (C-25): the weighted mean
    of their components, sum_k w_k c_k / sum_k w_k, on the trailing span every anchored member
    has a position in. The weights are the members' ``superposition_weight`` re-normalised to
    their own sum, so the result stays in [-1, 1]. An anchored component is cos(phase), unit
    amplitude by construction, so it enters unscaled: ``superpose`` rescales each component by
    its maximum over the span, which for an anchored cycle would make the figures depend on how
    far the axis runs (the projection horizon). Anchored cycles are defined for any date, so
    this runs through the projection, where the band-passed members stop."""
    n = len(years)
    out = np.full(n, np.nan)
    anchored = [t for t in members if t.anchored]
    if not anchored:
        return (), out
    names = tuple(t.spec.name for t in anchored)
    weight = sum(float(t.spec.superposition_weight) for t in anchored)
    covered = np.logical_and.reduce([np.isfinite(t.component) for t in anchored])
    span = trailing_span(np.where(covered, 0.0, np.nan))
    if span is None or weight <= 0.0:
        return names, out
    s = slice(span[0], span[1] + 1)
    out[s] = sum(float(t.spec.superposition_weight) * np.asarray(t.component[s], dtype=float)
                 for t in anchored) / weight
    notes.append(f"the anchored superposition covers {years[span[0]]} to {years[span[1]]} over "
                 f"{', '.join(names)} only, weights re-normalised to their sum "
                 f"({', '.join(f'{t.spec.name} {t.spec.superposition_weight / weight:.3g}' for t in anchored)})")
    return names, out


# ---------------------------------------------------------------------------
# Assembly into the contract
# ---------------------------------------------------------------------------

def _series(x: np.ndarray) -> tuple[Optional[float], ...]:
    return tuple(None if not np.isfinite(v) else float(v) for v in np.asarray(x, dtype=float))


def order_breaks(years: Sequence[int], phase: np.ndarray) -> tuple[int, ...]:
    """Years in which the phase angle moved backwards against the year before."""
    out = []
    for i in range(1, len(years)):
        if np.isfinite(phase[i]) and np.isfinite(phase[i - 1]):
            if float(_wrap(np.array([phase[i] - phase[i - 1]]))[0]) < 0.0:
                out.append(int(years[i]))
    return tuple(out)


def track_contract(years: Sequence[int], t: Track, result: EconomyResult) -> CycleTrack:
    n = len(years)
    name = t.spec.name
    phase = t.phase if t.identifiable else np.full(n, np.nan)
    at = [result.placements[i].get(name) for i in range(n)]
    return CycleTrack(
        cycle=name, kind=t.spec.kind, identifiable=t.identifiable, confidence=result.confidence[name],
        anchored=t.anchored, assumed=t.assumed,
        period_years=None if t.period_years is None else float(t.period_years),
        reference_year=None if t.reference_year is None else float(t.reference_year),
        sample_years=float(t.sample_years),
        phase=tuple(None if not np.isfinite(a) else phase_of(float(a)) for a in phase),
        angle=_series(phase), level=_series(np.cos(phase)), component=_series(t.component),
        amplitude=_series(t.amplitude), years_into_cycle=_series(t.years_into_cycle),
        bin_centre=tuple(None if p is None else p.centre for p in at),
        bin_width=tuple(None if p is None else p.width for p in at),
        bin_skew=tuple(None if p is None else p.skew for p in at),
        order_breaks=order_breaks(years, phase), notes=tuple(t.notes),
    )


def _mean_bin(row: Optional[np.ndarray]) -> Optional[float]:
    return None if row is None else float((np.arange(1, row.size + 1) * row).sum())


def economy_contract(code: str, name: str, years: Sequence[int], result: EconomyResult) -> EconomyCycles:
    return EconomyCycles(
        code=code, name=name,
        cycles=tuple(track_contract(years, t, result) for t in result.tracks),
        layer=tuple(None if row is None else tuple(float(v) for v in row) for row in result.layer),
        layer_mean_bin=tuple(_mean_bin(row) for row in result.layer),
        layer_modal_bin=tuple(None if row is None else int(np.argmax(row)) + 1 for row in result.layer),
        superposition=_series(result.superposition), alignment=_series(result.alignment),
        interference_members=result.members,
        superposition_anchored=_series(result.superposition_anchored if result.superposition_anchored is not None
                                       else np.full(len(years), np.nan)),
        anchored_members=result.anchored_members,
        synchrony_windows=tuple(SynchronyWindow(start_year=int(years[w.start_index]),
                                                end_year=int(years[w.end_index]), cycles=w.cycles,
                                                mean_absolute_phase_spread=w.mean_absolute_phase_spread)
                                for w in result.windows),
        notes=tuple(result.notes),
    )


@dataclass(frozen=True)
class ModelOutput:
    years: tuple[int, ...]
    economies: tuple[EconomyCycles, ...]
    coverage: CoverageReport
    observed_until: int = 0
    projected_until: Optional[int] = None


#: Macrofield's output per economy, as the service hands it over: code -> (years, Y).
MacroOutput = Mapping[str, tuple[Sequence[int], Sequence[Optional[float]]]]


def reads_macrofield(cal: Calibration) -> bool:
    return any(c.input == "macrofield_output_growth" for c in cal.cycles)


def year_axis(annual: AnnualPanel, macro: Optional[MacroOutput],
              horizon: Optional[int] = None) -> tuple[int, ...]:
    """The panel's complete years, extended back to every year macrofield has output for and
    forward to ``horizon`` (a projection's last year)."""
    years = set(annual.years)
    for mf_years, values in (macro or {}).values():
        years |= {int(y) for y, v in zip(mf_years, values) if v is not None}
    last = max(years) if horizon is None else max(max(years), int(horizon))
    return tuple(range(min(years), last + 1))


def _on_axis(values: np.ndarray, source_years: Sequence[int], axis: Sequence[int]) -> np.ndarray:
    index = {int(y): i for i, y in enumerate(axis)}
    out = np.full(len(axis), np.nan)
    for y, v in zip(source_years, values):
        if int(y) in index and v is not None:
            out[index[int(y)]] = float(v)
    return out


def prepare_inputs(annual: AnnualPanel, cal: Calibration, macro: Optional[MacroOutput] = None,
                   axis: Optional[Sequence[int]] = None) -> tuple[np.ndarray, list[dict]]:
    """Capital saturation (axis years by economies) and, per economy, each cycle input with its
    span, on the year axis (the panel's years unless macrofield extends it)."""
    axis = tuple(axis or annual.years)
    panel_saturation = capital_saturation(annual.data)
    saturation = np.column_stack([_on_axis(panel_saturation[:, j], annual.years, axis)
                                  for j in range(len(annual.economies))]) if annual.economies else \
        np.empty((len(axis), 0))
    per_economy = []
    for j, code in enumerate(annual.economies):
        gdp = _on_axis(annual.data["production.gdp_nominal"][:, j], annual.years, axis)
        cpi = _on_axis(annual.data["inflation.cpi_yoy"][:, j], annual.years, axis)
        mf = (macro or {}).get(code)
        mf_y = _on_axis(np.asarray([np.nan if v is None else v for v in mf[1]], float), mf[0], axis) \
            if mf is not None else np.full(len(axis), np.nan)
        per_economy.append({
            "output_growth": output_growth(gdp, cpi, cal.deflate_output),
            "saturation_change": saturation_change(saturation[:, j]),
            "macrofield_output_growth": macrofield_output_growth(mf_y),
            "@longest": longest_inputs(gdp, cpi, cal.deflate_output, saturation[:, j], mf_y),
        })
    return saturation, per_economy


def run_model(panel: Panel, cal: Calibration, economies: Sequence[str], names: Mapping[str, str],
              macro: Optional[MacroOutput] = None, horizon: Optional[int] = None) -> ModelOutput:
    """The full pipeline for every economy, assembled into the contract. ``macro`` is
    macrofield's output per economy; required when the calibration reads it. ``horizon``
    projects the axis to that year: anchored cycles are defined for any date and continue,
    band-passed ones stop at their data (the draft's rule)."""
    annual = annualise(panel, economies, cal.annualisation)
    if reads_macrofield(cal) and macro is None:
        raise EngineError(f"calibration {cal.version} reads macrofield output, and none was given")
    observed = year_axis(annual, macro if reads_macrofield(cal) else None)
    observed_until = observed[-1]
    years = year_axis(annual, macro if reads_macrofield(cal) else None, horizon)
    saturation, inputs = prepare_inputs(annual, cal, macro, years)
    used_inputs = sorted({c.input for c in cal.cycles if c.input is not None})
    saturation_cycles = [c for c in cal.cycles if c.kind == "anchored_saturation"]

    out, unidentified, gaps = [], [], []
    for j, code in enumerate(economies):
        result = run_economy(years, inputs[j], saturation[:, j], cal, code)
        out.append(economy_contract(code, names[code], years, result))
        for t in result.tracks:
            if not t.identifiable:
                unidentified.append(Unidentified(economy=code, cycle=t.spec.name,
                                                 reason=t.notes[0] if t.notes else "no position"))
        for key in used_inputs:
            # Years no estimated cycle reading this input has a phase in (the span may be the
            # trailing or the longest one); with no such cycle, the years the input lacks.
            readers = [t for t in result.tracks if t.spec.input == key and t.identifiable]
            if readers:
                covered = np.logical_or.reduce([np.isfinite(t.phase) for t in readers])
            else:
                covered = np.isfinite(inputs[j][key][0])
            missing = tuple(int(y) for y, ok in zip(years, covered) if not ok and y <= observed_until)
            if missing:
                gaps.append(InputGap(economy=code, input=key, years=missing))
        if any(code not in c.resets for c in saturation_cycles):
            missing = tuple(int(y) for y, v in zip(years, saturation[:, j])
                            if not np.isfinite(v) and y <= observed_until)
            if missing:
                gaps.append(InputGap(economy=code, input="saturation", years=missing))

    cells = sum(len(t.phase) for e in out for t in e.cycles)
    coverage = CoverageReport(
        economies=len(out), years=len(years), cycle_cells=cells,
        cycle_cells_without_phase=sum(1 for e in out for t in e.cycles for p in t.phase if p is None),
        layer_cells_unplaced=sum(1 for e in out for row in e.layer if row is None),
        unidentified=tuple(unidentified), input_gaps=tuple(gaps),
        public_fills=tuple(PublicFill(country=s.country, series_id=s.series_id, source=sp.source,
                                      first=sp.first, last=sp.last)
                           for s in panel.series if s.country in economies and s.series_id in REQUIRED_SERIES
                           for sp in s.source_spans if sp.source != panel.primary_source),
    )
    return ModelOutput(years=tuple(int(y) for y in years), economies=tuple(out), coverage=coverage,
                       observed_until=int(observed_until),
                       projected_until=None if years[-1] == observed_until else int(years[-1]))
