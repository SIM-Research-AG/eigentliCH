"""When a household closes. Separation is a first-class case and a data-separation rule, not a UX one.

Item 6's five rules, one section each, plus the two refusals. The rule that gets the most tests is the
fourth — a jointly-owned goal is frozen and flagged, and *nothing here divides it* — because that is the
one where a helpful-looking rule would do real harm.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.models import ADULT, DEPENDANT, Decision, Goal, Household, HouseholdMember
from eigentlich.services import household as household_service
from eigentlich.services import register_member
from eigentlich.services import version as version_service
from eigentlich.services.derive import GOAL_FROZEN_FOR_DIVISION, derive_action_items
from eigentlich.services.goals import GoalIsFrozen, goal_payload, revise_goal
from eigentlich.services.household import (
    AlreadyClosed,
    CompositionNotStated,
    NotSeparable,
    Person,
)
from eigentlich.services.plan import mutate_plan

MARCH = date(2027, 3, 14)
CLOSING = date(2028, 1, 31)


@pytest.fixture()
def store(tmp_path):
    from eigentlich.services.vault import VaultStore

    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def partner(session):
    other = register_member(session, age_at_registration=39, display_name="Anna A.")
    session.commit()
    return other


@pytest.fixture()
def couple(session, member, partner):
    """A two-account household with a child, and one goal of each kind of ownership."""
    house = household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Anna", kind=ADULT, member_id=partner.id),
            Person(label="Lena", kind=DEPENDANT),
        ],
        as_of=MARCH,
    )
    session.commit()

    mine = [one for one in house.members if one.member_id == member.id][0]
    hers = [one for one in house.members if one.member_id == partner.id][0]

    with mutate_plan(
        session, member_id=member.id, question="Record the goals?", choice="Yes"
    ) as decision:
        shared = Goal(member_id=member.id, name="Wohneigentum", target_amount=1_500_000.0)
        shared.owners.extend([mine, hers])
        solo = Goal(member_id=member.id, name="Mutgeld", target_amount=40_000.0)
        solo.owners.append(mine)
        orphan = Goal(member_id=member.id, name="Reserve", target_amount=20_000.0)
        session.add_all([shared, solo, orphan])
        decision.linked_goals.extend([shared, solo, orphan])
    session.commit()

    return {"house": house, "mine": mine, "hers": hers}


def _goal(session, name):
    return session.execute(select(Goal).where(Goal.name == name)).scalars().one()


# ============================================================ 1. closed, not deleted


def test_the_household_is_closed_and_not_deleted(session, member, couple):
    house_id = couple["house"].id
    report = household_service.close(
        session, household_id=house_id, closing_date=CLOSING, author_ref="curator:weber"
    )
    session.commit()

    stored = session.get(Household, house_id)
    assert stored is not None
    assert stored.closed_on == CLOSING
    assert report.closing_date == CLOSING


def test_every_plan_version_made_while_it_was_open_stays_attached(session, member, couple):
    """The versioning promise, kept for exactly the members who most need it."""
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    version_id, house_id = captured.id, couple["house"].id

    household_service.close(session, household_id=house_id, closing_date=CLOSING)
    session.commit()

    session.expire_all()
    stored = version_service.history(session, member_id=member.id)[-1]
    assert stored.id == version_id
    assert stored.household_id == house_id
    assert stored.household_as_of == MARCH


def test_closing_writes_the_decision_c09_requires(session, member, couple):
    before = len(session.execute(select(Decision)).scalars().all())
    household_service.close(
        session,
        household_id=couple["house"].id,
        closing_date=CLOSING,
        author="curator",
        author_ref="curator:weber",
    )
    session.commit()

    decisions = session.execute(select(Decision).order_by(Decision.created_at)).scalars().all()
    assert len(decisions) == before + 1
    latest = decisions[-1]
    assert latest.author == "curator"
    assert CLOSING.isoformat() in latest.question
    assert latest.linked_households


# ============================================================ 2. a new single-member household each


def test_each_adult_with_an_account_gets_a_new_single_member_household(
    session, member, partner, couple
):
    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    assert set(report.successors) == {member.id, partner.id}
    for member_id, successor_id in report.successors.items():
        successor = session.get(Household, successor_id)
        assert successor.succeeds_household_id == couple["house"].id
        assert successor.composition_as_of == CLOSING
        assert successor.closed_on is None
        assert [one.member_id for one in successor.members] == [member_id]
        assert successor.members[0].kind == ADULT


def test_the_successor_is_what_current_returns_afterwards(session, member, partner, couple):
    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    for who in (member, partner):
        live = household_service.current(session, member_id=who.id)
        assert live is not None
        assert live.id == report.successors[who.id]
        assert live.composition_as_of == CLOSING


def test_an_adult_without_an_account_gets_no_successor_and_is_named(session, member):
    """Not silently skipped. There is no plan to show a person the product cannot authenticate."""
    house = household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Anna", kind=ADULT),
        ],
        as_of=MARCH,
    )
    session.commit()

    report = household_service.close(session, household_id=house.id, closing_date=CLOSING)
    session.commit()

    assert list(report.successors) == [member.id]
    assert report.without_an_account == ("Anna",)


def test_the_old_membership_rows_are_marked_as_left_rather_than_removed(session, member, couple):
    house_id = couple["house"].id
    household_service.close(session, household_id=house_id, closing_date=CLOSING)
    session.commit()

    rows = session.execute(
        select(HouseholdMember).where(HouseholdMember.household_id == house_id)
    ).scalars().all()
    assert len(rows) == 3
    assert all(row.left_on == CLOSING for row in rows)


# ============================================================ 3. shared history, frozen, readable by both


def test_both_members_still_read_the_shared_history_and_neither_reads_the_others_plan(
    session, store, member, partner, couple
):
    """Rule 5, measured on the read rule rather than asserted.

    Each member reads their own successor and the closed household they shared. Nothing of the other's
    afterwards, because the successors are separate households.
    """
    from eigentlich.services.export import export_member

    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    mine = export_member(session, store, member_id=member.id)
    households_i_read = {row["household_id"] for row in mine["household_members"]}
    assert couple["house"].id in households_i_read, "the shared history is still mine to read"
    assert report.successors[member.id] in households_i_read
    assert report.successors[partner.id] not in households_i_read, (
        "one member must not read the other's post-closing household"
    )


def test_the_shared_history_cannot_be_edited_by_either_member(session, member, couple):
    """Frozen in the sense that matters: the plan version's own copy of the inputs and the stamp."""
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()

    # Re-stating a composition afterwards does not touch what the old version recorded.
    household_service.state(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=date(2028, 6, 1),
    )
    session.commit()

    session.expire_all()
    assert session.get(type(captured), captured.id).household_as_of == MARCH


