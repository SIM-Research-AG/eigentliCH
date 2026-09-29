"""S-14 settings, consent and data: R-230, R-231, R-232.

The three requirements pull in different directions and that is what most of this file is about. R-230
wants a consent history that outlives the consent, so withdrawal marks rather than deletes. R-231 wants
self-service deletion, and R-040 makes part of a member's material undeletable on purpose. R-232 wants a
statement about every stored category, which is the kind of statement that is true when written and wrong
one migration later — so it is derived, and a test asserts it is still derived.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from eigentlich.api.remainder import get_session, get_store, router
from eigentlich.consent import PURPOSES
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import Base, Classified, Consent, DataClass, Decision, Member, TOP_CLASS
from eigentlich.services import register_member, store_item
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.services.export import FORMAT_VERSION, export_member
from eigentlich.services.settings import (
    ConsentNotFound,
    DELETION_NOT_EXECUTED,
    ERASURE_ROUTE,
    UnspeakableLanguage,
    consent_history,
    data_class_statement,
    deletion_receipt,
    language_locale,
    request_deletion,
    request_export,
    set_language,
    withdraw,
)
from eigentlich.services.vault import VaultStore

SETTINGS_SOURCE = Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "settings.py"

#: R-103's registry, read rather than restated.
#:
#: **These used to be two hand-written pairs, one of which — `kuratoren_zugriff` — was not a purpose the
#: application had ever heard of.** `Consent.purpose` was free text with no registry until 31 August 2026,
#: which is exactly why a test fixture could name a purpose that did not exist and nothing noticed. The
#: registry is closed now and the fixture reads it, so a purpose added or retired arrives here rather than
#: being remembered.
CONSENTS = [
    {"purpose": purpose.key, "document_version": purpose.document_version}
    for purpose in PURPOSES
    if purpose.required_at_registration
]


@pytest.fixture()
def consenting_member(session):
    member = register_member(
        session, age_at_registration=41, display_name="Consenting Member", consents=CONSENTS
    )
    session.commit()
    return member


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path)


@pytest.fixture()
def api(tmp_path, fast_kdf):
    """The router on its own app, database and vault store — see test_stages.py for why not main.app.

    Authenticated. R-230's "by the member" is the bearer token now, not a `member_id` in the body.
    """
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
            email="router@example.ch",
            password="ein ziemlich langes passwort",
            age_at_registration=41,
            display_name="Router Member",
            consents=CONSENTS,
        )
        api_session.commit()
        _, token = login(
            api_session, email="router@example.ch", password="ein ziemlich langes passwort"
        )
        api_session.commit()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        app.dependency_overrides[get_store] = lambda: VaultStore(tmp_path)
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, member.id
    engine.dispose()


# ============================================================ R-230


def test_consent_history_is_visible(session, consenting_member):
    """R-230, first half. Versioned records, not a checkbox — R-103 is why this list is worth showing."""
    payload = consent_history(session, member_id=consenting_member.id)
    assert [c["purpose"] for c in payload["consents"]] == [c["purpose"] for c in CONSENTS]
    assert [c["document_version"] for c in payload["consents"]] == [
        c["document_version"] for c in CONSENTS
    ]
    assert all(c["withdrawable"] is True for c in payload["consents"])


def test_a_consent_is_withdrawable(session, consenting_member):
    """R-230, second half. By the member, without asking anyone."""
    first = consent_history(session, member_id=consenting_member.id)["consents"][0]
    withdraw(session, member_id=consenting_member.id, consent_id=first["id"])
    session.commit()

    after = consent_history(session, member_id=consenting_member.id)["consents"][0]
    assert after["withdrawn_at"] is not None
    assert after["withdrawable"] is False


def test_a_withdrawn_consent_stays_in_the_history(session, consenting_member):
    """Withdrawal marks; it does not delete.

    "Did they ever consent, and to what version" is a question that outlives the consent, and a list that
    hid withdrawn rows would answer a different and easier one.
    """
    before = consent_history(session, member_id=consenting_member.id)["consents"]
    withdraw(session, member_id=consenting_member.id, consent_id=before[0]["id"])
    session.commit()

    after = consent_history(session, member_id=consenting_member.id)
    assert len(after["consents"]) == len(before)
    assert after["withdrawal_marks_rather_than_deletes"] is True
    assert session.get(Consent, before[0]["id"]) is not None


def test_withdrawal_records_when_it_happened(session, consenting_member):
    at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    first = consent_history(session, member_id=consenting_member.id)["consents"][0]
    consent = withdraw(session, member_id=consenting_member.id, consent_id=first["id"], at=at)
    session.commit()
    assert consent.withdrawn_at == at


def test_another_members_consent_cannot_be_withdrawn(session, consenting_member):
    """An id arriving over HTTP is not proof of whose it is, and this is the worst screen to get that wrong."""
    other = register_member(session, age_at_registration=30, display_name="Other", consents=CONSENTS)
    session.commit()
    theirs = consent_history(session, member_id=other.id)["consents"][0]

    with pytest.raises(ConsentNotFound):
        withdraw(session, member_id=consenting_member.id, consent_id=theirs["id"])


def test_consent_withdrawal_writes_no_decision(session, consenting_member):
    """Deliberate, and recorded in the module docstring rather than left as an omission.

    R-231 names export and deletion as the two that produce a Decision, because those two leave no other
    trace. A `Consent` row already carries its own: the version agreed to, when, and when it was withdrawn.
    """
    first = consent_history(session, member_id=consenting_member.id)["consents"][0]
    withdraw(session, member_id=consenting_member.id, consent_id=first["id"])
    session.commit()
    decisions = session.execute(
        select(Decision).where(Decision.member_id == consenting_member.id)
    ).scalars().all()
    assert decisions == []


def test_the_api_shows_and_withdraws_consent(api):
    client, member_id = api
    listed = client.get("/api/settings/consents", params={"member_id": member_id}).json()
    consent_id = listed["consents"][0]["id"]

    response = client.post(
        f"/api/settings/consents/{consent_id}/withdraw", json={"member_id": member_id}
    )
    assert response.status_code == 200
    assert response.json()["withdrawn_at"]

    again = client.get("/api/settings/consents", params={"member_id": member_id}).json()
    assert again["consents"][0]["withdrawable"] is False


def test_the_api_404s_a_consent_that_is_not_this_members(api):
    """The pair is still checked in the service, which is what makes a 404 mean "not yours" as well as
    "not there". What changed is that the member half is the token's and cannot be typed."""
    client, _member_id = api
    response = client.post("/api/settings/consents/not_a_consent/withdraw", json={})
    assert response.status_code == 404


