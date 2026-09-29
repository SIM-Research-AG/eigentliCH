"""Write the cockpit's ``config.local.yaml`` for Docker, at image build time.

    python cockpit_docker_config.py /srv/Engines/cockpit

The cockpit reads ``config.yaml < config.local.yaml < COCKPIT_*``. Its roster in config.yaml
points every engine at 127.0.0.1 and carries a ``start`` command and ``autostart`` flag for
the Windows desktop app. In Docker the cockpit must only show status, so this script derives
an overlay from the committed roster, without touching the cockpit's code or config.yaml:

- every engine's ``url`` becomes ``http://<key>:<port>``: the compose service name is the
  engine key, and the port is the one config.yaml already names;
- ``start``, ``python`` and ``autostart`` are removed, so the launcher has nothing it may
  start (``POST /api/launcher/{key}/start`` answers 409, and the System page shows no Start);
- the curator's database host becomes the compose service ``postgres``.

Because the overlay is derived from config.yaml at every build, an engine added to the
roster there appears in Docker after the next ``docker compose build cockpit``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


def main(folder: str) -> int:
    root = Path(folder)
    tree = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    engines = []
    for row in tree.get("engines") or []:
        row = dict(row)
        port = urlparse(row["url"]).port
        row["url"] = f"http://{row['key']}:{port}"
        for key in ("start", "python"):
            row.pop(key, None)
        row["autostart"] = False
        engines.append(row)
    overlay = {
        "service": {"host": "0.0.0.0"},
        "python": None,
        "curator_db": {"host": "postgres", "port": 5432},
        "engines": engines,
    }
    header = ("# Generated at image build by deploy/docker/cockpit_docker_config.py from config.yaml.\n"
              "# Docker only: engines by service name, no start commands (status only). Do not edit.\n")
    (root / "config.local.yaml").write_text(
        header + yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"cockpit overlay: {len(engines)} engines, none startable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
