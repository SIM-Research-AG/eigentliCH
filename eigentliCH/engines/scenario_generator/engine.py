"""Scenario Generator: what a proposed change does to a household's position.

Reads a Snapshot and a change. Writes a Scenario.

**The line this engine must not cross.** A Scenario says "if you did X, the model projects Y". A Recommendation
says "do X". The difference is not tone: it is whether the output names an action for the client to take. So the
change is always the *client's*, and `Scenario.change_origin` refuses `system` at the contract level. An engine
that generated its own changes and presented them as what-ifs would be issuing advice with the label removed,
and it would bypass the wall entirely.

That constraint decides the shape of this engine: it **applies** a change and reports the consequence. It does
not search for a good change, rank changes, or suggest one. Those are optimiser jobs, and the optimiser's output
is regulated.

**What a change may touch.** Only the household's own levers: contributions, the horizon, the target, and the
starting position. Not the mandate, not the bounds, not the regime. Changing the mandate would be changing the
advice; changing the regime would be answering a different question about the world rather than about the
household.

**How the consequence is computed.** By re-projecting the goal under the change and differencing. The engine
therefore inherits the S-curve's model and its honesty: the band is a dispersion sketch, and a real confidence
statement belongs to the Life Balance Sheet's CVaR route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.s_curve_trajectory.engine import Curve, project

#: The only fields a client-originated change may touch. Anything else is either advice or a different question.
CHANGEABLE: frozenset[str] = frozenset(
    {
        "annual_contribution",
        "horizon_years",
        "target",
        "initial_wealth",
        "annual_return",
    }
)

#: Changing this one is legitimate but means something different: it is a question about the world rather than
#: about the household, so it is reported as such.
WORLD_FIELDS: frozenset[str] = frozenset({"annual_return"})


class ChangeRefused(ValueError):
    """Raised when a change is not the client's to make, or not this engine's to apply."""


@dataclass(frozen=True)
class Baseline:
    """The household position a scenario departs from."""

    initial_wealth: float
    target: float | None
    horizon_years: float
    annual_return: float
    annual_contribution: float
    annual_volatility: float | None = None

    def with_change(self, field: str, to_value: Any) -> "Baseline":
        if field not in CHANGEABLE:
            raise ChangeRefused(
                f"{field!r} is not a field a client-originated scenario may change. Changeable: "
                f"{sorted(CHANGEABLE)}. The mandate and its bounds are investment policy, and changing them "
                f"would be changing the advice rather than asking a what-if."
            )
        from dataclasses import replace

        return replace(self, **{field: to_value})


@dataclass(frozen=True)
class Outcome:
    """What the change did, as differences rather than levels.

    Differences, because a scenario's whole content is the comparison. Reporting only the new levels would make
    a reader do the subtraction and would hide a change that moved nothing.
    """

    field: str
    from_value: Any
    to_value: Any
    base: Curve
    changed: Curve

    @property
    def final_value_delta(self) -> float:
        return self.changed.final_value - self.base.final_value

    @property
    def contributed_delta(self) -> float:
        return self.changed.total_contributed - self.base.total_contributed

    @property
    def funded_at_delta(self) -> float | None:
        """Years earlier the goal funds. Positive means sooner.

        None when either path never funds, because a difference against "never" is not a number.
        """
        if self.base.funded_at_years is None or self.changed.funded_at_years is None:
            return None
        return self.base.funded_at_years - self.changed.funded_at_years

    @property
    def required_return_delta(self) -> float | None:
        if self.base.required_return is None or self.changed.required_return is None:
            return None
        return self.changed.required_return - self.base.required_return

    @property
    def flips_on_track(self) -> str | None:
        """Whether the change turns a failing goal into a funded one, or the reverse."""
        if self.base.on_track is None or self.changed.on_track is None:
            return None
        if self.base.on_track == self.changed.on_track:
            return None
        return "now funded" if self.changed.on_track else "no longer funded"

    def efficiency(self) -> float | None:
        """Terminal wealth gained per franc of extra contribution.

        The question a client actually asks about saving more: what does the next franc buy. None when the
        change did not alter contributions, since dividing by zero would invent a number.
        """
        if abs(self.contributed_delta) < 1e-9:
            return None
        return self.final_value_delta / self.contributed_delta

    def notes(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.field in WORLD_FIELDS:
            out.append(
                f"{self.field} is an assumption about the world rather than a household lever, so this "
                f"scenario asks what happens under a different market, not what happens if the household acts "
                f"differently. Read it as a sensitivity, not as a choice."
            )
        flip = self.flips_on_track
        if flip:
            out.append(f"the change is decisive for this goal: it is {flip}.")
        elif abs(self.final_value_delta) < 1e-6:
            out.append(
                "the change moves the projected outcome by less than a franc, so on these inputs it does not "
                "matter for this goal."
            )
        gain = self.efficiency()
        if gain is not None:
            out.append(
                f"each extra franc contributed adds {gain:.2f} to terminal wealth over the horizon."
            )
        if self.base.funded_at_years is None and self.changed.funded_at_years is None:
            out.append(
                "neither the base case nor the scenario funds the goal inside the horizon, so the comparison "
                "is between two shortfalls rather than between two outcomes."
            )
        return tuple(out)


def apply_change(baseline: Baseline, field: str, to_value: Any) -> Outcome:
    """Project the baseline and the change, and return the comparison.

    Deterministic: both projections are closed-form given their inputs.
    """
    changed = baseline.with_change(field, to_value)
    from_value = getattr(baseline, field)

    def run(b: Baseline) -> Curve:
        return project(
            initial_wealth=b.initial_wealth,
            target=b.target,
            horizon_years=b.horizon_years,
            annual_return=b.annual_return,
            annual_contribution=b.annual_contribution,
            annual_volatility=b.annual_volatility,
        )

    return Outcome(
        field=field,
        from_value=from_value,
        to_value=to_value,
        base=run(baseline),
        changed=run(changed),
    )
