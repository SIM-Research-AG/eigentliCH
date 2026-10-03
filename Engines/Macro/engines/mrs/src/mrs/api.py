"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific
reads (engine page section 3), which are additive only.

Build the app with :func:`create_app`; ``python -m mrs`` does so with the port from
``config.yaml``. Tests pass their own settings and, where needed, a mock transport.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import ENGINE_VERSION, access_log, contracts as c
from .clients import DatafeedClient, UpstreamError
from .service import Conflict, InvalidRequest, NotFound, Service, allowlist_report
from .settings import Settings, load
from .store import Store


def create_app(settings: Optional[Settings] = None,
               datafeed_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    # Successful health probes stay out of uvicorn's access log (MRS-26).
    access_log.install()
    datafeed = DatafeedClient(settings.datafeed_url, settings.upstream_timeout_s,
                              transport=datafeed_transport)
    service = Service(settings, Store(settings.database), datafeed)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        datafeed.close()

    app = FastAPI(
        title="sim-tech Macro: Market Risk Signal (mrs)",
        version=ENGINE_VERSION,
        description=("Publishes the MarketRiskSignal: per economy and month the eleven "
                     "sub-indicators, the four segment signals and a 25-state distribution, "
                     "from datafeed's panel, at zero optimism shift. " + c.NOTICE),
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
        except UpstreamError as exc:
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
            "MRSRunRequest": c.MRSRunRequest, "RunAccepted": c.RunAccepted,
            "RunStatus": c.RunStatus, "RunSummary": c.RunSummary,
            "MarketRiskSignal": c.MarketRiskSignal, "Calibration": c.Calibration,
            "InputReport": c.InputReport, "ModelCard": c.ModelCard, "Panel(datafeed)": c.Panel,
            "CoverageReport(datafeed)": c.UpstreamCoverage,
            "ImportConversion(datafeed)": c.ImportConversion,
        }
        inbound = ("MRSRunRequest", "Panel(datafeed)", "CoverageReport(datafeed)",
                   "ImportConversion(datafeed)")
        return {name: {"version": {**c.CONTRACT_VERSIONS, "ModelCard": c.MODEL_CARD_VERSION}.get(name),
                       "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.MRSRunRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs", tags=["standard"], response_model=list[c.RunSummary])
    def runs(limit: int = Query(default=20, ge=1, le=500)) -> list[c.RunSummary]:
        """Recent runs, newest first: find the latest artefact here."""
        return service.runs(limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.MarketRiskSignal)
    def artefact(artefact_id: str) -> c.MarketRiskSignal:
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

    @app.get("/model", tags=["mrs"], response_model=c.ModelCard)
    def model(economy: Optional[str] = None, calibration_version: Optional[str] = None) -> c.ModelCard:
        """The model explained on one economy's data: inputs, every step with its formula and
        charts, outputs (``model-card@1.0.0``)."""
        return guard(service.model_card, economy, calibration_version)

    @app.get("/input", tags=["mrs"], response_model=c.InputReport)
    def input_report(snapshot_id: Optional[str] = None) -> c.InputReport:
        """The datafeed snapshot mrs reads (default from config.yaml), read live and checked."""
        return guard(service.input_report, snapshot_id)

    @app.get("/calibration/versions", tags=["mrs"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/signal/{artefact_id}/distribution", tags=["mrs"])
    def distribution(artefact_id: str, date: Optional[str] = None,
                     economy: Optional[list[str]] = Query(default=None)) -> dict[str, Any]:
        """25-state distributions at ``date`` (default: the last month), per economy."""
        return guard(service.distribution, artefact_id, date, economy)

    @app.get("/signal/{artefact_id}/segments", tags=["mrs"])
    def segments(artefact_id: str,
                 economy: Optional[list[str]] = Query(default=None)) -> dict[str, Any]:
        """The four segment signals over time, per economy."""
        return guard(service.segments, artefact_id, economy)

    @app.get("/signal/{artefact_id}/current", tags=["mrs"])
    def current(artefact_id: str,
                economy: Optional[list[str]] = Query(default=None)) -> dict[str, Any]:
        """The latest assessed month per economy."""
        return guard(service.current, artefact_id, economy)

    return app
