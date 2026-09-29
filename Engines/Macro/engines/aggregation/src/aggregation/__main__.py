"""``python -m aggregation [serve | init-db]``.

``serve`` (the default) starts the engine on the host and port from ``config.yaml``.
``init-db`` creates the database if needed, then the schema, tables and seed calibrations;
it is only needed once per server.
"""

from __future__ import annotations

import argparse
import sys

from .settings import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aggregation")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "init-db"))
    args = parser.parse_args(argv)

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "init-db":
        from .clients import cycle_client, macrofield_client, mrs_client
        from .service import Service
        from .store import Store

        store = Store(settings.database)
        print(f"store: {settings.database.redacted_url()}")
        try:
            created = store.create_database()
            print("database created" if created else "database exists")
            Service(settings, store, mrs_client(settings.mrs_url), cycle_client(settings.cycle_url),
                    macrofield_client(settings.macrofield_url)).startup()
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        print(f"schema {settings.database.schema} ready, seed calibrations written")
        return 0

    import uvicorn

    uvicorn.run("aggregation.api:create_app", factory=True, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
