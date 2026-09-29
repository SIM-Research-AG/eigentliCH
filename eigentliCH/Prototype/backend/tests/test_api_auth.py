"""A11 at the boundary: the session routes, and the guard on every member route.

**What this file is for.** Until 31 August 2026 the application had no authentication at its edge.
`services/auth.py` had been complete and tested since phase 2 and nothing HTTP-facing called it except one
dependency in `api/curator.py`; every other member route took `member_id` from the caller and believed it,
so `GET /api/positions?member_id=<any id>` returned any member's whole role grid with no token, no
password and no header. This file is the proof that it does not any more.

**Every guard here was verified by planting the violation.** Not one of these tests asserts an absence it
has never watched fail — A20, A63, A66 and A68 are four occasions in this build where a green suite was
hiding a broken guarantee, and each time the missing step was the same one. What was planted, and what
went red, is recorded against each test.

**Two of them are the ones that matter.**

  `test_a_token_for_one_member_cannot_read_another_members_data` walks every member-facing read with
  member A's token while member B holds a position, a goal, a vault item, a consent and an onboarding
  answer, and requires that B's material appears in none of them.

  `test_every_guarded_route_refuses_without_a_token` **enumerates the routes from the application's own
  route table**, not from a list in this file. R-154 lost five tables to a hand-written list and A73
  records what that cost; a route added next month is covered by this test on the day it is added, and if
  it is added without a guard the test fails rather than skipping it.
"""

from __future__ import annotations

import base64
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from eigentlich.api import auth as auth_api
from eigentlich.consent import PURPOSES
from eigentlich.models import Consent, Credential, Position, Session as SessionRow, VaultItem, utcnow
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides

API = Path(__file__).resolve().parent.parent / "eigentlich" / "api"

PASSWORD_A = "ein ziemlich langes passwort"
PASSWORD_B = "ein anderes langes passwort"

#: R-103's required consents in the shape `POST /api/members` takes, read off the registry rather than
#: written out. Every registration body below carries it, because as of 31 August 2026 a body without it
#: is a 422 and no account is created.
CONSENT_BODY = [
    {"purpose": purpose.key, "document_version": purpose.document_version}
    for purpose in PURPOSES
    if purpose.required_at_registration
]


# ============================================================ the application, on a fixture database


@pytest.fixture()
def app(api_session, tmp_path, monkeypatch, fast_kdf):
    """The **real** application, with every database dependency pointed at the in-memory fixture.

    Deliberately not a hand-assembled sub-app carrying one router. The route-table tests below are only
    worth anything if the table they read is the one the server serves, and a sub-app would let a router
    that nobody remembered to include quietly escape every assertion in this file.

    `VAULT_STORE` is redirected too: a test that wrote K3 bytes into `backend/vault_store` would leave
    them there.
    """
    from eigentlich.api import main
    from eigentlich.api import remainder
    from eigentlich.services import VaultStore

    store = VaultStore(tmp_path / "vault")
    monkeypatch.setattr(main, "VAULT_STORE", store)

    application = main.app
    overrides = session_overrides(api_session)
    overrides[remainder.get_store] = lambda: store
    application.dependency_overrides.update(overrides)
    try:
        yield application
    finally:
        for key in overrides:
            application.dependency_overrides.pop(key, None)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _register(session, *, email, password, name, age=41, locale="de-CH"):
    member, credential = register_with_credentials(
        session,
        email=email,
        password=password,
        age_at_registration=age,
        display_name=name,
        locale=locale,
    )
    session.commit()
    return member, credential


@pytest.fixture()
def member_a(api_session, fast_kdf):
    member, _ = _register(api_session, email="a@example.ch", password=PASSWORD_A, name="Mitglied A")
    return member


@pytest.fixture()
def member_b(api_session, fast_kdf):
    member, _ = _register(api_session, email="b@example.ch", password=PASSWORD_B, name="Mitglied B")
    return member


