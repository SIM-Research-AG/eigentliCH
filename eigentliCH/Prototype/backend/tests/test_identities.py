"""The reimplemented identities, held against the ORIGINAL's own output.

Item 3 says these functions "must not be rewritten in the move". They are JavaScript in a single-file
prototype and this build is Python, so there is no move that preserves them as they are; the owner ruled on
3 September 2026 to reimplement, with the original as the standard.

**So the standard is differential.** `tools/extract_identities.mjs` runs the original JavaScript over a
corpus and writes `fixtures/identities-reference.json`. Every test here asserts the Python reproduces that
file exactly. "Did the port change the behaviour" is answered by the original rather than by whoever wrote
the port — which is the only reading of "must not be rewritten" that a test can hold.

The fixture is committed and this suite needs no Node. `conftest.py` makes the same point about the book
corpus: a suite that is green only where one developer's tooling happens to sit proves nothing about the
code a friend runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eigentlich.services.identities import (
    child_ages,
    confidence_table,
    learning_commitment_scale,
    goals_from,
    married,
    net_scale,
    parse_goal_text,
    partnered,
)

REFERENCE = Path(__file__).parent / "fixtures" / "identities-reference.json"


@pytest.fixture(scope="module")
def reference() -> dict:
    assert REFERENCE.exists(), (
        f"{REFERENCE} is missing. It is generated from andersCH-prototype/onboarding-chat.html by "
        f"tools/extract_identities.mjs and is committed; without it these tests assert nothing."
    )
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def _cases(reference: dict, name: str) -> list[dict]:
    cases = reference[name]
    assert cases, f"the reference carries no {name} cases, so this test would pass vacuously"
    return cases


# ============================================================ the lookup tables


def test_the_tables_match_the_original(reference):
    tables = reference["tables"]
    assert confidence_table() == tables["CONF"]
    assert list(partnered()) == tables["PARTNERED"]
    assert list(married()) == tables["MARRIED"]
    # The difference between the two is legal rather than cosmetic, so it is asserted rather than assumed.
    assert set(married()) < set(partnered())


# ============================================================ the identities, case for case


def test_parse_goal_text_matches_the_original(reference):
    for case in _cases(reference, "parseGoalText"):
        assert parse_goal_text(case["in"]) == case["out"], case["in"]


def test_the_year_is_removed_before_the_amount_is_looked_for(reference):
    """The original's own recorded bug: "2030: 750'000 für die Firma" returned 2030 as the AMOUNT.

    Pinned separately from the sweep above because it is the one case where a reimplementation that
    reordered two lines would still look right.
    """
    parsed = parse_goal_text("2030: 750'000 für die Firma")
    assert parsed == {"target_year": 2030, "amount_chf": 750000}


def test_goals_from_matches_the_original(reference):
    for case in _cases(reference, "goalsFrom"):
        got = goals_from(case["in"]["data"], case["in"]["year"])
        assert got == case["out"], case["in"]


def test_net_scale_matches_the_original(reference):
    for case in _cases(reference, "netScale"):
        got = net_scale(case["in"]["people"], case["in"]["mandates"])
        assert got == case["out"], case["in"]


def test_learning_commitment_scale_matches_the_original(reference):
    for case in _cases(reference, "expertiseScale"):
        assert learning_commitment_scale(case["in"]) == case["out"], case["in"]


def test_child_ages_matches_the_original(reference):
    for case in _cases(reference, "childAges"):
        got = child_ages(case["in"]["text"], case["in"]["year"])
        assert got == case["out"], case["in"]


# ============================================================ the JavaScript semantics, named


def test_javascript_rounding_is_half_toward_positive_infinity():
    """`Math.round` is `floor(x + 0.5)`, which is none of the three roundings a reader expects.

    Not Python's `round` (half to even), and **not** half-away-from-zero either — which is what the first
    version of both the function and this test said. Verified against `node`: `Math.round(-0.5)` is `-0`,
    `Math.round(-1.5)` is `-1`. Every one takes the higher neighbour.
    """
    from eigentlich.services.identities import _js_round, _round2

    assert _js_round(0.5) == 1 and round(0.5) == 0
    assert _js_round(2.5) == 3 and round(2.5) == 2
    assert _js_round(1.5) == 2
    # The three that separate "toward +Infinity" from "away from zero".
    assert _js_round(-0.5) == 0
    assert _js_round(-1.5) == -1
    assert _js_round(-2.5) == -2
    assert _round2(0.125) == 0.13


def test_an_empty_multi_select_is_unanswered_the_way_javascript_reads_it():
    """`String([])` is `""` in JavaScript and `"[]"` in Python, and `learning_commitment_scale`
    turns on its length.

    Caught by the differential fixture rather than by reading the code, which is the whole argument for
    generating the reference from the original.
    """
    from eigentlich.services.identities import _js_string

    assert _js_string([]) == ""
    assert _js_string(["MAS"]) == "MAS"
    assert _js_string(["a", "b"]) == "a,b"
    assert learning_commitment_scale({"education_planned": []}) is None


def test_number_or_zero_is_a_coercion_and_not_a_null_check():
    """`Number(x) || 0` returns 0 for null, "", NaN and for 0 itself — and for text that is not a number."""
    from eigentlich.services.identities import _number_or_zero

    assert _number_or_zero(None) == 0
    assert _number_or_zero("") == 0
    assert _number_or_zero("abc") == 0
    assert _number_or_zero(0) == 0
    assert _number_or_zero("69550") == 69550
    assert _number_or_zero(" 42 ") == 42
    # `Number(true)` is 1 in JavaScript but `|| 0` keeps it 1; the original never passes a boolean here and
    # this returns 0 for one, which is the safer disagreement to have. Stated so it is a known difference.
    assert _number_or_zero(True) == 0


def test_a_confidence_that_is_not_in_the_table_is_none_rather_than_a_guess():
    goals = goals_from(
        {"birth_year": 1993, "spend_now": 60000, "goal_confidence": "so ungefähr"}, 2026
    )
    assert goals[0]["confidence"] is None


# ============================================================ the corpus itself


def test_the_reference_covers_every_function_and_is_not_a_stub(reference):
    """A fixture with one happy case per function would let a port that mishandles null pass."""
    for name, minimum in (
        ("parseGoalText", 10),
        ("goalsFrom", 6),
        ("netScale", 10),
        ("expertiseScale", 10),
        ("childAges", 5),
    ):
        assert len(reference[name]) >= minimum, f"{name} has too few reference cases to hold a port"

    # Null and empty are in the corpus for every function that can receive them, because that is where a
    # reimplementation drifts first.
    assert any(case["in"] is None for case in reference["parseGoalText"])
    assert any(case["in"]["data"] == {} for case in reference["goalsFrom"])
    assert any(
        case["in"]["people"] is None and case["in"]["mandates"] is None
        for case in reference["netScale"]
    )
    assert any(case["in"] == {} for case in reference["expertiseScale"])
    assert any(case["in"]["text"] is None for case in reference["childAges"])


def test_the_reference_names_the_file_it_came_from(reference):
    """A fixture nobody can trace back is a fixture nobody can regenerate."""
    assert reference["source"].endswith("onboarding-chat.html")
    assert "extract_identities.mjs" in reference["_about"]
