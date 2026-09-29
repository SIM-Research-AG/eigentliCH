"""R-133 / C-02: a goal's illustration, or the true reason there is not one.

**The bug this replaces.** `services/goals.py` returned `illustration: None` with the reason
`"no_assumption_set_published"` on every goal, unconditionally, with a comment saying "none is published
yet". One has been published since A69 — `2024-12-31+REG-38d91c1a+RS-874b03c9` — so every goal in the
running application told the member a reason that was false. A35's blocker was lifted and nothing
propagated. That is worse than showing nothing: a client author reading it would go looking for a
publishing step that had already happened.

Every reason this module returns is **derived**, and `no_assumption_set_published` is now emitted only when
the table is genuinely empty. A set that exists but is not yet in effect is a different fact and gets a
different word.

===========================================================================================================
WHAT AN HONEST ILLUSTRATION IS, GIVEN WHAT THE PLAN ACTUALLY HOLDS
===========================================================================================================

`services/engine_inputs.py` is the map, and it rules out the obvious answer. A **trajectory** — "you will
have X by 2031" — needs `initial_wealth` and `annual_return`. Neither is available and neither may be
invented (A69, §12):

  * `initial_wealth` is **not in the plan at all**. `Position.magnitude` is a flow in francs per year or a
    share of a total, never a stock, and its unit is explicit and never inferred (A30). Capitalising a flow
    needs a discount rate; resolving a share needs a total the plan does not hold. Both are assumptions
    under C-02 and neither is published.
  * `annual_return` needs **one blended rate, and the published set deliberately has none**. A69: the role
    profiles and the scenario probabilities are published side by side and nothing multiplies them, because
    which probabilities weight which horizon is a decision with an owner. Multiplying them here would put
    that decision in a service module where nobody would find it again.

So no trajectory is offered, and the goal payload carries the gap list saying exactly that, straight from
`engine_inputs`. What *is* offered is the arithmetic the published set genuinely supports:

**the range of one-year outcomes, per macro scenario, for the roles the member's own funding occupies,
applied to the amount the member named.** Four things, and each traces to a source:

  * the **amount** is `Goal.target_amount` — the member's own number, and labelled as a *stated* amount
    rather than a holding, because the plan does not record what is held;
  * the **roles** are `Position.role` on the active **financial-capital** positions funding this goal —
    the member's own answers, filtered as the section below describes;
  * the **rates** are `role_profiles_by_scenario` from the published AssumptionSet, copied, not composed;
  * the **horizon** is the set's own `return_estimation_years`, which is **one**. It is not extended to the
    goal's own date, and the payload reports both numbers side by side so the member can see the
    difference. The AssumptionSet says why in its own words: a ten-year per-state return is not a one-year
    return compounded, because the regime does not persist for ten years. Compounding this rate over a
    member's eight-year horizon would be the single easiest invented number in the whole build.

**Nothing is blended, weighted, averaged or rounded.** The scenario probabilities travel beside the rates,
as published, and no field multiplies them — `tests/test_illustration.py` forbids one appearing later, the
same guard `test_no_blended_rate_is_published` puts on the set itself.

===========================================================================================================
ONLY FINANCIAL CAPITAL IS PROJECTED — Principle 9, 1 September 2026
===========================================================================================================

**A market return rate was being applied to human capital.** `_funding_roles` grouped `goal.funded_by` by
`Position.role` and never read `capital_type` at all, so a goal funded by a human-capital income position —
a salary — had the ReturnSet's `income` market profile applied to the member's stated income. An audit
measured `rate -0.0593 -> change_chf -14825.0` against somebody's job, with no caveat and no mention of
human capital anywhere in the payload.

That is one click off the default path, which is what makes it the serious kind of defect rather than an
edge case: `services/onboarding.py` gives every member exactly one position, `role="income",
capital_type="human"`, and the containers form offers it in the funding multiselect. Not one of the nine
fixtures in `tests/test_illustration.py` used `capital_type="human"`, which is why every guard in that file
passed over it.

**The rule now: a rate is applied to financial capital and to nothing else.**

  * A goal funded **only** by human capital gets no figure and the derived reason
    `the_goal_is_funded_only_by_human_capital` — its own reason, not `the_goal_names_no_active_funding`,
    because the goal *is* funded and a reason that says otherwise is the false-reason defect A85 fixed.
  * A goal funded by **both** is projected on its financial part and says what it left out.
  * Every response, illustrated or not, carries `excluded_from_the_projection`: one entry per excluded
    position with its id, role, capital type and a **stable reason key** (A12 — the client holds the
    wording). Excluded, never zeroed: a zero rate is a claim that a salary is expected not to move, and
    nobody published that.

Principle 9's testable form is "a summary component that accepts only financial inputs". This is the filter
that makes it true, and `_funding_roles` carries the rest of the argument.

===========================================================================================================
A RATE IS APPLIED TO A BALANCE, AND NEVER TO A FLOW - 1 September 2026
===========================================================================================================

**The stock unit changed what an honest illustration is, and it changed it in two directions.**

The caveat `the_amount_is_stated_by_the_member_and_is_not_a_holding` was not a nicety. It was there because
`MAGNITUDE_UNITS` held a flow and a fraction and nothing else, so the only franc figure this module could
reach was `Goal.target_amount` - what the member says the goal *needs*, which is not what they *have*.
`chf` exists now, so where a member has stated what they hold, the projection is applied to that, and the
caveat is replaced by one that says what the balance actually is (`HELD_BALANCE_CAVEAT`). Where they have
not, nothing changes: the target amount, labelled as stated.

**And the direction that matters more, because it is the one that goes wrong quietly.** A published role
profile is a one-year return: a fraction of a balance. Applying it to a balance gives francs. Applying it to
`chf_per_year` gives francs per year per year, which is not a quantity anybody asked for and renders on a
screen as a perfectly plausible number of francs. Applying it to `share_of_total` gives a bare fraction.
**That is the A105 defect, exactly** - A105 applied an income rate to a salary because `_funding_roles`
never read `capital_type`; this would apply a market rate to an annual flow because nothing read
`magnitude_unit`. Same class, same shape, same one-click-off-the-default-path reach: `services/onboarding.py`
gives every member a `chf_per_year` position and the containers form offers it in the funding multiselect.

So there is exactly **one multiplication in this module** and it is `apply_rate`, which takes the unit as a
required argument and refuses anything that is not a stock. Not a convention, a signature: a caller cannot
multiply without saying what they are multiplying, and a caller who says `chf_per_year` gets a `ValueError`
rather than a figure.

**A liability is not projected as a holding either.** It is a real balance in francs, so nothing dimensional
stops the arithmetic - which is why the check has to be deliberate. A market rate on a mortgage is a claim
that debt grows like equity, and nobody published one. Liabilities are named in
`not_counted_toward_the_held_balance` and never summed into the basis, and never netted out of it either.

**The role vocabularies are mapped here, explicitly, and this is the first place in prototype2 that does
it.** A69 recorded that the estate's ReturnSet calls the first role `gain` where §4 and `models.plan.ROLES`
call it `growth`, and said whatever mapped them first must do it explicitly. `PLAN_ROLE_TO_SET_ROLE` is
that mapping; it is checked against `ROLES` at import, so a fifth role cannot be added to the plan and
silently fall out of every illustration. Both names travel in the payload, so a reader can see that a
translation happened.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ASSET,
    AssumptionSet,
    CAPITAL_TYPES,
    FLOW_UNIT,
    Goal,
    LIABILITY,
    NoAssumptionSet,
    Position,
    ROLES,
    SHARE_UNIT,
    STOCK_UNITS,
)
from .assumptions import current as current_assumption_set
from .engine_inputs import horizon_years, plan_for
from .served import assert_no_engine_artefact

#: A69, made explicit. The estate's ReturnSet names the first role `gain`; §4 and `models.plan.ROLES` name
#: it `growth`. The other three agree. Written as a full mapping rather than as one special case, so the
#: check below covers every role rather than the one that currently differs.
PLAN_ROLE_TO_SET_ROLE = {
    "growth": "gain",
    "income": "income",
    "stabilisation": "stabilisation",
    "protection": "protection",
}

if set(PLAN_ROLE_TO_SET_ROLE) != set(ROLES):  # pragma: no cover - an import-time contract
    raise RuntimeError(
        "illustration.PLAN_ROLE_TO_SET_ROLE must name every role in models.plan.ROLES and no others. A "
        "role added to the plan without a line here would be silently absent from every illustration, "
        "which is the shape of defect A69 asked to be prevented explicitly."
    )

#: The engine whose gap list explains why no trajectory is offered. Named rather than inlined so the
#: payload's `no_trajectory_because` and this module's docstring cannot describe different engines.
TRAJECTORY_ENGINE = "s_curve_trajectory"

#: Principle 9. The only capital type a market rate may be applied to. A ReturnSet's role profiles are
#: estimated from market data for financial assets; a member's own labour is not one, and nothing in the
#: published set was estimated over it.
FINANCIAL_CAPITAL = "financial"

#: The capital type excluded from every figure below, and reported rather than dropped.
HUMAN_CAPITAL = "human"

if {FINANCIAL_CAPITAL, HUMAN_CAPITAL} != set(CAPITAL_TYPES):  # pragma: no cover - an import-time contract
    raise RuntimeError(
        "illustration must name every capital type in models.plan.CAPITAL_TYPES. A third one added to the "
        "plan would otherwise fall silently into whichever branch below happens to catch it, and the "
        "branch that catches it applies a market rate."
    )

#: Every reason a position funding this goal was left out of the **held balance**, as stable keys (A12).
#:
#: A separate list from `excluded_from_the_projection` on purpose, and the distinction is the same one A85
#: was about: a human-capital position is excluded from *every* figure, while a financial position with a
#: flow magnitude still names a role the rate is read for - it is only its *amount* that cannot be used.
#: Folding the two lists together would tell a member their securities account was excluded when it was not.
NOT_COUNTED_REASONS = (
    #: The member has not put a figure on it. R-020 and A30: a position without an amount is a full
    #: position, so this is a fact rather than an incomplete record.
    "no_magnitude_stated",
    #: `chf_per_year`. The A105 case: a rate on a flow is francs per year per year.
    "a_flow_is_not_a_balance",
    #: `share_of_total`. Dimensionless, and the total it is a share of is not in the plan.
    "a_share_of_a_total_is_not_an_amount",
    #: A `chf` stock with `stock_kind='liability'`. Dimensionally fine and refused anyway - see the essay.
    "a_liability_is_not_projected_as_a_holding",
)

#: Why a human-capital position carries no figure. A **stable key** and not a sentence (A12), the same
#: shape as `CAVEATS` and `UNAVAILABLE_REASONS`; the client holds the wording in both languages.
HUMAN_CAPITAL_EXCLUSION_REASON = "human_capital_carries_no_market_rate"

#: Where in the AssumptionSet each figure is read from. Named because a typo in one of these strings would
#: produce a missing-key reason that looks like a publishing problem.
ROLE_PROFILES_KEY = "role_profiles_by_scenario"
PROBABILITIES_KEY = "scenario_probabilities"
SCENARIOS_KEY = "scenarios"
VALUES_UNIT_KEY = "values_unit"
HORIZON_YEARS_KEY = "return_estimation_years"

class RateAppliedToSomethingThatIsNotABalance(ValueError):
    """`apply_rate` was handed a magnitude whose unit is not a stock.

    A class of its own rather than a bare `ValueError`, so a test can require *this* refusal and not merely
    some exception, and so a stack trace names the defect instead of an arithmetic error.
    """


def apply_rate(amount: float, rate: float, *, unit: str) -> float:
    """The change in a balance over the published horizon. **The only multiplication in this module.**

    `unit` is required and positional-by-keyword because the whole point is that it cannot be forgotten.
    A published role profile is a fraction of a balance; multiplying it by anything else produces a figure
    in a unit nobody asked for that looks exactly like francs on a screen. See the essay at the top.

    Refuses rather than returning None or zero: a zero change is a claim that the holding is expected not to
    move, which is the same substitution `_funding_roles` refuses for a salary.
    """
    if unit not in STOCK_UNITS:
        raise RateAppliedToSomethingThatIsNotABalance(
            f"a published rate may be applied to a balance and to nothing else; {unit!r} is not one of "
            f"{list(STOCK_UNITS)}. A rate times {FLOW_UNIT!r} is francs per year per year, and a rate "
            f"times {SHARE_UNIT!r} is a bare fraction - both render as francs and neither is one. "
            f"Capitalising a flow needs a discount rate, which is an assumption under C-02 and is not "
            f"published."
        )
    return amount * rate


#: Every reason an illustration can be unavailable. All derived; none is a placeholder.
#:
#: `no_assumption_set_published` is first because it is the one that was wrong: it may be returned only
#: when `assumption_sets` is genuinely empty. `test_the_empty_table_is_the_only_route_to_that_reason`
#: holds that, and it is the test the previous implementation would have failed.
UNAVAILABLE_REASONS = (
    "no_assumption_set_published",
    "no_assumption_set_in_effect_yet",
    "the_assumption_set_publishes_no_role_profiles",
    "the_goal_names_no_amount",
    "the_goal_names_no_active_funding",
    "the_funding_roles_are_not_in_the_assumption_set",
    # Principle 9, added 1 September 2026. Distinct from `the_goal_names_no_active_funding`, and the
    # distinction is the whole point: this goal **is** funded, by a position the member entered, and the
    # reason there is no figure is that a salary is not a security. Saying "no active funding" here would
    # be the A85 defect again — a reason that reads as a gap in the member's record when the record is
    # complete and it is the arithmetic that declines.
    "the_goal_is_funded_only_by_human_capital",
    # A129, added 4 September 2026. **A property goal's `target_amount` is the PRICE**, and the price is
    # not what has to be accumulated — the deposit is, and it is roughly a fifth of it. Projecting a
    # member's holdings toward the price would measure them against a number about five times too large,
    # in the direction that tells them they are far behind when they may already be there. Three of the
    # five real property cases reach the deposit comfortably.
    #
    # So a goal that says it is a property purchase is not projected here at all. `services/property.py`
    # answers it with the two tests that actually decide it, and its own conventions record is not yet
    # approved — which is the second half of this reason and the reason it is one reason rather than two:
    # from the member's side there is no figure either way, and inventing a distinction between "we do
    # not do this yet" and "nobody has signed the numbers" would be a distinction about us.
    "the_goal_is_a_property_purchase",
)

#: The two caveats about **what the figure is a figure of**, and exactly one of them is carried.
#:
#: Before the stock unit there was only the first, and it was permanent. Now which one applies is derived
#: from what the member stated, and both are wrong in the other case: telling a member their own stated
#: balance "is not a holding" reads as a system that has not understood them, and telling them a target
#: amount is their balance is an invented figure.
STATED_AMOUNT_CAVEAT = "the_amount_is_stated_by_the_member_and_is_not_a_holding"
HELD_BALANCE_CAVEAT = "the_balance_is_the_sum_of_the_stocks_the_member_has_stated"

#: Stable keys for the caveats every illustration carries. **Keys, not sentences**: A12 makes this product
#: bilingual with de-CH the default, the wording lives in the client's content files beside every other
#: string, and prose emitted from a service module is prose that exists in one language only.
CAVEATS = (
    # C-02 / A69. The rates hold at the horizon they were estimated at and are not extended.
    "rates_hold_at_the_published_horizon_only",
    # A69. The profiles and the probabilities are published side by side; nothing multiplies them.
    "no_blended_rate_is_published",
    # A69 / C-02. `inflation` is NULL in the set, so nothing here is in real terms.
    "not_in_real_terms_because_no_inflation_is_published",
    # A30. The amount is what the member said the goal needs, not what they hold. Carried when the basis
    # IS the target amount; swapped for `HELD_BALANCE_CAVEAT` when the member has stated what they hold,
    # because then it is false - and a caveat that is false is worse than no caveat.
    STATED_AMOUNT_CAVEAT,
    # R-133. This is an illustration under C-02, not a forecast and not advice (C-01).
    "an_illustration_and_not_a_forecast",
)


#: Every caveat key that can appear on any path, for a test that checks the payload emits only declared
#: ones. `CAVEATS` stays the ordered list an illustration carries, with one entry substituted.
ALL_CAVEATS = CAVEATS + (HELD_BALANCE_CAVEAT,)

#: What `basis.read_from` says. Two values, because there are two things a rate can honestly be applied to
#: and a client showing a figure has to be able to tell the member which one it is.
READ_FROM_TARGET = "goal_target_amount"
READ_FROM_HELD = "position_magnitude_stated_as_a_chf_stock"


def _unavailable(reason: str, *, excluded: list[dict] | None = None, **extra) -> dict:
    """One unavailable answer, with its reason and with what the projection left out.

    `excluded_from_the_projection` is on **every** return path, empty list included, for the reason the
    docstring of `goal_illustration` gives about `illustration_unavailable_reason` itself: a client that
    had to infer "nothing was excluded" from a missing key would be inferring from absence.
    """
    if reason not in UNAVAILABLE_REASONS:  # pragma: no cover - an internal contract
        raise ValueError(f"unknown illustration reason {reason!r}")
    return {
        "illustration": None,
        "illustration_unavailable_reason": reason,
        "excluded_from_the_projection": list(excluded or ()),
        # On every path, empty list included, for the same reason as the list above it.
        "not_counted_toward_the_held_balance": list(extra.pop("not_counted", None) or ()),
        **extra,
    }


def _any_assumption_set_exists(session: Session) -> bool:
    return session.execute(select(AssumptionSet.id).limit(1)).scalar_one_or_none() is not None


def _funding_roles(goal: Goal) -> tuple[dict[str, int], list[dict]]:
    """The goal's ACTIVE funding, split by capital type.

    Returns `(financial_role_counts, excluded)`:

      * **`financial_role_counts`** — the roles the goal's active *financial* funding occupies, and how
        many positions name each. These are the only positions a published rate may be read for.
      * **`excluded`** — one entry per active *human-capital* position, so the payload can say what it
        left out instead of quietly leaving it out.

    Active only: R-122 keeps an inactive position in history, and illustrating over something the member
    has stood down would be reading their record back to them wrong.

    ------------------------------------------------------------------------------------------------------
    WHY THE CAPITAL TYPE IS READ HERE — Principle 9, 1 September 2026
    ------------------------------------------------------------------------------------------------------

    **This function grouped on `Position.role` alone and never looked at `capital_type`.** So a goal funded
    by a human-capital income position — a salary — had the ReturnSet's `income` market profile applied to
    the member's stated income, with no caveat and no mention of human capital anywhere in the payload. An
    audit measured `rate -0.0593 -> change_chf -14825.0` on a salary: a market contraction taking a fifteen
    thousand franc bite out of somebody's job.

    It is one click off the default path, which is what makes it serious rather than theoretical.
    `services/onboarding.py` gives **every** member exactly one position, `role="income",
    capital_type="human"`, and the containers form offers it in the funding multiselect. Nothing had to go
    wrong for a member to see this.

    The role profiles are estimated over market instruments. Human capital is not one: it is bounded by
    hours rather than by price (R-121), the published set estimated nothing over it, and applying a return
    to it is inventing a figure, which is the one thing this module exists not to do. Principle 9's testable
    form is "a summary component that accepts only financial inputs", and this is the filter that makes that
    true.

    **Excluded, not zeroed.** A zero rate is a claim — that a salary is expected not to move — and it is
    a claim nobody published. The positions come back so the caller can name them.
    """
    counts: dict[str, int] = {}
    excluded: list[dict] = []
    for position in goal.funded_by:
        if not position.active or position.role is None:
            continue
        if position.capital_type != FINANCIAL_CAPITAL:
            excluded.append(
                {
                    "position_id": position.id,
                    "role": position.role,
                    "capital_type": position.capital_type,
                    # A stable key. The client holds the sentence, in both languages (A12).
                    "reason": HUMAN_CAPITAL_EXCLUSION_REASON,
                }
            )
            continue
        counts[position.role] = counts.get(position.role, 0) + 1
    return counts, excluded


def _held_balances(goal: Goal) -> tuple[dict[str, float], list[dict]]:
    """The balance the goal's ACTIVE FINANCIAL funding states, per role - and what could not be counted.

    Returns `(balance_by_role, not_counted)`. A role appears in the first only if at least one position
    funding this goal under that role states an asset stock in francs.

    **Per role rather than as one total**, because the rate is per role: summing a growth balance and a
    protection balance and then applying one of the two rates to the sum is a blend by the back door, and
    A69 is explicit that nothing here blends anything.

    **Four things are not counted, and each is named rather than dropped** (`NOT_COUNTED_REASONS`):

      * no magnitude at all - the member has not said, and A30 makes that a complete position;
      * `chf_per_year` - a flow. The A105 case; see the essay at the top of this module;
      * `share_of_total` - a fraction of a total the plan does not hold;
      * a liability - a real balance, and one a market rate is not published for.

    Human capital never reaches this function: `_funding_roles` has already taken it out of the roles this
    iterates, and it is reported in `excluded_from_the_projection` instead. So a human-capital `chf` asset -
    a member valuing their own training at 500,000 - **cannot** enter a balance a market rate is applied to,
    which is A105's own guarantee holding one layer further in.
    """
    balances: dict[str, float] = {}
    not_counted: list[dict] = []

    for position in goal.funded_by:
        if not position.active or position.role is None:
            continue
        if position.capital_type != FINANCIAL_CAPITAL:
            # Already reported by `_funding_roles`. Reporting it twice would read as two problems.
            continue

        if position.magnitude is None or position.magnitude_unit is None:
            reason = "no_magnitude_stated"
        elif position.magnitude_unit == FLOW_UNIT:
            reason = "a_flow_is_not_a_balance"
        elif position.magnitude_unit == SHARE_UNIT:
            reason = "a_share_of_a_total_is_not_an_amount"
        elif position.magnitude_unit in STOCK_UNITS and position.stock_kind == LIABILITY:
            reason = "a_liability_is_not_projected_as_a_holding"
        elif position.magnitude_unit in STOCK_UNITS and position.stock_kind == ASSET:
            # `0` and not `0.0`: an accumulator seed is not a rate, and C-02's float-literal scan over
            # application code is right to make no exception for one.
            balances[position.role] = balances.get(position.role, 0) + position.magnitude
            continue
        else:
            # A stock with no side of the balance sheet. `ck_positions_stock_kind_iff_stock` makes it
            # unstorable; if one ever appears it is NOT filed as an asset, because that silent default is
            # the whole reason `stock_kind` is a field rather than a sign.
            reason = "no_magnitude_stated"

        not_counted.append(
            {
                "position_id": position.id,
                "role": position.role,
                "magnitude_unit": position.magnitude_unit,
                "stock_kind": position.stock_kind,
                # A stable key. The client holds the sentence, in both languages (A12).
                "reason": reason,
            }
        )

    for entry in not_counted:  # pragma: no cover - an internal contract
        if entry["reason"] not in NOT_COUNTED_REASONS:
            raise ValueError(f"undeclared reason {entry['reason']!r}")
    return balances, not_counted


def _why_no_trajectory(
    session: Session, goal: Goal, *, member_id: str, today: date
) -> list[dict]:
    """The plan-blocking gaps for the trajectory engine, verbatim from A39's mapping layer.

    Carried into the payload rather than summarised, because the reasons in `engine_inputs.py` are the
    considered ones and a summary written here would be a second, shorter, less true copy.
    """
    # **The member's positions are passed, and that is not optional.** `initial_wealth` is fillable from a
    # stated stock now, so a call that withheld the positions would get back the gap reason "this member has
    # stated none" for a member who has stated one - a derived reason that is false, which is the A85 defect
    # this module was rebuilt to remove. The reason has to be about the plan, so the plan has to be handed
    # over.
    positions = list(
        session.execute(select(Position).where(Position.member_id == member_id)).scalars()
    )
    plan = plan_for(
        TRAJECTORY_ENGINE, member_id=member_id, goal=goal, positions=positions, today=today
    )
    return [gap.as_dict() for gap in plan.absent if gap.blocks_the_plan]


def goal_illustration(
    session: Session,
    goal: Goal,
    *,
    member_id: str,
    today: date | None = None,
) -> dict:
    """R-133 / C-02. `{"illustration": {...}|None, "illustration_unavailable_reason": str|None}`.

    Both keys are always present. An absent illustration is a fact with a reason, and a client that had to
    infer it from a missing key would be inferring from absence — the thing `illustration_unavailable_reason`
    exists to make unnecessary.

    **`excluded_from_the_projection` and `not_counted_toward_the_held_balance` are the third and fourth
    always-present keys**, and they are there for the same reason. Only financial capital gets a market
    rate (Principle 9, 1 September 2026), and only a stated balance in francs gets one applied to its own
    amount (1 September 2026): every position either exclusion touches is listed, whether or not an
    illustration was produced, so a client never has to work out from a missing key that nothing was
    dropped.
    """
    when = today or date.today()

    # -- Principle 9, before anything else reads the funding. Financial capital gets a rate; human capital
    # -- is excluded from every figure and named in the payload. `_funding_roles` carries the argument.
    roles, excluded_funding = _funding_roles(goal)
    # Principle 9 has already run, so only financial roles reach this. See `_held_balances`.
    held_by_role, not_counted = _held_balances(goal)
    held_total = sum(held_by_role.values()) if held_by_role else None

    # -- A129: a property purchase is not this module's question ------------------------------------
    #
    # Checked BEFORE the assumption set, deliberately. The reason a property goal has no figure here has
    # nothing to do with whether a rate is published, and reporting `no_assumption_set_published` for it
    # would send a reader to fix something that is not the obstacle.
    if goal.occupancy is not None:
        return _unavailable(
            "the_goal_is_a_property_purchase", excluded=excluded_funding, not_counted=not_counted
        )

    # -- C-02: is there a set at all, and is it in effect? -------------------------------------
    try:
        assumption_set = current_assumption_set(session, on=when)
    except NoAssumptionSet:
        # The one place `no_assumption_set_published` may be returned, and only after asking the table.
        if _any_assumption_set_exists(session):
            return _unavailable(
                "no_assumption_set_in_effect_yet", excluded=excluded_funding, not_counted=not_counted
            )
        return _unavailable(
            "no_assumption_set_published", excluded=excluded_funding, not_counted=not_counted
        )

    rates = assumption_set.rates or {}
    horizons = assumption_set.horizons or {}
    profiles = rates.get(ROLE_PROFILES_KEY) or {}
    if not profiles:
        return _unavailable(
            "the_assumption_set_publishes_no_role_profiles",
            assumption_set_id=assumption_set.id,
            excluded=excluded_funding,
            not_counted=not_counted,
        )

    # -- the member's own two inputs ------------------------------------------------------------
    if goal.target_amount is None and held_total is None:
        # R-132's normal case, not an incomplete record: courage money is defined by what it is FOR.
        #
        # **`held_total is None` is the second half, and it is new.** A goal the member never priced but
        # which is funded by a stated balance IS projectable - the rate applies to the balance, and the
        # target amount was never what the arithmetic needed. Returning "names no amount" there would send
        # a member to fill in a figure that would change nothing.
        return _unavailable(
            "the_goal_names_no_amount",
            assumption_set_id=assumption_set.id,
            excluded=excluded_funding,
            not_counted=not_counted,
        )

    if not roles:
        if excluded_funding:
            # Principle 9. The goal IS funded — by the member's own labour — and the honest answer is that
            # there is no rate to apply to it, not that they forgot to fund anything. Two different facts
            # get two different reasons, and the excluded positions travel so the client can name them.
            return _unavailable(
                "the_goal_is_funded_only_by_human_capital",
                assumption_set_id=assumption_set.id,
                excluded=excluded_funding,
                not_counted=not_counted,
            )
        # R-030: an unfunded goal is a legitimate state. There is simply no role to read a rate for.
        return _unavailable(
            "the_goal_names_no_active_funding",
            assumption_set_id=assumption_set.id,
            excluded=excluded_funding,
            not_counted=not_counted,
        )

    probabilities = rates.get(PROBABILITIES_KEY) or {}
    published_scenarios = list(rates.get(SCENARIOS_KEY) or ())

    # -- which amount the rate is applied to, decided once ------------------------------------
    #
    # A stated balance where there is one, and the member's target amount where there is not. Never a
    # mixture: a payload where some roles were projected on holdings and others on the target would be
    # arithmetic nobody could check, and the two numbers mean different things.
    on_holdings = held_total is not None

    by_role: list[dict] = []
    for plan_role in sorted(roles):
        set_role = PLAN_ROLE_TO_SET_ROLE[plan_role]
        profile = profiles.get(set_role)
        if not profile:
            continue
        # The set's own scenario order where it publishes one, so a screen lists crisis-to-boom the way the
        # engine does rather than alphabetically. Anything in the profile the list does not name is
        # appended rather than dropped: the profile is the authority on what was estimated.
        ordered = [name for name in published_scenarios if name in profile]
        ordered += sorted(name for name in profile if name not in ordered)

        # On holdings, each role is projected on ITS OWN balance. A role the member funds with positions
        # that state no balance is skipped rather than projected on somebody else's number: `.get` with no
        # default, checked, because `held_by_role.get(role, 0.0)` would produce a tidy row of zeros that
        # reads as "expected not to move".
        role_amount = held_by_role.get(plan_role) if on_holdings else goal.target_amount
        if role_amount is None:
            continue

        by_role.append(
            {
                "role": plan_role,
                # Both names, so a reader can see that a translation happened (A69).
                "assumption_set_role": set_role,
                "positions_naming_this_role": roles[plan_role],
                # Which amount this role's figures are figures of. Present in both cases: a client reading
                # one role's block must not have to look up at `basis` to know what it was applied to.
                "amount_chf": role_amount,
                "scenarios": [
                    {
                        "scenario": name,
                        # Copied from the set. Not rounded: rounding is a transformation, and the client
                        # is the layer that formats.
                        "rate": profile[name],
                        # `apply_rate` and not `*`. The unit is named at the call site, every time - see
                        # the essay at the top of this module. `STOCK_UNITS[0]` for the target amount is a
                        # claim about `Goal.target_amount` and it is the right one: it is an amount in
                        # francs at a point in time ("Zielbetrag in CHF"), not a yearly figure.
                        "rate_applied_to_unit": STOCK_UNITS[0],
                        "change_chf": apply_rate(
                            role_amount, profile[name], unit=STOCK_UNITS[0]
                        ),
                        "amount_after_the_horizon_chf": role_amount
                        + apply_rate(role_amount, profile[name], unit=STOCK_UNITS[0]),
                        # Published beside the rate and never multiplied into it (A69). A screen may show
                        # it; nothing here weights anything by it.
                        "probability_as_published": probabilities.get(name),
                    }
                    for name in ordered
                ],
            }
        )

    if not by_role:
        # **A known imprecision, recorded rather than papered over.** On the holdings basis this can also be
        # reached when the set does publish a funding role but no position under it states a balance — a
        # goal funded by a growth position with a stated stock the set has no profile for, plus a protection
        # position with no stock. The dominant clause is still true (a funding role the set does not
        # publish), and `not_counted_toward_the_held_balance` carries the rest, position by position. A
        # sixth unavailable reason would be more precise; it is not written until a real payload needs it,
        # because a reason nobody has seen produced is a reason nobody has checked.
        return _unavailable(
            "the_funding_roles_are_not_in_the_assumption_set",
            assumption_set_id=assumption_set.id,
            excluded=excluded_funding,
            not_counted=not_counted,
        )

    goal_years = horizon_years(goal, today=when)

    illustration = {
        "kind": "range_of_outcomes_by_role_at_the_published_horizon",
        # C-02: "every illustration response returns the assumption_set_id used".
        "assumption_set_id": assumption_set.id,
        "assumption_set_version": assumption_set.version,
        "assumption_set_effective_from": assumption_set.effective_from.isoformat(),
        "published_by": assumption_set.published_by,
        "values_unit": rates.get(VALUES_UNIT_KEY),
        # Explicitly a boolean rather than a null rate: `inflation: None` on a screen is one careless
        # template away from rendering as a zero, which is the R-302 mistake in C-02's clothing.
        "inflation_published": assumption_set.inflation is not None,
        "basis": {
            "amount_chf": held_total if on_holdings else goal.target_amount,
            "read_from": READ_FROM_HELD if on_holdings else READ_FROM_TARGET,
            # Principle 9, stated positively inside the figure block rather than only as an absence
            # outside it. A rate is applied to financial capital and to nothing else; a reader who has
            # only this block in front of them can still see which inputs it accepted.
            "capital_types_projected": [FINANCIAL_CAPITAL],
        },
        "horizon": {
            "published_years": horizons.get(HORIZON_YEARS_KEY),
            "goal_years": goal_years,
            # Never true: the set carries rates for one horizon and they are not extended. Stated as a
            # field rather than left to the caveat list, because a client showing a goal date beside a
            # one-year range needs to know in the data that the two are different horizons.
            "rates_extended_to_the_goal_horizon": False,
        },
        "by_role": by_role,
        "no_trajectory_because": _why_no_trajectory(
            session, goal, member_id=member_id, today=when
        ),
        # One of the two amount caveats, never both and never neither. See `STATED_AMOUNT_CAVEAT`.
        "caveats": [
            HELD_BALANCE_CAVEAT if (on_holdings and key == STATED_AMOUNT_CAVEAT) else key
            for key in CAVEATS
        ],
    }

    # C-03 / R-304, at the last boundary. The AssumptionSet legitimately stores `regime_timeline_id` and
    # `return_set_id` in `rates["source"]`; this payload copies field by field from a named allowlist and
    # must never carry them. Checked rather than trusted, because the way one would arrive is a future edit
    # copying `rates` through in one line.
    return assert_no_engine_artefact(
        {
            "illustration": illustration,
            "illustration_unavailable_reason": None,
            # Principle 9. A goal funded by both kinds of capital is projected on the financial part and
            # says what it left out - beside the figures, not instead of them, and in the same place and
            # the same shape as on every unavailable path. Empty when nothing was excluded.
            "excluded_from_the_projection": excluded_funding,
            # The second list, and a different fact: these positions DID contribute their role, and only
            # their amount could not be used. Folding the two together would tell a member a securities
            # account was excluded when it was projected.
            "not_counted_toward_the_held_balance": not_counted,
        },
        where=f"illustration for goal in assumption set {assumption_set.version}",
    )


__all__ = [
    "ALL_CAVEATS",
    "CAVEATS",
    "HELD_BALANCE_CAVEAT",
    "NOT_COUNTED_REASONS",
    "READ_FROM_HELD",
    "READ_FROM_TARGET",
    "RateAppliedToSomethingThatIsNotABalance",
    "STATED_AMOUNT_CAVEAT",
    "apply_rate",
    "FINANCIAL_CAPITAL",
    "HUMAN_CAPITAL",
    "HUMAN_CAPITAL_EXCLUSION_REASON",
    "PLAN_ROLE_TO_SET_ROLE",
    "TRAJECTORY_ENGINE",
    "UNAVAILABLE_REASONS",
    "goal_illustration",
]
