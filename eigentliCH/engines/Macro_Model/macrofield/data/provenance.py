"""Provenance records and the series type that carries them.

Brief section 2 requires that every loaded series carry a provenance record (source, identifier, URL,
retrieval date, units, currency, and any transformation) and that these be written to the data
manifest. This module defines that record and the `Series` wrapper that keeps a value inseparable from
its origin.

The design choice worth stating: provenance is not metadata bolted onto a `pandas.Series`, it is a
required constructor argument. A series cannot exist in this programme without one. That is what makes
the guarantee in section 2 enforceable rather than aspirational, and it is why every transformation
returns a new `Series` with the transformation appended to its log rather than mutating in place.

Currency and real-versus-nominal consistency is carried in the record and checked by
`macrofield.data.loaders`, so that adding a nominal series to a real one, or a euro series to a dollar
one, fails loudly instead of producing a plausible number.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


class Basis(enum.Enum):
    """Whether a series is measured in nominal or real terms, or is unitless.

    `UNKNOWN` exists so that a source which does not state its basis can still be loaded, but it is
    rejected by the consistency checks rather than assumed to match whatever it is combined with.
    """

    NOMINAL = "nominal"
    REAL = "real"
    #: Ratios, shares, rates and index levels, which have no nominal or real basis.
    UNITLESS = "unitless"
    UNKNOWN = "unknown"


class Frequency(enum.Enum):
    """Observation frequency of a series."""

    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    DAILY = "daily"

    @property
    def per_year(self) -> float:
        """Observations per year, used by the cycle module's sampling rate."""
        return {
            Frequency.ANNUAL: 1.0,
            Frequency.QUARTERLY: 4.0,
            Frequency.MONTHLY: 12.0,
            Frequency.DAILY: 365.25,
        }[self]


class Valuation(enum.Enum):
    """How a monetary series was converted across currencies.

    This exists because of a hazard that the currency and basis checks alone do not catch. Penn World
    Table capital stocks are in 2017 US dollars at current purchasing-power parities, and World Bank
    constant-price GDP is in 2015 US dollars at market exchange rates. Both are real, both are in US
    dollars, so both pass the currency and basis checks, yet a ratio built from one of each is
    meaningless. PPP and market-rate conversions differ by a factor of well over two for some
    economies.
    """

    #: Converted at market exchange rates.
    MARKET = "market_exchange_rate"
    #: Converted at purchasing-power parities.
    PPP = "purchasing_power_parity"
    #: Expressed in the economy's own currency, so no conversion applies.
    DOMESTIC = "domestic_currency"
    #: Not a monetary series.
    NOT_APPLICABLE = "not_applicable"


class Reliability(enum.Enum):
    """How far a series can be trusted as a published observation.

    This is the mechanism that keeps computed or filled values out of the model inputs unless a caller
    has explicitly opted into them. See `macrofield.data.integrity`.
    """

    #: Published by the named source, unmodified apart from logged unit conversions.
    PUBLISHED = "published"
    #: Computed by this programme from published inputs, by a documented method. The perpetual
    #: inventory extension of the capital stock is the main example.
    DERIVED = "derived"
    #: Contains at least one value produced by interpolation. Never silent: the method and the filled
    #: positions are recorded.
    INTERPOLATED = "interpolated"
    #: Placeholder or test data. Must never reach a model input, and the integrity check enforces that.
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class Transformation:
    """One recorded step applied to a series.

    Attributes:
        operation: A short name, for example "rebase_currency" or "perpetual_inventory_extension".
        detail: What was done, in enough detail to reproduce it.
        applied_on: When it was applied.
    """

    operation: str
    detail: str
    applied_on: dt.date = field(default_factory=dt.date.today)

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "detail": self.detail,
            "applied_on": self.applied_on.isoformat(),
        }


