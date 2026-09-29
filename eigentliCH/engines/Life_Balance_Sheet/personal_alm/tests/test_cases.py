"""The archetype interface (personal_alm/cases.py).

These assert the *interface* is sound — every life is a valid input, every goal
kind builds both a Python goal and a symbolic slack, and the engine produces a
distinct result per case. Per-case calibration of the magnitudes (getting each
P(goal) and binding constraint to match the book) is a separate, iterative task;
only the flagship (Nicolas) is asserted numerically here.
"""

import casadi as ca

from ..optim import symbolic as sym
import pytest

from personal_alm.cases import (
    WORKED_LIVES, FIVE_LIVES, NICOLAS, CaseResult, run_case,
)
from personal_alm.goals.spec import GoalSpec
from personal_alm.model.params import Params

P = Params()


# --- GoalSpec: every archetype builds both representations (fast, no solve) ------

def test_every_goal_kind_builds_python_and_symbolic():
    specs = [
        GoalSpec("fi", 5.0, 0.10, dict(G=120_000, swr=0.035, h_res=0.0)),
        GoalSpec("home", 8.0, 0.20, dict(price=400_000)),
        GoalSpec("company", 3.0, 0.25, dict(B_buffer=200_000, N_min=0.7, E_min=0.7)),
        GoalSpec("retirement", 7.0, 0.15, dict(G_ret=90_000, years_in_retirement=25.0)),
    ]
    x, u = ca.SX.sym("x", sym.NX), ca.SX.sym("u", sym.NU)
    for s in specs:
        assert s.to_goal().kind == s.kind          # Python goal
        expr = s.symbolic_slack(x, u, P)            # symbolic slack
        assert expr.shape == (1, 1)
        assert s.mode in ("at_deadline", "by_deadline")


def test_goalspec_rejects_unknown_kind():
    with pytest.raises(ValueError):
        GoalSpec("teleport", 5.0, 0.10)


# --- The five lives are valid inputs ---------------------------------------------

def test_five_lives_are_valid_inputs():
    assert len(FIVE_LIVES) == 5
    for c in FIVE_LIVES:
        assert c.x0.person.H > 0
        assert c.params(P) is not None
        assert c.goal.to_goal().kind == c.goal.kind


# --- One end-to-end run over all five, reused across assertions ------------------

# **These two are slow because of the fixture, not because of their own bodies.** `results` is module-scoped
# and runs `run_case` once per life in FIVE_LIVES: five full solves, measured at 941 s for this file even with
# the two flagship tests already deselected. Fixture setup is charged to whichever test requests it first,
# which is why `--durations` pointed at a test whose body is three asserts, and why grepping test bodies for
# `run_case` found nothing here. A marker on the fixture would do nothing: pytest builds a fixture because a
# test asked for it, so the cost is avoided only by deselecting every test that asks.
@pytest.fixture(scope="module")
def results():
    # Structural checks only — cheapest settings (single start, few scenarios).
    return {c.name: run_case(c, M_opt=8, M_eval=120, seed=0, n_starts=1)
            for c in FIVE_LIVES}


@pytest.mark.slow
def test_run_case_returns_a_result_per_life(results):
    for name, r in results.items():
        assert isinstance(r, CaseResult)
        assert 0.0 <= r.p_goal <= 1.0
        assert set(r.action) == {"tau_Y", "tau_E", "tau_N", "tau_H",
                                 "C", "m_E", "m_N", "p_A", "theta"}
        assert r.binding


@pytest.mark.slow
def test_interface_produces_distinct_results(results):
    """The whole point: different archetypes → different results, not one answer.

    The worked-lives gallery is fi/retirement heavy; that all four goal *kinds*
    build and solve is covered independently by
    test_every_goal_kind_builds_python_and_symbolic."""
    probs = {round(r.p_goal, 2) for r in results.values()}
    assert len(probs) >= 3
    kinds = {r.kind for r in results.values()}
    assert len(kinds) >= 2
    assert kinds <= {"home", "fi", "company", "retirement"}


