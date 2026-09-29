"""The pure engine: unit tests for every rule the prototype kept, and hypothesis property tests.

No store, no HTTP. Each test names the prototype rule or the decision it holds.
"""

from __future__ import annotations

import ast
import json
import math
from datetime import date
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import ValidationError

from lbs import engine
from lbs.calibration import SEED, calibration_hash, with_approved
from lbs.contracts import (
    PCP_BOUND_SOURCE,
    Calibration,
    LifeBalanceSheetRequest,
    MandateProposal,
    NotAvailable,
    ProposedBound,
)
from lbs.service import build_sheet, idempotency_key

from .conftest import APPROVED, CORRECTED, CORRECTED_1_3, sample_request

SRC = Path(__file__).resolve().parents[1] / "src" / "lbs"


def sheet(body: dict, cal: Calibration = SEED):
    return build_sheet(LifeBalanceSheetRequest.model_validate(body), cal)


def gaps_of(s, section: str | None = None):
    return [g for g in s.gaps if section is None or g.section.startswith(section)]


# ===========================================================================
# The contract
# ===========================================================================

@pytest.mark.parametrize("ref", ["Hans Muster", "hans@example.ch", "", "x" * 65])
def test_a_name_or_an_email_is_refused_as_a_client_ref(ref):
    with pytest.raises(ValidationError, match="opaque reference"):
        LifeBalanceSheetRequest.model_validate(sample_request(client_ref=ref))


def test_growth_is_read_as_gain_at_the_boundary():
    """LBS-05: the prototype stored ``growth``; pcp and the Manual call the role Gain."""
    req = LifeBalanceSheetRequest.model_validate(sample_request())
    assert {p.position_id: p.role for p in req.positions}["depot"] == "gain"


@pytest.mark.parametrize("change,message", [
    ({"magnitude": -5.0}, "never negative"),
    ({"stock_kind": None}, "exactly when the unit is chf"),
    ({"unit": None}, "a magnitude has a unit"),
    ({"unit": "chf_per_year"}, "exactly when the unit is chf"),
])
def test_a_stock_has_one_representation(change, message):
    body = sample_request()
    body["positions"][0] = {**body["positions"][0], **change}
    with pytest.raises(ValidationError, match=message):
        LifeBalanceSheetRequest.model_validate(body)


def test_stating_no_debt_and_a_debt_is_a_contradiction():
    body = sample_request(facts={"has_no_liabilities": True})
    with pytest.raises(ValidationError, match="contradicts"):
        LifeBalanceSheetRequest.model_validate(body)


@pytest.mark.parametrize("field,value,message", [
    ("owner", "p9", "not in the household"),
    ("funds_goals", ["nowhere"], "not in the request"),
])
def test_references_must_resolve(field, value, message):
    body = sample_request()
    body["positions"][0] = {**body["positions"][0], field: value}
    with pytest.raises(ValidationError, match=message):
        LifeBalanceSheetRequest.model_validate(body)


def test_a_household_without_an_adult_is_refused():
    body = sample_request()
    body["household"]["persons"][0]["kind"] = "dependant"
    with pytest.raises(ValidationError, match="no adult"):
        LifeBalanceSheetRequest.model_validate(body)


# ===========================================================================
# Approval gates
# ===========================================================================

def test_the_seed_carries_the_prototype_approval_state():
    state = {name: engine.approved(record) for name, record in SEED.records.items()}
    assert state == {"ahv-pension": False, "bvg-projection": True, "human-capital": True,
                     "property-funding": True, "liquidity-levers": True, "risk-profile": False,
                     "intake-scales": False, "roles": False, "currency-horizons": True}


def test_an_unapproved_record_is_a_reason_and_never_a_number():
    s = sheet(sample_request())
    ahv = s.pensions[0].ahv
    assert isinstance(ahv, NotAvailable) and ahv.record == "ahv-pension"
    assert "record not approved" in ahv.reason
    assert isinstance(s.risk_profile, NotAvailable) and s.risk_profile.record == "risk-profile"
    assert s.retirement[0].ahv is None and "the_ahv_table_is_not_approved" in s.retirement[0].undetermined_because
    kinds = {(g.input, g.kind) for g in s.gaps}
    assert ("ahv", "record_not_approved") in kinds and ("risk-profile", "record_not_approved") in kinds


def test_a_record_not_provisional_but_unsigned_still_refuses():
    records = json.loads(json.dumps(SEED.records))
    records["bvg-projection"]["_about"]["published_by"] = None
    cal = Calibration.model_validate({**SEED.model_dump(), "version": "1.0.1", "records": records})
    assert isinstance(sheet(sample_request(), cal).pensions[0].bvg, NotAvailable)


def test_approving_is_a_new_version_and_changes_the_hash():
    assert APPROVED.version != SEED.version and calibration_hash(APPROVED) != calibration_hash(SEED)
    s = sheet(sample_request(), APPROVED)
    assert not isinstance(s.pensions[0].ahv, NotAvailable)
    assert s.pensions[0].ahv.basis == "current_income_as_a_stand_in_for_the_lifetime_average"
    assert s.pensions[0].ahv.caveats[0] == "current_income_was_used_where_a_lifetime_average_belongs"


def test_provenance_names_every_record_read_and_its_state():
    s = sheet(sample_request())
    uses = {u.record: u for u in s.provenance.records}
    assert not uses["ahv-pension"].approved and uses["bvg-projection"].approved
    assert uses["intake-scales"].read_without_gate and uses["human-capital"].read_without_gate


# ===========================================================================
# The balance sheet
# ===========================================================================

def test_net_worth_is_assets_less_liabilities():
    s = sheet(sample_request())
    t = s.totals
    assert t.financial_assets == 350_000 and t.liabilities == 20_000 and t.net_worth == 330_000
    assert t.identity_holds and t.drawable == 200_000
    assert t.by_vessel == {"free": 200_000, "pillar_2": 150_000, "pillar_3a": None, "real_asset": None,
                           "not_stated": None}


def test_no_liability_stated_leaves_net_worth_open_rather_than_zero():
    body = sample_request()
    body["positions"] = [p for p in body["positions"] if p["position_id"] != "loan"]
    t = sheet(body).totals
    assert t.liabilities is None and t.net_worth is None and t.identity_holds is None
    assert any(g.input == "liabilities" for g in sheet(body).gaps)
    body["facts"] = {"has_no_liabilities": True}
    assert sheet(body).totals.net_worth == 350_000


def test_a_flow_is_never_a_stock():
    """``chf`` is a prefix of ``chf_per_year``: the salary never lands in wealth (the prototype's A105)."""
    t = sheet(sample_request()).totals
    assert t.human_assets is None and t.household_income == 120_000


def test_the_grid_has_eight_cells_and_no_count():
    s = sheet(sample_request())
    assert [(c.role, c.capital_type) for c in s.grid] == [
        (r, k) for r in ("gain", "income", "stabilisation", "protection") for k in ("human", "financial")]
    cell = next(c for c in s.grid if c.role == "stabilisation" and c.capital_type == "financial")
    assert cell.assets_chf == 80_000 and cell.liabilities_chf == 20_000 and cell.display == "Stabilisation"
    assert next(c for c in s.grid if c.role == "gain" and c.capital_type == "financial").display == "Gain"
    assert next(c for c in s.grid if c.role == "gain" and c.capital_type == "human").display == "Growth"
    assert "filled" not in json.dumps(s.model_dump(mode="json")["grid"])


def test_an_unstated_household_is_a_gap_and_not_a_single_person():
    body = sample_request(household=None)
    body["positions"] = [{**p, "owner": None} for p in body["positions"]]
    body["goals"] = [{**g, "owners": []} for g in body["goals"]]
    s = sheet(body)
    assert not s.household.stated and s.human_capital == () and s.pensions == ()
    assert any(g.section == "household" and g.input == "household" for g in s.gaps)


