"""Typed callers for public data sources. datafeed has no upstream engine; these are its
only outbound calls, and only the bootstrap makes them.

Every response is kept whole (its sha256 goes into the store), so a fill can always be
traced to the exact bytes it came from and re-derived offline.

``worldbank``  World Bank Indicators API v2, annual values. No key.
``imf``        IMF DataMapper API v1 (WEO and related), annual values. No key. The WEO
               carries projections; the caller decides which years it may use.
``cboe``       Cboe index history files (SKEW, VIX, VXFXI, VXEWZ, ...), daily closes. No key.
``bis``        BIS SDMX API v1, effective exchange rates (WS_EER), monthly. No key.

The two market providers (DF-18) return month-end values: the last daily close in each
calendar month for Cboe, the monthly average as BIS publishes it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx


class PublicSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicResponse:
    provider: str
    code: str
    iso3: str
    url: str
    sha256: str
    values: dict[int, float]


def _get(client: httpx.Client, url: str, params: dict, attempts: int = 3) -> bytes:
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            r = client.get(url, params=params)
            if r.status_code == 200:
                return r.content
            last = PublicSourceError(f"{url} answered {r.status_code}")
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise PublicSourceError(f"{url}: {last}")


class WorldBankClient:
    provider = "worldbank"
    base = "https://api.worldbank.org/v2"

    def __init__(self, client: httpx.Client):
        self.client = client

    def annual(self, iso3: str, code: str) -> PublicResponse:
        url = f"{self.base}/country/{iso3}/indicator/{code}"
        params = {"format": "json", "date": "1990:2030", "per_page": 200}
        body = _get(self.client, url, params)
        data = json.loads(body)
        if not isinstance(data, list) or len(data) < 2:
            message = data[0].get("message") if isinstance(data, list) and data else data
            raise PublicSourceError(f"World Bank {code}/{iso3}: {message}")
        values = {int(r["date"]): float(r["value"]) for r in (data[1] or [])
                  if r.get("value") is not None and str(r.get("date", "")).isdigit()}
        return PublicResponse(self.provider, code, iso3, str(httpx.URL(url, params=params)),
                              hashlib.sha256(body).hexdigest(), values)


class IMFDataMapperClient:
    provider = "imf"
    base = "https://www.imf.org/external/datamapper/api/v1"

    def __init__(self, client: httpx.Client):
        self.client = client

    def annual(self, iso3: str, code: str) -> PublicResponse:
        url = f"{self.base}/{code}/{iso3}"
        body = _get(self.client, url, {})
        data = json.loads(body)
        try:
            series = data["values"][code].get(iso3, {})
        except (KeyError, AttributeError, TypeError) as exc:
            raise PublicSourceError(f"IMF {code}/{iso3}: unexpected response") from exc
        values = {int(y): float(v) for y, v in series.items() if v is not None}
        return PublicResponse(self.provider, code, iso3, url, hashlib.sha256(body).hexdigest(), values)


@dataclass(frozen=True)
class MonthlyResponse:
    provider: str
    code: str
    url: str
    sha256: str
    #: month end (YYYY-MM-DD) -> value
    values: dict[str, float]


def _month_end(year: int, month: int) -> str:
    import calendar
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def parse_cboe(body: bytes) -> dict[str, float]:
    """Daily Cboe history -> the last close of each calendar month.

    Two layouts exist: ``DATE,OPEN,HIGH,LOW,CLOSE`` and ``DATE,<INDEX>`` (SKEW). Dates are
    MM/DD/YYYY. A row that does not parse is an error, not a skip: a silently shortened
    history would look like a real gap.
    """
    import csv
    import io
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    if not rows or rows[0][0].strip().upper() != "DATE":
        raise PublicSourceError("Cboe: no DATE header")
    header = [h.strip().upper() for h in rows[0]]
    col = header.index("CLOSE") if "CLOSE" in header else len(header) - 1
    last: dict[str, tuple[str, float]] = {}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        m, d, y = (int(x) for x in r[0].strip().split("/"))
        if not r[col].strip():
            continue
        key = _month_end(y, m)
        iso = f"{y:04d}-{m:02d}-{d:02d}"
        if key not in last or iso > last[key][0]:
            last[key] = (iso, float(r[col]))
    return {k: v for k, (_, v) in sorted(last.items())}


def parse_bis(body: bytes) -> dict[str, float]:
    """BIS SDMX CSV -> month end -> value (TIME_PERIOD YYYY-MM, OBS_VALUE)."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    out: dict[str, float] = {}
    for r in reader:
        v = (r.get("OBS_VALUE") or "").strip()
        if not v or v.upper() == "NAN":
            continue
        y, m = (int(x) for x in r["TIME_PERIOD"].split("-")[:2])
        out[_month_end(y, m)] = float(v)
    if not out:
        raise PublicSourceError("BIS: no observations")
    return dict(sorted(out.items()))


class CboeClient:
    provider = "cboe"
    base = "https://cdn.cboe.com/api/global/us_indices/daily_prices"

    def __init__(self, client: httpx.Client):
        self.client = client

    def monthly(self, code: str) -> MonthlyResponse:
        url = f"{self.base}/{code}_History.csv"
        body = _get(self.client, url, {})
        return MonthlyResponse(self.provider, code, url, hashlib.sha256(body).hexdigest(), parse_cboe(body))


class BISClient:
    """``code`` is the WS_EER key, e.g. ``M.N.B.BR`` (monthly, nominal, broad basket)."""

    provider = "bis"
    base = "https://stats.bis.org/api/v1/data/WS_EER"

    def __init__(self, client: httpx.Client):
        self.client = client

    def monthly(self, code: str) -> MonthlyResponse:
        url = f"{self.base}/{code}"
        params = {"format": "csv"}
        body = _get(self.client, url, params)
        return MonthlyResponse(self.provider, code, str(httpx.URL(url, params=params)),
                               hashlib.sha256(body).hexdigest(), parse_bis(body))


def market_clients(timeout_s: float = 60.0, transport: Optional[httpx.BaseTransport] = None):
    """Cboe redirects to its API host, so redirects are followed."""
    client = httpx.Client(timeout=timeout_s, transport=transport, follow_redirects=True,
                          headers={"User-Agent": "sim-tech-datafeed/1.0"})
    return client, {"cboe": CboeClient(client), "bis": BISClient(client)}


def public_clients(timeout_s: float = 60.0, transport: Optional[httpx.BaseTransport] = None):
    client = httpx.Client(timeout=timeout_s, transport=transport,
                          headers={"User-Agent": "sim-tech-datafeed/1.0"})
    return client, {"worldbank": WorldBankClient(client), "imf": IMFDataMapperClient(client)}
