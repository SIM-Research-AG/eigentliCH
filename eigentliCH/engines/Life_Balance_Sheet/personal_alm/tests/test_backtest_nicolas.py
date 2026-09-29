"""Nicolas backtest (spec §15.2 / book Fig. 16.1).

The calibration gate: run the dynamics forward from age 19 with the epoch control
history and events, and check both the three hard observables and the qualitative
shape of the trajectory.
"""

import numpy as np
import pytest

from personal_alm.calibrate import nicolas


@pytest.fixture(scope="module")
def bt() -> nicolas.Backtest:
    return nicolas.run()


# --- The three hard observables (spec §15.2) -------------------------------------

def test_three_hard_observables(bt):
    obs = {o.name: o for o in nicolas.observables(bt)}
    assert obs["equity-funded purchase @26"].ok, obs["equity-funded purchase @26"].value
    assert obs["CHF ~2M leverage @36"].ok, obs["CHF ~2M leverage @36"].value
    assert obs["valuation > CHF 5M @45"].ok, obs["valuation > CHF 5M @45"].value


def test_all_observables_pass(bt):
    assert all(o.ok for o in nicolas.observables(bt))


# --- Qualitative shape (book Fig. 16.1) ------------------------------------------

def _E(st):
    return st.person.E.aggregate()


def test_expertise_leads_network_early(bt):
    """Early on, expertise is built before the network compounds."""
    at24 = bt.at_age(24.0)
    assert _E(at24) > at24.person.N


def test_network_ceiling_lifts_after_property_and_founding(bt):
    """The K_N(E, W) coupling: network accelerates once E and property lift its
    ceiling (spec §6.1). Network at 45 far exceeds its early level and keeps rising."""
    n29 = bt.at_age(29.0).person.N
    n36 = bt.at_age(36.0).person.N
    n45 = bt.at_age(45.0).person.N
    assert n45 > n36 > n29
    # Post-founding growth outpaces pre-founding growth (acceleration).
    pre = bt.at_age(29.0).person.N - bt.at_age(22.0).person.N
    post = n36 - n29
    assert post > pre


def test_health_dips_then_recovers(bt):
    """Health falls through the intense building years, then recovers."""
    h19 = bt.at_age(19.0).person.H
    h26 = bt.at_age(26.0).person.H
    h45 = bt.at_age(45.0).person.H
    assert h26 < h19        # dips through the grind
    assert h45 > h26        # recovers later


def test_net_worth_accelerates_after_property(bt):
    """Net worth accelerates once the property and mortgage events land."""
    nw_26 = bt.at_age(26.0).net_worth
    nw_36 = bt.at_age(36.0).net_worth
    nw_45 = bt.at_age(45.0).net_worth
    assert nw_45 > nw_36 > nw_26


def test_trajectory_is_finite_and_bounded(bt):
    """No blow-ups or negative capitals leak through the clamp."""
    for st in bt.states:
        assert np.isfinite(st.wealth.W_L)
        assert st.wealth.W_R >= 0 and st.wealth.D >= 0
        assert _E(st) >= 0 and st.person.N >= 0
        assert 0.0 <= st.person.H <= 1.0