# ============================================================ 4. joint goals are frozen, never split


def test_a_goal_owned_by_both_is_frozen_and_flagged_and_never_split(session, member, couple):
    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    shared = _goal(session, "Wohneigentum")
    assert shared.id in report.goals_frozen_for_division
    assert shared.frozen_at == CLOSING
    # Not split, not halved, not reassigned: the amount and the owners are exactly as they were.
    assert shared.target_amount == 1_500_000.0
    assert len(shared.owners) == 2
    assert report.as_dict()["division_is_a_curators_decision"] is True


def test_a_frozen_goal_cannot_be_revised(session, member, couple):
    """The freeze is a fact, not a label. Enforced at the service so a new route inherits it."""
    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()
    shared = _goal(session, "Wohneigentum")

    with pytest.raises(GoalIsFrozen) as raised:
        revise_goal(
            session,
            member_id=member.id,
            goal_id=shared.id,
            changes={"target_amount": 750_000.0},
            question="Halve it?",
            choice="Yes",
        )
    assert "curator's decision" in str(raised.value)
    session.rollback()
    assert _goal(session, "Wohneigentum").target_amount == 1_500_000.0


def test_the_frozen_goal_says_so_in_its_payload(session, member, couple):
    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()

    payload = goal_payload(session, _goal(session, "Wohneigentum"), today=CLOSING)
    assert payload["frozen_at"] == CLOSING.isoformat()
    assert payload["may_be_revised"] is False

    still_mine = goal_payload(session, _goal(session, "Mutgeld"), today=CLOSING)
    assert still_mine["frozen_at"] is None
    assert still_mine["may_be_revised"] is True


