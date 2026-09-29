"""R-231's erasure, reachable. `POST /api/settings/erasure`.

**What was wrong.** `services/erasure.py` was complete, well tested and callable only from
`tests/test_erasure.py`. The route a member could actually reach — `POST /api/settings/deletion` — wrote a
Decision and returned `executed: false`, with a reason (`retention_scope_undecided`) that A61 had already
answered on 30 August 2026. So R-231 was not partly built: it was built and unreachable, and the product
told the member deletion was impossible. A90 found the pair.

`tests/test_erasure.py` holds what the erasure *does*, table by table. This file holds that a member can
reach it, that the confirmation cannot be got past, and that a refused attempt destroys nothing.

**Every test here runs on a throwaway in-memory database**, asserted in the fixture rather than assumed.
An erasure test pointed at `backend/eigentlich.db` would delete the developer's own account and the
demonstration roster with it — A68 was a test that silently used the wrong database, and the consequence
here is not a wrong result but a destroyed one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import StaticPool

from eigentlich.api.auth import router as auth_router
from eigentlich.api.erasure import ERASURE_PATH, router as erasure_router
from eigentlich.api.remainder import get_store, router as remainder_router
from eigentlich.consent import BY_KEY, PURPOSES
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import (
    Consent,
    Credential,
    Decision,
    Goal,
    Member,
    OnboardingAnswer,
    Position,
    Session as SessionRow,
    VaultItem,
)
from eigentlich.services import mutate_plan, record_answer, store_item
from eigentlich.services.auth import register_with_credentials
from eigentlich.services.erasure import CONFIRMATION_PHRASES, REDACTED
from eigentlich.services.settings import ERASURE_ROUTE
from eigentlich.services.vault import VaultStore
from conftest import session_overrides

PASSWORD = "ein ziemlich langes passwort"
PHRASE_DE = CONFIRMATION_PHRASES["de"]
PHRASE_EN = CONFIRMATION_PHRASES["en"]

SERVICE = Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "erasure.py"

CONSENT_BODY = [
    {"purpose": purpose.key, "document_version": purpose.document_version}
    for purpose in PURPOSES
    if purpose.required_at_registration
]


@pytest.fixture()
def api(tmp_path, fast_kdf):
    """The three routers on their own app, their own vault and a throwaway in-memory database.

    `api/erasure.py` takes its `get_session` from `api/auth.py` rather than defining its own, so
    `session_overrides` covers it without anyone having to add it to `conftest`'s module list. That is a
    deliberate property of that module and this fixture is where it pays: forgetting the list entry for
    any other router gives a test that reads the wrong database, and for this one it would give a test
    that *erases* it.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    assert ":memory:" in str(engine.url), (
        "this fixture must never touch a file on disk: these tests destroy every row they can reach"
    )
    create_all(engine)
    store = VaultStore(tmp_path / "vault")
    with make_session_factory(engine)() as db_session:
        app = FastAPI()
        for router in (auth_router, remainder_router, erasure_router):
            app.include_router(router)
        app.dependency_overrides.update(session_overrides(db_session))
        app.dependency_overrides[get_store] = lambda: store
        with TestClient(app) as client:
            yield client, db_session, store
    engine.dispose()


def _furnish(db_session, store, *, email="weg@example.ch", name="Zu löschen"):
    """A member with a row in everything the erasure touches, and a credential to confirm with."""
    member, _credential = register_with_credentials(
        db_session,
        email=email,
        password=PASSWORD,
        age_at_registration=44,
        display_name=name,
        consents=CONSENT_BODY,
    )
    db_session.commit()

    record_answer(
        db_session, member_id=member.id, question_key="employment_position", value="Treuhand"
    )
    with mutate_plan(
        db_session,
        member_id=member.id,
        question="Anstellung erfassen?",
        choice="Ja, als Einkommensposition",
        reasoning="Aus dem Erstgespräch",
    ) as decision:
        position = Position(
            member_id=member.id, role="income", capital_type="human", label="Anstellung"
        )
        goal = Goal(member_id=member.id, name="Wohneigentum")
        db_session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    store_item(
        db_session,
        store,
        member_id=member.id,
        kind="note",
        title="Notiz",
        source="manual",
        notes="etwas",
    )
    db_session.commit()
    return member, decision.id


