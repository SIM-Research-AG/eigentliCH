"""Golden layer B: lbsim's findings under 1.0.0 and 1.1.0 on the frozen lbs cases, every change attributed."""

from __future__ import annotations

import pytest

from conftest import GOLDEN, differences, load_json

from lbsim.calibration import ACTIVE_SEED, SEED, SEED_1_1, SEED_1_2, calibration_hash
from lbsim.layer_b import DECISIONS, changed, findings, flatten

CASES = GOLDEN / "lbs_cases"
NAMES = load_json(CASES / "manifest.json")["cases"]
RECORDS = load_json(CASES / "records.json")["records"]
CHANGES = load_json(GOLDEN / "layer_b" / "changes.json")


@pytest.mark.parametrize("name", NAMES)
def test_findings_reproduce_the_frozen_reference(name):
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    for cal in (SEED, SEED_1_1, SEED_1_2, ACTIVE_SEED):
        got = findings(CASES / name, RECORDS, cal)
        diff = differences(expected[cal.version], got)
        assert not diff, "\n".join(diff[:20])


@pytest.mark.parametrize("name", NAMES)
def test_every_changed_leaf_is_attributed_to_a_decision(name):
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    moved = changed(flatten(expected[SEED.version]), flatten(expected[SEED_1_1.version]))
    attributed = CHANGES["cases"][name]
    assert set(moved) == set(attributed), sorted(set(moved) ^ set(attributed))[:10]
    for leaf, who in attributed.items():
        assert who and set(who) <= set(DECISIONS), (leaf, who)


def test_changes_name_the_two_seeds():
    assert CHANGES["from"] == {"version": "1.0.0", "hash": calibration_hash(SEED)}
    assert CHANGES["to"] == {"version": "1.1.0", "hash": calibration_hash(SEED_1_1)}
    step = CHANGES["step_1_2_0"]
    assert step["from"]["version"] == "1.1.0" and step["to"] == {"version": "1.2.0",
                                                                 "hash": calibration_hash(SEED_1_2)}
    step13 = CHANGES["step_1_3_0"]
    assert step13["from"] == {"version": "1.2.0", "hash": calibration_hash(SEED_1_2)}
    assert step13["to"] == {"version": "1.3.0", "hash": calibration_hash(ACTIVE_SEED)}
    assert "UNATTRIBUTED" not in CHANGES["summary"]


def test_the_market_decision_moves_nothing_in_the_findings():
    """LBSIM-07 belongs to the paths; the fast half is untouched by it."""
    assert not any("LBSIM-07" in who for per in CHANGES["cases"].values() for who in per.values())


@pytest.mark.parametrize("name", NAMES)
def test_every_leaf_1_2_0_changes_is_the_income_path_correction(name):
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    moved = changed(flatten(expected[SEED_1_1.version]), flatten(expected[SEED_1_2.version]))
    attributed = CHANGES["step_1_2_0"]["cases"][name]
    assert set(moved) == set(attributed)
    assert all(who == ["P-9"] for who in attributed.values())
    # Only the income paths, and what rests on them (the frontier, the questions' spreads), move.
    assert all(leaf.startswith(("income_paths", "frontier", "next_questions", "findings", "unchecked",
                                "gate", "schedule")) for leaf in moved), [m for m in moved if not m.startswith(
                                    ("income_paths", "frontier", "next_questions"))][:5]


@pytest.mark.parametrize("name", NAMES)
def test_1_3_0_moves_no_leaf_of_the_findings(name):
    """1.3.0 changes the optimiser block only (DECISIONS O-18); the findings do not read it."""
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    assert not changed(flatten(expected[SEED_1_2.version]), flatten(expected[ACTIVE_SEED.version]))
    assert CHANGES["step_1_3_0"]["cases"][name] == {}