# ============================================================ R-231 — export


def test_the_export_request_writes_a_decision(session, store, consenting_member):
    """R-231. Self-service, and the request itself is recorded."""
    result = request_export(session, store, member_id=consenting_member.id)
    session.commit()

    decision = session.get(Decision, result["decision_id"])
    assert decision is not None
    assert decision.member_id == consenting_member.id
    assert decision.author == "member"


def test_the_export_is_r154s_and_not_a_second_one(session, store, consenting_member):
    """R-154 already built the export that round-trips and carries the format version. There is one.

    Compared field by field against `services/export.py`'s own output — a second exporter would be a
    second format, and the second one would be the one nobody verified.
    """
    result = request_export(session, store, member_id=consenting_member.id)
    session.commit()
    theirs = export_member(session, store, member_id=consenting_member.id)

    assert result["format"] == FORMAT_VERSION
    for key in ("member", "consents", "positions", "goals", "vault_items", "onboarding_answers"):
        assert result["export"][key] == theirs[key]


def test_settings_does_not_reimplement_the_export(session):
    """The reuse, asserted rather than trusted. `export_member` is imported; nothing here serialises."""
    source = SETTINGS_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "export_member" in imported
    for forbidden in ("base64", "hashlib", "content_base64", "FORMAT_VERSION ="):
        assert forbidden not in source, f"S-14 is composing its own export: found {forbidden!r}"


def test_the_export_contains_the_record_of_its_own_request(session, store, consenting_member):
    """The Decision is flushed before the export is composed, so a file in a drawer says why it exists."""
    result = request_export(session, store, member_id=consenting_member.id)
    session.commit()
    assert result["decision_id"] in [d["id"] for d in result["export"]["decisions"]]


