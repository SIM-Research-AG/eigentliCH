"""R-103's capture point, and the registry that made it possible to have one.

**What was wrong.** `Consent` was a versioned model with a working withdrawal since phase 0, and nothing in
the application ever wrote a row. `RegistrationRequest` had no consent field and `create_member` called
`register_with_credentials` without `consents=`, so `Consent` rows existed only in tests — which made
R-230's "consent history visible and withdrawable" an empty list for every real member and left C-05's
"sole data controller from the first intake question" with no artefact behind it. A90 found it.

**A97 split the registry into what a member is asked and what they are told.** `entscheidprotokoll` is a
notice: the member is told, no `Consent` row is written for it, and no record is kept of the telling. The
tests for that are in three groups below — the registry's own shape, the two write points refusing it, and
what R-230 shows for a row written while it *was* a consent.

**Every guard below has been watched to fail.** What was planted is recorded on each test. The absence
these tests assert — "no account exists without consent", "no row is written for a notice" — is the shape
A20, A63, A66, A68, A81, A91 and A95 were all found in, so none of them is left as an assertion nobody has
seen go red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from eigentlich import boundary, consent as registry
from eigentlich.api.auth import router as auth_router
from eigentlich.api.decisions import router as decisions_router
from eigentlich.api.remainder import get_store, router as remainder_router
from eigentlich.consent import (
    BY_KEY,
    CONSENT_PURPOSES,
    DATENBEARBEITUNG,
    ENTSCHEIDPROTOKOLL,
    KIND_CONSENT,
    KIND_NOTICE,
    NOTICE_PURPOSES,
    PURPOSES,
    Purpose,
    REGISTERED_PURPOSES,
    REQUIRED_PURPOSES,
    DuplicateConsent,
    MissingRequiredConsent,
    NotAConsent,
    StaleConsentDocument,
    UnregisteredPurpose,
    notices,
    statement,
    verify_acceptance,
)
from eigentlich.content import LANGUAGES as CONTENT_LANGUAGES
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import Consent, Credential, MINIMUM_AGE, Member
from eigentlich.services.vault import VaultStore
from conftest import session_overrides

API = Path(__file__).resolve().parent.parent / "eigentlich" / "api"

PASSWORD = "ein ziemlich langes passwort"

#: Exactly what `GET /api/consent-statement` hands a client to echo back. Derived, so a purpose added or
#: retired arrives in every body below at once.
CONSENT_BODY = [
    {"purpose": purpose.key, "document_version": purpose.document_version}
    for purpose in PURPOSES
    if purpose.required_at_registration
]


def registration_body(**overrides) -> dict:
    body = {
        "email": "neu@example.ch",
        "password": PASSWORD,
        "age_at_registration": 41,
        "display_name": "Neu",
        "consents": [dict(entry) for entry in CONSENT_BODY],
    }
    body.update(overrides)
    return body


# ============================================================ the registry itself


def test_the_purpose_set_is_closed_and_not_empty():
    """A registry with nothing in it would make every assertion below vacuous — the A20 shape."""
    assert REGISTERED_PURPOSES, "the registry is empty; nothing below is testing anything"
    assert set(REQUIRED_PURPOSES) <= set(REGISTERED_PURPOSES)
    assert REQUIRED_PURPOSES, "no purpose is required, so registration cannot refuse for want of one"
    assert set(REGISTERED_PURPOSES) == {DATENBEARBEITUNG, ENTSCHEIDPROTOKOLL}


def test_the_two_kinds_partition_the_registry_and_neither_half_is_empty():
    """A97. One vocabulary, two kinds, and both halves populated.

    Both halves matter to the tests below: an empty `NOTICE_PURPOSES` makes every A97 assertion vacuous
    (A20), and an empty `CONSENT_PURPOSES` would mean registration asks for nothing at all.
    """
    assert CONSENT_PURPOSES == (DATENBEARBEITUNG,)
    assert NOTICE_PURPOSES == (ENTSCHEIDPROTOKOLL,)
    assert set(CONSENT_PURPOSES) | set(NOTICE_PURPOSES) == set(REGISTERED_PURPOSES)
    assert not set(CONSENT_PURPOSES) & set(NOTICE_PURPOSES), "a purpose cannot be both asked and told"
    assert {purpose.kind for purpose in PURPOSES} == {KIND_CONSENT, KIND_NOTICE}


def test_registration_asks_for_the_consents_and_nothing_else():
    """A97, as the difference between the two lists. The notice is not required of the member.

    **Planted violation:** set `required_at_registration=True` on the `entscheidprotokoll` entry. The
    dataclass refused to construct at import time, so this failed along with the whole module — which is
    the guard below. Restored.
    """
    assert set(REQUIRED_PURPOSES) <= set(CONSENT_PURPOSES)
    assert not set(REQUIRED_PURPOSES) & set(NOTICE_PURPOSES)
    assert ENTSCHEIDPROTOKOLL not in REQUIRED_PURPOSES


def test_a_notice_cannot_be_marked_required_at_registration():
    """A97's one inexpressible combination. A notice a member must accept is a consent with the choice
    removed, which is exactly the misrepresentation the owner's answer ended.

    Checked at construction rather than by a test reading the registry, because every other test here
    *derives* from `required_at_registration` — flip that one field on the notice entry and they would all
    go on passing while registration demanded acceptance of something nobody may decline.
    """
    with pytest.raises(ValueError) as refused:
        Purpose(
            key="beispiel",
            kind=KIND_NOTICE,
            document_version="v1",
            required_at_registration=True,
            statement={"de": "x", "en": "x"},
            consequence={"de": "x", "en": "x"},
        )
    assert "notice" in str(refused.value)


def test_a_third_kind_is_not_expressible():
    """The vocabulary of kinds is closed for the same reason the vocabulary of purposes is: a client
    cannot be asked to guess how to render a word it has never met."""
    with pytest.raises(ValueError):
        Purpose(
            key="beispiel",
            kind="information",
            document_version="v1",
            required_at_registration=False,
            statement={"de": "x", "en": "x"},
            consequence={"de": "x", "en": "x"},
        )


def test_every_purpose_carries_a_document_version_and_it_is_distinct():
    """R-103. A `document_version` shared between two purposes cannot say which wording was agreed to."""
    versions = [purpose.document_version for purpose in PURPOSES]
    assert all(versions), "a purpose with no document version is a consent to nothing in particular"
    assert len(set(versions)) == len(versions), f"two purposes share a document version: {versions}"


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("purpose", PURPOSES, ids=lambda p: p.key)
def test_every_statement_is_written_in_both_languages(purpose, language):
    """A12. A consent form that half-speaks English is a consent form in one language."""
    assert purpose.statement[language].strip(), f"{purpose.key} has no {language} statement"
    assert purpose.consequence[language].strip(), f"{purpose.key} has no {language} consequence"


def test_the_registry_speaks_the_same_languages_as_the_content_loader():
    """`consent.py` is a leaf and restates the language tuple rather than importing `content.py`.

    Restating is the arrangement `boundary.py` also has, and the price of it is this test: two tuples that
    must agree, held by a comparison rather than by memory — the A73 and A91 defect, pre-empted.
    """
    assert registry.LANGUAGES == CONTENT_LANGUAGES
def test_no_authored_consent_string_carries_a_control_byte():
    """A91's shell hazard, checked in the bytes rather than trusted.

    Six occurrences of prose corrupted by a shell so far, twice inside comments describing it. This file
    and `consent.py` were written with the editor tools; this is what says the bytes agree.
    """
    source = (Path(__file__).resolve().parent.parent / "eigentlich" / "consent.py").read_bytes()
    offenders = sorted({byte for byte in source if byte < 9 or 13 < byte < 32})
    assert not offenders, f"consent.py carries control bytes: {offenders}"
    # The umlauts are real UTF-8 and not mojibake or an escape that got literalised.
    assert "läuft".encode("utf-8") in source
    assert "Änderung".encode("utf-8") in source
    # A97's new German sentence, so the wording written for the notice is checked in the bytes too and
    # not only the wording that predates it.
    assert "abwählen".encode("utf-8") in source
    assert b"\\u00e4" not in source, "an umlaut arrived as an escape sequence, not as a character"


def test_the_wording_is_marked_provisional():
    """D-03's arrangement. The text is honest and nobody qualified has reviewed it, and both are said."""
    assert registry.PROVISIONAL is True
    assert statement("de")["wording_is_provisional"] is True


