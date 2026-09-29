"""Data-structure invariants (spec §16.4 step 1)."""

import numpy as np
import pytest

from personal_alm.model.controls import Control
from personal_alm.model.expertise import Expertise
from personal_alm.model.state import State


def _control(**kw) -> Control:
    base = dict(tau_Y=0.4, tau_E=0.2, tau_N=0.1, tau_H=0.2,
                C=60_000, m_E=2_000, m_N=1_000, p_A=10_000, theta=0.5)
    base.update(kw)
    return Control(**base)


def test_net_worth_and_drawable():
    s = State.individual(W_L=600_000, W_R=5_000_000, D=1_800_000, E=0.9, N=0.9, H=0.7, W_res=1_000_000)
    assert s.net_worth == pytest.approx(3_800_000)
    # h_res = 0: the residence contributes nothing to drawable wealth (spec §7.4).
    assert s.wealth.drawable(h_res=0.0) == pytest.approx(600_000)
    # No haircut anywhere counts full equity — which now takes BOTH haircuts at 1.0, not just `h_res`.
    # There are two haircuts since the step-3 split, and debt is apportioned pro rata across them, so
    # `h_res=1.0` alone counts only the residence's share of the equity.
    assert s.wealth.drawable(h_res=1.0, q_inv=1.0) == pytest.approx(3_800_000)

    # `h_res=1.0` alone: the residence is a fifth of the stock, so it carries a fifth of the debt.
    # 600_000 + (1_000_000 − 1_800_000·0.2) = 1_240_000. It must not go negative — attaching *all* the
    # debt to the residence was the first attempt and gave −200_000, which is what this line guards.
    assert s.wealth.drawable(h_res=1.0) == pytest.approx(1_240_000)


def test_expertise_scalar_aggregate():
    e = Expertise.scalar(0.9)
    assert e.dim == 1
    assert e.aggregate() == pytest.approx(0.9)


def test_expertise_vector_aggregate_is_weighted_sum():
    # SEAM 1: vector E works today even though v1 uses d == 1.
    e = Expertise(components=np.array([0.6, 0.3]))
    assert e.dim == 2
    assert e.aggregate() == pytest.approx(0.9)


def test_time_budget_feasibility():
    assert _control().time_budget_ok()
    assert not _control(tau_Y=0.6, tau_E=0.3, tau_N=0.2, tau_H=0.2).time_budget_ok()
    assert not _control(tau_Y=-0.1).time_budget_ok()


def test_leisure_is_the_slack():
    u = _control(tau_Y=0.4, tau_E=0.2, tau_N=0.1, tau_H=0.2)
    assert u.tau_leisure == pytest.approx(0.1)


def test_theta_and_money_bounds():
    assert _control().is_admissible()
    assert not _control(theta=1.5).theta_ok()
    assert not _control(C=-1.0).money_nonneg()


def test_single_person_sugar_rejects_household():
    s = State.individual(W_L=1, W_R=1, D=0, E=0.5, N=0.5, H=0.9)
    s.persons.append(s.persons[0].copy())
    with pytest.raises(ValueError):
        _ = s.person
