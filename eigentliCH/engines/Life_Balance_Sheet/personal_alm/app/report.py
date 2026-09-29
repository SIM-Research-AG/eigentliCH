"""Task P3: the facts a report may state, and the warnings that must travel with them.

**Two requirements shape this file, and both are constraints rather than features.**

**M74 — a report may never reference another household.** A dossier disclosed a second client's debt level on
4 August 2026, and the durable fix is structural rather than editorial: `ReportFacts` has no field that can hold a
second household. Not "other households redacted" — *absent*. A cross-reference that is not in the context cannot
be leaked from it, which is a far stronger guarantee than instructing a writer, human or model, not to make one.
`test_report.py` asserts the shape, because the rule has to survive someone adding a "comparison" field later.

**A control sitting on its bound is not advice.** The first end-to-end P2 conversion returned `C` pinned at its
1 000 floor with `theta` at 1.0, because that household's independence requirement is about 3.43m of drawable
wealth against 400k. The optimiser is behaving correctly — it starves consumption chasing an unreachable goal —
and printing "spend CHF 1 000 a year" would be the report layer repeating a corner solution as a recommendation.
So bounds are detected here and reported as `Warning`s, and a caller that renders facts while ignoring warnings is
using this module wrongly.

**Nothing here is a Recommendation.** A *Befund* is education; G7 requires a named Curator and a Decision Record
before advice exists. This module produces figures and caveats, never an instruction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..cases import Case, CaseResult
from ..model.controls import Control
from ..model.params import Params
from ..ui.output import fi_drawable_requirement, hours_per_week, saving_rate

#: Control bounds worth reporting when an action sits on them. Values mirror `optim.problem`'s admissibility
#: constraints and `mpc._project_admissible`; each entry is (name, low, high, why it matters if it binds).
_CONTROL_BOUNDS: tuple[tuple[str, float | None, float | None, str], ...] = (
    ("C", 1_000.0, None,
     "consumption is pinned at its floor: the optimiser is starving spending to chase a goal it cannot reach, "
     "which is a diagnosis of the goal and not a spending plan"),
    ("theta", 0.0, 1.0,
     "the portfolio is at a corner (fully in or fully out of the risky asset), so the tilt is a boundary artefact "
     "rather than a chosen balance"),
    ("tau_Y", 0.0, 0.70,
     "working time is at its limit, so the plan depends on sustaining the maximum admissible workload"),
    ("tau_H", 0.05, None,
     "rest is at its floor, which the health equation will punish over any horizon longer than the plan's"),
)


@dataclass(frozen=True)
class Warning_:
    """Something a reader must be told before believing a figure."""

    code: str
    severity: str  # "blocking" | "caution"
    message: str


@dataclass(frozen=True)
class ReportFacts:
    """Everything a report may state about ONE household. Deliberately flat and deliberately closed.

    There is no field here that can hold a second household, a peer group, a comparison or an average, and that is
    the M74 guarantee expressed in a type rather than in a review checklist.
    """

    # --- provenance ---------------------------------------------------------------------------------
    schema_version: str
    collected: str
    engine_settings: dict[str, Any]

    # --- the household, as given -------------------------------------------------------------------
    age: float
    net_worth: float
    total_wealth: float
    drawable: float
    liquid: float
    real_assets: float
    residence: float
    let_property: float
    debt: float
    pillar2: float
    pillar3a: float

    # --- the goal ----------------------------------------------------------------------------------
    goal_kind: str
    goal_horizon_years: float
    deadline_age: float
    #: What the household demanded, or None when nothing was demanded. **None is not "zero required", it is a
    #: different question.** With a requirement the engine answers "does this hold at your confidence"; without
    #: one it answers "how confident does this turn out to be". The first can fail and be refused (M79); the
    #: second cannot fail, because nothing was promised. Collapsing them onto 0.0 would let a report claim a
    #: goal was met when no target existed.
    required_confidence: float | None
    goal_params: dict[str, Any]

    # --- what the engine found ---------------------------------------------------------------------
    p_goal: float
    #: None when no confidence was required. A boolean here would have to be True or False, and both are
    #: claims about a target that does not exist.
    meets_target: bool | None
    solver_converged: bool
    binding_constraint: str
    exchange_rate_winner: str
    exchange_rate_ratio: float

    # --- this period's action ----------------------------------------------------------------------
    action: dict[str, float]
    work_hours_per_week: float
    saving_rate: float

    # --- context for the goal, so a reader can see the size of the gap -----------------------------
    fi_requirement: float | None

    # --- whether there is a plan at all, and why not when there is none (M79) ----------------------
    #
    # Defaulted, and placed after every required field, because a dataclass may not put a defaulted field
    # ahead of an undefaulted one. `solver_converged` cannot express the middle case: on
    # `goal_not_fundable` the solver converged perfectly and the answer is that the goal is out of reach.
    outcome: str = "plan"

    #: Annual CHF by which the goal is missed in its worst ``epsilon`` tail, trying hardest. None unless
    #: ``outcome == "goal_not_fundable"``.
    shortfall: float | None = None

    #: The goal's own CVaR tail fraction. Carried because `shortfall` is an average over *this* fraction of
    #: scenarios and a report that names the wrong one misstates what the number measures — it is not a fixed
    #: decile, it differs per goal.
    goal_epsilon: float = 0.0

    # --- what IS within reach, when the stated goal is not (9 August 2026) -------------------------
    #
    # **This does not soften `goal_not_fundable`; it stands beside it.** The rule of 5 August 2026 holds — a
    # goal out of reach is reported as out of reach, with its shortfall — and the author's decision of 9 August
    # adds the second half of the answer, which the three dossiers of 6 August all needed and none could give:
    # *then what is within reach?*
    #
    # **It is a measurement, not a target.** `client/onboarding.py` is right that a suggested goal is a
    # recommendation about how much money somebody should want, and G7 reserves recommendations for a named
    # Curator. What is stated here is what this household's resources fund at the confidence THEY asked for.
    # A report may say "your means fund X"; it may not say "you should aim at X", and the difference is not
    # decoration — it is which side of the regulated wall the sentence falls on.
    #
    #: The largest amount funded at the required confidence, in the goal's own units, and its measured
    #: out-of-sample confidence. `None` when no search was run or none of the probed amounts held.
    achievable_amount: float | None = None
    achievable_p_goal: float | None = None
    #: The earliest deadline, in years from now, at which the FULL stated amount is funded — capped at the
    #: reference age, because a plan may say "not at 62, but at 65" and may never say "work past 65".
    achievable_full_deadline_years: float | None = None
    #: How the search ended, so a reader can tell a closed bracket from an exhausted budget. A caller that
    #: prints `achievable_amount` while ignoring this can present an unconverged bracket as an answer.
    achievable_converged: bool = False
    achievable_probes: int = 0
    achievable_note: str = ""

    # --- everything the reader must be told --------------------------------------------------------
    warnings: list[Warning_] = field(default_factory=list)
    deferred: list[tuple[str, str]] = field(default_factory=list)
    assumed: list[tuple[str, Any, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-ready. The transport for the subprocess seam and for the browser."""
        return asdict(self)

    @property
    def publishable(self) -> bool:
        """False when any warning is blocking. A caller that renders anyway is doing so knowingly."""
        return not any(w.severity == "blocking" for w in self.warnings)


