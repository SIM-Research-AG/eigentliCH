"""Cycle decomposition, frequency estimation and phase synchrony.

Brief section 0.9. The four sub-cycles (business, credit, innovation, capital) are decomposed and
estimated by spectral and band-pass methods, their frequencies and relative phase are estimated, and
the windows where they come into phase (constructive interference) are detected. The framework
identifies those windows as the regime of peak fragility.

The cycle periods from the source frequency analysis of the eight-century real-return series are
priors for the band-pass bands, not fixed answers: 3.6-year fundamental pulse, 7-year business cycle,
18-year credit cycle, 36-year innovation cycle (observed in a 40 to 54 year band), 90-year capital
cycle, 130-year hegemonic succession.

A caution the module enforces rather than leaves to the reader: a cycle cannot be estimated from a
sample shorter than a couple of its periods. A 90-year capital cycle needs roughly two centuries of
annual data, which no national accounts series provides. Where the sample is too short the cycle is
reported as unidentifiable, with the shortfall stated, instead of returning a number that a filter
will happily produce and that means nothing.

## The three long cycles are anchored, not estimated

Directed by the author on 2026-07-27. The consequence of the caution above is that the innovation and
capital cycles can *never* be estimated from national accounts: innovation needs about 94 years of
annual data and capital about 180, against the 50 to 60 years a typical series provides. Reporting them
as unidentifiable is honest but it also drops them out of the synchrony analysis entirely, which leaves
the synchronisation window a statement about the business and credit cycles alone. That is a window
computed over the two cycles the framework cares least about.

Both are therefore **anchored from author-supplied structural information** instead:

- **Capital.** Reaching a credit-to-GDP ratio of 3.5 means the economy is 90 years into the capital
  cycle. `anchor_capital_cycle` finds where the saturation axis crosses that ratio, interpolating
  within the year, and dates the cycle from it. This uses the same 3.5 that the phase classifier and the
  balanced band use, so the anchor and the phase boundary are the same quantity.
- **Innovation.** The innovation cycle is at a **low in 2032**, the same for every economy, since it is a
  global technological cycle rather than a national one. `fixed_innovation_cycle` builds it from that
  trough and a configured period.
- **Hegemonic succession.** Directed by the author on 2026-08-02. The UK-to-US succession ran **1914 to
  1945**, and the cycle is anchored on its completion: **a high in 1945**, the post-war settlement, at which
  the new order stands at full strength. `fixed_hegemonic_cycle` builds it from that peak and a 130-year
  period, and it is the only anchor pinned to a *peak* rather than a trough. Applied identically to every
  economy, since hegemonic order is a global structure.

  **It is deliberately kept out of the interference measure** (`cycles.anchored.hegemonic.in_interference`
  is false). It is positioned, charted and reported, and the fragility window is still computed over the four
  cycles it was computed over before, so adding it moved no published conclusion. That was the instruction
  and it is also the conservative choice: a 130-year cycle contributes a term that barely varies over any
  window this system looks at, and letting it into a normalised alignment measure would mostly add a
  near-constant.

**This reverses a design decision, and the reversal is deliberate.** An earlier revision of this module
carried a docstring stating that "the synchronisation window is computed, never asserted... so no date
appears anywhere in this module or in config", on the strength of brief section 0.14. Two dates now do
appear, in `config/defaults.yaml` under `cycles.anchored`. They are **structural inputs supplied by the
author, not forecasts recomputed by the programme**, which is exactly the standing of
`stock_gold.calibration_anchor_year` and is the one category of date section 0.14 permits. What section
0.14 forbids is the programme *asserting* a dated conclusion of its own, and that still does not happen:
the synchronisation window is computed from the phases, and the phases now include two that were
supplied rather than estimated. Recorded in docs/MODEL_SPEC.md section 7.

**Phase convention, which matters for reading synchrony.** `extract_cycle` takes its phase from the
analytic signal, so phase 0 is the *peak* of the extracted component and plus or minus pi is its trough.
The anchored cycles follow the same convention in their own variable: the capital cycle's phase is 0 at
the 3.5 crossing, because that is where saturation peaks and the reordering occurs; the innovation
cycle's phase is pi in 2032, because that is a low; and the hegemonic cycle's phase is 0 in 1945, because
that is a high. Two cycles therefore count as "in phase" when both are peaking in their own variable.

**One thing the hegemonic anchor does not say.** The 1929 crash lies inside the supplied 1914-to-1945
succession interval and is the deepest market dislocation of the period. It is *not* a trough of this cycle:
with a peak at 1945 and a 130-year period, 1929 sits on the rising limb at about +0.72, sixteen years short
of the peak. Both statements are true, and the distance between them is the reason this module computes
interference between cycles rather than reading a conclusion off any one of them. A severe crisis need not
coincide with the slowest cycle's low.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np
from scipy.signal import hilbert, welch
from statsmodels.tsa.filters.cf_filter import cffilter
from statsmodels.tsa.filters.hp_filter import hpfilter

#: Minimum number of full cycle periods a sample must span for the cycle to be identifiable.
MINIMUM_PERIODS_IN_SAMPLE = 2.0

#: Band half-width as a fraction of the prior period, used to build a band-pass band from a prior.
DEFAULT_BAND_FRACTION = 0.4


class CycleError(ValueError):
    """Raised when a cycle input is unusable."""


@dataclass(frozen=True)
class CycleBand:
    """A frequency band to extract, derived from a prior period.

    Attributes:
        name: The cycle name.
        prior_period: The prior period in years.
        low_period: The shortest period the band admits, in years.
        high_period: The longest period the band admits, in years.
    """

    name: str
    prior_period: float
    low_period: float
    high_period: float

    @classmethod
    def from_prior(
        cls, name: str, prior_period: float, band_fraction: float = DEFAULT_BAND_FRACTION
    ) -> "CycleBand":
        """Build a band around a prior period."""
        if prior_period <= 0.0:
            raise CycleError(f"cycle {name!r} needs a positive prior period, got {prior_period}")
        if not 0.0 < band_fraction < 1.0:
            raise CycleError(f"band_fraction must lie in (0, 1), got {band_fraction}")
        return cls(
            name=name,
            prior_period=float(prior_period),
            low_period=float(prior_period) * (1.0 - band_fraction),
            high_period=float(prior_period) * (1.0 + band_fraction),
        )

    @classmethod
    def from_explicit(cls, name: str, low_period: float, high_period: float) -> "CycleBand":
        """Build a band from an explicitly observed band, for example the innovation cycle's 40 to 54."""
        if low_period >= high_period:
            raise CycleError(
                f"cycle {name!r} needs low_period below high_period, got {low_period} and {high_period}"
            )
        return cls(
            name=name,
            prior_period=float((low_period + high_period) / 2.0),
            low_period=float(low_period),
            high_period=float(high_period),
        )


