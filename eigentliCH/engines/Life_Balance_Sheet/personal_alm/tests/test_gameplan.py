"""Task P5: the deterministic gameplan, and the rules that produce its findings.

**Two kinds of test here, and the split is a privacy constraint rather than a style choice.**

*Synthetic, committed.* One household per rule, with invented figures chosen to sit just inside and just
outside each trigger. These are the tests that say what a rule means, and they can live in version control
because nobody's numbers are in them.

*Reproduction, over whatever real submissions are on the machine.* The five worked cases are gitignored
(`andersCH-prototype/andersch-onboarding-*.json`) because they are real people's finances, and **that is why
this file asserts no figure from them.** A test reading `net_worth == 2_630_000` would put a household's net
worth into the repository, which is precisely what M74 and that gitignore line exist to prevent. So the
reproduction pass asserts *internal consistency* -- that the balance sheet adds up, that every finding's
figures match the section they were drawn from, that no rule failed to run -- and skips entirely when no
submissions are present, so a fresh clone passes.

The consequence worth stating: a regression in a *value* is caught by the synthetic tests, and a regression in
*coherence* by the reproduction pass. Neither alone would be enough.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from personal_alm.app import findings as F
from personal_alm.app import gameplan as G
from personal_alm.model.params import Params

#: Where the real submissions live when they exist. Gitignored; absent on any other machine.
REAL = Path(__file__).resolve().parents[4] / "andersCH-prototype"


# --- fixtures ------------------------------------------------------------------------------------------

def submission(**over) -> dict:
    """A minimal, entirely invented household that every rule can be tested against.

    Deliberately bland: a salary, a flat, a mortgage at the model's own rate, a pension consistent with the
    career, a filled pillar 3a and a will. Every rule below should be SILENT on it, which is what makes it a
    usable baseline -- a fixture that already trips three findings cannot show that a fourth one fired.
    """
    base = {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-20", "source": "test"},
        "state": {"age": 45, "W_L": 400_000.0, "W_R": 1_000_000.0, "W_res": 1_000_000.0,
                  "W_hol": 0.0, "D": 300_000.0, "W_P": 500_000.0, "W_3a": 120_000.0,
                  "H": 0.9, "N": 0.5, "E": 0.5},
        # `p_A` gives the free cash flow a destination. Without one this household frees about 71 000 and
        # commits only its 3a payment, so `undirected_surplus` fires -- correctly, which is why the fixture
        # needed fixing rather than the rule.
        "params": {"G": 90_000.0, "ahv_record_share": 1.0, "epsilon": 0.10,
                   "pillar3a_contribution": 7_258.0, "p_A": 60_000.0},
        "goals": [{"kind": "retirement", "description": "Ausgaben ab 65 gedeckt",
                   "target_year": 2046, "amount_chf": 90_000.0, "confidence": 0.9,
                   "is_consumption": False}],
        "asks": [],
        "derived_notes": [],
        "raw": {"birth_year": 1981, "canton": "Zug", "income_gross": 200_000.0,
                # Directed close to what the household actually frees, so the surplus rule is
                # silent here. It fired on the first version of this fixture, correctly.
                "spend_now": 90_000.0, "spend_later": 90_000.0, "savings": 62_000.0,
                "hours_per_week": 45, "work_years_current": 20, "pillar2": 500_000.0,
                "pillar3a": 120_000.0, "mortgage": 300_000.0, "mortgage_rate": 2.0,
                "property_total": 1_000_000.0, "civil_status": "verheiratet",
                "household": "mit Partnerin und Kindern", "legal_docs": ["Testament"],
                "other_kinds": [], "amortisation_mode": "direkt",
                "expected_return_pct": "5 %", "max_loss_pct": "20 %"},
    }
    for key, value in over.items():
        if key in ("state", "params", "raw", "meta") and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def evaluate(sub: dict) -> dict[str, dict]:
    """Assemble and return the findings by code, which is how every test below reads them."""
    q = G.assemble(sub)
    return {f["code"]: f for f in q["findings"]}


# --- a goal the arithmetic did not use -----------------------------------------------------------------

def test_a_stated_goal_that_is_not_computed_is_named():
    """**A live submission read a report in which its own goal did not occur.** A household stated "Eigentum
    kaufen 2037 2 Mio", the intake could not tell Wohneigentum from Ferienobjekt from Firma -- all three were
    ticked -- so the goal arrived as `other` and was correctly deferred. The report then solved the retirement
    gap, printed the return that target demands, and never mentioned the two million.

    The deferral is right. The silence was the defect.
    """
    sub = submission(goals=[
        {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2046,
         "amount_chf": 90_000.0, "confidence": 0.9, "is_consumption": False},
        {"kind": "other", "description": "Eigentum kaufen 2037 2 Mio", "target_year": 2037,
         "amount_chf": 2_000_000.0, "confidence": 0.9, "is_consumption": None},
    ])
    q = G.assemble(sub)
    deferred = q["goals_deferred"]
    assert len(deferred) == 1
    assert deferred[0]["description"] == "Eigentum kaufen 2037 2 Mio"
    assert deferred[0]["amount_chf"] == 2_000_000.0
    assert "Ferienobjekt" in deferred[0]["reason"], "the reason names what the ambiguity actually is"

    found = {f["code"]: f for f in q["findings"]}
    assert "goal_not_computed" in found
    # Severity is relative, so the test states the relation rather than a magic word: this fixture is a
    # wealthier household whose own target exceeds two million, which is why the first version of this
    # assertion was wrong and the rule was right.
    solved = q["required_return"]["target"]
    expected = "high" if 2_000_000.0 >= solved else "medium"
    assert found["goal_not_computed"]["severity"] == expected
    assert "2 000 000" in found["goal_not_computed"]["trigger"]
    # And it reaches the list a client acts from. It did not, on the first version: the rule was written with
    # an urgency outside the vocabulary, so it fired and the Zeitplan dropped it.
    assert "goal_not_computed" in [i["code"] for grp in q["schedule"] for i in grp["items"]]
    # The same list travels on the section that states the target, which is where a reader asks.
    assert q["required_return"]["goals_deferred"] == deferred


def test_a_goal_the_report_solves_for_is_not_reported_as_deferred():
    """The baseline states one retirement goal and it IS used, so nothing is deferred and nothing fires.

    Without this, the rule above would pass just as well on an implementation that called every goal deferred.
    """
    q = G.assemble(submission())
    assert q["goals_deferred"] == []
    assert "goal_not_computed" not in {f["code"] for f in q["findings"]}


def test_a_smaller_deferred_goal_is_medium_rather_than_high():
    """Severity tracks what was left out against what was solved, so it has to move with the figures.

    The spending target is raised here to open a real gap. The baseline household's flows at 65 already cover
    its spending, which makes its capital target zero -- and a zero target is the SEVERE case, because the
    report concludes nothing needs building while a stated goal sits uncomputed. So a fixture with no gap
    cannot show the mild end of this rule.
    """
    sub = submission(
        params={"G": 260_000.0},
        raw={"spend_now": 260_000.0, "spend_later": 260_000.0},
        goals=[
            {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2046,
             "amount_chf": 260_000.0, "confidence": 0.9, "is_consumption": False},
            {"kind": "holiday_home", "description": "Ferienwohnung 2035", "target_year": 2035,
             "amount_chf": 40_000.0, "confidence": 0.9, "is_consumption": True},
        ])
    q = G.assemble(sub)
    assert q["required_return"]["target"] > 40_000.0, "the fixture must have a gap for this to mean anything"
    found = {f["code"]: f for f in q["findings"]}
    assert found["goal_not_computed"]["severity"] == "medium"
    assert "Konsum" in found["goal_not_computed"]["why"], "the holiday-home reason, not the generic one"


def test_a_finding_with_an_unknown_urgency_is_listed_rather_than_dropped():
    """**A one-word typo removed an action from the only list a client acts from.**

    `schedule()` grouped by a hard-coded label dict and discarded anything else, so `urgency="weeks"` produced
    a finding that appeared among the findings and nowhere in the Zeitplan. A defect in the rules should be
    visible in the output, not invisible.
    """
    bogus = {"code": "made_up", "title": "Erfundener Befund", "severity": "high",
             "trigger": "-", "figures": {"x": 1}, "why": "-", "action": "-",
             "urgency": "weeks", "answers": []}
    groups = F.schedule([bogus])
    assert [i["code"] for grp in groups for i in grp["items"]] == ["made_up"]
    assert groups[-1]["when"] == "unsorted"
    assert "Fehler im Regelwerk" in groups[-1]["label"]


def test_every_urgency_has_a_group_in_the_schedule():
    """The two dicts were independent and happened to agree; this is what keeps them agreeing."""
    assert set(F.SCHEDULE_LABELS) == set(F.URGENCY_ORDER)


def test_the_two_deferral_tables_cannot_drift_apart():
    """The reader's reasons and the converter's reasons name the same kinds.

    `onboarding._NON_GOAL_KIND_REASONS` says why each kind is not converted, in the engine's terms;
    `gameplan._DEFERRAL_REASONS` says the same in the reader's. A kind that gains a slack function must leave
    neither table with a stale sentence, and a kind added to one must be added to the other.
    """
    from personal_alm.app.onboarding import _NON_GOAL_KIND_REASONS
    assert set(G._DEFERRAL_REASONS) == set(_NON_GOAL_KIND_REASONS)
    # And none of them is a kind the engine actually solves for, which would make the sentence a lie.
    assert not set(G._DEFERRAL_REASONS) & (G._CAPITAL_GOAL_KINDS | G._FLOW_GOAL_KINDS)


# --- the baseline is quiet -----------------------------------------------------------------------------

def test_baseline_trips_nothing_serious():
    """The bland household fires no `now` finding. Without this the other tests prove nothing."""
    fired = evaluate(submission())
    urgent = [c for c, f in fired.items() if f["urgency"] == "now"]
    assert urgent == [], f"the baseline should be quiet, fired: {urgent}"


def test_every_finding_is_well_formed():
    """Shape, severity and urgency. A finding the renderer cannot lay out is a finding nobody reads."""
    q = G.assemble(submission(state={"W_L": 1_000.0}, raw={"hours_per_week": 70, "legal_docs": "nichts",
                                                           "pillar3a": 0}))
    assert q["findings"], "expected this household to trip several rules"
    for f in q["findings"]:
        assert set(f) == {"code", "title", "severity", "trigger", "figures", "why", "action", "urgency",
                          "answers"}
        assert f["severity"] in F.SEVERITY_ORDER, f["severity"]
        assert f["urgency"] in F.URGENCY_ORDER, f["urgency"]
        for field in ("title", "trigger", "why", "action"):
            assert f[field].strip(), f"{f['code']}.{field} is empty"
        assert isinstance(f["figures"], dict) and f["figures"], f["code"]


def test_no_rule_fails_to_run():
    """An exception inside a rule is reported as unchecked, and there should be none.

    The distinction matters more than it looks: a rule that raised and a rule that found nothing both produce
    no finding, and treating them the same is what makes a checklist worse than no checklist.
    """
    for sub in (submission(),
                submission(raw={}),                       # nothing but the required blocks
                submission(state={"W_R": 0.0, "W_res": 0.0, "D": 0.0}),
                submission(params={"child_ages": [4.0, 9.0], "child_reference_age": 45})):
        assert G.assemble(sub)["findings_unchecked"] == []


# --- one test per rule of manual section 16 -------------------------------------------------------------

def test_drawable_thin_fires_below_twenty_percent():
    quiet = evaluate(submission(state={"W_L": 900_000.0}))
    assert "drawable_thin" not in quiet
    loud = evaluate(submission(state={"W_L": 50_000.0}))
    assert "drawable_thin" in loud
    assert loud["drawable_thin"]["figures"]["threshold"] == 0.20


def test_spending_doubling_needs_a_real_increase():
    assert "spending_doubling" not in evaluate(submission(raw={"spend_later": 100_000.0}))
    loud = evaluate(submission(raw={"spend_later": 180_000.0}))
    assert loud["spending_doubling"]["figures"]["factor"] == pytest.approx(2.0)


def test_undirected_surplus_measures_free_against_committed():
    """Free cash flow against saving that already has a destination -- not against what the client SAYS.

    The stated figure was the yardstick until 21 August 2026, which had two consequences: the finding could
    not fire for anyone who never gave one, and it produced a negative "surplus" for anyone whose stated
    figure exceeded the arithmetic. A real household stated 30 000 against a computed 18 626.
    """
    # No destination for the free cash flow: no amortisation, no 3a.
    loud = evaluate(submission(params={"p_A": None, "pillar3a_contribution": 0.0},
                              raw={"pillar3a": 0}))
    f = loud["undirected_surplus"]["figures"]
    assert f["undirected"] == pytest.approx(f["free"] - f["committed"])
    assert f["undirected"] > 0
    # And it fires whether or not the client ever stated a saving rate.
    assert "undirected_surplus" in evaluate(
        submission(params={"p_A": None, "pillar3a_contribution": 0.0},
                   raw={"pillar3a": 0, "savings": None}))


def test_a_stated_saving_above_the_computed_one_is_reported_as_a_contradiction():
    """It is not a surplus, and printing it as one put a minus sign in a sentence about unassigned money."""
    q = G.assemble(submission(raw={"savings": 300_000.0}))
    cf = q["cash_flow"]
    assert cf["stated_vs_free"] > 0, "the stated figure should exceed the computed one here"
    assert cf["undirected"] == pytest.approx(cf["free"] - cf["committed"])


def test_maintenance_paid_is_subtracted_and_received_is_added():
    """Asked since the beginning, subtracted nowhere until 21 August 2026."""
    base = G.assemble(submission())["cash_flow"]["free"]
    paying = G.assemble(submission(raw={"alimony_direction": "ich zahle",
                                        "alimony_amount": 24_000.0}))["cash_flow"]
    assert paying["alimony_paid"] == pytest.approx(24_000.0)
    assert paying["free"] == pytest.approx(base - 24_000.0)
    getting = G.assemble(submission(raw={"alimony_direction": "ich erhalte",
                                         "alimony_amount": 12_000.0}))["cash_flow"]
    assert getting["alimony_received"] == pytest.approx(12_000.0)
    assert getting["free"] == pytest.approx(base + 12_000.0)


def test_amortisation_is_a_destination_and_not_a_cost():
    """Paying down a mortgage is saving. Counting it as an expense made the same franc an outflow or an
    investment depending only on where it was sent."""
    with_amort = G.assemble(submission(params={"p_A": 20_000.0}))["cash_flow"]
    without = G.assemble(submission(params={"p_A": None}))["cash_flow"]
    assert with_amort["free"] == pytest.approx(without["free"]), "free must not depend on the destination"
    assert with_amort["committed"] > without["committed"]
    assert with_amort["undirected"] == pytest.approx(without["undirected"] - 20_000.0)


def test_debt_service_equal_to_spending_is_a_band_not_a_point():
    # i = 2 % of 4 500 000 is 90 000, exactly the target spend: the ratio is 1.00.
    loud = evaluate(submission(state={"D": 4_500_000.0, "W_R": 9_000_000.0, "W_res": 9_000_000.0}))
    assert loud["debt_service_equals_spending"]["figures"]["ratio"] == pytest.approx(1.0)
    # Half that debt puts the ratio at 0.50, outside the 0.80--1.25 band.
    assert "debt_service_equals_spending" not in evaluate(
        submission(state={"D": 2_250_000.0, "W_R": 9_000_000.0, "W_res": 9_000_000.0}))


def test_thin_liquidity_is_two_percent_of_debt():
    quiet = evaluate(submission(state={"W_L": 400_000.0, "D": 300_000.0}))
    assert "thin_liquidity" not in quiet
    loud = evaluate(submission(state={"W_L": 20_000.0, "D": 2_000_000.0, "W_R": 4_000_000.0,
                                      "W_res": 4_000_000.0}))
    f = loud["thin_liquidity"]["figures"]
    assert f["share"] == pytest.approx(0.01)
    assert f["cost_of_two_points"] == pytest.approx(40_000.0)


def test_pension_too_small_needs_a_long_career():
    """Under one year's income AND twenty years of work. Either alone is not the pattern."""
    small = {"W_P": 80_000.0}
    assert "pension_too_small" in evaluate(submission(state=small, raw={"work_years_current": 22}))
    # A short career explains a small balance, so the finding must not fire.
    assert "pension_too_small" not in evaluate(submission(state=small, raw={"work_years_current": 3}))


