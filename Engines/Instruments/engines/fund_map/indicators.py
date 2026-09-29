"""The eight economic indicators, and the market-environment cycle built from them.

A port of ``1_data.mlx`` (indicator construction) and the first half of ``2_market.mlx``
(the cycle). The output is ``ec_cycle``: one standardised reading per year, in units of
standard deviations, negative when conditions are poor.

**Every indicator is de-trended before it is used.** Debt saturation exponentially,
because a debt-to-GDP ratio compounds; the other seven linearly. What the model wants
from each series is the deviation from its own long-run path, not its level -- a
debt ratio that has risen for a century is not evidence that every recent year is a
crisis, and a raw level would say exactly that.

**Four indicators carry a negative sign**, because the cycle is oriented so that higher
is better: debt saturation, unemployment, inflation and volatility are all bad news when
they rise. This is the "four carry negative weight" line in manual section 9, and the
weighting is otherwise uniform -- the cycle is a plain mean across the eight, not a
weighted one. That is worth stating because the manual's word "weighted" invites the
opposite reading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engines.fund_map import numerics as num
from store.etl.long_record import RawSeries

#: The indicator window. Every indicator is a rate of change or a residual defined from
#: the second year of the source data onward, so the common window opens in 1871.
FIRST_YEAR = 1871
LAST_YEAR = 2020

#: Financial-sentiment weights, from ``1_data.mlx``: a tenth bills, a half bonds, the
#: rest equities. It is a proxy for what a representative balanced holder earned.
SENTIMENT_WEIGHTS = {"bill": 0.1, "bond": 0.5, "spx": 0.4}

#: The volatility indicator is a trailing standard deviation of financial sentiment over
#: the current year and the two before it. Backward-looking by construction, so the
#: indicator never sees the future.
VOLATILITY_LOOKBACK = 2

#: Sign applied to each indicator before the cycle is averaged. Higher must mean better.
INDICATOR_SIGNS = {
    "debt": -1.0,
    "earnings": +1.0,
    "monetary": +1.0,
    "sentiment": +1.0,
    "unemployment": -1.0,
    "yield_curve": +1.0,
    "inflation": -1.0,
    "volatility": -1.0,
}

#: The order the reference implementation assembles ``eco_series`` in. Held explicitly
#: because the cycle is a mean and a mean does not care about order -- but the stored
#: indicator table does, and a reader comparing against the MATLAB will.
INDICATOR_ORDER = (
    "debt",
    "earnings",
    "monetary",
    "sentiment",
    "unemployment",
    "yield_curve",
    "inflation",
    "volatility",
)


def _log_diff(values: list[float]) -> list[float]:
    if any(v <= 0.0 for v in values):
        raise ValueError("log differences need strictly positive levels")
    return [math.log(b) - math.log(a) for a, b in zip(values, values[1:])]


@dataclass(frozen=True)
class MarketEnvironment:
    """The annual market-environment reading and everything it was built from."""

    first_year: int
    last_year: int
    #: De-trended, *unsigned* indicator residuals, keyed by name. Signs are applied when
    #: the cycle is formed, so these read the way the underlying series does.
    indicators: dict[str, tuple[float, ...]]
    #: Each indicator after sign and standardisation -- the matrix the cycle averages.
    standardised: dict[str, tuple[float, ...]]
    #: The standardised economic cycle, in sigma. This is ``ec_cycle``.
    cycle: tuple[float, ...]
    #: Raw CPI inflation, retained unstandardised. The return blocks are nominal, and
    #: manual section 11.3 converts to real by subtracting current inflation at the point
    #: of use -- which needs this series, not the de-trended indicator.
    inflation: tuple[float, ...]

    @property
    def years(self) -> list[int]:
        return list(range(self.first_year, self.last_year + 1))


def build_indicators(record: dict[str, RawSeries]) -> MarketEnvironment:
    """Build the eight indicators and the economic cycle from the long record."""
    first, last = FIRST_YEAR, LAST_YEAR
    n = last - first + 1

    # 1. Debt saturation: (government debt + bank loans) / GDP, de-trended exponentially.
    gov = record["gov_debt"].window(first, last)
    loans = record["loans"].window(first, last)
    gdp = record["gdp"].window(first, last)
    debt_ratio = [(g + l) / y for g, l, y in zip(gov, loans, gdp)]
    debt = num.expfit1_residuals(debt_ratio)

    # 2. Yield curve: the 10-year less the 1-year, de-trended linearly.
    long_rate = record["lrate"].window(first, last)
    short_rate = record["srate"].window(first, last)
    yield_curve = num.polyfit1_residuals([l - s for l, s in zip(long_rate, short_rate)])

    # 3. Monetary composition: broad money growth less narrow money growth.
    broad = _log_diff(record["broad"].window(first - 1, last))
    narrow = _log_diff(record["narrow"].window(first - 1, last))
    monetary = num.polyfit1_residuals([b - nr for b, nr in zip(broad, narrow)])

    # 4. Financial sentiment: a weighted blend of what bills, bonds and equities paid.
    bill = record["bill"].window(first, last)
    bond = record["bond"].window(first, last)
    spx = _log_diff(record["spx"].window(first - 1, last))
    blended = [
        SENTIMENT_WEIGHTS["bill"] * b
        + SENTIMENT_WEIGHTS["bond"] * o
        + SENTIMENT_WEIGHTS["spx"] * e
        for b, o, e in zip(bill, bond, spx)
    ]
    sentiment = num.polyfit1_residuals(blended)

    # 5. Wage earnings growth.
    earnings = num.polyfit1_residuals(_log_diff(record["erng"].window(first - 1, last)))

    # 6. Unemployment rate.
    unemployment = num.polyfit1_residuals(record["ump"].window(first, last))

    # 7. Inflation. The raw rate is kept for the nominal-to-real conversion downstream.
    raw_inflation = record["cpi"].window(first, last)
    inflation = num.polyfit1_residuals(raw_inflation)

    # 8. Volatility: a trailing standard deviation of *de-trended* financial sentiment.
    #    Computed from the residual rather than the raw blend, as in the reference.
    volatility = num.polyfit1_residuals(
        num.movstd_trailing(sentiment, VOLATILITY_LOOKBACK)
    )

    indicators = {
        "debt": debt,
        "earnings": earnings,
        "monetary": monetary,
        "sentiment": sentiment,
        "unemployment": unemployment,
        "yield_curve": yield_curve,
        "inflation": inflation,
        "volatility": volatility,
    }
    for name, series in indicators.items():
        if len(series) != n:
            raise ValueError(
                f"indicator {name!r} came out {len(series)} long, expected {n}. "
                f"The source windows have drifted out of alignment."
            )

    # The cycle: sign each indicator so that higher is better, standardise each to put
    # them on a common scale, take the plain mean across the eight, then standardise the
    # result so the phase bounds can be stated in sigma.
    standardised = {
        name: tuple(num.standardise([INDICATOR_SIGNS[name] * v for v in indicators[name]]))
        for name in INDICATOR_ORDER
    }
    rows = [[standardised[name][i] for name in INDICATOR_ORDER] for i in range(n)]
    cycle = num.standardise([num.mean(row) for row in rows])

    return MarketEnvironment(
        first_year=first,
        last_year=last,
        indicators={k: tuple(v) for k, v in indicators.items()},
        standardised=standardised,
        cycle=tuple(cycle),
        inflation=tuple(raw_inflation),
    )
