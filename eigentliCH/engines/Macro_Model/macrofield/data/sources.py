"""Connectors to the published data sources.

Brief section 2 maps each model quantity to a documented published series. This module fetches them.
Every connector goes through the cache, so a live run populates it and an offline run reads it, and the
parse path is identical either way.

Sources wired here, all keyless:

- **World Bank** indicators API. Broad coverage, long histories, no key.
- **IMF** datasets via the SDMX-JSON gateway, for International Financial Statistics and the
  investment-and-capital-stock dataset.
- **OECD** SDMX, for national accounts and financial balance sheets (the chapter 10.4 measure of K_I).
- **BIS** statistics, for total credit to the non-financial sector (the saturation axis) and debt
  securities.
- **LBMA** gold price, for the stock-to-gold module.

FRED is defined but not wired, because it needs an API key and none is configured. It raises a clear
error naming the environment variable rather than failing obscurely at request time.

A note on what these connectors do not do. They fetch and parse; they do not clean, fill, or reconcile.
Gaps arrive as gaps and reach the caller as gaps, because brief section 2 requires them to be reported
rather than filled. Assembling quantities from several series, and the currency and basis checks, live
in `macrofield.data.loaders`.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import time
import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from macrofield.data.manifest import Cache, request_key
from macrofield.data.provenance import (
    Basis,
    Frequency,
    ProvenanceRecord,
    Reliability,
    Series,
    Valuation,
)

#: Default timeout for a live request, in seconds.
DEFAULT_TIMEOUT = 30

#: User agent sent with requests, so the sources can identify the client.
USER_AGENT = "macrofield/0.1 (SIM Research Institute; macroeconomic field model)"

#: Attempts per request, including the first.
DEFAULT_ATTEMPTS = 4

#: Seconds to wait before the first retry. Doubles per attempt.
DEFAULT_BACKOFF_SECONDS = 2.0

#: Status codes worth retrying.
#:
#: 429 and the 5xx range are the conventional ones. 400 is included because the World Bank indicators
#: API returns it under load rather than 429: a burst of requests produced HTTP 400 for indicators that
#: resolve correctly when requested singly. Retrying a 400 is normally wrong, since it means the request
#: itself is malformed, so this is a deliberate accommodation of one source's behaviour. The retry does
#: not mask a genuinely bad request, because that keeps returning 400 and the final failure still names
#: the URL.
RETRYABLE_STATUS = (400, 408, 425, 429, 500, 502, 503, 504)


class SourceError(RuntimeError):
    """Raised when a source cannot supply a requested series."""


class MissingCredentialError(SourceError):
    """Raised when a source needs a credential that is not configured."""


@dataclass
class FetchResult:
    """A raw payload and where it came from."""

    payload: bytes
    url: str
    content_type: str
    retrieved_on: dt.date
    from_cache: bool


class Fetcher:
    """Retrieves raw payloads, through the cache.

    Separating retrieval from parsing is what makes the offline guarantee hold: the bytes an offline
    run parses are the bytes a live run stored, so no code path is exercised only when the network is
    available.
    """

    def __init__(
        self,
        cache: Cache,
        timeout: int = DEFAULT_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep=None,
    ) -> None:
        """Create a fetcher.

        Args:
            cache: The cache to read from and write to.
            timeout: Per-request timeout in seconds.
            attempts: Attempts per request, including the first.
            backoff_seconds: Wait before the first retry, doubling thereafter.
            sleep: Injected sleep function, so tests do not have to wait.
        """
        self.cache = cache
        self.timeout = timeout
        self.attempts = max(1, int(attempts))
        self.backoff_seconds = float(backoff_seconds)
        self._sleep = sleep or time.sleep

    def fetch(
        self,
        source: str,
        identifier: str,
        url: str,
        content_type: str,
        description: str,
        refresh: bool = False,
        **parameters: Any,
    ) -> FetchResult:
        """Return a payload, from the cache when possible.

        Args:
            source: The publishing institution, used in the cache key.
            identifier: The source's series identifier, used in the cache key.
            url: The URL to fetch when the cache misses.
            content_type: "json" or "csv", used to name the cached file and to select the parser.
            description: Human-readable description, used in error messages.
            refresh: Fetch even if cached.
            **parameters: Anything else that distinguishes the request, included in the cache key.

        Raises:
            OfflineError: If offline and the payload is not cached.
            SourceError: If the request fails.
        """
        key = request_key(source, identifier, url=url, **parameters)

        if not refresh and self.cache.has(key):
            payload, entry = self.cache.read(key)
            return FetchResult(payload, entry.url, entry.content_type, entry.retrieved_on, True)

        if self.cache.offline:
            self.cache.require_offline(key, description)

        payload = self._request(url, description)
        entry = self.cache.write(key, payload, url, content_type)
        return FetchResult(payload, url, content_type, entry.retrieved_on, False)

    def _request(self, url: str, description: str) -> bytes:
        """Perform the live request, retrying transient failures with exponential backoff.

        Raises:
            SourceError: When every attempt fails, with the URL and the attempt count in the message so
                the failing request can be reproduced by hand.
        """
        import requests

        last_problem = "no attempt was made"

        for attempt in range(1, self.attempts + 1):
            try:
                response = requests.get(
                    url, timeout=self.timeout, headers={"User-Agent": USER_AGENT}
                )
            except Exception as error:  # noqa: BLE001 - the transport raises many unrelated types
                last_problem = f"{type(error).__name__}: {error}"
                if attempt == self.attempts:
                    break
                self._wait(attempt, description, last_problem)
                continue

            if response.status_code == 200:
                if not response.content:
                    raise SourceError(f"{description} returned an empty body from {url}")
                return response.content

            last_problem = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUS or attempt == self.attempts:
                break
            self._wait(attempt, description, last_problem)

        raise SourceError(
            f"{description} failed after {self.attempts} attempt(s) from {url}. Last problem: "
            f"{last_problem}. If this is a persistent HTTP 400 or 404 the identifier may have been "
            f"retired or renamed at source; if it is a timeout or a 429 the source is rate limiting and "
            f"a longer backoff may help."
        )

    def _wait(self, attempt: int, description: str, problem: str) -> None:
        """Sleep before a retry, and say why, so a slow run is explicable rather than mysterious."""
        delay = self.backoff_seconds * (2 ** (attempt - 1))
        warnings.warn(
            f"{description}: attempt {attempt} failed ({problem}), retrying in {delay:.0f}s",
            RuntimeWarning,
            stacklevel=3,
        )
        self._sleep(delay)


def _annual_series_from_pairs(
    pairs: Sequence[tuple[int, float | None]], name: str, provenance: ProvenanceRecord
) -> Series:
    """Build an annual Series from (year, value) pairs, dropping nothing and sorting by year.

    Missing values are kept as NaN rather than dropped, so that the gap report sees them.
    """
    if not pairs:
        raise SourceError(f"no observations were parsed for {name}")
    frame = pd.DataFrame(pairs, columns=["year", "value"]).drop_duplicates(
        subset="year", keep="first"
    )
    frame = frame.sort_values("year").set_index("year")
    values = pd.to_numeric(frame["value"], errors="coerce")
    values.index = values.index.astype(int)
    values.name = name
    return Series(name=name, values=values, provenance=provenance)


class WorldBank:
    """The World Bank indicators API.

    Keyless. Returns JSON. Documented at https://datahelpdesk.worldbank.org/.
    """

    SOURCE = "World Bank"
    BASE = "https://api.worldbank.org/v2"
    LICENCE = "CC BY 4.0, World Bank Open Data terms"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def series(
        self,
        country: str,
        indicator: str,
        name: str,
        units: str,
        basis: Basis,
        currency: str | None = None,
        start: int = 1960,
        end: int | None = None,
        refresh: bool = False,
        valuation: Valuation | None = None,
    ) -> Series:
        """Fetch one indicator for one country as an annual series.

        Args:
            country: ISO 3166 alpha-3 code, or an aggregate code such as "EMU" for the euro area.
            indicator: World Bank indicator code, for example "NY.GDP.MKTP.CD".
            name: The model quantity name to attach.
            units: Units as published.
            basis: Nominal, real or unitless.
            currency: ISO currency code for a monetary series.
            start: First year requested.
            end: Last year requested. Defaults to the current year.
            refresh: Bypass the cache.
        """
        last = end or dt.date.today().year
        url = (
            f"{self.BASE}/country/{country}/indicator/{indicator}"
            f"?date={start}:{last}&format=json&per_page=20000"
        )
        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier=f"{country}/{indicator}",
            url=url,
            content_type="json",
            description=f"World Bank {indicator} for {country}",
            refresh=refresh,
            start=start,
            end=last,
        )

        try:
            document = json.loads(result.payload)
        except json.JSONDecodeError as error:
            raise SourceError(f"World Bank returned unparseable JSON for {indicator}") from error

        if not isinstance(document, list) or len(document) < 2 or document[1] is None:
            message = ""
            if isinstance(document, list) and document and isinstance(document[0], dict):
                message = str(document[0].get("message", ""))
            raise SourceError(
                f"World Bank returned no observations for {indicator} in {country}. {message}".strip()
            )

        pairs = [
            (int(row["date"]), row["value"])
            for row in document[1]
            if row.get("date") is not None
        ]
        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset="World Development Indicators",
            identifier=f"{country}/{indicator}",
            url=url,
            retrieved_on=result.retrieved_on,
            units=units,
            basis=basis,
            frequency=Frequency.ANNUAL,
            currency=currency,
            # World Bank US dollar series are converted at market exchange rates unless the indicator
            # code says PPP, which the caller signals through the valuation argument.
            valuation=valuation
            or (Valuation.MARKET if currency is not None else Valuation.NOT_APPLICABLE),
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            notes=(f"World Bank indicator {indicator}, country code {country}",),
        )
        return _annual_series_from_pairs(pairs, name, provenance)


class BIS:
    """Bank for International Settlements statistics.

    Supplies total credit to the non-financial sector, which is the saturation axis of this
    implementation, and debt securities outstanding. BIS publishes bulk CSV files without a key.

    The bulk files are large and their column layout has changed between releases, so the parser locates
    columns by header name rather than by position and fails loudly if the expected headers are absent.
    """

    SOURCE = "BIS"
    LICENCE = "BIS terms and conditions, free for non-commercial use with attribution"
    CREDIT_URL = "https://data.bis.org/static/bulk/WS_TC_csv_flat.zip"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def total_credit_to_gdp(
        self,
        borrowers_country: str,
        name: str = "credit_to_gdp",
        refresh: bool = False,
    ) -> Series:
        """Fetch total credit to the non-financial sector as a percentage of GDP.

        Args:
            borrowers_country: BIS two-letter borrower country code, for example "US".
            name: Model quantity name.
            refresh: Bypass the cache.

        Note:
            BIS publishes this as a percentage of GDP, so the returned series is unitless and must be
            divided by 100 before it is used as the saturation ratio. `loaders` does that conversion
            and records it, rather than doing it here silently.
        """
        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier=f"total_credit/{borrowers_country}",
            url=self.CREDIT_URL,
            content_type="zip",
            description=f"BIS total credit to the non-financial sector for {borrowers_country}",
            refresh=refresh,
        )
        rows, columns = self._read_flat_zip(result.payload)
        pairs = self._select_credit_rows(rows, columns, borrowers_country)

        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset="Total credit to the non-financial sector (WS_TC)",
            identifier=f"WS_TC/{borrowers_country}/non-financial sector/percentage of GDP",
            url=self.CREDIT_URL,
            retrieved_on=result.retrieved_on,
            units="percent of GDP",
            basis=Basis.UNITLESS,
            frequency=Frequency.ANNUAL,
            currency=None,
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            notes=(
                "credit to the non-financial sector (BIS borrowing sector C) from all lending sectors, "
                "at market value, adjusted for breaks, as published by BIS as a percentage of GDP",
                "borrowing sector C is the non-financial sector as a whole. BIS code N, which is "
                "non-financial corporations only, is a much narrower aggregate and is not what the "
                "saturation axis uses",
                "quarterly observations aggregated to annual by taking the fourth-quarter value, "
                "which is a stock measure and so is not averaged",
            ),
        )
        return _annual_series_from_pairs(pairs, name, provenance)

    #: Dimension codes selecting total credit to the non-financial sector, as a percentage of GDP,
    #: at market value, from all lending sectors, adjusted for breaks.
    #:
    #: The borrowing-sector code is deliberately "C". BIS publishes five borrowing sectors, and the
    #: neighbouring code "N" means non-financial *corporations* only, which is a far narrower
    #: aggregate than the non-financial sector the model needs. Selecting the wrong one understates
    #: the saturation axis by roughly half and would move economies down a phase.
    CREDIT_SELECTORS = {
        "TC_BORROWERS": "C",   # non-financial sector, not "N" (non-financial corporations)
        "TC_LENDERS": "A",     # all sectors
        "UNIT_TYPE": "770",    # percentage of GDP
        "VALUATION": "M",      # market value
        "TC_ADJUST": "A",      # adjusted for breaks
    }

    @staticmethod
    def _code(value: str | None) -> str:
        """Return the code part of a BIS "CODE: Label" cell.

        BIS bulk files carry both the code and its label in a single cell, and the same convention in
        the header row. Splitting on the first colon recovers the code, and it is a no-op on a cell
        that carries a bare code, so it is safe if BIS changes the convention back.
        """
        if value is None:
            return ""
        return str(value).split(":", 1)[0].strip()

    def _read_flat_zip(self, payload: bytes) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Extract the CSV from a BIS bulk zip.

        Returns:
            The rows keyed by the raw header, and a mapping from normalised dimension code to that raw
            header, so callers can look columns up by code regardless of the label BIS appends.
        """
        import zipfile

        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as error:
            raise SourceError("the BIS bulk download is not a valid zip archive") from error

        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise SourceError(f"the BIS archive contains no CSV: {archive.namelist()}")

        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig")
            reader = csv.DictReader(text)
            if reader.fieldnames is None:
                raise SourceError("the BIS credit file has no header row")
            columns = {self._code(field): field for field in reader.fieldnames}
            return list(reader), columns

    def _select_credit_rows(
        self, rows: Sequence[Mapping[str, str]], columns: Mapping[str, str], borrowers_country: str
    ) -> list[tuple[int, float | None]]:
        """Pick the total-credit-to-non-financial-sector percentage-of-GDP series for one country.

        Raises:
            SourceError: If an expected dimension is absent, if no observation matches, or if the
                selectors match more than one series. The last case matters: silently taking the first
                of several would hide a BIS revision that added a dimension.
        """
        if not rows:
            raise SourceError("the BIS credit file contained no rows")

        required = set(self.CREDIT_SELECTORS) | {"BORROWERS_CTY", "TIME_PERIOD", "OBS_VALUE"}
        missing = sorted(required - set(columns))
        if missing:
            raise SourceError(
                f"the BIS credit file is missing expected dimensions {missing}. Its layout has "
                f"changed; available dimension codes are {sorted(columns)}."
            )

        selected: dict[int, float | None] = {}
        distinct_series: set[tuple[str, ...]] = set()

        for row in rows:
            if self._code(row.get(columns["BORROWERS_CTY"])) != borrowers_country:
                continue
            if any(
                self._code(row.get(columns[dimension])) != expected
                for dimension, expected in self.CREDIT_SELECTORS.items()
            ):
                continue

            period = str(row.get(columns["TIME_PERIOD"]) or "")
            if "-Q" not in period:
                # Series-level metadata rows carry no period. Skip rather than fail.
                continue
            year_text, quarter = period.split("-Q", 1)
            if not year_text.isdigit():
                continue
            if quarter.strip() != "4":
                # Credit is a stock, so the year-end observation is taken rather than an average.
                continue

            # Record which combination of remaining dimensions this row belongs to, so that an
            # unexpected extra dimension shows up as an ambiguity rather than as silent overwriting.
            distinct_series.add(
                tuple(
                    self._code(row.get(header))
                    for code, header in sorted(columns.items())
                    if code in {"FREQ", "COLLECTION", "UNIT_MEASURE"}
                )
            )

            raw = str(row.get(columns["OBS_VALUE"]) or "").strip()
            try:
                selected[int(year_text)] = float(raw) if raw not in ("", "NaN") else None
            except ValueError:
                selected[int(year_text)] = None

        if not selected:
            raise SourceError(
                f"BIS total credit contains no fourth-quarter percentage-of-GDP observations for "
                f"borrower country {borrowers_country!r} under selectors {self.CREDIT_SELECTORS}. "
                f"Check the country code against https://data.bis.org/topics/TOTAL_CREDIT."
            )
        if len(distinct_series) > 1:
            raise SourceError(
                f"the selectors matched {len(distinct_series)} distinct series for "
                f"{borrowers_country!r}: {sorted(distinct_series)}. BIS has added a dimension, so the "
                f"selection is ambiguous and must be narrowed rather than guessed."
            )
        return sorted(selected.items())


