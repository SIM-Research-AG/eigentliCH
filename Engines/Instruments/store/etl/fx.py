"""Load the two exchange rates that let every return be read in CHF, EUR or USD (D-01).

    python -m store.etl.fx              # fetch and store
    python -m store.etl.fx --dry-run    # fetch and print, store nothing

Two month-end rates span the three currencies: USD in CHF and EUR in CHF. They are stored
in the engine's feed schema as price levels, nominal and unconverted, beside the series
they will convert; the conversion itself happens at the point of use
(``engines/fund_map/currency.py``) and is never written back.

**Source and reach.** Yahoo Finance, through ``feeds/yahoo.py``, the only network code in
the project: ``CHF=X`` (CHF per USD) and ``EURCHF=X`` (CHF per EUR), monthly bars whose
close is the last trading day of the month. They reach back to 2003, which covers every
instrument history in the register (the earliest proxy returns start in 1993, but the
signal every estimator tags against starts in 2006-08). The long annual record 1870-2020 is
US data and is not converted: JST Macrohistory R6 would be the source for that and is not
loaded (HANDOVER section 5).

Like ``store.etl.download`` this is a separate command, not part of the bootstrap, so that
rebuilding the store stays offline and reproducible.
"""

from __future__ import annotations

import sys
import time

from engines.fund_map import service
from engines.fund_map.currency import FX_SERIES
from feeds import yahoo
from store import db
from store.etl.datafeed import upsert_series

#: series id -> (Yahoo symbol, name, description)
SYMBOLS: dict[str, tuple[str, str, str]] = {
    "fx.USDCHF": ("CHF=X", "US dollar in Swiss francs, month end",
                  "Price of one US dollar in Swiss francs at the last trading day of the "
                  "month. Used to read USD-quoted proxy returns in CHF or EUR, and CHF "
                  "returns in USD, at the point of use."),
    "fx.EURCHF": ("EURCHF=X", "Euro in Swiss francs, month end",
                  "Price of one euro in Swiss francs at the last trading day of the month. "
                  "With the dollar rate it spans CHF, EUR and USD, so any of the three can "
                  "be converted into any other."),
}


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    dry_run = "--dry-run" in argv
    started = time.perf_counter()
    if set(SYMBOLS) != set(FX_SERIES):
        raise SystemExit("store.etl.fx and engines.fund_map.currency disagree on the series")

    fetched: dict[str, yahoo.MonthlySeries] = {}
    for index, (series_id, (symbol, _, _)) in enumerate(SYMBOLS.items()):
        if index:
            time.sleep(yahoo.THROTTLE_SECONDS)
        fetched[series_id] = yahoo.fetch(symbol)
        s = fetched[series_id]
        print(f"  {series_id:<10} {symbol:<9} {len(s.levels):>4} month-end levels "
              f"{min(s.levels)}..{max(s.levels)}  quoted in {s.currency}")
        if s.currency != "CHF":
            raise SystemExit(f"{symbol} is quoted in {s.currency}, expected CHF")
    if dry_run:
        return 0

    with db.datafeed_session() as conn:
        for series_id, s in fetched.items():
            symbol, name, description = SYMBOLS[series_id]
            upsert_series(
                conn, series_id=series_id, name=name, description=description,
                unit="price", currency="CHF", magnitude="units", period="M",
                country="CH", category="fx", source="Yahoo Finance",
                origin_kind="internet:yahoo", quality_grade="close", pull_code=symbol,
                values=dict(s.levels))
    with db.session() as conn:
        service.record_run(
            conn, engine="fx",
            inputs={"symbols": [v[0] for v in SYMBOLS.values()]},
            outputs={k: len(v.levels) for k, v in fetched.items()},
            started=started,
        )
    print(f"stored {sum(len(v.levels) for v in fetched.values())} levels "
          f"in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
