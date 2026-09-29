"""HTTP surface of the cockpit. Routing only: no maths, and no model figure of its own.

    /                         the single page front end
    /api/config               roster, mode and CIO defaults for the front end
    /api/graph                every engine's /health and /meta: the system status view
    /api/decisions            the CIO's decision log (optimiser bounds, instrument shortlists)
    /api/export/...           Excel workbooks laid out from engine endpoints
    /api/launcher/...         start engines, read their logs (the desktop app's supervisor)
    /api/curator/...          the curator workflow on schema eigentlich, as role curator (C-16)
    /api/cio/...              the CIO's writes to an engine the proxy cannot name (C-32)
    /api/{engine}/{path}      proxy, so the browser talks to one origin
    /bench/{engine}/          the engine's own test bench, pointed at the proxy

Build the app with :func:`create_app`; ``python -m cockpit`` does so from ``config.yaml``.
Tests pass their own settings and a mock transport for the engines.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import __version__
from .clients import Engines, _describe
from .curator import CuratorStore, Refused, Unavailable
from .decisions import DecisionIn, DecisionLog
from .export import NOTICE, decision_workbook, honi_workbook, instruments_workbook
from .launcher import Launcher
from .mandate import DEFAULT_BASIS, PRESET_KEYS, MandateForm, Problem, assemble, to_form, vocabulary
from .regime import LEVELS, RegimeProblem, choose, levels as regime_levels, regime_level
from .settings import STATIC, Settings, load

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: Hop-by-hop and length headers the proxy must not copy onto its own response.
DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive",
        "server", "date"}


# ---- curator request bodies (C-16): every write names the acting curator -------------------

class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    curator_id: str = Field(min_length=1, description="the acting curator; the database refuses a revoked one")


class ThreadAnswer(_Body):
    body: str = Field(min_length=1)
    language: str = "de"
    in_reply_to_id: Optional[str] = None
    close: bool = False


class Acting(_Body):
    pass


class OutlookIn(_Body):
    """The lbsim outlook through the consumer app (C-34). ``optimise: "now"`` asks for a priority plan
    run recorded as the acting curator's ("Planrechnung neu starten"); left out, the app decides as it
    does after a new sheet (the plan runs in the background)."""
    optimise: Optional[Literal["now"]] = None


class ApprovalNote(_Body):
    note: Optional[str] = None


class Revision(_Body):
    note: Optional[str] = None
    body: Optional[str] = None
    revision_item_id: Optional[str] = None
    language: str = "de"


class ParameterSetIn(_Body):
    engine: str = "pcp"
    contract_version: str = "pcp-mandate@1.0.0"
    body: dict[str, Any]
    note: Optional[str] = None


class RunIn(_Body):
    engine: Literal["pcp"] = "pcp"
    parameter_set_id: Optional[str] = None
    #: Named, the Regime is used as it is. Left out, the cockpit takes the latest succeeded Regime of
    #: ``optimism`` (``default`` when that is left out too), derives ``regime_policy``'s scenario from
    #: it, and fetches the ReturnSet fmre serves for it in the mandate's currency (C-30).
    regime_id: Optional[str] = Field(default=None, min_length=1)
    return_set_id: Optional[str] = Field(default=None, min_length=1)
    optimism: Optional[Literal[LEVELS]] = None  # type: ignore[valid-type]
    speed_mode: Optional[Literal["fast", "exact"]] = None
    date: Optional[str] = None
    #: The page's context for this run, never forwarded to pcp (its request forbids extra fields): the
    #: currency the ReturnSet was fetched in, and the scenario policy and base Regime when the chosen
    #: Regime is one of aggregation's scenario Regimes (C-23, C-24).
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    regime_policy: Optional[str] = None
    base_regime_id: Optional[str] = None
    #: The basis the page fetched the ReturnSet in (C-31), context like ``currency``: it must be the
    #: finalised mandate's ``basis`` (nominal when the mandate names none).
    basis: Optional[Literal["nominal", "real"]] = None


class MandateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mandate: dict[str, Any]


class ContentIn(_Body):
    key: str = Field(min_length=1)
    kind: Literal["questionnaire", "scoring_map", "reference", "knowledge"]
    body: dict[str, Any]
    note: Optional[str] = None


class InflationBetaIn(BaseModel):
    """The CIO's inflation pass-through override for one instrument (C-32), in fmre's own names
    (``PUT /v1/inflation-beta/{instrument_id}``). ``beta`` null reverts to the house beta; ``set_by``
    is the acting curator. fmre keeps every version (append-only); the cockpit keeps nothing."""
    model_config = ConfigDict(extra="forbid")
    beta: Optional[float] = Field(ge=0, le=1.5, description="0 to 1.5; null reverts to the house beta")
    duration: Optional[float] = Field(default=None, ge=0, le=30, description="years; left out keeps the house duration")
    reason: str = Field(min_length=1, description="required, for a set and for a revert")
    set_by: str = Field(min_length=1, description="the acting curator")

    @field_validator("reason", "set_by")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


#: lbsim's RunStatus lists its artefacts (``artefact_ids``) rather than naming one. The engine_run keeps
#: the one a page opens: the plan, else the paths, else the findings (INTERFACES section 5).
_ARTEFACT_ORDER = ("LSO-", "LSP-", "LSF-")


def _main_artefact(ids: Any) -> Optional[str]:
    ids = [i for i in (ids or ()) if isinstance(i, str) and i]
    for prefix in _ARTEFACT_ORDER:
        hit = next((i for i in ids if i.startswith(prefix)), None)
        if hit:
            return hit
    return ids[-1] if ids else None


def create_app(settings: Optional[Settings] = None,
               transport: Optional[httpx.AsyncBaseTransport] = None,
               launcher: Optional[Launcher] = None,
               curator: Optional[CuratorStore] = None) -> FastAPI:
    settings = settings or load()
    engines = Engines(settings, transport=transport)
    log = DecisionLog(settings.data_dir)
    launcher = launcher or Launcher(settings)
    curator = curator or CuratorStore(settings.curator_db)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await engines.close()

    app = FastAPI(title="sim-tech cockpit", version=__version__, lifespan=lifespan,
                  description="CIO workspace, engine status and test benches behind one origin. "
                              + NOTICE)
    app.state.settings = settings
    app.state.last_heartbeat = None
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def engine_or_404(key: str):
        engine = settings.engine(key)
        if engine is None:
            raise HTTPException(404, f"no engine {key!r} in the cockpit's roster")
        return engine

    async def fetch(key: str, path: str) -> Any:
        engine = engine_or_404(key)
        try:
            return await engines.get_json(engine, path)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"{key}{path} answered {exc.response.status_code}: "
                                     f"{exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"{key} is {_describe(exc)} at {engine.url}") from exc

    async def optional(key: str, path: str) -> Any:
        """An engine read an export can do without: None when the engine is not there."""
        try:
            return await fetch(key, path)
        except HTTPException:
            return None

    def attachment(data: bytes, filename: str) -> Response:
        return Response(data, media_type=XLSX,
                        headers={"content-disposition": f'attachment; filename="{filename}"'})

    # ---- front end -----------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"cache-control": "no-cache"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC / "cockpit.ico")

    @app.get("/bench/{key}/", include_in_schema=False)
    def bench(key: str) -> FileResponse:
        engine = engine_or_404(key)
        if settings.mode != "development":
            raise HTTPException(404, "test benches are shown in development mode only")
        if engine.bench is None or not engine.bench.is_file():
            raise HTTPException(404, f"{key} has no test bench")
        return FileResponse(engine.bench, headers={"cache-control": "no-cache"})

    # ---- cockpit's own reads --------------------------------------------------------

    @app.get("/api/config", tags=["cockpit"])
    def config() -> dict[str, Any]:
        return {"cockpit_version": __version__, "mode": settings.mode, "notice": NOTICE,
                "cio": {"snapshot": settings.cio_snapshot, "writable": list(settings.cio_writable)},
                "engines": [e.public() for e in settings.engines],
                "curator_db": settings.curator_db.public(),
                "config_sources": list(settings.sources)}

    @app.get("/api/graph", tags=["cockpit"])
    async def graph() -> dict[str, Any]:
        probes = await engines.probe_all()
        nodes = [{**e.public(), **probes[e.key]} for e in settings.engines]
        edges = [[up, e.key] for e in settings.engines for up in e.consumes]
        return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": settings.mode,
                "nodes": nodes, "edges": edges, "launched": launcher.state()}

    # ---- decisions ------------------------------------------------------------------

    @app.get("/api/decisions", tags=["cockpit"])
    def decisions(kind: Optional[str] = None) -> list[dict[str, Any]]:
        return [d.model_dump() for d in log.list(kind)]

    @app.get("/api/decisions/{decision_id}", tags=["cockpit"])
    def decision(decision_id: str) -> dict[str, Any]:
        d = log.get(decision_id)
        if d is None:
            raise HTTPException(404, f"no decision {decision_id}")
        return d.model_dump()

    @app.post("/api/decisions", tags=["cockpit"], status_code=201)
    async def save_decision(request: Request) -> dict[str, Any]:
        try:
            body = DecisionIn.model_validate_json(await request.body())
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return log.append(body).model_dump()

    # ---- exports --------------------------------------------------------------------

    @app.get("/api/export/honi/{artefact_id}.xlsx", tags=["export"])
    async def export_honi(artefact_id: str, run_id: Optional[str] = None) -> Response:
        artefact = await fetch("honi", f"/artefacts/{artefact_id}")
        peers = await fetch("honi", f"/peer-stats/{artefact_id}")
        version = artefact["provenance"]["calibration_version"]
        ranges = await fetch("honi", f"/ranges?version={version}")
        run = await fetch("honi", f"/runs/{run_id}") if run_id else None
        trends = await fetch("honi", f"/trends/{artefact_id}?window=10")
        register = await optional("fmre", "/v1/instruments")
        wb = honi_workbook(artefact, peers, ranges, run, trends, register)
        return attachment(wb.to_bytes(), f"HoNI_{artefact_id}_{date.today():%Y-%m-%d}.xlsx")

    @app.get("/api/export/instruments.xlsx", tags=["export"])
    async def export_instruments(shortlist: Optional[str] = None,
                                 honi_artefact: Optional[str] = None) -> Response:
        register = await fetch("fmre", "/v1/instruments")
        performance = await fetch("fmre", "/v1/data/performance")
        classification = await fetch("fmre", "/v1/data/classification")
        overlap = await fetch("fmre", "/v1/data/overlap")
        return_set = await fetch("fmre", "/v1/return-set")
        axis = await fetch("fmre", "/v1/axis")
        pick = None
        if shortlist:
            d = log.get(shortlist)
            if d is None or d.kind != "instrument_selection":
                raise HTTPException(404, f"no instrument shortlist {shortlist}")
            pick = d.model_dump()
        trends = await fetch("honi", f"/trends/{honi_artefact}?window=10") if honi_artefact else None
        wb = instruments_workbook(register, performance, classification, overlap, return_set, axis,
                                  pick, trends)
        return attachment(wb.to_bytes(), f"Instruments_{date.today():%Y-%m-%d}.xlsx")

    @app.get("/api/export/decisions/{decision_id}.xlsx", tags=["export"])
    def export_decision(decision_id: str) -> Response:
        d = log.get(decision_id)
        if d is None:
            raise HTTPException(404, f"no decision {decision_id}")
        return attachment(decision_workbook(d.model_dump()).to_bytes(), f"{decision_id}.xlsx")

    # ---- launcher -------------------------------------------------------------------

    @app.get("/api/launcher", tags=["launcher"])
    def launched() -> list[dict[str, Any]]:
        return launcher.state()

    @app.post("/api/launcher/heartbeat", tags=["launcher"], include_in_schema=False)
    def heartbeat() -> dict[str, bool]:
        app.state.last_heartbeat = time.monotonic()
        return {"ok": True}

    @app.post("/api/launcher/{key}/start", tags=["launcher"])
    def start(key: str) -> dict[str, Any]:
        try:
            return launcher.start(engine_or_404(key))
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/launcher/{key}/log", tags=["launcher"])
    def log_tail(key: str, lines: int = 80) -> dict[str, Any]:
        engine_or_404(key)
        return {"key": key, "log": launcher.log_tail(key, min(max(lines, 1), 1000))}

    # ---- curator workflow (C-16) --------------------------------------------------------
    # Schema eigentlich, read and written directly as role curator. Allowed in both modes: this
    # is the curator's production work, as the decision log is the CIO's (C-02, C-16). The rules
    # are the database's; a refusal comes back with the database's own message.

    def db(fn, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except Refused as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.get("/api/curator/status", tags=["curator"])
    def curator_status() -> dict[str, Any]:
        return curator.status()

    @app.get("/api/curator/curators", tags=["curator"])
    def curators() -> list[dict[str, Any]]:
        return db(curator.curators)

    @app.get("/api/curator/clients", tags=["curator"])
    def curator_clients(q: str = "", open_only: bool = False, archived: bool = False) -> list[dict[str, Any]]:
        return db(curator.clients, q.strip(), open_only, archived)

    @app.get("/api/curator/clients/{client_id}", tags=["curator"])
    def curator_client(client_id: str) -> dict[str, Any]:
        return db(curator.client, client_id)

    @app.post("/api/curator/clients/{client_id}/sessions", tags=["curator"], status_code=201)
    def curator_session(client_id: str, body: Acting) -> dict[str, Any]:
        return db(curator.open_session, client_id, body.curator_id)

    @app.post("/api/curator/threads/{thread_id}/messages", tags=["curator"], status_code=201)
    def curator_answer(thread_id: str, body: ThreadAnswer) -> dict[str, Any]:
        return db(curator.answer_thread, thread_id, body.curator_id, body.body, body.language,
                  body.in_reply_to_id, body.close)

    @app.post("/api/curator/threads/{thread_id}/close", tags=["curator"])
    def curator_close(thread_id: str, body: Acting) -> dict[str, Any]:
        return db(curator.close_thread, thread_id, body.curator_id)

    @app.get("/api/curator/reports/{report_id}", tags=["curator"])
    def curator_report(report_id: str) -> dict[str, Any]:
        return db(curator.report, report_id)

    @app.get("/api/curator/approvals", tags=["curator"])
    def curator_approvals(state: Optional[str] = "awaiting_curator") -> list[dict[str, Any]]:
        return db(curator.approvals, state or None)

    @app.post("/api/curator/approvals/{request_id}/approve", tags=["curator"], status_code=201)
    def curator_approve(request_id: str, body: ApprovalNote) -> dict[str, Any]:
        return db(curator.approve, request_id, body.curator_id, body.note)

    @app.post("/api/curator/approvals/{request_id}/revise", tags=["curator"], status_code=201)
    def curator_revise(request_id: str, body: Revision) -> dict[str, Any]:
        return db(curator.revise, request_id, body.curator_id, body.note, body.body, body.revision_item_id,
                  body.language)

    @app.get("/api/curator/clients/{client_id}/parameter-sets", tags=["curator"])
    def curator_parameter_sets(client_id: str, engine: str = "pcp") -> list[dict[str, Any]]:
        return db(curator.parameter_sets, client_id, engine)

    @app.post("/api/curator/clients/{client_id}/parameter-sets", tags=["curator"], status_code=201)
    def curator_finalise(client_id: str, body: ParameterSetIn) -> dict[str, Any]:
        return db(curator.finalise, client_id, body.engine, body.contract_version, body.body, body.curator_id,
                  body.note)

    async def outcome_of(row: dict[str, Any], engine_key: str, accepted: dict[str, Any]) -> dict[str, Any]:
        """Record what the engine answered: succeeded with its artefact, failed with its error, or
        still running under its run id (refreshed later)."""
        status, run_id = accepted.get("status"), accepted.get("run_id")
        artefact_id = accepted.get("artefact_id") or _main_artefact(accepted.get("artefact_ids"))
        if status == "succeeded" and artefact_id:
            return await run_in_threadpool(db, curator.advance_run, row["id"], "succeeded", run_id, artefact_id)
        if status == "failed":
            error = accepted.get("error")
            if accepted.get("failure_kind"):   # lbsim's RunStatus names why (timed_out, superseded, ...)
                error = f"{accepted['failure_kind']}: {error}" if error else str(accepted["failure_kind"])
            if not error and run_id:
                try:
                    error = (await engines.get_json(engine_or_404(engine_key), f"/runs/{run_id}")).get("error")
                except (httpx.HTTPError, ValueError):
                    error = None
            return await run_in_threadpool(db, curator.advance_run, row["id"], "failed", run_id, None,
                                           error or f"{engine_key} reported the run as failed")
        return await run_in_threadpool(db, curator.advance_run, row["id"], "running", run_id)

    @app.get("/api/curator/regime", tags=["curator"])
    async def curator_regime(optimism: Optional[str] = None, policy: Optional[str] = None) -> dict[str, Any]:
        """The Regime a pcp run uses (C-30): the latest succeeded Regime of the optimism level
        (``default`` when none is named), read from aggregation by the Regime's own
        ``optimism_scale``, and with ``policy`` the scenario derived from it. The run route makes the
        same choice when its caller names no Regime. ``levels`` lists the four levels for the page."""
        agg = engine_or_404("aggregation")
        try:
            chosen = await choose(engines, agg, optimism or None, policy or None)
        except RegimeProblem as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return {**chosen, "levels": await regime_levels(engines, agg)}

    @app.post("/api/curator/clients/{client_id}/runs", tags=["curator"], status_code=201)
    async def curator_run(client_id: str, body: RunIn) -> dict[str, Any]:
        """Run pcp on the client's finalised mandate and record the call as an ``engine_run``.

        The row is written first, so a revoked curator is refused before pcp is called; pcp's answer
        (or its absence) is recorded on the same row. In cio mode this is the one way to run pcp from
        the cockpit (``pcp:/run`` is not in ``cio.writable``, C-16). With no ``regime_id`` the Regime
        is the latest succeeded one of ``optimism`` (``default`` unless named), as on the page (C-30)."""
        pset = (await run_in_threadpool(db, curator.parameter_set, body.parameter_set_id) if body.parameter_set_id
                else await run_in_threadpool(db, curator.current_parameter_set, client_id, body.engine))
        if pset is None:
            raise HTTPException(409, "no finalised parameter set for this client: finalise the mandate first")
        if pset["client_id"] != client_id or pset["engine"] != body.engine:
            raise HTTPException(409, f"parameter set {pset['id']} is not a {body.engine} set of this client")
        mandate_currency = (pset["body"] or {}).get("currency", "CHF")
        mandate_basis = (pset["body"] or {}).get("basis") or DEFAULT_BASIS   # absent means nominal (C-31)
        if body.basis and body.basis != mandate_basis:
            raise HTTPException(409, f"the ReturnSet was fetched on a {body.basis} basis, but the finalised mandate is "
                                     f"{mandate_basis}: fetch the ReturnSet with basis={mandate_basis}, or finalise the "
                                     f"mandate as {body.basis} first")
        if body.currency and body.currency != mandate_currency:
            raise HTTPException(409, f"the ReturnSet was fetched in {body.currency}, but the finalised mandate is in "
                                     f"{mandate_currency}: fetch the ReturnSet in {mandate_currency}, or finalise the "
                                     f"mandate in {body.currency} first")
        regime_id, return_set_id, optimism = body.regime_id, body.return_set_id, body.optimism
        policy, base_regime_id = body.regime_policy, body.base_regime_id
        agg = settings.engine("aggregation")
        await run_in_threadpool(db, curator.acting, client_id, body.curator_id)  # a revoked curator asks no engine
        if regime_id is None:
            # No Regime named: the same choice as the Parameters page (C-30), the latest succeeded Regime
            # of the named optimism level, default when none is named, never aggregation's newest run.
            if return_set_id is not None:
                raise HTTPException(422, "a ReturnSet is stamped for one Regime: name the regime_id with the "
                                         "return_set_id, or leave both out and the cockpit chooses them")
            if agg is None:
                raise HTTPException(503, "the roster names no aggregation: name the regime_id and return_set_id")
            try:
                chosen = await choose(engines, agg, optimism, policy)
            except RegimeProblem as exc:
                raise HTTPException(exc.status, exc.detail) from exc
            regime_id, optimism = chosen["regime_id"], chosen["optimism"]
            policy = chosen["policy"]
            base_regime_id = chosen["base_regime_id"] if policy else None
            fmre = settings.engine("fmre")
            if fmre is None:
                raise HTTPException(503, "the roster names no fmre: name the regime_id and return_set_id")
            query = httpx.QueryParams({"regime_id": regime_id, "include_instruments": "true",
                                       "include_blocks": "false", "currency": mandate_currency,
                                       # basis= only when real, as pcp asks fmre itself: a nominal query stays
                                       # exactly what it was, so the ReturnSet id pcp fetches is the same (C-31)
                                       **({"basis": mandate_basis} if mandate_basis != DEFAULT_BASIS else {})})
            served = await fetch("fmre", f"/v1/return-set?{query}")
            served_basis = (served.get("provenance") or {}).get("basis") or DEFAULT_BASIS
            if served_basis != mandate_basis:   # pcp refuses it too; say so before pcp is asked (C-31)
                raise HTTPException(409, f"fmre served the ReturnSet {served.get('return_set_id')} on a {served_basis} "
                                         f"basis for a {mandate_basis} mandate: fmre does not serve basis="
                                         f"{mandate_basis} yet, so pcp would refuse it")
            return_set_id = served["return_set_id"]
        elif agg is not None:
            # A Regime named: say which level it is (the Regime's own optimism_scale); a named level
            # that is not the Regime's is refused before pcp is asked.
            try:
                actual = await regime_level(engines, agg, regime_id)
            except RegimeProblem:
                actual = None
            if optimism and actual and actual != optimism:
                raise HTTPException(409, f"Regime {regime_id} is at optimism level {actual!r}, not {optimism!r}")
            optimism = actual or optimism
        context = {"regime_id": regime_id, "regime_policy": policy,
                   "base_regime_id": base_regime_id, "return_set_id": return_set_id,
                   "currency": body.currency or mandate_currency, "basis": mandate_basis}
        if optimism:
            context["optimism"] = optimism
        request = {"regime_id": regime_id, "return_set_id": return_set_id, "mandate": pset["body"]}
        if body.speed_mode:
            request["speed_mode"] = body.speed_mode
        if body.date:
            request["date"] = body.date
        row = await run_in_threadpool(db, curator.start_run, client_id, body.engine, request, body.curator_id,
                                      pset["id"])
        row = await run_in_threadpool(db, curator.advance_run, row["id"], "running")
        engine = engine_or_404(body.engine)

        async def call() -> dict[str, Any]:
            try:
                r = await engines.forward(engine, "POST", "run", "", json.dumps(request).encode("utf-8"),
                                          "application/json")
            except httpx.HTTPError as exc:
                return await run_in_threadpool(db, curator.advance_run, row["id"], "failed", None, None,
                                               f"{body.engine} is {_describe(exc)} at {engine.url}")
            if r.status_code >= 400:
                return await run_in_threadpool(db, curator.advance_run, row["id"], "failed", None, None,
                                               f"{body.engine} /run answered {r.status_code}: {r.text[:2000]}")
            try:
                accepted = r.json()
            except ValueError:
                return await run_in_threadpool(db, curator.advance_run, row["id"], "failed", None, None,
                                               f"{body.engine} /run did not answer JSON")
            return await outcome_of(row, body.engine, accepted)

        # The engine_run row is exactly what pcp was sent; the page's context (the Regime's policy, the
        # ReturnSet's currency) is answered alongside, for the page to show (C-23).
        return {**(await call()), "context": context}

    @app.post("/api/curator/runs/{run_row_id}/refresh", tags=["curator"])
    async def curator_run_refresh(run_row_id: str) -> dict[str, Any]:
        """Ask the engine again about a run that was still running when it was recorded."""
        row = await run_in_threadpool(db, curator.engine_run, run_row_id)
        if row["status"] in ("succeeded", "failed") or not row["run_id"]:
            return row
        try:
            status = await engines.get_json(engine_or_404(row["engine"]), f"/runs/{row['run_id']}")
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"{row['engine']} could not be asked about run {row['run_id']}: {exc}") from exc
        return await outcome_of(row, row["engine"], status)

    @app.post("/api/curator/clients/{client_id}/balance-sheet", tags=["curator"], status_code=201)
    async def curator_balance_sheet(client_id: str, body: Acting) -> dict[str, Any]:
        """Compute the client's Life Balance Sheet on demand, through the consumer app (C-20).

        The app builds the lbs request from the client's data and records the call as an
        ``engine_run``; the cockpit builds nothing and writes nothing here. It checks the client and
        the acting curator first (so a revoked curator never reaches the app), calls the app's
        ``POST /api/clients/{id}/balance-sheet``, and answers with the run the app recorded and the
        sheet it returned. When the app recorded a failed run (lbs down or refusing), that run is the
        answer, with ``error``; when the app is not there at all, 503 and nothing is recorded."""
        await run_in_threadpool(db, curator.acting, client_id, body.curator_id)
        app_entry = next((e for e in settings.engines if e.kind == "app"), None)
        if app_entry is None:
            raise HTTPException(503, "the roster names no consumer app (kind: app): lbs runs through it (C-20)")
        before = await run_in_threadpool(db, curator.latest_run, client_id, "lbs")
        try:
            payload = json.dumps({"curator_id": body.curator_id}).encode("utf-8")
            r = await engines.forward(app_entry, "POST", f"api/clients/{client_id}/balance-sheet", "", payload,
                                      "application/json")
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"The consumer app ({app_entry.key}) is {_describe(exc)} at {app_entry.url}, so no "
                                     "balance sheet was computed and nothing was recorded. lbs runs through the app: "
                                     "start it on the Consumer app page, then try again.") from exc
        try:
            answer = r.json()
        except ValueError:
            answer = {"detail": r.text[:2000]}
        after = await run_in_threadpool(db, curator.latest_run, client_id, "lbs")
        run = after if after is not None and (before is None or after["id"] != before["id"]) else None
        if r.status_code >= 400:
            detail = answer.get("detail", answer) if isinstance(answer, dict) else answer
            if isinstance(detail, dict) and "error" in detail:
                detail = f"{detail.get('engine', 'an engine')}: {detail['error']}"
            message = f"the consumer app answered {r.status_code}: {detail if isinstance(detail, str) else json.dumps(detail)[:2000]}"
            if run is None:  # refused before any lbs call was recorded (no such client, invalid data, store down)
                raise HTTPException(r.status_code if r.status_code in (404, 409, 422) else 502, message)
            return {"engine_run": run, "balance_sheet": None, "error": message}
        return {"engine_run": run, "balance_sheet": answer, "error": None}

    @app.post("/api/curator/clients/{client_id}/outlook", tags=["curator"], status_code=201)
    async def curator_outlook(client_id: str, body: OutlookIn) -> dict[str, Any]:
        """Ask for the client's lbsim outlook through the consumer app (C-34, the C-20 pattern).

        lbsim requests are built only in the app: it takes the client's newest sheet and the base-Regime
        Allocation of the current parameter set, calls lbsim and records every call as an ``engine_run``
        (engine ``lbsim``: the fast run, and the plan run under its own run id, refreshed later through
        ``/api/curator/runs/{id}/refresh``). The cockpit checks the client and the acting curator first,
        sends ``{"curator_id"}`` (and ``"optimise": "now"`` for a priority plan run) to the app's
        ``POST /api/clients/{id}/outlook``, and answers with the lbsim runs the app recorded during the
        call and what it returned. The app not there: 503, nothing recorded."""
        await run_in_threadpool(db, curator.acting, client_id, body.curator_id)
        app_entry = next((e for e in settings.engines if e.kind == "app"), None)
        if app_entry is None:
            raise HTTPException(503, "the roster names no consumer app (kind: app): lbsim runs through it (C-34)")
        before = {r["id"] for r in await run_in_threadpool(db, curator.recent_runs, client_id, "lbsim")}
        payload = {"curator_id": body.curator_id, **({"optimise": body.optimise} if body.optimise else {})}
        try:
            r = await engines.forward(app_entry, "POST", f"api/clients/{client_id}/outlook", "",
                                      json.dumps(payload).encode("utf-8"), "application/json")
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"The consumer app ({app_entry.key}) is {_describe(exc)} at {app_entry.url}, so no "
                                     "outlook was asked for and nothing was recorded. lbsim runs through the app: "
                                     "start it on the Consumer app page, then try again.") from exc
        try:
            answer = r.json()
        except ValueError:
            answer = {"detail": r.text[:2000]}
        runs = [x for x in await run_in_threadpool(db, curator.recent_runs, client_id, "lbsim") if x["id"] not in before]
        if r.status_code >= 400:
            detail = answer.get("detail", answer) if isinstance(answer, dict) else answer
            if isinstance(detail, dict) and "error" in detail:
                detail = f"{detail.get('engine', 'an engine')}: {detail['error']}"
            message = f"the consumer app answered {r.status_code}: {detail if isinstance(detail, str) else json.dumps(detail)[:2000]}"
            if not runs:   # refused before any lbsim call was recorded (no sheet, no such client, store down)
                raise HTTPException(r.status_code if r.status_code in (404, 409, 422) else 502, message)
            return {"engine_runs": runs, "outlook": None, "error": message}
        return {"engine_runs": runs, "outlook": answer, "error": None}

    # ---- the Parameters form (C-21, C-22): unit conversion only, plain Python, no store ---------

    @app.get("/api/curator/mandate/vocabulary", tags=["curator"])
    def mandate_vocabulary() -> dict[str, Any]:
        return vocabulary()

    @app.post("/api/curator/mandate/assemble", tags=["curator"])
    def mandate_assemble(form: MandateForm) -> dict[str, Any]:
        """The form (percent, percent per year) as pcp's Mandate (fractions, log returns). 422 with
        ``problems`` (field and message) when a field cannot be converted; pcp judges the rest."""
        try:
            return {"mandate": assemble(form), "conversion": vocabulary()["conversion"]}
        except Problem as exc:
            raise HTTPException(422, {"problems": exc.problems}) from exc

    @app.post("/api/curator/mandate/form", tags=["curator"])
    def mandate_form(body: MandateIn) -> dict[str, Any]:
        """A stored Mandate (parameter set, preset, lbs proposal) in the form's units."""
        return to_form(body.mandate)

    @app.get("/api/curator/presets", tags=["curator"])
    def curator_presets() -> dict[str, Any]:
        """The current target-curve and mandate presets from the content store (C-22), each with its
        version; a key never saved is answered as missing, not as an error."""
        out: dict[str, Any] = {}
        for name, key in PRESET_KEYS.items():
            try:
                row = db(curator.content_version, key)
                out[name] = {"key": key, "version": row["version"], "saved_at": row["saved_at"],
                             "saved_by_ref": row["saved_by_ref"], "body": row["body"]}
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                out[name] = {"key": key, "version": None, "missing": f"{key} is not in the content store yet: "
                                                                     "run python dev/build_presets.py --save"}
        return out

    @app.get("/api/curator/content", tags=["curator"])
    def curator_content(kind: Optional[str] = None) -> list[dict[str, Any]]:
        return db(curator.content_keys, kind)

    @app.get("/api/curator/content/versions", tags=["curator"])
    def curator_content_versions(key: str) -> list[dict[str, Any]]:
        return db(curator.content_versions, key)

    @app.get("/api/curator/content/version", tags=["curator"])
    def curator_content_version(key: str, version: Optional[int] = None) -> dict[str, Any]:
        return db(curator.content_version, key, version)

    @app.post("/api/curator/content", tags=["curator"], status_code=201)
    def curator_save_content(body: ContentIn) -> dict[str, Any]:
        version = db(curator.save_content, body.key, body.kind, body.body, body.curator_id, body.note)
        return {"key": body.key, "version": version,
                "bind_check": [b for b in db(curator.bind_check) if b["questionnaire_key"] == body.key
                               or b["scoring_key"] == body.key]}

    @app.get("/api/curator/binds", tags=["curator"])
    def curator_binds(all: bool = False) -> list[dict[str, Any]]:  # noqa: A002 - query parameter name
        return db(curator.bind_check, not all)

    # ---- the CIO's writes to an engine (C-32) --------------------------------------------
    # The proxy allows a write in cio mode only for an exact engine:path in cio.writable; fmre's
    # override path carries the instrument id, so no entry could name it. This route forwards the
    # one write, in both modes, as the curator routes do (C-16, C-20).

    @app.put("/api/cio/inflation-beta/{instrument_id}", tags=["cio"])
    async def cio_inflation_beta(instrument_id: str, body: InflationBetaIn) -> Response:
        """Set (``beta`` 0 to 1.5, optionally ``duration``) or revert (``beta`` null) the CIO's inflation
        pass-through override of one instrument in fmre, with the required ``reason``; ``set_by`` is the
        acting curator, checked in service first, so a revoked one never reaches fmre. fmre's answer
        (status and body) is passed through unchanged; fmre keeps every version."""
        await run_in_threadpool(db, curator.in_service, body.set_by)
        fmre = engine_or_404("fmre")
        payload = {"beta": body.beta, "reason": body.reason, "set_by": body.set_by}
        if body.duration is not None:
            payload["duration"] = body.duration
        try:
            r = await engines.forward(fmre, "PUT", f"v1/inflation-beta/{quote(instrument_id, safe='')}", "",
                                      json.dumps(payload).encode("utf-8"), "application/json")
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"{fmre.name} (fmre) is {_describe(exc)} at {fmre.url}, so no override was "
                                     "set. Start it from the System page.") from exc
        headers = {k: v for k, v in r.headers.items() if k.lower() not in DROP}
        return Response(r.content, status_code=r.status_code, headers=headers)

    # ---- proxy (last, so the cockpit's own routes win) -------------------------------

    @app.api_route("/api/{key}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"],
                   tags=["proxy"])
    async def proxy(key: str, path: str, request: Request) -> Response:
        engine = engine_or_404(key)
        if request.method != "GET" and not settings.writable(key, path):
            raise HTTPException(403, f"{request.method} /{path} on {key} is not allowed in "
                                     f"{settings.mode} mode")
        try:
            r = await engines.forward(engine, request.method, path, request.url.query,
                                      await request.body(), request.headers.get("content-type"))
        except httpx.HTTPError as exc:
            return JSONResponse({"detail": f"{engine.name} ({key}) is {_describe(exc)} at "
                                           f"{engine.url}. Start it from the System page or with its "
                                           f"start.cmd."}, status_code=502)
        headers = {k: v for k, v in r.headers.items() if k.lower() not in DROP}
        return Response(r.content, status_code=r.status_code, headers=headers)

    return app
