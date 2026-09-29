"""S-11, the Market Place. C-08 is the constraint that shapes this module the way it shapes the tables.

**"Market Place ordering cannot be bought."** Three things hold it, and none of them is care:

  * `browse` takes no paid-placement, boost, sponsor or priority parameter, and it takes no `**kwargs`
    either — an unknown keyword is a `TypeError` at the call site rather than something quietly ignored.
  * ordering is decided by `ordering_key`, which is handed an `OrderingInputs` — a frozen record of
    exactly the three inputs R-203 names. It is given no listing, no provider and no session, so there is
    no fee it could read and no query it could add to find one. Reaching a fee from inside the ordering
    would mean changing the signature, which is a visible act rather than an oversight.
  * the projections that build an `OrderingInputs` read the listing row and the offering member's own
    assertions and attendances. `Provider` — the only table carrying `billing_plan` and `billing_fee_chf`
    — is named nowhere in any of them. `ORDERING_FUNCTIONS` below lists the complete set, and
    `test_listing_ranking_cannot_read_fee_fields` scans exactly that set and then proves behaviourally
    that moving a provider's fee moves nothing.

Provider display names and contacts *are* read, because R-004 says a member may contact supply. They are
attached **after** the order is fixed, in `_entry_for_listing`, so the composition step cannot influence
the sort even by accident.

**And a fourth thing, added after the first three turned out not to be the whole of it.** A fee is not the
only way to buy a position. `roles` is written by the supplier, audited by nobody, and the ordering input
built from it used to be a *count* of matched roles — monotone in how many you declared, so declaring all
four was free and beat a specialist with six capability assertions and six attendances. `role_match_share`
makes the input a share of what was declared rather than a count of what matched: declaring a role nobody
asked for lowers it, and because it is capped no declaration can beat another declaration, only tie with
it — and ties fall to the two inputs that have to be earned. C-08's principle is that ordering follows
evidence rather than self-description, and that is now arithmetic rather than intent.

**The two earned inputs were dead on the real write path.** `Listing.standing_inputs` was written once,
empty, by `apply_to_be_listed`, and never derived from the database again, so every listing the
application itself created ranked on `role_match` and a row id. `member_standing` did the derivation, but
only for member offers. Both the application path and `publish` now derive it, and they derive it by
calling `member_standing` and nothing else — which is what keeps a field the ordering reads inside the
same guarantee as the functions that read it.

**R-205: alongside, not beneath.** Member offers and provider listings come back interleaved in one
`entries` list, each carrying its `entry_kind`, ordered by the same function on the same three inputs.
Two sibling keys would still let a client render one under a heading below the other; one list of peers
cannot be rendered that way without the client inventing the subordination itself.

**R-202: the publish path is the enforcement.** `publish` is the only function here that writes
`status = "published"`, and it refuses a listing with no `Disclosure` row. A validator somewhere else
would be the convenient path; this is the only path. `none_declared` is one of the kinds, because "we
have no economic relationships" is a claim somebody made and can be held to.

**R-204: two pipelines, and this module does not soften the CHECK.** `apply_to_be_listed` takes the
pipeline as an argument rather than deriving it from the domain: deriving it would make a mismatch
unrepresentable and so make the CHECK untestable, which is working around it in the shape of respecting
it. A mismatch raises here, and the CHECK is still there underneath for callers who never came this way.

**A41.** The seed content is fictional and says so in the file; `seed` refuses to write a record that is
not marked, so the marker is load-bearing rather than decorative.

**NG-04.** Nothing here claims federal or accredited standing. Capability assertions are eigentliCH's own,
registration references belong to the provider who supplied them, and the payloads say so out loud rather
than leaving it to be read out of an absent key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..content import CONTENT, DEFAULT_LANGUAGE, ContentMissing
from ..models import (
    Attendance,
    CapabilityAssertion,
    DOMAINS,
    Disclosure,
    Listing,
    MemberOffer,
    PIPELINES,
    Position,
    Provider,
    ROLES,
    utcnow,
)

#: The one content record this module reads, loaded the way `content.py` loads its own — same root, same
#: exception, no literal fallback — rather than through it, because wiring an accessor into `content.py`
#: is an edit to a file this change does not own.
MARKETPLACE = "marketplace"

#: R-204. Which pipeline each domain goes through. The same rule the model's CHECK states, said once here
#: so the service can refuse a mismatch with a sentence instead of an IntegrityError — and *only* refuse.
#: Nothing in this module rewrites a caller's pipeline to make it fit.
PIPELINE_FOR_DOMAIN = {
    "financial": "capability",
    "health": "professional_registration",
    "education": "professional_registration",
}

#: R-203. The complete set of ordering inputs, named once. A fourth entry here is a change to C-08.
ORDERING_INPUT_NAMES = ("role_match", "capability_evidence", "community_presence")

#: `role_match` is a SHARE of what an entry declares, not a count of it — see `role_match_share` for why
#: a count is a thing a supplier can help itself to. Held in twelfths so it stays a whole number: twelve
#: is the least common multiple of the numbers of roles an entry can declare (1, 2, 3 or 4), so every
#: share is exact and two equal shares compare equal rather than nearly so.
ROLE_MATCH_SCALE = 12

#: C-08. The complete set of functions that decide order. `test_listing_ranking_cannot_read_fee_fields`
#: reads this tuple and scans exactly these — so adding a fifth participant without adding it here is the
#: one way to evade the scan, and that is why the same test also asserts this module sorts in one place.
ORDERING_FUNCTIONS = (
    "ordering_key",
    "role_match_share",
    "listing_ordering_inputs",
    "offer_ordering_inputs",
    "member_standing",
)

#: R-205. Two kinds of entry, and they are peers.
ENTRY_KINDS = ("provider_listing", "member_offer")

#: R-201. The parameter the role filter lives on, and the value that drops it. Named so the payload can
#: tell a client how to remove the filter rather than expecting it to know.
FILTER_PARAMETER = "roles"
NO_FILTER = "all"

#: NG-04. eigentliCH awards nothing and verifies nothing: a capability assertion is its own statement, and a
#: registration reference belongs to the provider who supplied it. Named once — a second phrasing of this
#: elsewhere is a second claim to keep honest.
QUALIFICATION_CLAIM = "eigentlich_awards_no_qualification"


class NotMarkedFictional(Exception):
    """A41. Seed content that does not declare itself fictional is not written to the database.

    The honesty rule is only worth something if something enforces it. A record that reaches the store
    unmarked is a record that can be screenshotted as real supply, and the marker is in the content file
    rather than added on the way in because the model layer is fixed for this phase — so `seed` is where
    it bites.
    """


#: R-202. **Imported, not declared.** It used to be defined here, and `publish` was the only thing that
#: raised it — one enforcement point for a constraint about what may be in the store. The storage-layer
#: guard in `models/marketplace.py` is the second, and both raise this one class, because two exception
#: types for one rule is how two enforcement points come to mean different things.
from ..models.marketplace import UndisclosedListing  # noqa: E402,F401


class PipelineMismatch(Exception):
    """R-204. The two qualification pipelines are not interchangeable, and this refuses rather than fixes."""


class MissingRegistration(Exception):
    """R-204 / R-005. Health and education supply is gated on a professional registration reference.

    Capability evidence does not substitute. That is the whole of what "not interchangeable" means on this
    side of the pair.
    """


class InsufficientCapabilityEvidence(Exception):
    """R-005. Being listed as supply is gated on capability evidence. Reading and hiring are not."""


class UnknownListing(Exception):
    """No such listing in the market place. A draft is not in the market place."""


class UnknownRole(Exception):
    """R-200. The index is by role, and a role that is not one of the four is not a filter."""


@lru_cache(maxsize=1)
def _marketplace() -> dict:
    path = CONTENT / f"{MARKETPLACE}.json"
    if not path.exists():
        raise ContentMissing(
            f"marketplace content not found at {path}. S-11's providers, listings, disclosures and member "
            f"offers are content records; there is deliberately no literal to fall back to."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def content_is_fictional() -> bool:
    """A41. True while the shipped seed supply is demonstration material rather than real."""
    return bool(_marketplace().get("fictional", False))


def seed_providers() -> list[dict]:
    return _marketplace()["providers"]


def seed_listings() -> list[dict]:
    return _marketplace()["listings"]


def seed_member_offers() -> list[dict]:
    """R-205. Co-investment, succession, property, skills and services."""
    return _marketplace()["member_offers"]


def seed_disclosures() -> list[dict]:
    """R-202. Flattened across listings, so the A41 guard and the key-length test can walk them."""
    return [record for listing in seed_listings() for record in listing["disclosures"]]


def required_pipeline(domain: str) -> str:
    """R-204. Which pipeline a domain goes through. Raises on a domain the model does not have."""
    if domain not in DOMAINS:
        raise PipelineMismatch(f"unknown domain {domain!r}; expected one of {list(DOMAINS)}")
    return PIPELINE_FOR_DOMAIN[domain]


def _localised(block: dict, language: str) -> str | None:
    """A member-facing string in one language, or None. Never a placeholder, never the other language."""
    return block.get(language) or None


# ---------------------------------------------------------------- ordering (C-08, R-203)


@dataclass(frozen=True)
class OrderingInputs:
    """R-203 / C-08. The complete set of inputs to the ordering, and there is nothing else on it.

    Frozen and flat on purpose. A dataclass holding a `Listing` would be a dataclass holding
    `listing.provider.billing_fee_chf` one attribute hop away; holding three integers and an opaque
    tiebreak holds nothing.

    `tiebreak` is the listing's or offer's own row id. An order has to be total or it is not reproducible
    between two requests, and the id is the only candidate nobody chooses for themselves: it is opaque,
    system-assigned, and carries no fact about the supplier at all.
    """

    role_match: int
    capability_evidence: int
    community_presence: int
    tiebreak: str


def ordering_key(inputs: OrderingInputs) -> tuple:
    """**The ranking function.** C-08: it is handed three integers and an opaque tiebreak, and nothing else.

    No listing, no provider, no session. There is no fee in scope, and no way to fetch one without
    changing this signature — which is the point of the signature.
    """
    return (
        -inputs.role_match,
        -inputs.capability_evidence,
        -inputs.community_presence,
        inputs.tiebreak,
    )


def role_match_share(declared_roles, requested_roles) -> int:
    """R-203's first input. **A share of what was declared, not a count of what matched.**

    C-08 says Market Place ordering cannot be bought. The fee fields are the obvious way to buy it and
    they are held off by `ordering_key`'s signature — but a supplier writes its own `roles`, nobody
    audits them, and the count of matched roles is *monotone in how many you declare*. Ticking all four
    boxes was therefore free, it raised the input that dominates the ordering, and a generalist with one
    capability assertion and four declared roles came out above a specialist with six assertions and six
    attendances on any query naming more than one role. Ordering could not be bought; it could be taken
    with a checkbox, which is the same failure wearing different clothes.

    **The fix, and why this one.** A share — matched roles over declared roles — inverts the incentive
    instead of merely blunting it. Declaring a role the member did not ask for *lowers* the share, so
    breadth is no longer free; and because the share is capped at 1, **no declaration can beat another
    declaration — the best it can do is tie, and a tie is broken by capability evidence and community
    presence.** That is C-08's principle stated as an arithmetic property rather than as a hope: ordering
    follows evidence, because self-description has a ceiling every honest supplier already reaches.

    The alternatives were weighed and rejected. Making the input binary would have removed the incentive
    and the input with it: `browse` filters to entries that match at least one requested role, so every
    survivor would score the same and R-203 would be down to two live inputs — the very defect being
    fixed one input over. Weighting it below the evidence inputs leaves the count, so a generalist still
    wins every tie, and it silently reorders R-203's own sentence. Requiring each declared role to be
    corroborated by evidence is the purest reading of "ordering follows evidence" and is the one the data
    cannot support: `Capability` carries no role and D-01 leaves the rung scheme undecided, so the
    role-to-capability mapping would have to be invented here. Capping the count is the share without the
    arithmetic that makes the cap principled.

    Returns twelfths (`ROLE_MATCH_SCALE`) so the ordering stays integer and exact. Zero when nothing was
    asked for — an unfiltered browse asks for no role, and then the ordering rests entirely on the two
    earned inputs, which is the right answer rather than an accident.
    """
    declared = {role for role in declared_roles or [] if role in ROLES}
    asked = set(requested_roles or [])
    if not declared or not asked:
        return 0
    return len(declared & asked) * ROLE_MATCH_SCALE // len(declared)


def listing_ordering_inputs(listing: Listing, requested_roles: tuple) -> OrderingInputs:
    """Project one listing onto R-203's three inputs. Reads the listing row and nothing beyond it.

    `standing_inputs` is derived from the offering member's own assertions and attendances on the write
    path — see `apply_to_be_listed` and `publish` — so the two earned inputs carry the database's answer
    rather than the empty dict they used to be given once and never revisited.
    """
    standing = listing.standing_inputs or {}
    return OrderingInputs(
        role_match=role_match_share(listing.roles, requested_roles),
        capability_evidence=len(standing.get("capability_evidence") or []),
        community_presence=len(standing.get("community_presence") or []),
        tiebreak=listing.id,
    )


def offer_ordering_inputs(offer: MemberOffer, requested_roles: tuple, standing: dict) -> OrderingInputs:
    """R-205 / R-203. A member offer is projected onto the *same* three inputs as a listing.

    Not a courtesy: if member offers were ordered by a different rule, or by no rule, they would end up
    in a block of their own, which is the "beneath" R-205 forbids. `standing` comes from
    `member_standing` and is the same shape as a listing's `standing_inputs`.
    """
    return OrderingInputs(
        role_match=role_match_share(offer.roles, requested_roles),
        capability_evidence=len(standing.get("capability_evidence") or []),
        community_presence=len(standing.get("community_presence") or []),
        tiebreak=offer.id,
    )


def member_standing(session: Session, member_id: str) -> dict:
    """The capability evidence and community presence a member has, in `standing_inputs` shape.

    R-221: attendance is an input to community presence and is *not* shown back to the member. This
    returns the references themselves rather than a number, and no payload in this module renders either
    list — see `_entry_for_offer`, which carries neither.

    One pair of queries per offering member. The number of member offers on a browse page is small, and a
    batched version would be an optimisation nobody has needed yet.
    """
    evidence = session.execute(
        select(CapabilityAssertion.capability_id).where(CapabilityAssertion.member_id == member_id)
    ).scalars().all()
    presence = session.execute(
        select(Attendance.gathering_id).where(
            Attendance.member_id == member_id, Attendance.attended.is_(True)
        )
    ).scalars().all()
    return {"capability_evidence": sorted(set(evidence)), "community_presence": sorted(set(presence))}


def _in_order(pairs: list[tuple[OrderingInputs, dict]]) -> list[dict]:
    """The one place in this module where anything is put in order.

    Deliberately the only `sorted` call here, so that "the ordering is decided by `ordering_key`" is a
    statement a test can check rather than a claim about every function someone might add later.
    """
    return [entry for _, entry in sorted(pairs, key=lambda pair: ordering_key(pair[0]))]


# ---------------------------------------------------------------- R-201, the visible removable filter


def _member_role_grid(session: Session, member_id: str) -> list[str]:
    """The roles a member has actually filled in. In `ROLES` order, so two requests agree."""
    filled = set(
        session.execute(
            select(Position.role).where(Position.member_id == member_id, Position.active.is_(True))
        ).scalars()
    )
    return [role for role in ROLES if role in filled]


def _role_filter(session: Session, member_id: str | None, roles) -> tuple[tuple, dict]:
    """R-201. Resolve the role filter, and describe it well enough for a client to show and remove it.

    Three ways in. `roles="all"` is the member having removed it; an explicit list is the member having
    chosen; `None` with a member falls back to their own role grid, which is the pre-filter R-201 asks
    for. The returned block always names the parameter and the value that drops the filter, because "the
    filter is visible and removable" is a promise about the payload, not about a button somebody
    remembers to build.
    """
    common = {
        "parameter": FILTER_PARAMETER,
        "visible": True,
        "removable": True,
        "remove_by": {"parameter": FILTER_PARAMETER, "value": NO_FILTER},
        "all_roles": list(ROLES),
    }

    if roles == NO_FILTER:
        return (), {**common, "applied": False, "roles": [], "source": "removed_by_the_member"}

    if roles is not None:
        chosen = tuple(roles)
        unknown = [role for role in chosen if role not in ROLES]
        if unknown:
            raise UnknownRole(
                f"R-200: the market place is indexed by the four roles, not by profession. "
                f"{unknown} are not among {list(ROLES)}."
            )
        ordered = tuple(role for role in ROLES if role in chosen)
        return ordered, {**common, "applied": True, "roles": list(ordered), "source": "explicit"}

    if member_id is None:
        return (), {**common, "applied": False, "roles": [], "source": None,
                    "reason": "no_member_to_pre_filter_from"}

    grid = _member_role_grid(session, member_id)
    if not grid:
        # R-020: a grid is useful at n=1, and it is legitimate at n=0 too. An empty grid pre-filters
        # nothing rather than filtering everything away.
        return (), {**common, "applied": False, "roles": [], "source": None,
                    "reason": "role_grid_is_empty"}
    return tuple(grid), {**common, "applied": True, "roles": list(grid), "source": "member_role_grid"}


# ---------------------------------------------------------------- payload composition


def _disclosure_entries(listing: Listing, language: str) -> list[dict]:
    """R-202. Every listing displays its disclosures, so this is never empty for a published listing.

    The statement is rendered from the content record where the listing is seeded supply, and from the
    stored row otherwise. Same reason as `learning.py`: the row carries the authored language, and the
    sentence a member reads comes from the content record in their own language.
    """
    authored = {
        record["key"]: record
        for entry in seed_listings()
        for record in entry["disclosures"]
    }
    entries = []
    for row in listing.disclosures:
        record = authored.get(row.id)
        statement = _localised(record["statement"], language) if record else row.statement
        entries.append(
            {
                "id": row.id,
                "kind": row.kind,
                "statement": statement or row.statement,
                "declared_at": row.declared_at.isoformat(),
                "declared_by": row.declared_by,
            }
        )
    return entries


def _entry_for_listing(session: Session, listing: Listing, language: str) -> dict:
    """One provider listing as a client receives it.

    Called **after** the order is fixed. This is where the provider is read — for a display name and a
    contact, which R-004 requires — and reading it here rather than in a projection is what keeps C-08 a
    property of the code's shape rather than of its author's memory.
    """
    authored = {record["key"]: record for record in seed_listings()}
    record = authored.get(listing.id)
    supplier = session.get(Provider, listing.provider_id)

    return {
        "entry_kind": "provider_listing",
        "id": listing.id,
        "title": (_localised(record["title"], language) if record else None) or listing.title,
        "summary": (_localised(record["summary"], language) if record else None) or listing.summary,
        # R-200. The index is roles; the provider's profession is nowhere in this payload.
        "roles": list(listing.roles or []),
        "domain": listing.domain,
        # R-204. Which pipeline this listing declared, and what that pipeline carries as evidence.
        "qualification_pipeline": listing.qualification_pipeline,
        "registration_refs": list(listing.registration_refs or []),
        "registration_refs_are_the_providers_own": True,
        "supplier": {
            "id": supplier.id if supplier else None,
            "display_name": supplier.display_name if supplier else None,
            # R-004. Present for everyone, at all times. See `contact_details` for the same promise made
            # where a client would ask for it explicitly.
            "contact": supplier.contact if supplier else None,
            "is_a_member": bool(supplier.member_id) if supplier else False,
            "fictional": bool(supplier.fictional) if supplier else False,
        },
        # R-202. Always present, never empty — `publish` is what makes that true.
        "disclosures": _disclosure_entries(listing, language),
        "fictional": bool(listing.fictional),
    }


def _entry_for_offer(offer: MemberOffer, language: str) -> dict:
    """R-205. A member offer as a peer of a provider listing, in the same list and the same shape of key.

    It carries no standing numbers. R-221 records attendance as an input to Market Place standing and
    forbids showing it back to the member as a score, and a member offer is a member looking at their own
    row as often as anyone else's.
    """
    authored = {record["key"]: record for record in seed_member_offers()}
    record = authored.get(offer.id)
    return {
        "entry_kind": "member_offer",
        "id": offer.id,
        "member_id": offer.member_id,
        # co_investment | succession | property | skills | services — R-205's list, open by design.
        "kind": offer.kind,
        "direction": offer.direction,
        "title": (_localised(record["title"], language) if record else None) or offer.title,
        "body": (_localised(record["body"], language) if record else None) or offer.body,
        "roles": list(offer.roles or []),
        "fictional": bool(offer.fictional),
    }


# ---------------------------------------------------------------- browse (S-11, R-004)


def browse(
    session: Session,
    *,
    member_id: str | None = None,
    roles=None,
    domain: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """S-11's browse view: provider listings and member offers, interleaved, in one order.

    **The whole signature is C-08.** Role, domain, member and language. No placement, no boost, no
    sponsor, no priority, and no `**kwargs` for one to arrive through unnoticed.

    `roles=None` pre-filters by the member's own role grid (R-201); `roles="all"` removes the filter;
    an explicit list is the member choosing. The returned `filter` block names which of the three
    happened and how to drop it.

    **Never gated on learning progress** (R-004). `member_id` is used for exactly one thing here — the
    role grid — and nothing about the browsing member's capability assertions is read, so a member on
    their first day sees what a member of three years sees.
    """
    requested, applied_filter = _role_filter(session, member_id, roles)

    if domain is not None and domain not in DOMAINS:
        raise ContentMissing(f"unknown domain {domain!r}; expected one of {list(DOMAINS)}")

    # R-202. Only published listings are in the market place, and a published listing has disclosures
    # because `publish` is the only way it got here.
    query = select(Listing).where(Listing.status == "published")
    if domain is not None:
        query = query.where(Listing.domain == domain)

    pairs: list[tuple[OrderingInputs, dict]] = []

    for listing in session.execute(query).scalars().all():
        if requested and not set(listing.roles or []) & set(requested):
            continue
        pairs.append((listing_ordering_inputs(listing, requested), _entry_for_listing(session, listing, language)))

    # R-205. Alongside, in the same list, filtered by the same roles and ordered by the same function.
    # A member offer has no domain — co-investment is not "financial supply" — so a domain filter narrows
    # provider listings and leaves member offers where they are rather than hiding them.
    for offer in session.execute(select(MemberOffer).where(MemberOffer.active.is_(True))).scalars().all():
        if requested and not set(offer.roles or []) & set(requested):
            continue
        standing = member_standing(session, offer.member_id)
        pairs.append((offer_ordering_inputs(offer, requested, standing), _entry_for_offer(offer, language)))

    return {
        "member_id": member_id,
        "language": language,
        "fictional": content_is_fictional(),
        # R-201, said in the payload rather than left to a client to reconstruct from what it asked for.
        "filter": applied_filter,
        "domain": domain,
        # R-205. One list of peers. Not `listings` with `member_offers` underneath it.
        "entries": _in_order(pairs),
        "entry_kinds": list(ENTRY_KINDS),
        "entry_kinds_are_peers": True,
        # C-08 / R-203, stated where a client author reads it before designing a screen that implies
        # anything else is available to buy.
        "ordering_inputs": list(ORDERING_INPUT_NAMES),
        "ordering_is_not_purchasable": True,
        # R-004 and R-005 are opposite promises about the same surface, so both are named.
        "browsing_is_not_gated": True,
        "contacting_is_not_gated": True,
        "being_listed_is_gated_on": "capability_evidence_or_professional_registration",
        # NG-04.
        "qualification_claim": None,
        "qualification_claim_reason": QUALIFICATION_CLAIM,
    }


def listing_detail(session: Session, listing_id: str, *, language: str = DEFAULT_LANGUAGE) -> dict:
    """One listing, with its disclosures always present (R-202).

    A draft raises rather than rendering. A listing that has not been through `publish` has not been
    through the disclosure gate, and serving it would be the gap R-202 closes.
    """
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise UnknownListing(f"no listing {listing_id!r}")
    if listing.status != "published":
        raise UnknownListing(
            f"listing {listing_id!r} is {listing.status!r} and is not in the market place. R-202: a "
            f"listing reaches members through `publish`, which is where the disclosure gate is."
        )
    entry = _entry_for_listing(session, listing, language)
    return {
        "language": language,
        "fictional": content_is_fictional(),
        "listing": entry,
        "ordering_inputs": list(ORDERING_INPUT_NAMES),
        "ordering_is_not_purchasable": True,
        "contacting_is_not_gated": True,
        "qualification_claim": None,
        "qualification_claim_reason": QUALIFICATION_CLAIM,
    }


def role_index(session: Session, *, language: str = DEFAULT_LANGUAGE) -> dict:
    """R-200. The four roles, and what sits under each. A provider may appear under more than one.

    Built by asking `browse` once per role rather than by grouping a single pass, so that what a member
    sees under `growth` is exactly what they see when they filter to `growth`.
    """
    return {
        "language": language,
        "fictional": content_is_fictional(),
        "indexed_by": "role",
        # R-200 stated as an absence a client can read, because "not by profession" is the half that gets
        # designed away first.
        "not_indexed_by_profession": True,
        "a_supplier_may_appear_under_several_roles": True,
        "roles": [
            {
                "key": role,
                "entries": browse(session, roles=[role], language=language)["entries"],
            }
            for role in ROLES
        ],
        "ordering_inputs": list(ORDERING_INPUT_NAMES),
        "ordering_is_not_purchasable": True,
    }


def contact_details(
    session: Session,
    *,
    listing_id: str | None = None,
    offer_id: str | None = None,
    member_id: str | None = None,
) -> dict:
    """R-004. How to reach a supplier or a member. **Never gated on learning progress.**

    `member_id` is the member asking, and it is recorded in the payload so a client can show whose
    request this is. It is not consulted: there is no capability assertion, no unit and no assessment
    anywhere in this function, which is what "never gated" has to mean if it is to survive a redesign.
    """
    if listing_id is not None:
        listing = session.get(Listing, listing_id)
        if listing is None or listing.status != "published":
            raise UnknownListing(f"no published listing {listing_id!r}")
        supplier = session.get(Provider, listing.provider_id)
        return {
            "asked_by": member_id,
            "entry_kind": "provider_listing",
            "id": listing.id,
            "display_name": supplier.display_name if supplier else None,
            "contact": supplier.contact if supplier else None,
            "gated_on": None,
            "gated_on_reason": "browsing_and_contacting_are_never_gated",
        }

    if offer_id is not None:
        offer = session.get(MemberOffer, offer_id)
        if offer is None or not offer.active:
            raise UnknownListing(f"no active member offer {offer_id!r}")
        return {
            "asked_by": member_id,
            "entry_kind": "member_offer",
            "id": offer.id,
            "display_name": None,
            # A member offer is reached through the member, not through an address in a public payload.
            "contact": None,
            "contact_via": {"parameter": "member_id", "value": offer.member_id},
            "gated_on": None,
            "gated_on_reason": "browsing_and_contacting_are_never_gated",
        }

    raise UnknownListing("name a listing_id or an offer_id")


# ---------------------------------------------------------------- being listed (R-005, R-204, R-202)


def _capability_evidence_for(session: Session, member_id: str) -> list[str]:
    """R-005's gate, read off the same derivation the ordering uses.

    It used to run its own query. Two derivations of "what has this member evidenced" can disagree, and
    the one that decided whether a member may be listed at all is the wrong one to let drift.
    """
    return member_standing(session, member_id)["capability_evidence"]


def apply_to_be_listed(
    session: Session,
    *,
    member_id: str,
    display_name: str,
    title: str,
    domain: str,
    qualification_pipeline: str,
    roles,
    summary: str | None = None,
    contact: str | None = None,
    registration_refs=(),
) -> Listing:
    """R-005. Being listed as supply is gated. Reading and hiring are not.

    Two gates, and R-204 is why they are two rather than one with a fallback:

      * `capability` (financial supply) requires the member to hold at least one recorded capability
        assertion. A registration reference does not stand in for one, and passing refs on a capability
        listing raises rather than being quietly dropped.
      * `professional_registration` (health and education) requires at least one registration reference.
        Capability assertions do not stand in for one, however many the member holds.

    The pipeline is an argument, not a derivation. R-204 says a listing *declares* which pipeline it is
    under; deriving it from the domain would make a mismatch unrepresentable, and an unrepresentable
    mismatch is a CHECK constraint nobody can show works.

    Returns a **draft**. A listing becomes visible through `publish`, which is where R-202's disclosure
    gate is, and an application that ended in a published listing would route around it.
    """
    if qualification_pipeline not in PIPELINES:
        raise PipelineMismatch(
            f"unknown pipeline {qualification_pipeline!r}; expected one of {list(PIPELINES)}"
        )
    expected = required_pipeline(domain)
    if qualification_pipeline != expected:
        raise PipelineMismatch(
            f"R-204: {domain!r} supply goes through the {expected!r} pipeline, and this listing declares "
            f"{qualification_pipeline!r}. The two are not interchangeable; the model carries the same "
            f"rule as a CHECK, and this refuses rather than rewriting what the applicant declared."
        )

    chosen = [role for role in ROLES if role in set(roles)]
    if not chosen:
        raise UnknownRole(
            f"R-200: a listing is indexed by the four roles. {list(roles)} names none of {list(ROLES)}."
        )

    refs = list(registration_refs)

    if qualification_pipeline == "capability":
        if refs:
            raise PipelineMismatch(
                "R-204: registration references belong to the professional pipeline. A capability-assessed "
                "listing carrying them would be one pipeline wearing the other's evidence."
            )
        evidence = _capability_evidence_for(session, member_id)
        if not evidence:
            raise InsufficientCapabilityEvidence(
                f"R-005: being listed as supply is gated on capability evidence, and member {member_id!r} "
                f"has no recorded assertion. Browsing and contacting are not gated — see `browse` and "
                f"`contact_details`, neither of which reads this."
            )
    else:
        if not refs:
            raise MissingRegistration(
                f"R-204: {domain!r} supply goes through professional registration, and this application "
                f"carries no reference. Capability evidence does not substitute: that is what makes the "
                f"two pipelines not interchangeable rather than merely different."
            )

    supplier = Provider(display_name=display_name, contact=contact, member_id=member_id)
    session.add(supplier)
    session.flush()

    listing = Listing(
        provider_id=supplier.id,
        title=title,
        summary=summary,
        roles=chosen,
        domain=domain,
        qualification_pipeline=qualification_pipeline,
        registration_refs=refs,
        # R-202. Draft until it has been through the disclosure gate.
        status="draft",
        # R-203. **Derived, not left empty.** This was written once as two empty lists and never revisited,
        # so `capability_evidence` and `community_presence` were permanently zero for every listing the
        # application itself created — two of R-203's three ordering inputs dead on the only write path
        # that matters, and visible in no test because the seed fixture supplies its own values.
        standing_inputs=member_standing(session, member_id),
    )
    session.add(listing)
    session.flush()
    return listing


def declare(
    session: Session,
    *,
    listing_id: str,
    kind: str,
    statement: str,
    declared_by: str,
    declared_at: datetime | None = None,
) -> Disclosure:
    """R-202. Record one disclosure against a listing.

    `kind` is free text and `none_declared` is one of its values. Nothing here checks that a declaration
    is true — that is not a thing code can do — but the record carries who said it and when, which is
    what makes it a claim somebody can be held to rather than a checkbox.
    """
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise UnknownListing(f"no listing {listing_id!r}")
    record = Disclosure(
        listing_id=listing.id,
        kind=kind,
        statement=statement,
        declared_by=declared_by,
        declared_at=declared_at or utcnow(),
    )
    session.add(record)
    session.flush()
    return record


def publish(session: Session, listing_id: str) -> Listing:
    """R-202. **The only place a listing becomes published**, and the disclosure gate is here.

    Not in a validator called on the way past: a validator is something a second write path can be
    written without. This is the write path, and it refuses a listing that has no `Disclosure` row.
    """
    listing = session.get(Listing, listing_id)
    if listing is None:
        raise UnknownListing(f"no listing {listing_id!r}")

    # Pending disclosures added in this same transaction have to be visible to the check, or the gate
    # would pass for the wrong reason on the seeding path and fail for the wrong reason everywhere else.
    session.flush()

    # **Counted with a query, not read off `listing.disclosures`.** The relationship is a cached
    # collection: a first, refused publish loads it as empty, and because the session is created with
    # `expire_on_commit=False` a disclosure added afterwards does not expire it. The second publish would
    # then still see zero and refuse a listing that HAS a disclosure — the exact sequence an applicant
    # follows, and one that showed up as an order-dependent test failure before it showed up as a bug.
    disclosure_count = session.execute(
        select(func.count()).select_from(Disclosure).where(Disclosure.listing_id == listing.id)
    ).scalar_one()

    if not disclosure_count:
        raise UndisclosedListing(
            f"R-202: listing {listing_id!r} has no disclosure record and cannot be published. A supplier "
            f"with nothing to declare records a `none_declared` disclosure — that is a positive statement "
            f"somebody made, and it is not the same as a listing nobody has been asked."
        )

    expected = required_pipeline(listing.domain)
    if listing.qualification_pipeline != expected:
        raise PipelineMismatch(
            f"R-204: listing {listing_id!r} is {listing.domain!r} supply under the "
            f"{listing.qualification_pipeline!r} pipeline; {expected!r} is the one that domain goes "
            f"through. Checked again here because publish is the last gate before a member sees it."
        )
    if listing.qualification_pipeline == "professional_registration" and not listing.registration_refs:
        raise MissingRegistration(
            f"R-204: listing {listing_id!r} is under the professional pipeline and names no registration."
        )

    # R-203. Re-derived here because publish is the visible act that puts a listing in front of members,
    # and a listing that carried its application-day standing for ever would be an ordering input frozen
    # at the moment it was least informative. The values come from `member_standing` and from nothing
    # else — see `test_standing_inputs_are_only_ever_written_from_member_standing`, which is what keeps
    # C-08 true of a field the ordering reads but the ordering functions do not compute.
    #
    # Only when the supplier is a member. A provider that is not one has no assertions and no attendances
    # in this system, and overwriting the seeded demonstration standing with two empty lists would be
    # deriving an answer from the absence of a person rather than from a person.
    supplier = session.get(Provider, listing.provider_id)
    if supplier is not None and supplier.member_id:
        listing.standing_inputs = member_standing(session, supplier.member_id)

    listing.status = "published"
    return listing


# ---------------------------------------------------------------- seeding (A41)


def _refuse_unmarked(records, group: str) -> None:
    """A41. The marker is load-bearing: an unmarked record is not written, it stops the seeding."""
    for record in records:
        if not record.get("fictional"):
            raise NotMarkedFictional(
                f"A41: seed record {group}/{record['key']!r} is not marked fictional. Seeded supply is "
                f"demonstration material and must say so in the data itself, so that a screenshot of the "
                f"Market Place cannot be mistaken for a real market."
            )


def seed(session: Session, *, member_id: str | None = None) -> dict:
    """Write the content file's providers, listings, disclosures and member offers into the store, once.

    Idempotent by key: the content `key` is the row id, so re-running adds nothing and rewrites nothing.

    **Every listing goes through `publish`.** The seeding path is not a shortcut around R-202 — it writes
    each listing as a draft, records its disclosures, and then asks `publish`, which is the same gate an
    applicant meets. A seed record with no disclosure would fail here rather than appear published.

    **Member offers are written only when a member is named.** A `MemberOffer` without a member is not a
    member offer, and inventing a member to hang one on would be seeding a person.
    """
    _refuse_unmarked(seed_providers(), "providers")
    _refuse_unmarked(seed_listings(), "listings")
    _refuse_unmarked(seed_disclosures(), "disclosures")
    _refuse_unmarked(seed_member_offers(), "member_offers")

    written: dict[str, list[str]] = {
        "providers": [], "listings": [], "disclosures": [], "member_offers": []
    }

    for record in seed_providers():
        if session.get(Provider, record["key"]) is not None:
            continue
        session.add(
            Provider(
                id=record["key"],
                display_name=record["display_name"],
                contact=record.get("contact"),
                # A41, on the row and not only in the file.
                fictional=True,
                # C-08. The seed data leaves the billing fields unset. Demonstration supply that carried a
                # fee would put a commercial signal within reach of a screenshot, whatever the code does.
                member_id=None,
            )
        )
        written["providers"].append(record["key"])

    for record in seed_listings():
        if session.get(Listing, record["key"]) is not None:
            continue
        session.add(
            Listing(
                id=record["key"],
                provider_id=record["provider_key"],
                # The authored language (A12). The sentence a member reads comes from the content record
                # in their own language — see `_entry_for_listing`.
                title=record["title"][DEFAULT_LANGUAGE],
                summary=record["summary"][DEFAULT_LANGUAGE],
                roles=list(record["roles"]),
                domain=record["domain"],
                qualification_pipeline=record["qualification_pipeline"],
                registration_refs=list(record["registration_refs"]),
                standing_inputs=dict(record["standing_inputs"]),
                status="draft",
                fictional=True,
            )
        )
        session.flush()
        for entry in record["disclosures"]:
            session.add(
                Disclosure(
                    id=entry["key"],
                    listing_id=record["key"],
                    kind=entry["kind"],
                    statement=entry["statement"][DEFAULT_LANGUAGE],
                    declared_at=datetime.fromisoformat(entry["declared_at"]),
                    declared_by=entry["declared_by"],
                )
            )
            written["disclosures"].append(entry["key"])
        publish(session, record["key"])
        written["listings"].append(record["key"])

    if member_id is not None:
        for record in seed_member_offers():
            if session.get(MemberOffer, record["key"]) is not None:
                continue
            session.add(
                MemberOffer(
                    id=record["key"],
                    member_id=member_id,
                    direction=record["direction"],
                    kind=record["kind"],
                    title=record["title"][DEFAULT_LANGUAGE],
                    body=record["body"][DEFAULT_LANGUAGE],
                    roles=list(record["roles"]),
                    active=True,
                    fictional=True,
                )
            )
            written["member_offers"].append(record["key"])

    session.flush()
    return written
