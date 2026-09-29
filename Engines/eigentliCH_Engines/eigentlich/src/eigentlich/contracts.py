"""The engines' contracts as the app uses them: mirrored here, never imported (Engine Building Guide 1).

Outbound requests are mirrored whole and strictly (frozen, extra fields forbidden), so a request the app
builds is refused here, with the field named, before it is sent. Inbound artefacts are mirrored partially
(extra fields ignored): the fields the app reads, with the contract version pinned exactly.

* ``lbs``      ``lbs-request@1.0.0`` out; ``RunAccepted`` and ``lbs-balance-sheet@1.0.0`` (partial) in.
               Mirrored from ``engines/lbs/src/lbs/contracts.py`` as it stood on 28.09.2026; re-read on
               29.09.2026 (new calibration 1.1.0 with corrections): the request is unchanged field for field.
               Re-read again on 29.09.2026 (lbs@1.2.0): ``goals[].contribution_share`` added (LBS-29), and the
               request's owner and share checks mirrored. Re-read on 29.09.2026 for the nominal and real view
               (lbs's LBS-31, calibration 1.4.0): ``goals[].amount_basis`` (today | future) and
               ``mandate.contribution_indexed``, both optional and sent only when the client stated them, so a
               request without them keeps its bytes and an lbs before LBS-31 still takes it (EIG-60, EIG-61). The
               sheet's ``real_view`` and the mandate proposal's ``views`` are read for display (partial).
* ``chatbot``  ``chat-request@1.0.0`` out; ``chat-answer@1.0.0`` (partial) in.
               Mirrored from ``engines/chatbot/src/chatbot/contracts.py`` of 28.09.2026; re-read on 29.09.2026:
               the answer's optional ``basis`` (CHB-18) and ``model_display_name`` (CHB-21) added.
* ``report``   ``report-request@1.0.0`` out (the engine names the artefact list ``sources``); ``report@1.0.0``
               (partial) in. Mirrored from ``engines/report/src/report/contracts.py`` of 28.09.2026; re-read on
               29.09.2026 (report 1.2.0, REP-25): the optional ``revision_of`` and ``revision_note`` added
               (EIG-57). ``display_facts`` is not mirrored: the app sends none. Re-read on 29.09.2026 (REP-27):
               the optional ``basis`` (nominal | real), sent only when ``real`` (EIG-62).
* ``aggregation`` ``GET /scenarios`` in (``ScenarioListed``, partial): which Regimes are scenarios, so a report
               takes the allocation of the base Regime unless a scenario is asked for (EIG-63). Mirrored from
               ``Macro/engines/aggregation/src/aggregation/contracts.py`` of 29.09.2026.
* ``lbsim``    ``lbsim-request@1.0.0`` and ``lbsim-optimise@1.0.0`` out; ``RunAccepted``, ``RunStatus`` and the outlook
               (``GET /outlook``, partial: the plan state and the artefacts' ids and sheet; the page reads the rest as
               published) in. Mirrored from ``engines/lbsim/src/lbsim/contracts.py`` of 29.09.2026 (EIG-66). With it,
               lbs@1.4.0's optional ``persons[].earning_power`` and the six new ``facts`` (LBS-39), sent only when
               stated (EIG-65), and the report's ``lbsim`` sources, one per artefact kind (report 1.4.0, REP-32).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSIONS: dict[str, str] = {
    "LifeBalanceSheetRequest(lbs)": "lbs-request@1.0.0",
    "LifeBalanceSheet(lbs)": "lbs-balance-sheet@1.0.0",
    "ChatRequest(chatbot)": "chat-request@1.0.0",
    "ChatAnswer(chatbot)": "chat-answer@1.0.0",
    "ReportRequest(report)": "report-request@1.0.0",
    "Report(report)": "report@1.0.0",
    "LifeBalanceSimRequest(lbsim)": "lbsim-request@1.0.0",
    "OptimiseRequest(lbsim)": "lbsim-optimise@1.0.0",
    "LifeBalanceFindings(lbsim)": "lbsim-findings@1.0.0",
    "LifeBalancePaths(lbsim)": "lbsim-paths@1.0.0",
    "LifeBalancePlan(lbsim)": "lbsim-plan@1.0.0",
}

NOTICE = "Model-derived research output. Not investment advice."

_LBS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


def _opaque(value: str, what: str, pattern: re.Pattern = _LBS_ID) -> str:
    if not pattern.match(value):
        raise ValueError(f"{what} {value!r} is not an opaque reference")
    return value


# ---------------------------------------------------------------------------
# lbs: the request (strict mirror)
# ---------------------------------------------------------------------------

class HumanCapitalAnswers(_Out):
    qualification_highest: Optional[str] = None
    qualification_year: Optional[float] = None
    years_in_field: Optional[float] = None
    education_recent: Optional[str] = None
    network_people: Optional[float] = Field(default=None, ge=0)
    mandates: Optional[float] = Field(default=None, ge=0)
    network_reach: Optional[str] = None
    health: Optional[str] = None
    health_withheld: bool = False
    hours_per_week: Optional[float] = Field(default=None, ge=0)
    rest_hours: Optional[str] = None
    hours_learning: Optional[float] = Field(default=None, ge=0)
    hours_network: Optional[float] = Field(default=None, ge=0)


class AhvFacts(_Out):
    mdje: Optional[float] = Field(default=None, ge=0)
    contribution_years_missing: Optional[int] = Field(default=None, ge=0)


class EarningPowerAnswers(_Out):
    """lbs@1.4.0 (LBS-39): the answers lbsim reads for earning power and the income paths, per adult. Validated by
    lbs, computed by lbsim. Each is sent only when stated (EIG-65)."""
    expected_full_pensum_income: Optional[float] = Field(default=None, ge=0)
    #: A tier of lbs's ``human-capital.responsibility.tiers``, by its key or its German or English label.
    responsibility: Optional[str] = Field(default=None, min_length=1)
    sector: Optional[str] = Field(default=None, min_length=1)
    education_status: Optional[Literal["none", "in_progress", "planned"]] = None
    education_end_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    #: A band string ("3–5") or a number of hours.
    education_hours: Optional[Union[float, str]] = None
    education_budget_per_year: Optional[float] = Field(default=None, ge=0)
    #: K3 data: cannot be stated while ``human_capital.health_withheld`` is true (lbs refuses it, 422).
    health_work_capacity: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _education(self) -> "EarningPowerAnswers":
        if self.education_status == "none" and self.education_end_year is not None:
            raise ValueError("earning_power states no education but an education end year")
        return self

    def stated(self) -> bool:
        return any(v is not None for v in self.model_dump().values())


class LbsPerson(_Out):
    person_id: str
    kind: Literal["adult", "dependant"]
    age: Optional[int] = Field(default=None, ge=0, le=120)
    stated_gross_income: Optional[float] = Field(default=None, ge=0)
    human_capital: HumanCapitalAnswers = Field(default_factory=HumanCapitalAnswers)
    ahv: AhvFacts = Field(default_factory=AhvFacts)
    #: lbs@1.4.0 (LBS-39), adults only, sent only when some answer is stated (EIG-65).
    earning_power: Optional[EarningPowerAnswers] = None

    @field_validator("person_id")
    @classmethod
    def _pid(cls, v: str) -> str:
        return _opaque(v, "person_id")

    @model_validator(mode="after")
    def _earning(self) -> "LbsPerson":
        if self.earning_power is None:
            return self
        if self.kind != "adult":
            raise ValueError(f"person {self.person_id} is a dependant; earning power is asked of adults only")
        if self.human_capital.health_withheld and self.earning_power.health_work_capacity is not None:
            raise ValueError(f"person {self.person_id}: health is withheld (K3), so health_work_capacity is not sent")
        return self


class LbsHousehold(_Out):
    composition_as_of: date
    persons: tuple[LbsPerson, ...] = Field(min_length=1)
    principal: Optional[str] = None


class LbsPosition(_Out):
    position_id: str
    role: Literal["gain", "income", "stabilisation", "protection", "growth"]
    capital_type: Literal["human", "financial"]
    magnitude: Optional[float] = None
    unit: Optional[Literal["chf", "chf_per_year", "share_of_total"]] = None
    stock_kind: Optional[Literal["asset", "liability"]] = None
    liquidity: Optional[Literal["immediate", "within_months", "within_years", "illiquid"]] = None
    vessel: Optional[Literal["free", "pillar_2", "pillar_3a", "real_asset"]] = None
    owner: Optional[str] = None
    active: bool = True
    funds_goals: tuple[str, ...] = ()

    @field_validator("position_id")
    @classmethod
    def _pid(cls, v: str) -> str:
        return _opaque(v, "position_id")


class LbsGoal(_Out):
    goal_id: str
    kind: Literal["property", "retirement", "other"]
    target_amount: Optional[float] = Field(default=None, ge=0)
    target_date: Optional[date] = None
    occupancy: Optional[str] = None
    owners: tuple[str, ...] = ()
    #: The goal's share of the household's one yearly saving, 0 to 1 (lbs@1.2.0, LBS-29; read from calibration
    #: 1.3.0 on). The stated shares sum to at most 1: lbs refuses the request otherwise (EIG-59).
    contribution_share: Optional[float] = Field(default=None, ge=0, le=1)
    #: Whether ``target_amount`` is in today's francs or in the francs of the target date (lbs LBS-31; missing
    #: means today, owner decision 7). Sent only when the client answered (EIG-60).
    amount_basis: Optional[Literal["today", "future"]] = None

    @field_validator("goal_id")
    @classmethod
    def _gid(cls, v: str) -> str:
        return _opaque(v, "goal_id")


class LbsFacts(_Out):
    canton: Optional[str] = None
    civil_status: Optional[str] = None
    has_no_liabilities: bool = False
    # lbs@1.4.0 (LBS-39), optional and additive, each sent only when stated (EIG-65): the facts lbsim's findings read.
    stop_work_age: Optional[float] = Field(default=None, ge=40, le=75)
    #: The legal documents in place, by name; an empty tuple is a stated "none", unset is unanswered.
    legal_documents: Optional[tuple[str, ...]] = None
    mortgage_fixed_until: Optional[date] = None
    amortisation_mode: Optional[Literal["direct", "indirect"]] = None
    own_use_share: Optional[float] = Field(default=None, ge=0, le=1)
    pillar3a_contribution_per_year: Optional[float] = Field(default=None, ge=0)

    @field_validator("legal_documents")
    @classmethod
    def _documents(cls, value: Optional[tuple[str, ...]]) -> Optional[tuple[str, ...]]:
        if value is not None and (any(not d.strip() for d in value) or len(set(value)) != len(value)):
            raise ValueError("facts.legal_documents names an empty document or one twice")
        return value


#: The facts lbs@1.4.0 added (LBS-39): each left out of the request while unset.
FACTS_ADDED = ("stop_work_age", "legal_documents", "mortgage_fixed_until", "amortisation_mode", "own_use_share",
               "pillar3a_contribution_per_year")


class LbsRisk(_Out):
    stated_loss: Optional[float] = Field(default=None, ge=0, le=1)
    crisis_behaviour: Optional[str] = None
    esg_exclusions: tuple[str, ...] = ()
    esg_level: Optional[str] = None
    employment: Optional[str] = None
    liquidity_reserve_months: Optional[float] = Field(default=None, ge=0)
    spend_now_per_year: Optional[float] = Field(default=None, ge=0)
    variable_income_per_year: Optional[float] = Field(default=None, ge=0)
    gross_income_per_year: Optional[float] = Field(default=None, ge=0)
    mandates: Optional[int] = Field(default=None, ge=0)
    plan_until_age: Optional[float] = Field(default=None, ge=0)
    mortgage: Optional[float] = Field(default=None, ge=0)
    mortgage_rate_pct: Optional[float] = Field(default=None, ge=0)
    amortisation_per_year: Optional[float] = Field(default=None, ge=0)


class LbsMandate(_Out):
    goal_id: str
    annual_contribution: Optional[float] = Field(default=None, ge=0)
    name: Optional[str] = None
    #: Whether the yearly contribution rises with prices (lbs LBS-31; missing means fixed in francs, owner
    #: decision 9). Sent only when the client answered (EIG-61).
    contribution_indexed: Optional[bool] = None


class LbsRequest(_Out):
    """Checked as lbs checks it (its ``_references``), so a request lbs would refuse is refused here first."""

    contract_version: Literal["lbs-request@1.0.0"] = "lbs-request@1.0.0"
    client_ref: str
    as_of: date
    calibration_version: Optional[str] = None
    household: Optional[LbsHousehold] = None
    positions: tuple[LbsPosition, ...] = ()
    goals: tuple[LbsGoal, ...] = ()
    facts: LbsFacts = Field(default_factory=LbsFacts)
    risk: LbsRisk = Field(default_factory=LbsRisk)
    mandate: Optional[LbsMandate] = None

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _opaque(v, "client_ref")

    @model_validator(mode="after")
    def _references(self) -> "LbsRequest":
        persons = {p.person_id for p in self.household.persons} if self.household else set()
        for p in self.positions:
            if p.owner is not None and p.owner not in persons:
                raise ValueError(f"position {p.position_id} names owner {p.owner!r}, who is not in the household")
        shares = [g.contribution_share for g in self.goals if g.contribution_share is not None]
        if sum(shares) > 1 + 1e-9:
            raise ValueError(f"the goals' contribution shares sum to {sum(shares):.6g}; at most 1")
        return self


# ---------------------------------------------------------------------------
# lbs: what comes back (partial mirror)
# ---------------------------------------------------------------------------

class RunAccepted(_In):
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class LbsGridCell(_In):
    role: str
    capital_type: str
    display: str
    definition: Optional[str] = None
    positions: tuple[str, ...] = ()
    assets_chf: Optional[float] = None
    liabilities_chf: Optional[float] = None
    flows_chf_per_year: Optional[float] = None
    shares_of_total: Optional[float] = None


class LbsTotals(_In):
    financial_assets: Optional[float] = None
    human_assets: Optional[float] = None
    total_assets: Optional[float] = None
    liabilities: Optional[float] = None
    net_worth: Optional[float] = None
    drawable: Optional[float] = None
    household_income: Optional[float] = None


class LbsGap(_In):
    section: str
    input: str
    kind: str
    reason: str


class LifeBalanceSheet(_In):
    contract_version: Literal["lbs-balance-sheet@1.0.0"]
    artefact_id: str
    client_ref: str
    as_of: date
    calibration_version: str
    grid: tuple[LbsGridCell, ...]
    totals: LbsTotals
    gaps: tuple[LbsGap, ...] = ()
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# chatbot
# ---------------------------------------------------------------------------

class GroundingNote(_Out):
    id: str
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    source_label: str = Field(min_length=1, max_length=300)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return _opaque(v, "grounding id", _REF)


class ClientFact(_Out):
    key: str
    label: str = Field(min_length=1, max_length=200)
    value: Union[float, str]
    source: str = Field(min_length=1, max_length=200)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        return _opaque(v, "client fact key", _REF)


class Turn(_Out):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(_Out):
    contract_version: Literal["chat-request@1.0.0"] = "chat-request@1.0.0"
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["de", "en"]
    grounding: tuple[GroundingNote, ...] = ()
    client_facts: tuple[ClientFact, ...] = ()
    history: tuple[Turn, ...] = ()
    calibration_version: Optional[str] = None


class ChatAnswer(_In):
    contract_version: Literal["chat-answer@1.0.0"]
    artefact_id: str
    language: Literal["de", "en"]
    answer: str
    cited_ids: tuple[str, ...] = ()
    unverified_numbers: tuple[str, ...] = ()
    refused: bool
    refusal_code: Optional[str] = None
    refusal_reason: Optional[str] = None
    route: Optional[str] = None
    #: What the answer rests on: the notes, general knowledge, or both (CHB-18). Optional in the contract.
    basis: Optional[Literal["grounded", "general", "mixed"]] = None
    warnings: tuple[str, ...] = ()
    model: Optional[str] = None
    #: The name readers see for the house's AI ("MiniMind", CHB-21). The app shows its own i18n name.
    model_display_name: Optional[str] = None
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

#: lbsim's artefact kinds by the prefix of their id (report REP-32): at most one source per engine and kind.
LBSIM_KINDS = {"LSF": "findings", "LSP": "paths", "LSO": "plan"}


class SourceRef(_Out):
    engine: Literal["pcp", "lbs", "lbsim"]
    artefact_id: str = Field(min_length=1, max_length=80)

    def kind(self) -> str:
        if self.engine != "lbsim":
            return self.engine
        kind = LBSIM_KINDS.get(self.artefact_id.split("-", 1)[0])
        if kind is None:
            raise ValueError(f"an lbsim source is a findings, paths or plan artefact, not {self.artefact_id!r}")
        return f"lbsim.{kind}"


class ReportRequest(_Out):
    contract_version: Literal["report-request@1.0.0"] = "report-request@1.0.0"
    client_ref: str
    kind: Literal["report", "update"]
    language: Literal["de", "en"]
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    previous_report_id: Optional[str] = None
    prose: bool = True
    calibration_version: Optional[str] = None
    #: A revision (report 1.2.0, REP-25): the report engine's id of the report revised, and the curator's
    #: remark. Both enter the engine's request id, so a revision is a new artefact, never the cached copy.
    revision_of: Optional[str] = Field(default=None, min_length=1, max_length=80)
    revision_note: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    #: The basis of the return and goal figures (report 1.3.0, REP-27): ``real`` takes the real figures from the
    #: lbs sheet and needs a pcp Allocation of basis ``real``. Sent only when ``real`` (EIG-62).
    basis: Literal["nominal", "real"] = "nominal"

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _opaque(v, "client_ref", _REF)

    @model_validator(mode="after")
    def _revision(self) -> "ReportRequest":
        if self.revision_note is not None and (not self.revision_note.strip() or self.revision_of is None):
            raise ValueError("a revision_note belongs to a revision (revision_of) and is not blank")
        kinds = [s.kind() for s in self.sources]
        if len(set(kinds)) != len(kinds):
            raise ValueError("a report draws on at most one source per engine and artefact kind")
        return self


class Report(_In):
    contract_version: Literal["report@1.0.0"]
    artefact_id: str
    client_ref: str
    kind: Literal["report", "update"]
    language: Literal["de", "en"]
    title: str
    previous_report_id: Optional[str] = None
    revision_of: Optional[str] = None
    complete: bool
    warnings: tuple[str, ...] = ()
    html: str
    basis: Literal["nominal", "real"] = "nominal"
    notice: str = NOTICE


# ---------------------------------------------------------------------------
# aggregation: which Regimes are scenarios (partial mirror)
# ---------------------------------------------------------------------------

class ScenarioListed(_In):
    regime_id: str
    policy: str
    base_regime_id: str


# ---------------------------------------------------------------------------
# lbsim (Engine 14): the request strictly, what comes back partially (EIG-66)
# ---------------------------------------------------------------------------

_LBS_SHEET = r"^LBS-[0-9a-f]{16}$"
_PCP_ALLOCATION = r"^PCP-[0-9a-f]{16}$"


class LbsimRequest(_Out):
    """``lbsim-request@1.0.0``, the body of lbsim's ``POST /run``: the client's newest sheet and the base-Regime
    Allocation of the current parameter set; everything else lbsim resolves (LBSIM-18, the defaults of 3.1)."""
    contract_version: Literal["lbsim-request@1.0.0"] = "lbsim-request@1.0.0"
    client_ref: str
    life_balance_sheet_id: str = Field(pattern=_LBS_SHEET)
    allocation_id: Optional[str] = Field(default=None, pattern=_PCP_ALLOCATION)
    scenarios: Optional[tuple[Literal["depression", "hyperinflation", "stagflation", "deferral"], ...]] = None
    horizon_years: Optional[float] = Field(default=None, ge=1, le=60)
    income_path: Optional[Literal["today", "education", "full_pensum", "network"]] = None
    n_paths: Optional[int] = Field(default=None, ge=200, le=20_000)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    optimise: Literal["background", "no"] = "background"
    calibration_version: Optional[str] = None

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _opaque(v, "client_ref")


class LbsimRequestedBy(_Out):
    kind: Literal["client", "curator", "system"]
    ref: Optional[str] = None


class LbsimOptimise(_Out):
    """``lbsim-optimise@1.0.0``: a plan run on demand; a curator's goes ahead of the others."""
    contract_version: Literal["lbsim-optimise@1.0.0"] = "lbsim-optimise@1.0.0"
    paths_artefact_id: str = Field(pattern=r"^LSP-[0-9a-f]{16}$")
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    requested_by: LbsimRequestedBy