def bands_from_config(config, band_fraction: float = DEFAULT_BAND_FRACTION) -> list[CycleBand]:
    """Build the bands for the cycles the configuration asks to decompose.

    A cycle listed in `cycles.explicit_bands` takes that band verbatim instead of `prior +/- band_fraction`.
    Added 2026-08-02 for the fundamental pulse: its default band would reach 2.16 years, which against annual
    sampling is essentially the Nyquist limit, so the filter would alias rather than extract. The explicit
    band keeps it clear of that. See `config/defaults.yaml` under `cycles.explicit_bands`.
    """
    priors = config.get("cycles.priors")
    wanted = config.get("cycles.decompose")
    explicit = config.get("cycles.explicit_bands", default={}) or {}
    bands: list[CycleBand] = []
    for name in wanted:
        if name in explicit:
            low, high = explicit[name]
            bands.append(CycleBand.from_explicit(name, float(low), float(high)))
            continue
        if name == "innovation" and "innovation_observed_band_years" in priors:
            low, high = priors["innovation_observed_band_years"]
            bands.append(CycleBand.from_explicit(name, float(low), float(high)))
            continue
        key = f"{name}_years"
        if key not in priors:
            raise CycleError(f"no prior period configured for cycle {name!r} (expected {key})")
        bands.append(CycleBand.from_prior(name, float(priors[key]), band_fraction))
    return bands


@dataclass
class CycleEstimate:
    """The estimate for one cycle.

    Attributes:
        name: The cycle name.
        band: The band that was extracted.
        identifiable: Whether the sample is long enough to support the estimate.
        component: The extracted cyclical component, or None where unidentifiable.
        estimated_period: The dominant period within the band, estimated from the component's
            spectrum, or None.
        amplitude: The instantaneous amplitude from the analytic signal, or None.
        phase: The instantaneous phase in radians, wrapped to (-pi, pi], or None.
        sample_years: The span of the sample in years.
        notes: Why a cycle was judged unidentifiable, and any other caveat.
    """

    name: str
    band: CycleBand
    identifiable: bool
    component: np.ndarray | None = None
    estimated_period: float | None = None
    amplitude: np.ndarray | None = None
    phase: np.ndarray | None = None
    sample_years: float = 0.0
    notes: list[str] = field(default_factory=list)


def _dominant_period(component: np.ndarray, sampling_per_year: float, band: CycleBand) -> float | None:
    """Estimate the dominant period of a component by its power spectrum, restricted to the band.

    Restricting to the band matters: a band-pass component still carries leakage outside the band, and
    an unrestricted peak search can lock onto it.
    """
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


def extract_cycle(
    values: np.ndarray,
    band: CycleBand,
    sampling_per_year: float = 1.0,
    method: str = "christiano_fitzgerald",
) -> CycleEstimate:
    """Extract one cycle from a series.

    Args:
        values: The series, already detrended or in growth-rate form as the caller intends.
        band: The band to extract.
        sampling_per_year: Observations per year. One for annual data.
        method: `christiano_fitzgerald` (the default, because the periods are known a priori and it
            handles long periods without the end-point distortion Hodrick-Prescott shows on short
            samples) or `hodrick_prescott`.

    Returns:
        The estimate. Where the sample is shorter than MINIMUM_PERIODS_IN_SAMPLE band periods the
        component is not returned and the shortfall is stated.
    """
    series = np.asarray(values, dtype=float)
    if series.ndim != 1:
        raise CycleError(f"expected a one-dimensional series, got shape {series.shape}")
    if np.any(~np.isfinite(series)):
        raise CycleError(
            "the series contains non-finite values. Gaps must be resolved in the data layer, where "
            "they are flagged, rather than silently filled here."
        )

    sample_years = series.size / float(sampling_per_year)
    required = MINIMUM_PERIODS_IN_SAMPLE * band.prior_period
    if sample_years < required:
        return CycleEstimate(
            name=band.name,
            band=band,
            identifiable=False,
            sample_years=sample_years,
            notes=[
                f"the sample spans {sample_years:.1f} years but the {band.name} cycle has a prior "
                f"period of {band.prior_period:.1f} years, so at least {required:.1f} years are "
                f"needed to identify it. No estimate is produced. A band-pass filter would return a "
                f"component regardless, and it would not be an estimate of this cycle."
            ],
        )

    notes: list[str] = []
    if method == "christiano_fitzgerald":
        low = band.low_period * sampling_per_year
        high = band.high_period * sampling_per_year
        component, _trend = cffilter(series, low=low, high=high, drift=False)
    elif method == "hodrick_prescott":
        # Ravn-Uhlig frequency-scaling of lambda for the sampling rate, relative to the annual 6.25.
        smoothing = 6.25 * (sampling_per_year**4)
        component, _trend = hpfilter(series, lamb=smoothing)
        notes.append(
            "Hodrick-Prescott extracts a single cyclical component rather than a band, so the result "
            "is not restricted to this cycle's band and mixes neighbouring cycles"
        )
    else:
        raise CycleError(f"unknown extraction method {method!r}")

    component = np.asarray(component, dtype=float)
    analytic = hilbert(component)

    return CycleEstimate(
        name=band.name,
        band=band,
        identifiable=True,
        component=component,
        estimated_period=_dominant_period(component, sampling_per_year, band),
        amplitude=np.abs(analytic),
        phase=np.angle(analytic),
        sample_years=sample_years,
        notes=notes,
    )


def decompose(
    values: np.ndarray,
    bands: Sequence[CycleBand],
    sampling_per_year: float = 1.0,
    method: str = "christiano_fitzgerald",
) -> dict[str, CycleEstimate]:
    """Extract every requested cycle from a series."""
    return {
        band.name: extract_cycle(values, band, sampling_per_year, method) for band in bands
    }


