"""Content records: R-111, R-143, D-03, D-07, and the bilingual rule from A12."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from eigentlich.content import (
    CONTENT,
    LANGUAGES,
    ContentMissing,
    destination,
    role,
    role_definition,
    role_display,
    roles,
    roles_are_provisional,
)
from eigentlich.models import ROLES

# R-143 and C-07 vocabularies live in `vocabulary.py`, imported by BOTH this module and
# `test_client_bundle.py`. They used to be two literal copies, and the client copy claimed in a
# comment to match this one while omitting `hut`, `berg` and `tour`. Two lists that must agree,
# maintained separately — the same defect as A73 and A63. Divergence is now unexpressible.
from vocabulary import (  # noqa: E402
    ACCREDITATION_WORDS,
    GAMIFICATION_IDENTIFIERS,
    GAMIFICATION_WORDS,
    MOUNTAIN_FORMS_DE,
    MOUNTAIN_FORMS_EN,
    MOUNTAIN_WORDS_DE,
    MOUNTAIN_WORDS_EN,
    mountain_hits,
)

BACKEND_PACKAGE = Path(__file__).resolve().parent.parent / "eigentlich"


def _whole_words(words, haystack: str) -> list[str]:
    """Whole-word matching, not substring.

    Substring matching gave three false positives on the first run: `hut` inside "Schutz", `peak` inside
    "peaks in contraction", and `level` inside "leverage". A word filter that fires on the word it is meant
    to protect is worse than no filter, because the fix is to damage the copy.

    ("Schutz" was the draft German label for the Protection role and is now `Absicherung`. The example is
    kept because the failure mode is not specific to it: any German compound can contain an English word.)

    **This function is for PROSE. For identifiers, use `_whole_words_in_identifier`.** The underscore is a
    word character, so `\\b` does not break at it: `\\bcount\\b` never fires inside `asserted_count`, and a
    payload *key* is precisely where a tally word arrives underscore-joined. An agent found that by
    planting `"asserted_count": 1` and watching this filter pass it — a plant meant to prove the filter
    fires, proving the opposite.

    **The obvious fix — splitting on `_` here, for every caller — was tried and reverted.** Two legitimate
    identifiers failed immediately and one of them is instructive: `not_indexed_by_profession` is a payload
    key that exists **to assert the absence** of the forbidden concept, and splitting it made the filter
    forbidding that concept fire on the statement that it is absent. `cell_filled` is the other — `filled`
    is forbidden as a *tally* (`filled: 3, total: 8`), not as a statement that one cell holds something.

    So the two scans stay separate and a caller has to say which one it is doing.
    """
    return [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", haystack)]


def _whole_words_in_identifier(words, haystack: str) -> list[str]:
    """As `_whole_words`, but reads `snake_case` as words — for payload keys and code identifiers.

    Use this where the haystack is a *name* rather than a sentence: JSON keys, attribute names, the
    identifiers in a source file. `my_score` and `punkte_total` are caught here and not by `_whole_words`.

    **It over-reports on a name that denies the concept** — `not_indexed_by_profession` is the worked
    example — so a caller scanning identifiers needs either a short allowlist or a scan restricted to the
    names it owns. That cost is exactly why this is a second function rather than a wider `\\b`.
    """
    separated = haystack.replace("_", " ")
    return sorted(
        {
            w
            for w in words
            if re.search(r"\b" + re.escape(w) + r"\b", haystack)
            or re.search(r"\b" + re.escape(w) + r"\b", separated)
        }
    )


def _all_strings(node) -> list[str]:
    """Every member-facing string. `_about` is excluded: it is a note to implementers, not copy."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() if k != "_about" for s in _all_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _all_strings(v)]
    return []


def _role_copy() -> str:
    data = json.loads((CONTENT / "roles.json").read_text(encoding="utf-8"))
    return " ".join(_all_strings(data)).lower()


