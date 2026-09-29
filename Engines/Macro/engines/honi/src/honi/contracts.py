"""Contracts: every model this engine consumes or produces.

The contracts are the only thing another engine may rely on, so they depend on nothing in
this package. Every model is frozen and forbids extra fields: an unknown key is a caller
error, not something to ignore. Collections are tuples, so an instance cannot be edited
after validation.

Missing values travel as ``None``. JSON has no NaN, and a missing value must stay visibly
missing all the way to the consumer (defect 9.1: missing data used to score as worst).

Matrices are always **years by countries**: ``matrix[i][j]`` is year ``years[i]`` for
country ``countries[j]``. One orientation everywhere, so no consumer has to guess.

The ``Panel`` contract is owned by ``datafeed``. It is mirrored here, as this engine reads
it, because no engine imports another engine's code. If the two ever disagree, the
datafeed engine page is the authority and this mirror is the bug.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Contract versions this engine speaks. Bump the version on any change to a model's
#: fields; consumers pin on these strings.
CONTRACT_VERSIONS: dict[str, str] = {
    "Panel": "panel@1.1.0",
    "CoverageReport(datafeed)": "coverage@1.0.0",
    "Country(datafeed)": "country@1.0.0",
    "HoNIRunRequest": "honi-run@1.0.0",
    "HoNIScores": "honi-scores@1.1.0",
    "PeerStats": "peer-stats@1.0.0",
    "HoNITrends": "honi-trends@1.0.0",
    "Calibration": "honi-calibration@1.1.0",
}

#: Printed on every artefact and in the README. House rule.
NOTICE = (
    "Model-derived research output of the Health of Nations Index. "
    "Not investment advice."
)

Sector = Literal["financial", "international", "real"]
SECTORS: tuple[Sector, ...] = ("financial", "international", "real")

#: The fifteen indices, in the published order (manual sections 4.2 to 4.4). The order is
#: presentation only; everything is addressed by name.
INDICES: dict[str, Sector] = {
    "budget_balance": "financial",
    "monetary_supply": "financial",
    "government_debt": "financial",
    "real_rate_10y": "financial",
    "market_cap": "financial",
    "external_debt_affordability": "international",
    "external_debt_exposure": "international",
    "terms_of_trade": "international",
    "import_reserves": "international",
    "corruption_freedom": "international",
    "consumption_power": "real",
    "population_growth": "real",
    "gdp_per_capita_growth": "real",
    "consumption_dependency": "real",
    "labour_force": "real",
}

Kind = Literal["ramp", "tent"]
MissingPolicy = Literal["exclude", "score_worst"]
Annualisation = Literal["year_end", "mean"]
CellFlag = Literal["observed", "carried", "missing"]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_MONTH_END = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-\d{2}$")

Number = Optional[float]
Series = tuple[Number, ...]
Matrix = tuple[Series, ...]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Consumed: Panel (owned by datafeed)
# ---------------------------------------------------------------------------

class SourceSpan(_Frozen):
    """A run of cells that came from one source (dates on the panel's axis)."""

    source: str = Field(min_length=1)
    first: str
    last: str


class PanelSeries(_Frozen):
    """One series for one country, aligned to the panel's date axis."""

    country: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    unit: str = ""
    values: Series
    flags: tuple[CellFlag, ...]
    source_spans: tuple[SourceSpan, ...] = ()

    @model_validator(mode="after")
    def _flags_match_values(self) -> "PanelSeries":
        if len(self.flags) != len(self.values):
            raise ValueError("flags and values differ in length")
        for value, flag in zip(self.values, self.flags):
            if (value is None) != (flag == "missing"):
                raise ValueError("a cell is missing exactly when its value is null")
            if value is not None and not math.isfinite(value):
                raise ValueError("values must be finite or null")
        return self


class Panel(_Frozen):
    """Aligned monthly panel for one snapshot, as served by ``datafeed`` ``GET /panel``."""

    contract_version: Literal["panel@1.1.0"] = "panel@1.1.0"
    snapshot_id: str = Field(min_length=1)
    as_of: str
    freq: Literal["M"] = "M"
    #: The source a cell comes from unless a span says otherwise.
    primary_source: str
    dates: tuple[str, ...] = Field(min_length=1)
    series: tuple[PanelSeries, ...]

    @field_validator("dates")
    @classmethod
    def _dates_are_ordered_month_ends(cls, dates: tuple[str, ...]) -> tuple[str, ...]:
        for d in dates:
            if not _MONTH_END.match(d):
                raise ValueError(f"date {d!r} is not YYYY-MM-DD")
        months = [(int(d[:4]), int(d[5:7])) for d in dates]
        for (y0, m0), (y1, m1) in zip(months, months[1:]):
            if (y1 * 12 + m1) - (y0 * 12 + m0) != 1:
                raise ValueError("dates must be consecutive month ends")
        return dates

    @model_validator(mode="after")
    def _aligned_and_unique(self) -> "Panel":
        seen: set[tuple[str, str]] = set()
        for s in self.series:
            if len(s.values) != len(self.dates):
                raise ValueError(f"{s.country}/{s.series_id} is not aligned to the date axis")
            key = (s.country, s.series_id)
            if key in seen:
                raise ValueError(f"{s.country}/{s.series_id} appears twice")
            seen.add(key)
        return self


class UpstreamCountry(_Frozen):
    """``datafeed GET /countries``: the one country registry."""

    code: str
    name: str
    iso3: str
    matlab: Optional[str] = None


class UpstreamCoverageRow(_Frozen):
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


class UpstreamCoverage(_Frozen):
    """``datafeed GET /coverage``: the gate this engine checks before every run."""

    contract_version: Literal["coverage@1.0.0"] = "coverage@1.0.0"
    snapshot_id: str
    rows: tuple[UpstreamCoverageRow, ...]
    plausibility: tuple[PlausibilityFinding, ...] = ()


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class IndexSpec(_Frozen):
    """Scoring rule for one index: transfer function, calibration triple and weight."""

    name: str
    kind: Kind
    range: tuple[float, float, float]
    weight: float = Field(gt=0)

    @model_validator(mode="after")
    def _range_is_usable(self) -> "IndexSpec":
        if self.name not in INDICES:
            raise ValueError(f"unknown index {self.name!r}")
        r1, r2, r3 = self.range
        ascending = r1 < r2 < r3
        descending = r1 > r2 > r3
        if self.kind == "tent" and not ascending:
            raise ValueError(f"{self.name}: a tent needs min < mid < max")
        if self.kind == "ramp" and not (ascending or descending):
            raise ValueError(f"{self.name}: a ramp needs a strictly monotone triple")
        return self

    @property
    def sector(self) -> Sector:
        return INDICES[self.name]


class Calibration(_Frozen):
    """A complete, versioned parameter set. Never edited; a change is a new version."""

    contract_version: Literal["honi-calibration@1.1.0"] = "honi-calibration@1.1.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    indices: tuple[IndexSpec, ...]
    sector_weights: dict[Sector, float]
    #: ``exclude`` drops a missing index and re-weights the sector (the fix for 9.1).
    #: ``score_worst`` reproduces MATLAB, where a missing index scores 1.
    missing_policy: MissingPolicy = "exclude"
    #: Fewest indices a sector needs before it is scored at all.
    min_indices_per_sector: int = Field(default=3, ge=1, le=5)
    rescale_sectors: bool = True
    rescale_national: bool = True
    trailing_window: int = Field(default=5, ge=1)
    trailing_min_obs: int = Field(default=1, ge=1)
    annualisation: Annualisation = "year_end"
    #: datafeed plausibility check -> indices to drop for a country it flags. Dropped
    #: indices are treated as missing (re-weighted) and listed in the coverage report.
    exclude_on_plausibility: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v

    @model_validator(mode="after")
    def _complete(self) -> "Calibration":
        names = [spec.name for spec in self.indices]
        if sorted(names) != sorted(INDICES):
            raise ValueError("a calibration must define each of the fifteen indices exactly once")
        if set(self.sector_weights) != set(SECTORS):
            raise ValueError("sector_weights must name financial, international and real")
        if any(w <= 0 for w in self.sector_weights.values()):
            raise ValueError("sector weights must be positive")
        if abs(sum(self.sector_weights.values()) - 1.0) > 1e-12:
            raise ValueError("sector weights must sum to 1")
        if self.trailing_min_obs > self.trailing_window:
            raise ValueError("trailing_min_obs cannot exceed trailing_window")
        for indices in self.exclude_on_plausibility.values():
            if any(i not in INDICES for i in indices):
                raise ValueError("exclude_on_plausibility names an unknown index")
        return self

    def spec(self, name: str) -> IndexSpec:
        for s in self.indices:
            if s.name == name:
                return s
        raise KeyError(name)


# ---------------------------------------------------------------------------
# Run request and run status
# ---------------------------------------------------------------------------

class Window(_Frozen):
    start_year: int = Field(ge=1900, le=2200)
    end_year: int = Field(ge=1900, le=2200)

    @model_validator(mode="after")
    def _ordered(self) -> "Window":
        if self.start_year > self.end_year:
            raise ValueError("start_year is after end_year")
        return self


class HoNIRunRequest(_Frozen):
    """Body of ``POST /run``. Omitted fields take their defaults from ``config.yaml``."""

    snapshot_id: str = Field(min_length=1)
    countries: Optional[tuple[str, ...]] = Field(default=None, min_length=2)
    window: Optional[Window] = None
    calibration_version: Optional[str] = None

    @field_validator("countries")
    @classmethod
    def _unique(cls, v: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("countries must be unique")
        return v


RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class MissingSeries(_Frozen):
    country: str
    series_id: str
    missing_months: int
    total_months: int


class DroppedSector(_Frozen):
    """A country-year where a sector lost indices, or could not be scored at all."""

    country: str
    year: int
    sector: Sector
    indices_missing: tuple[str, ...]
    scored: bool


class PublicFill(_Frozen):
    """Cells of an input series that datafeed filled from a public source."""

    country: str
    series_id: str
    source: str
    first: str
    last: str


class Exclusion(_Frozen):
    """An index dropped for a country because datafeed flagged its inputs."""

    country: str
    index: str
    reason: str


class CoverageReport(_Frozen):
    country_years: int
    index_cells: int
    index_cells_missing: int
    sectors_reweighted: int
    sectors_unscored: int
    national_unscored: int
    missing_series: tuple[MissingSeries, ...]
    dropped: tuple[DroppedSector, ...]
    public_fills: tuple[PublicFill, ...] = ()
    excluded: tuple[Exclusion, ...] = ()


class Provenance(_Frozen):
    snapshot_id: str
    as_of: str
    upstream: dict[str, str]
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: HoNI sits upstream of the Regime, so there is no regime to stamp. The field exists
    #: so that the binding rule reads the same on every artefact in the system.
    regime_id: Optional[str] = None
    label: Literal["model-derived"] = "model-derived"


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: HoNIRunRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[Provenance]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Produced: HoNIScores and PeerStats
# ---------------------------------------------------------------------------

class CountryRef(_Frozen):
    code: str
    name: str


class HoNIScores(_Frozen):
    """The artefact: every figure the engine publishes for one run, years by countries."""

    artefact_id: str
    contract_version: Literal["honi-scores@1.1.0"] = "honi-scores@1.1.0"
    notice: str = NOTICE
    years: tuple[int, ...]
    countries: tuple[CountryRef, ...]
    national: Matrix
    sectors: dict[Sector, Matrix]
    index_scores: dict[str, Matrix]
    index_raw: dict[str, Matrix]
    capital_saturation: Matrix
    coverage: CoverageReport
    provenance: Provenance

    @model_validator(mode="after")
    def _shapes(self) -> "HoNIScores":
        shape = (len(self.years), len(self.countries))
        matrices = [self.national, self.capital_saturation, *self.sectors.values(),
                    *self.index_scores.values(), *self.index_raw.values()]
        for m in matrices:
            if len(m) != shape[0] or any(len(row) != shape[1] for row in m):
                raise ValueError("every matrix must be years by countries")
        if set(self.sectors) != set(SECTORS):
            raise ValueError("all three sectors are required")
        if set(self.index_scores) != set(INDICES) or set(self.index_raw) != set(INDICES):
            raise ValueError("all fifteen indices are required")
        for m in [self.national, *self.sectors.values(), *self.index_scores.values()]:
            for row in m:
                for v in row:
                    if v is not None and not (1.0 - 1e-12 <= v <= 5.0 + 1e-12):
                        raise ValueError("scores are bounded to [1, 5]")
        return self


class IndexView(_Frozen):
    index: str
    sector: Sector
    kind: Kind
    score: Series
    raw: Series


class CountryScores(_Frozen):
    """One country out of an artefact. Assembled on read; never stored separately."""

    artefact_id: str
    country: CountryRef
    years: tuple[int, ...]
    national: Series
    sectors: dict[Sector, Series]
    indices: tuple[IndexView, ...]
    capital_saturation: Series
    notice: str = NOTICE


class PeerStatsRow(_Frozen):
    index: str
    year: int
    basis: Literal["score", "raw"]
    n: int
    min: Number
    p25: Number
    median: Number
    p75: Number
    max: Number


class PeerStats(_Frozen):
    """Cross-sectional spread per index per year, for the box plots."""

    contract_version: Literal["peer-stats@1.0.0"] = "peer-stats@1.0.0"
    artefact_id: str
    rows: tuple[PeerStatsRow, ...]


class TrendSeries(_Frozen):
    """One published series (national, a sector, capital saturation, an index score or raw
    value) summarised over the trailing window. Every tuple is by country."""

    key: str
    label: str
    basis: Literal["score", "raw", "saturation"]
    sector: Optional[Sector] = None
    index: Optional[str] = None
    latest: Series
    base: Series
    change: Series
    slope: Series
    level_z: Series
    n: tuple[int, ...]


class HoNITrends(_Frozen):
    """Trend and level of every series over a trailing window, as ``HoNI_Lite.xlsx`` showed
    them ("Trend (10y)", "Level*: z-score last 10 years"). Computed on read from an artefact;
    never stored separately."""

    contract_version: Literal["honi-trends@1.0.0"] = "honi-trends@1.0.0"
    artefact_id: str
    year: int
    window: int
    first_year: int
    base_year: int
    min_obs: int
    countries: tuple[CountryRef, ...]
    series: tuple[TrendSeries, ...]
    definitions: dict[str, str]
    notice: str = NOTICE

# ---------------------------------------------------------------------------
# Model card (GET /model): the model explained on its own data
# ---------------------------------------------------------------------------
#
# ``model-card@1.0.0`` is the same shape in every engine (each engine keeps its own copy, as
# engines share no code), so one cockpit page can show any of them: what comes in, in plain
# names; every calculation step with its formula, parameters and the numbers it produced; and
# what goes out. The engine computes every figure; the consumer only draws it.
#
# The card is a view, not a result: it is deliberately not in CONTRACT_VERSIONS, which feeds
# every artefact's idempotency key and id, so adding or changing it never changes a result.

MODEL_CARD_VERSION = "model-card@1.0.0"

ChartX = Union[int, float, str]


class ChartSeries(_Frozen):
    """One line or set of bars of a chart, aligned to the chart's ``x``. ``slot`` fixes the
    categorical colour (0 to 4), so one entity wears one colour in every chart; ``muted``
    draws a reference series in grey."""

    name: str
    y: tuple[Number, ...]
    kind: Literal["line", "bar", "markers"] = "line"
    dash: Literal["solid", "dash", "dot"] = "solid"
    slot: Optional[int] = Field(default=None, ge=0, le=4)
    muted: bool = False


class Chart(_Frozen):
    """A chart the engine has computed. ``xy``: series against ``x``. ``heatmap``: ``z`` rows
    are ``rows`` (top to bottom), columns are ``x``; with ``categories`` the cells are indices
    into it (a categorical heatmap, drawn with one colour per category)."""

    title: str
    kind: Literal["xy", "heatmap"] = "xy"
    x: tuple[ChartX, ...]
    x_label: str = ""
    y_label: str = ""
    series: tuple[ChartSeries, ...] = ()
    rows: tuple[str, ...] = ()
    z: tuple[tuple[Number, ...], ...] = ()
    categories: tuple[str, ...] = ()
    #: x from which the values are projected, not observed (drawn shaded); null if none.
    projected_from: Optional[ChartX] = None
    note: str = ""

    @model_validator(mode="after")
    def _aligned(self) -> "Chart":
        n = len(self.x)
        for s in self.series:
            if len(s.y) != n:
                raise ValueError(f"chart {self.title!r}: series {s.name!r} has {len(s.y)} values for {n} x")
        if self.kind == "heatmap":
            if len(self.z) != len(self.rows) or any(len(r) != n for r in self.z):
                raise ValueError(f"chart {self.title!r}: z must be rows by x")
        return self


class ModelInput(_Frozen):
    """One input as the engine receives it: plain name, unit, where it comes from, the data."""

    key: str
    name: str
    unit: str
    frequency: str
    source: str
    description: str
    x: tuple[ChartX, ...]
    y: tuple[Number, ...]


class Parameter(_Frozen):
    symbol: str
    name: str
    value: str


class ModelStep(_Frozen):
    """One calculation: what it does in words, the formula (LaTeX), its parameters and charts."""

    key: str
    title: str
    text: str
    formulas: tuple[str, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    charts: tuple[Chart, ...] = ()


class ModelOutputField(_Frozen):
    key: str
    name: str
    unit: str
    description: str


class EconomyOption(_Frozen):
    code: str
    name: str


class ModelCard(_Frozen):
    """``GET /model``: the model for one economy, on the data in the store today."""

    contract_version: Literal["model-card@1.0.0"] = "model-card@1.0.0"
    engine: str
    title: str
    summary: str
    engine_version: str
    calibration_version: str
    data: str
    economy: EconomyOption
    economies: tuple[EconomyOption, ...]
    inputs: tuple[ModelInput, ...]
    steps: tuple[ModelStep, ...]
    outputs: tuple[ModelOutputField, ...]
    output_charts: tuple[Chart, ...] = ()
    notes: tuple[str, ...] = ()
    notice: str = NOTICE
