"""The golden cases, shared by tests/test_golden.py and dev/build_golden.py.

``golden/requests.json`` holds the requests; ``golden/cases.json`` holds, per case, spark7's reply as frozen
once from the live server (``model_reply``; ``null`` for a case that needs no model) and the engine's golden
output for that reply (``expected``): the fields a reader sees and the checks behind them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).resolve().parent.parent / "golden"

#: The ChatAnswer fields the golden layer pins. Latency, ids and timings vary by run and are not pinned.
PINNED = ("answer", "cited_ids", "numbers", "unverified_numbers", "refused", "refusal_code", "refusal_reason",
          "route", "basis", "warnings", "model", "model_display_name", "prompt_version", "notice")


def requests() -> list[dict[str, Any]]:
    data = json.loads((GOLDEN / "requests.json").read_text(encoding="utf-8"))
    notes = {n["id"]: n for n in data["notes"]}
    out = []
    for case in data["cases"]:
        body = dict(case["request"])
        body["grounding"] = [notes[i] for i in body.get("grounding", [])]
        out.append({"name": case["name"], "request": body})
    return out


def cases() -> list[dict[str, Any]]:
    return json.loads((GOLDEN / "cases.json").read_text(encoding="utf-8"))["cases"]


def pinned(answer: dict[str, Any]) -> dict[str, Any]:
    return {k: answer[k] for k in PINNED}
