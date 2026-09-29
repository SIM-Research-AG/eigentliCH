"""R-231's erasure. The member's material goes; the append-only rows stay and are emptied of them.

**Reachable by a member as of 31 August 2026.** `erase_on_member_request` at the foot of this file is the
entry point, behind a typed confirmation sentence and the member's own password; `api/erasure.py` is the
route. Before that, everything here was complete, well tested, and callable only from
`tests/test_erasure.py` — A90's finding, and the one that mattered most: R-231 was not partly built, it was
built and unreachable, while the route a member could reach reported `executed: false`.

**The decision, taken by the owner on 30 August 2026:** null the member reference on the records that
cannot be deleted, rather than deferring erasure until a retention policy exists.

**What "null it" has to mean to be worth doing.** `Decision` carries `question`, `choice` and `reasoning`
— free text *about* the member's plan. Nulling only `member_id` would leave that prose sitting in the
table, unattached but perfectly readable, which is the version of this that looks compliant and is not. So
a redacted Decision loses its member reference AND its free text, and keeps only what makes it a record
that something happened: its id, its timestamps, its author kind, and a marker saying it was redacted.

That is not a softening of the instruction. It is the instruction carried through the fields that actually
hold the person.

**Why the append-only tables are written to at all.** R-040 and C-10 make `decisions` and
`curator_session_events` refuse UPDATE and DELETE by trigger. Erasure drops those triggers, redacts, and
re-creates them, inside one transaction. That is a deliberate, narrow, operator-visible exception — and it
is why this lives in its own module with its own name rather than inside the settings service, where a
future reader might mistake it for ordinary maintenance.

**The list of what goes is not written here.** `member_data.py` holds it, because R-154's export walks
the same tuple and two hand-written lists cannot be kept in agreement. A member's `Provider` row and the
listings hanging off it are part of that list: a member who completed the ladder and became supply leaves
the market place when they leave, and before this was so the DELETE on `members` failed on a foreign key
and the erasure rolled back entirely.

**What is NOT redacted.** `curator_session_events` records what a CURATOR did. That is the curator's
accountability rather than the member's data, and an audit that erased itself whenever a member left would
not be an audit. Only the member reference is nulled there; the actor, the kind and the time stay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from ..db import ERASING, _APPEND_ONLY_TRIGGERS, _ERASURE_TOKEN, append_only_trigger_statements
from ..models import (
    Credential,
    CuratorSession,
    CuratorSessionEvent,
    Decision,
    Disclosure,
    Goal,
    Listing,
    Member,
    MemberFact,
    HouseholdMember,
    PlanVersion,
    Position,
    Provider,
    VaultItem,
    goal_funding,
    goal_owners,
    utcnow,
)
from ..models.decision import (
    decision_facts,
    decision_goals,
    decision_positions,
    decision_vault_items,
)
from .member_data import DELETED_IN_ERASURE_ORDER, DEPENDENTS_IN_ERASURE_ORDER, owning_predicate
from .plan import mutate_plan

#: Written into a redacted Decision's text fields. Not an empty string: a reader finding this knows the
#: record was emptied deliberately and when, rather than wondering whether it was ever filled in.
REDACTED = "[gelöscht auf Antrag des Mitglieds]"

#: Rows removed outright, children before the parents they reference.
#:
#: **Not written here.** It lives in `member_data.py`, because R-154's export walks the same tuple: a
#: table that is erased and not exported means the member is told less about their record than the
#: application is willing to destroy of it, which is the defect that put five tables outside the export.
#: Adding a table there adds it to both paths at once.
_DELETED_IN_ORDER = DELETED_IN_ERASURE_ORDER


@dataclass
class ErasureReport:
    """What was done, per table. Handed back so a member sees the act rather than a reassurance."""

    member_id: str
    executed_at: datetime
    deleted: dict[str, int] = field(default_factory=dict)
    redacted: dict[str, int] = field(default_factory=dict)
    vault_bytes_removed: bool = False

    def as_dict(self) -> dict:
        return {
            "member_id": self.member_id,
            "executed": True,
            "executed_at": self.executed_at.isoformat(),
            "deleted": self.deleted,
            "redacted": self.redacted,
            "vault_bytes_removed": self.vault_bytes_removed,
            "_about": {
                "redacted_means": "the row survives because R-040 and C-10 forbid removing it; its member "
                                  "reference and its free text are gone.",
                "curator_events": "only the member reference is nulled. What a curator did is the "
                                  "curator's accountability, and an audit that erased itself whenever a "
                                  "member left would not be an audit.",
            },
        }


def erase_member(session: Session, store, *, member_id: str) -> ErasureReport:
    """Execute R-231's erasure. Irreversible.

    The caller is responsible for having written the Decision that recorded the request — this function
    performs the act, and the record of it is made before, not after, because a crash between the two
    should leave a request without an erasure rather than an erasure without a request.
    """
    member = session.get(Member, member_id)
    if member is None:
        raise LookupError(f"no member {member_id!r}")

    report = ErasureReport(member_id=member_id, executed_at=utcnow())

    # C-09 stands down for this and nothing else. Removing a plan is not a change to one, and the Decision
    # recording the REQUEST was written by the caller before this began.
    # The token, not a bare `True`: the C-09 guard checks identity, so the escape hatch is reachable
    # only by code that imports `_ERASURE_TOKEN` from `db.py`. That is one grep, and a test does it.
    session.info[ERASING] = _ERASURE_TOKEN
    try:
        return _erase(session, store, member, report)
    finally:
        session.info.pop(ERASING, None)


def _erase(session: Session, store, member: Member, report: ErasureReport) -> ErasureReport:
    member_id = member.id

    # -- 1. the bytes, before the rows that address them ------------------------------------------
    if store is not None:
        store.delete_member(member_id)
        report.vault_bytes_removed = True

    # -- 2. the association rows, BEFORE what they point at ----------------------------------------
    #
    # `decision_positions`, `decision_goals`, `decision_vault_items`, `decision_facts` and
    # `goal_funding` are plain link tables — not append-only, and not covered by the triggers. They have
    # to go first or the deletes below fail on a foreign key, which is how this was found.
    connection = session.connection()
    owned_positions = select(Position.__table__.c.id).where(Position.__table__.c.member_id == member_id)
    owned_goals = select(Goal.__table__.c.id).where(Goal.__table__.c.member_id == member_id)
    owned_vault = select(VaultItem.__table__.c.id).where(VaultItem.__table__.c.member_id == member_id)

    connection.execute(delete(decision_positions).where(decision_positions.c.position_id.in_(owned_positions)))
    connection.execute(delete(decision_goals).where(decision_goals.c.goal_id.in_(owned_goals)))
    connection.execute(delete(decision_vault_items).where(decision_vault_items.c.vault_item_id.in_(owned_vault)))
    owned_facts = select(MemberFact.__table__.c.id).where(MemberFact.__table__.c.member_id == member_id)
    connection.execute(delete(decision_facts).where(decision_facts.c.member_fact_id.in_(owned_facts)))
    connection.execute(delete(goal_funding).where(goal_funding.c.goal_id.in_(owned_goals)))
    connection.execute(delete(goal_funding).where(goal_funding.c.position_id.in_(owned_positions)))
    # `goal_owners` names who a goal is for. Its `goal_id` is a NOT NULL foreign key, so it goes with
    # the other link tables and for the same reason. The `household_members` rows on the other side
    # are NOT deleted — see step 3b — so only the link is removed here.
    connection.execute(delete(goal_owners).where(goal_owners.c.goal_id.in_(owned_goals)))
    # `plan_versions.superseded_by_id` points at another row of the same table, `PRAGMA foreign_keys` is
    # ON, and SQLite checks a foreign key per row as it deletes — so the order matters and the generic
    # loop below selects rows unordered.
    #
    # **Deleted oldest first, and NOT by clearing the self-reference.** Nulling `superseded_by_id` was the
    # first attempt and `ck_plan_versions_superseded_names_successor` refused it, correctly: a superseded
    # version with no successor is a history that cannot be read in either direction, and erasure is not a
    # licence to write a row the schema forbids. Ascending `number` works with no such surgery, because
    # the reference points forward — an older version names the newer one that replaced it, so the
    # referrer always goes before the row it references.
    #
    # Not a C-09 concern: `plan_versions` is not `PlanMutable` (a version records the plan rather than
    # changing it), so the statement guard has nothing to say about a Core delete here.
    for version_id in connection.execute(
        select(PlanVersion.__table__.c.id)
        .where(PlanVersion.__table__.c.member_id == member_id)
        .order_by(PlanVersion.__table__.c.number)
    ).scalars():
        connection.execute(
            delete(PlanVersion.__table__).where(PlanVersion.__table__.c.id == version_id)
        )
        report.deleted["plan_versions"] = report.deleted.get("plan_versions", 0) + 1

    # A member who completed the ladder and became supply owns a `Provider` row, and that row is in
    # `_DELETED_IN_ORDER` below. Its listings and their disclosures both hold NOT NULL foreign keys back
    # up the chain, so they have to go first — the same rule as the link tables above, one table deeper.
    # Found by erasing a member who had been through `apply_to_be_listed`: the DELETE on `members` failed
    # on a foreign key and the whole erasure rolled back, so the member could not leave at all.
    # `owning_predicate` is the same expression the export selects them with, so the rows the member
    # takes away and the rows that are destroyed are found by one definition rather than by two.
    for model in DEPENDENTS_IN_ERASURE_ORDER:
        removed = connection.execute(
            delete(model.__table__).where(owning_predicate(model, member_id))
        ).rowcount
        if removed:
            report.deleted[model.__tablename__] = removed

    # The ORM still holds those collections in memory; expire so the deletes below see the truth.
    session.expire_all()

    # -- 3. the ordinary tables --------------------------------------------------------------------
    for model in _DELETED_IN_ORDER:
        rows = session.execute(select(model).where(model.member_id == member_id)).scalars().all()
        if rows:
            report.deleted[model.__tablename__] = len(rows)
        for row in rows:
            session.delete(row)
    session.flush()

    # -- 3b. household membership: redacted, not deleted --------------------------------------------
    #
    # The row names this member and R-231 takes their name off it. The row is also the OTHER member's
    # statement about their own household, and every plan version that household produced is stamped
    # against it — so deleting it would rewrite a second person's history to record a household that never
    # had two people in it. One member's erasure may not edit another member's record.
    #
    # Not part of step 4: `household_members` carries no append-only trigger, so it needs none of the
    # trigger handling and must not be inside the block that drops them.
    household_rows = session.execute(
        select(HouseholdMember).where(HouseholdMember.member_id == member_id)
    ).scalars().all()
    if household_rows:
        report.redacted["household_members"] = len(household_rows)
    for row in household_rows:
        # Through the ORM, not a Core UPDATE. `household_members` is a plan table now, so a Core statement
        # is refused by C-09's statement-level guard, which does not read the erasure token — only
        # `before_flush` does. The ORM path is the one the exception was written for, and unlike
        # `decisions` this table carries no immutability trigger to work around.
        row.member_id = None
        row.label = REDACTED
    session.flush()

    # -- 4. the append-only tables ------------------------------------------------------------------
    #
    # The triggers are dropped and re-created around this. It is the one place in the application that
    # does so, it is inside the caller's transaction, and the report says what it touched — an exception
    # that is visible is a different thing from one that is quiet.
    for table in _APPEND_ONLY_TRIGGERS:
        for verb in ("update", "delete"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_{verb}"))

    try:
        decisions = session.execute(
            select(Decision).where(Decision.member_id == member_id)
        ).scalars().all()
        if decisions:
            report.redacted["decisions"] = len(decisions)
        for decision in decisions:
            connection.execute(
                update(Decision.__table__)
                .where(Decision.__table__.c.id == decision.id)
                .values(
                    member_id=None,
                    question=REDACTED,
                    choice=REDACTED,
                    reasoning=None,
                    author_ref=None,
                    options_considered=[],
                )
            )

        sessions = session.execute(
            select(CuratorSession).where(CuratorSession.member_id == member_id)
        ).scalars().all()
        if sessions:
            report.redacted["curator_sessions"] = len(sessions)
        for curator_session in sessions:
            connection.execute(
                update(CuratorSession.__table__)
                .where(CuratorSession.__table__.c.id == curator_session.id)
                .values(member_id=None)
            )
            # The events keep their actor, kind and time. Only a detail payload that might name the
            # member is cleared.
            events = session.execute(
                select(CuratorSessionEvent).where(
                    CuratorSessionEvent.session_id == curator_session.id
                )
            ).scalars().all()
            if events:
                report.redacted["curator_session_events"] = (
                    report.redacted.get("curator_session_events", 0) + len(events)
                )
            for event in events:
                connection.execute(
                    update(CuratorSessionEvent.__table__)
                    .where(CuratorSessionEvent.__table__.c.id == event.id)
                    .values(detail=None)
                )

        session.execute(delete(Member.__table__).where(Member.__table__.c.id == member_id))
        report.deleted["members"] = 1
    finally:
        # Re-created whatever happened above, ON THE SESSION'S OWN CONNECTION. Going through
        # `engine.begin()` here opens a second transaction, so the CREATEs commit before the DROPs do and
        # the erasure leaves the database with no triggers at all. A failure that left the audit tables
        # writable would be worse than the failure itself.
        session.flush()
        for statement in append_only_trigger_statements():
            session.connection().execute(text(statement))

    session.expire_all()
    return report


# ================================================================ R-231, reachable by the member
#
# Everything above was complete, tested, and callable only from `tests/test_erasure.py`. A90's finding was
# that a member could not leave: `POST /api/settings/deletion` wrote a Decision and returned
# `executed: false`, and this file was the implementation nobody could reach. What follows is the reachable
# entry point, and it lives here rather than at the edge so that no second route can be added later that
# performs the act without the confirmation.


#: The sentence the member types, one per published language. **A closed set of two exact strings.**
#:
#: Why a typed phrase and not a checkbox: a checkbox is one click from a mis-click, and pydantic's lax
#: boolean would accept `1`, `"yes"` and `"on"` as agreement to something irreversible. A string compared
#: for equality against two published values has no ambiguous input — anything that is not one of these
#: two is refused, and there is nothing to coerce.
#:
#: Either language is accepted, whatever the member's locale says. Two exact strings are no less
#: unambiguous than one, and refusing an English member who typed the English sentence because their
#: locale had not been switched would be a guard misfiring on the person it protects.
CONFIRMATION_PHRASES: dict[str, str] = {
    "de": "ALLE MEINE DATEN LÖSCHEN",
    "en": "DELETE ALL MY DATA",
}


class ErasureNotConfirmed(ValueError):
    """The confirmation sentence was absent, misspelt, or in neither published language.

    Refused rather than interpreted. There is no near-match, no case folding and no partial credit: this is
    the last thing standing between a request and an irreversible act, and a guard that accepts
    approximations of the sentence accepts approximations of the intent.
    """

    def __init__(self, offered: object) -> None:
        super().__init__(
            "the erasure was not confirmed. The confirmation sentence has to be typed exactly, in one "
            f"of the published languages: {sorted(CONFIRMATION_PHRASES.values())}. "
            f"Received: {offered!r}."
        )
        self.offered = offered


def confirmation_phrase(language: str) -> str:
    """The sentence to display, for a client that has the member's language."""
    return CONFIRMATION_PHRASES.get(language, CONFIRMATION_PHRASES["de"])


