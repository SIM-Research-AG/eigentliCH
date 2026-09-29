"""Task P3: the report facts, and the two constraints that shape them.

M74 is asserted STRUCTURALLY here rather than by review, because a review is what failed: a dossier disclosed a
second household's debt level on 4 August 2026. The guarantee is that `ReportFacts` has no field able to hold a
second household, and this test is what stops someone adding a "peer comparison" field later.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from personal_alm.app.befund import DEFAULT_SETTINGS, PREVIEW_SETTINGS, befund
from personal_alm.app.onboarding import SubmissionError, case_from_submission
from personal_alm.app.report import ReportFacts, Warning_, report_facts
from personal_alm.cases import CaseResult, run_case
from personal_alm.optim.problem import Costates, ExchangeRate


def _submission(**over) -> dict:
    base = {
        "schema_version": "onb@0.1.1",
        "meta": {"collected": "2026-08-04", "source": "test"},
        "state": {"age": 52, "W_L": 400_000, "W_R": 2_000_000, "W_res": 1_200_000, "W_hol": 0,
                  "D": 800_000, "W_P": 600_000, "W_3a": 90_000, "E": 0.9, "N": 0.8, "H": 0.75},
        "params": {"G": 120_000, "swr": 0.035, "epsilon": 0.15},
        "goals": [{"kind": "fi", "description": "Unabhängigkeit", "target_year": 2036, "confidence": 0.85}],
        "raw": {},
    }
    for k, v in over.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def _result(case, **over) -> CaseResult:
    """A CaseResult without solving, so the report layer can be tested independently of the optimiser.

    `ExchangeRate.winner` and `.determined` are PROPERTIES derived from the two costate-times-marginal-product
    values, not init fields — a non-converged solve leaves both at 0.0 and `winner` becomes "undetermined". So an
    undetermined exchange rate is built by passing two zeroes, which is exactly how the engine produces one.
    """
    action = dict(tau_Y=0.40, tau_E=0.10, tau_N=0.10, tau_H=0.20,
                  C=90_000.0, m_E=3_000.0, m_N=2_000.0, p_A=20_000.0, theta=0.5)
    action.update(over.pop("action", {}))
    base = dict(name=case.name, kind=case.goal.kind, p_goal=0.90, action=action,
                costates=Costates(lam_W=1.0, lam_E=1.0, lam_N=1.0, lam_H=1.0),
                exchange_rate=ExchangeRate(goal=case.goal.kind, networking_value=1.0, overtime_value=2.0),
                binding="drawable wealth", success=True)
    base.update(over)
    return CaseResult(**base)


# --- M74: the structure cannot hold a second household ------------------------------

def test_report_facts_has_no_field_that_can_hold_another_household():
    """The M74 guarantee expressed as a type. A cross-reference not in the context cannot be leaked from it."""
    names = {f.name for f in dataclasses.fields(ReportFacts)}
    forbidden = {"households", "peers", "peer_group", "comparison", "comparisons", "others",
                 "other_cases", "benchmark_households", "cohort", "average_household"}
    assert not (names & forbidden), f"a field able to hold another household appeared: {names & forbidden}"

    # And no field is a container OF the facts type, which would be the same leak by another route.
    for f in dataclasses.fields(ReportFacts):
        ann = str(f.type)
        assert "ReportFacts" not in ann, f"{f.name} nests ReportFacts, which permits cross-household content"


def test_facts_serialise_to_json_without_reaching_outside_the_household():
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case), schema_version="onb@0.1.1")
    blob = json.dumps(facts.to_dict(), ensure_ascii=False)
    # A cheap but real check: nothing in the payload names another case from the engine's own gallery.
    for other in ("Young professional", "Independence by fifty", "Near-retiree", "Entrepreneur",
                  "Tail shock", "Nicolas"):
        assert other not in blob


# --- a control on its bound is not advice -------------------------------------------

def test_consumption_at_its_floor_is_flagged():
    """The first P2 end-to-end conversion returned exactly this: C at 1 000 with theta at 1.0."""
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, action={"C": 1_000.0, "theta": 1.0}))
    codes = {w.code for w in facts.warnings}
    assert "control_at_lower_bound" in codes
    assert "control_at_upper_bound" in codes
    msgs = " ".join(w.message for w in facts.warnings)
    assert "starving spending" in msgs, "the warning must say what the corner solution MEANS"
    assert "corner" in msgs


def test_an_interior_action_raises_no_bound_warning():
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case))
    assert not {w.code for w in facts.warnings} & {"control_at_lower_bound", "control_at_upper_bound"}


# --- non-convergence is blocking, not a caveat --------------------------------------

def test_a_non_converged_solve_is_blocking_and_not_publishable():
    """An unconverged shortfall was measured wrong by a factor of four (52 687 against 13 267)."""
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, success=False))
    blocking = [w for w in facts.warnings if w.severity == "blocking"]
    assert [w.code for w in blocking] == ["solver_did_not_converge"]
    assert facts.publishable is False
    assert "factor of four" in blocking[0].message


def test_a_tail_of_one_scenario_or_fewer_blocks():
    """`eps * M <= 1` makes the SAA CVaR the worst single draw, so the certificate is not about a tail.

    `problem.py` forms it as `z + sum(max(L - z, 0)) / (eps * M)`. The denominator IS the expected number of
    scenarios in the tail. Measured over 400 random draws at `eps*M = 0.8`, the minimising `z` is the maximum
    and the tail term vanishes in 100% of them: the constraint reads "the worst of M is under the bound".

    Blocking at exactly 1.0 because that is arithmetic rather than a quality bar -- above it the constraint is
    a real if noisy tail average, and inventing a threshold there would be inventing a standard.
    """
    conv = case_from_submission(_submission())
    eps = conv.case.goal.epsilon

    degenerate = report_facts(conv.case, _result(conv.case),
                              engine_settings={"M_opt": int(1 // eps), "M_eval": 400})
    codes = {w.code for w in degenerate.warnings}
    assert "cvar_tail_degenerate" in codes
    assert degenerate.publishable is False

    # Four times the scenarios, same goal: a real tail, and the warning must not fire on it.
    fine = report_facts(conv.case, _result(conv.case),
                        engine_settings={"M_opt": int(4 // eps) + 4, "M_eval": 400})
    assert "cvar_tail_degenerate" not in {w.code for w in fine.warnings}


def test_non_convergence_says_which_of_the_two_it_is():
    """Both states block and only one of them is about the household, so the message may not collapse them.

    With `restore_converged` True the funding-maximising phase converged and found the goal within reach, and
    only the plan solve failed: the difficulty is the computation, not the goal. A household told just "the
    optimiser did not converge" would reasonably read its own goal as the problem. With the flag absent or
    False nothing is known and the extra sentence must not appear, because it would be a claim about a goal
    that was never determined.
    """
    conv = case_from_submission(_submission())

    ours = report_facts(conv.case, _result(conv.case, success=False,
                                           stats={"restore_converged": True}))
    msg = [w for w in ours.warnings if w.code == "solver_did_not_converge"][0].message
    assert "within reach" in msg and "not in the goal" in msg
    assert ours.publishable is False        # still blocking: no plan was certified

    unknown = report_facts(conv.case, _result(conv.case, success=False,
                                              stats={"restore_converged": False}))
    assert "within reach" not in [w for w in unknown.warnings
                                  if w.code == "solver_did_not_converge"][0].message


def test_an_unfundable_goal_blocks_the_plan_and_says_so_with_the_shortfall():
    """M79, and the user's decision of 5 August 2026: if a plan is not feasible, drop it and state that it is
    not within the limits.

    This is the case `solver_converged` cannot express — the solver converged and the answer is that the goal
    is out of reach — so it must not be reported as a solver problem, and it must not be reported as a plan.
    """
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, success=False, p_goal=0.31,
                                            outcome="goal_not_fundable", shortfall=65_924.0))
    blocking = [w for w in facts.warnings if w.severity == "blocking"]
    assert [w.code for w in blocking] == ["goal_not_fundable"], "an unfundable goal is not a convergence failure"
    assert facts.publishable is False, "there is no plan to publish, so the prose layer must refuse"
    assert facts.outcome == "goal_not_fundable"
    assert facts.shortfall == 65_924.0

    msg = blocking[0].message
    assert "not within the limits" in msg, "the client must be told the goal is out of reach, in those terms"
    assert "65 924" in msg, "the shortfall is converged and quotable, and it is the useful number"
    assert "No plan is issued" in msg
    assert "the goal — its size, its date, or the confidence" in msg, "say what CAN be changed"


def test_an_unfundable_goal_does_not_also_claim_a_convergence_failure():
    """The two were one branch before M79 (`if not result.success`), which read a determination as a defect."""
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, success=False, outcome="goal_not_fundable",
                                            shortfall=1_000.0))
    assert "solver_did_not_converge" not in {w.code for w in facts.warnings}


def test_a_low_confidence_on_a_fundable_goal_asserts_no_cause():
    """The clause "a statement about the goal's size and date" was asserted unconditionally and was wrong: the
    flagship scored 0.82 and 0.3025 on two scenario draws of the SAME household and goal, so on that path the
    cause was the draw. It survives only where the goal is genuinely unfundable, which the block above states."""
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, p_goal=0.40))
    low = [w for w in facts.warnings if w.code == "goal_below_required_confidence"][0]
    assert "goal's size and date" not in low.message
    assert "40%" in low.message and "85%" in low.message

    unfundable = report_facts(conv.case, _result(conv.case, success=False, p_goal=0.40,
                                                outcome="goal_not_fundable", shortfall=5_000.0))
    low2 = [w for w in unfundable.warnings if w.code == "goal_below_required_confidence"][0]
    assert "goal's size and date" in low2.message


def test_a_converged_solve_that_misses_its_target_is_a_caution_not_a_block():
    """Missing a target is a fact about the goal. It is publishable; it just needs saying."""
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case, p_goal=0.40))
    codes = {w.code for w in facts.warnings}
    assert "goal_below_required_confidence" in codes
    assert facts.publishable is True
    assert facts.meets_target is False


def test_an_undetermined_exchange_rate_is_reported():
    """Two zero values is how a non-converged solve presents: every costate is 0.0, so neither lever wins."""
    conv = case_from_submission(_submission())
    er = ExchangeRate(goal="fi", networking_value=0.0, overtime_value=0.0)
    assert er.winner == "undetermined", "guard the premise of this test"
    facts = report_facts(conv.case, _result(conv.case, exchange_rate=er))
    assert "exchange_rate_undetermined" in {w.code for w in facts.warnings}


# --- deferred inputs from P2 travel into the report ---------------------------------

def test_deferred_inputs_become_warnings_so_the_client_learns_what_was_not_used():
    conv = case_from_submission(_submission(
        params={"p_A": 40_000, "max_loss_pct": 15},
        goals=[{"kind": "fi", "description": "FI", "target_year": 2036, "confidence": 0.85},
               {"kind": "holiday_home", "description": "Ferienhaus", "target_year": 2030,
                "amount_chf": 900_000}],
    ))
    facts = report_facts(conv.case, _result(conv.case), deferred=conv.deferred, assumed=conv.assumed)
    not_modelled = [w for w in facts.warnings if w.code == "input_not_modelled"]
    assert len(not_modelled) == len(conv.deferred) >= 3
    joined = " ".join(w.message for w in not_modelled)
    assert "Ferienhaus" in joined and "p_A" in joined and "max_loss_pct" in joined
    # The structured lists survive too, for a renderer that wants them separately from the prose.
    assert facts.deferred == conv.deferred
    assert facts.assumed == conv.assumed


# --- the figures themselves ---------------------------------------------------------

def test_the_household_figures_are_the_submission_s_own():
    conv = case_from_submission(_submission())
    facts = report_facts(conv.case, _result(conv.case))
    assert facts.age == pytest.approx(52.0)
    assert facts.liquid == pytest.approx(400_000)
    assert facts.residence == pytest.approx(1_200_000)
    assert facts.let_property == pytest.approx(800_000)
    assert facts.pillar2 == pytest.approx(600_000)
    assert facts.pillar3a == pytest.approx(90_000)
    assert facts.net_worth == pytest.approx(1_600_000)
    # total_wealth includes the pension stocks; net_worth excludes them because they are wealth-tax exempt.
    assert facts.total_wealth > facts.net_worth
    assert facts.deadline_age == pytest.approx(62.0)
    assert facts.fi_requirement is not None and facts.fi_requirement > 0


def test_fi_requirement_is_absent_for_a_non_fi_goal():
    conv = case_from_submission(_submission(
        goals=[{"kind": "retirement", "description": "Pensionierung", "target_year": 2039,
                "confidence": 0.9}]))
    facts = report_facts(conv.case, _result(conv.case))
    assert facts.goal_kind == "retirement"
    assert facts.fi_requirement is None


# --- the subprocess entry point -----------------------------------------------------

@pytest.mark.slow
def test_befund_runs_end_to_end_on_preview_settings():
    out = befund(_submission(), settings=PREVIEW_SETTINGS)
    assert "publishable" in out, "the engine must state whether it stands behind these numbers"
    for key in ("age", "p_goal", "warnings", "deferred", "assumed", "engine_settings"):
        assert key in out
    assert out["engine_settings"]["M_opt"] == 8
    # JSON-serialisable, because it crosses a subprocess boundary as text.
    json.loads(json.dumps(out, ensure_ascii=False))


def test_default_settings_are_the_sound_ones_not_the_cheap_ones():
    """M70: at M_opt=8 the tail constraint does not bind reliably and the worked lives do not converge."""
    assert DEFAULT_SETTINGS["M_opt"] == 32
    assert PREVIEW_SETTINGS["M_opt"] == 8
    assert DEFAULT_SETTINGS["n_starts"] >= 3


def test_befund_refuses_a_bad_submission_rather_than_degrading():
    with pytest.raises(SubmissionError):
        befund(_submission(schema_version="onb@9.9.9"), settings=PREVIEW_SETTINGS)


@pytest.mark.slow
def test_the_reported_action_is_the_one_that_was_scored_and_is_admissible():
    """`run_case` reported `res.u0` while scoring the PROJECTED control, so the quoted probability described a
    different action than the one shown. Found via P3 on a real submission: `tau_Y = -13.74` (negative working
    time) and `theta = 5.34` (534% in the risky asset) were reported alongside a p_goal computed for a control
    projected into the simplex.

    This runs a case that is KNOWN not to converge at preview settings, because a converged solve returns an
    admissible iterate and the projection is a no-op — the bug is invisible on the happy path, which is why it
    survived.
    """
    from personal_alm.model.controls import Control

    out = befund(_submission(), settings=PREVIEW_SETTINGS)
    a = out["action"]
    u = Control(**a)
    assert u.is_admissible(), f"an inadmissible action reached the report: {a}"
    # The specific values the defect produced, asserted as ranges rather than as the old numbers.
    assert 0.0 <= a["tau_Y"] <= 1.0
    assert 0.0 <= a["theta"] <= 1.0
    assert a["C"] >= 1_000.0
    assert all(a[k] >= 0.0 for k in ("m_E", "m_N", "p_A"))
    # And the human-readable derivation cannot be nonsense: -13.74 became -1374 hours a week.
    assert 0.0 <= out["work_hours_per_week"] <= 168.0
