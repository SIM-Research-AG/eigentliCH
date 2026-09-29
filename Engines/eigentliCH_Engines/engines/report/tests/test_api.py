"""The HTTP surface against a fresh store, upstream doubles on the frozen artefacts and the spark7 stand-in:
every endpoint, the report and its prose checks, refusals, updates, idempotency and the degraded path."""

from __future__ import annotations

import json

import pytest

from report.contracts import CONTRACT_VERSIONS

from .conftest import CLIENT, FAKE_ENV, INPUTS, LBS_ID, PCP_ID, request_body
from .standin import MODEL, Reply

PCP2 = (INPUTS / "pcp_allocation_2.json").read_bytes()
PCP2_ID = json.loads(PCP2)["artefact_id"]
PROPERTY = (INPUTS / "lbs_sheet_property.json").read_bytes()
PROPERTY_ID = json.loads(PROPERTY)["artefact_id"]


@pytest.fixture(scope="module", autouse=True)
def more_artefacts(upstream):
    upstream.extra["pcp"][f"/allocation/{PCP2_ID}"] = PCP2
    upstream.extra["lbs"][f"/artefacts/{PROPERTY_ID}"] = PROPERTY


def test_standard_endpoints(client, spark):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["engine_version"] == "report@1.3.0"
    meta = client.get("/meta").json()
    assert meta["contract_versions"] == CONTRACT_VERSIONS and meta["allowlist"]["ok"]
    assert meta["prompt_version"] == "report-prompt@1.1.0" and meta["sections"][0] == "changes"
    assert set(meta["upstream"]) == {"pcp", "lbs"}
    contracts = client.get("/contracts").json()
    assert contracts["Report"]["version"] == "report@1.0.0" and contracts["Allocation(pcp)"]["direction"] == "in"
    assert contracts["LifeBalanceSheet(lbs)"]["version"] == "lbs-balance-sheet@1.0.0"
    assert client.get("/calibration").json()["version"] == "1.0.0"
    for path in ("/health", "/meta", "/contracts", "/calibration", "/model"):
        text = client.get(path).text
        assert FAKE_ENV["SPARK7_CLIENT_SECRET"] not in text and FAKE_ENV["SPARK7_CLIENT_ID"] not in text


def test_a_report_with_verified_prose(client, spark):
    r = client.post("/report", json=request_body())
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["complete"] and rep["warnings"] == [] and rep["notice"].endswith("Not investment advice.")
    status = {s["key"]: s["prose_status"] for s in rep["sections"]}
    assert status["balance_sheet"] == status["allocation"] == status["roles"] == "verified"
    assert status["household"] == status["limits"] == status["sources"] == "no_slot"
    assert all(s["prose_model"] == MODEL for s in rep["sections"] if s["prose_status"] == "verified")
    assert rep["provenance"]["model"]["model"] == MODEL
    assert {s["engine"] for s in rep["provenance"]["sources"]} == {"pcp", "lbs"}
    assert 'data-prose="balance_sheet"' in rep["html"] and "Modellbasierte Auswertung. Keine Anlageberatung." in rep["html"]
    # one model call per section with a slot, each with only that section's figures
    prompts = [c["body"]["messages"][-1]["content"] for c in spark.chat_requests()]
    assert len(prompts) == sum(1 for s in rep["sections"] if s["prose_status"] == "verified")
    balance = next(p for p in prompts if "Die Bilanz" in p)
    assert "Reinvermögen" in balance and "Wertsteigerung" not in balance and "Muster" not in balance
    assert client.get(f"/artefacts/{rep['artefact_id']}").json() == rep
    html = client.get(f"/reports/{rep['artefact_id']}/html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")


def test_an_invented_figure_withholds_the_prose_and_says_why(client, spark):
    spark.responder = lambda body: Reply(content=(
        "Das Reinvermögen beträgt CHF 1 250 001, und der grösste Teil davon ist in Realwerten gebunden, "
        "nicht frei verfügbar."))
    rep = client.post("/report", json=request_body(language="de", display_facts=[
        {"key": "name", "label": "Kundin", "value": "Erfunden", "source": "test"}])).json()
    bal = next(s for s in rep["sections"] if s["key"] == "balance_sheet")
    assert bal["prose_status"] == "flagged" and bal["unverified_numbers"] == ["1 250 001"]
    assert bal["prose_attempts"] == 2 and bal["prose"] and 'data-prose="balance_sheet"' not in rep["html"]
    assert rep["complete"] and any("withheld" in w for w in rep["warnings"])


