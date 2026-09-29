"""The frontier: the smallest change that makes a goal hold, searched rather than illustrated.

**What it replaced.** `app/paths` builds four named paths from a hand-written list: three dimensions baked
into a signature, levels fixed at "today or full", four of the eight combinations chosen by hand, and neither
spending nor the stop age nor the goal itself varied at all. It illustrates. Asked "what would make this
work", it could only answer with one of its four pictures.

Two defects found while building it are pinned below, because both produced confident wrong answers:

  the cap truncated a systematic slice, and the search then reported "no way found" for a goal that a smaller
  amount at a later date plainly funds;

  the amount moves were silent no-ops, because the search varied the ROWS the simulation returns and a row
  carries no `amount_chf`.

Every test runs on an invented household (M74).
"""

from __future__ import annotations

import pytest

from personal_alm.app import search as S
from personal_alm.model.params import Params


def household(**over) -> dict:
    base = {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22", "source": "test"},
        "state": {"age": 24, "W_L": 2_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 0.0, "W_3a": 0.0, "H": 1.0, "N": 0.7, "E": 0.9},
        "params": {"G": 80_000.0, "ahv_record_share": 1.0, "epsilon": 0.30, "stop_work_age": 60},
        "goals": [
            {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2067,
             "amount_chf": 80_000.0, "confidence": 0.7, "is_consumption": False},
            {"kind": "home", "description": "Wohneigentum", "target_year": 2037,
             "amount_chf": 2_000_000.0, "confidence": 0.7, "is_consumption": False},
        ],
        "raw": {"birth_year": 2002, "canton": "Thurgau", "income_gross": 24_000.0,
                "spend_now": 24_000.0, "spend_later": 80_000.0, "hours_per_week": 16.8,
                "education_hours": "mehr als 10", "education_budget": 5_000.0,
                "education_recent": "Berufsmaturität 2026", "pillar3a_contribution": 0.0,
                "stop_work_age": 60},
    }
    for key, value in over.items():
        if key in ("state", "params", "raw", "meta") and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def run(sub: dict, rate: float = 0.0) -> dict:
    p = Params(**{k: v for k, v in (sub.get("params") or {}).items()
                  if k in Params.__dataclass_fields__})
    return S.frontier(sub, p, rate=rate)


def goal(fr: dict, kind: str) -> dict:
    return next(g for g in fr["goals"] if g["kind"] == kind)


# --- the two frontiers -----------------------------------------------------------------------------------

def test_effort_and_goal_changes_are_reported_separately():
    """**The refusal is the design.** Ranking "work more" against "want less" is a judgement G7 reserves for
    a person, so both are offered and neither is chosen."""
    fr = run(household(), rate=0.08)
    g = goal(fr, "home")
    assert not g["holds_today"]
    assert "cheapest_effort" in g and "cheapest_goal_change" in g and "cheapest_combination" in g
    # No field ranks one against the other.
    assert "recommended" not in g and "best" not in g


def test_an_unreachable_goal_is_solved_by_moving_its_date_and_amount():
    """**The defect that made this test necessary.** The search varied the rows `simulate` returns, which
    carry no `amount_chf`, so every "smaller amount" move changed nothing and the goal then vanished from the
    arithmetic for having no amount. A two-million target that a quarter of the amount ten years later funds
    was reported as reachable by no path at all -- after searching 2 303 combinations.
    """
    g = goal(run(household(), rate=0.08), "home")
    change = g["cheapest_goal_change"]
    assert change is not None, "a smaller, later version of this goal is fundable"
    assert any("Betrag" in mv for mv in change["moves"])
    assert change["available"] >= change["required"]


def test_a_goal_that_already_holds_is_not_searched():
    """Nothing to find, and a frontier printed for it would read as a demand."""
    sub = household(goals=[{"kind": "home", "description": "Kleines Ziel", "target_year": 2037,
                            "amount_chf": 20_000.0, "confidence": 0.7, "is_consumption": False}],
                    raw={"hours_per_week": 42.0, "income_gross": 90_000.0, "spend_now": 40_000.0})
    g = goal(run(sub), "home")
    assert g["holds_today"] and g["combinations_tried"] == 0


def test_cheapest_means_fewest_moves_before_smallest_moves():
    """A frontier ordered by francs alone would offer a decade of extra work over a two-year delay."""
    g = goal(run(household(), rate=0.08), "retirement")
    for key in ("cheapest_effort", "cheapest_goal_change"):
        c = g[key]
        if c:
            assert len(c["moves"]) == c["cost"][0]
            assert c["cost"][0] <= 2, c["moves"]