def test_hours_above_threshold_reports_the_multiple():
    p = Params()
    assert "hours_above_threshold" not in evaluate(submission(raw={"hours_per_week": 48}))
    loud = evaluate(submission(raw={"hours_per_week": 70}))
    f = loud["hours_above_threshold"]["figures"]
    assert f["threshold_hours"] == pytest.approx(p.tau_Y_star * 100.0)
    assert f["multiple"] == pytest.approx(4.0)   # 0.08 against a 0.02 base
    assert 0.0 < f["earning_power_ratio"] < 1.0


def test_empty_pillar3a_needs_both_zero():
    assert "empty_pillar3a" not in evaluate(submission())
    loud = evaluate(submission(state={"W_3a": 0.0}, params={"pillar3a_contribution": 0.0},
                               raw={"pillar3a": 0}))
    f = loud["empty_pillar3a"]["figures"]
    assert f["cap"] == pytest.approx(Params().pillar3a_cap)
    assert f["annual_effect"] == pytest.approx(f["cap"] * f["marginal_rate"])


def test_no_legal_documents_rationale_matches_the_household():
    """The WHY must fit. A widowed single person has no partner to disinherit."""
    single = evaluate(submission(raw={"legal_docs": "nichts", "civil_status": "verwitwet",
                                      "household": "alleine"}))["no_legal_documents"]
    assert "Partnerschaft" not in single["why"], single["why"]
    assert "gesetzlichen Erbfolge" in single["why"]

    cohabiting = evaluate(submission(raw={"legal_docs": [], "civil_status": "ledig, mit Partner",
                                          "household": "mit Partnerin"}))["no_legal_documents"]
    assert "Partnerschaft" in cohabiting["why"]