@pytest.mark.slow
def test_flagship_nicolas_meets_target():
    """The calibrated, validated result: Nicolas clears the 90% FI target.

    **M_opt raised 16 -> 32 on 3 August 2026, from measurement rather than preference.** The old comment here
    said 16 was "enough optimiser scenarios to avoid the poor local optimum a too-small sample can fall into".
    Both halves were wrong. It was not enough, and the problem is not local optima: `n_starts=8` reproduces
    `n_starts=3` byte for byte, while doubling scenarios collapses the seed spread from 0.585 to 0.032.

        n_starts=3  M_opt=16   0.845 0.855 0.858 0.555 0.273   spread 0.585
        n_starts=8  M_opt=16   0.845 0.855 0.858 0.555 0.273   spread 0.585
        n_starts=3  M_opt=32   0.845 0.840 0.860 0.838 0.828   spread 0.032

    At M=16 the CVaR constraint was being violated by up to 4.3e4 against a 1e-3 bound while the solve
    reported success; `problem.py` now gates `success` on the constraint actually holding, so too few
    scenarios fails loudly instead of returning a confident plan with no tail constraint behind it.

    **THE THIRD ROW ABOVE NO LONGER REPRODUCES, AND `assert r.success` DOES NOT MEAN WHAT IT SAYS. See M79.**
    Re-measured 5 August 2026 at the same settings: seed 4 gives 0.3025, not 0.828, so the spread is ~0.52 and
    not 0.032. The scan above is 3 August; the per-scenario seeding fix landed on the 4th and was validated on
    seed 0 only. The cause is not the scenario count: phase 1 cannot fund this goal at any draw (`s_star`
    29 032 at seed 0, 65 924 at seed 4), phase 2's bound is therefore `s_star` rather than zero, and the two
    seeds optimise against requirements 36 892 francs a year apart. Both certify. Neither funds the goal —
    which is why the assertion below is a level check on `p_goal` and NOT evidence that the flagship's goal is
    reachable. Do not re-tune the floor against this; the fix is P8.
    
    **AND THE CASE ITSELF MOVED ON 26 AUGUST 2026 (M88), SO BOTH ASSERTIONS BELOW ARE EXPECTED RED.** On the
    author's ruling the flagship's goal went to `swr = 0.030`, which raises its requirement from 1 142 857 to
    1 333 333. Measured at exactly these settings straight after: `outcome = "undetermined"`, `p_goal = 0.113`.
    So `r.success` is False and the 0.80 floor is far out of reach -- not because the floor drifted, but
    because the household is being asked a harder question than the one these numbers were drawn against.

    **Do not re-tune either assertion to this.** One seed at one horizon is not a distribution, and the whole
    point of the floor's history above is that a level fitted to the seed in front of you is not a
    measurement. The re-measurement across horizons is what these should be rebuilt on.
    """
    r = run_case(NICOLAS, M_opt=32, M_eval=400, seed=0, n_starts=3)
    assert r.success
    # **Floor lowered 0.85 -> 0.80 on 3 August 2026, and only after the diagnosis, not to make this pass.**
    #
    # With the CVaR constraint actually enforced (see the `success` gate in `problem.py`), out-of-sample
    # p_goal lands in a narrow band that 0.85 sits *inside*:
    #
    #     M_opt=32   seed 0..4   0.845 0.840 0.860 0.838 0.828     mean 0.842
    #
    # A floor drawn through the middle of the achieved distribution is a coin toss on which seed is used, not
    # a measurement. 0.80 sits below the observed minimum with room, so a breach means something moved.
    #
    # The reason the level is ~0.84 rather than ~0.90 is structural, not a shortfall: the goal carries
    # `epsilon = 0.10`, the optimiser maximises utility *subject to* that bound, and it therefore consumes
    # until the bound binds. Making the goal easier — as `G` 120k -> 90k did — does not raise p_goal, it
    # raises consumption. And as `test_optim.py::test_meets_confidence_target` already records, bounding the
    # mean shortfall of the worst decile does not bound *how many* scenarios miss, so the hit rate is a
    # weaker and different claim from the constraint the solver enforces.
    #
    # The robustness question is now asked by `test_flagship_confidence_is_stable_across_seeds` instead, on
    # the spread. That is the assertion that would have caught the M=16 defect; this one is a level check.
    assert r.p_goal >= 0.80
    assert r.binding == "drawable wealth"
    assert r.exchange_rate.winner == "overtime"


