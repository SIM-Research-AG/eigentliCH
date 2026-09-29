"""a numbered baseline, and what it assumed about the household

Revision ID: c8e40b23d971
Revises: a3f1e90c7b45
Create Date: 2026-09-03

===========================================================================================================
WHAT THIS ADDS
===========================================================================================================

One table, `plan_versions`. It closes a gap this build has recorded against itself since the engines were
mapped: `services/engine_inputs` leaves the Scenario Generator's `base_snapshot_id` absent with the reason
*"prototype2 has no Snapshot ... a history rather than a numbered baseline"*, and the Befund reports that
to the member as `numbered_baseline`.

It also carries item 6's stamp, `household_as_of` — copied at capture, never joined at render time.

Nothing is backfilled. A member with three years of Decisions gets no retrospective version 1, for the
same reason `a3f1e90c7b45` refused to backfill a household: a baseline invented from a history is a
statement about what the plan was that nobody made, and every figure measured against it would inherit
that. The first version is the next one captured.

===========================================================================================================
THE FOUR HAZARDS THIS FILE IS WRITTEN AGAINST
===========================================================================================================

1. **`uq_plan_versions_one_standing` is a PARTIAL unique index and has to be created as one.** The rule is
   "at most one *standing* version per member". A plain unique index on `(member_id, status)` would also
   forbid a member having two superseded versions, which is the normal case after two adoptions. SQLite
   has supported partial indexes since 3.8.0; the `sqlite_where` clause below is what makes it partial, and
   `tests/test_constraints.py` reads `sqlite_master` to confirm the `WHERE` survived rather than trusting
   that it was requested.

2. **No `batch_alter_table`, so no trigger can be lost** (A63). This migration only CREATEs, and no table
   carrying one of the four append-only triggers is touched.

3. **`superseded_by_id` is a self-referential foreign key and is declared inline**, for the reason
   `a3f1e90c7b45` gives: SQLite cannot `ALTER TABLE ... ADD CONSTRAINT`, so adding it afterwards would
   force alembic into a batch re-creation of the table it had just made. Named, so a downgrade or a future
   batch operation has something to refer to.

4. **The CHECK constraints are written out here as literals rather than imported from the model.** Same
   convention and same reason as `b2c7e5a91f40` and `a3f1e90c7b45`: a migration describes the schema as of
   this revision, and importing a vocabulary tuple that a later commit widens would silently rewrite
   history. The two are held in step by a test, not by an import.

===========================================================================================================
THE FIVE CHECKS, AND WHAT EACH ONE ACTUALLY PREVENTS
===========================================================================================================

* `ck_plan_versions_household_stamp_complete` — a version naming a household but not what it assumed of
  it. That is item 6's whole defect wearing a NULL, so it is refused at the storage layer.
* `ck_plan_versions_adoption_complete` — an `adopted_at` with no Decision behind it, or a Decision with no
  adoption. Item 2 needs every adoption to name its author; a half-set pair would make one unanswerable.
* `ck_plan_versions_superseded_names_successor` — a superseded version with no successor, or a
  proposed/standing one that has one. Either makes the history unreadable in one direction.
* `ck_plan_versions_no_self_succession` — the shape a copy-paste in an adoption service produces.
* `ck_plan_versions_number_positive` — baselines are numbered from 1, so a 0 or a negative is a bug that
  would sort in front of every real version.

===========================================================================================================
DOWNGRADE
===========================================================================================================

Drops the table. Lossy and it says so: a plan version exists nowhere else, and the household assumption it
stamped is not recoverable from the household record — which is the point of copying it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e40b23d971"
down_revision: Union[str, None] = "a3f1e90c7b45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The vocabulary as of THIS revision. Written out rather than imported — see hazard 4.
_STATUSES = ("proposed", "standing", "superseded")
_STATUS_SQL = ", ".join(f"'{one}'" for one in _STATUSES)
_STANDING = "standing"
_SUPERSEDED = "superseded"


def upgrade() -> None:
    op.create_table(
        "plan_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("data_class", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("household_id", sa.String(length=32), nullable=True),
        sa.Column("household_as_of", sa.Date(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adoption_decision_id", sa.String(length=32), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_plan_versions"),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], name="fk_plan_versions_member"
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name="fk_plan_versions_household"
        ),
        sa.ForeignKeyConstraint(
            ["adoption_decision_id"], ["decisions.id"], name="fk_plan_versions_adoption_decision"
        ),
        # Hazard 3: declared inline, and named.
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["plan_versions.id"], name="fk_plan_versions_superseded_by"
        ),
        sa.UniqueConstraint("member_id", "number", name="uq_plan_versions_member_number"),
        sa.CheckConstraint(f"status IN ({_STATUS_SQL})", name="ck_plan_versions_status"),
        sa.CheckConstraint("number >= 1", name="ck_plan_versions_number_positive"),
        sa.CheckConstraint(
            "(household_id IS NULL) = (household_as_of IS NULL)",
            name="ck_plan_versions_household_stamp_complete",
        ),
        sa.CheckConstraint(
            "(adopted_at IS NULL) = (adoption_decision_id IS NULL)",
            name="ck_plan_versions_adoption_complete",
        ),
        sa.CheckConstraint(
            f"(status = '{_SUPERSEDED}') = (superseded_by_id IS NOT NULL)",
            name="ck_plan_versions_superseded_names_successor",
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_plan_versions_no_self_succession",
        ),
    )
    op.create_index("ix_plan_versions_member_id", "plan_versions", ["member_id"])
    op.create_index("ix_plan_versions_household_id", "plan_versions", ["household_id"])
    op.create_index("ix_plan_versions_status", "plan_versions", ["member_id", "status"])
    # Hazard 1. The `WHERE` is what makes this correct rather than over-restrictive.
    op.create_index(
        "uq_plan_versions_one_standing",
        "plan_versions",
        ["member_id"],
        unique=True,
        sqlite_where=sa.text(f"status = '{_STANDING}'"),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_versions_one_standing", table_name="plan_versions")
    op.drop_index("ix_plan_versions_status", table_name="plan_versions")
    op.drop_index("ix_plan_versions_household_id", table_name="plan_versions")
    op.drop_index("ix_plan_versions_member_id", table_name="plan_versions")
    op.drop_table("plan_versions")
