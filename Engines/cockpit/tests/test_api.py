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

#: Benches the roster declares before their engine ships the file (C-34): the page shows the placeholder
#: until it exists. Every other declared bench must be there.
ANNOUNCED_BENCHES = {"lbsim"}


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
        assert e.bench is None or e.bench.is_file() or e.key in ANNOUNCED_BENCHES, f"{e.key}: bench {e.bench} is missing"
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
    basis: Literal["nominal", "real"] = "nominal"   # PCP-22: the basis of the target curve, optional
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


# ---- nominal and real (C-31) -----------------------------------------------------------------------

STATIC_PAGE = Path(__file__).resolve().parents[1] / "src" / "cockpit" / "static" / "index.html"


def _page_blocks() -> dict[str, str]:
    """Each page's render code in index.html, keyed by page id (from its page(...) call to the next)."""
    html = STATIC_PAGE.read_text(encoding="utf-8")
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'^page\("([^"]+)"', html, re.M)]
    ends = [s for s, _ in starts[1:]] + [len(html)]
    return {pid: html[s:e] for (s, pid), e in zip(starts, ends)}


def test_the_basis_is_nominal_by_default_and_real_passes_through_to_the_mandate(dev):
    """The switch sets the Mandate's basis (C-31). Nominal is the default and is left out of the Mandate,
    as pcp leaves it out (a nominal mandate keeps its bytes and its idempotency key); real is written as
    real and read back. The curve's numbers are the same on both bases: the cockpit converts nothing."""
    client, fake = dev
    nominal = client.post("/api/curator/mandate/assemble", json=FORM).json()["mandate"]
    assert "basis" not in nominal, "a nominal mandate is what it was before the real view"
    assert client.post("/api/curator/mandate/form", json={"mandate": nominal}).json()["basis"] == "nominal"
    assert client.post("/api/curator/mandate/assemble", json={**FORM, "basis": "nominal"}).json()["mandate"] == nominal
    real = client.post("/api/curator/mandate/assemble", json={**FORM, "basis": "real"}).json()["mandate"]
    assert real["basis"] == "real"
    assert real["target_curve"] == nominal["target_curve"], "real reads the same curve as real: no conversion"
    assert {k: v for k, v in real.items() if k != "basis"} == nominal
    PcpMandate.model_validate(real)
    assert client.post("/api/curator/mandate/form", json={"mandate": real}).json()["basis"] == "real"
    assert client.post("/api/curator/mandate/assemble", json={**FORM, "basis": "inflation"}).status_code == 422
    voc = client.get("/api/curator/mandate/vocabulary").json()
    assert voc["bases"] == ["nominal", "real"] and voc["default_basis"] == "nominal"
    assert not fake.calls


def test_the_switch_is_on_the_parameters_page_and_the_instrument_views_only():
    """The Parameters page, Instrument selection and the Client page's outlook (lbsim's own real view, C-34)
    carry the nominal / real switch; every other page, the
    macro views (macrofield, cycle, aggregation: Regime and signals, the Models pages) above all, has none
    and stays nominal (owner, 29.09.2026)."""
    blocks = _page_blocks()
    with_switch = {pid for pid, code in blocks.items() if re.search(r'basisSwitch\("', code)}
    assert with_switch == {"curator/parameters", "cio/instruments", "curator/client"}, with_switch
    for macro in ("cio/regime", "cio/country", "cio/bounds", "cio/overview", "cio/optimiser"):
        assert "basis=real" not in blocks[macro] and 'basis: "real"' not in blocks[macro], macro
    html = STATIC_PAGE.read_text(encoding="utf-8")
    render_model = html[html.index("async function renderModel("):html.index("function benchPages(")]
    assert "basisSwitch(" not in render_model and "basis" not in render_model, "the Models pages stay nominal"


def test_the_switch_defaults_to_nominal_and_names_the_basis_to_fmre():
    """Default nominal on both pages. The Parameters page asks fmre for the ReturnSet with basis= when real
    (and without it when nominal, as pcp does), and sends the basis to the run route; the instrument view
    asks fmre for the real ReturnSet and the per-state inflation of its currency."""
    html = STATIC_PAGE.read_text(encoding="utf-8")
    assert 'const DEFAULT_BASIS = "nominal";' in html
    blocks = _page_blocks()
    params, instruments = blocks["curator/parameters"], blocks["cio/instruments"]
    assert "basis: DEFAULT_BASIS" in params, "the form starts nominal"
    assert '...(basis === "real" ? { basis } : {})' in params, "basis= to fmre when real"
    assert "basis: (P.rs && P.rs.id === b.return_set_id ? P.rs.basis : F.basis)" in params, "the run is told the basis"
    assert 'basis: F.basis || DEFAULT_BASIS' in params, "the form sends its basis to /mandate/assemble"
    assert 'S.params.get("basis") === "real" ? "real" : DEFAULT_BASIS' in instruments, "nominal unless ?basis=real"
    assert 'basis: "real", currency: ccy' in instruments and "/fmre/v1/inflation?" in instruments


