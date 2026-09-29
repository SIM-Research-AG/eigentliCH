"""Household and HouseholdMember — the unit the planner actually solves for.

Until this file existed the build was single-subject: `Position.member_id`, `Goal.member_id`, and nowhere
to put "we are two". Journey & Design page 1 is explicit that this is the wrong shape —

    "the planner is built for a household of members from the first line — one or two in the first build,
    more later without a rewrite. The single-member case is not a lesser mode; it is the same model with
    one member in it."

— and `tools/load_submission.py` had already recorded the consequence from the other end: `children_count`
sat in `NO_FIELD_HOLDS_IT` with the reason "no household model in this build", so a real submission's
answer was read, reported and dropped.

===========================================================================================================
WHY COMPOSITION CARRIES A DATE AND ALMOST NOTHING ELSE DOES
===========================================================================================================

Household composition is the one load-bearing input the system cannot detect for itself. It sets the AHV
path, the tax path, goal ownership and the human role vector, and nothing — not aggregation, not a
document, not a re-solve — reveals that it changed. Everything else in the plan is either stated fresh or
visibly stale; this is stated once and then silently assumed forever.

So `composition_as_of` is not a convenience timestamp beside `created_at`. `created_at` is when the row was
written; `composition_as_of` is the date the member says the composition describes, and those differ every
time a curator records a session held last week. The Befund stamps the second one, never the first.

The twelve-month validity horizon that runs off this date is **not in this file and must not be put here**.
A horizon is an assumption under C-02, it has an owner and a publication date, and `models/currency.py`
holds the record that publishes it. A literal `12` in a model file is exactly the defect C-02 exists to
stop, and it would be invisible within a week.

===========================================================================================================
CLOSING, NOT DELETING
===========================================================================================================

`closed_on` and `succeeds_household_id` are the whole of the separation mechanism at the schema level.
Journey & Design page 3 makes separation a data-separation rule rather than a UX one, and the reasoning is
worth keeping next to the columns rather than in a service:

  * The household record is **closed, not deleted**, so every plan version created while it was open stays
    attached to something that still exists. Deleting would break the versioning promise for exactly the
    members who most need it — a member in a separation is the one who most needs to be able to say what
    was decided in 2027 and why.
  * Each member gets a **new single-member household** from the closing date forward. `succeeds_household_id`
    is how the new one names the old one. It is a plain self-referential key rather than a permissions
    model over one live shared record, because copy-and-freeze decouples the two plans in the data and
    leaves no standing leak to get wrong later.

Neither column implies the other is set. A household closed with no successors is a household whose members
left the product; a successor with no closed predecessor is impossible and the CHECK below says so.

===========================================================================================================
`kind` IS A CLOSED SET, AND DEPENDANTS CANNOT OWN A GOAL
===========================================================================================================

An `adult` is a household member who can own a goal, be named in a division, and hold their own member
record. A `dependant` affects the tax path and the household's standard of living and owns nothing. The
distinction is not about age — a 19-year-old in education is a dependant if the household says so — which
is why it is stated by the member rather than derived from a birth year the build does not hold.

`member_id` is nullable on purpose: a partner who has not signed up is still a member of the household, and
refusing to model them until they register would make the couple case wait on an invitation flow. What that
costs is stated at `HouseholdMember.member_id`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum as SAEnum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, new_id, Timestamped
from .plan import PlanMutable

#: What a household member is, for the purposes of the plan. Closed, and read by `services/household.py`
#: and by the goal-ownership guard rather than re-spelled at either site.
#:
#: `adult` — can own a goal, can be named in a division, may hold a Member record.
#: `dependant` — affects the tax path and the standard of living; owns nothing and is never a goal owner.
HOUSEHOLD_MEMBER_KINDS = ("adult", "dependant")
ADULT, DEPENDANT = HOUSEHOLD_MEMBER_KINDS

#: Who stated the composition. Journey & Design page 1 gives the two paths to a plan equal standing —
#: guided and self-directed — and item 3 of the update script requires the same intake to be drivable by a
#: curator on the member's behalf, producing the same versioned plan: "one code path, two initiators —
#: record which one". This is that record. It is not a permission and nothing branches on it.
STATED_BY = ("member", "curator")

_KIND_SQL = ", ".join(f"'{kind}'" for kind in HOUSEHOLD_MEMBER_KINDS)


class Household(Base, Classified, Timestamped, PlanMutable):
    """One household, open or closed. The single-member case is this model with one row beside it."""

    __tablename__ = "households"
    #: K2. Composition is substantive personal material that feeds the plan — the same class as the
    #: positions and goals derived from it, and above `Member`'s K1, which holds only a display name and a
    #: locale.
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)

    composition_as_of: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="The date the stated composition describes — NOT the date the row was written, which is "
        "`created_at`. A curator recording last week's session stamps last week. Every plan version reads "
        "this as its `household_as_of`, and the currency horizon runs from it.",
    )
    stated_by: Mapped[str] = mapped_column(
        SAEnum(*STATED_BY, name="household_stated_by"),
        nullable=False,
        doc="Which of the two initiators recorded this composition. A record, not a permission.",
    )

    closed_on: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
        doc="Set when the household closes. The row is never deleted: every plan version created while it "
        "was open stays attached to it.",
    )
    succeeds_household_id: Mapped[str | None] = mapped_column(
        ForeignKey("households.id"),
        nullable=True,
        index=True,
        doc="The closed household this one was created out of, on a separation. Null for a household that "
        "was not created by a closing.",
    )

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        order_by="HouseholdMember.created_at, HouseholdMember.id",
    )

    __table_args__ = (
        # A household cannot succeed itself. Cheap, and the shape a copy-paste in a split service produces.
        CheckConstraint(
            "succeeds_household_id IS NULL OR succeeds_household_id <> id",
            name="ck_households_no_self_succession",
        ),
    )


class HouseholdMember(Base, Classified, Timestamped, PlanMutable):
    """A person in a household. May or may not have an account.

    `left_on` is here for the same reason `closed_on` is on `Household`: a member who left in 2029 was in
    the household when the 2027 plan was solved, and a row that disappears takes that fact with it.
    """

    __tablename__ = "household_members"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        ForeignKey("households.id"), nullable=False, index=True
    )

    member_id: Mapped[str | None] = mapped_column(
        ForeignKey("members.id"),
        nullable=True,
        index=True,
        doc="The account, where there is one. NULLABLE on purpose: a partner who has not signed up is "
        "still in the household, and making the couple case wait on an invitation flow would mean the "
        "planner could not model the households it exists for. What it costs is that a goal owned by an "
        "account-less adult has an owner the product cannot show a plan to — which is correct, and is why "
        "`services/household.py` refuses to seed a successor household for one on a closing.",
    )

    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="What the member calls this person. Member-authored text: quoted, never interpolated into a "
        "composed sentence — see `services/befund.Fact.quoted` for why.",
    )
    kind: Mapped[str] = mapped_column(
        SAEnum(*HOUSEHOLD_MEMBER_KINDS, name="household_member_kind"), nullable=False
    )

    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    left_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    household: Mapped[Household] = relationship(back_populates="members")

    __table_args__ = (
        # One account appears at most once in one household. Two rows for the same person is a data error
        # that would double their income in every aggregate downstream.
        UniqueConstraint("household_id", "member_id", name="uq_household_members_account_once"),
        CheckConstraint(f"kind IN ({_KIND_SQL})", name="ck_household_members_kind"),
        CheckConstraint(
            "left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on",
            name="ck_household_members_left_after_joined",
        ),
    )
