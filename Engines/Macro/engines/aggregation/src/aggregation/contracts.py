"""Contracts: every model this engine consumes or produces.

The contracts are the only thing another engine may rely on, so they depend on nothing in
this package. Every model this engine *publishes* is frozen and forbids extra fields: an
unknown key is a caller error. Collections are tuples, so an instance cannot be edited after
validation. Missing values travel as ``None``; JSON has no NaN.

**Upstream mirrors.** ``MarketRiskSignal`` (owned by ``mrs``), ``CycleState`` (owned by
``cycle``) and ``MacroState`` (owned by ``macrofield``) are mirrored here as this engine reads
them, because no engine imports another engine's code. The mirrors are *partial*: they name
only the fields ``aggregation`` uses and ignore the rest, and they pin the upstream contract
version exactly. If a mirror and its owner ever disagree, the owner's engine page is the
authority and the mirror is the bug.

**The 25 states.** State 1 is the most cautious reading, state 25 the most aggressive, as in
every input and in the Portfolio Creation Program's return profiles. A distribution is always
25 non-negative numbers summing to 1. States are **1-based** everywhere in this contract (the
first draft published 0-based path states; decision AGG-09).
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

#: Contract versions this engine speaks. Bump the version on any change to a model's
#: fields; consumers pin on these strings.
CONTRACT_VERSIONS: dict[str, str] = {
    "AggregationRunRequest": "aggregation-run@1.0.0",
    "Regime": "aggregation-regime@1.0.0",
    "Calibration": "aggregation-calibration@1.1.0",
    "MarketRiskSignal(mrs)": "mrs-signal@1.0.0",
    "CycleState(cycle)": "cycle-state@1.1.0",
    "MacroState(macrofield)": "macrofield-state@1.2.0",
}

#: Printed on every artefact and in the README. House rule.
NOTICE = (
    "Model-derived research output of the aggregation layer (the combined market risk signal). "
    "The Regime is an assessment of the environment, not a forecast. Not investment advice."
)

#: Fixed by the downstream interface (PCP return profiles have 25 rows).
N_STATES = 25

OptimismScale = Literal["defensive", "default", "aggressive", "rogue"]
#: Cautious to aggressive. A later level never reads more cautious than an earlier one.
OPTIMISM_SCALES: tuple[OptimismScale, ...] = ("defensive", "default", "aggressive", "rogue")

#: The five regimes of book section 20.2, cautious to aggressive (the order of the axis).
REGIMES: tuple[str, ...] = ("crisis", "contraction", "stagnation", "expansion", "boom")

#: The macro tilts of the first draft (``saa_signal.DEFAULT_TILTS``). ``base`` is the weight
#: every regime starts with.
TILTS: tuple[str, ...] = (
    "base", "saturation_above_band", "saturation_below_band", "real_to_financial_below_one",
    "unsecured_rising", "interference", "alignment_gain", "capital_overdue_per_decade",
    "innovation_approach_per_decade",
)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")
_CODE = re.compile(r"^[A-Z]{2,4}$")

Number = Optional[float]
Distribution = tuple[float, ...]
Series = tuple[Number, ...]

#: Tolerance on "sums to 1". Normalisation divides once, so the error is a few ulp.
SUM_TOLERANCE = 1e-12


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Upstream(BaseModel):
    """A partial mirror of another engine's contract: read what we use, ignore the rest."""

    model_config = ConfigDict(frozen=True, extra="ignore")


def check_distribution(d: tuple[float, ...], where: str) -> None:
    if len(d) != N_STATES:
        raise ValueError(f"{where}: a distribution has {N_STATES} states, not {len(d)}")
    if any((not math.isfinite(p)) or p < 0.0 for p in d):
        raise ValueError(f"{where}: probabilities must be finite and non-negative")
    if abs(math.fsum(d) - 1.0) > SUM_TOLERANCE:
        raise ValueError(f"{where}: a distribution must sum to 1 (sums to {math.fsum(d)!r})")


# ---------------------------------------------------------------------------
# Upstream mirrors
# ---------------------------------------------------------------------------

class MRSProvenance(_Upstream):
    snapshot_id: str
    as_of: str
    calibration_version: str
    regime_id: None = None


