"""Golden layer B: the corrected behaviour (calibrations 1.2.0 and 1.3.0; LBS-24, LBS-28), frozen by
``dev/build_golden_corrected.py``.

Layer A (``test_golden.py``) keeps the prototype as the reference for the reproduction mode (1.0.0, 1.1.0).
Step 1.2.0: every sheet under 1.2.0 matches its frozen form to 1e-9 relative, the figures that differ from the
reproduction are exactly the listed ones, each is moved by the correction its case is about, and none of the
fifteen prototype cases moves at all. Step 1.3.0: the same against 1.2.0 for the three corrections of LBS-28;
here prototype cases do move, each by one named correction, and which and why is asserted. Step 1.4.0: the
nominal and real view against 1.3.0 (LBS-31 to LBS-35), each changed leaf attributed to one of four parts.
Step 1.5.0: the owner's CHF inflation of 1.0 % and the approved plausibility table against 1.4.0 (LBS-36 to
LBS-38), each changed leaf attributed to one of the two decisions.
"""

from __future__ import annotations

import json

import pytest

from lbs.calibration import CORRECTED, CORRECTED_1_3, CORRECTED_1_4, CORRECTED_1_5

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


# ---------------------------------------------------------------------------
# Step 1.4.0 (LBS-31 to LBS-35): calibration 1.4.0 against 1.3.0, frozen in golden/corrected/1.4.0
# ---------------------------------------------------------------------------

CASES_14 = CASES_13 + L.layer_b14_names()
FROZEN_CHANGES_14 = json.loads((L.LAYER_B14 / "changes.json").read_text(encoding="utf-8"))


def test_step_14_covers_every_case():
    assert sorted(FROZEN_CHANGES_14) == sorted(CASES_14) and set(L.layer_b14_names()) == set(L.CASE_ABOUT_14)
    assert sorted(p.stem for p in (L.LAYER_B14 / "expected").glob("*.json")) == sorted(CASES_14)


@pytest.mark.parametrize("name", CASES_14)
def test_the_14_sheet_matches_its_frozen_form(name):
    ours = L.sheet_of(name, CORRECTED_1_4)
    frozen = json.loads((L.LAYER_B14 / "expected" / f"{name}.json").read_text(encoding="utf-8"))
    assert L.diff(ours, frozen) == []


@pytest.mark.parametrize("name", CASES_14)
def test_the_14_changes_against_13_are_the_listed_ones(name):
    ours = L.changes_14(name)
    frozen = FROZEN_CHANGES_14[name]
    assert [c["path"] for c in ours] == [c["path"] for c in frozen]
    for a, b in zip(ours, frozen):
        assert a["by"] == b["by"] and a["by"][0] in L.WHY_14, a["path"]
        assert L.same(a["before"], b["before"]) and L.same(a["after"], b["after"]), a["path"]


def test_what_moves_in_14_and_what_does_not():
    """Decision 7 moves figures on purpose: a mandate on a dated goal amount now has a nominal target in francs
    of its date. A goal stated in future francs keeps every 1.3.0 figure (only notes and the target's wording
    move); nothing is removed; no retirement verdict flips in these cases."""
    for name, changes in FROZEN_CHANGES_14.items():
        assert all(c["after"] != "<absent>" for c in changes), name
        assert not any(c["path"].startswith("retirement[") and c["path"].endswith(".verdict") for c in changes), name
    future = [c["path"] for c in FROZEN_CHANGES_14["v-future"] if c["by"] == ["amounts_in_todays_francs"]]
    assert future and all(p.startswith(("mandate_proposal.notes", "mandate_proposal.target_basis")) for p in future)
    moved = {c["path"] for c in FROZEN_CHANGES_14["v-worked-example"] if c["by"] == ["amounts_in_todays_francs"]}
    assert {"mandate_proposal.target_chf", "mandate_proposal.required_return"} <= moved
    assert FROZEN_CHANGES_14["v-retirement"] and any(
        c["path"] == "retirement[later].covered_per_year" for c in FROZEN_CHANGES_14["v-retirement"])
    assert {c["by"][0] for c in FROZEN_CHANGES_14["syn-liquidity"]} == {"real_view"}


# ---------------------------------------------------------------------------
# Step 1.5.0 (LBS-36 to LBS-38): calibration 1.5.0 against 1.4.0, frozen in golden/corrected/1.5.0
# ---------------------------------------------------------------------------

