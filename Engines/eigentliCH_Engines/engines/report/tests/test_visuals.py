"""The life balance sheet and the four capitals (REP-40 to REP-42, review/VISUALS_INTERFACES.md, 03.10.2026).

* The two sections are on every page with an lbs source; the over-time panels only where lbsim's paths carry
  ``capitals`` (lbsim@1.1.0's samples, golden ``*_capitals``).
* Every printed value in their charts is a fact (the digit rule, held for every golden page by ``test_golden`` and
  ``test_lbsim``); no ``<script>`` and no ``http`` inside an SVG; no 32-hex id on a page made on the consumer app's
  ids.
* A capital is never on a money axis: the capitals' charts print no CHF figure but the household's wealth, and the
  over-time panels none at all; money follows the report's basis, the capitals have none.
* A request without these sources keeps its id, and its page has neither section.
"""

from __future__ import annotations

import json
import re

import pytest

from report import charts
from report.contracts import Fact, FactSource, ReportRequest
from report.service import Service

from . import golden_cases as gc
from .conftest import request_body

HEX = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])")
IDS = {'"g-home"': '"76658f42c1e04b5e9a3d2b1c0f9e8d7a"', '"g-ret"': '"8a1b2c3d4e5f60718293a4b5c6d7e8f9"',
       '"p1"': '"0a4dc62a87194424a579a12bd149d901"', '"p2"': '"1b5ed73b98205535b68a23ce25a0e012"'}
CAPITAL_CASES = ["de_capitals", "en_capitals", "de_capitals_real", "en_capitals_real"]


def _raw(name: str) -> bytes:
    return (gc.INPUTS / name).read_bytes()


def _json(name: str) -> dict:
    return json.loads(_raw(name))


def _chart(page: str, key: str) -> str:
    m = re.search(rf'<figure class="chart" data-chart="{key}">(.*?)</figure>', page, re.S)
    return m.group(1) if m else ""


def _printed(svg: str) -> list[str]:
    return re.findall(r'<tspan data-fact="([^"]+)">', svg)


# -- the frozen pages ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", CAPITAL_CASES)
def test_the_capital_pages_carry_both_graphs_and_the_panels_over_time(name):
    report = gc.frozen(name)["report"]
    page = report["html"]
    keys = [s["key"] for s in report["sections"]]
    assert keys.index("household") + 1 == keys.index("life_sheet") and keys.index("capitals") > keys.index("human_capital")
    assert _chart(page, "life_sheet") and _chart(page, "capitals") and _chart(page, "capitals_time")
    title = "Ihre Lebensbilanz" if name.startswith("de") else "Your life balance sheet"
    assert f"{title}</h2>" in page


@pytest.mark.parametrize("name", [c["name"] for c in gc.cases()])
def test_no_capital_is_ever_on_a_money_axis(name):
    report = gc.frozen(name)["report"]
    facts = {f["fact_id"]: f for f in report["facts"]}
    page = report["html"]
    today, over_time, sheet = _chart(page, "capitals"), _chart(page, "capitals_time"), _chart(page, "life_sheet")
    money_today = [i for i in _printed(today) if facts[i]["unit"] in ("chf", "chf_per_year")]
    assert money_today in ([], ["lbs.totals.net_worth"])
    for i in _printed(over_time):
        assert facts[i]["unit"] in ("number", "count") and facts[i]["basis"] is None, i  # levels and the years
    for i in _printed(today):
        if i != "lbs.totals.net_worth":
            assert facts[i]["unit"] in ("number", "text") and facts[i]["basis"] is None, i
    for i in _printed(sheet):
        assert facts[i]["unit"] == "chf", i
    for svg in (today, over_time, sheet):
        assert "<script" not in svg.lower() and "http" not in svg.lower()


