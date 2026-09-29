"""The life balance sheet, computed. Pure: no I/O, no clock, no randomness.

Every function here is a port of an eigentliCH prototype service (``Projects/eigentliCH/Prototype/backend/
eigentlich/services/``), named after it, reading the same content records from the calibration instead of
from files. The prototype's figures are the golden reference (``golden/``); where this port departs from the
prototype on purpose, the decision id is named at the spot (DECISIONS.md, LBS-xx).

The rules the prototype kept, kept here:

* **Nothing computes from an unapproved record.** A record is approved when ``_about.provisional`` is false
  and ``_about.published_by`` is set. An unapproved record yields a ``NotAvailable`` section with the reason,
  never a number (``ahv.scale``, ``risk_profile.parameters``, ``property.conventions``).
* **Absent is absent.** A missing input is a gap, never a zero; a capital that cannot be derived is dropped,
  not scored zero (A110); assets and liabilities are never netted into one input.
* **Three verdicts, never two**: meets, does not meet, could not be determined.

``build(request, calibration)`` is the only entry point the service calls.
"""

from __future__ import annotations

import math
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .contracts import (
    CAPITAL_TYPES,
    FLOW_UNIT,
    ROLES,
    STOCK_UNITS,
    AhvPension,
    BvgProjection,
    Calibration,
    Capital,
    CoupleCap,
    CuratorItem,
    Currency,
    Gap,
    GoalObservations,
    GridCell,
    HouseholdPerson,
    HouseholdSection,
    LifeBalanceSheetRequest,
    LiquidityFinding,
    MandateProposal,
    NotAvailable,
    Person,
    PersonHumanCapital,
    PersonPensions,
    Position,
    PropertyFinding,
    ProposedBound,
    RecordUse,
    RetirementFinding,
    RiskProfile,
    TimeBudget,
    Totals,
)

MEETS = "meets"
DOES_NOT_MEET = "does_not_meet"
COULD_NOT_BE_DETERMINED = "could_not_be_determined"

#: human_capital.py provenance vocabulary.
FROM_SUBMISSION = "submission"
ABSENT = "absent"
NOT_ASKED = "the intake does not ask a question this could be derived from"
NOT_ANSWERED = "the question was asked and left blank"
WITHHELD = "K3 data was filtered or erased"

#: The prototype's key for the first role in its content records (roles.json keeps ``growth``).
_RECORD_ROLE_KEY = {"gain": "growth"}


class EngineError(ValueError):
    """The engine met an internally inconsistent state. Data problems are gaps, never this."""


class NotApproved(Exception):
    """A record has no owner's name on it. Caught at the section boundary and reported, never shown."""

    def __init__(self, record: str):
        super().__init__(record)
        self.record = record


# ===========================================================================
# Records and approval
# ===========================================================================

def approved(record: dict[str, Any]) -> bool:
    """The prototype's gate: not provisional, and a publisher named."""
    about = record.get("_about") or {}
    return (not about.get("provisional", True)) and bool(about.get("published_by"))


@dataclass
class Ctx:
    """What a build accumulates: the request, the calibration, the gaps and the records read."""

    req: LifeBalanceSheetRequest
    cal: Calibration
    gaps: list[Gap] = field(default_factory=list)
    used: dict[str, bool] = field(default_factory=dict)

    def record(self, name: str, *, gated: bool = True) -> dict[str, Any]:
        """Read a record. ``gated`` raises ``NotApproved`` for an unapproved one, as the prototype does."""
        rec = self.cal.records[name]
        self.used[name] = self.used.get(name, False) or not gated
        if gated and not approved(rec):
            raise NotApproved(name)
        return rec

    def corrects(self, quirk: str) -> bool:
        """Whether this calibration corrects one of the prototype quirks of LBS-17 (LBS-24). A calibration
        without a corrections block reproduces the prototype."""
        c = self.cal.corrections
        return c is not None and bool(getattr(c, quirk))

    def gap(self, section: str, input_: str, kind: str, reason: str) -> None:
        g = Gap(section=section, input=input_, kind=kind, reason=reason)
        if g not in self.gaps:
            self.gaps.append(g)

    def uses(self) -> tuple[RecordUse, ...]:
        out = []
        for name in sorted(self.used):
            about = self.cal.records[name].get("_about") or {}
            out.append(RecordUse(record=name, approved=approved(self.cal.records[name]),
                                 published_by=about.get("published_by"), decided_on=about.get("decided_on"),
                                 effective_from=about.get("effective_from"),
                                 read_without_gate=self.used[name]))
        return tuple(out)


def not_approved(record: str) -> NotAvailable:
    return NotAvailable(reason=f"not available: record not approved ({record} carries no publisher, or is "
                               "marked provisional; the prototype refuses to compute from it)", record=record)


# ===========================================================================
# Small helpers, each the prototype's
# ===========================================================================

