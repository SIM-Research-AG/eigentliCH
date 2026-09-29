"""Export the store's metadata for the Notion **SQL Metadata** database.

The catalogue of what the SQL store contains lives in Notion, outside this repository, so
it can be read by people who will never clone it. This module is the one-way bridge:
**SQL is the source of truth, Notion is the published view.** Nothing here reads Notion
back, and nothing in the engines reads Notion at all -- a catalogue that could drift into
being authoritative would be a second, softer definition of the data.

Two kinds of object are exported, because "metadata" means both:

    series   one row per series the feed serves -- what the numbers mean
    table    one row per SQL table in either schema -- where they live

The series rows are derived entirely from ``series_definition``; they cannot drift,
because they are read out of the same columns the engines read. The table rows carry one
curated field -- ``purpose`` -- the only hand-written text in the export. It is kept here
rather than in Notion so that a table added without a purpose fails a test rather than
appearing in the catalogue unexplained.
"""

from __future__ import annotations

import csv
import io
import json
import os
import pathlib
from dataclasses import asdict, dataclass, replace

from store import config as dbconfig
from store import db
from store import provision

#: The Notion database this feeds.
NOTION_DATABASE = "3e80ba72-543f-8047-b5b3-dbf37ee6c4da"
NOTION_DATA_SOURCE = "3e80ba72-543f-809d-896e-000bb738ae63"

#: What each table is for, in one line. The only hand-written text in the export.
#: A table missing from here fails ``test_every_table_has_a_purpose`` rather than
#: reaching the catalogue undescribed.
TABLE_PURPOSE: dict[str, str] = {
    # -- datafeed: shared source data, owned by the feed, read by every engine --------
    "datafeed.source_file":
        "Provenance for every file loaded into the feed: SHA-256, byte size, the absolute "
        "path the bytes were read from, and whether that path was the NAS or the internet.",
    "datafeed.series_definition":
        "The registry. One row per series with the metadata that makes its numbers safe to "
        "combine: unit, currency, magnitude, period, country, and how far it can be trusted.",
    "datafeed.observation":
        "Every value the feed holds, each flagged observed, carried or stitched. A panel is "
        "assembled from here and never invents a cell.",
    "datafeed.series_segment":
        "The joints of a stitched series: which source covered which span, the overlap, the "
        "mean discrepancy that won it, and whether smoothing fired above the 2% threshold.",
    "datafeed.snapshot":
        "An immutable, checksummed manifest of the whole feed at a point in time. The "
        "reference every downstream golden test pins itself to.",
    "datafeed.snapshot_series":
        "Per-series coverage and checksum inside one snapshot.",
    "datafeed.reference_source":
        "The Notion Data Sources catalogue mirrored into SQL, each entry tagged with whether "
        "an engine actually reads it and which -- a bibliography and a dependency list look "
        "identical until something breaks.",

    # -- instruments: what the Fund Map engine produces -------------------------------
    "instruments.source_file":
        "Provenance for the files this engine loads directly, pending its migration to "
        "reading the feed.",
    "instruments.long_series":
        "The long annual record behind Steiner (2021): nineteen series, 1870 onwards.",
    "instruments.market_environment":
        "The composite economic cycle value per year, and the phase it was classified into.",
    "instruments.environment_indicator":
        "The eight standardised, de-trended indicators the cycle is built from, per year.",
    "instruments.market_risk_signal":
        "The monthly Market Risk Signal as a 25-state distribution. Read by reference, "
        "never recomputed here.",
    "instruments.market_risk_month":
        "Each month's summary reading of that distribution, so consumers need not re-reduce "
        "the distribution themselves.",
    "instruments.calibration":
        "One row per calibration run: its identifier, when it ran, and the source checksums "
        "that make it reproducible.",
    "instruments.calibration_block":
        "The 25-state return profile for each of the eight asset blocks, with the method "
        "label on every state.",
    "instruments.calibration_role":
        "The four role profiles -- gain, income, stabilisation, protection -- averaged at "
        "phase level and interpolated across the state axis.",
    "instruments.instrument":
        "The instrument register. Expandable by data change rather than code change.",
    "instruments.instrument_return":
        "Monthly returns per instrument, the evidence every estimated profile is built from.",
    "instruments.instrument_profile":
        "The estimated 25-state profile per instrument per calibration, carrying the method "
        "behind each value and the coverage grade of the weakest one.",
    "instruments.state_map":
        "The quantile bridge mapping the monthly signal onto the annual calibration axis.",
    "instruments.state_map_meta":
        "The quantiles and bounds that define that bridge.",
    "instruments.run_manifest":
        "What each run produced. No figure leaves an engine without one.",
}

