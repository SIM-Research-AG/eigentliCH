"""The three-driver stock-to-gold ratio model.

Brief section 0.7 and BOOK chapter 24.2, which gives the framework's own field-theoretic derivation of
gold's value. The three drivers arise from the three-body model and correspond to the credit,
innovation and capital cycles. The operational form is the differential equation in "Feldtheoretische
Beschreibung der Dynamiken von Volkswirtschaften" as applied in "Treiber des Goldwertes" (with Degussa
Goldhandel AG).

The modelled quantity is `R_DG`, the ratio of gold to an equity index. The brief asks for the
stock-to-gold ratio, which is its reciprocal; both are reported, because a reader who takes one for
the other inverts every conclusion.

The authoritative equation, supplied by the author on 2026-07-27:

    R_DG_dot = + a1 (K_I_ddot / Y) - a2 (Y_dot / K_I) - a3 ((K_R_dot + K_I_dot - Y_dot) / K_I)

with weights a1, a2, a3 >= 0. The signs are `+, -, -` and they live in config rather than in this
code, so that a recalibration cannot silently reverse a driver's economics.

BOOK equation 24.1 states the same model in conceptual variables:

    d/dt (P_G / P_S) = f1(K_I_dot) - f2(kappa_bar_R_dot) + f3(delta_C)

The two agree once the correspondences are made explicit, and the operational form supplies the
functional shapes `f1, f2, f3` that chapter 24 declines to give ("specified in the broader
field-theoretic apparatus; we will not develop the full mathematical specification here"). Each is
linear in its driver term:

- `f1`: the liquidity impulse. Chapter 24 writes `K_I_dot`; the operational form uses the
  acceleration `K_I_ddot` scaled by output, which is the credit *impulse* rather than the credit
  level. Both carry a **positive** sign.
- `f2`: the innovation driver. Chapter 24 writes the shift in the real-capital saturation level
  `kappa_bar_R_dot`; the operational form proxies it by output growth relative to financial capital,
  `Y_dot / K_I`. Both carry a **negative** sign.
- `f3`: currency-system confidence. Chapter 24 writes `+f3(delta_C)` where `delta_C` is the change in
  confidence; the operational form writes `-a3` on the unsecured-asset gap derivative. These are the
  same driver with the same orientation, because a widening unsecured-asset gap is a *loss* of
  currency backing, that is the negative of a confidence change. The two sign conventions differ only
  because the two quantities point opposite ways.

The three drivers:

1. **Liquidity and credit impulse.** Monetary expansion creates financial capital that seeks
   deployment, and a portion of it seeks expression in gold, supporting gold's price. The source
   approximates the credit cycle by the acceleration of financial capital relative to productivity,
   which is the `K_I_ddot / Y` term. Dominant implies a participatory stance.
2. **Innovation-driven growth.** Firms are value-creating, so under normal growth equities outperform
   gold over time. Vigorous innovation cycles create competing real-asset investments and the
   relative attractiveness of gold declines. Dominant implies a value-producing stance.
3. **Capital-cycle currency stability.** A derivative of the quantity equation. Above a threshold
   ratio of capital to output the quantity equation loses validity and currency stability is lost.
   Note the numerator is the time derivative of the unsecured-asset gap of section 0.4. Dominant
   implies a value-preserving stance.

**Driver one's sign is positive.** An earlier revision of this module made it negative, reasoning that
a positive credit impulse means rising system confidence and so must push gold down against equities.
That reasoning was wrong: the credit impulse enters as a *liquidity* impulse, not as a confidence
reading, and confidence is carried by driver three. Chapter 24.2 states the mechanism directly, and
the author confirmed the equation on 2026-07-27. See docs/MODEL_SPEC.md section 5.

**Chapter 24 on the combination.** The chapter says the three drivers' combination "is not a simple
weighted sum; it involves the specific interaction of the drivers under the conditions prevailing at
any given time." The signed weighted sum implemented here is the operational form the framework
calibrates, and the conditional interaction the chapter describes enters through the dominant-driver
selection and the quantity-equation validity check rather than through a cross term. That is a
documented simplification, not a claim that the chapter's sentence has been implemented.

**No dated forecast is encoded.** The source's 2020-vintage conclusions (a ratio peak in 2022 and a
2025 to 2028 hyperinflationary window) illustrate the method at that vintage and are excluded per
brief section 0.14. The calibration anchor is configuration, not a constant, and any dated statement
the programme makes is recomputed from data.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

#: The three drivers, in the order the source writes them.
DRIVER_KEYS = (
    "liquidity_credit_impulse",
    "innovation_growth",
    "capital_cycle_currency_stability",
)

#: The signs of the authoritative equation, `+, -, -`. Held here as well as in config so that a
#: DriverWeights built without a config carries the source's economics rather than a neutral guess,
#: and so that a config edit that reverses a driver is visible as a divergence from this constant.
SOURCE_DRIVER_SIGNS: Mapping[str, float] = {
    "liquidity_credit_impulse": 1.0,
    "innovation_growth": -1.0,
    "capital_cycle_currency_stability": -1.0,
}


class AssetStance(enum.Enum):
    """The asset stance the dominant driver selects, per the source.

    The source distinguishes value-producing assets (equity in firms), participatory assets (for
    example owner-occupied property), and value-preserving assets (physical gold).
    """

    PARTICIPATORY = "participatory"
    VALUE_PRODUCING = "value_producing"
    VALUE_PRESERVING = "value_preserving"


#: Which stance each driver selects when it dominates.
DRIVER_STANCE = {
    "liquidity_credit_impulse": AssetStance.PARTICIPATORY,
    "innovation_growth": AssetStance.VALUE_PRODUCING,
    "capital_cycle_currency_stability": AssetStance.VALUE_PRESERVING,
}


class StockGoldError(ValueError):
    """Raised when a stock-to-gold input or configuration is unusable."""


@dataclass
class DriverWeights:
    """The three weights and their signs.

    Attributes:
        liquidity_credit_impulse: Weight a1, non-negative.
        innovation_growth: Weight a2, non-negative.
        capital_cycle_currency_stability: Weight a3, non-negative.
        signs: Sign per driver, normally from config. Defaults to SOURCE_DRIVER_SIGNS, the `+, -, -`
            of the authoritative equation.
    """

    liquidity_credit_impulse: float = 1.0
    innovation_growth: float = 1.0
    capital_cycle_currency_stability: float = 1.0
    signs: Mapping[str, float] = field(
        default_factory=lambda: dict(SOURCE_DRIVER_SIGNS)
    )

    def __post_init__(self) -> None:
        for key in DRIVER_KEYS:
            weight = float(getattr(self, key))
            if weight < 0.0:
                raise StockGoldError(
                    f"weight {key} must be non-negative, got {weight}. The direction of a driver is "
                    f"carried by its sign in config, not by a negative weight, so that a fitted "
                    f"weight cannot silently flip a driver's economics."
                )
            if key not in self.signs:
                raise StockGoldError(f"no sign configured for driver {key}")

    def as_array(self) -> np.ndarray:
        """Return the signed weights in DRIVER_KEYS order."""
        return np.array(
            [float(self.signs[key]) * float(getattr(self, key)) for key in DRIVER_KEYS],
            dtype=float,
        )

    @classmethod
    def from_config(cls, config) -> "DriverWeights":
        """Build from a loaded Config."""
        initial = config.get("stock_gold.initial_weights")
        signs = config.get("stock_gold.driver_signs")
        return cls(
            liquidity_credit_impulse=float(initial["liquidity_credit_impulse"]),
            innovation_growth=float(initial["innovation_growth"]),
            capital_cycle_currency_stability=float(initial["capital_cycle_currency_stability"]),
            signs={key: float(signs[key]) for key in DRIVER_KEYS},
        )


def driver_terms(
    output: np.ndarray,
    output_growth: np.ndarray,
    real_capital_growth: np.ndarray,
    financial_capital: np.ndarray,
    financial_capital_growth: np.ndarray,
    financial_capital_acceleration: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return the three unweighted driver terms.

    Derivatives are passed in rather than differenced here, so that the smoothing choice stays a
    single documented decision in the calibration layer instead of being repeated per module.

    Args:
        output: Y.
        output_growth: Y_dot.
        real_capital_growth: K_R_dot.
        financial_capital: K_I.
        financial_capital_growth: K_I_dot.
        financial_capital_acceleration: K_I_ddot.

    Returns:
        The three terms keyed by driver, before weights and signs.

    Raises:
        StockGoldError: If the inputs do not share a shape, or if a denominator vanishes anywhere.
    """
    arrays = {
        "output": np.asarray(output, dtype=float),
        "output_growth": np.asarray(output_growth, dtype=float),
        "real_capital_growth": np.asarray(real_capital_growth, dtype=float),
        "financial_capital": np.asarray(financial_capital, dtype=float),
        "financial_capital_growth": np.asarray(financial_capital_growth, dtype=float),
        "financial_capital_acceleration": np.asarray(financial_capital_acceleration, dtype=float),
    }
    shapes = {name: array.shape for name, array in arrays.items()}
    if len(set(shapes.values())) != 1:
        raise StockGoldError(f"all inputs must share a shape, got {shapes}")

    y = arrays["output"]
    k_i = arrays["financial_capital"]
    if np.any(y == 0.0):
        raise StockGoldError("driver one is undefined where Y is zero")
    if np.any(k_i == 0.0):
        raise StockGoldError("drivers two and three are undefined where K_I is zero")

    return {
        "liquidity_credit_impulse": arrays["financial_capital_acceleration"] / y,
        "innovation_growth": arrays["output_growth"] / k_i,
        # The numerator is the time derivative of the unsecured-asset gap of section 0.4.
        "capital_cycle_currency_stability": (
            arrays["real_capital_growth"] + arrays["financial_capital_growth"]
            - arrays["output_growth"]
        )
        / k_i,
    }


