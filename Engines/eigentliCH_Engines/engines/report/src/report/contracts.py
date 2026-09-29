"""Contracts: every model ``report`` consumes or produces.

Inbound, from upstream engines, mirrored here and never imported (Engine Building Guide section 1). Each
mirror is partial: the fields the report reads, the version pinned exactly, everything else ignored.

* ``Allocation`` from ``pcp`` (``pcp-allocation@1.0.0``), ``GET /allocation/{id}`` on 8007.
* ``LifeBalanceSheet`` from ``lbs`` (``lbs-balance-sheet@1.0.0``), ``GET /artefacts/{id}`` on 8013. Mirrored
  from lbs's final ``contracts.py`` of 28.09.2026; a section lbs could not compute (``status:
  not_available``) is read as such and reported as a stated fact, never as a number (REP-09).

Own contracts, frozen, extra fields forbidden:

* ``ReportRequest`` (``report-request@1.0.0``), body of ``POST /run`` and ``POST /report``.
* ``Report`` (``report@1.0.0``): the facts (every figure with its source: engine, artefact id and JSON
  path), the sections in their fixed order with their prose and its check, the rendered HTML, the
  provenance and the notice.
* ``Calibration`` (``report-calibration@1.0.0``): prose generation, the number check, the reject rules and
  the section texts. Immutable per version.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSIONS: dict[str, str] = {
    "ReportRequest": "report-request@1.0.0",
    "Report": "report@1.0.0",
    "Calibration": "report-calibration@1.0.0",
    "Allocation(pcp)": "pcp-allocation@1.0.0",
    "LifeBalanceSheet(lbs)": "lbs-balance-sheet@1.0.0",
    "LifeBalanceFindings(lbsim)": "lbsim-findings@1.0.0",
    "LifeBalancePaths(lbsim)": "lbsim-paths@1.0.0",
    "LifeBalancePlan(lbsim)": "lbsim-plan@1.0.0",
}

NOTICE = "Model-derived research output. Not investment advice."

Language = Literal["de", "en"]
EngineName = Literal["pcp", "lbs", "lbsim"]
#: lbsim's three artefact kinds, by the prefix of their id (REP-32): at most one source per engine and kind.
LBSIM_KINDS: dict[str, str] = {"LSF": "findings", "LSP": "paths", "LSO": "plan"}


def source_kind(engine: str, artefact_id: str) -> str:
    """The kind of a source: the engine, or for lbsim the engine and the artefact kind its id's prefix names."""
    if engine != "lbsim":
        return engine
    kind = LBSIM_KINDS.get(artefact_id.split("-", 1)[0])
    if kind is None:
        raise ValueError(f"an lbsim source is a findings (LSF-), paths (LSP-) or plan (LSO-) artefact, not "
                         f"{artefact_id!r}")
    return f"lbsim.{kind}"
#: The basis of return and goal figures (REP-27): ``nominal`` (the default everywhere) or ``real``, in today's
#: francs, with ``real = nominal - ln(1 + inflation)`` for log returns.
Basis = Literal["nominal", "real"]

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Upstream(BaseModel):
    """A partial mirror: reads the named fields, ignores the rest."""

    model_config = ConfigDict(frozen=True, extra="ignore")


# ---------------------------------------------------------------------------
# Upstream mirrors: pcp
# ---------------------------------------------------------------------------

class InstrumentWeight(_Upstream):
    instrument_id: str
    name: str
    role: str
    weight: float
    coverage: str


class PortfolioMap(_Upstream):
    roles: tuple[str, ...]
    scenarios: tuple[str, ...]


class Diagnostics(_Upstream):
    objective: float
    objective_floor: float
    weight_leverage: Optional[float]
    solver_method: str
    solver_status: str
    success: bool
    constraint_rows: int
    binding: tuple[dict[str, Any], ...]
    notes: tuple[str, ...] = ()


class Coverage(_Upstream):
    weight_on_weak_profiles: float
    warnings: tuple[str, ...] = ()


class AllocationProvenance(_Upstream):
    snapshot_id: str
    as_of: str
    date: str
    engine_version: str
    calibration_version: str


