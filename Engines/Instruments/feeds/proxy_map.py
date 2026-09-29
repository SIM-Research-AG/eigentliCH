"""Which public series stands in for which registered instrument, and how well.

The register names 54 instruments by Bloomberg ticker. Bloomberg is not available here, so
a public proxy is used instead -- and a proxy is **not** the instrument. The difference
shows up as tracking error, fee drag, a different index construction, and in every case a
different currency: the proxies are US-listed and quoted in USD, while the register prices
these instruments in CHF, EUR, GBP, JPY and five others.

So every mapping carries a **grade**, and the grade travels with the data all the way to
the profile. An ungraded proxy would let a weak stand-in be read as a measurement, which
is the same failure the method labels exist to prevent everywhere else in this engine.

    close   a well-known tracker of the same index, or the same underlying
    proxy   the same asset class and region, built differently
    weak    related, but materially different exposure
    none    no defensible public proxy; the instrument keeps no history

Every proxy is fetched from Yahoo Finance (``feeds/yahoo.py``) except the few listed in
:data:`CBOE_SYMBOLS`, which are Cboe's own index histories (``feeds/cboe.py``). The feed
series id and the source label follow the source: ``yahoo.SPY`` / ``yahoo:SPY:proxy``,
``cboe.VXTH`` / ``cboe:VXTH:close``.

**`none` is a real answer and is used freely.** Swiss real estate funds, Asian hedge-fund
sub-strategy indices and CHF money-market rates have no honest US-listed equivalent, and
inventing one would be worse than leaving the instrument seeded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proxy:
    """One instrument's public stand-in."""

    symbol: str | None
    grade: str
    note: str

    @property
    def usable(self) -> bool:
        return bool(self.symbol) and self.grade != "none"

    @property
    def source(self) -> str:
        return source_of(self.symbol or "")


#: Symbols read from Cboe's public index histories rather than from Yahoo, which does not
#: carry them (``^VXTH`` comes back as a single bar).
CBOE_SYMBOLS: frozenset[str] = frozenset({"VXTH"})


def source_of(symbol: str) -> str:
    """Which public feed a proxy symbol comes from: ``cboe`` or ``yahoo``."""
    return "cboe" if symbol in CBOE_SYMBOLS else "yahoo"


def feed_series_id(symbol: str) -> str:
    """The proxy's series id in the feed schema, e.g. ``yahoo.GLD`` or ``cboe.VXTH``."""
    return f"{source_of(symbol)}.{symbol}"


def _n(note: str) -> Proxy:
    return Proxy(None, "none", note)


