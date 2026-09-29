"""HTTP surface. Routing only: no text handling, no SQL. Everything goes through ``service``.

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
from fastapi.responses import FileResponse

from . import ENGINE_VERSION, contracts as c
from .service import (
    BadModelOutput,
    Conflict,
    InvalidRequest,
    NotFound,
    RunFailed,
    Service,
    Unavailable,
    allowlist_report,
)
from .settings import ROOT, Settings, load
from .spark7 import Spark7Client
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None,
               model_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load()
    model = Spark7Client(settings.model, settings.env, model_transport)
    service = Service(settings, Store(settings.database), model)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield
        service.shutdown()

    app = FastAPI(
        title="eigentliCH ChatBot (chatbot)",
        version=ENGINE_VERSION,
        description=(f"{settings.model.display_name}, the house's AI, answers a client's question from the approved "
                     "knowledge notes the caller chose, and from general knowledge where they do not reach, marked "
                     "as such. Every number in an answer is checked against the grounding and the client facts. "
                     + c.NOTICE),
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
        models = {"ChatRequest": c.ChatRequest, "ChatAnswer": c.ChatAnswer, "RunAccepted": c.RunAccepted,
                  "RunStatus": c.RunStatus, "Calibration": c.Calibration}
        inbound = {"ChatRequest"}
        return {name: {"version": c.CONTRACT_VERSIONS.get(name), "direction": "in" if name in inbound else "out",
                       "schema": model.model_json_schema()} for name, model in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.ChatRequest) -> c.RunAccepted:
        """Answer a question and store the answer. A failed run is reported with status ``failed``; its
        reason is on ``GET /runs/{run_id}``."""
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

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.ChatAnswer)
    def artefact(artefact_id: str) -> c.ChatAnswer:
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

    @app.post("/answer", tags=["chatbot"], response_model=c.ChatAnswer)
    def answer(request: c.ChatRequest) -> c.ChatAnswer:
        """``POST /run`` returning the answer itself. 503 when the model cannot answer now, 502 when it
        answered with nothing usable; both name the failed run."""
        try:
            return guard(service.answer, request)
        except RunFailed as exc:
            status = 503 if issubclass(exc.kind, Unavailable) else 502 if issubclass(exc.kind, BadModelOutput) else 422
            raise HTTPException(status, {"run_id": exc.run_id, "error": str(exc)}) from exc

    @app.get("/model", tags=["chatbot"])
    def model_status() -> dict[str, Any]:
        """A live probe of the model service: reachable, and serving the configured model."""
        return service.model_status()

    @app.get("/calibration/versions", tags=["chatbot"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