class AllocationCurves(_Upstream):
    """The Mandate's target return per state and what the weights reach, 25 states from crisis to boom, on the
    Allocation's basis (chart 2, REP-34)."""

    target: tuple[float, ...]
    achieved: tuple[float, ...]


class Allocation(_Upstream):
    """``pcp-allocation@1.0.0``, as ``report`` reads it."""

    contract_version: Literal["pcp-allocation@1.0.0"]
    artefact_id: str
    regime_id: str
    return_set_id: str
    mandate_id: str
    client: str
    mandate_name: str
    date: str
    calibration_version: str
    release_state: Literal["unreleased"]
    instruments: tuple[InstrumentWeight, ...]
    budget_met: bool
    weights_by_role: dict[str, float]
    portfolio_map: PortfolioMap
    diagnostics: Diagnostics
    coverage: Coverage
    provenance: AllocationProvenance
    #: Since pcp's real view (REP-28): the basis of the Mandate's target curve and of the ReturnSet it was solved
    #: on. An Allocation without it counts as ``nominal``.
    basis: Optional[Basis] = None
    #: Chart 2 (REP-34); an Allocation without curves gets no chart.
    curves: Optional[AllocationCurves] = None


# ---------------------------------------------------------------------------
# Upstream mirrors: lbs
# ---------------------------------------------------------------------------

class LbsTotals(_Upstream):
    financial_assets: Optional[float]
    human_assets: Optional[float]
    total_assets: Optional[float]
    liabilities: Optional[float]
    net_worth: Optional[float]
    identity_holds: Optional[bool]
    by_vessel: dict[str, Optional[float]]
    drawable: Optional[float]
    household_income: Optional[float]
    household_income_basis: str


class LbsGridCell(_Upstream):
    role: str
    capital_type: str
    display: str
    assets_chf: Optional[float]
    liabilities_chf: Optional[float]
    flows_chf_per_year: Optional[float]


class LbsHouseholdPerson(_Upstream):
    person_id: str
    kind: str
    age: Optional[int]


class LbsHousehold(_Upstream):
    stated: bool
    composition_as_of: Optional[str]
    adults: tuple[LbsHouseholdPerson, ...]
    dependants: tuple[LbsHouseholdPerson, ...]


class LbsNotAvailable(_Upstream):
    """A section lbs could not compute. The report states it, with its reason; it never becomes a number."""

    status: Literal["not_available"]
    reason: str
    record: Optional[str] = None


class LbsCapital(_Upstream):
    key: Literal["E", "N", "H"]
    value: Optional[float]
    absent_because: Optional[str] = None


class LbsHumanCapital(_Upstream):
    person_id: str
    E: LbsCapital
    N: LbsCapital
    H: LbsCapital
    earning_power: LbsNotAvailable


class LbsAhv(_Upstream):
    status: Literal["available"]
    monthly: float
    yearly: float
    years: Optional[int]
    at_minimum: bool
    at_maximum: bool


class LbsBvg(_Upstream):
    status: Literal["available"]
    from_age: int
    to_age: int
    opening_balance: float
    closing_balance: float
    interest_rate: float
    conversion_rate: float
    monthly_pension: float
    yearly_pension: float


class LbsPensions(_Upstream):
    person_id: str
    ahv: Union[LbsAhv, LbsNotAvailable] = Field(discriminator="status")
    bvg: Union[LbsBvg, LbsNotAvailable] = Field(discriminator="status")


class LbsCoupleCap(_Upstream):
    status: Literal["available"]
    uncapped_monthly: float
    monthly: float
    yearly: float
    cap_binds: bool


class LbsProperty(_Upstream):
    goal_id: str
    verdict: str
    price_chf: Optional[float]
    target_date: Optional[str]
    binds_on: tuple[str, ...] = ()
    undetermined_because: tuple[str, ...] = ()
    #: From lbs calibration 1.4.0: ``real``, ``price_chf`` is in today's francs (REP-27).
    basis: Optional[Literal["real"]] = None


