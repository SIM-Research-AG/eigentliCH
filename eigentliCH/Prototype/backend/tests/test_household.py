"""The household spine: composition is stated, dated, covered by a Decision, and never guessed.

Written against the three refusals in `services/household.py`'s docstring rather than against its happy
path, because the happy path is two inserts and the refusals are the design.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.db import PlanMutationWithoutDecision
from eigentlich.models import (
    ADULT,
    DEPENDANT,
    Decision,
    Goal,
    Household,
    HouseholdMember,
)
from eigentlich.services import household as household_service
from eigentlich.services.household import (
    CompositionNotStated,
    InvalidComposition,
    Person,
)

MARCH = date(2027, 3, 14)


@pytest.fixture()
def store(tmp_path):
    from eigentlich.services.vault import VaultStore

    return VaultStore(tmp_path / "vault")


def _single(member, *, as_of=MARCH, **kwargs) -> list[Person]:
    return [Person(label="Ich", kind=ADULT, member_id=member.id)]


# ============================================================ stating one


def test_a_single_member_household_is_the_same_model_with_one_row_in_it(session, member):
    """Journey & Design page 1: "The single-member case is not a lesser mode"."""
    house = household_service.state(
        session, member_id=member.id, people=_single(member), as_of=MARCH
    )
    session.commit()

    assert house.composition_as_of == MARCH
    assert house.stated_by == "member"
    assert house.closed_on is None
    assert [p.kind for p in house.members] == [ADULT]
    assert household_service.adults(house)[0].member_id == member.id


def test_a_couple_with_a_dependant_records_all_three(session, member):
    house = household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Anna", kind=ADULT),
            Person(label="Lena", kind=DEPENDANT),
        ],
        as_of=MARCH,
    )
    session.commit()

    described = household_service.describe(house)
    assert described["stated"] is True
    assert [p["label"] for p in described["adults"]] == ["Ich", "Anna"]
    assert [p["label"] for p in described["dependants"]] == ["Lena"]
    # The partner has no account and is a full member of the household anyway.
    assert described["adults"][1]["has_account"] is False


def test_the_as_of_date_is_the_one_the_composition_describes_not_today(session, member):
    """A curator recording last week's session stamps last week.

    The whole currency mechanism measures from this date, so a default of `today` would make every
    horizon judgement downstream run from the wrong end.
    """
    last_week = date(2026, 8, 27)
    house = household_service.state(
        session,
        member_id=member.id,
        people=_single(member),
        as_of=last_week,
        stated_by="curator",
        author_ref="curator:weber",
    )
    session.commit()

    assert house.composition_as_of == last_week
    assert house.created_at.date() != last_week  # written today, describing last week


def test_stating_a_composition_writes_the_decision_c09_requires(session, member):
    household_service.state(session, member_id=member.id, people=_single(member), as_of=MARCH)
    session.commit()

    decision = session.execute(select(Decision)).scalars().one()
    assert decision.member_id == member.id
    assert "1 adult(s), 0 dependant(s)" in decision.choice
    assert MARCH.isoformat() in decision.choice
    # The Decision names the rows it covers, which is what the C-09 guard checks against.
    assert len(decision.linked_households) == 1
    assert len(decision.linked_household_members) == 1


def test_a_household_written_without_a_decision_is_refused_by_the_guard(session, member):
    """`Household` is `PlanMutable`, so this is enforced by `db.py` rather than by this module's manners."""
    session.add(Household(composition_as_of=MARCH, stated_by="member"))
    with pytest.raises(PlanMutationWithoutDecision):
        session.flush()


def test_the_curator_initiated_intake_produces_the_same_shape_as_the_member_initiated_one(
    session, member
):
    """Item 3: "one code path, two initiators — record which one"."""
    house = household_service.state(
        session,
        member_id=member.id,
        people=_single(member),
        as_of=MARCH,
        stated_by="curator",
        author_ref="curator:weber",
    )
    session.commit()

    assert house.stated_by == "curator"
    decision = session.execute(select(Decision)).scalars().one()
    assert decision.author == "curator"
    assert decision.author_ref == "curator:weber"
    # Same rows, same relationships. Only the attribution differs.
    assert [p.kind for p in house.members] == [ADULT]


