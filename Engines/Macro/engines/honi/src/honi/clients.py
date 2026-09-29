"""Typed callers for upstream engines. HoNI has one: ``datafeed``.

Everything that crosses the wire is validated against the contract on arrival. A panel
that does not validate, or that answers for a different snapshot than the one asked for,
fails the run; it is never repaired here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional, Sequence

import httpx
from pydantic import ValidationError

from .contracts import Panel, UpstreamCountry, UpstreamCoverage


class UpstreamError(RuntimeError):
    """An upstream engine could not supply a valid input. The message says which and why."""


def panel_checksum(panel: Panel) -> str:
    """sha256 of the panel's canonical JSON: the upstream fingerprint in provenance."""
    blob = json.dumps(panel.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DatafeedClient:
    """``GET /coverage`` and ``GET /panel`` on the datafeed engine."""

    def __init__(self, base_url: str, timeout_s: float = 30.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: list[tuple[str, str]], snapshot_id: str) -> httpx.Response:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"datafeed is unreachable at {self.base_url}: {exc}. Is it running? "
                "Start it with engines/datafeed/start.cmd."
            ) from exc
        if response.status_code == 404:
            raise UpstreamError(f"datafeed has no snapshot {snapshot_id!r}")
        if response.status_code != 200:
            raise UpstreamError(f"datafeed answered {response.status_code} for {path}: {response.text[:300]}")
        return response

    def current_snapshot(self) -> str:
        """The snapshot datafeed serves today (its newest; the store holds one)."""
        response = self._get("/snapshots", [], "")
        try:
            return str(response.json()[0]["snapshot_id"])
        except (ValueError, LookupError, TypeError) as exc:
            raise UpstreamError(f"datafeed returned no snapshot list: {exc}") from exc

    def countries(self) -> list[UpstreamCountry]:
        """The country registry every engine shares."""
        response = self._get("/countries", [], "")
        try:
            return [UpstreamCountry.model_validate(c) for c in response.json()]
        except (ValidationError, ValueError) as exc:
            raise UpstreamError(f"datafeed returned a country list that breaks country@1.0.0: {exc}") from exc

    def coverage(self, snapshot_id: str) -> UpstreamCoverage:
        """The gate: missingness and plausibility findings for one snapshot."""
        response = self._get("/coverage", [("snapshot_id", snapshot_id)], snapshot_id)
        try:
            return UpstreamCoverage.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(f"datafeed returned a coverage report that breaks coverage@1.0.0: {exc}") from exc

    def panel(self, snapshot_id: str, series: Sequence[str], countries: Sequence[str]) -> Panel:
        params = [("snapshot_id", snapshot_id), ("freq", "M")]
        params += [("series", s) for s in series]
        params += [("countries", c) for c in countries]
        response = self._get("/panel", params, snapshot_id)
        try:
            panel = Panel.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(f"datafeed returned a panel that breaks panel@1.1.0: {exc}") from exc
        if panel.snapshot_id != snapshot_id:
            raise UpstreamError(f"asked datafeed for snapshot {snapshot_id!r} and got {panel.snapshot_id!r}")
        return panel