class LbsLiquidity(_Upstream):
    goal_id: str
    gap_chf: Optional[float]
    due_date: str
    reason: str


class LbsRetirementView(_Upstream):
    """The retirement comparison in one basis (lbs LBS-31)."""

    basis: Basis
    needs_per_year: Optional[float]
    covered_per_year: Optional[float]
    shortfall_per_year: Optional[float]


class LbsRetirement(_Upstream):
    goal_id: str
    verdict: str
    needs_per_year: Optional[float]
    covered_per_year: Optional[float]
    shortfall_per_year: Optional[float]
    undetermined_because: tuple[str, ...] = ()
    #: From lbs calibration 1.4.0: ``real``, the figures above are in today's francs, and ``views`` carries
    #: both bases (REP-27).
    basis: Optional[Literal["real"]] = None
    views: Optional[dict[str, LbsRetirementView]] = None


class LbsRiskProfile(_Upstream):
    status: Literal["available"]
    value: Optional[float]
    binds_on: Optional[str]


class LbsRequiredReturnView(_Upstream):
    """The mandate's target and required return in one basis (lbs LBS-31)."""

    basis: Basis
    target_chf: Optional[float]
    required_return: Optional[float]


class LbsPlausibility(_Upstream):
    """Whether a portfolio within the risk profile can reasonably earn the required return (lbs LBS-34)."""

    judgement: Literal["realistic", "not_realistic", "could_not_be_determined"]


class LbsMandateProposal(_Upstream):
    status: Literal["available"]
    name: str
    goal_id: str
    goal_kind: str
    target_chf: Optional[float]
    goal_horizon_years: Optional[float]
    drawable_chf: Optional[float]
    annual_contribution: Optional[float]
    required_return: Optional[float]
    feasible: Optional[bool]
    complete: bool
    release_state: Literal["unreleased"]
    #: From lbs calibration 1.4.0 (REP-27): both views of the target and the required return, and the
    #: plausibility of the required return.
    views: Optional[dict[str, LbsRequiredReturnView]] = None
    plausibility: Optional[LbsPlausibility] = None


class LbsGap(_Upstream):
    section: str
    input: str
    kind: str
    reason: str


class LbsInflationUse(_Upstream):
    """The inflation assumption a sheet used (lbs LBS-32)."""

    currency: str
    index: str
    annual_rate: float
    log_rate: float
    label: Literal["measured", "extrapolated"]
    source: str


class LbsBasisAmount(_Upstream):
    basis: Basis
    amount: Optional[float]
    as_at: Optional[str] = None
    absent_because: Optional[str] = None


class LbsGoalBasisView(_Upstream):
    """One goal's amount in both bases (lbs LBS-31)."""

    goal_id: str
    unit: str
    amount_basis: Literal["today", "future"]
    amount_basis_stated: bool
    nominal: LbsBasisAmount
    real: LbsBasisAmount


class LbsRealView(_Upstream):
    """lbs's real view (lbs ``RealView``, LBS-31): the inflation assumption, whether the contribution is indexed,
    every goal's amount in both bases (REP-27)."""

    currency: str
    inflation: LbsInflationUse
    contribution_indexed: bool
    contribution_indexed_stated: bool
    goals: tuple[LbsGoalBasisView, ...] = ()


class LbsProvenance(_Upstream):
    engine_version: str
    calibration_version: str
    as_of: str


class LifeBalanceSheet(_Upstream):
    """``lbs-balance-sheet@1.0.0``, as ``report`` reads it (lbs contracts.py, final on 28.09.2026)."""

    contract_version: Literal["lbs-balance-sheet@1.0.0"]
    artefact_id: str
    client_ref: str
    as_of: str
    calibration_version: str
    household: LbsHousehold
    grid: tuple[LbsGridCell, ...]
    totals: LbsTotals
    human_capital: tuple[LbsHumanCapital, ...]
    pensions: tuple[LbsPensions, ...]
    couple_cap: Union[LbsCoupleCap, LbsNotAvailable] = Field(discriminator="status")
    property: tuple[LbsProperty, ...]
    liquidity: tuple[LbsLiquidity, ...]
    retirement: tuple[LbsRetirement, ...]
    risk_profile: Union[LbsRiskProfile, LbsNotAvailable] = Field(discriminator="status")
    mandate_proposal: Union[LbsMandateProposal, LbsNotAvailable] = Field(discriminator="status")
    gaps: tuple[LbsGap, ...]
    provenance: LbsProvenance
    #: Since lbs's real view (REP-27): the goal figures and the required return in today's francs. A sheet
    #: without it can be reported in nominal only.
    real_view: Optional[LbsRealView] = None


