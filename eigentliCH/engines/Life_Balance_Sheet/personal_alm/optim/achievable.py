"""The largest goal this household CAN fund, when the one they asked for is out of reach.

    from personal_alm.optim.achievable import largest_fundable

    result = largest_fundable(case, probes=4)

**Why this exists, and what it deliberately does not change.** The rule of 5 August 2026 (M79) stands: if a plan
is not feasible, the engine drops it and says the goal is not within the household's limits. That rule is what
stopped the optimiser starving consumption to CHF 4 061 a year while reporting success. What it does not do is
answer the question every one of the three dossiers of 6 August 2026 ran into — *then what is within reach?* All
three households failed the same way: `G` came from the questionnaire's "spend later", which for two of them was
double their "spend now", and the engine could only say no.

So this is an ADDITION, not a replacement. The refusal is still issued and still carries its shortfall; this
returns a second number beside it. The author's decision, 9 August 2026.

**It is a Befund, not a Recommendation.** `client/onboarding.py` is right that a suggested target is a
recommendation about how much money somebody should want, and G7 requires a named Curator for that. What this
returns is a measurement — *this household's resources fund at most X at the confidence they asked for* — and
the report layer states it as a finding. Nothing here says anyone should want X.

**Two levers, and only two.** The amount, and the deadline capped at the reference age. Both were chosen by the
author on 9 August 2026, and the cap is the interesting half: a plan may say "not at 62, but at 65", and may
never say "work past 65". The cap is read from `Params.ahv_age` rather than written as 65 so that it follows the
model if the reference age ever moves. **Confidence is deliberately NOT a lever.** Lowering the confidence
demanded of a plan does not make the goal more affordable, it relabels the risk of missing it, and a household
that asked for 95% did so for a reason.

**Every probe is scored OUT OF SAMPLE.** The test is `p_goal >= confidence` from `run_case`, not the solver's
in-sample `outcome == "plan"`. That is not caution for its own sake: on two of the three real submissions the
optimiser returned `outcome="plan"` with the tail constraint satisfied on its own 32 scenarios and a goal reached
in **none** of 400 fresh ones. Bisecting on the in-sample flag would search for the largest goal that *looks*
fundable, which is the exact failure `report.plan_fails_out_of_sample` had to be written to catch.

**Probes are expensive and the budget is explicit.** One probe is a full two-phase multistart solve plus a
400-scenario evaluation. On a 26-year horizon that has been measured at over an hour, so the default budget is
small and the result says how many probes it used and whether it converged. A caller that gets
`converged=False` has a bracket, not an answer, and must say so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from ..cases import Case, run_case
from ..goals.spec import GoalSpec
from ..model.params import Params

#: Where each goal kind keeps the number this module moves.
_AMOUNT_KEY: dict[str, str] = {"fi": "G", "retirement": "G_ret", "home": "price", "company": "B_buffer"}

#: How a CVaR shortfall converts into a deficit in the goal's own amount units.
#:
#: This is the detail that would have made a reduced goal silently wrong, because **the slacks are not all in
#: the same units** and nothing in the codebase said so:
#:
#:   fi          `y_R·W_inv + swr·Ω_draw − G`     CHF/yr, and `G` enters with coefficient −1, so the shortfall
#:                                                IS the deficit in francs. Additive.
#:   retirement  `assets / (G_ret·af) − 1`        DIMENSIONLESS, a funding-ratio deficit. The amount enters the
#:                                                denominator, so the deficit in francs is `G_ret · s`. Relative.
#:   home        `min(deposit, serviceability)`   dimensionless, both terms divided by `price`. Relative.
#:   company     `min` of three normalised margins, the binding one being `(W_L − B)/B`. Relative.
#:
#: `report.ReportFacts.shortfall` documents itself as "annual CHF by which the goal is missed" and is fed the raw
#: CVaR, so for a retirement goal it has been reporting a ratio labelled as francs. That is fixed at the source
#: in `_solve_case_once`; this table is the single definition both paths use.
_SHORTFALL_IS_RELATIVE: dict[str, bool] = {"fi": False, "retirement": True, "home": True, "company": True}


def amount_deficit(kind: str, amount: float, cvar_shortfall: float) -> float:
    """A CVaR shortfall expressed in the goal's own amount units. See `_SHORTFALL_IS_RELATIVE`."""
    s = max(0.0, float(cvar_shortfall))
    return amount * s if _SHORTFALL_IS_RELATIVE.get(kind, True) else s


