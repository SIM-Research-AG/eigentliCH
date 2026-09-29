"""An adversarial pass over the ten constraints, written to break them rather than to confirm them.

Every test here names one claim from build-spec §2 or §11 and tries to produce the thing the claim says
cannot happen. Where the attempt succeeds the test is marked `xfail(strict=True)`: the suite stays green,
and the finding is recorded as an executable statement of what is not yet true rather than as prose in a
review that will be closed.

**Why several of these exist at all.** A20, A57, A59 and A63 are four recorded cases of a guarantee that
looked held and was not, and A63 is the sharpest: a migration switched off the `decisions` triggers while
634 tests stayed green. The tests below assume that pattern did not stop with A63, and two of them found
it again — see `test_a_migrated_database_has_all_four_append_only_triggers` and
`test_the_existing_migration_trigger_test_never_migrates_anything`.

Nothing here modifies application source. Where a defect cannot be tested without changing source it is
reported to the owner instead.

**Most of these now pass, and that is the point of keeping them.** The audit that produced this file found
twelve defects. As each was fixed its `xfail(strict=True)` was removed rather than the test being deleted,
so what was written as a demonstration of a hole is now the regression test that keeps it shut. Several
docstrings below are therefore written in the present tense about a defect that no longer exists; they are
left as they were, because the description of how a guarantee failed is the most useful thing to read when
deciding whether a later change has broken it again.

Two were inverted rather than un-marked, because they asserted that something forbidden *succeeded*:
`test_a_migrated_database_refuses_to_rewrite_a_decision_with_raw_sql` used to require the UPDATE to go
through, and now requires it to raise.

What remains `xfail(strict=True)` is a real, open hole. `strict` matters: if one of them starts passing the
suite fails, so a hole cannot be quietly closed without someone noticing and recording why.
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import insert, select, text, update

from eigentlich import llm
from eigentlich.db import ERASING, PlanMutationWithoutDecision
from eigentlich.log_filter import REDACTION, install as install_log_filter
from eigentlich.models import (
    ActionItem,
    Attendance,
    Base,
    Capability,
    CapabilityAssertion,
    Gathering,
    Goal,
    Position,
)
from eigentlich.services import register_member, store_item
from eigentlich.services.export import export_member
from eigentlich.services.vault import VaultStore

BACKEND = Path(__file__).resolve().parent.parent
AWARE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _migrate_to(database: Path) -> subprocess.CompletedProcess:
    """Run the real migrations into `database`, in a subprocess.

    A subprocess rather than an in-process `command.upgrade`, because `migrations/env.py` calls
    `fileConfig(alembic.ini)`, which reconfigures the logging module for the whole interpreter and would
    reach into every other test in this suite.
    """
    script = (
        "from alembic.config import Config\n"
        "from alembic import command\n"
        "c = Config(%r)\n"
        "c.set_main_option('script_location', %r)\n"
        "c.set_main_option('sqlalchemy.url', %r)\n"
        "command.upgrade(c, 'head')\n"
    ) % (str(BACKEND / "alembic.ini"), str(BACKEND / "migrations"), f"sqlite:///{database}")
    return subprocess.run(
        [sys.executable, "-c", script], cwd=str(BACKEND), capture_output=True, text=True
    )


def _triggers(database: Path) -> set[str]:
    engine = sqlalchemy.create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
    finally:
        engine.dispose()


def test_a_migrated_database_has_all_four_append_only_triggers(tmp_path):
    """R-040 on a database the migrations actually built. Was xfail; now holds.

    This is the guarantee the whole append-only story rests on: the ORM guard in `db.py` covers the ORM,
    and the trigger is what makes "a Decision cannot be altered" a fact about the store rather than about
    the callers. When this test was written, a deployment built by `alembic upgrade head` had no
    `trg_decisions_no_update`, and a single `UPDATE decisions SET choice=...` rewrote the record that is
    supposed to survive a change of adviser.

    The cause was `install_append_only_triggers(op.get_bind().engine)` in migration `ee959786d912` —
    `.engine` opens a SECOND connection outside the migration's transaction, which still saw the pre-swap
    table with its triggers attached, so `CREATE TRIGGER IF NOT EXISTS` did nothing and the batch swap
    then committed the drop. It re-creates them on `op.get_bind()` now.

    `create_all` installs the triggers directly, which is why the whole suite and the development
    database looked correct throughout. Only the migrated path showed it.
    """
    database = tmp_path / "migrated.db"
    result = _migrate_to(database)
    assert database.exists(), f"the migration did not run: {result.stderr[-2000:]}"

    names = _triggers(database)
    missing = {
        "trg_decisions_no_update",
        "trg_decisions_no_delete",
        "trg_curator_session_events_no_update",
        "trg_curator_session_events_no_delete",
    } - names
    assert not missing, f"missing after migrating: {sorted(missing)}; present: {sorted(names)}"


def test_a_migrated_database_refuses_to_rewrite_a_decision_with_raw_sql(tmp_path):
    """The consequence of the finding above, now inverted because the finding was fixed.

    This test was written to *demonstrate* the defect: it asserted that `UPDATE decisions SET choice=…`
    succeeded on a migrated database, and it passed, which was the whole problem. The migration now
    re-creates the triggers on its own connection instead of reaching for a second one through `.engine`,
    so the same statement raises. Kept in its inverted form rather than deleted — a test that once caught a
    live defect is the one most worth keeping pointed at the same spot.
    """
    database = tmp_path / "migrated.db"
    result = _migrate_to(database)
    if not database.exists():  # pragma: no cover - the migration is expected to run
        pytest.skip(f"migrations did not run here: {result.stderr[-500:]}")

    engine = sqlalchemy.create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO decisions (id, member_id, author, question, options_considered, "
                    "choice, data_class, created_at) VALUES ('d1', NULL, 'member', 'Q', '[]', "
                    "'as recorded', 2, '2026-01-01 00:00:00')"
                )
            )
        with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(text("UPDATE decisions SET choice='rewritten' WHERE id='d1'"))
        with engine.connect() as connection:
            after = connection.execute(text("SELECT choice FROM decisions WHERE id='d1'")).scalar()
    finally:
        engine.dispose()

    assert after == "as recorded"


def test_the_existing_migration_trigger_test_never_migrates_anything(tmp_path):
    """A20's shape, inside the test written to prevent A63: a guard that cannot fail.

    `test_every_append_only_trigger_survives_a_full_migration` points alembic at a temporary database by
    setting `ANDERSCH_DB_URL` in the subprocess environment. Nothing reads that variable — not
    `migrations/env.py`, not `alembic.ini`, not `db.py`. So the subprocess migrates the DEVELOPMENT
    database instead, the temporary file is never created, and the test takes its documented fallback:
    `Base.metadata.create_all()` followed by `install_append_only_triggers()`. It then asserts that the
    triggers it has just installed by hand are installed. It has never once run a migration.

    That is why the defect above survived the fix for A63.
    """
    sources = [
        path for path in BACKEND.rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "test_adversarial.py"
    ] + [BACKEND / "alembic.ini"]
    readers = sorted(
        path.relative_to(BACKEND).as_posix()
        for path in sources
        if "ANDERSCH_DB_URL" in path.read_text(encoding="utf-8")
    )
    assert readers == ["tests/test_constraints.py"], (
        "ANDERSCH_DB_URL is now read somewhere; re-check whether the fallback branch in "
        f"test_every_append_only_trigger_survives_a_full_migration is still dead. Readers: {readers}"
    )

    # And the fallback is demonstrably the branch that runs: the same invocation, verbatim.
    database = tmp_path / "migrated.db"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), "upgrade", "head"],
        cwd=str(BACKEND),
        env={**os.environ, "ANDERSCH_DB_URL": f"sqlite:///{database}"},
        capture_output=True,
        text=True,
    )
    assert not database.exists(), (
        "the env override now works, so the existing test migrates for real and this finding is closed"
    )


def test_no_migration_rewrites_an_append_only_table_without_restoring_its_triggers():
    """A tripwire for the next A63, since the existing one does not trip.

    `batch_alter_table` recreates a SQLite table and everything attached to it goes with it. Any
    migration that batches an append-only table must put the triggers back — by calling
    `install_append_only_triggers` or by issuing the CREATE TRIGGER itself, as the spine migration does.
    This is a source scan, so it holds for a migration written next month by someone who never read A63,
    and it passes today only because both such migrations do one or the other. Whether what they do
    WORKS is the separate question the xfail above answers.

    **`curator_sessions` is in the set although it carries no trigger of its own**, and that is the point.
    It is the **parent** of `curator_session_events`, which does. A98's foreign-key migration batched it,
    and batch mode DROPs the original table — with foreign keys enforced, `DROP TABLE` performs an implicit
    `DELETE FROM` that the child's append-only trigger refuses for every session it references. So the
    migration **failed on the development database and passed on an empty one**, which is A68's shape a
    third time and exactly the asymmetry this file exists to catch.

    A table whose *children* are append-only is as dangerous to batch as an append-only table itself, and
    the agent that hit it reported the set being one short rather than editing this file. Reported, so
    added.
    """
    append_only = {"decisions", "curator_session_events", "curator_sessions"}
    offenders: list[str] = []
    for path in sorted((BACKEND / "migrations" / "versions").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        batched = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "batch_alter_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        touched = sorted(batched & append_only)
        restores = "install_append_only_triggers" in source or "CREATE TRIGGER" in source
        if touched and not restores:
            offenders.append(f"{path.name} batches {touched} and never reinstalls the triggers")
    assert not offenders, "; ".join(offenders)


# ==================================================================== C-04, the logging filter


K3_VALUE = "Pensionskassenausweis Helvetia 2026"


def _isolated_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers = []
    logger.filters = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


def test_the_filter_redacts_a_named_k3_field_when_installed_before_the_handler():
    """Proof the two xfails below are about *when* install runs, not about a filter that never worked.

    A20 and A63 were both absence tests that passed because nothing was there to find. This plants the
    exact value the next two tests hunt for, in the arrangement the filter was designed for, and asserts
    it is redacted — so a leak in the other arrangements is a statement about the arrangement.
    """
    logger = _isolated_logger("adv.c04.ordered")
    buffer = io.StringIO()
    logger.addHandler(logging.StreamHandler(buffer))
    install_log_filter(logger)

    logging.getLogger("adv.c04.ordered.child").info("stored vault item title=%s", K3_VALUE)

    assert K3_VALUE not in buffer.getvalue()
    assert REDACTION in buffer.getvalue()


def test_the_filter_still_redacts_when_the_handler_is_added_after_install():
    """Break C-04 by ordering alone, in the order the application actually starts in.

    This is the whole of C-04's runtime half. "A logging filter drops the top class by field name" is a
    claim about the deployed process, and in the deployed process every record from every `eigentlich.*`
    logger reaches a handler that carries no filter. The constraint test in test_constraints.py builds
    its own filter and attaches it by hand, so it never exercises `install()` at all.
    """
    logger = _isolated_logger("adv.c04.late")
    install_log_filter(logger)                        # import time
    buffer = io.StringIO()
    logger.addHandler(logging.StreamHandler(buffer))  # uvicorn, afterwards

    logging.getLogger("adv.c04.late.child").info("stored vault item title=%s", K3_VALUE)

    assert K3_VALUE not in buffer.getvalue(), f"a K3 value reached a log line: {buffer.getvalue()!r}"


def test_a_k3_value_inside_an_exception_does_not_reach_the_log():
    """Break C-04 through the traceback rather than through the message.

    Vault extraction is exactly the code that raises with the document it was parsing in the message, and
    `logger.exception(...)` is exactly what a service writes in that except block. The value then lands
    in the log with its field name attached, which is the case the filter claims to own.
    """
    logger = _isolated_logger("adv.c04.exc")
    buffer = io.StringIO()
    logger.addHandler(logging.StreamHandler(buffer))
    install_log_filter(logger)

    try:
        raise ValueError(f"could not parse title={K3_VALUE}")
    except ValueError:
        logger.exception("vault extraction failed")

    assert K3_VALUE not in buffer.getvalue(), (
        f"a K3 value reached a log line through the traceback: {buffer.getvalue()!r}"
    )


# ==================================================================== C-09, the plan-mutation guard


def test_a_core_insert_cannot_create_a_position_without_a_decision(session, member):
    """Break C-09 with the narrowest possible bypass: the same Session, one layer down.

    Unlike R-040 and C-10, `positions` and `goals` carry no trigger, so `before_flush` is the only guard
    there is. C-09 says a plan mutation without a linked decision "is a constraint violation, not a
    warning"; here it is neither.
    """
    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(
            insert(Position.__table__).values(
                id="adv-core-insert", member_id=member.id, role="growth", capital_type="financial",
                label="Smuggled in", magnitude=250000.0, magnitude_unit="chf",
                stock_kind="asset", active=True,
                data_class=2, created_at=AWARE,
            )
        )
        session.commit()


def test_a_core_update_cannot_change_a_magnitude_without_a_decision(session, member):
    """Break C-09 on the edit path rather than the create path.

    Changing what a position is worth is the material change C-09 exists for, and it is the one most
    likely to be done by a maintenance script rather than through the service.
    """
    from eigentlich.services import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Record it?", choice="Yes") as decision:
        position = Position(
            member_id=member.id, role="growth", capital_type="financial", label="Securities",
            magnitude=1000.0, magnitude_unit="chf",
            # `stock_kind` is required beside the stock unit and was not here when this test was written,
            # because the unit did not exist and `"chf"` was a string nothing validated. It does now, and
            # `ck_positions_stock_kind_iff_stock` refuses a franc balance that does not say whether it is
            # owned or owed — so this fixture had to say. The subject of the test is C-09 and is unchanged.
            stock_kind="asset",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(
            update(Position.__table__)
            .where(Position.__table__.c.id == position.id)
            .values(magnitude=999999.0)
        )
        session.commit()


def test_bulk_save_objects_cannot_write_a_goal_without_a_decision(session, member):
    """Break C-09 with an ORM method rather than with SQL.

    A Core insert can be argued to be "past the ORM". `Session.bulk_save_objects` cannot: it takes model
    instances, it is documented as the fast path for exactly this kind of write, and it is what someone
    reaches for when importing a member's goals from a spreadsheet.
    """
    with pytest.raises(PlanMutationWithoutDecision):
        session.bulk_save_objects([Goal(member_id=member.id, name="Imported goal")])
        session.commit()


def test_the_c09_guard_is_not_asleep_in_this_fixture(session, member):
    """Proof the three xfails above are bypasses and not a guard that was never armed.

    The same session, the same member, the ordinary ORM path — and it raises. Without this, "C-09 did not
    fire" would be indistinguishable from "C-09 does not run in this test's setup".
    """
    session.add(Goal(member_id=member.id, name="Plainly uncovered"))
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()


def test_the_erasure_escape_hatch_cannot_be_set_by_something_other_than_erasure(session, member):
    """Break C-09 by using its documented exception for something that is not erasure.

    The flag is deliberately named so it reads as an exception in a stack trace, and that is a good
    decision. It is still an unauthenticated opt-out of the constraint the spec calls "not a warning",
    available to anything that can reach the Session.
    """
    session.info[ERASING] = True
    try:
        session.add(Goal(member_id=member.id, name="Written under the erasure flag"))
        with pytest.raises(PlanMutationWithoutDecision):
            session.commit()
    finally:
        session.info.pop(ERASING, None)


# ==================================================================== C-06, prepared options
# ==================================================================== C-08, Market Place ordering


def _listed(session, *, name, roles, assertions, attendances):
    """One provider listing created the way the application creates them, and nothing else."""
    from eigentlich.services.marketplace import apply_to_be_listed, declare, publish

    person = register_member(session, age_at_registration=41, display_name=name)
    session.flush()
    for index in range(assertions):
        capability_id = f"cap-{name}-{index}"
        session.add(Capability(id=capability_id, statement="can explain something"))
        session.flush()
        session.add(CapabilityAssertion(
            member_id=person.id, capability_id=capability_id, evidence_kind="assessment",
            assessed_by="eigentliCH", assessed_at=AWARE,
        ))
    for index in range(attendances):
        gathering = Gathering(kind="lecture", title=f"L{name}{index}", held_on=dt.date(2026, 1, 1))
        session.add(gathering)
        session.flush()
        session.add(Attendance(member_id=person.id, gathering_id=gathering.id, attended=True))
    session.flush()

    listing = apply_to_be_listed(
        session, member_id=person.id, display_name=name, title=f"{name} listing",
        domain="financial", qualification_pipeline="capability", roles=roles,
    )
    declare(session, listing_id=listing.id, kind="none_declared", statement="none", declared_by="x")
    publish(session, listing.id)
    session.flush()
    return person, listing


def test_a_listings_standing_reflects_its_providers_real_evidence(session):
    """Break C-08 from the opposite side: not "can order be bought" but "is there an order at all".

    R-203 names three ordering inputs. Two of them are dead on the real write path — they carry values
    only in the seed fixture, which is where every ordering test in test_marketplace.py gets them from.
    A provider with six recorded capability assertions and six attendances ranks identically to one with
    none, and the C-08 test that proves a fee cannot move the order is proving it about an order that is
    two thirds constant.
    """
    from eigentlich.services.marketplace import listing_ordering_inputs

    _person, listing = _listed(session, name="Evidenced", roles=["growth"], assertions=6, attendances=6)
    session.commit()

    inputs = listing_ordering_inputs(listing, ("growth",))
    assert (inputs.capability_evidence, inputs.community_presence) == (6, 6), (
        f"standing_inputs never picked up the provider's real evidence: {listing.standing_inputs}"
    )


def test_declaring_every_role_does_not_outrank_genuine_standing(session):
    """Break C-08 through the input a provider controls rather than the one the test scans for.

    `test_listing_ranking_cannot_read_fee_fields` is a good test and it holds: money written onto a
    Provider row moves nothing. But C-08's requirement is that ordering "cannot be bought", and the
    commercial incentive here is to declare four roles instead of one. That is a supplier-controlled
    input to the ranking, it is unaudited, and it dominates the two inputs meant to be earned.
    """
    from eigentlich.services.marketplace import browse

    _listed(session, name="Generalist", roles=["growth", "income", "stabilisation", "protection"],
            assertions=1, attendances=0)
    _listed(session, name="Specialist", roles=["growth"], assertions=6, attendances=6)
    session.commit()

    order = [entry["title"] for entry in browse(session, roles=["growth", "income"])["entries"]]
    assert order[0] == "Specialist listing", f"the provider that ticked every role came first: {order}"


# ==================================================================== R-154, the export


#: Tables whose absence from the export is a decision rather than an omission: a password hash and a live
#: session token are not "material the member owns" in any sense that helps them.
EXPORT_MAY_OMIT = frozenset({"credentials", "sessions"})

def test_the_export_covers_every_member_owned_table():
    """R-154, measured against what "everything the member owns" actually is. Was xfail; now holds.

    The most consequential omission was `capability_assertions`: R-191 says the capability statements ARE
    the member's progression and that there is nothing else to show them, so a member who exported and left
    took no record of it. `member_offers` are things they wrote, `attendances` is their own history, and
    `access_grants` is the record of whom they let into their vault and when. Five tables were missing.

    **This test used to compare against a hardcoded list, which is why it could go stale and did.** It now
    reads the export's own registry, so the export and the thing measuring it cannot drift apart: the only
    way to pass is to actually carry the table.
    """
    from eigentlich.services.member_data import EXPORTED_TABLES

    owned = {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if "member_id" in mapper.class_.__table__.columns
    }
    assert owned, "no member-owned tables were discovered; this test would pass vacuously"

    missing = sorted(owned - set(EXPORTED_TABLES) - EXPORT_MAY_OMIT)
    assert not missing, f"member-owned tables absent from the export: {missing}"


def test_the_export_carries_every_column_of_the_tables_it_does_cover(session, member, tmp_path):
    """The half of R-154 that does hold, asserted so the finding above is scoped rather than sweeping.

    `_row` reads `obj.__table__.columns`, so a column added tomorrow is exported tomorrow. The gap is at
    the table level, not the column level, and this is what makes that distinction a result.
    """
    from eigentlich.services import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Record it?", choice="Yes") as decision:
        position = Position(
            member_id=member.id, role="income", capital_type="human", label="Employment",
            magnitude=92000.0, magnitude_unit="chf_per_year",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    export = export_member(session, VaultStore(tmp_path / "vault"), member_id=member.id)
    exported = export["positions"][0]
    for column in Position.__table__.columns:
        assert column.key in exported, f"export drops Position.{column.key}"


# ==================================================================== C-10 / R-213, which held


def test_revocation_is_immediate_across_a_second_session(engine, session, member):
    """C-10 / R-213 attacked with a stale reader, and it holds. Recorded because a negative is a result.

    The obvious way past "revocation is immediate" is a second Session holding the grant in its identity
    map: revoke in one, read in the other. `live_grants` re-queries and `is_live()` checks `revoked_at`
    before `expires_at`, so the second session refuses on its next read rather than on its next refresh.
    """
    from eigentlich.db import make_session_factory
    from eigentlich.services.curator import (
        AccessDenied, create_curator, curator_view_positions, grant_access, revoke_grant,
    )

    curator = create_curator(
        session, display_name="NB", email="nb@example.ch", password="ein langes passwort hier"
    )
    session.flush()
    grant = grant_access(session, member_id=member.id, curator_id=curator.id, scope=["positions"])
    session.commit()

    other = make_session_factory(engine)()
    try:
        curator_view_positions(other, member_id=member.id, curator_id=curator.id)

        revoke_grant(session, grant_id=grant.id, member_id=member.id)
        session.commit()

        with pytest.raises(AccessDenied):
            curator_view_positions(other, member_id=member.id, curator_id=curator.id)
    finally:
        other.close()


def test_an_expired_grant_is_refused_even_though_it_was_never_revoked(session, member):
    """The other half of R-210: a grant nobody withdrew, which simply ran out. Also holds.

    Worth asserting separately because `is_live()` short-circuits on `revoked_at` — a bug returning True
    for an unrevoked grant would be invisible to every revocation test in the suite.
    """
    from eigentlich.services.curator import AccessDenied, create_curator, grant_access, require_grant

    curator = create_curator(
        session, display_name="NB2", email="nb2@example.ch", password="ein langes passwort hier"
    )
    session.flush()
    grant_access(
        session, member_id=member.id, curator_id=curator.id, scope=["vault"],
        expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
    )
    session.commit()

    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    with pytest.raises(AccessDenied):
        require_grant(session, member_id=member.id, curator_id=curator.id, scope="vault", at=later)


# --------------------------------------------------------------------------------------------------
# The board that reports the gaps, and the tests that prove they are still gaps
# --------------------------------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason="C-09/raw-dbapi: the guard sits on SQLAlchemy's execution pipeline, so it sees the ORM, Core DML, the "
    "bulk helpers and raw text(). A DBAPI cursor taken from engine.raw_connection() does not pass through "
    "that pipeline at all, and neither does sqlite3 opened on the file. No trigger backstops it because "
    "C-09 requires a Decision in the SAME TRANSACTION and a SQLite trigger fires per statement, before "
    "the Decision exists.",
)
def test_a_raw_dbapi_cursor_cannot_create_a_position_without_a_decision(tmp_path):
    """C-09's stated limit, made executable so 'we know about that one' cannot drift into folklore."""
    from eigentlich.db import install_append_only_triggers
    from eigentlich.models import Base, Member

    database = tmp_path / "raw.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{database}")
    try:
        Base.metadata.create_all(engine)
        install_append_only_triggers(engine)

        with sqlalchemy.orm.Session(engine) as session:
            session.add(
                Member(id="m-raw", age_at_registration=40, display_name="X", locale="de-CH")
            )
            session.commit()

        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute(
                "INSERT INTO positions (id, member_id, role, capital_type, label, magnitude, "
                "magnitude_unit, data_class) VALUES ('p-raw', 'm-raw', 'growth', 'financial', "
                "'Bought outside the plan', 250000.0, 'chf_per_year', 2)"
            )
            raw.commit()
        finally:
            raw.close()

        with engine.connect() as connection:
            written = connection.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM positions WHERE id = 'p-raw'")
            ).scalar()
            decisions = connection.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM decisions")
            ).scalar()
    finally:
        engine.dispose()

    assert not (written == 1 and decisions == 0), (
        "a raw DBAPI cursor created a 250k position with no Decision behind it"
    )


