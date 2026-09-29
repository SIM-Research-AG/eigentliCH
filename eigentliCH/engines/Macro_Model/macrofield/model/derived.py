"""Indicators derived from the three-body state and the quantity equation.

The state variables Y, K_R and K_I are not the whole output of the framework. The quantity equation,
which book chapter 7 presents as the continuity equation of the monetary-and-price field, carries price
levels, and from price levels follow inflation, the return on capital, and the real interest rate. Those
are what a reader actually asks about, and they are all functions of the state rather than new data.

**The derivation, from book chapter 7.**

The quantity equation is written `K · V = P · H`, where K is monetary capital in circulation, V its
velocity, P the price level and H the transaction frequency. Chapter 7.2 reads this as a conservation
statement: the price level is the source of money flows, and the divergence-free condition
`grad · (K, -P) = 0` must hold.

Split into a real and a financial sector and apply the framework's simplifications (velocities
approximated at one, money supply approximated by the relevant capital stock, real-economy price times
volume set equal to Y):

    real sector:       P_R · H_R = Y
    financial sector:  P_I · H_I = K_R + K_I - Y

So each price level is a capital stock divided by a transaction frequency, and the financial price level
is proportional to the unsecured-asset gap of section 0.4.

**What has to be assumed, and why it is stated on every result.**

Neither transaction frequency is observed. `H_R` and `H_I` therefore have to be supplied or assumed, and
the usual assumption is that they are constant, or that they grow with real activity. That assumption is
not innocuous: under constant H the financial price level *is* the unsecured-asset gap up to a constant,
so financial-asset inflation and the growth of unsecured assets become the same series. That is a
substantive claim about asset prices, not an accounting identity, and every result here carries the
assumption it was computed under.

Because of that, the indicators in this module are reported as **index levels and growth rates, not as
absolute price levels**. A price level requires knowing H; a growth rate only requires knowing that H is
stable, which is a far weaker assumption and the one the framework actually leans on.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from macrofield.model.quantity import unsecured_assets

#: Assumptions available for the unobserved transaction frequencies.
CONSTANT_FREQUENCY = "constant"
FREQUENCY_TRACKS_OUTPUT = "tracks_output"


class DerivedError(ValueError):
    """Raised when a derived indicator cannot be computed."""


class Indicator(enum.Enum):
    """The derived indicators, each with what it means and how much it can bear."""

    REAL_PRICE_LEVEL = "real_price_level"
    FINANCIAL_PRICE_LEVEL = "financial_price_level"
    REAL_INFLATION = "real_inflation"
    FINANCIAL_INFLATION = "financial_inflation"
    RETURN_ON_CAPITAL = "return_on_capital"
    REAL_INTEREST_RATE = "real_interest_rate"
    WAGE_SHARE_GROWTH = "wage_share_growth"
    PRICE_DIVERGENCE = "price_divergence"

    @property
    def label(self) -> str:
        return {
            Indicator.REAL_PRICE_LEVEL: "Real price level, index",
            Indicator.FINANCIAL_PRICE_LEVEL: "Financial price level, index",
            Indicator.REAL_INFLATION: "Real inflation",
            Indicator.FINANCIAL_INFLATION: "Financial inflation, asset prices",
            Indicator.RETURN_ON_CAPITAL: "Achievable return on capital",
            Indicator.REAL_INTEREST_RATE: "Real interest rate",
            Indicator.WAGE_SHARE_GROWTH: "Wage against capital income, growth",
            Indicator.PRICE_DIVERGENCE: "Asset prices against real prices",
        }[self]

    @property
    def units(self) -> str:
        if self in (Indicator.REAL_PRICE_LEVEL, Indicator.FINANCIAL_PRICE_LEVEL):
            return "index, first period = 100"
        if self is Indicator.PRICE_DIVERGENCE:
            return "ratio, first period = 1"
        return "fraction per period"


def _growth(values: np.ndarray) -> np.ndarray:
    """Period-on-period fractional change, padded at the front with NaN to preserve length."""
    series = np.asarray(values, dtype=float)
    out = np.full(series.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = np.diff(series) / series[:-1]
    return np.where(np.isfinite(out), out, np.nan)


def _index(values: np.ndarray, base: float = 100.0) -> np.ndarray:
    """Rebase a positive series to an index. Dynamics-neutral, so growth rates are unaffected."""
    series = np.asarray(values, dtype=float)
    finite = series[np.isfinite(series) & (series != 0.0)]
    if finite.size == 0:
        return np.full(series.shape, np.nan)
    return base * series / finite[0]


def transaction_frequency(
    output: np.ndarray,
    assumption: str = CONSTANT_FREQUENCY,
) -> np.ndarray:
    """Return the assumed transaction frequency path.

    Neither H_R nor H_I is observed. `constant` holds it flat, which makes each price level proportional
    to its capital stock. `tracks_output` grows it with real activity, which makes the real price level
    flat by construction and is therefore only useful for the financial side.

    Raises:
        DerivedError: If the assumption is unknown.
    """
    series = np.asarray(output, dtype=float)
    if assumption == CONSTANT_FREQUENCY:
        return np.ones_like(series)
    if assumption == FREQUENCY_TRACKS_OUTPUT:
        finite = series[np.isfinite(series) & (series != 0.0)]
        if finite.size == 0:
            raise DerivedError("output has no usable observations to scale the frequency by")
        return series / finite[0]
    raise DerivedError(
        f"unknown frequency assumption {assumption!r}, expected one of "
        f"{(CONSTANT_FREQUENCY, FREQUENCY_TRACKS_OUTPUT)}"
    )


@dataclass
class DerivedIndicators:
    """Every indicator derived from one state path.

    Attributes:
        periods: The period labels.
        values: Indicator to its series.
        assumption: The transaction-frequency assumption used.
        caveats: What each reader must know, keyed by indicator.
        notes: Anything applying to the whole set.
    """

    periods: np.ndarray
    values: dict[str, np.ndarray] = field(default_factory=dict)
    assumption: str = CONSTANT_FREQUENCY
    caveats: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def series(self, indicator: Indicator) -> np.ndarray:
        """Return one indicator's series.

        Raises:
            DerivedError: If it was not computed, naming what is available.
        """
        key = indicator.value
        if key not in self.values:
            raise DerivedError(
                f"{key!r} was not computed. Available: {sorted(self.values)}"
            )
        return self.values[key]

    def as_dict(self) -> dict[str, Any]:
        return {
            "periods": [int(p) for p in self.periods],
            "assumption": self.assumption,
            "indicators": {
                key: {
                    "label": Indicator(key).label,
                    "units": Indicator(key).units,
                    "values": [None if not np.isfinite(v) else float(v) for v in series],
                    "caveat": self.caveats.get(key, ""),
                }
                for key, series in self.values.items()
            },
            "notes": list(self.notes),
        }


def compute(
    periods: Sequence[Any],
    output: np.ndarray,
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output_growth: np.ndarray | None = None,
    real_capital_growth: np.ndarray | None = None,
    financial_capital_growth: np.ndarray | None = None,
    assumption: str = CONSTANT_FREQUENCY,
) -> DerivedIndicators:
    """Compute every derived indicator from a state path.

    Args:
        periods: The period labels.
        output: Y.
        real_capital: K_R.
        financial_capital: K_I.
        output_growth: Y_dot, for the return on capital. Differenced from Y when omitted.
        real_capital_growth: K_R_dot. Differenced when omitted.
        financial_capital_growth: K_I_dot. Differenced when omitted.
        assumption: The transaction-frequency assumption.

    Returns:
        The indicators, each with its caveat.

    Raises:
        DerivedError: If the inputs disagree in length or output is non-positive.
    """
    y = np.asarray(output, dtype=float)
    k_r = np.asarray(real_capital, dtype=float)
    k_i = np.asarray(financial_capital, dtype=float)
    period_array = np.asarray(list(periods))

    if not (y.shape == k_r.shape == k_i.shape == period_array.shape):
        raise DerivedError(
            f"inputs must share a shape, got periods {period_array.shape}, Y {y.shape}, "
            f"K_R {k_r.shape}, K_I {k_i.shape}"
        )
    if np.any(y <= 0.0):
        raise DerivedError("output must be strictly positive to derive price levels")

    frequency = transaction_frequency(y, assumption)
    result = DerivedIndicators(periods=period_array, assumption=assumption)

    # Real price level: P_R H_R = Y.
    real_price = y / frequency
    result.values[Indicator.REAL_PRICE_LEVEL.value] = _index(real_price)
    result.caveats[Indicator.REAL_PRICE_LEVEL.value] = (
        f"P_R H_R = Y, with the transaction frequency assumed {assumption!r}. Under 'tracks_output' this "
        f"series is flat by construction and carries no information."
    )

    # Financial price level: P_I H_I = K_R + K_I - Y, the unsecured-asset gap.
    gap = unsecured_assets(k_r, k_i, y)
    with np.errstate(divide="ignore", invalid="ignore"):
        financial_price = np.where(gap > 0.0, gap / frequency, np.nan)
    result.values[Indicator.FINANCIAL_PRICE_LEVEL.value] = _index(financial_price)
    result.caveats[Indicator.FINANCIAL_PRICE_LEVEL.value] = (
        "P_I H_I = K_R + K_I - Y, so under a constant frequency the financial price level is the "
        "unsecured-asset gap up to a constant. That equivalence is a claim about asset prices, not an "
        "accounting identity, and it is the assumption this indicator rests on. Undefined where the gap "
        "is not positive."
    )

    # Inflation on each side.
    result.values[Indicator.REAL_INFLATION.value] = _growth(real_price)
    result.caveats[Indicator.REAL_INFLATION.value] = (
        "the growth rate of the real price level. Requires only that the transaction frequency be stable, "
        "not that its level be known, which is why growth rates are reported and levels are not."
    )
    result.values[Indicator.FINANCIAL_INFLATION.value] = _growth(financial_price)
    result.caveats[Indicator.FINANCIAL_INFLATION.value] = (
        "asset-price inflation, the growth rate of the financial price level. This is the series the "
        "framework points at when it says asset prices follow the capital base rather than the real "
        "economy."
    )

    # The achievable return on capital, p_p from section 0.2. This is the model's interest rate.
    y_dot = np.asarray(output_growth, dtype=float) if output_growth is not None else np.gradient(y)
    k_r_dot = (
        np.asarray(real_capital_growth, dtype=float)
        if real_capital_growth is not None
        else np.gradient(k_r)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        return_on_capital = np.where(k_r != 0.0, (y_dot + k_r_dot) / k_r, np.nan)
    result.values[Indicator.RETURN_ON_CAPITAL.value] = return_on_capital
    result.caveats[Indicator.RETURN_ON_CAPITAL.value] = (
        "p_p from section 0.2, the achievable return on capital. This is the model's own interest rate: "
        "the return the capital stock can actually earn, as distinct from the rate demanded of it."
    )

    # The real interest rate: the return on capital net of real inflation.
    real_inflation = result.values[Indicator.REAL_INFLATION.value]
    result.values[Indicator.REAL_INTEREST_RATE.value] = return_on_capital - real_inflation
    result.caveats[Indicator.REAL_INTEREST_RATE.value] = (
        "the return on capital net of real inflation. The framework's empirical counterpart is the "
        "Officer-Williamson series, whose seven-century secular decline book chapter 11 treats as the "
        "deepest evidence for capital saturation."
    )

    # Wage against capital income, p_b. Reported as a growth rate rather than a level, because its level
    # is dimensionally inconsistent with its stated meaning (see calibration/fit.py).
    k_i_dot = (
        np.asarray(financial_capital_growth, dtype=float)
        if financial_capital_growth is not None
        else np.gradient(k_i)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        wage_ratio = np.where(k_i_dot != 0.0, (y_dot + k_r_dot) / k_i_dot, np.nan)
    result.values[Indicator.WAGE_SHARE_GROWTH.value] = _growth(wage_ratio)
    result.caveats[Indicator.WAGE_SHARE_GROWTH.value] = (
        "the growth rate of p_b, wage against capital income. Only the growth rate is reported: the level "
        "of the section 0.2 formula is a ratio of flows of order one, which is dimensionally inconsistent "
        "with the rate its own description calls for. See docs/MODEL_SPEC.md."
    )

    # The divergence between asset prices and real prices, which is the financialisation signature.
    financial_index = result.values[Indicator.FINANCIAL_PRICE_LEVEL.value]
    real_index = result.values[Indicator.REAL_PRICE_LEVEL.value]
    with np.errstate(divide="ignore", invalid="ignore"):
        divergence = np.where(real_index > 0.0, financial_index / real_index, np.nan)
    result.values[Indicator.PRICE_DIVERGENCE.value] = divergence / (
        divergence[np.isfinite(divergence)][0] if np.any(np.isfinite(divergence)) else 1.0
    )
    result.caveats[Indicator.PRICE_DIVERGENCE.value] = (
        "asset prices against real prices, rebased to one. Rising means the financial sector is repricing "
        "faster than the real economy, which is the framework's definition of financialisation. This is "
        "the single most direct chart of the thesis."
    )

    result.notes = [
        f"transaction frequencies are unobserved and assumed {assumption!r}. Growth rates need only that "
        f"the frequency be stable; levels need its value, so levels are reported as indices.",
        "every indicator here is a function of the state path, not new data, so a projected state gives a "
        "projected indicator with no additional assumption.",
    ]
    return result


def summarise_latest(result: DerivedIndicators) -> dict[str, Any]:
    """The latest value of each indicator, for a dashboard tile or a brief."""
    latest: dict[str, Any] = {"period": None}
    if result.periods.size:
        latest["period"] = int(result.periods[-1])
    for key, series in result.values.items():
        finite = series[np.isfinite(series)]
        latest[key] = {
            "label": Indicator(key).label,
            "units": Indicator(key).units,
            "value": float(finite[-1]) if finite.size else None,
        }
    return latest
