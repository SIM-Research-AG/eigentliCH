"""The input: datafeed's panel, read live, and the frozen copy of it in ``golden/``.

mrs reads no file and no source table. Its input is datafeed's ``GET /panel`` for the 29
``M_TS`` series in ``series.py`` plus the public replacements where the snapshot carries
them, gated by ``GET /coverage``; the default snapshot is datafeed's market layer (DF-18),
named in ``config.yaml``. The golden input is datafeed's raw snapshot,
frozen over HTTP by ``golden/build_golden.py``; from it, :func:`mrs.inputs.matlab_view`
rebuilds MATLAB's own ``M_TS`` exactly (checked against ``M_TS.mat`` itself when present).
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import numpy as np
import pytest

from mrs.clients import DatafeedClient, UpstreamError, panel_checksum
from mrs.inputs import PLACEHOLDER_VALUE, matlab_view, matrix
from mrs.series import BY_ID, PUBLIC_SERIES_IDS, REQUIRED_SERIES
from mrs.settings import load

from .conftest import RAW_ID


# ---------------------------------------------------------------------------
# The frozen copy
# ---------------------------------------------------------------------------

def test_the_frozen_copy_is_complete_and_unaltered(frozen):
    panel, source = frozen["panel"], frozen["source"]
    assert panel.snapshot_id == source["snapshot_id"] == RAW_ID
    assert panel_checksum(panel) == source["panel_sha256"]
    assert {s.series_id for s in panel.series} == set(REQUIRED_SERIES) == set(source["series"])
    countries = {s.country for s in panel.series}
    assert len(countries) == 16 and len(panel.series) == 16 * len(REQUIRED_SERIES)
    assert (panel.dates[0], panel.dates[-1], len(panel.dates)) == ("2006-01-31", "2026-01-31", 241)
    assert all(f == "observed" for s in panel.series for f in s.flags if f != "missing"), \
        "the raw snapshot carries Bloomberg cells only"


def test_datafeed_still_serves_it(frozen, datafeed):
    """The live raw snapshot serves the frozen copy cell by cell, with the same checksum."""
    client = DatafeedClient(datafeed["url"], 60)
    try:
        live, sha = client.panel(RAW_ID, REQUIRED_SERIES)
        manifest = httpx.get(f"{datafeed['url']}/snapshots/{RAW_ID}", timeout=30).json()
    finally:
        client.close()
    assert sha == frozen["source"]["panel_sha256"]
    assert live == frozen["panel"]
    assert manifest["checksum"] == frozen["source"]["datafeed_checksum"]


def test_placeholders_are_the_documented_ones(frozen):
    """37 placeholder country-series in datafeed; 34 in series mrs reads: 24 market ones, VN
    wage growth (shared with HoNI) and 9 of the high-yield yield to worst."""
    blank = sorted((c.country, c.series_id) for c in frozen["conversions"] if c.placeholder)
    assert len(blank) == 34 and ("VN", "consumer.wage_growth") in blank
    assert {s for _, s in blank} == {
        "consumer.unemployment", "consumer.wage_growth", "debt.senior_loan_etf", "debt.npl_ratio",
        "equity.banks_total_return", "fx.beer", "inflation.ppi_yoy", "yields.high_yield_index",
        "yields.high_yield_ytw"}
    lookup = {(s.country, s.series_id): s for s in frozen["panel"].series}
    assert all(all(v is None for v in lookup[k].values) for k in blank), "a placeholder has cells"


# ---------------------------------------------------------------------------
# The two views
# ---------------------------------------------------------------------------

def test_views_keep_gaps_and_rebuild_matlab_zeros_and_ones(frozen):
    panel, conv = frozen["panel"], frozen["conversions"]
    countries = sorted({s.country for s in panel.series})
    for series_id in REQUIRED_SERIES:
        prod = matrix(panel, series_id, countries)
        mat = matlab_view(panel, series_id, countries, conv)
        present = np.isfinite(prod)
        assert np.array_equal(mat[present], prod[present]), series_id
        blank = {c.country for c in conv if c.series_id == series_id and c.placeholder}
        for j, country in enumerate(countries):
            gaps = ~present[:, j]
            expected = PLACEHOLDER_VALUE if country in blank else 0.0
            assert (mat[gaps, j] == expected).all(), f"{country}/{series_id}"


def test_matlab_view_is_m_ts_exactly(frozen):
    """Against M_TS.mat itself: every cell of the 29 columns, 16 countries, 241 months."""
    from datafeed.settings import load as load_datafeed

    m = load_datafeed().matlab
    path = m.dir / m.file
    if not path.is_file():
        pytest.skip(f"M_TS.mat not found at {path}; set DATAFEED_MATLAB_DIR to run this check")
    sio = pytest.importorskip("scipy.io")
    data = sio.loadmat(path, squeeze_me=True, struct_as_record=False)["M_TS"]
    panel, conv = frozen["panel"], frozen["conversions"]
    fields = {c["code"]: c["matlab"] for c in frozen["countries"] if c.get("matlab")}
    countries = sorted({s.country for s in panel.series})
    compared = 0
    for series_id in REQUIRED_SERIES:
        sheet, col = BY_ID[series_id].matlab
        ours = matlab_view(panel, series_id, countries, conv)
        for j, country in enumerate(countries):
            block = np.asarray(getattr(getattr(data, fields[country]), sheet), dtype=float)
            if block.ndim == 1:                  # one-series sheet (Commodity)
                block = block[:, None]
            theirs = np.nan_to_num(block[:, col - 1], nan=0.0)   # the loader's D(isnan(D)) = 0
            assert np.array_equal(ours[:, j], theirs), f"{country}/{series_id}"
            compared += theirs.size
    assert compared == 29 * 16 * 241


# ---------------------------------------------------------------------------
# The live panel through the service
# ---------------------------------------------------------------------------

def test_config_pins_a_snapshot():
    """config.yaml names one datafeed snapshot explicitly, never "latest" (MRS-14). Which
    one is the live datafeed's business (HANDOVER.md); the suite reads its own bootstrap."""
    snapshot = load().snapshot_id
    assert snapshot and snapshot.lower() not in {"latest", "newest", "current"}


