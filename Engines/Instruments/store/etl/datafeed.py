"""Build the shared datafeed store: every series, its metadata, and its joints.

    python -m store.etl.datafeed              # build from what is cached, stitch, snapshot
    python -m store.etl.datafeed --fetch      # download the raw feeds first
    python -m store.etl.datafeed --no-stitch  # raw series only
    python -m store.etl.datafeed --describe-only  # rewrite descriptions, touch no data

**Raw inputs and derived series are both first-class.** A stitched series does not replace
the pieces it was made from -- those stay in the registry as `yahoo.SPY`, `jst.chl` and so
on, and the derived series references them through ``series_segment``. Anyone who doubts a
long series can read the short ones it was built from and the discrepancy at every joint.

Everything written here lands in the ``datafeed`` schema, which is shared: engines read it
and only these loaders write to it.
"""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from store import db
from store.etl.long_record import SERIES as LONG_SERIES
from store.etl.long_record import read_long_record
from store.etl.market_signal import (
    instrument_names,
    read_market_risk_signal,
    recover_instrument_returns,
    split_sections,
)
from store.etl.universe import read_universe
from store.stitch import Candidate, stitch, summarise

DEFAULT_ECN_DIR = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Knowledge_Center\Published"
    r"\Dynamic Investment\Model\ecn_model"
)
DEFAULT_FEED_CSV = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Projects\andersCH-prototype_old"
    r"\andersCH-prototype_old\data\feeds\2026-08-01_andersCH-report.csv"
)


# ---------------------------------------------------------------------------
# Metadata for the long annual record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Meta:
    unit: str
    currency: str
    magnitude: str
    category: str
    description: str


#: What each of the 19 annual series actually is. Without this a reader cannot tell a rate
#: from a level from a ratio, and combining two of them is silently wrong.
LONG_META: dict[str, Meta] = {
    "gdp":      Meta("index_level", "USD", "units", "macro",
                     "US nominal GDP in current US dollars, full units (not billions), annual "
                     "1870 to 2020. Joined from the Macrohistory database and FRED. The "
                     "denominator of debt saturation."),
    "gov_debt": Meta("index_level", "USD", "units", "macro",
                     "US federal government debt outstanding in current US dollars, full "
                     "units, annual 1870 to 2020. Joined from census.gov historical "
                     "statistics and FRED."),
    "loans":    Meta("index_level", "USD", "units", "macro",
                     "US bank loans outstanding in current US dollars, full units, annual "
                     "1870 to 2020. Joined from census historical statistics and FRED."),
    "srate":    Meta("rate", "none", "decimal", "macro",
                     "US 1-year Treasury bill rate, annual 1870 to 2020, as a decimal (0.0572 "
                     "is 5.72 %). Joined from Macrohistory and FRED. The short leg of the "
                     "yield curve."),
    "lrate":    Meta("rate", "none", "decimal", "macro",
                     "US 10-year Treasury yield, annual 1870 to 2020, as a decimal. Joined "
                     "from Macrohistory and FRED. The long leg of the yield curve."),
    "narrow":   Meta("index_level", "USD", "units", "macro",
                     "US narrow money stock in current US dollars, full units, annual 1870 "
                     "to 2020. Joined from Macrohistory and FRED. Input to the monetary "
                     "composition indicator."),
    "broad":    Meta("index_level", "USD", "units", "macro",
                     "US broad money stock in current US dollars, full units, annual 1870 "
                     "to 2020. Joined from Macrohistory and FRED. Input to the monetary "
                     "composition indicator."),
    "bill":     Meta("return_simple", "USD", "decimal", "return",
                     "Annual return on holding US Treasury bills, 1870 to 2020, as a "
                     "decimal. Macrohistory, then FRED. The cash return of block 1 and the "
                     "financial sentiment component."),
    "bond":     Meta("rate", "none", "decimal", "return",
                     "US long-term government bond yield, annual 1870 to 2020, as a decimal, "
                     "from the Macrohistory database. A yield, not a holding return: the "
                     "holding return is long.bondtr. Block 2."),
    "spx":      Meta("index_level", "USD", "units", "return",
                     "S&P US stock index level, annual 1870 to 2020 (4.44 in 1870). "
                     "Log-differenced into the equity return of block 3."),
    "erng":     Meta("index_level", "USD", "units", "macro",
                     "US wage earnings index, annual 1870 to 2020, joined from census, FRED "
                     "and an earlier historical earnings index."),
    "ump":      Meta("rate", "none", "decimal", "macro",
                     "US unemployment rate, annual 1870 to 2020, as a decimal (0.0352 is "
                     "3.52 %). Joined from Vernon's historical estimates, census and FRED."),
    "cpi":      Meta("rate", "none", "decimal", "macro",
                     "US consumer price inflation, annual 1870 to 2020, as a decimal rate "
                     "rather than a price level. Macrohistory, then FRED. The deflator for "
                     "real terms."),
    "wheat":    Meta("price", "USD", "units", "price",
                     "US wheat price in US dollars, annual 1870 to 2020 (census, then "
                     "Macrotrends). Half of the commodity block, with oil."),
    "oil":      Meta("price", "USD", "units", "price",
                     "Crude oil price in US dollars per barrel, annual 1870 to 2020 (EIA, "
                     "then FRED). Half of the commodity block, with wheat."),
    "gold":     Meta("price", "USD", "units", "price",
                     "Gold price on the New York market in US dollars per fine ounce, "
                     "annual 1870 to 2020. Log-differenced into the return of block 6."),
    "house":    Meta("index_level", "USD", "units", "return",
                     "US house price index, annual 1890 to 2020, joined from Piketty's "
                     "series and FRED. Starts in 1890. The real estate return of block 8."),
    "bondtr":   Meta("return_simple", "USD", "decimal", "return",
                     "Annual total return on US government bonds, 1871 to 2015, as a "
                     "decimal (Macrohistory, then Macrotrends). Ends in 2015. Block 4."),
    "ag":       Meta("index_level", "USD", "units", "return",
                     "Value of US farm business, annual, held from 1910 to 2020 (census, "
                     "then FRED). The source is sparse before 1910 and those years are "
                     "dropped, not filled. The agriculture return of block 7."),
}


