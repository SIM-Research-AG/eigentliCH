"""The store: precision, isolation, upsert semantics and configuration.

The engine's claim is that it reproduces a published reference to 5e-16. A store that
rounds is not a storage detail, it is a change to the published figures -- so the
precision test comes first, and it is the reason every floating-point column is
``DOUBLE PRECISION`` rather than ``REAL``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from store import db
from store.config import ConfigError, DatabaseConfig, load, redacted_url
from tests.conftest import needs_feed, needs_sources

#: A value with a full 17 significant digits, taken from the published Equity profile.
#: Stored as PostgreSQL ``REAL`` it comes back wrong in the ninth decimal.
EXACTING_VALUE = -0.18721989171442346

ENVIRONMENT_COLUMNS = ("year", "cycle", "phase", "inflation")


class TestUpsert:
    def test_it_updates_every_non_key_column_by_default(self):
        assert db.upsert("t", ("a", "b", "c"), ("a",)) == (
            "INSERT INTO t (a, b, c) VALUES (%s, %s, %s) "
            "ON CONFLICT (a) DO UPDATE SET b = excluded.b, c = excluded.c"
        )

    def test_an_empty_update_list_means_do_nothing(self):
        assert db.upsert("t", ("a", "b"), ("a",), update=()).endswith(
            "ON CONFLICT (a) DO NOTHING"
        )

    def test_composite_keys_are_supported(self):
        assert "ON CONFLICT (a, b) DO UPDATE SET c = excluded.c" in db.upsert(
            "t", ("a", "b", "c"), ("a", "b")
        )

    def test_the_placeholder_count_matches_the_column_count(self):
        """The arity bug that shipped once: a literal in VALUES and a column in the list."""
        for n in range(1, 16):
            columns = tuple(f"c{i}" for i in range(n))
            assert db.upsert("t", columns, (columns[0],)).count("%s") == n


class TestConfig:
    def test_a_password_is_never_in_the_printable_url(self):
        config = DatabaseConfig(user="u", password="hunter2", host="h", dbname="d", schema="s")
        printed = redacted_url(config)
        assert "hunter2" not in printed
        assert "***" in printed

    def test_describe_never_leaks_the_password(self):
        described = json.dumps(DatabaseConfig(user="u", password="hunter2").describe())
        assert "hunter2" not in described
        assert "password_set" in described

    @pytest.mark.parametrize("bad", [
        "has space", "has-dash", "1leading", "", "drop;table", 'quo"te', "a" * 64,
    ])
    def test_a_dangerous_schema_name_is_refused(self, bad):
        """``CREATE SCHEMA`` and ``SET search_path`` cannot bind a parameter, so these two
        names are the only configuration that reaches SQL as text. They are validated
        where they are read, not trusted where they are used."""
        with pytest.raises(ConfigError):
            load({"schema": bad})

    def test_a_url_supplies_every_field_at_once(self):
        config = load({})
        assert config.host and config.dbname and config.schema

    def test_the_environment_beats_the_file(self, monkeypatch):
        monkeypatch.setenv("INSTRUMENTS_DB_SCHEMA", "from_env")
        assert load().schema == "from_env"
        assert any("env:" in s for s in load().sources)


class TestPrecision:
    def test_a_full_precision_value_round_trips(self, store):
        """The reason every float column is DOUBLE PRECISION.

        PostgreSQL's REAL is four bytes and would return this about 1.7e-9 out -- seven
        orders of magnitude worse than the agreement this engine claims with the published
        reference, and nothing about the result would look wrong.
        """
        with db.session() as conn:
            conn.execute(
                db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",)),
                (1900, EXACTING_VALUE, 0, 0.0),
            )
        with db.session() as conn:
            got = conn.execute(
                "SELECT cycle FROM market_environment WHERE year = %s", (1900,)
            ).fetchone()["cycle"]
        assert got == EXACTING_VALUE, f"lost {abs(got - EXACTING_VALUE):.3e}"

    def test_no_column_anywhere_is_single_precision(self, store):
        with db.session() as conn:
            offenders = conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND data_type = 'real'", (store.schema,)
            ).fetchall()
        assert not offenders, f"single-precision columns: {offenders}"


class TestIsolation:
    def test_every_table_lands_in_the_engine_schema(self, store):
        """The server is shared. Nothing of ours may appear in `public`."""
        with db.session() as conn:
            here = conn.execute(
                "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = %s",
                (store.schema,),
            ).fetchone()["n"]
        # 15 until 29.09.2026; +2 for the inflation pass-through (FMRE-35).
        assert here == 17, f"expected 17 tables in {store.schema}, found {here}"

    def test_the_search_path_is_pinned_to_the_engine_schema(self, store):
        with db.session() as conn:
            path = conn.execute("SHOW search_path").fetchone()["search_path"]
        assert store.schema in path

    def test_a_bare_table_name_resolves_inside_the_schema(self, store):
        """Where does an unqualified table name actually land?

        Two wrong ways to ask. ``pg_tables`` lists every schema, so it happily finds the
        real ``instruments.calibration`` and says nothing about resolution. And
        ``to_regclass(...)::text`` *omits* the schema exactly when the name resolved
        through the search path, so it answers a bare ``calibration`` either way. The
        namespace of the resolved oid is the question actually being asked.
        """
        with db.session() as conn:
            resolved = conn.execute(
                "SELECT n.nspname AS schema FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.oid = to_regclass('calibration')"
            ).fetchone()["schema"]
        assert resolved == store.schema


class TestSemantics:
    def test_the_upsert_updates_rather_than_duplicating(self, store):
        statement = db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",))
        with db.session() as conn:
            conn.execute(statement, (1900, 1.0, 0, 0.0))
            conn.execute(statement, (1900, 2.0, 4, 0.1))
        with db.session() as conn:
            rows = conn.execute("SELECT * FROM market_environment").fetchall()
        assert len(rows) == 1
        assert rows[0]["cycle"] == 2.0 and rows[0]["phase"] == 4

    def test_do_nothing_leaves_the_existing_row_alone(self, store):
        insert = db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",))
        ignore = db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",), update=())
        with db.session() as conn:
            conn.execute(insert, (1900, 1.0, 0, 0.0))
            conn.execute(ignore, (1900, 9.9, 4, 0.5))
        with db.session() as conn:
            assert conn.execute("SELECT cycle FROM market_environment").fetchone()["cycle"] == 1.0

    def test_rows_are_addressable_by_column_name(self, store):
        with db.session() as conn:
            row = conn.execute("SELECT 1 AS one, 'x' AS letter").fetchone()
        assert row["one"] == 1 and row["letter"] == "x"

    def test_a_failed_transaction_rolls_back(self, store):
        with pytest.raises(Exception):
            with db.session() as conn:
                conn.execute(
                    db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",)),
                    (1900, 1.0, 0, 0.0),
                )
                conn.execute("SELECT * FROM a_table_that_does_not_exist")
        with db.session() as conn:
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM market_environment"
            ).fetchone()["n"] == 0

    def test_a_foreign_key_is_enforced(self, store):
        """long_series references source_file; an orphan row must be refused."""
        with pytest.raises(Exception):
            with db.session() as conn:
                conn.execute(
                    db.upsert("long_series", ("series_key", "year", "value", "source_file"),
                              ("series_key", "year")),
                    ("ghost", 1900, 1.0, "a-file-that-was-never-registered.xlsx"),
                )

    def test_executemany_accepts_an_empty_batch(self, store):
        with db.session() as conn:
            assert conn.executemany(
                db.upsert("market_environment", ENVIRONMENT_COLUMNS, ("year",)), []
            ) is None


@needs_sources
@needs_feed
class TestBootstrappedStore:
    def test_the_published_reference_survives_the_round_trip(self, module_store):
        """The 5e-16 claim, re-checked after a real round trip through the server."""
        from store.etl import bootstrap

        bootstrap.main([])
        published = json.loads(
            (Path(__file__).parent / "fixtures" / "steiner_2021_reference.json")
            .read_text(encoding="utf-8")
        )["profiles"]

        with db.session() as conn:
            stored = {
                r["block_key"]: db.loads(r["profile_json"])
                for r in conn.execute("SELECT block_key, profile_json FROM calibration_block")
            }
        worst = 0.0
        for key, expected in published.items():
            for state, (got, want) in enumerate(zip(stored[key], expected), start=1):
                worst = max(worst, abs(got - want))
                assert abs(got - want) < 1e-12, f"{key} state {state}: {got!r} vs {want!r}"
        assert worst < 1e-12

    def test_re_running_the_bootstrap_changes_nothing(self, module_store):
        """Determinism is the regulatory spine: a figure that cannot be reproduced cannot
        be defended, and reproducing it has to survive a second run against the same store."""
        from store.etl import bootstrap

        bootstrap.main([])
        with db.session() as conn:
            first = conn.execute("SELECT calibration_id FROM calibration").fetchall()
            blocks = {
                r["block_key"]: r["profile_json"]
                for r in conn.execute("SELECT block_key, profile_json FROM calibration_block")
            }
        bootstrap.main([])
        with db.session() as conn:
            second = conn.execute("SELECT calibration_id FROM calibration").fetchall()
            again = {
                r["block_key"]: r["profile_json"]
                for r in conn.execute("SELECT block_key, profile_json FROM calibration_block")
            }
        assert [r["calibration_id"] for r in first] == [r["calibration_id"] for r in second]
        assert len(second) == 1, "a second run created a second calibration"
        assert blocks == again
