"""Where each capacity input comes from, and what happens when it comes from nowhere.

**The provenance is the point.** Three of the five inputs the plan holds; two it does not. A figure derived
from a plan the member can correct is not the same kind of figure as one lifted out of a form they filled
in once, and `sources` says which is which on every value.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from eigentlich.services import profile_inputs as pi
from eigentlich.services import submissions as subs


def _file(**raw):
    return {"schema_version": "intake@1.1", "meta": {"source": "intake.html"}, "raw": raw}


def _plan_goal(session, member, **kwargs):
    """A goal, written the only way the build permits: inside a Decision.

    C-09 refuses a bare `session.add(Goal(...))` at flush time, which is the guard working — a goal that
    appeared with no Decision behind it would be a change to a member's plan that nothing recorded.
    """
    from eigentlich.models import Goal
    from eigentlich.services.plan import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Ein Ziel für den Test?",
                     choice="ja") as decision:
        goal = Goal(member_id=member.id, **kwargs)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.flush()
    return goal


def _plan_position(session, member, **kwargs):
    from eigentlich.models import Position
    from eigentlich.services.plan import mutate_plan

    with mutate_plan(session, member_id=member.id, question="Eine Position für den Test?",
                     choice="ja") as decision:
        kwargs.setdefault("stock_kind", "asset")  # a chf magnitude is a stock, and the CHECK says so
        position = Position(member_id=member.id, active=True, **kwargs)
        session.add(position)
        decision.linked_positions.append(position)
    session.flush()
    return position



def test_a_value_that_is_nowhere_stays_none_and_says_so(session, member):
    """Nothing here substitutes a plausible number for an absent one — `capacity` drops the component."""
    got = pi.collect(session, member_id=member.id)
    assert got.reserve_months is None
    assert got.sources["reserve_months"] == pi.ABSENT
    assert got.as_kwargs()["debt_service_share"] is None


def test_the_horizon_comes_from_the_nearest_dated_goal(session, member):
    """The goal that binds first is the one capacity is about."""
    today = date(2026, 9, 6)
    _plan_goal(session, member, name="spät", target_date=today + timedelta(days=3650))
    _plan_goal(session, member, name="früh", target_date=today + timedelta(days=730))
    got = pi.collect(session, member_id=member.id, today=today)
    assert got.horizon_years == pytest.approx(2.0, abs=0.02)
    assert got.sources["horizon_years"] == pi.FROM_PLAN


def test_the_free_share_is_read_from_the_positions(session, member):
    for label, magnitude in (("Bargeld und Kontoguthaben", 60_000), ("Säule 3a", 40_000)):
        _plan_position(session, member, label=label, role="stabilisation",
                       capital_type="financial", magnitude=magnitude, magnitude_unit="chf")
    got = pi.collect(session, member_id=member.id)
    assert got.free_share == pytest.approx(0.6)
    assert got.sources["free_share"] == pi.FROM_PLAN


def test_a_pension_label_the_patterns_miss_counts_as_free(session, member):
    """**The direction of the error, asserted rather than hoped for.**

    The plan has no vessel field, so this reads what the member called the position. An unrecognised
    pension label counts as FREE, which OVERSTATES capacity. Stated here so that when the vessel field
    lands, this test is the one that changes.
    """
    _plan_position(session, member, label="Guthaben bei der Stiftung Auffangeinrichtung",
                   role="protection", capital_type="financial", magnitude=100_000,
                   magnitude_unit="chf")
    assert pi.collect(session, member_id=member.id).free_share == 1.0


def test_reserve_months_come_from_the_submission_when_stated(session, member):
    subs.store(session, member_id=member.id, file=_file(liquidity_reserve_months=8))
    session.flush()
    got = pi.collect(session, member_id=member.id)
    assert got.reserve_months == 8
    assert got.sources["reserve_months"] == pi.FROM_SUBMISSION


def test_a_collection_is_not_an_emergency_reserve(session, member):
    """**The defect this split was written for.**

    Renzo holds CHF 2'000 in the bank and a CHF 45'000 collection of art, vehicles and other things, and
    spends CHF 24'000 a year. Counting the collection as money credited him with a 23.5-month cushion,
    which scored the reserve component at its maximum — 20 per cent of capacity, earned by a car.

    One month is the true answer and one month is what this asserts.
    """
    _plan_position(session, member, label="Bargeld und Kontoguthaben", role="stabilisation",
                   capital_type="financial", magnitude=2_000, magnitude_unit="chf")
    _plan_position(session, member, label="Sammlungen, Kunst und Fahrzeuge", role="stabilisation",
                   capital_type="financial", magnitude=45_000, magnitude_unit="chf")
    subs.store(session, member_id=member.id, file=_file(spend_now=24_000))
    session.flush()
    got = pi.collect(session, member_id=member.id)
    assert got.reserve_months == pytest.approx(1.0), "CHF 2'000 against CHF 2'000 a month"


def test_an_illiquid_holding_counts_in_the_total_and_not_in_the_free_part(session, member):
    """It is the member's wealth, so it belongs in the denominator; it cannot be invested, so it does not
    belong in the numerator."""
    _plan_position(session, member, label="Bargeld und Kontoguthaben", role="stabilisation",
                   capital_type="financial", magnitude=25_000, magnitude_unit="chf")
    _plan_position(session, member, label="Sammlungen, Kunst und Fahrzeuge", role="stabilisation",
                   capital_type="financial", magnitude=50_000, magnitude_unit="chf")
    _plan_position(session, member, label="Säule 3a", role="protection",
                   capital_type="financial", magnitude=25_000, magnitude_unit="chf")
    assert pi.collect(session, member_id=member.id).free_share == pytest.approx(0.25)


def test_an_unrecognised_real_asset_counts_as_liquid(session, member):
    """**The direction of the error, asserted rather than hoped for** — the same shape as the pension case.

    The list reads what the member called the position, so a real asset it does not recognise is treated
    as money. That OVERSTATES the reserve. Stated here so that when the vessel field lands, this test and
    `test_a_pension_label_the_patterns_miss_counts_as_free` are the two that change together.
    """
    _plan_position(session, member, label="Oldtimer in der Scheune", role="stabilisation",
                   capital_type="financial", magnitude=80_000, magnitude_unit="chf")
    subs.store(session, member_id=member.id, file=_file(spend_now=24_000))
    session.flush()
    assert pi.collect(session, member_id=member.id).reserve_months == pytest.approx(40.0)


def test_reserve_months_are_derived_from_spending_where_not_stated(session, member):
    """The plan holds no expenditure at all, so this is the one place the figure can come from."""
    _plan_position(session, member, label="Konto", role="stabilisation",
                   capital_type="financial", magnitude=24_000, magnitude_unit="chf")
    subs.store(session, member_id=member.id, file=_file(spend_now=48_000))
    session.flush()
    got = pi.collect(session, member_id=member.id)
    assert got.reserve_months == pytest.approx(6.0), "24'000 against 4'000 a month"


def test_debt_service_is_summed_across_repeatable_property_objects(session, member):
    """The intake carries one entry per object since 6 September, and a household with two mortgages
    services both."""
    subs.store(session, member_id=member.id, file=_file(
        income_gross=100_000,
        properties=[{"mortgage": 500_000, "rate": 2.0, "amortisation": 5_000},
                    {"mortgage": 200_000, "rate": 3.0, "amortisation": 0}],
    ))
    session.flush()
    got = pi.collect(session, member_id=member.id)
    # 10'000 + 5'000 + 6'000 = 21'000 against 100'000
    assert got.debt_service_share == pytest.approx(0.21)


def test_the_older_flat_shape_still_works(session, member):
    """A file from before the repeatable block, which the archive is full of."""
    subs.store(session, member_id=member.id, file=_file(
        income_gross=100_000, mortgage=400_000, mortgage_rate=1.5, amortisation=4_000))
    session.flush()
    assert pi.collect(session, member_id=member.id).debt_service_share == pytest.approx(0.10)


def test_the_newest_submission_wins(session, member):
    """A later form is a later statement, and reconciling two of them is a judgement nothing here is
    entitled to make.

    The two are given distinct `received_at` values on purpose. `received_at` is stored to the second, so
    two files arriving in the same second have no fact that makes one newer -- writing this test without
    distinct times is what found that `for_member` was ordering ties arbitrarily.
    """
    from datetime import datetime, timezone

    first = subs.store(session, member_id=member.id, file=_file(liquidity_reserve_months=3))
    first.received_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    second = subs.store(session, member_id=member.id, file=_file(liquidity_reserve_months=9))
    second.received_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    session.flush()
    assert pi.collect(session, member_id=member.id).reserve_months == 9


# ============================================================ the stated answers


def test_a_percentage_is_read_whichever_way_it_was_written(session, member):
    """The form writes «30 %»; a bare 30 means the same thing and 0.30 does too."""
    from eigentlich.models import Submission

    for written, expected in (("30 %", 0.30), (30, 0.30), (0.30, 0.30)):
        session.query(Submission).delete()
        session.flush()
        subs.store(session, member_id=member.id, file=_file(max_loss_pct=written))
        session.flush()
        assert pi.stated_risk(session, member_id=member.id)["stated_loss"] == pytest.approx(expected)


def test_the_two_sustainability_answers_come_back_separately(session, member):
    """The gap that left `esg_min` at zero on every mandate ever derived in this build."""
    subs.store(session, member_id=member.id, file=_file(
        esg_exclusions="Waffen, Tabak", esg_minimum="mehrheitlich"))
    session.flush()
    stated = pi.stated_risk(session, member_id=member.id)
    assert stated["esg_exclusions"] == ["Waffen", "Tabak"]
    assert stated["esg_level"] == "mehrheitlich"


def test_no_submission_at_all_is_a_row_of_nones_rather_than_an_error(session, member):
    stated = pi.stated_risk(session, member_id=member.id)
    assert stated["stated_loss"] is None and stated["esg_exclusions"] == []


# ============================================================ the whole chain


def test_the_inputs_are_exactly_what_capacity_takes(session, member, monkeypatch):
    """A drift between these two signatures would be found at runtime by a member and not here."""
    import inspect

    from eigentlich.services import risk_profile as rp

    accepted = set(inspect.signature(rp.capacity).parameters)
    assert set(pi.Inputs().as_kwargs()) == accepted
