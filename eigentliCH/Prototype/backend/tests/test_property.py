"""Property goals: the two tests, the occupancy rule, and the refusal that guards all of it.

Written against the six real submissions rather than against constructed figures, because the whole reason
this module exists is that four of their eleven goals are property purchases and the build could not read
one. The cases at the bottom are the arithmetic from `tools/property_check.py`, and if they drift the
module has changed its mind about something a report already told the owner.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from eigentlich.services import property as prop
from eigentlich.services.property import (
    AFFORDABILITY,
    COULD_NOT_BE_DETERMINED,
    ConventionsNotApproved,
    DOES_NOT_MEET,
    EQUITY,
    MEETS,
    UnknownOccupancy,
    assess,
    levers,
)

PRIMARY = "owner_occupied_primary"
HOLIDAY = "second_or_holiday_home"
LET = "let_to_someone_else"

MARCH = date(2038, 12, 31)


@pytest.fixture()
def approved(monkeypatch):
    """The record with an owner's name on it, for the length of one test.

    The shipped record is provisional and must stay that way until someone approves it, so every test that
    needs a figure approves a copy. That is not a workaround: it is the same shape as the refusal, seen
    from the other side.
    """
    from eigentlich import content

    record = json.loads(json.dumps(content._load("property-funding")))
    record["_about"].update({
        "provisional": False,
        "published_by": "Test Fixture",
        "decided_on": "2026-09-04",
        "effective_from": "2026-09-04",
    })
    monkeypatch.setattr("eigentlich.services.property._record", lambda: record)
    return record


# ============================================================ the refusal


def test_the_shipped_record_is_approved_and_names_who_approved_it():
    """The owner approved it on 4 September 2026. Until then this file asserted the opposite.

    Kept in the inverse rather than deleted, because the property of interest never was "is it
    provisional" — it is **does a person stand behind these figures**. A record that lost its publisher
    in an edit would be one nobody stands behind, computing away.
    """
    from eigentlich import content

    about = content._load("property-funding")["_about"]
    assert about["provisional"] is False
    assert about["published_by"], "the conventions carry no publisher"
    assert about["decided_on"], "the conventions carry no decision date"
    prop.conventions()  # does not raise


def test_a_record_that_goes_back_to_provisional_computes_nothing(monkeypatch):
    """The refusal, still guarded after approval.

    The mechanism is the point and it outlives the state it was written for: if the figures are ever
    reopened for revision, everything downstream must stop rather than serve the old ones.
    """
    from eigentlich import content

    record = json.loads(json.dumps(content._load("property-funding")))
    record["_about"]["provisional"] = True
    monkeypatch.setattr("eigentlich.services.property._record", lambda: record)
    with pytest.raises(ConventionsNotApproved) as raised:
        prop.conventions()
    assert "provisional" in str(raised.value)


def test_approval_without_a_publisher_is_still_refused(monkeypatch):
    from eigentlich import content

    record = json.loads(json.dumps(content._load("property-funding")))
    record["_about"].update({"provisional": False, "published_by": None})
    monkeypatch.setattr("eigentlich.services.property._record", lambda: record)
    with pytest.raises(ConventionsNotApproved):
        prop.conventions()


def test_the_occupancy_set_is_readable_without_approval():
    """The question can be asked before the figures are approved — asking puts no number in front of
    anybody, and the set is needed to render the control and validate the answer."""
    keys = prop.occupancies()
    assert set(keys) == {PRIMARY, HOLIDAY, LET}
    assert all(not key.startswith("_") for key in keys), "a note leaked into the occupancy set"


def test_every_declared_occupancy_carries_the_four_fields_the_service_reads():
    for key, rule in prop.occupancies().items():
        for field in ("equity_min", "hard_equity_min", "pillar2_may_fund", "pillar3a_may_fund"):
            assert field in rule, f"{key} declares no {field}"
        assert rule["hard_equity_min"] <= rule["equity_min"], key


def test_an_undeclared_occupancy_is_refused():
    with pytest.raises(UnknownOccupancy):
        prop.occupancy_rule("houseboat")


# ============================================================ the occupancy rule


def test_pension_capital_may_fund_a_home_the_member_lives_in(approved):
    rule = prop.equity(1_000_000, occupancy=PRIMARY)
    assert rule.required == 200_000
    assert rule.hard_required == 100_000
    assert rule.pillar2_may_fund is True
    # At most half the deposit, which is the requirement less the hard-equity floor.
    assert rule.pillar2_cap == 100_000


def test_pension_capital_may_not_fund_a_holiday_home(approved):
    rule = prop.equity(1_000_000, occupancy=HOLIDAY)
    assert rule.pillar2_may_fund is False
    assert rule.pillar3a_may_fund is False
    assert rule.pillar2_cap == 0
    # The whole deposit is hard equity, so there is no half to fill with anything.
    assert rule.hard_required == rule.required


def test_pension_capital_may_not_fund_a_let_property(approved):
    rule = prop.equity(1_000_000, occupancy=LET)
    assert rule.pillar2_may_fund is False
    assert rule.pillar3a_may_fund is False


def test_a_3a_counts_as_hard_equity_for_a_home_and_not_for_a_holiday_home(approved):
    """The distinction that decides one of the six real cases.

    The same 3a balance is a deposit for a home the member lives in and unavailable for a Ferienhaus.
    """
    common = dict(goal_id="g", price=500_000, target_date=MARCH, hard_available=0.0,
                  pillar3a_available=100_000, household_income=1_000_000)
    assert assess(occupancy=PRIMARY, **common).equity_verdict == MEETS
    assert assess(occupancy=HOLIDAY, **common).equity_verdict == DOES_NOT_MEET


def test_ineligible_capital_is_reported_as_a_fact_with_its_rule(approved):
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=HOLIDAY,
        hard_available=64_000, pillar2_available=95_000, pillar3a_available=77_000,
        household_income=285_860,
    )
    kinds = {one["kind"]: one for one in result.ineligible}
    assert kinds["pillar_2"]["amount_chf"] == 95_000
    assert kinds["pillar_3a"]["amount_chf"] == 77_000
    assert all(
        one["reason"] == "vorsorge_capital_only_for_an_owner_occupied_primary_residence"
        for one in result.ineligible
    )


def test_nothing_is_reported_ineligible_when_the_member_holds_none(approved):
    """A member with no pension capital is not told that their pension capital is ineligible."""
    result = assess(
        goal_id="g", price=1_000_000, target_date=MARCH, occupancy=HOLIDAY,
        hard_available=500_000, household_income=1_000_000,
    )
    assert result.ineligible == []


# ============================================================ never the favourable case


def test_an_unstated_occupancy_could_not_be_determined(approved):
    """Assuming owner-occupied would make pension capital eligible for a holiday home. A110's discipline."""
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=None,
        hard_available=64_000, pillar2_available=95_000, pillar3a_available=77_000,
        household_income=285_860,
    )
    assert result.equity_verdict == COULD_NOT_BE_DETERMINED
    assert result.affordability_verdict == COULD_NOT_BE_DETERMINED
    assert "the_goal_does_not_say_whether_the_member_will_live_in_it" in result.undetermined_because
    assert result.binds_on == []