def test_input_reads_the_configured_snapshot_live(client, datafeed):
    report = client.get("/input").json()
    assert report["snapshot_id"] == datafeed["market"]
    assert report["contract_version"] == "mrs-input@1.0.0"
    assert (report["months"], len(report["countries"])) == (241, 16)
    assert [s["series_id"] for s in report["series"]] == list(REQUIRED_SERIES + PUBLIC_SERIES_IDS)
    by_id = {s["series_id"]: s for s in report["series"]}
    # The MATLAB inputs stay as MATLAB read them; the replacements carry the data (DF-18).
    assert by_id["fx.beer"]["countries_with_data"] == [] == by_id["volatility.fear_barometer"]["countries_with_data"]
    assert by_id["volatility.skew"]["countries_without_data"] == []
    assert by_id["fx.neer_broad"]["countries_without_data"] == ["BD", "VN"]
    assert by_id["yields.high_yield_ytw"]["countries_with_data"] == ["CN", "EU", "US"]
    assert by_id["commodity.gold"]["countries_without_data"] == []
    assert by_id["debt.npl_ratio"]["countries_without_data"] == ["CH"]
    assert by_id["consumer.household_consumption"]["from_public_sources"] > 0, "the six replacements"
    assert report["plausibility"] == []


def test_input_on_the_raw_snapshot_matches_the_frozen_copy(client, frozen):
    report = client.get("/input", params={"snapshot_id": RAW_ID}).json()
    assert report["panel_sha256"] == frozen["source"]["panel_sha256"]
    assert all(s["from_public_sources"] == 0 for s in report["series"])


def test_unknown_snapshot_is_404(client):
    r = client.get("/input", params={"snapshot_id": "no-such-snapshot"})
    assert r.status_code == 404 and "no-such-snapshot" in r.json()["detail"]


def test_a_snapshot_without_the_market_series_is_refused(settings, datafeed):
    """A datafeed that lacks a series: 503 naming it, before the panel is read."""
    from fastapi.testclient import TestClient

    from mrs.api import create_app

    live = httpx.Client(base_url=datafeed["url"], timeout=60)
    panel_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/panel":
            panel_calls.append(request)
        upstream = live.get(request.url.path, params=request.url.params)
        if request.url.path == "/coverage":
            body = upstream.json()
            body["rows"] = [r for r in body["rows"] if r["series_id"] != "fx.dxy"]
            return httpx.Response(200, content=json.dumps(body).encode())
        return httpx.Response(upstream.status_code, content=upstream.content)

    try:
        with TestClient(create_app(settings, datafeed_transport=httpx.MockTransport(handler))) as c:
            r = c.get("/input")
    finally:
        live.close()
    assert r.status_code == 503 and "fx.dxy" in r.json()["detail"]
    assert panel_calls == []


def test_datafeed_down_is_503_with_the_remedy(settings):
    from fastapi.testclient import TestClient

    from mrs.api import create_app
    down = replace(settings, datafeed_url="http://127.0.0.1:9")
    with TestClient(create_app(down)) as c:
        r = c.get("/input")
    assert r.status_code == 503 and "start.cmd" in r.json()["detail"]


def test_a_panel_that_breaks_the_contract_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"contract_version": "panel@9.9.9"})

    client = DatafeedClient("http://datafeed", transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError, match="panel@1.1.0"):
        client.panel(RAW_ID, REQUIRED_SERIES)


def test_meta_and_contracts_name_datafeed(client, datafeed):
    meta = client.get("/meta").json()
    assert meta["upstream"]["datafeed"] == datafeed["url"]
    assert meta["upstream"]["snapshot_id"] == datafeed["market"]
    contracts = client.get("/contracts").json()
    assert contracts["Panel(datafeed)"] == {**contracts["Panel(datafeed)"], "version": "panel@1.1.0",
                                            "direction": "in"}
    assert contracts["InputReport"]["direction"] == "out"
