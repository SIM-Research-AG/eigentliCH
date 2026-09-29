"""The cockpit against fake engines on a mock transport: no engine, database or network needed.

What matters here is the plumbing the CIO relies on: the proxy passes answers through unchanged
and refuses writes in CIO mode, the status graph survives engines that are down, the decision
log is append-only and validated, and the Excel exports are well-formed workbooks that carry
the engines' figures unchanged.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from cockpit.api import create_app
from cockpit.settings import load

INDICES = ["budget_balance", "monetary_supply", "government_debt", "real_rate_10y", "market_cap",
           "external_debt_affordability", "external_debt_exposure", "terms_of_trade", "import_reserves",
           "corruption_freedom", "consumption_power", "population_growth", "gdp_per_capita_growth",
           "consumption_dependency", "labour_force"]


def artefact() -> dict:
    m = lambda a, b: [[a, b], [b, None]]  # noqa: E731  years by countries, one gap
    return {
        "artefact_id": "HNS-test", "notice": "Model-derived research output. Not investment advice.",
        "years": [2024, 2025], "countries": [{"code": "CH", "name": "Switzerland"}, {"code": "US", "name": "United States"}],
        "national": m(4.25, 1.0), "sectors": {s: m(3.5, 2.0) for s in ("financial", "international", "real")},
        "index_scores": {i: m(5.0, 1.0) for i in INDICES}, "index_raw": {i: m(0.123456789, -0.5) for i in INDICES},
        "capital_saturation": m(3.1, 4.6),
        "coverage": {"country_years": 4, "index_cells": 60, "index_cells_missing": 15, "sectors_reweighted": 0,
                     "sectors_unscored": 3, "national_unscored": 1, "missing_series": [],
                     "dropped": [{"country": "US", "year": 2025, "sector": "real", "indices_missing": ["labour_force"], "scored": False}],
                     "public_fills": [], "excluded": []},
        "provenance": {"snapshot_id": "snap-1", "as_of": "2026-01-05", "upstream": {}, "engine_version": "honi@1.1.0",
                       "contract_versions": {}, "calibration_version": "1.1.0", "calibration_hash": "CAL-x",
                       "idempotency_key": "IDK-x", "regime_id": None, "label": "model-derived"},
    }


def trends() -> dict:
    series = [{"key": "national", "label": "HoNI", "basis": "score", "sector": None, "index": None,
               "latest": [4.25, None], "base": [3.0, 1.5], "change": [1.25, None], "slope": [0.125, None],
               "level_z": [1.5, None], "n": [10, 9]}]
    return {"contract_version": "honi-trends@1.0.0", "artefact_id": "HNS-test", "year": 2025, "window": 10,
            "first_year": 2016, "base_year": 2015, "min_obs": 5,
            "countries": [{"code": "CH", "name": "Switzerland"}, {"code": "US", "name": "United States"}],
            "series": series, "definitions": {"change": "latest - base"}}


def fm_payloads() -> dict:
    states = [{"state": k, "value": k / 100, "method": "data-driven" if k % 5 == 3 else "interpolated", "n_obs": 1} for k in range(1, 26)]
    return {
        "/v1/instruments": [{"instrument_id": "INS-a", "name": "Alpha", "role": "gain", "asset_class": "Equity", "ticker": "AAA Index",
                             "region_scope": "Europe", "region_geo": "Europe", "currency": "CHF", "liquidity": "Daily",
                             "countries": ["CH", "US"]}],
        "/v1/data/performance": {"calibration_id": "CAL-f", "registered": 1, "with_history": 1, "without_history": 0,
                                 "unit_note": "u", "caveat": "c", "instruments": [
                                     {"instrument_id": "INS-a", "coverage": "data-driven", "has_history": True,
                                      "performance": {"months": 12, "annualised_log_return": 0.05}}]},
        "/v1/data/classification": {"benchmark": "INS-a", "beta_bound": 0.4, "assessed": 1, "flagged": 0,
                                    "instruments": [{"instrument_id": "INS-a", "name": "Alpha", "equity_beta": 1.0, "crisis_mean": -0.2, "flag": None}]},
        "/v1/data/overlap": {"threshold": 0.95, "min_shared_months": 36, "ticker_collisions": [], "register_defect": [],
                             "proxy_artefact": [], "economic_overlap": []},
        "/v1/return-set": {"return_set_id": "RS-1", "role_profiles": [{"role": "gain", "states": states}],
                           "instrument_profiles": [{"key": "INS-a", "states": states}]},
        "/v1/axis": {"state_axis": [0.6 + 0.2 * k for k in range(25)]},
    }


class FakeEngines(httpx.AsyncBaseTransport):
    """honi and fmre answer; every other port refuses the connection."""

    def __init__(self):
        self.calls: list[tuple[str, str, bytes]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        self.calls.append((request.method, str(request.url), body))
        port, path = request.url.port, request.url.path
        if port == 8002:
            if path == "/health":
                return httpx.Response(200, json={"status": "ok", "engine_version": "honi@1.1.0"})
            if path == "/meta":
                return httpx.Response(200, json={"engine_version": "honi@1.1.0", "allowlist": {"ok": True, "packages": {}}})
            if path == "/run":
                return httpx.Response(200, json={"run_id": "RUN-1", "artefact_id": "HNS-test", "cached": True, "echo": json.loads(body)})
            if path == "/artefacts/HNS-test":
                return httpx.Response(200, json=artefact())
            if path == "/peer-stats/HNS-test":
                return httpx.Response(200, json={"artefact_id": "HNS-test", "rows": [
                    {"index": "budget_balance", "year": 2025, "basis": "score", "n": 2, "min": 1.0, "p25": 2.0, "median": 3.0, "p75": 4.0, "max": 5.0}]})
            if path == "/ranges":
                return httpx.Response(200, json={"calibration_version": request.url.params.get("version"), "indices": [
                    {"index": "budget_balance", "sector": "financial", "kind": "ramp", "range": [-0.1, -0.035, 0.0], "weight": 1.0, "definition": "d"}]})
            if path == "/trends/HNS-test":
                return httpx.Response(200, json=trends())
            if path == "/runs/RUN-1":
                return httpx.Response(200, json={"run_id": "RUN-1", "warnings": ["w1"]})
            if path == "/teapot":
                return httpx.Response(418, text="short and stout", headers={"x-engine": "honi"})
            return httpx.Response(404, json={"detail": "no such path"})
        if port == 8006:
            payloads = fm_payloads()
            if path == "/v1/health":
                return httpx.Response(200, json={"status": "ok", "engine_version": "fm@1.0.0"})
            if path in payloads:
                return httpx.Response(200, json=payloads[path])
            return httpx.Response(404, json={"detail": "no"})
        raise httpx.ConnectError("refused", request=request)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    bench = tmp_path / "bench.html"
    bench.write_text("<!doctype html><title>bench</title>", encoding="utf-8")
    text = f"""