def test_a_composition_past_its_horizon_degrades_what_rests_on_it():
    body = sample_request(as_of="2027-07-01")
    s = sheet(body)
    assert s.household.currency.expired and s.household.currency.expires_on == date(2027, 6, 1)
    assert s.property[0].verdict == "could_not_be_determined"
    assert "the_household_composition_is_past_its_validity_horizon" in s.property[0].undetermined_because
    assert any(g.kind == "past_its_validity_horizon" for g in s.gaps)


def test_a_composition_is_valid_on_the_day_it_expires():
    assert not sheet(sample_request(as_of="2027-06-01")).household.currency.expired


def test_two_adults_need_both_incomes_for_a_household_income():
    """LBS-14: the prototype returned None for every couple; lbs sums when every adult owns an income."""
    body = sample_request()
    body["household"]["persons"].append({"person_id": "p2", "kind": "adult", "age": 38})
    t = sheet(body).totals
    assert t.household_income is None and t.household_income_basis == "not_known_for_every_adult"
    body["positions"].append({"position_id": "salary2", "role": "income", "capital_type": "human",
                              "magnitude": 50_000, "unit": "chf_per_year", "owner": "p2"})
    t = sheet(body).totals
    assert t.household_income == 170_000 and t.household_income_basis == "income_positions_of_every_adult"


# ===========================================================================
# Human capital
# ===========================================================================

def test_capitals_absent_are_dropped_never_zero():
    body = sample_request()
    body["household"]["persons"][0]["human_capital"] = {"health_withheld": True}
    hc = sheet(body).human_capital[0]
    assert hc.E.value is None and hc.E.absent_because == engine.NOT_ASKED
    assert hc.N.value is None and hc.N.absent_because == engine.NOT_ANSWERED
    assert hc.H.value is None and hc.H.absent_because == engine.WITHHELD
    assert any("overstated" in c for c in hc.caveats)


def test_earning_power_belongs_to_lbsim():
    """LBS-10: the owner assigned personal_alm to lbsim."""
    s = sheet(sample_request())
    assert isinstance(s.human_capital[0].earning_power, NotAvailable)
    assert any(g.kind == "owned_by_another_engine" and g.input == "earning_power" for g in s.gaps)


def test_the_ladder_decays_and_ongoing_training_clears_it():
    rec, scales = SEED.records["human-capital"], SEED.records["intake-scales"]
    old = engine.expertise({"qualification_highest": "Berufsausbildung (EFZ)", "qualification_year": 2000}, rec, 2026)
    fresh = engine.expertise({"qualification_highest": "Berufsausbildung (EFZ)", "qualification_year": 2000,
                              "education_recent": "CAS Digital"}, rec, 2026)
    nein = engine.expertise({"qualification_highest": "Berufsausbildung (EFZ)", "qualification_year": 2000,
                             "education_recent": "nein"}, rec, 2026)
    assert old.value == pytest.approx(0.6309 - 0.105) and fresh.value == 0.6309 and nein.value == old.value
    assert engine.network({"network_people": 8}, rec, scales).value == 0.63


# ===========================================================================
# Pensions
# ===========================================================================

@pytest.mark.parametrize("mdje,monthly", [(0, 1260), (15_120, 1260), (15_121, 1293), (10**7, 2520)])
def test_the_skala_44_rows_are_upper_bounds(mdje, monthly):
    assert engine.ahv_full_monthly(SEED.records["ahv-pension"], mdje) == monthly


def test_a_missing_contribution_year_costs_one_forty_fourth():
    rec = SEED.records["ahv-pension"]
    full = engine.ahv_pension(rec, 80_000, 44)
    one = engine.ahv_pension(rec, 80_000, 43)
    assert one.monthly == pytest.approx(full.monthly * 43 / 44) and one.yearly == one.monthly * 13


@pytest.mark.parametrize("age,rate", [(24, 0), (25, 0.07), (34, 0.07), (35, 0.10), (45, 0.15), (55, 0.18),
                                      (65, 0.18), (66, 0)])
def test_the_credit_rate_steps_where_article_16_says(age, rate):
    assert engine.bvg_credit_rate(SEED.records["bvg-projection"], age) == rate


def test_a_salary_below_the_threshold_is_none_and_not_zero():
    rec = SEED.records["bvg-projection"]
    assert engine.bvg_coordinated_salary(rec, 22_680) is None
    assert engine.bvg_coordinated_salary(rec, 30_000) == 3_780
    assert engine.bvg_coordinated_salary(rec, 200_000) == 90_720 - 26_460


def test_the_couple_cap_binds_at_150_percent():
    c = engine.ahv_couple(SEED.records["ahv-pension"], 2_520, 2_520)
    assert c.cap == 3_780 and c.cap_binds and c.lost_to_the_cap_monthly == 1_260 and c.yearly == 3_780 * 13


# ===========================================================================
# Property, liquidity, retirement
# ===========================================================================

def test_pension_capital_may_not_fund_a_holiday_home():
    body = sample_request()
    body["goals"][0]["occupancy"] = "second_or_holiday_home"
    body["positions"][2]["funds_goals"] = ["home"]
    p = sheet(body).property[0]
    assert p.equity["pillar2_may_fund"] is False and p.ineligible_funding[0]["kind"] == "pillar_2"


def test_a_let_property_reports_affordability_as_undeterminable():
    body = sample_request()
    body["goals"][0]["occupancy"] = "let_to_someone_else"
    p = sheet(body).property[0]
    assert p.affordability is None and "rental_income_is_not_modelled_for_a_let_property" in p.undetermined_because


def test_unlinked_funding_is_undetermined_and_not_a_shortfall():
    body = sample_request()
    body["positions"] = [{**p, "funds_goals": []} for p in body["positions"]]
    p = sheet(body).property[0]
    assert p.equity["verdict"] == "could_not_be_determined"
    assert "no_position_is_linked_to_this_goal" in p.undetermined_because


def test_an_undeclared_occupancy_is_named():
    body = sample_request()
    body["goals"][0]["occupancy"] = "castle"
    p = sheet(body).property[0]
    assert p.undetermined_because == ("the_goal_names_an_occupancy_the_record_does_not_declare",)


def test_an_illiquid_dated_goal_is_short_with_one_prepared_option():
    body = sample_request()
    body["positions"].append({"position_id": "art", "role": "stabilisation", "capital_type": "financial",
                              "magnitude": 45_000, "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid",
                              "vessel": "real_asset", "owner": "p1", "funds_goals": ["later"]})
    f = sheet(body).liquidity
    assert len(f) == 1 and f[0].gap_chf == 45_000 and f[0].prepared["lever"] == "add_a_monthly_contribution"
    body["goals"][1]["target_date"] = "2026-01-01"
    assert sheet(body).liquidity[0].prepared["lever"] == "reduce_the_goal_size"


def test_a_flow_never_counts_as_an_illiquid_balance():
    """``chf`` is a prefix of ``chf_per_year``: a yearly flow marked illiquid is not part of the gap."""
    body = sample_request()
    body["positions"] += [
        {"position_id": "art", "role": "stabilisation", "capital_type": "financial", "magnitude": 45_000,
         "unit": "chf", "stock_kind": "asset", "liquidity": "illiquid", "vessel": "real_asset", "owner": "p1",
         "funds_goals": ["later"]},
        {"position_id": "rent", "role": "stabilisation", "capital_type": "financial", "magnitude": 12_000,
         "unit": "chf_per_year", "liquidity": "illiquid", "owner": "p1", "funds_goals": ["later"]}]
    f = sheet(body).liquidity
    assert f[0].gap_chf == 45_000 and set(f[0].position_ids) == {"art", "rent"}


def test_the_retirement_finding_counts_the_approved_pillars():
    s = sheet(sample_request(), APPROVED)
    r = s.retirement[0]
    assert r.verdict in ("meets", "does_not_meet") and r.covered_per_year == pytest.approx(
        r.ahv["yearly"] + r.pillar2["yearly"])


# ===========================================================================
# The mandate proposal
# ===========================================================================

def test_the_mandate_funds_the_deposit_not_the_price():
    m = sheet(sample_request()).mandate_proposal
    assert m.target_chf == 200_000 and "deposit" in m.target_basis
    assert m.required_return == 0.0 and m.feasible  # 200'000 drawable already holds the deposit


