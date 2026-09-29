"""HTTP surface. Routing only: no rules, no SQL. Everything goes through ``service``.

Standard endpoints (Engine Building Guide section 2.1), then the engine specific ones
(datafeed page section 3), additive only.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import ENGINE_VERSION, contracts as c
from .service import Conflict, InvalidRequest, NotFound, Service
from .settings import Settings, load
from .store import Store


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load()
    service = Service(settings, Store(settings.database))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        yield

    app = FastAPI(title="sim-tech Macro: Data Feed (datafeed)", version=ENGINE_VERSION,
                  description="Immutable snapshots of the source data, served as aligned panels. "
                              "Research data; not investment advice.", lifespan=lifespan)
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

    # ---- standard endpoints --------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return service.meta()

    @app.get("/contracts", tags=["standard"])
    def contracts() -> dict[str, Any]:
        models = {"Panel": c.Panel, "PanelRequest": c.PanelRequest, "SeriesDefinition": c.SeriesDefinition,
                  "Snapshot": c.Snapshot, "SnapshotIn": c.SnapshotIn, "CoverageReport": c.CoverageReport,
                  "Calibration": c.Calibration, "RunAccepted": c.RunAccepted, "RunStatus": c.RunStatus,
                  "Country": c.Country, "SeriesSpec": c.SeriesSpec, "ImportConversion": c.ImportConversion}
        inbound = {"PanelRequest", "SnapshotIn"}
        return {n: {"version": c.CONTRACT_VERSIONS.get(n), "direction": "in" if n in inbound else "out",
                    "schema": m.model_json_schema()} for n, m in models.items()}

    @app.post("/run", tags=["standard"], response_model=c.RunAccepted)
    def run(request: c.PanelRequest) -> c.RunAccepted:
        return guard(service.submit, request)

    @app.get("/runs/{run_id}", tags=["standard"], response_model=c.RunStatus)
    def run_status(run_id: str) -> c.RunStatus:
        return guard(service.run_status, run_id)

    @app.get("/artefacts/{artefact_id}", tags=["standard"], response_model=c.Panel)
    def artefact(artefact_id: str) -> c.Panel:
        return guard(service.artefact, artefact_id)

    @app.get("/calibration", tags=["standard"], response_model=c.Calibration)
    def calibration(version: Optional[str] = None) -> c.Calibration:
        return guard(service.calibration, version)

    @app.put("/calibration", tags=["standard"], response_model=c.Calibration)
    def propose_calibration(proposal: c.Calibration, response: Response) -> c.Calibration:
        stored, created = guard(service.propose_calibration, proposal)
        response.status_code = 201 if created else 200
        return stored

    # ---- engine specific ----------------------------------------------------------

    @app.get("/calibration/versions", tags=["datafeed"])
    def calibration_versions() -> list[dict[str, Any]]:
        return service.calibration_versions()

    @app.get("/countries", tags=["datafeed"], response_model=list[c.Country])
    def countries() -> list[c.Country]:
        """The country registry (table ``country``): the one list every engine uses."""
        return service.countries()

    @app.get("/registry/series", tags=["datafeed"], response_model=list[c.SeriesSpec])
    def registry_series() -> list[c.SeriesSpec]:
        """The series catalogue (table ``series``), independent of country and snapshot."""
        return service.series_specs()

    @app.get("/snapshots", tags=["datafeed"], response_model=list[c.Snapshot])
    def snapshots() -> list[c.Snapshot]:
        return service.snapshots()

    @app.get("/snapshots/{snapshot_id}", tags=["datafeed"], response_model=c.Snapshot)
    def snapshot(snapshot_id: str) -> c.Snapshot:
        return guard(service.snapshot, snapshot_id)

    @app.get("/snapshots/{snapshot_id}/conversions", tags=["datafeed"], response_model=list[c.ImportConversion])
    def conversions(snapshot_id: str) -> list[c.ImportConversion]:
        """What the MATLAB importer did to each series (NaN, zeros, placeholders)."""
        return guard(service.conversions, snapshot_id)

    @app.post("/snapshots", tags=["datafeed"], response_model=c.Snapshot)
    def ingest(body: c.SnapshotIn, response: Response,
               x_admin_token: Optional[str] = Header(default=None)) -> c.Snapshot:
        token = settings.admin_token
        if token is None:
            raise HTTPException(403, f"admin ingest is switched off: set {settings.admin_token_env}")
        if x_admin_token is None or not hmac.compare_digest(x_admin_token, token):
            raise HTTPException(401, "X-Admin-Token missing or wrong")
        manifest, created = guard(service.ingest, body)
        response.status_code = 201 if created else 200
        return manifest

    @app.get("/series", tags=["datafeed"], response_model=list[c.SeriesDefinition])
    def series(snapshot_id: Optional[str] = None, country: Optional[str] = None,
               category: Optional[str] = None, index: Optional[str] = None) -> list[c.SeriesDefinition]:
        return guard(service.series, snapshot_id, country, category, index)

    @app.get("/series/{series_id}", tags=["datafeed"], response_model=list[c.SeriesDefinition])
    def series_one(series_id: str, snapshot_id: Optional[str] = None,
                   country: Optional[str] = None) -> list[c.SeriesDefinition]:
        found = [d for d in guard(service.series, snapshot_id, country) if d.series_id == series_id]
        if not found:
            raise HTTPException(404, f"no series {series_id!r}")
        return found

    @app.get("/panel", tags=["datafeed"], response_model=c.Panel)
    def panel(snapshot_id: str, series: list[str] = Query(default=[]),
              countries: list[str] = Query(default=[]), freq: str = "M",
              start: Optional[str] = None, end: Optional[str] = None) -> c.Panel:
        try:
            request = c.PanelRequest(snapshot_id=snapshot_id, series=tuple(series),
                                     countries=tuple(countries), freq=freq, start=start, end=end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return guard(service.panel, request)

    @app.get("/coverage", tags=["datafeed"], response_model=c.CoverageReport)
    def coverage(snapshot_id: str) -> c.CoverageReport:
        return guard(service.coverage, snapshot_id)

    @app.get("/public", tags=["datafeed"])
    def public() -> list[dict[str, Any]]:
        """Every stored public-source response: where each fill came from."""
        return service.public_fetches()

    return app
