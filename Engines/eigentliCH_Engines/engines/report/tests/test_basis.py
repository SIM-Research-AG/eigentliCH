"""The nominal and real view (REP-27 to REP-29): the request's ``basis``, the key, the page, the refusals.

On frozen artefacts: lbs sheets built by lbs's own code under its calibration 1.4.0 (``lbs_sheet_real.json``,
``lbs_sheet_property_real.json``, each with its ``real_view``) and a stand-in for pcp's real Allocation
(``pcp_allocation_real.json``), beside the nominal inputs the other tests use (``dev/freeze_inputs.py --real``).
"""

from __future__ import annotations

import json
import re

import pytest

from report import engine
from report import vocabulary as voc
from report.calibration import PRODUCTION as CAL
from report.contracts import Allocation, LifeBalanceSheet, Report, ReportRequest
from report.service import Service

from . import golden_cases as gc
from .conftest import CLIENT, INPUTS, LBS_ID, PCP_ID, request_body

PCP_REAL = (INPUTS / "pcp_allocation_real.json").read_bytes()
LBS_REAL = (INPUTS / "lbs_sheet_real.json").read_bytes()
PROPERTY_REAL = (INPUTS / "lbs_sheet_property_real.json").read_bytes()
PCP_REAL_ID = json.loads(PCP_REAL)["artefact_id"]
LBS_REAL_ID = json.loads(LBS_REAL)["artefact_id"]
PROPERTY_REAL_ID = json.loads(PROPERTY_REAL)["artefact_id"]
PROPERTY_CLIENT = json.loads(PROPERTY_REAL)["client_ref"]

NOMINAL_SOURCES = [{"engine": "pcp", "artefact_id": PCP_ID}, {"engine": "lbs", "artefact_id": LBS_REAL_ID}]
REAL_SOURCES = [{"engine": "pcp", "artefact_id": PCP_REAL_ID}, {"engine": "lbs", "artefact_id": LBS_REAL_ID}]


@pytest.fixture(scope="module", autouse=True)
def real_artefacts(upstream):
    upstream.extra["pcp"][f"/allocation/{PCP_REAL_ID}"] = PCP_REAL
    upstream.extra["lbs"][f"/artefacts/{LBS_REAL_ID}"] = LBS_REAL
    upstream.extra["lbs"][f"/artefacts/{PROPERTY_REAL_ID}"] = PROPERTY_REAL


def _report(client, **over) -> dict:
    r = client.post("/report", json=request_body(prose=False, **over))
    assert r.status_code == 200, r.text
    return r.json()


def _refused(client, **over) -> str:
    r = client.post("/report", json=request_body(prose=False, **over))
    assert r.status_code == 422, r.text
    return r.json()["detail"]["error"]


# -- the request and the key ------------------------------------------------------------------------------------

def test_a_request_without_basis_keeps_its_request_id():
    """``RRQ-cf68ec90594ccb16`` is the id of the golden de_full request before the field existed (engine 1.2.0)."""
    body = dict(next(c for c in gc.cases() if c["name"] == "de_full")["request"])
    assert Service.request_id(ReportRequest.model_validate(body)) == "RRQ-cf68ec90594ccb16"
    assert Service.request_id(ReportRequest.model_validate({**body, "basis": "nominal"})) == "RRQ-cf68ec90594ccb16"
    assert Service.request_id(ReportRequest.model_validate({**body, "basis": "real"})) != "RRQ-cf68ec90594ccb16"
    assert ReportRequest.model_validate(body).basis == "nominal"


def test_the_basis_enters_the_key(client, spark):
    base = request_body(prose=False, display_facts=[], sources=REAL_SOURCES[1:])
    nominal = client.post("/run", json=base).json()
    explicit = client.post("/run", json={**base, "basis": "nominal"}).json()
    real = client.post("/run", json={**base, "basis": "real"}).json()
    assert nominal["status"] == explicit["status"] == real["status"] == "succeeded"
    assert nominal["idempotency_key"] == explicit["idempotency_key"] and explicit["cached"]
    assert real["idempotency_key"] != nominal["idempotency_key"] and real["artefact_id"] != nominal["artefact_id"]


def test_a_request_with_an_unknown_basis_is_422(client):
    assert client.post("/report", json=request_body(basis="nominell")).status_code == 422


# -- the page ---------------------------------------------------------------------------------------------------

def _marked(report: dict) -> None:
    """Every fact with a basis is printed with its basis next to it; no fact without one is."""
    page = report["html"]
    for f in report["facts"]:
        if f["basis"]:
            assert re.search(rf'data-fact="{re.escape(f["fact_id"])}">[^<]*</span> <small class="basis" '
                             rf'data-basis="{f["basis"]}">', page), f["fact_id"]
    marks = re.findall(r'data-fact="([^"]+)">[^<]*</(?:span|b)> <small class="basis"', page)
    assert set(marks) <= {f["fact_id"] for f in report["facts"] if f["basis"]}


