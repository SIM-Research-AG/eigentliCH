"""Stating, superseding and reading the five member facts. The instrument is the only registry.

The requirement this module exists to satisfy, from the sim-tech task the owner closed on 4 September 2026:

    "Build the instrument so keys can be added without touching the intake flow."

So there is **no list of keys in this file**. Which keys exist, what type each is, what options a choice
offers and what data class each answer carries are all read from `client/content/onboarding-questions.json`
— any question whose `fills.entity` is `member_fact`. A sixth key is one entry in that file; the only thing
that would have to change here is nothing.

That is a claim about the code and it is tested as one: `test_member_fact.py` plants a question the build
has never seen, writes it, reads it back and asserts the value survived, with no import of this module's
internals in between.

===========================================================================================================
WHAT IS VALIDATED, AND WHY IT IS VALIDATED HERE RATHER THAN AT THE ROUTE
===========================================================================================================

A `choice` answer must be one of the declared options; a `number` must be a number within the declared
bounds; a `text` answer is text. That check runs in this service, not in a request model, for the same
reason `MINIMUM_AGE` is a CHECK constraint as well as a validator: **a validator in a request model is
bypassed by anything that is not that request model**, and this build already has three writers that are
not — the intake, `tools/load_submission.py`, and a curator recording a session.

The bounds are the question's own (`min`, `max`), read rather than repeated. C-02 is not engaged: a
network of at most 200 people is not a rate and nothing compounds it, but it is still an editorial number
and it still belongs in the content file rather than here.

===========================================================================================================
WRITING ONE IS A PLAN MUTATION
===========================================================================================================

`MemberFact` is `PlanMutable`, so `state()` must be called inside `mutate_plan` and C-09's guard refuses it
otherwise. That is not ceremony: a member who changes canton has changed the tax path their whole plan
rests on, and "when did this become true, and who said so" is exactly what a Decision records.

**The superseding write is two statements and they are ordered.** The standing row is marked superseded
and flushed BEFORE the new row is added, because `uq_member_facts_one_current` is a partial unique index
over the rows that are still current — inserting first leaves two current rows for the instant between,
and SQLite checks a unique index at the statement, not at commit. This is why `models/member_fact.py`
records the date rather than a pointer at the successor: a pointer cannot be written in that order at all,
since the row it would name does not exist yet.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import onboarding_questions
from ..models import DataClass, Decision, MemberFact
from ..models.household import STATED_BY

#: The `fills.entity` that marks a question as collecting a member fact rather than filling a Position,
#: a Goal or the household. Named once: `services/onboarding.py` reads this rather than the string.
FILLS_ENTITY = "member_fact"

#: The question types this module can store. A declared type outside this set is refused at import of the
#: declaration rather than at the write, so a content edit that nothing could store fails loudly and early.
STORABLE_TYPES = ("choice", "number", "text")


class UnknownFact(KeyError):
    """A key the instrument does not declare. Refused rather than stored loose."""


class UndeclarableFact(ValueError):
    """The instrument declares a key this build cannot store — a bad content edit, not a bad answer."""


class RefusedValue(ValueError):
    """An answer the question's own declaration does not admit."""


def declarations() -> dict[str, dict]:
    """Every member-fact key the instrument declares, with what is needed to store and check it.

    Reads the content file on every call rather than caching at import. The file is small, and a cache
    here would mean a test that plants a question has to know to clear it — which is precisely the coupling
    the "no code change for a new key" requirement is about.
    """
    found: dict[str, dict] = {}
    for record in onboarding_questions():
        fills = record.get("fills") or {}
        if fills.get("entity") != FILLS_ENTITY:
            continue

        key = fills.get("key") or record["key"]
        kind = record.get("type")
        if kind not in STORABLE_TYPES:
            raise UndeclarableFact(
                f"onboarding question {record['key']!r} fills a {FILLS_ENTITY} with type {kind!r}, which "
                f"is not one of {list(STORABLE_TYPES)}. Nothing could store the answer, so the question "
                f"would be asked and dropped."
            )

        declared_class = fills.get("data_class")
        try:
            data_class = DataClass[str(declared_class)]
        except KeyError:
            raise UndeclarableFact(
                f"onboarding question {record['key']!r} declares data_class {declared_class!r}. C-04 "
                f"requires one of {[one.name for one in DataClass]}, and there is deliberately no "
                f"default — an answer whose author did not think about its class is the answer the "
                f"logging filter gets wrong."
            ) from None

        if kind == "choice" and not record.get("options"):
            raise UndeclarableFact(
                f"onboarding question {record['key']!r} is a choice with no options. A member would be "
                f"shown a control with nothing in it."
            )

        found[key] = {
            "question_key": record["key"],
            "type": kind,
            "data_class": data_class,
            "options": [one["value"] for one in record.get("options") or []],
            "min": record.get("min"),
            "max": record.get("max"),
        }
    return found


def declaration(key: str) -> dict:
    try:
        return declarations()[key]
    except KeyError:
        raise UnknownFact(
            f"{key!r} is not a member fact the instrument declares. Known: {sorted(declarations())}"
        ) from None


