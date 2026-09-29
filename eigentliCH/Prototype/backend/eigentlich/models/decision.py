"""The Decision Record: what was decided, why, and what it touched.

**This name was taken deliberately.** The estate already had a `DecisionRecord` keyed on
`household_id` + `recommendation_id`, recording a curator releasing advice. That is a different object, and
A7 in DECISIONS.md renames it rather than letting two things share one name in one system. This `Decision`
is the member-facing record C-09 requires around every plan mutation.

**Links are relationships, not id arrays, and that is load-bearing.** The C-09 guard runs in
`before_flush`, where a newly created Position does not have an id yet. An id array could not name it; an
ORM relationship can, because it holds the object. The spec's `linked_*_ids[]` are exposed as read-only
properties over those relationships, so the API shape matches §4 without the guard losing its grip.
"""

from __future__ import annotations

from sqlalchemy import Column, Enum as SAEnum, ForeignKey, JSON, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from typing import TYPE_CHECKING

from .base import Base, Classified, DataClass, new_id, Timestamped

if TYPE_CHECKING:  # names the relationships resolve at mapper-configuration time
    from .plan import Goal, Position
    from .vault import VaultItem

AUTHORS = ("member", "curator", "system")

decision_positions = Table(
    "decision_positions",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("position_id", ForeignKey("positions.id"), primary_key=True),
)

decision_goals = Table(
    "decision_goals",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("goal_id", ForeignKey("goals.id"), primary_key=True),
)

#: C-09 reaches household composition too, because `Household` and `HouseholdMember` are `PlanMutable`.
#: Two tables rather than one polymorphic link: the guard compares object identity, and a single table with
#: a `kind` discriminator would need the service layer to know which kind it was writing — which is exactly
#: the "someone remembering" that `PlanMutable` exists to remove.
decision_households = Table(
    "decision_households",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("household_id", ForeignKey("households.id"), primary_key=True),
)

decision_household_members = Table(
    "decision_household_members",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("household_member_id", ForeignKey("household_members.id"), primary_key=True),
)

#: The five stated member facts (A127). `MemberFact` is `PlanMutable`, and `covered_plan_objects` below
#: is what the C-09 guard compares against — so without this table a canton could not be written at all,
#: not merely written unlinked. It is also what makes a change of canton visible on S-07 beside the
#: positions and goals it moves, rather than legible only from the Decision's own prose.
decision_facts = Table(
    "decision_facts",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("member_fact_id", ForeignKey("member_facts.id"), primary_key=True),
)

decision_vault_items = Table(
    "decision_vault_items",
    Base.metadata,
    Column("decision_id", ForeignKey("decisions.id"), primary_key=True),
    Column("vault_item_id", ForeignKey("vault_items.id"), primary_key=True),
)


class DecisionImmutable(Exception):
    """Raised when something tries to change or remove a Decision. R-040, R-162."""


class Decision(Base, Classified, Timestamped):
    """Append-only. A correction is a new record pointing at the one it corrects (R-040).

    The UI offers "record a correction", never "edit" (R-162), and this model is why that is a statement
    about the data rather than about the buttons.
    """

    __tablename__ = "decisions"
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    #: Nullable so R-231's erasure can null it. The row itself cannot be deleted (R-040 / C-10), so
    #: "delete my data" is carried out by removing the member from it — see `services/erasure.py`.
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)

    author: Mapped[str] = mapped_column(SAEnum(*AUTHORS, name="decision_author"), nullable=False)
    author_ref: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        doc="Which curator, where the author is a curator. R-161, R-212 — a decision attributed to "
        "'a curator' is not attributed.",
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    options_considered: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    choice: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    curator_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("curator_sessions.id"), nullable=True, index=True
    )

    corrects_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id"),
        nullable=True,
        index=True,
        doc="R-040. Set on the NEW record: a correction references the prior one, and the prior one is "
        "left exactly as it was written.",
    )
    corrects: Mapped["Decision | None"] = relationship(remote_side=[id])

    linked_positions: Mapped[list["Position"]] = relationship(secondary=decision_positions)
    linked_goals: Mapped[list["Goal"]] = relationship(secondary=decision_goals)
    linked_vault_items: Mapped[list["VaultItem"]] = relationship(secondary=decision_vault_items)
    linked_households: Mapped[list["Household"]] = relationship(  # noqa: F821 - registry-resolved
        secondary=decision_households
    )
    linked_household_members: Mapped[list["HouseholdMember"]] = relationship(  # noqa: F821
        secondary=decision_household_members
    )
    linked_facts: Mapped[list["MemberFact"]] = relationship(  # noqa: F821 - registry-resolved
        secondary=decision_facts
    )

    # -- the §4 shape, read-only over the relationships above ----------------------------------------

    @property
    def linked_position_ids(self) -> list[str]:
        return [p.id for p in self.linked_positions]

    @property
    def linked_goal_ids(self) -> list[str]:
        return [g.id for g in self.linked_goals]

    @property
    def linked_vault_item_ids(self) -> list[str]:
        return [v.id for v in self.linked_vault_items]

    @property
    def linked_household_ids(self) -> list[str]:
        return [h.id for h in self.linked_households]

    @property
    def linked_household_member_ids(self) -> list[str]:
        return [h.id for h in self.linked_household_members]

    @property
    def linked_fact_ids(self) -> list[str]:
        return [f.id for f in self.linked_facts]

    def covered_plan_objects(self) -> set:
        """Every plan object this decision accounts for. What the C-09 guard checks against."""
        return {
            *self.linked_positions,
            *self.linked_goals,
            *self.linked_households,
            *self.linked_household_members,
            *self.linked_facts,
        }
