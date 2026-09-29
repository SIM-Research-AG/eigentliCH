"""Registration and the age floor (R-100, NG-05).

R-100 as written: "Age floor 25 enforced server-side, not only in the form", with an acceptance test that a
stated age of 24 is refused "even if the client is bypassed". **The number is now 18** — A50, on the
owner's instruction, so that eigentliCH can serve younger people; the floor is `models.MINIMUM_AGE` and this
module has never held a literal. What R-100 is actually about is the refusal being server-side, and that is
unchanged: the check lives here and again as `ck_members_age_floor` on the table. A request-model validator
would also catch it, and would also be the only one of the three that a different code path can walk past.

The quoted sentence is left in place rather than edited, because it is the requirement's own text and
someone reading R-100 should find it here; A50 is where the number moved.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..consent import NotAConsent, is_notice
from ..models import Consent, MINIMUM_AGE, Member


class BelowAgeFloor(ValueError):
    """R-100 / NG-05. Carries the floor so the message does not have to restate it."""

    def __init__(self, stated_age: int) -> None:
        super().__init__(
            f"eigentliCH opens accounts from {MINIMUM_AGE}. Stated age: {stated_age}."
        )
        self.stated_age = stated_age
        self.minimum_age = MINIMUM_AGE


def register_member(
    session: Session,
    *,
    age_at_registration: int,
    display_name: str,
    locale: str = "de-CH",
    consents: list[dict] | None = None,
) -> Member:
    """Create a member, or refuse.

    Consents are versioned records from the outset (R-103). There is no boolean anywhere in this path: a
    checkbox that was ticked tells you nothing a year later about *what* was ticked, and R-230 requires the
    history to be visible and withdrawable.

    **`consents` is optional HERE and required at the capture point**, which is a split worth stating.
    This function is called by fixtures and by `tools/seed_demo_accounts.py` to make member rows, and a
    member row is not an account: `api/auth.py` says a member with no credential is an account nobody can
    open. The route that opens accounts — `POST /api/members` — refuses without the required purposes, and
    it refuses before this function is reached. Enforcing it a second time in here would refuse dozens of
    legitimate internal callers for a guarantee they are not the ones making.

    Every `purpose` handed in is checked against R-103's registry by the model's own validator, so an
    entry with a purpose outside `consent.REGISTERED_PURPOSES` raises here whoever the caller is.

    **A97: a purpose published as a notice is refused here, and this is the only place it has to be.**
    `Consent` rows are written in exactly one function, this one, so the guarantee "nothing writes a
    `Consent` row for the notice" is one check rather than a rule every caller has to remember. It cannot
    be a model validator instead: rows naming `entscheidprotokoll` were written while it *was* a consent,
    and a validator refusing the key would make a real historical record unwritable — `consent.py` records
    that argument at `REGISTERED_PURPOSES`. Refused before the member row is created, so a caller passing
    one does not leave a half-registered member behind.
    """
    if not isinstance(age_at_registration, int) or isinstance(age_at_registration, bool):
        raise BelowAgeFloor(age_at_registration)  # a non-integer age is not an age
    if age_at_registration < MINIMUM_AGE:
        raise BelowAgeFloor(age_at_registration)

    for entry in consents or []:
        if is_notice(entry["purpose"]):
            raise NotAConsent(entry["purpose"])

    member = Member(
        age_at_registration=age_at_registration,
        display_name=display_name,
        locale=locale,
    )
    session.add(member)
    session.flush()  # member.id, so consents can reference it

    _write_consents(session, member_id=member.id, consents=consents)
    return member


def _write_consents(session: Session, *, member_id: str, consents: list[dict] | None) -> list[Consent]:
    """The one place a `Consent` row is written. A97's guarantee, kept as a single function.

    Extracted from `register_member` on 4 September 2026 so that `grant_consents` below can reuse it
    rather than build rows of its own. The guarantee A97 states — *nothing writes a Consent row for a
    notice* — is a property of this function, and it stays one function however many callers it has.
    """
    now = datetime.now(timezone.utc)
    written = []
    for entry in consents or []:
        row = Consent(
            member_id=member_id,
            purpose=entry["purpose"],
            document_version=entry["document_version"],
            granted_at=entry.get("granted_at") or now,
            notes=entry.get("notes"),
        )
        session.add(row)
        written.append(row)
    return written


def grant_consents(
    session: Session, *, member_id: str, consents: list[dict]
) -> list[Consent]:
    """Record consents for a member who already exists.

    **Why this exists.** `register_member` takes consents because the ordinary path creates the member and
    the consents together. A member seeded as an access shell (A53) has neither, and
    `tools/load_submission.py` was found on 4 September completing such a shell with a full plan and no
    consent at all — so C-05's "sole data controller from the first intake question" had no artefact
    behind it and R-230's history was empty for that member.

    The notice check is repeated here rather than left to the caller, for the reason A97 gives: a purpose
    published as a notice must not become a consent row, and the check belongs where the row is made.
    Already-granted purposes are skipped, so this is idempotent per purpose.
    """
    for entry in consents:
        if is_notice(entry["purpose"]):
            raise NotAConsent(entry["purpose"])

    already = {
        row.purpose
        for row in session.execute(
            select(Consent).where(Consent.member_id == member_id)
        ).scalars()
    }
    wanted = [entry for entry in consents if entry["purpose"] not in already]
    return _write_consents(session, member_id=member_id, consents=wanted)


def withdraw_consent(session: Session, *, consent: Consent, at: datetime | None = None) -> Consent:
    """R-230. The grant is marked withdrawn; it is not deleted.

    "Did they ever consent, and to what version" outlives the consent itself, and a deleted grant cannot
    answer it.

    **Marking is the whole of it, and that is the intended state.** Setting `withdrawn_at` does not
    revoke access, stop any processing, close the account or gate a single route: nothing in this
    application reads the column to decide anything, and an audit confirmed that every member route still
    answers after a withdrawal. The member-facing wording in `consent.py` was corrected to say so rather
    than this function being made to do what the wording claimed — the owner's decision. If that is ever
    reversed and a gate is added here, `consent.py`'s `datenbearbeitung` consequence has to change in the
    same commit, and `tests/test_consent.py` fails until it does.
    """
    consent.withdrawn_at = at or datetime.now(timezone.utc)
    return consent
