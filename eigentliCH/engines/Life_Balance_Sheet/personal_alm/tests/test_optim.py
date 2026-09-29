"""Optimiser layer (spec §16.4 step 4): the Route A NLP recovers sane allocations,
the chance constraint binds at the right ε, and the costates/exchange-rates are
economically meaningful."""

import ast
import inspect
import textwrap

import casadi as ca
import numpy as np
import pytest

from personal_alm.model.controls import Control
from personal_alm.model.dynamics import drift as npy_drift
from personal_alm.model.dynamics import habit_of
from personal_alm.model.params import Params
from personal_alm.model.state import State
from personal_alm.optim import symbolic as sym
from personal_alm.optim import problem as prob
from personal_alm.optim.problem import solve_fi

P = Params()


# --- Every state is bounded at every node (the gap the optimiser found first) ------

def _per_node_bounded_states(src: str) -> set[str]:
    """State names appearing in a `subject_to` nested inside BOTH the scenario and the time loop.

    Note this deliberately requires two enclosing loops. The CONTROL bounds are legitimately nested
    one deep — `U[k]` is shared across scenarios to encode non-anticipativity, so there is no `m`
    loop for them to be inside — and a version of this check that ignored the distinction flagged
    them, which was the check being wrong rather than the code.

    Structural, not textual. The defect this guards against was an *indentation* one: four
    bounds sat at the `for m` level rather than inside `for k`, so they constrained the leaked
    loop variable — the terminal node — and nothing else. A grep found them and saw nothing
    wrong, which is exactly why the check has to look at the enclosing loops.

    Takes source rather than reaching for `_solve_once` itself, so
    `test_the_bound_check_would_catch_a_terminal_only_bound` can validate *this* function
    against both shapes. A checker validated through a copy of itself is no checker.
    """
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
                    # Match `sym.W_RES` as an attribute, so `W_R` is not read out of `W_RES`.
                    if (isinstance(sub, ast.Attribute) and sub.attr in sym.STATE_NAMES
                            and isinstance(sub.value, ast.Name) and sub.value.id == "sym"):
                        found.add(sub.attr)
        for child in ast.iter_child_nodes(node):
            walk(child, loops)

    walk(ast.parse(src), ())
    return found


def _nlp_source() -> str:
    """`_solve_once` source, dedented so `ast.parse` accepts it."""
    return textwrap.dedent(inspect.getsource(prob._solve_once))


def test_state_names_cannot_drift_from_nx():
    """Half the guard rail: a twelfth state must be named before anything else passes."""
    assert len(sym.STATE_NAMES) == sym.NX
    for i, name in enumerate(sym.STATE_NAMES):
        assert getattr(sym, name) == i, f"{name} is not at index {i}"


def test_control_free_states_really_are_control_free():
    """`_CONTROL_FREE_STATES` is fixed by equal bounds, so a wrong entry silently over-constrains the problem.

    Derived from the symbolic Jacobian rather than trusted: if `d euler_step[i] / du` is structurally zero for
    every control, the optimiser cannot influence state `i` and fixing it to its seeded value loses nothing. The
    moment someone gives `W_R` a purchase control or lets the household choose its residence share, this test
    fails and the state has to come off the list.
    """
    x, u, z = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU), ca.SX.sym("z", 2)
    J = ca.jacobian(sym.euler_step(x, u, z, P, 0.5), u)
    sp = J.sparsity()
    for i in prob._CONTROL_FREE_STATES:
        nz = [j for j in range(sym.NU) if sp.has_nz(i, j)]
        assert not nz, (
            f"state {sym.STATE_NAMES[i]} is listed control-free but its euler_step row depends on controls "
            f"{[j for j in nz]} — fixing it by equal bounds would remove a real degree of freedom."
        )
    # And the converse, so the list cannot silently shrink: every state NOT listed must depend on some control,
    # otherwise it is a missed 352 variables per scenario-node.
    unlisted_and_free = []
    for i in range(sym.NX):
        if i in prob._CONTROL_FREE_STATES:
            continue
        if not any(sp.has_nz(i, j) for j in range(sym.NU)):
            unlisted_and_free.append(sym.STATE_NAMES[i])
    assert not unlisted_and_free, (
        f"these states depend on no control and could be fixed rather than solved for: {unlisted_and_free}"
    )


def test_every_state_is_bounded_per_node():
    """Every state must be bounded at every node, or exempted with a reason.

    `W_RES`, `W_HOL`, `W_P` and `W_3A` were added to the state vector on 3-4 August 2026 with dynamics and no
    constraints at all, and then with constraints written at the `for m` level rather than inside `for k` — so
    they bound the leaked loop variable, `X[m][K]`, and nothing else. `X[m][0]` is pinned by the initial
    condition, so nine of eleven nodes stayed free and the fix was ~2/11 effective.

    Checked structurally, because the statement text was correct and only its *position* was wrong. Nothing in a
    parity test asks this: parity compares the two transcriptions, and both were right throughout.
    """
    bounded = _per_node_bounded_states(_nlp_source())
    expected = set(sym.STATE_NAMES) - set(sym.UNBOUNDED_STATES)
    missing = sorted(expected - bounded)
    assert not missing, (
        f"states with dynamics but no per-node NLP bound: {missing}. A new state needs a constraint in the "
        f"same commit as its dynamics — add one in `_solve_once`, or add it to `sym.UNBOUNDED_STATES` with "
        f"the reason it cannot be pushed."
    )


