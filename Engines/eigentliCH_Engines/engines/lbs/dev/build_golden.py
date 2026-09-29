"""Freeze the golden cases: lbs requests and the eigentliCH prototype's own outputs for them.

Run with the PROTOTYPE's interpreter, never this family's (it imports the prototype's services and SQLAlchemy):

    C:\\Users\\nicol\\Desktop\\SIM_NAS\\Projects\\eigentliCH\\Prototype\\.venv\\Scripts\\python.exe -X utf8 dev/build_golden.py

Read-only use of the prototype, enforced rather than promised:

* the member database is opened as ``sqlite:///file:...?mode=ro&uri=true``, so any write the services might
  attempt raises instead of landing;
* approval fixtures replace a module's ``_record`` in memory (the prototype's own test technique,
  ``tests/test_ahv_and_pension.py::_approve``); no content file is touched;
* nothing is written outside ``golden/`` in this engine's folder.

No names, e-mail addresses, goal names, position labels or free-text answers are copied: members become
``db-01`` ..., persons ``p1`` ..., positions and goals opaque ids, and labels are reduced to the vessel the
prototype's own keyword rule reads from them (``goals._capital_by_eligibility``, ``profile_inputs._ILLIQUID``).

Two layers of cases:

* ``db-*``: eight members of the prototype database, run through the prototype's wiring end to end
  (``goals.property_finding``, ``goals.retirement_finding``, ``computations._retirement_provision``,
  ``human_capital.capitals``, ``engine_inputs.stated_stocks``, ``profile_inputs.collect``, ...).
* ``syn-*``: constructed cases that reach what the database does not (an occupancy, linked funding, a couple,
  a liability, an illiquid-funded goal), computed by the prototype's leaf services directly. The five
  ``syn-property-*`` cases are the report cases of ``tests/test_property.py``, renamed.

Each case is frozen twice: under the records as shipped (``seed``) and with ``ahv-pension`` and
``risk-profile`` approved by a test fixture (``approved``), so the refusal and the arithmetic behind it are
both golden.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

PROTO = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\Prototype")
EIGENTLICH = PROTO.parent
DB = PROTO / "backend" / "eigentlich.db"
HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "golden"
AS_OF = date(2026, 9, 28)

sys.path.insert(0, str(PROTO / "backend"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from eigentlich import content  # noqa: E402
from eigentlich.models import Goal, Member, Position  # noqa: E402
from eigentlich.services import ahv, computations, engine_inputs, goals as goal_service  # noqa: E402
from eigentlich.services import household as household_service  # noqa: E402
from eigentlich.services import human_capital as hc  # noqa: E402
from eigentlich.services import liquidity, pension_projection as pp, profile_inputs  # noqa: E402
from eigentlich.services import property as prop  # noqa: E402
from eigentlich.services import risk_profile as rp  # noqa: E402


def _load_scurve():
    """The S-curve engine by file path, so the eigentliCH ``engines`` package (which registers adapters on
    import) is never imported."""
    path = EIGENTLICH / "engines" / "s_curve_trajectory" / "engine.py"
    spec = importlib.util.spec_from_file_location("scurve_engine", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scurve_engine"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SCURVE = _load_scurve()
DAYS_PER_YEAR = 365.2425  # eigentlich.engines.DAYS_PER_YEAR, read below and asserted equal
from eigentlich.engines import DAYS_PER_YEAR as _PROTO_DAYS  # noqa: E402

assert _PROTO_DAYS == DAYS_PER_YEAR


# ---------------------------------------------------------------------------
# Approval fixtures (the prototype's own test technique)
# ---------------------------------------------------------------------------

APPROVED = ("ahv-pension", "risk-profile")


class approvals:
    """Within the block, ahv and risk_profile read an approved copy of their record."""

    def __init__(self, on: bool):
        self.on = on

    def __enter__(self):
        self.saved = (ahv._record, rp._record)
        if self.on:
            records = {}
            for name in APPROVED:
                record = copy.deepcopy(content._load(name))
                record["_about"].update({"provisional": False, "published_by": "Golden Fixture",
                                         "decided_on": "2026-09-28", "effective_from": "2026-09-28"})
                records[name] = record
            ahv._record = lambda: records["ahv-pension"]
            rp._record = lambda: records["risk-profile"]
        return self

    def __exit__(self, *exc):
        ahv._record, rp._record = self.saved


# ---------------------------------------------------------------------------
# The prototype's label rules, reduced to lbs's vessel
# ---------------------------------------------------------------------------

def vessel(label: str | None, capital_type: str, unit: str | None) -> str | None:
    if unit != "chf" or capital_type != "financial":
        return None
    text = (label or "").lower()
    if "3a" in text or "säule 3" in text or "saule 3" in text:
        return "pillar_3a"
    if "pensionskasse" in text or "pk-" in text or "2. säule" in text or "freizügigkeit" in text:
        return "pillar_2"
    if any(word in text for word in profile_inputs._ILLIQUID):
        return "real_asset"
    return "free"


def goal_kind(goal) -> str:
    if goal.occupancy is not None or goal_service._looks_like_a_property_goal(goal):
        return "property"
    if goal.template == "retirement" or goal_service._looks_like_a_retirement_goal(goal):
        return "retirement"
    return "other"


def text_or_none(value):
    return value if isinstance(value, str) else None


def num(value):
    return hc._number(value)


def human_capital_answers(answers: dict) -> dict:
    return {
        "qualification_highest": text_or_none(answers.get("qualification_highest")),
        "qualification_year": num(answers.get("qualification_year")),
        "years_in_field": num(answers.get("years_in_field")),
        "education_recent": text_or_none(answers.get("education_recent")),
        "network_people": num(answers.get("network_people")),
        "mandates": num(answers.get("mandates")),
        "network_reach": text_or_none(answers.get("network_reach")),
        "health": None if answers.get("health") is None else str(answers.get("health")),
        "hours_per_week": num(answers.get("hours_per_week")),
        "rest_hours": None if answers.get("rest_hours") is None else str(answers.get("rest_hours")),
        "hours_learning": num(answers.get("hours_learning")),
        "hours_network": num(answers.get("hours_network")),
    }


def capital(c) -> dict:
    return {"value": c.value, "source": c.source, "absent_because": c.absent_because}


def human_capital_expected(answers: dict) -> dict:
    caps = hc.capitals(answers)
    tb = hc.time_budget(answers)
    return {"E": capital(caps.E), "N": capital(caps.N), "H": capital(caps.H), "caveats": list(caps.caveats),
            "time_budget": {"tau_Y": tb.tau_Y, "tau_E": tb.tau_E, "tau_N": tb.tau_N, "tau_H": tb.tau_H,
                            "leisure": tb.leisure, "caveats": list(tb.caveats)}}


def ahv_expected(income, years_missing) -> dict:
    try:
        full = ahv.scale()["partial"]["full_scale"]
    except ahv.ScaleNotApproved:
        return {"status": "not_available", "refused": "ScaleNotApproved"}
    if not income:
        return {"status": "not_available", "missing": ["income"]}
    years = None if years_missing is None else max(0, int(full) - int(years_missing))
    res = ahv.illustration_for(current_income=income, contribution_years=years)
    return {"status": "available", "monthly": res.monthly, "yearly": res.yearly, "full_monthly": res.full_monthly,
            "factor": res.factor, "caveats": list(res.caveats)}


def bvg_expected(result) -> dict:
    if isinstance(result, computations.Undetermined):
        return {"status": "not_available", "missing": list(result.missing)}
    i = result.inputs
    return {"status": "available", "closing_balance": i["closing_balance"], "yearly_pension": i["yearly_pension"],
            "opening_balance": i["pillar2"], "gross_salary": i["income_gross"]}


def property_expected(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    out = {k: payload.get(k) for k in ("verdict", "binds_on", "undetermined_because", "ineligible_funding",
                                       "levers")}
    out["equity"] = payload.get("equity")
    out["affordability"] = payload.get("affordability")
    return out


def retirement_expected(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    out = {k: payload.get(k) for k in ("verdict", "undetermined_because", "covered_per_year", "shortfall_per_year",
                                       "needs_per_year")}
    out["ahv_yearly"] = (payload.get("ahv") or {}).get("yearly")
    p2 = payload.get("pillar2") or {}
    out["pillar2_closing"] = p2.get("closing_balance")
    out["pillar2_yearly"] = p2.get("yearly")
    return out


def liquidity_expected(finding) -> dict | None:
    if finding is None:
        return None
    return {"gap_chf": finding["gap_chf"], "due_date": finding["due_date"], "reason": finding["reason"],
            "lever": finding["prepared"]["lever"], "requires_curator": finding["prepared"]["requires_curator"],
            "considered": finding["prepared"]["considered"]}


def risk_expected(collected: profile_inputs.Inputs, stated: dict) -> dict:
    try:
        profile = rp.profile(stated_loss=stated["stated_loss"], crisis_behaviour=stated["crisis_behaviour"],
                             **collected.as_kwargs())
        sus = rp.sustainability(exclusions=stated["esg_exclusions"], level=stated["esg_level"])
    except rp.ProfileNotApproved:
        return {"status": "not_available", "refused": "ProfileNotApproved"}
    return {"status": "available", "value": profile.value, "binds_on": profile.binds_on,
            "capacity": profile.capacity.value, "willingness": profile.willingness.value,
            "role_bounds": profile.role_bounds, "curve_slope": profile.curve_slope, "esg_min": sus.esg_min,
            "capacity_inputs": collected.as_kwargs()}


def mandate_expected(kind, amount, target_date, occupancy, drawable, contribution) -> dict:
    """The mandate's derivable half, from the prototype and the eigentliCH S-curve engine."""
    out: dict = {}
    if kind == "property":
        if amount is None:
            return {"target": None}
        mt = prop.mandate_target(amount, occupancy=occupancy)
        out.update(target=mt.target, occupancy_used=mt.occupancy, assumed=mt.assumed)
    elif kind == "retirement":
        return {"target": None}
    else:
        out["target"] = amount
    if target_date is None or out["target"] is None:
        return out
    horizon = (target_date - AS_OF).days / DAYS_PER_YEAR
    out["horizon_years"] = horizon
    if horizon <= 0 or drawable is None or contribution is None:
        return out
    steps = max(1, int(round(horizon * SCURVE.STEPS_PER_YEAR)))
    out["required_return"] = SCURVE.required_return(drawable, out["target"], horizon,
                                                    [contribution / SCURVE.STEPS_PER_YEAR] * steps)
    return out