@pytest.mark.xfail(
    strict=True,
    reason="curator/no-release-gate: nothing holds the claim that a curator read a report before a "
    "member saw it. C-01 was withdrawn on 20 September 2026 and the release gate proposed to replace it "
    "(C-12) was refused by the owner, so no report, finding or allocation carries a release record and "
    "no code path requires one. This is a stated position rather than an oversight - A160 has the ruling "
    "and states what it costs - and it is on the board because a reader asking what stops unreviewed "
    "output reaching a member is entitled to find the answer rather than an absence. The assertion below "
    "is what a release record would have to make true, written out so that the day one exists this mark "
    "goes red and somebody has to come and read A160.",
)
def test_a_report_carries_a_record_of_the_curator_who_released_it(session, member):
    """The gap `/api/health` confesses to under `curator/no-release-gate`, made executable.

    A Befund is computed for a member and is immediately readable. There is no field on it naming a
    curator, no timestamp of a release, and no state in which it is withheld — so this asks the payload
    for the three things C-12 would have required and finds none of them.

    **It asserts the absence of a feature, not a defect**, which is unusual and deliberate. The board
    lists this as a known gap; A65's rule is that every listed gap has something in this file that
    demonstrates it, so that the board cannot keep confessing to a problem nobody can reproduce. This is
    that demonstration.
    """
    from eigentlich.services.befund import render_befund

    report = render_befund(session, member_id=member.id)

    release = (
        report.get("release")
        or report.get("released_by")
        or report.get("release_record")
    )
    assert release, (
        "the Befund carries no release record: no curator id, no timestamp, and no assumption set it "
        "was released against. Nothing stands between this computation and the member."
    )


