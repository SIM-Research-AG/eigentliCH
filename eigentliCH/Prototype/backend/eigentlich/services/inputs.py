"""What a member has told us, as a closed set of input names. One implementation, two directions.

Item 5, on the content hooks: "This is the same mechanism as the first-session finding, running in the
other direction: the chatbot composes a grounded statement when the app has something to say, and the same
path serves the member pulling when they want to know something. **One implementation serves both.**"

Both directions need the same question answered — *which of these inputs has this member already given?* —
and it is answered here rather than twice:

  * **Pushing** (item 3): `know.missing_personal_input` names the one input that would make a
    branch-2 answer personal.
  * **Pulling** (item 5): `hooks` asks which of a content item's declared inputs are still missing, so the
    ones already in the Vault can be skipped.

===========================================================================================================
A CLOSED SET, AND WHY IT IS NOT THE QUESTION SET
===========================================================================================================

These are **inputs**, not questions. `household_composition` happens to be both, but `financial_stock` is
satisfied by any stated balance from any route — the intake, the role grid, a curator session — and asking
"has the member answered question X" would miss all but the first.

So the set is keyed on what the plan HOLDS rather than on how it got there, and each entry carries its own
predicate. A content item may only declare an input from this set; an item declaring something nothing can
answer would be a tap that never completes, which item 5 rules out from the other end ("an item that cannot
be personalised within its declared inputs gets no tap").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Goal, Position, STOCK_UNITS

#: Every input a content item may declare, and the order they are asked in when more than one is missing.
#:
#: **Household composition is first here as it is first everywhere** (item 3): it sets the AHV path, the
#: tax path and goal ownership, and it is the one input nothing can detect for itself.
INPUT_ORDER = (
    "household_composition",
    "income_position",
    "financial_stock",
    "first_goal",
)


def _has_household(session: Session, member_id: str) -> bool:
    from .household import current as current_household

    return current_household(session, member_id=member_id) is not None


def _has_income_position(session: Session, member_id: str) -> bool:
    return (
        session.execute(
            select(Position.id).where(
                Position.member_id == member_id,
                Position.active.is_(True),
                Position.role == "income",
            )
        ).first()
        is not None
    )


def _has_financial_stock(session: Session, member_id: str) -> bool:
    """Any stated balance in francs. **However it arrived** — see the module docstring."""
    return (
        session.execute(
            select(Position.id).where(
                Position.member_id == member_id,
                Position.active.is_(True),
                Position.capital_type == "financial",
                Position.magnitude.is_not(None),
                # `in STOCK_UNITS`, never `== "chf"`: the literal is a prefix of `chf_per_year` and a site
                # that reaches for one reaches for `startswith` next (A105, A122).
                Position.magnitude_unit.in_(STOCK_UNITS),
            )
        ).first()
        is not None
    )


def _has_goal(session: Session, member_id: str) -> bool:
    return (
        session.execute(select(Goal.id).where(Goal.member_id == member_id)).first() is not None
    )


#: The predicate per input. A dict rather than a chain of `if`s so `INPUT_ORDER` and this cannot disagree
#: about what exists — the completeness check below fails the import if they do.
PREDICATES = {
    "household_composition": _has_household,
    "income_position": _has_income_position,
    "financial_stock": _has_financial_stock,
    "first_goal": _has_goal,
}

if set(PREDICATES) != set(INPUT_ORDER):  # pragma: no cover - an import-time contract
    raise RuntimeError(
        f"INPUT_ORDER and PREDICATES disagree: {set(INPUT_ORDER) ^ set(PREDICATES)}. An input with no "
        f"predicate is one nothing can ever satisfy, and a predicate with no place in the order is one "
        f"nothing will ever ask for."
    )


def stated(session: Session, *, member_id: str) -> set[str]:
    """Which inputs this member has already given. One query per input, and only four inputs."""
    return {name for name, holds in PREDICATES.items() if holds(session, member_id)}


def missing(session: Session, *, member_id: str, wanted) -> list[str]:
    """The wanted inputs this member has not given, in `INPUT_ORDER`.

    Ordered rather than returned as a set, because the caller asks them one at a time — item 5: "asked
    **one at a time rather than as a form**" — and the order has to be the same on two consecutive reads
    or the member is asked a different question each time they come back.
    """
    have = stated(session, member_id=member_id)
    return [name for name in INPUT_ORDER if name in set(wanted) and name not in have]


__all__ = ["INPUT_ORDER", "PREDICATES", "missing", "stated"]
