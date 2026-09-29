"""The Data Sources catalogue from Notion, mirrored into SQL and tagged with actual use.

Sixty-five sources were catalogued by hand over the life of the project. What the
catalogue could not say is **which of them any engine actually reads** -- and that is the
question worth answering, because a research bibliography and a production dependency list
look identical until something breaks.

**How usage is determined, and why it is curated rather than inferred.** The engines do not
read these sources directly; they read the Steiner workbooks, which were *built* from them.
The evidence is therefore the column headers inside those workbooks -- `mcrohist`, `census`,
`fred`, `pikety`, `Vernon`, `EIA` -- each naming the upstream it was stitched from. Matching
those to catalogue entries is a judgement, so every mapping below records the evidence that
supports it and nothing is marked active without one.

Three states, and the middle one is the useful one:

    active     an engine reads a series built from this source, with named evidence
    candidate  relevant to work in flight, not yet wired
    unused     catalogued, but nothing reads it
"""

from __future__ import annotations

from dataclasses import dataclass

#: The Notion data source holding the catalogue.
NOTION_DATA_SOURCE = "da33cd0b-0a11-4bf0-8fc4-80aebd5c700a"


@dataclass(frozen=True)
class Usage:
    """How one catalogued source relates to the engines."""

    status: str           # active | candidate | unused
    engines: tuple[str, ...]
    series: tuple[str, ...]   # the datafeed series it feeds
    evidence: str


def _a(engines, series, evidence) -> Usage:
    return Usage("active", engines, series, evidence)


def _c(evidence) -> Usage:
    return Usage("candidate", (), (), evidence)


#: Keyed by the catalogue's `Name`. Only entries appearing here are anything other than
#: unused; the loader defaults everything else to `unused` rather than guessing.
USAGE: dict[str, Usage] = {
    # --- feeding the long annual record, via the Steiner workbooks -----------
    "Macro history JSTR data base": _a(
        ("fund_map",),
        ("long.gdp", "long.srate", "long.lrate", "long.narrow", "long.broad",
         "long.bill", "long.bond", "long.bondtr", "long.cpi"),
        "Nine workbooks carry a `mcrohist` / `mchist` column as their primary vintage. "
        "The single largest upstream in the engine.",
    ),
    "Census.gov": _a(
        ("fund_map",),
        ("long.gov_debt", "long.loans", "long.erng", "long.ump", "long.wheat", "long.ag"),
        "Six workbooks carry a `census` column.",
    ),
    "Gov debt": _a(("fund_map",), ("long.gov_debt",),
                   "Gov_debt_1870-2020.xlsx, census column."),
    "Bank loans": _a(("fund_map",), ("long.loans",),
                     "loans_1870-2020.xlsx, census column."),
    "Total bank loans": _a(("fund_map",), ("long.loans",),
                           "Same series as Bank loans; the catalogue holds both."),
    "av. annual earning": _a(("fund_map",), ("long.erng",),
                             "erng_1870-2020.xlsx, census and lib_index columns."),
    "earnings": _a(("fund_map",), ("long.erng",),
                   "Same concept as av. annual earning; duplicated in the catalogue."),
    "unemployment": _a(("fund_map",), ("long.ump",),
                       "ump_1870-2020.xlsx; the Vernon column supplies the early years."),
    "Non-farm Unemployment": _a(("fund_map",), ("long.ump",),
                                "Same workbook; a second vintage of the same concept."),
    "CPI US average": _a(("fund_map",), ("long.cpi",),
                         "cpi_1870-2020.xlsx. Also the deflator for all real-terms work."),
    "Wheat US": _a(("fund_map",), ("long.wheat",),
                   "wheat_1870-2020.xlsx, census column; half the commodity block."),
    "Macrotrends": _a(("fund_map",), ("long.wheat", "long.gold"),
                      "The `macrotrend` column in wheat, and a gold vintage."),
    "Oil price": _a(("fund_map",), ("long.oil",),
                    "oil_1870-2020.xlsx, EIA column; the other half of commodities."),
    "Ag\\farm land": _a(("fund_map",), ("long.ag",),
                        "ag_1870-2020.xlsx, census column; block 7, from 1910."),
    "Housing prices": _a(("fund_map",), ("long.house",),
                         "house_1890-2020.xlsx, `pikety` column; block 8."),
    "Capital is Back: Wealth-Income Ratios in Rich Countries 1700–2010": _a(
        ("fund_map",), ("long.house",),
        "The Piketty-Zucman paper behind the housing series. The dataset file sits beside "
        "the workbooks in Knowledge_Center.",
    ),
    "Long US series Schiller": _a(("fund_map",), ("long.spx",),
                                  "spx_1870-2020.xlsx; the S&P level back to 1870."),
    "SnP500 yearly": _a(("fund_map",), ("long.spx",),
                        "Same concept as the Shiller series; catalogued separately."),
    "Gold yearly": _a(("fund_map",), ("long.gold",),
                      "gold_1870-2020.xlsx, New York market price per fine ounce."),
    "Goldprice series": _a(("fund_map",), ("long.gold",),
                           "A second gold vintage in the catalogue."),
    "Gold price UK": _a(
        ("fund_map",), ("long.gold",),
        "Officer & Williamson, MeasuringWorth. The 750-year real-rate series in manual "
        "section 9 uses the gold price as its deflator.",
    ),
    "World gov Bonds": _a(("fund_map",), ("long.bondtr",),
                          "bondtr_1871-2015.xlsx; block 4, government bond total return."),
    "US T-bond yearly": _a(("fund_map",), ("long.bond", "long.bondtr"),
                           "The long rate and its total-return counterpart."),

    # --- in flight ----------------------------------------------------------
    "Germany hyperinflation": _c(
        "Directly required: the currency work needs 1922-23 as a labelled regime rather "
        "than a phase estimate it can be averaged into."
    ),
    "CPI Inflation CH": _c(
        "Required for real terms in Swiss francs, which manual section 9 states the model "
        "is denominated in. Not yet loaded."
    ),
    "German Data & Sources": _c("The DEM leg of the EUR proxy, pre-1999."),
    "Credit suisse global returns": _c(
        "Long-run global returns from 1900. Hard copy only, per the catalogue -- so it is "
        "a transcription job rather than a load."
    ),
    "US historical 1610-1970": _c(
        "Census historical statistics. PDF, requires transcribing, per the catalogue."
    ),
    "International Historical Statistics": _c("Macmillan, PDF. Same constraint."),
    "Long term trends": _c("Catalogued as a full database; contents not yet inspected."),
    "Prices & wages US": _c("University of Missouri; a candidate for wage-series depth."),
}