class LbsimNotMade(_In):
    artefact: str
    reason: str
    text: dict[str, str] = Field(default_factory=dict)


class LbsimRunAccepted(_In):
    run_id: str
    kind: Literal["outlook", "plan"]
    status: Literal["queued", "running", "succeeded", "failed"]
    idempotency_key: str
    cached: bool
    findings_artefact_id: Optional[str] = None
    paths_artefact_id: Optional[str] = None
    plan_run_id: Optional[str] = None
    not_made: tuple[LbsimNotMade, ...] = ()


class LbsimRunStatus(_In):
    run_id: str
    kind: Literal["outlook", "plan"]
    status: Literal["queued", "running", "succeeded", "failed"]
    failure_kind: Optional[str] = None
    artefact_ids: tuple[str, ...] = ()
    error: Optional[str] = None
    started_at: Optional[str] = None
    queued_at: Optional[str] = None
    budget_s: Optional[float] = None


class _LbsimArtefact(_In):
    artefact_id: str
    client_ref: str
    life_balance_sheet_id: str


class LbsimFindings(_LbsimArtefact):
    contract_version: Literal["lbsim-findings@1.0.0"]


class LbsimPaths(_LbsimArtefact):
    contract_version: Literal["lbsim-paths@1.0.0"]
    allocation_id: str
    findings_artefact_id: str


