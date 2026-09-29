"""S-10 over HTTP: the learning path, the capability review, and R-193's three exits.

**Three reads and one write, and the write is new.** This module used to say it was read-only, and gave
the reason: *"there is no decided route by which a member gets assessed — D-01 owns 'how a capability is
assessed', and an HTTP verb is a decision about that whether or not it is described as one."* That
reasoning was right and its premise expired. **D-01 was answered on 31 August 2026 and A82 records the
answer: the member's own self-assessment.** So the verb no longer decides anything — it carries out a
decision somebody else made — and withholding it stopped protecting D-01 and started breaking R-005.

**What the absence was actually costing.** `services.learning.record_assertion` was the only way a
`CapabilityAssertion` could come into existence and it had no route, so no real member could hold one, so
`POST /api/marketplace/applications` answered every real member with a 403 and `capability_evidence` was
permanently zero in R-203's ordering inputs. The most carefully guarded module in the build could not be
entered by anybody. R-005 is a gate that has to be *satisfiable*, which is a different thing from a gate
that has to be weak.

**The D-01 line, and where it now sits.** Nothing here assesses. `POST /api/capabilities/assertions`
writes what a member says about themselves and no more: `evidence_kind` and `assessed_by` are filled by
the server from constants (see `services/learning.py`) rather than accepted from the caller, `rung` is
untouched and stays null on every row, both payloads still report `rung_scheme: None`, and there is no
route by which a curator, an operator or eigentliCH itself can grade one. The request body carries a
capability key and, optionally, one learning unit whose reference the content has to corroborate.

**`/api/learning/exits` is the one route here that takes no session** — R-193's three exits are
authored content and its own docstring already promised a client could show them without first asking for
a member's learning path. The other two resolve their member from the bearer token; see `api/auth.py` for
the whole list of what is deliberately open.

**The gate for this phase is an absence** (build-spec §10: no level numbers or points in schema or UI).
So these routes return exactly what the service composes and add nothing: no ordering parameter, no
filter that would imply one, and no aggregate assembled at the edge where the service refused to compute
one. C-07 is not enforced by the router; it is enforced by there being nothing here to enforce.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..content import ContentMissing, DEFAULT_LANGUAGE, LANGUAGES
from ..models import Member
from ..services.learning import (
    AlreadyAsserted,
    NoSuchCapability,
    NotEvidencedByThatUnit,
    QUALIFICATION_CLAIM,
    RUNG_SCHEME_NONE,
    SELF_ASSESSMENT,
    capability_review,
    exits,
    learning_path,
    record_self_assertion,
)
from .auth import current_member

router = APIRouter(prefix="/api", tags=["knowledge"])


def get_session() -> Iterator[Session]:
    """The application's session, resolved at request time rather than at import.

    `main.py` wires this router in, so importing it at module scope would be a cycle — and one that fails
    only in the order FastAPI actually loads things, which is the worst kind. The import inside the body
    runs after `main` is fully initialised, on every request.
    """
    from .main import get_session as application_session

    yield from application_session()


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise HTTPException(
            422, f"unknown language {language!r}; expected one of {list(LANGUAGES)} — A12."
        )
    return language


@router.get("/learning")
def get_learning_path(
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-10. The units, their prerequisites, and the capabilities each one evidences (R-190).

    **`member_id` used to be an optional query parameter and is now the token's member.** Optional meant
    that passing somebody else's id returned their evidence, which is what each capability carries. The
    anonymous mode went with it: the learning path is an authenticated screen, and `GET /api/learning/exits`
    is the route that answers "what is this for" without a session. No unit is locked either way — see
    the service.
    """
    try:
        return learning_path(session, member_id=member.id, language=_language(language))
    except ContentMissing as missing:
        # 503, not 500: the application is fine and the content record is not there. A phrase invented to
        # fill the gap would be the failure this raises to avoid.
        raise HTTPException(503, str(missing)) from missing


@router.get("/learning/exits")
def get_exits(language: str = DEFAULT_LANGUAGE) -> dict:
    """R-193. Three exits, named in the content. Only the second and third touch the Market Place.

    Its own route because the exits are the answer to "what is this for", and a client should be able to
    show them without first asking for a member's learning path.
    """
    chosen = _language(language)
    return {
        "language": chosen,
        "exits": [
            {
                "key": record["key"],
                "name": record["name"].get(chosen),
                "description": record["description"].get(chosen),
                "touches_market_place": bool(record["touches_market_place"]),
                "fictional": bool(record.get("fictional")),
            }
            for record in exits()
        ],
    }


