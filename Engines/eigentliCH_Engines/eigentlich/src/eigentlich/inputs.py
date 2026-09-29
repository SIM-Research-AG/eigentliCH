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


def _partner(pid: str, answer, num) -> c.LbsPerson:
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
    return c.LbsPerson(person_id=pid, kind="adult", age=None if age is None else int(round(age)),
                       stated_gross_income=num("partner_income_gross"), human_capital=hc,
                       ahv=c.AhvFacts(contribution_years_missing=None if years is None else int(years)))


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
            persons.append(c.LbsPerson(
                person_id="p1", kind=me["kind"], age=g.client["age_at_registration"],
                stated_gross_income=num("income_gross"), human_capital=hc,
                ahv=c.AhvFacts(contribution_years_missing=None if years is None else int(years))))
        partner = next((m for m in others if m["kind"] == "adult"), None)
        for i, m in enumerate(others, start=2):
            pid = f"p{i}"
            person_of_member[m["id"]] = pid
            if m is partner:
                partner_id = pid
                persons.append(_partner(pid, answer, num) if answer("partner_in_plan") != "nein"
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
    facts = c.LbsFacts(canton=_text(answer("canton")), civil_status=_text(answer("civil_status")))
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
