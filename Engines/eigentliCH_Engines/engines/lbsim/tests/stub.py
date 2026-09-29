"""A stand-in for lbs, pcp, aggregation and fmre, serving frozen payloads (tests only).

* lbs: the frozen lbs cases (``golden/lbs_cases``: the sheet, the request it was built from, the records).
* pcp, aggregation, fmre: the snapshot ``golden/upstream`` (``dev/build_upstream_snapshot.py``). The Allocation is
  pcp's bench Allocation; the stand-in serves it under the client of the case being tested (``client`` rewritten),
  because no real client's Allocation is frozen. A test that wants the mismatch serves it unchanged.

``transport(...)`` is an ``httpx.MockTransport`` for in-process tests; ``app(...)`` is the same routes as a FastAPI
app for the worker subprocess tests. ``Stub.edit`` changes a payload for one test (a moved return set, EUR, ...).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "golden" / "lbs_cases"
UP = ROOT / "golden" / "upstream"
KEYS = ("base", "depression", "hyperinflation", "stagflation", "deferral")


def _rd(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


_CACHE: dict[str, Any] = {}


def snapshot() -> dict[str, Any]:
    if not _CACHE:
        manifest = _rd(UP / "manifest.json")
        _CACHE["manifest"] = manifest
        _CACHE["allocation"] = _rd(UP / "allocation.json")
        _CACHE["scenarios"] = _rd(UP / "scenarios.json")
        _CACHE["policies"] = _rd(UP / "policies.json")
        for k in KEYS:
            _CACHE[f"regime_{k}"] = _rd(UP / f"regime_{k}.json")
            _CACHE[f"return_set_{k}"] = _rd(UP / f"return_set_{k}.json")
            _CACHE[f"inflation_{k}"] = _rd(UP / f"inflation_{k}.json")
        _CACHE["records"] = _rd(CASES / "records.json")["records"]
    return _CACHE


class Stub:
    """The payloads one test serves; copies, so a test's edit never leaks."""

    def __init__(self, cases: tuple[str, ...] = ("lbsim-sample",), *, client: Optional[str] = None):
        s = snapshot()
        self.data = {k: copy.deepcopy(v) for k, v in s.items() if k != "manifest"}
        self.regime_ids = dict(s["manifest"]["regimes"])
        self.sheets: dict[str, dict] = {}
        self.requests: dict[str, dict] = {}
        for name in cases:
            self.add_case(name)
        first = next(iter(self.sheets.values())) if self.sheets else None
        self.data["allocation"]["client"] = client or (first["client_ref"] if first else "bench")
        self.calls: list[str] = []
        self.down: set[str] = set()

    def add_case(self, name: str) -> str:
        sheet = _rd(CASES / name / "sheet.json")
        self.sheets[sheet["artefact_id"]] = sheet
        self.requests[sheet["artefact_id"]] = _rd(CASES / name / "request.json")
        return sheet["artefact_id"]

    @property
    def allocation_id(self) -> str:
        return self.data["allocation"]["artefact_id"]

    def sheet_id(self, name: str) -> str:
        return _rd(CASES / name / "sheet.json")["artefact_id"]

    def edit(self, key: str, fn: Callable[[Any], Any]) -> None:
        out = fn(self.data[key])
        if out is not None:
            self.data[key] = out

    def _by_regime(self, prefix: str, regime_id: str) -> Optional[dict]:
        for k, rid in self.regime_ids.items():
            if rid == regime_id:
                return self.data[f"{prefix}_{k}"]
        return None

    # -- routing ------------------------------------------------------------------------------------------------

    def route(self, host: str, path: str, query: dict[str, str]) -> tuple[int, Any]:
        self.calls.append(f"{host}{path}")
        engine = {"8013": "lbs", "8007": "pcp", "8004": "aggregation", "8006": "fmre"}.get(host.rsplit(":", 1)[-1],
                                                                                          host)
        if engine in self.down:
            return 599, None
        parts = [p for p in path.split("/") if p]
        if parts[:1] == ["artefacts"]:
            sid = parts[1]
            if sid not in self.sheets:
                return 404, {"detail": "no life balance sheet"}
            sheet = self.sheets[sid]
            if len(parts) == 3 and parts[2] == "request":
                return 200, {"artefact_id": sid, "request_hash": sheet["provenance"]["request_hash"],
                             "contract_version": "lbs-request@1.0.0", "request": self.requests[sid]}
            return 200, sheet
        if parts == ["calibration"]:
            return 200, {"contract_version": "lbs-calibration@1.3.0", "version": query.get("version"),
                         "records": self.data["records"]}
        if parts[:1] == ["allocation"]:
            if parts[1] != self.data["allocation"]["artefact_id"]:
                return 404, {"detail": "no allocation"}
            return 200, self.data["allocation"]
        if parts == ["scenarios"]:
            return 200, self.data["scenarios"]
        if parts == ["scenarios", "policies"]:
            return 200, self.data["policies"]
        if parts[:1] == ["regime"]:
            body = self._by_regime("regime", parts[1])
            return (404, {"detail": "no regime"}) if body is None else (200, body)
        if parts == ["v1", "return-set"]:
            body = self._by_regime("return_set", query.get("regime_id", ""))
            if body is not None and query.get("basis", "nominal") != "nominal":
                body = self.data.get(f"return_set_real_{query['regime_id']}")
            return (404, {"detail": "no return set"}) if body is None else (200, body)
        if parts == ["v1", "inflation"]:
            body = self._by_regime("inflation", query.get("regime_id", ""))
            return (404, {"detail": "no inflation"}) if body is None else (200, body)
        return 404, {"detail": f"unknown route {path}"}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            url = urlparse(str(request.url))
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            status, body = self.route(url.netloc, url.path, query)
            if status == 599:
                raise httpx.ConnectError("stand-in engine down", request=request)
            return httpx.Response(status, json=body)

        return httpx.MockTransport(handler)

    def app(self):
        app = FastAPI()

        @app.get("/{path:path}")
        def any_route(path: str, request: Request):
            status, body = self.route("stub", "/" + path, dict(request.query_params))
            return JSONResponse(status_code=status, content=body)

        return app


