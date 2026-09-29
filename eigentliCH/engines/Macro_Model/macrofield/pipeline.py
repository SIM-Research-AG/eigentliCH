"""Assembling one economy from the data layer into a calibratable path.

This is the keystone between `macrofield.data` and `macrofield.calibration`. Everything either side of it
was buildable and testable in isolation; this module is where the valuation, coverage and integrity
decisions have to be made concrete for a real economy.

**The valuation strategy, which determines everything else.**

The sources do not share a basis. World Bank dollar series are at market exchange rates, Penn World Table
is at purchasing-power parities, and BIS publishes ratios. Combining them naively produces numbers that
pass the currency and basis checks and mean nothing, which is what `provenance.Valuation` exists to catch.

The resolution is to take **one level series and express everything else as a ratio to it**. Nominal GDP
at market exchange rates is the level; real capital arrives as the PWT ratio `cn/cgdpo`, which is unitless
and therefore basis-free, and is multiplied by that level; credit arrives as a BIS ratio and is treated
the same way. Every assembled quantity is then market-valued by construction, and no PPP conversion factor
with its own vintage enters anywhere.

The cost is that `K_R` is a market-valued reconstruction rather than a published level. That is recorded on
the series and it is why the assembled path is marked derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from macrofield import config as config_module
from macrofield.calibration.fit import ObservedPath
from macrofield.data.adjustment import SeriesAdjustment, apply
from macrofield.data.integrity import IntegrityReport, check_consistency, check_model_inputs
from macrofield.data.loaders import (
    LoaderError,
    determine_window,
    extend_capital_ratio_by_perpetual_inventory,
    to_ratio_of_gdp,
)
from macrofield.data.manifest import Cache, Manifest
from macrofield.data.plausibility import check_plausibility
from macrofield.data.provenance import Basis, Reliability, Series, Valuation, align
from macrofield.data.sources import SourceError, SourceSet

#: World Bank indicator codes used by the pipeline. Held here rather than read from config because these
#: are the pipeline's own choices about which series realise which quantity, and config holds the
#: per-economy overrides.
WORLD_BANK = {
    "output": "NY.GDP.MKTP.CD",
    "investment_share": "NE.GDI.FTOT.ZS",
    "output_growth": "NY.GDP.MKTP.KD.ZG",
    "savings_rate": "NY.GNS.ICTR.ZS",
    "equity_market_cap": "CM.MKT.LCAP.CD",
    "fiscal_balance": "GC.NLD.TOTL.GD.ZS",
    "consumer_prices": "FP.CPI.TOTL",
}


#: Target ceiling for K_R / Y across the whole calibration window, used to set the common capital scale.
#:
#: Section 0.2 calls r = 1 - K_R/Y the investment share, the fraction of financial capital directed into
#: real capital. It is only a share if K_R/Y stays below one. On the chapter 10 proxies it does not: the
#: United States reads K_R/Y of 3.27, so r is -2.27, and multiplied by K_I of 4.61 Y the exchange term
#: r K_I reaches -10.5 Y, which is real capital collapsing at ten times output per year.
#:
#: **Why the ceiling is applied to the maximum over the window rather than to the first period.**
#:
#: Substituting the alpha definition of section 0.2 into the output equation makes the p_p K_R terms cancel
#: exactly and leaves
#:
#:     Y_dot = (p_b Y + r K_I + S) / 2
#:
#: so the sign of r decides whether output grows at all. Normalising on the first period alone let the
#: ratio rise past one later in the window, which flips r negative and drives output towards zero until its
#: logarithm is undefined. That is precisely what happened to Germany and the United Kingdom, whose ratios
#: cross one mid-window, while the United States and India, whose do not, integrated fine.
#:
#: Scaling on the maximum guarantees r stays positive for every period, which is what the definition
#: requires. The economy can still approach the production-versus-financial boundary of section 0.5, it
#: simply cannot cross it inside the calibration window, and that limitation is stated in the notes rather
#: than hidden.
DEFAULT_CAPITAL_TARGET = 0.9


class PipelineError(RuntimeError):
    """Raised when an economy cannot be assembled."""


@dataclass(frozen=True)
class CapitalNormalisation:
    """A common multiplicative scale applied to both capital stocks.

    This is the adjustment that makes the equations of motion usable on published data, and it works
    because of two properties that have to hold together.

    **It also harmonises Penn World Table capital across economies, which it has to.** PWT's cross-country
    capital *levels* are not trustworthy: it reports the United States with the lowest capital-to-output
    ratio of any advanced economy in the panel at 3.36, below the United Kingdom at 4.72, Germany at 4.59,
    Japan at 4.75 and France at 5.66. That ordering is not credible, and its cause is visible in the same
    data, where PWT's PPP output differs from market-rate output by a factor ranging from 0.67 for the
    United States to 2.31 for India. Because every economy is scaled to the same target, the resulting
    K_R/Y levels are comparable by construction.

    That trade is deliberate and it should be understood as declining to use information rather than
    discarding it: any genuine cross-country difference in capital intensity is given up, because the source
    does not measure it reliably, while each economy's own time path, which the source does measure usably,
    is preserved exactly. A reader must therefore not read a cross-country K_R/Y comparison as a finding.

    **It is dynamics-neutral.** A multiplicative constant cannot change a growth rate, a direction, or a
    turning point, for the reason set out in `macrofield.data.adjustment`. So it cannot manufacture or
    destroy any of the results the model is judged on.

    **It preserves K_R / K_I.** The same scale is applied to both capital stocks, so their ratio is
    untouched. That matters because the Phase 4 condition is `K_R/K_I < 1`, which is the scale-invariant
    part of the phase classifier and the reading that places the United States in Phase 4. A normalisation
    that scaled only real capital would move that ratio and would be changing the answer rather than
    making the equations solvable.

    What it does change is `K/Y`, and therefore `r`. That is the entire point: it brings the investment
    share back into the range in which section 0.2's definition of it is meaningful.

    Attributes:
        scale: The common factor applied to K_R and K_I.
        target: The K_R/Y value at the window start that the scale was chosen to produce.
        observed_ratio: The published K_R/Y at the window start, before scaling.
        rationale: Why the normalisation is applied.
    """

    scale: float
    target: float
    observed_ratio: float
    rationale: str

    @property
    def is_identity(self) -> bool:
        return self.scale == 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "target_capital_output_ratio": self.target,
            "observed_capital_output_ratio": self.observed_ratio,
            "preserves_real_to_financial_ratio": True,
            "dynamics_neutral": True,
            "rationale": self.rationale,
        }


def capital_normalisation(
    real_capital_ratio: float, target: float = DEFAULT_CAPITAL_TARGET
) -> CapitalNormalisation:
    """Return the common capital scale that puts K_R/Y at the target.

    Raises:
        PipelineError: If the observed ratio is not positive, since no scale then exists.
    """
    if real_capital_ratio <= 0.0:
        raise PipelineError(
            f"the observed capital-to-output ratio is {real_capital_ratio}, so no normalising scale "
            f"exists"
        )
    if target <= 0.0:
        raise PipelineError(f"the normalisation target must be positive, got {target}")

    scale = target / real_capital_ratio
    return CapitalNormalisation(
        scale=scale,
        target=target,
        observed_ratio=real_capital_ratio,
        rationale=(
            f"the highest published capital-to-output ratio over the window is {real_capital_ratio:.2f}, "
            f"which makes the investment share r = 1 - K_R/Y equal {1.0 - real_capital_ratio:.2f} at that "
            f"point. Wherever r is negative the reduced output equation "
            f"Y_dot = (p_b Y + r K_I + S) / 2 drives output towards zero, so the system does not "
            f"integrate. A common scale of {scale:.4f} applied to both capital stocks brings the maximum "
            f"K_R/Y to {target:.2f}, so r stays positive for every period and section 0.2's definition of "
            f"it as a share holds throughout. The scale is applied to both stocks, so K_R/K_I and "
            f"therefore the Phase 4 condition are unchanged, and being multiplicative it cannot alter "
            f"growth rates, direction or turning points. The consequence is that K_R/Y cannot cross one "
            f"inside the calibration window, so the production-versus-financial transition of section 0.5 "
            f"is not observable on the normalised path."
        ),
    )


@dataclass
class AssembledEconomy:
    """One economy, assembled and checked, ready to calibrate.

    Attributes:
        code: The economy code.
        name: The economy's name.
        path: The observed trajectory the calibration consumes.
        saturation: The credit saturation axis, as a ratio.
        series: Every assembled series, keyed by quantity, for the manifest and the charts.
        window: The (first, last) period common to every required quantity.
        integrity: The integrity report for the required series.
        plausibility: The plausibility report, advisory.
        adjustments: The standardising adjustment applied per quantity.
        vintage: Per-series vintage, for the reporting header.
        notes: Anything a reader must know.
    """

    code: str
    name: str
    path: ObservedPath
    saturation: Series
    population_growth: np.ndarray | None
    series: dict[str, Series]
    window: tuple[int, int]
    integrity: IntegrityReport
    plausibility: IntegrityReport
    adjustments: dict[str, Any]
    vintage: dict[str, str]
    notes: list[str] = field(default_factory=list)

    def record_in(self, manifest: Manifest) -> None:
        """Add every assembled series to a manifest."""
        manifest.record_all(self.code, self.series.values())


def _world_bank_unitless(sources: SourceSet, country: str, indicator: str, name: str, units: str) -> Series:
    """Fetch a World Bank percentage series and convert it to a fraction, logging the conversion."""
    series = sources.world_bank.series(
        country, indicator, name, units, Basis.UNITLESS, None, start=1960
    )
    return series.scaled(0.01, f"{units} to a fraction")


def _net_new_credit_share(saturation: Series, output: Series) -> Series:
    """Net new credit as a share of output, derived from the credit-to-GDP ratio and output.

    The identity. Total credit in period t is the credit-to-GDP ratio times output, `C_t = c_t * Y_t`.
    Net new credit is the change in that stock, and expressing it as a share of contemporaneous output
    gives

        stimulus_share_t = (c_t * Y_t - c_{t-1} * Y_{t-1}) / Y_t

    **Why this proxy exists.** For an economy whose discretionary injection runs mostly through credit
    rather than through the budget, the general-government balance measures the wrong channel. China is
    the case the economy configs name: local-government financing vehicles and policy-bank lending are
    the larger channels and neither appears in the fiscal balance, which the World Bank does not publish
    for China in any case. Net new credit captures both, because both end as credit to the non-financial
    sector.

    **What it is and is not.** Every input is published: the ratio is BIS total credit to the
    non-financial sector, the level is World Bank output. The result is therefore `DERIVED`, computed by
    a stated method from published inputs, and not an assumption. It is not a fiscal measure and should
    not be compared against one across economies: an economy on the fiscal proxy and an economy on this
    one are measuring different channels, which is why the choice is recorded per economy and reported
    on the output.

    **The first period.** A stock change needs a prior observation, so the first period is missing rather
    than zero. It is left as NaN and the window logic drops it, which shortens the window by one period.
    Filling it with zero would assert that no credit was created in that year.

    **The credit uplift.** This is derived from the unadjusted ratio, before the configured credit uplift
    is applied to the saturation axis. The uplift is a level scale, so applying it here as well would
    scale the injection by the same factor a second time without any further justification.
    """
    ratio = saturation.values
    level = output.values
    common = ratio.index.intersection(level.index)
    if len(common) < 2:
        raise LoaderError(
            f"net new credit needs at least two periods where both the credit ratio and output are "
            f"observed, found {len(common)}"
        )

    ratio_common = ratio.reindex(common).sort_index()
    level_common = level.reindex(common).sort_index()
    credit = ratio_common * level_common
    share = credit.diff() / level_common

    return saturation.transformed(
        share,
        "net_new_credit",
        (
            "net new credit as a share of output, computed as the period-on-period change in "
            "(credit-to-GDP ratio times output), divided by contemporaneous output. Derived from BIS "
            "total credit to the non-financial sector and World Bank output, both published. The first "
            "period is missing because a stock change has no prior to difference against."
        ),
        reliability=Reliability.DERIVED,
        units="fraction of GDP",
        basis=Basis.UNITLESS,
        currency=None,
        valuation=Valuation.NOT_APPLICABLE,
    ).rename("stimulus_share")


def _capital_ratio(
    sources: SourceSet,
    iso3: str,
    depreciation_prior: float,
) -> tuple[Series, list[str]]:
    """Build the real-capital-to-output ratio, extended past the Penn World Table window.

    Returns the ratio and any notes. The ratio is used rather than the level throughout, for the reasons
    in the module docstring: it is unitless, so it carries no valuation and can be multiplied by a
    market-valued output level without mixing bases.
    """
    notes: list[str] = []
    capital = sources.pwt.series(iso3, "cn", "K_R_ppp")
    output_ppp = sources.pwt.series(iso3, "cgdpo", "Y_ppp")

    aligned = align([capital, output_ppp], how="inner")
    ratio_values = (aligned["K_R_ppp"] / aligned["Y_ppp"]).dropna()
    if ratio_values.empty:
        raise PipelineError(
            f"Penn World Table has no overlapping capital and output observations for {iso3!r}"
        )

    ratio = Series(
        name="K_R_over_Y",
        values=ratio_values.rename("K_R_over_Y"),
        provenance=capital.provenance.with_transformation(
            "capital_output_ratio",
            "cn divided by cgdpo, both at current PPPs so the ratio is valid and unitless. Being "
            "unitless it carries no valuation, which is what allows it to be combined with a "
            "market-valued output level without mixing PPP and market bases.",
            units="ratio of output",
            basis=Basis.UNITLESS,
            currency=None,
            valuation=Valuation.NOT_APPLICABLE,
        ),
    )

    published_end = int(ratio.values.dropna().index[-1])
    try:
        share = _world_bank_unitless(
            sources, iso3, WORLD_BANK["investment_share"], "investment_share", "percent of GDP"
        )
        growth = _world_bank_unitless(
            sources, iso3, WORLD_BANK["output_growth"], "output_growth", "percent"
        )
        delta = sources.pwt.depreciation_rate(iso3)
        extended = extend_capital_ratio_by_perpetual_inventory(
            ratio, share, growth, depreciation_prior, published_depreciation=delta
        )
        extended_end = int(extended.values.dropna().index[-1])
        if extended_end > published_end:
            notes.append(
                f"the real-capital ratio is published through {published_end} and extended to "
                f"{extended_end} in ratio space. The extended values are computed, not published, and "
                f"any output using them carries the extension label."
            )
        return extended, notes
    except (SourceError, LoaderError) as error:
        notes.append(
            f"the real-capital ratio could not be extended past {published_end}: {error}. The window "
            f"therefore ends there rather than being filled."
        )
        return ratio, notes


def assemble(
    code: str,
    sources: SourceSet,
    config: config_module.Config | None = None,
    adjustments: Mapping[str, SeriesAdjustment] | None = None,
    window_start: int | None = None,
    window_end: int | None = None,
    capital_target: float = DEFAULT_CAPITAL_TARGET,
) -> AssembledEconomy:
    """Assemble one economy from the data layer.

    Args:
        code: The economy code, which must have a configuration file.
        sources: The connector set, sharing one cache.
        config: The loaded configuration. Loaded from the code if omitted.
        adjustments: Standardising level adjustments by quantity. Identity by default.
        window_start: Override the first calibration period.
        window_end: Override the last.
        capital_target: K_R/Y at the window start after normalisation. See CapitalNormalisation for why
            this is necessary rather than cosmetic.

    Returns:
        The assembled economy.

    Raises:
        PipelineError: If a required quantity is unavailable. Per brief section 2 a run that needs an
            unavailable input fails loudly rather than proceeding on a guess.
    """
    settings = config or config_module.load(code)
    iso3 = settings.get("economy.world_bank")
    bis_code = settings.get("economy.bis")
    name = settings.get("economy.name")
    depreciation_prior = float(
        settings.get("data.real_capital_extension.default_depreciation_rate")
    )
    chosen_adjustments = dict(adjustments or {})
    notes: list[str] = []

    # Output, the level everything else is expressed against.
    try:
        output = sources.world_bank.series(
            iso3, WORLD_BANK["output"], "Y", "current US dollars", Basis.NOMINAL, "USD", start=1960
        )
    except SourceError as error:
        raise PipelineError(f"{code}: output is unavailable, so nothing can be assembled: {error}") from error

    # The saturation axis, from BIS, as a ratio.
    try:
        saturation = to_ratio_of_gdp(sources.bis.total_credit_to_gdp(bis_code), "saturation")
    except SourceError as error:
        raise PipelineError(
            f"{code}: BIS total credit is unavailable, so the saturation axis and the phase "
            f"classification cannot be produced: {error}"
        ) from error

    # Real capital, as a ratio, extended where possible.
    capital_ratio, capital_notes = _capital_ratio(sources, iso3, depreciation_prior)
    notes.extend(capital_notes)

    # The savings rate.
    try:
        savings = _world_bank_unitless(
            sources, iso3, WORLD_BANK["savings_rate"], "p_s", "percent of GDP"
        )
    except SourceError as error:
        raise PipelineError(f"{code}: the savings rate is unavailable: {error}") from error

    # The stimulus proxy. The configured choice is recorded, per brief section 2.
    proxy = settings.get("data.stimulus.proxy")
    reverse = bool(settings.get("data.stimulus.reverse_sign"))
    if proxy == "net_new_credit":
        # Derived from the credit ratio and output, both already loaded above. See
        # `_net_new_credit_share` for the identity and for why the fiscal balance is the wrong channel
        # for an economy configured this way.
        try:
            stimulus_share = _net_new_credit_share(saturation, output)
        except LoaderError as error:
            raise PipelineError(
                f"{code}: net new credit could not be derived: {error}"
            ) from error
        notes.append(
            "the stimulus proxy is net new credit, not the fiscal balance, because for this economy the "
            "discretionary injection runs mostly through credit rather than through the budget. It is "
            "derived from BIS total credit and World Bank output by a stated method, so it is a computed "
            "input rather than a published one, and it is not comparable against an economy measured on "
            "the fiscal balance."
        )
    else:
        if proxy != "fiscal_balance":
            notes.append(
                f"the configured stimulus proxy for this economy is {proxy!r}, which is not yet wired. "
                f"The fiscal balance is used instead and that substitution is recorded here rather than "
                f"passed over."
            )
        try:
            stimulus_share = _world_bank_unitless(
                sources, iso3, WORLD_BANK["fiscal_balance"], "stimulus_share", "percent of GDP"
            )
        except SourceError as error:
            raise PipelineError(f"{code}: the stimulus proxy is unavailable: {error}") from error
    if reverse:
        stimulus_share = stimulus_share.scaled(
            -1.0, "sign reversed so that a fiscal deficit reads as a positive injection"
        )

    # Population growth, which section 0.2 says p_b tracks. Optional, because a missing population series
    # should not stop an economy being assembled; the calibration falls back to the formula as written and
    # records that it did.
    population_growth: Series | None = None
    try:
        population = sources.world_bank.series(
            iso3, "SP.POP.TOTL", "population", "persons", Basis.UNITLESS, None, start=1960
        )
        growth_values = population.values.astype(float).pct_change().dropna()
        population_growth = Series(
            name="population_growth",
            values=growth_values.rename("population_growth"),
            provenance=population.provenance.with_transformation(
                "growth_rate",
                "period-on-period fractional change in population, used for p_b because section 0.2 says "
                "p_b tracks population growth and the formula it gives is a flow ratio rather than a rate",
                units="fraction per year",
            ),
        )
    except SourceError as error:
        notes.append(
            f"population is unavailable ({error}), so p_b falls back to the flow-ratio formula of section "
            f"0.2, which is dimensionally inconsistent with its use and will not produce a usable "
            f"trajectory."
        )

    # Equity market capitalisation, optional: it only enters the fallback K_I measure.
    equity_share: Series | None = None
    try:
        equity = sources.world_bank.series(
            iso3,
            WORLD_BANK["equity_market_cap"],
            "equity_market_cap",
            "current US dollars",
            Basis.NOMINAL,
            "USD",
            start=1975,
        )
        aligned_equity = align([equity, output], how="inner")
        equity_share = Series(
            name="equity_share",
            values=(aligned_equity["equity_market_cap"] / aligned_equity["Y"]).rename("equity_share"),
            provenance=equity.provenance.with_transformation(
                "share_of_output",
                "listed equity market capitalisation divided by output, giving a unitless share",
                units="ratio of output",
                basis=Basis.UNITLESS,
                currency=None,
                valuation=Valuation.NOT_APPLICABLE,
            ),
        )
    except SourceError as error:
        notes.append(
            f"listed equity market capitalisation is unavailable ({error}), so K_I covers credit only "
            f"and is narrower than the chapter 10.4 definition."
        )

    # Consumer prices, optional: an INDEPENDENT deflator, which is the whole reason to fetch it.
    #
    # The programme can always deflate by its own real-economy price level, but chapter 7 derives that as
    # proportional to output, so deflating *output* by it is circular and returns a flat line. A real view of
    # output needs a deflator that is not a function of output, and CPI is the conventional one. Book chapter
    # 11 prefers the gold price and that remains to be wired; `real_view.Basis` carries both.
    #
    # Optional in the same sense as equity: a missing CPI narrows what can be reported and stops nothing.
    consumer_prices: Series | None = None
    try:
        consumer_prices = sources.world_bank.series(
            iso3,
            WORLD_BANK["consumer_prices"],
            "consumer_prices",
            "index, 2010 = 100",
            Basis.UNITLESS,
            None,
            start=1960,
        )
    except SourceError as error:
        notes.append(
            f"consumer prices are unavailable ({error}), so the only real view is the one deflated by the "
            f"model's own price level, and output has no real view at all because that deflator is "
            f"proportional to output."
        )

    # The gold price, optional: the framework's OWN preferred deflator.
    #
    # Chapter 11 computes its 172-year real-rate series with the gold price rather than CPI, on chapter 24's
    # argument that in a fiat regime gold becomes a price-of-money instrument whose nominal price reflects the
    # issuing currency's loss of purchasing power. So this is not an alternative to CPI, it is the book's
    # basis, and both are reported so the two can be compared rather than argued about.
    #
    # It is a single global USD price rather than a per-economy series, which is consistent here because every
    # nominal quantity in this programme is already in current US dollars.
    gold_price: Series | None = None
    try:
        gold_price = sources.lbma.annual_gold_price()
    except SourceError as error:
        notes.append(
            f"the gold price is unavailable ({error}), so the real views fall back to consumer prices and to "
            f"the model's own price level. Chapter 11's own basis is gold, so this is a narrowing."
        )

    # The credit uplift, applied to the saturation axis by default.
    #
    # BIS covers the non-financial sector only, so it omits credit to the financial sector and much non-bank
    # intermediation. Both are debt claims and therefore financial capital in the model's terms. Because K_I
    # is the saturation ratio times output, the uplift flows into K_I automatically, which is the point: the
    # newly attributed credit is financial capital.
    #
    # It is a level adjustment, so it cannot change a growth rate, a direction or a turning point, and it is
    # identical across economies so it cannot reorder the cross-section. See config/defaults.yaml for the
    # derivation of the factor.
    uplift_factor = float(settings.get("data.credit_uplift.factor", default=1.0))
    if uplift_factor != 1.0:
        uplift = SeriesAdjustment(
            level_scale=uplift_factor,
            rationale=str(settings.get("data.credit_uplift.rationale")).strip(),
            source=str(settings.get("data.credit_uplift.source")).strip(),
            prior_range=tuple(settings.get("data.credit_uplift.prior_range")),
        )
        chosen_adjustments.setdefault("saturation", uplift)
        notes.append(
            f"the credit saturation axis carries an uplift of {uplift_factor:.2f}, because BIS total credit "
            f"to the non-financial sector omits credit to the financial sector and much non-bank "
            f"intermediation. The uplift flows into K_I, since K_I is the saturation ratio times output. It "
            f"is a level adjustment, so growth rates, direction and turning points are unchanged, and it is "
            f"applied identically to every economy, so the cross-section ordering is unchanged."
        )

    # Apply any standardising adjustments, which are level-only and therefore dynamics-neutral.
    adjusted: dict[str, Series] = {}
    for quantity, series in {
        "Y": output,
        "saturation": saturation,
        "K_R_over_Y": capital_ratio,
        "p_s": savings,
        "stimulus_share": stimulus_share,
    }.items():
        adjustment = chosen_adjustments.get(quantity, SeriesAdjustment())
        adjusted[quantity] = apply(series, adjustment)
    if equity_share is not None:
        adjusted["equity_share"] = equity_share
    if population_growth is not None:
        adjusted["population_growth"] = population_growth
    # Deliberately not adjusted: a deflator carries no level adjustment, since scaling it would rescale every
    # deflated series by the same constant while changing nothing about the comparison.
    if consumer_prices is not None:
        adjusted["consumer_prices"] = consumer_prices
    if gold_price is not None:
        adjusted["gold_price"] = gold_price

    # Determine the window from the quantities the calibration actually needs.
    required = [adjusted["Y"], adjusted["saturation"], adjusted["K_R_over_Y"], adjusted["p_s"], adjusted["stimulus_share"]]
    try:
        window = determine_window(required, window_start, window_end)
    except LoaderError as error:
        raise PipelineError(f"{code}: no usable calibration window: {error}") from error

    # Which components K_I is built from. Read before the join, because it decides whether the equity
    # series is allowed to constrain the window.
    components = settings.get(
        "data.financial_capital.fallback_components", default=["bis_total_credit_non_financial"]
    )

    # Only series that actually feed the model may constrain the window.
    #
    # Equity market capitalisation is deliberately absent from this list. It is kept as a diagnostic but no
    # longer enters K_I, and while it was still in the inner join it was silently truncating windows: France
    # ended at 2018 and the United Kingdom at 2022 purely because their World Bank equity series stop there,
    # discarding six years of otherwise complete data. A series that contributes nothing must not constrain
    # anything.
    contributing = [adjusted[key] for key in ("population_growth",) if key in adjusted]
    if "listed_equity_market_cap" in components and "equity_share" in adjusted:
        contributing.append(adjusted["equity_share"])
    frame = pd.DataFrame(align(required + contributing, how="inner"))
    frame = frame.loc[(frame.index >= window[0]) & (frame.index <= window[1])].dropna()
    if frame.empty:
        raise PipelineError(
            f"{code}: the required quantities share no complete periods inside {window}. Narrow the "
            f"window or accept a shorter one."
        )

    periods = frame.index.to_numpy(dtype=int)
    output_level = frame["Y"].to_numpy(dtype=float)
    real_capital = frame["K_R_over_Y"].to_numpy(dtype=float) * output_level

    # K_I is BIS total credit only. Listed equity market capitalisation is deliberately excluded: it
    # varies by a factor of 3.9 across Germany, the United Kingdom and the United States against 1.28 for
    # credit, and the World Bank series is published on different vintages per economy (France 2018,
    # United Kingdom 2022, others 2025). See data.financial_capital in config/defaults.yaml for the
    # figures. The equity share is still carried in `series` as a diagnostic.
    financial_capital = frame["saturation"].to_numpy(dtype=float) * output_level
    if "listed_equity_market_cap" in components and "equity_share" in frame.columns:
        financial_capital = financial_capital + frame["equity_share"].to_numpy(dtype=float) * output_level
        notes.append(
            "K_I includes listed equity market capitalisation, which is not comparable across economies "
            "and is published on mixed vintages. This is not the default and should be justified."
        )
    else:
        notes.append(
            "K_I is BIS total credit to the non-financial sector only. Listed equity market "
            "capitalisation is excluded because it is not comparable across economies and its vintages "
            "differ by up to seven years, so including it would make a cross-section incoherent."
        )

    # The published capital ratios are far outside the range in which section 0.2's investment share is a
    # share, which is what stops the system integrating. A common scale on both stocks fixes that without
    # touching K_R/K_I or any dynamic quantity. See CapitalNormalisation.
    # Scaled on the maximum over the window, not the first period, so the investment share stays positive
    # throughout. See CapitalNormalisation and DEFAULT_CAPITAL_TARGET.
    normalisation = capital_normalisation(
        float(np.max(real_capital / output_level)), capital_target
    )
    real_capital_scaled = real_capital * normalisation.scale
    financial_capital_scaled = financial_capital * normalisation.scale
    if not normalisation.is_identity:
        notes.append(normalisation.rationale)

    path = ObservedPath(
        periods=periods,
        output=output_level,
        real_capital=real_capital_scaled,
        financial_capital=financial_capital_scaled,
        savings_rate=frame["p_s"].to_numpy(dtype=float),
        stimulus_proxy=frame["stimulus_share"].to_numpy(dtype=float) * output_level,
    )

    # Integrity: derived inputs are permitted here because the capital ratio is a documented extension
    # and any adjustment is a documented computation, and both are recorded on the series.
    integrity = check_model_inputs(required, allow_derived=True, allow_interpolated=False)
    consistency = check_consistency([adjusted["Y"]])
    integrity.extend(consistency)
    plausibility = check_plausibility(
        [adjusted["saturation"], adjusted["K_R_over_Y"], adjusted["p_s"]]
    )

    notes.append(
        "K_R is reconstructed as the Penn World Table capital-to-output ratio multiplied by "
        "market-valued output, so it is market-valued by construction and no PPP conversion factor is "
        "involved. It is a reconstruction rather than a published level."
    )

    return AssembledEconomy(
        code=code,
        name=str(name),
        path=path,
        saturation=adjusted["saturation"],
        population_growth=(
            frame["population_growth"].to_numpy(dtype=float)
            if "population_growth" in frame.columns
            else None
        ),
        series={key: value for key, value in adjusted.items()},
        window=(int(periods[0]), int(periods[-1])),
        integrity=integrity,
        plausibility=plausibility,
        adjustments={
            **{
                key: chosen_adjustments.get(key, SeriesAdjustment()).as_dict()
                for key in ("Y", "saturation", "K_R_over_Y", "p_s", "stimulus_share")
            },
            "capital_normalisation": normalisation.as_dict(),
        },
        vintage={
            key: f"{series.provenance.source} {series.provenance.vintage or series.provenance.retrieved_on}"
            for key, series in adjusted.items()
        },
        notes=notes,
    )


def common_cross_section_year(economies: Sequence[AssembledEconomy]) -> int:
    """Return the latest period every economy covers, for a coherent cross-section.

    Comparing each economy at its own latest period is not a cross-section, and the mismatch here is not
    small: the World Bank equity and fiscal series run to different years per economy, so an unrestricted
    comparison silently mixed vintages from 2018 to 2025. Two economies whose figures are seven years apart
    cannot be ranked against each other.

    Args:
        economies: The assembled economies to compare.

    Returns:
        The latest year all of them cover.

    Raises:
        PipelineError: If there is no shared year, since the comparison is then impossible rather than
            merely awkward.
    """
    if not economies:
        raise PipelineError("no economies were supplied")

    # Intersect the actual observed periods, not the window bounds. A window is only its first and last
    # period, and gap-dropping leaves the series non-contiguous, so a year inside every window can still be
    # missing from some economy's data. Taking the minimum of the window ends produced exactly that: a year
    # that no lookup could find.
    shared: set[int] | None = None
    for economy in economies:
        periods = {int(p) for p in np.asarray(economy.path.periods)}
        shared = periods if shared is None else shared & periods

    if not shared:
        detail = ", ".join(
            f"{economy.code} {economy.window[0]} to {economy.window[1]}" for economy in economies
        )
        raise PipelineError(
            f"these economies share no observed period, so they cannot be compared: {detail}"
        )
    return int(max(shared))


@dataclass
class CrossSection:
    """A comparison of several economies at one shared period.

    Attributes:
        year: The shared period.
        rows: One entry per economy, at that period.
        excluded: Economies dropped, with the reason.
        notes: What a reader must know to read the ranking.
    """

    year: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def cross_section(
    economies: Sequence[AssembledEconomy],
    year: int | None = None,
    exclude_aggregates: bool = True,
    thresholds: "PhaseThresholds | None" = None,
) -> CrossSection:
    """Build a comparison of several economies at a single shared period.

    Args:
        economies: The assembled economies.
        year: The period to compare at. Defaults to the latest year all of them cover.
        exclude_aggregates: Drop the euro area when any of its members is present, since a ranking
            containing both double counts them.
        thresholds: The phase cut-offs. Loaded from configuration when omitted, which matters: an earlier
            version left this to the dataclass defaults and so silently ignored the configured Phase 3
            ceiling, reporting the United Kingdom as Saturation on a ceiling of 3.0 after the configured
            value had been raised to 3.5.

    Returns:
        The cross-section.
    """
    from macrofield.model.phases import PhaseThresholds, classify_period

    if thresholds is None:
        thresholds = PhaseThresholds.from_config(config_module.load())

    selected = list(economies)
    excluded: list[str] = []

    if exclude_aggregates:
        codes = {economy.code for economy in selected}
        if "eurozone" in codes and codes & {"de", "fr"}:
            selected = [economy for economy in selected if economy.code != "eurozone"]
            excluded.append(
                "eurozone, because a ranking containing the aggregate and its members double counts them"
            )

    shared = int(year) if year is not None else common_cross_section_year(selected)
    rows: list[dict[str, Any]] = []

    for economy in selected:
        matches = np.flatnonzero(np.asarray(economy.path.periods) == shared)
        if matches.size == 0:
            excluded.append(f"{economy.code}, which has no observation for {shared}")
            continue
        index = int(matches[0])
        path = economy.path
        classification = classify_period(
            saturation=float(economy.saturation.values.loc[shared]),
            real_capital=float(path.real_capital[index]),
            financial_capital=float(path.financial_capital[index]),
            output=float(path.output[index]),
            thresholds=thresholds,
        )
        rows.append(
            {
                "code": economy.code,
                "name": economy.name,
                "year": shared,
                "saturation": classification.saturation,
                "real_capital_over_output": float(path.real_capital[index] / path.output[index]),
                "financial_capital_over_output": float(
                    path.financial_capital[index] / path.output[index]
                ),
                "real_to_financial": classification.real_to_financial,
                # The stimulus as a share of output. Surfaced in the cross-section because the framework
                # predicts a relationship: as saturation rises, a larger injection is needed to sustain
                # activity, so a highly saturated economy should show a larger deficit. Reporting the two
                # side by side lets that be read off rather than inferred.
                "stimulus_over_output": float(path.stimulus_proxy[index] / path.output[index]),
                "phase": classification.phase.label,
                "in_balanced_band": classification.in_balanced_band,
            }
        )

    rows.sort(key=lambda row: row["saturation"], reverse=True)

    # Does the framework's expected relationship hold across this panel? Computed here and reported below,
    # once the notes list exists.
    stimulus_note: str | None = None
    if len(rows) >= 3:
        saturations = np.array([row["saturation"] for row in rows])
        stimuli = np.array([row["stimulus_over_output"] for row in rows])
        if np.std(saturations) > 0 and np.std(stimuli) > 0:
            correlation = float(np.corrcoef(saturations, stimuli)[0, 1])
            stimulus_note = (
                f"saturation and the stimulus share correlate at {correlation:+.2f} across these "
                f"{len(rows)} economies. The framework expects a positive relationship, because a more "
                f"saturated economy needs a larger injection to sustain activity. With this few economies "
                f"the figure is indicative rather than evidence."
            )
    notes = [
        f"every figure is for {shared}, the latest period all these economies cover. Comparing each at its "
        f"own latest period would mix vintages, which for the World Bank series in this panel spans 2018 "
        f"to 2025.",
        "K_I is BIS total credit to the non-financial sector only, which is harmonised across economies. "
        "Listed equity market capitalisation is excluded because it varies by a factor of nearly four "
        "across otherwise similar economies and is published on mixed vintages.",
        "real capital levels come from Penn World Table and are normalised per economy, so the K_R/Y "
        "levels below are not independent cross-country observations. See CapitalNormalisation.",
    ]
    if stimulus_note:
        notes.append(stimulus_note)
    return CrossSection(year=shared, rows=rows, excluded=excluded, notes=notes)


def build_sources(offline: bool = False, config: config_module.Config | None = None) -> SourceSet:
    """Build the connector set against the configured cache."""
    settings = config or config_module.load()
    cache = Cache(Path(settings.get("data.cache_directory")), offline=offline)
    return SourceSet.build(cache, timeout=180)
