"""A11 over HTTP: the session routes, and the dependency every member route resolves its member from.

**What this closes.** `services/auth.py` has been complete and tested since phase 2 and nothing HTTP-facing
called it except one dependency in `api/curator.py`. Every other member route took `member_id` as a query
parameter or a body field and believed it, so `GET /api/positions?member_id=<any id>` returned another
member's whole role grid to anybody who could type. The service layer was built and the boundary was not.

**The fix is the removal of the parameter, not a check on it.** `current_member` reads the bearer token,
resolves the member through `services.auth.member_for_token`, and hands the route a `Member`. A route that
never receives a `member_id` cannot be given the wrong one, and no amount of forgetting to compare two
strings can reintroduce the hole. Where a request body used to carry `member_id` the field is gone from the
model, so FastAPI ignores an extra one rather than a handler quietly preferring it.

**There is no developer bypass, and that is a decision** (owner, 2026-08-31). No `?member_id=` fallback for
localhost, no `ANDERSCH_DEV_MEMBER` environment variable, no operator header. A second way in is the thing
that gets shipped by accident; the demonstration accounts in `tools/seed_demo_accounts.py` are how someone
gets in on their own laptop, and they go through this door like anyone else.
`test_api_auth.py::test_no_route_offers_a_way_in_that_is_not_the_token` greps this package for one.

---------------------------------------------------------------------------------------------------------
THE ROUTES THAT DO NOT REQUIRE A SESSION, and why each one does not
---------------------------------------------------------------------------------------------------------

Written out here rather than inferred route by route, because "did anyone remember to add the dependency"
is exactly the question a reader should not have to answer by reading 40 signatures. The rule is one line:

    A route is open only if it is incapable of returning anything about any member and takes no
    member-owned input. Everything else takes `Depends(current_member)`.

    GET  /api/health               the build's own status: revision, tables, triggers, constraint names.
                                   Names no member and reads no member table.
    GET  /api/local-model          whether Ollama is reachable. A statement about this machine.
    GET  /api/goal-templates       R-132. Authored content — the templates and the liquidity bands.
    GET  /api/destination          D-07 / A22. The one content key the destination phrase comes from. It
                                   is what the product is for, it is identical for every member, and it
                                   appears on screens a person sees before they have an account — a phrase
                                   behind a session could not be read by the person deciding whether to
                                   register. Reads `client/content/destination.json` and no table at all.
    GET  /api/learning/exits       R-193. Three authored exits. Its own docstring already promises that a
                                   client can show them "without first asking for a member's learning
                                   path", and the route has no member parameter to remove.
    GET  /api/life-events          S-09. The seven module titles, all unauthored (R-183). It used to
                                   accept `member_id` and did nothing with it but echo it back into the
                                   payload; the parameter is gone rather than guarded, because it never
                                   bought anything. `/api/life-events/{key}` is a different matter — it
                                   retrieves the member's vault items (R-181) — and is guarded.
    GET  /api/regime               The macro read, and the FIRST REGULATORY BOUNDARY made visible. Page 3
                                   of Journey & Design: the regime is "population-level and carries no
                                   member data at all: computed once, shared by everyone", and
                                   "everything on the population side can be shown to anyone, before
                                   signup, without member data and without regulatory exposure". Update
                                   script item 5 adds the product argument — it is "the product's most
                                   distinctive output at zero data cost" and nothing exposed it to a
                                   person who had not completed an intake. `services/regime.read` takes
                                   no member id and admits only SCALAR readings out of the Regime, so
                                   the Fund Map's grids and profile vectors stay on the server (C-03).
    GET  /api/stages/{key}         R-141: any stage, opened by anybody, at any age. Its docstring makes
                                   the absence of a member parameter the promise. `/api/stages` (the map)
                                   IS guarded: `member_id` there selects `opens_at` from the member's
                                   own `stage_hint`.
    GET  /api/settings/data-classes  R-232. Which data class each category falls into, derived from the
                                   model layer. Its docstring already says asking for a member would
                                   imply the answer differs per person.
    GET  /api/marketplace/roles    R-200. The four roles and what sits under each. The taxonomy.
    GET  /api/curator/grantable    A40 / R-212. The names of the grantable scopes — a vocabulary, the
                                   same four words for everybody. It is the only route under the curator
                                   prefix that authenticates nobody, and it has to be: a member choosing
                                   what to share reads it, and so does a curator.
    GET  /api/consent-statement    R-103 / C-05 / A97. What a member is **asked** and what they are
                                   **told** before an account exists: both purposes with their `kind`, the
                                   published wording, and the document version the registration form has
                                   to echo back for the consent. Authored K0 text (`consent.py`),
                                   identical for every member, and a form that could not be read without a
                                   session could not be read by the person about to register.
    GET  /api/curators             The staff list. `api/curators.py` records this as a decision rather
                                   than an omission: R-170 keeps the Curator button on screen at all
                                   times, and it cannot name anyone before login if this is locked. It
                                   says a name and a role label and nothing about any member.

    POST /api/session              The login form itself. It is what authenticates, so it cannot require
                                   having been authenticated.
    POST /api/members              Registration, and the one exemption that is not a memberlessness
                                   claim: this route is where a session becomes possible, so it cannot
                                   require one. It now takes an email and a password and creates the
                                   credential, because a member who cannot log in afterwards is not
                                   registered. R-100's age floor still runs in the service first, and
                                   R-103's consent is verified before any write at all.

Everything under `/api/curator/*` authenticates as a curator (A40, HTTP Basic) or, for the grant routes,
as the member with this same bearer token — `api/curator.py` owns that and imports `current_member` from
here rather than keeping a second copy of it. The one exception is `POST /api/curator/sessions`, which
lives in `main.py`, is member-facing despite its prefix, and is guarded like any other member route.

---------------------------------------------------------------------------------------------------------

**must_change is enforced here, not in the client.** A forced password change that only the client enforces
is not enforced. `current_member` refuses with 403 while the credential is marked, so a token issued to
Elio or Yasmin T. can reach exactly three routes — `GET /api/session`, `DELETE /api/session` and
`POST /api/password` — until a new password is chosen. Those three take `authenticating_member`, which is
the same resolution without that last step.

**Login says nothing about who has an account.** Wrong address, wrong password and no such account are one
401 with one message. `services.auth.login` derives against a throwaway salt when the account is missing so
the two take comparable time; this route adds no second lookup, no distinct status and no distinct body on
either path, because a membership oracle is as easily rebuilt at the edge as in the service.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..consent import (
    DuplicateConsent,
    MissingRequiredConsent,
    NotAConsent,
    REQUIRED_PURPOSES,
    StaleConsentDocument,
    UnregisteredPurpose,
    statement as consent_statement,
    verify_acceptance,
)
from ..content import DEFAULT_LANGUAGE, LANGUAGES
from ..models import Credential, MINIMUM_AGE, MINIMUM_PASSWORD_LENGTH, Member, WeakPassword
from ..services.auth import (
    AuthenticationFailed,
    EmailAlreadyRegistered,
    change_password,
    login,
    logout,
    member_for_token,
    register_with_credentials,
)
from ..services.registration import BelowAgeFloor

router = APIRouter(prefix="/api", tags=["session"])

#: The one message both halves of a failed login get. A single constant so a future edit cannot make one
#: path more informative than the other by accident.
LOGIN_REFUSED = "email or password is incorrect"

#: The detail a member with a must-change credential gets on every other route. Machine-readable in the
#: sense that matters: the client tests for the marker rather than for a sentence it would have to match.
MUST_CHANGE_REFUSED = (
    "password_change_required: this session cannot be used until a new password is chosen. "
    "POST /api/password with the current password and a new one."
)


def get_session() -> Iterator[DbSession]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle — and one that fails
    only in the order FastAPI actually loads things, which is the worst kind. The same pattern as
    `api/learning.py`, `api/marketplace.py` and the rest.

    **A test that stands a router up on its own app must override THIS dependency too**, not only its own
    router's copy: the token is resolved through this one, so overriding just the router under test would
    authenticate against the real `backend/eigentlich.db` while the routes read the in-memory fixture.
    `tests/conftest.py::api_app` does both, and every HTTP fixture in the suite goes through it.
    """
    from .main import get_session as application_session

    yield from application_session()