# ---------------------------------------------------------------------------
# Upstream mirrors: lbsim (REP-32), ``GET /artefacts/{id}`` on 8014, typed by the id's prefix. Mirrored from
# lbsim's contracts.py of 29.09.2026 (B1); pinned to lbsim-findings@1.0.0, lbsim-paths@1.0.0, lbsim-plan@1.0.0.
# ---------------------------------------------------------------------------

class LsWords(_Upstream):
    """A sentence for people in both languages; a page prints the one of its language."""

    de: str
    en: str


class LsResponsibility(_Upstream):
    label: LsWords
    stated: bool


class LsModelledEarning(_Upstream):
    full_time_chf_per_year: float
    responsibility: LsResponsibility


class LsStatedEarning(_Upstream):
    expected_full_pensum_income_chf_per_year: Optional[float] = None


class LsCurrentEarning(_Upstream):
    gross_income_chf_per_year: Optional[float] = None
    pensum: Optional[float] = None


class LsEarningPower(_Upstream):
    person_id: str
    status: Literal["available", "not_available"]
    reason: Optional[LsWords] = None
    modelled: Optional[LsModelledEarning] = None
    stated: LsStatedEarning
    level_basis: Literal["stated", "modelled"]
    current: LsCurrentEarning
    caveats: tuple[LsWords, ...] = ()


class LsSavingNeed(_Upstream):
    goal_id: str
    target_chf: float
    target_date: Optional[str] = None
    zero_return_saving_chf_per_year: float
    free_cash_chf_per_year: float
    holds: bool = False


class LsRealSavingView(_Upstream):
    derived: Literal[True]
    saving_need: tuple[LsSavingNeed, ...]


class LsIncomePathViews(_Upstream):
    real: LsRealSavingView


class LsIncomePath(_Upstream):
    code: str
    person_id: str
    name: LsWords
    note: LsWords
    saving_need: tuple[LsSavingNeed, ...]
    views: LsIncomePathViews


class LsZeroReturn(_Upstream):
    note: LsWords


class LsFigure(_Upstream):
    value: Optional[float]
    unit: Literal["chf", "chf_per_year", "share", "years", "hours_per_week", "count"]
    basis: Optional[Basis] = None


class LsFindingWords(_Upstream):
    title: str
    trigger: str
    why: str
    action: str


class LsFindingText(_Upstream):
    de: LsFindingWords
    en: LsFindingWords


class LsFinding(_Upstream):
    code: str
    severity: Literal["blocking", "high", "medium", "note"]
    urgency: Literal["now", "months", "year", "watch"]
    action_kind: Literal["ask", "quantify", "decide_between"]
    figures: dict[str, LsFigure]
    text: LsFindingText


class LsScheduleEntry(_Upstream):
    when: str
    label: LsWords
    codes: tuple[str, ...]


class LsUnchecked(_Upstream):
    code: str
    reason: LsWords
    #: ``plan`` for the rule only the plan calculation decides; left out of a report that carries the plan.
    answered_by: Optional[str] = None


class LsNextQuestion(_Upstream):
    question_key: str
    question: LsWords


class LifeBalanceFindings(_Upstream):
    """``lbsim-findings@1.0.0``, as ``report`` reads it."""

    contract_version: Literal["lbsim-findings@1.0.0"]
    artefact_id: str
    client_ref: str
    life_balance_sheet_id: str
    as_of: str
    principal: str
    earning_power: tuple[LsEarningPower, ...]
    income_paths: tuple[LsIncomePath, ...]
    zero_return: LsZeroReturn
    findings: tuple[LsFinding, ...]
    schedule: tuple[LsScheduleEntry, ...]
    unchecked: tuple[LsUnchecked, ...] = ()
    next_questions: tuple[LsNextQuestion, ...] = ()