# ---- the CIO's inflation pass-through override (C-32) ------------------------------------------------

class StandInFmreBeta(httpx.AsyncBaseTransport):
    """fmre on 8006 as its api/main.py serves the inflation pass-through (FMRE-33..37): GET /v1/inflation-beta
    answers {calibration, bounds, instruments}, each instrument with its house type, house beta and duration,
    the latest override version (or null; a revert is a version with a null beta), and the beta and duration in
    force with their source; PUT /v1/inflation-beta/{id} appends the next version and answers {written, ...row}.
    No history endpoint (fmre serves the version in force only). Every other port refuses."""

    HOUSE = {"INS-a": ("Alpha", "equities", "equities", 0.6, None),
             "INS-b": ("Bravo", "nominal_bonds_aggregate", "nominal bonds, aggregate", 0.0, 6.0)}

    def __init__(self, up: bool = True):
        self.up = up
        self.calls: list[tuple[str, str, dict]] = []
        self.versions: dict[str, list[dict]] = {k: [] for k in self.HOUSE}

    def entry(self, iid: str) -> dict:
        name, typ, typ_label, house, house_duration = self.HOUSE[iid]
        override = self.versions[iid][-1] if self.versions[iid] else None
        beta, source = (override["beta"], "override") if override and override["beta"] is not None else (house, "house")
        duration, dsource = ((override["duration"], "override") if override and override["duration"] is not None
                             else (house_duration, "house" if house_duration is not None else None))
        return {"instrument_id": iid, "name": name, "asset_class": "Equity", "role": "gain", "proxy_symbol": None,
                "type": typ, "type_label": typ_label, "rule": "r", "house_beta": house, "house_duration": house_duration,
                "override": override, "beta": beta, "source": source, "duration": duration, "duration_source": dsource}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(await request.aread() or b"{}")
        if request.url.port != 8006 or not self.up:
            raise httpx.ConnectError("refused", request=request)
        self.calls.append((request.method, request.url.path, body))
        parts = request.url.path.strip("/").split("/")
        if parts[:2] != ["v1", "inflation-beta"]:
            return httpx.Response(404, json={"detail": "Not Found"})
        if len(parts) == 2 and request.method == "GET":
            return httpx.Response(200, json={"calibration": {"version": "ipt@1.1.0"},
                                             "bounds": {"beta": [0.0, 1.5], "duration": [0.0, 30.0]},
                                             "instruments": [self.entry(k) for k in self.HOUSE]})
        iid = parts[2] if len(parts) > 2 else ""
        if len(parts) == 3 and request.method == "PUT":
            if iid not in self.HOUSE:
                return httpx.Response(404, json={"detail": f"no instrument {iid!r}"})
            beta, duration = body.get("beta"), body.get("duration")
            if (not str(body.get("reason") or "").strip() or (beta is not None and not 0 <= beta <= 1.5)
                    or (duration is not None and not 0 <= duration <= 30)):
                return httpx.Response(422, json={"detail": "fmre refuses"})
            row = {"instrument_id": iid, "version": len(self.versions[iid]) + 1, "beta": beta, "duration": duration,
                   "reason": body["reason"], "set_by": body.get("set_by"),
                   "set_at": f"2026-09-29T12:0{len(self.versions[iid])}:00Z", "calibration_version": "ipt@1.1.0"}
            self.versions[iid].append(row)
            return httpx.Response(200, json={"written": row, **self.entry(iid)})
        return httpx.Response(404 if request.method == "GET" else 405, json={"detail": "Not Found"})


class Curators:
    """The curator store's in-service check, without a database: cur-1 is in service, cur-x revoked."""

    def in_service(self, curator_id: str) -> None:
        from cockpit.curator import Refused
        if curator_id == "cur-x":
            raise Refused(403, f"curator {curator_id} is revoked and cannot act (A161)")
        if curator_id != "cur-1":
            raise Refused(422, f"no curator {curator_id}")


