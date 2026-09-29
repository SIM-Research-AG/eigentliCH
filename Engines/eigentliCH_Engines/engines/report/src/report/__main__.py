"""``python -m report [serve | init-db | probe]``.

``serve`` (the default) starts the engine on the host and port from ``config.yaml``. ``init-db`` creates
the tables and seed calibrations in the engine's schema (the role and schema are provisioned once by
``Projects/Engines/Instruments/store/provision.py``). ``probe`` asks the model service which models it
serves and sends one warm-up token, without printing any header.
"""

from __future__ import annotations

import argparse
import sys

from .settings import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m report")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "init-db", "probe"))
    args = parser.parse_args(argv)

    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command in ("init-db", "probe"):
        from .clients import engine_clients
        from .service import Service
        from .spark7 import ModelError, ModelUnavailable, Spark7Client
        from .store import Store

        model = Spark7Client(settings.model, settings.env)
        if args.command == "probe":
            try:
                served = model.models()
            except (ModelUnavailable, ModelError) as exc:
                print(f"{settings.model.service}: {exc}", file=sys.stderr)
                return 3
            reason, ms = model.touch()
            print(f"{settings.model.service} serves {served}; configured {settings.model.model!r}; "
                  f"warm-up {'ok' if reason is None else reason} in {ms:.0f} ms")
            return 0 if reason is None and settings.model.model in served else 3
        store = Store(settings.database)
        print(f"store: {settings.database.redacted_url()}")
        upstream = engine_clients({"pcp": settings.pcp_url, "lbs": settings.lbs_url, "lbsim": settings.lbsim_url}, settings.upstream_timeout_s)
        try:
            Service(settings, store, upstream, model).startup(warmup=False)
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        finally:
            model.close()
        print(f"schema {settings.database.schema} ready, seed calibrations written")
        return 0

    import uvicorn

    uvicorn.run("report.api:create_app", factory=True, host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
