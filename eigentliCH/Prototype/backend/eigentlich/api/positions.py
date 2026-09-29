"""Changing a position that already exists: R-122 and the second half of R-123.

**Why this is its own module and not three routes in `main.py`.** `main.py` is where the role grid's
`GET` and `POST` live and it is the one file that knows the whole surface exists; three phases were being
built against it at once. Every phase after the first was written as its own router for exactly this
reason, and the wiring line at the bottom of `main.py` is the one place that changes. It was written
unwired for that reason and is wired now — see the note at the end of this docstring for the two lines
that do it, kept there because they are what a reader needs in order to find the router from the app.

**What was missing, and it was not cosmetic.** `Position.active` is honoured on six read paths —
`services/grid.py` flags it, `services/befund.py` has a sentence for a cell holding only inactive
material, `services/illustration.py` and `services/engine_inputs.py` skip it, `services/derive.py`
filters on it, `services/goals.py` excludes it from a goal's funding — and it was rendered by the client.
**And nothing anywhere set it to `False`.** R-122 says a position may be marked inactive; no code could
mark one. §6 of the specification names `PATCH /api/positions/:id`; it did not exist. That also left
R-123 half-enforced: "creating **or editing** a position writes a Decision in the same transaction" was
held on creation, and there was no editing for it to be held on.

**Three routes, and the split between them is argued rather than incidental.** `PATCH` corrects what a
position *is*; `deactivate` and `reactivate` change what the member's **live plan** is. The reasoning for
keeping those two acts apart from an edit — and for in-place UPDATE plus a correcting `Decision` rather
than a superseding row, which is A86's argument applied to `positions` — is in
`services/plan.py::revise_position` and `::set_position_active`. It is there rather than here because it
is a decision about the data, not about HTTP.

**C-09 is not enforced by this module.** Both service functions write through `mutate_plan`, and the
guard in `db.py` refuses a plan mutation with no linked Decision in `before_flush` and again at statement
level (A72). These routes are the convenient path, not the enforcement — the same relationship
`POST /api/positions` has with it.

**A11.** Every route here takes a session and none of them takes a `member_id`: the position is addressed
by its own id in the path, and the service refuses one that does not belong to the token's member. The
refusal is 404 rather than 403, on A81's reasoning — a member who does not own a position has no business
learning whether that id exists, so "no such position" and "not yours" must be one answer.

**The two lines in `api/main.py` that wire it**, next to the other routers' own:

    from .positions import router as positions_router  # noqa: E402

and `positions_router,` in the tuple the loop below it passes to `app.include_router`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..models import Member
from ..services.plan import (
    PositionNotFound,
    PositionUnchanged,
    revise_position,
    set_position_active,
)
from .auth import current_member

router = APIRouter(prefix="/api", tags=["plan"])


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle — and one that fails
    only in the order FastAPI actually loads things, which is the worst kind. The import inside the body
    runs after `main` is fully initialised, on every request.
    """
    from .main import get_session as application_session

    yield from application_session()


class PositionRevisionRequest(BaseModel):
    """A change to a position that already exists. S-03 / R-120, R-121, R-123.

    **Every field is optional and `None` is a value, not an absence.** `model_fields_set` is what
    separates "clear the description" from "do not touch the description" — a shape where those are the
    same thing silently wipes whatever the member did not retype, which is `GoalRevisionRequest`'s reason
    for the same design and the defect this route exists to fix wearing a different coat.

    **No `active`.** Marking a position inactive is R-122's own act and has its own two routes, because a
    boolean in the middle of an edit form is how a member deactivates a position by accident. The service
    refuses `active` here by name rather than ignoring it, so a client that sends one is told.

    **No `member_id` and no `id`** (A11): the position is addressed in the path and the member is the
    token's.
    """

    #: **An unknown field is refused, not ignored**, and that is load-bearing here rather than tidiness.
    #: Pydantic's default is to drop what it does not recognise, and on a route whose whole shape is "state
    #: only what you are changing" that turns `{"active": false}` and `{"lable": "typo"}` into a 200 that
    #: changed nothing — or, worse, into the 422 that means "your revision is a no-op", which is a true
    #: sentence about the wrong thing. `active` is the field a client will actually send, because
    #: deactivating is the obvious thing to want from an edit route; it belongs to R-122's own two routes
    #: and the refusal has to say so rather than shrug. `services/plan.revise_position` refuses it by name
    #: for the same reason, one layer down, for callers who never came through HTTP.
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    capital_type: str | None = None
    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    #: R-120. A magnitude and its unit move together or the service refuses — an annualised amount and a
    #: share of total are not interchangeable, and a unit that was guessed is worse than no figure.
    magnitude: float | None = None
    magnitude_unit: str | None = None
    #: Asset or liability, for a magnitude stated in `chf`. Revisable, and it travels with the unit rather
    #: than in a route of its own: correcting "45,000 held" to "45,000 owed" is one statement about one
    #: position, and the service validates the merged state so a request that changes the unit and leaves
    #: the side behind is refused rather than persisted into a state the CHECK constraint forbids.
    stock_kind: str | None = None
    #: R-121. Human capital is bounded by hours; financial capital is not.
    time_basis: str | None = None
    #: R-031. One of the four bands, never a number of years — a threshold would be an assumption under
    #: C-02 and nobody has published one. `POST /api/positions` cannot set this, which is why a member
    #: told `liquidity_not_stated` about their own goal had no way to answer until this route existed.
    liquidity: str | None = None
    #: ISO-8601. Parsed here so a bad date is a 422 about the date rather than an error about the column.
    started_on: str | None = None
    #: R-021 / D-02. The five correlation tags, stored and read by nothing.
    tags: dict | None = None

    #: C-09. The decision is part of the request, exactly as on `POST /api/positions`. A member changing
    #: their plan states what they decided; the server does not compose that sentence on their behalf.
    question: str
    choice: str
    reasoning: str | None = None


