"""The HTTP surface against a fresh store and the spark7 stand-in: every endpoint, the answer and its checks,
the refusals, idempotency, failure handling, routing of client facts and the redrafts."""

from __future__ import annotations

import json

import pytest

from chatbot.contracts import CONTRACT_VERSIONS

from .conftest import FAKE_ENV, request_body
from .standin import MODEL, Reply, answer_json

GOOD = answer_json("Mit Pensionskasse dürfen Sie 2026 höchstens CHF 7'258 pro Jahr in die Säule 3a einzahlen.",
                   ["N1"])


def test_standard_endpoints(client, spark):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["engine_version"] == "chatbot@1.2.0"
    assert health["model_display_name"] == "MiniMind"
    meta = client.get("/meta").json()
    assert meta["contract_versions"] == CONTRACT_VERSIONS and meta["allowlist"]["ok"]
    assert meta["calibration_version"] == "1.1.0" and meta["prompt_version"] == "chatbot-prompt@1.2.0"
    assert meta["model"]["model"] == MODEL and meta["model"]["headers_from_env"]["CF-Access-Client-Id"]["set"]
    assert meta["model"]["display_name"] == "MiniMind" and meta["model"]["service"] == "spark7"
    contracts = client.get("/contracts").json()
    assert contracts["ChatRequest"]["version"] == "chat-request@1.0.0"
    assert contracts["ChatAnswer"]["direction"] == "out" and contracts["ChatRequest"]["direction"] == "in"
    assert client.get("/calibration").json()["version"] == "1.1.0"
    versions = client.get("/calibration/versions").json()
    assert [v["version"] for v in versions] == ["1.0.0", "1.1.0"] and [v["active"] for v in versions] == [False, True]


def test_no_endpoint_shows_the_token(client, spark):
    spark.queue(Reply(content=GOOD))
    client.post("/answer", json=request_body(question="Token-Probe: Wie viel darf ich 2026 einzahlen?"))
    for path in ("/health", "/meta", "/contracts", "/runs", "/model", "/calibration"):
        text = client.get(path).text
        assert FAKE_ENV["SPARK7_CLIENT_SECRET"] not in text and FAKE_ENV["SPARK7_CLIENT_ID"] not in text, path


def test_a_grounded_answer(client, spark):
    spark.queue(Reply(content=GOOD))
    r = client.post("/answer", json=request_body())
    assert r.status_code == 200, r.text
    a = r.json()
    assert not a["refused"] and a["cited_ids"] == ["N1"] and a["unverified_numbers"] == []
    assert [n["text"] for n in a["numbers"]] == ["2026", "7'258"]
    assert all(n["matched"] for n in a["numbers"])
    assert a["model"] == MODEL and a["prompt_version"] == "chatbot-prompt@1.2.0" and a["latency_ms"] > 0
    assert a["route"] == "client_situation" and a["notice"].endswith("Not investment advice.")
    assert a["basis"] == "grounded" and a["model_display_name"] == "MiniMind" and "MiniMind" in a["notice"]
    assert "Allgemeine Einschätzung" not in a["answer"]
    p = a["provenance"]
    assert p["grounding_ids"] == ["N1", "N2"] and p["model"]["attempts"] == 1 and p["label"] == "model-derived"
    assert client.get(f"/artefacts/{a['artefact_id']}").json() == a
    sent = spark.chat_requests()[0]["body"]
    assert sent["response_format"]["type"] == "json_schema" and sent["temperature"] == 0.0
    assert "[N1] Säule 3a" in sent["messages"][-1]["content"]


def test_an_invented_figure_is_listed(client, spark):
    spark.queue(Reply(content=answer_json("Der Betrag steigt 2027 auf CHF 7'400.", ["N1"])))
    a = client.post("/answer", json=request_body(question="Steigt der Betrag?")).json()
    assert a["unverified_numbers"] == ["2027", "7'400"] and not a["refused"]
    assert any("match no source" in w for w in a["warnings"])


LABEL = "Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:"


def test_a_question_the_notes_do_not_cover_is_answered_from_general_knowledge(client, spark):
    """Until calibration 1.1.0 this question was refused (``not_covered``). The owner withdrew that on 29.09.2026
    (CHB-18): it is answered, marked as a general assessment, and cites no note."""
    spark.queue(Reply(content=answer_json("", [], general="Den Leitzins legt die Nationalbank vierteljährlich fest.")))
    a = client.post("/answer", json=request_body(question="Wie hoch ist der Leitzins der SNB?")).json()
    assert not a["refused"] and a["refusal_code"] is None and a["basis"] == "general" and a["cited_ids"] == []
    assert a["answer"] == LABEL + "\nDen Leitzins legt die Nationalbank vierteljährlich fest."
    assert any("general assessment" in w for w in a["warnings"]) and a["model"] == MODEL