# ---------------------------------------------------------------------------
# Stitch chains
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chain:
    """One long series to be built: an anchor, and what may be joined behind it."""

    series_id: str
    name: str
    anchor: str
    candidates: tuple[str, ...]
    currency: str
    country: str
    index_family: str | None
    description: str


#: The anchor is always the best-evidenced modern series; candidates are ordered only for
#: readability, since the algorithm picks by measured discrepancy rather than by order.
CHAINS: tuple[Chain, ...] = (
    Chain("eq.world.m", "World equity, monthly", "URTH", ("ACWI", "VT", "EFA", "SPY"),
          "USD", "WLD", "MSCI", "Monthly total return on developed-market large and mid-cap "
          "equity, the MSCI World universe, in US dollars."),
    Chain("eq.acwi.m", "All-country equity, monthly", "ACWI", ("VT", "EFA", "SPY"),
          "USD", "WLD", "MSCI", "Monthly total return on large and mid-cap equity across "
          "developed and emerging markets, the MSCI ACWI universe, in US dollars."),
    Chain("eq.india.m", "India equity, monthly", "INDA", ("EPI", "IFN"),
          "USD", "IN", "MSCI", "Monthly total return on Indian equity, in US dollars."),
    Chain("eq.china.m", "China equity, monthly", "MCHI", ("GXC", "FXI"),
          "USD", "CN", "MSCI", "Monthly total return on Chinese equity in the share classes "
          "open to foreign investors, in US dollars."),
    Chain("eq.chinaA.m", "China A-share equity, monthly", "ASHR", ("GXC", "FXI"),
          "USD", "CN", "CSI", "Monthly total return on mainland-listed China A-shares (CSI "
          "300), the domestic market, in US dollars."),
    Chain("eq.europe.m", "Europe equity, monthly", "IEV", ("EZU", "VGK"),
          "USD", "EU", "S&P", "Monthly total return on European large-cap equity across "
          "developed markets, in US dollars."),
    Chain("re.us.m", "US real estate, monthly", "IYR", ("VNQ",),
          "USD", "US", "Dow Jones", "Monthly total return on US listed real estate "
          "investment trusts, in US dollars."),
    Chain("bd.ustreasury.m", "US Treasury total return, monthly", "GOVT", ("IEF", "TLT"),
          "USD", "US", "Bloomberg", "Monthly total return on US Treasuries across the curve, "
          "one to thirty years, in US dollars."),
    Chain("bd.globalagg.m", "Global aggregate, monthly", "BNDX", ("AGG",),
          "USD", "WLD", "Bloomberg", "Monthly total return on investment-grade bonds outside "
          "the US, hedged to the US dollar."),
    Chain("bd.emlocal.m", "EM government local currency, monthly", "EMLC", ("EMB",),
          "USD", "WLD", "JPMorgan", "Monthly total return on emerging-market government bonds "
          "in local currency (J.P. Morgan GBI-EM), measured in US dollars, so it "
          "carries the currency risk."),
    Chain("bd.highyield.m", "High yield, monthly", "HYG", ("JNK",),
          "USD", "US", "Bloomberg", "Monthly total return on US sub-investment-grade "
          "corporate bonds, in US dollars."),
    Chain("cm.broad.m", "Broad commodities, monthly", "GSG", ("DBC",),
          "USD", "WLD", "S&P GSCI", "Monthly total return on broad commodity futures (S&P "
          "GSCI, production weighted and so energy heavy), in US dollars."),
)