@dataclass(frozen=True)
class Achievable:
    """What this household can actually fund. Data for a report to state, never a sentence to repeat."""

    kind: str
    #: The amount as the household asked for it, and the deadline they asked for, in years from now.
    stated_amount: float
    stated_deadline_years: float
    #: Whether the goal AS STATED is funded at the required confidence. When true, everything below is the
    #: stated goal and there is nothing to reduce — the caller should say so rather than present a "reduction".
    stated_is_fundable: bool
    #: The largest amount funded at the required confidence, at the STATED deadline. `None` when even a probe at
    #: a small fraction of the goal failed, which is a statement about the solve rather than the household.
    largest_amount: float | None
    #: Its measured out-of-sample confidence, so a reader can see the margin rather than trust the label.
    largest_amount_p_goal: float | None
    #: The earliest deadline, in years from now, at which the FULL stated amount is funded — capped at the
    #: reference age. `None` when the cap does not help or there was no room to move (a goal already dated at or
    #: after the reference age has none).
    full_amount_deadline_years: float | None
    #: The cap itself, in years from now, and the age it came from. Reported so the constraint is visible.
    deadline_cap_years: float
    reference_age: float
    #: Bracket after the search: the largest amount known to work and the smallest known to fail.
    bracket_low: float | None
    bracket_high: float | None
    probes_used: int
    converged: bool
    #: Why the search stopped. Plain language, for a report to quote or a log to carry.
    note: str

    @property
    def reduction(self) -> float | None:
        """How much the amount had to come down, in the goal's own units."""
        return None if self.largest_amount is None else self.stated_amount - self.largest_amount


def _with_amount(goal: GoalSpec, amount: float) -> GoalSpec:
    key = _AMOUNT_KEY[goal.kind]
    return replace(goal, params={**goal.params, key: float(amount)})


def _amount_of(goal: GoalSpec, p: Params) -> float:
    key = _AMOUNT_KEY[goal.kind]
    return float(goal.params.get(key, p.G if key == "G" else 0.0))


