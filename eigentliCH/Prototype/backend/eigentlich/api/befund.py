"""The Befund over HTTP. One route, and it is a GET.

**A GET, because R-175 is a statement about who starts things.** The report is produced when a member asks
for it. There is no POST that schedules one, no route that raises an action item off the back of one, and
nothing that notifies. A member who never opens this screen is never told anything by it.

**The route adds nothing to what the service composes.** No ordering parameter, no aggregate assembled at
the edge, no convenience field, and above all no summary — `api/learning.py` and `api/remainder.py` both
record the same choice for the same reason: where a service refused to compute something, the edge is not
the place it reappears. A `sections` array with a `facts` array inside it is deliberately awkward to
render as a headline number.

**The member is the token's.** A11: `member_id` is not a parameter here, so there is no version of this
route that reads somebody else's Befund. That matters more here than on most routes, because this payload
is the one place K2 and K3 material about a member is assembled into a single readable document.

**`get_session` is defined here and delegates to `main`'s at request time**, and this module never imports
`main` at module scope — the cycle it would create fails only in the order FastAPI happens to load
things. `api/remainder.py` carries the same note.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..content import DEFAULT_LANGUAGE
from ..models import Member
from ..services.befund import BefundWouldAdvise, UnknownLanguage, render_befund
from .auth import current_member

router = APIRouter(prefix="/api", tags=["befund"])


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import."""
    from .main import get_session as application_session

    yield from application_session()


@router.get("/befund")
def get_befund(
    language: str = DEFAULT_LANGUAGE,
    prose: bool = Query(
        False,
        description=(
            "Let the local model rephrase each computed sentence. Off by default: the deterministic "
            "report is the product, and the model is an option on top of it. A rephrasing is discarded "
            "unless it carries exactly the same figures, adds no sentence and passes C-01."
        ),
    ),
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """The member's standing report over what they have recorded.

    Returns 422 for a language nobody has written the report in — A12 makes that a refusal rather than a
    silent fall back to German, which would ship a half-translated document.

    **A `BefundWouldAdvise` is a 500 and is meant to be.** It means a sentence *this application composed*
    was refused by C-01's outbound gate, which is a defect in eigentliCH's own copy, not a bad request from
    the member and not something to paper over with a partial report. A76 and A78 both record the
    practice: a refusal is a finding, and the finding is worth more than the response.
    """
    try:
        return render_befund(session, member_id=member.id, language=language, prose=prose)
    except UnknownLanguage as unknown:
        raise HTTPException(422, str(unknown)) from unknown
    except BefundWouldAdvise:
        # Re-raised unchanged. Not caught to be softened — caught to say why it is not being softened.
        raise
