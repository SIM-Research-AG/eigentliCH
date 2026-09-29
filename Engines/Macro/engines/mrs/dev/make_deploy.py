"""Build the deploy folder: the essential engine files and nothing else.

    python dev/make_deploy.py [target]      # default: ../../deploy/mrs

Engine Building Guide: "deploy folder where only the essential files that are needed. Not
to package the tests ... none of the UIs or associated packages are included." So the
folder gets ``src/mrs``, ``pyproject.toml``, ``config.yaml``, ``README.md`` and
``DECISIONS.md``, and a start script. It does not get ``tests/``, ``golden/``,
``testbench/``, ``dev/`` or ``config.local.yaml`` (which may hold a password). The ``dev``
extra in pyproject is not installed there.

The target is replaced wholesale, so a stale file cannot survive a rebuild.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("pyproject.toml", "config.yaml", "README.md", "DECISIONS.md")

START = """@echo off
REM Start the mrs engine (deployed build). Host and port come from config.yaml.
REM The database password comes from HONI_DB_PASSWORD or HONI_DATABASE_URL.
cd /d "%~dp0"
python -X utf8 -m mrs serve
pause
"""


def main(argv: list[str]) -> int:
    target = Path(argv[0]).resolve() if argv else (ROOT.parents[1] / "deploy" / "mrs")
    if target == ROOT or ROOT in target.parents:
        print("refusing to deploy into the source folder", file=sys.stderr)
        return 2
    if target.exists():
        shutil.rmtree(target)
    (target / "src").mkdir(parents=True)
    shutil.copytree(ROOT / "src" / "mrs", target / "src" / "mrs",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    (target / "start.cmd").write_text(START, encoding="utf-8")
    for p in sorted(target.rglob("*")):
        if p.is_file():
            print(p.relative_to(target))
    print(f"\ndeploy folder: {target}\ninstall there with:  pip install .")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
