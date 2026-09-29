"""Curator, AccessGrant and the community tables. Phases 5 and 8.

**A40: curators are staff, and get their own table.** Not a flag on `Member`. A role flag on a member row
is exactly the mistake C-10's audit table exists to make impossible, and it makes `curator_id` a foreign
key rather than a string that could name anything.

That last clause was true of this file and false of `models/curator.py` for the whole of the build —
`CuratorSession.curator_id` was a plain `String(120)`. A67 recorded the correction, A98 carried it out, and
it is noted here because this is the paragraph that made the claim.

**R-210 and R-213 are the shape of `AccessGrant`.** A curator sees a member's material only after the
member grants it, *scoped* and *time-limited*, and the member revokes at any time with immediate effect.
So a grant carries what it covers and when it lapses, and revocation is a timestamp rather than a delete —
an audit needs to show that access existed and was withdrawn, which a deleted row cannot.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, Boolean, Date, Enum as SAEnum, ForeignKey, JSON, String, Text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped, utcnow

#: What a grant may cover. R-210 says "scoped", so the scope is an explicit list rather than all-or-nothing.
GRANTABLE = ("positions", "goals", "decisions", "vault", "action_items")

GATHERING_KINDS = ("lecture", "cafe_evening", "meetup")


class Curator(Base, Classified, Timestamped):
    """Staff. Their own table and their own login (A40).

    `data_class` K1: a curator is an identified person, but nothing here is a member's financial material.

    **A curator who leaves is revoked, not deleted (A160).** Three of A62's five left eigentliCH on
    20 September 2026, and the row stays for the same reason `AccessGrant`'s revocation is a timestamp:
    C-10's audit table exists to say who did something, and `curator_session_events` refuses DELETE by
    trigger. Deleting a curator who appears in a session event leaves that event naming a foreign key that
    resolves to nothing, which makes every record they touched unresolvable — the audit stops being
    evidence at the moment it is most needed. So `revoked_at` and `revoked_reason` below, and
    `in_service` is the one question every gate asks.
    """

    __tablename__ = "curators"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    #: C-10 records "the identified curator". A role label is not an identification, which is the estate's
    #: own note on `Decision.decided_by_role` — it says real names are an overlay to add later. This is
    #: that overlay.
    role_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Separate from `credentials`, which is a member's. A curator logging in with a member credential
    #: would make the audit table's "who" ambiguous.
    password_hash: Mapped[bytes | None] = mapped_column(nullable=True)
    password_salt: Mapped[bytes | None] = mapped_column(nullable=True)
    iterations: Mapped[int | None] = mapped_column(nullable=True)

    #: Mirrors `Credential.must_change`. Added because the seeding script was printing "good for one
    #: login" beside a curator's password while nothing enforced it — a false statement on an operator's
    #: terminal is worse than no statement, and the fix is the field rather than the wording.
    must_change: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: A160. When this person stopped being a curator. Never cleared: `active` is a switch an operator may
    #: flip back — someone on leave, an account parked — and revocation is not that. A revoked row is a
    #: statement that the audit trail's "who" refers to someone who has left, and the timestamp is what
    #: makes a record from before it still readable as true at the time.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Free text, and required in practice by `revoke_curator` rather than by the column, because a
    #: revocation with no stated reason is the quiet deletion this whole approach exists to avoid.
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @hybrid_property
    def in_service(self) -> bool:
        """Whether this curator may authenticate, act, be listed, or be named on a session.

        **One implementation, deliberately.** Four gates asked `active` separately before this existed —
        `authenticate_curator`, `require_curator`, `resolve_curator` and `list_curators` — and adding
        revocation to a build with four copies of the same condition is the A73/A91 defect being written
        on purpose: the fifth caller forgets, and the one that forgets is a door. A `hybrid_property`
        because two of those gates hold a loaded row and two are SQL `WHERE` clauses, and the alternative
        is a Python predicate plus a query fragment that have to agree.

        `fictional` is not part of it. The demonstration curator is in service and is simply not offered
        in the directory (A62) — that is a separate decision belonging to `list_curators`.
        """
        return self.active and self.revoked_at is None

    @in_service.inplace.expression
    @classmethod
    def _in_service_expression(cls):
        return and_(cls.active.is_(True), cls.revoked_at.is_(None))


class AccessGrant(Base, Classified, Timestamped):
    """R-210 / R-213. Scoped, time-limited, and revocable with immediate effect.

    **Revocation is a timestamp, not a delete.** An audit has to be able to show that access existed and
    was withdrawn; a deleted row shows neither. `is_live()` is what every read path must consult, and it
    checks revocation before expiry because a member's withdrawal is the stronger fact.
    """

    __tablename__ = "access_grants"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)
    curator_id: Mapped[str] = mapped_column(ForeignKey("curators.id"), nullable=False, index=True)

    #: R-210 "scoped". A list of GRANTABLE names — never a boolean "full access".
    scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    #: R-210 "time-limited". Not nullable: a grant without an end is not time-limited, and the whole
    #: point is that a member who forgets is still protected.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Which curator session this grant was opened for, where it was.
    curator_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("curator_sessions.id"), nullable=True, index=True
    )

    def is_live(self, *, at: datetime | None = None) -> bool:
        """The single question every read path must ask. Revocation first — it is the stronger fact."""
        now = at or utcnow()
        if self.revoked_at is not None:
            return False
        return self.expires_at > now

    def covers(self, what: str, *, at: datetime | None = None) -> bool:
        return self.is_live(at=at) and what in (self.scope or [])


class Gathering(Base, Classified, Timestamped):
    """S-13. Lectures, café evenings and meet-ups.

    **R-222: the word "events" in the interface means LIFE events.** So this table is not called `Event`,
    and nothing built on it may use that word for a gathering. The name is the enforcement.
    """

    __tablename__ = "gatherings"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(SAEnum(*GATHERING_KINDS, name="gathering_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    held_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    attendances: Mapped[list["Attendance"]] = relationship(back_populates="gathering")


class Attendance(Base, Classified, Timestamped):
    """R-221. An input to community presence for Market Place standing — recorded, and NOT shown to the
    member as a score.

    That second half is a constraint on every payload built from this table, and it is why there is no
    `count` or `total` column here to make convenient.
    """

    __tablename__ = "attendances"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)
    gathering_id: Mapped[str] = mapped_column(ForeignKey("gatherings.id"), nullable=False, index=True)
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    gathering: Mapped[Gathering] = relationship(back_populates="attendances")
