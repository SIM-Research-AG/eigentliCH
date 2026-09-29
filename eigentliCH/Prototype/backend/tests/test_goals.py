"""S-04 containers: R-030, R-130, R-131, R-132, R-133 and R-031's statements of fact."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.db import PlanMutationWithoutDecision
from eigentlich.models import Decision, Goal, Position
from eigentlich.services import mutate_plan
from eigentlich.services.goals import (
    FIVE_PARAMETERS,
    GOAL_TEMPLATES,
    GoalNotFound,
    NothingToChange,
    REVISABLE_FIELDS,
    list_goals,
    observations,
    revise_goal,
)


def _plan(session, member, *, goals=(), positions=(), link=None):
    with mutate_plan(session, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        for obj in list(positions) + list(goals):
            session.add(obj)
        if link:
            link()
        decision.linked_positions.extend(positions)
        decision.linked_goals.extend(goals)
    session.commit()


@pytest.fixture()
def member_with_plan(session, member):
    house = Goal(member_id=member.id, name="Wohneigentum", target_date=date(2031, 6, 1))
    courage = Goal(member_id=member.id, name="Mutgeld", template="courage_money")
    securities = Position(
        member_id=member.id, role="growth", capital_type="financial",
        label="Wertschriftendepot", liquidity="within_months",
    )
    _plan(
        session, member,
        goals=[house, courage], positions=[securities],
        link=lambda: (house.funded_by.append(securities), courage.funded_by.append(securities)),
    )
    return member, house, courage, securities


# ============================================================ R-030 / R-130


def test_one_position_may_fund_two_goals(session, member_with_plan):
    """R-030 and principle 7. One portfolio, many meanings."""
    member, house, courage, securities = member_with_plan
    payload = list_goals(session, member_id=member.id)
    by_name = {g["name"]: g for g in payload["goals"]}
    assert by_name["Wohneigentum"]["funded_by"][0]["id"] == securities.id
    assert by_name["Mutgeld"]["funded_by"][0]["id"] == securities.id


def test_the_payload_says_funding_may_overlap(session, member_with_plan):
    """R-130: the UI must not imply separate accounts, so the payload says so out loud."""
    member, *_ = member_with_plan
    assert list_goals(session, member_id=member.id)["funding_may_overlap"] is True


def test_a_shared_position_reports_how_many_other_goals_it_funds(session, member_with_plan):
    member, *_ = member_with_plan
    payload = list_goals(session, member_id=member.id)
    for goal in payload["goals"]:
        assert goal["funded_by"][0]["also_funds_goal_count"] == 1


def test_sharing_is_surfaced_as_an_observation(session, member_with_plan):
    member, house, *_ = member_with_plan
    kinds = {o["kind"] for o in list_goals(session, member_id=member.id)["goals"][0]["observations"]}
    assert "funding_shared_with_other_goals" in kinds


# ============================================================ R-131


def test_every_goal_shows_all_five_parameters(session, member_with_plan):
    """R-131. Present and null when unanswered — a missing key and an unanswered parameter differ."""
    member, *_ = member_with_plan
    for goal in list_goals(session, member_id=member.id)["goals"]:
        assert set(goal["parameters"]) == set(FIVE_PARAMETERS)


def test_the_five_parameters_are_named_once():
    assert len(FIVE_PARAMETERS) == 5
    for name in FIVE_PARAMETERS:
        assert hasattr(Goal, name)


# ============================================================ R-132


def test_courage_money_is_a_first_class_template():
    """R-132. Not a footnote: a template with its own name and purpose, in both languages."""
    template = GOAL_TEMPLATES["courage_money"]
    assert template["de"]["name"] == "Mutgeld"
    assert template["en"]["name"] == "Courage money"
    assert template["de"]["purpose"] and template["en"]["purpose"]


def test_courage_money_prescribes_no_parameters(session, member_with_plan):
    """What makes it courage money is what it is FOR. Prescribing its volatility tolerance would be
    inventing the member's own answer."""
    member, _, courage, _ = member_with_plan
    payload = next(g for g in list_goals(session, member_id=member.id)["goals"] if g["template"])
    assert all(value is None for value in payload["parameters"].values())