@pytest.mark.parametrize("name", ["de_capitals", "de_capitals_real", "en_property", "en_property_real", "de_full"])
def test_the_goal_amounts_follow_the_basis_and_the_holdings_are_today(name):
    report = gc.frozen(name)["report"]
    basis = report["basis"]
    claims = [f for f in report["facts"] if f["fact_id"].startswith("lbs.claim.")]
    assert claims, "every one of these sheets names a goal with one amount"
    for f in claims:
        (src,) = f["sources"]
        if "/real_view/" in src["path"]:
            assert f["basis"] == basis and src["path"].endswith(f"/{basis}/amount")
        else:
            assert f["basis"] == "nominal"
        assert f'data-fact="{f["fact_id"]}"' in _chart(report["html"], "life_sheet")
    for f in report["facts"]:
        if f["fact_id"].startswith(("lbs.sheet.", "lbs.capital.", "lbsim.capitals.")):
            assert f["basis"] is None, f["fact_id"]


def test_the_over_time_panels_need_lbsims_capitals():
    """lbsim artefacts made before the field carry no ``capitals``: no panels, the section stands on lbs alone."""
    for name in ("de_outlook", "en_outlook_real"):
        page = gc.frozen(name)["report"]["html"]
        assert _chart(page, "capitals") and not _chart(page, "capitals_time")
    for name in ("en_property", "de_liquidity"):  # sheets without E, N or H: no capitals section at all
        report = gc.frozen(name)["report"]
        assert "capitals" not in [s["key"] for s in report["sections"]]


def test_the_capitals_over_time_name_the_principal_and_read_the_regimes_own_scale():
    report = gc.frozen("en_capitals")["report"]
    facts = {f["fact_id"]: f for f in report["facts"]}
    paths = _json("lbsim_paths_capitals.json")
    caps = paths["regimes"][0]["capitals"]
    assert facts["lbsim.capitals.person"]["display"] == "Person 1"
    last = paths["horizon_years"]
    for cap in ("expertise", "network", "health"):
        assert facts[f"lbsim.capitals.{cap}.p50.start"]["value"] == caps[cap]["p50"][0]
        assert facts[f"lbsim.capitals.{cap}.p90.end"]["value"] == caps[cap]["p90"][last]
    # The network's ceiling is the Regime's own (lbsim P-26): above 1 here, and a value at it is drawn at the top.
    top_n = caps["scale"]["network"]["max"]
    assert top_n > 1.0
    fact = Fact(fact_id="x", section="capitals", label="x", value=top_n, unit="number", display="x",
                sources=(FactSource(engine="lbsim", artefact_id="LSP-0", contract_version="c", path="/x"),))
    svg = charts.capitals_over_time([("Network", {"p10": [0.0, top_n], "p50": [0.0, top_n], "p90": [0.0, top_n]},
                                      (0.0, top_n), {"p50": fact}, None)], None,
                                     {k: k for k in ("today", "in", "years", "high_end", "low_end", "low", "mid",
                                                     "high")}, "t", "d", "")
    line = re.search(r'<polyline points="([^"]+)"', svg).group(1).split()
    assert line[-1].endswith(",26")  # the plot's top edge: y0 4 plus the 22 of the panel head


def test_a_request_without_these_sources_keeps_its_id_and_has_neither_section(client, upstream):
    """The golden de_full request keeps the id it had since engine 1.2.0, and a page on pcp alone has neither the
    life balance sheet nor the capitals."""
    assert Service.request_id(ReportRequest.model_validate(gc.cases()[0]["request"])) == "RRQ-cf68ec90594ccb16"
    alloc = _json("pcp_allocation.json")
    r = client.post("/report", json=request_body(sources=[{"engine": "pcp", "artefact_id": alloc["artefact_id"]}],
                                                 prose=False))
    assert r.status_code == 200, r.text
    keys = [s["key"] for s in r.json()["sections"]]
    assert "life_sheet" not in keys and "capitals" not in keys
    assert 'data-chart="life_sheet"' not in r.json()["html"]


