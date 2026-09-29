"""a goal can be frozen for division

Revision ID: d5b71fc02e83
Revises: c8e40b23d971
Create Date: 2026-09-03

===========================================================================================================
WHAT THIS MIGRATES
===========================================================================================================

One nullable column, `goals.frozen_at`. Item 6: when a household closes, *"Goals owned by both members are
frozen and flagged for division, never split automatically. A curator handles the division — a decision
with real consequences and emotional load."*

Nullable, so every existing goal is unfrozen after this runs and no data is rewritten.

**A date rather than a boolean.** "Frozen since the closing date" is the sentence a member needs, and a
boolean would have to be read alongside the household record to produce it — which is a join that would
break as soon as a goal could be frozen for a second reason.

===========================================================================================================
WHY THIS USES `batch_alter_table` AND WHAT THAT COSTS
===========================================================================================================

SQLite can add a nullable column with a plain `ALTER TABLE ... ADD COLUMN`, so alembic does not need batch
mode for this and **is not given it**. That matters here more than usual, because of A63: batch mode
re-creates the table, and anything attached to the table that SQLite's reflection cannot see is dropped in
the process.

`goals` carries no append-only trigger — `db.py`'s own docstring says positions and goals "are
legitimately mutable, which is the point of C-09" — but it does carry foreign keys from `goal_funding`,
`goal_owners` and `decision_goals`, and a batch re-creation would rebuild the table those point at. A
plain `ADD COLUMN` touches none of that.

`tests/test_constraints.py` counts the append-only triggers on a database built by `alembic upgrade head`,
which is the check that would notice if a later author reached for batch mode here.

===========================================================================================================
DOWNGRADE
===========================================================================================================

Drops the column, and with it the record that a goal was frozen. Lossy, and it says so. SQLite has
supported `DROP COLUMN` since 3.35; on an older file the downgrade fails loudly rather than silently
leaving the column in place, which is the correct outcome for a migration nobody should be running
backwards over real data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b71fc02e83"
down_revision: Union[str, None] = "c8e40b23d971"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("goals", sa.Column("frozen_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("goals", "frozen_at")
