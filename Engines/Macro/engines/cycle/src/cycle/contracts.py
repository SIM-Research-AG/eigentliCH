"""Contracts: every model this engine consumes or produces.

The contracts are the only thing another engine may rely on, so they depend on nothing in
this package. Every model is frozen and forbids extra fields: an unknown key is a caller
error, not something to ignore. Collections are tuples, so an instance cannot be edited
after validation.

Missing values travel as ``None``. JSON has no NaN, and a cycle that has no position in a
year (unidentifiable, unanchored, or outside the span its input covers) must stay visibly
without one all the way to the consumer.

Series are always **aligned to** ``years``: ``series[i]`` is year ``years[i]``. One
orientation everywhere, so no consumer has to guess.

The ``Panel`` contract is owned by ``datafeed``. It is mirrored here, as this engine reads
it, because no engine imports another engine's code. If the two ever disagree, the
datafeed engine page is the authority and this mirror is the bug.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Contract versions this engine speaks. Bump the version on any change to a model's
#: fields; consumers pin on these strings.
CONTRACT_VERSIONS: dict[str, str] = {
    "Panel": "panel@1.1.0",
    "Country(datafeed)": "country@1.0.0",
    "MacroState(macrofield)": "macrofield-state@1.2.0",
    "CycleRunRequest": "cycle-run@1.2.0",
    "CycleState": "cycle-state@1.2.0",
    "CurrentPhases": "cycle-current@1.0.0",
    "Calibration": "cycle-calibration@1.1.0",
}

#: Printed on every artefact and in the README. House rule.
NOTICE = "Model-derived research output of the cycle model. Not investment advice."

#: The four phases of every cycle, in the order a cycle passes through them. Phases are
#: read off the phase angle in the cycle's own variable, where 0 is the peak and plus or
#: minus pi the trough (the convention of the first draft, ``cycles.py``):
#:
#: ``recovery``     [-pi, -pi/2)   below its mean and rising
#: ``expansion``    [-pi/2, 0)     above its mean and rising
#: ``slowdown``     [0, pi/2)      above its mean and falling
#: ``contraction``  [pi/2, pi)     below its mean and falling
Phase = Literal["recovery", "expansion", "slowdown", "contraction"]
PHASES: tuple[Phase, ...] = ("recovery", "expansion", "slowdown", "contraction")

CycleKind = Literal["estimated", "anchored_trough", "anchored_peak", "anchored_saturation"]
#: What an estimated cycle is band-passed from. ``output_growth``: the year-on-year change
#: of log real output (datafeed GDP deflated by CPI). ``saturation_change``: the change of
#: capital saturation (total debt over GDP). ``macrofield_output_growth``: the change of log
#: output Y from macrofield's observed path, in current US dollars, as the first draft read it.
CycleInput = Literal["output_growth", "saturation_change", "macrofield_output_growth"]
#: What a cycle's position is worth, worst to best (``cycle_bins.py``).
Confidence = Literal["marginal", "assumed", "supplied", "measured"]
Annualisation = Literal["year_end", "mean"]
CellFlag = Literal["observed", "carried", "missing"]

#: Bins on the cautious-to-aggressive axis the cycle layer is placed on. Fixed by the
#: downstream interface (the Regime's axis), not a calibration choice.
STATE_COUNT = 25

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_MONTH_END = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-\d{2}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

Number = Optional[float]
Series = tuple[Number, ...]


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




# ---------------------------------------------------------------------------
# Consumed: MacroState (owned by macrofield), the part this engine reads
# ---------------------------------------------------------------------------

class _Upstream(BaseModel):
    """Mirror of only the fields this engine reads. Other fields are ignored, not refused:
    the full contract is macrofield's, and this engine must not break when it grows."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class UpstreamStatePaths(_Upstream):
    Y: Series


class UpstreamEconomyState(_Upstream):
    code: str
    name: str
    status: Literal["ok", "unavailable"]
    reason: Optional[str] = None
    years: tuple[int, ...] = ()
    observed: Optional[UpstreamStatePaths] = None
    projection: Optional["UpstreamProjection"] = None

    @model_validator(mode="after")
    def _aligned(self) -> "UpstreamEconomyState":
        if self.observed is not None and len(self.observed.Y) != len(self.years):
            raise ValueError(f"{self.code}: observed Y is not aligned to its years")
        return self


class UpstreamProjection(_Upstream):
    """macrofield's forward projection: only its horizon is read here."""

    status: Optional[str] = None
    years: tuple[int, ...] = ()


UpstreamEconomyState.model_rebuild()


class UpstreamMacroProvenance(_Upstream):
    snapshot_id: str
    calibration_version: str


