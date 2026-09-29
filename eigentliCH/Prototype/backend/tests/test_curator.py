"""S-12, the Curator Workbench. R-210, R-211, R-212, R-213, and C-01/C-09/C-10 where they touch it.

**The file's centre of gravity is `test_every_member_read_refuses_without_a_grant`** and the guard beside
it. Everything else here checks that a specific thing works; those two check that nothing works *without a
grant*, including a function nobody has written yet. If exactly one test in this file should survive a
rewrite, it is that pair.

Iterations are lowered throughout: 600,000 rounds of PBKDF2 per curator login is correct in production and
would make this file take minutes — the same fixture `test_auth.py` uses.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import StaticPool

from eigentlich.db import create_all, make_session_factory
from eigentlich.models import (
    AccessGrant,
    Curator,
    CuratorSession,
    CuratorSessionEvent,
    Decision,
    GRANTABLE,
    Goal,
    Position,
    WeakPassword,
    utcnow,
)
from eigentlich.services import mutate_plan, register_member, store_item
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.services.curator import (
    AccessDenied,
    CuratorAuthenticationFailed,
    MEMBER_READS,
    NOT_MEMBER_READS,
    NoOpenSession,
    PARTIALLY_GATED,
    SessionAlreadyClosed,
    UnknownScope,
    authenticate_curator,
    close_session,
    create_curator,
    curator_view_action_items,
    curator_view_decisions,
    curator_view_goals,
    curator_view_positions,
    curator_view_vault,
    curator_workbench,
    grant_access,
    granted_scopes,
    live_grants,
    members_with_live_access,
    open_session,
    recommend,
    record_note,
    require_grant,
    reset_curator_password,
    revoke_all_grants,
    revoke_grant,
    revoke_session_grants,
    session_record,
    sessions_for_curator,
)
from eigentlich.services.vault import VaultStore, action_item_for_expiry

CURATOR_PASSWORD = "eine ziemlich lange passphrase"


@pytest.fixture(autouse=True)
def _fast_hashing(monkeypatch):
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)


@pytest.fixture()
def curator(session):
    row = create_curator(
        session,
        display_name="Nicolas Bürkler",
        email="Kurator@Example.CH",
        password=CURATOR_PASSWORD,
        role_label="Kurator",
        fictional=True,
    )
    session.commit()
    return row


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def furnished(session, store, member):
    """A member with something in every scope, so a refusal cannot be mistaken for an empty account."""
    with mutate_plan(
        session,
        member_id=member.id,
        question="Record employment as a human-capital income position?",
        choice="Yes",
    ) as decision:
        position = Position(
            member_id=member.id,
            role="income",
            capital_type="human",
            label="Anstellung",
            magnitude=92000,
            magnitude_unit="chf_per_year",
        )
        goal = Goal(member_id=member.id, name="Mutgeld", template="courage_money")
        session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    session.commit()

    item = store_item(
        session,
        store,
        member_id=member.id,
        kind="policy",
        title="Freizügigkeitskonto bei der Bank Y",
        source="upload",
        data=b"x",
        expiry_date=date(2027, 3, 31),
    )
    session.commit()
    session.add(action_item_for_expiry(item))
    session.commit()
    return {"member": member, "position": position, "goal": goal, "vault_item": item}


@pytest.fixture()
def granted(session, member, curator):
    """A live grant covering everything. The permissive case, so refusals elsewhere mean something."""
    grant = grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=list(GRANTABLE)
    )
    session.commit()
    return grant


@pytest.fixture()
def consultation(session, member, curator):
    record = open_session(
        session, member_id=member.id, curator_id=curator.id, opened_from="workbench"
    )
    session.commit()
    return record


# ============================================================ THE test: nothing reads without a grant


#: Every entry of `MEMBER_READS`, with whatever else it needs beyond the two ids. Asserted below to match
#: the service's own table exactly, so a function added there cannot be quietly skipped here.
EXTRA_ARGUMENTS = {
    "curator_view_positions": {},
    "curator_view_goals": {},
    "curator_view_vault": {},
    "curator_view_decisions": {},
    "curator_view_action_items": {},
    "curator_workbench": {},
    "record_note": {"session_id": "<consultation>", "text": "eine Notiz"},
    "recommend": {
        "session_id": "<consultation>",
        "question": "Wie weiter mit dem Freizügigkeitskonto?",
        "choice": "Bei der Stiftung belassen",
    },
}


def test_the_argument_table_covers_every_member_read():
    """The enumeration below is only as good as its coverage. This is what keeps it honest."""
    assert set(EXTRA_ARGUMENTS) == set(MEMBER_READS), (
        "a member-facing function was added to MEMBER_READS without being enumerated here — "
        f"missing: {sorted(set(MEMBER_READS) - set(EXTRA_ARGUMENTS))}, "
        f"stale: {sorted(set(EXTRA_ARGUMENTS) - set(MEMBER_READS))}"
    )


def test_every_member_read_refuses_without_a_grant(session, member, curator, furnished, consultation):
    """R-210. The point of this phase.

    Every function in the service that touches the member's material is called with no grant in existence,
    and each must RAISE. The member has positions, goals, a vault item, a decision and an action item — so
    a function that returned an empty list would be returning a falsehood, not a null result.
    """
    import eigentlich.services.curator as service

    assert MEMBER_READS, "the registry is empty; the gate is unenforced"

    for name in sorted(MEMBER_READS):
        function = getattr(service, name)
        extra = {
            key: (consultation.id if value == "<consultation>" else value)
            for key, value in EXTRA_ARGUMENTS[name].items()
        }
        with pytest.raises(AccessDenied) as refusal:
            function(session, member_id=member.id, curator_id=curator.id, **extra)
        assert "R-210" in str(refusal.value), f"{name} refused without saying why"


def test_no_function_taking_both_ids_is_unclassified():
    """The guard on the guard: a read path added later has to be classified, in the service, by its author.

    Any module-level function taking both `member_id` and `curator_id` is either gated (`MEMBER_READS`),
    knowingly part-gated (`PARTIALLY_GATED`), or knowingly harmless (`NOT_MEMBER_READS`). A new one lands
    in none of the three and fails here — which is the only way this stays true after phase 5.
    """
    import eigentlich.services.curator as service

    classified = set(MEMBER_READS) | set(PARTIALLY_GATED) | set(NOT_MEMBER_READS)
    unclassified = []
    for name, obj in vars(service).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if obj.__module__ != service.__name__:
            continue
        parameters = inspect.signature(obj).parameters
        if {"member_id", "curator_id"} <= set(parameters) and name not in classified:
            unclassified.append(name)

    assert not unclassified, (
        f"{unclassified} take a member id and a curator id and are classified nowhere. R-210 requires "
        f"every read of a member's material to consult AccessGrant.covers(); say which table this belongs "
        f"in, in services/curator.py."
    )


def test_a_grant_for_another_scope_does_not_open_this_one(session, member, curator, furnished):
    """R-210 "scoped". Liveness is not enough — the grant has to name the thing being read."""
    readers = {
        "positions": curator_view_positions,
        "goals": curator_view_goals,
        "vault": curator_view_vault,
        "decisions": curator_view_decisions,
        "action_items": curator_view_action_items,
    }
    for scope, reader in readers.items():
        others = [name for name in GRANTABLE if name != scope]
        grant = grant_access(session, member_id=member.id, curator_id=curator.id, scope=others)
        session.commit()
        with pytest.raises(AccessDenied):
            reader(session, member_id=member.id, curator_id=curator.id)
        revoke_grant(session, grant_id=grant.id, member_id=member.id)
        session.commit()


def test_a_grant_for_another_member_does_not_open_this_one(session, curator, furnished):
    """The obvious mistake, checked because it is the one an index on curator_id makes easy to write."""
    other = register_member(session, age_at_registration=52, display_name="Someone Else")
    session.commit()
    grant_access(session, member_id=other.id, curator_id=curator.id, scope=list(GRANTABLE))
    session.commit()

    with pytest.raises(AccessDenied):
        curator_view_positions(
            session, member_id=furnished["member"].id, curator_id=curator.id
        )


def test_a_refusal_is_never_an_empty_result(session, member, curator, furnished):
    """The reason R-210 raises rather than filtering.

    With a grant the member has positions. Without one the call must not return the same shape with fewer
    rows, because a curator cannot tell that apart from a member who has not filled the grid in.
    """
    grant = grant_access(session, member_id=member.id, curator_id=curator.id, scope=["positions"])
    session.commit()
    filled = curator_view_positions(session, member_id=member.id, curator_id=curator.id)
    assert any(cell["positions"] for cell in filled["cells"])

    revoke_grant(session, grant_id=grant.id, member_id=member.id)
    session.commit()
    with pytest.raises(AccessDenied):
        curator_view_positions(session, member_id=member.id, curator_id=curator.id)


# ============================================================ R-210: the reads, granted


def test_each_scope_opens_exactly_its_own_read(session, member, curator, furnished, granted):
    assert any(c["positions"] for c in curator_view_positions(
        session, member_id=member.id, curator_id=curator.id)["cells"])
    assert curator_view_goals(session, member_id=member.id, curator_id=curator.id)["goals"]
    assert curator_view_vault(session, member_id=member.id, curator_id=curator.id)["items"]
    assert curator_view_decisions(session, member_id=member.id, curator_id=curator.id)["decisions"]
    assert curator_view_action_items(session, member_id=member.id, curator_id=curator.id)["items"]


def test_the_vault_view_carries_no_document_bytes(session, member, curator, furnished, granted):
    """R-210 gives the curator the vault; it does not make a K3 file a field in a list response."""
    payload = curator_view_vault(session, member_id=member.id, curator_id=curator.id)
    assert payload["content_bytes_included"] is False
    for item in payload["items"]:
        assert "content" not in item and "content_base64" not in item
        assert item["has_content"] is True


def test_the_workbench_names_what_was_not_granted(session, member, curator, furnished):
    """S-12. A section that is missing because it was withheld must say so, not render as absent."""
    grant_access(session, member_id=member.id, curator_id=curator.id, scope=["goals"])
    session.commit()

    payload = curator_workbench(session, member_id=member.id, curator_id=curator.id)
    assert payload["granted_scope"] == ["goals"]
    assert set(payload["not_granted"]) == set(GRANTABLE) - {"goals"}
    assert set(payload["sections"]) == {"goals"}
    assert payload["grants"][0]["revoke"]["method"] == "DELETE"


def test_the_workbench_refuses_outright_when_nothing_is_granted(session, member, curator, furnished):
    with pytest.raises(AccessDenied):
        curator_workbench(session, member_id=member.id, curator_id=curator.id)


def test_the_curators_worklist_only_names_members_who_granted(session, member, curator, granted):
    listed = members_with_live_access(session, curator_id=curator.id)
    assert [entry["member_id"] for entry in listed] == [member.id]
    assert sorted(listed[0]["scope"]) == sorted(GRANTABLE)

    revoke_all_grants(session, member_id=member.id)
    session.commit()
    assert members_with_live_access(session, curator_id=curator.id) == []


# ============================================================ R-213: revocation, immediate


def test_curator_access_revocation_takes_immediate_effect(session, member, curator, furnished, granted):
    """R-213, and the spec's named acceptance test.

    Not at expiry — on the very next read, inside the same transaction. The grant still has hours to run.
    """
    assert curator_view_positions(session, member_id=member.id, curator_id=curator.id)
    assert granted.expires_at > utcnow(), "the grant must still be within its window for this to prove it"

    revoke_grant(session, grant_id=granted.id, member_id=member.id)

    with pytest.raises(AccessDenied):
        curator_view_positions(session, member_id=member.id, curator_id=curator.id)


def test_revocation_is_a_timestamp_and_never_a_delete(session, member, curator, granted):
    """R-213. An audit has to show that access existed and was withdrawn; a deleted row shows neither."""
    revoke_grant(session, grant_id=granted.id, member_id=member.id)
    session.commit()

    row = session.get(AccessGrant, granted.id)
    assert row is not None, "the grant row was deleted; the evidence that access existed is gone"
    assert row.revoked_at is not None
    assert row.scope, "the scope that was granted is still recorded"
    assert row.is_live() is False


def test_revocation_beats_an_unexpired_window(session, member, curator):
    """`is_live()` checks revocation before expiry, because the member's withdrawal is the stronger fact."""
    grant = grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["goals"], lifetime=timedelta(days=30)
    )
    revoke_grant(session, grant_id=grant.id, member_id=member.id)
    session.commit()
    assert grant.expires_at > utcnow()
    assert grant.is_live() is False


