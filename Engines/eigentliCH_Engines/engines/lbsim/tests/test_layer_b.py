"""Golden layer B: lbsim's findings under 1.0.0 and 1.1.0 on the frozen lbs cases, every change attributed."""

from __future__ import annotations

import pytest

from conftest import GOLDEN, differences, load_json

from lbsim.calibration import ACTIVE_SEED, SEED, calibration_hash
from lbsim.layer_b import DECISIONS, changed, findings, flatten

CASES = GOLDEN / "lbs_cases"
NAMES = load_json(CASES / "manifest.json")["cases"]
RECORDS = load_json(CASES / "records.json")["records"]
CHANGES = load_json(GOLDEN / "layer_b" / "changes.json")


@pytest.mark.parametrize("name", NAMES)
def test_findings_reproduce_the_frozen_reference(name):
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    for cal in (SEED, ACTIVE_SEED):
        got = findings(CASES / name, RECORDS, cal)
        diff = differences(expected[cal.version], got)
        assert not diff, "\n".join(diff[:20])


@pytest.mark.parametrize("name", NAMES)
def test_every_changed_leaf_is_attributed_to_a_decision(name):
    expected = load_json(GOLDEN / "layer_b" / "expected" / f"{name}.json")
    moved = changed(flatten(expected[SEED.version]), flatten(expected[ACTIVE_SEED.version]))
    attributed = CHANGES["cases"][name]
    assert set(moved) == set(attributed), sorted(set(moved) ^ set(attributed))[:10]
    for leaf, who in attributed.items():
        assert who and set(who) <= set(DECISIONS), (leaf, who)


def test_changes_name_the_two_seeds():
    assert CHANGES["from"] == {"version": "1.0.0", "hash": calibration_hash(SEED)}
    assert CHANGES["to"] == {"version": "1.1.0", "hash": calibration_hash(ACTIVE_SEED)}
    assert "UNATTRIBUTED" not in CHANGES["summary"]


def test_the_market_decision_moves_nothing_in_the_findings():
    """LBSIM-07 belongs to the paths; the fast half is untouched by it."""
    assert not any("LBSIM-07" in who for per in CHANGES["cases"].values() for who in per.values())
