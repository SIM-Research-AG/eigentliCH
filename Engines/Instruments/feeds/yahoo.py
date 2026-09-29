"""Monthly total returns from Yahoo Finance.

**This is the first data in the engine that was not already on the NAS**, and that is a
change worth stating rather than absorbing. Until now every figure traced to
Knowledge_Center or to the previous build's directory, and a test asserted that nothing
had been downloaded. That test now asserts something narrower: that nothing was downloaded
*except through this module*, and that every row it writes is labelled ``internet:yahoo``.

What comes back is **adjusted close**, which folds dividends and splits back in, so a
month-on-month change of adjusted close is a total return rather than a price return. That
matters for anything with a distribution -- bonds, real estate, high yield -- where price
return alone would understate performance by most of the coupon.

Two limits that travel with every series this produces:

* **Everything is quoted in USD.** The proxies are US-listed. The register prices these
  instruments in CHF, EUR, GBP, JPY and five other currencies, so a USD series carries the
  dollar's movement on top of the asset's. Until the currency work lands, a downloaded
  series is a USD total return and is stored saying so.
* **A proxy is not the instrument.** Each carries a grade from ``feeds.proxy_map``, and the
  grade is stored on every row.

No API key, no licence agreement, and no redistribution right. Fine for a development
test bench; not a basis for anything published.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

#: Yahoo rejects the default urllib agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sim-tech-instruments/1.0)"}

#: Seconds between requests. Deliberately unhurried: this runs once, and a public endpoint
#: with no agreement behind it should not be hammered.
THROTTLE_SECONDS = 0.5

TIMEOUT_SECONDS = 30


class FeedError(RuntimeError):
    """Raised when a symbol cannot be fetched or does not look like a price series."""


@dataclass(frozen=True)
class MonthlySeries:
    """One symbol's monthly total-return history."""

    symbol: str
    currency: str
    first_period: str
    last_period: str
    #: ``{"YYYY-MM": simple monthly return}``
    returns: dict[str, float]
    #: The adjusted-close levels the returns were derived from, for auditing.
    levels: dict[str, float]
    fetched_at: str

    @property
    def months(self) -> int:
        return len(self.returns)


def _request(symbol: str) -> dict:
    url = (
        f"{BASE}{urllib.parse.quote(symbol)}"
        f"?interval=1mo&period1=0&period2=9999999999&events=div%7Csplit"
    )
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise FeedError(f"{symbol}: HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 - urllib raises a wide family here
        raise FeedError(f"{symbol}: {type(exc).__name__}: {exc}") from exc


def fetch(symbol: str) -> MonthlySeries:
    """Fetch one symbol's monthly adjusted-close series and difference it into returns."""
    payload = _request(symbol)
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise FeedError(f"{symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise FeedError(f"{symbol}: no result in the response")
    result = results[0]

    stamps = result.get("timestamp") or []
    adjusted = (
        (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    )
    if not stamps or not adjusted:
        raise FeedError(
            f"{symbol}: no adjusted close. Price return alone would understate anything "
            f"that pays a distribution, so this is refused rather than substituted."
        )

    levels: dict[str, float] = {}
    seen: dict[str, int] = {}
    for stamp, value in zip(stamps, adjusted):
        if value is None or value <= 0:
            continue
        # Yahoo stamps a monthly bar at **local midnight** on the first of the month, in
        # the exchange's time zone. For New York that is 04:00 or 05:00 UTC on the 1st and
        # reading the stamp in UTC is harmless. For London it is 23:00 UTC on the *last
        # day of the previous month* all summer, so reading it in UTC filed every BST
        # month one month early and lost October entirely -- found on the FX rates
        # (CHF=X), 28 September 2026. Half a day past the stamp lands inside the 1st for
        # any offset between UTC-12 and UTC+12, and leaves every US-listed series exactly
        # as it was.
        period = datetime.fromtimestamp(stamp + 43200, tz=timezone.utc).strftime("%Y-%m")
        seen[period] = seen.get(period, 0) + 1
        levels[period] = float(value)

    months = sorted(levels)
    # Two bars in one month mean the labelling above is wrong for this symbol. The month
    # in progress is exempt: Yahoo sometimes appends a bar for today, and that month is
    # dropped below anyway.
    doubled = [p for p, n in seen.items() if n > 1 and p != months[-1]]
    if doubled:
        raise FeedError(f"{symbol}: two monthly bars fell in {doubled[:3]}; the period "
                        f"labelling does not fit this symbol's time stamps")
    if len(months) < 13:
        raise FeedError(f"{symbol}: only {len(months)} months, too short to be useful")

    # The final bar is the month in progress and is incomplete; drop it.
    months = months[:-1]

    returns: dict[str, float] = {}
    for previous, current in zip(months, months[1:]):
        before, after = levels[previous], levels[current]
        if before <= 0:
            continue
        returns[current] = after / before - 1.0

    return MonthlySeries(
        symbol=symbol,
        currency=str(result.get("meta", {}).get("currency") or "USD"),
        first_period=months[1] if len(months) > 1 else months[0],
        last_period=months[-1],
        returns=returns,
        levels={m: levels[m] for m in months},
        fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )


def fetch_many(symbols: list[str], *, throttle: float = THROTTLE_SECONDS,
               on_progress=None) -> tuple[dict[str, MonthlySeries], dict[str, str]]:
    """Fetch several symbols. Returns ``(series, failures)`` -- a failure is not fatal.

    One symbol going missing must not lose the other forty. The caller decides what an
    incomplete download means.
    """
    series: dict[str, MonthlySeries] = {}
    failures: dict[str, str] = {}
    for index, symbol in enumerate(dict.fromkeys(symbols)):
        if index:
            time.sleep(throttle)
        try:
            series[symbol] = fetch(symbol)
            if on_progress:
                on_progress(symbol, series[symbol], None)
        except FeedError as exc:
            failures[symbol] = str(exc)
            if on_progress:
                on_progress(symbol, None, str(exc))
    return series, failures
