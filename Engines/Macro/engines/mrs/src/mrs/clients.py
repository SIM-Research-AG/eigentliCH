"""The typed caller for the one upstream engine, ``datafeed`` (the input panel).

Everything that crosses the wire is validated against the mirrored contract on arrival. A
payload that does not validate, or that answers for a different snapshot than the one
asked for, fails the run; it is never repaired here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional, Sequence

import httpx
from pydantic import ValidationError

from .contracts import CountryRecord, ImportConversion, Panel, UpstreamCoverage


class UpstreamError(RuntimeError):
    """An upstream engine could not supply a valid input. The message says which and why."""


def payload_checksum(content: bytes) -> str:
    """sha256 of the bytes an upstream served: the fingerprint recorded in provenance."""
    return hashlib.sha256(content).hexdigest()


def panel_checksum(panel: Panel) -> str:
    """sha256 of the panel's canonical JSON, independent of how the bytes were formatted."""
    blob = json.dumps(panel.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DatafeedClient:
    """``GET /coverage``, ``GET /panel``, ``GET /countries`` and
    ``GET /snapshots/{id}/conversions`` on datafeed.

    datafeed is the only source of data: ``mrs`` reads no file and no source table.
    """

    engine = "datafeed"

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
            raise UpstreamError(f"datafeed is unreachable at {self.base_url}: {exc}. Is it "
                                "running? Start it with engines/datafeed/start.cmd.") from exc
        if response.status_code == 404:
            raise UpstreamError(f"datafeed has no snapshot {snapshot_id!r}")
        if response.status_code != 200:
            raise UpstreamError(f"datafeed answered {response.status_code} for {path}: "
                                f"{response.text[:300]}")
        return response

    def coverage(self, snapshot_id: str) -> UpstreamCoverage:
        """The gate: missingness and plausibility findings for one snapshot."""
        response = self._get("/coverage", [("snapshot_id", snapshot_id)], snapshot_id)
        try:
            return UpstreamCoverage.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(f"datafeed returned a coverage report that breaks coverage@1.0.0: {exc}") from exc

    def panel(self, snapshot_id: str, series: Sequence[str],
              countries: Sequence[str] = ()) -> tuple[Panel, str]:
        """The panel for ``series`` (all countries unless named) and its canonical sha256.

        Fails unless every requested series comes back for at least one country: a series
        datafeed does not carry is a missing input, never an empty one.
        """
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
        absent = sorted(set(series) - {s.series_id for s in panel.series})
        if absent:
            raise UpstreamError(f"datafeed snapshot {snapshot_id!r} does not carry {absent}")
        return panel, panel_checksum(panel)

    def conversions(self, snapshot_id: str) -> list[ImportConversion]:
        """What datafeed's MATLAB importer did to each series of a raw snapshot."""
        response = self._get(f"/snapshots/{snapshot_id}/conversions", [], snapshot_id)
        try:
            return [ImportConversion.model_validate(c) for c in response.json()]
        except (ValidationError, ValueError) as exc:
            raise UpstreamError(f"datafeed returned conversions that break import-conversion@1.0.0: {exc}") from exc

    def countries(self) -> list[CountryRecord]:
        """The country registry: code and display name."""
        response = self._get("/countries", [], "")
        try:
            return [CountryRecord.model_validate(c) for c in response.json()]
        except (ValidationError, ValueError) as exc:
            raise UpstreamError(f"datafeed returned a country list that does not validate: {exc}") from exc