@dataclass(frozen=True)
class ProvenanceRecord:
    """Where a series came from and what has been done to it.

    Attributes:
        source: The publishing institution, for example "World Bank" or "BIS".
        dataset: The dataset within that source.
        identifier: The source's own series identifier, for example a World Bank indicator code.
        url: A URL from which the series can be retrieved or verified.
        retrieved_on: The date the values were pulled.
        units: The units as published, for example "current US dollars" or "percent of GDP".
        currency: ISO currency code, or None for a unitless series.
        basis: Nominal, real, unitless, or unknown.
        valuation: How the series was converted across currencies. Defaults to NOT_APPLICABLE, which
            is correct for a unitless series and is corrected below for a monetary one.
        frequency: Observation frequency.
        reliability: How far the values can be trusted as published observations.
        licence: The source's licence or terms, recorded because the README must state them.
        vintage: The data vintage or edition, where the source publishes one. Capital-stock datasets
            revise substantially between vintages, so this is not optional in practice.
        notes: Anything a reader needs in order to interpret the series correctly.
        transformations: Every step applied, in order.
    """

    source: str
    dataset: str
    identifier: str
    url: str
    retrieved_on: dt.date
    units: str
    basis: Basis
    frequency: Frequency
    currency: str | None = None
    valuation: Valuation = Valuation.NOT_APPLICABLE
    reliability: Reliability = Reliability.PUBLISHED
    licence: str | None = None
    vintage: str | None = None
    notes: tuple[str, ...] = ()
    transformations: tuple[Transformation, ...] = ()

    def __post_init__(self) -> None:
        if not self.source or not self.identifier:
            raise ValueError("a provenance record needs at least a source and an identifier")
        if self.basis is not Basis.UNITLESS and self.currency is None and self.basis is not Basis.UNKNOWN:
            # A nominal or real monetary series without a currency cannot be combined safely.
            raise ValueError(
                f"series {self.identifier!r} is {self.basis.value} but declares no currency. A "
                f"monetary series must state its currency so that combinations can be checked."
            )
        if self.currency is not None and self.valuation is Valuation.NOT_APPLICABLE:
            raise ValueError(
                f"series {self.identifier!r} declares currency {self.currency!r} but leaves valuation "
                f"as not applicable. A monetary series must say whether it was converted at market "
                f"exchange rates or at purchasing-power parities, because a ratio mixing the two is "
                f"meaningless and both otherwise look like real US dollars."
            )

    def with_transformation(self, operation: str, detail: str, **changes: Any) -> "ProvenanceRecord":
        """Return a copy with a transformation appended, and optionally other fields changed."""
        return replace(
            self,
            transformations=self.transformations + (Transformation(operation, detail),),
            **changes,
        )

    def as_dict(self) -> dict[str, Any]:
        """Render for the manifest."""
        return {
            "source": self.source,
            "dataset": self.dataset,
            "identifier": self.identifier,
            "url": self.url,
            "retrieved_on": self.retrieved_on.isoformat(),
            "units": self.units,
            "currency": self.currency,
            "basis": self.basis.value,
            "valuation": self.valuation.value,
            "frequency": self.frequency.value,
            "reliability": self.reliability.value,
            "licence": self.licence,
            "vintage": self.vintage,
            "notes": list(self.notes),
            "transformations": [t.as_dict() for t in self.transformations],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProvenanceRecord":
        """Rebuild from a manifest entry."""
        return cls(
            source=payload["source"],
            dataset=payload["dataset"],
            identifier=payload["identifier"],
            url=payload["url"],
            retrieved_on=dt.date.fromisoformat(payload["retrieved_on"]),
            units=payload["units"],
            basis=Basis(payload["basis"]),
            frequency=Frequency(payload["frequency"]),
            currency=payload.get("currency"),
            valuation=Valuation(payload.get("valuation", "not_applicable")),
            reliability=Reliability(payload.get("reliability", "published")),
            licence=payload.get("licence"),
            vintage=payload.get("vintage"),
            notes=tuple(payload.get("notes") or ()),
            transformations=tuple(
                Transformation(
                    operation=t["operation"],
                    detail=t["detail"],
                    applied_on=dt.date.fromisoformat(t["applied_on"]),
                )
                for t in payload.get("transformations") or ()
            ),
        )


@dataclass(frozen=True)
class GapReport:
    """Where a series is missing values.

    Brief section 2: gaps are reported, never silently filled.

    Attributes:
        missing_periods: The periods with no value.
        interior_gaps: Runs of missing periods that sit between two observed values. These are the
            ones that could in principle be interpolated.
        leading_missing: Count of missing periods before the first observation.
            Cannot be interpolated, only truncated.
        trailing_missing: Count of missing periods after the last observation. Cannot be interpolated,
            only extrapolated, which is a different decision and is handled explicitly by the capital
            stock extension.
        longest_interior_gap: Length of the longest interior run.
    """

    missing_periods: tuple[Any, ...]
    interior_gaps: tuple[tuple[Any, ...], ...]
    leading_missing: int
    trailing_missing: int

    @property
    def longest_interior_gap(self) -> int:
        return max((len(run) for run in self.interior_gaps), default=0)

    @property
    def has_gaps(self) -> bool:
        return bool(self.missing_periods)

    def as_dict(self) -> dict[str, Any]:
        return {
            "missing_count": len(self.missing_periods),
            "missing_periods": [str(p) for p in self.missing_periods],
            "interior_gap_count": len(self.interior_gaps),
            "longest_interior_gap": self.longest_interior_gap,
            "leading_missing": self.leading_missing,
            "trailing_missing": self.trailing_missing,
        }


@dataclass(frozen=True)
class Series:
    """A time series that cannot be separated from its provenance.

    Attributes:
        name: A short name for the quantity, for example "Y" or "K_R".
        values: The observations, indexed by period. The index is normally an integer year.
        provenance: Where the values came from and what has been done to them.
    """

    name: str
    values: pd.Series
    provenance: ProvenanceRecord

    def __post_init__(self) -> None:
        if not isinstance(self.values, pd.Series):
            raise TypeError(f"series {self.name!r} needs a pandas Series, got {type(self.values).__name__}")
        if self.values.index.has_duplicates:
            duplicates = self.values.index[self.values.index.duplicated()].unique().tolist()
            raise ValueError(f"series {self.name!r} has duplicate periods: {duplicates}")
        if not self.values.index.is_monotonic_increasing:
            raise ValueError(f"series {self.name!r} must be sorted by period")

    # --- basic properties ---

    @property
    def periods(self) -> pd.Index:
        return self.values.index

    @property
    def first_period(self) -> Any:
        return self.values.index[0] if len(self.values) else None

    @property
    def last_period(self) -> Any:
        return self.values.index[-1] if len(self.values) else None

    def to_numpy(self) -> np.ndarray:
        return self.values.to_numpy(dtype=float)

    # --- gaps ---

    def gap_report(self, expected_periods: Sequence[Any] | None = None) -> GapReport:
        """Report missing values, optionally against an expected period range.

        Args:
            expected_periods: The periods the series ought to cover. Defaults to every integer year
                between the first and last observation, which detects interior holes but not a series
                that simply starts late.
        """
        if expected_periods is None:
            if len(self.values) == 0:
                return GapReport((), (), 0, 0)
            first, last = self.values.index[0], self.values.index[-1]
            if isinstance(first, (int, np.integer)) and isinstance(last, (int, np.integer)):
                expected_periods = list(range(int(first), int(last) + 1))
            else:
                expected_periods = list(self.values.index)

        reindexed = self.values.reindex(expected_periods)
        missing_mask = reindexed.isna()
        missing = tuple(reindexed.index[missing_mask])

        observed_positions = np.flatnonzero(~missing_mask.to_numpy())
        if observed_positions.size == 0:
            return GapReport(missing, (), len(missing), 0)

        first_observed, last_observed = observed_positions[0], observed_positions[-1]
        leading = int(first_observed)
        trailing = int(len(reindexed) - 1 - last_observed)

        interior: list[tuple[Any, ...]] = []
        run: list[Any] = []
        for position in range(first_observed, last_observed + 1):
            if bool(missing_mask.iloc[position]):
                run.append(reindexed.index[position])
            elif run:
                interior.append(tuple(run))
                run = []
        if run:
            interior.append(tuple(run))

        return GapReport(missing, tuple(interior), leading, trailing)

    # --- transformations, each returning a new Series ---

    def transformed(
        self,
        values: pd.Series,
        operation: str,
        detail: str,
        **provenance_changes: Any,
    ) -> "Series":
        """Return a new series with the transformation recorded."""
        return Series(
            name=self.name,
            values=values,
            provenance=self.provenance.with_transformation(operation, detail, **provenance_changes),
        )

    def rename(self, name: str) -> "Series":
        """Return the same values under a different quantity name."""
        return Series(name=name, values=self.values, provenance=self.provenance)

    def restricted_to(self, start: Any | None = None, end: Any | None = None) -> "Series":
        """Return the series restricted to a period window, recording the restriction."""
        subset = self.values
        if start is not None:
            subset = subset[subset.index >= start]
        if end is not None:
            subset = subset[subset.index <= end]
        return self.transformed(
            subset,
            "restrict_window",
            f"restricted to periods {start if start is not None else 'start'} through "
            f"{end if end is not None else 'end'}",
        )

    def scaled(self, factor: float, detail: str, **provenance_changes: Any) -> "Series":
        """Return the series multiplied by a factor, recording why.

        Used for unit conversions such as millions to units. Currency conversion goes through
        `macrofield.data.loaders` instead, because it needs an exchange-rate series with its own
        provenance.
        """
        return self.transformed(
            self.values * float(factor),
            "scale",
            f"multiplied by {factor:g}: {detail}",
            **provenance_changes,
        )

    def as_manifest_entry(self) -> dict[str, Any]:
        """Render the series for the manifest, values excluded."""
        return {
            "quantity": self.name,
            "first_period": str(self.first_period),
            "last_period": str(self.last_period),
            "observations": int(self.values.notna().sum()),
            "gaps": self.gap_report().as_dict(),
            "provenance": self.provenance.as_dict(),
        }


def align(series: Iterable[Series], how: str = "inner") -> dict[str, pd.Series]:
    """Align several series onto a common period index.

    Args:
        series: The series to align.
        how: `inner` keeps only periods present in every series, which is the safe default for
            calibration because it guarantees no implicit filling. `outer` keeps the union and leaves
            gaps as NaN, for reporting.

    Returns:
        A mapping from quantity name to the aligned values.

    Raises:
        ValueError: If two series share a quantity name, since the result would silently drop one.
    """
    collected = list(series)
    names = [s.name for s in collected]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"cannot align series with duplicate quantity names: {sorted(duplicates)}")

    frame = pd.concat({s.name: s.values for s in collected}, axis=1, join=how)
    return {name: frame[name] for name in frame.columns}
