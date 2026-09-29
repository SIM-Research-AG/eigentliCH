"""Contracts: every model ``lbs`` consumes or produces. Frozen, extra fields forbidden.

Inbound:

* ``LifeBalanceSheetRequest`` (``lbs-request@1.0.0``), body of ``POST /run`` and ``POST /validate``: an opaque
  client reference, the date the sheet describes, the household, positions, goals, stated facts and the
  answers the prototype's services read. Everything the eigentliCH prototype read from its database, its
  stored submission and its member facts, made explicit (LBS-04).

Outbound:

* ``LifeBalanceSheet`` (``lbs-balance-sheet@1.0.0``): the grid (role by capital type), the totals with the
  net-worth identity, human capital per person, the two pillars, the property, liquidity and retirement
  findings, the risk profile, a ``MandateProposal`` in the shape of ``pcp-mandate@1.0.0``, every gap, and
  provenance. A section that cannot be computed carries ``status = not_available`` and the reason, never a
  number (LBS-07).
* ``Calibration`` (``lbs-calibration@1.3.0``): the prototype's content records verbatim, with their approval
  metadata, the mandate policy figures and, from 1.1.0 on, the optional ``corrections`` block that says which
  prototype behaviours the calibration corrects (LBS-24; from 1.2.0 on, the three of LBS-28 as well); from 1.3.0
  on, the optional ``real_view`` block (LBS-31): the long-run inflation assumption per currency and the
  plausibility ceiling of a required return by risk level. Older payloads are still read: a
  ``lbs-calibration@1.0.0`` payload (the seed 1.0.0) has no corrections block and so reproduces the prototype; a
  ``lbs-calibration@1.1.0`` payload names the four corrections of LBS-24 only; a ``lbs-calibration@1.2.0`` payload
  has no real view.

**Additive fields are left out when unset.** The fields added for the nominal and real view (LBS-31 to LBS-35)
are ``None`` under a calibration without the ``real_view`` block and are then left out of the serialised sheet,
so a sheet under 1.0.0 to 1.3.0 keeps its bytes and its artefact id.

Mirrored, never imported (Engine Building Guide section 1): the bucket vocabularies and the bound-source rule
of ``pcp-mandate@1.0.0`` (Optimizer ``pcp``, contracts.py), which the mandate proposal is shaped to.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

N_STATES = 25

CONTRACT_VERSIONS: dict[str, str] = {
    "LifeBalanceSheetRequest": "lbs-request@1.0.0",
    "LifeBalanceSheet": "lbs-balance-sheet@1.0.0",
    "ValidationReport": "lbs-validation@1.0.0",
    "Calibration": "lbs-calibration@1.3.0",
    # The shape the mandate proposal mirrors (Optimizer pcp). Mirrored, not imported.
    "Mandate(pcp)": "pcp-mandate@1.0.0",
}

NOTICE = "Model-derived research output. Not investment advice."

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

#: lbs's own role keys. The prototype stored ``growth`` for the first role; the System Build Manual and pcp
#: call it ``Gain``. ``growth`` is accepted on the way in and mapped to ``gain`` (LBS-05).
ROLES: tuple[str, ...] = ("gain", "income", "stabilisation", "protection")
ROLE_SYNONYMS: dict[str, str] = {"growth": "gain"}
CAPITAL_TYPES: tuple[str, ...] = ("human", "financial")
MAGNITUDE_UNITS: tuple[str, ...] = ("chf", "chf_per_year", "share_of_total")
#: The units that denote an amount at a point in time. ``chf`` is a prefix of ``chf_per_year``: every test is
#: ``unit in STOCK_UNITS``, never a prefix match (the prototype's A105 defect).
STOCK_UNITS: tuple[str, ...] = ("chf",)
FLOW_UNIT = "chf_per_year"
STOCK_KINDS: tuple[str, ...] = ("asset", "liability")
LIQUIDITY: tuple[str, ...] = ("immediate", "within_months", "within_years", "illiquid")
#: What kind of holding a financial stock is, stated rather than read off a label (LBS-06). ``pillar_2``
#: includes vested-benefits accounts (Freizuegigkeit).
VESSELS: tuple[str, ...] = ("free", "pillar_2", "pillar_3a", "real_asset")
PERSON_KINDS: tuple[str, ...] = ("adult", "dependant")
GOAL_KINDS: tuple[str, ...] = ("property", "retirement", "other")

#: pcp-mandate@1.0.0, mirrored: the seven bounded dimensions and which source each takes (System Build Manual
#: section 14.2, pcp PCP-12). lbs fills only ``derived`` dimensions; ``policy`` ones are the curator's.
PCP_DIMENSIONS: tuple[str, ...] = ("currency", "region", "role", "capital_type", "liquidity", "phase",
                                   "asset_class")
PCP_BOUND_SOURCE: dict[str, str] = {
    "currency": "derived", "liquidity": "derived", "role": "derived",
    "asset_class": "policy", "capital_type": "policy", "phase": "policy", "region": "policy",
}
PCP_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "currency": ("CHF", "USD", "EUR", "RMB", "GBP", "JPY", "HKD", "AUD", "INR", "Others"),
    "role": ("Gain", "Income", "Stabilisation", "Protection"),
    "liquidity": ("Daily", "Quarterly", "Yearly", "Decade"),
}

Role = Literal["gain", "income", "stabilisation", "protection"]
CapitalType = Literal["human", "financial"]
MagnitudeUnit = Literal["chf", "chf_per_year", "share_of_total"]
StockKind = Literal["asset", "liability"]
Liquidity = Literal["immediate", "within_months", "within_years", "illiquid"]
Vessel = Literal["free", "pillar_2", "pillar_3a", "real_asset"]
PersonKind = Literal["adult", "dependant"]
GoalKind = Literal["property", "retirement", "other"]
Verdict = Literal["meets", "does_not_meet", "could_not_be_determined"]
Status = Literal["available", "not_available"]
GapKind = Literal["not_in_the_request", "record_not_approved", "needs_an_unpublished_assumption",
                  "owned_by_another_engine", "past_its_validity_horizon"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _opaque(value: str, what: str) -> str:
    """Identifiers are opaque tokens: letters, digits, dot, dash, underscore. A space or an ``@`` means a name
    or an e-mail address is being passed where a reference belongs (LBS-03)."""
    if not _ID.match(value):
        raise ValueError(f"{what} {value!r} must be an opaque reference (letters, digits, '.', '-', '_', at most "
                         "64 characters); names and e-mail addresses do not belong in a request")
    return value


def _finite(value: Optional[float], what: str) -> Optional[float]:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{what} must be finite")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Additive(_Frozen):
    """A model that gained optional fields after artefacts were stored: each field named in ``_additive`` is left
    out of the serialised form while it is ``None``, so an artefact without it keeps its bytes (LBS-35)."""

    _additive: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _leave_out_unset_additive_fields(self, handler: Any) -> Any:
        data = handler(self)
        if isinstance(data, dict):
            for name in self._additive:
                if data.get(name) is None:
                    data.pop(name, None)
        return data


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------

class HumanCapitalAnswers(_Frozen):
    """The intake answers ``services/human_capital.py`` reads, per person. Each is optional: an unanswered
    one leaves its capital absent, never zero."""

    #: One of the five BFS education categories, verbatim (``human-capital.json``, expertise anchors).
    qualification_highest: Optional[str] = None
    qualification_year: Optional[float] = None
    years_in_field: Optional[float] = None
    #: Training under way. Clears the recency penalty unless it is a no (``nein``, ``no``, ``keine``, ...).
    education_recent: Optional[str] = None
    network_people: Optional[float] = Field(default=None, ge=0)
    mandates: Optional[float] = Field(default=None, ge=0)
    #: One of the published reach options, or unanswered (read at face value).
    network_reach: Optional[str] = None
    #: A published level (``"1"``, ``"0.85"``, ...) or a bare number in [0, 1].
    health: Optional[str] = None
    #: Health is K3 data: ``True`` when it was filtered or erased. H is then absent and the caveat says which
    #: way the error runs.
    health_withheld: bool = False
    hours_per_week: Optional[float] = Field(default=None, ge=0)
    #: A published band (``"5-10"`` with an en dash, ...) or a number of hours.
    rest_hours: Optional[str] = None
    hours_learning: Optional[float] = Field(default=None, ge=0)
    hours_network: Optional[float] = Field(default=None, ge=0)


class AhvFacts(_Frozen):
    #: The massgebendes durchschnittliches Jahreseinkommen. Never derived; when absent the pension is an
    #: illustration from current income and says so (``ahv.illustration_for``).
    mdje: Optional[float] = Field(default=None, ge=0)
    #: Missing contribution years as the person stated them; ``None`` is not a complete record.
    contribution_years_missing: Optional[int] = Field(default=None, ge=0)


class Person(_Frozen):
    person_id: str
    kind: PersonKind
    age: Optional[int] = Field(default=None, ge=0, le=120)
    #: The income a person stated where no income position carries it (the submission's ``income_gross``).
    stated_gross_income: Optional[float] = Field(default=None, ge=0)
    human_capital: HumanCapitalAnswers = Field(default_factory=HumanCapitalAnswers)
    ahv: AhvFacts = Field(default_factory=AhvFacts)

    @field_validator("person_id")
    @classmethod
    def _pid(cls, value: str) -> str:
        return _opaque(value, "person_id")

    @field_validator("stated_gross_income")
    @classmethod
    def _income(cls, value: Optional[float]) -> Optional[float]:
        return _finite(value, "stated_gross_income")


class Household(_Frozen):
    """The composition as stated. Never inferred: ``kind`` is who the household says is a dependant."""

    #: The date the composition describes, which its validity horizon runs from (``currency-horizons``).
    composition_as_of: date
    persons: tuple[Person, ...] = Field(min_length=1)
    #: The adult the plan is for: the prototype's account holder, whose age a goal without an owner is
    #: projected from. Stated, never picked (LBS-16).
    principal: Optional[str] = None

    @model_validator(mode="after")
    def _a_household(self) -> "Household":
        ids = [p.person_id for p in self.persons]
        if len(set(ids)) != len(ids):
            raise ValueError("a person_id appears twice in the household")
        if self.principal is not None and not any(p.person_id == self.principal and p.kind == "adult"
                                                  for p in self.persons):
            raise ValueError(f"the principal {self.principal!r} is not an adult of the household")
        if not any(p.kind == "adult" for p in self.persons):
            raise ValueError("a household with no adult in it has nobody who can own a goal")
        return self


class Position(_Frozen):
    """A filled cell of the grid. Valid with one field filled; nothing is required in groups."""

    position_id: str
    role: Role
    capital_type: CapitalType
    magnitude: Optional[float] = None
    unit: Optional[MagnitudeUnit] = None
    #: Asset or liability, exactly when the unit is ``chf``. A debt is a positive amount owed, never a
    #: negative magnitude.
    stock_kind: Optional[StockKind] = None
    liquidity: Optional[Liquidity] = None
    vessel: Optional[Vessel] = None
    #: The person the position belongs to. Per-person sections read owned positions only.
    owner: Optional[str] = None
    active: bool = True
    #: Goals this position funds. Overlap is permitted (R-030): one holding may fund several goals.
    funds_goals: tuple[str, ...] = ()

    @field_validator("role", mode="before")
    @classmethod
    def _role(cls, value: Any) -> Any:
        return ROLE_SYNONYMS.get(value, value) if isinstance(value, str) else value

    @field_validator("position_id")
    @classmethod
    def _pid(cls, value: str) -> str:
        return _opaque(value, "position_id")

    @model_validator(mode="after")
    def _units(self) -> "Position":
        _finite(self.magnitude, f"position {self.position_id} magnitude")
        if (self.magnitude is None) != (self.unit is None):
            raise ValueError(f"position {self.position_id}: a magnitude has a unit and a unit has a magnitude")
        is_stock = self.unit in STOCK_UNITS
        if is_stock != (self.stock_kind is not None):
            raise ValueError(f"position {self.position_id}: stock_kind is stated exactly when the unit is chf")
        if is_stock and self.magnitude is not None and self.magnitude < 0:
            raise ValueError(f"position {self.position_id}: a stock in chf is never negative; a debt is "
                             "stock_kind 'liability' with a positive magnitude")
        if self.vessel is not None and not (is_stock and self.capital_type == "financial"):
            raise ValueError(f"position {self.position_id}: a vessel describes a financial stock in chf")
        return self


class Goal(_Frozen):
    goal_id: str
    #: Stated, not guessed from the goal's name (the prototype matched words; LBS-06).
    kind: GoalKind
    #: For a property goal the PRICE; for a retirement goal what the household needs per year; otherwise the
    #: amount the goal needs.
    target_amount: Optional[float] = Field(default=None, ge=0)
    target_date: Optional[date] = None
    #: For a property goal: a key of ``occupancy`` in ``property-funding.json``. Never inferred.
    occupancy: Optional[str] = None
    owners: tuple[str, ...] = ()
    #: This goal's share of the household's one yearly saving (``mandate.annual_contribution``), 0 to 1.
    #: Optional and additive (LBS-29): the stated shares of all goals sum to at most 1 (a rest may go to no goal
    #: in the request); a goal without one has not said. Read from calibration 1.3.0 on.
    contribution_share: Optional[float] = Field(default=None, ge=0, le=1)
    #: Whether ``target_amount`` is in today's francs (the purchasing power of ``as_of``) or in the francs of the
    #: target date. Optional and additive (LBS-31); a missing basis means ``today``, the owner's decision 7 of
    #: 29.09.2026, and lbs inflates the amount to the target date. Read from calibration 1.4.0 on.
    amount_basis: Optional[Literal["today", "future"]] = None

    @field_validator("goal_id")
    @classmethod
    def _gid(cls, value: str) -> str:
        return _opaque(value, "goal_id")


class StatedFacts(_Frozen):
    canton: Optional[str] = None
    #: As the intake words it (``intake-scales.json`` civil_status); decides the AHV couple cap.
    civil_status: Optional[str] = None
    #: The household stated that it owes nothing. Only this makes liabilities zero; no liability position is
    #: not a statement that there is no debt.
    has_no_liabilities: bool = False


class RiskAnswers(_Frozen):
    """What ``services/profile_inputs.py`` and ``services/risk_profile.py`` read from the submission."""

    #: Largest tolerable loss as a fraction (the intake's ``30 %`` is 0.30).
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
    #: The mortgage outstanding, CHF. 0 is a paid-off mortgage from calibration 1.3.0 on (LBS-28); unstated is
    #: unknown. Before 1.3.0 a 0 read as unstated, as in the prototype.
    mortgage: Optional[float] = Field(default=None, ge=0)
    mortgage_rate_pct: Optional[float] = Field(default=None, ge=0)
    amortisation_per_year: Optional[float] = Field(default=None, ge=0)


class MandateRequest(_Frozen):
    """Which goal the mandate proposal serves, and what the household contributes towards it."""

    goal_id: str
    #: The yearly contribution toward the goal: what the household can put aside each year, in CHF (the
    #: consumer app's onboarding question "How much can you put aside each year?", LBS-25). Required for a
    #: required return and the target curve: an absent contribution is a gap, never zero; a stated 0 is 0.
    annual_contribution: Optional[float] = Field(default=None, ge=0)
    name: Optional[str] = None
    #: Whether the yearly contribution rises with prices (the consumer app's "steigt der Betrag mit der
    #: Teuerung?"). Optional and additive (LBS-31); missing means fixed in francs, the owner's decision 9. Read
    #: from calibration 1.4.0 on.
    contribution_indexed: Optional[bool] = None


class LifeBalanceSheetRequest(_Frozen):
    """Body of ``POST /run`` and ``POST /validate``."""

    contract_version: Literal["lbs-request@1.0.0"] = "lbs-request@1.0.0"
    client_ref: str
    #: The date the sheet describes. Every age, horizon and currency judgement is measured from it; the engine
    #: reads no clock.
    as_of: date
    #: ``None`` uses the active calibration from ``config.yaml``.
    calibration_version: Optional[str] = None
    #: ``None`` means the household has not stated its composition: a gap, never a single-person default.
    household: Optional[Household] = None
    positions: tuple[Position, ...] = ()
    goals: tuple[Goal, ...] = ()
    facts: StatedFacts = Field(default_factory=StatedFacts)
    risk: RiskAnswers = Field(default_factory=RiskAnswers)
    mandate: Optional[MandateRequest] = None

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _opaque(value, "client_ref")

    @model_validator(mode="after")
    def _references(self) -> "LifeBalanceSheetRequest":
        pids = [p.position_id for p in self.positions]
        if len(set(pids)) != len(pids):
            raise ValueError("a position_id appears twice")
        gids = [g.goal_id for g in self.goals]
        if len(set(gids)) != len(gids):
            raise ValueError("a goal_id appears twice")
        persons = {p.person_id for p in self.household.persons} if self.household else set()
        for p in self.positions:
            if p.owner is not None and p.owner not in persons:
                raise ValueError(f"position {p.position_id} names owner {p.owner!r}, who is not in the household")
            for g in p.funds_goals:
                if g not in gids:
                    raise ValueError(f"position {p.position_id} funds goal {g!r}, which is not in the request")
        for g in self.goals:
            for o in g.owners:
                if o not in persons:
                    raise ValueError(f"goal {g.goal_id} names owner {o!r}, who is not in the household")
            if g.occupancy is not None and g.kind != "property":
                raise ValueError(f"goal {g.goal_id} states an occupancy but is not a property goal")
        if self.facts.has_no_liabilities and any(p.stock_kind == "liability" for p in self.positions):
            raise ValueError("facts.has_no_liabilities contradicts a liability position in the request")
        shares = [g.contribution_share for g in self.goals if g.contribution_share is not None]
        if sum(shares) > 1 + 1e-9:
            raise ValueError(f"the goals' contribution shares sum to {sum(shares):.6g}; shares of one yearly saving "
                             "sum to at most 1")
        if self.mandate is not None and self.mandate.goal_id not in gids:
            raise ValueError(f"the mandate names goal {self.mandate.goal_id!r}, which is not in the request")
        return self


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

#: The records a calibration must carry, by the prototype's file names.
RECORD_NAMES: tuple[str, ...] = ("ahv-pension", "bvg-projection", "human-capital", "property-funding",
                                 "liquidity-levers", "risk-profile", "intake-scales", "roles",
                                 "currency-horizons")


class LiquidityRule(_Frozen):
    """One rung of the deadline rule (``engines/lbs/derive.py:_liquidity_floor``)."""

    horizon_at_most_years: float
    bounds: dict[str, tuple[float, float]]


class MandatePolicy(_Frozen):
    """The figures the mandate proposal needs that no content record holds. Each is the eigentliCH draft's
    (``Projects/eigentliCH/engines/lbs/derive.py`` and the S-curve engine), named for its source."""

    #: The target curve's shape when no approved risk profile supplies one: CIO policy, derive.py M50.
    curve_floor_offset: float = -0.025
    curve_ceiling_offset: float = 0.025
    #: A goal in this currency implies a floor in it (derive.py): currency risk against a fixed liability.
    currency: str = "CHF"
    currency_floor: float = 0.5
    liquidity_rules: tuple[LiquidityRule, ...]
    #: S-curve engine: monthly steps, a 1000 percent search ceiling, bisection to 1e-10.
    steps_per_year: int = 12
    search_ceiling: float = 10.0
    bisection_tolerance: float = 1e-10
    bisection_max_iterations: int = 200
    #: ``eigentlich.engines.DAYS_PER_YEAR``: a goal's horizon is its date less as_of over this.
    days_per_year: float = 365.2425
    #: ``profile_inputs.collect``: the capacity horizon uses 365 (C-02 kept the quarter day out).
    capacity_days_per_year: float = 365.0


class Corrections(_Frozen):
    """The prototype behaviours a calibration corrects (owner, 29.09.2026). The four of LBS-17 (LBS-24) are
    stated, none has a default: a calibration either names all four or carries no block at all, and no block is
    the prototype's behaviour (the reproduction mode, calibrations 1.0.0 and 1.1.0). The three of LBS-28 came
    later: a calibration written before them (1.2.0) does not name them, which reads as not corrected, and an
    unnamed one is left out of the canonical form so that calibration keeps its bytes and its hash."""

    #: The required-return search reaches the stated ``search_ceiling`` (1000 percent) instead of stopping at
    #: the last doubling below it (8, i.e. 800 percent, in the S-curve engine).
    required_return_search_reaches_its_ceiling: bool
    #: Without a dated goal the capacity horizon is ``plan_until_age`` less the subject's age, in years, not
    #: the age itself.
    capacity_horizon_is_years_to_the_planned_age: bool
    #: A stated zero income is zero (a person on leave, a household without earnings); only an income nobody
    #: stated is unknown.
    zero_income_is_a_stated_zero: bool
    #: A funding stock without a vessel is a named gap: neither hard equity for a property goal nor free wealth
    #: for the risk capacity.
    unstated_vessel_is_a_gap: bool
    # -- LBS-28 (lbs@1.2.0, calibration 1.3.0); ``None`` is "not named", the behaviour before them
    #: A human-capital stock in chf is human capital only: never free wealth for the risk capacity and never
    #: equity for a property goal (the prototype counted it as free).
    human_capital_is_never_free_wealth: Optional[bool] = None
    #: A stated mortgage of 0 is a paid-off mortgage, a debt service of 0; only an unstated one is unknown (the
    #: prototype read 0 as no answer, ``if r.mortgage``).
    zero_mortgage_is_a_stated_zero: Optional[bool] = None
    #: The yearly saving is split between the goals by their stated ``contribution_share``; the designated
    #: goal's missing share, with other goals in the request, is a gap (LBS-29). Before: all of it went to the
    #: designated goal.
    contribution_is_split_by_goal_share: Optional[bool] = None


#: The corrections LBS-28 added, which a ``lbs-calibration@1.1.0`` payload cannot name.
LATER_CORRECTIONS: tuple[str, ...] = ("human_capital_is_never_free_wealth", "zero_mortgage_is_a_stated_zero",
                                      "contribution_is_split_by_goal_share")


#: The currencies lbs carries an inflation assumption for (decision 3: the reporting currency's index).
INFLATION_CURRENCIES: tuple[str, ...] = ("CHF", "EUR", "USD")


class InflationAssumption(_Frozen):
    """The long-run expected inflation of one currency: a simple annual rate, with where it comes from. lbs reads
    no engine at run time; the figure is the calibration's (LBS-32)."""

    annual_rate: float
    #: The price index the rate describes (decision 3).
    index: str
    #: How the figure was obtained, in one sentence a reader can repeat.
    source: str
    #: What else the figure was checked against (the central bank's target).
    cross_check: str = ""

    @field_validator("annual_rate")
    @classmethod
    def _band(cls, value: float) -> float:
        if not math.isfinite(value) or not (-0.20 <= value <= 1.00):
            raise ValueError("an inflation assumption outside -20 % to +100 % a year is not computable (decision 4)")
        return value


