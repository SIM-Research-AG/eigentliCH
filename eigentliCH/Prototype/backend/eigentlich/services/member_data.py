"""The one list of what a member owns. R-154's export and R-231's erasure both read it.

**Why this module exists at all.** The export used to carry a hand-written list of tables and the erasure
carried its own. `export.py`'s `_row()` already meant that a new *column* could not be forgotten — but a
new *table* could, and five of them had been: `access_grants`, `attendances`, `capability_assertions`,
`member_offers` and `providers` were deleted when a member was erased and were not in the file the member
took away with them. **Exporting less than you erase is incoherent**: R-154 is the member's right to leave
with their record, and the application had already decided those rows were the member's when it agreed to
destroy them.

The worst of the five was `capability_assertions`. R-191 says the capability statements *are* the member's
progression and that there is nothing else in the system that represents it, so a member who exported and
left took no record of what they had learned.

**Two lists cannot agree; one list cannot disagree.** So there is one tuple here, and the export walks it.
`test_the_export_and_the_erasure_name_the_same_tables` asserts the agreement anyway — deriving one from the
other is what makes the next table added arrive in both places, and the test is what says so out loud when
somebody splits them again.

**The tuple's ORDER is load-bearing and belongs to the erasure**, not to the export. Foreign keys are on
(`db.py` sets `PRAGMA foreign_keys=ON`), so a row has to go before the row it points at. The export reads
the same tuple in reverse, purely so a person opening the file meets their positions and goals before the
rows that reference them; nothing in the export depends on the order.

**What is deliberately NOT here.** `credentials` and `sessions` are erased and not exported: a password
hash and a live session token are not material a member owns in any sense that helps them, and putting a
token in a file that gets emailed around is a hazard rather than a right. That exclusion is named in
`EXPORT_OMITS` with its reason, so it reads as a decision rather than as the same oversight again.
"""

from __future__ import annotations

from sqlalchemy import select

from ..models import (
    AccessGrant,
    ActionItem,
    Attendance,
    CapabilityAssertion,
    Consent,
    Credential,
    CuratorSession,
    Decision,
    Disclosure,
    EngineRun,
    Goal,
    HouseholdMember,
    Listing,
    MemberFact,
    MemberOffer,
    OnboardingAnswer,
    PlanVersion,
    Position,
    Provider,
    Session as LoginSession,
    Submission,
    VaultItem,
)

#: Every table that carries the member's own rows and is DELETED outright when they leave.
#:
#: Ordered so that a row goes before the row it references. `Provider` is last of the market-place group
#: because its `Listing` rows point at it, and those are cleared in the dependent-row step that runs
#: before this tuple is walked — see `erasure._erase`.
DELETED_IN_ERASURE_ORDER: tuple[type, ...] = (
    Attendance,
    # A plan version is wholly the member's: their own positions and goals, frozen, plus the household
    # composition their plan assumed. Deleted rather than redacted, unlike `household_members` — there is
    # no second member whose record a version is.
    #
    # A version's frozen `inputs` carries a partner's label inside its `owners` blocks, and that goes with
    # the row. That is the right outcome and it is the reverse of A109's case: there the row WAS the other
    # member's statement, here it is a copy this member took of their own plan.
    #
    # **`erasure._erase` deletes these itself, oldest first, before this tuple is walked** —
    # `superseded_by_id` is a self-reference and the order is not incidental. It stays in this tuple
    # because that is what puts it in `EXPORTED_MODELS`: R-154 gives the member every table R-231
    # destroys, and a table erased by a special case and absent from the export is the asymmetry the
    # schema check exists to catch. Deleting it twice is harmless — the second pass finds no rows.
    PlanVersion,
    # R-301's queued engine runs. The member's, in both directions: the payload was built from their plan
    # and the result was computed for them, so R-154 gives them the record and R-231 destroys it. The
    # stored result was already stripped of every published-artefact key on the way in (C-03), which is
    # what makes it safe for the export file as well as for the HTTP poll.
    EngineRun,
    CapabilityAssertion,
    MemberOffer,
    OnboardingAnswer,
    # The intake file as it arrived. Wholly the member's -- they typed it about themselves -- so R-154
    # hands it back on export and R-231 destroys it here. **It is in this tuple for the same reason it is
    # safe to store at all**: an unmapped answer the member cannot take away and cannot have deleted would
    # be a record held about them that they do not control, which is the argument against keeping it.
    Submission,
    # The five stated facts (A127). Wholly the member's: they said them about themselves, so R-154 gives
    # them the rows and R-231 destroys them. Unlike `household_members` there is no second person whose
    # record a canton is, so this is a delete and not a redaction.
    #
    # `decision_facts` is a plain link table and is cleared in the dependent-row step of `erasure._erase`
    # before this tuple is walked, for the same reason `decision_positions` is: `member_fact_id` is a NOT
    # NULL foreign key and the delete below fails on it otherwise.
    MemberFact,
    ActionItem,
    AccessGrant,
    LoginSession,
    Credential,
    Consent,
    VaultItem,
    Goal,
    Position,
    Provider,
)

