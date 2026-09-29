"""Contracts: every model this engine consumes or produces.

The contracts are the only thing another engine may rely on, so they depend on nothing in
this package. Every model this engine *publishes* is frozen and forbids extra fields: an
unknown key is a caller error. Collections are tuples, so an instance cannot be edited after
validation. Missing values travel as ``None``; JSON has no NaN.

**Upstream mirrors.** ``Panel``, ``UpstreamCoverage``, ``ImportConversion`` and
``CountryRecord`` (owned by ``datafeed``) are mirrored here as this engine reads them,
because no engine imports another engine's code. The mirrors are *partial*: they name only
the fields ``mrs`` uses and ignore the rest, and they pin the upstream contract version
exactly. If a mirror and its owner ever disagree, the owner is the authority and the mirror
is the bug.

**The 25 states.** State 1 is the most cautious reading, state 25 the most aggressive, as in
MATLAB and in the Portfolio Creation Program's return profiles (``Client.ReturnDist``, 25
rows). A distribution is always 25 non-negative numbers summing to 1.

**The output.** ``MarketRiskSignal`` (``mrs-signal@1.0.0``) carries, per economy and month and
each once, the eleven sub-indicators, the four segment signals and the 25-state
distribution at zero optimism shift. ``regime_id`` is always null: ``aggregation`` issues it,
and applies optimism and the market blends (MRS-13).
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Contract versions this engine speaks. Bump the version on any change to a model's
#: fields; consumers pin on these strings.
CONTRACT_VERSIONS: dict[str, str] = {
    "MRSRunRequest": "mrs-run@2.0.0",
    "MarketRiskSignal": "mrs-signal@1.0.0",
    "Calibration": "mrs-calibration@2.0.0",
    "InputReport": "mrs-input@1.0.0",
    "Panel(datafeed)": "panel@1.1.0",
    "CoverageReport(datafeed)": "coverage@1.0.0",
    "ImportConversion(datafeed)": "import-conversion@1.0.0",
}

#: Printed on every artefact and in the README. House rule.
NOTICE = (
    "Model-derived research output of the Market Risk Signal, at zero optimism shift. The "
    "distribution is an assessment of the current environment, not a forecast. "
    "Not investment advice."
)

#: Fixed by the downstream interface (PCP return profiles have 25 rows).
N_STATES = 25

Segment = Literal["business_cycle", "investment", "market_behaviour", "market_stress"]
#: MATLAB order (Market_Signal.m, Weights.m): Macro, Fundamental, Technical, Market Stress.
SEGMENTS: tuple[Segment, ...] = ("business_cycle", "investment", "market_behaviour",
                                 "market_stress")

#: The eleven sub-indicators that feed the distribution, in the published order
#: (``Market_Signal.m``, ``Index``, without ``KeyStats``: MRS-09).
INDICATORS: tuple[str, ...] = (
    "inflation", "monetary", "consumer", "company",
    "bond", "equity",
    "trend_osc", "fear_greed",
    "global_stability", "market_stability", "monetary_uncertainty",
)

SEGMENT_INDICATORS: dict[str, tuple[str, ...]] = {
    "business_cycle": ("inflation", "monetary", "consumer", "company"),
    "investment": ("bond", "equity"),
    "market_behaviour": ("trend_osc", "fear_greed"),
    "market_stress": ("global_stability", "market_stability", "monetary_uncertainty"),
}

MissingPolicy = Literal["reweight", "fail", "matlab"]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_ARTEFACT = re.compile(r"^MRS-[0-9a-f]{16}$")

Number = Optional[float]
Distribution = tuple[float, ...]

#: Tolerance on "sums to 1". Normalisation divides once, so the error is a few ulp.
SUM_TOLERANCE = 1e-12


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Upstream(BaseModel):
    """A partial mirror of another engine's contract: read what we use, ignore the rest."""

    model_config = ConfigDict(frozen=True, extra="ignore")


