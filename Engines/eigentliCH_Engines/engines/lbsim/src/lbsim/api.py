"""HTTP surface (spec 3.7). Routing only: no maths, no SQL. Everything goes through ``service``.

The API process never imports ``lbsim.optim`` or casadi (LBSIM-03); a test checks ``sys.modules``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import ENGINE_VERSION
from . import contracts as c
from .clients import Upstream
from .errors import LbsimError
from .service import Service
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None, upstream: Optional[Upstream] = None) -> FastAPI:
    settings = settings or load()
    service = Service(settings, Store(settings.database), upstream)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield

    app = FastAPI(
        title="sim-tech eigentliCH: LifeBalance Simulator (lbsim)", version=ENGINE_VERSION, lifespan=lifespan,
        description=("What a household's Life Balance Sheet means over time: the deterministic findings, the Monte "
                     "Carlo paths of its wealth under the stated plan in every market Regime, and the background "
                     "plan calculation. " + c.NOTICE))
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"], allow_credentials=False)

    @app.exception_handler(LbsimError)
    async def refused(_: Request, exc: LbsimError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for e in exc.errors():
            where = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
            parts.append(f"{where}: {e.get('msg')}" if where else str(e.get("msg")))
        return JSONResponse(status_code=422, content={"detail": "The request is not valid: " + "; ".join(parts) + "."})

    # ---- standard -----------------------------------------------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return service.meta()

    @app.get("/contracts", tags=["standard"])
    def contracts() -> dict[str, Any]:
        models = {"LifeBalanceSimRequest": c.LifeBalanceSimRequest, "OptimiseRequest": c.OptimiseRequest,
                  "RunAccepted": c.RunAccepted, "RunStatus": c.RunStatus, "ValidationReport": c.ValidationReport,
                  "LifeBalanceFindings": c.LifeBalanceFindings, "LifeBalancePaths": c.LifeBalancePaths,
                  "LifeBalancePlan": c.LifeBalancePlan, "LifeBalanceOutlook": c.LifeBalanceOutlook,
                  "Calibration": c.Calibration}
        inbound = {"LifeBalanceSimRequest", "OptimiseRequest"}
        out: dict[str, Any] = {name: {"version": c.CONTRACT_VERSIONS.get(name),
                                      "direction": "in" if name in inbound else "out",
                                      "schema": model.model_json_schema()} for name, model in models.items()}
        out["upstream"] = {"direction": "mirrored", "contracts": c.UPSTREAM_CONTRACTS,
                           "note": "read with frozen mirrors that ignore extra fields; never imported"}
        return out

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.LifeBalanceSimRequest) -> c.RunAccepted:
        return service.run(request)

    @app.get("/runs", tags=["standard"], response_model=list[c.RunStatus])
    def runs(client_ref: Optional[str] = None, kind: Optional[str] = None, status: Optional[str] = None,
             limit: int = 100) -> list[c.RunStatus]:
        return service.runs(client_ref=client_ref, kind=kind, status=status, limit=limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return service.run_status(run_id)

    @app.post("/runs/{run_id}/cancel", tags=["lbsim"], response_model=c.RunStatus)
    def cancel(run_id: str) -> c.RunStatus:
        """Plan runs only: a queued one stops now, a running one at its next checkpoint."""
        return service.cancel(run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"])
    def artefact(artefact_id: str) -> dict[str, Any]:
        """Typed by prefix: LSF- findings, LSP- paths, LSO- plan."""
        return service.artefact(artefact_id).model_dump(mode="json")

    @app.get("/calibration", tags=["standard"], response_model=c.Calibration)
    def calibration(version: Optional[str] = None) -> c.Calibration:
        return service.calibration(version)

    @app.put("/calibration", tags=["standard"], response_model=c.Calibration)
    def propose_calibration(proposal: c.Calibration, response: Response) -> c.Calibration:
        stored, created = service.propose_calibration(proposal)
        response.status_code = 201 if created else 200
        return stored

    # ---- engine specific ------------------------------------------------------------------------------------

    @app.post("/validate", tags=["lbsim"], response_model=c.ValidationReport)
    def validate(request: c.LifeBalanceSimRequest) -> c.ValidationReport:
        """What can be computed, what is blocked and what is assumed, without storing anything."""
        return service.validate(request)

    @app.get("/outlook", tags=["lbsim"], response_model=c.LifeBalanceOutlook)
    def outlook(client_ref: str, life_balance_sheet_id: Optional[str] = None) -> c.LifeBalanceOutlook:
        """The latest findings, paths and plan state for a sheet (default: the client's newest)."""
        return service.outlook(client_ref, life_balance_sheet_id)

    @app.get("/findings/{artefact_id}", tags=["lbsim"], response_model=c.LifeBalanceFindings)
    def findings(artefact_id: str) -> c.LifeBalanceFindings:
        return service.findings(artefact_id)

    @app.get("/paths/{artefact_id}", tags=["lbsim"], response_model=c.LifeBalancePaths)
    def paths(artefact_id: str) -> c.LifeBalancePaths:
        return service.paths(artefact_id)

    @app.get("/paths/{artefact_id}/fan", tags=["lbsim"])
    def fan(artefact_id: str, regime: str = "base", basis: str = "nominal",
            series: str = "goal_measure") -> dict[str, Any]:
        """One chart's series: the bands of one Regime in one basis, and the goal line."""
        return service.fan(artefact_id, regime=regime, basis=basis, series=series)

    @app.get("/plans/{artefact_id}", tags=["lbsim"], response_model=c.LifeBalancePlan)
    def plans(artefact_id: str) -> c.LifeBalancePlan:
        return service.plan(artefact_id)

    @app.post("/optimise", tags=["lbsim"], response_model=c.RunAccepted)
    def optimise(request: c.OptimiseRequest) -> c.RunAccepted:
        """A plan run on demand. Idempotent: a finished plan for the same key is ``cached``; a queued or running
        one is returned as it is."""
        return service.optimise(request)

    @app.get("/calibration/versions", tags=["lbsim"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    if TESTBENCH.is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