def test_the_statement_offers_exactly_what_registration_requires():
    """One list. `echo_at_registration` is what a client posts back, and if it were assembled separately
    from `REQUIRED_PURPOSES` the form could be complete and the registration still refused."""
    for language in registry.LANGUAGES:
        payload = statement(language)
        assert payload["required_at_registration"] == list(REQUIRED_PURPOSES)
        assert [entry["purpose"] for entry in payload["echo_at_registration"]] == list(REQUIRED_PURPOSES)
        for entry in payload["echo_at_registration"]:
            assert entry["document_version"] == BY_KEY[entry["purpose"]].document_version
        # C-04. The wording is published and impersonal; the row saying this member agreed is K1.
        assert {p["data_class"] for p in payload["purposes"]} == {"K0"}


def test_the_statement_tells_the_member_the_notice_as_well_as_asking_for_the_consent():
    """A97's second half, which is the half that could quietly go missing.

    Dropping the notice from this payload would leave the code correct — no row is written for it either
    way — and the member never told the more surprising of the two facts. So the assertion is that the
    wording is *there*, in both languages, marked as a notice and not as a choice.

    **Planted violation:** filtered `purposes` down to the consents in `consent.statement`. This failed on
    the missing entry; nothing else in the suite noticed. Restored.
    """
    for language in registry.LANGUAGES:
        payload = statement(language)
        by_key = {entry["purpose"]: entry for entry in payload["purposes"]}
        assert set(by_key) == set(REGISTERED_PURPOSES), "the form does not show every published purpose"
        assert payload["notices"] == list(NOTICE_PURPOSES)
        assert payload["notices_are_not_a_choice"] is True

        notice = by_key[ENTSCHEIDPROTOKOLL]
        assert notice["kind"] == KIND_NOTICE
        assert notice["required_at_registration"] is False
        # The surprising facts, in the words a member reads: undeletable even by eigentliCH, and surviving
        # an erasure emptied rather than removed.
        assert notice["statement"].strip()
        assert notice["consequence"].strip()
        assert by_key[DATENBEARBEITUNG]["kind"] == KIND_CONSENT
        # And the notice is not in the list the client sends back.
        assert ENTSCHEIDPROTOKOLL not in [e["purpose"] for e in payload["echo_at_registration"]]


def test_the_notices_are_available_on_their_own_for_a_screen_that_is_not_the_form():
    """`notices()` is what `GET /api/settings/consents` reads, since a member who registered after A97 has
    no row for it. Same payloads, same registry, one filter — not a second copy of the wording."""
    for language in registry.LANGUAGES:
        served = notices(language)
        assert [entry["purpose"] for entry in served] == list(NOTICE_PURPOSES)
        assert all(entry["kind"] == KIND_NOTICE for entry in served)
        assert all(entry["data_class"] == "K0" for entry in served)
    with pytest.raises(ValueError):
        notices("fr")


def test_the_statement_refuses_a_language_the_interface_does_not_speak():
    with pytest.raises(ValueError):
        statement("fr")


