"""S-11: C-08, R-004, R-005, R-200 to R-205, NG-04 and A41.

**C-08 is the phase gate**, and it is the kind of constraint that passes when it is broken: an ordering
that never reads a fee and an ordering that reads one it happens not to have been given look identical
from outside. So `test_listing_ranking_cannot_read_fee_fields` is written in two halves that fail for
different reasons — a structural half that reads the ordering functions' own source and a behavioural
half that moves real money through `Provider` and asserts nothing moves — and each half carries a guard
that it can still fail.

**The word filters are imported rather than re-listed.** `_whole_words`, `_all_strings` and the
gamification vocabulary live in `test_content.py`; `_code_only` and `ACCREDITATION_WORDS` in
`test_learning.py`, together with the note explaining why substring matching produced three false
positives — `hut` inside "Schutz", `peak` inside "peaks in contraction", `level` inside "leverage", and
`rank` inside "Franken", which is the one this module would have tripped over first.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from eigentlich.api.marketplace import get_session, router
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.content import CONTENT, LANGUAGES
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import (
    Attendance,
    Base,
    Capability,
    CapabilityAssertion,
    DOMAINS,
    Disclosure,
    Gathering,
    Listing,
    MemberOffer,
    PIPELINES,
    Position,
    Provider,
    ROLES,
)
from eigentlich.services import register_member
from eigentlich.services.learning import record_assertion
from eigentlich.services.learning import seed as seed_learning
from eigentlich.services.marketplace import (
    ENTRY_KINDS,
    FILTER_PARAMETER,
    InsufficientCapabilityEvidence,
    MissingRegistration,
    NO_FILTER,
    NotMarkedFictional,
    ORDERING_FUNCTIONS,
    ORDERING_INPUT_NAMES,
    ROLE_MATCH_SCALE,
    OrderingInputs,
    PIPELINE_FOR_DOMAIN,
    PipelineMismatch,
    QUALIFICATION_CLAIM,
    UndisclosedListing,
    UnknownListing,
    UnknownRole,
    apply_to_be_listed,
    browse,
    contact_details,
    content_is_fictional,
    declare,
    listing_detail,
    listing_ordering_inputs,
    member_standing,
    ordering_key,
    role_match_share,
    publish,
    required_pipeline,
    role_index,
    seed,
    seed_disclosures,
    seed_listings,
    seed_member_offers,
    seed_providers,
)

# The authorities for the word filters and the source stripper. See this module's docstring.
from test_content import (  # noqa: E402 - sibling test modules, on the path via pytest's rootdir
    GAMIFICATION_WORDS,
    MOUNTAIN_WORDS_DE,
    MOUNTAIN_WORDS_EN,
    _all_strings,
    _whole_words,
)
from test_learning import ACCREDITATION_WORDS, _code_only  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
SERVICE = BACKEND / "eigentlich" / "services" / "marketplace.py"
API = BACKEND / "eigentlich" / "api" / "marketplace.py"
SOURCES = [SERVICE, API]
MARKETPLACE_FILE = CONTENT / "marketplace.json"

#: C-08's own vocabulary. Whatever a bought position would be called when somebody adds one.
COMMERCIAL_WORDS = (
    "paid_placement",
    "paidplacement",
    "placement",
    "boost",
    "boosted",
    "sponsor",
    "sponsored",
    "sponsorship",
    "priority",
    "promoted",
    "featured",
    "highlighted",
    "bezahlt",
    "gesponsert",
)

#: What the ordering may not name. `Provider` is the table the fee columns live on, so naming it at all
#: inside an ordering function is the offence — not only naming a fee.
FEE_FIELDS = tuple(name for name in Provider.__table__.columns.keys() if name.startswith("billing"))

FORBIDDEN_IN_ORDERING = frozenset(
    {"Provider", "provider", "providers", "provider_id", "billing", "fee", "fees", "gebuehr", "preis"}
    | set(FEE_FIELDS)
    | set(COMMERCIAL_WORDS)
)

#: The only tables an ordering function may name. `Provider` is deliberately absent, and the guard below
#: asserts it is a real model so that this allowlist cannot pass by naming nothing.
ORDERING_MAY_READ = frozenset({"Listing", "MemberOffer", "CapabilityAssertion", "Attendance"})

MODEL_NAMES = frozenset(mapper.class_.__name__ for mapper in Base.registry.mappers)


def _models_the_service_imports() -> frozenset[str]:
    """Which model classes `services/marketplace.py` pulls in by name.

    Matched against the module's own `from ..models import ...` rather than against every mapped class,
    because the model layer has an auth `Session` table whose name collides exactly with SQLAlchemy's
    `Session` — the type every service annotates its first argument with. A name-based scan cannot tell
    those two apart, and reading the import list can: `Provider` is in it and `Session` is not, which is
    the distinction the allowlist below actually cares about.
    """
    for node in ast.walk(_module_tree(SERVICE)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("models"):
            return frozenset(alias.name for alias in node.names) & MODEL_NAMES
    raise AssertionError("services/marketplace.py imports no models — the scan below would see nothing")


def _content() -> dict:
    return json.loads(MARKETPLACE_FILE.read_text(encoding="utf-8"))


def _seed_copy() -> str:
    """Every member-facing string in the seed content, lowercased.

    `_about` is excluded by `_all_strings`: it is a note to implementers, and it has to be able to name
    the words it forbids.
    """
    return " ".join(_all_strings(_content())).lower()


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(name: str, path: Path = SERVICE) -> ast.FunctionDef:
    for node in ast.walk(_module_tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path.name} defines no function {name!r}")


def _names_in(node: ast.AST) -> list[str]:
    """Every identifier, attribute, argument, keyword and string literal in one subtree.

    String literals are included because a payload key and an ORM attribute fetched by name are both
    strings, and a filter that only reads identifiers misses `getattr(row, "billing_fee_chf")`.
    """
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.append(child.id)
        elif isinstance(child, ast.Attribute):
            found.append(child.attr)
        elif isinstance(child, ast.arg):
            found.append(child.arg)
        elif isinstance(child, ast.keyword) and child.arg:
            found.append(child.arg)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append(child.name)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append(child.value)
    return found


def _without_docstring(node: ast.FunctionDef) -> ast.FunctionDef:
    """The function body with its docstring removed, so a docstring quoting C-08 does not trip it."""
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:] or [ast.Pass()]
    stripped = ast.FunctionDef(
        name=node.name, args=node.args, body=body, decorator_list=[], returns=None, type_params=[]
    )
    return ast.fix_missing_locations(stripped)


# ============================================================ fixtures


@pytest.fixture()
def offer_member(session):
    """Whose member offers the seed data belongs to (R-205).

    Given **one** capability assertion and **one** attendance, deliberately. That puts the seeded offers
    in the middle of the ordered list rather than at either end, which is what
    `test_member_offers_are_not_a_block_below_the_listings` needs in order to be able to fail.
    """
    member = register_member(session, age_at_registration=52, display_name="Offer Member")
    seed_learning(session)
    session.flush()
    record_assertion(
        session,
        member_id=member.id,
        capability_id="eigene_verbindungen_offenlegen",
        evidence_kind="conversation_with_a_curator",
        assessed_by="curator:demo",
        assessed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    gathering = Gathering(
        id="cafe_2026_05_konten", kind="cafe_evening", title="Konten, die liegen bleiben",
        held_on=date(2026, 5, 21), fictional=True,
    )
    session.add(gathering)
    session.flush()
    session.add(Attendance(member_id=member.id, gathering_id=gathering.id, attended=True))
    session.commit()
    return member


@pytest.fixture()
def seeded(session, offer_member):
    seed(session, member_id=offer_member.id)
    session.commit()
    return session


@pytest.fixture()
def browser(session):
    """A member who browses and has done no learning at all. R-004's subject."""
    member = register_member(session, age_at_registration=29, display_name="Browsing Member")
    session.commit()
    return member


