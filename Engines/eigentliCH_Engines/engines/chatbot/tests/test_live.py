"""The one live test: the real spark7, with the token from the family .env. Opt-in:

    python -m pytest -m live -s

Runs the whole engine (real settings, a throwaway schema) against the real server, and prints the model,
the latency and the answer so the run can be reported.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from chatbot.settings import load

from . import golden_cases
from .conftest import drop, request_body

pytestmark = pytest.mark.live


def test_live_spark7_answers_from_the_grounding():
    from fastapi.testclient import TestClient

    from chatbot.api import create_app

    base = load(overrides={"model": {"warmup": {"enabled": False}}})
    if not all(base.env.values()) or len(base.env) < 2:
        pytest.fail("the spark7 token is not set: SPARK7_CLIENT_ID and SPARK7_CLIENT_SECRET in the family .env")
    settings = replace(base, database=replace(base.database, schema=f"t_{uuid.uuid4().hex[:12]}"))
    try:
        with TestClient(create_app(settings)) as client:
            probe = client.get("/model").json()
            assert probe["reachable"] and probe["serves_configured_model"], probe
            r = client.post("/answer", json=request_body(
                question=f"Wie viel darf ich 2026 in die Säule 3a einzahlen, wenn ich eine Pensionskasse habe? "
                         f"(Lauf {uuid.uuid4().hex[:6]})"))
            assert r.status_code == 200, r.text
            a = r.json()
            print(f"\nlive spark7: model {a['model']}, latency {a['latency_ms']:.0f} ms, first byte "
                  f"{a['provenance']['model']['first_byte_ms']:.0f} ms, probe {probe['ms']:.0f} ms")
            print(f"answer: {a['answer']}\ncited {a['cited_ids']}, numbers {[n['text'] for n in a['numbers']]}, "
                  f"unverified {a['unverified_numbers']}")
            assert a["model"] == settings.model.model and a["model_display_name"] == "MiniMind"
            assert not a["refused"] and a["cited_ids"] == ["N1"] and a["basis"] in ("grounded", "mixed")
            assert "7'258" in a["answer"].replace("’", "'") and a["unverified_numbers"] == []

            # CHB-18: the question that was refused on 29.09.2026, without grounding, now answered and marked.
            g = client.post("/answer", json=request_body(
                question="was muss ich machen so dass ich eine persönliche Wachstumsstrategie habe, also mehr "
                         f"einkommen generieren kann (Lauf {uuid.uuid4().hex[:6]})", grounding=[])).json()
            print(f"growth: latency {g['latency_ms']:.0f} ms, basis {g['basis']}, unverified "
                  f"{g['unverified_numbers']}\n{g['answer']}")
            assert not g["refused"] and g["basis"] == "general"
            assert g["answer"].startswith("Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:")

            # CHB-23: the incapacity question the app sent with notes that do not cover it, refused under prompt
            # 1.1.0 as out of domain, now answered.
            body = dict(golden_cases.requests()[[c["name"] for c in golden_cases.requests()].index("de_incapacity")]
                        ["request"])
            body["question"] += f" (Lauf {uuid.uuid4().hex[:6]})"
            i = client.post("/answer", json=body).json()
            print(f"incapacity: latency {i['latency_ms']:.0f} ms, basis {i['basis']}, refused {i['refused']}")
            assert not i["refused"] and i["basis"] in ("general", "mixed")
    finally:
        drop(settings)