def _token(client, email, password):
    response = client.post("/api/session", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["token"]


@pytest.fixture()
def token_a(client, member_a):
    return _token(client, "a@example.ch", PASSWORD_A)


@pytest.fixture()
def token_b(client, member_b):
    return _token(client, "b@example.ch", PASSWORD_B)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================ the route table
#
# Read from the application rather than written down. FastAPI 0.141 wraps an included router in an
# `_IncludedRouter` rather than splicing its routes into `app.routes`, so a walk that does not descend
# into `original_router` sees 19 routes where there are 67 — and a test that enumerated 19 of 67 while
# claiming to enumerate all of them is precisely the shape of R-154's missing five tables.


def walk_routes(routes):
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from walk_routes(route.original_router.routes)
            continue
        if getattr(route, "methods", None) and getattr(route, "path", "").startswith("/api"):
            yield route


def api_routes(application):
    seen = []
    for route in walk_routes(application.routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            seen.append((method, route.path))
    return sorted(set(seen))


#: The routes that deliberately require no session, and nothing else may be on this list without a line in
#: `api/auth.py`'s docstring saying why. The rule those lines were drawn from: a route is open only if it
#: is incapable of returning anything about any member and takes no member-owned input — plus registration
#: and the login form, which are where a session becomes possible and so cannot require one.
OPEN_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/local-model"),
    ("GET", "/api/goal-templates"),
    # D-07 / A22. The destination phrase: one authored key, the same for everybody, and on screens that
    # exist before an account does. `api/auth.py`'s docstring carries the line.
    ("GET", "/api/destination"),
    # Item 5's Regime pane, and the first regulatory boundary made visible. Journey & Design page 3: the
    # regime is "population-level and carries no member data at all: computed once, shared by everyone",
    # and "everything on the population side can be shown to anyone, before signup". Item 5 adds that it
    # is "the product's most distinctive output at zero data cost" and that nothing exposed it to a person
    # without an intake.
    ("GET", "/api/regime"),
    ("GET", "/api/learning/exits"),
    ("GET", "/api/life-events"),
    ("GET", "/api/stages/{key}"),
    ("GET", "/api/settings/data-classes"),
    ("GET", "/api/marketplace/roles"),
    ("GET", "/api/curators"),
    ("GET", "/api/curator/grantable"),
    # R-103 / C-05. The consent form's own text, before an account exists. Authored K0 wording that names
    # no member, and a consent statement behind a session is a statement the person about to consent
    # cannot read. `api/auth.py`'s docstring carries the line.
    ("GET", "/api/consent-statement"),
    ("POST", "/api/members"),
    ("POST", "/api/session"),
}

#: Values for path parameters. Nonsense on purpose: a guarded route has to refuse before it looks at them,
#: and a 404 from a real-looking id would hide a missing guard behind a plausible answer.
PATH_VALUES = {
    "member_id": "not-a-member",
    "listing_id": "not-a-listing",
    "offer_id": "not-an-offer",
    "consent_id": "not-a-consent",
    "goal_id": "not-a-goal",
    "position_id": "not-a-position",
    "grant_id": "not-a-grant",
    "session_id": "not-a-session",
    "question_key": "not-a-question",
    "key": "not-a-key",
    "run_id": "not-a-run",
    "decision_id": "not-a-decision",
}
#
# **This map failing to know a parameter is a test failure, not a skip**, and that is why the five routes
# wired on 31 August (S-07's three and the position edit/deactivate pair) turned this suite red the moment
# they were included rather than passing quietly. `concrete()` asserts no `{` survives substitution, so an
# unknown parameter cannot leave a templated URL that then 404s before the guard runs — which would read as
# "refused" and prove nothing. A list that has to be kept current is exactly what R-154 lost five tables
# to; here the cost of forgetting is a red suite naming the route.


def test_the_path_value_map_has_no_duplicate_key():
    """A duplicate dict key is silent in Python, and two agents produced one within an hour.

    Both added `position_id` while wiring different routers, and the later literal simply won. Harmless
    here because both values were identical — but the failure mode is that the *second* entry wins and
    nobody sees a diff, which for a map that decides what a guard is tested against is worth one test.

    Read from the source rather than from the dict, because by the time the dict exists the duplicate is
    gone. That is the whole point.
    """
    import ast

    source = Path(__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "PATH_VALUES" not in targets or not isinstance(node.value, ast.Dict):
            continue
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        assert not duplicates, f"PATH_VALUES declares these keys twice: {duplicates}"
        return
    raise AssertionError("PATH_VALUES is no longer a literal dict assignment; this test needs rewriting")


def concrete(path):
    for name, value in PATH_VALUES.items():
        path = path.replace("{" + name + "}", value)
    assert "{" not in path, f"no test value for a path parameter in {path}"
    return path


def test_the_route_table_is_not_empty_and_was_walked_to_the_bottom(app):
    """Guard on the guard, and not a formality — see the note above `walk_routes`.

    A walk that stopped at `_IncludedRouter` returns 19 routes and every enumeration test below would
    have passed while covering less than a third of the surface.
    """
    routes = api_routes(app)
    assert len(routes) >= 60, f"the route walk found only {len(routes)} routes"
    for path in ("/api/positions", "/api/marketplace/listings", "/api/settings/consents",
                 "/api/learning", "/api/curator/grants", "/api/curators/sessions"):
        assert any(p == path for _, p in routes), f"the walk missed {path}; it is not descending"


@pytest.mark.parametrize(
    "method,path",
    [entry for entry in api_routes(__import__("eigentlich.api.main", fromlist=["app"]).app)],
    ids=lambda value: value if isinstance(value, str) else str(value),
)
def test_every_guarded_route_refuses_without_a_token(client, method, path):
    """**The second of the two tests that matter.** Every route the application serves, enumerated from
    the application, refuses an anonymous caller unless it is on `OPEN_ROUTES`.

    Sent with no body where a body is required, deliberately: the refusal must come from the guard and
    not from schema validation, so a 422 here is a failure. FastAPI solves dependencies before it parses
    the body, which is what makes that assertion meaningful rather than lucky.

    **Planted violation:** removed `Depends(current_member)` from `get_positions`. Failed with
    `GET /api/positions returned 200 without a token`. Restored. Repeated for `/api/vault` and
    `/api/settings/consents`.
    """
    if (method, path) in OPEN_ROUTES:
        pytest.skip("documented as open in api/auth.py")

    response = client.request(method, concrete(path))
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code} without a token, not 401"
    )