def test_an_expired_grant_stops_working_without_being_revoked(session, member, curator, furnished):
    """R-210 "time-limited". A member who forgets is still protected."""
    grant = grant_access(
        session,
        member_id=member.id,
        curator_id=curator.id,
        scope=["positions"],
        lifetime=timedelta(minutes=30),
    )
    session.commit()

    later = utcnow() + timedelta(hours=2)
    assert grant.is_live(at=later) is False
    with pytest.raises(AccessDenied):
        curator_view_positions(session, member_id=member.id, curator_id=curator.id, at=later)


def test_a_curator_cannot_revoke_another_members_grant(session, member, curator, granted):
    """Revocation belongs to the member. The id in the call is checked, not trusted."""
    other = register_member(session, age_at_registration=33, display_name="Not The Grantor")
    session.commit()
    with pytest.raises(AccessDenied):
        revoke_grant(session, grant_id=granted.id, member_id=other.id)
    assert session.get(AccessGrant, granted.id).is_live() is True


def test_revoking_everything_for_one_consultation(session, member, curator, consultation):
    """§6's `DELETE /api/curator/sessions/:id/grant`, in the service."""
    grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["vault"],
        curator_session_id=consultation.id,
    )
    grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["goals"],
        curator_session_id=consultation.id,
    )
    unrelated = grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["positions"]
    )
    session.commit()

    closed = revoke_session_grants(
        session, curator_session_id=consultation.id, member_id=member.id
    )
    session.commit()
    assert closed == 2
    assert unrelated.is_live() is True
    assert granted_scopes(session, member_id=member.id, curator_id=curator.id) == {"positions"}