def test_unlinked_funding_is_undetermined_and_not_a_shortfall(approved):
    """The mirror of the occupancy rule, and a defect found by running a real member through the route.

    Marvin holds 222'750 against a 150'000 hard requirement, and the equity test reported
    `does_not_meet` — because no goal in the build has funding linked, so the caller passed zero. Zero
    and "not stated" are different facts and only one of them is his.
    """
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=None, household_income=69_550,
    )
    assert result.equity_verdict == COULD_NOT_BE_DETERMINED
    assert "no_position_is_linked_to_this_goal" in result.undetermined_because
    assert result.verdict == COULD_NOT_BE_DETERMINED
    assert EQUITY not in result.binds_on

    # The affordability half still answers: it reads the income position, not the funding links.
    assert result.affordability_verdict == DOES_NOT_MEET


def test_a_stated_zero_is_a_shortfall_and_not_an_absence(approved):
    """The other side of the same distinction. A member who links a position holding nothing HAS said
    which money is for the goal, and the answer is that it does not cover the deposit."""
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=0, household_income=69_550,
    )
    assert result.equity_verdict == DOES_NOT_MEET
    assert "no_position_is_linked_to_this_goal" not in result.undetermined_because


def test_a_goal_with_no_amount_could_not_be_determined(approved):
    result = assess(
        goal_id="g", price=None, target_date=MARCH, occupancy=PRIMARY,
        hard_available=100_000, household_income=100_000,
    )
    assert "the_goal_names_no_amount" in result.undetermined_because