def test_the_open_list_and_the_dependency_graph_agree(app):
    """The other direction, and the one that catches a route added tomorrow.

    `OPEN_ROUTES` is a statement about intent; the dependency graph is what the server does. Comparing
    them means a new route without a guard fails here **by name** rather than by being quietly absent
    from a list — the R-154 shape, where two things that had to agree were maintained separately.

    `DELETE /api/session` is expected on neither side: it takes the raw token rather than a resolved
    member (you log out of a session, not as a member), so it carries no dependency and is not open.

    **Planted violation:** added a route with no guard. Failed with the new route named in
    `guarded in intent but not in fact`. Removed.
    """
    from eigentlich.api.auth import authenticating_member, current_member
    from eigentlich.api.curator import authenticating_curator, current_curator

    # Four doors, not three. `authenticating_curator` joined the list on 31 August 2026, when the curator
    # side grew the same must-change split the member side already had: `current_curator` is that dependency
    # plus A43's 403, so a route taking it still shows `current_curator` in its graph — but the two routes
    # that have to work *while* the flag is set (the curator login and the curator password change) take
    # only the outer one, and without it here they would read as unguarded.
    doors = {current_member, authenticating_member, current_curator, authenticating_curator}

    def dependencies(dependant):
        for sub in dependant.dependencies:
            if sub.call is not None:
                yield sub.call
            yield from dependencies(sub)

    unguarded = set()
    for route in walk_routes(app.routes):
        if doors & set(dependencies(route.dependant)):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            unguarded.add((method, route.path))

    unguarded.discard(("DELETE", "/api/session"))
    assert unguarded == OPEN_ROUTES, (
        "the open list and the routes that actually have no guard have diverged.\n"
        f"  guarded in intent but not in fact: {sorted(unguarded - OPEN_ROUTES)}\n"
        f"  listed as open but now guarded:    {sorted(OPEN_ROUTES - unguarded)}"
    )


def test_every_open_route_is_argued_for_in_the_auth_docstring():
    """A route may be open only if someone wrote down why. The docstring is the argument and this makes
    it load-bearing rather than decorative — an open route nobody explained fails here."""
    docstring = (API / "auth.py").read_text(encoding="utf-8").split('"""')[1]
    for method, path in sorted(OPEN_ROUTES):
        assert path in docstring, f"{method} {path} is open and api/auth.py does not say why"


#: Routes that legitimately name a member in their request body, with the reason.
#:
#: **A named (method, path) pair, not a path skip.** A skip on the path would also exempt any second field
#: someone adds to that model later. `test_every_intended_member_id_in_a_body_still_exists` checks each
#: entry still names a live route, so a stale exemption fails rather than quietly widening the rule.
MEMBER_ID_IN_BODY_IS_INTENDED = {
    ("POST", "/api/curator/workbench/sessions"): (
        "a curator opens a consultation FOR a member, so the member named is not the caller. "
        "services/curator.py refuses without a live, scoped grant (R-210)."
    ),
}


def test_no_guarded_route_accepts_a_member_id_from_the_caller(app):
    """A11's substantive half: the parameter is gone, not checked.

    A route that still accepted `member_id` would be one forgotten comparison away from the hole this
    change closed, and a comparison is a thing a maintainer can delete without noticing. The curator
    routes are the exception and are addressed BY member id — `/api/curator/members/{member_id}` — which
    is a different arrangement: `services/curator.py` refuses without a live, scoped grant (R-210).

    **The body-model half of this test had never checked anything.** It read `parameter.annotation` and
    asked for `model_fields`, but every module here begins `from __future__ import annotations`, so an
    annotation is the *string* `'PositionRequest'` and `hasattr(..., "model_fields")` is always False. The
    signature half worked; the half that would have caught `member_id` arriving in a request *body* was
    inert from the day it was written. Sixth guard in this codebase found unable to fail — A20, A63, A66,
    A68, A81, A88 — and found by someone probing it rather than reading it.

    Resolving the hints is the fix, and `resolved` below is the guard on the guard: if the annotations stop
    resolving, this fails loudly instead of quietly returning to checking nothing.
    """
    import inspect
    import typing

    offenders = []
    resolved = 0
    for route in walk_routes(app.routes):
        if "{member_id}" in route.path:
            continue  # a curator reading a member they hold a grant for
        parameters = inspect.signature(route.endpoint).parameters
        if "member_id" in parameters:
            offenders.append(f"{sorted(route.methods)} {route.path} takes member_id as a parameter")

        try:
            hints = typing.get_type_hints(route.endpoint)
        except Exception as unresolved:  # pragma: no cover - a hint naming something unimportable
            offenders.append(f"{route.path}: annotations do not resolve ({unresolved})")
            continue
        resolved += 1

        intended = {(method, route.path) for method in route.methods} & set(
            MEMBER_ID_IN_BODY_IS_INTENDED
        )
        for name, hint in hints.items():
            fields = getattr(hint, "model_fields", None)
            if not fields or "member_id" not in fields or intended:
                continue
            offenders.append(
                f"{sorted(route.methods)} {route.path} has member_id on {hint.__name__} "
                f"(parameter {name!r})"
            )

    assert resolved > 20, (
        f"only {resolved} endpoints had resolvable annotations, so the body-model half of this test is "
        f"checking almost nothing — which is the defect it was written to fix"
    )
    assert not offenders, "member_id still arrives from the caller: " + "; ".join(offenders)