class MRSEconomy(_Upstream):
    code: str
    name: str
    #: 25 states summing to 1, at zero optimism shift; ``None`` where unassessed.
    distribution: tuple[Optional[Distribution], ...]


class MarketRiskSignal(_Upstream):
    """``mrs-signal@1.0.0``, the fields ``aggregation`` reads."""

    contract_version: Literal["mrs-signal@1.0.0"]
    artefact_id: str
    #: Month-end ISO dates, strictly increasing.
    dates: tuple[str, ...]
    economies: tuple[MRSEconomy, ...]
    provenance: MRSProvenance

    @model_validator(mode="after")
    def _shape(self) -> "MarketRiskSignal":
        n = len(self.dates)
        if any(b <= a for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("MarketRiskSignal dates must be strictly increasing")
        for e in self.economies:
            if len(e.distribution) != n:
                raise ValueError(f"MarketRiskSignal {e.code}: distribution is not aligned to dates")
            for i, d in enumerate(e.distribution):
                if d is not None:
                    check_distribution(d, f"mrs {e.code}[{self.dates[i]}]")
        return self


class CycleTrack(_Upstream):
    cycle: str
    anchored: bool
    #: For an anchored cycle, the year its anchor pins: the trough (innovation), or the
    #: reordering point (capital: the saturation crossing, or reset + 90 years).
    reference_year: Number = None


class CycleEconomy(_Upstream):
    code: str
    name: str
    cycles: tuple[CycleTrack, ...]
    #: The cycle layer on the 25-bin axis, per year; ``None`` where no cycle is placed.
    layer: tuple[Optional[Distribution], ...]
    #: Unit-amplitude sum of the interference members, per year, in [-1, 1].
    superposition: Series
    #: Alignment of the interference members, per year, in [0, 1].
    alignment: Series


class CycleProvenance(_Upstream):
    snapshot_id: str
    as_of: str
    upstream: dict[str, str] = Field(default_factory=dict)
    calibration_version: str


#: The cycle contract versions this mirror reads (AGG-18). ``cycle-state@1.2.0`` (cycle C-25,
#: review R-004) only adds fields aggregation does not read, so both validate; the version
#: actually read is recorded in the Regime's provenance. ``CONTRACT_VERSIONS`` keeps the
#: version this engine was written against, so the idempotency key, and with it every
#: ``regime_id`` of unchanged inputs, stays as it was.
CYCLE_STATE_ACCEPTED = ("cycle-state@1.1.0", "cycle-state@1.2.0")


class CycleState(_Upstream):
    """``cycle-state@1.1.0`` and ``@1.2.0``, the fields ``aggregation`` reads."""

    contract_version: Literal["cycle-state@1.1.0", "cycle-state@1.2.0"]
    artefact_id: str
    years: tuple[int, ...]
    #: The last observed year; later years are projected (anchored cycles only).
    observed_until: int
    economies: tuple[CycleEconomy, ...]
    provenance: CycleProvenance

    @model_validator(mode="after")
    def _shape(self) -> "CycleState":
        n = len(self.years)
        for e in self.economies:
            for name in ("layer", "superposition", "alignment"):
                if len(getattr(e, name)) != n:
                    raise ValueError(f"CycleState {e.code}: {name} is not aligned to years")
        return self


class MacroInputs(_Upstream):
    #: The saturation axis (the published credit ratio times the credit uplift), a ratio.
    saturation: Series


class MacroDiagnostics(_Upstream):
    real_to_financial: Series
    unsecured_ratio: Series
    phase: tuple[Literal[1, 2, 3, 4], ...]
    in_balanced_band: tuple[bool, ...]


class MacroCurrent(_Upstream):
    year: int
    phase: Literal[1, 2, 3, 4]
    phase_label: str
    saturation_pct: float


class MacroEconomy(_Upstream):
    code: str
    name: str
    status: Literal["ok", "unavailable"]
    reason: Optional[str] = None
    years: tuple[int, ...] = ()
    inputs: Optional[MacroInputs] = None
    diagnostics: Optional[MacroDiagnostics] = None
    current: Optional[MacroCurrent] = None


class MacroProvenance(_Upstream):
    snapshot_id: str
    as_of: str
    calibration_version: str


class MacroState(_Upstream):
    """``macrofield-state@1.2.0``, the fields ``aggregation`` reads."""

    contract_version: Literal["macrofield-state@1.2.0"]
    artefact_id: str
    economies: tuple[MacroEconomy, ...]
    provenance: MacroProvenance


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class Blend(_Frozen):
    """``final = (1 - cycle) * [macro * SAA + (1 - macro) * MRS] + cycle * CYCLES``, in bin
    space (first draft, ``saa_signal.merge``)."""

    #: Weight on the macro half against the market risk signal (draft ``saa.blend_weight``).
    macro: float = Field(ge=0.0, le=1.0)
    #: Share of the final distribution the cycle layer contributes (draft
    #: ``cycles.bins.blend_weight``).
    cycle: float = Field(ge=0.0, le=1.0)
    #: A year without a cycle layer row: ``reweight`` drops the cycle term for its months and
    #: records it; ``fail`` fails the economy.
    cycle_missing: Literal["reweight", "fail"] = "reweight"


class Kernels(_Frozen):
    """How the five regime weights are spread over the axis (draft ``regime.py``). Percentages;
    normalised before use. The boom kernel is the crisis kernel reversed."""

    symmetric: tuple[float, ...] = Field(min_length=1)
    crisis: tuple[float, ...] = Field(min_length=1)
    #: One-based inclusive start bin per regime.
    placement: dict[str, int]

    @model_validator(mode="after")
    def _fits(self) -> "Kernels":
        if set(self.placement) != set(REGIMES):
            raise ValueError(f"placement must name exactly {list(REGIMES)}")
        for name, kernel in (("symmetric", self.symmetric), ("crisis", self.crisis)):
            if any((not math.isfinite(v)) or v < 0 for v in kernel) or not sum(kernel) > 0:
                raise ValueError(f"the {name} kernel must be non-negative with positive mass")
        for regime, start in self.placement.items():
            size = len(self.crisis) if regime in ("crisis", "boom") else len(self.symmetric)
            if start < 1 or start + size - 1 > N_STATES:
                raise ValueError(f"the {regime} kernel placed at bin {start} runs off the "
                                 f"{N_STATES}-bin axis, which would discard probability")
        return self


class MacroTilts(_Frozen):
    """How the macro state moves the five regime weights (draft ``saa.tilts``). A judgement
    call with no source; swept and bounded in the draft's calibration round A."""

    coefficients: dict[str, float]
    #: Share of a cautious (aggressive) tilt that also lands on contraction (expansion).
    adjacent_share: float = Field(default=0.6, ge=0.0)
    #: The innovation tilt fires within this many years of the innovation trough.
    innovation_window_years: float = Field(default=20.0, gt=0.0)
    #: The saturation band (``saturation.balanced_band``): above the upper bound moves weight
    #: to the cautious end, below the lower bound to the aggressive end.
    band_lower: float
    band_upper: float
    #: A saturation reading above this refuses the economy (draft ``saturation.refuse_above``).
    saturation_ceiling: Optional[float] = None
    #: The cycle names whose anchors feed the two anchored tilts.
    capital_cycle: str = "capital"
    innovation_cycle: str = "innovation"

    @model_validator(mode="after")
    def _complete(self) -> "MacroTilts":
        if set(self.coefficients) != set(TILTS):
            raise ValueError(f"tilt coefficients must name exactly {list(TILTS)}")
        if not self.band_upper > self.band_lower:
            raise ValueError("band_upper must exceed band_lower")
        return self


class Optimism(_Frozen):
    """The optimism level, applied to the combined distribution (decision AGG-05).

    The distribution is moved by ``targets[level] - reference_state`` states (fractional
    shifts interpolate between the two neighbouring whole shifts); mass that runs past either
    end of the axis piles onto the end state. ``reference_state`` is the modal state of the
    market risk signal at neutral readings and zero shift (12), so a neutral signal reads at
    the target state of each level.

    ``keep_tail`` states (the most cautious ones) stay where they are and only the rest of the
    distribution moves (decision AGG-15), so the crisis regime keeps a live probability at every
    level. 0 moves everything.

    ``shifts``, when given, are the shifts in states per level, solved so that the neutral
    reading's published state lands on ``targets`` (with a kept tail, ``target - reference``
    falls short); ``targets`` then document the intent. ``None``: ``target - reference``.
    """

    reference_state: int = Field(ge=1, le=N_STATES)
    targets: dict[OptimismScale, float]
    keep_tail: int = Field(default=0, ge=0, lt=N_STATES)
    shifts: Optional[dict[OptimismScale, float]] = None

    @model_validator(mode="after")
    def _ordered(self) -> "Optimism":
        if set(self.targets) != set(OPTIMISM_SCALES):
            raise ValueError(f"targets must map exactly {list(OPTIMISM_SCALES)}")
        values = [self.targets[s] for s in OPTIMISM_SCALES]
        if any(b < a for a, b in zip(values, values[1:])):
            raise ValueError("a higher optimism level must never read more cautious")
        if any(not 1 <= v <= N_STATES for v in values):
            raise ValueError(f"targets are states in 1..{N_STATES}")
        if self.shifts is not None:
            if set(self.shifts) != set(OPTIMISM_SCALES):
                raise ValueError(f"shifts must map exactly {list(OPTIMISM_SCALES)}")
            given = [self.shifts[s] for s in OPTIMISM_SCALES]
            if any(b < a for a, b in zip(given, given[1:])):
                raise ValueError("a higher optimism level must never read more cautious")
        return self

    def shift(self, level: OptimismScale) -> float:
        if self.shifts is not None:
            return float(self.shifts[level])
        return float(self.targets[level]) - float(self.reference_state)


class Reading(_Frozen):
    """How a distribution is summarised (draft ``describe_reading`` and ``regime.shape``)."""

    mode_prominence: float = Field(default=0.25, gt=0.0, le=1.0)
    lean_bins: float = Field(default=2.0, ge=0.0)
    tail_bins: int = Field(default=5, ge=1, le=N_STATES)
    minimum_tail_probability: float = Field(default=0.01, ge=0.0, le=1.0)
    #: One-based inclusive [first, last] bins per regime; must partition the axis.
    five_regime_bins: dict[str, tuple[int, int]]

    @model_validator(mode="after")
    def _partition(self) -> "Reading":
        covered: list[int] = []
        for first, last in self.five_regime_bins.values():
            if not 1 <= first <= last <= N_STATES:
                raise ValueError("five_regime_bins are 1-based inclusive ranges inside the axis")
            covered.extend(range(first, last + 1))
        if sorted(covered) != list(range(1, N_STATES + 1)):
            raise ValueError("five_regime_bins must partition the 25 states exactly")
        return self


class Calibration(_Frozen):
    """A complete, versioned parameter set. Never edited; a change is a new version."""

    contract_version: Literal["aggregation-calibration@1.1.0"] = "aggregation-calibration@1.1.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    blend: Blend
    kernels: Kernels
    tilts: MacroTilts
    optimism: Optimism
    reading: Reading
    #: Months past the December of the last annual macro reading that the reading (and the
    #: cycle layer of that year) may be carried, flagged ``carried``. 0: never (the draft).
    carry_months: int = Field(default=0, ge=0, le=60)
    #: Market -> economy weights. Each set sums to 1. A market is published for a date only
    #: when every economy it weights is assessed on that date (the draft's rule: intersected,
    #: never renormalised).
    markets: dict[str, dict[str, float]] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be semantic, e.g. 1.2.0")
        return v

    @model_validator(mode="after")
    def _markets(self) -> "Calibration":
        for market, weights in self.markets.items():
            if not weights or any(w <= 0 for w in weights.values()):
                raise ValueError(f"market {market!r}: weights must be positive and non-empty")
            if abs(math.fsum(weights.values()) - 1.0) > 1e-12:
                raise ValueError(f"market {market!r}: weights must sum to 1")
            if any(not _CODE.match(c) for c in weights):
                raise ValueError(f"market {market!r}: economies are country codes, e.g. US")
        return self


# ---------------------------------------------------------------------------
# Run request and status
# ---------------------------------------------------------------------------

class AggregationRunRequest(_Frozen):
    """Body of ``POST /run``. The three inputs, by artefact id."""

    mrs_artefact_id: str = Field(min_length=1)
    cycle_artefact_id: str = Field(min_length=1)
    macro_artefact_id: str = Field(min_length=1)
    #: ``None`` uses ``run.optimism_scale`` from ``config.yaml``.
    optimism_scale: Optional[OptimismScale] = None
    #: ``None`` uses the active calibration from ``config.yaml``.
    calibration_version: Optional[str] = None
    #: Economy codes. ``None`` runs every economy all three inputs carry.
    economies: Optional[tuple[str, ...]] = Field(default=None, min_length=1)


RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    regime_id: Optional[str]
    idempotency_key: str
    cached: bool


class EconomyCoverage(_Frozen):
    code: str
    dates_assessed: int
    #: Months the market risk signal does not assess.
    dates_without_market: int
    #: Months whose year has no macro reading (and is not within the carry limit).
    dates_without_macro: int
    #: Months assessed on a macro reading carried past its year (``carry_months``).
    dates_macro_carried: int
    #: Years in which the cycle layer had no row, so its weight was dropped and re-distributed.
    years_cycle_reweighted: tuple[int, ...]
    #: Years whose macro reading lacks an input a tilt reads (tilt name -> years).
    tilt_inputs_missing: dict[str, tuple[int, ...]]


class MarketCoverage(_Frozen):
    code: str
    #: Economies the market weights name but the Regime does not carry at all.
    economies_absent: tuple[str, ...]
    dates_assessed: int
    dates_unassessed: int


class CoverageReport(_Frozen):
    economies: tuple[EconomyCoverage, ...]
    markets: tuple[MarketCoverage, ...]
    #: Economy -> why it is not in the Regime (missing from an input, or refused).
    economies_skipped: dict[str, str]
    #: The inputs do not stem from one datafeed snapshot (warned, not refused: AGG-04).
    snapshot_mismatch: bool
    warnings: tuple[str, ...]


ScenarioPolicy = Literal["depression", "hyperinflation", "stagflation", "deferral"]

#: Version of the scenario request and listing models (``POST /scenario``, ``GET /scenarios``).
#: Deliberately not in ``CONTRACT_VERSIONS``, which feeds every idempotency key: adding scenarios
#: must not move the ``regime_id`` of an issued Regime (AGG-21).
SCENARIO_CONTRACT_VERSION = "aggregation-scenario@1.0.0"


class ScenarioProvenance(_Frozen):
    """How a scenario Regime was derived (AGG-19 to AGG-22). ``None`` on an issued base Regime."""

    #: One of the four Phase IV policies of ``Scenario_SAA.m`` (macrofield's ids, TB-21).
    policy: ScenarioPolicy
    base_regime_id: str
    base_artefact_id: str
    #: Projected months appended after the base Regime's last month (``T`` of the .m file).
    horizon_months: int = Field(ge=1)
    #: sha256 of ``Scenario_SAA.m``, the template.
    template_sha256: str
    #: ``M1`` of the .m file: boom, recovery, contraction, bust.
    target_mix: dict[str, float]
    #: The base Regime's last month; the projected months follow it.
    base_as_of: str
    #: The first and the last projected month. ``scenario_date`` is the month that represents the
    #: scenario (month ``horizon_months``, the target reached); it is the Regime's last date and
    #: its ``as_of``, so a consumer that reads the latest assessed month reads the scenario.
    projected_from: str
    scenario_date: str
    rule_version: str
    #: The policy's inflation path of ``Scenario_SAA.m`` (AGG-24, nominal and real view):
    #: ``horizon_months`` annualised rates, month 1 to 60, macrofield's TB-21 values. A deterministic
    #: function of ``policy`` and ``horizon_months``, so it is **derived when the Regime is read**, never
    #: taken on trust: a value that differs from the policy's is refused. It is left out of the stored
    #: payload and of the ``artefact_id`` hash (serialise with ``context=STORED``), so no stored
    #: scenario Regime, ``artefact_id`` or ``regime_id`` moves.
    inflation_path: Optional[tuple[float, ...]] = None
    #: The average annual inflation over the final 12 months of the path (months 49 to 60), the
    #: scenario's inflation that fmre applies to every state (AGG-24). Derived as ``inflation_path``.
    inflation_final_12m: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def _derive_inflation(cls, data):
        if not isinstance(data, dict) or data.get("policy") is None:
            return data
        from . import scenario as sc                     # lazy: scenario imports this module

        months = int(data.get("horizon_months", sc.HORIZON_MONTHS))
        path = sc.inflation_path(data["policy"], months)
        derived = {"inflation_path": tuple(float(v) for v in path),
                   "inflation_final_12m": sc.inflation_final_12m(path)}
        given = data.get("inflation_path")
        if given is not None and tuple(float(v) for v in given) != derived["inflation_path"]:
            raise ValueError(f"inflation_path is not the {data['policy']} policy's path of Scenario_SAA.m")
        given = data.get("inflation_final_12m")
        if given is not None and float(given) != derived["inflation_final_12m"]:
            raise ValueError(f"inflation_final_12m is not the {data['policy']} policy's average of months "
                             f"{months - sc.FINAL_MONTHS + 1} to {months}")
        return {**data, **derived}

    @model_serializer(mode="wrap")
    def _omit_derived_when_stored(self, handler, info):
        data = handler(self)
        if isinstance(data, dict) and isinstance(info.context, dict) and info.context.get("stored"):
            for name in DERIVED_SCENARIO_FIELDS:
                data.pop(name, None)
        return data


#: Fields of ``provenance.scenario`` derived at read time (AGG-24): not stored, not hashed.
DERIVED_SCENARIO_FIELDS: tuple[str, ...] = ("inflation_path", "inflation_final_12m")

#: Serialisation context of the stored payload and of the ``artefact_id`` hash:
#: ``regime.model_dump_json(context=STORED)``.
STORED: dict[str, bool] = {"stored": True}


class Provenance(_Frozen):
    #: The datafeed snapshot of the market risk signal (the monthly axis).
    snapshot_id: str
    #: The last month any economy is assessed.
    as_of: str
    #: Artefact ids, snapshots, calibration versions and sha256 of every input.
    upstream: dict[str, str]
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    regime_id: str
    optimism_scale: OptimismScale
    #: States the combined distribution was moved by (``targets[level] - reference_state``).
    optimism_shift: float
    label: Literal["model-derived"] = "model-derived"
    #: Only on a scenario Regime (AGG-21). The one optional field ``aggregation-regime@1.0.0``
    #: gained: on an issued base Regime it is left out of the JSON altogether (not ``null``), so
    #: every stored Regime serialises byte for byte as before and its ``artefact_id`` is unchanged.
    scenario: Optional[ScenarioProvenance] = None

    @model_serializer(mode="wrap")
    def _omit_absent_scenario(self, handler):
        data = handler(self)
        if self.scenario is None and isinstance(data, dict):
            data.pop("scenario", None)
        return data


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: AggregationRunRequest
    artefact_id: Optional[str]
    regime_id: Optional[str]
    warnings: tuple[str, ...]
    coverage: Optional[CoverageReport]
    provenance: Optional[Provenance]
    error: Optional[str]


# ---------------------------------------------------------------------------
# The Regime
# ---------------------------------------------------------------------------

class CurrentRegime(_Frozen):
    """The latest assessed month, read as the draft reads it (``describe_reading``)."""

    date: str
    #: The bin nearest the probability-weighted mean (draft M57: an argmax over two near-equal
    #: humps jumps across the axis on a fraction of a point).
    state: int = Field(ge=1, le=N_STATES)
    modal_state: int = Field(ge=1, le=N_STATES)
    mean_bin: float
    #: Local maxima at or above ``mode_prominence`` of the peak, 1-based.
    modes: tuple[int, ...]
    #: How far the tallest mode leads the runner-up (the peak itself when unimodal).
    mode_margin: float
    bimodal: bool
    #: Mass on the ``tail_bins`` most cautious states.
    crisis_tail: float
    five_regime: dict[str, float]
    shape: str
    #: From MacroState (annual). ``None`` for a market blend or an unavailable economy.
    phase: Optional[Literal[1, 2, 3, 4]] = None
    phase_label: Optional[str] = None
    saturation_pct: Optional[float] = None
    macro_year: Optional[int] = None
    macro_carried: bool = False


class EconomyRegime(_Frozen):
    code: str
    name: str
    #: Per date (aligned to ``Regime.dates``); ``None`` where unassessed.
    distribution: tuple[Optional[Distribution], ...]
    #: Mean-nearest state per date (1-based); ``None`` where unassessed.
    state: tuple[Optional[int], ...]
    modal_state: tuple[Optional[int], ...]
    #: The annual reading each month used; ``None`` where unassessed.
    macro_year: tuple[Optional[int], ...]
    #: True where the macro reading and cycle layer were carried past their year.
    carried: tuple[bool, ...]
    #: Effective blend weights per date (after any re-weighting); ``None`` where unassessed.
    weight_macro: Series
    weight_market: Series
    weight_cycle: Series
    #: The components, for the contributions endpoint. Annual rows aligned to ``years``.
    years: tuple[int, ...]
    macro_layer: tuple[Optional[Distribution], ...]
    cycle_layer: tuple[Optional[Distribution], ...]
    #: The five regime weights of the macro half per year, and the tilts that moved them
    #: (tilt -> regime -> amount, before clamping).
    macro_weights: tuple[Optional[dict[str, float]], ...]
    tilts: tuple[dict[str, dict[str, float]], ...]
    #: The market risk signal per date, as ``mrs`` published it (zero shift).
    market: tuple[Optional[Distribution], ...]
    current: Optional[CurrentRegime]
    notes: tuple[str, ...] = ()


class MarketRegime(_Frozen):
    code: str
    weights: dict[str, float]
    distribution: tuple[Optional[Distribution], ...]
    state: tuple[Optional[int], ...]
    modal_state: tuple[Optional[int], ...]
    current: Optional[CurrentRegime]


class Regime(_Frozen):
    """The combined market risk signal. The artefact of one run."""

    contract_version: Literal["aggregation-regime@1.0.0"] = "aggregation-regime@1.0.0"
    artefact_id: str
    regime_id: str
    optimism_scale: OptimismScale
    n_states: Literal[25] = N_STATES
    #: Month-end ISO dates, the market risk signal's axis.
    dates: tuple[str, ...]
    economies: tuple[EconomyRegime, ...]
    markets: tuple[MarketRegime, ...]
    coverage: CoverageReport
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _shape(self) -> "Regime":
        n = len(self.dates)
        if any(b <= a for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("dates must be strictly increasing")
        for e in self.economies:
            for label in ("distribution", "state", "modal_state", "macro_year", "carried",
                          "weight_macro", "weight_market", "weight_cycle", "market"):
                if len(getattr(e, label)) != n:
                    raise ValueError(f"{e.code}.{label} is not aligned to dates")
            for label in ("macro_layer", "cycle_layer", "macro_weights", "tilts"):
                if len(getattr(e, label)) != len(e.years):
                    raise ValueError(f"{e.code}.{label} is not aligned to years")
            _check_path(e.code, e.state, e.distribution)
        for m in self.markets:
            if len(m.state) != n or len(m.distribution) != n or len(m.modal_state) != n:
                raise ValueError(f"market {m.code} is not aligned to dates")
            _check_path(m.code, m.state, m.distribution)
        return self

    def economy(self, code: str) -> EconomyRegime:
        for e in self.economies:
            if e.code == code:
                return e
        raise KeyError(code)

    def market(self, code: str) -> MarketRegime:
        for m in self.markets:
            if m.code == code:
                return m
        raise KeyError(code)


class ScenarioRequest(_Frozen):
    """Body of ``POST /scenario`` (``aggregation-scenario@1.0.0``)."""

    base_regime_id: str = Field(pattern=r"^RGM-[0-9a-f]{16}$")
    policy: ScenarioPolicy


class ScenarioAccepted(_Frozen):
    regime_id: str
    cached: bool
    policy: ScenarioPolicy
    base_regime_id: str


class ScenarioListed(_Frozen):
    regime_id: str
    policy: ScenarioPolicy
    base_regime_id: str
    created_at: str


class ScenarioPolicyInfo(_Frozen):
    policy: ScenarioPolicy
    case: int
    label_en: str
    label_de: str
    description_en: str
    description_de: str
    #: ``M1`` of the .m file: boom, recovery, contraction, bust.
    target_mix: dict[str, float]


def _check_path(code: str, states: tuple[Optional[int], ...],
                dists: tuple[Optional[Distribution], ...]) -> None:
    for i, (s, d) in enumerate(zip(states, dists)):
        if (s is None) != (d is None):
            raise ValueError(f"{code}[{i}]: state and distribution must be missing together")
        if s is None:
            continue
        if not 1 <= s <= N_STATES:
            raise ValueError(f"{code}[{i}]: state {s} is outside 1..{N_STATES}")
        check_distribution(d, f"{code}[{i}]")

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
