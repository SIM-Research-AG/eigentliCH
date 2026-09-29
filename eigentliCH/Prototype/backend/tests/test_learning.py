"""S-10: R-190, R-191, R-193, R-194, and the two constraints that bind the phase — C-07 and D-01.

The gate for phase 6 is an absence: *no level numbers or points in schema or UI*. Most of what follows
therefore asserts that something is not there, which is the kind of test that passes when it is broken. So
each filter carries a guard that it can still fail — the lesson A20 and `test_content.py` already paid for.

**The word filters are imported rather than re-listed.** `_whole_words` and its vocabulary live in
`test_content.py`, together with the note explaining why substring matching produced three false positives.
A second copy here would be a second list to keep in step, and the first divergence would be silent.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from eigentlich.api.learning import get_session, router
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.db import create_all, make_session_factory
from eigentlich.content import CONTENT, LANGUAGES, ContentMissing
from eigentlich.models import Capability, LearningUnit
from eigentlich.services import register_member
from eigentlich.services.learning import (
    NotMarkedFictional,
    capabilities,
    capability,
    capability_review,
    content_is_fictional,
    exits,
    learning_path,
    record_assertion,
    seed,
    statement,
    unit,
    units,
)

# The authorities for the word filters. See this module's docstring for why they are not re-listed.
from test_content import (  # noqa: E402 - a sibling test module, on the path via pytest's rootdir
    GAMIFICATION_WORDS,
    MOUNTAIN_WORDS_DE,
    MOUNTAIN_WORDS_EN,
    _all_strings,
    _whole_words,
    c07_identifier_offences,
)
from test_constraints import GAMIFICATION_IDENTIFIERS  # noqa: E402,F401

SOURCES = [
    Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "learning.py",
    Path(__file__).resolve().parent.parent / "eigentlich" / "api" / "learning.py",
]
LEARNING_FILE = CONTENT / "learning.json"

#: R-194 / NG-04. Re-exported so `test_marketplace.py` keeps importing it from here. **The list itself now
#: lives in `vocabulary.py`**, next to the other two vocabularies, because it had the same defect they had:
#: it was applied to `_seed_copy()` and to two source modules and to nothing else in the product, while
#: NG-04 says "in code, **copy**, or generated certificates". `test_content.py` now runs it over every
#: member-facing string on the server, which is where a claim of accreditation would actually be worth
#: something to whoever wrote it.
from vocabulary import ACCREDITATION_WORDS  # noqa: E402,F401


def _seed_content() -> dict:
    return json.loads(LEARNING_FILE.read_text(encoding="utf-8"))


def _seed_copy() -> str:
    """Every member-facing string in the seed content, lowercased.

    `_about` is excluded by `_all_strings`: it is a note to implementers, and it has to be able to name
    the words it forbids.
    """
    return " ".join(_all_strings(_seed_content())).lower()


def _code_only(path: Path) -> str:
    """One module's source with its comments and docstrings removed.

    A comment quoting the constraint must not trip the check for it — `test_client_bundle.py` makes the
    same move for the client bundle. Done through the AST rather than with a regex over triple quotes,
    because comments are simply not in the tree, and because a regex is what produced the confidently
    wrong answers this codebase keeps a note about.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    return ast.unparse(tree).lower()


@pytest.fixture()
def seeded(session):
    seed(session)
    session.commit()
    return session