service: {{host: 127.0.0.1, port: 8000, mode: development}}
data_dir: {tmp_path.as_posix()}/data
cio: {{snapshot: snap-1, writable: ["honi:/run"]}}
engines:
  - {{key: datafeed, number: 1, name: Data Feed, url: "http://127.0.0.1:8001", status: built}}
  - {{key: honi, number: 2, name: HoNI, url: "http://127.0.0.1:8002", status: built, consumes: [datafeed], bench: "{bench.as_posix()}"}}
  - {{key: fmre, number: 6, name: Fund Map, url: "http://127.0.0.1:8006", status: built, api: v1}}
  - {{key: pcp, number: 7, name: Optimiser, url: "http://127.0.0.1:8007", status: planned, consumes: [fmre]}}
"""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def client_for(config: Path, mode: str = "development") -> tuple[TestClient, FakeEngines]:
    fake = FakeEngines()
    settings = load(config, env={"COCKPIT_MODE": mode})
    return TestClient(create_app(settings, transport=fake)), fake


@pytest.fixture
def dev(config):
    client, fake = client_for(config)
    with client:
        yield client, fake


def sheets(xlsx: bytes) -> tuple[list[str], dict[str, str]]:
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    assert z.testzip() is None
    names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode())
    parts = {n: z.read(f"xl/worksheets/sheet{i}.xml").decode() for i, n in enumerate(names, start=1)}
    return names, parts


# ---- configuration ----------------------------------------------------------------------

def test_the_committed_config_loads_and_names_every_engine_once():
    s = load()
    keys = [e.key for e in s.engines]
    assert len(keys) == len(set(keys)) and {"datafeed", "honi", "fmre", "pcp"} <= set(keys)
    assert s.port == 8000
    for e in s.engines:
        if e.kind == "engine":
            assert e.url.endswith(f":80{e.number:02d}"), f"{e.key}: Engine NN listens on 80NN"
        else:  # C-18: an app has no engine number and must not take an engine's port
            assert e.number is None, f"{e.key}: an app carries no engine number"
            assert not any(x.kind == "engine" and x.url == e.url for x in s.engines), f"{e.key}: on an engine's port"
        assert e.bench is None or e.bench.is_file(), f"{e.key}: bench {e.bench} is missing"
        assert e.python is None or e.python.is_file(), f"{e.key}: python {e.python} is missing"
    app = s.engine("eigentlich")
    assert app.kind == "app" and app.url.endswith(":8017") and app.autostart
    assert s.curator_db.user == "curator" and s.curator_db.schema == "eigentlich"


def test_the_committed_config_holds_no_password():
    import yaml
    from cockpit.settings import ROOT
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert "password" not in (raw.get("curator_db") or {}), "C-16: the password lives in config.local.yaml"
    assert "config.local.yaml" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_an_engine_in_another_venv_is_started_with_its_own_python(tmp_path):
    """C-17: lbs, report, chatbot and the consumer app live in eigentliCH_Engines/.venv."""
    from cockpit.launcher import Launcher
    own = tmp_path / "python.exe"
    own.write_text("", encoding="utf-8")
    p = tmp_path / "config.yaml"
    p.write_text(f"""data_dir: {tmp_path.as_posix()}/data
