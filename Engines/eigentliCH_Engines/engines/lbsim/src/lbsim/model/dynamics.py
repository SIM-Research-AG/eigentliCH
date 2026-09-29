"""The SDE system (spec §5–6): drift f(x,u) and diffusion g(x,u).

Wealth accumulates; expertise, network and health saturate (logistic). Health
carries the balancing loop: overwork accelerates its decay, which drags income.

Derivatives are returned as a flat `Deriv` record so the same functions serve the
deterministic skeleton (σ = 0), the Monte-Carlo layer, and later the NLP.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

#: 1 − e^(−1). The saturating shapes divide by this so f(scale) == scale exactly.
_SATURATION_AT_SCALE: float = 1.0 - math.exp(-1.0)

#: Floor under a time share before a fractional power is taken. **Shared with `optim/symbolic.py` rather than
#: restated there.** The first version floored only the CasADi side, so the two transcriptions disagreed at
#: tau = 0 — numpy returned 0.0, CasADi returned 4.5e-5 — and `test_model_parity` caught it on its first run.
#: That is the entire argument for one definition: a constant written twice is a divergence waiting to happen.
#: Small enough to be numerically irrelevant against the 0.05 lower bound the solver enforces.
_TAU_FLOOR: float = 1e-12

from .controls import Control
from .fiscal import DEFAULT_FISCAL, FiscalModel
from .params import Params
from .state import PersonState, State


@dataclass
class Deriv:
    """Time-derivatives of the state, component-aligned with State."""

    dW_L: float
    dW_R: float
    dD: float
    dE: np.ndarray  # per expertise component
    dN: float
    dH: float
    #: d(age)/dt = 1 by definition. Carried as a derivative rather than special-cased in the integrator so that
    #: age advances by exactly the same mechanism as everything else, and so a caller who steps the system by hand
    #: cannot forget it. Added 3 August 2026 (step 1); `earning_power` has read it since step 2 the same day.
    dAge: float = 1.0
    #: d(W_res)/dt = mu_R·W_res — the residence appreciates with the market it sits in, which holds the residence
    #: *share* of `W_R` constant rather than its amount. Added 3 August 2026 (step 3). Defaulted so the ~130
    #: existing `Deriv` constructions keep working; `drift` sets it explicitly.
    dW_res: float = 0.0
    #: d(W_hol)/dt = mu_R*W_hol. A second home appreciates like any property; what it does not do is earn.
    dW_hol: float = 0.0
    #: d(W_P)/dt — pillar-2 accrual: contributions while working, plus credited interest, and contributions stop
    #: at `pension_age`. Added 3 August 2026 (step 4).
    dW_P: float = 0.0
    #: d(W_3a)/dt — capped contributions while eligible, plus credited interest. Added 3 August 2026 (step 4b).
    dW_3a: float = 0.0
    #: d(kappa)/dt = alpha_kappa * (C - kappa) — the standard-of-living habit chasing consumption, book eq.
    #: 29.10. Added 25 August 2026 (M80 decision 2). Defaulted like its four predecessors so that every
    #: existing `Deriv` construction keeps working; `drift` sets it explicitly.
    dKappa: float = 0.0
    dMaturity: np.ndarray = field(default_factory=lambda: np.zeros(0))  # per active venture (Q2)


# --- Scalar mechanics (spec §5–6) -------------------------------------------------

def phi(H: float, p: Params) -> float:
    """Health efficiency multiplier φ(H) = H^c (spec §5.2)."""
    return H ** p.c


def venture_income(state: State, p: Params) -> float:
    """Sum of active venture income streams (Q2, spec §18.4), each seeded by
    expertise and ramped by its own S-curve maturity. Zero when no venture has
    been founded, so wage-only cases are unaffected."""
    person = state.person
    if not person.ventures:
        return 0.0
    E_agg = person.E.aggregate()
    return sum(v.income(E_agg) for v in person.ventures)


def age_factor(age: float, p: Params) -> float:
    """The late-career decline: 1 up to the peak, then `(1 − decline)` per year beyond it.

    **This is the only thing age contributes, and it is the only thing it can contribute.** Expertise and network
    already rise over a career, so income already grows with age indirectly; adding an explicit rise would
    double-count it. What E and N structurally *cannot* produce is a fall — both saturate toward a ceiling and
    neither declines — so an age-earnings profile that turns over needs age, and needs it only for that.
    """
    over = max(0.0, age - p.earning_peak_age)
    return (1.0 - p.earning_decline) ** over


def earning_power(E: float, N: float, age: float, p: Params) -> float:
    """Annual earning power at full working time, bounded to [`earning_power_min`, `earning_power_max`].

    Replaces the retired `w0 · E^a · N^b` (step 2, `PLAN_2026-08.md` §0B). The old form asked for a scale at
    `E = N = 1` that nobody could picture; this asks for the range a person's earning power lives in, which is a
    quantity the author can reason about directly, and derives the position within it from the education and
    network scores.

    Continuity is preserved exactly at `E = N = 1` in mid-career, by construction of `earning_power_at_unit` — see
    that field. So the behavioural changes in this step are the bounds biting and the age decline, nothing else.
    """
    skill = p.earning_power_at_unit * (max(E, 0.0) ** p.a) * (max(N, 0.0) ** p.b)
    raw = p.earning_power_min * (p.earning_power_max / p.earning_power_min) ** min(1.0, skill)
    return min(p.earning_power_max, max(p.earning_power_min, raw * age_factor(age, p)))


def income(state: State, u: Control, p: Params) -> float:
    """Income from earning power, scaled by health and work time (spec §5.1):
    Y = earning_power(E, N, age) · τ_Y · φ(H), plus venture income."""
    person = state.person
    wage = earning_power(person.E.aggregate(), person.N, person.age, p) * u.tau_Y * phi(person.H, p)
    return wage + venture_income(state, p)


def habit_of(state: State, p: Params) -> float:
    """The household's habit stock, in CHF a year.

    `None` means the caller did not set one. Reading that as zero would hand the optimiser a free lunch in the
    early periods -- `z = C - h*kappa` would equal `C` -- and charge for it later, which inverts what a habit
    is. So an unset habit is read as the consumption the household's own drawable wealth supports, which is
    the same scale the ceiling normalises by and needs no new constant.
    """
    kappa = getattr(state.person, "kappa", None)
    if kappa is not None:
        return float(kappa)
    return float(p.swr * (state.wealth.W_L + state.wealth.W_R - state.wealth.D))


def network_ceiling(state: State, p: Params) -> float:
    """`N̄ = N_0 + λ_E E + λ_W Ω + λ_κ κ` — book eq. 29.11 and Appendix B.

    The single most consequential connection in the model: competence, resources and a maintained standard of
    living raise the ceiling on network. §29.3 is explicit that the habit term is the least comfortable of the
    three and the most interesting — it says a cut in spending is not free even when the goal is purely
    financial, because it lowers the ceiling on the network that lifts income.

    **This replaced a multiplicative form on GROSS wealth on 25 August 2026 (M80 decision 1).** The two are not
    the same model: for a household with 2.5m of debt against 5m of property, gross wealth is twice net worth,
    so the ceiling differed by about a factor of two. Net worth is the better-motivated argument, because a
    mortgage does not buy social reach.

    **The two scales are an author's decision of 25 August 2026, not the book's.** Appendix C calls `λ_W` and
    `λ_κ` dimensionless while Ω is in francs and κ is francs a year, so both need a normaliser and §29.11 names
    neither. Ω is taken over `W_scale` and κ over `swr · W_scale` — the spending that `W_scale` supports at the
    model's own withdrawal rate. That makes the two terms commensurate: a household holding exactly `W_scale`
    and living off it gets `λ_W` from the first and `λ_κ` from the second.
    """
    person = state.person
    E = person.E.aggregate()
    w = state.wealth
    omega = w.W_L + w.W_R - w.D
    kappa = habit_of(state, p)
    habit_scale = p.swr * p.W_scale
    return (p.N_0
            + p.lambda_E * E
            + p.lambda_W * (omega / p.W_scale)
            + p.lambda_kappa * (kappa / habit_scale))


def delta_H(tau_Y: float, p: Params) -> float:
    """Overwork-sensitive health decay (spec §5.11):
    δ_H(τ_Y) = δ_H0 + η·max(0, τ_Y − τ_Y*)."""
    return p.delta_H0 + p.eta * max(0.0, tau_Y - p.tau_Y_star)


#: Scale of the debt-amortisation gate, in CHF. See `debt_gate`.
_DEBT_GATE_SCALE: float = 100.0


#: Scale of the pension contribution gate, in years. See `pension_working_gate`.
_PENSION_GATE_SCALE: float = 1.0


def pension_working_gate(age: float, p: Params) -> float:
    """1 while contributing, 0 once past `pension_age`, smooth across the boundary.

    Contributions stop at retirement, which is a step — and a step is exactly what the CasADi transcription
    cannot carry, for the same reason `debt_gate` exists: IPOPT needs a derivative at the switch. So the gate
    is a `tanh` over a one-year scale, defined once here and imported by `optim.symbolic` rather than written
    twice. Two copies of one idea is how the debt gate went wrong (M67).

    One year is wide enough to be well-conditioned and narrow enough to be economically invisible: two years
    before the reference age the gate is 0.9993, two years after it is 0.0007. The smoothing therefore costs a
    household under a tenth of one per cent of a single year of contributions.
    """
    return 0.5 * (1.0 - math.tanh((age - p.pension_age) / _PENSION_GATE_SCALE))


#: Scale of the AHV entitlement gate, in years — a quarter of `_PENSION_GATE_SCALE`. See `ahv_pension` for why
#: a sharp gate is admissible here and not for the contribution gates.
_AHV_GATE_SCALE: float = 0.25


#: Width of the gate that ends a child's cost, in years. A quarter of `_PENSION_GATE_SCALE`, for the reason
#: given in `_child_cost_at_age`: the end of an education is a date, not a gradual fading, and at the wider
#: scale it smeared a 25 000 cost across four years and left a third of it standing in the year it ended.
_CHILD_END_GATE_SCALE: float = 0.25

#: Smoothing width for `_smooth_min`, in CHF. Six orders below the quantities it joins, so the rounding is
#: economically invisible, while the kink `min` would leave is not invisible to a barrier method.
_SMOOTH_MIN_EPS: float = 100.0


def _smooth_min(a: float, b: float, eps: float = _SMOOTH_MIN_EPS) -> float:
    """min(a, b), differentiable everywhere. Twin of `symbolic._smooth_min`; parity enforces the match.

    `0.5 * (a + b - sqrt((a - b)^2 + eps^2))`. It is `min` to within `eps/2` at the crossing, and **not** exactly
    `min` away from it: the error decays as `eps^2 / (4|a - b|)`, so at `eps = 100` and a gap of 15 240 it is still
    16 rappen low. That bias is economically nothing but it is not zero, and claiming otherwise would be the kind
    of overclaim this codebase keeps paying for — `test_dynamics` pins it at under one franc rather than at zero.
    A single household never sees it at all, because `ahv_pension` returns early when there is no partner.

    Chosen over a log-sum-exp softmin because that form overflows on money-scale arguments, which is exactly the
    range this is used on.
    """
    d = a - b
    return 0.5 * (a + b - math.sqrt(d * d + eps * eps))


def _ahv_individual(average_income: float, age: float, record_share: float, p: Params) -> float:
    """One person's AHV entitlement. Factored out of `ahv_pension` so the couple cap has something to sum.

    Two copies of this law is how the debt gate and the pension gate both went wrong (M67), so the partner's
    entitlement is computed by the same function as the subject's rather than by a second transcription of it.
    """
    share = min(1.0, max(0.0, average_income) / max(p.ahv_income_for_max, 1.0))
    full = p.ahv_full_single * max(0.0, min(1.0, record_share))
    # Rises from the minimum to the maximum across the income scale rather than from zero: a complete record
    # earns a floor regardless of how low the average was.
    entitled = full * (0.5 + 0.5 * share)
    gate = 0.5 * (1.0 + math.tanh((age - (p.ahv_age - 0.5)) / _AHV_GATE_SCALE))
    return entitled * gate


def ahv_pension(average_income: float, age: float, p: Params) -> float:
    """The AHV pension: zero before the reference age, then a capped share of the full single pension.

    **The one income stream here with no stock behind it.** Pillars 2 and 3a are capital that converts into
    income; this is a claim that pays. That is why there is no `W_AHV` state — a state would imply drawable
    capital, and no part of the AHV can be drawn, pledged, inherited as a balance or used for a deposit.

    Two properties are worth seeing in the code rather than discovering later. It is **regressive**: the
    pension rises with averaged lifetime income only up to `ahv_income_for_max` and is flat above it, so a
    household on 149 000 and one on 500 000 receive the same first pillar — the ratio to spending is therefore
    far better for a modest earner. And it is **scaled by the contribution record**, where each missing year
    costs roughly one forty-fourth; gaps are common and worth asking about rather than assuming away.

    **The age switch is deliberately much sharper than the two contribution gates, and it may be sharp for a
    reason those cannot use.** Reusing the shared one-year scale centred on 65 was the first attempt and it was
    wrong: a `tanh` centred on the reference age pays exactly *half* at that age, so a household received
    15 120 in the year it was entitled to 30 240. For a contribution gate that smoothing is invisible; for a
    pension it is fifteen thousand francs.

    A gate this steep would normally be a conditioning problem. It is not here, and the reason is worth stating:
    **the AHV depends only on age, and age is uncontrolled** — `dAge/dt = 1` regardless of every control. So the
    derivative of this gate with respect to anything the optimiser chooses is exactly zero, and IPOPT never
    differentiates through it. Smoothness is required where the solver searches, not everywhere.

    Centred half a year early at a quarter-year scale, so entitlement is ~2% at 64 and ~98% at 65.
    """
    own = _ahv_individual(average_income, age, p.ahv_record_share, p)
    if not p.has_partner:
        return own
    # --- H1: the couple's first pillar is CAPPED, not summed -------------------------------------------
    #
    # Two married pensions together may not exceed `ahv_couple_cap_multiple` of the maximum single pension (150%
    # in Swiss law), so adding two individual entitlements overstates a couple's AHV by up to a third. The cap is
    # on the SUM at the household level, which is why it cannot live inside `_ahv_individual`.
    #
    # Smooth minimum rather than `min`: this ceiling **binds by design** for any couple with two decent records,
    # and `symbolic.py` warns that a clamp which binds often "wants a softmin instead". The earning-power clamp
    # was measured never to bind and so was left hard; this one is the opposite case.
    partner = _ahv_individual(p.partner_income, age + p.partner_age_offset,
                              p.partner_ahv_record_share, p)
    # No separate "are both retired yet" gate is needed: each individual pension is already age-gated, so before
    # the second partner reaches 65 the sum cannot exceed one full pension and the 150% cap cannot bind.
    cap = p.ahv_couple_cap_multiple * p.ahv_full_single
    return _smooth_min(own + partner, cap)


def pillar3a_flow(income_now: float, age: float, p: Params) -> float:
    """This year's 3a contribution: the intended amount, capped, and zero once past the withdrawal age.

    Three limits, in order. The **cap** is the binding one for most people and is what makes the December
    deadline real: unused room does not carry forward, so a year not used is gone. **Affordability** floors it at
    what income can actually fund — a household cannot deduct a contribution it could not make, and without this
    the model would happily contribute 7 258 out of an income of 3 000. And the **age gate** stops contributions
    at `pillar3a_age`, smoothly, using the same one-year `tanh` as pillar 2 so the CasADi twin has a derivative.

    Returns a flow in CHF per year, which is what both the state and the tax deduction consume.
    """
    intended = min(p.pillar3a_contribution, p.pillar3a_cap)
    affordable = min(intended, max(0.0, income_now))
    return affordable * 0.5 * (1.0 - math.tanh((age - p.pillar3a_age) / _PENSION_GATE_SCALE))


def child_cost_level(p: Params) -> tuple[float, float]:
    """The two annual per-child costs — young band, older band — in the money the household typed in.

    Returns `(0.0, 0.0)` when there are no children, so every expression downstream is exactly zero and the
    childless answer is unchanged to the franc (the M73 rule).

    **The level a household states beats the published average.** `child_costs_stated` is a TOTAL for all
    children per year; it is spread over them and scaled so that the source's age *shape* is preserved while
    its *level* is replaced. The Bern household states 25 000 a year for one child in education against the
    source's 873 a month, and it is their household — the published mean is what to use when nobody has said
    anything, not a correction to what they did say.
    """
    n = len(p.child_ages)
    if n == 0:
        return 0.0, 0.0

    couple = bool(p.child_household_is_couple)
    # Nearest published row: exact count and household shape first, then the closest count for that shape, then
    # any row at all. Matching loosely is right here — the alternative is refusing to model a household with
    # four children because the study stops at three.
    rows = [r for r in p.child_cost_table if r[1] == couple] or list(p.child_cost_table)
    row = min(rows, key=lambda r: abs(r[0] - n))
    young, older = row[2] * 12.0, row[3] * 12.0          # CHF/month in the source -> CHF/year
    young, older = young * p.child_cost_uprating, older * p.child_cost_uprating

    if p.child_costs_stated is not None:
        # Scale both bands so the household's stated TOTAL is what the children cost at their CURRENT ages,
        # keeping the source's ratio between the bands. Falls back to a flat split if the shape is degenerate.
        stated_each = float(p.child_costs_stated) / n
        base = _child_band_mix(p, young, older)
        young, older = ((young * stated_each / base, older * stated_each / base) if base > 0.0
                        else (stated_each, stated_each))
    return young, older


def _child_band_mix(p: Params, young: float, older: float) -> float:
    """Average per-child cost at the children's ages as recorded — the denominator for a stated total."""
    if not p.child_ages:
        return 0.0
    return sum(_child_cost_at_age(float(a), young, older, p) for a in p.child_ages) / len(p.child_ages)


