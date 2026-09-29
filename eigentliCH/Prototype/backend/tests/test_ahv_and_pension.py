"""The first and second pillars: the statutory table, the age bands, and the refusals guarding both.

Written against the published documents rather than against constructed figures. The AHV cases are rows
of the official Skala 44 table; the BVG cases are the four bands of Art. 16 and the boundaries between
them, which is where an off-by-one in a projection hides.

**The refusal is the assertion that matters most.** Both records ship provisional, so on a clean checkout
every path producing a franc figure raises. A suite that only ran against approved fixtures would pass
while the shipped state was broken in the other direction.
"""

from __future__ import annotations

import json

import pytest

from eigentlich.services import ahv
from eigentlich.services import pension_projection as pp


def _approve(monkeypatch, module, name):
    from eigentlich import content

    record = json.loads(json.dumps(content._load(name)))
    record["_about"].update({
        "provisional": False, "published_by": "Test Fixture",
        "decided_on": "2026-09-05", "effective_from": "2026-09-05",
    })
    monkeypatch.setattr(module, "_record", lambda: record)
    return record


@pytest.fixture()
def ahv_approved(monkeypatch):
    return _approve(monkeypatch, ahv, "ahv-pension")


@pytest.fixture()
def bvg_approved(monkeypatch):
    return _approve(monkeypatch, pp, "bvg-projection")


# ============================================================ the refusals


def test_the_ahv_scale_still_ships_provisional_and_computes_nothing():
    """**`ahv-pension` has NOT been approved and this is the test that keeps saying so.**

    Its sibling `bvg-projection` was approved by the owner on 22 September 2026 and this file was updated
    in the same commit — the two records were asserted together until then, and that is the assertion that
    caught the change rather than being quietly broken by it. Splitting them is the point: two records
    with one guard means approving either one silences the guard on both.
    """
    from eigentlich import content

    about = content._load("ahv-pension")["_about"]
    assert about["provisional"] is True, (
        "ahv-pension was approved without this test being updated. Approving is the owner's act and it "
        "has consequences this file describes; do not flip the assertion to match the file."
    )
    assert about["published_by"] is None

    with pytest.raises(ahv.ScaleNotApproved):
        ahv.pension(mdje=70_000)


def test_the_bvg_projection_is_approved_and_computes():
    """Approved 22 September 2026, on the owner's instruction, with its four `_for_review` concerns open.

    Nine of the fifty members measured on 20 September asked about their own provision and got "not
    determinable" because this record was provisional. What the approval settled is that an illustration
    of the statutory rule, carrying its three caveats on every output, beats refusing to compute — not
    that the concerns went away.
    """
    from eigentlich import content

    about = content._load("bvg-projection")["_about"]
    assert about["provisional"] is False
    assert about["published_by"], "an approved record names who approved it"

    result = pp.project(current_age=30, opening_balance=0, gross_salary=80_000)
    assert result.closing_balance > 0
    assert result.monthly_pension > 0


def test_the_approved_projection_still_carries_every_caveat():
    """The approval did not remove a single one, and a figure without them is the thing to prevent.

    Planted violation: dropping `caveats` from `Projection` — the interest caveat is the one that matters,
    because the Mindestzinssatz reads as a forecast to anyone who is not told otherwise.
    """
    result = pp.project(current_age=45, opening_balance=200_000, gross_salary=120_000)
    assert "interest_is_a_statutory_minimum_not_a_return" in result.caveats
    assert "the_obligatory_portion_only_the_ueberobligatorium_is_not_visible_here" in result.caveats
    assert "the_salary_is_assumed_unchanged_to_the_reference_age" in result.caveats


def test_every_ahv_entry_point_still_refuses():
    for call in (lambda: ahv.full_monthly(70_000),
                 lambda: ahv.pension(mdje=70_000),
                 lambda: ahv.illustration_for(current_income=70_000),
                 lambda: ahv.scale()):
        with pytest.raises(ahv.ScaleNotApproved):
            call()


def test_the_shape_of_each_rule_is_readable_without_approval():
    """Same split as `property.occupancies()`: the rule's shape puts no figure on any member."""
    b = ahv.bounds()
    assert b["minimum"] == 1260 and b["maximum"] == 2520
    assert b["maximum"] == 2 * b["minimum"], "the maximum is exactly twice the minimum"
    assert b["couple_cap"] == 3780, "150 percent of the maximum, not 200"
    assert b["payments_per_year"] == 13, "the thirteenth pension, from 2026"

    bands = pp.bands()
    assert [x["rate"] for x in bands] == [0.07, 0.10, 0.15, 0.18]
    assert [x["from_age"] for x in bands] == [25, 35, 45, 55]