def test_templates_are_offered_with_the_list(session, member_with_plan):
    member, *_ = member_with_plan
    keys = {t["key"] for t in list_goals(session, member_id=member.id)["templates"]}
    assert "courage_money" in keys


# ============================================================ R-031


def test_a_dated_goal_with_no_funding_is_stated(session, member):
    goal = Goal(member_id=member.id, name="Ferienhaus", target_date=date(2030, 1, 1))
    _plan(session, member, goals=[goal])
    kinds = {o["kind"] for o in observations(goal)}
    assert "dated_but_unfunded" in kinds


def test_a_dated_goal_funded_only_by_illiquid_holdings_is_stated(session, member):
    """The one comparison that needs no threshold."""
    goal = Goal(member_id=member.id, name="Ferienhaus", target_date=date(2030, 1, 1))
    holding = Position(
        member_id=member.id, role="growth", capital_type="financial",
        label="Beteiligung an der Firma", liquidity="illiquid",
    )
    _plan(session, member, goals=[goal], positions=[holding],
          link=lambda: goal.funded_by.append(holding))
    kinds = {o["kind"] for o in observations(goal)}
    assert "dated_but_funding_is_illiquid" in kinds


def test_immediate_funding_is_never_flagged(session, member):
    goal = Goal(member_id=member.id, name="Steuern 2027", target_date=date(2027, 3, 1))
    cash = Position(
        member_id=member.id, role="stabilisation", capital_type="financial",
        label="Kontokorrent", liquidity="immediate",
    )
    _plan(session, member, goals=[goal], positions=[cash], link=lambda: goal.funded_by.append(cash))
    kinds = {o["kind"] for o in observations(goal)}
    assert "dated_but_funding_is_illiquid" not in kinds
    assert "dated_but_unfunded" not in kinds


def test_unstated_liquidity_is_reported_as_unstated_not_guessed(session, member):
    """A member who has not said is not the same as one who said 'immediate'."""
    goal = Goal(member_id=member.id, name="Umbau", target_date=date(2029, 1, 1))
    unknown = Position(
        member_id=member.id, role="growth", capital_type="financial", label="Depot",
    )
    _plan(session, member, goals=[goal], positions=[unknown],
          link=lambda: goal.funded_by.append(unknown))
    kinds = {o["kind"] for o in observations(goal)}
    assert "liquidity_not_stated" in kinds
    assert "dated_but_funding_is_illiquid" not in kinds


def test_an_undated_goal_produces_no_date_observations(session, member):
    goal = Goal(member_id=member.id, name="Irgendwann ein Boot")
    _plan(session, member, goals=[goal])
    assert observations(goal) == []


def test_observations_carry_no_severity_and_cannot_be_dismissed(session, member):
    """R-031: a statement of fact, not a warning to be dismissed.

    No severity, no status colour, no `dismissed` flag — there is nowhere to click 'ignore', because the
    thing being reported is not an alert.
    """
    goal = Goal(member_id=member.id, name="Ferienhaus", target_date=date(2030, 1, 1))
    _plan(session, member, goals=[goal])
    for observation in observations(goal):
        for forbidden in ("severity", "level", "warning", "dismissed", "dismissible", "status", "error"):
            assert forbidden not in observation, f"R-031: observation carries {forbidden!r}"


# ============================================================ R-133 / C-02


def test_no_illustration_is_offered_without_a_published_assumption_set(session, member_with_plan):
    """R-133 and C-02. The reason is explicit, so a client never infers from absence."""
    member, *_ = member_with_plan
    for goal in list_goals(session, member_id=member.id)["goals"]:
        assert goal["illustration"] is None
        assert goal["illustration_unavailable_reason"] == "no_assumption_set_published"


# ============================================================ R-113


def test_the_goal_payload_carries_no_funded_percentage(session, member_with_plan):
    """A '72% funded' is the completion meter this product exists without."""
    import json

    member, *_ = member_with_plan
    blob = json.dumps(list_goals(session, member_id=member.id))
    for forbidden in ("percent", "funded_ratio", "on_track", "progress", "completion", "shortfall_pct"):
        assert forbidden not in blob, f"R-113: goal payload carries {forbidden!r}"


