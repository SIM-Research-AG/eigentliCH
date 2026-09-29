"""Contracts: every model datafeed consumes or produces.

``datafeed`` owns ``Panel``; downstream engines (honi, macrofield, cycle) mirror it. Every
model is frozen and forbids extra fields. Collections are tuples. Missing values travel as
``None`` and are flagged ``missing``; nothing on the wire is ever an invented number.

A **snapshot** is immutable: once written, its cells never change, and its checksum is the
sha256 of its full panel in canonical JSON. A different content is a different snapshot.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSIONS: dict[str, str] = {
    "Panel": "panel@1.1.0",
    "PanelRequest": "panel-request@1.0.0",
    "SeriesDefinition": "series-definition@1.0.0",
    "Snapshot": "snapshot@1.2.0",
    "SnapshotIn": "snapshot-in@1.1.0",
    "CoverageReport": "coverage@1.0.0",
    "Calibration": "datafeed-calibration@1.0.0",
    "Country": "country@1.0.0",
    "SeriesSpec": "series-spec@1.1.0",
    "ImportConversion": "import-conversion@1.0.0",
}

CellFlag = Literal["observed", "carried", "missing"]
Frequency = Literal["M"]
FillMode = Literal["level", "rate", "share"]

_MONTH_END = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-\d{2}$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def month_index(date: str) -> int:
    return int(date[:4]) * 12 + int(date[5:7]) - 1


def _check_month_ends(dates: tuple[str, ...]) -> tuple[str, ...]:
    for d in dates:
        if not _MONTH_END.match(d):
            raise ValueError(f"date {d!r} is not YYYY-MM-DD")
    for a, b in zip(dates, dates[1:]):
        if month_index(b) - month_index(a) != 1:
            raise ValueError("dates must be consecutive month ends")
    return dates


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class SourceSpan(_Frozen):
    """A run of cells that came from one source. ``first``/``last`` are dates on the axis."""

    source: str = Field(min_length=1)
    first: str
    last: str


class PanelSeries(_Frozen):
    country: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    unit: str = ""
    values: tuple[Optional[float], ...]
    flags: tuple[CellFlag, ...]
    source_spans: tuple[SourceSpan, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "PanelSeries":
        if len(self.flags) != len(self.values):
            raise ValueError("flags and values differ in length")
        for value, flag in zip(self.values, self.flags):
            if (value is None) != (flag == "missing"):
                raise ValueError("a cell is missing exactly when its value is null")
            if value is not None and not math.isfinite(value):
                raise ValueError("values must be finite or null")
        return self


class Panel(_Frozen):
    """Aligned monthly panel for one snapshot. Served by ``GET /panel``."""

    contract_version: Literal["panel@1.1.0"] = "panel@1.1.0"
    snapshot_id: str = Field(min_length=1)
    as_of: str
    freq: Frequency = "M"
    #: The source a cell comes from unless a span says otherwise.
    primary_source: str
    dates: tuple[str, ...] = Field(min_length=1)
    series: tuple[PanelSeries, ...]

    @field_validator("dates")
    @classmethod
    def _dates(cls, dates: tuple[str, ...]) -> tuple[str, ...]:
        return _check_month_ends(dates)

    @model_validator(mode="after")
    def _aligned(self) -> "Panel":
        axis = {d: i for i, d in enumerate(self.dates)}
        seen: set[tuple[str, str]] = set()
        for s in self.series:
            if len(s.values) != len(self.dates):
                raise ValueError(f"{s.country}/{s.series_id} is not aligned to the date axis")
            if (s.country, s.series_id) in seen:
                raise ValueError(f"{s.country}/{s.series_id} appears twice")
            seen.add((s.country, s.series_id))
            covered = [0] * len(self.dates)
            for span in s.source_spans:
                if span.first not in axis or span.last not in axis or axis[span.first] > axis[span.last]:
                    raise ValueError(f"{s.country}/{s.series_id}: span {span.first}..{span.last} is off the axis")
                for i in range(axis[span.first], axis[span.last] + 1):
                    covered[i] += 1
            for i, v in enumerate(s.values):
                if v is not None and covered[i] != 1:
                    raise ValueError(f"{s.country}/{s.series_id}: cell {self.dates[i]} needs exactly one source span")
        return self


class PanelRequest(_Frozen):
    """What a consumer asks for. Body of ``POST /run``; query of ``GET /panel``."""

    snapshot_id: str = Field(min_length=1)
    series: tuple[str, ...] = ()           # empty: all
    countries: tuple[str, ...] = ()        # empty: all
    freq: Frequency = "M"
    start: Optional[str] = None            # YYYY-MM-DD, inclusive
    end: Optional[str] = None

    @field_validator("start", "end")
    @classmethod
    def _date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _MONTH_END.match(v):
            raise ValueError("start and end are YYYY-MM-DD")
        return v


# ---------------------------------------------------------------------------
# Registry (database tables `country` and `series`)
# ---------------------------------------------------------------------------

class Country(_Frozen):
    """A country datafeed may carry. ``matlab`` is its field name in M_TS.mat, if any."""

    code: str = Field(min_length=2, max_length=3)
    name: str = Field(min_length=1)
    iso3: str = Field(min_length=3, max_length=3)
    matlab: Optional[str] = None


class SeriesSpec(_Frozen):
    """A series datafeed may carry, independent of country."""

    series_id: str = Field(min_length=1)
    category: str
    unit: str
    period: str
    indices: tuple[str, ...] = ()
    #: M_TS sheet and 1-based column: the row-position contract, used only by the importer.
    matlab_sheet: Optional[str] = None
    matlab_column: Optional[int] = None
    #: An interior 0.0 is a plausible print (rates, balances); elsewhere it is a gap.
    zero_is_a_value: bool = False
    #: What the series measures, in plain language.
    description: str = ""


class ImportConversion(_Frozen):
    """What the MATLAB importer did to one series of one snapshot."""

    country: str
    series_id: str
    nan: int
    leading_zero: int
    trailing_zero: int
    interior_zero: int
    placeholder: int = 0


# ---------------------------------------------------------------------------
# Series definitions and snapshots
# ---------------------------------------------------------------------------

class SeriesDefinition(_Frozen):
    """One series for one country in one snapshot: what it is and where it came from."""

    series_id: str
    country: str
    category: str
    unit: str
    currency: str
    magnitude: float
    period: str
    pull_code: str
    field: str
    source: str
    description: str
    indices: tuple[str, ...] = ()


class FillRecord(_Frozen):
    """One attempted public-source fill: the fit, the verdict and what it changed."""

    country: str
    series_id: str
    source: str
    mode: FillMode
    anchor: str
    fx: bool
    overlap_years: int
    scale: Optional[float]
    offset: Optional[float]
    deviation: Optional[float]
    tolerance: float
    accepted: bool
    reason: str
    years_filled: tuple[int, ...]
    cells_observed: int
    cells_carried: int
    #: The stored public responses the fit used (PUB-...), so the fill can be re-derived.
    fetch_ids: tuple[str, ...] = ()
    #: Primary cells removed before the fill (share mode with replace only).
    cells_replaced: int = 0
    note: str = ""


MarketAction = Literal["correct", "series", "fill"]


class MarketRecord(_Frozen):
    """One step of the market layer (DF-18): a unit correction, a public series or a fill.

    ``correct`` rescales primary cells whose sheet scale factor is known to be wrong;
    ``series`` adds a series whose primary source is public (no Bloomberg equivalent);
    ``fill`` puts a public value into a missing primary cell, only if the monthly fit on the
    overlap holds. Every one, applied or refused, is on the manifest.
    """

    action: MarketAction
    country: str
    series_id: str
    source: str
    factor: Optional[float] = None
    overlap_months: int = 0
    scale: Optional[float] = None
    deviation: Optional[float] = None
    tolerance: Optional[float] = None
    accepted: bool
    reason: str
    cells_written: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    #: The stored public responses used (MKT-...), so the step can be re-derived offline.
    fetch_ids: tuple[str, ...] = ()
    note: str = ""


class Snapshot(_Frozen):
    """The manifest. Immutable once written."""

    contract_version: Literal["snapshot@1.0.0", "snapshot@1.1.0", "snapshot@1.2.0"] = "snapshot@1.2.0"
    snapshot_id: str
    parent_id: Optional[str]
    source: str
    primary_source: str
    as_of: str
    built_at: str
    calibration_version: str
    first_date: str
    last_date: str
    countries: tuple[str, ...]
    series: tuple[str, ...]
    cells_present: int
    checksum: str
    note: str = ""
    fills: tuple[FillRecord, ...] = ()
    market: tuple[MarketRecord, ...] = ()


class CellIn(_Frozen):
    date: str
    value: float
    flag: Literal["observed", "carried"]
    source: str


class SeriesIn(_Frozen):
    definition: SeriesDefinition
    cells: tuple[CellIn, ...]


class SnapshotIn(_Frozen):
    """Body of ``POST /snapshots``: everything a snapshot is made of."""

    snapshot_id: str
    parent_id: Optional[str] = None
    source: str
    primary_source: str
    as_of: str
    first_date: str
    last_date: str
    note: str = ""
    series: tuple[SeriesIn, ...]
    fills: tuple[FillRecord, ...] = ()
    market: tuple[MarketRecord, ...] = ()

    @field_validator("snapshot_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("snapshot_id may hold letters, digits and _ . : - only (URL-safe)")
        return v

    @model_validator(mode="after")
    def _cells_on_axis(self) -> "SnapshotIn":
        lo, hi = month_index(self.first_date), month_index(self.last_date)
        if lo > hi:
            raise ValueError("first_date is after last_date")
        for s in self.series:
            seen = set()
            for c in s.cells:
                if not _MONTH_END.match(c.date) or not lo <= month_index(c.date) <= hi:
                    raise ValueError(f"{s.definition.country}/{s.definition.series_id}: {c.date} is off the axis")
                if c.date in seen:
                    raise ValueError(f"{s.definition.country}/{s.definition.series_id}: {c.date} twice")
                if not math.isfinite(c.value):
                    raise ValueError("cell values must be finite")
                seen.add(c.date)
        return self


class CoverageRow(_Frozen):
    country: str
    series_id: str
    months: int
    observed: int
    carried: int
    missing: int
    from_public_sources: int


class PlausibilityFinding(_Frozen):
    country: str
    check: str
    detail: str


class CoverageReport(_Frozen):
    contract_version: Literal["coverage@1.0.0"] = "coverage@1.0.0"
    snapshot_id: str
    rows: tuple[CoverageRow, ...]
    plausibility: tuple[PlausibilityFinding, ...] = ()


# ---------------------------------------------------------------------------
# Calibration: alignment, carry-forward and fill acceptance rules
# ---------------------------------------------------------------------------

class Calibration(_Frozen):
    contract_version: Literal["datafeed-calibration@1.0.0"] = "datafeed-calibration@1.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    freq: Frequency = "M"
    #: An annual public-source value is placed at December and carried at most this many
    #: months into the following year, and only into cells that are otherwise missing.
    annual_carry_months: int = Field(default=11, ge=0, le=11)
    #: Fewest overlapping years between the primary series and a candidate before a fit
    #: is even attempted.
    min_overlap_years: int = Field(default=5, ge=2)
    #: Default acceptance: level series, largest relative deviation of the overlap ratio
    #: from the fitted scale; rate series, largest absolute residual after the fitted
    #: offset. A fill entry in config.yaml may tighten or loosen its own tolerance.
    level_tolerance: float = Field(default=0.10, gt=0)
    rate_tolerance: float = Field(default=0.01, gt=0)
    #: Plausibility bounds for household consumption / nominal GDP (reported, not fixed).
    consumption_share_bounds: tuple[float, float] = (0.2, 0.9)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: PanelRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[dict[str, str]]
    error: Optional[str]
