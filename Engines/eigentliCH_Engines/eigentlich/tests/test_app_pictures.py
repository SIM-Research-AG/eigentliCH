"""The life balance sheet as a graph and the four capitals (VISUALS_INTERFACES.md; EIG-70 to EIG-72):

* the server's pieces (``pictures``): lbs's figures by vessel, the debts, the net worth and the goals' claims in both
  bases, names instead of ids; today's capitals per adult; lbsim's ``capitals`` over time in one language; the K3
  rule (a withheld health leaves the server neither as a figure nor as a band);
* the mirror of lbsim's new field (optional, additive) and the two routes that carry the pieces;
* the browser: the three new charts drawn through the namespace-aware ``h()`` (in Node, against a small DOM
  stand-in, when Node is there), the home page's "Lebensbilanz" following the switch, the outlook's capitals.

On a throwaway schema seeded and aligned, with stand-in engines (lbsim on its frozen samples plus a capitals block
made from the spec, ``fixtures/lbsim/capitals.sample.json``)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eigentlich import alignment, pictures, store
from eigentlich import contracts as c
from eigentlich import seed as seeding
from eigentlich import outlook as ol

from .appkit import Engines, make_app
from .test_app_lbsim import allocate, new_client, with_goals, with_household

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
SAMPLES = Path(__file__).resolve().parent / "fixtures" / "lbsim"
CAPS = json.loads((SAMPLES / "capitals.sample.json").read_text(encoding="utf-8"))
ID = re.compile(r"\b(LBS|LSF|LSP|LSO|RUN|PCP|IDK|RGM)-|[0-9a-f]{32}")

SHEET = {
    "totals": {"financial_assets": 579000.0, "human_assets": 150000.0, "total_assets": 729000.0, "liabilities": 14000.0,
               "net_worth": 715000.0,
               "by_vessel": {"free": 65000.0, "pillar_2": 478000.0, "pillar_3a": 36000.0, "real_asset": None,
                             "not_stated": None}},
    "human_capital": [
        {"person_id": "p1", "E": {"key": "E", "value": 0.62}, "N": {"key": "N", "value": 0.31},
         "H": {"key": "H", "value": 0.85}},
        {"person_id": "p2", "E": {"key": "E", "value": None}, "N": {"key": "N", "value": 0.53},
         "H": {"key": "H", "value": None, "absent_because": pictures.LBS_WITHHELD}}],
    "real_view": {"goals": [
        {"goal_id": "g-home", "unit": "chf", "nominal": {"amount": 375000.0, "as_at": "2029-12-31"},
         "real": {"amount": 250000.0, "as_at": None}},
        {"goal_id": "g-ret", "unit": "chf_per_year", "nominal": {"amount": 90000.0}, "real": {"amount": 60000.0}}]},
}
NAMES = {"g-home": "Eigenheim in Luzern", "g-ret": "Ausgaben ab 65"}


# ---------------------------------------------------------------------------- the server's pieces (pure)

def test_the_balance_picture_is_lbs_s_figures_with_names():
    pic = pictures.balance(SHEET, NAMES)
    assert pic["assets"] == [{"part": "free", "chf": 65000.0}, {"part": "pillar_2", "chf": 478000.0},
                             {"part": "pillar_3a", "chf": 36000.0}, {"part": "human", "chf": 150000.0}]
    assert pic["liabilities"] == 14000.0 and pic["net_worth"] == 715000.0
    assert pic["claims"] == [{"name": "Eigenheim in Luzern", "nominal": 375000.0, "real": 250000.0, "date": "2029-12-31"}]
    assert pic["yearly_goals"] == ["Ausgaben ab 65"], "a need a year is named, never stacked with the stocks"
    assert not ID.search(json.dumps(pic)) and "g-home" not in json.dumps(pic)


def test_an_open_part_is_left_out_never_drawn_as_zero():
    sheet = {"totals": {"financial_assets": None, "human_assets": None, "liabilities": None, "net_worth": None,
                        "by_vessel": {"free": None, "pillar_2": 0.0}}}
    pic = pictures.balance(sheet, {})
    assert pic["assets"] == [] and pic["liabilities"] is None and pic["net_worth"] is None
    assert pic["claims"] == [] and pic["claims_available"] is False


def test_today_s_capitals_per_adult_and_the_k3_rule():
    caps = pictures.capitals_today(SHEET, {"p1": "Lea", "p2": "Noa"}, set())
    lea, noa = caps["adults"]
    assert lea == {"name": "Lea", "health_withheld": False, "expertise": 0.62, "network": 0.31, "health": 0.85}
    assert noa["health_withheld"] is True and noa["health"] is None and noa["expertise"] is None
    assert caps["scale"] == {"min": 0.0, "max": 1.0}
    assert caps["wealth"] == {"net_worth": 715000.0, "financial_assets": 579000.0}
    # withheld in the request the app sent: the figure lbs computed does not leave either
    held = pictures.capitals_today(SHEET, {"p1": "Lea"}, {"p1"})["adults"][0]
    assert held["health"] is None and held["health_withheld"] is True and "0.85" not in json.dumps(held)
    request = {"household": {"persons": [{"person_id": "p1", "human_capital": {"health_withheld": True}},
                                         {"person_id": "p2", "human_capital": {"health_withheld": False}}]}}
    assert pictures.withheld_persons(request) == {"p1"} and pictures.withheld_persons(None) == set()


def test_the_capitals_over_time_in_one_language_without_the_id():
    de = pictures.capitals_over_time(CAPS, {"p1": "Lea"}, "de", set())
    assert de["name"] == "Lea" and set(de["series"]) == {"expertise", "network", "health"}
    assert de["series"]["expertise"]["label"] == "Wissen und Ausbildung"
    assert de["series"]["network"]["scale"] == {"min": 0.0, "max": 1.0}
    assert len(de["series"]["health"]["bands"]["p50"]) == 28
    en = pictures.capitals_over_time(CAPS, {"p1": "Lea"}, "en", set())
    assert en["series"]["network"]["label"] == "Network" and "Netzwerk" not in json.dumps(en)
    assert '"p1"' not in json.dumps(de) and "person_id" not in json.dumps(de)
    held = pictures.capitals_over_time(CAPS, {"p1": "Lea"}, "de", {"p1"})
    assert held["health_withheld"] is True and "health" not in held["series"]
    assert pictures.capitals_over_time(None, {}, "de", set()) is None


def test_the_shaped_outlook_carries_the_capitals_per_regime():
    paths = json.loads((SAMPLES / "paths.sample.json").read_text(encoding="utf-8"))
    for r in paths["regimes"]:
        r["capitals"] = CAPS
    raw = {"findings": None, "paths": paths, "plan": {"state": "not_requested"}}
    shaped = ol.shape(raw, language="de", basis="nominal", persons={"p1": "Lea"}, goals={}, role_name=str,
                      questions=ol.Questions({}), mandate_goal=None, withheld={"p1"})
    for r in shaped["paths"]["regimes"]:
        assert r["capitals"]["name"] == "Lea" and set(r["capitals"]["series"]) == {"expertise", "network"}
    del paths["regimes"][0]["capitals"]
    shaped = ol.shape(raw, language="de", basis="nominal", persons={}, goals={}, role_name=str,
                      questions=ol.Questions({}), mandate_goal=None)
    assert shaped["paths"]["regimes"][0]["capitals"] is None, "an artefact made before the field"


# ---------------------------------------------------------------------------- the mirror

def _outlook(regimes, horizon=27):
    paths = {"contract_version": "lbsim-paths@1.0.0", "artefact_id": "LSP-1", "client_ref": "c1",
             "life_balance_sheet_id": "LBS-1", "allocation_id": "PCP-1", "findings_artefact_id": "LSF-1",
             "horizon_years": horizon, "regimes": regimes}
    return {"client_ref": "c1", "life_balance_sheet_id": "LBS-1", "paths": paths, "plan": {"state": "not_requested"}}


def test_the_mirror_takes_the_capitals_and_does_without_them():
    ok = c.LbsimOutlook.model_validate(_outlook([{"key": "base", "capitals": CAPS}, {"key": "depression"}]))
    caps = ok.paths.regimes[0].capitals
    assert caps.person_id == "p1" and len(caps.network.p90) == 28 and caps.scale["health"].max == 1.0
    assert ok.paths.regimes[1].capitals is None
    assert c.LbsimOutlook.model_validate(_outlook([])).paths.regimes == ()
    with pytest.raises(ValueError, match="one value per year end"):
        c.LbsimOutlook.model_validate(_outlook([{"key": "base", "capitals": CAPS}], horizon=10))
    short = json.loads(json.dumps(CAPS))
    short["expertise"]["p10"] = short["expertise"]["p10"][:5]
    with pytest.raises(ValueError, match="one value per year end"):
        c.LbsimOutlook.model_validate(_outlook([{"key": "base", "capitals": short}]))
    unscaled = json.loads(json.dumps(CAPS))
    del unscaled["scale"]["network"]
    with pytest.raises(ValueError, match="without its scale"):
        c.LbsimOutlook.model_validate(_outlook([{"key": "base", "capitals": unscaled}]))


LBSIM_SAMPLE = ROOT.parent / "engines" / "lbsim" / "golden" / "samples" / "paths.sample.json"


@pytest.mark.skipif(not LBSIM_SAMPLE.is_file(), reason="lbsim's source is not beside this package")
def test_lbsim_s_own_sample_passes_the_mirror_and_each_regime_keeps_its_scale():
    """lbsim 1.1.0's sample (LBSIM P-26): the network has no fixed ceiling, so its scale is given per Regime (1, or
    that Regime's highest p90). The page reads each Regime's scale as given and never assumes 1."""
    paths = json.loads(LBSIM_SAMPLE.read_text(encoding="utf-8"))
    if not any(r.get("capitals") for r in paths.get("regimes") or []):
        pytest.skip("lbsim's sample predates the capitals")
    checked = c.LbsimOutlook.model_validate({"client_ref": paths["client_ref"], "plan": {"state": "not_requested"},
                                             "life_balance_sheet_id": paths["life_balance_sheet_id"], "paths": paths})
    assert all(r.capitals is not None for r in checked.paths.regimes)
    for r in paths["regimes"]:
        shaped = pictures.capitals_over_time(r["capitals"], {"p1": "Lea"}, "de", set())
        for name in ("expertise", "network", "health"):
            assert shaped["series"][name]["scale"]["max"] == r["capitals"]["scale"][name]["max"]
            assert len(shaped["series"][name]["bands"]["p50"]) == paths["horizon_years"] + 1


# ---------------------------------------------------------------------------- the routes

@pytest.fixture(scope="module")
def world(settings, st):
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
        owner = store.create_curator(conn, display_name="Nicolas (Owner)")["id"]
    with st.session() as conn:
        alignment.align(conn, curator_id=owner)
    with st.session() as conn:
        alignment.revise(conn, curator_id=owner)
    with st.session() as conn:
        alignment.revise_basis(conn, curator_id=owner)
    with st.session() as conn:
        alignment.revise_earning(conn, curator_id=owner)
    return {"owner": owner}


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, world, engines):
    with TestClient(make_app(settings, engines)) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


def _pictured(http, name):
    cid = new_client(http, name)
    with_household(http, cid)
    with_goals(http, cid)
    for label, vessel, amount in (("Sparkonto", "free", 65000), ("Pensionskasse", "pillar_2", 478000)):
        r = http.post(f"/api/clients/{cid}/positions", json={
            "role": "stabilisation", "capital_type": "financial", "label": label, "magnitude": amount,
            "magnitude_unit": "chf", "stock_kind": "asset", "liquidity": "within_years", "vessel": vessel})
        assert r.status_code == 201, r.text
    return cid


def test_the_balance_sheet_route_carries_the_picture_and_the_capitals(http, engines):
    cid = _pictured(http, "Bild")
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    bs = http.get(f"/api/clients/{cid}/balance-sheet").json()
    pic, caps = bs["picture"], bs["capitals"]
    assert {a["part"]: a["chf"] for a in pic["assets"]} == {"free": 65000.0, "pillar_2": 478000.0}
    assert [g["name"] for g in pic["claims"]] == ["Eigenheim in Luzern"]
    claim = pic["claims"][0]
    assert claim["nominal"] == 375000.0 and claim["real"] == 250000.0, "both bases from lbs's real view"
    assert pic["yearly_goals"] == ["Ausgaben ab 65"]
    assert caps["adults"] == [{"name": "Lea", "health_withheld": False, "expertise": 0.62, "network": None,
                               "health": 0.85}]
    assert not ID.search(json.dumps({"picture": pic, "capitals": caps}))
    home = http.get(f"/api/clients/{cid}/home").json()["balance_sheet"]
    assert home["picture"] == pic and home["capitals"] == caps


def test_a_withheld_health_never_reaches_the_page(http, engines):
    engines.lbs.health_withheld = True
    cid = _pictured(http, "Geschützt")
    http.post(f"/api/clients/{cid}/balance-sheet")
    adult = http.get(f"/api/clients/{cid}/balance-sheet").json()["capitals"]["adults"][0]
    assert adult["health_withheld"] is True and adult["health"] is None


def test_the_outlook_route_carries_the_capitals_over_time(http, st, world, engines):
    engines.lbsim.capitals = True
    cid = _pictured(http, "Verlauf")
    allocate(st, cid, world["owner"])
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    http.post(f"/api/clients/{cid}/outlook")
    for lang, word in (("de", "Wissen und Ausbildung"), ("en", "Expertise and education")):
        page = http.get(f"/api/clients/{cid}/outlook?language={lang}").json()
        base = next(r for r in page["paths"]["regimes"] if r["key"] == "base")
        caps = base["capitals"]
        assert caps["name"] == "Lea" and caps["series"]["expertise"]["label"] == word
        assert set(caps["series"]) == {"expertise", "network", "health"}
        assert not ID.search(json.dumps(caps)) and "person_id" not in json.dumps(caps)
    # without the field (an artefact made before it): the regime says nothing, the page says it is not there yet
    engines.lbsim.capitals = False
    cid2 = _pictured(http, "Früher")
    allocate(st, cid2, world["owner"])
    http.post(f"/api/clients/{cid2}/balance-sheet")
    http.post(f"/api/clients/{cid2}/outlook")
    page = http.get(f"/api/clients/{cid2}/outlook").json()
    assert all(r["capitals"] is None for r in page["paths"]["regimes"])


# ---------------------------------------------------------------------------- the browser

CHARTS = (CLIENT / "app" / "charts.js").read_text(encoding="utf-8")
HOME = (CLIENT / "surfaces" / "home.js").read_text(encoding="utf-8")
OUTLOOK = (CLIENT / "surfaces" / "outlook.js").read_text(encoding="utf-8")
I18N = (CLIENT / "app" / "i18n.js").read_text(encoding="utf-8")


def _code(text: str) -> str:
    return re.sub(r"//[^\n]*", "", text)


def test_the_new_charts_are_svg_through_h_without_a_library():
    code = _code(CHARTS)
    for name in ("balanceChart", "capitalsChart", "capitalPathChart", "levelWord"):
        assert f"export function {name}" in CHARTS
    assert "innerHTML" not in code and "<script" not in code
    assert "http" not in code.replace("http://www.w3.org", "")
    path_chart = code[code.index("export function capitalPathChart"):]
    assert "CHF" not in path_chart and "amount(" not in path_chart, "a capital is never on a money axis"
    caps_chart = code[code.index("export function capitalsChart"):code.index("export function capitalPathChart")]
    assert "row.health_withheld" in caps_chart and "words.withheld" in caps_chart


def test_the_home_page_draws_the_balance_sheet_and_follows_the_switch():
    code = _code(HOME)
    draw = re.search(r"function drawSheet\(bs\)\s*\{(.*?)\n  \}", code, re.S).group(1)
    assert "pictureBlock(bs.picture, basis, L)" in draw and "capitalsBlock(bs.capitals, L)" in draw
    assert "basisSwitch(L, () => drawSheet(last))" in draw, "the switch redraws the picture"
    block = code[code.index("export function pictureBlock"):code.index("export function capitalsBlock")]
    assert "c[basis]" in block, "the goals' claims in the basis shown"
    for raw in ("goal_id", "person_id", "artefact_id"):
        assert raw not in block, raw


def test_the_outlook_draws_the_capitals_over_time_and_respects_k3():
    code = _code(OUTLOOK)
    body = re.search(r"function drawCharts\([^)]*\)\s*\{(.*?)\n  \}", code, re.S).group(1)
    assert "capitalsOverTime(reg.capitals, p.start_year, L)" in body
    fn = code[code.index("export function capitalsOverTime"):code.index("export async function render")]
    assert "caps.health_withheld" in fn and "capitals.time_withheld" in fn and "capitals.not_yet" in fn
    assert "capitalPathChart(" in fn and "person_id" not in fn


def test_the_new_words_are_in_both_languages():
    de, en = I18N.split("\nconst en = {", 1)
    keys = set(re.findall(r"'((?:picture|capitals)\.[a-z_.0-9]+)':", I18N))
    assert len(keys) > 30
    for k in keys:
        assert f"'{k}':" in de and f"'{k}':" in en, k
    assert "—" not in "".join(re.findall(r"'(?:picture|capitals)\.[^']+': (?:'[^']*'|\"[^\"]*\")", I18N))


NODE = shutil.which("node")

HARNESS = r"""
class Node { constructor() { this.children = []; this.attrs = {}; } append(...k) { this.children.push(...k); }
  setAttribute(k, v) { this.attrs[k] = String(v); } addEventListener() {} }
