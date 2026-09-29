"""The curator directory: who a member may ask for, and the guard that keeps C-10 honest.

**Why this exists at all.** `CuratorSession.curator_id` is documented "the identified curator. Never a
role, never a queue" — and until now nothing in the API could tell a member who that person might be. The
client's own comment said so and refused to invent one, which was the right refusal and a dead end: R-173
requires the session to record WHO, so a named person has to exist before the session does.

**Two jobs, deliberately separated.**

  * `list_curators` answers "who can I talk to". That is the member's question, and it is not a sensitive
    one — it is the staff list of a firm you are already a member of.
  * `resolve_curator` answers "is this a real curator". That is C-10's question, and it is asked on the
    way into every session this module opens, so the recorded "who" is a row in `curators` rather than a
    string a caller chose.

They give different answers on purpose. See the note on `fictional` in `list_curators`.

**This module writes nothing itself.** `open_identified_session` resolves the curator and then hands the
write to `services.know.open_curator_session`, which is the member-side opener the Curator button has
always used. A second implementation of "insert a CuratorSession and append its `opened` event" is a
second place for the audit's shape to drift, and C-10's value is that there is one shape.

**`resolve_curator` is called twice on that path now, and deliberately.** The opener resolves as well, since
31 August 2026 — it was the layer A67 left taking the id on trust, and it is reachable by callers who never
came through this module. Two lookups of a primary key is not a cost worth a comment; one unresolved write
into `curator_sessions` is, and the column is a foreign key underneath both (A98).

**Nothing here is gated on an AccessGrant, and that is not an oversight.** R-210 gates a curator reading a
member's material. This is a member reading a staff list: no member's material is reachable through any
function in this file, so `services/curator.py`'s `MEMBER_READS` registry is untouched by it — no function
here takes both a `member_id` and a `curator_id` except `open_identified_session`, which reads nothing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import Curator
from ..models.curator import CuratorSession
from .know import open_curator_session

#: Exactly what the directory says about a person, and the test asserts this is the whole of it.
#:
#: Written as a constant rather than left implicit in a dict literal so that adding a field is a visible
#: edit to a named list. What is missing is the point: no email (a member does not need a staff address to
#: press a button, and publishing one turns the directory into a mailing list), no password or
#: `must_change` state (the member's business is who exists, not who has logged in), no `fictional` flag
#: (see below), and nothing about which members a curator serves — that last one is a grant, it belongs to
#: the member who made it, and R-210 refuses to say it even to the curator without one.
DIRECTORY_FIELDS = ("id", "display_name", "role_label")


class NoSuchCurator(Exception):
    """C-10. The named party is not a curator, so no session may record them as one.

    Its own exception rather than `CuratorAuthenticationFailed`: nobody is authenticating here. A member
    naming a curator that does not exist has not failed a login, and saying so in the type keeps the two
    failures from being handled as one at the edge.
    """


def list_curators(db: DbSession) -> list[dict]:
    """R-170 / R-173. The people a member can ask to speak to.

    Active curators only. An inactive row is a person who has left, and offering them is offering a
    conversation that will not happen.

    **A62: the demonstration curator is not listed, and the five real ones are.** The decision is
    deliberate and could have gone the other way, so here is the reasoning. The directory is answering
    "who can I talk to", and "Demo Kuratorin" is not an answer to it: a member who picks her opens a real
    audit row about a consultation that nobody will hold. The alternative — list her and mark her — is
    worse, because the mark would have to be rendered on a card that otherwise names real colleagues, and
    a `fictional` flag shown beside a person reads as a judgement about that person rather than as a fact
    about a seeded account. So she is omitted here and left entirely usable everywhere else: she still
    logs into the workbench (A40), still resolves through `resolve_curator`, and still carries a
    walkthrough. Not offered is not deleted.

    R-113 / C-07: a list, and nothing counting it. No total, no "n curators available", no badge — the
    caller renders the people it was given.
    """
    rows = db.execute(
        select(Curator)
        .where(Curator.in_service, Curator.fictional.is_(False))
        # Stable and human: the order a staff list is read in, not insertion order, which would put
        # whoever was seeded first at the top of every member's chooser forever.
        .order_by(Curator.display_name)
    ).scalars().all()
    return [{field: getattr(row, field) for field in DIRECTORY_FIELDS} for row in rows]


def resolve_curator(db: DbSession, curator_id: str | None) -> Curator:
    """C-10. The "who" on a session is a row in `curators`, or there is no session.

    `None`, `""`, `"   "` and `"unassigned"` all fail here, and they fail for the same single reason —
    there is no such curator. Deliberately not a blocklist of placeholder words: a list of forbidden names
    is a list to maintain, and it is defeated by spelling the placeholder differently. "It must be a row"
    needs no maintenance and has no synonyms.

    Out of service is refused too, matching `services.curator.require_curator`. The two are separate
    functions because that one guards a curator acting and this one guards a member naming; they agree
    today, and the day they stop agreeing it should be visible rather than accidental.

    Since A160 they agree by construction rather than by coincidence: both ask `Curator.in_service`, which
    is the single place `active` and `revoked_at` are combined.
    """
    if not isinstance(curator_id, str) or not curator_id.strip():
        raise NoSuchCurator(
            "C-10: a curator session records an identified curator. No curator was named, and an "
            "unnamed party is not written into an audit table that is only worth having because it is true."
        )
    row = db.get(Curator, curator_id.strip())
    if row is None:
        raise NoSuchCurator(
            f"C-10: {curator_id!r} is not a curator. The session records the identified curator, never a "
            f"role and never a queue."
        )
    if not row.in_service:
        raise NoSuchCurator(
            f"C-10: curator {curator_id!r} is not in service and cannot be named on a session"
        )
    return row


def open_identified_session(
    db: DbSession, *, member_id: str, curator_id: str | None, opened_from: str
) -> CuratorSession:
    """R-173 / C-10. The Curator button's opener, with the curator resolved before anything is written.

    `opened_from` is passed through untouched: "where were they when they needed a human" is recorded at
    the time or not at all, and this function is not the place to normalise or shorten it.

    The resolved row's `id` is what goes onto the session, not the string that arrived. They are equal
    today up to surrounding whitespace, and passing the row's own id means the column holds something that
    was read out of `curators` rather than something that merely matched it.
    """
    curator = resolve_curator(db, curator_id)
    return open_curator_session(
        db, member_id=member_id, curator_id=curator.id, opened_from=opened_from
    )


__all__ = [
    "DIRECTORY_FIELDS",
    "NoSuchCurator",
    "list_curators",
    "open_identified_session",
    "resolve_curator",
]