def chain_description(chain: Chain, segments: list[tuple[str, str, str, bool]]) -> str:
    """What a stitched series is, including what each of its segments actually measures.

    ``segments`` is ``(source_series_id, from_period, to_period, smoothed)``, newest first,
    as written to ``series_segment``. The prose alone would hide the point that matters
    most: before the anchor's first month the series is a *different* instrument, and a
    reader has to be told which one and over which span.
    """
    from feeds.security_meta import SECURITIES

    def label(series_id: str) -> str:
        symbol = series_id.split(".", 1)[1]
        meta = SECURITIES.get(symbol)
        if meta is None:
            return symbol
        exposure = meta.description.split(". ")[0].rstrip(".")
        if exposure[1:2].islower():
            exposure = exposure[0].lower() + exposure[1:]
        return f"{symbol} ({meta.name}: {exposure})"

    if not segments:
        return chain.description
    if len(segments) == 1:
        sid, first, last, _ = segments[0]
        return (f"{chain.description} No earlier segment was joined: the series is "
                f"{label(sid)} alone, {first} to {last}.")
    parts = [f"{label(sid)} {first} to {last}" for sid, first, last, _ in segments]
    text = (f"{chain.description} Built from {len(segments)} segments, newest first: "
            + "; ".join(parts) + ". Each segment's own exposure applies over its span, "
            "and each earlier one was chosen by the smallest mean discrepancy over its "
            "overlap.")
    smoothed = [sid.split(".", 1)[1] for sid, _, _, sm in segments if sm]
    if smoothed:
        text += f" Smoothing was applied at the joint to {', '.join(smoothed)}."
    return text


def refresh_descriptions() -> int:
    """Rewrite the description column only, for the long record and the chains.

    Leaves every observation, segment and snapshot untouched, so it can run after the
    wording changes without re-fetching or re-stitching anything.
    """
    changed = 0
    with db.datafeed_session() as conn:
        for key, meta in LONG_META.items():
            changed += conn.execute(
                "UPDATE series_definition SET description = %s, updated_at = %s "
                "WHERE series_id = %s AND description IS DISTINCT FROM %s",
                (meta.description, db.utc_now(), f"long.{key}", meta.description),
            ).rowcount
        for chain in CHAINS:
            segments = [
                (r["source_series_id"], r["from_period"], r["to_period"], bool(r["smoothed"]))
                for r in conn.execute(
                    "SELECT source_series_id, from_period, to_period, smoothed "
                    "FROM series_segment WHERE series_id = %s ORDER BY segment_index",
                    (chain.series_id,))
            ]
            text = chain_description(chain, segments)
            changed += conn.execute(
                "UPDATE series_definition SET description = %s, updated_at = %s "
                "WHERE series_id = %s AND description IS DISTINCT FROM %s",
                (text, db.utc_now(), chain.series_id, text),
            ).rowcount
    return changed