def test_no_grounding_is_answered_from_general_knowledge(client, spark):
    """Until calibration 1.1.0 an empty grounding was refused without a model call (``no_grounding``); since
    CHB-18 the model is asked, is told there are no notes, and its answer is marked as general."""
    spark.queue(Reply(content=answer_json("", [], general="Die AHV ist die erste Säule der Vorsorge.")))
    a = client.post("/answer", json=request_body(question="Was gilt bei der AHV?", grounding=[])).json()
    assert not a["refused"] and a["basis"] == "general" and a["answer"].startswith(LABEL)
    assert a["provenance"]["model"] is not None and len(spark.chat_requests()) == 1
    assert spark.chat_requests()[0]["body"]["messages"][-1]["content"].startswith("UNTERLAGEN:\nkeine")
    assert any("no grounding notes were sent" in w for w in a["warnings"])


def test_a_partly_covered_question_cites_what_is_covered_and_marks_the_rest(client, spark):
    spark.queue(Reply(content=answer_json("Mit Pensionskasse dürfen Sie 2026 höchstens CHF 7'258 einzahlen.", ["N1"],
                                          general="Eröffnen Sie zuerst ein Vorsorgekonto.")))
    a = client.post("/answer", json=request_body(question="Wie viel darf ich 2026 einzahlen und wie beginne ich?")).json()
    assert a["basis"] == "mixed" and a["cited_ids"] == ["N1"] and a["unverified_numbers"] == []
    assert a["answer"] == ("Mit Pensionskasse dürfen Sie 2026 höchstens CHF 7'258 einzahlen.\n\n" + LABEL
                           + "\nEröffnen Sie zuerst ein Vorsorgekonto.")


def test_a_number_in_the_general_part_is_checked_too(client, spark):
    """No invented client figure: the client's own numbers verify only against the client facts."""
    facts = [{"key": "income", "label": "Erwerbseinkommen", "value": 98500.0, "source": "onboarding"}]
    spark.queue(Reply(content=answer_json("", [], general="Bei Ihrem Einkommen von CHF 98'500 und Ihrem Vermögen "
                                                          "von CHF 250'000 lohnt sich eine Weiterbildung.")))
    a = client.post("/answer", json=request_body(question="Wie kann ich mein Einkommen steigern?", grounding=[],
                                                  client_facts=facts)).json()
    assert a["unverified_numbers"] == ["250'000"] and not a["refused"] and a["basis"] == "general"
    assert a["numbers"][0]["matched"] == ["fact:income"]


def test_a_question_outside_the_domain_is_refused(client, spark):
    spark.queue(Reply(content=answer_json("", [], status="out_of_domain")))
    a = client.post("/answer", json=request_body(question="Wie backe ich einen Zopf?", grounding=[])).json()
    assert a["refused"] and a["refusal_code"] == "not_covered" and a["refusal_reason"].startswith("out_of_domain")
    assert a["basis"] is None and a["answer"].startswith("Diese Frage liegt ausserhalb dessen, wobei MiniMind")


def test_a_question_without_a_word_is_refused_without_a_model_call(client, spark):
    a = client.post("/answer", json=request_body(question="??? !!!", grounding=[])).json()
    assert a["refused"] and a["refusal_code"] == "not_covered" and a["refusal_reason"].startswith("unintelligible")
    assert a["model"] is None and a["provenance"]["model"] is None and spark.chat_requests() == []
    assert "MiniMind" in a["answer"]


def test_a_question_the_model_cannot_understand_is_refused(client, spark):
    spark.queue(Reply(content=answer_json("", [], status="unintelligible")))
    a = client.post("/answer", json=request_body(question="Blau quer Montag hinten?", grounding=[])).json()
    assert a["refused"] and a["refusal_reason"].startswith("unintelligible") and a["model"] == MODEL


def test_calibration_1_0_0_is_not_run_any_more(client, spark):
    """1.0.0 refused for lack of grounding; it stays in the store as history and is refused as a request."""
    r = client.post("/answer", json={**request_body(), "calibration_version": "1.0.0"})
    assert r.status_code == 422 and "CHB-18" in r.text and spark.chat_requests() == []


