"""Local web server for the Life Balance Sheet app.

Serves an interactive front end where you enter or edit a person's inputs, run the
engine, and see the result — plus save your own users. Pure standard library.

    python -m personal_alm.app.server

It picks a port, opens your browser, and computes on demand. A solve takes a few
seconds (longer for long horizons). Close the console window to stop the app.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Windows consoles default to cp1252 and choke on non-ASCII; make stdout robust.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from .dashboard import build_data
from .inputs import case_from_input, delete_user, load_users, presets, save_user

_SHELL = (Path(__file__).parent / "app.html").read_text(encoding="utf-8")


def _shell() -> bytes:
    html = (_SHELL
            .replace("__PRESETS__", json.dumps(presets()))
            .replace("__USERS__", json.dumps(load_users())))
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _shell(), "text/html")
        elif self.path == "/favicon.ico":
            self._send(204, b"", "text/plain")
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            if self.path == "/api/compute":
                case = case_from_input(self._read_json())
                print(f"  ... solving {case.name} ({case.goal.kind})")
                data = build_data(case)
                print(f"  [ok] {case.name}: P(goal)={data['p_goal']:.0%}")
                self._send(200, json.dumps(data).encode("utf-8"))
            elif self.path == "/api/users":
                users = save_user(self._read_json())
                self._send(200, json.dumps(users).encode("utf-8"))
            elif self.path == "/api/users/delete":
                users = delete_user(self._read_json().get("name", ""))
                self._send(200, json.dumps(users).encode("utf-8"))
            else:
                self._send(404, b'{"error":"not found"}')
        except Exception as exc:  # surface a readable message to the front end
            self._send(400, str(exc).encode("utf-8"), "text/plain")


def main(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print("=" * 58)
    print("  The Life Balance Sheet — engine running")
    print(f"  Open:  {url}")
    print("  Close this window to stop the app.")
    print("=" * 58)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
