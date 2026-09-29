"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific
reads (engine page section 3), which are additive only.

Build the app with :func:`create_app`; ``python -m honi`` does so with the port from
``config.yaml``. Tests pass their own settings and a mock transport for ``datafeed``.
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
from .clients import DatafeedClient
from .service import Conflict, InvalidRequest, NotFound, Service, Unavailable, allowlist_report
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the
#: file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None,
               datafeed_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    datafeed = DatafeedClient(settings.datafeed_url, settings.datafeed_timeout_s,
                              transport=datafeed_transport)
    service = Service(settings, Store(settings.database), datafeed)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        datafeed.close()

    app = FastAPI(
        title="sim-tech Macro: Health of Nations Index (honi)",
        version=ENGINE_VERSION,
        description=("Relative health of national economies: fifteen indices, three sectors, "
                     "one national score, 1 to 5. " + c.NOTICE),
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
            "Panel": c.Panel, "HoNIRunRequest": c.HoNIRunRequest, "RunAccepted": c.RunAccepted,
            "RunStatus": c.RunStatus, "HoNIScores": c.HoNIScores, "CountryScores": c.CountryScores,
            "PeerStats": c.PeerStats, "HoNITrends": c.HoNITrends, "Calibration": c.Calibration, "ModelCard": c.ModelCard,
        }
        return {name: {"version": {**c.CONTRACT_VERSIONS, "ModelCard": c.MODEL_CARD_VERSION}.get(name), "direction":
                       "in" if name in ("Panel", "HoNIRunRequest") else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.HoNIRunRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.HoNIScores)
    def artefact(artefact_id: str) -> c.HoNIScores:
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

    @app.get("/model", tags=["honi"], response_model=c.ModelCard)
    def model(economy: Optional[str] = None, calibration_version: Optional[str] = None) -> c.ModelCard:
        """HoNI explained on one economy's data: inputs, every step with its formula and charts,
        outputs (``model-card@1.0.0``)."""
        return guard(service.model_card, economy, calibration_version)

    @app.get("/calibration/versions", tags=["honi"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/scores/{artefact_id}", tags=["honi"])
    def scores(artefact_id: str) -> dict[str, Any]:
        return guard(service.scores, artefact_id)

    @app.get("/scores/{artefact_id}/countries/{code}", tags=["honi"],
             response_model=c.CountryScores)
    def country(artefact_id: str, code: str) -> c.CountryScores:
        return guard(service.country, artefact_id, code)

    @app.get("/saturation/{artefact_id}", tags=["honi"])
    def saturation(artefact_id: str) -> dict[str, Any]:
        return guard(service.saturation, artefact_id)

    @app.get("/ranges", tags=["honi"])
    def ranges(version: Optional[str] = None) -> dict[str, Any]:
        return guard(service.ranges, version)

    @app.get("/peer-stats/{artefact_id}", tags=["honi"], response_model=c.PeerStats)
    def peer_stats(artefact_id: str) -> c.PeerStats:
        return guard(service.peer_stats, artefact_id)

    @app.get("/trends/{artefact_id}", tags=["honi"], response_model=c.HoNITrends)
    def trends(artefact_id: str, window: int = 10, year: Optional[int] = None) -> c.HoNITrends:
        return guard(service.trends, artefact_id, window, year)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
