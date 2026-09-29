"""lbsim in the report (REP-32 to REP-36): the sources, the refusals, the five sections, the facts and the three
charts.

* A request draws on at most one source per engine and artefact kind (LSF, LSP, LSO); a request without lbsim
  sources keeps its id.
* lbsim artefacts on another sheet than the lbs source, paths on another Allocation than the pcp source, a plan on
  other paths (or without its paths), paths on other findings, and another client's artefacts are refused, each
  with a plain sentence.
* On the frozen pages: the three charts are there, every printed value in an SVG is a fact's ``<tspan>``, no SVG
  carries a ``<script>`` or ``http``, each names itself in words (``role="img"``, ``<title>``, ``<desc>``, a
  ``viewBox``); the finding texts are lbsim's templates in the page's language; the plan's figures stand under
  "Was die Rechnung annimmt"; a report whose plan still runs says "wird berechnet", and the update carries the plan.
"""

from __future__ import annotations

import json
import re

import pytest

from report import charts, engine
from report.contracts import Fact, FactSource, ReportRequest
from report.service import Service

from . import golden_cases as gc
from .conftest import request_body

OUTLOOK_CASES = [c["name"] for c in gc.cases() if c["name"].startswith(("de_outlook", "en_outlook"))]
ALL_THREE = ["de_outlook", "en_outlook", "de_outlook_calculating", "de_outlook_plan_update", "de_outlook_real",
             "en_outlook_real"]


def _raw(name: str) -> bytes:
    return (gc.INPUTS / name).read_bytes()


def _json(name: str) -> dict:
    return json.loads(_raw(name))


SHEET, ALLOC = _json("lbs_sheet_lbsim.json"), _json("pcp_allocation_lbsim.json")
FINDINGS, PATHS, PLAN = _json("lbsim_findings.json"), _json("lbsim_paths.json"), _json("lbsim_plan.json")
CLIENT = SHEET["client_ref"]


def src(engine_name: str, doc: dict) -> dict:
    return {"engine": engine_name, "artefact_id": doc["artefact_id"]}


OUTLOOK = [src("pcp", ALLOC), src("lbs", SHEET), src("lbsim", FINDINGS), src("lbsim", PATHS), src("lbsim", PLAN)]


# -- the request ----------------------------------------------------------------------------------------------

def test_one_source_per_engine_and_artefact_kind():
    ok = ReportRequest.model_validate(request_body(client_ref=CLIENT, sources=OUTLOOK))
    assert len(ok.sources) == 5
    twice = OUTLOOK + [{"engine": "lbsim", "artefact_id": "LSF-0000000000000000"}]
    with pytest.raises(ValueError, match="at most one source artefact per engine and artefact kind"):
        ReportRequest.model_validate(request_body(client_ref=CLIENT, sources=twice))
    with pytest.raises(ValueError, match="findings \\(LSF-\\), paths \\(LSP-\\) or plan \\(LSO-\\)"):
        ReportRequest.model_validate(request_body(client_ref=CLIENT, sources=[{"engine": "lbsim",
                                                                               "artefact_id": "LBS-1a68c6aa5d613766"}]))
    with pytest.raises(ValueError, match="at most one source artefact per engine"):
        ReportRequest.model_validate(request_body(sources=[src("lbs", SHEET), src("lbs", SHEET)]))


def test_a_request_without_lbsim_sources_keeps_its_id_and_its_bytes():
    """The golden de_full request: its id is the one of engine 1.2.0 and 1.3.0 (``RRQ-cf68ec90594ccb16``), and its
    JSON carries no field it did not carry before."""
    body = gc.cases()[0]["request"]
    request = ReportRequest.model_validate(body)
    assert Service.request_id(request) == "RRQ-cf68ec90594ccb16"
    assert set(request.model_dump()) == {"contract_version", "client_ref", "kind", "language", "sources",
                                         "previous_report_id", "display_facts", "prose", "calibration_version",
                                         "basis", "revision_of", "revision_note"}