def _check_distribution(d: tuple[float, ...], where: str) -> None:
    if len(d) != N_STATES:
        raise ValueError(f"{where}: a distribution has {N_STATES} states, not {len(d)}")
    if any((not math.isfinite(p)) or p < 0.0 for p in d):
        raise ValueError(f"{where}: probabilities must be finite and non-negative")
    if abs(math.fsum(d) - 1.0) > SUM_TOLERANCE:
        raise ValueError(f"{where}: a distribution must sum to 1 (sums to {math.fsum(d)!r})")


def _month_index(d: str) -> int:
    return int(d[:4]) * 12 + int(d[5:7])


# ---------------------------------------------------------------------------
# Upstream mirrors (datafeed)
# ---------------------------------------------------------------------------

CellFlag = Literal["observed", "carried", "missing"]


class SourceSpan(_Upstream):
    """A run of cells that came from one source (dates on the panel's axis)."""

    source: str
    first: str
    last: str


class PanelSeries(_Upstream):
    """One series for one country, aligned to the panel's date axis."""

    country: str
    series_id: str
    unit: str = ""
    values: tuple[Number, ...]
    flags: tuple[CellFlag, ...]
    source_spans: tuple[SourceSpan, ...] = ()

    @model_validator(mode="after")
    def _flags_match_values(self) -> "PanelSeries":
        if len(self.flags) != len(self.values):
            raise ValueError(f"{self.country}/{self.series_id}: flags and values differ in length")
        for value, flag in zip(self.values, self.flags):
            if (value is None) != (flag == "missing"):
                raise ValueError(f"{self.country}/{self.series_id}: a cell is missing exactly "
                                 "when its value is null")
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{self.country}/{self.series_id}: values must be finite or null")
        return self


class Panel(_Upstream):
    """``panel@1.1.0``: datafeed's aligned monthly panel for one snapshot (``GET /panel``)."""

    contract_version: Literal["panel@1.1.0"]
    snapshot_id: str
    as_of: str
    freq: Literal["M"]
    primary_source: str
    dates: tuple[str, ...] = Field(min_length=1)
    series: tuple[PanelSeries, ...]

    @model_validator(mode="after")
    def _aligned_and_unique(self) -> "Panel":
        if any(not _DATE.match(d) for d in self.dates):
            raise ValueError("Panel dates must be ISO dates, YYYY-MM-DD")
        months = [_month_index(d) for d in self.dates]
        if any(b - a != 1 for a, b in zip(months, months[1:])):
            raise ValueError("Panel dates must be consecutive month ends")
        seen: set[tuple[str, str]] = set()
        for s in self.series:
            if len(s.values) != len(self.dates):
                raise ValueError(f"{s.country}/{s.series_id} is not aligned to the date axis")
            if (s.country, s.series_id) in seen:
                raise ValueError(f"{s.country}/{s.series_id} appears twice")
            seen.add((s.country, s.series_id))
        return self


class UpstreamCoverageRow(_Upstream):
    country: str
    series_id: str
    months: int
    observed: int
    carried: int
    missing: int
    from_public_sources: int


class PlausibilityFinding(_Upstream):
    country: str
    check: str
    detail: str


class UpstreamCoverage(_Upstream):
    """``coverage@1.0.0``: datafeed's gate, checked before the panel is read."""

    contract_version: Literal["coverage@1.0.0"]
    snapshot_id: str
    rows: tuple[UpstreamCoverageRow, ...]
    plausibility: tuple[PlausibilityFinding, ...] = ()


class ImportConversion(_Upstream):
    """``import-conversion@1.0.0``: what datafeed's MATLAB importer did to one series.

    Needed only to rebuild MATLAB's own view of ``M_TS`` for the ``matlab`` mode: a
    ``placeholder`` count means MATLAB read that series as a constant 1.0.
    """

    country: str
    series_id: str
    nan: int
    leading_zero: int
    trailing_zero: int
    interior_zero: int
    placeholder: int = 0