class LsQuantiles(_Upstream):
    p05: tuple[float, ...]
    p10: tuple[float, ...]
    p25: tuple[float, ...]
    p50: tuple[float, ...]
    p75: tuple[float, ...]
    p90: tuple[float, ...]
    p95: tuple[float, ...]


class LsBandSet(_Upstream):
    nominal: LsQuantiles
    real: LsQuantiles


class LsGoalTarget(_Upstream):
    nominal_chf: float
    real_chf: float
    amount_basis: Literal["today", "future"]
    date: str


class LsGoalChance(_Upstream):
    goal_id: str
    kind: Literal["home", "retirement", "capital"]
    measure: Literal["drawable", "deposit_eligible", "retirement_capital"]
    target: LsGoalTarget
    chance: float
    chance_basis: Basis
    n_reached: int


class LsRegimePaths(_Upstream):
    key: str
    label: LsWords
    kind: Literal["base", "scenario"]
    bands: dict[str, LsBandSet]
    goals: tuple[LsGoalChance, ...]


class LifeBalancePaths(_Upstream):
    """``lbsim-paths@1.0.0``, as ``report`` reads it."""

    contract_version: Literal["lbsim-paths@1.0.0"]
    artefact_id: str
    client_ref: str
    life_balance_sheet_id: str
    findings_artefact_id: str
    allocation_id: str
    as_of: str
    start_year: int
    horizon_years: int
    n_paths: int
    regimes: tuple[LsRegimePaths, ...]


class LsPlanGoal(_Upstream):
    goal_id: str
    kind: str
    confidence: float


class LsActionNow(_Upstream):
    work_share: float
    learning_hours_per_week: float
    network_hours_per_week: float
    rest_hours_per_week: float
    consumption_chf_per_year: float
    saving_chf_per_year: float
    education_spend_chf_per_year: float
    network_spend_chf_per_year: float
    amortisation_chf_per_year: float


class LsPlanChance(_Upstream):
    out_of_sample: float


class LsReachable(_Upstream):
    amount_chf: float
    at_confidence: float


class LsPlanHorizon(_Upstream):
    solved_years: float
    total_years: float
    beyond_cap_rule: Optional[str] = None


class LifeBalancePlan(_Upstream):
    """``lbsim-plan@1.0.0``, as ``report`` reads it. Only a finished solve is ever an artefact."""

    contract_version: Literal["lbsim-plan@1.0.0"]
    artefact_id: str
    client_ref: str
    life_balance_sheet_id: str
    paths_artefact_id: str
    outcome: Literal["solved", "goal_not_fundable", "undetermined"]
    goal: LsPlanGoal
    action_now: LsActionNow
    framing: LsWords
    chance: LsPlanChance
    reachable: Optional[LsReachable] = None
    horizon: LsPlanHorizon


# ---------------------------------------------------------------------------
# In
# ---------------------------------------------------------------------------

class SourceRef(_Frozen):
    engine: EngineName
    artefact_id: str = Field(min_length=1, max_length=80)


class DisplayFact(_Frozen):
    """A fact the caller supplies for display, such as the client's name. Shown in the header as given; the
    model never sees it (REP-06)."""

    key: str
    label: str = Field(min_length=1, max_length=200)
    value: Union[float, str]
    source: str = Field(min_length=1, max_length=200)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _REF.match(value):
            raise ValueError(f"display fact key {value!r} must be 1 to 80 characters of letters, digits and _.:-")
        return value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: Union[float, str]) -> Union[float, str]:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("a display fact value must be finite")
        return value