engines:
  - {{key: a, number: 1, name: A, url: "http://127.0.0.1:8001", status: built}}
  - {{key: b, number: 2, name: B, url: "http://127.0.0.1:8002", status: built, python: "{own.as_posix()}"}}
  - {{key: c, number: 3, name: C, url: "http://127.0.0.1:8003", status: built, python: "{(tmp_path / 'nope.exe').as_posix()}"}}
""", encoding="utf-8")
    s = load(p, env={})
    launcher = Launcher(s)
    assert launcher.python_for(s.engine("a")) == launcher.python
    assert launcher.python_for(s.engine("b")) == str(own.resolve())
    with pytest.raises(LookupError, match="does not exist"):
        launcher.python_for(s.engine("c"))  # never falls back to an interpreter without its packages


def test_an_app_needs_no_number_but_an_engine_does(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('engines:\n  - {key: x, kind: app, name: X, url: "http://h:8017", status: scaffold}\n', encoding="utf-8")
    assert load(p, env={}).engine("x").number is None
    p.write_text('engines:\n  - {key: x, name: X, url: "http://h:8017", status: built}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="needs its number"):
        load(p, env={})


def test_an_engine_may_not_take_a_cockpit_route_name(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('engines:\n  - {key: graph, number: 1, name: x, url: "http://h:1", status: built}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="collides"):
        load(p, env={})


# ---- status graph -----------------------------------------------------------------------

def test_graph_reports_up_and_down_engines_without_failing(dev):
    client, _ = dev
    g = client.get("/api/graph").json()
    nodes = {n["key"]: n for n in g["nodes"]}
    assert nodes["honi"]["up"] and nodes["honi"]["meta"]["allowlist"]["ok"]
    assert nodes["fmre"]["up"] and nodes["fmre"]["meta"] is None  # v1 engines have no /meta
    assert not nodes["datafeed"]["up"] and "not running" in nodes["datafeed"]["error"]
    assert ["datafeed", "honi"] in g["edges"] and ["fmre", "pcp"] in g["edges"]


# ---- proxy ------------------------------------------------------------------------------

def test_proxy_passes_status_body_and_headers_through(dev):
    client, fake = dev
    r = client.get("/api/honi/teapot?x=1")
    assert r.status_code == 418 and r.text == "short and stout" and r.headers["x-engine"] == "honi"
    assert fake.calls[-1][1] == "http://127.0.0.1:8002/teapot?x=1"


def test_proxy_forwards_a_post_body_unchanged(dev):
    client, fake = dev
    r = client.post("/api/honi/run", json={"snapshot_id": "snap-1"})
    assert r.status_code == 200 and r.json()["echo"] == {"snapshot_id": "snap-1"}
    assert fake.calls[-1][0] == "POST"


def test_proxy_to_an_engine_that_is_down_says_so(dev):
    client, _ = dev
    r = client.get("/api/datafeed/health")
    assert r.status_code == 502 and "Data Feed" in r.json()["detail"]
    assert client.get("/api/nosuch/health").status_code == 404


def test_cio_mode_refuses_writes_except_the_listed_ones(config):
    client, fake = client_for(config, mode="cio")
    with client:
        assert client.post("/api/honi/run", json={"snapshot_id": "s"}).status_code == 200
        assert client.put("/api/honi/calibration", json={}).status_code == 403
        assert client.post("/api/fmre/v1/instruments", json={}).status_code == 403
        assert not any(c[0] == "PUT" for c in fake.calls), "a refused write must never reach the engine"
        assert client.get("/bench/honi/").status_code == 404
        assert client.get("/api/config").json()["mode"] == "cio"


def test_bench_is_served_in_development_mode(dev):
    client, _ = dev
    r = client.get("/bench/honi/")
    assert r.status_code == 200 and "<title>bench</title>" in r.text
    assert client.get("/bench/fmre/").status_code == 404  # no bench configured


def test_front_end_is_served(dev):
    client, _ = dev
    r = client.get("/")
    assert r.status_code == 200 and "sim-tech Cockpit" in r.text
    assert client.get("/favicon.ico").status_code == 200


# ---- decision log -----------------------------------------------------------------------

BOUNDS = {"kind": "optimiser_bounds", "title": "Bounds Q4", "author": "CIO",
          "basis": {"honi_artefact": "HNS-test", "snapshot": "snap-1"},
          "rows": [{"code": "CH", "name": "Switzerland", "min_pct": 5, "max_pct": 20, "note": "core"},
                   {"code": "US", "max_pct": 10}]}


def test_decisions_are_appended_and_listed_newest_first(dev, config):
    client, _ = dev
    first = client.post("/api/decisions", json=BOUNDS)
    second = client.post("/api/decisions", json={**BOUNDS, "title": "Bounds Q4 revised"})
    assert first.status_code == second.status_code == 201
    ids = [d["decision_id"] for d in client.get("/api/decisions").json()]
    assert ids == [second.json()["decision_id"], first.json()["decision_id"]]
    assert client.get(f"/api/decisions/{ids[1]}").json()["title"] == "Bounds Q4"
    log = (config.parent / "data" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 2, "append-only: one line per saved decision"


@pytest.mark.parametrize("row", [{"code": "CH", "min_pct": 30, "max_pct": 10},
                                 {"code": "CH", "max_pct": 120}, {"code": "CH", "colour": "red"}])
def test_invalid_bounds_are_refused(dev, row):
    client, _ = dev
    assert client.post("/api/decisions", json={**BOUNDS, "rows": [row]}).status_code == 422
    assert client.get("/api/decisions").json() == []


def test_an_empty_decision_is_refused(dev):
    client, _ = dev
    assert client.post("/api/decisions", json={**BOUNDS, "rows": []}).status_code == 422


# ---- exports ----------------------------------------------------------------------------

def test_honi_workbook_carries_the_engines_figures_unchanged(dev):
    client, _ = dev
    r = client.get("/api/export/honi/HNS-test.xlsx?run_id=RUN-1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxml")
    assert "attachment" in r.headers["content-disposition"]
    names, parts = sheets(r.content)
    assert names[:3] == ["Read me", "Overview 2025", "HoNI Score"]
    assert {"Switzerland", "United States", "Peer stats", "Coverage", "Calibration"} <= set(names)
    assert "<v>4.25</v>" in parts["HoNI Score"] and "<v>0.123456789</v>" in parts["Switzerland"]
    assert "Not investment advice" in parts["Read me"] and "w1" in parts["Read me"]
    # trends as honi published them, and the economies linked to the register
    assert "<v>1.25</v>" in parts["Trends 10y"] and "<v>0.125</v>" in parts["Trends 10y"]
    assert "Alpha" in parts["Exposed instruments"] and "with US" in parts["Exposed instruments"]
    # the gap stays a gap: US 2025 has no national score, and no zero is written for it
    us_2025 = re.search(r'<row r="4">(.*?)</row>', parts["HoNI Score"]).group(1)
    assert "<v>0</v>" not in us_2025


def test_instrument_workbook_and_shortlist(dev):
    client, _ = dev
    d = client.post("/api/decisions", json={"kind": "instrument_selection", "title": "Shortlist",
                                            "rows": [{"instrument_id": "INS-a", "name": "Alpha", "decision": "include"}]}).json()
    r = client.get(f"/api/export/instruments.xlsx?shortlist={d['decision_id']}")
    assert r.status_code == 200
    names, parts = sheets(r.content)
    assert names == ["Read me", "Universe", "Role profiles", "Instrument profiles", "Profile methods", "Register integrity"]
    assert "CH, US" in parts["Universe"]
    linked = client.get(f"/api/export/instruments.xlsx?shortlist={d['decision_id']}&honi_artefact=HNS-test")
    names, parts = sheets(linked.content)
    assert "HoNI exposure" in names and "<v>4.25</v>" in parts["HoNI exposure"] and "one of 2" in parts["HoNI exposure"]
    assert "include" in parts["Universe"] and "Alpha" in parts["Instrument profiles"]
    assert client.get("/api/export/instruments.xlsx?shortlist=DEC-nope").status_code == 404


def test_decision_workbook(dev):
    client, _ = dev
    d = client.post("/api/decisions", json=BOUNDS).json()
    names, parts = sheets(client.get(f"/api/export/decisions/{d['decision_id']}.xlsx").content)
    assert names == ["Decision", "Rows"] and "Switzerland" in parts["Rows"] and "<v>20</v>" in parts["Rows"]


def test_export_says_which_engine_is_missing(dev):
    client, _ = dev
    r = client.get("/api/export/honi/HNS-nope.xlsx")
    assert r.status_code == 502 and "404" in r.json()["detail"]


# ---- curator workflow without a database (C-16) ------------------------------------------

def test_curator_routes_say_when_the_store_is_not_configured(dev):
    client, fake = dev
    st = client.get("/api/curator/status").json()
    assert st["ok"] is False and "password" in st["error"] and st["user"] == "curator"
    r = client.get("/api/curator/clients")
    assert r.status_code == 503 and "COCKPIT_CURATOR_DB_PASSWORD" in r.json()["detail"]
    assert client.get("/api/config").json()["curator_db"]["configured"] is False
    assert not fake.calls, "curator routes never fall through to the engine proxy"


def test_curator_is_a_reserved_segment(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('engines:\n  - {key: curator, number: 1, name: x, url: "http://h:8001", status: built}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="collides"):
        load(p, env={})


# ---- the cockpit holds no maths ---------------------------------------------------------

def test_the_python_side_imports_no_numerics():
    src = Path(__file__).resolve().parents[1] / "src" / "cockpit"
    for f in src.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(numpy|pandas|scipy|statistics)\b", text, re.M), f.name


def test_the_honi_workbook_does_not_need_the_fund_map_engine(config):
    """The instrument link is optional: without fmre the HoNI export still works, minus that sheet."""

    class HoniOnly(FakeEngines):
        async def handle_async_request(self, request):
            if request.url.port == 8006:
                raise httpx.ConnectError("refused", request=request)
            return await super().handle_async_request(request)

    settings = load(config, env={})
    with TestClient(create_app(settings, transport=HoniOnly())) as client:
        r = client.get("/api/export/honi/HNS-test.xlsx")
        assert r.status_code == 200
        names, _ = sheets(r.content)
        assert "Trends 10y" in names and "Exposed instruments" not in names


def test_the_deployed_config_is_cio_mode_and_starts_nothing():
    """DECISIONS C-03: the deploy folder carries the CIO pages only."""
    import importlib.util
    import yaml
    spec = importlib.util.spec_from_file_location("make_deploy", Path(__file__).resolve().parents[1] / "dev" / "make_deploy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = yaml.safe_load(mod.production_config())
    assert cfg["service"]["mode"] == "cio" and "python" not in cfg
    assert all(not ({"bench", "start", "autostart", "python"} & set(e)) for e in cfg["engines"])
    # C-16: pcp's validation is allowed through the proxy; a pcp run only through the curator route
    assert cfg["cio"]["writable"] == ["honi:/run", "cycle:/run", "aggregation:/run", "aggregation:/scenario",
                                     "pcp:/validate"]
    assert "password" not in cfg.get("curator_db", {})


# ---- the Parameters form and the presets (C-21, C-22) -------------------------------------------

import math  # noqa: E402
from typing import Literal, Optional  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402

PRESETS = Path(__file__).resolve().parents[1] / "dev" / "presets"


class _Bound(BaseModel):
    """pcp's Bound (contracts.py), mirrored: both ends fractions, lower not above upper."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    lower: float = Field(default=0.0, ge=0.0, le=1.0)
    upper: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self):
        assert self.lower <= self.upper + 1e-12, "lower above upper"
        return self