#: Which engines read each schema, keyed by (database, schema). Kept coarse on purpose:
#: a per-table claim would be precise and wrong the moment a query changes.
#:
#: The key is the pair, not the schema alone, because **two different databases both have
#: a schema called `datafeed`** and they are not the same thing. Keying on the name alone
#: credited the Macro project's feed to `fund_map`, which does not read it.
SCHEMA_ENGINES = {
    ("simtech", "fmre"): ("fmre",),
    ("simtech", "fmre_feed"): ("fmre",),
    ("simtech", "datafeed"): ("datafeed",),
    ("simtech", "honi"): ("honi",),
    ("simtech", "macrofield"): ("macrofield",),
    ("simtech", "mrs"): ("mrs",),
    ("simtech", "pcp"): ("pcp",),
    ("simtech", "aggregation"): ("aggregation",),
    ("simtech", "cycle"): ("cycle",),
    ("simtech", "lbs"): ("lbs",),
    ("simtech", "report"): ("report",),
    ("simtech", "chatbot"): ("chatbot",),
    ("simtech", "eigentlich"): ("eigentlich",),
}



def engines_for(dbname: str, schema: str) -> tuple[str, ...]:
    return SCHEMA_ENGINES.get((dbname, schema), ())


@dataclass(frozen=True)
class Source:
    """One PostgreSQL database to catalogue.

    The server carries more than this repository builds. ``simtech_macro`` belongs to a
    different project and is read strictly read-only: catalogued because the point of a
    meta database is that it covers every engine, not just the convenient one.
    """

    dbname: str
    project: str
    schemas: tuple[str, ...]
    #: Which of ``schemas`` holds the engine's own artefacts, and which holds series.
    #: Named explicitly rather than guessed: guessing broke the moment the feed schema
    #: stopped being called `datafeed`.
    engine_schema: str
    feed_schema: str
    #: Where series-level metadata lives, if the project keeps any. The two projects
    #: shape it differently, which is itself worth recording.
    series_table: str | None
    #: True when this repository owns the schema and must supply a purpose per table.
    owned: bool


CATALOGUE: tuple[Source, ...] = (
    Source("simtech", "Instruments", ("fmre", "fmre_feed"),
           engine_schema="fmre", feed_schema="fmre_feed",
           series_table="fmre_feed.series_definition", owned=True),
    # The Macro repository's schemas moved into `simtech` on 27 September 2026, so both
    # projects are now one database. They stay two Sources because ownership of the prose
    # is still split: this repository will not invent descriptions for schemas it did not
    # build, and `owned=False` is what enforces that.
    # `aggregation` and `cycle` added 29.09.2026.
    Source("simtech", "Macro", ("aggregation", "cycle", "datafeed", "honi", "macrofield", "mrs"),
           engine_schema="honi", feed_schema="datafeed",
           series_table="datafeed.series", owned=False),
    # The Optimizer family (Projects/Engines/Optimizer), added 28.09.2026 with Engine 07. Its tables
    # describe themselves with COMMENT ON TABLE; it holds no series of its own.
    Source("simtech", "Optimizer", ("pcp",),
           engine_schema="pcp", feed_schema="datafeed",
           series_table=None, owned=False),
    # The eigentliCH project (Projects/Engines/eigentliCH_Engines), added 29.09.2026: the
    # lbs, report and chatbot engines and the `eigentlich` application schema. Its tables
    # describe themselves with COMMENT ON TABLE. `eigentlich` holds personal client data
    # (K1 to K3): the export reads only table names, column counts, table comments and
    # count(*), never a value, and no series reader runs here (series_table=None).
    Source("simtech", "eigentliCH_Engines", ("chatbot", "eigentlich", "lbs", "report"),
           engine_schema="eigentlich", feed_schema="datafeed",
           series_table=None, owned=False),
)


