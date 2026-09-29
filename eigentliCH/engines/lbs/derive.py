"""Deriving the mandate from the household's own position.

Implements the v1 of `architecture/DESIGN_snapshot_to_mandate.md`. What is derived, what is policy, and what is
deliberately absent:

| Field | Source | Why |
|---|---|---|
| target curve, level | the required return that funds the goal | the household's own requirement, not a typed-in number |
| target curve, slope | CIO policy (`TARGET_CURVE_FLOOR`/`CEILING`) | a mandate should ask less of a crisis; no household model here implies how much less |
| position caps | the goal buffer against each block's crisis loss | per instrument, severity read from the ReturnSet |
| liquidity bounds | the goal's deadline | a near deadline forces reachable wealth |
| currency bounds | the goal's own currency | a CHF goal implies a CHF floor |
| region, role, capital type, phase, asset class | CIO policy | not derivable from a household model |
| ESG floor | household preference | not derivable either, and says so |

**The curve slopes across the states, and the shape is policy while the level stays derived.** Superseded the
flat curve on 2 August 2026 (`DECISIONS.md` M50). A flat curve asked the same return of a crisis and a boom,
which no mandate should: it penalises a Protection sleeve for behaving as its role intends.

**The span in use is ±2.5 points, narrowed from the ±12.5 first specified.** The wide ramp was built and then
measured, and the measurement is why it is not the one shipped — see the sweep below.

**A sloped curve does not improve weight leverage, and the first version of this note claimed it would.** That
claim was measured and is false. Holding the expectation fixed and widening the ramp, leverage falls
monotonically:

| ramp span | state 0 | state 24 | weight leverage | objective | states met | void |
|---|---|---|---|---|---|---|
| 0pp (flat) | +8.80% | +8.80% | +0.1913% | 563 | 12/25 | 0 |
| **5pp (in use)** | **+6.30%** | **+11.30%** | **+0.1704%** | 580 | **13/25** | **0** |
| 10pp | +3.80% | +13.80% | +0.1518% | 629 | 13/25 | 1 |
| 25pp (first specified) | −3.70% | +21.30% | +0.1096% | 968 | 11/25 | 5 |
| 40pp | −11.20% | +28.80% | +0.0775% | 1515 | 11/25 | 5 |

Measured on `hh-0012` over the published ReturnSet, every curve level-shifted to the same house-view
expectation, so they differ only in shape. Widening the ramp raises the objective's *level* faster than it
raises the weights' influence on it, because the shortfall it adds sits in boom states no allocation can
reach — the `void` column. So the slope is justified on its own merits as a sanity property of a mandate, and
**M25 is untouched by it.** Anyone reading a state-varying curve as progress on weight leverage has it
backwards.

The row in use is the one that meets the most states and voids none. Note that it is not the row with the
highest leverage: flat still wins on that, and flat is the thing being deliberately given up.

The curve is now a **linear ramp from `TARGET_CURVE_FLOOR` to `TARGET_CURVE_CEILING` across the 25 states,
level-shifted so that its expectation under the ReturnSet's own house view equals the household's required
return.** Two claims, kept apart on purpose:

- **The level is still derived.** The shift is chosen so `E_omega[curve] == required_return` exactly. The
  household's goal still sets what the portfolio must earn in expectation, which is what M4 and M14 were for.
- **The shape is CIO policy, and is not derived from anything.** It says a mandate should ask less of a crisis
  than of a boom. The household model cannot supply that, because its regime seam is still a no-op (M5). So the
  slope sits in a named module constant beside `POLICY_BOUNDS`, not in a formula pretending to derive it.

`state_dependent` is therefore now True, and the contract's `_flat_curve_is_actually_flat` validator enforces
that the flag and the numbers agree in either direction.

**What this does not claim.** It does not make the target reachable in every state: at the span in use the top
of the ramp exceeds what any allocation over this universe can deliver in five of the 25 states. Those states
are counted on every derivation and reported in the notes, because a shortfall an allocation cannot remove is a
statement about the goal rather than about the weights, and a reader comparing fit qualities needs to know how
much of one is which.

**Why this does not depend on the household solve.** The curve's level comes from the S-curve engine's
`required_return`, which is closed-form bisection over the goal's own accumulation and touches `personal_alm`
not at all. The **costate ratios** do depend on the solve, so they are carried as an *ambition signal* and
reported with a caveat rather than being allowed to move the curve.

M11's three solver failures were **fixed on 1 August 2026** and `personal_alm` is 58 passed, 0 failed. The
separation above is kept anyway, because it is the right shape and not because the solve is broken: a mandate
whose target depended on a numerical optimisation would inherit that optimisation's convergence as a
correctness risk, and this one does not. What M11 now carries is a modelling question, not a defect: the
in-sample confidence target is met at 0.85 because no converged solve reaches 0.90, and the margin is one
scenario wide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from contracts.base import BoundSource, Provenance, Reliability, Sourced
from contracts.references import RegimeRef
from contracts.snapshot import (
    BalanceSheetSnapshot,
    Bound,
    Costates,
    DerivedMandate,
    GoalRef,
    HouseholdPosition,
    MandateCurve,
    PositionCap,
)
from engines.s_curve_trajectory.engine import STEPS_PER_YEAR, project, required_return

#: The curve is expressed annually, because that is the basis the ReturnSet is estimated on. Distinct from the
#: goal's deadline: see the BalanceSheetSnapshot validator.
CURVE_HORIZON_YEARS: float = 1.0

#: CIO-owned investment policy for the dimensions a household model cannot derive. A first set, so a snapshot
#: can carry a complete mandate; the real ones belong to the Investment Committee (DESIGN section 5.5).
#: **Widened on 2 August 2026 with the cut to eight instruments (DECISIONS.md M60), by CIO decision.** The
#: Protection ceiling went 0.35 -> 0.50 and the 0.25 `Alternative` cap was removed outright. The reason is that
#: the eight-instrument universe changed what those bounds bind on. Gold, Long Volatility and Trend Following
#: are all classed `Alternative`, and they are also where this universe's positive expected return lives, so a
#: 25 percent class cap and a 35 percent role cap together forced the residual into CHF cash at +1.41 percent
#: — a bound written against a 54-block register quietly became the binding constraint on an eight-block one.
#: Widening is therefore a correction to a stale bound, not a loosening of prudence.
#: **Role floors added 3 August 2026 (DECISIONS.md M63), and they are the fix for a real pathology.** Until
#: then only Protection carried a minimum, so a portfolio holding *no equity at all* broke no rule. With both
#: position caps removed and the return assumption iterated to a fixed point, the Optimiser found exactly that
#: corner: 50% Long Volatility Index and 50% Trend Following, zero Gain, zero Income, for every household. Legal
#: under the old bounds, verified arithmetically at an 11.86% expected return, and not a portfolio anyone should
#: be advised into.
#:
#: The floors were proposed by this module and **confirmed by the CIO on 3 August 2026** — "the role floor as
#: proposed", together with the Protection ceiling staying at 0.50. They force a balanced book without dictating
#: instruments: the floors sum to 45%, leaving 55% for the fit to place, and the ceilings sum to 200% so the set
#: is comfortably feasible.
#:
#: **The Protection ceiling of 0.50 is a decision that is now load-bearing, and should be read that way.** At
#: this ceiling the fixed point puts exactly 50% into the Long Volatility Index, and that single position is what
#: carries `hh-0012` and `hh-0013` over their goals (M63). Both were confirmed knowing this. If the ceiling is
#: ever lowered, expect both to stop being funded — that is the intended sensitivity, not a fragility to fix.
#:
#: One consequence to keep in view: the eight-instrument register carries exactly **one** Income block (id 18,
#: CHF Corporate Loans IG), so an Income floor is a floor on that single instrument rather than on a category
#: with alternatives. That is a fact about the register, not about the bound, and it argues for a second Income
#: instrument more than it argues against the floor.
POLICY_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "role": {
        "Protection": (0.05, 0.50),
        "Gain": (0.20, 0.70),
        "Income": (0.10, 0.40),
        "Stabilisation": (0.10, 0.40),
    },
    "asset_class": {"Cash": (0.0, 0.40)},
}

#: Bounds the derived per-instrument caps from above. The goal cannot see why concentration is imprudent for
#: reasons beyond itself.
#:
#: **Set to 1.0 — no policy cap — on 2026-08-02 by CIO decision (DECISIONS.md M60).** It was 0.25, and at
#: eight instruments that stopped being a diversification limit and became the allocation. 1 / 0.25 = 4, so at
#: least four positions had to sit *exactly* at the cap to fill the budget, and the objective's only remaining
#: freedom was which four. Measured: the curve fit and the mean-variance comparison returned the same weights
#: to 1e-16 — two different objectives made indistinguishable by a bound written for a 54-block register.
#:
#: **What still constrains an allocation, so this is not "unconstrained".** The derived per-instrument caps
#: below are unchanged and still bind wherever the goal buffer is thin, since they come from each block's
#: crisis-state loss rather than from policy. So do the role floors and ceilings in `POLICY_BOUNDS`, the CHF
#: currency floor, the liquidity floor from the goal's deadline, and the asset-class bounds.
#:
#: **What it now permits, stated plainly.** Where none of those bind, a single instrument may reach 100 percent.
#: That is a real change in what the Optimiser is allowed to return and it is the CIO's call, not the model's;
#: if the intent was "higher than 0.25" rather than "no cap", this is the one number to revisit.
DEFAULT_POLICY_CAP: float = 1.0

#: The target curve's shape, as an offset from the required return in the worst state and in the best.
#: **CIO policy, not derived.**
#:
#: These two numbers are the whole of the shape: the 25 points are linear between them and then shifted as a
#: block so the curve's expectation under the house view equals the household's required return. Nothing about a
#: household determines the slope, so it lives here rather than being computed from something that only looks
#: like it implies it. Because the house view's probability-weighted mean state is exactly the midpoint of the
#: axis, a symmetric pair like this one leaves the shift equal to the required return itself.
#:
#: **Why ±2.5 points and not the ±12.5 first asked for.** The instruction was a ramp from −15% to +10%, a
#: 25-point span. That was built, measured and narrowed, because the wide span cost weight leverage without
#: buying anything: holding the expectation fixed, leverage falls monotonically as the ramp widens, from
#: +0.1913% flat to +0.1096% at 25pp to +0.0775% at 40pp. Widening raises the objective's *level* faster than
#: the weights' influence over it, because the extra shortfall lands in boom states no allocation can reach.
#:
#: 5pp is the measured best trade: it introduces the asymmetry, meets **13 of 25** states — one more than flat
#: and more than any wider span — creates **no** arithmetically void states, and keeps leverage at +0.1704%.
#: The full sweep is in `DECISIONS.md` M50. Change these two numbers and the whole chain follows; run the sweep
#: again rather than assuming a wider ramp is a stricter mandate, because it is not.
TARGET_CURVE_FLOOR: float = -0.025
TARGET_CURVE_CEILING: float = 0.025

#: How much of the goal buffer a single position may consume if it suffers its crisis loss. A judgement, and the
#: one named in DESIGN section 5.3 as needing the CIO.
BUFFER_SHARE_PER_POSITION: float = 1.0

#: Liquidity classes ordered most to least reachable. Order is load-bearing for the deadline rule below.
LIQUIDITY_LADDER: tuple[str, ...] = ("Daily", "Quarterly", "Yearly", "Decade")


@dataclass(frozen=True)
class DerivationInputs:
    """Everything the derivation needs, gathered so it is one inspectable object."""

    household_id: str
    W_L: float
    W_R: float
    D: float
    h_res: float = 0.0
    E: float | None = None
    N: float | None = None
    H: float | None = None

    goal_kind: str = "fi"
    goal_mode: str = "at_deadline"
    target: float = 0.0
    horizon_years: float = 10.0
    epsilon: float = 0.10
    annual_contribution: float = 0.0

    currency: str = "CHF"
    esg_min: float = 0.0

    #: The return the household is assumed to earn, when a *measured* one is available.
    #:
    #: `None` means "use `_expected_return`", the role-bounded proxy of M59. That proxy answers "what is the
    #: best an admissible portfolio could earn", which is deliberately an upper bound and explicitly not a
    #: forecast — it ignores the currency, liquidity, region and per-instrument caps the Optimiser also faces.
    #:
    #: The fixed-point iteration (M63) fills this in: pass 0 runs with `None` and uses the proxy as a seed,
    #: then each later pass supplies the *actual* regime-weighted return of the allocation the Optimiser chose
    #: under the previous pass's mandate. So the buffer, the derived caps and the target curve's level all
    #: come to rest on a return the portfolio can really deliver rather than on a bound it cannot reach.
    #:
    #: Keep the proxy as the seed rather than starting from a guess: it is the tightest defensible starting
    #: point available before any allocation exists, and starting closer means fewer passes.
    expected_return_override: float | None = None

    policy_cap: float = DEFAULT_POLICY_CAP
    policy_bounds: Mapping[str, Mapping[str, tuple[float, float]]] = field(
        default_factory=lambda: POLICY_BOUNDS
    )

    #: Costates from the household solve, when available. Carried as an ambition signal only (M11).
    lam_W: float | None = None
    lam_E: float | None = None
    lam_N: float | None = None

    as_of: str = "2024-12-31"

    @property
    def drawable(self) -> float:
        return self.W_L + self.h_res * (self.W_R - self.D)


def derive_snapshot(
    inputs: DerivationInputs,
    regime: RegimeRef,
    returnset_payload: Mapping[str, Any],
    universe: Sequence[int] | None = None,
) -> tuple[BalanceSheetSnapshot, list[str]]:
    """Derive a BalanceSheetSnapshot, mandate included.

    Args:
        inputs: The household's position and goal.
        regime: The Regime this snapshot is computed under. Stamped, and checked downstream.
        returnset_payload: The published ReturnSet, for each block's crisis-state return and its metadata.
        universe: Restrict the investable set. Defaults to every block in the ReturnSet.

    Returns:
        The snapshot and the notes a reader must have.
    """
    notes: list[str] = []
    blocks = list(returnset_payload.get("building_blocks", []))
    if not blocks:
        raise ValueError("the ReturnSet carries no building blocks, so no mandate can be derived")
    if universe is not None:
        wanted = set(int(b) for b in universe)
        blocks = [b for b in blocks if int(b["bb_id"]) in wanted]
        if not blocks:
            raise ValueError(f"none of the requested universe {sorted(wanted)} is in the ReturnSet")

    # ---- the curve -------------------------------------------------------
    steps = max(1, int(round(inputs.horizon_years * STEPS_PER_YEAR)))
    contributions = [inputs.annual_contribution / STEPS_PER_YEAR] * steps
    r_star = required_return(inputs.drawable, inputs.target, inputs.horizon_years, contributions)

    if r_star is None:
        raise ValueError(
            f"the goal of {inputs.target:,.0f} in {inputs.horizon_years:g} years is not reachable from "
            f"{inputs.drawable:,.0f} drawable at any plausible return, so no required return exists and no "
            f"mandate can be derived from it. Five levers move this, and no allocation is one of them: "
            f"a longer horizon, higher income, a higher saving rate, more starting wealth, or a smaller "
            f"goal. Allocation cannot manufacture a return the market does not offer."
        )
    if r_star == 0.0:
        notes.append(
            "the goal is already funded by drawable wealth and contributions at a zero return, so the required "
            "return is zero and the mandate is capital preservation rather than growth. An authored curve "
            "routinely gets this case wrong by asking for growth the household does not need."
        )

    points, shape_mean, shift = _state_curve(r_star, returnset_payload)
    curve = MandateCurve(
        points=points,
        required_return=r_star,
        epsilon=inputs.epsilon,
        horizon_years=CURVE_HORIZON_YEARS,
        state_dependent=True,
        derivation=(
            f"a linear ramp from {TARGET_CURVE_FLOOR:.0%} to {TARGET_CURVE_CEILING:.0%} across the 25 states "
            f"(CIO policy shape), shifted as a block so its expectation under the ReturnSet's house view equals "
            f"the required return from the S-curve engine's closed-form bisection (derived level)"
        ),
    )
    notes.append(
        f"the target curve slopes from {points[0]:.4%} in state 0 to {points[-1]:.4%} in state 24, and its "
        f"expectation under the house view is {r_star:.4%} — the annual return this household's goal requires, "
        f"to within floating point. The shape is the policy ramp "
        f"{TARGET_CURVE_FLOOR:.0%}..{TARGET_CURVE_CEILING:.0%}, whose own house-view expectation is "
        f"{shape_mean:.4%}, so the level shift applied was {shift:+.4%}. The level is derived from the goal; "
        f"the slope is not derived from anything and is CIO policy. See DECISIONS.md M50, superseding the flat "
        f"curve of M5."
    )

    # Whether the curve is *reachable* is a separate question from whether it is derived, and it is measurable
    # rather than arguable: compare each point against the best single-block return available in that state.
    # This is deliberately generous — a real allocation is a convex combination and cannot beat its best
    # constituent, and the position caps forbid holding one block outright — so a state counted as reachable
    # here is only "not arithmetically void", which is the weaker claim actually being made.
    unreachable = _states_above_envelope(points, blocks)
    if unreachable:
        notes.append(
            f"the target exceeds the best single-block return available in {len(unreachable)} of "
            f"{len(points)} states, the lowest being state {unreachable[0]}. In those states no allocation "
            f"can meet the curve, so the shortfall there is a property of the goal rather than of the "
            f"weights. This is reported because a level-shifted curve preserves the goal and therefore "
            f"inherits its reachability: a goal needing {r_star:.2%} a year cannot be made attainable by "
            f"reshaping the target, only by changing the goal, the horizon, the contributions or the return "
            f"estimates. Reshaping changes *where* the shortfall falls, which is what gives the weights "
            f"leverage; it cannot remove shortfall the goal itself requires. DECISIONS.md M50."
        )
    else:
        notes.append(
            f"the target is at or below the best single-block return available in every one of {len(points)} "
            f"states, so the curve is not arithmetically void anywhere. That is a weaker statement than "
            f"attainable: a real allocation is a convex combination under position caps and cannot reach its "
            f"best constituent."
        )

    # ---- the buffer, and the per-instrument caps --------------------------
    #
    # The buffer must be measured at the return the household can *expect*, not at the return the goal
    # *requires*. Projecting at `r_star` gives a terminal value equal to the target by construction, so the
    # buffer would be identically zero and no cap could ever be derived from it. That was a real defect in the
    # first version of this module, found by running it.
    #
    # The expected return comes from the published ReturnSet under its own house view. Two sources, in order of
    # preference:
    #
    #   1. `inputs.expected_return_override`, when the caller has a *measured* allocation return — the
    #      fixed-point iteration's later passes (M63). This is the honest answer: the return of the portfolio
    #      the Optimiser actually chose under this mandate.
    #   2. `_expected_return`, the role-bounded best-admissible proxy (M59), used when no allocation exists yet.
    #
    # **The circularity is real and this is how it is broken.** The portfolio's true expected return depends on
    # weights the Optimiser has not chosen, and those weights depend on the mandate this function derives. The
    # first version of this module cut the knot with an equal weighting across the universe and called it
    # neutral; M59 showed that was a standing bet against the house view rather than neutrality. The proxy is
    # now the *seed* of an iteration rather than a substitute for the answer, which is the right shape: a fixed
    # point resolves the circle instead of pretending it is not there.
    if inputs.expected_return_override is not None:
        expected = float(inputs.expected_return_override)
        notes.append(
            f"the return assumption is {expected:.4%}, measured from the allocation the Optimiser chose under "
            f"the previous pass's mandate rather than proxied. The buffer, the derived caps and the curve's "
            f"level therefore rest on a return this portfolio can deliver, not on an upper bound it cannot "
            f"reach. DECISIONS.md M63."
        )
    else:
        expected = _expected_return(blocks, returnset_payload)
    for role, floor in _bounds_without_a_role(blocks):
        if floor > 0.0:
            notes.append(
                f"the mandate's {role} floor of {floor:.0%} cannot be met: no block in this universe carries "
                f"that role. The buffer below is measured without it, and the Optimiser will refuse the "
                f"mandate rather than approximate it. Either widen the universe or drop the floor."
            )
        else:
            notes.append(
                f"the mandate's {role} cap does not apply: no block in this universe carries that role. "
                f"Harmless, and recorded so the bound is not read as having constrained something."
            )
    projected = project(
        initial_wealth=inputs.drawable,
        target=inputs.target,
        horizon_years=inputs.horizon_years,
        annual_return=expected,
        contributions=contributions,
    )
    buffer = projected.final_value - inputs.target
    feasible = buffer >= -1e-6
    notes.append(
        f"the goal needs {r_star:.4%} a year; the best allocation this mandate permits offers {expected:.4%} "
        f"under the ReturnSet's house view — roles filled best-first under the CIO role bounds, not an equal "
        f"weighting of every block. So the projected terminal wealth is {projected.final_value:,.0f} against a "
        f"target of {inputs.target:,.0f}, a buffer of {buffer:,.0f}. The buffer is measured at the expected "
        f"return rather than the required one, because at the required return it is zero by construction. Read "
        f"{expected:.4%} as an upper bound rather than a forecast: it respects the role bounds but ignores the "
        f"currency, liquidity, region and per-instrument caps the Optimiser also faces. DECISIONS.md M59."
    )

    caps: dict[int, float] = {}
    if feasible and buffer > 0:
        compounding = (1.0 + r_star) ** inputs.horizon_years
        for block in blocks:
            crisis = float(block["profile_by_state"][0])
            severity = max(-crisis, 0.0)
            if severity <= 1e-9:
                # No crisis loss to bound against: the goal imposes no limit, so policy does.
                caps[int(block["bb_id"])] = inputs.policy_cap
                continue
            headroom = buffer * BUFFER_SHARE_PER_POSITION / (
                severity * inputs.drawable * compounding
            )
            caps[int(block["bb_id"])] = min(max(headroom, 0.0), inputs.policy_cap)

        # A cap set that cannot fill the budget is not a risk limit, it is an infeasible mandate.
        #
        # Added 2026-08-02 (DECISIONS.md M60). The derived-cap branch had not been exercised by any roster
        # household since M47, so this had never been reachable. When `hh-0013` crossed into funded it
        # derived a cap of 4.15% on each of eight instruments — 33.2% of the budget — and the Optimiser then
        # returned weights near 12.5%, which is that cap set renormalised. It also reported
        # `conditions_met: "yes"`. The caps were arithmetically unsatisfiable and were silently discarded.
        #
        # The CIO's instruction is that no such cap is wanted ("we don't need a 4.15% cap"), so the branch
        # now checks its own feasibility and declines to impose a cap set it knows cannot be met. A thin
        # buffer is reported as a thin buffer rather than encoded as a constraint nobody can satisfy.
        #
        # This does not fix the Optimiser accepting and then ignoring `max_single_position` while reporting
        # conditions met. That is a separate defect, recorded in the open items, and it merely stops biting
        # here because this no longer hands it an impossible cap.
        #
        # **The quantity to test is the tightest cap, not the sum.** A first version of this check summed the
        # caps, which is the wrong test and passed: four of the eight blocks have a non-negative crisis return
        # (gold +50%, long volatility +40%, trend following +10%, cash +1%), so their severity is zero and
        # their cap is the policy value, taking the sum well above 1. The infeasibility comes from the
        # collapse to a scalar further down — the Optimiser's schema takes one number, so the *smallest*
        # per-instrument cap is applied to every instrument. That is what makes it binding, and that is what
        # has to be feasible: `min(caps) x len(caps) >= 1`.
        tightest = min(caps.values()) if caps else inputs.policy_cap
        reachable = tightest * len(caps)
        if caps and reachable < 1.0:
            notes.append(
                f"the goal buffer of {buffer:,.0f} implies a tightest per-instrument cap of {tightest:.2%}, "
                f"and because the Optimiser takes a single scalar that cap applies to all {len(caps)} "
                f"instruments — a maximum of {reachable:.1%} of the portfolio, which cannot fill it. No "
                f"derived cap is imposed and policy applies instead. The buffer is thin rather than the "
                f"allocation being concentrated, and a cap that cannot be satisfied is an infeasible mandate "
                f"rather than a risk limit: the Optimiser discards it, renormalises, and reports success. "
                f"Read the buffer, not a cap. DECISIONS.md M60."
            )
            caps = {}
        else:
            notes.append(
                f"the position caps are derived per instrument from each block's published crisis-state return "
                f"against a goal buffer of {buffer:,.0f}, bounded above by the policy cap of "
                f"{inputs.policy_cap:.0%}. The tightest is {tightest:.2%}, which applied to all {len(caps)} "
                f"instruments still reaches {reachable:.1%} of the portfolio, so the budget can be filled. "
                f"Severity is read from the ReturnSet, not assumed."
            )
    else:
        notes.append(
            f"the projected path reaches {projected.final_value:,.0f} against a target of "
            f"{inputs.target:,.0f}, so the buffer is {buffer:,.0f} and the goal is not reachable on the "
            f"required return. The caps therefore fall back to the policy value: a negative buffer means the "
            f"goal does not work, not that nothing should be held. Five levers close a gap this size, and "
            f"choosing a different allocation is not among them: a longer horizon, higher income, a higher "
            f"saving rate, more starting wealth, or a smaller goal. The advice conversation belongs there, "
            f"not in the portfolio — which is why this is reported rather than optimised away."
        )

    position_cap = PositionCap(
        per_instrument=caps, policy_cap=inputs.policy_cap, derived=bool(caps)
    )

    # ---- bounds ----------------------------------------------------------
    bounds: dict[str, dict[str, Bound]] = {}

    liquidity_floor = _liquidity_floor(inputs.horizon_years)
    if liquidity_floor:
        bounds["liquidity"] = liquidity_floor
        floor_total = sum(b.lower for b in liquidity_floor.values())
        notes.append(
            f"a {inputs.horizon_years:g} year deadline forces {floor_total:.0%} into reachable liquidity "
            f"classes. Derived from the goal, because the household model separates liquid from illiquid "
            f"wealth precisely so a deadline can be tested against what is actually reachable."
        )

    bounds["currency"] = {
        inputs.currency: Bound(lower=0.5, upper=1.0, source=BoundSource.DERIVED)
    }
    notes.append(
        f"a floor of 50 percent in {inputs.currency} follows from the goal being denominated in it: currency "
        f"risk against a fixed liability is not diversification."
    )

    for dimension, categories in inputs.policy_bounds.items():
        bounds[dimension] = {
            label: Bound(lower=low, upper=high, source=BoundSource.POLICY)
            for label, (low, high) in categories.items()
        }
    notes.append(
        "region, role, capital type, phase and asset-class bounds are CIO investment policy, not derivable "
        "from a household model. They carry source 'policy' so a reader can tell them from the household's own "
        "economics."
    )

    mandate = DerivedMandate(
        curve=curve,
        position_cap=position_cap,
        bounds=bounds,
        esg_min=inputs.esg_min,
        reporting_currency=inputs.currency,
        universe=tuple(int(b["bb_id"]) for b in blocks),
    )

    # ---- costates, as an ambition signal only ----------------------------
    costates = Costates(
        lam_W=inputs.lam_W if inputs.lam_W is not None else 0.0,
        lam_E=inputs.lam_E,
        lam_N=inputs.lam_N,
    )
    if inputs.lam_W is None:
        notes.append(
            "no costates were supplied, so the ambition signal is unavailable. The curve does not depend on "
            "them: its level comes from the S-curve's closed-form required return, so this derivation is "
            "independent of whether the household solve converged at all. See DECISIONS.md M11."
        )
    else:
        ratio = costates.portfolio_over_expertise()
        if ratio is not None and ratio < 1.0:
            notes.append(
                f"the marginal value of expertise exceeds that of portfolio wealth (ratio {ratio:.2f}), so this "
                f"household is better served investing in itself than reaching for portfolio return. The "
                f"mandate should be read as deliberately unambitious."
            )
        notes.append(
            "the costates come from the household optimiser. Its solver failures were fixed on 1 August 2026 "
            "and the costates are now validated (lam_W 5.39e-05, lam_H 16.21, winner overtime, ratio 5), so "
            "the ambition signal is usable. Two limits remain: a non-converged solve reports "
            "ExchangeRate.winner as \"undetermined\" rather than a confident verdict, and the goal's "
            "confidence target is met at 0.85 rather than 0.90. See DECISIONS.md M11."
        )

    provenance = Provenance(
        source="life_balance_sheet (derived mandate v1)",
        as_of=inputs.as_of,
        model_version="lbs-derive@0.1.0",
        reliability=Reliability.DERIVED,
        unit="fraction",
    )

    snapshot = BalanceSheetSnapshot(
        as_of=inputs.as_of,
        model_version="lbs-derive@0.1.0",
        household_id=inputs.household_id,
        position=HouseholdPosition(
            W_L=inputs.W_L, W_R=inputs.W_R, D=inputs.D, h_res=inputs.h_res,
            E=inputs.E, N=inputs.N, H=inputs.H,
        ),
        goal=GoalRef(
            kind=inputs.goal_kind,
            mode=inputs.goal_mode,
            horizon_years=inputs.horizon_years,
            epsilon=inputs.epsilon,
            target=inputs.target,
            buffer=buffer,
            feasible=feasible,
        ),
        costates=costates,
        mandate=mandate,
        regime=regime,
        diagnostics={
            "drawable": Sourced(value=inputs.drawable, provenance=provenance),
            "required_return": Sourced(value=r_star, provenance=provenance),
            "projected_terminal_wealth": Sourced(
                value=projected.final_value, provenance=provenance
            ),
            "goal_buffer": Sourced(value=buffer, provenance=provenance),
        },
        notes=tuple(notes),
    )
    return snapshot, notes


def _states_above_envelope(
    points: Sequence[float],
    blocks: Sequence[Mapping[str, Any]],
) -> tuple[int, ...]:
    """Which states ask more than the best single block in the universe returns there.

    A convex combination cannot exceed its largest constituent, so a target above this envelope is unreachable
    by *any* allocation, caps or no caps. That makes this a one-sided test worth having: states it flags are
    definitely void, states it clears are merely not-definitely-void.

    Returns the flagged state indices in order, empty if the curve clears the envelope everywhere.
    """
    flagged: list[int] = []
    for s, target in enumerate(points):
        best = None
        for block in blocks:
            profile = block.get("profile_by_state") or []
            if s < len(profile):
                value = float(profile[s])
                best = value if best is None or value > best else best
        if best is not None and target > best:
            flagged.append(s)
    return tuple(flagged)


def _state_curve(
    r_star: float,
    returnset_payload: Mapping[str, Any],
) -> tuple[tuple[float, ...], float, float]:
    """The 25-point target curve: a policy ramp, level-shifted onto the household's required return.

    Returns:
        The 25 points, the *unshifted* ramp's house-view expectation, and the shift applied. The last two are
        returned rather than recomputed by the caller so that the note and the numbers cannot disagree.

    Raises:
        ValueError: If the ReturnSet carries no house view or no state-to-scenario partition. Both are needed
            to know what "expectation" means over the state axis, and assuming a uniform one would silently
            replace the Investment Committee's view with this module's.

    **The weighting, and the one approximation in it.** The house view is stated per *scenario*, five numbers,
    while the curve lives on the 25-state axis. The ReturnSet's own `state_to_scenario` map says which states
    make up each scenario, so the curve's expectation is

        E_omega[curve] = sum over scenarios g of omega_g * mean(curve over the states in g)

    States inside a scenario are weighted **equally**, because the payload carries no within-scenario state
    frequencies — the ones `aggregate_to_scenarios` used are consumed there and not published. That is an
    approximation and it is stated rather than hidden. It is also the reason this function returns the
    expectation it actually achieved: a caller can assert it, and `tests/test_roster.py` does.
    """
    house_view = returnset_payload.get("house_view") or {}
    if not house_view:
        raise ValueError(
            "the ReturnSet carries no house view, so there is no basis on which to say what a target curve's "
            "expectation is, and a uniform one would substitute this module's view for the Committee's"
        )
    mapping = returnset_payload.get("state_to_scenario") or {}
    if not mapping:
        raise ValueError(
            "the ReturnSet carries no state_to_scenario partition, so the 25-state curve cannot be weighted by "
            "a house view stated over five scenarios"
        )

    grid = int(returnset_payload.get("state_grid", 25))
    span = TARGET_CURVE_CEILING - TARGET_CURVE_FLOOR
    shape = [TARGET_CURVE_FLOOR + span * s / (grid - 1) for s in range(grid)]

    by_scenario: dict[str, list[float]] = {}
    for s in range(grid):
        scenario = mapping.get(str(s))
        if scenario is None:
            raise ValueError(f"state {s} has no scenario in the ReturnSet's state_to_scenario map")
        by_scenario.setdefault(scenario, []).append(shape[s])

    weight_total = sum(float(house_view[g]) for g in house_view if g in by_scenario)
    if weight_total <= 0:
        raise ValueError("the house view puts no weight on any scenario present in the state partition")
    shape_mean = (
        sum(
            float(house_view[g]) * (sum(by_scenario[g]) / len(by_scenario[g]))
            for g in house_view
            if g in by_scenario
        )
        / weight_total
    )

    shift = r_star - shape_mean
    return tuple(v + shift for v in shape), shape_mean, shift


#: The ReturnSet publishes roles in lower case; the constraint vocabularies use the framework's title-case
#: names, and the Fund Map's own seed register uses two words this project does not: `Growth` for Gain and the
#: American `Stabilization`. PCP already reconciles all three in `pcp/ingest/returnset.py`, deliberately and
#: with a refusal rather than a silent mismatch. This mirrors that mapping rather than inventing a second one.
#:
#: Worth knowing before touching it: a first version of the role-tilted proxy below matched `protection` against
#: `POLICY_BOUNDS`'s `Protection`, missed, silently took the default upper bound of 1.0, and allocated 100% to
#: Protection — reporting a 9.52% expected return that no admissible portfolio could hold. It looked like a
#: plausible improvement, which is what made it dangerous.
ROLE_SYNONYMS: dict[str, str] = {"growth": "Gain", "stabilization": "Stabilisation"}


def _bounds_without_a_role(
    blocks: Sequence[Mapping[str, Any]],
    policy_bounds: Mapping[str, Mapping[str, tuple[float, float]]] | None = None,
) -> list[tuple[str, float]]:
    """Bounded roles this universe does not contain, with their floors.

    A role bound naming something absent cannot apply. Where its floor is positive the mandate is asking for a
    holding the universe cannot supply, which makes it unsatisfiable rather than merely unconstrained — and that
    is worth saying out loud rather than discovering in the Optimiser.
    """
    present = {_canonical_role(b.get("role")) for b in blocks}
    bounds = (policy_bounds or POLICY_BOUNDS).get("role", {})
    return [
        (role, float(limits[0])) for role, limits in bounds.items() if role not in present
    ]


def _canonical_role(role: object) -> str:
    """The framework's title-case role name, from whichever of the three vocabularies arrived."""
    text = str(role or "unclassified").strip()
    return ROLE_SYNONYMS.get(text.lower(), text[:1].upper() + text[1:] if text else "Unclassified")


