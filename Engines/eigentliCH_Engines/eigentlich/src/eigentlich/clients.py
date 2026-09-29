"""Typed callers for the engines the app uses: ``lbs`` (8013), ``chatbot`` (8016), ``report`` (8015), and
``aggregation`` (8004), asked only which Regimes are scenarios (EIG-63).

HTTP only; each response is validated against its mirror in ``contracts.py`` on arrival. An engine that is
not there, answers with an error, or answers with something that breaks its contract raises
``EngineUnavailable`` or ``EngineRefused`` with a sentence a client can read. Nothing here repairs a
response or invents one: the caller keeps the request open and says so.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from pydantic import BaseModel, ValidationError

from . import contracts as c


class EngineError(RuntimeError):
    """Base: the engine could not supply the result. ``engine`` names it."""

    def __init__(self, engine: str, message: str):
        super().__init__(message)
        self.engine = engine


class EngineUnavailable(EngineError):
    """Not reachable, timed out, or answered 5xx: try again later."""


class EngineRefused(EngineError):
    """Answered, and refused this request (4xx) or broke its contract: retrying the same will not help."""


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:400]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("error") or detail
    return str(detail)[:600]


class _Client:
    engine: str = ""
    start_hint: str = ""

    def __init__(self, base_url: str, timeout_s: float, connect_s: float = 5.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, transport=transport,
                                    timeout=httpx.Timeout(timeout_s, connect=connect_s))

    def close(self) -> None:
        self._client.close()

    def _call(self, method: str, path: str, *, json: Any = None, timeout: Optional[float] = None) -> httpx.Response:
        try:
            kwargs: dict[str, Any] = {"json": json}
            if timeout is not None:
                kwargs["timeout"] = timeout
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise EngineUnavailable(self.engine, f"{self.engine} did not answer in time ({self.base_url}{path}).") from exc
        except httpx.HTTPError as exc:
            raise EngineUnavailable(self.engine, f"{self.engine} is not reachable at {self.base_url}. "
                                                 f"Start it with {self.start_hint}.") from exc
        if response.status_code >= 500:
            raise EngineUnavailable(self.engine, f"{self.engine} answered {response.status_code}: {_detail(response)}")
        if response.status_code >= 400:
            raise EngineRefused(self.engine, f"{self.engine} refused the request ({response.status_code}): "
                                             f"{_detail(response)}")
        return response

    def _parse(self, model: type[BaseModel], response: httpx.Response) -> Any:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise EngineRefused(self.engine, f"{self.engine} answered with something that is not "
                                             f"{model.__name__}: {str(exc)[:600]}") from exc

    def health(self, timeout_s: float) -> dict[str, Any]:
        try:
            response = self._client.get("/health", timeout=timeout_s)
            ok = response.status_code == 200
            body = response.json() if ok else {}
            return {"url": self.base_url, "reachable": ok, "engine_version": body.get("engine_version")}
        except (httpx.HTTPError, ValueError):
            return {"url": self.base_url, "reachable": False, "engine_version": None}


def lbs_body(request: c.LbsRequest) -> dict[str, Any]:
    """The request as sent: the nominal and real view's two answers (lbs LBS-31) only where the client stated
    them, so every other request keeps its bytes (and lbs's cache) and an lbs before LBS-31 still takes it."""
    body = c.dump(request)
    for goal in body.get("goals") or []:
        if goal.get("amount_basis") is None:
            goal.pop("amount_basis", None)
    mandate = body.get("mandate")
    if isinstance(mandate, dict) and mandate.get("contribution_indexed") is None:
        mandate.pop("contribution_indexed", None)
    return body


class LbsClient(_Client):
    engine = "lbs"
    start_hint = r"engines\lbs\start.cmd"

    def run(self, request: c.LbsRequest) -> c.RunAccepted:
        return self._parse(c.RunAccepted, self._call("POST", "/run", json=lbs_body(request)))

    def sheet(self, artefact_id: str) -> c.LifeBalanceSheet:
        sheet = self._parse(c.LifeBalanceSheet, self._call("GET", f"/artefacts/{artefact_id}"))
        if sheet.artefact_id != artefact_id:
            raise EngineRefused(self.engine, f"asked lbs for {artefact_id} and got {sheet.artefact_id}")
        return sheet

    def sheet_raw(self, artefact_id: str) -> dict[str, Any]:
        """The whole sheet as lbs published it, for display (validated first)."""
        response = self._call("GET", f"/artefacts/{artefact_id}")
        self._parse(c.LifeBalanceSheet, response)
        return response.json()


class ChatbotClient(_Client):
    engine = "chatbot"
    start_hint = r"engines\chatbot (python -m chatbot serve)"

    def answer(self, request: c.ChatRequest) -> c.ChatAnswer:
        return self._parse(c.ChatAnswer, self._call("POST", "/answer", json=c.dump(request)))


class ReportClient(_Client):
    engine = "report"
    start_hint = r"engines\report (python -m report serve)"

    def report(self, request: c.ReportRequest) -> c.Report:
        body = c.dump(request)
        # The revision fields (report 1.2.0) are sent only on a revision, so a report engine before 1.2.0,
        # which forbids unknown fields, still takes every other request (EIG-57).
        for key in ("revision_of", "revision_note"):
            if body.get(key) is None:
                body.pop(key, None)
        # The basis (report 1.3.0, REP-27) only when real, so an engine before 1.3.0 still takes a nominal one.
        if body.get("basis") == "nominal":
            body.pop("basis")
        report = self._parse(c.Report, self._call("POST", "/report", json=body))
        if report.client_ref != request.client_ref:
            raise EngineRefused(self.engine, "the report engine answered for another client")
        return report


class AggregationClient(_Client):
    engine = "aggregation"
    start_hint = r"Macro\engines\aggregation\start.cmd"

    def scenarios(self) -> list[c.ScenarioListed]:
        """Every scenario Regime aggregation has derived (``GET /scenarios``), with its policy and base."""
        response = self._call("GET", "/scenarios")
        try:
            rows = response.json()
        except ValueError as exc:
            raise EngineRefused(self.engine, "aggregation /scenarios did not answer JSON") from exc
        if not isinstance(rows, list):
            raise EngineRefused(self.engine, "aggregation /scenarios did not answer a list")
        try:
            return [c.ScenarioListed.model_validate(r) for r in rows]
        except ValidationError as exc:
            raise EngineRefused(self.engine, f"aggregation /scenarios broke its contract: {str(exc)[:400]}") from exc
