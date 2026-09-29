"""MemberFact — the five stated facts about a person that no other table could hold.

`tools/load_submission.py` has reported the same absence against every real submission since 30 August
2026: a member states their canton, their civil status, their own sense of their health, the size of the
network that would actually answer them, and what they trained in — and **nothing in the model had a place
to put any of it**, so all five were read, printed and dropped. The owner named those five on 4 September
2026 as the instrument's missing keys.

===========================================================================================================
WHY ONE TABLE AND NOT FIVE COLUMNS
===========================================================================================================

The instruction is that keys can be added **without touching the intake flow**. Five columns on `Member`
would satisfy today's list and break that promise on the sixth key: a new column is a model change, a
migration, a branch in `onboarding.complete`, and a new control in the client. What is wanted is that
adding a key is an **editorial** act — one entry in `client/content/onboarding-questions.json` — and that
is what a key/value table buys.

**This is not `OnboardingAnswer` wearing a different name**, and the distinction is the same one
`services/onboarding.py` already draws in its opening docstring. An `OnboardingAnswer` is *what was typed
during the first session*: one row per question, written as the member types, explicitly not a plan
mutation and explicitly not a Decision, and it exists so a member can resume at question n. A `MemberFact`
is *a fact about the member that findings rest on*. It has a date it describes, someone who stated it, and
it changes over a life — a member moves canton, marries, stops feeling well. The first is a transcript of
a session; the second is current standing. Storing the canton only as an onboarding answer would mean a
member who moved could correct it only by editing the record of a conversation they had years ago.

So this is `PlanMutable`: writing one is a plan mutation and takes a Decision in the same transaction
(C-09), exactly as `Household` does, and for the same reason — the tax path and the AHV path move when
these move.

===========================================================================================================
CLASSIFICATION, AND WHY THE COLUMN NAMES ARE ODD
===========================================================================================================

The entity is **K3**. That is one class above where a canton belongs, and it is deliberate: `health` is a
person's own statement about their body, the most sensitive value this application has ever stored, and
the C-04 logging filter drops by **field name** across the whole model layer. A K2 entity would leave
`health` in log lines.

Classifying the entity K3 means every non-structural column name on it joins the filter's drop list
globally — so the columns are named `stated_key` and `stated_value` rather than `key` and `value`. A K3
column called `key` would have the filter redacting `key=` in every log line this application writes,
including lines about content records and engine artefacts that are K0. **A filter that removes the field
every trace is followed by is not a safer filter, it is an unused one** — `models/base.py` makes that
argument about `member_id` and it applies here with more force, because `key` is the more common name.

`stated_on` and `stated_by` carry an override back down to K1. They are provenance — a date and one of two
words — and leaving them at K3 would drop `stated_by=` from log lines about `households`, which is a
different table's diagnostic being removed by this one's classification.

The per-row `data_class` is set from the **key's own declaration in the content record**, not from the
entity. A canton row stores K1 and a health row stores K3, so an export or a retention sweep reads the row
rather than the code that wrote it — which is the reason `Classified` puts the class in a column at all.
The entity constant governs the log filter; the row value governs everything downstream.

===========================================================================================================
SUPERSEDING RATHER THAN OVERWRITING
===========================================================================================================

A member who moves from Thurgau to St. Gallen has not corrected a typo, they have changed cantons, and a
plan version stamped against the old canton must keep meaning what it meant. So a new statement supersedes
the old one and the old row stays. `current` is "the row for this key that has not been superseded".

**Superseding is a date and deliberately NOT a pointer at the successor**, which is where `PlanVersion`
went and where this should not follow. A `superseded_by_id` would be a self-referencing foreign key, and
this build has already paid for one twice: `PRAGMA foreign_keys` is ON and SQLite checks per row, so
`erasure._erase` has to delete plan versions itself, oldest first, outside its own generic loop — and
nulling the reference to avoid that was refused by the schema, correctly. It is also unwritable here
without breaking the uniqueness rule below, because the row a pointer would name does not exist yet at the
moment the old row must stop being current. The successor is recoverable without a column: the rows for
one key are a sequence, ordered by when they were stated.

The rows are not append-only at the storage layer — no trigger — because unlike a Decision there is a
legitimate reason to remove one: R-231's erasure. `member_facts` is in `DELETED_IN_ERASURE_ORDER`, which
is also what puts it in the export, so a member leaves with these five and they are destroyed here.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, new_id, Timestamped
from .household import STATED_BY
from .plan import PlanMutable


class MemberFact(Base, Classified, Timestamped, PlanMutable):
    """One stated fact about one member, current until something supersedes it."""

    __tablename__ = "member_facts"
    __data_class__ = DataClass.K3

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    stated_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="The instrument's key for this fact. Not a closed set in the schema on purpose: the closed "
        "set lives in the content record, so adding a key is an editorial act. `services/member_fact.py` "
        "refuses a key the instrument does not declare, which is the check that matters — a key nothing "
        "declares is a fact nobody asked for.",
    )
    stated_value: Mapped[object] = mapped_column(
        JSON,
        nullable=False,
        doc="Whatever the question's type produces: a code for a choice, a number, a string. JSON rather "
        "than five typed columns, because the type belongs to the question and the question lives in "
        "content. Validated against the question's declaration before it is written, never after.",
    )

    stated_on: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="The date the member says this describes — not when the row was written. A curator recording "
        "a session held last week states last week's date, exactly as `households.composition_as_of` "
        "does, and for the same reason: the Befund stamps the stated date and never `created_at`.",
        info={
            # Provenance, not content. Left at K3 it would drop `stated_on=` from every log line in the
            # application, including tables that have nothing to do with this one.
            "data_class": DataClass.K1,
        },
    )
    stated_by: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="Which of the two initiators recorded it. A record, not a permission — the same word "
        "`households.stated_by` uses, read from the same tuple so the two cannot diverge. Typed as a "
        "String with an explicit CHECK rather than as `Enum`, because SQLAlchemy's `Enum` defaults to "
        "`create_constraint=False` and produces a bare VARCHAR: that is exactly how `magnitude_unit` was "
        "found to have never been constrained in any database this build ever produced.",
        info={"data_class": DataClass.K1},
    )

    superseded_on: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        doc="The date this statement stopped standing, which is the date the one replacing it describes. "
        "Null means current. See the module docstring on why this is a date and not a pointer.",
        info={"data_class": DataClass.K1},
    )

    __table_args__ = (
        CheckConstraint(
            "stated_by IN (" + ", ".join(f"'{one}'" for one in STATED_BY) + ")",
            name="ck_member_facts_stated_by",
        ),
        CheckConstraint(
            "superseded_on IS NULL OR superseded_on >= stated_on",
            name="ck_member_facts_superseded_after_stated",
        ),
        # At most one current row per key per member. A partial index rather than a plain unique one,
        # because the superseded rows are the history and there may be many of them — the same shape
        # `uq_plan_versions_one_standing` uses. Without it, two writes racing leave a member with two
        # current cantons and no rule for which one a finding reads.
        Index(
            "uq_member_facts_one_current",
            "member_id",
            "stated_key",
            unique=True,
            sqlite_where=(superseded_on.is_(None)),
        ),
    )


__all__ = ["MemberFact"]