@pytest.fixture()
def api(fast_kdf):
    """The router on its own app, with a seeded database and one member. Yields `(client, member_id)`.

    Deliberately not `eigentlich.api.main.app`: main.py is wired by hand, this router is not in it yet, and
    importing it here would open the real database file to prove something about a payload.

    **Its own engine, and not the `session` fixture's.** `TestClient` serves the request on a worker
    thread, and SQLAlchemy gives an in-memory SQLite database one connection per thread — so the request
    would find an empty schema. `StaticPool` pins the single connection that holds the schema.

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
        seed(api_session)
        member, _ = register_with_credentials(
            api_session,
            email="router@example.ch",
            password="ein ziemlich langes passwort",
            age_at_registration=41,
            display_name="Router Member",
        )
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


# ============================================================ D-01 — the scheme stays unset


def test_no_seeded_capability_carries_a_rung():
    """D-01. Every `rung` in the seed data is null. Inventing one is a defect, not a gap-fill."""
    for record in capabilities():
        assert record["rung"] is None, f"{record['key']} has been given a rung"


def test_seeding_writes_every_capability_with_a_null_rung(seeded):
    rows = seeded.execute(select(Capability)).scalars().all()
    assert rows, "nothing was seeded"
    for row in rows:
        assert row.rung is None, f"{row.id} was written with a rung"


def test_the_content_file_defines_no_rung_scheme():
    """D-01. No enum, no ordering, no thresholds — and no field a scheme could be read out of.

    The shape of a capability record is pinned exactly, which is the part that matters: a scheme arrives
    as a new key long before anyone writes it down as a decision.

    **D-01 was answered on 2026-08-31 (A82) and this test used to require the old wording.** It asserted
    `rung_scheme_open_decision == "D-01"` — i.e. that the content file still described the question as
    open — so the file could not be corrected without the test failing. The prohibition is unchanged and is
    what the rest of this test checks; what changed is that `rung_scheme` is null **permanently**, because
    a capability is the member's own self-assessment and eigentliCH never grades one (R-194), rather than null
    while a decision was pending.
    """
    data = _seed_content()
    assert data["rung_scheme"] is None
    assert data["rung_scheme_reason"] == "self_assessed_no_scheme_d01"
    assert "rung_scheme_open_decision" not in data, (
        "D-01 is answered; the content file must not describe it as an open decision"
    )
    for record in data["capabilities"]:
        assert set(record) == {"key", "fictional", "rung", "statement"}, (
            f"D-01: capability {record['key']} has grown a field: {sorted(set(record))}"
        )

    # And no scheme in the copy either. Bare "level" is deliberately absent from this vocabulary, for the
    # reason `test_content.py` gives: a capability statement legitimately asks at what *level* of annual
    # medical costs a Franchise turns over.
    found = _whole_words(
        ("rung", "rungs", "tier", "tiers", "grade", "grades", "stufe", "stufen", "niveau", "beginner",
         "advanced", "fortgeschritten"),
        _seed_copy(),
    )
    assert not found, f"D-01: the seeded copy invents a scheme — found {found}"


def test_both_payloads_state_that_there_is_no_scheme(session, member):
    """A null column says nothing to a client. The payload says it out loud instead.

    **The reason changed on 31 August 2026 and had to.** It used to read `undecided_d01`, which was true
    while D-01 was open. A82 answered D-01 — the member's own self-assessment — so there is no scheme, not
    a scheme still being chosen, and a payload that still said "undecided" would be giving a reason that
    had stopped being the reason. That is the defect `goal_illustration` carried for a month.
    """
    for payload in (
        learning_path(session, member_id=member.id),
        capability_review(session, member_id=member.id),
    ):
        assert payload["rung_scheme"] is None
        assert payload["rung_scheme_reason"] == "self_assessed_no_scheme_d01"
        assert "undecided" not in payload["rung_scheme_reason"], (
            "D-01 was answered by A82; a payload may only give a reason that is still the reason"
        )


def test_both_payloads_state_that_a_capability_is_the_members_own_claim(session, member):
    """D-01's answer (A82), on the wire. R-194: eigentliCH examines nothing and says so."""
    for payload in (
        learning_path(session, member_id=member.id),
        capability_review(session, member_id=member.id),
    ):
        assert payload["capabilities_are_self_asserted"] is True
        assert payload["capabilities_are_self_asserted_reason"] == "member_self_assessment_a82"
        assert payload["eigentlich_assesses_capabilities"] is False


def test_the_review_returns_a_null_rung_for_every_capability(session, member):
    for entry in capability_review(session, member_id=member.id)["capabilities"]:
        assert entry["rung"] is None


def test_file_order_is_denied_as_an_ordering(session, member):
    """File order is authoring convenience. A client reading it as a sequence reads a ladder nobody drew."""
    payload = capability_review(session, member_id=member.id)
    assert payload["capabilities_are_unordered"] is True
    assert [c["key"] for c in payload["capabilities"]] == [r["key"] for r in capabilities()]


def test_no_unit_is_gated_by_its_prerequisites(session, member):
    """R-190 says units *have* prerequisites. Whether meeting one unlocks a unit is D-01's question."""
    payload = learning_path(session, member_id=member.id)
    assert payload["units_are_not_gated"] is True
    for entry in payload["units"]:
        for forbidden in ("locked", "available", "unlocked", "met", "ready", "eligible"):
            assert forbidden not in entry, f"{entry['key']}: prerequisites became a gate ({forbidden})"


