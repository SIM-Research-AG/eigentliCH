"""The second pillar as the law builds it, and the sourced table behind it.

**Why this file exists.** The model credited a flat 15 % of full salary from whatever age the household
happened to be, with a gate that closed at retirement and never opened at the bottom. On a twenty-four-year-old
earning 24 000 at a reduced Pensum that produced 3 600 a year, 172 824 by 65, and an annuity of 9 073 -- a
third of the entire income the report promised him from 65, accrued in years he cannot legally accrue in. The
whole engine suite passed while that was true, which is the other reason this file exists: nothing pinned the
figure.

Every threshold asserted here is quoted from `data/social_insurance.json`, never written into the test, so a
new vintage cannot leave a stale number behind in the assertions.
"""

from __future__ import annotations

import json

import pytest

from personal_alm.model import bvg
from personal_alm.model.params import Params

TABLE = bvg.load()
B = TABLE["bvg"]


# --- the coordinated salary ------------------------------------------------------------------------------

def test_below_the_entry_threshold_there_is_no_insurance_at_all():
    """Not "a small coordinated salary": none. The two produce different plans."""
    assert bvg.coordinated_salary(B["entry_threshold_yearly"] - 1, TABLE) == 0.0
    assert bvg.coordinated_salary(0.0, TABLE) == 0.0


def test_at_the_threshold_the_minimum_applies_rather_than_a_negative():
    """**The case the flat rate got most wrong.** At a low salary the coordination deduction exceeds the
    salary itself, so what remains is the statutory minimum -- a small fraction of the figure a flat rate on
    full income produces, which is why a 24 000 earner was credited an eighth of what the model assumed.
    """
    at_threshold = bvg.coordinated_salary(B["entry_threshold_yearly"], TABLE)
    assert at_threshold == B["min_coordinated_salary_yearly"]
    assert B["coordination_deduction_yearly"] > B["entry_threshold_yearly"], (
        "the deduction exceeding the threshold is what makes the minimum bind at all"
    )


def test_a_middle_salary_is_the_salary_less_the_deduction():
    gross = 60_000.0
    assert bvg.coordinated_salary(gross, TABLE) == gross - B["coordination_deduction_yearly"]


def test_above_the_upper_limit_the_insured_salary_stops_growing():
    at_limit = bvg.coordinated_salary(B["upper_limit_yearly"], TABLE)
    assert bvg.coordinated_salary(1_000_000.0, TABLE) == at_limit
    assert at_limit == B["upper_limit_yearly"] - B["coordination_deduction_yearly"]


# --- the age bands ---------------------------------------------------------------------------------------

def test_nothing_accrues_before_the_start_age():
    start = B["savings_start_age"]
    assert bvg.savings_rate(start - 0.1, TABLE) == 0.0
    assert bvg.savings_rate(start, TABLE) > 0.0


def test_the_rate_rises_by_band_and_never_falls():
    rates = [bvg.savings_rate(a, TABLE) for a in (25, 30, 34, 35, 44, 45, 54, 55, 64)]
    assert rates == sorted(rates), rates
    assert len(set(rates)) == len(B["savings_rates"]), "each band should be visible in the sample"


def test_the_bands_are_steps_and_not_a_curve():
    """They are a step function in law. Smoothing them would produce a number no fund will credit."""
    first = B["savings_rates"][0]
    assert bvg.savings_rate(first["from_age"], TABLE) == bvg.savings_rate(first["to_age"], TABLE)


# --- the accrual -----------------------------------------------------------------------------------------

def test_a_young_low_earner_accrues_a_fraction_of_the_flat_rate_figure():
    """The measurement that prompted the whole module, stated as a relation rather than a magic number."""
    p = Params()
    got = bvg.accrue(age_now=24, age_stop=60, age_reference=65, start_capital=0.0,
                     interest=p.pension_interest, income_at=lambda _a: 24_000.0, table=TABLE)
    flat = p.pension_contribution_rate * 24_000.0 * 36  # what the old closed form credited, undiscounted
    assert got["contributed"] < flat / 5, (
        f"credited {got['contributed']:.0f} against the flat rate's {flat:.0f}"
    )
    # And none of it in the years before the start age.
    early = [y for y in got["years"] if y["age"] < B["savings_start_age"]]
    assert early and all(y["credit"] == 0.0 for y in early)