#: Everything the chains need, plus the proxies already in use.
def chain_symbols() -> list[str]:
    out: list[str] = []
    for chain in CHAINS:
        out.append(chain.anchor)
        out.extend(chain.candidates)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _checksum(values: dict[str, float]) -> str:
    blob = ";".join(f"{p}={values[p]!r}" for p in sorted(values))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def upsert_series(conn: db.Connection, *, series_id: str, name: str, unit: str,
                  currency: str, magnitude: str, period: str, country: str,
                  category: str, source: str, origin_kind: str, quality_grade: str,
                  values: dict[str, float], description: str = "",
                  index_family: str | None = None, pull_code: str | None = None,
                  source_file: str | None = None, is_stitched: bool = False,
                  flags: dict[str, str] | None = None,
                  segment_of: dict[str, int] | None = None) -> None:
    """Write one series and its observations."""
    now = db.utc_now()
    periods = sorted(values)
    conn.execute(
        db.upsert(
            "series_definition",
            ("series_id", "name", "description", "unit", "currency", "magnitude", "period",
             "country", "category", "index_family", "pull_code", "source", "source_file",
             "origin_kind", "quality_grade", "is_stitched", "first_period", "last_period",
             "observation_count", "notes", "created_at", "updated_at"),
            ("series_id",),
            update=("name", "description", "unit", "currency", "magnitude", "period",
                    "country", "category", "index_family", "pull_code", "source",
                    "source_file", "origin_kind", "quality_grade", "is_stitched",
                    "first_period", "last_period", "observation_count", "updated_at"),
        ),
        (series_id, name, description, unit, currency, magnitude, period, country,
         category, index_family, pull_code, source, source_file, origin_kind,
         quality_grade, is_stitched, periods[0] if periods else None,
         periods[-1] if periods else None, len(values), "", now, now),
    )
    conn.executemany(
        db.upsert("observation", ("series_id", "period", "value", "flag", "segment"),
                  ("series_id", "period")),
        [(series_id, p, values[p],
          (flags or {}).get(p, "observed"),
          (segment_of or {}).get(p))
         for p in periods],
    )


