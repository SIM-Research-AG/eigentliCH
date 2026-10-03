"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific reads,
which are additive only. Build the app with :func:`create_app`; ``python -m macrofield`` does so
with the port from ``config.yaml``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import ENGINE_VERSION, access_log, contracts as c
from .service import Conflict, InvalidRequest, NotFound, Service
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when it does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load()
    # Successful health probes stay out of uvicorn's access log.
    access_log.install()
    service = Service(settings, Store(settings.database))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        service.shutdown()

    app = FastAPI(
        title="sim-tech Macro: Macro Field, three-body capital-saturation model (macrofield)",
        version=ENGINE_VERSION,
        description=("Output, real capital and financial capital as three coupled bodies: "
                     "observed path, calibrated simulation, saturation and phase per economy. "
                     + c.NOTICE),
        lifespan=lifespan,
    )
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"],
                       allow_credentials=False)

    def guard(fn, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidRequest as exc:
            raise HTTPException(422, str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc

    # ---- standard endpoints ------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return service.meta()

    @app.get("/contracts", tags=["standard"])
    def contracts() -> dict[str, Any]:
        models = {"MacroRunRequest": c.MacroRunRequest, "RunAccepted": c.RunAccepted,
                  "RunStatus": c.RunStatus, "MacroState": c.MacroState,
                  "EconomyState": c.EconomyState, "Calibration": c.Calibration,
                  "DataNeed": c.DataNeed, "ProjectionRequest": c.ProjectionRequest,
                  "Projection": c.Projection, "ModelCard": c.ModelCard}
        inbound = ("MacroRunRequest", "ProjectionRequest")
        return {name: {"version": {**c.CONTRACT_VERSIONS, "ModelCard": c.MODEL_CARD_VERSION}.get(name),
                       "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted, status_code=202)
    def run(request: c.MacroRunRequest, response: Response) -> c.RunAccepted:
        accepted = guard(service.submit, request)
        if accepted.status == "succeeded":
            response.status_code = 200
        return accepted

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.MacroState)
    def artefact(artefact_id: str) -> c.MacroState:
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

    @app.get("/calibration/versions", tags=["macrofield"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/runs", tags=["macrofield"])
    def runs(limit: int = 20) -> list[dict[str, Any]]:
        return service.runs(limit)

    @app.get("/model", tags=["macrofield"], response_model=c.ModelCard)
    def model(economy: Optional[str] = None) -> c.ModelCard:
        """The model explained on one economy: inputs, every step with its formula and charts,
        outputs (``model-card@1.0.0``), from the latest successful run."""
        return guard(service.model_card, economy)

    @app.get("/snapshots", tags=["macrofield"])
    def snapshots() -> list[dict[str, Any]]:
        return service.snapshots()

    @app.get("/state/{artefact_id}/current", tags=["macrofield"])
    def current(artefact_id: str) -> dict[str, Any]:
        return guard(service.current, artefact_id)

    @app.get("/state/{artefact_id}/economies/{code}", tags=["macrofield"],
             response_model=c.EconomyState)
    def economy(artefact_id: str, code: str) -> c.EconomyState:
        return guard(service.economy, artefact_id, code)

    @app.post("/project", tags=["macrofield"], response_model=c.Projection)
    def project(request: c.ProjectionRequest) -> c.Projection:
        """What-if: the calibrated model run forward with other levers or horizon. Not stored."""
        return guard(service.project, request)

    @app.get("/data-need", tags=["macrofield"], response_model=c.DataNeed)
    def data_need(snapshot_id: Optional[str] = None,
                  calibration_version: Optional[str] = None) -> c.DataNeed:
        return guard(service.data_need, snapshot_id, calibration_version)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
