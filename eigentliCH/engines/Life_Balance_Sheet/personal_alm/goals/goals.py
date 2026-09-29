"""Goals as regions of the state space (spec §7 / book Chapter 7).

Each goal is a triple (deadline, region, confidence) — Definition 1.1. We
represent the region by a *slack* function g(x, u, p): the trajectory is in the
region iff g ≥ 0. Reporting slack (not just a boolean) is what feeds both the
Monte-Carlo probability and the CVaR surrogate (spec §8).

Four archetypes cover most of a life:
  - home        — lump claim + serviceability   (§7.1, eq. 7.1)
  - company     — joint region (intersection)   (§7.2, eq. 7.2)
  - retirement  — liability stream / funding ratio (§7.3, eq. 7.3–7.4)
  - fi          — counterfactual independence    (§7.4, eq. 7.6)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..model.controls import Control
from ..model.dynamics import ahv_pension, earning_power, income
from ..model.params import Params
from ..model.state import State

# Slack signature: (state, params, control) → float. ≥ 0 means "in the region".
SlackFn = Callable[[State, Params, Control], float]


@dataclass
class Goal:
    name: str
    kind: str
    slack: SlackFn
    horizon_years: float
    epsilon: float = 0.10           # failure tolerance (1 − confidence)
    mode: str = "at_deadline"       # "at_deadline" | "by_deadline"

    @property
    def confidence(self) -> float:
        return 1.0 - self.epsilon


def indexed_spend(amount: float, pi: float, horizon_years: float) -> float:
    """A spend target carried forward to the deadline at the indexing rate `pi`.

    **Why this exists (3 August 2026).** `Params.pi` was defined and never read, so nothing in the engine was
    inflation-indexed. That is not a cosmetic omission: `fi_slack` tests *nominally grown* wealth against a target
    in *today's* francs, so every financial-independence and retirement goal was systematically easier than it
    should be, and every household reached independence earlier than it would.

    **Applied at the horizon, not per step, because both affected goals are `at_deadline`.** The FI and retirement
    regions ask "is this true at the deadline", so the francs that matter are the deadline's francs. A
    `by_deadline` goal such as the home purchase is deliberately *not* indexed here — a property price moves with
    `mu_R`, which is a different quantity from a lifestyle spend, and conflating them would double-count.

    Used on both the numpy path (`fi_goal`, `retirement_goal`) and the symbolic one (`spec.symbolic_slack`), so the
    optimiser and the simulator test the same target. That parity is the point: an indexed simulator against a
    nominal optimiser would be worse than no indexing at all.

    `pi` is currently **0.0** by decision, so this returns `amount` unchanged. The mechanism is live so that
    changing the rate is a one-number change.
    """
    if pi == 0.0:
        return amount
    return amount * (1.0 + pi) ** horizon_years


# --- Financial independence (counterfactual, §7.4) --------------------------------

def fi_goal(
    *,
    G: float,
    swr: float,
    h_res: float = 0.0,
    horizon_years: float,
    epsilon: float = 0.10,
    include_debt_service: bool = False,
) -> Goal:
    """Independence: switch off labour income and ask whether passive cash flow
    plus a safe drawdown still covers desired spend (eq. 7.6):

        NL = y_R·W_inv + swr·Ω_draw ≥ G

    G is lifestyle spend net of debt service by default (the Nicolas convention);
    set include_debt_service=True to require passive income to also cover i·D.

    **This docstring stated the bug as the design until 3 August 2026 (step 3).** It read: "With h_res = 0 the
    residence contributes only through its operating yield y_R·W_R, not through drawable wealth — the
    illiquidity trap." The first half is the error. A residence you live in produces *no* operating yield, so
    crediting it with `y_R·W_R` was the one thing it should not have done, and the sentence presented that as
    the deliberate treatment. The illiquidity trap is real and survives: the residence is excluded from
    drawable wealth at `h_res ≈ 0`. What it must also be excluded from is the rent.

    This is the same error the book makes at eq. 29.17 and in its flagship case, where a residence explicitly
    "walled off at a zero haircut" is nonetheless credited ~CHF 51 000 of operating yield. See
    `BOOK_REVISION_SCOPE.md`.
    """

    def slack(x: State, p: Params, u: Control) -> float:
        draw = x.wealth.drawable(h_res=h_res, q_inv=p.q_inv, q_hol=p.q_hol)
        nl = p.y_R * x.wealth.W_inv + p.y_hol * x.wealth.W_hol + swr * draw
        # The spend is carried to the deadline at `p.pi`; debt service is not, since it is a nominal
        # contractual amount rather than a lifestyle. See `indexed_spend`.
        claim = indexed_spend(G, p.pi, horizon_years)
        claim += p.i * x.wealth.D if include_debt_service else 0.0
        return nl - claim

    return Goal(name="financial independence", kind="fi", slack=slack,
                horizon_years=horizon_years, epsilon=epsilon, mode="at_deadline")


# --- Home (lump + serviceability, §7.1) ------------------------------------------

def home_goal(
    *,
    price: float,
    xi: float | None = None,
    i_calc: float | None = None,
    maint_rate: float = 0.01,
    affordability: float = 1.0 / 3.0,
    horizon_years: float,
    epsilon: float = 0.20,
) -> Goal:
    """Buying at price P needs a deposit AND income to service the loan at a
    stressed rate (eq. 7.1). Slack is the binding (minimum) of the two, each
    normalised by the price so they are comparable:

        deposit:        W_L ≥ ξ·P
        serviceability: i_calc·D_new + p_A_req + maint ≤ affordability·Y_annual
                        with D_new = (1 − ξ)·P
    """

    def slack(x: State, p: Params, u: Control) -> float:
        _xi = p.xi if xi is None else xi
        _icalc = p.i_calc if i_calc is None else i_calc
        deposit_slack = (x.wealth.W_L - _xi * price) / price

        D_new = (1.0 - _xi) * price
        Y = income(x, u, p)
        # Required annual outlay at the stressed rate + maintenance; amortisation
        # to a third over ~15y is folded into i_calc conservatively here.
        outlay = _icalc * D_new + maint_rate * price
        serviceability_slack = (affordability * Y - outlay) / price
        return min(deposit_slack, serviceability_slack)

    return Goal(name="home purchase", kind="home", slack=slack,
                horizon_years=horizon_years, epsilon=epsilon, mode="by_deadline")


# --- Company (joint region, §7.2) ------------------------------------------------

def company_goal(
    *,
    B_buffer: float,
    N_min: float,
    E_min: float,
    horizon_years: float,
    epsilon: float = 0.25,
) -> Goal:
    """Founding requires a cash buffer AND network AND expertise simultaneously
    above threshold (eq. 7.2) — the intersection, no substitution. Slack is the
    minimum of the three normalised margins, so the binding sub-condition shows."""

    def slack(x: State, p: Params, u: Control) -> float:
        person = x.person
        buf = (x.wealth.W_L - B_buffer) / max(B_buffer, 1.0)
        net = (person.N - N_min) / max(N_min, 1e-6)
        exp = (person.E.aggregate() - E_min) / max(E_min, 1e-6)
        return min(buf, net, exp)

    return Goal(name="company founding", kind="company", slack=slack,
                horizon_years=horizon_years, epsilon=epsilon, mode="by_deadline")


# --- Retirement (liability stream, §7.3) -----------------------------------------

def _annuity_pv_factor(rate: float, years: float) -> float:
    """PV of 1/yr paid continuously for `years` at discount `rate`."""
    if abs(rate) < 1e-9:
        return years
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def retirement_goal(
    *,
    G_ret: float,
    years_in_retirement: float,
    r_disc: float = 0.02,
    horizon_years: float,
    epsilon: float = 0.15,
    h_res: float = 0.0,
) -> Goal:
    """Retirement is funded when assets plus the PV of future non-labour income
    cover the PV of future consumption (eq. 7.3):

        F = (Ω_draw + PV_nonlabour) / PV_liabilities ≥ 1

    A simplified v1: PV_liabilities is an annuity on G_ret over the retirement
    horizon; PV_nonlabour capitalises the property's operating yield. Slack = F − 1.

    **The three pillars count here and nowhere else, by decision of 3 August 2026.** They are excluded from
    `drawable` and from the FI test, because those ask what is spendable *now* — and pillar-2 capital, 3a
    capital and an AHV entitlement are none of them. But this ratio asks what funds *retirement*, and the
    pillars are precisely what funds retirement. Excluding them told a 52-year-old with CHF 475 000 of pension
    capital and a full AHV record that she was destitute, which is not conservatism but a category error.

    The asymmetry is the point and is worth stating rather than smoothing: the same capital is invisible to one
    goal and decisive for another, because the two goals ask different questions of it.
    """

    def slack(x: State, p: Params, u: Control) -> float:
        af = _annuity_pv_factor(r_disc, years_in_retirement)
        # The retirement spend is carried to the deadline at `p.pi`, as the FI goal's is. Note the annuity
        # factor already discounts *within* retirement at `r_disc`; this indexes the spend *up to* the
        # deadline, which is a different span and not a double count. See `indexed_spend`.
        pv_liab = indexed_spend(G_ret, p.pi, horizon_years) * af
        # `W_inv`, not `W_R`, since 3 August 2026 (step 3): only let property yields rent. This is the term
        # worth about a third of hh-0013's retirement income, and it was the residence's phantom rent.
        #
        # AHV is capitalised at the same annuity factor. It is evaluated at the *deadline* age, so a goal dated
        # before the reference age correctly capitalises nothing — the gate in `ahv_pension` does that work.
        person = x.person
        ahv_at_deadline = ahv_pension(
            earning_power(person.E.aggregate(), person.N, person.age + horizon_years, p),
            person.age + horizon_years,
            p,
        )
        pv_nonlabour = (p.y_R * x.wealth.W_inv + p.y_hol * x.wealth.W_hol + ahv_at_deadline) * af
        # Pillar-2 and 3a capital enter at face value rather than through a haircut: unlike property they are
        # cash at the moment they become available, and this ratio is evaluated at a deadline on or after that
        # moment. A household retiring *before* either becomes accessible is a case this v1 does not express.
        pillars = x.wealth.W_P + x.wealth.W_3a
        assets = x.wealth.drawable(h_res=h_res, q_inv=p.q_inv, q_hol=p.q_hol) + pillars + pv_nonlabour
        F = assets / max(pv_liab, 1.0)
        return F - 1.0

    return Goal(name="retirement funding", kind="retirement", slack=slack,
                horizon_years=horizon_years, epsilon=epsilon, mode="at_deadline")
