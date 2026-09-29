"""S-11 over HTTP. The routes are thin; C-08 is what they leave out.

**The query string is the attack surface.** A paid-placement parameter arrives as a query parameter long
before it arrives as a column, so `GET /api/marketplace/listings` declares its parameters exhaustively —
`roles`, `domain`, `member_id`, `language` — and hands them to `services.marketplace.browse`, whose
signature is the same four. There is no `**kwargs` on either, so `?boost=1` is ignored by FastAPI rather
than reaching anything, and a future `boost=` would have to be written here in full view.

**The router does no ordering of its own.** It returns what the service composed, in the order the service
composed it. Nothing is re-sorted at the edge, which is the other place a commercial signal would fit.

**R-201's filter parameter is named `roles`, not `role`.** The build spec's §6 sketch says `role=`; the
payload has to tell a client how to *remove* the filter, and it can only do that honestly if the name it
prints is the name the client sends. `services.marketplace.FILTER_PARAMETER` is that one name.

**R-004 and R-005 are opposite promises, and both are routes.** Browsing and contacting are GETs that
read no capability assertion at all; applying to be listed is a POST that reads little else.

**Every route here takes a session except `GET /roles`** (A11, wired 31 August 2026). `member_id` is gone
from the query string and from `ApplicationRequest`: the member browsing, the member asking for a
contact and the member applying are all the bearer token's member. Requiring a session is not the gate
R-004 forbids — that rule is about capability evidence, and none of these reads any.

**One thing this did not close, stated rather than left to be discovered.** `POST /applications/{id}/
disclosures` and `.../publish` are addressed by listing id and carry no member field, so the token
requirement is all they gained: any authenticated member can still add a disclosure to, or publish,
another member's draft listing. The ownership chain exists (`Listing.provider_id` -> `Provider.member_id`)
and the check is small; it is not made here because it is a second decision — whether a curator or an
operator may publish on an applicant's behalf is exactly the "who may call this write route" question
`api/remainder.py` records as open for the whole prototype.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..content import ContentMissing, DEFAULT_LANGUAGE, LANGUAGES
from ..models import Member
from ..models.marketplace import Listing, Provider
from ..services.marketplace import (
    InsufficientCapabilityEvidence,
    MissingRegistration,
    NO_FILTER,
    PipelineMismatch,
    UndisclosedListing,
    UnknownListing,
    UnknownRole,
    apply_to_be_listed,
    browse,
    contact_details,
    declare,
    listing_detail,
    publish,
    role_index,
)
from .auth import current_member

router = APIRouter(prefix="/api/marketplace", tags=["market place"])


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


def _roles(roles: list[str] | None):
    """R-201. `None` pre-filters by the member's grid; `roles=all` removes the filter; a list chooses.

    The single-element `["all"]` form is how "remove the filter" survives a query string, and it is the
    literal the payload's `remove_by` prints back.
    """
    if roles is None:
        return None
    if [value.strip() for value in roles] == [NO_FILTER]:
        return NO_FILTER
    return roles


@router.get("/listings")
def get_listings(
    roles: list[str] | None = Query(
        None, description="R-201. Omit to pre-filter by the member's own role grid; `all` to remove it."
    ),
    domain: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """S-11 browse. Provider listings and member offers as peers in one ordered list (R-205).

    **No placement, boost, sponsor or priority parameter, now or later** — C-08. Ordering is the service's
    `ordering_key`, whose inputs are role match, capability evidence and community presence (R-203).

    **Not gated on learning progress** (R-004)** The member is the token's, and selects the role filter
    and nothing else. Requiring a session is not the gate R-004 forbids: R-004 is about capability
    evidence, and nothing here reads any. `member_id` used to be a query parameter, which meant the
    default filter could be pointed at somebody else's role grid — a small leak of what roles a named
    member holds, from a route that never needed to be told.
    """
    try:
        return browse(
            session,
            member_id=member.id,
            roles=_roles(roles),
            domain=domain,
            language=_language(language),
        )
    except UnknownRole as refusal:
        raise HTTPException(422, str(refusal)) from refusal
    except ContentMissing as missing:
        # 503, not 500: the application is fine and the content record is not there.
        raise HTTPException(503, str(missing)) from missing


@router.get("/roles")
def get_role_index(
    language: str = DEFAULT_LANGUAGE,
    session: Session = Depends(get_session),
) -> dict:
    """R-200. The four roles and what sits under each. A supplier may appear under more than one.

    **The one route in this module with no session.** It is the taxonomy: four role names and the domains
    under them, identical for everybody and about nobody. See `api/auth.py` for the whole open list.
    """
    try:
        return role_index(session, language=_language(language))
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing


@router.get("/listings/{listing_id}")
def get_listing(
    listing_id: str,
    language: str = DEFAULT_LANGUAGE,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """One listing. R-202: its disclosures are always present, because a listing without any is a draft.

    **Authenticated although it takes no member id.** R-205 makes a member offer a peer of a provider
    listing in this payload, so the thing on the other end of this id can be a member's own words and
    contact details. `member` is unused: what this route needs is a session, not an identity.
    """
    try:
        return listing_detail(session, listing_id, language=_language(language))
    except UnknownListing as missing:
        raise HTTPException(404, str(missing)) from missing
    except ContentMissing as missing:
        raise HTTPException(503, str(missing)) from missing


@router.get("/listings/{listing_id}/contact")
def get_listing_contact(
    listing_id: str,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-004. How to reach a supplier. Never gated on learning progress, and there is no gate to pass.

    `asked_by` in the payload is the token's member. It used to be a query parameter, so the record of
    who asked was whatever the caller typed.
    """
    try:
        return contact_details(session, listing_id=listing_id, member_id=member.id)
    except UnknownListing as missing:
        raise HTTPException(404, str(missing)) from missing


