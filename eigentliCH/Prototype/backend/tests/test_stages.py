"""S-05 the stage map and S-09 the life-event modules: R-006, R-140 to R-143, R-180 to R-183, NG-02.

Most of what follows asserts that something is *not* there — no grading, no stage after 50, no mountain
word, no authored module — which is the kind of test that passes when it is broken. So every filter here
carries a guard that it can still fail, the lesson `test_content.py` and A20 already paid for.

**The word filters are imported rather than re-listed**, for the same reason `test_learning.py` gives:
`_whole_words` and its vocabulary live in `test_content.py` with the note explaining why substring
matching produced three false positives, and a second copy would be a second list to keep in step.

**The one test this file exists for is `test_no_life_event_module_is_authored`.** R-183 says ship the
framework with the modules empty rather than filling them with generated text, and the pressure to be
helpful — to write "what not to sign" for a separation because it would take ten minutes — is exactly what
that test is pointed at. Its failure is the news that a person wrote a module. Nothing else should ever
make it pass differently.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import eigentlich.services.stages as stages_module
from eigentlich.api.remainder import get_session, router
from eigentlich.content import CONTENT, LANGUAGES, ContentMissing
from eigentlich.db import create_all, make_session_factory
from eigentlich.services import register_member, store_item
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.services.stages import (
    LIFE_EVENT_KEYS,
    MODULE_FIELDS,
    NO_STAGE_AFTER,
    ModuleShapeDiffers,
    StageAfterTheLast,
    life_event_modules,
    module,
    module_is_authored,
    module_payload,
    modules,
    relevant_vault_items,
    stage,
    stage_map,
    stages,
)
from eigentlich.services.vault import VaultStore

# The authorities for the word filters. See this module's docstring for why they are not re-listed.
from test_content import (  # noqa: E402 - a sibling test module, on the path via pytest's rootdir
    GAMIFICATION_WORDS,
    MOUNTAIN_WORDS_DE,
    MOUNTAIN_WORDS_EN,
    _all_strings,
    _whole_words,
)

STAGES_FILE = CONTENT / "stages.json"
LIFE_EVENTS_FILE = CONTENT / "life-events.json"

SOURCES = [
    Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "stages.py",
    Path(__file__).resolve().parent.parent / "eigentlich" / "api" / "remainder.py",
]

#: NG-02 / R-142. Decumulation is a later scope, not a later stage, so its vocabulary may not appear in the
#: stage content in either language.
#:
#: Compounds are listed alongside their stems because matching is whole-word: `Entnahme` does not match
#: inside `Entnahmeplan`, and the compound is the form a drafter would actually reach for.
DRAWDOWN_WORDS = (
    "decumulation",
    "drawdown",
    "annuitisation",
    "annuitization",
    "entnahme",
    "entnahmen",
    "entnahmeplan",
    "rentenbezug",
    "kapitalbezug",
    "verrentung",
    "kapitalverzehr",
    "entsparen",
)

#: R-006 / R-140. Key names that would mean the map had started grading somebody. Checked as substrings of
#: the key rather than as whole words, because these are identifiers this build chose and a payload field
#: called `completion_percent` should fail on both halves.
#:
#: **The four at the bottom were missing, and R-140's own words were among them.** An audit planted
#: `"you_are_here": "career_start"`, `"stages_opened_so_far": 3` and `"grade": "B"` into the `stage_map`
#: payload and this file reported zero failures. R-140 is written as *no "you are here"*; the scan
#: forbidding it could not see the phrase the requirement is made of, which is close to the worst way for
#: an absence-shaped guard to be wrong — it reads as though the exact case were the one thing covered.
#:
#: **`opened` is deliberately NOT here bare, and the reason is worth keeping.** The audit reported it as
#: an omission and it was added and then taken out again: the stage map's own key
#: `any_stage_may_be_opened` contains it, and that key exists precisely to state that R-141 holds. A
#: filter forbidding a concept must not fire on the payload's statement that the concept is absent —
#: `not_indexed_by_profession` and `cell_filled` are the worked examples `test_content.py` records, and
#: this is a third. `so_far`, `stages_opened` and `opened_at` name the tally without naming its denial,
#: and between them they catch `stages_opened_so_far`, which is what the plant actually was. The
#: life-event payload's `opened_by_key` (R-182) is left alone by all three for the same reason.
GRADING_KEY_FRAGMENTS = (
    "progress",
    "percent",
    "rank",
    "score",
    "complete",
    "achiev",
    "current_stage",
    "locked",
    "unlock",
    "next_stage",
    "streak",
    "badge",
    "you_are_here",
    "youarehere",
    "grade",
    "stages_opened",
    "opened_at",
    "so_far",
)

#: R-140 as a SENTENCE rather than as a field name. The fragments above read keys; a stage map that says
#: "Sie sind hier" in its copy has done the same thing to a member and would pass every one of them.
POSITION_PHRASES = (
    "you are here",
    "sie sind hier",
    "you have reached",
    "sie haben erreicht",
    "ihr aktueller stand",
    "your current standing",
)


def _stage_content() -> dict:
    return json.loads(STAGES_FILE.read_text(encoding="utf-8"))


def _life_event_content() -> dict:
    return json.loads(LIFE_EVENTS_FILE.read_text(encoding="utf-8"))


def _stage_copy() -> str:
    """Every member-facing string in the stage content, lowercased.

    `_about` is excluded by `_all_strings`: it is a note to implementers, and it has to be able to name the
    words it forbids.
    """
    return " ".join(_all_strings(_stage_content())).lower()


def _code_only(path: Path) -> str:
    """One module's source with comments and docstrings removed — `test_learning.py`'s helper, same reason.

    A docstring quoting a constraint must not trip the check for it.
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


