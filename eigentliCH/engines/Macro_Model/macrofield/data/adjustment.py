"""Standardising adjustments for poorly defined source data.

The published series this model consumes are not clean measurements of the theoretical quantities. Book
chapter 10 is explicit about it: output is inflated by imputed components, hedonic quality adjustment and
FISIM; financial aggregates double count; capital stocks are themselves modelled by perpetual inventory;
and section 10.6 records that alternative United States GDP estimates on more conservative methodologies
run 10 to 20 per cent below the official ones, with official inflation understating the alternative
measures by several percentage points a year.

Since the framework's conclusions rest on dynamics and on derived projections rather than on exact
levels, the right response is to carry an explicit adjustment per series rather than to pretend the
published number is the theoretical quantity.

**The invariant this module guarantees.**

Every adjustment available here is a multiplicative scaling of the level, and nothing else. That makes it
*invisible* to every criterion the model is judged on: scaling a series by a constant leaves its growth
rates identical, its direction identical, and its turning points in exactly the same periods, because
`d log(cX)/dt = d log(X)/dt` for any constant `c`. So an adjustment absorbs definitional and scope bias
at zero cost to the dynamic assessment. What it does change is the ratios between series, which is where
it does real work: `K_R/Y` and the saturation axis both move, and those are what the phase classifier and
HoNI consume.

**Drift adjustment is deliberately not available.** An additive correction to the growth rate, which is
what a deflator-bias correction amounts to, would change the trend and could change whether a series is
rising at all. The author ruled it out on 2026-07-27. It is not implemented, not defaulted to zero and
not reachable behind a flag, because an option that must never be used is better removed than guarded:
leaving it available would mean every downstream reader had to check whether it had been applied.

The consequence is a guarantee rather than a discipline. No adjustment this module can produce is capable
of altering a growth rate, a direction, or a turning point. `ADJUSTMENTS_ARE_DYNAMICS_NEUTRAL` states it
and `tests/test_adjustment.py` asserts it as a property across the whole permitted range of scales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from macrofield.data.provenance import Reliability, Series

#: The invariant this module guarantees, asserted as a property test. No adjustment available here can
#: change a growth rate, a direction, or a turning-point period, because level scaling is the only
#: operation offered and drift adjustment is deliberately not implemented.
ADJUSTMENTS_ARE_DYNAMICS_NEUTRAL = True


class AdjustmentError(ValueError):
    """Raised when an adjustment is not usable."""


@dataclass(frozen=True)
class SeriesAdjustment:
    """A documented multiplicative adjustment to one series' level.

    There is deliberately no drift or growth-rate parameter. See the module docstring: an additive growth
    correction would break the dynamics-neutrality guarantee, and it was ruled out rather than guarded.

    Attributes:
        level_scale: Multiplicative factor on the level. One means no adjustment.
        rationale: Why the adjustment is applied. Required, because an undocumented adjustment to
            published data is indistinguishable from fabricating it.
        source: Where the magnitude comes from.
        prior_range: The plausible range of `level_scale`, used by the sensitivity sweep.
    """

    level_scale: float = 1.0
    rationale: str = ""
    source: str = ""
    prior_range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.level_scale <= 0.0:
            raise AdjustmentError(
                f"level_scale must be positive, got {self.level_scale}. A negative or zero scale would "
                f"change the sign or annihilate the series rather than adjust it."
            )
        if not np.isfinite(self.level_scale):
            raise AdjustmentError(f"level_scale must be finite, got {self.level_scale}")
        if self.is_identity:
            return
        if not self.rationale:
            raise AdjustmentError(
                "a non-identity adjustment must state its rationale. An undocumented adjustment to "
                "published data cannot be distinguished from fabricating it."
            )
        if not self.source:
            raise AdjustmentError(
                "a non-identity adjustment must state where its magnitude comes from, so a reader can "
                "judge it rather than inherit it"
            )
        if self.prior_range is not None:
            low, high = self.prior_range
            if not low <= self.level_scale <= high:
                raise AdjustmentError(
                    f"level_scale {self.level_scale} sits outside its own declared prior range "
                    f"{self.prior_range}"
                )

    @property
    def is_identity(self) -> bool:
        """Whether this adjustment changes anything."""
        return self.level_scale == 1.0

    @property
    def is_dynamics_neutral(self) -> bool:
        """Always true. Retained so a consumer can assert the invariant rather than assume it."""
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "level_scale": self.level_scale,
            "dynamics_neutral": True,
            "rationale": self.rationale,
            "source": self.source,
            "prior_range": list(self.prior_range) if self.prior_range else None,
        }


#: Documented adjustment priors, from the sources rather than invented.
#:
#: Every entry is the identity by default. These are the *ranges* the sensitivity run should explore,
#: not corrections silently applied: applying them by default would replace one poorly defined number
#: with another and hide the choice.
ADJUSTMENT_PRIORS: Mapping[str, SeriesAdjustment] = {
    "Y": SeriesAdjustment(
        level_scale=1.0,
        rationale=(
            "measured GDP is inflated relative to the theoretical productive output by imputed "
            "components (chiefly owner-occupied housing), hedonic quality adjustment, and FISIM-based "
            "financial-sector value added. Book section 10.2 names all three and section 10.6 records "
            "that alternative estimates on more conservative methodologies run 10 to 20 per cent lower. "
            "A level scale below one moves the capital-saturation ratios up, which the book notes are "
            "correspondingly understated."
        ),
        source="Capital Saturation sections 10.2 and 10.6",
        prior_range=(0.80, 1.00),
    ),
    "K_R": SeriesAdjustment(
        level_scale=1.0,
        rationale=(
            "the conventional national-accounts capital definition covers only tangible reproducible "
            "assets and excludes land and mineral resources even where they are plainly productive, "
            "which understates the productive capital stock. Book section 10.3 states this, and notes it "
            "bites hardest for resource-rich economies."
        ),
        source="Capital Saturation section 10.3",
        prior_range=(1.00, 1.30),
    ),
    "K_I": SeriesAdjustment(
        level_scale=1.0,
        rationale=(
            "financial-asset aggregates double count, because a deposit is a claim on a bank which holds "
            "securities which are claims on issuers. Consolidation methodologies exist but are applied "
            "inconsistently in public data. Book section 10.4 states this, and separately notes that "
            "shadow banking is incompletely captured, which pulls the other way."
        ),
        source="Capital Saturation section 10.4",
        prior_range=(0.80, 1.20),
    ),
    "saturation": SeriesAdjustment(
        level_scale=1.0,
        rationale=(
            "the credit saturation axis inherits the output bias in its denominator, so an output "
            "adjustment implies a reciprocal adjustment here"
        ),
        source="implied by the Y adjustment; Capital Saturation section 10.6",
        prior_range=(1.00, 1.25),
    ),
}


def apply(series: Series, adjustment: SeriesAdjustment) -> Series:
    """Apply a level adjustment to a series, recording it.

    An adjusted series is marked `DERIVED`, so `integrity.check_model_inputs` refuses it unless the
    caller has explicitly opted into derived inputs. That is deliberate: an adjustment is a computation
    on published data, and opting into it should be a visible decision at the call site.

    Args:
        series: The series to adjust.
        adjustment: The adjustment.

    Returns:
        The adjusted series, or the original unchanged if the adjustment is the identity.
    """
    if adjustment.is_identity:
        return series

    values = series.values.astype(float)
    adjusted = values * adjustment.level_scale

    detail = (
        f"level scale {adjustment.level_scale:g}. "
        f"Rationale: {adjustment.rationale} Source: {adjustment.source}. "
        f"Dynamics-neutral by construction: level scaling is the only adjustment this programme offers, "
        f"so growth rates, direction and turning points are unchanged."
    )

    return series.transformed(
        pd.Series(adjusted, index=values.index, name=series.name),
        "standardising_adjustment",
        detail,
        reliability=Reliability.DERIVED,
        notes=series.provenance.notes
        + (
            "a standardising adjustment has been applied; the level of this series is not the published "
            "level and any output using it must say so",
        ),
    )


def apply_priors(
    series: Iterable[Series],
    overrides: Mapping[str, SeriesAdjustment] | None = None,
) -> tuple[list[Series], dict[str, SeriesAdjustment]]:
    """Apply the configured adjustment to each series by quantity name.

    Defaults to the identity for every quantity, so calling this changes nothing unless an override is
    supplied. That is the point: the priors document what *could* be adjusted and by how much, and the
    sensitivity run explores them, but nothing is quietly corrected.

    Args:
        series: The series to adjust.
        overrides: Adjustments by quantity name, overriding the priors.

    Returns:
        The adjusted series and the adjustment actually applied to each, for the manifest.
    """
    chosen = dict(overrides or {})
    adjusted: list[Series] = []
    applied: dict[str, SeriesAdjustment] = {}

    for item in series:
        adjustment = chosen.get(item.name, SeriesAdjustment())
        adjusted.append(apply(item, adjustment))
        applied[item.name] = adjustment
    return adjusted, applied


def prior_range_for(quantity: str) -> tuple[float, float]:
    """Return the documented level-scale prior range for a quantity.

    Raises:
        AdjustmentError: If no prior is documented, since inventing a range at the point of use is how an
            undocumented number enters the sensitivity analysis and then the conclusions.
    """
    prior = ADJUSTMENT_PRIORS.get(quantity)
    if prior is None or prior.prior_range is None:
        raise AdjustmentError(
            f"no adjustment prior is documented for {quantity!r}. Add one to ADJUSTMENT_PRIORS with its "
            f"source rather than choosing a range at the point of use."
        )
    return prior.prior_range


def standardise(
    series: Series,
    reference_period: Any | None = None,
    reference_value: float = 100.0,
) -> Series:
    """Rebase a series to an index, for comparing indicators of different units side by side.

    Purely presentational and, like the level scale, dynamics-neutral: an index rebasing is a
    multiplicative constant, so growth rates, direction and turning points are all unchanged. Use it to
    put output, capital and credit on one chart without one of them flattening the others.

    Args:
        series: The series to rebase.
        reference_period: The period set to `reference_value`. Defaults to the first observed period.
        reference_value: The index value at the reference period.

    Returns:
        The rebased series.

    Raises:
        AdjustmentError: If the reference period is absent or its value is zero.
    """
    observed = series.values.dropna()
    if observed.empty:
        raise AdjustmentError(f"{series.name!r} has no observations to rebase")

    period = reference_period if reference_period is not None else observed.index[0]
    if period not in observed.index:
        raise AdjustmentError(
            f"reference period {period!r} is not observed in {series.name!r}, which covers "
            f"{observed.index[0]} to {observed.index[-1]}"
        )
    base = float(observed.loc[period])
    if base == 0.0:
        raise AdjustmentError(f"{series.name!r} is zero at {period!r}, so it cannot be rebased on it")

    factor = reference_value / base
    return series.transformed(
        series.values.astype(float) * factor,
        "rebase_index",
        f"rebased to {reference_value:g} at {period}. Presentational and dynamics-neutral: an index "
        f"rebasing is a multiplicative constant, so growth rates, direction and turning points are "
        f"unchanged.",
        units=f"index, {period} = {reference_value:g}",
    )


@dataclass
class AdjustmentSensitivity:
    """How a conclusion moves as a level adjustment is varied across its documented prior.

    Attributes:
        quantity: The series varied.
        scales: The level scales applied.
        values: The resulting value of the quantity of interest at each scale.
        label: What the value represents.
        dynamics_unchanged: Whether the dynamic criteria were unaffected, which for a pure level
            adjustment they must be.
        verdict: What the spread means.
    """

    quantity: str
    scales: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    label: str = ""
    dynamics_unchanged: bool = True
    verdict: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "level_scales": self.scales,
            "values": self.values,
            "value_label": self.label,
            "dynamics_unchanged": self.dynamics_unchanged,
            "verdict": self.verdict,
        }


def sweep_level_adjustment(
    quantity: str,
    evaluate: Any,
    steps: int = 5,
    prior_range: tuple[float, float] | None = None,
    label: str = "",
) -> AdjustmentSensitivity:
    """Vary a level adjustment across its documented prior and report how a conclusion moves.

    This is the honest way to use the adjustment machinery. Rather than picking a scale and presenting
    one number, the prior range is swept and the *spread* of the conclusion is reported. Where the
    conclusion is stable across the range it is robust to the measurement problem; where it is not, the
    measurement problem is the binding constraint and should be stated as such.

    Args:
        quantity: The series being varied, used to look up the prior.
        evaluate: A callable taking a level scale and returning the conclusion of interest as a float,
            for example a saturation ratio or a turning-point hit rate.
        steps: How many scales to try across the range.
        prior_range: Overrides the documented prior.
        label: What the returned value represents.

    Returns:
        The sensitivity result.
    """
    low, high = prior_range or prior_range_for(quantity)
    if steps < 2:
        raise AdjustmentError(f"a sweep needs at least two steps, got {steps}")

    scales = [float(s) for s in np.linspace(low, high, steps)]
    values = [float(evaluate(scale)) for scale in scales]

    finite = [v for v in values if np.isfinite(v)]
    spread = (max(finite) - min(finite)) if finite else float("nan")
    midpoint = float(np.mean(finite)) if finite else float("nan")
    relative = abs(spread / midpoint) if finite and midpoint != 0.0 else float("nan")

    if not finite:
        verdict = "no scale produced a usable value, so robustness cannot be assessed"
    elif np.isfinite(relative) and relative < 0.10:
        verdict = (
            f"the conclusion varies by {spread:.4g} ({relative:.0%}) across the documented prior, so it "
            f"is robust to the measurement problem in {quantity}"
        )
    else:
        verdict = (
            f"the conclusion varies by {spread:.4g} ({relative:.0%}) across the documented prior, so the "
            f"definitional uncertainty in {quantity} is the binding constraint and the value should be "
            f"quoted as a range rather than a point"
        )

    return AdjustmentSensitivity(
        quantity=quantity,
        scales=scales,
        values=values,
        label=label,
        dynamics_unchanged=True,
        verdict=verdict,
    )