def test_a_will_or_an_inheritance_contract_both_count():
    """An Erbvertrag does the same job and binds harder, so either silences the rule."""
    for doc in ("Testament", "Erbvertrag"):
        assert "no_legal_documents" not in evaluate(
            submission(raw={"legal_docs": [doc], "civil_status": "ledig, mit Partner"}))


# --- ordering, the schedule, and the guarantees ---------------------------------------------------------

def test_findings_are_sorted_by_urgency_then_severity():
    q = G.assemble(submission(state={"W_L": 10_000.0, "W_3a": 0.0, "D": 2_000_000.0,
                                     "W_R": 4_000_000.0, "W_res": 4_000_000.0},
                              params={"pillar3a_contribution": 0.0},
                              raw={"hours_per_week": 70, "legal_docs": "nichts", "pillar3a": 0,
                                   "spend_later": 200_000.0}))
    keys = [(F.URGENCY_ORDER[f["urgency"]], F.SEVERITY_ORDER[f["severity"]]) for f in q["findings"]]
    assert keys == sorted(keys), "findings are not in urgency-then-severity order"


def test_the_schedule_says_nothing_the_findings_do_not():
    """Every scheduled action belongs to a finding. A plan with an item nobody derived is unauditable."""
    q = G.assemble(submission(state={"W_L": 10_000.0, "D": 2_000_000.0, "W_R": 4_000_000.0,
                                     "W_res": 4_000_000.0}, raw={"hours_per_week": 70}))
    by_code = {f["code"]: f for f in q["findings"]}
    seen = 0
    for group in q["schedule"]:
        for item in group["items"]:
            assert item["code"] in by_code
            assert item["action"] == by_code[item["code"]]["action"]
            assert by_code[item["code"]]["urgency"] == group["when"]
            seen += 1
    assert seen == len(q["findings"]), "some findings never reached the schedule"