# ============================================================ C-07 / R-191


def test_no_gamification_vocabulary_in_the_seed_content():
    """C-07 as copy. The constraint is about the product, not only the schema."""
    found = _whole_words(GAMIFICATION_WORDS, _seed_copy())
    assert not found, f"C-07: found game-mechanic vocabulary in the seeded learning content: {found}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_gamification_vocabulary_in_the_phase_six_source(path):
    """The same filter over this phase's own code, with comments and docstrings stripped."""
    found = _whole_words(GAMIFICATION_WORDS + ("rank", "daily_goal"), _code_only(path))
    assert not found, f"C-07: found game-mechanic vocabulary in {path.name}: {found}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_gamification_identifiers_in_the_phase_six_source(path):
    """C-07 by identifier as well as by word, the way `test_constraints` walks the model layer.

    Words catch the copy; identifiers catch the field that has not been rendered yet. A payload key named
    `score` would pass a prose filter and still be the primitive the constraint forbids.

    **This file's copy of the walk was the only one that read `ast.Constant`**, and the string-literal
    clause below is the one that the other two were missing — which is how a column named `points` got
    into a schema with the model-layer test reporting 66 passed. The walk is now `c07_identifier_offences`
    in `test_content.py` and there is one of it.
    """
    offences = c07_identifier_offences(path)
    assert not offences, f"C-07 forbids gamification primitives. Found: {'; '.join(offences)}"


def test_no_gamification_vocabulary_in_the_served_payloads(session, member):
    """The payloads a client receives, not only the files they are built from."""
    blob = json.dumps(
        [learning_path(session, member_id=member.id), capability_review(session, member_id=member.id)],
        default=str,
    ).lower()
    found = _whole_words(GAMIFICATION_WORDS + ("rank", "daily_goal"), blob)
    assert not found, f"C-07: found game-mechanic vocabulary in an S-10 payload: {found}"


#: R-113 / R-006. The vocabulary of a completion meter. Whole-word matched like everything else here:
#: "count" sits inside "accounts", which is a word an English capability statement needs.
TALLY_WORDS = (
    "percent", "prozent", "progress", "fortschritt", "completion", "completed", "total", "count",
    "counts", "ratio", "anzahl", "remaining",
)


def test_no_payload_carries_a_tally_of_what_the_member_has_done(session, member):
    """R-113 and R-006. A '7 of 10' is the completion meter this product exists without."""
    blob = json.dumps(
        [learning_path(session, member_id=member.id), capability_review(session, member_id=member.id)],
        default=str,
    ).lower()
    found = _whole_words(TALLY_WORDS, blob)
    assert not found, f"R-113: an S-10 payload carries {found}"


def test_the_copy_scanner_actually_reads_the_seed_content():
    """Every filter below runs over `_seed_copy()`. An empty one would make all of them pass, silently."""
    copy = _seed_copy()
    assert len(copy.split()) > 300, f"the seed-copy scanner found only {len(copy.split())} words"
    assert "freizügigkeitskonto" in copy
    assert "requirement" not in copy, "`_about` leaked into the member-facing copy the filters scan"


def test_the_word_filter_is_not_vacuous():
    """Guard on the guard, twice over.

    `Franken` is the reason whole-word matching is not optional here: it contains `rank`, and a substring
    filter would fail on every capability statement that names an amount in Swiss francs.
    """
    assert _whole_words(("score",), "the score was high") == ["score"]
    assert _whole_words(("badge", "leaderboard"), "a badge on a leaderboard") == ["badge", "leaderboard"]
    assert _whole_words(("rank",), "in franken pro jahr") == [], "must not fire inside Franken"
    assert _whole_words(("count",), "two saeule 3a accounts") == [], "must not fire inside accounts"


def test_the_source_stripper_removes_prose_and_keeps_code():
    """The stripper above is what lets the docstrings quote the constraint. It has to actually work."""
    stripped = _code_only(SOURCES[1])
    assert "points" not in stripped, "the docstring quoting the phase gate was not stripped"
    assert "learning_path" in stripped, "the stripper removed code as well as prose"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_capability_is_a_sentence_a_member_can_read(language):
    """R-191. The statement IS the progression; there is nothing else to show, so it is never absent."""
    for record in capabilities():
        text = statement(record["key"], language)
        assert len(text.split()) >= 6, f"{record['key']} is a label, not a statement a member can read"


