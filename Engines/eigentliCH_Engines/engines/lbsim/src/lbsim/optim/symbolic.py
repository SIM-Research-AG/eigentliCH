"""Symbolic (CasADi) mirror of the dynamics (spec §5–6).

lbsim port (agent C, 29.09.2026): the draft's ``optim/symbolic.py`` verbatim against ``lbsim.model``, plus
``allocation_step`` and ``measure_slack`` at the end (the market adapter of LBSIM-07; see ``lbsim.optim.market``).
The draft's text below is the draft's.

This re-expresses the drift, diffusion and one Euler–Maruyama step as CasADi
expressions so IPOPT can autodiff them — and, through the multipliers on the
resulting state-transition constraints, hand back the costates (spec §10.2–10.3,
§13). It must stay numerically aligned with model/dynamics.py; the shared
parameter table (Params) and a cross-check test keep the two honest.

State vector x = [W_L, W_R, D, E, N, H, age, W_res, W_hol, W_P, W_3a, kappa]  (v1: scalar expertise, one person).
`W_R` is the real-asset TOTAL; `W_res` is the residence, `W_hol` second homes, and the LET share is the
remainder `W_R − W_res − W_hol`. Only the let share earns; `W_hol` yields NEGATIVE (`y_hol`).
`W_P` is pillar-2 and `W_3a` pillar-3a capital. Both are wealth-tax exempt and therefore outside `net_worth`;
`W_3a`'s contributions additionally reduce taxable income, which makes it the only state that touches the tax
function rather than only the wealth block.
Control    u = [τ_Y, τ_E, τ_N, τ_H, C, m_E, m_N, p_A, θ].
Shock      z = [z_W, z_R]  (correlated wealth shocks; other capitals noiseless).
"""

from __future__ import annotations

import casadi as ca

from ..model.params import Params

# State / control indices.
#
# `AGE` joined on 3 August 2026 as step 1 of the state-vector revision (PLAN_2026-08.md §0B), inert by design so
# the dimension change could be proved on a state whose correct outcome was "every published number identical".
# Step 2 then gave it work: `_earning_power` reads it for the late-career decline, so it is no longer inert.
#
# `W_RES` joined the same day as step 3 — the residence share of `W_R`. It is **appended rather than inserted
# beside `W_R`** so that no existing index shifts: `problem.py` and four test modules address states positionally,
# and a tidier ordering would have silently repointed every one of them.
# `W_P` joined on 3 August 2026 as step 4 — pillar-2 capital. Appended for the same reason as the two before
# it: `problem.py` and three test harnesses address states positionally, so a tidier ordering beside `W_L`
# would silently repoint every one of them.
W_L, W_R, D, E, N, H, AGE, W_RES, W_HOL, W_P, W_3A, KAPPA = range(12)
TAU_Y, TAU_E, TAU_N, TAU_H, C, M_E, M_N, P_A, THETA = range(9)

#: The dimensions, exported so nothing has to hardcode them again.
#:
#: They were literal `6` and `9` in eight places — `problem.py`, four test modules, both vertcats — and adding one
#: state variable meant finding all of them, which is what this constant is for.
#:
#: It earned its keep on the `W_R` split (step 3): `NX` moved 7 → 8 here and the positional readers followed. What
#: it does *not* cover is a hardcoded literal in a `vertcat` — `diffusion` and `euler_step` each carried a
#: 7-length zero-padded vector that no search for the changed symbol would find, and both had to be widened by
#: hand.
#:
#: **That warning has now served as the checklist three times** — steps 3, 4 and 4b — and the two `vertcat`s
#: needed widening on every one of them. `NX` has moved 6 → 7 → 8 → 9 → 10 → 11 in a single day. The remaining
#: planned change is the first to move `NU` instead: an annuity-versus-lump-sum control for pillar-2 capital,
#: which has to sit *outside* the time simplex, so the positional readers to check are different ones
#: (`Control`'s field order, `_named`, the warm-start, `_u_vec`, and the simplex/box bounds).
NX: int = 12
NU: int = 9

