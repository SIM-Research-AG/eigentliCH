"""Deterministic-skeleton validation (spec §16.4 step 1).

With σ = 0 we check the identities balance and the qualitative shapes hold:
wealth accumulates (no ceiling); expertise, network and health saturate; and the
health feedback punishes overwork.
"""

import numpy as np
import pytest

from dataclasses import replace

from personal_alm.model.controls import Control
from personal_alm.model.dynamics import (
    _SMOOTH_MIN_EPS,
    _smooth_min,
    ahv_pension,
    delta_H,
    drift,
    income,
    income_tax,
    net_cash_to_liquid,
    network_ceiling,
    phi,
)
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.sim.montecarlo import constant_policy, simulate, step


def _state(**kw) -> State:
    base = dict(W_L=600_000, W_R=5_000_000, D=1_800_000, E=0.9, N=0.9, H=0.7, W_res=1_000_000)
    base.update(kw)
    return State.individual(**base)


def _control(**kw) -> Control:
    base = dict(tau_Y=0.4, tau_E=0.2, tau_N=0.1, tau_H=0.2,
                C=60_000, m_E=2_000, m_N=1_000, p_A=10_000, theta=0.5)
    base.update(kw)
    return Control(**base)


# --- H1: the exogenous partner ----------------------------------------------------
#
# Parity proves the two transcriptions AGREE; it cannot prove either is right. These assert levels and
# directions, which is the thing a parity test structurally cannot see.


def test_ahv_couple_cap_binds_at_150_percent():
    """Two married pensions are capped at 150% of the maximum single, not summed.

    Summing two full entitlements would give 200% and overstate a couple's first pillar by a third. `params.py`
    had recorded this gap for days: "a couple is capped at 150% of the maximum, which this single-person model
    does not express."
    """
    single = Params()
    # Above `ahv_income_for_max` (90 720), not at 90 000: the entitlement ramps to the maximum across the income
    # scale, so 90 000 reaches 30 120 rather than the full 30 240 and would make this test about the ramp instead.
    INCOME = 120_000.0
    couple = replace(single, has_partner=True, partner_income=INCOME)
    at = 70.0  # well past the gate, so both entitlements are fully switched on

    own = ahv_pension(INCOME, at, single)
    both = ahv_pension(INCOME, at, couple)
    cap = single.ahv_couple_cap_multiple * single.ahv_full_single

    assert own == pytest.approx(single.ahv_full_single, rel=1e-3), "a full record should reach the maximum"
    assert both == pytest.approx(cap, abs=2.0 * _SMOOTH_MIN_EPS)
    assert both < 2.0 * own, "two pensions were summed; the couple cap is not being applied"
    assert both > own, "a couple must still receive more than a single person"


def test_ahv_couple_cap_does_not_bind_before_the_second_retires():
    """A couple where only one has reached 65 must not be capped against a two-pension ceiling.

    There is no explicit "both retired" gate, by design: each entitlement is age-gated, so the sum cannot reach
    the cap until the second partner draws. This asserts that reasoning rather than trusting it.
    """
    p = replace(Params(), has_partner=True, partner_income=90_000.0, partner_age_offset=-10.0)
    couple = ahv_pension(90_000.0, 66.0, p)
    single = ahv_pension(90_000.0, 66.0, Params())
    # Within a franc, NOT exact. `_smooth_min`'s error decays as eps^2/(4|gap|), so with the cap 15 240 away it is
    # still ~16 rappen low. Pinning this at zero would be pinning a claim that is not true; pinning it under a
    # franc is what the smoothing actually promises.
    assert couple == pytest.approx(single, abs=1.0)
    assert couple <= single, "smoothing must not lift a pension above the hard-min value"


def test_smooth_min_is_min_to_within_its_width():
    """`_smooth_min` replaces `min` for the couple cap, so it must BE min to within its width.

    Smooth rather than hard because this ceiling **binds by design** for any couple with two decent records, and
    `symbolic.py` records that a clamp binding often "wants a softmin instead". The earning-power clamp was left
    hard only because measurement showed it never activates.
    """
    eps = _SMOOTH_MIN_EPS
    assert _smooth_min(10_000.0, 90_000.0) == pytest.approx(10_000.0, abs=1.0)
    assert _smooth_min(90_000.0, 10_000.0) == pytest.approx(10_000.0, abs=1.0)
    # At the crossing it sits half a width below both, which is the price of differentiability.
    assert _smooth_min(50_000.0, 50_000.0) == pytest.approx(50_000.0 - 0.5 * eps, abs=1e-6)
    for a, b in ((1.0, 2.0), (0.0, 100_000.0), (45_360.0, 45_400.0), (-5.0, 5.0)):
        assert _smooth_min(a, b) == pytest.approx(_smooth_min(b, a), abs=1e-9)
        # Never ABOVE the true minimum: a cap that could be exceeded would not be a cap.
        assert _smooth_min(a, b) <= min(a, b) + 1e-9