def _child_cost_at_age(child_age: float, young: float, older: float, p: Params) -> float:
    """One child's annual cost at a given age. Smooth in age, for the same reason every gate here is.

    Two `tanh` gates, and **deliberately at different widths**, because the two events are different in kind.

    The band change at `child_cost_age_split` is genuinely gradual — a child does not become more expensive on
    a birthday, and the source's 0-10 against 11-21 split is a bucket boundary in an estimate, not an event. A
    one-year scale, the width `pension_working_gate` uses, is the honest shape.

    The end at `child_cost_end_age` is **a date**. An apprenticeship finishes, a degree finishes, and the money
    stops. At a one-year scale the transition smears across about four years, and measured on the Bern
    household — whose entire result rests on 25 000 a year ending in 2028 — that put 12 729 of a 25 000 cost in
    the year it was supposed to be gone, and 3 035 the year after. That is not a rounding artefact, it is the
    finding being blurred away. So the end uses a quarter-year scale, the same narrowing and for the same
    reason `_AHV_GATE_SCALE` is a quarter of the contribution gates: a sharp gate is admissible where the
    underlying event really is a step.

    Neither is a hard step, because CasADi's transcription needs a derivative at the switch — this is why
    `debt_gate` exists (M67).
    """
    band = 0.5 * (1.0 + math.tanh((child_age - p.child_cost_age_split) / _PENSION_GATE_SCALE))
    ended = 0.5 * (1.0 - math.tanh((child_age - p.child_cost_end_age) / _CHILD_END_GATE_SCALE))
    return (young * (1.0 - band) + older * band) * ended


