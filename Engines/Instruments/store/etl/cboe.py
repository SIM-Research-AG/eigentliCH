"""Load the Cboe index histories that stand in for registered instruments.

    python -m store.etl.cboe              # fetch and store
    python -m store.etl.cboe --dry-run    # fetch and print, store nothing

One series today: **``cboe.VXTH``**, the Cboe VIX Tail Hedge index, the price proxy of
Long Volatility Index since 29 September 2026 (``feeds/proxy_map.py``, FMRE-18). Monthly
simple returns from month-end closes, in USD, stored in the engine's feed schema beside the
Yahoo proxies, where the 12 month forward measurement reads them.

Like ``store.etl.fx`` and ``store.etl.download`` this is a separate command, not part of
the bootstrap, so that rebuilding the store stays offline and reproducible. It writes the
feed series only; the instrument row's proxy symbol, grade and note are refreshed by
``python -m store.etl.download``, which reads ``feeds/proxy_map.py``.
"""

from __future__ import annotations

import sys
import time

from engines.fund_map import service
from feeds import cboe
from feeds.proxy_map import CBOE_SYMBOLS, feed_series_id
from feeds.security_meta import describe
from store import db
from store.etl.datafeed import upsert_series


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    dry_run = "--dry-run" in argv
    started = time.perf_counter()

    fetched: dict[str, cboe.MonthlySeries] = {}
    for symbol in sorted(CBOE_SYMBOLS):
        if describe(symbol) is None:
            raise SystemExit(f"no entry in feeds/security_meta.py for {symbol}")
        fetched[symbol] = s = cboe.fetch(symbol)
        print(f"  {feed_series_id(symbol):<12} {s.months:>4} monthly returns "
              f"{s.first_period}..{s.last_period}  {s.currency}")
    if dry_run:
        return 0

    with db.datafeed_session() as conn:
        for symbol, s in fetched.items():
            meta = describe(symbol)
            upsert_series(
                conn, series_id=feed_series_id(symbol), name=meta.name,
                description=(f"{meta.description} Monthly total return from the month-end "
                             f"index level, in US dollars."),
                unit="return_simple", currency="USD", magnitude="decimal", period="M",
                country=meta.country, category="return", source="Cboe",
                index_family=meta.index_family or None,
                origin_kind="internet:cboe", quality_grade="close",
                pull_code=f"{cboe.BASE}{symbol}_History.csv", values=dict(s.returns))
    with db.session() as conn:
        service.record_run(
            conn, engine="cboe",
            inputs={"symbols": sorted(CBOE_SYMBOLS)},
            outputs={feed_series_id(k): len(v.returns) for k, v in fetched.items()},
            started=started,
        )
    print(f"stored {sum(len(v.returns) for v in fetched.values())} monthly returns "
          f"in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