def test_no_household_income_could_not_be_determined_rather_than_zero(approved):
    """Zero income would report DOES_NOT_MEET, which is a false statement about a member who simply has
    not stated one."""
    result = assess(
        goal_id="g", price=500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=200_000, household_income=None,
    )
    assert result.affordability_verdict == COULD_NOT_BE_DETERMINED
    assert result.equity_verdict == MEETS, "the equity test does not need an income"
    assert "no_income_is_recorded_for_the_household" in result.undetermined_because


# ============================================================ the affordability convention


def test_the_affordability_convention_reproduces_the_familiar_multiple(approved):
    """About 5.7x gross income. Not a number this module invented — it is what the published convention
    produces, and it is the standard Swiss rule of thumb, which is the check that the convention was
    transcribed correctly."""
    result = prop.affordability(1_000_000, income=None)
    assert round(result.annual_cost / 1_000_000, 5) == 0.05889
    supported = prop.affordability(1_000_000, income=100_000).price_supported
    assert 5.6 < supported / 100_000 < 5.7


def test_the_imputed_rate_is_not_in_the_code():
    """C-02, as an AST-free but real check: the module must not carry the figures it reads.

    A guard that reads prose matches its own docstring — three did this week — so this reads the module
    source with the docstring removed.
    """
    import ast
    import inspect

    source = inspect.getsource(prop)
    tree = ast.parse(source)
    numbers = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert 0.05 not in numbers, "the imputed rate is a literal in services/property.py"
    assert 0.2 not in numbers and 0.20 not in numbers, "an equity floor is a literal"
    assert 0.01 not in numbers, "the maintenance fraction is a literal"


# ============================================================ the six real cases


#: The submissions, as the report published them. Figures from `tools/property_check.py`.
REAL = [
    # who, price, year, occupancy, hard, p2, p3a, household income, binds on
    ("Marvin M.", 1_500_000, 2038, PRIMARY, 475_600, 0, 17_750, 69_550, [AFFORDABILITY]),
    ("Renzo T.", 2_000_000, 2037, PRIMARY, 332_000, 0, 0, 24_000, [EQUITY, AFFORDABILITY]),
    ("Elia T.", 1_500_000, 2040, PRIMARY, 471_000, 0, 0, 70_200, [AFFORDABILITY]),
    ("Levin S.", 1_100_000, 2034, PRIMARY, 276_600, 0, 8_600, 175_000, [AFFORDABILITY]),
    ("Yasmin T.", 1_500_000, 2036, HOLIDAY, 64_000, 95_000, 77_000, 285_860, [EQUITY]),
]


@pytest.mark.parametrize("who,price,year,occupancy,hard,p2,p3a,income,binds", REAL)
def test_the_real_cases_bind_where_the_report_says_they_bind(
    approved, who, price, year, occupancy, hard, p2, p3a, income, binds
):
    result = assess(
        goal_id="g", price=price, target_date=date(year, 12, 31), occupancy=occupancy,
        hard_available=hard, pillar2_available=p2, pillar3a_available=p3a,
        household_income=income,
    )
    assert result.binds_on == binds, f"{who}: {result.binds_on} != {binds}"


