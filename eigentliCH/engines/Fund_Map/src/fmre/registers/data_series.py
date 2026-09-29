"""Data series register (spec 3.3).

One row per pullable series. In v0.1.0 the register is built in-memory from the
Fund Map seed rather than pulled from Notion, so every seed ticker resolves to
a DataSeries entry with sensible defaults (monthly, level, PX, LCY).

Duplicate tickers (proxies: MXWO Index on rows 16, 45, 47; SWIIT Index on rows
39, 48; VXTH Index on rows 37, 49; MXEU Index on rows 3, 46) collapse into a
single DataSeries row keyed by ticker. Building blocks record which ticker
they resolve to; the DataSeries register does not know which blocks depend on
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from fmre.registers.building_blocks import BuildingBlock


class Period(str, Enum):
    MONTHLY = "M"
    QUARTERLY = "Q"
    ANNUAL = "A"


class Currency(str, Enum):
    LCY = "LCY"  # native local currency of the series
    USD = "USD"
    NA = "NA"
    NONE = "--"


class Magnitude(str, Enum):
    TN = "Tn"
    BN = "Bn"
    HUNDRED_MN = "100 Mn"
    MN = "Mn"
    TH = "th"
    CRORE = "Crore"
    LEVEL = "Lvl"
    PCT = "Pct"
    BSE = "Bse"


class Unit(str, Enum):
    PX = "PX"        # price series; take returns
    PCT = "%"        # already a rate; use as-is
    DELTA = "+/-"    # already a differential
    RATIO = ":"      # already a ratio
    COUNT = "#"      # count series


class Status(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DataSeries:
    ticker: str
    pull_code: str
    period: Period
    crncy: Currency
    magnitude: Magnitude
    unit: Unit
    status: Status
    date_frame: str | None = None


def build_default_register(blocks: list[BuildingBlock]) -> dict[str, DataSeries]:
    """Build a minimal DataSeries register from the seed tickers.

    Every unique ticker becomes one DataSeries entry with monthly / level /
    PX / LCY defaults. The pull_code equals the ticker (Bloomberg convention:
    the field is PX_LAST or TOT_RETURN_INDEX; we default to PX_LAST here).
    """
    reg: dict[str, DataSeries] = {}
    for b in blocks:
        if b.ticker in reg:
            continue
        reg[b.ticker] = DataSeries(
            ticker=b.ticker,
            pull_code=b.ticker,
            period=Period.MONTHLY,
            crncy=Currency.LCY,
            magnitude=Magnitude.LEVEL,
            unit=Unit.PX,
            status=Status.COMPLETE,
            date_frame=None,
        )
    return reg
