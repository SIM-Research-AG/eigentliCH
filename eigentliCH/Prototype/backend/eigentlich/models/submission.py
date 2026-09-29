"""Submission — the intake file exactly as the member handed it over, kept before anything is mapped.

===========================================================================================================
WHY THE WHOLE FILE AND NOT ONLY THE PARTS THAT FIT
===========================================================================================================

`client/intake.html` asks 102 questions and the loader has a home for about a third of them. Until now the
rest were read, reported and dropped: `tools/load_submission.py` printed them under `absent`, `deferred`
and `dropped`, and nothing was written. That is defensible while the instrument is small and indefensible
now, because the member typed an answer and was told nothing, and the answer has to be asked for a second
time when the calculation that needs it finally exists.

The owner's ruling of 6 September 2026: **store the submission verbatim, then map.** An answer with no home
is still there when the home is built.

**This is a transcript, not a plan.** Like `OnboardingAnswer` and unlike `MemberFact`, it records what was
said at a moment rather than what currently stands. So it is NOT `PlanMutable`, writing one takes no
Decision, and nothing in a Befund may read it: a finding rests on positions, goals and facts, which are
the mapped, correctable, dated record. A submission is the evidence those were derived from.

That distinction is the whole safety argument for keeping unmapped answers. The blob is inert. It is not
an input to anything, so an answer sitting in it cannot quietly reach a member's plan without somebody
building the mapping — which is the act that also decides what the answer means.

===========================================================================================================
CLASSIFICATION
===========================================================================================================

**K3, and higher than any single field in it.** The file mixes a canton (K1) with a pension balance (K2)
with a self-assessment of health and a free-text question about what worries the member (K3). C-04's
filter drops by field name, and the field here is called `payload` — a name that tells the filter nothing
about the health answer inside it. Classifying the container at the highest class anything in it can carry
is the only reading that does not leak.

**A consequence worth stating plainly:** an export hands the member this file back, and an erasure destroys
it. Both follow from `Submission` being in `DELETED_IN_ERASURE_ORDER`, which is what R-154 and R-231 are
read from. A blob the schema could not explain would have been the reason not to store it; a blob that
erasure reaches and export returns is a record the member controls.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Classified, DataClass, DateTime, Timestamped, new_id, utcnow


class Submission(Base, Classified, Timestamped):
    """One intake file, as received."""

    __tablename__ = "submissions"
    __data_class__ = DataClass.K3

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    #: The instrument that produced it — `intake@1.1`, `onb@0.1.3`. **Never inferred.** A file whose shape
    #: is guessed is a file whose fields are guessed, and two instruments have used the same key for
    #: different things before.
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)

    #: Where it came from: `intake.html`, `onboarding-chat`, a curator's transcription.
    source: Mapped[str] = mapped_column(String(60), nullable=False)

    #: The date the member says they filled it in, which is not the date it arrived. A file completed in
    #: March and sent in September describes March, and a finding dated from the wrong one is wrong.
    collected_on: Mapped[str | None] = mapped_column(String(10), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    #: The file. Whole, unaltered, keys and all.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    #: Hex digest of the payload as received. Two purposes, and the second is the reason it is stored
    #: rather than computed: loading the same file twice is an accident that should be visible, and a
    #: member asking "is this what I sent you" is entitled to an answer that does not depend on the
    #: application having serialised it back the same way.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The shared code from the intake's first section, where the member gave one. Two files carrying the
    #: same code are one household waiting to be joined — see `services/household_link.py`. Nullable and
    #: unvalidated: it is a word a member chose, not an identifier this application issued.
    household_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    #: What the mapping made of it, written after the load runs: which keys became positions, goals or
    #: facts, and which were carried without a home. A report and not a plan — it exists so that when a
    #: field gains a home later, the submissions that already carry it can be found.
    mapping_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: Free text from whoever loaded it. A curator transcribing a paper form leaves the provenance here.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Not unique on `content_hash` alone: two members of one household may legitimately submit
        # identical files if neither filled anything in yet, and refusing the second would be refusing a
        # real person. Unique per member, which is the case that means "loaded twice by mistake".
        Index("uq_submission_member_hash", "member_id", "content_hash", unique=True),
        # `household_code` declares `index=True` on the column itself; naming it again here created the
        # same index twice and SQLite refused the second.
    )
