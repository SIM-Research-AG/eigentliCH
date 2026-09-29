"""The curator directory over HTTP, and the one session opener that checks who it is naming.

**Plural on purpose.** `/api/curator` (singular) is the workbench: routes a curator authenticates to.
`/api/curators` (plural) is the directory: the list of curators, which a *member* reads. Two different
audiences, two different prefixes, and no route here serves a member's material to anyone.

**`GET /api/curators` is not authenticated, and that is a decision rather than an omission.** It is the staff
list of a firm the reader is already a member of — the same fact that would be on a contact page. It says
nothing about any member, nothing about who has granted what, and nothing about a curator beyond their
name and their role label. The 401 on `/api/curator/*` protects a member's positions and vault; putting
the same lock on "who works here" would protect nothing and would leave the Curator button unable to name
anyone before login, which R-170 does not allow.

**`POST /api/curators/sessions` is the opener the client calls.** This one resolves the curator id against
the `curators` table, so C-10's "identified curator" is a row rather than a string.

*This paragraph used to say that `POST /api/curator/sessions` in `main.py` "takes `curator_id` on trust"
and "can be made strict later".* It was true when it was written and is not any more: that route calls
`services.directory.resolve_curator` too, and its own docstring records who found the defect and why a
plain string written into an append-only audit table was the wrong shape. Both openers are strict; this one
stays because the request body and the prefix are the ones the client is written against.

*And the column itself is a foreign key as of 31 August 2026 (A98),* so "identified curator" is now a fact
about the store rather than a property of whichever opener a caller happened to use. That is the version of
this guarantee that survives somebody adding a third opener.

`POST /api/curators/sessions` **is** authenticated, and takes no `member_id`: A11 was wired on 31 August
2026, so which member opened the session is the bearer token's member and not a body field anyone could
type. The curator id stays in the body — it is what is being named, not who is asking.

`api/main.py` defines nothing here; it imports the router and includes it, the same arrangement
`api/curator.py`, `api/learning.py` and the rest use.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Member
from ..services.directory import NoSuchCurator, list_curators, open_identified_session
from .auth import current_member

router = APIRouter(prefix="/api/curators", tags=["curators"])


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle — and one that fails
    only in the order FastAPI actually loads things, which is the worst kind. The same pattern as
    `api/curator.py` and `api/learning.py`.
    """
    from .main import get_session as application_session

    yield from application_session()


@router.get("")
def curator_directory(session: Session = Depends(get_session)) -> dict:
    """R-170 / R-173. The named people a member can ask for.

    An empty list is a legitimate answer and comes back as 200, never as a 404 and never as an error. The
    Curator button is present at all times (R-170) and has to render something truthful when nobody is
    available; a client that received an error would be entitled to hide the button, which is the one
    thing it may not do.

    R-113 / C-07: no total, no availability meter, no "next free in n minutes". A list of people.
    """
    return {"curators": list_curators(session)}


class OpenCuratorSessionRequest(BaseModel):
    #: No `member_id`. R-173 records which member opened the session and that is the token's member; a
    #: field here would have let anyone open a curator session in someone else's name, into an
    #: append-only audit table whose whole value is being true.
    #: C-10. `min_length=1` refuses an empty string at the schema, before the service is reached; a
    #: missing field and a null are refused by the type. `services.directory.resolve_curator` then refuses
    #: everything that is a non-empty string but not a curator — "unassigned" among them, not because it
    #: is a forbidden word but because it is not a row.
    curator_id: str = Field(..., min_length=1, max_length=120)
    #: R-173. Which screen the button was pressed on — recorded at the time or not at all.
    opened_from: str = Field(..., min_length=1, max_length=120)


@router.post("/sessions", status_code=201)
def open_curator_session_route(
    body: OpenCuratorSessionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-173 / C-10. The Curator button's session: an identified curator and the screen it came from.

    422 rather than 404 when the curator is unknown. The curator arrives as a field of the request, not as
    the address of it — the route exists, the body is wrong — and the detail carries C-10's reason so the
    member sees why nothing was recorded rather than a bare status code.
    """
    try:
        record = open_identified_session(
            session,
            member_id=member.id,
            curator_id=body.curator_id,
            opened_from=body.opened_from,
        )
    except NoSuchCurator as unknown:
        raise HTTPException(422, str(unknown)) from unknown
    session.commit()
    return {
        "id": record.id,
        "member_id": record.member_id,
        "curator_id": record.curator_id,
        "opened_from": record.opened_from,
        "opened_at": record.opened_at.isoformat(),
    }


__all__ = ["router"]