@dataclass
class AnchoredCycle:
    """A long cycle positioned from supplied structure rather than estimated from the sample.

    Attributes:
        name: The cycle name.
        estimate: A CycleEstimate carrying the constructed component and phase, so that an anchored
            cycle can be passed to detect_synchrony alongside the estimated ones without special-casing.
        period_years: The period used.
        reference_year: The year the anchor pins, interpolated where it falls within a year.
        years_into_cycle: How far into the cycle each period sits.
        anchored: Whether the anchor could be established at all.
        assumed: Whether the anchor is an assumption about the future rather than an observed crossing.
            True only for a capital cycle anchored by projecting the trend forward, and it is what
            separates `Provenance.ASSUMED` from `Provenance.DERIVED`.
        trend_slope: The fitted slope, where the anchor was assumed.
        trend_window: Periods the trend was fitted over, where the anchor was assumed.
        notes: How the anchor was established, and any caveat.
    """

    name: str
    estimate: CycleEstimate
    period_years: float
    reference_year: float | None
    years_into_cycle: np.ndarray | None
    anchored: bool
    assumed: bool = False
    trend_slope: float | None = None
    trend_window: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def provenance(self):
        """What the position is worth, for a chart or a manifest."""
        from macrofield.control import Provenance

        if not self.anchored:
            return Provenance.OBSERVED
        return Provenance.ASSUMED if self.assumed else Provenance.DERIVED


def _anchored_estimate(
    name: str,
    band: CycleBand,
    phase: np.ndarray,
    sample_years: float,
    period_years: float,
    notes: Sequence[str],
) -> CycleEstimate:
    """Wrap a supplied phase path as a CycleEstimate.

    The component is `cos(phase)`, that is the cycle normalised to unit amplitude. It is deliberately not
    scaled to the data: the anchor supplies *where in the cycle* the economy is, and claiming an amplitude
    would be inventing one. The amplitude array is therefore ones, and the note says so.
    """
    return CycleEstimate(
        name=name,
        band=band,
        identifiable=True,
        component=np.cos(phase),
        estimated_period=float(period_years),
        amplitude=np.ones_like(phase),
        phase=_wrap(phase),
        sample_years=sample_years,
        notes=list(notes),
    )


def fixed_innovation_cycle(
    periods: Sequence[object],
    trough_year: float,
    period_years: float,
) -> AnchoredCycle:
    """Build the innovation cycle from a supplied trough, identically for every economy.

    The innovation cycle is a global technological cycle rather than a national one, so it takes the same
    phase in every economy and is not estimated per country. See the module docstring.

    Args:
        periods: The period labels, which must be years.
        trough_year: The year the cycle is at a low. Phase is pi there.
        period_years: The cycle period.

    Returns:
        The anchored cycle. Always anchored, since the trough is supplied rather than found.

    Raises:
        CycleError: If the period is not positive.
    """
    if period_years <= 0.0:
        raise CycleError(f"the innovation period must be positive, got {period_years}")

    years = np.asarray(list(periods), dtype=float)
    if years.size == 0:
        raise CycleError("no periods were given")

    # Phase pi at the trough, following the peak-at-zero convention of extract_cycle.
    phase = 2.0 * np.pi * (years - float(trough_year)) / float(period_years) + np.pi
    years_into_cycle = np.mod(years - float(trough_year), float(period_years))

    notes = [
        f"the innovation cycle is not estimated. It is anchored on a low in {trough_year:g} with a "
        f"period of {period_years:g} years, supplied by the author and applied identically to every "
        f"economy, because it is a global technological cycle and because a {period_years:g}-year cycle "
        f"cannot be estimated from a national-accounts sample.",
        "the amplitude is normalised to one. The anchor gives the position in the cycle, not its size, "
        "and scaling it to the data would be inventing an amplitude.",
    ]

    return AnchoredCycle(
        name="innovation",
        estimate=_anchored_estimate(
            "innovation",
            CycleBand.from_prior("innovation", float(period_years)),
            phase,
            sample_years=float(years.size),
            period_years=float(period_years),
            notes=notes,
        ),
        period_years=float(period_years),
        reference_year=float(trough_year),
        years_into_cycle=years_into_cycle,
        anchored=True,
        notes=notes,
    )


def fixed_hegemonic_cycle(
    periods: Sequence[object],
    peak_year: float,
    period_years: float,
    succession_from: float | None = None,
    succession_to: float | None = None,
) -> AnchoredCycle:
    """Build the hegemonic succession cycle from a supplied peak, identically for every economy.

    Anchored on a **peak** rather than a trough, which is what distinguishes it from
    `fixed_innovation_cycle`. Directed by the author on 2026-08-02: the UK-to-US succession ran from
    **1914** to **1945**, and the anchor is its completion — the post-war settlement, at which the new
    hegemonic order stands at full strength. Phase 0 there, following the peak-at-zero convention of
    `extract_cycle`.

    Args:
        periods: The period labels, which must be years.
        peak_year: The year the cycle is at a high. Phase is 0 there.
        period_years: The cycle period.
        succession_from: The year the succession began, recorded rather than used. Kept because the interval
            is the evidence for the anchor and a reader should be able to see it without leaving the object.
        succession_to: The year it completed. Normally equal to `peak_year`.

    Returns:
        The anchored cycle. Always anchored, since the peak is supplied rather than found.

    Raises:
        CycleError: If the period is not positive, or no periods were given.

    **What this anchoring does not say, and it is worth being explicit.** The 1929 crash falls inside the
    supplied succession interval, and it is the deepest market dislocation of the era. It is *not* a trough of
    this cycle: with a peak at 1945 and a 130-year period, 1929 sits on the **rising limb** at about +0.72,
    sixteen years before the peak. Both things are true, and the gap between them is the point of the whole
    nested-cycle apparatus — a severe crisis need not coincide with the slowest cycle's low, and reading
    fragility off any single cycle is the error the interference measure exists to avoid. Recorded here rather
    than in a change report, because this is where somebody will come looking for it.
    """
    if period_years <= 0.0:
        raise CycleError(f"the hegemonic period must be positive, got {period_years}")

    years = np.asarray(list(periods), dtype=float)
    if years.size == 0:
        raise CycleError("no periods were given")

    # Phase 0 at the peak: no offset, unlike the innovation cycle's trough anchoring.
    phase = 2.0 * np.pi * (years - float(peak_year)) / float(period_years)
    years_into_cycle = np.mod(years - float(peak_year), float(period_years))

    interval = ""
    if succession_from is not None and succession_to is not None:
        span = float(succession_to) - float(succession_from)
        interval = (
            f" The succession it is anchored on ran {succession_from:g} to {succession_to:g}, a span of "
            f"{span:g} years or {span / float(period_years):.1%} of the period."
        )

    notes = [
        f"the hegemonic succession cycle is not estimated. It is anchored on a high in {peak_year:g} with a "
        f"period of {period_years:g} years, supplied by the author and applied identically to every economy, "
        f"because hegemonic order is a global structure rather than a national one and because a "
        f"{period_years:g}-year cycle cannot be estimated from any national-accounts sample that exists."
        + interval,
        "the amplitude is normalised to one. The anchor gives the position in the cycle, not its size, "
        "and scaling it to the data would be inventing an amplitude.",
        "excluded from the interference measure by configuration. It is positioned and reported, and it does "
        "not enter the alignment measure the fragility window is computed from, so adding it did not move a "
        "published conclusion. See cycles.anchored.hegemonic.in_interference.",
    ]

    return AnchoredCycle(
        name="hegemonic",
        estimate=_anchored_estimate(
            "hegemonic",
            CycleBand.from_prior("hegemonic", float(period_years)),
            phase,
            sample_years=float(years.size),
            period_years=float(period_years),
            notes=notes,
        ),
        period_years=float(period_years),
        reference_year=float(peak_year),
        years_into_cycle=years_into_cycle,
        anchored=True,
        notes=notes,
    )


