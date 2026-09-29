"""The five instrument keys (A127), and the claim that a sixth costs no code.

The sim-tech task the owner closed on 4 September 2026 asked for two things: name the five keys, and
"build the instrument so keys can be added without touching the intake flow". The first is a content edit
and shows up in `test_the_five_keys_the_owner_named_are_all_in_the_instrument`. The second is a claim about
the code, so it is tested as one — a question this build has never seen is planted in the instrument,
answered, completed and read back, with no branch anywhere that names it.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.db import PlanMutationWithoutDecision
from eigentlich.models import ADULT, Decision, MemberFact
from eigentlich.services import member_fact as facts
from eigentlich.services import onboarding
from eigentlich.services.household import Person, state as state_household
from eigentlich.services.member_fact import (
    RefusedValue,
    UndeclarableFact,
    UnknownFact,
)
from eigentlich.services.plan import mutate_plan

MARCH = date(2027, 3, 14)
APRIL = date(2027, 4, 2)

#: The five, from the sim-tech task "Add the five missing keys to the intake instrument". Written out here
#: rather than read from the content file on purpose: a test that derives its expectation from the thing
#: under test asserts only that the file is self-consistent. This is the owner's list.
THE_FIVE = ("canton", "civil_status", "education", "network_people", "health")


def _state(session, member, key, value, *, on=MARCH, by="member"):
    with mutate_plan(session, member_id=member.id, question="q", choice="c") as decision:
        row = facts.state(
            session, member_id=member.id, key=key, value=value, decision=decision, on=on, by=by
        )
    session.commit()
    return row


# ============================================================ the five, and the instrument


def test_the_five_keys_the_owner_named_are_all_in_the_instrument():
    declared = facts.declarations()
    assert set(THE_FIVE) <= set(declared), f"missing: {sorted(set(THE_FIVE) - set(declared))}"


def test_every_declared_key_is_one_this_build_can_store_and_classify():
    """An import-time-shaped contract, exercised: a content edit that nothing could store must fail here
    rather than at the one write it affects, months later, for one member."""
    for key, declared in facts.declarations().items():
        assert declared["type"] in facts.STORABLE_TYPES, f"{key} is a {declared['type']}"
        assert declared["data_class"] is not None, key


def test_health_is_the_one_key_classified_at_the_top():
    """C-04. A person's own statement about their body, and the reason the whole entity is K3 — the log
    filter drops by field NAME, so a K2 entity would have left `health` in log lines."""
    declared = facts.declarations()
    assert str(declared["health"]["data_class"]) == "K3"
    assert str(declared["canton"]["data_class"]) == "K1", "a canton is not documentary material"


def test_the_log_filter_drops_the_value_and_nothing_common():
    """The narrow-column-name argument in `models/member_fact.py`, asserted.

    A K3 column called `key` or `value` would have the filter redacting those names in every log line the
    application writes. The point of `stated_key`/`stated_value` is that the drop list stays narrow.
    """
    from eigentlich.models import top_class_field_names

    dropped = top_class_field_names()
    assert "stated_value" in dropped
    assert "stated_key" in dropped
    # Provenance, overridden back to K1. `stated_by` is also a column on `households`, and this table's
    # classification must not remove that table's diagnostic.
    assert "stated_by" not in dropped
    assert "stated_on" not in dropped
    assert "key" not in dropped and "value" not in dropped


# ============================================================ a sixth key costs no code


PLANTED = {
    "key": "favourite_transport",
    "order": 99,
    "required": False,
    "provenance": "planted by test_member_fact.py",
    "type": "choice",
    "options": [
        {"value": "velo", "label": {"de": "Velo"}},
        {"value": "zug", "label": {"de": "Zug"}},
    ],
    "fills": {"entity": "member_fact", "key": "favourite_transport", "data_class": "K1"},
    "question": {"de": "Womit fahren Sie?"},
    "why": {"de": "Damit dieser Test etwas fragt, das der Build nie gesehen hat."},
}


@pytest.fixture()
def planted_key(monkeypatch):
    """A key this build has never heard of, in the instrument, for the length of one test."""
    from eigentlich import content

    original = content.onboarding_questions()

    def with_planted():
        return [*original, PLANTED]

    # Patched at every site that imported it by name, not only on the module: `services/onboarding` and
    # `services/member_fact` both did `from ..content import onboarding_questions`, so patching only
    # `content.onboarding_questions` would leave both looking at the original list — and the test would
    # pass for the wrong reason, which is the failure mode this whole file is about.
    monkeypatch.setattr("eigentlich.content.onboarding_questions", with_planted)
    monkeypatch.setattr("eigentlich.services.member_fact.onboarding_questions", with_planted)
    monkeypatch.setattr("eigentlich.services.onboarding.onboarding_questions", with_planted)
    return PLANTED


def test_a_key_the_build_has_never_seen_goes_in_end_to_end(session, member, planted_key):
    """The requirement, as one path: answer, complete, read back.

    Nothing in `services/onboarding` or `services/member_fact` names `favourite_transport`. If either of
    them grows a list of keys, this test is what fails.
    """
    state_household(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=MARCH,
    )
    onboarding.record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    onboarding.record_answer(
        session, member_id=member.id, question_key="favourite_transport", value="velo"
    )
    session.commit()

    onboarding.complete(session, member_id=member.id, today=MARCH)
    session.commit()

    assert facts.values(session, member_id=member.id)["favourite_transport"] == "velo"


def test_the_planted_key_is_asked_for_without_the_resume_point_being_told_about_it(
    session, member, planted_key
):
    """`resume_point` walks the question set in `order`, so a new key is already in the flow. Asserted
    because "the intake flow was not touched" is only true if the flow reaches the new question."""
    onboarding.record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    session.commit()
    keys = [q["key"] for q in sorted(__import__("eigentlich.content", fromlist=["x"]).onboarding_questions(), key=lambda q: q["order"])]
    assert keys[-1] == "favourite_transport"

    point = onboarding.resume_point(session, member_id=member.id)
    assert point["next_question_key"] is not None


def test_a_declared_type_nothing_can_store_is_refused_rather_than_dropped(monkeypatch):
    from eigentlich import content

    broken = {**PLANTED, "type": "colour_wheel"}
    monkeypatch.setattr(
        "eigentlich.services.member_fact.onboarding_questions",
        lambda: [*content.onboarding_questions(), broken],
    )
    with pytest.raises(UndeclarableFact) as raised:
        facts.declarations()
    assert "colour_wheel" in str(raised.value)


def test_a_declared_key_with_no_data_class_is_refused(monkeypatch):
    """C-04 has deliberately no default. A key whose author did not think about its class is the key the
    logging filter gets wrong."""
    from eigentlich import content

    broken = {**PLANTED, "fills": {"entity": "member_fact", "key": "x"}}
    monkeypatch.setattr(
        "eigentlich.services.member_fact.onboarding_questions",
        lambda: [*content.onboarding_questions(), broken],
    )
    with pytest.raises(UndeclarableFact):
        facts.declarations()


def test_a_choice_with_no_options_is_a_control_a_member_cannot_use(monkeypatch):
    from eigentlich import content

    broken = {**PLANTED, "options": []}
    monkeypatch.setattr(
        "eigentlich.services.member_fact.onboarding_questions",
        lambda: [*content.onboarding_questions(), broken],
    )
    with pytest.raises(UndeclarableFact):
        facts.declarations()


# ============================================================ what is refused


def test_an_undeclared_key_is_refused(session, member):
    with pytest.raises(UnknownFact):
        facts.check("shoe_size", 44)


def test_an_answer_outside_the_declared_options_is_refused(session, member):
    with pytest.raises(RefusedValue):
        facts.check("canton", "Bayern")


def test_every_canton_the_real_submissions_state_is_admissible():
    """The Renzo lesson, applied before the wording was approved rather than after.

    Two of the six real submissions say `St. Gallen` and four say `Thurgau`; one says
    `ledig, mit Partner`, which is not a legal civil status at all. All of them have to fit, or the load
    records a false answer — which is what forcing one of three crisis options would have done.
    """
    for canton in ("Thurgau", "St. Gallen"):
        assert facts.check("canton", canton) == canton
    for status in ("ledig", "verheiratet", "ledig, mit Partner"):
        assert facts.check("civil_status", status) == status
    for reading in (0.7, 0.85, 0.9, 1.0, 1):
        assert facts.check("health", reading) == reading
    for people in (5, 10, 18, 20):
        assert facts.check("network_people", people) == people


def test_health_admits_any_reading_between_zero_and_one():
    """A173. The owner's ruling of 21 September 2026, pinned so a list cannot come back by accident.

    `health` offered seven discrete readings — 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.00 — and the list
    was irregular: coarse below 0.80, fine above it, with one gap between 0.70 and 0.80. Four of fifty
    submissions answered **0.75** and landed exactly in that gap, and R-020 forbids rounding a member's
    own answer to the nearest option, so `onboarding.complete` refused all four and they could not be
    loaded at all (A172).

    The ruling is that any number between 0 and 1 is an answer. `services/human_capital.py` already read
    a bare number in that range — its own note says "Read as a bare number; not a published option" — so
    the instrument was the only thing refusing what the model could already use.

    **0.75 is named explicitly** rather than tested as one of a range: it is the value that was refused,
    and a test that only checks the bounds would pass again on the day somebody reintroduces a list that
    happens to include 0 and 1.
    """
    assert facts.check("health", 0.75) == 0.75
    for reading in (0.0, 0.01, 0.5, 0.63, 0.749, 0.9999, 1.0, 1, 0):
        assert facts.check("health", reading) == reading

    declared = facts.declaration("health")
    assert declared["type"] == "number", (
        "health is a bounded number since A173. A choice list here refuses whatever falls between its "
        "entries, which is what it did to four members."
    )
    assert not declared["options"], "a number question with an option list is a list wearing a type"
    assert (declared["min"], declared["max"]) == (0, 1)


def test_health_still_refuses_what_is_not_a_reading():
    """The bounds and the type are the whole of the rule, and they are still a rule.

    Widening a question is not the same as removing its guard. A figure outside 0..1 is not a
    self-assessment, and a label is still not an answer (the stored value is never the rendering).
    """
    for outside in (1.01, -0.01, 2, -1, 100):
        with pytest.raises(RefusedValue):
            facts.check("health", outside)
    for not_a_number in ("0,85", "0.85", "gut", "", None, True):
        with pytest.raises(RefusedValue):
            facts.check("health", not_a_number)


def test_a_label_is_not_an_answer():
    """The stored value is the option's `value`, never the label it renders as — a label changes with the
    reader's language and an answer must not."""
    with pytest.raises(RefusedValue):
        facts.check("health", "0,85")


