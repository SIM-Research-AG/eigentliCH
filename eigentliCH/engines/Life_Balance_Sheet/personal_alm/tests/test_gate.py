"""The gate: what is still open, and which of the three stages a household is therefore in.

**The report used to arrive whole, with its unresolved parts marked inside it.** That reads as a finished
document with caveats, and a caveat inside a finished document is something a reader skips. On the household
this was built for, three answers contradicted each other and the largest goal had no resolved kind -- all of
it inside thirty-eight kilobytes of figures computed from those same answers.

The rule for blocking is one sentence: an item blocks when answering it changes a number already in the
report. That is why a contradiction blocks and a ranked ask does not -- the ask would make the report better,
the contradiction makes it a report about a household that may not exist.

Invented households only (M74).
"""

from __future__ import annotations

from personal_alm.app import gameplan as G
from personal_alm.app import workflow as W
from personal_alm.model.params import Params


def household(**over) -> dict:
    """Deliberately clean: nothing contradicts, so a test can show one thing blocking."""
    base = {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22", "source": "test"},
        "state": {"age": 40, "W_L": 120_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 250_000.0, "W_3a": 40_000.0, "H": 0.9, "N": 0.5, "E": 0.6},
        "params": {"G": 70_000.0, "ahv_record_share": 1.0, "epsilon": 0.10},
        "goals": [{"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2051,
                   "amount_chf": 70_000.0, "confidence": 0.9, "is_consumption": False}],
        "pending_fields": [],
        "raw": {"birth_year": 1986, "canton": "Zug", "income_gross": 120_000.0,
                "spend_now": 70_000.0, "spend_later": 70_000.0, "savings": 20_000.0,
                "hours_per_week": 42.0, "hours_is_fulltime": "Vollpensum",
                "work_years_current": 20, "pillar2": 250_000.0, "pillar3a": 40_000.0,
                "pillar3a_contribution": 7_258.0, "civil_status": "ledig",
                "legal_docs": ["Testament"], "other_kinds": []},
    }
    for key, value in over.items():
        if key in ("state", "params", "raw", "meta") and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def gate(sub: dict) -> dict:
    return G.assemble(sub)["gate"]


def codes(items: list[dict]) -> set[str]:
    return {i["code"] for i in items}


# --- the stages ------------------------------------------------------------------------------------------

def test_a_household_with_nothing_open_goes_straight_to_the_report():
    g = gate(household())
    assert g["stage"] == "report" and g["open_count"] == 0


def test_a_contradiction_holds_the_report_back():
    """Two answers that cannot both be true. The report used to pick one silently."""
    g = gate(household(raw={"savings": 500_000.0}))
    assert g["stage"] == "open"
    assert "saving_exceeds_income" in codes(g["blocking"])


def test_an_unresolved_goal_kind_holds_the_report_back_and_is_still_priced():
    """**Both halves matter.** What must be saved by a date follows from the amount and the date, so the goal
    is priced; what the purchase does to the balance sheet afterwards follows from the kind, so it blocks.
    """
    sub = household(goals=[
        {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2051,
         "amount_chf": 70_000.0, "confidence": 0.9, "is_consumption": False},
        {"kind": "other", "description": "Objekt 2035", "target_year": 2035,
         "amount_chf": 300_000.0, "confidence": 0.9, "is_consumption": None},
    ])
    q = G.assemble(sub)
    assert q["gate"]["stage"] == "open"
    assert any(b["kind"] == "unresolved_goal" for b in q["gate"]["blocking"])
    # Priced in the paths despite blocking the report.
    priced = [g for run in q["paths"]["paths"] for g in run["goals"] if g["target_year"] == 2035]
    assert priced and priced[0]["target"] == 300_000.0


def test_a_ranked_ask_never_blocks():
    """There is no end to them, and a gate that waited for them would never open."""
    g = gate(household())
    assert all(i["kind"] != "ask" for i in g["blocking"])


def test_a_field_the_household_declined_does_not_block():
    """**A gate that keeps demanding an answer somebody has already refused is a gate nobody can pass.**

    A reduced Pensum with no stated full-time income blocks, because every income path then rests on a level
    the model chose rather than one the household gave. Declining is a real answer: the field lands in
    `pending_fields` and the item moves to the optional list.
    """
    part_time = household(raw={"hours_per_week": 20.0, "hours_is_fulltime": "ein reduziertes Pensum"})
    blocked = gate(part_time)
    assert "reduced_pensum_without_an_anchor" in codes(blocked["blocking"])

    declined = household(raw={"hours_per_week": 20.0, "hours_is_fulltime": "ein reduziertes Pensum"},
                         pending_fields=["income_expected_full"])
    after = gate(declined)
    assert "reduced_pensum_without_an_anchor" not in codes(after["blocking"])
    assert "reduced_pensum_without_an_anchor" in codes(after["optional"])


def test_answering_the_open_item_opens_the_gate():
    """The loop the whole stage exists for: answer, and the report appears."""
    contradicted = household(raw={"savings": 500_000.0})
    assert gate(contradicted)["stage"] == "open"
    resolved = household(raw={"savings": 20_000.0})
    assert gate(resolved)["stage"] == "report"


# --- what the gate reports about itself --------------------------------------------------------------------

def test_every_open_item_carries_a_question_and_the_fields_that_answer_it():
    """An item a reader cannot act on is a complaint rather than a step."""
    g = gate(household(raw={"savings": 500_000.0}))
    for item in g["blocking"]:
        assert item["title"] and item["why"]
        assert item["question"] or item["fields"], item["code"]


def test_the_pending_fields_are_listed_without_blocking():
    g = gate(household(pending_fields=["legal_docs"]))
    assert g["stage"] == "report"
    assert any(i["kind"] == "pending" for i in g["optional"])


def test_the_gate_survives_a_report_with_no_paths_or_plausibility():
    """It reads what other layers produced, so it must not require them."""
    out = W.open_items({}, household())
    assert out["stage"] in ("open", "report") and isinstance(out["blocking"], list)