def test_a_revocation_is_written_into_the_session_audit(session, member, curator, consultation):
    """C-10. The member withdrawing is part of what happened in the consultation."""
    grant = grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["vault"],
        curator_session_id=consultation.id,
    )
    revoke_grant(session, grant_id=grant.id, member_id=member.id)
    session.commit()

    kinds = [e.kind for e in session.get(CuratorSession, consultation.id).events]
    assert kinds == ["opened", "granted", "revoked"]


# ============================================================ R-210: the shape of a grant


def test_a_grant_must_name_a_known_scope(session, member, curator):
    with pytest.raises(UnknownScope):
        grant_access(session, member_id=member.id, curator_id=curator.id, scope=["everything"])


def test_a_grant_covering_nothing_is_refused(session, member, curator):
    with pytest.raises(UnknownScope):
        grant_access(session, member_id=member.id, curator_id=curator.id, scope=[])


def test_a_grant_always_ends(session, member, curator):
    """R-210 "time-limited". There is no "until revoked" and no null expiry."""
    grant = grant_access(session, member_id=member.id, curator_id=curator.id, scope=["goals"])
    assert grant.expires_at is not None
    assert grant.expires_at > grant.granted_at

    with pytest.raises(UnknownScope):
        grant_access(
            session, member_id=member.id, curator_id=curator.id, scope=["goals"],
            expires_at=utcnow() - timedelta(minutes=1),
        )