@pytest.fixture()
def api(fast_kdf):
    """The router on its own app, with a seeded database. Yields `(client, member_id)`.

    Deliberately not `eigentlich.api.main.app`: main.py is wired by hand, this router is not in it yet, and
    importing it here would open the real database file to prove something about a payload.

    **Its own engine, with `StaticPool`.** `TestClient` serves the request on a worker thread, and
    SQLAlchemy gives an in-memory SQLite database one connection per thread — so the request would find an
    empty schema without the single pinned connection.

    **Authenticated.** A11 was wired on 31 August 2026: `member_id` is no longer a query parameter or a
    body field on any member route, so this fixture registers a credential, logs in, and gives the client
    a default bearer header. `session_overrides` covers `api.auth.get_session` as well as this router's —
    not optional, because the token is resolved through that one and overriding only the router's would
    authenticate against the developer's real database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    with make_session_factory(engine)() as api_session:
        member, _ = register_with_credentials(
            api_session,
            email="router@example.ch",
            password="ein ziemlich langes passwort",
            age_at_registration=44,
            display_name="Router Member",
        )
        seed_learning(api_session)
        api_session.flush()
        seed(api_session, member_id=member.id)
        api_session.commit()
        _, token = login(
            api_session, email="router@example.ch", password="ein ziemlich langes passwort"
        )
        api_session.commit()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        with TestClient(app) as test_client:
            test_client.headers["Authorization"] = f"Bearer {token}"
            yield test_client, member.id
    engine.dispose()


def _ids(payload: dict, kind: str | None = None) -> list[str]:
    return [e["id"] for e in payload["entries"] if kind is None or e["entry_kind"] == kind]


# ============================================================ C-08 — ordering cannot be bought


def test_listing_ranking_cannot_read_fee_fields(seeded):
    """C-08. The acceptance check the build spec names, in the two halves it has to have.

    **Half one, structurally.** Every function in `ORDERING_FUNCTIONS` is read from source with its
    docstring stripped, and none of them may name `Provider`, a `billing_*` column, or any word a bought
    position would go by. A fee is only reachable from an ordering function through the provider row, so
    forbidding the table forbids the field and every future field like it.

    **Half two, behaviourally.** Real fees are written onto the providers of the first and last provider
    listings, in one arrangement and then the opposite one, and the order is asserted unchanged both
    times. The structural half would pass on an ordering that read a fee through a variable named
    something innocent; this one would not.
    """
    # -- half one: the ordering functions' own source ---------------------------------------------
    assert FEE_FIELDS, "Provider carries no billing column — this test would be scanning for nothing"

    offences: list[str] = []
    for name in ORDERING_FUNCTIONS:
        node = _without_docstring(_function(name))
        for used in _names_in(node):
            if used.lower().lstrip("_") in FORBIDDEN_IN_ORDERING:
                offences.append(f"{name}: {used}")
    assert not offences, (
        "C-08: an ordering function reaches for something commercial. Fee fields exist on Provider for "
        "billing and must not be readable by the ranking function. Found: " + "; ".join(offences)
    )

    # And the tables it may read are an allowlist that Provider is not on. Without this, a rename of
    # `billing_fee_chf` would slip past the word list above.
    available = _models_the_service_imports()
    assert "Provider" in available, "the service does not import Provider — the allowlist proves nothing"
    for name in ORDERING_FUNCTIONS:
        node = _without_docstring(_function(name))
        tables = {used for used in _names_in(node) if used in available}
        assert tables <= ORDERING_MAY_READ, (
            f"C-08: {name} reads {sorted(tables - ORDERING_MAY_READ)}, which is outside the tables the "
            f"ordering may see."
        )

    # -- half two: money on the table, and nothing moves -------------------------------------------
    before = _ids(browse(seeded, roles=NO_FILTER))
    listings = _ids(browse(seeded, roles=NO_FILTER), kind="provider_listing")
    assert len(listings) >= 8, f"only {len(listings)} listings to order — nothing to prove"

    first = seeded.get(Listing, listings[0])
    last = seeded.get(Listing, listings[-1])
    assert first.provider_id != last.provider_id, "the two ends share a provider; pick a wider seed"

    def pay(listing: Listing, amount: float | None, plan: str | None) -> None:
        supplier = seeded.get(Provider, listing.provider_id)
        supplier.billing_fee_chf = amount
        supplier.billing_plan = plan

    # The listing at the bottom pays the most it can; the one at the top pays nothing.
    pay(last, 24000.0, "the_most_expensive_thing_we_sell")
    pay(first, None, None)
    seeded.commit()
    assert seeded.get(Provider, last.provider_id).billing_fee_chf == 24000.0, (
        "the fee was not actually written — this half would pass on an empty database"
    )
    # And the fees written are enough to have moved something, so "unchanged" is a result rather than an
    # arithmetic accident. This is what an ordering that read them would have returned.
    if_it_read_the_fee = sorted(
        listings,
        key=lambda listing_id: (
            -(seeded.get(Provider, seeded.get(Listing, listing_id).provider_id).billing_fee_chf or 0),
            listing_id,
        ),
    )
    assert if_it_read_the_fee != listings, "the fees are too flat to reorder anything"

    assert _ids(browse(seeded, roles=NO_FILTER)) == before, "C-08: paying moved a listing up"

    # And the opposite arrangement, so the test cannot pass because the order is simply insensitive to
    # everything on one particular row.
    pay(last, None, None)
    pay(first, 24000.0, "the_most_expensive_thing_we_sell")
    seeded.commit()
    assert _ids(browse(seeded, roles=NO_FILTER)) == before, "C-08: paying moved a listing down"


def test_the_ordering_does_move_when_a_permitted_input_moves(seeded):
    """The guard on the half above. An order that never changes proves nothing about what it ignores.

    R-203's inputs are the ones that may move it, so one of them is moved here and the order is asserted
    to follow. Without this, `browse` could return a constant and C-08 would look enforced.
    """
    before = _ids(browse(seeded, roles=NO_FILTER), kind="provider_listing")
    bottom = seeded.get(Listing, before[-1])
    # A new dict, not a mutation: SQLAlchemy does not track in-place changes to a JSON column, and a
    # silent no-op here would make this guard vacuous in exactly the way it exists to prevent.
    bottom.standing_inputs = {
        "capability_evidence": ["a", "b", "c", "d", "e", "f"],
        "community_presence": ["g", "h", "i", "j"],
    }
    seeded.commit()
    after = _ids(browse(seeded, roles=NO_FILTER), kind="provider_listing")
    assert after[0] == bottom.id, "capability evidence is supposed to be an ordering input (R-203)"
    assert after != before


def test_browse_accepts_no_commercial_parameter():
    """C-08, at the signature. A boost parameter arrives as an argument before it arrives as a column."""
    parameters = set(inspect.signature(browse).parameters)
    assert parameters == {"session", "member_id", "roles", "domain", "language"}, (
        f"C-08: browse's parameters have changed to {sorted(parameters)}. The listing query accepts no "
        f"paid-placement, boost, sponsor or priority parameter."
    )
    assert not any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in inspect.signature(browse).parameters.values()
    ), "a **kwargs on browse is a door a commercial parameter walks through without being written down"


def test_an_unknown_browse_parameter_is_refused(seeded):
    """Not ignored. An ignored parameter is one a client can be told is supported."""
    with pytest.raises(TypeError):
        browse(seeded, boost=1)


def test_the_ordering_key_is_handed_three_integers_and_nothing_else():
    """C-08 structurally: there is no row in scope, so there is no fee in scope."""
    assert [f for f in OrderingInputs.__dataclass_fields__] == [
        *ORDERING_INPUT_NAMES,
        "tiebreak",
    ]
    assert list(inspect.signature(ordering_key).parameters) == ["inputs"]
    # It is a pure function of its argument: same inputs, same key, no session anywhere near it.
    one = OrderingInputs(role_match=2, capability_evidence=1, community_presence=0, tiebreak="a")
    assert ordering_key(one) == ordering_key(one)
    two = OrderingInputs(role_match=1, capability_evidence=9, community_presence=9, tiebreak="a")
    assert ordering_key(one) < ordering_key(two) or ordering_key(one) > ordering_key(two)


def test_role_match_outranks_the_other_two_inputs():
    """R-203 names three inputs; this pins which of them dominates, so a reordering is a visible change."""
    matched = OrderingInputs(role_match=1, capability_evidence=0, community_presence=0, tiebreak="z")
    evidenced = OrderingInputs(role_match=0, capability_evidence=9, community_presence=9, tiebreak="a")
    assert ordering_key(matched) < ordering_key(evidenced)


def test_the_module_sorts_in_exactly_one_place_and_uses_the_ordering_key():
    """`ORDERING_FUNCTIONS` is only a complete list if nothing else decides order.

    A second `sorted(..., key=...)` somewhere in this module would be an ordering the scan above never
    reads. Keyless sorts are left alone — `sorted(set(...))` for a stable list of references is not an
    ordering of supply.
    """
    keyed = [
        node
        for node in ast.walk(_module_tree(SERVICE))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "sorted")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "sort")
        )
        and any(kw.arg == "key" for kw in node.keywords)
    ]
    assert len(keyed) == 1, f"expected one ordered sort in {SERVICE.name}, found {len(keyed)}"
    assert "ordering_key" in _names_in(keyed[0]), "the one sort does not use ordering_key"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_commercial_vocabulary_in_the_phase_seven_source(path):
    """C-08 over the whole module, with comments and docstrings stripped so they may quote it."""
    found = _whole_words(COMMERCIAL_WORDS, _code_only(path))
    assert not found, f"C-08: {path.name} has grown a commercial signal: {found}"


def test_the_commercial_filter_is_not_vacuous():
    """It would pass silently on an empty vocabulary or a broken pattern."""
    assert _whole_words(COMMERCIAL_WORDS, "a sponsored placement with priority") == [
        "placement",
        "sponsored",
        "priority",
    ]
    assert _whole_words(COMMERCIAL_WORDS, "in franken pro jahr") == []


def test_the_fee_scan_catches_an_ordering_that_reads_one():
    """The guard on half one, and the reason it is a test rather than a comment.

    A scan that forbids words nobody writes passes for ever. So the scan is run here against a function
    that does exactly what C-08 forbids — reaches through the listing to its provider's fee — and it has
    to find it. Three shapes, because the third is the one a word list on its own would miss.
    """
    shapes = {
        "attribute": "def f(listing, roles):\n"
                     "    return listing.provider.billing_fee_chf\n",
        "query": "def f(session, listing, roles):\n"
                 "    return session.get(Provider, listing.provider_id)\n",
        "by_name": "def f(listing, roles):\n"
                   "    return getattr(listing, 'billing_fee_chf')\n",
    }
    for shape, source in shapes.items():
        node = _without_docstring(ast.parse(source).body[0])
        caught = [
            used for used in _names_in(node) if used.lower().lstrip("_") in FORBIDDEN_IN_ORDERING
        ]
        assert caught, f"C-08: the scan would not catch a fee read as {shape}"


def test_the_source_scanner_actually_reads_the_ordering_functions():
    """A guard on half one. A misspelled name in `ORDERING_FUNCTIONS` would scan nothing, silently."""
    assert len(ORDERING_FUNCTIONS) >= 4
    for name in ORDERING_FUNCTIONS:
        node = _without_docstring(_function(name))
        assert len(_names_in(node)) > 3, f"{name} unparsed to almost nothing — the scanner is broken"
    # And the filter fires on the thing it is looking for.
    assert "billing_fee_chf" in FORBIDDEN_IN_ORDERING
    assert "Provider" in MODEL_NAMES and "Provider" not in ORDERING_MAY_READ


def test_the_seed_data_leaves_the_billing_fields_unset(seeded):
    """A41 meets C-08. Demonstration supply that carried a fee is a screenshot of a bought market."""
    for supplier in seeded.execute(select(Provider)).scalars().all():
        assert supplier.billing_plan is None
        assert supplier.billing_fee_chf is None


def test_no_payload_carries_a_commercial_field(seeded, browser):
    blob = json.dumps(
        [
            browse(seeded, member_id=browser.id, roles=NO_FILTER),
            role_index(seeded),
            listing_detail(seeded, "fzk_kostenrechnung"),
        ],
        default=str,
    ).lower()
    found = _whole_words(COMMERCIAL_WORDS + FEE_FIELDS, blob)
    assert not found, f"C-08: an S-11 payload carries {found}"


def test_the_payload_says_the_ordering_is_not_for_sale(seeded):
    """Explicit rather than inferred from an absent key, the way `illustration_unavailable_reason` is."""
    payload = browse(seeded, roles=NO_FILTER)
    assert payload["ordering_inputs"] == list(ORDERING_INPUT_NAMES)
    assert payload["ordering_is_not_purchasable"] is True


# ============================================================ R-200 — indexed by role


def test_every_seeded_listing_is_indexed_by_role():
    """R-200. By the four roles, not by profession."""
    for record in seed_listings():
        assert record["roles"], f"{record['key']} is indexed by nothing"
        unknown = [role for role in record["roles"] if role not in ROLES]
        assert not unknown, f"{record['key']} names roles that do not exist: {unknown}"


def test_a_provider_appears_under_more_than_one_role(seeded):
    """R-200, said exactly. One supplier, several roles — through one listing or through two."""
    index = role_index(seeded)
    appearances: dict[str, set[str]] = {}
    for bucket in index["roles"]:
        for entry in bucket["entries"]:
            if entry["entry_kind"] != "provider_listing":
                continue
            appearances.setdefault(entry["supplier"]["id"], set()).add(bucket["key"])
    several = {key: roles for key, roles in appearances.items() if len(roles) > 1}
    assert several, "no supplier appears under more than one role, so R-200's 'may' is untested"


def test_the_role_index_covers_all_four_roles(seeded):
    index = role_index(seeded)
    assert [bucket["key"] for bucket in index["roles"]] == list(ROLES)
    assert index["indexed_by"] == "role"
    assert index["not_indexed_by_profession"] is True


def test_no_payload_indexes_by_profession(seeded):
    """R-200's other half. The word is the thing a screen gets designed around."""
    blob = json.dumps(role_index(seeded), default=str).lower()
    found = _whole_words(("profession", "professions", "beruf", "berufe", "branche"), blob)
    assert not found, f"R-200: the index has grown a profession dimension: {found}"


