"""Health of every engine in the simtech container: each health route on 127.0.0.1.

    simtech health            a table: ok/FAIL, engine, HTTP status, the engine's own status
    simtech health --quiet    no output; exit status only (the container's health check)

Exit status 0 only when every route answered HTTP 200. Standard library only. The list is
the programs in docker/supervisord.conf; the lbsim workers have no port and are
checked by `supervisorctl status` (scripts/health.sh).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

ROUTES = [
    ("datafeed", "http://127.0.0.1:8001/health"),
    ("honi", "http://127.0.0.1:8002/health"),
    ("macrofield", "http://127.0.0.1:8003/health"),
    ("aggregation", "http://127.0.0.1:8004/health"),
    ("mrs", "http://127.0.0.1:8005/health"),
    ("fmre", "http://127.0.0.1:8006/v1/health"),
    ("pcp", "http://127.0.0.1:8007/health"),
    ("cycle", "http://127.0.0.1:8012/health"),
    ("lbs", "http://127.0.0.1:8013/health"),
    ("lbsim", "http://127.0.0.1:8014/health"),
    ("report", "http://127.0.0.1:8015/health"),
    ("chatbot", "http://127.0.0.1:8016/health"),
    ("eigentlich", "http://127.0.0.1:8017/health"),
    ("cockpit", "http://127.0.0.1:8000/health"),
]


def probe(url: str) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            code, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        code, body = exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001 - any failure means not healthy
        return None, str(exc)[:80]
    try:
        status = json.loads(body).get("status", "") or ""
    except Exception:  # noqa: BLE001
        status = body[:80].decode("utf-8", "replace")
    return code, str(status)


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    bad = 0
    for name, url in ROUTES:
        code, status = probe(url)
        ok = code == 200
        bad += not ok
        if not quiet:
            print(f"  {'ok  ' if ok else 'FAIL'} {name:<12} {code or '-':<4} {status}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