def _token(client, email=  "weg@example.ch"):
    response = client.post("/api/session", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _counts(db_session, member_id):
    return {
        model.__name__: len(
            db_session.execute(select(model).where(model.member_id == member_id)).scalars().all()
        )
        for model in (Consent, Credential, Goal, OnboardingAnswer, Position, SessionRow, VaultItem)
    }


# ============================================================ the route exists and matches the receipt


def test_the_route_the_receipt_promises_is_the_route_this_router_serves(api):
    """Step one hands the member `execute_at`; step two has to be there.

    Two constants derived from one (`services/settings.ERASURE_ROUTE`), so this is a check that the
    derivation still resolves rather than two strings someone kept in step.
    """
    client, db_session, store = api
    _furnish(db_session, store)
    token = _token(client)

    receipt = client.post("/api/settings/deletion", headers=_bearer(token), json={})
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["executed"] is False
    assert receipt.json()["execute_at"] == ERASURE_ROUTE
    assert ERASURE_ROUTE == f"POST /api{ERASURE_PATH}"

    # And it is served, not merely named.
    assert client.get(f"/api{ERASURE_PATH}", headers=_bearer(token)).status_code == 200


def test_the_confirmation_route_says_what_is_required(api):
    client, db_session, store = api
    _furnish(db_session, store)
    token = _token(client)
    payload = client.get(f"/api{ERASURE_PATH}", headers=_bearer(token)).json()
    assert payload["confirmation_phrase"] == PHRASE_DE
    assert payload["requires_password"] is True
    assert payload["irreversible"] is True


def test_the_confirmation_route_refuses_without_a_token(api):
    """It names the exact sentence that destroys an account, which is not a string to hand out."""
    client, _, _ = api
    assert client.get(f"/api{ERASURE_PATH}").status_code == 401
    assert client.post(f"/api{ERASURE_PATH}").status_code == 401


# ============================================================ end to end


def test_a_member_can_erase_their_own_record_end_to_end(api):
    """**R-231, reachable.** Register, log in, confirm, and the record is gone.

    Asserted on the rows rather than on the report: the report is a claim and the tables are the fact.

    **Planted violation:** replaced `erase_on_member_request`'s call to `erase_member` with an empty
    `ErasureReport`, so the route answered 200 with a well-formed receipt and destroyed nothing — the worst
    version of this defect, and the one a status-code assertion would have missed. This failed on the row
    counts. Restored.
    """
    client, db_session, store = api
    member, decision_id = _furnish(db_session, store)
    member_id = member.id
    token = _token(client)

    before = _counts(db_session, member_id)
    assert all(count for count in before.values()), f"the fixture furnished nothing: {before}"

    response = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD, "reason": "Kein Bedarf mehr."},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["executed"] is True
    assert payload["irreversible"] is True
    assert payload["member_id"] == member_id
    assert payload["deleted"]["members"] == 1
    assert payload["redacted"]["decisions"] >= 1
    assert payload["vault_bytes_removed"] is True

    db_session.expire_all()
    assert db_session.get(Member, member_id) is None
    after = _counts(db_session, member_id)
    assert not any(after.values()), f"rows survived the erasure: {after}"

    # R-040 and C-10: the Decision row stays and is emptied of the member.
    decision = db_session.get(Decision, decision_id)
    assert decision is not None, "an append-only row was deleted rather than redacted"
    assert decision.member_id is None
    assert decision.question == REDACTED
    assert decision.reasoning is None


def test_the_decision_recording_the_request_is_written_and_then_redacted(api):
    """A61 carried through: the request to be erased is itself a fact about this member.

    The id survives and is returned, so an operator reading `decisions` can tell which redacted row was
    the request. That is the whole of what remains, and it is deliberate rather than an oversight.
    """
    client, db_session, store = api
    _furnish(db_session, store)
    token = _token(client)

    payload = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD, "reason": "Umzug ins Ausland."},
    ).json()

    db_session.expire_all()
    recorded = db_session.get(Decision, payload["decision_id"])
    assert recorded is not None
    assert payload["decision_was_redacted_with_the_rest"] is True
    assert recorded.member_id is None
    assert recorded.reasoning is None, "the member's stated reason survived their own erasure"


def test_the_token_that_authorised_the_erasure_stops_working(api):
    """The member's `sessions` rows are among those destroyed. A client should treat this as a logout."""
    client, db_session, store = api
    _furnish(db_session, store)
    token = _token(client)

    assert client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD},
    ).status_code == 200

    assert client.get("/api/settings/consents", headers=_bearer(token)).status_code == 401


def test_the_append_only_triggers_are_back_afterwards(api):
    """A66, from the route rather than from the service.

    The erasure drops the four triggers, redacts, and re-creates them on the session's own connection. It
    was once doing that through `engine.begin()`, so the CREATEs committed before the DROPs and the
    database was left with no append-only guarantee at all — silently. This is the same check A66 bought,
    made through the path a member actually takes.

    **Planted violation:** removed the re-creation loop from `_erase`'s `finally`. This failed naming all
    four triggers. Restored.
    """
    client, db_session, store = api
    _furnish(db_session, store)
    token = _token(client)
    client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD},
    )

    names = {
        row[0]
        for row in db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger'")
        ).all()
    }
    for expected in (
        "trg_decisions_no_update",
        "trg_decisions_no_delete",
        "trg_curator_session_events_no_update",
        "trg_curator_session_events_no_delete",
    ):
        assert expected in names, f"{expected} is gone after an erasure: {sorted(names)}"

    # Present and firing.
    with pytest.raises(Exception):
        db_session.execute(text("DELETE FROM decisions"))
        db_session.flush()
    db_session.rollback()


