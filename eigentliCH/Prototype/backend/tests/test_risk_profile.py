"""The risk profile: willingness, capacity, the conservative binding, and the interpolation.

**What these tests are protecting.** The profile is a continuous mapping, chosen over named bands, and the
objection to continuous is that the reasoning disappears into code. The defence is that the code holds a
straight line and the record holds both of its ends — so the assertions here are mostly that the code
*has no opinion*: at 0 it reproduces the cautious anchor exactly, at 1 the aggressive one, and in between
it is linear and nothing else.
"""

from __future__ import annotations

import json

import pytest

from eigentlich.services import risk_profile as rp


@pytest.fixture()
def approved(monkeypatch):
    from eigentlich import content

    record = json.loads(json.dumps(content._load("risk-profile")))
    record["_about"].update({
        "provisional": False, "published_by": "Test Fixture",
        "decided_on": "2026-09-06", "effective_from": "2026-09-06",
    })
    monkeypatch.setattr(rp, "_record", lambda: record)
    return record


# ============================================================ the refusal


def test_the_record_ships_provisional_and_nothing_computes():
    from eigentlich import content

    about = content._load("risk-profile")["_about"]
    assert about["provisional"] is True
    assert about["published_by"] is None
    for call in (lambda: rp.profile(stated_loss=0.3, crisis_behaviour="nachgekauft"),
                 lambda: rp.willingness(stated_loss=0.3, crisis_behaviour=None),
                 lambda: rp.capacity(horizon_years=10),
                 lambda: rp.parameters()):
        with pytest.raises(rp.ProfileNotApproved):
            call()


# ============================================================ the code has no opinion


def test_a_profile_of_zero_reproduces_the_cautious_anchor_exactly(approved):
    """If this drifts, the interpolation has started contributing something the record does not say."""
    result = rp.profile(stated_loss=0.0, crisis_behaviour="alles verkauft",
                        horizon_years=0, reserve_months=0, employment="nicht erwerbstätig",
                        free_share=0.0, debt_service_share=1.0)
    assert result.value == 0
    assert result.role_bounds == approved["anchors"]["role_bounds"]["cautious"]
    assert result.curve_slope == approved["anchors"]["curve_slope"]["cautious"]


def test_a_profile_of_one_reproduces_the_aggressive_anchor_exactly(approved):
    result = rp.profile(stated_loss=0.90, crisis_behaviour="nachgekauft",
                        horizon_years=40, reserve_months=24, employment="angestellt",
                        free_share=0.95, debt_service_share=0.0, mandates=3)
    assert result.value == 1
    assert result.role_bounds == approved["anchors"]["role_bounds"]["aggressive"]


def test_the_middle_is_the_midpoint_and_nothing_cleverer(approved):
    anchors = approved["anchors"]["role_bounds"]
    low, high = anchors["cautious"]["Gain"]["upper"], anchors["aggressive"]["Gain"]["upper"]
    assert rp.lerp(low, high, 0.5) == pytest.approx((low + high) / 2)
    halfway = rp.lerp(anchors["cautious"], anchors["aggressive"], 0.5)
    assert halfway["Gain"]["upper"] == pytest.approx((low + high) / 2)


def test_prose_beside_a_number_is_carried_and_never_interpolated(approved):
    """Every record in this build annotates its own numbers. A mapper that tried to blend a `why`
    string would fail on the first record written in the house style -- and this one does carry one
    right beside the anchors."""
    blended = rp.lerp(
        {"upper": 0.2, "why": "the cautious reason", "only_here": 1},
        {"upper": 0.8, "why": "the aggressive reason"}, 0.5)
    assert blended["upper"] == pytest.approx(0.5)
    assert blended["why"] == "the cautious reason"
    assert blended["only_here"] == 1


# ============================================================ willingness


def test_the_stated_loss_maps_between_the_two_published_points(approved):
    """`from_stated` and not `value`, deliberately: since 6 September the value carries the behaviour
    cap and floor as well, and there is no crisis answer that leaves the raw figure untouched at both
    ends. The mapping itself is what this asserts."""
    scale = approved["willingness"]["from_stated_loss"]
    assert rp.willingness(stated_loss=scale["at_or_below"]["loss"],
                          crisis_behaviour=None).from_stated == 0
    assert rp.willingness(stated_loss=scale["at_or_above"]["loss"],
                          crisis_behaviour=None).from_stated == 1
    # and it clamps rather than extrapolating
    assert rp.willingness(stated_loss=0.99, crisis_behaviour=None).from_stated == 1