# -- in-process building blocks (no HTTP) -------------------------------------------------------------------------

def case_inputs(name: str, calibration=None):
    """The sheet, its request, the records and the findings of a frozen lbs case."""
    from lbsim.calibration import ACTIVE_SEED  # noqa: PLC0415
    from lbsim.contracts import LbsRequest, LbsSheet  # noqa: PLC0415
    from lbsim.fast.build import build_findings  # noqa: PLC0415
    from lbsim.ids import sha256  # noqa: PLC0415

    cal = calibration or ACTIVE_SEED
    raw = _rd(CASES / name / "sheet.json")
    sheet, request = LbsSheet.model_validate(raw), LbsRequest.model_validate(_rd(CASES / name / "request.json"))
    records = snapshot()["records"]
    findings = build_findings(sheet, request, records, cal, sheet_sha256=sha256(raw))
    return sheet, request, records, findings


def bundle(stub: "Stub", sheet, scenarios=None, accept_ipt=("ipt@1.1.0",)):
    """The checked market bundle, from the stand-in's payloads, exactly as ``Service.read_market`` builds it."""
    from lbsim import upstream as U  # noqa: PLC0415

    d = stub.data
    alloc = U.check_allocation(d["allocation"], client_ref=sheet.client_ref, sheet=sheet, currencies=("CHF",))
    base = U.check_base_regime(d["regime_base"], alloc)
    chosen = U.choose_scenarios(d["scenarios"], alloc.regime_id, scenarios)
    return U.assemble(allocation=alloc, allocation_raw=d["allocation"], base_regime=base,
                      base_regime_raw=d["regime_base"], scenario_ids=chosen,
                      scenario_regimes_raw={k: d[f"regime_{k}"] for k in chosen}, policies_raw=d["policies"],
                      return_sets_raw={"base": d["return_set_base"], **{k: d[f"return_set_{k}"] for k in chosen}},
                      check_set_raw=d["return_set_base"],
                      inflation_raw={"base": d["inflation_base"], **{k: d[f"inflation_{k}"] for k in chosen}},
                      accept_ipt=accept_ipt)


def stated(name: str, *, horizon=None, income_path=None, calibration=None):
    from lbsim.calibration import ACTIVE_SEED  # noqa: PLC0415
    from lbsim.paths.household import stated_plan  # noqa: PLC0415

    cal = calibration or ACTIVE_SEED
    sheet, request, records, findings = case_inputs(name, cal)
    plan = stated_plan(sheet, request, records, cal, findings, income_path=income_path, horizon_years=horizon,
                       max_horizon_years=60, reference_age=65.0)
    return sheet, request, records, findings, plan