PCP_DIMENSIONS = ("currency", "region", "role", "capital_type", "liquidity", "phase", "asset_class")
PCP_BOUND_SOURCE = {"currency": "derived", "liquidity": "derived", "role": "derived",
                    "asset_class": "policy", "capital_type": "policy", "phase": "policy", "region": "policy"}


class PcpMandate(BaseModel):
    """pcp's Mandate (``pcp-mandate@1.0.0``, Optimizer/engines/pcp/src/pcp/contracts.py), mirrored in the
    test, never imported: every field, and the checks its validators make."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["pcp-mandate@1.0.0"] = "pcp-mandate@1.0.0"
    client: str = Field(min_length=1)
    name: str = Field(min_length=1)
    currency: str = Field(default="CHF", pattern=r"^[A-Z]{3}$")
    horizon_years: float = Field(default=1.0, gt=0.0)
    curve_unit: Literal["annualised_log_return", "annualised_decimal"] = "annualised_log_return"
    target_curve: tuple[float, ...]
    universe: tuple[str, ...] = Field(min_length=1)
    max_single_position: float = Field(gt=0.0, le=1.0)
    esg_min: float = Field(default=0.0, ge=0.0)
    fixed_allocations: dict[str, float] = Field(default_factory=dict)
    bounds: dict[str, dict[str, _Bound]] = Field(default_factory=dict)
    bound_sources: dict[str, Literal["derived", "policy"]] = Field(default_factory=dict)
    regime_weights: Optional[dict[str, float]] = None
    regime_market: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        assert len(self.target_curve) == 25 and all(math.isfinite(v) for v in self.target_curve)
        assert len(set(self.universe)) == len(self.universe), "the universe repeats an instrument"
        assert all(k in self.universe and 0 <= w <= 1 for k, w in self.fixed_allocations.items())
        assert sum(self.fixed_allocations.values()) <= 1 + 1e-9
        assert set(self.bounds) <= set(PCP_DIMENSIONS), "unknown bound dimension"
        assert all(PCP_BOUND_SOURCE[d] == s for d, s in self.bound_sources.items()), "a mislabelled bound source"
        assert set(self.bounds) <= set(self.bound_sources), "a bounded dimension names no source"
        assert (self.regime_weights is None) != (self.regime_market is None), "exactly one of the two"
        if self.regime_weights is not None:
            assert self.regime_weights and all(w >= 0 for w in self.regime_weights.values())
            assert abs(sum(self.regime_weights.values()) - 1.0) <= 1e-9
        return self


FORM = {"client": "c-1", "name": "Balanced", "currency": "EUR", "horizon_years": 1,
        "curve": {"points_pct": [5.0] * 12 + [0.0] + [-10.0] * 12},
        "universe": ["INS-a", "INS-b", "INS-c"], "max_single_position_pct": 35, "esg_min": 0.5,
        "fixed_allocations_pct": {"INS-a": 10},
        "bounds_pct": {"role": {"Gain": {"lower_pct": 20, "upper_pct": 60}, "Income": {"lower_pct": None, "upper_pct": None}},
                       "region": {"Europe": {"lower_pct": 0, "upper_pct": 70}},
                       "liquidity": {"Daily": {"lower_pct": 0, "upper_pct": 100}}},
        "regime_weights_pct": {"CH": 50, "EU": 30, "US": 20}}


def test_the_form_is_assembled_into_pcps_mandate(dev):
    """Percent to fraction, percent per year to ln(1 + p/100), each source fixed per dimension."""
    client, fake = dev
    r = client.post("/api/curator/mandate/assemble", json=FORM)
    assert r.status_code == 200, r.text
    m = r.json()["mandate"]
    assert m["curve_unit"] == "annualised_log_return" and len(m["target_curve"]) == 25
    assert m["target_curve"][0] == pytest.approx(math.log(1.05), abs=1e-12)        # 5 % a year -> 0.04879
    assert m["target_curve"][12] == 0.0 and m["target_curve"][24] == pytest.approx(math.log(0.9), abs=1e-12)
    assert m["max_single_position"] == 0.35 and m["fixed_allocations"] == {"INS-a": 0.1}
    assert m["bounds"] == {"role": {"Gain": {"lower": 0.2, "upper": 0.6}}, "region": {"Europe": {"lower": 0.0, "upper": 0.7}}}, \
        "an empty or 0 to 100 % row constrains nothing and is left out"
    assert m["bound_sources"] == {"role": "derived", "region": "policy"}
    assert m["regime_weights"] == {"CH": 0.5, "EU": 0.3, "US": 0.2} and "regime_market" not in m
    assert m["currency"] == "EUR" and m["esg_min"] == 0.5
    PcpMandate.model_validate(m)
    assert "ln(1 + p/100)" in r.json()["conversion"]
    assert not fake.calls, "assembling is the cockpit's own conversion: no engine is asked"
    # and back: the stored mandate in the form's units
    back = client.post("/api/curator/mandate/form", json={"mandate": m}).json()
    assert back["curve"]["points_pct"] == pytest.approx(FORM["curve"]["points_pct"], abs=1e-9)
    assert back["max_single_position_pct"] == 35 and back["regime_weights_pct"] == {"CH": 50, "EU": 30, "US": 20}
    assert back["bounds_pct"]["role"]["Gain"] == {"lower_pct": 20, "upper_pct": 60}


def test_a_preset_curve_is_shifted_and_tilted_and_matched_to_the_required_return(dev):
    from cockpit.mandate import adjust, match_shift
    base = [float(i) for i in range(1, 26)]
    out = adjust(base, 1.5, 2.0)
    assert out[0] == pytest.approx(1 + 1.5 - 2.0) and out[12] == pytest.approx(13 + 1.5)
    assert out[24] == pytest.approx(25 + 1.5 + 2.0)
    assert sum(out) / 25 == pytest.approx(sum(base) / 25 + 1.5), "the tilt keeps the mean"
    assert match_shift(0.042, 3.0) == pytest.approx(1.2)
    client, _ = dev
    form = {**FORM, "curve": {"base_pct": base, "shift_pp": 1.5, "tilt_pp": 2.0, "preset": "x"}}
    m = client.post("/api/curator/mandate/assemble", json=form).json()["mandate"]
    assert m["target_curve"] == pytest.approx([math.log1p(p / 100) for p in out], abs=1e-12)


@pytest.mark.parametrize("change, field", [
    ({"regime_weights_pct": {"CH": 50, "EU": 40}}, "regime_weights"),
    ({"curve": {"points_pct": [1.0] * 24}}, "target_curve"),
    ({"bounds_pct": {"role": {"Gain": {"lower_pct": 70, "upper_pct": 20}}}}, "bounds.role"),
    ({"bounds_pct": {"role": {"Growth": {"lower_pct": 10}}}}, "bounds.role"),
    ({"max_single_position_pct": 0}, "max_single_position"),
    ({"fixed_allocations_pct": {"INS-z": 5}}, "fixed_allocations"),
    ({"regime_market": "global"}, "regime"),
    ({"universe": []}, "universe"),
])
def test_the_assembly_names_the_field_it_cannot_convert(dev, change, field):
    client, _ = dev
    r = client.post("/api/curator/mandate/assemble", json={**FORM, **change})
    assert r.status_code == 422
    fields = [p["field"] for p in r.json()["detail"]["problems"]]
    assert field in fields, fields


def test_the_form_works_in_cio_mode_and_a_scenario_regime_may_be_derived(config):
    """The form's conversion is a curator route (C-16), allowed in both modes; aggregation:/scenario is
    writable through the proxy in the committed cio config (C-24)."""
    client, _ = client_for(config, mode="cio")
    with client:
        assert client.post("/api/curator/mandate/assemble", json=FORM).status_code == 200
        assert client.get("/api/curator/mandate/vocabulary").json()["bound_source"]["region"] == "policy"
        assert client.post("/api/aggregation/scenario", json={}).status_code in (403, 404), "not in this test config"
    s = load(env={"COCKPIT_MODE": "cio"})
    assert s.writable("aggregation", "scenario") and not s.writable("aggregation", "scenarios/policies")
    assert not s.writable("pcp", "run"), "pcp runs only through the recorded curator route"


def test_every_mandate_preset_is_a_valid_pcp_mandate():
    """dev/presets holds what dev/build_presets.py saved to the content store (C-22)."""
    curves = json.loads((PRESETS / "target-curve-presets.json").read_text(encoding="utf-8"))
    mandates = json.loads((PRESETS / "mandate-presets.json").read_text(encoding="utf-8"))
    by_key = {c["key"]: c for c in curves["presets"]}
    assert curves["unit"] == "percent_per_year" and len(by_key) >= 12
    for c in curves["presets"]:
        assert len(c["points_pct"]) == 25 and c["provenance"]
        assert c["mean_pct"] == pytest.approx(sum(c["points_pct"]) / 25, abs=1e-3), c["key"]
    for k in ("role-gain", "role-income", "role-stabilisation", "role-protection", "balanced-blend"):
        assert by_key[k]["provenance"]["calibration_id"].startswith("CAL-"), f"{k} names its fmre calibration"
    assert min(by_key["capital-preservation"]["points_pct"]) >= 0
    assert len(mandates["presets"]) >= 7
    for p in mandates["presets"]:
        m = PcpMandate.model_validate({**p["mandate"], "client": "any"})
        assert 8 <= len(m.universe) <= 20
        assert not set(m.universe) & {"INS-short-msci-us", "INS-cs-long-vola"}, "deactivated in fmre"
        assert m.currency in ("CHF", "EUR", "USD")
        curve = by_key[p["curve_preset"]]
        assert list(m.target_curve) == pytest.approx([math.log1p(v / 100) for v in curve["points_pct"]], abs=1e-12)
        assert p["validation"]["ok"] is True, (p["key"], p["validation"].get("problems"))


def test_every_mandate_preset_holds_instruments_in_every_role():
    """lbs's derived role bounds replace a preset's role bounds when a client's parameters are applied, so a
    preset with a role left empty is refused by pcp for any household (C-29). At least two active register
    instruments per role, and pcp's /validate answered ok with every role floor at 5, 10 and 15 %."""
    mandates = json.loads((PRESETS / "mandate-presets.json").read_text(encoding="utf-8"))
    assert mandates["min_instruments_per_role"] >= 2
    for p in mandates["presets"]:
        by_role = p["universe_by_role"]
        assert set(by_role) == {"gain", "income", "stabilisation", "protection"}, p["key"]
        assert sorted(i for ids in by_role.values() for i in ids) == sorted(p["mandate"]["universe"]), p["key"]
        thin = {r: len(ids) for r, ids in by_role.items() if len(ids) < 2}
        assert not thin, f"{p['key']} holds fewer than two instruments in {thin}"
        checks = p["validation"]["role_floor_checks"]
        assert [c["role_floor"] for c in checks] == [0.05, 0.10, 0.15], p["key"]
        assert all(c["ok"] is True for c in checks), (p["key"], [c["problems"] for c in checks])