def test_a_missing_statement_raises_rather_than_falling_back():
    with pytest.raises(ContentMissing):
        statement("not_a_capability")


# ============================================================ R-190


def test_every_unit_evidences_at_least_one_capability():
    """R-190, second half."""
    for record in units():
        assert record["capability_keys"], f"{record['key']} evidences nothing"


def test_every_capability_reference_resolves():
    keys = {r["key"] for r in capabilities()}
    for record in units():
        unknown = [k for k in record["capability_keys"] if k not in keys]
        assert not unknown, f"{record['key']} names capabilities that do not exist: {unknown}"


def test_every_prerequisite_resolves_and_the_graph_terminates():
    """R-190, first half. A prerequisite naming a missing unit is a path with a hole in it."""
    known = {r["key"] for r in units()}
    for record in units():
        unknown = [k for k in record["prerequisites"] if k not in known]
        assert not unknown, f"{record['key']} requires units that do not exist: {unknown}"

    def depth(key: str, seen: frozenset[str]) -> int:
        assert key not in seen, f"prerequisites form a cycle through {key}"
        return 1 + max((depth(p, seen | {key}) for p in unit(key)["prerequisites"]), default=0)

    for record in units():
        depth(record["key"], frozenset())


def test_at_least_one_unit_has_no_prerequisite():
    """Otherwise the path has no way in, whatever the graph says."""
    assert any(not r["prerequisites"] for r in units())


def test_the_payload_names_prerequisites_as_facts_not_as_a_gate(seeded, member):
    payload = learning_path(seeded, member_id=member.id)
    entry = next(u for u in payload["units"] if u["prerequisites"])
    prerequisite = entry["prerequisites"][0]
    assert prerequisite["title"], "a prerequisite is shown as a key rather than as a title"
    # Nothing evidenced yet, so every capability of the prerequisite is reported as lacking evidence.
    assert prerequisite["capabilities_without_evidence"] == unit(prerequisite["key"])["capability_keys"]


def test_no_unit_ships_generated_lesson_prose():
    """R-183's call, applied here: ship the framework empty rather than filling it with generated text."""
    for record in units():
        assert record["body_ref"] is None, f"{record['key']} ships a body nobody authored"


def test_the_payload_says_why_there_is_no_body(session):
    for entry in learning_path(session)["units"]:
        assert entry["body_ref"] is None
        assert entry["body_unavailable_reason"] == "not_authored"


# ============================================================ R-193


def test_three_exits_are_named_in_the_content():
    assert [r["key"] for r in exits()] == ["run_own_affairs", "offer_a_service", "start_a_venture"]


def test_only_the_second_and_third_exit_touch_the_market_place():
    """R-193, stated exactly. Running your own affairs ends with the member and leads nowhere else."""
    touching = {r["key"] for r in exits() if r["touches_market_place"]}
    assert touching == {"offer_a_service", "start_a_venture"}


def test_the_exits_reach_the_payload_with_their_market_place_flag(session):
    payload = learning_path(session)
    assert {e["key"] for e in payload["exits"] if e["touches_market_place"]} == {
        "offer_a_service",
        "start_a_venture",
    }


def test_a_unit_names_an_exit_only_where_it_leads_to_one():
    named = {key for record in units() for key in record["exits"]}
    assert named <= {r["key"] for r in exits()}
    assert named, "no unit names an exit, so R-193's three are decoration"


# ============================================================ R-194 / NG-04


def test_no_claim_of_federal_or_accredited_status_in_the_seed_content():
    """R-194. These statements are eigentliCH's own and claim nothing else."""
    found = _whole_words(ACCREDITATION_WORDS, _seed_copy())
    assert not found, f"NG-04: the seeded content claims a qualification it does not have: {found}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_claim_of_federal_or_accredited_status_in_the_source(path):
    found = _whole_words(ACCREDITATION_WORDS, _code_only(path))
    assert not found, f"NG-04: {path.name} claims a qualification eigentliCH does not award: {found}"


def test_the_accreditation_filter_is_not_vacuous():
    """It would pass silently on an empty vocabulary or a broken pattern."""
    assert _whole_words(ACCREDITATION_WORDS, "ein eidgenössisch anerkannter fachausweis") == [
        "eidgenössisch",
        "fachausweis",
    ]
    assert _whole_words(ACCREDITATION_WORDS, "der vorsorgeausweis") == [], "must not fire on Vorsorgeausweis"