#: The exact keys of one entry in `purposes` / `notices`. Pinned because a client renders from them and
#: A97 renamed one: `withdrawal` became `consequence`, since for a notice there is no withdrawal for it to
#: be the meaning of. A silently added or renamed key is a screen that stops showing a sentence, which is
#: how a member ends up not being told the one thing A97 exists to tell them.
PURPOSE_PAYLOAD_KEYS = {
    "purpose",
    "kind",
    "document_version",
    "required_at_registration",
    "statement",
    "consequence",
    "data_class",
}

#: The exact keys of one entry in the R-230 history. `withdrawal_means` became `consequence` here for the
#: same reason, and `kind` is new.
HISTORY_ENTRY_KEYS = {
    "id",
    "purpose",
    "kind",
    "document_version",
    "granted_at",
    "withdrawn_at",
    "withdrawable",
    "required_at_registration",
    "consequence",
}


def test_the_published_wording_payload_has_exactly_these_keys():
    """The contract, written down where a change to it has to be deliberate."""
    for language in registry.LANGUAGES:
        for entry in statement(language)["purposes"]:
            assert set(entry) == PURPOSE_PAYLOAD_KEYS
        for entry in notices(language):
            assert set(entry) == PURPOSE_PAYLOAD_KEYS


# ============================================================ verify_acceptance, the four refusals


def test_a_complete_acceptance_is_returned_in_the_shape_register_member_takes():
    accepted = verify_acceptance([dict(entry) for entry in CONSENT_BODY])
    assert accepted == CONSENT_BODY
    assert all(set(entry) == {"purpose", "document_version"} for entry in accepted)


def test_a_purpose_outside_the_registry_is_refused():
    """The whole point of closing the set. `kuratoren_zugriff` is the real example: it sat in a test
    fixture for weeks as a purpose the application had never heard of, and nothing could notice."""
    with pytest.raises(UnregisteredPurpose):
        verify_acceptance(CONSENT_BODY + [{"purpose": "kuratoren_zugriff", "document_version": "kur@2026-01"}])


def test_a_stale_document_version_is_refused_rather_than_corrected():
    """R-103. Stamping the current version onto an acceptance of older text would record that the member
    agreed to words they were never shown."""
    stale = [dict(entry) for entry in CONSENT_BODY]
    stale[0]["document_version"] = "dsg@2025-01"
    with pytest.raises(StaleConsentDocument) as refused:
        verify_acceptance(stale)
    assert refused.value.current == BY_KEY[stale[0]["purpose"]].document_version


def test_the_same_purpose_twice_is_refused_rather_than_deduplicated():
    with pytest.raises(DuplicateConsent):
        verify_acceptance([dict(CONSENT_BODY[0]), dict(CONSENT_BODY[0])])


def test_a_notice_offered_as_a_consent_is_refused_rather_than_dropped():
    """A97. A registration form still sending `entscheidprotokoll` is a form still showing a checkbox for
    something the member cannot decline.

    Refused, and refused *specifically*: not `UnregisteredPurpose`, because the purpose is registered and
    the wording is still published and still shown — what changed is that nobody is being asked. Dropping
    it silently would have been the tempting repair and the wrong one: the member would have ticked
    something with no effect, and the stale form would never be found.
    """
    with pytest.raises(NotAConsent) as refused:
        verify_acceptance(
            CONSENT_BODY + [{"purpose": ENTSCHEIDPROTOKOLL, "document_version": "ent@2026-01"}]
        )
    assert refused.value.purpose == ENTSCHEIDPROTOKOLL


def test_a_notice_alone_is_refused_as_a_notice_and_not_as_a_missing_consent():
    """The order of the two checks, which is the difference between a useful message and a confusing one.

    A body carrying only the notice is wrong twice — it names something that is not a consent, and it
    omits the one that is. The purpose-level refusal comes first, because "you sent a notice" tells the
    client what to fix and "you are missing datenbearbeitung" tells it to add a second field to a form
    that already has the wrong one.
    """
    with pytest.raises(NotAConsent):
        verify_acceptance([{"purpose": ENTSCHEIDPROTOKOLL, "document_version": "ent@2026-01"}])


@pytest.mark.parametrize("entries", [[], None, "datenbearbeitung", {}], ids=repr)
def test_nothing_that_is_not_a_complete_acceptance_gets_through(entries):
    """Empty, absent, a bare string, an object — all refused, and none of them defaults to consent."""
    with pytest.raises((MissingRequiredConsent, UnregisteredPurpose, AttributeError)):
        verify_acceptance(entries)


def test_an_acceptance_short_of_a_required_consent_names_what_is_missing():
    """The message has to name the purpose, because "consent is missing" is not something a client can act
    on. With one required consent an acceptance short of it is an empty one; the assertion is on the list
    the exception carries, so it goes on holding if a second consent is ever added."""
    with pytest.raises(MissingRequiredConsent) as refused:
        verify_acceptance([])
    assert refused.value.missing == list(REQUIRED_PURPOSES)


# ============================================================ the model's own validator


def test_the_model_refuses_an_unregistered_purpose_however_the_row_is_built(session, member):
    """R-103 at the attribute, not at the route.

    **Planted violation:** removed the `@validates("purpose")` hook from `models/member.py` and this test
    passed the row straight into the database. Restored.
    """
    with pytest.raises(UnregisteredPurpose):
        Consent(
            member_id=member.id,
            purpose="onboarding",
            document_version="v1",
            granted_at=None,
        )
    assert session.execute(select(Consent)).scalars().all() == []