def largest_fundable(
    case: Case,
    *,
    base_params: Params | None = None,
    probes: int = 4,
    tol_frac: float = 0.02,
    try_deadline: bool = True,
    run: Callable[..., object] | None = None,
    on_probe: Callable[[int, float, bool, float], None] | None = None,
    **run_kwargs,
) -> Achievable:
    """Search for the largest fundable amount, and for the earliest deadline that funds the full amount.

    `probes` bounds the number of solves the SEARCH may spend, over and above the one that establishes whether
    the stated goal is fundable at all. `tol_frac` stops the bisection once the bracket is within that fraction
    of the stated amount — 2% of a 300 000 goal is 6 000, which is finer than any of the inputs behind it.

    `run` exists so a test can drive this without an hour of IPOPT; it defaults to `run_case`.

    `on_probe(used, amount, funded, p_goal)` is called after each probe returns. It exists because each probe
    is a full solve and the whole search can outlive a timeout: a caller that records the bracket as it moves
    keeps an answer when the run is killed, where before an hour of solving was discarded entire. It must not
    raise -- a callback that fails would lose the search it was meant to preserve -- so it is called defensively.
    """
    runner = run or run_case
    p = case.params(base_params)
    goal = case.goal
    kind = goal.kind
    stated = _amount_of(goal, p)
    # **A search for the largest amount that holds AT A CONFIDENCE needs that confidence.** Reached without
    # one it would previously have raised a TypeError deep in the bisection; refusing here names the reason.
    if case.confidence is None:
        raise ValueError(
            "largest_fundable needs a required confidence: the search asks which amount holds AT a "
            "confidence, and a case whose confidence is measured rather than required has not set one."
        )
    confidence = float(case.confidence)
    cap_years = max(0.0, float(p.ahv_age) - float(case.x0.person.age))

    used = 0

    def probe(amount: float, horizon: float) -> tuple[bool, float, float]:
        """Run one case. Returns (funded, p_goal, cvar-derived deficit in amount units)."""
        nonlocal used
        used += 1
        g = replace(_with_amount(goal, amount), horizon_years=float(horizon))
        res = runner(replace(case, goal=g), base_params=base_params, **run_kwargs)
        deficit = amount_deficit(kind, amount, getattr(res, "shortfall", None) or 0.0)
        funded = res.p_goal >= confidence
        if on_probe is not None:
            # Defensive on purpose: a reporting callback that raises would destroy the very search it exists
            # to preserve, and there is nothing this function could usefully do about its caller's file.
            try:
                on_probe(used, float(amount), bool(funded), float(res.p_goal))
            except Exception:  # noqa: BLE001
                pass
        return funded, float(res.p_goal), deficit

    # --- is the goal fundable as stated? ------------------------------------------------------------
    ok, p_stated, deficit = probe(stated, goal.horizon_years)
    if ok:
        return Achievable(
            kind=kind, stated_amount=stated, stated_deadline_years=goal.horizon_years,
            stated_is_fundable=True, largest_amount=stated, largest_amount_p_goal=p_stated,
            full_amount_deadline_years=goal.horizon_years, deadline_cap_years=cap_years,
            reference_age=float(p.ahv_age), bracket_low=stated, bracket_high=None,
            probes_used=used, converged=True,
            note="the goal as stated is funded at the required confidence; nothing was reduced",
        )

    # --- seed from the shortfall, then bisect -------------------------------------------------------
    #
    # The seed is not a guess: for a retirement goal it is exact to the extent the plan is unchanged, since the
    # funding ratio is inversely proportional to the amount. It is also CONSERVATIVE in the right direction —
    # a smaller goal frees the optimiser to consume less and save more, so the true answer is at or above it.
    seed = max(0.0, stated - deficit) if deficit > 0.0 else stated * 0.5
    lo: float | None = None            # largest amount known to be funded
    hi: float = stated                 # smallest amount known to fail
    trial = min(max(seed, stated * 0.05), stated * 0.98)

    tol = tol_frac * stated
    converged = False
    note = "probe budget exhausted before the bracket closed"
    p_lo: float | None = None

    while used < probes + 1:
        ok, p_hat, _ = probe(trial, goal.horizon_years)
        if ok:
            lo, p_lo = trial, p_hat
        else:
            hi = trial
        if lo is not None and hi - lo <= tol:
            converged = True
            note = f"bracket closed to within {tol_frac:.0%} of the stated amount"
            break
        trial = (lo + hi) / 2.0 if lo is not None else hi / 2.0

    if lo is None:
        note = ("no probed amount was funded at the required confidence. That is a bracket, not an answer: "
                "the largest fundable amount is below the smallest amount tried.")

    # --- the deadline lever, capped at the reference age --------------------------------------------
    #
    # Only worth a probe when there is room: a goal already dated at or after the reference age has none, which
    # is the case for all three households of 6 August 2026 and is why this lever is quiet in practice. It
    # earns its place on an EARLY-retirement goal, where "not at 60, but at 65" is the honest answer.
    full_at: float | None = None
    if try_deadline and cap_years > goal.horizon_years + 0.5 and used < probes + 2:
        ok, _, _ = probe(stated, cap_years)
        if ok:
            full_at = cap_years

    return Achievable(
        kind=kind, stated_amount=stated, stated_deadline_years=goal.horizon_years,
        stated_is_fundable=False, largest_amount=lo, largest_amount_p_goal=p_lo,
        full_amount_deadline_years=full_at, deadline_cap_years=cap_years,
        reference_age=float(p.ahv_age), bracket_low=lo, bracket_high=hi,
        probes_used=used, converged=converged, note=note,
    )
