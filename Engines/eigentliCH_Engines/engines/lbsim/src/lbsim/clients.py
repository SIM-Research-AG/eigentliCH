"""HTTP clients of the four engines lbsim reads (spec 3.8). GET only; lbsim never writes upstream.

Each call returns the JSON as served, so the store can record its sha256 and the mirrors in ``contracts`` can read
it. The refusals: an unknown id is 404 (``NotFound``), an engine that does not answer or answers with a server
error is 503 (``UpstreamDown``), fmre's 422 for inflation it cannot compute stays 422. The lbs checks of 3.8
(client_ref, ``request_hash == sheet.provenance.request_hash``, the records with their approval state) are here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .contracts import LbsArtefactRequest, LbsCalibration, LbsSheet
from .errors import Conflict, InvalidRequest, NotFound, UpstreamDown
from .settings import UpstreamConfig

LBS_RECORDS = ("human-capital", "property-funding", "ahv-pension", "bvg-projection")


class _Client:
    name = "upstream"

    def __init__(self, url: str, timeouts: tuple[float, float], transport: Optional[httpx.BaseTransport] = None):
        self.url = url.rstrip("/")
        self.timeout = httpx.Timeout(timeouts[1], connect=timeouts[0])
        self.transport = transport

    def get(self, path: str, params: Optional[dict[str, Any]] = None, *, what: str = "") -> Any:
        try:
            with httpx.Client(base_url=self.url, timeout=self.timeout, transport=self.transport) as http:
                resp = http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamDown(f"{self.name} at {self.url} does not answer ({type(exc).__name__}); lbsim cannot read "
                               f"{what or path} now. Start {self.name} and try again.") from exc
        if resp.status_code == 404:
            raise NotFound(f"{self.name} knows no {what or path}.")
        if resp.status_code == 422:
            raise InvalidRequest(f"{self.name} refused {what or path}: {_detail(resp)}")
        if resp.status_code >= 400:
            raise UpstreamDown(f"{self.name} answered {resp.status_code} for {what or path}: {_detail(resp)}")
        return resp.json()


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    return str(body.get("detail") if isinstance(body, dict) else body)[:300]


class LbsClient(_Client):
    name = "lbs"

    def sheet(self, sheet_id: str) -> dict[str, Any]:
        return self.get(f"/artefacts/{sheet_id}", what=f"Life Balance Sheet {sheet_id}")

    def request(self, sheet_id: str) -> dict[str, Any]:
        return self.get(f"/artefacts/{sheet_id}/request", what=f"request of Life Balance Sheet {sheet_id}")

    def calibration(self, version: str) -> dict[str, Any]:
        return self.get("/calibration", {"version": version}, what=f"lbs calibration {version}")


class PcpClient(_Client):
    name = "pcp"

    def allocation(self, allocation_id: str) -> dict[str, Any]:
        return self.get(f"/allocation/{allocation_id}", what=f"allocation {allocation_id}")


class AggregationClient(_Client):
    name = "aggregation"

    def regime(self, regime_id: str) -> dict[str, Any]:
        return self.get(f"/regime/{regime_id}", what=f"Regime {regime_id}")

    def scenarios(self) -> list[dict[str, Any]]:
        return self.get("/scenarios", what="the scenario list")

    def policies(self) -> list[dict[str, Any]]:
        return self.get("/scenarios/policies", what="the scenario policies")


class FmreClient(_Client):
    name = "fmre"

    def return_set(self, regime_id: str, basis: str = "nominal") -> dict[str, Any]:
        params = {"regime_id": regime_id, "currency": "CHF", "include_instruments": "true",
                  "include_blocks": "false"}
        if basis != "nominal":
            params["basis"] = basis
        return self.get("/v1/return-set", params, what=f"the Swiss-franc return figures of Regime {regime_id}")

    def inflation(self, regime_id: str) -> dict[str, Any]:
        return self.get("/v1/inflation", {"currency": "CHF", "regime_id": regime_id},
                        what=f"the Swiss inflation of Regime {regime_id}")


@dataclass
class Upstream:
    """The four clients together; the service reads through this and nothing else."""

    lbs: LbsClient
    pcp: PcpClient
    aggregation: AggregationClient
    fmre: FmreClient

    @classmethod
    def from_config(cls, cfg: UpstreamConfig, transport: Optional[httpx.BaseTransport] = None) -> "Upstream":
        t = (cfg.connect_s, cfg.read_s)
        return cls(lbs=LbsClient(cfg.lbs_url, t, transport), pcp=PcpClient(cfg.pcp_url, t, transport),
                   aggregation=AggregationClient(cfg.aggregation_url, t, transport),
                   fmre=FmreClient(cfg.fmre_url, t, transport))

    def describe(self) -> dict[str, str]:
        return {"lbs": self.lbs.url, "pcp": self.pcp.url, "aggregation": self.aggregation.url, "fmre": self.fmre.url}

    # -- lbs, with the checks of 3.8

    def read_sheet(self, sheet_id: str, client_ref: str) -> tuple[LbsSheet, dict[str, Any], LbsArtefactRequest,
                                                                  dict[str, dict[str, Any]]]:
        raw = self.lbs.sheet(sheet_id)
        sheet = LbsSheet.model_validate(raw)
        if sheet.client_ref != client_ref:
            raise Conflict("The Life Balance Sheet belongs to another client than the one named in the request.")
        req = LbsArtefactRequest.model_validate(self.lbs.request(sheet_id))
        if req.request_hash != sheet.provenance.request_hash or req.artefact_id != sheet.artefact_id:
            raise Conflict("lbs's stored request does not hash to the sheet's request hash, so the sheet cannot be "
                           "traced to what the household stated.")
        cal = LbsCalibration.model_validate(self.lbs.calibration(sheet.calibration_version))
        missing = [n for n in ("human-capital", "property-funding") if n not in cal.records]
        if missing:
            raise Conflict(f"lbs calibration {sheet.calibration_version} lacks the records {missing} lbsim reads.")
        records = {n: cal.records[n] for n in LBS_RECORDS if n in cal.records}
        return sheet, raw, req, records