def test_m74_nothing_can_hold_a_second_household():
    """The same guarantee `ReportFacts` gives, asserted on this payload's shape.

    Not "no comparison is made" but "there is no field a comparison could sit in". A rule someone adds later
    that returns a peer figure has nowhere to put it, and this test is what makes that stay true.
    """
    q = G.assemble(submission())
    banned = ("peer", "average", "benchmark_household", "comparison", "others", "cohort", "median")
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(q)


# --- the sections, where a defect was actually shipped --------------------------------------------------

def test_a_retirement_amount_is_a_flow_and_not_a_capital_target():
    """The defect this test exists for was measured, not imagined.

    A `retirement` goal states an amount PER YEAR. Feeding it to the required-return solve as a capital target
    asks what return turns the liquid wealth into 90 000 over twenty years -- which is met by losing money, and
    was reported as -50 %. So the target must come from the gap's implied capital, never from the goal's
    `amount_chf`, unless the goal kind actually states a capital sum.
    """
    q = G.assemble(submission())
    rr = q["required_return"]
    assert rr["target"] != q["goals"][0]["amount_chf"] if "goals" in q else True
    assert "Kapitalbedarf" in rr["target_source"] or rr["target"] == 0.0
    for rung in rr["rungs"]:
        assert rung["rate"] is None or rung["rate"] > rr["floor"], rung