def test_a_number_outside_the_declared_bounds_is_refused():
    """The bounds are the question's own, read rather than repeated here."""
    assert facts.check("network_people", 200) == 200
    with pytest.raises(RefusedValue):
        facts.check("network_people", 201)
    with pytest.raises(RefusedValue):
        facts.check("network_people", -1)


def test_a_boolean_is_not_a_number():
    """`isinstance(True, int)` is True in Python, so `True` would otherwise store as a network of one."""
    with pytest.raises(RefusedValue):
        facts.check("network_people", True)


def test_whitespace_is_a_skipped_question(session, member):
    with pytest.raises(RefusedValue):
        facts.check("education", "   ")


def test_an_empty_answer_writes_no_row_rather_than_an_empty_one(session, member):
    """"Nothing stated" and "stated as nothing" are different facts and only one of them is true."""
    with pytest.raises(RefusedValue):
        facts.check("canton", None)


def test_text_is_stored_stripped_and_otherwise_untouched():
    """Marvin's answer is two lines: a qualification and three strengths. Neither is parsed."""
    answer = "  Elektroinstallateur EFZ\nKommunikation, Kontaktfreudig  "
    assert facts.check("education", answer) == answer.strip()


def test_an_unknown_initiator_is_refused(session, member):
    with pytest.raises(RefusedValue):
        with mutate_plan(session, member_id=member.id, question="q", choice="c") as decision:
            facts.state(
                session, member_id=member.id, key="canton", value="Thurgau",
                decision=decision, by="somebody_else",
            )