# ============================================================ the AHV table


@pytest.mark.parametrize("mdje,monthly", [
    (0, 1260), (10_000, 1260), (15_120, 1260),   # at or below the first row: the minimum
    (15_121, 1293),                              # one franc over pushes to the next row
    (45_360, 1915),                              # the bend, visible in the published data
    (90_720, 2520), (250_000, 2520),             # at or above the last row: the maximum
])
def test_the_published_rows_are_reproduced_exactly(ahv_approved, mdje, monthly):
    """Rows of the official table, not a formula I fitted.

    A two-piece linear formula through these points is derivable — the slope changes at 45'360 — and was
    deliberately not used: a fitted formula is a figure nobody published, and the table is what the
    Ausgleichskasse applies.
    """
    assert ahv.full_monthly(mdje) == monthly


def test_the_bestimmungsgroesse_column_is_an_upper_bound(ahv_approved):
    """The published column reads «bis / jusqu'à». A row is the pension for everything up to its value."""
    row = ahv_approved["monthly"]["scale_44"][10]
    below = ahv_approved["monthly"]["scale_44"][9]
    assert ahv.full_monthly(row["up_to"]) == row["monthly"]
    assert ahv.full_monthly(below["up_to"] + 1) == row["monthly"]


def test_the_table_never_decreases_and_spans_the_stated_bounds(ahv_approved):
    rows = ahv_approved["monthly"]["scale_44"]
    assert len(rows) == 51
    assert [r["monthly"] for r in rows] == sorted(r["monthly"] for r in rows)
    assert rows[0]["monthly"] == ahv_approved["monthly"]["minimum"]
    assert rows[-1]["monthly"] == ahv_approved["monthly"]["maximum"]
    steps = {rows[i + 1]["up_to"] - rows[i]["up_to"] for i in range(len(rows) - 1)}
    assert steps == {1512}, "the published grid is a constant step, and a transcription slip would show here"


def test_a_missing_contribution_year_costs_one_forty_fourth(ahv_approved):
    """Merkblatt 3.01's own figure, and the Berechnungsvorschriften table at 8.2 is `Skala / 44`."""
    full = ahv.pension(mdje=69_550, contribution_years=44)
    short = ahv.pension(mdje=69_550, contribution_years=43)
    assert full.factor == 1.0
    assert short.factor == pytest.approx(43 / 44)
    assert short.monthly == pytest.approx(full.monthly * 43 / 44)


def test_an_unstated_record_is_a_caveat_and_not_a_silent_full_one(ahv_approved):
    """`None` means nobody said. Treating it as complete without saying so would be the quiet error."""
    result = ahv.pension(mdje=69_550, contribution_years=None)
    assert result.factor == 1.0
    assert "the_contribution_record_was_not_stated_so_a_full_one_is_assumed" in result.caveats


def test_the_yearly_figure_uses_thirteen_payments(ahv_approved):
    """Twelve would understate it by a whole month, which a member cannot catch by inspection."""
    result = ahv.pension(mdje=90_720)
    assert result.monthly == 2520
    assert result.yearly == 2520 * 13


def test_current_income_is_never_silently_used_as_a_lifetime_average(ahv_approved):
    """**The input nobody has.** The table is keyed on a revalued lifetime average; the build holds today's
    salary. The substitution is legitimate only if it is loud, so it lives in a differently-named function
    and arrives back as the first caveat."""
    plain = ahv.pension(mdje=69_550)
    assert "current_income_was_used_where_a_lifetime_average_belongs" not in plain.caveats

    loud = ahv.illustration_for(current_income=69_550)
    assert loud.caveats[0] == "current_income_was_used_where_a_lifetime_average_belongs"
    assert loud.monthly == plain.monthly, "same arithmetic, different honesty"


def test_the_couple_cap_binds_at_150_percent_and_says_what_it_cost(ahv_approved):
    both_max = ahv.pension(mdje=90_720)
    result = ahv.couple(first=both_max, second=both_max)
    assert result["uncapped_monthly"] == 5040
    assert result["monthly"] == 3780
    assert result["cap_binds"] is True
    assert result["lost_to_the_cap_monthly"] == 1260, "a whole minimum pension, lost to being married"