def _all_keys(node) -> list[str]:
    if isinstance(node, dict):
        return [k for key, value in node.items() for k in [key, *_all_keys(value)]]
    if isinstance(node, list):
        return [k for value in node for k in _all_keys(value)]
    return []


@pytest.fixture()
def api(tmp_path, fast_kdf):
    """The router on its own app with its own database. Yields `(client, member_id)`, authenticated.

    Deliberately not `eigentlich.api.main.app`: main.py is wired by hand, this router is not in it yet, and
    importing it would open the real database file to prove something about a payload. `StaticPool` pins
    the one in-memory connection that holds the schema, because `TestClient` serves on another thread.
    A11 was wired on 31 August 2026 and every member route now resolves its member from a bearer token.
    The fixtures below therefore register a credential, log in, and hand the `TestClient` a default
    `Authorization` header — so the tests read as they did, and the difference is that they are now going
    through the door rather than round it. `session_overrides` covers `api.auth.get_session` as well as the
    router's own, which is not optional: the token is resolved through that one, and overriding only the
    router's would authenticate against the developer's real database. See tests/conftest.py.
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
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, member.id
    engine.dispose()


# ============================================================ S-05: the five stages


def test_five_stages_in_the_specifications_own_order():
    """S-05 names them: 25 career start, 30 family and home, 35 own business, 45 a large asset, 50 optimising."""
    assert [(s["key"], s["age_marker"]) for s in stages()] == [
        ("career_start", 25),
        ("family_and_home", 30),
        ("own_business", 35),
        ("large_asset", 45),
        ("optimising", 50),
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_stage_describes_a_situation_in_both_languages(language):
    """R-140 and A12. A situation, stated in both languages, on every record."""
    for record in stages():
        payload = stages_module.stage_payload(record, language)
        assert payload["situation"], f"{record['key']} has no situation in {language}"
        assert payload["title"], f"{record['key']} has no title in {language}"


def test_a_stage_carries_questions_and_no_answers():
    """R-006 / C-01. Content navigation: the questions a situation raises, never what to do about them."""
    for record in stages():
        payload = stages_module.stage_payload(record, "de")
        assert payload["questions"], f"{record['key']} raises no questions"
        for question in payload["questions"]:
            assert question.strip().endswith("?"), f"{record['key']}: {question!r} is not a question"


def test_the_german_is_marked_unreviewed():
    """A42's precedent: a cleared draft flag claims a review that has not happened.

    The eight role definitions were read and signed off by their owner. These have not been, so every
    German string says `de_draft: true` and the file says `reviewed: false`.
    """
    data = _stage_content()
    assert data["reviewed"] is False
    for record in data["stages"]:
        for block in [record["title"], record["situation"], *record["questions"]]:
            assert block["de_draft"] is True, f"{record['key']}: a German string claims a review"
            assert block["de"], f"{record['key']}: a draft flag over a missing string"


# ============================================================ R-141


def test_a_member_may_open_any_stage_regardless_of_age(session):
    """R-141. The youngest member the age floor admits opens the stage marked 50, and the oldest opens 25."""
    youngest = register_member(session, age_at_registration=18, display_name="Youngest")
    oldest = register_member(session, age_at_registration=64, display_name="Oldest")
    session.commit()

    for member in (youngest, oldest):
        payload = stage_map(session, member_id=member.id)
        keys = [s["key"] for s in payload["stages"]]
        assert keys == [s["key"] for s in stages()], "a stage was withheld from a member"
        assert payload["any_stage_may_be_opened"] is True

    assert stage("optimising")["age_marker"] == 50
    assert stage("career_start")["age_marker"] == 25


def test_opening_a_stage_takes_no_age_argument():
    """R-141 held by an absent parameter rather than by an ignored one.

    "The age is ignored" is a claim a reader has to verify by reading the body. "There is no age
    parameter" is one they can verify from the signature, and it cannot rot.
    """
    for function in (stage, stages_module.stage_payload, stages_module.stage_map):
        names = set(inspect.signature(function).parameters)
        assert not (names & {"age", "age_at_registration", "member_age", "born"}), (
            f"{function.__name__} accepts an age; R-141 says any stage, regardless of it"
        )


def test_two_members_of_different_ages_get_the_same_stage_payloads(session):
    """The payloads are identical apart from the member id — nothing is tailored, so nothing ranks."""
    a = register_member(session, age_at_registration=18, display_name="A")
    b = register_member(session, age_at_registration=59, display_name="B")
    session.commit()
    first, second = stage_map(session, member_id=a.id), stage_map(session, member_id=b.id)
    assert first["stages"] == second["stages"]


def test_the_api_opens_any_stage(api):
    """R-141 over HTTP, and the route deliberately has no member parameter at all."""
    client, _member_id = api
    for record in stages():
        response = client.get(f"/api/stages/{record['key']}")
        assert response.status_code == 200
        assert response.json()["key"] == record["key"]


# ============================================================ R-140 / R-006


def test_the_stage_map_carries_nothing_that_grades_a_member(session, member):
    """R-140 and R-006: no grading, no locking, no 'you are here', no percentage, no rank."""
    payload = stage_map(session, member_id=member.id)
    offenders = [
        key
        for key in _all_keys(payload)
        if any(fragment in key.lower() for fragment in GRADING_KEY_FRAGMENTS)
    ]
    assert not offenders, f"R-006: the stage map payload carries {offenders}"


def test_the_stage_map_never_tells_a_member_where_they_are_in_words(session, member):
    """R-140 said as a sentence rather than as a field name.

    The fragment scan reads keys. "Sie sind hier" in a title is the same claim about the same member and
    carries no key at all, so it needs its own reader.

    **Planted:** set the German `situation` of the first stage to "Sie sind hier." in `stages.json`.
    Failed naming the phrase and the payload. Restored.
    """
    payload = stage_map(session, member_id=member.id)
    blob = json.dumps(payload, ensure_ascii=False, default=str).lower()
    for text in (blob, _stage_copy()):
        said = [phrase for phrase in POSITION_PHRASES if phrase in text]
        assert not said, f"R-140: the stage map tells a member where they are: {said}"


def test_the_grading_key_filter_actually_matches():
    """A guard on the guard. An empty offender list is what healthy and broken both look like.

    The last three entries are the audit's own plant, kept verbatim: it went into `stage_map` and this
    file reported zero failures, because R-140's phrasing — "you are here" — was not in the tuple that
    exists to forbid it.
    """
    fake = {
        "stages": [
            {
                "completion_percent": 40,
                "current_stage": "own_business",
                "you_are_here": "career_start",
                "stages_opened_so_far": 3,
                "grade": "B",
            }
        ]
    }
    found = [
        key
        for key in _all_keys(fake)
        if any(fragment in key.lower() for fragment in GRADING_KEY_FRAGMENTS)
    ]
    assert set(found) == {
        "completion_percent",
        "current_stage",
        "you_are_here",
        "stages_opened_so_far",
        "grade",
    }
    # And it still does not fire on the map's own vocabulary, which is what makes it usable.
    for innocent in ("opens_at", "opens_at_is_not_a_position", "any_stage_may_be_opened", "age_marker"):
        assert not any(fragment in innocent for fragment in GRADING_KEY_FRAGMENTS), innocent

    assert POSITION_PHRASES and all(" " in phrase for phrase in POSITION_PHRASES)


def test_the_stage_hint_is_where_the_map_opens_not_where_the_member_is(session, member):
    """R-140. `Member.stage_hint` is content routing, and the payload says so in a field of its own."""
    member.stage_hint = "own_business"
    session.commit()
    payload = stage_map(session, member_id=member.id)
    assert payload["opens_at"] == "own_business"
    assert payload["opens_at_is_not_a_position"] is True
    # Every stage still comes back, in the same shape, with nothing marking one as reached.
    assert len(payload["stages"]) == len(stages())


def test_an_unknown_stage_hint_is_not_echoed(session, member):
    """A hint pointing at a stage that does not exist opens the map at nothing, rather than at a phantom."""
    member.stage_hint = "retirement"
    session.commit()
    assert stage_map(session, member_id=member.id)["opens_at"] is None


def test_no_stage_record_carries_an_entry_condition():
    """R-141 in the content: `age_marker` is when a situation typically arrives, not who may read it."""
    for record in stages():
        assert not (set(record) & {"requires_age", "min_age", "max_age", "unlocks_at", "locked"})


# ============================================================ R-142 / NG-02


def test_there_is_no_stage_after_fifty():
    """R-142. Five stages, the last marked 50."""
    assert len(stages()) == 5
    assert max(s["age_marker"] for s in stages()) == NO_STAGE_AFTER == 50


def test_a_sixth_stage_beyond_fifty_is_refused_at_load(tmp_path, monkeypatch):
    """R-142 enforced, not merely observed.

    A record with `age_marker: 65` is drawdown content arriving through a JSON edit, and NG-02 says
    withdrawal sequencing is not in this product yet. Filtering it out silently would let somebody write it
    and find out on the day it did not ship.
    """
    data = _stage_content()
    data["stages"].append({**data["stages"][-1], "key": "later", "age_marker": 65})
    (tmp_path / "stages.json").write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(stages_module, "CONTENT", tmp_path)
    stages_module._stages.cache_clear()
    try:
        with pytest.raises(StageAfterTheLast):
            stages_module.stages()
    finally:
        stages_module._stages.cache_clear()


def test_no_drawdown_vocabulary_in_the_stage_content():
    """R-142 / NG-02, in both languages — A12 makes every copy rule a two-language rule."""
    found = _whole_words(DRAWDOWN_WORDS, _stage_copy())
    assert not found, (
        f"NG-02: decumulation is a later scope, not a later stage. Found {found} in the stage content."
    )


def test_the_drawdown_filter_actually_matches():
    """A guard on the guard, and on its word boundaries."""
    assert _whole_words(DRAWDOWN_WORDS, "die entnahme aus dem kapital") == ["entnahme"]
    assert _whole_words(DRAWDOWN_WORDS, "drawdown modelling") == ["drawdown"]
    assert _whole_words(DRAWDOWN_WORDS, "der rentenbezug") == ["rentenbezug"]
    assert _whole_words(DRAWDOWN_WORDS, "die einnahmen") == [], "must not fire inside Einnahmen"


def test_no_drawdown_vocabulary_in_the_phase_eight_source():
    """The same filter over this phase's own code, with comments and docstrings stripped.

    A helper called `entnahme_plan` would be NG-02 arriving as an identifier rather than as copy.
    """
    for path in SOURCES:
        found = _whole_words(DRAWDOWN_WORDS, _code_only(path))
        assert not found, f"NG-02: {path.name} contains {found}"


# ============================================================ R-143


def test_no_mountain_vocabulary_in_the_stage_content():
    """R-143, and this is the file most at risk of breaking it.

    "The climb" is the stage map's own marketing name — the specification's §5 heading says so — and this
    is where it would arrive in the authenticated product. Principle 10: metaphor in the marketing, plain
    language in the product.
    """
    found = _whole_words(MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE, _stage_copy())
    assert not found, f"R-143: the stage content uses {found}"


def test_no_mountain_vocabulary_in_the_phase_eight_source():
    """Identifiers too. A `climb_map` function would put the metaphor in every stack trace."""
    for path in SOURCES:
        found = _whole_words(MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE, _code_only(path))
        assert not found, f"R-143: {path.name} uses {found}"


def test_the_word_the_screen_is_named_after_is_absent():
    """The named risk, pinned separately so its failure message says what happened.

    R-143's most likely breach here is not a stray metaphor — it is somebody titling the screen after the
    name the specification itself gives it.
    """
    for text in (_stage_copy(), *(_code_only(p) for p in SOURCES)):
        assert not _whole_words(("climb", "the climb", "aufstieg"), text)


def test_no_gamification_vocabulary_in_the_stage_content():
    """C-07 as copy. A stage map is where a level scheme would arrive if one ever did."""
    found = _whole_words(GAMIFICATION_WORDS, _stage_copy())
    assert not found, f"C-07: the stage content uses {found}"


# ============================================================ S-09 / R-183 — the point of this file


def test_seven_life_event_modules_exist():
    """S-09 names seven: separation, job loss, illness and incapacity, death of a partner, inheritance,
    caring for parents, move abroad or return."""
    assert [m["key"] for m in modules()] == list(LIFE_EVENT_KEYS)
    assert len(LIFE_EVENT_KEYS) == 7


def test_no_life_event_module_is_authored():
    """**R-183. The test this file exists for.**

    "Module content is authored, not generated. Ship the framework with the modules empty rather than
    filling them with generated text." Every content field on every one of the seven is empty, and every
    module says `authored: false`.

    A person facing a separation or a death reads this screen in the worst week of their life, and "what
    not to sign" is a legal statement with consequences. Plausible text written by nobody is worse than a
    screen that says nothing yet — this is the case where a wrong answer is not a smaller version of a
    right one.

    **When this test fails, check who wrote the content before making it pass.** If a person authored a
    module, update the expectation. If anything else did, the fix is to delete the text.
    """
    for key in LIFE_EVENT_KEYS:
        record = module(key)
        assert module_is_authored(key) is False, f"{key} is marked authored — by whom?"
        assert record["title"]["de"] is None and record["title"]["en"] is None
        assert record["first_steps"] == [], f"{key}: first steps have been written"
        assert record["do_not_sign"] == [], f"{key}: 'what not to sign' has been written"
        assert record["vault_kinds"] == [], f"{key}: the vault kinds have been chosen"
        assert record["curator_role"] is None, f"{key}: a curator has been named"
        assert record["authored_by"] is None


def test_the_life_event_file_carries_no_prose_at_all():
    """The same claim from the other direction: no member-facing string exists anywhere in the file.

    The per-field assertions above would still pass if somebody added a `summary` key. This one would not.
    `_about` is excluded — it is a note to implementers and has to be able to explain itself.
    """
    keys_and_markers = set(LIFE_EVENT_KEYS) | {"life-events@0.1.0", "R-183"}
    prose = [s for s in _all_strings(_life_event_content()) if s not in keys_and_markers]
    assert not prose, f"R-183: the life-event modules carry authored text: {prose}"


def test_the_prose_scan_would_notice_prose():
    """A guard on the guard, and this one guards the requirement this phase is most likely to break.

    The test above passes on an empty file and on a correct one alike. If `_all_strings` ever stopped
    walking the modules, R-183 would be unenforced and green. So: inject a sentence of exactly the kind
    somebody would helpfully write, and assert it is caught.
    """
    injected = _life_event_content()
    injected["modules"][0]["do_not_sign"] = [
        {"de": "Unterschreiben Sie nichts, bevor Sie beraten wurden.", "en": "Sign nothing yet."}
    ]
    keys_and_markers = set(LIFE_EVENT_KEYS) | {"life-events@0.1.0", "R-183"}
    found = [s for s in _all_strings(injected) if s not in keys_and_markers]
    assert len(found) == 2, "the prose scan does not see authored text"


def test_every_module_has_the_same_shape():
    """R-180. The same four fields on all seven, empty or not — a module that differs is a second screen."""
    assert MODULE_FIELDS == ("first_steps", "do_not_sign", "vault_kinds", "curator_role")
    for key in LIFE_EVENT_KEYS:
        record = module(key)
        for field in MODULE_FIELDS:
            assert field in record, f"{key} is missing {field}"


def test_a_module_missing_a_field_is_refused_at_load(tmp_path, monkeypatch):
    """R-180 enforced rather than observed — the guard on the shape can still fail."""
    data = _life_event_content()
    del data["modules"][0]["do_not_sign"]
    (tmp_path / "life-events.json").write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(stages_module, "CONTENT", tmp_path)
    stages_module._life_events.cache_clear()
    try:
        with pytest.raises(ModuleShapeDiffers):
            stages_module.modules()
    finally:
        stages_module._life_events.cache_clear()


def test_an_unauthored_module_payload_says_so_rather_than_looking_finished(session, member):
    """R-183. The payload distinguishes "nobody has written this" from "there is nothing to say"."""
    payload = module_payload(session, key="separation", member_id=member.id)
    assert payload["authored"] is False
    assert payload["unauthored_reason"] == stages_module.NOT_AUTHORED
    assert payload["first_steps"] == [] and payload["do_not_sign"] == []
    assert payload["curator_role"] is None


def test_the_module_list_states_the_framework_is_unauthored(session, member):
    """A caller reading the list meets R-183 before it reads a single record."""
    payload = life_event_modules(session, member_id=member.id)
    assert payload["authored"] is False
    assert payload["unauthored_reason"] == "R-183"
    assert [m["key"] for m in payload["modules"]] == list(LIFE_EVENT_KEYS)
    assert all(m["authored"] is False for m in payload["modules"])


# ============================================================ R-181


def test_retrieval_by_kind_returns_the_members_own_items(session, member, tmp_path):
    """R-181. The module pulls the vault items; the member is never asked to go and find them."""
    store = VaultStore(tmp_path)
    store_item(session, store, member_id=member.id, kind="policy", title="Hausratversicherung",
               source="upload", data=b"police")
    store_item(session, store, member_id=member.id, kind="note", title="Notiz", source="manual")
    session.commit()

    found = relevant_vault_items(session, member_id=member.id, kinds=("policy",))
    assert [item["title"] for item in found] == ["Hausratversicherung"]
    assert "content" not in found[0], "C-04: a K3 payload must not carry the document itself"


def test_retrieval_returns_empty_when_the_vault_is_empty(session, member):
    """R-181's other half: an empty vault is an empty list, not an error and not a prompt to go looking."""
    assert relevant_vault_items(session, member_id=member.id, kinds=("policy", "contract")) == []