class CountryRecord(_Upstream):
    """One row of datafeed's ``GET /countries``: the code and the display name."""

    code: str
    name: str


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class Edges(_Frozen):
    """The signal grid a segment reading is binned on: ``linspace(low, high, count)``
    (``Weights.m`` at zero optimism shift). The number of kernel columns equals ``count``."""

    low: float = -2.0
    high: float = 2.0
    count: int = Field(default=11, ge=2)

    @model_validator(mode="after")
    def _ordered(self) -> "Edges":
        if not self.high > self.low:
            raise ValueError("edges.high must exceed edges.low")
        return self


class BandKernel(_Frozen):
    """A binomial kernel that slides across the axis as the reading rises.

    Column ``j`` (1-based) places ``binopdf(0:n, n, p)`` on states
    ``first_state + step*(j-1)`` onwards; mass that falls off either end of the axis is
    folded onto the end state. ``Weights.m`` builds this on a 33-row padded matrix and folds
    rows 1-4 and 30-33; the result is identical.
    """

    kind: Literal["band"] = "band"
    binomial_n: int = Field(default=8, ge=1)
    binomial_p: float = Field(default=0.5, ge=0.0, le=1.0)
    first_state: int = 18
    step: int = -2


class TailKernel(_Frozen):
    """A fixed kernel on the cautious tail, switched on and scaled up as stress rises.

    Columns below ``active_from_column`` carry nothing. Column ``j >= active_from_column``
    carries ``binopdf(0:n, n, p) * (j - active_from_column + 1) ** intensity_exponent /
    intensity_divisor`` from ``first_state`` onwards (``Weights.m``: ``(j-5)^sqrt(2) / 11``).
    Its mass is therefore not 1, which is why published distributions are normalised and
    the pre-normalisation mass is kept as ``raw_mass`` (decision MRS-02).
    """

    kind: Literal["tail"] = "tail"
    binomial_n: int = Field(default=8, ge=1)
    binomial_p: float = Field(default=0.1, ge=0.0, le=1.0)
    first_state: int = 1
    active_from_column: int = Field(default=6, ge=1)
    intensity_exponent: float = math.sqrt(2.0)
    intensity_divisor: float = Field(default=11.0, gt=0.0)


Kernel = Annotated[Union[BandKernel, TailKernel], Field(discriminator="kind")]


class SegmentSpec(_Frozen):
    name: Segment
    #: ``Model_Weights`` (Controller_Test.xlsx, Market_Settings row 2).
    weight: float = Field(gt=0.0)
    kernel: Kernel


class StressThresholds(_Frozen):
    """Every threshold of ``MR_Global_Stability.m`` and ``MR_Market_Stability.m``, in the
    units of the data the calibration reads (MRS-16)."""

    #: ``abs(diff(DXY)) > 2``: index points.
    dxy_move: float = 2.0
    #: ``OIS > 0.01``: a level, decimal (ruled 27.09.2026).
    ois_level: float = 0.01
    #: ``std(diff(gold))`` over ``gold_window`` months ``> 15``: price units (local currency).
    gold_std: float = 15.0
    gold_window: int = Field(default=20, ge=2)
    #: ``movmean(dlog(banks) - dlog(index), [5 0]) < -0.01``.
    bank_vs_index: float = -0.01
    bank_window: int = Field(default=6, ge=1)
    #: ``VIX > level && diff(gradient(VIX)) > accel``. MATLAB: 20 and 2 on a decimal VIX.
    vix_level: float = 0.20
    vix_accel: float = 0.02
    #: ``abs(movmean(gradient(loan), [5 0])) > loan_move``; ``relative`` divides the
    #: gradient by the price first (MRS-16, MRS-19).
    loan_move: float = 0.005
    loan_change: Literal["price", "relative"] = "relative"
    loan_window: int = Field(default=6, ge=1)
    #: ``Output = 3*ndx``.
    flag_scale: float = 3.0