# ---------------------------------------------------------------- the dependency


def _bearer(authorization: str | None) -> str:
    """The token out of an Authorization header, or a 401. The one place this header is parsed.

    **A bare `Bearer ` used to raise IndexError and come back as a 500.** `split(None, 1)` returns a
    one-element list when there is nothing after the scheme, and `api/curator.py` carried the same line
    for three phases. Found by the parametrised header test, which exists because header parsing is where
    a guard historically stops being a refusal and becomes a stack trace. `partition` cannot do that, and
    an empty token is refused here rather than handed to `member_for_token` to fail on later.
    """
    refusal = HTTPException(
        401,
        "a member session token is required. POST /api/session with an email and a password.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization:
        raise refusal
    scheme, _, rest = authorization.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        raise refusal
    return rest.strip()


def authenticating_member(
    authorization: str | None = Header(default=None),
    session: DbSession = Depends(get_session),
) -> Member:
    """The member behind the token, with a must-change credential still allowed through.

    Exactly three routes take this: reading who you are, ending the session, and choosing the new
    password. Anything else takes `current_member`, which is this plus the refusal.
    """
    member = member_for_token(session, _bearer(authorization))
    if member is None:
        raise HTTPException(
            401,
            "session token is not valid. It may have expired or been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return member


def current_member(
    member: Member = Depends(authenticating_member),
    session: DbSession = Depends(get_session),
) -> Member:
    """**The** member of this request. Every member-facing route in the application takes this.

    Returns a `Member`, not an id, so a route cannot accept one from anywhere else and still typecheck
    against the service call it makes.
    """
    credential = _credential(session, member.id)
    if credential is not None and credential.must_change:
        raise HTTPException(403, MUST_CHANGE_REFUSED)
    return member


def _credential(session: DbSession, member_id: str) -> Credential | None:
    return session.execute(
        select(Credential).where(Credential.member_id == member_id)
    ).scalar_one_or_none()


def _language_for(member: Member) -> str:
    """`de-CH` is a locale and `de` is a language; A12 keys the strings by the second.

    Derived on the server rather than left to the client to split on a hyphen, because a client that
    guesses gets `de-CH` right and a future `rm-CH` wrong, silently, in German.
    """
    prefix = (member.locale or "").split("-")[0].lower()
    return prefix if prefix in LANGUAGES else DEFAULT_LANGUAGE


# ---------------------------------------------------------------- the session


class LoginRequest(BaseModel):
    #: No `EmailStr`. A9 took four dependencies and `email-validator` is not one of them, and a format
    #: rule here would answer "is this address shaped like one we would have" a shade faster than it
    #: answers anything else. The service normalises and looks up; that is the whole check.
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)


@router.post("/session", status_code=201)
def open_session(body: LoginRequest, session: DbSession = Depends(get_session)) -> dict:
    """A11. Email and password in, one raw token out, once.

    The token is returned here and nowhere else: `sessions` stores only its SHA-256, so this response is
    the only moment it exists in a form anyone can use. A client that loses it logs in again.

    **Both halves of a failure are this same 401 with this same body.** No branch above returns early on
    an unknown address, and the service derives against a throwaway salt when there is no credential, so
    neither the status, the body nor the clock says whether the address is one of ours — C-05 makes
    eigentliCH sole controller of that fact and it is not given away at a login form.
    """
    try:
        record, token = login(session, email=body.email, password=body.password)
    except AuthenticationFailed as refused:
        raise HTTPException(401, LOGIN_REFUSED, headers={"WWW-Authenticate": "Bearer"}) from refused

    member = session.get(Member, record.member_id)
    credential = _credential(session, record.member_id)
    session.commit()
    return {
        "token": token,
        "member_id": member.id,
        "display_name": member.display_name,
        "locale": member.locale,
        "language": _language_for(member),
        # A43. Set by `operator_reset` and by the two seeded access accounts. While it is true the token
        # opens this route, `DELETE /api/session` and `POST /api/password` and nothing else.
        "must_change": bool(credential.must_change) if credential else False,
        "expires_at": record.expires_at.isoformat(),
    }


@router.get("/session")
def read_session(member: Member = Depends(authenticating_member),
                 session: DbSession = Depends(get_session)) -> dict:
    """Who am I. The client's first call after it finds a stored token, and its liveness check.

    Deliberately readable while `must_change` is set: a client that could not ask who it was would have
    to decide what screen to show from a status code.
    """
    credential = _credential(session, member.id)
    return {
        "member_id": member.id,
        "display_name": member.display_name,
        "locale": member.locale,
        "language": _language_for(member),
        "must_change": bool(credential.must_change) if credential else False,
    }


@router.delete("/session")
def end_session(
    authorization: str | None = Header(default=None),
    session: DbSession = Depends(get_session),
) -> dict:
    """Logout. Revokes this one session, not every session the member has.

    `revoke_all_sessions` exists and is what the operator reset uses (A43). Logging out of a laptop is
    not a statement about a phone, so this route is the narrow one and there is no parameter that widens
    it.

    Idempotent by intent: a token that was already revoked, expired or never valid gets a 200 and
    `ended: false`. A 404 here would report on the existence of a session to whoever is holding the
    string, which is the same oracle the login route refuses to be.
    """
    ended = logout(session, _bearer(authorization))
    session.commit()
    return {"ended": bool(ended)}


# ---------------------------------------------------------------- the password


class PasswordChangeRequest(BaseModel):
    current: str = Field(..., min_length=1, max_length=1024)
    new: str = Field(..., min_length=1, max_length=1024)


@router.post("/password")
def change_own_password(
    body: PasswordChangeRequest,
    member: Member = Depends(authenticating_member),
    session: DbSession = Depends(get_session),
) -> dict:
    """A member changing their own password. **The current one is required even when `must_change` is set.**

    That is the service's rule and it is kept rather than relaxed: `must_change` means an operator set this
    password (A43) or it is a documented demonstration credential (A53), and in both cases the person at
    the keyboard is supposed to know it. Waiving it would turn a stolen token into a password change.

    **The old password stops working here**, which is the half of A53 that matters: the passwords for the
    two access accounts are written down in Notion, and they are good for one login precisely because this
    route clears `must_change` and rewrites the hash.

    No `member_id` field. The member is the token's, so this route cannot be aimed at anyone else.
    """
    try:
        change_password(session, member_id=member.id, current=body.current, new=body.new)
    except AuthenticationFailed as refused:
        # 403, not 401: the session is valid and the member is who they say. What is wrong is the current
        # password in the body, and a 401 here would tell a client to throw away a good token.
        raise HTTPException(403, "current password is incorrect") from refused
    except WeakPassword as weak:
        raise HTTPException(422, str(weak)) from weak
    session.commit()
    return {"member_id": member.id, "must_change": False}


# ---------------------------------------------------------------- registration


class ConsentAcceptance(BaseModel):
    """One accepted purpose, and the version of the wording the form displayed.

    **The version comes from the client, and it is checked rather than trusted.** It is not the client's
    to decide — `consent.py` publishes it and `verify_acceptance` refuses anything else. Sending it is how
    the client proves *which words* it showed: a registration form left open across a wording change is
    refused instead of quietly recording agreement to text nobody saw. Stamping the current version
    server-side would have made the field decorative and R-103's versioning with it.

    **A97: only a consent may appear here.** A purpose the registry publishes as a notice is refused with
    a 422 naming it, rather than dropped — a form still sending `entscheidprotokoll` is a form still
    showing a checkbox for something the member cannot decline, and that is worth a client noticing.
    """

    purpose: str = Field(
        ..., min_length=1, max_length=80, description=f"One of {list(REQUIRED_PURPOSES)} — R-103."
    )
    document_version: str = Field(
        ..., min_length=1, max_length=40, description="Echoed from GET /api/consent-statement."
    )


class RegistrationRequest(BaseModel):
    """R-100, R-103 and A11 in one request, because they are one moment.

    No `Field(ge=MINIMUM_AGE)` on the age and no length rule on the password. Both are checked in the
    service — `services/registration.py` and `Credential.set_password` — and a request-model validator
    would return 422 before either ran, which reads like enforcement and is not: it would be walked past
    by every other caller. The schema's job here is the shape.

    **`consents` is required and has no default**, which is the whole of the R-103 fix. A default — an
    empty list, or the required set filled in — would be the path every caller took, and the consent
    recorded would be eigentliCH's rather than the member's. `consent.verify_acceptance` does the checking;
    what the schema contributes is that a body without the field never reaches a write.
    """

    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description=f"At least {MINIMUM_PASSWORD_LENGTH} characters. Length is the only rule.",
    )
    age_at_registration: int = Field(
        ..., description=f"NG-05 / A50: eigentliCH does not open accounts below {MINIMUM_AGE}."
    )
    display_name: str = Field(..., min_length=1, max_length=200)
    locale: str = "de-CH"
    consents: list[ConsentAcceptance] = Field(
        ...,
        description=(
            "R-103 / C-05. Every purpose in `required_at_registration` from "
            "GET /api/consent-statement, each with the document_version that response gave. A97: the "
            "purposes in `notices` are displayed to the member and not sent back here."
        ),
    )


