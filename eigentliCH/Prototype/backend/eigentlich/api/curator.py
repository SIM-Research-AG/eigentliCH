"""S-12 over HTTP. Two authenticated parties, and no route that serves member material to neither.

**Two doors, deliberately not one.** The curator routes authenticate as a curator (A40, HTTP Basic against
the `curators` table). The grant routes authenticate as the *member*, with the member's own bearer token —
because R-213 says grants are revocable *by the member*, and a revocation a curator could perform on the
member's behalf is not the member's control. `member_id` never arrives as an unauthenticated body field on
those routes; it is read off the token.

**Every member-facing GET here is a thin wrapper over a gated service call**, and none of them catches
`AccessDenied` to fall back to something emptier. A refusal is a 403 with the reason, because R-210's whole
value is that the curator, the member and the log all see the same "no" — a 200 with an empty list would be
indistinguishable from a member who has nothing.

**No curator token is issued.** `POST /api/curator/login` verifies and returns the identity; it does not
mint a session, because there is no curator session table and phase 5 does not own a migration. Every
subsequent request re-authenticates. See the note in `services/curator.py` for the trade.

**must_change is enforced here, not in the client** — the same arrangement `api/auth.py` describes for
members, and added on 31 August 2026 because until then `Curator.must_change` was a flag nothing read.
`authenticating_curator` is the Basic door with the flag still allowed through, and exactly two routes take
it: `POST /api/curator/login` (so a curator can be told *why* they may not proceed) and
`POST /api/curator/password` (so they can do something about it). Every other route under this prefix takes
`current_curator`, which is the same resolution plus a 403. All five real curators are seeded with the flag
set, so until each of them chooses a password their credential opens those two routes and nothing else.

`api/main.py` is not touched by this module. The router is exported and wired there, so phase 5 could be
written without contending for that file — the same reason `api/learning.py` exists.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AccessGrant, Curator, GRANTABLE, Member
from ..models.auth import WeakPassword
from ..services.curator import (
    AccessDenied,
    CuratorAuthenticationFailed,
    NoOpenSession,
    SessionAlreadyClosed,
    UnknownScope,
    authenticate_curator,
    change_curator_password,
    close_session,
    curator_view_action_items,
    curator_view_decisions,
    curator_view_goals,
    curator_view_positions,
    curator_view_vault,
    curator_workbench,
    grant_access,
    is_live,
    members_with_live_access,
    open_session,
    recommend,
    record_note,
    revoke_grant,
    revoke_session_grants,
    session_record,
    sessions_for_curator,
)
from .auth import current_member

router = APIRouter(prefix="/api/curator", tags=["curator"])

#: The detail a curator with a must-change credential gets on every route but the two that take
#: `authenticating_curator`. Machine-readable in the sense that matters: the client tests for the marker
#: rather than for a sentence it would have to match, exactly as `api/auth.py::MUST_CHANGE_REFUSED` does.
#:
#: A distinct marker from the member's, deliberately. The two changes go to different routes with different
#: credentials, and a client that matched one string for both would send a curator to the member's form.
CURATOR_MUST_CHANGE_REFUSED = (
    "curator_password_change_required: this credential cannot be used until a new password is chosen. "
    "POST /api/curator/password with the current password and a new one."
)


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle — and one that fails
    only in the order FastAPI actually loads things, which is the worst kind. The same pattern as
    `api/learning.py`.
    """
    from .main import get_session as application_session

    yield from application_session()


# ---------------------------------------------------------------- the two doors


