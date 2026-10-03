"""HTTP surface. Routing only: no maths, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1) first, then the engine specific ones, which are
additive only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import ENGINE_VERSION, contracts as c
from .service import Conflict, InvalidRequest, NotFound, Service, allowlist_report
from .settings import ROOT, Settings, load
from .store import Store

#: Development test bench. Not part of the deploy folder; the route exists only when the file does.
TESTBENCH = ROOT / "testbench" / "index.html"


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load()
    service = Service(settings, Store(settings.database))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield

    app = FastAPI(
        title="sim-tech eigentliCH: Life Balance Sheet (lbs)",
        version=ENGINE_VERSION,
        description=("The client's deterministic life balance sheet: role by capital type, net worth, human "
                     "capital, the two pillars, the property, liquidity and retirement findings, every gap named, "
                     "and a mandate proposal in the shape of pcp-mandate@1.0.0 for the curator. " + c.NOTICE),
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

    # ---- standard endpoints ------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return service.meta(allowlist_report())

    @app.get("/contracts", tags=["standard"])
    def contracts() -> dict[str, Any]:
        models = {"LifeBalanceSheetRequest": c.LifeBalanceSheetRequest, "RunAccepted": c.RunAccepted,
                  "RunStatus": c.RunStatus, "ValidationReport": c.ValidationReport,
                  "LifeBalanceSheet": c.LifeBalanceSheet, "Calibration": c.Calibration}
        inbound = {"LifeBalanceSheetRequest"}
        out: dict[str, Any] = {
            name: {"version": c.CONTRACT_VERSIONS.get(name), "direction": "in" if name in inbound else "out",
                   "schema": model.model_json_schema()} for name, model in models.items()}
        out["Mandate(pcp)"] = {"version": c.CONTRACT_VERSIONS["Mandate(pcp)"], "direction": "mirrored",
                               "note": ("the mandate proposal is shaped to pcp-mandate@1.0.0 (Optimizer pcp); "
                                        "mirrored, never imported"),
                               "bound_sources": c.PCP_BOUND_SOURCE, "vocabularies": c.PCP_VOCABULARIES}
        return out

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.LifeBalanceSheetRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs", tags=["standard"])
    def runs(limit: int = 50) -> list[dict[str, Any]]:
        return service.runs(limit)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.LifeBalanceSheet)
    def artefact(artefact_id: str) -> c.LifeBalanceSheet:
        return guard(service.artefact, artefact_id)

    @app.get("/artefacts/{artefact_id}/request", tags=["lbs"], response_model=c.ArtefactRequest)
    def artefact_request(artefact_id: str) -> c.ArtefactRequest:
        """The request a sheet was built from (LBS-40); its request_hash equals the sheet's."""
        return guard(service.artefact_request, artefact_id)

    @app.get("/calibration", tags=["standard"], response_model=c.Calibration)
    def calibration(version: Optional[str] = None) -> c.Calibration:
        return guard(service.calibration, version)

    @app.put("/calibration", tags=["standard"], response_model=c.Calibration)
    def propose_calibration(proposal: c.Calibration, response: Response) -> c.Calibration:
        stored, created = guard(service.propose_calibration, proposal)
        response.status_code = 201 if created else 200
        return stored

    # ---- engine specific, additive ------------------------------------------

    @app.post("/validate", tags=["lbs"], response_model=c.ValidationReport)
    def validate(request: c.LifeBalanceSheetRequest) -> c.ValidationReport:
        """Every gap and every unavailable section the sheet would carry, without storing anything."""
        return guard(service.validate, request)

    @app.get("/sheet/{artefact_id}", tags=["lbs"], response_model=c.LifeBalanceSheet)
    def sheet(artefact_id: str) -> c.LifeBalanceSheet:
        return guard(service.artefact, artefact_id)

    @app.get("/sheet/{artefact_id}/{section}", tags=["lbs"])
    def sheet_section(artefact_id: str, section: str) -> dict[str, Any]:
        """One view of a sheet: grid, human-capital, pensions, findings, mandate or gaps."""
        return guard(service.section, artefact_id, section)

    @app.get("/records", tags=["lbs"])
    def records(version: Optional[str] = None) -> dict[str, Any]:
        """Each content record's approval state in a calibration."""
        return guard(service.records, version)

    @app.get("/calibration/versions", tags=["lbs"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/bench/candidates", tags=["bench"])
    def bench_candidates(limit: int = 40) -> list[dict[str, Any]]:
        """The test bench's picker (LBS-42): the newest sheet of each client with a readable label. Read-only."""
        return service.bench_candidates(limit)

    if Path(TESTBENCH).is_file():
        @app.get("/", include_in_schema=False)
        def testbench() -> FileResponse:
            return FileResponse(TESTBENCH)

    return app
