"""PlanVersion — the numbered baseline this build has been missing, and what a plan assumed when it was made.

Two separate holes close here and they turn out to be one object.

**The engines asked for it by name.** `services/engine_inputs` leaves the Scenario Generator's
`base_snapshot_id` absent with the reason *"prototype2 has no Snapshot. The plan is Position and Goal with
a Decision behind every mutation (C-09), which is a history rather than a numbered baseline."* The Befund
reports that absence to the member as `numbered_baseline`. A history tells you what changed; it does not
give you a thing to re-simulate against, because a `Decision` carries a question and a choice in prose and
not the state that resulted.

**Item 6 asked for the stamp.** *"Every plan version carries a `household_as_of` stamp, so the app can
state 'this plan assumes a two-member household as of March 2027.'"* A version with no record of the
household it assumed is a figure whose most load-bearing input is unrecoverable — and household composition
is precisely the input nothing in the system can detect changed.

===========================================================================================================
A VERSION IS FROZEN INPUTS, NOT A FROZEN RENDERING
===========================================================================================================

`inputs` holds the member's positions and goals as they stood, at the granularity the engines read them —
role, capital type, magnitude and unit, stock kind, liquidity, and for a goal its name, target, date, five
parameters and owners. It does **not** hold computed figures, an illustration, a chart or a rendered
sentence.

That is the difference between a baseline and a screenshot. A rate published later has to be applicable to
an old baseline, or "you are eight months behind the plan you made in March 2027" cannot be computed
without re-deriving the whole plan; and a frozen *output* would be a figure whose assumption set nobody can
trace, which C-02 exists to prevent. So the version freezes what the member stated and nothing that was
concluded from it.

===========================================================================================================
PROPOSED, STANDING, SUPERSEDED — AND WHY A RE-SOLVE CANNOT SILENTLY WIN
===========================================================================================================

Journey & Design page 1: *"A re-solve is always proposed against the standing plan and never silently
replaces it — adopting it is the member's act."* So a new version arrives `proposed`, and only an explicit
adoption makes it `standing`. There is at most one standing version per member, and the previous one
becomes `superseded` with `superseded_by_id` naming its replacement.

A `proposed` version that is never adopted stays `proposed` forever. It is not cleaned up, not expired and
not auto-adopted after a while: an auto-adopting proposal is a silent replacement with a delay, which is the
thing the sentence above forbids.

**Not `PlanMutable`.** Writing a version records the plan; it does not change it — the same reasoning
`EngineRun` states, and for the same guard. `positions` and `goals` are untouched by anything in this file.
**Adoption is different**, and `services/version.py` writes a Decision for it explicitly rather than
relying on the marker: adopting is the member's act with a consequence, page 1 says so, and item 2 adds
that a curator's confirmation does not carry forward to a re-solved plan — which is only checkable if
adoption is a recorded event with an author.

**K2, and nothing raised above it.** `inputs` can carry the member's plan, which is the class of the rows
it was built from. Deliberately not K3, for the reason `run.py` sets out at length: a `data_class` override
feeds `top_class_field_names()`, which the C-04 log filter drops **by field name across the whole
application**, so marking `inputs` here would redact the word `inputs=` out of every log line the server
writes.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped

#: The three states a version can be in. Named once so the service, the API and the tests cannot drift —
#: the same reasoning as `RUN_STATUSES` and `FIVE_PARAMETERS`.
PROPOSED = "proposed"
STANDING = "standing"
SUPERSEDED = "superseded"
VERSION_STATUSES = (PROPOSED, STANDING, SUPERSEDED)

_STATUS_SQL = ", ".join(f"'{one}'" for one in VERSION_STATUSES)


class PlanVersion(Base, Classified, Timestamped):
    """One numbered baseline of one member's plan, and what it assumed about their household."""

    __tablename__ = "plan_versions"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="The baseline's number, per member, from 1. This is the `base_snapshot_id` the Scenario "
        "Generator asks for and the `numbered_baseline` the Befund reports as absent. Sequential per "
        "member rather than global: 'the plan you made in March 2027' is version 3 of theirs, and a "
        "global counter would tell them how many plans other people have made.",
    )

    status: Mapped[str] = mapped_column(
        SAEnum(*VERSION_STATUSES, name="plan_version_status"),
        nullable=False,
        default=PROPOSED,
        doc="Arrives `proposed`. Only an explicit adoption makes it `standing` — page 1: a re-solve never "
        "silently replaces the standing plan.",
    )

    # -- what it assumed about the household ---------------------------------------------------------

    household_id: Mapped[str | None] = mapped_column(
        ForeignKey("households.id"),
        nullable=True,
        index=True,
        doc="The household this version was solved for. NULLABLE because a member may have a plan before "
        "they state a composition — and a version that records `None` here is telling the truth about "
        "what it knew, which is more useful than refusing to exist.",
    )
    household_as_of: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        doc="Item 6's stamp: the `composition_as_of` of the household at the moment this version was "
        "made. COPIED, not joined. If it were read through `household_id` at render time, a member who "
        "restated their composition would silently rewrite what every past version assumed — which is the "
        "exact class of quiet wrongness item 6 exists to close. Null if and only if `household_id` is.",
    )

    # -- the frozen inputs ---------------------------------------------------------------------------

    inputs: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="The member's positions and goals as they stood. Stated inputs only — no computed figure, no "
        "illustration, no rendered sentence. See the module docstring on why a baseline is not a "
        "screenshot.",
    )

    # -- adoption and succession ---------------------------------------------------------------------

    adopted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the member adopted it. Set if and only if the version ever became standing, and NOT "
        "cleared when it is later superseded: 'this was the plan from March to November 2027' needs both "
        "ends, and a cleared field would lose the near one.",
    )
    adoption_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id"),
        nullable=True,
        doc="The Decision recording the adoption, and therefore its author. Item 2 requires that a "
        "curator's confirmation does not carry forward to a re-solved plan; that is only checkable if "
        "each adoption names who made it.",
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_versions.id"),
        nullable=True,
        doc="The version that replaced this one as standing.",
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Why this version exists: the first plan, an annual review, a life event, a regime shift, a "
        "what-if the member adopted. Free text and never parsed — the planning loop's five causes are "
        "already a closed set in `services/know.py`, and a second copy here would be a second list to "
        "keep in step.",
    )

    superseded_by: Mapped["PlanVersion | None"] = relationship(
        remote_side="PlanVersion.id", foreign_keys=[superseded_by_id]
    )

    __table_args__ = (
        UniqueConstraint("member_id", "number", name="uq_plan_versions_member_number"),
        # At most one standing version per member, enforced by the database rather than by the service.
        # A PARTIAL unique index is the only construction that expresses "unique among the rows where
        # status = 'standing'" — a plain unique index on (member_id, status) would also forbid a member
        # having two superseded versions, which is the normal case. SQLite has supported partial indexes
        # since 3.8, and without this, two standing versions is one mis-ordered service call away with no
        # symptom until a member is shown two plans.
        Index(
            "uq_plan_versions_one_standing",
            "member_id",
            unique=True,
            sqlite_where=text(f"status = '{STANDING}'"),
        ),
        Index("ix_plan_versions_status", "member_id", "status"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="ck_plan_versions_status"),
        CheckConstraint("number >= 1", name="ck_plan_versions_number_positive"),
        # Item 6's stamp is all-or-nothing. A version naming a household but not what it assumed of it is
        # the defect this column exists to prevent, wearing a NULL.
        CheckConstraint(
            "(household_id IS NULL) = (household_as_of IS NULL)",
            name="ck_plan_versions_household_stamp_complete",
        ),
        # A version that was never adopted cannot carry an adoption Decision, and one that was must.
        CheckConstraint(
            "(adopted_at IS NULL) = (adoption_decision_id IS NULL)",
            name="ck_plan_versions_adoption_complete",
        ),
        # Only a superseded version names a successor, and every superseded one does.
        CheckConstraint(
            f"(status = '{SUPERSEDED}') = (superseded_by_id IS NOT NULL)",
            name="ck_plan_versions_superseded_names_successor",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_plan_versions_no_self_succession",
        ),
    )


__all__ = [
    "PROPOSED",
    "STANDING",
    "SUPERSEDED",
    "VERSION_STATUSES",
    "PlanVersion",
]
