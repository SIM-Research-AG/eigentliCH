"""Start the prototype2 backend and open the browser once the socket is listening.

    python desktop/run.py [--port 8420] [--no-browser]

**Same shape as the estate's `desktop/server.py` launcher, deliberately.** Double-click the icon, a browser
opens, closing the console stops the program. Someone who has used the existing two icons should not have to
learn anything new for the third.

**Two differences that matter.** This one runs uvicorn rather than `http.server`, and it writes to a SQLite
file rather than holding a submission in memory — so unlike the estate's launcher, closing the window does
leave state behind. That state is `backend/eigentlich.db`, it is gitignored, and it will hold member data as
soon as phase 2 lands.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_PORT = 8420  # not 8080: the estate's mockup client already uses that one


def _wait_then_open(host: str, port: int, timeout: float = 20.0) -> None:
    """Open the browser only once something is actually listening.

    Opening it immediately shows a connection error for the second or two uvicorn takes to bind, which reads
    as a broken program rather than a slow one.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.4)
            if probe.connect_ex((host, port)) == 0:
                webbrowser.open(f"http://{host}:{port}/")
                return
        time.sleep(0.25)
    print(f"  the server did not come up on {host}:{port} within {timeout:.0f}s", file=sys.stderr)


def _already_listening(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((host, port)) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eigentliCH prototype2")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reload", action="store_true", help="development: restart on source change")
    args = parser.parse_args(argv)

    # Double-clicking the icon while the program is already running is the most likely way this is used
    # wrongly, and uvicorn's answer to it is `[Errno 10048] only one usage of each socket address`, printed
    # under a generic "the program stopped with an error". For an icon meant to be double-clicked that is a
    # bug report waiting to happen. Do the useful thing instead: it is already open, so open it.
    if _already_listening(args.host, args.port):
        print(f"\n  eigentliCH is already running at http://{args.host}:{args.port}/")
        print("  Opening it rather than starting a second copy.")
        print("  To restart it, close the other console window first.\n")
        if not args.no_browser:
            webbrowser.open(f"http://{args.host}:{args.port}/")
        return 0

    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "\n  uvicorn is not installed in this environment.\n"
            "  Create it with:\n"
            "    python -m venv .venv\n"
            "    .venv\\Scripts\\python.exe -m pip install -e backend[test] uvicorn[standard]\n",
            file=sys.stderr,
        )
        return 1

    db = BACKEND / "eigentlich.db"
    if not db.exists():
        print(
            "\n  No database yet. Create it with:\n"
            f"    .venv\\Scripts\\python.exe -m alembic -c {BACKEND / 'alembic.ini'} upgrade head\n",
            file=sys.stderr,
        )
        return 1

    print(f"\n  eigentliCH prototype2 — http://{args.host}:{args.port}/")
    print("  Close this window to stop.\n")

    if not args.no_browser:
        threading.Thread(target=_wait_then_open, args=(args.host, args.port), daemon=True).start()

    # 127.0.0.1 rather than localhost: the estate learned that astro bound ::1 and the browser resolved to
    # IPv4, which looks exactly like a server that failed to start.
    uvicorn.run(
        "eigentlich.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
