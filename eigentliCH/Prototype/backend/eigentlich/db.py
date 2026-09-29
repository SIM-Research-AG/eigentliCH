"""Engine, session, and the three constraints that are enforced by the store rather than by callers.

  C-09  a plan mutation without a linked Decision raises, in `before_flush` AND in `before_execute`
  R-040 a Decision cannot be updated or deleted, in `before_flush` and by trigger
  C-10  the curator audit table rejects UPDATE and DELETE, by trigger

**Why `before_flush` and not a decorator on the service.** A service function that writes the Decision is
the convenient path, and convenience is not enforcement — the guard has to hold for code that never heard
of the service, including a future maintainer's one-line fix in a REPL. C-09 says a plan mutation without a
decision "is a constraint violation, not a warning", and a listener on the session is the narrowest place
that sees every write regardless of who made it.

**Why relationships and not id arrays.** `before_flush` runs before INSERT, so a new Position has no id.
The guard matches on object identity through `Decision.linked_positions` / `linked_goals`, which hold the
pending objects themselves. This is the reason `Decision` models its links as relationships — see the note
in `models/decision.py`.

**Why there is a second C-09 guard, one layer down.** `before_flush` sees the ORM unit of work and nothing
else, and three writes that never enter it were demonstrated against this file:
`session.execute(insert(Position.__table__))`, `session.execute(update(Position.__table__))` — R-123's own
case — and `Session.bulk_save_objects([Goal(...)])`, which is an ORM call that skips the unit of work.
`positions` and `goals` carry no append-only trigger (they are legitimately mutable, which is the point of
C-09), so `before_flush` was the ONLY guard and all three walked past it. `_refuse_unvetted_plan_dml`
below listens on the Engine's `before_execute` and refuses INSERT / UPDATE / DELETE against a plan table
unless it is being emitted by a flush that `before_flush` has just vetted. That is one statement-level
chokepoint every SQLAlchemy write must pass, whoever built it.

**What that second guard does NOT cover, stated rather than papered over.**

  * a `text()` statement is matched by parsing its leading tokens — `INSERT INTO <t>`, `UPDATE <t>`,
    `DELETE FROM <t>`. That catches the REPL one-liner, which is the case that matters. It does not catch
    SQL that reaches a plan table by a name this parser does not resolve (a view, an `ATTACH`ed alias, a
    `WITH` statement whose final DML target is a plan table).
  * a DBAPI cursor obtained from the raw connection (`engine.raw_connection().cursor().execute(...)`)
    bypasses SQLAlchemy's execution pipeline entirely and is therefore invisible here. So does `sqlite3`
    opened on the file directly. Nothing short of a database-level guard would see either.
  * **and there is no database-level guard for C-09, deliberately.** `decisions` and
    `curator_session_events` get one because "never UPDATE, never DELETE" is a property of a single
    statement. C-09 is not: it says a plan write must be accompanied by a Decision *in the same
    transaction*, and a SQLite trigger fires per statement, before the Decision and its link rows are
    written. There is no deferred-constraint mechanism in SQLite to check it at COMMIT instead. A trigger
    that fired on every INSERT into `positions` would refuse the legitimate path as readily as the illegal
    one, which is a guard that gets removed within a week. The honest statement is: C-09 holds for
    everything that goes through SQLAlchemy, and does not hold against a raw DBAPI cursor.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import Delete, Insert, TextClause, Update, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Decision, DecisionImmutable, PlanMutable


#: Set on `session.info` while R-231's erasure runs. The C-09 guard stands down for exactly that, and
#: for nothing else — a flag with a name is auditable in a way that a special case buried in a condition
#: is not.
ERASING = "eigentlich.erasing"


class _ErasureToken:
    """The type of the one value that stands the C-09 guard down. See `_ERASURE_TOKEN`."""

    __slots__ = ()

    def __repr__(self) -> str:  # so a stack trace or a session dump names it
        return "<eigentlich erasure token>"


#: The ONLY value that switches the C-09 guard off. `session.info[ERASING] = True` does not, and
#: `test_a_bare_true_does_not_disable_the_c09_guard` holds that.
#:
#: **What this buys and what it does not.** It does not make the escape hatch unreachable: Python has no
#: private, and any module that imports this name can set it. What it changes is that standing C-09 down is
#: now a single greppable identifier rather than a bare boolean any caller holding the Session could set by
#: accident or by convenience. `test_only_erasure_reaches_the_erasure_token` greps the package and fails if
#: a second module acquires it, so "erasure is the only thing that sets it" is checked rather than asserted.
_ERASURE_TOKEN = _ErasureToken()


class PlanMutationWithoutDecision(Exception):
    """C-09. Raised in `before_flush` for ORM writes and in `before_execute` for everything else, so the
    transaction never reaches the database either way."""


# -- the flush bracket -----------------------------------------------------------------------------
#
# `before_flush` has already checked every plan object the unit of work is about to write. The statements
# that flush then emits must be allowed through the statement-level guard below, and they are the only
# writes to a plan table that may be. Thread-local because a Session belongs to one thread for the
# duration of a flush, and FastAPI runs each request on its own.
#
# Set at the END of `before_flush`, after every raise, so a rejected flush never marks itself vetted.
# Cleared on flush completion AND on both rollback events, because a flush whose SQL fails never reaches
# `after_flush_postexec` — leaving the mark set would silently disarm the guard for the rest of the
# session, which is precisely the failure mode A63 and A66 are about.
_flush_state = threading.local()


def _begin_vetted_flush() -> None:
    _flush_state.vetted = True


def _end_vetted_flush() -> None:
    _flush_state.vetted = False


def _in_vetted_flush() -> bool:
    return getattr(_flush_state, "vetted", False)


def _describe(obj: object) -> str:
    return f"{type(obj).__name__}(id={getattr(obj, 'id', None)!r}, label={getattr(obj, 'label', getattr(obj, 'name', None))!r})"


@event.listens_for(Session, "before_flush")
def _enforce_constraints(session: Session, _flush_context: object, _instances: object) -> None:
    _check(session)
    # Reached only if nothing above raised: this flush may now emit SQL against a plan table.
    _begin_vetted_flush()


@event.listens_for(Session, "after_flush_postexec")
def _release_after_flush(session: Session, _flush_context: object) -> None:
    _end_vetted_flush()


@event.listens_for(Session, "after_commit")
def _release_after_commit(session: Session) -> None:
    _end_vetted_flush()


@event.listens_for(Session, "after_rollback")
def _release_after_rollback(session: Session) -> None:
    _end_vetted_flush()


@event.listens_for(Session, "after_soft_rollback")
def _release_after_soft_rollback(session: Session, _previous_transaction: object) -> None:
    """The path a flush takes when its SQL raises: `Session._flush` catches, rolls back, re-raises.

    Without this, an IntegrityError mid-flush would leave the thread marked as being inside a vetted
    flush and the statement-level guard below would wave everything through afterwards.
    """
    _end_vetted_flush()


def _check(session: Session) -> None:
    # -- R-040: decisions are append-only ---------------------------------------------------------
    for obj in session.dirty:
        if isinstance(obj, Decision) and session.is_modified(obj, include_collections=True):
            changed = [
                attr.key
                for attr in inspect(obj).attrs
                if attr.history.has_changes()
            ]
            raise DecisionImmutable(
                f"R-040: a Decision is immutable once written; {_describe(obj)} was modified "
                f"({', '.join(changed)}). Record a correction as a new Decision with `corrects_id` set "
                f"— the UI offers 'record a correction', never 'edit' (R-162)."
            )
    for obj in session.deleted:
        if isinstance(obj, Decision):
            raise DecisionImmutable(
                f"R-040: a Decision cannot be deleted; {_describe(obj)}. The record of what was decided is "
                f"the thing that survives a change of adviser (S-07) and it does not get tidied away."
            )

    # -- C-09: every plan mutation is covered by a Decision in this same flush ---------------------
    #
    # **One explicit exception: erasure.** R-231's erasure removes the member, and removing a plan is not
    # a change to one — there is no decision to record about a portfolio that will not exist, and the
    # Decision recording the REQUEST is written before erasure begins, by the caller.
    #
    # Marked on the session rather than inferred, and named so it reads as an exception in a stack trace
    # rather than as an absence. The value has to be `_ERASURE_TOKEN` itself — a bare `True` set by a
    # caller who happened to know the key does not stand the guard down. `services/erasure.py` is the only
    # module that imports the token, and a test greps for that rather than trusting this comment.
    if session.info.get(ERASING) is _ERASURE_TOKEN:
        return

    mutated: list[object] = []
    for obj in session.new:
        if isinstance(obj, PlanMutable):
            mutated.append(obj)
    for obj in session.dirty:
        if isinstance(obj, PlanMutable) and session.is_modified(obj, include_collections=True):
            mutated.append(obj)
    for obj in session.deleted:
        if isinstance(obj, PlanMutable):
            mutated.append(obj)

    if not mutated:
        return

    covered: set[int] = set()
    for obj in session.new:
        if isinstance(obj, Decision):
            covered |= {id(o) for o in obj.covered_plan_objects()}

    uncovered = [obj for obj in mutated if id(obj) not in covered]
    if uncovered:
        raise PlanMutationWithoutDecision(
            "C-09: every material change to a member's plan produces a Decision Record, written in the "
            "same transaction. Uncovered: "
            + "; ".join(_describe(obj) for obj in uncovered)
            + ". Use `eigentlich.services.plan.mutate_plan(...)`, which writes both, or link the objects on "
            "the Decision explicitly."
        )


# ================================================================ C-09, one layer below the unit of work


_plan_tables: frozenset[str] | None = None


def plan_table_names() -> frozenset[str]:
    """The tables C-09 calls "the plan", read off the `PlanMutable` mappers rather than listed.

    Same reasoning as the marker class itself: a future plan entity is covered by inheriting from
    `PlanMutable`, not by someone remembering to add a string to a tuple in this file.
    """
    global _plan_tables
    if _plan_tables is None:
        _plan_tables = frozenset(
            mapper.class_.__tablename__
            for mapper in Base.registry.mappers
            if issubclass(mapper.class_, PlanMutable)
        )
    return _plan_tables


def _bare_table_name(token: str) -> str:
    """`"positions",` / `` `positions` `` / `[positions]` / `main.positions` -> `positions`."""
    name = token.strip().strip(",;()")
    for quote in ('"', "'", "`", "[", "]"):
        name = name.replace(quote, "")
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name.lower()


#: `INSERT OR REPLACE INTO`, `UPDATE OR IGNORE`, `INSERT OR ROLLBACK INTO` — SQLite's conflict clauses sit
#: between the verb and the table, and the table is what this needs to find.
_CONFLICT_CLAUSE = ("OR", "ROLLBACK", "ABORT", "FAIL", "IGNORE", "REPLACE")


def _text_dml_target(statement: str) -> str | None:
    """The table a raw `text()` DML statement writes to, or None if it is not DML this can resolve.

    Deliberately a token walk and not a regex. It resolves the three shapes a person types into a REPL or
    a maintenance script — `INSERT INTO t`, `UPDATE t`, `DELETE FROM t` — and returns None for anything
    else, including a statement that merely *mentions* a plan table in a subquery. Returning None means
    "not recognised", and the caller lets it through: this layer is a second net under the structural
    check below, not a SQL parser, and pretending otherwise would start refusing alembic's batch copies.
    """
    tokens = statement.split()
    if not tokens:
        return None
    upper = [token.upper() for token in tokens]
    verb = upper[0]

    if verb in ("INSERT", "REPLACE"):
        for index, token in enumerate(upper[:6]):
            if token == "INTO" and index + 1 < len(tokens):
                return _bare_table_name(tokens[index + 1])
        return None

    if verb == "UPDATE":
        index = 1
        while index < len(upper) and upper[index] in _CONFLICT_CLAUSE:
            index += 1
        return _bare_table_name(tokens[index]) if index < len(tokens) else None

    if verb == "DELETE":
        if len(upper) > 2 and upper[1] == "FROM":
            return _bare_table_name(tokens[2])
        return None

    return None


def _dml_target(clauseelement: object) -> str | None:
    """The table a statement writes to, for the statement kinds this guard understands."""
    if isinstance(clauseelement, (Insert, Update, Delete)):
        table = getattr(clauseelement, "table", None)
        return None if table is None else str(table.name).lower()
    if isinstance(clauseelement, TextClause):
        return _text_dml_target(str(clauseelement.text))
    return None


@event.listens_for(Engine, "before_execute")
def _refuse_unvetted_plan_dml(
    _connection: object,
    clauseelement: object,
    _multiparams: object,
    _params: object,
    _execution_options: object,
) -> None:
    """C-09 at the statement level: no write reaches `positions` or `goals` unvetted.

    This is the guard that `session.execute(insert(...))`, `session.execute(update(...))` and
    `Session.bulk_save_objects(...)` all have to pass — all three emit an ordinary INSERT or UPDATE
    through the connection and none of them enters `before_flush`. It is on `Engine` rather than on one
    engine instance so that a Session built by hand in a REPL is covered too.

    The ORM's own flush statements are let through because `before_flush` has just checked the objects
    they are made of, and only for the duration of that flush.
    """
    if _in_vetted_flush():
        return
    target = _dml_target(clauseelement)
    if target is None or target not in plan_table_names():
        return
    raise PlanMutationWithoutDecision(
        f"C-09: every material change to a member's plan produces a Decision Record, written in the same "
        f"transaction. This statement writes {target!r} outside the unit of work, where no Decision can "
        f"be linked to it — a Core insert/update, a bulk_save_objects, or raw SQL. Use "
        f"`eigentlich.services.plan.mutate_plan(...)`, which writes both. C-09 calls this a constraint "
        f"violation, not a warning, and it does not become one because the write went round the ORM."
    )


#: SQLite refuses UPDATE and DELETE on the append-only tables at the storage layer. The `before_flush`
#: guard above covers the ORM; a trigger covers everything else, which is what "cannot be persisted" and
#: "rejects update and delete" actually claim.
_APPEND_ONLY_TRIGGERS = {
    "decisions": "R-040 — a correction is a new record referencing the prior one",
    "curator_session_events": "C-10 — immutable append-only audit table",
}


def append_only_trigger_statements() -> list[str]:
    """The CREATE TRIGGER statements, so a caller inside a transaction can run them on its own connection.

    Separated from `install_append_only_triggers` because running them on a *different* connection is a
    real bug rather than a style question: R-231's erasure drops the triggers, redacts, and re-creates
    them. When the re-creation went through `engine.begin()` it opened a second transaction, so the
    CREATEs committed before the DROPs did and the erasure left the database with no triggers at all —
    every append-only guarantee silently off. Found by erasing one account and counting.
    """
    statements: list[str] = []
    for table, reason in _APPEND_ONLY_TRIGGERS.items():
        for verb in ("UPDATE", "DELETE"):
            statements.append(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_{verb.lower()} "
                f"BEFORE {verb} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{table} is append-only: {reason}'); "
                f"END;"
            )
    return statements


def install_append_only_triggers(engine: Engine) -> None:
    """Install them in their own transaction. For setup and migrations, NOT for code already in one."""
    with engine.begin() as connection:
        for statement in append_only_trigger_statements():
            connection.execute(text(statement))


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
    """Foreign keys are off by default in SQLite, which makes every ForeignKey above decorative."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    from sqlalchemy import create_engine

    if url is None:
        db_path = Path(__file__).resolve().parent.parent / "eigentlich.db"
        url = f"sqlite:///{db_path}"
    return create_engine(url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Schema for tests and first run. Alembic owns the real schema — see `migrations/`."""
    Base.metadata.create_all(engine)
    install_append_only_triggers(engine)
