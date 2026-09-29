"""``python -m datafeed [serve | init-db | bootstrap ...]``.

``serve`` (default) starts the engine on the host and port from ``config.yaml``.
``init-db`` creates the database, schema and seed calibrations.
``bootstrap`` builds the snapshots; see ``datafeed/etl/bootstrap.py`` for its options.
"""

from __future__ import annotations

import sys

from .settings import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv else "serve"
    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if command == "bootstrap":
        try:
            from .etl.bootstrap import main as bootstrap
        except ImportError:
            print("this is a deployed build without the importer; bootstrap from a development "
                  "checkout, or ingest through POST /snapshots", file=sys.stderr)
            return 2
        return bootstrap(argv, settings)
    if command == "init-db":
        from .service import Service
        from .store import Store
        store = Store(settings.database)
        try:
            print("database created" if store.create_database() else "database exists")
            Service(settings, store).startup()
        except Exception as exc:  # noqa: BLE001
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        print(f"schema {settings.database.schema} ready")
        return 0
    if command == "serve":
        import uvicorn
        uvicorn.run("datafeed.api:create_app", factory=True, host=settings.host, port=settings.port)
        return 0
    print(f"unknown command {command!r}: serve, init-db or bootstrap", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