def test_a_capital_goal_does_set_the_target():
    sub = submission(goals=[{"kind": "home", "description": "Wohnung", "target_year": 2036,
                             "amount_chf": 1_500_000.0, "confidence": 0.9, "is_consumption": True}])
    rr = G.assemble(sub)["required_return"]
    assert rr["target"] == pytest.approx(1_500_000.0)
    assert rr["years"] == pytest.approx(10.0)
    assert "Kapital bis 2036" in rr["target_source"]


def test_required_return_distinguishes_covered_from_unreachable():
    covered = G.assemble(submission())["required_return"]
    assert covered["rungs"][0]["outcome"] in ("covered", "ok")
    hopeless = G.assemble(submission(
        state={"W_L": 1_000.0},
        goals=[{"kind": "home", "description": "x", "target_year": 2028,
                "amount_chf": 50_000_000.0, "confidence": 0.9, "is_consumption": True}],
        raw={"savings": 0.0}))["required_return"]
    assert hopeless["unreachable_at_stated"] is True
    assert hopeless["rungs"][0]["rate"] is None


def test_the_mortgage_rate_the_household_gave_is_the_one_used():
    """The interview promises the answer replaces the model's 2 %, and for a while nothing consumed it."""
    q = G.assemble(submission(params={"mortgage_rate": 0.0135}, raw={"mortgage_rate": 1.35}))
    cf = q["cash_flow"]
    assert cf["mortgage_rate"] == pytest.approx(0.0135)
    assert cf["mortgage_interest"] == pytest.approx(0.0135 * 300_000.0)
    assert cf["mortgage_rate_is_stated"] is True
    assert "rate_not_recorded" not in {f["code"] for f in q["findings"]}