def test_a_member_who_had_applied_to_be_listed_can_still_leave(api):
    """A73, through the route. The `Provider` chain is why this once failed entirely.

    Erasing a member who had been through `apply_to_be_listed` used to raise on `DELETE FROM members` and
    roll the whole erasure back, so the member could not leave at all. Held here as well as in
    `test_erasure.py` because the route is the path where that failure would have reached a person.
    """
    from eigentlich.services.marketplace import apply_to_be_listed

    client, db_session, store = api
    member, _ = _furnish(db_session, store)
    # The id as a plain string, captured before the row goes. Reading `member.id` off the instance
    # afterwards raises ObjectDeletedError — a test failure that reads like a product failure.
    member_id = member.id
    apply_to_be_listed(
        db_session,
        member_id=member_id,
        display_name="Praxis",
        title="Praxis",
        domain="health",
        qualification_pipeline="professional_registration",
        roles=["protection"],
        registration_refs=["GLN-7601000000001"],
    )
    db_session.commit()
    token = _token(client)

    response = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.get(Member, member_id) is None


# ============================================================ the refusals


@pytest.mark.parametrize(
    "confirmation",
    [
        "",
        "ja",
        "loeschen",
        "alle meine daten löschen",
        "ALLE MEINE DATEN LOSCHEN",
        "ALLE MEINE DATEN LÖSCHEN!",
        "ALLE MEINE DATEN",
        "SUPPRIMER TOUTES MES DONNÉES",
        "true",
        "1",
    ],
    ids=repr,
)
def test_anything_that_is_not_the_sentence_destroys_nothing(api, confirmation):
    """**The guard on the destructive route.** Ten near-misses, and after each one the record is intact.

    Case is not folded and punctuation is not stripped: `alle meine daten löschen` is a different string,
    and a guard that decided it meant the same thing would be deciding what the member meant. `"true"` and
    `"1"` are in the list because they are what a boolean field would have accepted — the reason this is a
    typed sentence and not a checkbox.

    **Planted violation:** changed `_confirmed` to `offered.strip().lower() in {p.lower() for p in ...}`.
    Two of these ten went green and the record was destroyed by a lowercase sentence. Restored.
    """
    client, db_session, store = api
    member, _ = _furnish(db_session, store)
    token = _token(client)
    before = _counts(db_session, member.id)

    refused = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": confirmation, "password": PASSWORD},
    )
    assert refused.status_code == 422, f"{confirmation!r} was accepted: {refused.status_code}"

    db_session.expire_all()
    assert db_session.get(Member, member.id) is not None, f"{confirmation!r} erased the member"
    assert _counts(db_session, member.id) == before


def test_the_english_sentence_is_accepted_too(api):
    """Two exact strings are no less unambiguous than one, and refusing an English member who typed the
    English sentence would be the guard misfiring on the person it protects."""
    client, db_session, store = api
    member, _ = _furnish(db_session, store, email="en@example.ch", name="To erase")
    member_id = member.id
    token = _token(client, "en@example.ch")

    response = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_EN, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.get(Member, member_id) is None


@pytest.mark.parametrize("field", ["confirmation", "password"], ids=lambda f: f"no {f}")
def test_a_missing_field_is_refused_by_the_schema_and_destroys_nothing(api, field):
    """Neither has a default. A default on either would be the destructive route's own bypass."""
    client, db_session, store = api
    member, _ = _furnish(db_session, store)
    token = _token(client)

    body = {"confirmation": PHRASE_DE, "password": PASSWORD}
    del body[field]
    refused = client.post(f"/api{ERASURE_PATH}", headers=_bearer(token), json=body)
    assert refused.status_code == 422
    db_session.expire_all()
    assert db_session.get(Member, member.id) is not None


def test_a_valid_token_is_not_enough_without_the_password(api):
    """Re-authentication, and the reason for it: a token left open on a borrowed laptop would otherwise be
    enough to destroy somebody's whole record.

    403 and not 401 — the session is valid and the member is who they say; what is wrong is the password
    in the body, and a 401 would tell the client to throw away a good token. The same reading
    `POST /api/password` takes.

    **Planted violation:** removed the `credential.verify(password)` check from
    `erase_on_member_request`. This failed with a 200 and an erased member. Restored.
    """
    client, db_session, store = api
    member, _ = _furnish(db_session, store)
    token = _token(client)
    before = _counts(db_session, member.id)

    refused = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": "das falsche passwort hier"},
    )
    assert refused.status_code == 403, refused.text

    db_session.expire_all()
    assert db_session.get(Member, member.id) is not None
    assert _counts(db_session, member.id) == before


