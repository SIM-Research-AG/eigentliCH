"""R-152's other sources: action items derived from the plan itself.

`services/derive.py` is the half of R-152 that was missing. Expiry dates are the *primary* source of
action items and they were the only one, so a member who had recorded positions and goals and uploaded no
dated document read an empty `/api/actions` forever.

**Every guard in this file was verified by planting the violation it names, watching it fail, and
restoring the fix.** Each such test carries a `Planted violation:` line saying what was broken and what
went red. That is not decoration: five guarantees in this estate stopped holding while the suite stayed
green (A20, A63, A66, A63 again, A71), and every one of them was absence-shaped. A test that asserts
something is absent must be proven able to detect its presence.

**The largest section is not the positives.** It is `test_no_derived_string_carries_a_recommending_shape`
and its firing proof, because `boundary.check_answer` — which C-01 is enforced by everywhere else — is
structurally unable to fire on the register this module writes in. See the long note above that test. A
green `check_answer` over these strings would have been A20's hazard exactly: a check that passes because
nothing it looks for can occur.
"""

from __future__ import annotations

import ast
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from eigentlich import boundary
from eigentlich.models import ActionItem, Decision, Goal, Position, utcnow
from eigentlich.models.action import DERIVED_CAUSE_INDEX

#: What `services/derive.py` writes, asserted here because this module is what writes it.
#:
#: **This was `OPTIONS_DERIVE_WRITES`, imported from the model, until 20 September 2026.** C-06 made it
#: a claim about the store — a CHECK counting the array and two triggers walking its contents — and A168
#: dropped all three. The number did not stop mattering: an action item with one option is an instruction
#: rather than a decision, and this module still writes two. What changed is who guarantees it. It is now
#: a property of the code that writes action items, checked here, and nothing stops a different writer
#: from doing otherwise.
OPTIONS_DERIVE_WRITES = 2
from eigentlich.models import ADULT
from eigentlich.services import household as household_service
from eigentlich.services import store_item
from eigentlich.services.household import Person as HouseholdPerson
from eigentlich.services.derive import (
    CAPITAL_TYPE_EMPTY,
    CAUSE_NO_LONGER_HOLDS,
    DERIVED_TRIGGER_KINDS,
    GOAL_TARGET_DATE_PASSED,
    GOAL_UNFUNDED,
    ONBOARDING_ANSWER_SKIPPED,
    POSITION_UNREVISED,
    causes_by_item_id,
    derive_action_items,
    every_member_facing_string,
    prepared_options_for,
)
from eigentlich.services.onboarding import complete as onboarding_complete, record_answer
from eigentlich.services.plan import mutate_plan
from eigentlich.services.vault import VaultStore

DERIVE_SOURCE = Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "derive.py"

#: The fixed "today" every derivation in this file is run with. Nothing here reads the wall clock: a
#: suite whose result depends on the date it is run on is a suite that goes red in January for no
#: reason.
TODAY = date(2027, 6, 1)

#: A target date behind TODAY.
PASSED = date(2027, 1, 15)

#: The date a caller supplies for the quiet-position derivation. After `DECIDED_AT`, so that the
#: Decision which created the position does not itself count as having reviewed it since.
UNREVISED_BEFORE = date(2026, 6, 1)


# ============================================================================== fixtures


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


#: When the helpers below date the Decision they write. Long before anything else in this file, so that
#: creating a position or a goal does not by itself count as having reviewed it.
#:
#: **This has to be controllable, and why is the most useful thing in this file to know.** Every Position
#: and Goal is created through `mutate_plan`, so every one of them has a Decision naming it, dated at
#: creation. Both date-based derivations ask whether a decision has been recorded SINCE — so a goal
#: created with an already-past target date is never derived, and a position recorded today is never
#: quiet however long ago it started. That is correct behaviour rather than a bug to design around: the
#: member has just looked at it, and asking them to review what they entered a minute ago is the nag
#: R-175 forbids. But a test that let the creation Decision default to `utcnow()` could not express the
#: case where the date passed AFTERWARDS, which is the case the derivation exists for.
DECIDED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def add_position(session, member, *, decided_at=DECIDED_AT, **kwargs):
    """A position, with the Decision C-09 requires. Never a bare `session.add`."""
    fields = {"role": "income", "capital_type": "human", "label": "Anstellung"}
    fields.update(kwargs)
    with mutate_plan(
        session, member_id=member.id, question="Position erfassen?", choice="Ja"
    ) as decision:
        decision.created_at = decided_at
        position = Position(member_id=member.id, **fields)
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    return position


def add_goal(session, member, *, decided_at=DECIDED_AT, **kwargs):
    fields = {"name": "Wohnung"}
    fields.update(kwargs)
    with mutate_plan(session, member_id=member.id, question="Ziel erfassen?", choice="Ja") as decision:
        decision.created_at = decided_at
        goal = Goal(member_id=member.id, **fields)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()
    return goal


def set_funding(session, member, goal, position, *, attach: bool):
    """Attach or detach a funding position, with the Decision C-09 requires.

    **Two ordering traps, both hit while writing this, both worth the helper.** `decision.linked_goals`
    and `goal.funded_by` are lazy relationships, so touching either emits a SELECT — and a SELECT
    autoflushes. Mutate the goal first and the autoflush finds a dirty `PlanMutable` the Decision does not
    yet cover, so C-09 fires correctly on a caller who was going to link it a line later. Link first and
    the autoflush persists the Decision, which then leaves `session.new` — so the flush that carries the
    goal's change sees no new Decision and C-09 fires again, for the opposite reason.

    `no_autoflush` is what makes it one flush: the Decision and the change it accounts for reach the
    database together, which is what C-09 means by "the same transaction".
    """
    with mutate_plan(
        session,
        member_id=member.id,
        question="Position diesem Ziel zuordnen?",
        choice="Ja" if attach else "Nein",
    ) as decision, session.no_autoflush:
        decision.linked_goals.append(goal)
        if attach:
            goal.funded_by.append(position)
        else:
            goal.funded_by.remove(position)
    session.commit()