def test_every_intended_member_id_in_a_body_still_exists(app):
    """A stale exemption is a widened rule, so each entry must still name a live route.

    Without this, deleting `POST /api/curator/workbench/sessions` would leave an exemption behind that
    silently covers whatever route later takes that path.
    """
    live = {
        (method, route.path) for route in walk_routes(app.routes) for method in route.methods
    }
    stale = sorted(pair for pair in MEMBER_ID_IN_BODY_IS_INTENDED if pair not in live)
    assert not stale, f"these exemptions name routes that no longer exist: {stale}"


# ============================================================ the test that matters


def _give_member_b_something_to_steal(api_session, member_b):
    """A position, a goal, a vault item, a consent and an onboarding answer, each with a distinctive
    string in it, so a leak is findable by searching the response text rather than by knowing the shape
    of every payload.

    **The consent's sentinel is its id, not its purpose.** It used to be `purpose="B-CONSENT-SECRET"`,
    which stopped being possible on 31 August 2026 when R-103's registry closed the set — a purpose is now
    one of two published words and cannot be unique to a member. The id is the stronger canary anyway: it
    is the field `GET /api/settings/consents` actually returns, so a leak of the row is a leak of this
    string, and it cannot be satisfied by a payload that happens to omit `purpose`.
    """
    from eigentlich.services import mutate_plan, record_answer, store_item
    from eigentlich.services.vault import VaultStore
    from eigentlich.models import Goal

    with mutate_plan(
        api_session, member_id=member_b.id, question="B?", choice="B-CHOICE-SECRET"
    ) as decision:
        position = Position(
            member_id=member_b.id,
            role="growth",
            capital_type="financial",
            label="B-POSITION-SECRET",
        )
        goal = Goal(member_id=member_b.id, name="B-GOAL-SECRET")
        api_session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)

    consent = Consent(
        member_id=member_b.id,
        purpose=CONSENT_BODY[0]["purpose"],
        document_version=CONSENT_BODY[0]["document_version"],
        granted_at=utcnow(),
    )
    api_session.add(consent)
    record_answer(api_session, member_id=member_b.id, question_key="employment_position",
                  value="B-ANSWER-SECRET")
    api_session.commit()
    return "B-POSITION-SECRET", "B-GOAL-SECRET", consent.id, "B-ANSWER-SECRET"


#: Every member-facing read, with no parameter left on any of them by which a member could be named.
MEMBER_READS = [
    "/api/positions",
    "/api/goals",
    "/api/vault",
    "/api/actions",
    "/api/export",
    "/api/export/verify",
    "/api/onboarding",
    "/api/settings/consents",
    "/api/stages",
    "/api/learning",
    "/api/capabilities",
    "/api/community/gatherings",
    "/api/marketplace/listings",
    "/api/life-events/inheritance",
]


def test_a_token_for_one_member_cannot_read_another_members_data(
    client, api_session, member_a, member_b, token_a
):
    """**The test.** A holds a valid session; B holds the data; nothing of B's reaches A.

    Every read is made twice over: once checking that A's own id comes back where the payload names one,
    and once searching the raw response text for five strings that exist only in B's rows. The second is
    the one that would survive a refactor — it does not depend on knowing which key of which payload the
    leak would appear under.

    **Every read is made twice: once plainly, and once with `?member_id=<B>` still on the query string.**
    The second pass is not redundant. The failure this change is undoing was not that nobody compared two
    ids — it was that an id from the caller was believed, and the shape a partial fix takes is an optional
    parameter that "wins if present". A plain-request-only test is green against that fix; this one is not.

    **Planted violation, twice.** (1) `Depends(current_member)` removed from `get_positions` and
    `member_id` restored as a query parameter: `GET /api/positions?member_id=<B>` returned B's grid and
    this test failed on `B-POSITION-SECRET`. (2) The dependency left in place and `member_id` re-added as
    an optional query parameter preferred when supplied — the "check it instead of removing it" shape.
    The first pass stayed green and the second caught it, which is the reason the second exists. Both
    restored.
    """
    secrets = _give_member_b_something_to_steal(api_session, member_b)

    for path in MEMBER_READS:
        for query in ({}, {"member_id": member_b.id}):
            response = client.get(path, headers=bearer(token_a), params=query)
            assert response.status_code == 200, f"{path} {query}: {response.status_code} {response.text[:200]}"
            body = response.text
            for secret in secrets:
                assert secret not in body, f"{path} {query} leaked {secret} to another member's token"
            payload = response.json()
            if isinstance(payload, dict) and payload.get("member_id"):
                assert payload["member_id"] == member_a.id, (
                    f"{path} {query} answered as {payload['member_id']}"
                )
            assert member_b.id not in body, f"{path} {query} names member B to member A's token"