# ---- which Regime a pcp run uses: by optimism level, default unless named (C-30) ----------------

#: aggregation issues one Regime per optimism level in one go. As on the live system, the newest run is
#: the rogue one; the list also holds an older default run ahead of the newer one, so neither the first
#: run nor the first default run in the list is the answer.
AGG_RUNS = [
    {"run_id": "RUN-r", "status": "succeeded", "finished_at": "2026-09-28T05:37:21+00:00", "regime_id": "RGM-rogue", "optimism_scale": "rogue"},
    {"run_id": "RUN-f", "status": "failed", "finished_at": "2026-09-28T05:37:21+00:00", "regime_id": None, "optimism_scale": "default"},
    {"run_id": "RUN-o", "status": "succeeded", "finished_at": "2026-09-20T08:00:00+00:00", "regime_id": "RGM-olddefault", "optimism_scale": "default"},
    {"run_id": "RUN-a", "status": "succeeded", "finished_at": "2026-09-28T05:37:20+00:00", "regime_id": "RGM-aggressive", "optimism_scale": "aggressive"},
    {"run_id": "RUN-d", "status": "succeeded", "finished_at": "2026-09-28T05:37:20+00:00", "regime_id": "RGM-defensive", "optimism_scale": "defensive"},
    {"run_id": "RUN-n", "status": "succeeded", "finished_at": "2026-09-28T05:37:19+00:00", "regime_id": "RGM-default", "optimism_scale": "default"},
]
AGG_LEVEL = {r["regime_id"]: r["optimism_scale"] for r in AGG_RUNS if r["regime_id"]}