@dataclass(frozen=True)
class Record:
    """One catalogue row, whether it describes a series or a table."""

    name: str
    object_type: str          # series | instrument | table
    database: str
    project: str
    schema: str
    description: str
    engines: tuple[str, ...]
    # series only -- empty for a table
    unit: str = ""
    currency: str = ""
    magnitude: str = ""
    frequency: str = ""
    country: str = ""
    category: str = ""
    index_family: str = ""
    pull_code: str = ""
    source: str = ""
    origin_kind: str = ""
    quality_grade: str = ""
    stitched: bool = False
    first_period: str = ""
    last_period: str = ""
    observations: int = 0
    #: instrument only: which of the four roles it plays
    role: str = ""
    #: instrument only. Deliberately separate from `category`: a macro series categorised
    #: `equity` and an instrument whose asset class is `Equity` are different statements,
    #: and one column holding both would group them together in every view.
    asset_class: str = ""
    # table only
    columns: int = 0




def _config_for(source: Source):
    """A read-only connection config pointed at one catalogued database.

    **The catalogue is operator tooling, not an engine**, and it is the one thing that has
    to see across the whole server. Each engine role is confined to its own schemas by
    design, so running the export as one of them reads only that engine. The credentials
    come from ``SIMTECH_CATALOGUE_USER`` / ``SIMTECH_CATALOGUE_PASSWORD``, falling back to
    the configured connection, and the account needs read access and nothing else.

    Nothing here calls ``initialise``, so pointing at another project's database cannot
    create anything in it, and every statement is a SELECT.
    """
    base = dbconfig.load()
    user = os.environ.get("SIMTECH_CATALOGUE_USER", provision.CATALOGUE_ROLE)
    password = os.environ.get("SIMTECH_CATALOGUE_PASSWORD", provision.DEV_PASSWORD)
    return replace(base, dbname=source.dbname, user=user, password=password,
                   schema=source.engine_schema, datafeed_schema=source.feed_schema)


def _series_rich(conn, source: Source, schema: str, table: str) -> list[Record]:
    """Series from a registry that records the full metadata set."""
    rows = conn.execute(
        f"SELECT * FROM {schema}.{table} ORDER BY series_id"
    ).fetchall()
    return [
        Record(
            name=r["series_id"], object_type="series",
            database=source.dbname, project=source.project, schema=schema,
            description=r["description"] or r["name"],
            engines=engines_for(source.dbname, schema),
            unit=r["unit"], currency=r["currency"], magnitude=r["magnitude"],
            frequency=r["period"], country=r["country"], category=r["category"],
            index_family=r["index_family"] or "", pull_code=r["pull_code"] or "",
            source=r["source"], origin_kind=r["origin_kind"],
            quality_grade=r["quality_grade"], stitched=bool(r["is_stitched"]),
            first_period=r["first_period"] or "", last_period=r["last_period"] or "",
            observations=r["observation_count"],
        )
        for r in rows
    ]


#: The macro project writes `period` as a word rather than a code.
_PERIOD_CODE = {"annual": "A", "quarterly": "Q", "monthly": "M", "daily": "D",
                "weekly": "W"}


def _series_basic(conn, source: Source, schema: str, table: str) -> list[Record]:
    """Series from a registry that records only part of the metadata set.

    The macro project's `datafeed.series` carries `category`, `unit` and `period` but no
    currency, magnitude or country. What it does keep is one definition per series *and
    economy* in `series_definition.payload_json`: the Bloomberg ticker, the field, the
    currency, the import scale and a short label. The description is assembled from those
    facts and nothing else. Where the economies disagree, the disagreement is the
    description: a series that means seven different things across sixteen countries must
    say so rather than be summarised as one of them. Currency is filled only when every
    economy agrees; a mixed one comes back empty rather than guessed.
    """
    rows = conn.execute(
        f"SELECT series_id, category, unit, period, indices_json, matlab_sheet, "
        f"       matlab_column, description "
        f"FROM {schema}.{table} ORDER BY series_id"
    ).fetchall()

    counts = {
        r["series_id"]: r["n"]
        for r in conn.execute(
            f"SELECT series_id, count(*) AS n FROM {schema}.observation GROUP BY series_id"
        ).fetchall()
    }
    # The latest snapshot's definition per series and economy. The snapshots agree
    # today; taking the latest keeps that true when one day they do not.
    payloads: dict[str, list[dict]] = {}
    for r in conn.execute(
        f"SELECT DISTINCT ON (series_id, country) series_id, country, payload_json "
        f"FROM {schema}.series_definition "
        f"ORDER BY series_id, country, snapshot_id DESC"
    ).fetchall():
        payloads.setdefault(r["series_id"], []).append(db.loads(r["payload_json"]))

    out = []
    for r in rows:
        defs = payloads.get(r["series_id"], [])
        currencies = {d.get("currency") for d in defs}
        out.append(Record(
            name=r["series_id"], object_type="series",
            database=source.dbname, project=source.project, schema=schema,
            description=_describe_basic(r, defs),
            engines=engines_for(source.dbname, schema),
            unit=r["unit"] or "", category=r["category"] or "",
            currency=("none" if r["unit"] in _UNITLESS
                      else currencies.pop() if len(currencies) == 1 else ""),
            frequency=_PERIOD_CODE.get(r["period"], r["period"] or ""),
            pull_code="; ".join(f"{d['country']}: {d.get('pull_code', '')}"
                                for d in sorted(defs, key=lambda d: d["country"])),
            source=", ".join(sorted({d.get("source", "") for d in defs} - {""})),
            observations=counts.get(r["series_id"], 0),
        ))
    return out