def child_costs(age: float, p: Params) -> float:
    """Total annual child cost for the household at the subject's age `age`, CHF per year.

    The children age with the subject. `age` is a state that advances, so the child's age at any point is
    `recorded age + (age - child_reference_age)` and no new state is needed — `NX` is unchanged, which is what
    keeps this from being a state-vector revision.
    """
    young, older = child_cost_level(p)
    if young == 0.0 and older == 0.0:
        return 0.0
    shift = age - p.child_reference_age
    return sum(_child_cost_at_age(float(a) + shift, young, older, p) for a in p.child_ages)


def debt_gate(D: float) -> float:
    """How open amortisation is: 0 with no debt, 1 with any real amount of it.

    **Why this exists.** `drift` used a hard `if D > 0`, while `optim/symbolic` subtracted the payment
    unconditionally — so the optimiser solved a system where paying down a zero balance still reduced it, driving
    `D` negative. `problem.py`'s `D >= 0` constraint hid the consequence, meaning a constraint was doing work the
    dynamics should have done. Found by `tests/test_model_parity.py` on its first real run, 3 August 2026.

    **Why `tanh` and not `D/(D+s)`.** The rational gate was tried first and is asymptotic: at CHF 300 000 it is
    0.9999967, so it under-amortises by 3.3e-6 *everywhere*, which is a systematic error rather than a boundary
    one. `tanh` saturates exponentially and reaches exactly 1.0 in float64 by about twenty times the scale — CHF
    2 000 here — so for any real mortgage the gate is exactly open and the two models agree bit for bit.

    **Why it is shared rather than written twice.** Because the bug it fixes was two transcriptions of one idea
    disagreeing. The derivative at zero is 1/scale = 0.01, which is well-conditioned for IPOPT; the sharper
    rational gate needed a scale of 1e-6 to reach the same accuracy, at a derivative of 1e6.
    """
    return math.tanh(max(D, 0.0) / _DEBT_GATE_SCALE)