#: Rows that survive erasure because removing them would damage a record that is not only this member's,
#: and are emptied of the member instead. They are the member's while the member is here, so they are
#: exported.
#:
#: **`Decision` and `CuratorSession` are here because R-040 and C-10 forbid removing them.**
#:
#: **`HouseholdMember` is here for a different reason, and it is the one worth reading.** The row names
#: this member, so R-231 must take their name off it. But the row is also a statement *the other member
#: made about their own household* — "we were two adults as of March 2027" — and every plan version that
#: household ever produced is stamped against that composition. Deleting the row would silently rewrite a
#: second person's stated history and leave their `household_as_of` describing a household that, according
#: to the database, never had two people in it. **One member exercising erasure may not edit another
#: member's record.** So the row survives with `member_id` NULL and its label redacted: the composition
#: stays true, and nothing in it identifies anybody.
#:
#: A single-member household ends up holding one anonymous row, which is the honest result — somebody
#: stated a household and then left.
#:
#: **Recorded as needing the owner's ratification (see DECISIONS.md A108).** Whose personal data a
#: partner's `label` is — the member who typed it, or the person it names — is a privacy question with an
#: owner, and the export currently gives a member only their own row rather than the composition they
#: themselves stated. That narrowness is deliberate until the question is answered, not an oversight.
REDACTED_IN_ERASURE: tuple[type, ...] = (Decision, CuratorSession, HouseholdMember)

#: The member's rows that carry no `member_id` of their own. They hang off the member's `Provider` through
#: NOT NULL foreign keys, so they have to be cleared before it — the same rule as the tuple above, one
#: table deeper — and they are exported for exactly the reason the five missing tables were: a listing's
#: title and summary are words the member wrote, and the erasure destroys them. A member who applied to be
#: listed and then left would otherwise take away a `providers` row and no record of what they offered.
#:
#: Ordered for the erasure, children first. `owning_predicate` is how a row here is known to be theirs.
DEPENDENTS_IN_ERASURE_ORDER: tuple[type, ...] = (Disclosure, Listing)

#: R-154, the exclusions, with the reason each one is a decision rather than an omission.
EXPORT_OMITS: dict[str, str] = {
    "credentials": "a password hash and its salt are not material the member owns in any sense that "
                   "helps them, and a copy of one is a hazard rather than a right.",
    "sessions": "a live session token is a key to the running application, not a record of the member's "
                "life. An export that carried one would be a credential in a file people email around.",
}

#: R-154's collections, in the order a person meets them when they open the file. Derived, so the next
#: table added to the erasure appears here without anybody remembering to add it.
EXPORTED_MODELS: tuple[type, ...] = tuple(
    model
    for model in (
        *reversed(DELETED_IN_ERASURE_ORDER),
        *reversed(DEPENDENTS_IN_ERASURE_ORDER),
        *REDACTED_IN_ERASURE,
    )
    if model.__tablename__ not in EXPORT_OMITS
)