def test_an_unauthored_module_retrieves_nothing_and_says_which_kind_of_nothing(session, member, tmp_path):
    """The distinction R-181 and R-183 make together, and the reason it is a field rather than a comment.

    The member holds documents. The module returns none of them — because no module has named a kind to
    retrieve, not because the vault is empty. Those are different statements to make to somebody in the
    week after a death, so the payload keeps them apart.
    """
    store = VaultStore(tmp_path)
    store_item(session, store, member_id=member.id, kind="policy", title="Lebensversicherung",
               source="upload", data=b"police")
    session.commit()

    payload = module_payload(session, key="death_of_a_partner", member_id=member.id)
    assert payload["vault_items"] == []
    assert payload["vault_kinds"] == []
    assert payload["retrieval_unavailable_reason"] == stages_module.NOT_AUTHORED


# ============================================================ R-182


def test_a_module_is_addressed_by_its_key(session, member):
    """R-182. Reachable from The Know without navigating a menu: the key is the whole address."""
    payload = module_payload(session, key="job_loss", member_id=member.id)
    assert payload["opened_by_key"] == "job_loss"


def test_an_unknown_module_raises_rather_than_returning_a_blank_one(session, member):
    with pytest.raises(ContentMissing):
        module_payload(session, key="redundancy", member_id=member.id)