# -- the refusals, each a plain sentence ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def served(upstream):
    """The frozen lbsim case and variants of it, served by the test doubles."""
    upstream.extra["pcp"].update({f"/allocation/{ALLOC['artefact_id']}": _raw("pcp_allocation_lbsim.json")})
    upstream.extra["lbs"].update({f"/artefacts/{SHEET['artefact_id']}": _raw("lbs_sheet_lbsim.json")})
    for name in ("lbsim_findings.json", "lbsim_paths.json", "lbsim_plan.json"):
        upstream.extra["lbsim"][f"/artefacts/{_json(name)['artefact_id']}"] = _raw(name)
    variants = {
        "findings_other_sheet": {**FINDINGS, "artefact_id": "LSF-00000000000000a1",
                                 "life_balance_sheet_id": "LBS-00000000000000b2"},
        "plan_other_paths": {**PLAN, "artefact_id": "LSO-00000000000000a3", "paths_artefact_id": "LSP-00000000000000c4"},
        "paths_other_findings": {**PATHS, "artefact_id": "LSP-00000000000000a5",
                                 "findings_artefact_id": "LSF-00000000000000d6"},
        "paths_other_client": {**PATHS, "artefact_id": "LSP-00000000000000a7", "client_ref": "someone-else"},
    }
    for doc in variants.values():
        upstream.extra["lbsim"][f"/artefacts/{doc['artefact_id']}"] = json.dumps(doc).encode("utf-8")
    return variants


def _refused(client, sources, **over) -> str:
    r = client.post("/report", json=request_body(client_ref=CLIENT, sources=sources, prose=False, **over))
    assert r.status_code == 422, r.text
    return r.json()["detail"]["error"]


def test_the_outlook_is_reported(client, served):
    r = client.post("/report", json=request_body(client_ref=CLIENT, sources=OUTLOOK, prose=False))
    assert r.status_code == 200, r.text
    rep = r.json()
    keys = [s["key"] for s in rep["sections"]]
    assert {"earning_power", "income_paths", "outlook", "plan", "findings"} <= set(keys)
    assert keys.index("human_capital") + 1 == keys.index("earning_power")
    assert {s["engine"] for s in rep["provenance"]["sources"]} == {"pcp", "lbs", "lbsim"}
    assert all(s["prose_status"] == "not_requested" for s in rep["sections"])


def test_lbsim_artefacts_on_another_sheet_are_refused(client, served):
    error = _refused(client, [src("lbs", SHEET), src("lbsim", served["findings_other_sheet"])])
    assert "never mixes two balance sheets" in error and "LBS-00000000000000b2" in error


def test_lbsim_artefacts_on_two_sheets_are_refused_without_an_lbs_source(client, served):
    error = _refused(client, [src("lbsim", served["findings_other_sheet"]), src("lbsim", PATHS)])
    assert "rest on different balance sheets" in error or "rest on findings" in error


def test_paths_on_another_allocation_are_refused(client, served):
    error = _refused(client, [{"engine": "pcp", "artefact_id": json.loads((gc.INPUTS / "pcp_allocation.json")
                                                                         .read_bytes())["artefact_id"]},
                              src("lbs", SHEET), src("lbsim", PATHS)])
    assert "never mixes two allocations" in error and ALLOC["artefact_id"] in error


def test_a_plan_on_other_paths_or_without_its_paths_is_refused(client, served):
    error = _refused(client, [src("lbs", SHEET), src("lbsim", PATHS), src("lbsim", served["plan_other_paths"])])
    assert "never shows a plan on other paths" in error
    error = _refused(client, [src("lbs", SHEET), src("lbsim", PLAN)])
    assert "reported with the paths it was calculated on" in error


def test_paths_on_other_findings_are_refused(client, served):
    error = _refused(client, [src("lbs", SHEET), src("lbsim", FINDINGS), src("lbsim", served["paths_other_findings"])])
    assert "rest on findings" in error