def test_english(client, spark):
    spark.queue(Reply(content=answer_json("The reference age is 65 [N2].", ["N2"])))
    a = client.post("/answer", json=request_body(question="What is the AHV reference age?", language="en")).json()
    assert a["answer"] == "The reference age is 65." and a["cited_ids"] == ["N2"] and a["unverified_numbers"] == []
    assert "Rules without exception" in spark.chat_requests()[0]["body"]["messages"][0]["content"]


def test_a_repeat_is_answered_from_the_store_without_the_model(client, spark):
    body = request_body(question="Wiederholung: Wie viel darf ich 2026 einzahlen?")
    spark.queue(Reply(content=GOOD))
    first = client.post("/run", json=body).json()
    second = client.post("/run", json=body).json()
    assert first["status"] == "succeeded" and not first["cached"]
    assert second["cached"] and second["artefact_id"] == first["artefact_id"]
    assert second["idempotency_key"] == first["idempotency_key"] and len(spark.chat_requests()) == 1


def test_every_input_enters_the_key(client, spark):
    spark.responder = lambda body: Reply(content=GOOD)
    base = request_body(question="Schlüssel: Wie viel darf ich 2026 einzahlen?")
    keys = {client.post("/run", json=b).json()["idempotency_key"] for b in (
        base, {**base, "language": "en"}, {**base, "grounding": base["grounding"][:1]},
        {**base, "client_facts": [{"key": "age", "label": "Alter", "value": 48, "source": "lbs"}]},
        {**base, "history": [{"role": "user", "content": "Hallo"}]})}
    assert len(keys) == 5


def test_the_model_name_enters_the_key(standin, spark):
    from fastapi.testclient import TestClient

    from chatbot.api import create_app

    from .conftest import drop, settings_for

    spark.responder = lambda body: Reply(content=GOOD, model=body["model"])
    a, b = settings_for(standin.url), settings_for(standin.url, model="other/model")
    try:
        with TestClient(create_app(a)) as ca, TestClient(create_app(b)) as cb:
            ka = ca.post("/run", json=request_body()).json()["idempotency_key"]
            kb = cb.post("/run", json=request_body()).json()["idempotency_key"]
        assert ka != kb
    finally:
        drop(a)
        drop(b)


def test_client_facts_are_used_only_for_a_question_about_the_client(client, spark):
    facts = [{"key": "income", "label": "Erwerbseinkommen", "value": 98500.0, "source": "lbs LBS-0001"}]
    spark.responder = lambda body: Reply(content=answer_json(
        "Bei einem Einkommen von CHF 98'500 gelten die Regeln der Säule 3a [N1].", ["N1"]))
    mine = client.post("/answer", json=request_body(question="Was gilt für mein Einkommen?",
                                                     client_facts=facts)).json()
    world = client.post("/answer", json=request_body(question="Was gilt bei einem Einkommen?",
                                                      client_facts=facts)).json()
    sent = [r["body"]["messages"][-1]["content"] for r in spark.chat_requests()]
    assert "KUNDENANGABEN:\n- Erwerbseinkommen: 98500" in sent[0]
    assert "KUNDENANGABEN" not in sent[1] and "98500" not in sent[1]
    assert mine["provenance"]["client_facts_used"] and mine["unverified_numbers"] == []
    assert mine["numbers"][0]["matched"] == ["fact:income"]
    assert not world["provenance"]["client_facts_used"] and world["unverified_numbers"] == ["98'500"]
    assert world["route"] == "population_fact"


def test_a_reply_that_breaks_the_schema_is_redrafted(client, spark):
    spark.queue(Reply(content="Das ist kein JSON."), Reply(content=GOOD))
    a = client.post("/answer", json=request_body(question="Redraft: Wie viel darf ich 2026 einzahlen?")).json()
    assert not a["refused"] and a["provenance"]["model"]["attempts"] == 2
    assert any(w.startswith("redrafted") for w in a["warnings"])


def test_a_reply_that_leaves_the_language_is_redrafted_with_the_reminder(client, spark):
    spark.queue(Reply(content=answer_json("Sie dürfen 很好 einzahlen.", ["N1"])), Reply(content=GOOD))
    a = client.post("/answer", json=request_body(question="Sprache: Wie viel darf ich 2026 einzahlen?")).json()
    assert "很" not in a["answer"] and a["provenance"]["model"]["attempts"] == 2
    assert "vollständig auf Deutsch" in spark.chat_requests()[1]["body"]["messages"][-1]["content"]