def test_a_role_bucket_matches_the_same_filter_applied_directly(seeded):
    index = role_index(seeded)
    for bucket in index["roles"]:
        direct = browse(seeded, roles=[bucket["key"]])
        assert [e["id"] for e in bucket["entries"]] == _ids(direct)


def test_an_unknown_role_is_refused(seeded):
    with pytest.raises(UnknownRole):
        browse(seeded, roles=["treuhaenderin"])


# ============================================================ R-201 — visible, removable pre-filter


@pytest.fixture()
def member_with_grid(session, member):
    """Two filled cells. R-020: the grid is useful at n=1, so two is already more than the minimum."""
    from eigentlich.services import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        positions = [
            Position(member_id=member.id, role="growth", capital_type="financial", label="Depot"),
            Position(member_id=member.id, role="protection", capital_type="human", label="Anstellung"),
        ]
        for position in positions:
            session.add(position)
        decision.linked_positions.extend(positions)
    session.commit()
    return member


def test_the_members_own_role_grid_pre_filters_the_view(seeded, member_with_grid):
    """R-201, first half. No parameter passed: the grid is the filter."""
    payload = browse(seeded, member_id=member_with_grid.id)
    assert payload["filter"]["applied"] is True
    assert payload["filter"]["source"] == "member_role_grid"
    assert payload["filter"]["roles"] == ["growth", "protection"]
    for entry in payload["entries"]:
        assert set(entry["roles"]) & {"growth", "protection"}, f"{entry['id']} is outside the filter"


def test_the_filter_names_itself_and_how_to_drop_it(seeded, member_with_grid):
    """R-201, second half. Visible and removable is a promise about the payload, not about a button."""
    applied = browse(seeded, member_id=member_with_grid.id)["filter"]
    assert applied["visible"] is True
    assert applied["removable"] is True
    assert applied["parameter"] == FILTER_PARAMETER
    assert applied["remove_by"] == {"parameter": FILTER_PARAMETER, "value": NO_FILTER}
    assert applied["all_roles"] == list(ROLES)


def test_removing_the_filter_shows_what_it_was_hiding(seeded, member_with_grid):
    """And the instruction the payload gave actually works when it is followed."""
    filtered = browse(seeded, member_id=member_with_grid.id)
    removal = filtered["filter"]["remove_by"]
    unfiltered = browse(seeded, member_id=member_with_grid.id, **{removal["parameter"]: removal["value"]})
    assert unfiltered["filter"]["applied"] is False
    assert unfiltered["filter"]["source"] == "removed_by_the_member"
    assert set(_ids(filtered)) < set(_ids(unfiltered)), "removing the filter revealed nothing"


def test_an_explicit_role_choice_is_named_as_the_members_own(seeded, member_with_grid):
    payload = browse(seeded, member_id=member_with_grid.id, roles=["income"])
    assert payload["filter"]["source"] == "explicit"
    assert payload["filter"]["roles"] == ["income"]


def test_an_empty_role_grid_filters_nothing_away(seeded, browser):
    """R-020 at n=0. A member who has filled in no cell sees the market place, not an empty one."""
    payload = browse(seeded, member_id=browser.id)
    assert payload["filter"]["applied"] is False
    assert payload["filter"]["reason"] == "role_grid_is_empty"
    assert _ids(payload) == _ids(browse(seeded, roles=NO_FILTER))


def test_browsing_without_a_member_applies_no_filter(seeded):
    payload = browse(seeded)
    assert payload["filter"]["applied"] is False
    assert payload["filter"]["reason"] == "no_member_to_pre_filter_from"


# ============================================================ R-202 — disclosures, in the publish path


def test_every_published_listing_displays_its_disclosures(seeded):
    """R-202, first half. Always present, and never an empty list."""
    for entry in browse(seeded, roles=NO_FILTER)["entries"]:
        if entry["entry_kind"] != "provider_listing":
            continue
        assert entry["disclosures"], f"{entry['id']} is published with nothing declared"
        for record in entry["disclosures"]:
            assert record["kind"] and record["statement"]
            assert record["declared_by"] and record["declared_at"]


def test_a_listing_with_no_disclosure_record_cannot_be_published(session, member):
    """R-202, second half, **in the publish path**. Not in a validator a second write path can skip."""
    supplier = Provider(display_name="Undeclared", fictional=False)
    session.add(supplier)
    session.flush()
    listing = Listing(
        provider_id=supplier.id, title="Ohne Offenlegung", roles=["growth"], domain="financial",
        qualification_pipeline="capability", registration_refs=[], standing_inputs={}, status="draft",
    )
    session.add(listing)
    session.flush()

    with pytest.raises(UndisclosedListing):
        publish(session, listing.id)
    assert session.get(Listing, listing.id).status == "draft"


def test_none_declared_is_a_statement_somebody_made_and_publishes(session, member):
    """R-202. `none_declared` is a positive statement, not an empty field — so it satisfies the gate."""
    supplier = Provider(display_name="Nothing To Declare", fictional=False)
    session.add(supplier)
    session.flush()
    listing = Listing(
        provider_id=supplier.id, title="Mit Offenlegung", roles=["growth"], domain="financial",
        qualification_pipeline="capability", registration_refs=[], standing_inputs={}, status="draft",
    )
    session.add(listing)
    session.flush()
    declare(
        session,
        listing_id=listing.id,
        kind="none_declared",
        statement="Keine wirtschaftlichen Verbindungen.",
        declared_by="Inhaberin",
    )
    assert publish(session, listing.id).status == "published"


def test_a_published_listing_with_no_disclosure_cannot_be_STORED(session, member):
    """R-202's second enforcement point, and until 1 September 2026 there was only one.

    **The finding.** `publish` is written as the write path rather than as "a validator called on the way
    past: a validator is something a second write path can be written without" — the right instinct, and
    still one point rather than two. An audit constructed the second write path in four lines: a raw
    `Listing(status="published")` with zero disclosures committed without complaint, and `browse` served
    it with `disclosures: []`, while `test_every_published_listing_displays_its_disclosures` above went on
    passing because it only reads the listings the seeding path created.

    `test_publish_is_the_only_place_a_listing_becomes_published` is the structural half of this and does
    not cover it: it reads `services/marketplace.py` and can say nothing about a caller outside it.

    **Planted:** commented out the `before_flush` guard in `models/marketplace.py`. `session.commit()`
    returned normally, the row was queryable with `status == 'published'`, and this test failed on
    `DID NOT RAISE UndisclosedListing`. Restored.
    """
    from eigentlich.models import UndisclosedListing as ModelUndisclosed

    # One class, two enforcement points — the service imports the model's exception rather than declaring
    # a second one, so `except UndisclosedListing` catches both halves of R-202.
    assert UndisclosedListing is ModelUndisclosed

    supplier = Provider(display_name="Round The Back", fictional=False)
    session.add(supplier)
    session.flush()

    session.add(
        Listing(
            provider_id=supplier.id, title="Direkt geschrieben", roles=["growth"], domain="financial",
            qualification_pipeline="capability", registration_refs=[], standing_inputs={},
            status="published",
        )
    )
    with pytest.raises(UndisclosedListing, match="R-202"):
        session.commit()
    session.rollback()

    # Nothing was stored, so nothing can be served. The gap R-202 closes is a listing a member can see.
    assert not session.query(Listing).filter_by(provider_id=supplier.id).count()
    assert not _ids(browse(session, roles=NO_FILTER))