#: State index names, in index order — the missing link that let a state ship unbounded.
#:
#: `NX` counts the states; nothing named them, so nothing could ask "is every state constrained?". Four of
#: eleven (`W_RES`, `W_HOL`, `W_P`, `W_3A`) were added without bounds on 3-4 August 2026 and the optimiser
#: found the gap before any test did — see the comment on the state bounds in `problem.py`.
#:
#: `test_optim.py::test_every_state_is_bounded_per_node` walks this list against the NLP source, and asserts
#: `len(STATE_NAMES) == NX` so the list cannot drift from the count. Adding a twelfth state therefore fails
#: twice over — once until it is named here, again until it is bounded or deliberately exempted — which is
#: the guard rail that was missing.
STATE_NAMES: tuple[str, ...] = (
    "W_L", "W_R", "D", "E", "N", "H", "AGE", "W_RES", "W_HOL", "W_P", "W_3A", "KAPPA",
)

#: States deliberately carrying no NLP bound, with the reason.
#:
#: `AGE` only ever advances at `dt` per step from a fixed initial value; it is uncontrolled and monotone, so
#: there is no direction for the optimiser to push it. It is the one state where "unbounded" is not a gap.
UNBOUNDED_STATES: frozenset[str] = frozenset({"AGE"})

_EPS = 1e-8




def _softplus_pos(x: ca.SX) -> ca.SX:
    """Smooth max(0, x) so the overwork kink stays differentiable for IPOPT."""
    return 0.5 * (x + ca.sqrt(x * x + 1e-6))


# --- Returns to invested time: CasADi twins of model/dynamics ------------------------
#
# These must agree with `model.dynamics.rest_effect / network_effect / learning_effect`
# to the last decimal. The model exists twice — numpy for simulation, CasADi for the
# optimiser — and if the two drift the solver optimises a system nobody simulates.
# `tests/test_model_parity.py` pins them against each other for exactly that reason.

#: 1 − e^(−1), so each saturating shape equals its scale at its scale. Imported from the numpy model rather than
#: restated, because two definitions of one constant is exactly how the two implementations drift apart.
from ..model.dynamics import (  # noqa: E402
    _AHV_GATE_SCALE,
    _CHILD_END_GATE_SCALE,
    _DEBT_GATE_SCALE,
    _PENSION_GATE_SCALE,
    _SATURATION_AT_SCALE,
    _TAU_FLOOR,
)


def _rest_effect(tau_H: ca.SX, p: Params) -> ca.SX:
    """ref^(1−ν)·τ^ν, guarded at zero.

    `tau_H` is bounded below by a hard constraint, but IPOPT evaluates outside its bounds during line searches,
    and a fractional power of a negative number is NaN — which would poison the whole solve rather than fail
    visibly. `fmax` is used rather than the softplus above because this needs a hard floor, not a smooth one:
    the derivative at the floor does not matter when the floor is never the optimum.
    """
    safe = ca.fmax(tau_H, _TAU_FLOOR)
    return (p.tau_H_ref ** (1.0 - p.nu_H)) * safe ** p.nu_H


def _saturating(tau: ca.SX, scale: float) -> ca.SX:
    """s·(1 − e^(−τ/s))/(1 − e^(−1)). Smooth everywhere, so no guard is needed."""
    return scale * (1.0 - ca.exp(-ca.fmax(tau, 0.0) / scale)) / _SATURATION_AT_SCALE


