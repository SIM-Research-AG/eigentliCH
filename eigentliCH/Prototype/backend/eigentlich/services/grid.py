"""The role grid payload (S-02).

Four roles across two kinds of capital: eight cells, each empty or holding one or more positions.

**Three requirements shape this function and they all say the same thing in different words.**

  R-110  renders meaningfully with a single position filled; empty cells state what would go there
  R-113  no completion meter, no "3 of 8 filled", no progress ring
  R-006  progress along anything is never displayed as achievement

So this payload deliberately contains **no count of filled cells, no total, and no ratio**. Not because
the client would necessarily render one, but because a payload carrying `filled: 3, total: 8` is a
completion meter that has not been drawn yet, and the next person to build a component will draw it. The
absence is the enforcement.

**What an empty cell carries instead.** `prompt` — what would go in it, from the role's own definition.
R-110 says an empty cell states what would go there rather than "no data", and the honest source for that
sentence is the definition of the role itself, which the member can already ask to see.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import DEFAULT_LANGUAGE, role_definition, role_display
from ..models import CAPITAL_TYPES, Position, ROLES


def _position_payload(position: Position) -> dict:
    """Every field of a position that `PATCH /api/positions/{id}` can change, plus its `active` flag.

    **That correspondence is the rule, and `liquidity` was the field that proved it needed stating.** The
    payload carried every other revisable field and not that one, so the edit form built on 31 August 2026
    could not show a member which band their position holds and had to offer an additive "leave unchanged"
    selector instead. Meanwhile `services/goals.py` reports `liquidity_not_stated` about that same position
    under R-031 — so the product told a member a field was missing, gave them a route to set it, and no way
    to see what it already said. One omission, three surfaces disagreeing.

    `time_basis` and `started_on` were checked for the same defect and did not have it; both were already
    here. What they do have is the *write*-side half of it — `POST /api/positions` cannot set either, and
    neither can it set `liquidity` — which `services/plan.py` records above `POSITION_REVISABLE_FIELDS` and
    which the edit route is the answer to.

    **C-04.** No change of class. `Position.__data_class__` is K2, no column on it declares a higher class
    of its own, and `liquidity` is an enum band the member stated about their own holding — so this payload
    was K2 before and is K2 now.

    **The four band names are not here.** They are authored vocabulary, they are already served by
    `GET /api/goal-templates` as `liquidity_bands`, and a second copy in a member-scoped payload is a second
    place for the list to drift. What is here is what this member's position holds, or `None` where they
    have not said — which is a different fact from `"immediate"` and has to stay one.
    """
    return {
        "id": position.id,
        "label": position.label,
        "description": position.description,
        "magnitude": position.magnitude,
        # Never inferred. A magnitude whose unit was guessed is worse than one that is absent.
        "magnitude_unit": position.magnitude_unit,
        # Asset or liability, non-null exactly when the unit is `chf`. **Not defaulted to "asset" for
        # display**, which is the tempting one-liner: a debt rendered as a holding is the netting error
        # `models/plan.py` chose a field to avoid, arriving in the client instead of in the store.
        "stock_kind": position.stock_kind,
        "time_basis": position.time_basis,
        # R-031. Null means the member has not said, and it is never filled in from the label.
        "liquidity": position.liquidity,
        "active": position.active,
        "started_on": position.started_on.isoformat() if position.started_on else None,
        # D-02: stored, never interpreted. The rule that would read these is undecided.
        "tags": position.tags or {},
    }


def role_grid(session: Session, *, member_id: str, language: str = DEFAULT_LANGUAGE) -> dict:
    """The eight cells, with their positions and their definitions.

    Inactive positions are included and flagged rather than filtered out: R-122 keeps them in history, and
    a grid that silently drops them would misrepresent what the member has done.
    """
    positions = list(
        session.execute(select(Position).where(Position.member_id == member_id)).scalars()
    )

    cells = []
    for role_key in ROLES:
        for capital_type in CAPITAL_TYPES:
            in_cell = [
                p for p in positions if p.role == role_key and p.capital_type == capital_type
            ]
            cells.append(
                {
                    "role": role_key,
                    "capital_type": capital_type,
                    "display": role_display(role_key, capital_type, language),
                    "definition": role_definition(role_key, capital_type, language),
                    "positions": [_position_payload(p) for p in in_cell],
                    # R-110. What would go here, said in the role's own words. Present on filled cells
                    # too, so the client never has to decide which sentence to show.
                    "prompt": role_definition(role_key, capital_type, language),
                    # R-112. Adding a position is reachable from any empty cell in one action.
                    "add_action": {
                        "method": "POST",
                        "href": "/api/positions",
                        "role": role_key,
                        "capital_type": capital_type,
                    },
                }
            )

    return {
        "member_id": member_id,
        "language": language,
        "roles": list(ROLES),
        "capital_types": list(CAPITAL_TYPES),
        "cells": cells,
        # R-114 / principle 9: both kinds of capital are always present, even when one side is empty, so a
        # summary component cannot be built that accepts only financial inputs.
        "both_capital_types_always_present": True,
        # NO filled count, NO total, NO ratio, NO percentage. See this module's docstring — R-113, R-006.
    }