def _confirmed(offered: object) -> bool:
    """Exact equality against the published sentences, after trimming surrounding whitespace only.

    **Whitespace and nothing else.** A trailing space arrives from a form field and from a paste, and
    refusing it protects nobody. Case is not folded and interior spacing is not normalised, because
    `alle meine daten loschen` is a different string and treating it as the same one would be this guard
    deciding what the member meant.
    """
    if not isinstance(offered, str):
        return False
    return offered.strip() in set(CONFIRMATION_PHRASES.values())


def erase_on_member_request(
    session: Session,
    store,
    *,
    member_id: str,
    confirmation: object,
    password: object,
    reason: str | None = None,
) -> dict:
    """R-231's erasure, performed for a member who asked for it. **Irreversible.**

    Three things have to be true before anything is destroyed, and they are checked here rather than in the
    route so that they hold for any caller:

      1. the member exists;
      2. the confirmation sentence was typed exactly (`ErasureNotConfirmed`);
      3. the member's own password verifies (`AuthenticationFailed`).

    **The password, and why a valid token is not enough.** `api/auth.py` keeps the current password
    required even for a forced change, on the grounds that waiving it would turn a stolen token into a
    password change. The same reasoning applies with more force here: a token left open on a borrowed
    laptop would otherwise be enough to destroy somebody's whole record. Re-authentication is what makes
    this an act of the member rather than of whoever holds the string.

    **The Decision is written first, and it is then redacted by the erasure it records.** That ordering is
    `erase_member`'s own rule: a crash between the two should leave a request without an erasure rather
    than an erasure without a request. And the redaction is not an oversight — A61 decided that a
    Decision loses its member reference and its free text, and the request to be erased is as much a fact
    about this member as anything else they wrote. The id survives, and is returned, so an operator
    reading `decisions` can see which redacted row was the request.

    Returns `ErasureReport.as_dict()` with the decision id added. The member's sessions are among the rows
    destroyed, so the token that authorised this call stops working with it.
    """
    from .auth import AuthenticationFailed  # local: services/auth.py imports the registration side

    member = session.get(Member, member_id)
    if member is None:
        raise LookupError(f"no member {member_id!r}")

    if not _confirmed(confirmation):
        raise ErasureNotConfirmed(confirmation)

    credential = session.execute(
        select(Credential).where(Credential.member_id == member_id)
    ).scalar_one_or_none()
    if credential is None or not isinstance(password, str) or not credential.verify(password):
        # One refusal for "no credential" and for "wrong password", the same shape the login route uses:
        # neither says anything more than that this call is not authorised.
        raise AuthenticationFailed("password is incorrect")

    with mutate_plan(
        session,
        member_id=member_id,
        question="Alle eigenen Daten endgültig löschen?",
        choice="Ja. Bestätigt und ausgeführt.",
        author="member",
        reasoning=reason,
        options_considered=[
            {
                "label": "Löschen",
                "consequence": "Die eigenen Daten werden entfernt. Entscheide und das "
                               "Kuratoren-Protokoll bleiben als Zeilen bestehen (R-040, C-10), ohne "
                               "Namen und ohne Text. Der Vorgang ist nicht umkehrbar.",
            },
            {
                "label": "Konto behalten",
                "consequence": "Die Daten bestehen weiter und bleiben jederzeit exportierbar (R-154).",
            },
        ],
    ) as decision:
        session.flush()
        decision_id = decision.id

    report = erase_member(session, store, member_id=member_id)
    payload = report.as_dict()
    payload["decision_id"] = decision_id
    payload["decision_was_redacted_with_the_rest"] = True
    payload["irreversible"] = True
    return payload