def beta_client(config: Path, mode: str, up: bool = True) -> tuple[TestClient, StandInFmreBeta]:
    fake = StandInFmreBeta(up)
    settings = load(config, env={"COCKPIT_MODE": mode})
    return TestClient(create_app(settings, transport=fake, curator=Curators())), fake


@pytest.mark.parametrize("mode", ["development", "cio"])
def test_the_cio_lists_sets_and_reverts_an_inflation_beta_with_a_reason(config, mode):
    """The list comes through the proxy unchanged; a set and a revert go through PUT /api/cio/inflation-beta/{id},
    forwarded to fmre in fmre's own names, with the acting curator as set_by, in both modes (C-32)."""
    client, fake = beta_client(config, mode)
    with client:
        listed = client.get("/api/fmre/v1/inflation-beta").json()
        assert listed["bounds"] == {"beta": [0.0, 1.5], "duration": [0.0, 30.0]}
        assert [(r["instrument_id"], r["house_beta"], r["override"], r["beta"], r["source"]) for r in listed["instruments"]] == \
            [("INS-a", 0.6, None, 0.6, "house"), ("INS-b", 0.0, None, 0.0, "house")]
        r = client.put("/api/cio/inflation-beta/INS-a",
                       json={"beta": 0.8, "duration": 2, "reason": "Pricing power", "set_by": "cur-1"})
        assert r.status_code == 200, r.text
        assert fake.calls[-1] == ("PUT", "/v1/inflation-beta/INS-a",
                                  {"beta": 0.8, "reason": "Pricing power", "set_by": "cur-1", "duration": 2.0})
        got = r.json()
        assert got["written"]["version"] == 1 and got["beta"] == 0.8 and got["source"] == "override"
        assert got["override"]["set_by"] == "cur-1" and got["duration"] == 2.0
        # without a duration none is sent: fmre keeps the house duration
        r = client.put("/api/cio/inflation-beta/INS-b", json={"beta": 1.2, "reason": "Linker", "set_by": "cur-1"})
        assert "duration" not in fake.calls[-1][2] and r.json()["duration"] == 6.0
        # revert: beta null, with its reason; fmre appends it as the next version
        r = client.put("/api/cio/inflation-beta/INS-a",
                       json={"beta": None, "reason": "Back to the house view", "set_by": "cur-1"})
        assert r.status_code == 200 and r.json()["beta"] == 0.6 and r.json()["source"] == "house"
        assert r.json()["override"]["version"] == 2 and r.json()["override"]["beta"] is None
        assert fake.calls[-1][2] == {"beta": None, "reason": "Back to the house view", "set_by": "cur-1"}
        assert [v["beta"] for v in fake.versions["INS-a"]] == [0.8, None], "append-only: the set, then the revert"
        # fmre's own refusal (an unknown instrument) comes back as fmre answered it
        r = client.put("/api/cio/inflation-beta/INS-zz", json={"beta": 0.5, "reason": "x", "set_by": "cur-1"})
        assert r.status_code == 404 and "INS-zz" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"beta": 0.8, "set_by": "cur-1"},                               # no reason
    {"beta": 0.8, "reason": "   ", "set_by": "cur-1"},              # a blank reason
    {"beta": None, "set_by": "cur-1"},                              # a revert needs its reason too
    {"beta": 1.6, "reason": "too much", "set_by": "cur-1"},         # outside 0 to 1.5
    {"beta": -0.1, "reason": "negative", "set_by": "cur-1"},
    {"beta": 0.5, "duration": 31, "reason": "too long", "set_by": "cur-1"},   # a duration is 0 to 30 years
    {"reason": "no beta named", "set_by": "cur-1"},                 # beta is required (null reverts)
    {"beta": 0.8, "reason": "nobody"},                              # no acting curator
    {"beta": 0.8, "reason": "r", "set_by": "cur-1", "note": "x"},   # nothing fmre does not take
])
def test_an_override_without_its_reason_or_out_of_range_never_reaches_fmre(config, body):
    client, fake = beta_client(config, "cio")
    with client:
        assert client.put("/api/cio/inflation-beta/INS-a", json=body).status_code == 422
        assert not fake.calls


