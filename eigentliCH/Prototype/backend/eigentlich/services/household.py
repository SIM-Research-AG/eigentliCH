"""Household composition: stating it, reading it, and refusing to guess it.

The one load-bearing input the system cannot detect for itself. It sets the AHV path, the tax path, goal
ownership and the human role vector, and no aggregation, document or re-solve reveals that it changed.
Everything this module does follows from that sentence.

===========================================================================================================
THREE THINGS THIS MODULE WILL NOT DO
===========================================================================================================

**It will not invent a household for a member who has not stated one.** `current()` returns `None`, and
`describe()` says `stated: false`. The tempting alternative — treat an unstated composition as a
single-member household, since most members are single — is wrong for a reason that only shows up later:
`composition_as_of` would then carry a date nobody gave, the twelve-month currency horizon would run off
that invented date, and in a year the product would report a household as needing re-confirmation when it
had never been confirmed in the first place. An unstated composition is a gap; a guessed one is a fact.

**It will not derive `kind` from an age.** A dependant is who the household says is a dependant. The build
holds `Member.age_at_registration` and nothing else about anybody's age, and a 19-year-old in an
apprenticeship is a dependant in one household and an adult in the next. Deriving it would be a threshold,
and a threshold is an assumption nobody has published (C-02).

**It will not write a composition without a Decision.** `Household` and `HouseholdMember` are
`PlanMutable`, so this is not a matter of discipline here — `db.py`'s `before_flush` guard raises. The
constructor below goes through `mutate_plan`, which is the seam that writes both halves in one transaction.

===========================================================================================================
WHY `stated_by` IS RECORDED AND NOTHING BRANCHES ON IT
===========================================================================================================

The update script's item 3 requires the same intake to be drivable by a curator on the member's behalf and
to produce the same versioned plan: "one code path, two initiators — record which one". So `state()` takes
`stated_by` and stores it, and no function in this module reads it back to decide anything. The moment a
curator-stated composition takes a different path from a member-stated one, the two initiators stop
producing the same plan and the requirement is broken quietly. A test asserts the value is never read as a
condition.

The Decision written alongside carries the real attribution — `author` and `author_ref` — which is where a
reader looks for who did it. `stated_by` is the household's own copy of that, so a composition can say what
it is without joining to a Decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import (
    household_confirmation_keys,
    household_change_signals,
    observable_household_signals,
)
from ..models import (
    ADULT,
    ActionItem,
    DEPENDANT,
    Goal,
    HOUSEHOLD_MEMBER_KINDS,
    STATED_BY,
    Household,
    HouseholdMember,
)
from .derive import (
    CAUSE_NO_LONGER_HOLDS,
    HOUSEHOLD_CHANGE_INFERRED,
    prepared_options_for,
)
from .plan import mutate_plan


class CompositionNotStated(LookupError):
    """No household has been stated for this member.

    A distinct exception rather than `None` at the call sites that cannot proceed without one, so that
    "the member has not told us yet" never gets confused with "the member lives alone".
    """


class InvalidComposition(ValueError):
    """The stated composition is not one a household can have."""


class InvalidConfirmation(ValueError):
    """The answer set does not match the published confirmation items."""


class AlreadyClosed(ValueError):
    """This household is already closed. Closing it twice would create a second set of successors."""


class NotSeparable(ValueError):
    """This household cannot be closed as a separation.

    A single-adult household has nobody to separate from. What that member wants is either to leave the
    product — which is R-231's erasure and destroys rather than preserves — or to restate their
    composition. Closing it would create a successor household identical to the one just closed, and a
    lineage of empty steps is worse than a refusal with a reason.
    """


class UnknownSignal(ValueError):
    """A flag was raised by a signal nobody published.

    The set is closed on purpose: a flag whose cause is a caller's free string is a flag nobody can
    explain to the member, and "why am I being asked this?" is the first question it provokes.
    """


@dataclass(frozen=True)
class Person:
    """One person to record in a household, as the caller states them.

    `member_id` is the account, where there is one. A partner who has not signed up is a `Person` with
    `member_id=None` and is a full household member in every other respect — see the model.
    """

    label: str
    kind: str = ADULT
    member_id: str | None = None
    joined_on: date | None = None


def _validate(people: Sequence[Person], *, member_id: str) -> None:
    if not people:
        raise InvalidComposition(
            "a household has at least one person in it. An empty composition is not the single-member "
            "case; it is an unanswered question, and the caller should not have reached here."
        )

    for person in people:
        if person.kind not in HOUSEHOLD_MEMBER_KINDS:
            raise InvalidComposition(
                f"{person.kind!r} is not a household member kind; expected one of "
                f"{', '.join(HOUSEHOLD_MEMBER_KINDS)}."
            )
        if not person.label.strip():
            raise InvalidComposition(
                "every person in a household carries a label — what the member calls them. A blank label "
                "is a row nobody can point at when a goal has to be divided."
            )

    if not any(person.kind == ADULT for person in people):
        raise InvalidComposition(
            "a household with no adult in it has nobody who can own a goal, and the member stating it is "
            "an adult by construction (the age floor is enforced at registration)."
        )

    accounts = [person.member_id for person in people if person.member_id is not None]
    if len(set(accounts)) != len(accounts):
        raise InvalidComposition("one account appears twice in the same household.")
    if member_id not in accounts:
        raise InvalidComposition(
            f"the member stating the composition ({member_id}) is not in it. A household somebody "
            f"describes from outside is not their household, and the plan would have no subject."
        )


def state(
    session: Session,
    *,
    member_id: str,
    people: Sequence[Person],
    as_of: date,
    stated_by: str = "member",
    author_ref: str | None = None,
    curator_session_id: str | None = None,
) -> Household:
    """Record a household composition. Writes the Decision C-09 requires, in the same transaction.

    `as_of` is the date the composition *describes*, and it is required rather than defaulted to today.
    A curator recording a session held last week stamps last week; defaulting would silently stamp the day
    the row was typed, and every currency judgement downstream would then be measured from the wrong end.

    Raises:
        InvalidComposition: When the stated people are not a household. Nothing is written.
    """
    if stated_by not in STATED_BY:
        raise InvalidComposition(
            f"{stated_by!r} is not an initiator; expected one of {', '.join(STATED_BY)}."
        )
    _validate(people, member_id=member_id)

    adults = sum(1 for person in people if person.kind == ADULT)
    dependants = sum(1 for person in people if person.kind == DEPENDANT)

    with mutate_plan(
        session,
        member_id=member_id,
        question="What is the household this plan is for?",
        # Counts, not labels. The Decision is readable by a curator and by an export, and a member's own
        # word for their partner is `quoted` material that does not belong in a composed sentence.
        choice=f"{adults} adult(s), {dependants} dependant(s), as of {as_of.isoformat()}",
        author=stated_by,
        author_ref=author_ref,
        curator_session_id=curator_session_id,
        reasoning=(
            "Household composition sets the AHV path, the tax path, goal ownership and the human role "
            "vector. It is stated rather than inferred because nothing in the system can detect it."
        ),
    ) as decision:
        household = Household(
            composition_as_of=as_of,
            stated_by=stated_by,
        )
        session.add(household)
        decision.linked_households.append(household)

        for person in people:
            row = HouseholdMember(
                household=household,
                member_id=person.member_id,
                label=person.label.strip(),
                kind=person.kind,
                joined_on=person.joined_on,
            )
            session.add(row)
            decision.linked_household_members.append(row)

        # A full restatement answers whatever the inference layer was asking about, whether or not the
        # answer matches the signal. `flag_inferred_change` raises it again if the signal fires afresh.
        _close_inferred_flags(session, member_id=member_id)

    return household


def _close_inferred_flags(session: Session, *, member_id: str) -> list[ActionItem]:
    """Close any open inferred-change flag. The question has been answered, so it stops being prepared.

    **Only the inferred kind.** `HOUSEHOLD_CONFIRMATION_DUE` is state-based and `derive_action_items`
    closes it on its own once `composition_as_of` is fresh — closing it here as well would be a second
    place that owns one item's life, which is the drift this estate has paid for twice (A63's triggers,
    A40's `curator_id`).

    An item the MEMBER closed — acted, dismissed — is left alone, the same rule `derive.py` states: a
    member who dismissed something and finds it altered is being managed.
    """
    open_flags = list(
        session.execute(
            select(ActionItem).where(
                ActionItem.member_id == member_id,
                ActionItem.trigger_kind == HOUSEHOLD_CHANGE_INFERRED,
                ActionItem.status == "open",
            )
        ).scalars()
    )
    for flag in open_flags:
        flag.status = CAUSE_NO_LONGER_HOLDS
    return open_flags


def flag_inferred_change(
    session: Session,
    *,
    member_id: str,
    signal: str,
) -> ActionItem | None:
    """Item 6's inferred half. A visible event raises a flag for confirmation and changes NOTHING.

    Returns the flag, or the existing one if this signal already raised it and the member has not yet
    answered. Returns `None` when the member has already spoken on it — a dismissed flag is not re-raised
    by the same signal firing again, which is the difference between a prepared question and a nag.

    **It writes no Decision and touches no plan row.** That is the whole point of a flag: the app noticed
    something and has not concluded anything. `partner_invited` firing does not make the household two
    adults — it makes the question worth asking at the next return, with the answer left to the member.

    Raises:
        UnknownSignal: The signal is not in the published set.
    """
    published = {one["key"] for one in household_change_signals()}
    if signal not in published:
        raise UnknownSignal(
            f"{signal!r} is not a published household-change signal. Known: "
            f"{', '.join(sorted(published))}. Publishing one is an editorial act, in "
            f"client/content/household-confirmation.json, and each entry says whether this build can "
            f"actually observe it."
        )

    existing = session.execute(
        select(ActionItem).where(
            ActionItem.member_id == member_id,
            ActionItem.trigger_kind == HOUSEHOLD_CHANGE_INFERRED,
            ActionItem.derived_from == signal,
        )
    ).scalar_one_or_none()
    if existing is not None:
        # `open` -> already prepared, hand back the same row. `expired` -> the signal fired again after a
        # confirmation, so the question is live once more. `acted`/`dismissed` -> the member has spoken.
        if existing.status == CAUSE_NO_LONGER_HOLDS:
            existing.status = "open"
            return existing
        return existing if existing.status == "open" else None

    flag = ActionItem(
        member_id=member_id,
        trigger_kind=HOUSEHOLD_CHANGE_INFERRED,
        # No due date. A flag is not a deadline — it surfaces at the next return, which is when the member
        # comes back, not on a date the app picked.
        due_date=None,
        derived_from=signal,
        prepared_options=prepared_options_for(HOUSEHOLD_CHANGE_INFERRED, signal),
    )
    session.add(flag)
    return flag


def signals(session: Session, *, member_id: str) -> dict:
    """What the inference layer can see, and what it has raised for this member.

    `observable_now` is published per signal and is mostly `false` in Phase 0 — item 6's own note is that
    inference is largely the partner-invite signal until aggregation is live, and that the flag mechanism
    gets built anyway. Reporting the unobservable ones with their reason is what stops the emptiness
    reading as "nothing ever happens here".
    """
    raised = {
        row.derived_from: row.status
        for row in session.execute(
            select(ActionItem).where(
                ActionItem.member_id == member_id,
                ActionItem.trigger_kind == HOUSEHOLD_CHANGE_INFERRED,
            )
        ).scalars()
    }
    return {
        "observable_now": list(observable_household_signals()),
        "published": [
            {
                "key": one["key"],
                "observable_now": bool(one.get("observable_now")),
                "not_yet": one.get("not_yet"),
                "raised": raised.get(one["key"]),
            }
            for one in household_change_signals()
        ],
    }


@dataclass(frozen=True)
class Confirmation:
    """The result of the annual review's structured confirmation."""

    #: True when every item was answered no. The composition then stands, re-dated.
    unchanged: bool
    #: The item keys the member answered yes to. Empty when `unchanged`.
    changed: tuple[str, ...]
    #: The household, re-dated when unchanged and untouched otherwise.
    household: Household
    #: Inferred flags this confirmation resolved.
    flags_closed: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "unchanged": self.unchanged,
            "changed": list(self.changed),
            "household_id": self.household.id,
            "as_of": self.household.composition_as_of.isoformat(),
            "flags_closed": list(self.flags_closed),
            # What the caller has to do next, said in the payload rather than left to be inferred from
            # `unchanged`. A yes means the composition is restated in full through `state()`.
            "restatement_needed": not self.unchanged,
        }


