"""The symbolic mirror against B1's numpy model (``lbsim.model``), on every step length the grids use.

The draft's ``tests/test_model_parity.py`` and the structural checks of its ``tests/test_optim.py``, ported, plus
the parity of the market adapter's step (``symbolic.allocation_step`` against ``market.numpy_allocation_step``)
and of the goal slacks. The model exists twice, numpy to simulate and CasADi to optimise; if the two drift the
solver optimises a system nobody simulates.
"""

from __future__ import annotations

import ast
import inspect
import math
import textwrap
from dataclasses import replace

import casadi as ca
import numpy as np
import pytest

from lbsim.model.controls import Control
from lbsim.model.dynamics import diffusion as np_diffusion
from lbsim.model.dynamics import learning_effect, network_effect, rest_effect
from lbsim.model.params import Params
from lbsim.model.state import State
from lbsim.optim import goals as npgoals
from lbsim.optim import market as mk
from lbsim.optim import problem as prob
from lbsim.optim import symbolic as sym
from lbsim.optim.spec import GoalSpec

TOL = 1e-9
SOFTPLUS_TOL = 2e-4   # the draft's bound on the overwork softplus (dH only)
#: Every step length a grid uses: the model's own month, the half year and the year of the variable grid.
STEP_LENGTHS = (1.0 / 12.0, 0.5, 1.0)
_COMPONENTS = ("W_L", "W_R", "D", "E", "N", "H", "AGE", "W_RES", "W_HOL", "W_P", "W_3A", "KAPPA")


def _state(W_L=400_000.0, W_R=800_000.0, D=300_000.0, E=0.8, N=1.2, H=0.9, age=45.0,
           W_res=500_000.0, W_hol=150_000.0, W_P=380_000.0, W_3a=95_000.0) -> State:
    """A partial residence share and live pillars, so every term is exercised (the draft's helper set W_P and
    W_3a after its ``return``, so its parity ran with both at zero; here they are set)."""
    return State.individual(W_L=W_L, W_R=W_R, D=D, E=E, N=N, H=H, age=age, W_res=W_res, W_hol=W_hol,
                            W_P=W_P, W_3a=W_3a)


def _control(tau_Y=0.45, tau_E=0.10, tau_N=0.08, tau_H=0.15,
             C=90_000.0, m_E=3_000.0, m_N=5_000.0, p_A=10_000.0, theta=0.4) -> Control:
    return Control(tau_Y=tau_Y, tau_E=tau_E, tau_N=tau_N, tau_H=tau_H,
                   C=C, m_E=m_E, m_N=m_N, p_A=p_A, theta=theta)


def _u_vec(u: Control) -> np.ndarray:
    return np.array([u.tau_Y, u.tau_E, u.tau_N, u.tau_H, u.C, u.m_E, u.m_N, u.p_A, u.theta], dtype=float)


def _fn(expr_builder, *extra):
    xs, us = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    return ca.Function("f", [xs, us, *extra], [expr_builder(xs, us)])


def _symbolic_drift(x: State, u: Control, p: Params) -> np.ndarray:
    f = _fn(lambda xs, us: sym.drift(xs, us, p))
    return np.asarray(f(mk.state_vector(x, p), _u_vec(u))).ravel()


def _assert_agree(a, b, context: str = "", softplus_scale: float = 1.0) -> None:
    for name, lhs, rhs in zip(_COMPONENTS, a, b):
        diff = abs(lhs - rhs)
        if name == "H":
            assert diff < SOFTPLUS_TOL * softplus_scale, f"H{context}: numpy {lhs!r} vs casadi {rhs!r}"
        else:
            assert diff / max(1.0, abs(lhs)) < TOL, f"{name}{context}: numpy {lhs!r} vs casadi {rhs!r}"


# --- the three shapes -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("tau", [0.0, 0.01, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.0])
def test_the_three_shapes_match(tau):
    p = Params()
    t = ca.SX.sym("t")
    assert float(ca.Function("f", [t], [sym._rest_effect(t, p)])(tau)) == pytest.approx(rest_effect(tau, p), abs=TOL)
    assert float(ca.Function("f", [t], [sym._saturating(t, p.tau_N_scale)])(tau)) == pytest.approx(
        network_effect(tau, p), abs=TOL)
    assert float(ca.Function("f", [t], [sym._saturating(t, p.tau_E_scale)])(tau)) == pytest.approx(
        learning_effect(tau, p), abs=TOL)