def test_three_of_the_five_reach_the_deposit_and_cannot_carry_the_loan(approved):
    """The finding the whole module exists for, asserted as one statement rather than left to a reader to
    notice across five parametrised cases. The product's savings machinery is pointed at the test that is
    not binding."""
    equity_ok_income_not = 0
    for who, price, year, occupancy, hard, p2, p3a, income, _ in REAL:
        result = assess(
            goal_id="g", price=price, target_date=date(year, 12, 31), occupancy=occupancy,
            hard_available=hard, pillar2_available=p2, pillar3a_available=p3a,
            household_income=income,
        )
        if result.equity_verdict == MEETS and result.affordability_verdict == DOES_NOT_MEET:
            equity_ok_income_not += 1
    assert equity_ok_income_not == 3


def test_levin_is_the_near_miss(approved):
    """The case the first edition of the report got most wrong: 11 % out of reach on joint income, not
    149 % of one income."""
    result = assess(
        goal_id="g", price=1_100_000, target_date=date(2034, 12, 31), occupancy=PRIMARY,
        hard_available=276_600, pillar3a_available=8_600, household_income=175_000,
    )
    assert result.equity_verdict == MEETS
    assert result.affordability_verdict == DOES_NOT_MEET
    shortfall = result.price - result.affordability.price_supported
    assert 100_000 < shortfall < 120_000
    assert result.price / result.affordability.price_supported - 1 < 0.12


def test_the_household_income_changes_the_answer_and_not_the_tone(approved):
    """One income against joint income, same goal. A caller that passes one member's figure for a couple
    produces a true statement about the wrong household."""
    alone = assess(
        goal_id="g", price=1_100_000, target_date=date(2034, 12, 31), occupancy=PRIMARY,
        hard_available=276_600, household_income=90_000,
    )
    joint = assess(
        goal_id="g", price=1_100_000, target_date=date(2034, 12, 31), occupancy=PRIMARY,
        hard_available=276_600, household_income=175_000,
    )
    assert alone.affordability.price_supported < 550_000
    assert joint.affordability.price_supported > 950_000


# ============================================================ levers, and the boundary


def test_levers_are_dimensions_with_arithmetic_and_never_an_imperative(approved):
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=475_600, pillar3a_available=17_750, household_income=69_550,
    )
    got = levers(result, household_income=69_550)
    assert {one["lever"] for one in got} == {"price", "household_income"}
    for one in got:
        for value in one.values():
            assert not isinstance(value, str) or value in ("price", "household_income", "deposit"), (
                f"a lever carries prose: {one}"
            )


def test_a_goal_that_meets_both_tests_has_no_levers(approved):
    result = assess(
        goal_id="g", price=300_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=100_000, household_income=200_000,
    )
    assert result.binds_on == []
    assert levers(result, household_income=200_000) == []


def test_the_payload_carries_one_verdict_on_every_path(approved):
    """A client reads `property.verdict` and gets a string whatever happened — including on the two
    refusal paths in `services/goals.property_finding`, which build their payload by hand."""
    undetermined = assess(
        goal_id="g", price=1_000_000, target_date=MARCH, occupancy=None,
        hard_available=500_000, household_income=500_000,
    )
    assert undetermined.verdict == COULD_NOT_BE_DETERMINED

    fails = assess(
        goal_id="g", price=2_000_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=10_000, household_income=24_000,
    )
    assert fails.verdict == DOES_NOT_MEET

    passes = assess(
        goal_id="g", price=300_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=100_000, household_income=200_000,
    )
    assert passes.verdict == MEETS


def test_an_income_that_was_never_stated_does_not_read_as_a_pass(approved):
    """The failure mode a single verdict invites: both tests undetermined, no `binds_on`, and a naive
    `not binds_on -> meets` would tell a member their goal is fine."""
    result = assess(
        goal_id="g", price=2_000_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=400_000, household_income=None,
    )
    assert result.binds_on == []
    assert result.verdict == COULD_NOT_BE_DETERMINED