CASES_15 = L.layer_b15_names()
FROZEN_CHANGES_15 = json.loads((L.LAYER_B15 / "changes.json").read_text(encoding="utf-8"))
FROZEN_RETURNS_15 = json.loads((L.LAYER_B15 / "required_returns.json").read_text(encoding="utf-8"))


def test_step_15_covers_every_case():
    assert sorted(CASES_15) == sorted(CASES_14) and sorted(FROZEN_CHANGES_15) == sorted(CASES_15)
    assert sorted(p.stem for p in (L.LAYER_B15 / "expected").glob("*.json")) == sorted(CASES_15)


@pytest.mark.parametrize("name", CASES_15)
def test_the_15_sheet_matches_its_frozen_form(name):
    ours = L.sheet_of(name, CORRECTED_1_5)
    frozen = json.loads((L.LAYER_B15 / "expected" / f"{name}.json").read_text(encoding="utf-8"))
    assert L.diff(ours, frozen) == []


@pytest.mark.parametrize("name", CASES_15)
def test_the_15_changes_against_14_are_the_listed_ones(name):
    ours = L.changes_15(name)
    frozen = FROZEN_CHANGES_15[name]
    assert [c["path"] for c in ours] == [c["path"] for c in frozen]
    for a, b in zip(ours, frozen):
        assert a["by"] == b["by"] and a["by"][0] in L.WHY_15 and a["figure"] == b["figure"] in L.FIGURE_15
        assert L.same(a["before"], b["before"]) and L.same(a["after"], b["after"]), a["path"]


def test_the_15_required_returns_are_the_frozen_ones():
    for name in CASES_15:
        ours = L.required_returns_15(name)
        assert (ours is None) == (name not in FROZEN_RETURNS_15), name
        if ours is not None:
            for view in ("nominal", "real"):
                for key in ("1.4.0", "1.5.0", "move_points"):
                    assert L.same(ours[view][key], FROZEN_RETURNS_15[name][view][key]), (name, view, key)


def test_what_moves_in_15_and_what_does_not():
    """Only the real view moves: no leaf appears or disappears, no ceiling in real terms moves (the table is
    approved unchanged), the approval moves only the ceiling's source line, and every other change is the CHF
    inflation. A goal in future francs keeps its nominal required return; an indexed contribution keeps its real
    one; a goal in today's francs with a fixed contribution needs more, nominal and real. One retirement verdict
    flips: v-retirement's need of 60'000 in today's francs, met at 0.50 %, is not met at 1 % (the nominal BVG
    pension is worth less in today's francs)."""
    for name, changes in FROZEN_CHANGES_15.items():
        assert all("<absent>" not in (c["before"], c["after"]) for c in changes), name
        assert not any(c["path"].endswith("plausibility.ceiling_real") for c in changes), name
        for c in changes:
            if c["by"] == ["plausibility_table_approved"]:
                assert c["path"].endswith("plausibility.ceiling_source")
                assert c["after"].startswith("approved by the owner"), name
            else:
                assert c["figure"] != "other", (name, c["path"])
        assert any(c["path"] == "real_view.inflation.annual_rate" for c in changes), name
    flips = [(n, c["path"]) for n, cs in FROZEN_CHANGES_15.items() for c in cs if c["path"].endswith(".verdict")]
    assert flips == [("v-retirement", "retirement[later].verdict")]
    r = FROZEN_RETURNS_15
    assert r["v-future"]["nominal"]["move_points"] == 0 and r["v-not-realistic"]["nominal"]["move_points"] == 0
    assert abs(r["v-indexed"]["real"]["move_points"]) < 1e-6 and r["v-indexed"]["nominal"]["move_points"] > 0
    today_fixed = [n for n, v in r.items() if v["amount_basis"] == "today" and not v["contribution_indexed"]
                   and v["nominal"]["1.4.0"] > 0 and v["real"]["1.4.0"] > 0 and n != "q-ceiling"]
    assert today_fixed and all(r[n]["nominal"]["move_points"] > 0 and r[n]["real"]["move_points"] > 0
                               for n in today_fixed)
    assert all(v["judgement"]["1.4.0"] == v["judgement"]["1.5.0"] for v in r.values())
    worked = r["v-worked-example"]
    assert round(worked["nominal"]["1.5.0"] * 100, 2) == 1.60 and round(worked["real"]["1.5.0"] * 100, 2) == 0.59