def test_another_clients_lbsim_artefact_is_refused(client, served):
    error = _refused(client, [src("lbs", SHEET), src("lbsim", served["paths_other_client"])])
    assert "never draws on another client's artefact" in error


def test_a_real_report_refuses_the_nominal_allocation_of_the_paths(client, served):
    """REP-28 holds with lbsim: a real report takes lbs and lbsim alone, not a nominal Allocation."""
    error = _refused(client, OUTLOOK, basis="real")
    assert "never mixes nominal and real figures" in error


def test_an_unknown_lbsim_artefact_is_refused(client, served):
    error = _refused(client, [src("lbs", SHEET), {"engine": "lbsim", "artefact_id": "LSP-ffffffffffffffff"}])
    assert "lbsim has no artefact" in error


# -- the frozen pages ---------------------------------------------------------------------------------------------

def _svgs(page: str) -> list[str]:
    return re.findall(r"<svg\b.*?</svg>", page, re.S)


@pytest.mark.parametrize("name", ALL_THREE)
def test_the_pages_carry_all_three_charts(name):
    page = gc.frozen(name)["report"]["html"]
    shown = re.findall(r'<figure class="chart" data-chart="([^"]+)">', page)
    assert shown == ["roles", "positions", "fit", "outlook"], shown


@pytest.mark.parametrize("name", [c["name"] for c in gc.cases()])
def test_every_svg_is_self_contained_and_prints_only_facts(name):
    report = gc.frozen(name)["report"]
    facts = {f["fact_id"]: f for f in report["facts"]}
    for svg in _svgs(report["html"]):
        assert "<script" not in svg.lower() and "http" not in svg.lower()
        assert "xlink" not in svg and "<image" not in svg and "@import" not in svg and "url(" not in svg
        assert 'role="img"' in svg and 'viewBox="0 0 ' in svg
        assert re.search(r"<title>[^<\d]+</title>", svg) and re.search(r"<desc>[^<\d]+</desc>", svg)
        printed = re.findall(r'<tspan data-fact="([^"]+)">([^<]*)</tspan>', svg)
        for fact_id, text in printed:
            assert fact_id in facts, fact_id
            assert text == __import__("html").escape(facts[fact_id]["display"], quote=True), fact_id
        # Outside the fact spans, a chart prints words only: no tick label, no axis number.
        rest = re.sub(r'<tspan data-fact="[^"]+">[^<]*</tspan>', " ", svg)
        text = re.sub(r"<[^>]+>", " ", rest)
        assert not re.search(r"\d", text), re.findall(r".{20}\d.{20}", text)


def test_the_weights_chart_prints_the_role_and_position_facts():
    report = gc.frozen("de_outlook")["report"]
    page = report["html"]
    roles = re.search(r'data-chart="roles">(.*?)</figure>', page, re.S).group(1)
    assert set(re.findall(r'data-fact="([^"]+)"', roles)) == {f["fact_id"] for f in report["facts"]
                                                               if f["fact_id"].startswith("pcp.role.")}
    words = re.sub(r"<[^>]+>", " ", roles)
    assert "Wertsteigerung" in words and "Absicherung" in words and "Gain" not in words
    held = re.search(r'data-chart="positions">(.*?)</figure>', page, re.S).group(1)
    held_words = re.sub(r"<[^>]+>", " ", held)
    assert "MSCI AC World IMI" in held_words and "INS-" not in held_words


def test_the_fit_chart_names_the_states_in_words_and_its_basis():
    page = gc.frozen("de_outlook")["report"]["html"]
    fit = re.search(r'data-chart="fit">(.*?)</figure>', page, re.S).group(1)
    assert ">Krise<" in fit and ">Boom<" in fit and "Rendite null" in fit and "nominal." in fit
    assert fit.count("<polyline") == 2