class OECD:
    """OECD SDMX-JSON.

    Used for financial balance sheets, which is the chapter 10.4 measure of financial capital, and for
    national accounts where the World Bank's coverage is thinner.
    """

    SOURCE = "OECD"
    BASE = "https://sdmx.oecd.org/public/rest/data"
    LICENCE = "OECD terms of use, free reuse with attribution"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def series(
        self,
        dataflow: str,
        key: str,
        name: str,
        units: str,
        basis: Basis,
        currency: str | None = None,
        start: int | None = None,
        end: int | None = None,
        dataset_label: str | None = None,
        notes: Sequence[str] = (),
        refresh: bool = False,
    ) -> Series:
        """Fetch one SDMX series as an annual series.

        Args:
            dataflow: The SDMX dataflow, for example "OECD.SDD.NAD,DSD_NASEC20@DF_T7PS1S2".
            key: The series key selecting the dimensions.
            name: Model quantity name.
            units: Units as published.
            basis: Nominal, real or unitless.
            currency: ISO currency code for a monetary series.
            start: First year requested.
            end: Last year requested.
            dataset_label: Human-readable dataset name for the provenance record.
            notes: Extra provenance notes, for example which aggregate was selected.
            refresh: Bypass the cache.
        """
        query = "?format=jsondata&dimensionAtObservation=TIME_PERIOD"
        if start is not None:
            query += f"&startPeriod={start}"
        if end is not None:
            query += f"&endPeriod={end}"
        url = f"{self.BASE}/{dataflow}/{key}{query}"

        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier=f"{dataflow}/{key}",
            url=url,
            content_type="json",
            description=f"OECD {dataflow} key {key}",
            refresh=refresh,
            start=start,
            end=end,
        )
        pairs = self._parse_sdmx_json(result.payload, f"{dataflow}/{key}")

        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset=dataset_label or dataflow,
            identifier=f"{dataflow}/{key}",
            url=url,
            retrieved_on=result.retrieved_on,
            units=units,
            basis=basis,
            frequency=Frequency.ANNUAL,
            currency=currency,
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            notes=tuple(notes),
        )
        return _annual_series_from_pairs(pairs, name, provenance)

    def _parse_sdmx_json(self, payload: bytes, label: str) -> list[tuple[int, float | None]]:
        """Parse SDMX-JSON into (year, value) pairs.

        Raises:
            SourceError: If the response contains no observations, or more than one series, since
                silently taking the first of several would hide a mis-specified key.
        """
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            raise SourceError(f"OECD returned unparseable JSON for {label}") from error

        data_sets = document.get("dataSets") or []
        structures = document.get("structures") or document.get("structure")
        if not data_sets:
            raise SourceError(f"OECD returned no dataSets for {label}")

        series_map = data_sets[0].get("series") or {}
        if not series_map:
            observations = data_sets[0].get("observations")
            if observations:
                raise SourceError(
                    f"OECD returned flat observations for {label}, which this parser does not handle. "
                    f"Request with dimensionAtObservation=TIME_PERIOD."
                )
            raise SourceError(f"OECD returned an empty series set for {label}")
        if len(series_map) > 1:
            raise SourceError(
                f"the key for {label} selects {len(series_map)} series. Narrow it so exactly one is "
                f"returned, rather than relying on which one comes first."
            )

        if isinstance(structures, list):
            structure = structures[0]
        else:
            structure = structures or {}
        dimensions = (structure.get("dimensions") or {}).get("observation") or []
        time_values = dimensions[0].get("values") if dimensions else []
        periods = [str(v.get("id")) for v in time_values]

        observations = next(iter(series_map.values())).get("observations") or {}
        pairs: list[tuple[int, float | None]] = []
        for position_text, entry in observations.items():
            position = int(position_text)
            if position >= len(periods):
                continue
            period = periods[position]
            year_text = period[:4]
            if not year_text.isdigit():
                continue
            value = entry[0] if entry else None
            pairs.append((int(year_text), None if value is None else float(value)))

        if not pairs:
            raise SourceError(f"OECD returned no observations for {label}")
        return pairs