def test_selling_everything_caps_the_claim(approved):
    """Behaviour observed beats a statement made in calm, and a bad answer still only lowers."""
    caps = approved["willingness"]["crisis_behaviour"]["caps"]
    sold = rp.willingness(stated_loss=0.40, crisis_behaviour="alles verkauft")
    assert sold.value == caps["alles verkauft"]
    assert sold.capped is True


def test_holding_through_a_fall_now_raises_the_claim(approved):
    """**The reversal of 6 September.** Nadine states a 10 % tolerance and held through the last fall;
    on the first draft she received a mandate identical to somebody who sold everything, because the
    stated figure decided and behaviour could only ever lower it.

    It cuts both ways on purpose: this is the application crediting a member with more than they wrote
    down, on the strength of one answer about one past fall.
    """
    floors = approved["willingness"]["crisis_behaviour"]["floors"]
    timid_but_steady = rp.willingness(stated_loss=0.10, crisis_behaviour="nichts, ich blieb investiert")
    assert timid_but_steady.from_stated == pytest.approx(0.143, abs=0.001)
    assert timid_but_steady.value == floors["nichts, ich blieb investiert"]
    assert timid_but_steady.lifted is True

    bought_more = rp.willingness(stated_loss=0.10, crisis_behaviour="nachgekauft")
    assert bought_more.value == floors["nachgekauft"] > timid_but_steady.value


def test_only_demonstrated_behaviour_lifts_and_the_rest_only_caps(approved):
    """Never having been invested is not evidence, and neither is silence."""
    for answer in ("ich war nicht investiert", "noch nie investiert", None, "alles verkauft"):
        result = rp.willingness(stated_loss=0.10, crisis_behaviour=answer)
        assert result.floor == 0, answer
        assert result.lifted is False, answer
        assert result.value == pytest.approx(0.143, abs=0.001), answer


def test_leaving_the_crisis_question_blank_caps_like_never_having_invested(approved):
    """**Blank is not evidence of composure.** In both cases nothing is known about how this person
    behaves when the number goes down, so both are capped the same."""
    caps = approved["willingness"]["crisis_behaviour"]["caps"]
    blank = rp.willingness(stated_loss=0.40, crisis_behaviour=None)
    never = rp.willingness(stated_loss=0.40, crisis_behaviour="ich war nicht investiert")
    assert blank.value == never.value == caps["_unanswered"]
    assert "not evidence of composure" in blank.cap_reason


# ============================================================ capacity


def test_a_missing_input_drops_its_component_rather_than_scoring_zero(approved):
    """Scoring zero would say «this household has no reserve» when what happened is that nobody asked,
    and it would pull every incomplete record toward cautious for a reason about the form."""
    everything = rp.capacity(horizon_years=20, reserve_months=12, employment="angestellt",
                             variable_share=0, mandates=0, free_share=0.9, debt_service_share=0)
    partial = rp.capacity(horizon_years=20, employment="angestellt", variable_share=0, mandates=0)
    assert "reserve" in partial.missing and "free_share" in partial.missing
    assert partial.value is not None
    assert partial.value > 0.5, "the components that ARE known still score"
    assert everything.value > partial.value


def test_capacity_is_none_when_nothing_at_all_is_known(approved):
    assert rp.capacity().value is None


def test_a_variable_income_reduces_stability_and_mandates_raise_it(approved):
    plain = rp.capacity(employment="angestellt", variable_share=0, mandates=0)
    bonus = rp.capacity(employment="angestellt", variable_share=1.0, mandates=0)
    spread = rp.capacity(employment="angestellt", variable_share=0, mandates=3)
    assert bonus.value < plain.value < spread.value


# ============================================================ the conservative binds


def test_the_lower_of_willingness_and_capacity_is_the_profile(approved):
    """The owner's standing ruling, applied for the third time."""
    # willing but unable. A crisis answer with no floor, so only the position can bind.
    a = rp.profile(stated_loss=0.40, crisis_behaviour="ich war nicht investiert", horizon_years=1,
                   reserve_months=0, employment="nicht erwerbstätig")
    assert a.binds_on == rp.BY_CAPACITY
    # able but unwilling
    b = rp.profile(stated_loss=0.06, crisis_behaviour="ich war nicht investiert", horizon_years=40,
                   reserve_months=24, employment="angestellt", free_share=0.9)
    assert b.binds_on == rp.BY_WILLINGNESS
    assert b.value < a.value or b.value < 0.2