def test_naming_another_member_in_a_body_does_not_move_the_write(
    client, api_session, member_a, member_b, token_a
):
    """The other half of "the parameter is gone": an extra field is ignored, not preferred.

    Pydantic drops an unknown key rather than raising, which is the behaviour that matters here — a
    client that keeps sending the old field gets its own row written, not somebody else's and not a 422.

    **Planted violation:** put `member_id` back on `PositionRequest` and used it. The position landed on
    B and this failed. Restored.
    """
    response = client.post(
        "/api/positions",
        headers=bearer(token_a),
        json={
            "member_id": member_b.id,
            "role": "growth",
            "capital_type": "financial",
            "label": "written by A",
            "question": "erfassen?",
            "choice": "ja",
        },
    )
    assert response.status_code == 201, response.text
    written = api_session.get(Position, response.json()["id"])
    assert written.member_id == member_a.id, "a member_id in the body still steered the write"


def test_a_revoked_or_expired_token_is_refused(client, api_session, member_a, token_a):
    """R-213's revocation, and `SESSION_LIFETIME`, at the edge rather than in the service.

    **Planted violation:** made `member_for_token` ignore `row.active`. Both halves failed. Restored.
    """
    assert client.get("/api/positions", headers=bearer(token_a)).status_code == 200

    row = api_session.execute(
        select(SessionRow).where(SessionRow.token_hash == SessionRow.hash_token(token_a))
    ).scalar_one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    api_session.commit()
    assert client.get("/api/positions", headers=bearer(token_a)).status_code == 401

    row.expires_at = utcnow() + timedelta(days=1)
    row.revoked_at = utcnow()
    api_session.commit()
    assert client.get("/api/positions", headers=bearer(token_a)).status_code == 401


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer ", "Basic abc", "Token abc", "bearer not-a-real-token"],
    ids=["absent", "empty", "scheme only", "scheme and space", "basic", "wrong scheme", "made up"],
)
def test_no_shape_of_authorization_header_gets_in_without_a_real_token(client, member_a, header):
    """The header is parsed in one place; these are the shapes that have historically got past one.

    `bearer` lowercase is included because the scheme is case-insensitive and the check is `.lower()` —
    a made-up token in the right case must fail for the token's sake, not the scheme's.
    """
    headers = {} if header is None else {"Authorization": header}
    assert client.get("/api/positions", headers=headers).status_code == 401


# ============================================================ the login form is not a membership oracle


def test_a_wrong_password_and_an_unknown_address_are_indistinguishable(client, member_a):
    """C-05 makes eigentliCH sole controller of who is a member, and it is not given away at a login form.

    Status, body and headers are compared as whole objects rather than field by field, so a future
    `detail` that named the failure would fail here even if somebody remembered to keep the status codes
    equal.

    **Planted violation:** returned 404 with `no such account` on the missing-credential path. Failed on
    the status comparison. Restored.
    """
    wrong_password = client.post(
        "/api/session", json={"email": "a@example.ch", "password": "definitely not the password"}
    )
    no_account = client.post(
        "/api/session", json={"email": "nobody@example.ch", "password": "definitely not the password"}
    )

    assert wrong_password.status_code == no_account.status_code == 401
    assert wrong_password.json() == no_account.json()
    assert wrong_password.json()["detail"] == auth_api.LOGIN_REFUSED
    assert wrong_password.headers.get("www-authenticate") == no_account.headers.get("www-authenticate")