def test_a_grant_to_a_curator_that_does_not_exist_is_refused(session, member):
    """A40. `curator_id` names a row. A grant to a string is a grant to whoever claims the string."""
    with pytest.raises(CuratorAuthenticationFailed):
        grant_access(session, member_id=member.id, curator_id="curator:whoever", scope=["goals"])


def test_require_grant_rejects_a_scope_nothing_checks(session, member, curator, granted):
    with pytest.raises(UnknownScope):
        require_grant(session, member_id=member.id, curator_id=curator.id, scope="invented")


# ============================================================ R-211 / C-10: the session audit


def test_every_session_records_its_entry_point(session, member, curator):
    """R-211 / R-173. "Where were they when they needed a human" is only answerable if it is recorded."""
    record = open_session(
        session, member_id=member.id, curator_id=curator.id, opened_from="goal_detail"
    )
    session.commit()

    assert record.opened_from == "goal_detail"
    assert record.curator_id == curator.id
    events = session.execute(
        select(CuratorSessionEvent).where(CuratorSessionEvent.session_id == record.id)
    ).scalars().all()
    assert [e.kind for e in events] == ["opened"]
    assert events[0].detail["opened_from"] == "goal_detail"


def test_closing_a_session_appends_an_event_and_updates_nothing(session, member, curator, consultation):
    """R-211 / C-10. The outcome is a new row in the append-only table, never an UPDATE.

    Checked twice: the event exists, and the `curator_sessions` row is byte-identical to what was opened.
    """
    before = session.execute(
        text("SELECT id, member_id, curator_id, opened_from, opened_at, liability_flag "
             "FROM curator_sessions WHERE id = :i"),
        {"i": consultation.id},
    ).one()

    close_session(
        session,
        session_id=consultation.id,
        curator_id=curator.id,
        outcome="handoff_completed",
        liability_flag=False,
    )
    session.commit()

    after = session.execute(
        text("SELECT id, member_id, curator_id, opened_from, opened_at, liability_flag "
             "FROM curator_sessions WHERE id = :i"),
        {"i": consultation.id},
    ).one()
    assert before == after, "closing a session modified the session row; C-10 says append"

    kinds = [e.kind for e in session.get(CuratorSession, consultation.id).events]
    assert kinds == ["opened", "closed"]


def test_the_outcome_is_readable_from_the_appended_event(session, member, curator, consultation):
    """R-211. §4 lists `closed_at` and `outcome` on the session; they are derived, and they still work."""
    close_session(
        session, session_id=consultation.id, curator_id=curator.id,
        outcome="referred_to_pension_specialist", liability_flag=True,
    )
    session.commit()

    record = session.get(CuratorSession, consultation.id)
    assert record.outcome == "referred_to_pension_specialist"
    assert record.closed_at is not None
    closing = [e for e in record.events if e.kind == "closed"][-1]
    assert closing.detail["liability_flag"] is True


def test_a_session_cannot_be_closed_twice(session, curator, consultation):
    close_session(session, session_id=consultation.id, curator_id=curator.id, outcome="done")
    session.commit()
    with pytest.raises(SessionAlreadyClosed):
        close_session(session, session_id=consultation.id, curator_id=curator.id, outcome="done again")


def test_a_session_cannot_be_closed_without_an_outcome(session, curator, consultation):
    """R-211 records the outcome. A blank one is a session that happened and was not accounted for."""
    with pytest.raises(ValueError):
        close_session(session, session_id=consultation.id, curator_id=curator.id, outcome="   ")


def test_a_session_can_be_closed_after_the_member_revokes(session, member, curator, consultation):
    """C-10 outranks R-210 here, deliberately.

    An audit trail that a member can leave open by withdrawing consent is an audit trail with a hole in
    it. Revoking stops the reads; it does not stop the record being completed.
    """
    grant = grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=list(GRANTABLE),
        curator_session_id=consultation.id,
    )
    revoke_grant(session, grant_id=grant.id, member_id=member.id)
    session.commit()

    with pytest.raises(AccessDenied):
        curator_view_goals(session, member_id=member.id, curator_id=curator.id)

    close_session(session, session_id=consultation.id, curator_id=curator.id, outcome="member_revoked")
    session.commit()
    assert session.get(CuratorSession, consultation.id).outcome == "member_revoked"