def confirm(
    session: Session,
    *,
    member_id: str,
    answers: dict[str, bool],
    as_of: date,
    stated_by: str = "member",
    author_ref: str | None = None,
    curator_session_id: str | None = None,
) -> Confirmation:
    """The annual review's structured confirmation. Five or six closed items, never a freeform prompt.

    **All no: the same people are re-dated.** `composition_as_of` is updated on the same row, which resets
    the twelve-month horizon and is why horizon expiry and the annual review are the same event in the
    common case. A new `Household` row is deliberately NOT created: nothing about the household changed,
    the plan versions that reference it still reference the right thing, and each version carries its own
    copied `household_as_of` so no history is rewritten by the update.

    **Any yes: nothing is changed, and the flag stays prepared.** A yes/no answer cannot say who joined,
    what they are called, or whether they are an adult or a person in the member's care, so patching the
    composition from one would write facts nobody stated. No Decision is written either — the member said
    something changed and has not yet said what, and a Decision recording a change that was never
    described would be a record of the wrong event. The open action item is left open, so the question is
    still prepared at the next return, and the caller routes to `state()`.

    Raises:
        CompositionNotStated: There is nothing to confirm.
        InvalidConfirmation: The answers do not match the published items exactly.
    """
    if stated_by not in STATED_BY:
        raise InvalidConfirmation(
            f"{stated_by!r} is not an initiator; expected one of {', '.join(STATED_BY)}."
        )

    household = require(session, member_id=member_id)

    published = set(household_confirmation_keys())
    given = set(answers)
    if given != published:
        missing = sorted(published - given)
        extra = sorted(given - published)
        raise InvalidConfirmation(
            f"a confirmation answers exactly the published items. Missing: {missing or 'none'}. "
            f"Not published: {extra or 'none'}. An unanswered item is a question the member was not "
            f"asked, and an extra one is an answer to a question nobody published."
        )
    if not all(isinstance(value, bool) for value in answers.values()):
        raise InvalidConfirmation(
            "every confirmation item is answered yes or no. A missing or third value is not a shorter "
            "answer, it is an unanswered question."
        )

    changed = tuple(key for key in household_confirmation_keys() if answers[key])
    if changed:
        return Confirmation(unchanged=False, changed=changed, household=household)

    with mutate_plan(
        session,
        member_id=member_id,
        question="Is the household unchanged since it was last recorded?",
        choice=(
            f"Confirmed unchanged; re-dated from "
            f"{household.composition_as_of.isoformat()} to {as_of.isoformat()}"
        ),
        author=stated_by,
        author_ref=author_ref,
        curator_session_id=curator_session_id,
        reasoning=(
            "The annual review's structured confirmation, all items answered no. The same people are "
            "re-dated, which resets the composition's validity horizon."
        ),
    ) as decision:
        household.composition_as_of = as_of
        household.stated_by = stated_by
        decision.linked_households.append(household)
        closed = _close_inferred_flags(session, member_id=member_id)

    return Confirmation(
        unchanged=True,
        changed=(),
        household=household,
        flags_closed=tuple(sorted(flag.derived_from or "" for flag in closed)),
    )