#: Keyed by the register's instrument name.
PROXIES: dict[str, Proxy] = {
    # --- equities ----------------------------------------------------------
    "Fixed Holding": Proxy("URTH", "close",
        "MSCI World. The register's MXWO0FD is a zero-fee share class of the same index."),
    "CH Equities": Proxy("EWL", "close", "iShares MSCI Switzerland."),
    "EU Equities": Proxy("IEV", "proxy",
        "S&P Europe 350 against the register's MSCI Europe -- similar universe, different "
        "construction and weighting."),
    "UK Equities": Proxy("EWU", "close", "iShares MSCI United Kingdom."),
    "US Equities": Proxy("SPY", "proxy",
        "S&P 500 against MSCI USA. Large-cap overlap is high; MSCI USA reaches further "
        "down the cap scale."),
    "Japan Equities": Proxy("EWJ", "close", "iShares MSCI Japan."),
    "China Equities": Proxy("MCHI", "close", "iShares MSCI China."),
    "AU NZ Equities": Proxy("EWA", "proxy",
        "MSCI Australia only -- the register's block includes New Zealand."),
    "EM Equities": Proxy("EEM", "close", "iShares MSCI Emerging Markets."),
    "Private Equity": Proxy("PSP", "proxy",
        "Listed private equity against the LPX50 total-return index. Listed vehicles are "
        "marked daily; the index is not, so measured volatility is higher here."),
    "China A Shares": Proxy("ASHR", "proxy",
        "CSI 300 against the Shanghai A-share index."),
    "India Equities": Proxy("INDA", "close", "iShares MSCI India."),
    "ASEAN Equities": Proxy("ASEA", "proxy",
        "FTSE ASEAN 40 against MSCI South-East Asia."),
    "Asia ex Japan TR": Proxy("AAXJ", "close", "iShares MSCI All Country Asia ex Japan."),
    "MSCI AC World IMI": Proxy("ACWI", "proxy",
        "MSCI ACWI (large and mid cap) against ACWI IMI, which adds small cap."),
    "APAC Equities": Proxy("VPL", "proxy",
        "FTSE Developed Asia Pacific against MSCI AC Asia Pacific -- no emerging markets."),
    "Hang Seng Index": Proxy("EWH", "proxy",
        "MSCI Hong Kong against the Hang Seng. Related, differently constituted."),
    "Swiss Performance Index": Proxy("EWL", "weak",
        "MSCI Switzerland against the SPI. Kept, unlike the other two EWL entries, "
        "because the difference is breadth rather than strategy: the SPI covers about 200 "
        "Swiss names against MSCI Switzerland's large and mid caps, and the two track each "
        "other closely. It is the same series as CH Equities, so expect near-identical "
        "profiles -- that is the honest answer, not a defect."),
    "Fundo World Equity": Proxy("ACWV", "proxy",
        "iShares MSCI Global Minimum Volatility. Re-pointed by CIO decision: the intent is "
        "a conservative global equity basket, where the register had it duplicating "
        "Global Equities on MXWO."),
    "Aktien Europe aktiv": _n(
        "The register gives this the same MXEU ticker as EU Equities, so IEV would make "
        "the two byte-identical -- 313 months, every value equal. What distinguishes this "
        "entry is that it is actively managed, and there is no public proxy for a "
        "manager's skill. Better seeded and visibly unmeasured than measured as a copy of "
        "the passive index it is supposed to beat."),
    "Mining Equities": Proxy("XME", "proxy",
        "SPDR S&P Metals and Mining. Re-pointed by CIO decision from the register's MXWO, "
        "which was MSCI World and not a mining index at all. XME over PICK for length -- "
        "it reaches back to 2006 rather than 2012, covering the financial crisis."),
    "Swiss Dividend Equity": _n(
        "The dividend tilt is the whole instrument, and EWL carries none of it -- it "
        "would only reproduce CH Equities, to the value. No US-listed Swiss dividend "
        "strategy exists, so this is seeded rather than proxied."),
    "Short MSCI US": Proxy("SH", "proxy",
        "Short S&P 500 against short MSCI USA. Daily-reset inverse, so it compounds "
        "differently from a true short over long holding periods."),
    "Structured Products": _n(
        "A bank-issued structured-product index has no public equivalent; payoff depends "
        "on issuer terms."),

    # --- fixed income ------------------------------------------------------
    "Global Bonds": Proxy("BNDX", "proxy",
        "Global aggregate ex-US, currency-hedged to USD, against an unhedged global "
        "aggregate."),
    "Global Governmental Bonds": Proxy("BWX", "proxy",
        "International treasury ex-US against a world government index that includes the "
        "US."),
    "Global High Yields": Proxy("HYG", "proxy",
        "US high yield against a global high-yield index -- no European or EM issuers."),
    "EM Government Bonds LC": Proxy("EMLC", "close",
        "JPMorgan GBI-EM local currency, which is the register's index family."),
    "Private Debt": Proxy("BKLN", "weak",
        "Senior leveraged loans against private debt. Both float, but leveraged loans are "
        "traded and marked; private debt is neither."),
    "US Treasury TR Index": Proxy("GOVT", "close",
        "iShares US Treasury Bond, the whole curve."),
    "Bloomberg Multiverse (H-CHF)": Proxy("BNDX", "weak",
        "Global aggregate hedged to USD, not to CHF. The hedge currency is the whole point "
        "of the register's entry and it is not reproduced."),
    "CHF Corporate Loans IG": _n("No public CHF investment-grade credit series."),
    "EUR  Corporate Loans IG": _n(
        "A EUR IG credit tracker exists on European exchanges but not on this feed."),
    "Asian JACI Bond Index": _n("No public tracker of the JP Morgan Asia Credit Index."),

    # --- real estate -------------------------------------------------------
    "Real Estate direct": _n(
        "Swiss direct real estate, appraisal-valued. No listed equivalent, and a listed "
        "one would have entirely different volatility."),
    "SXI Real Estate": _n("Swiss listed real estate funds; no US-listed tracker."),
    "Infrastructure": Proxy("IGF", "close",
        "iShares Global Infrastructure, which tracks the S&P Global Infrastructure index. "
        "Graded close now that the register's ticker is corrected: SWIIT was the SXI Real "
        "Estate Funds index, so the entry had been pointing at Swiss listed property."),

    # --- alternatives ------------------------------------------------------
    "Commodities": Proxy("GSG", "close", "iShares S&P GSCI, the register's index."),
    "Bloomberg Hedge Fund": Proxy("QAI", "proxy",
        "A liquid hedge-fund-replication ETF against a hedge-fund index. Replication, not "
        "the funds themselves."),
    "Bloomberg Market Neutral HF": Proxy("BTAL", "weak",
        "Anti-beta long/short against an equity market-neutral index. Same intent, very "
        "different construction."),
    "Trend Following": Proxy("WTMF", "proxy",
        "Managed futures. Trend programmes differ widely; this is one implementation."),
    "Digital Assets": Proxy("BTC-USD", "close",
        "Bitcoin spot, which is the register's XBTUSD."),
    "Long Volatility Index": Proxy("VXTH", "close",
        "The Cboe VIX Tail Hedge index itself, the register's own index, from Cboe's "
        "public daily history (31 March 2006 onwards, month-end close). It is a total "
        "return: the S&P 500 with dividends reinvested plus a rolling position in "
        "one-month VIX calls. Replaced VIXY (graded weak) on 29 September 2026: VIXY is "
        "pure short-term VIX futures roll, loses to roll in every state and starts only "
        "in 2011. An index is not investable and carries no fee, so a fund on it would "
        "trail it slightly."),
    "CS Long Vola": Proxy("VIXY", "weak",
        "Short-term VIX futures against the register's VXTH tail-hedge index, which it "
        "shares with Long Volatility Index. Instrument inactive since 29 September 2026 "
        "(owner): Long Volatility Index is kept as the one volatility instrument."),
    "Global Macro": _n("No public tracker of a discretionary global-macro index."),
    "Asia Multi Strategy HF": _n("Eurekahedge sub-strategy index; no public tracker."),
    "Asia Pacific Arbitrage": _n("Eurekahedge sub-strategy index; no public tracker."),
    "Asia Long Short Equities": _n("Eurekahedge sub-strategy index; no public tracker."),
    "Precious Metals": Proxy("GLD", "close", "Gold spot via SPDR Gold Shares."),

    # --- cash --------------------------------------------------------------
    "USD Cash": Proxy("BIL", "close", "1-3 month US Treasury bills."),
    "CHF Cash": _n(
        "CHF money market. No USD-listed equivalent, and converting one would measure the "
        "franc rather than the rate."),
    "EUR Cash": _n("EUR money market; same reasoning as CHF Cash."),

    # --- already carried by the monthly report -----------------------------
    "Global Equities": Proxy("URTH", "close", "MSCI World."),
    "Global Real Estate indirect": Proxy("IYR", "close",
        "iShares US Real Estate, which is the register's own ticker."),
}

GRADES = ("close", "proxy", "weak", "none")


def summary() -> dict[str, int]:
    counts = {g: 0 for g in GRADES}
    for p in PROXIES.values():
        counts[p.grade] = counts.get(p.grade, 0) + 1
    return counts