class PlausibilityRow(_Frozen):
    """One row of the plausibility table: the most a portfolio at this risk level can reasonably be planned to
    earn, as a real annual return (simple, decimal)."""

    risk_level: float = Field(ge=0.0, le=1.0)
    real_return: float


class RealViewPolicy(_Frozen):
    """The figures the nominal and real view needs (LBS-31 to LBS-34). Present from calibration 1.4.0 on; a
    calibration without it computes as before, in the stated francs throughout."""

    inflation: dict[str, InflationAssumption]
    #: Decision 4: inside this band a real figure is ``measured``, outside it (up to the computable band)
    #: ``extrapolated``.
    measured_band: tuple[float, float] = (-0.10, 0.20)
    #: The plausibility ceiling by risk level, interpolated linearly between rows (LBS-34).
    plausibility: tuple[PlausibilityRow, ...]
    plausibility_source: str
    #: The levers search a longer horizon up to this many years.
    lever_horizon_limit_years: float = Field(default=100.0, gt=0)

    @model_validator(mode="after")
    def _rows(self) -> "RealViewPolicy":
        levels = [r.risk_level for r in self.plausibility]
        if len(levels) < 2 or levels != sorted(set(levels)) or levels[0] != 0.0 or levels[-1] != 1.0:
            raise ValueError("the plausibility table runs from risk level 0 to 1 in strictly rising rows")
        reals = [r.real_return for r in self.plausibility]
        if reals != sorted(reals):
            raise ValueError("the plausibility ceiling does not fall as the risk level rises")
        missing = sorted(set(INFLATION_CURRENCIES) - set(self.inflation))
        if missing:
            raise ValueError(f"the real view lacks an inflation assumption for {missing}")
        return self