# --- Returns to invested time (calibration round B, 3 August 2026) --------------------
#
# Each function maps a time share to its *effective* share, and each is built so that
# `f(reference) == reference` exactly. That means `alpha_* · f(tau)` replaces
# `alpha_* · tau` without changing what the `alpha_*` rates mean or requiring them to be
# rescaled — the shape carries its own normalisation. Verified by `test_model_parity`.
#
# `optim/symbolic.py` holds CasADi twins of all three. They must agree.


def rest_effect(tau_H: float, p: Params) -> float:
    """Recovery time with diminishing returns and no knee: ref^(1−ν) · τ^ν.

    ν = 0.5 makes recovery a square root of time, so quadrupling rest doubles it. Chosen to match
    `_GAMMA_V = 0.5`, the leisure curvature already used in the objective, so the model treats rest and leisure
    with one saturation. Replaces a linear term under which 40 h/week of rest restored exactly four times what
    10 h/week did.
    """
    safe = max(tau_H, _TAU_FLOOR)
    return (p.tau_H_ref ** (1.0 - p.nu_H)) * (safe ** p.nu_H)


def _saturating(tau: float, scale: float) -> float:
    """Effective time under a knee at `scale`: s·(1 − e^(−τ/s))/(1 − e^(−1)).

    Equals `scale` at `tau == scale`, reaches 86% of its maximum at twice the scale and 95% at three times. A
    power law cannot express this — it has constant elasticity, so no knee — which is why this family is used for
    the two activities the author described with a threshold.
    """
    if tau <= 0.0:
        return 0.0
    return scale * (1.0 - math.exp(-tau / scale)) / _SATURATION_AT_SCALE