def test_the_payload_names_the_record_it_read(approved):
    result = assess(
        goal_id="g", price=500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=200_000, household_income=200_000,
    )
    payload = result.as_payload()
    assert payload["conventions"] == "property-funding.json"
    assert payload["occupancy"] == PRIMARY
    assert payload["equity"]["verdict"] == MEETS


def test_what_is_not_modelled_is_named_in_the_record():
    """Seven things that would change a figure and are not computed. Named rather than approximated, and
    asserted so the list cannot quietly empty."""
    from eigentlich import content

    items = content._load("property-funding")["not_modelled"]["items"]
    assert len(items) >= 7
    joined = " ".join(items).lower()
    for subject in ("rental income", "pension benefit", "age 50", "tax"):
        assert subject in joined, f"{subject} is not named among what is not modelled"


# ============================================================ the let property's affordability


def test_a_let_property_reports_affordability_as_undeterminable_rather_than_unaffordable(approved):
    """**The damaging direction of A110, found by answering the occupancy question for the first time.**

    A goal set to `let_to_someone_else` used to come back `does_not_meet` on an affordability figure
    containing no rent at all. For a property bought to let, the rent is most of the income that carries
    it: omitting it does not understate the position slightly, it removes the purpose of the purchase, and
    tells the member a lender would refuse them on a calculation no lender would run.

    The record forbade this in prose before the code did it -- `_provisional_note` on that occupancy has
    said since approval that a finding here reports the equity test and says affordability could not be
    determined. `affordability_is_determinable` is that sentence made machine-readable.
    """
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=LET,
        hard_available=205_000, pillar2_available=0, pillar3a_available=17_750,
        household_income=69_550,
    )
    assert result.affordability is None
    # the dataclass default, which is the right word for it: not "fails", not "passes"
    assert result.affordability_verdict == COULD_NOT_BE_DETERMINED
    assert AFFORDABILITY not in result.binds_on
    assert "rental_income_is_not_modelled_for_a_let_property" in result.undetermined_because
    # and the equity half is unaffected -- it is perfectly computable for a let property
    assert result.equity is not None
    assert result.equity_verdict == DOES_NOT_MEET  # 205'000 hard against a 375'000 requirement


def test_the_same_price_and_income_still_computes_affordability_when_owner_occupied(approved):
    """The control. Only the let case is withheld; nothing else changed."""
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=PRIMARY,
        hard_available=205_000, pillar2_available=0, pillar3a_available=17_750,
        household_income=69_550,
    )
    assert result.affordability is not None
    assert result.affordability_verdict == DOES_NOT_MEET
    assert AFFORDABILITY in result.binds_on


def test_a_let_property_still_offers_the_deposit_lever(approved):
    """`levers` used to return nothing unless BOTH tests had run, which hid a computable dimension.

    A lever list is a list of dimensions the member could move. One of them being unavailable is not a
    reason to withhold the others, and the deposit is exactly the dimension a buy-to-let turns on.
    """
    result = assess(
        goal_id="g", price=1_500_000, target_date=MARCH, occupancy=LET,
        hard_available=205_000, pillar2_available=0, pillar3a_available=17_750,
        household_income=69_550,
    )
    dimensions = [entry["lever"] for entry in levers(result, household_income=69_550)]
    assert "deposit" in dimensions
    assert "price" not in dimensions and "household_income" not in dimensions


def test_the_shipped_record_carries_the_flag_the_service_reads(approved):
    """The record and the code have to agree, and they are maintained separately -- R-154's shape."""
    from eigentlich import content

    occupancies = content._load("property-funding")["occupancy"]
    assert occupancies["let_to_someone_else"]["affordability_is_determinable"] is False
    # the other two say nothing, and the service defaults them to determinable
    for key in ("owner_occupied_primary", "second_or_holiday_home"):
        assert "affordability_is_determinable" not in occupancies[key]