def test_both_halves_of_a_failed_login_derive_a_key(client, member_a, monkeypatch):
    """The timing half of the same promise, asserted as work done rather than measured with a stopwatch.

    A wall-clock test would be flaky on a shared machine and would say nothing about *why* the two are
    alike. What makes them alike is that `services.auth.login` runs a PBKDF2 derivation on the
    missing-account path too, against a throwaway salt — so counting derivations is the property, and a
    count of 0 on one path is the oracle re-opening.

    **Planted violation:** deleted the throwaway `Credential.derive` from the `credential is None` branch.
    Failed with `0 derivations for an unknown address`. Restored.
    """
    calls = {"wrong_password": 0, "unknown_address": 0}
    current = {"phase": None}
    original = Credential.derive

    def counting(password, salt, iterations):
        if current["phase"]:
            calls[current["phase"]] += 1
        return original(password, salt, iterations)

    monkeypatch.setattr(Credential, "derive", staticmethod(counting))

    current["phase"] = "wrong_password"
    client.post("/api/session", json={"email": "a@example.ch", "password": "not the password"})
    current["phase"] = "unknown_address"
    client.post("/api/session", json={"email": "nobody@example.ch", "password": "not the password"})
    current["phase"] = None

    assert calls["wrong_password"] >= 1
    assert calls["unknown_address"] >= 1, "0 derivations for an unknown address: the stopwatch answers"


def test_the_address_is_matched_case_insensitively_and_trimmed(client, member_a):
    """`_normalise_email` is the service's, and this is the route honouring it rather than pre-lowering
    the address itself — two normalisations that could drift is one too many."""
    assert client.post(
        "/api/session", json={"email": "  A@Example.CH  ", "password": PASSWORD_A}
    ).status_code == 201


# ============================================================ the session itself


def test_the_raw_token_is_returned_once_and_stored_only_as_a_hash(client, api_session, member_a):
    """If `sessions` leaks it must not be a set of live keys. The row is checked directly."""
    token = _token(client, "a@example.ch", PASSWORD_A)
    rows = api_session.execute(select(SessionRow)).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash == SessionRow.hash_token(token)
    assert token.encode("utf-8") not in bytes(rows[0].token_hash)

    identity = client.get("/api/session", headers=bearer(token))
    assert identity.status_code == 200
    assert "token" not in identity.json(), "the raw token is echoed by a second route"


def test_who_am_i_reports_the_member_and_the_language(client, member_a, token_a):
    payload = client.get("/api/session", headers=bearer(token_a)).json()
    assert payload["member_id"] == member_a.id
    assert payload["display_name"] == "Mitglied A"
    assert payload["locale"] == "de-CH"
    # A12 keys the strings by language, not by locale. The server splits it so a client cannot.
    assert payload["language"] == "de"
    assert payload["must_change"] is False


def test_logging_out_revokes_that_session_and_only_that_session(client, api_session, member_a):
    """A laptop logging out is not a statement about a phone.

    **Planted violation:** called `revoke_all_sessions` instead of `logout`. Failed on the second token
    still being expected to work. Restored.
    """
    laptop = _token(client, "a@example.ch", PASSWORD_A)
    phone = _token(client, "a@example.ch", PASSWORD_A)

    assert client.delete("/api/session", headers=bearer(laptop)).json() == {"ended": True}
    assert client.get("/api/positions", headers=bearer(laptop)).status_code == 401
    assert client.get("/api/positions", headers=bearer(phone)).status_code == 200


def test_logging_out_twice_reports_nothing_about_whether_the_token_existed(client, member_a, token_a):
    """The same oracle in a smaller place: a 404 on an unknown token would answer "was this ever a
    session" for whoever is holding the string."""
    assert client.delete("/api/session", headers=bearer(token_a)).status_code == 200
    again = client.delete("/api/session", headers=bearer(token_a))
    unknown = client.delete("/api/session", headers=bearer("not-a-token-at-all"))
    assert again.status_code == unknown.status_code == 200
    assert again.json() == unknown.json() == {"ended": False}


# ============================================================ must_change (A43, A53)


@pytest.fixture()
def must_change_member(client, api_session, fast_kdf):
    """Elio and Yasmin T. as the seed script makes them: a documented password, good for one login."""
    member, credential = _register(
        api_session, email="elio@example.ch", password="das dokumentierte passwort", name="Elio"
    )
    credential.must_change = True
    api_session.commit()
    return member


def test_a_must_change_session_can_do_exactly_three_things(client, must_change_member):
    """A forced password change the client enforces is not enforced.

    The token is real and it opens `GET /api/session`, `DELETE /api/session` and `POST /api/password`.
    Everything else is 403 with the marker the client tests for.

    **Planted violation:** made `current_member` return the member without consulting `must_change`.
    Failed on `/api/positions` returning 200. Restored.
    """
    token = _token(client, "elio@example.ch", "das dokumentierte passwort")
    assert client.post(
        "/api/session", json={"email": "elio@example.ch", "password": "das dokumentierte passwort"}
    ).json()["must_change"] is True

    identity = client.get("/api/session", headers=bearer(token))
    assert identity.status_code == 200 and identity.json()["must_change"] is True

    for path in ("/api/positions", "/api/vault", "/api/goals", "/api/actions", "/api/export"):
        refused = client.get(path, headers=bearer(token))
        assert refused.status_code == 403, f"{path} let a must-change session through"
        assert "password_change_required" in refused.json()["detail"]