def network_effect(tau_N: float, p: Params) -> float:
    """Networking time, knee at 10 h/week: "anything more is useless"."""
    return _saturating(tau_N, p.tau_N_scale)


def learning_effect(tau_E: float, p: Params) -> float:
    """Learning time, knee at 20 h/week — twice networking's.

    Deep work absorbs more sustained hours before it stops paying, and the engine's own backtest records 30
    h/week of learning during full-time education. At a 10-hour scale that period would read as 95% saturated,
    i.e. the model would claim the last 20 of those 30 hours bought almost nothing during a degree.
    """
    return _saturating(tau_E, p.tau_E_scale)


def mu_P(theta: float, p: Params) -> float:
    """Portfolio mean return μ_P(θ) = r_f + θ·(μ_M − r_f) (spec §5.5)."""
    return p.r_f + theta * (p.mu_M - p.r_f)


def sigma_P(theta: float, p: Params) -> float:
    """Portfolio volatility σ_P(θ) = θ·σ_M (spec §5.4)."""
    return theta * p.sigma_M


def income_tax(taxable: float, p: Params) -> float:
    """Smooth progressive effective income tax (spec Ch.20 §3):
    r_max·t·(1 − e^(−t/scale)) with t = max(0, taxable). Differentiable in t,
    which the symbolic optimiser needs; matches optim/symbolic.income_tax.

    **H1 joint taxation.** `tax_split_factor` expresses Swiss *Vollsplitting*: the couple's combined income is
    taxed as `f` shares at the single tariff, `f * base(t / f)`. Because the tariff is progressive, that is
    strictly less than `base(t)` for `f > 1` — which is the point, and why a couple cannot be modelled by simply
    adding the partner's income to a single-person tariff. At the default `f = 1.0` this is *algebraically* the
    original expression, not merely close to it, so no single-person figure moves.

    Cantonal practice varies — full splitting, partial splitting, or a separate married tariff — so `f = 2.0` is a
    declared approximation rather than a claim about any canton. The onboarding collects the canton; matching a
    real cantonal tariff is a calibration task, not a modelling one.
    """
    t = max(0.0, taxable)
    f = max(1.0, p.tax_split_factor)
    return f * (p.tax_rate_max * (t / f) * (1.0 - np.exp(-(t / f) / p.tax_income_scale)))