#: Units that carry no currency, whatever the import recorded (Guide section 7.1: `none`
#: for a rate or a ratio). The macro payloads say USD for a CPI rate, which means nothing.
_UNITLESS = ("ratio", "rate", "index")

#: The macro import marks a missing Bloomberg series with this ticker.
_PLACEHOLDER_TICKER = "USD BGN Curncy"


def _describe_basic(row, defs: list[dict]) -> str:
    """One macro series in prose, from the definitions its own project stored.

    The registry's own plain-language line comes first (``datafeed.series.description``);
    the per-economy facts follow, because they are where a series is not like for like.
    """
    lead = (row.get("description") or "").strip()
    live = [d for d in defs if d.get("pull_code") != _PLACEHOLDER_TICKER
            and "placeholder" not in d.get("description", "")]
    dead = sorted(d["country"] for d in defs if d not in live)
    period = {"annual": "Annual", "quarterly": "Quarterly", "monthly": "Monthly",
              "daily": "Daily"}.get(row["period"], row["period"] or "")

    by_label: dict[str, list[str]] = {}
    for d in live:
        by_label.setdefault(d.get("description", "").strip(), []).append(d["country"])
    bits = []
    if len(by_label) == 1:
        label, countries = next(iter(by_label.items()))
        n = len(countries)
        bits.append(f'{label} ({period.lower()}), Bloomberg, for {n} '
                    f'{"economy" if n == 1 else "economies"}.')
    elif by_label:
        parts = [f'"{label}" ({", ".join(sorted(cs))})'
                 for label, cs in sorted(by_label.items(), key=lambda kv: -len(kv[1]))]
        bits.append(f"{period} Bloomberg series whose definition differs by economy: "
                    + "; ".join(parts) + ".")
    if dead:
        bits.append(f"No data for {', '.join(dead)}: the ticker is a placeholder.")

    tickers: dict[str, list[str]] = {}
    for d in live:
        tickers.setdefault(d.get("pull_code", ""), []).append(d["country"])
    shared = [f"{' and '.join(sorted(cs))} share {t}" for t, cs in tickers.items()
              if len(cs) > 1]
    if shared:
        bits.append("Same ticker for more than one economy: " + "; ".join(shared) + ".")

    currencies: dict[str, list[str]] = {}
    for d in live:
        currencies.setdefault(d.get("currency", ""), []).append(d["country"])
    if len(currencies) > 1 and row["unit"] not in _UNITLESS:
        bits.append("Currency differs by economy: " + "; ".join(
            f"{c} ({', '.join(sorted(cs))})" for c, cs in sorted(currencies.items())) + ".")
    scales = {d.get("magnitude") for d in live}
    if len(scales) > 1:
        bits.append("The scale factor applied on import differs by economy ("
                    + ", ".join(f"x{m:g}" for m in sorted(scales)) + ").")

    indices = db.loads(row["indices_json"] or "[]")
    if indices:
        bits.append("Feeds the HoNI " + ("indices " if len(indices) > 1 else "index ")
                    + ", ".join(indices) + ".")
    if row["matlab_sheet"]:
        bits.append(f"Imported from the {row['matlab_sheet']} sheet of the MATLAB ticker "
                    f"workbooks, column {row['matlab_column']}.")
    return " ".join(([lead] if lead else []) + bits)


