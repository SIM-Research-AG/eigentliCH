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
    return {"pcp": {f"/allocation/{_id(n)}": n for n in ("pcp_allocation.json", "pcp_allocation_2.json",
                                                          "pcp_allocation_real.json", "pcp_allocation_lbsim.json")},
            "lbs": {f"/artefacts/{_id(n)}": n for n in ("lbs_sheet.json", "lbs_sheet_property.json",
                                                         "lbs_sheet_liquidity.json", "lbs_sheet_real.json",
                                                         "lbs_sheet_property_real.json", "lbs_sheet_lbsim.json")},
            "lbsim": {f"/artefacts/{_id(n)}": n for n in ("lbsim_findings.json", "lbsim_paths.json", "lbsim_plan.json")}}


NAME = [{"key": "name", "label": "Kundin", "value": "Muster", "source": "golden"}]
REVISION_NOTE = ("Bitte den Erbvorbezug an die Kinder auf je 80 000 Franken senken und die Reserve für die Pflege "
                 "zuerst sichern. Die Kuratorin")


def cases() -> list[dict[str, Any]]:
    """Ordered: an update names the report of an earlier case by its case name (``previous``), a revision the
    report it revises (``revision_of``)."""
    couple = _client("lbs_sheet.json")
    sim = _client("lbs_sheet_lbsim.json")
    outlook = [{"engine": "pcp", "artefact_id": _id("pcp_allocation_lbsim.json")},
               {"engine": "lbs", "artefact_id": _id("lbs_sheet_lbsim.json")},
               {"engine": "lbsim", "artefact_id": _id("lbsim_findings.json")},
               {"engine": "lbsim", "artefact_id": _id("lbsim_paths.json")},
               {"engine": "lbsim", "artefact_id": _id("lbsim_plan.json")}]
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
        # The real view (REP-27): a real report on lbs's real figures and pcp's real Allocation (a stand-in), the
        # same in English on the property sheet, and a nominal report on a sheet that carries both views.
        {"name": "de_real", "request": {"client_ref": couple, "kind": "report", "language": "de", "basis": "real",
                                        "display_facts": NAME, "prose": False,
                                        "sources": [{"engine": "pcp", "artefact_id": _id("pcp_allocation_real.json")},
                                                    {"engine": "lbs", "artefact_id": _id("lbs_sheet_real.json")}]}},
        {"name": "en_property_real", "request": {"client_ref": _client("lbs_sheet_property_real.json"),
                                                 "kind": "report", "language": "en", "prose": False, "basis": "real",
                                                 "sources": [{"engine": "lbs",
                                                              "artefact_id": _id("lbs_sheet_property_real.json")}]}},
        {"name": "en_property_nominal_views", "request": {
            "client_ref": _client("lbs_sheet_property_real.json"), "kind": "report", "language": "en",
            "prose": False, "sources": [{"engine": "lbs", "artefact_id": _id("lbs_sheet_property_real.json")}]}},
        # lbsim (REP-32 to REP-36): the outlook with all three charts in both languages; the real view on lbs and
        # lbsim alone (a real report takes no nominal Allocation, REP-28); the plan still running, then the update
        # that includes it.
        {"name": "de_outlook", "request": {"client_ref": sim, "kind": "report", "language": "de", "prose": False,
                                           "display_facts": NAME, "sources": outlook}},
        {"name": "en_outlook", "request": {"client_ref": sim, "kind": "report", "language": "en", "prose": False,
                                           "display_facts": [{**NAME[0], "label": "Client"}], "sources": outlook}},
        {"name": "de_outlook_real", "request": {"client_ref": sim, "kind": "report", "language": "de", "prose": False,
                                                "basis": "real", "display_facts": NAME, "sources": outlook[1:]}},
        {"name": "en_outlook_real", "request": {"client_ref": sim, "kind": "report", "language": "en", "prose": False,
                                                "basis": "real", "sources": outlook[1:]}},
        {"name": "de_outlook_calculating", "request": {"client_ref": sim, "kind": "report", "language": "de",
                                                       "prose": False, "display_facts": NAME, "sources": outlook[:4]}},
        {"name": "de_outlook_plan_update", "previous": "de_outlook_calculating",
         "request": {"client_ref": sim, "kind": "update", "language": "de", "prose": False, "display_facts": NAME,
                     "sources": outlook}},
        {"name": "de_full_prose", "live": True,
         "request": {"client_ref": couple, "kind": "report", "language": "de", "sources": both,
                     "display_facts": NAME, "prose": True}},
    ]


def frozen(name: str) -> dict[str, Any]:
    return json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))
