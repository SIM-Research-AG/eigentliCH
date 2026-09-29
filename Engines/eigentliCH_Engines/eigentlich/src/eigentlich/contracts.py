"""The engines' contracts as the app uses them: mirrored here, never imported (Engine Building Guide 1).

Outbound requests are mirrored whole and strictly (frozen, extra fields forbidden), so a request the app
builds is refused here, with the field named, before it is sent. Inbound artefacts are mirrored partially
(extra fields ignored): the fields the app reads, with the contract version pinned exactly.

* ``lbs``      ``lbs-request@1.0.0`` out; ``RunAccepted`` and ``lbs-balance-sheet@1.0.0`` (partial) in.
               Mirrored from ``engines/lbs/src/lbs/contracts.py`` as it stood on 28.09.2026; re-read on
               29.09.2026 (new calibration 1.1.0 with corrections): the request is unchanged field for field.
               Re-read again on 29.09.2026 (lbs@1.2.0): ``goals[].contribution_share`` added (LBS-29), and the
               request's owner and share checks mirrored.
* ``chatbot``  ``chat-request@1.0.0`` out; ``chat-answer@1.0.0`` (partial) in.
               Mirrored from ``engines/chatbot/src/chatbot/contracts.py`` of 28.09.2026; re-read on 29.09.2026:
               the answer's optional ``basis`` (CHB-18) and ``model_display_name`` (CHB-21) added.
* ``report``   ``report-request@1.0.0`` out (the engine names the artefact list ``sources``); ``report@1.0.0``
               (partial) in. Mirrored from ``engines/report/src/report/contracts.py`` of 28.09.2026; re-read on
               29.09.2026 (report 1.2.0, REP-25): the optional ``revision_of`` and ``revision_note`` added
               (EIG-57). ``display_facts`` is not mirrored: the app sends none.
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


class LbsPerson(_Out):
    person_id: str
    kind: Literal["adult", "dependant"]
    age: Optional[int] = Field(default=None, ge=0, le=120)
    stated_gross_income: Optional[float] = Field(default=None, ge=0)
    human_capital: HumanCapitalAnswers = Field(default_factory=HumanCapitalAnswers)
    ahv: AhvFacts = Field(default_factory=AhvFacts)

    @field_validator("person_id")
    @classmethod
    def _pid(cls, v: str) -> str:
        return _opaque(v, "person_id")


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

    @field_validator("goal_id")
    @classmethod
    def _gid(cls, v: str) -> str:
        return _opaque(v, "goal_id")


class LbsFacts(_Out):
    canton: Optional[str] = None
    civil_status: Optional[str] = None
    has_no_liabilities: bool = False


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

class SourceRef(_Out):
    engine: Literal["pcp", "lbs"]
    artefact_id: str = Field(min_length=1, max_length=80)


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

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _opaque(v, "client_ref", _REF)

    @model_validator(mode="after")
    def _revision(self) -> "ReportRequest":
        if self.revision_note is not None and (not self.revision_note.strip() or self.revision_of is None):
            raise ValueError("a revision_note belongs to a revision (revision_of) and is not blank")
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
    notice: str = NOTICE


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
