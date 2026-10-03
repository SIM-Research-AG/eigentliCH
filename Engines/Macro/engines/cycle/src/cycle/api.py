"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific
reads (engine page section 3), which are additive only.

Build the app with :func:`create_app`; ``python -m cycle`` does so with the port from
``config.yaml``. Tests pass their own settings.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import ENGINE_VERSION, access_log, contracts as c
from .clients import DatafeedClient, MacrofieldClient
from .service import Conflict, InvalidRequest, NotFound, Service, Unavailable, allowlist_report
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the
#: file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None,
               datafeed_transport: Optional[httpx.BaseTransport] = None,
               macrofield_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    # Successful health probes stay out of uvicorn's access log (C-27).
    access_log.install()
    datafeed = DatafeedClient(settings.datafeed_url, settings.datafeed_timeout_s,
                              transport=datafeed_transport)
    macrofield = MacrofieldClient(settings.macrofield_url, settings.macrofield_timeout_s,
                                  transport=macrofield_transport)
    service = Service(settings, Store(settings.database), datafeed, macrofield)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        datafeed.close()
        macrofield.close()

    app = FastAPI(
        title="sim-tech Macro: Cycle Model (cycle)",
        version=ENGINE_VERSION,
        description=("The nested cycles per economy and year, each with its phase, and the cycle "
                     "layer on the 25-bin axis. " + c.NOTICE),
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
        models = {
            "Panel": c.Panel, "MacroState(macrofield)": c.UpstreamMacroState, "CycleRunRequest": c.CycleRunRequest, "RunAccepted": c.RunAccepted,
            "RunStatus": c.RunStatus, "CycleState": c.CycleState, "CurrentPhases": c.CurrentPhases,
            "Calibration": c.Calibration, "ModelCard": c.ModelCard,
        }
        return {name: {"version": {**c.CONTRACT_VERSIONS, "ModelCard": c.MODEL_CARD_VERSION}.get(name), "direction":
                       "in" if name in ("Panel", "MacroState(macrofield)", "CycleRunRequest") else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.CycleRunRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.AnyCycleState)
    def artefact(artefact_id: str) -> c.AnyCycleState:
        """The artefact as it was published: a stored 1.1.0 artefact as 1.1.0 (C-26)."""
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

    @app.get("/model", tags=["cycle"], response_model=c.ModelCard)
    def model(economy: Optional[str] = None, calibration_version: Optional[str] = None) -> c.ModelCard:
        """The model explained on one economy's data: inputs, every step with its formula and
        charts, outputs (``model-card@1.0.0``)."""
        return guard(service.model_card, economy, calibration_version)

    @app.get("/calibration/versions", tags=["cycle"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/cycles/{artefact_id}", tags=["cycle"])
    def cycles(artefact_id: str) -> dict[str, Any]:
        return guard(service.cycles, artefact_id)

    @app.get("/cycles/{artefact_id}/current", tags=["cycle"], response_model=c.CurrentPhases)
    def current(artefact_id: str) -> c.CurrentPhases:
        return guard(service.current, artefact_id)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
