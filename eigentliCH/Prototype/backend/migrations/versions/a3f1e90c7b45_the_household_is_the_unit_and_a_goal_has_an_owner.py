"""the household is the unit, and a goal has an owner

Revision ID: a3f1e90c7b45
Revises: b2c7e5a91f40
Create Date: 2026-09-03

===========================================================================================================
WHAT THIS ADDS
===========================================================================================================

Five tables — `households`, `household_members`, `goal_owners`, and the two that let a `Decision` name
them, `decision_households` and `decision_household_members` — and nothing else.

**The two decision-link tables are in this migration rather than a later one because without them the
other three are unusable.** `Household` and `HouseholdMember` are `PlanMutable`, so C-09's `before_flush`
guard refuses any transaction that writes one without a Decision covering it; and a Decision can only cover
an object it can link. Shipping the household tables first and the link tables second would produce one
revision at which every household write raises `PlanMutationWithoutDecision`. No column on an
existing table changes, no data is rewritten, and every row that exists before this runs is valid after it.

That is deliberate and it is the reason this migration is short. The obvious alternative was to put
`household_id` on `members`, `positions` and `goals` and backfill a single-member household for everyone.
It was not done, for two reasons worth having on the record:

1. **A backfilled household is a stated fact nobody stated.** `households.composition_as_of` carries the
   date a member says their composition describes. Inventing one for every existing member — today's date?
   their registration date? — would write a K2 fact with a source of "the migration", and the currency
   horizon that runs off that date would then expire against a date no human ever gave. C-02's argument
   about invented rates is the same argument; this is an invented *date*, which is worse only in that it
   looks more innocent.

2. **`member_id` on the plan tables is not wrong, it is narrower.** A `Position` belongs to a person, and
   it still does. What was missing was the household the people are in, and that is a new relation rather
   than a correction to an old one. Adding `household_id` to `positions` would make every existing row
   need one, which is (1) again.

So a member acquires a household when they answer the composition question, and until then
`services/household.py` reports "not stated" rather than a household of one that they never described. The
single-member case is a household with one row in it — but it is one the member confirmed.

===========================================================================================================
THE FOUR HAZARDS THIS FILE IS WRITTEN AGAINST
===========================================================================================================

1. **`batch_alter_table` is not used here, and that is the point** (A63). This migration only CREATEs. The
   four append-only triggers live on `decisions` and `curator_session_events` and no table carrying one is
   touched, so nothing can be dropped by a table re-creation that does not happen.

2. **`households.succeeds_household_id` is a self-referential foreign key, and SQLite creates it inline.**
   It is declared inside `create_table` rather than added afterwards with `create_foreign_key`, because
   SQLite cannot `ALTER TABLE ... ADD CONSTRAINT` and alembic would have to fall back on a batch
   re-creation of the table it just made. Named explicitly (`fk_households_succeeds`) so the downgrade and
   any future batch operation have something to refer to; an unnamed constraint on SQLite is one nobody
   can drop.

3. **`household_members` gains its CHECK constraints at create time, from the model's own vocabulary.**
   The `kind` list is written out here as a literal rather than imported from `eigentlich.models.household`,
   which is the convention this build follows for a reason stated in
   `b2c7e5a91f40`: a migration describes the schema *as of this revision*, and importing a tuple that a
   later commit widens would silently rewrite history. `tests/test_constraints.py` asserts the two agree
   today, which is the check that actually holds them together.

4. **`goal_owners` is a pure association table with a composite primary key**, exactly like `goal_funding`
   beside it. No surrogate id, no uniqueness constraint bolted on afterwards: the pair IS the identity, and
   giving it an `id` would permit the same owner twice on one goal, which downstream would read as joint
   ownership between a person and themselves.

===========================================================================================================
DOWNGRADE
===========================================================================================================

Drops the three tables. Lossy, and it says so: a household composition and a goal's owner exist nowhere
else, so downgrading discards them. That is true of every create-table migration in this build and is not
a reason to make this one pretend otherwise.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1e90c7b45"
down_revision: Union[str, None] = "b2c7e5a91f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The vocabulary as of THIS revision. Written out rather than imported — see hazard 3.
_KINDS = ("adult", "dependant")
_STATED_BY = ("member", "curator")

_KIND_SQL = ", ".join(f"'{kind}'" for kind in _KINDS)
_STATED_BY_SQL = ", ".join(f"'{who}'" for who in _STATED_BY)


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("data_class", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("composition_as_of", sa.Date(), nullable=False),
        sa.Column("stated_by", sa.String(length=7), nullable=False),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("succeeds_household_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_households"),
        # Hazard 2: declared inline, and named.
        sa.ForeignKeyConstraint(
            ["succeeds_household_id"], ["households.id"], name="fk_households_succeeds"
        ),
        sa.CheckConstraint(
            "succeeds_household_id IS NULL OR succeeds_household_id <> id",
            name="ck_households_no_self_succession",
        ),
        sa.CheckConstraint(f"stated_by IN ({_STATED_BY_SQL})", name="ck_households_stated_by"),
    )
    op.create_index("ix_households_closed_on", "households", ["closed_on"])
    op.create_index(
        "ix_households_succeeds_household_id", "households", ["succeeds_household_id"]
    )

    op.create_table(
        "household_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("data_class", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("household_id", sa.String(length=32), nullable=False),
        sa.Column("member_id", sa.String(length=32), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=9), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=True),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_household_members"),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name="fk_household_members_household"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], name="fk_household_members_member"
        ),
        sa.UniqueConstraint(
            "household_id", "member_id", name="uq_household_members_account_once"
        ),
        sa.CheckConstraint(f"kind IN ({_KIND_SQL})", name="ck_household_members_kind"),
        sa.CheckConstraint(
            "left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on",
            name="ck_household_members_left_after_joined",
        ),
    )
    op.create_index("ix_household_members_household_id", "household_members", ["household_id"])
    op.create_index("ix_household_members_member_id", "household_members", ["member_id"])

    op.create_table(
        "goal_owners",
        sa.Column("goal_id", sa.String(length=32), nullable=False),
        sa.Column("household_member_id", sa.String(length=32), nullable=False),
        # Hazard 4: the pair is the identity.
        sa.PrimaryKeyConstraint("goal_id", "household_member_id", name="pk_goal_owners"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], name="fk_goal_owners_goal"),
        sa.ForeignKeyConstraint(
            ["household_member_id"],
            ["household_members.id"],
            name="fk_goal_owners_household_member",
        ),
    )


    op.create_table(
        "decision_households",
        sa.Column("decision_id", sa.String(length=32), nullable=False),
        sa.Column("household_id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("decision_id", "household_id", name="pk_decision_households"),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decisions.id"], name="fk_decision_households_decision"
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["households.id"], name="fk_decision_households_household"
        ),
    )

    op.create_table(
        "decision_household_members",
        sa.Column("decision_id", sa.String(length=32), nullable=False),
        sa.Column("household_member_id", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint(
            "decision_id", "household_member_id", name="pk_decision_household_members"
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decisions.id"], name="fk_decision_household_members_decision"
        ),
        sa.ForeignKeyConstraint(
            ["household_member_id"],
            ["household_members.id"],
            name="fk_decision_household_members_household_member",
        ),
    )


def downgrade() -> None:
    op.drop_table("decision_household_members")
    op.drop_table("decision_households")
    op.drop_table("goal_owners")
    op.drop_index("ix_household_members_member_id", table_name="household_members")
    op.drop_index("ix_household_members_household_id", table_name="household_members")
    op.drop_table("household_members")
    op.drop_index("ix_households_succeeds_household_id", table_name="households")
    op.drop_index("ix_households_closed_on", table_name="households")
    op.drop_table("households")
