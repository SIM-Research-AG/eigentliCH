"""Member and Consent.

The age floor (R-100, NG-05) is enforced here as a database CHECK as well as in the service layer, because
R-100's acceptance test was written as "registration with a stated age of 24 is refused by the API even if
the client is bypassed". The floor is now 18 (A50), so the test asserts the same thing one below whatever
`MINIMUM_AGE` says rather than the literal 24 — the mechanism is the point, not the number. A validator in a request model is bypassed by anything that is not that request model;
a CHECK constraint is bypassed by nothing that speaks SQL.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..consent import UnregisteredPurpose, is_registered
from .base import Base, Classified, DataClass, DateTime, new_id, Timestamped

#: The age floor. Named once so the API, the CHECK constraint and the test all read the same number.
#:
#: **18, lowered from 25 on 30 August 2026** at the owner's instruction (A50). The specification's NG-05
#: set 25 and gave its reason as "no minor-consent flows" — so the floor moved to the age at which that
#: reason stops applying, rather than being removed. Everyone here is an adult in Swiss law, so NG-05's
#: actual promise is kept while its number is not.
#:
#: Going below 18 is not a config change: it makes parental or guardian consent a real requirement, and
#: those flows do not exist. Whoever lowers this further owes them first.
MINIMUM_AGE = 18


class Member(Base, Classified, Timestamped):
    __tablename__ = "members"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)

    age_at_registration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="NG-05, R-100. Stored as the age stated at registration rather than a birth date: the product "
        "needs the floor to have been met, not a birthday. Holding less is the cheaper compliance position.",
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="de-CH")

    stage_hint: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        doc="Content routing only (S-05). Never rendered as a position on a scale, never compared to age, "
        "and never a source of progress — R-006, R-140.",
    )

    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="S-01. Set once, in the same transaction that writes the first Position and Goal. Explicit "
        "state rather than inferred from 'does a position exist', because inferring it made `complete` "
        "non-idempotent: a double-click produced two identical positions and two Decisions, and the "
        "second Decision could not be deleted afterwards because R-040 makes them append-only.",
    )

    consents: Mapped[list["Consent"]] = relationship(
        back_populates="member", cascade="all, delete-orphan", order_by="Consent.granted_at"
    )

    __table_args__ = (
        CheckConstraint(
            f"age_at_registration >= {MINIMUM_AGE}",
            name="ck_members_age_floor",
        ),
    )


class Consent(Base, Classified, Timestamped):
    """R-103: consent is a versioned, timestamped record, not a checkbox boolean.

    Withdrawal sets `withdrawn_at` on the row — the grant itself is never deleted, because "did they ever
    consent, and to what version" is a question that outlives the consent.

    **`withdrawn_at` is a record and not a gate.** Nothing in this application reads it to decide
    what a member may do; it is written by `services/registration.withdraw_consent`, rendered by R-230's
    history and by the withdrawal route, and read nowhere else. That is deliberate as of 1 September 2026:
    the owner kept the behaviour and corrected the member-facing wording in `consent.py`, which had claimed
    that withdrawing stopped the processing and closed the account.

    **`purpose` is a closed set** as of 31 August 2026. It was free text with no registry, which is why
    `services/derive.py` could not build R-152's consent item and why R-230's history could not be read
    by code: a purpose nobody guaranteed the spelling of is a consent nobody can later reason about.
    `consent.py` holds the registry and the argument, including why this is a validator and not a CHECK
    constraint.

    **The closed set is every registered purpose, of either kind (A97).** `entscheidprotokoll` is published
    as a *notice* now — the member is told rather than asked — but rows naming it were written on 30 August
    while it was a consent, and they are real records of what somebody agreed to. A validator refusing the
    key would leave those rows readable, because `@validates` does not fire on load, and unwritable: no
    re-save, no ORM copy, and no test able to construct the historical row that proves R-230 still shows
    it. So the guarantee that no *new* row names a notice lives at the one place rows are written,
    `services/registration.register_member`, and at the capture point in front of it.
    """

    __tablename__ = "consents"
    __data_class__ = DataClass.K1

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False, index=True)

    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    document_version: Mapped[str] = mapped_column(
        String(40), nullable=False, doc="Which version of the wording was agreed to. R-103, R-230."
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    member: Mapped[Member] = relationship(back_populates="consents")

    @validates("purpose")
    def _purpose_is_registered(self, _key: str, value: object) -> str:
        """R-103. The registry is enforced on the way in, for every ORM write in the application.

        The same arrangement as `ActionItem`'s option-key validator: the check sits on the attribute, so
        it holds for a row built in a REPL as readily as for one built by the registration route. The
        registry lives in `consent.py` rather than here, because `services/settings.py` and the statement
        route read the same list and two lists that must agree are the defect A73 and A91 both are.
        """
        if not is_registered(value):
            raise UnregisteredPurpose(value)
        return str(value)
