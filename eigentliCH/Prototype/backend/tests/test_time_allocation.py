"""The time frontier: options with consequences, and never a choice.

**The C-01 property is the one that matters here.** «Move five hours from work to learning» is a
personalised recommendation, so this module must never make it. It returns everything it evaluated and
selects nothing, which is the same shape `models/action.py` enforces at the database.
"""
from __future__ import annotations

import pytest

from eigentlich.services import human_capital as hc
from eigentlich.services import time_allocation as ta

#: A person the engine can compute: a stated qualification, a network, health, an age and a working week.
LEVIN = {
    "qualification_highest": "Höhere Berufsausbildung", "network_people": 18,
    "health": "0.85", "age": 25, "hours_per_week": 41, "rest_hours": "10–20",
    "hours_learning": 6, "hours_network": 2,
}


def _frontier_or_skip(answers=None, **kwargs):
    try:
        return ta.frontier(answers or LEVIN, **kwargs)
    except ta.EngineUnavailable:
        pytest.skip("the Life Balance Sheet engine is not reachable from this build")


# ============================================================ the C-01 shape


def test_it_returns_options_and_selects_none():
    """No field on the result says which one. That is the property, not a style choice."""
    got = _frontier_or_skip()
    assert len(got.options) >= 2
    for name in ("best", "recommended", "chosen", "suggested", "preferred"):
        assert not hasattr(got, name), name


def test_doing_nothing_is_one_of_the_options():
    """A list that omits the current allocation invites the reading that something must change."""
    got = _frontier_or_skip()
    keys = [row["key"] for row in got.as_prepared_options()]
    assert keys[0] == "current"


def test_more_work_is_offered_as_well_as_less():
    """Leaving it out would make the frontier argue for less work by omission."""
    got = _frontier_or_skip()
    assert "to_work" in {option.key for option in got.options}


def test_every_prepared_option_carries_a_consequence():
    """`models/action.py`: an option without a consequence is a label."""
    rows = _frontier_or_skip().as_prepared_options()
    assert len(rows) >= 2, "the CHECK requires at least two"
    for row in rows:
        assert row["consequence"].strip()
        assert row["label"].strip()


def test_the_prepared_options_satisfy_the_databases_own_validator(session, member):
    """Not asserted by reading the constraint — asserted by writing a row through it."""
    from eigentlich.models import ActionItem

    rows = _frontier_or_skip().as_prepared_options()
    item = ActionItem(member_id=member.id, trigger_kind="time_allocation",
                      prepared_options=rows)
    assert len(item.prepared_options) == len(rows)


# ============================================================ what it computes


def test_the_hours_always_add_up_to_the_productive_week_or_less():
    got = _frontier_or_skip()
    for option in [got.current, *got.options]:
        assert sum(option.hours.values()) <= got.productive_week_hours + 1e-6, option.key


def test_moving_hours_out_of_work_costs_income_and_the_consequence_says_so():
    got = _frontier_or_skip()
    learning = next(o for o in got.options if o.key == "to_learning")
    assert learning.income < got.current.income
    assert learning.income_delta < 0
    assert "weniger Erwerbsarbeit" in learning.consequence["de"]


def test_learning_hours_slow_the_decay_of_expertise():
    """The engine's `learning_effect`, saturating at a 20 h/week knee. Read, not reimplemented."""
    got = _frontier_or_skip()
    learning = next(o for o in got.options if o.key == "to_learning")
    assert learning.dE > got.current.dE


def test_rest_hours_slow_the_decay_of_health():
    got = _frontier_or_skip()
    rest = next(o for o in got.options if o.key == "to_rest")
    assert rest.dH > got.current.dH


def test_the_consequence_compares_against_today_rather_than_stating_a_direction():
    """**Every capital in this model decays.** An absolute reading says «expertise falls» under every
    option and hides the only thing a reader is comparing."""
    got = _frontier_or_skip()
    learning = next(o for o in got.options if o.key == "to_learning")
    assert "fällt weniger" in learning.consequence["de"]
    assert "declines less" in learning.consequence["en"]


def test_the_current_option_reports_no_movement_against_itself():
    got = _frontier_or_skip()
    assert "kein Kapital anders" in got.current.consequence["de"]
    assert got.current.income_delta == 0


# ============================================================ what it refuses


def test_a_missing_capital_refuses_rather_than_drawing_a_frontier_from_a_guess():
    """A frontier from a guessed starting point compares options against a person who does not exist."""
    with pytest.raises(ValueError) as raised:
        ta.frontier({"network_people": 10, "health": "1", "age": 30, "hours_per_week": 40})
    assert "E" in str(raised.value)


def test_a_missing_working_week_refuses():
    with pytest.raises(ValueError) as raised:
        ta.frontier({"qualification_highest": "Fachhochschule FH", "network_people": 10,
                     "health": "1", "age": 30})
    assert "hours_per_week" in str(raised.value)


def test_withheld_health_still_draws_a_frontier_and_names_the_overstatement():
    """**The K3 condition.** A consumer must survive H's removal, and say which way the error points."""
    got = _frontier_or_skip(k3_permitted=False)
    assert len(got.options) >= 2
    assert any("overstates income" in c for c in got.caveats)


def test_unstated_learning_hours_are_read_as_zero_and_the_caveat_says_so():
    answers = {k: v for k, v in LEVIN.items() if k not in ("hours_learning", "hours_network")}
    got = _frontier_or_skip(answers)
    assert any("read as zero" in c for c in got.caveats)


# ============================================================ the time budget behind it


def test_the_two_new_questions_now_reach_the_time_budget():
    """They were added to the instrument on 6 September 2026 precisely so these stop being holes."""
    budget = hc.time_budget(LEVIN)
    assert budget.tau_E == pytest.approx(0.06)
    assert budget.tau_N == pytest.approx(0.02)
    assert budget.sources["tau_E"] == hc.FROM_SUBMISSION


def test_the_leisure_residual_exists_once_all_four_are_answered():
    """It could not be computed at all until the two questions were added."""
    budget = hc.time_budget(LEVIN)
    assert budget.leisure is not None
    assert budget.leisure == pytest.approx(1 - (0.41 + 0.06 + 0.02 + 0.15))


def test_an_unanswered_share_still_leaves_the_residual_uncomputable():
    answers = {k: v for k, v in LEVIN.items() if k != "hours_network"}
    budget = hc.time_budget(answers)
    assert budget.tau_N is None
    assert budget.leisure is None, "a residual computed over holes is a lie"


def test_hours_that_exceed_the_productive_week_are_flagged():
    budget = hc.time_budget({**LEVIN, "hours_per_week": 70, "hours_learning": 30,
                             "hours_network": 20, "rest_hours": "über 30"})
    assert any("more than the" in c for c in budget.caveats)