def test_one_side_alone_still_produces_a_profile_and_says_so(approved):
    """Refusing outright would leave the member with the identical block this module exists to replace."""
    no_tolerance = rp.profile(stated_loss=None, crisis_behaviour=None, horizon_years=20,
                              reserve_months=12, employment="angestellt")
    assert no_tolerance.value is not None
    assert no_tolerance.binds_on == rp.BY_CAPACITY
    assert any("decides unrestrained" in c for c in no_tolerance.caveats)


def test_neither_side_computable_is_reported_and_not_guessed(approved):
    result = rp.profile(stated_loss=None, crisis_behaviour=None)
    assert result.value is None
    assert result.verdict == rp.COULD_NOT_BE_DETERMINED
    assert result.role_bounds is None


# ============================================================ the universe, the one hard edge


def test_nothing_is_ever_removed_from_the_universe_any_more(approved):
    """**A ceiling of zero cannot make a mandate infeasible; a removal can** (A157).

    Removing equity emptied the Gain role while that role's own floor still demanded weight from it, the
    solver failed to converge, and the fallback it reported read like a considered allocation. A cautious
    profile now gets a low equity ceiling instead of no equity.
    """
    assert "universe" not in approved, "the removal rule is gone from the record too"
    cautious = rp.profile(stated_loss=0.05, crisis_behaviour="alles verkauft", horizon_years=2)
    for asset_class in ("Equity", "Alternative", "Real Assets", "Cash"):
        assert rp.admits(cautious, asset_class=asset_class) is True

    ceiling = cautious.asset_class_bounds["Equity"]["upper"]
    assert ceiling == 0, "at the cautious anchor itself the ceiling is zero"


def test_a_low_profile_still_reaches_a_real_equity_ceiling(approved):
    """Stated because it is counter-intuitive and is in the record's own review list: a ceiling of zero
    at the anchor does NOT give a near-zero ceiling just above it. The map is a straight line, so a
    profile of 0.14 already reaches about eleven per cent."""
    low = rp.profile(stated_loss=0.10, crisis_behaviour="alles verkauft", horizon_years=2,
                     employment="pensioniert")
    ceiling = low.asset_class_bounds["Equity"]["upper"]
    assert 0.08 < ceiling < 0.15, ceiling


# ============================================================ sustainability


def test_the_two_sustainability_questions_stay_separate(approved):
    """An exclusion is categorical and a minimum is a proportion. «Anything but weapons» answers the
    first and not the second, and a build that conflated them would record neither."""
    result = rp.sustainability(exclusions=["Waffen"], level="keine Vorgabe")
    assert result.exclusions == ["Waffen"]
    assert result.esg_min == 0, "refusing one category is not a statement about the whole portfolio"


def test_the_level_maps_to_the_constraint_the_optimiser_already_enforces(approved):
    levels = {e["label"]: e["esg_min"] for e in approved["sustainability"]["minimum"]["levels"]}
    for label, expected in levels.items():
        assert rp.sustainability(level=label).esg_min == expected


def test_an_exclusion_the_record_does_not_offer_is_reported_not_dropped(approved):
    """A member who wrote something the build cannot match has said something, and a curator should
    see it rather than have it silently vanish."""
    result = rp.sustainability(exclusions=["Waffen", "Rüstungszulieferer"])
    assert result.exclusions == ["Waffen"]
    assert result.unknown_exclusions == ["Rüstungszulieferer"]


# ============================================================ the ten, and the point of the exercise


#: (name, stated loss, crisis answer, years to the nearest dated goal) as they answered.
MEMBERS = [
    ("Elia T.", 0.30, "ich war nicht investiert", 14),
    ("Marvin M.", 0.30, "ich war nicht investiert", 12),
    ("Renzo T.", 0.30, "ich war nicht investiert", 11),
    ("Levin S.", 0.20, "ich war nicht investiert", 8),
    ("Sandra I.", 0.30, "nachgekauft", 25),
    ("Reto K.", 0.20, "nachgekauft", 20),
    ("Yasmin T.", 0.30, "", 10),
    ("Nadine C.", 0.10, "nichts, ich blieb investiert", 10),
    ("Elio T.", 0.10, "", 7),
    ("Ueli W.", 0.10, "alles verkauft", 2),
]


