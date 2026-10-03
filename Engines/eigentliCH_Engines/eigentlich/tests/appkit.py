"""Stand-in engines and app helpers for the app tests.

The stand-ins answer in the shapes of the real contracts (``lbs-balance-sheet@1.0.0``, ``chat-answer@1.0.0``,
``report@1.0.0``, lbsim's ``RunAccepted``, ``RunStatus`` and outlook on its frozen samples in ``fixtures/lbsim``),
record every request they receive, and can be switched off (``down = True``: the
connection is refused, as for an engine that is not running) or made to refuse (``refuse = True``: 422).
Each serves through ``httpx.MockTransport`` (as pcp's tests do) or on a real socket (``serve``).
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import copy
from pathlib import Path

import anyio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from eigentlich.appsettings import AppSettings, load_app
from eigentlich.settings import Settings

ROLES = ("gain", "income", "stabilisation", "protection")


def _id(prefix: str, payload: Any) -> str:
    return f"{prefix}-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class StandIn:
    engine = ""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.down = False
        self.refuse = False
        self.delay_s = 0.0
        self.lock = threading.Lock()

    def handle(self, method: str, path: str, body: Any) -> tuple[int, Any]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _dispatch(self, method: str, path: str, body: Any, query: Optional[dict[str, str]] = None) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"status": "ok", "engine": self.engine, "engine_version": f"{self.engine}@stand-in"}
        with self.lock:
            self.requests.append({"method": method, "path": path, "body": body, "query": dict(query or {})})
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.refuse:
            return 422, {"detail": f"{self.engine} stand-in refuses"}
        if getattr(self, "wants_query", False):
            return self.handle(method, path, body, dict(query or {}))
        return self.handle(method, path, body)

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if self.down:
                raise httpx.ConnectError("connection refused (stand-in down)", request=request)
            body = json.loads(request.content) if request.content else None
            status, payload = self._dispatch(request.method, request.url.path, body, dict(request.url.params))
            return httpx.Response(status, json=payload)
        return httpx.MockTransport(handler)

    def asgi(self):
        """The stand-in as a FastAPI app, for a real socket."""
        app = FastAPI()

        @app.api_route("/{path:path}", methods=["GET", "POST"])
        async def any_route(path: str, request: Request):
            raw = await request.body()
            body = json.loads(raw) if raw else None
            status, payload = await anyio.to_thread.run_sync(self._dispatch, request.method, "/" + path, body,
                                                             dict(request.query_params))
            return JSONResponse(payload, status_code=status)
        return app


class Lbs(StandIn):
    engine = "lbs"

    def __init__(self) -> None:
        super().__init__()
        self.sheets: dict[str, dict[str, Any]] = {}
        self.real_view = True           # the sheet carries lbs's real view (calibration 1.4.0, LBS-31)
        self.health_withheld = False    # H absent as lbs states it when K3 data was filtered or erased

    def handle(self, method, path, body):
        if method == "POST" and path == "/run":
            assert body["contract_version"] == "lbs-request@1.0.0"
            aid = _id("LBS", body)
            grid = []
            for role in ROLES:
                for cap in ("human", "financial"):
                    mine = [p for p in body["positions"] if p["role"] in (role, "growth" if role == "gain" else role)
                            and p["capital_type"] == cap and p["active"]]
                    assets = sum(p["magnitude"] for p in mine if p["unit"] == "chf" and p["stock_kind"] == "asset") or None
                    flows = sum(p["magnitude"] for p in mine if p["unit"] == "chf_per_year") or None
                    grid.append({"role": role, "capital_type": cap, "display": f"{role}/{cap}", "definition": None,
                                 "positions": [p["position_id"] for p in mine], "assets_chf": assets,
                                 "liabilities_chf": None, "flows_chf_per_year": flows, "shares_of_total": None})
            fin = sum(c["assets_chf"] or 0 for c in grid if c["capital_type"] == "financial")
            income = sum(p["magnitude"] for p in body["positions"] if p["role"] == "income" and p["active"]
                         and p["unit"] == "chf_per_year") or None
            persons = (body["household"] or {}).get("persons") or []
            gaps = [{"section": "totals", "input": "liabilities", "kind": "not_in_the_request",
                     "reason": "no liability is stated"}]
            for g in body["goals"]:
                if g["kind"] == "property" and g["occupancy"] is None:
                    gaps.append({"section": f"property.{g['goal_id']}",
                                 "input": "the_goal_does_not_say_whether_the_member_will_live_in_it",
                                 "kind": "not_in_the_request", "reason": "the property finding could not be determined"})
            if body["mandate"] is None:
                gaps.append({"section": "mandate_proposal", "input": "mandate.goal_id", "kind": "not_in_the_request",
                             "reason": "no goal is designated for the mandate"})
            elif body["mandate"]["annual_contribution"] is None:
                gaps.append({"section": "mandate_proposal", "input": "annual_contribution",
                             "kind": "not_in_the_request", "reason": "the yearly contribution is not stated"})
            gaps.append({"section": "retirement.x", "input": "the_ahv_table_is_not_approved",
                         "kind": "record_not_approved", "reason": "the retirement finding: the ahv table is not approved"})
            self.sheets[aid] = {
                "contract_version": "lbs-balance-sheet@1.0.0", "artefact_id": aid, "client_ref": body["client_ref"],
                "as_of": body["as_of"], "calibration_version": "1.0.0", "grid": grid,
                "household": {"stated": body["household"] is not None,
                              "adults": [p for p in persons if p["kind"] == "adult"],
                              "dependants": [p for p in persons if p["kind"] == "dependant"]},
                "human_capital": [{"person_id": "p1", "E": {"key": "E", "value": 0.62}, "N": {"key": "N", "value": None},
                                   "H": {"key": "H", "value": None, "absent_because": "K3 data was filtered or erased"}
                                   if self.health_withheld else {"key": "H", "value": 0.85}}] if persons else [],
                "totals": {"financial_assets": fin, "human_assets": None, "total_assets": None, "liabilities": None,
                           "net_worth": None, "drawable": None, "household_income": income,
                           # lbs's sums by vessel over the active financial assets in chf, None where none
                           "by_vessel": {v or "not_stated": sum(p["magnitude"] for p in body["positions"]
                                                                if p["active"] and p["capital_type"] == "financial"
                                                                and p["unit"] == "chf" and p["stock_kind"] == "asset"
                                                                and p.get("vessel") == v) or None
                                         for v in ("free", "pillar_2", "pillar_3a", "real_asset", None)}},
                "gaps": gaps,
                "notice": "Model-derived research output. Not investment advice.",
            }
            if self.real_view:
                # lbs's real view (LBS-31) in its shape: a price level of 1.5 to every target date
                views = []
                for g in body["goals"]:
                    amount, basis = g["target_amount"], g.get("amount_basis") or "today"
                    nominal = None if amount is None else (amount * 1.5 if basis == "today" else amount)
                    real = None if amount is None else (amount if basis == "today" else amount / 1.5)
                    views.append({"goal_id": g["goal_id"], "kind": g["kind"],
                                  "unit": "chf_per_year" if g["kind"] == "retirement" else "chf",
                                  "amount_basis": basis, "amount_basis_stated": "amount_basis" in g,
                                  "stated_amount": amount, "horizon_years": 20.0, "price_level": 1.5,
                                  "nominal": {"basis": "nominal", "amount": nominal, "as_at": g["target_date"]},
                                  "real": {"basis": "real", "amount": real, "as_at": None}})
                m = body["mandate"] or {}
                self.sheets[aid]["real_view"] = {
                    "currency": "CHF", "contribution_indexed": bool(m.get("contribution_indexed")),
                    "contribution_indexed_stated": "contribution_indexed" in m, "goals": views,
                    "inflation": {"currency": "CHF", "index": "CPI", "annual_rate": 0.01, "log_rate": 0.00995,
                                  "label": "measured", "source": "stand-in"}}
                if m:
                    self.sheets[aid]["mandate_proposal"] = {
                        "status": "available", "goal_id": m["goal_id"], "target_chf": 150000.0, "required_return": 0.05,
                        "basis": "nominal",
                        "views": {"nominal": {"basis": "nominal", "target_chf": 150000.0, "required_return": 0.05},
                                  "real": {"basis": "real", "target_chf": 100000.0, "required_return": 0.0396}}}
            return 200, {"run_id": _id("RUN", [aid, len(self.requests)]), "status": "succeeded", "artefact_id": aid,
                         "idempotency_key": aid, "cached": False}
        if method == "GET" and path.startswith("/artefacts/"):
            aid = path.rsplit("/", 1)[1]
            return (200, self.sheets[aid]) if aid in self.sheets else (404, {"detail": "no such sheet"})
        return 404, {"detail": "no route"}


class Chatbot(StandIn):
    engine = "chatbot"

    def __init__(self) -> None:
        super().__init__()
        self.unverified: list[str] = []
        self.refusal = False
        self.general = False            # answer from general knowledge (basis general), as the chatbot now may

    def handle(self, method, path, body):
        if method == "POST" and path == "/answer":
            assert body["contract_version"] == "chat-request@1.0.0"
            aid = _id("CHAT", [body, len(self.requests)])
            grounding = body["grounding"]
            if self.general and not self.refusal:
                return 200, {"contract_version": "chat-answer@1.0.0", "artefact_id": aid, "question": body["question"],
                             "language": body["language"], "answer": "Allgemeine Einschätzung von MiniMind: ...",
                             "cited_ids": [], "numbers": [], "unverified_numbers": [], "refused": False,
                             "route": "client_situation", "basis": "general", "warnings": [], "model": "stand-in-model",
                             "model_display_name": "MiniMind", "prompt_version": "stand-in", "latency_ms": 1.0,
                             "provenance": {}, "notice": "Model-derived research output. Not investment advice."}
            if self.refusal or not grounding:
                return 200, {"contract_version": "chat-answer@1.0.0", "artefact_id": aid, "question": body["question"],
                             "language": body["language"], "answer": "Dazu habe ich keine geprüfte Quelle.",
                             "cited_ids": [], "numbers": [], "unverified_numbers": [], "refused": True,
                             "refusal_code": "no_grounding", "refusal_reason": "no grounding", "route": "population_fact",
                             "warnings": [], "model": None, "prompt_version": "stand-in", "latency_ms": 0.0,
                             "provenance": {}, "notice": "Model-derived research output. Not investment advice."}
            cited = [grounding[0]["id"]]
            text = f"Entwurf zu «{body['question'][:40]}» aus {grounding[0]['title']}."
            if self.unverified:
                text += " Zahlen: " + ", ".join(self.unverified)
            return 200, {"contract_version": "chat-answer@1.0.0", "artefact_id": aid, "question": body["question"],
                         "language": body["language"], "answer": text, "cited_ids": cited,
                         "numbers": [{"text": n, "matched": []} for n in self.unverified],
                         "unverified_numbers": list(self.unverified), "refused": False, "route": "population_fact",
                         "basis": "grounded", "model_display_name": "MiniMind",
                         "warnings": [], "model": "stand-in-model", "prompt_version": "stand-in", "latency_ms": 1.0,
                         "provenance": {}, "notice": "Model-derived research output. Not investment advice."}
        return 404, {"detail": "no route"}


class Report(StandIn):
    engine = "report"

    def handle(self, method, path, body):
        if method == "POST" and path == "/report":
            assert body["contract_version"] == "report-request@1.0.0"
            aid = _id("REP", body)             # as the engine: the same request is the same (cached) artefact
            src = ", ".join(f"{s['engine']}:{s['artefact_id']}" for s in body["sources"])
            html = (f"<!doctype html><html><head><style>h1{{color:#1A1740}}</style></head><body>"
                    f"<h1>{'Aktualisierung' if body['kind'] == 'update' else 'Bericht'}</h1><p>{src}</p>"
                    f"<p>Model-derived research output. Not investment advice.</p></body></html>")
            return 200, {"contract_version": "report@1.0.0", "artefact_id": aid, "client_ref": body["client_ref"],
                         "kind": body["kind"], "language": body["language"], "title": "Bericht",
                         "previous_report_id": body.get("previous_report_id"), "as_of": "2026-09-28", "facts": [],
                         "revision_of": body.get("revision_of"), "revision_note": body.get("revision_note"),
                         "sections": [], "complete": True, "warnings": [], "html": html, "provenance": {},
                         "notice": "Model-derived research output. Not investment advice."}
        return 404, {"detail": "no route"}


class Aggregation(StandIn):
    """``GET /scenarios``: the scenario Regimes, as ``aggregation`` lists them (EIG-63)."""
    engine = "aggregation"

    def __init__(self) -> None:
        super().__init__()
        self.scenarios: list[dict[str, Any]] = []

    def handle(self, method, path, body):
        if method == "GET" and path == "/scenarios":
            return 200, list(self.scenarios)
        return 404, {"detail": "no route"}


SAMPLES = Path(__file__).resolve().parent / "fixtures" / "lbsim"


def _sample(name: str) -> dict[str, Any]:
    return json.loads((SAMPLES / f"{name}.sample.json").read_text(encoding="utf-8"))


class Lbsim(StandIn):
    """lbsim on B1's frozen samples (``fixtures/lbsim``, copied from ``engines/lbsim/golden/samples``): ``POST /run``
    makes findings (and paths with an Allocation) for the sheet asked, with the sample's two goals renamed to the
    first two goals of the lbs request that made the sheet; a plan run is queued unless ``optimise: "no"``;
    ``finish(run_id)`` ends it (``succeeded`` writes the sample plan). ``GET /outlook`` answers as lbsim does."""
    engine = "lbsim"
    wants_query = True

    def __init__(self, lbs: "Lbs") -> None:
        super().__init__()
        self.lbs = lbs
        self.outlooks: dict[tuple[str, str], dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.capitals = False           # each Regime carries ``capitals`` (VISUALS_INTERFACES.md), from the fixture

    def _goals(self, sheet_id: str) -> dict[str, str]:
        request = next((r["body"] for r in self.lbs.requests if r["path"] == "/run"
                        and _id("LBS", r["body"]) == sheet_id), None)
        ids = [g["goal_id"] for g in (request or {}).get("goals") or []]
        return {sample: mine for sample, mine in zip(("g-home", "g-ret"), ids)}

    @staticmethod
    def _rename(payload: Any, names: dict[str, str]) -> Any:
        text = json.dumps(payload)
        for old, new in names.items():
            text = text.replace(f'"{old}"', f'"{new}"')
        return json.loads(text)

    def _plan_run(self, paths: dict[str, Any], requested_by: dict[str, Any]) -> str:
        for rid, run in self.runs.items():
            if run["kind"] == "plan" and run["paths"] == paths["artefact_id"] and run["status"] in ("queued", "running", "succeeded"):
                return rid
        rid = _id("RUN", ["plan", paths["artefact_id"], len(self.runs)])
        self.runs[rid] = {"kind": "plan", "status": "queued", "paths": paths["artefact_id"], "requested_by": requested_by,
                          "artefact_ids": [], "failure_kind": None, "error": None,
                          "client_ref": paths["client_ref"], "sheet": paths["life_balance_sheet_id"]}
        return rid

    def finish(self, run_id: str, status: str = "succeeded", failure_kind: Optional[str] = None) -> None:
        run = self.runs[run_id]
        run["status"] = status
        if status == "succeeded":
            out = self.outlooks[(run["client_ref"], run["sheet"])]
            plan = copy.deepcopy(_sample("plan"))
            plan.update(client_ref=run["client_ref"], life_balance_sheet_id=run["sheet"],
                        paths_artefact_id=run["paths"], artefact_id=_id("LSO", run["paths"]))
            plan = self._rename(plan, out["names"])
            self.plans[plan["artefact_id"]] = plan
            run["artefact_ids"] = [plan["artefact_id"]]
        elif status == "failed":
            run["failure_kind"], run["error"] = failure_kind or "solver", "the solver did not converge"

    def _status(self, rid: str) -> dict[str, Any]:
        run = self.runs[rid]
        return {"run_id": rid, "kind": run["kind"], "status": run["status"], "failure_kind": run["failure_kind"],
                "idempotency_key": _id("IDK", rid), "requested_by": run["requested_by"],
                "queued_at": "2026-09-29T10:00:00Z", "started_at": "2026-09-29T10:00:05Z"
                if run["status"] != "queued" else None, "finished_at": None, "budget_s": 7200.0,
                "request": {}, "artefact_ids": run["artefact_ids"], "error": run["error"]}

    def handle(self, method, path, body, query):
        if method == "POST" and path == "/run":
            assert body["contract_version"] == "lbsim-request@1.0.0"
            sheet, client = body["life_balance_sheet_id"], body["client_ref"]
            names = self._goals(sheet)
            findings = copy.deepcopy(_sample("findings"))
            findings.update(artefact_id=_id("LSF", sheet), client_ref=client, life_balance_sheet_id=sheet)
            findings = self._rename(findings, names)
            paths = None
            not_made = []
            if body.get("allocation_id"):
                paths = copy.deepcopy(_sample("paths"))
                paths.update(artefact_id=_id("LSP", [sheet, body["allocation_id"]]), client_ref=client,
                             life_balance_sheet_id=sheet, findings_artefact_id=findings["artefact_id"],
                             allocation_id=body["allocation_id"])
                paths["allocation_view"]["allocation_id"] = body["allocation_id"]
                paths = self._rename(paths, names)
                if self.capitals:
                    for regime in paths["regimes"]:
                        regime["capitals"] = _sample("capitals")
            else:
                not_made.append({"artefact": "paths", "reason": "no_allocation",
                                 "text": {"de": "Noch keine Allokation.", "en": "No allocation yet."}})
            rid = _id("RUN", ["outlook", sheet, len(self.requests)])
            self.runs[rid] = {"kind": "outlook", "status": "succeeded", "paths": None, "requested_by": {"kind": "system", "ref": "run"},
                              "artefact_ids": [findings["artefact_id"]] + ([paths["artefact_id"]] if paths else []),
                              "failure_kind": None, "error": None, "client_ref": client, "sheet": sheet}
            plan_rid = None
            if paths and body.get("optimise", "background") == "background":
                plan_rid = self._plan_run(paths, {"kind": "system", "ref": "run"})
            self.outlooks[(client, sheet)] = {"findings": findings, "paths": paths, "names": names, "at": time.time()}
            return 200, {"run_id": rid, "kind": "outlook", "status": "succeeded", "idempotency_key": _id("IDK", sheet),
                         "cached": False, "findings_artefact_id": findings["artefact_id"],
                         "paths_artefact_id": paths["artefact_id"] if paths else None, "plan_run_id": plan_rid,
                         "not_made": not_made}
        if method == "POST" and path == "/optimise":
            assert body["contract_version"] == "lbsim-optimise@1.0.0"
            out = next((o for o in self.outlooks.values() if o["paths"] and o["paths"]["artefact_id"] == body["paths_artefact_id"]), None)
            if out is None:
                return 404, {"detail": "lbsim has no such paths."}
            rid = self._plan_run(out["paths"], body["requested_by"])
            run = self.runs[rid]
            return 200, {"run_id": rid, "kind": "plan", "status": run["status"], "idempotency_key": _id("IDK", rid),
                         "cached": run["status"] == "succeeded", "findings_artefact_id": out["findings"]["artefact_id"],
                         "paths_artefact_id": out["paths"]["artefact_id"], "plan_run_id": rid, "not_made": []}
        if method == "GET" and path.startswith("/runs/"):
            rid = path.rsplit("/", 1)[1]
            return (200, self._status(rid)) if rid in self.runs else (404, {"detail": "lbsim has no such run."})
        if method == "GET" and path == "/outlook":
            client, sheet = query.get("client_ref"), query.get("life_balance_sheet_id")
            out = self.outlooks.get((client, sheet))
            if out is None:
                return 404, {"detail": "lbsim has no outlook for this Life Balance Sheet yet."}
            plan: dict[str, Any]
            if out["paths"] is None:
                plan = {"state": "waiting_for_allocation", "reason": {"de": "Die Planrechnung wartet auf eine Allokation.",
                                                                      "en": "The plan calculation waits for an allocation."}}
            else:
                runs = [(rid, r) for rid, r in self.runs.items() if r["kind"] == "plan" and r["paths"] == out["paths"]["artefact_id"]]
                done = next(((rid, r) for rid, r in runs if r["status"] == "succeeded"), None)
                active = next(((rid, r) for rid, r in runs if r["status"] in ("queued", "running")), None)
                if done:
                    plan = {"state": "ready", "run": self._status(done[0]), "artefact": self.plans[done[1]["artefact_ids"][0]]}
                elif active:
                    plan = {"state": "calculating", "run": self._status(active[0]), "elapsed_s": 600.0, "budget_s": 7200.0}
                elif runs:
                    plan = {"state": "not_possible", "run": self._status(runs[-1][0]),
                            "reason": {"de": "Die Planrechnung kam zu keinem Ergebnis.", "en": "The plan calculation found no result."}}
                else:
                    plan = {"state": "not_requested", "reason": {"de": "Keine Planrechnung verlangt.", "en": "No plan calculation asked for."}}
            return 200, {"client_ref": client, "life_balance_sheet_id": sheet, "findings": out["findings"],
                         "paths": out["paths"], "plan": plan}
        return 404, {"detail": "no route"}


class Engines:
    def __init__(self) -> None:
        self.lbs, self.chatbot, self.report = Lbs(), Chatbot(), Report()
        self.aggregation = Aggregation()
        self.lbsim = Lbsim(self.lbs)

    def reset(self) -> None:
        for e in (self.lbs, self.chatbot, self.report, self.aggregation, self.lbsim):
            e.down = e.refuse = False
            e.delay_s = 0.0
        self.chatbot.unverified = []
        self.chatbot.refusal = False
        self.chatbot.general = False
        self.lbs.real_view = True
        self.lbs.health_withheld = False
        self.lbsim.capitals = False
        self.aggregation.scenarios = []


def app_settings(store: Settings, lbs_auto: Optional[dict[str, Any]] = None,
                 lbsim_auto: Optional[dict[str, Any]] = None, **urls: str) -> AppSettings:
    """The automatic lbs runs (EIG-47) and lbsim runs (EIG-67) are off unless a test asks for them: a run firing
    in the background of another test would change what that test counts."""
    return load_app(store=store, overrides={**urls, "lbs_auto": lbs_auto or {"enabled": False},
                                            "lbsim_auto": lbsim_auto or {"enabled": False}})


def make_app(store: Settings, engines: Engines, lbs_auto: Optional[dict[str, Any]] = None,
             lbsim_auto: Optional[dict[str, Any]] = None):
    from eigentlich.api import create_app
    return create_app(app_settings(store, lbs_auto, lbsim_auto), lbs_transport=engines.lbs.transport(),
                      chatbot_transport=engines.chatbot.transport(), report_transport=engines.report.transport(),
                      aggregation_transport=engines.aggregation.transport(), lbsim_transport=engines.lbsim.transport())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert not 8000 <= port <= 8016
    return port


@contextmanager
def serve(app, port: Optional[int] = None) -> Iterator[str]:
    """Serve an ASGI app with uvicorn on a real socket in a thread; yields its base URL."""
    import uvicorn

    port = port or free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("the server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def wait_for(fn: Callable[[], Any], timeout: float = 20.0, step: float = 0.05) -> Any:
    deadline = time.time() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.time() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(step)
