"""The return-zero path simulation: what each way forward demands per year.

**The defect this answers.** A twenty-four-year-old earning 24 000 at a reduced Pensum *because he is in
education* was planned as though that salary were permanent for forty-one years, which produced a required
return of 17,50 % a year. That number is not a finding about markets; it is what happens when the arithmetic is
fed a salary nobody expects him to keep.

Every test here runs on an invented household. The real submissions stay out of version control (M74), and a
test asserting a figure from one would put it there.
"""

from __future__ import annotations

import pytest

from personal_alm.app import paths as P
from personal_alm.model.params import Params


def household(**over) -> dict:
    """A young household in education on a reduced Pensum: the case the module exists for."""
    base = {
        "schema_version": "onb@0.1.3",
        "meta": {"collected": "2026-08-22", "source": "test"},
        "state": {"age": 24, "W_L": 2_000.0, "W_R": 0.0, "W_res": 0.0, "W_hol": 0.0,
                  "D": 0.0, "W_P": 0.0, "W_3a": 0.0, "H": 1.0, "N": 0.7, "E": 0.9},
        "params": {"G": 80_000.0, "ahv_record_share": 1.0, "epsilon": 0.30},
        "goals": [
            {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2067,
             "amount_chf": 80_000.0, "confidence": 0.7, "is_consumption": False},
            {"kind": "home", "description": "Wohneigentum", "target_year": 2037,
             "amount_chf": 400_000.0, "confidence": 0.7, "is_consumption": False},
        ],
        "raw": {"birth_year": 2002, "canton": "Thurgau", "income_gross": 24_000.0,
                "spend_now": 24_000.0, "spend_later": 80_000.0, "hours_per_week": 16.8,
                "education_hours": "mehr als 10", "education_budget": 5_000.0,
                "education_recent": "Berufsmaturität 2026", "pillar3a_contribution": 0.0},
    }
    for key, value in over.items():
        if key in ("state", "params", "raw", "meta") and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def run(sub: dict, stop_age: float = 60.0) -> dict:
    return P.ledger(sub, Params(**{k: v for k, v in (sub.get("params") or {}).items()
                                   if k in Params.__dataclass_fields__}), stop_age=stop_age)


# --- the paths themselves --------------------------------------------------------------------------------

def test_a_banded_education_answer_is_read_rather_than_dropped():
    """**"mehr als 10" was read as zero and both education paths silently vanished.**

    The band map lived inline in `levers`; this module parsed the raw string and got nothing, so the table
    showed two paths instead of four and looked as though the alternatives had been explored.
    """
    codes = [p["code"] for p in P.income_paths(household(), Params())]
    assert "education" in codes, codes
    assert len(codes) == 4


def test_without_an_education_the_education_paths_are_not_offered():
    """Four rows that are secretly two overstate how much was explored."""
    sub = household(raw={"education_hours": "keine", "education_budget": 0.0,
                         "education_recent": "", "education_planned": ""})
    codes = [p["code"] for p in P.income_paths(sub, Params())]
    assert "education" not in codes and len(codes) == 3


def test_the_full_pensum_path_earns_more_than_the_reduced_one():
    """The arithmetic a household can check in its head, and the largest single step for this case."""
    runs = {r["code"]: r for r in run(household())["paths"]}
    assert runs["full_pensum"]["income_now"] > runs["education"]["income_now"]
    assert runs["full_pensum"]["free_now"] > runs["education"]["free_now"]


def test_education_raises_income_over_the_path_that_skips_it():
    runs = {r["code"]: r for r in run(household())["paths"]}
    assert runs["education"]["income_at_45"] > runs["today"]["income_at_45"]


def test_skill_growth_is_held_after_the_window_the_engine_supports():
    """**Measured: `beta_E` compounds at 15 % a year and `earning_power` is bounded.**

    Projected to 65 every path sits on `earning_power_max` from about year ten, so four rows that look
    distinct would be identical. The projection is therefore held after `SKILL_PROJECTION_YEARS`, and this is
    what stops that bound being quietly removed again.
    """
    p = Params()
    path = P.income_paths(household(), p)[-1]
    beyond = P.SKILL_PROJECTION_YEARS + 5
    # Past the window the only thing still moving is the age profile, so two ages inside the flat part of
    # that profile give the same income.
    assert path["income_at"](24 + beyond) == pytest.approx(path["income_at"](24 + beyond + 1), rel=0.02)
    assert P.SKILL_PROJECTION_YEARS <= 10, "beyond ten years every path is on the ceiling"


# --- the goals -------------------------------------------------------------------------------------------

def test_every_goal_appears_on_its_own_date_with_retirement_among_them():
    """A young household's plan is not one run to 65: retirement is a row, not the frame."""
    rows = run(household())["paths"][0]["goals"]
    years = [g["target_year"] for g in rows]
    assert years == sorted(years) and 2037 in years and 2067 in years
    assert any(g["kind"] == "retirement" for g in rows)


def test_the_required_saving_is_the_capital_less_what_is_there_over_the_years():
    """At zero return the arithmetic is deliberately trivial, and that is what makes it checkable."""
    sub = household()
    row = next(g for g in run(sub)["paths"][0]["goals"] if g["kind"] == "home")
    liquid = sub["state"]["W_L"]
    assert row["required_saving"] == pytest.approx((row["target"] - liquid) / row["years"])