def test_a_draft_that_advises_is_rejected_and_redrafted(client, spark):
    from .conftest import echo

    replies = iter([Reply(content="Sie sollten Ihr Vermögen umschichten, weil die Realwerte zu gross sind und das "
                                  "Risiko hoch ist.")])

    def responder(body):
        return next(replies, None) or echo(body)

    spark.responder = responder
    rep = client.post("/report", json=request_body(display_facts=[])).json()
    first = next(s for s in rep["sections"] if s["prose_status"] != "no_slot")
    assert first["prose_status"] == "verified" and first["prose_attempts"] == 2


def test_prose_off(client, spark):
    rep = client.post("/report", json=request_body(prose=False)).json()
    assert rep["complete"] and all(s["prose_status"] == "not_requested" for s in rep["sections"])
    assert rep["provenance"]["model"] is None and spark.chat_requests() == []


def test_spark7_down_the_report_stands_without_prose_and_is_not_cached(client, spark, standin):
    spark.responder = lambda body: Reply(status=524)
    body = request_body(display_facts=[{"key": "name", "label": "Kundin", "value": "Ausfall", "source": "t"}])
    first = client.post("/run", json=body).json()
    rep = client.get(f"/artefacts/{first['artefact_id']}").json()
    assert first["status"] == "succeeded" and not rep["complete"]
    assert "524" in rep["warnings"][0] and "asking again tries again" in rep["warnings"][0]
    assert all(s["prose_status"] in ("unavailable", "no_slot") for s in rep["sections"])
    assert len(spark.chat_requests()) == 1, "after the first failure the other sections do not call again"
    assert 'data-meta="warnings"' in rep["html"]
    spark.responder = None
    from .conftest import echo
    spark.responder = echo
    second = client.post("/run", json=body).json()
    assert not second["cached"] and second["artefact_id"] != first["artefact_id"]
    assert client.get(f"/artefacts/{second['artefact_id']}").json()["complete"]
    third = client.post("/run", json=body).json()
    assert third["cached"] and third["artefact_id"] == second["artefact_id"]


def test_a_repeat_is_answered_from_the_store(client, spark):
    body = request_body(display_facts=[{"key": "name", "label": "Kundin", "value": "Wiederholung", "source": "t"}])
    a = client.post("/run", json=body).json()
    calls = len(spark.chat_requests())
    b = client.post("/run", json=body).json()
    assert b["cached"] and b["artefact_id"] == a["artefact_id"] and len(spark.chat_requests()) == calls


def test_every_input_enters_the_key(client, spark):
    base = request_body(prose=False, display_facts=[])
    keys = {client.post("/run", json=b).json()["idempotency_key"] for b in (
        base, {**base, "language": "en"}, {**base, "sources": base["sources"][:1]},
        {**base, "display_facts": [{"key": "k", "label": "l", "value": "v", "source": "s"}]},
        {**base, "prose": True})}
    assert len(keys) == 5


def test_an_update_states_what_changed(client, spark):
    first = client.post("/report", json=request_body(prose=False)).json()
    body = request_body(kind="update", previous_report_id=first["artefact_id"], prose=True,
                        sources=[{"engine": "pcp", "artefact_id": PCP2_ID}, {"engine": "lbs", "artefact_id": LBS_ID}])
    upd = client.post("/report", json=body).json()
    assert upd["kind"] == "update" and upd["sections"][0]["key"] == "changes"
    changes = {f["fact_id"]: f for f in upd["facts"] if f["section"] == "changes"}
    gain = changes["change.pcp.role.Gain"]
    assert gain["previous"] < gain["value"] and {s["artefact_id"] for s in gain["sources"]} == {first["artefact_id"], PCP2_ID}
    assert "change.lbs.totals.net_worth" not in changes and changes["changes.unchanged"]["value"] > 0
    assert upd["sections"][0]["prose_status"] == "verified"
    assert upd["provenance"]["previous_report_id"] == first["artefact_id"]
    assert "Update zum Bericht" in upd["html"]
    listed = client.get("/reports", params={"client_ref": CLIENT}).json()
    assert {first["artefact_id"], upd["artefact_id"]} <= {r["artefact_id"] for r in listed}