class Calibration(_Frozen):
    #: 1.0.0 is the seed's contract (no corrections block); 1.1.0 adds the optional block with the four
    #: corrections of LBS-24; 1.2.0 adds the three of LBS-28 to it; 1.3.0 adds the optional ``real_view``
    #: block (LBS-31). All four are read.
    contract_version: Literal["lbs-calibration@1.0.0", "lbs-calibration@1.1.0", "lbs-calibration@1.2.0",
                              "lbs-calibration@1.3.0"] = "lbs-calibration@1.3.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    #: The prototype's content records, verbatim, each with its ``_about`` approval metadata. A record is
    #: approved when ``_about.provisional`` is false and ``_about.published_by`` is set, the prototype's gate.
    records: dict[str, dict[str, Any]]
    policy: MandatePolicy
    #: ``None``: the prototype's behaviour throughout, kept selectable for golden fidelity (LBS-24).
    corrections: Optional[Corrections] = None
    #: ``None``: no real view; goal amounts are read in the francs they are stated in, as before (LBS-31).
    real_view: Optional[RealViewPolicy] = None

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
        if self.policy.curve_floor_offset > self.policy.curve_ceiling_offset:
            raise ValueError("the curve's floor offset exceeds its ceiling offset")
        if self.corrections is not None and self.contract_version == "lbs-calibration@1.0.0":
            raise ValueError("a corrections block needs lbs-calibration@1.1.0; 1.0.0 has none")
        if (self.corrections is not None and self.contract_version == "lbs-calibration@1.1.0"
                and any(getattr(self.corrections, name) is not None for name in LATER_CORRECTIONS)):
            raise ValueError(f"the corrections {list(LATER_CORRECTIONS)} need lbs-calibration@1.2.0")
        if self.real_view is not None and self.contract_version != "lbs-calibration@1.3.0":
            raise ValueError("a real_view block needs lbs-calibration@1.3.0")
        return self


