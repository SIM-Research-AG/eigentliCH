"""The instrument register, imported from the prototype's published universe.

The prototype carried 54 instruments with real classification metadata -- ticker, region,
capital type, liquidity, currency -- and **no estimation at all**: every one came back
``coverage: seed`` with an identical ``n_obs_total`` of 176, which is not a per-instrument
observation count but the same placeholder repeated 54 times. So what is worth importing
is the register, not the profiles.

That distinction is the point of this module. A complete universe matters -- manual
section 11.4 makes the register a versioned input, and the Portfolio Optimiser's objective
has a floor that scales with its size -- but importing 44 seeded profiles alongside it
would dress up an absence of data as an estimate.

**Where the roles disagree, the manual wins and the override is recorded.** The prototype
predates section 11.4's role derivation, so a handful of its assignments contradict it.
Those are listed in :data:`ROLE_OVERRIDES` with the manual's reasoning attached, rather
than silently corrected on import.

**An instrument leaves the universe by deactivation, never by deletion** (:data:`DEACTIVATED`,
with the reason and the date). It stays in the register with its history and its profile,
and drops out of everything published: the ReturnSet, the instrument listing, the
estimators' peer sets.

Register decisions (role overrides, deactivations, corrections, country exposure) are
re-applied by every bootstrap, so a decision taken today reaches a store built earlier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The prototype's published 54-instrument universe.
DEFAULT_UNIVERSE_JSON = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Projects\andersCH-prototype_old"
    r"\andersCH-prototype_old\legacy\pre-universe-cut\rs.json"
)

#: Roles the manual assigns differently from the prototype. Section 11.4 derives the role
#: from the measured phase profile, which the prototype could not do because it never
#: estimated one.
ROLE_OVERRIDES: dict[str, tuple[str, str]] = {
    "Global Governmental Bonds": (
        "protection",
        "Section 11.4: government bonds are Protection, not Income -- the coupon is not "
        "what defines the block, the flight-to-safety jump is.",
    ),
    "US Treasury TR Index": (
        "protection",
        "Same reasoning as Global Governmental Bonds.",
    ),
    "Bloomberg Multiverse (H-CHF)": (
        "protection",
        "A government-heavy aggregate; Protection by the same rule.",
    ),
    "Global Real Estate indirect": (
        "income",
        "Section 11.4: real estate is Income on the let share, and emphatically not "
        "Stabilisation -- it collapses in precisely the state a stabiliser exists for.",
    ),
    "Real Estate direct": ("income", "Same reasoning as Global Real Estate indirect."),
    "SXI Real Estate": ("income", "Same reasoning as Global Real Estate indirect."),
    "Commodities": (
        "stabilisation",
        "Section 11.4: commodities peak in contraction -- they pay before the damage, "
        "not during it.",
    ),
    "Digital Assets": (
        "gain",
        "CIO decision, 27 September 2026. Registered as Stabilisation, which the measured "
        "behaviour contradicts outright: equity beta 1.67 and -68.9 % in crisis months. "
        "A stabiliser pays before the damage; this amplifies it.",
    ),
    # Role review after R-001 (owner, 29 September 2026). The evidence is the nearest-curve
    # reading of FMRE-13: the correlation across the 25 states of the instrument's 12 month
    # forward profile (source currency) with the four role curves of CAL-69d9d1ee5245ac71,
    # the calibration with Income A.
    "Global Bonds": (
        "income",
        "Owner decision, 29 September 2026, in two steps. First the role review after R-001 "
        "moved it to Stabilisation: its 12 month forward profile (BNDX, source currency) "
        "correlates with the role curves under Income A at Stabilisation 0.75, Income 0.68, "
        "Gain 0.52, Protection -0.56. Then the owner moved it back to Income, its registered "
        "role, because only stagnation and expansion are measured (the other three phases "
        "are filled from the role shape), so the evidence for the move is too thin.",
    ),
    "Bloomberg Market Neutral HF": (
        "stabilisation",
        "Owner decision, 29 September 2026 (role review after R-001): Stabilisation, which "
        "is also its registered role. Its 12 month forward profile (BTAL, source currency) "
        "correlates with the role curves under Income A at Stabilisation 0.78, Income "
        "0.63, Gain 0.39, Protection -0.98: nearest to Stabilisation. Under the earlier "
        "real-estate-only Income it read nearest to Income (0.88).",
    ),
}

#: Instruments taken out of the universe, with the reason. Deactivated, never deleted:
#: the row, its history and its profile stay, ``active`` is 0, and nothing published
#: carries it. Re-applied by every bootstrap.
DEACTIVATED: dict[str, str] = {
    "Short MSCI US": (
        "A short index is not a hold-through-crisis instrument (owner, 29.09.2026). It "
        "pays while the market falls and loses in the rebound year that follows."
    ),
    "CS Long Vola": (
        "Long Volatility Index is kept as the one volatility instrument (owner, "
        "29.09.2026). The two share the register's VXTH ticker, so keeping both counted "
        "the same exposure twice."
    ),
}

#: Entries whose Bloomberg ticker is wrong or a placeholder, with what they were meant to
#: be. Section 11.4 makes the register a versioned input, so a correction is a dated data
#: decision rather than a silent edit -- and the original is kept so the change is legible.
TICKER_CORRECTIONS: dict[str, tuple[str, str]] = {
    "Mining Equities": (
        "MXWO Index",
        "CIO decision, 27 September 2026. The register pointed this at MSCI World, which "
        "is not a mining index -- a placeholder nobody filled in. Re-pointed at a real "
        "metals-and-mining index.",
    ),
    "Fundo World Equity": (
        "MXWO Index",
        "CIO decision, 27 September 2026. Shared MSCI World with Global Equities, making "
        "it a duplicate. Its intent is a conservative global equity basket, so it is "
        "re-pointed at a global minimum-volatility index.",
    ),
    "Infrastructure": (
        "SWIIT Index",
        "CIO decision, 27 September 2026. SWIIT is the SXI Real Estate Funds index, which "
        "the register also gives to SXI Real Estate -- so this entry pointed at Swiss "
        "listed property, not infrastructure. SXI Real Estate keeps the ticker; this one "
        "is re-pointed at global listed infrastructure, which is what its name says.",
    ),
}

#: The ticker a correction puts in place of the register's. Only for entries where the
#: register names the wrong instrument outright, rather than merely a rough one: leaving
#: both Infrastructure and SXI Real Estate on SWIIT would keep the collision in the data
#: while claiming in prose to have resolved it.
TICKER_REPLACEMENTS: dict[str, str] = {
    "Infrastructure": "SPGTIND Index",
}

#: Where the register's geography contradicts the corrected exposure. Applied alongside
#: `TICKER_CORRECTIONS`, because moving an instrument onto a global index and leaving its
#: region as one country is the same wrong metadata in a second column.
REGION_CORRECTIONS: dict[str, tuple[str, str]] = {
    "Infrastructure": (
        "Global",
        "Follows the ticker correction: global listed infrastructure is not Swiss.",
    ),
}

#: The economies each instrument is exposed to, as datafeed country codes (ISO 3166 alpha-2,
#: `EU` for the European Union): the key that links an instrument to the Health of Nations
#: Index, whose peer set uses the same registry. An empty tuple means no single economy
#: dominates (global, multi-asset, or a market outside the HoNI peer set), and says so
#: explicitly rather than by omission. Only economies in the HoNI peer set are named; a
#: regional index lists the peer-set members it holds, without weights.
#:
#: Proposed 27 September 2026 from name, ticker and region, for the CIO to confirm. Every
#: instrument has an entry, so an instrument added without a decision fails a test.
COUNTRY_EXPOSURE: dict[str, tuple[tuple[str, ...], str]] = {
    # single economy
    "CH Equities": (("CH",), "MSCI Switzerland."),
    "Swiss Performance Index": (("CH",), "SPI."),
    "Swiss Dividend Equity": (("CH",), "Swiss dividend equities."),
    "CHF Corporate Loans IG": (("CH",), "Swiss franc investment-grade corporate loans."),
    "CHF Cash": (("CH",), "Swiss franc money market."),
    "Real Estate direct": (("CH",), "Swiss direct property."),
    "SXI Real Estate": (("CH",), "SXI Real Estate Funds (Swiss listed property)."),
    "China Equities": (("CN",), "MSCI China."),
    "China A Shares": (("CN",), "Shanghai A shares."),
    "Hang Seng Index": (("CN",), "Hong Kong is not in the peer set; its market is priced off "
                                 "the Chinese economy."),
    "India Equities": (("IN",), "MSCI India."),
    "Japan Equities": (("JP",), "MSCI Japan."),
    "UK Equities": (("GB",), "MSCI United Kingdom."),
    "US Equities": (("US",), "MSCI USA."),
    "US Treasury TR Index": (("US",), "US Treasuries."),
    "USD Cash": (("US",), "US dollar money market."),
    "Short MSCI US": (("US",), "Short MSCI USA: exposed to the US economy with the sign reversed."),
    "Structured Products": (("US",), "Registered as North America, USD."),
    "CS Long Vola": (("US",), "VXTH: the CBOE VIX tail hedge on the S&P 500."),
    "Long Volatility Index": (("US",), "Shares VXTH with CS Long Vola (a register collision)."),
    "EU Equities": (("EU",), "MSCI Europe; the EU is the peer-set economy it tracks."),
    "Aktien Europe aktiv": (("EU",), "Active European equities on MSCI Europe."),
    "EUR Cash": (("EU",), "Euro money market."),
    "EUR  Corporate Loans IG": (("EU",), "Euro investment-grade corporate loans."),
    "Private Debt": (("EU",), "European leveraged loans (registered Europe, EUR)."),
    # several peer-set economies
    "ASEAN Equities": (("ID", "MY", "PH", "TH"), "MSCI South East Asia; Vietnam is not in it."),
    "Asia ex Japan TR": (("CN", "IN", "ID", "MY", "PH", "TH"), "MSCI AC Asia ex Japan members in the peer set."),
    "APAC Equities": (("JP", "CN", "IN", "ID", "MY", "PH", "TH"), "MSCI AC Asia Pacific members in the peer set."),
    "Asian JACI Bond Index": (("CN", "IN", "ID", "MY", "PH", "TH"), "JP Morgan Asia credit: Asia ex Japan issuers."),
    "Asia Long Short Equities": (("JP", "CN", "IN", "ID", "MY", "PH", "TH"), "Asian hedge-fund index."),
    "Asia Multi Strategy HF": (("JP", "CN", "IN", "ID", "MY", "PH", "TH"), "Asian hedge-fund index."),
    "Asia Pacific Arbitrage": (("JP", "CN", "IN", "ID", "MY", "PH", "TH"), "Asian hedge-fund index."),
    "EM Equities": (("CN", "IN", "BR", "ID", "MY", "PH", "TH"), "MSCI Emerging Markets members in the peer set."),
    "EM Government Bonds LC": (("BR", "CN", "IN", "ID", "MY", "PH", "TH"), "GBI-EM members in the peer set."),
    # no single economy
    "AU NZ Equities": ((), "Australia and New Zealand are not in the peer set."),
    "Bloomberg Hedge Fund": ((), "Global."),
    "Bloomberg Market Neutral HF": ((), "Global."),
    "Bloomberg Multiverse (H-CHF)": ((), "Global aggregate."),
    "Commodities": ((), "Global commodity prices."),
    "Digital Assets": ((), "No economy."),
    "Fixed Holding": ((), "MSCI World based."),
    "Fundo World Equity": ((), "Global minimum volatility."),
    "Global Bonds": ((), "Global aggregate."),
    "Global Equities": ((), "Global."),
    "Global Governmental Bonds": ((), "Global."),
    "Global High Yields": ((), "Global."),
    "Global Macro": ((), "Global."),
    "Global Real Estate indirect": ((), "Global."),
    "Infrastructure": ((), "Global listed infrastructure."),
    "Mining Equities": ((), "Global metals and mining."),
    "MSCI AC World IMI": ((), "Global."),
    "Precious Metals": ((), "Gold: no economy."),
    "Private Equity": ((), "Global."),
    "Trend Following": ((), "Global futures."),
}

#: Any `Growth` label maps to `Gain` at the boundary -- manual section 2.
ROLE_ALIASES = {"growth": "gain", "stabilization": "stabilisation"}


@dataclass(frozen=True)
class RegisteredInstrument:
    """One instrument's classification, as the register holds it."""

    name: str
    role: str
    asset_class: str
    ticker: str | None
    region_scope: str
    region_geo: str | None
    capital_type: str
    currency: str
    liquidity: str | None
    source_role: str
    overridden: bool
    override_reason: str
    #: Set where the register's own ticker was wrong; the original is kept for the audit.
    original_ticker: str | None = None
    ticker_note: str = ""
    #: Economies the instrument is exposed to (`COUNTRY_EXPOSURE`), datafeed country codes.
    countries: tuple[str, ...] = ()
    #: False where the owner took the instrument out of the universe (`DEACTIVATED`).
    active: bool = True
    deactivation_reason: str = ""

    @property
    def note(self) -> str:
        parts = ["Imported from the prototype's published universe (54 instruments)."]
        if self.overridden:
            parts.append(f"Role changed from {self.source_role!r}: {self.override_reason}")
        elif self.override_reason:
            parts.append(f"Role {self.role!r} confirmed: {self.override_reason}")
        if not self.active:
            parts.append(f"Not active. {self.deactivation_reason}")
        if self.ticker_note:
            parts.append(self.ticker_note)
        return "  ".join(parts)