def anchor_capital_cycle(
    periods: Sequence[object],
    saturation: Sequence[float],
    anchor_saturation: float = 3.5,
    years_into_cycle_at_anchor: float = 90.0,
    period_years: float = 90.0,
) -> AnchoredCycle:
    """Date the capital cycle from where the saturation axis crosses a given ratio.

    Reaching `anchor_saturation` means the economy is `years_into_cycle_at_anchor` years into the capital
    cycle, on the author's instruction of 2026-07-27. That single fact dates the whole cycle, which is
    otherwise unestimatable from any national-accounts series.

    The crossing is interpolated within the year rather than snapped to an annual observation, because
    snapping would quantise the cycle position to whole years for no reason.

    Where the axis crosses more than once, the **last upward crossing** is used, since the cycle position
    is a statement about where the economy is now rather than where it has been.

    Args:
        periods: The period labels, which must be years.
        saturation: The saturation axis, aligned with `periods`.
        anchor_saturation: The ratio that marks `years_into_cycle_at_anchor`.
        years_into_cycle_at_anchor: How far into the cycle that ratio falls.
        period_years: The cycle period.

    Returns:
        The anchored cycle. Where the axis never reaches the anchor the result is `anchored=False` with
        the shortfall stated, rather than an extrapolated position: an economy that has not reached 3.5
        has no anchor, and guessing where it sits in a 90-year cycle from a 50-year sample is precisely
        what this anchoring exists to avoid.

    Raises:
        CycleError: If the inputs disagree in length or the period is not positive.
    """
    if period_years <= 0.0:
        raise CycleError(f"the capital period must be positive, got {period_years}")

    years = np.asarray(list(periods), dtype=float)
    values = np.asarray(saturation, dtype=float)
    if years.shape != values.shape:
        raise CycleError(
            f"periods and saturation must share a shape, got {years.shape} and {values.shape}"
        )
    if years.size == 0:
        raise CycleError("no periods were given")

    band = CycleBand.from_prior("capital", float(period_years))
    finite = np.isfinite(values)

    # Upward crossings of the anchor ratio, between consecutive finite observations.
    crossings: list[float] = []
    for index in range(1, years.size):
        if not (finite[index - 1] and finite[index]):
            continue
        below, now = values[index - 1], values[index]
        if below < anchor_saturation <= now:
            span = now - below
            fraction = (anchor_saturation - below) / span if span else 0.0
            crossings.append(float(years[index - 1] + fraction * (years[index] - years[index - 1])))

    peak = float(np.nanmax(values)) if finite.any() else float("nan")

    if not crossings:
        note = (
            f"the capital cycle is not anchored: the saturation axis peaks at {peak:.2f} over this "
            f"window and never reaches the anchor of {anchor_saturation:.2f}, which is what would date "
            f"the cycle. No position is reported, because placing a {period_years:g}-year cycle from a "
            f"{years.size}-year sample without the anchor would be a guess."
        )
        return AnchoredCycle(
            name="capital",
            estimate=CycleEstimate(
                name="capital",
                band=band,
                identifiable=False,
                sample_years=float(years.size),
                notes=[note],
            ),
            period_years=float(period_years),
            reference_year=None,
            years_into_cycle=None,
            anchored=False,
            notes=[note],
        )

    reference = crossings[-1]
    years_into_cycle = years - reference + float(years_into_cycle_at_anchor)

    # Phase 0 at the anchor, because that is where saturation peaks and the reordering occurs.
    phase = 2.0 * np.pi * (years - reference) / float(period_years)

    notes = [
        f"the capital cycle is not estimated. It is anchored on the saturation axis crossing "
        f"{anchor_saturation:.2f} in {reference:.1f}, which the author places at "
        f"{years_into_cycle_at_anchor:g} years into a {period_years:g}-year cycle. A "
        f"{period_years:g}-year cycle cannot be estimated from a {years.size}-year sample.",
        "phase zero sits at the crossing, since that is where saturation peaks and the reordering "
        "occurs. The cycle's trough is therefore half a period earlier.",
        "the amplitude is normalised to one. The anchor gives the position in the cycle, not its size.",
    ]
    if len(crossings) > 1:
        notes.append(
            f"the axis crossed {anchor_saturation:.2f} {len(crossings)} times, at "
            f"{', '.join(f'{c:.1f}' for c in crossings)}. The last crossing is used, so the position is "
            f"a statement about the current cycle rather than an average over past ones."
        )

    return AnchoredCycle(
        name="capital",
        estimate=_anchored_estimate(
            "capital",
            band,
            phase,
            sample_years=float(years.size),
            period_years=float(period_years),
            notes=notes,
        ),
        period_years=float(period_years),
        reference_year=reference,
        years_into_cycle=years_into_cycle,
        anchored=True,
        notes=notes,
    )