def test_a_nominal_report_says_so_in_the_header_and_next_to_every_return_and_goal_figure(client, spark):
    rep = _report(client, sources=NOMINAL_SOURCES)
    assert rep["basis"] == "nominal"
    assert '<span data-basis="nominal">Alle Beträge nominal, gerundet.</span>' in rep["html"]
    facts = {f["fact_id"]: f for f in rep["facts"]}
    for fid in ("lbs.mandate.target", "lbs.mandate.required_return", "lbs.mandate.contribution"):
        assert facts[fid]["basis"] == "nominal", fid
    # Nominal reads lbs's top-level figures, the paths a nominal report always cited.
    assert facts["lbs.mandate.target"]["sources"][0]["path"] == "/mandate_proposal/target_chf"
    assert "lbs.real.inflation" not in facts and "pcp.basis" not in facts
    _marked(rep)


def test_a_real_report_takes_lbss_real_figures_and_says_so(client, spark):
    raw = json.loads(LBS_REAL)
    rep = _report(client, sources=REAL_SOURCES, basis="real")
    assert rep["basis"] == "real"
    assert "Alle Beträge in heutigen Franken (real), gerundet." in rep["html"]
    facts = {f["fact_id"]: f for f in rep["facts"]}
    real = raw["mandate_proposal"]["views"]["real"]
    assert facts["lbs.mandate.target"]["value"] == real["target_chf"] != raw["mandate_proposal"]["target_chf"]
    assert facts["lbs.mandate.target"]["sources"][0]["path"] == "/mandate_proposal/views/real/target_chf"
    assert facts["lbs.mandate.required_return"]["value"] == real["required_return"]
    assert facts["lbs.mandate.required_return"]["basis"] == facts["lbs.mandate.target"]["basis"] == "real"
    # What lbs gives only in nominal is shown as lbs states it, marked nominal, and the header says what that means.
    assert raw["real_view"]["contribution_indexed"] is False and facts["lbs.mandate.contribution"]["basis"] == "nominal"
    assert voc.BASIS_NOMINAL_KEPT["de"] in rep["html"]
    assert facts["lbs.real.inflation"]["value"] == raw["real_view"]["inflation"]["annual_rate"]
    assert facts["pcp.basis"]["display"] == "real, teuerungsbereinigt"
    _marked(rep)


def test_an_english_real_report_on_the_property_sheet(client, spark):
    raw = json.loads(PROPERTY_REAL)
    rep = _report(client, client_ref=PROPERTY_CLIENT, language="en", basis="real", display_facts=[],
                  sources=[{"engine": "lbs", "artefact_id": PROPERTY_REAL_ID}])
    assert "All amounts in today’s francs (real), rounded." in rep["html"]
    price = next(f for f in rep["facts"] if f["fact_id"].endswith(".price"))
    # From lbs 1.4.0 the top-level price is in today's francs (``basis: real``).
    assert raw["property"][0]["basis"] == "real" and price["value"] == raw["property"][0]["price_chf"]
    assert price["basis"] == "real" and '<small class="basis" data-basis="real">real</small>' in rep["html"]
    nominal = _report(client, client_ref=PROPERTY_CLIENT, language="en", display_facts=[],
                      sources=[{"engine": "lbs", "artefact_id": PROPERTY_REAL_ID}])
    price_n = next(f for f in nominal["facts"] if f["fact_id"].endswith(".price"))
    assert price_n["value"] == raw["real_view"]["goals"][0]["nominal"]["amount"] > price["value"]
    assert price_n["sources"][0]["path"] == "/real_view/goals/0/nominal/amount"
    assert "All amounts nominal, rounded." in nominal["html"]


def test_the_real_prompt_tells_the_model_the_basis(client, spark):
    rep = client.post("/report", json=request_body(sources=REAL_SOURCES, basis="real")).json()
    assert rep["complete"], rep["warnings"]
    mandate = next(q["body"]["messages"][-1]["content"] for q in spark.chat_requests()
                   if "Mandatsvorschlag" in q["body"]["messages"][-1]["content"])
    assert "(real)" in mandate and voc.BASIS_PROMPT["real"]["de"].strip() in mandate
    assert any(s["key"] == "mandate" and s["prose_status"] == "verified" for s in rep["sections"])


# -- a mix is refused --------------------------------------------------------------------------------------------

def test_a_real_report_on_a_nominal_allocation_is_refused(client, spark):
    error = _refused(client, basis="real", sources=NOMINAL_SOURCES)
    assert f"pcp allocation {PCP_ID} is nominal" in error and "never mixes" in error and "basis=real" in error