def test_nothing_in_the_module_branches_on_who_stated_it():
    """The moment `stated_by` becomes a condition, the two initiators stop producing the same plan.

    A grep rather than a behavioural probe, because the failure this guards against is a future `if` that
    no existing test would exercise. Assignments and the membership check in `state()` are the two places
    the name may legitimately appear.
    """
    import inspect

    source = inspect.getsource(household_service)
    offending = [
        line.strip()
        for line in source.splitlines()
        if "stated_by" in line
        and ("if " in line or "elif " in line)
        and "not in STATED_BY" not in line
    ]
    assert not offending, (
        f"`stated_by` is a record, not a condition. Branching on it: {offending}"
    )


# ============================================================ refusing to guess one


def test_an_unstated_composition_is_none_and_not_a_household_of_one(session, member):
    assert household_service.current(session, member_id=member.id) is None
    described = household_service.describe(None)
    assert described["stated"] is False
    assert described["as_of"] is None
    assert described["adults"] == []


def test_require_raises_rather_than_inventing_a_composition(session, member):
    with pytest.raises(CompositionNotStated) as raised:
        household_service.require(session, member_id=member.id)
    assert "nothing derives it" in str(raised.value)


def test_an_empty_composition_is_an_unanswered_question_not_a_single_member_household(
    session, member
):
    with pytest.raises(InvalidComposition) as raised:
        household_service.state(session, member_id=member.id, people=[], as_of=MARCH)
    assert "not the single-member case" in str(raised.value)


def test_a_household_the_member_is_not_in_is_refused(session, member):
    with pytest.raises(InvalidComposition) as raised:
        household_service.state(
            session,
            member_id=member.id,
            people=[Person(label="Anna", kind=ADULT)],
            as_of=MARCH,
        )
    assert "is not in it" in str(raised.value)


def test_a_household_of_dependants_only_is_refused(session, member):
    with pytest.raises(InvalidComposition):
        household_service.state(
            session,
            member_id=member.id,
            people=[Person(label="Lena", kind=DEPENDANT, member_id=member.id)],
            as_of=MARCH,
        )


def test_an_unknown_kind_is_refused_rather_than_stored(session, member):
    with pytest.raises(InvalidComposition) as raised:
        household_service.state(
            session,
            member_id=member.id,
            people=[Person(label="Ich", kind="child", member_id=member.id)],
            as_of=MARCH,
        )
    assert "not a household member kind" in str(raised.value)


def test_one_account_cannot_appear_twice_in_a_household(session, member):
    with pytest.raises(InvalidComposition) as raised:
        household_service.state(
            session,
            member_id=member.id,
            people=[
                Person(label="Ich", kind=ADULT, member_id=member.id),
                Person(label="Ich nochmal", kind=ADULT, member_id=member.id),
            ],
            as_of=MARCH,
        )
    assert "twice" in str(raised.value)


def test_a_blank_label_is_refused(session, member):
    with pytest.raises(InvalidComposition):
        household_service.state(
            session,
            member_id=member.id,
            people=[Person(label="   ", kind=ADULT, member_id=member.id)],
            as_of=MARCH,
        )


def test_an_unknown_initiator_is_refused(session, member):
    with pytest.raises(InvalidComposition):
        household_service.state(
            session,
            member_id=member.id,
            people=_single(member),
            as_of=MARCH,
            stated_by="the_app",
        )


# ============================================================ the schema's own guards


def test_a_household_cannot_succeed_itself(session, member):
    house = household_service.state(
        session, member_id=member.id, people=_single(member), as_of=MARCH
    )
    session.commit()

    from sqlalchemy.exc import IntegrityError

    from eigentlich.services.plan import mutate_plan

    with pytest.raises(IntegrityError):
        with mutate_plan(
            session,
            member_id=member.id,
            question="Make the household succeed itself?",
            choice="No — the CHECK refuses it",
        ) as decision:
            house.succeeds_household_id = house.id
            decision.linked_households.append(house)
        session.flush()
    session.rollback()


