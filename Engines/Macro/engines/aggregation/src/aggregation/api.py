"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific
reads (engine page section 3), which are additive only.

Build the app with :func:`create_app`; ``python -m aggregation`` does so with the port from
``config.yaml``. Tests pass their own settings and transports.
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
from .clients import cycle_client, macrofield_client, mrs_client
from .service import Conflict, InvalidRequest, NotFound, Service, Unavailable, allowlist_report
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the
#: file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None,
               mrs_transport: Optional[httpx.BaseTransport] = None,
               cycle_transport: Optional[httpx.BaseTransport] = None,
               macrofield_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    # Successful health probes stay out of uvicorn's access log (AGG-92).
    access_log.install()
    timeout = settings.upstream_timeout_s
    mrs = mrs_client(settings.mrs_url, timeout, mrs_transport)
    cycle = cycle_client(settings.cycle_url, timeout, cycle_transport)
    macrofield = macrofield_client(settings.macrofield_url, timeout, macrofield_transport)
    service = Service(settings, Store(settings.database), mrs, cycle, macrofield)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        for client in (mrs, cycle, macrofield):
            client.close()

    app = FastAPI(
        title="sim-tech Macro: Aggregation layer (aggregation)",
        version=ENGINE_VERSION,
        description=("Combines the market risk signal (mrs), the cycle model (cycle) and the macro "
                     "field (macrofield) into the Regime, the combined market risk signal; issues the "
                     "regime_id and applies the optimism level. " + c.NOTICE),
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
            "MarketRiskSignal(mrs)": c.MarketRiskSignal, "CycleState(cycle)": c.CycleState,
            "MacroState(macrofield)": c.MacroState, "AggregationRunRequest": c.AggregationRunRequest,
            "RunAccepted": c.RunAccepted, "RunStatus": c.RunStatus, "Regime": c.Regime,
            "Calibration": c.Calibration, "ModelCard": c.ModelCard,
            "ScenarioRequest": c.ScenarioRequest, "ScenarioAccepted": c.ScenarioAccepted,
        }
        inbound = {"MarketRiskSignal(mrs)", "CycleState(cycle)", "MacroState(macrofield)",
                   "AggregationRunRequest", "ScenarioRequest"}
        return {name: {"version": {**c.CONTRACT_VERSIONS, "ModelCard": c.MODEL_CARD_VERSION,
                                    "ScenarioRequest": c.SCENARIO_CONTRACT_VERSION,
                                    "ScenarioAccepted": c.SCENARIO_CONTRACT_VERSION}.get(name),
                       "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.AggregationRunRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs", tags=["standard"])
    def runs(limit: int = 50) -> list[dict[str, Any]]:
        return service.runs(limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.Regime)
    def artefact(artefact_id: str) -> c.Regime:
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

    @app.get("/model", tags=["aggregation"], response_model=c.ModelCard)
    def model(economy: Optional[str] = None) -> c.ModelCard:
        """The aggregation layer explained on one economy: inputs, every step with its formula
        and charts, outputs (``model-card@1.0.0``), from the latest Regime."""
        return guard(service.model_card, economy)

    @app.get("/calibration/versions", tags=["aggregation"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/regime/{regime_id}", tags=["aggregation"], response_model=c.Regime)
    def regime(regime_id: str) -> c.Regime:
        return guard(service.regime, regime_id)

    @app.get("/regime/{regime_id}/path", tags=["aggregation"])
    def path(regime_id: str, economy: Optional[str] = None) -> dict[str, Any]:
        return guard(service.path, regime_id, economy)

    @app.get("/regime/{regime_id}/distribution", tags=["aggregation"])
    def distribution(regime_id: str, date: Optional[str] = None,
                     economy: Optional[str] = None) -> dict[str, Any]:
        return guard(service.distribution, regime_id, date, economy)

    @app.get("/regime/{regime_id}/current", tags=["aggregation"])
    def current(regime_id: str) -> dict[str, Any]:
        return guard(service.current, regime_id)

    @app.get("/regime/{regime_id}/contributions", tags=["aggregation"])
    def contributions(regime_id: str, economy: str, date: Optional[str] = None) -> dict[str, Any]:
        return guard(service.contributions, regime_id, economy, date)

    # ---- scenario Regimes (AGG-19 to AGG-22) --------------------------------

    @app.post("/scenario", tags=["scenario"], response_model=c.ScenarioAccepted)
    def scenario(request: c.ScenarioRequest) -> c.ScenarioAccepted:
        """Derive a scenario Regime from an issued Regime under one of the four policies of
        ``Scenario_SAA.m``; stored and served like any Regime (``GET /regime/{regime_id}``).
        Idempotent: the same base and policy always give the same ``regime_id``."""
        return guard(service.create_scenario, request)

    @app.get("/scenarios/policies", tags=["scenario"], response_model=list[c.ScenarioPolicyInfo])
    def scenario_policies() -> list[c.ScenarioPolicyInfo]:
        return service.scenario_policies()

    @app.get("/scenarios", tags=["scenario"], response_model=list[c.ScenarioListed])
    def scenarios(base: Optional[str] = None) -> list[c.ScenarioListed]:
        """Scenario Regimes, of one base Regime (``?base=RGM-...``) or all."""
        return guard(service.scenarios, base)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
