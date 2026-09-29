"""The market layer (DF-18): unit corrections, public market series and monthly fills.

Pure tests of the plan on small snapshots, parser tests on literal responses, and checks
on the store the real bootstrap built from the frozen responses in ``golden/``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from datafeed.clients import PublicSourceError, parse_bis, parse_cboe
from datafeed.contracts import CellIn, SeriesDefinition, SeriesIn, SnapshotIn
from datafeed.etl import market
from datafeed.settings import Market, MarketCorrection, MarketSource, load

from .conftest import RAW_ID

REGISTRY = {"volatility.implied": {"category": "volatility", "unit": "ratio", "period": "daily"},
            "volatility.skew": {"category": "volatility", "unit": "index", "period": "daily"}}
DATES = ("2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30", "2020-05-31", "2020-06-30",
         "2020-07-31", "2020-08-31")


def _snapshot(values: dict[str, dict[str, float]]) -> SnapshotIn:
    series = []
    for country, cells in values.items():
        d = SeriesDefinition(series_id="volatility.implied", country=country, category="volatility",
                             unit="ratio", currency="USD", magnitude=0.01, period="daily",
                             pull_code="X Index", field="PX_LAST", source="bloomberg", description="Vol")
        series.append(SeriesIn(definition=d, cells=tuple(
            CellIn(date=k, value=v, flag="observed", source="bloomberg") for k, v in sorted(cells.items()))))
    return SnapshotIn(snapshot_id="t", source="test", primary_source="bloomberg", as_of="2020-08-31",
                      first_date=DATES[0], last_date=DATES[-1], series=tuple(series))


def _settings(**market_kw):
    return replace(load(), market=Market(**market_kw))


# -- parsers -------------------------------------------------------------------------

def test_cboe_takes_the_last_close_of_each_month():
    body = (b"DATE,OPEN,HIGH,LOW,CLOSE\n01/30/2020,1,1,1,10.0\n01/31/2020,1,1,1,12.5\n"
            b"02/03/2020,1,1,1,13.0\n")
    assert parse_cboe(body) == {"2020-01-31": 12.5, "2020-02-29": 13.0}
    assert parse_cboe(b"DATE,SKEW\n03/02/2020,120.5\n") == {"2020-03-31": 120.5}
    with pytest.raises(PublicSourceError):
        parse_cboe(b"<html>")


def test_bis_reads_the_monthly_observations():
    body = b"FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\nM,BR,2020-01,101.5\nM,BR,2020-02,NaN\nM,BR,2020-03,99\n"
    assert parse_bis(body) == {"2020-01-31": 101.5, "2020-03-31": 99.0}


# -- the plan ------------------------------------------------------------------------

def test_a_correction_rescales_cells_and_says_so():
    parent = _snapshot({"ID": {d: 19.6 for d in DATES}})
    s = _settings(corrections=(MarketCorrection("volatility.implied", ("ID", "MY"), 0.01, "percent"),))
    child, records = market.plan(parent, s, REGISTRY, {})
    (sid,) = child.series
    assert all(abs(c.value - 0.196) < 1e-12 for c in sid.cells)
    assert sid.definition.magnitude == pytest.approx(0.0001) and "rescaled x0.01" in sid.definition.description
    by = {r.country: r for r in records}
    assert by["ID"].accepted and by["ID"].cells_written == len(DATES)
    assert not by["MY"].accepted and by["MY"].reason == "no primary cells to correct"
    assert child.parent_id == "t" and child.market == records


def test_a_public_series_gets_its_own_id_and_every_country_its_row():
    parent = _snapshot({"US": {d: 0.2 for d in DATES}})
    src = MarketSource("volatility.skew", "cboe", "SKEW", ("US", "CH"), note="tail risk")
    child, records = market.plan(parent, _settings(sources=(src,)), REGISTRY,
                                 {("cboe", "SKEW"): ("MKT-1", {d: 130.0 for d in DATES} | {"2030-01-31": 1.0})})
    skew = {s.definition.country: s for s in child.series if s.definition.series_id == "volatility.skew"}
    assert set(skew) == {"US", "CH"}
    assert [c.date for c in skew["CH"].cells] == list(DATES)          # off-axis months dropped
    assert all(c.source == "cboe:SKEW" for c in skew["CH"].cells)
    assert skew["CH"].definition.pull_code == "SKEW" and skew["CH"].definition.description == "tail risk"
    assert all(r.accepted and r.fetch_ids == ("MKT-1",) for r in records)


def test_a_series_not_in_the_registry_is_refused():
    parent = _snapshot({"US": {d: 0.2 for d in DATES}})
    src = MarketSource("volatility.unknown", "cboe", "SKEW", ("US",))
    child, (r,) = market.plan(parent, _settings(sources=(src,)), REGISTRY, {("cboe", "SKEW"): ("MKT-1", {DATES[0]: 1.0})})
    assert child is None and not r.accepted and r.reason == "series not in the registry"


def test_a_fill_goes_into_missing_cells_only_and_needs_the_fit():
    primary = {d: 0.30 for d in DATES[4:]}
    public = {d: 30.0 for d in DATES}
    parent = _snapshot({"CN": primary})
    fill = MarketSource("volatility.implied", "cboe", "VXFXI", ("CN",), unit_scale=0.01, fill=True)
    s = _settings(sources=(fill,), min_overlap_months=3)
    child, (r,) = market.plan(parent, s, REGISTRY, {("cboe", "VXFXI"): ("MKT-2", public)})
    cells = {c.date: c for c in child.series[0].cells}
    assert r.accepted and r.cells_written == 4 and r.scale == pytest.approx(1.0)
    assert {d for d, c in cells.items() if c.source == "cboe:VXFXI"} == set(DATES[:4])
    assert all(cells[d].source == "bloomberg" for d in DATES[4:])       # primary never overwritten

    noisy = {d: v * (1.5 if d == DATES[5] else 1.0) for d, v in public.items()}
    child, (r,) = market.plan(parent, s, REGISTRY, {("cboe", "VXFXI"): ("MKT-2", noisy)})
    assert child is None and not r.accepted and r.reason.startswith("fit fails")


def test_an_identical_index_only_has_to_agree_on_the_unit():
    primary = {d: 0.30 for d in DATES[2:]}
    public = {d: 30.0 * (1.2 if d == DATES[3] else 1.0) for d in DATES}   # one month closes elsewhere
    parent = _snapshot({"CN": primary})
    fill = MarketSource("volatility.implied", "cboe", "VXFXI", ("CN",), unit_scale=0.01, fill=True, identical=True)
    child, (r,) = market.plan(parent, _settings(sources=(fill,), identical_min_overlap=6), REGISTRY,
                              {("cboe", "VXFXI"): ("MKT-3", public)})
    assert r.accepted and r.cells_written == 2 and "same index" in r.reason

    wrong_unit = MarketSource("volatility.implied", "cboe", "VXFXI", ("CN",), fill=True, identical=True)
    child, (r,) = market.plan(parent, _settings(sources=(wrong_unit,), identical_min_overlap=6), REGISTRY,
                              {("cboe", "VXFXI"): ("MKT-3", public)})
    assert child is None and not r.accepted and "units disagree" in r.reason


def test_the_plan_is_deterministic():
    parent = _snapshot({"ID": {d: 19.6 for d in DATES}})
    s = _settings(corrections=(MarketCorrection("volatility.implied", ("ID",), 0.01, "percent"),))
    assert market.plan(parent, s, REGISTRY, {})[0].snapshot_id == market.plan(parent, s, REGISTRY, {})[0].snapshot_id


# -- the store the bootstrap built ---------------------------------------------------

@pytest.fixture(scope="module")
def market_id(service) -> str:
    filled = next(s.snapshot_id for s in service.snapshots() if s.parent_id == RAW_ID)
    return next(s.snapshot_id for s in service.snapshots() if s.parent_id == filled)


def test_the_market_snapshot_replaces_the_broken_inputs(service, market_id):
    from datafeed.contracts import PanelRequest

    manifest = service.snapshot(market_id)
    assert manifest.contract_version == "snapshot@1.2.0" and manifest.market
    panel = service.panel(PanelRequest(snapshot_id=market_id,
                                       series=("volatility.skew", "fx.neer_broad", "volatility.implied")))
    got = {(s.country, s.series_id): s for s in panel.series}
    assert sum(1 for (c, sid) in got if sid == "volatility.skew") == 16
    assert {c for (c, sid), s in got.items() if sid == "fx.neer_broad" and any(v is not None for v in s.values)} \
        == {"BR", "CH", "CN", "DE", "ES", "EU", "GB", "ID", "IN", "JP", "MY", "PH", "TH", "US"}
    for country in ("BD", "ID", "JP", "US", "VN"):       # every implied volatility is now a decimal
        values = [v for v in got[(country, "volatility.implied")].values if v is not None]
        assert values and max(values) < 1.5, country
    cn = got[("CN", "volatility.implied")]
    assert sum(v is not None for v in cn.values) > 150    # 48 from Bloomberg + the Cboe fill


def test_the_market_layer_changes_only_what_it_records(service, market_id):
    from datafeed.contracts import PanelRequest

    filled = service.snapshot(market_id).parent_id
    before = {(s.country, s.series_id): s.values for s in service.panel(PanelRequest(snapshot_id=filled)).series}
    after = {(s.country, s.series_id): s.values for s in service.panel(PanelRequest(snapshot_id=market_id)).series}
    touched = {(r.country, r.series_id) for r in service.snapshot(market_id).market if r.accepted and r.cells_written}
    for key, values in before.items():
        if key not in touched:
            assert after[key] == values, key
    assert set(after) - set(before) == {k for k in touched if k[1] in ("volatility.skew", "fx.neer_broad")}