def aggregation_answer(request: httpx.Request, body: dict) -> httpx.Response:
    """aggregation on 8004: its runs, each Regime's own optimism_scale, its calibration, and
    POST /scenario deriving a scenario Regime (which keeps its base's level)."""
    path = request.url.path
    if path == "/runs":
        return httpx.Response(200, json=AGG_RUNS)
    if path == "/calibration":
        return httpx.Response(200, json={"optimism": {"targets": {"defensive": 10.0, "default": 14.0, "aggressive": 19.0, "rogue": 24.0}}})
    if path.startswith("/regime/") and path.endswith("/current"):
        rid = path.split("/")[2]
        if rid in AGG_LEVEL:
            return httpx.Response(200, json={"regime_id": rid, "optimism_scale": AGG_LEVEL[rid], "markets": [], "economies": []})
        if rid.startswith("RGM-scn-"):
            base = "RGM-" + rid.split("-", 3)[3]
            return httpx.Response(200, json={"regime_id": rid, "optimism_scale": AGG_LEVEL[base],
                                             "scenario": {"policy": rid.split("-")[2], "base_regime_id": base}})
        return httpx.Response(404, json={"detail": f"no regime {rid}"})
    if path == "/scenario" and request.method == "POST":
        rid = f"RGM-scn-{body['policy']}-{body['base_regime_id'][4:]}"
        return httpx.Response(200, json={"regime_id": rid, "cached": False, "policy": body["policy"],
                                         "base_regime_id": body["base_regime_id"]})
    return httpx.Response(404, json={"detail": "no such path"})