def kinds(session, member, status="open"):
    """`{(trigger_kind, derived_from)}` for the member's items at one status."""
    rows = session.execute(
        select(ActionItem).where(ActionItem.member_id == member.id)
    ).scalars().all()
    return {(r.trigger_kind, r.derived_from) for r in rows if r.status == status}


# ============================================================================== the derivations fire
#
# One test per derivation, and immediately after it the negative: the same shape with the cause removed
# must produce nothing. A20's rule — both directions, always.


def test_a_goal_with_no_funding_position_is_derived(session, member):
    """R-030 permits an unfunded goal, so this is an observation and not an error.

    **Planted violation:** made `_unfunded_goals` return `set()`. Failed here on the empty result set.
    Restored.
    """
    goal = add_goal(session, member)
    result = derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member)
    assert [item.trigger_kind for item in result["created"]].count(GOAL_UNFUNDED) == 1


def test_a_funded_goal_is_not_derived_as_unfunded(session, member):
    """The negative direction. Without this, `_unfunded_goals` returning every goal would pass."""
    position = add_position(session, member)
    goal = add_goal(session, member)
    set_funding(session, member, goal, position, attach=True)

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_UNFUNDED, goal.id) not in kinds(session, member)


def test_a_goal_funded_only_by_a_deactivated_position_is_unfunded(session, member):
    """R-122 keeps a deactivated position in history; it does not keep it carrying a goal."""
    position = add_position(session, member, active=False)
    goal = add_goal(session, member)
    set_funding(session, member, goal, position, attach=True)

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member)


def test_a_goal_whose_target_date_has_passed_is_derived(session, member):
    """The date went by after the goal was recorded, and nothing has been decided since.

    **Planted violation:** flipped `goal.target_date >= today` to `<=`. Failed here. Restored.
    """
    goal = add_goal(session, member, target_date=PASSED)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_TARGET_DATE_PASSED, goal.id) in kinds(session, member)


def test_a_goal_whose_target_date_is_ahead_is_not_derived(session, member):
    """No horizon and no "approaching" — C-02. A date that has not passed is simply a date."""
    goal = add_goal(session, member, target_date=TODAY + timedelta(days=1))
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_TARGET_DATE_PASSED, goal.id) not in kinds(session, member)


def test_a_decision_recorded_since_the_date_answers_it(session, member):
    """The member looked at the goal after the date went by and recorded what they concluded. S-07 is
    where that answer lives, and an item repeating the question would be a nag.

    **Planted violation:** dropped the `recorded`/`continue` branch from `_goals_past_their_date`. Failed
    here. Restored.
    """
    # The Decision `add_goal` writes is dated AFTER the target date here, which is the member having
    # looked at the goal once the date had gone by.
    goal = add_goal(
        session, member, target_date=PASSED, decided_at=datetime(2027, 2, 1, tzinfo=timezone.utc)
    )
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_TARGET_DATE_PASSED, goal.id) not in kinds(session, member)


def test_a_quiet_position_is_derived_only_when_the_caller_supplies_the_date(session, member):
    """C-02, and the one derivation that needs a horizon.

    "Long past" is a threshold and a threshold is an assumption nobody has published — `store_item`
    refused to gate the expiry items on one for exactly this reason. So the date is the caller's, with no
    default, the way `expiring_items` takes `on_or_before`.

    **Planted violation:** gave `unrevised_before` a default of `today - 365 days`. The first assertion
    failed, which is the point: a module that invents the horizon cannot pass this test.
    """
    position = add_position(session, member, started_on=date(2018, 1, 1))

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (POSITION_UNREVISED, position.id) not in kinds(session, member), (
        "no date was supplied, so this module must not have invented one"
    )

    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert (POSITION_UNREVISED, position.id) in kinds(session, member)


def test_not_supplying_the_date_does_not_close_the_quiet_position_items(session, member):
    """Not having asked the question is not an answer to it.

    A derivation that closed its items whenever its parameter was absent would silently retire everything
    it had ever raised on the next ordinary read — and the read path in `api/main.py` supplies no date.

    **Planted violation:** put `POSITION_UNREVISED: set()` into `causes` unconditionally instead of behind
    the `if`. Failed here on the item coming back closed. Restored.
    """
    position = add_position(session, member, started_on=date(2018, 1, 1))
    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert (POSITION_UNREVISED, position.id) in kinds(session, member)

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (POSITION_UNREVISED, position.id) in kinds(session, member)


def test_a_position_revised_since_the_date_is_not_quiet(session, member):
    position = add_position(session, member, started_on=date(2018, 1, 1))
    # A later decision naming the position: the member has revisited it. R-040's append-only Decision is
    # this estate's revision history, which is why there is no `updated_at` to read instead.
    with mutate_plan(session, member_id=member.id, question="Durchgesehen?", choice="Ja") as decision:
        decision.created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
        decision.linked_positions.append(position)
    session.commit()

    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert (POSITION_UNREVISED, position.id) not in kinds(session, member)


def test_an_inactive_position_is_never_quiet(session, member):
    position = add_position(session, member, started_on=date(2018, 1, 1), active=False)
    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert (POSITION_UNREVISED, position.id) not in kinds(session, member)


def test_an_empty_capital_type_is_derived(session, member):
    """R-110: an empty cell states what would go there. One item, for the column — not eight, for the
    cells. See the module docstring for why the role half of this candidate was rejected.

    **Planted violation:** made `_empty_capital_types` return `set()`. Failed here. Restored.
    """
    add_position(session, member, capital_type="human")
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    assert (CAPITAL_TYPE_EMPTY, "financial") in kinds(session, member)
    assert (CAPITAL_TYPE_EMPTY, "human") not in kinds(session, member)