def test_the_payload_states_that_no_qualification_is_claimed(session):
    """Explicit rather than inferred from an absent key, the way `illustration_unavailable_reason` is."""
    payload = learning_path(session)
    assert payload["qualification_claim"] is None
    assert payload["qualification_claim_reason"] == "eigentlich_states_capabilities_only"


def test_no_mountain_vocabulary_in_the_seed_content():
    """R-143, in both languages. A12 makes every copy rule a two-language rule."""
    found = _whole_words(MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE, _seed_copy())
    assert not found, f"R-143: metaphor belongs in the marketing surfaces, not here. Found: {found}"


# ============================================================ A41 — fictional, and marked so


def test_the_content_file_declares_itself_fictional():
    assert content_is_fictional() is True


def test_every_seeded_record_is_marked_fictional():
    """A41. In the data itself, so a screenshot cannot be mistaken for real."""
    data = _seed_content()
    for group in ("capabilities", "units", "exits"):
        for record in data[group]:
            assert record.get("fictional") is True, f"{group}/{record['key']} is not marked fictional"


def test_the_marker_survives_into_the_payloads(session):
    path = learning_path(session)
    assert path["fictional"] is True
    assert all(u["fictional"] is True for u in path["units"])
    assert all(e["fictional"] is True for e in path["exits"])
    review = capability_review(session)
    assert review["fictional"] is True
    assert all(c["fictional"] is True for c in review["capabilities"])


def test_seeding_refuses_a_record_that_is_not_marked(session, monkeypatch):
    """The marker is load-bearing, not decorative. This is what makes that true."""
    unmarked = [dict(capabilities()[0], fictional=False)]
    monkeypatch.setattr("eigentlich.services.learning.capabilities", lambda: unmarked)
    with pytest.raises(NotMarkedFictional):
        seed(session)


def test_a_seeded_unit_traces_back_to_the_fictional_content_record(seeded):
    """The model layer is fixed this phase, so the marker lives in the file. `body_ref` is the thread back."""
    for row in seeded.execute(select(LearningUnit)).scalars().all():
        assert row.body_ref == f"learning.json#units.{row.id}"


def test_seeded_content_claims_no_owner(seeded):
    """Fictional demonstration content has no owner to name, and naming one would be the claim A41 guards."""
    for row in seeded.execute(select(LearningUnit)).scalars().all():
        assert row.ip_owner is None


# ============================================================ A12 — bilingual, de-CH authored


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_member_facing_string_exists_in_both_languages(language):
    """A12. A missing German string is a failure now rather than a re-authoring later."""
    data = _seed_content()
    for record in data["capabilities"]:
        assert record["statement"].get(language), f"{record['key']} has no {language} statement"
    for record in data["units"]:
        assert record["title"].get(language), f"{record['key']} has no {language} title"
        assert record["summary"].get(language), f"{record['key']} has no {language} summary"
    for record in data["exits"]:
        assert record["name"].get(language), f"{record['key']} has no {language} name"
        assert record["description"].get(language), f"{record['key']} has no {language} description"


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

    walk(_seed_content())


def test_german_is_what_is_stored_and_english_is_rendered_on_request(seeded):
    """The row carries the authored language; the sentence a member reads comes from the content record."""
    row = seeded.get(Capability, "freizuegigkeitskonto_kosten")
    assert row.statement == capability("freizuegigkeitskonto_kosten")["statement"]["de"]
    english = learning_path(seeded, language="en")
    assert any(
        e["statement"] == capability(e["key"])["statement"]["en"]
        for u in english["units"]
        for e in u["evidences"]
    )


# ============================================================ seeding and assertions


def test_seeding_is_idempotent(session):
    first = seed(session)
    session.commit()
    second = seed(session)
    session.commit()
    assert first["capabilities"] and first["units"]
    assert second == {"capabilities": [], "units": []}


def test_every_key_fits_the_id_column():
    """The content key is the row id. A key too long for `String(32)` would truncate silently on SQLite."""
    for record in list(capabilities()) + list(units()):
        assert len(record["key"]) <= 32, f"{record['key']} is {len(record['key'])} characters"