def test_a_richer_path_lowers_the_retirement_target_rather_than_only_funding_it():
    """**The property the single-salary arithmetic could not express at all.**

    AHV is a function of averaged lifetime income and the second pillar accrues on the coordinated salary, so
    a path that raises income also raises what arrives from 65 -- which *reduces* the capital to build. The old
    version computed one gap and one target regardless of what anybody did.
    """
    runs = {r["code"]: r for r in run(household())["paths"]}
    poor = next(g for g in runs["today"]["goals"] if g["kind"] == "retirement")
    rich = next(g for g in runs["full_pensum"]["goals"] if g["kind"] == "retirement")
    assert runs["full_pensum"]["flows_from_65"]["total"] > runs["today"]["flows_from_65"]["total"]
    assert rich["target"] < poor["target"]


def test_a_goal_that_no_path_can_fund_is_reported_as_short_rather_than_optimised():
    """A two-million target eleven years out is not a portfolio question, and the table says so plainly."""
    sub = household(goals=[{"kind": "home", "description": "Eigentum 2 Mio", "target_year": 2037,
                            "amount_chf": 2_000_000.0, "confidence": 0.7, "is_consumption": False}])
    for r in run(sub)["paths"]:
        row = r["goals"][0]
        assert not row["reachable"]
        assert row["shortfall_per_year"] > 0


# --- what the ledger says about itself -------------------------------------------------------------------

def test_the_first_column_is_the_zero_baseline_and_the_returns_come_after_it():
    """**Zero is the overview, not the answer.** It says what a goal costs in saving alone -- a figure a
    household can check and no market can be blamed for -- and the columns after it then ask whether a return
    closes what is left. A table that stopped at zero would leave the second question hanging.
    """
    led = run(household())
    assert led["return_assumed"] == 0.0
    assert led["rates"][0]["rate"] == "0.0000"
    assert "Grundlinie" in led["rates"][0]["whose"]
    assert any("ohne Rendite" in a and "mit Rendite" in a for a in led["assumptions"])


def test_a_stated_expectation_becomes_a_column_labelled_as_the_clients_own():
    """A return in a plan is a claim about the future, and the report makes none of its own."""
    led = run(household(raw={"expected_return_pct": "8 %"}))
    assert len(led["rates"]) == 2
    assert led["rates"][1]["rate"] == "0.0800"
    assert "Ihre eigene" in led["rates"][1]["whose"]
    row = led["paths"][0]["goals"][0]
    # A return can only lower what must be saved, never raise it.
    assert row["required_by_rate"]["0.0800"] < row["required_by_rate"]["0.0000"]


def test_a_goal_already_covered_by_growth_asks_for_nothing_rather_than_a_negative():
    assert P.saving_required(target=100.0, present=1000.0, years=10.0, rate=0.05) == 0.0
    assert P.saving_required(target=100.0, present=0.0, years=10.0, rate=0.0) == pytest.approx(10.0)


def test_a_missing_income_anchor_is_declared_as_a_modelled_level():
    """A stated level and a modelled one are different claims, and the difference is the client's own number."""
    led = run(household())
    assert led["anchored"] is False
    assert any("Modell" in a for a in led["assumptions"])
    assert all(r["basis"] == "modelled" for r in led["paths"])


def test_the_clients_own_figure_anchors_every_path_when_given():
    led = run(household(raw={"income_expected_full": 95_000.0}))
    assert led["anchored"] is True
    runs = {r["code"]: r for r in led["paths"]}
    # Anchored at the full Pensum after the education, so that path earns about the stated figure there.
    assert runs["full_pensum"]["income_at_45"] > 0
    assert runs["full_pensum"]["income_now"] == pytest.approx(95_000.0, rel=0.35)


def test_every_value_that_leaves_the_module_is_plain_json():
    """**The model returns numpy scalars and this crosses a process boundary.**

    A `np.bool_` from one comparison took the whole report down with "Object of type bool is not JSON
    serializable", far from the line that produced it.
    """
    import json
    json.dumps(run(household()), ensure_ascii=False)


def test_a_household_that_never_stated_a_stop_age_still_gets_its_paths():
    """**The whole section used to vanish for them, and the report did not say so.**

    Only `onb@0.1.3` asks when somebody wants to stop earning. Older and hand-written submissions carry None,
    every arithmetic here subtracted a float from it, and the exception was recorded in a field nothing
    rendered -- so the paths were simply absent, indistinguishable from a household they do not apply to.
    None now reads as what it means: contributions run to the reference age.
    """
    sub = household()
    p = Params(**{k: v for k, v in sub["params"].items() if k in Params.__dataclass_fields__})
    led = P.ledger(sub, p, stop_age=None)
    assert led["paths"] and led["paths"][0]["goals"]
    to_reference = P.ledger(sub, p, stop_age=p.ahv_age)
    assert (led["paths"][0]["flows_from_65"]["total"]
            == pytest.approx(to_reference["paths"][0]["flows_from_65"]["total"]))


def test_a_household_with_no_dated_goal_still_produces_paths():
    """The income paths are worth having even when there is nothing to measure them against yet."""
    led = run(household(goals=[]))
    assert led["paths"] and all(r["goals"] == [] for r in led["paths"])
    assert all(r["income_now"] > 0 for r in led["paths"])
