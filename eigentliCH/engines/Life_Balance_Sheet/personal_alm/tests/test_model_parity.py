"""The model exists twice. These tests check the two copies agree.

`model/dynamics.py` is the numpy system used for simulation, the deterministic skeleton and the backtest.
`optim/symbolic.py` is the CasADi system the NLP is built from. **They are independent transcriptions of the same
equations**, and a divergence between them does not fail loudly: the optimiser would happily solve a system nobody
simulates, converge, hand back valid-looking costates, and the simulation would then report different numbers for
the same plan.

**A correction, recorded because the first version of this docstring got it wrong.** This module was written on
3 August 2026 claiming that *nothing* had ever checked the two models agreed. That is false.
`test_optim.py::test_symbolic_drift_matches_numpy` has existed all along, under the heading "Symbolic ↔ numpy
dynamics agreement (the invariant that keeps both honest)". The claim came from a `Get-ChildItem -Include` without
`-Recurse`, which matches no files in PowerShell — an empty result read as evidence of absence.

**What this module adds over that test is real, but narrower than "the first of its kind".** Two things:

- **Tolerance.** The existing test allows `1e-3`, annotated "softplus kink only". That is about six orders of
  magnitude looser than the `1e-9` used here for every component except `dH`, and loose enough to hide a genuine
  formula difference in the wealth flows, which are O(1e5).
- **Coverage.** It has two hand-written cases. This module sweeps the control space and the state space separately.
  That is why it caught the debt-amortisation gate (M67) and the older test did not: catching it needed `D = 0`
  and `p_A > 0` *at the same time*, and neither of the two cases combined them — one has `D = 1.8e6`, the other
  has `p_A = 0.0`.

So the honest account is that a parity test existed, was too loose and too narrow to catch a real bug, and this
module tightened and widened it. Not that the invariant was unguarded.
"""

from __future__ import annotations

from dataclasses import replace

import casadi as ca
import numpy as np
import pytest

from ..model.controls import Control
from ..model.dynamics import (
    Deriv,
    drift,
    habit_of,
    learning_effect,
    network_effect,
    rest_effect,
)
from ..model.dynamics import diffusion as np_diffusion
from ..model.params import Params
from ..model.state import State
from ..optim import symbolic as sym

#: Both sides are float64 doing the same arithmetic in the same order, so agreement should be near-exact.
#: A loose tolerance here would defeat the purpose: the failure this guards against is a *different formula*,
#: which shows up as a large discrepancy, not as accumulated rounding.
TOL = 1e-9

#: **`dH` is the one component the two models differ on by design, and this is the size of it.**
#:
#: `model/dynamics.delta_H` uses an exact `max(0, tau_Y − tau_Y*)`. `optim/symbolic` cannot: IPOPT needs the
#: overwork kink differentiable, so it uses `_softplus_pos(x) = 0.5(x + sqrt(x^2 + 1e-6))`. That is a deliberate,
#: documented smoothing which predates this test.
#:
#: The bound is derived rather than guessed. The softplus's worst deviation from `max(0, ·)` is at x = 0, where it
#: returns `0.5·sqrt(1e-6) = 5e-4`. That flows into `delta_H` scaled by `eta` and into `dH` scaled by `H <= 1`, so
#: |dH difference| <= eta · 5e-4 = 1.5e-4. Set just above it.
#:
#: Every other component gets `TOL`. Widening this one is not a licence to widen those: a discrepancy anywhere
#: else means the two transcriptions have genuinely diverged.
SOFTPLUS_TOL = 2e-4


def _params() -> Params:
    return Params()


def _state(W_L=400_000.0, W_R=800_000.0, D=300_000.0, E=0.8, N=1.2, H=0.9, age=45.0,
           W_res=500_000.0, W_hol=150_000.0, W_P=380_000.0, W_3a=95_000.0) -> State:
    """`W_res` defaults to a *partial* residence share, deliberately.

    The production default is `None`, meaning all of `W_R` is the residence — but that leaves `W_inv = 0`, and a
    parity test run at `W_inv = 0` would multiply the new yield term by zero and agree trivially on both sides.
    500 000 of 800 000 leaves `W_inv = 300 000`, so the term is live and a divergence between the two
    transcriptions can actually show up.
    """
    return State.individual(W_L=W_L, W_R=W_R, D=D, E=E, N=N, H=H, age=age, W_res=W_res, W_hol=W_hol)
    st.wealth.W_P = W_P
    st.wealth.W_3a = W_3a
    return st


