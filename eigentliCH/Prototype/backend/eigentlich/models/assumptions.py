"""AssumptionSet — C-02's answer to "where does the number come from".

"No literal rate in application code." Rates, horizons and inflation live here, versioned and dated, and
every illustration response returns the `assumption_set_id` it used. That is what makes an illustration
reproducible a year later, when the rate has changed and the screenshot has not.

**This file ships with no values.** A rate written here by an implementing agent would be an invented
number, which §12 calls a defect rather than a gap-fill. The table exists; populating it is an editorial
act with an owner, and `published_by` is where that owner is recorded.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, new_id, Timestamped


class NoAssumptionSet(Exception):
    """Raised when an illustration is requested and no assumption set is in effect.

    The correct behaviour is to refuse the illustration, not to fall back on a default. A default rate is
    an invented rate wearing a different hat, and C-02 exists precisely because that substitution is easy
    to make and impossible to see afterwards.
    """


class AssumptionSet(Base, Classified, Timestamped):
    __tablename__ = "assumption_sets"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)

    version: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    published_by: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        doc="C-02. Who stands behind these numbers. Not nullable: an assumption set with no author is an "
        "assumption set nobody can be asked about.",
    )

    rates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    horizons: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inflation: Mapped[float | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("version", name="uq_assumption_sets_version"),)