def _drawable_real(x: ca.SX, h_res: float, q_inv: float, q_hol: float = 0.0) -> ca.SX:
    """The real-asset contribution to drawable wealth: CasADi twin of `HouseholdWealth.drawable`'s tail.

    Debt is apportioned pro rata, `D·W_res/W_R` and `D·W_inv/W_R`, for the reasons on that method — attaching it
    all to the residence made the term negative whenever debt exceeded the residence. Defined once here rather
    than inlined in both slack functions, because two copies of one idea is how the debt gate went wrong (M67).

    `W_R = 0` is a legitimate state — a household with no property — and IPOPT will evaluate there, so the shares
    are `0/0`. **The branch is not cosmetic: without it the two transcriptions disagree.** The numpy side reduces
    to `W_L − h_res·D` at `W_R = 0` (inherited from the old single-haircut formula), whereas an epsilon-guarded
    division silently drops the debt and returns `W_L`. That divergence needs `W_R = 0` *and* `D > 0` *and*
    `h_res > 0` together, which no current test hits and production never reaches at `h_res = 0.0` — which is
    precisely why it would have sat there unnoticed. All debt goes to the residence share when there is no stock
    to apportion against, matching numpy.
    """
    W_inv = ca.fmax(0.0, x[W_R] - x[W_RES] - x[W_HOL])
    degenerate = x[W_R] <= _EPS
    total = ca.if_else(degenerate, 1.0, x[W_R])
    res_share = ca.if_else(degenerate, 1.0, x[W_RES] / total)
    inv_share = ca.if_else(degenerate, 0.0, W_inv / total)
    hol_share = ca.if_else(degenerate, 0.0, x[W_HOL] / total)
    return (q_inv * (W_inv - x[D] * inv_share)
            + q_hol * (x[W_HOL] - x[D] * hol_share)
            + h_res * (x[W_RES] - x[D] * res_share))


def _smin(a: ca.SX, b: ca.SX) -> ca.SX:
    """Smooth min — keeps the joint-region (min-of-margins) slack differentiable,
    which IPOPT needs on the CVaR constraint. Slacks are O(0.1), so ε = 1e-4 is a
    tight, harmless rounding of the kink."""
    return 0.5 * (a + b - ca.sqrt((a - b) ** 2 + 1e-4))


def _earning_power_at(x: ca.SX, age: ca.SX, p: Params) -> ca.SX:
    """`_earning_power` evaluated at an arbitrary age rather than the state's own.

    Needed because the retirement goal capitalises AHV at the *deadline* age, not at today's. Factored out
    rather than duplicated: the income law now has two callers with different ages, and two copies of it is how
    the debt gate and the pension gate both went wrong.
    """
    E_ = ca.fmax(x[E], _EPS)
    N_ = ca.fmax(x[N], _EPS)
    skill = ca.fmin(1.0, p.earning_power_at_unit * E_ ** p.a * N_ ** p.b)
    ratio = p.earning_power_max / p.earning_power_min
    over = ca.fmax(0.0, age - p.earning_peak_age)
    raw = p.earning_power_min * ratio ** skill * (1.0 - p.earning_decline) ** over
    return ca.fmin(p.earning_power_max, ca.fmax(p.earning_power_min, raw))


def _earning_power(x: ca.SX, p: Params) -> ca.SX:
    """CasADi twin of ``model.dynamics.earning_power``. Must agree; ``test_model_parity`` enforces it.

    ``fmin``/``fmax`` give the clamp. They are non-differentiable at the bounds, which is acceptable here for the
    same reason the rest floor is: IPOPT is prevented from evaluating outside variable bounds, and at an *interior*
    clamp the subgradient CasADi returns is one-sided but finite, so a solve that hits the ceiling stalls rather
    than producing NaN. If the ceiling turns out to bind often, this wants a softmin instead.
    """
    E_ = ca.fmax(x[E], _EPS)
    N_ = ca.fmax(x[N], _EPS)
    skill = ca.fmin(1.0, p.earning_power_at_unit * E_ ** p.a * N_ ** p.b)
    ratio = p.earning_power_max / p.earning_power_min
    over = ca.fmax(0.0, x[AGE] - p.earning_peak_age)
    raw = p.earning_power_min * ratio ** skill * (1.0 - p.earning_decline) ** over
    return ca.fmin(p.earning_power_max, ca.fmax(p.earning_power_min, raw))


#: Smoothing width for `_smooth_min`, in CHF. Must equal `model.dynamics._SMOOTH_MIN_EPS`; parity enforces it.
_SMOOTH_MIN_EPS: float = 100.0


def _smooth_min(a: ca.SX, b: ca.SX, eps: float = _SMOOTH_MIN_EPS) -> ca.SX:
    """min(a, b), differentiable everywhere. Twin of `model.dynamics._smooth_min`.

    Used for the AHV couple cap rather than `fmin` because that ceiling **binds by design** for any couple with
    two decent records. The comment on `_earning_power`'s clamps says a ceiling that binds often "wants a softmin
    instead"; measurement showed that one never binds, so it stayed hard. This one is the opposite case, so it is
    smooth from the start rather than after a stalled solve teaches the same lesson twice.
    """
    d = a - b
    return 0.5 * (a + b - ca.sqrt(d * d + eps * eps))