def test_the_fan_dashes_the_goal_in_the_other_basis_only():
    """The home goal is set in today's francs (``chance_basis`` real): dashed and converted in nominal, solid in
    real (LBSIM-09)."""
    nominal = re.search(r'data-chart="outlook">(.*?)</figure>', gc.frozen("de_outlook")["report"]["html"], re.S).group(1)
    real = re.search(r'data-chart="outlook">(.*?)</figure>', gc.frozen("de_outlook_real")["report"]["html"],
                     re.S).group(1)
    assert 'stroke-dasharray="6 4"' in nominal and "umgerechnet" in nominal
    assert 'stroke-dasharray="6 4"' not in real and "umgerechnet" not in real
    for part in (nominal, real):
        ids = set(re.findall(r'data-fact="([^"]+)"', part))
        assert {"lbsim.fan.base.p10.end", "lbsim.fan.base.p50.end", "lbsim.fan.base.p90.end",
                "lbsim.chance.base.goal1", "lbsim.goal.goal1.target", "lbsim.goal.goal1.date"} <= ids


@pytest.mark.parametrize("name", OUTLOOK_CASES)
def test_the_facts_of_the_spec_are_there(name):
    report = gc.frozen(name)["report"]
    ids = {f["fact_id"] for f in report["facts"]}
    assert {"lbsim.earning_power.person1.modelled", "lbsim.earning_power.person1.stated", "lbsim.earning_power.person1.level_basis",
            "lbsim.path.today.saving_need.goal1", "lbsim.finding.undirected_surplus.undirected",
            "lbsim.chance.base.goal1", "lbsim.chance.stagflation.goal2", "lbsim.fan.base.p50.end"} <= ids
    if name == "de_outlook_calculating":
        assert "lbsim.plan.state" in ids and not any(i.startswith("lbsim.plan.action_now.") for i in ids)
    else:
        assert "lbsim.plan.state" not in ids
        assert {f"lbsim.plan.action_now.{k}" for k in ("work_share", "consumption_chf_per_year",
                                                       "saving_chf_per_year")} <= ids
    basis = report["basis"]
    by = {f["fact_id"]: f for f in report["facts"]}
    assert by["lbsim.path.today.saving_need.goal1"]["basis"] == basis
    assert by["lbsim.fan.base.p50.end"]["basis"] == basis
    # lbs's "earning power is another model's" note goes when lbsim's section is there.
    assert not any(i.startswith("lbs.human.") and i.endswith(".earning_power") for i in ids)


def test_a_real_report_reads_lbsims_real_views():
    real = {f["fact_id"]: f for f in gc.frozen("de_outlook_real")["report"]["facts"]}
    nominal = {f["fact_id"]: f for f in gc.frozen("de_outlook")["report"]["facts"]}
    need = FINDINGS["income_paths"][0]["views"]["real"]["saving_need"][0]
    assert real["lbsim.path.today.saving_need.goal1"]["value"] == need["zero_return_saving_chf_per_year"]
    assert real["lbsim.path.today.saving_need.goal1"]["sources"][0]["path"].startswith("/income_paths/0/views/real/")
    assert real["lbsim.goal.goal1.target"]["value"] == PATHS["regimes"][0]["goals"][0]["target"]["real_chf"]
    assert nominal["lbsim.goal.goal1.target"]["value"] == PATHS["regimes"][0]["goals"][0]["target"]["nominal_chf"]
    assert real["lbsim.fan.base.p50.end"]["sources"][0]["path"].startswith("/regimes/0/bands/deposit_eligible/real/")
    # A chance is one per goal and Regime, independent of the view.
    assert real["lbsim.chance.base.goal1"]["value"] == nominal["lbsim.chance.base.goal1"]["value"]
    # A finding's figure lbsim states nominal stays nominal, and is marked so.
    assert real["lbsim.finding.undirected_surplus.undirected"]["basis"] == "nominal"