def test_the_documented_password_stops_working_once_a_new_one_is_chosen(client, must_change_member):
    """A53's whole argument for writing a demonstration password into a shared document is that it is
    good for exactly one login. This is that claim, executed.

    **Planted violation:** had `change_password` keep the old hash. Failed on the old password still
    opening a session. Restored.
    """
    token = _token(client, "elio@example.ch", "das dokumentierte passwort")
    changed = client.post(
        "/api/password",
        headers=bearer(token),
        json={"current": "das dokumentierte passwort", "new": "ein selbst gewaehltes passwort"},
    )
    assert changed.status_code == 200 and changed.json()["must_change"] is False

    stale = client.post(
        "/api/session", json={"email": "elio@example.ch", "password": "das dokumentierte passwort"}
    )
    assert stale.status_code == 401, "the documented password still opens a session"

    fresh = client.post(
        "/api/session", json={"email": "elio@example.ch", "password": "ein selbst gewaehltes passwort"}
    )
    assert fresh.status_code == 201 and fresh.json()["must_change"] is False

    # And the session that did the changing is now a full session.
    assert client.get("/api/positions", headers=bearer(token)).status_code == 200


def test_changing_a_password_still_requires_the_current_one_when_must_change_is_set(
    client, must_change_member
):
    """The service's rule, kept rather than relaxed at the edge: waiving it here would turn a stolen
    token into a password change."""
    token = _token(client, "elio@example.ch", "das dokumentierte passwort")
    refused = client.post(
        "/api/password",
        headers=bearer(token),
        json={"current": "the wrong one", "new": "ein selbst gewaehltes passwort"},
    )
    # 403 and not 401: the session is fine, the field is wrong, and a 401 would tell a client to discard
    # a good token.
    assert refused.status_code == 403


def test_a_password_change_refuses_a_short_password_by_the_models_own_rule(client, member_a, token_a):
    refused = client.post(
        "/api/password", headers=bearer(token_a), json={"current": PASSWORD_A, "new": "kurz"}
    )
    assert refused.status_code == 422
    assert "12 characters" in refused.json()["detail"]


def test_a_password_change_cannot_be_aimed_at_another_member(client, member_a, member_b, token_a):
    """There is no field to aim it with, which is the point; this pins that the extra field is inert."""
    client.post(
        "/api/password",
        headers=bearer(token_a),
        json={"member_id": member_b.id, "current": PASSWORD_A, "new": "ein neues langes passwort"},
    )
    assert client.post(
        "/api/session", json={"email": "b@example.ch", "password": PASSWORD_B}
    ).status_code == 201, "B's password was changed by A"


# ============================================================ registration


def test_registration_creates_a_credential_and_the_member_can_then_log_in(client, api_session, fast_kdf):
    """A member row with no credential is an account nobody can ever open. Registration and the
    credential are one act now, which is why `POST /api/members` moved into `api/auth.py`."""
    created = client.post(
        "/api/members",
        json={
            "email": "neu@example.ch",
            "password": "ein hinreichend langes passwort",
            "age_at_registration": 30,
            "display_name": "Neu",
            "consents": CONSENT_BODY,
        },
    )
    assert created.status_code == 201, created.text
    assert "token" not in created.json(), "registration mints a token; only POST /api/session may"

    opened = client.post(
        "/api/session", json={"email": "neu@example.ch", "password": "ein hinreichend langes passwort"}
    )
    assert opened.status_code == 201
    assert opened.json()["member_id"] == created.json()["id"]


def test_registration_refuses_below_the_age_floor_and_leaves_nothing_behind(client, api_session):
    """R-100 / A50. The floor is the service's; what this adds is that a refusal writes no half-account.

    **Planted violation, and it did not fail — which is the finding.** Removing the route's
    `session.rollback()` from the `BelowAgeFloor` branch changed nothing, because `register_member`
    raises before it adds a row and there is nothing to roll back. Re-planted by *reordering the service*
    so the floor raises after the member has been added and flushed, and this test failed — on
    `CHECK constraint failed: ck_members_age_floor`, from the table, not from the service. So the
    property this test holds is real and is held by two mechanisms, and the route's rollback is neither
    of them. `api/auth.py` now says so at that line rather than leaving it looking load-bearing. The
    `WeakPassword` branch below is the one where the rollback *is* what keeps the row out, and that one
    was proven by removing it.
    """
    from eigentlich.models import MINIMUM_AGE, Member

    before = len(api_session.execute(select(Member)).scalars().all())
    refused = client.post(
        "/api/members",
        json={
            "email": "zujung@example.ch",
            "password": "ein hinreichend langes passwort",
            "age_at_registration": MINIMUM_AGE - 1,
            "display_name": "Zu jung",
            "consents": CONSENT_BODY,
        },
    )
    assert refused.status_code == 422
    assert str(MINIMUM_AGE) in refused.json()["detail"]
    assert len(api_session.execute(select(Member)).scalars().all()) == before
    assert api_session.execute(
        select(Credential).where(Credential.email == "zujung@example.ch")
    ).scalar_one_or_none() is None