# -- the consumer app's ids ---------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hex_pages(client, upstream):
    """lbsim@1.1.0's samples with capitals, on the ids the consumer app makes (32 hex)."""
    names = {"lbs_sheet_lbsim.json": "LBS-00000000c0ffee12", "lbsim_findings_capitals.json": "LSF-00000000c0ffee13",
             "lbsim_paths_capitals.json": "LSP-00000000c0ffee14", "lbsim_plan_capitals.json": "LSO-00000000c0ffee15"}
    renames = {_json(n)["artefact_id"]: new for n, new in names.items()}
    alloc = _json("pcp_allocation_lbsim.json")
    upstream.extra["pcp"][f"/allocation/{alloc['artefact_id']}"] = _raw("pcp_allocation_lbsim.json")
    for name, new in names.items():
        raw = _raw(name).decode("utf-8")
        for old, nid in {**IDS, **renames}.items():
            raw = raw.replace(old, nid)
        upstream.extra["lbs" if name.startswith("lbs_") else "lbsim"][f"/artefacts/{new}"] = raw.encode("utf-8")
    sources = [{"engine": "pcp", "artefact_id": alloc["artefact_id"]}] + [
        {"engine": "lbs" if n.startswith("lbs_") else "lbsim", "artefact_id": a} for n, a in names.items()]
    client_ref = _json("lbs_sheet_lbsim.json")["client_ref"]
    out = {}
    for lang in ("de", "en"):
        for basis in ("nominal", "real"):
            r = client.post("/report", json=request_body(client_ref=client_ref, language=lang, prose=False,
                                                         basis=basis, sources=sources if basis == "nominal" else sources[1:]))
            assert r.status_code == 200, r.text
            out[(lang, basis)] = r.json()
    return out


@pytest.mark.parametrize("lang,basis", [("de", "nominal"), ("en", "nominal"), ("de", "real"), ("en", "real")])
def test_no_32_hex_string_anywhere_on_a_page_with_the_new_graphs(hex_pages, lang, basis):
    rep = hex_pages[(lang, basis)]
    page = rep["html"]
    assert HEX.findall(page) == []
    assert _chart(page, "life_sheet") and _chart(page, "capitals") and _chart(page, "capitals_time")
    ids = {f["fact_id"] for f in rep["facts"]}
    assert {"lbs.claim.goal1", "lbs.capital.person1.E", "lbsim.capitals.person"} <= ids
    assert not [i for i in ids if HEX.search(i)]


# -- the test bench's routes (REP-43) ----------------------------------------------------------------------------

def test_the_bench_lists_stored_reports_by_client_with_readable_labels(client, hex_pages):
    got = client.get("/bench/reports").json()
    assert got and all(c["reports"] for c in got)
    mine = next(c for c in got if any(r["artefact_id"] == hex_pages[("de", "real")]["artefact_id"] for r in c["reports"]))
    assert mine["label"].startswith("Couple, one dependant · net worth CHF 257,000 · with the outlook")
    assert {"report · German · real", "report · English · nominal"} <= {r["label"].rsplit(" · ", 1)[0]
                                                                       for r in mine["reports"]}
    for c in got:
        for text in [c["label"]] + [r["label"] for r in c["reports"]]:
            assert not HEX.search(text) and "REP-" not in text and "Muster" not in text, text
    assert len({c["label"] for c in got}) == len(got)


def test_the_bench_gallery_serves_the_golden_pages_only(client):
    pages = client.get("/bench/golden").json()
    names = {p["name"] for p in pages}
    assert set(CAPITAL_CASES) <= names and "de_full" in names
    capitals = next(p for p in pages if p["name"] == "en_capitals")
    assert capitals["capitals_over_time"] and capitals["lbsim"] and capitals["language"] == "en"
    page = client.get("/bench/golden/en_capitals")
    assert page.status_code == 200 and 'data-chart="capitals_time"' in page.text
    assert client.get("/bench/golden/nothing").status_code == 404
    assert client.get("/bench/golden/..%2Finputs%2Flbs_sheet").status_code == 404


def test_the_testbench_needs_no_external_script(client):
    r = client.get("/")
    assert r.status_code == 200 and "/bench/reports" in r.text and "/bench/golden" in r.text
    assert not re.search(r"<script[^>]+src=", r.text) and 'sandbox=""' in r.text
