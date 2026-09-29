"""Plan versions: the numbered baseline, item 6's stamp, and a re-solve that cannot silently win.

Three claims are load-bearing here and each has its own section:

  * the stamp is COPIED at capture, so restating a composition cannot rewrite what a past plan assumed;
  * a captured version arrives `proposed` and only an explicit adoption makes it standing;
  * the database, not the service, is what makes two standing versions impossible.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from eigentlich.models import (
    ADULT,
    Decision,
    Goal,
    PROPOSED,
    PlanVersion,
    STANDING,
    SUPERSEDED,
    Position,
)
from eigentlich.services import household as household_service
from eigentlich.services import version as version_service
from eigentlich.services.household import Person
from eigentlich.services.plan import mutate_plan
from eigentlich.services.version import (
    AlreadyStanding,
    CannotAdoptSuperseded,
    NothingStanding,
    VersionNotFound,
)

MARCH = date(2027, 3, 14)
LATER = date(2029, 6, 1)


@pytest.fixture()
def store(tmp_path):
    from eigentlich.services.vault import VaultStore

    return VaultStore(tmp_path / "vault")


def _house(session, member, *, as_of=MARCH, partner=False):
    people = [Person(label="Ich", kind=ADULT, member_id=member.id)]
    if partner:
        people.append(Person(label="Anna", kind=ADULT))
    house = household_service.state(
        session, member_id=member.id, people=people, as_of=as_of
    )
    session.commit()
    return house


def _plan(session, member, *, goal_name="Wohneigentum", owners=()):
    with mutate_plan(
        session, member_id=member.id, question="Record the plan?", choice="Yes"
    ) as decision:
        position = Position(
            member_id=member.id,
            role="growth",
            capital_type="financial",
            label="Wertschriften",
            magnitude=101_500.0,
            magnitude_unit="chf",
            stock_kind="asset",
            liquidity="immediate",
        )
        goal = Goal(
            member_id=member.id,
            name=goal_name,
            target_amount=1_500_000.0,
            target_date=date(2038, 12, 31),
        )
        goal.owners.extend(owners)
        session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    session.commit()


# ============================================================ the numbered baseline


def test_a_captured_version_is_numbered_from_one_per_member(session, member):
    _house(session, member)
    _plan(session, member)

    first = version_service.capture(session, member_id=member.id, reason="first plan")
    session.commit()
    assert first.number == 1

    second = version_service.capture(session, member_id=member.id, reason="annual review")
    session.commit()
    assert second.number == 2


def test_a_version_freezes_the_inputs_and_not_a_rendering(session, member):
    house = _house(session, member, partner=True)
    _plan(session, member, owners=house.members)

    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    goal = captured.inputs["goals"][0]
    assert goal["name"] == "Wohneigentum"
    assert goal["target_amount"] == 1_500_000.0
    # All seven fields, the owner among them — which is what a division reads.
    assert {o["label"] for o in goal["owners"]} == {"Ich", "Anna"}

    position = captured.inputs["positions"][0]
    assert position["magnitude"] == 101_500.0
    assert position["magnitude_unit"] == "chf"

    # No computed figure anywhere: no illustration, no projection, no verdict.
    blob = str(captured.inputs)
    for forbidden in ("illustration", "projected", "on_track", "score", "change_chf"):
        assert forbidden not in blob


def test_capturing_writes_no_decision(session, member):
    """A capture records the plan; it does not change it. A Decision per capture would fill an
    append-only table with rows nobody chose."""
    _house(session, member)
    before = len(session.execute(select(Decision)).scalars().all())

    version_service.capture(session, member_id=member.id)
    session.commit()

    assert len(session.execute(select(Decision)).scalars().all()) == before


def test_a_version_is_not_plan_mutable(session, member):
    """Writing one needs no Decision, so the C-09 guard must not be asking for one."""
    from eigentlich.db import plan_table_names

    assert "plan_versions" not in plan_table_names()


# ============================================================ item 6's stamp


def test_a_version_stamps_the_household_it_assumed(session, member):
    _house(session, member, partner=True)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    assert captured.household_as_of == MARCH
    described = version_service.describe(captured)
    assert described["household_as_of"] == "2027-03-14"
    assert described["household_assumption_recorded"] is True


def test_restating_the_composition_does_not_rewrite_what_a_past_version_assumed(session, member):
    """The reason the stamp is copied rather than joined. This is item 6's whole defect.

    If `household_as_of` were read through `household_id` at render time, the second composition would
    silently change what the first version is recorded as having assumed, and every figure measured
    against it would agree with the present rather than with March.
    """
    _house(session, member)
    first = version_service.capture(session, member_id=member.id)
    session.commit()
    first_id = first.id

    # A new composition, a year and a bit later.
    _house(session, member, as_of=date(2028, 7, 1), partner=True)
    second = version_service.capture(session, member_id=member.id)
    session.commit()

    session.expire_all()
    assert session.get(PlanVersion, first_id).household_as_of == MARCH
    assert second.household_as_of == date(2028, 7, 1)


def test_a_version_captured_before_any_composition_records_that_it_knew_none(session, member):
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    assert captured.household_id is None
    assert captured.household_as_of is None
    assert version_service.describe(captured)["household_assumption_recorded"] is False


def test_the_household_stamp_is_all_or_nothing(session, member):
    """A version naming a household but not what it assumed of it is item 6's defect wearing a NULL."""
    house = _house(session, member)
    session.add(
        PlanVersion(member_id=member.id, number=9, household_id=house.id, household_as_of=None)
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ============================================================ a re-solve cannot silently win


def test_a_captured_version_arrives_proposed_and_is_not_standing(session, member):
    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    assert captured.status == PROPOSED
    with pytest.raises(NothingStanding):
        version_service.standing(session, member_id=member.id)
    assert version_service.standing(session, member_id=member.id, missing_ok=True) is None


def test_adopting_is_the_members_act_and_writes_a_decision_naming_the_author(session, member):
    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    adopted = version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.commit()

    assert adopted.status == STANDING
    assert adopted.adopted_at is not None
    decision = session.get(Decision, adopted.adoption_decision_id)
    assert decision is not None
    assert decision.author == "member"
    assert "version 1" in decision.choice


def test_a_curator_can_adopt_on_the_members_behalf_and_the_record_says_so(session, member):
    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    adopted = version_service.adopt(
        session,
        member_id=member.id,
        version_id=captured.id,
        author="curator",
        author_ref="curator:weber",
    )
    session.commit()

    decision = session.get(Decision, adopted.adoption_decision_id)
    assert decision.author == "curator"
    assert decision.author_ref == "curator:weber"


def test_a_curators_confirmation_does_not_carry_forward_to_the_next_version(session, member):
    """Item 2's acceptance criterion, made checkable by adoption being a recorded event with an author."""
    _house(session, member)
    one = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(
        session,
        member_id=member.id,
        version_id=one.id,
        author="curator",
        author_ref="curator:weber",
    )
    session.commit()

    two = version_service.capture(session, member_id=member.id, reason="re-solve")
    session.commit()

    # The new version is proposed and carries no adoption at all — nothing was inherited.
    assert two.status == PROPOSED
    assert two.adopted_at is None
    assert two.adoption_decision_id is None
    assert version_service.standing(session, member_id=member.id).number == 1


def test_adopting_supersedes_the_previous_standing_version_and_names_the_successor(session, member):
    _house(session, member)
    one = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=one.id)
    session.commit()

    two = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=two.id)
    session.commit()

    session.expire_all()
    one = session.get(PlanVersion, one.id)
    assert one.status == SUPERSEDED
    assert one.superseded_by_id == two.id
    # `adopted_at` is NOT cleared: "this was the plan from March to November" needs both ends.
    assert one.adopted_at is not None
    assert version_service.standing(session, member_id=member.id).number == 2


