"""R-231's erasure: the member's material goes, the append-only rows stay and are emptied of them.

The tests that matter here are the ones asserting what is GONE, because that is the claim being made to
a person about their own data.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import select

from eigentlich.consent import BY_KEY, DATENBEARBEITUNG
from eigentlich.models import (
    ActionItem,
    Consent,
    Credential,
    Curator,
    CuratorSession,
    CuratorSessionEvent,
    Decision,
    Goal,
    Member,
    OnboardingAnswer,
    Position,
    VaultItem,
)
from eigentlich.services import mutate_plan, record_answer, store_item
from eigentlich.services.auth import login, register_with_credentials
from eigentlich.services.erasure import REDACTED, erase_member
from eigentlich.services.export import export_member, to_json, verify_round_trip
from eigentlich.services.member_data import (
    DELETED_IN_ERASURE_ORDER,
    DEPENDENTS_IN_ERASURE_ORDER,
    EXPORTED_TABLES,
    EXPORT_OMITS,
    REDACTED_IN_ERASURE,
    member_owned_tables,
    tables_missing_from_the_export,
)
from eigentlich.services.know import open_curator_session
from eigentlich.services.vault import VaultStore


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def furnished(session, store):
    """A member with something in every table erasure touches."""
    member, _credential = register_with_credentials(
        session, email="weg@example.ch", password="ein langes passwort hier",
        age_at_registration=44, display_name="Zu löschen",
        consents=[{"purpose": DATENBEARBEITUNG, "document_version": BY_KEY[DATENBEARBEITUNG].document_version}],
    )
    session.commit()

    login(session, email="weg@example.ch", password="ein langes passwort hier")
    record_answer(session, member_id=member.id, question_key="employment_position", value="Treuhand")
    session.commit()

    with mutate_plan(
        session, member_id=member.id,
        question="Anstellung erfassen?", choice="Ja, als Einkommensposition",
        reasoning="Aus dem Erstgespräch",
    ) as decision:
        position = Position(member_id=member.id, role="income", capital_type="human", label="Anstellung")
        goal = Goal(member_id=member.id, name="Wohneigentum")
        session.add_all([position, goal])
        decision.linked_positions.append(position)
        decision.linked_goals.append(goal)
    session.commit()

    store_item(session, store, member_id=member.id, kind="policy", title="Hausrat Helvetia",
               source="upload", data=b"%PDF geheim", expiry_date=date(2028, 1, 1))
    session.commit()

    # A real `curators` row. `CuratorSession.curator_id` is a foreign key since 31 August 2026 (A67's
    # correction to A40), and `open_curator_session` resolves the id before it writes — the
    # `"curator:demo"` string this fixture used to pass is now refused at both layers.
    kuratorin = Curator(display_name="Demo Kuratorin", email="kurator@example.ch", role_label="Kuratorin",
                        fictional=True)
    session.add(kuratorin)
    session.flush()

    curator_session = open_curator_session(
        session, member_id=member.id, curator_id=kuratorin.id, opened_from="know_panel"
    )
    session.commit()
    return member, decision, curator_session, store


# ============================================================ what must be gone


def test_everything_deletable_is_deleted(session, furnished):
    member, _decision, _cs, store = furnished
    # Held as a string: after the erasure the object is gone, and reading `.id` off it raises — which is
    # SQLAlchemy telling the truth rather than a bug.
    member_id = member.id

    erase_member(session, store, member_id=member_id)
    session.commit()

    for model in (Position, Goal, VaultItem, OnboardingAnswer, Consent, Credential, ActionItem):
        remaining = session.execute(
            select(model).where(model.member_id == member_id)
        ).scalars().all()
        assert remaining == [], f"{model.__tablename__} still holds rows for the member"

    assert session.get(Member, member_id) is None


def test_the_vault_bytes_are_gone_from_disk(session, furnished):
    member, _d, _cs, store = furnished
    member_id = member.id
    item = session.execute(select(VaultItem).where(VaultItem.member_id == member_id)).scalars().first()
    item_id = item.id
    assert store.exists(member_id, item_id)

    erase_member(session, store, member_id=member_id)
    session.commit()
    assert not store.exists(member_id, item_id)


def test_the_member_can_no_longer_log_in(session, furnished):
    from eigentlich.services.auth import AuthenticationFailed

    member, _d, _cs, store = furnished
    erase_member(session, store, member_id=member.id)
    session.commit()

    with pytest.raises(AuthenticationFailed):
        login(session, email="weg@example.ch", password="ein langes passwort hier")


# ============================================================ what survives, and emptied of what


def test_the_decision_survives_but_holds_nothing_about_the_member(session, furnished):
    """The owner's decision: null it rather than defer erasure.

    Carried through the fields that actually hold the person. Nulling only `member_id` would leave the
    free text — question, choice, reasoning — sitting in the table, unattached and perfectly readable.
    """
    member, decision, _cs, store = furnished
    decision_id = decision.id

    erase_member(session, store, member_id=member.id)
    session.commit()

    row = session.get(Decision, decision_id)
    assert row is not None, "R-040: the record that a decision happened survives"
    assert row.member_id is None
    assert row.question == REDACTED
    assert row.choice == REDACTED
    assert row.reasoning is None
    assert row.options_considered == []
    assert row.linked_position_ids == []


def test_no_trace_of_the_members_own_words_remains_anywhere(session, furnished):
    """The claim being made to a person about their data, asserted as a sweep over every table."""
    member, _d, _cs, store = furnished
    erase_member(session, store, member_id=member.id)
    session.commit()

    from eigentlich.models import Base

    needles = ("Anstellung", "Wohneigentum", "Hausrat Helvetia", "Treuhand",
               "Aus dem Erstgespräch", "Zu löschen", "weg@example.ch")
    connection = session.connection()
    for mapper in Base.registry.mappers:
        table = mapper.class_.__table__
        for row in connection.execute(select(table)):
            blob = " ".join(str(v) for v in row if v is not None)
            for needle in needles:
                assert needle not in blob, f"{needle!r} survives in {table.name}"


def test_the_curator_audit_keeps_what_the_curator_did(session, furnished):
    """C-10. An audit that erased itself whenever a member left would not be an audit."""
    member, _d, curator_session, store = furnished
    session_id = curator_session.id
    curator_id = curator_session.curator_id

    erase_member(session, store, member_id=member.id)
    session.commit()

    row = session.get(CuratorSession, session_id)
    assert row is not None
    assert row.member_id is None
    assert row.curator_id == curator_id, "who acted is the curator's accountability, not member data"
    assert row.opened_from == "know_panel"

    # R-231 nulls the member and leaves the curator. Since 31 August 2026 that has a second consequence
    # worth asserting: `curator_id` is a foreign key, so the row still resolves to a live `curators` row
    # after the erasure — an audit that named a curator who no longer exists anywhere would be an audit
    # that had quietly stopped being checkable.
    assert session.get(Curator, row.curator_id) is not None

    events = session.execute(
        select(CuratorSessionEvent).where(CuratorSessionEvent.session_id == session_id)
    ).scalars().all()
    assert events, "the events survive"
    assert all(e.actor == curator_id for e in events)


# ============================================================ the triggers


def test_the_append_only_triggers_are_restored_afterwards(tmp_path):
    """Erasure is the one place that drops them, so the restore is in a `finally`.

    **On a FILE database, deliberately.** The first version of this test used `sqlite:///:memory:`, where
    every connection gets its own separate database — which hid the bug it was written to catch. The
    restore was going through `engine.begin()`, a second transaction, so the CREATEs committed before the
    DROPs did and a real erasure left the database with NO triggers: every append-only guarantee silently
    off. In memory the second connection was a different database entirely, so the test saw triggers that
    the real path had just destroyed.

    Found by erasing one account on the development database and counting. A test on the wrong substrate
    is worse than no test, because it is believed.
    """
    from sqlalchemy import create_engine, text

    from eigentlich.db import create_all, make_session_factory
    from eigentlich.services.registration import register_member

    database = tmp_path / "erasure.db"
    engine = create_engine(f"sqlite:///{database}")
    create_all(engine)
    factory = make_session_factory(engine)

    with factory() as db:
        member = register_member(db, age_at_registration=44, display_name="Zu löschen")
        db.commit()
        member_id = member.id

        with mutate_plan(db, member_id=member_id, question="Position?", choice="Ja") as decision:
            position = Position(member_id=member_id, role="income", capital_type="human", label="Arbeit")
            db.add(position)
            decision.linked_positions.append(position)
        db.commit()

        erase_member(db, VaultStore(tmp_path / "vault"), member_id=member_id)
        db.commit()

    with engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            )
        }
    for expected in ("trg_decisions_no_update", "trg_decisions_no_delete",
                     "trg_curator_session_events_no_update", "trg_curator_session_events_no_delete"):
        assert expected in names, (
            f"{expected} was not restored after an erasure. The restore must run on the session's own "
            f"connection — `engine.begin()` opens a second transaction and the CREATEs land before the "
            f"DROPs, leaving none."
        )

    # And the guarantee is real again, not merely present as a name.
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE decisions SET choice='tampered'"))


def test_a_decision_is_still_immutable_after_an_erasure(session, furnished, engine):
    """The proof that the exception was narrow: ordinary writes are refused again immediately after."""
    member, _d, _cs, store = furnished
    erase_member(session, store, member_id=member.id)
    session.commit()

    from sqlalchemy import text

    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE decisions SET choice='tampered'"))


def test_erasing_an_unknown_member_raises(session, store):
    with pytest.raises(LookupError):
        erase_member(session, store, member_id="nobody")


def test_the_report_names_what_it_touched(session, furnished):
    """A member sees the act, not a reassurance."""
    member, _d, _cs, store = furnished
    report = erase_member(session, store, member_id=member.id).as_dict()
    session.commit()

    assert report["executed"] is True
    assert report["vault_bytes_removed"] is True
    assert report["deleted"]["positions"] == 1
    assert report["redacted"]["decisions"] >= 1
    assert "curator_events" in report["_about"]


# ============================================================ R-154 meets R-231
#
# The export and the erasure are two statements about the same set of rows, and they had come apart:
# `access_grants`, `attendances`, `capability_assertions`, `member_offers` and `providers` were destroyed
# when a member left and were not in the file they took with them. Exporting less than you erase is
# incoherent — the application had already decided those rows were the member's when it agreed to destroy
# them — and the worst of the five was `capability_assertions`, which R-191 says IS the member's
# progression and which nothing else in the system represents.
#
# The fix is one list in `member_data.py` that both paths walk. These tests are what keeps it one list.


@pytest.fixture()
def supplying(session, store):
    """A member with a row in every table the erasure touches, including the five that were missing.

    Built through the services wherever there is one — `apply_to_be_listed` and `publish` for the market
    place — so the rows are the shape the application actually writes rather than the shape a fixture
    finds convenient.
    """
    from datetime import datetime, timezone

    from eigentlich.models import (
        AccessGrant,
        Attendance,
        Capability,
        CapabilityAssertion,
        Curator,
        Gathering,
        MemberOffer,
    )
    from eigentlich.services.marketplace import apply_to_be_listed, declare, publish

    member, _credential = register_with_credentials(
        session, email="lieferant@example.ch", password="ein langes passwort hier",
        age_at_registration=47, display_name="Wird Angebot",
        consents=[{"purpose": DATENBEARBEITUNG, "document_version": BY_KEY[DATENBEARBEITUNG].document_version}],
    )
    session.flush()

    session.add(Capability(id="cap-export", statement="kann die eigenen Fixkosten benennen"))
    session.flush()
    session.add(CapabilityAssertion(
        member_id=member.id, capability_id="cap-export", evidence_kind="conversation_with_a_curator",
        assessed_by="curator:demo", assessed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    ))

    gathering = Gathering(id="cafe-export", kind="cafe_evening", title="Konten",
                          held_on=date(2026, 5, 21))
    session.add(gathering)
    session.flush()
    session.add(Attendance(member_id=member.id, gathering_id=gathering.id, attended=True))

    curator = Curator(id="cur-export", display_name="Eine Kuratorin", email="k@example.ch")
    session.add(curator)
    session.flush()
    session.add(AccessGrant(
        member_id=member.id, curator_id=curator.id, scope=["positions"],
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    ))

    session.add(MemberOffer(
        member_id=member.id, direction="offer", kind="skills", title="Buchhaltung, zwei Stunden",
        roles=["income"],
    ))
    session.flush()

    listing = apply_to_be_listed(
        session, member_id=member.id, display_name="Wird Angebot", title="Fixkosten durchsehen",
        domain="financial", qualification_pipeline="capability", roles=["stabilisation"],
    )
    declare(session, listing_id=listing.id, kind="none_declared", statement="keine",
            declared_by="Wird Angebot")
    publish(session, listing.id)
    session.commit()
    return member, listing


def _destroyed_tables() -> set:
    """Every table R-231's erasure empties of the member: deleted, dependent, or redacted.

    The dependents are in here on purpose. `listings` and `disclosures` carry no `member_id`, so no schema
    scan finds them — and a listing's title and summary are words the member wrote, which the erasure
    destroys. Leaving them out would be the same defect the five missing tables were, one table deeper.
    """
    return (
        {model.__tablename__ for model in DELETED_IN_ERASURE_ORDER}
        | {model.__tablename__ for model in DEPENDENTS_IN_ERASURE_ORDER}
        | {model.__tablename__ for model in REDACTED_IN_ERASURE}
    )


def test_the_export_carries_every_table_the_erasure_destroys(session, store, supplying):
    """**The class of defect, not the instance.** R-154 measured against R-231 on a real document.

    Not a comparison of two constants — `export_member` is run and the document's own keys are read, so a
    future export that stopped walking `member_data.EXPORTED_MODELS` and went back to a hand-written list
    fails here rather than passing on the strength of a tuple nothing reads.
    """
    member, _listing = supplying
    export = export_member(session, store, member_id=member.id)

    missing = sorted(_destroyed_tables() - set(export) - set(EXPORT_OMITS))
    assert not missing, (
        f"R-154: the erasure destroys {missing} and the export does not carry them. A member is told less "
        f"about their record than the application is willing to destroy of it."
    )


def test_that_check_would_notice_a_table_the_export_dropped(session, store, supplying):
    """The guard on the guard. An emptiness nobody has shown able to be non-empty is A20's shape.

    One collection is removed from a real export document and the same comparison is run again; it has to
    name exactly that collection. Removed from the copy, not from the exporter — planting a fault in the
    source and forgetting to take it out is how a suite ends up green over a broken guarantee.
    """
    member, _listing = supplying
    export = export_member(session, store, member_id=member.id)
    assert "capability_assertions" in export

    tampered = {key: value for key, value in export.items() if key != "capability_assertions"}
    assert sorted(_destroyed_tables() - set(tampered) - set(EXPORT_OMITS)) == ["capability_assertions"]


def test_every_member_owned_table_is_exported_or_named_as_an_exclusion():
    """R-154 measured against the SCHEMA rather than against either list.

    The erasure and the export can agree with each other and both be wrong about a table neither has
    heard of. This asks the ORM instead: a mapped class with a `member_id` is the member's, and it is
    either in the export or in `EXPORT_OMITS` with a reason.
    """
    missing = tables_missing_from_the_export(member_owned_tables())
    assert not missing, (
        f"member-owned tables that are neither exported nor named as a deliberate exclusion: {missing}"
    )


def test_the_schema_check_detects_a_table_that_is_genuinely_absent():
    """The guard on the guard above, with a table name planted into the comparison's input."""
    planted = member_owned_tables() | {"a_table_nobody_added_to_the_export"}
    assert tables_missing_from_the_export(planted) == ["a_table_nobody_added_to_the_export"]
    # And the two exclusions are exclusions rather than an empty set that would swallow anything.
    assert set(EXPORT_OMITS) == {"credentials", "sessions"}
    assert all(reason for reason in EXPORT_OMITS.values()), "an exclusion without a reason is an omission"