@pytest.mark.parametrize("over,needle", [
    ({"sources": [{"engine": "pcp", "artefact_id": "PCP-0000000000000000"}]}, "has no artefact"),
    ({"client_ref": "someone-else"}, "another client's artefact"),
    ({"kind": "update", "previous_report_id": "REP-0000000000000000"}, "does not exist"),
])
def test_refusals_name_their_reason(client, spark, over, needle):
    r = client.post("/report", json=request_body(prose=False, **over))
    assert r.status_code == 422 and needle in r.json()["detail"]["error"]
    assert client.get(f"/runs/{r.json()['detail']['run_id']}").json()["status"] == "failed"


def test_an_update_against_another_clients_report_is_refused(client, spark):
    other = client.post("/report", json=request_body(prose=False, client_ref="other-client",
                                                     sources=[{"engine": "pcp", "artefact_id": PCP_ID}])).json()
    r = client.post("/report", json=request_body(prose=False, kind="update", previous_report_id=other["artefact_id"]))
    assert r.status_code == 422 and "another client" in r.json()["detail"]["error"]


def test_an_upstream_engine_down_is_503(client, spark, upstream):
    upstream.down.add("lbs")
    try:
        r = client.post("/report", json=request_body(prose=False, display_facts=[
            {"key": "k", "label": "l", "value": "down", "source": "s"}]))
        assert r.status_code == 503 and "lbs is unreachable" in r.json()["detail"]["error"]
        run = client.post("/run", json=request_body(prose=False, display_facts=[
            {"key": "k", "label": "l", "value": "down", "source": "s"}])).json()
        assert run["status"] == "failed"
    finally:
        upstream.down.discard("lbs")


def test_an_artefact_breaking_its_contract_is_refused(client, spark, upstream):
    broken = json.loads(PCP2)
    broken["artefact_id"] = "PCP-brokenbroken0001"
    broken["release_state"] = "released"
    upstream.extra["pcp"]["/allocation/PCP-brokenbroken0001"] = json.dumps(broken).encode()
    r = client.post("/report", json=request_body(prose=False, sources=[{"engine": "pcp",
                                                                        "artefact_id": "PCP-brokenbroken0001"}]))
    assert r.status_code == 503 and "breaks pcp-allocation@1.0.0" in r.json()["detail"]["error"]


def test_english_report_on_one_source(client, spark):
    rep = client.post("/report", json=request_body(language="en", sources=[{"engine": "lbs", "artefact_id": PROPERTY_ID}],
                                                   client_ref=json.loads(PROPERTY)["client_ref"],
                                                   display_facts=[])).json()
    keys = [s["key"] for s in rep["sections"]]
    assert "property" in keys and "allocation" not in keys
    assert "Model-derived research output. Not investment advice." in rep["html"] and rep["language"] == "en"


@pytest.mark.parametrize("bad", [{"kind": "update"}, {"sources": []}, {"language": "fr"}, {"client_ref": "bad ref!"},
                                 {"sources": [{"engine": "pcp", "artefact_id": "a"}, {"engine": "pcp", "artefact_id": "b"}]},
                                 {"sources": [{"engine": "mrs", "artefact_id": "a"}]}])
def test_a_request_breaking_its_contract_is_422(client, bad):
    assert client.post("/report", json={**request_body(), **bad}).status_code == 422


def test_calibration_is_append_only_through_the_api(client):
    cal = client.get("/calibration").json()
    assert client.put("/calibration", json=cal).status_code == 200
    changed = {**cal, "position_min_weight": 0.01}
    assert client.put("/calibration", json=changed).status_code == 409
    assert client.put("/calibration", json={**changed, "version": "1.0.1", "parent_version": "1.0.0"}).status_code == 201


def test_runs_and_unknowns(client, spark):
    run = client.post("/run", json=request_body(prose=False)).json()
    assert any(r["run_id"] == run["run_id"] for r in client.get("/runs").json())
    assert client.get(f"/runs/{run['run_id']}").json()["provenance"]["idempotency_key"] == run["idempotency_key"]
    assert client.get("/artefacts/REP-0000000000000000").status_code == 404
    assert client.get("/reports/REP-0000000000000000/html").status_code == 404


# -- revisions (REP-25) -------------------------------------------------------------------------------------------

NOTE = "Bitte die Reserve von 45 000 Franken zuerst sichern und das Mandat danach neu rechnen. Die Kuratorin"