def anchor_capital_cycle_by_projection(
    periods: Sequence[object],
    saturation: Sequence[float],
    anchor_saturation: float = 3.5,
    years_into_cycle_at_anchor: float = 90.0,
    period_years: float = 90.0,
    trend_window: int = 10,
    maximum_years_ahead: float = 120.0,
) -> AnchoredCycle:
    """Anchor an economy that has not reached the anchor ratio, by solving for when it would.

    Phase 2.2 of docs/BATTLE_PLAN.md, on the author's instruction of 2026-07-28: where there is no capital
    cycle, assume when it would hit the mark and compute from there linearly.

    The recent trend of the saturation axis is fitted by least squares over `trend_window` periods and
    extended to find the year it would cross `anchor_saturation`. The whole cycle is then dated from that
    provisional crossing exactly as `anchor_capital_cycle` dates it from a real one, and everything it
    produces carries `Provenance.ASSUMED`.

    **Where the trend is flat or falling there is no crossing, and none is invented.** Assuming *when* an
    economy reaches saturation is a reasonable extrapolation of a rising trend. Assuming *that* it will,
    against a trend that says otherwise, would be a different and much weaker claim, so it is refused and
    the reason is reported.

    Args:
        periods: The period labels, which must be years.
        saturation: The saturation axis, aligned with `periods`.
        anchor_saturation: The ratio that marks `years_into_cycle_at_anchor`.
        years_into_cycle_at_anchor: How far into the cycle that ratio falls.
        period_years: The cycle period.
        trend_window: Periods of recent history the trend is fitted over.
        maximum_years_ahead: How far ahead a crossing may be and still be reported. A trend that reaches
            the anchor in three centuries is arithmetically a crossing and analytically nothing.

    Returns:
        The anchored cycle, with `anchored` true only where a crossing was found.

    Raises:
        CycleError: If the inputs disagree in length or the period is not positive.
    """
    if period_years <= 0.0:
        raise CycleError(f"the capital period must be positive, got {period_years}")

    years = np.asarray(list(periods), dtype=float)
    values = np.asarray(saturation, dtype=float)
    if years.shape != values.shape:
        raise CycleError(
            f"periods and saturation must share a shape, got {years.shape} and {values.shape}"
        )

    band = CycleBand.from_prior("capital", float(period_years))
    finite = np.isfinite(values)
    if finite.sum() < 2:
        note = "the saturation axis has fewer than two finite observations, so no trend can be fitted"
        return AnchoredCycle(
            name="capital",
            estimate=CycleEstimate("capital", band, False, sample_years=float(years.size), notes=[note]),
            period_years=float(period_years),
            reference_year=None,
            years_into_cycle=None,
            anchored=False,
            notes=[note],
        )

    window = min(int(trend_window), int(finite.sum()))
    recent_years = years[finite][-window:]
    recent_values = values[finite][-window:]
    slope, intercept = np.polyfit(recent_years, recent_values, 1)

    latest_year = float(years[finite][-1])
    latest_value = float(values[finite][-1])

    if slope <= 0.0:
        note = (
            f"the capital cycle is not anchored, even provisionally. The saturation axis stands at "
            f"{latest_value:.2f} against an anchor of {anchor_saturation:.2f}, and its trend over the last "
            f"{window} periods is {slope:+.4f} a year, so it is not approaching the anchor at all. "
            f"Assuming when an economy reaches saturation extrapolates a rising trend; assuming that it "
            f"will, against a falling one, is a different and much weaker claim, so it is refused."
        )
        return AnchoredCycle(
            name="capital",
            estimate=CycleEstimate("capital", band, False, sample_years=float(years.size), notes=[note]),
            period_years=float(period_years),
            reference_year=None,
            years_into_cycle=None,
            anchored=False,
            notes=[note],
        )

    crossing = (float(anchor_saturation) - float(intercept)) / float(slope)
    years_ahead = crossing - latest_year

    if years_ahead > float(maximum_years_ahead):
        note = (
            f"the capital cycle is not anchored. The trend over the last {window} periods reaches the "
            f"anchor of {anchor_saturation:.2f} only in {crossing:.0f}, which is {years_ahead:.0f} years "
            f"ahead of {latest_year:.0f}. A crossing that far out is arithmetic rather than a position in "
            f"a cycle."
        )
        return AnchoredCycle(
            name="capital",
            estimate=CycleEstimate("capital", band, False, sample_years=float(years.size), notes=[note]),
            period_years=float(period_years),
            reference_year=None,
            years_into_cycle=None,
            anchored=False,
            notes=[note],
        )

    years_into_cycle = years - crossing + float(years_into_cycle_at_anchor)
    phase = 2.0 * np.pi * (years - crossing) / float(period_years)

    notes = [
        f"the capital cycle is ASSUMED, not anchored on an observed crossing. The saturation axis stands "
        f"at {latest_value:.2f} and has never reached the anchor of {anchor_saturation:.2f}, so the "
        f"crossing is solved from the trend of the last {window} periods, {slope:+.4f} a year, giving "
        f"{crossing:.1f}. Everything derived from it is an assumption about the future, not a measurement.",
        f"the position is therefore {float(years_into_cycle[-1]):.0f} years into a "
        f"{period_years:g}-year cycle, on that assumption.",
        "the answer moves with the trend window. A different window gives a different crossing, and the "
        "sensitivity should be checked before the number is quoted.",
        "the amplitude is normalised to one. The anchor gives the position in the cycle, not its size.",
    ]

    return AnchoredCycle(
        name="capital",
        estimate=_anchored_estimate(
            "capital",
            band,
            phase,
            sample_years=float(years.size),
            period_years=float(period_years),
            notes=notes,
        ),
        period_years=float(period_years),
        reference_year=crossing,
        years_into_cycle=years_into_cycle,
        anchored=True,
        assumed=True,
        trend_slope=float(slope),
        trend_window=window,
        notes=notes,
    )