def test_a_frozen_goal_raises_an_item_whose_options_name_a_curator(session, member, couple):
    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()

    derive_action_items(session, member_id=member.id, today=CLOSING)
    session.commit()

    items = [
        one
        for one in session.execute(
            select(__import__("eigentlich.models", fromlist=["ActionItem"]).ActionItem).where(
                __import__("eigentlich.models", fromlist=["ActionItem"]).ActionItem.trigger_kind
                == GOAL_FROZEN_FOR_DIVISION
            )
        ).scalars()
    ]
    assert len(items) == 1
    assert items[0].derived_from == _goal(session, "Wohneigentum").id
    labels = " ".join(one["label"] for one in items[0].prepared_options)
    assert "Kurator" in labels
    assert len(items[0].prepared_options) == 2


def test_unfreezing_closes_the_item_without_anyone_remembering_to(session, member, couple):
    """State-based, so a curator completing the division resolves the item as a side effect of the fact."""
    from eigentlich.models import ActionItem

    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()
    derive_action_items(session, member_id=member.id, today=CLOSING)
    session.commit()

    shared = _goal(session, "Wohneigentum")
    with mutate_plan(
        session, member_id=member.id, question="Division recorded?", choice="Yes"
    ) as decision:
        shared.frozen_at = None
        decision.linked_goals.append(shared)
    session.commit()

    derive_action_items(session, member_id=member.id, today=CLOSING)
    session.commit()

    session.expire_all()
    item = session.execute(
        select(ActionItem).where(ActionItem.trigger_kind == GOAL_FROZEN_FOR_DIVISION)
    ).scalars().one()
    assert item.status == "expired"


def test_a_goal_owned_by_one_adult_follows_them_into_their_new_household(
    session, member, couple
):
    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    solo = _goal(session, "Mutgeld")
    assert solo.id in report.goals_followed
    assert solo.frozen_at is None
    assert [one.household_id for one in solo.owners] == [report.successors[member.id]]
    # The owner still names the same person, in a household that is live rather than closed.
    assert solo.owners[0].member_id == member.id
    assert solo.owners[0].label == "Ich"


def test_a_goal_with_no_owner_recorded_is_reported_and_not_assigned(session, member, couple):
    """A household that never populated the owner field cannot be divided cleanly — so it is named."""
    report = household_service.close(
        session, household_id=couple["house"].id, closing_date=CLOSING
    )
    session.commit()

    orphan = _goal(session, "Reserve")
    assert orphan.id in report.goals_without_an_owner
    assert orphan.owners == []
    assert orphan.frozen_at is None


# ============================================================ the two refusals


def test_closing_a_single_adult_household_is_refused_with_a_reason(session, member):
    house = household_service.state(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=MARCH,
    )
    session.commit()

    with pytest.raises(NotSeparable) as raised:
        household_service.close(session, household_id=house.id, closing_date=CLOSING)
    assert "nobody to separate from" in str(raised.value)


def test_a_dependant_does_not_count_towards_separability(session, member):
    house = household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Lena", kind=DEPENDANT),
        ],
        as_of=MARCH,
    )
    session.commit()

    with pytest.raises(NotSeparable):
        household_service.close(session, household_id=house.id, closing_date=CLOSING)


def test_closing_twice_is_refused(session, member, couple):
    household_service.close(session, household_id=couple["house"].id, closing_date=CLOSING)
    session.commit()

    with pytest.raises(AlreadyClosed) as raised:
        household_service.close(
            session, household_id=couple["house"].id, closing_date=date(2028, 6, 1)
        )
    assert "second set of successor households" in str(raised.value)


def test_closing_a_household_that_does_not_exist_is_refused(session):
    with pytest.raises(CompositionNotStated):
        household_service.close(
            session, household_id="0" * 32, closing_date=CLOSING
        )
