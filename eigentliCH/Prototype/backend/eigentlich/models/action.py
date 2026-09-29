"""ActionItem — a notification with the decision it is about.

"No notification without a prepared decision." `prepared_options` carries what the member is choosing
between, and it is non-nullable: an item that notifies without saying what the choice is would be the
interruption R-175 forbids wearing a different hat.

**C-06 was dropped on 20 September 2026 (A168), and this file is where most of it lived.** It required at
least two options, each carrying a label and a consequence, and it was enforced three times over — a
`@validates` hook, a CHECK constraint counting the array, and two BEFORE triggers walking its contents
because a CHECK cannot. All three are gone. The owner's reasoning is in A168: the property could be
satisfied vacuously, nothing ever checked that two consequences differed, and "two options" was being
enforced to the letter by machinery that could not express the thing it was for.

**What is left is the column and its shape by convention.** `services/derive.py` still writes two options
with labels and consequences, and `tests/test_derive.py` still asserts it does. The difference is that it
is now a property of the code that writes action items rather than a claim about the store, and the
difference is real: `bulk_insert_mappings` or a raw INSERT can now write an item with an empty array.

The unique index below is NOT C-06 and stays. It makes the plan derivations idempotent, which is what
decides whether the feature is usable at all.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, new_id, Timestamped

STATUSES = ("open", "acted", "dismissed", "expired")

#: The unique index that makes the plan derivations idempotent. Named once so the model, the migration and
#: the test that plants a duplicate all read the same string.
DERIVED_CAUSE_INDEX = "uq_action_items_derived_cause"


class ActionItem(Base, Classified, Timestamped):
    __tablename__ = "action_items"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    trigger_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(SAEnum(*STATUSES, name="action_status"), nullable=False, default="open")

    prepared_options: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        doc="Each option: {label, consequence, cost_or_benefit, assumption_set_id}. "
        "`assumption_set_id` is present wherever the consequence carries a figure — C-02. The minimum of "
        "two and the required keys were C-06 and are no longer enforced anywhere (A168).",
    )

    source_vault_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("vault_items.id"), nullable=True, index=True
    )

    derived_from: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        doc="What in the member's own record caused this item — a goal id, a position id, a capital type "
        "or an onboarding question key. NOT a foreign key, because the causes are of several kinds and a "
        "column per kind would make the unique index below one index per kind. Null for the expiry items "
        "(R-152's primary source), which are caused by a document and say so in `source_vault_item_id`.",
    )

    __table_args__ = (
        # ------------------------------------------------------------------ idempotence, at the store
        #
        # One derived item per cause, forever. `services/derive.py` re-runs on every read of the action
        # list, so "running the derivation twice must not produce two items for the same cause" is the
        # property that decides whether the feature is usable at all — and onboarding `complete` is the
        # precedent for getting it wrong: called twice it wrote a duplicate Position and a duplicate
        # Decision that R-040 then made undeletable.
        #
        # A read-then-insert in the service would be the ordinary fix and would still be a race between
        # two concurrent reads. This is the same argument A63, A66, A68 and A72 all make about C-09 and
        # R-040: a guarantee the service checks is a guarantee that holds until someone writes another
        # service. A UNIQUE INDEX is a claim about the store.
        #
        # **An INDEX rather than a UniqueConstraint, deliberately.** `create_all` renders a
        # UniqueConstraint inline in CREATE TABLE and a migration renders it as a separate unique index;
        # the two paths would then produce schemas that differ, and A68 is the week this estate lost to a
        # migrated schema differing from the `create_all` one. An index is spelled the same by both.
        #
        # NULLs are distinct in SQLite, so the expiry items — which all carry `derived_from IS NULL` —
        # are untouched by this: two of them for one document remain possible, exactly as before.
        Index(
            DERIVED_CAUSE_INDEX,
            "member_id",
            "trigger_kind",
            "derived_from",
            unique=True,
        ),
    )