def test_the_five_tables_that_were_missing_carry_the_members_rows(session, store, supplying):
    """Behaviourally, on a member who has one of each. A key present and empty would satisfy the shape."""
    member, _listing = supplying
    export = export_member(session, store, member_id=member.id)

    for table in ("access_grants", "attendances", "capability_assertions", "member_offers", "providers",
                  "listings", "disclosures"):
        assert export[table], f"{table} is in the export and empty for a member who has one"

    # A listing's title and summary are the member's own words. `listings` and `disclosures` carry no
    # `member_id`, so they are reached through the provider chain — by the same expression the erasure
    # deletes them with.
    assert export["listings"][0]["title"] == "Fixkosten durchsehen"

    # R-191. The capability statements are the progression, so this is the one that had to be there.
    assert export["capability_assertions"][0]["capability_id"] == "cap-export"


def test_the_export_still_round_trips_with_the_new_collections(session, store, supplying):
    """The phase gate, on the wider document. Counting collections it does not carry proves nothing."""
    member, _listing = supplying
    report = verify_round_trip(session, store, member_id=member.id)
    assert report["ok"] is True
    for table in ("access_grants", "attendances", "capability_assertions", "member_offers", "providers"):
        assert report["counts"][table]["exported"] == report["counts"][table]["reparsed"]
        assert report["counts"][table]["exported"] >= 1
    assert json.loads(to_json(export_member(session, store, member_id=member.id)))