def test_the_shapes_are_safe_at_and_below_zero():
    p = Params()
    t = ca.SX.sym("t")
    fr = ca.Function("fr", [t], [sym._rest_effect(t, p)])
    for tau in (0.0, -1e-9, -0.01):
        assert np.isfinite(rest_effect(tau, p)) and np.isfinite(float(fr(tau)))


# --- the drift ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    dict(),
    dict(tau_Y=0.05, tau_E=0.30, tau_N=0.02, tau_H=0.40),
    dict(tau_Y=0.70, tau_E=0.05, tau_N=0.10, tau_H=0.05),
    dict(tau_Y=0.30, tau_E=0.02, tau_N=0.30, tau_H=0.20),
    dict(m_E=0.0, m_N=0.0),
    dict(theta=0.0),
    dict(theta=1.0),
])
def test_drift_matches_across_the_control_space(kwargs):
    p, x, u = Params(), _state(), _control(**kwargs)
    _assert_agree(mk.numpy_drift(x, u, p), _symbolic_drift(x, u, p), f" at {kwargs}")


@pytest.mark.parametrize("state_kwargs", [
    dict(W_L=0.0, W_R=0.0, D=0.0, E=0.01, N=0.01, H=0.01, W_res=0.0, W_hol=0.0),
    dict(W_L=5_000_000.0, W_R=3_000_000.0, D=0.0, E=2.0, N=6.0, H=1.0),
    dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=59.0, W_res=400_000.0, W_hol=0.0),
    dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=64.0, W_res=400_000.0, W_hol=0.0),
    dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=66.0, W_res=400_000.0, W_hol=0.0),
    dict(W_L=800_000.0, W_R=400_000.0, D=0.0, E=0.8, N=1.0, H=0.8, age=70.0, W_res=400_000.0, W_hol=0.0),
    dict(D=2_000_000.0),
])
def test_drift_matches_across_the_state_space(state_kwargs):
    p, x, u = Params(), _state(**state_kwargs), _control()
    _assert_agree(mk.numpy_drift(x, u, p), _symbolic_drift(x, u, p), f" at {state_kwargs}")


@pytest.mark.parametrize("age", [45.0, 64.0, 66.0, 70.0])
@pytest.mark.parametrize("param_kwargs", [
    dict(has_partner=True, partner_income=90_000.0, tax_split_factor=2.0),
    dict(has_partner=True, partner_income=150_000.0, partner_age_offset=-4.0, tax_split_factor=2.0),
    dict(has_partner=True, partner_income=60_000.0, partner_ahv_record_share=0.6, tax_split_factor=2.0),
    dict(child_ages=(3.0, 9.0), child_reference_age=45.0),
    dict(pillar3a_contribution=7_258.0),
])
def test_drift_matches_with_a_partner_children_and_pillar_3a(param_kwargs, age):
    p = replace(Params(), **param_kwargs)
    x, u = _state(age=age), _control()
    _assert_agree(mk.numpy_drift(x, u, p), _symbolic_drift(x, u, p), f" at {param_kwargs}, age {age}")


def test_diffusion_matches():
    p, x, u = Params(), _state(), _control()
    d = np_diffusion(x, u, p)
    a = np.array([d.dW_L, d.dW_R, d.dD, float(np.sum(d.dE)), d.dN, d.dH, d.dAge, d.dW_res, d.dW_hol,
                  d.dW_P, d.dW_3a, d.dKappa], dtype=float)
    f = _fn(lambda xs, us: sym.diffusion(xs, us, p))
    _assert_agree(a, np.asarray(f(mk.state_vector(x, p), _u_vec(u))).ravel())


# --- one step, on every step length ----------------------------------------------------------------------------

