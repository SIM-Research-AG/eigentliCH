"""What each public symbol actually is.

Without this the feed described fifty-one series as "Adjusted close, month on month.
Quoted in USD." That sentence says how the number was computed and nothing about what was
measured, which makes the catalogue useless for the one question a reader brings to it:
*what is this series?* `yahoo.IGF` is global listed infrastructure equity, and no amount of
knowing it is an adjusted close will tell you that.

So every symbol carries a name, a description, the country or region it measures and the
index family behind it. It is hand-written because there is no free machine-readable
source for it that is worth trusting, and it lives here rather than in the catalogue
because **SQL is the source of truth** and the catalogue is generated from it.

The descriptions state the exposure, not the marketing. Where a fund is an imperfect stand
in for what the register wants, that belongs in `proxy_map.py` as a grade; here the job is
only to say what the thing is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Security:
    """One public symbol, described."""

    name: str
    description: str
    country: str = "WLD"        # ISO 3166-1 alpha-2, or WLD for a world aggregate
    index_family: str = ""


_S = Security

#: Keyed by the public symbol (Yahoo, or Cboe for `proxy_map.CBOE_SYMBOLS`). Every symbol
#: the feed fetches must appear here; a test fails the build if one does not, because the
#: alternative is a series nobody can identify.
SECURITIES: dict[str, Security] = {
    # --- global and regional equity ------------------------------------------
    "VT": _S("Vanguard Total World Stock ETF",
             "All-cap global equity, developed and emerging, about 9,000 holdings.",
             "WLD", "FTSE"),
    "ACWI": _S("iShares MSCI ACWI ETF",
               "Large and mid-cap equity across 23 developed and 24 emerging markets.",
               "WLD", "MSCI"),
    "URTH": _S("iShares MSCI World ETF",
               "Large and mid-cap equity across developed markets only, no emerging.",
               "WLD", "MSCI"),
    "ACWV": _S("iShares MSCI Global Min Vol Factor ETF",
               "Global equity weighted to minimise total portfolio volatility. A "
               "deliberately defensive equity basket rather than a market-cap one.",
               "WLD", "MSCI"),
    "SPY": _S("SPDR S&P 500 ETF Trust",
              "US large-cap equity. The oldest and most liquid equity ETF.",
              "US", "S&P"),
    "EFA": _S("iShares MSCI EAFE ETF",
              "Developed-market equity outside the US and Canada: Europe, Australasia "
              "and the Far East.", "WLD", "MSCI"),
    "EEM": _S("iShares MSCI Emerging Markets ETF",
              "Large and mid-cap equity across emerging markets.", "WLD", "MSCI"),
    "IEV": _S("iShares Europe ETF",
              "European large-cap equity across 16 developed markets.", "EU", "S&P"),
    "VGK": _S("Vanguard FTSE Europe ETF",
              "European equity, all-cap, including the UK and Switzerland.", "EU", "FTSE"),
    "EZU": _S("iShares MSCI Eurozone ETF",
              "Equity of the euro-currency members only. Excludes the UK, Switzerland "
              "and Scandinavia outside the euro.", "EU", "MSCI"),
    "EWU": _S("iShares MSCI United Kingdom ETF",
              "UK large and mid-cap equity. Revenue is largely earned outside the UK, "
              "so it tracks sterling and the global cycle more than the domestic "
              "economy.", "GB", "MSCI"),
    "EWL": _S("iShares MSCI Switzerland ETF",
              "Swiss large and mid-cap equity, heavily concentrated in three names.",
              "CH", "MSCI"),
    "EWJ": _S("iShares MSCI Japan ETF", "Japanese large and mid-cap equity.",
              "JP", "MSCI"),
    "EWA": _S("iShares MSCI Australia ETF",
              "Australian large and mid-cap equity, resource and bank heavy.",
              "AU", "MSCI"),
    "VPL": _S("Vanguard FTSE Pacific ETF",
              "Developed Asia-Pacific equity: Japan, Australia, Korea, Hong Kong, "
              "Singapore, New Zealand.", "WLD", "FTSE"),
    "AAXJ": _S("iShares MSCI All Country Asia ex Japan ETF",
               "Asian equity, developed and emerging, excluding Japan.", "WLD", "MSCI"),
    "ASEA": _S("Global X FTSE Southeast Asia ETF",
               "Equity of Singapore, Malaysia, Indonesia, Thailand and the Philippines.",
               "WLD", "FTSE"),
    "EWH": _S("iShares MSCI Hong Kong ETF",
              "Hong Kong equity. Property and financials dominated.", "HK", "MSCI"),

    # --- China and India ------------------------------------------------------
    "MCHI": _S("iShares MSCI China ETF",
               "Broad China equity across all share classes available to foreigners.",
               "CN", "MSCI"),
    "FXI": _S("iShares China Large-Cap ETF",
              "The fifty largest Chinese companies listed in Hong Kong. Narrow and "
              "financials heavy.", "CN", "FTSE"),
    "GXC": _S("SPDR S&P China ETF",
              "Broad Chinese equity across offshore-investable share classes.",
              "CN", "S&P"),
    "ASHR": _S("Xtrackers Harvest CSI 300 China A-Shares ETF",
               "Mainland-listed A-shares, the domestic market rather than the offshore "
               "one. A different exposure from MCHI or FXI.", "CN", "CSI"),
    "INDA": _S("iShares MSCI India ETF", "Indian large and mid-cap equity.",
               "IN", "MSCI"),
    "EPI": _S("WisdomTree India Earnings Fund",
              "Indian equity weighted by earnings rather than market capitalisation.",
              "IN"),
    "IFN": _S("abrdn India Fund",
              "Closed-end Indian equity fund. Its value is the reason it is here: it "
              "reaches back to 1994, far earlier than any Indian ETF, so it anchors the "
              "long end of the India chain. Being closed-end, it trades at a varying "
              "premium or discount to net asset value.", "IN"),

    # --- government and corporate bonds ---------------------------------------
    "GOVT": _S("iShares U.S. Treasury Bond ETF",
               "US Treasuries across the whole curve, one to thirty years.",
               "US", "Bloomberg"),
    "IEF": _S("iShares 7-10 Year Treasury Bond ETF",
              "Intermediate US Treasuries. The classic duration hedge.",
              "US", "Bloomberg"),
    "TLT": _S("iShares 20+ Year Treasury Bond ETF",
              "Long US Treasuries. The most rate-sensitive government exposure here.",
              "US", "Bloomberg"),
    "AGG": _S("iShares Core U.S. Aggregate Bond ETF",
              "US investment-grade bonds: Treasuries, agency, corporate and "
              "mortgage-backed.", "US", "Bloomberg"),
    "BNDX": _S("Vanguard Total International Bond ETF",
               "Investment-grade bonds outside the US, hedged to the US dollar, so it "
               "measures foreign rates without foreign currency.", "WLD", "Bloomberg"),
    "BWX": _S("SPDR Bloomberg International Treasury Bond ETF",
              "Government bonds outside the US, unhedged, so it carries currency as "
              "well as rate risk.", "WLD", "Bloomberg"),
    "HYG": _S("iShares iBoxx $ High Yield Corporate Bond ETF",
              "US sub-investment-grade corporate credit.", "US"),
    "JNK": _S("SPDR Bloomberg High Yield Bond ETF",
              "US high-yield corporate credit; a second vintage alongside HYG.",
              "US", "Bloomberg"),
    "BKLN": _S("Invesco Senior Loan ETF",
               "Floating-rate senior secured bank loans. Credit risk with little "
               "duration.", "US"),
    "EMB": _S("iShares J.P. Morgan USD Emerging Markets Bond ETF",
              "Emerging-market sovereign and quasi-sovereign debt issued in US dollars, "
              "so it carries credit risk but not local currency risk.",
              "WLD", "JPMorgan"),
    "EMLC": _S("VanEck J.P. Morgan EM Local Currency Bond ETF",
               "Emerging-market government debt in local currency. Unlike EMB it carries "
               "the currency risk, which is most of its behaviour.", "WLD", "JPMorgan"),
    "BIL": _S("SPDR Bloomberg 1-3 Month T-Bill ETF",
              "US Treasury bills. The cash leg, and the closest thing here to a "
              "risk-free rate.", "US", "Bloomberg"),

    # --- real assets ----------------------------------------------------------
    "GLD": _S("SPDR Gold Shares",
              "Spot gold bullion held in allocated form.", "WLD"),
    "DBC": _S("Invesco DB Commodity Index Tracking Fund",
              "Broad commodity futures across energy, metals and agriculture.", "WLD"),
    "GSG": _S("iShares S&P GSCI Commodity-Indexed Trust",
              "Broad commodity futures, production weighted and therefore heavily "
              "energy weighted.", "WLD", "S&P GSCI"),
    "XME": _S("SPDR S&P Metals & Mining ETF",
              "US-listed metals and mining equities. Equity of the producers, not the "
              "metal, so it carries equity beta as well as commodity exposure.",
              "US", "S&P"),
    "IYR": _S("iShares U.S. Real Estate ETF",
              "US listed real estate investment trusts.", "US", "Dow Jones"),
    "VNQ": _S("Vanguard Real Estate ETF",
              "US listed real estate; a second vintage alongside IYR.", "US"),
    "IGF": _S("iShares Global Infrastructure ETF",
              "Listed equity of infrastructure operators worldwide: utilities, "
              "transport and energy infrastructure. Equity of the asset owners rather "
              "than the assets themselves.", "WLD", "S&P"),

    # --- alternatives and hedges ----------------------------------------------
    "PSP": _S("Invesco Global Listed Private Equity ETF",
              "Listed private-equity firms and vehicles. A liquid, listed and therefore "
              "imperfect window onto private equity.", "WLD"),
    "QAI": _S("NYLI Hedge Multi-Strategy Tracker ETF",
              "Attempts to replicate broad hedge-fund index returns with liquid "
              "instruments.", "WLD"),
    "WTMF": _S("WisdomTree Managed Futures Strategy Fund",
               "Rules-based managed futures across commodities, currencies and rates. "
               "The trend-following proxy.", "WLD"),
    "BTAL": _S("AGF U.S. Market Neutral Anti-Beta Fund",
               "Long low-beta and short high-beta US equities. Designed to rise when "
               "the equity market falls.", "US"),
    "SH": _S("ProShares Short S&P500",
             "Inverse daily exposure to the S&P 500. Daily reset means it does not track "
             "the inverse over long horizons.", "US", "S&P"),
    "VIXY": _S("ProShares VIX Short-Term Futures ETF",
               "Short-dated VIX futures. Structurally loses value in calm markets and "
               "spikes in crises, which is the point of holding it.", "US"),
    "VXTH": _S("Cboe VIX Tail Hedge Index",
               "A hypothetical portfolio of the S&P 500 with dividends reinvested plus "
               "one-month VIX call options, bought monthly and sized by the level of the "
               "VIX. An equity holding with a tail hedge: it gives up a little in calm "
               "markets and gains when volatility spikes. Published by Cboe from 2006.",
               "US", "Cboe"),
    "BTC-USD": _S("Bitcoin / US dollar",
                  "Bitcoin spot price against the US dollar. Not a fund; the asset "
                  "itself, traded continuously.", "WLD"),
}


def describe(symbol: str) -> Security | None:
    """What this symbol is, or None if it is not catalogued."""
    return SECURITIES.get(symbol)


def missing(symbols) -> list[str]:
    """Symbols the feed wants that nobody has described."""
    return sorted(s for s in symbols if s not in SECURITIES)
