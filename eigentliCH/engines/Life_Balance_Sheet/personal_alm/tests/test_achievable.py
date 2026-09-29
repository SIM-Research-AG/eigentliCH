"""The goal-reduction search, driven by a STUB rather than by IPOPT.

One real probe is a two-phase multistart solve plus a 400-scenario evaluation, measured at over an hour on a
26-year horizon. A test that ran four of those would not be run. Substituting a runner whose answer is known
tests what is actually worth testing here — the seeding, the bisection, the probe budget, the deadline cap and
the refusal to present a bracket as an answer — in milliseconds.

What this deliberately does NOT test is whether the solver is right. That is `test_optim.py`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from ..cases import Case
from ..goals.spec import GoalSpec
from ..model.state import State
from ..optim.achievable import amount_deficit, largest_fundable

#: The largest amount the stub household can fund at the stated deadline.
TRUE_MAX = 137_000.0


@dataclass
class _FakeResult:
    p_goal: float
    shortfall: float | None = None


def _make_runner(calls: list, *, true_max: float = TRUE_MAX, cap_funds_full: bool = False,
                 stated_horizon: float = 10.0):
    def run(case, *, base_params=None, **kw):
        amount = float(case.goal.params["G_ret"])
        horizon = float(case.goal.horizon_years)
        calls.append((amount, horizon))
        # "At the cap" means any deadline later than the one the household stated. Comparing against a literal
        # was the first version of this stub and it silently never fired, because the cap for a 55-year-old is
        # ten years and the literal was 10.5 — the test then asserted against a bug in its own fixture.
        at_cap = horizon > stated_horizon + 1e-9
        if amount <= true_max or (at_cap and cap_funds_full):
            return _FakeResult(p_goal=0.97)
        # A funding-RATIO deficit, which is what the retirement slack really produces.
        return _FakeResult(p_goal=0.0, shortfall=1.0 - true_max / amount)
    return run


def _case(age: float = 55.0, amount: float = 200_000.0, horizon: float = 10.0) -> Case:
    x0 = State.individual(W_L=170_000.0, W_R=800_000.0, D=200_000.0, E=0.5, N=0.5, H=0.7, age=age,
                          W_res=800_000.0, W_hol=0.0, W_P=570_000.0, W_3a=200_000.0)
    goal = GoalSpec(kind="retirement", horizon_years=horizon, epsilon=0.05,
                    params={"G_ret": amount, "years_in_retirement": 25.0, "r_disc": 0.02})
    return Case(name="stub", persona="stub", x0=x0, goal=goal, confidence=0.95,
                param_overrides={}, calibrated=False)


@pytest.mark.parametrize("kind, amount, cvar, expected", [
    # The FI slack is money: `y_R·W_inv + swr·Ω_draw − G`, and G enters with coefficient −1.
    ("fi", 90_000.0, 13_267.0, 13_267.0),
    # The retirement slack is `assets/(G_ret·af) − 1`, DIMENSIONLESS. Before this conversion existed, a 31.5%
    # funding gap reached a client-facing warning as "CHF 0 a year".
    ("retirement", 200_000.0, 0.315, 63_000.0),
    ("home", 1_200_000.0, 0.08, 96_000.0),
    ("company", 250_000.0, 0.20, 50_000.0),
])
def test_a_cvar_shortfall_is_converted_into_the_goals_own_units(kind, amount, cvar, expected):
    assert amount_deficit(kind, amount, cvar) == pytest.approx(expected)


def test_a_negative_shortfall_is_not_a_deficit():
    assert amount_deficit("retirement", 200_000.0, -0.02) == 0.0


def test_it_finds_the_largest_fundable_amount():
    calls: list = []
    r = largest_fundable(_case(), probes=6, run=_make_runner(calls), try_deadline=False)
    assert r.stated_is_fundable is False
    assert r.largest_amount == pytest.approx(TRUE_MAX)
    assert r.converged is True
    assert r.reduction == pytest.approx(200_000.0 - TRUE_MAX)


def test_the_first_search_probe_is_seeded_from_the_shortfall_not_from_the_midpoint():
    """The seed is what keeps the probe budget small enough to afford at all.

    For a retirement goal the funding ratio is inversely proportional to the amount, so `stated - deficit` is
    exact whenever the plan is unchanged — the first probe lands on the answer rather than at 100 000.
    """
    calls: list = []
    largest_fundable(_case(), probes=1, run=_make_runner(calls), try_deadline=False)
    assert calls[0][0] == pytest.approx(200_000.0)      # the stated goal, to see whether it holds
    assert calls[1][0] == pytest.approx(TRUE_MAX)       # seeded, not bisected


def test_the_probe_budget_is_respected():
    for budget in (1, 2, 4, 8):
        calls: list = []
        largest_fundable(_case(), probes=budget, run=_make_runner(calls), try_deadline=False)
        assert len(calls) <= budget + 1, f"budget {budget} overspent"


def test_a_fundable_goal_is_not_reduced():
    calls: list = []
    r = largest_fundable(_case(amount=100_000.0), probes=4, run=_make_runner(calls), try_deadline=False)
    assert r.stated_is_fundable is True
    assert r.largest_amount == pytest.approx(100_000.0)
    assert r.reduction == pytest.approx(0.0)
    assert len(calls) == 1, "a household whose goal holds should cost exactly one probe"


def test_when_nothing_probed_holds_it_reports_a_bracket_and_not_an_answer():
    calls: list = []
    r = largest_fundable(_case(), probes=3, run=_make_runner(calls, true_max=1.0), try_deadline=False)
    assert r.largest_amount is None
    assert r.converged is False
    assert r.bracket_high is not None and r.bracket_low is None
    assert "bracket, not an answer" in r.note


def test_the_deadline_lever_never_goes_past_the_reference_age():
    """A plan may say 'not at 60, but at 65'. It may never say 'work past 65'."""
    calls: list = []
    r = largest_fundable(_case(age=55.0, horizon=5.0), probes=4,
                         run=_make_runner(calls, cap_funds_full=True, stated_horizon=5.0),
                         try_deadline=True)
    assert r.deadline_cap_years == pytest.approx(10.0)          # 65 less the subject's 55
    assert max(h for _, h in calls) <= r.deadline_cap_years + 1e-9
    assert r.full_amount_deadline_years == pytest.approx(10.0)


def test_a_goal_already_dated_at_the_reference_age_has_no_deadline_room():
    """All three real submissions of 6 August 2026 are this shape, which is why the lever is quiet."""
    calls: list = []
    largest_fundable(_case(age=55.0, horizon=10.0), probes=4,
                     run=_make_runner(calls, cap_funds_full=True), try_deadline=True)
    assert {h for _, h in calls} == {10.0}, "no probe should have moved the deadline"