def authenticating_curator(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Curator:
    """A40. The curator behind this request, with a must-change credential still allowed through.

    HTTP Basic, over loopback (C-05: eigentliCH runs locally and this surface is not on the public web). The
    401 carries no detail about which half was wrong, for the reason `services/auth.py` gives: who curates
    for eigentliCH is not a fact to be enumerated at a login prompt.

    Exactly two routes take this: the login, and the password change. Anything else takes
    `current_curator`, which is this plus the refusal — the same split `api/auth.py` draws for members, and
    for the same reason: the routes that let someone out of the must-change state cannot themselves be
    inside it.
    """
    if not authorization or not authorization.lower().startswith("basic "):
        raise HTTPException(
            401,
            "a curator must authenticate. A40: curators have their own login, in their own table.",
            headers={"WWW-Authenticate": 'Basic realm="eigentliCH curator"'},
        )
    try:
        raw = base64.b64decode(authorization.split(None, 1)[1], validate=True).decode("utf-8")
        email, password = raw.split(":", 1)
    except (ValueError, binascii.Error, UnicodeDecodeError) as bad:
        raise HTTPException(401, "malformed credentials") from bad

    try:
        return authenticate_curator(session, email=email, password=password)
    except CuratorAuthenticationFailed as refused:
        raise HTTPException(
            401,
            str(refused),
            headers={"WWW-Authenticate": 'Basic realm="eigentliCH curator"'},
        ) from refused


def current_curator(curator: Curator = Depends(authenticating_curator)) -> Curator:
    """**The** curator of this request. Every workbench route under this prefix takes this.

    The one thing it adds to `authenticating_curator` is A43's refusal, and it lives here rather than in
    each route for the reason `api/auth.py` gives about the member's copy: two lists that must agree and
    are maintained separately is the A73 shape.

    No second database read. `authenticating_curator` has already loaded the row, and the flag is a column
    on it — unlike the member's, where the credential is a different table from the member.
    """
    if curator.must_change:
        # 403, not 401: the credential is correct and the curator is who they say. What is wrong is the
        # state of the account, and a 401 would tell a client to ask for the password again — which would
        # loop, because the password it would be given is the one that may not be used.
        raise HTTPException(403, CURATOR_MUST_CHANGE_REFUSED)
    return curator


# R-213's member door is `api.auth.current_member`, imported above rather than reimplemented here.
#
# **This module used to own a second copy of it**, and for a while it was the only place in the
# application that read a session token at all — every other member route took `member_id` from the
# caller. When A11 was wired on 31 August 2026 the choice was one dependency or two, and two lists that
# must agree and are maintained separately is the A73 shape: the must-change refusal, the WWW-Authenticate
# header and the wording of the 401 would have had to be kept in step by hand. There is one now, and
# `test_api_auth.py::test_only_one_module_reads_a_session_token` fails if a third appears.


def _refusal(error: AccessDenied) -> HTTPException:
    """R-210. 403 with the reason, never 200 with less.

    Not a 404 either: pretending the member does not exist would hide a refusal behind a different lie,
    and the curator needs to know the difference between "wrong id" and "she has not shared that".
    """
    return HTTPException(403, str(error))


# ---------------------------------------------------------------- curator identity


@router.post("/login")
def curator_login(curator: Curator = Depends(authenticating_curator)) -> dict:
    """A40. Verifies the credentials and returns the identity. Issues no token — see the module docstring.

    Useful to a workbench client that wants to fail at a login form rather than on the first data request.

    **Readable while `must_change` is set**, which is why it takes `authenticating_curator`. The reasoning is
    `api/auth.py`'s about `GET /api/session`: a client that could not ask who it was would have to decide
    which screen to show from a status code, and the screen it has to show is the password change.

    `session_token` is `None` and is stated rather than omitted, so a client reading this payload is told
    there is no token rather than left to notice the absence of a field.
    """
    return {
        "id": curator.id,
        "display_name": curator.display_name,
        "email": curator.email,
        # C-10 records the identified curator. The role label is an overlay on that, not a substitute.
        "role_label": curator.role_label,
        "fictional": curator.fictional,
        # A43 / A53. While this is true the credential opens this route and the password change; every
        # other route under this prefix answers 403 with CURATOR_MUST_CHANGE_REFUSED.
        "must_change": bool(curator.must_change),
        "session_token": None,
        "note": "Each request re-authenticates. There is no curator token table — see services/curator.py.",
    }


class CuratorPasswordChangeRequest(BaseModel):
    current: str = Field(..., min_length=1, max_length=1024)
    new: str = Field(..., min_length=1, max_length=1024)


@router.post("/password")
def change_own_curator_password(
    body: CuratorPasswordChangeRequest,
    curator: Curator = Depends(authenticating_curator),
    session: Session = Depends(get_session),
) -> dict:
    """A40 / A43 / A53. A curator changing their own password, mirroring `POST /api/password`.

    **The current password is required in the body even though Basic has already carried one.** That looks
    redundant and is not, for two reasons. The first is the member route's: `must_change` means someone else
    set this password and the person at the keyboard is supposed to know it, so the change is gated on
    knowing it rather than on holding it. The second is specific to Basic — a browser or a proxy that has
    cached an `Authorization` header replays it without anybody typing anything, and a route that took the
    header as the whole proof would let a cached header rewrite the password. The body field is the one
    part of this request that only a person can supply.

    **This route is why the seeded curator passwords are honest.** `tools/seed_demo_accounts.py` prints
    "each good for ONE login" under all five real curators; without a way to clear the flag that line was
    describing behaviour no code implemented.

    No `curator_id` field. The subject of the change is the authenticated credential, so this route cannot
    be aimed at a colleague.
    """
    try:
        change_curator_password(session, curator_id=curator.id, current=body.current, new=body.new)
    except CuratorAuthenticationFailed as refused:
        # 403, not 401: the credential in the header is valid and the curator is who they say. A 401 here
        # would tell the client the whole credential was wrong, and it would ask for it again — when what
        # is wrong is the `current` field of the body.
        raise HTTPException(403, "current password is incorrect") from refused
    except WeakPassword as weak:
        raise HTTPException(422, str(weak)) from weak
    session.commit()
    return {"id": curator.id, "must_change": False}


@router.get("/members")
def curator_members(
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """The worklist: members who have granted this curator something, and what.

    Composed from live grants only, so a member who revoked disappears from it on the same read that would
    refuse the underlying data.
    """
    return {
        "curator_id": curator.id,
        "members": members_with_live_access(session, curator_id=curator.id),
    }


# ---------------------------------------------------------------- R-210: the gated reads


@router.get("/members/{member_id}")
def workbench(
    member_id: str,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """S-12. The workbench for one member: what was granted, and what was explicitly not."""
    try:
        return curator_workbench(session, member_id=member_id, curator_id=curator.id)
    except AccessDenied as denied:
        raise _refusal(denied) from denied


def _gated(reader):
    def route(
        member_id: str,
        curator: Curator = Depends(current_curator),
        session: Session = Depends(get_session),
    ) -> dict:
        try:
            return reader(session, member_id=member_id, curator_id=curator.id)
        except AccessDenied as denied:
            raise _refusal(denied) from denied

    return route


#: Registered through one factory so no route can be added by hand without the gate and the 403. The
#: service refuses either way — this only removes the chance to write a fifth route that forgets to
#: translate the refusal into a status code.
for _path, _reader in (
    ("positions", curator_view_positions),
    ("goals", curator_view_goals),
    ("vault", curator_view_vault),
    ("decisions", curator_view_decisions),
    ("actions", curator_view_action_items),
):
    router.add_api_route(
        f"/members/{{member_id}}/{_path}",
        _gated(_reader),
        methods=["GET"],
        name=f"curator_view_{_path}",
        summary=f"R-210: the member's {_path}, only under a live grant covering it",
    )


# ---------------------------------------------------------------- R-211 / C-10: sessions


class OpenSessionRequest(BaseModel):
    member_id: str
    #: R-173. Which screen this was opened from. Recorded at the time or not at all.
    opened_from: str = Field(..., min_length=1, max_length=120)


@router.post("/workbench/sessions", status_code=201)
def open_workbench_session(
    body: OpenSessionRequest,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """R-211 / C-10. The workbench's own opener, distinct from the member-side Curator button.

    A separate path from `POST /api/curator/sessions` (which `main.py` owns, and which the member's Know
    panel calls) because the two record different things: that one is a member asking for a human, this
    one is a curator starting work. Both write an `opened` event.
    """
    record = open_session(
        session, member_id=body.member_id, curator_id=curator.id, opened_from=body.opened_from
    )
    session.commit()
    return {
        "id": record.id,
        "member_id": record.member_id,
        "curator_id": record.curator_id,
        "opened_from": record.opened_from,
        "opened_at": record.opened_at.isoformat(),
    }


@router.get("/sessions")
def list_sessions(
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """R-211. The curator's own consultations, so an open one can be found and closed."""
    return {"curator_id": curator.id, "sessions": sessions_for_curator(session, curator_id=curator.id)}


@router.get("/members/{member_id}/sessions/{session_id}")
def read_session(
    member_id: str,
    session_id: str,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """R-211 / C-10. Entry point, every event, and the outcome.

    Note bodies are redacted without a live grant — the audit stays legible after a revocation, the
    member's words do not. `notes_readable` says which of the two you are looking at.
    """
    try:
        return session_record(
            session, session_id=session_id, member_id=member_id, curator_id=curator.id
        )
    except AccessDenied as denied:
        raise _refusal(denied) from denied
    except NoOpenSession as missing:
        raise HTTPException(404, str(missing)) from missing


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/members/{member_id}/sessions/{session_id}/notes", status_code=201)
def add_note(
    member_id: str,
    session_id: str,
    body: NoteRequest,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """C-10. Appended to the audit table, which refuses UPDATE and DELETE by trigger.

    Gated: a note about a member, written while reading their vault, is the member's material.
    """
    try:
        event = record_note(
            session, session_id=session_id, member_id=member_id, curator_id=curator.id, text=body.text
        )
    except AccessDenied as denied:
        raise _refusal(denied) from denied
    except SessionAlreadyClosed as closed:
        raise HTTPException(409, str(closed)) from closed
    except NoOpenSession as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return {"id": event.id, "kind": event.kind, "at": event.at.isoformat()}


class CloseSessionRequest(BaseModel):
    #: R-211. The outcome is what makes the session accounted for; there is no default.
    outcome: str = Field(..., min_length=1, max_length=400)
    liability_flag: bool | None = None
    note: str | None = None


@router.post("/members/{member_id}/sessions/{session_id}/close")
def close(
    member_id: str,
    session_id: str,
    body: CloseSessionRequest,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """R-211 / C-10. Closing appends an event. Nothing on `curator_sessions` is updated.

    Not grant-gated on purpose: a member revoking mid-consultation must not be able to leave the audit
    trail open. See `services.curator.close_session`.
    """
    try:
        event = close_session(
            session,
            session_id=session_id,
            curator_id=curator.id,
            outcome=body.outcome,
            liability_flag=body.liability_flag,
            note=body.note,
        )
    except SessionAlreadyClosed as closed:
        raise HTTPException(409, str(closed)) from closed
    except NoOpenSession as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return {
        "session_id": session_id,
        "member_id": member_id,
        "closed_at": event.at.isoformat(),
        "outcome": (event.detail or {}).get("outcome"),
        "appended": True,
    }


# ---------------------------------------------------------------- R-212 / C-01: the recommendation


class RecommendationRequest(BaseModel):
    session_id: str
    question: str = Field(..., min_length=1, max_length=1000)
    choice: str = Field(..., min_length=1, max_length=2000)
    reasoning: str | None = None
    options_considered: list[dict] = Field(default_factory=list)
    position_ids: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)


@router.post("/members/{member_id}/recommendations", status_code=201)
def make_recommendation(
    member_id: str,
    body: RecommendationRequest,
    curator: Curator = Depends(current_curator),
    session: Session = Depends(get_session),
) -> dict:
    """R-212 / C-01 / C-09. A curator's recommendation, written as a Decision attributed to them.

    **`author_ref` comes from the authenticated curator, never from the request body.** That is the whole
    of C-01's second half here: the licensed human may recommend, and there must be no way for a caller to
    write a curator-attributed Decision without being that curator.
    """
    try:
        decision = recommend(
            session,
            session_id=body.session_id,
            member_id=member_id,
            curator_id=curator.id,
            question=body.question,
            choice=body.choice,
            options_considered=body.options_considered,
            reasoning=body.reasoning,
            position_ids=body.position_ids,
            goal_ids=body.goal_ids,
        )
    except AccessDenied as denied:
        raise _refusal(denied) from denied
    except SessionAlreadyClosed as closed:
        raise HTTPException(409, str(closed)) from closed
    except NoOpenSession as missing:
        raise HTTPException(
            422,
            f"R-211: a recommendation is made inside a recorded curator session. {missing}",
        ) from missing
    session.commit()
    return {
        "id": decision.id,
        "author": decision.author,
        "author_ref": decision.author_ref,
        "curator_session_id": decision.curator_session_id,
        "linked_position_ids": decision.linked_position_ids,
        "linked_goal_ids": decision.linked_goal_ids,
    }


# ---------------------------------------------------------------- R-210 / R-213: the member's control


class GrantRequest(BaseModel):
    curator_id: str
    #: R-210 "scoped". An explicit list; there is no "everything" value.
    scope: list[str] = Field(..., min_length=1)
    #: R-210 "time-limited". Hours, because a grant is a consultation window rather than a subscription.
    #: Omitted means `DEFAULT_GRANT_LIFETIME`; there is no way to say "no expiry".
    hours: float | None = None
    curator_session_id: str | None = None


@router.post("/grants", status_code=201)
def create_grant(
    body: GrantRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-210. The member opens a scoped, time-limited window. Authenticated as the member, always."""
    if body.hours is not None and body.hours <= 0:
        raise HTTPException(422, "a grant lasting no time is a refusal wearing a grant's clothes")
    try:
        grant = grant_access(
            session,
            member_id=member.id,
            curator_id=body.curator_id,
            scope=body.scope,
            lifetime=timedelta(hours=body.hours) if body.hours else None,
            curator_session_id=body.curator_session_id,
        )
    except UnknownScope as bad:
        raise HTTPException(422, str(bad)) from bad
    except CuratorAuthenticationFailed as missing:
        raise HTTPException(422, str(missing)) from missing
    session.commit()
    return {
        "id": grant.id,
        "curator_id": grant.curator_id,
        "scope": grant.scope,
        "granted_at": grant.granted_at.isoformat(),
        "expires_at": grant.expires_at.isoformat(),
        "grantable": list(GRANTABLE),
        "revoke": {"method": "DELETE", "href": f"/api/curator/grants/{grant.id}"},
    }


@router.get("/grants")
def my_grants(
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-213 needs the member to be able to see what is open before they can withdraw it."""
    rows = session.execute(
        select(AccessGrant).where(AccessGrant.member_id == member.id)
    ).scalars().all()
    return {
        "member_id": member.id,
        "grants": [
            {
                "id": g.id,
                "curator_id": g.curator_id,
                "scope": g.scope,
                "granted_at": g.granted_at.isoformat(),
                "expires_at": g.expires_at.isoformat(),
                # Revocation is a timestamp, never a delete: a withdrawn grant stays visible as withdrawn.
                "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
                "live": is_live(g),
            }
            for g in rows
        ],
    }


@router.delete("/grants/{grant_id}")
def delete_grant(
    grant_id: str,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-213. Immediate effect: the next read by that curator refuses, not at expiry.

    Named `delete` by HTTP and implemented as a timestamp. The verb is the member's intent; the row is the
    evidence that access existed, and that evidence is not the member's to destroy or ours to lose.
    """
    try:
        grant = revoke_grant(session, grant_id=grant_id, member_id=member.id)
    except AccessDenied as denied:
        raise HTTPException(404, str(denied)) from denied
    session.commit()
    return {
        "id": grant.id,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "live": is_live(grant),
        "deleted": False,
        "note": "R-213: revocation is a timestamp. The record that access existed is kept.",
    }


@router.delete("/sessions/{session_id}/grant")
def delete_session_grant(
    session_id: str,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """§6's shape: the member revokes everything opened for one consultation, in one action.

    Returns how many were closed. Zero is a legitimate answer — nothing was open — and is reported as a
    count rather than as an error, because a member pressing this twice has done nothing wrong.
    """
    closed = revoke_session_grants(session, curator_session_id=session_id, member_id=member.id)
    session.commit()
    return {"curator_session_id": session_id, "revoked": closed, "deleted": False}


@router.get("/grantable")
def grantable() -> dict:
    """R-210's scope vocabulary, so a client renders the member's choices rather than inventing them."""
    return {
        "grantable": list(GRANTABLE),
        "default_lifetime_hours": 24,
        "note": "R-210: a grant is scoped and time-limited. There is no 'all' and no 'until revoked'.",
    }


__all__ = [
    "CURATOR_MUST_CHANGE_REFUSED",
    "authenticating_curator",
    "current_curator",
    "current_member",
    "router",
]
