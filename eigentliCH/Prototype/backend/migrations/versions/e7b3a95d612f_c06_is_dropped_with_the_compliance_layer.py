"""C-06 is dropped with the compliance layer (A168)

Revision ID: e7b3a95d612f
Revises: c4e18b2f9d07
Create Date: 2026-09-20 11:48:31.207744

C-06 required an action item to carry at least two prepared options, each with a label and a consequence.
The owner dropped it on 20 September 2026 with the rest of the compliance layer. A168 has the reasoning;
the short version is that the property could be satisfied vacuously — nothing ever checked that two
consequences *differed* — so two triggers and a CHECK were enforcing to the letter a rule whose content
nobody had defined.

Two things come off the store here:

  * the two content triggers from `a7c41b6f28de`, dropped by name;
  * the `ck_action_items_prepared_options_min` CHECK from the spine migration, which needs a table
    rebuild because SQLite cannot drop a constraint in place.

**The table rebuild is the dangerous half, and A63 / A66 / A68 are why this file is careful.** Recreating
`action_items` drops every trigger attached to it. The two being removed are the only ones it carries —
verified below rather than assumed, because "this table happens to have nothing else on it" is exactly
the assumption that has cost this build its append-only triggers three separate times. The check runs
against the live schema, and the migration refuses rather than silently dropping something it was not
asked to drop.

`batch_alter_table` is used here, unlike `c4e18b2f9d07`, because dropping a CHECK genuinely requires the
rebuild. The unique index `uq_action_items_derived_cause` is NOT C-06's, is re-created by the batch
operation from the model's `__table_args__`, and is verified afterwards.

**No data migration.** Rows already in the table are untouched. Nothing is deleted to satisfy the removal
of a constraint, for the same reason `a7c41b6f28de` refused to delete rows to satisfy its addition.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7b3a95d612f"
down_revision: Union[str, Sequence[str], None] = "c4e18b2f9d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

C06_TRIGGERS = (
    "trg_action_items_option_content_insert",
    "trg_action_items_option_content_update",
)

CHECK_NAME = "ck_action_items_prepared_options_min"
DERIVED_CAUSE_INDEX = "uq_action_items_derived_cause"


def _triggers_on(connection, table: str) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :t"),
            {"t": table},
        )
    }


def upgrade() -> None:
    """Drop the two content triggers and the minimum-length CHECK."""
    connection = op.get_bind()

    # 1. What is actually attached, read from the live schema rather than assumed.
    before = _triggers_on(connection, "action_items")
    unexpected = before - set(C06_TRIGGERS)
    if unexpected:  # pragma: no cover - a guard against a schema this migration was not written for
        raise RuntimeError(
            f"action_items carries triggers this migration did not expect: {sorted(unexpected)}. "
            f"The table rebuild below would drop them silently, which is A63, A66 and A68's failure. "
            f"Add them to the re-creation explicitly, or drop this migration and think again."
        )

    for name in C06_TRIGGERS:
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))

    # 2. The CHECK. SQLite cannot drop one in place, so the table is rebuilt.
    with op.batch_alter_table("action_items", schema=None) as batch_op:
        batch_op.drop_constraint(CHECK_NAME, type_="check")

    # 3. The rebuild must not have cost anything that was not C-06's.
    after = _triggers_on(connection, "action_items")
    if after:  # pragma: no cover - nothing should survive, and nothing should have been added
        raise RuntimeError(f"action_items unexpectedly carries triggers after the rebuild: {sorted(after)}")

    indexes = {
        row[0]
        for row in connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'action_items'")
        )
    }
    if DERIVED_CAUSE_INDEX not in indexes:  # pragma: no cover - the batch op re-creates it
        raise RuntimeError(
            f"{DERIVED_CAUSE_INDEX} did not survive the table rebuild. It is what makes the plan "
            f"derivations idempotent and it is not C-06's; without it every read of the action list "
            f"writes another copy of every derived item."
        )


def downgrade() -> None:
    """Put the CHECK and the two triggers back, exactly as `a7c41b6f28de` wrote them."""
    connection = op.get_bind()

    with op.batch_alter_table("action_items", schema=None) as batch_op:
        batch_op.create_check_constraint(CHECK_NAME, "json_array_length(prepared_options) >= 2")

    condition = (
        "json_type(NEW.prepared_options) = 'array' "
        "AND json_array_length(NEW.prepared_options) >= 2 "
        "AND EXISTS (SELECT 1 FROM json_each(NEW.prepared_options) AS each "
        "WHERE json_type(each.value) <> 'object' "
        "OR json_extract(each.value, '$.label') IS NULL "
        "OR json_extract(each.value, '$.label') = '' "
        "OR json_extract(each.value, '$.consequence') IS NULL "
        "OR json_extract(each.value, '$.consequence') = '')"
    )
    message = (
        "action_items: C-06 - every prepared option carries a label and a consequence. An option without "
        "a stated consequence is a label, and a label is what C-06 exists to forbid."
    )
    for name, verb in zip(C06_TRIGGERS, ("INSERT", "UPDATE")):
        connection.execute(
            sa.text(
                f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {verb} ON action_items "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, '{message}'); END;"
            )
        )
