"""R-231's erasure over HTTP. One route, and it destroys a member's record.

    POST /api/settings/erasure

**Its own module, for the same reason `services/erasure.py` is its own module**: this is the only route in
the application that removes rows, the only one that stands the C-09 guard down, and the only one whose
mistake cannot be corrected afterwards. A reader looking for the destructive path should find it by the
name of one file, not by scrolling past a language setting. `api/remainder.py` keeps the other six
`/api/settings/*` routes and its docstring points here.

**Wiring.** `api/main.py` needs one line, and this module deliberately does not add it:

    from .erasure import router as erasure_router

...added to the tuple that `main.py` loops over with `app.include_router`. Until then the route is not
served, and `tests/test_consent.py` and `tests/test_erasure_route.py` mount this router on an app they
build themselves — which is how they run against a throwaway in-memory database and never the developer's
`backend/eigentlich.db`.

**The dependencies are imported, not redefined, and that is a safety property rather than tidiness.**
`get_session` comes from `api/auth.py` and `get_store` from `api/remainder.py`. Every other router in this
package defines its own `get_session`, and `tests/conftest.py` carries a list of those modules so that a
test can override all of them at once — the list exists because A68 was a test that silently used the wrong
database. A module of mine on that list is a module someone can forget to add, and here forgetting it would
point an *erasure* at the real database. Sharing one dependency object means overriding
`eigentlich.api.auth.get_session` covers this route too, with nothing to remember.

**What the route adds to the service, and it is nothing.** The confirmation sentence, the password check
and the Decision-before-erasure ordering are all in `services/erasure.erase_on_member_request`, so a second
route added next year cannot perform the act without them. This layer translates three exceptions into
three status codes and commits.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Member
from ..services.auth import AuthenticationFailed
from ..services.erasure import (
    CONFIRMATION_PHRASES,
    ErasureNotConfirmed,
    confirmation_phrase,
    erase_on_member_request,
)
from ..services.settings import ERASURE_ROUTE
from ..services.vault import VaultStore
from .auth import current_member, get_session
from .remainder import get_store

router = APIRouter(prefix="/api", tags=["erasure"])

#: **Derived from the service's constant, not typed again.** `POST /api/settings/deletion` hands the member
#: `execute_at: ERASURE_ROUTE`, and a receipt that names a path this router does not serve is the
#: two-lists-one-fact defect A73 and A91 are both instances of. `test_erasure_route.py` asserts the
#: application serves exactly what the receipt promises.
ERASURE_PATH = ERASURE_ROUTE.split(" ", 1)[1][len("/api"):]


class ErasureConfirmation(BaseModel):
    """What a member sends to destroy their own record. Two required strings and no member id.

    **No `member_id`, and not because it would be checked.** A81's rule: a route that never receives one
    cannot be given the wrong one. On this route that is not a hardening, it is the difference between a
    member erasing themselves and one member erasing another.

    **No boolean.** An `understood: true` field was considered and left out. Pydantic's lax mode accepts
    `1`, `"y"` and `"on"` as `true`, so a field meant to represent deliberate agreement would have been the
    most permissive input on the request — and a checkbox is one mis-click either way. The typed sentence
    carries the same meaning and has no ambiguous value.
    """

    confirmation: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "The published sentence, typed exactly: "
            f"{CONFIRMATION_PHRASES['de']!r} (de) or {CONFIRMATION_PHRASES['en']!r} (en)."
        ),
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="The member's own password. A valid session token alone does not authorise this.",
    )
    reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional, and recorded on the Decision — which the erasure then redacts.",
    )


@router.get(ERASURE_PATH)
def get_erasure_confirmation(
    member: Member = Depends(current_member),
) -> dict:
    """What the confirmation step requires, in the member's language. Reads nothing and writes nothing.

    Guarded like every other member route even though the answer barely differs per member: it differs by
    the member's language, and an unauthenticated route whose payload tells anyone the exact sentence that
    destroys an account is a route that exists to be pasted into a phishing page.

    The receipt of what will and will not be removed comes from `POST /api/settings/deletion`, which
    records the request. This says only what the second step needs.
    """
    language = (member.locale or "de-CH").split("-")[0].lower()
    if language not in CONFIRMATION_PHRASES:
        language = "de"
    return {
        "member_id": member.id,
        "language": language,
        "confirmation_phrase": confirmation_phrase(language),
        "requires_password": True,
        "irreversible": True,
        # Named rather than implied: the client should not present this as reversible, and the two rows
        # that survive do so at the storage layer and not by choice.
        "append_only_rows_are_emptied_not_removed": True,
    }


@router.post(ERASURE_PATH)
def post_erasure(
    body: ErasureConfirmation,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
    store: VaultStore = Depends(get_store),
) -> dict:
    """R-231. **The member's data is destroyed here.** Irreversible, and the response is the receipt.

    200 rather than 201: nothing was created. The body is `ErasureReport.as_dict()` — what was deleted and
    what was redacted, per table, with the Decision id of the request. A member is handed the act rather
    than a reassurance, which is the same choice `ErasureReport` was written for.

    Refusals, and each one leaves the record intact:

      * **422** the confirmation sentence was not typed exactly (`ErasureNotConfirmed`).
      * **403** the password does not verify. 403 and not 401: the session is valid and the member is who
        they say — what is wrong is the password in the body, and a 401 would tell the client to throw away
        a good token. The same reading `POST /api/password` takes.
      * **404** no such member. Reachable only if the row went away between the token being resolved and
        this line, which is a concurrent erasure.

    The commit is after the service returns, so a failure anywhere inside it rolls the whole erasure back
    together with the Decision that recorded the request — including the trigger drop and re-creation,
    which is why `services/erasure.py` insists on doing that on the session's own connection (A66).

    **The token dies with the account.** The member's `sessions` rows are among those deleted, so the
    caller's next request is a 401. A client should treat this response as a logout.
    """
    try:
        payload = erase_on_member_request(
            session,
            store,
            member_id=member.id,
            confirmation=body.confirmation,
            password=body.password,
            reason=body.reason,
        )
    # The three rollbacks below are insurance and say so rather than looking load-bearing (A81). All three
    # refusals are raised by the service before it writes anything: the confirmation and the password are
    # checked before `mutate_plan` opens, and the member lookup before either. What they would keep clean
    # is a future ordering in which that stops being true.
    except ErasureNotConfirmed as unconfirmed:
        session.rollback()
        raise HTTPException(422, str(unconfirmed)) from unconfirmed
    except AuthenticationFailed as refused:
        session.rollback()
        raise HTTPException(403, "password is incorrect") from refused
    except LookupError as missing:
        session.rollback()
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return payload


__all__ = ["ERASURE_PATH", "ErasureConfirmation", "router"]