@router.get("/offers/{offer_id}/contact")
def get_offer_contact(
    offer_id: str,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-205 / R-004. A member offer is contacted the same way a provider listing is, on its own route."""
    try:
        return contact_details(session, offer_id=offer_id, member_id=member.id)
    except UnknownListing as missing:
        raise HTTPException(404, str(missing)) from missing


class ApplicationRequest(BaseModel):
    """R-005 / R-204. What an applicant declares to be listed as supply.

    `qualification_pipeline` is declared, not derived. R-204 says a listing declares which pipeline it is
    under, and a server that worked it out from the domain would make a mismatch unrepresentable — and an
    unrepresentable mismatch is a rule nobody can show is enforced.
    """

    display_name: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)
    domain: str
    qualification_pipeline: str
    roles: list[str] = Field(..., min_length=1)
    summary: str | None = None
    contact: str | None = None
    #: R-204. For the professional pipeline. Empty for the capability one, and the service refuses rather
    #: than dropping them silently.
    registration_refs: list[str] = Field(default_factory=list)


class DisclosureRequest(BaseModel):
    """R-202. `kind` may be `none_declared`: a positive statement, not an empty field."""

    kind: str = Field(..., min_length=1, max_length=60)
    statement: str = Field(..., min_length=1)
    declared_by: str = Field(..., min_length=1, max_length=120)


@router.post("/applications", status_code=201)
def create_application(
    body: ApplicationRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-005. Being listed as supply is gated on capability evidence. Reading and hiring are not.

    Returns a **draft**. The listing is not in the market place until it has been through the disclosure
    gate — see `POST /applications/{listing_id}/disclosures` and `.../publish`. The gate is in
    `services.marketplace.publish`, not here: this endpoint is the convenient path, not the enforcement.

    403 rather than 422 for a missing gate: the request is well-formed and the applicant is not yet
    eligible, which is a different fact from a malformed application.
    """
    try:
        listing = apply_to_be_listed(
            session,
            member_id=member.id,
            display_name=body.display_name,
            title=body.title,
            domain=body.domain,
            qualification_pipeline=body.qualification_pipeline,
            roles=body.roles,
            summary=body.summary,
            contact=body.contact,
            registration_refs=body.registration_refs,
        )
    except InsufficientCapabilityEvidence as gate:
        raise HTTPException(403, str(gate)) from gate
    except MissingRegistration as gate:
        raise HTTPException(403, str(gate)) from gate
    except (PipelineMismatch, UnknownRole) as refusal:
        raise HTTPException(422, str(refusal)) from refusal
    session.commit()
    return {
        "id": listing.id,
        "status": listing.status,
        "qualification_pipeline": listing.qualification_pipeline,
        "roles": list(listing.roles),
        # R-202, said before the applicant asks why nothing appeared.
        "publishable": False,
        "publishable_after": "at_least_one_disclosure",
    }


def _own_listing_or_refuse(session: Session, listing_id: str, member: Member) -> None:
    """Refuse unless this listing's provider is this member. One answer to "is this yours".

    **Why this exists as a function and not as two inline checks.** Authentication was wired across the
    whole surface by removing `member_id` from every signature, which closed the read side completely — a
    caller cannot name someone else because there is nowhere to name them. These two routes address a
    listing by its own id, so the id in the path is not the caller's to begin with, and they were left
    merely *authenticated*: any member with a valid token could add a disclosure to, or publish, another
    member's draft listing.

    Publishing someone else's application is not a feature anyone asked for, so it is closed in the
    restrictive direction rather than left as an open decision. Whether a **curator** may publish on an
    applicant's behalf is a real question and remains open — but it is now an addition someone has to make
    deliberately, rather than a hole that happens to be open. That asymmetry is the point: a permission
    added on purpose is reviewable, one left behind is not.

    The refusal is 404 rather than 403. A member who does not own a listing has no business learning
    whether that listing id exists, and the two answers must be indistinguishable for the same reason
    `login` refuses a wrong address and a wrong password identically.
    """
    listing = session.get(Listing, listing_id)
    provider = session.get(Provider, listing.provider_id) if listing is not None else None
    if listing is None or provider is None or provider.member_id != member.id:
        raise HTTPException(404, f"no application {listing_id!r} belonging to this member")


@router.post("/applications/{listing_id}/disclosures", status_code=201)
def create_disclosure(
    listing_id: str,
    body: DisclosureRequest,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-202. Record what a supplier declares about its economic relationships.

    A session is required, and it must belong to the listing's own applicant — see
    `_own_listing_or_refuse`, which is where the reasoning lives.
    """
    _own_listing_or_refuse(session, listing_id, member)
    try:
        record = declare(
            session,
            listing_id=listing_id,
            kind=body.kind,
            statement=body.statement,
            declared_by=body.declared_by,
        )
    except UnknownListing as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return {"id": record.id, "listing_id": listing_id, "kind": record.kind}


@router.post("/applications/{listing_id}/publish")
def publish_application(
    listing_id: str,
    member: Member = Depends(current_member),
    session: Session = Depends(get_session),
) -> dict:
    """R-202. The disclosure gate, over HTTP. It refuses; it does not warn.

    Owned as well as authenticated — see `_own_listing_or_refuse`.
    """
    _own_listing_or_refuse(session, listing_id, member)
    try:
        listing = publish(session, listing_id)
    except UndisclosedListing as refusal:
        raise HTTPException(422, str(refusal)) from refusal
    except (MissingRegistration, PipelineMismatch) as refusal:
        raise HTTPException(422, str(refusal)) from refusal
    except UnknownListing as missing:
        raise HTTPException(404, str(missing)) from missing
    session.commit()
    return {"id": listing.id, "status": listing.status}