class ReportRequest(_Frozen):
    contract_version: Literal["report-request@1.0.0"] = "report-request@1.0.0"
    #: Opaque to this engine. Checked against the ``client_ref`` an upstream artefact carries, when it has one.
    client_ref: str
    kind: Literal["report", "update"]
    language: Language
    #: The artefacts the report draws on, at most one per engine.
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    #: For an update: the report it states the changes against. Must be this client's.
    previous_report_id: Optional[str] = None
    display_facts: tuple[DisplayFact, ...] = ()
    #: ``False`` renders the report without model prose.
    prose: bool = True
    calibration_version: Optional[str] = None
    #: Since engine 1.3.0, optional (REP-27): the basis of the return and goal figures. ``real`` takes the real
    #: figures from the lbs sheet and needs a pcp Allocation of basis ``real``; a mix is refused. Enters the
    #: request id only when ``real``, so a request without it (or with ``nominal``) keeps its id and key.
    basis: Basis = "nominal"
    #: Since engine 1.2.0, optional (REP-25): the report this one revises (a ``REP-...`` id of this client's),
    #: and the curator's remark that asks for the revision. Both enter the request id and so the idempotency
    #: key, so a revision is a distinct artefact; the note is printed on the page as the curator's remark and
    #: never reaches the model. Left out of the request id when absent, so a request without them keeps its key.
    revision_of: Optional[str] = Field(default=None, min_length=1, max_length=80)
    revision_note: Optional[str] = Field(default=None, min_length=1, max_length=4000)

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not _REF.match(value):
            raise ValueError(f"client_ref {value!r} must be 1 to 80 characters of letters, digits and _.:-")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "ReportRequest":
        kinds = [source_kind(s.engine, s.artefact_id) for s in self.sources]
        if len(set(kinds)) != len(kinds):
            raise ValueError("at most one source artefact per engine and artefact kind")
        if (self.kind == "update") != (self.previous_report_id is not None):
            raise ValueError("an update names previous_report_id, and only an update does")
        keys = [f.key for f in self.display_facts]
        if len(set(keys)) != len(keys):
            raise ValueError("display fact keys must be unique")
        if self.revision_note is not None:
            if not self.revision_note.strip():
                raise ValueError("revision_note must not be blank")
            if self.revision_of is None:
                raise ValueError("a revision_note belongs to a revision: name revision_of")
        return self


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class ProseGeneration(_Frozen):
    max_tokens: int = Field(ge=32, le=4096)
    temperature: float = Field(ge=0.0, le=2.0)
    seed: Optional[int] = None
    #: Drafts per section while a draft is rejected or carries an unverified number.
    attempts: int = Field(ge=1, le=4)
    min_words: int = Field(ge=1)
    max_words: int = Field(ge=10)


class NumberCheck(_Frozen):
    min_checked_digits: int = Field(ge=1, le=6)
    rounding_decimals: tuple[int, ...]
    relative_tolerance: float = Field(gt=0.0, le=1e-3)


class RejectRules(_Frozen):
    """Ways a draft is wrong without a wrong number (prior art ``desktop/sectionprose._reject``)."""

    advice: dict[str, tuple[str, ...]]
    wrong_currency: tuple[str, ...]
    echoes: tuple[str, ...]
    max_upper_share: float = Field(gt=0.0, le=1.0)


class Calibration(_Frozen):
    contract_version: Literal["report-calibration@1.0.0"] = "report-calibration@1.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    prose: ProseGeneration
    number_check: NumberCheck
    reject: RejectRules
    #: A position is listed when its weight is at least this share.
    position_min_weight: float = Field(ge=0.0, lt=1.0)
    #: Per section key, per language: what the connecting sentences are asked to say. A section without an
    #: entry gets no prose, which is the safe direction (REP-05).
    slots: dict[str, dict[str, str]]

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$", value):
            raise ValueError(f"calibration version {value!r} is not semantic")
        return value

    @model_validator(mode="after")
    def _languages(self) -> "Calibration":
        for key, asks in self.slots.items():
            if set(asks) != {"de", "en"}:
                raise ValueError(f"slot {key!r} must be asked in de and en")
        if set(self.reject.advice) != {"de", "en"}:
            raise ValueError("the advice phrases must be given for de and en")
        if self.prose.min_words >= self.prose.max_words:
            raise ValueError("prose.min_words must be below prose.max_words")
        return self


