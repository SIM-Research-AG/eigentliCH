"""What a member's own record can tell us about their capacity, and where each figure came from.

`services/risk_profile.capacity` takes five numbers. Three of them the plan holds; two of them it does
not, and this is where that gap gets closed honestly rather than by guessing.

**The plan first, the submission second, and never anything else.** Horizon comes from a dated goal, the
free share from the positions, income from the income position. Reserve months, the variable share, the
employment form and the debt service have no home in the schema — so they are read from the **stored
submission** (A154), which is the reason keeping the file whole was worth doing. Every value comes back
labelled with its source, because a figure derived from a plan the member can correct is not the same kind
of figure as one lifted out of a form they filled in once.

**A value that is nowhere is `None`**, and `capacity` drops the component rather than scoring it zero.
Nothing here substitutes a plausible number for an absent one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FLOW_UNIT, Goal, Position, STOCK_UNITS
from . import submissions as submission_service

#: Labels that mean a holding is Vorsorge and therefore not free. Same weakness as
#: `goals._capital_by_eligibility` and stated for the same reason: the plan has no vessel field, so this
#: reads what the member called the position. Until that field exists this is the honest best available,
#: and the direction of its error is named — an unrecognised pension label counts as FREE, which
#: overstates capacity rather than understating it.
_LOCKED = ("3a", "säule 3", "saule 3", "pensionskasse", "pk-", "2. säule", "freizügigkeit", "vorsorge")

#: Labels that mean a holding is a real asset rather than money. **A separate test from `_LOCKED`, because
#: it answers a separate question.** `_LOCKED` asks whether a holding is Vorsorge; this asks whether it can
#: be spent next month. Conflating the two credited a member holding CHF 2'000 in the bank and a CHF 45'000
#: collection with a 23.5-month emergency reserve, which scored the reserve component at its maximum.
#:
#: The list is short because the loader's vocabulary is: the only labels this build writes for a stock are
#: Bargeld und Kontoguthaben, Wertschriften, Säule 3a, Pensionskasse and Sammlungen, Kunst und Fahrzeuge.
#: Same weakness as `_LOCKED` and the same direction of error, asserted in the tests: an unrecognised label
#: counts as liquid, which OVERSTATES the reserve rather than understating it.
_ILLIQUID = ("sammlung", "kunst", "fahrzeug", "liegenschaft", "wohneigentum", "beteiligung")

#: Where a value came from. Carried on every figure so a reader can weigh it.
FROM_PLAN = "plan"
FROM_SUBMISSION = "submission"
ABSENT = "absent"


@dataclass(frozen=True)
class Inputs:
    """The five capacity inputs, each with its provenance."""

    horizon_years: float | None = None
    reserve_months: float | None = None
    employment: str | None = None
    variable_share: float | None = None
    mandates: int | None = None
    free_share: float | None = None
    debt_service_share: float | None = None
    sources: dict = field(default_factory=dict)

    def as_kwargs(self) -> dict:
        """Exactly the keyword arguments `risk_profile.capacity` takes."""
        return {
            "horizon_years": self.horizon_years, "reserve_months": self.reserve_months,
            "employment": self.employment, "variable_share": self.variable_share,
            "mandates": self.mandates, "free_share": self.free_share,
            "debt_service_share": self.debt_service_share,
        }


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(str(value).replace("'", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _latest_answers(session: Session, member_id: str) -> dict:
    """The most recent submission's answers, or an empty dict.

    Newest wins where a member has handed over more than one file: a later form is a later statement,
    and reconciling two of them is a judgement nothing here is entitled to make.
    """
    rows = submission_service.for_member(session, member_id=member_id)
    return submission_service.answers(rows[0]) if rows else {}


def collect(session: Session, *, member_id: str, today: date | None = None) -> Inputs:
    """Everything `capacity` needs, from the plan where the plan holds it."""
    today = today or date.today()
    answers = _latest_answers(session, member_id)
    sources: dict = {}

    def note(name, value, source):
        sources[name] = source if value is not None else ABSENT
        return value

    # -- horizon: the nearest dated goal. The one that binds first is the one capacity is about.
    years = None
    dated = [g.target_date for g in session.execute(
        select(Goal).where(Goal.member_id == member_id, Goal.target_date.is_not(None))
    ).scalars() if g.target_date]
    if dated:
        # 365 and not 365.25: C-02's structural guard refuses a float literal in this layer, and
        # nothing here needs the quarter day. The capacity band it feeds runs from three years to
        # twenty, where leap years move the answer by less than a hundredth of a component.
        years = max(0, (min(dated) - today).days / 365)
    horizon = note("horizon_years", years, FROM_PLAN)
    if horizon is None:
        horizon = note("horizon_years", _number(answers.get("plan_until_age")), FROM_SUBMISSION)

    # -- the positions, split three ways. **Three and not two**: money, Vorsorge, and things that are
    # neither. A car is not locked away, but it is not a reserve either, and counting it as one is what
    # gave a member with CHF 2'000 in the bank a 23.5-month cushion.
    free = locked = illiquid = 0
    income = 0
    for position in session.execute(
        select(Position).where(Position.member_id == member_id, Position.active.is_(True),
                               Position.magnitude.is_not(None))
    ).scalars():
        label = (position.label or "").lower()
        if position.magnitude_unit == FLOW_UNIT and position.role == "income":
            income += position.magnitude
        elif position.magnitude_unit in STOCK_UNITS:
            if any(word in label for word in _LOCKED):
                locked += position.magnitude
            elif any(word in label for word in _ILLIQUID):
                illiquid += position.magnitude
            else:
                free += position.magnitude

    # The illiquid share sits in the denominator and not the numerator: it is the member's wealth, so it
    # belongs in the total, and it is not available to invest, so it does not belong in the free part.
    total = free + locked + illiquid
    free_share = note("free_share", (free / total) if total else None, FROM_PLAN)

    # -- reserve months. The plan holds no expenditure, so this is the submission's or nothing.
    reserve = _number(answers.get("liquidity_reserve_months"))
    if reserve is None:
        spend = _number(answers.get("spend_now"))
        if spend and spend > 0 and free:
            # Derived rather than stated: LIQUID wealth over one month of spending. `free` excludes both
            # Vorsorge and real assets, which is the whole point of splitting the positions three ways.
            # Marked as coming from the submission because the spending figure did.
            reserve = free / (spend / 12)
    reserve_months = note("reserve_months", reserve, FROM_SUBMISSION)

    employment = note("employment", (answers.get("employment") or None), FROM_SUBMISSION)

    variable = _number(answers.get("income_variable"))
    gross = _number(answers.get("income_gross")) or (income or None)
    variable_share = note(
        "variable_share",
        (variable / gross) if (variable is not None and gross) else None,
        FROM_SUBMISSION)

    mandates = _number(answers.get("mandates"))
    mandates = note("mandates", int(mandates) if mandates is not None else None, FROM_SUBMISSION)

    # -- debt service. Interest plus amortisation over gross income, from whichever shape the file uses.
    service = None
    properties = answers.get("properties")
    if isinstance(properties, list):
        total_service = 0
        seen = False
        for entry in properties:
            if not isinstance(entry, dict):
                continue
            mortgage, rate = _number(entry.get("mortgage")), _number(entry.get("rate"))
            amort = _number(entry.get("amortisation")) or 0
            if mortgage:
                seen = True
                total_service += mortgage * ((rate or 0) / 100) + amort
        service = total_service if seen else None
    if service is None:
        mortgage, rate = _number(answers.get("mortgage")), _number(answers.get("mortgage_rate"))
        amort = _number(answers.get("amortisation")) or 0
        if mortgage:
            service = mortgage * ((rate or 0) / 100) + amort
    debt_service = note("debt_service_share",
                        (service / gross) if (service is not None and gross) else None,
                        FROM_SUBMISSION)

    return Inputs(horizon_years=horizon, reserve_months=reserve_months, employment=employment,
                  variable_share=variable_share, mandates=mandates, free_share=free_share,
                  debt_service_share=debt_service, sources=sources)


def stated_risk(session: Session, *, member_id: str) -> dict:
    """The two answers the member gave about risk, and the two about sustainability.

    Read from the submission because the plan has no field for any of them — which is the same gap that
    left `esg_min` at zero on every mandate ever derived in this build.
    """
    answers = _latest_answers(session, member_id)
    exclusions = answers.get("esg_exclusions")
    if isinstance(exclusions, str):
        exclusions = [part.strip() for part in exclusions.split(",") if part.strip()]
    loss = _number(answers.get("max_loss_pct"))
    expected = _number(answers.get("expected_return_pct"))
    return {
        # The form writes «30 %»; a bare 30 means the same thing and 0.30 does too.
        "stated_loss": (loss / 100 if loss is not None and loss > 1 else loss),
        "stated_return": (expected / 100 if expected is not None and expected > 1 else expected),
        "crisis_behaviour": (answers.get("crisis_behaviour") or "").strip() or None,
        "esg_exclusions": exclusions or [],
        "esg_level": (answers.get("esg_minimum") or "").strip() or None,
    }


__all__ = ["ABSENT", "FROM_PLAN", "FROM_SUBMISSION", "Inputs", "collect", "stated_risk"]