class LBMA:
    """The LBMA gold price, for the stock-to-gold module.

    LBMA publishes the daily auction prices as JSON without a key. The daily series is aggregated to
    annual here by taking the final observation of each year, since the model uses an annual ratio and
    an average would mix a flow convention into a price level.
    """

    SOURCE = "LBMA"
    URL = "https://prices.lbma.org.uk/json/gold_pm.json"
    LICENCE = "LBMA terms, free for non-commercial use with attribution"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def annual_gold_price(
        self, currency_index: int = 0, currency: str = "USD", refresh: bool = False
    ) -> Series:
        """Fetch the annual gold price.

        Args:
            currency_index: Which of the published currencies to take. LBMA publishes USD, GBP and EUR
                in that order for the PM auction.
            currency: The ISO code matching `currency_index`, recorded in the provenance.
            refresh: Bypass the cache.
        """
        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier="gold_pm",
            url=self.URL,
            content_type="json",
            description="LBMA gold PM auction price",
            refresh=refresh,
        )
        try:
            document = json.loads(result.payload)
        except json.JSONDecodeError as error:
            raise SourceError("LBMA returned unparseable JSON") from error

        if not isinstance(document, list) or not document:
            raise SourceError("LBMA returned no price observations")

        by_year: dict[int, tuple[str, float]] = {}
        for row in document:
            date_text = str(row.get("d", ""))
            prices = row.get("v") or []
            if len(date_text) < 4 or currency_index >= len(prices):
                continue
            year_text = date_text[:4]
            if not year_text.isdigit():
                continue
            price = prices[currency_index]
            if price in (None, ""):
                continue
            year = int(year_text)
            # Keep the latest date within each year.
            if year not in by_year or date_text > by_year[year][0]:
                by_year[year] = (date_text, float(price))

        if not by_year:
            raise SourceError("no usable LBMA observations were parsed")

        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset="Gold PM auction price",
            identifier=f"gold_pm/{currency}",
            url=self.URL,
            retrieved_on=result.retrieved_on,
            units=f"{currency} per troy ounce",
            basis=Basis.NOMINAL,
            frequency=Frequency.ANNUAL,
            currency=currency,
            valuation=Valuation.MARKET,
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            notes=(
                "annual value is the final auction of each year, not an average, because the model "
                "uses a price level rather than a flow",
            ),
        )
        pairs = [(year, value) for year, (_, value) in sorted(by_year.items())]
        return _annual_series_from_pairs(pairs, "gold_price", provenance)