@pytest.mark.parametrize("name,words", [("de_outlook", ("keine Verwendung", "Ein Überschuss ohne Verwendung")),
                                        ("en_outlook", ("has no use", "A surplus without a use"))])
def test_the_findings_are_lbsims_templates_in_the_pages_language(name, words):
    page = gc.frozen(name)["report"]["html"]
    for w in words:
        assert w in page
    other = ("has no use" if name.startswith("de") else "keine Verwendung")
    assert other not in page
    # Each figure of the template is a fact element inside the sentence.
    sentence = re.search(r'<span data-fact="lbsim\.finding\.undirected_surplus\.trigger">(.*?)</span></p>', page, re.S)
    assert sentence and 'data-fact="lbsim.finding.undirected_surplus.free"' in sentence.group(1)
    assert "{" not in sentence.group(1)


def test_earning_power_says_whose_level_the_calculation_uses():
    page = gc.frozen("de_outlook")["report"]["html"]
    assert "Ihre Angabe" in page and "Modellwert" in page
    page = gc.frozen("en_outlook")["report"]["html"]
    assert "Your statement" in page and "Model value" in page


@pytest.mark.parametrize("name", ["de_outlook", "de_outlook_real", "de_outlook_plan_update"])
def test_the_plans_figures_are_what_the_calculation_assumes(name):
    page = gc.frozen(name)["report"]["html"]
    box = re.search(r'<div class="box" data-plan="assumes">(.*?)</div>', page, re.S).group(1)
    assert "Was die Rechnung annimmt" in box and "keine Empfehlung" in box
    assert 'data-fact="lbsim.plan.action_now.saving_chf_per_year"' in box
    assert "empfehlen" not in box.lower().replace("keine empfehlung", "")


def test_while_the_plan_runs_the_report_says_so_and_the_update_includes_it():
    calc = gc.frozen("de_outlook_calculating")["report"]
    assert 'data-plan="calculating"' in calc["html"] and "wird berechnet" in calc["html"]
    upd = gc.frozen("de_outlook_plan_update")["report"]
    assert upd["kind"] == "update" and upd["previous_report_id"] == calc["artefact_id"]
    assert upd["sections"][0]["key"] == "changes" and 'data-plan="calculating"' not in upd["html"]
    added = next(f for f in upd["facts"] if f["fact_id"] == "changes.added")
    assert "Sparen" in added["value"] and "Konsum" in added["value"]


def test_the_sources_table_names_lbsims_artefacts_in_words():
    page = gc.frozen("de_outlook")["report"]["html"]
    table = re.search(r'data-section="sources">(.*?)</section>', page, re.S).group(1)
    for words in ("Ihre Befunde und Einkommenspfade", "Ihre simulierten Verläufe", "Ihre Planrechnung"):
        assert words in table
    for doc in (FINDINGS, PATHS, PLAN):
        assert doc["artefact_id"] not in page


# -- the chart functions -----------------------------------------------------------------------------------------

def _fact(fid: str, value: float, display: str) -> Fact:
    return Fact(fact_id=fid, section="roles", label=fid, value=value, unit="share", display=display,
                sources=(FactSource(engine="pcp", artefact_id="PCP-x", contract_version="pcp-allocation@1.0.0",
                                    path="/x"),))


def test_a_weights_chart_draws_one_bar_per_row_and_prints_the_facts():
    svg = charts.weights("roles", [("Wertsteigerung", _fact("a", 0.6, "60,0 %")),
                                   ("Einkommen", _fact("b", 0.0, "0,0 %"))], "Titel", "Beschreibung")
    assert svg.count("<rect") == 1 and '<tspan data-fact="a">60,0 %</tspan>' in svg
    assert '<tspan data-fact="b">0,0 %</tspan>' in svg and "<title>Titel</title>" in svg
    assert charts.weights("roles", [], "t", "d") == ""