def reordering_end(phase_labels: Sequence[str], foundation_label: str = "Foundation") -> int | None:
    """The index at which a completed reordering hands over to a new cycle, or None.

    That is the first period classified Foundation *after* a period in Saturation. Entering Foundation
    without having been in Saturation is not the end of a reordering, it is simply an unsaturated economy, so
    it does not restart anything.
    """
    labels = list(phase_labels)
    seen_saturation = False
    for index, label in enumerate(labels):
        if label == foundation_label and seen_saturation:
            return index
        if label != foundation_label:
            seen_saturation = seen_saturation or "Saturation" in label
    return None


def years_into_capital_cycle(
    periods: Sequence[object],
    reference_year: float,
    years_into_cycle_at_anchor: float,
    period_years: float,
    restart_year: float | None = None,
) -> np.ndarray:
    """How far into the capital cycle each period sits, restarting at a completed reordering.

    Directed by the author on 2026-07-28, and the consequence of the phase rule settled the same day: the
    reordering ends when saturation reaches the Foundation level, and at that point **the cycle restarts**.

    Without the restart the anchor stays at the last observed crossing and "years into the cycle" grows
    without bound, so an economy that has already been through its reordering goes on being reported as
    decades late for it. On United States projected data that pushed weight to crisis in ten periods where
    the correction was already behind the economy.

    Args:
        periods: The period labels, which must be years.
        reference_year: The observed crossing of the anchor ratio.
        years_into_cycle_at_anchor: How far into the cycle that crossing falls.
        period_years: The cycle period, used only for the caller's overdue arithmetic.
        restart_year: Where a completed reordering handed over. From that year the count begins again at
            zero, because the economy is at the start of a new cycle rather than the end of the old one.

    Returns:
        Years into the cycle per period.
    """
    years = np.asarray(list(periods), dtype=float)
    into = years - float(reference_year) + float(years_into_cycle_at_anchor)
    if restart_year is not None:
        after = years >= float(restart_year)
        into = np.where(after, years - float(restart_year), into)
    return into


def _optional_year(value: object) -> float | None:
    """A configured year, or None where the key is absent. Kept separate so an absent key and a zero cannot
    be confused: a succession starting in year 0 is not a thing, but neither is silently reading one."""
    return None if value is None else float(value)


def interference_members(config, anchored: Mapping[str, "AnchoredCycle"]) -> list[str]:
    """Which anchored cycles may enter the alignment measure.

    An anchored cycle is included unless its configuration says `in_interference: false`. The hegemonic cycle
    sets that flag, so it is positioned and reported without contributing to the fragility window
    (`DECISIONS.md` M52). Returning names rather than filtering the dict keeps the exclusion visible at the
    call site: a caller that wants everything can still pass everything, and has to say so.
    """
    settings = config.get("cycles.anchored", default={}) or {}
    out: list[str] = []
    for name in anchored:
        entry = settings.get(name) or {}
        if entry.get("in_interference", True):
            out.append(name)
    return out


def anchored_from_config(
    config,
    periods: Sequence[object],
    saturation: Sequence[float] | None = None,
    assume_capital_crossing: bool = False,
) -> dict[str, AnchoredCycle]:
    """Build every anchored cycle the configuration declares.

    The capital cycle needs the saturation axis to find its anchor. Where it is not supplied the capital
    cycle is omitted rather than anchored on a default, since the anchor is the whole content of it.

    Every declared cycle is built, including one flagged `in_interference: false`. Building and *using* are
    separated on purpose: the hegemonic cycle is positioned and reported but excluded from the alignment
    measure, and a function that refused to build it would make its phase unreportable as a side effect of a
    decision about interference. Use `interference_members` to filter at the point of use.

    Args:
        config: A loaded Config.
        periods: The period labels.
        saturation: The saturation axis, needed for the capital anchor.
        assume_capital_crossing: Where the axis has never reached the anchor ratio, solve the recent trend
            for when it would and anchor provisionally on that, marked as an assumption. Off by default, so
            an ordinary run still reports an economy as unanchored rather than quietly assuming a future.
    """
    settings = config.get("cycles.anchored", default={}) or {}
    anchored: dict[str, AnchoredCycle] = {}

    innovation = settings.get("innovation")
    if innovation:
        anchored["innovation"] = fixed_innovation_cycle(
            periods,
            trough_year=float(innovation["trough_year"]),
            period_years=float(innovation["period_years"]),
        )

    hegemonic = settings.get("hegemonic")
    if hegemonic:
        anchored["hegemonic"] = fixed_hegemonic_cycle(
            periods,
            peak_year=float(hegemonic["peak_year"]),
            period_years=float(hegemonic["period_years"]),
            succession_from=_optional_year(hegemonic.get("succession_from")),
            succession_to=_optional_year(hegemonic.get("succession_to")),
        )

    capital = settings.get("capital")
    if capital and saturation is not None:
        observed = anchor_capital_cycle(
            periods,
            saturation,
            anchor_saturation=float(capital["anchor_saturation"]),
            years_into_cycle_at_anchor=float(capital["years_into_cycle_at_anchor"]),
            period_years=float(capital["period_years"]),
        )
        if observed.anchored or not assume_capital_crossing:
            anchored["capital"] = observed
        else:
            assumed = anchor_capital_cycle_by_projection(
                periods,
                saturation,
                anchor_saturation=float(capital["anchor_saturation"]),
                years_into_cycle_at_anchor=float(capital["years_into_cycle_at_anchor"]),
                period_years=float(capital["period_years"]),
                trend_window=int(capital.get("assume_trend_window", 10)),
                maximum_years_ahead=float(capital.get("assume_maximum_years_ahead", 120.0)),
            )
            # Carry the reason the observed anchor failed, so the assumption is read against it.
            assumed.notes = list(observed.notes) + list(assumed.notes)
            anchored["capital"] = assumed
    return anchored


