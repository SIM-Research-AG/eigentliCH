"""``python -m lbsim [serve | worker | init-db]``.

``serve`` (the default) prepares the store, puts the plan runs whose worker died back on the queue, starts
``optimiser.workers`` worker processes (``python -m lbsim worker``) and then the API on the host and port from
``config.yaml``; stopping it stops the workers. ``worker`` runs one worker alone (``--once`` handles the queue until
it is empty, for tests and scripts). ``init-db`` creates the tables and the seed calibrations and exits.

The API process never imports ``lbsim.optim`` or casadi; each worker process loads them on its first plan.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading

from .settings import ConfigError, load


def _service(settings):
    from .service import Service  # noqa: PLC0415
    from .store import Store  # noqa: PLC0415

    return Service(settings, Store(settings.database))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lbsim")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "worker", "init-db"))
    parser.add_argument("--workers", type=int, default=None, help="serve: worker processes (default: config)")
    parser.add_argument("--once", action="store_true", help="worker: stop when the queue is empty")
    args = parser.parse_args(argv)
    try:
        settings = load()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "init-db":
        service = _service(settings)
        try:
            service.startup()
        except Exception as exc:  # noqa: BLE001 - a CLI reports the reason, not a traceback
            print(f"init-db failed: {exc}", file=sys.stderr)
            return 3
        print(f"schema {settings.database.schema} ready, seed calibrations written")
        return 0

    if args.command == "worker":
        from .worker import Worker  # noqa: PLC0415

        service = _service(settings)
        service.startup()
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: stop.set())
            except (ValueError, OSError):
                pass
        worker = Worker(service)
        print(f"lbsim worker {worker.name}: waiting for plan runs", flush=True)
        worker.run_forever(stop, idle_exit_s=0.0 if args.once else None)
        return 0

    service = _service(settings)
    service.startup()
    requeued = service.requeue_stale()
    if requeued:
        print(f"requeued or closed {len(requeued)} plan runs whose worker stopped: {requeued}", flush=True)
    n = settings.optimiser.workers if args.workers is None else max(0, args.workers)
    procs = []
    for _ in range(n):
        procs.append(subprocess.Popen([sys.executable, "-X", "utf8", "-m", "lbsim", "worker"], env=dict(os.environ)))
    print(f"lbsim: {n} plan workers started (pids {[p.pid for p in procs]})", flush=True)
    try:
        import uvicorn  # noqa: PLC0415

        uvicorn.run("lbsim.api:create_app", factory=True, host=settings.host, port=settings.port)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