class Text extends Node { constructor(t) { super(); this.text = String(t); } }
class El extends Node {
  constructor(tag, ns) { super(); this.tag = tag; this.ns = ns; }
  set textContent(v) { this.children = [new Text(v)]; } set className(v) { this.attrs.class = v; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t, null), createElementNS: (ns, t) => new El(t, ns),
  createTextNode: (t) => new Text(t), documentElement: { lang: 'de' }, getElementById: () => null };
globalThis.localStorage = { getItem: () => null, setItem() {} };
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
const ser = (n) => n instanceof Text ? esc(n.text) : `<${n.tag}${n.ns ? ' ns="svg"' : ''}${Object.entries(n.attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join('')}>${n.children.map(ser).join('')}</${n.tag}>`;
const [home, outlook, data] = process.argv.slice(2);
const H = await import(home);
const O = await import(outlook);
const d = JSON.parse(data);
const out = {};
for (const L of ['de', 'en']) {
  for (const basis of ['nominal', 'real']) out[`picture_${L}_${basis}`] = ser(H.pictureBlock(d.picture, basis, L));
  out[`capitals_${L}`] = ser(H.capitalsBlock(d.capitals, L));
  out[`time_${L}`] = ser(O.capitalsOverTime(d.time, 2026, L));
  out[`time_held_${L}`] = ser(O.capitalsOverTime(d.time_held, 2026, L));
  out[`time_none_${L}`] = ser(O.capitalsOverTime(null, 2026, L));
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node is not installed: the charts are checked by their source above")
    script = tmp_path_factory.mktemp("node") / "draw.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    data = {"picture": pictures.balance(SHEET, NAMES),
            "capitals": pictures.capitals_today(SHEET, {"p1": "Lea", "p2": "Noa"}, set()),
            "time": pictures.capitals_over_time(CAPS, {"p1": "Lea"}, "de", set()),
            "time_held": pictures.capitals_over_time(CAPS, {"p1": "Lea"}, "de", {"p1"})}
    run = subprocess.run([NODE, str(script), (CLIENT / "surfaces" / "home.js").as_uri(),
                          (CLIENT / "surfaces" / "outlook.js").as_uri(), json.dumps(data)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    # one apostrophe for the thousands, whichever the ICU at hand writes (a browser writes ’, a small ICU ')
    return {k: v.replace("’", "'") for k, v in json.loads(run.stdout).items()}


def test_the_charts_draw_in_the_browser_as_svg_with_their_words(drawn):
    for key, markup in drawn.items():
        assert "NaN" not in markup and "undefined" not in markup and "Infinity" not in markup, key
        assert not ID.search(markup), key
    de = drawn["picture_de_nominal"]
    assert '<svg ns="svg" class="chart" role="img"' in de and '<title ns="svg">Ihre Lebensbilanz</title>' in de
    for words in ("frei verfügbar", "Pensionskasse / Freizügigkeit", "Säule 3a", "menschliches Kapital", "Schulden",
                  "Nettovermögen", "Eigenheim in Luzern · 2029", "CHF 375'000", "Ausgaben ab 65"):
        assert words in de, words
    real = drawn["picture_de_real"]
    assert "CHF 250'000" in real and "CHF 375'000" not in real and "in heutigen Franken" in real
    assert "CHF 65'000" in real, "today's assets are the same in both bases"
    assert "Your life balance sheet" in drawn["picture_en_nominal"] and "Vermögen" not in drawn["picture_en_nominal"]


def test_the_capitals_are_levels_in_words_and_k3_is_said_not_drawn(drawn):
    de = drawn["capitals_de"]
    assert "Wissen und Ausbildung" in de and "mittel (0.62 von 1.00)" in de and "hoch (0.85 von 1.00)" in de
    assert "CHF 715'000 netto, gemeinsam im Haushalt" in de
    noa = de[de.index("Noa"):]
    assert "zurückgehalten" in noa and 'class="chart-capital health"' not in noa, "Noa's health is not drawn"
    assert 'class="chart-capital health"' in de[:de.index("Noa")], "Lea's health is drawn"
    en = drawn["capitals_en"]
    assert "moderate (0.62 of 1.00)" in en and "withheld by you" in en and "Gesundheit" not in en
    time = drawn["time_de"]
    assert time.count('<svg ns="svg" class="chart" role="img"') == 3 and "CHF" not in time
    assert "80 von 100 Verläufen" in time and "Skalenende 1.00" in time and "2053" in time
    held = drawn["time_held_de"]
    assert held.count('role="img"') == 2 and "Gesundheitsangaben zurückgehalten" in held
    assert "noch nicht vor" in drawn["time_none_de"] and "not yet available" in drawn["time_none_en"]


def test_the_drawn_pages_carry_no_raw_float(drawn):
    """Display rounding (ROUNDING.md, EIG-73): the text a person reads on these pages carries no raw float and no
    figure with more digits than the rule allows."""
    from .test_app_rounding import too_precise

    for key, markup in drawn.items():
        text = re.sub(r"<[^>]+>", " ", markup)
        assert too_precise(text) == [], (key, too_precise(text))