def wealth_tax(net_worth: float, p: Params) -> float:
    """Flat cantonal-style wealth tax on positive net worth."""
    return p.wealth_tax_rate * max(0.0, net_worth)


def net_cash_to_liquid(
    state: State,
    u: Control,
    p: Params,
    fiscal: FiscalModel = DEFAULT_FISCAL,
) -> float:
    """Cash-flow identity feeding the liquid-wealth SDE (spec §5.3):
    NetCashToLiquid = Y + y_R·W_inv − C − m_E − m_N − i·D − p_A − taxes, then routed
    through the FiscalModel (SEAM 3) for any further institutional adjustment.

    Taxable income deducts mortgage interest (Swiss practice); the wealth tax is
    levied on net worth.

    **The yield term was `y_R·W_R` until 3 August 2026 (step 3).** That credited the whole real-asset stock
    with rent, including a home the household lives in — which produces no cash. It is now `y_R·W_inv`, the
    let share only. The wealth tax still falls on `net_worth`, which is right: a residence is taxed whether
    or not it earns."""
    Y = income(state, u, p)
    asset_yield = p.y_R * state.wealth.W_inv + p.y_hol * state.wealth.W_hol
    interest = p.i * state.wealth.D
    # Pillar 3a leaves liquid wealth as cash and reduces taxable income — the deduction is the whole point of
    # the pillar, and it is the only place in this model where a *stock's* inflow moves the tax base. Netting it
    # out of `raw` as well as out of `taxable` is deliberate: the money genuinely leaves the account.
    contrib_3a = pillar3a_flow(Y, state.person.age, p)
    # Pillar 2 leaves the household's cash as well as entering `W_P`. **It did not until 4 August 2026, and the
    # model was creating money**: `pension_contribution_rate` appeared only in `dW_P`, so 15% of income
    # materialised in the pension pot without leaving anywhere. The employee half is deducted from salary and
    # the employer half never reaches the employee, so treating `Y` as gross and removing the whole contribution
    # is the consistent reading — the same treatment 3a gets two lines up.
    contrib_p2 = p.pension_contribution_rate * Y * pension_working_gate(state.person.age, p)
    # AHV. `earning_power` stands in for averaged lifetime income, because this model keeps no earnings history
    # and adding one for a regressive, capped benefit would be a state variable spent on a rounding effect: the
    # pension is flat above ~90 700, and any household whose earning capacity clears that gets the maximum
    # either way. It is a proxy and errs on the generous side for someone whose average was below their peak.
    person = state.person
    ahv = ahv_pension(
        earning_power(person.E.aggregate(), person.N, person.age, p), person.age, p
    )
    # H1: the partner's income is exogenous — it is not chosen and does not respond to the plan — but it is
    # household cash and it is part of the joint tax base, so it must appear in both. No pillar-2 or 3a deduction
    # is taken on it: those are the subject's own stocks here, and crediting the partner's contributions without
    # carrying their capital would create the same money-from-nothing error `contrib_p2` above was added to fix.
    Y_partner = p.partner_income if p.has_partner else 0.0
    # Children: a cash outflow that changes with their age and then stops. NOT taxable-income-reducing — Swiss
    # child deductions exist but are a cantonal tariff feature, and this model's tax function is a smooth
    # stand-in with no allowance structure to hang them on. Claiming the deduction here would be inventing one.
    kids = child_costs(person.age, p)
    raw = (Y + Y_partner + ahv + asset_yield
           - u.C - u.m_E - u.m_N - interest - u.p_A - contrib_3a - contrib_p2 - kids)
    # AHV is taxable income in Switzerland, in full.
    taxes = (income_tax(max(0.0, Y + Y_partner + ahv + asset_yield - interest - contrib_3a), p)
             + wealth_tax(state.net_worth, p))
    return fiscal.adjust_net_cash(
        raw - taxes, income=Y, asset_yield=asset_yield, state=state, params=p
    )


