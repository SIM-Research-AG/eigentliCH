"""Display rounding (owner, 03.10.2026, ``review/ROUNDING.md``; EIG-73): one formatter in the client
(``client/app/format.js``) and its Python twin on the server (``eigentlich.rounding``), the same rows in both.

* every row of the rule, in both languages and both code bases, with the edges: negatives, exactly 1 000,
  100 000 and 1 000 000, zero, ``None``, a chance below 1 % and above 99 %, a weight below 1 % and of 0;
* no ad-hoc number formatting left in the client (``Intl.NumberFormat`` lives in ``format.js`` alone; a
  ``toFixed`` only places an SVG mark, never prints a figure);
* the rendered pages (the home page's figures, the balance sheet, the capitals, the outlook's charts and
  sentences, drawn in Node against a small DOM stand-in, as ``test_app_pictures`` does) carry no raw float and
  no figure with more digits than the rule allows, though they are fed the engines' unrounded floats;
* a finding's sentence on the server is rounded the same way (``outlook.figure_text``)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from eigentlich import outlook as ol
from eigentlich import rounding as rnd

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
NODE = shutil.which("node")

# (function, value, German, English); None stays None. The apostrophe is the browser's de-CH thousands mark.
ROWS = [
    # amounts: whole below 1 000, nearest 100 below 100 000, nearest 1 000 below 1 000 000, then millions
    ("amount", 0, "0", "0"), ("amount", 0.4, "0", "0"), ("amount", 640, "640", "640"), ("amount", 999.4, "999", "999"),
    ("amount", 999.6, "1’000", "1’000"), ("amount", 1000, "1’000", "1’000"), ("amount", 1249, "1’200", "1’200"),
    ("amount", 1250, "1’300", "1’300"), ("amount", 38234.56, "38’200", "38’200"), ("amount", 99949, "99’900", "99’900"),
    ("amount", 99950, "100’000", "100’000"), ("amount", 100000, "100’000", "100’000"),
    ("amount", 578640.37, "579’000", "579’000"), ("amount", 999499, "999’000", "999’000"),
    ("amount", 999500, "1.00 Mio.", "1.00 m"), ("amount", 1000000, "1.00 Mio.", "1.00 m"),
    ("amount", 1354999, "1.35 Mio.", "1.35 m"), ("amount", 1355000, "1.36 Mio.", "1.36 m"),
    ("amount", 12345678, "12.35 Mio.", "12.35 m"), ("amount", -780400, "-780’000", "-780’000"),
    ("amount", -38250, "-38’300", "-38’300"), ("amount", -0.3, "0", "0"), ("amount", -2500000, "-2.50 Mio.", "-2.50 m"),
    ("amount", None, None, None),
    ("money", 38234.56, "CHF 38’200", "CHF 38’200"), ("money", 1354999, "CHF 1.35 Mio.", "CHF 1.35 m"),
    ("money", None, None, None),
    # rates: one decimal
    ("rate", 0.049, "4.9 %", "4.9 %"), ("rate", 0.0495, "5.0 %", "5.0 %"), ("rate", -0.013, "-1.3 %", "-1.3 %"),
    ("rate", 0.0, "0.0 %", "0.0 %"), ("rate", -0.0004, "0.0 %", "0.0 %"), ("rate", 0.0396, "4.0 %", "4.0 %"),
    ("rate", None, None, None),
    # chances: whole; the words at the ends; 0 and 100 only when every path agrees
    ("chance", 0.0, "0 %", "0 %"), ("chance", 1.0, "100 %", "100 %"), ("chance", 0.0001, "unter 1 %", "below 1 %"),
    ("chance", 0.0099, "unter 1 %", "below 1 %"), ("chance", 0.01, "1 %", "1 %"), ("chance", 0.684, "68 %", "68 %"),
    ("chance", 0.685, "69 %", "69 %"), ("chance", 0.99, "99 %", "99 %"), ("chance", 0.991, "über 99 %", "above 99 %"),
    ("chance", 0.9999, "über 99 %", "above 99 %"), ("chance", None, None, None),
    # weights and shares: whole; below 1 % one decimal; 0 as a dash
    ("share", 0.27, "27 %", "27 %"), ("share", 0.27493, "27 %", "27 %"), ("share", 0.004, "0.4 %", "0.4 %"),
    ("share", 0.0095, "1 %", "1 %"), ("share", 0.0094, "0.9 %", "0.9 %"), ("share", 0, "–", "–"), ("share", 2e-16, "–", "–"),
    ("share", 0.0004, "unter 0.1 %", "below 0.1 %"), ("share", 1.0, "100 %", "100 %"), ("share", -0.05, "-5 %", "-5 %"),
    ("share", None, None, None),
    # model levels: two decimals; counts and hours: whole
    ("level", 0.6234, "0.62", "0.62"), ("level", 0.625, "0.63", "0.63"), ("level", 0, "0.00", "0.00"),
    ("level", None, None, None),
    ("count", 19.6, "20", "20"), ("count", 66.5, "67", "67"), ("count", 1250, "1’250", "1’250"), ("count", 0, "0", "0"),
    ("count", None, None, None),
]


def _norm(text):
    return None if text is None else text.replace("'", "’")


@pytest.mark.parametrize("fn,value,de,en", ROWS)
def test_the_server_s_twin_follows_every_row(fn, value, de, en):
    f = getattr(rnd, fn)
    assert f(value, "de") == de and f(value, "en") == en


FORMAT_HARNESS = r"""
const F = await import(process.argv[2]);
const rows = JSON.parse(process.argv[3]);
console.log(JSON.stringify(rows.map(([fn, v]) => [F[fn](v, 'de'), F[fn](v, 'en')])));
"""


@pytest.fixture(scope="module")
def client_rows(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node is not installed: the client's formatter is checked through its twin")
    script = tmp_path_factory.mktemp("fmt") / "rows.mjs"
    script.write_text(FORMAT_HARNESS, encoding="utf-8")
    run = subprocess.run([NODE, str(script), (CLIENT / "app" / "format.js").as_uri(),
                          json.dumps([[fn, v] for fn, v, _, _ in ROWS])],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("i", range(len(ROWS)))
def test_the_client_s_formatter_follows_every_row(i, client_rows):
    fn, value, de, en = ROWS[i]
    got_de, got_en = client_rows[i]
    assert (_norm(got_de), _norm(got_en)) == (de, en), (fn, value)


def test_the_client_formats_a_stated_figure_as_stated_and_a_year_ungrouped(tmp_path):
    if NODE is None:
        pytest.skip("Node is not installed")
    script = tmp_path / "stated.mjs"
    script.write_text("const F = await import(process.argv[2]);\n"
                      "console.log(JSON.stringify([F.stated(1800, 'de'), F.stated(61234.5, 'de'), F.stated(12.5, 'de'),"
                      " F.stated(7.000000000000001, 'de'), F.year(2034), F.ratio(6.04, 'de'), F.ratio(0.8, 'de', 2)]));",
                      encoding="utf-8")
    run = subprocess.run([NODE, str(script), (CLIENT / "app" / "format.js").as_uri()],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    assert [_norm(x) for x in json.loads(run.stdout)] == ["1’800", "61’234.5", "12.5", "7", "2034", "6.0", "0.80"]


# ---------------------------------------------------------------------------- no ad-hoc formatting left

def _code(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"(?m)^\s*(//|\*|/\*\*).*$", "", re.sub(r"//[^\n]*", "", text))


def test_the_client_has_one_number_formatter():
    files = sorted((CLIENT / "app").glob("*.js")) + sorted((CLIENT / "surfaces").glob("*.js"))
    for path in files:
        if path.name == "format.js":
            continue
        code = _code(path)
        assert "Intl.NumberFormat" not in code, f"{path.name} formats a number itself"
        assert not re.search(r"text:\s*[^,}]*toFixed", code), f"{path.name} prints a toFixed figure"
        assert not re.search(r"Math\.round\([^)]*\*\s*100\)", code), f"{path.name} rounds a percent itself"
        if path.name != "charts.js":
            assert "toFixed" not in code, path.name
    charts = _code(CLIENT / "app" / "charts.js")
    # a toFixed in a chart only places a mark (a coordinate, a width), never a printed value
    for line in (ln for ln in charts.splitlines() if "toFixed" in ln):
        assert "text:" not in line, line


# ---------------------------------------------------------------------------- the rendered pages

PAGE_HARNESS_TAIL = r"""
const [home, outlook, charts, data] = process.argv.slice(2);
const H = await import(home);
const O = await import(outlook);
const C = await import(charts);
const d = JSON.parse(data);
const out = {};
for (const L of ['de', 'en']) {
  out[`totals_${L}`] = ser(H.totals(d.sheet, L));
  for (const basis of ['nominal', 'real']) {
    out[`goals_${L}_${basis}`] = ser(H.goalFigures(d.views, basis, L));
    out[`picture_${L}_${basis}`] = ser(H.pictureBlock(d.picture, basis, L));
  }
  out[`capitals_${L}`] = ser(H.capitalsBlock(d.capitals, L));
  out[`time_${L}`] = ser(O.capitalsOverTime(d.time, 2026, L));
  out[`weights_${L}`] = ser(C.weightsChart(d.weights, { title: 't', desc: 'd' }, L));
  out[`fan_${L}`] = ser(C.fanChart(d.bands, 2026, null, { value: 431234.56, dashed: true, label: 'g' },
    { title: 't', desc: 'd', outer: 'o', inner: 'i', median: 'm', today: 'h' }, L));
  out[`chance_${L}`] = [0.0042, 0.68437, 0.99731, 0, 1].map((p) => O.chanceWords(p, L)).join(' | ');
  out[`plan_${L}`] = O.planSentence({ state: 'calculating', elapsed_s: 754.3, budget_s: 10800 }, L);
}
console.log(JSON.stringify(out));
"""

# The engines' unrounded floats: if one reached the page, the scan below would find it.
SHEET = {"totals": {"financial_assets": 578640.37, "human_assets": 1354999.12, "liabilities": 14321.5,
                    "net_worth": 1919317.99}}
VIEWS = {"available": True,
         "goals": [{"name": "Eigenheim", "unit": "chf", "nominal": {"amount": 412345.67, "as_at": "2031-06-30"},
                    "real": {"amount": 371234.89}},
                   {"name": "Ausgaben ab 65", "unit": "chf_per_year", "nominal": {"amount": 71634.21},
                    "real": {"amount": 60123.45}}],
         "mandate": {"name": "Eigenheim", "nominal": {"required_return": 0.052537}, "real": {"required_return": 0.039612}},
         "inflation": {"annual_rate": 0.012345}}
PICTURE = {"assets": [{"part": "free", "chf": 65432.1}, {"part": "pillar_2", "chf": 478123.45},
                      {"part": "pillar_3a", "chf": 999.6}, {"part": "human", "chf": 1354999.12}],
           "financial_assets": 578640.37, "human_assets": 1354999.12, "total_assets": 1933639.49,
           "liabilities": 14321.5, "net_worth": 1919317.99, "yearly_goals": ["Ausgaben ab 65"], "claims_available": True,
           "claims": [{"name": "Eigenheim", "nominal": 412345.67, "real": 371234.89, "date": "2031-06-30"}]}
CAPITALS = {"adults": [{"name": "Lea", "expertise": 0.623456, "network": 0.31111, "health": 0.854999,
                        "health_withheld": False}],
            "scale": {"min": 0.0, "max": 1.0}, "wealth": {"net_worth": 1919317.99, "financial_assets": 578640.37}}
TIME = {"name": "Lea", "health_withheld": False, "series": {
    "expertise": {"bands": {q: [0.6 + 0.0123456 * i + k * 0.01 for i in range(28)]
                            for k, q in enumerate(("p10", "p25", "p50", "p75", "p90"))},
                  "scale": {"min": 0.0, "max": 1.0}, "label": "Wissen"}}}
WEIGHTS = [{"label": "Aktien Schweiz", "weight": 0.274931}, {"label": "Obligationen", "weight": 0.0042},
           {"label": "Gold", "weight": 0.000437}, {"label": "Rest", "weight": 0.720432}]
BANDS = {q: [250000.0 + 12345.678 * i * (k + 1) for i in range(12)] for k, q in
         enumerate(("p05", "p10", "p25", "p50", "p75", "p90", "p95"))}


def too_precise(text: str) -> list[str]:
    """What in a page's text carries more digits than ROUNDING.md allows: a raw float, an amount not rounded to
    its step, a percent with more than one decimal. Levels (two decimals) and millions (two) are allowed."""
    text = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", " ", text)      # a date (dd.mm.yyyy) is no figure
    bad = re.findall(r"\d+\.\d{3,}", text)
    for m in re.finditer(r"CHF (-?[\d’']+)(\.\d+)?( Mio\.| m\b)?", text):
        whole, frac, mio = m.group(1), m.group(2), m.group(3)
        if mio:
            if not frac or len(frac) != 3:
                bad.append(m.group(0))
            continue
        n = abs(int(re.sub(r"[’']", "", whole)))
        if frac or n >= 1_000_000 or (n >= 100_000 and n % 1000) or (1_000 <= n < 100_000 and n % 100):
            bad.append(m.group(0))
    bad += [m.group(0) for m in re.finditer(r"\d+\.\d{2,} ?%", text)]
    return bad


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    if NODE is None:
        pytest.skip("Node is not installed: the pages are checked by their source above")
    from .test_app_pictures import HARNESS

    head = HARNESS[:HARNESS.index("const [home, outlook, data]")]
    script = tmp_path_factory.mktemp("pages") / "pages.mjs"
    script.write_text(head + PAGE_HARNESS_TAIL, encoding="utf-8")
    data = {"sheet": SHEET, "views": VIEWS, "picture": PICTURE, "capitals": CAPITALS, "time": TIME,
            "weights": WEIGHTS, "bands": BANDS}
    run = subprocess.run([NODE, str(script), (CLIENT / "surfaces" / "home.js").as_uri(),
                          (CLIENT / "surfaces" / "outlook.js").as_uri(), (CLIENT / "app" / "charts.js").as_uri(),
                          json.dumps(data)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return {k: v.replace("'", "’") for k, v in json.loads(run.stdout).items()}


def _text(markup: str) -> str:
    """The words a person reads: the text between the tags (a mark's coordinates are attributes, not text)."""
    return re.sub(r"<[^>]+>", " ", markup)


def test_no_raw_float_reaches_a_rendered_page(pages):
    for key, markup in pages.items():
        text = _text(markup)
        assert "NaN" not in text and "undefined" not in text, key
        assert too_precise(text) == [], (key, too_precise(text))


def test_the_rendered_pages_show_the_rounded_figures(pages):
    de = _text(pages["totals_de"])
    assert "CHF 579’000" in de and "CHF 1.35 Mio." in de and "CHF 14’300" in de and "CHF 1.92 Mio." in de
    assert "Beträge gerundet." in de and "Amounts rounded." in _text(pages["totals_en"])
    assert "CHF 1.35 m" in _text(pages["totals_en"])
    goals = _text(pages["goals_de_nominal"])
    assert "CHF 412’000" in goals and "CHF 71’600 pro Jahr" in goals and "5.3 %" in goals
    assert "4.0 %" in _text(pages["goals_de_real"]) and "1.2 %" in _text(pages["goals_de_real"])
    picture = _text(pages["picture_de_nominal"])
    assert "CHF 65’400" in picture and "CHF 478’000" in picture and "CHF 1’000" in picture
    assert "mittel (0.62 von 1.00)" in _text(pages["capitals_de"])
    weights = _text(pages["weights_de"])
    assert "27 %" in weights and "0.4 %" in weights and "unter 0.1 %" in weights and "72 %" in weights
    assert pages["chance_de"] == ("In unter 1 % der simulierten Verläufe | In 68 % der simulierten Verläufe | "
                                  "In über 99 % der simulierten Verläufe | In 0 % der simulierten Verläufe | "
                                  "In 100 % der simulierten Verläufe")
    assert "below 1 %" in pages["chance_en"] and "above 99 %" in pages["chance_en"]
    assert "seit 13 Minuten, höchstens 3 Stunden" in pages["plan_de"]


def test_the_scan_catches_a_raw_figure():
    assert too_precise("CHF 578’640") and too_precise("27.49 %") and too_precise("0.623456")
    assert too_precise("CHF 1’354’999") and too_precise("CHF 1.354 Mio.")
    assert not too_precise("CHF 579’000 · 0.4 % · mittel (0.62) · CHF 1.35 Mio. · 2034 · 4.9 % · 30.06.2031")


# ---------------------------------------------------------------------------- the server's sentences

@pytest.mark.parametrize("fig,lang,text", [
    ({"value": 71634.21, "unit": "chf_per_year"}, "de", "CHF 71’600"),
    ({"value": 1354999, "unit": "chf"}, "en", "CHF 1.35 m"),
    ({"value": 0.4012, "unit": "share"}, "de", "40 %"),
    ({"value": 0.004, "unit": "share"}, "en", "0.4 %"),
    ({"value": 3.6, "unit": "years"}, "de", "4 Jahre"),
    ({"value": 19.6, "unit": "hours_per_week"}, "en", "20 hours a week"),
    ({"value": 7.4, "unit": "count"}, "de", "7"),
    ({"value": None, "unit": "chf"}, "de", "offen"),
    ({"value": 61234.0, "unit": "chf", "basis": "nominal"}, "de", "CHF 61’200 (nominal)")])
def test_a_finding_s_figure_is_rounded_in_its_sentence(fig, lang, text):
    basis = "real" if fig.get("basis") else "nominal"
    assert ol.figure_text(fig, lang, basis) == text
    assert ol.fill("Es fehlen {gap} pro Jahr.", {"gap": fig}, lang, basis) == f"Es fehlen {text} pro Jahr."
