"""Publish the first AssumptionSet from the estate's own engines. A35, C-02.

    python tools/publish_assumption_set.py                # run the two world engines, write one set
    python tools/publish_assumption_set.py --dry-run      # run them, print the set, write nothing
    python tools/publish_assumption_set.py --list         # what is already published
    python tools/publish_assumption_set.py --recompute    # republish the Regime and the ReturnSet first

**Why a tool rather than a migration or a fixture.** The numbers come from two engines that take minutes
and reach the network. A migration cannot run them, and a fixture would mean typing them in — which is the
exact substitution C-02 and §12 exist to prevent. Publishing is an act with an owner and a date, and this
is where both are recorded: `published_by` is written as "SIM Research, run <date>".

**Why it is not called from the API.** R-301 — the two engines declare 1800-second timeouts, so neither
may be reached from a request thread, and R-304 keeps the artefacts they read off every HTTP route
entirely. This runs at a terminal, deliberately.

**`--recompute` is not the default, and that matters.** A Regime is a vintage that downstream artefacts
stamp; republishing it on every read would move it under a consumer mid-run. The default reads what the
estate has already published, which is what makes two runs of this tool idempotent.

**If an engine will not run, nothing is written.** The tool prints the reason and exits non-zero. An empty
assumption-set table refuses every illustration (C-02) and is the honest state; a partly-filled one would
look complete.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from eigentlich.db import make_engine, make_session_factory  # noqa: E402
from eigentlich.engines import DEFAULT_MARKET_SCOPE, ESTATE_ROOT, estate_available  # noqa: E402
from eigentlich.models import AssumptionSet  # noqa: E402
from eigentlich.services.assumptions import (  # noqa: E402
    NothingToPublish,
    compose,
    describe,
    publish,
    _run_world_engines,
)


def _print_set(payload: dict) -> None:
    print(f"  version         {payload['version']}")
    print(f"  effective_from  {payload['effective_from']}")
    print(f"  published_by    {payload['published_by']}")
    print(f"  inflation       {payload['inflation']}  (NULL: neither engine publishes one)")
    source = payload["rates"]["source"]
    print(f"  regime          {source['market_signal']['regime_id']}")
    print(f"  return set      {source['return_estimation']['return_set_id']}")
    print(f"  horizon         {payload['horizons']['return_estimation_years']}y, "
          f"scope {payload['horizons']['scope']}")
    print("  replay:")
    print(f"    {source['market_signal']['replay']}")
    print(f"    {source['return_estimation']['replay']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="run the engines, print the set, write nothing")
    parser.add_argument("--list", action="store_true", help="print what is already published, run nothing")
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="republish the Regime and the ReturnSet first. Minutes, and reaches the network.",
    )
    parser.add_argument("--verbose", action="store_true", help="show the R-303 engine log lines")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    engine = make_engine()
    sessions = make_session_factory(engine)

    with sessions() as session:
        if args.list:
            rows = session.execute(
                select(AssumptionSet).order_by(AssumptionSet.effective_from.desc())
            ).scalars().all()
            if not rows:
                print("no assumption set is published. Every illustration refuses (C-02), which is correct.")
                return 0
            for row in rows:
                print(f"{row.version}  effective {row.effective_from}  by {row.published_by}  id {row.id}")
            return 0

        if not estate_available():
            print(f"the estate at {ESTATE_ROOT} is not reachable, so no engine can run. Nothing written.")
            return 2

        try:
            if args.dry_run:
                runs = _run_world_engines(
                    scope=DEFAULT_MARKET_SCOPE,
                    publish_artefacts=args.recompute,
                    purpose="dry run of the first AssumptionSet (A35)",
                )
                payload = compose(runs, run_date=date.today())
                print("would publish:")
                _print_set(payload)
                print("\nnotes:\n" + payload["notes"])
                print("\nnothing was written (--dry-run).")
                return 0

            assumption_set = publish(session, publish_artefacts=args.recompute)
            session.commit()
        except NothingToPublish as error:
            print(f"nothing published: {error}")
            return 1

        payload = describe(assumption_set)
        print(f"published assumption set {payload['assumption_set_id']}")
        _print_set(payload)
        print("\nnotes:\n" + payload["notes"])
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
