"""``python -m cockpit [serve | desktop | shortcut | start-engines]``.

    serve           the cockpit on its port (default); engines are started separately
    desktop         the desktop app: starts the autostart engines, opens the app window,
                    and stops what it started when the window closes
    shortcut        puts a "sim-tech Cockpit" shortcut on the desktop (--start-menu: in Start)
    start-engines   starts the autostart engines in the background and exits
"""

from __future__ import annotations

import argparse
import sys

from .settings import load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cockpit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="serve",
                        choices=["serve", "desktop", "shortcut", "start-engines"])
    parser.add_argument("--no-engines", action="store_true", help="desktop: do not start engines")
    parser.add_argument("--browser", help="desktop: path to msedge.exe or chrome.exe")
    parser.add_argument("--start-menu", action="store_true", help="shortcut: in the Start menu")
    parser.add_argument("--mode", choices=["development", "cio"], help="override config.yaml")
    args = parser.parse_args(argv)

    if sys.stdout is None or sys.stderr is None:
        # Started by pythonw (the desktop shortcut): there is no console, and uvicorn's
        # logging set-up fails on a missing stream. Everything goes to a log file instead.
        from .settings import ROOT
        logs = ROOT / "data" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(logs / "cockpit-desktop.log", "a", encoding="utf-8", buffering=1)

    env = None
    if args.mode:
        import os
        env = {**os.environ, "COCKPIT_MODE": args.mode}
    settings = load(env=env)

    if args.command == "serve":
        import uvicorn
        from .api import create_app
        print(f"sim-tech cockpit ({settings.mode} mode) on http://{settings.host}:{settings.port}/")
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
        return 0
    if args.command == "desktop":
        from .desktop import run
        return run(settings, start_engines=not args.no_engines, browser=args.browser)
    if args.command == "shortcut":
        from .desktop import create_shortcut
        print(f"created {create_shortcut(settings, start_menu=args.start_menu)}")
        return 0
    from .launcher import OFF, Launcher
    if not settings.launcher:
        print(OFF)  # C-39: something else starts the engines
        return 0
    for r in Launcher(settings).start_autostart(wait=True):
        print(f"{r['key']:<12} {r.get('action')}{'' if r.get('up', True) else '  (did not come up: see its log)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
