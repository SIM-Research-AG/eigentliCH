"""``python -m macrofield [serve | init-db | load | data-need]``.

``serve`` (the default) starts the engine on the host and port from ``config.yaml``.
``init-db`` creates the database if needed, then the schema, tables and seed calibrations.
``load`` verifies the frozen raw folder against its manifest and loads it as a snapshot.
``data-need`` writes the data-need specification to ``data_need.csv`` for the T5 register.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .settings import ROOT, ConfigError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m macrofield")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=("serve", "init-db", "load", "data-need"))
    parser.add_argument("--raw", type=Path, default=None,
                        help="load: the raw folder (default: data.raw_dir in config.yaml)")
    parser.add_argument("--out", type=Path, default=ROOT / "data_need.csv",
                        help="data-need: where to write the CSV")
    args = parser.parse_args(argv)

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "serve":
        import uvicorn

        uvicorn.run("macrofield.api:create_app", factory=True, host=settings.host,
                    port=settings.port)
        return 0

    from .service import Service
    from .store import Store

    store = Store(settings.database)
    service = Service(settings, store)
    try:
        if args.command == "init-db":
            print(f"store: {settings.database.redacted_url()}")
            print("database created" if store.create_database() else "database exists")
            service.startup()
            print(f"schema {settings.database.schema} ready, seed calibrations written")
        elif args.command == "load":
            service.startup()
            result = service.load_snapshot(args.raw)
            verb = "loaded" if result["created"] else "already loaded"
            print(f"snapshot {result['snapshot_id']} {verb}"
                  + (f" ({result['observations']} observations)" if result["created"] else ""))
            for note in result["notes"]:
                print(f"  note: {note}")
        else:
            from .data_need import CSV_COLUMNS

            rows = service.data_need(None, None).rows
            with args.out.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, delimiter="|")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row.model_dump())
            missing = sum(r.status == "missing" for r in rows)
            print(f"{len(rows)} rows ({missing} missing) written to {args.out}")
    except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 3
    finally:
        service.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