@pytest.mark.parametrize("dt", STEP_LENGTHS)
@pytest.mark.parametrize("z", [(0.0, 0.0), (1.3, -0.7), (-2.1, 0.4)])
def test_the_draft_euler_step_matches_on_every_step_length(dt, z):
    p, x, u = Params(), _state(), _control()
    zs = ca.SX.sym("z", 2)
    f = _fn(lambda xs, us: sym.euler_step(xs, us, zs, p, dt), zs)
    b = np.asarray(f(mk.state_vector(x, p), _u_vec(u), z)).ravel()
    _assert_agree(mk.numpy_euler_step(x, u, p, dt, z), b, f" at dt={dt}, z={z}", softplus_scale=dt)


@pytest.mark.parametrize("dt", STEP_LENGTHS)
@pytest.mark.parametrize("r, pi, growth", [(0.0, 0.0, 0.0), (0.045, 0.012, 0.031), (-0.25, 0.04, -0.09),
                                           (0.18, -0.005, 0.12)])
@pytest.mark.parametrize("state_kwargs", [dict(), dict(age=66.0), dict(W_R=0.0, W_res=0.0, W_hol=0.0, D=0.0)])
def test_the_allocation_step_matches_on_every_step_length(dt, r, pi, growth, state_kwargs):
    """Numbers in the NLP (the scenario is drawn first), symbols in the warm-start rollout: both against numpy."""
    p, x, u = Params(), _state(**state_kwargs), _control(theta=1.0)
    p_nm = mk.no_market_params(p)
    infl, g = pi * dt, growth * dt
    a = mk.numpy_allocation_step(x, u, p, dt, r=r, infl=infl, growth=g)
    f_num = _fn(lambda xs, us: sym.allocation_step(xs, us, p_nm, dt, r=r, infl=infl, growth=g))
    rs, ins, gs = ca.SX.sym("r"), ca.SX.sym("i"), ca.SX.sym("g")
    f_sym = _fn(lambda xs, us: sym.allocation_step(xs, us, p_nm, dt, r=rs, infl=ins, growth=gs), rs, ins, gs)
    xv, uv = mk.state_vector(x, p), _u_vec(u)
    _assert_agree(a, np.asarray(f_num(xv, uv)).ravel(), f" (numbers) at dt={dt}", softplus_scale=dt)
    _assert_agree(a, np.asarray(f_sym(xv, uv, r, infl, g)).ravel(), f" (symbols) at dt={dt}", softplus_scale=dt)


def test_the_allocation_step_carries_the_market_and_inflation():
    """The adapted step does what LBSIM-07 says, read on the numbers: liquid wealth earns the state's real
    return, property its real growth, debt and the pillars lose inflation, and theta does nothing."""
    p, u = Params(), _control(theta=1.0)
    x = _state()
    dt, r, pi, g = 1.0, 0.05, 0.02, 0.03
    base = mk.state_vector(x, p) + mk.numpy_drift(x, u, mk.no_market_params(p)) * dt
    out = mk.numpy_allocation_step(x, u, p, dt, r=r, infl=pi, growth=g)
    assert out[0] - base[0] == pytest.approx(x.wealth.W_L * (math.exp(r - pi) - 1.0), rel=1e-12)
    assert out[1] - base[1] == pytest.approx(x.wealth.W_R * (math.exp(g - pi) - 1.0), rel=1e-12)
    assert out[2] - base[2] == pytest.approx(x.wealth.D * (math.exp(-pi) - 1.0), rel=1e-12)
    other = mk.numpy_allocation_step(x, _control(theta=0.0), p, dt, r=r, infl=pi, growth=g)
    assert np.array_equal(out, other), "theta must not move anything under the allocation market"


# --- the goal slacks -------------------------------------------------------------------------------------------

def _slack(spec: GoalSpec, x: State, u: Control, p: Params, level: float = 1.0) -> float:
    f = _fn(lambda xs, us: spec.symbolic_slack(xs, us, p, level=level))
    return float(f(mk.state_vector(x, p), _u_vec(u)))