def test_joint_taxation_reduces_the_bill_and_is_inert_by_default():
    """`tax_split_factor` expresses Vollsplitting, and is algebraically inert at 1.0."""
    single = Params()
    couple = replace(single, tax_split_factor=2.0)
    for t in (0.0, 40_000.0, 120_000.0, 300_000.0, 1_000_000.0):
        assert income_tax(t, single) == income_tax(t, replace(single, tax_split_factor=1.0))
    assert income_tax(0.0, couple) == pytest.approx(0.0)
    for t in (60_000.0, 200_000.0, 500_000.0):
        assert income_tax(t, couple) < income_tax(t, single), "splitting must lower a progressive bill"
    for t in (0.0, 50_000.0, 400_000.0):
        assert 0.0 <= income_tax(t, couple) <= income_tax(t, single) + 1e-9


def test_partner_income_reaches_cash_and_the_tax_base():
    """A partner's income must appear in BOTH the cash identity and the taxable base.

    Adding it to cash alone creates money the tax system never sees; adding it to the base alone taxes income that
    never arrived. The pillar-2 error this model already made — a contribution in `dW_P` and nowhere in the cash
    flow — was exactly this shape.
    """
    s = _state()
    u = _control()
    single = Params()
    couple = replace(single, has_partner=True, partner_income=100_000.0)

    gain = net_cash_to_liquid(s, u, couple) - net_cash_to_liquid(s, u, single)
    # Strictly positive, strictly less than gross: the marginal tax on it is real.
    assert 0.0 < gain < 100_000.0, f"partner income contributed {gain:.0f} of 100 000 gross"
    # With splitting the same gross keeps more, because the tariff is progressive.
    assert net_cash_to_liquid(s, u, replace(couple, tax_split_factor=2.0)) > net_cash_to_liquid(s, u, couple)


# --- Identities -------------------------------------------------------------------

def test_income_from_earning_power():
    """`w0 · E^a · N^b` was retired for `earning_power(E, N, age)` on 3 August 2026 (step 2).

    This asserted continuity with the retired `w0`: income at `E = N = H = 1` and full working time equalled
    200 000 exactly. **That anchor is gone, by decision on 3 August 2026, and its loss was not a regression.**
    It was a property of *additive* interpolation against a *250 000* ceiling — `50 000 + 200 000·0.75` — and
    both of those were replaced: the shape became geometric (because additive put an unrealistic 143 000 on an
    early career, a floor added to a scaled term being a base salary rather than a floor), and the ceiling rose
    to 500 000. Income at unit capitals is therefore `50 000 · 10^0.75 = 281 170.66`, and the CIO accepted that
    level rather than retuning `at_unit` to 0.602 to recover the old figure.

    The level is pinned literally because the level is a calibration under review; the shape is asserted
    separately so a future recalibration breaks one assertion and not three.
    """
    p = Params()
    s = State.individual(W_L=0, W_R=0, D=0, E=1.0, N=1.0, H=1.0, age=45.0)
    u = _control(tau_Y=1.0)

    # 50_000 · (500_000/50_000) ** 0.75 — geometric interpolation at unit capitals, mid-career.
    assert income(s, u, p) == pytest.approx(281_170.66, abs=0.01)

    # Linear in work time, whatever the level: halving τ_Y halves income.
    assert income(s, _control(tau_Y=0.5), p) == pytest.approx(income(s, u, p) / 2.0)


def test_earning_power_declines_only_after_the_peak():
    """Age contributes the late-career fall and nothing else — the one thing E and N cannot produce."""
    p = Params()
    u = _control(tau_Y=1.0)

    def at(age: float) -> float:
        return income(State.individual(W_L=0, W_R=0, D=0, E=1.0, N=1.0, H=1.0, age=age), u, p)

    # Stated against the peak rather than against an absolute level: the claim is about the decline
    # mechanism, so recalibrating the earning bounds must not break this test. It did once, on 3 August 2026,
    # only because the 200 000 anchor was written in here as a literal.
    assert at(30.0) == pytest.approx(at(55.0)), "no age effect before the peak"
    assert at(60.0) == pytest.approx(at(55.0) * 0.98 ** 5, rel=1e-9), "2%/yr for 5 years past the peak"
    assert at(65.0) < at(60.0) < at(55.0), "monotone decline after the peak"


def test_health_scales_income_linearly():
    p = Params()  # c = 1 → φ(H) = H
    s_well = State.individual(W_L=0, W_R=0, D=0, E=1.0, N=1.0, H=1.0)
    s_sick = State.individual(W_L=0, W_R=0, D=0, E=1.0, N=1.0, H=0.5)
    u = _control(tau_Y=1.0)
    assert income(s_sick, u, p) == pytest.approx(0.5 * income(s_well, u, p))
    assert phi(0.5, p) == pytest.approx(0.5)


def test_cashflow_identity_feeds_liquid_wealth():
    """ΔW_L over one deterministic step equals (net_cash + μ_P·W_L)·Δt."""
    p = Params()
    s = _state()
    u = _control()
    f = drift(s, u, p)
    from personal_alm.model.dynamics import mu_P
    expected_dW_L = net_cash_to_liquid(s, u, p) + mu_P(u.theta, p) * s.wealth.W_L
    assert f.dW_L == pytest.approx(expected_dW_L)

    nxt = step(s, u, p, dt=p.dt)
    assert nxt.wealth.W_L - s.wealth.W_L == pytest.approx(expected_dW_L * p.dt)


