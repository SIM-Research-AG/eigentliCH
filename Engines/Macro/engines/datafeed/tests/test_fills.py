"""The public-source fills on the real data: the frozen raw snapshot and the frozen public
responses. These assert the outcome candidate by candidate, so a change to the rules, the
tolerances or the responses shows up as a named failure rather than a shifted number."""

from __future__ import annotations

import json

import pytest

from datafeed.calibration import DEFAULT
from datafeed.etl import public
from datafeed.etl.bootstrap import FROZEN_PUBLIC, FROZEN_RAW, read_frozen
from datafeed.settings import load

ACCEPTED = {
    ("BD", "production.gdp_nominal"): tuple(range(2006, 2016)),
    ("BD", "consumer.household_consumption"): tuple(range(2006, 2026)),
    ("VN", "consumer.household_consumption"): tuple(range(2006, 2026)),
    ("BR", "consumer.labour_force_participation"): tuple(range(2006, 2012)),
    ("JP", "money.budget_balance_gdp"): (2006,),
    **{(c, "consumer.household_consumption"): tuple(range(2006, 2026))
       for c in ("BR", "DE", "EU", "GB", "IN", "TH")},       # DF-16: share of GDP, replacing
}
REPLACED = {"BR", "DE", "EU", "GB", "IN", "TH"}
REJECTED = {
    ("IN", "money.budget_balance_gdp"): "residual",
    ("CN", "debt.external"): "deviates",
    ("ID", "debt.external"): "deviates",
    ("BD", "debt.external"): "deviates",
    ("BD", "fx.trade_balance"): "deviates",                   # goods only vs goods and services
    ("VN", "equity.market_cap_gdp"): "residual",
}


@pytest.fixture(scope="module")
def planned():
    settings = load()
    raw = read_frozen(FROZEN_RAW)
    rows = json.loads(FROZEN_PUBLIC.read_text(encoding="utf-8"))["fetches"]
    available = {(r["provider"], r["code"], r["country"]):
                 (r["fetch_id"], {int(y): v for y, v in r["values"].items()}) for r in rows}
    filled, records = public.plan(raw, settings, DEFAULT, available)
    return raw, filled, {(r.country, r.series_id): r for r in records}


def test_every_candidate_has_a_verdict(planned):
    _, _, records = planned
    assert set(records) == set(ACCEPTED) | set(REJECTED)


@pytest.mark.parametrize("key, years", ACCEPTED.items())
def test_accepted_fills(planned, key, years):
    record = planned[2][key]
    assert record.accepted and record.years_filled == years
    if record.mode != "share":
        assert record.deviation <= record.tolerance
    assert record.fetch_ids, "a fill must cite the response it came from"


@pytest.mark.parametrize("key, word", REJECTED.items())
def test_rejected_fills_keep_the_gap(planned, key, word):
    raw, filled, records = planned
    assert not records[key].accepted and word in records[key].reason
    before = next(s for s in raw.series if (s.definition.country, s.definition.series_id) == key)
    after = next(s for s in filled.series if (s.definition.country, s.definition.series_id) == key)
    assert before.cells == after.cells


def test_no_primary_cell_changes_except_declared_replacements(planned):
    raw, filled, _ = planned
    for a, b in zip(raw.series, filled.series):
        primary = {c.date: c for c in b.cells if c.source == raw.primary_source}
        if (a.definition.country, a.definition.series_id) in {(c, "consumer.household_consumption") for c in REPLACED}:
            assert primary == {}, "a replaced series keeps no primary cell"
        else:
            assert primary == {c.date: c for c in a.cells}


def test_a_replacement_is_a_plausible_share_of_bloomberg_gdp(planned):
    raw, filled, records = planned
    get = {(s.definition.country, s.definition.series_id): {c.date: c.value for c in s.cells} for s in filled.series}
    for c in REPLACED:
        cons, gdp = get[(c, "consumer.household_consumption")], get[(c, "production.gdp_nominal")]
        shares = [cons[d] / gdp[d] for d in cons if d.endswith("-12-31") and d in gdp]
        assert shares and 0.2 <= min(shares) and max(shares) <= 0.9
        assert records[(c, "consumer.household_consumption")].cells_replaced > 0


def test_the_filled_snapshot_is_a_deterministic_child(planned):
    raw, filled, _ = planned
    again = public.plan(raw, load(), DEFAULT, {
        (r["provider"], r["code"], r["country"]): (r["fetch_id"], {int(y): v for y, v in r["values"].items()})
        for r in json.loads(FROZEN_PUBLIC.read_text(encoding="utf-8"))["fetches"]})[0]
    assert filled.parent_id == raw.snapshot_id
    assert filled.snapshot_id == again.snapshot_id and filled.snapshot_id.startswith(raw.snapshot_id + ".public-")


def test_an_anchored_fill_lands_in_the_anchor_unit(planned):
    """Bangladesh consumption has no Bloomberg values; scaled through GDP, it must come out
    as a plausible share of Bloomberg GDP."""
    _, filled, _ = planned
    get = {(s.definition.country, s.definition.series_id): {c.date: c.value for c in s.cells} for s in filled.series}
    c, g = get[("BD", "consumer.household_consumption")], get[("BD", "production.gdp_nominal")]
    shares = [c[d] / g[d] for d in c if d.endswith("-12-31") and d in g]
    assert 0.5 < min(shares) and max(shares) < 0.85