# ============================================================ the templates, after the owner's report
#
# 31 August 2026. The owner: "There is only one Vorlage Mutgeld and this one I don't understand. We have
# the potential goals already defined and when in the onboarding the system ask for a goal, then we should
# immediately fill that goal out." There were two templates — courage money and `unspecified` — so their
# own "Frühpensionierung" was stored as `unspecified`.


def test_early_retirement_is_first_and_is_named_in_german():
    """The owner asked for Frühpensionierung and asked for it first.

    First in a dict is not decoration: `list(GOAL_TEMPLATES.values())` is what the client renders in
    order, so the ordering here IS the ordering on screen.

    **Planted violation:** moved `early_retirement` below `financial_independence`. Failed on the index.
    Restored.
    """
    keys = list(GOAL_TEMPLATES)
    assert keys[0] == "early_retirement", f"Frühpensionierung is no longer first: {keys}"
    assert GOAL_TEMPLATES["early_retirement"]["de"]["name"] == "Frühpensionierung"


def test_the_owners_own_goal_kinds_are_all_present():
    """The list is the owner's, not one invented for them.

    Seven of the nine come from `goal_kinds` in `client/reference/questions-onb-0.1.3.json`, which holds
    the wording from three real interviews. Checked by German name, because a key can be renamed without
    anyone noticing that a kind of goal has quietly gone.
    """
    named = {record["de"]["name"] for record in GOAL_TEMPLATES.values()}
    for expected in (
        "Frühpensionierung",
        "Finanzielle Unabhängigkeit",
        "Wohneigentum",
        "Ferienobjekt",
        "Weiterbildung oder Umschulung",
        "Firma aufbauen oder kaufen",
        "Nachlass und Erben",
        "Mutgeld",
    ):
        assert expected in named, f"{expected!r} is gone from GOAL_TEMPLATES"


def test_a_member_can_still_name_their_own():
    """`unspecified` is kept, and last, and now says what it is instead of being a blank line in a select."""
    keys = list(GOAL_TEMPLATES)
    assert keys[-1] == "unspecified"
    assert GOAL_TEMPLATES["unspecified"]["de"]["name"], "the option renders as an empty line again"


@pytest.mark.parametrize("key", sorted(GOAL_TEMPLATES))
def test_every_template_is_complete_in_both_languages(key):
    """A12. A template with no English purpose is a screen that half-speaks English."""
    record = GOAL_TEMPLATES[key]
    assert record["key"] == key, "the key inside the record disagrees with the key it is stored under"
    for language in ("de", "en"):
        assert record[language]["name"], f"{key} has no {language} name"
        assert record[language]["purpose"], f"{key} has no {language} purpose"


@pytest.mark.parametrize("key", sorted(GOAL_TEMPLATES))
def test_no_template_states_a_figure(key):
    """C-02. A template describes a KIND of goal; a rate, an age or an amount is a published assumption.

    The AHV material this drew on is full of numbers — a reduction per month, a minimum contribution, a
    reference age — and every one of them is dated and belongs where its `Stand` can travel with it. A
    digit in a one-sentence purpose has no source and no date.

    **Planted violation:** wrote "frühestens ab 63" into `early_retirement`. Failed naming the template.
    Removed; the AHV note carries the age with its source instead.
    """
    record = GOAL_TEMPLATES[key]
    for language in ("de", "en"):
        text = f"{record[language]['name']} {record[language]['purpose']}"
        digits = [character for character in text if character.isdigit()]
        assert not digits, f"C-02: template {key} states {digits} in {language}"
        for word in ("prozent", "percent", "%", "chf", "franken", "francs"):
            assert word not in text.lower(), f"C-02: template {key} names {word!r} in {language}"


@pytest.mark.parametrize("key", sorted(GOAL_TEMPLATES))
def test_every_template_key_fits_the_column(key):
    """`Goal.template` is `String(40)`. SQLite does not enforce a VARCHAR length, so a longer key would be
    stored happily here and truncated by whatever database this is ported to."""
    assert len(key) <= 40, f"{key!r} is {len(key)} characters; Goal.template is String(40)"