def test_a_member_with_no_position_at_all_gets_no_capital_type_item(session, member):
    """R-175. Telling someone their empty plan is empty is the interruption, and they are mid-onboarding.

    **Planted violation:** removed the `if not positions: return set()` guard. Failed here with two items
    — which is also the R-113 failure: the derivation became a completion meter for a member who had
    recorded nothing at all.
    """
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert not [pair for pair in kinds(session, member) if pair[0] == CAPITAL_TYPE_EMPTY]


def test_at_most_one_capital_type_item_can_ever_exist(session, member):
    """R-113 as arithmetic. Firing needs one active position and a type with none, and there are two
    types — so this derivation cannot become a count however the plan is shaped."""
    add_position(session, member, capital_type="human")
    add_position(session, member, capital_type="financial", role="growth", label="Depot")
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert not [pair for pair in kinds(session, member) if pair[0] == CAPITAL_TYPE_EMPTY]


def test_a_skipped_onboarding_answer_is_derived(session, member):
    """The optional questions the member passed over, named individually.

    Per question rather than one item covering all of them: each question is a different fact, so each
    has a different cause, and `derived_from` is what lets the panel name which one. An item that said
    "some answers are missing" would be a count wearing a sentence (R-113).
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "employment_magnitude" in skipped
    assert "first_goal" in skipped
    assert "employment_position" not in skipped, "a required question cannot be skipped and complete"


def test_a_required_question_is_never_derived_even_when_it_is_empty(session, member):
    """R-102's required question is not a skippable one, and the filter that says so has to be provable.

    **This test exists because the obvious one was vacuous.** `test_a_skipped_onboarding_answer_is_derived`
    asserted `"employment_position" not in skipped`, and that assertion cannot fail: onboarding cannot
    complete without an answer to it, so an answered question is absent from the skipped set whether the
    `required` filter is there or not. Deleting the filter left the suite green — caught by planting it,
    which is the whole reason for planting.

    Blanking the answer AFTER completion is the state that separates the two, and it is a state a real
    member can reach by clearing a field.

    **Planted violation:** dropped the `record.get("required")` skip. Failed here. Restored.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    record_answer(session, member_id=member.id, question_key="employment_position", value="")
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "employment_position" not in skipped, (
        "R-102's required question is not a skippable one, however it is left"
    )
    assert skipped, "the fixture must produce some skipped questions or this proves nothing"


def test_nothing_is_derived_from_onboarding_before_it_is_complete(session, member):
    """An unanswered question mid-questionnaire is not skipped, it is next — and `resume_point` names it.

    **Planted violation:** removed the `onboarding_completed_at is None` guard. Failed here. Restored.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert not [pair for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED]


def test_an_answered_optional_question_is_not_skipped(session, member):
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    record_answer(session, member_id=member.id, question_key="employment_magnitude", value=92000)
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "employment_magnitude" not in skipped


def test_an_answer_row_holding_nothing_counts_as_skipped(session, member):
    """`record_answer` writes a row either way, so absence is not the only shape of a skip.

    Uses `first_goal` rather than `employment_magnitude` because `onboarding.complete` calls `float()` on
    the magnitude, so a whitespace answer raises `ValueError` there. That is a real fragility one module
    over from this one; it is reported rather than worked around here.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    record_answer(session, member_id=member.id, question_key="first_goal", value="   ")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "first_goal" in skipped


# ============================================================================== idempotence
#
# The property the whole feature stands on. `api/main.py` derives on every read of the action list, so a
# derivation that is not idempotent produces a pile rather than a list within a few page loads.
#
# Onboarding `complete` is the estate's own worked example of getting this wrong: called twice it wrote a
# duplicate Position and a duplicate Decision, and R-040 then made the Decision undeletable.


def test_the_derivation_is_idempotent(session, member):
    """Run it twice over an unchanged plan; the second run must create nothing.

    **Planted violation:** made `_existing` filter `ActionItem.status == "open"` only — the shape of the
    bug a reader would consider reasonable. The second run then found nothing for a cause whose item was
    closed and tried to insert a second row; this went red. Restored.

    **And a plant this test does NOT catch, recorded because that is the honest thing to do:** deleting
    the `Index` from `models/action.py` leaves this test green. With `_existing` reading correctly the
    service never attempts the duplicate, so the index is invisible from here — it is the backstop for the
    race between two concurrent readers, not for this path. What sees it is
    `test_the_store_refuses_a_second_item_for_the_same_cause`, which attempts the duplicate directly, and
    the two schema tests at the end of this file. Verified by planting; the first draft of this docstring
    claimed this test caught it and was wrong.
    """
    add_position(session, member, capital_type="human", started_on=date(2018, 1, 1))
    add_goal(session, member, target_date=PASSED)
    add_goal(session, member, name="Mutgeld")
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    first = derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert first["created"], "the fixture must actually produce items or this proves nothing"
    after_first = kinds(session, member)
    total_first = session.execute(
        select(ActionItem).where(ActionItem.member_id == member.id)
    ).scalars().all()

    second = derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()

    assert second["created"] == []
    assert second["closed"] == []
    assert second["reopened"] == []
    assert kinds(session, member) == after_first
    total_second = session.execute(
        select(ActionItem).where(ActionItem.member_id == member.id)
    ).scalars().all()
    assert len(total_second) == len(total_first)