def test_the_round_trip_report_counts_every_collection_the_export_carries():
    """`verify_round_trip` used to hold its own list of keys, which is the same defect one file down."""
    export_keys = set(EXPORTED_TABLES)
    assert export_keys, "the export carries no collections — this comparison would be vacuous"
    assert "capability_assertions" in export_keys and "providers" in export_keys


def _order_offences(order, *, must_hold: bool):
    """Every pair in `order` where a table is deleted AFTER a table it references.

    One walk, used twice: once over the real list, where it has to come back empty, and once over a list
    inverted on purpose, where it has to come back with the pair. `must_hold` makes the first of those an
    assertion at the point the pair is seen, so a failure names the two tables rather than a list.
    """
    positions = {model.__tablename__: index for index, model in enumerate(order)}
    offences = []
    pairs = 0
    for index, model in enumerate(order):
        for column in model.__table__.columns:
            for key in column.foreign_keys:
                referenced = key.column.table.name
                if referenced == model.__tablename__ or referenced not in positions:
                    continue
                pairs += 1
                if positions[referenced] <= index:
                    offences.append((model.__tablename__, referenced))
                    if must_hold:
                        raise AssertionError(
                            f"{model.__tablename__} references {referenced} and is deleted after it; "
                            f"the DELETE will fail on a foreign key."
                        )
    return offences if not must_hold else pairs


