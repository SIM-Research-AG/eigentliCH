"""goals.occupancy — whether the member will live in the property

Revision ID: b7c2f1e48a30
Revises: 42975d339a0b
Create Date: 2026-09-04

A129. One nullable column, and the reason it has to exist rather than be derived: pillar 2 and pillar 3a
may be drawn only for a property the member occupies themselves, and nothing else on the `goals` row says
whether they will. The six real submissions named property goals «Wohneigentum», «Eigenheim», «Eigentum
kaufen» and «Ferienhaus kaufen» — only the last is unambiguous, and one member's goal says Wohneigentum
while their own question describes letting it out.

**Nullable, and null is a real answer.** Every goal that exists today has no occupancy, including four
property goals, and `services/property.assess` reports `could_not_be_determined` for them rather than
assuming the favourable case. Backfilling from the name would put a legal eligibility on a member's record
that nobody asked them about.

**No CHECK constraint on the values, deliberately.** The closed set lives in
`client/content/property-funding.json` and `services/property.occupancy_rule` refuses a value the record
does not declare — the same argument A127 makes for `member_facts.stated_key`. A CHECK here would have to
be migrated every time the record gains an occupancy, which is exactly the coupling the content record
exists to remove.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7c2f1e48a30"
down_revision: Union[str, Sequence[str], None] = "42975d339a0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("occupancy", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_column("occupancy")
