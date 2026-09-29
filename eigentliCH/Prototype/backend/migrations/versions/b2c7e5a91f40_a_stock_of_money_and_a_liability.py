"""a stock of money, and a liability that cannot be stored ambiguously

Revision ID: b2c7e5a91f40
Revises: 5dcf92664790
Create Date: 2026-09-01

===========================================================================================================
WHAT THIS MIGRATES, AND WHAT IT DELIBERATELY DOES NOT
===========================================================================================================

`MAGNITUDE_UNITS` gained `chf`, and `positions` gained `stock_kind` plus two CHECK constraints.

**The enum widening needs no DDL on SQLite, and this file says so rather than pretending otherwise.**
SQLAlchemy's `Enum` defaults to `create_constraint=False`, so `magnitude_unit` is a bare `VARCHAR(14)` in
every database this build has ever produced — verified by reading `sqlite_master` on
`backend/eigentlich.db`, which is at revision `5dcf92664790` and carries no CHECK on that column. A
migration "widening the enum" would therefore be a migration that changed nothing, and a comment claiming
it had would be worse than no comment. What *is* asserted below is that the column really is unconstrained
after this runs, so the day somebody turns `create_constraint` on, this migration fails instead of the
member's `chf` position failing at runtime.

On a backend with a native enum type (Postgres) the widening would be a real `ALTER TYPE`. `_check_units`
is where that goes, and it raises rather than guessing.

===========================================================================================================
THE THREE HAZARDS THIS FILE IS WRITTEN AGAINST
===========================================================================================================

1. **`batch_alter_table` recreates the table and everything attached to it goes** (A63). The four
   append-only triggers live on `decisions` and `curator_session_events`, not on `positions`, so nothing
   *should* be lost here — but "should" and "today" are not properties a migration may rely on, and four
   `CREATE TRIGGER IF NOT EXISTS` statements are free. The check that counts is a trigger count on a
   database built by `alembic upgrade head`; see
   `tests/test_constraints.py::test_the_stock_unit_migration_leaves_every_append_only_trigger_standing`.

2. **The re-creation runs on `op.get_bind()` and never on `.engine`** (A68). `.engine` opens a SECOND
   connection outside this migration's transaction; it sees the pre-swap schema, `CREATE TRIGGER IF NOT
   EXISTS` becomes a no-op, and the swap then commits with no triggers at all. That is how A63's own fix
   was broken for a week.

3. **SQLite reflection does not return CHECK constraints, so a naive batch recreate would silently DROP
   `ck_positions_magnitude_has_unit`.** This is the constraint that keeps a magnitude and its unit
   together, and losing it is the whole point of the exercise going backwards. `copy_from` is therefore
   mandatory here rather than stylistic: the table below is the pre-migration `positions` written out in
   full — every column, the CHECK, the foreign key and the index — because with `copy_from` alembic uses
   what it is given and reflects nothing, so anything omitted here is anything dropped. Proven by
   `test_the_migrated_positions_table_keeps_all_three_check_constraints`, which reads `sqlite_master`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from eigentlich.db import append_only_trigger_statements
from eigentlich.models.plan import MAGNITUDE_UNITS, STOCK_KINDS


# revision identifiers, used by Alembic.
revision: str = "b2c7e5a91f40"
down_revision: Union[str, Sequence[str], None] = "5dcf92664790"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The two constraints this migration adds. The stock-unit list is **pinned to what it was at this
#: revision** rather than imported from `models/plan.py`: a migration describes the database at one point in
#: history, and one that read a live constant would silently rewrite its own past the day a second stock
#: unit was added. What keeps the two honest is a test, not an import —
#: `test_the_model_and_the_migration_state_the_same_constraint` compiles `Position.__table_args__` and
#: compares the SQL, so adding `eur` to `STOCK_UNITS` fails the suite until a NEW migration exists.
_STOCK_UNIT_SQL = ", ".join(f"'{unit}'" for unit in ("chf",))

NEW_CHECKS = {
    "ck_positions_stock_kind_iff_stock": (
        f"(stock_kind IS NOT NULL) = (COALESCE(magnitude_unit, '') IN ({_STOCK_UNIT_SQL}))"
    ),
    "ck_positions_stock_is_not_negative": (
        f"COALESCE(magnitude_unit, '') NOT IN ({_STOCK_UNIT_SQL}) OR magnitude >= 0"
    ),
}


def _positions_before() -> sa.Table:
    """`positions` exactly as revision `5dcf92664790` leaves it.

    Hazard 3 in the docstring: with `copy_from` alembic reflects nothing, so this has to be complete —
    columns in their stored order, the CHECK, the foreign key and the index. It is written out rather than
    imported from `eigentlich.models` on purpose: the model is the *destination*, and using it as the source
    is how a migration silently starts depending on a future edit to the model.
    """
    metadata = sa.MetaData()
    table = sa.Table(
        "positions",
        metadata,
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("member_id", sa.String(length=32), nullable=False),
        sa.Column(
            "role",
            sa.Enum("growth", "income", "stabilisation", "protection", name="role"),
            nullable=False,
        ),
        sa.Column(
            "capital_type", sa.Enum("human", "financial", name="capital_type"), nullable=False
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column(
            "magnitude_unit",
            sa.Enum("chf_per_year", "share_of_total", name="magnitude_unit"),
            nullable=True,
        ),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("time_basis", sa.String(length=80), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("data_class", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "liquidity",
            sa.Enum("immediate", "within_months", "within_years", "illiquid", name="liquidity"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        # Hazard 3. Absent from this list means dropped from the database.
        sa.CheckConstraint(
            "(magnitude IS NULL) = (magnitude_unit IS NULL)",
            name="ck_positions_magnitude_has_unit",
        ),
    )
    sa.Index("ix_positions_member_id", table.c.member_id)
    return table


def _check_units() -> None:
    """Refuse to run if the unit vocabulary is enforced by a type this migration does not alter.

    The premise of "no DDL is needed for the widening" is that `magnitude_unit` is a bare VARCHAR. If a
    future edit sets `create_constraint=True`, or the deployment moves to a backend with a native enum,
    that premise is false and a `chf` position would be refused by the store while every layer above it
    accepted one. Cheaper to fail here, with the reason, than to find it in a member's 422.
    """
    from eigentlich.models.plan import Position

    column = Position.__table__.c.magnitude_unit
    enum_type = column.type
    if getattr(enum_type, "create_constraint", False):
        raise RuntimeError(
            "Position.magnitude_unit now creates a CHECK constraint from its enum values. A migrated "
            "database still carries the two-value constraint from revision bd3fedd3d5cb, so `chf` would "
            "be refused by the store. Add the constraint swap to this migration (drop and recreate it "
            f"inside the batch block below) before shipping. Units: {list(MAGNITUDE_UNITS)}"
        )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError(
            f"this migration's no-DDL-for-the-widening argument is specific to SQLite, where "
            f"SQLAlchemy renders Enum as VARCHAR. On {bind.dialect.name!r} `magnitude_unit` is a native "
            f"type and needs an explicit ALTER TYPE ... ADD VALUE for each of {list(MAGNITUDE_UNITS)}. "
            f"Write it before running this."
        )


def _restore_triggers() -> None:
    """Re-assert the four append-only triggers on the migration's OWN connection.

    `op.get_bind()`, never `op.get_bind().engine` — hazard 2 above and A68. Idempotent: every statement is
    `CREATE TRIGGER IF NOT EXISTS`, so this is a repair on a database that lost them and a no-op on one
    that did not.
    """
    bind = op.get_bind()
    for statement in append_only_trigger_statements():
        bind.execute(text(statement))


def upgrade() -> None:
    """Upgrade schema."""
    _check_units()

    with op.batch_alter_table(
        "positions", schema=None, copy_from=_positions_before()
    ) as batch_op:
        batch_op.add_column(
            sa.Column("stock_kind", sa.Enum(*STOCK_KINDS, name="stock_kind"), nullable=True)
        )
        for name, condition in NEW_CHECKS.items():
            batch_op.create_check_constraint(name, condition)

    # Every existing row is left with `stock_kind` NULL, and that is correct rather than a gap to backfill:
    # no row can carry the stock unit yet — it did not exist until this revision — so
    # `ck_positions_stock_kind_iff_stock` is satisfied by every one of them. A backfill of `'asset'` would
    # be inventing a side of the balance sheet for magnitudes that are not on one.

    _restore_triggers()


def downgrade() -> None:
    """Downgrade schema.

    **A position stated in `chf` cannot survive this**, and the downgrade refuses rather than mangling one.
    Dropping `stock_kind` from a liability would turn a debt into a holding of the same size, which is the
    single worst outcome in the whole feature; dropping the row would delete a member's own statement about
    their plan. Neither is a migration's decision to make, so it stops and names the ids.
    """
    bind = op.get_bind()
    stocks = [
        row[0]
        for row in bind.execute(
            text("SELECT id FROM positions WHERE magnitude_unit IN (:unit)"), {"unit": "chf"}
        )
    ]
    if stocks:
        raise RuntimeError(
            "these positions are stated as a stock in francs and this revision removes the unit's only "
            f"honest representation: {stocks}. Downgrading would either drop `stock_kind` — turning every "
            "liability into a holding of the same amount — or drop the rows, which deletes what a member "
            "said about their own plan. Decide per position and restate them before downgrading."
        )

    with op.batch_alter_table("positions", schema=None) as batch_op:
        for name in NEW_CHECKS:
            batch_op.drop_constraint(name, type_="check")
        batch_op.drop_column("stock_kind")

    _restore_triggers()