#: The keys the export document carries, one per model above. A table name, so a reader of the file and a
#: reader of the schema are looking at the same word.
EXPORTED_TABLES: tuple[str, ...] = tuple(model.__tablename__ for model in EXPORTED_MODELS)


def member_owned_tables() -> frozenset[str]:
    """Every mapped table carrying a `member_id`, asked of the schema rather than listed here.

    This is the measure the two lists above are held against: a table the ORM says belongs to a member and
    that neither erases nor exports it is the defect this module was written to close.
    """
    from ..models import Base

    return frozenset(
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if "member_id" in mapper.class_.__table__.columns
    )


def tables_missing_from_the_export(owned: frozenset[str]) -> list[str]:
    """Which of `owned` neither the export carries nor `EXPORT_OMITS` accounts for.

    A function rather than an expression inside a test, so the comparison can be shown to detect a table
    that is genuinely absent — hand it a name nothing exports and it has to come back. A guard that asserts
    an emptiness and has never been shown able to report a non-emptiness is the shape this estate has been
    bitten by four times (A20, A63, A66, A68).
    """
    return sorted(owned - set(EXPORTED_TABLES) - set(EXPORT_OMITS))


def owning_predicate(model, member_id: str):
    """How a row of `model` is known to be this member's. **One answer, used by both paths.**

    Almost every table says so with a `member_id` column. The two market-place tables do not: a `Listing`
    belongs to a `Provider` and a `Disclosure` belongs to a `Listing`, and the chain has to be walked. It
    is walked here rather than twice — the erasure deleting by one rule and the export selecting by
    another is the same hazard as two lists of tables, in a shape that is harder to notice.
    """
    if model is Listing:
        return Listing.provider_id.in_(
            select(Provider.id).where(Provider.member_id == member_id)
        )
    if model is Disclosure:
        return Disclosure.listing_id.in_(
            select(Listing.id).where(owning_predicate(Listing, member_id))
        )
    return model.member_id == member_id


#: The one model on which reading and erasing legitimately differ, and the reason. Read by
#: `readable_predicate` below and asserted by `tests/test_household.py` to be exactly this size, so a
#: second entry cannot be added without a test saying why.
READS_WIDER_THAN_IT_ERASES: dict[type, str] = {
    HouseholdMember: (
        "A109. The member stated the whole composition — themselves, their partner, their children — so "
        "R-154 gives them all of it: an export that returned one row would not show them what they "
        "described. But R-231 may only take their own name off it, because the same rows are the OTHER "
        "member's statement about their own household, and one member's erasure may not edit another "
        "member's record."
    ),
}


def readable_predicate(model, member_id: str):
    """What the member may READ. Identical to `owning_predicate` except where the two must differ.

    **This function exists because the invariant above has exactly one true exception, and hiding it
    inside `owning_predicate` behind a flag would have been worse than naming it.** The docstring above is
    emphatic that one definition serves both paths, and it is right for every table but one: on
    `household_members`, a member may read rows they do not own and may not erase them. A boolean
    parameter on `owning_predicate` would have made the erasure's behaviour depend on an argument some
    future caller forgets to pass, and the failure would be silent and in the direction that destroys a
    third party's data.

    So the widening is a separate, named function over a table of models with a written reason each, and
    the export calls this one while the erasure keeps calling `owning_predicate`. A test asserts the two
    disagree on exactly the models in `READS_WIDER_THAN_IT_ERASES` and agree on every other.
    """
    if model in READS_WIDER_THAN_IT_ERASES:
        if model is HouseholdMember:
            # Every row of every household this member belongs to, closed households included: a plan
            # version stamped against a household that has since closed is still the member's record.
            return HouseholdMember.household_id.in_(
                select(HouseholdMember.household_id).where(
                    HouseholdMember.member_id == member_id
                )
            )
        raise NotImplementedError(  # pragma: no cover - an import-time contract in function form
            f"{model.__name__} is named in READS_WIDER_THAN_IT_ERASES with no widening written for it. "
            f"A model listed here and not handled would silently fall through to the erasure's own rule, "
            f"which is the narrower one — the export would quietly under-report."
        )
    return owning_predicate(model, member_id)
