"""Nominal and real views of any series, and the terminology collision that has to be settled first.

Phase 6 of docs/BATTLE_PLAN.md. Directed by the author on 2026-07-28: build both views.

## The word "real" is already taken, and that is the first thing to fix

`macrofield/model/derived.py` uses `real_*` to mean **the real economy as against the financial economy**:
`real_price_level` is the price level of the real sector, derived from `P_R . H_R = Y`. That is a statement
about *which sector*, and it has nothing to do with inflation adjustment.

"Nominal against real" in the ordinary sense is a different axis entirely: whether a quantity has been
deflated. The two are orthogonal, and a financial-sector price level can perfectly well be expressed in real
terms.

So this module never says "real" without qualification. It uses:

- **sector**: `real economy` against `financial economy`. This is what `derived.py`'s prefixes mean.
- **basis**: `nominal` against `deflated`. This is what item 6 is about.

`Basis` below is the second axis only. Anything reported from here carries its basis explicitly, because a
number whose basis is ambiguous is worse than no number.

## Which deflator, and why gold is the headline

Two are offered and both are reported, because they answer different questions and the framework has a
commitment about it.

- **Gold.** Book chapter 11 computes its 172-year real-rate series with the **gold price as the deflator**,
  not CPI. That is a framework commitment rather than an implementation detail: chapter 24 argues that in a
  fiat regime gold becomes a price-of-money instrument whose nominal price reflects the loss of purchasing
  power of the issuing currency, so deflating by gold measures a quantity against money's own store of value.
  It is the headline basis here for that reason.
- **CPI.** The conventional basis, and the one an outside reader will assume. Reported alongside so the two
  can be compared rather than argued about.

## The regime caution, which is not optional

Chapter 24.3.1 records two structurally different inflation regimes: roughly **0.47 per cent a year** from
1820 to 1920 under commodity money, and **2.6 per cent a year** from 1920 to 2020 under monetary money, with
the transition somewhere between 1914 and 1971. A deflated series spanning that transition spans two regimes
and should not be read as one. `check_regime_span` says so whenever a window crosses it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

#: The two axes, named apart so they cannot be conflated. See the module docstring.
SECTOR_AXIS = "sector: the real economy against the financial economy, as in derived.py's prefixes"
BASIS_AXIS = "basis: nominal against deflated, which is what a nominal and a real view mean"

#: The inflation-regime transition of book chapter 24.3.1. A window spanning it spans two regimes.
REGIME_TRANSITION = (1914, 1971)

#: The regimes' own measured rates, for the note rather than for any computation.
REGIME_RATES = {
    "commodity_money": {"window": (1820, 1920), "annual_inflation": 0.0047},
    "monetary_money": {"window": (1920, 2020), "annual_inflation": 0.026},
}


class RealViewError(ValueError):
    """Raised when a basis cannot be produced."""


class Basis(enum.Enum):
    """Whether a quantity has been deflated, and by what.

    This is the *basis* axis only. It says nothing about which sector a quantity belongs to.
    """

    NOMINAL = "nominal"
    #: Deflated by the model's own real-economy price level, from the quantity equation of book chapter 7.
    #:
    #: This is the basis the programme can always produce, because the deflator is derived from the state
    #: rather than fetched: `derived.py` gets it from `P_R . H_R = Y`. It is also the internally consistent
    #: one, since the price level being divided out is the same object the model used to generate the
    #: series. Gold and CPI need series the data layer does not currently assemble.
    REAL_MODEL = "real_model"
    #: Deflated by the gold price. The book's own basis, chapter 11. Needs the `gold_price` series.
    REAL_GOLD = "real_gold"
    #: Deflated by consumer prices. The conventional basis. Needs the `consumer_prices` series.
    REAL_CPI = "real_cpi"

    @property
    def is_deflated(self) -> bool:
        return self is not Basis.NOMINAL

    @property
    def label(self) -> str:
        return {
            Basis.NOMINAL: "nominal",
            Basis.REAL_MODEL: "real, deflated by the model's own price level",
            Basis.REAL_GOLD: "real, gold-deflated",
            Basis.REAL_CPI: "real, CPI-deflated",
        }[self]

    @property
    def deflator_series(self) -> str | None:
        """The data-layer series this basis needs, or None where it needs none."""
        return {
            Basis.NOMINAL: None,
            Basis.REAL_MODEL: None,
            Basis.REAL_GOLD: "gold_price",
            Basis.REAL_CPI: "consumer_prices",
        }[self]

    @property
    def deflator_description(self) -> str:
        """What the deflator is, for a chart footer."""
        return {
            Basis.NOMINAL: "none",
            Basis.REAL_MODEL: "the real-economy price level derived from the quantity equation",
            Basis.REAL_GOLD: "the gold price",
            Basis.REAL_CPI: "consumer prices",
        }[self]


@dataclass
class Deflated:
    """One series on one basis.

    Attributes:
        basis: What was done to it.
        periods: The period labels.
        values: The series on this basis.
        base_period: The period the deflator was indexed to, so the level is readable.
        deflator_index: The deflator, indexed to one at `base_period`.
        notes: Anything a reader must know, including the regime caution.
    """

    basis: Basis
    periods: np.ndarray
    values: np.ndarray
    base_period: Any = None
    deflator_index: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)

    def growth(self) -> np.ndarray:
        """Period-on-period fractional change, NaN-padded at the front."""
        out = np.full(self.values.shape, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[1:] = np.where(
                self.values[:-1] != 0.0, self.values[1:] / self.values[:-1] - 1.0, np.nan
            )
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis.value,
            "label": self.basis.label,
            "deflated": self.basis.is_deflated,
            "periods": [int(p) for p in self.periods],
            "values": [None if not np.isfinite(v) else float(v) for v in self.values],
            "base_period": self.base_period,
            "notes": list(self.notes),
        }


def check_regime_span(periods: Sequence[Any]) -> list[str]:
    """Warn where a window crosses the inflation-regime transition of chapter 24.3.1.

    Not a computation, a caution. Deflating across 1914 to 1971 splices a commodity-money regime averaging
    0.47 per cent a year onto a monetary-money one averaging 2.6, and the result is one series only in the
    arithmetic sense.
    """
    years = np.asarray(list(periods), dtype=float)
    if years.size == 0:
        return []
    first, last = float(years.min()), float(years.max())
    low, high = REGIME_TRANSITION
    if first < low and last > high:
        return [
            f"this window runs {first:.0f} to {last:.0f} and so spans the whole inflation-regime "
            f"transition of {low} to {high}. Book chapter 24.3.1 measures about "
            f"{REGIME_RATES['commodity_money']['annual_inflation']:.2%} a year before it and "
            f"{REGIME_RATES['monetary_money']['annual_inflation']:.2%} after. A deflated series across it is "
            f"two regimes spliced together and should not be read as one."
        ]
    if first < high and last > low:
        return [
            f"this window overlaps the inflation-regime transition of {low} to {high}, so part of the "
            f"deflated series is on a commodity-money basis and part on a monetary-money one."
        ]
    return []


def deflate(
    periods: Sequence[Any],
    values: Sequence[float],
    deflator: Sequence[float],
    basis: Basis,
    base_period: Any = None,
) -> Deflated:
    """Express a nominal series on a deflated basis.

    The deflator is indexed to one at `base_period`, so the deflated series is in the currency of that
    period and its level is directly readable. Indexing is a multiplicative rescaling, so it changes no
    growth rate, direction or turning point of the deflated series.

    Args:
        periods: The period labels.
        values: The nominal series.
        deflator: The deflator, in any units.
        basis: Which deflated basis this is. `NOMINAL` is refused, since there is nothing to do.
        base_period: The period to index the deflator to. Defaults to the last.

    Returns:
        The deflated series.

    Raises:
        RealViewError: If the basis is nominal, the lengths disagree, the base period is absent, or the
            deflator is not positive there.
    """
    if basis is Basis.NOMINAL:
        raise RealViewError(
            "the nominal basis needs no deflator. Use `nominal_view` to wrap a series unchanged, so that "
            "its basis is still stated."
        )

    period_array = np.asarray(list(periods))
    series = np.asarray(values, dtype=float)
    index = np.asarray(deflator, dtype=float)
    if not (period_array.size == series.size == index.size):
        raise RealViewError(
            f"periods, values and deflator must share a length, got {period_array.size}, "
            f"{series.size} and {index.size}"
        )
    if period_array.size == 0:
        raise RealViewError("no periods were given")

    base = period_array[-1] if base_period is None else base_period
    matches = np.flatnonzero(period_array == base)
    if matches.size == 0:
        raise RealViewError(
            f"the base period {base!r} is not in the range {period_array[0]!r} to {period_array[-1]!r}"
        )
    position = int(matches[0])
    if not np.isfinite(index[position]) or index[position] <= 0.0:
        raise RealViewError(
            f"the deflator is {index[position]} at the base period {base!r}, so it cannot be indexed to "
            f"it. Choose a base period where the deflator is published and positive."
        )

    with np.errstate(divide="ignore", invalid="ignore"):
        indexed = index / index[position]
        deflated = np.where(indexed > 0.0, series / indexed, np.nan)

    notes = [
        f"deflated by {basis.deflator_description}, indexed to one at {base!r}, so the level is in "
        f"{base!r} terms.",
    ]
    if basis is Basis.REAL_MODEL:
        notes.append(
            "the deflator is the model's own real-economy price level, from the quantity equation of book "
            "chapter 7. That makes this basis internally consistent, since the price level divided out is "
            "the same object the model used to generate the series, but it is a model quantity rather than "
            "an observed one: it is not CPI and should not be quoted as though it were."
        )
    if basis is Basis.REAL_GOLD:
        notes.append(
            "gold is the book's own deflator, chapter 11, on the argument of chapter 24 that in a fiat "
            "regime gold's nominal price measures the issuing currency's loss of purchasing power. It is "
            "not the conventional basis and a reader expecting CPI should be told which this is."
        )
    notes.extend(check_regime_span(period_array))

    return Deflated(
        basis=basis,
        periods=period_array,
        values=deflated,
        base_period=base,
        deflator_index=indexed,
        notes=notes,
    )


def nominal_view(periods: Sequence[Any], values: Sequence[float]) -> Deflated:
    """Wrap a series unchanged, so that even the nominal view carries its basis explicitly."""
    period_array = np.asarray(list(periods))
    series = np.asarray(values, dtype=float)
    if period_array.size != series.size:
        raise RealViewError(
            f"periods and values must share a length, got {period_array.size} and {series.size}"
        )
    return Deflated(
        basis=Basis.NOMINAL,
        periods=period_array,
        values=series,
        notes=["as published, undeflated. Not comparable across periods in purchasing-power terms."],
    )


def both_views(
    periods: Sequence[Any],
    values: Sequence[float],
    model_price_level: Sequence[float] | None = None,
    gold: Sequence[float] | None = None,
    consumer_prices: Sequence[float] | None = None,
    base_period: Any = None,
) -> dict[str, Deflated]:
    """The nominal view and every deflated view the supplied deflators allow.

    The nominal reading is the primary one and is always present; each deflated view is an **overlay** on it.
    A deflator that is absent produces no view rather than a fallback: substituting one deflator for another
    would change what the number means while leaving its label intact.

    Returns:
        Keyed by `Basis.value`, always including `nominal`.
    """
    views: dict[str, Deflated] = {Basis.NOMINAL.value: nominal_view(periods, values)}
    for basis, deflator in (
        (Basis.REAL_MODEL, model_price_level),
        (Basis.REAL_GOLD, gold),
        (Basis.REAL_CPI, consumer_prices),
    ):
        if deflator is None:
            continue
        views[basis.value] = deflate(periods, values, deflator, basis, base_period=base_period)
    return views


def deflate_rate(nominal_rate: Sequence[float], deflator_rate: Sequence[float]) -> np.ndarray:
    """Convert a nominal growth rate to a real one, exactly rather than by subtraction.

    `(1 + n) / (1 + d) - 1`, not `n - d`. The difference is second-order and therefore negligible at low
    rates and material at high ones, which is precisely the hyperinflationary case the framework cares
    about: at 100 per cent inflation the subtraction is wrong by a factor of two.
    """
    nominal = np.asarray(nominal_rate, dtype=float)
    deflator = np.asarray(deflator_rate, dtype=float)
    if nominal.shape != deflator.shape:
        raise RealViewError(
            f"the two rate series must share a shape, got {nominal.shape} and {deflator.shape}"
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(deflator != -1.0, (1.0 + nominal) / (1.0 + deflator) - 1.0, np.nan)