def _board_source() -> str:
    """`client/status.html`, read as text. The board is a rendered view, so this is its whole contract."""
    return (Path(__file__).resolve().parents[2] / "client" / "status.html").read_text(encoding="utf-8")


def _health_dict(name: str) -> dict:
    """One dict literal out of `api/main.py`'s health payload, by key, read from the source.

    From the source rather than by calling the route, because `health` is a FastAPI endpoint with an
    injected session and this is a question about what the file declares.
    """
    import ast as _ast

    import eigentlich.api.main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    for node in _ast.walk(_ast.parse(source)):
        if not isinstance(node, _ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, _ast.Constant) and key.value == name and isinstance(value, _ast.Dict):
                return {
                    k.value: v
                    for k, v in zip(value.keys, value.values)
                    if isinstance(k, _ast.Constant)
                }
    raise AssertionError(f"no {name!r} dict literal in api/main.py")


def test_the_board_keeps_no_second_copy_of_the_health_payload():
    """T3.3, the first direction: the status page may not restate what `/api/health` says.

    **The defect this prevents is the one that made the rewrite necessary.** `status.html` was a
    hand-written table, and by 20 September 2026 five of its rows were wrong: a foreign key listed as
    "next" that A98 had closed, a destination phrase said to be read by nothing that had served since
    A99, a wrong-law risk A103 and A106 had narrowed, and a whole column for C-01. Every one was a
    second copy that went stale while the thing it copied moved.

    The page may name a constraint in *prose* — it explains why C-01 and C-06 are absent, which a reader
    needs. It may not carry one in a table cell, because that is the copy.

    **Planted violation:** added a `<td>C-02</td>` row to the constraints table. Failed naming C-02.
    Removed.
    """
    import re

    source = _board_source()
    identifiers = set(_health_dict("constraints_enforced")) | set(_health_dict("known_gaps"))
    assert identifiers, "the health payload declares nothing; this test would pass vacuously"

    cells = re.findall(r"<td[^>]*>(.*?)</td>", source, re.DOTALL)
    offenders = [
        f"{identifier} appears in a table cell: {cell.strip()[:60]!r}"
        for cell in cells
        for identifier in identifiers
        if re.search(rf"\b{re.escape(identifier)}\b", cell)
    ]
    assert not offenders, (
        "client/status.html carries rows that duplicate /api/health: "
        + "; ".join(offenders)
        + ". The board is a rendered view: what it states about a constraint or a gap comes from the "
          "payload at load time, or it is a second copy waiting to go stale."
    )

    assert "fetch('/api/health')" in source, (
        "the board no longer reads /api/health. If it is meant to be static again that is a decision "
        "and belongs in the register - A171 is the entry that made it a view."
    )