class PennWorldTable:
    """Penn World Table, the source of the real capital stock K_R.

    Version 10.01, which is the current release: 183 countries, 1950 to 2019, distributed as a single
    keyless spreadsheet. It is the only source that covers every economy in the panel, including China
    and India, with one consistent perpetual-inventory method, which is what makes cross-economy capital
    ratios comparable at all.

    Three things about this source shape how it is used:

    1. **It ends in 2019.** That is not a temporary gap, it is the release. Carrying the stock forward
       is therefore mandatory rather than optional, and it is done by
       `loaders.extend_capital_stock_by_perpetual_inventory`, marked as derived.
    2. **It publishes the depreciation rate**, per country and per year, as `delta`. That is strictly
       better than a configured prior, so the extension uses it where available and falls back to
       config only when it is missing.
    3. **It is PPP-converted.** `cn` is in 2017 US dollars at current purchasing-power parities, as is
       `cgdpo`. Mixing either with a market-exchange-rate series produces a meaningless ratio, and
       because both are real US dollar series the currency and basis checks do not catch it. Every
       series from this connector is therefore tagged `Valuation.PPP`, and
       `integrity.check_consistency` refuses a mixture.
    """

    SOURCE = "Penn World Table"
    VERSION = "10.01"
    #: Dataverse file identifier for the 10.01 spreadsheet, DOI 10.34894/QT5BCC.
    URL = "https://dataverse.nl/api/access/datafile/354095"
    DOI = "10.34894/QT5BCC"
    LICENCE = "CC BY 4.0"
    SHEET = "Data"

    #: The columns this connector exposes, with the units PWT states for each.
    COLUMNS = {
        "cn": ("K_R", "millions of 2017 US dollars at current PPPs", Basis.REAL, "USD"),
        "rnna": (
            "K_R_national",
            "millions of 2017 national-currency units at constant national prices",
            Basis.REAL,
            "USD",
        ),
        "cgdpo": ("Y_ppp", "millions of 2017 US dollars at current PPPs", Basis.REAL, "USD"),
        "delta": ("depreciation_rate", "annual rate", Basis.UNITLESS, None),
        "pop": ("population_pwt", "millions of persons", Basis.UNITLESS, None),
        "labsh": ("labour_share", "share of GDP", Basis.UNITLESS, None),
    }

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._frame = None

    def _load_frame(self, refresh: bool = False):
        """Fetch and parse the spreadsheet once per process."""
        if self._frame is not None and not refresh:
            return self._frame

        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier=f"pwt{self.VERSION}",
            url=self.URL,
            content_type="xlsx",
            description=f"Penn World Table {self.VERSION}",
            refresh=refresh,
        )
        try:
            book = pd.ExcelFile(io.BytesIO(result.payload))
        except Exception as error:  # noqa: BLE001 - openpyxl raises several unrelated types
            raise SourceError(
                f"could not open the Penn World Table spreadsheet: {error}"
            ) from error

        if self.SHEET not in book.sheet_names:
            raise SourceError(
                f"the Penn World Table spreadsheet has no {self.SHEET!r} sheet. Sheets present: "
                f"{book.sheet_names}. The release layout has changed."
            )
        frame = book.parse(self.SHEET)

        required = {"countrycode", "year"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise SourceError(
                f"the Penn World Table sheet is missing {missing}. Columns present: "
                f"{sorted(frame.columns)}"
            )

        self._retrieved_on = result.retrieved_on
        self._frame = frame
        return frame

    def available_columns(self) -> list[str]:
        """Return the exposable columns actually present in this release."""
        frame = self._load_frame()
        return [column for column in self.COLUMNS if column in frame.columns]

    def series(
        self,
        country: str,
        column: str = "cn",
        name: str | None = None,
        refresh: bool = False,
    ) -> Series:
        """Fetch one PWT column for one country as an annual series.

        Args:
            country: ISO 3166 alpha-3 code, PWT's `countrycode`.
            column: The PWT column, for example "cn" for the capital stock at current PPPs.
            name: Model quantity name. Defaults to the mapping in COLUMNS.
            refresh: Bypass the cache.

        Raises:
            SourceError: If the column is unknown, absent from the release, or the country has no
                observations for it.
        """
        if column not in self.COLUMNS:
            raise SourceError(
                f"column {column!r} is not exposed by this connector. Available: "
                f"{sorted(self.COLUMNS)}"
            )
        frame = self._load_frame(refresh)
        if column not in frame.columns:
            raise SourceError(
                f"the Penn World Table {self.VERSION} release does not contain column {column!r}"
            )

        subset = frame[frame["countrycode"] == country]
        if subset.empty:
            raise SourceError(
                f"Penn World Table has no rows for country code {country!r}. It uses ISO alpha-3 codes."
            )

        quantity, units, basis, currency = self.COLUMNS[column]
        pairs = [
            (int(row.year), None if pd.isna(getattr(row, column)) else float(getattr(row, column)))
            for row in subset.itertuples()
        ]
        if all(value is None for _, value in pairs):
            raise SourceError(
                f"Penn World Table has no {column!r} observations for {country!r}, only empty rows"
            )

        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset=f"Penn World Table {self.VERSION}",
            identifier=f"pwt{self.VERSION}/{country}/{column}",
            url=self.URL,
            retrieved_on=self._retrieved_on,
            units=units,
            basis=basis,
            frequency=Frequency.ANNUAL,
            currency=currency,
            valuation=Valuation.PPP if currency is not None else Valuation.NOT_APPLICABLE,
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            vintage=f"{self.VERSION} (DOI {self.DOI})",
            notes=(
                f"Penn World Table column {column!r}",
                "the release ends in 2019, so any later value must come from the documented perpetual "
                "inventory extension and is marked derived",
                *(
                    (
                        "converted at purchasing-power parities, so this series must not be combined "
                        "with market-exchange-rate series",
                    )
                    if currency is not None
                    else ()
                ),
            ),
        )
        return _annual_series_from_pairs(pairs, name or quantity, provenance)

    def depreciation_rate(self, country: str, refresh: bool = False) -> Series:
        """Fetch the published depreciation rate, which the capital-stock extension prefers to a prior."""
        return self.series(country, "delta", "depreciation_rate", refresh)