def test_the_store_refuses_a_second_item_for_the_same_cause(session, member):
    """Idempotence as a fact about the store, not a promise made by one service function.

    A read-then-insert in `derive.py` is the ordinary fix and is still a race between two concurrent
    reads. This is the same argument A63, A66, A68 and A72 all make about C-09 and R-040.

    **Planted violation:** removed the `Index(DERIVED_CAUSE_INDEX, ...)` from `models/action.py`. The
    duplicate committed and this test failed on `pytest.raises` seeing no error. Restored.
    """
    goal = add_goal(session, member)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    session.add(
        ActionItem(
            member_id=member.id,
            trigger_kind=GOAL_UNFUNDED,
            derived_from=goal.id,
            prepared_options=prepared_options_for(GOAL_UNFUNDED, goal.id),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_the_unique_index_leaves_the_expiry_items_alone(session, store, member):
    """R-152's primary source is untouched by this. Every expiry item carries `derived_from IS NULL`, and
    SQLite treats NULLs as distinct in a unique index — so two items for one document remain possible,
    exactly as before.

    **Planted violation:** set `derived_from` to the vault item id inside `action_item_for_expiry`. The
    second store then raised IntegrityError and this test failed. Restored — the expiry items say what
    caused them in `source_vault_item_id`, which is the column that exists for it.
    """
    item = store_item(
        session, store, member_id=member.id, kind="policy", title="Hausrat", source="upload",
        data=b"x", expiry_date=date(2028, 6, 30),
    )
    session.commit()
    # A second dated document, same member, same trigger kind, both with a null cause.
    store_item(
        session, store, member_id=member.id, kind="policy", title="Haftpflicht", source="upload",
        data=b"y", expiry_date=date(2029, 6, 30),
    )
    session.commit()

    rows = session.execute(
        select(ActionItem).where(
            ActionItem.member_id == member.id, ActionItem.trigger_kind == "vault_expiry"
        )
    ).scalars().all()
    assert len(rows) == 2
    assert all(row.derived_from is None for row in rows)
    assert {row.source_vault_item_id for row in rows} != {item.id}, "each names its own document"


def test_a_cause_that_stops_holding_closes_its_item(session, member):
    """A member who funds their goal must not keep reading that it has no funding position.

    Closed as `expired` rather than `acted`: marking it acted would assert the member acted on the item,
    and they may have changed their plan for an unrelated reason. `know.py` draws the same distinction
    when a vault item is superseded and says so at length.

    **Planted violation:** deleted the closing loop. Failed here on the item still being open. Restored.
    """
    position = add_position(session, member)
    goal = add_goal(session, member)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member)

    set_funding(session, member, goal, position, attach=True)

    result = derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert [row.derived_from for row in result["closed"]] == [goal.id]
    assert (GOAL_UNFUNDED, goal.id) not in kinds(session, member)
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member, status=CAUSE_NO_LONGER_HOLDS)


def test_a_cause_that_comes_back_reopens_the_item_it_had(session, member):
    """The unique index means there can be no second row, so a returning cause must reopen the first one
    or become permanently unspeakable.

    **Planted violation:** deleted the `elif row.status == CAUSE_NO_LONGER_HOLDS` branch. Failed here on
    the item staying closed while its cause held — the silent-hole shape, since nothing else goes red.
    Restored.
    """
    position = add_position(session, member)
    goal = add_goal(session, member)
    set_funding(session, member, goal, position, attach=True)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    # The member takes the funding away again.
    set_funding(session, member, goal, position, attach=False)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member)

    # ... funds it, so the item closes ...
    set_funding(session, member, goal, position, attach=True)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member, status=CAUSE_NO_LONGER_HOLDS)

    # ... and takes it away once more. The same row comes back.
    set_funding(session, member, goal, position, attach=False)
    result = derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()
    assert [row.derived_from for row in result["reopened"]] == [goal.id]
    assert (GOAL_UNFUNDED, goal.id) in kinds(session, member)


@pytest.mark.parametrize("spoken", ["dismissed", "acted"])
def test_an_item_the_member_closed_is_never_reopened(session, member, spoken):
    """R-175. A member who dismissed an item and finds it back tomorrow is being nagged.

    **Planted violation:** reopened on any status other than `open`. Failed here on the dismissed item
    coming back. Restored — only an item this module itself closed is ever reopened.
    """
    goal = add_goal(session, member)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    item = session.execute(
        select(ActionItem).where(
            ActionItem.member_id == member.id, ActionItem.trigger_kind == GOAL_UNFUNDED
        )
    ).scalar_one()
    item.status = spoken
    session.commit()

    for _ in range(3):
        result = derive_action_items(session, member_id=member.id, today=TODAY)
        session.commit()
        assert result["created"] == []
        assert result["reopened"] == []
    session.refresh(item)
    assert item.status == spoken


# ===================================================== what the derivation writes into each item