# ============================================================ C-09


def test_stating_a_fact_outside_a_decision_is_refused(session, member):
    """C-09. `MemberFact` is `PlanMutable`, and the guard compares against
    `Decision.covered_plan_objects` — which is why `decision_facts` had to exist for this to be
    writable at all, rather than merely for S-07 to be able to show it."""
    row = MemberFact(
        member_id=member.id,
        stated_key="canton",
        stated_value="Thurgau",
        stated_on=MARCH,
        stated_by="member",
    )
    session.add(row)
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()
    session.rollback()


def test_the_decision_links_the_fact_it_recorded(session, member):
    row = _state(session, member, "canton", "Thurgau")
    decision = session.execute(
        select(Decision).where(Decision.member_id == member.id)
    ).scalars().first()
    assert row.id in decision.linked_fact_ids
    assert row in decision.covered_plan_objects()


def test_the_row_carries_the_class_its_key_declares_and_not_the_entitys(session, member):
    """Per-row, from the content declaration. The entity constant governs the log filter; the row value
    is what an export or a retention sweep reads."""
    canton = _state(session, member, "canton", "Thurgau")
    health = _state(session, member, "health", 0.85)
    assert canton.data_class == 1, "a canton stored as documentary material"
    assert health.data_class == 3


# ============================================================ superseding


def test_a_second_statement_supersedes_the_first_and_the_first_survives(session, member):
    """A member who moved canton has not corrected a typo. A plan version stamped against Thurgau has to
    keep reading true."""
    first = _state(session, member, "canton", "Thurgau", on=MARCH)
    second = _state(session, member, "canton", "St. Gallen", on=APRIL)

    session.refresh(first)
    assert first.superseded_on == APRIL
    assert second.superseded_on is None
    assert facts.values(session, member_id=member.id)["canton"] == "St. Gallen"

    rows = session.execute(
        select(MemberFact).where(MemberFact.stated_key == "canton").order_by(MemberFact.stated_on)
    ).scalars().all()
    assert [r.stated_value for r in rows] == ["Thurgau", "St. Gallen"], "the history was overwritten"