def test_curator_audit_table_rejects_update_and_delete(session, curator, consultation):
    """C-10, the spec's named constraint test, at the storage layer rather than in the ORM."""
    event_id = session.execute(
        select(CuratorSessionEvent.id).where(CuratorSessionEvent.session_id == consultation.id)
    ).scalars().first()

    with pytest.raises(Exception) as update_refused:
        session.execute(
            text("UPDATE curator_session_events SET actor = 'someone else' WHERE id = :i"),
            {"i": event_id},
        )
    assert "append-only" in str(update_refused.value)
    session.rollback()

    with pytest.raises(Exception) as delete_refused:
        session.execute(text("DELETE FROM curator_session_events WHERE id = :i"), {"i": event_id})
    assert "append-only" in str(delete_refused.value)
    session.rollback()


def test_a_note_needs_a_live_grant(session, member, curator, consultation):
    """A curator's note, written while reading a member's vault, is the member's material."""
    with pytest.raises(AccessDenied):
        record_note(
            session, session_id=consultation.id, member_id=member.id,
            curator_id=curator.id, text="Freizügigkeitskonto bei der Bank Y",
        )

    grant_access(session, member_id=member.id, curator_id=curator.id, scope=["vault"])
    session.commit()
    event = record_note(
        session, session_id=consultation.id, member_id=member.id,
        curator_id=curator.id, text="Freizügigkeitskonto bei der Bank Y",
    )
    session.commit()
    assert event.kind == "note"
    assert event.actor == curator.id


def test_a_session_belongs_to_one_curator(session, member, curator, consultation):
    """C-10's "who" is a row. Another curator cannot act inside this consultation."""
    other = create_curator(
        session, display_name="Andere Kuratorin", email="andere@example.ch", password=CURATOR_PASSWORD
    )
    session.commit()
    with pytest.raises(NoOpenSession):
        close_session(session, session_id=consultation.id, curator_id=other.id, outcome="not mine")


def test_the_audit_metadata_survives_revocation_and_the_notes_do_not(
    session, member, curator, consultation
):
    """`session_record`: C-10 keeps the shape of the consultation; R-210 keeps the member's words.

    The redaction is explicit rather than an omission, because a note that was never written and a note
    that is being withheld must not look the same in an audit.
    """
    grant = grant_access(session, member_id=member.id, curator_id=curator.id, scope=["vault"])
    record_note(
        session, session_id=consultation.id, member_id=member.id,
        curator_id=curator.id, text="Freizügigkeitskonto bei der Bank Y",
    )
    session.commit()

    open_view = session_record(
        session, session_id=consultation.id, member_id=member.id, curator_id=curator.id
    )
    assert open_view["notes_readable"] is True
    assert any(e["detail"].get("text") for e in open_view["events"] if e["kind"] == "note")

    revoke_grant(session, grant_id=grant.id, member_id=member.id)
    session.commit()

    closed_view = session_record(
        session, session_id=consultation.id, member_id=member.id, curator_id=curator.id
    )
    assert closed_view["notes_readable"] is False
    assert closed_view["opened_from"] == "workbench"
    notes = [e for e in closed_view["events"] if e["kind"] == "note"]
    assert notes, "the note is still in the audit; only its body is withheld"
    assert "Freizügigkeitskonto" not in str(notes)
    assert notes[0]["detail"]["redacted"]


def test_a_curator_sees_only_their_own_sessions(session, member, curator, consultation):
    other = create_curator(
        session, display_name="Andere", email="andere2@example.ch", password=CURATOR_PASSWORD
    )
    session.commit()
    assert [s["id"] for s in sessions_for_curator(session, curator_id=curator.id)] == [consultation.id]
    assert sessions_for_curator(session, curator_id=other.id) == []


# ============================================================ R-212 / C-01: the recommendation


def test_a_curators_recommendation_is_attributed_to_that_curator(
    session, member, curator, furnished, granted, consultation
):
    """R-212. Not "a curator" — which one. `author_ref` is the whole requirement."""
    decision = recommend(
        session,
        session_id=consultation.id,
        member_id=member.id,
        curator_id=curator.id,
        question="Wie weiter mit dem Freizügigkeitskonto?",
        choice="Bei der Stiftung belassen, bis die Anstellung geklärt ist",
        reasoning="Die Anstellung ist im Wandel; ein Wechsel jetzt bindet das Guthaben.",
        options_considered=[{"option": "belassen"}, {"option": "auf ein neues Konto übertragen"}],
    )
    session.commit()

    stored = session.get(Decision, decision.id)
    assert stored.author == "curator"
    assert stored.author_ref == curator.id
    assert stored.curator_session_id == consultation.id


