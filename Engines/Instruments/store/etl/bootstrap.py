"""Build the store from the two sources, in one command.

    python -m store.etl.bootstrap

    python -m store.etl.bootstrap --create-database   # the first time

This is the only step that touches a spreadsheet or a raw CSV. Everything afterwards --
the engine, the API, the test bench -- reads the database. Re-running it is safe: every
write is an upsert keyed on content, so a second run against unchanged inputs produces the
same calibration id and changes nothing.

The two sources are configurable by environment variable so the script can run against a
copy, but they default to where they actually live on the build machine:

    INSTRUMENTS_ECN_DIR    the Steiner workbooks   (Model/ecn_model)
    INSTRUMENTS_FEED_CSV   the monthly andersCH report
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from engines.fund_map.calibrate import Estimator
from engines.fund_map.indicators import build_indicators
from engines.fund_map.phases import classify_series
from engines.fund_map.service import (
    UNIVERSE_VERSION,
    estimate_and_save,
    record_run,
    run_calibration,
    save_calibration,
    save_state_map,
)
from engines.fund_map.state_map import build_state_map
from store import db
from store.config import redacted_url
from store.etl.long_record import iter_rows, read_long_record
from store.etl.universe import (DEACTIVATED, DEFAULT_UNIVERSE_JSON, REGION_CORRECTIONS,
                                ROLE_OVERRIDES, TICKER_REPLACEMENTS, read_universe)
from store.etl.market_signal import (
    instrument_names,
    read_market_risk_signal,
    recover_instrument_returns,
    split_sections,
)

DEFAULT_ECN_DIR = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Knowledge_Center\Published"
    r"\Dynamic Investment\Model\ecn_model"
)
DEFAULT_FEED_CSV = Path(
    r"C:\Users\nicol\Desktop\SIM_NAS\Projects\andersCH-prototype_old"
    r"\andersCH-prototype_old\data\feeds\2026-08-01_andersCH-report.csv"
)


def slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return f"INS-{out.strip('-')}"


def main(argv: list[str] | None = None) -> int:
    """Build the store against the configured database.

    ``--create-database`` creates the engine's database first, which is needed once. The
    schema is created either way, so a second run is a no-op against unchanged inputs.
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    create_database = "--create-database" in argv

    ecn_dir = Path(os.environ.get("INSTRUMENTS_ECN_DIR", DEFAULT_ECN_DIR))
    feed_csv = Path(os.environ.get("INSTRUMENTS_FEED_CSV", DEFAULT_FEED_CSV))
    config = db.get_config()

    for path, what in ((ecn_dir, "the Steiner workbook directory"), (feed_csv, "the monthly feed")):
        if not path.exists():
            print(f"error: {what} was not found at {path}", file=sys.stderr)
            return 2

    started = time.perf_counter()
    print(f"store: {redacted_url(config)}")
    print(f"  config from: {', '.join(config.sources)}")
    if create_database:
        try:
            made = db.create_database(config)
        except Exception as exc:  # noqa: BLE001 - the message matters more than the type
            print(f"error: could not create the database: {exc}", file=sys.stderr)
            print(
                "  Many managed providers forbid CREATE DATABASE. Point dbname at the "
                "database they gave you; the schema still keeps the tables apart.",
                file=sys.stderr,
            )
            return 3
        print(f"  database {config.dbname}: {'created' if made else 'already present'}")

    try:
        db.initialise()
    except Exception as exc:  # noqa: BLE001
        print(f"error: could not reach the store: {exc}", file=sys.stderr)
        print(
            f"  Tried {redacted_url(config)}\n"
            f"  Is the container up?  docker compose ps\n"
            f"  First run?            python -m store.etl.bootstrap --create-database",
            file=sys.stderr,
        )
        return 3

    print("reading the long annual record ...")
    record = read_long_record(ecn_dir)
    print(f"  {len(record)} series, {sum(len(s.values) for s in record.values())} observations")

    print("reading the monthly feed ...")
    sections = split_sections(feed_csv)
    signal = read_market_risk_signal(sections)
    kept, dropped = recover_instrument_returns(sections)
    print(f"  {len(signal)} signal months {signal[0].period}..{signal[-1].period}")
    print(f"  {len(kept)} recovered instrument-months kept, {len(dropped)} below the weight floor")

    print("calibrating ...")
    result = run_calibration(record, estimator=Estimator.PLAIN_MEAN)
    environment = build_indicators(record)
    phases = classify_series(environment.cycle)
    environment_rows = [
        (environment.first_year + i, environment.cycle[i], phases[i], environment.inflation[i])
        for i in range(len(environment.cycle))
    ]
    print(f"  {result.calibration_id}")
    print(f"  phases: {result.timeline.counts()}")

    with db.session() as conn:
        # Provenance first: long_series references source_file.
        for spec_key, series in record.items():
            db.register_source(
                conn,
                name=series.source_file,
                path=ecn_dir / series.source_file,
                note=series.note,
            )
        conn.executemany(
            db.upsert(
                "long_series",
                (
                    "series_key", "year", "value", "source_file",
                ),
                ("series_key", "year",),
            ),
            [(k, y, v, record[k].source_file) for k, y, v in iter_rows(record)],
        )
        db.register_source(
            conn, name=DEFAULT_UNIVERSE_JSON.name + " (universe)",
            path=DEFAULT_UNIVERSE_JSON,
            note="The prototype's published 54-instrument register. Classification only "
                 "-- its profiles were all seeded and are not imported.",
        )
        db.register_source(
            conn, name=feed_csv.name, path=feed_csv,
            note="Monthly andersCH report. Dates corrected by -1 month on load; "
                 "see store/etl/market_signal.py.",
        )

        conn.executemany(
            db.upsert(
                "environment_indicator",
                (
                    "year", "name", "residual", "standardised",
                ),
                ("year", "name",),
            ),
            [
                (environment.first_year + i, name, environment.indicators[name][i],
                 environment.standardised[name][i])
                for name in environment.standardised
                for i in range(len(environment.cycle))
            ],
        )

        save_calibration(conn, result, environment_rows)

        conn.executemany(
            db.upsert(
                "market_risk_signal",
                (
                    "period", "state", "probability",
                ),
                ("period", "state",),
            ),
            [(m.period, i + 1, p) for m in signal for i, p in enumerate(m.probabilities)],
        )
        conn.executemany(
            db.upsert(
                "market_risk_month",
                (
                    "period", "modal_state", "mean_state", "raw_sum", "in_tolerance",
                ),
                ("period",),
            ),
            [(m.period, m.modal_state, m.mean_state, m.raw_sum, int(m.in_tolerance))
             for m in signal],
        )

        state_map = build_state_map(
            [m.probabilities for m in signal], environment.cycle,
            signal_first=signal[0].period, signal_last=signal[-1].period,
        )
        map_id = save_state_map(conn, state_map, result.calibration_id)
        print(f"  state map {map_id}")

        # The register: the full published universe, not only the ten with data.
        #
        # Keeping all 54 matters. The register is a versioned input (manual section 11.4)
        # and the Portfolio Optimiser's objective has a floor that scales with its size,
        # so a universe truncated to whatever happens to have a price history would change
        # measured leverage. The 44 without history are registered and carry a seeded
        # profile that says so; they are not hidden, and they are not pretended into
        # existence either.
        now = db.utc_now()
        registry = read_universe()
        with_data = set(instrument_names(sections))
        print(f"  register: {len(registry)} instruments, {len(with_data)} with return history")
        overrides = [i for i in registry if i.overridden]
        if overrides:
            print(f"  role overrides against the prototype: {len(overrides)}")
            for i in overrides:
                print(f"    {i.name:<30} {i.source_role} -> {i.role}")
        inactive = [i.name for i in registry if not i.active]
        if inactive:
            print(f"  deactivated (kept, not published): {', '.join(inactive)}")
        missing = sorted(with_data - {i.name for i in registry})
        if missing:
            print(f"  warning: the feed carries {missing} which the register does not list")

        # The upsert below is DO NOTHING, so that re-running never clobbers a role or a
        # note edited through the API. A *correction* is the opposite case: it exists
        # precisely to override the register, so it has to be applied every time or a
        # decision taken today silently fails to reach a database created yesterday.
        for instrument in registry:
            if instrument.name not in TICKER_REPLACEMENTS and                     instrument.name not in REGION_CORRECTIONS:
                continue
            conn.execute(
                "UPDATE instrument SET ticker = %s, region_geo = %s, updated_at = %s "
                "WHERE instrument_id = %s AND (ticker IS DISTINCT FROM %s "
                "      OR region_geo IS DISTINCT FROM %s)",
                (instrument.ticker, instrument.region_geo, now, slug(instrument.name),
                 instrument.ticker, instrument.region_geo),
            )

        # The country exposure is a register decision (`COUNTRY_EXPOSURE`) like a correction:
        # applied every time, so a decision taken today reaches a database built yesterday.
        for instrument in registry:
            conn.execute(
                "UPDATE instrument SET countries_json = %s, updated_at = %s "
                "WHERE instrument_id = %s AND countries_json IS DISTINCT FROM %s",
                (json.dumps(list(instrument.countries)), now, slug(instrument.name),
                 json.dumps(list(instrument.countries))),
            )

        def note_for(i) -> str:
            # Whether an instrument has a return history is not written here: proxy
            # returns arrive in a later step, so a sentence saying "none" went stale.
            # instrument_return holds the answer, and the catalogue reads it from there.
            return i.note + (
                "  Returns are recovered from the monthly report as "
                "contribution/weight and are conditional on the manager having held "
                "the instrument -- not an unconditional index series."
                if i.name in with_data else ""
            )

        # Role overrides and deactivations are register decisions too, and reach a store
        # built before them the same way. Before 29 September 2026 they were written only
        # on first insert, so the CIO's Digital Assets decision of 27 September never
        # reached the live store (it still read Stabilisation there). Only the instruments
        # a decision names are touched; `active` is only ever cleared here, never set, so
        # an instrument retired through the API stays retired.
        for instrument in registry:
            if instrument.name not in ROLE_OVERRIDES and instrument.name not in DEACTIVATED:
                continue
            active_clause = "active = 0, " if not instrument.active else ""
            conn.execute(
                f"UPDATE instrument SET role = %s, {active_clause}note = %s, updated_at = %s "
                "WHERE instrument_id = %s AND (role IS DISTINCT FROM %s "
                "      OR note IS DISTINCT FROM %s"
                + ("      OR active <> 0" if not instrument.active else "") + ")",
                (instrument.role, note_for(instrument), now, slug(instrument.name),
                 instrument.role, note_for(instrument)),
            )

        conn.executemany(
            db.upsert(
                "instrument",
                (
                    "instrument_id", "name", "ticker", "role", "asset_class",
                    "region_scope", "region_geo", "capital_type", "currency", "liquidity",
                    "countries_json", "active", "created_at", "updated_at", "note",
                ),
                ("instrument_id",),
                # DO NOTHING: re-running the bootstrap must not overwrite a role or a note
                # that has since been edited through the API.
                update=(),
            ),
            [
                (slug(i.name), i.name, i.ticker, i.role, i.asset_class, i.region_scope,
                 i.region_geo, i.capital_type, i.currency, i.liquidity,
                 json.dumps(list(i.countries)), int(i.active), now, now, note_for(i))
                for i in registry
            ],
        )
        conn.executemany(
            db.upsert(
                "instrument_return",
                (
                    "instrument_id", "period", "value", "source", "ingested_at",
                ),
                ("instrument_id", "period",),
            ),
            [(slug(r.instrument), r.period, r.value, "andersch-report:recovered", now)
             for r in kept],
        )

        print("estimating instrument profiles ...")
        # Two passes: the first gives every instrument a profile from its own data, the
        # second lets a short-history instrument borrow from a peer that now has one.
        for _ in range(2):
            for row in conn.execute("SELECT instrument_id FROM instrument ORDER BY name"):
                estimate_and_save(conn, row["instrument_id"], result.calibration_id)

        for row in conn.execute(
            "SELECT i.name, p.coverage, p.n_obs_total, p.borrowed_from, p.match_score FROM "
            "instrument i JOIN instrument_profile p USING (instrument_id) WHERE "
            "p.calibration_id = %s ORDER BY i.name",
            (result.calibration_id,),
        ):
            borrowed = ""
            if row["borrowed_from"]:
                borrowed = f"  <- {row['borrowed_from']} (r={row['match_score']:.2f})"
            print(f"  {row['name']:<30} {row['coverage']:<22} n={row['n_obs_total']:<4}{borrowed}")

        record_run(
            conn, engine="bootstrap",
            inputs={"ecn_dir": str(ecn_dir), "feed": feed_csv.name,
                    "universe_version": UNIVERSE_VERSION},
            outputs={"calibration_id": result.calibration_id, "state_map_id": map_id},
            started=started,
        )

    print(f"done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
