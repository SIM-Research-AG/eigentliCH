"""Contracts: every model ``lbsim`` consumes or produces (spec ``review/LBSIM_INTERFACES.md`` section 3).

lbsim's own models are frozen and forbid extra fields. The upstream mirrors (lbs, pcp, aggregation, fmre) are
frozen and IGNORE extra fields: they read only what lbsim needs and pin it exactly, so an additive change
upstream never breaks lbsim and a removed field it reads always does (Engine Building Guide section 1: mirrored,
never imported).

Conventions throughout: CHF amounts; decimal rates a year; annualised log returns; chances in [0, 1]; ages in
years; every figure nominal unless its ``basis`` says ``real`` (``real = nominal - ln(1 + inflation)``, log returns
throughout). Content-hash ids: Findings ``LSF-<16hex>``, Paths ``LSP-``, Plan ``LSO-``, Run ``RUN-``, key ``IDK-``,
calibration hash ``CAL-``. Words for people are ``{de, en}`` pairs; no id or key is ever shown to a person.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

N_STATES = 25

CONTRACT_VERSIONS: dict[str, str] = {
    "LifeBalanceSimRequest": "lbsim-request@1.0.0",
    "LifeBalanceFindings": "lbsim-findings@1.0.0",
    "LifeBalancePaths": "lbsim-paths@1.0.0",
    "LifeBalancePlan": "lbsim-plan@1.0.0",
    "OptimiseRequest": "lbsim-optimise@1.0.0",
    "ValidationReport": "lbsim-validation@1.0.0",
    "Calibration": "lbsim-calibration@1.0.0",
}

#: What lbsim reads, pinned exactly (section 3.8). Mirrored, not imported.
UPSTREAM_CONTRACTS: dict[str, str] = {
    "lbs:sheet": "lbs-balance-sheet@1.0.0",
    "lbs:request": "lbs-request@1.0.0",
    "lbs:calibration": "lbs-calibration@1.3.0",
    "pcp:allocation": "pcp-allocation@1.0.0",
    "aggregation:regime": "aggregation-regime@1.0.0",
    "aggregation:scenario": "aggregation-scenario@1.0.0",
    "fmre:return_set": "rs@1.0.0",
}

NOTICE = "Model-derived research output. Not investment advice."

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

Scenario = Literal["depression", "hyperinflation", "stagflation", "deferral"]
SCENARIOS: tuple[str, ...] = ("depression", "hyperinflation", "stagflation", "deferral")
RegimeKey = Literal["base", "depression", "hyperinflation", "stagflation", "deferral"]
IncomePathCode = Literal["today", "education", "full_pensum", "network"]
INCOME_PATHS: tuple[str, ...] = ("today", "education", "full_pensum", "network")
Basis = Literal["nominal", "real"]
LevelBasis = Literal["stated", "modelled"]
Severity = Literal["blocking", "high", "medium", "note"]
Urgency = Literal["now", "months", "year", "watch"]
ActionKind = Literal["ask", "quantify", "decide_between"]
FigureUnit = Literal["chf", "chf_per_year", "share", "years", "hours_per_week", "count"]
#: The draft's RULES, in its order (``app/findings.py``). ``wealth_that_cannot_work`` is the rule the draft
#: reports under the code ``drawable_thin``; lbsim reports it under the rule's name (spec 3.2).
FINDING_CODES: tuple[str, ...] = (
    "goal_not_fundable", "thin_liquidity", "no_legal_documents", "hours_above_threshold", "undirected_surplus",
    "debt_service_equals_spending", "wealth_that_cannot_work", "pension_too_small", "empty_pillar3a",
    "spending_doubling", "positions_outside_model", "rate_reset_near", "rate_not_recorded", "goal_not_computed",
    "own_share_only", "stop_age_missing", "indirect_amortisation", "unmarried_tax_overstated",
)
FindingCode = Literal[
    "goal_not_fundable", "thin_liquidity", "no_legal_documents", "hours_above_threshold", "undirected_surplus",
    "debt_service_equals_spending", "wealth_that_cannot_work", "pension_too_small", "empty_pillar3a",
    "spending_doubling", "positions_outside_model", "rate_reset_near", "rate_not_recorded", "goal_not_computed",
    "own_share_only", "stop_age_missing", "indirect_amortisation", "unmarried_tax_overstated",
]
GoalMeasure = Literal["drawable", "deposit_eligible", "retirement_capital"]
BAND_SERIES: tuple[str, ...] = ("net_worth", "drawable", "deposit_eligible", "retirement_capital")
QUANTILES: tuple[str, ...] = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")
ROLES: tuple[str, ...] = ("Gain", "Income", "Stabilisation", "Protection")

_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEX16 = r"[0-9a-f]{16}"


def _opaque(value: str, what: str) -> str:
    """An identifier is an opaque token (LBS-03): letters, digits, dot, dash, underscore."""
    if not _OPAQUE.match(value):
        raise ValueError(f"{what} {value!r} must be an opaque reference (letters, digits, '.', '-', '_', at most "
                         "64 characters); names and e-mail addresses do not belong in a request")
    return value


def _id(prefix: str) -> str:
    return rf"^{prefix}-{_HEX16}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Mirror(BaseModel):
    """An upstream model as lbsim reads it: frozen, extra fields ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Words(_Frozen):
    """A sentence for people, in both languages. One language per page: a surface picks one."""

    de: str
    en: str


# ---------------------------------------------------------------------------
# 3.1 The request
# ---------------------------------------------------------------------------