def test_a_nominal_report_on_a_real_allocation_is_refused(client, spark):
    error = _refused(client, sources=REAL_SOURCES)
    assert f"pcp allocation {PCP_REAL_ID} is real" in error and "never mixes" in error


def test_a_real_report_on_a_sheet_without_a_real_view_is_refused(client, spark):
    error = _refused(client, basis="real", sources=[{"engine": "pcp", "artefact_id": PCP_REAL_ID},
                                                    {"engine": "lbs", "artefact_id": LBS_ID}])
    assert f"lbs sheet {LBS_ID} carries nominal figures only" in error and "real view" in error


def test_a_real_figure_that_says_nominal_is_refused(client, spark, upstream):
    raw = json.loads(LBS_REAL)
    raw["mandate_proposal"]["views"]["real"]["basis"] = "nominal"
    raw["artefact_id"] = "LBS-00000000000ba515"
    upstream.extra["lbs"][f"/artefacts/{raw['artefact_id']}"] = json.dumps(raw).encode("utf-8")
    error = _refused(client, basis="real", sources=[REAL_SOURCES[0], {"engine": "lbs", "artefact_id": raw["artefact_id"]}])
    assert "/mandate_proposal/views/real/target_chf is nominal, read as real" in error and "never mixes" in error


def test_an_update_across_bases_is_refused(client, spark):
    first = _report(client, sources=NOMINAL_SOURCES)
    error = _refused(client, kind="update", basis="real", sources=REAL_SOURCES,
                     previous_report_id=first["artefact_id"])
    assert "is nominal and this update is asked in real" in error
    same = _report(client, kind="update", basis="real", sources=REAL_SOURCES,
                   previous_report_id=_report(client, sources=REAL_SOURCES, basis="real")["artefact_id"])
    assert same["basis"] == "real" and same["sections"][0]["key"] == "changes"


# -- the extractor ------------------------------------------------------------------------------------------------

def _retirement_sheet() -> dict:
    """The real couple sheet with a retirement finding as lbs 1.4.0 writes it: top-level figures in today's
    francs (``basis: real``) and both views."""
    raw = json.loads(LBS_REAL)
    raw["retirement"] = [{"goal_id": "g9", "verdict": "does_not_meet", "needs_per_year": 90000.0,
                          "target_date": "2039-01-01", "undetermined_because": [], "caveats": [], "ahv": None,
                          "pillar2": None, "covered_per_year": 70000.0, "shortfall_per_year": 20000.0, "basis": "real",
                          "views": {b: {"basis": b, "as_at": None if b == "real" else "2039-01-01",
                                        "needs_per_year": 90000.0 * k, "ahv_per_year": None, "bvg_per_year": None,
                                        "covered_per_year": 70000.0 * k, "shortfall_per_year": 20000.0 * k}
                                    for b, k in (("real", 1.0), ("nominal", 1.1))}}]
    return raw


@pytest.mark.parametrize("basis,factor,path", [("nominal", 1.1, "/retirement/0/views/nominal/needs_per_year"),
                                               ("real", 1.0, "/retirement/0/needs_per_year")])
def test_a_retirement_finding_in_both_bases(basis, factor, path):
    sheet = LifeBalanceSheet.model_validate(_retirement_sheet())
    facts = {f.fact_id: f for f in engine.extract_lbs(sheet, CAL, "de", basis)}
    needs = facts["lbs.retirement.g9.needs"]
    assert needs.value == pytest.approx(90000.0 * factor) and needs.basis == basis
    assert needs.sources[0].path == path


def test_a_real_top_level_figure_without_its_nominal_view_is_refused_in_nominal():
    raw = _retirement_sheet()
    raw["retirement"][0]["views"] = None
    with pytest.raises(engine.EngineError, match="in real only, not in nominal"):
        engine.extract_lbs(LifeBalanceSheet.model_validate(raw), CAL, "de", "nominal")


def test_an_allocation_without_basis_counts_as_nominal():
    raw = json.loads((INPUTS / "pcp_allocation.json").read_bytes())
    assert "basis" not in raw and engine.allocation_basis(Allocation.model_validate(raw)) == "nominal"
    assert engine.allocation_basis(Allocation.model_validate({**raw, "basis": "nominal"})) == "nominal"
    assert engine.allocation_basis(Allocation.model_validate_json(PCP_REAL)) == "real"


def test_a_report_stored_before_the_basis_reads_as_nominal():
    stored = json.loads(json.dumps(gc.frozen("de_full")["report"]))
    stored.pop("basis")
    for f in stored["facts"]:
        f.pop("basis")
    assert Report.model_validate(stored).basis == "nominal"


def test_the_client_of_every_real_input_is_the_nominal_ones():
    assert json.loads(LBS_REAL)["client_ref"] == CLIENT
