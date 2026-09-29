"""Build the cockpit's deploy folder: the CIO pages only (DECISIONS.md C-03).

    python dev/make_deploy.py [target]      # default: ../Macro/deploy/cockpit

The Engine Building Guide keeps every UI out of deployment. The CIO pages are the recorded
exception (owner, 27.09.2026): they are a product view, not a development tool. So the folder
gets ``src/cockpit``, ``pyproject.toml``, ``README.md``, ``DECISIONS.md`` and a start
script, and a ``config.yaml`` rewritten for production:

- ``service.mode: cio``: no test benches, no API explorer, and a read-only proxy apart from
  ``cio.writable``;
- no ``bench``, ``start``, ``autostart`` or ``python`` entries (top level or per engine): a
  deployed cockpit shows the engines, it does not start them or reach into their source folders.
- the curator's database connection (``curator_db``) stays, without a password: the deployed
  cockpit takes it from ``COCKPIT_CURATOR_DB_PASSWORD`` (C-16).

It does not get ``tests/``, ``dev/``, ``data/`` (the build machine's decision log and logs)
or ``config.local.yaml``. The target is replaced wholesale, so a stale file cannot survive.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pyproject.toml", "README.md", "DECISIONS.md")
DROP = ("bench", "start", "autostart", "python")

HEADER = """\
# Engine 11: Cockpit, deployed build (dev/make_deploy.py). CIO pages only (DECISIONS.md C-03).
# Generated from the development config.yaml; edit that one and rebuild. Engine URLs are the
# development defaults: point them at the deployed engines. No password lives here.
"""

START = """@echo off
REM The cockpit's CIO pages (deployed build). Host, port and engine URLs come from config.yaml.
cd /d "%~dp0"
python -X utf8 -m cockpit serve --mode cio
pause
"""


def production_config() -> str:
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["service"]["mode"] = "cio"
    raw.pop("python", None)
    (raw.get("curator_db") or {}).pop("password", None)
    for engine in raw.get("engines", []):
        for key in DROP:
            engine.pop(key, None)
    return HEADER + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100)


def main(argv: list[str]) -> int:
    target = Path(argv[0]).resolve() if argv else (ROOT.parent / "Macro" / "deploy" / "cockpit")
    if target == ROOT or ROOT in target.parents:
        print("refusing to deploy into the source folder", file=sys.stderr)
        return 2
    if target.exists():
        shutil.rmtree(target)
    (target / "src").mkdir(parents=True)
    shutil.copytree(ROOT / "src" / "cockpit", target / "src" / "cockpit",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    (target / "config.yaml").write_text(production_config(), encoding="utf-8")
    (target / "start.cmd").write_text(START, encoding="utf-8")
    for p in sorted(target.rglob("*")):
        if p.is_file():
            print(p.relative_to(target))
    print(f"\ndeploy folder: {target}\ninstall there with:  pip install .")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