class TrendOscParams(_Frozen):
    """``MR_Trend_Osc.m``: windows of the technical indicators and the clip."""

    ema: tuple[int, int, int] = (3, 6, 12)
    sar: int = Field(default=6, ge=1)
    macd: tuple[int, int, int] = (3, 6, 12)
    momentum: int = Field(default=6, ge=1)
    roc: int = Field(default=6, ge=1)
    kst_option: Literal[1, 2, 3] = 3
    clip: float = Field(default=5.0, gt=0.0)


class MonetaryUncertaintyParams(_Frozen):
    """``MR_Monetary_Uncertainty.m``: M3 / GDP, detrended, smoothed, scaled and clipped."""

    skip: int = Field(default=5, ge=0)          # Ratio(6:end)
    window: int = Field(default=7, ge=1)        # movmean(., [6 0])
    clip: float = Field(default=3.0, gt=0.0)
    scale: float = Field(default=2.0, gt=0.0)


class IndicatorParams(_Frozen):
    """The indicator layer: which inputs, which weights, how to normalise."""

    #: ``matlab``: full-sample normalisation on MATLAB's view (gaps 0, placeholders 1.0).
    #: ``production``: data up to each month only, gaps stay gaps (module ``indicators``).
    mode: Literal["matlab", "production"]
    #: ``w_all``: leading, concurrent, lagging.
    lcl_weights: tuple[float, float, float] = (0.5, 0.25, 0.25)
    #: ``w_Biz``, ``w_Invst``, ``w_Behav``, ``w_Stress``: indicator weights within a segment.
    weights: dict[Segment, dict[str, float]]
    #: Production only: observations needed before a z-score (or trend) is published, for a
    #: transform of an input and of a combination (ruled 27.09.2026: 24 and 12).
    min_history_input: int = Field(default=24, ge=2)
    min_history_composite: int = Field(default=12, ge=2)
    fear_greed_series: Literal["volatility.fear_barometer", "volatility.skew"]
    inflation_fx_series: Literal["fx.beer", "fx.neer_broad"]
    bond_hy_series: Literal["yields.high_yield_index", "yields.high_yield_ytw"]
    thresholds: StressThresholds = StressThresholds()
    trend_osc: TrendOscParams = TrendOscParams()
    monetary_uncertainty: MonetaryUncertaintyParams = MonetaryUncertaintyParams()

    @model_validator(mode="after")
    def _weights_complete(self) -> "IndicatorParams":
        if set(self.weights) != set(SEGMENTS):
            raise ValueError("indicator weights must name each of the four segments")
        for seg, names in SEGMENT_INDICATORS.items():
            if set(self.weights[seg]) != set(names):
                raise ValueError(f"{seg} weights must name exactly {list(names)}")
            if any(w < 0 for w in self.weights[seg].values()):
                raise ValueError(f"{seg} weights must be non-negative")
        if any(w < 0 for w in self.lcl_weights):
            raise ValueError("lcl_weights must be non-negative")
        return self

    def segment_weights(self) -> dict[str, dict[str, float]]:
        return {k: dict(v) for k, v in self.weights.items()}