def test_no_rate_given_is_reported_as_substituted():
    q = G.assemble(submission(raw={"mortgage_rate": None}))
    assert q["cash_flow"]["mortgage_rate_is_stated"] is False
    assert "rate_not_recorded" in {f["code"] for f in q["findings"]}


def test_the_bridge_needs_a_stop_age_and_prices_the_permanent_cost():
    """No stop age, no bridge -- and the absence is a finding, not a silent omission."""
    without = G.assemble(submission(raw={"goals": "Ab 55 nicht mehr arbeiten"}))
    assert without["bridge"] is None
    assert "stop_age_missing" in {f["code"] for f in without["findings"]}

    with_stop = G.assemble(submission(params={"stop_work_age": 55},
                                      raw={"stop_work_age": 55}))
    b = with_stop["bridge"]
    assert b["stop_age"] == 55 and b["years"] == pytest.approx(10.0)
    # Pillar 2 is gated at 65 and 3a at 60, so a stop at 55 reaches neither.
    assert b["pillar3a_at_stop"] == 0.0
    assert b["ahv_gated_at"] == Params().ahv_age
    # Contributions stopping ten years early must cost something for life.
    assert b["permanent_pension_cost"] > 0
    assert b["pension_full"] > b["pension_early"]


def test_a_stop_age_at_or_after_the_reference_age_is_not_a_bridge():
    for age in (65, 67):
        assert G.assemble(submission(params={"stop_work_age": age}))["bridge"] is None


def test_the_unmarried_couple_tax_correction_is_applied_and_stated():
    sub = submission(params={"has_partner": True, "partner_income": 150_000.0,
                             "tax_split_factor": None},
                     raw={"civil_status": "ledig, mit Partner"})
    cf = G.assemble(sub)["cash_flow"]
    assert cf["unmarried_correction_applied"] is True
    # Separate assessment must be cheaper than one joint base at the single tariff, and the report uses it.
    assert cf["income_tax"] == pytest.approx(cf["income_tax_separate"])
    assert cf["tax_overstatement"] > 0
    assert cf["income_tax_joint_base"] > cf["income_tax_separate"]


def test_both_cash_flow_readings_are_given_when_a_partner_earns():
    sub = submission(params={"has_partner": True, "partner_income": 120_000.0})
    cf = G.assemble(sub)["cash_flow"]
    assert cf["free_subject_alone"] is not None
    assert cf["free_subject_alone"] < cf["free"]


def test_positions_outside_the_model_are_named_with_their_total():
    q = G.assemble(submission(raw={"company_value": 500_000.0, "collectibles_value": 10_000.0}))
    b = q["balance"]
    assert b["outside_total"] == pytest.approx(510_000.0)
    assert {o["label"] for o in b["outside_model"]} == {"Firmenbeteiligung",
                                                       "Sammlungen, Kunst, Fahrzeuge"}
    assert "positions_outside_model" in {f["code"] for f in q["findings"]}


def test_children_end_by_themselves():
    """A cost that runs to the end of the horizon is a constant, which is the defect M85 removed."""
    q = G.assemble(submission(params={"child_ages": [8.0, 12.0], "child_reference_age": 45,
                                      "child_cost_end_age": 21.0}))
    k = q["children"]
    assert k["cost_now"] > 0
    assert k["path"][-1]["cost"] < 0.1 * k["cost_now"], "the child cost never ends"
    assert "2000" in k["source"] and k["uprating"] == 1.0


def test_the_plan_section_is_absent_rather_than_invented_without_a_solve():
    q = G.assemble(submission())
    assert q["plan"] is None
    assert any("Optimierung ist nicht gelaufen" in x for x in q["limits"])


def test_a_goal_out_of_reach_is_a_finding_not_a_solver_failure():
    """M79: the solver converged and the answer is that the goal does not fit the means."""
    facts = {"outcome": "goal_not_fundable", "shortfall": 12_000.0, "p_goal": 0.42,
             "required_confidence": 0.90, "goal_epsilon": 0.10, "solver_converged": True,
             "achievable_amount": 60_000.0, "achievable_p_goal": 0.91,
             "achievable_full_deadline_years": 4.0, "engine_settings": {"M_opt": 32}}
    q = G.assemble(submission(), facts)
    got = {f["code"]: f for f in q["findings"]}
    assert "goal_not_fundable" in got
    f = got["goal_not_fundable"]
    assert f["severity"] == "blocking" and f["urgency"] == "now"
    assert f["figures"]["achievable_amount"] == 60_000.0
    # The achievable amount is a MEASUREMENT, never a target the report recommends aiming at.
    assert "Zielvorschlag" in f["action"] or "Messung" in f["action"]


