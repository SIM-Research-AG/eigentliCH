"""Golden layer: spark7's real replies, frozen once (dev/build_golden.py --live), served by the stand-in; the
engine's handling of each (answer, citations, the number check, refusals, route, warnings) must be exactly
the frozen output."""

from __future__ import annotations

import json

import pytest

from . import golden_cases
from .standin import Reply

CASES = {c["name"]: c for c in golden_cases.cases()}
REQUESTS = {c["name"]: c["request"] for c in golden_cases.requests()}


def test_every_request_has_a_frozen_case():
    assert set(CASES) == set(REQUESTS) and len(CASES) >= 5


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_case(name, client, spark):
    case = CASES[name]
    if case["model_reply"] is not None:
        spark.queue(Reply(content=case["model_reply"], model=case["expected"]["model"]))
    r = client.post("/answer", json=REQUESTS[name])
    assert r.status_code == 200, r.text
    assert golden_cases.pinned(r.json()) == case["expected"]
    assert len(spark.chat_requests()) == (0 if case["model_reply"] is None else 1)


def test_the_golden_answers_are_all_verified():
    """The frozen live answers carry no unverified number: the model did not invent a figure."""
    assert all(c["expected"]["unverified_numbers"] == [] for c in CASES.values())
    # Until prompt 1.1.0 this case was refused. Since CHB-18 it is answered; the model must still not do the
    # arithmetic (no "17" appears, and every number in the answer is verified).
    arithmetic = CASES["de_client_needs_arithmetic"]["expected"]
    assert not arithmetic["refused"] and "17" not in arithmetic["answer"]


def test_the_changed_behaviour_of_calibration_1_1_0():
    """CHB-18 and CHB-19 on spark7's real replies: no refusal for lack of grounding, the general part marked,
    refused only outside the domain and without a word."""
    label = "Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:"
    growth = CASES["de_growth_strategy"]["expected"]
    assert not growth["refused"] and growth["basis"] == "general" and growth["answer"].startswith(label)
    assert growth["model_display_name"] == "MiniMind" and "spark7" not in growth["answer"]
    assert CASES["de_mixed"]["expected"]["basis"] == "mixed" and CASES["de_mixed"]["expected"]["cited_ids"] == ["N1"]
    assert CASES["de_3a_maximum"]["expected"]["basis"] == "grounded"
    assert CASES["de_no_grounding"]["expected"]["basis"] == "general"
    assert [n for n, c in CASES.items() if c["expected"]["refused"]] == [
        "en_out_of_domain", "de_unintelligible", "de_medical_diagnosis"]


#: The three requests the consumer app sent while building the use cases (29.09.2026), notes and client facts as
#: sent, each refused as out of domain under prompt 1.1.0 (CHB-23), and the words the answer must use.
WIDER_DOMAIN = {"de_care_for_a_parent": ("Mutter",), "de_incapacity": ("Vorsorgeauftrag", "KESB"),
                "de_inheritance": ("Pflichtteil",)}


@pytest.mark.parametrize("name", sorted(WIDER_DOMAIN))
def test_care_incapacity_and_inheritance_are_answered(name):
    """CHB-23 on spark7's real replies: care for a parent, incapacity and inheritance are in the domain. The app
    sent notes that do not cover them; the model answers from general knowledge, marked, and refuses nothing."""
    e = CASES[name]["expected"]
    assert not e["refused"] and e["refusal_reason"] is None and e["basis"] in ("general", "mixed")
    assert e["prompt_version"] == "chatbot-prompt@1.2.0" and e["unverified_numbers"] == []
    assert all(word in e["answer"] for word in WIDER_DOMAIN[name])
    reply = json.loads(CASES[name]["model_reply"])
    assert reply["status"] == "answer" and reply["general"]


def test_out_of_domain_stays_narrow():
    """A medical diagnosis and a recipe are still refused under the wider domain (CHB-23)."""
    for name in ("en_out_of_domain", "de_medical_diagnosis"):
        e = CASES[name]["expected"]
        assert e["refused"] and e["refusal_reason"].startswith("out_of_domain:")
        assert json.loads(CASES[name]["model_reply"])["status"] == "out_of_domain"