def test_the_regime_is_the_default_optimism_level_even_when_another_level_is_newer(tmp_path):
    """The Parameters page's Regime (GET /api/curator/regime): the latest succeeded Regime of the chosen
    optimism level, default unless another is named, never aggregation's newest run (the rogue one)."""
    class Agg(httpx.AsyncBaseTransport):
        def __init__(self):
            self.calls: list[tuple[str, str, dict]] = []

        async def handle_async_request(self, request):
            body = json.loads(await request.aread() or b"{}")
            self.calls.append((request.method, request.url.path, body))
            if request.url.port == 8004:
                return aggregation_answer(request, body)
            raise httpx.ConnectError("refused", request=request)

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""
data_dir: {tmp_path.as_posix()}/data
engines:
  - {{key: aggregation, number: 4, name: Aggregation, url: "http://127.0.0.1:8004", status: built}}
""", encoding="utf-8")
    fake = Agg()
    for mode in ("development", "cio"):
        with TestClient(create_app(load(cfg, env={"COCKPIT_MODE": mode}), transport=fake)) as client:
            r = client.get("/api/curator/regime")
            assert r.status_code == 200, r.text
            got = r.json()
            assert got["optimism"] == "default" and got["regime_id"] == "RGM-default", \
                "the default level's latest Regime, not the newest run (rogue) nor the first default in the list"
            assert got["policy"] is None and got["run_id"] == "RUN-n"
            assert [lv["key"] for lv in got["levels"]] == ["defensive", "default", "aggressive", "rogue"]
            assert [lv["key"] for lv in got["levels"] if lv["default"]] == ["default"]
            for level in ("defensive", "aggressive", "rogue"):
                assert client.get("/api/curator/regime", params={"optimism": level}).json()["regime_id"] == f"RGM-{level}"
            # a scenario is derived from the chosen level's Regime
            s = client.get("/api/curator/regime", params={"policy": "stagflation"}).json()
            assert s["regime_id"] == "RGM-scn-stagflation-default" and s["base_regime_id"] == "RGM-default"
            assert s["optimism"] == "default" and s["policy"] == "stagflation"
            assert [c for c in fake.calls if c[1] == "/scenario"][-1] == ("POST", "/scenario", {"base_regime_id": "RGM-default", "policy": "stagflation"})
            s = client.get("/api/curator/regime", params={"optimism": "defensive", "policy": "depression"}).json()
            assert s["base_regime_id"] == "RGM-defensive" and s["optimism"] == "defensive"
            assert client.get("/api/curator/regime", params={"optimism": "reckless"}).status_code == 422