#: macrofield's free-text units, mapped onto the catalogue's unit and currency vocabulary.
def _macrofield_unit(units: str) -> tuple[str, str]:
    u = units.lower()
    if "percent" in u or u == "rate":
        return "ratio", "none"
    if "persons" in u:
        return "count", "none"
    if "us dollar" in u:
        return "level", "USD"
    if u.startswith("eur"):
        return "level", "EUR"
    return "level", ""


def _series_macrofield(conn, source: Source, schema: str = "macrofield") -> list[Record]:
    """The series the three-body engine reads, from its own ``series_registry`` table.

    macrofield holds its own frozen snapshot until datafeed serves it, so its series are
    not in the feed's registry. It publishes its source catalogue as a table instead; the
    coverage comes from its newest snapshot's observations.
    """
    if not conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'series_registry'",
        (schema,),
    ).fetchone():
        return []
    latest = conn.execute(
        f"SELECT snapshot_id FROM {schema}.snapshot ORDER BY loaded_at DESC LIMIT 1").fetchone()
    coverage = {}
    if latest:
        coverage = {
            r["series_id"]: r for r in conn.execute(
                f"SELECT series_id, count(DISTINCT area) AS areas, count(value) AS n, "
                f"       min(year) FILTER (WHERE value IS NOT NULL) AS first, "
                f"       max(year) FILTER (WHERE value IS NOT NULL) AS last "
                f"FROM {schema}.observation WHERE snapshot_id = %s GROUP BY series_id",
                (latest["snapshot_id"],)).fetchall()
        }
    out = []
    for r in conn.execute(f"SELECT * FROM {schema}.series_registry ORDER BY series_id").fetchall():
        cov = coverage.get(r["series_id"])
        unit, currency = _macrofield_unit(r["units"])
        text = (f"{r['description']}. Units: {r['units']}. In the three-body model: "
                f"{r['model_role']} ({r['lead_lag']}"
                f"{'; a level error moves an economy against a threshold' if r['scale_critical'] else ''}).")
        if cov:
            text += (f" {cov['n']} values for {cov['areas']} areas in snapshot "
                     f"{latest['snapshot_id']}.")
        out.append(Record(
            name=r["series_id"], object_type="series",
            database=source.dbname, project=source.project, schema=schema,
            description=text, engines=engines_for(source.dbname, schema),
            unit=unit, currency=currency, frequency=r["frequency"], category="macro",
            pull_code=r["code"], source=r["provider"],
            first_period=str(cov["first"]) if cov and cov["first"] else "",
            last_period=str(cov["last"]) if cov and cov["last"] else "",
            observations=cov["n"] if cov else 0,
        ))
    return out


def _instruments(conn, source: Source) -> list[Record]:
    """The Fund Map register: one row per investable instrument.

    An instrument is a data series in its own right -- it carries monthly returns and an
    estimated profile -- so leaving it out of the catalogue would mean the catalogue covers
    what the engine *reads* but not what it *tracks*. The profile's coverage grade is the
    honest quality signal here: it reports the weakest method behind any of the 25 states.
    """
    schema = conn.config.schema
    rows = conn.execute(
        f"SELECT i.instrument_id, i.name, i.role, i.asset_class, i.currency, "
        f"       i.ticker, i.region_scope, i.region_geo, i.capital_type, "
        f"       i.proxy_symbol, i.proxy_grade, i.proxy_note, i.note, i.active, "
        f"       p.coverage, p.n_obs_total, "
        f"       h.n AS returns, h.first_period, h.last_period, h.sources "
        f"FROM {schema}.instrument i "
        # One profile per instrument: the newest calibration's. Joining every calibration
        # repeated each instrument once per run (54 duplicates after the second one).
        f"LEFT JOIN (SELECT DISTINCT ON (ip.instrument_id) ip.instrument_id, ip.coverage, "
        f"                  ip.n_obs_total "
        f"           FROM {schema}.instrument_profile ip "
        f"           JOIN {schema}.calibration c USING (calibration_id) "
        f"           ORDER BY ip.instrument_id, c.created_at DESC) p USING (instrument_id) "
        f"LEFT JOIN (SELECT instrument_id, count(*) AS n, min(period) AS first_period, "
        f"                  max(period) AS last_period, "
        f"                  string_agg(DISTINCT source, ', ') AS sources "
        f"           FROM {schema}.instrument_return GROUP BY instrument_id) h "
        f"       USING (instrument_id) "
        f"ORDER BY i.instrument_id"
    ).fetchall()
    return [
        Record(
            name=r["instrument_id"], object_type="instrument",
            database=source.dbname, project=source.project, schema=schema,
            description=_describe_instrument(r),
            engines=engines_for(source.dbname, schema),
            asset_class=r["asset_class"] or "", currency=r["currency"] or "",
            frequency="M", unit="return_simple", magnitude="decimal",
            pull_code=r["proxy_symbol"] or r["ticker"] or "",
            source=r["ticker"] or "",
            quality_grade=r["proxy_grade"] or "",
            first_period=r["first_period"] or "", last_period=r["last_period"] or "",
            observations=r["n_obs_total"] or 0,
            role=r["role"] or "",
        )
        for r in rows
    ]


