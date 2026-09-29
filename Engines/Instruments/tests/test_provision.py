"""The database layout, and the boundary it is supposed to enforce.

The argument for one database with a schema per engine is that the boundary comes from
grants rather than from geography. That argument is only worth anything if the grants are
real, so these tests do not inspect the configuration: they open connections as the actual
roles and try to do the forbidden thing.

A convention that nobody tests is a convention that decays. The schema this engine deleted
by accident was protected by one.
"""

from __future__ import annotations

import psycopg
import pytest

from store import provision
from store.config import load


def _connect(user: str, dbname: str, password: str = provision.DEV_PASSWORD):
    config = load()
    return psycopg.connect(
        config.conninfo(dbname=dbname).replace(f"user={config.user}", f"user={user}")
        + f" password={password}",
        connect_timeout=5,
    )


@pytest.fixture(scope="module")
def layout():
    """The live layout, or a skip if the shared database has not been provisioned."""
    rows = provision.describe(provision.admin(load()))
    if not rows:
        pytest.skip(f"{provision.DATABASE} has not been provisioned")
    return {r["schema"]: r for r in rows}


def test_each_schema_is_owned_by_its_engine(layout):
    """A schema owned by the superuser is a schema with no boundary at all."""
    for engine in provision.ROSTER:
        if not engine.built or engine.name not in provision.OWNED_HERE:
            continue
        for schema in engine.schemas:
            assert schema in layout, f"{schema} missing from {provision.DATABASE}"
            assert layout[schema]["owner"] == engine.name, (
                f"{schema} is owned by {layout[schema]['owner']}, not {engine.name}. "
                f"The grants below mean nothing if the superuser still owns the schema."
            )


def test_nothing_may_be_created_in_public(layout):
    """`public` is where two projects collide. It is closed."""
    with _connect("fmre", provision.DATABASE) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE public.should_not_exist (x int)")


def test_an_engine_role_cannot_read_another_project(layout):
    """The boundary, tried rather than described.

    `fmre` has no grant in `simtech_macro`. It must not be able to read it, and the
    failure must come from the server.
    """
    try:
        conn = _connect("fmre", "simtech_macro")
    except psycopg.OperationalError:
        return  # refused at connect, which is a stronger answer still
    with conn:
        with pytest.raises(psycopg.Error):
            conn.execute("SELECT count(*) FROM datafeed.series").fetchone()


def test_the_catalogue_role_can_read_everything_and_write_nothing(layout):
    """The one account that crosses engines must not be able to change anything.

    It exists because the catalogue has to see the whole server, which is exactly what an
    engine role must not do. That privilege is only safe while it is read-only.
    """
    for dbname in provision.CATALOGUED:
        try:
            conn = _connect(provision.CATALOGUE_ROLE, dbname)
        except psycopg.OperationalError:
            pytest.skip(f"cannot reach {dbname} as {provision.CATALOGUE_ROLE}")
        with conn:
            schemas = conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' "
                "AND nspname NOT IN ('information_schema', 'public')"
            ).fetchall()
            assert schemas, f"{dbname}: the catalogue can see no schemas"

            target = schemas[0][0]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"CREATE TABLE {target}.should_not_exist (x int)")


def test_the_feed_schema_name_belongs_to_engine_one(layout):
    """This engine's private copy must not be called `datafeed`.

    Two schemas answering to that name, with different definitions, is the specific
    failure the consolidation was for. If someone renames this back, the catalogue starts
    describing two different things under one name again.
    """
    config = load()
    assert config.datafeed_schema != "datafeed", (
        "the Fund Map feed copy is called `datafeed`, which is Engine 01's name. "
        "It is an interim private copy and must say so."
    )
    assert config.datafeed_schema.startswith(config.schema), (
        f"{config.datafeed_schema} does not name its owner; call it "
        f"{config.schema}_feed so the catalogue shows who it belongs to."
    )


def test_every_object_is_owned_by_its_engine(layout):
    """Not just tables: functions and types too.

    The first version of the ownership sweep read `pg_class` and stopped there, so the
    engines' `refuse_change()` trigger functions stayed owned by the superuser. Each
    engine re-runs its schema on start, so `CREATE OR REPLACE FUNCTION` then failed with
    "must be owner of function" -- on a real start, never in the suites, because their
    fixtures build throwaway schemas the role owns outright.

    A partial ownership sweep is the same shape of bug as a partial drop: correct for the
    objects it thought of, silent about the rest.
    """
    stray = provision.unowned(provision.admin(load()))
    assert not stray, (
        f"objects not owned by their engine role: {stray}. Run "
        f"`python -m store.provision` and then adopt() on the affected schema."
    )