@pytest.mark.parametrize("pi", [0.0, 0.01, 0.05])
def test_the_draft_goal_slacks_match_numpy(pi):
    p = replace(Params(), pi=pi)
    x, u = _state(W_L=2_000_000.0, W_R=1_000_000.0, D=200_000.0, age=58.0), _control(p_A=0.0)
    cases = [
        (GoalSpec("fi", 10.0, 0.10, {"G": 120_000.0, "swr": 0.035, "h_res": 0.0}),
         npgoals.fi_goal(G=120_000.0, swr=0.035, h_res=0.0, horizon_years=10.0)),
        (GoalSpec("home", 4.0, 0.10, {"price": 1_200_000.0}), npgoals.home_goal(price=1_200_000.0, horizon_years=4.0)),
        (GoalSpec("company", 3.0, 0.10, {"B_buffer": 300_000.0, "N_min": 0.7, "E_min": 0.7}),
         npgoals.company_goal(B_buffer=300_000.0, N_min=0.7, E_min=0.7, horizon_years=3.0)),
        (GoalSpec("retirement", 7.0, 0.10, {"G_ret": 90_000.0, "years_in_retirement": 25.0, "r_disc": 0.02}),
         npgoals.retirement_goal(G_ret=90_000.0, years_in_retirement=25.0, r_disc=0.02, horizon_years=7.0,
                                 epsilon=0.10)),
    ]
    for spec, goal in cases:
        tol = 1e-4 if spec.kind in ("home", "company") else 1e-6   # the smooth min of the joint regions
        assert _slack(spec, x, u, p) == pytest.approx(goal.slack(x, p, u), abs=tol), spec.kind


@pytest.mark.parametrize("measure", mk.MEASURE_NAMES)
@pytest.mark.parametrize("basis, level", [("today", 1.0), ("today", 1.3), ("future", 1.0), ("future", 1.27)])
def test_the_measure_slack_is_the_measure_against_the_target(measure, basis, level):
    p, x, u = Params(), _state(), _control()
    target = 700_000.0
    spec = GoalSpec("measure", 5.0, 0.10, {"measure": measure, "target": target, "basis": basis,
                                           "extra": 12_000.0})
    lv = level if basis == "future" else 1.0
    expected = (lv * mk.measure_value(mk.state_vector(x, p), measure, p) + 12_000.0 - target) / target
    assert _slack(spec, x, u, p, level=level) == pytest.approx(expected, rel=1e-12, abs=1e-12)


_HAIRCUTS = [dict(), dict(h_res=0.1, q_inv=0.3, q_hol=0.2), dict(pension_deposit_share=0.35, h_res=0.2)]
_STATES = [dict(), dict(W_R=0.0, W_res=0.0, W_hol=0.0, D=250_000.0), dict(W_R=0.0, W_res=0.0, W_hol=0.0, D=0.0),
           dict(W_L=20_000.0, W_R=2_000_000.0, W_res=1_500_000.0, W_hol=0.0, D=1_900_000.0),
           dict(W_P=0.0, W_3a=0.0)]


@pytest.mark.parametrize("kind", ["home", "retirement", "capital"])
@pytest.mark.parametrize("haircuts", _HAIRCUTS)
@pytest.mark.parametrize("state_kwargs", _STATES)
def test_the_in_sample_and_out_of_sample_measures_are_one_function(kind, haircuts, state_kwargs):
    """The coordinator's decision of 29.09.2026 (B2's P-11): the NLP's goal measure is the Monte Carlo's, for
    every goal kind, so the in-sample chance and the out-of-sample chance judge the same quantity. The kind's
    measure is B2's own table (``paths.household.MEASURE_OF``) and the value B2's own ``measure_values``."""
    from lbsim.paths.engine import measure_values
    from lbsim.paths.household import MEASURE_OF

    p = replace(Params(), **haircuts)
    x = _state(**state_kwargs)
    measure = MEASURE_OF[kind]
    xs = ca.SX.sym("x", sym.NX)
    f = ca.Function("m", [xs], [sym.measure_expr(xs, measure, p)])
    v = mk.state_vector(x, p)
    numpy = measure_values({k: np.asarray([float(a)]) for k, a in mk.measure_states(v).items()}, measure, p)[0]
    assert float(f(v)) == pytest.approx(float(numpy), rel=1e-12, abs=1e-6), (kind, haircuts, state_kwargs)