def test_two_standing_versions_are_impossible_at_the_storage_layer(session, member):
    """A partial unique index, not a service-layer promise. Two standing versions would show a member
    two plans, and the only symptom would be the member noticing."""
    _house(session, member)
    one = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=one.id)
    session.commit()

    two = version_service.capture(session, member_id=member.id)
    session.commit()

    # Straight past the service, the way a future mis-ordered call would.
    two.status = STANDING
    two.adopted_at = one.adopted_at
    two.adoption_decision_id = one.adoption_decision_id
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_the_partial_index_still_allows_many_superseded_versions(session, member):
    """The guard on the guard above: a plain unique index would pass that test and break this one."""
    _house(session, member)
    for _ in range(3):
        captured = version_service.capture(session, member_id=member.id)
        session.commit()
        version_service.adopt(session, member_id=member.id, version_id=captured.id)
        session.commit()

    # `history()` is newest first, so version 3 stands and 1 and 2 are behind it.
    by_number = {one.number: one.status for one in version_service.history(session, member_id=member.id)}
    assert by_number == {3: STANDING, 2: SUPERSEDED, 1: SUPERSEDED}


def test_an_unadopted_proposal_stays_proposed_forever(session, member):
    """No expiry, no cleanup, no auto-adoption. An auto-adopting proposal is a silent replacement with a
    delay, which is the thing page 1 forbids."""
    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    # Nothing in the module can be called that would change it, and time passing does not either.
    assert version_service.standing(session, member_id=member.id, missing_ok=True) is None
    session.expire_all()
    assert session.get(PlanVersion, captured.id).status == PROPOSED


def test_adopting_twice_is_refused_rather_than_writing_a_second_decision(session, member):
    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.commit()

    with pytest.raises(AlreadyStanding):
        version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.rollback()


def test_a_superseded_version_cannot_be_re_adopted(session, member):
    _house(session, member)
    one = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=one.id)
    session.commit()
    two = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=two.id)
    session.commit()

    with pytest.raises(CannotAdoptSuperseded) as raised:
        version_service.adopt(session, member_id=member.id, version_id=one.id)
    assert "read as a cycle" in str(raised.value)
    session.rollback()


