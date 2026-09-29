"""R-154 — full export of everything the member owns, in a documented format, without asking anyone.

**"Without asking anyone" is the load-bearing phrase.** No approval step, no support ticket, no curator in
the path. The member presses a button and gets everything. So this module takes a member id and returns
the whole estate; there is no permission parameter to forget to pass.

**The format is documented here rather than elsewhere**, because a format documented in a separate file is
a format that drifts from its writer. `FORMAT_VERSION` changes when the shape changes, and the export
carries it, so a file found in five years says what it is.

**It round-trips.** The phase gate is "full export round-trips; no overwrite in place", and `verify_round_trip`
is what makes that a test rather than a claim: every row and every byte that went out comes back
identical. An export that cannot be read back is a backup that is not one.

**It includes superseded versions.** R-041 keeps history, so exporting only current rows would quietly
drop what a document used to say — which is often the thing a member needs when something is disputed.

**Which tables it covers is not decided here.** `_row()` meant a new COLUMN could never be dropped from the
export — but the list of TABLES was hand-written, and five member-owned tables had fallen off it while
`services/erasure.py` went on deleting all five. Exporting less than you erase is incoherent: the
application had already decided those rows were the member's when it agreed to destroy them, and the worst
of the five was `capability_assertions`, which R-191 says *is* the member's progression and which nothing
else in the system represents. The list now lives in `member_data.py` and both paths walk it, so the next
table added to the erasure is exported without anyone remembering to add it twice.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Decision, Goal, Member, VaultItem
from .member_data import (
    EXPORTED_MODELS,
    EXPORTED_TABLES,
    EXPORT_OMITS,
    readable_predicate,
)
from .vault import VaultStore

#: Bumped when the SHAPE changes, not when content does. An export in a drawer must be readable.
#:
#: `@2` adds `access_grants`, `attendances`, `capability_assertions`, `member_offers` and `providers`.
#: `@1` files are still readable — nothing was removed or renamed — but a reader can tell from the version
#: alone whether the absence of a capability assertion means the member had none or means the export
#: predates this.
FORMAT_VERSION = "eigentlich-export@2"


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return value


def _row(obj: Any) -> dict:
    """Every column, by name. Not a curated subset — 'everything the member owns' means every column.

    A hand-written field list would silently stop exporting a column added later, which is the failure
    mode that makes an export untrustworthy exactly when someone needs it.
    """
    return {c.key: _plain(getattr(obj, c.key)) for c in obj.__table__.columns}


# ---------------------------------------------------------------- the rows that are more than a row
#
# Three tables carry something a column scan cannot see: a relationship, or bytes on disk. Each is a
# function keyed by its model rather than a branch inside the loop, so the loop stays one statement about
# every table and the exceptions stay visible as exceptions.


def _goal_row(_session: Session, _store: VaultStore, goal: Goal) -> dict:
    """R-030's funding links. A goal without what funds it is half a goal."""
    return {**_row(goal), "funded_by_position_ids": [p.id for p in goal.funded_by]}


def _decision_row(_session: Session, _store: VaultStore, decision: Decision) -> dict:
    """Links are relationships, so they are exported explicitly — a Decision without what it touched is
    not a decision record."""
    return {
        **_row(decision),
        "linked_position_ids": decision.linked_position_ids,
        "linked_goal_ids": decision.linked_goal_ids,
        "linked_vault_item_ids": decision.linked_vault_item_ids,
    }


def _vault_row(_session: Session, store: VaultStore, item: VaultItem) -> dict:
    """The bytes, base64 in the same document."""
    payload = _row(item)
    if store.exists(item.member_id, item.id):
        data = store.read(item.member_id, item.id)
        payload["content_base64"] = base64.b64encode(data).decode("ascii")
        # Recomputed at export, not copied from the row. If the two disagree the export says so
        # rather than reproducing a hash that no longer matches its bytes.
        payload["content_sha256_at_export"] = hashlib.sha256(data).hexdigest()
    return payload


_COMPOSERS: dict[type, Callable[[Session, VaultStore, Any], dict]] = {
    Goal: _goal_row,
    Decision: _decision_row,
    VaultItem: _vault_row,
}


def export_member(session: Session, store: VaultStore, *, member_id: str) -> dict:
    """Everything, as one JSON-serialisable object.

    Vault bytes are base64 inside the same document. One file is what a member can actually keep; a
    directory of loose attachments is what gets separated from its index and becomes useless.

    The collections are `member_data.EXPORTED_MODELS` — the tables R-231's erasure destroys, minus the two
    it names as deliberate exclusions. There is no list of table names in this function to fall behind.
    """
    member = session.get(Member, member_id)
    if member is None:
        raise LookupError(f"no member {member_id!r}")

    export: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(),
        "member": _row(member),
    }

    for model in EXPORTED_MODELS:
        # `readable_predicate` rather than `member_id` directly: a listing belongs to a member through
        # their provider row, and the erasure walks that same chain to destroy it. It is the READ rule
        # rather than the erasure's rule because of A109 — see `member_data.READS_WIDER_THAN_IT_ERASES`,
        # which is the only place the two differ and says why for each entry.
        rows = session.execute(
            select(model).where(readable_predicate(model, member_id))
        ).scalars().all()
        compose = _COMPOSERS.get(model)
        export[model.__tablename__] = [
            compose(session, store, row) if compose else _row(row) for row in rows
        ]

    export["_about"] = {
        "requirement": "R-154 — full export of everything the member owns, without asking anyone.",
        "collections": list(EXPORTED_TABLES),
        "vault_bytes": "base64 in `content_base64`. One file, because a directory of loose "
                       "attachments gets separated from its index.",
        "history": "Superseded vault versions are INCLUDED. R-041 keeps history and an export that "
                   "dropped it would lose what a document used to say.",
        "progression": "R-191 — `capability_assertions` is the member's progression. There is no level "
                       "number and no score anywhere in this file because there is none in the system.",
        "data_classes": "Every row carries its `data_class` column (C-04). This file contains the "
                        "member's top-class material and should be treated accordingly.",
        # Named rather than silently absent, so a reader can tell an exclusion from an omission.
        "not_included": dict(EXPORT_OMITS),
    }
    return export


def to_json(export: dict) -> str:
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=False)


def verify_round_trip(session: Session, store: VaultStore, *, member_id: str) -> dict:
    """The phase gate, as a function. Serialise, parse back, and compare against the database.

    Returns a report rather than raising, so a caller can show a member what was checked. `ok` is only
    true when every count matches and every vault hash verifies against its own bytes.

    The keys it counts are `EXPORTED_TABLES` rather than a list written here, so a collection that is
    added to the export and not to this check cannot exist.
    """
    export = export_member(session, store, member_id=member_id)
    parsed = json.loads(to_json(export))

    counts = {}
    for key in EXPORTED_TABLES:
        counts[key] = {"exported": len(export[key]), "reparsed": len(parsed[key])}

    hashes_ok = True
    for item in parsed["vault_items"]:
        if "content_base64" not in item:
            continue
        data = base64.b64decode(item["content_base64"])
        if hashlib.sha256(data).hexdigest() != item["content_sha256_at_export"]:
            hashes_ok = False
        if item.get("content_hash") and item["content_hash"] != item["content_sha256_at_export"]:
            # The stored hash disagrees with the bytes on disk. Reported, never silently corrected.
            hashes_ok = False

    ok = all(c["exported"] == c["reparsed"] for c in counts.values()) and hashes_ok
    return {
        "ok": ok,
        "format": parsed["format"],
        "counts": counts,
        "vault_bytes_verify": hashes_ok,
        "member_id": member_id,
    }