def test_the_curve_is_the_policy_ramp_levelled_on_the_required_return():
    body = sample_request(mandate={"goal_id": "home", "annual_contribution": 0})
    body["goals"][0]["target_amount"] = 1_600_000  # deposit 320'000 against 200'000 drawable
    m = sheet(body).mandate_proposal
    r = m.required_return
    assert r is not None and r > 0
    decimal = [math.expm1(v) for v in m.target_curve]
    assert decimal[0] == pytest.approx(r - 0.025) and decimal[-1] == pytest.approx(r + 0.025)
    assert sum(decimal) / 25 == pytest.approx(r, abs=1e-12)
    assert all(b > a for a, b in zip(m.target_curve, m.target_curve[1:]))
    assert m.curve_shape["source"] == "policy"


def test_only_derived_dimensions_are_proposed_and_policy_is_left_to_the_curator():
    m = sheet(sample_request()).mandate_proposal
    assert set(m.bounds) == {"currency", "liquidity"} and set(m.bound_sources.values()) == {"derived"}
    assert all(PCP_BOUND_SOURCE[d] == "derived" for d in m.bounds)
    left = {c.field for c in m.curator_to_fill}
    assert {"universe", "max_single_position", "regime_weights", "bounds.role", "esg_min"} <= left
    assert m.complete is False and m.release_state == "unreleased"
    with pytest.raises(ValidationError, match="policy"):
        MandateProposal.model_validate({**m.model_dump(), "bounds": {
            "region": {"Europe": ProposedBound(lower=0, upper=1, reasoning="x")}}, "bound_sources": {}})


def test_an_approved_risk_profile_fills_the_role_bounds_and_the_slope():
    m = sheet(sample_request(), APPROVED).mandate_proposal
    assert set(m.bounds["role"]) == {"Protection", "Stabilisation", "Income", "Gain"}
    assert m.curve_shape["source"] == "risk-profile" and m.esg_min == 0.0
    assert "bounds.role" not in {c.field for c in m.curator_to_fill}


@pytest.mark.parametrize("years,expected", [(1.5, {"Daily": (0.6, 1.0), "Decade": (0.0, 0.0)}),
                                            (4.0, {"Daily": (0.3, 1.0), "Decade": (0.0, 0.1)}),
                                            (10.0, {"Daily": (0.1, 1.0)}), (20.0, None)])
def test_the_deadline_ladder(years, expected):
    target = date.fromordinal(date(2026, 9, 28).toordinal() + round(years * 365.2425))
    body = sample_request()
    body["goals"][0]["target_date"] = target.isoformat()
    m = sheet(body).mandate_proposal
    got = {k: (b.lower, b.upper) for k, b in m.bounds.get("liquidity", {}).items()} or None
    assert got == expected


def test_a_missing_contribution_is_a_gap_and_no_curve():
    m = sheet(sample_request(mandate={"goal_id": "home"})).mandate_proposal
    assert m.required_return is None and m.target_curve is None
    assert "target_curve" in {c.field for c in m.curator_to_fill}


def test_a_retirement_goal_needs_an_unpublished_withdrawal_rate():
    s = sheet(sample_request(mandate={"goal_id": "later", "annual_contribution": 10_000}))
    assert s.mandate_proposal.target_chf is None
    assert any(g.kind == "needs_an_unpublished_assumption" for g in s.gaps)


def test_an_unreachable_goal_is_infeasible_and_says_why():
    body = sample_request(mandate={"goal_id": "home", "annual_contribution": 0})
    body["goals"][0]["target_date"] = "2027-01-31"
    body["goals"][0]["target_amount"] = 50_000_000
    m = sheet(body).mandate_proposal
    assert m.feasible is False and m.required_return is None and m.target_curve is None


def test_no_designated_goal_is_not_available():
    assert isinstance(sheet(sample_request(mandate=None)).mandate_proposal, NotAvailable)


# ===========================================================================
# Purity and determinism
# ===========================================================================

