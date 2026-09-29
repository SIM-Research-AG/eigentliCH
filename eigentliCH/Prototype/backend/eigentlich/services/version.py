"""Capturing a plan version, and adopting one. Item 6's `household_as_of` stamp lives at the capture.

Two operations and a reader. `capture()` freezes what the member has stated and stamps what it assumed;
`adopt()` makes a version the standing plan and records who did it. Nothing here computes a figure.

===========================================================================================================
THE STAMP IS COPIED AT CAPTURE, AND THAT IS THE WHOLE POINT
===========================================================================================================

`household_as_of` is read off the household **now** and written into the row. It is not joined at render
time. If it were, a member who restated their composition in 2029 would silently change what the March
2027 plan is recorded as having assumed — every past version would quietly agree with the present, which
is the exact class of wrongness item 6 exists to close. A stamp that can be rewritten by later events is
not a stamp.

The same argument applies to `inputs`: a version holds its own copy of the positions and goals, not a list
of ids to look up. Positions are revisable (`services/plan.revise_position`), so a baseline made of
pointers would drift every time the member corrected a figure, and "you are eight months behind the plan
you made in March 2027" would be measured against a plan that has been edited since.

===========================================================================================================
ADOPTION IS THE MEMBER'S ACT, SO IT IS A DECISION WITH AN AUTHOR
===========================================================================================================

`PlanVersion` is not `PlanMutable` — writing a version records the plan rather than changing it. But
adoption is not a recording, it is a choice with a consequence, and page 1 says so: *"A re-solve is always
proposed against the standing plan and never silently replaces it — adopting it is the member's act."*

So `adopt()` writes a Decision naming the author, and the version keeps its id in
`adoption_decision_id`. That is what makes item 2's requirement checkable — *"A confirmation from a curator
does not carry forward to a re-solved plan"* — because each adoption can be asked who made it, and a
curator's release of version 3 says nothing about version 4.

There is deliberately **no** `capture_and_adopt()` convenience. One call that produces a new plan and makes
it standing is a silent replacement with two steps inside it, and the next caller who wants "just re-solve
it for me" would reach for it.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Decision,
    Goal,
    PROPOSED,
    Position,
    PlanVersion,
    STANDING,
    SUPERSEDED,
    utcnow,
)
from .household import current as current_household
from .plan import mutate_plan


class VersionNotFound(LookupError):
    """No such version for this member."""


class NothingStanding(LookupError):
    """The member has no standing plan.

    Distinct from "no versions at all": a member with three proposed versions and none adopted has a plan
    history and no standing plan, and a caller that cannot tell those apart would report the wrong thing.
    """


class AlreadyStanding(ValueError):
    """This version is already the standing plan. Adopting it twice would write a second Decision."""


class CannotAdoptSuperseded(ValueError):
    """A superseded version cannot be re-adopted.

    Going back to an old plan is a real thing a member may want, and it is not this operation: it is a new
    version whose inputs happen to match an old one, captured and adopted like any other. Flipping a
    superseded row back to standing would leave `superseded_by_id` pointing at a version that is now
    behind it, and the history would read as a cycle.
    """


def _position_inputs(positions: Sequence[Position]) -> list[dict]:
    """One position, as the engines read it. Stated fields only."""
    return [
        {
            "id": p.id,
            "role": p.role,
            "capital_type": p.capital_type,
            "label": p.label,
            "magnitude": p.magnitude,
            "magnitude_unit": p.magnitude_unit,
            "stock_kind": p.stock_kind,
            "liquidity": p.liquidity,
            "time_basis": p.time_basis,
            "active": p.active,
        }
        for p in positions
    ]


def _goal_inputs(goals: Sequence[Goal]) -> list[dict]:
    """One goal, with all seven fields. `owners` is the seventh (A108) and is what a division reads."""
    return [
        {
            "id": g.id,
            "name": g.name,
            "template": g.template,
            "target_amount": g.target_amount,
            "target_date": g.target_date.isoformat() if g.target_date else None,
            "safety": g.safety,
            "liquidity_need": g.liquidity_need,
            "volatility_tolerance": g.volatility_tolerance,
            "horizon": g.horizon,
            "flexibility": g.flexibility,
            "owners": [
                {"household_member_id": o.id, "label": o.label, "kind": o.kind} for o in g.owners
            ],
            "funded_by": [p.id for p in g.funded_by],
        }
        for g in goals
    ]


def capture(
    session: Session,
    *,
    member_id: str,
    reason: str | None = None,
) -> PlanVersion:
    """Freeze the member's plan as a new numbered baseline. Arrives `proposed`, never standing.

    Writes no Decision: a capture records the plan and does not change it, and a Decision per capture
    would fill an append-only table with rows nobody chose. Adoption is where the record belongs.
    """
    positions = list(
        session.execute(
            select(Position).where(Position.member_id == member_id).order_by(Position.id)
        ).scalars()
    )
    goals = list(
        session.execute(select(Goal).where(Goal.member_id == member_id).order_by(Goal.id)).scalars()
    )

    household = current_household(session, member_id=member_id)
    highest = session.execute(
        select(PlanVersion.number)
        .where(PlanVersion.member_id == member_id)
        .order_by(PlanVersion.number.desc())
        .limit(1)
    ).scalar_one_or_none()

    version = PlanVersion(
        member_id=member_id,
        number=(highest or 0) + 1,
        status=PROPOSED,
        household_id=household.id if household else None,
        # Item 6's stamp. Copied now; see the module docstring on why it is not joined later.
        household_as_of=household.composition_as_of if household else None,
        inputs={
            "positions": _position_inputs(positions),
            "goals": _goal_inputs(goals),
        },
        reason=reason,
    )
    session.add(version)
    session.flush()
    return version


def adopt(
    session: Session,
    *,
    member_id: str,
    version_id: str,
    author: str = "member",
    author_ref: str | None = None,
    curator_session_id: str | None = None,
    reasoning: str | None = None,
) -> PlanVersion:
    """Make a version the standing plan. The member's act, so it writes a Decision naming the author.

    The previous standing version becomes `superseded` and names this one as its successor, in the same
    transaction. A database-level partial unique index backs that up: two standing versions cannot exist
    even if a future caller does the two writes in the wrong order.

    Raises:
        VersionNotFound, AlreadyStanding, CannotAdoptSuperseded: Nothing is written.
    """
    version = session.execute(
        select(PlanVersion).where(
            PlanVersion.id == version_id, PlanVersion.member_id == member_id
        )
    ).scalar_one_or_none()
    if version is None:
        raise VersionNotFound(f"no plan version {version_id!r} for member {member_id!r}")
    if version.status == STANDING:
        raise AlreadyStanding(
            f"version {version.number} is already the standing plan. Adopting it again would write a "
            f"second Decision recording a choice nobody made twice."
        )
    if version.status == SUPERSEDED:
        raise CannotAdoptSuperseded(
            f"version {version.number} was superseded. Returning to an earlier plan is a new version "
            f"whose inputs match an old one — captured and adopted like any other — not a flip of this "
            f"row, which would make the history read as a cycle."
        )

    previous = standing(session, member_id=member_id, missing_ok=True)

    with mutate_plan(
        session,
        member_id=member_id,
        question=f"Adopt plan version {version.number} as the standing plan?",
        choice=(
            f"Yes — version {version.number} replaces "
            + (f"version {previous.number}" if previous else "no previous standing plan")
        ),
        author=author,
        author_ref=author_ref,
        curator_session_id=curator_session_id,
        reasoning=reasoning,
    ) as decision:
        # The Decision covers no `PlanMutable` object, which is correct: adoption changes which version
        # stands, not the positions and goals. `mutate_plan` is used for the Decision it writes and the
        # transaction it shares, not because the guard demands it here.
        session.flush()  # the Decision needs an id before the version can reference it

        # **The demotion is flushed on its own, before the promotion.** `uq_plan_versions_one_standing`
        # is a partial unique index over the standing rows, and SQLAlchemy's unit of work orders its
        # UPDATE statements by identity rather than by the order the attributes were assigned here. So
        # assigning both and flushing once let the promotion reach the database first, leaving two
        # standing rows for the length of one statement — which the index refused, correctly.
        #
        # Found by `test_the_partial_index_still_allows_many_superseded_versions`, on the second
        # adoption. Worth keeping in mind generally: an index that enforces "at most one" catches a
        # transient violation inside a flush, not only a final one.
        if previous is not None:
            previous.status = SUPERSEDED
            previous.superseded_by_id = version.id
            session.flush()

        version.status = STANDING
        version.adopted_at = utcnow()
        version.adoption_decision_id = decision.id

    return version


def standing(session: Session, *, member_id: str, missing_ok: bool = False) -> PlanVersion | None:
    """The member's standing plan, or `None` / `NothingStanding`.

    `missing_ok` rather than a separate function, because the two callers genuinely differ: `adopt()` needs
    to know whether there is a predecessor and is fine either way, while a reader rendering "your plan"
    cannot proceed and should say so.
    """
    found = session.execute(
        select(PlanVersion).where(
            PlanVersion.member_id == member_id, PlanVersion.status == STANDING
        )
    ).scalar_one_or_none()
    if found is None and not missing_ok:
        raise NothingStanding(
            f"member {member_id!r} has no standing plan. A version is proposed when it is captured and "
            f"becomes standing only when the member adopts it — page 1: a re-solve never silently "
            f"replaces the standing plan."
        )
    return found


def history(session: Session, *, member_id: str) -> list[PlanVersion]:
    """Every version, newest first. Proposed ones included — an unadopted proposal is part of the record."""
    return list(
        session.execute(
            select(PlanVersion)
            .where(PlanVersion.member_id == member_id)
            .order_by(PlanVersion.number.desc())
        ).scalars()
    )


def describe(version: PlanVersion) -> dict:
    """One version as a response payload.

    `household_as_of` is present even when null, and `household_assumption_recorded` says which it is —
    a client should not have to infer from a missing key whether the plan knew the household or not.
    """
    return {
        "id": version.id,
        "number": version.number,
        "status": version.status,
        "created_at": version.created_at.isoformat(),
        "reason": version.reason,
        "household_id": version.household_id,
        "household_as_of": (
            version.household_as_of.isoformat() if version.household_as_of else None
        ),
        "household_assumption_recorded": version.household_as_of is not None,
        "adopted_at": version.adopted_at.isoformat() if version.adopted_at else None,
        "adoption_decision_id": version.adoption_decision_id,
        "superseded_by_id": version.superseded_by_id,
        "inputs": version.inputs,
        # NO score, NO "on track", NO percentage against the goal. A version is what was stated, and a
        # verdict about it belongs to whoever solves it — R-113, C-07.
    }
