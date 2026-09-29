"""The S-curve goal trajectory: does this goal get funded, and when.

Reads a goal, a contributions path and a return. Writes a Trajectory. Per-goal rather than per-user, which is
why it is a separate engine from the Life Balance Sheet: the household simulation answers "what happens to this
person", and this answers "does this one goal land".

**Why it is called an S-curve.** Wealth accumulating under a constant return with steady contributions grows
convexly at first, because the contributions dominate, then the compounding takes over. Plotted against a fixed
target the *funding ratio* traces an S: slow, then fast, then flattening as it approaches and passes one. The
useful reading is not the level but where the knee sits relative to the deadline.

**The model, stated plainly so it can be argued with.**

    W(t+1) = W(t) * (1 + r_period) + c(t)

with `r_period = (1 + r_annual)^(1/steps_per_year) - 1`, so an annual return compounds at the step frequency
rather than being divided. Dividing would understate the return, and by more the longer the horizon.

**The band is not a distribution.** Given a volatility it draws `value * (1 +/- z * sigma * sqrt(t))`, which is
a spread that widens with the square root of time. That is a legible sketch of dispersion, not a modelled
quantile: it assumes returns are independent across periods and it ignores the contributions' own timing. Where
a real confidence statement is needed, the Life Balance Sheet's CVaR route is the engine that owns it, and this
one says so rather than pretending otherwise.

**`project_over_regime` replaces that sketch with a real one, and `project` keeps it.** Added 2026-08-02
(`DECISIONS.md` M54) on the author's instruction to bring the market signal and the Fund Map's returns into this
engine. Given the ReturnSet's per-state returns and the Regime's own 25-state probability vector, it projects
**one exact path per state** through the same recursion below and reports:

- the **probability-weighted mixture** of those paths as the central line,
- a band from **weighted quantiles across the states**, which is a genuine quantile over a genuine discrete
  distribution rather than a normal assumption,
- and `funded_probability`, the regime mass on states whose path actually reaches the target — a statement the
  sigma-sqrt-t band could not make at all.

`project` is untouched and still takes one constant return, because the mandate's required return is a constant
by definition and `validation/calibration.py` checks this recursion against a closed form. Two functions, two
claims, neither pretending to be the other.

**What the new band does and does not claim, because it is a different limitation rather than none.** It
captures **regime uncertainty**: the spread of outcomes across macro states, weighted by how likely each state
is. It does *not* capture within-regime volatility — inside a state the return is constant, so a state that is
merely *volatile* rather than *bad* shows no spread. And every magnitude inherits M9: the per-state returns are
seed-based rather than estimated. So the band is now well-founded in its own terms and still rests on inputs
that are illustrative.

**One arithmetical trap, worth stating because it is easy to get backwards.** The mixture of paths is not the
path of the mixture: `E[W(r)] != W(E[r])`. Wealth is convex in the return, so averaging the *paths* gives a
higher terminal value than projecting at the *average* return. This engine averages paths, which is the correct
order, and `test_mixture_exceeds_the_path_of_the_mean_return` asserts the inequality so the two cannot be
silently swapped.

**Nothing here is fitted.** Every input is supplied. The engine computes an implication of the inputs, which is
why it is deterministic and why it cannot be wrong about anything except arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: Steps per year. Monthly, matching the Regime's frequency and the Life Balance Sheet's dt, so the three
#: engines' paths can be read on one axis.
STEPS_PER_YEAR: int = 12

#: The z multiplier for the reported band. 1.2816 is the 90th percentile of the standard normal, so the band
#: spans a nominal 80 percent under the sketch's own assumptions. Named rather than inlined because it is a
#: presentation choice, not a property of the model.
BAND_Z: float = 1.2816

#: The highest annual return `required_return` will search before declaring a goal infeasible. A goal needing
#: more than 1000 percent a year is not a demanding mandate, it is an impossible one, and saying so is more
#: use than returning a large number.
SEARCH_CEILING: float = 10.0


@dataclass(frozen=True)
class Point:
    """One step on the path."""

    t_years: float
    value: float
    lower: float | None
    upper: float | None
    contributed_to_date: float
    #: value / target, or None when there is no target. The quantity the S is traced in.
    funding_ratio: float | None


@dataclass(frozen=True)
class Curve:
    """A goal's projected path and what it implies."""

    points: tuple[Point, ...]
    target: float | None
    horizon_years: float
    annual_return: float
    total_contributed: float
    final_value: float
    #: The first time the path reaches the target, in years, or None if it never does inside the horizon.
    funded_at_years: float | None
    on_track: bool | None
    #: The constant annual return that would just fund the goal by the deadline. The mandate's required return
    #: when this goal is the binding one.
    required_return: float | None
    notes: tuple[str, ...]