def test_a_stored_draft_cannot_be_flipped_to_published_by_assignment(session, member):
    """The same gate on the other raw write: not creating a published row, but promoting a draft one.

    `publish` is what a caller is meant to use and it does more than this check — R-204's pipeline, R-203's
    standing. This asserts only that the assignment cannot get past the disclosure gate on its own, which
    is what makes `publish` the way in rather than the polite way in.
    """
    supplier = Provider(display_name="Flipped", fictional=False)
    session.add(supplier)
    session.flush()
    listing = Listing(
        provider_id=supplier.id, title="Entwurf", roles=["growth"], domain="financial",
        qualification_pipeline="capability", registration_refs=[], standing_inputs={}, status="draft",
    )
    session.add(listing)
    session.commit()

    listing.status = "published"
    with pytest.raises(UndisclosedListing, match="R-202"):
        session.commit()
    session.rollback()
    assert session.get(Listing, listing.id).status == "draft"

    # And the gate opens on a disclosure rather than on nothing: the same assignment, once something has
    # been declared, is allowed through. A guard that refused every write would pass its own plant.
    declare(
        session,
        listing_id=listing.id,
        kind="none_declared",
        statement="Keine wirtschaftlichen Verbindungen.",
        declared_by="Inhaberin",
    )
    listing.status = "published"
    session.commit()
    assert session.get(Listing, listing.id).status == "published"