def test_the_ten_no_longer_collapse_onto_one_another(approved):
    """**The whole reason this module exists.** Ten members produced two portfolios because every input
    that could distinguish them was held constant. Five distinct profiles is not a target anybody set —
    it is what these ten answers produce once the answers are read."""
    values = set()
    for _name, loss, crisis, horizon in MEMBERS:
        result = rp.profile(stated_loss=loss, crisis_behaviour=crisis, horizon_years=horizon,
                            employment="angestellt", variable_share=0, mandates=0)
        assert result.value is not None
        values.add(round(result.value, 3))
    assert len(values) >= 4, f"the profiles collapsed again: {sorted(values)}"


def test_the_three_who_stated_ten_per_cent_are_no_longer_identical(approved):
    """**The case that drove the reversal.** All three wrote «10 %». One held through the last fall, one
    sold everything, one did not answer. On the first draft they received identical mandates."""
    got = {}
    for name, loss, crisis, horizon in MEMBERS:
        if name not in ("Ueli W.", "Nadine C.", "Elio T."):
            continue
        got[name] = rp.profile(stated_loss=loss, crisis_behaviour=crisis, horizon_years=horizon,
                               employment="angestellt", variable_share=0, mandates=0).value

    assert got["Nadine C."] > got["Ueli W."], "she held through it and he sold everything"
    assert got["Nadine C."] > got["Elio T."], "he did not answer, which is not evidence of composure"
    # Ueli and Elio remain equal, and that is right: nothing is known about either that separates them.
    assert got["Ueli W."] == got["Elio T."]


# ============================================================ the two numbers that disagreed


def test_a_role_with_nothing_to_buy_loses_its_floor(approved):
    """**The defect this function exists for, and it was live.**

    The cautious anchor puts Gain's lower bound at 0.00 and the aggressive one at 0.40, so interpolation
    gives a positive Gain floor at any profile above zero -- 0.057 at 0.143. The universe rule removes
    equity below 0.35. Between those two numbers every mandate demanded Gain from a universe with no Gain
    instrument in it, because every Gain block in the register is an equity.

    The Optimiser caught it and said so in its notes, failed to converge, and reported a fallback. Reading
    `role_allocation` without reading `notes` made that look like a considered allocation with no equity.
    """
    result = rp.profile(stated_loss=0.10, crisis_behaviour="alles verkauft", horizon_years=2,
                        employment="pensioniert")
    assert result.role_bounds["Gain"]["lower"] > 0, "the interpolation does create the floor"

    fixed = rp.reconcile_with_universe(result, roles_available=["income", "protection", "stabilisation"])
    assert fixed.role_bounds["Gain"]["lower"] == 0
    assert fixed.role_bounds["Gain"]["upper"] == 0
    assert any("no instrument for Gain" in c for c in fixed.caveats)
    # and the roles that ARE available are untouched
    assert fixed.role_bounds["Protection"] == result.role_bounds["Protection"]


def test_reconciling_changes_nothing_when_every_role_can_be_bought(approved):
    result = rp.profile(stated_loss=0.40, crisis_behaviour="nachgekauft", horizon_years=30,
                        reserve_months=12, employment="angestellt", free_share=0.9)
    same = rp.reconcile_with_universe(
        result, roles_available=["gain", "income", "protection", "stabilisation"])
    assert same is result, "no change means no new object and no new caveat"


def test_a_sustainability_exclusion_is_now_the_only_way_to_empty_a_role(approved):
    """Since the profile removes nothing, the reconciliation is not dead code — it is what an exclusion
    needs. A member who refuses every category a role is built from has emptied that role, and the
    mandate must not then demand weight from it."""
    assert "universe" not in approved
    result = rp.profile(stated_loss=0.40, crisis_behaviour="nachgekauft", horizon_years=30,
                        reserve_months=12, employment="angestellt", free_share=0.9)
    assert result.role_bounds["Gain"]["lower"] > 0
    emptied = rp.reconcile_with_universe(
        result, roles_available=["income", "protection", "stabilisation"])
    assert emptied.role_bounds["Gain"]["lower"] == 0
