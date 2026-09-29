"""Record a human's approval of authored knowledge entries.

    python tools/approve_knowledge.py --list
    python tools/approve_knowledge.py --by "Nicolas Bürkler, SIM Research" <id> [<id> ...]
    python tools/approve_knowledge.py --by "..." --all
    python tools/approve_knowledge.py --withdraw <id> [<id> ...]

**Why this is a tool and not a text edit.** `approved: true` is the only thing standing between a draft and
a member reading it as fact about Swiss law. Flipping it by hand in fourteen files invites the two failures
that matter: setting it on a file nobody read, and setting it without recording who read it. This writes
`approved`, `reviewed_by` and `reviewed_on` together or not at all, refuses an id it cannot find rather than
silently doing nothing, and prints what it changed.

**It does not judge the content.** Approval is a human act. This records it.

**Withdrawal is symmetrical and deliberately easy.** A figure that was current when it was approved stops
being current — Swiss figures change annually — so unapproving has to be as cheap as approving, or the
corpus rots in the direction of being wrong. `--withdraw` clears all three fields.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "content" / "knowledge"

#: `README.md` documents the format and carries no frontmatter. It is not an entry.
SKIP = {"README.md"}


def entries() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(KNOWLEDGE.glob("*.md")):
        if path.name in SKIP:
            continue
        text = io.open(path, encoding="utf-8").read()
        match = re.search(r"(?m)^id:\s*(\S+)\s*$", text)
        if match:
            found[match.group(1)] = path
    return found


def _set(text: str, key: str, value: str) -> str:
    """Replace `key: ...` inside the frontmatter, or fail loudly rather than appending a second one."""
    pattern = re.compile(rf"(?m)^{re.escape(key)}:.*$")
    if not pattern.search(text):
        raise SystemExit(f"  frontmatter has no `{key}:` line to set; refusing to invent one")
    return pattern.sub(f"{key}: {value}", text, count=1)


def show() -> int:
    found = entries()
    if not found:
        print(f"  no entries under {KNOWLEDGE}")
        return 1
    print(f"  {len(found)} entries in {KNOWLEDGE}\n")
    for identifier, path in found.items():
        text = io.open(path, encoding="utf-8").read()
        approved = re.search(r"(?m)^approved:\s*(\S+)\s*$", text)
        by = re.search(r"(?m)^reviewed_by:\s*(.*)$", text)
        state = (approved.group(1) if approved else "?").strip()
        mark = "APPROVED" if state.lower() == "true" else "draft   "
        who = (by.group(1).strip() if by else "").strip('"')
        print(f"   {mark}  {identifier:<38} {who if who != 'null' else ''}")
    return 0


def apply(identifiers: list[str], reviewer: str | None, withdraw: bool) -> int:
    found = entries()
    unknown = [i for i in identifiers if i not in found]
    if unknown:
        # Refusing the whole batch, not the unknown ones: a typo'd id in a list of fourteen otherwise
        # means thirteen get approved and nobody notices the fourteenth did not.
        print(f"  unknown entry ids, nothing changed: {', '.join(unknown)}", file=sys.stderr)
        print(f"  known ids are: {', '.join(sorted(found))}", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    for identifier in identifiers:
        path = found[identifier]
        text = io.open(path, encoding="utf-8").read()
        if withdraw:
            text = _set(text, "approved", "false")
            text = _set(text, "reviewed_by", "null")
            text = _set(text, "reviewed_on", "null")
            verb = "withdrawn"
        else:
            text = _set(text, "approved", "true")
            text = _set(text, "reviewed_by", f'"{reviewer}"')
            text = _set(text, "reviewed_on", today)
            verb = "approved"
        io.open(path, "w", encoding="utf-8", newline="\n").write(text)
        print(f"   {verb}: {identifier}")

    print(f"\n  {len(identifiers)} {'withdrawn' if withdraw else 'approved'}", end="")
    if not withdraw:
        print(f" by {reviewer} on {today}", end="")
    print(".")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record approval of authored knowledge entries")
    parser.add_argument("ids", nargs="*", help="entry ids, as printed by --list")
    parser.add_argument("--list", action="store_true", help="show every entry and its state")
    parser.add_argument("--all", action="store_true", help="act on every entry")
    parser.add_argument("--by", help="the person recording the approval — required to approve")
    parser.add_argument("--withdraw", action="store_true", help="clear approval instead of setting it")
    args = parser.parse_args(argv)

    if args.list or (not args.ids and not args.all):
        return show()

    identifiers = sorted(entries()) if args.all else args.ids
    if not args.withdraw and not args.by:
        print("  --by is required to approve: an approval with no reviewer is not an approval.",
              file=sys.stderr)
        return 1
    return apply(identifiers, args.by, args.withdraw)


if __name__ == "__main__":
    raise SystemExit(main())