def test_the_export_carries_the_members_vault(session, store, consenting_member):
    """"Everything the member owns" — the vault included, which is what makes R-154 worth requesting."""
    store_item(
        session, store, member_id=consenting_member.id, kind="policy", title="Hausratversicherung",
        source="upload", data=b"police",
    )
    session.commit()
    result = request_export(session, store, member_id=consenting_member.id)
    session.commit()
    assert [item["title"] for item in result["export"]["vault_items"]] == ["Hausratversicherung"]


def test_the_api_exports_and_records_it(api):
    client, member_id = api
    response = client.post("/api/settings/export", json={"member_id": member_id})
    assert response.status_code == 201
    payload = response.json()
    assert payload["format"] == FORMAT_VERSION
    assert payload["decision_id"]


def test_the_api_cannot_be_asked_to_export_for_anybody_else(api):
    """This test used to post `{"member_id": "nobody"}` and require a 404.

    **It cannot any more, and that is the improvement rather than a regression.** A11 was wired on
    31 August 2026 and `DataRequest` has no `member_id` field: the export is the bearer token's member's,
    so there is no longer a way to name a member who does not exist — or one who does. The 404 the old
    test pinned is still reachable and still tested, one layer down, by
    `test_no_decision_is_written_for_a_member_who_does_not_exist`, which calls the service directly.
    What is asserted here is the property that replaced it: a stray `member_id` in the body is inert.
    """
    client, member_id = api
    response = client.post("/api/settings/export", json={"member_id": "nobody"})
    assert response.status_code == 201
    assert response.json()["member_id"] == member_id, "a body field steered the export"


def test_no_decision_is_written_for_a_member_who_does_not_exist(session, store):
    """The half of the 404 that matters: the audit does not gain a row for a request nobody made."""
    with pytest.raises(LookupError):
        request_export(session, store, member_id="nobody")
    session.rollback()
    with pytest.raises(LookupError):
        request_deletion(session, member_id="nobody")
    session.rollback()
    assert session.execute(select(Decision)).scalars().all() == []


# ============================================================ R-231 — deletion


def test_the_deletion_request_writes_a_decision(session, consenting_member):
    """R-231. The request is self-service and it is recorded, which is the half this module owns."""
    result = request_deletion(session, member_id=consenting_member.id, reason="Kein Bedarf mehr.")
    session.commit()

    decision = session.get(Decision, result["decision_id"])
    assert decision is not None
    assert decision.author == "member"
    assert decision.reasoning == "Kein Bedarf mehr."
    assert len(decision.options_considered) >= 2


def test_the_deletion_receipt_says_it_was_not_executed(session, consenting_member):
    """The most consequential thing this application could get wrong is claiming an erasure it did not do.

    So the receipt says `executed: false` in as many words, and names why: this is step one of two, and
    the act itself waits for the confirmation `POST /api/settings/erasure` asks for. It also names where
    that step is, from `ERASURE_ROUTE` rather than from a string typed here.
    """
    result = request_deletion(session, member_id=consenting_member.id)
    session.commit()
    assert result["requested"] is True
    assert result["executed"] is False
    assert result["not_executed_reason"] == DELETION_NOT_EXECUTED
    assert result["execute_at"] == ERASURE_ROUTE


def test_the_deletion_request_deletes_nothing(session, consenting_member):
    """Stated as a test, because "not executed" is a claim about behaviour and not only about a field."""
    before = len(consent_history(session, member_id=consenting_member.id)["consents"])
    request_deletion(session, member_id=consenting_member.id)
    session.commit()
    assert session.get(Member, consenting_member.id) is not None
    assert len(consent_history(session, member_id=consenting_member.id)["consents"]) == before


def test_the_receipt_names_what_could_not_be_erased(session):
    """R-040 and C-10 as a fact the member is told rather than one they discover.

    Decisions and the curator audit refuse DELETE at the storage layer. The receipt reads `db.py`'s own
    map of those tables, so it cannot drift from the triggers it is describing.
    """
    receipt = deletion_receipt(session)
    retained = {entry["category"] for entry in receipt["retained"]}
    assert "decisions" in retained
    assert "curator_session_events" in retained
    assert all(entry["retained_because"] for entry in receipt["retained"])
    assert "decisions" not in {entry["category"] for entry in receipt["erasable"]}