@dataclass(frozen=True)
class ClosingReport:
    """What a closing did. Every list is named so a curator can read the consequences before acting."""

    closed_household_id: str
    closing_date: date
    #: `{member_id: new_household_id}` for each adult who had an account.
    successors: dict[str, str]
    #: Adults with no account, who therefore get no successor household. Named, not silently skipped.
    without_an_account: tuple[str, ...]
    #: Goals that followed a single owner into their new household.
    goals_followed: tuple[str, ...]
    #: Goals owned by more than one adult: frozen, flagged, and never split here.
    goals_frozen_for_division: tuple[str, ...]
    #: Goals with no owner recorded. They cannot be divided cleanly and are reported rather than assigned.
    goals_without_an_owner: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "closed_household_id": self.closed_household_id,
            "closing_date": self.closing_date.isoformat(),
            "successors": dict(self.successors),
            "without_an_account": list(self.without_an_account),
            "goals_followed": list(self.goals_followed),
            "goals_frozen_for_division": list(self.goals_frozen_for_division),
            "goals_without_an_owner": list(self.goals_without_an_owner),
            "division_is_a_curators_decision": True,
        }


def close(
    session: Session,
    *,
    household_id: str,
    closing_date: date,
    author: str = "curator",
    author_ref: str | None = None,
    curator_session_id: str | None = None,
) -> ClosingReport:
    """Close a household. Separation is a first-class case and a data-separation rule, not a UX one.

    Five things happen, and the reasoning for each is on page 3 of Journey & Design and in item 6:

    1. **The household is closed, not deleted**, with a closing date. Every plan version created while it
       was open stays attached to it — deleting would break the versioning promise for exactly the members
       who most need it, because a member in a separation is the one who most needs to be able to say what
       was decided in 2027 and why.
    2. **Each adult with an account gets a new single-member household** from the closing date forward,
       naming the closed one through `succeeds_household_id`.
    3. **Shared history is frozen and readable by both.** It needs no copying in this build and that is
       worth stating rather than leaving as an apparent omission: plan versions carry their own `inputs`
       and their own `household_as_of`, `decisions` is append-only at the storage layer, and
       `readable_predicate` already gives each member every row of every household they belong to — the
       closed one included. So both members keep the shared history, neither can edit it, and nothing was
       duplicated to achieve it. Copy-and-freeze was the specified mechanism; the specified GUARANTEE is
       what is implemented, and a second copy of immutable rows would be a second thing to keep in step.
    4. **Goals owned by both are frozen and flagged for division, never split.** `Goal.frozen_at` is set,
       `revise_goal` refuses them, and `derive_action_items` raises an item whose prepared options name a
       curator. There is deliberately no arithmetic here: dividing a goal needs a view of two people's
       preferences the planner does not have, and it carries an emotional load a rule should not touch.
    5. **Neither member sees the other's post-closing plan.** Structural rather than enforced: the
       successors are separate households, so the read rule that widens across a household gives each
       member their own successor and the shared closed one, and nothing of the other's afterwards.

    **What a single owner "following" a goal means, and what it does not.** `Goal.member_id` already names
    one account, so a goal does not move between people here — nothing could move it, and nothing should.
    What follows is the OWNERSHIP: `goal_owners` is re-pointed at the owner's row in their new household,
    so the seventh field keeps naming a person who exists in a live household rather than one in a closed
    one. A goal whose sole owner has no account cannot be re-pointed and is reported instead.

    Raises:
        CompositionNotStated: No such household.
        AlreadyClosed, NotSeparable: Nothing is written.
    """
    if author not in STATED_BY:
        raise NotSeparable(
            f"{author!r} is not an initiator; expected one of {', '.join(STATED_BY)}. Validated up front "
            f"rather than coerced at the point of use, so that no line in this module reads as a branch "
            f"on who acted."
        )

    household = session.get(Household, household_id)
    if household is None:
        raise CompositionNotStated(f"no household {household_id!r}")
    if household.closed_on is not None:
        raise AlreadyClosed(
            f"household {household_id!r} closed on {household.closed_on.isoformat()}. Closing it again "
            f"would create a second set of successor households from the same record."
        )

    present_adults = adults(household)
    if len(present_adults) < 2:
        raise NotSeparable(
            f"household {household_id!r} has {len(present_adults)} adult(s) in it. A separation needs two "
            f"parties; a single-adult household has nobody to separate from."
        )

    with_account = [one for one in present_adults if one.member_id is not None]
    without_account = tuple(
        sorted(one.label for one in present_adults if one.member_id is None)
    )

    # Every goal recorded by any account in this household. Read before anything is written, so the
    # ownership decisions below are made against the household as it stood.
    member_ids = [one.member_id for one in with_account]
    goals = list(
        session.execute(
            select(Goal).where(Goal.member_id.in_(member_ids)).order_by(Goal.id)
        ).scalars()
    )
    ids_in_household = {one.id for one in household.members}

    successor_rows: dict[str, Household] = {}
    followed: list[str] = []
    frozen: list[str] = []
    unowned: list[str] = []

    with mutate_plan(
        session,
        member_id=with_account[0].member_id if with_account else None,
        question=f"Close household {household_id} as of {closing_date.isoformat()}?",
        choice=(
            f"Yes — closed, {len(with_account)} successor household(s) created, "
            f"shared history frozen"
        ),
        author=author,
        author_ref=author_ref,
        curator_session_id=curator_session_id,
        reasoning=(
            "Separation. The household record is closed rather than deleted so every plan version made "
            "while it was open stays attached to it. Goals owned by more than one adult are frozen and "
            "flagged for division; nothing is split here."
        ),
    ) as decision, session.no_autoflush:
        # **Autoflush is off for the whole of this block, and it has to be.** A closing links many objects
        # to one Decision — the household, three membership rows, two successors and their rows, and every
        # goal it touches. Any lazy load in the middle would autoflush, write the Decision, and every link
        # made after that point would then be a modification of a written Decision, which `R-040`'s
        # `DecisionImmutable` guard refuses. Assembled first, flushed once, which is also what makes the
        # closing atomic in the way the report claims it is.
        #
        # The consequence is that `Household.id` is not assigned inside this block — `new_id` is a
        # Python-side column default and runs at flush — so the successors are collected as objects and
        # their ids read after the flush below.
        # **Linked to the Decision BEFORE it is mutated, and that order is not stylistic.**
        # `decision.linked_*.append(...)` can itself trigger an autoflush — appending to a relationship
        # collection loads it first — and `before_flush` then sees a dirty `PlanMutable` object whose link
        # has not landed yet. C-09 refuses the transaction, correctly, and the failure looks like a bug in
        # the guard rather than in the ordering here. Link first, mutate second, every time.
        decision.linked_households.append(household)
        household.closed_on = closing_date

        for person in household.members:
            if person.left_on is None:
                decision.linked_household_members.append(person)
                person.left_on = closing_date

        # One successor per adult who has an account. An adult without one gets none: there is no plan to
        # show a person the product cannot authenticate, and inventing an account for them would be
        # creating a member nobody registered.
        for person in with_account:
            successor = Household(
                composition_as_of=closing_date,
                stated_by=author,
                succeeds_household_id=household.id,
            )
            session.add(successor)
            row = HouseholdMember(
                household=successor,
                member_id=person.member_id,
                label=person.label,
                kind=ADULT,
                joined_on=closing_date,
            )
            session.add(row)
            decision.linked_households.append(successor)
            decision.linked_household_members.append(row)
            successor_rows[person.member_id] = successor
            person.__dict__["_successor_row"] = row  # transient, read in the goal loop below

        for goal in goals:
            # Reading `goal.owners` is safe before the link: a lazy load flushes nothing that is dirty and
            # unlinked, because every mutation below is linked first.
            owners_here = [one for one in goal.owners if one.id in ids_in_household]
            if not owners_here:
                # No owner recorded, or owned only by someone outside this household. Either way there is
                # no owner field to follow, which is precisely what makes a household that never
                # populated it impossible to divide cleanly.
                unowned.append(goal.id)
                continue

            if len(owners_here) > 1:
                decision.linked_goals.append(goal)
                goal.frozen_at = closing_date
                frozen.append(goal.id)
                continue

            sole = owners_here[0]
            row = sole.__dict__.get("_successor_row")
            if row is None:
                # The sole owner has no account, so there is no live household to re-point at. Nothing is
                # mutated, so nothing is linked.
                unowned.append(goal.id)
                continue
            decision.linked_goals.append(goal)
            goal.owners.remove(sole)
            goal.owners.append(row)
            followed.append(goal.id)

    # One flush for the whole closing, now that every link is in place. Ids are assigned here, which is
    # why the report is built after the block rather than inside it.
    session.flush()

    return ClosingReport(
        closed_household_id=household.id,
        closing_date=closing_date,
        successors={
            member_id: successor.id for member_id, successor in successor_rows.items()
        },
        without_an_account=without_account,
        goals_followed=tuple(followed),
        goals_frozen_for_division=tuple(frozen),
        goals_without_an_owner=tuple(unowned),
    )