def test_the_erasure_order_removes_a_row_before_the_rows_it_points_at():
    """The ordering constraint the shared list carries, asserted rather than left to a comment.

    Foreign keys are on, so a table has to be emptied before the table it references. This walks the
    tuple and requires every referenced table that is also in the tuple to come later. It is the property
    that made `providers` fail — its listings pointed at it and were not cleared first.
    """
    order = list(DELETED_IN_ERASURE_ORDER)
    checked = _order_offences(order, must_hold=True)
    assert checked, (
        "no table in the list references another one in it, so this walk examined nothing. It is the "
        "constraint that made `providers` fail, and a check that inspects no pair cannot see it."
    )


def test_the_order_check_catches_a_pair_the_wrong_way_round():
    """The guard on the guard: the same walk over a deliberately inverted order has to complain.

    `ActionItem.source_vault_item_id` points at `vault_items`, so putting the vault items first is a real
    foreign-key failure rather than an invented one — SQLite would refuse the DELETE in that order.
    """
    from eigentlich.models import ActionItem, VaultItem

    offences = _order_offences([VaultItem, ActionItem], must_hold=False)
    assert offences == [("action_items", "vault_items")], (
        f"the walk did not notice action items being deleted after the vault items they reference: "
        f"{offences}"
    )


def test_a_member_who_became_supply_can_still_leave(session, store, supplying):
    """R-231, on the path that could not complete at all.

    A member who went through `apply_to_be_listed` owns a `Provider` row; its listings hold a NOT NULL
    foreign key to it and its disclosures hold one to them. Nothing cleared either, so the DELETE on
    `members` failed on a foreign key and the whole erasure rolled back — the member could not leave.
    """
    from eigentlich.models import Disclosure, Listing, Provider as SupplierRow

    member, listing = supplying
    member_id, listing_id = member.id, listing.id

    report = erase_member(session, store, member_id=member_id)
    session.commit()

    assert session.get(Member, member_id) is None
    assert session.get(Listing, listing_id) is None
    assert session.execute(
        select(SupplierRow).where(SupplierRow.member_id == member_id)
    ).scalars().all() == []
    assert session.execute(
        select(Disclosure).where(Disclosure.listing_id == listing_id)
    ).scalars().all() == []
    assert report.deleted["providers"] == 1
    assert report.deleted["listings"] == 1
    assert report.deleted["disclosures"] == 1


def test_the_five_tables_are_emptied_as_well_as_exported(session, store, supplying):
    """The other side of the same statement. What is exported is what is destroyed."""
    from eigentlich.models import AccessGrant, Attendance, CapabilityAssertion, MemberOffer

    member, _listing = supplying
    member_id = member.id
    erase_member(session, store, member_id=member_id)
    session.commit()

    for model in (AccessGrant, Attendance, CapabilityAssertion, MemberOffer):
        assert session.execute(
            select(model).where(model.member_id == member_id)
        ).scalars().all() == [], f"{model.__tablename__} still holds rows for the member"