def test_a_closed_household_is_not_returned_as_current(session, member):
    """Closing does not delete. `current()` stops finding it; the row and its history stay."""
    house = household_service.state(
        session, member_id=member.id, people=_single(member), as_of=MARCH
    )
    session.commit()
    assert household_service.current(session, member_id=member.id) is not None

    from eigentlich.services.plan import mutate_plan

    with mutate_plan(
        session,
        member_id=member.id,
        question="Close the household?",
        choice="Yes, as of 31.01.2028",
    ) as decision:
        house.closed_on = date(2028, 1, 31)
        decision.linked_households.append(house)
    session.commit()

    assert household_service.current(session, member_id=member.id) is None
    assert session.get(Household, house.id) is not None


# ============================================================ the seventh field


def test_a_goal_carries_its_owners(session, member):
    """Whose goal it is. A link table, so "both of us" is two rows rather than a sentinel."""
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

    from eigentlich.services.plan import mutate_plan

    with mutate_plan(
        session,
        member_id=member.id,
        question="Record a shared housing goal?",
        choice="Yes, owned by both",
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=1_500_000.0)
        goal.owners.extend(house.members)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    stored = session.execute(select(Goal)).scalars().one()
    assert {o.label for o in stored.owners} == {"Ich", "Anna"}


def test_a_goal_owner_may_be_a_partner_with_no_account(session, member):
    """The owner names a household member, not a member. An unregistered partner can own their own goal."""
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
    anna = [p for p in house.members if p.member_id is None][0]

    from eigentlich.services.plan import mutate_plan

    with mutate_plan(
        session,
        member_id=member.id,
        question="Record Anna's retraining goal?",
        choice="Yes",
    ) as decision:
        goal = Goal(member_id=member.id, name="Umschulung")
        goal.owners.append(anna)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    stored = session.execute(select(Goal)).scalars().one()
    assert [o.id for o in stored.owners] == [anna.id]
    assert stored.owners[0].member_id is None


# ============================================================ erasure


def test_erasure_redacts_the_household_row_rather_than_deleting_it(session, store, member):
    """One member's erasure may not rewrite another member's stated composition.

    The couple case is the one that matters: after the member erases, the household must still say it had
    two adults in March 2027, and must not say who the second one was talking about.
    """
    from eigentlich.services.erasure import REDACTED, erase_member

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
    house_id = house.id

    report = erase_member(session, store, member_id=member.id)
    session.commit()

    assert report.redacted["household_members"] == 1

    survived = session.execute(
        select(HouseholdMember).where(HouseholdMember.household_id == house_id)
    ).scalars().all()
    # Both rows survive: the composition is still "two adults as of March 2027".
    assert len(survived) == 2
    assert session.get(Household, house_id).composition_as_of == MARCH

    erased = [row for row in survived if row.label == REDACTED]
    assert len(erased) == 1
    assert erased[0].member_id is None
    # The other member's own row is untouched — it was never this member's to destroy.
    assert {row.label for row in survived} == {REDACTED, "Anna"}


def test_the_erased_member_no_longer_has_a_current_household(session, store, member):
    from eigentlich.services.erasure import erase_member

    household_service.state(session, member_id=member.id, people=_single(member), as_of=MARCH)
    session.commit()
    # Held before the erasure: the `Member` instance is gone afterwards, and touching it raises.
    member_id = member.id

    erase_member(session, store, member_id=member_id)
    session.commit()

    assert household_service.current(session, member_id=member_id) is None


# ============================================================ A109: reading wider than erasing


def test_the_export_carries_the_whole_composition_the_member_stated(session, store, member):
    """A109. They described the household, so R-154 gives them all of it, partner and child included."""
    from eigentlich.services.export import export_member

    household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Anna", kind=ADULT),
            Person(label="Lena", kind=DEPENDANT),
        ],
        as_of=MARCH,
    )
    session.commit()

    export = export_member(session, store, member_id=member.id)
    assert {row["label"] for row in export["household_members"]} == {"Ich", "Anna", "Lena"}