def test_every_gap_the_board_will_render_carries_a_date_and_an_owner():
    """T3.3: "every open row carries a date and an owner".

    Enforced on the payload rather than on the markup, because the markup has no other source. An
    undated gap is one nobody can tell has been open for three weeks or three months; an unowned one is
    one nobody has agreed to answer.
    """
    import ast as _ast
    import datetime as _dt

    gaps = _health_dict("known_gaps")
    assert gaps, "no known gaps declared; if that is true, delete this test deliberately"

    for identifier, node in gaps.items():
        assert isinstance(node, _ast.Dict), (
            f"known_gaps[{identifier!r}] is a bare string. Every row carries since, owner and what "
            f"since A171."
        )
        row = {
            k.value: getattr(v, "value", None)
            for k, v in zip(node.keys, node.values)
            if isinstance(k, _ast.Constant)
        }
        missing = sorted({"since", "owner", "what"} - set(row))
        assert not missing, f"known_gaps[{identifier!r}] is missing {missing}"
        assert row["owner"], f"known_gaps[{identifier!r}] has an empty owner"
        # A real date, not a year and not a phrase. Parsed rather than matched, so 2026-02-31 fails.
        _dt.date.fromisoformat(row["since"])


def test_every_known_gap_on_the_health_board_still_has_a_failing_test_behind_it():
    """A65: `/api/health` is read as a statement of fact, so its `known_gaps` must not go stale.

    A gap listed there is a promise that something in this file still demonstrates it. The `xfail(strict)`
    marks already catch the forward direction — fix the hole and the suite fails until someone records it.
    This catches the other direction: a gap that is *listed* but has no test left behind it, which would
    let the board keep confessing to a problem nobody can reproduce.

    Matched on the constraint id rather than on wording, because the prose is meant to be edited.
    """
    import ast

    import eigentlich.api.main as main_module

    # Read the board out of the SOURCE rather than by calling the route: `health` is a FastAPI endpoint
    # with an injected session, and this test is about what the file declares, not about serving it.
    main_source = Path(main_module.__file__).read_text(encoding="utf-8")
    gaps: set[str] = set()
    for node in ast.walk(ast.parse(main_source)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "known_gaps"
                    and isinstance(value, ast.Dict)
                ):
                    gaps = {k.value for k in value.keys if isinstance(k, ast.Constant)}
    assert gaps, "the health board lists no known gaps; if that is true, delete this test deliberately"

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    reasons: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            name = ast.unparse(call.func if call else decorator)
            if not name.endswith("xfail"):
                continue
            strict = any(
                kw.arg == "strict" and getattr(kw.value, "value", False) is True
                for kw in (call.keywords if call else [])
            )
            if not strict:
                continue
            reasons.extend(
                ast.literal_eval(kw.value)
                for kw in (call.keywords if call else [])
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant)
            )

    unbacked = sorted(gap for gap in gaps if not any(gap in reason for reason in reasons))
    assert not unbacked, (
        f"these constraints are listed as known gaps on /api/health but no strict xfail in this file "
        f"demonstrates them any more: {unbacked}. Either the gap was closed and the board should say so, "
        f"or the test that proved it was deleted and the claim is now unverifiable."
    )