# --- Drift and diffusion (spec §5) ------------------------------------------------

def drift(
    state: State,
    u: Control,
    p: Params,
    fiscal: FiscalModel = DEFAULT_FISCAL,
) -> Deriv:
    """f(x, u): the deterministic part of dx/dt."""
    w = state.wealth
    person = state.person
    E = person.E.components
    E_agg = person.E.aggregate()

    # Liquid wealth: net cash flow + investment return (spec §5.4).
    dW_L = net_cash_to_liquid(state, u, p, fiscal) + mu_P(u.theta, p) * w.W_L

    # Real assets: appreciate + (yield already counted as cash into W_L) (spec §5.6).
    # Both the total and the residence share appreciate at `mu_R`, which holds the *share* constant. See the
    # `dW_res` note on `Deriv`, and its CasADi twin in `optim.symbolic.drift`.
    dW_R = p.mu_R * w.W_R
    dW_res = p.mu_R * float(w.W_res or 0.0)
    # Pillar 2: contributions are a share of income and stop at the reference age; the accrued balance earns
    # the rate the fund credits, not the portfolio return. `income` is recomputed here rather than reused from
    # `net_cash_to_liquid`, which owns its own local copy — the first version of this line referenced a `Y`
    # that does not exist in this scope and would have raised on the first call.
    dW_P = (p.pension_contribution_rate * income(state, u, p) * pension_working_gate(person.age, p)
            + p.pension_interest * w.W_P)

    # Pillar 3a. The contribution is the same flow `net_cash_to_liquid` deducts, computed from the same helper
    # so the money cannot both stay in the account and enter the stock.
    dW_3a = pillar3a_flow(income(state, u, p), person.age, p) + p.pillar3a_interest * w.W_3a
    dW_hol = p.mu_R * w.W_hol

    # Debt: amortises down between events, floored at D ≥ 0 (spec §5.7).
    dD = -u.p_A * debt_gate(w.D)

    # Expertise: logistic growth + compounding − depreciation (spec §5.8), per component.
    # Time enters through `learning_effect`, which saturates at a 20 h/week knee.
    growth_E = (p.alpha_E * learning_effect(u.tau_E, p) + p.kappa_E * u.m_E) + p.beta_E * E
    dE = growth_E * (1.0 - E / p.K_E) - p.delta_E * E

    # Network: logistic with ceiling raised by E and W (spec §5.9).
    # Time enters through `network_effect`, which saturates at a 10 h/week knee.
    K_N = network_ceiling(state, p)
    growth_N = (p.alpha_N * network_effect(u.tau_N, p) + p.kappa_N * u.m_N) + p.beta_N * person.N
    dN = growth_N * (1.0 - person.N / K_N) - p.delta_N * person.N

    # Health: recovers with rest, decays faster under overwork (spec §5.10).
    # Time enters through `rest_effect`: diminishing returns in the hours, on top of the
    # existing saturation in the health level.
    dH = p.alpha_H * rest_effect(u.tau_H, p) * (1.0 - person.H / p.K_H) - delta_H(u.tau_Y, p) * person.H

    # The habit adjusts toward recent consumption (book eq. 29.10):  d(kappa) = alpha_kappa * (C - kappa) dt.
    # A stock, not a capital: it has no ceiling and no depreciation, it simply chases what is being spent.
    dKappa = p.alpha_kappa * (u.C - habit_of(state, p))

    # Venture maturities ramp logistically toward 1 (Q2).
    dMaturity = np.array([v.maturity_drift() for v in person.ventures], dtype=float)

    return Deriv(dW_L=dW_L, dW_R=dW_R, dD=dD, dE=dE, dN=dN, dH=dH, dW_res=dW_res, dW_hol=dW_hol, dW_P=dW_P, dW_3a=dW_3a,
                 dKappa=dKappa, dMaturity=dMaturity)


def diffusion(state: State, u: Control, p: Params) -> Deriv:
    """g(x, u): volatility coefficients (multiply √Δt · Z). σ scales the noise
    per the SDE system (spec §5.12). Deterministic skeleton uses none of this."""
    w = state.wealth
    person = state.person
    # Only the volatilities the spec attaches noise to; expertise/network/health
    # noise (σ_E, σ_N, σ_H) enter at the feasibility stage — kept 0 here until
    # those parameters are calibrated.
    return Deriv(
        dW_L=sigma_P(u.theta, p) * w.W_L,
        dW_R=p.sigma_R * w.W_R,
        dD=0.0,
        dE=np.zeros_like(person.E.components),
        dN=0.0,
        dH=0.0,
        # Age carries no noise: nobody's birthday is stochastic. Stated rather than left to the default, because
        # the drift's `dAge` default is 1.0 and inheriting that here would make age advance twice per step.
        dAge=0.0,
        dMaturity=np.zeros(len(person.ventures)),
    )