#: The import wrote this into every note, and it went stale when proxy returns arrived.
_STALE_NO_HISTORY = "No return history: the profile is seeded from the role."


def _describe_instrument(r) -> str:
    """One register entry in prose: what it is, what stands in for it, what it rests on."""
    region = r["region_geo"] if r["region_geo"] not in (None, "Others") else r["region_scope"]
    what = ", ".join(x for x in (r["asset_class"], region, r["currency"]) if x)
    bits = [f"{r['name']}: {what}, {r['role']} role."]
    if r["ticker"]:
        bits.append(f"Register index {r['ticker']}.")
    if r["proxy_symbol"]:
        proxy = f"Public proxy {r['proxy_symbol']}, graded {r['proxy_grade']}"
        bits.append(f"{proxy}: {r['proxy_note']}" if r["proxy_note"] else f"{proxy}.")
    if r["returns"]:
        bits.append(f"{r['returns']} monthly returns, {r['first_period']} to "
                    f"{r['last_period']} ({r['sources']}).")
    else:
        bits.append("No return history: the profile is seeded from the role.")
    note = (r["note"] or "").replace(_STALE_NO_HISTORY, "").strip()
    if note:
        bits.append(" ".join(note.split()))
    if r["coverage"]:
        bits.append(f"Profile coverage {r['coverage']}, the weakest method behind any "
                    f"of its 25 states.")
    if not r["active"]:
        bits.append("Not active.")
    return " ".join(bits)


def _purpose_for(source: Source, schema: str, table: str, feed_schema: str) -> str:
    """The curated purpose, looked up under the canonical schema name.

    Tests run against throwaway schemas with random names, so the lookup falls back to
    whichever role the schema is playing rather than its literal name.
    """
    direct = TABLE_PURPOSE.get(f"{schema}.{table}")
    if direct and source.owned:
        return direct
    if not source.owned:
        return ""
    role = "datafeed" if schema == feed_schema else "instruments"
    return TABLE_PURPOSE.get(f"{role}.{table}", "")


def _foreign_purpose(source: Source, schema: str, table: str, columns: int) -> str:
    """A factual placeholder for a table another project owns.

    Not a guess at what it is for. It says what is measurably true and names the gap, so
    the catalogue shows an undocumented table rather than quietly hiding one behind a
    blank cell.
    """
    return (f"Table in the {schema} schema of the {source.project} project, "
            f"{columns} columns. Purpose not documented by that project.")


def _comments(conn, schemas) -> dict[tuple[str, str], str]:
    """`COMMENT ON TABLE`, where the owning project wrote one.

    Better than any placeholder this repository can invent, and it puts the description
    where the people who built the table will maintain it.
    """
    rows = conn.execute(
        "SELECT n.nspname AS s, c.relname AS t, "
        "       obj_description(c.oid, 'pg_class') AS note "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY(%s) AND c.relkind = 'r' "
        "  AND obj_description(c.oid, 'pg_class') IS NOT NULL",
        (list(schemas),),
    ).fetchall()
    return {(r["s"], r["t"]): r["note"].strip() for r in rows if r["note"].strip()}


