"""A property goal's mandate target is the deposit, and getting this wrong cost five members a verdict.

Feeding the derivation the full purchase price asks the portfolio to buy the house in cash. Over the ten
loaded members that produced required returns of 13 % to 37 % a year and five verdicts of «not
reachable» — arithmetically correct, about a goal nobody has. Against the deposit, three of the five are
reachable and the two that are not fail for reasons that are true.
"""
from __future__ import annotations

import pytest

from eigentlich.services import property as prop

PRICE = 1_100_000


def test_the_target_is_the_deposit_and_never_the_price():
    got = prop.mandate_target(PRICE, occupancy="owner_occupied_primary")
    assert got.target == pytest.approx(PRICE * 0.2)
    assert got.target < got.price


def test_the_rest_is_a_mortgage_and_is_not_accumulated():
    got = prop.mandate_target(PRICE, occupancy="owner_occupied_primary")
    assert got.mortgage == pytest.approx(PRICE - got.target)
    assert got.target + got.mortgage == pytest.approx(got.price)


@pytest.mark.parametrize("occupancy,share", [
    ("owner_occupied_primary", 0.20),
    ("let_to_someone_else", 0.25),
    ("second_or_holiday_home", 0.30),
])
def test_each_occupancy_uses_its_own_published_requirement(occupancy, share):
    got = prop.mandate_target(PRICE, occupancy=occupancy)
    assert got.equity_min == pytest.approx(share)
    assert got.target == pytest.approx(PRICE * share)
    assert not got.assumed


def test_an_unanswered_occupancy_uses_the_strictest_and_says_so():
    """**The direction of the error decides which to pick.** Targeting too little tells a household they
    will make it when they will not; targeting too much tells them to keep saving. Only one of those is
    safe to be wrong about."""
    got = prop.mandate_target(PRICE)
    strictest = max(
        float(rule["equity_min"])
        for rule in prop._record()["occupancy"].values()
        if isinstance(rule, dict)
    )
    assert got.equity_min == pytest.approx(strictest)
    assert got.assumed
    assert "nicht erfasst" in got.why


def test_an_unknown_occupancy_is_treated_as_unanswered_rather_than_accepted():
    got = prop.mandate_target(PRICE, occupancy="im Baumhaus")
    assert got.assumed


def test_the_strictest_is_never_below_any_published_requirement():
    """A guard on the record: adding an occupancy with a higher requirement must move the default."""
    assumed = prop.mandate_target(PRICE)
    for key, rule in prop._record()["occupancy"].items():
        if not isinstance(rule, dict):
            continue
        assert assumed.target >= prop.mandate_target(PRICE, occupancy=key).target - 1, key


def test_the_reason_travels_with_the_number():
    """A target a reader cannot account for is a target they cannot argue with."""
    for got in (prop.mandate_target(PRICE), prop.mandate_target(PRICE, occupancy="let_to_someone_else")):
        assert got.why.strip()
        assert got.occupancy in prop._record()["occupancy"]


# ============================================================ what it changes


def test_the_five_property_goals_against_both_readings():
    """The five real prices, and what each asks of a portfolio under the two readings.

    Not a test of the members — a test that the difference is the size the reports claim it is.
    """
    for price in (1_100_000, 1_500_000, 2_000_000):
        deposit = prop.mandate_target(price, occupancy="owner_occupied_primary")
        # The deposit is a fifth of the price, so the capital to accumulate falls by four fifths.
        assert deposit.target == pytest.approx(price * 0.2)
        assert price - deposit.target == pytest.approx(price * 0.8)


def test_both_tests_still_exist_and_are_independent():
    """The deposit is a capital question and the Tragbarkeit an income one. Fixing the first must not
    quietly answer the second: every one of the ten still fails affordability."""
    price, income = 1_100_000, 90_000
    deposit = prop.mandate_target(price, occupancy="owner_occupied_primary")
    carrying = prop.affordability(price, income=income)
    assert deposit.target < price, "the capital test got easier"
    assert getattr(carrying, "ratio", 2) > 1, "and the income test did not move"
