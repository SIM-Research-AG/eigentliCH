"""Property goals: the equity floor, the affordability ceiling, and which capital may legally fund them.

Four of the eleven goals across the six real submissions are property purchases, and they carry the
largest figures any member wrote down. Until this module existed the build had one way to read a goal —
*can the member accumulate `target_amount` by `target_date`* — and for a property goal that question is
the wrong one. A member does not save 1.5 million to buy a 1.5 million house; they save the deposit and
borrow the rest, and whether they can do it is decided by two tests that bind independently:

    EQUITY          at least a fifth of the price for a home they live in, of which at least half must be
                    "hard" — not from pillar 2. Pillar 3a counts as hard equity; pillar 2 does not.

    AFFORDABILITY   imputed interest, plus maintenance, plus amortisation of the portion above the first
                    mortgage, all of it at most a third of gross HOUSEHOLD income. Computed at a rate the
                    member is not paying, which is the whole point of the test.

Run against the six real submissions on 4 September 2026, those two tests disagree about which one binds
in four cases out of five, and the one the product was built to answer is the one that does not bind:
three members reach the deposit comfortably and cannot carry the loan.

===========================================================================================================
OCCUPANCY IS A RULE AND NOT A DIAL
===========================================================================================================

Pillar 2 and pillar 3a may be drawn only for a property the member lives in themselves. For a holiday home
or a property they let out, the pension capital is **not illiquid — it is unavailable**, and no amount of
horizon or risk appetite changes that. One of the six members holds 172'000 across pillar 2 and 3a against
a holiday-home goal, and a naive reading of their own balance sheet says they are most of the way to the
deposit when in fact they have a fifth of it.

That is why `Goal.occupancy` exists and why nothing here infers it. A goal whose occupancy is unknown gets
`COULD_NOT_BE_DETERMINED`, never the favourable case — the same discipline `services/currency.py` applies
to an expired input and `services/household.py` applies to an unstated composition (A110).

===========================================================================================================
NOTHING HERE IS APPROVED YET, AND THE REFUSAL IS THE POINT
===========================================================================================================

Every figure this module reads is in `client/content/property-funding.json`, marked `provisional: true`,
and `conventions()` raises `ConventionsNotApproved` while it stays that way. A member cannot be shown a
figure that says what a lender would do on the implementer's word alone.

Approving is three fields and a boolean. Until then the module is fully built, fully tested against an
approved fixture, and serves nobody — which is the honest state for a calculation that tells someone
whether they can buy a house.

===========================================================================================================
WHERE THE BOUNDARY SITS
===========================================================================================================

"A property at this price is tested against an income of 265'000; your plan records 69'550" is a
**per-member computation** — the second of the three branches in `services/router.py`, below the advice
boundary and permitted without a curator. It is the same shape as the Befund's existing sentences: a
figure, its source, and what it was compared against.

"Buy a cheaper house" is a recommendation and this module never produces one. `levers()` returns the
*dimensions* a member could move — price, date, income, deposit — with the arithmetic for each, and no
ranking and no imperative. C-06's rule about prepared options carrying consequences is satisfied by the
consequence being a number rather than an adjective.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..content import _load

#: What `assess` concluded. Deliberately the same three words `services/liquidity.py` uses, because a
#: reader meeting both should not have to learn two vocabularies for the same idea.
MEETS = "meets"
DOES_NOT_MEET = "does_not_meet"
COULD_NOT_BE_DETERMINED = "could_not_be_determined"

#: The two tests, named once. A caller asking "which test failed" compares against these rather than a
#: string it spelled itself.
EQUITY = "equity"
AFFORDABILITY = "affordability"


class ConventionsNotApproved(Exception):
    """The property conventions have no owner's name on them, so nothing may be computed from them.

    Raised rather than defaulted, for the reason `services/currency.py` raises for an input class with no
    published horizon: an absence that silently behaves like a permission is the defect the published
    record exists to prevent.
    """


class UnknownOccupancy(ValueError):
    """A goal carries an occupancy the content record does not declare."""


def _record() -> dict:
    return _load("property-funding")


def conventions() -> dict:
    """The approved conventions, or a refusal.

    Reads the content file on every call rather than caching, so approving the record takes effect without
    a restart and a test can approve a fixture without clearing anything.
    """
    record = _record()
    about = record["_about"]
    if about.get("provisional", True):
        raise ConventionsNotApproved(
            "client/content/property-funding.json is marked provisional and carries no publisher. "
            "The equity floors, the imputed rate and the affordability share are figures that tell a "
            "member what a lender would say, and no member may be shown one on the implementer's word. "
            "Approving is `published_by`, `decided_on`, `effective_from` and `provisional: false`."
        )
    if not about.get("published_by"):
        raise ConventionsNotApproved(
            "property-funding.json is not provisional and names no `published_by`. A value nobody stands "
            "behind is the defect C-02 exists to prevent, and this record carries seven of them."
        )
    return record


def occupancies() -> dict:
    """Every occupancy the record declares, read without requiring approval.

    Separate from `conventions()` on purpose: the *set* of occupancies is needed to render the question and
    to validate what a member answered, and neither of those puts a figure in front of anybody. Only the
    figures are gated.

    Keys beginning with an underscore are the record's own notes to a reader, not occupancies. Filtered
    here rather than at each call site, because a caller that forgot would offer a member `_about` as
    something they could be living in.
    """
    return {
        key: value for key, value in _record()["occupancy"].items() if not key.startswith("_")
    }


def occupancy_rule(key: str) -> dict:
    try:
        return occupancies()[key]
    except KeyError:
        raise UnknownOccupancy(
            f"{key!r} is not an occupancy the record declares. Known: {sorted(occupancies())}"
        ) from None


# ---------------------------------------------------------------------------
# the two tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Equity:
    """What the deposit has to be, and what may legally go toward it."""

    price: float
    required: float
    hard_required: float
    pillar2_may_fund: bool
    pillar3a_may_fund: bool
    #: The most pillar 2 that may count, which is the requirement less the hard-equity floor. Zero
    #: wherever pillar 2 may not fund at all.
    pillar2_cap: float

    def verdict(self, *, hard_available: float, pillar2_available: float) -> str:
        usable_pension = min(pillar2_available, self.pillar2_cap) if self.pillar2_may_fund else 0
        if hard_available < self.hard_required:
            return DOES_NOT_MEET
        return MEETS if hard_available + usable_pension >= self.required else DOES_NOT_MEET


@dataclass(frozen=True)
class Affordability:
    """What the property costs each year under the test, and the income that carries it."""

    price: float
    #: The annual cost the test imputes, in francs. Not what the member would pay.
    annual_cost: float
    #: The gross household income that cost requires.
    income_required: float
    #: The most expensive property the stated income carries. None when no income is stated.
    price_supported: float | None

    def verdict(self, *, income: float | None) -> str:
        if income is None:
            return COULD_NOT_BE_DETERMINED
        return MEETS if income >= self.income_required else DOES_NOT_MEET


def equity(price: float, *, occupancy: str) -> Equity:
    rule = occupancy_rule(occupancy)
    conventions()  # the floors below are figures; refuse before producing any
    required = price * rule["equity_min"]
    hard_required = price * rule["hard_equity_min"]
    return Equity(
        price=price,
        required=required,
        hard_required=hard_required,
        pillar2_may_fund=bool(rule["pillar2_may_fund"]),
        pillar3a_may_fund=bool(rule["pillar3a_may_fund"]),
        pillar2_cap=max(0, required - hard_required) if rule["pillar2_may_fund"] else 0,
    )


@dataclass(frozen=True)
class MandateTarget:
    """What a portfolio actually has to accumulate for a property goal, and on what assumption."""

    #: The capital to fund. The deposit, never the purchase price.
    target: float
    price: float
    occupancy: str
    equity_min: float
    #: True when the member has not said how they will use the property and one had to be chosen.
    assumed: bool
    why: str

    @property
    def mortgage(self) -> float:
        """The rest, which is a loan and not a savings target — and which the Tragbarkeit test governs."""
        return self.price - self.target


def mandate_target(price: float, *, occupancy: str | None = None,
                   record: dict | None = None) -> MandateTarget:
    """The capital a property goal requires by its deadline.

    **The deposit, and this is the whole point of the function.** Feeding a mandate the full purchase
    price asks the portfolio to buy the house in cash. For a 1'100'000 home over eight years that
    produced a required return of 31.3 % a year and the verdict «not reachable» — arithmetically correct
    and about a goal nobody has. The deposit for the same home is 220'000, which the same household
    reaches. What it then fails is the Tragbarkeit test, and that is a conversation about income rather
    than about the portfolio.

    So the mandate funds the deposit. The rest is a mortgage, which is not accumulated and is governed by
    `affordability` instead.

    **Where the occupancy is unanswered, the strictest requirement is used**, and `assumed` says so. The
    three run 20 %, 25 % and 30 %, and the direction of the error decides which to pick: targeting too
    little tells a household they will make it when they will not, and targeting too much tells them to
    keep saving. Only one of those is safe to be wrong about.
    """
    record = record or _record()
    rules = record["occupancy"]
    known = {key: rule for key, rule in rules.items() if isinstance(rule, dict)}

    if occupancy in known:
        rule = known[occupancy]
        share = float(rule["equity_min"])
        label = (rule.get("label") or {}).get("de", occupancy)
        return MandateTarget(target=float(price) * share, price=float(price), occupancy=occupancy,
                             equity_min=share, assumed=False,
                             why=f"Nutzung angegeben: {label}, {share:.0%} Eigenmittel.")

    strictest = max(known, key=lambda key: float(known[key]["equity_min"]))
    share = float(known[strictest]["equity_min"])
    label = (known[strictest].get("label") or {}).get("de", strictest)
    return MandateTarget(
        target=float(price) * share, price=float(price), occupancy=strictest, equity_min=share,
        assumed=True,
        why=(f"Die Nutzung ist nicht erfasst. Gerechnet wird mit der strengsten der drei Varianten "
             f"({label}, {share:.0%}), weil ein zu tiefes Ziel einem Haushalt sagt, es reiche, wenn es "
             f"nicht reicht."),
    )


def affordability(price: float, *, income: float | None = None) -> Affordability:
    published = conventions()["affordability"]
    loan_to_value = 1 - occupancy_rule("owner_occupied_primary")["equity_min"]
    return _affordability(price, income=income, published=published, loan_to_value=loan_to_value)


def _affordability(price, *, income, published, loan_to_value) -> Affordability:
    interest = loan_to_value * published["imputed_rate"]
    above_first = max(0, loan_to_value - published["first_mortgage_max"])
    amortisation = above_first / published["amortisation_years"]
    fraction = interest + published["maintenance_and_ancillary"] + amortisation

    annual = price * fraction
    share = published["max_share_of_gross_income"]
    return Affordability(
        price=price,
        annual_cost=annual,
        income_required=annual / share,
        price_supported=(income * share / fraction) if income else None,
    )


# ---------------------------------------------------------------------------
# the assessment a caller actually wants
# ---------------------------------------------------------------------------


@dataclass
class Assessment:
    """Both tests, and which of them binds. No ranking and no imperative — see the module docstring."""

    goal_id: str
    price: float
    target_date: date | None
    occupancy: str | None
    equity: Equity | None = None
    affordability: Affordability | None = None
    equity_verdict: str = COULD_NOT_BE_DETERMINED
    affordability_verdict: str = COULD_NOT_BE_DETERMINED
    binds_on: list[str] = field(default_factory=list)
    undetermined_because: list[str] = field(default_factory=list)
    #: Positions that may not fund this goal, with the rule that says so. Not a warning: a fact.
    ineligible: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """One word for the whole assessment, so a client reads one key.

        `could_not_be_determined` wins over everything: a goal missing its occupancy has not passed the
        equity test, it has not been tested. `does_not_meet` when either test binds. `meets` only when
        both were run and both passed.
        """
        if self.undetermined_because or COULD_NOT_BE_DETERMINED in (
            self.equity_verdict, self.affordability_verdict
        ):
            return COULD_NOT_BE_DETERMINED
        return DOES_NOT_MEET if self.binds_on else MEETS

    def as_payload(self) -> dict:
        return {
            "goal_id": self.goal_id,
            # Present on both this path and the refusal paths in `services/goals.property_finding`, so a
            # client reads one key rather than discovering that the shape depends on why there is no
            # figure.
            "verdict": self.verdict,
            "price_chf": self.price,
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "occupancy": self.occupancy,
            "equity": None if self.equity is None else {
                "required_chf": self.equity.required,
                "hard_required_chf": self.equity.hard_required,
                "pillar2_cap_chf": self.equity.pillar2_cap,
                "pillar2_may_fund": self.equity.pillar2_may_fund,
                "pillar3a_may_fund": self.equity.pillar3a_may_fund,
                "verdict": self.equity_verdict,
            },
            "affordability": None if self.affordability is None else {
                "annual_cost_chf": self.affordability.annual_cost,
                "income_required_chf": self.affordability.income_required,
                "price_supported_chf": self.affordability.price_supported,
                "verdict": self.affordability_verdict,
            },
            "binds_on": list(self.binds_on),
            "undetermined_because": list(self.undetermined_because),
            "ineligible_funding": list(self.ineligible),
            # Which record produced this, so a reader can find the figures rather than trust them.
            "conventions": "property-funding.json",
        }


def assess(
    *,
    goal_id: str,
    price: float | None,
    target_date: date | None,
    occupancy: str | None,
    hard_available: float | None,
    pillar2_available: float = 0,
    pillar3a_available: float = 0,
    household_income: float | None,
) -> Assessment:
    """Both tests for one property goal.

    `hard_available` is money that is neither pillar 2 nor pillar 3a, and **`None` means the member has
    not said which holdings are for this goal** — which is different from having none, and is reported as
    undetermined rather than as a shortfall. The 3a is passed separately because whether it counts depends
    on the occupancy: it is hard equity for a home the member lives in and unavailable for anything else,
    and folding it into `hard_available` at the call site would hide that.

    `household_income` is the household's, not the member's, and it is the caller's job to have composed
    it. One of the six real cases is reachable on joint income and absurd on one income, so a caller
    passing a single member's figure for a couple produces a true statement about the wrong household.
    """
    result = Assessment(goal_id=goal_id, price=price or 0, target_date=target_date, occupancy=occupancy)

    if not price:
        result.undetermined_because.append("the_goal_names_no_amount")
        return result

    if occupancy is None:
        # **Never the favourable case.** Assuming owner-occupied would make pension capital eligible for a
        # holiday home, which is not a matter of degree — see the module docstring.
        result.undetermined_because.append("the_goal_does_not_say_whether_the_member_will_live_in_it")
        return result

    rule = occupancy_rule(occupancy)
    result.equity = equity(price, occupancy=occupancy)

    if hard_available is None:
        # **Nobody has said which money is for this goal, and that is not the same as not having it.**
        # Found by running a real member through the route: Marvin holds 222'750 against a 150'000 hard
        # requirement and the equity test reported `does_not_meet`, because `goal.funded_by` is empty for
        # every goal in the build. Reporting a shortfall there would tell a member they are short of a
        # deposit they have, on the strength of a link they were never asked to make — the unfavourable
        # mirror of the mistake A110 forbids in the other direction.
        result.undetermined_because.append("no_position_is_linked_to_this_goal")
    else:
        hard = hard_available + (pillar3a_available if rule["pillar3a_may_fund"] else 0)
        result.equity_verdict = result.equity.verdict(
            hard_available=hard, pillar2_available=pillar2_available
        )

    for label, amount, allowed in (
        ("pillar_2", pillar2_available, rule["pillar2_may_fund"]),
        ("pillar_3a", pillar3a_available, rule["pillar3a_may_fund"]),
    ):
        if amount and not allowed:
            result.ineligible.append({
                "kind": label,
                "amount_chf": amount,
                "reason": "vorsorge_capital_only_for_an_owner_occupied_primary_residence",
            })

    # **The affordability test is not computable for every occupancy, and computing it anyway was a
    # defect.** Found on 5 September by answering the occupancy question through the client for the first
    # time: a goal set to `let_to_someone_else` came back `does_not_meet` on an affordability figure that
    # contains no rent at all. For a property bought to let, the rent is most of the income that carries
    # it -- omitting it does not understate the position slightly, it removes the point of the purchase,
    # and the member is told a lender would refuse them on a calculation no lender would run.
    #
    # This is A110's family in its damaging direction, and the record already forbade it in prose: the
    # `_provisional_note` on that occupancy has said since approval that a finding here "reports the
    # equity test and says the affordability test could not be determined, rather than guessing".
    # `affordability_is_determinable` is that sentence made machine-readable. Defaulting to True keeps
    # every other occupancy unchanged and keeps a record that predates the key working.
    if not rule.get("affordability_is_determinable", True):
        result.undetermined_because.append("rental_income_is_not_modelled_for_a_let_property")
    else:
        result.affordability = affordability(price, income=household_income)
        result.affordability_verdict = result.affordability.verdict(income=household_income)
        if household_income is None:
            result.undetermined_because.append("no_income_is_recorded_for_the_household")

    if result.equity_verdict == DOES_NOT_MEET:
        result.binds_on.append(EQUITY)
    if result.affordability_verdict == DOES_NOT_MEET:
        result.binds_on.append(AFFORDABILITY)
    return result


def levers(assessment: Assessment, *, household_income: float | None) -> list[dict]:
    """The dimensions that would change the answer, each with its arithmetic. Not advice, and not ranked.

    C-01 forbids a personalised recommendation, and "buy a cheaper house" is one. A list of dimensions with
    a number against each is a computation: the member decides which of them they are willing to move, and
    a curator is required only to recommend one. Deliberately returns keys rather than sentences — the
    wording is the client's, and a sentence composed here would be a sentence this module could not have
    checked against C-01's outbound scan.
    """
    # **Each block is guarded separately.** This used to return `[]` unless BOTH tests had run, which was
    # harmless while every occupancy produced both -- and stopped being harmless the moment
    # `let_to_someone_else` began reporting affordability as undeterminable: the equity lever, which is
    # perfectly computable for a let property, disappeared with it. A lever list is a list of dimensions,
    # and one dimension being unavailable is not a reason to withhold the others.
    out: list[dict] = []

    if (assessment.affordability is not None and AFFORDABILITY in assessment.binds_on
            and assessment.affordability.price_supported is not None):
        out.append({
            "lever": "price",
            "supported_chf": assessment.affordability.price_supported,
            "stated_chf": assessment.price,
            "difference_chf": assessment.price - assessment.affordability.price_supported,
        })
        out.append({
            "lever": "household_income",
            "required_chf": assessment.affordability.income_required,
            "recorded_chf": household_income,
            "difference_chf": (
                assessment.affordability.income_required - household_income
                if household_income is not None else None
            ),
        })

    if assessment.equity is not None and EQUITY in assessment.binds_on:
        out.append({
            "lever": "deposit",
            "required_chf": assessment.equity.required,
            "hard_required_chf": assessment.equity.hard_required,
        })

    return out


__all__ = [
    "MandateTarget",
    "mandate_target",
    "AFFORDABILITY",
    "Affordability",
    "Assessment",
    "COULD_NOT_BE_DETERMINED",
    "ConventionsNotApproved",
    "DOES_NOT_MEET",
    "EQUITY",
    "Equity",
    "MEETS",
    "UnknownOccupancy",
    "affordability",
    "assess",
    "conventions",
    "equity",
    "levers",
    "occupancies",
    "occupancy_rule",
]