class UpstreamMacroState(_Upstream):
    """``macrofield GET /artefacts/{id}``: the observed output path per economy."""

    contract_version: Literal["macrofield-state@1.2.0"]
    artefact_id: str
    economies: tuple[UpstreamEconomyState, ...]
    provenance: UpstreamMacroProvenance


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class CycleSpec(_Frozen):
    """One cycle: how it is found, how long it is, and how it enters the layer.

    ``estimated`` cycles are band-passed from ``input`` around ``period_years`` (the prior),
    within ``band`` if given, else ``period_years * (1 -/+ band_fraction)``. The anchored
    kinds are positioned from supplied structure, never estimated: ``anchored_trough`` has
    its low in ``anchor_year``, ``anchored_peak`` its high, and ``anchored_saturation`` is
    ``years_into_cycle_at_anchor`` years in where capital saturation last crosses
    ``anchor_saturation`` upwards.
    """

    name: str
    kind: CycleKind
    period_years: float = Field(gt=0)
    input: Optional[CycleInput] = None
    band: Optional[tuple[float, float]] = None
    anchor_year: Optional[float] = None
    #: ``anchored_trough`` and ``anchored_peak``: economy code -> that economy's own anchor
    #: year, overriding ``anchor_year``. An economy with neither has no position.
    anchor_years: dict[str, float] = Field(default_factory=dict)
    anchor_saturation: Optional[float] = Field(default=None, gt=0)
    years_into_cycle_at_anchor: Optional[float] = Field(default=None, ge=0)
    #: +1 when a peak in the cycle's own variable belongs at the aggressive end of the
    #: 25-bin axis, -1 when at the cautious end. Capital is -1: its peak is peak saturation.
    orientation: Literal[1, -1] = 1
    #: ``anchored_saturation`` only: economy code -> the year of a historical reset, which is
    #: year 0 of the cycle (so ``years_into_cycle_at_anchor`` years later it peaks). Supplied
    #: by the author; where an economy has one it replaces the saturation crossing.
    resets: dict[str, float] = Field(default_factory=dict)
    #: Anchored cycles only. ``cosine``: the draft's cosine, peak at the anchor. ``rise_fall``
    #: (saturation anchor only): low at year 0, a rise to the peak at year
    #: ``years_into_cycle_at_anchor``, a fall to the next low at year ``period_years``.
    #: ``fall_rise``: the same timing inverted: peak at year 0, a fall to the low at year
    #: ``years_into_cycle_at_anchor`` (saturation), a rise to the next peak at ``period_years``.
    shape: Literal["cosine", "rise_fall", "fall_rise"] = "cosine"
    #: Whether the cycle enters the superposition and the synchrony windows. It is placed on
    #: the 25-bin axis either way.
    in_interference: bool = True
    layer_weight: float = Field(default=1.0, ge=0)
    superposition_weight: float = Field(default=1.0, ge=0)
    source: str = ""

    @model_validator(mode="after")
    def _fields_fit_the_kind(self) -> "CycleSpec":
        if not _NAME.match(self.name):
            raise ValueError(f"cycle name {self.name!r} must be lower case, digits and underscores")
        estimated = self.kind == "estimated"
        if estimated != (self.input is not None):
            raise ValueError(f"{self.name}: an estimated cycle needs an input, an anchored one has none")
        if self.band is not None:
            if not estimated:
                raise ValueError(f"{self.name}: only an estimated cycle has a band")
            low, high = self.band
            if not 2.0 <= low < high:
                raise ValueError(f"{self.name}: a band needs 2 <= low < high (annual sampling)")
        fixed = self.kind in ("anchored_trough", "anchored_peak")
        if fixed != (self.anchor_year is not None or bool(self.anchor_years)):
            raise ValueError(f"{self.name}: anchored_trough and anchored_peak need anchor_year or "
                             "anchor_years, and only they have one")
        saturation = self.kind == "anchored_saturation"
        if saturation != (self.anchor_saturation is not None) or \
                saturation != (self.years_into_cycle_at_anchor is not None):
            raise ValueError(f"{self.name}: anchor_saturation and years_into_cycle_at_anchor "
                             "belong to anchored_saturation, and it needs both")
        if self.resets and not saturation:
            raise ValueError(f"{self.name}: resets belong to anchored_saturation")
        if self.shape in ("rise_fall", "fall_rise") and not (saturation and self.years_into_cycle_at_anchor < self.period_years):
            raise ValueError(f"{self.name}: rise_fall needs anchored_saturation with the peak "
                             "(years_into_cycle_at_anchor) before the end of the period")
        return self