class UniverseError(ValueError):
    """Raised when the universe file is not shaped the way this loader expects."""


def read_universe(path: Path | str = DEFAULT_UNIVERSE_JSON) -> list[RegisteredInstrument]:
    """Read the register, applying the manual's role rules where they differ."""
    path = Path(path)
    if not path.is_file():
        raise UniverseError(f"the universe file was not found at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = payload.get("building_blocks")
    if not isinstance(blocks, list) or not blocks:
        raise UniverseError(f"{path} carries no building_blocks")

    out: list[RegisteredInstrument] = []
    for block in blocks:
        name = str(block.get("name", "")).strip()
        if not name:
            raise UniverseError("an entry in the universe has no name")
        source_role = ROLE_ALIASES.get(
            str(block.get("role", "gain")).strip().lower(),
            str(block.get("role", "gain")).strip().lower(),
        )
        override = ROLE_OVERRIDES.get(name)
        role = override[0] if override else source_role
        correction = TICKER_CORRECTIONS.get(name)
        region_fix = REGION_CORRECTIONS.get(name)
        out.append(
            RegisteredInstrument(
                name=name,
                role=role,
                asset_class=str(block.get("asset_class") or "Unclassified"),
                ticker=(TICKER_REPLACEMENTS.get(name)
                        or block.get("ticker") or None),
                region_scope=str(block.get("region_scope") or "Global"),
                region_geo=(region_fix[0] if region_fix
                            else (block.get("region_geo") or None)),
                capital_type=str(block.get("capital_type") or "Financial"),
                currency=str(block.get("currency") or "CHF"),
                liquidity=(block.get("liquidity") or None),
                source_role=source_role,
                overridden=bool(override) and override[0] != source_role,
                override_reason=override[1] if override else "",
                original_ticker=correction[0] if correction else None,
                ticker_note=" ".join(
                    part for part in (correction[1] if correction else "",
                                      region_fix[1] if region_fix else "") if part),
                countries=COUNTRY_EXPOSURE.get(name, ((), ""))[0],
                active=name not in DEACTIVATED,
                deactivation_reason=DEACTIVATED.get(name, ""),
            )
        )

    names = [i.name for i in out]
    if len(set(names)) != len(names):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise UniverseError(f"the universe repeats instrument name(s): {duplicates}")
    return out
