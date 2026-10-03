"""``python -m lbs [serve | init-db]``.

``serve`` (the default) starts the engine on the host and port from ``config.yaml``.
``init-db`` creates the database if needed, then the schema, tables and seed calibrations;
it is only needed once per server.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .settings import ConfigError, load


class _NoHealthAccess(logging.Filter):
    """Leaves ``/health`` out of uvicorn's access log (ENGINE_CHANGES item 10): the container's health check calls
    it every 30 seconds. Every other request is still logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        path = args[2] if isinstance(args, tuple) and len(args) > 2 else ""
        return str(path).split("?", 1)[0] != "/health"


def quiet_health_probes() -> None:
    """Install the filter on ``uvicorn.access`` once; ``uvicorn.run`` keeps a logger's filters."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _NoHealthAccess) for f in logger.filters):
        logger.addFilter(_NoHealthAccess())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lbs")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "init-db"))
    args = parser.parse_args(argv)

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "init-db":
        from .service import Service
        from .store import Store

        store = Store(settings.database)
        print(f"store: {settings.database.redacted_url()}")
        try:
            created = store.create_database()
            print("database created" if created else "database exists")
            Service(settings, store).startup()
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        print(f"schema {settings.database.schema} ready, seed calibrations written")
        return 0

    import uvicorn

    quiet_health_probes()
    uvicorn.run("lbs.api:create_app", factory=True, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