def test_a_goal_can_be_named_from_every_template(session, member):
    """The keys are not decorative: each has to be storable and readable back.

    A template whose key the API refuses is a template nobody can choose, which is the state
    `early_retirement` was in before it existed.
    """
    for key in GOAL_TEMPLATES:
        goal = Goal(member_id=member.id, name=GOAL_TEMPLATES[key]["de"]["name"] or "Eigenes", template=key)
        _plan(session, member, goals=[goal])
    stored = {goal["template"] for goal in list_goals(session, member_id=member.id)["goals"]}
    assert stored == set(GOAL_TEMPLATES)


# ============================================================ changing a goal after it is named
#
# The owner: "If I have a Ziel, I can not change it afterwards." Verified before building: `/api/goals`
# carried GET and POST and nothing else, and `services/goals.py` had no function that wrote to a Goal.
# `services/goals.revise_goal` carries the argument for why this is an UPDATE plus a correcting Decision
# rather than a superseding row.


def test_a_goal_can_be_changed(session, member_with_plan):
    member, house, *_ = member_with_plan
    result = revise_goal(
        session,
        member_id=member.id,
        goal_id=house.id,
        changes={"target_date": date(2035, 6, 1), "name": "Wohneigentum, später"},
        question="Zieldatum verschieben?",
        choice="Ja, auf 2035.",
    )
    session.commit()
    assert result["changed"] == ["name", "target_date"]
    assert house.target_date == date(2035, 6, 1)
    assert house.name == "Wohneigentum, später"


def test_changing_a_goal_writes_a_decision_that_corrects_the_prior_one(session, member_with_plan):
    """R-040 in the shape R-040 asks for: the new record references the prior one, and the prior one is
    left exactly as it was written.

    **Planted violation:** dropped `corrects_id=` from the `mutate_plan` call in `revise_goal`. Failed on
    `corrects_id is None`. Restored.
    """
    member, house, *_ = member_with_plan
    prior = session.execute(
        select(Decision).join(Decision.linked_goals).where(Goal.id == house.id)
    ).scalars().all()
    assert len(prior) == 1, "the fixture no longer writes exactly one decision"

    result = revise_goal(
        session, member_id=member.id, goal_id=house.id,
        changes={"target_amount": 250000.0},
        question="Zielbetrag festhalten?", choice="250 000.",
    )
    session.commit()

    decision = result["decision"]
    assert decision.corrects_id == prior[0].id
    assert house in decision.linked_goals
    # The prior record is untouched, which is the whole of R-040 and is enforced by trigger as well.
    assert prior[0].choice == "Ja"


def test_the_prior_values_survive_in_the_decision(session, member_with_plan):
    """The cost of choosing an UPDATE over a superseding row, and how it is paid.

    An UPDATE loses what the goal used to be, and a record of a change that cannot say what changed is a
    poor record. Both states go into the Decision, in C-06's own label/consequence shape plus a
    machine-readable `values` map — so the earlier state is readable rather than reconstructable.

    **Planted violation:** removed `options_considered=` from the `mutate_plan` call. Failed on the empty
    list. Restored.
    """
    member, house, *_ = member_with_plan
    before = house.target_date.isoformat()

    result = revise_goal(
        session, member_id=member.id, goal_id=house.id,
        changes={"target_date": date(2035, 6, 1)},
        question="Verschieben?", choice="Ja.",
    )
    session.commit()

    options = result["decision"].options_considered
    assert len(options) == 2
    for option in options:
        # C-06's shape, because this is the same kind of statement — two options and what follows from each.
        assert option["label"] and option["consequence"]
    assert options[0]["values"]["target_date"] == before, "the prior target date is not recoverable"
    assert options[1]["values"]["target_date"] == "2035-06-01"