def test_no_usable_draft_fails_the_run(client, spark):
    spark.queue(Reply(content="kaputt"), Reply(content="immer noch kaputt"))
    body = request_body(question="Kaputt: Wie viel darf ich 2026 einzahlen?")
    r = client.post("/answer", json=body)
    assert r.status_code == 502 and "no usable draft" in r.json()["detail"]["error"]
    status = client.get(f"/runs/{r.json()['detail']['run_id']}").json()
    assert status["status"] == "failed" and status["artefact_id"] is None


def test_spark7_down_fails_loudly_and_is_not_cached(client, spark):
    body = request_body(question="Ausfall: Wie viel darf ich 2026 einzahlen?")
    spark.queue(Reply(status=524))
    r = client.post("/answer", json=body)
    assert r.status_code == 503 and "524" in r.json()["detail"]["error"]
    spark.queue(Reply(status=503))
    run = client.post("/run", json=body).json()
    assert run["status"] == "failed" and run["artefact_id"] is None
    assert "HTTP 503" in client.get(f"/runs/{run['run_id']}").json()["error"]
    spark.queue(Reply(content=GOOD))
    again = client.post("/run", json=body).json()
    assert again["status"] == "succeeded" and not again["cached"]


def test_a_request_over_the_limits_is_422(client, spark):
    long = [{"id": "L", "title": "t", "text": "x" * 6001, "source_label": "s"}]
    assert client.post("/answer", json=request_body(grounding=long)).status_code == 422
    dup = request_body(grounding=request_body()["grounding"] * 2)
    assert client.post("/answer", json=dup).status_code == 422
    assert spark.chat_requests() == []


def test_runs_and_unknowns(client, spark):
    spark.queue(Reply(content=GOOD))
    run = client.post("/run", json=request_body(question="Liste: Wie viel darf ich 2026 einzahlen?")).json()
    rows = client.get("/runs").json()
    assert any(r["run_id"] == run["run_id"] and r["grounding_ids"] == ["N1", "N2"] for r in rows)
    status = client.get(f"/runs/{run['run_id']}").json()
    assert status["provenance"]["idempotency_key"] == run["idempotency_key"]
    assert client.get("/artefacts/CHB-0000000000000000").status_code == 404
    assert client.get("/runs/RUN-0000000000000000").status_code == 404


def test_calibration_is_append_only_through_the_api(client):
    cal = client.get("/calibration").json()
    same = client.put("/calibration", json=cal)
    assert same.status_code == 200
    changed = {**cal, "generation": {**cal["generation"], "temperature": 0.3}}
    assert client.put("/calibration", json=changed).status_code == 409
    new = {**changed, "version": "1.0.1", "parent_version": "1.0.0", "note": "test"}
    assert client.put("/calibration", json=new).status_code == 201


def test_a_named_calibration_enters_the_key(client, spark):
    spark.responder = lambda body: Reply(content=GOOD)
    cal = client.get("/calibration").json()
    client.put("/calibration", json={**cal, "version": "1.0.2", "parent_version": "1.0.0",
                                     "generation": {**cal["generation"], "max_tokens": 600}})
    body = request_body(question="Kalibrierung: Wie viel darf ich 2026 einzahlen?")
    k1 = client.post("/run", json=body).json()["idempotency_key"]
    k2 = client.post("/run", json={**body, "calibration_version": "1.0.2"}).json()["idempotency_key"]
    assert k1 != k2 and spark.chat_requests()[-1]["body"]["max_tokens"] == 600
    assert client.post("/run", json={**body, "calibration_version": "9.9.9"}).status_code == 422


def test_the_model_probe(client, spark):
    m = client.get("/model").json()
    assert m["reachable"] and m["serves_configured_model"] and m["served"] == [MODEL]


def test_the_stored_answer_round_trips_exactly(client, spark):
    spark.queue(Reply(content=GOOD))
    a = client.post("/answer", json=request_body(question="Rundreise: Wie viel darf ich 2026 einzahlen?")).json()
    assert json.loads(json.dumps(a)) == client.get(f"/artefacts/{a['artefact_id']}").json()


@pytest.mark.parametrize("bad", [{"language": "fr"}, {"question": ""}, {"extra": 1},
                                 {"grounding": [{"id": "bad id!", "title": "t", "text": "x", "source_label": "s"}]}])
def test_a_request_breaking_its_contract_is_422(client, bad):
    assert client.post("/answer", json={**request_body(), **bad}).status_code == 422