def test_assumptions_name_every_figure_the_household_did_not_give():
    q = G.assemble(submission())
    what = {a["what"] for a in q["assumptions"]}
    assert "Umwandlungssatz Pensionskasse" in what
    assert "Entnahmesatz" in what
    for a in q["assumptions"]:
        assert a["value"] and a["source"] and a["replaced_by"]
    # The conversion rate is a declared assumption and must be reported as one, not as a parameter.
    conv = next(a for a in q["assumptions"] if a["what"] == "Umwandlungssatz Pensionskasse")
    assert "Annahme" in conv["source"]


def test_german_notation_in_german_strings():
    """A trigger reading 4.75 beside a table reading 4,75 was shipped, and is what this guards."""
    q = G.assemble(submission(state={"W_L": 10_000.0, "D": 2_000_000.0, "W_R": 4_000_000.0,
                                     "W_res": 4_000_000.0}, raw={"hours_per_week": 70}))
    import re
    for f in q["findings"]:
        for field in ("trigger", "why", "action"):
            # A digit, a full stop, a digit: an English decimal in German prose. Section numbers and
            # ellipses do not match, because both sides must be digits.
            assert not re.search(r"\d\.\d", f[field]), f"{f['code']}.{field}: {f[field]}"
    for a in q["assumptions"]:
        assert not re.search(r"\d\.\d", a["value"]), a


def test_levers_carry_a_unit_and_a_stock_effect_is_not_a_yearly_one():
    q = G.assemble(submission(raw={"hours_per_week": 70, "savings": 1_000.0}))
    lv = {x["kind"]: x for x in q["levers"]}
    assert lv["hours"]["unit"] == "chf_at_horizon"
    assert lv["surplus"]["unit"] == "chf_per_year"
    assert lv["amortisation"]["unit"] == "rate" and lv["amortisation"]["amount"] is None
    # Recurring francs sort before the horizon figure, whatever their size.
    order = [x["unit"] for x in q["levers"]]
    assert order.index("chf_per_year") < order.index("chf_at_horizon")


def test_amortisation_is_priced_after_tax():
    """The gross rate is the wrong number: the interest was deductible and paying it down forfeits that."""
    q = G.assemble(submission())
    lever = next(x for x in q["levers"] if x["kind"] == "amortisation")
    marginal = q["cash_flow"]["marginal_rate"]
    assert lever["rate"] == pytest.approx(Params().i * (1.0 - marginal))
    assert lever["rate"] < Params().i


# --- reproduction, over real submissions when they are present ------------------------------------------

def _real_submissions() -> list[Path]:
    return sorted(REAL.glob("andersch-onboarding-*.json")) if REAL.is_dir() else []


@pytest.mark.parametrize("path", _real_submissions(), ids=lambda p: p.stem[-18:])
def test_real_submissions_are_internally_consistent(path: Path):
    """Every worked case assembles, and every figure agrees with the one it was derived from.

    **No figure from these files is asserted here, and that is deliberate.** They are real households; a test
    naming their numbers would put those numbers in version control. What is asserted is coherence, which
    catches a whole class of regression without disclosing anything.
    """
    sub = json.loads(path.read_text(encoding="utf-8-sig"))
    q = G.assemble(sub)

    assert q["findings_unchecked"] == [], q["findings_unchecked"]

    b = q["balance"]
    assert b["net_worth"] == pytest.approx(b["liquid"] + b["property_total"] - b["debt"])
    assert b["total_wealth"] == pytest.approx(b["net_worth"] + b["pillar2"] + b["pillar3a"])
    assert b["let"] == pytest.approx(b["property_total"] - b["residence"] - b["holiday"])
    if b["total_wealth"]:
        assert 0.0 <= b["drawable_share"] <= 1.0
    assert b["outside_total"] == pytest.approx(sum(o["amount"] for o in b["outside_model"]))

    g = q["gap"]
    assert g["gap"] == pytest.approx(g["target_spend"] - g["flows"])
    for rate, capital in g["capital"].items():
        expected = g["gap"] / float(rate) if g["gap"] > 0 else 0.0
        assert capital == pytest.approx(expected)

    f65 = q["income_65"]
    assert f65["pillar2_annuity"] == pytest.approx(
        f65["pillar2_capital"] * G.PILLAR2_CONVERSION_RATE)
    assert f65["pillar2_capital"] >= f65["pillar2_today"]

    # Every finding's figures must match the section they came from, or the trigger is describing a
    # different household from the one the tables show.
    by_code = {x["code"]: x for x in q["findings"]}
    if "thin_liquidity" in by_code:
        assert by_code["thin_liquidity"]["figures"]["liquid"] == pytest.approx(b["liquid"])
        assert by_code["thin_liquidity"]["figures"]["debt"] == pytest.approx(b["debt"])
    if "undirected_surplus" in by_code:
        assert by_code["undirected_surplus"]["figures"]["free"] == pytest.approx(q["cash_flow"]["free"])
    if "drawable_thin" in by_code:
        assert by_code["drawable_thin"]["figures"]["drawable"] == pytest.approx(b["drawable"])

    # The schedule is a sort of the findings and may not gain or lose one.
    scheduled = [i["code"] for grp in q["schedule"] for i in grp["items"]]
    assert sorted(scheduled) == sorted(by_code)


