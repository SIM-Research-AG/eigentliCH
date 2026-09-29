"""Container health check: exit 0 when the URL answers HTTP 200 within the timeout.

    python /opt/deploy/healthcheck.py http://127.0.0.1:8002/health

Standard library only, so it works in every family image without curl.
"""

import sys
import urllib.request

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/health"
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
    print(f"{url}: {exc}", file=sys.stderr)
    sys.exit(1)