# ---------------------------------------------------------------------------
# Database cases
# ---------------------------------------------------------------------------

#: Chosen for variety (one adult, two adults, older than the reference age, a property goal, an "other" goal
#: with an amount, a member with member facts). The prefixes are the members' ids in the prototype database.
DB_MEMBERS = ("038e92f3", "1ad09ef4", "3d8aaa58", "47527a1f", "4c5550ca", "5da43ed9", "92977053", "fed4280c")


def db_case(session: Session, prefix: str, index: int) -> tuple[dict, dict]:
    member = session.execute(select(Member).where(Member.id.like(prefix + "%"))).scalar_one()
    mid = member.id
    answers = computations._answers(session, member_id=mid)
    household = household_service.current(session, member_id=mid)
    positions = list(session.execute(select(Position).where(Position.member_id == mid)
                                     .order_by(Position.created_at, Position.id)).scalars())
    goal_rows = list(session.execute(select(Goal).where(Goal.member_id == mid)
                                     .order_by(Goal.created_at, Goal.id)).scalars())
    gid = {g.id: f"g{i + 1}" for i, g in enumerate(goal_rows)}
    pid = {p.id: f"a{i + 1}" for i, p in enumerate(positions)}

    persons = []
    others = 0
    for hm in [m for m in household.members if m.left_on is None]:
        if hm.member_id == mid:
            persons.append({"person_id": "p1", "kind": hm.kind, "age": member.age_at_registration,
                            "stated_gross_income": num(answers.get("income_gross")),
                            "human_capital": human_capital_answers(answers),
                            "ahv": {"contribution_years_missing": (None if num(answers.get("ahv_years_missing")) is None
                                                                   else int(num(answers.get("ahv_years_missing"))))}})
        else:
            others += 1
            persons.append({"person_id": f"p{others + 1}", "kind": hm.kind})
    persons.sort(key=lambda p: p["person_id"])

    funding: dict[str, list[str]] = {}
    for g in goal_rows:
        for p in g.funded_by:
            funding.setdefault(p.id, []).append(gid[g.id])
    req_positions = []
    for p in positions:
        req_positions.append({
            "position_id": pid[p.id], "role": p.role, "capital_type": p.capital_type, "magnitude": p.magnitude,
            "unit": p.magnitude_unit, "stock_kind": p.stock_kind, "liquidity": p.liquidity,
            "vessel": vessel(p.label, p.capital_type, p.magnitude_unit), "owner": "p1", "active": bool(p.active),
            "funds_goals": funding.get(p.id, [])})
    req_goals = [{"goal_id": gid[g.id], "kind": goal_kind(g), "target_amount": g.target_amount,
                  "target_date": g.target_date.isoformat() if g.target_date else None, "occupancy": g.occupancy}
                 for g in goal_rows]

    stated = profile_inputs.stated_risk(session, member_id=mid)
    raw = profile_inputs._latest_answers(session, mid)
    risk = {"stated_loss": stated["stated_loss"], "crisis_behaviour": stated["crisis_behaviour"],
            "esg_exclusions": stated["esg_exclusions"], "esg_level": stated["esg_level"],
            "employment": raw.get("employment") or None,
            "liquidity_reserve_months": num(raw.get("liquidity_reserve_months")),
            "spend_now_per_year": num(raw.get("spend_now")), "variable_income_per_year": num(raw.get("income_variable")),
            "gross_income_per_year": num(raw.get("income_gross")),
            "mandates": None if num(raw.get("mandates")) is None else int(num(raw.get("mandates"))),
            "plan_until_age": num(raw.get("plan_until_age")), "mortgage": num(raw.get("mortgage")),
            "mortgage_rate_pct": num(raw.get("mortgage_rate")), "amortisation_per_year": num(raw.get("amortisation"))}

    # The mandate goal: the first goal with an amount and a date, preferring one that is not a retirement goal.
    candidates = [g for g in goal_rows if g.target_amount and g.target_date]
    chosen = next((g for g in candidates if goal_kind(g) != "retirement"), candidates[0] if candidates else None)
    savings = num(raw.get("savings"))
    request = {
        "client_ref": f"db-{index:02d}", "as_of": AS_OF.isoformat(),
        "household": {"composition_as_of": household.composition_as_of.isoformat(), "persons": persons,
                      "principal": "p1"},
        "positions": req_positions, "goals": req_goals,
        "facts": {"canton": text_or_none(answers.get("canton")), "civil_status": text_or_none(answers.get("civil_status"))},
        "risk": risk,
        "mandate": ({"goal_id": gid[chosen.id], "annual_contribution": savings} if chosen is not None else None),
    }

    # -- the prototype's outputs
    stocks = engine_inputs.stated_stocks(positions)
    # profile_inputs.collect's own split, for the mandate's drawable ("free").
    free = 0
    for p in positions:
        if p.active and p.magnitude is not None and p.magnitude_unit == "chf":
            label = (p.label or "").lower()
            if any(w in label for w in profile_inputs._LOCKED) or any(w in label for w in profile_inputs._ILLIQUID):
                continue
            if p.capital_type == "financial" and p.stock_kind == "asset":
                free += p.magnitude
    has_free = any(r["vessel"] == "free" and r["stock_kind"] == "asset" and r["active"] for r in req_positions)
    expected = {}
    for variant in ("seed", "approved"):
        with approvals(variant == "approved"):
            income = computations._gross_income(session, member_id=mid)
            e: dict = {
                "stocks": {"financial_assets": stocks.financial_assets, "human_assets": stocks.human_assets,
                           "liabilities": stocks.liabilities},
                "household_income": (goal_service._household_income(session, goal_rows[0]) if goal_rows else None),
                "human_capital": {"p1": human_capital_expected(answers)},
                "bvg": {"p1": bvg_expected(computations._retirement_provision(session, member_id=mid))},
                "ahv": {"p1": ahv_expected(income, num(answers.get("ahv_years_missing")))},
                "property": {gid[g.id]: property_expected(goal_service.property_finding(session, g))
                             for g in goal_rows if goal_kind(g) == "property"},
                "retirement": {gid[g.id]: retirement_expected(goal_service.retirement_finding(session, g, member=member))
                               for g in goal_rows if goal_kind(g) == "retirement"},
                "liquidity": {gid[g.id]: liquidity_expected(liquidity.finding(g, today=AS_OF)) for g in goal_rows},
                "observations": {gid[g.id]: sorted(o["kind"] for o in goal_service.observations(g, today=AS_OF))
                                 for g in goal_rows},
                "risk_profile": risk_expected(profile_inputs.collect(session, member_id=mid, today=AS_OF), stated),
                "mandate": (mandate_expected(goal_kind(chosen), chosen.target_amount, chosen.target_date,
                                             chosen.occupancy, free if has_free else None, savings)
                            if chosen is not None else None),
            }
            expected[variant] = e
    return request, expected


