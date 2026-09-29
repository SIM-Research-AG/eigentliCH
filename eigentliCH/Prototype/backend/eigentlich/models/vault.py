"""VaultItem — K3, the class that never leaves the server and never reaches a log line (C-04).

R-041: nothing is overwritten in place. A new version is a new row carrying `supersedes_id`, so the vault
is a chain rather than a cell. That is what makes "full export of everything the member owns" (R-154) an
export of a history rather than of a current state.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped

#: R-150. Four intake paths behind one interface. Which automated path is built first is D-04, so only
#: `upload` and `capture` are implemented; the other two are accepted as values but their adapters raise.
SOURCES = ("upload", "forward", "import", "capture", "manual")

#: R-153. Member-authored material is a vault item of equal standing, not a lesser kind. `note` sits in the
#: same list as `policy` for that reason.
KINDS = ("policy", "statement", "contract", "note", "arrangement", "learning", "other")


class VaultItem(Base, Classified, Timestamped):
    __tablename__ = "vault_items"
    __data_class__ = DataClass.K3

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(SAEnum(*KINDS, name="vault_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(SAEnum(*SOURCES, name="vault_source"), nullable=False)

    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("vault_items.id"),
        nullable=True,
        index=True,
        doc="R-041. Set on the NEW row. The superseded row is never updated and never deleted.",
    )
    supersedes: Mapped["VaultItem | None"] = relationship(remote_side=[id])

    expiry_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
        doc="R-152. First-class, indexed, and the primary source of action items — which is why it is a "
        "column and not a key inside `extracted_fields`.",
    )

    extracted_fields: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        doc="R-151. Every entry carries its provenance and a confidence indication. Extraction NEVER "
        "overwrites a member-entered value: a disagreement is two recorded facts, not one corrected one.",
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