def test_the_engine_reads_no_clock_and_does_no_io():
    tree = ast.parse((SRC / "engine.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "open" not in names and not {"today", "now", "utcnow"} & attrs
    assert not {"time", "random", "os", "pathlib", "httpx", "psycopg"} & (imports | modules)


def test_the_same_request_gives_the_same_bytes():
    a, b = sheet(sample_request()), sheet(sample_request())
    assert a.model_dump_json() == b.model_dump_json() and a.artefact_id == b.artefact_id


def test_the_key_moves_with_the_request_and_the_calibration():
    req = LifeBalanceSheetRequest.model_validate(sample_request())
    other = LifeBalanceSheetRequest.model_validate(sample_request(as_of="2026-09-29"))
    assert idempotency_key(req, SEED) != idempotency_key(other, SEED) != idempotency_key(req, APPROVED)
    named = LifeBalanceSheetRequest.model_validate(sample_request(calibration_version="1.0.0"))
    assert idempotency_key(req, SEED) == idempotency_key(named, SEED)


# ===========================================================================
# Property tests
# ===========================================================================

stock = st.fixed_dictionaries({
    "role": st.sampled_from(["gain", "growth", "income", "stabilisation", "protection"]),
    "capital_type": st.sampled_from(["human", "financial"]),
    "magnitude": st.floats(min_value=0, max_value=1e8, allow_nan=False),
    "kind": st.sampled_from(["asset", "liability"]),
    "vessel": st.sampled_from(["free", "pillar_2", "pillar_3a", "real_asset", None]),
    "active": st.booleans(),
})


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(stocks=st.lists(stock, max_size=12), no_debt=st.booleans())
def test_the_identity_and_the_grid_hold_for_any_positions(stocks, no_debt):
    positions = []
    for i, s in enumerate(stocks):
        p = {"position_id": f"x{i}", "role": s["role"], "capital_type": s["capital_type"], "magnitude": s["magnitude"],
             "unit": "chf", "stock_kind": s["kind"], "active": s["active"],
             "vessel": s["vessel"] if s["capital_type"] == "financial" else None}
        positions.append(p)
    has_debt = any(p["stock_kind"] == "liability" for p in positions)
    body = {"client_ref": "prop", "as_of": "2026-09-28", "positions": positions,
            "facts": {"has_no_liabilities": no_debt and not has_debt}}
    s = sheet(body)
    t = s.totals
    live = [p for p in positions if p["active"]]
    assets = [p["magnitude"] for p in live if p["stock_kind"] == "asset"]
    debts = [p["magnitude"] for p in live if p["stock_kind"] == "liability"]
    assert t.total_assets == (pytest.approx(sum(assets)) if assets else None)
    grid_assets = sum(c.assets_chf or 0 for c in s.grid)
    assert grid_assets == pytest.approx(sum(assets))
    if t.net_worth is not None:
        assert t.identity_holds and t.net_worth == pytest.approx(t.total_assets - t.liabilities)
    if not debts and not body["facts"]["has_no_liabilities"]:
        assert t.liabilities is None and t.net_worth is None


@settings(max_examples=200, deadline=None)
@given(w=st.floats(0, 2e6), target=st.floats(1, 5e6), years=st.floats(0.1, 40), c=st.floats(0, 2e5))
def test_the_required_return_funds_the_goal_exactly(w, target, years, c):
    steps = max(1, int(round(years * 12)))
    path = [c / 12] * steps
    r = engine.required_return(w, target, path, steps_per_year=12, ceiling=10.0, tolerance=1e-10, max_iterations=200)

    def terminal(annual):
        step = (1 + annual) ** (1 / 12) - 1
        v = w
        for x in path:
            v = v * (1 + step) + x
        return v

    if r is None:
        # Reproduction: the S-curve engine's doubling search tests 1, 2, 4, 8 and stops at 16 > 10, so the
        # effective ceiling is 8 (800 percent), the prototype's (LBS-17); corrected in 1.2.0 (LBS-24).
        assert terminal(8.0) < target
    elif r == 0.0:
        assert terminal(0.0) >= target
    else:
        assert terminal(r) == pytest.approx(target, rel=1e-6)
        more = engine.required_return(w, target, [x + 100 for x in path], steps_per_year=12, ceiling=10.0,
                                      tolerance=1e-10, max_iterations=200)
        assert more is not None and more <= r + 1e-9


@settings(max_examples=200, deadline=None)
@given(a=st.floats(-1e5, 2e5), b=st.floats(-1e5, 2e5))
def test_the_ahv_table_is_monotone_and_bounded(a, b):
    rec = SEED.records["ahv-pension"]
    lo, hi = sorted((a, b))
    x, y = engine.ahv_full_monthly(rec, lo), engine.ahv_full_monthly(rec, hi)
    assert 1260 <= x <= y <= 2520


@settings(max_examples=150, deadline=None)
@given(age=st.integers(18, 70), opening=st.floats(0, 2e6), gross=st.floats(0, 5e5))
def test_the_projection_reconciles_to_its_parts(age, opening, gross):
    res = engine.bvg_project(SEED.records["bvg-projection"], current_age=age, opening_balance=opening,
                             gross_salary=gross)
    assert res.closing_balance == pytest.approx(opening + res.total_credited + res.total_interest)
    assert res.closing_balance >= opening and len(res.years) == max(0, 65 - age)


@settings(max_examples=150, deadline=None)
@given(t=st.floats(0, 1))
def test_the_profile_interpolates_between_signed_anchors(t):
    anchors = SEED.records["risk-profile"]["anchors"]["role_bounds"]
    out = engine.lerp(anchors["cautious"], anchors["aggressive"], t)
    for role in ("Protection", "Gain"):
        lo, hi = sorted((anchors["cautious"][role]["lower"], anchors["aggressive"][role]["lower"]))
        assert lo - 1e-12 <= out[role]["lower"] <= hi + 1e-12
    assert engine.lerp(anchors["cautious"], anchors["aggressive"], 0) is anchors["cautious"]
    assert engine.lerp(anchors["cautious"], anchors["aggressive"], 1) is anchors["aggressive"]


@settings(max_examples=100, deadline=None)
@given(loss=st.one_of(st.none(), st.floats(0, 1)), reserve=st.one_of(st.none(), st.floats(0, 60)),
       crisis=st.sampled_from([None, "alles verkauft", "nachgekauft", "nichts, ich blieb investiert", "anders"]))
def test_the_profile_stays_in_the_unit_interval(loss, reserve, crisis):
    body = sample_request(risk={"stated_loss": loss, "liquidity_reserve_months": reserve, "crisis_behaviour": crisis})
    p = sheet(body, APPROVED).risk_profile
    assert p.value is None or 0 <= p.value <= 1


@settings(max_examples=200, deadline=None)
@given(w=st.floats(0, 2e6), target=st.floats(1, 5e6), years=st.floats(0.1, 40), c=st.floats(0, 2e5))
def test_the_corrected_search_is_bounded_by_its_stated_ceiling(w, target, years, c):
    """LBS-24: no required return exactly when not even the stated ceiling (1000 percent) reaches the goal."""
    steps = max(1, int(round(years * 12)))
    path = [c / 12] * steps
    r = engine.required_return(w, target, path, steps_per_year=12, ceiling=10.0, tolerance=1e-10, max_iterations=200,
                               reach_the_ceiling=True)

    def terminal(annual):
        step = (1 + annual) ** (1 / 12) - 1
        v = w
        for x in path:
            v = v * (1 + step) + x
        return v

    if r is None:
        assert terminal(10.0) < target
    else:
        assert r <= 10.0 and (r == 0.0 or terminal(r) == pytest.approx(target, rel=1e-6))


# ===========================================================================
# The owner's decisions of 29.09.2026 (LBS-23 to LBS-25)
# ===========================================================================

def _content(cal):
    return {name: {k: v for k, v in rec.items() if k != "_about"} for name, rec in cal.records.items()}


def test_the_approval_changes_only_the_about_block():
    """LBS-23: 1.1.0 approves ahv-pension and risk-profile (Nicolas, 29.09.2026); content unchanged."""
    assert _content(APPROVED) == _content(SEED) == _content(CORRECTED)
    for name in ("ahv-pension", "risk-profile"):
        about = APPROVED.records[name]["_about"]
        assert engine.approved(APPROVED.records[name]) and not engine.approved(SEED.records[name])
        assert about["published_by"] == "Nicolas" and about["decided_on"] == "2026-09-29"
        assert about["_approval"].startswith("Approved by Nicolas, 29.09.2026")
        before = {k: v for k, v in SEED.records[name]["_about"].items()
                  if k not in ("provisional", "published_by", "decided_on", "effective_from", "_approval")}
        assert {k: about[k] for k in before} == before
    others = [n for n in SEED.records if n not in ("ahv-pension", "risk-profile")]
    assert all(APPROVED.records[n] == SEED.records[n] for n in others)
    assert (APPROVED.version, APPROVED.parent_version, APPROVED.corrections) == ("1.1.0", "1.0.0", None)
    assert (CORRECTED.version, CORRECTED.parent_version) == ("1.2.0", "1.1.0")


def test_under_the_approval_every_gated_section_computes():
    """AHV per adult, the couple cap, the risk profile, the role bounds and the ESG floor."""
    body = sample_request(facts={"civil_status": "verheiratet"},
                          risk={"stated_loss": 0.3, "esg_level": "mehrheitlich"})
    body["household"]["persons"].append({"person_id": "p2", "kind": "adult", "age": 38})
    body["positions"].append({"position_id": "salary2", "role": "income", "capital_type": "human",
                              "magnitude": 90_000, "unit": "chf_per_year", "owner": "p2"})
    for cal in (APPROVED, CORRECTED):
        s = sheet(body, cal)
        assert all(not isinstance(p.ahv, NotAvailable) for p in s.pensions)
        assert not isinstance(s.couple_cap, NotAvailable) and s.couple_cap.cap == 3_780
        assert not isinstance(s.risk_profile, NotAvailable) and s.risk_profile.value is not None
        m = s.mandate_proposal
        assert set(m.bounds["role"]) == {"Protection", "Stabilisation", "Income", "Gain"} and m.esg_min == 0.6
        assert not {"bounds.role", "esg_min"} & {c.field for c in m.curator_to_fill}
        assert not any(g.kind == "record_not_approved" for g in s.gaps)
    assert isinstance(sheet(body, SEED).couple_cap, NotAvailable)


def test_the_search_reaches_its_stated_ceiling():
    """LBS-24 quirk 1: 10 000 to 95 000 in a year needs 850 percent, above the prototype's effective 800."""
    kw = dict(steps_per_year=12, ceiling=10.0, tolerance=1e-10, max_iterations=200)
    assert engine.required_return(10_000, 95_000, [0.0] * 12, **kw) is None
    assert engine.required_return(10_000, 95_000, [0.0] * 12, reach_the_ceiling=True, **kw) == pytest.approx(8.5)
    assert engine.required_return(10_000, 109_000, [0.0] * 12, reach_the_ceiling=True, **kw) == pytest.approx(9.9)
    assert engine.required_return(10_000, 110_001, [0.0] * 12, reach_the_ceiling=True, **kw) is None
    body = sample_request(mandate={"goal_id": "far", "annual_contribution": 0})
    body["goals"].append({"goal_id": "far", "kind": "other", "target_amount": 1_900_000, "target_date": "2027-09-28"})
    old, new = sheet(body, APPROVED).mandate_proposal, sheet(body, CORRECTED).mandate_proposal
    assert old.required_return is None and old.target_curve is None and not old.feasible
    assert new.required_return == pytest.approx(8.5, rel=1e-6) and new.feasible and len(new.target_curve) == 25


def test_the_capacity_horizon_is_years_to_the_planned_age():
    """LBS-24 quirk 2: no dated goal, plan_until_age 65 at age 40 is 25 years, not 65."""
    body = sample_request(risk={"plan_until_age": 65, "stated_loss": 0.3})
    body["goals"] = [{**g, "target_date": None} for g in body["goals"]]
    old, new = sheet(body, APPROVED).risk_profile, sheet(body, CORRECTED).risk_profile
    assert old.capacity_inputs["horizon_years"] == 65
    assert new.capacity_inputs["horizon_years"] == 25
    assert new.capacity_inputs["sources"]["horizon_years"] == "submission: plan_until_age less the age"
    body["household"]["persons"][0]["age"] = None
    s = sheet(body, CORRECTED)
    assert s.risk_profile.capacity_inputs["horizon_years"] is None
    assert any(g.section == "risk_profile" and g.input == "horizon_years" for g in s.gaps)


def test_a_stated_zero_income_is_zero():
    """LBS-24 quirk 3: an income position of 0 (or a stated gross income of 0) is a stated zero."""
    body = sample_request()
    body["positions"][3]["magnitude"] = 0
    old, new = sheet(body, APPROVED), sheet(body, CORRECTED)
    assert isinstance(old.pensions[0].bvg, NotAvailable) and old.totals.household_income is None
    bvg = new.pensions[0].bvg
    assert not isinstance(bvg, NotAvailable) and bvg.gross_salary == 0 and bvg.coordinated is None
    assert bvg.total_credited == 0 and bvg.closing_balance == pytest.approx(150_000 * 1.0125 ** 25)
    assert new.pensions[0].ahv.full_monthly == 1_260 and new.totals.household_income == 0
    assert new.property[0].affordability["verdict"] == "does_not_meet"
    assert new.property[0].affordability["price_supported_chf"] == 0
    body["positions"] = [p for p in body["positions"] if p["position_id"] != "salary"]
    body["household"]["persons"][0]["stated_gross_income"] = 0
    assert sheet(body, CORRECTED).pensions[0].bvg.gross_salary == 0
    assert isinstance(sheet(body, APPROVED).pensions[0].bvg, NotAvailable)
    body["household"]["persons"][0]["stated_gross_income"] = None
    s = sheet(body, CORRECTED)
    assert isinstance(s.pensions[0].bvg, NotAvailable) and s.totals.household_income is None


def _unvested(amount: float, price: float = 1_000_000) -> dict:
    body = sample_request()
    body["goals"][0]["target_amount"] = price
    body["positions"] = [p for p in body["positions"] if p["position_id"] != "depot"]
    body["positions"].append({"position_id": "savings", "role": "gain", "capital_type": "financial",
                              "magnitude": amount, "unit": "chf", "stock_kind": "asset", "liquidity": "immediate",
                              "owner": "p1", "funds_goals": ["home"]})
    return body


def test_a_stock_without_a_vessel_is_a_gap_and_not_equity():
    """LBS-24 quirk 4: 80 000 free and 150 000 unvested against a 200 000 deposit; the verdict turns on it."""
    body = _unvested(150_000)
    old, new = sheet(body, APPROVED).property[0], sheet(body, CORRECTED).property[0]
    assert old.equity["verdict"] == "meets"
    assert new.equity["verdict"] == "could_not_be_determined"
    assert "a_funding_position_states_no_vessel" in new.undetermined_because
    assert sheet(_unvested(50_000), CORRECTED).property[0].equity["verdict"] == "does_not_meet"
    assert sheet(_unvested(150_000, price=300_000), CORRECTED).property[0].equity["verdict"] == "meets"
    risk = {"stated_loss": 0.5}
    old_rp = sheet({**body, "risk": risk}, APPROVED).risk_profile
    new_rp = sheet({**body, "risk": risk}, CORRECTED).risk_profile
    assert old_rp.capacity_inputs["free_share"] == pytest.approx(230 / 380)
    assert new_rp.capacity_inputs["free_share"] == pytest.approx(80 / 380)
    gaps = sheet({**body, "risk": risk}, CORRECTED).gaps
    assert any(g.section == "risk_profile" and g.input == "vessel" for g in gaps)


def test_the_yearly_contribution_sets_the_required_return_and_the_curve():
    """LBS-25: mandate.annual_contribution (the onboarding's yearly saving) levels the curve; 0 is stated."""
    def m(contribution):
        body = sample_request(mandate={"goal_id": "home", "annual_contribution": contribution})
        body["goals"][0]["target_amount"] = 1_600_000
        return sheet(body, CORRECTED).mandate_proposal
    none, zero, some, more = m(None), m(0), m(6_000), m(12_000)
    assert none.required_return is None and none.target_curve is None
    assert zero.required_return > some.required_return > more.required_return > 0
    assert all(a > b for a, b in zip(some.target_curve, more.target_curve))
    assert more.annual_contribution == 12_000
    assert any("stated yearly saving" in n for n in more.notes)
    body = sample_request(mandate={"goal_id": "home"})
    gaps = [g for g in sheet(body, CORRECTED).gaps if g.input == "annual_contribution"]
    assert len(gaps) == 1 and gaps[0].kind == "not_in_the_request" and "put aside each year" in gaps[0].reason


# ===========================================================================
# The owner's decisions of 29.09.2026, second round (LBS-28 to LBS-30): calibration 1.3.0
# ===========================================================================

def test_1_3_is_1_2_with_three_more_corrections():
    assert (CORRECTED_1_3.version, CORRECTED_1_3.parent_version) == ("1.3.0", "1.2.0")
    assert CORRECTED_1_3.records == CORRECTED.records and CORRECTED_1_3.policy == CORRECTED.policy
    before, after = CORRECTED.corrections.model_dump(), CORRECTED_1_3.corrections.model_dump()
    assert {k for k in after if after[k] != before[k]} == {
        "human_capital_is_never_free_wealth", "zero_mortgage_is_a_stated_zero", "contribution_is_split_by_goal_share"}
    assert all(after.values()) and all(before[k] is None for k in after if after[k] != before[k])
    payload = {**CORRECTED_1_3.model_dump(), "contract_version": "lbs-calibration@1.1.0"}
    with pytest.raises(ValidationError, match="need lbs-calibration@1.2.0"):
        Calibration.model_validate(payload)


def _with_training(amount: float = 150_000) -> dict:
    """80 000 free and 120 000 in a depot fund a 1 200 000 home (deposit 240 000); a training claim in chf is
    human capital and funds the home as well."""
    body = sample_request(risk={"stated_loss": 0.5, "spend_now_per_year": 60_000})
    body["goals"][0]["target_amount"] = 1_200_000
    body["positions"].append({"position_id": "training", "role": "gain", "capital_type": "human",
                              "magnitude": amount, "unit": "chf", "stock_kind": "asset", "owner": "p1",
                              "funds_goals": ["home"]})
    return body


def test_a_human_capital_stock_is_never_free_wealth():
    """LBS-28 (1): a human-capital stock in chf is human capital only: not free wealth for the capacity, not
    equity for the deposit, and never drawable. 1.2.0 counted it as free for the capacity."""
    body = _with_training()
    old, new = sheet(body, CORRECTED), sheet(body, CORRECTED_1_3)
    assert old.risk_profile.capacity_inputs["free_share"] == pytest.approx(350 / 500)
    assert new.risk_profile.capacity_inputs["free_share"] == pytest.approx(200 / 350)
    assert old.risk_profile.capacity_inputs["reserve_months"] == pytest.approx(350_000 / 5_000)
    assert new.risk_profile.capacity_inputs["reserve_months"] == pytest.approx(200_000 / 5_000)
    assert "training" in new.risk_profile.capacity_inputs["sources"]["free_share"]
    assert new.totals.drawable == old.totals.drawable == 200_000 and new.totals.human_assets == 150_000
    assert new.mandate_proposal.drawable_chf == 200_000
    assert old.property[0].equity["verdict"] == "could_not_be_determined"
    assert new.property[0].equity["verdict"] == "does_not_meet"
    assert any(g.input == "training.capital_type" for g in new.gaps)
    assert not any(g.input == "training.vessel" for g in new.gaps)
    body["goals"][0]["target_amount"] = 1_000_000
    assert sheet(body, CORRECTED_1_3).property[0].equity["verdict"] == "meets"


def test_a_stated_mortgage_of_zero_is_paid_off():
    """LBS-28 (2): risk.mortgage 0 is a debt service of 0; only an unstated mortgage is unknown."""
    risk = {"stated_loss": 0.5, "gross_income_per_year": 120_000, "mortgage_rate_pct": 2.0}
    paid = sample_request(risk={**risk, "mortgage": 0})
    old, new = sheet(paid, CORRECTED).risk_profile, sheet(paid, CORRECTED_1_3).risk_profile
    assert old.capacity_inputs["debt_service_share"] is None and "debt_service" in old.capacity["missing"]
    assert new.capacity_inputs["debt_service_share"] == 0 and "debt_service" not in new.capacity["missing"]
    assert new.capacity["components"]["debt_service"]["input"] == 0
    assert new.capacity_inputs["sources"]["debt_service_share"].endswith("paid-off mortgage")
    unknown = sheet(sample_request(risk=risk), CORRECTED_1_3).risk_profile
    assert unknown.capacity_inputs["debt_service_share"] is None and "debt_service" in unknown.capacity["missing"]
    owed = sheet(sample_request(risk={**risk, "mortgage": 300_000}), CORRECTED_1_3).risk_profile
    assert owed.capacity_inputs["debt_service_share"] == pytest.approx(6_000 / 120_000)


def _shares(home=None, later=None, contribution=24_000, price=1_600_000):
    body = sample_request(mandate={"goal_id": "home", "annual_contribution": contribution})
    body["goals"][0]["target_amount"] = price
    for goal, share in zip(body["goals"], (home, later)):
        if share is not None:
            goal["contribution_share"] = share
    return body


def test_the_saving_is_split_by_the_stated_shares():
    """LBS-29: the yearly saving goes to the designated goal in its stated share. 1.2.0 read all of it."""
    whole = sheet(_shares(), CORRECTED).mandate_proposal
    part = sheet(_shares(home=0.5, later=0.5), CORRECTED_1_3).mandate_proposal
    alone = sheet(_shares(contribution=12_000), CORRECTED).mandate_proposal
    assert part.annual_contribution == 12_000 and whole.annual_contribution == 24_000
    assert part.required_return == pytest.approx(alone.required_return, rel=1e-12)
    assert part.required_return > whole.required_return
    assert any("stated share of it, 50.0%" in n for n in part.notes)
    assert not any(g.input == "contribution_share" for g in sheet(_shares(home=0.5), CORRECTED_1_3).gaps)
    ignored = sheet(_shares(home=0.5, later=0.5), CORRECTED).mandate_proposal
    assert ignored.annual_contribution == 24_000 and any("are not read" in n for n in ignored.notes)
    zero = sheet(_shares(home=0.0), CORRECTED_1_3).mandate_proposal
    assert zero.annual_contribution == 0


def test_a_missing_share_is_a_gap_and_the_required_return_a_lower_bound():
    """LBS-29: with other goals in the request and no share for the designated goal, the most it can receive
    is used (the rest the stated shares leave), the required return is a lower bound, and the share is a gap."""
    s = sheet(_shares(later=0.25), CORRECTED_1_3)
    m = s.mandate_proposal
    assert m.annual_contribution == pytest.approx(18_000)
    gaps = [g for g in s.gaps if g.input == "contribution_share"]
    assert len(gaps) == 1 and gaps[0].section == "mandate_proposal" and gaps[0].kind == "not_in_the_request"
    assert "lower bound" in gaps[0].reason and any("lower bounds" in n for n in m.notes)
    stated = sheet(_shares(home=0.75, later=0.25), CORRECTED_1_3).mandate_proposal
    assert m.required_return == pytest.approx(stated.required_return, rel=1e-9)
    assert sheet(_shares(later=1.0), CORRECTED_1_3).mandate_proposal.annual_contribution == 0
    assert not any(g.input == "contribution_share" for g in sheet(_shares(later=1.0), CORRECTED_1_3).gaps)
    only = _shares()
    only["goals"] = only["goals"][:1]
    lone = sheet(only, CORRECTED_1_3)
    assert lone.mandate_proposal.annual_contribution == 24_000
    assert not any(g.input == "contribution_share" for g in lone.gaps)
    none = sheet(_shares(contribution=None), CORRECTED_1_3)
    assert not any(g.input == "contribution_share" for g in none.gaps)


@pytest.mark.parametrize("home,later,ok", [(0.6, 0.4, True), (0.6, 0.41, False), (1.0, None, True),
                                           (1.2, None, False), (-0.1, None, False)])
def test_the_shares_sum_to_at_most_one(home, later, ok):
    body = _shares(home=home, later=later)
    if ok:
        LifeBalanceSheetRequest.model_validate(body)
    else:
        with pytest.raises(ValidationError):
            LifeBalanceSheetRequest.model_validate(body)


# ===========================================================================
# The nominal and real view (owner's decisions of 29.09.2026; LBS-31 to LBS-35): calibration 1.4.0
# ===========================================================================

from lbs.calibration import CORRECTED_1_4  # noqa: E402
from lbs.contracts import RealViewPolicy  # noqa: E402


def _at(rate: float) -> Calibration:
    """1.4.0 with the CHF inflation set to ``rate`` (the design note's worked example uses 2 %)."""
    d = CORRECTED_1_4.model_dump()
    d["real_view"]["inflation"]["CHF"]["annual_rate"] = rate
    return Calibration.model_validate({**d, "version": "1.4.0-test"})


def _worked(amount_basis=None, indexed=None, amount=400_000, date_="2046-09-29", free=150_000, saving=12_000,
            risk=None):
    """The design note's section 4.2: CHF 400 000 in 20 years, 150 000 now, 12 000 a year in monthly steps."""
    goal = {"goal_id": "g", "kind": "other", "target_amount": amount, "target_date": date_}
    if amount_basis is not None:
        goal["amount_basis"] = amount_basis
    mandate = {"goal_id": "g", "annual_contribution": saving}
    if indexed is not None:
        mandate["contribution_indexed"] = indexed
    return sample_request(
        as_of="2026-09-29", goals=[goal], mandate=mandate, facts={"has_no_liabilities": True},
        risk=risk if risk is not None else {"stated_loss": 0.3},
        positions=[{"position_id": "free", "role": "gain", "capital_type": "financial", "magnitude": free,
                    "unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free",
                    "funds_goals": ["g"]}])


def test_the_design_notes_worked_example_to_the_cent():
    """Section 4.2 of the design note: read as future francs the goal needs 0.18 % a year; in today's francs at
    2 % inflation its nominal target is 594 379 and it needs 2.96 % nominal, 0.94 % real (log)."""
    as_future = sheet(_worked(amount_basis="future"), _at(0.02)).mandate_proposal
    assert as_future.target_chf == 400_000
    assert round(as_future.required_return * 100, 2) == 0.18
    s = sheet(_worked(), _at(0.02))
    m = s.mandate_proposal
    assert round(m.target_chf, 2) == 594_378.96 and round(400_000 * 1.02 ** 20, 2) == 594_378.96
    assert round(m.required_return * 100, 2) == 2.96
    assert m.required_return == pytest.approx(0.029610281315, abs=1e-10)
    real = m.views["real"]
    assert real.basis == "real" and real.target_chf == pytest.approx(400_000, abs=0.005)
    assert round(real.required_return_log * 100, 2) == 0.94
    assert real.required_return_log == pytest.approx(math.log1p(m.required_return) - math.log(1.02), abs=1e-15)
    assert real.required_return == pytest.approx((1 + m.required_return) / 1.02 - 1, abs=1e-15)
    nominal = m.views["nominal"]
    assert nominal.basis == "nominal" and nominal.target_chf == m.target_chf
    assert nominal.required_return == m.required_return and m.basis == "nominal"
    # the required return funds the nominal target to the cent
    wealth = engine.terminal_wealth(150_000, [1_000.0] * 240, m.required_return, 12)
    assert abs(wealth - m.target_chf) < 0.01
    view = s.real_view.goals[0]
    assert (view.amount_basis, view.amount_basis_stated) == ("today", False)
    assert view.horizon_years == 20 and view.price_level == pytest.approx(1.02 ** 20, rel=1e-15)
    assert not s.real_view.contribution_indexed and not s.real_view.contribution_indexed_stated
    assert any("decision 7" in n for n in m.notes) and any("decision 9" in n for n in m.notes)


def test_a_missing_basis_is_todays_francs_and_future_francs_keep_the_old_figures():
    """Decision 7: a missing amount_basis reads as today; a stated future basis gives 1.3.0's nominal figures."""
    old = sheet(_worked(), CORRECTED_1_3).mandate_proposal
    future = sheet(_worked(amount_basis="future"), CORRECTED_1_4).mandate_proposal
    today = sheet(_worked(amount_basis="today"), CORRECTED_1_4).mandate_proposal
    unstated = sheet(_worked(), CORRECTED_1_4).mandate_proposal
    assert future.target_chf == old.target_chf and future.required_return == old.required_return
    assert future.target_curve == old.target_curve
    assert unstated.target_chf == today.target_chf == pytest.approx(400_000 * 1.005 ** 20, rel=1e-12)
    assert unstated.required_return == today.required_return > old.required_return
    assert future.views["real"].target_chf == pytest.approx(400_000 / 1.005 ** 20, rel=1e-12)


def test_an_indexed_contribution_holds_the_real_problem_at_its_uninflated_one():
    """Decision 9 and LBS-31: an indexed contribution keeps its purchasing power month by month, so the real
    required return of a goal in today's francs is the one the problem poses without inflation (0.18 % here, at
    any inflation)."""
    uninflated = sheet(_worked(amount_basis="future"), _at(0.0)).mandate_proposal.required_return
    for rate in (0.005, 0.02, 0.10):
        m = sheet(_worked(indexed=True), _at(rate)).mandate_proposal
        assert m.views["real"].required_return == pytest.approx(uninflated, abs=1e-9)
        fixed = sheet(_worked(indexed=False), _at(rate)).mandate_proposal
        assert fixed.views["real"].required_return > m.views["real"].required_return
    s = sheet(_worked(indexed=True), _at(0.02))
    assert s.real_view.contribution_indexed and s.real_view.contribution_indexed_stated


def test_an_undated_goal_has_only_its_stated_basis():
    s = sheet(_worked(date_=None), CORRECTED_1_4)
    view = s.real_view.goals[0]
    assert view.real.amount == 400_000 and view.nominal.amount is None
    assert "undated" in view.nominal.absent_because and view.price_level is None
    future = sheet(_worked(amount_basis="future", date_=None), CORRECTED_1_4).real_view.goals[0]
    assert future.nominal.amount == 400_000 and future.real.amount is None


def test_16_percent_in_a_year_and_a_quarter_is_feasible_and_not_realistic():
    """LBS-34: feasible keeps its narrow meaning (a return below the 1000 % search ceiling exists); the
    plausibility judgement says a portfolio within the risk profile cannot reasonably earn it, and names the
    levers, each computed: each alone reaches the goal at the ceiling."""
    body = _worked(amount_basis="future", amount=125_000, date_="2027-12-29", free=100_000, saving=4_000)
    s = sheet(body, CORRECTED_1_4)
    m = s.mandate_proposal
    assert m.goal_horizon_years == pytest.approx(1.25, abs=0.01) and m.required_return > 0.15 and m.feasible
    p = m.plausibility
    assert p.judgement == "not_realistic" and p.risk_level == s.risk_profile.value
    assert p.ceiling_real == pytest.approx(engine.plausibility_ceiling(engine.Ctx(req=None, cal=CORRECTED_1_4),
                                                                       p.risk_level))
    assert p.ceiling_nominal == pytest.approx((1 + p.ceiling_real) * 1.005 - 1)
    levers = {lever["lever"]: lever for lever in p.levers}
    assert set(levers) == {"longer_horizon", "higher_saving", "smaller_goal"}
    months = 15
    at_ceiling = engine.terminal_wealth(100_000, [levers["higher_saving"]["annual_contribution"] / 12] * months,
                                        p.ceiling_nominal, 12)
    assert at_ceiling == pytest.approx(125_000, rel=1e-9)
    assert levers["smaller_goal"]["target_chf_nominal"] == pytest.approx(
        engine.terminal_wealth(100_000, [4_000 / 12] * months, p.ceiling_nominal, 12), rel=1e-12)
    k = round(levers["longer_horizon"]["horizon_years"] * 12)
    assert engine.terminal_wealth(100_000, [4_000 / 12] * k, p.ceiling_nominal, 12) >= 125_000
    assert engine.terminal_wealth(100_000, [4_000 / 12] * (k - 1), p.ceiling_nominal, 12) < 125_000
    assert "longer horizon, a higher saving or a smaller goal" in p.reason
    # an easy goal is realistic, with no levers
    easy = sheet(_worked(amount_basis="future"), CORRECTED_1_4).mandate_proposal.plausibility
    assert easy.judgement == "realistic" and easy.levers == ()


def test_without_a_risk_profile_the_table_bounds_the_judgement():
    """No profile: realistic below the most cautious row, not realistic above the most aggressive, could not
    be determined in between."""
    d = CORRECTED_1_4.model_dump()
    d["records"]["risk-profile"]["_about"]["provisional"] = True
    unapproved = Calibration.model_validate({**d, "version": "1.4.0-noprofile"})
    rows = CORRECTED_1_4.real_view.plausibility
    s = sheet(_worked(amount_basis="future"), unapproved)
    assert isinstance(s.risk_profile, NotAvailable)
    assert s.mandate_proposal.plausibility.judgement == "realistic"
    assert s.mandate_proposal.plausibility.ceiling_real == rows[0].real_return
    hard = sheet(_worked(amount_basis="future", amount=125_000, date_="2027-12-29", free=100_000, saving=4_000),
                 unapproved).mandate_proposal.plausibility
    assert hard.judgement == "not_realistic" and hard.ceiling_real == rows[-1].real_return and hard.levers
    # about 3 % real: between the rows
    mid = sheet(_worked(amount_basis="future", amount=150_000 * 1.035 ** 10, date_="2036-09-29", saving=0),
                unapproved).mandate_proposal.plausibility
    assert mid.judgement == "could_not_be_determined" and mid.ceiling_real is None
    unreachable = sheet(_worked(amount_basis="future", amount=10 ** 12, date_="2027-09-29", saving=0),
                        CORRECTED_1_4).mandate_proposal
    assert unreachable.feasible is False and unreachable.plausibility.judgement == "not_realistic"


def test_the_retirement_comparison_is_made_in_todays_francs():
    """LBS-33: a need in today's francs against AHV (indexed, today's francs) and the nominal BVG pension
    deflated from its first year; both views side by side."""
    body = sample_request()
    old = sheet(body, CORRECTED_1_3).retirement[0]
    s = sheet(body, CORRECTED_1_4)
    new = s.retirement[0]
    years = new.pillar2["to_age"] - new.pillar2["from_age"]
    bvg_real = new.pillar2["yearly"] / 1.005 ** years
    assert new.basis == "real" and new.needs_per_year == old.needs_per_year == 80_000
    assert new.covered_per_year == pytest.approx(new.ahv["yearly"] + bvg_real, rel=1e-12)
    assert old.covered_per_year == pytest.approx(new.ahv["yearly"] + new.pillar2["yearly"], rel=1e-12)
    assert new.views["real"].bvg_per_year == pytest.approx(bvg_real) and new.views["real"].as_at is None
    level = s.real_view.goals[1].price_level
    assert new.views["nominal"].needs_per_year == pytest.approx(80_000 * level)
    assert new.views["nominal"].as_at == date(2051, 1, 1)
    body["goals"][1]["amount_basis"] = "future"
    future = sheet(body, CORRECTED_1_4).retirement[0]
    assert future.needs_per_year == pytest.approx(80_000 / level)


def test_a_property_price_in_future_francs_is_tested_in_todays_francs():
    body = sample_request()
    body["goals"][0]["amount_basis"] = "future"
    s = sheet(body, CORRECTED_1_4)
    level = s.real_view.goals[0].price_level
    assert s.property[0].basis == "real" and s.property[0].price_chf == pytest.approx(1_000_000 / level)
    today = sheet(sample_request(), CORRECTED_1_4)
    assert today.property[0].price_chf == 1_000_000
    assert today.mandate_proposal.target_chf == pytest.approx(0.2 * 1_000_000 * today.real_view.goals[0].price_level)


def test_earlier_calibrations_do_not_read_the_new_fields_and_keep_their_bytes():
    """LBS-35: under 1.0.0 to 1.3.0 the new fields are not read (a note says so) and the sheet carries none of
    the new keys, so a stored artefact keeps its bytes and its id."""
    body = _worked(amount_basis="today", indexed=True)
    for cal in (SEED, APPROVED, CORRECTED, CORRECTED_1_3):
        s = sheet(body, cal)
        dumped = s.model_dump(mode="json")
        assert "real_view" not in dumped
        if isinstance(s.mandate_proposal, MandateProposal):
            assert not {"basis", "views", "plausibility"} & set(dumped["mandate_proposal"])
            assert any("are not read" in n for n in s.mandate_proposal.notes)
        assert all("basis" not in r for r in dumped["retirement"] + dumped["property"])
    plain = sheet(_worked(), CORRECTED_1_3)
    assert not any("are not read" in n for n in plain.mandate_proposal.notes)
    assert sheet(_worked(), CORRECTED_1_4).model_dump(mode="json")["real_view"]["inflation"]["label"] == "measured"


def test_the_real_view_calibration_is_checked():
    rv = CORRECTED_1_4.real_view.model_dump()
    assert CORRECTED_1_4.real_view.inflation["CHF"].annual_rate == 0.005
    assert set(CORRECTED_1_4.real_view.inflation) == {"CHF", "EUR", "USD"}
    with pytest.raises(ValidationError, match="not computable"):
        RealViewPolicy.model_validate({**rv, "inflation": {**rv["inflation"], "CHF": {
            **rv["inflation"]["CHF"], "annual_rate": 1.5}}})
    with pytest.raises(ValidationError, match="lacks an inflation"):
        RealViewPolicy.model_validate({**rv, "inflation": {"CHF": rv["inflation"]["CHF"]}})
    with pytest.raises(ValidationError, match="does not fall"):
        RealViewPolicy.model_validate({**rv, "plausibility": [{"risk_level": 0.0, "real_return": 0.05},
                                                              {"risk_level": 1.0, "real_return": 0.02}]})
    with pytest.raises(ValidationError, match="needs lbs-calibration@1.3.0"):
        Calibration.model_validate({**CORRECTED_1_4.model_dump(), "contract_version": "lbs-calibration@1.2.0"})
    assert (CORRECTED_1_4.version, CORRECTED_1_4.parent_version) == ("1.4.0", "1.3.0")
    assert CORRECTED_1_4.records == CORRECTED_1_3.records and CORRECTED_1_4.corrections == CORRECTED_1_3.corrections


# ===========================================================================
# The owner's decisions on the two assumptions of 1.4.0 (29.09.2026; LBS-36 to LBS-38): calibration 1.5.0
# ===========================================================================

from lbs.calibration import CORRECTED_1_5  # noqa: E402


def test_15_sets_the_chf_inflation_to_one_percent_and_keeps_the_rest():
    """LBS-36: CHF 1.0 %, the midpoint of the SNB's 0 to 2 % range, forward-looking, with its source line; EUR and
    USD keep their measured figures; LBS-37: the plausibility table is 1.4.0's, now approved. Nothing else in
    the calibration moves."""
    rv, old = CORRECTED_1_5.real_view, CORRECTED_1_4.real_view
    chf = rv.inflation["CHF"]
    assert chf.annual_rate == 0.01 and old.inflation["CHF"].annual_rate == 0.005
    assert "Nicolas, 29.09.2026" in chf.source and "midpoint" in chf.source and "SNB" in chf.source
    assert "0.4997" in chf.source and chf.index == old.inflation["CHF"].index
    assert rv.inflation["EUR"] == old.inflation["EUR"] and rv.inflation["USD"] == old.inflation["USD"]
    assert (rv.inflation["EUR"].annual_rate, rv.inflation["USD"].annual_rate) == (0.0211, 0.0254)
    assert rv.plausibility == old.plausibility
    assert [(r.risk_level, r.real_return) for r in rv.plausibility] == [(0.0, 0.02), (0.5, 0.035), (1.0, 0.05)]
    assert rv.plausibility_source.startswith("approved by the owner (Nicolas, 29.09.2026")
    assert "proposed" in old.plausibility_source and "to confirm" in old.plausibility_source
    assert (rv.measured_band, rv.lever_horizon_limit_years) == (old.measured_band, old.lever_horizon_limit_years)
    assert (CORRECTED_1_5.version, CORRECTED_1_5.parent_version) == ("1.5.0", "1.4.0")
    assert CORRECTED_1_5.records == CORRECTED_1_4.records and CORRECTED_1_5.policy == CORRECTED_1_4.policy
    assert CORRECTED_1_5.corrections == CORRECTED_1_4.corrections


def test_the_design_notes_worked_example_at_the_chf_one_percent():
    """The worked example (CHF 400 000 in today's francs in 20 years, 150 000 now, 12 000 a year fixed) under
    1.5.0, the owner's CHF 1 %: nominal target 488 076.02, 1.60 % nominal and 0.59 % real (log, and simple);
    read as future francs 0.18 % as before; with the contribution indexed 0.18 % real, as at any inflation."""
    s = sheet(_worked(), CORRECTED_1_5)
    m = s.mandate_proposal
    assert round(m.target_chf, 2) == 488_076.02 and round(400_000 * 1.01 ** 20, 2) == 488_076.02
    assert round(m.required_return * 100, 2) == 1.60
    assert m.required_return == pytest.approx(0.015963740851, abs=1e-10)
    real = m.views["real"]
    assert real.target_chf == pytest.approx(400_000, abs=0.005)
    assert round(real.required_return * 100, 2) == 0.59 and round(real.required_return_log * 100, 2) == 0.59
    assert real.required_return == pytest.approx((1 + m.required_return) / 1.01 - 1, abs=1e-15)
    assert real.required_return_log == pytest.approx(math.log1p(m.required_return) - math.log(1.01), abs=1e-15)
    wealth = engine.terminal_wealth(150_000, [1_000.0] * 240, m.required_return, 12)
    assert abs(wealth - m.target_chf) < 0.01
    assert s.real_view.inflation.annual_rate == 0.01 and s.real_view.inflation.label == "measured"
    assert s.real_view.goals[0].price_level == pytest.approx(1.01 ** 20, rel=1e-15)
    # the same figures as the 2 % example's machinery at 1 %: 1.5.0 differs from 1.4.0 in the rate only
    assert m.required_return == sheet(_worked(), _at(0.01)).mandate_proposal.required_return
    # between the measured 0.50 % (1.4.0) and the design note's 2 %
    low, high = sheet(_worked(), CORRECTED_1_4).mandate_proposal, sheet(_worked(), _at(0.02)).mandate_proposal
    assert low.required_return < m.required_return < high.required_return
    assert low.views["real"].required_return < real.required_return < high.views["real"].required_return
    future = sheet(_worked(amount_basis="future"), CORRECTED_1_5).mandate_proposal
    assert round(future.required_return * 100, 2) == 0.18 and future.target_chf == 400_000
    indexed = sheet(_worked(indexed=True), CORRECTED_1_5).mandate_proposal
    assert round(indexed.views["real"].required_return * 100, 2) == 0.18
    assert m.plausibility.judgement == "realistic"
    assert m.plausibility.ceiling_source.startswith("approved by the owner")
    assert m.plausibility.ceiling_nominal == pytest.approx((1 + m.plausibility.ceiling_real) * 1.01 - 1)