# ---------------------------------------------------------------------------
# The balance sheet
# ---------------------------------------------------------------------------

class Gap(_Frozen):
    """One input the sheet could not use, and why. Never filled in."""

    section: str
    input: str
    kind: GapKind
    reason: str


class RecordUse(_Frozen):
    """A content record a section read, and whether it was approved when read."""

    record: str
    approved: bool
    published_by: Optional[str] = None
    decided_on: Optional[str] = None
    effective_from: Optional[str] = None
    #: True where the prototype reads this record without its approval gate (LBS-08).
    read_without_gate: bool = False


class Currency(_Frozen):
    input_class: str
    stated_on: date
    age_days: int
    horizon_months: int
    expires_on: date
    expired: bool
    load_bearing: bool
    determination: Literal["stands", "could_not_be_determined"]


class HouseholdPerson(_Frozen):
    person_id: str
    kind: PersonKind
    age: Optional[int]


class HouseholdSection(_Frozen):
    stated: bool
    composition_as_of: Optional[date]
    adults: tuple[HouseholdPerson, ...]
    dependants: tuple[HouseholdPerson, ...]
    married: Optional[bool]
    currency: Optional[Currency]


class GridCell(_Frozen):
    role: Role
    capital_type: CapitalType
    display: str
    definition: Optional[str]
    positions: tuple[str, ...]
    #: Sums over the cell's active positions per unit, ``None`` where the cell states nothing in that unit.
    assets_chf: Optional[float]
    liabilities_chf: Optional[float]
    flows_chf_per_year: Optional[float]
    shares_of_total: Optional[float]