@pytest.mark.parametrize("path", _real_submissions(), ids=lambda p: p.stem[-18:])
def test_real_submissions_render(path: Path):
    """The dossier renders, and carries the sections its own data implies.

    The renderer lives outside this package, so it is imported by path rather than by name -- it must not
    become an import the engine depends on.
    """
    import importlib.util
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("dossier_under_test",
                                                  root / "desktop" / "dossier.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    q = G.assemble(json.loads(path.read_text(encoding="utf-8-sig")))

    # **Two stages, and the gated one is not a degraded report.** A household whose answers contradict each
    # other gets the open-items page instead of the report, because every figure in the report is computed
    # from those answers. So the report's own structure is asserted on the forced render, and the gated page
    # is checked for being what it claims: the questions, and no figures.
    gated = mod.render(q)
    assert gated.startswith("<!doctype html>") and gated.rstrip().endswith("</html>")
    if (q.get("gate") or {}).get("stage") == "open":
        assert "Was noch offen ist" in gated
        assert "Wo Sie heute stehen" not in gated, "the open page must carry no report section"

    page = mod.render(q, force=True)
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    # The sections that are unconditional.
    for must in ("Wo Sie heute stehen", "Was dieses Dossier nicht sagen kann", "Der Zeitplan"):
        assert must in page, must
    # Never a Python None or a raw dict in the output, on either page.
    for rendered in (gated, page):
        for leak in (">None<", "None ", "{'", "dict_"):
            assert leak not in rendered, leak
    # A Befund is not a Recommendation, and the footer has to say so on every page.
    assert "keine Empfehlung" in page

#: Interview fields that reach NO equation, so a finding must never offer one as its answer. The canton is the
#: documented case: it is collected, `dynamics.income_tax` is a smooth approximation, and matching a real
#: cantonal tariff is a calibration task -- so an input for it collects an answer that changes nothing. It was
#: offered once, in the assumptions table, and had to be taken back out. `mortgage_fixed_until` is the same
#: shape: the model has one mortgage rate for the whole horizon and no date on which it resets.
FIELDS_THAT_REACH_NOTHING = frozenset({"canton", "mortgage_fixed_until", "amortisation_mode"})


def test_a_findings_answer_fields_are_real_interview_questions():
    """Every field a finding offers must be one the interview actually asks.

    **This is the test that catches a field attached to the wrong finding**, which happened: `legal_docs`
    landed on `rate_reset_near` instead of `no_legal_documents`. A name that exists somewhere in the schema
    but not in the interview would render as an empty control, and an empty control looks like a bug in the
    page rather than a mistake in a table.
    """
    page = (Path(__file__).resolve().parents[4] / "andersCH-prototype" / "onboarding-chat.html")
    if not page.is_file():
        pytest.skip("the interview page is not on this machine")
    text = page.read_text(encoding="utf-8")
    asked = set(re.findall(r'k:"([a-z_0-9]+)"', text))
    assert asked, "no questions found in the interview page; the pattern must have changed"

    # Every finding, not only the ones this household trips.
    seen = set()
    for rule in F.RULES:
        for sub in (submission(),
                    submission(state={"W_L": 1_000.0, "W_3a": 0.0, "D": 2_000_000.0,
                                      "W_R": 4_000_000.0, "W_res": 4_000_000.0, "W_P": 50_000.0},
                               params={"pillar3a_contribution": 0.0, "ahv_record_share": 0.8},
                               raw={"hours_per_week": 70, "legal_docs": "nichts", "pillar3a": 0,
                                    "spend_later": 300_000.0, "savings": 0.0, "mortgage_rate": None,
                                    "asset_scope": "nur mein Anteil", "work_years_current": 25})):
            got = rule(G.assemble(sub, with_asks=False), Params(), sub.get("raw") or {})
            if got:
                seen.add(got["code"])
                for field in got.get("answers") or []:
                    assert isinstance(field, str) and field
                    assert field in asked, f"{got['code']} offers {field!r}, which the interview never asks"
                    assert field not in FIELDS_THAT_REACH_NOTHING, (
                        f"{got['code']} offers {field!r}, which reaches no equation: answering it would "
                        f"change nothing and the control would be a promise the code does not keep")
    assert len(seen) >= 8, f"expected most rules to fire across the two fixtures, got {sorted(seen)}"
