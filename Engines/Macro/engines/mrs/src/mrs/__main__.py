"""``python -m mrs [serve | init-db [--rebuild] | load-reference [folder]]``.

``load-reference`` loads a frozen MATLAB export (a folder with ``manifest.json``) into
``reference_source`` and ``reference_signal``; loading the same file twice is a no-op.

``serve`` (the default) starts the engine on the host and port from ``config.yaml``.
``init-db`` creates the database if needed, then the schema, tables and seed calibrations;
it is only needed once per server. ``init-db --rebuild`` drops this engine's tables in its
own schema (never the schema, its grants or any other schema) and creates them afresh:
needed once to leave the v0.1.0 store, whose tables have another shape.
"""

from __future__ import annotations

import argparse
import sys

from .settings import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mrs")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=("serve", "init-db", "load-reference"))
    parser.add_argument("--rebuild", action="store_true",
                        help="init-db: drop and recreate this engine's tables in its schema")
    parser.add_argument("folder", nargs="?", default=None,
                        help="load-reference: frozen export folder with manifest.json "
                             "(default golden/cio_signal_2026-09)")
    args = parser.parse_args(argv)

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "init-db":
        from .clients import DatafeedClient
        from .service import Service
        from .store import Store

        store = Store(settings.database)
        print(f"store: {settings.database.redacted_url()}")
        try:
            created = store.create_database()
            print("database created" if created else "database exists")
            if args.rebuild:
                dropped = store.rebuild()
                print(f"rebuilt schema {settings.database.schema}: dropped "
                      f"{', '.join(dropped) or 'nothing'}; tables recreated")
            Service(settings, store, DatafeedClient(settings.datafeed_url)).startup()
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        print(f"schema {settings.database.schema} ready, seed calibrations written")
        return 0

    if args.command == "load-reference":
        from pathlib import Path

        from . import reference
        from .settings import ROOT
        from .store import Store, put_reference_signal

        folder = Path(args.folder) if args.folder else ROOT / "golden" / "cio_signal_2026-09"
        store = Store(settings.database)
        print(f"store: {settings.database.redacted_url()}")
        try:
            store.initialise()
            for manifest, rows, months in reference.iter_folder(folder):
                with store.session() as conn:
                    source_id, created = put_reference_signal(conn, manifest=manifest, rows=rows,
                                                              months=months)
                print(f"{source_id}: {'loaded' if created else 'already loaded'}, "
                      f"{len(rows)} rows, {months} months")
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"load-reference failed: {exc}", file=sys.stderr)
            return 3
        return 0

    import uvicorn

    uvicorn.run("mrs.api:create_app", factory=True, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