def _bound_warnings(action: dict[str, float]) -> list[Warning_]:
    out: list[Warning_] = []
    for name, lo, hi, why in _CONTROL_BOUNDS:
        v = action.get(name)
        if v is None:
            continue
        # Absolute tolerance, because these are shares and money on different scales and a relative test would
        # treat a 1 000-franc floor and a 0..1 share identically.
        if lo is not None and abs(v - lo) <= max(1e-6, abs(lo) * 1e-6):
            out.append(Warning_("control_at_lower_bound", "caution", f"{name} is at its minimum ({v:g}): {why}"))
        if hi is not None and abs(v - hi) <= 1e-6:
            out.append(Warning_("control_at_upper_bound", "caution", f"{name} is at its maximum ({v:g}): {why}"))
    return out


def report_facts(
    case: Case,
    result: CaseResult,
    *,
    deferred: list[tuple[str, str]] | None = None,
    assumed: list[tuple[str, Any, str]] | None = None,
    engine_settings: dict[str, Any] | None = None,
    schema_version: str = "",
    collected: str = "",
    achievable: Any | None = None,
) -> ReportFacts:
    """Assemble the facts for one household, with the warnings that must travel with them."""
    p = case.params(None)
    x0 = case.x0
    w = x0.wealth
    u = Control(**{k: result.action[k] for k in
                   ("tau_Y", "tau_E", "tau_N", "tau_H", "C", "m_E", "m_N", "p_A", "theta")})

    warnings: list[Warning_] = []

    # A non-converged solve is BLOCKING, not a caveat. The flagship's unconverged phase 1 reported a shortfall of
    # 52 687 against a true 13 267 -- a four-fold error -- so an unconverged figure is not a rough figure.
    # **The three outcomes are distinct, and only one of them is a solver problem (M79).** Before 5 August 2026
    # this read `if not result.success`, which collapsed "the optimiser broke" together with "the optimiser
    # worked and the goal is out of reach" — and the second is not a caveat about the figures, it is the answer.
    outcome = getattr(result, "outcome", "plan" if result.success else "undetermined")

    if outcome == "undetermined":
        # **Which of the two it is, since 26 August 2026.** `undetermined` covers two states that give a
        # household opposite information. If the funding-maximising phase did not converge either, nothing is
        # known. If it DID converge and found the goal within reach, and the plan solve then certified nothing,
        # the failure is ours and the goal is not the problem — and a household told only "the optimiser did not
        # converge" would reasonably conclude their goal was the difficulty. Neither case issues a plan.
        detail = ("" if getattr(result, "stats", {}).get("restore_converged") is not True else
                  " What is known: the funding-maximising solve DID converge and found this goal within reach at "
                  "its own confidence. It is the plan itself that could not be certified, so the difficulty is in "
                  "the computation and not in the goal.")
        warnings.append(Warning_(
            "solver_did_not_converge", "blocking",
            "the optimiser did not converge, so these figures come from an unfinished solve and are not a "
            "quantitative statement about this household. An unconverged shortfall has been observed to be wrong "
            "by a factor of four, not by a rounding error." + detail))

    # **An unfundable goal is BLOCKING, and it blocks the plan rather than the figures.** The user's decision of
    # 5 August 2026: if a plan is not feasible, drop it and state that it is not within the limits. So there is
    # no action to publish — the control shown came from the funding-maximising phase, not from a plan for this
    # household's life — while the shortfall itself is a converged, quotable number and the most useful thing
    # the engine can say. Blocking is what stops the prose layer writing a plan over it (`prose.py` refuses on
    # `publishable = False`), which is exactly the right refusal here.
    if outcome == "goal_not_fundable":
        short = getattr(result, "shortfall", None)
        amount = f"about CHF {short:,.0f} a year".replace(",", " ") if short else "an amount the solve quantified"
        warnings.append(Warning_(
            "goal_not_fundable", "blocking",
            f"this goal is not within the limits of this household's resources at the confidence it asks for. "
            f"Even on the funding-maximising plan, the worst {case.goal.epsilon:.0%} of scenarios fall short by "
            f"{amount}. No plan is issued, because every plan that meets the goal is infeasible and a plan that "
            f"misses it is not the plan that was asked for. What can be changed is the goal — its size, its date, "
            f"or the confidence demanded of it — or the resources brought to it."))

    # **A plan that funds the goal in NO scenario is not a plan, whatever the in-sample constraint says.**
    # Measured 5 August 2026 on a real submission: at `M_opt=24` the engine returned `outcome="plan"`,
    # `success=True`, `publishable=True` — and `p_goal = 0.0000` against a required 0.95, with consumption
    # starved to CHF 4 061 a year against a stated spending of 90 000. The in-sample CVaR constraint held at its
    # bound; out of sample the plan funded the goal in none of 400 draws.
    #
    # That divergence is M70's lesson at the scoring layer rather than the solver layer: a constraint satisfied
    # on the draw it was optimised against is not a claim about the household. `goal_below_required_confidence`
    # is the right warning for a goal that is merely hard — 0.47 against 0.90 is a real plan missing a demanding
    # target — but it is a caution, and a caution is not what "works in zero scenarios" deserves.
    #
    # The threshold is deliberately not a quality bar. It fires at *no* successful scenario, which needs no
    # judgement about how much confidence is enough: whatever the household asked for, a plan that never once
    # delivers it is a different kind of object from a plan that usually does.
    # **THE TAIL THE CVaR IS AVERAGED OVER CAN BE LESS THAN ONE SCENARIO, and then the certificate does not
    # mean what it says.** `problem.py` forms the CVaR the standard way, `z + sum(max(L - z, 0)) / (eps * M)`.
    # That denominator is the expected number of scenarios in the tail, and when it drops to one or below the
    # minimising `z` is the worst draw and the tail term vanishes: the constraint becomes "the WORST of M
    # scenarios is under the bound", not "the mean of the worst eps-fraction is". Measured 26 August 2026 over
    # 400 random draws at `eps*M = 0.8`: the SAA CVaR equalled the worst single draw in 100% of them.
    #
    # This is arithmetic, not a quality threshold, which is why it blocks at 1.0 and nothing is invented above
    # it. At `M_opt = 8` it catches exactly the cases whose epsilon is 0.10 -- and M87 measured one of those
    # certifying with `p_goal = 0.000` against a required 0.90, which is what a certificate against a single
    # draw is worth out of sample.
    m_opt = (engine_settings or {}).get("M_opt")
    eps = getattr(case.goal, "epsilon", None)
    if m_opt and eps and eps * float(m_opt) <= 1.0:
        warnings.append(Warning_(
            "cvar_tail_degenerate", "blocking",
            f"the tail this plan was certified against is {eps * float(m_opt):.1f} scenarios, not a tail: at "
            f"{int(m_opt)} scenarios and a confidence of {1 - eps:.0%} the constraint reduces to the single "
            f"worst draw, so what held is that one scenario and not the {eps:.0%} of outcomes it stands for. "
            f"The figures are not wrong; the certificate behind them is a weaker claim than it appears, and "
            f"nothing here should be read as a statement about the tail."))

    if outcome == "plan" and result.p_goal <= 0.0:
        n_eval = (engine_settings or {}).get("M_eval")
        scored_on = f"{int(n_eval)} fresh scenarios" if n_eval else "a fresh set of scenarios"
        # The comparison is only made where a requirement exists. A plan that reaches the goal in none of
        # 400 fresh scenarios is blocking either way -- that is the point of the warning -- but naming a
        # "required 0 %" would be inventing the target.
        against = (f", against a required {case.confidence:.0%}" if case.confidence is not None
                   else " -- and the confidence here was measured rather than required, so this is what the "
                        "measurement says")
        warnings.append(Warning_(
            "plan_fails_out_of_sample", "blocking",
            f"the optimiser produced a plan and the plan does not work: scored on {scored_on} it "
            f"reaches the goal in none of them{against}. The tail constraint "
            f"held on the scenarios the plan was computed against and fails on scenarios it has not seen, which "
            f"means the figures describe that particular sample rather than this household. No action is "
            f"published from it."))

    warnings.extend(_bound_warnings(result.action))

    # **Only where a confidence was actually required.** With `case.confidence` None the measured p_goal is the
    # answer rather than a shortfall against a target, and a "below required" caution would be inventing the
    # target it complains about.
    if case.confidence is not None and result.p_goal < case.confidence:
        # **The causal clause was wrong and had to go (M79).** It read "That is a statement about the goal's size
        # and date, not about the household's conduct" — asserted unconditionally. Measured on the flagship, the
        # same household with the same goal scored 0.82 and 0.3025 on two scenario draws, so on that path the
        # cause was the draw, and the sentence explained a correct number with a wrong reason. Where the goal is
        # genuinely unfundable the size-and-date reading IS right, and the warning above says so. Elsewhere this
        # states the number and stops.
        cause = (" That is a statement about the goal's size and date, not about the household's conduct."
                 if outcome == "goal_not_fundable" else "")
        warnings.append(Warning_(
            "goal_below_required_confidence", "caution",
            f"the goal is reached in {result.p_goal:.0%} of scenarios against a required {case.confidence:.0%}."
            + cause))

    if result.exchange_rate.winner in ("undetermined", ""):
        warnings.append(Warning_(
            "exchange_rate_undetermined", "caution",
            "the earn-versus-network comparison is unavailable: the costates come back zero when the dual "
            "extraction is skipped, which happens when the solve does not converge."))

    for what, why in (deferred or []):
        warnings.append(Warning_("input_not_modelled", "caution", f"not modelled: {what} — {why}"))

    fi_req = None
    if case.goal.kind == "fi":
        fi_req = float(fi_drawable_requirement(x0, p, case.goal.params.get("G")))

    return ReportFacts(
        schema_version=schema_version,
        collected=collected,
        engine_settings=dict(engine_settings or {}),
        age=float(x0.person.age),
        net_worth=float(x0.net_worth),
        total_wealth=float(x0.total_wealth),
        drawable=float(w.drawable(h_res=case.goal.params.get("h_res", 0.0),
                                 q_inv=p.q_inv, q_hol=p.q_hol)),
        liquid=float(w.W_L),
        real_assets=float(w.W_R),
        residence=float(w.W_res or 0.0),
        let_property=float(w.W_inv),
        debt=float(w.D),
        pillar2=float(w.W_P),
        pillar3a=float(w.W_3a),
        goal_kind=case.goal.kind,
        goal_horizon_years=float(case.goal.horizon_years),
        deadline_age=float(x0.person.age + case.goal.horizon_years),
        required_confidence=(None if case.confidence is None else float(case.confidence)),
        goal_params=dict(case.goal.params),
        p_goal=float(result.p_goal),
        meets_target=(None if case.confidence is None
                      else bool(result.p_goal >= case.confidence)),
        solver_converged=bool(result.success),
        outcome=outcome,
        shortfall=(float(getattr(result, "shortfall", None)) if outcome == "goal_not_fundable"
                   and getattr(result, "shortfall", None) is not None else None),
        goal_epsilon=float(case.goal.epsilon),
        achievable_amount=(float(achievable.largest_amount)
                           if achievable is not None and achievable.largest_amount is not None else None),
        achievable_p_goal=(float(achievable.largest_amount_p_goal)
                           if achievable is not None and achievable.largest_amount_p_goal is not None
                           else None),
        achievable_full_deadline_years=(float(achievable.full_amount_deadline_years)
                                        if achievable is not None
                                        and achievable.full_amount_deadline_years is not None else None),
        achievable_converged=bool(getattr(achievable, "converged", False)),
        achievable_probes=int(getattr(achievable, "probes_used", 0)),
        achievable_note=str(getattr(achievable, "note", "")),
        binding_constraint=result.binding,
        exchange_rate_winner=result.exchange_rate.winner,
        exchange_rate_ratio=float(getattr(result.exchange_rate, "ratio", 0.0) or 0.0),
        action={k: float(v) for k, v in result.action.items()},
        work_hours_per_week=float(hours_per_week(result.action["tau_Y"])),
        saving_rate=float(saving_rate(x0, u, p)),
        fi_requirement=fi_req,
        warnings=warnings,
        deferred=list(deferred or []),
        assumed=list(assumed or []),
    )