@pytest.mark.slow
def test_flagship_confidence_is_stable_across_seeds():
    """The suite asserted ONE seed for months, and that is how the M=16 defect hid.

    A single draw from a distribution that ranged 0.273 to 0.858 was not measuring solution quality, it was
    measuring seed 0 — and it only surfaced when two calibration changes happened to push seed 0 across the
    0.85 line. What is worth pinning is the *spread*: if the scenario count is too low for the tail constraint
    to bind reliably, seeds disagree, and that is the symptom to catch rather than any one value.

    Deliberately a small sample at M_opt=32 to stay affordable in the suite; the diagnosis that set these
    numbers used five seeds at three settings. If this goes red, re-run that scan before touching the bound.

    **IT IS RED, AND CORRECTLY SO — do not loosen it. See M79.** Seed 4 returns 0.3025 against seeds 0 and 3 at
    ~0.82, measured 5 August 2026. This test is the one that caught it: the spread is real, it survives at
    M_opt=32, and its cause is phase 2 inheriting its CVaR bound from a phase 1 whose shortfall depends on the
    draw (29 032 at seed 0, 65 924 at seed 4). Raising `M_opt` will not close it, because the bound moves with
    the draw at any scenario count. Leave both assertions until P8 decides what the bound should be.

    **P8 HAS SINCE LANDED and the case has since moved, so the reason it is red is no longer the reason
    written above.** Phase 2's bound is `cvar_tol` now, chosen rather than inherited from the draw. And M88's
    ruling of 26 August 2026 took the flagship's goal to `swr = 0.030`, a requirement 190 476 higher, at which
    the case returns `undetermined` with `p_goal = 0.113` at these very settings. A spread test over three
    seeds cannot say anything useful while no seed produces a plan: what it would measure is the spread of an
    unconverged iterate. Rebuild it on the re-measurement, not on this.
    """
    vals = [run_case(NICOLAS, M_opt=32, M_eval=400, seed=s, n_starts=3).p_goal for s in (0, 3, 4)]
    assert max(vals) - min(vals) < 0.10, (
        f"p_goal spread {max(vals) - min(vals):.3f} across seeds {vals} — at M=16 this was 0.585 because the "
        f"CVaR constraint was not binding. A wide spread means the scenario count is too low again."
    )
    # Seeds 3 and 4 were the two that collapsed, so name them: they must now clear the same floor as seed 0.
    assert all(v >= 0.80 for v in vals), f"a seed fell below 0.80: {vals}"


# --- an undetermined solve must arrive with its cause attached -------------------

def test_case_result_carries_the_solver_stats():
    """`undetermined` is reached two ways that mean opposite things, so the cause travels with the result.

    Phase 1 not converging means nothing numeric may be claimed. Phase 1 converging with `s_star <= cvar_tol`
    and phase 2 certifying nothing anyway means the goal is within reach and the optimiser failed on the
    household's own problem -- a solver defect, not a finding about the household. Until 26 August 2026 both
    arrived here as the bare string `"undetermined"` with `stats` discarded at this boundary, which is why no
    diagnosis of an undetermined risk assessment had been possible.

    A structural test, not a solve: it pins that the field exists, defaults safely and is not client-facing.
    """
    from personal_alm.cases import CaseResult
    from personal_alm.optim.problem import Costates, ExchangeRate  # noqa: PLC0415

    cs = Costates(lam_W=0.0, lam_E=0.0, lam_N=0.0, lam_H=0.0)
    xr = ExchangeRate(goal="fi", networking_value=0.0, overtime_value=0.0)

    r = CaseResult(name="x", kind="fi", p_goal=0.0, action={}, costates=cs,
                   exchange_rate=xr, binding="", success=False)
    assert r.stats == {}                       # defaults empty, never None
    assert r.outcome == "undetermined"         # __post_init__ still repairs the unlabelled failure

    r2 = CaseResult(name="x", kind="fi", p_goal=0.0, action={}, costates=cs,
                    exchange_rate=xr, binding="", success=False,
                    outcome="undetermined", stats={"restore_converged": False, "s_star": 52_687.0})
    assert r2.stats["restore_converged"] is False
    assert "s_star" not in r2.summary()        # the diagnosis is not printed at the client-facing boundary
