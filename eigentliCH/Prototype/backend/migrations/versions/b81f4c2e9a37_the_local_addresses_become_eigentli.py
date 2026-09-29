"""the local addresses become eigentli.local (A174)

Revision ID: b81f4c2e9a37
Revises: e7b3a95d612f
Create Date: 2026-09-21 09:24:11.883021

`@andersch.local` becomes `@eigentli.local`, and `@kurator.andersch.local` becomes
`@kurator.eigentli.local`. The domain is **eigentli**, not eigentlich — the casing table in
`TASK-rename-eigentlich-2026-09-20.md` sets it, to match the website at eigentli.tech.

**This is a data migration and not a find-and-replace, which is why it is here at all.** These are login
credentials. 71 member credentials and 6 curator rows hold them, and a member whose address changed
without their password following it cannot get in. Nothing about the passwords is touched: the hash, the
salt and the iteration count are columns of their own and this statement does not mention them.

**A62's two namespaces are preserved, and the order of the two statements is what preserves them.**
Curators live at `@kurator.andersch.local` so that an address can never be ambiguous about which table it
belongs to. `@kurator.andersch.local` ends with `@andersch.local`'s own suffix only if you match
carelessly — `kurator.andersch.local` does not end with `@andersch.local`, so the two patterns are
disjoint and the order does not actually matter. It is written most-specific-first anyway, because the
next person to add a namespace should find that habit here rather than discover why it was needed.

**On `op.get_bind()` and not `.engine`.** A63, A66 and A68 were all one mistake: DDL or DML run through
`engine.begin()` opens a second connection outside the migration's transaction, so the work lands
against a database the migration has not finished changing. `get_bind()` is the migration's own
connection.

**The append-only triggers are counted before and after.** This migration creates and drops nothing, so
they cannot be affected — and they have been lost three times in this repository by migrations whose
authors were equally sure. Counting costs one query.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b81f4c2e9a37"
down_revision: Union[str, Sequence[str], None] = "e7b3a95d612f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_MEMBER, NEW_MEMBER = "@andersch.local", "@eigentli.local"
OLD_CURATOR, NEW_CURATOR = "@kurator.andersch.local", "@kurator.eigentli.local"


def _triggers(connection) -> int:
    return connection.execute(
        sa.text("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'")
    ).scalar_one()


def _swap(connection, old: str, new: str) -> None:
    """Rewrite one namespace in both tables that hold an address."""
    for table in ("credentials", "curators"):
        connection.execute(
            sa.text(
                f"UPDATE {table} SET email = replace(email, :old, :new) WHERE email LIKE :like"
            ),
            {"old": old, "new": new, "like": f"%{old}"},
        )


def upgrade() -> None:
    connection = op.get_bind()
    before = _triggers(connection)

    # Most specific first. See the module docstring on why the two are disjoint anyway.
    _swap(connection, OLD_CURATOR, NEW_CURATOR)
    _swap(connection, OLD_MEMBER, NEW_MEMBER)

    left = connection.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT email FROM credentials WHERE email LIKE '%andersch.local'"
            "  UNION ALL"
            "  SELECT email FROM curators WHERE email LIKE '%andersch.local')"
        )
    ).scalar_one()
    if left:  # pragma: no cover - the two patterns above cover every shape that exists
        raise RuntimeError(
            f"{left} address(es) still end in andersch.local after the rewrite. A namespace this "
            f"migration does not know about is a namespace whose members cannot sign in."
        )

    after = _triggers(connection)
    if after != before:  # pragma: no cover - nothing here creates or drops one
        raise RuntimeError(f"append-only triggers changed during the rewrite: {before} -> {after}")


def downgrade() -> None:
    connection = op.get_bind()
    _swap(connection, NEW_CURATOR, OLD_CURATOR)
    _swap(connection, NEW_MEMBER, OLD_MEMBER)
