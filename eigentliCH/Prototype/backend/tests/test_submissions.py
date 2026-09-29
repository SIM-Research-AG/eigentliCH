"""The intake file kept verbatim: what is stored, what is refused, and who can destroy it.

**The two tests that matter are the last two.** Storing a blob of unmapped answers is only defensible if
the member can take it away and can have it destroyed — R-154 and R-231. A record held about somebody that
they cannot reach is the argument against keeping it at all, so those are asserted rather than assumed.
"""

from __future__ import annotations

import pytest

from eigentlich.models import Submission
from eigentlich.services import submissions as subs
from eigentlich.services.auth import register_member
from eigentlich.services.vault import VaultStore


@pytest.fixture()
def store_dir(tmp_path):
    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def second_member(session):
    other = register_member(session, age_at_registration=39, display_name="Zweite Person")
    session.commit()
    return other

FILE = {
    "schema_version": "intake@1.1",
    "meta": {"collected": "2026-09-06", "source": "intake.html"},
    "raw": {
        "person_label": "Marvin",
        "household_code": "seeblick",
        "income_gross": 69550,
        # three answers with no home anywhere in the build
        "permit": "C (Niederlassung)",
        "advisors": "Kantonalbank, Treuhand Meier",
        "documents_where": "Ordner im Schrank, Kopie bei meiner Schwester",
    },
}


def test_a_file_is_kept_whole_and_not_only_its_mapped_parts(session, member):
    row = subs.store(session, member_id=member.id, file=FILE)
    assert row.payload == FILE, "the file is kept as it arrived, meta and all"
    assert row.schema_version == "intake@1.1"
    assert row.source == "intake.html"
    assert row.collected_on == "2026-09-06"
    assert row.household_code == "seeblick"


def test_the_schema_version_is_never_guessed(session, member):
    """A file whose shape is inferred is a file whose fields are inferred, and two instruments have used
    the same key for different things."""
    with pytest.raises(ValueError, match="schema_version"):
        subs.store(session, member_id=member.id, file={"raw": {"income_gross": 1}})


def test_the_same_file_twice_is_refused_rather_than_doubled(session, member):
    subs.store(session, member_id=member.id, file=FILE)
    with pytest.raises(subs.DuplicateSubmission):
        subs.store(session, member_id=member.id, file=FILE)


def test_the_hash_does_not_depend_on_key_order(session, member):
    reordered = {
        "meta": FILE["meta"], "schema_version": FILE["schema_version"],
        "raw": {k: FILE["raw"][k] for k in reversed(list(FILE["raw"]))},
    }
    assert subs.content_hash(FILE) == subs.content_hash(reordered)


def test_two_members_may_hold_identical_files(session, member, second_member):
    """Uniqueness is per member, deliberately. Two people in one household who have each filled in
    almost nothing produce the same file, and refusing the second would be refusing a real person."""
    subs.store(session, member_id=member.id, file=FILE)
    subs.store(session, member_id=second_member.id, file=FILE)
    assert len(subs.by_household_code(session, code="seeblick")) == 2


def test_an_unmapped_submission_reports_every_answer_as_waiting(session, member):
    """A file stored and never mapped must report all of its answers, not none.

    Reporting none would read as "there is nothing here", which is the opposite of true and exactly the
    silence this table was built to end.
    """
    row = subs.store(session, member_id=member.id, file=FILE)
    keys = {u.key for u in subs.unmapped(row)}
    assert keys == set(FILE["raw"]), "nothing has been claimed yet, so everything is waiting"


def test_mapping_narrows_what_is_reported_as_waiting(session, member):
    row = subs.store(session, member_id=member.id, file=FILE)
    subs.record_mapping(
        session, row,
        mapped_keys=["income_gross", "person_label", "household_code"],
        reasons={"permit": "no field holds a residence permit"},
    )
    waiting = {u.key: u.reason for u in subs.unmapped(row)}
    assert set(waiting) == {"permit", "advisors", "documents_where"}
    assert waiting["permit"] == "no field holds a residence permit"
    assert waiting["advisors"] is None, "unclaimed with no stated reason is a real state"


def test_the_answers_a_member_gave_are_reachable_whatever_the_wrapper(session, member):
    row = subs.store(session, member_id=member.id, file=FILE)
    assert subs.answers(row)["income_gross"] == 69550


def test_a_shared_code_finds_both_files_and_claims_nothing(session, member, second_member):
    """The code is a word the member chose, not an identifier this application issued. Finding two rows
    by it is a lookup; deciding they are one household takes consent from both sides."""
    subs.store(session, member_id=member.id, file=FILE)
    other = {**FILE, "raw": {**FILE["raw"], "person_label": "Sofia"}}
    subs.store(session, member_id=second_member.id, file=other)
    found = subs.by_household_code(session, code="seeblick")
    assert [s.member_id for s in found] == [member.id, second_member.id]
    assert subs.by_household_code(session, code="  ") == []


# ============================================================ the two that justify storing it at all


def test_a_member_takes_the_file_with_them(session, member):
    """R-154. Every table erasure destroys, the export returns."""
    from eigentlich.services.member_data import DELETED_IN_ERASURE_ORDER

    assert Submission in DELETED_IN_ERASURE_ORDER, (
        "a blob the member cannot take away and cannot have destroyed is a record held about them that "
        "they do not control, which is the argument against keeping unmapped answers at all"
    )


def test_erasure_destroys_the_file(session, store_dir, member):
    """R-231, and the assertion this whole table rests on."""
    from eigentlich.services.erasure import erase_member

    # The id, before the row it belongs to stops existing -- reading `member.id` after the erasure is
    # reading a deleted instance.
    member_id = member.id
    subs.store(session, member_id=member_id, file=FILE)
    session.commit()
    assert session.query(Submission).filter_by(member_id=member_id).count() == 1

    report = erase_member(session, store_dir, member_id=member_id)
    session.commit()

    assert report.deleted.get("submissions") == 1, report.as_dict()
    assert session.query(Submission).filter_by(member_id=member_id).count() == 0