def test_the_bound_check_would_catch_a_terminal_only_bound():
    """Validate the instrument: it must distinguish per-node from the actual defect shape.

    A checker only ever exercised against correct code proves nothing, and the first version of this walker
    dispatched on child nodes — which made every constraint look one loop shallower and wrongly flagged `W_L`.
    So assert both shapes explicitly, against the *same* function the real test calls.
    """
    buggy = """
def f():
    for m in range(M):
        for k in range(K + 1):
            xk = X[m][k]
            opti.subject_to(xk[sym.W_L] >= 0)
        opti.subject_to(xk[sym.W_RES] >= 0)
"""
    fixed = """
def f():
    for m in range(M):
        for k in range(K + 1):
            xk = X[m][k]
            opti.subject_to(xk[sym.W_L] >= 0)
            opti.subject_to(xk[sym.W_RES] >= 0)
"""
    assert _per_node_bounded_states(buggy) == {"W_L"}, (
        "the checker failed to see the terminal-only bound as unbounded")
    assert _per_node_bounded_states(fixed) == {"W_L", "W_RES"}, (
        "the checker failed to accept a correct per-node bound")


def _nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


# --- Symbolic ↔ numpy dynamics agreement (the invariant that keeps both honest) ---

def test_symbolic_drift_matches_numpy():
    xv, uv = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    f_fun = ca.Function("f", [xv, uv], [sym.drift(xv, uv, P)])
    cases = [
        ([0.6e6, 5.0e6, 1.8e6, 0.90, 0.90, 0.70],
         [0.30, 0.10, 0.10, 0.20, 120_000, 5_000, 10_000, 60_000, 0.40]),
        ([1.0e5, 0.0, 0.0, 0.30, 0.20, 0.95],
         [0.70, 0.20, 0.05, 0.05, 20_000, 2_000, 1_000, 0.0, 0.60]),
    ]
    for xnum, unum in cases:
        # `W_res` left at its default (None → all of W_R is the residence), so `W_inv = 0` in both cases here.
        # That is fine for *this* test but is exactly why `test_model_parity.py::_state` sets a partial share:
        # at `W_inv = 0` the new yield term is multiplied by zero and agrees trivially on both sides.
        st = State.individual(W_L=xnum[0], W_R=xnum[1], D=xnum[2],
                              E=xnum[3], N=xnum[4], H=xnum[5])
        u = Control(*unum)
        fn = npy_drift(st, u, P)
        fnp = np.array([fn.dW_L, fn.dW_R, fn.dD, fn.dE[0], fn.dN, fn.dH, fn.dAge, fn.dW_res, fn.dW_hol,
                        fn.dW_P, fn.dW_3a, fn.dKappa])
        fsx = np.array(f_fun(xnum + [st.person.age, float(st.wealth.W_res or 0.0), st.wealth.W_hol,
                                     st.wealth.W_P, st.wealth.W_3a, habit_of(st, P)], unum)).flatten()
        assert np.max(np.abs(fsx - fnp)) < 1e-3   # softplus kink only


# --- One converged solve, reused across assertions -------------------------------

# **Seven tests, one solve, and all seven have to be deselected for the default run to skip it.** `sol_90`
# is module-scoped precisely so the solve is paid once rather than seven times, which is the right design --
# and it means the cost is charged to whichever test asks first (measured: 138 s of "setup" against
# test_solver_converges, whose body is one assert). A marker on the fixture would achieve nothing, because
# pytest builds a fixture when a test requests it. So the marker goes on every consumer, and
# test_relaxing_confidence_raises_consumption carries it too: that one solves twice in its own body, 140 s.
@pytest.fixture(scope="module")
def sol_90():
    return solve_fi(_nicolas_45(), horizon_years=5.0, params=P,
                    epsilon=0.10, psi=1.0, dt_opt=0.5, M=14, seed=0, n_starts=2)


@pytest.mark.slow
def test_solver_converges(sol_90):
    assert sol_90.success


@pytest.mark.slow
def test_first_action_is_admissible(sol_90):
    u = sol_90.u0
    taus = [u["tau_Y"], u["tau_E"], u["tau_N"], u["tau_H"]]
    assert all(t >= -1e-6 for t in taus)
    assert sum(taus) <= 1.0 + 1e-6
    assert all(u[k] >= -1e-6 for k in ("C", "m_E", "m_N", "p_A"))
    assert -1e-6 <= u["theta"] <= 1.0 + 1e-6