# ---------------------------------------------------------------------------
# Constructed cases, through the leaf services
# ---------------------------------------------------------------------------

#: tests/test_property.py REAL: price, year, occupancy, hard, pillar 2, pillar 3a, household income.
PROPERTY_REPORT = (
    (1_500_000, 2038, "owner_occupied_primary", 475_600, 0, 17_750, 69_550),
    (2_000_000, 2037, "owner_occupied_primary", 332_000, 0, 0, 24_000),
    (1_500_000, 2040, "owner_occupied_primary", 471_000, 0, 0, 70_200),
    (1_100_000, 2034, "owner_occupied_primary", 276_600, 0, 8_600, 175_000),
    (1_500_000, 2036, "second_or_holiday_home", 64_000, 95_000, 77_000, 285_860),
)


def syn_property(i: int, row) -> tuple[dict, dict]:
    price, year, occupancy, hard, p2, p3a, income = row
    positions = [{"position_id": "a1", "role": "stabilisation", "capital_type": "financial", "magnitude": hard,
                  "unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free", "owner": "p1",
                  "funds_goals": ["g1"]}]
    if p2:
        positions.append({"position_id": "a2", "role": "protection", "capital_type": "financial", "magnitude": p2,
                          "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid", "vessel": "pillar_2",
                          "owner": "p1", "funds_goals": ["g1"]})
    if p3a:
        positions.append({"position_id": "a3", "role": "protection", "capital_type": "financial", "magnitude": p3a,
                          "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid", "vessel": "pillar_3a",
                          "owner": "p1", "funds_goals": ["g1"]})
    positions.append({"position_id": "i1", "role": "income", "capital_type": "human", "magnitude": income,
                      "unit": "chf_per_year", "owner": "p1"})
    target_date = date(year, 12, 31)
    contribution = 12_000.0
    request = {"client_ref": f"syn-property-{i}", "as_of": AS_OF.isoformat(),
               "household": {"composition_as_of": "2026-09-01",
                             "persons": [{"person_id": "p1", "kind": "adult", "age": 35}]},
               "positions": positions,
               "goals": [{"goal_id": "g1", "kind": "property", "target_amount": price,
                          "target_date": target_date.isoformat(), "occupancy": occupancy, "owners": ["p1"]}],
               "facts": {"civil_status": "ledig", "has_no_liabilities": True},
               "mandate": {"goal_id": "g1", "annual_contribution": contribution}}
    expected = {}
    for variant in ("seed", "approved"):
        with approvals(variant == "approved"):
            a = prop.assess(goal_id="g1", price=price, target_date=target_date, occupancy=occupancy,
                            hard_available=hard, pillar2_available=p2, pillar3a_available=p3a, household_income=income)
            payload = a.as_payload()
            payload["levers"] = prop.levers(a, household_income=income)
            expected[variant] = {
                "stocks": {"financial_assets": float(hard + p2 + p3a), "human_assets": None, "liabilities": None},
                "net_worth": float(hard + p2 + p3a),
                "household_income": float(income),
                "property": {"g1": property_expected(payload)},
                "mandate": mandate_expected("property", price, target_date, occupancy, float(hard), contribution),
            }
    return request, expected