def test_a_recommendation_that_touches_the_plan_is_one_transaction(
    session, member, curator, furnished, granted, consultation
):
    """C-09. The Decision and the plan objects it accounts for are linked, written through `mutate_plan`."""
    decision = recommend(
        session,
        session_id=consultation.id,
        member_id=member.id,
        curator_id=curator.id,
        question="Soll das Mutgeld an die Anstellung gekoppelt werden?",
        choice="Ja",
        position_ids=[furnished["position"].id],
        goal_ids=[furnished["goal"].id],
    )
    session.commit()

    assert decision.linked_position_ids == [furnished["position"].id]
    assert decision.linked_goal_ids == [furnished["goal"].id]


def test_a_recommendation_is_written_into_the_session_audit(
    session, member, curator, granted, consultation
):
    """C-10. Someone reading the session log should not have to know to go and read the decisions."""
    decision = recommend(
        session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
        question="Frage", choice="Antwort",
    )
    session.commit()

    notes = [e for e in session.get(CuratorSession, consultation.id).events if e.kind == "note"]
    assert notes[-1].detail["decision_id"] == decision.id
    assert notes[-1].actor == curator.id


def test_an_unknown_curator_cannot_write_a_curator_attributed_decision(
    session, member, granted, consultation
):
    """C-01. There is no path by which an unauthenticated caller writes a Decision attributed to a curator.

    The id has to resolve to an active row in `curators`, which is only obtainable by authenticating.
    """
    with pytest.raises(CuratorAuthenticationFailed):
        recommend(
            session, session_id=consultation.id, member_id=member.id, curator_id="curator:anyone",
            question="Frage", choice="Kaufen Sie Fonds X",
        )
    assert session.execute(select(Decision).where(Decision.author == "curator")).first() is None


def test_a_deactivated_curator_cannot_recommend(session, member, curator, granted, consultation):
    curator.active = False
    session.commit()
    with pytest.raises(CuratorAuthenticationFailed):
        recommend(
            session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
            question="Frage", choice="Antwort",
        )


def test_a_recommendation_needs_an_open_session(session, member, curator, granted, consultation):
    """R-211. A recommendation outside a recorded session would be advice with no audit."""
    close_session(session, session_id=consultation.id, curator_id=curator.id, outcome="done")
    session.commit()
    with pytest.raises(SessionAlreadyClosed):
        recommend(
            session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
            question="Frage", choice="Antwort",
        )


def test_a_recommendation_needs_the_decisions_scope(session, member, curator, consultation):
    """R-210. Writing into a member's record is reading it too."""
    grant_access(session, member_id=member.id, curator_id=curator.id, scope=["goals"])
    session.commit()
    with pytest.raises(AccessDenied):
        recommend(
            session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
            question="Frage", choice="Antwort",
        )


def test_a_recommendation_cannot_link_another_members_plan(
    session, member, curator, furnished, granted, consultation
):
    other = register_member(session, age_at_registration=60, display_name="Someone Else")
    session.commit()
    with mutate_plan(session, member_id=other.id, question="q", choice="c") as decision:
        theirs = Position(member_id=other.id, role="growth", capital_type="financial", label="Depot")
        session.add(theirs)
        decision.linked_positions.append(theirs)
    session.commit()

    with pytest.raises(AccessDenied):
        recommend(
            session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
            question="Frage", choice="Antwort", position_ids=[theirs.id],
        )


def test_the_member_sees_the_curators_recommendation_in_their_own_decisions(
    session, member, curator, granted, consultation
):
    """R-212 read back: attribution is visible in the record the member owns."""
    recommend(
        session, session_id=consultation.id, member_id=member.id, curator_id=curator.id,
        question="Frage", choice="Antwort",
    )
    session.commit()

    payload = curator_view_decisions(session, member_id=member.id, curator_id=curator.id)
    attributed = [d for d in payload["decisions"] if d["author"] == "curator"]
    assert attributed and attributed[0]["author_ref"] == curator.id


# ============================================================ A40 / A43: the curator's own login


def test_a_curator_logs_in_as_a_curator(session, curator):
    """A40. Their own table, their own credential — never a flag on a member row."""
    found = authenticate_curator(session, email="kurator@example.ch", password=CURATOR_PASSWORD)
    assert found.id == curator.id
    assert found.email == "kurator@example.ch", "the address is normalised on the way in"


def test_a_wrong_password_and_an_unknown_address_are_indistinguishable(session, curator):
    """The same refusal for both, so the form is not a roster of who curates for eigentliCH."""
    with pytest.raises(CuratorAuthenticationFailed) as wrong:
        authenticate_curator(session, email="kurator@example.ch", password="falsch aber lang genug")
    with pytest.raises(CuratorAuthenticationFailed) as unknown:
        authenticate_curator(session, email="niemand@example.ch", password=CURATOR_PASSWORD)
    assert str(wrong.value) == str(unknown.value)


def test_a_deactivated_curator_cannot_log_in(session, curator):
    curator.active = False
    session.commit()
    with pytest.raises(CuratorAuthenticationFailed):
        authenticate_curator(session, email="kurator@example.ch", password=CURATOR_PASSWORD)


