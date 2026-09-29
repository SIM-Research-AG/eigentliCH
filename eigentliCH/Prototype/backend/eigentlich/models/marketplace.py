"""Listing, Provider and Disclosure — phase 7's tables. C-08 is the constraint that shapes them.

**"Market Place ordering cannot be bought."** The enforcement is structural rather than procedural: the
fee fields live on `Provider`, and the ranking function is handed `Listing` rows. There is no relationship
from a listing to its provider's billing, so a ranking function cannot reach a fee even by accident — it
would have to add a query, which is a visible act rather than an oversight.

**Disclosures are a table, not a column.** R-202: "a listing with no disclosure record cannot be
published". A nullable text field would let a listing be published with an empty one; a required
relationship with an explicit `none_declared` row makes "we have no economic relationships" a positive
statement someone made rather than a field nobody filled in.

**Two qualification pipelines that are not interchangeable** (R-204). A listing declares which one it is
under, and the two carry different evidence: capability assertions for financial supply, registration
references for health and education.

**What the CHECK actually does, corrected 30 August 2026.** It ties *domain to pipeline* and nothing more:
financial must be `capability`, health and education must be `professional_registration`. An earlier
version of this docstring claimed it also kept `registration_refs` empty under the capability pipeline. It
does not, and saying so was worse than saying nothing — a reader trusting it would have skipped the check
that matters. That rule is enforced in `services/marketplace.py`, which is the honest place for it: it is a
statement about evidence rather than about shape, and SQLite cannot express "this JSON array is empty"
without a trigger. Caught by the phase 7 agent reading the model rather than the comment.

**R-202 is enforced here as well as in `publish`, since 1 September 2026.** `services/marketplace.py`
says of `publish` that it is the write path rather than "a validator called on the way past: a validator
is something a second write path can be written without". That is the right instinct and it was one
enforcement point, not two. An audit constructed `Listing(status="published")` with zero disclosures
through the ORM; it committed, and `browse` served it with `disclosures: []` — the promise that "every
listing displays its disclosures" broken by a row nobody had been asked. The `before_flush` guard at the
foot of this module is the second point, and it is at storage, where a write that skipped the service
still has to pass. `UndisclosedListing` is defined here so both points raise the *same* exception:
`services/marketplace.py` imports it rather than declaring one of its own, because two exception classes
for one rule is how two enforcement points come to mean different things.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped
from .plan import ROLES


class UndisclosedListing(Exception):
    """R-202. A listing with no disclosure record cannot be published.

    Raised by `services.marketplace.publish`, which is the only place `status` becomes `published` on the
    way in, and by this module's `before_flush` guard, which is what makes that true of a write that never
    went near the service. A listing that has nothing to declare says so with a `none_declared` disclosure;
    that is a positive statement someone made, and it is not the same thing as a listing nobody has asked.
    """

DOMAINS = ("financial", "health", "education")

#: R-204. Capability-assessed for financial supply; professional registration for health and education.
#: Not interchangeable, and the CHECK below is what makes that structural.
PIPELINES = ("capability", "professional_registration")

LISTING_STATUS = ("draft", "published", "withdrawn")


class Provider(Base, Classified, Timestamped):
    """Who supplies. Fee fields live HERE and nowhere a ranking function is handed.

    C-08 permits fee fields to exist for billing and forbids the ranking function from reading them. That
    is a hard promise to keep if the fee sits on the row being ranked, so it does not.
    """

    __tablename__ = "providers"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(320), nullable=True)

    #: A member who completed the ladder and now supplies. §1: "supply comes partly from members who
    #: complete the ladder". Nullable — not every provider is a member.
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)

    #: A41. Seeded demonstration data is marked in the data itself, so a screenshot cannot be mistaken
    #: for real supply.
    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- billing. C-08: these exist, and the ranking function must not be able to read them. ---------
    billing_plan: Mapped[str | None] = mapped_column(String(40), nullable=True)
    billing_fee_chf: Mapped[float | None] = mapped_column(Float, nullable=True)

    listings: Mapped[list["Listing"]] = relationship(back_populates="provider")


class Listing(Base, Classified, Timestamped):
    __tablename__ = "listings"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: R-200. Indexed by the four roles, not by profession. A provider may appear under more than one.
    roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    domain: Mapped[str] = mapped_column(SAEnum(*DOMAINS, name="listing_domain"), nullable=False)

    qualification_pipeline: Mapped[str] = mapped_column(
        SAEnum(*PIPELINES, name="qualification_pipeline"), nullable=False
    )
    #: For the professional pipeline. Empty for the capability pipeline, and the CHECK enforces it.
    registration_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    status: Mapped[str] = mapped_column(
        SAEnum(*LISTING_STATUS, name="listing_status"), nullable=False, default="draft"
    )

    #: R-203. Ranking inputs: role match, capability evidence, community presence. Nothing commercial.
    standing_inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    provider: Mapped[Provider] = relationship(back_populates="listings")
    disclosures: Mapped[list["Disclosure"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # R-204. Health and education go through professional registration; financial supply through
        # capability assessment. Mixing them is what this prevents.
        CheckConstraint(
            "(domain = 'financial' AND qualification_pipeline = 'capability') OR "
            "(domain IN ('health', 'education') AND qualification_pipeline = 'professional_registration')",
            name="ck_listings_pipeline_matches_domain",
        ),
    )


class Disclosure(Base, Classified, Timestamped):
    """R-202. Every listing displays its disclosures, and one with no record cannot be published.

    `none_declared` is a KIND, not an absence. "We have no economic relationships to declare" is a claim
    somebody made and can be held to; an empty column is nobody saying anything.
    """

    __tablename__ = "disclosures"
    __data_class__ = DataClass.K0

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    declared_by: Mapped[str] = mapped_column(String(120), nullable=False)

    listing: Mapped[Listing] = relationship(back_populates="disclosures")


class MemberOffer(Base, Classified, Timestamped):
    """R-205. Member offers and searches sit ALONGSIDE provider listings, not beneath them.

    Co-investment, succession, property, skills and services. A separate table because a member offering
    to co-invest is not a provider with a service, and flattening the two would make one of them look like
    a lesser version of the other.
    """

    __tablename__ = "member_offers"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    direction: Mapped[str] = mapped_column(
        SAEnum("offer", "search", name="offer_direction"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


@event.listens_for(Session, "before_flush")
def _refuse_to_publish_without_a_disclosure(
    session: Session, _flush_context: object, _instances: object
) -> None:
    """R-202 at storage. See this module's docstring for what got through before it was here.

    Only listings being written in this flush are examined — new rows, and rows whose `status` is actually
    changing — so a session that touches an unrelated column on a long-published listing pays nothing and
    a listing published before this guard existed is not retroactively refused mid-transaction. R-202 is
    about the act of publishing.

    **Disclosures pending in this same flush count.** `publish` flushes before it checks, so it sees them
    in the table, but a caller that adds a listing and its disclosure together and commits once is doing
    nothing wrong, and refusing that would push people towards the raw writes this guard exists to catch.

    The count is read on the session's own connection rather than through the ORM. A `session.execute` or
    a touch of `listing.disclosures` inside `before_flush` triggers autoflush, and autoflush inside a
    before_flush handler is a recursion, not a query.
    """
    candidates = [obj for obj in session.new if isinstance(obj, Listing)]
    for obj in session.dirty:
        if not isinstance(obj, Listing):
            continue
        history = inspect(obj).attrs.status.history
        if history.has_changes():
            candidates.append(obj)

    if not candidates:
        return

    pending = {obj.listing_id for obj in session.new if isinstance(obj, Disclosure)}
    connection = session.connection()
    for listing in candidates:
        if listing.status != "published":
            continue
        if listing.id is None:
            # A row whose key has not been assigned yet — column defaults are applied at INSERT, which is
            # after this handler runs — cannot have a stored disclosure pointing at it. Only one attached
            # in this same flush can, and that one is on the relationship. Reading it emits no SQL for a
            # pending object.
            declared = bool(listing.disclosures)
        elif listing.id in pending:
            declared = True
        else:
            declared = bool(
                connection.execute(
                    select(func.count())
                    .select_from(Disclosure.__table__)
                    .where(Disclosure.__table__.c.listing_id == listing.id)
                ).scalar_one()
            )
        if not declared:
            raise UndisclosedListing(
                f"R-202: listing {listing.id!r} was written with status 'published' and has no disclosure "
                f"record. Every listing displays its disclosures, so a published listing with none is a "
                f"promise the Market Place cannot keep. A supplier with nothing to declare records a "
                f"`none_declared` disclosure — that is a positive statement somebody made, and it is not "
                f"the same as a listing nobody has been asked. `services.marketplace.publish` is the way "
                f"in; this is the same gate, for a write that did not use it."
            )