def test_one_member_cannot_erase_another(api):
    """A81's rule where it matters most: the request model carries no `member_id`, so there is nothing to
    aim. An extra field is dropped by pydantic rather than preferred — and the erasure lands on the token's
    own member.

    **Planted violation:** added `member_id: str | None = None` to `ErasureConfirmation` and passed it
    through when present. A erased B and this failed. Restored.
    """
    client, db_session, store = api
    victim, _ = _furnish(db_session, store, email="opfer@example.ch", name="Bleibt")
    attacker, _ = _furnish(db_session, store, email="taeter@example.ch", name="Geht")
    victim_id, attacker_id = victim.id, attacker.id
    token = _token(client, "taeter@example.ch")

    response = client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={
            "member_id": victim_id,
            "confirmation": PHRASE_DE,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["member_id"] == attacker_id

    db_session.expire_all()
    assert db_session.get(Member, victim_id) is not None, "a member_id in the body steered the erasure"
    assert db_session.get(Member, attacker_id) is None


def test_the_erasure_does_not_reach_another_members_rows(api):
    """The other half: B is furnished as fully as A, and nothing of B's goes with A."""
    client, db_session, store = api
    stays, stays_decision = _furnish(db_session, store, email="bleibt@example.ch", name="Bleibt")
    goes, _ = _furnish(db_session, store, email="geht@example.ch", name="Geht")
    stays_id, goes_id = stays.id, goes.id
    token = _token(client, "geht@example.ch")

    before = _counts(db_session, stays_id)
    assert client.post(
        f"/api{ERASURE_PATH}",
        headers=_bearer(token),
        json={"confirmation": PHRASE_DE, "password": PASSWORD},
    ).status_code == 200

    db_session.expire_all()
    assert db_session.get(Member, goes_id) is None
    assert db_session.get(Member, stays_id) is not None
    assert _counts(db_session, stays_id) == before
    surviving = db_session.get(Decision, stays_decision)
    assert surviving.member_id == stays_id
    assert surviving.question != REDACTED, "another member's Decision was redacted"


# ============================================================ the confirmation is the service's, not the edge's


def test_the_confirmation_and_the_password_are_checked_in_the_service(api):
    """So that a second route added next year cannot perform the act without them.

    Called directly, with no HTTP in the path, because "the route checks it" is the guarantee that stops
    being true the moment there are two routes.
    """
    from eigentlich.services.auth import AuthenticationFailed
    from eigentlich.services.erasure import ErasureNotConfirmed, erase_on_member_request

    _client, db_session, store = api
    member, _ = _furnish(db_session, store)

    with pytest.raises(ErasureNotConfirmed):
        erase_on_member_request(
            db_session, store, member_id=member.id, confirmation="ja", password=PASSWORD
        )
    with pytest.raises(AuthenticationFailed):
        erase_on_member_request(
            db_session, store, member_id=member.id, confirmation=PHRASE_DE, password="falsch"
        )
    with pytest.raises(LookupError):
        erase_on_member_request(
            db_session, store, member_id="nobody", confirmation=PHRASE_DE, password=PASSWORD
        )
    db_session.rollback()
    assert db_session.get(Member, member.id) is not None


def test_the_confirmation_phrases_are_a_closed_set_of_two(api):
    """A20. A registry with one entry, or none, would make the parametrised refusal list above vacuous."""
    assert set(CONFIRMATION_PHRASES) == {"de", "en"}
    assert len(set(CONFIRMATION_PHRASES.values())) == 2
    assert all(phrase.strip() == phrase and phrase for phrase in CONFIRMATION_PHRASES.values())


def test_no_confirmation_phrase_carries_a_control_byte():
    """A91's shell hazard. The umlaut in the German sentence is a real character, checked in the bytes.

    A backspace byte or a literalised `\\u00d6` inside the phrase would give a member a sentence they
    cannot type, and the failure would look like a member who simply changed their mind.
    """
    source = SERVICE.read_bytes()
    assert "ALLE MEINE DATEN LÖSCHEN".encode("utf-8") in source
    assert not sorted({byte for byte in source if byte < 9 or 13 < byte < 32})
    assert b"\\u00d6" not in source, "an umlaut arrived as an escape sequence, not as a character"
    assert PHRASE_DE == "ALLE MEINE DATEN LÖSCHEN"
