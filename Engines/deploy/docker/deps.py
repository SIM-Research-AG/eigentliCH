"""Write the third-party runtime dependencies of one or more engines to a requirements file.

    python deps.py OUT.txt path/to/pyproject.toml[EXTRA,...] [more pyproject.toml ...]

Reads ``[project] dependencies`` from each pyproject.toml, plus the optional-dependency groups
named in brackets after a file (``fmre.toml[etl]``; never ``dev`` unless named), drops
duplicates and writes one requirement per line. The images install this list first, before
the engine code is copied, so a code change does not reinstall numpy. The engines' own files
stay the one place that says what an engine needs.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    out, rest = Path(argv[0]), argv[1:]
    seen: list[str] = []
    for arg in rest:
        name, _, groups = arg.partition("[")
        with open(name, "rb") as fh:
            project = tomllib.load(fh).get("project") or {}
        deps = list(project.get("dependencies") or [])
        optional = project.get("optional-dependencies") or {}
        for group in filter(None, groups.rstrip("]").split(",")):
            if group not in optional:
                print(f"{name} has no optional dependencies [{group}]", file=sys.stderr)
                return 2
            deps += optional[group]
        for dep in deps:
            if dep not in seen:
                seen.append(dep)
    out.write_text("\n".join(seen) + "\n", encoding="utf-8")
    print(f"{len(seen)} requirements from {len(rest)} pyproject files -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