def test_the_recorded_decision_is_itself_append_only(session, consenting_member):
    """The point made from the other side: the record of the deletion request cannot be tidied away."""
    from eigentlich.models import DecisionImmutable

    result = request_deletion(session, member_id=consenting_member.id)
    session.commit()
    decision = session.get(Decision, result["decision_id"])
    session.delete(decision)
    with pytest.raises(DecisionImmutable):
        session.flush()
    session.rollback()


def test_the_api_records_a_deletion_request(api):
    client, member_id = api
    response = client.post("/api/settings/deletion", json={"member_id": member_id})
    assert response.status_code == 201
    payload = response.json()
    assert payload["executed"] is False
    assert payload["decision_id"]
    assert payload["retained"]


def test_the_api_cannot_be_asked_to_record_a_deletion_for_anybody_else(api):
    """The same replacement as the export above, for the same reason — see that test's note."""
    client, member_id = api
    response = client.post("/api/settings/deletion", json={"member_id": "nobody"})
    assert response.status_code == 201
    assert response.json()["member_id"] == member_id, "a body field steered the deletion request"


# ============================================================ R-232


def _classified_tables() -> set[str]:
    """Computed here, independently of the module under test — otherwise this asserts nothing."""
    return {
        mapper.class_.__table__.name
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, Classified)
    }


def test_every_stored_category_carries_a_statement():
    """R-232. Each stored category, and the class it falls into."""
    statement = data_class_statement()
    named = {entry["category"] for entry in statement["categories"]}
    assert named == _classified_tables()
    assert all(entry["data_class"] in statement["scheme"] for entry in statement["categories"])


def test_the_statement_is_derived_and_not_hand_listed():
    """A hand-written list is correct on the day it is written and wrong one migration later.

    Asserted by scanning the three functions that produce the statement for string constants: if a
    category name appears as a literal in any of them, something is being listed rather than read.

    Scoped to those three rather than to the whole module, because `consent_history` legitimately has a
    payload key called `consents` that happens to match a table name — and a filter that fires on a
    coincidence is one somebody deletes.
    """
    tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
    derived_from = {"data_class_statement", "deletion_receipt", "_classified_models"}
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in derived_from
    ]
    assert len(functions) == len(derived_from), "the R-232 functions were renamed; this test is stale"

    literals = {
        inner.value
        for node in functions
        for inner in ast.walk(node)
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
    }
    listed = literals & _classified_tables()
    assert not listed, f"R-232: {sorted(listed)} is hand-listed in settings.py; derive it instead"


def test_a_categorys_class_is_the_models_own(session):
    """Read from `__data_class__`, so the statement and the storage cannot disagree."""
    by_category = {entry["category"]: entry for entry in data_class_statement()["categories"]}
    assert by_category[Member.__table__.name]["data_class"] == str(Member.__data_class__)
    assert by_category[Consent.__table__.name]["data_class"] == str(Consent.__data_class__)
    assert by_category[Decision.__table__.name]["data_class"] == str(Decision.__data_class__)


def test_the_top_class_is_named_and_says_it_stays_on_the_server():
    """C-04. K3 never leaves the server and never appears in a log line, and the member is told which
    categories that covers."""
    statement = data_class_statement()
    assert statement["top_class"] == str(TOP_CLASS) == "K3"
    assert statement["top_class_never_leaves_the_server"] is True

    top = [c for c in statement["categories"] if c["data_class"] == str(TOP_CLASS)]
    assert top, "no category is classified at the top class; C-04's whole point is that the vault is"
    assert all(entry["leaves_the_server"] is False for entry in top)


def test_the_statement_says_which_categories_hold_member_material():
    """"Which data class each stored CATEGORY falls into" is more useful when it also says whose."""
    by_category = {entry["category"]: entry for entry in data_class_statement()["categories"]}
    assert by_category[Member.__table__.name]["holds_member_material"] is True
    assert by_category[Consent.__table__.name]["holds_member_material"] is True


def test_a_field_may_classify_itself_above_its_row():
    """C-04's second level, reported where one exists.

    None does today, so this asserts the mechanism rather than a value: the key is present on every
    category, and the per-field lookup returns the row's class where a column declares no override.
    """
    for entry in data_class_statement()["categories"]:
        assert isinstance(entry["fields_classified_above_the_row"], dict)
    assert Member.field_data_class("display_name") is DataClass.K1


