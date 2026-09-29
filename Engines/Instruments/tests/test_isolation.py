"""The shared feed must survive the test suite.

This file exists because it did not. ``drop_schema`` dropped the engine schema *and* the
feed schema, while the fixture gave a throwaway name only to the engine one -- so every
test teardown deleted the real ``datafeed`` schema: 117 series, 26,341 observations, the
twelve stitched chains and the snapshot that pins them. The suite reported 206 passed
while doing it, because nothing asserted on what teardown touched.

The lesson is narrow and worth keeping: **a cleanup routine that reaches beyond the thing
it was handed is a destructive bug that only shows up when you are not looking.** These
tests watch the teardown rather than the feature.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from store import db
from store.config import load
from tests.conftest import temp_schema


def _exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname = %s", (name,)
    ).fetchone()
    return row is not None


def test_drop_schema_leaves_the_feed_alone():
    """The default drop must not touch the feed schema, whatever it is pointed at."""
    engine = f"t_{uuid.uuid4().hex[:12]}"
    feed = f"{engine}_feed"
    config = replace(db.get_config(), schema=engine, datafeed_schema=feed)

    db.use_config(config)
    try:
        db.initialise()
        with db.session(config) as conn:
            assert _exists(conn, engine)
            assert _exists(conn, feed)

        db.drop_schema(config)              # the default: engine only

        with db.session(config) as conn:
            assert not _exists(conn, engine), "the engine schema should be gone"
            assert _exists(conn, feed), (
                "drop_schema removed the feed schema. That default deleted the real "
                "datafeed once already."
            )
    finally:
        db.drop_schema(config, include_datafeed=True)
        db.use_config(load())


def test_fixture_never_points_at_the_production_feed():
    """The throwaway schema must be throwaway on *both* axes."""
    production = load()
    with temp_schema() as config:
        assert config.schema != production.schema
        assert config.datafeed_schema != production.datafeed_schema, (
            "the fixture left datafeed_schema pointing at production; a test would then "
            "read -- and on teardown delete -- the real feed"
        )
        assert config.schema.startswith("t_")
        assert config.datafeed_schema.startswith("t_")


def test_the_production_feed_survives_a_fixture_cycle():
    """End to end: run the fixture, then confirm the real feed schema is still there.

    The check that would have caught the original bug on the first run.
    """
    production = load()
    with db.session(production) as conn:
        before = _exists(conn, production.datafeed_schema)
    if not before:
        pytest.skip(f"no {production.datafeed_schema} schema on this server to protect")

    with temp_schema():
        pass

    with db.session(production) as conn:
        assert _exists(conn, production.datafeed_schema), (
            f"the {production.datafeed_schema} schema was destroyed by a fixture cycle"
        )
