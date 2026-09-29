"""A11 credentials and sessions, and A43's operator reset.

Iterations are lowered for these tests: 600,000 rounds of PBKDF2 per login is correct in production and
would make this file take minutes.
"""

from __future__ import annotations

import pytest

from eigentlich.models import Credential, Session, WeakPassword
from eigentlich.models.auth import MINIMUM_PASSWORD_LENGTH
from eigentlich.services import (
    AuthenticationFailed,
    BelowAgeFloor,
    EmailAlreadyRegistered,
    change_password,
    login,
    logout,
    member_for_token,
    operator_reset,
    register_with_credentials,
    revoke_all_sessions,
)

GOOD_PASSWORD = "ein ziemlich langes passwort"


@pytest.fixture(autouse=True)
def _fast_hashing(monkeypatch):
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)


@pytest.fixture()
def account(session):
    member, credential = register_with_credentials(
        session,
        email="Nicolas@Example.CH",
        password=GOOD_PASSWORD,
        age_at_registration=45,
        display_name="Nicolas",
    )
    session.commit()
    return member, credential


# ============================================================ registration


def test_email_is_normalised(account):
    _, credential = account
    assert credential.email == "nicolas@example.ch"


def test_the_age_floor_runs_before_any_credential_exists(session):
    """R-100. No credential is created for an account that cannot exist."""
    with pytest.raises(BelowAgeFloor):
        register_with_credentials(
            session, email="young@example.ch", password=GOOD_PASSWORD,
            age_at_registration=17, display_name="Too young",
        )
    session.rollback()
    assert session.query(Credential).count() == 0


def test_a_duplicate_address_is_refused(session, account):
    with pytest.raises(EmailAlreadyRegistered):
        register_with_credentials(
            session, email="nicolas@example.ch", password=GOOD_PASSWORD,
            age_at_registration=50, display_name="Someone else",
        )


def test_a_short_password_is_refused(session):
    with pytest.raises(WeakPassword):
        register_with_credentials(
            session, email="x@example.ch", password="kurz",
            age_at_registration=40, display_name="X",
        )


def test_the_password_is_not_stored(session, account):
    _, credential = account
    assert GOOD_PASSWORD.encode() not in credential.password_hash
    assert credential.password_hash != credential.password_salt
    assert len(credential.password_salt) >= 16


# ============================================================ login


def test_login_returns_a_session_and_a_token(session, account):
    row, token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()
    assert token and len(token) > 30
    assert row.active


def test_the_raw_token_is_never_stored(session, account):
    row, token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()
    assert token.encode() not in row.token_hash
    assert row.token_hash == Session.hash_token(token)


def test_a_token_resolves_to_its_member(session, account):
    member, _ = account
    _, token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()
    assert member_for_token(session, token).id == member.id


def test_a_wrong_password_is_refused(session, account):
    with pytest.raises(AuthenticationFailed):
        login(session, email="nicolas@example.ch", password="das falsche passwort")


def test_an_unknown_address_fails_identically(session, account):
    """No membership oracle: a login form must not answer 'does this person have an account'."""
    with pytest.raises(AuthenticationFailed) as unknown:
        login(session, email="nobody@example.ch", password=GOOD_PASSWORD)
    with pytest.raises(AuthenticationFailed) as wrong:
        login(session, email="nicolas@example.ch", password="das falsche passwort")
    assert str(unknown.value) == str(wrong.value)


def test_logout_revokes_the_session(session, account):
    _, token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()
    assert logout(session, token) is True
    session.commit()
    assert member_for_token(session, token) is None


def test_an_expired_session_does_not_resolve(session, account):
    from datetime import timedelta

    from eigentlich.models import utcnow

    row, token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    row.expires_at = utcnow() - timedelta(seconds=1)
    session.commit()
    assert member_for_token(session, token) is None


def test_a_garbage_token_resolves_to_nothing(session, account):
    assert member_for_token(session, "not-a-token") is None
    assert member_for_token(session, "") is None


# ============================================================ A43 operator reset


def test_operator_reset_sets_a_new_password(session, account):
    operator_reset(session, email="nicolas@example.ch", new_password="ein neues langes passwort")
    session.commit()

    with pytest.raises(AuthenticationFailed):
        login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    row, _ = login(session, email="nicolas@example.ch", password="ein neues langes passwort")
    assert row.active


def test_operator_reset_revokes_every_existing_session(session, account):
    """A reset that left old sessions alive would not be a reset."""
    _, old_token = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()
    assert member_for_token(session, old_token) is not None

    operator_reset(session, email="nicolas@example.ch", new_password="ein neues langes passwort")
    session.commit()
    assert member_for_token(session, old_token) is None


def test_operator_reset_marks_must_change(session, account):
    _, credential = account
    operator_reset(session, email="nicolas@example.ch", new_password="ein neues langes passwort")
    session.commit()
    assert credential.must_change is True


def test_there_is_no_reset_token_table():
    """A43. The whole class of reset-token bugs is avoided by not having the table.

    Expiry, single-use enforcement, and the enumeration oracle in 'we sent a link if that address exists'
    all live in a table that does not exist here.
    """
    from eigentlich.models import Base

    names = {mapper.class_.__tablename__ for mapper in Base.registry.mappers}
    assert not any("reset" in name or "token" in name for name in names), names


def test_the_generated_password_is_long_enough():
    from eigentlich.reset import suggest_password

    for _ in range(20):
        assert len(suggest_password()) >= MINIMUM_PASSWORD_LENGTH


# ============================================================ change and revoke


def test_a_member_changes_their_own_password(session, account):
    member, _ = account
    change_password(session, member_id=member.id, current=GOOD_PASSWORD, new="noch ein langes passwort")
    session.commit()
    assert login(session, email="nicolas@example.ch", password="noch ein langes passwort")


def test_changing_requires_the_current_password(session, account):
    member, _ = account
    with pytest.raises(AuthenticationFailed):
        change_password(session, member_id=member.id, current="falsch", new="ein anderes langes passwort")


def test_changing_clears_must_change(session, account):
    member, credential = account
    operator_reset(session, email="nicolas@example.ch", new_password="ein neues langes passwort")
    session.commit()
    change_password(
        session, member_id=member.id,
        current="ein neues langes passwort", new="ein selbst gewaehltes passwort",
    )
    session.commit()
    assert credential.must_change is False


def test_revoking_all_sessions_is_immediate(session, account):
    """R-213's mechanism, reused: revocation takes effect on the next request, not at expiry."""
    member, _ = account
    _, first = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    _, second = login(session, email="nicolas@example.ch", password=GOOD_PASSWORD)
    session.commit()

    assert revoke_all_sessions(session, member_id=member.id) == 2
    session.commit()
    assert member_for_token(session, first) is None
    assert member_for_token(session, second) is None
