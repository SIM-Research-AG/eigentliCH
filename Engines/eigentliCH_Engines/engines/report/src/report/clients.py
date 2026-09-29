"""Typed callers for the engines a report draws on, through their published endpoints.

One generic client per engine; what it reads and how it is validated comes from that engine's
:class:`report.engine.Extractor` (the path, the mirror contract). Every response is validated against its
mirror on arrival. An artefact that does not validate, or that answers with another id than the one asked
for, fails the run; it is never repaired here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from .engine import EXTRACTORS, EngineError, Extractor, extractor_for


class UpstreamError(RuntimeError):
    """An upstream engine could not supply a valid artefact. The message says which and why."""


class NotFoundUpstream(UpstreamError):
    """The upstream engine answered, and has no such artefact."""


START_HINTS = {"pcp": "Projects/Engines/Optimizer/engines/pcp/start.cmd",
               "lbs": "Projects/Engines/eigentliCH_Engines/engines/lbs/start.cmd",
               "lbsim": "the cockpit (Projects/Engines/cockpit), which starts lbsim on 8014"}

#: The engines a report can draw on (REP-32 adds lbsim, whose three artefact kinds share one client).
ENGINES = tuple(EXTRACTORS) + ("lbsim",)


@dataclass(frozen=True)
class Fetched:
    engine: str
    artefact: Any
    sha256: str
    url: str
    extractor: Extractor

    @property
    def kind(self) -> str:
        """The source kind: the engine, or ``lbsim.findings``, ``lbsim.paths``, ``lbsim.plan``."""
        return self.extractor.source_kind


class EngineClient:
    def __init__(self, engine: str, base_url: str, timeout_s: float = 60.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.engine = engine
        self.extractor = EXTRACTORS.get(engine)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def fetch(self, artefact_id: str) -> Fetched:
        try:
            extractor = extractor_for(self.engine, artefact_id)
        except EngineError as exc:
            raise NotFoundUpstream(str(exc)) from exc
        path = extractor.path(artefact_id)
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{self.engine} is unreachable at {self.base_url}: {exc}. Is it running? Start it "
                                f"with {START_HINTS.get(self.engine, 'its start.cmd')}.") from exc
        if response.status_code == 404:
            raise NotFoundUpstream(f"{self.engine} has no artefact {artefact_id!r} ({path} answered 404)")
        if response.status_code != 200:
            raise UpstreamError(f"{self.engine} answered {response.status_code} for {path}: {response.text[:300]}")
        try:
            artefact = extractor.mirror.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(f"{self.engine} returned an artefact that breaks {extractor.contract_version}: "
                                f"{str(exc)[:1500]}") from exc
        if getattr(artefact, "artefact_id", None) != artefact_id:
            raise UpstreamError(f"asked {self.engine} for {artefact_id!r} and got {getattr(artefact, 'artefact_id', None)!r}")
        return Fetched(engine=self.engine, artefact=artefact, sha256=hashlib.sha256(response.content).hexdigest(),
                       url=f"{self.base_url}{path}", extractor=extractor)


def engine_clients(urls: dict[str, str], timeout_s: float,
                   transports: Optional[dict[str, httpx.BaseTransport]] = None) -> dict[str, EngineClient]:
    transports = transports or {}
    return {name: EngineClient(name, urls[name], timeout_s, transports.get(name)) for name in ENGINES if name in urls}