class LifeBalanceSimRequest(_Frozen):
    """Body of ``POST /run`` and ``POST /validate`` (``lbsim-request@1.0.0``)."""

    contract_version: Literal["lbsim-request@1.0.0"] = "lbsim-request@1.0.0"
    #: Must equal ``sheet.client_ref`` and ``allocation.client``, else 409.
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    #: A pcp Allocation on the client's base Regime; ``None``: no paths and no plan (``no_allocation``).
    allocation_id: Optional[str] = Field(default=None, pattern=_id("PCP"))
    #: ``None``: all four scenarios aggregation lists for the base Regime.
    scenarios: Optional[tuple[Scenario, ...]] = None
    #: ``None`` applies LBSIM-18 (latest goal date, else the reference age, capped at 60).
    horizon_years: Optional[float] = Field(default=None, ge=1, le=60)
    #: ``None``: ``education`` when an education is planned or in progress, else ``today``.
    income_path: Optional[IncomePathCode] = None
    n_paths: Optional[int] = Field(default=None, ge=200, le=20_000)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    optimise: Literal["background", "no"] = "background"
    #: ``None``: the active calibration.
    calibration_version: Optional[str] = None

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _opaque(value, "client_ref")

    @field_validator("scenarios")
    @classmethod
    def _unique(cls, value: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("a scenario is named twice")
        return value


class RequestedBy(_Frozen):
    kind: Literal["client", "curator", "system"]
    #: An opaque reference (the curator's id, the client's ref, or a system job name).
    ref: Optional[str] = None


class OptimiseRequest(_Frozen):
    """Body of ``POST /optimise`` (``lbsim-optimise@1.0.0``). ``requested_by`` is not part of the key."""

    contract_version: Literal["lbsim-optimise@1.0.0"] = "lbsim-optimise@1.0.0"
    paths_artefact_id: str = Field(pattern=_id("LSP"))
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    requested_by: RequestedBy


# ---------------------------------------------------------------------------
# Shared blocks
# ---------------------------------------------------------------------------

class InflationUsed(_Frozen):
    """The inflation a figure rests on (LBSIM-08): the sheet's own for the findings, fmre's per state for paths."""

    currency: str
    #: Simple, decimal a year; and ``ln(1 + annual_rate)``.
    annual_rate: float
    log_rate: float
    #: Where it comes from, in one sentence (the lbs calibration and its version for the findings).
    source: str


class LbsUpstream(_Frozen):
    artefact_id: str = Field(pattern=_id("LBS"))
    request_hash: str
    calibration_version: str
    contract: str = "lbs-balance-sheet@1.0.0"
    #: sha256 of the sheet's canonical JSON as read.
    sha256: str
    url: Optional[str] = None


class RecordUse(_Frozen):
    """A content record a figure read, and whether it was approved when read."""

    record: str
    #: ``lbs`` for a record of the lbs calibration (read from its provenance), ``lbsim`` for lbsim's own.
    source: Literal["lbs", "lbsim"]
    version: Optional[str] = None
    approved: bool
    published_by: Optional[str] = None
    #: True where the figure is computed although the record is not approved (the draft had no gate).
    read_without_gate: bool = False


class Provenance(_Frozen):
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    upstream: dict[str, Any]
    records: tuple[RecordUse, ...] = ()
    label: Literal["model-derived"] = "model-derived"
    #: ``sample``: a frozen sample for the agents building on lbsim, hand-built where the engine part that makes it
    #: is not built yet (``golden/samples``). An engine artefact is always ``engine``.
    made_by: Literal["engine", "sample"] = "engine"
    sample_note: Optional[str] = None
    #: Every random seed the artefact used, by stream (paths and plan).
    seeds: dict[str, int] = Field(default_factory=dict)
    numpy_version: Optional[str] = None


# ---------------------------------------------------------------------------
# 3.2 Findings, the fast deterministic half
# ---------------------------------------------------------------------------

class Responsibility(_Frozen):
    tier: str
    label: Words
    multiplier: float
    #: False when nobody stated a tier (the modest reading: no management function).
    stated: bool


class EarningInputs(_Frozen):
    E: float
    N: float
    age: float
    qualification: Optional[str]
    earning_power_at_unit: float


class ModelledEarningPower(_Frozen):
    """The one earning-power computation (LBSIM-11)."""

    #: At the BFS full-time week of 40 hours: the figure a reader recognises.
    full_time_chf_per_year: float
    #: The engine's own quantity: income at the 100-hour productive week nobody works.
    at_full_productive_week_chf: float
    monthly_standardised_chf: float
    before_responsibility_chf: float
    responsibility: Responsibility
    inputs: EarningInputs


class StatedEarning(_Frozen):
    #: The person's own expectation at a full pensum once any education is done, today's francs.
    expected_full_pensum_income_chf_per_year: Optional[float]
    #: The age from which it applies: the end of the education, else today.
    from_age: Optional[float]


class CurrentEarning(_Frozen):
    gross_income_chf_per_year: Optional[float]
    #: Hours a week over 42, the ordinary Swiss full-time week (the draft's convention).
    pensum: Optional[float]
    full_pensum_equivalent_chf: Optional[float]


class EducationPlan(_Frozen):
    status: Optional[Literal["none", "in_progress", "planned"]]
    end_year: Optional[int]
    end_age: Optional[float]
    hours_per_week: Optional[float]
    budget_chf_per_year: Optional[float]


class HealthCapacity(_Frozen):
    H: Optional[float]
    work_capacity: Optional[float]
    capacity_basis: Literal["stated", "modelled", "withheld"]


class EarningPower(_Frozen):
    person_id: str
    #: ``available`` when the modelled level could be computed (E, N and the age known).
    status: Literal["available", "not_available"]
    reason: Optional[Words] = None
    modelled: Optional[ModelledEarningPower]
    stated: StatedEarning
    #: ``stated`` when the person gave an expectation; ``modelled`` when the model supplies the level.
    level_basis: LevelBasis
    current: CurrentEarning
    education: EducationPlan
    health: HealthCapacity
    caveats: tuple[Words, ...] = ()


class IncomeYear(_Frozen):
    year: int
    age: float
    gross_chf_per_year: float


class From65(_Frozen):
    ahv_chf_per_year: float
    bvg_chf_per_year: float


class SavingNeed(_Frozen):
    goal_id: str
    #: Nominal: francs of the target date.
    target_chf: float
    target_date: Optional[date]
    years: float
    #: What must be put aside each year at a return of zero.
    zero_return_saving_chf_per_year: float
    #: What this path frees on average until the goal.
    free_cash_chf_per_year: float
    holds: bool


class SavingNeedReal(_Frozen):
    goal_id: str
    #: Today's francs: the nominal target over the price level at the target date.
    target_chf: float
    #: The yearly saving in today's francs that, rising with prices, reaches the nominal target.
    zero_return_saving_chf_per_year: float
    free_cash_chf_per_year: float


class RealSavingView(_Frozen):
    derived: Literal[True] = True
    deflator: InflationUsed
    saving_need: tuple[SavingNeedReal, ...]


class IncomePathViews(_Frozen):
    real: RealSavingView


class IncomePath(_Frozen):
    code: IncomePathCode
    person_id: str
    name: Words
    note: Words
    level_basis: LevelBasis
    pensum_now: float
    pensum_after: float
    education_end_age: Optional[float]
    learning_hours: float
    network_hours: float
    #: Nominal gross income per year, from today to the reference age.
    income: tuple[IncomeYear, ...]
    #: At the reference age, in today's francs (the draft's convention for the flows that fund retirement).
    from_65: From65
    saving_need: tuple[SavingNeed, ...]
    views: IncomePathViews


class ZeroReturn(_Frozen):
    rate: float = 0.0
    note: Words


class Figure(_Frozen):
    value: Optional[float]
    unit: FigureUnit
    basis: Optional[Basis] = None


class FindingWords(_Frozen):
    """One language of a finding: templates with ``{figure}`` placeholders, never a number in the template."""

    title: str
    trigger: str
    why: str
    action: str


class FindingText(_Frozen):
    de: FindingWords
    en: FindingWords


class Finding(_Frozen):
    code: FindingCode
    severity: Severity
    urgency: Urgency
    #: What the action asks of the reader. Never "buy" (LBSIM-17).
    action_kind: ActionKind
    figures: dict[str, Figure]
    text: FindingText
    #: The app's question keys whose answers respond to this finding.
    answers: tuple[str, ...] = ()
    audience: Literal["both"] = "both"

    @model_validator(mode="after")
    def _placeholders(self) -> "Finding":
        names = set(self.figures)
        for lang in (self.text.de, self.text.en):
            for part in (lang.title, lang.trigger, lang.why, lang.action):
                for name in re.findall(r"\{([a-z0-9_]+)\}", part):
                    if name not in names:
                        raise ValueError(f"finding {self.code}: the text names {{{name}}}, which is not a figure")
        return self


class ScheduleEntry(_Frozen):
    when: Urgency
    label: Words
    codes: tuple[FindingCode, ...]


class Unchecked(_Frozen):
    """A rule whose input the sheet lacks: listed, never passed."""

    code: FindingCode
    reason: Words
    #: The app's question keys whose answers would let the rule run.
    missing: tuple[str, ...] = ()
    #: ``plan`` for the one rule only the plan calculation can decide (``goal_not_fundable``).
    answered_by: Optional[Literal["plan"]] = None

    @model_validator(mode="after")
    def _names_what_is_missing(self) -> "Unchecked":
        if not self.missing and self.answered_by is None:
            raise ValueError(f"unchecked rule {self.code} names neither a missing question nor who answers it")
        return self


class InputCheck(_Frozen):
    """Two answers that cannot both be true, or rarely are (the draft's plausibility checks)."""

    code: str
    severity: Literal["impossible", "unlikely"]
    blocks: bool
    title: Words
    question: Words
    figures: dict[str, Figure] = Field(default_factory=dict)
    fields: tuple[str, ...] = ()


class FrontierMove(_Frozen):
    dimension: Literal["pensum", "learning", "network", "spending", "stop_age", "goal_year", "goal_amount"]
    value: float
    label: Words


class FrontierPlan(_Frozen):
    moves: tuple[FrontierMove, ...]
    target_date_year: int
    target_chf: float
    required_chf_per_year: float
    available_chf_per_year: float


class FrontierGoal(_Frozen):
    goal_id: str
    #: The return the test ran at: ``zero`` (0 %) or ``stated`` (the household's own expectation).
    rate_basis: Literal["zero", "stated"]
    rate: float
    holds_today: bool
    required_today_chf_per_year: Optional[float]
    available_today_chf_per_year: Optional[float]
    cheapest_effort: Optional[FrontierPlan]
    cheapest_goal_change: Optional[FrontierPlan]
    cheapest_combination: Optional[FrontierPlan]
    combinations_tried: int
    refused: Optional[Words] = None


class NextQuestion(_Frozen):
    question_key: str
    #: The largest movement answering it can produce in a figure the client reads, CHF.
    spread_chf: Optional[float]
    headline: Optional[Literal["capital_need", "gap_per_year", "free_cash", "taxes", "bridge_need"]]
    question: Words


class GateItem(_Frozen):
    code: str
    kind: Literal["contradiction", "blocking_field", "unresolved_goal", "pending", "ask"]
    title: Words
    fields: tuple[str, ...] = ()


class Gate(_Frozen):
    stage: Literal["open", "report"]
    blocking: tuple[GateItem, ...]
    optional: tuple[GateItem, ...]
    open_count: int
    optional_count: int


class Assumption(_Frozen):
    """A figure lbsim used that the household did not supply. Every figure resting on one names it."""

    key: str
    value: Optional[float]
    unit: Optional[Literal["rate", "chf", "chf_per_year", "share", "years", "hours_per_week"]]
    text: Words
    replaced_by: Words


class LifeBalanceFindings(_Frozen):
    """The fast deterministic half (``lbsim-findings@1.0.0``): lbs only, seconds."""

    contract_version: Literal["lbsim-findings@1.0.0"] = "lbsim-findings@1.0.0"
    artefact_id: str = Field(pattern=_id("LSF"))
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    as_of: date
    calibration_version: str
    inflation: InflationUsed
    basis: Literal["nominal"] = "nominal"
    #: The adult the plan is for; income paths and the findings are about this person's plan.
    principal: str
    earning_power: tuple[EarningPower, ...]
    income_paths: tuple[IncomePath, ...]
    zero_return: ZeroReturn
    findings: tuple[Finding, ...]
    schedule: tuple[ScheduleEntry, ...]
    unchecked: tuple[Unchecked, ...]
    input_checks: tuple[InputCheck, ...]
    frontier: tuple[FrontierGoal, ...]
    next_questions: tuple[NextQuestion, ...]
    gate: Gate
    assumptions: tuple[Assumption, ...]
    limits: tuple[Words, ...]
    provenance: Provenance
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# 3.3 Paths, the Monte Carlo under the stated plan
# ---------------------------------------------------------------------------

class Policy(_Frozen):
    kind: Literal["stated_plan"] = "stated_plan"
    spending_chf_per_year: float
    spending_indexed: Literal[True] = True
    pensum: float
    saving_source: Literal["cash_flow", "stated_contribution"]
    #: Set when spending was not stated and the fallback applied; says which.
    fallback: Optional[Words] = None


class Quantiles(_Frozen):
    p05: tuple[float, ...]
    p10: tuple[float, ...]
    p25: tuple[float, ...]
    p50: tuple[float, ...]
    p75: tuple[float, ...]
    p90: tuple[float, ...]
    p95: tuple[float, ...]

    @model_validator(mode="after")
    def _shape(self) -> "Quantiles":
        lengths = {len(getattr(self, q)) for q in QUANTILES}
        if len(lengths) != 1:
            raise ValueError("every quantile series has the same length (horizon + 1 year-end values)")
        return self


class RealQuantiles(Quantiles):
    """Quantiles of the per-path deflated values (LBSIM-10), computed from the same draws: not deflated quantiles."""

    derived: Literal[True] = True
    #: The deflator, in words: each path's own cumulative inflation.
    deflator: str


class BandSet(_Frozen):
    nominal: Quantiles
    real: RealQuantiles


class GoalTarget(_Frozen):
    nominal_chf: float
    real_chf: float
    amount_basis: Literal["today", "future"]
    date: date


class GoalChance(_Frozen):
    goal_id: str
    kind: Literal["home", "retirement", "capital"]
    measure: GoalMeasure
    target: GoalTarget
    #: One chance per goal and Regime, in the goal's own basis (LBSIM-09), independent of the view.
    chance: float = Field(ge=0.0, le=1.0)
    chance_basis: Basis
    n_reached: int
    median_shortfall_chf: float


class RegimeInflation(_Frozen):
    source: str
    #: How many of the 25 states carry each fmre label (``measured``, ``fallback``, ``scenario``, ...).
    labels_summary: dict[str, int]


class RegimePaths(_Frozen):
    key: RegimeKey
    label: Words
    regime_id: str
    kind: Literal["base", "scenario"]
    #: How long the scenario's projected months drive the draws before the base Regime takes over.
    scenario_years: Optional[int] = None
    return_set_id: str
    inflation_pass_through: Optional[str] = None
    inflation: RegimeInflation
    #: Keyed by series: ``net_worth`` and each goal measure present (``drawable``, ``deposit_eligible``,
    #: ``retirement_capital``). Year-end values, recorded BEFORE any goal of that date is carried out: at a goal's
    #: date the band is the value its chance is judged on; a deposit or a lump sum paid then shows from the next
    #: year end on.
    bands: dict[str, BandSet]
    goals: tuple[GoalChance, ...]

    @field_validator("bands")
    @classmethod
    def _series(cls, value: dict[str, BandSet]) -> dict[str, BandSet]:
        unknown = sorted(set(value) - set(BAND_SERIES))
        if unknown:
            raise ValueError(f"unknown band series {unknown}")
        return value


class AllocationInstrument(_Frozen):
    instrument_id: str
    name: str
    role: Literal["Gain", "Income", "Stabilisation", "Protection"]
    weight: float


class Curves(_Frozen):
    target: tuple[float, ...]
    achieved: tuple[float, ...]
    derived: bool = False

    @model_validator(mode="after")
    def _states(self) -> "Curves":
        if len(self.target) != N_STATES or len(self.achieved) != N_STATES:
            raise ValueError(f"a curve has {N_STATES} states")
        return self


class CurvesView(_Frozen):
    nominal: Curves
    real: Curves
    #: ``ln(1 + inflation_s)`` per state, the shift between the two bases.
    log_inflation: tuple[float, ...]
    inflation_labels: tuple[str, ...]


class AllocationView(_Frozen):
    """Charts 1 and 2: the weights by instrument and role, the target against the reached curve."""

    allocation_id: str = Field(pattern=_id("PCP"))
    mandate_name: str
    currency: Literal["CHF"]
    allocation_basis: Basis
    date: date
    regime_id: str
    instruments: tuple[AllocationInstrument, ...]
    by_role: dict[str, float]
    #: The base Regime's state distribution (``Allocation.curves.regime``).
    state_probability: tuple[float, ...]
    curves: CurvesView


class ReproductionCheck(_Frozen):
    achieved_reproduced: bool
    max_abs_diff: float


class PropertyModel(_Frozen):
    nominal_log_growth: float
    inflation_beta: float
    inflation_anchor_log: float
    sigma: float
    rho_with_market: float


class MarketModel(_Frozen):
    rule: Words
    reversion_years: float
    state_persistence: float
    weights: Literal["renormalised"] = "renormalised"
    check: ReproductionCheck
    property: PropertyModel
    pass_through: dict[str, Any]


class LifeBalancePaths(_Frozen):
    """The Monte Carlo under the stated plan, per Regime (``lbsim-paths@1.0.0``)."""

    contract_version: Literal["lbsim-paths@1.0.0"] = "lbsim-paths@1.0.0"
    artefact_id: str = Field(pattern=_id("LSP"))
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    findings_artefact_id: str = Field(pattern=_id("LSF"))
    allocation_id: str = Field(pattern=_id("PCP"))
    as_of: date
    calibration_version: str
    start_year: int
    horizon_years: int
    n_paths: int
    seed: int
    steps_per_year: Literal[12] = 12
    income_path: IncomePathCode
    basis: Literal["nominal"] = "nominal"
    policy: Policy
    regimes: tuple[RegimePaths, ...]
    allocation_view: AllocationView
    market_model: MarketModel
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _bands(self) -> "LifeBalancePaths":
        for r in self.regimes:
            for series, band in r.bands.items():
                for part in (band.nominal, band.real):
                    if len(part.p50) != self.horizon_years + 1:
                        raise ValueError(f"{r.key}/{series}: a band has horizon + 1 year-end values")
        return self


# ---------------------------------------------------------------------------
# 3.4 The plan, the optimiser result (stored only for a finished solve)
# ---------------------------------------------------------------------------

class PlanGoal(_Frozen):
    goal_id: str
    kind: Literal["home", "retirement", "capital"]
    #: ``1 - epsilon`` (``optimiser.confidence``, 0.90 by the owner's decision of 29.09.2026).
    confidence: float = Field(gt=0.0, lt=1.0)


class ActionNow(_Frozen):
    """The draft's ``u0`` in plain units: what the calculation assumes for this period, never a recommendation."""

    work_share: float
    learning_hours_per_week: float
    network_hours_per_week: float
    rest_hours_per_week: float
    consumption_chf_per_year: float
    saving_chf_per_year: float
    education_spend_chf_per_year: float
    network_spend_chf_per_year: float
    amortisation_chf_per_year: float


class PlanChance(_Frozen):
    in_sample: float = Field(ge=0.0, le=1.0)
    out_of_sample: float = Field(ge=0.0, le=1.0)
    n_out_of_sample: int
    seed_out: int


class Reachable(_Frozen):
    amount_chf: float
    at_confidence: float


class ExchangeRate(_Frozen):
    winner: Literal["networking", "overtime", "undetermined"]
    ratio: Optional[float]
    dominant: Optional[str]


class Costates(_Frozen):
    W: float
    E: float
    N: float
    H: float


class PlanControls(_Frozen):
    tau_Y: float
    tau_E: float
    tau_N: float
    tau_H: float
    C: float
    m_E: float
    m_N: float
    p_A: float


class ControlStep(_Frozen):
    t_years: float
    dt_years: float
    controls: PlanControls


class PlanHorizon(_Frozen):
    solved_years: float
    total_years: float
    beyond_cap_rule: Optional[Literal["zero_return_terminal"]]


class SolverRecord(_Frozen):
    return_status: str
    iterations: int
    wall_clock_s: float
    seed: int
    seed_attempt: int
    M_opt: int
    grid: tuple[float, ...]
    casadi_version: str
    ipopt_version: Optional[str]


class LifeBalancePlan(_Frozen):
    """The plan calculation (``lbsim-plan@1.0.0``). No figure from a non-converged or timed-out solve: such a run
    is ``failed`` and no plan artefact is written."""

    contract_version: Literal["lbsim-plan@1.0.0"] = "lbsim-plan@1.0.0"
    artefact_id: str = Field(pattern=_id("LSO"))
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    paths_artefact_id: str = Field(pattern=_id("LSP"))
    calibration_version: str
    outcome: Literal["solved", "goal_not_fundable", "undetermined"]
    goal: PlanGoal
    extra_goals: tuple[str, ...] = ()
    action_now: ActionNow
    #: How every surface frames ``action_now`` (owner, 29.09.2026): what the calculation assumes.
    framing: Words
    chance: PlanChance
    shortfall_cvar_chf: float
    reachable: Optional[Reachable] = None
    exchange_rate: ExchangeRate
    costates: Costates
    control_path: tuple[ControlStep, ...]
    horizon: PlanHorizon
    solver: SolverRecord
    basis: Literal["nominal"] = "nominal"
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _outcome(self) -> "LifeBalancePlan":
        if self.outcome == "goal_not_fundable" and self.reachable is None:
            raise ValueError("an unfundable goal states what is reachable")
        return self


# ---------------------------------------------------------------------------
# 3.5 Runs, the optimiser status and the outlook
# ---------------------------------------------------------------------------

RunKind = Literal["outlook", "plan"]
RunState = Literal["queued", "running", "succeeded", "failed"]
FailureKind = Literal["timed_out", "superseded", "cancelled", "solver", "upstream"]


class NotMade(_Frozen):
    artefact: Literal["findings", "paths", "plan"]
    #: A reason key (``no_allocation``, ``not_requested``, ...) and the plain sentence for people.
    reason: str
    text: Words


class RunAccepted(_Frozen):
    run_id: str = Field(pattern=_id("RUN"))
    kind: RunKind
    status: RunState
    idempotency_key: str = Field(pattern=_id("IDK"))
    cached: bool
    findings_artefact_id: Optional[str] = Field(default=None, pattern=_id("LSF"))
    paths_artefact_id: Optional[str] = Field(default=None, pattern=_id("LSP"))
    plan_run_id: Optional[str] = Field(default=None, pattern=_id("RUN"))
    not_made: tuple[NotMade, ...] = ()


class Progress(_Frozen):
    phase: Literal["restore", "best_life"]
    start: int
    of: int
    seed_attempt: int
    elapsed_s: float


class RunStatus(_Frozen):
    run_id: str = Field(pattern=_id("RUN"))
    kind: RunKind
    status: RunState
    failure_kind: Optional[FailureKind] = None
    idempotency_key: str = Field(pattern=_id("IDK"))
    requested_by: RequestedBy
    queued_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    wall_clock_ms: Optional[float] = None
    budget_s: Optional[float] = None
    progress: Optional[Progress] = None
    #: Ids and options only, never a copy of client data.
    request: dict[str, Any]
    artefact_ids: tuple[str, ...] = ()
    error: Optional[str] = None


class PlanOutlook(_Frozen):
    state: Literal["ready", "calculating", "waiting_for_allocation", "not_possible", "not_requested"]
    reason: Optional[Words] = None
    run: Optional[RunStatus] = None
    artefact: Optional[LifeBalancePlan] = None
    elapsed_s: Optional[float] = None
    budget_s: Optional[float] = None


class LifeBalanceOutlook(_Frozen):
    """``GET /outlook``: not stored. Never mixes sheets."""

    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    findings: Optional[LifeBalanceFindings] = None
    paths: Optional[LifeBalancePaths] = None
    plan: PlanOutlook

    @model_validator(mode="after")
    def _one_sheet(self) -> "LifeBalanceOutlook":
        for part in (self.findings, self.paths, self.plan.artefact):
            if part is not None and part.life_balance_sheet_id != self.life_balance_sheet_id:
                raise ValueError("an outlook never mixes sheets")
        return self


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationReport(_Frozen):
    """``POST /validate`` (``lbsim-validation@1.0.0``): what can be computed, blocked and assumed, not stored."""

    contract_version: Literal["lbsim-validation@1.0.0"] = "lbsim-validation@1.0.0"
    ok: bool
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_id("LBS"))
    calibration_version: Optional[str]
    #: Why nothing can be computed (an unknown calibration, a client mismatch). Plain sentences.
    problems: tuple[Words, ...] = ()
    #: ``workflow.open_items`` on the sheet: what blocks, what would improve the figures.
    gate: Optional[Gate] = None
    unchecked: tuple[Unchecked, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    not_made: tuple[NotMade, ...] = ()
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# Calibration (lbsim-calibration@1.0.0)
# ---------------------------------------------------------------------------

#: The records a calibration must carry.
RECORD_NAMES: tuple[str, ...] = ("social-insurance", "canton-tax", "findings-text")


class Behaviour(_Frozen):
    """Which of lbsim's decisions a calibration applies (LBSIM-13). 1.0.0 applies none: it reproduces the draft."""

    #: LBSIM-08. ``none``: no inflation, the draft's reading. ``sheet``: the sheet's ``real_view.inflation``.
    inflation: Literal["none", "sheet"]
    #: LBSIM-11. ``draft``: ``Params.earning_power_at_unit`` (0.75) and the draft's level. ``record``: the lbs
    #: ``human-capital`` record's ``earning_power_at_unit`` and the one earning-power computation's level.
    earning_power: Literal["draft", "record"]
    #: LBSIM-07. ``draft``: the draft's Gaussian ``mu_M``/``sigma_M`` and the tilt. ``allocation``: the pcp
    #: Allocation's weights on fmre's per-state profiles, theta fixed at 1.
    market: Literal["draft", "allocation"]
    #: LBSIM-14: the currencies an Allocation may be in.
    currencies: tuple[str, ...] = ("CHF",)
    #: DECISIONS P-9 (calibration 1.2.0): ``corrected`` credits an income path only with what its own education and
    #: networking add (not the draft's autonomous 15 % a year of expertise growth), and applies a path's pensum
    #: from today when no education is planned. ``None`` (1.0.0, 1.1.0): the draft's paths. Left out of the
    #: canonical form while ``None``, so 1.0.0 and 1.1.0 keep their bytes and hashes.
    income_paths: Optional[Literal["corrected"]] = None


class Retirement(_Frozen):
    #: Owner, 29.09.2026: capital needed = yearly retirement need / 0.03. An assumption, and named as one.
    withdrawal_rate: float = Field(gt=0.0, lt=1.0)
    withdrawal_rate_is_assumption: Literal[True] = True


class Market(_Frozen):
    reversion_years: float = Field(ge=0.0)
    state_persistence: float = Field(ge=0.0, le=1.0)
    #: A scenario Regime's projected months drive this many years, then the base Regime ("shock, then normal").
    scenario_years: int = Field(ge=1)
    wage_pass_through: float
    spending_pass_through: float


class PropertyParameters(_Frozen):
    nominal_log_growth: float
    inflation_beta: float
    inflation_anchor_log: float
    sigma: float = Field(ge=0.0)
    rho_with_market: float = Field(ge=-1.0, le=1.0)


class Optimiser(_Frozen):
    """The draft's ``cases.run_case`` and ``optim.problem.solve_case`` settings, verbatim, and the plan grid."""

    #: ``1 - epsilon``. Owner, 29.09.2026: 0.90 for everyone.
    confidence: float = Field(gt=0.0, lt=1.0)
    M_opt: int
    M_eval: int
    n_starts: int
    restore_starts: int
    max_iter: int
    seed_retries: int
    cvar_tol: float
    #: ``(until_years, dt_years)`` rungs: 0.5-year steps to 10 years, 1-year steps beyond (section 5). The draft's
    #: ``run_case`` chose one step for the whole horizon (0.5 up to 10 years, 1.0 beyond).
    grid: tuple[tuple[float, float], ...]
    grid_rule: Literal["draft_single_step", "variable"]
    #: The solve cap in years (section 5); beyond it a goal is the zero-return terminal requirement. None (1.0.0 to
    #: 1.2.0): the grid's last rung and ``config.yaml``'s ``optimiser.max_solve_horizon_years`` decide. Set from
    #: 1.3.0 (owner, 29.09.2026: 10 years). Left out of the canonical form while unset, so the older seeds keep
    #: their hashes.
    max_solve_horizon_years: Optional[float] = Field(default=None, gt=0.0)


class Calibration(_Frozen):
    contract_version: Literal["lbsim-calibration@1.0.0"] = "lbsim-calibration@1.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    #: Content records, each with its ``_about`` approval metadata: ``social-insurance`` and ``canton-tax`` (the
    #: draft's two tables) and ``findings-text`` (LBSIM-17).
    records: dict[str, dict[str, Any]]
    #: Overrides of the draft's ``Params()`` (empty: the draft's defaults, which is what 1.0.0 carries).
    params: dict[str, float] = Field(default_factory=dict)
    behaviour: Behaviour
    retirement: Retirement
    market: Market
    property: PropertyParameters
    optimiser: Optimiser

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$", value):
            raise ValueError(f"calibration version {value!r} is not semantic")
        return value

    @model_validator(mode="after")
    def _records(self) -> "Calibration":
        missing = sorted(set(RECORD_NAMES) - set(self.records))
        if missing:
            raise ValueError(f"the calibration lacks the records {missing}")
        for name, record in self.records.items():
            if not isinstance(record.get("_about"), dict):
                raise ValueError(f"record {name} carries no _about block, so its approval cannot be read")
        from .model.params import Params
        unknown = sorted(set(self.params) - set(Params.__dataclass_fields__))
        if unknown:
            raise ValueError(f"params {unknown} are not fields of the draft's Params")
        return self


# ---------------------------------------------------------------------------
# Upstream mirrors (extra ignored; only what lbsim reads)
# ---------------------------------------------------------------------------

# -- lbs 8013 -----------------------------------------------------------------

class LbsEarningPowerAnswers(_Mirror):
    expected_full_pensum_income: Optional[float] = None
    responsibility: Optional[str] = None
    sector: Optional[str] = None
    education_status: Optional[Literal["none", "in_progress", "planned"]] = None
    education_end_year: Optional[int] = None
    education_hours: Optional[float | str] = None
    education_budget_per_year: Optional[float] = None
    health_work_capacity: Optional[float] = None


class LbsHumanCapitalAnswers(_Mirror):
    qualification_highest: Optional[str] = None
    education_recent: Optional[str] = None
    health_withheld: bool = False
    hours_per_week: Optional[float] = None
    rest_hours: Optional[str] = None
    hours_learning: Optional[float] = None
    hours_network: Optional[float] = None


class LbsAhvFacts(_Mirror):
    mdje: Optional[float] = None
    contribution_years_missing: Optional[int] = None


class LbsPerson(_Mirror):
    person_id: str
    kind: Literal["adult", "dependant"]
    age: Optional[int] = None
    stated_gross_income: Optional[float] = None
    human_capital: LbsHumanCapitalAnswers = Field(default_factory=LbsHumanCapitalAnswers)
    ahv: LbsAhvFacts = Field(default_factory=LbsAhvFacts)
    earning_power: Optional[LbsEarningPowerAnswers] = None


class LbsHousehold(_Mirror):
    composition_as_of: date
    persons: tuple[LbsPerson, ...]
    principal: Optional[str] = None


class LbsPosition(_Mirror):
    position_id: str
    role: str
    capital_type: Literal["human", "financial"]
    magnitude: Optional[float] = None
    unit: Optional[Literal["chf", "chf_per_year", "share_of_total"]] = None
    stock_kind: Optional[Literal["asset", "liability"]] = None
    liquidity: Optional[str] = None
    vessel: Optional[Literal["free", "pillar_2", "pillar_3a", "real_asset"]] = None
    owner: Optional[str] = None
    active: bool = True


class LbsGoal(_Mirror):
    goal_id: str
    kind: Literal["property", "retirement", "other"]
    target_amount: Optional[float] = None
    target_date: Optional[date] = None
    occupancy: Optional[str] = None
    owners: tuple[str, ...] = ()
    amount_basis: Optional[Literal["today", "future"]] = None


class LbsFacts(_Mirror):
    canton: Optional[str] = None
    civil_status: Optional[str] = None
    has_no_liabilities: bool = False
    stop_work_age: Optional[float] = None
    legal_documents: Optional[tuple[str, ...]] = None
    mortgage_fixed_until: Optional[date] = None
    amortisation_mode: Optional[Literal["direct", "indirect"]] = None
    own_use_share: Optional[float] = None
    pillar3a_contribution_per_year: Optional[float] = None


class LbsRisk(_Mirror):
    stated_loss: Optional[float] = None
    spend_now_per_year: Optional[float] = None
    gross_income_per_year: Optional[float] = None
    plan_until_age: Optional[float] = None
    mortgage: Optional[float] = None
    mortgage_rate_pct: Optional[float] = None
    amortisation_per_year: Optional[float] = None


class LbsMandate(_Mirror):
    goal_id: str
    annual_contribution: Optional[float] = None
    contribution_indexed: Optional[bool] = None


class LbsRequest(_Mirror):
    contract_version: Literal["lbs-request@1.0.0"]
    client_ref: str
    as_of: date
    calibration_version: Optional[str] = None
    household: Optional[LbsHousehold] = None
    positions: tuple[LbsPosition, ...] = ()
    goals: tuple[LbsGoal, ...] = ()
    facts: LbsFacts = Field(default_factory=LbsFacts)
    risk: LbsRisk = Field(default_factory=LbsRisk)
    mandate: Optional[LbsMandate] = None


class LbsArtefactRequest(_Mirror):
    """``GET /artefacts/{id}/request`` (LBS-40)."""

    artefact_id: str
    request_hash: str
    contract_version: Literal["lbs-request@1.0.0"]
    request: LbsRequest


class LbsCapital(_Mirror):
    key: Literal["E", "N", "H"]
    value: Optional[float] = None
    source: Optional[str] = None
    absent_because: Optional[str] = None


class LbsPersonHumanCapital(_Mirror):
    person_id: str
    E: LbsCapital
    N: LbsCapital
    H: LbsCapital
    caveats: tuple[str, ...] = ()


class LbsTotals(_Mirror):
    financial_assets: Optional[float] = None
    liabilities: Optional[float] = None
    net_worth: Optional[float] = None
    by_vessel: dict[str, Optional[float]] = Field(default_factory=dict)
    drawable: Optional[float] = None
    household_income: Optional[float] = None


class LbsInflationUse(_Mirror):
    currency: str
    index: str
    annual_rate: float
    log_rate: float
    label: str
    source: str


class LbsBasisAmount(_Mirror):
    basis: Literal["nominal", "real"]
    amount: Optional[float] = None
    as_at: Optional[date] = None


class LbsGoalBasisView(_Mirror):
    goal_id: str
    kind: Literal["property", "retirement", "other"]
    unit: Literal["chf", "chf_per_year"]
    amount_basis: Literal["today", "future"]
    amount_basis_stated: bool
    stated_amount: Optional[float] = None
    horizon_years: Optional[float] = None
    price_level: Optional[float] = None
    nominal: LbsBasisAmount
    real: LbsBasisAmount


class LbsRealView(_Mirror):
    currency: str
    inflation: LbsInflationUse
    contribution_indexed: bool
    goals: tuple[LbsGoalBasisView, ...] = ()


class LbsMandateProposal(_Mirror):
    status: Literal["available"]
    goal_id: str
    goal_kind: str
    target_chf: Optional[float] = None
    currency: str


class LbsNotAvailable(_Mirror):
    status: Literal["not_available"]
    reason: str


class LbsRecordUse(_Mirror):
    record: str
    approved: bool
    published_by: Optional[str] = None
    read_without_gate: bool = False


class LbsProvenance(_Mirror):
    engine_version: str
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    request_hash: str
    as_of: date
    records: tuple[LbsRecordUse, ...] = ()


class LbsSheet(_Mirror):
    """``lbs-balance-sheet@1.0.0``, the fields lbsim reads."""

    contract_version: Literal["lbs-balance-sheet@1.0.0"]
    artefact_id: str = Field(pattern=_id("LBS"))
    client_ref: str
    as_of: date
    calibration_version: str
    totals: LbsTotals
    human_capital: tuple[LbsPersonHumanCapital, ...] = ()
    mandate_proposal: LbsMandateProposal | LbsNotAvailable
    provenance: LbsProvenance
    real_view: Optional[LbsRealView] = None


class LbsCalibration(_Mirror):
    """``lbs-calibration@1.3.0``: lbsim reads ``human-capital``, ``ahv-pension``, ``bvg-projection`` and
    ``property-funding`` with their approval state."""

    contract_version: str
    version: str
    records: dict[str, dict[str, Any]]


# -- pcp 8007 -----------------------------------------------------------------

class PcpInstrument(_Mirror):
    instrument_id: str
    name: str
    role: Literal["Gain", "Income", "Stabilisation", "Protection"]
    weight: float
    raw_weight: float


class PcpCurves(_Mirror):
    target: tuple[float, ...]
    achieved: tuple[float, ...]
    regime: tuple[float, ...]


class PcpProvenance(_Mirror):
    regime_id: str
    return_set_id: str
    currency: Optional[str] = None
    regime_weights: Optional[dict[str, float]] = None
    #: ``{from, to, states, reason}`` when a real Allocation fell back to a hard currency (PCP-23); refused.
    hard_currency_fallback: Optional[dict[str, Any]] = None


class PcpAllocation(_Mirror):
    """``pcp-allocation@1.0.0``, the fields lbsim reads."""

    contract_version: Literal["pcp-allocation@1.0.0"]
    artefact_id: str = Field(pattern=_id("PCP"))
    regime_id: str
    return_set_id: str
    #: ``None`` only on Allocations published before PCP-18; lbsim then refuses it (LBSIM-14).
    currency: Optional[str] = None
    client: str
    mandate_name: str
    date: date
    #: PCP-22: stated in the JSON when ``real``; a body without it is nominal.
    basis: Literal["nominal", "real"] = "nominal"
    instruments: tuple[PcpInstrument, ...]
    weights_by_role: dict[str, float]
    curves: PcpCurves
    provenance: PcpProvenance


# -- aggregation 8004 ---------------------------------------------------------

class AggregationEconomy(_Mirror):
    code: str
    #: One entry per date: 25 state probabilities, or ``None`` where the economy was not assessed.
    distribution: tuple[Optional[tuple[float, ...]], ...]


class AggregationScenarioProvenance(_Mirror):
    policy: str
    base_regime_id: str
    horizon_months: int
    projected_from: Optional[str] = None


class AggregationProvenance(_Mirror):
    regime_id: str
    scenario: Optional[AggregationScenarioProvenance] = None


class AggregationRegime(_Mirror):
    contract_version: Literal["aggregation-regime@1.0.0"]
    regime_id: str
    n_states: int
    dates: tuple[str, ...]
    economies: tuple[AggregationEconomy, ...]
    provenance: AggregationProvenance


class AggregationScenarioListed(_Mirror):
    regime_id: str
    policy: str
    base_regime_id: str


class AggregationScenarioPolicy(_Mirror):
    policy: str
    label_en: str
    label_de: str


# -- fmre 8006 ----------------------------------------------------------------

class FmreState(_Mirror):
    state: int
    value: float


class FmreProfile(_Mirror):
    key: str
    unit: Literal["annualised_log_return"]
    states: tuple[FmreState, ...]


class FmrePassThrough(_Mirror):
    calibration_version: str
    calibration_id: str


class FmreProvenance(_Mirror):
    regime_id: str
    inflation_pass_through: Optional[FmrePassThrough] = None


class FmreReturnSet(_Mirror):
    return_set_id: str
    contract_version: Literal["rs@1.0.0"]
    instrument_profiles: tuple[FmreProfile, ...]
    provenance: FmreProvenance


class FmreInflationState(_Mirror):
    state: int
    inflation: float
    log_inflation: float
    label: str


class FmreInflation(_Mirror):
    """``GET /v1/inflation``: unversioned; a field mirror, its sha256 recorded."""

    currency: str
    states: tuple[FmreInflationState, ...]
    regime_id: Optional[str] = None
    regime_kind: Optional[str] = None
    source: Optional[str] = None