@dataclass
class Superposition:
    """The cycles summed, and where they reinforce or cancel.

    Phase 3 of docs/BATTLE_PLAN.md. The framework's claim is that peak fragility is where the sub-cycles
    come into phase, so the object that matters is not any one cycle but their sum.

    **Every component is normalised to unit amplitude before summing**, settled by the author on
    2026-07-28. The amplitudes are not comparable: a band-passed business cycle is a deviation in a growth
    rate of order 0.02, and an anchored capital cycle is a position with no amplitude at all, because an
    anchor says where in a cycle an economy is and not how large the cycle is. Summing them raw would make
    the total a picture of whichever cycles happened to be anchored. Normalising makes the sum a statement
    about **phase alignment only**, which is what the framework's claim is actually about, and the per-cycle
    weights are exposed so a considered view about relative importance can be applied deliberately.

    Attributes:
        periods: The period labels.
        components: Cycle name to its normalised component, each in [-1, 1].
        weights: The weight applied to each.
        total: The weighted sum, divided by the total weight so it stays in [-1, 1].
        alignment: How far the cycles agree at each period, from 0 when they cancel exactly to 1 when they
            all point the same way. This is the constructive-interference measure. NaN where every component
            sits at a zero crossing, since there is then nothing to align and reporting 0 would read as a
            finding that they cancel.
        stabilising: Per period, the cycles currently contributing positively.
        destabilising: Per period, the cycles currently contributing negatively.
        excluded: Cycles left out, and why.
        notes: Anything a reader must know.
    """

    periods: np.ndarray
    components: dict[str, np.ndarray]
    weights: dict[str, float]
    total: np.ndarray
    alignment: np.ndarray
    stabilising: list[list[str]] = field(default_factory=list)
    destabilising: list[list[str]] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def at(self, index: int = -1) -> dict[str, Any]:
        """The reading at one period, latest by default."""
        return {
            "period": self.periods[index],
            "total": float(self.total[index]),
            "alignment": float(self.alignment[index]),
            "stabilising": list(self.stabilising[index]),
            "destabilising": list(self.destabilising[index]),
            "components": {name: float(values[index]) for name, values in self.components.items()},
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "periods": [int(p) for p in self.periods],
            "components": {name: [float(v) for v in values] for name, values in self.components.items()},
            "weights": dict(self.weights),
            "total": [float(v) for v in self.total],
            "alignment": [float(v) for v in self.alignment],
            "stabilising": [list(names) for names in self.stabilising],
            "destabilising": [list(names) for names in self.destabilising],
            "excluded": dict(self.excluded),
            "latest": self.at(),
            "notes": list(self.notes),
        }


def _unit_amplitude(component: np.ndarray) -> np.ndarray:
    """Scale a component so its largest absolute value is one.

    Deliberately the peak rather than the standard deviation: the question the superposition answers is
    where the cycles line up at their extremes, and dividing by a spread would let a spiky cycle dominate a
    smooth one of the same reach.
    """
    values = np.asarray(component, dtype=float)
    peak = float(np.nanmax(np.abs(values))) if values.size else 0.0
    return values / peak if peak > 0.0 else np.zeros_like(values)


def superpose(
    periods: Sequence[object],
    estimates: Mapping[str, CycleEstimate],
    weights: Mapping[str, float] | None = None,
) -> Superposition:
    """Sum the cycles at unit amplitude and report where they reinforce.

    Args:
        periods: The period labels.
        estimates: The cycles, estimated or anchored. Any without a component is excluded and named.
        weights: Per-cycle weight. Defaults to equal, which is the configured default.

    Returns:
        The superposition.

    Raises:
        CycleError: If no cycle carries a component, or a component's length disagrees with the periods.
    """
    period_array = np.asarray(list(periods))
    usable: dict[str, np.ndarray] = {}
    excluded: dict[str, str] = {}

    for name, estimate in estimates.items():
        if estimate.component is None or not estimate.identifiable:
            excluded[name] = (
                estimate.notes[0]
                if estimate.notes
                else "no component was produced, so it cannot enter the sum"
            )
            continue
        component = np.asarray(estimate.component, dtype=float)
        if component.size != period_array.size:
            raise CycleError(
                f"cycle {name!r} has {component.size} values but {period_array.size} periods were given"
            )
        usable[name] = _unit_amplitude(component)

    if not usable:
        raise CycleError(
            "no cycle carries a component, so there is nothing to superpose. This is not a finding that "
            "the cycles cancel."
        )

    applied = {name: float((weights or {}).get(name, 1.0)) for name in usable}
    if any(w < 0.0 for w in applied.values()):
        raise CycleError(f"cycle weights must be non-negative, got {applied}")
    total_weight = sum(applied.values())
    if total_weight <= 0.0:
        raise CycleError("the cycle weights sum to zero, so the superposition is undefined")

    stacked = np.vstack([usable[name] * applied[name] for name in usable])
    total = stacked.sum(axis=0) / total_weight

    # Alignment: the sum's magnitude against the sum of magnitudes. One when every cycle points the same
    # way, zero when they cancel exactly. This is the constructive-interference measure, and it is
    # independent of how large the cycles are, which is the point of normalising first.
    #
    # Where every component is at a zero crossing there is nothing to align, so alignment is NaN rather
    # than zero: reporting zero there would read as "the cycles cancel", which is a finding, when the truth
    # is that the measure is undefined. Downstream consumers already guard on finiteness.
    magnitudes = np.abs(stacked).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        alignment = np.where(
            magnitudes > 1e-12, np.abs(stacked.sum(axis=0)) / np.where(magnitudes > 0, magnitudes, 1.0), np.nan
        )

    names = list(usable)
    stabilising: list[list[str]] = []
    destabilising: list[list[str]] = []
    for index in range(period_array.size):
        stabilising.append([n for n in names if usable[n][index] > 0.0])
        destabilising.append([n for n in names if usable[n][index] < 0.0])

    notes = [
        "every component is normalised to unit amplitude before summing, because a band-passed growth-rate "
        "deviation and an anchored cycle position are not comparable magnitudes. The sum is therefore a "
        "statement about phase alignment, not about size.",
        "alignment runs from zero, where the cycles cancel, to one, where they all point the same way. The "
        "framework places peak fragility where alignment is high and the total is negative.",
    ]
    if excluded:
        notes.append(
            f"excluded from the sum: {', '.join(sorted(excluded))}. A superposition computed without them "
            f"is a statement about the remaining cycles only."
        )
    if len({round(w, 9) for w in applied.values()}) == 1:
        notes.append(
            "the cycles are equally weighted, which is the configured default and asserts nothing about "
            "their relative importance."
        )

    return Superposition(
        periods=period_array,
        components=usable,
        weights=applied,
        total=total,
        alignment=alignment,
        stabilising=stabilising,
        destabilising=destabilising,
        excluded=excluded,
        notes=notes,
    )