def number(value: Any) -> Optional[float]:
    """``human_capital._number``: a bare number from a number or a string with ' and %; else None."""
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(str(value).replace("'", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def number_or_zero(value: Any) -> float:
    """``identities._number_or_zero``: JavaScript's ``Number(value) || 0``."""
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if not math.isnan(float(value)) else 0.0
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        parsed = float(text)
    except ValueError:
        return 0.0
    return 0.0 if math.isnan(parsed) else parsed


def js_round(value: float) -> int:
    """``Math.round``: half toward positive infinity."""
    return math.floor(value + 0.5)


def round2(value: float) -> float:
    return js_round(value * 100) / 100


def add_months(start: date, months: int) -> date:
    """``currency._add_months``: calendar arithmetic, day-clamped."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def _active(positions: tuple[Position, ...]) -> list[Position]:
    return [p for p in positions if p.active]


def _is_stock(p: Position) -> bool:
    return p.unit in STOCK_UNITS and p.magnitude is not None


# ===========================================================================
# Household (services/household.py, services/currency.py)
# ===========================================================================

def household_section(ctx: Ctx) -> HouseholdSection:
    h = ctx.req.household
    if h is None:
        ctx.gap("household", "household", "not_in_the_request",
                "no household composition has been stated. It is asked first and nothing derives it: the AHV "
                "path, the household income and goal ownership hang on it, so a default would be an invented "
                "fact rather than a missing one (household.py)")
        return HouseholdSection(stated=False, composition_as_of=None, adults=(), dependants=(), married=None,
                                currency=None)
    scales = ctx.record("intake-scales", gated=False)
    married: Optional[bool] = None
    status = ctx.req.facts.civil_status
    if status is not None:
        married = status in tuple(scales["civil_status"]["married"])
    else:
        ctx.gap("household", "civil_status", "not_in_the_request",
                "the civil status decides whether the AHV couple cap applies; it is not stated")
    horizons = ctx.record("currency-horizons")["horizons"]
    spec = horizons["household_composition"]
    months = int(spec["months"])
    expires = add_months(h.composition_as_of, months)
    expired = ctx.req.as_of > expires
    load_bearing = bool(spec.get("load_bearing", True))
    determination = COULD_NOT_BE_DETERMINED if (expired and load_bearing) else "stands"
    if determination == COULD_NOT_BE_DETERMINED:
        ctx.gap("household", "composition_as_of", "past_its_validity_horizon",
                f"the composition was stated on {h.composition_as_of.isoformat()} and its {months}-month horizon "
                f"ran out on {expires.isoformat()}; findings resting on it could not be determined")
    currency = Currency(input_class="household_composition", stated_on=h.composition_as_of,
                        age_days=(ctx.req.as_of - h.composition_as_of).days, horizon_months=months,
                        expires_on=expires, expired=expired, load_bearing=load_bearing,
                        determination=determination)

    def person(p: Person) -> HouseholdPerson:
        return HouseholdPerson(person_id=p.person_id, kind=p.kind, age=p.age)

    return HouseholdSection(
        stated=True, composition_as_of=h.composition_as_of,
        adults=tuple(person(p) for p in h.persons if p.kind == "adult"),
        dependants=tuple(person(p) for p in h.persons if p.kind == "dependant"),
        married=married, currency=currency)


def _composition_degrades(ctx: Ctx) -> bool:
    h = ctx.req.household
    if h is None:
        return False
    spec = ctx.cal.records["currency-horizons"]["horizons"]["household_composition"]
    return ctx.req.as_of > add_months(h.composition_as_of, int(spec["months"])) and bool(
        spec.get("load_bearing", True))


def adults(ctx: Ctx) -> list[Person]:
    h = ctx.req.household
    return [p for p in h.persons if p.kind == "adult"] if h else []


# ===========================================================================
# The grid and the totals (services/grid.py, services/engine_inputs.stated_stocks)
# ===========================================================================

def grid(ctx: Ctx) -> tuple[GridCell, ...]:
    roles = {r["key"]: r for r in ctx.record("roles", gated=False)["roles"]}
    cells = []
    for role in ROLES:
        rec = roles[_RECORD_ROLE_KEY.get(role, role)]
        for capital_type in CAPITAL_TYPES:
            members = [p for p in ctx.req.positions if p.role == role and p.capital_type == capital_type]
            live = _active(tuple(members))

            def total(unit: str, kind: Optional[str] = None) -> Optional[float]:
                values = [p.magnitude for p in live if p.unit == unit and p.magnitude is not None
                          and (kind is None or p.stock_kind == kind)]
                return float(sum(values)) if values else None

            definition = (rec.get("definition") or {}).get(capital_type) or {}
            cells.append(GridCell(
                role=role, capital_type=capital_type, display=rec["display"][capital_type]["en"],
                definition=definition.get("en") or None, positions=tuple(p.position_id for p in members),
                assets_chf=total("chf", "asset"), liabilities_chf=total("chf", "liability"),
                flows_chf_per_year=total(FLOW_UNIT), shares_of_total=total("share_of_total")))
    return tuple(cells)


def household_income(ctx: Ctx) -> tuple[Optional[float], str]:
    """``goals._household_income``: gross yearly household income from active income positions.

    The prototype returned ``None`` for any household of more than one adult, because it could not see a
    partner's positions. lbs can: with more than one adult the income is the sum when every adult owns at
    least one income position, and ``None`` otherwise (LBS-14).
    """
    income = [p for p in _active(ctx.req.positions)
              if p.role == "income" and p.magnitude is not None and p.unit == FLOW_UNIT]
    total = float(sum(p.magnitude for p in income)) if income else 0.0
    # The prototype read a zero as no income (``if not total``); corrected, a stated zero is zero and only no
    # income position at all is unknown (LBS-24).
    stated_zero = ctx.corrects("zero_income_is_a_stated_zero") and bool(income)
    grown = adults(ctx)
    if len(grown) > 1:
        owners = {p.owner for p in income}
        uncovered = [a.person_id for a in grown if a.person_id not in owners]
        if uncovered:
            ctx.gap("totals", "household_income", "not_in_the_request",
                    f"the household has {len(grown)} adults and {', '.join(uncovered)} own no income position, so "
                    "the household's income is not known; one earner's figure would answer the affordability "
                    "test for a household that does not exist")
            return None, "not_known_for_every_adult"
        return (total if stated_zero else (total or None)), "income_positions_of_every_adult"
    if not total and not stated_zero:
        ctx.gap("totals", "household_income", "not_in_the_request",
                "no active income position in chf_per_year is stated")
        return None, "no_income_position"
    return total, "income_positions"


def totals(ctx: Ctx) -> Totals:
    live = [p for p in _active(ctx.req.positions) if _is_stock(p)]
    fin = [p.magnitude for p in live if p.stock_kind == "asset" and p.capital_type == "financial"]
    hum = [p.magnitude for p in live if p.stock_kind == "asset" and p.capital_type == "human"]
    owed = [p.magnitude for p in live if p.stock_kind == "liability"]
    financial = float(sum(fin)) if fin else None
    human = float(sum(hum)) if hum else None
    if owed:
        liabilities: Optional[float] = float(sum(owed))
    elif ctx.req.facts.has_no_liabilities:
        liabilities = 0.0
    else:
        liabilities = None
        ctx.gap("totals", "liabilities", "not_in_the_request",
                "no liability is stated, which is not a statement that there is no debt; net worth is left open "
                "until a liability is stated or facts.has_no_liabilities is set")
    if financial is None and human is None:
        ctx.gap("totals", "assets", "not_in_the_request", "no asset is stated as a stock in chf")
    total_assets = None if (financial is None and human is None) else (financial or 0.0) + (human or 0.0)
    net = None if (total_assets is None or liabilities is None) else total_assets - liabilities
    identity = None if net is None else abs(total_assets - liabilities - net) <= 1e-9 * max(1.0, abs(net))

    by_vessel: dict[str, Optional[float]] = {}
    financial_assets = [p for p in live if p.stock_kind == "asset" and p.capital_type == "financial"]
    for vessel in ("free", "pillar_2", "pillar_3a", "real_asset", None):
        values = [p.magnitude for p in financial_assets if p.vessel == vessel]
        by_vessel[vessel or "not_stated"] = float(sum(values)) if values else None
    unstated = [p.position_id for p in financial_assets if p.vessel is None]
    if unstated:
        ctx.gap("totals", "vessel", "not_in_the_request",
                f"positions {', '.join(unstated)} do not say whether they are free, pillar 2, pillar 3a or a real "
                "asset, so they are left out of drawable wealth")
    drawable = by_vessel["free"]
    if drawable is None:
        ctx.gap("totals", "drawable", "not_in_the_request",
                "no financial asset is stated with vessel 'free', so no drawable wealth is known")
    income, basis = household_income(ctx)
    return Totals(financial_assets=financial, human_assets=human, total_assets=total_assets,
                  liabilities=liabilities, net_worth=net, identity_holds=identity, by_vessel=by_vessel,
                  drawable=drawable, household_income=income, household_income_basis=basis)


# ===========================================================================
# Human capital (services/human_capital.py, services/identities.net_scale)
# ===========================================================================

def net_scale(people: Any, mandates: Any, scales: dict[str, Any]) -> Optional[float]:
    if people is None and mandates is None:
        return None
    published = scales["network"]
    base = 1 - math.exp(-number_or_zero(people) / published["people_scale"])
    seats = min(published["mandate_ceiling"], published["per_mandate"] * number_or_zero(mandates))
    return round2(min(published["ceiling"], base + seats))


def expertise(answers: dict[str, Any], record: dict[str, Any], today_year: int) -> Capital:
    anchors = record["expertise"]["anchors"]
    level = (answers.get("qualification_highest") or "").strip() or None
    if level is None:
        return Capital(key="E", value=None, source=ABSENT, absent_because=NOT_ASKED,
                       note=("Education was given as free text, which a reader can judge and a mapping cannot. "
                             "`expertise.intake_question` in the record is the structured question that closes it."))
    by_level = anchors["by_qualification"]
    if level not in by_level:
        return Capital(key="E", value=None, source=ABSENT, absent_because=NOT_ANSWERED,
                       inputs={"qualification_highest": level},
                       note=(f"{level!r} has no published median in the BFS table, so it is not a rung. "
                             f"Placing it on a neighbouring one would be the guessing the source removed."))
    base = float(by_level[level])
    inputs: dict[str, Any] = {"qualification_highest": level, "base": base}
    recency = anchors["recency"]
    penalty = 0.0
    ongoing = (answers.get("education_recent") or "").strip().lower()
    has_ongoing = bool(ongoing) and ongoing not in ("nein", "no", "keine", "none", "-")
    year = number(answers.get("qualification_year"))
    if has_ongoing:
        inputs["recency_cleared_by"] = answers.get("education_recent")
    elif year is not None:
        elapsed = max(0, today_year - year)
        over = max(0, elapsed - float(recency["full_value_within_years"]))
        penalty = min(float(recency["maximum_penalty"]), over * float(recency["penalty_per_year_after"]))
        inputs["years_since_qualification"] = elapsed
        inputs["recency_penalty"] = penalty
    experience = anchors["experience"]
    addition = 0.0
    years = number(answers.get("years_in_field"))
    if years is not None:
        scale = float(experience["scale_years"])
        addition = float(experience["maximum_addition"]) * (1 - math.exp(-max(0, years) / scale))
        inputs["years_in_field"] = years
        inputs["experience_addition"] = addition
    value = min(float(anchors["ceiling"]), max(float(anchors["floor"]), base - penalty + addition))
    return Capital(key="E", value=value, source=FROM_SUBMISSION, inputs=inputs)


def network(answers: dict[str, Any], record: dict[str, Any], scales: dict[str, Any]) -> Capital:
    section = record["network"]
    people = number(answers.get("network_people"))
    mandates = number(answers.get("mandates"))
    if people is None and mandates is None:
        return Capital(key="N", value=None, source=ABSENT, absent_because=NOT_ANSWERED,
                       note="Neither the number of people nor the number of mandates was given.")
    reach_section = section.get("reach") or {}
    multipliers = reach_section.get("multipliers") or {}
    stated_reach = (answers.get("network_reach") or "").strip() or None
    reach = float(multipliers.get(stated_reach, reach_section.get("default_when_unanswered", 1)))
    effective = (people or 0) * reach
    value = net_scale(effective, mandates, scales)
    inputs = {"network_people": people, "mandates": mandates, "network_reach": stated_reach,
              "reach_multiplier": reach, "effective_people": effective,
              "computed_by": "services/identities.net_scale"}
    notes = []
    if people is None:
        notes.append("Only mandates were given, so this rests entirely on the published mandate credit "
                     "of 0.06 each.")
    if stated_reach is None:
        notes.append("Reach was not stated, so the count is read at face value — which under-reads a "
                     "senior specialist who names few but far-reaching contacts.")
    elif stated_reach not in multipliers:
        notes.append(f"{stated_reach!r} is not a published reach, so the count is read at face value.")
    return Capital(key="N", value=value, source=FROM_SUBMISSION, inputs=inputs, note=" ".join(notes) or None)


def health(answers: dict[str, Any], record: dict[str, Any], k3_permitted: bool) -> Capital:
    levels = record["health"]["levels"]
    if not k3_permitted:
        return Capital(key="H", value=None, source=ABSENT, absent_because=WITHHELD,
                       note=("`health` is K3. Without it the income equation loses its efficiency multiplier and "
                             "reports earning power at full health, which OVERSTATES income rather than "
                             "understating it."))
    stated = answers.get("health")
    if stated is None or str(stated).strip() == "":
        return Capital(key="H", value=None, source=ABSENT, absent_because=NOT_ANSWERED)
    key = str(stated).strip()
    if key in levels:
        return Capital(key="H", value=float(levels[key]), source=FROM_SUBMISSION, inputs={"health": key})
    value = number(stated)
    if value is not None and 0 <= value <= 1:
        return Capital(key="H", value=value, source=FROM_SUBMISSION, inputs={"health": key},
                       note="Read as a bare number; not a published option.")
    return Capital(key="H", value=None, source=ABSENT, absent_because=NOT_ANSWERED, inputs={"health": key},
                   note=f"{key!r} is not a published level.")


def capitals(answers: dict[str, Any], record: dict[str, Any], scales: dict[str, Any], today_year: int,
             k3_permitted: bool) -> tuple[Capital, Capital, Capital, tuple[str, ...]]:
    E = expertise(answers, record, today_year)
    N = network(answers, record, scales)
    H = health(answers, record, k3_permitted)
    caveats = []
    if E.value is None:
        caveats.append("expertise is unknown, so earning power rests on the network alone")
    if N.value is None:
        caveats.append("the network is unknown")
    if H.value is None and H.absent_because == WITHHELD:
        caveats.append("health was withheld as K3 data; earning power is reported at full health "
                       "and is therefore overstated")
    elif H.value is None:
        caveats.append("health is unknown; earning power is reported at full health and is overstated")
    return E, N, H, tuple(caveats)


def _band_hours(value: Any, record: dict[str, Any]) -> Optional[float]:
    bands = record["rest_hours_bands"]
    key = str(value or "").strip()
    if key in bands and not key.startswith("_") and isinstance(bands[key], (int, float)):
        return float(bands[key])
    return number(value)


def time_budget(answers: dict[str, Any], record: dict[str, Any]) -> TimeBudget:
    section = record["time"]
    week = float(section["productive_week_hours"])
    sources: dict[str, str] = {}
    caveats: list[str] = []
    hours = number(answers.get("hours_per_week"))
    tau_Y = (hours / week) if hours is not None else None
    sources["tau_Y"] = FROM_SUBMISSION if tau_Y is not None else ABSENT
    rest = _band_hours(answers.get("rest_hours"), record)
    tau_H = (rest / week) if rest is not None else None
    sources["tau_H"] = FROM_SUBMISSION if tau_H is not None else ABSENT
    if rest is not None and not number(answers.get("rest_hours")):
        caveats.append(f"recovery was given as the band {answers.get('rest_hours')!r} and read at "
                       f"{rest:g} hours by the record's convention, not measured")
    learning = number(answers.get("hours_learning"))
    tau_E = (learning / week) if learning is not None else None
    sources["tau_E"] = FROM_SUBMISSION if tau_E is not None else ABSENT
    networking = number(answers.get("hours_network"))
    tau_N = (networking / week) if networking is not None else None
    sources["tau_N"] = FROM_SUBMISSION if tau_N is not None else ABSENT
    unasked = [name for name, value in (("Lernen", tau_E), ("Netzwerk", tau_N)) if value is None]
    if unasked:
        caveats.append(f"no hours were stated for {' and '.join(unasked)}, so the leisure residual "
                       f"cannot be computed")
    bounds = section["bounds"]
    if tau_Y is not None and tau_Y > float(bounds["max_tau_Y"]):
        caveats.append(f"stated working hours are {hours:g} a week, above the model's hard ceiling of "
                       f"{float(bounds['max_tau_Y']) * week:g}")
    if tau_Y is not None and tau_Y > float(section["overwork_threshold"]):
        caveats.append(f"stated working hours are {hours:g} a week, above the "
                       f"{float(section['overwork_threshold']) * week:g}-hour "
                       f"threshold where the model accelerates health decay")
    if tau_H is not None and tau_H < float(bounds["min_tau_H"]):
        caveats.append(f"stated recovery is {rest:g} hours a week, below the model's floor of "
                       f"{float(bounds['min_tau_H']) * week:g}")
    total = sum(share for share in (tau_Y, tau_E, tau_N, tau_H) if share is not None)
    if total > 1:
        caveats.append(f"the stated hours add to {total * week:g} a week, which is more than the "
                       f"{week:g}-hour productive week the model allows")
    shares = (tau_Y, tau_E, tau_N, tau_H)
    leisure = None if any(s is None for s in shares) else 1 - sum(shares)  # type: ignore[arg-type]
    return TimeBudget(productive_week_hours=week, tau_Y=tau_Y, tau_E=tau_E, tau_N=tau_N, tau_H=tau_H,
                      leisure=leisure, sources=sources, caveats=tuple(caveats))


def answers_of(person: Person) -> dict[str, Any]:
    return person.human_capital.model_dump(exclude={"health_withheld"})


def human_capital(ctx: Ctx) -> tuple[PersonHumanCapital, ...]:
    # The prototype's human_capital.capitals reads the record without calling its own gate (LBS-08); the
    # record is approved at seeding in any case.
    record = ctx.record("human-capital", gated=False)
    scales = ctx.record("intake-scales", gated=False)
    out = []
    for person in adults(ctx):
        answers = answers_of(person)
        E, N, H, caveats = capitals(answers, record, scales, ctx.req.as_of.year,
                                    not person.human_capital.health_withheld)
        for cap in (E, N, H):
            if cap.value is None:
                ctx.gap("human_capital", f"{person.person_id}.{cap.key}", "not_in_the_request",
                        f"{cap.key} is absent: {cap.absent_because}")
        out.append(PersonHumanCapital(
            person_id=person.person_id, E=E, N=N, H=H, caveats=caveats,
            time_budget=time_budget(answers, record),
            earning_power=NotAvailable(reason=(
                "not available in lbs: earning power is personal_alm's income equation (the stochastic "
                "model), which the owner assigned to lbsim; lbs reports E, N and H and the time budget only"))))
    if out:
        ctx.gap("human_capital", "earning_power", "owned_by_another_engine",
                "earning power is computed by the stochastic model personal_alm, assigned to lbsim (LBS-10)")
    return tuple(out)


# ===========================================================================
# The first pillar (services/ahv.py)
# ===========================================================================

@dataclass(frozen=True)
class AhvResult:
    mdje: float
    years: Optional[int]
    full_scale: int
    full_monthly: int
    factor: float
    monthly: float
    yearly: float
    at_minimum: bool
    at_maximum: bool
    caveats: list[str]


def ahv_full_monthly(record: dict[str, Any], mdje: float) -> int:
    monthly = record["monthly"]
    if mdje <= 0:
        return int(monthly["minimum"])
    for row in monthly["scale_44"]:
        if mdje <= row["up_to"]:
            return int(row["monthly"])
    return int(monthly["maximum"])


def ahv_pension(record: dict[str, Any], mdje: float, contribution_years: Optional[int]) -> AhvResult:
    monthly_record = record["monthly"]
    full = ahv_full_monthly(record, mdje)
    full_scale = int(record["partial"]["full_scale"])
    caveats = ["mdje_is_a_lifetime_average_and_was_supplied_not_derived"]
    factor: float = 1
    if contribution_years is None:
        caveats.append("the_contribution_record_was_not_stated_so_a_full_one_is_assumed")
    elif contribution_years < full_scale:
        factor = contribution_years / full_scale
        caveats.append("the_contribution_record_is_incomplete")
    monthly = full * factor
    return AhvResult(mdje=mdje, years=contribution_years, full_scale=full_scale, full_monthly=full,
                     factor=factor, monthly=monthly, yearly=monthly * int(monthly_record["payments_per_year"]),
                     at_minimum=full <= int(monthly_record["minimum"]),
                     at_maximum=full >= int(monthly_record["maximum"]), caveats=caveats)


def ahv_illustration(record: dict[str, Any], current_income: float,
                     contribution_years: Optional[int]) -> AhvResult:
    result = ahv_pension(record, current_income, contribution_years)
    result.caveats.insert(0, "current_income_was_used_where_a_lifetime_average_belongs")
    return result


def ahv_levers(record: dict[str, Any], result: AhvResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"dimension": "mdje", "stands_at": result.mdje, "gives_monthly": result.full_monthly,
                                  "at_minimum": result.at_minimum, "at_maximum": result.at_maximum}]
    if result.years is not None and result.years < result.full_scale:
        missing = result.full_scale - result.years
        out.append({"dimension": "contribution_years", "stands_at": result.years, "of": result.full_scale,
                    "missing": missing, "costs_monthly": result.full_monthly * missing / result.full_scale,
                    "may_be_paid_within_years": record["partial"]["gap_can_be_paid_within_years"]})
    for item in record["not_modelled"]["items"]:
        out.append({"dimension": "not_modelled", "note": item})
    return out


def ahv_couple(record: dict[str, Any], first: float, second: float) -> CoupleCap:
    monthly_record = record["monthly"]
    cap = int(monthly_record["couple_cap"])
    uncapped = first + second
    capped = min(uncapped, cap)
    return CoupleCap(uncapped_monthly=uncapped, cap=cap, monthly=capped,
                     yearly=capped * int(monthly_record["payments_per_year"]), cap_binds=uncapped > cap,
                     lost_to_the_cap_monthly=max(0, uncapped - cap))


# ===========================================================================
# The second pillar (services/pension_projection.py)
# ===========================================================================

@dataclass(frozen=True)
class BvgResult:
    from_age: int
    to_age: int
    opening_balance: float
    gross_salary: float
    coordinated: Optional[float]
    interest_rate: float
    years: list[dict[str, Any]]
    closing_balance: float
    total_credited: float
    total_interest: float
    conversion_rate: float
    monthly_pension: float
    caveats: list[str]


def bvg_credit_rate(record: dict[str, Any], age: int) -> float:
    credits = record["credits"]
    if age < int(credits["starts_at_age"]):
        return 0
    for band in credits["bands"]:
        if band["from_age"] <= age <= band["to_age"]:
            return float(band["rate"])
    return 0


def bvg_coordinated_salary(record: dict[str, Any], gross: float) -> Optional[float]:
    c = record["coordination"]
    if gross <= c["entry_threshold"]:
        return None
    coordinated = min(gross, c["upper_limit"]) - c["deduction"]
    if coordinated <= 0:
        return float(c["minimum_coordinated"])
    return float(max(coordinated, c["minimum_coordinated"]))


def bvg_project(record: dict[str, Any], *, current_age: int, opening_balance: float, gross_salary: float,
                to_age: Optional[int] = None) -> BvgResult:
    rate = float(record["interest"]["minimum_rate"])
    conversion = float(record["conversion"]["minimum_rate"])
    end = int(to_age if to_age is not None else record["conversion"]["at_reference_age"])
    coordinated = bvg_coordinated_salary(record, gross_salary)
    caveats = ["interest_is_a_statutory_minimum_not_a_return",
               "the_obligatory_portion_only_the_ueberobligatorium_is_not_visible_here",
               "the_salary_is_assumed_unchanged_to_the_reference_age"]
    if coordinated is None:
        caveats.append("the_salary_is_below_the_entry_threshold_so_nothing_is_credited")
    balance = float(opening_balance)
    years: list[dict[str, Any]] = []
    credited: float = 0
    interest_total: float = 0
    for age in range(int(current_age), end):
        band_rate = bvg_credit_rate(record, age)
        credit = (coordinated or 0) * band_rate
        interest = balance * rate
        balance = balance + credit + interest
        credited += credit
        interest_total += interest
        years.append({"age": age, "credit_rate": band_rate, "credit": credit, "interest": interest,
                      "closing": balance})
    return BvgResult(from_age=int(current_age), to_age=end, opening_balance=float(opening_balance),
                     gross_salary=float(gross_salary), coordinated=coordinated, interest_rate=rate, years=years,
                     closing_balance=balance, total_credited=credited, total_interest=interest_total,
                     conversion_rate=conversion, monthly_pension=balance * conversion / 12, caveats=caveats)


def bvg_levers(record: dict[str, Any], result: BvgResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"dimension": "coordinated_salary", "stands_at": result.coordinated, "gross": result.gross_salary,
         "deduction": record["coordination"]["deduction"]},
        {"dimension": "years_remaining", "stands_at": result.to_age - result.from_age},
        {"dimension": "opening_balance", "stands_at": result.opening_balance, "grows_to": result.closing_balance,
         "of_which_interest": result.total_interest, "of_which_credits": result.total_credited},
    ]
    for item in record["not_modelled"]["items"]:
        out.append({"dimension": "not_modelled", "note": item})
    return out


def person_income(ctx: Ctx, person: Person) -> Optional[float]:
    """``computations._gross_income``: the person's income positions, else their stated gross income.

    Reproduction (no corrections): zero counts as unknown, as in the prototype (``if not income``).
    Corrected (LBS-24): a stated zero is zero, from an income position or from ``stated_gross_income``; only a
    person with neither is unknown."""
    owned = [p.magnitude for p in _active(ctx.req.positions)
             if p.owner == person.person_id and p.role == "income" and p.unit == FLOW_UNIT
             and p.magnitude is not None]
    total = sum(owned)
    if ctx.corrects("zero_income_is_a_stated_zero"):
        if owned:
            return float(total)
        return None if person.stated_gross_income is None else float(person.stated_gross_income)
    if total:
        return float(total)
    return person.stated_gross_income or None


def person_pillar2(ctx: Ctx, person: Person) -> Optional[float]:
    values = [p.magnitude for p in _active(ctx.req.positions) if p.owner == person.person_id and _is_stock(p)
              and p.stock_kind == "asset" and p.vessel == "pillar_2"]
    return float(sum(values)) if values else None


def pensions(ctx: Ctx) -> tuple[tuple[PersonPensions, ...], CoupleCap | NotAvailable]:
    out = []
    monthly: list[float] = []
    ahv_record_ok = approved(ctx.cal.records["ahv-pension"])
    for person in adults(ctx):
        section = f"pensions.{person.person_id}"
        income = person_income(ctx, person)
        # -- AHV
        ahv: AhvPension | NotAvailable
        try:
            record = ctx.record("ahv-pension")
        except NotApproved as exc:
            ahv = not_approved(exc.record)
            ctx.gap(section, "ahv", "record_not_approved",
                    "ahv-pension is not approved (provisional, no publisher): no AHV figure is shown")
        else:
            missing = person.ahv.contribution_years_missing
            full_scale = int(record["partial"]["full_scale"])
            years = None if missing is None else max(0, full_scale - missing)
            if person.ahv.mdje is not None:
                res = ahv_pension(record, person.ahv.mdje, years)
                basis = "mdje_stated"
            elif income is not None:
                res = ahv_illustration(record, income, years)
                basis = "current_income_as_a_stand_in_for_the_lifetime_average"
            else:
                res = None
            if res is None:
                ahv = NotAvailable(reason="not available: neither an mdje nor an income is stated")
                ctx.gap(section, "mdje", "not_in_the_request", "neither an mdje nor a gross income is stated")
            else:
                ahv = AhvPension(basis=basis, mdje=res.mdje, years=res.years, full_scale=res.full_scale,
                                 full_monthly=res.full_monthly, factor=res.factor, monthly=res.monthly,
                                 yearly=res.yearly, at_minimum=res.at_minimum, at_maximum=res.at_maximum,
                                 caveats=tuple(res.caveats), levers=tuple(ahv_levers(record, res)))
                monthly.append(res.monthly)
        # -- BVG (computations._retirement_provision, per person)
        bvg: BvgProjection | NotAvailable
        try:
            record = ctx.record("bvg-projection")
        except NotApproved as exc:
            bvg = not_approved(exc.record)
            ctx.gap(section, "bvg", "record_not_approved", "bvg-projection is not approved")
        else:
            if person.age is None:
                bvg = NotAvailable(reason="not available: the person's age is not stated")
                ctx.gap(section, "age", "not_in_the_request", "the BVG projection runs from the person's age")
            elif income is None:
                bvg = NotAvailable(reason="not available: no gross income is stated for the person")
                ctx.gap(section, "gross_income", "not_in_the_request",
                        "the BVG projection credits a share of the gross salary; none is stated")
            else:
                opening = person_pillar2(ctx, person)
                res2 = bvg_project(record, current_age=person.age, opening_balance=opening or 0,
                                   gross_salary=income)
                caveats = list(res2.caveats)
                if opening is None:
                    caveats.append("no_position_names_a_pension_fund_so_the_opening_balance_is_zero")
                    ctx.gap(section, "pillar_2_balance", "not_in_the_request",
                            "no pillar 2 position is stated for the person; the projection opens at zero and "
                            "says so")
                bvg = BvgProjection(
                    from_age=res2.from_age, to_age=res2.to_age, opening_balance=res2.opening_balance,
                    gross_salary=res2.gross_salary, coordinated=res2.coordinated, interest_rate=res2.interest_rate,
                    years=tuple(res2.years), closing_balance=res2.closing_balance,
                    total_credited=res2.total_credited, total_interest=res2.total_interest,
                    conversion_rate=res2.conversion_rate, monthly_pension=res2.monthly_pension,
                    yearly_pension=res2.monthly_pension * 12, caveats=tuple(caveats),
                    levers=tuple(bvg_levers(record, res2)))
        out.append(PersonPensions(person_id=person.person_id, ahv=ahv, bvg=bvg))

    couple: CoupleCap | NotAvailable
    married = None
    if ctx.req.household is not None and ctx.req.facts.civil_status is not None:
        married = ctx.req.facts.civil_status in tuple(
            ctx.cal.records["intake-scales"]["civil_status"]["married"])
    if not ahv_record_ok:
        couple = not_approved("ahv-pension")
    elif married is None:
        couple = NotAvailable(reason="not available: the civil status is not stated")
    elif not married or len(adults(ctx)) != 2:
        couple = NotAvailable(reason="not available: the cap applies to a married couple only")
    elif len(monthly) != 2:
        couple = NotAvailable(reason="not available: both pensions are needed")
    elif _composition_degrades(ctx):
        couple = NotAvailable(reason="not available: the household composition is past its validity horizon")
    else:
        couple = ahv_couple(ctx.cal.records["ahv-pension"], monthly[0], monthly[1])
    return tuple(out), couple


# ===========================================================================
# Property goals (services/property.py, goals.property_finding)
# ===========================================================================

def occupancies(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in record["occupancy"].items() if not k.startswith("_")}


@dataclass(frozen=True)
class MandateTarget:
    target: float
    price: float
    occupancy: str
    equity_min: float
    assumed: bool
    why: str


def mandate_target(record: dict[str, Any], price: float, occupancy: Optional[str]) -> MandateTarget:
    """``property.mandate_target``: the deposit, never the price. Unknown occupancy takes the strictest."""
    known = {k: r for k, r in record["occupancy"].items() if isinstance(r, dict)}
    if occupancy in known:
        rule = known[occupancy]
        share = float(rule["equity_min"])
        label = (rule.get("label") or {}).get("de", occupancy)
        return MandateTarget(target=float(price) * share, price=float(price), occupancy=occupancy,
                             equity_min=share, assumed=False,
                             why=f"Nutzung angegeben: {label}, {share:.0%} Eigenmittel.")
    strictest = max(known, key=lambda key: float(known[key]["equity_min"]))
    share = float(known[strictest]["equity_min"])
    label = (known[strictest].get("label") or {}).get("de", strictest)
    return MandateTarget(
        target=float(price) * share, price=float(price), occupancy=strictest, equity_min=share, assumed=True,
        why=(f"Die Nutzung ist nicht erfasst. Gerechnet wird mit der strengsten der drei Varianten "
             f"({label}, {share:.0%}), weil ein zu tiefes Ziel einem Haushalt sagt, es reiche, wenn es "
             f"nicht reicht."))


def property_assess(record: dict[str, Any], *, goal_id: str, price: Optional[float], target_date: Optional[date],
                    occupancy: Optional[str], hard_available: Optional[float], pillar2_available: float,
                    pillar3a_available: float, household_income: Optional[float],
                    unknown_vessel_available: float = 0, zero_income_is_stated: bool = False) -> dict[str, Any]:
    """``property.assess`` and ``Assessment.as_payload``, with ``levers``. Raises ``NotApproved`` where the
    prototype raises ``ConventionsNotApproved`` and ``KeyError`` for an undeclared occupancy.

    ``unknown_vessel_available`` (LBS-24, corrected only): funding that states no vessel. It is judged both
    ways: the equity meets if it meets without it, does not meet if it fails even counted as hard equity (the
    most favourable class), and could not be determined in between. ``zero_income_is_stated`` (LBS-24): a
    household income of zero supports a price of zero rather than none."""
    res: dict[str, Any] = {"goal_id": goal_id, "price": price, "target_date": target_date, "occupancy": occupancy,
                           "equity": None, "affordability": None, "equity_verdict": COULD_NOT_BE_DETERMINED,
                           "affordability_verdict": COULD_NOT_BE_DETERMINED, "binds_on": [],
                           "undetermined_because": [], "ineligible": []}
    if not price:
        res["undetermined_because"].append("the_goal_names_no_amount")
        return res
    if occupancy is None:
        res["undetermined_because"].append("the_goal_does_not_say_whether_the_member_will_live_in_it")
        return res
    rules = occupancies(record)
    if occupancy not in rules:
        raise KeyError(occupancy)
    rule = rules[occupancy]
    if not approved(record):
        raise NotApproved("property-funding")
    required = price * rule["equity_min"]
    hard_required = price * rule["hard_equity_min"]
    p2_may, p3a_may = bool(rule["pillar2_may_fund"]), bool(rule["pillar3a_may_fund"])
    pillar2_cap = max(0, required - hard_required) if rule["pillar2_may_fund"] else 0
    res["equity"] = {"required_chf": required, "hard_required_chf": hard_required, "pillar2_cap_chf": pillar2_cap,
                     "pillar2_may_fund": p2_may, "pillar3a_may_fund": p3a_may}
    if hard_available is None:
        res["undetermined_because"].append("no_position_is_linked_to_this_goal")
    else:
        def judge(hard_stock: float) -> str:
            hard = hard_stock + (pillar3a_available if rule["pillar3a_may_fund"] else 0)
            usable = min(pillar2_available, pillar2_cap) if p2_may else 0
            if hard < hard_required:
                return DOES_NOT_MEET
            return MEETS if hard + usable >= required else DOES_NOT_MEET

        without = judge(hard_available)
        if unknown_vessel_available and without != MEETS:
            if judge(hard_available + unknown_vessel_available) == DOES_NOT_MEET:
                res["equity_verdict"] = DOES_NOT_MEET
            else:
                res["undetermined_because"].append("a_funding_position_states_no_vessel")
        else:
            res["equity_verdict"] = without
    for label, amount, allowed in (("pillar_2", pillar2_available, rule["pillar2_may_fund"]),
                                   ("pillar_3a", pillar3a_available, rule["pillar3a_may_fund"])):
        if amount and not allowed:
            res["ineligible"].append({"kind": label, "amount_chf": amount,
                                      "reason": "vorsorge_capital_only_for_an_owner_occupied_primary_residence"})
    if not rule.get("affordability_is_determinable", True):
        res["undetermined_because"].append("rental_income_is_not_modelled_for_a_let_property")
    else:
        published = record["affordability"]
        ltv = 1 - rules["owner_occupied_primary"]["equity_min"]
        interest = ltv * published["imputed_rate"]
        above_first = max(0, ltv - published["first_mortgage_max"])
        amortisation = above_first / published["amortisation_years"]
        fraction = interest + published["maintenance_and_ancillary"] + amortisation
        annual = price * fraction
        share = published["max_share_of_gross_income"]
        income_required = annual / share
        if zero_income_is_stated:
            supported = None if household_income is None else household_income * share / fraction
        else:
            supported = (household_income * share / fraction) if household_income else None
        res["affordability"] = {"annual_cost_chf": annual, "income_required_chf": income_required,
                                "price_supported_chf": supported}
        if household_income is None:
            res["affordability_verdict"] = COULD_NOT_BE_DETERMINED
            res["undetermined_because"].append("no_income_is_recorded_for_the_household")
        else:
            res["affordability_verdict"] = MEETS if household_income >= income_required else DOES_NOT_MEET
    if res["equity_verdict"] == DOES_NOT_MEET:
        res["binds_on"].append("equity")
    if res["affordability_verdict"] == DOES_NOT_MEET:
        res["binds_on"].append("affordability")
    return res


def _property_verdict(res: dict[str, Any]) -> str:
    if res["undetermined_because"] or COULD_NOT_BE_DETERMINED in (res["equity_verdict"],
                                                                  res["affordability_verdict"]):
        return COULD_NOT_BE_DETERMINED
    return DOES_NOT_MEET if res["binds_on"] else MEETS


def property_levers(res: dict[str, Any], household_income: Optional[float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    aff = res["affordability"]
    if aff is not None and "affordability" in res["binds_on"] and aff["price_supported_chf"] is not None:
        out.append({"lever": "price", "supported_chf": aff["price_supported_chf"], "stated_chf": res["price"],
                    "difference_chf": res["price"] - aff["price_supported_chf"]})
        out.append({"lever": "household_income", "required_chf": aff["income_required_chf"],
                    "recorded_chf": household_income,
                    "difference_chf": (aff["income_required_chf"] - household_income
                                       if household_income is not None else None)})
    if res["equity"] is not None and "equity" in res["binds_on"]:
        out.append({"lever": "deposit", "required_chf": res["equity"]["required_chf"],
                    "hard_required_chf": res["equity"]["hard_required_chf"]})
    return out


def _funding(ctx: Ctx, goal_id: str) -> list[Position]:
    return [p for p in ctx.req.positions if goal_id in p.funds_goals]


def capital_by_eligibility(ctx: Ctx, goal_id: str) -> tuple[Optional[float], float, float, float]:
    """``goals._capital_by_eligibility``, reading the stated vessel instead of the label (LBS-06).

    No link is "nobody has said" (``None``), never zero. Liabilities are not funding and are skipped (LBS-15).
    A funding stock without a vessel is named as a gap either way. Reproduction: it counts as hard equity, the
    prototype's direction for an unrecognised label. Corrected (LBS-24): it is not counted as equity of any
    class; it is returned apart (the fourth figure) and the verdict is judged both ways. From 1.3.0 (LBS-28) a
    human-capital stock is human capital, never equity: it is left out, with a gap.
    """
    funding = _funding(ctx, goal_id)
    if not funding:
        return None, 0, 0, 0
    corrected = ctx.corrects("unstated_vessel_is_a_gap")
    human_is_human = ctx.corrects("human_capital_is_never_free_wealth")
    hard: float = 0
    pillar2: float = 0
    pillar3a: float = 0
    unknown: float = 0
    for p in funding:
        if p.magnitude is None or p.unit not in STOCK_UNITS or p.stock_kind == "liability":
            continue
        if p.capital_type == "human" and human_is_human:
            ctx.gap(f"property.{goal_id}", f"{p.position_id}.capital_type", "not_in_the_request",
                    "a human-capital position funds this goal; human capital is not drawable wealth and is not "
                    "counted as equity of any class (LBS-28)")
            continue
        if p.vessel == "pillar_3a":
            pillar3a += p.magnitude
        elif p.vessel == "pillar_2":
            pillar2 += p.magnitude
        else:
            if p.vessel is None and corrected:
                ctx.gap(f"property.{goal_id}", f"{p.position_id}.vessel", "not_in_the_request",
                        "a funding position states no vessel, so it is not counted as equity of any class: it "
                        "may be pension capital, which a let or second home may not use; the equity is judged "
                        "with and without it")
                unknown += p.magnitude
                continue
            if p.vessel is None:
                ctx.gap(f"property.{goal_id}", f"{p.position_id}.vessel", "not_in_the_request",
                        "a funding position states no vessel and is counted as hard equity, which overstates "
                        "the equity if it is pension capital")
            hard += p.magnitude
    return hard, pillar2, pillar3a, unknown


def property_findings(ctx: Ctx, income: Optional[float]) -> tuple[PropertyFinding, ...]:
    record = ctx.cal.records["property-funding"]
    out = []
    for goal in ctx.req.goals:
        if goal.kind != "property":
            continue
        ctx.used["property-funding"] = ctx.used.get("property-funding", False)
        options = tuple({"value": k, "label": r["label"], "why": r.get("why")}
                        for k, r in occupancies(record).items())
        hard, p2, p3a, unknown = capital_by_eligibility(ctx, goal.goal_id)
        base = dict(goal_id=goal.goal_id, price_chf=goal.target_amount, target_date=goal.target_date,
                    occupancy=goal.occupancy, occupancy_options=options)
        try:
            res = property_assess(record, goal_id=goal.goal_id, price=goal.target_amount,
                                  target_date=goal.target_date, occupancy=goal.occupancy, hard_available=hard,
                                  pillar2_available=p2, pillar3a_available=p3a, household_income=income,
                                  unknown_vessel_available=unknown,
                                  zero_income_is_stated=ctx.corrects("zero_income_is_a_stated_zero"))
        except NotApproved:
            ctx.gap(f"property.{goal.goal_id}", "property-funding", "record_not_approved",
                    "property-funding is not approved")
            out.append(PropertyFinding(**base, verdict=COULD_NOT_BE_DETERMINED, equity=None, affordability=None,
                                       binds_on=(), undetermined_because=("the_property_conventions_are_not_approved",),
                                       ineligible_funding=(), levers=()))
            continue
        except KeyError:
            ctx.gap(f"property.{goal.goal_id}", "occupancy", "not_in_the_request",
                    f"{goal.occupancy!r} is not an occupancy property-funding declares")
            out.append(PropertyFinding(**base, verdict=COULD_NOT_BE_DETERMINED, equity=None, affordability=None,
                                       binds_on=(),
                                       undetermined_because=("the_goal_names_an_occupancy_the_record_does_not_declare",),
                                       ineligible_funding=(), levers=()))
            continue
        if _composition_degrades(ctx) and res["affordability"] is not None:
            res["undetermined_because"].append("the_household_composition_is_past_its_validity_horizon")
        for reason in res["undetermined_because"]:
            ctx.gap(f"property.{goal.goal_id}", reason, "not_in_the_request",
                    f"the property finding could not be determined: {reason.replace('_', ' ')}")
        equity = None if res["equity"] is None else {**res["equity"], "verdict": res["equity_verdict"]}
        aff = None if res["affordability"] is None else {**res["affordability"],
                                                         "verdict": res["affordability_verdict"]}
        out.append(PropertyFinding(**base, verdict=_property_verdict(res), equity=equity, affordability=aff,
                                   binds_on=tuple(res["binds_on"]),
                                   undetermined_because=tuple(res["undetermined_because"]),
                                   ineligible_funding=tuple(res["ineligible"]),
                                   levers=tuple(property_levers(res, income))))
    return tuple(out)


# ===========================================================================
# The blocking liquidity finding (services/liquidity.py)
# ===========================================================================

def liquidity_findings(ctx: Ctx) -> tuple[LiquidityFinding, ...]:
    record = ctx.record("liquidity-levers")
    levers = sorted(record["levers"], key=lambda lever: lever["order"])
    today = ctx.req.as_of
    out = []
    for goal in ctx.req.goals:
        if goal.target_date is None:
            continue
        funding = [p for p in _funding(ctx, goal.goal_id) if p.active]
        stated = [p for p in funding if p.liquidity]
        if not stated or not all(p.liquidity == "illiquid" for p in stated):
            continue
        amounts = [p.magnitude for p in stated if p.magnitude is not None and p.unit in STOCK_UNITS]
        considered = []
        prepared: dict[str, Any] = {"lever": None, "considered": [], "requires_curator": True,
                                    "reason": "no_single_lever_closes_the_gap"}
        for lever in levers:
            key = lever["key"]
            if key in ("move_funding_to_a_liquid_form", "move_the_goal_date"):
                verdict = "does_not_close"
            elif key == "add_a_monthly_contribution":
                verdict = "closes" if goal.target_date > today else "does_not_close"
            elif key == "reduce_the_goal_size":
                verdict = "closes"
            else:
                verdict = COULD_NOT_BE_DETERMINED
            considered.append({"lever": key, "verdict": verdict})
            if verdict == COULD_NOT_BE_DETERMINED:
                prepared = {"lever": None, "considered": considered, "requires_curator": True,
                            "reason": "a_lever_could_not_be_determined"}
                break
            if verdict == "closes":
                prepared = {"lever": key, "considered": considered, "requires_curator": False, "reason": None}
                break
        else:
            prepared["considered"] = considered
        out.append(LiquidityFinding(goal_id=goal.goal_id, gap_chf=float(sum(amounts)) if amounts else None,
                                    due_date=goal.target_date, reason="funding_is_illiquid",
                                    position_ids=tuple(p.position_id for p in stated), prepared=prepared))
    return tuple(out)


def observations(ctx: Ctx) -> tuple[GoalObservations, ...]:
    """``goals.observations``: statements of fact, never a severity."""
    count: dict[str, int] = {}
    for p in ctx.req.positions:
        count[p.position_id] = len(p.funds_goals)
    out = []
    for goal in ctx.req.goals:
        found: list[dict[str, Any]] = []
        funding = [p for p in _funding(ctx, goal.goal_id) if p.active]
        if goal.target_date and not funding:
            found.append({"kind": "dated_but_unfunded", "target_date": goal.target_date.isoformat(),
                          "note": "no_position_names_this_goal"})
        stated = [p for p in funding if p.liquidity]
        if goal.target_date and stated and all(p.liquidity == "illiquid" for p in stated):
            found.append({"kind": "dated_but_funding_is_illiquid", "target_date": goal.target_date.isoformat(),
                          "position_ids": [p.position_id for p in stated]})
        unstated = [p for p in funding if not p.liquidity]
        if goal.target_date and unstated:
            found.append({"kind": "liquidity_not_stated", "position_ids": [p.position_id for p in unstated],
                          "note": "cannot_compare_without_it"})
        shared = [p for p in funding if count[p.position_id] > 1]
        if shared:
            found.append({"kind": "funding_shared_with_other_goals",
                          "position_ids": [p.position_id for p in shared]})
        out.append(GoalObservations(goal_id=goal.goal_id, observations=tuple(found)))
    return tuple(out)


# ===========================================================================
# Retirement goals (goals.retirement_finding)
# ===========================================================================

def _subject(ctx: Ctx, owners: tuple[str, ...]) -> Optional[Person]:
    """Whose age a retirement projection runs from: the goal's single owner; for a goal without an owner the
    household's stated principal (the prototype used the account holder's age), else its only adult (LBS-16)."""
    h = ctx.req.household
    if h is None:
        return None
    by_id = {p.person_id: p for p in h.persons}
    if len(owners) == 1:
        return by_id[owners[0]]
    if owners:
        return None
    if h.principal is not None:
        return by_id[h.principal]
    grown = adults(ctx)
    return grown[0] if len(grown) == 1 else None


def retirement_findings(ctx: Ctx, income: Optional[float]) -> tuple[RetirementFinding, ...]:
    out = []
    for goal in ctx.req.goals:
        if goal.kind != "retirement":
            continue
        section = f"retirement.{goal.goal_id}"
        why: list[str] = []
        caveats: list[str] = []
        subject = _subject(ctx, goal.owners)
        age = subject.age if subject is not None else None
        if income is None:
            why.append("no_income_is_recorded_for_the_household")
        if age is None:
            why.append("the_members_age_is_not_recorded")
        if goal.target_amount is None:
            why.append("the_goal_names_no_yearly_amount")
        covered: float = 0
        reached = False
        ahv_payload = pillar2_payload = None
        if income is not None:
            try:
                record = ctx.record("ahv-pension")
            except NotApproved:
                why.append("the_ahv_table_is_not_approved")
            else:
                first = ahv_illustration(record, income, None)
                reached = True
                covered += first.yearly
                caveats.extend(first.caveats)
                ahv_payload = {"basis": "current_income_as_a_stand_in_for_the_lifetime_average",
                               "monthly": first.monthly, "yearly": first.yearly, "at_minimum": first.at_minimum,
                               "at_maximum": first.at_maximum, "levers": ahv_levers(record, first)}
        if age is not None and income is not None:
            try:
                record = ctx.record("bvg-projection")
            except NotApproved:
                why.append("the_pension_projection_record_is_not_approved")
            else:
                values = [p.magnitude for p in _active(ctx.req.positions) if _is_stock(p)
                          and p.stock_kind == "asset" and p.vessel == "pillar_2"]
                balance = float(sum(values)) if values else None
                second = bvg_project(record, current_age=age, opening_balance=balance or 0, gross_salary=income)
                reached = True
                yearly = second.monthly_pension * 12
                covered += yearly
                caveats.extend(second.caveats)
                if balance is None:
                    caveats.append("no_position_names_a_pension_fund_so_the_opening_balance_is_zero")
                pillar2_payload = {"opening_balance": second.opening_balance,
                                   "coordinated_salary": second.coordinated,
                                   "closing_balance": second.closing_balance, "monthly": second.monthly_pension,
                                   "yearly": yearly, "from_age": second.from_age, "to_age": second.to_age,
                                   "levers": bvg_levers(record, second)}
        if _composition_degrades(ctx):
            why.append("the_household_composition_is_past_its_validity_horizon")
        verdict = COULD_NOT_BE_DETERMINED
        covered_out = shortfall = None
        if reached and goal.target_amount:
            covered_out = covered
            shortfall = max(0, goal.target_amount - covered)
            verdict = MEETS if covered >= goal.target_amount else DOES_NOT_MEET
            if "the_household_composition_is_past_its_validity_horizon" in why:
                verdict = COULD_NOT_BE_DETERMINED
        for reason in why:
            kind = "record_not_approved" if "approved" in reason else (
                "past_its_validity_horizon" if "horizon" in reason else "not_in_the_request")
            ctx.gap(section, reason, kind, f"the retirement finding: {reason.replace('_', ' ')}")
        out.append(RetirementFinding(goal_id=goal.goal_id, verdict=verdict, needs_per_year=goal.target_amount,
                                     target_date=goal.target_date, undetermined_because=tuple(why),
                                     caveats=tuple(caveats), ahv=ahv_payload, pillar2=pillar2_payload,
                                     covered_per_year=covered_out, shortfall_per_year=shortfall))
    return tuple(out)


# ===========================================================================
# Risk profile (services/risk_profile.py, services/profile_inputs.py)
# ===========================================================================

def _between(value: float, low: dict, high: dict, low_key: str, high_key: str, out_low: float,
             out_high: float) -> float:
    a, b = float(low[low_key]), float(high[high_key])
    if b == a:
        return out_high
    t = min(1, max(0, (float(value) - a) / (b - a)))
    return out_low + t * (out_high - out_low)


def lerp(low: Any, high: Any, t: float) -> Any:
    if t <= 0:
        return low
    if t >= 1:
        return high
    if isinstance(low, dict):
        out = {}
        for key, value in low.items():
            if key not in high:
                out[key] = value
            elif isinstance(value, dict) or isinstance(value, (int, float)):
                out[key] = lerp(value, high[key], t)
            else:
                out[key] = value
        return out
    return float(low) + (float(high) - float(low)) * t


def capacity_inputs(ctx: Ctx) -> tuple[dict[str, Any], dict[str, str]]:
    """``profile_inputs.collect``, from the request. Vessel instead of label (LBS-06); liabilities are not
    free wealth (LBS-15). Three prototype quirks are corrected when the calibration says so (LBS-24): the
    horizon without a dated goal, a stated zero income, and a stock without a vessel; and two more (LBS-28): a
    human-capital stock is not free wealth, and a stated mortgage of 0 is a debt service of 0."""
    r = ctx.req.risk
    today = ctx.req.as_of
    sources: dict[str, str] = {}

    def note(name: str, value: Any, source: str) -> Any:
        sources[name] = source if value is not None else ABSENT
        return value

    dated = [g.target_date for g in ctx.req.goals if g.target_date is not None]
    years = max(0, (min(dated) - today).days / ctx.cal.policy.capacity_days_per_year) if dated else None
    horizon = note("horizon_years", years, "plan")
    if horizon is None and ctx.corrects("capacity_horizon_is_years_to_the_planned_age"):
        # plan_until_age is an age; the horizon is the years from the subject's age to it (LBS-24).
        subject = _subject(ctx, ())
        age = subject.age if subject is not None else None
        if r.plan_until_age is None:
            horizon = note("horizon_years", None, "submission")
        elif age is None:
            horizon = note("horizon_years", None, "submission")
            ctx.gap("risk_profile", "horizon_years", "not_in_the_request",
                    "no goal is dated and plan_until_age is an age, not a horizon: the years to it need the age of "
                    "the principal (or the only adult), which is not stated")
        else:
            horizon = note("horizon_years", max(0.0, float(r.plan_until_age) - age),
                           "submission: plan_until_age less the age")
    elif horizon is None:
        horizon = note("horizon_years", r.plan_until_age, "submission")
    corrected_vessel = ctx.corrects("unstated_vessel_is_a_gap")
    human_is_human = ctx.corrects("human_capital_is_never_free_wealth")
    human: list[Position] = []
    free: float = 0
    locked: float = 0
    illiquid: float = 0
    unknown: list[Position] = []
    income: float = 0
    income_stated = False
    for p in _active(ctx.req.positions):
        if p.magnitude is None:
            continue
        if p.unit == FLOW_UNIT and p.role == "income":
            income += p.magnitude
            income_stated = True
        elif p.unit in STOCK_UNITS and p.stock_kind == "asset":
            if p.capital_type == "human" and human_is_human:
                # Human capital only: neither free nor any other financial wealth (LBS-28).
                human.append(p)
            elif p.vessel in ("pillar_2", "pillar_3a"):
                locked += p.magnitude
            elif p.vessel == "real_asset":
                illiquid += p.magnitude
            elif p.vessel is None and corrected_vessel and p.capital_type == "financial":
                unknown.append(p)
            else:
                free += p.magnitude
    unstated = float(sum(p.magnitude for p in unknown))
    total = free + locked + illiquid + unstated
    free_source = "plan"
    if unknown:
        free_source = "plan, a lower bound: stocks without a vessel are wealth but not free wealth"
        ctx.gap("risk_profile", "vessel", "not_in_the_request",
                f"positions {', '.join(p.position_id for p in unknown)} state no vessel, so they are not counted "
                "as free wealth; the free share and the reserve are lower bounds")
    if human:
        free_source += (f"; human-capital stocks ({', '.join(p.position_id for p in human)}) are human capital, "
                        "not financial wealth, and are left out")
    free_share = note("free_share", (free / total) if total else None, free_source)
    reserve = r.liquidity_reserve_months
    if reserve is None and r.spend_now_per_year and r.spend_now_per_year > 0 and free:
        reserve = free / (r.spend_now_per_year / 12)
    reserve_months = note("reserve_months", reserve, "submission")
    employment = note("employment", r.employment or None, "submission")
    if ctx.corrects("zero_income_is_a_stated_zero"):
        # A stated zero is zero; the shares below stay undefined at a zero income (a share of nothing).
        gross = r.gross_income_per_year if r.gross_income_per_year is not None else (
            income if income_stated else None)
    else:
        gross = r.gross_income_per_year or (income or None)
    variable = r.variable_income_per_year
    variable_share = note("variable_share", (variable / gross) if (variable is not None and gross) else None,
                          "submission")
    mandates = note("mandates", r.mandates, "submission")
    service = None
    debt_source = "submission"
    if ctx.corrects("zero_mortgage_is_a_stated_zero"):
        # A stated 0 is a paid-off mortgage; only an unstated one is unknown (LBS-28).
        if r.mortgage is not None:
            service = r.mortgage * ((r.mortgage_rate_pct or 0) / 100) + (r.amortisation_per_year or 0)
            if r.mortgage == 0:
                debt_source = "submission: a stated mortgage of 0 is a paid-off mortgage"
    elif r.mortgage:
        service = r.mortgage * ((r.mortgage_rate_pct or 0) / 100) + (r.amortisation_per_year or 0)
    debt = note("debt_service_share", (service / gross) if (service is not None and gross) else None,
                debt_source)
    return ({"horizon_years": horizon, "reserve_months": reserve_months, "employment": employment,
             "variable_share": variable_share, "mandates": mandates, "free_share": free_share,
             "debt_service_share": debt}, sources)


def willingness(record: dict[str, Any], stated_loss: Optional[float], crisis: Optional[str]) -> dict[str, Any]:
    spec = record["willingness"]
    caps, floors = spec["crisis_behaviour"]["caps"], spec["crisis_behaviour"]["floors"]
    key = (crisis or "").strip() or "_unanswered"
    cap = float(caps.get(key, caps["_unanswered"]))
    floor = float(floors.get(key, 0))
    reason = ("no crisis behaviour was stated, which is not evidence of composure"
              if key == "_unanswered" else f"stated behaviour: {key}")
    if stated_loss is None:
        return {"stated_loss": None, "crisis_behaviour": crisis, "from_stated": None, "cap": cap, "floor": floor,
                "cap_reason": reason, "value": floor or None, "capped": False, "lifted": bool(floor)}
    scale = spec["from_stated_loss"]
    raw = _between(stated_loss, scale["at_or_below"], scale["at_or_above"], "loss", "loss",
                   float(scale["at_or_below"]["profile"]), float(scale["at_or_above"]["profile"]))
    value = min(max(raw, floor), cap)
    return {"stated_loss": stated_loss, "crisis_behaviour": crisis, "from_stated": raw, "cap": cap, "floor": floor,
            "cap_reason": reason, "value": value, "capped": cap < raw, "lifted": floor > raw}


def capacity(record: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    spec = record["capacity"]["components"]
    out: dict[str, Any] = {}
    missing: list[str] = []

    def line(name: str, value: Any, key: str) -> None:
        c = spec[name]
        if value is None:
            missing.append(name)
            return
        v = _between(value, c["at_or_below"], c["at_or_above"], key, key, float(c["at_or_below"]["value"]),
                     float(c["at_or_above"]["value"]))
        out[name] = {"input": value, "value": v, "weight": float(c["weight"])}

    line("horizon", inputs["horizon_years"], "years")
    line("reserve", inputs["reserve_months"], "months")
    line("free_share", inputs["free_share"], "share")
    line("debt_service", inputs["debt_service_share"], "share")
    stability = spec["income_stability"]
    employment, variable, mandates = inputs["employment"], inputs["variable_share"], inputs["mandates"]
    if employment is None and variable is None and mandates is None:
        missing.append("income_stability")
    else:
        base = float(stability["base"].get((employment or "").strip(), stability["base_unknown"]))
        if variable:
            base -= min(1, max(0, float(variable))) * float(stability["variable_share_subtracts_up_to"])
        if mandates:
            base += min(int(mandates) * float(stability["each_mandate_adds"]), float(stability["mandates_add_at_most"]))
        out["income_stability"] = {"input": {"employment": employment, "variable_share": variable,
                                             "mandates": mandates},
                                   "value": min(1, max(0, base)), "weight": float(stability["weight"])}
    total = sum(c["weight"] for c in out.values())
    value = None if not total else sum(c["value"] * c["weight"] for c in out.values()) / total
    return {"components": out, "value": value, "missing": missing}


def sustainability(record: dict[str, Any], exclusions: tuple[str, ...], level: Optional[str]) -> dict[str, Any]:
    spec = record["sustainability"]
    offered = set(spec["exclusions"]["offered"])
    named = [str(x).strip() for x in exclusions if str(x).strip()]
    esg_min: float = 0
    for entry in spec["minimum"]["levels"]:
        if entry["label"] == (level or "").strip():
            esg_min = float(entry["esg_min"])
            break
    return {"exclusions": [x for x in named if x in offered], "level": level, "esg_min": esg_min,
            "unknown_exclusions": [x for x in named if x not in offered]}


def risk_profile(ctx: Ctx) -> RiskProfile | NotAvailable:
    try:
        record = ctx.record("risk-profile")
    except NotApproved as exc:
        ctx.gap("risk_profile", "risk-profile", "record_not_approved",
                "risk-profile is not approved: no profile, role bounds, curve slope or ESG floor is derived")
        return not_approved(exc.record)
    inputs, sources = capacity_inputs(ctx)
    w = willingness(record, ctx.req.risk.stated_loss, ctx.req.risk.crisis_behaviour)
    c = capacity(record, inputs)
    caveats: list[str] = []
    if c["missing"]:
        caveats.append(f"capacity was computed without: {', '.join(sorted(c['missing']))}")
    if w["capped"]:
        caveats.append("stated tolerance was capped by the crisis answer")
    if w["lifted"]:
        caveats.append("demonstrated behaviour raised the claim above the stated tolerance")
    sus = sustainability(record, ctx.req.risk.esg_exclusions, ctx.req.risk.esg_level)
    both = [x for x in (w["value"], c["value"]) if x is not None]
    base = dict(willingness=w, capacity=c, capacity_inputs={**inputs, "sources": sources}, sustainability=sus)
    if not both:
        ctx.gap("risk_profile", "profile", "not_in_the_request",
                "neither the position nor a stated tolerance could be read")
        return RiskProfile(value=None, binds_on=None, role_bounds=None, asset_class_bounds=None, curve_slope=None,
                           caveats=tuple(caveats + ["neither the position nor a stated tolerance could be read"]),
                           **base)
    value = min(both)
    note = None
    if c["value"] is None:
        binds, note = "willingness", ("nothing was known of the position, so the stated tolerance alone decides — "
                                      "the case this design exists to avoid, reported rather than hidden")
    elif w["value"] is None:
        binds, note = "capacity", "no tolerance was stated, so the position decides unrestrained"
    elif w["value"] == c["value"]:
        binds = "both"
    else:
        binds = "willingness" if w["value"] < c["value"] else "capacity"
    if note:
        caveats.append(note)
    anchors = record["anchors"]

    def floats(d: dict[str, Any]) -> dict[str, dict[str, float]]:
        return {k: {kk: float(vv) for kk, vv in v.items() if isinstance(vv, (int, float))
                    and not isinstance(vv, bool)}
                for k, v in d.items() if isinstance(v, dict) and not k.startswith("_")}

    return RiskProfile(
        value=value, binds_on=binds,
        role_bounds=floats(lerp(anchors["role_bounds"]["cautious"], anchors["role_bounds"]["aggressive"], value)),
        asset_class_bounds=floats(lerp(anchors["asset_class_bounds"]["cautious"],
                                       anchors["asset_class_bounds"]["aggressive"], value)),
        curve_slope={k: float(v) for k, v in lerp(anchors["curve_slope"]["cautious"],
                                                  anchors["curve_slope"]["aggressive"], value).items()
                     if isinstance(v, (int, float))},
        caveats=tuple(caveats), **base)


# ===========================================================================
# The mandate proposal (engines/lbs/derive.py, s_curve_trajectory.required_return)
# ===========================================================================

def required_return(initial_wealth: float, target: float, contributions: list[float], *, steps_per_year: int,
                    ceiling: float, tolerance: float, max_iterations: int,
                    reach_the_ceiling: bool = False) -> Optional[float]:
    """The S-curve engine's bisection: the constant annual return that funds the goal by its date. ``0.0``
    when already funded without a return, ``None`` when no return up to the ceiling reaches it.

    The bracket doubles from 1. Reproduction (``reach_the_ceiling`` false): it stops as soon as the doubled
    bound exceeds the ceiling, so with the ceiling 10 the last bound tested is 8 and the effective ceiling is
    800 percent (LBS-17). Corrected (LBS-24): the last doubling is clamped to the ceiling, which is tested, so
    the stated bound is the bound."""
    if not contributions:
        raise EngineError("required_return needs a contribution path with at least one step")

    def terminal(annual: float) -> float:
        step = (1.0 + annual) ** (1.0 / steps_per_year) - 1.0
        value = float(initial_wealth)
        for c in contributions:
            value = value * (1.0 + step) + c
        return value

    if terminal(0.0) >= target:
        return 0.0
    low, high = 0.0, 1.0
    if reach_the_ceiling:
        high = min(high, ceiling)
        while terminal(high) < target:
            if high >= ceiling:
                return None
            high = min(high * 2.0, ceiling)
    else:
        while terminal(high) < target:
            high *= 2.0
            if high > ceiling:
                return None
    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        if terminal(mid) < target:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break
    return 0.5 * (low + high)


def _effective_ceiling(ceiling: float) -> float:
    """The last bound the prototype's doubling search tests: the largest power of two not above the ceiling."""
    high = 1.0
    while high * 2.0 <= ceiling:
        high *= 2.0
    return high


def goal_contribution(ctx: Ctx, goal: Any, saving: float, notes: list[str]) -> float:
    """What of the household's one yearly saving goes to the designated goal, in CHF a year; a stated 0 is 0.

    Up to 1.2.0 (LBS-25): all of it, paid in twelve equal monthly steps. From 1.3.0 (LBS-29): the goal's stated
    ``contribution_share`` of it. With no share stated for the goal: all of it when it is the only goal in the
    request; otherwise the most it can receive, the rest the other goals' stated shares leave, which makes the
    required return a lower bound, and the missing share is a gap (a zero rest is exact: the other goals take
    the whole saving)."""
    goals = ctx.req.goals
    stated = [g for g in goals if g.contribution_share is not None]
    others = [g for g in goals if g.goal_id != goal.goal_id]
    split = ctx.corrects("contribution_is_split_by_goal_share")
    if not split or (goal.contribution_share is None and not others):
        # Up to 1.2.0, and from 1.3.0 for the only goal in the request when it states no share: all of it.
        notes.append(f"the contribution of {saving:,.0f} a year is the household's stated yearly saving, "
                     "read as going wholly to this goal in twelve monthly steps; savings shared with other goals "
                     "would make the required return higher than shown")
        if stated and not split:
            notes.append("this calibration does not split the saving between goals, so the stated contribution "
                         "shares are not read (they are from calibration 1.3.0 on)")
        return saving
    if goal.contribution_share is not None:
        share = float(goal.contribution_share)
        amount = saving * share
        notes.append(f"the household's stated yearly saving is {saving:,.0f}; this goal's stated share of it, "
                     f"{share:.1%}, is {amount:,.0f} a year, paid in twelve monthly steps")
        return amount
    rest = max(0.0, 1.0 - sum(float(g.contribution_share) for g in stated))
    if rest <= 1e-12:
        notes.append(f"the household's stated yearly saving is {saving:,.0f}; the other goals' stated shares take "
                     "all of it, so none goes to this goal")
        return 0.0
    amount = saving * rest
    ctx.gap("mandate_proposal", "contribution_share", "not_in_the_request",
            f"the request has {len(goals)} goals and does not state this goal's share of the yearly saving "
            f"(goals[{goal.goal_id}].contribution_share); the most it can receive, {rest:.1%} of it, is used, so "
            "the required return is a lower bound")
    notes.append(f"the household's stated yearly saving is {saving:,.0f}; this goal's share is not stated, so the "
                 f"most it can receive ({rest:.1%}, {amount:,.0f} a year) is used: the required return and the "
                 "curve's level are lower bounds until the share is stated")
    return amount


def mandate_proposal(ctx: Ctx, totals_: Totals, profile: RiskProfile | NotAvailable) -> MandateProposal | NotAvailable:
    req, pol = ctx.req, ctx.cal.policy
    section = "mandate_proposal"
    if req.mandate is None:
        ctx.gap(section, "mandate.goal_id", "not_in_the_request",
                "no goal is designated for the mandate; choosing one for the household would decide what its "
                "portfolio is for")
        return NotAvailable(reason=("not available: no goal is designated for the mandate (request.mandate, which "
                                    "also carries the yearly contribution)"))
    m = req.mandate
    goal = next(g for g in req.goals if g.goal_id == m.goal_id)
    notes: list[str] = []
    curator: list[CuratorItem] = []

    # -- what the portfolio has to accumulate
    target: Optional[float] = None
    basis: str
    if goal.kind == "property":
        if goal.target_amount is None:
            basis = "not available: the property goal names no price"
            ctx.gap(section, "target_amount", "not_in_the_request", "the property goal names no price")
        else:
            try:
                record = ctx.record("property-funding")
            except NotApproved:
                basis = "not available: record not approved (property-funding), so no deposit is derived"
                ctx.gap(section, "property-funding", "record_not_approved", basis)
            else:
                mt = mandate_target(record, goal.target_amount, goal.occupancy)
                target = mt.target
                basis = (f"deposit: {mt.equity_min:.0%} of the price {mt.price:,.0f} "
                         f"({'strictest occupancy assumed' if mt.assumed else 'occupancy ' + mt.occupancy}); the "
                         "rest is a mortgage, which the affordability test governs")
                if mt.assumed:
                    notes.append(mt.why)
    elif goal.kind == "retirement":
        basis = ("not available: a yearly need becomes a capital requirement only at a withdrawal rate, and no "
                 "withdrawal rate is published")
        ctx.gap(section, "target_capital", "needs_an_unpublished_assumption", basis)
    else:
        if goal.target_amount is None:
            basis = "not available: the goal names no amount"
            ctx.gap(section, "target_amount", "not_in_the_request", "the goal names no amount")
        else:
            target = float(goal.target_amount)
            basis = "the goal's own amount"

    horizon: Optional[float] = None
    if goal.target_date is None:
        ctx.gap(section, "target_date", "not_in_the_request",
                "the goal is undated; any horizon written here would decide when the household needs the money")
    else:
        horizon = (goal.target_date - req.as_of).days / pol.days_per_year
        if horizon <= 0:
            ctx.gap(section, "target_date", "not_in_the_request",
                    f"the goal's date is not after as_of ({horizon:.2f} years); it is not a goal to fund")
    drawable = totals_.drawable
    saving = m.annual_contribution
    contribution = goal_contribution(ctx, goal, saving, notes) if saving is not None else None
    if saving is None:
        ctx.gap(section, "annual_contribution", "not_in_the_request",
                "the yearly contribution toward the goal is not stated (mandate.annual_contribution, the "
                "onboarding's \"How much can you put aside each year?\"); a required return and a target curve "
                "without it would rest on a zero nobody stated")

    r_star: Optional[float] = None
    feasible: Optional[bool] = None
    curve: Optional[tuple[float, ...]] = None
    if target is not None and horizon is not None and horizon > 0 and drawable is not None and contribution is not None:
        steps = max(1, int(round(horizon * pol.steps_per_year)))
        r_star = required_return(drawable, target, [contribution / pol.steps_per_year] * steps,
                                 steps_per_year=pol.steps_per_year, ceiling=pol.search_ceiling,
                                 tolerance=pol.bisection_tolerance, max_iterations=pol.bisection_max_iterations,
                                 reach_the_ceiling=ctx.corrects("required_return_search_reaches_its_ceiling"))
        feasible = r_star is not None
        if r_star is None:
            if ctx.corrects("required_return_search_reaches_its_ceiling"):
                bound = f"at any return up to {pol.search_ceiling:.0%}"
            else:
                bound = (f"at any return the search tested (the prototype's doubling stops below its "
                         f"{pol.search_ceiling:.0%} ceiling, at {_effective_ceiling(pol.search_ceiling):.0%})")
            notes.append(f"the goal of {target:,.0f} in {horizon:.2f} years is not reachable from {drawable:,.0f} "
                         f"drawable and {contribution:,.0f} a year {bound}; no required return exists and no "
                         "curve is proposed")
            ctx.gap(section, "required_return", "not_in_the_request",
                    "the goal is unreachable at any plausible return; the levers are the horizon, the "
                    "contributions, the starting wealth and the goal's size, not the allocation")
        elif r_star == 0.0:
            notes.append("the goal is already funded at a zero return: the mandate is capital preservation")

    if isinstance(profile, RiskProfile) and profile.curve_slope:
        floor_off = profile.curve_slope["floor_offset"]
        ceiling_off = profile.curve_slope["ceiling_offset"]
        shape = {"source": "risk-profile", "floor_offset": floor_off, "ceiling_offset": ceiling_off,
                 "why": "the approved risk profile's curve slope, interpolated between its anchors"}
    else:
        floor_off, ceiling_off = pol.curve_floor_offset, pol.curve_ceiling_offset
        shape = {"source": "policy", "floor_offset": floor_off, "ceiling_offset": ceiling_off,
                 "why": ("CIO policy (derive.py M50): a mandate asks less of a crisis than of a boom; no approved "
                         "risk profile supplies a household slope")}
    shape["level"] = ("the ramp is level-shifted so its equal-weighted mean over the 25 states is the required "
                      "return (the ramp is symmetric); pcp weights states by the client's regime blend (LBS-11)")
    shape["unit"] = "each decimal point p is published as the log return ln(1 + p)"
    if r_star is not None:
        points = []
        for s in range(25):
            p = r_star + floor_off + (ceiling_off - floor_off) * s / 24
            if p <= -1.0:
                raise EngineError(f"target curve point {p} is a loss of the whole portfolio")
            points.append(math.log1p(p))
        curve = tuple(points)
    else:
        curator.append(CuratorItem(field="target_curve", reason="no required return could be derived; see gaps"))

    # -- bounds, derived dimensions only
    bounds: dict[str, dict[str, ProposedBound]] = {}
    bounds["currency"] = {pol.currency: ProposedBound(
        lower=pol.currency_floor, upper=1.0,
        reasoning=(f"every stock is stated in {pol.currency.lower()} and the goal is a {pol.currency} amount: a "
                   f"{pol.currency_floor:.0%} floor in the goal's currency, because currency risk against a fixed "
                   "liability is not diversification (derive.py)"))}
    if horizon is not None and horizon > 0:
        rule = next((r for r in pol.liquidity_rules if horizon <= r.horizon_at_most_years), None)
        if rule is None:
            notes.append(f"a {horizon:.2f}-year deadline imposes no liquidity requirement, so none is proposed")
        else:
            bounds["liquidity"] = {bucket: ProposedBound(
                lower=lo, upper=hi,
                reasoning=(f"a {horizon:.2f}-year deadline (at most {rule.horizon_at_most_years:g} years) "
                           f"forces reachable wealth: {bucket} in [{lo:g}, {hi:g}] (derive.py deadline ladder)"))
                for bucket, (lo, hi) in rule.bounds.items()}
    if isinstance(profile, RiskProfile) and profile.role_bounds:
        bounds["role"] = {role: ProposedBound(
            lower=b["lower"], upper=b["upper"],
            reasoning=(f"the risk profile {profile.value:.4f} ({profile.binds_on} binds) interpolates the "
                       "risk-profile anchors between cautious and aggressive"))
            for role, b in profile.role_bounds.items()}
    else:
        curator.append(CuratorItem(field="bounds.role", reason=(
            "role bounds derive from the risk profile, whose record is not approved or could not be computed")))
    esg_min: Optional[float] = None
    if isinstance(profile, RiskProfile):
        esg_min = float(profile.sustainability["esg_min"])
    else:
        curator.append(CuratorItem(field="esg_min", reason="the ESG floor comes from the risk-profile record, "
                                                           "which is not approved"))
    curator.extend([
        CuratorItem(field="universe", reason="the investable set is policy; lbs holds no instrument register"),
        CuratorItem(field="max_single_position", reason=(
            "derive.py derived per-instrument caps from each block's crisis-state return against the goal "
            "buffer; lbs reads no ReturnSet, so the cap is the curator's")),
        CuratorItem(field="regime_weights", reason="the client's economy blend (or a regime_market) is the "
                                                   "curator's; pcp blends the Regime from it (PCP-04)"),
        CuratorItem(field="bounds.region|capital_type|phase|asset_class",
                    reason="policy dimensions (System Build Manual 14.2); never derived"),
    ])
    if isinstance(profile, RiskProfile) and profile.asset_class_bounds:
        notes.append("the risk profile also interpolates asset-class bounds "
                     f"{profile.asset_class_bounds}; asset class is a policy dimension, so they are a suggestion "
                     "for the curator and not a derived bound")
    return MandateProposal(
        client=req.client_ref, name=m.name or f"lbs-{goal.goal_id}", currency=pol.currency, target_curve=curve,
        esg_min=esg_min, bounds=bounds, bound_sources={d: "derived" for d in bounds}, goal_id=goal.goal_id,
        goal_kind=goal.kind, target_basis=basis, target_chf=target, goal_horizon_years=horizon,
        drawable_chf=drawable, annual_contribution=contribution, required_return=r_star, feasible=feasible,
        curve_shape=shape, curator_to_fill=tuple(curator), complete=not curator, notes=tuple(notes))


# ===========================================================================
# The whole sheet
# ===========================================================================

def build(req: LifeBalanceSheetRequest, cal: Calibration) -> tuple[dict[str, Any], tuple[Gap, ...],
                                                                     tuple[RecordUse, ...]]:
    """Every section of the sheet, the gaps and the records read. The service adds ids and provenance."""
    ctx = Ctx(req=req, cal=cal)
    household = household_section(ctx)
    cells = grid(ctx)
    tot = totals(ctx)
    hc = human_capital(ctx)
    pens, couple = pensions(ctx)
    prop = property_findings(ctx, tot.household_income)
    liq = liquidity_findings(ctx)
    ret = retirement_findings(ctx, tot.household_income)
    obs = observations(ctx)
    profile = risk_profile(ctx)
    mandate = mandate_proposal(ctx, tot, profile)
    body = dict(household=household, grid=cells, totals=tot, human_capital=hc, pensions=pens, couple_cap=couple,
                property=prop, liquidity=liq, retirement=ret, observations=obs, risk_profile=profile,
                mandate_proposal=mandate)
    gaps = tuple(sorted(ctx.gaps, key=lambda g: (g.section, g.input, g.kind)))
    return body, gaps, ctx.uses()
