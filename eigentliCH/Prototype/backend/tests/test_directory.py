"""The curator directory: R-170, R-173, C-10, A62, and the things the list must not say.

**The centre of gravity is `test_a_session_cannot_be_opened_naming_a_party_that_is_not_a_curator`.** The
directory itself is a small piece of plumbing; the reason it exists is that C-10 says a session records the
identified curator, and until there was a list nothing could name one. So the list is checked for what it
leaves out, and the opener is checked for what it refuses.

`iterations` are lowered throughout: `create_curator` runs the real KDF, and 600,000 rounds per fixture is
correct in production and would make this file take minutes. Same fixture as `test_curator.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from eigentlich.db import create_all, make_session_factory
from eigentlich.models import CuratorSessionEvent, GRANTABLE
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.services.curator import (
    CuratorAuthenticationFailed,
    authenticate_curator,
    create_curator,
    grant_access,
    require_curator,
    revoke_curator,
)
from eigentlich.services.directory import (
    DIRECTORY_FIELDS,
    NoSuchCurator,
    list_curators,
    open_identified_session,
    resolve_curator,
)

CURATOR_PASSWORD = "eine ziemlich lange passphrase"

CLIENT = Path(__file__).resolve().parent.parent.parent / "client"


@pytest.fixture(autouse=True)
def _fast_hashing(monkeypatch):
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)


def _curator(session, name, *, email=None, role_label="Kurator", fictional=False, active=True):
    row = create_curator(
        session,
        display_name=name,
        email=email or f"{name.lower().replace(' ', '-')}@kurator.example.ch",
        password=CURATOR_PASSWORD,
        role_label=role_label,
        fictional=fictional,
    )
    row.active = active
    session.flush()
    return row


@pytest.fixture()
def staff(session):
    """Two curators and the demonstration one beside them.

    **The names here are invented, since 20 September 2026 (A160).** They used to be two of A62's five
    real curators, which was a small convenience and a quiet dependency: three of those five left
    eigentliCH, and a fixture naming a real person needs editing whenever the staff changes for reasons
    that have nothing to do with what the test asserts. Nothing in this file is about who the curators
    are — it is about the list saying only what it may and the session naming a row that exists.
    """
    people = {
        "vreni": _curator(session, "Vreni"),
        "tobias": _curator(session, "Tobias"),
        "demo": _curator(session, "Demo Kuratorin", role_label="Kuratorin", fictional=True),
    }
    session.commit()
    return people


# ============================================================ what the directory says


def test_the_directory_names_people(session, staff):
    """R-173. A named person exists before the session does, which is the whole point of this module."""
    listed = list_curators(session)
    assert [row["display_name"] for row in listed] == ["Tobias", "Vreni"], "sorted by name, not by insertion"
    assert all(row["id"] for row in listed)
    assert {row["role_label"] for row in listed} == {"Kurator"}


def test_the_directory_says_nothing_beyond_a_name_and_a_role(session, staff):
    """Not sensitive, and still not a data dump.

    Checked as an exact key set rather than by asserting a few absences: a field added to the payload
    later fails here whether or not anyone thought to forbid it by name.
    """
    for row in list_curators(session):
        assert set(row) == set(DIRECTORY_FIELDS)
    assert set(DIRECTORY_FIELDS) == {"id", "display_name", "role_label"}


def test_the_directory_leaks_no_email_no_password_state_and_no_judgement(session, staff):
    """Three separate things this may not carry, and one test so none of them can be re-added quietly."""
    listed = list_curators(session)
    joined = " ".join(f"{key}={value}" for row in listed for key, value in row.items())
    assert "@" not in joined, "a staff address is not part of 'who can I talk to'"
    for forbidden in ("password", "hash", "salt", "iterations", "must_change", "fictional", "active"):
        assert all(forbidden not in row for row in listed), forbidden


def test_the_directory_does_not_say_which_members_a_curator_serves(session, member, staff):
    """R-210 in a place it is easy to forget: a worklist is not a staff list.

    A live grant exists. The directory must read exactly the same as it did without one — otherwise the
    list of curators quietly becomes a list of who is working with whom.
    """
    before = list_curators(session)
    grant_access(session, member_id=member.id, curator_id=staff["vreni"].id, scope=list(GRANTABLE))
    session.commit()

    after = list_curators(session)
    assert after == before
    assert member.id not in str(after)


def test_the_directory_carries_no_count(session, staff):
    """R-113 / C-07. A list of people, and nothing counting them."""
    payload = {"curators": list_curators(session)}
    for forbidden in ("count", "total", "available", "n_curators", "waiting", "capacity"):
        assert forbidden not in str(payload).lower(), forbidden


def test_an_inactive_curator_is_not_offered(session, staff):
    """Someone who has left is not a conversation a member can have."""
    staff["vreni"].active = False
    session.commit()
    assert [row["display_name"] for row in list_curators(session)] == ["Tobias"]


def test_the_demonstration_curator_is_not_offered_and_the_real_ones_are(session, staff):
    """A62, and the decision this module made about it.

    The real curators are not marked `fictional`; the demonstration one is. She is left out of the
    directory because it answers "who can I talk to" and she is not an answer to that — a member who picks
    her opens a real audit row about a consultation nobody will hold. Listing her *with* a mark would be
    worse: the mark would sit on a card beside real colleagues and read as a judgement about a person.

    She is omitted, not disabled — `resolve_curator` still finds her, so the walkthrough still works.
    """
    listed = {row["display_name"] for row in list_curators(session)}
    assert "Demo Kuratorin" not in listed
    assert listed == {"Vreni", "Tobias"}
    assert resolve_curator(session, staff["demo"].id).display_name == "Demo Kuratorin"


# ============================================================ C-10: the session names a real curator


def test_a_session_records_the_identified_curator_and_the_screen(session, member, staff):
    """R-173 / C-10 together: WHO, and WHERE THEY WERE."""
    record = open_identified_session(
        session,
        member_id=member.id,
        curator_id=staff["vreni"].id,
        opened_from="know_panel:plan",
    )
    session.commit()

    assert record.curator_id == staff["vreni"].id
    assert record.opened_from == "know_panel:plan"
    events = session.query(CuratorSessionEvent).filter_by(session_id=record.id).all()
    assert [e.kind for e in events] == ["opened"]
    assert events[0].actor == staff["vreni"].id
    assert events[0].detail["opened_from"] == "know_panel:plan"


def test_the_recorded_curator_is_the_row_and_not_the_string_it_was_given(session, member, staff):
    """C-10's column reads "the identified curator". A whitespace-padded id is not an identification.

    It matches a row, so the session is opened — with the id read back out of `curators`, which is the
    difference between recording a person and recording what a caller typed.
    """
    record = open_identified_session(
        session,
        member_id=member.id,
        curator_id=f"  {staff['tobias'].id}  ",
        opened_from="know_panel:goals",
    )
    session.commit()
    assert record.curator_id == staff["tobias"].id


@pytest.mark.parametrize(
    "named",
    [None, "", "   ", "unassigned", "Unassigned", "curator", "kurator", "queue", "team", "does-not-exist"],
)
def test_a_session_cannot_be_opened_naming_a_party_that_is_not_a_curator(session, member, staff, named):
    """**C-10.** The test this module exists for.

    Every one of these is refused for the same single reason: there is no such row. Not a blocklist of
    placeholder words — that would be a list to maintain and would be defeated by spelling "unassigned"
    differently. `None` and `""` fail before the query, the rest fail at it.
    """
    with pytest.raises(NoSuchCurator) as refused:
        open_identified_session(
            session, member_id=member.id, curator_id=named, opened_from="know_panel:plan"
        )
    assert "C-10" in str(refused.value)


def test_nothing_is_written_when_the_curator_is_refused(session, member, staff):
    """A refusal that had already inserted a row would be a falsehood the rollback might not reach."""
    from eigentlich.models import CuratorSession

    with pytest.raises(NoSuchCurator):
        open_identified_session(
            session, member_id=member.id, curator_id="unassigned", opened_from="know_panel:plan"
        )
    assert session.query(CuratorSession).count() == 0
    assert session.query(CuratorSessionEvent).count() == 0


def test_an_inactive_curator_cannot_be_named_on_a_session(session, member, staff):
    """The directory stops offering them; this stops a stale id from being used anyway."""
    staff["vreni"].active = False
    session.commit()
    with pytest.raises(NoSuchCurator):
        open_identified_session(
            session, member_id=member.id, curator_id=staff["vreni"].id, opened_from="know_panel:plan"
        )


# ============================================================ A160: revoked, and still resolvable


def _revoke(session, row):
    revoke_curator(session, email=row.email, reason="No longer part of eigentliCH (A160).")
    session.commit()


def test_a_revoked_curator_is_refused_at_every_gate(session, member, staff):
    """A160. The four gates that used to ask `active` now ask `in_service`, and this is all four of them.

    Written as one test on purpose. They are four call sites of a single predicate, and a file with four
    separate tests would pass with three of them wired and the fourth forgotten — which is exactly the
    failure `Curator.in_service` exists to make impossible.
    """
    revoked = staff["vreni"]
    _revoke(session, revoked)

    with pytest.raises(CuratorAuthenticationFailed):
        authenticate_curator(session, email=revoked.email, password=CURATOR_PASSWORD)

    assert [row["display_name"] for row in list_curators(session)] == ["Tobias"]

    with pytest.raises(CuratorAuthenticationFailed):
        require_curator(session, revoked.id)

    with pytest.raises(NoSuchCurator):
        open_identified_session(
            session, member_id=member.id, curator_id=revoked.id, opened_from="know_panel:plan"
        )


def test_what_a_revoked_curator_did_is_still_readable(session, member, staff):
    """**The reason revocation is not a delete, and the only test that checks it.**

    C-10's audit answers "who did this" for a reader who was not there. A session opened while the curator
    was in service keeps naming them afterwards, and the name still resolves to a row — with a revocation
    date on it, so the reader learns both that this person did the thing and that they have since left.
    Delete the row instead and the event names a foreign key pointing at nothing: the audit still has the
    id and has lost the only thing that made it evidence.
    """
    row = staff["vreni"]
    record = open_identified_session(
        session, member_id=member.id, curator_id=row.id, opened_from="know_panel:plan"
    )
    session.commit()
    _revoke(session, row)

    event = session.query(CuratorSessionEvent).filter_by(session_id=record.id).one()
    assert event.actor == row.id
    still_there = session.get(type(row), event.actor)
    assert still_there is not None, "the audit's 'who' resolves to a row after revocation"
    assert still_there.display_name == "Vreni"
    assert still_there.revoked_at is not None
    assert still_there.revoked_reason


def test_a_revocation_carries_its_reason(session, staff):
    """Rule 5 of the cull, in the one place it can be enforced: no quiet removals."""
    for empty in ("", "   "):
        with pytest.raises(ValueError):
            revoke_curator(session, email=staff["vreni"].email, reason=empty)
    assert staff["vreni"].revoked_at is None


def test_revoking_twice_does_not_move_the_date_they_left(session, staff):
    """The date is a fact about the person, not about how many times the seeding script was run."""
    row = staff["vreni"]
    _revoke(session, row)
    first = row.revoked_at
    _revoke(session, row)
    assert row.revoked_at == first


def test_revocation_is_not_the_same_switch_as_active(session, staff):
    """`active` is a switch an operator may flip back; revocation is not, and the columns say so.

    Re-activating a revoked curator must not let them back in — otherwise the strongest of the two states
    is the one a stray `active = True` can undo.
    """
    row = staff["vreni"]
    _revoke(session, row)
    row.active = True
    session.commit()
    assert row.in_service is False
    assert [r["display_name"] for r in list_curators(session)] == ["Tobias"]


def test_resolve_refuses_a_member_id(session, member, staff):
    """A40 keeps curators out of `members`, and this is where that stops being theoretical.

    A member id is a well-formed id of the same shape. It is not a curator, and naming one on a session
    would put a member in the column that says who advised them.
    """
    with pytest.raises(NoSuchCurator):
        resolve_curator(session, member.id)


# ============================================================ the HTTP surface


@pytest.fixture()
def api(monkeypatch):
    """The directory router on its own app. Yields `(client, session, member_id)`.

    Its own engine on a `StaticPool` for the reason `test_curator.py` gives — `TestClient` serves on a
    worker thread and in-memory SQLite is per connection. Not `eigentlich.api.main.app`: this router is
    wired there by one line, and importing the real application here would open the real database file to
    prove something about a status code.

    **Authenticated for the session opener.** A11 was wired on 31 August 2026: `POST /api/curators/
    sessions` takes no `member_id`, because R-173 records which member opened the session and that is the
    bearer token's member. `GET /api/curators` stays open — it is the staff list, and this module's
    docstring records why. `session_overrides` covers `api.auth.get_session`, through which the token is
    resolved, as well as this router's own.
    """
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)

    from eigentlich.api.curators import get_session, router

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
        api_session.commit()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, api_session, member.id
    engine.dispose()


def test_the_directory_over_http_names_the_active_curators(api):
    client, session, _ = api
    _curator(session, "Nicolai")
    _curator(session, "Anouk")
    session.commit()

    response = client.get("/api/curators")
    assert response.status_code == 200
    assert [row["display_name"] for row in response.json()["curators"]] == ["Anouk", "Nicolai"]
    assert set(response.json()["curators"][0]) == set(DIRECTORY_FIELDS)


def test_an_empty_directory_is_an_answer_and_not_an_error(api):
    """R-170. The Curator button is present at all times, so it must have something truthful to render.

    A 404 or a 500 here would entitle a client to hide the button, which is the one thing it may not do.
    """
    client, _, _ = api
    response = client.get("/api/curators")
    assert response.status_code == 200
    assert response.json() == {"curators": []}


def test_the_directory_needs_no_credentials(api):
    """Deliberate: this is the staff list of a firm the reader belongs to, not a member's material.

    Nothing under `/api/curator/*` is readable without authenticating, and nothing here is a member's.
    """
    client, session, _ = api
    _curator(session, "Vreni")
    session.commit()
    assert client.get("/api/curators").status_code == 200
    assert "@" not in client.get("/api/curators").text


def test_opening_a_session_over_http_records_the_curator_and_the_screen(api):
    """R-173 / C-10 at the edge."""
    client, session, member_id = api
    vreni = _curator(session, "Vreni")
    session.commit()

    response = client.post(
        "/api/curators/sessions",
        json={"member_id": member_id, "curator_id": vreni.id, "opened_from": "know_panel:vault"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["curator_id"] == vreni.id
    assert body["opened_from"] == "know_panel:vault"
    assert body["member_id"] == member_id


@pytest.mark.parametrize("named", ["unassigned", "", "does-not-exist", "   "])
def test_over_http_a_session_refuses_a_curator_that_is_not_one(api, named):
    """C-10 at the edge. 422, and the reason is in the response rather than only in a log."""
    client, session, member_id = api
    _curator(session, "Vreni")
    session.commit()

    response = client.post(
        "/api/curators/sessions",
        json={"member_id": member_id, "curator_id": named, "opened_from": "know_panel:plan"},
    )
    assert response.status_code == 422, named


def test_over_http_a_session_without_a_curator_at_all_is_refused(api):
    """A missing field and a null are the same refusal as a wrong one: no session is opened."""
    client, session, member_id = api
    _curator(session, "Vreni")
    session.commit()

    for body in (
        {"member_id": member_id, "opened_from": "know_panel:plan"},
        {"member_id": member_id, "curator_id": None, "opened_from": "know_panel:plan"},
    ):
        assert client.post("/api/curators/sessions", json=body).status_code == 422


def test_over_http_a_session_without_an_entry_point_is_refused(api):
    """R-173. Recorded at the time or not at all — so a session with nowhere to record is not opened."""
    client, session, member_id = api
    vreni = _curator(session, "Vreni")
    session.commit()

    assert client.post(
        "/api/curators/sessions", json={"member_id": member_id, "curator_id": vreni.id}
    ).status_code == 422


def test_the_router_is_defined_here_and_only_wired_by_main():
    """The arrangement every phase router uses: its own file, one line in `main.py`."""
    source = (Path(__file__).parent.parent / "eigentlich" / "api" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/api/curators' not in source
    assert '@app.post("/api/curators' not in source


# ============================================================ the client half


def _client_source(name: str) -> str:
    return (CLIENT / name).read_text(encoding="utf-8")


def _without_comments(source: str) -> str:
    """A comment explaining why the button is never hidden must not read as hiding it."""
    return re.sub(r"^\s*//.*$", " ", re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL), flags=re.MULTILINE)


def test_the_curator_button_is_never_hidden_or_removed():
    """R-170: "carries a Curator button at ALL times", including when the directory call fails.

    Checked over the source rather than in a browser, for the reason `test_client_bundle.py` gives: a
    scan fails when someone writes the line, not when someone happens to exercise it.
    """
    source = _without_comments(_client_source("surfaces/know.js"))
    assert "const curatorButton = button(" in source, "the button is built once, at panel scope"
    assert "[curatorButton]" in source, "and appended to the panel header unconditionally"
    for forbidden in (
        "curatorButton.setAttribute('hidden'",
        "curatorButton.hidden",
        "curatorButton.remove(",
        "curatorButton.disabled = true;\n    return",
    ):
        assert forbidden not in source, f"R-170: {forbidden!r} would take the button away"


def test_the_client_never_invents_a_curator():
    """C-10 on the client side: no default, no placeholder, no 'unassigned' anywhere in the bundle."""
    for name in ("surfaces/know.js", "app/api.js", "app/i18n.js"):
        body = _without_comments(_client_source(name)).lower()
        for forbidden in ("unassigned", "unbesetzt", "'curator:", '"curator:'):
            assert forbidden not in body, f"{name} contains {forbidden!r}"


def test_the_client_calls_the_directory_and_the_strict_opener():
    """The Curator button gets its names from the API rather than from a query parameter."""
    api_js = _without_comments(_client_source("app/api.js"))
    assert "'/api/curators'" in api_js
    assert "'/api/curators/sessions'" in api_js
    know_js = _without_comments(_client_source("surfaces/know.js"))
    assert "getCurators" in know_js


@pytest.mark.parametrize(
    "key",
    ["know.curator_choose", "know.curator_loading", "know.curator_directory_error",
     "know.curator_person", "know.curator_unnamed"],
)
def test_every_new_client_string_exists_in_both_languages(key):
    """A12. `test_i18n_parity.py` proves the two blocks match; this names the strings this work added.

    Parity alone would pass if a key were missing from both. These have to be present.
    """
    source = _client_source("app/i18n.js")
    assert source.count(f"'{key}':") == 2, f"{key} must appear once in de and once in en"


def test_no_meter_or_count_language_reaches_the_chooser():
    """R-113 / C-07. Nothing near the Curator button counts anything."""
    body = _without_comments(_client_source("surfaces/know.js")).lower()
    for forbidden in ("verfügbar:", "available:", "queue", "warteschlange", "wartend"):
        assert forbidden not in body, forbidden
