#!/usr/bin/env bash
# Health of the whole deployment, from the server.
#
#   ./scripts/health.sh            container states, then every engine's health endpoint
#   ./scripts/health.sh -p NAME    the same for another compose project (e.g. simtech-test)
#
# The engine endpoints are called from inside the cockpit container, over the compose network,
# because engines publish no host ports. Exit status 0 when every endpoint answered 200.
set -uo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose)
if [ "${1:-}" = "-p" ] && [ -n "${2:-}" ]; then COMPOSE=(docker compose -p "$2"); fi

echo "== containers"
"${COMPOSE[@]}" ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

echo
echo "== health endpoints (from inside the cockpit container)"
"${COMPOSE[@]}" exec -T cockpit python - <<'PY'
import json, sys, urllib.request

ENDPOINTS = [
    ("cockpit", "http://127.0.0.1:8000/api/config"),
    ("datafeed", "http://datafeed:8001/health"),
    ("honi", "http://honi:8002/health"),
    ("macrofield", "http://macrofield:8003/health"),
    ("aggregation", "http://aggregation:8004/health"),
    ("mrs", "http://mrs:8005/health"),
    ("fmre", "http://fmre:8006/v1/health"),
    ("pcp", "http://pcp:8007/health"),
    ("cycle", "http://cycle:8012/health"),
    ("lbs", "http://lbs:8013/health"),
    ("lbsim", "http://lbsim:8014/health"),
    ("report", "http://report:8015/health"),
    ("chatbot", "http://chatbot:8016/health"),
    ("eigentlich", "http://eigentlich:8017/health"),
]
bad = 0
for name, url in ENDPOINTS:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            code, body = r.status, r.read()
    except urllib.error.HTTPError as exc:
        code, body = exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001
        code, body = None, str(exc).encode()
    try:
        status = json.loads(body).get("status", "")
    except Exception:  # noqa: BLE001
        status = body[:80].decode("utf-8", "replace")
    ok = code == 200
    bad += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {name:<12} {code or '-':<4} {status}")
sys.exit(1 if bad else 0)
PY
