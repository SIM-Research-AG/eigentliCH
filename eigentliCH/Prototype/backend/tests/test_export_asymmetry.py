"""R-231's export half: two routes, one format, and only one of them writes a Decision.

**The finding (A90).** R-231 asks for export and deletion to be self-service, "both producing a Decision
record of the request". `POST /api/settings/export` writes one and had no client caller;
`GET /api/export` is what the client actually used and writes nothing. So the requirement held on the path
nobody took.

**The resolution is not to make the GET write.** A GET must be safe. A browser prefetch, a retry after a
dropped connection, a proxy revalidation, a double-click on a download link — any of these repeats it, and
each repetition would append a Decision to a table that R-040 makes append-only. S-07's screen would fill
with export requests the member never made, and there would be no removing them: the whole point of
`decisions` is that it cannot be tidied. A route whose side effect cannot be undone must not be on a verb
that the web repeats on its own.

So the two stay different and the difference is deliberate. What this file holds is that they cannot drift
apart in the ways that would matter: the document is the same document, the GET still writes nothing, and
the POST writes exactly one Decision per request.

**The client has to move.** `client/app/api.js` calls the GET; a client agent is changing it to the POST
and reading `payload["export"]`. Until it does, R-231's export record is still unwritten in practice —
which is a client-side gap and is reported as one rather than closed by making a read route mutate.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from eigentlich.api.auth import router as auth_router
from eigentlich.api.remainder import get_store, router as remainder_router
from eigentlich.consent import PURPOSES
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import Decision, Goal, Position
from eigentlich.services import mutate_plan, store_item
from eigentlich.services.auth import register_with_credentials
from eigentlich.services.export import FORMAT_VERSION, export_member
from eigentlich.services.vault import VaultStore
from conftest import session_overrides

PASSWORD = "ein ziemlich langes passwort"

CONSENT_BODY = [
    {"purpose": purpose.key, "document_version": purpose.document_version}
    for purpose in PURPOSES
    if purpose.required_at_registration
]


@pytest.fixture()
def api(tmp_path, fast_kdf):
    """Both export routes on one app, sharing one throwaway database and one vault store.

    `GET /api/export` lives on `api/main.py`'s app object rather than on a router, so this fixture mounts
    the real application. `session_overrides` points every `get_session` in the package at the in-memory
    session, which is what keeps an export test off the developer's own record.
    """
    from eigentlich.api import main

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    assert ":memory:" in str(engine.url)
    create_all(engine)
    store = VaultStore(tmp_path / "vault")

    with make_session_factory(engine)() as db_session:
        original = main.VAULT_STORE
        main.VAULT_STORE = store
        overrides = session_overrides(db_session)
        overrides[get_store] = lambda: store
        main.app.dependency_overrides.update(overrides)
        try:
            with TestClient(main.app) as client:
                yield client, db_session, store
        finally:
            for key in overrides:
                main.app.dependency_overrides.pop(key, None)
            main.VAULT_STORE = original
    engine.dispose()


@pytest.fixture()
def furnished(api):
    """A member with a plan, a document, and a token. Something for an export to contain."""
    client, db_session, store = api
    member, _ = register_with_credentials(
        db_session,
        email="export@example.ch",
        password=PASSWORD,
        age_at_registration=39,
        display_name="Exportiert",
        consents=CONSENT_BODY,
    )
    db_session.commit()

    with mutate_plan(
        db_session,
        member_id=member.id,
        question="Anstellung erfassen?",
        choice="Ja",
    ) as decision:
        position = Position(
            member_id=member.id, role="income", capital_type="human", label="Anstellung"
        )
        goal = Goal(member_id=member.id, name="Wohneigentum")
        db_session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    store_item(
        db_session, store, member_id=member.id, kind="note", title="Notiz",
        source="manual", notes="etwas",
    )
    db_session.commit()

    token = client.post(
        "/api/session", json={"email": "export@example.ch", "password": PASSWORD}
    ).json()["token"]
    return client, db_session, member.id, {"Authorization": f"Bearer {token}"}


def _decision_count(db_session, member_id):
    return db_session.execute(
        select(func.count()).select_from(Decision).where(Decision.member_id == member_id)
    ).scalar()


def test_the_read_route_writes_no_decision_however_many_times_it_is_called(furnished):
    """**Deliberate, and this is what says so.** Five reads, no new Decision.

    Five rather than one, because the hazard is repetition: a prefetch or a retry is what a GET gets, and
    a Decision per repetition into an append-only table is the outcome that cannot be corrected.

    **Planted violation, and it was planted in the test rather than in `api/main.py`.** That file belongs
    to another agent's change this week and a temporary edit to it is not a temporary edit when three
    people are working. So the loop was pointed at `POST /api/settings/export` instead — a route that does
    write a Decision — and this test went red with five extra Decisions. That proves the counter can see a
    Decision-writing route, which is the property the assertion depends on; an emptiness nobody has
    watched go red is the A20 shape. Restored.
    """
    client, db_session, member_id, auth = furnished
    before = _decision_count(db_session, member_id)

    for _ in range(5):
        response = client.get("/api/export", headers=auth)
        assert response.status_code == 200, response.text

    db_session.expire_all()
    assert _decision_count(db_session, member_id) == before, (
        "GET /api/export wrote a Decision; a safe method must not append to an append-only table"
    )


def test_the_request_route_writes_exactly_one_decision_per_request(furnished):
    """R-231's record, on the route a client should call. One per request, and it is findable by id."""
    client, db_session, member_id, auth = furnished
    before = _decision_count(db_session, member_id)

    first = client.post("/api/settings/export", headers=auth, json={})
    assert first.status_code == 201, first.text
    db_session.expire_all()
    assert _decision_count(db_session, member_id) == before + 1

    recorded = db_session.get(Decision, first.json()["decision_id"])
    assert recorded is not None
    assert recorded.member_id == member_id
    assert recorded.author == "member"

    second = client.post("/api/settings/export", headers=auth, json={})
    assert second.status_code == 201
    db_session.expire_all()
    assert _decision_count(db_session, member_id) == before + 2
    assert second.json()["decision_id"] != first.json()["decision_id"]