def _expected_return(
    blocks: Sequence[Mapping[str, Any]],
    returnset_payload: Mapping[str, Any],
    policy_bounds: Mapping[str, Mapping[str, tuple[float, float]]] | None = None,
) -> float:
    """The best expected annual return an *admissible* allocation reaches under the house view.

    Per block, `E[R] = sum over scenarios of omega_g * profile_by_scenario[g]`. Blocks are then aggregated to
    roles and the roles filled greedily, best first, **subject to the CIO role bounds** — so the result is the
    return a portfolio this mandate would actually permit, not the return of holding everything.

    **This replaced an equal weighting on 2 August 2026, and the reason is a defect rather than a refinement.**
    The old proxy averaged all 54 blocks equally and called that neutral. It is not neutral: 23 of the 54 are
    Gain, and under a Regime weighted toward caution Gain earns about -4%. Equal weighting therefore embedded a
    standing bet *against* the macro view the same system publishes, and it set every household's goal buffer.
    Measured under the published contracts, the roles are not close:

        protection      7 blocks   +12.29%     (regime-weighted)
        stabilisation  11 blocks    +0.97%
        income         13 blocks    -0.76%
        gain           23 blocks    -4.22%

    So "the universe returns about nothing" was an artefact of the weighting, and a household was told its goal
    was unreachable partly because the proxy insisted on holding the worst role in the set.

    **Still house-view weighted, deliberately.** The scenario weights stay the Investment Committee's, per the
    refusal below — what changed is the weighting *across instruments*, which was never theirs to set.

    **Still not circular.** The role mix is derived from the bounds and the returns alone, so it needs no
    allocation from the Optimiser. It remains a proxy: the real allocation is also constrained by currency,
    liquidity, region and per-instrument caps that this ignores, so treat it as an upper bound on what an
    admissible portfolio reaches rather than as a forecast of what the Optimiser will choose.

    Raises:
        ValueError: If the ReturnSet carries no house view, since then there is no basis on which to form an
            expectation and guessing one would be worse than refusing.
    """
    house_view = returnset_payload.get("house_view") or {}
    if not house_view:
        raise ValueError(
            "the ReturnSet carries no house view, so no expected return can be formed and the goal buffer "
            "cannot be measured. The house view is the Investment Committee's input; it is not this module's "
            "to invent."
        )

    by_role: dict[str, list[float]] = {}
    for block in blocks:
        profile = block.get("profile_by_scenario") or {}
        if not profile:
            continue
        expected = sum(
            float(house_view[s]) * float(profile[s]) for s in house_view if s in profile
        )
        by_role.setdefault(_canonical_role(block.get("role")), []).append(expected)
    if not by_role:
        raise ValueError("no block carries a scenario profile, so no expected return can be formed")

    role_return = {role: sum(v) / len(v) for role, v in by_role.items()}
    bounds = dict((policy_bounds or POLICY_BOUNDS).get("role", {}))

    # A bound naming a role this universe does not contain cannot apply, so it is dropped here rather than
    # allowed to look as though it constrained something.
    #
    # This *reports* rather than refuses, and the distinction was decided by a test. A first version raised, on
    # the reasoning that a constraint which silently does not apply is worse than no constraint — which is true
    # of the mandate but wrong here. This function computes a buffer *diagnostic*; whether the mandate is
    # satisfiable is the Optimiser's judgement, and crashing a diagnostic denies a reader the very number that
    # would explain why. The end-to-end journey restricts the universe to Gain and Income, so its 5% Protection
    # floor is genuinely unmeetable — a finding worth surfacing, not a reason to fail the projection.
    #
    # `derive_snapshot` turns the dropped bounds into a note. See `_bounds_without_a_role`.
    bounds = {role: limits for role, limits in bounds.items() if role in role_return}

    # Fill the best-returning admissible roles first, honour the floors afterwards. A greedy fill is exact for
    # a linear objective under independent box bounds, which is what this is.
    allocation: dict[str, float] = {role: 0.0 for role in role_return}
    remaining = 1.0
    for role in sorted(role_return, key=lambda r: -role_return[r]):
        if remaining <= 1e-12:
            break
        _, upper = bounds.get(role, (0.0, 1.0))
        take = min(float(upper), remaining)
        allocation[role] = take
        remaining -= take

    # A floor is a floor even when the role earns badly: the mandate requires it to be held.
    for role, (lower, _upper) in bounds.items():
        if role not in allocation:
            continue
        shortfall = float(lower) - allocation[role]
        if shortfall <= 1e-12:
            continue
        for donor in sorted(role_return, key=lambda r: role_return[r]):
            if donor == role or allocation.get(donor, 0.0) <= 0.0:
                continue
            _, donor_floor = bounds.get(donor, (0.0, 1.0)), bounds.get(donor, (0.0, 1.0))[0]
            spare = allocation[donor] - donor_floor
            give = min(shortfall, max(spare, 0.0))
            allocation[donor] -= give
            shortfall -= give
            if shortfall <= 1e-12:
                break
        allocation[role] += float(lower) - allocation[role] if shortfall > 1e-12 else shortfall

    total = sum(allocation.values()) or 1.0
    return sum(w / total * role_return[role] for role, w in allocation.items())


