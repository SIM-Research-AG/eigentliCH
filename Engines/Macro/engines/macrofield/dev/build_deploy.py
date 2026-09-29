"""Assemble the deploy folder: only what a running engine needs. Development only.

Engine Building Guide: the deploy folder holds the essential engine files and nothing used to
build or test it. So it takes ``src/``, ``pyproject.toml``, ``config.yaml``, ``README.md``,
``start.cmd`` and the frozen ``data/raw`` snapshot, and leaves out ``tests/``, ``golden/``,
``dev/``, ``testbench/`` and ``config.local.yaml`` (which holds a password).

    python dev/build_deploy.py --out <folder>

The target must not exist: a deploy folder is built fresh, never patched.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_FILES = ("pyproject.toml", "config.yaml", "README.md", "start.cmd")
INCLUDE_DIRS = ("src", "data/raw")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    out: Path = parser.parse_args(argv).out.resolve()
    if out.exists():
        print(f"{out} exists; a deploy folder is built fresh", file=sys.stderr)
        return 2
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
    for name in INCLUDE_DIRS:
        shutil.copytree(ROOT / name, out / name, ignore=ignore)
    for name in INCLUDE_FILES:
        shutil.copy2(ROOT / name, out / name)
    files = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"deploy folder written to {out} ({files} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