def _control(tau_Y=0.45, tau_E=0.10, tau_N=0.08, tau_H=0.15,
             C=90_000.0, m_E=3_000.0, m_N=5_000.0, p_A=10_000.0, theta=0.4) -> Control:
    return Control(tau_Y=tau_Y, tau_E=tau_E, tau_N=tau_N, tau_H=tau_H,
                   C=C, m_E=m_E, m_N=m_N, p_A=p_A, theta=theta)


def _x_vec(x: State) -> np.ndarray:
    # Order must match `sym.W_L, W_R, D, E, N, H, AGE, W_RES` — W_RES is appended last, not slotted beside W_R.
    return np.array([x.wealth.W_L, x.wealth.W_R, x.wealth.D,
                     x.person.E.aggregate(), x.person.N, x.person.H,
                     x.person.age, float(x.wealth.W_res or 0.0), x.wealth.W_hol,
                     x.wealth.W_P, x.wealth.W_3a, habit_of(x, Params())], dtype=float)


def _u_vec(u: Control) -> np.ndarray:
    return np.array([u.tau_Y, u.tau_E, u.tau_N, u.tau_H,
                     u.C, u.m_E, u.m_N, u.p_A, u.theta], dtype=float)


def _symbolic_drift(x: State, u: Control, p: Params) -> np.ndarray:
    xs = ca.SX.sym("x", sym.NX)
    us = ca.SX.sym("u", sym.NU)
    f = ca.Function("f", [xs, us], [sym.drift(xs, us, p)])
    return np.asarray(f(_x_vec(x), _u_vec(u))).ravel()


def _numpy_drift(x: State, u: Control, p: Params) -> np.ndarray:
    d: Deriv = drift(x, u, p)
    return np.array([d.dW_L, d.dW_R, d.dD, float(np.sum(d.dE)), d.dN, d.dH, d.dAge, d.dW_res, d.dW_hol,
                     d.dW_P, d.dW_3a, d.dKappa], dtype=float)


_COMPONENTS = ("dW_L", "dW_R", "dD", "dE", "dN", "dH", "dAge", "dW_res", "dW_hol", "dW_P", "dW_3a", "dKappa")


def _assert_agree(a: np.ndarray, b: np.ndarray, context: str = "") -> None:
    """Compare two drift vectors component by component, strictly except where the models differ by design.

    `dH` carries the softplus smoothing (see `SOFTPLUS_TOL`); everything else must match to `TOL`.
    """
    for name, lhs, rhs in zip(_COMPONENTS, a, b):
        diff = abs(lhs - rhs)
        if name == "dH":
            assert diff < SOFTPLUS_TOL, (
                f"dH{context}: numpy {lhs!r} vs casadi {rhs!r}, differ by {diff:.3e}. That exceeds the "
                f"softplus smoothing's own bound of {SOFTPLUS_TOL:.1e}, so this is a real divergence rather "
                f"than the documented kink approximation."
            )
        else:
            rel = diff / max(1.0, abs(lhs))
            assert rel < TOL, f"{name}{context}: numpy {lhs!r} vs casadi {rhs!r}"


# --- the shape functions, both transcriptions -----------------------------------------


@pytest.mark.parametrize("tau", [0.0, 0.01, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.0])
def test_rest_effect_matches_casadi(tau):
    p = _params()
    t = ca.SX.sym("t")
    f = ca.Function("f", [t], [sym._rest_effect(t, p)])
    assert float(f(tau)) == pytest.approx(rest_effect(tau, p), abs=TOL)


@pytest.mark.parametrize("tau", [0.0, 0.01, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.0])
def test_network_effect_matches_casadi(tau):
    p = _params()
    t = ca.SX.sym("t")
    f = ca.Function("f", [t], [sym._saturating(t, p.tau_N_scale)])
    assert float(f(tau)) == pytest.approx(network_effect(tau, p), abs=TOL)


@pytest.mark.parametrize("tau", [0.0, 0.01, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.0])
def test_learning_effect_matches_casadi(tau):
    p = _params()
    t = ca.SX.sym("t")
    f = ca.Function("f", [t], [sym._saturating(t, p.tau_E_scale)])
    assert float(f(tau)) == pytest.approx(learning_effect(tau, p), abs=TOL)


