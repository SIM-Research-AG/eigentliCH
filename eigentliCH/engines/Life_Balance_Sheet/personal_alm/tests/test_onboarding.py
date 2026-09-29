"""Task P2: `onb@0.1.x` submission -> `Case`.

Half of what this converter does is REFUSE, so half of these tests assert refusal. The failure mode it exists to
prevent is not a crash: it is a converter that silently drops the six `params` keys that are not `Params` fields
and returns a plausible case whose amortisation, confidence and mandate conditions were quietly discarded.
"""

from __future__ import annotations

import pytest

from personal_alm.app.onboarding import (
    SUPPORTED_VERSIONS,
    Conversion,
    SubmissionError,
    case_from_submission,
)
from personal_alm.model.params import Params


def _submission(**over) -> dict:
    """A complete, realistic 0.1.1 submission. Shaped after the cases actually run through the chat:
    a mid-career household with property, a mortgage, pension capital and an independence goal."""
    base = {
        "schema_version": "onb@0.1.1",
        "meta": {"collected": "2026-08-04", "source": "onboarding-chat"},
        "state": {"age": 52, "W_L": 400_000, "W_R": 2_000_000, "W_res": 1_200_000,
                  "W_hol": 0, "D": 800_000, "W_P": 600_000, "W_3a": 90_000,
                  "E": 0.9, "N": 0.8, "H": 0.75},
        "params": {"G": 120_000, "swr": 0.035, "epsilon": 0.10},
        "goals": [{"kind": "fi", "description": "Unabhängigkeit mit 62", "target_year": 2036,
                   "confidence": 0.85}],
        "raw": {"canton": "ZH"},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


# --- the happy path ----------------------------------------------------------------

def test_a_complete_submission_becomes_a_runnable_case():
    c = case_from_submission(_submission())
    assert isinstance(c, Conversion)
    assert c.case.goal.kind == "fi"
    # 2036 target against a 2026 collection date is a ten-year horizon, read from meta rather than from today.
    assert c.case.goal.horizon_years == pytest.approx(10.0)
    # confidence 0.85 -> epsilon 0.15, and Case.confidence is its complement.
    assert c.case.goal.epsilon == pytest.approx(0.15)
    assert c.case.confidence == pytest.approx(0.85)
    assert c.case.goal.params["G"] == pytest.approx(120_000)
    assert not c.case.calibrated, "a live submission is never a fitted case"


def test_age_reaches_the_state_not_only_the_label():
    """The M76 defect, guarded on the new path. `app/inputs.py` passed age to the label and no equation."""
    c = case_from_submission(_submission())
    assert c.case.x0.person.age == pytest.approx(52.0)
    # `Case.age` is a property derived from the state, so this is one fact, not two.
    assert c.case.age == pytest.approx(52.0)


def test_state_amounts_survive_including_the_residence_split():
    c = case_from_submission(_submission())
    w = c.case.x0.wealth
    assert (w.W_L, w.W_R, w.D) == (400_000.0, 2_000_000.0, 800_000.0)
    assert w.W_res == pytest.approx(1_200_000)
    # W_inv is DERIVED, so the parts summing to the whole is structural rather than asserted.
    assert w.W_inv == pytest.approx(800_000)
    assert (w.W_P, w.W_3a) == (600_000.0, 90_000.0)


# --- routing: the six keys that are not Params fields -------------------------------

def test_non_params_keys_are_deferred_with_reasons_not_dropped():
    """`replace(Params(), **params)` would raise on these. Silently filtering them is the worse failure."""
    c = case_from_submission(_submission(params={
        "p_A": 40_000, "tau_H_hint": 0.2, "max_loss_pct": 15, "expected_return_pct": 5,
    }))
    text = " ".join(what for what, _ in c.deferred)
    for key in ("p_A", "tau_H_hint", "max_loss_pct", "expected_return_pct"):
        assert key in text, f"{key} vanished without being reported"
    # And none of them reached the engine's parameters, where they are not fields at all.
    assert not {"p_A", "tau_H_hint", "max_loss_pct", "expected_return_pct"} & set(c.case.param_overrides)
    # Every deferral carries a reason; a bare list of dropped keys is not an account of anything.
    assert all(reason.strip() for _, reason in c.deferred)


def test_real_params_fields_do_reach_param_overrides():
    c = case_from_submission(_submission(params={
        "ahv_record_share": 0.86, "pension_contribution_rate": 0.12, "pillar3a_contribution": 7_258,
    }))
    o = c.case.param_overrides
    assert o["ahv_record_share"] == 0.86
    assert o["pension_contribution_rate"] == 0.12
    assert o["pillar3a_contribution"] == 7_258
    # And they survive into a real Params, which is the only proof that matters.
    p = c.case.params(None)
    assert p.ahv_record_share == 0.86 and p.pillar3a_contribution == 7_258


def test_an_unknown_params_key_is_refused_rather_than_ignored():
    with pytest.raises(SubmissionError, match="no documented route"):
        case_from_submission(_submission(params={"invented_knob": 1.0}))


# --- H1: the partner parameters reach the engine ------------------------------------

def test_partner_parameters_reach_the_engine():
    c = case_from_submission(_submission(params={
        "has_partner": True, "partner_income": 95_000, "partner_age_offset": -3,
        "partner_ahv_record_share": 0.9, "tax_split_factor": 2.0,
    }))
    p = c.case.params(None)
    assert p.has_partner is True
    assert p.partner_income == 95_000
    assert p.partner_age_offset == -3
    assert p.tax_split_factor == 2.0
    # The whole point of P6 and H1 together: a couple is taxed jointly and their AHV is capped.
    assert p.ahv_couple_cap_multiple == Params().ahv_couple_cap_multiple


def test_has_partner_is_inferred_from_an_income_but_reported_as_an_assumption():
    c = case_from_submission(_submission(params={"partner_income": 95_000}))
    assert c.case.params(None).has_partner is True
    assert any(f == "has_partner" for f, _, _ in c.assumed), "an inference must be reported as one"


# --- goals the engine cannot express ------------------------------------------------

def test_a_holiday_home_is_deferred_as_consumption_not_converted_to_a_goal():
    """The author was explicit that a holiday home is a consumption good: the question is affordability."""
    c = case_from_submission(_submission(goals=[
        {"kind": "fi", "description": "Unabhängigkeit", "target_year": 2036, "confidence": 0.85},
        {"kind": "holiday_home", "description": "Ferienhaus in den Bergen",
         "target_year": 2030, "amount_chf": 900_000, "is_consumption": True},
    ]))
    assert c.case.goal.kind == "fi"
    assert not c.case.extra_goals, "a consumption good must not become a funded goal"
    assert any("Ferienhaus" in what and "consumption" in why for what, why in c.deferred)


@pytest.mark.parametrize("kind", ["education", "legacy", "other"])
def test_kinds_the_model_expresses_elsewhere_are_deferred(kind):
    c = case_from_submission(_submission(goals=[
        {"kind": "fi", "description": "FI", "target_year": 2036, "confidence": 0.85},
        {"kind": kind, "description": f"a {kind} intention", "target_year": 2032, "amount_chf": 50_000},
    ]))
    assert not c.case.extra_goals
    assert any(kind in what for what, _ in c.deferred)


def test_a_goal_without_a_target_year_is_deferred_not_dated_by_guesswork():
    c = case_from_submission(_submission(goals=[
        {"kind": "fi", "description": "FI", "target_year": 2036, "confidence": 0.85},
        {"kind": "home", "description": "irgendwann ein Haus", "amount_chf": 1_200_000},
    ]))
    assert not c.case.extra_goals
    assert any("no usable target_year" in why for _, why in c.deferred)


def test_multiple_engine_goals_become_primary_plus_extras_in_order():
    c = case_from_submission(_submission(goals=[
        {"kind": "fi", "description": "FI", "target_year": 2036, "confidence": 0.85},
        {"kind": "home", "description": "Haus", "target_year": 2030, "amount_chf": 1_200_000,
         "confidence": 0.8},
    ]))
    assert c.case.goal.kind == "fi"
    assert [g.kind for g in c.case.extra_goals] == ["home"]
    assert c.case.extra_goals[0].params["price"] == pytest.approx(1_200_000)


# --- refusals ----------------------------------------------------------------------

def test_an_unrecognised_version_is_refused():
    with pytest.raises(SubmissionError, match="unrecognised schema_version"):
        case_from_submission(_submission(schema_version="onb@0.9.0"))


def test_a_0_1_0_payload_is_accepted_because_its_absence_of_partner_fields_is_meaningful():
    """Reading an older payload is safe; the hazard the schema warns about is the other direction."""
    p = dict(_submission())
    p["schema_version"] = "onb@0.1.0"
    p["params"] = {"G": 120_000, "swr": 0.035, "epsilon": 0.10}
    c = case_from_submission(p)
    assert c.case.params(None).has_partner is False
    assert "onb@0.1.0" in SUPPORTED_VERSIONS


def test_a_missing_G_is_refused_rather_than_defaulted():
    """G is the most sensitive input in the model; a default would invent an answer, not degrade one."""
    s = _submission()
    s["params"] = {"swr": 0.035}
    with pytest.raises(SubmissionError, match="params.G"):
        case_from_submission(s)


def test_a_missing_age_is_refused():
    s = _submission()
    s["state"] = {k: v for k, v in s["state"].items() if k != "age"}
    with pytest.raises(SubmissionError, match="state.age"):
        case_from_submission(s)


def test_a_submission_with_no_runnable_goal_is_refused_and_says_why():
    with pytest.raises(SubmissionError, match="no runnable goal"):
        case_from_submission(_submission(goals=[
            {"kind": "holiday_home", "description": "Ferienhaus", "target_year": 2030,
             "amount_chf": 900_000},
        ]))


def test_a_home_goal_without_a_price_is_refused():
    with pytest.raises(SubmissionError, match="amount_chf"):
        case_from_submission(_submission(goals=[
            {"kind": "home", "description": "Haus", "target_year": 2032, "confidence": 0.8},
        ]))


# --- assumptions are reported ------------------------------------------------------

def test_missing_capitals_are_defaulted_and_reported():
    s = _submission()
    s["state"] = {k: v for k, v in s["state"].items() if k not in ("E", "N", "H")}
    c = case_from_submission(s)
    reported = {f for f, _, _ in c.assumed}
    assert {"E", "N", "H"} <= reported, "a defaulted capital is a modelling assumption and must be reported"


def test_h_res_is_assumed_zero_and_says_so():
    """Counting the residence as drawable would inflate wealth by the value of the roof over their head."""
    c = case_from_submission(_submission())
    assert c.case.goal.params["h_res"] == 0.0
    assert any(f == "h_res" for f, _, _ in c.assumed)


def test_a_retirement_goal_gets_its_annuity_horizon_and_reports_an_assumed_one():
    c = case_from_submission(_submission(goals=[
        {"kind": "retirement", "description": "Pensionierung", "target_year": 2039, "confidence": 0.9},
    ]))
    assert c.case.goal.kind == "retirement"
    assert c.case.goal.params["years_in_retirement"] == pytest.approx(25.0)
    assert any(f == "years_in_retirement" for f, _, _ in c.assumed)

    explicit = case_from_submission(_submission(
        params={"years_in_retirement": 30},
        goals=[{"kind": "retirement", "description": "Pensionierung", "target_year": 2039,
                "confidence": 0.9}],
    ))
    assert explicit.case.goal.params["years_in_retirement"] == pytest.approx(30.0)
