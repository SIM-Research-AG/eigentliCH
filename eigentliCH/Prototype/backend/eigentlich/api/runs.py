"""R-301 over HTTP: submit a run, poll a run. Three routes, all member-scoped.

**This module deliberately does not import the engine façade**, and a constraint test holds it to that:
`tests/test_constraints.py::test_no_engine_artefact_served_over_http` fails if any module under
`eigentlich/api/` reaches `eigentlich.engines`. That is C-03's strong form — a module that can reach
`call_engine` can also serialise its output — and it is why R-301's thread flag is reached through
`services.runs.serving_request` rather than imported from where it lives.

**The member never supplies an engine payload.** `POST /api/runs` takes an engine name and, optionally, one
of the member's own goal ids. The payload is built server-side by `services/engine_inputs.py` from rows the
plan already holds. A route that accepted engine inputs would be handing the estate arbitrary keys, and
`call_engine`'s undeclared-input refusal exists precisely so that this layer never has to be trusted about
it — belt and braces, in that order.

**A refusal is a 422 with the gap list, not an empty 200.** Four of the seven engines cannot be run from
what the plan holds (A69 recorded twenty-one absent inputs and defaulted none), so the common answer to
this route is a refusal — and the refusal is the product. It names which of the member's own inputs is
missing, in the words `services/engine_inputs.py` uses, so the screen can say *what to fill in* rather than
"engine unavailable". `portfolio_optimiser` was refused outright under C-01 and is not any more (A166):
C-01 is withdrawn and the authorisation it was being held for is no longer sought. It is now refused only
when the plan cannot answer it, like the other three, and its `mandate` gap is the thing that refuses it.

**Polling, not streaming.** R-301 says "queue and poll" and this is the poll: `GET /api/runs/{id}` returns
the run's status and, once it is `done`, its result. A `failed` run comes back with a reason and **no
numeric field at all** (R-302) — `services/runs.describe_run` owns that shape and a recursive test holds it.

**404, never 403, for a run that is not yours.** `services.runs.read_run` scopes the SELECT by member id,
so a run belonging to somebody else and a run that never existed are one answer. A81's reasoning: a
distinct status here would make the route an oracle for other people's run ids.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from ..models import Member
from ..services.runs import (
    NotQueueable,
    describe_run,
    ensure_worker_for,
    list_runs,
    read_run,
    serving_request,
    submit,
)
from .auth import current_member

router = APIRouter(prefix="/api", tags=["runs"])


def get_session() -> Iterator[DbSession]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle that fails only in the
    order FastAPI happens to load things. Same pattern as `api/auth.py` and `api/remainder.py`; the test
    fixture in `conftest.py` overrides this dependency by name from its own list.
    """
    from .main import get_session as application_session

    yield from application_session()


class RunRequest(BaseModel):
    """What a member may ask for: an engine, and optionally one of their own goals.

    **No payload field, and that is the point.** There is nowhere to put an engine input, so no caller can
    supply one. `goal_id` is resolved against `Goal.member_id` in the service, so a goal id belonging to
    somebody else is the same refusal as one that does not exist.
    """

    engine: str = Field(..., min_length=1, max_length=60)
    goal_id: str | None = Field(default=None, max_length=32)


@router.post("/runs", status_code=202)
def start_run(
    body: RunRequest,
    member: Member = Depends(current_member),
    session: DbSession = Depends(get_session),
) -> dict:
    """R-301. Queue one engine run and return its id. 202, because nothing has happened yet.

    **202 Accepted rather than 201 Created.** A 201 would be defensible — a row was created — but the thing
    the member asked for has not been done, and 202 is the status that says so. The body carries the poll
    URL so a client does not have to build one.

    `serving_request()` wraps the body so that R-301's thread flag is set on the thread actually serving
    this request: if a future edit reaches an engine from here, `call_engine` refuses instead of blocking a
    screen for up to half an hour. It is the second net. The first is that there is no synchronous engine
    call in `services/runs.submit` to reach.
    """
    with serving_request():
        try:
            run = submit(session, engine=body.engine, member_id=member.id, goal_id=body.goal_id)
        except NotQueueable as refused:
            session.rollback()
            # 422: the request was understood and is not something this plan can answer. The gap list is
            # the useful half of the response and the client renders it as the member's own missing inputs.
            raise HTTPException(422, refused.as_dict()) from refused
        payload = describe_run(run)
        session.commit()

    # After the commit, deliberately, and in this order: the worker binds to *this* session's engine, so
    # it must not look at the table before the row is visible there. `ensure_worker_for` is idempotent and
    # wakes an already-running worker — see its docstring for why the binding happens here rather than at
    # application boot.
    ensure_worker_for(session).wake()
    return {**payload, "queued": True, "poll": f"/api/runs/{run.id}"}


@router.get("/runs")
def get_runs(
    member: Member = Depends(current_member),
    session: DbSession = Depends(get_session),
) -> dict:
    """This member's runs, newest first. No counts and no aggregate — R-113.

    Starting the worker from a *listing* looks odd and is deliberate: it is the second entry point that
    knows which database is in play, so a run left `submitted` by a previous process is picked up as soon
    as anybody comes back to look at it. See `services.runs.ensure_worker_for`.
    """
    ensure_worker_for(session).wake()
    return list_runs(session, member_id=member.id)


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    member: Member = Depends(current_member),
    session: DbSession = Depends(get_session),
) -> dict:
    """R-301's poll. 404 for a run that is not this member's — see the module docstring."""
    run = read_run(session, run_id=run_id, member_id=member.id)
    if run is None:
        raise HTTPException(404, "no such run")
    return describe_run(run)


__all__ = ["RunRequest", "get_session", "router"]
