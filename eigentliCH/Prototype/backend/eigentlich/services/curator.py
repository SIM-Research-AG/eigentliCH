"""S-12, the Curator Workbench: the curator-side surface, and the refusals that make it safe.

**The whole module is built around one function.** `require_grant` is the gate, and every function here
that returns a member's material calls it first. R-210 says a curator sees the vault, positions, goals and
decisions *only after the member grants access, scoped and time-limited* — so there is no read path that
does not consult `AccessGrant.covers(...)`, and `MEMBER_READS` below names every one of them so a test can
enumerate them rather than trusting a reviewer to notice a new one.

**A refusal raises; it never returns empty.** An empty list is indistinguishable from "this member has no
positions", and that ambiguity hides the refusal from the curator, from the member and from anyone reading
the record afterwards. `AccessDenied` carries which scope was missing and what is actually live.

**R-213: revocation is immediate, and it is a timestamp.** `revoke_grant` sets `revoked_at` and flushes.
The very next `require_grant` fails, because `AccessGrant.is_live()` checks revocation before expiry — the
member's withdrawal is the stronger fact. Nothing is deleted: an audit has to show that access existed and
was withdrawn, and a deleted row shows neither.

**R-211 / C-10: closing a session appends, it never updates.** `CuratorSession` holds what is known at open
time; `close_session` writes a `closed` event into `curator_session_events`, which the database refuses to
UPDATE or DELETE by trigger. `CuratorSession.closed_at` and `.outcome` are derived from that event — see
the note in `models/curator.py` for why the split exists.

**R-212 / C-01: a curator may recommend, and the record says who did.** That is the point of the licensed
human: C-01 forbids *the application* from selecting or ranking for an identified member, not the curator.
So `recommend` exists — and it goes through `services.plan.mutate_plan` with `author="curator"` and
`author_ref` set to the curator's id, because a decision attributed to "a curator" is not attributed. It
refuses unless the curator row exists and is active, holds an open session with this member, and has a
live grant. There is deliberately no path by which an unauthenticated caller writes a curator-attributed
Decision.

**A40: curators have their own login, in their own table.** `authenticate_curator` mirrors
`services/auth.py` — PBKDF2-HMAC-SHA256 with the iteration count stored per row, a constant-time compare,
and a throwaway derivation when the address is unknown so a wrong address and a wrong password take
comparable time.

**A43: an operator reset for curators is `reset_curator_password`, exposed here and given no CLI.**
`eigentlich/reset.py` is the pattern to copy if one is wanted: a command run on the machine, authenticated
by having the machine, printing the new password once because there is nowhere to send it. It is not
written yet because no curator has needed one, and an unused command path is a second thing to keep
correct.

**No curator token table, and that is a deliberate interim.** A member's `Session` table is keyed to
`members.id` and cannot hold a curator; a curator equivalent is a migration, and phase 5 does not own one.
So the HTTP surface re-authenticates the curator on every request. The cost is one PBKDF2 derivation per
call, which a workbench used by a handful of staff can pay, and the benefit is that there is no bearer
token for a curator to leave in a browser pointed at other people's K3.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import auth as auth_models
from ..models import (
    AccessGrant,
    ActionItem,
    Curator,
    CuratorSession,
    CuratorSessionEvent,
    Decision,
    GRANTABLE,
    Goal,
    Position,
    utcnow,
)
from ..models.auth import MINIMUM_PASSWORD_LENGTH, WeakPassword
from .goals import list_goals
from .grid import role_grid
from .plan import mutate_plan
from .vault import current_items

#: How long a grant runs when the member does not say. R-210 requires "time-limited", and a grant with no
#: end is not time-limited — so there is no "until revoked" option and no `None`. Not a tuned security
#: parameter, the same kind of plain default `SESSION_LIFETIME` is in `models/auth.py`; a member who wants
#: longer passes `expires_at`, and a member who wants it gone uses `revoke_grant`.
DEFAULT_GRANT_LIFETIME = timedelta(hours=24)

#: Every function in this module that touches a member's material, and the scope each one needs. Every
#: entry here RAISES `AccessDenied` without a live covering grant — none of them returns an empty result.
#:
#: **This mapping is the point of phase 5.** `test_every_member_read_refuses_without_a_grant` iterates it,
#: and a companion test fails if a function taking both `member_id` and `curator_id` is not classified in
#: exactly one of the three tables below. A read path added later cannot quietly avoid the gate: it has to
#: be classified, in this file, by whoever adds it.
MEMBER_READS: dict[str, str] = {
    "curator_view_positions": "positions",
    "curator_view_goals": "goals",
    "curator_view_vault": "vault",
    "curator_view_decisions": "decisions",
    "curator_view_action_items": "action_items",
    #: The composite. Needs no particular scope, but refuses outright when nothing is granted.
    "curator_workbench": "*",
    #: Writes, gated the same way: a note or a recommendation about a member is member material.
    "record_note": "*",
    "recommend": "decisions",
}

#: Functions where part of the payload is gated and part is not, with the reason. Kept separate from
#: `MEMBER_READS` so that "every entry raises" stays a true statement about that table rather than a rule
#: with an exception in it — an exception nobody would notice growing a second member.
PARTIALLY_GATED: dict[str, str] = {
    "session_record": (
        "C-10 outranks R-210 for the audit metadata: entry point, times and outcome stay legible after a "
        "revocation, or an audit trail could be closed off by withdrawing consent. The note bodies are "
        "the member's material and are replaced by an explicit redaction marker without a live grant."
    ),
}

#: Functions that legitimately take both ids and return nothing of the member's. Listed so the guard test
#: can tell "checked and safe" apart from "not thought about".
NOT_MEMBER_READS: frozenset[str] = frozenset({
    "grant_access",
    "revoke_grant",
    "revoke_all_grants",
    "revoke_session_grants",
    "live_grants",
    "granted_scopes",
    "require_grant",
    "open_session",
})


class AccessDenied(Exception):
    """R-210. No live grant covers this.

    Raised rather than returning an empty result, because an empty result is indistinguishable from "no
    data" and hides the refusal from everyone who would need to see it.
    """


class CuratorAuthenticationFailed(Exception):
    """Wrong address, wrong password, no such curator, or a deactivated one — indistinguishable."""


class SessionAlreadyClosed(Exception):
    """C-10. A session closes once. A second closure would make "the outcome" ambiguous."""


class NoOpenSession(Exception):
    """R-211. A curator acts inside a recorded session or not at all."""


class UnknownScope(ValueError):
    """A grant may only cover what `GRANTABLE` names. A scope nothing checks is a scope that grants all."""


# ==================================================================== A40: curators log in as curators


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def set_curator_password(curator: Curator, password: str) -> None:
    """The hashing half of A11, applied to the curator table.

    Not a method on the model: `Curator` is shared with phases 7 and 8 and its migration is already
    applied, so the behaviour goes where behaviour goes. `PBKDF2_ITERATIONS` is read off the module at call
    time rather than imported by value, so a test lowering it lowers it here too.
    """
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPassword(
            f"a password of at least {MINIMUM_PASSWORD_LENGTH} characters is required. Length is the "
            f"only rule here: composition rules produce shorter, more guessable passwords."
        )
    curator.password_salt = secrets.token_bytes(auth_models.SALT_BYTES)
    curator.iterations = auth_models.PBKDF2_ITERATIONS
    curator.password_hash = auth_models.Credential.derive(
        password, curator.password_salt, curator.iterations
    )


def verify_curator_password(curator: Curator, password: str) -> bool:
    """Constant-time. A timing difference on a staff login is a real oracle, not a theoretical one."""
    if not curator.password_hash or not curator.password_salt or not curator.iterations:
        return False
    candidate = auth_models.Credential.derive(password, curator.password_salt, curator.iterations)
    return hmac.compare_digest(candidate, curator.password_hash)


def create_curator(
    db: DbSession,
    *,
    display_name: str,
    email: str,
    password: str,
    role_label: str | None = None,
    fictional: bool = False,
) -> Curator:
    """A40. Staff, in the staff table, with a login of their own.

    A curator logging in on a member credential would make C-10's "who" ambiguous, which is the whole
    reason `Curator` is not a flag on `Member`.
    """
    address = _normalise_email(email)
    existing = db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none()
    if existing is not None:
        raise CuratorAuthenticationFailed(f"{address} is already a curator")

    curator = Curator(
        display_name=display_name,
        email=address,
        role_label=role_label,
        fictional=fictional,
        active=True,
    )
    set_curator_password(curator, password)
    db.add(curator)
    db.flush()
    return curator


def authenticate_curator(db: DbSession, *, email: str, password: str) -> Curator:
    """A40 / C-01. The identified curator behind a request, or a refusal.

    Mirrors `services.auth.login` deliberately, including the throwaway derivation when the address is
    unknown: without it the endpoint answers "is this person a curator" by stopwatch, and who curates for
    eigentliCH is not a fact given away at a login form.

    Returns the `Curator` rather than a session row, because there is no curator token table — see the
    module docstring. Callers hold the object for the length of one request.
    """
    address = _normalise_email(email)
    curator = db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none()

    if curator is None:
        auth_models.Credential.derive(password, b"\x00" * 16, 1000)
        raise CuratorAuthenticationFailed("email or password is incorrect")

    if not verify_curator_password(curator, password):
        raise CuratorAuthenticationFailed("email or password is incorrect")

    if not curator.in_service:
        # The same message. A deactivated or revoked curator learning that their account still exists is a
        # small disclosure with no upside, and the caller needs the same answer either way: not you.
        #
        # A160 put revocation behind the same clause rather than beside it. The password is deliberately
        # left intact on a revoked row — it is not a second lock, and clearing it would make the refusal
        # depend on which of two mechanisms happened to fire.
        raise CuratorAuthenticationFailed("email or password is incorrect")

    return curator


def reset_curator_password(db: DbSession, *, email: str, new_password: str) -> Curator:
    """A43, for staff. The operator has the machine, so a reset is performed rather than emailed.

    Exposed as a function and deliberately not given a command of its own yet. `eigentlich/reset.py` is the
    pattern to copy if a curator reset is wanted: `python -m eigentlich.reset`, authenticated by having the
    machine, printing the new password once because there is nowhere to send it.

    Unlike the member reset there is nothing to revoke — a curator holds no session rows, because there is
    no curator token table. That is the interim in the module docstring showing its one benefit.
    """
    address = _normalise_email(email)
    curator = db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none()
    if curator is None:
        raise CuratorAuthenticationFailed(f"no curator for {address}")
    set_curator_password(curator, new_password)
    curator.must_change = True
    return curator


def change_curator_password(db: DbSession, *, curator_id: str, current: str, new: str) -> Curator:
    """A curator changing their own password. **The current one is required even when must_change is set.**

    Mirrors `services.auth.change_password` field for field, and the mirroring is the point: `must_change`
    means either an operator set this password (A43) or it is a documented seeded credential (A53), and in
    both cases the person at the keyboard is supposed to know it. The member route keeps that rule and so
    does this one — a curator path that waived it would be the weaker of the two doors, on the table that
    reaches other people's material.

    **Without this function `Curator.must_change` was a flag nothing could ever clear.** All five real
    curators are seeded with it set and their documented password described as good for one login; there
    was no service, no route and no screen by which any of them could choose a second one, so the
    documented password never stopped working. The field's own comment says it exists because printing
    "good for one login" beside a password that never expires is a false statement on an operator's
    terminal. It was still false until this landed.

    Takes the curator's **id**, not their email: the caller is a route that has already authenticated, and
    an email parameter would be a second way to name the subject of the change. `reset_curator_password`
    takes an address because its caller is an operator who has one and no session.
    """
    curator = db.get(Curator, curator_id)
    if curator is None or not verify_curator_password(curator, current):
        # Deliberately one message for "no such curator" and "wrong password", the same way
        # `authenticate_curator` refuses. A caller holding a valid credential for curator A must not be
        # able to learn whether id B exists by aiming this at it.
        raise CuratorAuthenticationFailed("current password is incorrect")

    # `set_curator_password` raises WeakPassword below the length floor, before anything is written.
    set_curator_password(curator, new)
    curator.must_change = False
    return curator


def revoke_curator(db: DbSession, *, email: str, reason: str, at: datetime | None = None) -> Curator:
    """A160. This person is no longer a curator. The row stays; the access goes.

    **Not a delete, and the reason is C-10 rather than sentiment.** `curator_session_events` refuses
    DELETE by trigger and `CuratorSession.curator_id` has been a foreign key since A98, so removing the
    row either fails outright or — if the constraint were ever relaxed — leaves an append-only audit
    naming someone who cannot be looked up. The audit's whole value is that "a named curator did this" can
    be checked afterwards by someone who was not there.

    **`reason` is required by this function and not by the column.** A nullable column with a caller that
    insists is the shape used elsewhere in this build for the same purpose: the store stays able to hold a
    row written by a migration or a repair, and the one supported path refuses to make a revocation
    nobody can account for. Rule 5 of the cull — a closed item with a record beats a quiet deletion.

    Idempotent on purpose. Revoking twice keeps the first timestamp, because the date this person stopped
    being a curator is a fact about them and not about how many times the script was run.
    """
    address = _normalise_email(email)
    curator = db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none()
    if curator is None:
        raise CuratorAuthenticationFailed(f"no curator for {address}")
    if not reason or not reason.strip():
        raise ValueError(
            "a revocation carries its reason. A curator row that says access ended but not why is the "
            "quiet deletion that revoking instead of deleting exists to avoid."
        )
    if curator.revoked_at is None:
        curator.revoked_at = at or utcnow()
        curator.revoked_reason = reason.strip()
    db.flush()
    return curator


def require_curator(db: DbSession, curator_id: str) -> Curator:
    """The curator row behind an id, active, or a refusal.

    Every attributed write goes through here. C-01's rule is not that a curator may not recommend — it is
    that the Decision must record whose recommendation it was, and an id naming no row records nothing.
    """
    curator = db.get(Curator, curator_id)
    if curator is None:
        raise CuratorAuthenticationFailed(f"no curator {curator_id!r}")
    if not curator.in_service:
        raise CuratorAuthenticationFailed(f"curator {curator_id!r} is not in service")
    return curator


# ==================================================================== R-210 / R-213: the grant


def grant_access(
    db: DbSession,
    *,
    member_id: str,
    curator_id: str,
    scope: Sequence[str],
    expires_at: datetime | None = None,
    lifetime: timedelta | None = None,
    curator_session_id: str | None = None,
    at: datetime | None = None,
) -> AccessGrant:
    """R-210. The member opens a window: scoped, time-limited, and recorded.

    The scope is validated against `GRANTABLE` rather than stored as given. An unrecognised scope name is
    a scope nothing checks, and a scope nothing checks is indistinguishable from full access — so it is
    refused here rather than silently ignored at read time.

    An empty scope is refused too. A grant covering nothing is not a safe grant, it is a confusing one:
    the curator sees refusals and the member believes access was given.
    """
    unknown = [name for name in scope if name not in GRANTABLE]
    if unknown:
        raise UnknownScope(
            f"unknown scope {unknown!r}; R-210's scope is an explicit list drawn from {list(GRANTABLE)}. "
            f"A name nothing checks would be indistinguishable from full access."
        )
    if not scope:
        raise UnknownScope(
            "a grant covering nothing is not a grant. Name what the curator may see, or do not grant."
        )

    require_curator(db, curator_id)

    now = at or utcnow()
    ends = expires_at or (now + (lifetime or DEFAULT_GRANT_LIFETIME))
    if ends <= now:
        raise UnknownScope(
            "a grant that has already expired cannot be created. R-210 is a window, not a formality."
        )

    grant = AccessGrant(
        member_id=member_id,
        curator_id=curator_id,
        # De-duplicated, order preserved. A repeated scope is a payload quirk, not a stronger grant.
        scope=list(dict.fromkeys(scope)),
        granted_at=now,
        expires_at=ends,
        curator_session_id=curator_session_id,
    )
    db.add(grant)
    db.flush()

    if curator_session_id is not None:
        _append_event(
            db,
            session_id=curator_session_id,
            kind="granted",
            actor=f"member:{member_id}",
            detail={"grant_id": grant.id, "scope": grant.scope, "expires_at": ends.isoformat()},
        )
    return grant


def revoke_grant(
    db: DbSession, *, grant_id: str, member_id: str, at: datetime | None = None
) -> AccessGrant:
    """R-213. The member withdraws, and it takes effect on the next read rather than at expiry.

    `member_id` is required and checked. Revocation belongs to the member: a curator who could revoke
    their own grant could also close the record of having held it at a moment of their choosing.

    The row is flushed, not deleted. `is_live()` checks `revoked_at` before `expires_at`, so the very next
    `require_grant` — in this same transaction — refuses.
    """
    grant = db.get(AccessGrant, grant_id)
    if grant is None or grant.member_id != member_id:
        # Not "no such grant": the two cases get the same refusal, because distinguishing them would let
        # one member probe for another's grants by id.
        raise AccessDenied(f"no grant {grant_id!r} belonging to this member")

    if grant.revoked_at is None:
        grant.revoked_at = at or utcnow()
        db.flush()
        if grant.curator_session_id:
            _append_event(
                db,
                session_id=grant.curator_session_id,
                kind="revoked",
                actor=f"member:{member_id}",
                detail={"grant_id": grant.id, "scope": grant.scope},
            )
    return grant


def revoke_all_grants(
    db: DbSession, *, member_id: str, curator_id: str | None = None, at: datetime | None = None
) -> int:
    """R-213 in one action: everything, or everything held by one curator. Returns how many were closed."""
    query = select(AccessGrant).where(
        AccessGrant.member_id == member_id, AccessGrant.revoked_at.is_(None)
    )
    if curator_id is not None:
        query = query.where(AccessGrant.curator_id == curator_id)

    closed = 0
    for grant in db.execute(query).scalars().all():
        revoke_grant(db, grant_id=grant.id, member_id=member_id, at=at)
        closed += 1
    return closed


def revoke_session_grants(
    db: DbSession, *, curator_session_id: str, member_id: str, at: datetime | None = None
) -> int:
    """Every grant opened for one consultation. §6's `DELETE /api/curator/sessions/:id/grant`."""
    grants = db.execute(
        select(AccessGrant).where(
            AccessGrant.curator_session_id == curator_session_id,
            AccessGrant.member_id == member_id,
            AccessGrant.revoked_at.is_(None),
        )
    ).scalars().all()
    for grant in grants:
        revoke_grant(db, grant_id=grant.id, member_id=member_id, at=at)
    return len(grants)


