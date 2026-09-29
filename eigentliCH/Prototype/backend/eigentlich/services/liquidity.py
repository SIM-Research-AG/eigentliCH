"""The blocking liquidity finding. Item 4, and the one comparison that needs no published threshold.

Journey & Design page 2: "The `liquidity` field is enforced rather than displayed. When a goal's liquidity
requirement exceeds what its funding can actually supply on the date, that is a blocking finding, not a
footnote on a cheerful chart. The enforcement is what makes the goal system honest rather than decorative."

Item 4 says what the member sees and what is prepared, and both are narrow on purpose:

  * **The goal is not hidden, not greyed out, not marked failed.** It carries a state and stays in the list
    with everything else.
  * **Three things and nothing else:** the gap in francs, the date it falls due, and the reason in one
    line. "No warning colour doing the work of a sentence."
  * **One prepared option, not a menu** — Principle 4 — chosen by a fixed lever precedence held in
    `client/content/liquidity-levers.json`, never by minimising across francs, months and goal size.
  * **If no lever closes the gap alone, no option is prepared and it routes to the curator.**

===========================================================================================================
WHAT CAN BE DECIDED TODAY, AND WHAT IS WAITING ON A VOCABULARY
===========================================================================================================

The general form of the finding — "the goal's liquidity requirement exceeds what its funding can supply" —
needs `Goal.liquidity_need` to be comparable with `Position.liquidity`. **It is not, yet.**
`liquidity_need` is a free-text column with no published answer options: the five return-profile questions
are drafted and awaiting line-by-line approval, and `PICK-UP-HERE.md` records that as an owner decision.
Comparing a free-text answer with a band would mean inventing the mapping, which is the defect §12 names.

**One case is decidable now and needs no vocabulary at all**: a goal with a target date whose funding is
*entirely* marked `illiquid`. `services/goals.observations` already finds it — "the one comparison that
needs no threshold: everything funding this has been marked as not reliably convertible, and the goal has
a date" — and reports it as a note with no gap, no prepared option and no consequence. This module gives
that case the state, the figure and the prepared option item 4 asks for, and leaves the general case
plainly unbuilt rather than approximated.

So this is deliberately narrow. When the parameter vocabulary lands, `assess` grows a second branch and
everything below it — the precedence, the preparation, the curator route — is already here.

===========================================================================================================
AN UNDECIDABLE LEVER ROUTES TO A HUMAN; IT IS NOT SKIPPED
===========================================================================================================

The precedence claims the prepared option is **the first that closes the gap**. A lever whose effect cannot
be worked out cannot be ruled out, so skipping it would let a later, more expensive lever be prepared while
an earlier and cheaper one might have closed the gap — and the claim would then be one the code does not
keep. `prepare` therefore stops at the first lever it cannot decide and routes to a curator, which is what
item 4 says happens when the order cannot deliver an option.

`move_the_goal_date` is the lever this bites on, and only sometimes: no date makes an `illiquid` holding
available, so for the case above it is decidably *no*. For `within_years` funding it would close the gap at
some date, and naming that date needs a duration nobody has published.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..content import ContentMissing, liquidity_levers
from ..models import STOCK_UNITS, Goal

#: The state a short goal carries. Item 4 names it, and it is a state on the goal rather than a severity:
#: "The goal is not hidden, not greyed out, not marked failed."
SHORT_ON_DATE = "short_on_date"

#: What a lever evaluation can say. The third value is the one that matters — it is the Household
#: Optimiser's own third answer, and it is why an undecidable lever is not the same as a lever that fails.
CLOSES = "closes"
DOES_NOT_CLOSE = "does_not_close"
COULD_NOT_BE_DETERMINED = "could_not_be_determined"


def levers() -> list[dict]:
    """The fixed precedence, in publication order. Config, per item 4."""
    return liquidity_levers()


def lever_sentence(key: str, language: str = "de") -> str:
    for lever in levers():
        text = lever.get(language)
        if lever["key"] == key and text:
            return text
    raise ContentMissing(
        f"no liquidity lever {key!r} in language {language!r}. There is no literal to fall back to."
    )


@dataclass(frozen=True)
class Shortfall:
    """A goal that its funding cannot supply on its date. The three things the member sees, and no more."""

    #: The gap, in francs. `None` when the funding carries no stated magnitude — the goal is still short,
    #: and by how much is a different question from whether. Reported as absent rather than as zero.
    gap_chf: float | None
    due_date: date
    #: A key, not a sentence. The wording is the client's; the finding is this module's.
    reason: str
    #: The funding that cannot supply it. Named so the member can see which holding is meant.
    position_ids: tuple[str, ...] = ()

    #: Item 4: "The goal cannot be marked on track and the plan cannot be certified as funding it."
    blocks_certification: bool = True

    def as_dict(self) -> dict:
        return {
            "state": SHORT_ON_DATE,
            "gap_chf": self.gap_chf,
            "due_date": self.due_date.isoformat(),
            "reason": self.reason,
            "position_ids": list(self.position_ids),
            "blocks_certification": self.blocks_certification,
        }


@dataclass(frozen=True)
class Prepared:
    """The one option, or the absence of one and the route to a human."""

    #: The lever key, or None when none closed the gap or one could not be decided.
    lever: str | None
    #: Every lever tried and what it said, in precedence order. Present so the choice is inspectable —
    #: "the first that closes" is a claim, and this is the working.
    considered: tuple[dict, ...] = field(default_factory=tuple)
    requires_curator: bool = False
    #: Why it went to a curator, when it did.
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "lever": self.lever,
            "considered": [dict(one) for one in self.considered],
            "requires_curator": self.requires_curator,
            "reason": self.reason,
        }


def assess(goal: Goal, *, today: date) -> Shortfall | None:
    """Is this goal short on its date? `None` when it is not, or when the question cannot be asked.

    Today this finds exactly one shape: a dated goal funded entirely by holdings marked `illiquid`. See
    the module docstring for why the general comparison is not here.
    """
    if goal.target_date is None:
        return None

    funding = [position for position in goal.funded_by if position.active]
    stated = [position for position in funding if position.liquidity]
    if not stated:
        # Nothing to compare. `goals.observations` already reports unstated liquidity as its own fact, and
        # a goal whose funding is unmarked is not short — it is unmeasured.
        return None

    if not all(position.liquidity == "illiquid" for position in stated):
        return None

    amounts = [
        position.magnitude
        for position in stated
        # `in STOCK_UNITS`, never `== "chf"`: the literal is a PREFIX of `chf_per_year`, and a site that
        # reaches for one reaches for `startswith` next — which is A105's defect, a market rate applied to
        # a salary. `test_no_module_writes_the_stock_unit_as_a_literal` caught this line.
        if position.magnitude is not None and position.magnitude_unit in STOCK_UNITS
    ]
    return Shortfall(
        # The gap is what the goal cannot draw on: the funding that will not be there. Absent when the
        # member has stated no balance for it — "how much" is a different question from "whether".
        gap_chf=sum(amounts) if amounts else None,
        due_date=goal.target_date,
        reason="funding_is_illiquid",
        position_ids=tuple(position.id for position in stated),
    )


def _evaluate(lever: str, goal: Goal, shortfall: Shortfall, *, today: date) -> str:
    """What one lever would do about this shortfall. Three answers, never two."""
    if lever == "move_funding_to_a_liquid_form":
        # The funding is marked `illiquid` — not reliably convertible at all. Moving it into a liquid form
        # is not something the plan can assume is available; if it were, the member would not have marked
        # it that way.
        return DOES_NOT_CLOSE

    if lever == "move_the_goal_date":
        # Decidable HERE, and only here: no later date makes an illiquid holding available. For a
        # `within_years` holding this would close the gap at some date, and naming that date needs a
        # duration nobody has published — that branch returns COULD_NOT_BE_DETERMINED when it exists.
        return DOES_NOT_CLOSE

    if lever == "add_a_monthly_contribution":
        # Closes it: money set aside from now until the date is available on the date, by construction.
        # No rate is applied and none is needed — this is contributions, not growth.
        return CLOSES if goal.target_date > today else DOES_NOT_CLOSE

    if lever == "reduce_the_goal_size":
        return CLOSES

    return COULD_NOT_BE_DETERMINED


def prepare(goal: Goal, shortfall: Shortfall, *, today: date) -> Prepared:
    """The first lever that closes the gap, or a route to a human. Never a menu.

    Stops at the first lever it cannot decide rather than skipping it — see the module docstring: skipping
    would let a later lever be prepared while an earlier one might have closed the gap, and "the first
    that closes" would then be a claim this function does not keep.
    """
    considered: list[dict] = []
    for lever in levers():
        verdict = _evaluate(lever["key"], goal, shortfall, today=today)
        considered.append({"lever": lever["key"], "verdict": verdict})

        if verdict == COULD_NOT_BE_DETERMINED:
            return Prepared(
                lever=None,
                considered=tuple(considered),
                requires_curator=True,
                reason="a_lever_could_not_be_determined",
            )
        if verdict == CLOSES:
            return Prepared(lever=lever["key"], considered=tuple(considered))

    return Prepared(
        lever=None,
        considered=tuple(considered),
        requires_curator=True,
        reason="no_single_lever_closes_the_gap",
    )


def finding(goal: Goal, *, today: date) -> dict | None:
    """The whole finding for one goal, or None. What a goal payload carries."""
    shortfall = assess(goal, today=today)
    if shortfall is None:
        return None
    return {**shortfall.as_dict(), "prepared": prepare(goal, shortfall, today=today).as_dict()}


__all__ = [
    "CLOSES",
    "COULD_NOT_BE_DETERMINED",
    "DOES_NOT_CLOSE",
    "Prepared",
    "SHORT_ON_DATE",
    "Shortfall",
    "assess",
    "finding",
    "levers",
    "lever_sentence",
    "prepare",
]
