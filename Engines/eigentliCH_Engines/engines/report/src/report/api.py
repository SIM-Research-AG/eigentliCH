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


def create_app(settings: Optional[Settings] = None,
               upstream_transports: Optional[dict[str, httpx.BaseTransport]] = None,
               model_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    upstream = engine_clients({"pcp": settings.pcp_url, "lbs": settings.lbs_url}, settings.upstream_timeout_s,
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
                  "ReportRequest": c.ReportRequest, "Report": c.Report, "RunAccepted": c.RunAccepted,
                  "RunStatus": c.RunStatus, "Calibration": c.Calibration}
        inbound = {"Allocation(pcp)", "LifeBalanceSheet(lbs)", "ReportRequest"}
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

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