def test_a_version_belonging_to_another_member_is_not_found(session, member):
    from eigentlich.services import register_member

    other = register_member(session, age_at_registration=52, display_name="Someone Else")
    session.commit()
    theirs = version_service.capture(session, member_id=other.id)
    session.commit()

    with pytest.raises(VersionNotFound):
        version_service.adopt(session, member_id=member.id, version_id=theirs.id)


def test_there_is_no_capture_and_adopt_convenience():
    """One call that produces a new plan and makes it standing is a silent replacement in two steps."""
    assert not hasattr(version_service, "capture_and_adopt")
    assert not hasattr(version_service, "resolve_and_adopt")


# ============================================================ the engines and the Befund


def test_the_scenario_generator_fills_its_baseline_when_one_is_given(session, member):
    """`base_snapshot_id` was recorded absent with the reason "prototype2 has no Snapshot". It has one now."""
    from eigentlich.services import engine_inputs

    _house(session, member)
    _plan(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()

    plan = engine_inputs.plan_for(
        "scenario_generator", member_id=member.id, base_snapshot_id=captured.id
    )
    assert plan.payload["base_snapshot_id"] == captured.id
    assert "base_snapshot_id" not in [gap.name for gap in plan.absent]


def test_without_a_baseline_the_absence_gives_a_reason_that_is_still_true(session, member):
    from eigentlich.services import engine_inputs

    plan = engine_inputs.plan_for("scenario_generator", member_id=member.id)
    gap = [one for one in plan.absent if one.name == "base_snapshot_id"][0]
    # The old reason claimed no Snapshot exists, which stopped being true when PlanVersion landed.
    assert "has no Snapshot" not in gap.reason
    assert "PlanVersion" in gap.reason


def test_the_befund_states_what_the_standing_plan_assumed(session, member):
    from eigentlich.services.befund import render_befund

    _house(session, member, partner=True)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.commit()

    report = render_befund(session, member_id=member.id, today=date(2027, 6, 1))
    facts = [
        one
        for block in report["sections"]
        if block["key"] == "household"
        for one in block["facts"]
    ]
    stated = [one for one in facts if one["key"] == "plan_version_assumes"][0]
    assert "14.03.2027" in stated["sentence"]
    assert stated["values"]["version_number"] == 1


def test_a_standing_plans_assumption_degrades_on_its_own_stamp(session, member):
    """Not on the household's current record. A member who restated last week still has a standing plan
    built on what it assumed, and it is that assumption whose currency matters."""
    from eigentlich.services.befund import render_befund
    from eigentlich.services.currency import COULD_NOT_BE_DETERMINED

    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.commit()

    report = render_befund(session, member_id=member.id, today=LATER)
    keys = {
        one["key"]: one
        for block in report["sections"]
        if block["key"] == "household"
        for one in block["facts"]
    }
    assert "plan_version_assumption_could_not_be_determined" in keys
    assert "plan_version_assumes" not in keys
    assert keys["plan_version_assumption_could_not_be_determined"]["determination"] == (
        COULD_NOT_BE_DETERMINED
    )


def test_when_the_household_was_restated_the_report_says_both_dates_and_proposes_nothing(
    session, member
):
    from eigentlich.services.befund import render_befund

    _house(session, member)
    captured = version_service.capture(session, member_id=member.id)
    session.commit()
    version_service.adopt(session, member_id=member.id, version_id=captured.id)
    session.commit()

    _house(session, member, as_of=date(2027, 9, 1), partner=True)

    report = render_befund(session, member_id=member.id, today=date(2027, 10, 1))
    facts = {
        one["key"]: one
        for block in report["sections"]
        if block["key"] == "household"
        for one in block["facts"]
    }
    older = facts["plan_version_assumption_is_older"]
    assert older["values"]["as_of"] == "2027-09-01"
    assert older["values"]["assumed_as_of"] == "2027-03-14"
    # Two facts side by side. No verdict, and nothing proposed: the re-solve is the member's act.
    for word in ("sollten", "empfehlen", "müssen", "jetzt"):
        assert word not in older["sentence"].lower()


# ============================================================ erasure and export


def test_a_members_versions_are_exported(session, store, member):
    from eigentlich.services.export import export_member

    _house(session, member)
    _plan(session, member)
    version_service.capture(session, member_id=member.id)
    session.commit()

    export = export_member(session, store, member_id=member.id)
    assert len(export["plan_versions"]) == 1
    assert export["plan_versions"][0]["household_as_of"] == "2027-03-14"


def test_erasure_destroys_the_versions_including_a_superseded_chain(session, store, member):
    from eigentlich.services.erasure import erase_member

    _house(session, member)
    for _ in range(2):
        captured = version_service.capture(session, member_id=member.id)
        session.commit()
        version_service.adopt(session, member_id=member.id, version_id=captured.id)
        session.commit()
    member_id = member.id

    report = erase_member(session, store, member_id=member_id)
    session.commit()

    assert report.deleted["plan_versions"] == 2
    assert session.execute(select(PlanVersion)).scalars().all() == []
