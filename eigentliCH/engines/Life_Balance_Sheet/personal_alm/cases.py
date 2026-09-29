"""Cases — the archetype *input* interface (book Part III, "Five lives").

A `Case` is an input: an initial state, a `GoalSpec`, and per-case parameter
overrides. `run_case` feeds it through the same engine (optimiser → feasibility →
binding-constraint read-out) and returns a `CaseResult`. The five book personas
are five instances of this one interface; any new life is just another `Case`.

Nicolas is therefore one result among five, not the product — the product is the
interface that turns any archetype into a calibrated result.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .goals.feasibility import feasibility
from .goals.spec import GoalSpec
from .model.controls import Control
from .model.dynamics import income
from .model.params import Params, earning_ceiling_for_scale
from .model.state import State
from .optim.mpc import apply_control, _project_admissible
from .optim.problem import Costates, ExchangeRate, solve_case
from .sim.montecarlo import constant_policy, simulate


@dataclass
class Case:
    name: str
    persona: str
    x0: State
    goal: GoalSpec            # the primary goal (drives the objective/insight)
    #: The confidence the household requires, or None to have it MEASURED instead of required. None is not
    #: zero: with a requirement the engine answers "does this hold at your confidence" and may refuse (M79);
    #: without one it answers "how confident does this turn out to be", which cannot fail because nothing was
    #: promised. Every calibrated case below names one, because a calibration target is a promise by
    #: definition.
    confidence: float | None
    param_overrides: dict = field(default_factory=dict)
    psi: float = 1.0
    notes: str = ""
    calibrated: bool = False   # True only where the case is fitted to its target
    extra_goals: list[GoalSpec] = field(default_factory=list)  # additional concurrent goals

    def params(self, base: Params | None = None) -> Params:
        return replace(base or Params(), **self.param_overrides)

    @property
    def age(self) -> float:
        """The household's age — read from the state, which is the only copy of it (M76).

        **This was a stored field until 4 August 2026, and it disagreed with the state for a day.** `age` became a
        state on step 1 with a default of 40.0, deliberately, so that every existing call site was unaffected and
        the plumbing change was provable as a no-op. But no case was ever updated to pass it, so all six ran at
        40 while declaring 28, 40, 60, 46, 44 and 45 — and `app/dashboard.py` labelled its charts from the stored
        field, so an axis read "age 60 → 65" for a household the engine aged 40 → 45. `app/inputs.py` had the
        same defect for live input: a user's typed age reached the persona string and no equation.

        A property rather than a field plus an assertion, because the two were the same fact stored twice and
        that is what let them diverge. An assertion detects the divergence; one source of truth prevents it.
        """
        return self.x0.person.age

    @property
    def goals(self) -> list[GoalSpec]:
        """All concurrent goals — the primary first (spec §12: active liabilities)."""
        return [self.goal, *self.extra_goals]


@dataclass
class CaseResult:
    name: str
    kind: str
    p_goal: float           # out-of-sample P(goal) under the optimal action
    action: dict
    costates: Costates
    exchange_rate: ExchangeRate
    binding: str            # which sub-condition binds at the deadline
    success: bool

    #: Why there is no plan, when there is none (M79). ``"plan"`` — a funded plan; ``"goal_not_fundable"`` — the
    #: goal cannot be met at its own ``epsilon`` even trying hardest, and ``shortfall`` says by how much;
    #: ``"undetermined"`` — the solve did not converge, so nothing numeric may be claimed. ``success`` is True
    #: only for ``"plan"``, so a caller reading it alone is never told a determination is a plan.
    outcome: str = "plan"

    #: Annual CHF shortfall in the worst ``epsilon`` tail, trying hardest. Set only for ``"goal_not_fundable"``,
    #: because a shortfall read off an unconverged solve was wrong by a factor of four (M75).
    shortfall: float | None = None

    #: The solve's own record, passed through rather than summarised. **Added 26 August 2026 because
    #: `undetermined` was arriving here with its cause already discarded.** It carries `restore_converged`,
    #: which separates "the solver could not answer" from "phase 1 says the goal is fundable and phase 2
    #: certified nothing anyway", and `s_star`/`cvar_bound`, which say what was being certified against. None
    #: of it is client-facing: `s_star` off an unconverged phase 1 may not be quoted (M79), and this field
    #: exists so a diagnosis can read it, not so a report can print it.
    stats: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """`outcome` defaults to `"plan"` for the callers that predate it, so the one combination that must not
        exist is `success=False` with `outcome="plan"`: no plan comes out of a solve that did not produce one.
        Repaired rather than raised, because the honest reading of an unlabelled failure is `undetermined` and a
        caller constructing one by hand should not have to know about this field to get a safe answer."""
        if not self.success and self.outcome == "plan":
            self.outcome = "undetermined"

    def summary(self) -> str:
        state = {"plan": "ok", "goal_not_fundable": "not fundable",
                 "undetermined": "no-converge"}.get(self.outcome, self.outcome)
        if self.outcome == "goal_not_fundable" and self.shortfall is not None:
            state = f"not fundable, short {self.shortfall:,.0f}/yr"
        return (f"{self.name:<14} {self.kind:<11} "
                f"P(goal)={self.p_goal:.0%}  binds: {self.binding:<14} "
                f"insight: {self.exchange_rate.winner} "
                f"{self.exchange_rate.ratio:.1f}x  "
                f"[{state}]")


# --- binding-constraint read-out (evaluated at the projected deadline state) -----

def _binding(goal: GoalSpec, terminal: State, u: Control, p: Params) -> str:
    pr = goal.params
    if goal.kind == "fi":
        return "drawable wealth"
    if goal.kind == "retirement":
        return "funding ratio"
    if goal.kind == "company":
        person = terminal.person
        margins = {
            "cash buffer": (terminal.wealth.W_L - pr["B_buffer"]) / max(pr["B_buffer"], 1.0),
            "network": (person.N - pr["N_min"]) / pr["N_min"],
            "expertise": (person.E.aggregate() - pr["E_min"]) / pr["E_min"],
        }
        return min(margins, key=margins.get)
    if goal.kind == "home":
        xi = pr.get("xi", p.xi)
        price = pr["price"]
        deposit = (terminal.wealth.W_L - xi * price) / price
        i_calc = pr.get("i_calc", p.i_calc)
        maint = pr.get("maint_rate", 0.01)
        aff = pr.get("affordability", 1.0 / 3.0)
        outlay = i_calc * (1.0 - xi) * price + maint * price
        serviceability = (aff * income(terminal, u, p) - outlay) / price
        return "deposit" if deposit < serviceability else "serviceability"
    return "goal"


def run_case(
    case: Case,
    *,
    base_params: Params | None = None,
    M_opt: int = 14,
    M_eval: int = 400,
    seed: int = 0,
    n_starts: int = 3,
    restore_starts: int = 2,
) -> CaseResult:
    """Run one case end-to-end: optimise this period's action, score the goal
    out-of-sample, and report the binding constraint."""
    p = case.params(base_params)
    # Semiannual steps up to a decade; yearly beyond, to keep the NLP small.
    dt_opt = 0.5 if case.goal.horizon_years <= 10.0 else 1.0

    res = solve_case(case.x0, case.goal, params=p, psi=case.psi,
                     extra_goals=case.extra_goals, dt_opt=dt_opt, M=M_opt, seed=seed,
                     n_starts=n_starts, restore_starts=restore_starts, max_iter=400)
    u0_admissible = _project_admissible(res.u0)
    action = apply_control(u0_admissible)

    goal = case.goal.to_goal()
    feas = feasibility(case.x0, constant_policy(action), goal, p,
                       n_scenarios=M_eval, seed=seed + 1)

    # Project deterministically to the deadline to read the binding sub-condition.
    n = max(1, int(round(case.goal.horizon_years / p.dt)))
    terminal = simulate(case.x0, constant_policy(action), p, n).final
    binding = _binding(case.goal, terminal, action, p)

    # **Report the action that was SCORED, not the raw iterate. Fixed 4 August 2026 (task P3).**
    #
    # This said `action=res.u0` while `p_goal` and `binding` above were computed from `action` — the projected,
    # admissible control. So the quoted probability described one action and the reported action was another. On a
    # non-converged solve the difference is not cosmetic: a real submission came back with `tau_Y = -13.74`
    # (negative working time) and `theta = 5.34` (534% in the risky asset), against a `p_goal` computed for a
    # control projected into the simplex. `_project_admissible` exists precisely so the loop "must never apply an
    # inadmissible action", and then the inadmissible one was the one handed to the caller.
    #
    # `res.u0` is still available on the `SolveResult` for anyone debugging the optimiser; what leaves this
    # function is what was measured.
    # **`p_goal` is still scored when the goal is unfundable, and it is not a plan's confidence (M79).** On that
    # path the action came from phase 1, which maximises funding rather than the household's life, so scoring it
    # answers the client's actual next question — "how close does trying hardest get?" — and nothing more. What
    # stops it being read as a plan is `outcome`, which the report layer turns into a blocking warning.
    outcome = res.stats.get("outcome", "plan" if res.success else "undetermined")
    return CaseResult(
        name=case.name, kind=case.goal.kind, p_goal=feas.p_hat,
        action=dict(u0_admissible),
        costates=res.costates, exchange_rate=res.exchange_rate,
        binding=binding, success=res.success,
        outcome=outcome, stats=dict(res.stats),
        shortfall=res.stats.get("shortfall_annual") if outcome == "goal_not_fundable" else None,
    )


# --- The five worked lives (book Part III) as inputs -----------------------------
# Each is an instance of the one framework (spec §12; book Ch. 12): a tuple of
# initial capitals, dated goals with confidences, and constraints. The old named
# personas (Maya, Jonas & Lena, Amara, David) were retired with the Worked-Lives
# rewrite; Nicolas is kept below as the calibrated flagship / backtest anchor but
# sits outside this gallery (he has his own special-case article).

YOUNG_PRO = Case(
    name="Young professional",
    persona="28 · technologist · high, market-correlated human capital",
    x0=State.individual(W_L=40_000, W_R=0, D=0, E=0.45, N=0.30, H=0.92, age=28.0),
    # A reachable early-independence target: the case is about the POLICY (build the
    # capitals, hold a defensive book), so the goal is set so the engine engages and
    # the build-vs-earn exchange rate is the story, not a pass/fail FI number.
    goal=GoalSpec(kind="fi", horizon_years=12.0, epsilon=0.35,
                  params=dict(G=55_000, swr=0.045, h_res=0.0)),
    confidence=0.65, psi=1.2, calibrated=True,
    param_overrides={"earning_power_max": earning_ceiling_for_scale(280_000)},  # strong technologist
    notes="HC >> W; the lever is building expertise and network (their S-curves are "
          "still steep), and holding a defensive financial book, not chasing Gain.",
)

INDEPENDENCE_50 = Case(
    name="Independence by fifty",
    persona="40 · mid-career · work by choice, not need",
    x0=State.individual(W_L=1_600_000, W_R=1_100_000, D=300_000, E=0.80, N=0.72, H=0.80, age=40.0),
    goal=GoalSpec(kind="fi", horizon_years=10.0, epsilon=0.15,
                  params=dict(G=120_000, swr=0.03, h_res=0.0)),
    confidence=0.85, psi=1.1, calibrated=True,
    param_overrides={"earning_power_max": earning_ceiling_for_scale(450_000)},
    notes="Fundable* = 120k/0.03 = 4.0m drawable; residence walled off (h_res=0); "
          "drawable wealth binds, not net worth.",
)

NEAR_RETIREE = Case(
    name="Near-retiree",
    persona="60 · approaching decumulation · horizon short, tail binding",
    x0=State.individual(W_L=1_600_000, W_R=1_400_000, D=100_000, E=0.82, N=0.75, H=0.68, age=60.0),
    goal=GoalSpec(kind="retirement", horizon_years=5.0, epsilon=0.10,
                  params=dict(G_ret=90_000, years_in_retirement=25.0, r_disc=0.02)),
    confidence=0.90, psi=1.2, calibrated=True,
    notes="Sequence risk: the tail constraint binds and glides the book toward "
          "protection and income; a modest encore closes any gap.",
)

ENTREPRENEUR = Case(
    name="Entrepreneur",
    persona="46 · founder · balance sheet dominated by one venture",
    x0=State.individual(W_L=300_000, W_R=2_500_000, D=600_000, E=0.85, N=0.70, H=0.72, age=46.0),
    goal=GoalSpec(kind="fi", horizon_years=8.0, epsilon=0.20,
                  params=dict(G=95_000, swr=0.035, h_res=0.15)),
    confidence=0.80, psi=1.0, calibrated=True,
    param_overrides={"earning_power_max": earning_ceiling_for_scale(300_000)},
    notes="Concentrated, illiquid venture; drawable liquidity binds, so the liquid "
          "sleeve should diversify away from the venture (Stabilization, Protection).",
)

TAIL_SHOCK = Case(
    name="Tail shock",
    persona="44 · a scenario, not a person · job loss / disability / health event",
    x0=State.individual(W_L=900_000, W_R=700_000, D=250_000, E=0.72, N=0.60, H=0.78, age=44.0),
    goal=GoalSpec(kind="fi", horizon_years=6.0, epsilon=0.15,
                  params=dict(G=80_000, swr=0.04, h_res=0.0)),
    confidence=0.85, psi=1.1, calibrated=True,
    # `w0` was retired on 3 August 2026 (step 2). This life is a documented high earner, and 340 000 of
        # earning power is **outside** the [50k, 250k] default range the CIO set — so the ceiling is raised for
        # this case rather than the figure being quietly clamped down to 250k.
        #
        # 436 666.67 is not arbitrary: it is the max for which
        # `min + (max - min) * at_unit = 50_000 + 386_666.67 * 0.75 = 340_000`, so this household earns exactly
        # what it earned before. That the default range cannot hold this person is worth noticing rather than
        # hiding — it is evidence the [50k, 250k] bound is a statement about typical clients, not all of them.
        param_overrides={"earning_power_max": earning_ceiling_for_scale(340_000), "W_buffer": 120_000},
    notes="High confidence makes the tail constraint dominate; the plan pre-positions "
          "a protection buffer sized to the worst-epsilon shortfall (see tail_shock_buffer).",
)

# The gallery of worked lives shown in the app and the Worked-Lives note.
WORKED_LIVES = [YOUNG_PRO, INDEPENDENCE_50, NEAR_RETIREE, ENTREPRENEUR, TAIL_SHOCK]
FIVE_LIVES = WORKED_LIVES  # back-compat alias (the app/tests iterate this list)


# --- Nicolas: the calibrated flagship + 26-year backtest anchor (special case) ---
# Kept in the codebase because the backtest and several tests depend on it, but it
# is NOT one of the shown worked lives; it has its own special-case article
# (Nicolas_special_case.md).

NICOLAS = Case(
    name="Nicolas", persona="45 · adviser, board member, educator · flagship",
    # `W_res = 1.0e6`: the 5m property is one fifth own use, per the author, 3 August 2026. So 4.0e6 is let and
    # yields rent; 1.0e6 is the residence and does not. Before the step-3 split the whole 5.0e6 was credited with
    # `y_R`, worth CHF 100 000/yr — of which CHF 20 000/yr was rent from the part he lives in, and that is the
    # portion this figure removes. Without it, `W_res` would default to the whole 5.0e6 and strip all 100 000.
    x0=State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, own_use_share=0.2,
                        age=45.0),
    # **`swr` 0.035 -> 0.030 on 26 August 2026, on the author's ruling (M88).** It is the rate M80 decision 5
    # ships as `Params.swr` and the rate §31.4.2 states for this case, and the goal's own rate had been left
    # behind when the model constant moved. Each case still states its own rate deliberately (0.045, 0.03,
    # 0.035, 0.04); this one is no longer among the ones that differ from the model.
    #
    # **The requirement this case computes is 1 333 333, and the book's §31.4.2 says 2 300 000.** That is not a
    # disagreement to reconcile in code: the author confirmed on 26 August that the property is one fifth own
    # use, so the book's figure is posed on a property about half lived in, which is a different household. At
    # this split the engine puts age fifty short by about 8 455 a year against the book's 46 271. Fifty remains
    # unfundable, which is §31.4.2's conclusion; every figure under it changes, which is M80 decision 4's work.
    goal=GoalSpec(kind="fi", horizon_years=5.0, epsilon=0.10,
                  params=dict(G=120_000, swr=0.030, h_res=0.0)),
    confidence=0.90, calibrated=True,
    notes="Net worth ample, drawable wealth binding; time and health the limiter.",
)


def tail_shock_buffer(
    case: Case, *, income_off_years: float = 1.0, liability_bump: float = 0.0,
    M_eval: int = 400, seed: int = 0, base_params: Params | None = None,
) -> dict:
    """Size the pre-positioned protection buffer for the tail-shock case (book Ch. 17,
    eq. 17.1):  B + hedge >= (ΔL − Δfundable)_tail  at the ε quantile.

    We estimate the worst-ε drop in fundable wealth from a shock that switches labour
    income off for ``income_off_years`` (a job-loss / disability proxy), add any rise
    in liabilities ``liability_bump``, and return the buffer that covers it. This is a
    principled, illustrative sizing, not a re-solve of the shocked problem."""
    p = case.params(base_params)
    x = case.x0
    G = case.goal.params.get("G", p.G)
    # A job-loss / disability shock switches LABOUR income off for the window;
    # passive income (property yield) continues. The spending stream and debt
    # service do not stop, so the buffer must plug the net cash gap in the tail.
    u = Control(tau_Y=0.5, tau_E=0.05, tau_N=0.05, tau_H=0.2,
                C=G, m_E=0, m_N=0, p_A=0.0, theta=0.3)
    labour_lost = income(x, u, p) * income_off_years        # Δfundable driver
    passive = p.y_R * x.wealth.W_inv + p.y_hol * x.wealth.W_hol                         # let share only (step 3); continues through the shock
    debt_service = p.i * x.wealth.D
    gap_per_year = max(0.0, G + debt_service - passive)
    need = gap_per_year * income_off_years + liability_bump  # (ΔL − Δfundable)_tail
    provisioned = case.param_overrides.get("W_buffer", 0.0)
    return {
        "case": case.name,
        "labour_income_lost": round(labour_lost),
        "net_cash_gap_per_year": round(gap_per_year),
        "buffer_required": round(need),
        "buffer_provisioned": round(provisioned),
        "covered": provisioned >= need,
    }
