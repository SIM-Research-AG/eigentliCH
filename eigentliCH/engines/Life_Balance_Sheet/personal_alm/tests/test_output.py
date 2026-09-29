"""Consumer output layer (spec §14). Pure formatting/computation over engine
values — no modelling, so these are fast unit tests."""

import pytest

from personal_alm.model.controls import Control
from personal_alm.model.dynamics import income
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.sim.montecarlo import constant_policy
from personal_alm.ui.output import (
    WorkOptional,
    fi_drawable_requirement,
    plain_language_action,
    render_period,
    saving_rate,
    tilt_language,
    work_optional_age,
)

P = Params()


def _nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


def _action(**kw) -> Control:
    base = dict(tau_Y=0.5, tau_E=0.0, tau_N=0.10, tau_H=0.20,
                C=84_000, m_E=0, m_N=0, p_A=0, theta=0.21)
    base.update(kw)
    return Control(**base)


def test_tilt_language_bands():
    assert "conservative" in tilt_language(0.1)
    assert "moderate" in tilt_language(0.4)
    assert "aggressive" in tilt_language(0.8)


def test_saving_rate_is_output_of_income_and_consumption():
    # The claim is the identity s = 1 − C/Y, so C is set from Y rather than from a remembered income level.
    # Hard-coding `C=100_000` against an assumed 200k income broke this on 3 August 2026 when the earning
    # bounds were recalibrated — the identity held throughout; only the assumed level was stale.
    s = State.individual(W_L=0, W_R=0, D=0, E=1.0, N=1.0, H=1.0)
    y = income(s, _action(tau_Y=1.0, C=0.0), P)
    assert saving_rate(s, _action(tau_Y=1.0, C=y / 2.0), P) == pytest.approx(0.5, abs=1e-6)
    assert saving_rate(s, _action(tau_Y=1.0, C=y / 4.0), P) == pytest.approx(0.75, abs=1e-6)


def test_fi_drawable_requirement_matches_eq_7_8():
    st = _nicolas_45()
    # (G − y_R·W_inv)/swr, stated against `P.G` rather than a literal. **The literal was 120 000 and went stale
    # within hours**, when the CIO lowered G to 90 000 on 3 August 2026 — the same failure mode this suite keeps
    # catching, committed while fixing an instance of it.
    #
    # `W_inv`, not `W_R`, since the step-3 split: the 5m property is one fifth own use, so W_inv = 4.0m and the
    # yield is 80k rather than 100k. The requirement is a small difference of two large numbers, so it is far
    # more sensitive than it looks: 571k at G=120k crediting all 5m, 1.143m at G=120k crediting 4m, and
    # 285 714 at G=90k and swr=3.5%. Three very different answers from two modest input changes.
    #
    # **333 333 since 25 August 2026**, because M80 decision 5 moved `swr` 0.035 -> 0.030 to make the book's
    # own "roughly thirty to one" true again. The requirement rises by a sixth for every household in the
    # repo, which is the point of the decision rather than a side effect of it: the earlier rate made
    # independence look nearer than the book's arithmetic says it is.
    assert fi_drawable_requirement(st, P) == pytest.approx((P.G - P.y_R * st.wealth.W_inv) / P.swr, rel=1e-6)
    # Pin the arithmetic too, so the line above cannot pass by echoing a broken implementation.
    assert fi_drawable_requirement(st, P) == pytest.approx(333_333.33, abs=0.01)


def test_plain_language_action_reads_like_advice():
    txt = plain_language_action(_nicolas_45(), _action(), P)
    assert txt.startswith("This period:")
    assert "work 50%" in txt
    assert "networking" in txt
    assert "equity tilt" in txt


def test_work_optional_scan_finds_a_later_date_for_nicolas():
    """The scan reports the first age at which the goal is 90%-confident.

    **The book's 'plan against ~52-53' no longer holds, and the test says so rather than asserting it.** That
    result needed `G = 120 000` and a drawable requirement of 571 429 against 600 000 of liquid wealth — a
    margin of 28 571, which is why it was sensitive enough to be interesting. Two CIO decisions on 3 August 2026
    moved it: the step-3 split cut the credited rent from 100 000 to 80 000 (raising the requirement), and `G`
    fell 120 000 -> 90 000 (cutting it much harder). Net effect, the requirement is **285 714** against the same
    600 000, so he was work-optional at the first step of the scan.

    **That reversed on 25 August 2026 and the reversal is the decision working.** M80 decision 5 moved `swr`
    0.035 -> 0.030, and at 3 % the same household needs 333 333 against the same 600 000 of drawable wealth --
    still covered -- but `gamma` moved 2.0 -> 3.0 in the same decision, and a more risk-averse planner consumes
    and invests differently, so the scan now first reports optional at **61**. What is pinned below is
    therefore the property rather than the age: the scan must report rather than guess, and its two figures
    must be mutually consistent.

    Asserting `> 50.0` here would now be asserting a stale calibration rather than a property of the model. What
    is still worth pinning is that the scan *reports* rather than guesses, and that its two figures are mutually
    consistent — a verdict of "already optional" must come with drawable >= required, which is the check that
    would have caught the q_inv = 0.85 inconsistency (a verdict of optional while displaying 600 000 against
    1 142 857).
    """
    policy = constant_policy(_action(C=90_000, p_A=60_000, m_E=5_000, m_N=10_000))
    wo = work_optional_age(_nicolas_45(), policy, P, from_age=45.0,
                           confidence=0.90, M=300, seed=0, step=1.0)
    assert isinstance(wo, WorkOptional)
    # The age itself is a calibration and moves whenever `swr` or `gamma` does; what must hold is that the
    # verdict and the figures agree. Pinning 46.0 was pinning the calibration of 3 August.
    assert wo.age is not None and 45.0 <= wo.age <= 65.0, "the scan must report an age inside its own range"
    # The verdict and the displayed figures must agree — that is the invariant, not the age.
    assert wo.drawable_now >= wo.drawable_required
    # The illiquidity gap is large and positive (residence excluded from drawable).
    assert wo.illiquidity_gap > 2_000_000
    assert wo.drawable_required > 0


def test_render_period_smoke():
    from personal_alm.optim.problem import Costates, ExchangeRate
    from personal_alm.optim.mpc import PeriodOutput

    po = PeriodOutput(
        period=0, age=45.0, state=_nicolas_45(), action=_action(),
        p_fi_oos=0.65, costates=Costates(1e-5, 2.5, 2.4, 10.8),
        exchange_rate=ExchangeRate("financial independence", 0.4, 2.0),
        solve_ok=True, warning="P(FI) 65% below target 90% at age 45.00",
        lever="an hour of overtime is worth ~5.0× the alternative toward FI",
    )
    txt = render_period(po, P, confidence=0.90)
    assert "Financial independence" in txt
    assert "65%" in txt
    assert "BELOW TARGET" in txt
    assert "Drawable" in txt
    assert "overtime" in txt
    assert "⚠" in txt
