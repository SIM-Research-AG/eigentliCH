"""Typed callers for the three upstream engines: ``mrs``, ``cycle`` and ``macrofield``.

Each input is read by artefact id through the standard endpoint ``GET /artefacts/{id}`` and
validated against its contract mirror on arrival. An artefact that does not validate, or that
answers with a different id than the one asked for, fails the run; it is never repaired here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Generic, Optional, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .contracts import CONTRACT_VERSIONS, CycleState, MacroState, MarketRiskSignal


class UpstreamError(RuntimeError):
    """An upstream engine could not supply a valid input. The message says which and why."""


class NotFoundUpstream(UpstreamError):
    """The upstream engine answered, and has no such artefact."""


def checksum(model: BaseModel) -> str:
    """sha256 of the part of an input this engine read: its upstream fingerprint."""
    blob = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


M = TypeVar("M", bound=BaseModel)


class ArtefactClient(Generic[M]):
    """``GET /artefacts/{id}`` on one upstream engine, validated as ``model``."""

    def __init__(self, engine: str, contract: str, model: type[M], base_url: str,
                 timeout_s: float = 120.0, transport: Optional[httpx.BaseTransport] = None):
        self.engine = engine
        self.contract = contract
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def artefact(self, artefact_id: str) -> M:
        path = f"/artefacts/{artefact_id}"
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"{self.engine} is unreachable at {self.base_url}: {exc}. Is it running? "
                f"Start it with engines/{self.engine}/start.cmd."
            ) from exc
        if response.status_code == 404:
            raise NotFoundUpstream(f"{self.engine} has no artefact {artefact_id!r}")
        if response.status_code != 200:
            raise UpstreamError(f"{self.engine} answered {response.status_code} for {path}: "
                                f"{response.text[:300]}")
        try:
            value = self.model.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(f"{self.engine} returned an artefact that breaks {self.contract}: "
                                f"{str(exc)[:1500]}") from exc
        if getattr(value, "artefact_id", None) != artefact_id:
            raise UpstreamError(f"asked {self.engine} for {artefact_id!r} and got "
                                f"{getattr(value, 'artefact_id', None)!r}")
        return value


def mrs_client(base_url: str, timeout_s: float = 120.0,
               transport: Optional[httpx.BaseTransport] = None) -> ArtefactClient[MarketRiskSignal]:
    return ArtefactClient("mrs", CONTRACT_VERSIONS["MarketRiskSignal(mrs)"], MarketRiskSignal,
                          base_url, timeout_s, transport)


def cycle_client(base_url: str, timeout_s: float = 120.0,
                 transport: Optional[httpx.BaseTransport] = None) -> ArtefactClient[CycleState]:
    return ArtefactClient("cycle", CONTRACT_VERSIONS["CycleState(cycle)"], CycleState,
                          base_url, timeout_s, transport)


def macrofield_client(base_url: str, timeout_s: float = 120.0,
                      transport: Optional[httpx.BaseTransport] = None) -> ArtefactClient[MacroState]:
    return ArtefactClient("macrofield", CONTRACT_VERSIONS["MacroState(macrofield)"], MacroState,
                          base_url, timeout_s, transport)