def test_a_second_members_household_is_not_in_the_first_members_export(session, store, member):
    """The widening is to the member's own household, not to every household in the table."""
    from eigentlich.services.export import export_member
    from eigentlich.services import register_member

    other = register_member(session, age_at_registration=52, display_name="Somebody Else")
    session.commit()

    household_service.state(session, member_id=member.id, people=_single(member), as_of=MARCH)
    household_service.state(
        session,
        member_id=other.id,
        people=[Person(label="Fremd", kind=ADULT, member_id=other.id)],
        as_of=MARCH,
    )
    session.commit()

    export = export_member(session, store, member_id=member.id)
    assert [row["label"] for row in export["household_members"]] == ["Ich"]


def test_erasure_still_touches_only_the_erasing_members_own_row(session, store, member):
    """The other half of A109, stated as its own test because the two rules now differ.

    If `readable_predicate`'s widening ever leaked into the erasure, this is what would break: the
    partner's row would be redacted too, and a second person's stated history would be gone.
    """
    from eigentlich.services.erasure import REDACTED, erase_member

    house = household_service.state(
        session,
        member_id=member.id,
        people=[
            Person(label="Ich", kind=ADULT, member_id=member.id),
            Person(label="Anna", kind=ADULT),
            Person(label="Lena", kind=DEPENDANT),
        ],
        as_of=MARCH,
    )
    session.commit()
    house_id, member_id = house.id, member.id

    erase_member(session, store, member_id=member_id)
    session.commit()

    labels = [
        row.label
        for row in session.execute(
            select(HouseholdMember).where(HouseholdMember.household_id == house_id)
        ).scalars()
    ]
    assert sorted(labels) == sorted([REDACTED, "Anna", "Lena"])


def test_the_two_predicates_disagree_on_exactly_the_models_that_declare_it(session, member):
    """The invariant, measured rather than asserted in a comment.

    `owning_predicate`'s docstring promises one definition for both paths. A109 breaks that for exactly
    one model, so the promise is restated as: they compile to the same SQL everywhere except the models
    named in `READS_WIDER_THAN_IT_ERASES`, each with a written reason.
    """
    from eigentlich.services.member_data import (
        EXPORTED_MODELS,
        READS_WIDER_THAN_IT_ERASES,
        owning_predicate,
        readable_predicate,
    )

    differing = {
        model
        for model in EXPORTED_MODELS
        if str(owning_predicate(model, member.id)) != str(readable_predicate(model, member.id))
    }
    assert differing == set(READS_WIDER_THAN_IT_ERASES), (
        "the read rule and the erase rule may differ only where a model declares it and says why"
    )
    assert all(reason.strip() for reason in READS_WIDER_THAN_IT_ERASES.values()), (
        "a widening without a reason is a divergence nobody decided"
    )


def test_that_comparison_would_notice_an_undeclared_widening(session, member):
    """The guard on the guard. A20's shape: an emptiness never shown able to be non-empty.

    The risk being guarded is a future author widening the read rule for another model and not declaring
    it. So the plant is exactly that — a `readable_predicate` that widens `Goal` as well, with
    `READS_WIDER_THAN_IT_ERASES` left as it is — and the comparison has to report `Goal`.

    An earlier version of this test emptied the declaration table instead. That proved nothing: the real
    `readable_predicate` reads that table to decide whether to widen, so emptying it removed the widening
    too and the comparison correctly found no difference. Recorded here because the mistake is the one
    this estate keeps making — a probe that reports a uniform result across cases chosen to differ has
    usually not run.
    """
    from eigentlich.services import member_data
    from eigentlich.models import Goal as GoalModel

    def widened(model, member_id):
        if model is GoalModel:
            return GoalModel.member_id.in_(
                select(GoalModel.member_id).where(GoalModel.member_id == member_id)
            )
        return member_data.readable_predicate(model, member_id)

    differing = {
        model
        for model in member_data.EXPORTED_MODELS
        if str(member_data.owning_predicate(model, member.id)) != str(widened(model, member.id))
    }

    assert GoalModel in differing, "the comparison cannot see a widening, so it proves nothing"
    assert HouseholdMember in differing, "and it still sees the declared one"
    assert differing != set(member_data.READS_WIDER_THAN_IT_ERASES), (
        "an undeclared widening has to make the real assertion fail"
    )
