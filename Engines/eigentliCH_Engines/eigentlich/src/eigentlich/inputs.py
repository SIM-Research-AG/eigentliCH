"""The ``lbs-request@1.0.0`` built from what the store holds for one client (EIG-32).

Pure: ``gather`` reads the store, ``build`` maps what was read. Nothing is guessed that lbs would read as a
statement: an unstated household stays ``None`` (lbs reports it as a gap), a missing amount stays absent, an
answer that does not fit the contract is left out and named in ``dropped``, never coerced into range.

Where each field comes from:

* ``client_ref``: the client id (opaque; never the display name).
* ``household``: the client's current household (``closed_on`` null) and its members who have not left. The
  client is ``p1`` and the principal; other members ``p2``, ``p3``, ... in their stored order. Age of ``p1`` is
  ``age_at_registration`` (the store holds no birth date; the prototype read the same field).
* ``human_capital``, income, AHV years: the client's current answers. A stated ``client_fact`` wins over an
  onboarding answer, which wins over an intake answer.
* **the partner** (EIG-53): the first other adult of the household (in ``MEMBER_ORDER``) is the partner. Their
  age, gross salary, working hours, missing AHV years and human-capital answers come from the intake's partner
  section (``partner_*``, section 21), unless ``partner_in_plan`` is ``nein``. Other members carry their kind
  only. Nothing is read from another client's own record.
* ``positions``: every position of the client (inactive ones flagged ``active: false``). ``vessel`` is
  ``tags.vessel`` when stated, else the prototype's label rule (LBS-06); role ``growth`` is lbs's ``gain``.
  ``owner`` is the partner's person for ``position.owner = 'partner'``, else ``p1`` (the client) when there is a
  household; a partner's position without a partner in the household has no owner and is named in ``dropped``.
* ``goals``: the active goals. ``kind`` is ``property`` for a stated occupancy or a property word in the
  name or template, ``retirement`` for a retirement template or word, else ``other`` (the prototype's
  rules, which lbs's golden builder applies too). ``contribution_share`` is the goal's stored share (EIG-59);
  shares that sum above 1 (possible only through a direct write) are all left out and named in ``dropped``,
  since lbs would refuse the whole request.
* ``facts``: canton and civil status (fact, then answer); ``risk``: the intake's risk answers.
* ``mandate``: the first active goal with an amount and a date, preferring one that is not a retirement
  goal (the golden builder's rule). ``annual_contribution`` is the onboarding's ``annual_contribution``
  answer, CHF per year (EIG-45; a stated fact of that key would win, as everywhere). Without a mandate goal
  the contribution has nothing to attach to and is named in ``dropped``; without an answer it stays absent
  and lbs names the gap.
* **the nominal and real view** (lbs LBS-31): ``goals[].amount_basis`` is the goal's stored ``amount_basis``
  (``today`` or ``future``, EIG-60) and ``mandate.contribution_indexed`` the onboarding's
  ``contribution_indexed`` answer (``ja`` true, ``nein`` false, EIG-61). Each is sent only when stated; unstated,
  lbs reads today's francs and a fixed contribution (owner decisions 7 and 9), and the request keeps its bytes.
* ``risk.esg_exclusions``: the intake's ``esg_exclusions``: the chosen options (a list, EIG-44), or for an
  answer to the earlier free-text version, the text split at commas, semicolons and line breaks.
* **lbsim's answers** (lbs@1.4.0, LBS-39; EIG-65), each sent only when stated, so a request without them keeps its
  bytes: per adult ``earning_power`` from the intake (the principal's ``income_expected_full``, ``kader``,
  ``sector``, ``education_status``, ``education_end_year``, ``education_hours``, ``education_budget``,
  ``health_work_capacity``; the partner's ``partner_*`` of the same, while ``partner_in_plan`` is not ``nein``);
  ``facts.stop_work_age`` from ``work_until_age``, ``facts.legal_documents`` from the five document questions of
  section 12 (those answered ``ja``, by name; answered and none ``ja`` is a stated none),
  ``facts.pillar3a_contribution_per_year`` from ``pillar3a_contribution``, and from the ``properties`` entries
  ``facts.mortgage_fixed_until`` (the earliest "Fest bis" of a property with a mortgage, 31 December of that year),
  ``facts.amortisation_mode`` (direct or indirect of the first property with a mortgage that states one) and
  ``facts.own_use_share`` (the self-occupied share of the stated values, only when every entry states its value and
  its use). What does not fit lbs's rules is left out and named in ``dropped``: an unknown management tier, an end
  year with no education, an education that ends before the year of the sheet, an answer outside its range. The
  work capacity is K3 data, as health: withheld health withholds it too (lbs refuses the two together).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from pydantic import ValidationError

from . import contracts as c

ONBOARDING = "questionnaire/onboarding"
INTAKE = "questionnaire/intake"

# The prototype's label and name rules (profile_inputs._ILLIQUID, goals._PROPERTY_WORDS, _RETIREMENT_WORDS).
_ILLIQUID = ("sammlung", "kunst", "fahrzeug", "liegenschaft", "wohneigentum", "beteiligung")
_PROPERTY_WORDS = ("eigenheim", "wohneigentum", "eigentum", "immobilie", "haus", "wohnung", "ferienhaus")
_RETIREMENT_WORDS = ("rente", "pension", "ruhestand", "ab 65", "aufhören", "aufhoren", "frühpension",
                     "fruehpension", "nicht mehr arbeiten", "ausgaben ab")
_PROPERTY_TEMPLATES = ("home_ownership", "holiday_property")
_RETIREMENT_TEMPLATES = ("early_retirement", "retirement")

VESSELS = ("free", "pillar_2", "pillar_3a", "real_asset")

#: A goal amount's basis (EIG-60) and the indexed contribution's answer (EIG-61), as lbs reads them.
AMOUNT_BASES = ("today", "future")
INDEXED: dict[Any, bool] = {"ja": True, "nein": False, True: True, False: False}

#: A household's current members: the client first, then adults, then dependants, by label. Members written
#: in one transaction share created_at, and household_member has no write-order column.
MEMBER_ORDER = ("SELECT * FROM household_member WHERE household_id = %s AND left_on IS NULL "
                "ORDER BY (client_id IS NOT DISTINCT FROM %s) DESC, kind, label, id")


def vessel_of(position: dict[str, Any]) -> Optional[str]:
    if position.get("magnitude_unit") != "chf" or position.get("capital_type") != "financial":
        return None
    stated = (position.get("tags") or {}).get("vessel")
    if stated in VESSELS:
        return stated
    text = (position.get("label") or "").lower()
    if "3a" in text or "säule 3" in text or "saule 3" in text:
        return "pillar_3a"
    if "pensionskasse" in text or "pk-" in text or "2. säule" in text or "freizügigkeit" in text:
        return "pillar_2"
    if any(word in text for word in _ILLIQUID):
        return "real_asset"
    return "free"


def goal_kind(goal: dict[str, Any]) -> str:
    name = (goal.get("name") or "").lower()
    template = goal.get("template") or ""
    if goal.get("occupancy") or template in _PROPERTY_TEMPLATES or any(w in name for w in _PROPERTY_WORDS):
        return "property"
    if template in _RETIREMENT_TEMPLATES or any(w in name for w in _RETIREMENT_WORDS):
        return "retirement"
    return "other"


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("'", "").replace("’", "").replace(" ", "").replace(",", ".")
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return float(text)
    return None


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _exclusions(value: Any) -> tuple[str, ...]:
    """A list (the aligned intake's multi_choice, EIG-44) or, answered to the earlier free-text version, the
    text split at commas, semicolons and line breaks."""
    if isinstance(value, str):
        return tuple(s.strip() for s in re.split(r"[,;\n]", value) if s.strip())
    if isinstance(value, list):
        return tuple(s.strip() for s in value if isinstance(s, str) and s.strip())
    return ()


#: lbs's ``human-capital.responsibility.tiers`` (calibration 1.5.0): each tier by its key and its labels, as the
#: intake's ``kader`` options word them. Any other answer is left out (lbs refuses an unknown tier, 422).
RESPONSIBILITY_TIERS = ("ohne Kaderfunktion", "oberes und mittleres Kader", "topmanagement",
                        "Keine Führungsfunktion", "Oberes oder mittleres Kader", "Oberste Führung",
                        "No management function", "Upper or middle management", "Top management")
#: The intake's words (EIG-65) and lbs's: the education states and how far health limits the working week.
EDUCATION_STATUS = {"keine": "none", "läuft": "in_progress", "geplant": "planned",
                    "none": "none", "in_progress": "in_progress", "planned": "planned"}
WORK_CAPACITY = {"nein": 1.0, "leicht": 0.8, "deutlich": 0.5, "stark": 0.2}
#: The legal documents of intake section 12 by the name lbsim reads.
LEGAL_DOCUMENTS = (("legal_will", "Testament"), ("legal_marriage_contract", "Ehevertrag"),
                   ("legal_cohabitation", "Konkubinatsvertrag"), ("legal_power_of_attorney", "Vorsorgeauftrag"),
                   ("legal_patient_decree", "Patientenverfügung"))
_AMORTISATION = {"direkt": "direct", "indirekt über Säule 3a": "indirect", "indirekt": "indirect"}


def earning_power(prefix: str, answer, num, dropped: list[str], as_of: date,
                  health_withheld: bool = False) -> Optional[c.EarningPowerAnswers]:
    """One adult's earning-power answers (EIG-65): ``prefix`` is ``""`` for the principal, ``"partner_"`` for the
    partner. ``None`` when nothing is stated (the request keeps its bytes)."""
    def key(name: str) -> str:
        return f"{prefix}{name}"

    values: dict[str, Any] = {"expected_full_pensum_income": num(key("income_expected_full"))}
    tier = _text(answer(key("kader")))
    if tier is not None and tier not in RESPONSIBILITY_TIERS:
        dropped.append(f"{key('kader')}: {tier!r} is not a management tier lbs knows")
        tier = None
    values["responsibility"] = tier
    values["sector"] = _text(answer(key("sector")))
    raw_status = answer(key("education_status"))
    status = EDUCATION_STATUS.get(raw_status) if isinstance(raw_status, str) else None
    if raw_status is not None and status is None:
        dropped.append(f"{key('education_status')}: {raw_status!r} is not keine, läuft or geplant")
    values["education_status"] = status
    end = num(key("education_end_year"), low=2000, high=2100)
    if end is not None and status == "none":
        dropped.append(f"{key('education_end_year')}: {end:g}, but no education is under way or planned")
        end = None
    elif end is not None and status in ("in_progress", "planned") and end < as_of.year:
        dropped.append(f"{key('education_end_year')}: {end:g} is before {as_of.year}, the year of the sheet")
        end = None
    values["education_end_year"] = None if end is None else int(end)
    hours = answer(key("education_hours"))
    values["education_hours"] = _text(hours) if isinstance(hours, str) else (
        num(key("education_hours"), high=168) if hours is not None else None)
    values["education_budget_per_year"] = num(key("education_budget"))
    raw_capacity = answer(key("health_work_capacity"))
    capacity = WORK_CAPACITY.get(raw_capacity) if isinstance(raw_capacity, str) else None
    if raw_capacity is not None and capacity is None:
        dropped.append(f"{key('health_work_capacity')}: not one of the options")
    if capacity is not None and health_withheld:
        dropped.append(f"{key('health_work_capacity')}: withheld with the health answers (K3)")
        capacity = None
    values["health_work_capacity"] = capacity
    if all(v is None for v in values.values()):
        return None
    return c.EarningPowerAnswers(**values)


def _year_end(value: Any) -> Optional[date]:
    year = _number(value)
    if year is None or not 2000 <= year <= 2100 or year != int(year):
        return None
    return date(int(year), 12, 31)


def stated_facts(answer, num, dropped: list[str]) -> dict[str, Any]:
    """lbs@1.4.0's six facts (LBS-39) from the intake, only the stated ones (EIG-65)."""
    out: dict[str, Any] = {}
    stop = num("work_until_age")
    if stop is not None:
        if 40 <= stop <= 75:
            out["stop_work_age"] = stop
        else:
            dropped.append(f"work_until_age: {stop:g} is outside 40 to 75, the ages lbs reads as a stop age")
    answered = [(k, name) for k, name in LEGAL_DOCUMENTS if answer(k) is not None]
    if answered:
        out["legal_documents"] = tuple(name for k, name in answered if answer(k) == "ja")
    p3a = num("pillar3a_contribution")
    if p3a is not None:
        out["pillar3a_contribution_per_year"] = p3a
    props = answer("properties")
    entries = [e for e in props if isinstance(e, dict)] if isinstance(props, list) else []
    mortgaged = [e for e in entries if (_number(e.get("mortgage")) or 0) > 0]
    fixed = [d for d in (_year_end(e.get("fixed_until")) for e in mortgaged) if d is not None]
    if fixed:
        out["mortgage_fixed_until"] = min(fixed)
    modes = [_AMORTISATION.get(str(e.get("amortisation_kind") or "")) for e in mortgaged]
    mode = next((m for m in modes if m), None)
    if mode:
        out["amortisation_mode"] = mode
    valued = [(_number(e.get("value")), e.get("occupancy")) for e in entries]
    if valued and all(v is not None and v >= 0 and occ for v, occ in valued) and sum(v for v, _ in valued) > 0:
        own = sum(v for v, occ in valued if occ == "Ich wohne selbst darin")
        out["own_use_share"] = round(own / sum(v for v, _ in valued), 6)
    return out


def _partner(pid: str, answer, num, dropped: Optional[list[str]] = None,
             as_of: Optional[date] = None) -> c.LbsPerson:
    """The partner as the intake's partner section states them (EIG-53); an unanswered question stays absent."""
    years = num("partner_ahv_years_missing")
    age = num("partner_age", high=120)
    health = answer("partner_health")
    hc = c.HumanCapitalAnswers(
        qualification_highest=_text(answer("partner_qualification_highest")),
        qualification_year=num("partner_qualification_year"),
        years_in_field=num("partner_years_in_field"),
        education_recent=_text(answer("partner_education_recent")),
        network_people=num("partner_network_people"),
        mandates=num("partner_mandates"),
        network_reach=_text(answer("partner_network_reach")),
        health=None if health is None else str(health),
        hours_per_week=num("partner_hours_per_week"),
        rest_hours=_text(answer("partner_rest_hours")),
    )
    ep = earning_power("partner_", answer, num, dropped if dropped is not None else [], as_of or date.today(),
                       health_withheld=hc.health_withheld)
    return c.LbsPerson(person_id=pid, kind="adult", age=None if age is None else int(round(age)),
                       stated_gross_income=num("partner_income_gross"), human_capital=hc,
                       ahv=c.AhvFacts(contribution_years_missing=None if years is None else int(years)),
                       earning_power=ep)


@dataclass
class Gathered:
    client: dict[str, Any]
    answers: dict[str, dict[str, Any]]          # questionnaire key -> {question key: value}
    facts: dict[str, Any]                        # stated key -> value (current facts)
    positions: list[dict[str, Any]]
    goals: list[dict[str, Any]]
    funding: list[dict[str, Any]]                # active goal_funding rows
    owners: list[dict[str, Any]]                 # active goal_owner rows
    household: Optional[dict[str, Any]]
    members: list[dict[str, Any]] = field(default_factory=list)


def gather(conn, client_id: str) -> Gathered:
    from . import store

    client = store.get_client(conn, client_id)
    answers: dict[str, dict[str, Any]] = {}
    for key in (ONBOARDING, INTAKE):
        answers[key] = {a["question_key"]: a["value"] for a in store.get_answers(conn, client_id, key)}
    plan = store.plan_of(conn, client_id, include_inactive=True)
    facts = {f["stated_key"]: f["stated_value"] for f in plan["facts"]}
    goals = [g for g in plan["goals"] if g["active"]]
    goal_ids = [g["id"] for g in goals]
    funding = conn.execute("SELECT goal_id, position_id FROM goal_funding WHERE active AND goal_id = ANY(%s)",
                           (goal_ids,)).fetchall()
    owners = conn.execute("SELECT goal_id, household_member_id FROM goal_owner WHERE active AND goal_id = ANY(%s)",
                          (goal_ids,)).fetchall()
    household = conn.execute(
        "SELECT h.* FROM household h JOIN household_member m ON m.household_id = h.id "
        "WHERE m.client_id = %s AND m.left_on IS NULL AND h.closed_on IS NULL "
        "ORDER BY h.created_at DESC, h.id LIMIT 1", (client_id,)).fetchone()
    members = []
    if household:
        members = conn.execute(MEMBER_ORDER, (household["id"], client_id)).fetchall()
    return Gathered(client=client, answers=answers, facts=facts, positions=plan["positions"], goals=goals,
                    funding=funding, owners=owners, household=household, members=members)


def build(g: Gathered, as_of: date) -> tuple[c.LbsRequest, list[str]]:
    """The request and the list of stored values left out because they do not fit the contract."""
    dropped: list[str] = []
    onb, intake = g.answers.get(ONBOARDING, {}), g.answers.get(INTAKE, {})

    def answer(key: str) -> Any:
        for source in (g.facts, onb, intake):
            if key in source and source[key] not in (None, "", [], {}):
                return source[key]
        return None

    def num(key: str, *, low: float = 0.0, high: Optional[float] = None) -> Optional[float]:
        raw = answer(key)
        if raw is None:
            return None
        value = _number(raw)
        if value is None or value < low or (high is not None and value > high):
            dropped.append(f"{key}: {raw!r} is not a number in range")
            return None
        return value

    client_id = g.client["id"]

    # -- household
    household = None
    partner_id: Optional[str] = None
    person_of_member: dict[str, str] = {}
    if g.household is not None and g.members:
        me = next((m for m in g.members if m["client_id"] == client_id), None)
        others = [m for m in g.members if m is not me]
        persons = []
        if me is not None:
            person_of_member[me["id"]] = "p1"
            years = num("ahv_years_missing")
            health = answer("health")
            hc = c.HumanCapitalAnswers(
                qualification_highest=_text(answer("qualification_highest")),
                qualification_year=num("qualification_year"),
                years_in_field=num("years_in_field"),
                education_recent=_text(answer("education_recent")),
                network_people=num("network_people"),
                mandates=num("mandates"),
                network_reach=_text(answer("network_reach")),
                health=None if health is None else str(health),
                hours_per_week=num("employment_time_basis"),
                rest_hours=_text(answer("rest_hours")),
                hours_learning=num("hours_learning"),
                hours_network=num("hours_network"),
            )
            ep = earning_power("", answer, num, dropped, as_of, health_withheld=hc.health_withheld) \
                if me["kind"] == "adult" else None
            persons.append(c.LbsPerson(
                person_id="p1", kind=me["kind"], age=g.client["age_at_registration"],
                stated_gross_income=num("income_gross"), human_capital=hc,
                ahv=c.AhvFacts(contribution_years_missing=None if years is None else int(years)),
                earning_power=ep))
        partner = next((m for m in others if m["kind"] == "adult"), None)
        for i, m in enumerate(others, start=2):
            pid = f"p{i}"
            person_of_member[m["id"]] = pid
            if m is partner:
                partner_id = pid
                persons.append(_partner(pid, answer, num, dropped, as_of) if answer("partner_in_plan") != "nein"
                               else c.LbsPerson(person_id=pid, kind="adult"))
            else:
                persons.append(c.LbsPerson(person_id=pid, kind=m["kind"]))
        if persons and any(p.kind == "adult" for p in persons):
            principal = "p1" if me is not None and me["kind"] == "adult" else None
            household = c.LbsHousehold(composition_as_of=g.household["composition_as_of"],
                                       persons=tuple(persons), principal=principal)
        else:
            dropped.append("household: no adult in the stated household")

    # -- goals
    goal_ids = {row["id"] for row in g.goals}
    goals = []
    for row in g.goals:
        owners = tuple(person_of_member[o["household_member_id"]] for o in g.owners
                       if o["goal_id"] == row["id"] and o["household_member_id"] in person_of_member
                       and household is not None)
        kind = goal_kind(row)
        goals.append(dict(goal_id=row["id"], kind=kind,
                          target_amount=row["target_amount"] if (row["target_amount"] or 0) >= 0 else None,
                          target_date=row["target_date"],
                          occupancy=row["occupancy"] if kind == "property" else None, owners=owners,
                          contribution_share=row.get("contribution_share"),
                          amount_basis=row.get("amount_basis") if row.get("amount_basis") in AMOUNT_BASES else None))
    shares = [x["contribution_share"] for x in goals if x["contribution_share"] is not None]
    if sum(shares) > 1 + 1e-9:
        dropped.append(f"contribution_share: the goals' shares sum to {sum(shares) * 100:.0f} %, above 100 %; none is sent")
        for x in goals:
            x["contribution_share"] = None
    goals = [c.LbsGoal(**x) for x in goals]

    # -- positions
    positions = []
    for row in g.positions:
        funds = tuple(f["goal_id"] for f in g.funding if f["position_id"] == row["id"] and f["goal_id"] in goal_ids)
        owner = None
        if household is not None:
            if row.get("owner") == "partner":
                owner = partner_id
                if owner is None:
                    dropped.append(f"position {row['label']!r}: belongs to the partner, but the household has no "
                                   "other adult; sent without an owner")
            elif "p1" in person_of_member.values():
                owner = "p1"
        try:
            positions.append(c.LbsPosition(
                position_id=row["id"], role="gain" if row["role"] == "growth" else row["role"],
                capital_type=row["capital_type"], magnitude=row["magnitude"], unit=row["magnitude_unit"],
                stock_kind=row["stock_kind"], liquidity=row["liquidity"], vessel=vessel_of(row),
                owner=owner,
                active=bool(row["active"]), funds_goals=funds))
        except ValidationError as exc:
            dropped.append(f"position {row['label']!r}: {exc.errors()[0]['msg']}")

    # -- facts and risk
    facts = c.LbsFacts(canton=_text(answer("canton")), civil_status=_text(answer("civil_status")),
                       **stated_facts(answer, num, dropped))
    loss = num("max_loss_pct", high=100)
    mandates = num("mandates")
    exclusions = answer("esg_exclusions")
    risk_values = dict(
        stated_loss=None if loss is None else loss / 100.0,
        crisis_behaviour=_text(answer("crisis_behaviour")),
        esg_exclusions=_exclusions(exclusions),
        esg_level=_text(answer("esg_minimum")),
        employment=_text(answer("employment")),
        liquidity_reserve_months=num("liquidity_reserve_months"),
        spend_now_per_year=num("spend_now"),
        variable_income_per_year=num("income_variable"),
        gross_income_per_year=num("income_gross"),
        mandates=None if mandates is None else int(mandates),
        plan_until_age=num("plan_until_age"),
    )
    risk = c.LbsRisk(**risk_values)

    # -- mandate
    candidates = [row for row in g.goals if row["target_amount"] and row["target_date"]]
    chosen = next((row for row in candidates if goal_kind(row) != "retirement"),
                  candidates[0] if candidates else None)
    contribution = num("annual_contribution")
    if contribution is not None and chosen is None:
        dropped.append(f"annual_contribution: {contribution:g} CHF per year, but no goal with an amount and a date "
                       "to attach it to (the mandate goal)")
    indexed_answer = answer("contribution_indexed")
    indexed = INDEXED.get(indexed_answer) if isinstance(indexed_answer, (str, bool)) else None
    if indexed_answer is not None and indexed is None:
        dropped.append(f"contribution_indexed: {indexed_answer!r} is neither ja nor nein")
    mandate = c.LbsMandate(goal_id=chosen["id"], annual_contribution=contribution, name=None,
                           contribution_indexed=indexed) if chosen else None

    request = c.LbsRequest(client_ref=client_id, as_of=as_of, household=household, positions=tuple(positions),
                           goals=tuple(goals), facts=facts, risk=risk, mandate=mandate)
    return request, dropped