def _ahv_individual(average_income: ca.SX, age: ca.SX, record_share: float, p: Params) -> ca.SX:
    """One person's AHV entitlement. Twin of `model.dynamics._ahv_individual`."""
    share = ca.fmin(1.0, ca.fmax(0.0, average_income) / max(p.ahv_income_for_max, 1.0))
    full = p.ahv_full_single * max(0.0, min(1.0, record_share))
    entitled = full * (0.5 + 0.5 * share)
    gate = 0.5 * (1.0 + ca.tanh((age - (p.ahv_age - 0.5)) / _AHV_GATE_SCALE))
    return entitled * gate


def _ahv_household(x: ca.SX, p: Params, age: ca.SX | None = None) -> ca.SX:
    """Household AHV: the subject's entitlement, plus an exogenous partner's, capped at 150% (H1).

    `age` overrides the state's age so the retirement goal can evaluate this at its deadline age, the same reason
    `_earning_power_at` exists. Twin of `model.dynamics.ahv_pension`.
    """
    age_ = x[AGE] if age is None else age
    own = _ahv_individual(_earning_power_at(x, age_, p), age_, p.ahv_record_share, p)
    if not p.has_partner:
        return own
    partner = _ahv_individual(p.partner_income, age_ + p.partner_age_offset,
                              p.partner_ahv_record_share, p)
    # No separate "both retired" gate: each entitlement is age-gated, so the sum cannot reach the 150% cap until
    # the second partner is drawing.
    return _smooth_min(own + partner, p.ahv_couple_cap_multiple * p.ahv_full_single)


def _child_costs(x: ca.SX, p: Params) -> ca.SX:
    """Twin of `model.dynamics.child_costs`. Total annual child cost at the subject's age `x[AGE]`.

    The LEVEL is a plain Python number — it depends on the child count and household shape, both fixed over a
    solve — so it is computed once by the numpy side rather than transcribed a second time. That is deliberate:
    two copies of one piece of arithmetic is exactly how the debt gate and the pension gate both went wrong
    (M67). What must be symbolic is the part that depends on `x[AGE]`, which is the ageing, and that is here.

    Returns a plain Python zero for a childless household, so the expression graph is untouched when there are
    no children and no parity test has to be re-run to believe it.

    **The zero and the accumulator are Python floats, not `ca.SX`, and that is not a style choice.** `drift` is
    transcribed with `SX` symbols in `problem.py` and with `MX` symbols elsewhere in the solver stack, and every
    other expression here inherits its type from `x`. Seeding the sum with `ca.SX(0.0)` pinned the result to SX
    and made `net_cash - kids` raise `unsupported operand type(s) for -: 'MX' and 'SX'` — seventeen tests, none
    of them about children. A Python float mixes with both.
    """
    from ..model.dynamics import child_cost_level  # noqa: PLC0415 - avoids a circular import at module load

    young, older = child_cost_level(p)
    if young == 0.0 and older == 0.0:
        return 0.0
    shift = x[AGE] - p.child_reference_age
    total = 0.0
    for a in p.child_ages:
        child_age = float(a) + shift
        # Two widths on purpose: the band change is gradual, the end of an education is a date. See
        # `model.dynamics._child_cost_at_age` for the measurement that forced the narrower end gate.
        band = 0.5 * (1.0 + ca.tanh((child_age - p.child_cost_age_split) / _PENSION_GATE_SCALE))
        ended = 0.5 * (1.0 - ca.tanh((child_age - p.child_cost_end_age) / _CHILD_END_GATE_SCALE))
        total = total + (young * (1.0 - band) + older * band) * ended
    return total


