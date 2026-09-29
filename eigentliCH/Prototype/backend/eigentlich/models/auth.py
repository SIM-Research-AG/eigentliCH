"""Credentials and sessions. A11 chose email and password, self-hosted.

**Password reset is a backend operation, not a mail flow** (A43). eigentliCH runs locally: the operator has
the machine. So a reset is performed by whoever runs the server, through `python -m eigentlich.reset`, and
there is no SMTP dependency, no reset-token table, and no email a member has to wait for. That removes
A27's blocker rather than deferring it, and removes the whole class of bugs that live in token expiry and
mail delivery.

The trade is stated plainly: a member cannot reset their own password unattended. For a locally-run
product with an operator present, that is the correct trade. It stops being correct the day this is hosted
for members who cannot reach the operator, and at that point a mail route becomes a real decision again.

**Hashing is PBKDF2-HMAC-SHA256 from the standard library.** Not the strongest available — scrypt and
argon2 are better — but it is in `hashlib`, and A9 accepted four dependencies for reasons that do not
extend to a fifth for this. The iteration count is stored on the row, so it can be raised later and old
rows keep verifying against the count they were written with.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped, utcnow

#: Raised over time as hardware improves. Stored per row so old credentials keep verifying.
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
#: How long a session is good for. Not a security parameter anyone tuned — a plain default, and the kind
#: of number that should move into a config record if it ever becomes contentious.
SESSION_LIFETIME = timedelta(days=14)

MINIMUM_PASSWORD_LENGTH = 12


class WeakPassword(ValueError):
    """Refused before hashing. The length floor is the only rule: composition rules push people toward
    Passwort1! and away from length, which is the thing that actually helps."""


class Credential(Base, Classified, Timestamped):
    """One login per member. Separate from `Member` so the K-classes stay honest.

    K1 as a row: an email address identifies a person. The hash itself is not a secret worth a higher
    class — it is designed to be useless — but `email` is, and the C-04 filter drops both by name.
    """

    __tablename__ = "credentials"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[bytes] = mapped_column(LargeBinary(64), nullable=False)
    password_salt: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=PBKDF2_ITERATIONS)

    #: Set by an operator reset. The member is asked to choose a new password on next login.
    must_change: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("email", name="uq_credentials_email"),)

    # -- hashing ---------------------------------------------------------------------------------

    @staticmethod
    def derive(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    def set_password(self, password: str) -> None:
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise WeakPassword(
                f"a password of at least {MINIMUM_PASSWORD_LENGTH} characters is required. Length is the "
                f"only rule here: composition rules produce shorter, more guessable passwords."
            )
        self.password_salt = secrets.token_bytes(SALT_BYTES)
        self.iterations = PBKDF2_ITERATIONS
        self.password_hash = self.derive(password, self.password_salt, self.iterations)

    def verify(self, password: str) -> bool:
        """Constant-time comparison. A timing difference here is a real oracle, not a theoretical one."""
        candidate = self.derive(password, self.password_salt, self.iterations)
        return hmac.compare_digest(candidate, self.password_hash)


class Session(Base, Classified, Timestamped):
    """A logged-in session. The token is stored hashed, so the table is not a set of live keys.

    If this table leaks, nothing in it can be replayed as a session — the same reason passwords are hashed,
    applied to the thing that actually grants access day to day.
    """

    __tablename__ = "sessions"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    member: Mapped["Member"] = relationship()  # noqa: F821

    @staticmethod
    def hash_token(token: str) -> bytes:
        # A session token is already high-entropy random, so a single SHA-256 is right here: there is no
        # low-entropy secret to slow an attacker down against, and PBKDF2 on every request would only
        # slow the server.
        return hashlib.sha256(token.encode("utf-8")).digest()

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()