@router.get("/consent-statement")
def get_consent_statement(language: str = DEFAULT_LANGUAGE) -> dict:
    """R-103 and C-05, before an account exists. What is being agreed to, in the member's language.

    **Open, and it has to be**: the person reading this has no session yet, and asking for one would put
    the consent form behind the thing the consent form makes possible. It names no member, reads no member
    table and takes no member-owned input, which is the rule `OPEN_ROUTES` is drawn from.

    `wording_is_provisional` is `true` and will stay true until the owner reviews the text — the same
    arrangement D-03 has for the role definitions. A client should render it rather than hide it: these are
    honest descriptions of what eigentliCH does, written to make the capture point exist, and they are not a
    data-protection notice.

    **A97 put two kinds in one payload.** Each entry in `purposes` carries `kind`: `"consent"` is asked and
    goes back in the registration body, `"notice"` is told and does not. `required_at_registration` and
    `notices` name them, `echo_at_registration` is the consent half alone, and `notices_are_not_a_choice`
    is true — a notice rendered as a checkbox, ticked or not, is the misrepresentation A97 removed arriving
    back through the front end. The notice is the more surprising of the two facts, so it is not the one to
    put behind a link.
    """
    if language not in LANGUAGES:
        raise HTTPException(
            422, f"unknown language {language!r}; expected one of {list(LANGUAGES)} — A12."
        )
    return consent_statement(language)