def test_a_revision_that_changes_nothing_is_refused(session, member_with_plan):
    """A Decision saying a change was made when none was is permanent (R-040) and makes S-07 less true.

    **Planted violation:** returned early with the existing goal instead of raising. The test failed by
    not raising, and a second assertion — that no Decision was written — caught the version that raised
    after writing one. Restored.
    """
    member, house, *_ = member_with_plan
    before = session.execute(select(Decision)).scalars().all()

    with pytest.raises(NothingToChange):
        revise_goal(
            session, member_id=member.id, goal_id=house.id,
            changes={"name": house.name},
            question="Nichts ändern?", choice="Nichts.",
        )
    session.rollback()
    assert len(session.execute(select(Decision)).scalars().all()) == len(before)


def test_another_members_goal_cannot_be_changed(session, member):
    """A81's reasoning one level down: a wrong id and someone else's goal are one refusal.

    **Planted violation:** dropped `or goal.member_id != member_id` from the lookup. The stranger's goal
    was renamed and the test failed on the raise. Restored.
    """
    from eigentlich.services import register_member

    stranger = register_member(session, age_at_registration=52, display_name="Fremd")
    session.commit()
    theirs = Goal(member_id=stranger.id, name="Nicht Ihres")
    _plan(session, stranger, goals=[theirs])

    with pytest.raises(GoalNotFound):
        revise_goal(
            session, member_id=member.id, goal_id=theirs.id,
            changes={"name": "Jetzt meines"},
            question="Umbenennen?", choice="Ja.",
        )
    session.rollback()
    assert theirs.name == "Nicht Ihres"


def test_a_template_that_does_not_exist_is_refused(session, member_with_plan):
    """`Goal.template` is read against `GOAL_TEMPLATES` by every surface that renders it, so a key nothing
    resolves would render as no template while looking like one in the database."""
    member, house, *_ = member_with_plan
    with pytest.raises(ValueError):
        revise_goal(
            session, member_id=member.id, goal_id=house.id,
            changes={"template": "frugal_maximalism"},
            question="Vorlage setzen?", choice="Ja.",
        )
    session.rollback()


def test_a_field_that_is_not_revisable_is_refused(session, member_with_plan):
    """`member_id` is not in `REVISABLE_FIELDS`, and a goal does not move between members.

    **Planted violation:** added `member_id` to `REVISABLE_FIELDS`. The goal moved and this failed.
    Removed.
    """
    assert "member_id" not in REVISABLE_FIELDS and "id" not in REVISABLE_FIELDS
    member, house, *_ = member_with_plan
    with pytest.raises(ValueError):
        revise_goal(
            session, member_id=member.id, goal_id=house.id,
            changes={"member_id": "somebody-else"},
            question="Verschieben?", choice="Ja.",
        )
    session.rollback()
    assert house.member_id == member.id


def test_the_funding_can_be_changed_and_cleared(session, member_with_plan):
    """R-030 makes an unfunded goal a legitimate state, so clearing the funding has to be expressible —
    and `None` (not stated) has to stay different from `[]` (nothing funds this)."""
    member, house, courage, securities = member_with_plan

    revise_goal(
        session, member_id=member.id, goal_id=house.id, funded_by_position_ids=[],
        changes={}, question="Deckung lösen?", choice="Ja.",
    )
    session.commit()
    assert house.funded_by == []
    # The other goal still names the same position: nothing was taken away from it (R-030).
    assert courage.funded_by == [securities]

    revise_goal(
        session, member_id=member.id, goal_id=house.id, funded_by_position_ids=[securities.id],
        changes={}, question="Wieder decken?", choice="Ja.",
    )
    session.commit()
    assert house.funded_by == [securities]


def test_c09_still_covers_the_revision(session, member_with_plan):
    """The revision writes through `mutate_plan`, so C-09 is satisfied by construction.

    **This is the plant that matters**, and it is the reason `revise_goal` does not simply `setattr`: the
    same field written outside a `mutate_plan` raises. Verified here rather than asserted, because "the
    guard would have caught it" is the claim A72 found to be false for three other paths.
    """
    member, house, *_ = member_with_plan
    house.name = "Ohne Entscheid geändert"
    with pytest.raises(PlanMutationWithoutDecision):
        session.flush()
    session.rollback()
