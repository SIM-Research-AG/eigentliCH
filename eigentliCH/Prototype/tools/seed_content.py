"""Write the authored content records into the store. Run once per database.

    python tools/seed_content.py             # show what is in the store and what is missing
    python tools/seed_content.py --write     # write the missing rows
    python tools/seed_content.py --write --member <id>   # also the member offers, hung on that member

**Why this exists, and why its absence was a real defect.** `services/learning.py::seed` and
`services/marketplace.py::seed` were both complete, idempotent and well tested — and **nothing called
either of them outside the test suite.** No startup hook, no operator command, nothing in the distribution
installer. So on the database the desktop icon actually opens:

  * `capabilities`, `learning_units`, `providers`, `listings`, `disclosures`, `gatherings` were all empty;
  * S-10's screen listed ten capability statements read from the *content file*, and pressing any of them
    returned **503 — "no capability … in the store. Run `seed` first"**, a server error naming a command
    that did not exist;
  * with no `CapabilityAssertion` possible, **R-005's gate refused every real member**, which is precisely
    the condition A94 records as fixed;
  * the Market Place and Community screens were empty over payloads that worked.

An audit found it by counting rows rather than by reading code, which is the only way this class of defect
is ever found: every function involved was correct, and the thing that was missing was the call.

**Idempotent, and it does not repair.** Both services key rows by the content `key`, so re-running adds
nothing and rewrites nothing. That is deliberate and is stated in `learning.seed`'s own docstring: a
member's assertion points at a capability id, and silently restating a statement under an id somebody has
already been assessed against changes what their assertion means. So this tool writes what is absent and
leaves what is present, and `--write` on a seeded database is a no-op that says so.

**Every listing goes through `publish`.** The seeding path is not a shortcut around R-202: a seed record
carrying no disclosure fails the same gate an applicant meets, rather than appearing as a published listing
with nothing declared.

**Member offers need a member and are otherwise skipped.** A `MemberOffer` with no member is not a member
offer, and inventing one to hang it on would be seeding a person. Pass `--member` with a real id when you
want them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

#: The tables these two services fill, in the order a reader would ask about them.
SEEDED_TABLES = (
    "capabilities",
    "learning_units",
    "providers",
    "listings",
    "disclosures",
    "member_offers",
)


def _counts(session) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    for table in SEEDED_TABLES:
        counts[table] = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="seed the authored content records")
    parser.add_argument("--write", action="store_true", help="write the missing rows")
    parser.add_argument(
        "--member",
        help="a member id to hang the R-205 member offers on; omitted, they are skipped",
    )
    args = parser.parse_args(argv)

    from eigentlich.db import make_engine, make_session_factory
    from eigentlich.services import learning, marketplace

    sessions = make_session_factory(make_engine())

    with sessions() as session:
        before = _counts(session)
        print(f"\n  {'table':<20} rows")
        for table, count in before.items():
            print(f"  {table:<20} {count}")

        if not args.write:
            empty = [table for table, count in before.items() if count == 0]
            if empty:
                print(f"\n  empty: {', '.join(empty)}")
                print("  Run with --write to fill them. Nothing has been changed.")
            else:
                print("\n  Nothing is missing.")
            return 0

        learning_written = learning.seed(session)
        market_written = marketplace.seed(session, member_id=args.member)
        session.commit()

        after = _counts(session)
        print("\n  written:")
        for name, rows in {**learning_written, **market_written}.items():
            print(f"   {name:<20} {len(rows)}")
        print("\n  after:")
        for table, count in after.items():
            moved = count - before[table]
            print(f"  {table:<20} {count}" + (f"   (+{moved})" if moved else "   (unchanged)"))

        if args.member is None and after["member_offers"] == 0:
            print(
                "\n  member_offers is empty because no --member was given. R-205's offers belong to a\n"
                "  member, and inventing one to hang them on would be seeding a person."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
