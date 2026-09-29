"""The Feed. Item 5, in the Reading Room's own shape.

    "Rename `wisdom` to `know` and restructure it on the pattern of https://stk.sim-tech.ch/. Open that
     page and read its actual structure before building — it organises around **pinned groups, pinned
     follows and pinned vaults**, and that is the shape to reuse rather than a generic article list."

The page was read on 4 September 2026. Its three section labels are exactly those, under the heading
"Share the Know — Prototype", and they are reused here.

===========================================================================================================
TWO OF THE THREE HAVE NO OBJECT BEHIND THEM, AND SAY SO
===========================================================================================================

  * **groups** — `Gathering` exists (S-13) and is never seeded, so it is empty in any running copy. That is
    already recorded in `PICK-UP-HERE.md` as an open item, not discovered here.
  * **follows** — there is no follow relation in this build at all. No table, no route, nothing.
  * **vaults** — the learning units, which are real, and which now carry item 5's content hooks.

They are rendered empty **with their reason** rather than omitted or filled with something invented. That
is the treatment the owner chose for the community recovery on the same day (A124), and the argument is the
same: a section that is missing looks like a build error, a section filled with placeholders is a lie, and
a section that says what it is waiting for is the truth.

**Why keep an empty section at all.** The shape is the instruction. A Feed that quietly dropped two of the
three would be the "generic article list" the script names as the thing to avoid, and reintroducing them
later would be a second decision nobody would remember to take.

===========================================================================================================
"VAULT" MEANS TWO DIFFERENT THINGS AND THAT IS WORTH SAYING OUT LOUD
===========================================================================================================

The Reading Room's "pinned vaults" are collections of reading. This application's **Vault** is the member's
own plan — goals, actions, documents, decisions — and item 4 makes it a door. They are not the same thing
and nothing here joins them.

The section key stays `vaults` because the instruction is to reuse the Reading Room's shape and renaming
it would make the two pages harder to compare. The member-facing label does not use the word: see
`feed.section_vaults` in the string table, which calls it what it is.

===========================================================================================================
ORDERING
===========================================================================================================

Item 5's return behaviour: "When the member opens the app, the Know's feed is ordered by what follows from
what they have read and what is in their Vault. Not an interruption, so Principle 4 does not govern it."

**Not implemented, and not faked.** Nothing records what a member has read — there is no read receipt in
this build — so an ordering claiming to follow from it would be an ordering that follows from nothing. The
items come back in the content file's own order, and `ordered_by` says so in the payload rather than
leaving a client to assume relevance.

**No outbound channel exists and none is added.** Item 5 is explicit — "Do not build an outbound channel,
and do not add one behind a flag" — and this module has no notion of notifying anybody.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Gathering
from .hooks import learning_items

#: The Reading Room's three sections, in its own order. Reused rather than renamed — see the docstring.
SECTIONS = ("groups", "follows", "vaults")

#: Why a section is empty, when the reason is structural rather than "this member has none". A key, not a
#: sentence: the wording is the client's and lives in the string table.
NO_OBJECT = {
    "groups": "no_gathering_is_seeded",
    "follows": "no_follow_relation_exists",
}


def _groups(session: Session) -> list[dict]:
    """Gatherings. Real, and empty in any running copy until somebody seeds one."""
    rows = session.execute(select(Gathering).order_by(Gathering.id)).scalars().all()
    return [{"key": row.id, "title": row.title, "kind": row.kind} for row in rows]


def read(session: Session, *, member_id: str) -> dict:
    """The Feed, as three sections.

    Takes a member because the hooks do — item 5: "Inputs already in the Vault are skipped." Nothing else
    here reads the member's plan, and the hook reports only which inputs are still wanted, never a figure.
    """
    sections = {
        "groups": {"items": _groups(session), "empty_reason": NO_OBJECT["groups"]},
        # No table, no route, nothing. Reported rather than omitted.
        "follows": {"items": [], "empty_reason": NO_OBJECT["follows"]},
        "vaults": {"items": learning_items(session, member_id=member_id), "empty_reason": None},
    }
    for name in SECTIONS:
        block = sections[name]
        # A reason is for a section that CANNOT be filled. One that merely happens to be empty for this
        # member carries none, and the client says something different about the two.
        if block["items"]:
            block["empty_reason"] = None

    return {
        "sections": [{"key": name, **sections[name]} for name in SECTIONS],
        # Item 5's ordering is not implemented and is not faked. Said in the payload so a client does not
        # render these as "most relevant first".
        "ordered_by": "content_order",
        "ordering_note": "no_read_history_recorded",
    }


__all__ = ["NO_OBJECT", "SECTIONS", "read"]