def test_every_derived_item_carries_two_options_with_stated_consequences(session, member):
    """Two options, each with a stated consequence, over every shape of item this module produces.

    **This asserted C-06 at the store until 20 September 2026**, and the store no longer has anything to
    say about it: A168 dropped the CHECK, both A75 triggers and the `@validates` hook. The companion test
    that proved `bulk_insert_mappings` was refused went with them, because there is nothing left to refuse
    it — a malformed item now commits.

    So this is the whole of the guarantee now, and it is a narrower one: it holds for what
    `services/derive.py` writes, because that is what it reads. It says nothing about any other writer.
    """
    add_position(session, member, capital_type="human", started_on=date(2018, 1, 1))
    add_goal(session, member, target_date=PASSED)
    add_goal(session, member, name="Mutgeld")
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    # Item 6's two kinds. The composition is stated far enough back that its published twelve-month
    # horizon has passed by TODAY, which is what makes the confirmation due; the inferred flag has no
    # computable cause and is raised by the event path, which is the only way it ever arrives.
    household_service.state(
        session,
        member_id=member.id,
        people=[HouseholdPerson(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=date(2026, 1, 10),
    )
    household_service.flag_inferred_change(
        session, member_id=member.id, signal="dated_obligation_added"
    )
    session.commit()

    # A112's kind. Frozen directly rather than through a closing, because this fixture is about C-06 over
    # every shape of item and a two-adult separation would be a lot of setup to reach one row.
    frozen = session.execute(select(Goal).where(Goal.member_id == member.id)).scalars().first()
    with mutate_plan(
        session, member_id=member.id, question="Freeze for division?", choice="Yes"
    ) as decision:
        frozen.frozen_at = date(2027, 5, 1)
        decision.linked_goals.append(frozen)
    session.commit()

    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()

    rows = session.execute(
        select(ActionItem).where(ActionItem.member_id == member.id)
    ).scalars().all()
    assert rows, "the fixture must produce items or this test proves nothing"
    seen = set()
    for row in rows:
        seen.add(row.trigger_kind)
        assert len(row.prepared_options) >= OPTIONS_DERIVE_WRITES
        for option in row.prepared_options:
            assert option["label"].strip()
            assert option["consequence"].strip()
    # Every kind this module owns was actually exercised, so "every item" means every shape.
    assert seen >= set(DERIVED_TRIGGER_KINDS)
# ============================================================================== C-01
#
# Two checks, and the second is the one with teeth.
# ------------------------------------------------------------------------------------------------------
# Why `check_answer` is not sufficient here, and what is.
#
# `check_answer` is a per-sentence CO-OCCURRENCE rule. Rules 2 through 5 all require the sentence to land
# on something financial — an instrument from the lexicon, an amount, or a verb of moving money — and rule
# 7 needs an instrument too. Only rule 1's advisory-construct list fires alone.
#
# A derived plan item contains none of those by construction: C-02 forbids the figures, and the subjects
# are goals, positions, dates and grid columns. So most of the gate is structurally unable to fire on
# anything this module can write, and every sentence below is a recommendation that `check_answer` returns
# with `requires_curator` False. Probed on the real gate, before this test was written.
#
# This is not a defect in `boundary.py`. Refusing "Sie sollten die Steuererklärung bis März einreichen"
# would make the product a wall, and the financial conjunct is what stops that. It is a statement about
# scope — and it means a green `check_answer` over these strings is exactly A20's hazard: a check that
# passes because nothing it looks for can occur.
#
# So C-01 is read again here with the financial conjunct removed. Narrower domain, stricter rule: these
# strings are six fixed pairs of sentences about a member's own plan, not free model output, so there is
# no educational register to protect.

RECOMMENDING_SHAPES = {
    "deontic_modal_aimed_at_the_member": r"\b(?:sie|du)\s+(?:sollten|sollen|solltest|sollst|müssen|"
                                         r"musst|müssten|müsstest)\b"
                                         r"|\b(?:sollten|solltest|müssten|müsstest)\s+(?:sie|du)\b",
    "advisory_first_person": r"\b(?:ich|wir)\s+(?:würde|würden|empfehle|empfehlen|rate|raten|schlage|"
                             r"schlagen|wähle|wählen)\b|\bwürde[n]?\s+(?:ich|wir)\b",
    "superlative_of_selection": r"\bam\s+besten\b|\bbeste[nrms]?\b|\bsinnvollste[nrms]?\b"
                                r"|\bgeeignetste[nrms]?\b|\bgünstigste[nrms]?\b",
    "suitability_verdict": r"\b(?:geeignet|sinnvoll|passend|empfehlenswert|ideal|optimal|ratsam)\b",
    "advice_as_a_question": r"\bwarum\s+nicht\b|\bwieso\s+nicht\b|\bwie\s+wäre\s+es\b"
                            r"|\bhaben\s+sie\s+(?:schon\s+)?(?:überlegt|erwogen)\b",
    "in_your_place": r"\ban\s+(?:ihrer|deiner)\s+stelle\b",
    "comparative_drawn_for_the_member": r"\b(?:besser|geeigneter|sinnvoller|günstiger|passender)\s+"
                                        r"(?:für\s+\w+\s+)?als\b",
    "our_recommendation": r"\b(?:meine|unsere)\s+empfehlung\b|\b(?:mein|unser)\s+(?:rat|tipp)\b",
}


def test_no_derived_string_carries_a_recommending_shape():
    """C-01's actual guard for this module. Neither option may be a recommendation.

    **Planted violation, once per shape.** Each pattern was proved able to fire by substituting a
    recommending sentence into `_GOAL_UNFUNDED_OPTIONS` and watching this test name it — see
    `test_every_recommending_shape_can_fire`, which does the same thing permanently and in-process rather
    than by hand.
    """
    offences = []
    for kind, field, text in every_member_facing_string():
        for name, pattern in RECOMMENDING_SHAPES.items():
            if re.search(pattern, text, re.IGNORECASE):
                offences.append(f"{kind}.{field} carries {name}: {text!r}")
    assert not offences, "C-01: neither option may be a recommendation. " + "; ".join(offences)


#: One sentence per shape, each of which SHOULD be refused. Kept beside the patterns so a pattern added
#: without an example is a test failure rather than a pattern nobody has seen work — `test_boundary_c01`'s
#: `test_every_pattern_can_fire` is the precedent and A20 is the reason.
#: `(sentence, does the shared gate already refuse it)`.
#:
#: The second element is the measurement this whole section exists for, and it is recorded per shape
#: rather than asserted in bulk because the answer is not uniform — the first version of this test
#: asserted "the gate catches none of these" and was wrong about half of them.
#:
#: Two of `check_answer`'s rules need no financial object and therefore do fire here: **rule 1**, its list
#: of advisory constructs, and **rule 3**, a comparison drawn explicitly for this member. **Rules 2, 4, 5
#: and 7** are conjunctions requiring an instrument, an amount or a verb of moving money, and a derived
#: plan item contains none of those by construction — C-02 forbids the figures and the subjects are goals,
#: positions, dates and grid columns. The four shapes those four rules would have to catch get through.
WOULD_BE_REFUSED = {
    # rule 2 would need a financial object; "Datum" is not one.
    "deontic_modal_aimed_at_the_member": ("Sie sollten ein neues Datum festhalten.", False),
    "advisory_first_person": ("Wir empfehlen, die Position durchzugehen.", True),
    # `am besten` is in the directive list, which is rule 2, which needs an object.
    "superlative_of_selection": ("Am besten setzen Sie ein neues Datum.", False),
    # **These two changed on 31 August 2026, and this test is what reported it.** `boundary.py` gained
    # `_PLAN_OBJECT` — the member's own plan as something a directive can land on — because the Befund was
    # the first surface to discuss a plan at length and showed that advice about a fund was refused while
    # advice about a member's own goals was not. Rule 5's third conjunct and rule 2's object are now
    # satisfied by `Ziel` and `Spalte`, so the shared gate catches both. Recorded rather than assumed: the
    # local patterns above are kept, because a closed-set scan over this module's own copy table is a
    # different guarantee from a blacklist over model output, and retiring them buys nothing.
    "suitability_verdict": ("Ein Ziel ohne Zuordnung ist für Sie geeignet.", True),
    "advice_as_a_question": ("Warum nicht die Spalte jetzt ausfüllen?", True),
    "in_your_place": ("An Ihrer Stelle würde man das Datum neu setzen.", True),
    "comparative_drawn_for_the_member": ("Eine Zuordnung ist besser für Sie als keine.", True),
    "our_recommendation": ("Unsere Empfehlung: das Datum neu setzen.", True),
}


def test_every_recommending_shape_can_fire():
    """The guard on the guard. A pattern that cannot match is a pattern that reports nothing.

    A20 cost this estate an hour to a word filter rewritten into a pattern that could not match, and it
    stayed green because a filter that cannot fire and a filter with nothing to report return the same
    empty list. So every shape above is named here with a sentence it must catch.
    """
    assert set(WOULD_BE_REFUSED) == set(RECOMMENDING_SHAPES), (
        "every recommending shape needs an example that reaches it"
    )
    for name, (sentence, _) in WOULD_BE_REFUSED.items():
        assert re.search(RECOMMENDING_SHAPES[name], sentence, re.IGNORECASE), (
            f"{name} cannot match its own example: {sentence!r}"
        )
# ============================================================================== C-02


def test_no_derived_string_carries_a_figure():
    """C-02. `action_item_for_expiry` carries no figure because a figure needs an `assumption_set_id`, and
    the same holds for every option here.

    **Planted violation:** put "in den nächsten 12 Monaten" into a consequence. Failed here. Restored.
    """
    for kind, field, text in every_member_facing_string():
        assert not any(char.isdigit() for char in text), (
            f"{kind}.{field} carries a figure, which would need a published assumption set: {text!r}"
        )


def test_the_derivations_declare_no_float():
    """C-02, the structural check, aimed at this file specifically.

    `test_constraints.test_no_literal_rate_in_application_code` already scans the whole services
    directory. This is here so that a failure names the derivation module rather than a directory, and so
    that deleting the global test does not silently drop this one.
    """
    tree = ast.parse(DERIVE_SOURCE.read_text(encoding="utf-8"), filename=str(DERIVE_SOURCE))
    floats = [
        f"line {node.lineno}: {node.value}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert not floats, "C-02: no literal rate in the service layer. Found: " + "; ".join(floats)


def test_no_derived_item_carries_a_due_date(session, member):
    """A derived item is not a deadline. R-152's expiry items are the ones with a date, and
    `know.action_items` sorts a null due date last — so the primary source stays at the top of the list
    without anyone ordering it there by hand.

    **Planted violation:** set `due_date=on` on the created item. Failed here, and the ordering assertion
    in the next test failed too. Restored.
    """
    add_position(session, member, capital_type="human", started_on=date(2018, 1, 1))
    add_goal(session, member, target_date=PASSED)
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    result = derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()
    assert result["created"]
    for item in result["created"]:
        assert item.due_date is None, f"{item.trigger_kind} carries a due date and is not a deadline"


def test_derived_items_sort_below_the_expiry_items(session, store, member):
    """R-152: expiry dates are the PRIMARY source. That ordering is the payload's way of saying so."""
    from eigentlich.services.know import action_items

    add_goal(session, member)
    store_item(
        session, store, member_id=member.id, kind="policy", title="Hausrat", source="upload",
        data=b"x", expiry_date=date(2028, 6, 30),
    )
    session.commit()
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    listed = action_items(session, member_id=member.id)
    assert len(listed) == 2
    assert listed[0]["trigger_kind"] == "vault_expiry"
    assert listed[0]["due_date"] == "2028-06-30"
    assert listed[1]["trigger_kind"] == GOAL_UNFUNDED
    assert listed[1]["due_date"] is None


# ============================================================================== C-09


def test_deriving_writes_no_decision_and_needs_none(session, member):
    """C-09 attaches a Decision to a plan MUTATION. Generating an observation is not one.

    That it does not need one is proved by the commit succeeding — `db.py`'s guard raises in
    `before_flush` for ORM writes and in `before_execute` for Core DML, bulk helpers and raw SQL (A72), so
    a derivation that touched a `PlanMutable` could not reach the database. That it does not WRITE one is
    the second assertion, and it is the one that keeps S-07 readable: a Decisions screen filled with
    observations buries the decisions that matter.

    **Planted violation:** had the derivation set `goal.name` while it was in there. Failed with
    `PlanMutationWithoutDecision`, which is the guard, not this test — so the assertion below is about the
    Decision count and nothing else.
    """
    add_position(session, member, capital_type="human")
    add_goal(session, member, target_date=PASSED)
    before = len(session.execute(
        select(Decision).where(Decision.member_id == member.id)
    ).scalars().all())

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()  # no PlanMutationWithoutDecision

    after = session.execute(select(Decision).where(Decision.member_id == member.id)).scalars().all()
    assert len(after) == before


def test_deriving_changes_no_position_and_no_goal(session, member):
    """The stronger form of the same claim, read off the rows rather than off the guard."""
    position = add_position(session, member, capital_type="human", label="Anstellung")
    goal = add_goal(session, member, name="Wohnung", target_date=TODAY - timedelta(days=1))
    snapshot = (position.label, position.active, position.role, goal.name, goal.target_date)

    derive_action_items(
        session, member_id=member.id, today=TODAY, unrevised_before=UNREVISED_BEFORE
    )
    session.commit()

    session.refresh(position)
    session.refresh(goal)
    assert (position.label, position.active, position.role, goal.name, goal.target_date) == snapshot


# ============================================================================== D-02, R-113, R-175


def test_the_derivations_never_read_a_correlation_tag():
    """D-02, answered on 31 August 2026 (A82): positions are never aggregated as risk, and this closes as
    a decision NOT to build the inference rather than as a deferral.

    A structural check rather than a behavioural one, because the property is an absence: several
    positions sharing a tag must not be a finding, and the way to be sure is that no code here can read
    the column. `tags` appears in this module's prose and must not appear in its code.
    """
    tree = ast.parse(DERIVE_SOURCE.read_text(encoding="utf-8"), filename=str(DERIVE_SOURCE))
    reads = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"tags"}
    ]
    assert not reads, (
        "D-02: the correlation tags stay stored and uninterpreted. No concentration warning. " + "; ".join(reads)
    )
    source = DERIVE_SOURCE.read_text(encoding="utf-8")
    for name in ("CORRELATION_TAGS", "client_type", "reputation_basis", "time_basis"):
        assert f"{name}" not in source.split('"""')[-1], f"{name} is read by the derivation code"


def test_the_derivation_returns_no_count(session, member):
    """R-003 and R-113. Items, never a total. The return names what changed and nothing aggregates it."""
    add_goal(session, member)
    result = derive_action_items(session, member_id=member.id, today=TODAY)
    assert set(result) == {"created", "closed", "reopened"}
    for value in result.values():
        assert isinstance(value, list)


def test_no_derivation_is_keyed_on_a_role():
    """R-113 and S-02's acceptance test: no element may imply that eight positions is the goal.

    A member with one position has seven empty cells. Seven action items saying so is a completion meter
    written as a list, so the role half of the "empty cell" candidate was rejected — and this is what
    stops it being re-added without the argument being had again.
    """
    from eigentlich.models import ROLES

    assert not [kind for kind in DERIVED_TRIGGER_KINDS if "role" in kind]
    source = DERIVE_SOURCE.read_text(encoding="utf-8")
    body = source.split('"""')[-1]
    for role in ROLES:
        assert f'"{role}"' not in body, f"a derivation keyed on the role {role!r} is R-113's failure mode"


# ============================================================================== the read path


def test_the_read_path_derives_and_names_the_cause(session, member):
    """R-174: an item expandable to its options is not expandable to anything if it does not say WHICH
    goal it is about."""
    goal = add_goal(session, member)
    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    causes = causes_by_item_id(session, member_id=member.id)
    assert goal.id in causes.values()


def test_a_member_with_a_plan_and_no_dated_document_reads_a_non_empty_list(session, member):
    """The defect, stated as the test that would have caught it.

    "The owner filled in a plan and got nothing back." Before `derive.py` an ActionItem existed only when
    a member uploaded a document with an expiry date, so this member — positions, goals, no dated
    document — had an empty `/api/actions` forever, and R-152 was satisfied on paper only.

    **Planted violation:** removed the `derive_action_items` call from `get_actions`. Failed here.
    Restored.
    """
    from eigentlich.services.know import action_items

    add_position(session, member, capital_type="human")
    add_goal(session, member, name="Wohnung")
    assert action_items(session, member_id=member.id) == [], "the starting state is the defect"

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    listed = action_items(session, member_id=member.id)
    assert listed, "a member with a plan and no dated document still reads nothing"
    for item in listed:
        assert len(item["prepared_options"]) >= OPTIONS_DERIVE_WRITES
        assert all(option["consequence"] for option in item["prepared_options"])


def test_the_route_derives_and_is_idempotent_over_repeated_reads(api_session):
    """The whole feature, over HTTP, twice.

    `GET /api/actions` derives on the read (see the route's docstring for why that is R-175's shape and
    not a violation of it). A route that derived non-idempotently would grow the list on every page load,
    so reading it twice and comparing the ids is the assertion that matters.

    Registers its own member rather than using the `member` fixture: that fixture is bound to the other
    engine, and a test that reads one database while the route writes another is A68's failure mode.

    **Planted violation:** removed the `derive_action_items` call from `get_actions`. Failed here on the
    route returning nothing for a member with a plan. Restored.

    **A plant this does NOT catch:** deleting the unique index leaves it green, because the service's own
    `_existing` lookup keeps the second read from attempting a duplicate. Verified by planting. The idempotence
    the index guards is the concurrent one, and there is no two-request race to stage in a TestClient.
    """
    from fastapi.testclient import TestClient

    from eigentlich.api import auth as api_auth
    from eigentlich.api.main import app
    from eigentlich.services import register_member
    from conftest import session_overrides

    owner = register_member(api_session, age_at_registration=41, display_name="Leserin")
    api_session.commit()
    add_position(api_session, owner, capital_type="human")
    add_goal(api_session, owner, name="Wohnung")

    app.dependency_overrides.update(session_overrides(api_session))
    app.dependency_overrides[api_auth.current_member] = lambda: owner
    try:
        with TestClient(app) as client:
            first = client.get("/api/actions")
            assert first.status_code == 200, first.text
            second = client.get("/api/actions")
            assert second.status_code == 200, second.text
    finally:
        app.dependency_overrides.clear()

    items = first.json()["items"]
    assert items, "the route returned nothing for a member with a plan"
    assert [i["id"] for i in second.json()["items"]] == [i["id"] for i in items]
    # R-174: the cause is named, so the panel can say WHICH goal.
    assert any(i["derived_from"] for i in items)
    for item in items:
        assert len(item["prepared_options"]) >= OPTIONS_DERIVE_WRITES


# ============================================================================== the migrated schema
#
# A68 is the week this estate lost to a migrated schema differing from the `create_all` one, and the
# lesson recorded there is that only the migrated path — the one every deployment takes and no test took —
# shows it. So the index that carries the idempotence is checked on a database built the way a deployment
# builds one.


def test_a_migrated_database_carries_the_derived_cause_index(tmp_path):
    """The unique index exists after `alembic upgrade head`, not only after `create_all`.

    **Planted violation:** deleted the `op.create_index` call from the migration. This test and the
    schema-agreement test below both went red; the other forty-three stayed green, because every one of
    them builds its schema with `create_all` and `create_all` reads the model. That is A68's failure mode
    exactly — a defect only the migrated path can show — reproduced once deliberately to prove these two
    can see it. Restored.
    """
    import sqlite3

    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parent.parent
    database = tmp_path / "migrated.db"

    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    assert database.exists(), "the migration did not produce a database; the url was not honoured"

    connection = sqlite3.connect(database)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(action_items)")}
        assert "derived_from" in columns

        indexes = {row[1]: row[2] for row in connection.execute("PRAGMA index_list(action_items)")}
        assert DERIVED_CAUSE_INDEX in indexes, (
            f"{DERIVED_CAUSE_INDEX} is missing after migrating. Idempotence is a claim about the store, "
            f"and on a real deployment the store is built by alembic."
        )
        assert indexes[DERIVED_CAUSE_INDEX] == 1, "the index exists but is not UNIQUE"
        covered = [
            row[2]
            for row in connection.execute(f"PRAGMA index_info({DERIVED_CAUSE_INDEX})")
        ]
        assert covered == ["member_id", "trigger_kind", "derived_from"]

        # **`action_items` carries no triggers at all since A168**, and this assertion is what says so.
        #
        # It used to require exactly two: C-06's content triggers, checked here because a migration that
        # recreated the table to add a column would have taken them with it (A63, A66, A68). C-06 was
        # dropped, `e7b3a95d612f` removed them deliberately, and that migration guards the same hazard in
        # the other direction — it refuses to run if it finds a trigger on this table it was not told
        # about, precisely so a future append-only trigger cannot be swept away by its table rebuild.
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='action_items'"
            )
        }
        assert triggers == set(), (
            f"action_items carries triggers after migrating: {sorted(triggers)}. C-06's two were removed "
            f"by e7b3a95d612f; anything here now is either a resurrection or something new that nobody "
            f"recorded."
        )
    finally:
        connection.close()


