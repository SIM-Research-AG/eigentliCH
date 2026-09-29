"""curator_sessions.curator_id becomes a real foreign key — A40's claim, A67's correction

Revision ID: 5dcf92664790
Revises: f4b1c07ad9e2
Create Date: 2026-08-31 21:02:51.021401

**What this closes.** A40 said `curator_id` "becomes a foreign key rather than a free string". That was
true of `AccessGrant` and false of `CuratorSession`, where it was a plain `String(120)` — so any string at
all could be written as the identified curator on the parent row of an append-only audit. A67 recorded the
correction and deferred the work; this is the work.

**Why it matters more here than on an ordinary table.** `curator_session_events` refuses UPDATE and DELETE
by trigger (C-10 / R-040). A wrong curator recorded against a session is therefore not correctable by the
usual means: the child rows that name the act cannot be rewritten and cannot be removed. A constraint that
has to hold *before* the row exists has to live in the storage layer, which is what this migration puts
there.

**This migration refuses rather than guesses, and that is the decision in it.** A session whose
`curator_id` names nobody cannot be repaired by a rule: deleting it is impossible (its `opened` event is in
a table that refuses DELETE, and the event references the session), and pointing it at *some* curator would
write a new false statement into an audit in order to satisfy a constraint whose only purpose is that the
audit be true. So the check runs first and stops the migration with the offending ids, and a human decides
what each one actually was. See A98 in `DECISIONS.md` for what was decided about the three rows in this
build's own development database.

**Two hazards this file is written against, both of which have cost this build a week each.**

  * `batch_alter_table` recreates the table and everything attached to it goes (A63). `curator_sessions`
    carries no trigger of its own today, so nothing is lost — but "today" is not a property a migration
    should rely on, and re-asserting the four `CREATE TRIGGER IF NOT EXISTS` statements is free. The check
    that matters is a trigger count on a database built by `alembic upgrade head`, not a reading of this
    file.
  * The re-creation runs on **`op.get_bind()`** and never on `.engine` (A68). `.engine` opens a second
    connection outside the migration's transaction; that connection sees the pre-swap schema, so
    `CREATE TRIGGER IF NOT EXISTS` becomes a no-op and the swap then commits without the triggers. That is
    exactly how A63's *fix* was itself broken for a week.

**A third hazard, found while writing this one, and fixed in `migrations/env.py` rather than here.** The
batch rebuild DROPs the original table, and `DROP TABLE` with foreign keys enforced performs an implicit
`DELETE FROM` that `curator_session_events` refuses for every session it references. So this migration
failed on the development database and passed on a fresh file, because a fresh file has no rows — A68's
shape again. `env.py` now turns enforcement off for the run, at the one point in it where the pragma
provably takes effect, and runs `PRAGMA foreign_key_check` on the finished result before committing. The
reasoning, including why the transaction-safe-looking `defer_foreign_keys` is a trap, is in that file.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from eigentlich.db import append_only_trigger_statements


# revision identifiers, used by Alembic.
revision: str = '5dcf92664790'
down_revision: Union[str, Sequence[str], None] = 'f4b1c07ad9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Named, not `None`. Alembic's autogenerate offers `create_foreign_key(None, ...)`, and an unnamed
#: constraint is one `downgrade()` cannot drop by name — a migration that can only go one way is a
#: migration nobody dares run.
FK_NAME = "fk_curator_sessions_curator_id_curators"

INDEX_NAME = "ix_curator_sessions_curator_id"


def _refuse_sessions_naming_nobody() -> None:
    """Stop the migration if any session names a curator that is not a row in `curators`.

    Run before the schema changes, so a database that would violate the new constraint is left exactly as
    it was rather than half-migrated. The message names the ids because the person who has to decide what
    each row actually recorded needs them, and because a refusal that says only "there is bad data" is a
    refusal somebody works around.
    """
    bind = op.get_bind()
    unresolvable = bind.execute(
        text(
            "SELECT s.id, s.curator_id FROM curator_sessions AS s "
            "LEFT JOIN curators AS c ON c.id = s.curator_id "
            "WHERE c.id IS NULL ORDER BY s.opened_at"
        )
    ).fetchall()
    if not unresolvable:
        return
    listed = "\n".join(f"    curator_sessions.id={row[0]!r} names curator_id={row[1]!r}" for row in unresolvable)
    raise RuntimeError(
        "C-10: this migration will not run, and will not repair the rows itself.\n\n"
        f"{len(unresolvable)} curator session(s) name a curator that is not a row in `curators`:\n"
        f"{listed}\n\n"
        "Each of these rows is the parent of an append-only event that cannot be rewritten or removed, so "
        "there is no rule this migration could apply that would not be a guess written into an audit. "
        "Decide per row what was actually recorded, correct `curator_sessions.curator_id` to the id of the "
        "curator it stood for (or insert the curator row it named, if that person is staff and simply has "
        "no row yet), write down which you did and why, and run the migration again."
    )


def _require_enforcement_suspended() -> None:
    """Read the pragma back, rather than trusting `env.py` to have set it.

    `env.py` turns `PRAGMA foreign_keys` off for the run, and it has to go round SQLAlchemy's transaction
    bookkeeping to do it — which is exactly the kind of arrangement that stops working silently when
    somebody tidies the file. If it stops working, the batch rebuild below fails with
    `FOREIGN KEY constraint failed` on `DROP TABLE`, on databases that have rows and not on empty ones. So
    the condition is measured here, where a failure names the cause instead of the symptom.
    """
    enforced = op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar()
    if enforced:
        raise RuntimeError(
            "Foreign key enforcement is on, and the table rebuild below will fail on any database that "
            "holds a curator session: DROP TABLE performs an implicit DELETE FROM, and every row in "
            "`curator_session_events` refuses it. `migrations/env.py` is supposed to have turned "
            "enforcement off for this run on the DBAPI cursor — check that it still does, and that "
            "`PRAGMA foreign_key_check` still runs there afterwards."
        )


def _restore_triggers() -> None:
    """Re-assert the four append-only triggers on the migration's OWN connection.

    `op.get_bind()`, never `op.get_bind().engine` — see this module's docstring and A68. Idempotent:
    every statement is `CREATE TRIGGER IF NOT EXISTS`.
    """
    bind = op.get_bind()
    for statement in append_only_trigger_statements():
        bind.execute(text(statement))


def upgrade() -> None:
    """Upgrade schema."""
    _refuse_sessions_naming_nobody()
    _require_enforcement_suspended()

    with op.batch_alter_table('curator_sessions', schema=None) as batch_op:
        batch_op.alter_column('curator_id',
               existing_type=sa.VARCHAR(length=120),
               type_=sa.String(length=32),
               existing_nullable=False)
        batch_op.create_index(batch_op.f(INDEX_NAME), ['curator_id'], unique=False)
        batch_op.create_foreign_key(FK_NAME, 'curators', ['curator_id'], ['id'])

    _restore_triggers()


def downgrade() -> None:
    """Downgrade schema.

    Reversible on purpose. The column goes back to a free `String(120)`, which is the hole A67 named — so
    a downgrade is a deliberate step backwards and not a rollback anybody should take casually.
    """
    _require_enforcement_suspended()

    with op.batch_alter_table('curator_sessions', schema=None) as batch_op:
        batch_op.drop_constraint(FK_NAME, type_='foreignkey')
        batch_op.drop_index(batch_op.f(INDEX_NAME))
        batch_op.alter_column('curator_id',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=120),
               existing_nullable=False)

    _restore_triggers()
