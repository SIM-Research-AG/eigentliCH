"""Consumer output layer (spec §14 / book Chapter 14–18 case surface).

Hide all the math; surface only what a person acts on:
  - a goal gauge (the Monte-Carlo P(goal));
  - the work-optional date, paired with drawable vs total net worth so the
    illiquidity gap is visible at a glance;
  - this period's action, in plain words;
  - one insight — the top exchange rate (§13);
  - an early warning if any P(goal) has slipped below target, with the lever.

Everything here is formatting and light computation over values the engine has
already produced; no modelling happens in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..goals.feasibility import feasibility
from ..goals.goals import fi_goal
from ..model.controls import Control
from ..model.dynamics import income
from ..model.params import Params
from ..model.state import State
from ..sim.montecarlo import ControlPolicy, constant_policy

# A nominal productive week, only for turning time-shares into "hours/week".
# 100 h/week: waking hours less commuting, chores, admin and non-discretionary family duties.
# Decided 3 August 2026 (M67), correcting 50.0. The old value halved every hour figure this module displayed,
# and it was incoherent with 	au_Y_star = 0.50, which would have put the overwork threshold at 25 h/week.
_PRODUCTIVE_WEEK_HOURS = 100.0


def tilt_language(theta: float) -> str:
    if theta < 0.25:
        return "a conservative equity tilt"
    if theta < 0.55:
        return "a moderate equity tilt"
    return "an aggressive equity tilt"


def saving_rate(state: State, u: Control, p: Params) -> float:
    """s = (inflow − C) / inflow — an output, never an input (spec §3, Chapter 1).

    Inflow is total cash in: labour income plus the asset yield y_R·W_inv. Using
    labour income alone understates saving for someone whose inflow is mostly
    asset yield (exactly the Nicolas case), so total inflow is the honest base.

    `W_inv`, not `W_R`, since 3 August 2026 (step 3) — a residence pays no rent, so counting it here inflated
    the denominator and *understated* the saving rate for anyone with a large home.
    """
    inflow = income(state, u, p) + p.y_R * state.wealth.W_inv + p.y_hol * state.wealth.W_hol
    if inflow <= 0:
        return 0.0
    return max(0.0, min(1.0, (inflow - u.C) / inflow))


def fi_drawable_requirement(state: State, p: Params, G: float | None = None) -> float:
    """Drawable wealth required at the target date (eq. 7.8), net of what LET property yields:
    Ω_draw ≥ (G − y_R·W_inv) / swr.

    **This docstring said "the residence's operating yield" until 3 August 2026, which was the error.** A
    residence has no operating yield to contribute, and `W_inv` is what this function nets, which is why the
    split between let and lived-in decides the answer.

    **The sentence that followed was itself withdrawn on 26 August 2026 (M88).** It said the book's eq. 29.17
    nets a whole five-million-franc property "with the property being the home", turning 4.0m into 2.3m.
    `BOOK_REVISION_01_independence.md` §0 had already overturned that reading: the book's property is mixed, and
    its 2.3m is arithmetically 2.55m of let property at a 2% yield. What is now settled is which household the
    flagship is — the author confirmed one fifth own use — so the book's 2.3m describes a different split from
    the case's, and this function returns 1 333 333 for the flagship. The defect the book does carry is a
    notation one, `y_R W_R` where eqs. 29.16 and 29.17 mean `y_R W_R^inv`.
    """
    G = p.G if G is None else G
    net_of_yield = G - (p.y_R * state.wealth.W_inv + p.y_hol * state.wealth.W_hol)
    return max(0.0, net_of_yield / p.swr)


def hours_per_week(share: float) -> float:
    return share * _PRODUCTIVE_WEEK_HOURS


def plain_language_action(state: State, u: Control, p: Params) -> str:
    """The applied u_0 as a sentence (spec §14)."""
    parts = [f"work {u.tau_Y * 100:.0f}% of your productive time"]
    if u.tau_N > 0.02:
        parts.append(f"{hours_per_week(u.tau_N):.0f} h/week networking")
    if u.tau_E > 0.02:
        parts.append(f"{hours_per_week(u.tau_E):.0f} h/week building expertise")
    parts.append(f"save {saving_rate(state, u, p) * 100:.0f}%")
    parts.append(f"hold {tilt_language(u.theta)}")
    if u.p_A > 1.0:
        parts.append(f"pay CHF {u.p_A:,.0f}/yr to the mortgage")
    return "This period: " + ", ".join(parts) + "."


@dataclass
class WorkOptional:
    age: float | None          # earliest age P(FI) clears the target, or None
    confidence: float
    drawable_now: float
    drawable_required: float
    net_worth_now: float

    @property
    def illiquidity_gap(self) -> float:
        """How far total net worth exceeds drawable wealth — the trap made visible."""
        return self.net_worth_now - self.drawable_now


def work_optional_age(
    x0: State,
    policy: ControlPolicy,
    p: Params | None = None,
    *,
    from_age: float,
    latest_age: float = 65.0,
    confidence: float = 0.90,
    G: float | None = None,
    M: int = 400,
    seed: int = 0,
    step: float = 1.0,
) -> WorkOptional:
    """Earliest age at which P(FI) under `policy` clears the confidence target
    (spec §14). Scans candidate dates and reports the first crossing, alongside
    drawable-vs-total net worth today."""
    p = p or Params()
    G = p.G if G is None else G

    found: float | None = None
    age = from_age + step
    while age <= latest_age + 1e-9:
        goal = fi_goal(G=G, swr=p.swr, h_res=p.h_res,
                       horizon_years=age - from_age, epsilon=1.0 - confidence)
        r = feasibility(x0, policy, goal, p, n_scenarios=M, seed=seed)
        if r.p_hat >= confidence:
            found = round(age, 2)
            break
        age += step

    return WorkOptional(
        age=found, confidence=confidence,
        drawable_now=x0.wealth.drawable(h_res=p.h_res),
        drawable_required=fi_drawable_requirement(x0, p, G),
        net_worth_now=x0.net_worth,
    )


def render_period(period, p: Params | None = None, *, confidence: float = 0.90) -> str:
    """Render a PeriodOutput (from the MPC loop) as the §14 consumer summary."""
    p = p or Params()
    state, u = period.state, period.action
    lines: list[str] = []
    lines.append(f"── Life Balance Sheet · age {period.age:.1f} " + "─" * 24)

    # Goal gauge.
    gauge = _bar(period.p_fi_oos)
    flag = "on track" if period.p_fi_oos >= confidence else "BELOW TARGET"
    lines.append(f"Financial independence   {gauge} {period.p_fi_oos:.0%}"
                 f"  (target {confidence:.0%} — {flag})")

    # Drawable vs total net worth — the illiquidity gap.
    draw = state.wealth.drawable(h_res=p.h_res)
    req = fi_drawable_requirement(state, p)
    lines.append(f"Net worth CHF {state.net_worth:,.0f}   ·   "
                 f"Drawable CHF {draw:,.0f}   (need ~CHF {req:,.0f})")

    # This period's action.
    lines.append("")
    lines.append(plain_language_action(state, u, p))

    # One insight (the top exchange rate).
    xr = period.exchange_rate
    lines.append(f"Insight: an hour of {xr.winner} moves you toward FI "
                 f"~{xr.ratio:.1f}× faster than the alternative.")

    # Early warning.
    if period.warning:
        lines.append(f"⚠  {period.warning} — lever: {period.lever}")

    return "\n".join(lines)


def _bar(p: float, width: int = 20) -> str:
    filled = int(round(max(0.0, min(1.0, p)) * width))
    return "[" + "█" * filled + "·" * (width - filled) + "]"