# --- the shapes' defining properties -------------------------------------------------


def test_each_shape_equals_tau_at_its_reference():
    """The normalisation that lets `alpha_*` keep their values (M67).

    Each shape is built so `f(reference) == reference`, which is what makes `alpha·f(tau)` a drop-in for
    `alpha·tau` without rescaling the rate. If this breaks, introducing a shape silently changes a *level* as
    well as a curve, and every household's capital path moves for a reason nobody chose.
    """
    p = _params()
    assert rest_effect(p.tau_H_ref, p) == pytest.approx(p.tau_H_ref, abs=1e-12)
    assert network_effect(p.tau_N_scale, p) == pytest.approx(p.tau_N_scale, abs=1e-12)
    assert learning_effect(p.tau_E_scale, p) == pytest.approx(p.tau_E_scale, abs=1e-12)


def test_rest_quadrupled_doubles():
    """nu = 0.5 means a square root: 4x the hours, 2x the recovery. The claim made to the CIO."""
    p = _params()
    assert rest_effect(0.40, p) / rest_effect(0.10, p) == pytest.approx(2.0, abs=1e-12)


def test_saturating_shapes_have_a_knee_a_power_law_cannot():
    """Why the family was changed, pinned as a property rather than left in a comment.

    Networking was first proposed as a power law. At nu = 0.5, tripling 10 -> 30 h/week still buys 1.73x, which
    contradicts "anything more is useless". The saturating form buys about 1.50x, and the gap between those two
    numbers is the whole reason for the family change.
    """
    p = _params()
    ratio = network_effect(0.30, p) / network_effect(0.10, p)
    assert ratio < 1.60, f"10->30 h/week buys {ratio:.3f}x; a power law at nu=0.5 would buy 1.73x"
    assert ratio > 1.0, "more networking must still be weakly better, just barely"


def test_shapes_are_monotone_and_nonnegative():
    p = _params()
    for f in (rest_effect, network_effect, learning_effect):
        vals = [f(t, p) for t in np.linspace(0.0, 1.0, 41)]
        assert all(v >= 0.0 for v in vals), f"{f.__name__} went negative"
        assert all(b >= a - 1e-15 for a, b in zip(vals, vals[1:])), f"{f.__name__} is not monotone"


def test_shapes_are_safe_at_and_below_zero():
    """IPOPT evaluates outside its bounds during line searches.

    `rest_effect` raises tau to a fractional power, so a negative argument is NaN — and a NaN does not fail
    loudly, it poisons the solve. Both transcriptions must return a finite number at 0 and below.
    """
    p = _params()
    t = ca.SX.sym("t")
    fr = ca.Function("fr", [t], [sym._rest_effect(t, p)])
    for tau in (0.0, -1e-9, -0.01):
        assert np.isfinite(rest_effect(tau, p)), f"numpy rest_effect({tau}) is not finite"
        assert np.isfinite(float(fr(tau))), f"casadi _rest_effect({tau}) is not finite"


# --- the whole drift vector ----------------------------------------------------------


def test_drift_matches_across_implementations():
    """The headline parity check: every component of f(x, u), both transcriptions."""
    p, x, u = _params(), _state(), _control()
    a, b = _numpy_drift(x, u, p), _symbolic_drift(x, u, p)
    _assert_agree(a, b)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(tau_Y=0.05, tau_E=0.30, tau_N=0.02, tau_H=0.40),   # a study-heavy epoch
        dict(tau_Y=0.70, tau_E=0.05, tau_N=0.10, tau_H=0.05),   # at the work ceiling and rest floor
        dict(tau_Y=0.30, tau_E=0.02, tau_N=0.30, tau_H=0.20),   # networking well past its knee
        dict(m_E=0.0, m_N=0.0),                                  # no money into capital
        dict(theta=0.0),                                         # fully riskless
        dict(theta=1.0),                                         # fully risky
    ],
)
def test_drift_matches_across_the_control_space(kwargs):
    """Parity at one point proves little — the shapes are non-linear, so it is checked across the corners."""
    p, x = _params(), _state()
    u = _control(**kwargs)
    a, b = _numpy_drift(x, u, p), _symbolic_drift(x, u, p)
    _assert_agree(a, b, f" at {kwargs}")