def test_the_scheme_is_the_whole_k0_to_k3_ladder():
    assert data_class_statement()["scheme"] == ["K0", "K1", "K2", "K3"]


def test_the_api_states_the_data_classes(api):
    """No member id: this is a statement about the schema, and asking for one would imply it differs."""
    client, _ = api
    payload = client.get("/api/settings/data-classes").json()
    assert payload["categories"]
    assert payload["derived_from"] == "__data_class__"


#: Everything the R-232 screen reads off this payload, named once.
#:
#: **Why this list exists.** The route derived a complete statement and, until 31 August 2026, no client
#: called it — C-04's scheme was a thing the code knew and the member could not read. Now a screen renders
#: it, and every key below is one that screen resolves; a field dropped from the payload would leave a blank
#: line beside a category rather than an error anybody notices. The route serving a 200 was never the part
#: at risk.
#:
#: Kept as a flat set rather than derived, deliberately: this is a *contract*, and a contract computed from
#: the thing it constrains constrains nothing. Adding a key here is free; removing one should require
#: arguing that no screen reads it.
R_232_TOP_LEVEL_KEYS = {
    "categories",
    "scheme",
    "top_class",
    "top_class_never_leaves_the_server",
    "derived_from",
    "link_tables_carry_no_class_of_their_own",
}

R_232_CATEGORY_KEYS = {
    "category",
    "model",
    "data_class",
    "holds_member_material",
    "fields_classified_above_the_row",
    "leaves_the_server",
}


def test_the_data_class_statement_carries_every_field_a_screen_resolves(api):
    """R-232 over HTTP, checked field by field rather than by the route answering at all.

    **Planted violation:** dropped `holds_member_material` from the dict in
    `services/settings.data_class_statement`. This test failed naming that key, and so did
    `test_the_statement_says_which_categories_hold_member_material` — recorded because it means that one
    field was already covered and the others were not. `test_the_api_states_the_data_classes`, which is the
    only other test that goes over HTTP, stayed green: "the route returns categories" is true of a payload
    missing most of its fields. Restored.
    """
    client, _ = api
    response = client.get("/api/settings/data-classes")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert R_232_TOP_LEVEL_KEYS <= set(payload), (
        f"missing from the statement: {sorted(R_232_TOP_LEVEL_KEYS - set(payload))}"
    )
    assert payload["categories"], "a statement with no categories in it is not a statement"

    for entry in payload["categories"]:
        assert R_232_CATEGORY_KEYS <= set(entry), (
            f"{entry.get('category')!r} is missing {sorted(R_232_CATEGORY_KEYS - set(entry))}"
        )
        # Every class it names is on the ladder it publishes, so a screen can look the word up.
        assert entry["data_class"] in payload["scheme"]
        assert isinstance(entry["holds_member_material"], bool)
        assert isinstance(entry["leaves_the_server"], bool)
        assert isinstance(entry["fields_classified_above_the_row"], dict)

    # The one piece of arithmetic in it, checked rather than trusted: only the top class stays.
    for entry in payload["categories"]:
        assert entry["leaves_the_server"] is (entry["data_class"] != payload["top_class"])


def test_the_statement_does_not_go_stale_when_the_schema_grows(session):
    """The claim behind derivation, exercised rather than asserted in a comment.

    A category added to the model layer appears in the statement without anyone editing this module. The
    check is that the two sets are computed from the same registry and match exactly — so a table added
    tomorrow either appears or fails this test.
    """
    assert {entry["category"] for entry in data_class_statement()["categories"]} == _classified_tables()
    assert len(_classified_tables()) > 10, "the registry looks empty; this test would pass vacuously"


# ============================================================ A12 / A26 — the language
#
# The owner, 31 August 2026, testing the application: "English vs German Version - where can I switch" and
# then "Make a switch in the browser". There was nowhere. A12 shipped both languages in phase 0 and A26
# decided the switch would be a setting on `Member.locale`; the column existed, `STRINGS.en` was complete,
# and nothing could write the column. Every seeded member was de-CH, so half the product was unreachable.


