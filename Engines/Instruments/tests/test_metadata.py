"""The metadata export must describe everything the store holds, and describe it truly.

A data dictionary is worth exactly as much as its worst row. These tests guard the two
ways it goes wrong: a table that exists in SQL but is missing from the catalogue, and a
catalogue row whose metadata disagrees with the column it claims to describe.
"""

from __future__ import annotations

import pytest

from store import db
from store.etl import notion_metadata as meta


@pytest.fixture()
def seeded(store):
    """A throwaway store with two series in its feed.

    The series tests are worthless against an empty schema -- they pass by having nothing
    to check. Two rows, deliberately unlike each other, give them something to fail on.
    """
    now = db.utc_now()
    rows = [
        ("eq.test.m", "Test equity", "return_simple", "USD", "decimal", "M", "WLD",
         "return", "internet:yahoo", "proxy", True, "2001-01", "2026-08", 308),
        ("long.test", "Test macro", "index_level", "none", "units", "A", "US",
         "macro", "nas:house-research", "authoritative", False, "1870", "2020", 151),
    ]
    with db.datafeed_session() as conn:
        for r in rows:
            conn.execute(
                db.upsert(
                    "series_definition",
                    ("series_id", "name", "unit", "currency", "magnitude", "period",
                     "country", "category", "origin_kind", "quality_grade", "is_stitched",
                     "first_period", "last_period", "observation_count", "source",
                     "created_at", "updated_at"),
                    ("series_id",),
                ),
                (*r, "test fixture", now, now),
            )
    return store


def test_every_table_has_a_purpose(store):
    """A table added to the schema without a curated purpose fails here.

    Otherwise it reaches Notion as a row with an empty description, which reads as
    'this exists and nobody knows why'.
    """
    records = meta.export()
    missing = meta.undescribed(records)
    assert not missing, (
        f"no purpose recorded in TABLE_PURPOSE for {missing}. Add one line per table; "
        f"the catalogue is the only place a reader learns what the table is for."
    )


def test_export_covers_every_table_in_both_schemas(store):
    """The catalogue must not quietly omit a table."""
    records = meta.export()
    catalogued = {r.name.split(".", 1)[1] for r in records if r.object_type == "table"}

    with db.session() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
            ([conn.config.schema, conn.config.datafeed_schema],),
        ).fetchall()
    actual = {r["table_name"] for r in rows}

    assert actual - catalogued == set(), f"tables absent from the catalogue: {actual - catalogued}"


def test_series_rows_carry_the_metadata_that_makes_numbers_safe(seeded):
    """Unit, currency, magnitude, frequency and country are never blank on a series.

    These five are what make two numbers safe to put in the same expression. A blank one
    is not a cosmetic gap; it is an invitation to add a percentage to a decimal.
    """
    records = meta.export()
    series = [r for r in records if r.object_type == "series"]
    assert len(series) == 2, "the fixture's series did not reach the export"

    for r in series:
        for field in ("unit", "currency", "magnitude", "frequency", "country"):
            assert getattr(r, field), f"{r.name} has no {field}"


def test_series_rows_match_the_registry(seeded):
    """The export reads the registry rather than restating it.

    If these ever disagree the catalogue has grown its own copy of the truth, which is
    the failure mode this module exists to avoid.
    """
    records = {r.name: r for r in meta.export() if r.object_type == "series"}
    with db.session() as conn:
        feed = conn.config.datafeed_schema
        rows = conn.execute(
            f"SELECT series_id, unit, currency, period, observation_count "
            f"FROM {feed}.series_definition"
        ).fetchall()

    assert rows, "nothing to compare against"
    for row in rows:
        record = records[row["series_id"]]
        assert record.unit == row["unit"]
        assert record.currency == row["currency"]
        assert record.frequency == row["period"]
        assert record.observations == row["observation_count"]


def test_the_catalogue_is_one_way(store):
    """Nothing in the engine reads the Notion catalogue.

    The export is a publication, not a dependency. A module that imported it would make
    a hand-editable page part of the calculation path.
    """
    import pathlib

    root = pathlib.Path(meta.__file__).resolve().parent.parent.parent
    offenders = []
    for path in list((root / "engines").rglob("*.py")) + list((root / "api").rglob("*.py")):
        if "notion" in path.read_text(encoding="utf-8").lower():
            offenders.append(str(path.relative_to(root)))
    assert not offenders, (
        f"{offenders} reference Notion. The catalogue is published from SQL, never read "
        f"back into a calculation."
    )