def _tables(conn, source: Source, feed_schema: str, schemas: tuple[str, ...]) -> list[Record]:
    rows = conn.execute(
        "SELECT t.table_schema AS s, t.table_name AS n, "
        "  (SELECT count(*) FROM information_schema.columns c "
        "    WHERE c.table_schema = t.table_schema AND c.table_name = t.table_name) AS cols "
        "FROM information_schema.tables t "
        "WHERE t.table_schema = ANY(%s) AND t.table_type = 'BASE TABLE' "
        "ORDER BY t.table_schema, t.table_name",
        (list(schemas),),
    ).fetchall()
    noted = _comments(conn, schemas)
    out = []
    for r in rows:
        counted = conn.execute(
            f'SELECT count(*) AS n FROM "{r["s"]}"."{r["n"]}"'
        ).fetchone()["n"]
        out.append(Record(
            name=f"{r['s']}.{r['n']}", object_type="table",
            database=source.dbname, project=source.project, schema=r["s"],
            description=(_purpose_for(source, r["s"], r["n"], feed_schema)
                         or noted.get((r["s"], r["n"]), "")
                         or ("" if source.owned
                             else _foreign_purpose(source, r["s"], r["n"], r["cols"]))),
            engines=engines_for(source.dbname, r["s"]),
            columns=r["cols"], observations=counted,
        ))
    return out


def export() -> list[Record]:
    """This repository's own store: series first, then tables.

    Kept separate from ``export_all`` so the tests can insist on a purpose for every table
    here without demanding one for another project's schema.
    """
    with db.session() as conn:
        feed = conn.config.datafeed_schema
        engine = conn.config.schema
        source = CATALOGUE[0]
        series = _series_rich(conn, source, feed, "series_definition")
        return (series + _instruments(conn, source)
                + _tables(conn, source, feed, (engine, feed)))


def export_all() -> list[Record]:
    """Every catalogued database on the server, this project's and the others'."""
    out: list[Record] = []
    for source in CATALOGUE:
        cfg = _config_for(source)
        with db.session(cfg) as conn:
            present = {
                r["table_schema"] for r in conn.execute(
                    "SELECT DISTINCT table_schema FROM information_schema.tables "
                    "WHERE table_schema = ANY(%s)", (list(source.schemas),)
                ).fetchall()
            }
            _check_nothing_hidden(cfg, source, present)
            if not present:
                # `information_schema` hides what the connected role cannot see, so a
                # missing grant looks exactly like an empty database and the catalogue
                # would quietly shrink. It has to be an error, not a shrug.
                raise PermissionError(
                    f"{source.dbname} returned no schemas for {list(source.schemas)} as "
                    f"user {conn.config.user!r}. Either the database is gone or the role "
                    f"lacks USAGE. Set SIMTECH_CATALOGUE_USER / "
                    f"SIMTECH_CATALOGUE_PASSWORD to an account that can read the whole "
                    f"server; the catalogue is the one tool that must see across engines."
                )
            if source.series_table:
                schema, table = source.series_table.split(".", 1)
                if schema in present:
                    reader = _series_rich if source.owned else _series_basic
                    out.extend(reader(conn, source, schema, table))
            if "macrofield" in present:
                out.extend(_series_macrofield(conn, source))
            if source.owned:
                out.extend(_instruments(conn, source))
            out.extend(_tables(conn, source, cfg.datafeed_schema, tuple(sorted(present))))
    return out


#: The catalogue's column order, and the property names it creates on import.
CSV_COLUMNS = (
    "Name", "Object", "Project", "Database", "Schema", "Description", "Category",
    "Asset class", "Role", "Unit", "Currency", "Magnitude", "Frequency", "Country", "Index family",
    "Pull code", "Source", "Origin", "Quality", "Stitched", "First period",
    "Last period", "Rows", "Columns", "Engines",
)


def _display_name(record: Record, ambiguous: set[str]) -> str:
    """The title a row carries in the catalogue.

    Two databases both have a schema called `datafeed`, so four table names appear twice.
    Those are qualified with the database; everything else keeps its short name, which is
    what an existing row in the catalogue is already called and what a CSV merge matches on.
    """
    if (record.object_type == "table" and record.name in ambiguous
            and record.database == "simtech"):
        return f"{record.database}.{record.name}"
    return record.name


