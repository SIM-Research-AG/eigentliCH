"""Build the golden layer: freeze spark7's replies (``--live``) and the engine's output for them.

    python dev/build_golden.py --live     # ask spark7 once per case and freeze the replies, then build
    python dev/build_golden.py            # rebuild the expected output from the frozen replies

``--live`` calls the real spark7 with the token from the family .env (never printed). Without it nothing
leaves the machine: the frozen replies are served by the test stand-in. Check the diff of
``golden/cases.json`` before committing it; a changed ``expected`` is a behaviour change.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chatbot import engine  # noqa: E402
from chatbot.calibration import PRODUCTION  # noqa: E402
from chatbot.contracts import ChatRequest  # noqa: E402
from chatbot.settings import load  # noqa: E402
from chatbot.spark7 import Spark7Client  # noqa: E402
from tests import golden_cases  # noqa: E402
from tests.conftest import drop, settings_for  # noqa: E402
from tests.standin import Reply, StandIn  # noqa: E402


def freeze_live() -> dict[str, str | None]:
    settings = load()
    client = Spark7Client(settings.model, settings.env)
    g = PRODUCTION.generation
    replies: dict[str, str | None] = {}
    try:
        for case in golden_cases.requests():
            request = ChatRequest.model_validate(case["request"])
            if not engine.intelligible(request.question):
                replies[case["name"]] = None     # refused without a model call (CHB-19)
                continue
            use = bool(engine.client_markers(request.question, request.language, PRODUCTION)) and bool(
                request.client_facts)
            done = client.complete(engine.build_messages(request, PRODUCTION, use_client_facts=use,
                                                         assistant=settings.model.display_name),
                                   max_tokens=g.max_tokens, temperature=g.temperature, seed=g.seed,
                                   response_format=engine.response_format())
            print(f"{case['name']}: {done.latency_ms:.0f} ms, {done.model}, finish {done.finish_reason}")
            replies[case["name"]] = done.text
    finally:
        client.close()
    return replies


def build(replies: dict[str, str | None], model: str) -> list[dict]:
    from fastapi.testclient import TestClient

    from chatbot.api import create_app

    standin = StandIn().start()
    settings = settings_for(standin.url)
    settings = replace(settings, model=replace(settings.model, model=model))
    out = []
    try:
        with TestClient(create_app(settings)) as client:
            for case in golden_cases.requests():
                reply = replies[case["name"]]
                standin.reset()
                if reply is not None:
                    standin.queue(Reply(content=reply, model=model))
                r = client.post("/answer", json=case["request"])
                r.raise_for_status()
                out.append({"name": case["name"], "model_reply": reply,
                            "expected": golden_cases.pinned(r.json())})
    finally:
        standin.stop()
        drop(settings)
    return out


def main(argv: list[str]) -> int:
    path = golden_cases.GOLDEN / "cases.json"
    model = load().model.model
    if "--live" in argv:
        replies = freeze_live()
    else:
        replies = {c["name"]: c["model_reply"] for c in golden_cases.cases()}
    cases = build(replies, model)
    path.write_text(json.dumps({"_note": "Golden layer: spark7's replies frozen from the live server "
                                         "(dev/build_golden.py --live) and the engine's output for them.",
                                "model": model, "cases": cases}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