def test_every_public_symbol_is_described():
    """A ticker cannot enter the feed without someone saying what it is.

    The feed once described fifty-one series as "Adjusted close, month on month", which
    states how the number was computed and nothing about what was measured. This is a
    pure-code check, so it fails the moment a symbol is added to the proxy map or a stitch
    chain without a matching entry, rather than after the next fetch.
    """
    from feeds.proxy_map import PROXIES
    from feeds.security_meta import missing
    from store.etl.datafeed import chain_symbols

    wanted = set(chain_symbols()) | {p.symbol for p in PROXIES.values()
                                     if p.usable and p.symbol}
    absent = missing(wanted)
    assert not absent, (
        f"no entry in feeds/security_meta.py for {absent}. Add the name and what the "
        f"exposure actually is; a catalogue row nobody can identify is not documentation."
    )


def test_described_symbols_carry_real_prose():
    """The description has to say something, not restate the ticker."""
    from feeds.security_meta import SECURITIES

    for symbol, security in SECURITIES.items():
        assert security.name and security.name != symbol, f"{symbol} has no name"
        assert len(security.description) > 30, f"{symbol}: description too thin"
        assert security.country, f"{symbol} has no country"


def test_hand_written_series_descriptions_say_what_is_measured():
    """The long record and the chains carry prose a reader can use.

    "Oil price; the other half." survived for months because nothing checked it. A
    description has to name the quantity, and for the long record the country and span,
    so a reader can tell a rate from a level without opening the workbook.
    """
    from store.etl.datafeed import CHAINS, LONG_META

    for key, m in LONG_META.items():
        assert len(m.description.split()) >= 12, f"long.{key}: description too thin"
        assert "US" in m.description, f"long.{key}: does not say which economy"
        assert any(y in m.description for y in ("1870", "1871", "1890", "1910")), (
            f"long.{key}: does not say which years it covers")
    for chain in CHAINS:
        assert len(chain.description.split()) >= 8, f"{chain.series_id}: too thin"
        assert chain.description.startswith("Monthly total return"), (
            f"{chain.series_id}: does not say what the number is")


def test_a_chain_description_names_every_segment_and_its_span():
    """Before the anchor starts, a stitched series is a different instrument.

    `eq.world.m` is SPY, US large cap only, before 2008. A description that stopped at
    "developed-market equity" would be true of the last twelve years and false of the
    fifteen before them.
    """
    from store.etl.datafeed import CHAINS, chain_description

    chain = next(c for c in CHAINS if c.series_id == "eq.world.m")
    segments = [("yahoo.URTH", "2012-02", "2026-08", False),
                ("yahoo.ACWI", "2008-04", "2012-01", False),
                ("yahoo.SPY", "1993-02", "2008-03", True)]
    text = chain_description(chain, segments)
    for sid, first, last, _ in segments:
        symbol = sid.split(".", 1)[1]
        assert f"{symbol} (" in text and f"{first} to {last}" in text, symbol
    assert "US large-cap equity" in text
    assert "Smoothing was applied at the joint to SPY" in text

    alone = chain_description(chain, segments[:1])
    assert "No earlier segment was joined" in alone


def test_a_macro_series_says_where_its_economies_disagree():
    """Sixteen economies under one series id are not one definition.

    `consumer.wage_growth` holds seven different wage concepts. Summarising it as "wage
    growth" would invite exactly the comparison it cannot support.
    """
    row = {"period": "monthly", "unit": "ratio", "indices_json": '["consumption_power"]',
           "matlab_sheet": "Consumer", "matlab_column": 5}
    defs = [
        {"country": "US", "pull_code": "WGTROVER Index", "currency": "USD",
         "magnitude": 0.01, "description": "Wage growth"},
        {"country": "CH", "pull_code": "ENWGCHS Index", "currency": "CHF",
         "magnitude": 1.0, "description": "Wages nominal (GDP)"},
        {"country": "VN", "pull_code": "USD BGN Curncy", "currency": "USD",
         "magnitude": 1.0, "description": "Wage growth (placeholder ticker: no data)"},
    ]
    text = meta._describe_basic(row, defs)
    assert '"Wage growth" (US)' in text and '"Wages nominal (GDP)" (CH)' in text
    assert "No data for VN" in text
    assert "scale factor" in text
    assert "Currency differs" not in text, "a ratio has no currency to differ in"
    assert "consumption_power" in text

    same = meta._describe_basic(row, defs[:1])
    assert same.startswith("Wage growth (monthly), Bloomberg, for 1 economy.")
