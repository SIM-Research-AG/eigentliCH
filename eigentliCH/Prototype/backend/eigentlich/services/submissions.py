"""Keeping the intake file, and finding the answers in it that nothing can use yet.

**The order is the point: store first, map second.** `tools/load_submission.py` read a file, mapped what
it could and printed the rest. If the process died between reading and writing, or if a key had no home,
the answer was gone. Now the file lands whole and the mapping runs over a row that already exists, so an
answer with no home is still there when the home is built.

**Nothing here reads a submission back into a plan.** That is deliberate and it is what makes storing
unmapped answers safe: the blob is inert. `unmapped()` reports what is in it; turning one of those keys
into a position or a fact is a separate act, in the loader, that also decides what the key means.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Submission


class DuplicateSubmission(Exception):
    """This member already has this exact file.

    Raised rather than ignored. Loading twice is an accident — a curator running the tool again, a member
    sending the same attachment — and the two outcomes a caller might want (skip it, or replace it) are
    different enough that guessing is worse than stopping.
    """


def content_hash(payload: dict) -> str:
    """A stable digest of the payload.

    `sort_keys` and a fixed separator, so the same answers hash the same whatever order the browser wrote
    them in. `ensure_ascii=False` so an umlaut is the same bytes here as in the file.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def store(session: Session, *, member_id: str, file: dict, note: str | None = None) -> Submission:
    """Keep an intake file against a member, exactly as it arrived.

    Takes the whole file — `schema_version`, `meta`, `raw` — rather than only its answers, because the
    instrument version is what says which question a key belonged to and two instruments have used the
    same key for different things.

    **No Decision.** A submission is a transcript, not a plan mutation. C-09 governs what changes a
    member's plan, and storing what they typed does not: the mapping that follows does, and that writes
    its own Decisions.
    """
    if not isinstance(file, dict):
        raise ValueError("a submission is a JSON object")
    schema_version = str(file.get("schema_version") or "").strip()
    if not schema_version:
        # **Never inferred.** A file whose shape is guessed is a file whose fields are guessed.
        raise ValueError("the file names no schema_version, and it must not be guessed")

    meta = file.get("meta") or {}
    raw = file.get("raw") if isinstance(file.get("raw"), dict) else file
    digest = content_hash(file)

    existing = session.execute(
        select(Submission).where(
            Submission.member_id == member_id, Submission.content_hash == digest
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateSubmission(
            f"this member already carries this file, stored {existing.received_at:%Y-%m-%d}. "
            f"Loading it again would double every position it maps to."
        )

    row = Submission(
        member_id=member_id,
        schema_version=schema_version,
        source=str(meta.get("source") or "unknown")[:60],
        collected_on=(str(meta.get("collected"))[:10] if meta.get("collected") else None),
        payload=file,
        content_hash=digest,
        household_code=(str(raw.get("household_code")).strip()[:80]
                        if raw.get("household_code") else None),
        note=note,
    )
    session.add(row)
    session.flush()
    return row


def answers(submission: Submission) -> dict:
    """The answer block, whichever shape the file uses."""
    payload = submission.payload or {}
    raw = payload.get("raw")
    return raw if isinstance(raw, dict) else {k: v for k, v in payload.items() if k != "meta"}


@dataclass(frozen=True)
class Unmapped:
    """One answer the member gave that nothing in the build reads."""

    key: str
    value: object
    #: Why it is unmapped, where the loader said so. `None` means simply that no mapping claimed it.
    reason: str | None = None


def unmapped(submission: Submission) -> list[Unmapped]:
    """Every answer in the file that the mapping did not claim.

    Reads `mapping_report` where the loader wrote one and falls back to "nothing was claimed" where it did
    not — a submission stored but never mapped should report all of its answers as waiting, not none of
    them, because the second reads as "there is nothing here".
    """
    report = submission.mapping_report or {}
    claimed = set(report.get("mapped_keys") or [])
    reasons = report.get("reasons") or {}
    out = []
    for key, value in answers(submission).items():
        if key in claimed:
            continue
        out.append(Unmapped(key=key, value=value, reason=reasons.get(key)))
    return sorted(out, key=lambda u: u.key)


def not_presented(submission: Submission) -> set[str]:
    """The instrument's questions this submission's format never put to the person.

    **The difference between "skipped" and "never asked", and the reason it has to be stored.** A member
    who completes onboarding in the application sees all 21 questions and leaves some blank; a member
    loaded from an interview file was asked whatever that interview asked, which is a different set. Both
    end with `onboarding_completed_at` set and both have unanswered questions, and nothing in the member's
    record afterwards tells the two apart — so `derive` cannot compute this and the loader has to say it.

    Empty for a submission whose loader did not record one, which is the honest reading: a mapping that
    never claimed a question was never asked is indistinguishable, from here, from one that did.
    """
    report = submission.mapping_report or {}
    return set(report.get("not_presented") or ())


def record_mapping(session: Session, submission: Submission, *, mapped_keys, reasons=None,
                   created=None, not_presented=None) -> Submission:
    """Write what the mapping made of this file.

    Separate from `store` because the mapping runs after — and because a submission that was stored and
    never mapped is a real state worth being able to see.

    **`mapped_keys` is in the submission's namespace, not the instrument's**, because `unmapped` subtracts
    it from `answers(submission)` and those are the file's own keys. Passing question keys instead made
    every renamed field — `income_gross` answering `employment_magnitude`, and all five franc stocks —
    report as having no home while the same record said it had created them, 450 times across fifty
    clients. The two namespaces coincide for exactly five names, which is why it read as nearly right.
    """
    submission.mapping_report = {
        "mapped_keys": sorted(set(mapped_keys)),
        "reasons": dict(reasons or {}),
        "created": dict(created or {}),
        "not_presented": sorted(set(not_presented or ())),
    }
    session.add(submission)
    session.flush()
    return submission


def for_member(session: Session, *, member_id: str) -> list[Submission]:
    """Every file this member has handed over, newest first.

    **`id` breaks the tie, and the tie is real.** `received_at` is stored to the second, so two files that
    arrive in the same second have no fact that makes one newer than the other. Ordering by the timestamp
    alone left that to the database, which meant `collect` could read a different file on two consecutive
    calls with nothing having changed — found by a test that stored two files and asked for the newest.

    The id is random, so this does not recover the true order; it makes the answer stable and lets a
    caller that genuinely needs the later of two same-second files say so by giving them different
    `received_at` values. A stable wrong answer is debuggable and an unstable one is not.
    """
    return list(session.execute(
        select(Submission)
        .where(Submission.member_id == member_id)
        .order_by(Submission.received_at.desc(), Submission.id.desc())
    ).scalars())


def by_household_code(session: Session, *, code: str) -> list[Submission]:
    """Every submission carrying this shared code, oldest first.

    The code is a word a member chose and not an identifier this application issued, so this is a lookup
    and never a claim that the rows belong together. Joining them is `services/household_link.py`, and it
    takes consent from both sides.
    """
    cleaned = (code or "").strip()
    if not cleaned:
        return []
    return list(session.execute(
        select(Submission)
        .where(Submission.household_code == cleaned)
        .order_by(Submission.received_at.asc())
    ).scalars())


__all__ = [
    "DuplicateSubmission",
    "Unmapped",
    "answers",
    "by_household_code",
    "content_hash",
    "for_member",
    "record_mapping",
    "store",
    "unmapped",
]