def project(
    initial_wealth: float,
    target: float | None,
    horizon_years: float,
    annual_return: float,
    annual_contribution: float = 0.0,
    contributions: Sequence[float] | None = None,
    annual_volatility: float | None = None,
) -> Curve:
    """Project a goal forward.

    Args:
        initial_wealth: Starting drawable wealth.
        target: The requirement at the deadline. None for an open-ended projection.
        horizon_years: The deadline.
        annual_return: Expected annual return, as a decimal.
        annual_contribution: A steady annual contribution, spread evenly across the steps.
        contributions: A per-step contribution path, which overrides `annual_contribution` when given. Must be
            at least as long as the number of steps, and a shorter one is an error rather than being padded
            with zeros: a silently shortened contribution path would flatter the projection.
        annual_volatility: Draws the dispersion band. None leaves the band off, which is the honest default.

    Raises:
        ValueError: On a non-positive horizon, a return at or below -100 percent, or a contributions path too
            short for the horizon.
    """
    if horizon_years <= 0:
        raise ValueError(f"horizon_years must be positive, got {horizon_years}")
    if annual_return <= -1.0:
        raise ValueError(
            f"annual_return={annual_return} would destroy more than the whole portfolio each year"
        )

    steps = max(1, int(round(horizon_years * STEPS_PER_YEAR)))
    step_return = (1.0 + annual_return) ** (1.0 / STEPS_PER_YEAR) - 1.0

    if contributions is not None:
        if len(contributions) < steps:
            raise ValueError(
                f"the contributions path has {len(contributions)} entries but the horizon needs {steps}. A "
                f"short path is not padded with zeros, because that would quietly flatter the projection."
            )
        path = [float(c) for c in contributions[:steps]]
    else:
        path = [float(annual_contribution) / STEPS_PER_YEAR] * steps

    notes: list[str] = []
    value = float(initial_wealth)
    contributed = 0.0
    points = [
        Point(
            t_years=0.0,
            value=value,
            lower=value if annual_volatility else None,
            upper=value if annual_volatility else None,
            contributed_to_date=0.0,
            funding_ratio=None if not target else value / target,
        )
    ]
    funded_at: float | None = 0.0 if (target is not None and value >= target) else None

    for step in range(1, steps + 1):
        value = value * (1.0 + step_return) + path[step - 1]
        contributed += path[step - 1]
        t = step / STEPS_PER_YEAR

        lower = upper = None
        if annual_volatility:
            spread = BAND_Z * float(annual_volatility) * (t ** 0.5)
            lower = value * (1.0 - spread)
            upper = value * (1.0 + spread)

        if funded_at is None and target is not None and value >= target:
            funded_at = t

        points.append(
            Point(
                t_years=t,
                value=value,
                lower=lower,
                upper=upper,
                contributed_to_date=contributed,
                funding_ratio=None if not target else value / target,
            )
        )

    if annual_volatility:
        notes.append(
            f"the band is a dispersion sketch at z={BAND_Z:g} widening with the square root of time, not a "
            f"modelled quantile. It assumes independent period returns and ignores contribution timing. For a "
            f"real confidence statement use the Life Balance Sheet's CVaR route."
        )
    if target is not None and funded_at is None:
        notes.append(
            f"the goal is not funded inside {horizon_years:g} years on these inputs: the path reaches "
            f"{value:,.0f} against a target of {target:,.0f}."
        )
    elif funded_at is not None and target is not None and funded_at < horizon_years:
        notes.append(
            f"the goal funds at {funded_at:.1f} years, {horizon_years - funded_at:.1f} years inside the "
            f"deadline."
        )

    required = required_return(initial_wealth, target, horizon_years, path) if target else None
    if required is not None and required > annual_return:
        notes.append(
            f"the goal needs {required:.2%} a year against the {annual_return:.2%} assumed, a shortfall of "
            f"{required - annual_return:.2%}."
        )

    return Curve(
        points=tuple(points),
        target=target,
        horizon_years=float(horizon_years),
        annual_return=float(annual_return),
        total_contributed=contributed,
        final_value=value,
        funded_at_years=funded_at,
        on_track=None if target is None else bool(value >= target),
        required_return=required,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class StatePath:
    """One macro state's exact path, and how much regime weight it carries."""

    state: int
    annual_return: float
    weight: float
    values: tuple[float, ...]
    final_value: float
    #: The first time this state's path reaches the target, or None if it never does inside the horizon.
    funded_at_years: float | None

    @property
    def funds(self) -> bool:
        return self.funded_at_years is not None


@dataclass(frozen=True)
class RegimeCurve:
    """A goal projected across the macro states, mixed by the Regime's own probabilities.

    Attributes:
        points: The probability-weighted central path, with the band from cross-state weighted quantiles.
        state_paths: Every state's exact path, so the mixture can be taken apart.
        target: The requirement at the deadline.
        horizon_years: The deadline.
        expected_return: The probability-weighted annual return. Reported because it is the interpretable
            scalar, *not* because the central path is what projecting at it would give — it is not.
        mixture_final_value: The probability-weighted terminal wealth. This is the honest expectation.
        deterministic_final_value: What projecting at `expected_return` alone would have produced. Carried
            beside the mixture precisely so the gap between them is visible rather than arguable.
        funded_probability: Regime mass on states whose path reaches the target. The quantity the old band
            could not produce.
        band_lower / band_upper: The quantiles the band was drawn at.
        required_return: The constant annual return that funds the goal exactly. Unchanged in meaning.
        notes: What a reader must know.
    """

    points: tuple[Point, ...]
    state_paths: tuple[StatePath, ...]
    target: float | None
    horizon_years: float
    expected_return: float
    mixture_final_value: float
    deterministic_final_value: float
    funded_probability: float
    band_lower: float
    band_upper: float
    total_contributed: float
    required_return: float | None
    on_track: bool | None
    notes: tuple[str, ...]


def _weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    """The weighted quantile of a small discrete distribution, at midpoint plotting positions.

    Written out rather than pulled from numpy because this engine is pure Python by design — the contracts and
    the orchestration carry no numpy, and a projection over 25 states is 25 numbers.

    **Each atom is placed at the midpoint of the weight it occupies**, position `(cumulative - w/2) / total`,
    and the quantile is interpolated linearly between those positions. This is the standard construction for a
    weighted quantile, and the reason for it is that the naive alternative — "the smallest value whose
    cumulative weight reaches q" — steps by whole states. On 25 states that makes a band edge jump from one
    state's path to the next as the regime weights move, which reads as a finding when nothing happened.

    A first version of this interpolated from the *previous* atom's value, which on the first atom has no
    previous and silently returned the extreme. Both band edges then pinned to the best and worst paths and
    stopped responding to the regime weights at all. Caught by
    `test_shifting_regime_weight_to_bad_states_lowers_the_band`.

    Beyond the outermost positions the result clamps to the outermost values, which is correct: there is no
    information out there to extrapolate from, and inventing some would widen a band on no evidence.
    """
    pairs = sorted(zip(values, weights), key=lambda vw: vw[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        raise ValueError("the regime weights sum to zero, so no quantile exists")

    positions: list[float] = []
    cumulative = 0.0
    for _, weight in pairs:
        cumulative += weight
        positions.append((cumulative - weight / 2.0) / total)

    if q <= positions[0]:
        return pairs[0][0]
    if q >= positions[-1]:
        return pairs[-1][0]
    for index in range(1, len(positions)):
        if q <= positions[index]:
            low_pos, high_pos = positions[index - 1], positions[index]
            low_val, high_val = pairs[index - 1][0], pairs[index][0]
            if high_pos <= low_pos:      # coincident positions, from a zero-weight atom
                return high_val
            span = (q - low_pos) / (high_pos - low_pos)
            return low_val + (high_val - low_val) * span
    return pairs[-1][0]


def project_over_regime(
    initial_wealth: float,
    target: float | None,
    horizon_years: float,
    returns_by_state: Sequence[float],
    state_weights: Sequence[float],
    annual_contribution: float = 0.0,
    contributions: Sequence[float] | None = None,
    band: tuple[float, float] = (0.10, 0.90),
) -> RegimeCurve:
    """Project a goal across the macro states and mix the paths by the Regime's probabilities.

    Args:
        initial_wealth: Starting drawable wealth.
        target: The requirement at the deadline. None for an open-ended projection.
        horizon_years: The deadline.
        returns_by_state: One annual return per macro state, from the ReturnSet's per-state profiles evaluated
            over the allocation being tested.
        state_weights: The Regime's probability per state. Normalised here; need not sum to one.
        annual_contribution: A steady annual contribution.
        contributions: A per-step path, overriding `annual_contribution`.
        band: The quantile pair the band is drawn at. Defaults to 10th and 90th, an 80 percent span, which is
            the same nominal coverage the retired sigma-sqrt-t band claimed — chosen so the two are comparable
            rather than because 80 is special.

    Raises:
        ValueError: If the two sequences disagree in length, if either is empty, if the weights do not sum to
            something positive, or if the band quantiles are not an increasing pair inside (0, 1).
    """
    if len(returns_by_state) != len(state_weights):
        raise ValueError(
            f"{len(returns_by_state)} per-state returns against {len(state_weights)} state weights. They must "
            f"describe the same axis, and padding either would invent a state."
        )
    if not returns_by_state:
        raise ValueError("no per-state returns were given, so there is no distribution to project over")
    low_q, high_q = band
    if not 0.0 < low_q < high_q < 1.0:
        raise ValueError(f"the band quantiles must satisfy 0 < low < high < 1, got {band}")

    total_weight = float(sum(state_weights))
    if total_weight <= 0.0:
        raise ValueError("the state weights sum to zero, so the Regime carries no distribution to mix over")
    omega = [float(w) / total_weight for w in state_weights]

    # One exact path per state, through the same recursion `project` uses. Reusing `project` rather than
    # reimplementing the loop keeps the two functions arithmetically identical by construction: a change to
    # the recursion cannot apply to one and not the other.
    curves = [
        project(
            initial_wealth=initial_wealth,
            target=target,
            horizon_years=horizon_years,
            annual_return=float(r),
            annual_contribution=annual_contribution,
            contributions=contributions,
            annual_volatility=None,
        )
        for r in returns_by_state
    ]

    steps = len(curves[0].points)
    state_paths = tuple(
        StatePath(
            state=index,
            annual_return=float(returns_by_state[index]),
            weight=omega[index],
            values=tuple(p.value for p in curve.points),
            final_value=curve.final_value,
            funded_at_years=curve.funded_at_years,
        )
        for index, curve in enumerate(curves)
    )

    points: list[Point] = []
    for step in range(steps):
        values = [curve.points[step].value for curve in curves]
        mixed = sum(w * v for w, v in zip(omega, values))
        lower = _weighted_quantile(values, omega, low_q)
        upper = _weighted_quantile(values, omega, high_q)
        reference = curves[0].points[step]
        points.append(
            Point(
                t_years=reference.t_years,
                value=mixed,
                lower=lower,
                upper=upper,
                contributed_to_date=reference.contributed_to_date,
                funding_ratio=None if not target else mixed / target,
            )
        )

    expected_return = sum(w * float(r) for w, r in zip(omega, returns_by_state))
    mixture_final = points[-1].value
    deterministic = project(
        initial_wealth=initial_wealth,
        target=target,
        horizon_years=horizon_years,
        annual_return=expected_return,
        annual_contribution=annual_contribution,
        contributions=contributions,
    )
    funded_probability = sum(w for w, path in zip(omega, state_paths) if path.funds)

    notes = [
        f"projected over {len(returns_by_state)} macro states and mixed by the Regime's own probabilities. The "
        f"band is the {low_q:.0%} to {high_q:.0%} weighted quantile ACROSS STATES, which is a real quantile "
        f"over a real discrete distribution rather than a normal assumption.",
        f"it captures regime uncertainty and not within-regime volatility: inside a state the return is "
        f"constant, so a state that is merely volatile rather than bad shows no spread here. The Life Balance "
        f"Sheet's CVaR route remains the engine that owns a full confidence statement.",
        f"per-state returns span {min(returns_by_state):.2%} to {max(returns_by_state):.2%}. Every magnitude "
        f"inherits DECISIONS.md M9: these profiles are seed-based rather than estimated from instrument "
        f"series, so the band's width tests the plumbing rather than the market.",
    ]
    if target is not None:
        notes.append(
            f"the goal is funded in states carrying {funded_probability:.1%} of the regime weight. That is a "
            f"probability over macro states, not a confidence interval, and it is the statement the retired "
            f"sigma-sqrt-t band could not make."
        )
    if mixture_final > deterministic.final_value:
        notes.append(
            f"the mixture of paths reaches {mixture_final:,.0f} against {deterministic.final_value:,.0f} for a "
            f"single path at the {expected_return:.2%} weighted-average return. The gap is Jensen's "
            f"inequality, not an error: wealth is convex in the return, so averaging paths is not projecting "
            f"at the average. This engine averages paths, which is the correct order."
        )

    return RegimeCurve(
        points=tuple(points),
        state_paths=state_paths,
        target=target,
        horizon_years=float(horizon_years),
        expected_return=expected_return,
        mixture_final_value=mixture_final,
        deterministic_final_value=deterministic.final_value,
        funded_probability=funded_probability,
        band_lower=low_q,
        band_upper=high_q,
        total_contributed=deterministic.total_contributed,
        required_return=deterministic.required_return,
        on_track=None if target is None else bool(mixture_final >= target),
        notes=tuple(notes),
    )


def required_return(
    initial_wealth: float,
    target: float,
    horizon_years: float,
    contributions: Sequence[float],
    tolerance: float = 1e-10,
    max_iterations: int = 200,
) -> float | None:
    """The constant annual return that funds the goal exactly by the deadline.

    This is the quantity the derived mandate needs: the return the household's own goal demands. Solved by
    bisection rather than in closed form, because a per-step contribution path has no clean inverse and
    bisection is robust to one that varies.

    Returns:
        The required annual return. **`0.0`** when the goal is already funded by contributions alone, since
        then the mandate is capital preservation rather than growth. **`None`** means exactly one thing: the
        goal cannot be funded at any return below `SEARCH_CEILING`, so it is infeasible rather than merely
        demanding.

    Raises:
        ValueError: On input that cannot describe a goal — an empty contribution path or a non-positive
            horizon. Those are programming errors rather than household conditions, and returning `None` for
            them made `None` mean three different things at once: malformed, already funded, and impossible.
            A caller could not tell an infeasible goal from a bad call, which is precisely the distinction
            the derived mandate needs. Found by the Phase 7 validation suite; see DECISIONS.md M27.
    """
    steps = len(contributions)
    if steps == 0:
        raise ValueError(
            "required_return needs a contribution path with at least one step. An empty path cannot "
            "describe a goal, and returning None would be indistinguishable from an infeasible goal."
        )
    if horizon_years <= 0:
        raise ValueError(
            f"required_return needs a positive horizon, got {horizon_years!r}. A deadline in the past or "
            f"at zero is not a goal."
        )

    def terminal(annual: float) -> float:
        step = (1.0 + annual) ** (1.0 / STEPS_PER_YEAR) - 1.0
        value = float(initial_wealth)
        for c in contributions:
            value = value * (1.0 + step) + c
        return value

    # Already there without any return: the mandate is capital preservation, not growth.
    if terminal(0.0) >= target:
        return 0.0

    low, high = 0.0, 1.0
    # Widen the ceiling until the goal is reachable, or give up. A goal needing more than the ceiling is not
    # a mandate, it is an infeasibility, and saying so is more use than returning a large number.
    while terminal(high) < target:
        high *= 2.0
        if high > SEARCH_CEILING:
            return None

    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        if terminal(mid) < target:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break
    return 0.5 * (low + high)
