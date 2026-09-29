"""The data need: every series ``mrs`` reads, named as ``datafeed`` names series.

Two sets, because two views of the input exist:

* ``SERIES`` (``REQUIRED_SERIES``): the 29 columns of ``M_TS`` that ``Market_Signal.m`` reads,
  plus the high-yield yield to worst it should have read. All are in datafeed's raw snapshot
  (``matlab-m_ts-2026-01-05.r3``), so the ``matlab`` mode and the golden test see exactly
  what MATLAB saw. ``matlab`` is the ``M_TS`` sheet and 1-based column, the same
  row-position contract as the datafeed registry.
* ``PUBLIC_SERIES``: replacements with no ``M_TS`` column, served only by datafeed's market
  layer (DF-18, the snapshot ``...r3.public-21886dde.market-690ff362``). ``REPLACEMENTS``
  says which production input takes the place of which MATLAB column, and why.

Units in the raw snapshot are as MATLAB stored them after the ticker sheets' scale factor:
rates, yields and ratios are decimals (the VIX reads 0.16, not 16). Seven economies'
implied volatility broke that (BD, ID, MY, PH, TH, VN in percent, JP a hundred times too
small); the market layer corrects them, the raw snapshot keeps them as MATLAB read them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeriesNeed:
    series_id: str
    category: str
    unit: str
    description: str
    matlab: tuple[str, int]
    #: An interior 0.0 is a plausible print (rates, growth rates, flows).
    zero_is_a_value: bool = False
    #: In the datafeed registry (all since 27.09.2026).
    in_datafeed: bool = True


SERIES: tuple[SeriesNeed, ...] = (
    SeriesNeed("commodity.gold", "commodity", "price", "Gold per ounce, London PM fix (USD)", ("Commodity", 1)),
    SeriesNeed("consumer.unemployment", "consumer", "ratio", "Unemployment rate", ("Consumer", 4)),
    SeriesNeed("consumer.wage_growth", "consumer", "ratio", "Wage growth", ("Consumer", 5), True, True),
    SeriesNeed("consumer.household_consumption", "consumer", "level", "Household consumption expenditure", ("Consumer", 7), False, True),
    SeriesNeed("debt.senior_loan_etf", "debt", "price", "Senior loan ETF", ("Debt", 6)),
    SeriesNeed("debt.npl_ratio", "debt", "ratio", "Non-performing loans", ("Debt", 7)),
    SeriesNeed("equity.capital_stock_decrease", "equity", "level", "Decrease in capital stock (buybacks), index aggregate", ("Equity", 3), True),
    SeriesNeed("equity.dividend_yield", "equity", "ratio", "Net aggregate dividend yield", ("Equity", 4)),
    SeriesNeed("equity.pe_long_term", "equity", "ratio", "Long-term price/earnings ratio", ("Equity", 5)),
    SeriesNeed("equity.price_to_sales", "equity", "ratio", "Price to sales", ("Equity", 6)),
    SeriesNeed("equity.profit_margin", "equity", "ratio", "Profit margin", ("Equity", 7), True),
    SeriesNeed("equity.debt_to_assets", "equity", "ratio", "Total debt to total assets", ("Equity", 8)),
    SeriesNeed("equity.total_return", "equity", "index_level", "Equity index, total return", ("Equity", 9)),
    SeriesNeed("equity.banks_total_return", "equity", "index_level", "Bank equity index, total return", ("Equity", 10)),
    SeriesNeed("fx.beer", "fx", "index_level", "JP Morgan BEER (behavioural equilibrium exchange rate)", ("FX", 6)),
    SeriesNeed("fx.ois_1y", "fx", "rate", "1-year overnight index swap", ("FX", 8), True),
    SeriesNeed("fx.dxy", "fx", "index_level", "USD against the world (DXY)", ("FX", 9)),
    SeriesNeed("inflation.cpi_yoy", "inflation", "ratio", "CPI, year on year", ("Inflation", 1), True, True),
    SeriesNeed("inflation.ppi_yoy", "inflation", "ratio", "PPI, year on year", ("Inflation", 2), True),
    SeriesNeed("money.broad_money", "money", "level", "Broad money (M3), nominal", ("Money", 2), False, True),
    SeriesNeed("money.m1_yoy", "money", "ratio", "M1 growth, year on year", ("Money", 4), True),
    SeriesNeed("production.gdp_nominal", "production", "level", "GDP, nominal", ("Production", 1), False, True),
    SeriesNeed("production.manufacturing_confidence", "production", "index_level", "Manufacturing confidence (OECD)", ("Production", 5)),
    SeriesNeed("volatility.implied", "volatility", "ratio", "Implied equity volatility index (VIX or local)", ("Volatility", 1)),
    SeriesNeed("volatility.fear_barometer", "volatility", "index_level", "Fear barometer (CSFB)", ("Volatility", 2)),
    SeriesNeed("yields.govt_10y", "yields", "ratio", "Government bond yield, 10 years", ("Yields", 1), True, True),
    SeriesNeed("yields.govt_2y", "yields", "ratio", "Government bond yield, 2 years", ("Yields", 2), True),
    SeriesNeed("yields.high_yield_index", "yields", "index_level", "High-yield bond index, total return", ("Yields", 4)),
    SeriesNeed("yields.high_yield_ytw", "yields", "ratio", "High-yield bond index, yield to worst", ("Yields", 8)),
)


@dataclass(frozen=True)
class PublicNeed:
    """A replacement served only by datafeed's market layer (no ``M_TS`` column)."""

    series_id: str
    category: str
    unit: str
    description: str
    source: str


PUBLIC_SERIES: tuple[PublicNeed, ...] = (
    PublicNeed("volatility.skew", "volatility", "index",
               "Cboe SKEW index, month-end close (price of S&P 500 tail-risk protection); one global series",
               "cboe:SKEW"),
    PublicNeed("fx.neer_broad", "fx", "index",
               "BIS nominal effective exchange rate, broad basket, monthly (not BD, VN)", "bis:M.N.B.{area}"),
)


@dataclass(frozen=True)
class Replacement:
    """Which production input takes the place of which MATLAB input (the ``matlab`` mode
    keeps the MATLAB one, so the golden test still reproduces what MATLAB computed)."""

    matlab_series: str
    production_series: str
    used_in: str
    reason: str


REPLACEMENTS: tuple[Replacement, ...] = (
    Replacement("volatility.fear_barometer", "volatility.skew", "MR_Fear_Greed.m",
                "The Credit Suisse Fear Barometer (CSFB Index) is discontinued and empty for every economy; "
                "Cboe SKEW measures the same thing (demand for tail-risk protection, higher is more fear)."),
    Replacement("fx.beer", "fx.neer_broad", "MR_Inflation.m (leading third)",
                "The JP Morgan series (JBDN... Index) holds no data for any economy; the BIS broad nominal "
                "effective exchange rate is the public equivalent. BD and VN have none."),
    Replacement("yields.high_yield_index", "yields.high_yield_ytw", "MR_Bond.m (HY spread)",
                "MR_Bond.m subtracts the 10y yield from a total-return index level (about 2,000); the spread "
                "needs the index's yield to worst. Data for US, EU and CN only."),
)

REQUIRED_SERIES: tuple[str, ...] = tuple(s.series_id for s in SERIES)
PUBLIC_SERIES_IDS: tuple[str, ...] = tuple(s.series_id for s in PUBLIC_SERIES)
BY_ID: dict[str, SeriesNeed] = {s.series_id: s for s in SERIES}