def test_stopping_early_costs_the_contributions_and_not_the_growth():
    """A household that stops at 55 loses ten years of credits; what is already there keeps earning."""
    common = dict(age_now=40, age_reference=65, start_capital=200_000.0, interest=0.0125,
                  income_at=lambda _a: 100_000.0, table=TABLE)
    early = bvg.accrue(age_stop=55, **common)
    full = bvg.accrue(age_stop=65, **common)
    assert early["contributed"] < full["contributed"]
    # The starting capital still compounds over the whole span in both cases, so the gap between them is
    # smaller than the missing credits themselves would suggest if growth stopped too.
    assert early["capital"] > 200_000.0 * (1.0125 ** 25)


def test_the_income_path_is_a_function_of_age_and_actually_moves_the_result():
    """**The seam the path simulation needs.** A closed-form annuity factor can only express a flat salary,
    and a young household's income is the one thing certain to change.
    """
    flat = bvg.accrue(age_now=25, age_stop=65, age_reference=65, start_capital=0.0, interest=0.0125,
                      income_at=lambda _a: 60_000.0, table=TABLE)
    rising = bvg.accrue(age_now=25, age_stop=65, age_reference=65, start_capital=0.0, interest=0.0125,
                        income_at=lambda a: 40_000.0 if a < 35 else 90_000.0, table=TABLE)
    assert rising["capital"] != flat["capital"]
    assert len(rising["years"]) == 40


def test_the_trace_names_every_year_that_produced_the_capital():
    got = bvg.accrue(age_now=30, age_stop=65, age_reference=65, start_capital=0.0, interest=0.0,
                     income_at=lambda _a: 80_000.0, table=TABLE)
    assert got["capital"] == pytest.approx(sum(y["credit"] for y in got["years"]))
    assert got["years"][0]["coordinated"] == bvg.coordinated_salary(80_000.0, TABLE)


# --- the table itself ------------------------------------------------------------------------------------

def test_the_table_carries_its_source_and_vintage():
    """Every forward-looking figure in a report inherits this vintage, so it may not be absent."""
    assert TABLE["source"] and TABLE["as_of"]
    assert "BSV" in TABLE["source"]


def test_a_table_without_a_vintage_is_refused(tmp_path):
    bad = tmp_path / "no_vintage.json"
    bad.write_text(json.dumps({"bvg": TABLE["bvg"], "ahv": TABLE["ahv"]}), encoding="utf-8")
    with pytest.raises(bvg.TableError, match="vintage"):
        bvg.load(bad)


def test_a_missing_table_is_an_error_rather_than_a_silent_fallback(tmp_path):
    """**Deliberately unlike the canton table.** A missing cantonal factor leaves the national approximation
    standing, which degrades honestly. A missing BVG table would mean falling back to a flat rate on full
    income -- the defect this module removed -- for exactly the households it was found on.
    """
    with pytest.raises(bvg.TableError, match="missing"):
        bvg.load(tmp_path / "absent.json")


def test_the_ahv_defaults_agree_with_the_sourced_scale():
    """**The 13th payment, which the model was missing.** `ahv_full_single` carried 30 240, twelve times the
    published maximum, so every household was short a month of pension a year. The parameter must stay a
    constant for the dual transcription, so this is what stops it drifting from the table again.
    """
    p, a = Params(), TABLE["ahv"]
    assert p.ahv_full_single == a["max_pension_monthly"] * a["payments_per_year"]
    assert p.ahv_min_single == a["min_pension_monthly"] * a["payments_per_year"]
    assert a["payments_per_year"] == 13, "if this ever returns to 12, both defaults move with it"


def test_the_income_reaching_the_maximum_pension_is_the_bvg_upper_limit():
    """The two are the same published figure, and carrying it twice is how they come to disagree."""
    assert Params().ahv_income_for_max == TABLE["bvg"]["upper_limit_yearly"]


def test_the_pillar3a_cap_agrees_with_the_sourced_figure():
    assert Params().pillar3a_cap == TABLE["pillar3a"]["max_with_pension_fund"]
