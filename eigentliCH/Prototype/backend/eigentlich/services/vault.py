"""S-06, the Vault. K3 — the class that never leaves the server and never reaches a log line.

**Four intake paths behind one interface** (R-150). `upload` and `capture` are implemented; `forward` and
`import` raise `IntakeNotImplemented`, because D-04 has not decided which automated path is built first
and a stub that silently accepts would be worse than one that refuses. The interface exists now so that
adding an adapter later is adding an adapter, not rebuilding the vault.

**Nothing is overwritten in place** (R-041). A new version is a new row carrying `supersedes_id`. The
superseded row keeps its bytes, its hash and its extracted fields exactly as they were — which is what
makes an export a history rather than a snapshot, and what makes "what did this policy say in 2027" a
question with an answer.

**Extraction never overwrites a member-entered value** (R-151). Extracted fields live in their own column
with provenance and a confidence on every one. Where a member has stated something and extraction
disagrees, both are kept: a disagreement is two recorded facts, not one corrected one.

**Bytes live beside the database, not in it.** A K3 document in a row makes every incidental query and
every backup carry it. The store is a directory keyed by member and item, and the row carries the hash.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActionItem, VaultItem, utcnow

#: R-150. Declared here so the interface is one list, and the unimplemented ones are visible rather than
#: missing. D-04 decides which of the two automated paths is built first.
IMPLEMENTED_INTAKE = ("upload", "capture", "manual")
DEFERRED_INTAKE = ("forward", "import")


class IntakeNotImplemented(NotImplementedError):
    """D-04. Raised rather than accepting quietly — an intake that pretends to work loses documents."""


class VaultStore:
    """Bytes on disk, addressed by member and item.

    Deliberately not clever: no deduplication across members, no shared content-addressed pool. Two
    members holding the same document is two documents, and a store that noticed would be a store that
    could tell you they both hold it.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, member_id: str, item_id: str) -> Path:
        return self.root / member_id / item_id

    def write(self, member_id: str, item_id: str, data: bytes) -> str:
        target = self.path_for(member_id, item_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def read(self, member_id: str, item_id: str) -> bytes:
        return self.path_for(member_id, item_id).read_bytes()

    def exists(self, member_id: str, item_id: str) -> bool:
        return self.path_for(member_id, item_id).exists()

    def delete_member(self, member_id: str) -> None:
        """Used by R-231's self-service deletion. Removes the bytes; rows are handled by the caller."""
        shutil.rmtree(self.root / member_id, ignore_errors=True)


def store_item(
    session: Session,
    store: VaultStore,
    *,
    member_id: str,
    kind: str,
    title: str,
    source: str,
    data: bytes | None = None,
    expiry_date: date | None = None,
    notes: str | None = None,
    supersedes: VaultItem | None = None,
    extracted_fields: dict | None = None,
) -> VaultItem:
    """Add a vault item, or a new version of one.

    R-153: a member-authored note is stored through this same function with `data=None`. Notes, learning
    and family arrangements are vault items of equal standing, not a lesser kind kept somewhere else.
    """
    if source in DEFERRED_INTAKE:
        raise IntakeNotImplemented(
            f"intake path {source!r} is not built. D-04 has not decided which automated path comes first, "
            f"and an adapter that accepted quietly would lose documents rather than refuse them."
        )
    if source not in IMPLEMENTED_INTAKE:
        raise ValueError(f"unknown intake path {source!r}")

    item = VaultItem(
        member_id=member_id,
        kind=kind,
        title=title,
        source=source,
        stored_at=utcnow(),
        expiry_date=expiry_date,
        notes=notes,
        extracted_fields=extracted_fields,
        # R-041. The new row records what it supersedes; the old row is not touched.
        supersedes_id=supersedes.id if supersedes else None,
        version=(supersedes.version + 1) if supersedes else 1,
    )
    session.add(item)
    session.flush()  # item.id, so the bytes can be addressed

    if data is not None:
        item.content_hash = store.write(member_id, item.id, data)

    # R-152: "expiry dates are first-class and are the PRIMARY SOURCE of action items". Until now nothing
    # made one outside a test, so `/api/actions` was empty in the running application forever and the
    # requirement was satisfied on paper only. Caught by the client agent building the panel that lists
    # them and finding nothing to list.
    #
    # Created at storage time with `due_date = expiry_date`, and NOT gated on a horizon. "Within how many
    # months is an expiry worth surfacing" is a threshold, and a threshold is an assumption nobody has
    # published (C-02). Ordering by due date needs no such number, and `expiring_items` already lets a
    # caller ask the horizon question with a date it supplies itself.
    if expiry_date is not None:
        session.add(action_item_for_expiry(item))

    return item


def current_items(session: Session, *, member_id: str) -> list[VaultItem]:
    """The latest version of each chain. Superseded rows still exist and still export."""
    rows = session.execute(select(VaultItem).where(VaultItem.member_id == member_id)).scalars().all()
    superseded = {row.supersedes_id for row in rows if row.supersedes_id}
    return [row for row in rows if row.id not in superseded]


def history_of(session: Session, item: VaultItem) -> list[VaultItem]:
    """A chain, oldest first. What a document said before it said what it says now."""
    chain = [item]
    seen = {item.id}
    cursor = item
    while cursor.supersedes_id and cursor.supersedes_id not in seen:
        previous = cursor.supersedes
        if previous is None:
            break
        chain.append(previous)
        seen.add(previous.id)
        cursor = previous
    return list(reversed(chain))


def merge_extraction(item: VaultItem, extracted: dict) -> dict:
    """R-151. Extraction never overwrites a member-entered value.

    Every field carries its provenance and a confidence. Where the member has already stated a value, the
    extracted one is recorded ALONGSIDE it as `disagrees_with_member`, never in place of it — a
    disagreement between a person and a reader is two facts, not one correction.
    """
    fields = dict(item.extracted_fields or {})
    for name, proposed in extracted.items():
        existing = fields.get(name)
        if existing and existing.get("provenance") == "member":
            if existing.get("value") != proposed.get("value"):
                existing = dict(existing)
                existing["disagrees_with_extraction"] = proposed
                fields[name] = existing
            continue
        fields[name] = {
            "value": proposed.get("value"),
            "provenance": proposed.get("provenance", "extraction"),
            "confidence": proposed.get("confidence"),
            "extracted_at": utcnow().isoformat(),
        }
    return fields


def state_member_value(item: VaultItem, name: str, value) -> dict:
    """A value the member typed. Outranks extraction permanently."""
    fields = dict(item.extracted_fields or {})
    fields[name] = {"value": value, "provenance": "member", "confidence": None,
                    "stated_at": utcnow().isoformat()}
    item.extracted_fields = fields
    return fields


def expiring_items(
    session: Session, *, member_id: str, on_or_before: date
) -> list[VaultItem]:
    """R-152. Expiry dates are the primary source of action items, so they are queried, not scanned."""
    rows = session.execute(
        select(VaultItem).where(
            VaultItem.member_id == member_id,
            VaultItem.expiry_date.is_not(None),
            VaultItem.expiry_date <= on_or_before,
        )
    ).scalars().all()
    current = {row.id for row in current_items(session, member_id=member_id)}
    # A superseded version's expiry is not news; the current one's is.
    return [row for row in rows if row.id in current]


def action_item_for_expiry(item: VaultItem) -> ActionItem:
    """R-152 into C-06: an action item exists only if it carries the options and their consequences.

    The two options are the two things that actually happen, stated as consequences rather than as verbs.
    Neither is recommended — C-01 — and no figure appears, because a figure would need an assumption set.
    """
    if not item.expiry_date:
        raise ValueError("an expiry action item needs an expiry date")

    return ActionItem(
        member_id=item.member_id,
        trigger_kind="vault_expiry",
        due_date=item.expiry_date,
        source_vault_item_id=item.id,
        prepared_options=[
            {
                "label": "Verlängern",
                "consequence": "Die Deckung läuft weiter. Die Bedingungen können sich geändert haben; "
                               "der Vertrag sagt, welche.",
            },
            {
                "label": "Auslaufen lassen",
                "consequence": "Die Deckung endet am genannten Datum. Danach besteht sie nicht mehr.",
            },
        ],
    )
