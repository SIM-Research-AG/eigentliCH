"""Golden layer B: the corrected behaviour (calibrations 1.2.0 and 1.3.0; LBS-24, LBS-28), frozen by
``dev/build_golden_corrected.py``.

Layer A (``test_golden.py``) keeps the prototype as the reference for the reproduction mode (1.0.0, 1.1.0).
Step 1.2.0: every sheet under 1.2.0 matches its frozen form to 1e-9 relative, the figures that differ from the
reproduction are exactly the listed ones, each is moved by the correction its case is about, and none of the
fifteen prototype cases moves at all. Step 1.3.0: the same against 1.2.0 for the three corrections of LBS-28;
here prototype cases do move, each by one named correction, and which and why is asserted.
"""

from __future__ import annotations

import json

import pytest

from lbs.calibration import CORRECTED, CORRECTED_1_3

from . import layer_b as L

CASES = L.layer_a_names() + L.layer_b_names()
FROZEN_CHANGES = json.loads((L.LAYER_B / "changes.json").read_text(encoding="utf-8"))

#: Which correction each quirk case is about.
CASE_QUIRK = {"q-ceiling": "required_return_search_reaches_its_ceiling",
              "q-horizon": "capacity_horizon_is_years_to_the_planned_age",
              "q-zero-income": "zero_income_is_a_stated_zero",
              "q-no-vessel": "unstated_vessel_is_a_gap"}


def test_layer_b_covers_every_case():
    assert sorted(FROZEN_CHANGES) == sorted(CASES) and set(L.layer_b_names()) == set(CASE_QUIRK)
    assert sorted(p.stem for p in (L.LAYER_B / "expected").glob("*.json")) == sorted(CASES)


@pytest.mark.parametrize("name", CASES)
def test_the_corrected_sheet_matches_its_frozen_form(name):
    ours = L.sheet_of(name, CORRECTED)
    frozen = json.loads((L.LAYER_B / "expected" / f"{name}.json").read_text(encoding="utf-8"))
    assert L.diff(ours, frozen) == []


@pytest.mark.parametrize("name", CASES)
def test_the_changes_against_the_reproduction_are_the_listed_ones(name):
    ours = L.changes(name)
    frozen = FROZEN_CHANGES[name]
    assert [c["path"] for c in ours] == [c["path"] for c in frozen]
    for a, b in zip(ours, frozen):
        assert a["by"] == b["by"], a["path"]
        assert L.same(a["reproduction"], b["reproduction"]) and L.same(a["corrected"], b["corrected"]), a["path"]


@pytest.mark.parametrize("name", L.layer_a_names())
def test_no_prototype_case_moves(name):
    """The corrections reach only what the prototype's golden cases never exercise."""
    assert FROZEN_CHANGES[name] == []


@pytest.mark.parametrize("name", sorted(CASE_QUIRK))
def test_each_quirk_case_is_moved_by_its_own_correction_only(name):
    changes = FROZEN_CHANGES[name]
    assert changes, name
    assert {tuple(c["by"]) for c in changes} == {(CASE_QUIRK[name],)}


# ---------------------------------------------------------------------------
# Step 1.3.0 (LBS-28): calibration 1.3.0 against 1.2.0, frozen in golden/corrected/1.3.0
# ---------------------------------------------------------------------------

CASES_13 = L.layer_a_names() + L.layer_b_names() + L.layer_b13_names()
FROZEN_CHANGES_13 = json.loads((L.LAYER_B13 / "changes.json").read_text(encoding="utf-8"))

#: Which correction each case of the step is about.
CASE_CORRECTION_13 = {"r-human-capital": "human_capital_is_never_free_wealth",
                      "r-paid-mortgage": "zero_mortgage_is_a_stated_zero",
                      "r-share-stated": "contribution_is_split_by_goal_share",
                      "r-share-missing": "contribution_is_split_by_goal_share"}


def test_step_13_covers_every_case():
    assert sorted(FROZEN_CHANGES_13) == sorted(CASES_13) and set(L.layer_b13_names()) == set(CASE_CORRECTION_13)
    assert sorted(p.stem for p in (L.LAYER_B13 / "expected").glob("*.json")) == sorted(CASES_13)


@pytest.mark.parametrize("name", CASES_13)
def test_the_13_sheet_matches_its_frozen_form(name):
    ours = L.sheet_of(name, CORRECTED_1_3)
    frozen = json.loads((L.LAYER_B13 / "expected" / f"{name}.json").read_text(encoding="utf-8"))
    assert L.diff(ours, frozen) == []


@pytest.mark.parametrize("name", CASES_13)
def test_the_13_changes_against_12_are_the_listed_ones(name):
    ours = L.changes(name, "1.3.0")
    frozen = FROZEN_CHANGES_13[name]
    assert [c["path"] for c in ours] == [c["path"] for c in frozen]
    for a, b in zip(ours, frozen):
        assert a["by"] == b["by"] and len(a["by"]) == 1, a["path"]
        assert L.same(a["before"], b["before"]) and L.same(a["after"], b["after"]), a["path"]


@pytest.mark.parametrize("name", sorted(CASE_CORRECTION_13))
def test_each_13_case_is_moved_by_its_own_correction_only(name):
    changes = FROZEN_CHANGES_13[name]
    assert changes, name
    assert {tuple(c["by"]) for c in changes} == {(CASE_CORRECTION_13[name],)}


def test_which_prototype_cases_move_in_13_and_why():
    """A stated mortgage of 0 in db-01 and db-05, the human-capital stock of syn-couple, and the missing share of
    every multi-goal household with a stated saving (a gap and a note only: the most the goal can receive is
    all of it, so no figure moves). Nothing else."""
    moved = {n: {c["by"][0] for c in FROZEN_CHANGES_13[n]} for n in CASES_13 if FROZEN_CHANGES_13[n]}
    split = "contribution_is_split_by_goal_share"
    assert moved.pop("db-01") == moved.pop("db-05") == {"zero_mortgage_is_a_stated_zero", split}
    assert moved.pop("syn-couple") == {"human_capital_is_never_free_wealth"}
    for name in ("db-02", "db-03", "db-04", "db-06", "db-07", "q-zero-income"):
        assert moved.pop(name) == {split}
        paths = [c["path"] for c in FROZEN_CHANGES_13[name]]
        assert all(p.startswith(("gaps[mandate_proposal|contribution_share", "mandate_proposal.notes")) for p in paths)
    assert set(moved) == set(CASE_CORRECTION_13)