def build(*, fetch: bool, do_stitch: bool, ecn_dir: Path, feed_csv: Path) -> dict:
    started = time.perf_counter()
    db.initialise()
    report: dict = {"raw": 0, "stitched": 0, "observations": 0}

    # --- 1. the long annual record ----------------------------------------
    print("long annual record ...")
    record = read_long_record(ecn_dir)
    with db.datafeed_session() as conn:
        for key, series in record.items():
            spec = next(s for s in LONG_SERIES if s.key == key)
            meta = LONG_META[key]
            db.register_source(conn, name=spec.filename, path=ecn_dir / spec.filename,
                               note=spec.note, origin_kind="nas:house-research")
            values = {str(series.first_year + i): v for i, v in enumerate(series.values)}
            upsert_series(
                conn, series_id=f"long.{key}", name=f"{key} (long annual record)",
                description=meta.description, unit=meta.unit, currency=meta.currency,
                magnitude=meta.magnitude, period="A", country="US",
                category=meta.category, source="Steiner (2021), Dynamic Investment",
                source_file=spec.filename, origin_kind="nas:house-research",
                quality_grade="authoritative", pull_code=f"{spec.filename}:col{spec.column}",
                values=values)
            report["raw"] += 1
            report["observations"] += len(values)
    print(f"  {len(record)} series")

    # --- 2. the monthly market risk signal --------------------------------
    print("monthly signal ...")
    sections = split_sections(feed_csv)
    signal = read_market_risk_signal(sections)
    with db.datafeed_session() as conn:
        db.register_source(conn, name=feed_csv.name, path=feed_csv,
                           note="Monthly andersCH report; dates corrected by -1 month.",
                           origin_kind="nas:prototype")
        for state in range(1, 26):
            values = {m.period: m.probabilities[state - 1] for m in signal}
            upsert_series(
                conn, series_id=f"signal.mrs.s{state:02d}",
                name=f"Market Risk Signal, state {state}",
                description=(
                    f"Probability the monthly Market Risk Signal places on state "
                    f"{state} of 25, where 1 is the most adverse market environment and "
                    f"25 the most benign. Each month's 25 values are normalised to sum "
                    f"to one, so this is a distribution across states, not a level."
                ),
                unit="ratio", currency="none", magnitude="decimal", period="M",
                country="WLD", category="signal", source="andersCH monthly report",
                source_file=feed_csv.name, origin_kind="nas:prototype",
                quality_grade="proxy", pull_code=f"MARKET RISK SIGNAL:col{state}",
                values=values)
            report["raw"] += 1
            report["observations"] += len(values)
    print(f"  25 state columns x {len(signal)} months")

    # --- 3. recovered instrument returns ----------------------------------
    print("recovered instrument returns ...")
    kept, _ = recover_instrument_returns(sections)
    by_name: dict[str, dict[str, float]] = {}
    for row in kept:
        by_name.setdefault(row.instrument, {})[row.period] = row.value
    with db.datafeed_session() as conn:
        for name, values in by_name.items():
            upsert_series(
                conn, series_id=f"recovered.{_slug(name)}",
                name=f"{name} (recovered)",
                description=(
                    f"{name}, as held in the andersCH portfolio. Recovered as "
                    f"performance contribution divided by weight, so it is the return "
                    f"of the position rather than of an index. Conditional on the "
                    f"manager having held it that month, which makes it "
                    f"selection-biased: it describes the asset when chosen, not the "
                    f"asset in that state."
                ),
                unit="return_simple", currency="CHF", magnitude="decimal", period="M",
                country="WLD", category="return", source="andersCH monthly report",
                source_file=feed_csv.name, origin_kind="nas:prototype",
                quality_grade="weak", pull_code=f"PERFORMANCE CONTRIBUTION:{name}",
                values=values)
            report["raw"] += 1
            report["observations"] += len(values)
    print(f"  {len(by_name)} instruments")

    # --- 4. public feeds ---------------------------------------------------
    from feeds import yahoo
    from feeds.proxy_map import PROXIES
    from feeds.security_meta import describe, missing

    # Yahoo symbols only: a Cboe index (`proxy_map.CBOE_SYMBOLS`) has no Yahoo history
    # and is loaded by `python -m store.etl.cboe`.
    wanted = sorted(set(chain_symbols()) |
                    {p.symbol for p in PROXIES.values()
                     if p.usable and p.symbol and p.source == "yahoo"})
    fetched: dict[str, dict[str, float]] = {}
    if fetch:
        print(f"fetching {len(wanted)} public series ...")
        series, failures = yahoo.fetch_many(wanted)
        for symbol, s in series.items():
            fetched[symbol] = s.returns
        undescribed = missing(fetched)
        if undescribed:
            raise ValueError(
                f"no entry in feeds/security_meta.py for {undescribed}. A series whose "
                f"description says only how it was computed cannot be identified by "
                f"anyone reading the catalogue; add what it is before loading it."
            )
        with db.datafeed_session() as conn:
            for symbol, values in fetched.items():
                meta = describe(symbol)
                upsert_series(
                    conn, series_id=f"yahoo.{symbol}", name=meta.name,
                    description=(
                        f"{meta.description} Monthly total return from the adjusted "
                        f"close, quoted in US dollars."
                    ),
                    unit="return_simple", currency="USD", magnitude="decimal", period="M",
                    country=meta.country, category="return", source="Yahoo Finance",
                    index_family=meta.index_family or None,
                    origin_kind="internet:yahoo", quality_grade="close",
                    pull_code=symbol, values=values)
                report["raw"] += 1
                report["observations"] += len(values)
        print(f"  {len(fetched)} fetched, {len(failures)} failed")
        if failures:
            for symbol, why in failures.items():
                print(f"    {symbol}: {why}")
    else:
        with db.datafeed_session() as conn:
            for row in conn.execute(
                "SELECT series_id FROM series_definition WHERE origin_kind = 'internet:yahoo'"
            ):
                symbol = row["series_id"].split(".", 1)[1]
                fetched[symbol] = {
                    o["period"]: o["value"]
                    for o in conn.execute(
                        "SELECT period, value FROM observation WHERE series_id = %s",
                        (row["series_id"],))
                }
        print(f"  {len(fetched)} public series already in the store")

    # --- 5. stitch ---------------------------------------------------------
    if do_stitch and fetched:
        print("stitching ...")
        with db.datafeed_session() as conn:
            for chain in CHAINS:
                anchor = fetched.get(chain.anchor)
                if not anchor:
                    print(f"  {chain.series_id:<18} SKIPPED: no anchor {chain.anchor}")
                    continue
                candidates = [
                    Candidate(series_id=f"yahoo.{s}", values=fetched[s])
                    for s in chain.candidates if s in fetched
                ]
                result = stitch(Candidate(f"yahoo.{chain.anchor}", anchor), candidates)
                flags = {p: result.flag_for(p) for p in result.values}
                upsert_series(
                    conn, series_id=chain.series_id, name=chain.name,
                    description=chain_description(chain, [
                        (s.source_series_id, s.from_period, s.to_period, s.smoothed)
                        for s in result.segments]),
                    unit="return_simple",
                    currency=chain.currency, magnitude="decimal", period="M",
                    country=chain.country, category="return",
                    index_family=chain.index_family,
                    source=f"stitched from {chain.anchor} + "
                           f"{len(result.segments) - 1} earlier segment(s)",
                    origin_kind="derived:stitch", quality_grade="proxy",
                    is_stitched=True, values=result.values, flags=flags,
                    segment_of=result.segment_of)
                conn.execute("DELETE FROM series_segment WHERE series_id = %s",
                             (chain.series_id,))
                conn.executemany(
                    db.upsert(
                        "series_segment",
                        ("series_id", "segment_index", "source_series_id", "from_period",
                         "to_period", "overlap_periods", "mean_discrepancy", "smoothed",
                         "rejected_candidates", "note"),
                        ("series_id", "segment_index"),
                    ),
                    [(chain.series_id, s.segment_index, s.source_series_id, s.from_period,
                      s.to_period, s.overlap_periods, s.mean_discrepancy, s.smoothed,
                      db.dumps(s.rejected), s.note) for s in result.segments],
                )
                gained = len(result.values) - len(anchor)
                report["stitched"] += 1
                print(f"  {chain.series_id:<18} {len(result.values):>4} months "
                      f"(+{gained:>3})  {summarise(result)}")

    # --- 6. snapshot -------------------------------------------------------
    with db.datafeed_session() as conn:
        rows = conn.execute(
            "SELECT series_id, first_period, last_period, observation_count "
            "FROM series_definition ORDER BY series_id").fetchall()
        per_series = []
        for row in rows:
            values = {
                o["period"]: o["value"]
                for o in conn.execute(
                    "SELECT period, value FROM observation WHERE series_id = %s",
                    (row["series_id"],))
            }
            per_series.append((row["series_id"], row["first_period"], row["last_period"],
                               row["observation_count"], _checksum(values)))
        checksum = hashlib.sha256(
            ";".join(f"{s[0]}:{s[4]}" for s in per_series).encode("utf-8")
        ).hexdigest()
        snapshot_id = db.content_id("SNAP", {"checksum": checksum})
        total = sum(s[3] for s in per_series)
        conn.execute(
            db.upsert("snapshot", ("snapshot_id", "created_at", "checksum", "series_count",
                                   "observation_count", "note"), ("snapshot_id",)),
            (snapshot_id, db.utc_now(), checksum, len(per_series), total,
             "Built by store.etl.datafeed"),
        )
        conn.executemany(
            db.upsert("snapshot_series",
                      ("snapshot_id", "series_id", "first_period", "last_period",
                       "observation_count", "checksum"), ("snapshot_id", "series_id")),
            [(snapshot_id, *s) for s in per_series],
        )
        report["snapshot_id"] = snapshot_id
        report["series_total"] = len(per_series)
        report["observation_total"] = total

    report["seconds"] = time.perf_counter() - started
    return report


def _slug(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--describe-only" in argv:
        print(f"{refresh_descriptions()} descriptions rewritten")
        return 0
    report = build(
        fetch="--fetch" in argv,
        do_stitch="--no-stitch" not in argv,
        ecn_dir=DEFAULT_ECN_DIR,
        feed_csv=DEFAULT_FEED_CSV,
    )
    print(f"\nsnapshot {report['snapshot_id']}")
    print(f"  {report['series_total']} series, {report['observation_total']} observations")
    print(f"  {report['stitched']} stitched")
    print(f"done in {report['seconds']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
