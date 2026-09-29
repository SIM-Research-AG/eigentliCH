"""The registry lives in the database: tables ``country`` and ``series``."""

from __future__ import annotations

import json

import psycopg
import pytest

from datafeed.contracts import Country
from datafeed.etl.bootstrap import FROZEN_RAW, read_frozen
from datafeed.etl.seed import load_seed
from datafeed.service import InvalidRequest

from .conftest import RAW_ID


def test_the_seed_fills_the_registry(service):
    assert len(service.countries()) == 16 and len(service.series_specs()) == 46
    ch = next(c for c in service.countries() if c.code == "CH")
    assert (ch.name, ch.iso3, ch.matlab) == ("Switzerland", "CHE", "CH")
    cpi = next(s for s in service.series_specs() if s.series_id == "inflation.cpi_yoy")
    assert (cpi.matlab_sheet, cpi.matlab_column, cpi.zero_is_a_value) == ("Inflation", 1, True)


def test_seeding_again_adds_nothing(service):
    assert service.seed_registry(*load_seed()) == (0, [])


def test_the_database_wins_over_the_seed(service):
    with service.store.session() as conn:
        conn.execute("UPDATE country SET name = 'Swiss Confederation' WHERE code = 'CH'")
    added, differ = service.seed_registry(*load_seed())
    assert added == 0 and any("country CH" in d for d in differ)
    assert next(c for c in service.countries() if c.code == "CH").name == "Swiss Confederation"
    with service.store.session() as conn:
        conn.execute("UPDATE country SET name = 'Switzerland' WHERE code = 'CH'")


def test_a_new_registry_row_is_accepted_for_ingest(service):
    service.seed_registry([Country(code="NO", name="Norway", iso3="NOR")], [])
    assert "NO" in {c.code for c in service.countries()}


def test_an_unregistered_country_cannot_be_ingested(service):
    raw = read_frozen(FROZEN_RAW)
    first = raw.series[0]
    foreign = first.model_copy(update={"definition": first.definition.model_copy(update={"country": "ZZ"})})
    with pytest.raises(InvalidRequest, match="unregistered"):
        service.ingest(raw.model_copy(update={"snapshot_id": "x-test", "series": (foreign,)}))


def test_import_counts_are_in_the_database(service):
    frozen = json.loads((FROZEN_RAW / "zero_rule.json").read_text(encoding="utf-8"))["conversions"]
    stored = {f"{c.country}/{c.series_id}": c for c in service.conversions(RAW_ID)}
    assert set(stored) == set(frozen) and len(stored) == 16 * 44
    for key, counts in frozen.items():
        assert stored[key].leading_zero == counts["leading_zero"]
        assert stored[key].placeholder == counts.get("placeholder", 0)
    assert sum(c.placeholder for c in stored.values()) == sum(c.get("placeholder", 0) for c in frozen.values())


def test_import_counts_are_append_only(service):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with service.store.session() as conn:
            conn.execute("UPDATE series_conversion SET nan = 0")


def test_the_registry_endpoints(client):
    countries = client.get("/countries").json()
    assert {c["code"] for c in countries} >= {"US", "CH", "EU"}
    series = client.get("/registry/series").json()
    assert len(series) == 46 and all("matlab_sheet" in s for s in series)
    conv = client.get(f"/snapshots/{RAW_ID}/conversions").json()
    assert len(conv) == 16 * 44
    assert client.get("/snapshots/nope/conversions").status_code == 404


def test_every_series_says_what_it_measures(service):
    """A series cannot enter the registry without a plain-language description: the SQL
    Metadata catalogue reads it, and a bare id tells a reader nothing."""
    thin = [s.series_id for s in service.series_specs() if len(s.description.split()) < 5]
    assert not thin, f"describe these in seed/registry.yaml: {thin}"