# ============================================================ the one member-facing string scan


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Every module, class and function docstring removed, so a note may name what it forbids.

    `test_learning._code_only` makes the same move and gives the same reason. Comments need no handling:
    they are not in the tree at all.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        while (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
        if not body:
            body.append(ast.Pass())
    return tree


def _package_sources() -> list[Path]:
    return [p for p in sorted(BACKEND_PACKAGE.rglob("*.py")) if "__pycache__" not in p.parts]


def member_facing_strings() -> list[tuple[str, str]]:
    """Every string this product can put in front of a member, wherever it is composed.

    **Why this exists.** R-143's §11 check was `test_no_mountain_vocabulary_in_authenticated_strings`, and
    what it actually read was `_role_copy()` — `client/content/roles.json`, one file out of seven. No test
    anywhere scanned a member-facing literal on the server side: not a refusal text, not a notice, not an
    action item's consequence, not any sentence a module composes. An audit planted seven mountain words
    into `boundary.py`'s German refusal and into `services/community.py` and `services/know.py` payload
    strings and the suite stayed green on all seven. NG-04 had the same hole from the other side: its
    vocabulary was applied to one seed file and two modules, and "in code, copy, or generated
    certificates" covers rather more than that.

    The repair is not a seventh per-file scanner. It is one collector with two arms, because a
    member-facing sentence has exactly two homes in this build:

      * **every** `client/content/*.json`, not only `roles.json` — `_all_strings` drops `_about`, which is
        a note to implementers and has to be able to name the words it forbids;
      * **every string literal in `backend/eigentlich/**/*.py`**, docstrings removed. Blunt on purpose: a
        scanner that tried to tell a member-facing sentence from an internal key would be a judgement
        somebody has to keep making correctly, and the whole finding here is that per-file judgement is
        what failed. The vocabularies it carries were run over the entire package before this was written
        and neither produced a single false positive, which is what makes the bluntness affordable.

    **`GAMIFICATION_WORDS` is deliberately NOT one of them, and this is the reason.** Run over the whole
    package it fires four times, and all four are the shape that gets a filter switched off within a week:
    `boundary.py`'s own detector pattern `(?:rangfolge|reihenfolge|rangliste)`, which is the code
    *enforcing* C-07; `services/export.py`'s note that "there is no level number and no score anywhere in"
    the export; a sentence in `services/engine_inputs.py`; and `services/grounding.py`'s literal `score`,
    which is an engine's field name and A6 scoped C-07 away from the estate's Score on purpose. A blunt
    scan that fires on the sentence denying the concept is the `not_indexed_by_profession` failure at
    package scale. C-07 keeps its existing per-surface readers — role copy, stage content, learning seed,
    Befund payload, marketplace copy — plus `c07_identifier_offences` for the schema, and widening it to
    the whole package needs a scoped allowlist that nobody has needed yet. R-143 and NG-04 have no such
    conflict, which is why they get the broad scan and C-07 does not.

    Returns `(origin, string)` pairs so a failure says which file to open.
    """
    out: list[tuple[str, str]] = []
    for path in sorted(CONTENT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.extend((path.name, s) for s in _all_strings(data))
    for path in _package_sources():
        origin = path.relative_to(BACKEND_PACKAGE.parent).as_posix()
        tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append((f"{origin}:{node.lineno}", node.value))
    return out


#: `services/befund.py` names the engines whose gaps are withheld from a member, and `score_engine` is
#: one of them. That string exists to keep the estate's Score out of a member's report — and
#: `test_the_estates_score_engine_is_never_surfaced_to_a_member` is what holds it there — so a C-07
#: filter firing on it would be firing on the statement that the concept is absent. Same shape as
#: `not_indexed_by_profession`, which `_whole_words_in_identifier` documents at length.
C07_PERMITTED_LITERALS = frozenset({"score_engine"})


def c07_identifier_offences(path: Path) -> list[str]:
    """C-07's AST walk, once, for every caller that reads a source file for gamification primitives.

    **This was three near-copies** — `test_constraints.py` over the model layer, `test_befund.py` over the
    Befund service and route, `test_learning.py` over phase six — and they had drifted. Only the third
    looked at `ast.Constant`, so a column named by string literal was invisible to the other two: an audit
    planted `tally: Mapped[int] = mapped_column("points", Integer, ...)`, which puts a column called
    `points` in the schema, and `test_constraints.py` reported 66 passed. `test_befund.py` imported the
    same set and shared the hole. Two scanners that must agree, maintained separately — the defect
    `vocabulary.py` exists to make unexpressible, in its other half.

    So there is one walk, it looks at `ast.Constant`, and it matches with `_whole_words_in_identifier`
    rather than by set membership, which is the second half of the same finding: `grid_completion_score`,
    `points_earned`, `streak_days` and `xp_total` are all a tally primitive and none of them is an element
    of `GAMIFICATION_IDENTIFIERS`.

    Docstrings are stripped, for `_code_only`'s reason: a docstring quoting the constraint must not trip
    the check for it.
    """
    tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    offences: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, ast.keyword) and node.arg:
            names = [node.arg]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names = [node.value]
        for name in names:
            cleaned = name.lower().strip().lstrip("_")
            if cleaned in C07_PERMITTED_LITERALS:
                continue
            found = _whole_words_in_identifier(GAMIFICATION_IDENTIFIERS, cleaned)
            if found:
                offences.append(f"{path.name}:{getattr(node, 'lineno', '?')} {name!r} {found}")
    return offences


# ============================================================ R-111 / D-03


def test_all_four_roles_have_content_records():
    """R-111. Definitions are content records, not hardcoded strings."""
    keys = [r["key"] for r in roles()]
    assert set(keys) == set(ROLES)


def test_role_definitions_ship_marked_provisional():
    """D-03. They come from a published model and are provisional until reviewed."""
    assert roles_are_provisional() is True


@pytest.mark.parametrize("key", ROLES)
@pytest.mark.parametrize("capital_type", ("human", "financial"))
def test_every_role_defines_both_kinds_of_capital(key, capital_type):
    """R-114 / principle 9. Both kinds of capital, together, for every role."""
    assert role_definition(key, capital_type, "en"), f"{key}/{capital_type} has no English definition"
    assert role_display(key, capital_type, "en")


@pytest.mark.parametrize("key", ROLES)
@pytest.mark.parametrize("capital_type", ("human", "financial"))
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_definition_exists_in_both_languages(key, capital_type, language):
    """A12. Bilingual from the start, so a missing German string is a failure now, not a retrofit later."""
    assert role_definition(key, capital_type, language)


def test_growth_displays_as_gain_on_the_financial_side():
    """The source manual's own distinction: `Gain` financially, `Growth` for human capital.

    The build spec's §4 enum says `growth`, so the stored key stays `growth` and only the display differs.
    This test exists so that reconciliation cannot be quietly undone by someone tidying the file.
    """
    assert role_display("growth", "financial", "en") == "Gain"
    assert role_display("growth", "human", "en") == "Growth"
    assert role("growth")["key"] == "growth"


def test_missing_content_raises_rather_than_falling_back():
    with pytest.raises(ContentMissing):
        role("not_a_role")


def test_german_role_terms_are_the_reviewed_ones():
    """The four German labels were corrected by their owner on 30 August 2026, not drafted by me.

    Pinned because they are the kind of string a later pass "improves" back to the obvious translation.
    `Schutz` in particular is the dictionary word for protection and the wrong term of art here.
    """
    assert role_display("protection", "human", "de") == "Absicherung"
    assert role_display("protection", "financial", "de") == "Absicherung"
    assert role_display("growth", "human", "de") == "Wachstum"
    assert role_display("growth", "financial", "de") == "Wertsteigerung"
    assert role_display("income", "human", "de") == "Einkommen"
    assert role_display("income", "financial", "de") == "Einkommen"
    assert role_display("stabilisation", "human", "de") == "Stabilisierung"


# ============================================================ D-07


@pytest.mark.parametrize("language", LANGUAGES)
def test_destination_comes_from_one_key(language):
    """D-07. All destination copy comes from a single content key."""
    assert destination(language)


def test_destination_matches_the_specs_own_phrasing():
    assert destination("en") == "a self-determined life"
    assert destination("de") == "ein selbstbestimmtes Leben"


def test_destination_phrase_is_not_inlined_anywhere_in_the_backend():
    """The point of one key is that nothing else says it. This is what makes that checkable.

    Scans the application source for the phrase as a literal. The content file and this test are the only
    places it may appear.
    """
    backend = CONTENT.parent.parent / "backend" / "eigentlich"
    offenders = []
    for path in backend.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        if "a self-determined life" in text or "ein selbstbestimmtes leben" in text:
            offenders.append(path.name)
    assert not offenders, (
        f"D-07: the destination phrase is inlined in {offenders}. It comes from content.destination() "
        f"and nowhere else."
    )


def test_the_destination_key_is_reachable_over_http_in_both_languages():
    """D-07 / A22. **The test above passed because nothing said the phrase at all.**

    That is the finding this test exists for. A22 resolved D-07 by promoting the specification's §1
    phrasing into one content key and reading it through `content.destination()`, and the scan above
    confirmed nothing inlined it — which was true, and true for the wrong reason:
    `content.destination()` had no production caller and appeared in no API payload, so the one key D-07
    asked for was a key no screen could reach. An absence-shaped test (A20, A66, A68) passing over an
    absence is exactly the shape this build keeps being bitten by, and the fix is a test that requires the
    phrase to be *present somewhere reachable* rather than only absent from the wrong places.

    **Planted violation:** removed the `@app.get("/api/destination")` route from `api/main.py`. This test
    failed with 404 on both languages while `test_destination_phrase_is_not_inlined_anywhere_in_the_backend`
    stayed green — the two halves demonstrably independent. Restored.
    """
    from fastapi.testclient import TestClient

    from eigentlich.api.main import app

    client = TestClient(app)

    for language in LANGUAGES:
        response = client.get("/api/destination", params={"language": language})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["language"] == language
        assert body["destination"] == destination(language), (
            "the route must serve the content key rather than a phrase of its own"
        )
        assert body["destination"].strip() == body["destination"]

    # Default is de-CH (A12), asked for without a parameter the way a first render asks.
    assert client.get("/api/destination").json()["destination"] == destination("de")

    # No fallback. A language nobody authored is refused rather than answered in another one, because a
    # silent fallback is how one key becomes a phrase people believe was translated.
    refused = client.get("/api/destination", params={"language": "fr"})
    assert refused.status_code == 422
    assert "fr" in refused.text


# ============================================================ R-143 / C-07 as copy


def test_no_mountain_vocabulary_in_authenticated_strings():
    """R-143. In both languages — A12 makes this a two-language rule."""
    found = _whole_words(MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE, _role_copy())
    assert not found, (
        f"R-143: metaphor belongs in the marketing surfaces, not the authenticated product. Found: {found}"
    )


def test_no_gamification_vocabulary_in_role_copy():
    """C-07 as copy, not only as schema."""
    found = _whole_words(GAMIFICATION_WORDS, _role_copy())
    assert not found, f"C-07: found gamification vocabulary in role copy: {found}"


def test_no_mountain_vocabulary_in_any_member_facing_string():
    """R-143 over every string the product can show, wherever it is composed. See `member_facing_strings`.

    The named check above reads one content file. This one reads all seven, and every string literal in
    `backend/eigentlich/` as well, because a refusal text and an action item's consequence are copy just as
    much as a role definition is.

    **Planted:** `Der Aufstiegs-Gipfelweg über die Bergetappe zum Basislager: summits, climbing,
    Gipfelsturm, Bergführer.` into `boundary.py`'s German REFUSAL, into a `services/community.py` payload
    string and into a `services/know.py` payload string. Failed naming all three origins and the stems
    `aufstieg`, `basislager`, `berg`, `climb`, `gipfel`, `summit`. Restored.
    """
    offenders = [
        (origin, sorted(mountain_hits(text)), text[:80])
        for origin, text in member_facing_strings()
        if mountain_hits(text)
    ]
    assert not offenders, (
        f"R-143: the metaphor belongs to the marketing surfaces, not the authenticated product. "
        f"Found in {len(offenders)} strings: {offenders[:12]}"
    )


def test_no_accreditation_claim_in_any_member_facing_string():
    """NG-04 over the same strings. "In code, **copy**, or generated certificates" — this is the copy half.

    `ACCREDITATION_WORDS` had a reader on the learning seed file and on two source modules, and on nothing
    else in the product. NG-04 names copy, and a claim of federal accreditation is worth more to whoever
    writes it in a refusal or a notice than in a learning unit.

    **Planted:** `Eidgenössisch akkreditierter Fachausweis` into the German block of
    `client/content/roles.json` and into `boundary.py`'s German REFUSAL. Failed naming both origins and
    `akkreditiert`, `eidgenössisch`, `fachausweis`. Restored.
    """
    offenders = [
        (origin, _whole_words(ACCREDITATION_WORDS, text.lower()), text[:80])
        for origin, text in member_facing_strings()
        if _whole_words(ACCREDITATION_WORDS, text.lower())
    ]
    assert not offenders, (
        f"NG-04: eigentliCH states capabilities and awards nothing. A member-facing string claims a "
        f"qualification in {len(offenders)} places: {offenders[:12]}"
    )


def test_the_member_facing_string_scan_reaches_where_copy_is_actually_composed():
    """A guard on the scan, and the reason it is here is that the scan it replaces passed for eight months.

    Two empty offender lists are what a healthy product and an unplugged scanner both look like. So this
    asserts the collector reaches the specific places the audit's plants went, plus the content files that
    no reader covered, and that it is not returning a handful of strings from one module.
    """
    origins = {origin for origin, _ in member_facing_strings()}
    for required in (
        "eigentlich/boundary.py",
        "eigentlich/services/community.py",
        "eigentlich/services/know.py",
        "roles.json",
        "destination.json",
        "life-events.json",
        "onboarding-questions.json",
        "stages.json",
        "learning.json",
        "marketplace.json",
    ):
        assert any(required in origin for origin in origins), f"the scan never opens {required}"

    strings = member_facing_strings()
    assert len(strings) > 1000, f"only {len(strings)} strings collected; the collector has come unplugged"


def test_the_member_facing_scanners_can_still_fail():
    """Both filters, on the exact forms that walked past the old ones. A20's lesson, applied to a new scan."""
    assert mountain_hits("der gipfelweg über die bergetappe") == ["berg", "gipfel"]
    assert mountain_hits("summits and climbing above the basislager") == [
        "basislager",
        "climb",
        "summit",
    ]
    assert mountain_hits("aufstiegs-etappe mit bergführer") == ["aufstieg", "berg"]
    # And the two exact words still do not fire inside a longer word, which is why they are exact.
    assert mountain_hits("le modèle local ne tourne pas en ce moment") == []
    assert mountain_hits("schutz vor verlust") == []
    assert mountain_hits("ein tour de suisse") == ["tour"]
    # The audit's own planted phrase, and it is the reason the declined forms were appended: without
    # `akkreditierter` this returns two of the three words it should.
    assert _whole_words(ACCREDITATION_WORDS, "eidgenössisch akkreditierter fachausweis") == [
        "eidgenössisch",
        "fachausweis",
        "akkreditierter",
    ]
    assert _whole_words(ACCREDITATION_WORDS, "der vorsorgeausweis") == [], "not on Vorsorgeausweis"


def test_the_stem_rule_and_the_flat_list_agree():
    """The two halves of the mountain vocabulary cannot come to forbid different words.

    `mountain_hits()` matches stems into compounds; `test_client_bundle.py` matches `MOUNTAIN_WORDS`
    whole-word and belongs to another owner, so the compound forms are listed as literals as well. This is
    the A91 shape all over again — one fact, two representations — and the only thing that keeps it honest
    is an assertion that the weaker half is a subset of the stronger one.
    """
    for form in MOUNTAIN_FORMS_EN + MOUNTAIN_FORMS_DE:
        assert mountain_hits(form), f"{form} is in the flat list but no stem catches it"
    for word in MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE:
        assert mountain_hits(word), f"{word} is in the flat list but no stem or exact word catches it"


def test_no_gamification_identifier_anywhere_the_walk_is_pointed():
    """C-07's AST walk, in one place. See `c07_identifier_offences` for what the three copies had drifted to.

    **Planted:** `tally: Mapped[int] = mapped_column("points", Integer, nullable=True)` on `Position` in
    `eigentlich/models/plan.py`. Failed naming `plan.py:… 'points' ['points']`. Restored.
    """
    offences: list[str] = []
    for path in sorted((BACKEND_PACKAGE / "models").glob("*.py")):
        offences.extend(c07_identifier_offences(path))
    assert not offences, (
        "C-07 forbids gamification primitives in the member application's model layer. Found: "
        + "; ".join(offences)
    )


def test_the_identifier_walk_reads_a_name_as_words_and_a_string_as_a_name(tmp_path):
    """The guard on the walk, written from the four plants that passed set membership.

    A column named by string literal, and four compound names of which not one is an element of
    `GAMIFICATION_IDENTIFIERS`. It also has to stay off the names that deny the concept — the
    `not_indexed_by_profession` shape — so those are asserted in the same place.
    """
    source = tmp_path / "planted.py"
    source.write_text(
        "\n".join(
            [
                "TALLY = mapped_column('points', Integer)",
                "GRID = {'grid_completion_score': 1, 'points_earned': 2}",
                "STREAK = {'streak_days': 3, 'xp_total': 4}",
                "OK = {'not_indexed_by_profession': True, 'cell_filled': False}",
                "ALSO_OK = 'a product-level commitment, in Höhe von, underscore'",
            ]
        ),
        encoding="utf-8",
    )
    offences = c07_identifier_offences(source)
    caught = " ".join(offences)
    for expected in ("points", "grid_completion_score", "points_earned", "streak_days", "xp_total"):
        assert expected in caught, f"the walk missed {expected}"
    assert "not_indexed_by_profession" not in caught, "fired on a name asserting the concept is absent"
    assert "cell_filled" not in caught
    assert "product-level" not in caught, "bare `level` is not the constraint; `level-number` is"


def test_the_word_filter_actually_matches():
    """A guard on the guard, and it is here because the filter above was once silently vacuous.

    A stray escape turned the pattern into a literal backspace byte either side of the word, so it matched
    nothing and both vocabulary tests above passed by being unable to fail. Word filters are exactly the
    kind of test that looks green when broken, because the healthy result and the broken result are the
    same empty list. So: assert it catches what it should, and ignores what it should not.
    """
    assert _whole_words(("summit",), "the summit is near") == ["summit"]
    assert _whole_words(("hut",), "schutz vor verlust") == [], "must not fire inside a German compound"
    assert _whole_words(("tour",), "die absicherung") == [], "must not fire inside Absicherung"
    assert _whole_words(("score",), "underscore") == [], "must not fire inside underscore"
    assert _whole_words(("berg",), "ein berg") == ["berg"]
    assert _whole_words(("berg",), "heidelberger") == []
    assert _whole_words(("level_number",), "the level_number field") == ["level_number"]


def test_no_string_claims_review_without_existing():
    """A cleared draft flag on a missing string claims a review that never happened.

    Caught after a bulk flag-clear set `de_draft: false` on a `de: null` entry. The flag and the string
    have to agree, or the file lies about what has been read by a human.
    """
    data = json.loads((CONTENT / "roles.json").read_text(encoding="utf-8"))

    def walk(node, path="root"):
        if isinstance(node, dict):
            if "de_draft" in node and node.get("de_draft") is False:
                assert node.get("de"), f"{path}: de_draft is False but there is no German string"
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(data)


def test_the_eight_role_definitions_are_reviewed():
    """A42. All eight read and signed off on 30 August 2026, with three corrections applied."""
    data = json.loads((CONTENT / "roles.json").read_text(encoding="utf-8"))
    for record in data["roles"]:
        for capital_type in ("human", "financial"):
            block = record["definition"][capital_type]
            assert block["de_draft"] is False, f"{record['key']}/{capital_type} is still a draft"
            assert block["de"]


def test_the_three_german_corrections_stuck():
    """Pinned: each was a specific correction, and each is the kind a later pass would undo."""
    from eigentlich.content import role_definition

    assert role_definition("stabilisation", "financial", "de").endswith("nicht währenddessen.")
    assert "absolviert wird" in role_definition("growth", "human", "de")
    assert "die Schwankungen des Ganzen" in role_definition("stabilisation", "human", "de")


# ============================================================ S-01's goal question, reworded by the owner


def _goal_question() -> dict:
    from eigentlich.content import onboarding_questions

    return next(record for record in onboarding_questions() if record["key"] == "first_goal")


def test_the_goal_question_asks_what_the_member_works_toward():
    """The owner's own wording, 31 August 2026: "Auf welches finanzielle Ziel arbeiten Sie hin".

    **The reason is worth pinning, not just the sentence.** "Wofür ist das Geld da" asks what the money is
    FOR, which invites an expense — a kitchen, a car — and an expense stored in a `Goal` is not what a Goal
    models. Asking what the member is working TOWARD asks for the thing the model holds. A later editing
    pass could easily "improve" this back.

    **Planted violation:** put "Wofür ist das Geld da?" back. Failed on both assertions. Restored.
    """
    question = _goal_question()
    assert question["question"]["de"].startswith("Auf welches finanzielle Ziel arbeiten Sie hin")
    assert "Wofür ist das Geld da" not in question["question"]["de"]
    assert question["question"]["en"].startswith("What financial goal are you working toward")
    # And it no longer asks for a year and an amount it never stored — `fills` names one field, so
    # "Wohneigentum 2031" used to become the goal's NAME.
    for stray in ("Jahr und Betrag", "a year and an amount"):
        for language in ("de", "en"):
            assert stray not in question["question"][language]


def test_the_goal_question_still_says_why_it_is_asked():
    """A12 and S-01's most valuable inheritance: every question carries its `why`, in both languages.

    The line still does R-030's work — goals do not partition holdings, said in the question that creates
    the member's first one — and it gained the clause that the goal can be changed later, which was untrue
    when it was written and is true now.
    """
    question = _goal_question()
    for language in ("de", "en"):
        assert question["why"][language]
    assert "nicht aufgeteilt" in question["why"]["de"]
    assert "not divided up" in question["why"]["en"]


def test_the_goal_question_offers_the_templates():
    """The owner's second sentence: the system should fill the goal out when one is chosen.

    The type is what the client branches on and what `GET /api/onboarding` attaches the templates to, so a
    revert to `text` would silently take the choice away again.
    """
    question = _goal_question()
    assert question["type"] == "goal_template"
    assert question["fills"]["template_field"] == "template"