def test_an_assertion_shows_up_against_its_statement(seeded, member):
    record_assertion(
        seeded,
        member_id=member.id,
        capability_id="fixkosten_eines_monats",
        evidence_kind="conversation_with_a_curator",
        assessed_by="curator:demo",
        assessed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    seeded.commit()
    review = capability_review(seeded, member_id=member.id)
    entry = next(c for c in review["capabilities"] if c["key"] == "fixkosten_eines_monats")
    assert entry["evidenced"] is True
    assert entry["evidence"][0]["assessed_by"] == "curator:demo"
    assert entry["evidence"][0]["evidence_kind"] == "conversation_with_a_curator"
    others = [c for c in review["capabilities"] if c["key"] != "fixkosten_eines_monats"]
    assert all(c["evidenced"] is False for c in others)


def test_recording_an_assertion_decides_nothing_about_assessment(seeded, member):
    """D-01. No enum of evidence kinds, no rule about who may assess, nothing inferred from the row."""
    assertion = record_assertion(
        seeded,
        member_id=member.id,
        capability_id="franchise_rechnung",
        evidence_kind="anything at all, and nobody has decided what belongs here",
        assessed_by="the member themselves",
    )
    seeded.commit()
    assert assertion.evidence_kind.startswith("anything at all")
    assert seeded.get(Capability, "franchise_rechnung").rung is None


def test_an_assertion_against_an_unknown_capability_raises(session, member):
    with pytest.raises(ContentMissing):
        record_assertion(
            session,
            member_id=member.id,
            capability_id="not_seeded",
            evidence_kind="conversation",
            assessed_by="curator:demo",
        )


def test_the_review_without_a_member_shows_the_statements_and_no_evidence(session):
    """A client rendering S-10 before sign-in needs the statements; it does not need a member."""
    review = capability_review(session)
    assert len(review["capabilities"]) == len(capabilities())
    assert all(c["evidence"] == [] for c in review["capabilities"])


# ============================================================ the router


def test_the_learning_path_endpoint_returns_the_units(api):
    client, member_id = api
    response = client.get("/api/learning", params={"member_id": member_id})
    assert response.status_code == 200
    body = response.json()
    assert [u["key"] for u in body["units"]] == [r["key"] for r in units()]
    assert body["rung_scheme"] is None
    assert body["fictional"] is True


def test_the_capability_endpoint_returns_the_statements(api):
    client, member_id = api
    response = client.get("/api/capabilities", params={"member_id": member_id})
    assert response.status_code == 200
    body = response.json()
    assert len(body["capabilities"]) == len(capabilities())
    assert all(c["rung"] is None for c in body["capabilities"])
    assert all(c["evidenced"] is False for c in body["capabilities"])


def test_the_exits_endpoint_answers_without_a_member(api):
    """R-193. The exits are the answer to 'what is this for' and need no member to be shown."""
    client, _ = api
    body = client.get("/api/learning/exits").json()
    assert len(body["exits"]) == 3
    assert [e["touches_market_place"] for e in body["exits"]] == [False, True, True]


def test_the_router_serves_both_languages(api):
    client, _ = api
    german = client.get("/api/learning", params={"language": "de"}).json()
    english = client.get("/api/learning", params={"language": "en"}).json()
    assert german["units"][0]["title"] != english["units"][0]["title"]


def test_an_unknown_language_is_refused(api):
    client, _ = api
    assert client.get("/api/learning", params={"language": "fr"}).status_code == 422


def test_the_router_exposes_exactly_the_routes_it_means_to():
    """A route nobody meant to add is how an assessment scheme would arrive.

    **This test used to assert the router was read-only**, and the reason it gave was sound: "an HTTP verb
    is a decision about how a capability is assessed, described as a route", and D-01 owned that decision.
    A82 answered D-01 on 31 August 2026, so the verb no longer decides anything — it carries out a
    decision somebody else made. What survives of the old rule is that there is exactly **one** write here
    and it is the member's own assertion: no grading route, no curator route, no route that takes a rung.
    """
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/learning",
        "/api/learning/exits",
        "/api/capabilities",
        "/api/capabilities/assertions",
    }
    writes = sorted(
        (sorted(route.methods - {"HEAD", "OPTIONS"})[0], route.path)
        for route in router.routes
        if route.methods - {"GET", "HEAD", "OPTIONS"}
    )
    assert writes == [("POST", "/api/capabilities/assertions")], (
        f"D-01 / A82: the only write on the learning surface is a member asserting a capability about "
        f"themselves. Found: {writes}"
    )
