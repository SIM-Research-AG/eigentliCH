"""S-10, the learning path and the capability review.

**The sentence is the progression** (R-191). A member opening this screen sees statements about what they
can do — "can explain what a Freizuegigkeitskonto in cash costs per year" — and there is nothing else to
see, because there is nothing else. C-07 is held here by absence: no counter, no meter, no ordering, no
aggregate of any kind. Not one is withheld from the UI; none is computed, so none can be rendered.

**D-01 is open and this module does not close it.** `Capability.rung` is written as null by `seed`, the
content file defines no scheme, and every payload states the scheme is undecided rather than leaving a
client to infer one from silence. Two places where a scheme would have crept in, and what happens instead:

  * *Ordering.* Capabilities and units are returned in file order and the payload says so
    (`capabilities_are_unordered`). File order is authoring convenience; reading it as a sequence would be
    reading a ladder that nobody has designed.
  * *Prerequisites.* R-190 says units have prerequisites, so they are stated. It does not say a unit is
    locked until they are met, and whether evidence of a prerequisite's capabilities constitutes having
    met it is precisely the assessment question D-01 owns. So `learning_path` reports, per prerequisite,
    which of its capabilities have no assertion yet — a fact — and never a met/unmet flag or a lock.

**A41.** The seeded content is fictional and says so in the file. `seed` refuses to write a record that is
not marked, so the marker is load-bearing rather than decorative.

**R-194 / NG-04.** These are eigentliCH's own statements. No payload claims federal or accredited standing,
and `qualification_claim` is explicitly null so a client never has to infer that from an absent key.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..content import CONTENT, DEFAULT_LANGUAGE, ContentMissing
from ..models import Capability, CapabilityAssertion, LearningUnit, utcnow

#: The one content record this module reads. Loaded the way `content.py` loads its own — same root, same
#: exception, no literal fallback — rather than through it, because wiring these accessors into
#: `content.py` is an edit to a file this change does not own. They belong there once it does.
LEARNING = "learning"

#: D-01, **answered**. Stated in every payload, so a client reads the answer rather than an absent key.
#:
#: A82 records the answer as *"it's their responsibility"*, read as self-assessment: a member asserts a
#: capability and eigentliCH never tests, grades or certifies it. So there is no rung scheme — not one still
#: being chosen, but none, permanently — and `Capability.rung` stays null because nothing will ever have
#: the standing to write it.
#:
#: **This constant used to read `undecided_d01`.** That stopped being true on 31 August 2026, and it is
#: the same defect `goal_illustration` carried: a payload may only give a reason that is still the reason.
RUNG_SCHEME_NONE = "self_assessed_no_scheme_d01"

#: D-01 / A82. What a self-asserted capability records in `CapabilityAssertion.evidence_kind`.
#:
#: **A constant rather than a field on the request**, and that is the D-01 line held in one place.
#: `record_assertion` deliberately takes `evidence_kind` as free text with no enum, because the caller
#: states what happened — but the caller on the member's own route is a browser, and a free-text kind
#: arriving from one is where a graded word gets stored and then rendered straight back out by
#: `capability_review`. The member's route may write exactly one kind: the member said so.
SELF_ASSERTION_KIND = "member_self_assertion"

#: The reason both payloads give for there being no assessment to report. Names A82 so the sentence that
#: decided it is findable from the wire.
SELF_ASSESSMENT = "member_self_assessment_a82"

#: R-194 / NG-04. Named once; a second phrasing of this somewhere else is a second claim to keep honest.
QUALIFICATION_CLAIM = "eigentlich_states_capabilities_only"


class NoSuchCapability(LookupError):
    """The caller named a capability statement that does not exist in the content.

    Distinct from `ContentMissing`, which means the content *file* or a statement inside it is absent —
    that is a 503, because the application is fine and the record is not there. A caller naming a key
    nobody authored is a 404, and collapsing the two would answer "the server is broken" to a typo.
    """


class NotEvidencedByThatUnit(ValueError):
    """A member pointed a self-assertion at a unit that does not evidence the capability they asserted.

    Refused rather than stored, because `evidence_ref` is rendered back by `capability_review` and a
    reference that does not hold is worse than no reference: it reads as corroboration and is not.
    """


class AlreadyAsserted(ValueError):
    """This member has already asserted this capability themselves.

    **Refused rather than accepted as a second row**, and the reason is C-07 rather than tidiness. R-191
    makes the statement itself the whole of the progression: a capability is asserted or it is not, and
    there is nothing a second identical assertion could add except a number of them. A number of them is
    the tally this product exists without — and it would be a tally that `member_standing` already
    de-duplicates for the ordering, so it could only ever be rendered, never used.

    Matched on the self-assertion kind alone, so a differently-sourced assertion — if the owner ever
    corrects A82's reading to mean the curators — is not blocked by a member's own.
    """


class NotMarkedFictional(Exception):
    """A41. Seed content that does not declare itself fictional is not written to the database.

    The honesty rule is only worth something if something enforces it. A record that reaches the store
    unmarked is a record that can be screenshotted as real supply, and the marker is in the content file
    rather than on the row because the model layer is fixed for this phase — so `seed` is where it bites.
    """


@lru_cache(maxsize=1)
def _learning() -> dict:
    path = CONTENT / f"{LEARNING}.json"
    if not path.exists():
        raise ContentMissing(
            f"learning content not found at {path}. S-10's units, capability statements and the three "
            f"exits of R-193 are content records; there is deliberately no literal to fall back to."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def content_is_fictional() -> bool:
    """A41. True while the shipped seed content is demonstration material rather than real."""
    return bool(_learning().get("fictional", False))


def capabilities() -> list[dict]:
    """R-191. The statements, in file order, which is not an order of anything."""
    return _learning()["capabilities"]


def capability(key: str) -> dict:
    for record in capabilities():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no capability statement {key!r}")


def units() -> list[dict]:
    return _learning()["units"]


def unit(key: str) -> dict:
    for record in units():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no learning unit {key!r}")


def exits() -> list[dict]:
    """R-193. Three, named in the content. Only the second and third touch the Market Place."""
    return _learning()["exits"]


def statement(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    """One capability statement in one language.

    Raises rather than falling back to the other language. A12 makes German the authored language, and a
    silent German fallback on an English screen is how a half-translated product ships unnoticed.
    """
    value = capability(key)["statement"].get(language)
    if not value:
        raise ContentMissing(
            f"capability {key!r} has no statement in {language!r}. R-191 makes this sentence the whole of "
            f"what a member is shown, so there is nothing to render without it."
        )
    return value


def _localised(block: dict, language: str) -> str | None:
    """A member-facing string in one language, or None. Never a placeholder, never the other language."""
    return block.get(language) or None


# ---------------------------------------------------------------- seeding


def seed(session: Session) -> dict:
    """Write the content file's units and capabilities into the store, once.

    Idempotent by key: the content `key` is the row id, so re-running adds nothing and rewrites nothing.
    Existing rows are left exactly as they are — a member's assertions point at these ids, and silently
    restating a statement under an id somebody has already been assessed against changes what their
    assertion means.

    **Every row is written with `rung=None`** (D-01, R-192). Explicitly, not by omission, so that the
    absence reads as a decision when someone greps for it.
    """
    for record in list(capabilities()) + list(units()):
        if not record.get("fictional"):
            raise NotMarkedFictional(
                f"A41: seed record {record['key']!r} is not marked fictional. Seeded content is "
                f"demonstration material and must say so in the data itself, so that a screenshot of it "
                f"cannot be mistaken for real."
            )

    written = {"capabilities": [], "units": []}

    for record in capabilities():
        if session.get(Capability, record["key"]) is not None:
            continue
        session.add(
            Capability(
                id=record["key"],
                # The authored language (A12). The row exists so an assertion has something to point at;
                # the sentence a member reads comes from the content record in their own language.
                statement=record["statement"][DEFAULT_LANGUAGE],
                rung=None,
            )
        )
        written["capabilities"].append(record["key"])

    for record in units():
        if session.get(LearningUnit, record["key"]) is not None:
            continue
        session.add(
            LearningUnit(
                id=record["key"],
                title=record["title"][DEFAULT_LANGUAGE],
                # Traces the row back to the fictional content record it came from. Null in the file
                # because no unit ships lesson prose — see `_about.bodies` there, and R-183's same call.
                body_ref=f"{LEARNING}.json#units.{record['key']}",
                prerequisites=list(record["prerequisites"]),
                capability_ids=list(record["capability_keys"]),
                # Left unset. Fictional demonstration content has no owner to name, and naming one would
                # be the claim of provenance A41 exists to prevent.
                ip_owner=None,
            )
        )
        written["units"].append(record["key"])

    return written


# ---------------------------------------------------------------- member payloads


def _evidenced_capability_ids(session: Session, member_id: str | None) -> set[str]:
    if member_id is None:
        return set()
    rows = session.execute(
        select(CapabilityAssertion.capability_id).where(CapabilityAssertion.member_id == member_id)
    ).scalars()
    return set(rows)


def _assertions_for(session: Session, member_id: str | None) -> dict[str, list[CapabilityAssertion]]:
    if member_id is None:
        return {}
    rows = session.execute(
        select(CapabilityAssertion).where(CapabilityAssertion.member_id == member_id)
    ).scalars()
    found: dict[str, list[CapabilityAssertion]] = {}
    for row in rows:
        found.setdefault(row.capability_id, []).append(row)
    return found


def learning_path(
    session: Session, *, member_id: str | None = None, language: str = DEFAULT_LANGUAGE
) -> dict:
    """S-10. The units, what each evidences, and the three exits.

    `member_id` is optional: without one this is the path as anybody would see it, which is what a client
    rendering it before sign-in needs. With one, each capability carries whether an assertion exists.
    """
    evidenced = _evidenced_capability_ids(session, member_id)

    payload_units = []
    for record in units():
        payload_units.append(
            {
                "key": record["key"],
                "title": _localised(record["title"], language),
                "summary": _localised(record["summary"], language),
                # A41, carried through to the client so the marker survives into what is rendered.
                "fictional": bool(record.get("fictional")),
                # R-190, first half. Stated as facts about each prerequisite, never as a gate.
                "prerequisites": [
                    {
                        "key": prerequisite,
                        "title": _localised(unit(prerequisite)["title"], language),
                        "capabilities_without_evidence": [
                            key
                            for key in unit(prerequisite)["capability_keys"]
                            if key not in evidenced
                        ],
                    }
                    for prerequisite in record["prerequisites"]
                ],
                # R-190, second half. One or more capabilities, each with the sentence itself.
                "evidences": [
                    {
                        "key": key,
                        "statement": _localised(capability(key)["statement"], language),
                        "rung": None,
                        "evidenced": key in evidenced,
                    }
                    for key in record["capability_keys"]
                ],
                # R-193. A unit names an exit only where it genuinely leads to one.
                "exits": list(record["exits"]),
                # No lesson prose ships with the seed content, and the reason is explicit rather than
                # left to be read out of a null.
                "body_ref": record["body_ref"],
                "body_unavailable_reason": "not_authored",
            }
        )

    return {
        "member_id": member_id,
        "language": language,
        "fictional": content_is_fictional(),
        "units": payload_units,
        "exits": [
            {
                "key": record["key"],
                "name": _localised(record["name"], language),
                "description": _localised(record["description"], language),
                # R-193. Only `offer_a_service` and `start_a_venture` are true here.
                "touches_market_place": bool(record["touches_market_place"]),
                "fictional": bool(record.get("fictional")),
            }
            for record in exits()
        ],
        # D-01 / R-192, said out loud in the payload rather than inferred from a null column.
        "rung_scheme": None,
        "rung_scheme_reason": RUNG_SCHEME_NONE,
        # D-01's answer (A82), stated as a positive fact rather than left to be read out of the null
        # above. A member is the one who says what they can do; eigentliCH records that they said it.
        "capabilities_are_self_asserted": True,
        "capabilities_are_self_asserted_reason": SELF_ASSESSMENT,
        # R-194 restated where it bites hardest: this is the field a reader would use to decide what a
        # capability is worth, and the honest answer is that eigentliCH examined nothing.
        "eigentlich_assesses_capabilities": False,
        # File order is authoring convenience. A client that reads it as a sequence is reading a ladder
        # nobody designed, so the payload denies the reading it would otherwise invite.
        "capabilities_are_unordered": True,
        # Nothing here locks a unit. Whether evidence of a prerequisite's capabilities means the
        # prerequisite is met is the assessment question D-01 owns.
        "units_are_not_gated": True,
        # R-194 / NG-04.
        "qualification_claim": None,
        "qualification_claim_reason": QUALIFICATION_CLAIM,
        # NO count of units, NO count of capabilities evidenced, NO ratio, NO next-unit suggestion.
        # C-07 and R-006: progress along anything is never displayed as achievement.
    }


def capability_review(
    session: Session, *, member_id: str | None = None, language: str = DEFAULT_LANGUAGE
) -> dict:
    """S-10's other half: every capability statement, and what evidence the member has for it.

    The evidence is reported as it was recorded — kind, reference, who assessed it, when. It is not
    summarised, graded or reduced to a state, because the vocabulary for doing that is D-01's to choose.
    """
    assertions = _assertions_for(session, member_id)
    evidencing_units = {
        record["key"]: [u["key"] for u in units() if record["key"] in u["capability_keys"]]
        for record in capabilities()
    }

    return {
        "member_id": member_id,
        "language": language,
        "fictional": content_is_fictional(),
        "capabilities": [
            {
                "key": record["key"],
                # R-191. The sentence, in the member's language. This is the whole of the progression.
                "statement": _localised(record["statement"], language),
                # D-01. Null in the file, null on the row, null here.
                "rung": None,
                "fictional": bool(record.get("fictional")),
                "evidenced": bool(assertions.get(record["key"])),
                "evidence": [
                    {
                        "evidence_kind": row.evidence_kind,
                        "evidence_ref": row.evidence_ref,
                        "assessed_by": row.assessed_by,
                        "assessed_at": row.assessed_at.isoformat(),
                        # D-01 / A82. Which of these the member said themselves. A flag rather than a
                        # client parsing `evidence_kind`, because a client that has to recognise a magic
                        # string is a client that gets it wrong on the row that matters.
                        "self_asserted": row.evidence_kind == SELF_ASSERTION_KIND,
                    }
                    for row in assertions.get(record["key"], [])
                ],
                "evidenced_by_units": evidencing_units[record["key"]],
            }
            for record in capabilities()
        ],
        "rung_scheme": None,
        "rung_scheme_reason": RUNG_SCHEME_NONE,
        # D-01's answer (A82). Same two keys as `learning_path`, from the same constant.
        "capabilities_are_self_asserted": True,
        "capabilities_are_self_asserted_reason": SELF_ASSESSMENT,
        "eigentlich_assesses_capabilities": False,
        "capabilities_are_unordered": True,
        "qualification_claim": None,
        "qualification_claim_reason": QUALIFICATION_CLAIM,
        # NO tally of evidenced capabilities, NO ratio, NO ordering by evidence. A "7 of 10" here is the
        # completion meter this product exists without — R-113, R-006.
    }


def record_assertion(
    session: Session,
    *,
    member_id: str,
    capability_id: str,
    evidence_kind: str,
    assessed_by: str,
    evidence_ref: str | None = None,
    assessed_at: datetime | None = None,
) -> CapabilityAssertion:
    """Record that a member has evidenced one capability.

    **This decides nothing about assessment** (D-01). `evidence_kind` is free text with no enum, there is
    no rule here about who may appear in `assessed_by`, and nothing is inferred from the assertion beyond
    its own existence. The caller states what happened and who says so; the route by which a member gets
    assessed is the open decision, and it does not get settled by a constructor.

    Deliberately not exposed over HTTP for the same reason — see `api/knowledge.py`.
    """
    if session.get(Capability, capability_id) is None:
        raise ContentMissing(
            f"no capability {capability_id!r} in the store. Run `seed` first: an assertion has to point "
            f"at a statement that exists, or it asserts nothing readable."
        )
    assertion = CapabilityAssertion(
        member_id=member_id,
        capability_id=capability_id,
        evidence_kind=evidence_kind,
        evidence_ref=evidence_ref,
        assessed_by=assessed_by,
        assessed_at=assessed_at or utcnow(),
    )
    session.add(assertion)
    return assertion


# ---------------------------------------------------------------- D-01's answer: the member says so


def self_assessed_by(member_id: str) -> str:
    """A82 / R-194. What `assessed_by` names on a self-assertion: the member themselves.

    **Not `"eigentlich"`, and not a curator.** `assessed_by` is the field a reader uses to decide what a
    claim is worth, so eigentliCH's own name in it would be eigentliCH vouching for a statement it never
    examined — the claim of standing R-194 forbids, made in a column instead of in copy. The member's own
    id is both the honest answer and the useful one: it says the evidence for this capability is that the
    person who holds it says so, which is exactly what A82 decided and no more than that.

    The id rather than the display name, because a display name is not an identity and R-231's erasure
    empties it — an `assessed_by` reading `member:Lea` would survive the erasure of Lea.
    """
    return f"member:{member_id}"


def _self_assertion_exists(session: Session, member_id: str, capability_id: str) -> bool:
    row = session.execute(
        select(CapabilityAssertion.id).where(
            CapabilityAssertion.member_id == member_id,
            CapabilityAssertion.capability_id == capability_id,
            CapabilityAssertion.evidence_kind == SELF_ASSERTION_KIND,
        )
    ).scalars().first()
    return row is not None


def record_self_assertion(
    session: Session,
    *,
    member_id: str,
    capability_id: str,
    learning_unit: str | None = None,
    assessed_at: datetime | None = None,
) -> CapabilityAssertion:
    """A member asserts one capability about themselves. **D-01's answer, and nothing beyond it.**

    A82 answered D-01: the rung scheme and how a capability is assessed are *"their responsibility"*,
    read as self-assessment. So this is the whole of the assessment route eigentliCH has — a member says
    what they can do and eigentliCH records that they said it. R-194 is why it can be nothing more: a
    product that may make no claim of accredited status cannot be in the business of examining anybody.

    **What the row records, and why each field holds what it holds.**

      * `evidence_kind` is `SELF_ASSERTION_KIND`, a server constant, not the caller's word. See that
        constant: the free-text kind `record_assertion` accepts is right for a caller who knows what
        happened and wrong for a browser, because `capability_review` renders this field straight back.
      * `assessed_by` is `self_assessed_by(member_id)` — the member. See that function for why naming
        eigentliCH here would be a claim rather than a record.
      * `evidence_ref` is either null or the trace of one learning unit, and never free text. A member
        may point at the unit they worked through, and the reference is *checked*: the unit has to be one
        that actually evidences this capability (R-190's `capability_ids`). So the only reference this
        can hold is one the content already asserts, which keeps a member's own words out of a field that
        is rendered back as corroboration.
      * `rung` is not touched, because there is nothing to write there and never will be.

    **This is not a plan mutation and writes no Decision** (C-09). C-09 covers `positions` and `goals` —
    what a member holds and what it is for. A capability assertion is a statement about the member, not a
    change to their plan, and manufacturing a Decision for one would put a record in S-07 that says a
    plan changed when none did. The permanent record here is the assertion row itself.

    Raises `NoSuchCapability`, `NotEvidencedByThatUnit`, `AlreadyAsserted` — see each.
    """
    # Against the content, not the table: a key nobody authored is a caller's mistake, and `capability`
    # raises `ContentMissing` for it, which the router would answer with a 503 about the server.
    try:
        capability(capability_id)
    except ContentMissing as unknown:
        raise NoSuchCapability(
            f"no capability statement {capability_id!r}. The keys are the ones "
            f"`GET /api/capabilities` returns."
        ) from unknown

    evidence_ref = None
    if learning_unit is not None:
        try:
            record = unit(learning_unit)
        except ContentMissing as unknown:
            raise NoSuchCapability(
                f"no learning unit {learning_unit!r}. The keys are the ones `GET /api/learning` returns."
            ) from unknown
        if capability_id not in record["capability_keys"]:
            raise NotEvidencedByThatUnit(
                f"R-190: unit {learning_unit!r} does not evidence {capability_id!r}. A reference that "
                f"does not hold reads as corroboration and is not one, so it is refused rather than "
                f"stored — the unit evidences {list(record['capability_keys'])}."
            )
        # The same trace shape `seed` writes onto `LearningUnit.body_ref`, so both point at the content
        # record they came from in one form rather than two.
        evidence_ref = f"{LEARNING}.json#units.{learning_unit}"

    if _self_assertion_exists(session, member_id, capability_id):
        raise AlreadyAsserted(
            f"member {member_id!r} has already asserted {capability_id!r}. R-191 makes the statement "
            f"itself the progression: it is asserted or it is not, and a second row could only ever be "
            f"read as a number of them."
        )

    return record_assertion(
        session,
        member_id=member_id,
        capability_id=capability_id,
        evidence_kind=SELF_ASSERTION_KIND,
        assessed_by=self_assessed_by(member_id),
        evidence_ref=evidence_ref,
        assessed_at=assessed_at,
    )
