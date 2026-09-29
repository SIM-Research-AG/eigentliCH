"""C-06 at the storage layer: every prepared option carries a consequence

Revision ID: a7c41b6f28de
Revises: ed7a417e4348
Create Date: 2026-08-30 20:12:00.000000

The CHECK constraint counts the array. It cannot look inside it — SQLite prohibits subqueries in a CHECK
and `json_each` is a table-valued function — so two options with no `consequence` key persisted through
any path that skipped the ORM validator, `Session.bulk_insert_mappings` among them. C-06 says an action
item exists only if it carries the options AND THEIR CONSEQUENCES; the store enforced only the count.

**No data migration.** The triggers are BEFORE triggers on new writes. Rows already in the table are not
re-checked, because a migration that deleted a member's action items to satisfy a constraint would be
destroying the member's material to make a report come out right. If any exist they are found by reading,
not by this.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


#: **Inlined on 20 September 2026, and the reason is worth a line.** This migration imported these from
#: `eigentlich.models.action`, which made a historical migration depend on live model code. A168 deleted
#: C-06 and with it the constants, and this file stopped importing — a migration that cannot run is a
#: migration that has lost the history it records. The statements below are byte-for-byte what the model
#: generated on the day this revision was written, and they will not change again.
OPTION_CONTENT_TRIGGERS = (
    "trg_action_items_option_content_insert",
    "trg_action_items_option_content_update",
)

_CONDITION = (
    "json_type(NEW.prepared_options) = 'array' "
    "AND json_array_length(NEW.prepared_options) >= 2 "
    "AND EXISTS (SELECT 1 FROM json_each(NEW.prepared_options) AS each "
    "WHERE json_type(each.value) <> 'object' "
    "OR json_extract(each.value, '$.label') IS NULL "
    "OR json_extract(each.value, '$.label') = '' "
    "OR json_extract(each.value, '$.consequence') IS NULL "
    "OR json_extract(each.value, '$.consequence') = '')"
)

_MESSAGE = (
    "action_items: C-06 - every prepared option carries a label and a consequence. An option without a "
    "stated consequence is a label, and a label is what C-06 exists to forbid."
)


def option_content_trigger_statements() -> list[str]:
    return [
        f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {verb} ON action_items "
        f"WHEN {_CONDITION} BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END;"
        for name, verb in zip(OPTION_CONTENT_TRIGGERS, ("INSERT", "UPDATE"))
    ]


# revision identifiers, used by Alembic.
revision: str = "a7c41b6f28de"
down_revision: Union[str, Sequence[str], None] = "ed7a417e4348"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Install the two content triggers.

    **On `op.get_bind()`, never on `.engine`.** A63, A66 and A68 were all one mistake: trigger DDL run
    through `engine.begin()` opens a second connection outside the migration's transaction, so the CREATEs
    land against a database the migration has not finished changing and the statement quietly does
    nothing. `get_bind()` is the migration's own connection.
    """
    connection = op.get_bind()
    for statement in option_content_trigger_statements():
        connection.execute(sa.text(statement))


def downgrade() -> None:
    connection = op.get_bind()
    for name in OPTION_CONTENT_TRIGGERS:
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