def _liquidity_floor(horizon_years: float) -> dict[str, Bound]:
    """How much must sit in reachable classes, given how soon the money is needed.

    The household model haircuts the residence to near zero precisely because net worth is not spendable, so a
    deadline is a claim on *reachable* wealth. A near deadline therefore forces the top of the ladder; a distant
    one permits the bottom, which is where illiquidity premia live.
    """
    if horizon_years <= 2.0:
        return {
            "Daily": Bound(lower=0.60, upper=1.0, source=BoundSource.DERIVED),
            "Decade": Bound(lower=0.0, upper=0.0, source=BoundSource.DERIVED),
        }
    if horizon_years <= 5.0:
        return {
            "Daily": Bound(lower=0.30, upper=1.0, source=BoundSource.DERIVED),
            "Decade": Bound(lower=0.0, upper=0.10, source=BoundSource.DERIVED),
        }
    if horizon_years <= 15.0:
        return {"Daily": Bound(lower=0.10, upper=1.0, source=BoundSource.DERIVED)}
    # Beyond fifteen years the goal imposes no liquidity requirement at all, so none is claimed.
    return {}


def render_mandate_yaml(
    snapshot: BalanceSheetSnapshot,
    returnset_payload: Mapping[str, Any],
    market: str = "Global",
    benchmark: str = "Swiss",
) -> str:
    """Render a derived mandate into the Optimiser's own mandate format.

    **This is transport, not derivation.** The derivation happened in `derive_snapshot`, inside this engine,
    which is where M4 places it. The Optimiser already reads a mandate YAML, so materialising the derived
    mandate in that format joins the chain without changing the Optimiser at all, and without an adapter
    quietly deriving anything between the two engines.

    The per-instrument caps are the one thing the Optimiser's current schema cannot express: it takes a single
    `max_single_position`. So the tightest derived cap is used, which is conservative, and the note says so.
    """
    import yaml

    mandate = snapshot.mandate
    caps = mandate.position_cap
    effective = [caps.for_instrument(b) for b in mandate.universe]
    tightest = min(effective) if effective else caps.policy_cap

    bounds_out: dict[str, dict[str, dict[str, float]]] = {}
    for dimension, categories in mandate.bounds.items():
        bounds_out[dimension] = {
            label: {"lower": bound.lower, "upper": bound.upper}
            for label, bound in categories.items()
        }

    payload = {
        "client": snapshot.household_id,
        "mandate": f"derived-{snapshot.goal.kind}-{snapshot.goal.horizon_years:g}y",
        "market": market,
        "currency": mandate.reporting_currency,
        "benchmark": benchmark,
        "horizon_years": mandate.curve.horizon_years,
        "max_single_position": float(tightest),
        "esg_min": mandate.esg_min,
        "target_curve": [float(v) for v in mandate.curve.points],
        "universe": [int(b) for b in mandate.universe],
        "fixed_allocations": {},
        "bounds": bounds_out,
    }

    header = (
        f"# DERIVED MANDATE. Generated from BalanceSheetSnapshot {snapshot.snapshot_id()}.\n"
        f"# Do not edit: it is regenerated from the household's position and goal.\n"
        f"#\n"
        f"# household      {snapshot.household_id}\n"
        f"# goal           {snapshot.goal.kind}, {snapshot.goal.target:,.0f} in "
        f"{snapshot.goal.horizon_years:g}y at {1 - snapshot.goal.epsilon:.0%} confidence\n"
        f"# required       {mandate.curve.required_return:.4%} a year, in expectation under the house view\n"
        f"# curve          {mandate.curve.points[0]:.4%} in state 0 rising to "
        f"{mandate.curve.points[-1]:.4%} in state 24 "
        f"(state_dependent={mandate.curve.state_dependent})\n"
        f"# regime         {snapshot.regime.regime_id}\n"
        f"# bound sources  {mandate.sources_in_use()}\n"
        f"#\n"
        f"# The curve's SHAPE is CIO policy and the LEVEL is derived. The ramp asks less of a crisis than of\n"
        f"# a boom, which no household model here can supply; the block shift that sets the level is chosen\n"
        f"# so the curve's house-view expectation equals the required return above. DECISIONS.md M50.\n"
        f"#\n"
        f"# The single max_single_position below is the tightest of the per-instrument caps this mandate\n"
        f"# derived, because the Optimiser's schema takes one scalar. That is conservative: instruments with\n"
        f"# a smaller crisis loss could safely carry more. Per-instrument caps need a schema change there.\n"
    )
    return header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)


