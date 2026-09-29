"""a curator is revoked, not deleted (A160)

Revision ID: c4e18b2f9d07
Revises: aef04e0d683b
Create Date: 2026-09-20 09:12:04.551302

Three of A62's five left andersCH on 20 September 2026. `revoked_at` and `revoked_reason` are how the
table says so without losing the row, and `Curator.in_service` is the single predicate the four gates ask.

**Deliberately not `batch_alter_table`, and the reason is A63 / A66 / A68.** Batch mode recreates the
table, and a recreate drops whatever is attached to it. `curators` carries no trigger today, so the
upgrade would survive it — but "survives because the table happens to have nothing on it" is the kind of
accident that stops being true the week someone adds one, and this build has already lost its append-only
triggers twice that way. Both columns are nullable, so plain `ADD COLUMN` is all SQLite needs and nothing
is recreated. The downgrade uses batch because `DROP COLUMN` has no such luck, and it is the rarer path.

There is no data step here. The three revocations are seed state, not schema, and they are written by
`tools/seed_demo_accounts.py --revoke` so that a rebuilt database gets them the same way a migrated one
does. A migration that edits rows would put the list of names in a second place (rule 4 of the cull).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4e18b2f9d07"
down_revision: Union[str, Sequence[str], None] = "aef04e0d683b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("curators", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("curators", sa.Column("revoked_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("curators", schema=None) as batch_op:
        batch_op.drop_column("revoked_reason")
        batch_op.drop_column("revoked_at")