def test_a_registered_purpose_still_writes(session, member):
    """The other direction, so the test above is a refusal and not a blanket."""
    from eigentlich.models import utcnow

    session.add(
        Consent(
            member_id=member.id,
            purpose=DATENBEARBEITUNG,
            document_version=BY_KEY[DATENBEARBEITUNG].document_version,
            granted_at=utcnow(),
        )
    )
    session.commit()
    assert len(session.execute(select(Consent)).scalars().all()) == 1


def test_the_validator_still_admits_a_purpose_that_is_now_a_notice(session, member):
    """A97, and the reason the closed set was **not** narrowed to the consents.

    Rows naming `entscheidprotokoll` were written on 30 August while it was a consent. They are real
    records of what a member agreed to, and R-230 has to be able to show them. A validator refusing the key
    would leave them readable — `@validates` does not fire on load — and unwritable: no re-save, no ORM
    copy, and no way to construct the fixture two tests below.

    This is also the case A93's refusal of a CHECK constraint was written for, arriving on schedule.

    **Planted violation:** narrowed the validator to `CONSENT_PURPOSES`. This failed at construction and
    so did `test_r230_still_shows_a_row_written_while_the_notice_was_a_consent`. Restored.
    """
    from eigentlich.models import utcnow

    session.add(
        Consent(
            member_id=member.id,
            purpose=ENTSCHEIDPROTOKOLL,
            document_version=BY_KEY[ENTSCHEIDPROTOKOLL].document_version,
            granted_at=utcnow(),
        )
    )
    session.commit()
    assert len(session.execute(select(Consent)).scalars().all()) == 1


# ============================================================ A97 — the two write points


def test_the_one_function_that_writes_consent_rows_refuses_a_notice(session):
    """A97's guarantee at the place it can be held once: `register_member` is the only function in the
    application that constructs a `Consent`.

    So the rule "nothing writes a `Consent` row for the notice" is one check rather than something every
    internal caller — fixtures, `tools/seed_demo_accounts.py` — has to remember. Refused before the member
    row is created, which is why the assertion is on the tables and not only on the exception.

    **Planted violation:** removed the `is_notice` check from `services/registration.register_member`. The
    row was written and this failed. Restored.
    """
    from eigentlich.services.registration import register_member

    with pytest.raises(NotAConsent):
        register_member(
            session,
            age_at_registration=41,
            display_name="Notice",
            consents=[
                dict(CONSENT_BODY[0]),
                {"purpose": ENTSCHEIDPROTOKOLL, "document_version": "ent@2026-01"},
            ],
        )
    session.rollback()
    assert session.execute(select(Consent)).scalars().all() == []
    assert session.execute(select(Member)).scalars().all() == []


# ============================================================ the capture point, over HTTP