def test_a_member_cannot_publish_another_members_listing(api_session, tmp_path, monkeypatch, fast_kdf):
    """A79's stated open point, closed. Two members, one draft listing, a stranger with a valid token.

    Authentication was wired by REMOVING `member_id` from every route signature, which closes the read side
    outright: a caller cannot name someone else because there is nowhere to name them. These two routes
    address a listing by its own id, so the id in the path was never the caller's, and they were left
    merely authenticated — any member with a token could add a disclosure to, or publish, anyone's draft
    application.

    The refusal is 404, not 403: a member who does not own a listing has no business learning whether that
    id exists, on the same reasoning that makes a wrong address and a wrong password indistinguishable.

    Uses the suite's own session overrides rather than a hand-rolled engine. Overriding only
    `main.get_session` leaves every other router on its own dependency, which is how my first attempt at
    this test failed with a 401 that had nothing to do with the thing under test.
    """
    from conftest import session_overrides
    from fastapi.testclient import TestClient

    from eigentlich.api import main, remainder
    from eigentlich.services import VaultStore
    from eigentlich.services.auth import register_with_credentials
    from eigentlich.services.marketplace import apply_to_be_listed

    store = VaultStore(tmp_path / "vault")
    monkeypatch.setattr(main, "VAULT_STORE", store)

    owner, _ = register_with_credentials(
        api_session, age_at_registration=46, display_name="Owner", locale="de-CH",
        email="owner@x.local", password="ein ziemlich langes passwort",
    )
    register_with_credentials(
        api_session, age_at_registration=40, display_name="Stranger", locale="de-CH",
        email="stranger@x.local", password="ein anderes langes passwort",
    )
    listing_id = apply_to_be_listed(
        api_session, member_id=owner.id, display_name="Owner Praxis", title="Praxis",
        domain="health", qualification_pipeline="professional_registration",
        roles=["protection"], registration_refs=["GLN-7601000000001"],
    ).id
    api_session.commit()

    overrides = session_overrides(api_session)
    overrides[remainder.get_store] = lambda: store
    main.app.dependency_overrides.update(overrides)
    try:
        client = TestClient(main.app)
        signed_in = client.post(
            "/api/session",
            json={"email": "stranger@x.local", "password": "ein anderes langes passwort"},
        )
        assert signed_in.status_code == 201, signed_in.text
        headers = {"Authorization": f"Bearer {signed_in.json()['token']}"}

        disclosure = client.post(
            f"/api/marketplace/applications/{listing_id}/disclosures",
            headers=headers,
            json={
                "kind": "conflict_of_interest",
                "statement": "injected by a stranger",
                "declared_by": "Stranger",
            },
        )
        published = client.post(
            f"/api/marketplace/applications/{listing_id}/publish", headers=headers, json={}
        )
    finally:
        for key in overrides:
            main.app.dependency_overrides.pop(key, None)

    assert disclosure.status_code == 404, (
        f"a stranger added a disclosure to someone else's listing: {disclosure.status_code}"
    )
    assert published.status_code == 404, (
        f"a stranger published someone else's listing: {published.status_code}"
    )


