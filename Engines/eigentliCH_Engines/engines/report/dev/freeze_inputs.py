"""Freeze the upstream artefacts the report tests run on, into ``golden/inputs/``.

    python dev/freeze_inputs.py                     # pcp from the running pcp (8007), lbs in-process
    python dev/freeze_inputs.py --real              # the real view: lbs 1.4.0 sheets, the pcp real stand-in
    ..\\..\\..\\Optimizer\\.venv\\Scripts\\python dev/freeze_inputs.py --pcp-offline   # pcp in-process

pcp (``pcp-allocation@1.0.0``)
    ``pcp_allocation.json`` and ``pcp_allocation_2.json``: two Allocations of the same client under different
    role bounds (the second is what an update reports against the first). Read from the running pcp
    (``GET /allocation/{id}``, read only; ``--pcp PCP-... --pcp2 PCP-...``), or, when pcp is not running, built
    by pcp's own service logic in-process on pcp's frozen inputs, without a database (``--pcp-offline``, with
    the Optimizer venv, which has scipy).
lbs (``lbs-balance-sheet@1.0.0``)
    ``lbs_sheet.json``, ``lbs_sheet_property.json``, ``lbs_sheet_liquidity.json``: sheets built by lbs's own
    ``service.build_sheet`` from its constructed cases ``syn-couple``, ``syn-property-1`` and
    ``syn-liquidity``, imported read-only from ``engines/lbs/src``. The ``db-*`` cases are database members'
    figures and are deliberately not copied here.

Everything is validated against this engine's mirrors before it is written, and written here only. Re-run
after an upstream contract change and check the diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "golden" / "inputs"
LBS = ROOT.parent / "lbs"
sys.path.insert(0, str(ROOT / "src"))

from report.contracts import Allocation, LifeBalanceSheet  # noqa: E402

LBS_CASES = {"lbs_sheet.json": "syn-couple", "lbs_sheet_property.json": "syn-property-1",
             "lbs_sheet_liquidity.json": "syn-liquidity"}

#: The two mandates: balanced, then the same with more weight allowed in Gain and less in Protection.
BOUNDS = {
    "pcp_allocation.json": {"role": {"Gain": {"lower": 0.2, "upper": 0.6}, "Protection": {"lower": 0.05, "upper": 0.4}},
                            "currency": {"CHF": {"lower": 0.3, "upper": 1.0}}},
    "pcp_allocation_2.json": {"role": {"Gain": {"lower": 0.5, "upper": 0.7},
                                       "Protection": {"lower": 0.05, "upper": 0.1}},
                              "currency": {"CHF": {"lower": 0.3, "upper": 1.0}}},
}


def _write_allocation(name: str, content: bytes | str) -> str:
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    allocation = Allocation.model_validate_json(text)
    (INPUTS / name).write_text(text.rstrip() + "\n", encoding="utf-8")
    return allocation.artefact_id


def freeze_pcp(argv: list[str]) -> None:
    base = "http://127.0.0.1:8007"
    for flag, name in (("--pcp", "pcp_allocation.json"), ("--pcp2", "pcp_allocation_2.json")):
        if flag not in argv:
            continue
        aid = argv[argv.index(flag) + 1]
        body = httpx.get(f"{base}/allocation/{aid}", timeout=60)
        body.raise_for_status()
        print(f"{name}: {_write_allocation(name, body.content)}")


def freeze_pcp_offline() -> None:
    pcp_root = ROOT.parents[2] / "Optimizer" / "engines" / "pcp"
    sys.path.insert(0, str(pcp_root / "src"))
    import httpx as _httpx
    from pcp.calibration import PRODUCTION  # type: ignore[import-not-found]
    from pcp.clients import aggregation_client, fmre_client  # type: ignore[import-not-found]
    from pcp.contracts import PCPRunRequest  # type: ignore[import-not-found]
    from pcp.service import Service  # type: ignore[import-not-found]

    inputs = pcp_root / "golden" / "inputs"
    regime = (inputs / "regime.json").read_bytes()
    rs = json.loads((inputs / "return_set.json").read_bytes())
    register = (inputs / "instruments.json").read_bytes()
    regime_id = json.loads(regime)["regime_id"]

    def agg(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(200, content=regime) if request.url.path == f"/regime/{regime_id}" else _httpx.Response(404)

    def fmre(request: _httpx.Request) -> _httpx.Response:
        if request.url.path == "/v1/return-set":
            return _httpx.Response(200, json={**rs, "provenance": {**rs["provenance"], "regime_id": regime_id}})
        return _httpx.Response(200, content=register)

    class Offline(Service):
        def calibration(self, version=None):  # the seed, not the store
            return PRODUCTION

    service = Offline(None, None, aggregation_client("http://agg", 60, _httpx.MockTransport(agg)),
                      fmre_client("http://fmre", 60, _httpx.MockTransport(fmre)))
    universe = sorted(i["instrument_id"] for i in json.loads(register))
    for name, bounds in BOUNDS.items():
        request = PCPRunRequest.model_validate({
            "regime_id": regime_id, "return_set_id": rs["return_set_id"], "speed_mode": "exact",
            "mandate": {"client": "syn-couple", "name": "balanced", "currency": "CHF", "target_curve": [0.02] * 25,
                        "universe": universe, "max_single_position": 0.15, "bounds": bounds,
                        "bound_sources": {"role": "derived", "currency": "derived"}, "regime_market": "global"}})
        allocation = service._execute(request, service.idempotency_key(request, PRODUCTION))
        print(f"{name} (offline): {_write_allocation(name, allocation.model_dump_json(indent=1))}")


def freeze_lbs() -> None:
    sys.path.insert(0, str(LBS / "src"))
    from lbs.calibration import SEEDS  # type: ignore[import-not-found]
    from lbs.contracts import LifeBalanceSheetRequest  # type: ignore[import-not-found]
    from lbs.service import build_sheet  # type: ignore[import-not-found]

    for name, case_name in LBS_CASES.items():
        case = json.loads((LBS / "golden" / "cases" / f"{case_name}.json").read_text(encoding="utf-8"))
        sheet = build_sheet(LifeBalanceSheetRequest.model_validate(case), SEEDS[-1])
        text = sheet.model_dump_json(indent=1)
        LifeBalanceSheet.model_validate_json(text)
        (INPUTS / name).write_text(text + "\n", encoding="utf-8")
        print(f"{name}: {sheet.artefact_id} ({sheet.client_ref}, calibration {sheet.calibration_version})")


#: The real view (REP-27, REP-29): lbs sheets under lbs's calibration 1.4.0, the first with a ``real_view``.
LBS_REAL_CASES = {"lbs_sheet_real.json": "syn-couple", "lbs_sheet_property_real.json": "syn-property-1"}
LBS_REAL_CALIBRATION = "1.4.0"
#: A stand-in for pcp's real Allocation: pcp_allocation.json restated on basis ``real`` as pcp PCP-22 writes it
#: (``basis`` and ``provenance.basis`` real, pcp's real-basis note first among the coverage warnings), under its
#: own content id. pcp's real path needs a real ReturnSet from fmre, which an offline freeze cannot have.
PCP_REAL_STANDIN = "pcp_allocation_real.json"
PCP_REAL_NOTE = ("real basis: the target curve and every profile are net of inflation, deflated by fmre with CHF "
                 "Swiss CPI (per_state_forward_12m); states: measured 23, extrapolated 2 (PCP-22)")


def freeze_real() -> None:
    import hashlib

    sys.path.insert(0, str(LBS / "src"))
    from lbs.calibration import SEEDS  # type: ignore[import-not-found]
    from lbs.contracts import LifeBalanceSheetRequest  # type: ignore[import-not-found]
    from lbs.service import build_sheet  # type: ignore[import-not-found]

    cal = next(c for c in SEEDS if c.version == LBS_REAL_CALIBRATION)
    for name, case_name in LBS_REAL_CASES.items():
        case = json.loads((LBS / "golden" / "cases" / f"{case_name}.json").read_text(encoding="utf-8"))
        sheet = build_sheet(LifeBalanceSheetRequest.model_validate(case), cal)
        text = sheet.model_dump_json(indent=1)
        assert LifeBalanceSheet.model_validate_json(text).real_view is not None, name
        (INPUTS / name).write_text(text + "\n", encoding="utf-8")
        print(f"{name}: {sheet.artefact_id} ({sheet.client_ref}, calibration {sheet.calibration_version})")
    raw = json.loads((INPUTS / "pcp_allocation.json").read_text(encoding="utf-8"))
    raw["basis"] = "real"
    raw["provenance"]["basis"] = "real"
    raw["coverage"]["warnings"] = [PCP_REAL_NOTE] + list(raw["coverage"].get("warnings") or [])
    raw["_standin"] = ("report dev/freeze_inputs.py --real: pcp_allocation.json restated on basis real, a stand-in "
                       "until a real Allocation is frozen from the running pcp")
    raw["artefact_id"] = ""
    raw["artefact_id"] = "PCP-" + hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    text = json.dumps(raw, ensure_ascii=False, indent=1)
    assert Allocation.model_validate_json(text).basis == "real"
    (INPUTS / PCP_REAL_STANDIN).write_text(text + "\n", encoding="utf-8")
    print(f"{PCP_REAL_STANDIN} (stand-in): {raw['artefact_id']}")


def main(argv: list[str]) -> int:
    INPUTS.mkdir(parents=True, exist_ok=True)
    if "--real" in argv:
        freeze_real()
        return 0
    if "--pcp-offline" in argv:
        freeze_pcp_offline()
        return 0
    if "--lbs-only" not in argv:
        freeze_pcp(argv)
    if "--pcp-only" not in argv:
        freeze_lbs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