def test_the_fan_needs_two_years_and_the_curve_needs_matching_states():
    words = {k: v["de"] for k, v in __import__("report.vocabulary", fromlist=["x"]).CHART_WORDS.items()}
    one = {k: [1.0] for k in ("p05", "p25", "p50", "p75", "p95")}
    assert charts.fan(one, {}, None, None, None, None, False, words, "t", "d", "c") == ""
    assert charts.target_vs_reached([0.1] * 25, [0.1] * 24, words, "t", "d", "c") == ""


def test_the_fan_window_ends_at_the_goal_date():
    from report.contracts import LifeBalancePaths
    paths = LifeBalancePaths.model_validate(PATHS)
    series, last, j = engine.fan_window(paths, "g-home")
    assert (series, last, j) == ("deposit_eligible", 3, 0)
    assert engine.fan_window(paths, "g-ret")[:2] == ("retirement_capital", 27)
    assert engine.fan_window(paths, None)[:2] == ("net_worth", 27)
    assert engine.designated_goal(paths, None, None) == "g-home"


# -- REP-38: the allocation charts in a real report, from lbsim's view of the Allocation -------------------------

@pytest.mark.parametrize("name,word", [("de_outlook_real", "umgerechnet"), ("en_outlook_real", "converted")])
def test_a_real_report_draws_chart_two_from_lbsims_converted_curves(name, word):
    report = gc.frozen(name)["report"]
    by = {f["fact_id"]: f for f in report["facts"]}
    curves = by["lbsim.alloc.curves"]
    assert curves["value"] is True and curves["sources"][0]["engine"] == "lbsim"
    assert curves["sources"][0]["path"] == "/allocation_view/curves/real/derived"
    fit = re.search(r'data-chart="fit">(.*?)</figure>', report["html"], re.S).group(1)
    caption = re.search(r"<figcaption>(.*?)</figcaption>", fit).group(1)
    assert word in caption
    # The drawn line is lbsim's real curve, not pcp's nominal one.
    real = PATHS["allocation_view"]["curves"]["real"]["achieved"]
    nominal = PATHS["allocation_view"]["curves"]["nominal"]["achieved"]
    assert real != nominal
    # Chart 1 states the Allocation's basis; no pcp figure is on a real page.
    roles = re.search(r'data-chart="roles">(.*?)</figure>', report["html"], re.S).group(1)
    assert "<figcaption>" in roles and "nominal" in roles
    assert not any(f.startswith("pcp.") for f in by)
    assert by["lbsim.alloc.basis"]["value"] == "nominal"


def test_a_real_report_without_paths_says_why_chart_two_is_missing(client, served):
    r = client.post("/report", json=request_body(client_ref=CLIENT, sources=[src("lbs", SHEET), src("lbsim", FINDINGS)],
                                                 prose=False, basis="real"))
    assert r.status_code == 200, r.text
    rep = r.json()
    assert 'data-chart="fit"' not in rep["html"] and 'data-chart="roles"' not in rep["html"]
    note = next(f for f in rep["facts"] if f["fact_id"] == "lbsim.alloc.no_real_curve")
    assert note["section"] == "limits" and note["display"] in rep["html"]


def test_a_nominal_report_with_pcp_draws_the_charts_from_pcp():
    by = {f["fact_id"] for f in gc.frozen("de_outlook")["report"]["facts"]}
    assert "pcp.role.Gain" in by and not any(f.startswith("lbsim.alloc.") for f in by)


# -- REP-39: no id on a page with lbsim sources, in the text or in the markup ---------------------------------------

HEX = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32}(?![0-9A-Fa-f])")
IDS = {'"g-home"': '"76658f42c1e04b5e9a3d2b1c0f9e8d7a"', '"g-ret"': '"8a1b2c3d4e5f60718293a4b5c6d7e8f9"',
       '"p1"': '"0a4dc62a87194424a579a12bd149d901"', '"p2"': '"1b5ed73b98205535b68a23ce25a0e012"'}