def test_the_create_all_schema_and_the_migrated_schema_agree_on_the_index(engine, tmp_path):
    """A68's actual lesson: the two paths must produce the same store.

    A `UniqueConstraint` in `__table_args__` would render inline in `create_all`'s CREATE TABLE and as a
    separate unique index in the migration — the same rule, two shapes, and nothing comparing them. An
    `Index` is spelled the same by both, and this is what says so.
    """
    import sqlite3

    from alembic import command
    from alembic.config import Config

    with engine.connect() as connection:
        built = {
            row[1]: row[2]
            for row in connection.execute(text("PRAGMA index_list(action_items)"))
        }
    assert built.get(DERIVED_CAUSE_INDEX) == 1

    database = tmp_path / "migrated.db"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database)
    try:
        migrated = {row[1]: row[2] for row in connection.execute("PRAGMA index_list(action_items)")}
    finally:
        connection.close()

    assert DERIVED_CAUSE_INDEX in migrated
    assert migrated[DERIVED_CAUSE_INDEX] == built[DERIVED_CAUSE_INDEX]


# ---------------------------------------------------------------- never asked is not skipped
#
# A question the member was never shown is not a question they passed over. The distinction is stored on
# the submission by the loader and read here, because nothing in the member's record afterwards carries
# it: a loaded member and a member who finished onboarding in the application both end with
# `onboarding_completed_at` set and both have unanswered questions.