def check(key: str, value: Any) -> Any:
    """The value as it will be stored, or a refusal. Never a silent coercion of a wrong answer."""
    declared = declaration(key)
    kind = declared["type"]

    if value is None or value == "":
        raise RefusedValue(
            f"{key!r} was given no answer. A skipped question writes no row at all — an empty fact is "
            f"indistinguishable from one the member declined to state, and only one of those is true."
        )

    if kind == "choice":
        # Compared against the declared values, not their labels. A label is a rendering and changes with
        # the language; a member's answer must not.
        if value not in declared["options"]:
            raise RefusedValue(
                f"{value!r} is not one of the options {key!r} offers. The instrument's own list is the "
                f"only source of them, so an answer outside it came from somewhere that is not the "
                f"question."
            )
        return value

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RefusedValue(f"{key!r} takes a number; got {type(value).__name__}.")
        low, high = declared["min"], declared["max"]
        if low is not None and value < low:
            raise RefusedValue(f"{key!r} is bounded below at {low}; got {value}.")
        if high is not None and value > high:
            raise RefusedValue(f"{key!r} is bounded above at {high}; got {value}.")
        return value

    if not isinstance(value, str):
        raise RefusedValue(f"{key!r} takes text; got {type(value).__name__}.")
    text = value.strip()
    if not text:
        raise RefusedValue(f"{key!r} was answered with whitespace, which is a skipped question.")
    return text


def current(session: Session, *, member_id: str) -> dict[str, MemberFact]:
    """The standing statement per key. Superseded rows are history and are not returned."""
    rows = session.execute(
        select(MemberFact).where(
            MemberFact.member_id == member_id,
            MemberFact.superseded_on.is_(None),
        )
    ).scalars()
    return {row.stated_key: row for row in rows}


def values(session: Session, *, member_id: str) -> dict[str, Any]:
    """Just the answers, for the callers that want a dict rather than rows."""
    return {key: row.stated_value for key, row in current(session, member_id=member_id).items()}


def state(
    session: Session,
    *,
    member_id: str,
    key: str,
    value: Any,
    decision: Decision,
    on: date | None = None,
    by: str = "member",
) -> MemberFact:
    """Record a fact, superseding whatever stood before it. A plan mutation — call inside `mutate_plan`.

    `on` defaults to today, which is the one place a default is right: a member answering in the app is
    describing today. A curator recording last week's session passes last week, exactly as
    `onboarding.composition_as_of` does.
    """
    if by not in STATED_BY:
        raise RefusedValue(f"{by!r} is not an initiator; expected one of {', '.join(STATED_BY)}.")

    declared = declaration(key)
    stored = check(key, value)
    describes = on or date.today()

    # **`no_autoflush` around the read, and it is the whole reason this function is shaped like this.**
    # `current` issues a SELECT, a SELECT triggers autoflush, and autoflush writes everything pending —
    # including the Decision `mutate_plan` is still assembling. Once that Decision is on disk, the
    # `linked_facts.append` below modifies a written Decision and R-040's guard refuses it, correctly.
    # The failure reads as "a Decision is immutable" and has nothing to do with immutability.
    with session.no_autoflush:
        standing = current(session, member_id=member_id).get(key)

    if standing is not None and describes < standing.stated_on:
        raise RefusedValue(
            f"{key!r} already has a statement describing {standing.stated_on.isoformat()}, and this "
            f"one describes {describes.isoformat()}. Recording an earlier statement as the current "
            f"one would make the standing fact older than the history behind it."
        )

    row = MemberFact(
        member_id=member_id,
        stated_key=key,
        stated_value=stored,
        stated_on=describes,
        stated_by=by,
        # From the key's own declaration, not from the entity. See `models/member_fact.py`: the entity
        # constant governs the log filter, the row value governs the export and any retention sweep.
        data_class=int(declared["data_class"]),
    )

    # Linked BEFORE anything is flushed, so the Decision is still pending when it gains this row. The
    # append cascades `row` into the session, so no `session.add` is needed or wanted.
    decision.linked_facts.append(row)

    # Ordered, and the order is the index's — see the module docstring. A targeted flush, because a full
    # one would emit this UPDATE and the INSERT above in the mapper's order, which puts the INSERT first
    # and leaves two current rows at the moment `uq_member_facts_one_current` is checked. The Decision is
    # not in the list and is not related to `standing` in the direction that cascades, so it stays
    # pending and stays writable.
    if standing is not None:
        # **Linked too, and C-09 was right to insist.** Ending a statement is a change to the plan as
        # surely as beginning one — the old row is `PlanMutable` and it is being modified — so the guard
        # refused a Decision that covered only the new row. It reads better on S-07 as well: one Decision
        # holding the canton that stopped applying and the one that replaced it is the whole change,
        # where a Decision naming only the new row would leave the member wondering what it replaced.
        decision.linked_facts.append(standing)
        standing.superseded_on = describes
        session.flush([standing])

    return row


__all__ = [
    "FILLS_ENTITY",
    "RefusedValue",
    "STORABLE_TYPES",
    "UndeclarableFact",
    "UnknownFact",
    "check",
    "current",
    "declaration",
    "declarations",
    "state",
    "values",
]
