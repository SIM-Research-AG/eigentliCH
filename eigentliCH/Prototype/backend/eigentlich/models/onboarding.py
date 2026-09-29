"""OnboardingAnswer — one row per question, which is what R-101 actually asks for.

"Must be resumable. Partial state persists **per question**, not per session."

That wording rules out the obvious implementation. A session blob written on navigate would be resumable
in the ordinary sense and would still fail this: a member who answers question 9 and closes the tab before
the blob is flushed loses nine answers, and the acceptance test — "a member who abandons at question n and
returns resumes at n" — is about exactly that member.

So an answer is a row, written when it is given. There is nothing to flush and nothing to lose.

**Not a plan mutation, and therefore not under C-09.** An answer is what the member said, not a change to
their plan. The Position and Goal are written at the end of onboarding, in one transaction with one
Decision — see `services/onboarding.py`. Recording an intermediate answer as a plan decision would fill
the Decisions screen (S-07) with keystrokes and bury the decisions that matter.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped, utcnow


class OnboardingAnswer(Base, Classified, Timestamped):
    __tablename__ = "onboarding_answers"
    #: K2. The answers describe a member's employment and money, which is the same class as the Position
    #: they become — classifying the transport lower than the destination would be a hole in C-04.
    __data_class__ = DataClass.K2

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    question_key: Mapped[str] = mapped_column(String(80), nullable=False)
    #: JSON rather than text: a question may answer with a number, a string or a list, and coercing all
    #: three into text is how a "42" that meant hours becomes a "42" that means nothing.
    value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)

    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    #: Which version of the question set was being answered. A member who resumes after the set changed
    #: must not have their answer silently re-pointed at a question that now asks something else.
    question_set_version: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        # One answer per question per member. Re-answering updates the row rather than appending, because
        # this is a form in progress, not a record of what was decided — that is what Decision is for.
        UniqueConstraint("member_id", "question_key", name="uq_onboarding_answer"),
    )