def test_no_tracked_text_file_contains_a_control_byte():
    """A20's hazard, made mechanical after it landed three times in one day.

    `\b` written through a bash heredoc becomes a literal backspace byte, `0x08`. It has now done so:
    once in `boundary.py`, where it silently disabled two vocabulary filters and both of their tests
    passed by being unable to fail (A20); once in `log_filter.py`, where `\n` produced an unterminated
    string literal — which at least failed loudly; and once in **`DECISIONS.md`'s A78 entry**, which is the
    entry describing the hazard. That last one is the reason this test exists: the damage was invisible.
    Rendered, `` `<BS>beste<BS>` `` reads as almost the right thing, and nobody reading the paragraph would
    catch it. It was found by an agent scanning bytes.

    Tab, newline and carriage return are the only control characters a text file has any business holding.

    **Scope, stated because the name overstates it.** `git ls-files` runs from `Prototype/`, so
    this scans the ~190 tracked text files **this build authors** and not the parent estate. That is the
    right boundary and not an oversight: the estate carries vendored minified libraries — `plotly.min.js`
    holds an `0x1b` at byte 3 022 246 — and a guard that fired on third-party bundles would be turned off
    within a week, which is the fate of every filter that cries wolf. What this cannot catch is a control
    byte written into the estate, and §9 puts the estate out of scope for this build anyway.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent.parent
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listing.returncode != 0:  # pragma: no cover - git absent or not a work tree
        pytest.skip("git is not available here, so the tracked-file list cannot be read")

    names = [name for name in listing.stdout.decode("utf-8", "replace").split("\0") if name]
    checked = 0
    offenders: list[str] = []
    for name in names:
        if not name.endswith((".py", ".md", ".json", ".js", ".css", ".html", ".ini", ".cfg", ".txt")):
            continue
        path = root / name
        if not path.is_file():
            continue
        raw = path.read_bytes()
        checked += 1
        for index, byte in enumerate(raw):
            if byte < 9 or byte in (11, 12) or 14 <= byte <= 31:
                context = raw[max(0, index - 40) : index + 20].decode("utf-8", "replace")
                offenders.append(f"{name}: byte 0x{byte:02x} at {index} — ...{context}...")
                break

    assert checked > 100, f"only {checked} files were scanned; the filter or the listing is wrong"
    assert not offenders, "control bytes in tracked text files:\n  " + "\n  ".join(offenders)
@pytest.mark.xfail(
    strict=True,
    reason="S-08/relevance: the residual member-facing risk after C-11 closed the truth half. A sentence "
    "copied verbatim out of the corpus, carrying a correct citation, can answer an ADJACENT question "
    "rather than the one that was asked. C-11 checks attribution, not aboutness, and nothing else in the "
    "build checks either since C-01 was withdrawn (A164). It is on the board as a known gap because it "
    "is visible to the member - the citation names the source of the quote, so a reader who follows it "
    "sees what the sentence is actually about - and closing it needs a relevance judgement nobody has "
    "specified. This mark is what keeps the board honest: close the gap and the suite goes red.",
)
def test_a_correctly_quoted_sentence_that_answers_a_different_question_is_refused():
    """The gap `/api/health` confesses to under `S-08/relevance`, made executable.

    The member asks about contribution gaps. The corpus answers, verbatim and correctly cited, about the
    reference age. Both sentences are true, both are genuinely in the corpus, and the quotation check
    passes because every word is attributable. Nothing looks at whether it is an answer.
    """
    from eigentlich.services.know import unquoted_sentences

    class _Passage:
        def __init__(self, text: str) -> None:
            self.text = text

    asked_about = "Wie schliesse ich eine Beitragslücke bei der AHV?"
    passages = [
        _Passage("Das Referenzalter für die AHV liegt bei 65 Jahren."),
    ]
    answered_with = "„Das Referenzalter für die AHV liegt bei 65 Jahren.“ [1]"

    # C-11 is satisfied: the sentence is attributable, word for word.
    assert unquoted_sentences(answered_with, passages) == []

    # And this is the property the build does NOT have.
    assert _answers_the_question(answered_with, asked_about), (
        "a true, correctly cited sentence about the reference age was returned to a member who asked "
        "how to close a contribution gap, and nothing refused it"
    )


def _answers_the_question(answer: str, question: str) -> bool:
    """The relevance judgement this build has never specified. Always False, deliberately.

    Written as a named function rather than a bare `False` so the xfail above reads as a claim about a
    missing capability instead of as a test that was rigged to fail. If somebody ever builds relevance
    checking, this is the seam it lands on and the xfail above is what tells them the gap has closed.
    """
    return False


def test_a_false_statement_of_law_cannot_be_emitted_because_it_is_in_no_passage():
    """A103's risk, re-expressed against C-11 now that C-01 is gone (A164, A166).

    **The observed failure:** asked whether an AHV pension may be *deferred*, the model answered about
    the *reduction* applied to drawing one *early* — the opposite operation — and presented the 20-80 %
    Teilbezug band as a range of reductions. Every figure in it is genuinely in the corpus. Every
    citation is correct. It reproduced in 3 of 3 runs against apertus:8b, and no run stated the correct
    fact.

    **The citation is what makes it dangerous.** A member who reads an opinion knows they are being
    given one; a member who reads a cited paragraph about their own pension has every reason to believe
    it.

    **This was an xfail asserting C-01 caught it, and that was always the wrong guard.** C-01 asked
    whether an answer ADVISES, not whether it is TRUE, and it passed this sentence correctly — which is
    why the mark was strict, and why A103 called this the build's largest member-facing risk. C-01 has
    been withdrawn, so the xfail cannot survive in that form; the question it stood in for is the one
    A164 promotes to **C-11**: no member-facing sentence asserts a fact it cannot attribute to a
    retrieved passage.

    So the property is now asserted where it actually holds. The sentence below is in no passage,
    `unquoted_sentences` refuses anything a member could read that is not a quotation, and the answer
    path therefore cannot emit it. That is a property of the construction rather than of a pattern list,
    which is exactly why the extractive rule survived the cull and C-01 did not.
    """
    from eigentlich.services.know import unquoted_sentences

    false_but_grounded = (
        "Die Kürzung des Rentenbetrags erfolgt um einen versicherungstechnischen Prozentsatz und "
        "muss zwischen 20 % und 80 % der zustehenden Altersrente liegen."
    )

    class _Passage:
        def __init__(self, text: str) -> None:
            self.text = text

    # The corpus genuinely carries the figures and the vocabulary. It does not carry this claim.
    passages = [
        _Passage(
            "Ein Teilbezug der Altersrente ist zwischen 20 % und 80 % der zustehenden Altersrente "
            "möglich."
        ),
        _Passage("Wer die Rente aufschiebt, erhält einen Zuschlag auf den Rentenbetrag."),
    ]

    assert unquoted_sentences(false_but_grounded, passages), (
        "C-11: a false statement of Swiss pension law, assembled out of figures that ARE in the corpus, "
        "was treated as attributable to it. This is the sentence A103 recorded reaching a member in 3 of "
        "3 runs, and the extractive rule is the only thing left standing between it and them."
    )
