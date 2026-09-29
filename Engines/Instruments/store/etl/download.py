"""Download public proxy histories for the registered instruments.

    python -m store.etl.download            # only those with no history
    python -m store.etl.download --all      # every mappable instrument
    python -m store.etl.download --dry-run  # show the plan, fetch nothing

**This is the only module in the project that touches the network**, and it is a separate
command rather than part of the bootstrap on purpose: rebuilding the store must stay
offline and reproducible, and a download is neither. Run it when you want to refresh the
proxy histories, and the bootstrap afterwards will use whatever is in the store.

Everything written here is labelled ``internet:yahoo`` at source and carries the proxy's
grade on the instrument row, so nothing downloaded can be mistaken for a house series.
"""

from __future__ import annotations

import sys
import time

from engines.fund_map import service
from feeds import cboe, yahoo
from feeds.proxy_map import PROXIES, Proxy
from store import db
from store.etl.bootstrap import slug

SOURCE_PREFIX = "yahoo"

#: One proxy per symbol is enough to know its source; several instruments may share one.
PROXIES_BY_SYMBOL: dict[str, Proxy] = {p.symbol: p for p in PROXIES.values() if p.symbol}


def plan(conn: db.Connection, *, everything: bool) -> list[tuple[str, str, Proxy]]:
    """Which instruments to fetch, as ``(instrument_id, name, proxy)``."""
    rows = conn.execute(
        "SELECT i.instrument_id, i.name, COUNT(r.period) AS months "
        "FROM instrument i LEFT JOIN instrument_return r USING (instrument_id) "
        "GROUP BY i.instrument_id, i.name ORDER BY i.name"
    ).fetchall()
    out = []
    for row in rows:
        if not everything and row["months"]:
            continue
        proxy = PROXIES.get(row["name"])
        if proxy is None or not proxy.usable:
            continue
        out.append((row["instrument_id"], row["name"], proxy))
    return out