def test_the_language_is_stored_on_the_member(session, consenting_member):
    """A26. Not a session toggle: the member chooses once and finds it on the next device.

    **Planted violation:** replaced the assignment with `pass`, which is what the code did before this
    existed — the request succeeded and changed nothing. Failed on the locale. Restored.
    """
    assert consenting_member.locale == "de-CH"
    set_language(session, member_id=consenting_member.id, language="en")
    session.commit()
    session.expire_all()
    assert session.get(Member, consenting_member.id).locale == "en-CH"


def test_the_region_survives_a_language_change(session, consenting_member):
    """`de-CH` becomes `en-CH`, not `en`. The member changed the language they read; nothing about them
    changed country, and other code splits the tag on the hyphen.

    **Planted violation:** returned the bare language. Failed on `en-CH`. Restored.
    """
    assert language_locale("en", current="de-CH") == "en-CH"
    assert language_locale("en", current="de-LI") == "en-LI", "the region was replaced rather than kept"
    assert language_locale("de", current=None) == "de-CH"
    assert language_locale("de", current="de") == "de-CH"


@pytest.mark.parametrize("language", ["fr", "it", "rm", "de-CH", "", "EN"])
def test_a_language_the_interface_cannot_speak_is_refused(session, consenting_member, language):
    """`boundary.py` carries refusal texts in four languages; `i18n.js` carries strings in two.

    Storing `fr` would give a member a French refusal inside a German product, and `rm` a screen of key
    names. The check reads `content.LANGUAGES` rather than a second list, so the two cannot drift.

    **Planted violation:** `if False:` in place of the membership test. `fr` was stored and this failed.
    Restored.
    """
    with pytest.raises(UnspeakableLanguage):
        set_language(session, member_id=consenting_member.id, language=language)
    session.rollback()
    assert session.get(Member, consenting_member.id).locale == "de-CH"


def test_changing_the_language_writes_no_decision(session, consenting_member):
    """C-09 read rather than skipped: it covers a change to the member's *plan*, and `Member` is not
    `PlanMutable`. R-231 names export and deletion as the two settings actions that produce a Decision,
    and it names them because those two leave no other trace. A language leaves its trace on screen.

    The same argument this module already makes about consent withdrawal, one function along.
    """
    before = session.execute(select(Decision)).scalars().all()
    set_language(session, member_id=consenting_member.id, language="en")
    session.commit()
    assert len(session.execute(select(Decision)).scalars().all()) == len(before)


def test_no_language_is_stored_for_a_member_who_does_not_exist(session):
    with pytest.raises(LookupError):
        set_language(session, member_id="nobody", language="en")


def test_the_api_changes_the_language_and_says_what_it_stored(api):
    """The route the client calls. It reports the locale as well as the language, so a client does not have
    to know what `de` becomes."""
    client, member_id = api
    response = client.put("/api/settings/language", json={"language": "en"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["locale"] == "en-CH"
    assert payload["persisted"] is True
    assert payload["member_id"] == member_id


def test_the_api_refuses_a_language_with_no_strings(api):
    """`fr` has refusal texts on the server and no interface. 422 rather than a silent fallback to German:
    a client asking for a language it cannot render should hear so."""
    client, _ = api
    response = client.put("/api/settings/language", json={"language": "fr"})
    assert response.status_code == 422, response.text


def test_the_language_route_cannot_be_aimed_at_another_member(api):
    """A11. There is no `member_id` on `LanguageChoice`, so an extra one in the body is ignored rather than
    obeyed — and the member it writes to is the token's."""
    client, member_id = api
    response = client.put(
        "/api/settings/language", json={"language": "en", "member_id": "somebody-else"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["member_id"] == member_id


def test_expiry_of_a_grant_is_not_a_settings_concern(session, consenting_member):
    """A boundary marker, not a feature: S-14 shows consent, not curator access grants.

    R-213's revocation lives with the curator surface (phase 5). Recorded here so that a later reading of
    "consent history" does not quietly merge two different withdrawals into one screen.
    """
    payload = consent_history(session, member_id=consenting_member.id)
    assert "grants" not in payload
    assert all("expires_at" not in entry for entry in payload["consents"])
    # And the fixture's consents really are the ones being described.
    assert datetime.now(timezone.utc) - timedelta(days=1) < datetime.fromisoformat(
        payload["consents"][0]["granted_at"]
    )