def _hexed(name: str, renames: dict[str, str]) -> bytes:
    raw = _raw(name).decode("utf-8")
    for old, new in {**IDS, **renames}.items():
        raw = raw.replace(old, new)
    return raw.encode("utf-8")


@pytest.fixture(scope="module")
def hex_pages(client, upstream):
    """B1's samples with the ids the consumer app makes (32 hex), the goals named by the caller."""
    renames = {SHEET["artefact_id"]: "LBS-00000000c0ffee02", FINDINGS["artefact_id"]: "LSF-00000000c0ffee03",
               PATHS["artefact_id"]: "LSP-00000000c0ffee04", PLAN["artefact_id"]: "LSO-00000000c0ffee05"}
    upstream.extra["pcp"][f"/allocation/{ALLOC['artefact_id']}"] = _raw("pcp_allocation_lbsim.json")
    for name, new in (("lbs_sheet_lbsim.json", "LBS-00000000c0ffee02"), ("lbsim_findings.json", "LSF-00000000c0ffee03"),
                      ("lbsim_paths.json", "LSP-00000000c0ffee04"), ("lbsim_plan.json", "LSO-00000000c0ffee05")):
        engine_name = "lbs" if name.startswith("lbs_") else "lbsim"
        upstream.extra[engine_name][f"/artefacts/{new}"] = _hexed(name, renames)
    sources = [src("pcp", ALLOC)] + [{"engine": e, "artefact_id": a} for e, a in (
        ("lbs", "LBS-00000000c0ffee02"), ("lbsim", "LSF-00000000c0ffee03"), ("lbsim", "LSP-00000000c0ffee04"),
        ("lbsim", "LSO-00000000c0ffee05"))]
    named = [{"key": "goal.8a1b2c3d4e5f60718293a4b5c6d7e8f9", "label": "Ziel", "value": "Frei mit sechzig",
              "source": "app"}]
    out = {}
    for lang in ("de", "en"):
        for basis in ("nominal", "real"):
            srcs = sources if basis == "nominal" else sources[1:]
            r = client.post("/report", json=request_body(client_ref=CLIENT, language=lang, sources=srcs, prose=False,
                                                         basis=basis, display_facts=named))
            assert r.status_code == 200, r.text
            out[(lang, basis)] = r.json()
    return out


@pytest.mark.parametrize("lang,basis", [("de", "nominal"), ("en", "nominal"), ("de", "real"), ("en", "real")])
def test_no_32_hex_string_anywhere_on_a_page_with_lbsim_sources(hex_pages, lang, basis):
    rep = hex_pages[(lang, basis)]
    assert HEX.findall(rep["html"]) == []
    ids = {f["fact_id"] for f in rep["facts"]}
    assert "lbsim.path.today.saving_need.goal1" in ids and "lbsim.chance.base.goal2" in ids
    assert "lbsim.earning_power.person1.modelled" in ids and "lbs.human.person1.E" in ids
    # The id stays in the source path's artefact, never in the fact id.
    goal = next(f for f in rep["facts"] if f["fact_id"] == "lbsim.goal.goal1.name")
    assert goal["value"] == "76658f42c1e04b5e9a3d2b1c0f9e8d7a"
    # Only the caller's own naming key carries the id it names (never printed, REP-20).
    assert [f["fact_id"] for f in rep["facts"] if HEX.search(f["fact_id"])] == ["caller.goal.8a1b2c3d4e5f60718293a4b5c6d7e8f9"]


def test_the_income_path_table_names_each_goal(hex_pages):
    page = hex_pages[("de", "nominal")]["html"]
    table = re.search(r'data-section="income_paths">(.*?)</section>', page, re.S).group(1)
    text = re.sub(r"<[^>]+>", " ", table)
    assert "Frei mit sechzig" in text and "Ihr Wohneigentumsziel" in text
    assert "Ihr Ziel" not in text