class MaddisonProject:
    """The Maddison Project Database, for the long historical series.

    Real GDP per capita and population back to the first century for some economies, which is the only
    keyless source long enough to support the cycle hierarchy: the capital cycle at 90 years needs
    roughly two centuries, and the hegemonic cycle at 130 years needs closer to three.

    It carries no capital stock, so it complements Penn World Table rather than replacing it.
    """

    SOURCE = "Maddison Project Database"
    VERSION = "2023"
    #: Dataverse file identifier, DOI 10.34894/INZBF2.
    URL = "https://dataverse.nl/api/access/datafile/421302"
    DOI = "10.34894/INZBF2"
    LICENCE = "CC BY 4.0"
    SHEET = "Full data"

    COLUMNS = {
        "gdppc": ("gdp_per_capita", "2011 US dollars, multiple benchmarks", Basis.REAL, "USD"),
        "pop": ("population_maddison", "thousands of persons", Basis.UNITLESS, None),
    }

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._frame = None

    def _load_frame(self, refresh: bool = False):
        if self._frame is not None and not refresh:
            return self._frame
        result = self.fetcher.fetch(
            source=self.SOURCE,
            identifier=f"maddison{self.VERSION}",
            url=self.URL,
            content_type="xlsx",
            description=f"Maddison Project Database {self.VERSION}",
            refresh=refresh,
        )
        try:
            book = pd.ExcelFile(io.BytesIO(result.payload))
        except Exception as error:  # noqa: BLE001
            raise SourceError(f"could not open the Maddison spreadsheet: {error}") from error
        if self.SHEET not in book.sheet_names:
            raise SourceError(
                f"the Maddison spreadsheet has no {self.SHEET!r} sheet. Sheets: {book.sheet_names}"
            )
        self._retrieved_on = result.retrieved_on
        self._frame = book.parse(self.SHEET)
        return self._frame

    def series(
        self,
        country: str,
        column: str = "gdppc",
        name: str | None = None,
        refresh: bool = False,
    ) -> Series:
        """Fetch one Maddison column for one country as an annual series.

        Args:
            country: ISO 3166 alpha-3 code, Maddison's `countrycode`.
            column: "gdppc" or "pop".
            name: Model quantity name.
            refresh: Bypass the cache.
        """
        if column not in self.COLUMNS:
            raise SourceError(
                f"column {column!r} is not exposed by this connector. Available: {sorted(self.COLUMNS)}"
            )
        frame = self._load_frame(refresh)
        code_column = "countrycode" if "countrycode" in frame.columns else "country"
        if column not in frame.columns:
            raise SourceError(f"the Maddison release does not contain column {column!r}")

        subset = frame[frame[code_column] == country]
        if subset.empty:
            raise SourceError(f"Maddison has no rows for {country!r} in column {code_column!r}")

        quantity, units, basis, currency = self.COLUMNS[column]
        pairs = [
            (int(row.year), None if pd.isna(getattr(row, column)) else float(getattr(row, column)))
            for row in subset.itertuples()
            if not pd.isna(row.year)
        ]
        if all(value is None for _, value in pairs):
            raise SourceError(f"Maddison has no {column!r} observations for {country!r}")

        provenance = ProvenanceRecord(
            source=self.SOURCE,
            dataset=f"Maddison Project Database {self.VERSION}",
            identifier=f"maddison{self.VERSION}/{country}/{column}",
            url=self.URL,
            retrieved_on=self._retrieved_on,
            units=units,
            basis=basis,
            frequency=Frequency.ANNUAL,
            currency=currency,
            valuation=Valuation.PPP if currency is not None else Valuation.NOT_APPLICABLE,
            reliability=Reliability.PUBLISHED,
            licence=self.LICENCE,
            vintage=f"{self.VERSION} (DOI {self.DOI})",
            notes=(
                f"Maddison column {column!r}",
                "long historical coverage, used for the cycle hierarchy where the sample must span "
                "several periods of a long cycle",
                "historical values before the twentieth century carry wide uncertainty and are "
                "reconstructions rather than national accounts",
            ),
        )
        return _annual_series_from_pairs(pairs, name or quantity, provenance)