class Totals(_Frozen):
    """Stocks in chf over active positions. Assets and liabilities are never netted into one input."""

    financial_assets: Optional[float]
    human_assets: Optional[float]
    total_assets: Optional[float]
    liabilities: Optional[float]
    #: Assets less liabilities. ``None`` when either side is unknown; never computed against a zero nobody
    #: stated.
    net_worth: Optional[float]
    #: ``total_assets - liabilities == net_worth`` to 1e-9 relative, checked on every sheet.
    identity_holds: Optional[bool]
    by_vessel: dict[str, Optional[float]]
    #: Free financial assets: what a goal can draw on (derive.py's W_L, the prototype's "free").
    drawable: Optional[float]
    #: Gross yearly income of the household from income positions (``goals._household_income``).
    household_income: Optional[float]
    household_income_basis: str


class Capital(_Frozen):
    key: Literal["E", "N", "H"]
    value: Optional[float]
    source: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    absent_because: Optional[str] = None
    note: Optional[str] = None


class TimeBudget(_Frozen):
    productive_week_hours: float
    tau_Y: Optional[float]
    tau_E: Optional[float]
    tau_N: Optional[float]
    tau_H: Optional[float]
    leisure: Optional[float]
    sources: dict[str, str]
    caveats: tuple[str, ...]