def proxy_expected_return(
    returnset_payload: Mapping[str, Any],
    universe: Sequence[int] | None = None,
) -> float:
    """The role-bounded best-admissible return (M59), for a caller that needs the iteration's seed.

    A public seam over `_expected_return`, which takes an already-filtered block list. Exists so the
    orchestration layer can compute the fixed point's starting value without either importing a private or
    re-implementing this function's universe filtering — the second of which would be a second definition of
    "the investable set" and would drift from this one.
    """
    blocks = list(returnset_payload.get("building_blocks", []))
    if universe is not None:
        wanted = {int(b) for b in universe}
        blocks = [b for b in blocks if int(b["bb_id"]) in wanted]
    if not blocks:
        raise ValueError(
            "no building blocks in the requested universe, so no proxy return can be formed to seed the "
            "fixed-point iteration"
        )
    return _expected_return(blocks, returnset_payload)


def allocation_expected_return(
    holdings: Sequence[Any],
    returnset_payload: Mapping[str, Any],
) -> float:
    """The house-view expected annual return of an allocation the Optimiser actually chose.

    The other half of the fixed point (M63). `_expected_return` answers "what is the best an admissible
    portfolio *could* earn" and is an upper bound by construction; this answers "what does *this* portfolio
    earn", which is the number the household's buffer, caps and curve level should rest on.

    `E[R] = sum over holdings of w_i * sum over scenarios of omega_g * profile_by_scenario[g]`, with `omega`
    the Investment Committee's house view. The scenario weights stay the Committee's for exactly the reason
    `_expected_return` gives: they are not this module's to set.

    Args:
        holdings: The Recommendation's holdings, each carrying `bb_id` and `weight`.
        returnset_payload: The published ReturnSet the allocation was solved against.

    Returns:
        The weighted expected annual return, as a decimal.

    Raises:
        ValueError: If the ReturnSet carries no house view, if a holding names a block the ReturnSet does not
            contain, or if the weights do not sum to one. Each is a genuine break rather than something to
            paper over: a missing house view leaves no basis for an expectation, an unknown block means the
            allocation and the ReturnSet disagree about the universe, and weights that miss one mean the
            iteration would converge on a return for a portfolio nobody can hold.
    """
    house_view = returnset_payload.get("house_view") or {}
    if not house_view:
        raise ValueError(
            "the ReturnSet carries no house view, so an allocation's expected return cannot be formed and "
            "the fixed-point iteration has nothing to measure"
        )
    by_id = {int(b["bb_id"]): b for b in returnset_payload.get("building_blocks", [])}

    total_weight = 0.0
    expected = 0.0
    for holding in holdings:
        bb_id = int(getattr(holding, "bb_id"))
        weight = float(getattr(holding, "weight"))
        block = by_id.get(bb_id)
        if block is None:
            raise ValueError(
                f"the allocation holds block {bb_id}, which the ReturnSet does not contain. The allocation and "
                f"the ReturnSet disagree about the universe, so no return can be measured from them."
            )
        profile = block["profile_by_scenario"]
        expected += weight * sum(
            float(w) * float(profile[g]) for g, w in house_view.items() if g in profile
        )
        total_weight += weight

    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(
            f"the allocation's weights sum to {total_weight:.8f} rather than one, so its expected return is "
            f"not a portfolio return. Refusing rather than normalising: the Optimiser reports budget failures "
            f"itself, and silently rescaling here would hide one."
        )
    return expected
