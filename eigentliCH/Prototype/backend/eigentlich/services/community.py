"""S-13, Community. Lectures, café evenings and meet-ups, and the attendance that is never a score.

**R-222 is a vocabulary rule and this module treats it as one.** "Events" in the interface means LIFE
events — S-09's seven. A lecture is a lecture. `models/access.py` makes the point by not naming its table
`Event`; this module makes it by refusing to store a gathering whose own title calls it one. A word filter
on member-visible copy is a strange thing to find in a service layer, and it is here because the rule is
about words, and the titles are written by whoever schedules the gathering rather than by anybody who has
read the specification.

**R-221 is held by there being nothing to show.** Attendance is recorded, and it is an input to community
presence for Market Place standing (C-08 names it as one of the three permitted ranking inputs). It is not
shown to the member as a score, so no member-facing payload here carries a count, a total, a streak or a
share, and `Attendance` has no such column for one to be built from. `presence_evidence` — the ranking
side — returns the recorded attendances themselves rather than a number, so that the one function that
exists for standing still has no tally in it for a payload to pick up by accident.

**Where the German words for the three kinds are not.** A gathering's `kind` comes back as its key —
`lecture`, `cafe_evening`, `meetup`. The words a member reads are the client's own chrome and live in its
string table, which this change does not own. A label invented here would be a second place the product
names these things, and R-222 is precisely a rule about how the product names things.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attendance, GATHERING_KINDS, Gathering

#: R-222. The word a gathering is never called, in both languages (A12 makes every copy rule two).
#:
#: `Veranstaltung` is on the list with the English: it is the generic German word this rule exists to keep
#: out, and letting it through would hold R-222 in English only. Matching is whole-word, so a compound
#: that happens to contain one of these — `Veranstaltungsreihe` — is not caught; that is the same choice
#: `test_content.py` documents, and for the same reason.
FORBIDDEN_GATHERING_WORDS = ("event", "events", "anlass", "anlässe", "anlaesse", "veranstaltung",
                             "veranstaltungen")


class GatheringCalledAnEvent(ValueError):
    """R-222. A gathering whose title or description calls it an event.

    Raised rather than rewritten. The fix is a better name for the gathering, and only the person
    scheduling it knows what that is.
    """


def _forbidden_words(text: str | None) -> list[str]:
    """Whole-word matching, for the reason `test_content.py::_whole_words` records at length.

    Substring matching would fire on `Eventualverbindlichkeit` and on any German compound built from
    `Anlass`, and a filter that damages good copy is one somebody eventually removes.
    """
    if not text:
        return []
    body = text.lower()
    return [w for w in FORBIDDEN_GATHERING_WORDS if re.search(r"\b" + re.escape(w) + r"\b", body)]


def create_gathering(
    session: Session,
    *,
    kind: str,
    title: str,
    held_on: date,
    description: str | None = None,
    location: str | None = None,
    fictional: bool = False,
) -> Gathering:
    """R-220. A scheduled item: a lecture, a café evening or a meet-up.

    `fictional` follows A41: seeded demonstration gatherings mark themselves in the data, so that a
    screenshot of the community screen cannot be mistaken for a programme anybody can attend.
    """
    if kind not in GATHERING_KINDS:
        raise ValueError(
            f"unknown gathering kind {kind!r}; expected one of {list(GATHERING_KINDS)}. R-220 names three: "
            f"lectures, café evenings and meet-ups."
        )

    offending = _forbidden_words(title) + _forbidden_words(description)
    if offending:
        raise GatheringCalledAnEvent(
            f"R-222: 'events' in the interface means LIFE events (S-09). A gathering is a lecture, an "
            f"evening or a meet-up. Found {offending} in the title or description."
        )

    gathering = Gathering(
        kind=kind,
        title=title,
        description=description,
        held_on=held_on,
        location=location,
        fictional=fictional,
    )
    session.add(gathering)
    return gathering


def record_attendance(
    session: Session, *, member_id: str, gathering_id: str, attended: bool = True
) -> Attendance:
    """R-220 / R-221. Recorded once per member and gathering.

    Idempotent by (member, gathering): attending twice is not a thing that happened twice, and a second
    row would be the beginning of a tally that R-221 says the member must never be shown.
    """
    existing = session.execute(
        select(Attendance).where(
            Attendance.member_id == member_id, Attendance.gathering_id == gathering_id
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.attended = attended
        return existing

    row = Attendance(member_id=member_id, gathering_id=gathering_id, attended=attended)
    session.add(row)
    return row


def _attended_ids(session: Session, member_id: str | None) -> set[str]:
    if member_id is None:
        return set()
    rows = session.execute(
        select(Attendance.gathering_id).where(
            Attendance.member_id == member_id, Attendance.attended.is_(True)
        )
    ).scalars()
    return set(rows)


def gatherings(
    session: Session,
    *,
    member_id: str | None = None,
    on_or_after: date | None = None,
) -> dict:
    """S-13, the member-facing payload. Scheduled items, and whether this member was at each one.

    **`attended` per gathering is a fact; a count of them would be a score.** R-221 forbids the second, not
    the first — a member looking at a lecture they went to should see that they went. What is absent, and
    absent by never being computed, is any aggregate: no total, no count, no streak, no share, no standing.

    `member_id` is optional: without one this is the programme as anybody would see it.
    """
    query = select(Gathering)
    if on_or_after is not None:
        query = query.where(Gathering.held_on >= on_or_after)
    rows = session.execute(query.order_by(Gathering.held_on)).scalars().all()

    attended = _attended_ids(session, member_id)

    return {
        "member_id": member_id,
        "gatherings": [
            {
                "id": row.id,
                # R-222. The key, not a word. The words live in the client's string table.
                "kind": row.kind,
                "title": row.title,
                "description": row.description,
                "held_on": row.held_on.isoformat(),
                "location": row.location,
                # A41, carried through so the marker survives into what is rendered.
                "fictional": bool(row.fictional),
                "attended": row.id in attended if member_id is not None else None,
            }
            for row in rows
        ],
        # R-220. The three kinds, named once, so a client filter and this service cannot drift apart.
        "kinds": list(GATHERING_KINDS),
        # R-221, said out loud in the payload: a client author meets the rule before designing a tile that
        # would need a number in it.
        "attendance_is_not_scored": True,
        # NO count, NO total, NO streak, NO share, NO standing — R-221 and C-07. Nothing above computes
        # one, so there is nothing here to have left out.
    }


def presence_evidence(session: Session, *, member_id: str) -> list[dict]:
    """R-221's other half, and C-08's third permitted ranking input. **Not a member-facing payload.**

    Community presence is an input to Market Place standing, and the Market Place ranking function is the
    only caller this exists for. It returns the attendances themselves — which gathering, of what kind, on
    what date — rather than a number, for two reasons: a ranking that wants to weigh a lecture differently
    from a meet-up needs the kinds, and a function that returned an integer would be one `import` away
    from appearing on a member's screen as one.

    Callers must not put the result, or its length, into anything a member reads. R-221.
    """
    rows = session.execute(
        select(Attendance, Gathering)
        .join(Gathering, Attendance.gathering_id == Gathering.id)
        .where(Attendance.member_id == member_id, Attendance.attended.is_(True))
        .order_by(Gathering.held_on)
    ).all()

    return [
        {"gathering_id": gathering.id, "kind": gathering.kind, "held_on": gathering.held_on.isoformat()}
        for _attendance, gathering in rows
    ]
