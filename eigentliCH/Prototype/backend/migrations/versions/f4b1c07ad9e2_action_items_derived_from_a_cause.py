"""action_items.derived_from, and one derived item per cause

Revision ID: f4b1c07ad9e2
Revises: f3a91c7b2e64
Create Date: 2026-08-31 16:20:00.000000

R-152 makes expiry dates the PRIMARY source of action items, not the only one. `services/derive.py` adds
the others — items derived from the plan the member has actually recorded — and it re-runs every time the
action list is read. So "running the derivation twice must not produce two items for the same cause" is
not a nicety; it is the difference between a list and a pile.

`derived_from` names the cause: a goal id, a position id, a capital type, or an onboarding question key.
The unique index over (member_id, trigger_kind, derived_from) is what makes the idempotence a fact about
the store rather than a promise made by one service function. A read-then-insert in the service is the
ordinary fix and is still a race between two concurrent reads; onboarding `complete` called twice is this
estate's own worked example of the cost, and it cost an undeletable duplicate Decision.

**No data migration, and nothing to back-fill.** Existing rows are the expiry items, whose cause is a
document and is already recorded in `source_vault_item_id`. They keep `derived_from IS NULL`, and SQLite
treats NULLs as distinct in a unique index, so the constraint says nothing about them at all.

**Plain `add_column`, not `batch_alter_table`.** SQLite supports ALTER TABLE ADD COLUMN for a nullable
column with no default, so the table is not recreated — and a table that is not recreated cannot lose the
two C-06 content triggers attached to it. That is the A63 / A66 / A68 trap, and the way past it here is to
not open the door.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from eigentlich.models.action import DERIVED_CAUSE_INDEX


# revision identifiers, used by Alembic.
revision: str = "f4b1c07ad9e2"
#: Chained after `f3a91c7b2e64` (engine runs) rather than after `a7c41b6f28de`, which both were written
#: against on the same day. Two revisions naming one parent is two heads, and `alembic upgrade head` then
#: refuses to run at all — so the later of the two is rebased onto the earlier rather than branched.
down_revision: Union[str, Sequence[str], None] = "f3a91c7b2e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("action_items", sa.Column("derived_from", sa.String(length=80), nullable=True))
    # Unique INDEX and not a unique CONSTRAINT: `create_all` renders a UniqueConstraint inline in the
    # CREATE TABLE, and this renders it separately. An index is spelled the same by both paths, so the
    # migrated schema and the `create_all` schema stay identical — which is the property A68 lost.
    op.create_index(
        DERIVED_CAUSE_INDEX,
        "action_items",
        ["member_id", "trigger_kind", "derived_from"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(DERIVED_CAUSE_INDEX, table_name="action_items")
    op.drop_column("action_items", "derived_from")