def test_levers_name_the_two_omissions_that_move_the_figure_up(ahv_approved):
    """Erziehungs- and Betreuungsgutschriften raise the mdJE and are not modelled anywhere in the build.

    A member reading a pension figure that omits them should meet that beside the figure, not in a
    footnote, so `levers` carries every `not_modelled` item rather than only the ones that reduce it.
    """
    notes = " ".join(str(x.get("note", "")) for x in ahv.levers(ahv.pension(mdje=50_000)))
    assert "Erziehungsgutschriften" in notes
    assert "Splitting" in notes


# ============================================================ the second pillar


@pytest.mark.parametrize("age,rate", [
    (18, 0.0), (24, 0.0),               # death and invalidity only below 25
    (25, 0.07), (34, 0.07),
    (35, 0.10), (44, 0.10),
    (45, 0.15), (54, 0.15),
    (55, 0.18), (65, 0.18),
])
def test_the_credit_rate_steps_exactly_where_article_16_says(bvg_approved, age, rate):
    assert pp.credit_rate(age) == rate


def test_nothing_is_credited_before_twenty_five(bvg_approved):
    """A balance of zero at 23 is consistent with being correctly insured, and the projection must not
    quietly start early to make the number look better."""
    result = pp.project(current_age=23, opening_balance=0, gross_salary=69_550)
    assert [y["credit"] for y in result.years[:2]] == [0.0, 0.0]
    assert result.years[2]["age"] == 25 and result.years[2]["credit"] > 0


def test_the_coordinated_salary_is_the_salary_less_a_fixed_deduction(bvg_approved):
    assert pp.coordinated_salary(69_550) == pytest.approx(69_550 - 26_460)
    # capped at the upper limit before the deduction
    assert pp.coordinated_salary(200_000) == pytest.approx(90_720 - 26_460)


def test_a_salary_below_the_threshold_is_none_and_not_zero(bvg_approved):
    """Different statements: no obligatory insurance at all, versus insured on nothing."""
    assert pp.coordinated_salary(20_000) is None
    result = pp.project(current_age=30, opening_balance=0, gross_salary=20_000)
    assert result.closing_balance == 0
    assert "the_salary_is_below_the_entry_threshold_so_nothing_is_credited" in result.caveats


def test_the_fixed_deduction_hits_a_small_pensum_harder_than_proportionally(bvg_approved):
    """The deduction removes the same amount from both salaries, so halving pay more than halves cover."""
    small, large = pp.coordinated_salary(40_000), pp.coordinated_salary(80_000)
    assert large / small > 2


def test_the_projection_reconciles_to_its_own_parts(bvg_approved):
    result = pp.project(current_age=30, opening_balance=50_000, gross_salary=90_000)
    assert result.closing_balance == pytest.approx(
        result.opening_balance + result.total_credited + result.total_interest
    )
    assert len(result.years) == result.to_age - result.from_age
    assert result.monthly_pension == pytest.approx(result.closing_balance * 0.068 / 12)


def test_every_projection_carries_the_caveat_that_the_rate_is_not_a_return(bvg_approved):
    """The Mindestzinssatz is a floor set for one year and revisited annually. A member reading a
    forty-year projection at it will read a forecast unless the output says otherwise."""
    result = pp.project(current_age=40, opening_balance=100_000, gross_salary=100_000)
    assert "interest_is_a_statutory_minimum_not_a_return" in result.caveats
    assert "the_obligatory_portion_only_the_ueberobligatorium_is_not_visible_here" in result.caveats


def test_marvin_is_the_case_the_two_modules_were_built_for(ahv_approved, bvg_approved):
    """23, 69'550 gross, a pillar 2 of zero, and a stated retirement need of 57'000 a year.

    His Befund said «Das Modell führt keine AHV-Rente» and his dossier said the retirement gap was
    *probably* not a gap. Both pillars now compute, and the two together answer it rather than guessing:
    the first pillar alone is over half the need.
    """
    first = ahv.illustration_for(current_income=69_550)
    second = pp.project(current_age=23, opening_balance=0, gross_salary=69_550)
    together = first.yearly + second.monthly_pension * 12

    assert first.monthly == 2238
    assert second.coordinated == pytest.approx(43_090)
    assert 45_000 < together < 50_000
    assert together > 57_000 * 0.75, "the two pillars carry three quarters of what he says he needs"