class Widths(_Frozen):
    """Kernel width on the 25-bin axis, by what a cycle's position is worth, in bins."""

    measured_base: float = Field(default=2.0, gt=0)
    measured_reference_periods: float = Field(default=10.0, gt=0)
    measured_min: float = Field(default=1.5, gt=0)
    measured_max: float = Field(default=5.0, gt=0)
    supplied: float = Field(default=5.0, gt=0)
    assumed: float = Field(default=7.0, gt=0)
    marginal: float = Field(default=7.0, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Widths":
        if self.measured_min > self.measured_max:
            raise ValueError("measured_min exceeds measured_max")
        return self


class Calibration(_Frozen):
    """A complete, versioned parameter set. Never edited; a change is a new version."""

    contract_version: Literal["cycle-calibration@1.1.0"] = "cycle-calibration@1.1.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    cycles: tuple[CycleSpec, ...] = Field(min_length=1)
    annualisation: Annualisation = "year_end"
    #: Deflate nominal GDP by CPI before taking output growth.
    deflate_output: bool = True
    #: Half-width of an estimated cycle's band, as a fraction of its prior period.
    band_fraction: float = Field(default=0.4, gt=0, lt=1)
    #: A cycle is identifiable only if the sample spans this many of its prior periods.
    minimum_periods_in_sample: float = Field(default=2.0, gt=0)
    #: Fewer sampling intervals per period than this makes a cycle ``marginal``.
    minimum_intervals_per_period: float = Field(default=4.0, gt=0)
    #: Where saturation never reaches the anchor, solve its recent trend for when it would
    #: and anchor on that, marked ``assumed``. Off: an unanchored economy stays unanchored.
    assume_capital_crossing: bool = False
    assume_trend_window: int = Field(default=10, ge=2)
    assume_maximum_years_ahead: float = Field(default=120.0, gt=0)
    phase_tolerance_radians: float = Field(default=0.5, gt=0, le=math.pi)
    minimum_cycles_in_phase: int = Field(default=3, ge=2)
    widths: Widths = Widths()
    #: Lean of the kernel toward the direction of travel. No source; 0 is symmetric.
    skew_coefficient: float = Field(default=0.35, ge=0, le=0.95)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v

    @model_validator(mode="after")
    def _unique(self) -> "Calibration":
        names = [c.name for c in self.cycles]
        if len(set(names)) != len(names):
            raise ValueError("cycle names must be unique")
        if sum(1 for c in self.cycles if c.kind == "anchored_saturation") > 1:
            raise ValueError("at most one cycle is anchored on saturation")
        return self

    def spec(self, name: str) -> CycleSpec:
        for c in self.cycles:
            if c.name == name:
                return c
        raise KeyError(name)


# ---------------------------------------------------------------------------
# Run request and run status
# ---------------------------------------------------------------------------

class CycleRunRequest(_Frozen):
    """Body of ``POST /run``. Omitted fields take their defaults from ``config.yaml``.

    ``macrofield_artefact_id`` names the ``MacroState`` whose output paths the calibration's
    macrofield inputs read; omitted, macrofield's latest successful run is used and recorded.
    It is ignored by a calibration that reads nothing from macrofield.
    """

    snapshot_id: str = Field(min_length=1)
    economies: Optional[tuple[str, ...]] = Field(default=None, min_length=1)
    calibration_version: Optional[str] = None
    macrofield_artefact_id: Optional[str] = None
    #: Project the anchored cycles as far ahead as macrofield projects. Omitted: config.yaml.
    project: Optional[bool] = None

    @field_validator("economies")
    @classmethod
    def _unique(cls, v: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("economies must be unique")
        return v


RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class Unidentified(_Frozen):
    """A cycle with no position at all for an economy, and why."""

    economy: str
    cycle: str
    reason: str


class InputGap(_Frozen):
    """Years an input is missing for an economy. Estimated cycles use only the trailing
    contiguous span of their input, so a gap shortens the sample rather than being filled."""

    economy: str
    input: str
    years: tuple[int, ...]


class PublicFill(_Frozen):
    """Cells of an input series that datafeed filled from a public source."""

    country: str
    series_id: str
    source: str
    first: str
    last: str


class CoverageReport(_Frozen):
    economies: int
    years: int
    #: economy x cycle x year cells, and how many carry no phase.
    cycle_cells: int
    cycle_cells_without_phase: int
    #: economy x year cells where no cycle could be placed on the 25-bin axis.
    layer_cells_unplaced: int
    unidentified: tuple[Unidentified, ...]
    input_gaps: tuple[InputGap, ...]
    public_fills: tuple[PublicFill, ...] = ()


class Provenance(_Frozen):
    snapshot_id: str
    as_of: str
    upstream: dict[str, str]
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: The cycle model sits upstream of the Regime, so there is no regime to stamp. The
    #: field exists so that the binding rule reads the same on every artefact.
    regime_id: Optional[str] = None
    label: Literal["model-derived"] = "model-derived"


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: CycleRunRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[Provenance]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Produced: CycleState
# ---------------------------------------------------------------------------

def phase_of(angle: float) -> Phase:
    """The phase an angle (radians, any winding) falls in. See ``PHASES``."""
    wrapped = (angle + math.pi) % (2.0 * math.pi)          # [0, 2 pi): 0 is the trough
    return PHASES[min(3, int(wrapped // (math.pi / 2.0)))]


class CycleTrack(_Frozen):
    """One cycle for one economy, year by year.

    ``angle`` is the phase angle in the cycle's own variable (0 peak, plus or minus pi
    trough), ``level`` its cosine. ``bin_centre``, ``bin_width`` and ``bin_skew`` place it
    on the 25-bin axis, orientation applied; a missing entry means it was not placed.
    """

    cycle: str
    kind: CycleKind
    identifiable: bool
    confidence: Optional[Confidence]
    anchored: bool
    assumed: bool
    #: The dominant period estimated in the band, or the anchored cycle's period.
    period_years: Number
    #: The year the anchor pins, if anchored: the trough or peak year, the saturation
    #: crossing, or for a historical reset the peak it implies (reset + 90 years).
    reference_year: Number
    sample_years: float
    phase: tuple[Optional[Phase], ...]
    angle: Series
    level: Series
    component: Series
    amplitude: Series
    years_into_cycle: Series
    bin_centre: Series
    bin_width: Series
    bin_skew: Series
    #: Years in which the phase angle stepped backwards. A phase otherwise only moves
    #: forward through ``PHASES`` (a cycle faster than four years can skip one).
    order_breaks: tuple[int, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> "CycleTrack":
        n = len(self.phase)
        for name in ("angle", "level", "component", "amplitude", "years_into_cycle",
                     "bin_centre", "bin_width", "bin_skew"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{self.cycle}: {name} is not aligned to the years")
        for label, angle in zip(self.phase, self.angle):
            if (label is None) != (angle is None):
                raise ValueError(f"{self.cycle}: a year has a phase exactly when it has an angle")
            if angle is not None and phase_of(angle) != label:
                raise ValueError(f"{self.cycle}: phase {label} does not match angle {angle}")
        if not self.identifiable and any(a is not None for a in self.angle):
            raise ValueError(f"{self.cycle}: an unidentifiable cycle has no phase")
        if self.identifiable != (self.confidence is not None):
            raise ValueError(f"{self.cycle}: confidence is set exactly when identifiable")
        return self


class SynchronyWindow(_Frozen):
    """Consecutive years in which at least ``minimum_cycles_in_phase`` cycles are in phase."""

    start_year: int
    end_year: int
    cycles: tuple[str, ...]
    mean_absolute_phase_spread: float


class EconomyCyclesV110(_Frozen):
    """One economy as ``cycle-state@1.1.0`` published it: the read model for stored 1.1.0
    artefacts (C-26). ``EconomyCycles`` is this plus the fields 1.2.0 added."""

    code: str
    name: str
    cycles: tuple[CycleTrack, ...]
    #: The cycle layer: the placed cycles mixed linearly on the 25-bin axis (bin 1 cautious,
    #: bin 25 aggressive), one distribution per year, or null where nothing was placed.
    layer: tuple[Optional[tuple[float, ...]], ...]
    layer_mean_bin: Series
    layer_modal_bin: tuple[Optional[int], ...]
    #: Unit-amplitude sum of the interference members, in [-1, 1], and their alignment in
    #: [0, 1] (1: all point the same way). Null outside the span every member covers.
    superposition: Series
    alignment: Series
    interference_members: tuple[str, ...]
    synchrony_windows: tuple[SynchronyWindow, ...]
    notes: tuple[str, ...]

    @model_validator(mode="after")
    def _layer(self) -> "EconomyCyclesV110":
        n = len(self.layer)
        if any(len(s) != n for s in (self.layer_mean_bin, self.layer_modal_bin,
                                     self.superposition, self.alignment)):
            raise ValueError(f"{self.code}: the layer series are not aligned to the years")
        for row in self.layer:
            if row is not None:
                if len(row) != STATE_COUNT:
                    raise ValueError(f"{self.code}: a layer row needs {STATE_COUNT} bins")
                if any(v < 0 for v in row) or abs(sum(row) - 1.0) > 1e-9:
                    raise ValueError(f"{self.code}: a layer row is a distribution")
        return self


class EconomyCycles(EconomyCyclesV110):
    """One economy in ``cycle-state@1.2.0``: 1.1.0's fields, then the anchored superposition."""

    #: The same superposition over the anchored interference members only (``anchored_members``,
    #: today credit, innovation and capital), weights re-normalised to their sum, in [-1, 1].
    #: Anchored cycles are defined for any date, so it runs through the projection, where the
    #: band-passed members and ``superposition`` stop (C-25). Not a substitute for
    #: ``superposition`` where both exist: it leaves the pulse and business cycles out.
    superposition_anchored: Series
    anchored_members: tuple[str, ...]

    @model_validator(mode="after")
    def _anchored(self) -> "EconomyCycles":
        if len(self.superposition_anchored) != len(self.layer):
            raise ValueError(f"{self.code}: the anchored superposition is not aligned to the years")
        return self


class _CycleStateBase(_Frozen):
    """The fields every published version of the artefact shares. Not served by itself."""

    artefact_id: str
    contract_version: str
    notice: str = NOTICE
    years: tuple[int, ...] = Field(min_length=1)
    #: The last observed year. Years after it are projected: only the anchored cycles (defined
    #: for any date) have a position there; a band-passed cycle cannot be extrapolated.
    observed_until: int
    #: The last projected year (macrofield's projection horizon), or null without a projection.
    projected_until: Optional[int] = None
    phase_order: tuple[Phase, ...] = PHASES
    state_count: int = STATE_COUNT
    cycles: tuple[CycleSpec, ...]
    economies: tuple[EconomyCyclesV110, ...]
    coverage: CoverageReport
    provenance: Provenance

    @model_validator(mode="after")
    def _shape(self) -> "_CycleStateBase":
        if self.observed_until not in self.years:
            raise ValueError("observed_until must be a year on the axis")
        if (self.projected_until is None) != (self.observed_until == self.years[-1]):
            raise ValueError("projected_until is set exactly when the axis runs past observed_until")
        names = tuple(c.name for c in self.cycles)
        for e in self.economies:
            if tuple(t.cycle for t in e.cycles) != names:
                raise ValueError(f"{e.code}: every economy carries every cycle, in order")
            if len(e.layer) != len(self.years) or any(len(t.phase) != len(self.years) for t in e.cycles):
                raise ValueError(f"{e.code}: not aligned to the years")
        return self


class CycleState(_CycleStateBase):
    """The artefact: the cycles per economy per year, each with its phase. Every new run
    publishes this version."""

    contract_version: Literal["cycle-state@1.2.0"] = "cycle-state@1.2.0"
    economies: tuple[EconomyCycles, ...]


class CycleStateV110(_CycleStateBase):
    """Read model of a stored ``cycle-state@1.1.0`` artefact (C-26). No run publishes it any
    more; ``GET /artefacts/{id}`` serves a stored 1.1.0 artefact through it, as published."""

    contract_version: Literal["cycle-state@1.1.0"] = "cycle-state@1.1.0"
    economies: tuple[EconomyCyclesV110, ...]


#: Every version of the artefact the store may hold, by ``contract_version``.
STORED_CYCLE_STATES: dict[str, type[_CycleStateBase]] = {
    "cycle-state@1.1.0": CycleStateV110,
    "cycle-state@1.2.0": CycleState,
}
AnyCycleState = Annotated[Union[CycleState, CycleStateV110], Field(discriminator="contract_version")]


class CurrentCycle(_Frozen):
    cycle: str
    #: The last year the cycle has a phase in, which is the final year unless its input
    #: ends early; null if it has none.
    year: Optional[int]
    phase: Optional[Phase]
    angle: Number
    level: Number
    confidence: Optional[Confidence]
    years_into_cycle: Number
    bin_centre: Number


class CurrentEconomy(_Frozen):
    code: str
    name: str
    cycles: tuple[CurrentCycle, ...]
    layer_mean_bin: Number
    #: Alignment in the last year the superposition covers, and whether a synchrony window
    #: ends in that year.
    alignment: Number
    in_synchrony_window: bool


class CurrentPhases(_Frozen):
    """``/cycles/{id}/current``: each cycle's current phase per economy."""

    contract_version: Literal["cycle-current@1.0.0"] = "cycle-current@1.0.0"
    artefact_id: str
    year: int
    phase_order: tuple[Phase, ...] = PHASES
    economies: tuple[CurrentEconomy, ...]
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
