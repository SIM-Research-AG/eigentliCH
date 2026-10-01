"""Write the cockpit's ``config.local.yaml`` for Docker, at image build time.

    python cockpit_docker_config.py /srv/Engines/cockpit

The cockpit reads ``config.yaml < config.local.yaml < COCKPIT_*``. Its roster in config.yaml
carries a ``start`` command and an ``autostart`` flag per engine for the Windows desktop app.
In Docker the engines are started by supervisord, and the cockpit must only show status, so
this script derives an overlay from the committed roster, without touching the cockpit's code
or config.yaml:

- every engine keeps its ``url`` from config.yaml (``http://127.0.0.1:80NN``): in the one
  ``simtech`` container every engine listens on 127.0.0.1, exactly as on the owner's machine;
- ``start``, ``python`` and ``autostart`` are removed, so the launcher has nothing it may
  start (``POST /api/launcher/{key}/start`` answers 409, and the System page shows no Start);
- the curator's database host becomes the compose service ``db`` (the cockpit has no
  environment variable for it yet, ENGINE_CHANGES.md item 1).

Because the overlay is derived from config.yaml at every build, an engine added to the
roster there appears in Docker after the next ``docker compose build``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

DB_HOST = "db"


def main(folder: str) -> int:
    root = Path(folder)
    tree = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    engines = []
    for row in tree.get("engines") or []:
        row = dict(row)
        for key in ("start", "python"):
            row.pop(key, None)
        row["autostart"] = False
        engines.append(row)
    overlay = {
        "python": None,
        "curator_db": {"host": DB_HOST, "port": 5432},
        "engines": engines,
    }
    header = ("# Generated at image build by deploy/docker/cockpit_docker_config.py from config.yaml.\n"
              "# Docker only: no start commands (status only), curator database on host db. Do not edit.\n")
    (root / "config.local.yaml").write_text(
        header + yaml.safe_dump(overlay, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"cockpit overlay: {len(engines)} engines, none startable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