def test_a_curator_password_has_the_same_length_floor(session):
    with pytest.raises(WeakPassword):
        create_curator(session, display_name="Kurz", email="kurz@example.ch", password="zu kurz")


def test_the_curator_password_is_stored_hashed_and_salted(session, curator):
    row = session.get(Curator, curator.id)
    assert row.password_hash and row.password_salt and row.iterations
    assert CURATOR_PASSWORD.encode("utf-8") not in row.password_hash


def test_an_operator_reset_sets_a_new_curator_password(session, curator):
    """A43. The operator has the machine, so a reset is performed rather than emailed."""
    reset_curator_password(session, email="kurator@example.ch", new_password="ein neues langes wort")
    session.commit()

    with pytest.raises(CuratorAuthenticationFailed):
        authenticate_curator(session, email="kurator@example.ch", password=CURATOR_PASSWORD)
    assert authenticate_curator(
        session, email="kurator@example.ch", password="ein neues langes wort"
    ).id == curator.id


def test_the_curator_reset_names_reset_py_as_its_pattern():
    """A43. There is no curator CLI yet, and the module says where the pattern is if one is wanted.

    Checked in the source because the note is the deliverable: an unused command path is a second thing to
    keep correct, and the next person needs to be told that rather than left to guess.
    """
    import eigentlich.services.curator as service

    assert "reset.py" in (service.__doc__ or ""), "the module docstring must name A43's pattern"
    assert "A43" in (service.reset_curator_password.__doc__ or "")


def test_registering_the_same_curator_twice_is_refused(session, curator):
    with pytest.raises(CuratorAuthenticationFailed):
        create_curator(
            session, display_name="Doppelt", email="KURATOR@example.ch", password=CURATOR_PASSWORD
        )


# ============================================================ the HTTP surface


@pytest.fixture()
def api(monkeypatch):
    """The router on its own app. Yields `(client, member_id, member_token, curator_basic)`.

    Deliberately not `eigentlich.api.main.app`: main.py is wired by hand, this router is not in it yet, and
    importing it here would open the real database file to prove something about a status code. Its own
    engine on a `StaticPool` for the reason `test_learning.py` gives — `TestClient` serves on a worker
    thread, and in-memory SQLite is per connection.

    **`session_overrides` rather than one override.** The grant routes resolve their member through
    `api.auth.current_member` — `api/curator.py` stopped carrying its own copy when A11 was wired on
    31 August 2026 — and that dependency takes its database session from `api.auth.get_session`.
    Overriding only this router's would have authenticated the token against the developer's real
    `backend/eigentlich.db` while the routes read this fixture, which is A68's failure mode exactly.
    """
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)
    import base64

    from eigentlich.api.curator import get_session, router

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    with make_session_factory(engine)() as api_session:
        member, _ = register_with_credentials(
            api_session,
            email="mitglied@example.ch",
            password="ein ziemlich langes passwort",
            age_at_registration=44,
            display_name="API Member",
        )
        api_session.commit()
        _, token = login(
            api_session, email="mitglied@example.ch", password="ein ziemlich langes passwort"
        )
        row = create_curator(
            api_session,
            display_name="API Kurator",
            email="api-kurator@example.ch",
            password=CURATOR_PASSWORD,
        )
        api_session.commit()

        basic = base64.b64encode(
            f"api-kurator@example.ch:{CURATOR_PASSWORD}".encode("utf-8")
        ).decode("ascii")

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        with TestClient(app) as client:
            yield client, member.id, token, f"Basic {basic}", row.id
    engine.dispose()


def test_no_curator_route_serves_member_data_unauthenticated(api):
    """C-01 and R-210 at the edge. Nothing here is readable without being someone."""
    client, member_id, _, _, _ = api
    for path in (
        f"/api/curator/members/{member_id}",
        f"/api/curator/members/{member_id}/positions",
        f"/api/curator/members/{member_id}/goals",
        f"/api/curator/members/{member_id}/vault",
        f"/api/curator/members/{member_id}/decisions",
        f"/api/curator/members/{member_id}/actions",
    ):
        assert client.get(path).status_code == 401, path


def test_an_authenticated_curator_without_a_grant_gets_a_refusal_not_an_empty_payload(api):
    """R-210 over HTTP. 403 with the reason, never 200 with nothing in it."""
    client, member_id, _, basic, _ = api
    response = client.get(
        f"/api/curator/members/{member_id}/positions", headers={"Authorization": basic}
    )
    assert response.status_code == 403
    assert "R-210" in response.json()["detail"]


