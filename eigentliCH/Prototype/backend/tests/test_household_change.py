"""How a household change is learned: declared at the review, inferred from an event.

Item 6 splits this in two and the split is the design. The declared half asks five closed questions at an
already-scheduled return. The inferred half notices something and **changes nothing** — it makes the
question worth asking, and the answer stays the member's.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.content import household_confirmation_keys
from eigentlich.models import ADULT, ActionItem, DEPENDANT, Decision, Household
from eigentlich.services import household as household_service
from eigentlich.services.derive import (
    CAUSE_NO_LONGER_HOLDS,
    HOUSEHOLD_CHANGE_INFERRED,
    HOUSEHOLD_CONFIRMATION_DUE,
    derive_action_items,
)
from eigentlich.services.household import (
    CompositionNotStated,
    InvalidConfirmation,
    Person,
    UnknownSignal,
)

STATED = date(2027, 3, 14)
WITHIN = date(2027, 9, 1)
PAST = date(2028, 6, 1)

ALL_NO = {key: False for key in household_confirmation_keys()}


def _house(session, member, *, as_of=STATED, dependants=0):
    people = [Person(label="Ich", kind=ADULT, member_id=member.id)]
    people += [Person(label=f"Kind {n}", kind=DEPENDANT) for n in range(1, dependants + 1)]
    house = household_service.state(
        session, member_id=member.id, people=people, as_of=as_of
    )
    session.commit()
    return house


def _items(session, member, kind):
    return list(
        session.execute(
            select(ActionItem).where(
                ActionItem.member_id == member.id, ActionItem.trigger_kind == kind
            )
        ).scalars()
    )


# ============================================================ the declared half


def test_the_confirmation_asks_five_or_six_closed_items(session):
    """Item 6: "five or six yes/no items, not a freeform prompt"."""
    keys = household_confirmation_keys()
    assert 5 <= len(keys) <= 6
    assert len(set(keys)) == len(keys)


def test_all_no_re_dates_the_same_people_and_resets_the_horizon(session, member):
    house = _house(session, member)
    original_id = house.id

    result = household_service.confirm(
        session, member_id=member.id, answers=ALL_NO, as_of=WITHIN
    )
    session.commit()

    assert result.unchanged is True
    assert result.changed == ()
    # The SAME row, re-dated. Not a new household: nothing about it changed.
    assert result.household.id == original_id
    assert result.household.composition_as_of == WITHIN
    assert session.execute(select(Household)).scalars().all() == [house]


def test_re_dating_does_not_rewrite_what_a_past_version_assumed(session, member):
    """The reason a confirmation can safely update in place: each version carries its own copied stamp."""
    from eigentlich.services import version as version_service

    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    household_service.confirm(session, member_id=member.id, answers=ALL_NO, as_of=WITHIN)
    session.commit()

    session.expire_all()
    assert version_service.history(session, member_id=member.id)[0].household_as_of == STATED


def test_a_confirmation_writes_the_decision_c09_requires(session, member):
    _house(session, member)
    before = len(session.execute(select(Decision)).scalars().all())

    household_service.confirm(
        session, member_id=member.id, answers=ALL_NO, as_of=WITHIN, stated_by="curator",
        author_ref="curator:weber",
    )
    session.commit()

    decisions = session.execute(select(Decision).order_by(Decision.created_at)).scalars().all()
    assert len(decisions) == before + 1
    latest = decisions[-1]
    assert latest.author == "curator"
    assert "Confirmed unchanged" in latest.choice
    assert STATED.isoformat() in latest.choice and WITHIN.isoformat() in latest.choice
    assert latest.linked_households


def test_any_yes_changes_nothing_and_says_a_restatement_is_needed(session, member):
    """A yes/no cannot say who joined or in what role, so patching from one would invent a fact."""
    house = _house(session, member)
    before = len(session.execute(select(Decision)).scalars().all())

    answers = dict(ALL_NO, someone_joined=True)
    result = household_service.confirm(
        session, member_id=member.id, answers=answers, as_of=WITHIN
    )
    session.commit()

    assert result.unchanged is False
    assert result.changed == ("someone_joined",)
    assert result.as_dict()["restatement_needed"] is True
    # Nothing moved: not the date, not the people, not the record.
    assert house.composition_as_of == STATED
    assert len(session.execute(select(Decision)).scalars().all()) == before
    assert len(house.members) == 1


def test_the_changed_items_come_back_in_the_published_order(session, member):
    _house(session, member)
    result = household_service.confirm(
        session,
        member_id=member.id,
        answers=dict(ALL_NO, care_began=True, someone_left=True),
        as_of=WITHIN,
    )
    assert result.changed == ("someone_left", "care_began")


def test_a_confirmation_must_answer_exactly_the_published_items(session, member):
    _house(session, member)

    with pytest.raises(InvalidConfirmation) as raised:
        household_service.confirm(
            session, member_id=member.id, answers={"someone_joined": False}, as_of=WITHIN
        )
    assert "Missing" in str(raised.value)

    with pytest.raises(InvalidConfirmation) as raised:
        household_service.confirm(
            session,
            member_id=member.id,
            answers=dict(ALL_NO, invented_item=False),
            as_of=WITHIN,
        )
    assert "Not published" in str(raised.value)


def test_a_non_boolean_answer_is_refused(session, member):
    _house(session, member)
    with pytest.raises(InvalidConfirmation):
        household_service.confirm(
            session,
            member_id=member.id,
            answers=dict(ALL_NO, someone_joined=None),
            as_of=WITHIN,
        )


def test_there_is_nothing_to_confirm_before_a_composition_is_stated(session, member):
    with pytest.raises(CompositionNotStated):
        household_service.confirm(
            session, member_id=member.id, answers=ALL_NO, as_of=WITHIN
        )


# ============================================================ the confirmation-due item


def test_the_confirmation_becomes_due_when_the_horizon_passes(session, member):
    house = _house(session, member)

    derive_action_items(session, member_id=member.id, today=WITHIN)
    session.commit()
    assert _items(session, member, HOUSEHOLD_CONFIRMATION_DUE) == []

    derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()
    due = _items(session, member, HOUSEHOLD_CONFIRMATION_DUE)
    assert len(due) == 1
    assert due[0].derived_from == house.id
    assert due[0].status == "open"
    # Two prepared options, each with a consequence — C-06.
    assert len(due[0].prepared_options) == 2
    assert all(one["consequence"].strip() for one in due[0].prepared_options)


def test_a_member_with_no_composition_is_not_asked_to_confirm_one(session, member):
    """Raising it here would ask them to confirm something they never said."""
    derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()
    assert _items(session, member, HOUSEHOLD_CONFIRMATION_DUE) == []


def test_confirming_closes_the_item_and_the_next_expiry_reopens_the_same_row(session, member):
    """The annual cadence falls out of the store rather than out of a scheduler."""
    _house(session, member)

    derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()
    first = _items(session, member, HOUSEHOLD_CONFIRMATION_DUE)[0]
    first_id = first.id

    household_service.confirm(session, member_id=member.id, answers=ALL_NO, as_of=PAST)
    session.commit()
    derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()

    session.expire_all()
    assert session.get(ActionItem, first_id).status == CAUSE_NO_LONGER_HOLDS

    # A year on from the new date, the cause holds again — and it is the same row, reopened.
    derive_action_items(session, member_id=member.id, today=date(2029, 7, 1))
    session.commit()
    session.expire_all()
    assert session.get(ActionItem, first_id).status == "open"
    assert len(_items(session, member, HOUSEHOLD_CONFIRMATION_DUE)) == 1


def test_the_derivation_is_idempotent_over_the_new_kind(session, member):
    _house(session, member)
    derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()
    second = derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()

    assert second["created"] == []
    assert second["closed"] == []
    assert second["reopened"] == []


# ============================================================ the inferred half


def test_an_inferred_flag_changes_nothing(session, member):
    """The whole point: the app noticed something and has concluded nothing."""
    house = _house(session, member)
    before_people = len(house.members)
    before_decisions = len(session.execute(select(Decision)).scalars().all())

    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    assert house.composition_as_of == STATED
    assert len(house.members) == before_people
    # No Decision: nothing was decided, and a flag is not a change.
    assert len(session.execute(select(Decision)).scalars().all()) == before_decisions

    flags = _items(session, member, HOUSEHOLD_CHANGE_INFERRED)
    assert len(flags) == 1
    assert flags[0].derived_from == "dated_obligation_added"
    assert flags[0].due_date is None


def test_a_flag_can_be_raised_before_any_composition_exists(session, member):
    """A signal does not wait for an intake. Nothing is asserted about a household that has none."""
    flag = household_service.flag_inferred_change(
        session, member_id=member.id, signal="partner_invited"
    )
    session.commit()
    assert flag is not None
    assert household_service.current(session, member_id=member.id) is None


def test_the_same_signal_firing_twice_does_not_raise_a_second_flag(session, member):
    _house(session, member)
    first = household_service.flag_inferred_change(
        session, member_id=member.id, signal="partner_invited"
    )
    session.commit()
    again = household_service.flag_inferred_change(
        session, member_id=member.id, signal="partner_invited"
    )
    session.commit()

    assert again.id == first.id
    assert len(_items(session, member, HOUSEHOLD_CHANGE_INFERRED)) == 1


def test_a_dismissed_flag_is_not_re_raised_by_the_same_signal(session, member):
    """The difference between a prepared question and a nag. R-175."""
    _house(session, member)
    flag = household_service.flag_inferred_change(
        session, member_id=member.id, signal="partner_invited"
    )
    session.commit()
    flag.status = "dismissed"
    session.commit()

    assert (
        household_service.flag_inferred_change(
            session, member_id=member.id, signal="partner_invited"
        )
        is None
    )
    session.expire_all()
    assert _items(session, member, HOUSEHOLD_CHANGE_INFERRED)[0].status == "dismissed"


def test_an_unpublished_signal_is_refused(session, member):
    _house(session, member)
    with pytest.raises(UnknownSignal) as raised:
        household_service.flag_inferred_change(
            session, member_id=member.id, signal="the_member_looked_sad"
        )
    assert "not a published household-change signal" in str(raised.value)


def test_confirming_unchanged_closes_the_inferred_flag(session, member):
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    result = household_service.confirm(
        session, member_id=member.id, answers=ALL_NO, as_of=WITHIN
    )
    session.commit()

    assert result.flags_closed == ("dated_obligation_added",)
    session.expire_all()
    assert _items(session, member, HOUSEHOLD_CHANGE_INFERRED)[0].status == (
        CAUSE_NO_LONGER_HOLDS
    )


def test_a_yes_answer_leaves_the_flag_prepared_for_the_next_return(session, member):
    """Item 6: the flag surfaces at the next return with the question already prepared. It has not been
    answered until the composition is restated."""
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    household_service.confirm(
        session,
        member_id=member.id,
        answers=dict(ALL_NO, someone_joined=True),
        as_of=WITHIN,
    )
    session.commit()

    session.expire_all()
    assert _items(session, member, HOUSEHOLD_CHANGE_INFERRED)[0].status == "open"


def test_restating_the_composition_closes_the_flag(session, member):
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    _house(session, member, as_of=WITHIN, dependants=1)

    session.expire_all()
    assert _items(session, member, HOUSEHOLD_CHANGE_INFERRED)[0].status == (
        CAUSE_NO_LONGER_HOLDS
    )


def test_a_signal_firing_after_a_confirmation_makes_the_question_live_again(session, member):
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()
    household_service.confirm(session, member_id=member.id, answers=ALL_NO, as_of=WITHIN)
    session.commit()

    again = household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()
    assert again.status == "open"
    assert len(_items(session, member, HOUSEHOLD_CHANGE_INFERRED)) == 1


def test_the_derivation_never_creates_or_closes_an_inferred_flag(session, member):
    """Its cause is an event, so `derive_action_items` has nothing to recompute and must not guess.

    The failure this guards: a derivation that closed the flag because it could not find a cause would
    silently discard the only record that a signal ever fired.
    """
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    result = derive_action_items(session, member_id=member.id, today=PAST)
    session.commit()

    assert all(
        item.trigger_kind != HOUSEHOLD_CHANGE_INFERRED
        for group in result.values()
        for item in group
    )
    session.expire_all()
    assert _items(session, member, HOUSEHOLD_CHANGE_INFERRED)[0].status == "open"


def test_the_computed_kinds_are_every_derived_kind_but_the_inferred_flag(session):
    """Stated as its own tuple so the exception is declared rather than being an absence in a dict."""
    from eigentlich.services.derive import COMPUTED_TRIGGER_KINDS, DERIVED_TRIGGER_KINDS

    assert set(DERIVED_TRIGGER_KINDS) - set(COMPUTED_TRIGGER_KINDS) == {
        HOUSEHOLD_CHANGE_INFERRED
    }


# ============================================================ what the inference layer can see


def test_the_unobservable_signals_are_published_with_their_reason(session, member):
    """An empty inference layer and a broken one look the same, so the reasons are the difference."""
    reported = household_service.signals(session, member_id=member.id)

    published = {one["key"]: one for one in reported["published"]}
    assert len(published) >= 5
    for entry in published.values():
        if not entry["observable_now"]:
            assert entry["not_yet"], f"{entry['key']} is unobservable with no reason given"
        else:
            assert entry["not_yet"] is None


def test_the_report_says_which_signals_have_been_raised_for_this_member(session, member):
    _house(session, member)
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    published = {
        one["key"]: one
        for one in household_service.signals(session, member_id=member.id)["published"]
    }
    assert published["dated_obligation_added"]["raised"] == "open"
    assert published["partner_invited"]["raised"] is None
