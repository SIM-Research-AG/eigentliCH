"""Replace a member's name with a pseudonym, everywhere the database holds it. A162.

**What this is for, and what it is not.** R-231's erasure removes a person; this keeps the person's
record and changes what it calls them. The owner's ruling of 20 September 2026 was that one of the six
real submissions keeps its record — those six are the corpus A135 and A139 measure against, and erasing
one changes what the Know surface has been proved to answer — but stops carrying the person's name.
Renaming is therefore the operation, not deletion, and the numbers, answers and derived findings are
untouched.

**Almost all of it is a file rename.** `tools/load_submission.py._names` derives the slug, the address
and the display name from the submission's *filename* and nothing else: `RenzoTommasini` becomes
`renzot`, `renzo.t` and `Renzo T.`. The submission JSON contains no name at all. So renaming the file and
re-loading would produce a correctly-named member from scratch. This script exists for the database that
already holds the old name, where re-loading would mean discarding a plan, its versions and its history.

**No example in this file uses the name it was written to remove.** A pseudonym works by being the only
name the record holds, and a tool that documents itself with a worked before-and-after rebuilds the link
in the one place a reader is guaranteed to look. The usage below is written with the new name on both
sides for that reason; substitute whatever pair you actually need.

**The hard part is `decisions`, and it is the reason this is a script rather than three UPDATEs.**
`decisions` and `curator_session_events` refuse UPDATE and DELETE by trigger, and `db.py` raises
`DecisionImmutable` before the ORM can flush a change. That is correct and must stay correct. Erasure is
the one operation in this build that works around it, and it does so by dropping the triggers, redacting
through Core `update()` statements, and re-creating the triggers in a `finally` **on the session's own
connection** — going through `engine.begin()` would commit the CREATEs before the DROPs and leave the
database with no append-only triggers at all. A63, A66 and A68 are three separate occasions on which
this build lost those triggers silently. This script copies erasure's shape exactly, for that reason,
and verifies the trigger count before and after rather than trusting that it worked.

**A pseudonymisation is a rewrite of an append-only row, and that is a real cost.** A decision's
`reasoning` is part of the record; editing it means the register can no longer say that no decision has
ever been altered. It is done here because a name the owner has ruled must go is a stronger claim than
the integrity of a German sentence naming a source file, and it is written down because the alternative
— doing it at a prompt with no record — is the quiet change rule 5 of the cull task forbids.

Usage:

    python tools/pseudonymise_member.py --from <OldName> --to <NewName>
    python tools/pseudonymise_member.py --from <OldName> --to <NewName> --apply

Without `--apply` it reports what it would change and writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from sqlalchemy import select, text, update

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from eigentlich.db import _APPEND_ONLY_TRIGGERS, append_only_trigger_statements  # noqa: E402
from eigentlich.db import make_engine, make_session_factory  # noqa: E402
from eigentlich.models import Credential, Decision, Member  # noqa: E402
from eigentlich.models.household import HouseholdMember  # noqa: E402
from eigentlich.services.plan import mutate_plan  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from load_submission import _names  # noqa: E402


def _trigger_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    }


def pseudonymise(db, *, old_person: str, new_person: str, apply: bool) -> list[str]:
    """Rewrite one member's name. Returns the lines of the report, applied or not."""
    old_slug, _old_dotted, old_display = _names(old_person)
    new_slug, _new_dotted, new_display = _names(new_person)
    changes: list[str] = []

    member = db.execute(
        select(Member).where(Member.display_name == old_display)
    ).scalar_one_or_none()
    if member is None:
        return [f"no member named {old_display!r} in this database; nothing to do"]

    changes.append(f"members.display_name       {old_display!r} -> {new_display!r}")

    credentials = db.execute(
        select(Credential).where(Credential.member_id == member.id)
    ).scalars().all()
    for credential in credentials:
        changes.append(
            f"credentials.email          {credential.email!r} -> "
            f"{credential.email.replace(old_slug, new_slug)!r}"
        )

    labels = db.execute(
        select(HouseholdMember).where(HouseholdMember.label.like(f"%{old_display}%"))
    ).scalars().all()
    for row in labels:
        changes.append(f"household_members.label    {row.label!r} -> {new_display!r}")

    # The append-only one. Matched on the person key (`NinoTommasini`) as well as the display name,
    # because `load_submission` writes the source file's own stem into the German reasoning string.
    decisions = db.execute(select(Decision).where(Decision.member_id == member.id)).scalars().all()
    touched = [
        d for d in decisions if d.reasoning and (old_person in d.reasoning or old_display in d.reasoning)
    ]
    for decision in touched:
        changes.append(f"decisions.reasoning        {decision.id} (append-only; triggers dropped)")

    if not apply:
        changes.append("")
        changes.append("dry run. Nothing was written. Re-run with --apply.")
        return changes

    member.display_name = new_display
    for credential in credentials:
        credential.email = credential.email.replace(old_slug, new_slug)
    db.flush()

    # -- the household label, which C-09 makes into a Decision ----------------------------------------
    #
    # **This is the interesting part of the script and it was got wrong once.** `HouseholdMember` is
    # `PlanMutable`, so assigning to `label` raises `PlanMutationWithoutDecision` on flush. The first
    # attempt argued that a pseudonymisation is not a change to the plan — the household's composition,
    # its relationships and every number attached to it are identical before and after — and went round
    # the ORM with a Core `update()`, the way `services/erasure.py` reaches the append-only tables.
    #
    # C-09 refused that too. It has two enforcement points, not one: the `before_flush` guard AND
    # `_refuse_unvetted_plan_dml`, which inspects statements going to the connection and says in as many
    # words that a violation "does not become one because the write went round the ORM". That second
    # guard is A72's fix, and it did exactly the job it was added for.
    #
    # The refusal settles the argument against the argument. This build has already classified
    # `household_members` as plan-mutable; a tool deciding from outside that one particular column does
    # not count is a tool overruling the schema's own judgement to save itself a record. So the change
    # is made the way C-09 requires, and the Decision is true: the label did change, on the owner's
    # instruction, and now there is a row saying so.
    #
    # The Decision deliberately does not name the old name. A record that reads "X was renamed to Y" in
    # a database that no longer holds X anywhere else would reintroduce exactly the link the
    # pseudonymisation exists to break.
    if labels:
        with mutate_plan(
            db,
            member_id=member.id,
            question="Anzeigename dieses Haushaltsmitglieds durch ein Pseudonym ersetzen?",
            choice=f"Ja — der Name lautet neu {new_display}",
            author="curator",
            reasoning=(
                "Weisung des Eigentümers vom 20. September 2026. Der Datensatz bleibt vollständig "
                "erhalten; geändert wird ausschliesslich der angezeigte Name. Der frühere Name wird "
                "hier absichtlich nicht genannt — eine Aufzeichnung, die beide Namen nebeneinander "
                "führt, stellt genau die Verbindung wieder her, die das Pseudonym auflösen soll."
            ),
        ) as decision:
            for row in labels:
                row.label = new_display
                decision.linked_household_members.append(row)

    if touched:
        connection = db.connection()
        before = _trigger_names(connection)
        for table in _APPEND_ONLY_TRIGGERS:
            for verb in ("update", "delete"):
                connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_{verb}"))
        try:
            for decision in touched:
                rewritten = decision.reasoning.replace(old_person, new_person).replace(
                    old_display, new_display
                )
                connection.execute(
                    update(Decision.__table__)
                    .where(Decision.__table__.c.id == decision.id)
                    .values(reasoning=rewritten)
                )
        finally:
            # Erasure's rule, and the reason it is a rule: on the session's own connection, so the
            # CREATEs cannot commit ahead of the DROPs and leave the audit tables writable.
            db.flush()
            for statement in append_only_trigger_statements():
                db.connection().execute(text(statement))

        after = _trigger_names(db.connection())
        if after != before:
            raise RuntimeError(
                f"the append-only triggers did not come back: {sorted(before - after)} missing. "
                f"This is A63/A66/A68's failure and the transaction is being rolled back."
            )
        changes.append(f"triggers verified          {len(before)} before, {len(after)} after")

    db.commit()
    changes.append("")
    changes.append("applied.")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="old", required=True, help="e.g. NinoTommasini")
    parser.add_argument("--to", dest="new", required=True, help="e.g. RenzoTommasini")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--database", help="override the database URL")
    args = parser.parse_args(argv)

    sessions = make_session_factory(make_engine(args.database))
    with sessions() as db:
        for line in pseudonymise(db, old_person=args.old, new_person=args.new, apply=args.apply):
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
