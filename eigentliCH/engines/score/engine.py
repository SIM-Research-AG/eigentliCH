"""Score engine: a household's standing, folded from its event stream and the Regime.

Reads the FDT event stream and the Regime. Writes a Score.

**Educational, and that constrains the design.** A score a client cannot interrogate is not education, it is a
verdict. So the score is always decomposable: every component carries its value, its weight and a note saying
what moved it, and the `Score` contract refuses component weights that do not sum to one. A number that cannot
be taken apart cannot be argued with, and a client who cannot argue with it has learned nothing.

**The weights are a judgement and are labelled as one.** Nothing in the framework derives them. They are a
declared editorial position about what a household should be judged on, held in `DEFAULT_WEIGHTS` so that
changing them is one visible edit rather than a hunt through the code.

**Why the Regime enters.** Saving consistently through a crisis is a different achievement from saving
consistently through a boom. The regime adjustment credits behaviour that held up when the macro state was
against it, and it is deliberately small: a score that swung with the market would measure the market rather
than the household.

**What it refuses to do.** It does not score a household with too few events. A score computed from four events
looks identical to one computed from four hundred, and presenting them alike would be the most misleading thing
this engine could do. Below the floor it returns no score and says why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

#: The editorial position: what a household is judged on, and how much each counts. Sums to one, checked.
DEFAULT_WEIGHTS: dict[str, float] = {
    "savings_consistency": 0.35,
    "goal_progress": 0.30,
    "liability_discipline": 0.20,
    "engagement": 0.15,
}

#: Below this many live events the stream is too thin to score. Returning a number anyway would present a guess
#: with the same authority as a measurement.
MINIMUM_EVENTS: int = 12

#: How much the regime adjustment may move a component, at most. Small on purpose: a score that swung with the
#: market would measure the market.
REGIME_ADJUSTMENT_CAP: float = 5.0

SCALE_MIN: float = 0.0
SCALE_MAX: float = 100.0


class NotEnoughHistory(ValueError):
    """Raised when the event stream is too thin to score honestly."""


@dataclass(frozen=True)
class Component:
    """One scored dimension, with what moved it."""

    name: str
    value: float
    weight: float
    note: str


@dataclass(frozen=True)
class Scored:
    """The score, its parts, and what it was computed from."""

    value: float
    components: tuple[Component, ...]
    events_considered: int
    tier: str
    regime_adjustment: float
    notes: tuple[str, ...]


def _clamp(value: float, low: float = SCALE_MIN, high: float = SCALE_MAX) -> float:
    return max(low, min(high, value))


def savings_consistency(events: Sequence[Mapping[str, Any]], months: int) -> Component:
    """How reliably contributions were made, not how large they were.

    Deliberately about regularity rather than amount: a household saving two hundred a month every month is
    doing something a household saving nothing for a year and then a lump sum is not, and size is already
    visible in the balance sheet. Scoring size here would double-count wealth and penalise a low income for
    being low.
    """
    contributions = [e for e in events if e.get("kind") == "contribution.made"]
    if months <= 0:
        return Component("savings_consistency", 0.0, DEFAULT_WEIGHTS["savings_consistency"],
                         "no period to measure over")

    # Distinct months in which a contribution was made, over months observed.
    months_with = {str(e.get("occurred_at", ""))[:7] for e in contributions if e.get("occurred_at")}
    ratio = len(months_with) / months
    value = _clamp(100.0 * min(1.0, ratio))
    return Component(
        "savings_consistency",
        value,
        DEFAULT_WEIGHTS["savings_consistency"],
        f"contributed in {len(months_with)} of {months} observed months",
    )


def goal_progress(events: Sequence[Mapping[str, Any]]) -> Component:
    """Progress against the goals the household has actually set.

    A household with no goal set scores zero here rather than being excused: setting a goal is the first act
    this engine is trying to encourage, and excusing its absence would reward not deciding.
    """
    set_events = [e for e in events if e.get("kind") == "goal.set"]
    reached = [e for e in events if e.get("kind") == "goal.reached"]

    if not set_events:
        return Component(
            "goal_progress", 0.0, DEFAULT_WEIGHTS["goal_progress"],
            "no goal has been set, which is the first thing to do rather than an exemption",
        )

    # Credit reaching goals, and give partial credit for having set them at all.
    completion = len(reached) / len(set_events)
    value = _clamp(40.0 + 60.0 * min(1.0, completion))
    return Component(
        "goal_progress",
        value,
        DEFAULT_WEIGHTS["goal_progress"],
        f"{len(reached)} of {len(set_events)} goal(s) reached",
    )


def liability_discipline(events: Sequence[Mapping[str, Any]]) -> Component:
    """Whether debt is being repaid faster than it is being taken on.

    Counts events rather than amounts, because an amount comparison would need a common currency and a
    valuation date, and the balance sheet is the right place for that. This measures the habit.
    """
    added = [e for e in events if e.get("kind") == "liability.added"]
    repaid = [e for e in events if e.get("kind") == "liability.repaid"]

    if not added and not repaid:
        return Component(
            "liability_discipline", 60.0, DEFAULT_WEIGHTS["liability_discipline"],
            "no liability activity recorded, scored as neutral rather than good: no evidence is not virtue",
        )
    total = len(added) + len(repaid)
    value = _clamp(100.0 * len(repaid) / total)
    return Component(
        "liability_discipline",
        value,
        DEFAULT_WEIGHTS["liability_discipline"],
        f"{len(repaid)} repayment(s) against {len(added)} new liability event(s)",
    )


def engagement(events: Sequence[Mapping[str, Any]], months: int) -> Component:
    """How actively the household maintains its own record.

    Included because the whole model rests on the twin being current: a stale twin produces a confident wrong
    answer. Capped so that activity alone cannot carry a score.
    """
    if months <= 0:
        return Component("engagement", 0.0, DEFAULT_WEIGHTS["engagement"], "no period to measure over")
    per_month = len(events) / months
    # Two events a month is taken as fully engaged. Beyond that adds nothing: this measures upkeep, not volume.
    value = _clamp(100.0 * min(1.0, per_month / 2.0))
    return Component(
        "engagement",
        value,
        DEFAULT_WEIGHTS["engagement"],
        f"{len(events)} event(s) over {months} months, {per_month:.1f} a month",
    )


def regime_adjustment(crisis_tail: float | None) -> tuple[float, str]:
    """Credit behaviour that held up when the macro state was against it.

    Scaled by the crisis tail of the live Regime, capped at `REGIME_ADJUSTMENT_CAP`. Small deliberately: the
    household's conduct is what is being scored, not the weather.
    """
    if crisis_tail is None:
        return 0.0, "no Regime supplied, so no regime adjustment was applied"
    adjustment = REGIME_ADJUSTMENT_CAP * min(1.0, max(0.0, float(crisis_tail)))
    return adjustment, (
        f"crisis tail {crisis_tail:.3f} credits {adjustment:+.1f} for maintaining conduct against an adverse "
        f"macro state, capped at {REGIME_ADJUSTMENT_CAP:g}"
    )


def tier_for(value: float) -> str:
    """The ladder position, named in the framework's phase vocabulary.

    Uses the capital-cycle phase names deliberately, so a client sees one vocabulary across the whole system
    rather than a separate set of score badges.
    """
    if value >= 80.0:
        return "Saturation"
    if value >= 60.0:
        return "Optimisation"
    if value >= 35.0:
        return "Build-up"
    return "Foundation"


def score(
    events: Sequence[Mapping[str, Any]],
    months_observed: int,
    crisis_tail: float | None = None,
    weights: Mapping[str, float] | None = None,
) -> Scored:
    """Fold an event stream into a decomposable score.

    Args:
        events: The **live** events, that is with superseded ones already dropped. A correction applied
            alongside the thing it corrects would count twice.
        months_observed: How long the stream covers. The denominator for the rate components.
        crisis_tail: From the live Regime, for the adjustment.
        weights: Override the editorial weights. Must sum to one.

    Raises:
        NotEnoughHistory: Below `MINIMUM_EVENTS`.
        ValueError: If the weights do not sum to one.
    """
    if len(events) < MINIMUM_EVENTS:
        raise NotEnoughHistory(
            f"{len(events)} event(s) is too thin to score: the floor is {MINIMUM_EVENTS}. A score from a "
            f"handful of events would look identical to one from hundreds, and presenting them alike is the "
            f"most misleading thing this engine could do. Report 'not yet scored' instead."
        )

    active = dict(weights or DEFAULT_WEIGHTS)
    total_weight = sum(active.values())
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(
            f"the score weights sum to {total_weight}, not 1, so the decomposition would not account for the "
            f"score"
        )

    parts = [
        savings_consistency(events, months_observed),
        goal_progress(events),
        liability_discipline(events),
        engagement(events, months_observed),
    ]
    # Re-weight in case an override changed them.
    parts = [Component(p.name, p.value, active[p.name], p.note) for p in parts]

    weighted = sum(p.value * p.weight for p in parts)
    adjustment, adjustment_note = regime_adjustment(crisis_tail)
    value = _clamp(weighted + adjustment)

    notes = [
        "the component weights are an editorial judgement about what a household should be judged on, not a "
        "quantity the framework derives. They are declared in DEFAULT_WEIGHTS.",
        adjustment_note,
        "the components measure habits rather than amounts: size is already visible in the balance sheet, and "
        "scoring it here would double-count wealth and penalise a low income for being low.",
    ]

    return Scored(
        value=value,
        components=tuple(parts),
        events_considered=len(events),
        tier=tier_for(value),
        regime_adjustment=adjustment,
        notes=tuple(notes),
    )
