"""lower the age floor to 18 (A50)

The specification's NG-05 set the floor at 25 and gave its reason as "no minor-consent flows". The owner
lowered it on 30 August 2026 so that andersCH can serve younger people. It moved to 18 rather than being
removed, because 18 is the age at which NG-05's stated reason stops applying: everyone admitted is an
adult in Swiss law, so the promise NG-05 was actually making is kept while its number is not.

**This is a CHECK constraint, and SQLite cannot alter one in place.** Batch mode rewrites the table, which
is why `render_as_batch` is on in `migrations/env.py`. Existing rows are unaffected — every member already
recorded is 25 or older and therefore satisfies the looser constraint. The downgrade is written and is
safe only while that stays true: it will fail if any member has since registered between 18 and 24, which
is correct behaviour rather than a bug. A downgrade that silently dropped those members would be worse.

Revision ID: 28fc468464dc
Revises: 13d2a5ebfe32
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op

revision = "28fc468464dc"
down_revision = "13d2a5ebfe32"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_members_age_floor"
OLD_FLOOR = 25
NEW_FLOOR = 18


def upgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, f"age_at_registration >= {NEW_FLOOR}")


def downgrade() -> None:
    # Deliberately not guarded with a DELETE. If a member aged 18-24 exists, this raises — and that is the
    # right outcome: restoring the old floor is a policy reversal, and what happens to the people it would
    # exclude is a decision, not something a migration should make on its own.
    with op.batch_alter_table("members") as batch:
        batch.drop_constraint(CONSTRAINT, type_="check")
        batch.create_check_constraint(CONSTRAINT, f"age_at_registration >= {OLD_FLOOR}")
