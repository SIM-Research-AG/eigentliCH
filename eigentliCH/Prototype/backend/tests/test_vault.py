"""Phase 3, the Vault. Gate: full export round-trips; no overwrite in place.

Also the first real workout for C-04, because `VaultItem` is the only K3 entity and its fields are what
the logging filter exists to drop.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest

from eigentlich.log_filter import REDACTION, TopClassRedactingFilter
from eigentlich.models import ActionItem, VaultItem, utcnow
from eigentlich.services.export import FORMAT_VERSION, export_member, to_json, verify_round_trip
from eigentlich.services.vault import (
    DEFERRED_INTAKE,
    IntakeNotImplemented,
    VaultStore,
    action_item_for_expiry,
    current_items,
    expiring_items,
    history_of,
    merge_extraction,
    state_member_value,
    store_item,
)


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def policy(session, store, member):
    item = store_item(
        session, store,
        member_id=member.id, kind="policy", title="Hausratversicherung Helvetia",
        source="upload", data=b"%PDF-1.4 fake policy bytes",
        expiry_date=date(2027, 3, 31),
    )
    session.commit()
    return item


# ============================================================ R-150 / D-04


@pytest.mark.parametrize("source", DEFERRED_INTAKE)
def test_unbuilt_intake_paths_raise(session, store, member, source):
    """D-04. An adapter that accepted quietly would lose documents rather than refuse them."""
    with pytest.raises(IntakeNotImplemented):
        store_item(session, store, member_id=member.id, kind="policy", title="x", source=source)


@pytest.mark.parametrize("source", ["upload", "capture", "manual"])
def test_built_intake_paths_work(session, store, member, source):
    item = store_item(
        session, store, member_id=member.id, kind="statement", title=f"via {source}", source=source,
        data=b"bytes",
    )
    session.commit()
    assert item.id and item.source == source


def test_a_member_note_is_a_vault_item_of_equal_standing(session, store, member):
    """R-153. Notes, learning and family arrangements are not a lesser kind kept somewhere else."""
    note = store_item(
        session, store, member_id=member.id, kind="note", title="Was wir mit den Eltern besprochen haben",
        source="manual", notes="Mutter möchte im Haus bleiben. Bruder ist einverstanden.",
    )
    session.commit()
    assert note in current_items(session, member_id=member.id)
    assert note.content_hash is None, "a note has no bytes, and that does not make it lesser"


# ============================================================ R-041


def test_a_new_version_does_not_overwrite_the_old(session, store, member, policy):
    """R-041. Nothing is overwritten in place."""
    original_id, original_hash = policy.id, policy.content_hash

    v2 = store_item(
        session, store, member_id=member.id, kind="policy", title="Hausratversicherung Helvetia",
        source="upload", data=b"%PDF-1.4 renewed policy bytes", expiry_date=date(2028, 3, 31),
        supersedes=policy,
    )
    session.commit()

    assert v2.id != original_id
    assert v2.version == 2 and v2.supersedes_id == original_id
    old = session.get(VaultItem, original_id)
    assert old is not None, "the superseded row still exists"
    assert old.content_hash == original_hash, "and its bytes are untouched"
    assert store.read(member.id, original_id) == b"%PDF-1.4 fake policy bytes"


def test_only_the_current_version_is_listed(session, store, member, policy):
    v2 = store_item(session, store, member_id=member.id, kind="policy", title="v2", source="upload",
                    data=b"new", supersedes=policy)
    session.commit()
    current = current_items(session, member_id=member.id)
    assert current == [v2]


def test_history_reads_oldest_first(session, store, member, policy):
    v2 = store_item(session, store, member_id=member.id, kind="policy", title="v2", source="upload",
                    data=b"b", supersedes=policy)
    session.commit()
    v3 = store_item(session, store, member_id=member.id, kind="policy", title="v3", source="upload",
                    data=b"c", supersedes=v2)
    session.commit()
    assert [i.version for i in history_of(session, v3)] == [1, 2, 3]


# ============================================================ R-151


def test_extraction_carries_provenance_and_confidence(session, store, member, policy):
    policy.extracted_fields = merge_extraction(
        policy, {"premium": {"value": 480, "confidence": 0.82}}
    )
    session.commit()
    field = policy.extracted_fields["premium"]
    assert field["value"] == 480
    assert field["provenance"] == "extraction"
    assert field["confidence"] == 0.82
    assert field["extracted_at"]


def test_extraction_never_overwrites_a_member_entered_value(session, store, member, policy):
    """R-151. A disagreement between a person and a reader is two facts, not one correction."""
    state_member_value(policy, "premium", 500)
    session.commit()

    policy.extracted_fields = merge_extraction(
        policy, {"premium": {"value": 480, "confidence": 0.9}}
    )
    session.commit()

    field = policy.extracted_fields["premium"]
    assert field["value"] == 500, "the member's own value stands"
    assert field["provenance"] == "member"
    assert field["disagrees_with_extraction"]["value"] == 480, "and the disagreement is kept, not dropped"


def test_extraction_fills_a_field_the_member_left_alone(session, store, member, policy):
    policy.extracted_fields = merge_extraction(policy, {"insurer": {"value": "Helvetia"}})
    session.commit()
    assert policy.extracted_fields["insurer"]["value"] == "Helvetia"


# ============================================================ R-152 / C-06


def test_expiry_is_queryable_not_scanned(session, store, member, policy):
    found = expiring_items(session, member_id=member.id, on_or_before=date(2027, 12, 31))
    assert policy in found
    assert expiring_items(session, member_id=member.id, on_or_before=date(2026, 1, 1)) == []


def test_a_superseded_versions_expiry_is_not_news(session, store, member, policy):
    store_item(session, store, member_id=member.id, kind="policy", title="v2", source="upload",
               data=b"b", expiry_date=date(2029, 3, 31), supersedes=policy)
    session.commit()
    found = expiring_items(session, member_id=member.id, on_or_before=date(2030, 1, 1))
    assert [i.version for i in found] == [2]


def test_an_expiry_action_item_satisfies_c06(session, store, member, policy):
    """R-152 into C-06: an item exists only if it carries the options AND their consequences."""
    item = action_item_for_expiry(policy)
    session.add(item)
    session.commit()

    assert len(item.prepared_options) >= 2
    assert all(o["label"] and o["consequence"] for o in item.prepared_options)
    assert item.source_vault_item_id == policy.id
    assert item.due_date == policy.expiry_date


def test_the_expiry_options_recommend_nothing(session, store, member, policy):
    """C-01. Neither option is advised, and neither carries a figure — a figure needs an assumption set."""
    item = action_item_for_expiry(policy)
    blob = " ".join(o["consequence"] for o in item.prepared_options).lower()
    for word in ("empfehlen", "sollten", "am besten", "raten wir", "wir empfehlen"):
        assert word not in blob
    assert not any(ch.isdigit() for ch in blob), "a figure here would need a published assumption set"


# ============================================================ C-04, the K3 workout


def test_vault_fields_are_the_ones_the_filter_protects():
    from eigentlich.models import top_class_field_names

    protected = top_class_field_names()
    for field in ("title", "notes", "extracted_fields", "content_hash", "expiry_date"):
        assert field in protected, f"{field} is K3 content and must be dropped from logs"


def test_a_vault_title_never_reaches_a_log_line(caplog, session, store, member, policy):
    """C-04, with a real K3 value rather than a fixture string."""
    logger = logging.getLogger("eigentlich.test.vault")
    filt = TopClassRedactingFilter()
    logger.addFilter(filt)

    with caplog.at_level(logging.INFO, logger="eigentlich.test.vault"):
        logger.info("stored item title=%s member_id=%s", policy.title, member.id)
        logger.info("payload %s", {"title": policy.title, "notes": "etwas Privates"})
    logger.removeFilter(filt)

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "Helvetia" not in joined
    assert "etwas Privates" not in joined
    assert REDACTION in joined
    # member_id is structural and must survive, or a trace cannot be followed at all.
    assert member.id in joined


# ============================================================ R-154, the phase gate


def test_full_export_round_trips(session, store, member, policy):
    """The phase 3 gate."""
    report = verify_round_trip(session, store, member_id=member.id)
    assert report["ok"] is True
    assert report["format"] == FORMAT_VERSION
    assert report["vault_bytes_verify"] is True


def test_the_export_contains_the_vault_bytes(session, store, member, policy):
    import base64

    export = export_member(session, store, member_id=member.id)
    item = export["vault_items"][0]
    assert base64.b64decode(item["content_base64"]) == b"%PDF-1.4 fake policy bytes"


def test_the_export_includes_superseded_versions(session, store, member, policy):
    """R-041 keeps history; an export that dropped it would lose what a document used to say."""
    store_item(session, store, member_id=member.id, kind="policy", title="v2", source="upload",
               data=b"b", supersedes=policy)
    session.commit()
    export = export_member(session, store, member_id=member.id)
    assert len(export["vault_items"]) == 2
    assert {i["version"] for i in export["vault_items"]} == {1, 2}


def test_the_export_carries_every_column(session, store, member, policy):
    """Not a curated subset: a hand-written field list stops exporting a column added later."""
    export = export_member(session, store, member_id=member.id)
    exported = set(export["vault_items"][0])
    for column in VaultItem.__table__.columns.keys():
        assert column in exported, f"{column} is missing from the export"


def test_the_export_is_json_serialisable(session, store, member, policy):
    import json

    assert json.loads(to_json(export_member(session, store, member_id=member.id)))


def test_the_export_names_its_format_and_its_sensitivity(session, store, member, policy):
    export = export_member(session, store, member_id=member.id)
    assert export["format"] == FORMAT_VERSION
    assert "data_class" in export["_about"]["data_classes"]


def test_export_needs_no_permission_parameter(session, store, member, policy):
    """R-154: 'without asking anyone'. There is no approval argument to forget to pass."""
    import inspect

    parameters = set(inspect.signature(export_member).parameters)
    assert parameters == {"session", "store", "member_id"}