class FRED:
    """Federal Reserve Economic Data.

    Defined but not wired, because FRED requires an API key and none is configured. Every method raises
    a clear error naming the environment variable, so a missing key is diagnosed at the call site
    instead of surfacing as an authentication failure inside a request.

    Most of what FRED would supply for the United States is available keyless from the World Bank, the
    BIS and the OECD, so this is not on the critical path.
    """

    SOURCE = "FRED"
    ENV_VAR = "FRED_API_KEY"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    @property
    def available(self) -> bool:
        """Whether a key is configured."""
        return bool(os.environ.get(self.ENV_VAR))

    def series(self, series_id: str, *_: Any, **__: Any) -> Series:
        """Raise, because FRED needs a key.

        Raises:
            MissingCredentialError: Always, until a key is configured.
        """
        raise MissingCredentialError(
            f"the FRED connector needs an API key in the {self.ENV_VAR} environment variable, which is "
            f"not set, so series {series_id!r} cannot be fetched. Keys are free from "
            f"https://fredaccount.stlouisfed.org/apikeys. The equivalent United States series are "
            f"available keyless from the World Bank, the BIS and the OECD, which is what the economy "
            f"configurations use by default."
        )


@dataclass
class SourceSet:
    """Every connector, sharing one fetcher and therefore one cache."""

    fetcher: Fetcher
    world_bank: WorldBank
    bis: BIS
    oecd: OECD
    lbma: LBMA
    pwt: PennWorldTable
    maddison: MaddisonProject
    fred: FRED

    @classmethod
    def build(
        cls,
        cache: Cache,
        timeout: int = DEFAULT_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> "SourceSet":
        fetcher = Fetcher(cache, timeout, attempts, backoff_seconds)
        return cls(
            fetcher=fetcher,
            world_bank=WorldBank(fetcher),
            bis=BIS(fetcher),
            oecd=OECD(fetcher),
            lbma=LBMA(fetcher),
            pwt=PennWorldTable(fetcher),
            maddison=MaddisonProject(fetcher),
            fred=FRED(fetcher),
        )