@dataclass
class StockGoldResult:
    """The modelled ratio path and its decomposition.

    Attributes:
        periods: The period labels.
        contributions: Signed, weighted contribution of each driver to R_dot.
        ratio_change: R_dot, the sum of the contributions.
        gold_over_equity: The integrated R path, anchored as configured.
        stock_to_gold: The reciprocal, which is what the brief asks for.
        dominant_driver: The driver with the largest absolute contribution at each period.
        stance: The asset stance the dominant driver selects at each period.
        anchor_period: The period at which the ratio was anchored.
        anchor_value: The value the ratio was anchored to.
        quantity_equation_valid: Whether capital saturation is below the ceiling above which the
            quantity equation loses validity, per period. Where it is false, driver three is expected
            to dominate.
        notes: Anything a reader must know.
    """

    periods: np.ndarray
    contributions: dict[str, np.ndarray]
    ratio_change: np.ndarray
    gold_over_equity: np.ndarray
    stock_to_gold: np.ndarray
    dominant_driver: list[str]
    stance: list[AssetStance]
    anchor_period: object
    anchor_value: float
    quantity_equation_valid: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """The label every projected path must carry, per brief section 6."""
        return "illustrative, model-derived"


def evaluate(
    periods: Sequence[object],
    terms: Mapping[str, np.ndarray],
    weights: DriverWeights,
    anchor_period: object,
    anchor_value: float = 1.0,
    capital_saturation: np.ndarray | None = None,
    quantity_equation_validity_ceiling: float | None = None,
) -> StockGoldResult:
    """Evaluate the ratio path from the driver terms.

    `R_dot` is the signed weighted sum of the three terms. The level is recovered by cumulative
    integration anchored at `anchor_period`, because the differential equation fixes the change and
    not the level. The anchor is configuration and is reported in the result, per the brief's
    requirement that it not be buried.

    Args:
        periods: The period labels, normally years.
        terms: The three unweighted driver terms, from driver_terms.
        weights: The weights and signs.
        anchor_period: The period at which the level is pinned. The framework's calibration is
            anchored around 2019.
        anchor_value: The value of the gold-over-equity ratio at the anchor. Defaults to one, which
            makes the path a ratio relative to the anchor rather than a price level.
        capital_saturation: Total capital over output, used only for the validity check.
        quantity_equation_validity_ceiling: The saturation above which the quantity equation loses
            validity and currency stability is lost.

    Returns:
        The result.

    Raises:
        StockGoldError: If a driver term is missing, the shapes disagree, or the anchor is absent.
    """
    period_array = np.asarray(list(periods))
    missing = [key for key in DRIVER_KEYS if key not in terms]
    if missing:
        raise StockGoldError(f"missing driver terms: {', '.join(missing)}")

    # Check the lengths before stacking, so a mismatch reports which driver is wrong rather than
    # surfacing as a numpy concatenation error.
    lengths = {key: np.asarray(terms[key], dtype=float).shape for key in DRIVER_KEYS}
    if len({shape for shape in lengths.values()}) != 1:
        raise StockGoldError(f"driver terms must share a shape, got {lengths}")
    stacked = np.vstack([np.asarray(terms[key], dtype=float) for key in DRIVER_KEYS])
    if stacked.shape[1] != period_array.size:
        raise StockGoldError(
            f"driver terms have length {stacked.shape[1]} but {period_array.size} periods were given"
        )

    matches = np.flatnonzero(period_array == anchor_period)
    if matches.size == 0:
        raise StockGoldError(
            f"anchor period {anchor_period!r} is not in the period range "
            f"{period_array[0]!r} to {period_array[-1]!r}. The anchor is configuration "
            f"(stock_gold.calibration_anchor_year) and must fall inside the calibration window."
        )
    anchor_index = int(matches[0])

    signed = weights.as_array()
    contributions = {
        key: signed[position] * stacked[position] for position, key in enumerate(DRIVER_KEYS)
    }
    ratio_change = np.sum([contributions[key] for key in DRIVER_KEYS], axis=0)

    # Integrate the change into a level. Cumulative trapezoidal integration over the period spacing,
    # then shift so the anchor takes the anchor value.
    if np.issubdtype(period_array.dtype, np.number):
        spacing = np.asarray(period_array, dtype=float)
    else:
        spacing = np.arange(period_array.size, dtype=float)
    level = np.concatenate(([0.0], np.cumsum(np.diff(spacing) * (ratio_change[:-1] + ratio_change[1:]) / 2.0)))
    gold_over_equity = level - level[anchor_index] + float(anchor_value)

    notes: list[str] = []
    if np.any(gold_over_equity <= 0.0):
        notes.append(
            "the integrated gold-over-equity ratio reaches zero or below at least once, so the "
            "reciprocal stock-to-gold path is undefined there. This normally means the weights are "
            "uncalibrated or the anchor value is too small relative to the integrated change."
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        stock_to_gold = np.where(gold_over_equity != 0.0, 1.0 / gold_over_equity, np.nan)

    absolute = np.vstack([np.abs(contributions[key]) for key in DRIVER_KEYS])
    dominant_index = np.argmax(absolute, axis=0)
    dominant = [DRIVER_KEYS[int(i)] for i in dominant_index]
    stance = [DRIVER_STANCE[key] for key in dominant]

    validity: np.ndarray | None = None
    if capital_saturation is not None and quantity_equation_validity_ceiling is not None:
        saturation = np.asarray(capital_saturation, dtype=float)
        if saturation.shape != period_array.shape:
            raise StockGoldError(
                f"capital_saturation has shape {saturation.shape}, expected {period_array.shape}"
            )
        validity = saturation < float(quantity_equation_validity_ceiling)
        if not validity.all():
            notes.append(
                f"capital saturation exceeds the quantity-equation validity ceiling of "
                f"{quantity_equation_validity_ceiling} in "
                f"{int((~validity).sum())} of {validity.size} periods. Driver three is expected to "
                f"dominate there, and currency stability is the binding consideration."
            )

    return StockGoldResult(
        periods=period_array,
        contributions=contributions,
        ratio_change=ratio_change,
        gold_over_equity=gold_over_equity,
        stock_to_gold=stock_to_gold,
        dominant_driver=dominant,
        stance=stance,
        anchor_period=anchor_period,
        anchor_value=float(anchor_value),
        quantity_equation_valid=validity,
        notes=notes,
    )


def dominant_driver_summary(result: StockGoldResult) -> dict[str, object]:
    """Summarise the current dominant driver and stance, for the per-economy brief."""
    if not result.dominant_driver:
        raise StockGoldError("the result carries no periods")
    return {
        "period": result.periods[-1],
        "dominant_driver": result.dominant_driver[-1],
        "stance": result.stance[-1].value,
        "contributions": {
            key: float(values[-1]) for key, values in result.contributions.items()
        },
        "ratio_change": float(result.ratio_change[-1]),
        "gold_over_equity": float(result.gold_over_equity[-1]),
        "stock_to_gold": float(result.stock_to_gold[-1]),
        "anchor_period": result.anchor_period,
        "label": result.label,
    }