@pytest.fixture()
def api(tmp_path, fast_kdf):
    """The registration and settings routers on their own app and their own in-memory database.

    Not `main.app`: this file registers members and reads their consent history, and a fixture that
    resolved a session against `backend/eigentlich.db` would write demonstration accounts into the
    developer's database. `session_overrides` covers every `get_session` in the api package for the same
    reason (A68).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    assert ":memory:" in str(engine.url), "this fixture must never touch a file on disk"
    create_all(engine)
    with make_session_factory(engine)() as db_session:
        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(remainder_router)
        # `GET /api/decisions` is here so the withdrawal tests below can ask a real member-data route
        # whether it still answers after a consent is withdrawn. It is the claim the consequence wording
        # now makes, and a wording test that could not reach a member route would be checking prose
        # against prose.
        app.include_router(decisions_router)
        app.dependency_overrides.update(session_overrides(db_session))
        app.dependency_overrides[get_store] = lambda: VaultStore(tmp_path / "vault")
        with TestClient(app) as client:
            yield client, db_session
    engine.dispose()


def _rows(db_session, model):
    return db_session.execute(select(model)).scalars().all()


def test_the_consent_statement_is_readable_without_a_session(api):
    """C-05. The person about to register has no token, so a form behind one is a form nobody can read."""
    client, _ = api
    response = client.get("/api/consent-statement")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["language"] == "de"
    assert payload["echo_at_registration"]
    assert all(entry["statement"] for entry in payload["purposes"])


def test_the_consent_statement_speaks_english_too(api):
    client, _ = api
    payload = client.get("/api/consent-statement", params={"language": "en"}).json()
    assert payload["language"] == "en"
    assert "eigentliCH stores and processes" in payload["purposes"][0]["statement"]


def test_the_statement_route_carries_the_notice_and_marks_it_as_one(api):
    """A97 over HTTP, because this is the payload a client actually reads.

    The registration screen has to be able to tell the two apart without a table of its own: `kind` says
    which control to draw, `notices_are_not_a_choice` says a notice gets none, and `echo_at_registration`
    is the only list that goes back.
    """
    client, _ = api
    payload = client.get("/api/consent-statement").json()
    kinds = {entry["purpose"]: entry["kind"] for entry in payload["purposes"]}
    assert kinds == {DATENBEARBEITUNG: KIND_CONSENT, ENTSCHEIDPROTOKOLL: KIND_NOTICE}
    assert payload["notices"] == [ENTSCHEIDPROTOKOLL]
    assert payload["notices_are_not_a_choice"] is True
    assert [entry["purpose"] for entry in payload["echo_at_registration"]] == [DATENBEARBEITUNG]
    assert payload["required_at_registration"] == [DATENBEARBEITUNG]
    # The wording is still provisional. A97 settled what the member is asked, not who wrote the words.
    assert payload["wording_is_provisional"] is True


def test_the_consent_statement_refuses_an_unspeakable_language(api):
    client, _ = api
    assert client.get("/api/consent-statement", params={"language": "fr"}).status_code == 422


def test_registration_writes_the_consent_rows_in_the_same_transaction(api):
    """**The fix, stated as behaviour.** R-230's history is not empty for a member who registered.

    **Planted violation:** dropped `consents=consents` from the `register_with_credentials` call in
    `api/auth.py::create_member`. The account was still created and this failed on an empty history.
    Restored.
    """
    client, db_session = api
    created = client.post("/api/members", json=registration_body())
    assert created.status_code == 201, created.text
    assert created.json()["consents_recorded"] == list(REQUIRED_PURPOSES)

    rows = _rows(db_session, Consent)
    assert sorted(row.purpose for row in rows) == sorted(REQUIRED_PURPOSES)
    assert all(row.granted_at is not None and row.withdrawn_at is None for row in rows)
    assert {row.document_version for row in rows} == {
        BY_KEY[key].document_version for key in REQUIRED_PURPOSES
    }
    # One transaction: the member, the credential and the consents, or none of them.
    assert len(_rows(db_session, Member)) == 1
    assert len(_rows(db_session, Credential)) == 1


def test_registration_writes_no_row_for_the_notice(api):
    """A97, as the absence it is. One consent asked for, one row written, and nothing at all for the
    notice — no `Consent` row, and no row of any kind recording that it was displayed.

    The second assertion is the one that matters and it is a count of every table in the schema. A97 said
    *sufficient*, so the temptation this guards against is not writing a `Consent` row for the notice —
    that would fail the first assertion — but adding a tidy little `notice_acknowledgements` table beside
    it. Nothing new may appear, which is checkable without naming what to look for.

    **Planted violation:** made `verify_acceptance` pass the notice through instead of refusing it and let
    the form send it. The purpose list went to two and this failed. Restored.
    """
    from eigentlich.models import Base

    client, db_session = api
    assert client.post("/api/members", json=registration_body()).status_code == 201

    rows = _rows(db_session, Consent)
    assert [row.purpose for row in rows] == [DATENBEARBEITUNG]
    assert ENTSCHEIDPROTOKOLL not in {row.purpose for row in rows}

    #: Every table the registration touched, so a new one holding a per-member record of the telling
    #: would show up here rather than in a review.
    written = {
        table.name
        for table in Base.metadata.sorted_tables
        if db_session.execute(select(table)).first() is not None
    }
    assert written == {"members", "credentials", "consents"}, (
        "registration wrote to a table it did not write to before A97"
    )


def test_r230_history_is_no_longer_empty_for_a_member_who_registered(api):
    """R-230 end to end: register, log in, read the history the screen reads.

    This is the assertion A90's finding was really about — the route worked all along and had nothing to
    return.
    """
    client, _ = api
    assert client.post("/api/members", json=registration_body()).status_code == 201
    token = client.post(
        "/api/session", json={"email": "neu@example.ch", "password": PASSWORD}
    ).json()["token"]

    payload = client.get(
        "/api/settings/consents", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [entry["purpose"] for entry in payload["consents"]] == list(REQUIRED_PURPOSES)
    for entry in payload["consents"]:
        assert entry["withdrawable"] is True
        assert entry["kind"] == KIND_CONSENT
        # R-230's second half is worth a screen only if it can say what follows.
        assert entry["required_at_registration"] is True
        assert entry["consequence"], f"{entry['purpose']} offers withdrawal and says nothing about it"


def test_the_settings_screen_still_tells_a_new_member_about_the_notice(api):
    """A97's other half, where it is easiest to lose. **This member has no row for the notice and never
    will**, so a payload built from `consents` alone would be a settings screen that mentions the
    processing they agreed to and never mentions the record that cannot be deleted.

    That is the more surprising of the two facts — undeletable even by eigentliCH, surviving an erasure
    emptied of name and text — so it is served here as well as at registration. It is the published K0
    wording read from the registry: no row, no table, nothing per member.

    **Planted violation:** dropped `notices` from `consent_history`. Every other test in this file and in
    `test_settings.py` passed. Restored.
    """
    client, _ = api
    assert client.post("/api/members", json=registration_body()).status_code == 201
    token = client.post(
        "/api/session", json={"email": "neu@example.ch", "password": PASSWORD}
    ).json()["token"]
    payload = client.get(
        "/api/settings/consents", headers={"Authorization": f"Bearer {token}"}
    ).json()

    assert ENTSCHEIDPROTOKOLL not in [entry["purpose"] for entry in payload["consents"]]
    told = {entry["purpose"]: entry for entry in payload["notices"]}
    assert set(told) == {ENTSCHEIDPROTOKOLL}
    assert told[ENTSCHEIDPROTOKOLL]["kind"] == KIND_NOTICE
    assert told[ENTSCHEIDPROTOKOLL]["statement"].strip()
    assert told[ENTSCHEIDPROTOKOLL]["consequence"].strip()
    assert payload["notices_are_not_a_choice"] is True


def test_the_history_speaks_the_members_language(api):
    """A12 / A26. `consequence` comes from the member's locale, not from a query parameter."""
    client, _ = api
    assert client.post(
        "/api/members", json=registration_body(locale="en-CH", email="en@example.ch")
    ).status_code == 201
    token = client.post(
        "/api/session", json={"email": "en@example.ch", "password": PASSWORD}
    ).json()["token"]
    payload = client.get(
        "/api/settings/consents", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert "A withdrawal is recorded" in payload["consents"][0]["consequence"]
    # The notice too: a member reading English must not meet the one undeletable fact in German.
    assert "This is a notice" in payload["notices"][0]["consequence"]


# ============================================================ A97 — the rows written yesterday


def _register_and_log_in(client, **overrides) -> str:
    body = registration_body(**overrides)
    assert client.post("/api/members", json=body).status_code == 201
    return client.post(
        "/api/session", json={"email": body["email"], "password": body["password"]}
    ).json()["token"]


def _plant_yesterdays_notice_consent(db_session) -> str:
    """A `Consent` row for `entscheidprotokoll`, exactly as 30 August wrote it.

    The development database and the demonstration accounts hold these. Built through the ORM rather than
    by raw SQL on purpose: that such a row *can* still be built is the property the validator test above
    asserts, and a fixture reaching for raw SQL here would hide a narrowed validator rather than fail on
    it.
    """
    from eigentlich.models import utcnow

    member = db_session.execute(select(Member)).scalars().one()
    row = Consent(
        member_id=member.id,
        purpose=ENTSCHEIDPROTOKOLL,
        document_version="ent@2026-01",
        granted_at=utcnow(),
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def test_r230_still_shows_a_row_written_while_the_notice_was_a_consent(api):
    """**What R-230 shows for a purpose that is no longer a consent.** A93 refused a CHECK constraint for
    exactly this case and here it is, one day later.

    The row stays in the history: "did they ever consent, and to what version" is the question R-230
    answers, and a member who was asked on 30 August *was* asked. What changed is what the screen says
    about it, and all three changed fields come from the registry rather than from the row:

      * `kind` is `"notice"` — the client can label it as one.
      * `withdrawable` is `false`. Leaving it true was the worst available outcome: a button offering to
        revoke a record R-040 makes undeletable, beside `required_at_registration: false`, reads as
        "optional, and you may take it back".
      * `consequence` says why there is nothing to withdraw *and* why an agreement to it is still listed.
        Not silence, which is what a `null` here would have been.

    **Planted violation:** left `withdrawable` as `row.withdrawn_at is None`. The row came back offering
    withdrawal and this failed. Restored.
    """
    client, db_session = api
    token = _register_and_log_in(client)
    _plant_yesterdays_notice_consent(db_session)

    payload = client.get(
        "/api/settings/consents", headers={"Authorization": f"Bearer {token}"}
    ).json()
    listed = {entry["purpose"]: entry for entry in payload["consents"]}
    assert set(listed) == {DATENBEARBEITUNG, ENTSCHEIDPROTOKOLL}, (
        "a consent row disappeared from the history because its purpose is no longer a consent"
    )

    historical = listed[ENTSCHEIDPROTOKOLL]
    assert set(historical) == HISTORY_ENTRY_KEYS
    assert historical["kind"] == KIND_NOTICE
    assert historical["withdrawable"] is False
    assert historical["required_at_registration"] is False
    assert historical["consequence"], "the history says nothing at all about a row it still shows"
    # The record of what happened is untouched: they agreed, on a date, to a version.
    assert historical["granted_at"]
    assert historical["document_version"] == "ent@2026-01"
    assert historical["withdrawn_at"] is None
    # And the consent beside it is unaffected.
    assert listed[DATENBEARBEITUNG]["withdrawable"] is True


def test_such_a_row_cannot_be_withdrawn(api):
    """R-230's second half, refused. 422 and not 404: the row is there and it is theirs.

    Marking `withdrawn_at` on it would record a member revoking something they cannot revoke — the
    decision record is undeletable at the storage layer — which is A97's misrepresentation written into a
    column. The refusal is `services/settings.withdraw`'s, not the route's, so a second route reaching the
    service cannot skip it.

    **Planted violation:** removed the `is_notice` check from `services/settings.withdraw`. The withdrawal
    succeeded with a 200 and `withdrawn_at` set, and this failed on both. Restored.
    """
    client, db_session = api
    token = _register_and_log_in(client)
    consent_id = _plant_yesterdays_notice_consent(db_session)

    refused = client.post(
        f"/api/settings/consents/{consent_id}/withdraw",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 422, refused.text
    assert ENTSCHEIDPROTOKOLL in refused.json()["detail"]
    assert db_session.get(Consent, consent_id).withdrawn_at is None, (
        "a notice was marked withdrawn, which records a revocation that cannot happen"
    )


def test_the_consent_beside_it_is_still_withdrawable(api):
    """So the refusal above is a refusal and not a screen with the button taken off it."""
    client, db_session = api
    token = _register_and_log_in(client)
    _plant_yesterdays_notice_consent(db_session)
    listed = client.get(
        "/api/settings/consents", headers={"Authorization": f"Bearer {token}"}
    ).json()["consents"]
    consent_id = next(e["id"] for e in listed if e["purpose"] == DATENBEARBEITUNG)

    response = client.post(
        f"/api/settings/consents/{consent_id}/withdraw",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["withdrawn_at"]


@pytest.mark.parametrize(
    "consents,why",
    [
        (None, "the field is absent"),
        ([], "an empty list"),
        (
            [{"purpose": "onboarding", "document_version": "v1"}],
            "a purpose outside the registry",
        ),
        (
            [{"purpose": DATENBEARBEITUNG, "document_version": "dsg@2025-01"}],
            "wording that is no longer the published wording",
        ),
        (
            [
                {"purpose": DATENBEARBEITUNG, "document_version": "dsg@2026-01"},
                {"purpose": DATENBEARBEITUNG, "document_version": "dsg@2026-01"},
            ],
            "the same purpose twice",
        ),
        (
            [{"purpose": ENTSCHEIDPROTOKOLL, "document_version": "ent@2026-01"}],
            "a notice offered instead of the consent",
        ),
        (
            [
                {"purpose": DATENBEARBEITUNG, "document_version": "dsg@2026-01"},
                {"purpose": ENTSCHEIDPROTOKOLL, "document_version": "ent@2026-01"},
            ],
            "yesterday's form, sending the notice as well",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "body",
)
def test_no_account_is_created_without_the_required_consents(api, consents, why):
    """**The guard.** Seven shapes of unacceptable consent, and after each one the database is unchanged.

    The last two are A97's: a form still offering the notice as a checkbox is refused with a 422 rather
    than half-honoured, and — the part worth the assertion — **no account is created for it either**. A
    client that had been sending both fields since yesterday finds out; it does not quietly register
    members with an extra tick nobody stored.

    A 422 alone would not be enough: the failure this replaces was a member row created and then found
    unusable, so the assertion is on the rows and not only on the status.

    **Planted violation:** gave `RegistrationRequest.consents` a default of `[]` and made
    `verify_acceptance` return early on an empty list — the "sensible default" shape, and the state the
    application was in before R-103's capture point existed. Re-run against A97's seven shapes: the two
    that carry no consent at all — the absent field and the empty list — came back **201 Created** with no
    row written anywhere, and both went red here. The other five still name something wrong with what was
    sent, so they are still refused for that. Restored.
    """
    client, db_session = api
    body = registration_body()
    if consents is None:
        del body["consents"]
    else:
        body["consents"] = consents

    refused = client.post("/api/members", json=body)
    assert refused.status_code == 422, f"{why}: {refused.status_code} {refused.text[:200]}"
    assert _rows(db_session, Member) == [], f"{why}: a member row survived a refused registration"
    assert _rows(db_session, Credential) == [], f"{why}: a credential survived a refused registration"
    assert _rows(db_session, Consent) == [], f"{why}: a consent row survived a refused registration"


def test_the_age_floor_still_refuses_before_any_write(api):
    """R-100 / A50, with a consent step in front of it. **The floor did not move.**

    The consent check is a pure function on the request and touches nothing, so the age floor is still the
    first thing that refuses *a write* — and it is still enforced twice, in `register_member` and by
    `ck_members_age_floor`. What this test holds is that a complete, valid consent does not buy a
    registration below the floor, and that the refusal is the floor's rather than the consent check's.

    **Planted violation, and the result is worth recording exactly.** The member and the credential were
    written first, with `consents=[]`, and `verify_acceptance` was called afterwards without a rollback.
    **This test stayed green** — the floor is held by `register_member` and by `ck_members_age_floor`, and
    the position of the consent check does not touch either, which is what A81's finding about the rollback
    beside it already established. `test_a_weak_password_leaves_no_consent_row_behind_either` stayed green
    too, because that branch rolls back.

    What did go red was `test_no_account_is_created_without_the_required_consents`, in **six of its seven**
    shapes — a member row survived every refusal. The seventh is the absent field, which pydantic refuses
    before the route body runs at all. So the ordering IS load-bearing, and for the other guard: a consent
    check that runs after the write leaves a member row and a credential behind for every unacceptable
    body, which is precisely the half-registered account `POST /api/members` exists to make impossible.
    Restored, and `api/auth.py` says which of the two properties the ordering buys.

    **The first attempt at this plant planted nothing, and that is worth writing down.** Passing
    `consents=(consents := verify_acceptance(body.consents))` in the call's argument list *looks* like the
    check moved inside the call; Python evaluates arguments before calling, so it ran exactly where it
    always had and all eight tests passed. A plant that changes nothing reads as a guard that cannot fail
    — the A95 shape, from the other direction.
    """
    client, db_session = api
    refused = client.post(
        "/api/members", json=registration_body(age_at_registration=MINIMUM_AGE - 1)
    )
    assert refused.status_code == 422
    assert str(MINIMUM_AGE) in refused.json()["detail"], (
        "a below-floor registration was refused for some other reason than the floor"
    )
    assert _rows(db_session, Member) == []
    assert _rows(db_session, Consent) == []


def test_a_weak_password_leaves_no_consent_row_behind_either(api):
    """`set_password` raises after `register_member` has flushed the member *and its consents*.

    So the route's rollback in the `WeakPassword` branch now has one more thing to keep out, and this is
    what says it does. A consent row for an account that does not exist would be a record that a person
    agreed to something as a member they never became.
    """
    client, db_session = api
    refused = client.post("/api/members", json=registration_body(password="kurz"))
    assert refused.status_code == 422
    assert _rows(db_session, Member) == []
    assert _rows(db_session, Consent) == []


# ============================================================ what a withdrawal actually does
#
# An audit on 1 September 2026 found the `datenbearbeitung` consequence describing something no code
# performs. Withdrawing wrote `withdrawn_at`, answered 200 and changed nothing else — login still
# succeeded, every member route still answered, and a new vault item could still be created — while the
# text a member read before confirming said eigentliCH "may no longer process your entries" and that "an
# account cannot continue without it".
#
# **The owner decided to soften the wording and keep the behaviour.** So these three tests hold the two
# halves against each other: the behaviour is pinned, the columns nobody gates on are pinned, and the
# sentence is pinned against the claim it used to make. If any one of them is ever changed on its own,
# one of the other two goes red.


def test_a_withdrawal_is_recorded_and_access_does_not_stop(api):
    """The behaviour the consequence wording now describes, pinned end to end.

    This is the decided state and not an oversight: `withdrawn_at` is a record, not a gate. Should
    somebody later add the gate — which is a legitimate thing for the owner to decide — this test goes red
    and the sentence in `consent.py` has to be rewritten in the same commit. That is the whole point of
    pinning it: the two must not be able to drift apart again.

    **Planted violation:** made `services/settings.withdraw` raise after marking, and separately made
    `api/auth.current_member` refuse a member whose `datenbearbeitung` consent carries a `withdrawn_at`.
    The first failed on the 200; the second failed on every call after the withdrawal, naming the route.
    Restored both.
    """
    client, db_session = api
    token = _register_and_log_in(client)
    auth = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/settings/consents", headers=auth).json()["consents"]
    consent_id = next(e["id"] for e in listed if e["purpose"] == DATENBEARBEITUNG)

    withdrawn = client.post(f"/api/settings/consents/{consent_id}/withdraw", json={}, headers=auth)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["withdrawn_at"], "the withdrawal was not recorded"
    assert db_session.get(Consent, consent_id).withdrawn_at is not None

    # The record is there — and nothing stopped. Each of these is a claim the sentence makes.
    assert client.get("/api/settings/consents", headers=auth).status_code == 200
    assert client.get("/api/decisions", headers=auth).status_code == 200
    assert client.post("/api/settings/export", json={}, headers=auth).status_code == 201
    # And the session still authenticates, which is the claim about the account continuing.
    again = client.post(
        "/api/session", json={"email": "neu@example.ch", "password": PASSWORD}
    )
    assert again.status_code == 201, "login stopped working after a consent was withdrawn"
    assert again.json()["token"], "a session was opened with no token in it"

    # The history still shows the row, now marked, and no longer offers the button.
    after = {e["purpose"]: e for e in client.get(
        "/api/settings/consents", headers=auth
    ).json()["consents"]}
    assert after[DATENBEARBEITUNG]["withdrawn_at"]
    assert after[DATENBEARBEITUNG]["withdrawable"] is False


def test_no_module_outside_the_consent_record_reads_withdrawn_at():
    """`withdrawn_at` is written and read by nothing that gates behaviour, and that is the intended state.

    Checked as a closed set of modules rather than as a search for branching keywords, because the
    interesting failure is not `if consent.withdrawn_at:` in a file that already handles consents — it is
    the column being read *somewhere else*: in `api/auth.py` to refuse a session, in `services/vault.py`
    to refuse a write, in `services/befund.py` to empty a section. A fifth module appearing here means
    somebody built the gate, and the sentence a member reads before confirming has to change with it.

    Comments and docstrings are stripped first, for the reason
    `test_only_the_registration_route_creates_an_account` gives: this very file's neighbours *discuss*
    `withdrawn_at` at length, and a scan that matched prose would match the paragraphs explaining that
    nothing reads it.

    **Planted violation:** added `if consent.withdrawn_at is not None: raise` to `api/auth.py`'s member
    lookup. Failed naming `api/auth.py`. Restored. Also planted the vacuous case — renamed the column in
    the four expected modules — and the non-emptiness assertion below failed.
    """
    package = API.parent
    expected = {
        # Writes it, and says in its docstring that marking is the whole of it.
        "services/registration.py",
        # Declares the column.
        "models/member.py",
        # Renders it into R-230's history, and derives `withdrawable` for the client.
        "services/settings.py",
        # Returns it from the withdrawal route.
        "api/remainder.py",
    }

    found = set()
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        code = path.read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', " ", code)
        code = re.sub(r"^\s*#.*$", " ", code, flags=re.MULTILINE)
        if "withdrawn_at" in code:
            found.add(path.relative_to(package).as_posix())

    assert found, "nothing reads `withdrawn_at` at all, so this test is checking nothing (A20)"
    assert found == expected, (
        "the set of modules touching `withdrawn_at` changed.\n"
        f"  unexpected: {sorted(found - expected)}\n"
        f"  gone:       {sorted(expected - found)}\n"
        "If a gate was added, the `datenbearbeitung` consequence in `consent.py` no longer describes "
        "what happens and has to be rewritten in the same commit."
    )


def test_the_consequence_does_not_claim_a_revocation_that_does_not_happen():
    """C-06's rule about stated consequences, turned on eigentliCH's own consent screen.

    The old sentence made two claims in both languages — that eigentliCH may no longer process the member's
    entries, and that an account cannot continue without the consent — and the application did neither.
    **It must not come back**, in either language, by an edit that does not also build the gate.

    The second half is the one it would be easy to forget: the correction must not overstate in the other
    direction either. A member reading this is entitled to know that their withdrawal *was* registered,
    so the text has to say so rather than reading as a shrug.

    **Planted violation:** restored the 31 August sentence in both languages. Failed on the German
    `weiterführen` claim and on the English `cannot continue`. Restored. Then planted the opposite —
    a consequence saying only that nothing happens — and the second half failed on both languages.
    """
    entry = BY_KEY[DATENBEARBEITUNG]

    withdrawn = {
        "de": ("Konto lässt sich dann nicht weiterführen", "nicht weiter bearbeiten darf"),
        "en": ("account cannot continue", "may no longer process your entries"),
    }
    for language, claims in withdrawn.items():
        text = entry.consequence[language]
        for claim in claims:
            assert claim not in text, (
                f"the {language} consequence still claims {claim!r}, and no code path performs it: "
                f"withdrawing writes `withdrawn_at` and gates nothing"
            )

    # And it does say that the withdrawal is registered — the other way to be wrong.
    recorded = {"de": "festgehalten", "en": "recorded"}
    for language, word in recorded.items():
        assert word in entry.consequence[language], (
            f"the {language} consequence does not say the withdrawal is registered, which leaves a "
            f"member unable to tell whether their withdrawal reached eigentliCH at all"
        )



# ============================================================ no second way to open an account


def test_only_the_registration_route_creates_an_account():
    """A81's rule applied to R-103: a second route that made accounts would be a second route with no
    consent, and it would be the one that got used.

    A grep, and what it buys is that adding one takes a deliberate edit to a file whose docstring says
    there is only one door.

    **Planted violation:** added a `register_with_credentials(...)` call to `api/remainder.py`. Failed
    naming `remainder.py`. Removed.
    """
    offenders = []
    for path in sorted(API.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', " ", source)
        code = re.sub(r"^\s*#.*$", " ", code, flags=re.MULTILINE)
        for marker in ("register_with_credentials", "register_member"):
            if marker in code and path.name != "auth.py":
                offenders.append(f"{path.name} creates members ({marker})")
    assert not offenders, "more than one route can open an account:\n  " + "\n  ".join(offenders)