class NotAvailable(_Frozen):
    status: Literal["not_available"] = "not_available"
    reason: str
    record: Optional[str] = None


class PersonHumanCapital(_Frozen):
    person_id: str
    E: Capital
    N: Capital
    H: Capital
    caveats: tuple[str, ...]
    time_budget: TimeBudget
    #: Earning power is the stochastic model's (personal_alm, lbsim), not lbs's (LBS-10).
    earning_power: NotAvailable


class AhvPension(_Frozen):
    status: Literal["available"] = "available"
    basis: Literal["mdje_stated", "current_income_as_a_stand_in_for_the_lifetime_average"]
    mdje: float
    years: Optional[int]
    full_scale: int
    full_monthly: int
    factor: float
    monthly: float
    yearly: float
    at_minimum: bool
    at_maximum: bool
    caveats: tuple[str, ...]
    levers: tuple[dict[str, Any], ...]


class BvgProjection(_Frozen):
    status: Literal["available"] = "available"
    from_age: int
    to_age: int
    opening_balance: float
    gross_salary: float
    coordinated: Optional[float]
    interest_rate: float
    years: tuple[dict[str, Any], ...]
    closing_balance: float
    total_credited: float
    total_interest: float
    conversion_rate: float
    monthly_pension: float
    yearly_pension: float
    caveats: tuple[str, ...]
    levers: tuple[dict[str, Any], ...]


class PersonPensions(_Frozen):
    person_id: str
    ahv: AhvPension | NotAvailable
    bvg: BvgProjection | NotAvailable


class CoupleCap(_Frozen):
    status: Literal["available"] = "available"
    uncapped_monthly: float
    cap: int
    monthly: float
    yearly: float
    cap_binds: bool
    lost_to_the_cap_monthly: float


Basis = Literal["nominal", "real"]


class PropertyFinding(_Additive):
    _additive: ClassVar[tuple[str, ...]] = ("basis",)

    goal_id: str
    verdict: Verdict
    price_chf: Optional[float]
    target_date: Optional[date]
    occupancy: Optional[str]
    equity: Optional[dict[str, Any]]
    affordability: Optional[dict[str, Any]]
    binds_on: tuple[str, ...]
    undetermined_because: tuple[str, ...]
    ineligible_funding: tuple[dict[str, Any], ...]
    levers: tuple[dict[str, Any], ...]
    occupancy_options: tuple[dict[str, Any], ...]
    conventions: str = "property-funding"
    #: From calibration 1.4.0: ``real``, the equity and affordability tests run on the price in today's francs
    #: (a ratio test in today's terms; a price stated in future francs is deflated to today first, LBS-31).
    basis: Optional[Literal["real"]] = None


class LiquidityFinding(_Frozen):
    goal_id: str
    state: Literal["short_on_date"] = "short_on_date"
    gap_chf: Optional[float]
    due_date: date
    reason: str
    position_ids: tuple[str, ...]
    blocks_certification: bool = True
    prepared: dict[str, Any]


class RetirementView(_Frozen):
    """The retirement comparison in one basis (LBS-31)."""

    basis: Basis
    #: ``real``: francs of ``as_of`` (today's francs), ``as_at`` null; ``nominal``: francs of ``as_at``.
    as_at: Optional[date]
    needs_per_year: Optional[float]
    ahv_per_year: Optional[float]
    bvg_per_year: Optional[float]
    covered_per_year: Optional[float]
    shortfall_per_year: Optional[float]


class RetirementFinding(_Additive):
    _additive: ClassVar[tuple[str, ...]] = ("basis", "views")

    goal_id: str
    verdict: Verdict
    needs_per_year: Optional[float]
    target_date: Optional[date]
    undetermined_because: tuple[str, ...]
    caveats: tuple[str, ...]
    ahv: Optional[dict[str, Any]]
    pillar2: Optional[dict[str, Any]]
    covered_per_year: Optional[float]
    shortfall_per_year: Optional[float]
    conventions: tuple[str, ...] = ("ahv-pension", "bvg-projection")
    #: From calibration 1.4.0: ``real``, the need, the pensions and the verdict above are in today's francs (the
    #: BVG pension, nominal by law, deflated from its first year), and ``views`` carries both bases (LBS-33).
    basis: Optional[Literal["real"]] = None
    views: Optional[dict[str, RetirementView]] = None