def test_the_member_grants_and_the_curator_can_then_read(api):
    """R-210, end to end, with the two doors: the member's token grants, the curator's login reads."""
    client, member_id, token, basic, curator_id = api

    created = client.post(
        "/api/curator/grants",
        json={"curator_id": curator_id, "scope": ["positions", "goals"], "hours": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    assert created.json()["expires_at"]

    allowed = client.get(
        f"/api/curator/members/{member_id}/goals", headers={"Authorization": basic}
    )
    assert allowed.status_code == 200

    refused = client.get(
        f"/api/curator/members/{member_id}/vault", headers={"Authorization": basic}
    )
    assert refused.status_code == 403, "a scope that was not granted stays shut"


def test_a_grant_cannot_be_created_for_someone_else(api):
    """R-213. `member_id` is read off the token; there is no body field to put another member's id in."""
    client, member_id, token, _, curator_id = api
    response = client.post(
        "/api/curator/grants",
        json={"curator_id": curator_id, "scope": ["goals"], "member_id": "someone-else"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    listed = client.get(
        "/api/curator/grants", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [g["id"] for g in listed["grants"]] == [response.json()["id"]]
    assert listed["member_id"] == member_id


def test_revoking_over_http_takes_effect_on_the_next_request(api):
    """R-213 at the edge. The window is still open; the access is not."""
    client, member_id, token, basic, curator_id = api
    grant = client.post(
        "/api/curator/grants",
        json={"curator_id": curator_id, "scope": ["goals"], "hours": 24},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert client.get(
        f"/api/curator/members/{member_id}/goals", headers={"Authorization": basic}
    ).status_code == 200

    revoked = client.delete(
        f"/api/curator/grants/{grant['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 200
    assert revoked.json()["deleted"] is False
    assert revoked.json()["revoked_at"]

    assert client.get(
        f"/api/curator/members/{member_id}/goals", headers={"Authorization": basic}
    ).status_code == 403


def test_a_curator_cannot_revoke_a_grant_with_their_own_credentials(api):
    """R-213. Revocation is the member's, and a curator's Basic header is not a member token."""
    client, _, token, basic, curator_id = api
    grant = client.post(
        "/api/curator/grants",
        json={"curator_id": curator_id, "scope": ["goals"]},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert client.delete(
        f"/api/curator/grants/{grant['id']}", headers={"Authorization": basic}
    ).status_code == 401


def test_a_recommendation_over_http_is_attributed_to_the_authenticated_curator(api):
    """R-212 / C-01. `author_ref` comes from the credential, never from the request body."""
    client, member_id, token, basic, curator_id = api
    client.post(
        "/api/curator/grants",
        json={"curator_id": curator_id, "scope": ["decisions"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    opened = client.post(
        "/api/curator/workbench/sessions",
        json={"member_id": member_id, "opened_from": "workbench"},
        headers={"Authorization": basic},
    ).json()

    made = client.post(
        f"/api/curator/members/{member_id}/recommendations",
        json={
            "session_id": opened["id"],
            "question": "Wie weiter?",
            "choice": "Belassen",
            "author_ref": "someone-else",
        },
        headers={"Authorization": basic},
    )
    assert made.status_code == 201
    assert made.json()["author"] == "curator"
    assert made.json()["author_ref"] == curator_id, "the body must not be able to set the attribution"


def test_closing_a_session_over_http_appends(api):
    """R-211 / C-10 at the edge."""
    client, member_id, _, basic, _ = api
    opened = client.post(
        "/api/curator/workbench/sessions",
        json={"member_id": member_id, "opened_from": "know_panel"},
        headers={"Authorization": basic},
    ).json()

    closed = client.post(
        f"/api/curator/members/{member_id}/sessions/{opened['id']}/close",
        json={"outcome": "handoff_completed", "liability_flag": False},
        headers={"Authorization": basic},
    )
    assert closed.status_code == 200
    assert closed.json()["appended"] is True

    again = client.post(
        f"/api/curator/members/{member_id}/sessions/{opened['id']}/close",
        json={"outcome": "handoff_completed"},
        headers={"Authorization": basic},
    )
    assert again.status_code == 409


def test_the_grantable_vocabulary_offers_no_everything(api):
    """R-210 "scoped". A client renders the member's choices; it does not get an all-access option."""
    client, _, _, _, _ = api
    payload = client.get("/api/curator/grantable").json()
    assert payload["grantable"] == list(GRANTABLE)
    for forbidden in ("all", "everything", "full", "*"):
        assert forbidden not in payload["grantable"]


def test_the_router_is_wired_by_main_and_not_defined_there(api):
    """Phase 5 defined its surface in its own file so four phases could be built in parallel.

    The original form of this asserted main.py did not mention the router at all — correct while the
    phases were being written concurrently, wrong once they were wired together. What it was protecting
    is that the routes are DEFINED here, not there, and that is what it now checks.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).parent.parent / "eigentlich" / "api" / "main.py"
    ).read_text(encoding="utf-8")
    assert "from .curator import router as curator_router" in source, (
        "api/main.py should wire this router; it is the one place that knows the whole surface exists"
    )
    # What the original assertion was really protecting: that phase 5 defined its surface in its own
    # file rather than by editing main.py. That still holds — main.py imports and includes, and defines
    # none of these routes itself.
    assert "@app.get(\"/api/curator" not in source
    assert "@app.post(\"/api/curator/grants" not in source