# ============================================================ over HTTP


def test_the_api_returns_the_stage_map(api):
    client, member_id = api
    payload = client.get("/api/stages", params={"member_id": member_id}).json()
    assert len(payload["stages"]) == 5
    assert payload["no_stage_after"] == 50
    offenders = [k for k in _all_keys(payload) if any(f in k for f in GRADING_KEY_FRAGMENTS)]
    assert not offenders, f"R-006: the HTTP payload carries {offenders}"


def test_the_api_refuses_an_unknown_language(api):
    """A12. A language nobody authored is a 422, never a silent fallback to the other one."""
    client, _ = api
    assert client.get("/api/stages", params={"language": "fr"}).status_code == 422


def test_the_api_lists_seven_unauthored_modules(api):
    client, member_id = api
    payload = client.get("/api/life-events", params={"member_id": member_id}).json()
    assert len(payload["modules"]) == 7
    assert payload["authored"] is False
    assert all(m["authored"] is False for m in payload["modules"])


def test_the_api_returns_one_module_in_the_shared_shape(api):
    client, member_id = api
    payload = client.get("/api/life-events/inheritance", params={"member_id": member_id}).json()
    assert payload["authored"] is False
    for field in MODULE_FIELDS:
        assert field in payload


def test_the_api_404s_an_invented_module(api):
    """Seven modules exist. An eighth is not created by asking for it."""
    client, _ = api
    assert client.get("/api/life-events/divorce_settlement").status_code == 404
