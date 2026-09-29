"""Operator password reset. A43 — this is what replaces a mail flow.

    python -m eigentlich.reset someone@example.ch
    python -m eigentlich.reset someone@example.ch --password "a chosen one"
    python -m eigentlich.reset --list

**Why a command and not an endpoint.** An HTTP reset endpoint has to authenticate the operator, which
means another credential, which means another thing to reset. A command run on the machine is
authenticated by having the machine — which, for a product that runs locally and stores K3 in a file
beside it, is the honest boundary. Anyone who can run this can already read `eigentlich.db`.

**It prints the new password once.** There is nowhere to send it, so it goes to the operator's terminal
and the operator passes it on however they and the member arrange. `must_change` is set, so it is good for
exactly one login.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import select

from .db import make_engine, make_session_factory
from .models import Credential
from .services.auth import AuthenticationFailed, operator_reset

#: Four words from a small readable set beats a random string that gets written on paper wrongly.
#: Not a passphrase generator with any security claim beyond length — `secrets` picks, and the result is
#: replaced at first login anyway.
_WORDS = (
    "anker", "birke", "delta", "eisen", "feder", "granit", "hafen", "iglu", "jura", "kiesel",
    "linde", "moor", "nebel", "olive", "pfad", "quarz", "runde", "salz", "tanne", "ufer",
    "vogel", "wiese", "zeder", "ampel", "brunnen", "chor", "dorf", "esche",
)


def suggest_password() -> str:
    return "-".join(secrets.choice(_WORDS) for _ in range(4))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eigentlich.reset",
        description="Reset a member's password. Run on the machine that hosts eigentliCH.",
    )
    parser.add_argument("email", nargs="?", help="the address to reset")
    parser.add_argument("--password", help="the new password; one is generated if omitted")
    parser.add_argument("--list", action="store_true", help="list registered addresses and exit")
    parser.add_argument("--database", help="override the database URL")
    args = parser.parse_args(argv)

    engine = make_engine(args.database)
    sessions = make_session_factory(engine)

    with sessions() as db:
        if args.list:
            rows = db.execute(select(Credential).order_by(Credential.email)).scalars().all()
            if not rows:
                print("no credentials registered")
                return 0
            for row in rows:
                last = row.last_login_at.isoformat(timespec="minutes") if row.last_login_at else "never"
                flag = "  (must change)" if row.must_change else ""
                print(f"  {row.email:<40} last login {last}{flag}")
            return 0

        if not args.email:
            parser.error("an email address is required unless --list is given")

        password = args.password or suggest_password()
        try:
            operator_reset(db, email=args.email, new_password=password)
        except AuthenticationFailed as failure:
            print(f"  {failure}", file=sys.stderr)
            return 1
        db.commit()

        print()
        print(f"  Password reset for {args.email}")
        print(f"  New password: {password}")
        print()
        print("  Every existing session for this member has been revoked, and the password is marked")
        print("  must-change: it is good for one login, after which they choose their own.")
        print()
        print("  This is printed once and is not stored anywhere. Pass it on out of band.")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
