"""CuratorSession and its append-only event log (C-10).

**A note on a tension in the spec, resolved here and worth knowing about.** §4 lists `CuratorSession` with
`closed_at` and `outcome` on the row, and marks it `append_only`. §11 asks for
`test_curator_audit_table_rejects_update_and_delete()`. Those two cannot both hold of one row: closing a
session that was opened earlier is an UPDATE, and a table that rejects UPDATE cannot record a closure.

The resolution is to keep both promises by splitting them. `curator_session_events` is the audit table, and
it rejects UPDATE and DELETE at the database level. `CuratorSession` holds what is known at open time, and
`closed_at` / `outcome` are **derived properties** reading the latest event. The §4 field list is preserved
as an interface; the append-only guarantee is preserved as a fact about the store.

C-10's full verification is phase 5. What is here is the table and its trigger, because the spine is where
an append-only table has to be created if migrations are ever to say so.

**C-10 had one enforcement point where R-040 has two, and the missing one was the ORM.** `AuditImmutable`
was defined in this file on the day the table was and raised nowhere in the codebase. Dropping the
triggers — which R-231's erasure does, by design, every time it runs — and rewriting a
`CuratorSessionEvent` through the ORM *succeeded*, while the same experiment on `decisions` was still
refused by `DecisionImmutable` from `db.py`'s `before_flush` guard. `db.py` says of the append-only
triggers that "the `before_flush` guard above covers the ORM; a trigger covers everything else"; for this
table only the second half was true, and an exception class that is never raised reads exactly like one
that is. The guard below is the first half, and it lives here rather than in `db.py` so that it arrives
with the table it protects.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum as SAEnum, ForeignKey, JSON, String, Text, event, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped, utcnow

EVENT_KINDS = ("opened", "granted", "revoked", "note", "closed")


class AuditImmutable(Exception):
    """Raised when something tries to change or remove an audit row. C-10."""


class CuratorSession(Base, Classified, Timestamped):
    __tablename__ = "curator_sessions"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: Nullable so R-231's erasure can null it. The row itself cannot be deleted (R-040 / C-10), so
    #: "delete my data" is carried out by removing the member from it — see `services/erasure.py`.
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)

    #: **A foreign key, since 31 August 2026.** It was a plain `String(120)` for the whole of the build
    #: before that, which meant any string at all could be written into the parent row of an append-only
    #: audit — and A40 had claimed the opposite in writing. `AccessGrant.curator_id` was the foreign key;
    #: this one was not, and the correction is A67's. The reason it matters here more than anywhere else:
    #: `curator_session_events` refuses UPDATE and DELETE by trigger, so an invented curator recorded
    #: against a session cannot be corrected afterwards. A constraint that has to hold before the row
    #: exists is a constraint the storage layer has to hold, not a caller.
    curator_id: Mapped[str] = mapped_column(
        ForeignKey("curators.id"),
        nullable=False,
        index=True,
        doc="C-10. The identified curator. Never a role, never a queue.",
    )
    opened_from: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        doc="R-173. Which screen the Curator button was pressed on. Recorded because 'where were they when "
        "they needed a human' is the question this product is trying to answer about itself.",
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    liability_flag: Mapped[bool | None] = mapped_column(nullable=True)

    events: Mapped[list["CuratorSessionEvent"]] = relationship(
        back_populates="session", order_by="CuratorSessionEvent.at"
    )

    def _last(self, kind: str) -> "CuratorSessionEvent | None":
        matching = [e for e in self.events if e.kind == kind]
        return matching[-1] if matching else None

    @property
    def closed_at(self) -> datetime | None:
        event = self._last("closed")
        return event.at if event else None

    @property
    def outcome(self) -> str | None:
        event = self._last("closed")
        return event.detail.get("outcome") if event and event.detail else None


class CuratorSessionEvent(Base, Classified, Timestamped):
    """The append-only audit table. UPDATE and DELETE are refused by trigger — see `db.py`."""

    __tablename__ = "curator_session_events"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("curator_sessions.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(SAEnum(*EVENT_KINDS, name="curator_event_kind"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped[CuratorSession] = relationship(back_populates="events")


@event.listens_for(Session, "before_flush")
def _refuse_to_change_an_audit_row(
    session: Session, _flush_context: object, _instances: object
) -> None:
    """C-10's ORM half, written to mirror `db.py`'s R-040 guard statement for statement.

    `before_flush` rather than `before_update`/`before_delete`: it raises before any SQL is emitted, so a
    refused write is not a half-written transaction. It is registered when `eigentlich.models` is imported,
    which is before `db.py` registers its own listener, so this runs first and `_begin_vetted_flush` is
    never reached on a flush this refuses.

    **It only covers `CuratorSessionEvent`.** `CuratorSession` is deliberately mutable: R-231's erasure
    nulls its `member_id`, and this module's docstring explains why the parent row holds what is known at
    open time while the append-only guarantee belongs to the event log.

    R-231's erasure is unaffected. It redacts through Core `update()` statements on
    `CuratorSessionEvent.__table__`, which is not an ORM flush and never was — the triggers are what it
    drops and re-creates, and they are still the half of C-10 that covers a write going round the ORM.
    """
    for obj in session.dirty:
        if isinstance(obj, CuratorSessionEvent) and session.is_modified(obj, include_collections=True):
            changed = [attr.key for attr in inspect(obj).attrs if attr.history.has_changes()]
            raise AuditImmutable(
                f"C-10: curator_session_events is an append-only audit table; event {obj.id!r} "
                f"({obj.kind!r}) was modified ({', '.join(changed)}). What a curator did is recorded by "
                f"appending another event — `services/curator.py.record_event` is the only writer — and a "
                f"session is closed by writing a `closed` event, not by editing the one before it."
            )
    for obj in session.deleted:
        if isinstance(obj, CuratorSessionEvent):
            raise AuditImmutable(
                f"C-10: curator_session_events is an append-only audit table; event {obj.id!r} "
                f"({obj.kind!r}) cannot be deleted. R-040's reasoning applies here for the same reason: "
                f"the record of what a curator did is the thing that survives a change of adviser, and it "
                f"does not get tidied away."
            )