def syn_couple() -> tuple[dict, dict]:
    """A married couple: two incomes, an incomplete AHV record, pillar 2 balances, a mortgage and a home."""
    people = (("p1", 52, 110_000.0, 2, 310_000.0), ("p2", 49, 64_000.0, 5, 120_000.0))
    positions = []
    for person, _age, income, _missing, p2 in people:
        positions.append({"position_id": f"i-{person}", "role": "income", "capital_type": "human", "magnitude": income,
                          "unit": "chf_per_year", "owner": person})
        positions.append({"position_id": f"pk-{person}", "role": "protection", "capital_type": "financial",
                          "magnitude": p2, "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid",
                          "vessel": "pillar_2", "owner": person})
    positions += [
        {"position_id": "home", "role": "stabilisation", "capital_type": "financial", "magnitude": 1_250_000.0,
         "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid", "vessel": "real_asset", "owner": "p1"},
        {"position_id": "mortgage", "role": "stabilisation", "capital_type": "financial", "magnitude": 780_000.0,
         "unit": "chf", "stock_kind": "liability", "owner": "p1"},
        {"position_id": "cash", "role": "stabilisation", "capital_type": "financial", "magnitude": 95_000.0,
         "unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free", "owner": "p1",
         "funds_goals": ["g1"]},
        {"position_id": "skills", "role": "gain", "capital_type": "human", "magnitude": 40_000.0, "unit": "chf",
         "stock_kind": "asset", "owner": "p2"},
    ]
    request = {"client_ref": "syn-couple", "as_of": AS_OF.isoformat(),
               "household": {"composition_as_of": "2026-03-15", "persons": [
                   {"person_id": person, "kind": "adult", "age": age, "ahv": {"contribution_years_missing": missing}}
                   for person, age, _i, missing, _p in people] + [{"person_id": "p3", "kind": "dependant", "age": 12}]},
               "positions": positions,
               "goals": [{"goal_id": "g1", "kind": "other", "target_amount": 180_000.0,
                          "target_date": "2031-06-30", "owners": ["p1", "p2"]}],
               "facts": {"civil_status": "verheiratet"},
               "mandate": {"goal_id": "g1", "annual_contribution": 15_000.0}}
    fin = 310_000.0 + 120_000.0 + 1_250_000.0 + 95_000.0
    expected = {}
    for variant in ("seed", "approved"):
        with approvals(variant == "approved"):
            e: dict = {"stocks": {"financial_assets": fin, "human_assets": 40_000.0, "liabilities": 780_000.0},
                       "net_worth": fin + 40_000.0 - 780_000.0, "household_income": 174_000.0,
                       "ahv": {}, "bvg": {}}
            monthly = []
            for person, age, income, missing, p2 in people:
                e["ahv"][person] = ahv_expected(income, missing)
                if e["ahv"][person]["status"] == "available":
                    monthly.append(ahv.illustration_for(current_income=income, contribution_years=44 - missing))
                res = pp.project(current_age=age, opening_balance=p2, gross_salary=income)
                e["bvg"][person] = {"status": "available", "closing_balance": res.closing_balance,
                                    "yearly_pension": res.monthly_pension * 12, "opening_balance": p2,
                                    "gross_salary": income, "total_credited": res.total_credited,
                                    "total_interest": res.total_interest}
            e["couple"] = (ahv.couple(first=monthly[0], second=monthly[1]) if len(monthly) == 2
                           else {"status": "not_available"})
            e["mandate"] = mandate_expected("other", 180_000.0, date(2031, 6, 30), None, 95_000.0, 15_000.0)
            expected[variant] = e
    return request, expected


