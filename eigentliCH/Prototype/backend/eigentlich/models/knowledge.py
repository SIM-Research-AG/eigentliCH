"""LearningUnit, Capability, CapabilityAssertion.

Included in the spine rather than deferred to phase 6 because R-192 asks for exactly this: *build the data
model and leave the scheme configurable*. The structure is what holds D-01 open. Building it later would
mean the intervening phases had nowhere to put a capability reference, and the pressure to invent a scheme
grows with every week it has no home.

**`Capability.rung` is nullable and has no default.** D-01 — the ladder's unit of progression, the rung
scheme, and how a capability is assessed are undecided. No enum, no ordering, no thresholds, and no numbers
carried over from the estate's XP ladder, which A2 and A3 in DECISIONS.md deliberately left behind.

**No level numbers and no points anywhere in this file** (C-07, R-191). Progression is expressed as
capability statements a member can read. `statement` is therefore not nullable: a capability nobody wrote a
sentence for is a number wearing a name.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped


class LearningUnit(Base, Classified, Timestamped):
    __tablename__ = "learning_units"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)

    prerequisites: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capability_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, doc="R-190. What completing this unit evidences."
    )

    ip_owner: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        doc="Who owns this content. Nullable and currently unset for the same reason engine manifests "
        "carry a null owner — A4 in DECISIONS.md. Not invented.",
    )


class Capability(Base, Classified, Timestamped):
    __tablename__ = "capabilities"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Testable and readable, e.g. 'can explain what a Freizuegigkeitskonto in cash costs per year'. "
        "R-191: this sentence IS the progression. There is nothing else to show a member.",
    )
    rung: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
        doc="D-01, UNDECIDED. A free-text, nullable, unordered label with no default and no enum. Giving "
        "this a scheme is the defect §12 names — do not add one without an owner for the decision.",
    )


class CapabilityAssertion(Base, Classified, Timestamped):
    """That a member has evidenced a capability, by whom and on what evidence."""

    __tablename__ = "capability_assertions"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)
    capability_id: Mapped[str] = mapped_column(ForeignKey("capabilities.id"), nullable=False, index=True)

    evidence_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assessed_by: Mapped[str] = mapped_column(String(120), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    capability: Mapped[Capability] = relationship()
