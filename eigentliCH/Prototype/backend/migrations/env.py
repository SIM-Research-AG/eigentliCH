"""Alembic environment.

Autogenerate reads `eigentlich.models.Base.metadata`, so the schema follows the models rather than being
maintained twice. The append-only triggers are NOT part of `metadata` — they are installed by
`db.install_append_only_triggers` and re-asserted by the migration that creates their tables, because a
trigger that only exists in `create_all` would be missing from every real database.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eigentlich.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", f"sqlite:///{BACKEND / 'eigentlich.db'}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def refuse_broken_foreign_keys(connection) -> None:
    """`PRAGMA foreign_key_check` after the migrations, and raise if it finds anything.

    This is the other half of turning enforcement off below. `foreign_key_check` reports every violating
    row in the whole database — table, rowid, and which constraint — and it works with enforcement off,
    which is precisely why it is the right instrument here: the check is explicit, it names what is wrong,
    and it runs inside the migration transaction, so raising rolls the whole upgrade back rather than
    leaving a database that half satisfies its own schema.

    It is deliberately stronger than what enforcement during the run would have given. Per-statement
    enforcement can only refuse the statement in front of it; this looks at the finished result.
    """
    broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if not broken:
        return
    listed = "\n".join(
        f"    {row[0]}: rowid {row[1]} references {row[2]} (foreign key #{row[3]})" for row in broken
    )
    raise RuntimeError(
        "The migration left rows that violate a foreign key, so it has been rolled back:\n"
        f"{listed}\n"
        "Foreign keys are not enforced statement by statement during a migration — see the pragma in "
        "`run_migrations_online` and why it has to be off — so this check is what stands in for it. Fix "
        "the data or the migration; do not remove the check."
    )


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # **Foreign key enforcement is off for the duration of the migrations, and it has to be.**
        #
        # `db.py` turns `PRAGMA foreign_keys=ON` on every connection, because a `ForeignKey` in SQLite is
        # decorative without it. But SQLite cannot alter a column in place, so alembic's batch mode
        # rebuilds the table: copy the rows out, **DROP the original**, rename the copy back. With
        # enforcement on, `DROP TABLE` performs an implicit `DELETE FROM` first, and any child row
        # pointing at that table refuses it — `curator_sessions` has `curator_session_events` pointing at
        # every one of its rows, so the drop fails on any database that has ever recorded a consultation.
        # It succeeded in the test suite and on a fresh file only because those tables were empty, which
        # is A68's shape exactly: the path with real rows in it was the path nothing took.
        #
        # **Set here, and not inside a migration.** `PRAGMA foreign_keys` is documented as a no-op inside
        # a transaction; this connection has executed nothing yet, so it is the one place in the run where
        # the pragma provably takes effect. `PRAGMA defer_foreign_keys` looks like the transaction-safe
        # alternative and is a trap in the other direction — SQLite switches it off at every COMMIT, and a
        # migration that has only run SELECTs and DDL is in autocommit, so it is switched off by the
        # implicit commit of the statement that set it. Measured, not assumed.
        #
        # **On the DBAPI cursor, not `connection.exec_driver_sql`, and this one cost an hour.** Any
        # statement through the SQLAlchemy `Connection` autobegins its transaction. `begin_transaction()`
        # below then sees a connection already in one and returns a context that commits nothing, so the
        # whole upgrade is rolled back when the block exits — every migration appears to run, alembic
        # reports success, and the file on disk is unchanged. Going round SQLAlchemy's bookkeeping is the
        # point here rather than a shortcut: `conn.in_transaction()` is False before and after this.
        #
        # What replaces the enforcement is `refuse_broken_foreign_keys` below, which runs
        # `PRAGMA foreign_key_check` on the finished result before the transaction commits.
        if connection.dialect.name == "sqlite":
            cursor = connection.connection.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rewrites the table instead. Without it
            # the first constraint change on this schema would be unmigratable.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
            refuse_broken_foreign_keys(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
