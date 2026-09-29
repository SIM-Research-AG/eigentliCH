"""Typed callers for the engines: liveness and metadata probes, and the raw proxy call.

The cockpit reads engines over their published HTTP endpoints and nothing else. A probe never
raises: an engine that is down, slow or answering garbage is a status, not an error.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx

from .settings import Engine, Settings

PROBE_TIMEOUT_S = 2.0


class Engines:
    """One shared async client for every engine the roster names."""

    def __init__(self, settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=settings.timeout_s, transport=transport,
                                      follow_redirects=False)

    async def close(self) -> None:
        await self.http.aclose()

    async def get_json(self, engine: Engine, path: str, timeout: Optional[float] = None) -> Any:
        r = await self.http.get(engine.url + path, timeout=timeout or self.settings.timeout_s)
        r.raise_for_status()
        return r.json()

    async def probe(self, engine: Engine) -> dict[str, Any]:
        """``/health`` and ``/meta`` of one engine, with the round trip, never raising.

        Planned and scaffold engines are probed too: someone may be running a draft on the port.
        """
        out: dict[str, Any] = {"up": False, "health": None, "meta": None, "error": None,
                               "latency_ms": None}
        started = time.perf_counter()
        try:
            out["health"] = await self.get_json(engine, engine.health_path, PROBE_TIMEOUT_S)
            out["up"] = True
            out["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        except httpx.HTTPError as exc:
            out["error"] = _describe(exc)
            return out
        except ValueError:
            out["error"] = "health did not answer JSON"
            return out
        if engine.meta_path:
            try:
                out["meta"] = await self.get_json(engine, engine.meta_path, PROBE_TIMEOUT_S * 2)
            except (httpx.HTTPError, ValueError) as exc:
                out["error"] = f"meta: {_describe(exc) if isinstance(exc, httpx.HTTPError) else exc}"
        return out

    async def probe_all(self) -> dict[str, dict[str, Any]]:
        results = await asyncio.gather(*(self.probe(e) for e in self.settings.engines))
        return {e.key: r for e, r in zip(self.settings.engines, results)}

    async def forward(self, engine: Engine, method: str, path: str, query: str, body: bytes,
                      content_type: Optional[str]) -> httpx.Response:
        url = engine.url + "/" + path.lstrip("/")
        if query:
            url += "?" + query
        headers = {"content-type": content_type} if content_type else {}
        return await self.http.request(method, url, content=body or None, headers=headers)


def _describe(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.ConnectError):
        return "not running (connection refused)"
    if isinstance(exc, httpx.TimeoutException):
        # On Windows a refused localhost connection is retried for about 2 s, so an empty
        # port usually shows up here rather than as a ConnectError.
        return "not answering (not running, or too slow)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"answered {exc.response.status_code}"
    return type(exc).__name__