def test_the_proxy_stays_closed_to_the_override_in_cio_mode_and_a_revoked_curator_is_refused(config):
    """cio.writable holds exact engine:path pairs only, so fmre's PUT is not added to it: in cio mode a PUT
    through the proxy is refused and never reaches fmre; the cockpit route is the one way (C-32). A revoked
    curator is refused before fmre is asked."""
    body = {"beta": 0.8, "reason": "r", "set_by": "cur-1"}
    client, fake = beta_client(config, "cio")
    with client:
        assert client.put("/api/fmre/v1/inflation-beta/INS-a", json=body).status_code == 403 and not fake.calls
        assert not any("inflation-beta" in w for w in client.get("/api/config").json()["cio"]["writable"])
        r = client.put("/api/cio/inflation-beta/INS-a", json={**body, "set_by": "cur-x"})
        assert r.status_code == 403 and "revoked" in r.json()["detail"] and not fake.calls
    client, fake = beta_client(config, "development")
    with client:   # development mode: the proxy lets it through, as every write
        assert client.put("/api/fmre/v1/inflation-beta/INS-a", json=body).status_code == 200
    client, fake = beta_client(config, "cio", up=False)
    with client:
        r = client.put("/api/cio/inflation-beta/INS-a", json=body)
        assert r.status_code == 502 and "no override was set" in r.json()["detail"]
    p = config.with_name("reserved.yaml")
    p.write_text('engines:\n  - {key: cio, number: 1, name: x, url: "http://h:8001", status: built}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="collides"):
        load(p, env={})


def test_the_instrument_page_carries_the_pass_through_panel_and_shows_the_beta_a_scenario_used():
    """Instrument selection lists fmre's inflation betas and writes through the cockpit route with the acting
    curator as set_by; where scenario profiles are shown (Instrument selection, Parameters) the page shows
    provenance.inflation_pass_through."""
    html = STATIC_PAGE.read_text(encoding="utf-8")
    blocks = _page_blocks()
    instruments, params = blocks["cio/instruments"], blocks["curator/parameters"]
    assert "Inflation pass-through (scenarios)" in instruments and "inflationBetaPanel(" in instruments
    assert 'api("/fmre/v1/inflation-beta")' in html
    assert 'api(`/cio/inflation-beta/${encodeURIComponent(id)}`, { method: "PUT"' in html
    assert "set_by: actingCurator()" in html and "act({ beta: null })" in html
    assert "passThroughView(view.rs" in instruments and "passThroughView(rs)" in params
    assert "inflation_pass_through" in html
    assert [pid for pid, code in blocks.items() if "inflationBetaPanel(" in code] == ["cio/instruments"]


# ---- lbsim: the roster entry, the outlook panel and the Parameters call (C-34, C-35) ----------------

LBSIM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lbsim"


def lbsim_outlook(plan_state: str = "ready") -> dict:
    """lbsim's GET /outlook built from B1's frozen samples (one sheet: findings, paths and the plan)."""
    rd = lambda n: json.loads((LBSIM_FIXTURES / f"{n}.sample.json").read_text(encoding="utf-8"))  # noqa: E731
    findings, paths, plan = rd("findings"), rd("paths"), rd("plan")
    state = {"ready": {"state": "ready", "artefact": plan},
             "calculating": {"state": "calculating", "elapsed_s": 754.0, "budget_s": 7200.0}}[plan_state]
    return {"client_ref": findings["client_ref"], "life_balance_sheet_id": findings["life_balance_sheet_id"],
            "findings": findings, "paths": paths, "plan": state}


def test_lbsim_is_in_the_roster_as_built_and_starts_from_its_own_venv():
    """Section 8 of LBSIM_INTERFACES: status built, the three artefacts, what it reads, its bench, the serve
    command in eigentliCH_Engines/.venv, autostart, port 8014 (Engine 14)."""
    from cockpit.settings import ROOT
    s = load()
    e = s.engine("lbsim")
    assert e.status == "built" and e.number == 14 and e.url == "http://127.0.0.1:8014"
    assert e.produces == "LifeBalanceFindings, LifeBalancePaths, LifeBalancePlan"
    assert e.consumes == ("lbs", "pcp", "aggregation", "fmre")
    engines = (ROOT.parent / "eigentliCH_Engines").resolve()
    assert e.bench == engines / "engines" / "lbsim" / "testbench" / "index.html", "the convention lbs follows"
    assert e.start_cwd == engines / "engines" / "lbsim"
    assert e.start_args == ("-X", "utf8", "-m", "lbsim", "serve")
    assert e.python == engines / ".venv" / "Scripts" / "python.exe" and e.autostart
    assert e.public()["bench"] == e.bench.is_file(), "a bench not delivered yet is reported as none (placeholder)"
    order = [x.key for x in s.engines]
    assert all(order.index(u) < order.index("lbsim") for u in e.consumes), "autostart in roster order: upstream first"


class StandInLbsim(httpx.AsyncBaseTransport):
    """lbsim on 8014 answering GET /outlook with the sample outlook for its sheet, 404 for another."""

    def __init__(self):
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if request.url.port == 8014 and request.url.path == "/outlook":
            o = lbsim_outlook()
            if request.url.params.get("life_balance_sheet_id") not in (None, o["life_balance_sheet_id"]):
                return httpx.Response(404, json={"detail": "lbsim holds no outlook for this Life Balance Sheet."})
            return httpx.Response(200, json=o)
        raise httpx.ConnectError("refused", request=request)


def test_the_outlook_is_read_through_the_proxy_unchanged(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""data_dir: {tmp_path.as_posix()}/data
engines:
  - {{key: lbsim, number: 14, name: lbsim, url: "http://127.0.0.1:8014", status: built}}
""", encoding="utf-8")
    fake = StandInLbsim()
    for mode in ("development", "cio"):
        with TestClient(create_app(load(cfg, env={"COCKPIT_MODE": mode}), transport=fake)) as client:
            r = client.get("/api/lbsim/outlook", params={"client_ref": "lbsim-sample", "life_balance_sheet_id": "LBS-1a68c6aa5d613766"})
            assert r.status_code == 200 and r.json() == lbsim_outlook(), mode
            assert fake.calls[-1] == ("http://127.0.0.1:8014/outlook?client_ref=lbsim-sample"
                                      "&life_balance_sheet_id=LBS-1a68c6aa5d613766")
            other = client.get("/api/lbsim/outlook", params={"client_ref": "c", "life_balance_sheet_id": "LBS-0000000000000000"})
            assert other.status_code == 404 and "no outlook" in other.json()["detail"]


def test_the_samples_carry_what_the_panel_draws():
    """The panel reads these fields; the fixtures are B1's frozen samples, so a changed shape shows here."""
    o = lbsim_outlook()
    f, p, plan = o["findings"], o["paths"], o["plan"]["artefact"]
    assert {e["level_basis"] for e in f["earning_power"]} == {"stated", "modelled"}
    assert all(x["saving_need"] and x["views"]["real"]["saving_need"] for x in f["income_paths"])
    for x in f["findings"]:
        placeholders = set(re.findall(r"\{(\w+)\}", " ".join(x["text"]["en"].values())))
        assert placeholders <= set(x["figures"]), "every placeholder has its figure"
    base = p["regimes"][0]
    assert base["key"] == "base" and len(base["bands"]["net_worth"]["real"]["p50"]) == p["horizon_years"] + 1
    for g in base["goals"]:
        assert g["measure"] in base["bands"] and g["chance_basis"] in ("nominal", "real")
    av = p["allocation_view"]
    assert len(av["curves"]["nominal"]["target"]) == len(av["curves"]["real"]["achieved"]) == 25
    assert set(av["by_role"]) == {"Gain", "Income", "Stabilisation", "Protection"}
    assert set(plan["action_now"]) >= {"work_share", "saving_chf_per_year"} and plan["framing"]["en"]


def test_the_client_page_carries_the_outlook_panel():
    """The Client page's Outlook panel: read through the proxy for the newest sheet, the same content as the
    app (earning power, income paths with the zero-return saving need, findings filled from their figures,
    the schedule, charts 1 to 3 through plot() with the nominal / real switch, the Regime selector with the
    chances), the plan block under the framing heading, the solver details, and the restart through the app."""
    html = STATIC_PAGE.read_text(encoding="utf-8")
    client = _page_blocks()["curator/client"]
    assert "outlookPanel(oc, id, d" in client
    assert ("api(`/lbsim/outlook?${new URLSearchParams({ client_ref: clientId, life_balance_sheet_id: "
            "sheetRun.artefact_id })}`)") in client
    assert 'd.engine_runs.find(r => r.engine === "lbs" && r.status === "succeeded" && r.artefact_id)' in client, "the newest sheet"
    # the restart goes through the app (C-20 pattern), never to lbsim directly
    assert 'cpost(`/clients/${encodeURIComponent(clientId)}/outlook`, { optimise: "now" })' in client
    assert "/lbsim/run" not in html and "/lbsim/optimise" not in html, "lbsim requests are built only in the app"
    # the words: German and English side by side, the page reads one language (English, as the page is)
    assert 'const OUTLOOK_LANG = "en";' in html and '<html lang="en-GB">' in html
    for de, en in (("Aussichten", "Outlook"), ("Was die Rechnung annimmt", "What the calculation assumes"),
                   ("Planrechnung neu starten", "Restart the plan calculation"), ("Ihre Angabe", "Stated by the client"),
                   ("Modellwert", "Model value"), ("umgerechnet", "converted"), ("Krise", "Crisis")):
        assert f'"{de}"' in client and f'"{en}"' in client, de
    assert "Die Planrechnung läuft noch (seit ${n} Minuten, höchstens ${h} Stunden)." in client
    for role in ("Wertsteigerung", "Einkommen", "Stabilisierung", "Absicherung"):
        assert role in client
    # the content
    assert "e.modelled.full_time_chf_per_year" in client and "e.stated.expected_full_pensum_income_chf_per_year" in client
    assert "x.views && x.views.real && x.views.real.saving_need" in client and "zero_return_saving_chf_per_year" in client
    assert "fillTemplate(t.action, x.figures)" in client and "f.schedule" in client
    assert 'case "chf": case "chf_per_year"' in client, "figures formatted by unit"
    assert 'basisSwitch("oBasis", view.basis)' in client and 'wireBasis("oBasis"' in client
    assert "lw(r.label)" in client and "pct(g.chance, 0)" in client, "Regimes by their labels, chances as numbers"
    assert "weightsChart(w1, av.instruments, av.by_role)" in client
    assert "stateCurveChart(chartIn(w2, 280), curves.target, curves.achieved, view.basis)" in client
    assert "(av.curves || {})[view.basis]" in client
    assert "fanChart(chartIn(fanHost, 340), p, reg, view.series, view.basis, goals)" in client
    assert "((regime.bands || {})[series] || {})[basis]" in client
    assert 'dash: other ? "dash" : "solid"' in client and 'g.chance_basis || "nominal"' in client
    assert "plot(el, traces" in client and "Plotly.react" not in client, "charts through the page's plot() helper"
    # the plan block: every state, and the framing
    for state in ('plan.state === "calculating"', 'plan.state !== "ready"', "lw(plan.reason)", "lw(a.framing)", 'ow("assumes")'):
        assert state in client, state
    for part in ("s.return_status", "ch.in_sample", "ch.out_of_sample", "hz.solved_years", "ex.winner", "s.casadi_version"):
        assert part in client, part


def test_the_parameters_page_asks_for_the_outlook_after_a_base_regime_run_only():
    """After a succeeded pcp run on a base Regime (the run's context names no scenario policy) the page asks the
    app for the outlook through the cockpit route; after a scenario Regime's run, or a run that did not succeed,
    it asks nothing. The Allocation shows chart 1 (weights) and chart 2 (target and reached per state)."""
    params = _page_blocks()["curator/parameters"]
    call = 'if (run.status === "succeeded" && !(run.context && run.context.regime_policy)) outlookAfterPcp(id);'
    run_handler = params[params.index('$("pRun").onclick'):params.index("// ---- history and the allocation")]
    assert call in run_handler and params.count("outlookAfterPcp(id)") == 1, "the only call, inside the run handler"
    assert "cpost(`/clients/${encodeURIComponent(cid)}/outlook`)" in params, "no optimise: the app decides as after a new sheet"
    assert 'weightsChart($("allocWeights"), a.instruments, a.weights_by_role)' in params
    assert 'stateCurveChart($("allocCurve"), a.curves.target, a.curves.achieved, abasis)' in params
    html = STATIC_PAGE.read_text(encoding="utf-8")
    chart2 = html[html.index("function stateCurveChart("):html.index("function fanChart(")]
    assert 'tickvals: [1, 25], ticktext: [ow("crisis"), ow("boom")]' in chart2 and "zeroline: true" in chart2


def test_an_lbsim_run_status_names_its_artefact_by_kind():
    """lbsim's RunStatus lists artefact_ids; the engine_run keeps the plan, else the paths, else the findings."""
    from cockpit.api import _main_artefact
    assert _main_artefact(["LSF-1", "LSP-2"]) == "LSP-2"
    assert _main_artefact(["LSO-3"]) == "LSO-3" and _main_artefact(["LSF-1"]) == "LSF-1"
    assert _main_artefact(["ALC-9"]) == "ALC-9" and _main_artefact([]) is None and _main_artefact(None) is None



# ---- the life balance sheet and the four capitals (C-36, VISUALS_INTERFACES.md) -----------------------------

CAPITALS_SAMPLE = json.loads((LBSIM_FIXTURES / "capitals.sample.json").read_text(encoding="utf-8"))


def test_the_client_page_carries_the_balance_panel_and_the_capitals_over_time():
    """The balance panel reads the newest sheet through the proxy and has its own nominal / real switch; the
    outlook panel draws lbsim's capitals after the fan; every chart goes through plot(); the words are in OW in
    both languages and the page reads English (C-35)."""
    client = _page_blocks()["curator/client"]
    assert "balancePanel(bc, d)" in client
    assert "api(`/lbs/artefacts/${encodeURIComponent(sheetRun.artefact_id)}`)" in client, "through the proxy"
    assert 'basisSwitch("bBasis", view.basis)' in client and 'wireBasis("bBasis"' in client
    assert "balanceSheetChart(chartIn(sec, 320), sheet, view.basis, goalName)" in client
    assert "(g[basis] || {}).amount" in client, "the goals' claims follow the switch"
    assert "capitalsTodayChart(chartIn(cap, 90 + 60 * adults.length), adults)" in client
    draw = client[client.index("function drawOutlook("):client.index("async function outlookPanel(")]
    assert draw.index("fanChart(chartIn(fanHost, 340)") < draw.index("capitalsOverTime(capHost, p, reg, view.withheld || new Set())")
    assert "view.withheld = withheldIn(sheetRun && sheetRun.request)" in client
    region = client[client.index("// ---- the life balance sheet and the four capitals (C-36"):client.index("// ---- Parameters: the pcp mandate")]
    assert "Plotly" not in region and region.count("plot(el, ") == 3
    assert "idChip(" not in region, "no raw ids in the new panel"
    assert "—" not in region, "no em-dash"
    for de, en in (("Lebensbilanz", "Life balance sheet"), ("Schulden und Nettovermögen", "Debts and net worth"),
                   ("Die vier Kapitale heute", "The four capitals today"),
                   ("Wissen, Netzwerk und Gesundheit über die Zeit", "Expertise, network and health over time"),
                   ("Gesundheit zurückgehalten (K3): nicht gezeigt.", "Health withheld (K3): not shown.")):
        assert f'"{de}"' in client and f'"{en}"' in client, de


def test_the_capitals_sample_has_the_shape_the_spec_fixes():
    """The fixture is made from VISUALS_INTERFACES.md before lbsim ships the field: the principal, three capitals
    with five quantiles each over horizon + 1 year ends, their scales and their labels in both languages."""
    caps, paths = CAPITALS_SAMPLE, lbsim_outlook()["paths"]
    assert caps["person_id"] == "p1"
    for k in ("expertise", "network", "health"):
        assert set(caps[k]) == {"p10", "p25", "p50", "p75", "p90"}
        assert {len(v) for v in caps[k].values()} == {paths["horizon_years"] + 1}
        lo, hi = caps["scale"][k]["min"], caps["scale"][k]["max"]
        assert all(lo <= x <= hi for v in caps[k].values() for x in v), "every band within its scale"
        assert caps["labels"][k]["de"] and caps["labels"][k]["en"]


NODE = __import__("shutil").which("node")


def _charts_in_node(script: str) -> dict:
    """Run the page's own chart functions in Node with plot() recording its traces and layout (no Plotly, no DOM)."""
    import subprocess
    html = STATIC_PAGE.read_text(encoding="utf-8")
    words = html[html.index("const OUTLOOK_LANG = "):html.index("function planBlock(")]
    charts = html[html.index("const LBS_WITHHELD = "):html.index("async function balancePanel(")]
    js = (f"{html[html.index('const esc = '):html.index('const pct = ')]}\n"
          "const css = (v) => ({ '--s1': '#2a78d6', '--s2': '#eb6834', '--s3': '#1baf7a', '--s4': '#eda100', '--s5': '#e87ba4', "
          "'--rest': '#c3c2b7', '--serious': '#ec835a', '--ink-2': '#52514e' })[v] || '#000000';\n"
          "const label = (s) => String(s); const pct = (v) => String(v); const table = () => '';\n"
          "const calls = []; const plot = (el, traces, lay) => calls.push({ el, traces, lay });\n"
          f"{words}\n{charts}\n{script}\nconsole.log(JSON.stringify(out));")
    run = subprocess.run([NODE, "--input-type=module", "-"], input=js, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


SHEET = {"totals": {"financial_assets": 579000, "human_assets": 150000, "liabilities": 14000, "net_worth": 715000,
                    "by_vessel": {"free": 65000, "pillar_2": 478000, "pillar_3a": 36000, "real_asset": None, "not_stated": None}},
         "real_view": {"goals": [{"goal_id": "g1", "kind": "property", "unit": "chf", "nominal": {"amount": 375000}, "real": {"amount": 250000}},
                                 {"goal_id": "g2", "kind": "retirement", "unit": "chf_per_year", "nominal": {"amount": 90000}, "real": {"amount": 60000}}]},
         "human_capital": [{"person_id": "p1", "E": {"value": 0.62}, "N": {"value": 0.31}, "H": {"value": 0.85}},
                           {"person_id": "p2", "E": {"value": None}, "N": {"value": 0.53},
                            "H": {"value": None, "absent_because": "K3 data was filtered or erased"}}]}


@pytest.mark.skipif(NODE is None, reason="Node is not installed: the panel is checked by its source above")
def test_the_charts_stack_lbs_s_figures_and_keep_the_capitals_off_the_money_axis():
    script = f"""
const sheet = {json.dumps(SHEET)}, caps = {json.dumps(CAPITALS_SAMPLE)};
const goalName = (g) => g.goal_id === 'g1' ? 'Eigenheim' : 'Ruhestand';
balanceSheetChart('a', sheet, 'nominal', goalName);
balanceSheetChart('b', sheet, 'real', goalName);
capitalsTodayChart('c', [{{ name: 'Principal', held: false, values: {{ expertise: 0.62, network: 0.31, health: 0.85 }} }},
                        {{ name: 'Partner', held: true, values: {{ expertise: null, network: 0.53, health: null }} }}]);
capitalPathChart('d', {{ start_year: 2026 }}, caps, 'network');
capitalPathChart('e', {{ start_year: 2026 }}, {{ ...caps, scale: {{ ...caps.scale, network: {{ min: 0, max: 1.21 }} }} }}, 'network');
const out = {{ calls, held: [...withheldIn({{ household: {{ persons: [{{ person_id: 'p1', human_capital: {{ health_withheld: true }} }},
  {{ person_id: 'p2', human_capital: {{}} }}] }} }})], none: [...withheldIn(null)],
  words: [levelWord(0.1, 0, 1), levelWord(0.5, 0, 1), levelWord(1, 0, 1)] }};
"""
    out = _charts_in_node(script)
    nominal, real, today, path, raised = out["calls"]
    # the network has no fixed ceiling (lbsim P-26): each Regime's scale is read as given, never assumed to be 1
    assert raised["lay"]["yaxis"]["range"] == [0, 1.21] and raised["lay"]["yaxis"]["ticktext"][2] == "top of scale 1.21"
    stacks = {(t["x"][0], t["name"]): t["y"][0] for t in nominal["traces"]}
    assert stacks == {("Assets", "Free"): 65000, ("Assets", "Pillar 2"): 478000, ("Assets", "Pillar 3a"): 36000,
                      ("Assets", "Human capital"): 150000, ("Debts and net worth", "Debts"): 14000,
                      ("Debts and net worth", "Net worth"): 715000, ("The goals' claims", "Eigenheim"): 375000}
    assert nominal["lay"]["barmode"] == "stack" and nominal["lay"]["yaxis"]["tickprefix"] == "CHF "
    assert {(t["x"][0], t["name"]): t["y"][0] for t in real["traces"]}[("The goals' claims", "Eigenheim")] == 250000
    assert "Ruhestand" not in json.dumps(nominal["traces"]), "a need a year is not stacked with the stocks"
    # the capitals: levels on 0 to 1 with words, never francs; a withheld health has no bar
    assert "CHF" not in json.dumps(today) and "CHF" not in json.dumps(path)
    assert today["lay"]["xaxis"]["range"] == [0, 1.2] and today["lay"]["xaxis"]["title"]["text"] == "model level, no currency"
    lea, noa = today["traces"]
    assert lea["x"] == [0.62, 0.31, 0.85] and lea["text"] == ["moderate (0.62)", "low (0.31)", "high (0.85)"]
    assert noa["x"][2] is None and noa["text"][2] == ""
    assert path["lay"]["yaxis"]["range"] == [0, 1] and path["lay"]["yaxis"]["ticktext"] == ["none 0.00", "0.50", "top of scale 1.00"]
    assert [t["name"] for t in path["traces"]] == ["p90", "80 of 100 paths", "p75", "50 of 100 paths", "middle"]
    assert path["traces"][4]["x"][0] == 2026 and len(path["traces"][4]["y"]) == 28
    assert out["held"] == ["p1"] and out["none"] == [] and out["words"] == ["low", "moderate", "high"]