def drift(x: ca.SX, u: ca.SX, p: Params) -> ca.SX:
    """f(x, u): matches model.dynamics.drift (venture income omitted — the forward
    problem seeds no new venture)."""
    E_ = ca.fmax(x[E], _EPS)
    N_ = ca.fmax(x[N], _EPS)
    H_ = ca.fmax(x[H], _EPS)

    Y = _earning_power(x, p) * u[TAU_Y] * H_ ** p.c
    # Let share only (step 3). `fmax` clamps the same way `HouseholdWealth.W_inv` does, so a `W_res` above `W_R`
    # cannot manufacture negative rent on either side of the parity test.
    W_inv = ca.fmax(0.0, x[W_R] - x[W_RES] - x[W_HOL])
    asset_yield = p.y_R * W_inv + p.y_hol * x[W_HOL]
    interest = p.i * x[D]
    # Pillar 3a: the contribution leaves the account AND reduces the tax base. Both effects, or the money is
    # counted twice — it is the only inflow in this model that moves the tax base, so it is the only place the
    # two sides of that have to be written out. Mirrors `model.dynamics.pillar3a_flow`: intended amount, capped,
    # floored by affordability, then the same one-year `tanh` age gate.
    # AHV. Twin of `model.dynamics.ahv_pension`, including its two non-obvious properties: the entitlement is
    # capped above `ahv_income_for_max` (regressive), and the age gate is centred half a year early at a quarter
    # scale so 65 pays ~98% rather than the 50% a symmetric gate would give.
    ahv = _ahv_household(x, p)

    _intended_3a = min(p.pillar3a_contribution, p.pillar3a_cap)
    _gate_3a = 0.5 * (1.0 - ca.tanh((x[AGE] - p.pillar3a_age) / _PENSION_GATE_SCALE))
    contrib_3a = ca.fmin(_intended_3a, ca.fmax(0.0, Y)) * _gate_3a

    # Pillar 2 leaves cash as well as entering W_P — see `model.dynamics.net_cash_to_liquid`. Omitting this
    # made the model create 15% of income out of nothing every year.
    pension_gate_cash = 0.5 * (1.0 - ca.tanh((x[AGE] - p.pension_age) / _PENSION_GATE_SCALE))
    contrib_p2 = p.pension_contribution_rate * Y * pension_gate_cash

    # `p.partner_income` (H1) is added below with the tax base, where `Y_partner` is defined, so the cash identity
    # and the taxable base cannot disagree about whether the partner earns.
    # Children: a cash outflow that rises with their age and then ends. Not deducted from the tax base — see
    # the note in `model.dynamics.net_cash_to_liquid` for why this model has no allowance structure to hang a
    # child deduction on.
    kids = _child_costs(x, p)
    net_cash_before_partner = (Y + ahv + asset_yield - u[C] - u[M_E] - u[M_N] - interest - u[P_A]
                               - contrib_3a - contrib_p2 - kids)

    # Taxes (must match model/dynamics income_tax / wealth_tax exactly).
    #
    # H1: the partner's exogenous income is household cash and part of the joint tax base, and
    # `tax_split_factor` taxes the combined income as `f` shares at the single tariff (Vollsplitting). At the
    # default `f = 1.0` both lines are algebraically the single-person expressions.
    Y_partner = p.partner_income if p.has_partner else 0.0
    net_cash = net_cash_before_partner + Y_partner
    taxable = ca.fmax(0.0, Y + Y_partner + ahv + asset_yield - interest - contrib_3a)
    _f = max(1.0, p.tax_split_factor)
    income_tax = _f * (p.tax_rate_max * (taxable / _f)
                       * (1.0 - ca.exp(-(taxable / _f) / p.tax_income_scale)))
    net_worth = x[W_L] + x[W_R] - x[D]
    wealth_tax = p.wealth_tax_rate * ca.fmax(0.0, net_worth)

    mu_P = p.r_f + u[THETA] * (p.mu_M - p.r_f)
    dW_L = net_cash - income_tax - wealth_tax + mu_P * x[W_L]

    dW_R = p.mu_R * x[W_R]

    # Amortisation is gated on there being debt to amortise. **This gate was missing until 3 August 2026, and
    # `tests/test_model_parity.py` found it on its first real run** — `model/dynamics.drift` has always had
    # `-p_A if D > 0 else 0`, while this side subtracted `p_A` unconditionally. So the optimiser was solving a
    # system in which paying down a zero balance still reduced it, driving `D` negative.
    #
    # `problem.py`'s `D >= 0` state constraint masked the consequence, which is why nothing failed: a constraint
    # was doing work the dynamics should have done. That is a poor division of labour — the constraint cannot
    # distinguish "this is impossible" from "this is merely unwise", and the solver saw a slightly wrong system
    # near D = 0 in every solve.
    #
    # The gate itself is defined in `model.dynamics.debt_gate` and its scale is imported, not restated: a bug
    # caused by two copies of one idea should not be fixed by writing a third. `tanh` rather than `D/(D + s)`
    # because the rational form is asymptotic and under-amortises by 3.3e-6 at *any* real debt level, which is a
    # systematic error; `tanh` is exactly 1.0 in float64 beyond about CHF 2 000. See that docstring.
    dD = -u[P_A] * ca.tanh(ca.fmax(x[D], 0.0) / _DEBT_GATE_SCALE)

    # Time enters the three capitals through its shape functions, not linearly (M67).
    growth_E = (p.alpha_E * _saturating(u[TAU_E], p.tau_E_scale) + p.kappa_E * u[M_E]) + p.beta_E * x[E]
    dE = growth_E * (1.0 - x[E] / p.K_E) - p.delta_E * x[E]

    # `N̄ = N_0 + λ_E E + λ_W Ω + λ_κ κ` — book eq. 29.11, twin of `dynamics.network_ceiling`. Additive, on
    # NET worth, with the habit term; the multiplicative form on gross wealth was retired on 25 August 2026.
    # The two scales (Ω over `W_scale`, κ over `swr·W_scale`) are the author's decision recorded there.
    K_N = (p.N_0
           + p.lambda_E * x[E]
           + p.lambda_W * (x[W_L] + x[W_R] - x[D]) / p.W_scale
           + p.lambda_kappa * x[KAPPA] / (p.swr * p.W_scale))
    growth_N = (p.alpha_N * _saturating(u[TAU_N], p.tau_N_scale) + p.kappa_N * u[M_N]) + p.beta_N * x[N]
    dN = growth_N * (1.0 - x[N] / K_N) - p.delta_N * x[N]

    overwork = _softplus_pos(u[TAU_Y] - p.tau_Y_star)
    delta_H = p.delta_H0 + p.eta * overwork
    dH = p.alpha_H * _rest_effect(u[TAU_H], p) * (1.0 - x[H] / p.K_H) - delta_H * x[H]

    # The residence appreciates at the same rate as the stock it is part of, which holds the residence *share*
    # constant rather than the residence *amount*. That is the intended reading: `mu_R` is a property-market
    # return and does not care which door the owner walks through. A household that lets out a room, or buys a
    # second flat, changes `W_res` through an input rather than through drift.
    dW_RES = p.mu_R * x[W_RES]
    dW_HOL = p.mu_R * x[W_HOL]

    # Pillar 2 (step 4). `Y` above is the same labour income the numpy side recomputes, so the two agree by
    # construction rather than by coincidence. The retirement switch is a `tanh` over one year using the scale
    # imported from `model.dynamics` — the gate must be smooth for IPOPT, and defining it once is the lesson the
    # debt gate taught (M67).
    pension_gate = 0.5 * (1.0 - ca.tanh((x[AGE] - p.pension_age) / _PENSION_GATE_SCALE))
    dW_P = p.pension_contribution_rate * Y * pension_gate + p.pension_interest * x[W_P]
    dW_3A = contrib_3a + p.pillar3a_interest * x[W_3A]

    # d(age)/dt = 1, matching `model.dynamics.Deriv.dAge`. Age is a state in the bookkeeping sense: it advances
    # by the same mechanism as everything else so the integrator cannot forget it.
    # The habit chases consumption: d(kappa) = alpha_kappa * (C - kappa), book eq. 29.10.
    dKAPPA = p.alpha_kappa * (u[C] - x[KAPPA])

    return ca.vertcat(dW_L, dW_R, dD, dE, dN, dH, 1.0, dW_RES, dW_HOL, dW_P, dW_3A, dKAPPA)