class GoalObservations(_Frozen):
    goal_id: str
    observations: tuple[dict[str, Any], ...]


class RiskProfile(_Frozen):
    status: Literal["available"] = "available"
    value: Optional[float]
    binds_on: Optional[str]
    willingness: dict[str, Any]
    capacity: dict[str, Any]
    capacity_inputs: dict[str, Any]
    role_bounds: Optional[dict[str, dict[str, float]]]
    asset_class_bounds: Optional[dict[str, dict[str, float]]]
    curve_slope: Optional[dict[str, float]]
    sustainability: dict[str, Any]
    caveats: tuple[str, ...]


class ProposedBound(_Frozen):
    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    #: Why this bound has this value, in one sentence a curator can check.
    reasoning: str

    @model_validator(mode="after")
    def _ordered(self) -> "ProposedBound":
        if self.lower > self.upper + 1e-12:
            raise ValueError(f"bound lower {self.lower} exceeds upper {self.upper}")
        return self


class CuratorItem(_Frozen):
    field: str
    reason: str


class RequiredReturnView(_Frozen):
    """The mandate's target and required return in one basis (LBS-31). Real = (1 + nominal) / (1 + inflation)
    - 1, exact (Fisher); in logs, real = nominal - ln(1 + inflation)."""

    basis: Basis
    #: ``nominal``: francs of the target date; ``real``: today's francs (the purchasing power of ``as_of``).
    target_chf: Optional[float]
    #: A decimal annual rate compounded monthly, as ``required_return``; ``None`` when none exists.
    required_return: Optional[float]
    #: ``ln(1 + required_return)``, the unit of the target curve.
    required_return_log: Optional[float]


class Plausibility(_Frozen):
    """Whether a portfolio within the household's risk profile can reasonably earn the required return
    (LBS-34). ``feasible`` keeps its narrow meaning (a return below the search ceiling exists); this is the
    judgement a household can act on."""

    judgement: Literal["realistic", "not_realistic", "could_not_be_determined"]
    #: The real required return judged (simple, decimal a year); ``None`` when none exists below the ceiling.
    required_return_real: Optional[float]
    #: The ceiling applied, real and nominal (simple, decimal a year); ``None`` when no single ceiling applies.
    ceiling_real: Optional[float]
    ceiling_nominal: Optional[float]
    #: The risk profile's level the ceiling is read at; ``None`` without a profile.
    risk_level: Optional[float]
    ceiling_source: str
    reason: str
    #: When not realistic: what reaches the goal at the ceiling (a longer horizon, a higher saving, a smaller
    #: goal), each computed.
    levers: tuple[dict[str, Any], ...] = ()


class MandateProposal(_Additive):
    """A proposal in the shape of ``pcp-mandate@1.0.0`` for the curator to finalise. Unreleased.

    Field names are pcp's. lbs fills what the household determines (the curve's level, the derived
    dimensions currency, liquidity and, when an approved risk profile exists, role) and leaves every policy
    field to the curator, listed in ``curator_to_fill``. ``complete`` is true only when nothing is left, which
    in lbs 1.x is never: the universe, the position cap and the regime blend are always the curator's (LBS-12).
    """

    _additive: ClassVar[tuple[str, ...]] = ("basis", "views", "plausibility")

    status: Literal["available"] = "available"
    shape: Literal["pcp-mandate@1.0.0"] = "pcp-mandate@1.0.0"
    client: str
    name: str
    currency: str
    horizon_years: float = 1.0
    curve_unit: Literal["annualised_log_return"] = "annualised_log_return"
    target_curve: Optional[tuple[float, ...]]
    universe: Optional[tuple[str, ...]] = None
    max_single_position: Optional[float] = None
    esg_min: Optional[float] = None
    fixed_allocations: dict[str, float] = Field(default_factory=dict)
    bounds: dict[str, dict[str, ProposedBound]]
    bound_sources: dict[str, Literal["derived"]]
    regime_weights: Optional[dict[str, float]] = None
    regime_market: Optional[str] = None
    # -- what the proposal rests on --
    goal_id: str
    goal_kind: GoalKind
    target_basis: str
    target_chf: Optional[float]
    goal_horizon_years: Optional[float]
    drawable_chf: Optional[float]
    #: The yearly contribution the required return rests on: the household's stated saving, or from
    #: calibration 1.3.0 this goal's part of it (its ``contribution_share``, LBS-29; the notes say which).
    annual_contribution: Optional[float]
    #: The constant annual return (decimal, compounded monthly) that funds the goal by its date; ``0.0`` when
    #: already funded, ``None`` when unreachable at any return below the search ceiling.
    required_return: Optional[float]
    feasible: Optional[bool]
    curve_shape: dict[str, Any]
    curator_to_fill: tuple[CuratorItem, ...]
    complete: bool
    release_state: Literal["unreleased"] = "unreleased"
    notes: tuple[str, ...] = ()
    # -- the nominal and real view (LBS-31, LBS-34), from calibration 1.4.0; left out before
    #: The basis of ``target_curve``, ``target_chf`` and ``required_return``: always ``nominal`` (decision 6; the
    #: optional ``basis`` of ``pcp-mandate@1.0.0``, default nominal).
    basis: Optional[Literal["nominal"]] = None
    #: Both views of the target and the required return, side by side: ``nominal`` and ``real``.
    views: Optional[dict[str, RequiredReturnView]] = None
    plausibility: Optional[Plausibility] = None

    @model_validator(mode="after")
    def _shape(self) -> "MandateProposal":
        if self.target_curve is not None and len(self.target_curve) != N_STATES:
            raise ValueError(f"the target curve has {len(self.target_curve)} points, expected {N_STATES}")
        for dimension, buckets in self.bounds.items():
            if PCP_BOUND_SOURCE.get(dimension) != "derived":
                raise ValueError(f"lbs proposes derived dimensions only; {dimension!r} is policy")
            vocabulary = PCP_VOCABULARIES.get(dimension, ())
            unknown = sorted(set(buckets) - set(vocabulary))
            if unknown:
                raise ValueError(f"{dimension} buckets {unknown} are not in pcp's vocabulary")
            if self.bound_sources.get(dimension) != "derived":
                raise ValueError(f"the {dimension} bounds must be labelled 'derived'")
        return self


