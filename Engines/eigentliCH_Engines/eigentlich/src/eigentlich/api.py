"""HTTP surface of the consumer app. Routing only: every route calls ``service``.

JSON under ``/api/...``; ``GET /health`` and ``GET /meta`` as the engines have them; the browser app
(``client/``) is served at ``/``. **There is no sign-in** (owner decision, 9.1): the client picked in the
browser travels in the path of every client route (``/api/clients/{client_id}/...``), and every row reached
through it is checked to be that client's. No route reads a token, a cookie or a password.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx
import psycopg
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .appsettings import AppSettings, load_app
from .clients import ChatbotClient, EngineRefused, EngineUnavailable, LbsClient, ReportClient
from .questionnaires import AnswerRefused
from .service import APP_VERSION, Conflict, Forbidden, Invalid, Service
from .settings import ROOT
from .store import NotFound, Store, StoreError

CLIENT_DIR = ROOT / "client"

#: The report HTML is the report engine's, shown in a sandboxed frame; it may carry inline styles and no
#: script, no remote fetch of any kind.
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-ancestors 'self'"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewClient(_Body):
    display_name: str = Field(min_length=1, max_length=200)
    age_at_registration: int = Field(ge=18, le=120)
    locale: str = "de-CH"


class ClientPatch(_Body):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    locale: Optional[str] = None


class AnswerBody(_Body):
    content_version: int = Field(ge=1)
    value: Any


class ContentEdit(_Body):
    base_version: int = Field(ge=1)
    question_key: str
    question: Optional[dict[str, str]] = None
    why: Optional[dict[str, str]] = None
    placeholder: Optional[dict[str, str]] = None
    options: Optional[list[dict[str, Any]]] = None
    note: Optional[str] = Field(default=None, max_length=500)


class HouseholdBody(_Body):
    adults: list[str] = Field(min_length=1)
    dependants: list[str] = []
    as_of: Optional[date] = None
    reasoning: Optional[str] = Field(default=None, max_length=2000)


class PositionBody(_Body):
    model_config = ConfigDict(extra="forbid")
    role: Optional[str] = None
    capital_type: Optional[str] = None
    label: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    magnitude: Optional[float] = None
    magnitude_unit: Optional[str] = None
    stock_kind: Optional[str] = None
    liquidity: Optional[str] = None
    time_basis: Optional[str] = Field(default=None, max_length=200)
    started_on: Optional[date] = None
    vessel: Optional[str] = None
    #: Whose position it is: ``client`` (the default, stored as none) or ``partner`` (EIG-53).
    owner: Optional[str] = None
    reasoning: Optional[str] = Field(default=None, max_length=2000)


class GoalBody(_Body):
    name: Optional[str] = Field(default=None, max_length=300)
    target_amount: Optional[float] = Field(default=None, ge=0)
    target_date: Optional[date] = None
    template: Optional[str] = None
    occupancy: Optional[str] = None
    horizon: Optional[str] = None
    flexibility: Optional[str] = None
    safety: Optional[str] = None
    liquidity_need: Optional[str] = None
    volatility_tolerance: Optional[str] = None
    #: The goal's share of the yearly saving, 0 to 1 (the page shows 0 to 100 %); the active goals' shares sum
    #: to at most 1 (EIG-59).
    contribution_share: Optional[float] = Field(default=None, ge=0, le=1)
    funded_by: Optional[list[str]] = None
    reasoning: Optional[str] = Field(default=None, max_length=2000)


class FactBody(_Body):
    value: Any
    reasoning: Optional[str] = Field(default=None, max_length=2000)


class SheetRun(_Body):
    """Who asks for the run: nobody named (the client, in the app) or a curator in service (the cockpit)."""
    curator_id: Optional[str] = Field(default=None, min_length=1, max_length=64)


class Reason(_Body):
    reasoning: Optional[str] = Field(default=None, max_length=2000)


class AskBody(_Body):
    question: str = Field(min_length=1, max_length=2000)
    language: str = "de"
    subject: Optional[str] = Field(default=None, max_length=200)


class MessageBody(_Body):
    body: str = Field(min_length=1, max_length=2000)
    language: str = "de"


class ApprovalBody(_Body):
    item: str                         # answer | report
    item_id: str
    note: Optional[str] = Field(default=None, max_length=1000)


class ProduceBody(_Body):
    """A revision's particulars (the cockpit's): the curator's remark, printed on the revised report, and which
    report of the request is revised (default: its latest)."""
    revision_note: Optional[str] = Field(default=None, max_length=4000)
    revision_of: Optional[str] = Field(default=None, max_length=64)


class ReportBody(_Body):
    kind: str = "report"              # report | update
    language: str = "de"
    note: Optional[str] = Field(default=None, max_length=1000)


def _fields(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True)


def create_app(settings: Optional[AppSettings] = None, *,
               lbs_transport: Optional[httpx.BaseTransport] = None,
               chatbot_transport: Optional[httpx.BaseTransport] = None,
               report_transport: Optional[httpx.BaseTransport] = None) -> FastAPI:
    settings = settings or load_app()
    t = settings.timeouts
    service = Service(settings, Store(settings.store.database),
                      LbsClient(settings.lbs_url, t.lbs_s, t.connect_s, lbs_transport),
                      ChatbotClient(settings.chatbot_url, t.chatbot_s, t.connect_s, chatbot_transport),
                      ReportClient(settings.report_url, t.report_s, t.connect_s, report_transport))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        service.close()

    app = FastAPI(title="eigentliCH: the client's app", version=APP_VERSION, lifespan=lifespan,
                  description="The consumer side of eigentliCH on the `eigentlich` store. No sign-in: a client "
                              "picker. Model-derived research output. Not investment advice.")
    app.state.service = service
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["*"], allow_credentials=False)

    def guard(fn, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except NotFound as exc:
            raise HTTPException(404, str(exc).strip("'\"")) from exc
        except (Invalid, AnswerRefused) as exc:
            raise HTTPException(422, str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(403, str(exc)) from exc
        except EngineUnavailable as exc:
            raise HTTPException(503, {"engine": exc.engine, "error": str(exc)}) from exc
        except EngineRefused as exc:
            raise HTTPException(502, {"engine": exc.engine, "error": str(exc)}) from exc
        except StoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        except (psycopg.errors.RaiseException, psycopg.errors.IntegrityError) as exc:
            raise HTTPException(422, str(exc).split("\n")[0]) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    # ---- standard ------------------------------------------------------------------------------

    @app.get("/health", tags=["standard"])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/meta", tags=["standard"])
    def meta() -> dict[str, Any]:
        return guard(service.meta)

    # ---- the client picker -----------------------------------------------------------------------

    @app.get("/api/clients", tags=["clients"])
    def clients(include_archived: bool = False) -> list[dict[str, Any]]:
        return guard(service.list_clients, include_archived)

    @app.post("/api/clients", tags=["clients"], status_code=201)
    def new_client(body: NewClient) -> dict[str, Any]:
        return guard(service.create_client, **body.model_dump())

    @app.get("/api/clients/{client_id}", tags=["clients"])
    def client(client_id: str) -> dict[str, Any]:
        return guard(service.get_client, client_id)

    @app.patch("/api/clients/{client_id}", tags=["clients"])
    def patch_client(client_id: str, body: ClientPatch) -> dict[str, Any]:
        return guard(service.update_client, client_id, **_fields(body))

    @app.get("/api/clients/{client_id}/home", tags=["clients"])
    def home(client_id: str, language: str = "de") -> dict[str, Any]:
        return guard(service.home, client_id, language)

    # ---- questionnaires ------------------------------------------------------------------------

    @app.get("/api/clients/{client_id}/questionnaires/{name}", tags=["questionnaires"])
    def questionnaire(client_id: str, name: str, language: str = "de") -> dict[str, Any]:
        return guard(service.questionnaire, client_id, name, language)

    @app.put("/api/clients/{client_id}/questionnaires/{name}/answers/{question_key}", tags=["questionnaires"])
    def put_answer(client_id: str, name: str, question_key: str, body: AnswerBody) -> dict[str, Any]:
        """Stored at once (R-101), naming the content version it answered."""
        return guard(service.put_answer, client_id, name, question_key, value=body.value,
                     content_version=body.content_version)

    @app.post("/api/clients/{client_id}/questionnaires/{name}/edit", tags=["questionnaires"], status_code=201)
    def edit_questionnaire(client_id: str, name: str, body: ContentEdit) -> dict[str, Any]:
        """A new version of the shared questionnaire content, saved by this client."""
        edit = {k: v for k, v in _fields(body).items() if k in ("question", "why", "placeholder", "options")}
        return guard(service.edit_content, client_id, name, base_version=body.base_version,
                     question_key=body.question_key, edit=edit, note=body.note)

    @app.get("/api/questionnaires/{name}/history", tags=["questionnaires"])
    def questionnaire_history(name: str) -> list[dict[str, Any]]:
        return guard(service.content_history, name)

    @app.post("/api/clients/{client_id}/onboarding/complete", tags=["questionnaires"])
    def complete_onboarding(client_id: str) -> dict[str, Any]:
        return guard(service.complete_onboarding, client_id)

    # ---- the plan (every change through a decision, C-09) --------------------------------------

    @app.get("/api/clients/{client_id}/plan", tags=["plan"])
    def plan(client_id: str, language: str = "de") -> dict[str, Any]:
        return guard(service.plan, client_id, language)

    @app.get("/api/clients/{client_id}/decisions", tags=["plan"])
    def decisions(client_id: str) -> list[dict[str, Any]]:
        return guard(service.decisions, client_id)

    @app.put("/api/clients/{client_id}/facts/{key}", tags=["plan"])
    def restate_fact(client_id: str, key: str, body: FactBody) -> dict[str, Any]:
        """State a fact anew (canton, civil status, health, ...) under a decision (C-09, EIG-54): a stated fact
        wins over an answer, so this is how a changed fact reaches lbs. Checked against the onboarding question
        that fills the key, when there is one."""
        return guard(service.restate_fact, client_id, key, value=body.value, reasoning=body.reasoning)

    @app.put("/api/clients/{client_id}/household", tags=["plan"])
    def household(client_id: str, body: HouseholdBody) -> dict[str, Any]:
        return guard(service.set_household, client_id, adults=body.adults, dependants=body.dependants,
                     as_of=body.as_of, reasoning=body.reasoning)

    @app.post("/api/clients/{client_id}/positions", tags=["plan"], status_code=201)
    def new_position(client_id: str, body: PositionBody) -> dict[str, Any]:
        return guard(service.create_position, client_id, _fields(body))

    @app.patch("/api/clients/{client_id}/positions/{position_id}", tags=["plan"])
    def patch_position(client_id: str, position_id: str, body: PositionBody) -> dict[str, Any]:
        return guard(service.update_position, client_id, position_id, _fields(body))

    @app.post("/api/clients/{client_id}/positions/{position_id}/deactivate", tags=["plan"])
    def deactivate_position(client_id: str, position_id: str, body: Reason = Body(default=Reason())) -> dict[str, Any]:
        return guard(service.set_position_active, client_id, position_id, False, body.reasoning)

    @app.post("/api/clients/{client_id}/positions/{position_id}/reactivate", tags=["plan"])
    def reactivate_position(client_id: str, position_id: str, body: Reason = Body(default=Reason())) -> dict[str, Any]:
        return guard(service.set_position_active, client_id, position_id, True, body.reasoning)

    @app.post("/api/clients/{client_id}/goals", tags=["plan"], status_code=201)
    def new_goal(client_id: str, body: GoalBody) -> dict[str, Any]:
        return guard(service.create_goal, client_id, _fields(body))

    @app.patch("/api/clients/{client_id}/goals/{goal_id}", tags=["plan"])
    def patch_goal(client_id: str, goal_id: str, body: GoalBody) -> dict[str, Any]:
        return guard(service.update_goal, client_id, goal_id, _fields(body))

    @app.post("/api/clients/{client_id}/goals/{goal_id}/deactivate", tags=["plan"])
    def deactivate_goal(client_id: str, goal_id: str, body: Reason = Body(default=Reason())) -> dict[str, Any]:
        return guard(service.set_goal_active, client_id, goal_id, False, body.reasoning)

    @app.post("/api/clients/{client_id}/goals/{goal_id}/reactivate", tags=["plan"])
    def reactivate_goal(client_id: str, goal_id: str, body: Reason = Body(default=Reason())) -> dict[str, Any]:
        return guard(service.set_goal_active, client_id, goal_id, True, body.reasoning)

    # ---- the balance sheet (lbs) -----------------------------------------------------------------

    @app.get("/api/clients/{client_id}/balance-sheet", tags=["balance sheet"])
    def balance_sheet(client_id: str, language: str = "de") -> dict[str, Any]:
        return guard(service.balance_sheet, client_id, language=language)

    @app.post("/api/clients/{client_id}/balance-sheet", tags=["balance sheet"])
    def run_balance_sheet(client_id: str, body: Optional[SheetRun] = Body(default=None),
                          language: str = "de") -> dict[str, Any]:
        """Run lbs now. With ``{"curator_id": ...}`` (the cockpit's button) the run is recorded as that
        curator's, who must exist and be in service (403 otherwise); without a body, as the client's."""
        guard(service.run_balance_sheet, client_id, curator_id=body.curator_id if body else None)
        return guard(service.balance_sheet, client_id, language=language)

    # ---- threads ---------------------------------------------------------------------------------

    @app.get("/api/clients/{client_id}/threads", tags=["threads"])
    def threads(client_id: str) -> list[dict[str, Any]]:
        return guard(service.threads, client_id)

    @app.post("/api/clients/{client_id}/threads", tags=["threads"], status_code=201)
    def ask(client_id: str, body: AskBody, wait: bool = Query(False)) -> dict[str, Any]:
        """The client asks; spark7 drafts an answer through the chatbot engine (in the background unless
        ``wait``)."""
        return guard(service.ask, client_id, question=body.question, language=body.language, subject=body.subject,
                     wait=wait)

    @app.get("/api/clients/{client_id}/threads/{thread_id}", tags=["threads"])
    def thread(client_id: str, thread_id: str) -> dict[str, Any]:
        return guard(service.thread, client_id, thread_id)

    @app.post("/api/clients/{client_id}/threads/{thread_id}/messages", tags=["threads"], status_code=201)
    def message(client_id: str, thread_id: str, body: MessageBody, wait: bool = Query(False)) -> dict[str, Any]:
        return guard(service.add_client_message, client_id, thread_id, body=body.body, language=body.language,
                     wait=wait)

    @app.post("/api/clients/{client_id}/threads/{thread_id}/draft", tags=["threads"])
    def draft(client_id: str, thread_id: str, wait: bool = Query(False)) -> dict[str, Any]:
        """Try the spark7 draft again (after the chatbot was not reachable)."""
        return guard(service.draft, client_id, thread_id, wait=wait)

    @app.post("/api/clients/{client_id}/threads/{thread_id}/close", tags=["threads"])
    def close(client_id: str, thread_id: str) -> dict[str, Any]:
        return guard(service.close_thread, client_id, thread_id)

    # ---- approval, only on the client's request --------------------------------------------------

    @app.get("/api/clients/{client_id}/approvals", tags=["approval"])
    def approvals(client_id: str) -> list[dict[str, Any]]:
        return guard(service.approvals, client_id)

    @app.post("/api/clients/{client_id}/approvals", tags=["approval"], status_code=201)
    def ask_approval(client_id: str, body: ApprovalBody) -> dict[str, Any]:
        """"Ask the curator to approve": the item then shows awaiting curator until the curator decides."""
        return guard(service.request_approval, client_id, item=body.item, item_id=body.item_id, note=body.note)

    @app.post("/api/clients/{client_id}/approvals/{approval_id}/withdraw", tags=["approval"])
    def withdraw_approval(client_id: str, approval_id: str) -> dict[str, Any]:
        return guard(service.withdraw_approval, client_id, approval_id)

    # ---- reports and updates ---------------------------------------------------------------------

    @app.get("/api/clients/{client_id}/reports", tags=["reports"])
    def reports(client_id: str) -> list[dict[str, Any]]:
        return guard(service.reports, client_id)

    @app.post("/api/clients/{client_id}/reports", tags=["reports"], status_code=201)
    def request_report(client_id: str, body: ReportBody, wait: bool = Query(False)) -> dict[str, Any]:
        """A report or update request; lbs runs, then the report engine (in the background unless ``wait``)."""
        return guard(service.request_report, client_id, kind=body.kind, language=body.language, note=body.note,
                     wait=wait)

    @app.post("/api/clients/{client_id}/reports/{request_id}/produce", tags=["reports"])
    def produce(client_id: str, request_id: str, wait: bool = Query(False), revision: bool = Query(False),
                body: Optional[ProduceBody] = Body(default=None)) -> dict[str, Any]:
        """Try again for an open request; ``revision=true`` makes a new report for a fulfilled one, sent to the
        report engine as a revision of its latest report (or of ``revision_of``, a report of this request) with
        the curator's ``revision_note`` (EIG-57)."""
        return guard(service.produce, client_id, request_id, wait=wait, revision=revision,
                     revision_note=body.revision_note if body else None,
                     revision_of=body.revision_of if body else None)

    @app.post("/api/clients/{client_id}/reports/{request_id}/withdraw", tags=["reports"])
    def withdraw_report(client_id: str, request_id: str) -> dict[str, Any]:
        return guard(service.withdraw_report_request, client_id, request_id)

    @app.get("/api/clients/{client_id}/report/{report_id}/html", tags=["reports"], response_class=HTMLResponse)
    def report_html(client_id: str, report_id: str) -> HTMLResponse:
        html = guard(service.report_html, client_id, report_id)
        return HTMLResponse(html, headers={"Content-Security-Policy": REPORT_CSP, "X-Content-Type-Options": "nosniff",
                                           "Cache-Control": "no-store"})

    # ---- the browser app -------------------------------------------------------------------------

    if Path(CLIENT_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=CLIENT_DIR, html=True), name="client")

    return app