@pytest.mark.parametrize(
    "state_kwargs",
    [
        dict(W_L=0.0, W_R=0.0, D=0.0, E=0.01, N=0.01, H=0.01),   # near the origin
        dict(W_L=5_000_000.0, W_R=3_000_000.0, D=0.0, E=2.0, N=6.0, H=1.0),  # at the state ceilings
        # --- retirement ages, added 4 August 2026 because their absence hid a live divergence ---
        #
        # **Every case above runs at the default age of 45, and that blind spot cost nearly CHF 25 000.** AHV
        # was added to the numpy model and not to the CasADi one, and this suite reported 52 passed while the
        # two transcriptions disagreed on `dW_L` by 24 964 at age 70. At 45 the pension is zero on both sides,
        # so the divergence was real and invisible.
        #
        # Three retirement-age behaviours landed in two days — the pillar-2 contribution gate, the 3a age limit
        # and the AHV entitlement — and none of them was exercised. These four ages bracket every switch: 59
        # before any of them, 64 mid-AHV-ramp, 66 just after it, and 70 with all three settled.
        dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=59.0),
        dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=64.0),
        dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=66.0),
        dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=70.0),
        dict(D=2_000_000.0),                                      # heavily levered
    ],
)
def test_drift_matches_across_the_state_space(state_kwargs):
    p = _params()
    x = _state(**state_kwargs)
    u = _control()
    a, b = _numpy_drift(x, u, p), _symbolic_drift(x, u, p)
    _assert_agree(a, b, f" at {state_kwargs}")


# --- H1: the exogenous partner, on both paths ----------------------------------------


@pytest.mark.parametrize("age", [45.0, 64.0, 66.0, 70.0])
@pytest.mark.parametrize(
    "param_kwargs",
    [
        # The no-op default, asserted here as well as in test_dynamics so a divergence introduced by the H1
        # plumbing shows up even when no partner is declared.
        dict(),
        # Two earners, full splitting. At 66 and 70 the 150% AHV cap BINDS, which is the whole point of running
        # this at retirement ages: `_smooth_min` is the only genuinely new nonlinearity H1 adds, and a cap that
        # never activates in the tests is a cap that is not being compared.
        dict(has_partner=True, partner_income=90_000.0, tax_split_factor=2.0),
        # A partner with no earned income: splitting still applies, the AHV entitlement is the record floor.
        dict(has_partner=True, partner_income=0.0, tax_split_factor=2.0),
        # A younger partner, so the two age gates are offset and the cap starts binding later.
        dict(has_partner=True, partner_income=150_000.0, partner_age_offset=-4.0, tax_split_factor=2.0),
        # An incomplete partner record, which lowers their entitlement and can lift the cap off the sum.
        dict(has_partner=True, partner_income=60_000.0, partner_ahv_record_share=0.6, tax_split_factor=2.0),
        # A declared partner WITHOUT splitting, because the two parameters are independent and a household can
        # be taxed separately (unmarried cohabitation) while still sharing a balance sheet.
        dict(has_partner=True, partner_income=90_000.0, tax_split_factor=1.0),
    ],
)
def test_drift_matches_with_an_exogenous_partner(param_kwargs, age):
    """H1 added a partner to BOTH transcriptions; this is what stops them drifting apart.

    The precedent is exact and expensive: AHV itself was added to the numpy model and not the CasADi one, and the
    suite reported 52 passed while `dW_L` disagreed by 24 964 at age 70 — invisible at 45, where the pension is
    zero on both sides. H1 touches the same three places (cash identity, tax base, AHV) and adds a smooth
    minimum, so it is tested at the same ages for the same reason.
    """
    p = replace(_params(), **param_kwargs)
    x = _state(age=age)
    u = _control()
    a, b = _numpy_drift(x, u, p), _symbolic_drift(x, u, p)
    _assert_agree(a, b, f" at {param_kwargs}, age {age}")


def test_partner_defaults_change_nothing_anywhere():
    """The M73 rule, asserted rather than trusted: four defaults broke it in a single revision.

    A parameter added to an existing calculation must default to reproducing the previous answer. Here that means
    `Params()` and an explicitly-single `Params(has_partner=False, partner_income=0.0, tax_split_factor=1.0)` must
    agree to the LAST BIT, not approximately — so this compares exactly rather than with a tolerance.
    """
    base = _params()
    explicit = replace(base, has_partner=False, partner_income=0.0, tax_split_factor=1.0,
                       partner_age_offset=0.0, partner_ahv_record_share=1.0)
    u = _control()
    for age in (28.0, 45.0, 60.0, 64.0, 66.0, 70.0):
        x = _state(age=age)
        a, b = _numpy_drift(x, u, base), _numpy_drift(x, u, explicit)
        # `array_equal`, not `==`: these are vectors, and `assert a == b` on arrays raises rather than comparing.
        # Bit-exact on purpose — `pytest.approx` would let a default that shifts a figure by a franc through.
        assert np.array_equal(a, b), f"partner defaults are not inert at age {age}: {a} vs {b}"