def test_the_retirement_measure_leaves_pillar_2_out():
    """The retirement target is the gap the pillar-2 annuity leaves, so pillar-2 capital must not count again."""
    p = Params()
    a, b = _state(W_P=0.0), _state(W_P=900_000.0)
    assert mk.measure_value(mk.state_vector(a, p), "retirement_capital", p) ==         mk.measure_value(mk.state_vector(b, p), "retirement_capital", p)
    assert mk.measure_value(mk.state_vector(b, p), "retirement_capital", p) == pytest.approx(
        b.wealth.W_L + b.wealth.W_3a)


# --- structural checks of the NLP (the draft's test_optim, ported) --------------------------------------------

def _per_node_bounded_states(src: str) -> set[str]:
    """State names in a ``subject_to`` nested inside both the scenario and the time loop (the draft's walker)."""
    found: set[str] = set()

    def walk(node: ast.AST, loops: tuple[str, ...]) -> None:
        if isinstance(node, ast.For):
            tgt = node.target.id if isinstance(node.target, ast.Name) else "?"
            loops = loops + (tgt,)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "subject_to" and len(loops) >= 2:
                for sub in ast.walk(node.value):
                    if (isinstance(sub, ast.Attribute) and sub.attr in sym.STATE_NAMES
                            and isinstance(sub.value, ast.Name) and sub.value.id == "sym"):
                        found.add(sub.attr)
        for child in ast.iter_child_nodes(node):
            walk(child, loops)

    walk(ast.parse(src), ())
    return found


def test_state_names_cannot_drift_from_nx():
    assert len(sym.STATE_NAMES) == sym.NX
    for i, name in enumerate(sym.STATE_NAMES):
        assert getattr(sym, name) == i


def test_every_state_is_bounded_per_node():
    bounded = _per_node_bounded_states(textwrap.dedent(inspect.getsource(prob._solve_once)))
    missing = sorted(set(sym.STATE_NAMES) - set(sym.UNBOUNDED_STATES) - bounded)
    assert not missing, f"states with dynamics but no per-node NLP bound: {missing}"


def test_the_bound_check_would_catch_a_terminal_only_bound():
    buggy = ("def f():\n    for m in range(M):\n        for k in range(K + 1):\n            xk = X[m][k]\n"
             "            opti.subject_to(xk[sym.W_L] >= 0)\n        opti.subject_to(xk[sym.W_RES] >= 0)\n")
    fixed = buggy.replace("        opti.subject_to(xk[sym.W_RES]", "            opti.subject_to(xk[sym.W_RES]")
    assert _per_node_bounded_states(buggy) == {"W_L"}
    assert _per_node_bounded_states(fixed) == {"W_L", "W_RES"}


@pytest.mark.parametrize("step", ["euler", "allocation"])
def test_control_free_states_really_are_control_free(step):
    """Derived from the Jacobian of both steps: fixing a listed state would lose nothing, and every unlisted
    state depends on some control."""
    x, u, z = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU), ca.SX.sym("z", 2)
    if step == "euler":
        expr = sym.euler_step(x, u, z, Params(), 0.5)
    else:
        expr = sym.allocation_step(x, u, mk.no_market_params(Params()), 0.5, r=0.04, infl=0.005, growth=0.01)
    sp = ca.jacobian(expr, u).sparsity()
    for i in prob._CONTROL_FREE_STATES:
        assert not [j for j in range(sym.NU) if sp.has_nz(i, j)], sym.STATE_NAMES[i]
    free = [sym.STATE_NAMES[i] for i in range(sym.NX) if i not in prob._CONTROL_FREE_STATES
            and not any(sp.has_nz(i, j) for j in range(sym.NU))]
    assert not free


def test_theta_moves_nothing_under_the_allocation_market():
    """LBSIM-16: the optimiser does not choose the portfolio; under the allocation step theta has no effect."""
    x, u = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    expr = sym.allocation_step(x, u, mk.no_market_params(Params()), 1.0, r=0.04, infl=0.005, growth=0.01)
    sp = ca.jacobian(expr, u).sparsity()
    assert not any(sp.has_nz(i, sym.THETA) for i in range(sym.NX))


def test_the_two_solver_flags_stay_off():
    """M87: both flags off, settled by the draft's full-matrix measurement."""
    assert prob._ENFORCE_PARTS_LE_WHOLE is False
    assert prob._SCALE_NLP is False