class Calibration(_Frozen):
    """A complete, versioned parameter set. Never edited; a change is a new version.

    No optimism: ``mrs`` publishes at zero shift and ``aggregation`` applies optimism
    (MRS-13, MRS-18). No market weights: blends are ``aggregation``'s.
    """

    contract_version: Literal["mrs-calibration@2.0.0"] = "mrs-calibration@2.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    edges: Edges = Edges()
    segments: tuple[SegmentSpec, ...]
    #: ``reweight``: a missing segment reading is dropped for that date and the present
    #: segments' weights are scaled back up to the full total; recorded in the coverage.
    #: ``fail``: any missing reading fails the run. ``matlab``: a missing reading selects
    #: column 1, as the MATLAB comparisons do with NaN (reconciliation only).
    missing_policy: MissingPolicy = "reweight"
    #: Fewest segments present on a date before that date is assessed at all.
    min_segments: int = Field(default=3, ge=1, le=4)
    indicators: IndicatorParams

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v

    @model_validator(mode="after")
    def _complete(self) -> "Calibration":
        names = [s.name for s in self.segments]
        if sorted(names) != sorted(SEGMENTS):
            raise ValueError("a calibration must define each of the four segments exactly once")
        if abs(math.fsum(s.weight for s in self.segments) - 1.0) > 1e-12:
            raise ValueError("segment weights must sum to 1")
        for s in self.segments:
            k = s.kernel
            if isinstance(k, TailKernel) and k.active_from_column > self.edges.count:
                raise ValueError(f"{s.name}: active_from_column exceeds the column count")
        return self

    def segment(self, name: str) -> SegmentSpec:
        for s in self.segments:
            if s.name == name:
                return s
        raise KeyError(name)


# ---------------------------------------------------------------------------
# Input report
# ---------------------------------------------------------------------------

class InputSeries(_Frozen):
    """One input series across economies, as datafeed's coverage report counts it."""

    series_id: str
    countries_with_data: tuple[str, ...]
    countries_without_data: tuple[str, ...]
    observed: int
    carried: int
    missing: int
    from_public_sources: int


class InputReport(_Frozen):
    """``GET /input``: the datafeed snapshot ``mrs`` reads, checked series by series.

    Built from datafeed's coverage report (the gate) and a read of the panel itself, so it
    proves the live panel is served and valid, and fingerprints it.
    """

    contract_version: Literal["mrs-input@1.0.0"] = "mrs-input@1.0.0"
    snapshot_id: str
    as_of: str
    first_date: str
    last_date: str
    months: int
    countries: tuple[str, ...]
    panel_sha256: str
    series: tuple[InputSeries, ...]
    plausibility: tuple[str, ...] = ()
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# Run request and status
# ---------------------------------------------------------------------------

class MRSRunRequest(_Frozen):
    """``mrs-run@2.0.0``. ``None`` takes the default from ``config.yaml``
    (``upstream.snapshot_id``, ``calibration.active``)."""

    snapshot_id: Optional[str] = Field(default=None, min_length=1)
    calibration_version: Optional[str] = None


RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class RunSummary(_Frozen):
    """One row of ``GET /runs``, newest first."""

    run_id: str
    status: RunState
    artefact_id: Optional[str]
    snapshot_id: str
    calibration_version: str
    finished_at: Optional[str]


class EconomyCoverage(_Frozen):
    code: str
    dates_assessed: int
    #: Dates left unassessed: fewer than ``min_segments`` segments present.
    dates_unassessed: int
    #: First and last assessed month; ``None`` if the economy is never assessed.
    first_assessed: Optional[str]
    last_assessed: Optional[str]
    #: Segment -> dates it is missing (its weight re-distributed where the date is assessed).
    segment_gaps: dict[Segment, int]
    #: Indicator -> dates it is missing (every one of its inputs missing, or warm-up).
    indicator_gaps: dict[str, int]
    #: Input series the calibration reads that hold no observation at all for this economy.
    inputs_missing: tuple[str, ...]


class CoverageReport(_Frozen):
    economies: tuple[EconomyCoverage, ...]
    indicator_mode: Literal["matlab", "production"]
    missing_policy: MissingPolicy
    min_segments: int
    #: Input series the calibration reads (datafeed ids).
    inputs: tuple[str, ...]


class Provenance(_Frozen):
    snapshot_id: str
    as_of: str
    upstream: dict[str, str]
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: Always null: ``aggregation`` issues the regime_id (MRS-13).
    regime_id: None = None
    label: Literal["model-derived"] = "model-derived"


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    snapshot_id: str
    calibration_version: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: MRSRunRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[Provenance]
    error: Optional[str]


# ---------------------------------------------------------------------------
# The MarketRiskSignal
# ---------------------------------------------------------------------------

