"""Registering with credentials, logging in, and the operator reset that replaces a mail flow.

**Why there is no reset token here.** A43: eigentliCH runs locally and the operator has the machine, so a
reset is `python -m eigentlich.reset <email>` rather than an email with a link in it. That deletes the
entire surface where reset bugs live — token expiry, single-use enforcement, mail delivery, the enumeration
oracle in "we sent you a link if that address exists" — by not having it.

**Login does not say which half was wrong.** A distinct "no such account" would turn this endpoint into a
membership oracle: anyone could learn who has an eigentliCH account by trying addresses. C-05 makes eigentliCH
sole controller of that fact and it is not given away at the login form.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import Credential, Member, Session, utcnow
from ..models.auth import SESSION_LIFETIME
from .registration import register_member


class AuthenticationFailed(Exception):
    """Wrong address, wrong password, or no such account — deliberately indistinguishable."""


class EmailAlreadyRegistered(Exception):
    """Raised at registration, where saying so is unavoidable and the member is the one being told."""


def _normalise_email(email: str) -> str:
    # Lowercased and trimmed. Not further normalised: stripping dots or plus-tags is a provider-specific
    # guess, and guessing that two addresses are one person is exactly the wrong direction here.
    return email.strip().lower()


def register_with_credentials(
    db: DbSession,
    *,
    email: str,
    password: str,
    age_at_registration: int,
    display_name: str,
    locale: str = "de-CH",
    consents: list[dict] | None = None,
) -> tuple[Member, Credential]:
    """R-100's age floor still runs first: no credential is created for an account that cannot exist."""
    address = _normalise_email(email)
    existing = db.execute(select(Credential).where(Credential.email == address)).scalar_one_or_none()
    if existing is not None:
        raise EmailAlreadyRegistered(f"{address} is already registered")

    member = register_member(
        db,
        age_at_registration=age_at_registration,
        display_name=display_name,
        locale=locale,
        consents=consents,
    )
    db.flush()

    credential = Credential(member_id=member.id, email=address)
    credential.set_password(password)
    db.add(credential)
    return member, credential


def login(db: DbSession, *, email: str, password: str) -> tuple[Session, str]:
    """Returns the session row and the raw token. The raw token is never stored and never logged."""
    address = _normalise_email(email)
    credential = db.execute(select(Credential).where(Credential.email == address)).scalar_one_or_none()

    if credential is None:
        # Derive against a throwaway salt anyway, so a missing account and a wrong password take
        # comparable time. Without this the endpoint answers "does this address exist" by stopwatch.
        Credential.derive(password, b"\x00" * 16, 1000)
        raise AuthenticationFailed("email or password is incorrect")

    if not credential.verify(password):
        raise AuthenticationFailed("email or password is incorrect")

    credential.last_login_at = utcnow()

    token = secrets.token_urlsafe(32)
    session = Session(
        member_id=credential.member_id,
        token_hash=Session.hash_token(token),
        expires_at=utcnow() + SESSION_LIFETIME,
    )
    db.add(session)
    return session, token


def member_for_token(db: DbSession, token: str) -> Member | None:
    """The member behind a session token, or None. Expired and revoked sessions return None."""
    if not token:
        return None
    row = db.execute(
        select(Session).where(Session.token_hash == Session.hash_token(token))
    ).scalar_one_or_none()
    if row is None or not row.active:
        return None
    return db.get(Member, row.member_id)


def logout(db: DbSession, token: str) -> bool:
    row = db.execute(
        select(Session).where(Session.token_hash == Session.hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    return True


def revoke_all_sessions(db: DbSession, *, member_id: str, at: datetime | None = None) -> int:
    """Every session for one member. Used by the operator reset, and by R-213's immediate revocation."""
    when = at or utcnow()
    rows = db.execute(
        select(Session).where(Session.member_id == member_id, Session.revoked_at.is_(None))
    ).scalars()
    count = 0
    for row in rows:
        row.revoked_at = when
        count += 1
    return count


def operator_reset(db: DbSession, *, email: str, new_password: str) -> Credential:
    """A43. The reset, performed by whoever runs the server.

    Sets the new password, marks it must-change, and revokes every existing session — a reset that left
    old sessions alive would not be a reset.
    """
    address = _normalise_email(email)
    credential = db.execute(select(Credential).where(Credential.email == address)).scalar_one_or_none()
    if credential is None:
        raise AuthenticationFailed(f"no credential for {address}")

    credential.set_password(new_password)
    credential.must_change = True
    revoke_all_sessions(db, member_id=credential.member_id)
    return credential


def change_password(db: DbSession, *, member_id: str, current: str, new: str) -> Credential:
    """A member changing their own password. Requires the current one even when must_change is set."""
    credential = db.execute(
        select(Credential).where(Credential.member_id == member_id)
    ).scalar_one_or_none()
    if credential is None or not credential.verify(current):
        raise AuthenticationFailed("current password is incorrect")

    credential.set_password(new)
    credential.must_change = False
    return credential