class InflationUse(_Frozen):
    """The inflation assumption a sheet used (LBS-32)."""

    currency: str
    index: str
    #: Simple, decimal a year; and ``ln(1 + annual_rate)``, the rate every real figure is deflated by.
    annual_rate: float
    log_rate: float
    #: Decision 4: ``measured`` inside -10 % to +20 % a year, else ``extrapolated``.
    label: Literal["measured", "extrapolated"]
    source: str


class BasisAmount(_Frozen):
    basis: Basis
    amount: Optional[float]
    #: ``real``: francs of ``as_of``, ``as_at`` null; ``nominal``: francs of ``as_at`` (the goal's target date).
    as_at: Optional[date]
    #: Why the amount is absent, when it is.
    absent_because: Optional[str] = None


class GoalBasisView(_Frozen):
    """One goal's amount in both bases (LBS-31)."""

    goal_id: str
    kind: GoalKind
    #: What ``target_amount`` is: ``chf`` (a price or an amount) or ``chf_per_year`` (a retirement need).
    unit: Literal["chf", "chf_per_year"]
    amount_basis: Literal["today", "future"]
    #: False when the request did not say and decision 7's default (today's francs) was applied.
    amount_basis_stated: bool
    stated_amount: Optional[float]
    #: Whole months to the target date, over 12, and the price level there: ``(1 + inflation) ** horizon``.
    horizon_years: Optional[float]
    price_level: Optional[float]
    nominal: BasisAmount
    real: BasisAmount


class RealView(_Frozen):
    """The nominal and real view of the sheet (LBS-31): the inflation assumption, whether the contribution is
    indexed, and every goal's amount in both bases. Everything else on the sheet names its own basis."""

    currency: str
    inflation: InflationUse
    contribution_indexed: bool
    #: False when the request did not say and decision 9's default (fixed in francs) was applied.
    contribution_indexed_stated: bool
    goals: tuple[GoalBasisView, ...]
    convention: str = ("log returns throughout: real = nominal - ln(1 + inflation); a simple rate converts "
                       "exactly as (1 + nominal) / (1 + inflation) - 1. A figure is nominal unless its basis says "
                       "real; the default view is nominal (decision 6)")


class Provenance(_Frozen):
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    request_hash: str
    as_of: date
    records: tuple[RecordUse, ...]
    label: Literal["model-derived"] = "model-derived"


class LifeBalanceSheet(_Additive):
    """The artefact of one run."""

    _additive: ClassVar[tuple[str, ...]] = ("real_view",)

    contract_version: Literal["lbs-balance-sheet@1.0.0"] = "lbs-balance-sheet@1.0.0"
    artefact_id: str
    client_ref: str
    as_of: date
    calibration_version: str
    household: HouseholdSection
    grid: tuple[GridCell, ...]
    totals: Totals
    human_capital: tuple[PersonHumanCapital, ...]
    pensions: tuple[PersonPensions, ...]
    couple_cap: CoupleCap | NotAvailable
    property: tuple[PropertyFinding, ...]
    liquidity: tuple[LiquidityFinding, ...]
    retirement: tuple[RetirementFinding, ...]
    observations: tuple[GoalObservations, ...]
    risk_profile: RiskProfile | NotAvailable
    mandate_proposal: MandateProposal | NotAvailable
    gaps: tuple[Gap, ...]
    provenance: Provenance
    notice: str = NOTICE
    #: From calibration 1.4.0 (LBS-31); left out before.
    real_view: Optional[RealView] = None

    @model_validator(mode="after")
    def _identity(self) -> "LifeBalanceSheet":
        t = self.totals
        if t.net_worth is not None:
            if t.total_assets is None or t.liabilities is None:
                raise ValueError("net worth is stated while one side of the sheet is unknown")
            expected = t.total_assets - t.liabilities
            if abs(expected - t.net_worth) > 1e-9 * max(1.0, abs(expected)):
                raise ValueError("assets less liabilities does not equal net worth")
        if len(self.grid) != len(ROLES) * len(CAPITAL_TYPES):
            raise ValueError("the grid has eight cells, role by capital type")
        return self


class ValidationReport(_Frozen):
    contract_version: Literal["lbs-validation@1.0.0"] = "lbs-validation@1.0.0"
    ok: bool
    client_ref: str
    calibration_version: Optional[str]
    #: Why no sheet can be built (an unknown calibration). Empty when ``ok``.
    problems: tuple[str, ...]
    #: Every gap the sheet would report.
    gaps: tuple[Gap, ...]
    #: Section name to ``available`` or the reason it would not be.
    sections: dict[str, str]
    notice: str = NOTICE


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
    request: LifeBalanceSheetRequest
    artefact_id: Optional[str]
    gaps: tuple[Gap, ...]
    provenance: Optional[Provenance]
    error: Optional[str]
