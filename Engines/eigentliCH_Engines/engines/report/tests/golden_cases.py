"""The golden cases, shared by tests/test_golden.py and dev/build_golden.py.

Each case is a request over the frozen inputs (``golden/inputs``). ``golden/reports/<name>.json`` holds the
frozen report and, for a prose case, spark7's replies in the order the engine asked for them
(``model_replies``, frozen once from the live server by ``dev/build_golden.py --live``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).resolve().parent.parent / "golden"
INPUTS = GOLDEN / "inputs"
REPORTS = GOLDEN / "reports"


def _id(name: str) -> str:
    return json.loads((INPUTS / name).read_bytes())["artefact_id"]


def _client(name: str) -> str:
    return json.loads((INPUTS / name).read_bytes())["client_ref"]


def upstream_files() -> dict[str, dict[str, str]]:
    """engine -> upstream path -> frozen file."""
    return {"pcp": {f"/allocation/{_id(n)}": n for n in ("pcp_allocation.json", "pcp_allocation_2.json")},
            "lbs": {f"/artefacts/{_id(n)}": n for n in ("lbs_sheet.json", "lbs_sheet_property.json",
                                                         "lbs_sheet_liquidity.json")}}


NAME = [{"key": "name", "label": "Kundin", "value": "Muster", "source": "golden"}]
REVISION_NOTE = ("Bitte den Erbvorbezug an die Kinder auf je 80 000 Franken senken und die Reserve für die Pflege "
                 "zuerst sichern. Die Kuratorin")


def cases() -> list[dict[str, Any]]:
    """Ordered: an update names the report of an earlier case by its case name (``previous``), a revision the
    report it revises (``revision_of``)."""
    couple = _client("lbs_sheet.json")
    both = [{"engine": "pcp", "artefact_id": _id("pcp_allocation.json")},
            {"engine": "lbs", "artefact_id": _id("lbs_sheet.json")}]
    return [
        {"name": "de_full", "request": {"client_ref": couple, "kind": "report", "language": "de", "sources": both,
                                        "display_facts": NAME, "prose": False}},
        {"name": "en_full", "request": {"client_ref": couple, "kind": "report", "language": "en", "sources": both,
                                        "display_facts": [{**NAME[0], "label": "Client"}], "prose": False}},
        {"name": "en_property", "request": {"client_ref": _client("lbs_sheet_property.json"), "kind": "report",
                                            "language": "en", "prose": False,
                                            "sources": [{"engine": "lbs", "artefact_id": _id("lbs_sheet_property.json")}]}},
        {"name": "de_liquidity", "request": {"client_ref": _client("lbs_sheet_liquidity.json"), "kind": "report",
                                             "language": "de", "prose": False,
                                             "sources": [{"engine": "lbs",
                                                          "artefact_id": _id("lbs_sheet_liquidity.json")}]}},
        {"name": "de_update", "previous": "de_full",
         "request": {"client_ref": couple, "kind": "update", "language": "de", "display_facts": NAME, "prose": False,
                     "sources": [{"engine": "pcp", "artefact_id": _id("pcp_allocation_2.json")},
                                 {"engine": "lbs", "artefact_id": _id("lbs_sheet.json")}]}},
        # A revision of de_full (REP-25): the same sources, the curator's remark, a distinct report.
        {"name": "de_revision", "revision_of": "de_full",
         "request": {"client_ref": couple, "kind": "report", "language": "de", "sources": both,
                     "display_facts": NAME, "prose": False, "revision_note": REVISION_NOTE}},
        {"name": "de_full_prose", "live": True,
         "request": {"client_ref": couple, "kind": "report", "language": "de", "sources": both,
                     "display_facts": NAME, "prose": True}},
    ]


def frozen(name: str) -> dict[str, Any]:
    return json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))