@router.post("/members", status_code=201)
def create_member(body: RegistrationRequest, session: DbSession = Depends(get_session)) -> dict:
    """R-100 and A11. The floor is checked in the service, not in the request model.

    **Moved here from `main.py` when A11 was wired.** Registration and the credential are one act: a member
    row with no credential is an account nobody can ever open, and leaving the two in two files is how one
    of them gets forgotten. `register_with_credentials` refuses the age first, so no credential is created
    for an account that cannot exist.

    **No token comes back.** Registration does not log anybody in; the client posts the same address and
    password to `POST /api/session` immediately afterwards. One route mints tokens, which is one place to
    read when asking how a session begins.

    `EmailAlreadyRegistered` is a 409 and does say so — unavoidably, and the person being told is the one
    trying to register that address. That is a different situation from the login form, where the asker is
    anonymous; see the module docstring.

    **R-103's capture point is here, and it runs before any write.** `verify_acceptance` is a pure
    function on the request: it refuses an unregistered purpose, a purpose published as a notice (A97), a
    stale document version, a repeated purpose and a missing required one, and it does so while the
    transaction is still empty.

    **What that ordering buys, and what it does not.** It does not protect R-100 — writing the member and
    the credential first and checking the consent afterwards was planted, and the age floor went on
    refusing exactly as before, because the floor is held by `register_member` and by
    `ck_members_age_floor` and neither cares where this line sits. What it protects is the *consent*
    guarantee: run after the write and every unacceptable body leaves a member row and a credential
    behind, which is the half-registered account this route exists to make impossible. **Six of the seven**
    refusal shapes in `test_no_account_is_created_without_the_required_consents` went red on that plant,
    re-run for A97; the seventh is the absent field, which pydantic refuses before this function is
    entered.

    A member who is both too young and short of consent is refused for the consent. The floor is still
    enforced twice below this line.

    The `Consent` rows are written inside `register_with_credentials`, in the same transaction as the
    member and the credential. There is no window in which an account exists without them.
    """
    try:
        consents = verify_acceptance(body.consents)
    except (
        UnregisteredPurpose,
        NotAConsent,
        StaleConsentDocument,
        DuplicateConsent,
        MissingRequiredConsent,
    ) as refused:
        # No rollback: nothing has been written. Said out loud because the two branches below do roll
        # back, and a reader should not have to work out why this one does not.
        raise HTTPException(422, str(refused)) from refused

    try:
        member, _ = register_with_credentials(
            session,
            email=body.email,
            password=body.password,
            age_at_registration=body.age_at_registration,
            display_name=body.display_name,
            locale=body.locale,
            consents=consents,
        )
    except BelowAgeFloor as refusal:
        # Insurance, and said to be insurance rather than left looking load-bearing. `register_member`
        # raises before it adds anything, and `ck_members_age_floor` refuses the INSERT even if that
        # order ever changes — both were re-checked by planting the reordering, and the CHECK caught it.
        # This line is what would keep the transaction clean; it is not what keeps the row out.
        session.rollback()
        raise HTTPException(422, str(refusal)) from refusal
    except WeakPassword as weak:
        # The member row was created and flushed before `set_password` raised. Roll it back explicitly
        # rather than relying on the session context closing: a half-registered member with no credential
        # is exactly the state this route exists to make impossible.
        session.rollback()
        raise HTTPException(422, str(weak)) from weak
    except EmailAlreadyRegistered as taken:
        session.rollback()
        raise HTTPException(409, str(taken)) from taken
    session.commit()
    return {
        "id": member.id,
        "display_name": member.display_name,
        "locale": member.locale,
        # R-230's history starts here rather than empty. Returned so a client can show what was recorded
        # instead of asserting that something was.
        "consents_recorded": [entry["purpose"] for entry in consents],
    }


__all__ = [
    "LOGIN_REFUSED",
    "MUST_CHANGE_REFUSED",
    "ConsentAcceptance",
    "RegistrationRequest",
    "authenticating_member",
    "current_member",
    "get_session",
    "router",
]