def _loaded_from_a_submission(session, member, *, not_presented):
    """A member whose answers arrived in a file, with the instrument questions that file cannot ask."""
    from eigentlich.services.submissions import record_mapping, store

    stored = store(
        session, member_id=member.id,
        file={"schema_version": "onb@0.1.3", "raw": {"employment": "angestellt"}},
    )
    record_mapping(session, stored, mapped_keys=["employment"], not_presented=not_presented)
    session.commit()


def test_a_question_the_submission_format_never_asked_is_not_derived_as_skipped(session, member):
    """§4 of the run of 20 September 2026, which made 86% of every client's worklist an artefact.

    Fifty clients each carried twelve `plan_onboarding_answer_skipped` items naming the same twelve
    questions — 659 of the run's 780 items. None of those members skipped anything: the interview format
    they were loaded from has no field for those questions, so they were never put to anybody.

    Planted violation: `submissions.not_presented` returning `set()` — which is what it effectively did
    before the loader wrote the key — and this went red on `employment_magnitude`.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    _loaded_from_a_submission(session, member, not_presented=["employment_magnitude", "kader"])
    onboarding_complete(session, member_id=member.id)
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "employment_magnitude" not in skipped, "the format has no field for it; nobody skipped it"
    assert "kader" not in skipped
    assert "first_goal" in skipped, (
        "a question the format COULD have answered and did not is still skipped — otherwise this fix "
        "would silence the derivation rather than correct it"
    )


def test_the_never_asked_exemption_does_not_reach_a_member_who_answered_in_the_application(session, member):
    """Planted violation: returning `set()` from `_skipped_onboarding_answers` passes the test above.

    This is the other half. A member with no submission at all has been asked everything the instrument
    asks, so every optional question they left blank is a skip and must still be derived.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Beratung")
    session.commit()
    onboarding_complete(session, member_id=member.id)
    session.commit()

    derive_action_items(session, member_id=member.id, today=TODAY)
    session.commit()

    skipped = {pair[1] for pair in kinds(session, member) if pair[0] == ONBOARDING_ANSWER_SKIPPED}
    assert "employment_magnitude" in skipped
    assert "kader" in skipped