def test_network_ceiling_lifted_by_expertise_and_wealth():
    p = Params()
    poor = State.individual(W_L=0, W_R=0, D=0, E=0.0, N=0.5, H=0.9)
    rich = State.individual(W_L=1_000_000, W_R=0, D=0, E=1.0, N=0.5, H=0.9)
    assert network_ceiling(rich, p) > network_ceiling(poor, p)
    # Base ceiling with no E and no W is exactly K_N0.
    assert network_ceiling(poor, p) == pytest.approx(p.K_N0)


# --- Qualitative shapes -----------------------------------------------------------

def test_expertise_saturates_below_ceiling():
    """Sustained learning drives E up toward — but not past — a fixed point < K_E."""
    p = Params()
    s = State.individual(W_L=0, W_R=0, D=0, E=0.1, N=0.5, H=0.9)
    u = _control(tau_Y=0.0, tau_E=0.8, tau_N=0.0, tau_H=0.2, C=0, m_E=0, m_N=0, p_A=0)
    traj = simulate(s, constant_policy(u), p, n_steps=12 * 60)  # 60 years, monthly
    E_path = np.array([st.person.E.aggregate() for st in traj.states])
    assert np.all(np.diff(E_path) > 0)              # monotone increasing
    assert E_path[-1] < p.K_E                        # never breaches the ceiling
    assert E_path[-1] == pytest.approx(E_path[-2], abs=1e-4)  # converged


def test_health_saturates_and_recovers():
    p = Params()
    s = State.individual(W_L=0, W_R=0, D=0, E=0.5, N=0.5, H=0.3)
    u = _control(tau_Y=0.0, tau_E=0.0, tau_N=0.0, tau_H=1.0, C=0, m_E=0, m_N=0, p_A=0)
    traj = simulate(s, constant_policy(u), p, n_steps=12 * 40)
    H_path = np.array([st.person.H for st in traj.states])
    assert H_path[-1] > H_path[0]      # recovers with rest
    assert H_path[-1] <= p.K_H + 1e-9  # bounded by the ceiling


def test_wealth_accumulates_without_ceiling():
    """With a *sustaining* policy (capitals maintained, no overwork) and positive
    net cash, liquid wealth compounds without ever flattening toward a ceiling —
    the accumulation law, in contrast to the logistic capitals above."""
    p = Params()
    s = State.individual(W_L=100_000, W_R=0, D=0, E=0.7, N=0.6, H=0.9)
    # τ_Y = 0.4 < τ_Y* (no overwork); E/N/H maintained; modest consumption.
    u = _control(tau_Y=0.4, tau_E=0.2, tau_N=0.2, tau_H=0.2,
                 C=20_000, m_E=0, m_N=0, p_A=0, theta=0.5)
    traj = simulate(s, constant_policy(u), p, n_steps=12 * 40)
    W_path = np.array([st.wealth.W_L for st in traj.states])
    assert np.all(np.diff(W_path) > 0)                 # monotone increasing
    # Convex, not saturating: later growth increments exceed earlier ones.
    incr = np.diff(W_path)
    assert incr[-1] > incr[0]
    assert W_path[-1] > 10 * W_path[0]


def test_overwork_accelerates_health_decay():
    p = Params()
    assert delta_H(0.8, p) > delta_H(0.3, p)
    # Below the threshold, decay is exactly baseline.
    assert delta_H(0.3, p) == pytest.approx(p.delta_H0)
    assert delta_H(p.tau_Y_star, p) == pytest.approx(p.delta_H0)


def test_grinding_erodes_health_vs_balanced():
    """The balancing loop: a grind policy ends with lower health than a balanced one."""
    p = Params()
    s = State.individual(W_L=0, W_R=0, D=0, E=0.8, N=0.8, H=0.8)
    grind = _control(tau_Y=0.9, tau_E=0.05, tau_N=0.0, tau_H=0.05,
                     C=0, m_E=0, m_N=0, p_A=0)
    balanced = _control(tau_Y=0.5, tau_E=0.1, tau_N=0.1, tau_H=0.3,
                        C=0, m_E=0, m_N=0, p_A=0)
    H_grind = simulate(s, constant_policy(grind), p, n_steps=12 * 10).final.person.H
    H_bal = simulate(s, constant_policy(balanced), p, n_steps=12 * 10).final.person.H
    assert H_grind < H_bal


def test_debt_floored_at_zero():
    p = Params()
    s = State.individual(W_L=0, W_R=0, D=5_000, E=0.5, N=0.5, H=0.9)
    u = _control(tau_Y=0.0, tau_E=0.0, tau_N=0.0, tau_H=0.5,
                 C=0, m_E=0, m_N=0, p_A=100_000)  # amortise far past zero
    traj = simulate(s, constant_policy(u), p, n_steps=24)
    assert traj.final.wealth.D >= 0.0