def spectrum(
    values: np.ndarray, sampling_per_year: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Return the power spectrum against period in years, for the cycle-spectrum chart.

    Returns:
        The periods in years and the corresponding power, ordered by increasing period.
    """
    series = np.asarray(values, dtype=float)
    if series.size < 8:
        raise CycleError(f"a spectrum needs at least 8 observations, got {series.size}")
    segment = min(series.size, max(8, series.size // 2))
    frequencies, power = welch(series, fs=sampling_per_year, nperseg=segment)
    positive = frequencies > 0.0
    periods = 1.0 / frequencies[positive]
    order = np.argsort(periods)
    return periods[order], power[positive][order]


def _wrap(angle: np.ndarray) -> np.ndarray:
    """Wrap an angle to (-pi, pi]."""
    return (np.asarray(angle, dtype=float) + np.pi) % (2.0 * np.pi) - np.pi


@dataclass
class SynchronyWindow:
    """A window in which several cycles are in phase.

    Attributes:
        start_index: First index of the window.
        end_index: Last index of the window, inclusive.
        start_period: The period label at the start.
        end_period: The period label at the end.
        cycles_in_phase: The cycles that are in phase across the window.
        mean_absolute_phase_spread: Mean absolute pairwise phase difference across the window, in
            radians. Smaller means more tightly synchronised.
    """

    start_index: int
    end_index: int
    start_period: object
    end_period: object
    cycles_in_phase: list[str]
    mean_absolute_phase_spread: float


@dataclass
class SynchronyResult:
    """The synchrony analysis across the decomposed cycles.

    Attributes:
        pairwise_phase_difference: Mean absolute phase difference per cycle pair, in radians.
        windows: The detected constructive-interference windows.
        current_window: The window covering the final period, if any.
        excluded_cycles: Cycles left out because they were unidentifiable.
        notes: Anything a reader must know.
    """

    pairwise_phase_difference: dict[tuple[str, str], float]
    windows: list[SynchronyWindow]
    current_window: SynchronyWindow | None
    excluded_cycles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def detect_synchrony(
    periods: Sequence[object],
    estimates: Mapping[str, CycleEstimate],
    phase_tolerance_radians: float = 0.5,
    minimum_cycles_in_phase: int = 3,
) -> SynchronyResult:
    """Detect windows where the cycles come into phase.

    A period counts as synchronised when at least `minimum_cycles_in_phase` of the identifiable
    cycles have pairwise phase differences within the tolerance. Contiguous synchronised periods are
    merged into a window.

    Args:
        periods: The period labels.
        estimates: The decomposed cycles.
        phase_tolerance_radians: How close two phases must be to count as in phase.
        minimum_cycles_in_phase: How many cycles must agree before a window is reported.

    Returns:
        The synchrony result. Where fewer than two cycles are identifiable, no window can be detected
        and that is stated rather than returning an empty result that reads as "no synchronisation".
    """
    period_array = np.asarray(list(periods))
    usable = {
        name: estimate
        for name, estimate in estimates.items()
        if estimate.identifiable and estimate.phase is not None
    }
    excluded = sorted(set(estimates) - set(usable))

    notes: list[str] = []
    if excluded:
        notes.append(
            f"excluded from the synchrony analysis because the sample is too short to identify them: "
            f"{', '.join(excluded)}. A synchronisation window computed without them is a statement "
            f"about the remaining cycles only."
        )

    if len(usable) < 2:
        notes.append(
            f"only {len(usable)} cycle(s) are identifiable, so phase synchrony cannot be assessed. "
            f"This is not a finding that the cycles are out of phase."
        )
        return SynchronyResult({}, [], None, excluded, notes)

    for name, estimate in usable.items():
        if estimate.phase is not None and estimate.phase.size != period_array.size:
            raise CycleError(
                f"cycle {name!r} has {estimate.phase.size} phase values but {period_array.size} "
                f"periods were given"
            )

    names = sorted(usable)
    pairwise: dict[tuple[str, str], float] = {}
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            difference = np.abs(_wrap(usable[first].phase - usable[second].phase))
            pairwise[(first, second)] = float(np.mean(difference))

    # Per period, find the largest set of cycles that are mutually within tolerance.
    synchronised = np.zeros(period_array.size, dtype=bool)
    in_phase_names: list[list[str]] = []
    spreads = np.full(period_array.size, np.nan)

    for index in range(period_array.size):
        phases = {name: float(usable[name].phase[index]) for name in names}
        best: list[str] = []
        best_spread = np.inf
        # Anchor on each cycle in turn and collect those within tolerance of it.
        for anchor in names:
            group = [
                name
                for name in names
                if abs(float(_wrap(np.array([phases[name] - phases[anchor]]))[0]))
                <= phase_tolerance_radians
            ]
            if len(group) < 2:
                continue
            differences = [
                abs(float(_wrap(np.array([phases[a] - phases[b]]))[0]))
                for i, a in enumerate(group)
                for b in group[i + 1 :]
            ]
            spread = float(np.mean(differences)) if differences else 0.0
            if len(group) > len(best) or (len(group) == len(best) and spread < best_spread):
                best, best_spread = group, spread
        in_phase_names.append(sorted(best))
        if len(best) >= minimum_cycles_in_phase:
            synchronised[index] = True
            spreads[index] = best_spread

    windows: list[SynchronyWindow] = []
    start: int | None = None
    for index in range(period_array.size + 1):
        active = bool(synchronised[index]) if index < period_array.size else False
        if active and start is None:
            start = index
        elif not active and start is not None:
            end = index - 1
            members = sorted({name for i in range(start, end + 1) for name in in_phase_names[i]})
            window_spread = float(np.nanmean(spreads[start : end + 1]))
            windows.append(
                SynchronyWindow(
                    start_index=start,
                    end_index=end,
                    start_period=period_array[start].item()
                    if hasattr(period_array[start], "item")
                    else period_array[start],
                    end_period=period_array[end].item()
                    if hasattr(period_array[end], "item")
                    else period_array[end],
                    cycles_in_phase=members,
                    mean_absolute_phase_spread=window_spread,
                )
            )
            start = None

    current = next(
        (w for w in windows if w.end_index == period_array.size - 1), None
    )
    return SynchronyResult(pairwise, windows, current, excluded, notes)