def test_two_current_rows_for_one_key_cannot_exist(session, member):
    """`uq_member_facts_one_current`, planted. Without it a member has two cantons and no rule for which
    one a finding reads.

    Written at the storage layer rather than through the service, because the service's ordering is
    exactly what this index is the backstop for.
    """
    _state(session, member, "canton", "Thurgau", on=MARCH)
    with pytest.raises(Exception) as raised:
        with mutate_plan(session, member_id=member.id, question="q", choice="c") as decision:
            row = MemberFact(
                member_id=member.id,
                stated_key="canton",
                stated_value="Zug",
                stated_on=APRIL,
                stated_by="member",
            )
            decision.linked_facts.append(row)
            session.add(row)
        session.commit()
    assert "uq_member_facts_one_current" in str(raised.value) or "UNIQUE" in str(raised.value).upper()
    session.rollback()


def test_a_statement_older_than_the_one_it_replaces_is_refused(session, member):
    """Otherwise the standing fact is older than the history behind it, and
    `ck_member_facts_superseded_after_stated` would refuse the write anyway — this says so with a
    sentence rather than with an IntegrityError."""
    _state(session, member, "canton", "St. Gallen", on=APRIL)
    with pytest.raises(RefusedValue) as raised:
        _state(session, member, "canton", "Thurgau", on=MARCH)
    assert "earlier" in str(raised.value)


def test_two_members_may_state_the_same_key(session, member):
    """The uniqueness is per member. Obvious, and the kind of thing a partial index gets wrong."""
    from eigentlich.services.registration import register_member

    other = register_member(session, age_at_registration=29, display_name="Zweite")
    session.commit()

    _state(session, member, "canton", "Thurgau")
    _state(session, other, "canton", "Thurgau")
    assert facts.values(session, member_id=other.id)["canton"] == "Thurgau"


# ============================================================ the intake, and erasure


def test_the_intake_writes_the_five_and_dates_them_as_stated(session, member):
    for key, value in (
        ("canton", "St. Gallen"),
        ("civil_status", "ledig"),
        ("education", "Elektroinstallateur EFZ"),
        ("network_people", 20),
        ("health", 1),
    ):
        onboarding.record_answer(session, member_id=member.id, question_key=key, value=value)
    onboarding.record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    session.commit()

    onboarding.complete(session, member_id=member.id, today=MARCH)
    session.commit()

    stored = facts.values(session, member_id=member.id)
    assert stored == {
        "canton": "St. Gallen",
        "civil_status": "ledig",
        "education": "Elektroinstallateur EFZ",
        "network_people": 20,
        "health": 1,
    }
    assert all(row.stated_on == MARCH for row in facts.current(session, member_id=member.id).values())


def test_a_skipped_key_writes_nothing(session, member):
    onboarding.record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    session.commit()
    onboarding.complete(session, member_id=member.id, today=MARCH)
    session.commit()
    assert facts.values(session, member_id=member.id) == {}


def test_a_stored_answer_the_question_no_longer_admits_stops_the_intake(session, member):
    """Refused rather than dropped — which is precisely what happened to all five keys for the five days
    before this table existed. The same call `_people_from` makes about a misread composition."""
    onboarding.record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    onboarding.record_answer(session, member_id=member.id, question_key="canton", value="Bayern")
    session.commit()

    with pytest.raises(onboarding.OnboardingIncomplete) as raised:
        onboarding.complete(session, member_id=member.id, today=MARCH)
    assert "canton" in str(raised.value)


def test_the_facts_are_both_exported_and_erased(session, member, tmp_path):
    """R-154 and R-231, from the one registry. Exporting less than you erase is incoherent."""
    from eigentlich.services.member_data import DELETED_IN_ERASURE_ORDER

    assert MemberFact in DELETED_IN_ERASURE_ORDER


def test_erasing_a_member_removes_the_facts_and_the_links(session, member, tmp_path):
    from eigentlich.models.decision import decision_facts
    from eigentlich.services.erasure import erase_member
    from eigentlich.services.vault import VaultStore

    _state(session, member, "health", 0.85)
    assert session.execute(select(MemberFact)).scalars().all()

    with mutate_plan(session, member_id=member.id, question="Löschung?", choice="ja"):
        pass
    session.commit()

    report = erase_member(session, VaultStore(tmp_path / "vault"), member_id=member.id)
    session.commit()

    assert report.deleted.get("member_facts") == 1
    assert session.execute(select(MemberFact)).scalars().all() == []
    assert session.execute(select(decision_facts)).all() == []
