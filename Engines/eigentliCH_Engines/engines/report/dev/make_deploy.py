"""Build the deploy folder: the essential engine files and nothing else.

    python dev/make_deploy.py [target]      # default: ../../deploy/report

Engine Building Guide: only the files the engine needs; no tests, no golden data, no test bench, no dev
scripts. So the folder gets ``src/report``, ``pyproject.toml``, ``config.yaml``, ``README.md`` and
``DECISIONS.md``, and a start script. It does not get ``tests/``, ``golden/``, ``testbench/``, ``dev/`` or
``config.local.yaml`` (which may hold a password), and never the family ``.env`` (the spark7 token): the
deployment sets ``SPARK7_CLIENT_ID`` and ``SPARK7_CLIENT_SECRET`` in its environment, or places its own
``.env`` where ``model.env_file`` points. The ``dev`` extra in pyproject is not installed there.

The target is replaced wholesale, so a stale file cannot survive a rebuild.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pyproject.toml", "config.yaml", "README.md", "DECISIONS.md")

START = """@echo off
REM Start the eigentliCH Report Engine (report) (deployed build). Host and port come from config.yaml.
REM The database password comes from REPORT_DB_PASSWORD or REPORT_DATABASE_URL; the spark7 token from
REM SPARK7_CLIENT_ID and SPARK7_CLIENT_SECRET in the environment.
cd /d "%~dp0"
python -X utf8 -m report serve
pause
"""


def main(argv: list[str]) -> int:
    target = Path(argv[0]).resolve() if argv else (ROOT.parents[1] / "deploy" / "report")
    if target == ROOT or ROOT in target.parents:
        print("refusing to deploy into the source folder", file=sys.stderr)
        return 2
    if target.exists():
        shutil.rmtree(target)
    (target / "src").mkdir(parents=True)
    shutil.copytree(ROOT / "src" / "report", target / "src" / "report",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    (target / "start.cmd").write_text(START, encoding="utf-8")
    leaked = [p for p in target.rglob("*") if p.name in (".env", "config.local.yaml") or "tests" in p.parts]
    if leaked:
        print(f"refusing: the deploy folder would carry {leaked}", file=sys.stderr)
        shutil.rmtree(target)
        return 3
    for p in sorted(target.rglob("*")):
        if p.is_file():
            print(p.relative_to(target))
    print(f"\ndeploy folder: {target}\ninstall there with:  pip install .")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