#: The engines that exist. Kept explicit so a typo in USAGE fails a test rather than
#: silently inventing an engine.
KNOWN_ENGINES = ("fund_map", "datafeed", "market_risk", "lbs", "optimiser", "mandate",
                 "pcp", "scenario", "trajectory", "score")


def classify(name: str) -> Usage:
    return USAGE.get(name, Usage("unused", (), (), ""))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

import json  # noqa: E402
import pathlib  # noqa: E402

from store import db  # noqa: E402

SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent / "data" / "notion_data_sources.json"


def slug(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:120]


def load() -> dict:
    """Mirror the catalogue into SQL, tagged with actual use."""
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    rows = payload["rows"]
    now = db.utc_now()

    unknown = sorted(set(USAGE) - {r["name"] for r in rows})
    if unknown:
        raise ValueError(
            f"USAGE names {unknown} that the catalogue does not contain. Either the "
            f"catalogue was re-synced and an entry renamed, or the mapping has a typo -- "
            f"and a typo here silently marks a used source as unused."
        )

    counts: dict[str, int] = {}
    with db.datafeed_session() as conn:
        for row in rows:
            usage = classify(row["name"])
            counts[usage.status] = counts.get(usage.status, 0) + 1
            conn.execute(
                db.upsert(
                    "reference_source",
                    ("source_key", "name", "author", "quality", "comments", "notion_url",
                     "usage_status", "engines", "series", "evidence", "synced_at"),
                    ("source_key",),
                ),
                (slug(row["name"]), row["name"], row["author"], row["quality"],
                 row["comments"], row["notion_url"], usage.status,
                 db.dumps(list(usage.engines)), db.dumps(list(usage.series)),
                 usage.evidence, now),
            )
    return {"total": len(rows), "by_status": counts}


if __name__ == "__main__":
    report = load()
    print(f"{report['total']} reference sources loaded")
    for status, n in sorted(report["by_status"].items()):
        print(f"  {status:<10} {n}")