# ---------------------------------------------------------------------------
# Out
# ---------------------------------------------------------------------------

class FactSource(_Frozen):
    #: ``pcp``, ``lbs``, ``report`` (a previous report) or ``caller`` (a display fact).
    engine: str
    #: The artefact the value was read from. For a display fact, the request id (``RRQ-...``).
    artefact_id: str
    contract_version: str
    #: JSON pointer into that artefact (RFC 6901).
    path: str


Unit = Literal["chf", "chf_per_year", "share", "count", "number", "text", "date", "flag"]


class Fact(_Frozen):
    fact_id: str
    section: str
    label: str
    value: Union[bool, float, str, None]
    unit: Unit
    #: The value as the report prints it, in the report's language.
    display: str
    #: Where the value comes from: one source, or two for a change (previous and current).
    sources: tuple[FactSource, ...] = Field(min_length=1)
    #: How the code derived the value, when it is not read verbatim ("count of ...", "current - previous").
    derivation: Optional[str] = None
    #: For a change: the previous value.
    previous: Union[bool, float, str, None] = None
    #: Since engine 1.3.0 (REP-27): the basis of a return or goal figure, printed next to it; ``None`` for a
    #: figure that has none (an amount today, a count, a date).
    basis: Optional[Basis] = None


ProseStatus = Literal["verified", "flagged", "rejected", "unavailable", "not_requested", "no_slot"]


class Section(_Frozen):
    key: str
    title: str
    fact_ids: tuple[str, ...]
    #: The model's connecting sentences. Rendered only when ``prose_status`` is ``verified``.
    prose: Optional[str] = None
    prose_status: ProseStatus
    prose_model: Optional[str] = None
    #: Numbers in the prose that match none of this section's facts.
    unverified_numbers: tuple[str, ...] = ()
    prose_attempts: int = 0
    #: Why there is no verified prose, in plain words.
    prose_note: Optional[str] = None


class SourceUse(_Frozen):
    engine: str
    artefact_id: str
    contract_version: str
    #: sha256 of the artefact as received.
    sha256: str
    url: str


class ModelUse(_Frozen):
    service: str
    host: str
    model: str
    prompt_version: str
    prompt_hash: str


class ReportProvenance(_Frozen):
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: Content hash of the request: the artefact id display facts cite.
    request_id: str
    sources: tuple[SourceUse, ...]
    previous_report_id: Optional[str]
    #: ``None`` when no prose was asked for.
    model: Optional[ModelUse]
    label: Literal["model-derived"] = "model-derived"


class Report(_Frozen):
    contract_version: Literal["report@1.0.0"] = "report@1.0.0"
    artefact_id: str
    client_ref: str
    kind: Literal["report", "update"]
    language: Language
    title: str
    previous_report_id: Optional[str]
    #: Since engine 1.2.0, optional (REP-25): the report this one revises and the curator's remark, as requested.
    revision_of: Optional[str] = None
    revision_note: Optional[str] = None
    #: Since engine 1.3.0 (REP-27): the basis the report was asked in. A report stored before it reads as nominal.
    basis: Basis = "nominal"
    #: The as-of date of the newest source, the date the report speaks for.
    as_of: str
    facts: tuple[Fact, ...]
    sections: tuple[Section, ...]
    #: Whether everything asked for was produced. ``False`` when the model could not be reached: the report
    #: stands without prose, and a repeat of the request tries again (REP-07).
    complete: bool
    warnings: tuple[str, ...] = ()
    #: Self-contained HTML in the house style, rendered from the fields above.
    html: str
    provenance: ReportProvenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _consistent(self) -> "Report":
        ids = [f.fact_id for f in self.facts]
        if len(set(ids)) != len(ids):
            raise ValueError("fact ids must be unique")
        known = set(ids)
        for s in self.sections:
            missing = [i for i in s.fact_ids if i not in known]
            if missing:
                raise ValueError(f"section {s.key} names unknown facts {missing}")
        return self


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
    request: ReportRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    provenance: Optional[ReportProvenance]
    error: Optional[str]
