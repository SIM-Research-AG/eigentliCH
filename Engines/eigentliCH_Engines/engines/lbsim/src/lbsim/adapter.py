"""The adapter (spec 3.6): a Life Balance Sheet and the request it was built from, to the draft's submission.

The draft's fast half reads an intake submission (``onb@0.1.3``: ``meta``, ``state``, ``params``, ``goals``,
``raw``). lbs states the household once (LBSIM-05); this module reads that statement and nothing else, and
builds the submission the port computes on. Every value it had to supply rather than read is returned as an
assumption key, and every input a rule needs and the sheet lacks is returned as missing, so a rule is reported
unchecked rather than passed.

Mapping (section 3.6):

    state.age, E, N, H             the principal's age; sheet.human_capital[p].E/N/H.value
    W_L, W_P, W_3a, W_R            totals.by_vessel.free, .pillar_2, .pillar_3a, .real_asset
    W_res                          facts.own_use_share * W_R, else W_R (an assumption, the cautious one)
    D, rate, amortisation          totals.liabilities, risk.mortgage_rate_pct, risk.amortisation_per_year
    income_gross, hours            person.stated_gross_income, else owned income positions; hours_per_week
    spend_now                      risk.spend_now_per_year
    canton, civil status, children facts.canton, facts.civil_status, the dependants' ages
    partner                        the second adult: has_partner, partner_income, partner_age_offset
    earning-power answers          persons[].earning_power (lbs@1.4.0)
    stop age, documents, ...       facts (lbs@1.4.0); absent means the rule is unchecked, or the M73 default
                                   is used and listed in the assumptions
    goals                          property -> home (the deposit, property.mandate_target); retirement ->
                                   retirement; other with amount and date -> capital (LBSIM-19). Amounts in
                                   the francs of their date from real_view.goals[].nominal under calibration
                                   1.1.0; as stated under 1.0.0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from .contracts import Calibration, LbsPerson, LbsRequest, LbsSheet
from .fast import earning as _earning
from .fast.paths import FULL_TIME_HOURS

SCHEMA_VERSION = "onb@0.1.3"
#: The draft's AHV record: one missing year costs 1/44 (``gameplan.AHV_FULL_RECORD_YEARS``).
AHV_FULL_RECORD_YEARS = 44.0


class AdapterError(ValueError):
    """The sheet and its request do not describe one household (a mismatch, not a gap)."""


@dataclass(frozen=True)
class AdultInputs:
    """What the earning-power block reads for one adult."""

    person: LbsPerson
    E: Optional[float]
    N: Optional[float]
    H: Optional[float]
    capital_caveats: tuple[str, ...]
    gross_income: Optional[float]


@dataclass
class Adapted:
    submission: dict[str, Any]
    principal: str
    partner: Optional[str]
    adults: dict[str, AdultInputs]
    #: Assumption keys (the ``assumptions`` block of ``findings-text``), with the value used.
    assumptions: dict[str, Optional[float]] = field(default_factory=dict)
    #: Rule code -> question keys the sheet lacks for it.
    missing: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Submission goal index -> lbs goal id, and the lbs goal's date.
    goal_ids: list[str] = field(default_factory=list)
    goal_dates: dict[str, Any] = field(default_factory=dict)
    #: lbs goal id -> the target in both bases (``nominal``, ``real``) and its basis.
    goal_amounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    inflation: float = 0.0
    debt_known: bool = True


def _vessel(sheet: LbsSheet, name: str) -> float:
    v = sheet.totals.by_vessel.get(name)
    return float(v) if v is not None else 0.0


def _owned_income(request: LbsRequest, person_id: str) -> Optional[float]:
    flows = [p.magnitude for p in request.positions
             if p.active and p.owner == person_id and p.capital_type == "human" and p.role == "income"
             and p.unit == "chf_per_year" and p.magnitude is not None]
    return float(sum(flows)) if flows else None


def _gross(request: LbsRequest, person: LbsPerson) -> Optional[float]:
    if person.stated_gross_income is not None:
        return float(person.stated_gross_income)
    return _owned_income(request, person.person_id)


def _capitals(sheet: LbsSheet, person_id: str) -> tuple[Optional[float], Optional[float], Optional[float],
                                                           tuple[str, ...]]:
    for hc in sheet.human_capital:
        if hc.person_id == person_id:
            return hc.E.value, hc.N.value, hc.H.value, tuple(hc.caveats)
    return None, None, None, ()


def deposit(records: dict[str, dict[str, Any]], price: float, occupancy: Optional[str]) -> tuple[float, bool]:
    """lbs's ``property.mandate_target``: the deposit, never the price; unknown occupancy takes the strictest.
    Returns ``(deposit, occupancy_assumed)``."""
    known = {k: r for k, r in records["property-funding"]["occupancy"].items() if isinstance(r, dict)}
    if occupancy in known:
        return float(price) * float(known[occupancy]["equity_min"]), False
    strictest = max(known, key=lambda key: float(known[key]["equity_min"]))
    return float(price) * float(known[strictest]["equity_min"]), True


def adapt(sheet: LbsSheet, request: LbsRequest, lbs_records: dict[str, dict[str, Any]],
          calibration: Calibration) -> Adapted:
    """The draft's submission for this sheet, under this calibration."""
    if request.client_ref != sheet.client_ref:
        raise AdapterError("the sheet and the request it was read with belong to different clients")
    if request.household is None or not any(p.kind == "adult" for p in request.household.persons):
        raise AdapterError("the sheet states no household, so there is nobody the plan is for")
    household = request.household
    adults = [p for p in household.persons if p.kind == "adult"]
    principal = next((p for p in adults if p.person_id == household.principal), adults[0])
    partner = next((p for p in adults if p.person_id != principal.person_id), None)
    dependants = [p for p in household.persons if p.kind == "dependant"]
    behaviour = calibration.behaviour
    hc_record = lbs_records["human-capital"]

    assumptions: dict[str, Optional[float]] = {}
    missing: dict[str, tuple[str, ...]] = {}
    as_of = sheet.as_of
    year_now = as_of.year

    # -- inflation (LBSIM-08)
    inflation = 0.0
    if behaviour.inflation == "sheet":
        if sheet.real_view is None:
            raise AdapterError("the sheet carries no real view, so the sheet's inflation cannot be read; it was "
                               "built under an lbs calibration before 1.4.0")
        if sheet.real_view.currency not in behaviour.currencies:
            raise AdapterError(f"the sheet is in {sheet.real_view.currency}; lbsim computes in CHF only")
        inflation = float(sheet.real_view.inflation.annual_rate)
        assumptions["inflation"] = inflation

    # -- the adults
    adult_inputs: dict[str, AdultInputs] = {}
    for p in adults:
        E, N, H, cav = _capitals(sheet, p.person_id)
        adult_inputs[p.person_id] = AdultInputs(p, E, N, H, cav, _gross(request, p))
    me = adult_inputs[principal.person_id]
    age = principal.age

    # -- the balance sheet
    W_L = _vessel(sheet, "free")
    W_P = _vessel(sheet, "pillar_2")
    W_3a = _vessel(sheet, "pillar_3a")
    W_R = _vessel(sheet, "real_asset")
    facts = request.facts
    if facts.own_use_share is not None:
        W_res = float(facts.own_use_share) * W_R
        raw_own_use = float(facts.own_use_share) * 100.0
    else:
        W_res = W_R
        if W_R > 0:
            assumptions["residence_is_all_property"] = W_R
    debt_known = sheet.totals.liabilities is not None or facts.has_no_liabilities
    D = float(sheet.totals.liabilities or 0.0)
    if not debt_known:
        for code in ("thin_liquidity", "rate_not_recorded", "debt_service_equals_spending"):
            missing[code] = ("mortgage",)

    state: dict[str, Any] = {"age": age, "W_L": W_L, "W_R": W_R, "W_res": W_res, "W_hol": 0.0, "D": D,
                             "W_P": W_P, "W_3a": W_3a, "H": me.H, "N": me.N, "E": me.E}
    if me.E is None or me.N is None:
        assumptions["capitals_mid_scale"] = 0.5

    params: dict[str, Any] = {"swr": calibration.retirement.withdrawal_rate, "epsilon":
                              round(1.0 - calibration.optimiser.confidence, 12)}
    params.update(calibration.params)
    raw: dict[str, Any] = {"canton": facts.canton, "civil_status": facts.civil_status}
    if facts.own_use_share is not None:
        raw["own_use_pct"] = raw_own_use
    if age is not None:
        raw["birth_year"] = year_now - int(age)
    lbsim_block: dict[str, Any] = {"inflation": inflation, "unstated_stop_age_is_reference_age": True}
    if behaviour.income_paths is not None:
        lbsim_block["income_paths"] = behaviour.income_paths
    if behaviour.income_levels is not None:
        lbsim_block["income_levels"] = behaviour.income_levels

    # -- earning power (LBSIM-11)
    if behaviour.earning_power == "record":
        params["earning_power_at_unit"] = _earning.at_unit(hc_record)
        ep = principal.earning_power
        qualification = principal.human_capital.qualification_highest
        tier = _earning.responsibility(hc_record, ep.responsibility if ep else None,
                                       qualification=qualification, sector=ep.sector if ep else None)
        lbsim_block["model_level_factor"] = tier.multiplier * _earning.full_time_share(hc_record)

    # -- income, hours, spending
    gross = me.gross_income
    if gross is not None:
        raw["income_gross"] = gross
    if principal.human_capital.hours_per_week is not None:
        raw["hours_per_week"] = float(principal.human_capital.hours_per_week)
        raw["hours_is_fulltime"] = None
    spend_now = request.risk.spend_now_per_year
    if spend_now is not None:
        raw["spend_now"] = float(spend_now)
    if request.mandate is not None and request.mandate.annual_contribution is not None:
        raw["savings"] = float(request.mandate.annual_contribution)
    ep = principal.earning_power
    if ep is not None:
        if ep.expected_full_pensum_income is not None:
            raw["income_expected_full"] = float(ep.expected_full_pensum_income)
        if ep.education_status in ("in_progress", "planned") and ep.education_end_year is not None:
            raw["education_planned"] = str(int(ep.education_end_year))
        educating = ep.education_status in ("in_progress", "planned")
        if behaviour.income_levels == "stated" and not educating:
            # P-25: without an education under way or planned there is no education path (the draft's rule for a
            # household with no study hours), whatever hours or budget were left in the answers.
            pass
        elif isinstance(ep.education_hours, str):
            raw["education_hours"] = ep.education_hours
        elif ep.education_hours is not None:
            raw["education_hours_num"] = float(ep.education_hours)
        if ep.education_budget_per_year is not None and (behaviour.income_levels != "stated" or educating):
            raw["education_budget"] = float(ep.education_budget_per_year)
    if "income_expected_full" not in raw:
        assumptions["earning_level"] = None

    # -- the mortgage
    risk = request.risk
    if risk.mortgage_rate_pct is not None:
        params["mortgage_rate"] = float(risk.mortgage_rate_pct) / 100.0
        raw["mortgage_rate"] = float(risk.mortgage_rate_pct)
    elif D > 0:
        assumptions["mortgage_rate"] = None
    if facts.amortisation_mode is not None:
        raw["amortisation_mode"] = "indirekt" if facts.amortisation_mode == "indirect" else "direkt"
    elif D > 0:
        missing["indirect_amortisation"] = ("amortisation_mode",)
    if risk.amortisation_per_year is not None:
        if facts.amortisation_mode == "indirect":
            params["amortisation_indirect"] = float(risk.amortisation_per_year)
        else:
            params["p_A"] = float(risk.amortisation_per_year)
    if facts.mortgage_fixed_until is not None:
        raw["mortgage_fixed_until"] = int(facts.mortgage_fixed_until.year)
    elif D > 0:
        missing["rate_reset_near"] = ("mortgage_fixed_until",)

    # -- pillar 3a (the M73 default: no contribution, stated as an assumption)
    if facts.pillar3a_contribution_per_year is not None:
        params["pillar3a_contribution"] = float(facts.pillar3a_contribution_per_year)
        raw["pillar3a_contribution"] = float(facts.pillar3a_contribution_per_year)
    else:
        assumptions["pillar3a_contribution"] = 0.0
        if W_3a <= 0:
            missing["empty_pillar3a"] = ("pillar3a_contribution",)
    raw["pillar3a"] = W_3a
    raw["pillar2"] = W_P

    # -- the other facts
    if facts.stop_work_age is not None:
        params["stop_work_age"] = float(facts.stop_work_age)
        raw["stop_work_age"] = float(facts.stop_work_age)
    if facts.legal_documents is not None:
        raw["legal_docs"] = list(facts.legal_documents)
    else:
        missing["no_legal_documents"] = ("legal_documents",)
    if facts.civil_status is None:
        missing["unmarried_tax_overstated"] = ("civil_status",)
    missing["own_share_only"] = ("asset_scope",)
    if principal.human_capital.hours_per_week is None:
        missing["hours_above_threshold"] = ("hours_per_week",)
    if gross is None or spend_now is None:
        missing["undirected_surplus"] = tuple(k for k, v in (("income_gross", gross), ("spend_now", spend_now))
                                              if v is None)
    if gross is None:
        missing["pension_too_small"] = ("income_gross",)
    if principal.ahv.contribution_years_missing is not None:
        params["ahv_record_share"] = max(0.0, 1.0 - principal.ahv.contribution_years_missing
                                         / AHV_FULL_RECORD_YEARS)
        raw["ahv_years_missing"] = int(principal.ahv.contribution_years_missing)
    else:
        assumptions["ahv_record"] = 1.0
    unassigned = [p.magnitude for p in request.positions
                  if p.active and p.capital_type == "financial" and p.unit == "chf" and p.stock_kind == "asset"
                  and p.vessel is None and p.magnitude]
    if unassigned:
        raw["unassigned_value"] = float(sum(unassigned))

    # -- the partner and the children
    if partner is not None:
        p_in = adult_inputs[partner.person_id]
        params["has_partner"] = True
        params["partner_income"] = float(p_in.gross_income or 0.0)
        if partner.age is not None and age is not None:
            params["partner_age_offset"] = float(partner.age - age)
        civil = str(facts.civil_status or "")
        if civil.startswith("verheiratet") or civil.startswith("eingetragen"):
            params["tax_split_factor"] = 2.0
    if dependants and age is not None:
        ages = [float(d.age) for d in dependants if d.age is not None]
        if ages:
            params["child_ages"] = ages
            params["child_reference_age"] = float(age)
            params["child_household_is_couple"] = partner is not None
            raw["children_count"] = len(ages)
            assumptions["child_costs"] = None

    # -- the goals
    views = {g.goal_id: g for g in (sheet.real_view.goals if sheet.real_view else ())}
    designated = request.mandate.goal_id if request.mandate else None
    ordered = sorted(request.goals, key=lambda g: (g.goal_id != designated,
                                                   g.target_date or as_of.replace(year=as_of.year + 200)))
    goals: list[dict[str, Any]] = []
    goal_ids: list[str] = []
    goal_amounts: dict[str, dict[str, Any]] = {}
    retirement_real: Optional[float] = None
    for g in ordered:
        view = views.get(g.goal_id)
        year = g.target_date.year if g.target_date else None
        nominal = real = None
        if g.target_amount is not None:
            if inflation and view is not None and view.nominal.amount is not None:
                nominal = float(view.nominal.amount)
                real = float(view.real.amount) if view.real.amount is not None else None
            else:
                nominal = real = float(g.target_amount)
        entry: dict[str, Any] = {"description": g.goal_id, "target_year": year, "confidence":
                                 calibration.optimiser.confidence, "is_consumption": False}
        if g.kind == "property":
            entry["kind"] = "home"
            if nominal is not None:
                amount, assumed = deposit(lbs_records, nominal, g.occupancy)
                entry["amount_chf"] = amount
                goal_amounts[g.goal_id] = {"nominal": amount,
                                           "real": deposit(lbs_records, real, g.occupancy)[0]
                                           if real is not None else None,
                                           "basis": view.amount_basis if view else "today", "measure":
                                           "deposit_eligible", "occupancy_assumed": assumed}
        elif g.kind == "retirement":
            entry["kind"] = "retirement"
            if real is not None:
                entry["amount_chf"] = real
                entry["amount_real_chf"] = real
                retirement_real = real if retirement_real is None else retirement_real
                goal_amounts[g.goal_id] = {"nominal": nominal, "real": real, "unit": "chf_per_year",
                                           "basis": view.amount_basis if view else "today",
                                           "measure": "retirement_capital"}
        else:
            if nominal is not None and year is not None:
                entry["kind"] = "capital"
                entry["amount_chf"] = nominal
                goal_amounts[g.goal_id] = {"nominal": nominal, "real": real,
                                           "basis": view.amount_basis if view else "today", "measure": "drawable"}
            else:
                entry["kind"] = "other"
                entry["amount_chf"] = nominal
        goals.append(entry)
        goal_ids.append(g.goal_id)
    if not goals:
        missing["goal_not_computed"] = ("goals",)
    if retirement_real is not None:
        params["G"] = retirement_real
        raw["spend_later"] = retirement_real
    elif spend_now is not None:
        params["G"] = float(spend_now)
        assumptions["spending"] = float(spend_now)
    if retirement_real is None:
        missing["spending_doubling"] = ("spend_later",)
        if facts.stop_work_age is None:
            missing["stop_age_missing"] = ("goals",)
    elif facts.stop_work_age is None and age is not None:
        # The draft reads an early exit from free text; lbs states a dated retirement goal instead.
        ret = next(g for g in ordered if g.kind == "retirement" and g.target_amount is not None)
        if ret.target_date is not None and ret.target_date.year - year_now + age < 65:
            raw["work_plan"] = "frühpension"

    submission = {
        "schema_version": SCHEMA_VERSION,
        "meta": {"collected": as_of.isoformat(), "source": "lbsim.adapter"},
        "state": state,
        "params": params,
        "goals": goals,
        "asks": [],
        "derived_notes": [],
        "pending_fields": [],
        "raw": {k: v for k, v in raw.items() if v is not None},
        "lbsim": lbsim_block,
    }
    return Adapted(submission=submission, principal=principal.person_id,
                   partner=partner.person_id if partner else None, adults=adult_inputs,
                   assumptions=assumptions, missing=missing, goal_ids=goal_ids,
                   goal_dates={g.goal_id: g.target_date for g in request.goals}, goal_amounts=goal_amounts,
                   inflation=inflation, debt_known=debt_known)


def pensum(hours: Optional[float]) -> Optional[float]:
    """The draft's reading: hours over the 42-hour Swiss full-time week, clamped to 0.05..1.5."""
    if hours is None or hours <= 0:
        return None
    return max(0.05, min(1.5, float(hours) / FULL_TIME_HOURS))


def log_rate(annual: float) -> float:
    return math.log1p(annual)
