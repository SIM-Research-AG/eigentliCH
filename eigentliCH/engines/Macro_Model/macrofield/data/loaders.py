"""Assembling the model quantities from published series.

Brief section 2 maps each model quantity to published data. This module performs the assembly, and it
is where the decisions that shape every downstream diagnostic are made explicit:

- **K_I**, financial capital. Book chapter 10.4 defines it as the consolidated gross financial-asset
  stock and states it runs 400 to 600 percent of GDP for major advanced economies. That measure is
  primary, taken from national financial balance sheets. Where it is not published, the fallback is
  BIS total credit to the non-financial sector plus listed equity market capitalisation. Debt
  securities outstanding are excluded from the fallback because non-financial issuance already sits
  inside BIS total credit, and adding both double counts. Which measure was used is recorded per
  economy and per year and must appear on any output that uses it.

- **K_R**, real capital. Published capital stock (IMF investment and capital stock, Penn World Table)
  ends several years short of the present. It is carried forward by perpetual inventory from published
  gross fixed capital formation, marked `DERIVED`, with the depreciation rate and the first extended
  year recorded. This is a documented computation, never a silent interpolation, and the integrity
  check refuses it unless the caller opts in.

- **Saturation axis**. BIS publishes total credit as a percentage of GDP. The division by 100 that
  turns it into the ratio the phase classifier expects is performed here and logged, not applied
  silently at the point of use.

Nothing in this module fills a gap. Gaps arrive as gaps, are reported, and either the window is
narrowed or the run fails, per brief section 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from macrofield.data.integrity import IntegrityReport, check_consistency
from macrofield.data.provenance import (
    Basis,
    Frequency,
    ProvenanceRecord,
    Reliability,
    Series,
    align,
)


class LoaderError(ValueError):
    """Raised when the model quantities cannot be assembled as configured."""


#: The measures K_I can be assembled from, in preference order.
FINANCIAL_CAPITAL_MEASURES = ("consolidated_financial_assets", "credit_plus_listed_equity")


@dataclass
class AssembledQuantity:
    """A model quantity and how it was put together.

    Attributes:
        series: The assembled series.
        measure: Which configured measure produced it.
        components: The component series that went into it, for the manifest.
        notes: Anything a reader must know, for example that a fallback was used.
    """

    series: Series
    measure: str
    components: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def to_ratio_of_gdp(percentage_series: Series, name: str) -> Series:
    """Convert a published percentage-of-GDP series into a ratio.

    BIS publishes total credit as a percentage. The phase classifier expects a ratio, and a factor of
    100 in the wrong place moves an economy from Phase 1 to Phase 4, so the conversion is logged.
    """
    if percentage_series.provenance.basis is not Basis.UNITLESS:
        raise LoaderError(
            f"{percentage_series.name!r} is {percentage_series.provenance.basis.value}, but a "
            f"percentage-of-GDP series must be unitless"
        )
    converted = percentage_series.scaled(
        0.01,
        "converted from percent of GDP to a ratio of GDP",
        units="ratio of GDP",
    )
    return converted.rename(name)


def resolve_depreciation_rate(
    published: Series | None,
    configured: float,
    period: int,
) -> tuple[float, str]:
    """Return the depreciation rate to use for one period, preferring the published value.

    Penn World Table publishes `delta` per country and per year, which is strictly better than a
    configured prior: it is the rate the source itself used to build the stock being extended, so using
    it keeps the extension on the same basis as the published values it continues.

    Where the published series has no value for the period, the last published value is carried forward
    in preference to the configured prior, because the source's own rate for a neighbouring year is
    closer to the truth than a hand-set constant. The configured prior is the last resort.

    Args:
        published: The published depreciation-rate series, or None if unavailable.
        configured: The configured prior, used only as a fallback.
        period: The period the rate is needed for.

    Returns:
        The rate and a short description of where it came from, for the transformation log.
    """
    if published is not None:
        observed = published.values.dropna()
        if not observed.empty:
            if period in observed.index:
                return float(observed.loc[period]), f"published rate for {period}"
            earlier = observed[observed.index <= period]
            if not earlier.empty:
                last_period = int(earlier.index[-1])
                return (
                    float(earlier.iloc[-1]),
                    f"last published rate, from {last_period}, carried forward to {period}",
                )
    return float(configured), "configured prior, no published rate available"


def extend_capital_stock_by_perpetual_inventory(
    capital_stock: Series,
    investment: Series,
    depreciation_rate: float,
    through_period: int | None = None,
    published_depreciation: Series | None = None,
) -> Series:
    """Carry a capital stock forward from published investment flows.

    The perpetual inventory recursion is

        K(t) = (1 - delta) K(t-1) + I(t)

    applied from the last published capital-stock observation forward, using published gross fixed
    capital formation for I and a documented depreciation rate for delta. This is the standard method
    national statistical agencies use to construct these stocks in the first place, which is why it is
    a defensible extension rather than an invention. It is nonetheless a computation by this programme,
    so the result is marked `DERIVED`, the transformation records the rate and the extended range, and
    the integrity check will refuse it unless the caller opts in.

    Args:
        capital_stock: The published stock, in the same currency and basis as the investment series.
        investment: Published gross fixed capital formation.
        depreciation_rate: Annual depreciation rate, delta. Used only where no published rate is
            supplied or where the published series does not reach the period.
        through_period: Last period to extend to. Defaults to the last investment observation.
        published_depreciation: The source's own depreciation-rate series, preferred over the
            configured rate. Penn World Table publishes this as `delta`, per country and per year.

    Returns:
        The stock, extended.

    Raises:
        LoaderError: If the two series disagree on currency or basis, if the depreciation rate is not a
            proper fraction, or if the investment series does not cover the extension range without
            gaps. An extension across a gap in investment would be an interpolation in disguise.
    """
    if not 0.0 < depreciation_rate < 1.0:
        raise LoaderError(
            f"the depreciation rate must lie strictly between zero and one, got {depreciation_rate}"
        )

    consistency = check_consistency([capital_stock, investment])
    if not consistency.ok:
        raise LoaderError(
            "the capital stock and the investment series are not consistent, so the perpetual "
            f"inventory extension cannot proceed: {[str(f) for f in consistency.failures]}"
        )

    stock = capital_stock.values.dropna()
    flows = investment.values.dropna()
    if stock.empty:
        raise LoaderError(f"{capital_stock.name!r} has no observations to extend from")
    if flows.empty:
        raise LoaderError(f"{investment.name!r} has no observations to extend with")

    last_published = int(stock.index[-1])
    target = int(through_period if through_period is not None else flows.index[-1])

    if target <= last_published:
        return capital_stock

    needed = list(range(last_published + 1, target + 1))
    missing = [year for year in needed if year not in flows.index]
    if missing:
        raise LoaderError(
            f"cannot extend {capital_stock.name!r} to {target}: gross fixed capital formation is "
            f"missing for {missing}. Extending across a gap would interpolate, which the brief "
            f"forbids. Narrow the target period to {min(missing) - 1} or supply the missing flows."
        )

    extended = stock.copy()
    level = float(stock.iloc[-1])
    rates_used: list[str] = []
    for year in needed:
        rate, origin = resolve_depreciation_rate(published_depreciation, depreciation_rate, year)
        if not 0.0 < rate < 1.0:
            raise LoaderError(
                f"the depreciation rate for {year} resolved to {rate} ({origin}), which is not a "
                f"proper fraction"
            )
        level = (1.0 - rate) * level + float(flows.loc[year])
        extended.loc[year] = level
        rates_used.append(f"{year}: {rate:.4f} ({origin})")
    extended = extended.sort_index()

    detail = (
        f"extended from {last_published} to {target} by perpetual inventory, "
        f"K(t) = (1 - delta) K(t-1) + I(t), using {investment.provenance.source} "
        f"{investment.provenance.identifier} for gross fixed capital formation. "
        f"Depreciation rates applied: {'; '.join(rates_used)}"
    )
    return capital_stock.transformed(
        extended,
        "perpetual_inventory_extension",
        detail,
        reliability=Reliability.DERIVED,
        notes=capital_stock.provenance.notes
        + (
            f"values for {last_published + 1} to {target} are computed, not published. Any output "
            f"using them must carry the extension label.",
        ),
    )


def extend_capital_ratio_by_perpetual_inventory(
    capital_ratio: Series,
    investment_share: Series,
    output_growth: Series,
    depreciation_rate: float,
    through_period: int | None = None,
    published_depreciation: Series | None = None,
) -> Series:
    """Extend the capital-to-output ratio forward, working entirely in unitless quantities.

    This is the preferred extension route, and the reason is a valuation problem that the
    currency-level recursion cannot escape.

    Penn World Table ends in 2019 across every column, including its own investment share, so it cannot
    extend itself. Extending it therefore needs an external investment series, and the obvious candidate
    (World Bank gross fixed capital formation) is converted at market exchange rates while Penn World
    Table is converted at purchasing-power parities. Combining them produces a meaningless number that
    `integrity.check_consistency` correctly refuses, and forcing it through would require a PPP
    conversion factor with its own vintage and its own price base, adding two more places to be wrong.

    Working in ratio space removes the problem rather than managing it. Dividing the recursion
    `K(t) = (1 - delta) K(t-1) + I(t)` through by output gives

        k(t) = (1 - delta) k(t-1) / (1 + g(t)) + i(t)

    where `k = K_R / Y`, `i = I / Y` and `g` is the growth rate of output. Every input is unitless, so
    the PPP against market-rate distinction cannot arise, and the published ratio and the extension are
    on the same footing by construction. The ratio is also what the phase classifier and HoNI actually
    consume, so nothing is lost by never reconstructing a level.

    Args:
        capital_ratio: The published capital-to-output ratio, K_R / Y.
        investment_share: Investment as a share of output, I / Y. Must be unitless.
        output_growth: The growth rate of output, as a fraction. Must be unitless.
        depreciation_rate: Fallback annual depreciation rate.
        through_period: Last period to extend to. Defaults to the last period covered by both the
            investment share and the growth rate.
        published_depreciation: The source's own depreciation-rate series, preferred over the fallback.

    Returns:
        The extended ratio, marked derived, with every applied rate recorded.

    Raises:
        LoaderError: If any input is not unitless, if a required period is missing, or if a growth rate
            would make the recursion undefined.
    """
    for label, candidate in (
        ("capital_ratio", capital_ratio),
        ("investment_share", investment_share),
        ("output_growth", output_growth),
    ):
        if candidate.provenance.basis is not Basis.UNITLESS:
            raise LoaderError(
                f"{label} must be unitless to extend in ratio space, but {candidate.name!r} is "
                f"{candidate.provenance.basis.value}. Convert it to a share or a growth rate first, "
                f"which is what makes this route immune to the PPP against market-rate problem."
            )

    ratio = capital_ratio.values.dropna()
    shares = investment_share.values.dropna()
    growth = output_growth.values.dropna()
    if ratio.empty:
        raise LoaderError(f"{capital_ratio.name!r} has no observations to extend from")

    last_published = int(ratio.index[-1])
    available = sorted(set(shares.index).intersection(growth.index))
    if not available:
        raise LoaderError(
            "the investment share and the output growth rate share no periods, so the ratio cannot be "
            "extended"
        )
    target = int(through_period if through_period is not None else max(available))

    if target <= last_published:
        return capital_ratio

    needed = list(range(last_published + 1, target + 1))
    missing = [year for year in needed if year not in shares.index or year not in growth.index]
    if missing:
        raise LoaderError(
            f"cannot extend {capital_ratio.name!r} to {target}: the investment share or the output "
            f"growth rate is missing for {missing}. Extending across a gap would interpolate, which the "
            f"brief forbids. Narrow the target to {min(missing) - 1}."
        )

    extended = ratio.copy()
    level = float(ratio.iloc[-1])
    applied: list[str] = []
    for year in needed:
        rate, origin = resolve_depreciation_rate(published_depreciation, depreciation_rate, year)
        if not 0.0 < rate < 1.0:
            raise LoaderError(
                f"the depreciation rate for {year} resolved to {rate} ({origin}), which is not a "
                f"proper fraction"
            )
        g = float(growth.loc[year])
        if g <= -1.0:
            raise LoaderError(
                f"output growth for {year} is {g}, which implies output at or below zero and makes the "
                f"ratio recursion undefined"
            )
        level = (1.0 - rate) * level / (1.0 + g) + float(shares.loc[year])
        extended.loc[year] = level
        applied.append(f"{year}: delta={rate:.4f} ({origin}), g={g:+.4f}, i={float(shares.loc[year]):.4f}")
    extended = extended.sort_index()

    detail = (
        f"extended from {last_published} to {target} in ratio space, "
        f"k(t) = (1 - delta) k(t-1) / (1 + g(t)) + i(t), using "
        f"{investment_share.provenance.source} {investment_share.provenance.identifier} for the "
        f"investment share and {output_growth.provenance.source} "
        f"{output_growth.provenance.identifier} for output growth. All inputs unitless, so no currency "
        f"or valuation conversion is involved. Steps: {'; '.join(applied)}"
    )
    return capital_ratio.transformed(
        extended,
        "perpetual_inventory_ratio_extension",
        detail,
        reliability=Reliability.DERIVED,
        notes=capital_ratio.provenance.notes
        + (
            f"values for {last_published + 1} to {target} are computed, not published. Any output "
            f"using them must carry the extension label.",
        ),
    )


def assemble_financial_capital(
    consolidated_assets: Series | None,
    total_credit: Series | None,
    listed_equity: Series | None,
    primary_measure: str = "consolidated_financial_assets",
    fallback_measure: str = "credit_plus_listed_equity",
) -> AssembledQuantity:
    """Assemble K_I, preferring the chapter 10.4 measure and falling back where it is unpublished.

    Args:
        consolidated_assets: The consolidated gross financial-asset stock, or None if unpublished.
        total_credit: BIS total credit to the non-financial sector, in currency units.
        listed_equity: Listed equity market capitalisation, in currency units.
        primary_measure: The preferred measure name.
        fallback_measure: The fallback measure name.

    Returns:
        The assembled quantity, recording which measure was used.

    Raises:
        LoaderError: If neither measure can be assembled, or if the fallback components are
            inconsistent in currency, basis or frequency.
    """
    if primary_measure not in FINANCIAL_CAPITAL_MEASURES:
        raise LoaderError(
            f"unknown primary measure {primary_measure!r}, expected one of {FINANCIAL_CAPITAL_MEASURES}"
        )

    if consolidated_assets is not None and primary_measure == "consolidated_financial_assets":
        series = consolidated_assets.rename("K_I")
        return AssembledQuantity(
            series=series,
            measure="consolidated_financial_assets",
            components=[consolidated_assets.provenance.identifier],
            notes=[
                "K_I is the consolidated gross financial-asset stock, per book chapter 10.4, which "
                "states this runs 400 to 600 percent of GDP for major advanced economies"
            ],
        )

    if total_credit is None or listed_equity is None:
        missing = [
            label
            for label, value in (
                ("consolidated financial assets", consolidated_assets),
                ("BIS total credit", total_credit),
                ("listed equity market capitalisation", listed_equity),
            )
            if value is None
        ]
        raise LoaderError(
            f"K_I cannot be assembled: {', '.join(missing)} unavailable. The brief requires a run that "
            f"needs an unavailable input to fail rather than guess."
        )

    consistency = check_consistency([total_credit, listed_equity])
    if not consistency.ok:
        raise LoaderError(
            "the fallback components of K_I are not consistent: "
            f"{[str(f) for f in consistency.failures]}"
        )

    aligned = align([total_credit, listed_equity], how="inner")
    combined = aligned[total_credit.name] + aligned[listed_equity.name]

    provenance = ProvenanceRecord(
        source=f"{total_credit.provenance.source} and {listed_equity.provenance.source}",
        dataset="composite: total credit to the non-financial sector plus listed equity market capitalisation",
        identifier=f"{total_credit.provenance.identifier} + {listed_equity.provenance.identifier}",
        url=total_credit.provenance.url,
        retrieved_on=max(
            total_credit.provenance.retrieved_on, listed_equity.provenance.retrieved_on
        ),
        units=total_credit.provenance.units,
        basis=total_credit.provenance.basis,
        frequency=total_credit.provenance.frequency,
        currency=total_credit.provenance.currency,
        # Inherited from the components, which check_consistency above has already established agree.
        valuation=total_credit.provenance.valuation,
        reliability=Reliability.DERIVED,
        licence=f"{total_credit.provenance.licence}; {listed_equity.provenance.licence}",
        notes=(
            "fallback measure, used because the consolidated financial-asset stock of book chapter "
            "10.4 is not published for this economy",
            "debt securities outstanding are deliberately excluded: non-financial issuance already "
            "sits inside BIS total credit to the non-financial sector, so including both double counts",
            f"aligned on the {len(combined)} periods common to both components",
        ),
        transformations=(),
    )
    series = Series(name="K_I", values=combined.rename("K_I"), provenance=provenance)
    return AssembledQuantity(
        series=series,
        measure=fallback_measure,
        components=[
            total_credit.provenance.identifier,
            listed_equity.provenance.identifier,
        ],
        notes=[
            "K_I uses the fallback measure, which is narrower than the chapter 10.4 definition and "
            "will not reproduce its 400 to 600 percent range. Comparisons against economies using the "
            "primary measure are not like for like.",
        ],
    )


@dataclass
class EconomyData:
    """Every series one economy's calibration needs, assembled and checked.

    Attributes:
        economy: The economy code.
        output: Y.
        real_capital: K_R.
        financial_capital: K_I.
        savings_rate: p_s.
        stimulus: S.
        saturation: The saturation axis, total credit over GDP as a ratio.
        auxiliary: Anything else the modules need, for example the gold price or population.
        financial_capital_measure: Which K_I measure was used.
        window: The (first, last) period common to the required series.
        integrity: The integrity report for the required series.
        notes: Assembly notes that must reach the output.
    """

    economy: str
    output: Series
    real_capital: Series
    financial_capital: Series
    savings_rate: Series
    stimulus: Series
    saturation: Series
    auxiliary: dict[str, Series] = field(default_factory=dict)
    financial_capital_measure: str = "consolidated_financial_assets"
    window: tuple[int, int] = (0, 0)
    integrity: IntegrityReport = field(default_factory=IntegrityReport)
    notes: list[str] = field(default_factory=list)

    @property
    def required(self) -> list[Series]:
        """The series the equations of motion need."""
        return [
            self.output,
            self.real_capital,
            self.financial_capital,
            self.savings_rate,
            self.stimulus,
        ]

    def aligned_frame(self) -> pd.DataFrame:
        """Return the required series plus the saturation axis on their common period index.

        An inner join, so no period is present unless every quantity is observed there. That is what
        keeps an implicit fill out of the calibration input.
        """
        series = self.required + [self.saturation]
        aligned = align(series, how="inner")
        frame = pd.DataFrame(aligned)
        if frame.empty:
            coverage = {
                s.name: f"{s.first_period} to {s.last_period}" for s in series
            }
            raise LoaderError(
                f"the required series for {self.economy!r} share no common periods. Coverage: "
                f"{coverage}. Narrow the configured calibration window or choose different series."
            )
        return frame

    def summary(self) -> dict[str, Any]:
        """A short description for the calibration report."""
        return {
            "economy": self.economy,
            "window": {"first": self.window[0], "last": self.window[1]},
            "financial_capital_measure": self.financial_capital_measure,
            "series": {
                s.name: {
                    "source": s.provenance.source,
                    "identifier": s.provenance.identifier,
                    "reliability": s.provenance.reliability.value,
                    "coverage": f"{s.first_period} to {s.last_period}",
                    "gaps": s.gap_report().as_dict()["missing_count"],
                }
                for s in self.required + [self.saturation]
            },
            "integrity": self.integrity.as_dict(),
            "notes": list(self.notes),
        }


def determine_window(
    series: Sequence[Series],
    configured_start: int | None = None,
    configured_end: int | None = None,
) -> tuple[int, int]:
    """Return the calibration window: the overlap of the series, narrowed by any configured bounds.

    Raises:
        LoaderError: If the series do not overlap, or if the configured window falls outside the
            overlap. Both cases must fail rather than silently returning a shorter window than asked
            for, because a calibration reported against the requested window that actually used a
            different one is misleading.
    """
    if not series:
        raise LoaderError("no series were supplied")

    firsts, lasts = [], []
    for item in series:
        observed = item.values.dropna()
        if observed.empty:
            raise LoaderError(f"{item.name!r} has no observations")
        firsts.append(int(observed.index[0]))
        lasts.append(int(observed.index[-1]))

    start, end = max(firsts), min(lasts)
    if start > end:
        coverage = {s.name: f"{s.first_period} to {s.last_period}" for s in series}
        raise LoaderError(f"the series do not overlap. Coverage: {coverage}")

    if configured_start is not None:
        if configured_start > end:
            raise LoaderError(
                f"the configured window starts at {configured_start}, after the data ends at {end}"
            )
        if configured_start < start:
            raise LoaderError(
                f"the configured window starts at {configured_start}, before the data begins at "
                f"{start}. Adjust the configuration rather than silently starting later."
            )
        start = configured_start

    if configured_end is not None:
        if configured_end < start:
            raise LoaderError(
                f"the configured window ends at {configured_end}, before the data begins at {start}"
            )
        if configured_end > end:
            raise LoaderError(
                f"the configured window ends at {configured_end}, after the data ends at {end}. "
                f"Adjust the configuration rather than silently stopping earlier."
            )
        end = configured_end

    return start, end


def numeric_derivative(
    values: np.ndarray,
    periods: np.ndarray,
    method: str = "savitzky_golay",
    window_years: int = 5,
    polynomial_order: int = 2,
    order: int = 1,
) -> np.ndarray:
    """Return a smoothed numerical derivative of an observed series.

    Brief section 3 requires a documented numerical derivative with smoothing wherever a definition uses
    the time derivative of an observed series, and requires the smoothing choice to be exposed. It
    matters more than it appears: `p_p`, `p_b` and `alpha` are all defined through derivatives, so the
    smoothing choice propagates into every one of them and hence into the whole calibration.

    Args:
        values: The observed series.
        periods: The period labels, used for the spacing.
        method: `savitzky_golay` (the default, which fits a local polynomial and differentiates it,
            giving a smooth derivative without the phase shift a moving average introduces) or
            `central_difference` (unsmoothed, for comparison).
        window_years: Width of the smoothing window. Coerced to an odd number of observations.
        polynomial_order: Order of the local polynomial.
        order: Which derivative to take. `1` is the default. `2` is needed by the gold module, whose
            first driver is the acceleration of financial capital. Under `savitzky_golay` the derivative
            is taken from the fitted local polynomial directly rather than by calling this function on
            its own output, so the local polynomial must be of at least this order.

            The reason to prefer it is attenuation, not noise. Differentiating twice applies the
            smoothing filter twice, and a filter that preserves a constant curvature exactly still
            damps a *varying* one. On an 18-year cycle, the credit cycle's own prior, a five-year window
            recovers about 77 per cent of the true curvature amplitude taken directly and about 46 per
            cent taken twice. A varying curvature is precisely what the credit impulse is, so the
            attenuation would fall on the signal the driver is meant to carry. On a constant curvature
            the double route is in fact the more accurate of the two, because there the extra smoothing
            costs no bias; that is not the case this is used for.

    Returns:
        The derivative at each period.

    Raises:
        LoaderError: If the inputs disagree in length, the sample is too short for the window, the
            method is unknown, or the polynomial is too low an order for the derivative requested.
    """
    series = np.asarray(values, dtype=float)
    times = np.asarray(periods, dtype=float)
    if series.shape != times.shape:
        raise LoaderError(f"values and periods must share a shape, got {series.shape} and {times.shape}")
    if series.size < 3:
        raise LoaderError(f"a derivative needs at least three observations, got {series.size}")
    if np.any(~np.isfinite(series)):
        raise LoaderError(
            "cannot differentiate a series containing gaps. Resolve them in the data layer, where they "
            "are reported, rather than differentiating across them."
        )

    if int(order) < 1:
        raise LoaderError(f"order must be at least one, got {order}")
    order = int(order)

    if method == "central_difference":
        result = series
        for _ in range(order):
            result = np.gradient(result, times)
        return result

    if method != "savitzky_golay":
        raise LoaderError(f"unknown derivative method {method!r}")

    from scipy.signal import savgol_filter

    if polynomial_order < order:
        raise LoaderError(
            f"a derivative of order {order} needs a local polynomial of at least that order, but the "
            f"polynomial order is {polynomial_order}. A lower-order polynomial has a zero {order}th "
            f"derivative everywhere, so the result would be identically zero rather than wrong-looking."
        )

    window = int(window_years)
    if window % 2 == 0:
        window += 1
    window = min(window, series.size if series.size % 2 == 1 else series.size - 1)
    if window <= polynomial_order:
        raise LoaderError(
            f"the smoothing window of {window} observations is too small for a polynomial of order "
            f"{polynomial_order}. Shorten the polynomial or lengthen the sample."
        )

    spacing = float(np.median(np.diff(times)))
    if spacing <= 0.0:
        raise LoaderError("periods must increase")
    return savgol_filter(
        series, window_length=window, polyorder=polynomial_order, deriv=order, delta=spacing
    )