def _aligned_now(grant: AccessGrant, at: datetime | None = None) -> datetime:
    """The clock to hand `is_live()`, matched to the awareness of the row it will be compared against.

    **A real trap, not a formality.** SQLite has no timezone type: `DateTime(timezone=True)` writes the
    UTC instant and drops the offset, so a grant still in the identity map comes back *aware* and the same
    grant re-loaded from disk comes back *naive*. `expires_at > now` then raises `TypeError` — and it does
    so on the read path, meaning the failure mode is a crash that looks like a bug rather than a refusal.

    Aligning here rather than in the model is deliberate: `AccessGrant.is_live()` stays the one definition
    of live, this only makes sure it is asked a question it can answer. Both values are UTC either way —
    the offset is the only thing SQLite discarded.
    """
    now = at or utcnow()
    reference = grant.expires_at
    if reference is None:
        return now
    if reference.tzinfo is None and now.tzinfo is not None:
        return now.replace(tzinfo=None)
    if reference.tzinfo is not None and now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def is_live(grant: AccessGrant, *, at: datetime | None = None) -> bool:
    """`AccessGrant.is_live()`, asked with a comparable clock. The model decides; this only aligns."""
    return grant.is_live(at=_aligned_now(grant, at))


def covers(grant: AccessGrant, what: str, *, at: datetime | None = None) -> bool:
    """`AccessGrant.covers()`, asked with a comparable clock. Every gated read arrives here."""
    return grant.covers(what, at=_aligned_now(grant, at))


