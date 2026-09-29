"""Monthly total returns of Cboe strategy indices, from Cboe's public daily history files.

Added 29 September 2026 for one instrument: the register names **Long Volatility Index**
by the Cboe VIX Tail Hedge index (VXTH), and Yahoo does not carry that index's history
(``^VXTH`` returns a single bar). Cboe publishes it itself, as a daily CSV of closing
levels from 31 March 2006, at the same public address Engine 01's datafeed already reads
SKEW and the country volatility indices from. No API key, no licence agreement, no
redistribution right, exactly as for ``feeds/yahoo.py``: fine for a development test bench,
not a basis for anything published.

**What comes back is the index level, and the index is already a total return.** VXTH is a
hypothetical portfolio of the S&P 500 with dividends reinvested plus a rolling position in
one-month VIX call options, so a month-on-month change of its level is the strategy's total
return; there is no adjusted close to prefer over it.

Month end is the last trading day's close in the calendar month. The month in progress is
dropped, as ``feeds/yahoo.py`` drops its last bar: a partial month is not a monthly return.
Everything is in USD.

Standard library only (``urllib``), like the rest of ``feeds/``.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from datetime import datetime, timezone

from feeds.yahoo import HEADERS, TIMEOUT_SECONDS, FeedError, MonthlySeries

BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices/"


def _download(code: str) -> str:
    request = urllib.request.Request(f"{BASE}{code}_History.csv", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise FeedError(f"{code}: HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 - urllib raises a wide family here
        raise FeedError(f"{code}: {type(exc).__name__}: {exc}") from exc


def parse_daily(code: str, text: str) -> dict[str, float]:
    """``{"YYYY-MM-DD": close}`` from a Cboe daily history file.

    Two layouts exist: ``DATE,<CODE>`` for a strategy index (one level per day) and
    ``DATE,OPEN,HIGH,LOW,CLOSE`` for a volatility index. Either is read; anything else is
    refused rather than guessed at.
    """
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().upper() for h in next(reader, [])]
    if not header or header[0] != "DATE":
        raise FeedError(f"{code}: not a Cboe daily history file (header {header[:5]})")
    if code.upper() in header:
        column = header.index(code.upper())
    elif "CLOSE" in header:
        column = header.index("CLOSE")
    else:
        raise FeedError(f"{code}: no {code} or CLOSE column in {header}")
    out: dict[str, float] = {}
    for row in reader:
        if len(row) <= column or not row[0].strip():
            continue
        try:
            day = datetime.strptime(row[0].strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
            value = float(row[column])
        except ValueError:
            continue
        if value > 0:
            out[day] = value
    return out


def monthly(code: str, daily: dict[str, float], *, today: str | None = None) -> MonthlySeries:
    """Month-end levels and simple monthly returns from daily closes."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    levels: dict[str, float] = {}
    for day in sorted(daily):
        levels[day[:7]] = daily[day]          # the last trading day of the month wins
    months = sorted(levels)
    if months and months[-1] >= today[:7]:
        months = months[:-1]                  # the month in progress is incomplete
    if len(months) < 13:
        raise FeedError(f"{code}: only {len(months)} complete months, too short to be useful")
    returns = {
        current: levels[current] / levels[previous] - 1.0
        for previous, current in zip(months, months[1:])
    }
    return MonthlySeries(
        symbol=code,
        currency="USD",
        first_period=months[1],
        last_period=months[-1],
        returns=returns,
        levels={m: levels[m] for m in months},
        fetched_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )


def fetch(code: str) -> MonthlySeries:
    """Fetch one Cboe index's daily history and reduce it to monthly total returns."""
    return monthly(code, parse_daily(code, _download(code)))