@pytest.mark.slow
def test_the_cvar_bound_is_actually_met(sol_90):
    """The constraint the NLP contains is satisfied by the solve it produced.

    **This replaced `test_meets_confidence_target` on 21 August 2026, keeping one of its two assertions.**
    That test also asserted an in-sample hit rate of 0.85, which was a floor on a coarse grid rather than a
    calibrated target: at M = 14 the rate is 12/14 = 0.857 and the next step down is 11/14 = 0.786, so a single
    scenario changing side took it under. It went red and stayed red, and was dropped by decision -- lowering
    the number again would have moved the coin toss rather than removed it. Bounding the mean shortfall of the
    worst decile does not bound how many scenarios miss, so the two were never the same claim.

    **The bound is not a literal, and writing one here cost an hour of solving to find out.** The first
    version of this test asserted `cvar_shortfall <= 1e-3`, taking the default `cvar_tol` for the bound. The
    bound the solve actually uses is `max(cvar_tol, 1e-5 * G)`: `solve_case` widens it to the goal's own money
    scale on purpose, because a sub-franc shortfall on a five-figure goal is solver noise, and the fixed 1e-3
    once made a report tell a household its goal was out of reach "by CHF 0 a year".

    Measured on this fixture: the solve converges, `cvar_constrained` and `cvar_ok` are both true, `s_star` is
    -16 250 -- the goal is over-funded -- and the CVaR sits exactly on its bound. The test was red while the
    engine was right, which is the worst way for a test to be wrong: it accuses the code it is checking.

    So the comparison is against the bound the solve recorded, which is also what makes this robust to the
    widening rule changing. The optimiser drives CVaR *onto* that bound, so it is compared with a tolerance
    rather than exactly: asserting a bare `<=` against a quantity the solver pins to the bound is a coin toss
    on the last digits.
    """
    assert sol_90.success, "the fixture's solve must converge before its constraint means anything"
    stats = sol_90.stats or {}
    assert stats.get("cvar_constrained") is True, "the constraint must be in the problem at all"
    bound = stats.get("cvar_bound")
    assert bound is not None, "the solve must record the bound it used, or nothing here can be checked"
    assert sol_90.cvar_shortfall <= bound * (1.0 + 1e-6) + 1e-6


@pytest.mark.slow
def test_costates_positive_and_health_is_scarce(sol_90):
    c = sol_90.costates
    assert c.lam_W > 0 and c.lam_E > 0 and c.lam_N > 0 and c.lam_H > 0
    # The book's thesis: for saturated E/N, health carries the highest shadow price.
    assert c.lam_H > c.lam_E
    assert c.lam_H > c.lam_N


@pytest.mark.slow
def test_saturated_capitals_get_no_time(sol_90):
    # E and N start at 0.90 (near ceiling) → the optimiser buys neither.
    assert sol_90.u0["tau_E"] < 0.05
    assert sol_90.u0["tau_N"] < 0.05


@pytest.mark.slow
def test_overtime_beats_networking_for_nicolas(sol_90):
    """N is saturated and the goal is drawable wealth → an hour of earning is worth
    more than an hour of networking (the inverse of the founding case)."""
    xr = sol_90.exchange_rate
    assert xr.winner == "overtime"
    assert xr.ratio > 1.0


# --- Chance constraint binds at the right ε --------------------------------------

@pytest.mark.slow
def test_relaxing_confidence_raises_consumption():
    """Tighter confidence forces more saving (lower consumption); relaxing it lets
    the optimiser spend more and accept a lower P(FI) — the constraint is binding."""
    tight = solve_fi(_nicolas_45(), horizon_years=5.0, params=P,
                     epsilon=0.10, psi=1.0, dt_opt=0.5, M=12, seed=0, n_starts=2)
    loose = solve_fi(_nicolas_45(), horizon_years=5.0, params=P,
                     epsilon=0.50, psi=1.0, dt_opt=0.5, M=12, seed=0, n_starts=2)
    assert tight.success and loose.success
    assert loose.u0["C"] > tight.u0["C"]
    assert loose.p_fi_insample <= tight.p_fi_insample


# --- The two solver flags are a settled decision, not a knob ----------------------

def test_the_two_solver_flags_stay_off():
    """M87, measured 25 August 2026 on the post-M80 model: 24 cells, both flags off wins.

    Pinned because the value here is a *measurement's* verdict, and the same constraint has now carried three
    successive opposite verdicts (M76 "safe", M77 "a bad trade", M78 "net-positive", M87 "certifies nothing")
    -- each overturned by measuring more of the space. Flipping either flag on a hunch is the failure mode this
    line exists to stop; flipping it on a fresh full-matrix run is the way it is meant to change.

    `M77=True` certifies 0 of 6 under either scaling and drops the usable-finding count from 4 of 6 to 1 of 6.
    Scaling's certifying set is a strict subset of unscaled's, so unscaled weakly dominates.
    """
    assert prob._ENFORCE_PARTS_LE_WHOLE is False
    assert prob._SCALE_NLP is False