def diffusion(x: ca.SX, u: ca.SX, p: Params) -> ca.SX:
    """g(x, u): volatility coefficients (only the two wealth shocks carry noise)."""
    sigma_P = u[THETA] * p.sigma_M
    # Age carries no noise: nobody's birthday is stochastic.
    #
    # **`W_res` carries no noise either, and that is provisional rather than principled.** Strictly it should
    # take the same proportional shock as `W_R`, since a residence sits in the same property market — otherwise
    # a large negative shock to `W_R` can push it below `W_res` and the `fmax` clamp in `drift` starts doing
    # load-bearing work. It is left at zero because `Deriv.dW_res` defaults to zero on the numpy side, so this
    # is what keeps the two transcriptions in exact agreement, and because **step 5 deletes the diffusion term
    # altogether** (PLAN_2026-08.md §0B). Inventing a correlation structure days before removing it would be
    # work spent on something about to be deleted. Revisit if step 5 slips.
    # Twelve entries. The habit carries no noise: it follows consumption, which is a control.
    return ca.vertcat(sigma_P * x[W_L], p.sigma_R * x[W_R], 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def euler_step(x: ca.SX, u: ca.SX, z: ca.SX, p: Params, dt: float) -> ca.SX:
    """One Euler–Maruyama step (spec §10.1). z = [z_W, z_R] already correlated."""
    f = drift(x, u, p)
    g = diffusion(x, u, p)
    sqrt_dt = dt ** 0.5
    noise = ca.vertcat(g[0] * sqrt_dt * z[0], g[1] * sqrt_dt * z[1], 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    return x + f * dt + noise


def income_sx(x: ca.SX, u: ca.SX, p: Params) -> ca.SX:
    """Symbolic labour income Y (spec §5.1), for goals whose region depends on it."""
    E_ = ca.fmax(x[E], _EPS)
    N_ = ca.fmax(x[N], _EPS)
    H_ = ca.fmax(x[H], _EPS)
    return _earning_power(x, p) * u[TAU_Y] * H_ ** p.c


def fi_slack(x: ca.SX, *, G: float, swr: float, h_res: float, y_R: float, q_inv: float = 0.0,
             y_hol: float = 0.0, q_hol: float = 0.0) -> ca.SX:
    """Symbolic FI slack g = y_R·W_inv + swr·Ω_draw − G (eq. 7.6).

    Mirrors `HouseholdWealth.drawable` and `goals.fi_goal` after the step-3 split: rent from the let share
    only, and two haircuts rather than one. Reduces to the pre-split expression exactly when `W_res = W_R`.
    """
    W_inv = ca.fmax(0.0, x[W_R] - x[W_RES] - x[W_HOL])
    draw = x[W_L] + _drawable_real(x, h_res, q_inv, q_hol)
    return y_R * W_inv + y_hol * x[W_HOL] + swr * draw - G


def home_slack(x: ca.SX, u: ca.SX, p: Params, *, price: float, xi: float,
               i_calc: float, maint_rate: float, affordability: float) -> ca.SX:
    """Symbolic home slack = min(deposit margin, serviceability margin) (eq. 7.1)."""
    deposit = (x[W_L] - xi * price) / price
    D_new = (1.0 - xi) * price
    outlay = i_calc * D_new + maint_rate * price
    serviceability = (affordability * income_sx(x, u, p) - outlay) / price
    return _smin(deposit, serviceability)


def company_slack(x: ca.SX, *, B_buffer: float, N_min: float, E_min: float) -> ca.SX:
    """Symbolic company slack = min of the three normalised margins (eq. 7.2)."""
    buf = (x[W_L] - B_buffer) / max(B_buffer, 1.0)
    net = (x[N] - N_min) / max(N_min, 1e-6)
    exp = (x[E] - E_min) / max(E_min, 1e-6)
    return _smin(_smin(buf, net), exp)


def retirement_slack(x: ca.SX, p: Params, *, G_ret: float, years_in_retirement: float,
                     r_disc: float, h_res: float, q_inv: float = 0.0,
                     q_hol: float = 0.0, horizon_years: float = 0.0) -> ca.SX:
    """Symbolic retirement funding slack F − 1 (eq. 7.3). Annuity factor is a
    constant (r_disc, years fixed), so this stays affine in the state.

    Note it stays affine after the step-3 split only because `W_inv` is a difference of two states; the `fmax`
    clamp is the one non-affine element, and it is inactive wherever `W_res <= W_R`, which the state
    constraints enforce.
    """
    if abs(r_disc) < 1e-9:
        af = years_in_retirement
    else:
        af = (1.0 - (1.0 + r_disc) ** (-years_in_retirement)) / r_disc
    pv_liab = G_ret * af
    W_inv = ca.fmax(0.0, x[W_R] - x[W_RES] - x[W_HOL])
    # The three pillars count in this goal and nowhere else — see `goals.retirement_goal` for why the same
    # capital is invisible to the FI test and decisive here. AHV is evaluated at the DEADLINE age, so a goal
    # dated before the reference age capitalises nothing.
    age_at_deadline = x[AGE] + horizon_years
    # Household AHV at the DEADLINE age, so a couple's 150% cap (H1) applies here too rather than only in the
    # cash flow — the retirement goal is the one place the first pillar is capitalised, so uncapping it here
    # would overstate a couple's funding by up to a third of their AHV times the annuity factor.
    ahv_end = _ahv_household(x, p, age=age_at_deadline)
    pv_nonlabour = (p.y_R * W_inv + p.y_hol * x[W_HOL] + ahv_end) * af
    pillars = x[W_P] + x[W_3A]
    assets = (x[W_L] + _drawable_real(x, h_res, q_inv, q_hol)) + pillars + pv_nonlabour
    return assets / max(pv_liab, 1.0) - 1.0


# --- lbsim: the market adapter (LBSIM-07) ----------------------------------------------------------------------
#
# The draft's drift with its market taken out (``market.no_market_params``: mu_M = r_f = mu_R = 0), then the
# per-state terms of one scenario and step, all in today's francs. The numpy twin is
# ``lbsim.optim.market.numpy_allocation_step``; ``tests/optim/test_parity.py`` holds the two together on every
# step length of the grid.

def allocation_step(x, u, p_no_market: Params, dt: float, *, r: float, infl: float, growth: float):
    """One step under the allocation market. ``r`` the portfolio's log return a year in the scenario's state,
    ``infl`` the log inflation over the step, ``growth`` the property's nominal log growth over the step (noise
    included). In the NLP all three are numbers (the scenario is drawn before the NLP is built), so IPOPT sees only
    the state and the controls; the warm-start rollout passes them as symbols of one compiled step."""
    f = drift(x, u, p_no_market)
    market = x[W_L] * (ca.exp(r * dt - infl) - 1.0)
    real_growth = ca.exp(growth - infl) - 1.0
    erosion = ca.exp(-infl) - 1.0
    extra = ca.vertcat(market, x[W_R] * real_growth, x[D] * erosion, 0, 0, 0, 0,
                       x[W_RES] * real_growth, x[W_HOL] * real_growth, x[W_P] * erosion, x[W_3A] * erosion, 0)
    return x + f * dt + extra


#: Weights of a goal measure on (W_L, W_P, W_3a); the table itself is ``lbsim.optim.market.MEASURES``.
def measure_expr(x, measure: str):
    from .market import MEASURES  # noqa: PLC0415 - one table, casadi-free
    w = MEASURES[measure]
    return w["W_L"] * x[W_L] + w["W_P"] * x[W_P] + w["W_3a"] * x[W_3A]


def measure_slack(x, *, measure: str, target: float, level: float = 1.0, extra: float = 0.0):
    """lbsim's goal slack, ``(level * measure(x) + extra - target) / target``.

    ``x`` is in today's francs. A goal in the francs of its date (LBSIM-09) is compared nominally: ``level`` is the
    scenario's price level at the goal node and ``target`` the nominal target. A goal in today's francs has
    ``level = 1`` and the real target. ``extra`` is the zero-return terminal allowance beyond the solve cap (the
    planned saving times the remaining years, in the target's francs). Normalised by the target, so a CVaR of s
    is ``s * target`` francs and the target reachable at the confidence is ``(1 - s) * target`` exactly (CVaR is
    translation-equivariant and the normaliser does not move with the target)."""
    return (float(level) * measure_expr(x, measure) + float(extra) - float(target)) / max(float(target), 1.0)
