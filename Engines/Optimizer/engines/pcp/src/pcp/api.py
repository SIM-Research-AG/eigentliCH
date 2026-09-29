"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific ones (engine page
section 3), which are additive only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import ENGINE_VERSION, contracts as c
from .clients import aggregation_client, fmre_client
from .service import Conflict, InvalidRequest, NotFound, Refused, Service, Unavailable, allowlist_report
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None,
               aggregation_transport: Optional[httpx.BaseTransport] = None,
               fmre_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    timeout = settings.upstream_timeout_s
    aggregation = aggregation_client(settings.aggregation_url, timeout, aggregation_transport)
    fmre = fmre_client(settings.fmre_url, timeout, fmre_transport)
    service = Service(settings, Store(settings.database), aggregation, fmre)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        aggregation.close()
        fmre.close()

    app = FastAPI(
        title="sim-tech Optimizer: Portfolio Creation Program (pcp)",
        version=ENGINE_VERSION,
        description=("The curve-fit optimiser: fits a client's target return curve across the 25 regime states "
                     "with the fmre instrument profiles, weighted by the client's blend of the Regime, under "
                     "the mandate's 75-row constraint block. Publishes the Allocation, unreleased. " + c.NOTICE),
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
        except (InvalidRequest, Refused) as exc:
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
        models = {
            "Regime(aggregation)": c.Regime, "ReturnSet(fmre)": c.ReturnSet, "InstrumentOut(fmre)": c.InstrumentOut,
            "Mandate": c.Mandate, "PCPRunRequest": c.PCPRunRequest, "RunAccepted": c.RunAccepted,
            "RunStatus": c.RunStatus, "ValidationReport": c.ValidationReport, "Allocation": c.Allocation,
            "Calibration": c.Calibration,
        }
        inbound = {"Regime(aggregation)", "ReturnSet(fmre)", "InstrumentOut(fmre)", "Mandate", "PCPRunRequest"}
        return {name: {"version": c.CONTRACT_VERSIONS.get(name), "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.PCPRunRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs", tags=["standard"])
    def runs(limit: int = 50) -> list[dict[str, Any]]:
        return service.runs(limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.Allocation)
    def artefact(artefact_id: str) -> c.Allocation:
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

    @app.post("/validate", tags=["pcp"], response_model=c.ValidationReport)
    def validate(request: c.PCPRunRequest) -> c.ValidationReport:
        """Mandate plausibility and constraint feasibility, before running."""
        return guard(service.validate, request)

    @app.get("/allocation/{artefact_id}", tags=["pcp"], response_model=c.Allocation)
    def allocation(artefact_id: str) -> c.Allocation:
        return guard(service.artefact, artefact_id)

    @app.get("/allocation/{artefact_id}/map", tags=["pcp"])
    def allocation_map(artefact_id: str) -> dict[str, Any]:
        return guard(service.allocation_map, artefact_id)

    @app.get("/allocation/{artefact_id}/roles", tags=["pcp"])
    def allocation_roles(artefact_id: str) -> dict[str, Any]:
        return guard(service.allocation_roles, artefact_id)

    @app.get("/allocation/{artefact_id}/diagnostics", tags=["pcp"])
    def allocation_diagnostics(artefact_id: str) -> dict[str, Any]:
        return guard(service.allocation_diagnostics, artefact_id)

    @app.get("/constraints", tags=["pcp"])
    def constraints(version: Optional[str] = None) -> dict[str, Any]:
        """The 75-row constraint block, as configured."""
        return guard(service.constraints, version)

    @app.get("/calibration/versions", tags=["pcp"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