def _withdraw_unusable(conn, now) -> dict[str, int]:
    """Clear instruments whose proxy has been withdrawn.

    **Only handling the additive case is how stale data survives a decision.** This
    routine used to update the instruments that *have* a usable proxy and touch nothing
    else, so re-grading one to `none` changed nothing at all: the old symbol, the old
    grade and the old monthly returns stayed exactly where they were, and the register
    went on reporting a measurement the proxy map had just retracted.

    Returns from the monthly report are left alone. Only rows this module wrote -- those
    whose source carries the proxy prefix -- are removed, because a withdrawn public
    proxy says nothing about an instrument's own recovered history.
    """
    withdrawn = {
        name for name, proxy in PROXIES.items() if not proxy.usable
    }
    if not withdrawn:
        return {}

    rows = conn.execute(
        "SELECT instrument_id, name FROM instrument "
        "WHERE coalesce(proxy_symbol, '') <> '' OR coalesce(proxy_grade, '') <> ''"
    ).fetchall()

    removed: dict[str, int] = {}
    for row in rows:
        if row["name"] not in withdrawn:
            continue
        deleted = conn.execute(
            "DELETE FROM instrument_return WHERE instrument_id = %s "
            "AND (source LIKE %s OR source LIKE %s) RETURNING period",
            (row["instrument_id"], f"{SOURCE_PREFIX}:%", "cboe:%"),
        ).fetchall()
        conn.execute(
            "UPDATE instrument SET proxy_symbol = NULL, proxy_grade = NULL, "
            "proxy_note = %s, updated_at = %s WHERE instrument_id = %s",
            (PROXIES[row["name"]].note, now, row["instrument_id"]),
        )
        removed[row["instrument_id"]] = len(deleted)
    return removed


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    everything = "--all" in argv
    dry_run = "--dry-run" in argv

    started = time.perf_counter()
    with db.session() as conn:
        targets = plan(conn, everything=everything)
        unmapped = [
            r["name"]
            for r in conn.execute("SELECT name FROM instrument ORDER BY name")
            if not (PROXIES.get(r["name"]) and PROXIES[r["name"]].usable)
        ]

    print(f"to fetch: {len(targets)} instruments")
    grades: dict[str, int] = {}
    for _, name, proxy in targets:
        grades[proxy.grade] = grades.get(proxy.grade, 0) + 1
        print(f"  {name:<32} {proxy.symbol:<9} {proxy.grade}")
    print(f"  grades: {grades}")
    print(f"\nno defensible proxy ({len(unmapped)}): {', '.join(unmapped)}")
    if dry_run:
        return 0

    # **Before the early return, not after it.** Withdrawing a proxy is a change in
    # its own right. On a run with nothing new to fetch the old code returned below
    # and left the retracted symbol, grade and returns exactly where they were.
    with db.session() as conn:
        now = db.utc_now()
        pruned = _withdraw_unusable(conn, now)

        # Refresh the grade and note on every instrument with a usable proxy, whether or
        # not this run fetches it. The update used to be part of the fetch loop, so
        # re-grading an instrument whose returns were already present changed nothing.
        for name, proxy in PROXIES.items():
            if not proxy.usable:
                continue
            conn.execute(
                "UPDATE instrument SET proxy_symbol = %s, proxy_grade = %s, "
                "proxy_note = %s, updated_at = %s WHERE name = %s "
                "AND (proxy_symbol IS DISTINCT FROM %s OR proxy_grade IS DISTINCT FROM %s "
                "     OR proxy_note IS DISTINCT FROM %s)",
                (proxy.symbol, proxy.grade, proxy.note, now, name,
                 proxy.symbol, proxy.grade, proxy.note),
            )
    for instrument_id, rows in pruned.items():
        print(f"  withdrawn: {instrument_id}, proxy cleared, "
              f"{rows} proxy return(s) removed")

    if not targets:
        print("\nnothing to do.")
        return 0

    print("\nfetching ...")
    symbols = [p.symbol for _, _, p in targets if p.symbol]

    def progress(symbol, series, error):
        if error:
            print(f"  {symbol:<9} FAILED  {error}")
        else:
            print(f"  {symbol:<9} {series.months:>4} months  "
                  f"{series.first_period}..{series.last_period}  {series.currency}")

    series, failures = yahoo.fetch_many(
        [s for s in symbols if PROXIES_BY_SYMBOL[s].source == "yahoo"], on_progress=progress)
    # A Cboe index (`proxy_map.CBOE_SYMBOLS`) is read from Cboe's own history file.
    for symbol in [s for s in symbols if PROXIES_BY_SYMBOL[s].source == "cboe"]:
        try:
            series[symbol] = cboe.fetch(symbol)
            progress(symbol, series[symbol], None)
        except yahoo.FeedError as exc:
            failures[symbol] = str(exc)
            progress(symbol, None, str(exc))

    now = db.utc_now()
    written = 0
    with db.session() as conn:
        pruned = _withdraw_unusable(conn, now)
        if pruned:
            for instrument_id, rows in pruned.items():
                print(f"  withdrawn: {instrument_id} lost its proxy, {rows} row(s) removed")

        for instrument_id, name, proxy in targets:
            fetched = series.get(proxy.symbol or "")
            if fetched is None:
                continue
            conn.execute(
                "UPDATE instrument SET proxy_symbol = %s, proxy_grade = %s, "
                "proxy_note = %s, updated_at = %s WHERE instrument_id = %s",
                (proxy.symbol, proxy.grade, proxy.note, now, instrument_id),
            )
            conn.executemany(
                db.upsert(
                    "instrument_return",
                    ("instrument_id", "period", "value", "source", "ingested_at"),
                    ("instrument_id", "period"),
                ),
                [
                    (instrument_id, period, value,
                     f"{proxy.source}:{proxy.symbol}:{proxy.grade}", now)
                    for period, value in sorted(fetched.returns.items())
                ],
            )
            written += len(fetched.returns)

        service.record_run(
            conn, engine="download",
            inputs={"targets": len(targets), "symbols": len(symbols),
                    "mode": "all" if everything else "missing-only"},
            outputs={"fetched": len(series), "failed": len(failures), "rows": written},
            started=started,
        )

    print(f"\nwrote {written} instrument-months for {len(series)} symbols")
    if failures:
        print(f"failed ({len(failures)}):")
        for symbol, why in failures.items():
            print(f"  {symbol}: {why}")
    print(f"done in {time.perf_counter() - started:.1f}s")
    print("\nNow re-estimate:  python -m store.etl.bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