def to_csv(records: list[Record]) -> str:
    """The catalogue as CSV, for Notion's `Merge with CSV` import.

    Needed because a database created in the Notion UI cannot be given properties through
    the API: its data source is invisible to the schema endpoint however it is shared. A
    CSV import creates the columns from these headers and fills the rows in one action.
    """
    seen: dict[str, int] = {}
    for r in records:
        if r.object_type == "table":
            seen[r.name] = seen.get(r.name, 0) + 1
    ambiguous = {name for name, n in seen.items() if n > 1}

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator=chr(10))
    writer.writeheader()
    for r in records:
        writer.writerow({
            "Name": _display_name(r, ambiguous),
            "Object": r.object_type,
            "Project": r.project,
            "Database": r.database,
            "Schema": r.schema,
            "Description": r.description,
            "Category": r.category,
            "Asset class": r.asset_class,
            "Role": r.role,
            "Unit": r.unit,
            "Currency": r.currency,
            "Magnitude": r.magnitude,
            "Frequency": r.frequency,
            "Country": r.country,
            "Index family": r.index_family,
            "Pull code": r.pull_code,
            "Source": r.source,
            "Origin": r.origin_kind,
            "Quality": r.quality_grade,
            "Stitched": "Yes" if r.stitched else "",
            "First period": r.first_period,
            "Last period": r.last_period,
            "Rows": r.observations or "",
            "Columns": r.columns or "",
            "Engines": ", ".join(r.engines),
        })
    return buffer.getvalue()


def _check_nothing_hidden(cfg, source: Source, present) -> None:
    """Refuse to publish a catalogue that is quietly short.

    The empty-list check below catches a role with no access at all. It does **not**
    catch the more likely case: a role that can see most of a schema but not the tables
    an engine added afterwards, because `ALTER DEFAULT PRIVILEGES` applies only to
    objects created by the role that set it. That happened -- two new `mrs` tables were
    invisible and the export reported three instead of five, with no error.

    So the visible count is compared against an administrator's count. A catalogue that
    is missing rows is worse than one that fails, because nobody goes looking for what
    it does not mention.
    """
    from store import provision

    admin = provision.admin(dbconfig.load())
    with db.session(replace(admin, dbname=source.dbname,
                            schema=source.engine_schema,
                            datafeed_schema=source.feed_schema)) as truth:
        expected = {
            (r["table_schema"], r["table_name"]) for r in truth.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
                (list(source.schemas),)
            ).fetchall()
        }
    if not expected:
        return
    with db.session(cfg) as seen_conn:
        seen = {
            (r["table_schema"], r["table_name"]) for r in seen_conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
                (list(source.schemas),)
            ).fetchall()
        }
    hidden = sorted(expected - seen)
    if hidden:
        raise PermissionError(
            f"{len(hidden)} table(s) in {source.dbname} are invisible to the catalogue "
            f"role and would have been left out silently: {hidden}. Run "
            f"`python -m store.provision`, which reapplies the grants and sets default "
            f"privileges for every role that owns a schema."
        )


def undescribed(records: list[Record]) -> list[str]:
    """Tables owned by this repository that reached the export without a purpose.

    Another project's tables are exempt: this repository cannot honestly describe what it
    did not build, and a guessed purpose in a catalogue is worse than a blank one.
    """
    owned = {s.dbname for s in CATALOGUE if s.owned}
    return [r.name for r in records
            if r.object_type == "table" and r.database in owned
            and not r.description.strip()]


if __name__ == "__main__":
    import sys

    records = export_all() if "--all" in sys.argv else export()
    missing = undescribed(records)
    if missing:
        print(f"WARNING: no purpose recorded for {missing}", file=sys.stderr)
    if "--csv" in sys.argv:
        out = pathlib.Path("docs/sql_metadata.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_csv(records), encoding="utf-8-sig")
        print(f"{len(records)} rows -> {out}")
    elif "--json" in sys.argv:
        print(json.dumps([asdict(r) for r in records], indent=1, default=list))
    else:
        for source in CATALOGUE:
            mine = [r for r in records if r.project == source.project]
            if not mine:
                continue
            counts = {}
            for r in mine:
                counts[r.object_type] = counts.get(r.object_type, 0) + 1
            flag = "" if source.owned else "   (read-only, another project)"
            print(f"{source.project:14} {source.dbname:10} "
                  f"{counts.get('series', 0):>4} series "
                  f"{counts.get('instrument', 0):>4} instruments "
                  f"{counts.get('table', 0):>3} tables{flag}")
        print(f"{'total':22} {len(records):>4} records")