def test_the_figures_come_from_the_rate_being_tested():
    """**A frontier run at 8 % printed the zero-return requirement beside its verdict.** The verdict was
    right and the number next to it came from a different column."""
    zero = goal(run(household(), rate=0.0), "retirement")
    eight = goal(run(household(), rate=0.08), "retirement")
    a, b = zero["cheapest_effort"], eight["cheapest_effort"]
    assert a and b
    assert b["required"] < a["required"], "a return can only lower what must be saved"


# --- completeness ----------------------------------------------------------------------------------------

def test_the_search_is_complete_or_refuses_rather_than_truncating():
    """**Truncation produced a confident wrong answer and has been removed.**

    Seven dimensions make 2 304 combinations against a cap of 2 000, and `product` varies the last dimension
    fastest -- so the 304 dropped were every combination with the largest goal reductions at the longest
    delays, which is exactly where the answer for an out-of-reach goal lives.
    """
    fr = run(household(), rate=0.08)
    assert not fr["truncated"]
    for g in fr["goals"]:
        assert "refused" not in g
        # The whole space is reachable; only part of it needs evaluating.
        assert g["combinations_tried"] <= g["combinations_possible"]


def test_a_space_too_large_to_finish_is_refused_and_named(monkeypatch):
    """A partial search that answers anyway is the failure this replaced, so the bound refuses instead."""
    monkeypatch.setattr(S, "MAX_COMBINATIONS", 10)
    fr = run(household())
    assert fr["truncated"]
    assert all(g.get("refused") for g in fr["goals"])
    assert all(g["cheapest_effort"] is None for g in fr["goals"])


def test_the_scan_stops_at_the_first_hit_of_each_kind():
    """Under a cost ordering the first hit IS the cheapest, which is what makes a complete search cheap."""
    g = goal(run(household(), rate=0.08), "retirement")
    assert g["combinations_tried"] < g["combinations_possible"] / 10


# --- what the moves do -----------------------------------------------------------------------------------

def test_the_household_is_not_mutated_by_the_search():
    """A search that edits in place leaves the report describing whichever combination was tried last."""
    sub = household()
    before = sub["raw"]["spend_now"], [dict(g) for g in sub["goals"]]
    run(sub, rate=0.08)
    assert sub["raw"]["spend_now"] == before[0]
    assert sub["goals"] == before[1]


def test_only_the_goal_being_varied_is_replaced():
    """A household may state two goals of one kind; replacing the wrong one moves a target nobody asked about."""
    twin = household(goals=[
        {"kind": "home", "description": "Erstes Objekt", "target_year": 2037,
         "amount_chf": 2_000_000.0, "confidence": 0.7, "is_consumption": False},
        {"kind": "home", "description": "Zweites Objekt", "target_year": 2045,
         "amount_chf": 300_000.0, "confidence": 0.7, "is_consumption": False},
    ])
    fr = run(twin, rate=0.08)
    described = {g["description"] for g in fr["goals"]}
    assert described == {"Erstes Objekt", "Zweites Objekt"}
    assert {g["target_year"] for g in fr["goals"]} == {2037, 2045}


def test_spending_and_stop_age_are_searched_even_though_no_preset_varies_them():
    """The two dimensions `app/paths` never touches, and one of them is the lever the report already prices."""
    dims = run(household())["dimensions"]
    assert any("Ausgaben" in lab for lab in dims["spending"])
    assert any("Erwerbsende" in lab for lab in dims["stop_age"])
    assert len(dims["pensum"]) > 2, "more than today-or-full"


def test_a_goal_whose_kind_is_unresolved_is_still_priced_and_flagged():
    """**Two sections disagreed about one goal, and both were right about their own question.**

    `required_return` defers a goal whose kind is unresolved, because a Ferienobjekt, Wohneigentum and a Firma
    do different things to a balance sheet AFTER the purchase. What must be saved BY a date, though, follows
    from the amount and the date alone. So the frontier prices it and the flag records what is still open --
    rather than the report pricing it in one place and calling it uncomputed in another.
    """
    sub = household(goals=[{"kind": "other", "description": "Unklar", "target_year": 2037,
                            "amount_chf": 500_000.0, "confidence": 0.7, "is_consumption": None}])
    fr = run(sub, rate=0.08)
    assert len(fr["goals"]) == 1 and fr["goals"][0]["description"] == "Unklar"

    from personal_alm.app import paths as P
    p = Params(**{k: v for k, v in sub["params"].items() if k in Params.__dataclass_fields__})
    row = P.simulate(sub, p, P.income_paths(sub, p)[0], stop_age=60.0, rates=(0.0,))["goals"][0]
    assert row["kind_unresolved"] is True

    resolved = household(goals=[{"kind": "home", "description": "Klar", "target_year": 2037,
                                 "amount_chf": 500_000.0, "confidence": 0.7, "is_consumption": False}])
    row2 = P.simulate(resolved, p, P.income_paths(resolved, p)[0], stop_age=60.0,
                      rates=(0.0,))["goals"][0]
    assert row2["kind_unresolved"] is False
