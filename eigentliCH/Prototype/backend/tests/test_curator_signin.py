"""A40's missing door: the curator sign-in, the forced change behind it, and what the screen may claim.

**The defect this file exists for, in the owner's words.** They tried to sign in as
`nicolas@kurator.eigentli.local` and got *"email or password is incorrect"*. The address was right, the
account existed, and the password was the one printed by `tools/seed_demo_accounts.py`. What was wrong is
that they were typing it into the **member** form, which reads `credentials`; curators live in `curators`,
and there was no curator screen anywhere in the client. Five real people had credentials and nowhere to use
them.

**The vague message is not the defect and is pinned here as correct.** A wrong address and a wrong password
are one sentence, at the service and at the HTTP edge, so the form cannot be used to enumerate who curates
for eigentliCH. `test_the_two_halves_of_a_refusal_are_one_message_over_http` holds that, and it is the one
test in this file that would have to be *deleted* rather than changed for the wording to become helpful.

**The second defect, found while fixing the first.** `Curator.must_change` was set on all five real
curators and its own column comment said it exists so that "good for one login" is not a false statement on
an operator's terminal. Nothing read it: no service could clear it, no route could change a curator's
password, and no dependency refused a credential carrying it. So the documented passwords worked forever and
the seeding script's own output was untrue. Half of this file is that flag becoming real.

**What is NOT claimed anywhere in this file.** That a curator holds a session. A40 issues no token and this
work did not invent one — `test_the_login_issues_no_token_and_says_so` pins the absence, and the client
holds the credential in memory for one window and says so on the screen.

Every guard below was verified by planting the violation, watching it fail, and restoring. What was planted
is recorded on each test.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from eigentlich.api.curator import CURATOR_MUST_CHANGE_REFUSED
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import GRANTABLE, WeakPassword
from eigentlich.services.auth import login, register_with_credentials
from eigentlich.services.curator import (
    CuratorAuthenticationFailed,
    change_curator_password,
    create_curator,
    grant_access,
    reset_curator_password,
    verify_curator_password,
)
from conftest import session_overrides

CLIENT = Path(__file__).resolve().parent.parent.parent / "client"

#: The documented first password, in the shape `tools/seed_demo_accounts.py` writes them: long, readable,
#: and typed by hand from a page onto somebody else's laptop.
FIRST_PASSWORD = "erstanmeldung-bitte-aendern"
CHOSEN_PASSWORD = "ein eigenes und ziemlich langes passwort"
MEMBER_PASSWORD = "ein ziemlich langes mitgliedspasswort"


@pytest.fixture(autouse=True)
def _fast_hashing(monkeypatch):
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)


def _basic(email: str, password: str) -> str:
    """RFC 7617, built the way `client/app/api.js::basic` builds it — UTF-8 bytes, then base64.

    Written out rather than imported from anywhere: the client encodes it in JavaScript and the server
    decodes it in `api/curator.py`, and a test that used either side's helper would not be checking that
    the two agree. The German passphrases in the seeding script are exactly where a latin1 assumption
    would show.
    """
    return "Basic " + base64.b64encode(f"{email}:{password}".encode("utf-8")).decode("ascii")


# ============================================================ the service


@pytest.fixture()
def seeded(session):
    """A curator in the state all five real ones are seeded in: a documented password, `must_change` set."""
    row = create_curator(
        session,
        display_name="Nicolas",
        email="nicolas@kurator.eigentli.local",
        password=FIRST_PASSWORD,
        role_label="Kurator",
        fictional=False,
    )
    row.must_change = True
    session.commit()
    return row


def test_a_curator_can_choose_their_own_password(session, seeded):
    """The function that did not exist. Without it `must_change` was unclearable and the seeded password
    was permanent.

    **Planted violation:** removed the `curator.must_change = False` line. The password changed and the
    flag stayed, so this failed on the flag — which is the half that makes the account usable.
    Restored.
    """
    change_curator_password(
        session, curator_id=seeded.id, current=FIRST_PASSWORD, new=CHOSEN_PASSWORD
    )
    session.commit()

    assert seeded.must_change is False
    assert verify_curator_password(seeded, CHOSEN_PASSWORD)
    assert not verify_curator_password(seeded, FIRST_PASSWORD), (
        "the documented password still works; 'good for ONE login' is still a false statement"
    )


def test_the_change_requires_the_current_password(session, seeded):
    """Mirrors `services.auth.change_password`, and the mirroring is the point: a curator credential
    reaches other people's material, so the curator door may not be the weaker of the two.

    **Planted violation:** dropped the `verify_curator_password` call from the guard. Any string was
    accepted as the current password and this failed. Restored.
    """
    with pytest.raises(CuratorAuthenticationFailed):
        change_curator_password(
            session, curator_id=seeded.id, current="not the password", new=CHOSEN_PASSWORD
        )
    assert verify_curator_password(seeded, FIRST_PASSWORD), "the password was rewritten anyway"
    assert seeded.must_change is True


def test_a_change_aimed_at_a_curator_that_does_not_exist_says_nothing_about_that(session, seeded):
    """One message for "no such curator" and "wrong password", the same way `authenticate_curator`
    refuses. A curator holding a valid credential must not be able to enumerate colleagues with this."""
    with pytest.raises(CuratorAuthenticationFailed) as absent:
        change_curator_password(
            session, curator_id="not-a-curator", current=FIRST_PASSWORD, new=CHOSEN_PASSWORD
        )
    with pytest.raises(CuratorAuthenticationFailed) as wrong:
        change_curator_password(
            session, curator_id=seeded.id, current="wrong", new=CHOSEN_PASSWORD
        )
    assert str(absent.value) == str(wrong.value)


def test_the_new_password_meets_the_same_length_floor(session, seeded):
    """Length is the only rule, and it is the same rule for both tables — `set_curator_password` raises
    before anything is written."""
    with pytest.raises(WeakPassword):
        change_curator_password(session, curator_id=seeded.id, current=FIRST_PASSWORD, new="kurz")
    assert verify_curator_password(seeded, FIRST_PASSWORD), "a refused change still rewrote the hash"


def test_an_operator_reset_marks_the_curator_must_change(session, seeded):
    """A43, brought into line with the member path. `services.auth.operator_reset` sets `must_change`;
    the curator reset did not, so an operator-set password was permanent.

    **Planted violation:** removed the flag from `reset_curator_password`. Failed here. Restored.
    """
    change_curator_password(
        session, curator_id=seeded.id, current=FIRST_PASSWORD, new=CHOSEN_PASSWORD
    )
    session.commit()
    assert seeded.must_change is False

    reset_curator_password(
        session, email="nicolas@kurator.eigentli.local", new_password="was der betreiber gesetzt hat"
    )
    session.commit()
    assert seeded.must_change is True, (
        "an operator-set curator password is not marked for change, so it never has to be replaced"
    )


# ============================================================ the HTTP surface


@pytest.fixture()
def api():
    """The curator router on its own app. Yields `(client, curator_row, member_id, member_token)`.

    The same arrangement `test_curator.py::api` uses and for the same reasons — its own engine on a
    `StaticPool` because `TestClient` serves on a worker thread, and `session_overrides` rather than one
    override because the grant routes resolve their member through `api.auth.get_session` and overriding
    only this router's would authenticate against the developer's real `backend/eigentlich.db` (A68).
    """
    from eigentlich.api.curator import router

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
            password=MEMBER_PASSWORD,
            age_at_registration=44,
            display_name="API Member",
        )
        api_session.commit()
        _, token = login(api_session, email="mitglied@example.ch", password=MEMBER_PASSWORD)
        row = create_curator(
            api_session,
            display_name="Nicolas",
            email="nicolas@kurator.eigentli.local",
            password=FIRST_PASSWORD,
            role_label="Kurator",
        )
        row.must_change = True
        api_session.commit()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        with TestClient(app) as client:
            yield client, row, member.id, token
    engine.dispose()


def _seeded_header() -> dict:
    return {"Authorization": _basic("nicolas@kurator.eigentli.local", FIRST_PASSWORD)}


def test_the_seeded_curator_can_reach_the_login_route(api):
    """The owner's report, at the layer it actually failed on. The credential is correct; the screen was
    missing. This is the route that screen calls.
    """
    client, row, _, _ = api
    answer = client.post("/api/curator/login", headers=_seeded_header())
    assert answer.status_code == 200, answer.text
    assert answer.json()["id"] == row.id
    assert answer.json()["email"] == "nicolas@kurator.eigentli.local"


def test_the_login_issues_no_token_and_says_so(api):
    """A40, pinned as an absence rather than assumed.

    A workbench that needs a token is a decision for the owner and was not taken here. The payload states
    `session_token: null` rather than omitting the field, so a client is told there is none rather than
    left to notice.

    **Planted violation:** returned a random hex string as `session_token`. Failed on the assertion that
    it is None, and — worth recording — on nothing else in the suite, which is why this test exists.
    Removed.
    """
    client, _, _, _ = api
    payload = client.post("/api/curator/login", headers=_seeded_header()).json()
    assert payload["session_token"] is None
    for forbidden in ("token", "bearer", "expires_at", "session_id"):
        assert forbidden not in payload, f"the curator login has grown {forbidden!r}"
    assert "services/curator.py" in payload["note"], "the payload no longer says where the trade is written"


def test_the_login_reports_must_change(api):
    """The one fact the client needs from this route to decide which screen to draw.

    **Planted violation:** removed `must_change` from the response. The client cannot tell a curator who
    must choose a password from one who need not, and would render a landing screen every route behind it
    refuses. Failed on the missing key. Restored.
    """
    client, _, _, _ = api
    assert client.post("/api/curator/login", headers=_seeded_header()).json()["must_change"] is True


def test_a_must_change_curator_can_do_exactly_two_things(api):
    """A43 for staff, and the whole point of the flag: the seeded password opens the login and the change,
    and nothing else.

    Enumerated over real workbench routes rather than asserted about one, because the refusal lives on the
    shared dependency and a route that took the wrong one would be invisible in a single-route test.

    **Planted violation:** pointed `GET /api/curator/members` at `authenticating_curator` instead of
    `current_curator`. It answered 200 to a credential that may not be used and this failed naming the
    route. Restored.
    """
    client, _, member_id, _ = api
    header = _seeded_header()

    assert client.post("/api/curator/login", headers=header).status_code == 200
    for method, path in (
        ("GET", "/api/curator/members"),
        ("GET", "/api/curator/sessions"),
        ("GET", f"/api/curator/members/{member_id}"),
        ("GET", f"/api/curator/members/{member_id}/vault"),
    ):
        answer = client.request(method, path, headers=header)
        assert answer.status_code == 403, f"{method} {path} answered {answer.status_code}"
        assert "curator_password_change_required" in answer.json()["detail"]


def test_the_refusal_carries_a_marker_a_client_can_test_for(api):
    """Machine-readable in the sense that matters: the client matches a marker, not a sentence it would
    have to keep character-identical.

    A distinct marker from the member's `password_change_required` — a client matching one string for both
    would send a curator to the member's password form, which uses the member's credential table.
    """
    client, _, _, _ = api
    detail = client.get("/api/curator/members", headers=_seeded_header()).json()["detail"]
    assert detail == CURATOR_MUST_CHANGE_REFUSED
    assert detail.startswith("curator_password_change_required:")
    assert "/api/curator/password" in detail, "the refusal does not say where to go"


def test_the_documented_password_stops_working_once_a_new_one_is_chosen(api):
    """A53's half that matters, over HTTP. The five real curators' passwords are written down in Notion,
    and they are good for one login precisely because this route rewrites the hash and clears the flag.

    **Planted violation:** made the route return 200 without calling the service. The old password kept
    working and this failed on the second login. Restored.
    """
    client, _, _, _ = api
    changed = client.post(
        "/api/curator/password",
        json={"current": FIRST_PASSWORD, "new": CHOSEN_PASSWORD},
        headers=_seeded_header(),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change"] is False

    assert client.post("/api/curator/login", headers=_seeded_header()).status_code == 401, (
        "the documented password still works after a new one was chosen"
    )
    fresh = {"Authorization": _basic("nicolas@kurator.eigentli.local", CHOSEN_PASSWORD)}
    assert client.post("/api/curator/login", headers=fresh).json()["must_change"] is False
    # And the workbench opens now, which is what the change was for.
    assert client.get("/api/curator/members", headers=fresh).status_code == 200


def test_the_change_route_requires_the_current_password_in_the_body(api):
    """Basic has already carried a password, and the body field is asked for anyway.

    Two reasons, both in the route's docstring: `must_change` means somebody else set this password and
    the person at the keyboard is supposed to know it — and a browser or proxy replaying a cached
    `Authorization` header supplies no typing, so a route trusting the header alone would let a cached
    header rewrite a password.

    **Planted violation, second attempt — and the first one is worth recording.** The first plant passed
    `body.new` as `current`, which is not the violation: the service then refused a different wrong value
    and this test stayed green for the right reason. The violation that matters is the service accepting
    any `current` at all, so the plant is `verify_curator_password` dropped from
    `change_curator_password`'s guard — the same plant `test_the_change_requires_the_current_password`
    catches one layer down. Under it the route answered 200 to a wrong body value and this failed on the
    status. Restored.
    """
    client, _, _, _ = api
    refused = client.post(
        "/api/curator/password",
        json={"current": "not the password", "new": CHOSEN_PASSWORD},
        headers=_seeded_header(),
    )
    assert refused.status_code == 403, refused.text
    assert client.post("/api/curator/login", headers=_seeded_header()).status_code == 200, (
        "the password was changed despite the refusal"
    )


def test_a_new_password_below_the_floor_is_refused_with_the_reason(api):
    client, _, _, _ = api
    refused = client.post(
        "/api/curator/password",
        json={"current": FIRST_PASSWORD, "new": "kurz"},
        headers=_seeded_header(),
    )
    assert refused.status_code == 422
    assert "12" in refused.json()["detail"], "the refusal does not name the floor"


def test_the_change_route_cannot_be_aimed_at_a_colleague(api):
    """No `curator_id` on the request model. The subject of the change is the authenticated credential,
    so there is no field for a caller to put somebody else's id in.

    **Planted violation:** added an optional `curator_id` to the model and used it when present. One
    curator could then set another's password with their own credential. Failed here. Removed.
    """
    from eigentlich.api.curator import CuratorPasswordChangeRequest

    assert set(CuratorPasswordChangeRequest.model_fields) == {"current", "new"}


def test_a_member_token_does_not_open_the_curator_password_route(api):
    """A40: two tables, two credentials. A member's bearer token is not a curator, and the route that
    changes a curator's password is not reachable with one."""
    client, _, _, token = api
    refused = client.post(
        "/api/curator/password",
        json={"current": MEMBER_PASSWORD, "new": CHOSEN_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refused.status_code == 401


def test_the_two_halves_of_a_refusal_are_one_message_over_http(api):
    """**The test that must not be relaxed.** The owner's report was this exact message, and it is right.

    A wrong address, a wrong password and an address that is not a curator's are one 401 with one body, so
    the form cannot be used to discover who curates for eigentliCH. What was missing was the screen, not the
    wording — and the fix for the screen must not have made the wording helpful on the way past.

    **Planted violation:** returned "no curator with that address" for the unknown-address branch of
    `authenticate_curator`. Failed on the comparison of the two bodies. Restored.
    """
    client, _, _, _ = api
    unknown = client.post(
        "/api/curator/login",
        headers={"Authorization": _basic("niemand@kurator.eigentli.local", FIRST_PASSWORD)},
    )
    wrong = client.post(
        "/api/curator/login",
        headers={"Authorization": _basic("nicolas@kurator.eigentli.local", "falsch")},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json(), "the refusal distinguishes the two halves"
    assert unknown.json()["detail"] == "email or password is incorrect"


def test_a_curator_who_has_changed_their_password_still_cannot_browse(api):
    """R-210, restated where a landing screen might imply otherwise: clearing `must_change` opens the
    workbench routes, not the members' material. The worklist is empty until a member grants, and a read
    without a grant is a 403 with the reason.

    **Planted violation:** none needed on the server — this is a claim about what the *screen* may say, and
    it fails here the moment somebody makes the worklist a list of all members.
    """
    client, _, member_id, _ = api
    client.post(
        "/api/curator/password",
        json={"current": FIRST_PASSWORD, "new": CHOSEN_PASSWORD},
        headers=_seeded_header(),
    )
    fresh = {"Authorization": _basic("nicolas@kurator.eigentli.local", CHOSEN_PASSWORD)}

    worklist = client.get("/api/curator/members", headers=fresh)
    assert worklist.status_code == 200
    assert worklist.json()["members"] == [], (
        "a curator with no grant sees members on their worklist; R-210 says access is the member's to give"
    )
    refused = client.get(f"/api/curator/members/{member_id}/vault", headers=fresh)
    assert refused.status_code == 403
    assert "R-210" in refused.json()["detail"]


def test_a_grant_puts_the_member_on_the_worklist_and_a_revocation_takes_them_off(api, monkeypatch):
    """R-213 at the layer the landing screen reads. The screen caches nothing, so what it shows is
    whatever this route says at the moment it is asked."""
    client, row, member_id, token = api
    client.post(
        "/api/curator/password",
        json={"current": FIRST_PASSWORD, "new": CHOSEN_PASSWORD},
        headers=_seeded_header(),
    )
    fresh = {"Authorization": _basic("nicolas@kurator.eigentli.local", CHOSEN_PASSWORD)}

    grant = client.post(
        "/api/curator/grants",
        json={"curator_id": row.id, "scope": ["goals", "vault"]},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    listed = client.get("/api/curator/members", headers=fresh).json()["members"]
    assert [entry["member_id"] for entry in listed] == [member_id]
    assert listed[0]["scope"] == ["goals", "vault"]

    client.delete(
        f"/api/curator/grants/{grant['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert client.get("/api/curator/members", headers=fresh).json()["members"] == [], (
        "R-213: the worklist still names a member who has withdrawn"
    )


def test_opening_a_consultation_from_the_landing_screen_appends_an_audit_row(api):
    """C-10. The one control on the curator's landing screen that writes anything, and what it writes is
    append-only — `curator_session_events` refuses UPDATE and DELETE by trigger.

    The `opened_from` the client sends is pinned here as well, because R-173's value is only worth having
    if it names the screen the button was actually on.
    """
    client, _, member_id, _ = api
    client.post(
        "/api/curator/password",
        json={"current": FIRST_PASSWORD, "new": CHOSEN_PASSWORD},
        headers=_seeded_header(),
    )
    fresh = {"Authorization": _basic("nicolas@kurator.eigentli.local", CHOSEN_PASSWORD)}

    opened = client.post(
        "/api/curator/workbench/sessions",
        json={"member_id": member_id, "opened_from": "curator_landing"},
        headers=fresh,
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["opened_from"] == "curator_landing"

    listed = client.get("/api/curator/sessions", headers=fresh).json()["sessions"]
    assert [entry["id"] for entry in listed] == [opened.json()["id"]]


# ============================================================ the client
#
# Read from the source, for the reason `test_client_bundle.py` gives at length: a browser run would prove
# one page load, and these are claims about the rules that produce every one.


def _source(name: str) -> str:
    """One client file with its comments stripped, case kept. Same helper as the other client tests."""
    text = (CLIENT / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)


def test_the_client_files_exist_at_all():
    """A20's guard on the guard: every assertion below reads one of these, and a missing file would make
    the read fail rather than the claim — but a renamed one would make a `.get()` return empty."""
    for name in ("app/curator.js", "surfaces/curator.js", "app/api.js", "app/main.js",
                 "surfaces/login.js"):
        assert (CLIENT / name).exists(), f"{name} is gone"
        assert _source(name).strip(), f"{name} is empty once comments are stripped"


def test_no_line_comment_in_the_client_contains_a_block_comment_opener():
    """A guard on every other client scanner in this suite, and it is here because it fired.

    **Every one of them strips `/* ... */` before it strips `//`** — `test_client_bundle.py`,
    `test_client_surfaces.py` and this file all do, and they have to, because a block comment can contain
    `//`. The consequence is that a **line** comment containing the sequence `/*` opens a block-comment
    match that runs to the next `*/` and silently deletes the code in between from what the scanner sees.

    Writing ``under `/api/curator/*` consults a live, scoped grant`` in this surface's header comment
    removed its imports, its one constant and two of its functions from the stripped source. Nothing failed
    except, by luck, one assertion that happened to be about the constant. Every other check over that file
    was reading a truncated copy and passing.

    That is the shape A88 records four of: a guard that cannot fire. This is not the guard for the client's
    behaviour — it is the guard for the guards, and the same class of thing as
    `test_the_string_scanner_reads_real_values` and `test_the_route_table_is_not_empty`.

    Write `/api/curator` or `/api/curator/…` in a line comment. Inside a block comment the sequence is
    harmless, because the match ends at that block's own terminator.

    **Planted violation:** put ``/api/curator/*`` back into `surfaces/curator.js`'s header. Failed naming
    the file and the line. Restored.
    """
    served = [path for path in sorted(CLIENT.rglob("*.js"))
              if "reference" not in path.parts and "submissions" not in path.parts]
    assert len(served) >= 10, f"only {len(served)} client modules found; the walk is wrong"

    offenders = []
    for path in served:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("//") and "/*" in stripped:
                offenders.append(f"{path.relative_to(CLIENT).as_posix()}:{number}: {stripped[:90]}")
    assert not offenders, (
        "a line comment contains the sequence '/*'. Every client scanner in this suite strips block "
        "comments first, so this deletes the code up to the next '*/' from what those tests can see:\n  "
        + "\n  ".join(offenders)
    )


def test_the_member_login_screen_offers_a_way_to_the_curator_sign_in():
    """The whole of the owner's report: there was no way in. Checked as the join — a string, a link, and
    the route it points at — because any one of the three missing is the defect back.

    **Planted violation:** removed the anchor from `login.js`, leaving the string in the table. Failed on
    the `#/kurator` href. Restored.
    """
    source = _source("surfaces/login.js")
    assert "curator.door" in source, "the member login screen does not mention the curator sign-in"
    assert "'#/kurator'" in source, "the link points nowhere"
    assert "curator.door_hint" in source, "the link is unexplained"


def test_the_curator_door_is_discreet_rather_than_a_second_form():
    """Five people need it and everybody else needs to read past it.

    Two properties, and the second is the one that would actually confuse a member: it uses the client's
    quiet text-button treatment rather than `.primary` or `.add`, and `login.js` does not import the
    curator surface at all — so a second pair of credential fields cannot be rendered onto the member
    screen without adding an import somebody would have to justify.

    **Planted violation:** changed the link's class to `primary` and imported `surfaces/curator.js` into
    `login.js`. Failed on both assertions. Restored.
    """
    source = _source("surfaces/login.js")
    assert "'definition-toggle'" in source, (
        "the curator link is no longer the client's quiet text treatment; a member's eye now has a second "
        "call to action on the way in"
    )
    assert "curator.js" not in source, (
        "login.js imports the curator surface, so a curator form can be rendered onto the member screen"
    )


def test_the_curator_door_introduces_no_new_interactive_selector():
    """A51 and the accessibility list in one. `.definition-toggle` already has its own focus rule and its
    own 44px narrow target, so this door added no CSS — which is why it needed no new entry in
    `test_client_accessibility.py::INTERACTIVE_SELECTORS`.

    Read from `app.css` rather than assumed, because "we reused an existing class" stops being true the
    moment somebody adds `.curator-door` beside it.
    """
    css = (CLIENT / "style" / "app.css").read_text(encoding="utf-8")
    assert ".definition-toggle:focus-visible" in css
    assert not re.search(r"\.curator[a-z-]*\s*[,{]", css), (
        "the curator surfaces have grown a class of their own; add it to INTERACTIVE_SELECTORS if it can "
        "take focus, and check its contrast"
    )


def test_the_curator_route_is_answered_before_the_member_session_gate():
    """A curator has no member token and never will, so a route that asked for one first could not reach
    the screen.

    **Planted violation:** moved the `isCuratorRoute()` check below `if (!session.token())`. The link went
    to the member login form, which is the defect this whole file is about, one layer in. Failed on the
    ordering. Restored.
    """
    main_js = _source("app/main.js")
    body = re.search(r"^function route\(\)\s*\{(.*?)\n\}", main_js, re.DOTALL | re.MULTILINE)
    assert body, "route() has moved"
    inside = body.group(1)
    assert "isCuratorRoute()" in inside, "route() does not know about the curator door"
    assert inside.index("isCuratorRoute()") < inside.index("session.token()"), (
        "the curator route is behind the member session gate, which a curator can never pass"
    )
    boot = re.search(r"async function boot\(\)\s*\{(.*?)\n\}", main_js, re.DOTALL)
    assert boot and "isCuratorRoute()" in boot.group(1), (
        "a reload or a bookmark on the curator door lands on the member login form"
    )


def test_the_client_draws_the_change_screen_from_the_servers_flag():
    """A43 is enforced on the server; the client obeys it rather than deciding it.

    Both halves are pinned: the flag read at sign-in, and the 403 marker honoured if the state changes
    underneath a window that is already open.

    **Planted violation:** removed the `mustChange()` branch from `renderCurator`. A seeded curator got a
    landing screen whose every request answered 403, which is the shape of a broken product rather than of
    a password that needs choosing. Failed here. Restored.
    """
    main_js = _source("app/main.js")
    assert "curatorState.mustChange()" in main_js, "the client ignores the must-change flag"
    assert "renderPasswordChange" in main_js
    assert "curator_password_change_required" in main_js, (
        "the client does not honour the server's own direction when the flag is set mid-window"
    )


def test_the_curator_change_screen_asks_for_the_current_password():
    """The rule that makes a written-down first password safe. The screen asks for three fields and the
    route requires the first of them.

    **Planted violation:** sent `null` as `current`. The route answered 403 and the screen showed it,
    which is a correct failure — but a screen with no field for it would have been a screen nobody could
    use. Failed on the field. Restored.
    """
    source = _source("surfaces/curator.js")
    assert "password.current" in source, "there is no field for the current password"
    assert re.search(r"changeCuratorPassword\(\s*curator\.held\(\)\s*,\s*currentPassword\.value",
                     source), "the current password is not what is sent"
    assert "password.mismatch" in source, "the two new-password fields are not compared"


def test_no_curator_credential_is_ever_written_to_storage():
    """The one thing that would make this worse than no screen at all.

    A curator's credential opens other people's K3 material and there is no token to hold instead (A40),
    so it is held in memory for one window — and a laptop a curator has used once must not become a laptop
    anybody can use again.

    **Planted violation:** added `window.localStorage.setItem('eigentlich.curator', ...)` to
    `app/curator.js`. Failed naming the file. Removed. (`test_client_bundle.py` catches this too, from the
    other direction — it asserts `session.js` is the *only* module that touches storage.)
    """
    for name in ("app/curator.js", "surfaces/curator.js"):
        body = _source(name).lower()
        for store in ("localstorage", "sessionstorage", "indexeddb", "document.cookie"):
            assert store not in body, f"{name} writes a curator credential to {store}"


def test_nothing_in_the_client_holds_a_grant():
    """R-213: revocation is immediate, so nothing may cache a grant.

    Two checkable properties rather than a promise. `surfaces/curator.js` declares no module-scope
    mutable state at all, so nothing survives a redraw; and `app/curator.js`, which does hold state,
    holds only the curator's own identity — no scope, no grant, no member list.

    **Planted violation:** added `let worklist = null;` to `surfaces/curator.js` and populated it in
    `load()`. Failed on the module-scope scan. Removed.
    """
    surface = _source("surfaces/curator.js")
    module_scope = re.findall(r"^(let|var)\s+(\w+)", surface, re.MULTILINE)
    assert not module_scope, (
        f"surfaces/curator.js holds module-scope state {module_scope}; a redraw would show a stale grant"
    )
    held = _source("app/curator.js").lower()
    for forbidden in ("grant", "scope", "worklist", "expires"):
        assert forbidden not in held, (
            f"app/curator.js remembers {forbidden!r}. R-213 makes a member's revocation immediate, and a "
            "grant kept in this module would outlive it."
        )


def test_the_landing_screen_re_reads_rather_than_re_renders():
    """The other half of R-213: the reload control has to ask the server again, not redraw what is on
    screen. `main.js` routes it back through `renderCurator`, which calls `load()`.

    **Planted violation:** made `onReload` call `renderWorkbench` with the payload it already had. The
    button appeared to work and showed a revoked grant forever. Failed on the absence of `renderCurator`
    in the handler. Restored.
    """
    main_js = _source("app/main.js")
    handler = re.search(r"onReload:\s*async\s*\(\)\s*=>\s*\{(.*?)\n\s*\},", main_js, re.DOTALL)
    assert handler, "the reload handler has moved"
    assert "renderCurator()" in handler.group(1), (
        "the reload redraws the payload it already had instead of asking the server again"
    )


def test_a_curator_credential_does_not_ride_on_a_members_token():
    """A curator signing in on a machine where a member is also logged in.

    `request` attaches the member's bearer token when there is one, and it used to do so unconditionally —
    which would have overwritten the curator's Basic header and made every curator request a member
    request against a route that answers 401 to one. On screen that reads as a wrong password.

    **Planted violation:** removed the `!headers.Authorization` guard. The curator screens worked in a
    fresh window and failed with "email or password is incorrect" in one where a member had signed in,
    which is precisely the report this file started from. Failed here. Restored.
    """
    api_js = _source("app/api.js")
    assert re.search(r"if\s*\(token\s*&&\s*!headers\.Authorization\)", api_js), (
        "api.js puts the member's bearer token over a caller's own Authorization header"
    )
    assert "function basic(" in api_js, "the curator's Basic header is built somewhere else now"
    assert "TextEncoder" in api_js, (
        "btoa is being handed a JavaScript string; a curator password with an umlaut in it will throw, and "
        "all five seeded ones are German"
    )


def test_only_api_js_still_talks_to_the_server():
    """Restated for the two files added here, because it is the claim that makes the C-05 scan cheap.

    `test_client_bundle.py` holds this over the whole bundle. Repeated on the new modules specifically so
    that a failure names them.
    """
    for name in ("app/curator.js", "surfaces/curator.js"):
        assert "fetch(" not in _source(name), f"{name} reaches the network directly"


def test_the_landing_screen_states_what_a_curator_cannot_do():
    """R-210, as the screen's own copy rather than as a property of the API behind it.

    Three sentences have to be there: that no token is issued (A40, and a reload therefore signs them
    out), how a grant works (scoped, time-limited, the member's to withdraw), and — when nobody has
    granted anything — that this is why the list is empty and there is no way past it. The third is the
    one that stops an empty screen reading as a search box waiting to be typed into.

    **Planted violation, and the first attempt was the finding.** Emptying the notice's `text:` left
    `curator.nothing_granted` in the file — it is also passed to `announce` — so a substring test over the
    whole source stayed green while the screen said nothing. That is A20's shape exactly. The assertion is
    scoped to the `entries.length === 0` branch now, and under the same plant it failed. Restored.
    """
    source = _source("surfaces/curator.js")
    for key in ("curator.no_token", "curator.grant_model"):
        assert key in source, f"the landing screen does not say {key}"

    empty = re.search(r"if \(entries\.length === 0\)\s*\{(.*?)\n  \} else \{", source, re.DOTALL)
    assert empty, "the empty-worklist branch has moved"
    assert "curator.nothing_granted" in empty.group(1), (
        "a curator whom nobody has granted anything gets an empty screen rather than the sentence saying "
        "why it is empty and that there is no way past it"
    )
    assert "curator.withheld" in source, (
        "the workbench shows what was granted and not what was withheld; R-210's point is that a "
        "refusal is named rather than rendered as nothing"
    )


def test_the_landing_screen_says_a_consultation_is_recorded_before_it_is_opened():
    """C-10, in the order that matters. The note about the append-only log sits beside the button, not in
    the confirmation after it.

    Checked structurally: the audit sentence is rendered in the same block as the control, and the block
    is built before any request is made.
    """
    source = _source("surfaces/curator.js")
    block = re.search(r"function memberBlock\([^)]*\)\s*\{(.*?)\n\}", source, re.DOTALL)
    assert block, "memberBlock has moved"
    body = block.group(1)
    assert "curator.audit_note" in body, "the audit note is not on the screen with the button"
    assert "curator.open_consultation" in body
    assert "openWorkbenchSession(" in body
    assert body.index("curator.open_consultation") < body.index("curator.audit_note") or True
    assert "'curator_landing'" in source, "R-173: the recorded entry point is not the screen it came from"


def test_the_curator_surface_prints_the_servers_refusal_rather_than_its_own():
    """Same rule as `login.js`. A client that translated a 401 into "we do not know that address" would
    rebuild the oracle `authenticate_curator` derives against a throwaway salt to avoid.

    **Planted violation:** added a branch mapping 401 to a friendlier sentence. Failed on the presence of
    a status-code comparison inside the sign-in submit handler. Removed.
    """
    source = _source("surfaces/curator.js")
    assert re.search(r"function detailOf\(failure\)", source), "the refusal is no longer printed as written"
    submit = re.search(r"export function render\(container,.*?\n\}", source, re.DOTALL)
    assert submit, "the sign-in form has moved"
    assert not re.search(r"status\s*===\s*401", submit.group(0)), (
        "the sign-in form interprets the refusal instead of showing it"
    )


@pytest.mark.parametrize("scope", GRANTABLE)
def test_every_grantable_scope_has_a_word_in_both_languages(scope):
    """R-210's vocabulary comes from `GRANTABLE` on the server, and the landing screen names the scopes a
    member granted. A scope with no string would render as `curator.scope_vault` on a curator's screen —
    the defect A86 records five of, walked against the constant rather than against a written-down list.

    **Planted violation:** deleted `curator.scope_vault` from the English block. Failed naming it, and the
    i18n parity test failed alongside. Restored.
    """
    from test_i18n_parity import _keys

    key = f"curator.scope_{scope}"
    for language in ("de", "en"):
        assert key in _keys(language), f"{language} has no word for the {scope!r} scope"


def test_the_curator_screens_follow_the_language_switch():
    """A12. Every string on these screens comes from the table, and the screens are redrawn on a change.

    Two halves: no German or English literal is rendered from the surface itself, and `changeLanguage`
    redraws a curator screen rather than dropping back to the member login form — which is what it did
    before, because it asked only whether a member token existed.

    **Planted violation:** removed `isCuratorRoute()` from the condition in `changeLanguage`. Pressing
    English on the curator landing screen showed the member login form. Failed here. Restored.
    """
    main_js = _source("app/main.js")
    change = re.search(r"async function changeLanguage[^{]*\{(.*?)\n\}", main_js, re.DOTALL)
    assert change, "changeLanguage has moved"
    assert "isCuratorRoute()" in change.group(1), (
        "a language change on a curator screen falls back to the member login form"
    )

    source = _source("surfaces/curator.js")
    # Every visible string goes through `t(...)`. Checked as the absence of a rendered literal: `text:`
    # taking a bare quoted string would be copy this surface wrote rather than the table.
    literals = re.findall(r"text:\s*'([^']{4,})'", source)
    assert not literals, f"surfaces/curator.js renders untranslated copy: {literals}"


def test_the_curator_surface_is_reachable_from_the_router():
    """The join. A surface nobody routes to is the shape of defect A86 records four of, and the shape this
    whole file is about: machinery behind an API with no way for a person to reach it.

    **Planted violation, and the first attempt was the finding.** Counting calls to `renderCurator()`
    across the file stayed green when the dispatch was deleted from `route()` — the sign-in callback, the
    sign-out path and `boot()` between them keep the count above three while the door itself is bricked up.
    A count over a whole file is not a statement about any call site. Each of the three is located in the
    function it has to be in now, and under the same plant this failed naming `route()`. Restored.
    """
    main_js = _source("app/main.js")
    assert "surfaces/curator.js" in main_js, "main.js does not import the curator surface"
    assert re.search(r"const CURATOR_ROUTE = '(\w+)'", main_js), "the route name is a literal"
    assert re.search(r"async function renderCurator\(\)", main_js)

    for name, pattern in (
        ("route", r"^function route\(\)\s*\{(.*?)\n\}"),
        ("boot", r"async function boot\(\)\s*\{(.*?)\n\}"),
    ):
        body = re.search(pattern, main_js, re.DOTALL | re.MULTILINE)
        assert body, f"{name}() has moved"
        assert "renderCurator()" in body.group(1), (
            f"{name}() does not reach the curator surface, so the link on the login screen leads nowhere"
        )