def test_both_routes_hand_back_the_same_document(furnished):
    """One format. Two exporters would mean two formats and the second one would be unverified.

    The shapes differ by one level of nesting — the GET answers the document, the POST wraps it as
    `{member_id, decision_id, export, format}` — and a client moving across reads `payload["export"]`.
    That is the only difference, and this is what holds it to being the only one.

    `decision_id` is excluded from the comparison for a reason worth stating: the POST flushes its
    Decision before composing the export, so the file contains the record of its own request. That is
    deliberate (see `services/settings.request_export`) and it is the one place the two documents
    legitimately differ.
    """
    client, _db_session, _member_id, auth = furnished

    posted = client.post("/api/settings/export", headers=auth, json={}).json()
    fetched = client.get("/api/export", headers=auth).json()

    assert posted["format"] == fetched["format"] == FORMAT_VERSION
    # `fetched` IS the document; `posted["export"]` is the same document one level in. That is the whole
    # of the difference, and writing it out here is what a client agent needs to read.
    assert set(posted["export"]) == set(fetched), (
        "the two export paths carry different collections: "
        f"{set(posted['export']) ^ set(fetched)}"
    )
    # Every collection but `decisions`, which the POST's own Decision is now inside, and the two
    # generation stamps, which differ because the two documents were composed a moment apart.
    for key in set(fetched) - {"decisions", "generated_at", "exported_at"}:
        assert posted["export"][key] == fetched[key], f"{key} differs between the two paths"


def test_the_posted_export_contains_the_record_of_its_own_request(furnished):
    """Stated as a test because it is surprising, and because it is the reason the comparison above
    excludes one key. A file in a drawer should be able to say when and why it was made."""
    client, _db_session, _member_id, auth = furnished
    payload = client.post("/api/settings/export", headers=auth, json={}).json()
    ids = [row["id"] for row in payload["export"]["decisions"]]
    assert payload["decision_id"] in ids


def test_the_service_composes_the_document_and_neither_route_assembles_its_own(furnished):
    """R-154's `export_member` is the one composer. Asserted against the service directly, so a route
    that started adding a convenience field would be visible here rather than in a diff."""
    client, db_session, member_id, auth = furnished
    from eigentlich.api import main

    direct = export_member(db_session, main.VAULT_STORE, member_id=member_id)
    fetched = client.get("/api/export", headers=auth).json()
    assert set(direct) == set(fetched)
    assert direct["format"] == fetched["format"]