# --- spend indexing, on both paths ---------------------------------------------------


def test_indexing_is_a_no_op_at_the_current_rate():
    """`pi` is 0.0 by decision, so the mechanism must be exactly inert until someone raises it.

    This is what let the indexing land without re-verifying a single published figure. If it ever stops being
    inert at 0.0, every household's buffer moved for a reason nobody chose.
    """
    from ..goals.goals import indexed_spend

    p = _params()
    assert p.pi == 0.0
    for amount in (0.0, 55_000.0, 120_000.0, 2_250_000.0):
        for horizon in (1.0, 5.0, 10.0, 26.0):
            assert indexed_spend(amount, p.pi, horizon) == amount


def test_indexing_compounds_when_the_rate_is_raised():
    """The mechanism does something once `pi` is non-zero — otherwise wiring it in would be theatre."""
    from ..goals.goals import indexed_spend

    assert indexed_spend(120_000.0, 0.01, 10.0) == pytest.approx(132_555.0, abs=1.0)
    assert indexed_spend(120_000.0, 0.02, 10.0) == pytest.approx(146_279.0, abs=1.0)
    # Monotone in both the rate and the horizon.
    assert indexed_spend(100.0, 0.02, 10.0) > indexed_spend(100.0, 0.01, 10.0) > indexed_spend(100.0, 0.0, 10.0)
    assert indexed_spend(100.0, 0.01, 20.0) > indexed_spend(100.0, 0.01, 10.0)


@pytest.mark.parametrize("pi", [0.0, 0.01, 0.02, 0.05])
def test_the_fi_goal_indexes_identically_on_both_paths(pi):
    """**The parity that matters most for this change.**

    An indexed simulator against a nominal optimiser would be worse than no indexing at all: the solver would
    optimise against an easier goal than the one its answer is then measured on, and the disagreement would
    surface as an unexplained gap between in-sample and evaluated feasibility rather than as an error anyone
    could trace.
    """
    from dataclasses import replace as dc_replace

    from ..goals.spec import GoalSpec

    p = dc_replace(_params(), pi=pi)
    spec = GoalSpec(kind="fi", horizon_years=10.0, epsilon=0.10,
                    params={"G": 120_000.0, "swr": 0.035, "h_res": 0.0})
    x, u = _state(W_L=2_000_000.0, W_R=1_000_000.0, D=200_000.0), _control(p_A=0.0)
    numpy_slack = spec.to_goal().slack(x, p, u)
    xs, us = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    f = ca.Function("f", [xs, us], [spec.symbolic_slack(xs, us, p)])
    casadi_slack = float(f(_x_vec(x), _u_vec(u)))
    assert numpy_slack == pytest.approx(casadi_slack, abs=1e-6), (
        f"at pi={pi} the simulator and the optimiser disagree about the FI target: "
        f"{numpy_slack!r} vs {casadi_slack!r}"
    )


def test_diffusion_matches_across_implementations():
    """Kept deliberately, even though the diffusion term is decided out of the model.

    Round B decided to remove diffusion entirely and let regime paths carry the uncertainty. Until that lands
    the term is live, so it needs the same parity guarantee as the drift — and when it is removed, this test
    failing to import is the reminder that it should go with it.
    """
    p, x, u = _params(), _state(), _control()
    d = np_diffusion(x, u, p)
    a = np.array([d.dW_L, d.dW_R, d.dD, float(np.sum(d.dE)), d.dN, d.dH, d.dAge, d.dW_res, d.dW_hol,
                  d.dW_P, d.dW_3a, d.dKappa], dtype=float)
    xs, us = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    f = ca.Function("f", [xs, us], [sym.diffusion(xs, us, p)])
    b = np.asarray(f(_x_vec(x), _u_vec(u))).ravel()
    _assert_agree(a, b)
