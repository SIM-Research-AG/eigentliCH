"""Create the demonstration accounts, one per persona, and print their credentials.

    python tools/seed_demo_accounts.py            # create, or report what already exists
    python tools/seed_demo_accounts.py --reset    # set fresh passwords on the existing accounts
    python tools/seed_demo_accounts.py --list     # print the table without touching anything

**One account per persona, each with its own password.** Not a single shared demo login. Two reasons, and
the second is the one that matters:

  * a shared login means everyone exploring the prototype writes into the same plan, and the role grid of
    a member who has been poked at by four people is not a demonstration of anything;
  * a shared password teaches the wrong habit about a product whose whole posture is that one member's
    material is theirs. The credential model already gives every member their own — seeding should not be
    the one place that pretends otherwise.

The personas are from the eigentliCH Persona Framework (Swiss Fintech Users 18-60). Ages are theirs.

**These guard a local demonstration database and nothing else.** They are documented in the eigentliCH System
Engine page in Notion so someone installing this on their own laptop can get in. That is acceptable only
while three things stay true:

  1. the database is local, created by the installer, and holds no real member's material;
  2. every account created here is marked `fictional`, so it is visible in the data as demonstration;
  3. nothing here is reused as a production credential.

The day a real member registers, the third stops being automatic — and a credential in a shared document
becomes a real exposure rather than a convenience. If this script is still being run when there are real
members, that is the signal to stop.

**Passwords are long and readable rather than random**, deliberately: they are typed by hand from a page
onto someone else's laptop, and a 24-character random string in that path gets pasted wrong or written
down. Length is the property that matters, and they protect nothing real.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from sqlalchemy import select

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from eigentlich.consent import PURPOSES  # noqa: E402
from eigentlich.db import make_engine, make_session_factory  # noqa: E402
from eigentlich.models import Credential, Curator  # noqa: E402
from eigentlich.models.auth import PBKDF2_ITERATIONS, SALT_BYTES  # noqa: E402
from eigentlich.services.auth import register_with_credentials  # noqa: E402
#: Imported rather than reimplemented, unlike `_set_curator_password` below. The reasoning there is about
#: two independent uses of one standard KDF; there is nothing standard about "what revoking means", and a
#: second copy of it here is the A73/A91 defect.
from eigentlich.services.curator import revoke_curator  # noqa: E402

#: The ten in-range personas. Lea is 18 rather than 17: the range was narrowed from 16-60 to 18-60 on
#: 30 August 2026 (A50, A55) and she was aged up rather than dropped, because she is the cohort's
#: deliberate stress case — "if a screen works for both, it works for the cohort as a whole".
#:
#: Kurt, 68 and Lena, 14 are out of scope in the framework itself and are not seeded.
PERSONAS = [
    ("lea", "Lea", 18, "Erstjahr-Lernende Coiffeuse, Renens", "coiffeuse-in-renens-erstes-lehrjahr"),
    ("timo", "Timo", 23, "Lehrabgänger, erster Lohn", "erster-lohn-nach-der-lehre"),
    ("elena", "Elena", 26, "Marketing-Koordinatorin, Zürich", "vom-tessin-nach-zuerich-gezogen"),
    ("lukas", "Lukas", 29, "Ingenieur, Wohneigentum am Horizont", "ingenieur-mit-hauskauf-im-blick"),
    ("marc", "Marc", 35, "Familie und Wohneigentum", "familie-hypothek-und-zwei-kinder"),
    ("celine", "Céline", 43, "Pflegedienstleiterin, Lausanne", "wieder-aufbauen-nach-der-trennung"),
    ("yasminb", "Yasmin B.", 46, "Dermatologin, selbständig, Basel", "eigene-praxis-und-alleinerziehend"),
    ("regina", "Regina", 53, "Kindergärtnerin, Wohneigentum", "kinder-erwachsen-haus-bezahlt"),
    ("roland", "Roland", 55, "Restaurantbesitzer, Locarno", "nachfolge-fuer-das-restaurant"),
    ("beatrice", "Beatrice", 58, "HR-Leiterin, fünf Jahre bis zur Pensionierung", "noch-fuenf-jahre-bis-zur-pension"),
]

#: Accounts whose password is good for exactly ONE login. `must_change` is set, so the holder chooses
#: their own on first use and the documented one stops working.
#:
#: Elio and Yasmin T. are here rather than in PERSONAS because they are not personas:
#: `client/submissions/` holds real submissions under those names, and they are a couple.
#:
#: **The B and T suffixes exist because two different Yasmins now share this system.** Yasmin B. is the
#: fictional Basel dermatologist from the persona framework; Yasmin T. is a real submission. Before the
#: split, `yasmin@eigentli.local` could have been read as either, which is the kind of ambiguity that
#: ends with someone opening the wrong person's plan.
#:
#: An account is a login, a submission is data, and this file does not read one to build the other. The
#: ages below are PLACEHOLDERS that clear the floor; they are not theirs, and nothing here should be
#: taken as a fact about a person.
MUST_CHANGE = [
    ("elio", "Elio", 48, "Zugang, Passwort bei der ersten Anmeldung ändern", "erstanmeldung-bitte-aendern"),
    ("yasmint", "Yasmin T.", 46, "Zugang, Passwort bei der ersten Anmeldung ändern", "erstanmeldung-bitte-wechseln"),
]

#: The real curators, named by the owner on 30 August 2026. These are people, not personas, so each gets
#: a password that is good for ONE login — the documented one stops working the moment they choose their
#: own. Same treatment as Elio and Yasmin T., and for the same reason.
#:
#: **That sentence became true on 31 August 2026 (A89) and was not before.** `must_change` was set here and
#: read by nothing: no service could clear it, no route could change a curator's password, and no
#: dependency refused a credential carrying it — so "good for ONE login" was a false statement printed on
#: an operator's terminal. The curator signs in at `#/kurator` in the client, is sent to a password screen
#: by the server's own 403, and the password below stops working there.
#:
#: **Two, since 20 September 2026.** A62 seeded five. Three of them are no longer part of eigentliCH and
#: were revoked on that date — see `REVOKED` below, which is where their names now live and the only place
#: in this file they still appear.
CURATORS = [
    ("nicolas", "Nicolas", "Kurator", "erstanmeldung-nicolas-bitte-aendern"),
    ("nicolai", "Nicolai", "Kurator", "erstanmeldung-nicolai-bitte-aendern"),
]

#: A160. Revoked on 20 September 2026: no longer part of eigentliCH.
#:
#: **They are listed here rather than deleted from the file, and the row is revoked rather than dropped.**
#: `curator_session_events` refuses DELETE by trigger and `CuratorSession.curator_id` is a foreign key
#: (A98). A curator who appears in a session event and no longer exists in `curators` leaves that event
#: naming nothing, and an audit that cannot resolve its own "who" has stopped being evidence. So the rows
#: stay, `Curator.in_service` goes false, and every gate refuses them.
#:
#: This list is the seed half of that. A database that already holds the three gets them revoked; a fresh
#: one never creates them, and has nothing to revoke — which is why the migration adds the columns and
#: this file writes the state, rather than a migration editing rows and putting the names in two places.
REVOKED_ON = "2026-09-20"
REVOCATION_REASON = "No longer part of eigentliCH (A160, 20 September 2026)."
REVOKED = [("mike", "Mike"), ("nino", "Nino"), ("gian", "Gian")]

#: Kept so the demonstration walkthrough has a curator that is plainly not a real person.
DEMO_CURATOR = {
    "email": "kurator@eigentli.local",
    "password": "kuratorin-mit-mandat-und-protokoll",
    "display_name": "Demo Kuratorin",
    "role_label": "Kuratorin",
}


def _email(key: str) -> str:
    return f"{key}@eigentli.local"


def _curator_email(key: str) -> str:
    """A separate namespace from members, so an address can never be ambiguous about which table it is in."""
    return f"{key}@kurator.eigentli.local"


def _set_curator_password(curator: Curator, password: str) -> None:
    """Mirrors `Credential.set_password`.

    Written out rather than imported: A40 keeps curators and members in separate tables, not on separate
    algorithms, but importing the curator service's helper would let seeding diverge silently if that
    service changed its own. Two independent implementations of one standard KDF is the cheaper failure.
    """
    import hashlib
    import secrets

    curator.password_salt = secrets.token_bytes(SALT_BYTES)
    curator.iterations = PBKDF2_ITERATIONS
    curator.password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), curator.password_salt, curator.iterations
    )


def print_table() -> None:
    print()
    print(f"  {'Persona':<12}{'Age':<5}{'Login':<30}Password")
    print(f"  {'-' * 11:<12}{'-' * 3:<5}{'-' * 28:<30}{'-' * 36}")
    for key, name, age, _role, password in PERSONAS:
        print(f"  {name:<12}{age:<5}{_email(key):<30}{password}")
    print()
    for key, name, age, _role, password in MUST_CHANGE:
        print(f"  {name:<12}{age:<5}{_email(key):<30}{password}")
        print(f"  {'':<12}{'':<5}{'':<30}^ good for ONE login; the holder then chooses their own")
    print()
    print(f"  {'Curator':<12}{'':<5}{'Login':<34}Password")
    print(f"  {'-' * 11:<12}{'':<5}{'-' * 32:<34}{'-' * 36}")
    for key, name, _role, password in CURATORS:
        print(f"  {name:<12}{'':<5}{_curator_email(key):<34}{password}")
    print(f"  {'':<12}{'':<5}{'':<34}^ each good for ONE login")
    print()
    for _key, name in REVOKED:
        print(f"  {name:<12}{'':<5}{'revoked ' + REVOKED_ON:<34}no longer part of eigentliCH")
    print()
    print(f"  {'Demo':<12}{'':<5}{DEMO_CURATOR['email']:<34}{DEMO_CURATOR['password']}")
    print()
    print("  These guard a local demonstration database and nothing else. Do not reuse them for anything")
    print("  real, and do not run this against a database holding a real member.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the eigentliCH demonstration accounts.")
    parser.add_argument("--reset", action="store_true", help="set fresh passwords on existing accounts")
    parser.add_argument("--list", action="store_true", help="print the table and exit")
    parser.add_argument("--database", help="override the database URL")
    args = parser.parse_args(argv)

    if args.list:
        print_table()
        return 0

    engine = make_engine(args.database)
    sessions = make_session_factory(engine)
    created, reset, revoked, existing_count = [], [], [], 0

    with sessions() as db:
        for key, name, age, role, password in PERSONAS + MUST_CHANGE:
            address = _email(key)
            found = db.execute(
                select(Credential).where(Credential.email == address)
            ).scalar_one_or_none()
            if found is None:
                member, _credential = register_with_credentials(
                    db,
                    email=address,
                    password=password,
                    age_at_registration=age,
                    display_name=f"{name} ({role})",
                    # R-103. The same rows `POST /api/members` writes, from the same registry, so a
                    # seeded account's S-14 consent screen shows what a real one shows. Without this
                    # the demonstration accounts would be the one place R-230's history is still empty,
                    # and the demonstration accounts are what the owner looks at.
                    consents=[
                        {"purpose": purpose.key, "document_version": purpose.document_version}
                        for purpose in PURPOSES
                        if purpose.required_at_registration
                    ],
                )
                if (key, name, age, role, password) in MUST_CHANGE:
                    # Good for one login. The documented password stops working the moment it is used.
                    _credential.must_change = True
                created.append((name, address, member.id))
            elif args.reset:
                found.set_password(password)
                found.must_change = (key, name, age, role, password) in MUST_CHANGE
                reset.append((name, address, found.member_id))
            else:
                existing_count += 1

        for key, name, role_label, password in CURATORS:
            address = _curator_email(key)
            found = db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none()
            if found is None:
                person = Curator(display_name=name, email=address, role_label=role_label,
                                 # Real people. Not marked fictional — the audit table's whole purpose is
                                 # saying who did something, and a real curator flagged as fictional would
                                 # make every record they touch ambiguous.
                                 fictional=False)
                _set_curator_password(person, password)
                person.must_change = True
                db.add(person)
                db.flush()
                created.append((name, address, person.id))
            elif args.reset:
                _set_curator_password(found, password)
                found.must_change = True
                reset.append((name, address, found.id))
            else:
                existing_count += 1

        # A160. Revoke the three who left, if this database is one that still has them. Idempotent:
        # `revoke_curator` keeps the first timestamp, so re-seeding does not move the date they left.
        # A row that is not here was never created, and there is nothing to revoke — a fresh database is
        # correct by never having them rather than by having them switched off.
        for key, name in REVOKED:
            address = _curator_email(key)
            if db.execute(select(Curator).where(Curator.email == address)).scalar_one_or_none() is None:
                continue
            revoke_curator(db, email=address, reason=REVOCATION_REASON)
            revoked.append((name, address))

        curator = db.execute(
            select(Curator).where(Curator.email == DEMO_CURATOR["email"])
        ).scalar_one_or_none()
        if curator is None:
            curator = Curator(
                display_name=DEMO_CURATOR["display_name"],
                email=DEMO_CURATOR["email"],
                role_label=DEMO_CURATOR["role_label"],
                # Marked in the data, so a demonstration curator is never mistaken for a real one in an
                # audit table whose entire purpose is recording who did something.
                fictional=True,
            )
            _set_curator_password(curator, DEMO_CURATOR["password"])
            db.add(curator)
            db.flush()
            created.append(("Kuratorin", DEMO_CURATOR["email"], curator.id))
        elif args.reset:
            _set_curator_password(curator, DEMO_CURATOR["password"])
            reset.append(("Kuratorin", DEMO_CURATOR["email"], curator.id))
        else:
            existing_count += 1

        db.commit()

    print()
    for label, rows in (("created", created), ("reset", reset)):
        for name, address, row_id in rows:
            print(f"  {label:<8}{name:<12}{address:<34}{row_id}")
    for name, address in revoked:
        print(f"  {'revoked':<8}{name:<12}{address:<34}{REVOCATION_REASON}")
    if existing_count:
        print(f"  {existing_count} account(s) already existed. Use --reset to set fresh passwords.")
    print_table()
    return 0


if __name__ == "__main__":
    sys.exit(main())
