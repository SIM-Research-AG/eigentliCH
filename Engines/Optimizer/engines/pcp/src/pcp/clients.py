"""Typed callers for the two upstream engines: ``aggregation`` (the Regime) and ``fmre`` (the ReturnSet and
the instrument register).

Every response is validated against its contract mirror on arrival. An input that does not validate, or
that answers with a different id than the one asked for, fails the run; it is never repaired here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from .contracts import InstrumentOut, Regime, ReturnSet


class UpstreamError(RuntimeError):
    """An upstream engine could not supply a valid input. The message says which and why."""


class NotFoundUpstream(UpstreamError):
    """The upstream engine answered, and has no such artefact."""


def checksum(model: BaseModel) -> str:
    """sha256 of the part of an input this engine read: its upstream fingerprint."""
    blob = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class _Client:
    engine: str
    start_hint: str

    def __init__(self, base_url: str, timeout_s: float = 120.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: Optional[dict] = None) -> bytes:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{self.engine} is unreachable at {self.base_url}: {exc}. Is it running? "
                                f"Start it with {self.start_hint}.") from exc
        if response.status_code == 404:
            raise NotFoundUpstream(f"{self.engine} answered 404 for {path}: {response.text[:300]}")
        if response.status_code != 200:
            raise UpstreamError(f"{self.engine} answered {response.status_code} for {path}: "
                                f"{response.text[:300]}")
        return response.content


class AggregationClient(_Client):
    engine = "aggregation"
    start_hint = "Macro/engines/aggregation/start.cmd"

    def regime(self, regime_id: str) -> Regime:
        body = self._get(f"/regime/{regime_id}")
        try:
            value = Regime.model_validate_json(body)
        except ValidationError as exc:
            raise UpstreamError(f"aggregation returned a Regime that breaks aggregation-regime@1.0.0: "
                                f"{str(exc)[:1500]}") from exc
        if value.regime_id != regime_id:
            raise UpstreamError(f"asked aggregation for regime {regime_id!r} and got {value.regime_id!r}")
        return value


class FmreClient(_Client):
    engine = "fmre"
    start_hint = "Instruments/start.cmd"

    def return_set(self, regime_id: str, currency: str) -> ReturnSet:
        """The current ReturnSet with its instrument profiles, stamped against ``regime_id`` and measured in
        ``currency`` (CHF, EUR or USD; D-01, PCP-18). ``fmre`` serves the current set only, confirms the Regime
        with aggregation before stamping it, and converts the instrument series at the point of use; both the
        Regime and the currency enter its ``return_set_id``."""
        body = self._get("/v1/return-set", {"include_instruments": "true", "include_blocks": "false",
                                            "regime_id": regime_id, "currency": currency})
        try:
            return ReturnSet.model_validate_json(body)
        except ValidationError as exc:
            raise UpstreamError(f"fmre returned a ReturnSet that breaks rs@1.0.0: {str(exc)[:1500]}") from exc

    def instruments(self) -> list[InstrumentOut]:
        body = self._get("/v1/instruments", {"active_only": "true"})
        try:
            return TypeAdapter(list[InstrumentOut]).validate_json(body)
        except ValidationError as exc:
            raise UpstreamError(f"fmre returned an instrument register that does not validate: "
                                f"{str(exc)[:1500]}") from exc


def aggregation_client(base_url: str, timeout_s: float = 120.0,
                       transport: Optional[httpx.BaseTransport] = None) -> AggregationClient:
    return AggregationClient(base_url, timeout_s, transport)


def fmre_client(base_url: str, timeout_s: float = 120.0,
                transport: Optional[httpx.BaseTransport] = None) -> FmreClient:
    return FmreClient(base_url, timeout_s, transport)
