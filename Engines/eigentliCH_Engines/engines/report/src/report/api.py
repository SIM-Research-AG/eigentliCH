"""HTTP surface. Routing only: no figures, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific ones, which are
additive only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from . import ENGINE_VERSION, contracts as c
from .clients import engine_clients
from .service import (
    Conflict,
    InvalidRequest,
    NotFound,
    Refused,
    RunFailed,
    Service,
    Unavailable,
    allowlist_report,
)
from .settings import ROOT, Settings, load
from .spark7 import Spark7Client
from .store import Store

TESTBENCH = ROOT / "testbench" / "index.html"
#: The golden example pages, shown by the test bench's gallery. Not in the deploy folder either.
GOLDEN_REPORTS = ROOT / "golden" / "reports"


def golden_gallery() -> list[dict[str, Any]]:
    """Each golden page with what it shows, in words, read from its frozen report."""
    import json

    out = []
    for path in sorted(GOLDEN_REPORTS.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))["report"]
        keys = [s["key"] for s in report["sections"]]
        has = [w for k, w in (("outlook", "outlook"), ("capitals", "four capitals"), ("life_sheet", "life balance sheet"),
                              ("allocation", "allocation"), ("property", "home ownership"), ("liquidity", "liquidity"))
               if k in keys]
        charts = [c for c in ("capitals_time",) if f'data-chart="{c}"' in report["html"]]
        out.append({"name": path.stem, "language": report["language"], "basis": report.get("basis") or "nominal",
                    "kind": report["kind"], "lbsim": "outlook" in keys,
                    "capitals_over_time": bool(charts), "revision": bool(report.get("revision_of")),
                    "prose": any(s["prose_status"] == "verified" for s in report["sections"]),
                    "shows": has})
    return out


def create_app(settings: Optional[Settings] = None,
               upstream_transports: Optional[dict[str, httpx.BaseTransport]] = None,
               model_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    upstream = engine_clients({"pcp": settings.pcp_url, "lbs": settings.lbs_url, "lbsim": settings.lbsim_url}, settings.upstream_timeout_s,
                              upstream_transports)
    model = Spark7Client(settings.model, settings.env, model_transport)
    service = Service(settings, Store(settings.database), upstream, model)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        service.shutdown()

    app = FastAPI(
        title="eigentliCH Report Engine (report)",
        version=ENGINE_VERSION,
        description=("Renders reports in which every figure traces back to an artefact id: the code owns every "
                     f"figure, {settings.model.display_name}, the house's AI, writes the connecting sentences, and "
                     "every number in them is checked against the facts of its section. " + c.NOTICE),
        lifespan=lifespan,
    )
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"],
                       allow_credentials=False)

    def guard(fn, *args: Any) -> Any:
        try:
            return fn(*args)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidRequest as exc:
            raise HTTPException(422, str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    # ---- standard endpoints ------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return service.meta(allowlist_report())

    @app.get("/contracts", tags=["standard"])
    def contracts() -> dict[str, Any]:
        models = {"Allocation(pcp)": c.Allocation, "LifeBalanceSheet(lbs)": c.LifeBalanceSheet,
                  "LifeBalanceFindings(lbsim)": c.LifeBalanceFindings, "LifeBalancePaths(lbsim)": c.LifeBalancePaths,
                  "LifeBalancePlan(lbsim)": c.LifeBalancePlan,
                  "ReportRequest": c.ReportRequest, "Report": c.Report, "RunAccepted": c.RunAccepted,
                  "RunStatus": c.RunStatus, "Calibration": c.Calibration}
        inbound = {"Allocation(pcp)", "LifeBalanceSheet(lbs)", "LifeBalanceFindings(lbsim)", "LifeBalancePaths(lbsim)",
                   "LifeBalancePlan(lbsim)", "ReportRequest"}
        return {name: {"version": c.CONTRACT_VERSIONS.get(name), "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.ReportRequest) -> c.RunAccepted:
        """Produce a report and store it. A failed run is reported with status ``failed``; its reason is on
        ``GET /runs/{run_id}``."""
        try:
            return guard(service.submit, request)
        except RunFailed as exc:
            return c.RunAccepted(run_id=exc.run_id, status="failed", artefact_id=None,
                                 idempotency_key=exc.idempotency_key, cached=False)

    @app.get("/runs", tags=["standard"])
    def runs(limit: int = 50) -> list[dict[str, Any]]:
        return service.runs(limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.Report)
    def artefact(artefact_id: str) -> c.Report:
        return guard(service.artefact, artefact_id)

    @app.get("/calibration", tags=["standard"], response_model=c.Calibration)
    def calibration(version: Optional[str] = None) -> c.Calibration:
        return guard(service.calibration, version)

    @app.put("/calibration", tags=["standard"], response_model=c.Calibration)
    def propose_calibration(proposal: c.Calibration, response: Response) -> c.Calibration:
        stored, created = guard(service.propose_calibration, proposal)
        response.status_code = 201 if created else 200
        return stored

    # ---- engine specific, additive ------------------------------------------

    @app.post("/report", tags=["report"], response_model=c.Report)
    def report(request: c.ReportRequest) -> c.Report:
        """``POST /run`` returning the report itself. 422 when the engine cannot report on the request as
        asked, 503 when an upstream engine is not there; both name the failed run. A missing model is not a
        failure: the report comes without prose, ``complete`` false."""
        try:
            return guard(service.report, request)
        except RunFailed as exc:
            status = 503 if issubclass(exc.kind, Unavailable) else 422
            raise HTTPException(status, {"run_id": exc.run_id, "error": str(exc)}) from exc

    @app.get("/reports", tags=["report"])
    def reports(client_ref: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Stored reports, newest first, optionally for one client."""
        return service.reports(client_ref, limit)

    @app.get("/reports/{artefact_id}/html", tags=["report"], response_class=HTMLResponse)
    def report_html(artefact_id: str) -> HTMLResponse:
        """The rendered report, as a page."""
        return HTMLResponse(guard(service.artefact, artefact_id).html)

    @app.get("/model", tags=["report"])
    def model_status() -> dict[str, Any]:
        """A live probe of the model service: reachable, and serving the configured model."""
        return service.model_status()

    @app.get("/calibration/versions", tags=["report"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/bench/reports", tags=["bench"])
    def bench_reports(limit: int = 200) -> list[dict[str, Any]]:
        """The test bench's picker (REP-43): stored reports by client, with readable labels. Read-only."""
        return service.bench_reports(limit)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    if GOLDEN_REPORTS.is_dir():
        @app.get("/bench/golden", tags=["bench"])
        def bench_golden() -> list[dict[str, Any]]:
            """The golden example pages (development only; the deploy folder has no golden data)."""
            return golden_gallery()

        @app.get("/bench/golden/{name}", tags=["bench"], response_class=HTMLResponse)
        def bench_golden_page(name: str) -> HTMLResponse:
            page = GOLDEN_REPORTS / f"{name}.html"
            if name not in {g["name"] for g in golden_gallery()} or not page.is_file():
                raise HTTPException(404, f"no golden page {name!r}")
            return HTMLResponse(page.read_text(encoding="utf-8"))

    return app