@router.get("/capabilities")
def get_capability_review(
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-10. Every capability statement, and what evidence this member has for it.

    R-191: the statements are the progression. The payload carries no tally of how many are evidenced,
    and `rung` is null on every one of them — D-01.
    """
    try:
        return capability_review(session, member_id=member.id, language=_language(language))
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing


class SelfAssertionRequest(BaseModel):
    """What a member states when they assert a capability about themselves. D-01 / A82.

    **Two fields, and the two that matter are absent.** `evidence_kind` and `assessed_by` are not here:
    they are written by the server from `services/learning.py`'s constants, because they are the two
    places a grade would arrive and `capability_review` renders both straight back to a client. A body
    that could set them would be a body that could store `"assessed_by": "eigentliCH"` — which is the claim
    of standing R-194 forbids — or a kind naming a level.

    No `member_id` either (A11): a member asserts something about themselves, and the member is the
    token's.
    """

    #: One key from `GET /api/capabilities`. A statement that does not exist is a 404, not a 503.
    capability_id: str = Field(..., min_length=1, max_length=32)

    #: R-190, optional. The unit the member worked through, if they want to point at one. The content has
    #: to agree that this unit evidences this capability, so the reference is corroborated rather than
    #: taken on trust — see `record_self_assertion`. Omit it and the assertion stands on its own, which is
    #: what a self-assertion is.
    learning_unit: str | None = Field(default=None, max_length=32)


@router.post("/capabilities/assertions", status_code=201)
def create_self_assertion(
    body: SelfAssertionRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """**D-01's answer, as a route.** A member records that they can do one of the things S-10 names.

    A82: *"it's their responsibility"*, read as self-assessment. eigentliCH does not test, grade or certify
    the assertion — R-194 forbids it any claim of accredited standing, so being in the business of
    examining people was never available to it. What this route does is write down that the member said
    so, with the member named as the one who said it.

    **This is the route R-005 was waiting for.** `POST /api/marketplace/applications` gates being listed
    as supply on capability evidence, and until this existed no real member could hold any, so the gate
    refused everybody with a 403. The gate is unchanged; it is now satisfiable.

    **What it does not do**, each because something forbids it rather than because nobody got to it:

      * It writes no `rung` and there is no field for one — D-01, and `Capability.rung` stays null.
      * It writes no `Decision`. C-09 covers `positions` and `goals`; a capability assertion is a
        statement about the member, not a change to their plan, and a Decision claiming otherwise would
        be permanent under R-040.
      * It has no delete or withdraw. Following A86's reasoning about goals: nothing in the specification
        says what withdrawing an assertion means for a listing already published on the strength of it,
        and answering that question in a form is how a member loses something they cannot get back.

    Refusals, and each is a different fact about the request:

      * **404** — no such capability statement, or no such learning unit.
      * **409** — this member has already asserted this capability. A second identical row could only be
        read as a number of them, which is the tally C-07 forbids.
      * **422** — the named unit does not evidence the named capability (R-190).
    """
    try:
        assertion = record_self_assertion(
            session,
            member_id=member.id,
            capability_id=body.capability_id,
            learning_unit=body.learning_unit,
        )
    except NoSuchCapability as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    except AlreadyAsserted as duplicate:
        # 409, not 200: answering "done" would tell the member something was recorded that was not, and
        # answering 422 would say the request was malformed when it was merely already true.
        raise HTTPException(409, str(duplicate)) from duplicate
    except NotEvidencedByThatUnit as refusal:
        raise HTTPException(422, str(refusal)) from refusal
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing
    session.commit()

    return {
        "id": assertion.id,
        "capability_id": assertion.capability_id,
        # Echoed so a client can show what was recorded without having to re-read the review, and so that
        # what the server chose is visible rather than implied.
        "evidence_kind": assertion.evidence_kind,
        "evidence_ref": assertion.evidence_ref,
        "assessed_by": assertion.assessed_by,
        "assessed_at": assertion.assessed_at.isoformat(),
        "self_asserted": True,
        # D-01 / R-192. Null on the row, null here, and the reason says there is no scheme rather than
        # that one is pending.
        "rung": None,
        "rung_scheme": None,
        "rung_scheme_reason": RUNG_SCHEME_NONE,
        "capabilities_are_self_asserted_reason": SELF_ASSESSMENT,
        "eigentlich_assesses_capabilities": False,
        # R-194 / NG-04, on the one payload where a member might otherwise read the 201 as a pass.
        "qualification_claim": None,
        "qualification_claim_reason": QUALIFICATION_CLAIM,
    }
