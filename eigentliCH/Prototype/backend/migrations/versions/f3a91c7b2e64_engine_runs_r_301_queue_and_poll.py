"""engine_runs — R-301's queue: submitted, running, done, failed

Revision ID: f3a91c7b2e64
Revises: a7c41b6f28de
Create Date: 2026-08-31 15:40:00.000000

R-301 forbids an engine call on a request thread and says "queue and poll". The queue was never built, so
`call_engine` had exactly one caller — `tools/publish_assumption_set.py` — and no member-facing path could
reach an engine at all. This is the table the queue is made of: the row IS the queue and the row IS the
status, so there is no second store of a run's state to drift out of agreement with this one.

**One table, no triggers, no batch operation.** `engine_runs` is a new table, so there is nothing to copy
and nothing to swap. That matters here specifically: `batch_alter_table` recreates a table and **drops its
triggers**, which is the mistake A63, A66 and A68 were all one form of. Nothing in this migration reaches
for `op.get_bind().engine` either — `op.create_table` runs on the migration's own connection, which is the
whole of the lesson from those three.

**No data migration and nothing backfilled.** There are no historical runs: before this revision there was
no way to start one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from eigentlich.models.run import RUN_STATUSES


# revision identifiers, used by Alembic.
revision: str = "f3a91c7b2e64"
down_revision: Union[str, Sequence[str], None] = "a7c41b6f28de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "engine_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        # Nullable: `tools/` submits runs at a terminal on nobody's behalf, and this column is the OWNER of
        # the run rather than a claim that the payload names a member.
        sa.Column("member_id", sa.String(length=32), nullable=True),
        sa.Column("engine", sa.String(length=60), nullable=False),
        # `sa.Enum` on SQLite is a VARCHAR with a CHECK constraint, which is what `create_all` produces
        # from the same declaration. The names come from the model rather than being retyped here: A63's
        # cause was a migration and a model disagreeing about a detail nobody re-read.
        sa.Column("status", sa.Enum(*RUN_STATUSES, name="run_status"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("timeout_s", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # C-04: classification is a column, not a convention. K2 — the payload can carry the member's plan.
        #
        # **This column and `created_at` are in the order the mixins declare them**, so the DDL this
        # migration produces is byte-identical to `create_all`'s. It was the other way round first and the
        # only difference was column order — harmless, and worth removing anyway: A63 and A68 were both a
        # migrated schema differing from the declared one, and a reader comparing the two should find
        # nothing to have to dismiss.
        sa.Column("data_class", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_engine_runs_member_id", "engine_runs", ["member_id"])
    op.create_index("ix_engine_runs_engine", "engine_runs", ["engine"])
    # The claim query is `WHERE status = 'submitted' ORDER BY created_at`, which is the one read the worker
    # makes on every wake-up.
    op.create_index("ix_engine_runs_status", "engine_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_engine_runs_status", table_name="engine_runs")
    op.drop_index("ix_engine_runs_engine", table_name="engine_runs")
    op.drop_index("ix_engine_runs_member_id", table_name="engine_runs")
    op.drop_table("engine_runs")