def test_a_password_too_short_leaves_no_member_row_behind(client, api_session, fast_kdf):
    """`set_password` raises after `register_member` has already flushed the member. Without the explicit
    rollback this route would create members nobody could ever log in as, one failed attempt at a time.

    **Planted violation:** removed `session.rollback()` from the `WeakPassword` branch. The member row
    was committed by the next request's commit and this failed. Restored.
    """
    from eigentlich.models import Member

    before = len(api_session.execute(select(Member)).scalars().all())
    refused = client.post(
        "/api/members",
        json={
            "email": "kurz@example.ch",
            "password": "kurz",
            "age_at_registration": 30,
            "display_name": "Kurzes Passwort",
            "consents": CONSENT_BODY,
        },
    )
    assert refused.status_code == 422
    assert len(api_session.execute(select(Member)).scalars().all()) == before


def test_a_second_registration_of_one_address_is_refused(client, api_session, fast_kdf):
    """The one place eigentliCH does say whether an address is known — and the person being told is the one
    trying to register it. Different situation from the login form; see api/auth.py."""
    body = {
        "email": "zweimal@example.ch",
        "password": "ein hinreichend langes passwort",
        "age_at_registration": 30,
        "display_name": "Zweimal",
        "consents": CONSENT_BODY,
    }
    assert client.post("/api/members", json=body).status_code == 201
    assert client.post("/api/members", json=body).status_code == 409


# ============================================================ no second way in


def test_no_route_offers_a_way_in_that_is_not_the_token():
    """The owner's instruction, as an executable rule: no developer bypass, and nothing that could grow
    into one.

    A grep, not a proof. What it buys is that adding a bypass takes a deliberate edit to a file that says
    in its own docstring why there is not one — the same argument A72 makes for keeping the C-09 escape
    hatch a single greppable identifier.

    **Planted violation:** added `if os.environ.get("ANDERSCH_DEV_MEMBER")` to `current_member`. Failed
    on `auth.py reads the environment`. Removed.
    """
    offenders = []
    for path in sorted(API.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', " ", source)
        code = re.sub(r"^\s*#.*$", " ", code, flags=re.MULTILINE)
        if re.search(r"os\.environ|getenv", code):
            offenders.append(f"{path.name} reads the environment")
        for marker in ("X-Member-Id", "dev_member", "DEV_MEMBER", "impersonate", "as_member"):
            if marker in code:
                offenders.append(f"{path.name} mentions {marker}")
    assert not offenders, "a second door into the application:\n  " + "\n  ".join(offenders)


def test_only_one_module_reads_a_session_token():
    """A73's lesson applied before it costs anything: two implementations of "who is this" would have to
    be kept in step by hand, and the second one is where the must-change refusal gets forgotten.

    `api/curator.py` used to carry its own copy. It imports `current_member` now.

    **This test was itself wrong once, and it is worth recording why.** It matched `member_for_token(` —
    with the parenthesis — so re-adding the *import* to `api/curator.py` did not trip it, and the module
    would have been one line from a second implementation with the guard still green. Matched on the bare
    name now: importing it is the thing that precedes calling it.
    """
    readers = [
        path.name
        for path in sorted(API.glob("*.py"))
        if "member_for_token" in re.sub(r'"""(?:.|\n)*?"""', " ", path.read_text(encoding="utf-8"))
    ]
    assert readers == ["auth.py"], f"more than one module resolves a session token: {readers}"


def test_the_curator_door_and_the_member_door_are_still_two_doors(client, api_session, member_a, token_a):
    """A member's bearer token is not a curator login, and a 401 on the curator surface must not become
    a 403 by accident — `api/curator.py` documents these as two doors and this holds it."""
    assert client.get("/api/curator/members", headers=bearer(token_a)).status_code == 401
    basic = base64.b64encode(b"a@example.ch:" + PASSWORD_A.encode()).decode()
    assert client.get(
        "/api/curator/members", headers={"Authorization": f"Basic {basic}"}
    ).status_code == 401, "a member's credentials authenticated as a curator"


def test_a_vault_item_cannot_be_superseded_across_the_member_boundary(
    client, api_session, member_a, member_b, token_a
):
    """R-041's chain, with two members in the database. The check was `body.member_id`, which the caller
    supplied on both sides and could therefore always satisfy."""
    from eigentlich.services import store_item
    from eigentlich.api import main

    item = store_item(
        api_session, main.VAULT_STORE, member_id=member_b.id, kind="note", title="B's Notiz",
        source="manual", notes="B",
    )
    api_session.commit()

    refused = client.post(
        "/api/vault",
        headers=bearer(token_a),
        json={"kind": "note", "title": "uebernommen", "notes": "A", "supersedes_id": item.id},
    )
    assert refused.status_code == 422
    assert api_session.get(VaultItem, item.id).member_id == member_b.id