def syn_liquidity() -> tuple[dict, dict]:
    """A dated goal funded only by illiquid holdings, one by mixed holdings, an undated one and a lapsed one."""
    def position(pid, magnitude, liq, vessel_, goals):
        return {"position_id": pid, "role": "stabilisation", "capital_type": "financial", "magnitude": magnitude,
                "unit": "chf", "stock_kind": "asset", "liquidity": liq, "vessel": vessel_, "owner": "p1",
                "funds_goals": goals}
    positions = [position("art", 45_000.0, "illiquid", "real_asset", ["g1", "g4"]),
                 position("car", 18_000.0, "illiquid", "real_asset", ["g1"]),
                 position("cash", 2_000.0, "immediate", "free", ["g2"]),
                 position("fund", 30_000.0, None, "free", ["g2"])]
    goals = [("g1", "2029-12-31"), ("g2", "2030-06-30"), ("g3", None), ("g4", "2026-01-31")]
    request = {"client_ref": "syn-liquidity", "as_of": AS_OF.isoformat(),
               "household": {"composition_as_of": "2025-06-01", "persons": [{"person_id": "p1", "kind": "adult",
                                                                            "age": 44}]},
               "positions": positions,
               "goals": [{"goal_id": g, "kind": "other", "target_amount": 50_000.0, "target_date": d} for g, d in goals],
               "facts": {"civil_status": "ledig"}}
    ns_positions = {p["position_id"]: SimpleNamespace(id=p["position_id"], active=True, liquidity=p["liquidity"],
                                                      magnitude=p["magnitude"], magnitude_unit=p["unit"])
                    for p in positions}
    expected = {}
    for variant in ("seed", "approved"):
        with approvals(variant == "approved"):
            liq, obs = {}, {}
            for g, d in goals:
                funded = [ns_positions[p["position_id"]] for p in positions if g in p["funds_goals"]]
                goal = SimpleNamespace(target_date=date.fromisoformat(d) if d else None, funded_by=funded)
                liq[g] = liquidity_expected(liquidity.finding(goal, today=AS_OF))
                obs[g] = sorted(o["kind"] for o in goal_service.observations(goal, today=AS_OF))
            expected[variant] = {"liquidity": liq, "observations": obs,
                                 "composition_expired": True}
    return request, expected


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    engine = create_engine(f"sqlite:///file:{DB.as_posix()}?mode=ro&uri=true", future=True)
    cases: dict[str, tuple[dict, dict]] = {}
    with Session(engine) as session:
        for i, prefix in enumerate(DB_MEMBERS, start=1):
            cases[f"db-{i:02d}"] = db_case(session, prefix, i)
        session.rollback()
    for i, row in enumerate(PROPERTY_REPORT, start=1):
        cases[f"syn-property-{i}"] = syn_property(i, row)
    cases["syn-couple"] = syn_couple()
    cases["syn-liquidity"] = syn_liquidity()

    (OUT / "cases").mkdir(parents=True, exist_ok=True)
    (OUT / "expected").mkdir(parents=True, exist_ok=True)
    for name, (request, expected) in cases.items():
        (OUT / "cases" / f"{name}.json").write_text(json.dumps(request, indent=1, ensure_ascii=False, default=str),
                                                     encoding="utf-8")
        (OUT / "expected" / f"{name}.json").write_text(
            json.dumps(expected, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    manifest = {
        "built_by": "dev/build_golden.py", "interpreter": sys.executable, "as_of": AS_OF.isoformat(),
        "prototype": str(PROTO), "database_sha256": sha(DB),
        "content_records_sha256": {n: sha(PROTO / "client" / "content" / f"{n}.json")
                                   for n in ("ahv-pension", "bvg-projection", "human-capital", "property-funding",
                                             "liquidity-levers", "risk-profile", "intake-scales", "roles",
                                             "currency-horizons")},
        "variants": {"seed": "records as shipped",
                     "approved": "ahv-pension and risk-profile approved by an in-memory fixture"},
        "cases": sorted(cases),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cases)} cases frozen in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