class EconomySignal(_Frozen):
    code: str
    name: str
    #: Sub-indicator -> value per date (``INDICATORS``); ``None`` where missing.
    indicators: dict[str, tuple[Number, ...]]
    #: Segment -> reading per date; ``None`` where missing. The three band segments are
    #: z-scores, market stress the weighted flag sum (higher always more cautious).
    segments: dict[Segment, tuple[Number, ...]]
    #: 25 probabilities per date, summing to 1, at zero optimism shift; ``None`` where
    #: unassessed.
    distribution: tuple[Optional[Distribution], ...]
    #: Total kernel mass before normalisation (MRS-02); ``None`` where unassessed.
    raw_mass: tuple[Number, ...]
    #: Modal state (1 cautious .. 25 aggressive), ties to the more cautious (MRS-08).
    state: tuple[Optional[int], ...]


class MarketRiskSignal(_Frozen):
    contract_version: Literal["mrs-signal@1.0.0"] = "mrs-signal@1.0.0"
    artefact_id: str
    n_states: Literal[25] = N_STATES
    dates: tuple[str, ...]
    indicator_names: tuple[str, ...] = INDICATORS
    segment_names: tuple[Segment, ...] = SEGMENTS
    economies: tuple[EconomySignal, ...]
    coverage: CoverageReport
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _shape(self) -> "MarketRiskSignal":
        if self.artefact_id != "MRS-draft" and not _ARTEFACT.match(self.artefact_id):
            raise ValueError("artefact_id is MRS- and 16 hex digits")
        if any(not _DATE.match(d) for d in self.dates):
            raise ValueError("dates must be ISO dates, YYYY-MM-DD")
        months = [_month_index(d) for d in self.dates]
        if any(b - a != 1 for a, b in zip(months, months[1:])):
            raise ValueError("dates must be strictly increasing consecutive month ends")
        if tuple(self.indicator_names) != INDICATORS or tuple(self.segment_names) != SEGMENTS:
            raise ValueError("indicator_names and segment_names are fixed")
        n = len(self.dates)
        codes = [e.code for e in self.economies]
        if len(set(codes)) != len(codes):
            raise ValueError("an economy is listed twice")
        for e in self.economies:
            if set(e.indicators) != set(INDICATORS):
                raise ValueError(f"{e.code}: indicators must be exactly {list(INDICATORS)}")
            if set(e.segments) != set(SEGMENTS):
                raise ValueError(f"{e.code}: segments must be exactly {list(SEGMENTS)}")
            for label, seq in (("state", e.state), ("distribution", e.distribution),
                               ("raw_mass", e.raw_mass),
                               *((f"indicators.{k}", v) for k, v in e.indicators.items()),
                               *((f"segments.{k}", v) for k, v in e.segments.items())):
                if len(seq) != n:
                    raise ValueError(f"{e.code}.{label} is not aligned to dates")
            for label, seq in list(e.indicators.items()) + list(e.segments.items()):
                if any(v is not None and not math.isfinite(v) for v in seq):
                    raise ValueError(f"{e.code}.{label} carries a non-finite value")
            for i, (s, d, m) in enumerate(zip(e.state, e.distribution, e.raw_mass)):
                if not ((s is None) == (d is None) == (m is None)):
                    raise ValueError(f"{e.code}[{i}]: state, distribution and raw_mass must be "
                                     "missing together")
                if s is None:
                    continue
                if not 1 <= s <= N_STATES:
                    raise ValueError(f"{e.code}[{i}]: state {s} is outside 1..{N_STATES}")
                if not (math.isfinite(m) and m > 0.0):
                    raise ValueError(f"{e.code}[{i}]: raw_mass must be positive")
                _check_distribution(d, f"{e.code}[{i}]")
        return self

    def economy(self, code: str) -> EconomySignal:
        for e in self.economies:
            if e.code == code:
                return e
        raise KeyError(code)

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