def test_a_revision_is_a_distinct_report_with_the_curators_remark(client, spark):
    """The bug of 29.09.2026: a revision sent with the same sources was answered from the cache, so the revised
    report was the first one again. The revision fields enter the key; the remark is printed, as a fact."""
    body = request_body(prose=False, display_facts=[{"key": "name", "label": "Kundin", "value": "Revision",
                                                      "source": "t"}])
    first = client.post("/run", json=body).json()
    revised = client.post("/run", json={**body, "revision_of": first["artefact_id"], "revision_note": NOTE}).json()
    assert not revised["cached"] and revised["artefact_id"] != first["artefact_id"]
    assert revised["idempotency_key"] != first["idempotency_key"]
    rep = client.get(f"/artefacts/{revised['artefact_id']}").json()
    assert rep["revision_of"] == first["artefact_id"] and rep["revision_note"] == NOTE
    remark = next(f for f in rep["facts"] if f["fact_id"] == "caller.revision_note")
    assert remark["value"] == NOTE and remark["sources"][0]["engine"] == "caller"
    assert remark["sources"][0]["path"] == "/revision_note"
    assert remark["sources"][0]["artefact_id"] == rep["provenance"]["request_id"]
    box = rep["html"].split('data-meta="revision"', 1)[1].split("</div>", 1)[0]
    assert "Anmerkung der Kuratorin oder des Kurators" in box and "überarbeitet einen früheren Bericht" in box
    assert f'<span data-fact="caller.revision_note">{NOTE}</span>' in box
    assert first["artefact_id"] not in rep["html"], "no id on the page (REP-23)"
    assert 'data-meta="revision"' not in client.get(f"/artefacts/{first['artefact_id']}").json()["html"]

    # The same revision again is the same artefact; another remark is another one.
    again = client.post("/run", json={**body, "revision_of": first["artefact_id"], "revision_note": NOTE}).json()
    assert again["cached"] and again["artefact_id"] == revised["artefact_id"]
    other = client.post("/run", json={**body, "revision_of": first["artefact_id"],
                                      "revision_note": NOTE + " Danke."}).json()
    assert not other["cached"] and other["artefact_id"] not in (first["artefact_id"], revised["artefact_id"])


def test_the_revision_remark_is_in_the_reports_language_and_never_reaches_the_model(client, spark):
    first = client.post("/report", json=request_body(language="en", prose=False)).json()
    note = "Please keep the reserve of 45,000 francs first. The curator"
    rep = client.post("/report", json=request_body(language="en", prose=True, revision_of=first["artefact_id"],
                                                   revision_note=note)).json()
    box = rep["html"].split('data-meta="revision"', 1)[1].split("</div>", 1)[0]
    assert "The curator&#x27;s remark" in box and "This version revises an earlier report." in box
    assert "Kurator" not in box
    sent = json.dumps(spark.chat_requests(), ensure_ascii=False)
    assert spark.chat_requests() and "reserve of 45,000" not in sent and "curator" not in sent.lower()


def test_a_request_without_revision_fields_keeps_its_request_id():
    """Additive: the two fields are left out of the request id when absent, so every earlier request keeps its
    id and its key."""
    from report import engine
    from report.contracts import ReportRequest
    from report.service import Service

    req = ReportRequest.model_validate(request_body())
    before = engine.content_id("RRQ", {k: v for k, v in req.model_dump(mode="json").items()
                                       if k not in ("calibration_version", "revision_of", "revision_note", "basis")})
    assert Service.request_id(req) == before
    with_note = ReportRequest.model_validate(request_body(revision_of="REP-0000000000000000", revision_note="x y"))
    assert Service.request_id(with_note) != before


@pytest.mark.parametrize("over,needle", [
    ({"revision_note": "Bitte neu rechnen."}, "name revision_of"),
    ({"revision_of": "REP-0000000000000000", "revision_note": "   "}, "must not be blank"),
    ({"revision_of": "REP-0000000000000000", "revision_note": "Bitte neu."}, "does not exist"),
])
def test_revision_refusals_name_their_reason(client, spark, over, needle):
    r = client.post("/report", json=request_body(prose=False, **over))
    assert r.status_code == 422 and needle in json.dumps(r.json(), ensure_ascii=False)


def test_a_revision_of_another_clients_report_is_refused(client, spark):
    other = client.post("/report", json=request_body(prose=False, client_ref="revision-other",
                                                     sources=[{"engine": "pcp", "artefact_id": PCP_ID}])).json()
    r = client.post("/report", json=request_body(prose=False, revision_of=other["artefact_id"], revision_note="x y"))
    assert r.status_code == 422 and "another client" in r.json()["detail"]["error"]