class PositionStatusRequest(BaseModel):
    """What a member states when they mark a position inactive, or active again. R-122.

    **It carries no `active` field**, and that is the point of there being two routes: the act is the
    route, so there is no flag to get the wrong way round and no request that means "leave it as it is".
    A body that sends one anyway is refused rather than having it dropped, so a client cannot come away
    believing the flag it sent is what decided the outcome.
    """

    model_config = ConfigDict(extra="forbid")

    #: C-09 again. Deactivating a position is a material change to the plan.
    question: str
    choice: str
    reasoning: str | None = None


def _result(result: dict) -> dict:
    """The response shape all three routes share.

    `corrects_decision_id` is in it so a client can say "this corrects an earlier record" rather than
    having to know that it does — R-040's chain, named on the wire.
    """
    return {
        "id": result["position"].id,
        "active": result["position"].active,
        "decision_id": result["decision"].id,
        "corrects_decision_id": result["decision"].corrects_id,
        "changed": result["changed"],
    }


@router.patch("/positions/{position_id}")
def revise_existing_position(
    position_id: str,
    body: PositionRevisionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-123's second half. **The route §6 names and that did not exist.**

    An in-place UPDATE plus a correcting `Decision` carrying both the prior and the new values — A86's
    choice for goals, applied to positions for the four reasons `revise_position` sets out.

    `PATCH` rather than `PUT`, which is where this differs from `PUT /api/goals/{goal_id}`: §6 names
    `PATCH` for this resource, and the goal route chose `PUT` because what comes back is the goal's whole
    new state. What comes back here is what changed and the Decision that records it, which is what
    `PATCH` describes.

    Refusals: **404** for a position that is not this member's, **422** for a revision that changes
    nothing or that would leave the position in a state R-120 or R-121 forbids.
    """
    stated = body.model_dump(exclude_unset=True)
    for field in ("question", "choice", "reasoning"):
        stated.pop(field, None)

    if "started_on" in stated and stated["started_on"] is not None:
        try:
            stated["started_on"] = date.fromisoformat(stated["started_on"])
        except (TypeError, ValueError) as bad:
            raise HTTPException(422, f"started_on must be ISO-8601: {bad}") from bad

    try:
        result = revise_position(
            session,
            member_id=member.id,
            position_id=position_id,
            changes=stated,
            question=body.question,
            choice=body.choice,
            reasoning=body.reasoning,
        )
    except PositionNotFound as missing:
        raise HTTPException(404, str(missing)) from missing
    except PositionUnchanged as unchanged:
        # 422, not 204: the request is well formed and nothing is wrong with the member. What is wrong is
        # that it asks for the state the position is already in, and answering "done" would imply a
        # Decision was written.
        raise HTTPException(422, str(unchanged)) from unchanged
    except ValueError as bad:
        # An unknown role, a magnitude without a unit, a time basis on financial capital. `PositionUnchanged`
        # is a ValueError too and is caught above, so the order of these two clauses is load-bearing.
        raise HTTPException(422, str(bad)) from bad
    session.commit()
    return _result(result)


@router.post("/positions/{position_id}/deactivate")
def deactivate_position(
    position_id: str,
    body: PositionStatusRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-122. Mark a position inactive. **Deactivating is not deleting, and nothing is removed.**

    R-122's own word is *inactive*: "inactive positions remain in history and in decisions". So the row
    stays, its links to every Decision that referenced it stay, `services/grid.py` still returns it with
    its flag, and `services/befund.py` has a sentence for a cell that holds only inactive material. What
    changes is that it leaves the live plan.

    The payload says both halves out loud rather than leaving a client to infer either.
    """
    return _status(session, member, position_id, body, active=False)


@router.post("/positions/{position_id}/reactivate")
def reactivate_position(
    position_id: str,
    body: PositionStatusRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-122, the other direction. A position the member marked inactive rejoins the live plan.

    **This route exists on purpose.** R-122 does not say the mark is one-way, and making it one-way would
    make a mis-click permanent on a table `db.py` calls legitimately mutable. It is a material change like
    any other and writes its own Decision.
    """
    return _status(session, member, position_id, body, active=True)


def _status(
    session: Session,
    member: Member,
    position_id: str,
    body: PositionStatusRequest,
    *,
    active: bool,
) -> dict:
    """The two R-122 routes' shared body. One implementation, two names — the act is the route."""
    try:
        result = set_position_active(
            session,
            member_id=member.id,
            position_id=position_id,
            active=active,
            question=body.question,
            choice=body.choice,
            reasoning=body.reasoning,
        )
    except PositionNotFound as missing:
        raise HTTPException(404, str(missing)) from missing
    except PositionUnchanged as unchanged:
        raise HTTPException(422, str(unchanged)) from unchanged
    session.commit()
    return {
        **_result(result),
        # R-122, stated rather than implied. A client rendering a confirmation should be able to tell the
        # member what did NOT happen, because "deactivate" is the word people read as "delete".
        "remains_in_history": True,
        "remains_linked_to_decisions": True,
    }