def current(session: Session, *, member_id: str) -> Household | None:
    """The member's open household, or `None` if they have not stated one.

    "Open" is `closed_on IS NULL`. A member has at most one open household at a time: a closing creates the
    successor and closes the predecessor in one transaction, so the window in which two are open does not
    exist outside a failed transaction. Ordered newest-first anyway, because a defensive `limit(1)` over an
    unordered set is how the wrong row gets returned for a year without anyone noticing.
    """
    return session.execute(
        select(Household)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(
            HouseholdMember.member_id == member_id,
            HouseholdMember.left_on.is_(None),
            Household.closed_on.is_(None),
        )
        .order_by(Household.composition_as_of.desc(), Household.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def require(session: Session, *, member_id: str) -> Household:
    """`current()`, for a caller that cannot proceed without one."""
    household = current(session, member_id=member_id)
    if household is None:
        raise CompositionNotStated(
            f"no household composition has been stated for member {member_id}. It is asked first in the "
            f"intake, and nothing derives it: the AHV path, the tax path and goal ownership all hang on "
            f"it, so a default here would be an invented fact rather than a missing one."
        )
    return household


def adults(household: Household) -> list[HouseholdMember]:
    """The people in a household who can own a goal. Order is the relationship's: stable, oldest row first."""
    return [
        person
        for person in household.members
        if person.kind == ADULT and person.left_on is None
    ]


def describe(household: Household | None) -> dict:
    """The composition as a response payload. Honest about the unstated case rather than empty-shaped.

    No count of anything appears at the top level as a bare number a client could render as progress
    (R-006, C-07). `adults` and `dependants` are lists of people, and a client showing "2 adults" is
    describing a household, not scoring one.
    """
    if household is None:
        return {
            "stated": False,
            "as_of": None,
            "adults": [],
            "dependants": [],
            "closed_on": None,
            "succeeds_household_id": None,
        }

    def _person(row: HouseholdMember) -> dict:
        return {
            "id": row.id,
            # Member-authored: the client quotes it, and nothing composes a sentence around it.
            "label": row.label,
            "kind": row.kind,
            "member_id": row.member_id,
            "has_account": row.member_id is not None,
            "joined_on": row.joined_on.isoformat() if row.joined_on else None,
            "left_on": row.left_on.isoformat() if row.left_on else None,
        }

    present: Iterable[HouseholdMember] = [p for p in household.members if p.left_on is None]
    return {
        "stated": True,
        "household_id": household.id,
        "as_of": household.composition_as_of.isoformat(),
        "stated_by": household.stated_by,
        "adults": [_person(p) for p in present if p.kind == ADULT],
        "dependants": [_person(p) for p in present if p.kind == DEPENDANT],
        "closed_on": household.closed_on.isoformat() if household.closed_on else None,
        "succeeds_household_id": household.succeeds_household_id,
    }