def test_a_listing_and_its_first_disclosure_may_be_written_in_one_flush(session, member):
    """The guard must not make the honest single-transaction write impossible.

    A caller that adds a listing and its disclosure together and commits once has declared something; a
    gate that refused that would push people towards exactly the raw two-step it exists to catch. Ordering
    matters here — the listing has no id yet when the guard runs — which is why this is asserted rather
    than assumed.
    """
    supplier = Provider(display_name="One Transaction", fictional=False)
    session.add(supplier)
    session.flush()
    listing = Listing(
        provider_id=supplier.id, title="Zusammen geschrieben", roles=["income"], domain="financial",
        qualification_pipeline="capability", registration_refs=[], standing_inputs={},
        status="published",
    )
    listing.disclosures.append(
        Disclosure(
            kind="none_declared",
            statement="Keine wirtschaftlichen Verbindungen.",
            declared_by="Inhaberin",
            declared_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    session.add(listing)
    session.commit()
    assert session.get(Listing, listing.id).status == "published"


def test_publish_is_the_only_place_a_listing_becomes_published():
    """The gate is only a gate if there is one way in. Checked structurally, not by reading carefully."""
    writers: set[str] = set()
    for node in ast.walk(_module_tree(SERVICE)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            wrote = (
                isinstance(child, ast.Assign)
                and isinstance(child.value, ast.Constant)
                and child.value.value == "published"
            ) or (
                isinstance(child, ast.keyword)
                and child.arg == "status"
                and isinstance(child.value, ast.Constant)
                and child.value.value == "published"
            )
            if wrote:
                writers.add(node.name)
    assert writers == {"publish"}, (
        f"R-202: {sorted(writers)} write a published status. `publish` is where the disclosure gate is, "
        f"and a second writer is a route around it."
    )


def test_the_seeding_path_goes_through_the_same_gate(session, offer_member, monkeypatch):
    """A41 supply is not exempt from R-202. Strip a seed record's disclosures and seeding must stop."""
    stripped = [dict(record, disclosures=[]) for record in seed_listings()]
    monkeypatch.setattr("eigentlich.services.marketplace.seed_listings", lambda: stripped)
    monkeypatch.setattr("eigentlich.services.marketplace.seed_disclosures", lambda: [])
    with pytest.raises(UndisclosedListing):
        seed(session, member_id=offer_member.id)


def test_a_draft_listing_is_not_served(session, member):
    supplier = Provider(display_name="Draft Only", fictional=False)
    session.add(supplier)
    session.flush()
    listing = Listing(
        provider_id=supplier.id, title="Entwurf", roles=["income"], domain="financial",
        qualification_pipeline="capability", registration_refs=[], standing_inputs={}, status="draft",
    )
    session.add(listing)
    session.commit()
    with pytest.raises(UnknownListing):
        listing_detail(session, listing.id)
    assert listing.id not in _ids(browse(session, roles=NO_FILTER))


def test_every_seeded_listing_declares_something():
    """R-202 in the content file, so the failure is visible before anything is written."""
    for record in seed_listings():
        assert record["disclosures"], f"{record['key']} declares nothing"


def test_the_detail_payload_always_carries_the_disclosures(seeded):
    payload = listing_detail(seeded, "hypothek_amortisation_check")
    assert len(payload["listing"]["disclosures"]) == 2
    kinds = {record["kind"] for record in payload["listing"]["disclosures"]}
    assert "referral_arrangement" in kinds


# ============================================================ R-204 — two pipelines, not interchangeable


def test_each_domain_declares_its_own_pipeline():
    """R-204. Capability-assessed for financial supply; professional registration for the other two."""
    assert set(PIPELINE_FOR_DOMAIN) == set(DOMAINS)
    assert required_pipeline("financial") == "capability"
    assert required_pipeline("health") == "professional_registration"
    assert required_pipeline("education") == "professional_registration"
    assert set(PIPELINE_FOR_DOMAIN.values()) == set(PIPELINES)


def test_every_seeded_listing_is_under_the_pipeline_its_domain_goes_through():
    for record in seed_listings():
        assert record["qualification_pipeline"] == required_pipeline(record["domain"]), record["key"]


def test_the_two_pipelines_carry_different_evidence():
    """R-204. Registration references belong to one of them and not to the other."""
    for record in seed_listings():
        if record["qualification_pipeline"] == "professional_registration":
            assert record["registration_refs"], f"{record['key']} names no registration"
        else:
            assert record["registration_refs"] == [], f"{record['key']} borrows the other pipeline's evidence"


def test_declaring_the_wrong_pipeline_is_refused_rather_than_corrected(session, member_with_evidence):
    """R-204. The service must not work around the CHECK by quietly rewriting what was declared."""
    with pytest.raises(PipelineMismatch):
        apply_to_be_listed(
            session, member_id=member_with_evidence.id, display_name="Praxis", title="Gespräche",
            domain="health", qualification_pipeline="capability", roles=["protection"],
        )
    with pytest.raises(PipelineMismatch):
        apply_to_be_listed(
            session, member_id=member_with_evidence.id, display_name="Büro", title="Kostenrechnung",
            domain="financial", qualification_pipeline="professional_registration", roles=["growth"],
            registration_refs=["irgendein Register"],
        )


def test_the_service_does_not_rewrite_the_declared_pipeline():
    """Structurally: what the applicant declared is what reaches the row.

    A service that assigned `required_pipeline(domain)` onto the listing would pass every behavioural
    test above and make the CHECK unreachable, which is working around it while appearing to respect it.
    """
    node = _function("apply_to_be_listed")
    construction = next(
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "Listing"
    )
    declared = next(kw for kw in construction.keywords if kw.arg == "qualification_pipeline")
    assert isinstance(declared.value, ast.Name) and declared.value.id == "qualification_pipeline", (
        "R-204: the listing is built from something other than the pipeline the applicant declared"
    )


def test_the_check_constraint_still_fires_when_the_service_is_bypassed(session):
    """R-204. The service refuses; the store refuses too, for callers who never came through the service."""
    supplier = Provider(display_name="Bypass", fictional=False)
    session.add(supplier)
    session.flush()
    session.add(
        Listing(
            provider_id=supplier.id, title="Gemischt", roles=["protection"], domain="health",
            qualification_pipeline="capability", registration_refs=[], standing_inputs={}, status="draft",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_capability_evidence_does_not_substitute_for_a_registration(session, member_with_evidence):
    """R-204, the half that makes the pipelines *not interchangeable* rather than merely different."""
    with pytest.raises(MissingRegistration):
        apply_to_be_listed(
            session, member_id=member_with_evidence.id, display_name="Praxis", title="Gespräche",
            domain="health", qualification_pipeline="professional_registration", roles=["protection"],
        )


def test_a_registration_does_not_substitute_for_capability_evidence(session, browser):
    """And the other direction. A financial listing carrying registration references is refused."""
    with pytest.raises(PipelineMismatch):
        apply_to_be_listed(
            session, member_id=browser.id, display_name="Büro", title="Kostenrechnung",
            domain="financial", qualification_pipeline="capability", roles=["growth"],
            registration_refs=["Kantonales Register, Eintrag 1 (fiktiv)"],
        )


def test_a_registration_alone_lists_health_supply(session, browser):
    """The professional pipeline stands on its own: no eigentliCH capability assertion is needed for it."""
    listing = apply_to_be_listed(
        session, member_id=browser.id, display_name="Praxis am Platz", title="Einzelsitzungen",
        domain="health", qualification_pipeline="professional_registration", roles=["protection"],
        registration_refs=["Kantonales Berufsregister ZH, Eintrag 9 (fiktiv)"],
    )
    assert listing.status == "draft"
    assert listing.qualification_pipeline == "professional_registration"


def test_publishing_re_checks_the_pipeline(session, browser):
    """The last gate before a member sees it, checked again there rather than trusted from earlier."""
    listing = apply_to_be_listed(
        session, member_id=browser.id, display_name="Praxis", title="Sitzungen",
        domain="health", qualification_pipeline="professional_registration", roles=["protection"],
        registration_refs=["Kantonales Berufsregister ZH, Eintrag 9 (fiktiv)"],
    )
    declare(session, listing_id=listing.id, kind="none_declared", statement="Keine.", declared_by="Leitung")
    listing.registration_refs = []
    with pytest.raises(MissingRegistration):
        publish(session, listing.id)


# ============================================================ R-205 — alongside, not beneath


def test_member_offers_and_provider_listings_are_in_one_list(seeded):
    """R-205. Two sibling keys would still let a client render one under a heading below the other."""
    payload = browse(seeded, roles=NO_FILTER)
    assert "listings" not in payload and "member_offers" not in payload
    kinds = {entry["entry_kind"] for entry in payload["entries"]}
    assert kinds == set(ENTRY_KINDS)
    assert payload["entry_kinds_are_peers"] is True


def test_member_offers_are_not_a_block_below_the_listings(seeded):
    """R-205's word is *alongside*. A block at the bottom is 'beneath' whatever the key is called."""
    entries = browse(seeded, roles=NO_FILTER)["entries"]
    offers = [i for i, e in enumerate(entries) if e["entry_kind"] == "member_offer"]
    listings = [i for i, e in enumerate(entries) if e["entry_kind"] == "provider_listing"]
    assert offers and listings
    assert min(offers) > min(listings), "member offers are a block at the top"
    assert max(offers) < max(listings), "member offers are a block at the bottom"


def test_both_kinds_are_ordered_by_the_same_function(seeded):
    """Different rules for the two kinds would separate them without anyone naming a heading."""
    node = _without_docstring(_function("browse"))
    used = _names_in(node)
    assert "listing_ordering_inputs" in used and "offer_ordering_inputs" in used
    assert used.count("_in_order") == 1, "the two kinds are put in order in different places"


def test_the_seeded_offers_cover_what_r205_names():
    """Co-investment, succession, property, skills and services."""
    kinds = {record["kind"] for record in seed_member_offers()}
    assert {"co_investment", "succession", "property"} <= kinds
    assert kinds & {"skills", "services"}
    directions = {record["direction"] for record in seed_member_offers()}
    assert directions == {"offer", "search"}, "R-205 names offers AND searches"


def test_a_member_offer_is_filtered_by_the_same_roles(seeded):
    payload = browse(seeded, roles=["stabilisation"])
    offers = [e for e in payload["entries"] if e["entry_kind"] == "member_offer"]
    assert offers, "the role filter removed every member offer"
    for entry in offers:
        assert "stabilisation" in entry["roles"]


def test_a_member_offer_carries_no_standing_number(seeded):
    """R-221. Attendance is an input to standing and is not shown back as a score."""
    for entry in browse(seeded, roles=NO_FILTER)["entries"]:
        assert "standing_inputs" not in entry
        assert "capability_evidence" not in entry
        assert "community_presence" not in entry


# ============================================================ R-004 / R-005 — both directions


def test_browsing_is_never_gated_on_learning_progress(seeded, browser, offer_member):
    """R-004. A member on their first day sees what a member of three years sees."""
    fresh = browse(seeded, member_id=browser.id, roles=NO_FILTER)
    experienced = browse(seeded, member_id=offer_member.id, roles=NO_FILTER)
    assert _ids(fresh) == _ids(experienced)
    assert fresh["browsing_is_not_gated"] is True


def test_contacting_is_never_gated_on_learning_progress(seeded, browser):
    """R-005: reading and hiring are not gated. So there is no gate here to pass, and none to fail."""
    payload = contact_details(seeded, listing_id="fzk_kostenrechnung", member_id=browser.id)
    assert payload["contact"], "a member with no learning behind them cannot reach supply"
    assert payload["gated_on"] is None
    assert payload["gated_on_reason"] == "browsing_and_contacting_are_never_gated"


def test_contacting_reads_no_capability_evidence_at_all():
    """R-004 structurally. 'Never gated' has to survive a redesign, so nothing is in scope to gate on."""
    used = _names_in(_without_docstring(_function("contact_details")))
    for forbidden in ("CapabilityAssertion", "capability_id", "LearningUnit", "learning", "rung"):
        assert forbidden not in used, f"R-004: contact_details reads {forbidden}"


def test_a_member_offer_is_reachable_without_learning_progress(seeded, browser):
    offer = next(e for e in browse(seeded, roles=NO_FILTER)["entries"] if e["entry_kind"] == "member_offer")
    payload = contact_details(seeded, offer_id=offer["id"], member_id=browser.id)
    assert payload["contact_via"]["value"]
    assert payload["gated_on"] is None


@pytest.fixture()
def member_with_evidence(session):
    """R-005's other side: a member who has evidenced something and may therefore be listed."""
    member = register_member(session, age_at_registration=38, display_name="Evidenced Member")
    seed_learning(session)
    session.flush()
    record_assertion(
        session,
        member_id=member.id,
        capability_id="fondskosten_in_franken",
        evidence_kind="conversation_with_a_curator",
        assessed_by="curator:demo",
        assessed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    session.commit()
    return member


def test_being_listed_as_supply_is_gated_on_capability_evidence(session, browser):
    """R-005. The direction that IS gated, and it refuses rather than warning."""
    with pytest.raises(InsufficientCapabilityEvidence):
        apply_to_be_listed(
            session, member_id=browser.id, display_name="Neu im Markt", title="Kostenrechnung",
            domain="financial", qualification_pipeline="capability", roles=["growth"],
        )


def test_evidence_opens_the_gate_and_produces_a_draft(session, member_with_evidence):
    """And the same call succeeds once there is evidence — a gate that never opens is a wall."""
    listing = apply_to_be_listed(
        session, member_id=member_with_evidence.id, display_name="Zahlenbüro", title="Kostenrechnung",
        domain="financial", qualification_pipeline="capability", roles=["growth", "income"],
    )
    assert listing.status == "draft", "R-202: an application must not arrive published"
    assert listing.roles == ["growth", "income"]
    supplier = session.get(Provider, listing.provider_id)
    assert supplier.member_id == member_with_evidence.id


def test_the_payload_names_both_promises(seeded):
    """R-004 and R-005 are opposite statements about one surface, so a client reads both or neither."""
    payload = browse(seeded, roles=NO_FILTER)
    assert payload["browsing_is_not_gated"] is True
    assert payload["contacting_is_not_gated"] is True
    assert payload["being_listed_is_gated_on"] == "capability_evidence_or_professional_registration"


def test_an_application_names_at_least_one_role(session, member_with_evidence):
    with pytest.raises(UnknownRole):
        apply_to_be_listed(
            session, member_id=member_with_evidence.id, display_name="Ohne Rolle", title="Etwas",
            domain="financial", qualification_pipeline="capability", roles=["treuhand"],
        )


# ============================================================ NG-04 — no accredited status claimed


def test_no_claim_of_federal_or_accredited_status_in_the_seed_data():
    """NG-04 / A41's second guard. Asserted by a test over the seed data, not by care."""
    found = _whole_words(ACCREDITATION_WORDS, _seed_copy())
    assert not found, f"NG-04: the seeded supply claims a qualification it does not have: {found}"


def test_the_accreditation_filter_is_not_vacuous():
    """Whole-word matching, and it has to be: `Franken` contains `rank`, and this copy is full of francs."""
    assert _whole_words(ACCREDITATION_WORDS, "ein akkreditiert zertifikat mit diplom") == [
        "akkreditiert",
        "diplom",
        "zertifikat",
    ]
    assert _whole_words(ACCREDITATION_WORDS, "eidgenössisch anerkannt") == ["eidgenössisch"]
    assert _whole_words(("rank",), _seed_copy()) == [], "must not fire inside Franken"
    assert "franken" in _seed_copy(), "the seed copy names no francs — the guard above proves nothing"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_claim_of_federal_or_accredited_status_in_the_source(path):
    found = _whole_words(ACCREDITATION_WORDS, _code_only(path))
    assert not found, f"NG-04: {path.name} claims a qualification eigentliCH does not award: {found}"


def test_no_claim_of_federal_or_accredited_status_in_the_payloads(seeded):
    blob = json.dumps([browse(seeded, roles=NO_FILTER), role_index(seeded)], default=str).lower()
    found = _whole_words(ACCREDITATION_WORDS, blob)
    assert not found, f"NG-04: an S-11 payload claims {found}"


def test_the_payloads_state_that_no_qualification_is_claimed(seeded):
    """Explicit rather than inferred from an absent key."""
    for payload in (browse(seeded, roles=NO_FILTER), listing_detail(seeded, "belastung_gespraech")):
        assert payload["qualification_claim"] is None
        assert payload["qualification_claim_reason"] == QUALIFICATION_CLAIM


def test_a_registration_reference_is_marked_as_the_providers_own(seeded):
    """NG-04. eigentliCH neither awards nor verifies these, and the payload does not let that be inferred."""
    payload = listing_detail(seeded, "belastung_gespraech")
    assert payload["listing"]["registration_refs"]
    assert payload["listing"]["registration_refs_are_the_providers_own"] is True
    for reference in payload["listing"]["registration_refs"]:
        assert "fiktiv" in reference, "a seeded registration reference reads as a real one"


def test_the_copy_scanner_actually_reads_the_seed_content():
    """Every filter here runs over `_seed_copy()`. An empty one would make all of them pass, silently."""
    copy = _seed_copy()
    assert len(copy.split()) > 400, f"the seed-copy scanner found only {len(copy.split())} words"
    assert "freizügigkeitskonto" in copy
    assert "requirement" not in copy, "`_about` leaked into the member-facing copy the filters scan"


def test_no_gamification_vocabulary_in_the_seed_content():
    """C-07 as copy. The constraint is about the product, not only the schema."""
    found = _whole_words(GAMIFICATION_WORDS, _seed_copy())
    assert not found, f"C-07: found game-mechanic vocabulary in the seeded supply: {found}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_gamification_vocabulary_in_the_phase_seven_source(path):
    found = _whole_words(GAMIFICATION_WORDS + ("rank", "daily_goal"), _code_only(path))
    assert not found, f"C-07: found game-mechanic vocabulary in {path.name}: {found}"


def test_no_mountain_vocabulary_in_the_seed_content():
    """R-143, in both languages. A12 makes every copy rule a two-language rule."""
    found = _whole_words(MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE, _seed_copy())
    assert not found, f"R-143: metaphor belongs in the marketing surfaces, not here. Found: {found}"


# ============================================================ A41 — fictional, and marked so


def test_the_content_file_declares_itself_fictional():
    assert content_is_fictional() is True


def test_every_seeded_record_is_marked_fictional():
    """A41. In the data itself, so a screenshot cannot be mistaken for a real market."""
    groups = {
        "providers": seed_providers(),
        "listings": seed_listings(),
        "disclosures": seed_disclosures(),
        "member_offers": seed_member_offers(),
    }
    for name, records in groups.items():
        assert records, f"{name} is empty — this assertion would pass over nothing"
        for record in records:
            assert record.get("fictional") is True, f"{name}/{record['key']} is not marked"


@pytest.mark.parametrize(
    "accessor",
    ["seed_providers", "seed_listings", "seed_member_offers"],
)
def test_seeding_refuses_a_record_that_is_not_marked(session, offer_member, monkeypatch, accessor):
    """A41. The marker is load-bearing, not decorative. This is what makes that true, per group."""
    from eigentlich.services import marketplace as service

    original = getattr(service, accessor)()
    unmarked = [dict(original[0], fictional=False), *original[1:]]
    monkeypatch.setattr(f"eigentlich.services.marketplace.{accessor}", lambda: unmarked)
    with pytest.raises(NotMarkedFictional):
        seed(session, member_id=offer_member.id)


def test_seeding_refuses_an_unmarked_disclosure(session, offer_member, monkeypatch):
    """The nested group, which a guard walking only the top-level lists would miss."""
    stripped = [dict(record, fictional=False) for record in seed_disclosures()]
    monkeypatch.setattr("eigentlich.services.marketplace.seed_disclosures", lambda: stripped)
    with pytest.raises(NotMarkedFictional):
        seed(session, member_id=offer_member.id)


def test_the_marker_reaches_the_rows(seeded):
    for model in (Provider, Listing, MemberOffer):
        rows = seeded.execute(select(model)).scalars().all()
        assert rows, f"nothing was seeded into {model.__name__}"
        assert all(row.fictional is True for row in rows)


def test_the_marker_survives_into_the_payloads(seeded):
    payload = browse(seeded, roles=NO_FILTER)
    assert payload["fictional"] is True
    for entry in payload["entries"]:
        assert entry["fictional"] is True
        if entry["entry_kind"] == "provider_listing":
            assert entry["supplier"]["fictional"] is True


def test_a_real_application_is_not_marked_fictional(session, member_with_evidence):
    """The marker means something only if it distinguishes. A member's own listing is not seed data."""
    listing = apply_to_be_listed(
        session, member_id=member_with_evidence.id, display_name="Zahlenbüro", title="Kostenrechnung",
        domain="financial", qualification_pipeline="capability", roles=["growth"],
    )
    assert listing.fictional is False
    assert session.get(Provider, listing.provider_id).fictional is False


# ============================================================ A12 — bilingual, de-CH authored


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_member_facing_string_exists_in_both_languages(language):
    """A12. A missing German string is a failure now rather than a re-authoring later."""
    for record in seed_listings():
        assert record["title"].get(language), f"{record['key']} has no {language} title"
        assert record["summary"].get(language), f"{record['key']} has no {language} summary"
        for entry in record["disclosures"]:
            assert entry["statement"].get(language), f"{entry['key']} has no {language} statement"
    for record in seed_member_offers():
        assert record["title"].get(language), f"{record['key']} has no {language} title"
        assert record["body"].get(language), f"{record['key']} has no {language} body"


def test_the_english_is_marked_as_a_draft_translation():
    """A12. German is the authored language; the English says what it is rather than implying review."""

    def walk(node, path="root"):
        if isinstance(node, dict):
            if "en" in node and "de" in node:
                assert node.get("en_draft") is True, f"{path}: English is not marked as a draft"
            for key, value in node.items():
                if key != "_about":
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(_content())


def test_german_is_what_is_stored_and_english_is_rendered_on_request(seeded):
    """The row carries the authored language; the sentence a member reads comes from the content record."""
    authored = {record["key"]: record for record in seed_listings()}
    row = seeded.get(Listing, "fzk_kostenrechnung")
    assert row.title == authored["fzk_kostenrechnung"]["title"]["de"]

    english = browse(seeded, roles=NO_FILTER, language="en")
    entry = next(e for e in english["entries"] if e["id"] == "fzk_kostenrechnung")
    assert entry["title"] == authored["fzk_kostenrechnung"]["title"]["en"]
    assert entry["summary"] == authored["fzk_kostenrechnung"]["summary"]["en"]


def test_a_disclosure_is_shown_in_the_members_language(seeded):
    """R-202 meets A12. A disclosure a member cannot read is one they have not been shown."""
    german = listing_detail(seeded, "fondskosten_durchsicht", language="de")["listing"]["disclosures"][0]
    english = listing_detail(seeded, "fondskosten_durchsicht", language="en")["listing"]["disclosures"][0]
    assert german["statement"] != english["statement"]
    assert "Treuhandgesellschaft" in german["statement"]


def test_no_eszett_in_the_seed_copy():
    """de-CH. Not a style note: the estate's German is Swiss German orthography throughout."""
    assert "ß" not in _seed_copy()


# ============================================================ seeding mechanics


def test_seeding_is_idempotent(session, offer_member):
    first = seed(session, member_id=offer_member.id)
    session.commit()
    second = seed(session, member_id=offer_member.id)
    session.commit()
    assert first["providers"] and first["listings"] and first["member_offers"]
    assert second == {"providers": [], "listings": [], "disclosures": [], "member_offers": []}


def test_seeding_without_a_member_writes_no_member_offer(session):
    """A MemberOffer without a member is not a member offer, and inventing one would seed a person."""
    written = seed(session)
    session.commit()
    assert written["listings"]
    assert written["member_offers"] == []
    assert session.execute(select(MemberOffer)).scalars().all() == []


def test_every_key_fits_the_id_column():
    """The content key is the row id. A key too long for `String(32)` would truncate silently on SQLite."""
    records = seed_providers() + seed_listings() + seed_disclosures() + seed_member_offers()
    for record in records:
        assert len(record["key"]) <= 32, f"{record['key']} is {len(record['key'])} characters"


def test_every_key_is_unique():
    keys = [r["key"] for r in seed_providers() + seed_listings() + seed_member_offers()]
    keys += [r["key"] for r in seed_disclosures()]
    assert len(keys) == len(set(keys))


def test_every_listing_names_a_provider_that_exists():
    known = {record["key"] for record in seed_providers()}
    for record in seed_listings():
        assert record["provider_key"] in known, f"{record['key']} names an unknown provider"


def test_every_capability_reference_resolves_against_the_learning_content():
    """`standing_inputs.capability_evidence` names keys in `learning.json`, so a typo is not standing."""
    from eigentlich.services.learning import capabilities

    known = {record["key"] for record in capabilities()}
    for record in seed_listings():
        unknown = [
            key for key in record["standing_inputs"]["capability_evidence"] if key not in known
        ]
        assert not unknown, f"{record['key']} claims evidence that does not exist: {unknown}"


def test_the_seed_covers_both_pipelines_and_all_three_domains():
    """A market place with one domain seeded would leave R-204 untested by anything that runs."""
    assert {record["domain"] for record in seed_listings()} == set(DOMAINS)
    assert {record["qualification_pipeline"] for record in seed_listings()} == set(PIPELINES)
    assert len(seed_listings()) >= 8


def test_every_seeded_listing_reaches_the_store_published(seeded):
    rows = seeded.execute(select(Listing)).scalars().all()
    assert len(rows) == len(seed_listings())
    assert all(row.status == "published" for row in rows)
    assert seeded.execute(select(Disclosure)).scalars().all()


# ============================================================ the router


def test_the_listings_endpoint_returns_both_kinds(api):
    client, member_id = api
    response = client.get("/api/marketplace/listings", params={"roles": NO_FILTER})
    assert response.status_code == 200
    body = response.json()
    assert {e["entry_kind"] for e in body["entries"]} == set(ENTRY_KINDS)
    assert body["ordering_is_not_purchasable"] is True
    assert body["fictional"] is True


def test_the_router_declares_no_commercial_query_parameter(api):
    """C-08 at the edge. Every parameter of every route, named and checked.

    FastAPI ignores an unknown query parameter, so the enforcement is that none of these routes declares
    one — and a future `boost=` would have to be added here in full view.
    """
    offences: list[str] = []
    for route in router.routes:
        for name in inspect.signature(route.endpoint).parameters:
            if name.lower().lstrip("_") in FORBIDDEN_IN_ORDERING:
                offences.append(f"{route.path}: {name}")
    assert not offences, f"C-08: the API accepts {offences}"


def test_a_boost_parameter_changes_nothing(api):
    """And in case one is ever sent anyway: it is not read, so the order it asked for does not happen."""
    client, _ = api
    plain = client.get("/api/marketplace/listings", params={"roles": NO_FILTER}).json()
    bought = client.get(
        "/api/marketplace/listings", params={"roles": NO_FILTER, "boost": "zahlenwerk_olten"}
    ).json()
    assert [e["id"] for e in plain["entries"]] == [e["id"] for e in bought["entries"]]


def test_the_detail_endpoint_always_carries_disclosures(api):
    client, _ = api
    body = client.get("/api/marketplace/listings/fzk_kostenrechnung").json()
    assert body["listing"]["disclosures"]


def test_an_unknown_listing_is_a_404(api):
    client, _ = api
    assert client.get("/api/marketplace/listings/not_a_listing").status_code == 404


def test_the_role_index_endpoint_answers_without_a_member(api):
    client, _ = api
    body = client.get("/api/marketplace/roles").json()
    assert [bucket["key"] for bucket in body["roles"]] == list(ROLES)


def test_the_filter_can_be_removed_over_http(api):
    client, member_id = api
    filtered = client.get("/api/marketplace/listings", params={"roles": "growth"}).json()
    removal = filtered["filter"]["remove_by"]
    unfiltered = client.get(
        "/api/marketplace/listings", params={removal["parameter"]: removal["value"]}
    ).json()
    assert unfiltered["filter"]["applied"] is False
    assert len(unfiltered["entries"]) > len(filtered["entries"])


def test_an_unknown_role_is_refused_over_http(api):
    client, _ = api
    assert client.get("/api/marketplace/listings", params={"roles": "beruf"}).status_code == 422


def test_an_unknown_language_is_refused(api):
    client, _ = api
    assert client.get("/api/marketplace/listings", params={"language": "fr"}).status_code == 422


def test_contacting_over_http_needs_no_progress(api):
    """R-004. No member id at all, and the contact still comes back."""
    client, _ = api
    body = client.get("/api/marketplace/listings/fzk_kostenrechnung/contact").json()
    assert body["contact"]
    assert body["gated_on"] is None


def test_an_application_without_evidence_is_refused_over_http(api):
    """R-005. 403, not 422: the request is well formed and the applicant is not yet eligible."""
    client, _ = api
    fresh = client
    response = fresh.post(
        "/api/marketplace/applications",
        json={
            "member_id": "no_such_member_with_evidence",
            "display_name": "Neu",
            "title": "Kostenrechnung",
            "domain": "financial",
            "qualification_pipeline": "capability",
            "roles": ["growth"],
        },
    )
    assert response.status_code == 403


def test_an_application_arrives_as_a_draft_and_publishes_only_after_a_disclosure(api):
    """R-005 then R-202, in the order an applicant meets them."""
    client, member_id = api
    created = client.post(
        "/api/marketplace/applications",
        json={
            "member_id": member_id,
            "display_name": "Praxis am Platz",
            "title": "Einzelsitzungen",
            "domain": "health",
            "qualification_pipeline": "professional_registration",
            "roles": ["protection"],
            "registration_refs": ["Kantonales Berufsregister ZH, Eintrag 9 (fiktiv)"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["publishable"] is False

    refused = client.post(f"/api/marketplace/applications/{body['id']}/publish")
    assert refused.status_code == 422, "R-202: published without a disclosure record"

    declared = client.post(
        f"/api/marketplace/applications/{body['id']}/disclosures",
        json={"kind": "none_declared", "statement": "Keine Verbindungen.", "declared_by": "Leitung"},
    )
    assert declared.status_code == 201
    published = client.post(f"/api/marketplace/applications/{body['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"


def test_a_mismatched_pipeline_is_refused_over_http(api):
    client, member_id = api
    response = client.post(
        "/api/marketplace/applications",
        json={
            "member_id": member_id,
            "display_name": "Praxis",
            "title": "Gespräche",
            "domain": "health",
            "qualification_pipeline": "capability",
            "roles": ["protection"],
        },
    )
    assert response.status_code == 422


def test_the_router_exposes_exactly_the_routes_it_means_to():
    """A route nobody meant to add is the shape a commercial surface arrives in."""
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/marketplace/listings",
        "/api/marketplace/listings/{listing_id}",
        "/api/marketplace/listings/{listing_id}/contact",
        "/api/marketplace/offers/{offer_id}/contact",
        "/api/marketplace/roles",
        "/api/marketplace/applications",
        "/api/marketplace/applications/{listing_id}/disclosures",
        "/api/marketplace/applications/{listing_id}/publish",
    }


# ============================================================ R-203 — the two inputs that were dead
#
# `Listing.standing_inputs` was written ONCE, EMPTY, by `apply_to_be_listed` and never derived from the
# database again. `member_standing()` did the derivation, but only for member offers — so a provider with
# six capability assertions and six attendances got `capability_evidence=0, community_presence=0`, and the
# ordering was `role_match` followed by a row id. Every ordering test above takes its non-zero standing
# from the seed fixture, which is why nothing went red: C-08 was being proved about an order that was two
# thirds constant.


def _evidenced(session, *, name, roles, assertions, attendances, publish_it=True):
    """One provider listing made the way the application makes them, with real evidence behind it."""
    person = register_member(session, age_at_registration=41, display_name=name)
    session.flush()
    for index in range(assertions):
        capability_id = f"cap-{name}-{index}"
        session.add(Capability(id=capability_id, statement="kann etwas erklären"))
        session.flush()
        session.add(CapabilityAssertion(
            member_id=person.id, capability_id=capability_id, evidence_kind="assessment",
            assessed_by="eigentliCH", assessed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ))
    for index in range(attendances):
        gathering = Gathering(kind="lecture", title=f"L{name}{index}", held_on=date(2026, 1, 1))
        session.add(gathering)
        session.flush()
        session.add(Attendance(member_id=person.id, gathering_id=gathering.id, attended=True))
    session.flush()

    listing = apply_to_be_listed(
        session, member_id=person.id, display_name=name, title=f"{name} listing",
        domain="financial", qualification_pipeline="capability", roles=roles,
    )
    declare(session, listing_id=listing.id, kind="none_declared", statement="keine", declared_by=name)
    if publish_it:
        publish(session, listing.id)
    session.flush()
    return person, listing


def test_a_listing_carries_the_offering_members_real_standing(session):
    """R-203. The application's own write path, which is the one that was returning zeroes."""
    _person, listing = _evidenced(session, name="Evidenced", roles=["growth"], assertions=6,
                                  attendances=6)
    session.commit()

    inputs = listing_ordering_inputs(listing, ("growth",))
    assert (inputs.capability_evidence, inputs.community_presence) == (6, 6), (
        f"standing_inputs did not pick up the member's real evidence: {listing.standing_inputs}"
    )


def test_the_standing_is_re_derived_when_the_listing_is_published(session):
    """Evidence earned after the application is picked up by `publish`, which is the visible act.

    Without this a listing would carry its application-day answer for ever — an ordering input frozen at
    the moment it was least informative, which is the same defect one step further along.
    """
    person, listing = _evidenced(session, name="Later", roles=["growth"], assertions=1, attendances=0,
                                 publish_it=False)
    assert len(listing.standing_inputs["capability_evidence"]) == 1

    session.add(Capability(id="cap-later-extra", statement="kann noch etwas erklären"))
    session.flush()
    session.add(CapabilityAssertion(
        member_id=person.id, capability_id="cap-later-extra", evidence_kind="assessment",
        assessed_by="eigentliCH", assessed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ))
    session.flush()

    publish(session, listing.id)
    session.commit()
    assert len(listing.standing_inputs["capability_evidence"]) == 2


def test_publishing_seeded_supply_does_not_wipe_its_authored_standing(seeded):
    """A provider that is not a member has no assertions and no attendances in this system.

    Deriving from that absence would replace the seeded demonstration standing with two empty lists —
    an answer derived from the absence of a person rather than from a person. `publish` refuses to.
    """
    listings = seeded.execute(select(Listing)).scalars().all()
    assert listings
    assert any(listing.standing_inputs.get("capability_evidence") for listing in listings), (
        "no seeded listing carries authored capability evidence, so this test would pass on a wipe"
    )
    for listing in listings:
        supplier = seeded.get(Provider, listing.provider_id)
        assert supplier.member_id is None
    # Re-publishing is idempotent for them.
    publish(seeded, listings[0].id)
    assert listings[0].standing_inputs["capability_evidence"]


def test_the_earned_inputs_move_the_order_on_the_real_write_path(session):
    """Behaviourally, and with no seed fixture anywhere near it.

    Two listings that declare the same single role, so `role_match` is identical and cannot be what
    separates them. Before the fix both carried empty standing and the order fell to the row id.

    Both hold at least one assertion because R-005 gates being listed on exactly that — a supplier with
    none never reaches the market place, so "one against six" is the real comparison rather than
    "none against six".
    """
    _evidenced(session, name="Thin", roles=["growth"], assertions=1, attendances=0)
    _evidenced(session, name="Thick", roles=["growth"], assertions=6, attendances=6)
    session.commit()

    order = [entry["title"] for entry in browse(session, roles=["growth"])["entries"]]
    assert order[0] == "Thick listing", f"capability evidence did not decide the order: {order}"


def _standing_writes(path=None):
    """Every expression this module assigns to `standing_inputs`, as an AST node."""
    tree = _module_tree(path or SERVICE)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "standing_inputs":
                    found.append(node.value)
        elif isinstance(node, ast.keyword) and node.arg == "standing_inputs":
            found.append(node.value)
    return found


def test_the_standing_is_only_ever_written_from_something_the_c08_scan_reads(seeded):
    """C-08, extended to the field the ordering reads but does not compute.

    `listing_ordering_inputs` is scanned by `test_listing_ranking_cannot_read_fee_fields` and may not name
    `Provider`. But it reads `standing_inputs`, and something else fills that in — so a fee written into
    `standing_inputs` on the write path would reach the ordering through a field the scan trusts. This
    reads every expression assigned to `standing_inputs` anywhere in the module and requires all of them
    to be free of the same vocabulary the ordering functions are.

    `publish` resolves the supplier's member id and hands it to `member_standing`, which IS one of the
    scanned ordering functions. That is the whole of the widening, and it is visible here.
    """
    writes = _standing_writes()
    assert len(writes) >= 3, f"only {len(writes)} writes to standing_inputs found — the scan is broken"
    offences = []
    for value in writes:
        for used in _names_in(value):
            if used.lower().lstrip("_") in FORBIDDEN_IN_ORDERING:
                offences.append(f"{ast.unparse(value)}: {used}")
    assert not offences, (
        "C-08: something commercial is written into the field the ordering reads. Found: "
        + "; ".join(offences)
    )


def test_that_scan_catches_a_fee_written_into_the_standing(tmp_path):
    """The guard on the guard. A scan that forbids what nobody writes passes for ever."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f(session, listing):\n"
        "    supplier = session.get(Provider, listing.provider_id)\n"
        "    listing.standing_inputs = {'capability_evidence': [supplier.billing_fee_chf]}\n",
        encoding="utf-8",
    )
    writes = _standing_writes(planted)
    assert writes, "the scan found no write in the planted file — it is not reading assignments at all"
    caught = [
        used
        for value in writes
        for used in _names_in(value)
        if used.lower().lstrip("_") in FORBIDDEN_IN_ORDERING
    ]
    assert caught, "the scan would not catch a fee written into standing_inputs"


# ============================================================ C-08 — the input a supplier writes itself


def test_declaring_every_role_cannot_outrank_earned_standing(session):
    """**C-08 through the input the fee scan does not look at.**

    A supplier writes its own `roles` and nobody audits them. While `role_match` was a COUNT of matched
    roles it was monotone in how many you declared, so a generalist with one assertion and four ticked
    boxes came out above a specialist with six assertions and six attendances on any multi-role query.
    Ordering could not be bought; it could be taken with a checkbox.
    """
    _evidenced(session, name="Generalist", roles=list(ROLES), assertions=1, attendances=0)
    _evidenced(session, name="Specialist", roles=["growth"], assertions=6, attendances=6)
    session.commit()

    order = [entry["title"] for entry in browse(session, roles=["growth", "income"])["entries"]]
    assert order[0] == "Specialist listing", (
        f"the supplier that ticked every role came first: {order}"
    )

    # And on the widest query there is, where the old count gave the generalist four to the specialist's
    # one. A share caps both at the same ceiling and the earned inputs decide.
    widest = [entry["title"] for entry in browse(session, roles=list(ROLES))["entries"]]
    assert widest[0] == "Specialist listing", f"declaring all four still won the widest query: {widest}"


def test_the_old_count_is_what_would_have_ranked_the_generalist_first(session):
    """The change stated as a result rather than as an intention.

    The order a COUNT of matched roles would have produced is computed here and asserted different, so
    "the specialist came first" is a consequence of the fix and not of the seed happening to sort that
    way. This is the same move `test_listing_ranking_cannot_read_fee_fields` makes with its fees.
    """
    _evidenced(session, name="Generalist", roles=list(ROLES), assertions=1, attendances=0)
    _evidenced(session, name="Specialist", roles=["growth"], assertions=6, attendances=6)
    session.commit()

    requested = ("growth", "income")
    listings = session.execute(select(Listing)).scalars().all()

    def counted(listing):
        return len(set(listing.roles or []) & set(requested))

    by_count = sorted(listings, key=lambda l: (-counted(l), -0, l.id))
    assert "Generalist" in by_count[0].title, "the old count would not have put the generalist first"

    order = [entry["title"] for entry in browse(session, roles=list(requested))["entries"]]
    assert "Specialist" in order[0]


def test_breadth_of_declaration_can_tie_but_never_beat():
    """The property that makes the fix principled rather than a tuned number.

    `role_match_share` is capped at `ROLE_MATCH_SCALE`, and the cap is reached by exactly the entries
    whose declared roles are all asked for. So no declaration can beat another declaration — the most it
    can do is tie, and a tie falls to capability evidence and community presence, which have to be earned.
    Checked over every non-empty declaration and every non-empty query rather than on an example.
    """
    from itertools import combinations

    subsets = [
        set(combination)
        for size in range(1, len(ROLES) + 1)
        for combination in combinations(ROLES, size)
    ]
    checked = 0
    for declared in subsets:
        for requested in subsets:
            share = role_match_share(sorted(declared), tuple(sorted(requested)))
            assert 0 <= share <= ROLE_MATCH_SCALE
            assert (share == ROLE_MATCH_SCALE) == declared.issubset(requested), (
                f"declared={sorted(declared)} requested={sorted(requested)} share={share}"
            )
            checked += 1
    assert checked == len(subsets) ** 2 == 225


def test_declaring_a_role_nobody_asked_for_lowers_the_input():
    """The incentive, inverted rather than merely blunted. Breadth is no longer free; it costs."""
    focused = role_match_share(["growth"], ("growth", "income"))
    padded = role_match_share(["growth", "protection"], ("growth", "income"))
    assert padded < focused, "adding an unrequested role did not cost anything"
    assert role_match_share(list(ROLES), ("growth", "income")) < focused


def test_role_match_is_still_an_ordering_input_and_not_a_constant(session):
    """The guard that the fix did not kill the input it was fixing.

    Making the input binary would have removed the incentive and R-203's first input with it: `browse`
    already filters to entries matching at least one requested role, so every survivor would score the
    same and the ordering would rest on two inputs. It still discriminates inside a result set.
    """
    # Identical evidence on both, so `role_match` is the only thing left that can separate them.
    _evidenced(session, name="Focused", roles=["growth"], assertions=1, attendances=0)
    _evidenced(session, name="Spread", roles=["growth", "protection"], assertions=1, attendances=0)
    session.commit()

    entries = browse(session, roles=["growth"])["entries"]
    assert [e["title"] for e in entries] == ["Focused listing", "Spread listing"]

    inputs = [
        listing_ordering_inputs(session.get(Listing, entry["id"]), ("growth",)) for entry in entries
    ]
    assert len({i.role_match for i in inputs}) == 2, (
        "role_match takes the same value for every entry in a result set — it is a dead input"
    )


def test_the_share_is_a_whole_number_of_twelfths(session):
    """Exactness, so two equal shares compare equal rather than nearly so.

    Twelve is the least common multiple of 1, 2, 3 and 4 — the numbers of roles an entry can declare — so
    every share this can produce is an integer and the ordering key stays free of floating point.
    """
    for size in range(1, len(ROLES) + 1):
        declared = list(ROLES[:size])
        assert role_match_share(declared, tuple(ROLES)) == ROLE_MATCH_SCALE
        assert isinstance(role_match_share(declared, ("growth",)), int)
    assert role_match_share(["growth", "income"], ("growth",)) == ROLE_MATCH_SCALE // 2
    assert role_match_share(["growth", "income", "protection"], ("growth",)) == ROLE_MATCH_SCALE // 3
    assert role_match_share(list(ROLES), ("growth",)) == ROLE_MATCH_SCALE // 4


def test_nothing_asked_for_means_no_role_input_at_all():
    """An unfiltered browse asks for no role, and then the order rests on the two earned inputs.

    That is the right answer rather than an accident: with no query there is no relevance to measure, and
    falling back to the count of declared roles would be ranking suppliers by how much they claim.
    """
    assert role_match_share(list(ROLES), ()) == 0
    assert role_match_share([], ("growth",)) == 0
    assert role_match_share(["not_a_role"], ("growth",)) == 0


def test_the_ordering_inputs_are_still_the_three_r203_names():
    """The fix changed how one input is computed, not how many there are. C-08's surface is unchanged."""
    assert ORDERING_INPUT_NAMES == ("role_match", "capability_evidence", "community_presence")
    assert "role_match_share" in ORDERING_FUNCTIONS, (
        "the function that computes an ordering input is not in the set the C-08 source scan reads"
    )


def test_paying_still_moves_nothing_with_the_role_input_live(session):
    """C-08's own check, re-run where `role_match` is doing work.

    `test_listing_ranking_cannot_read_fee_fields` browses with the filter removed, so every entry scores
    zero on `role_match` and the half-two attack lands on an order decided by the two earned inputs. That
    was true before this change and it is still true — but `role_match` is now a share rather than a
    count, so it is worth showing once that money moves nothing in a result set where that share differs
    between the entries and is the thing deciding the order.
    """
    _evidenced(session, name="Focused", roles=["growth"], assertions=1, attendances=0)
    _evidenced(session, name="Spread", roles=["growth", "protection"], assertions=1, attendances=0)
    session.commit()

    before = [entry["id"] for entry in browse(session, roles=["growth"])["entries"]]
    assert len(before) == 2

    inputs = [
        listing_ordering_inputs(session.get(Listing, listing_id), ("growth",)) for listing_id in before
    ]
    assert len({i.role_match for i in inputs}) == 2, "role_match is not what separates these two"

    bottom = session.get(Listing, before[-1])
    supplier = session.get(Provider, bottom.provider_id)
    supplier.billing_fee_chf = 24000.0
    supplier.billing_plan = "the_most_expensive_thing_we_sell"
    session.commit()
    assert session.get(Provider, bottom.provider_id).billing_fee_chf == 24000.0, (
        "the fee was not written — this would pass on an empty database"
    )

    assert [entry["id"] for entry in browse(session, roles=["growth"])["entries"]] == before, (
        "C-08: paying moved a listing in a result set the role input was ordering"
    )