class LbsimPlan(_LbsimArtefact):
    contract_version: Literal["lbsim-plan@1.0.0"]
    paths_artefact_id: str


class LbsimPlanOutlook(_In):
    state: Literal["ready", "calculating", "waiting_for_allocation", "not_possible", "not_requested"]
    reason: Optional[dict[str, str]] = None
    run: Optional[LbsimRunStatus] = None
    artefact: Optional[LbsimPlan] = None
    elapsed_s: Optional[float] = None
    budget_s: Optional[float] = None


class LbsimOutlook(_In):
    """``GET /outlook``, checked for what the app relies on: one client, one sheet, the plan on these paths. The
    page reads the rest of the published findings and paths as they are."""
    client_ref: str
    life_balance_sheet_id: str
    findings: Optional[LbsimFindings] = None
    paths: Optional[LbsimPaths] = None
    plan: LbsimPlanOutlook

    @model_validator(mode="after")
    def _one_sheet(self) -> "LbsimOutlook":
        for part in (self.findings, self.paths, self.plan.artefact):
            if part is not None and (part.life_balance_sheet_id != self.life_balance_sheet_id
                                     or part.client_ref != self.client_ref):
                raise ValueError("an outlook never mixes sheets or clients")
        if self.plan.artefact is not None and (self.paths is None
                                               or self.plan.artefact.paths_artefact_id != self.paths.artefact_id):
            raise ValueError("the plan rests on other paths than the outlook's")
        return self


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
