"""Write the third-party runtime dependencies of one or more engines to a requirements file.

    python deps.py OUT.txt path/to/pyproject.toml [more pyproject.toml ...] [--extra PKG ...]

Reads ``[project] dependencies`` from each pyproject.toml (never the ``dev`` extras), drops
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
    extras: list[str] = []
    if "--extra" in rest:
        i = rest.index("--extra")
        rest, extras = rest[:i], rest[i + 1:]
    seen: list[str] = []
    for name in rest:
        with open(name, "rb") as fh:
            project = tomllib.load(fh).get("project") or {}
        for dep in project.get("dependencies") or []:
            if dep not in seen:
                seen.append(dep)
    for dep in extras:
        if dep not in seen:
            seen.append(dep)
    out.write_text("\n".join(seen) + "\n", encoding="utf-8")
    print(f"{len(seen)} requirements from {len(rest)} pyproject files -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