def live_grants(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> list[AccessGrant]:
    """Every grant currently open between this member and this curator.

    Liveness is decided by `AccessGrant.is_live()` per row rather than by a SQL predicate, so there is one
    definition of "live" and it is the model's. A `WHERE revoked_at IS NULL AND expires_at > now` here
    would be a second copy of that rule, free to drift from the first.
    """
    rows = db.execute(
        select(AccessGrant).where(
            AccessGrant.member_id == member_id, AccessGrant.curator_id == curator_id
        )
    ).scalars().all()
    return [g for g in rows if is_live(g, at=at)]


def granted_scopes(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> set[str]:
    """The union of what is live. Never used to decide a read — `require_grant` does that, per scope."""
    return {
        name
        for grant in live_grants(db, member_id=member_id, curator_id=curator_id, at=at)
        for name in (grant.scope or [])
    }


def require_grant(
    db: DbSession, *, member_id: str, curator_id: str, scope: str, at: datetime | None = None
) -> AccessGrant:
    """R-210. The gate. Every read path in this module begins here.

    Raises `AccessDenied` naming the scope wanted and the scopes actually live, so a curator staring at a
    refusal can tell "she revoked it" from "she never shared that part" — which is the difference between
    calling her back and calling her out.
    """
    if scope not in GRANTABLE:
        raise UnknownScope(f"{scope!r} is not one of {list(GRANTABLE)}")

    for grant in live_grants(db, member_id=member_id, curator_id=curator_id, at=at):
        if covers(grant, scope, at=at):
            return grant

    have = sorted(granted_scopes(db, member_id=member_id, curator_id=curator_id, at=at))
    raise AccessDenied(
        f"R-210: curator {curator_id!r} has no live grant covering {scope!r} for this member. "
        f"Live scopes: {have or 'none'}. A member grants access; it is not held by being staff. This is a "
        f"refusal rather than an empty result, so it cannot be misread as 'there is no data'."
    )


def _require_any_grant(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> list[AccessGrant]:
    grants = live_grants(db, member_id=member_id, curator_id=curator_id, at=at)
    if not grants:
        raise AccessDenied(
            f"R-210: curator {curator_id!r} holds no live grant for this member. Nothing here is "
            f"readable, and that is said rather than rendered as an empty workbench."
        )
    return grants


# ==================================================================== R-211 / C-10: the session


def _append_event(
    db: DbSession, *, session_id: str, kind: str, actor: str, detail: dict | None = None
) -> CuratorSessionEvent:
    """The only way anything is written to `curator_session_events`. Append; never update.

    Appended through the relationship rather than with `db.add`, so `CuratorSession.closed_at` and
    `.outcome` — which read `self.events` — are correct within the same transaction rather than after a
    refresh.
    """
    record = db.get(CuratorSession, session_id)
    if record is None:
        raise NoOpenSession(f"no curator session {session_id!r}")
    event = CuratorSessionEvent(session_id=session_id, kind=kind, actor=actor, detail=detail)
    record.events.append(event)
    db.flush()
    return event


def open_session(
    db: DbSession, *, member_id: str, curator_id: str, opened_from: str
) -> CuratorSession:
    """R-211 / R-173 / C-10. Entry point recorded at the time, or not at all.

    The workbench's own opener. `services.know.open_curator_session` is the member-side one behind the
    Curator button and takes the id on trust; this one resolves it against the `curators` table first,
    because a workbench session is opened by someone who authenticated as a curator and C-10's "who"
    should be a row rather than a string.
    """
    require_curator(db, curator_id)
    record = CuratorSession(member_id=member_id, curator_id=curator_id, opened_from=opened_from)
    db.add(record)
    db.flush()
    _append_event(
        db,
        session_id=record.id,
        kind="opened",
        actor=curator_id,
        detail={"opened_from": opened_from},
    )
    return record


def require_open_session(db: DbSession, *, session_id: str, curator_id: str) -> CuratorSession:
    """The session a curator is acting inside. R-211 makes this a precondition, not a convenience."""
    record = db.get(CuratorSession, session_id)
    if record is None:
        raise NoOpenSession(f"no curator session {session_id!r}")
    if record.curator_id != curator_id:
        raise NoOpenSession(f"curator session {session_id!r} does not belong to curator {curator_id!r}")
    if record.closed_at is not None:
        raise SessionAlreadyClosed(f"curator session {session_id!r} closed at {record.closed_at}")
    return record


def close_session(
    db: DbSession,
    *,
    session_id: str,
    curator_id: str,
    outcome: str,
    liability_flag: bool | None = None,
    note: str | None = None,
) -> CuratorSessionEvent:
    """R-211 / C-10. The outcome, appended.

    **Nothing on `curator_sessions` is modified.** `closed_at` and `outcome` are derived properties over
    the event log, so closing writes one row into the append-only table and the row opened earlier is left
    exactly as it was written. `liability_flag` travels in the event detail for the same reason: it is
    known at close time, and writing it back onto the open row would be the UPDATE this avoids.

    **Deliberately does NOT require a live grant.** A member who revokes mid-consultation must not thereby
    prevent the session being closed — an audit trail that can be left open by withdrawing consent is an
    audit trail with a hole in it, and C-10 is the stronger claim at this point. `outcome` is a curator's
    account of the consultation, not the member's material, and the free-text `note` is optional.
    """
    record = require_open_session(db, session_id=session_id, curator_id=curator_id)
    if not outcome or not outcome.strip():
        raise ValueError(
            "R-211 records the outcome. An empty one is a session that was had and not accounted for."
        )
    detail: dict = {"outcome": outcome.strip(), "member_id": record.member_id}
    if liability_flag is not None:
        detail["liability_flag"] = bool(liability_flag)
    if note:
        detail["note"] = note
    return _append_event(db, session_id=session_id, kind="closed", actor=curator_id, detail=detail)


def record_note(
    db: DbSession, *, session_id: str, member_id: str, curator_id: str, text: str
) -> CuratorSessionEvent:
    """A curator's note during a consultation. Gated, because a note about a member is member material.

    Free text a curator writes while reading someone's vault is exactly as sensitive as what they read. So
    this needs a live grant like any other member-facing path: a curator whose access lapsed cannot go on
    writing into the record about what they saw.
    """
    _require_any_grant(db, member_id=member_id, curator_id=curator_id)
    record = require_open_session(db, session_id=session_id, curator_id=curator_id)
    if record.member_id != member_id:
        raise AccessDenied(f"curator session {session_id!r} is not about this member")
    return _append_event(
        db, session_id=session_id, kind="note", actor=curator_id, detail={"text": text}
    )


def session_record(
    db: DbSession, *, session_id: str, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-211's session as an audit payload: entry point, every event, and the outcome.

    **The metadata is readable by the owning curator without a grant; the free text inside it is not.**
    Which screen a session was opened from and when it closed are facts about the consultation, and they
    have to stay legible after a member revokes, or the audit could be shut off by withdrawing consent.
    The `note` bodies are the member's material, so without a live grant each is replaced by an explicit
    `redacted` marker rather than dropped — a missing note and a withheld note must not look the same in
    an audit.
    """
    record = db.get(CuratorSession, session_id)
    if record is None:
        raise NoOpenSession(f"no curator session {session_id!r}")
    if record.curator_id != curator_id or record.member_id != member_id:
        raise AccessDenied(
            f"curator session {session_id!r} does not belong to this curator and this member"
        )

    readable = bool(live_grants(db, member_id=member_id, curator_id=curator_id, at=at))

    events = []
    for event in sorted(record.events, key=lambda e: e.at):
        detail = event.detail or {}
        if event.kind == "note" and not readable:
            detail = {"redacted": "R-210: no live grant covers this member's material"}
        events.append(
            {"kind": event.kind, "at": event.at.isoformat(), "actor": event.actor, "detail": detail}
        )

    return {
        "id": record.id,
        "member_id": record.member_id,
        "curator_id": record.curator_id,
        # R-211's two halves. Both derived from the append-only log.
        "opened_from": record.opened_from,
        "opened_at": record.opened_at.isoformat(),
        "closed_at": record.closed_at.isoformat() if record.closed_at else None,
        "outcome": record.outcome,
        "events": events,
        "notes_readable": readable,
    }


def sessions_for_curator(db: DbSession, *, curator_id: str) -> list[dict]:
    """The curator's own history: which consultations they held, when, and how each ended.

    Carries no member material — ids, entry points, timestamps and outcomes — so it is not grant-gated and
    is not in `MEMBER_READS`. It is here so a curator can find a session to close; a workbench that could
    not list its own open sessions would leave them open, which is the thing R-211 is about.
    """
    rows = db.execute(
        select(CuratorSession).where(CuratorSession.curator_id == curator_id)
    ).scalars().all()
    rows.sort(key=lambda r: r.opened_at)
    return [
        {
            "id": r.id,
            "member_id": r.member_id,
            "opened_from": r.opened_from,
            "opened_at": r.opened_at.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "outcome": r.outcome,
        }
        for r in rows
    ]


def members_with_live_access(
    db: DbSession, *, curator_id: str, at: datetime | None = None
) -> list[dict]:
    """The curator's worklist: who has granted them something, and what.

    Composed entirely from live grants, so by construction it names only members who granted — there is no
    member here whose access was not given, and a revoked grant drops out of it on the same read that
    `require_grant` would refuse. Not in `MEMBER_READS` for that reason: the grant is the row, not
    something read from behind one.
    """
    rows = db.execute(
        select(AccessGrant).where(AccessGrant.curator_id == curator_id)
    ).scalars().all()

    by_member: dict[str, dict] = {}
    for grant in rows:
        if not is_live(grant, at=at):
            continue
        entry = by_member.setdefault(
            grant.member_id, {"member_id": grant.member_id, "scope": [], "expires_at": None}
        )
        for name in grant.scope or []:
            if name not in entry["scope"]:
                entry["scope"].append(name)
        ends = grant.expires_at.isoformat()
        if entry["expires_at"] is None or ends > entry["expires_at"]:
            entry["expires_at"] = ends
    for entry in by_member.values():
        entry["scope"].sort()
    return sorted(by_member.values(), key=lambda e: e["member_id"])


# ==================================================================== R-210: the reads, every one gated


def curator_view_positions(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-210. The member's role grid, after `positions` was granted."""
    require_grant(db, member_id=member_id, curator_id=curator_id, scope="positions", at=at)
    return role_grid(db, member_id=member_id)


def curator_view_goals(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-210. The member's containers, after `goals` was granted.

    Reuses `services.goals.list_goals` unchanged, so a curator sees what the member sees — including
    R-113's absence of any funded percentage. A curator-only summary figure would be a number about the
    member's plan that the member cannot see.
    """
    require_grant(db, member_id=member_id, curator_id=curator_id, scope="goals", at=at)
    return list_goals(db, member_id=member_id)


def curator_view_vault(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-210. The vault index, after `vault` was granted.

    **Metadata, never bytes.** The payload names what is held and reports `has_content`; it carries no
    document body, because a K3 file crossing this boundary should be a deliberate and separately recorded
    act rather than a field in a list response. `notes` and `extracted_fields` are included: they are what
    makes the index useful to the human the member asked for.
    """
    require_grant(db, member_id=member_id, curator_id=curator_id, scope="vault", at=at)
    items = current_items(db, member_id=member_id)
    return {
        "member_id": member_id,
        "items": [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "source": item.source,
                "version": item.version,
                "supersedes_id": item.supersedes_id,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "has_content": bool(item.content_hash),
                "extracted_fields": item.extracted_fields or {},
                "notes": item.notes,
            }
            for item in items
        ],
        "content_bytes_included": False,
    }


def curator_view_decisions(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-210. The decision record, after `decisions` was granted.

    Ordered oldest first and carrying `corrects_id`, because R-040 makes the chain the meaning: a
    correction arriving without the record it corrects would read as a contradiction.
    """
    require_grant(db, member_id=member_id, curator_id=curator_id, scope="decisions", at=at)
    rows = db.execute(select(Decision).where(Decision.member_id == member_id)).scalars().all()
    rows.sort(key=lambda d: d.created_at)
    return {
        "member_id": member_id,
        "decisions": [
            {
                "id": d.id,
                "author": d.author,
                # R-212. "a curator" is not an attribution; this is which one.
                "author_ref": d.author_ref,
                "question": d.question,
                "options_considered": d.options_considered,
                "choice": d.choice,
                "reasoning": d.reasoning,
                "curator_session_id": d.curator_session_id,
                "corrects_id": d.corrects_id,
                "linked_position_ids": d.linked_position_ids,
                "linked_goal_ids": d.linked_goal_ids,
                "linked_vault_item_ids": d.linked_vault_item_ids,
                "created_at": d.created_at.isoformat(),
            }
            for d in rows
        ],
    }


def curator_view_action_items(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """R-210 and C-06. Open items with their prepared options, after `action_items` was granted.

    No count and no total (R-003): a curator's view of a member's obligations is a list, for the same
    reason the member's is.
    """
    require_grant(db, member_id=member_id, curator_id=curator_id, scope="action_items", at=at)
    rows = db.execute(
        select(ActionItem).where(ActionItem.member_id == member_id, ActionItem.status == "open")
    ).scalars().all()
    rows.sort(key=lambda r: (r.due_date is None, r.due_date))
    return {
        "member_id": member_id,
        "items": [
            {
                "id": r.id,
                "trigger_kind": r.trigger_kind,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                # C-06: never empty, minimum two, each with its consequence.
                "prepared_options": r.prepared_options,
                "source_vault_item_id": r.source_vault_item_id,
            }
            for r in rows
        ],
    }


#: Which reader serves which scope. Used by the composite below and by the enumeration test.
_READERS = {
    "positions": curator_view_positions,
    "goals": curator_view_goals,
    "vault": curator_view_vault,
    "decisions": curator_view_decisions,
    "action_items": curator_view_action_items,
}


def curator_workbench(
    db: DbSession, *, member_id: str, curator_id: str, at: datetime | None = None
) -> dict:
    """S-12. Everything the member has opened, and an explicit statement of everything they have not.

    **`not_granted` is the point of the payload.** A composite that quietly omitted the ungranted sections
    would render as a member with no goals, which is the ambiguity this whole module refuses. Each withheld
    scope is named, so the workbench shows "she has not shared this" rather than nothing.

    With no live grant at all it raises. There is no read-only preview of a member who has granted nothing.
    """
    _require_any_grant(db, member_id=member_id, curator_id=curator_id, at=at)
    have = granted_scopes(db, member_id=member_id, curator_id=curator_id, at=at)

    sections: dict[str, dict] = {}
    for name, reader in _READERS.items():
        if name in have:
            # Called rather than inlined, so the composite goes through exactly the same gate a direct
            # read does. A shortcut here would be a second read path, and the second one is always the
            # one that forgets.
            sections[name] = reader(db, member_id=member_id, curator_id=curator_id, at=at)

    return {
        "member_id": member_id,
        "curator_id": curator_id,
        "granted_scope": sorted(have),
        # Named, never silently empty.
        "not_granted": sorted(set(GRANTABLE) - have),
        "sections": sections,
        "grants": [
            {
                "id": g.id,
                "scope": g.scope,
                "granted_at": g.granted_at.isoformat(),
                "expires_at": g.expires_at.isoformat(),
                # R-213. The route out travels with the access, so the member is never hunting for it.
                "revoke": {"method": "DELETE", "href": f"/api/curator/grants/{g.id}"},
            }
            for g in live_grants(db, member_id=member_id, curator_id=curator_id, at=at)
        ],
    }


# ==================================================================== R-212 / C-01: the recommendation


def recommend(
    db: DbSession,
    *,
    session_id: str,
    member_id: str,
    curator_id: str,
    question: str,
    choice: str,
    options_considered: Sequence[dict] | None = None,
    reasoning: str | None = None,
    position_ids: Sequence[str] = (),
    goal_ids: Sequence[str] = (),
    at: datetime | None = None,
) -> Decision:
    """R-212 / C-01. The licensed human recommends, and the record says who.

    **C-01 is not breached by this function; it is what C-01 leaves room for.** The constraint forbids *the
    application* selecting, ranking or weighting instruments for an identified member. A curator doing so
    is the reason the handoff in `boundary.py` exists at all. What C-01 requires here is that the result be
    attributable, so `author="curator"` and `author_ref=<curator id>` — never a role label, never "the
    curator team".

    **Four preconditions, and none of them is a UI convention.**
      1. the curator id resolves to an active row in `curators` (A40) — an id naming nothing attributes
         nothing, and an unauthenticated caller has no way to obtain one;
      2. an open `CuratorSession` for this member belongs to this curator (R-211) — a recommendation made
         outside a recorded session would be advice with no audit;
      3. a live grant covers `decisions` (R-210) — writing into a member's record is reading it too;
      4. any position or goal named is the member's own, and its own scope is granted.

    Written through `services.plan.mutate_plan`, so the Decision and anything it touches are one
    transaction. The C-09 guard in `db.py` would refuse the write otherwise, and this function does not
    relax it — it makes the correct path the easy one.
    """
    require_curator(db, curator_id)
    record = require_open_session(db, session_id=session_id, curator_id=curator_id)
    if record.member_id != member_id:
        raise AccessDenied(f"curator session {session_id!r} is not about this member")

    require_grant(db, member_id=member_id, curator_id=curator_id, scope="decisions", at=at)

    positions: list[Position] = []
    if position_ids:
        require_grant(db, member_id=member_id, curator_id=curator_id, scope="positions", at=at)
        for position_id in position_ids:
            position = db.get(Position, position_id)
            if position is None or position.member_id != member_id:
                raise AccessDenied(f"no position {position_id!r} for this member")
            positions.append(position)

    goals: list[Goal] = []
    if goal_ids:
        require_grant(db, member_id=member_id, curator_id=curator_id, scope="goals", at=at)
        for goal_id in goal_ids:
            goal = db.get(Goal, goal_id)
            if goal is None or goal.member_id != member_id:
                raise AccessDenied(f"no goal {goal_id!r} for this member")
            goals.append(goal)

    with mutate_plan(
        db,
        member_id=member_id,
        question=question,
        choice=choice,
        author="curator",
        author_ref=curator_id,
        reasoning=reasoning,
        options_considered=options_considered,
        curator_session_id=session_id,
    ) as decision:
        decision.linked_positions.extend(positions)
        decision.linked_goals.extend(goals)
    db.flush()

    # C-10: the session log carries the recommendation too, so the audit is complete from the session's
    # side as well as the decision's. Someone reading one should never have to know to look at the other.
    _append_event(
        db,
        session_id=session_id,
        kind="note",
        actor=curator_id,
        detail={"recommendation": True, "decision_id": decision.id, "question": question},
    )
    return decision
