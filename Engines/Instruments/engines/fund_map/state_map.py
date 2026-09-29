"""The quantile bridge between the monthly Market Risk Signal and the annual calibration.

Two axes both happen to have twenty-five positions, and that is a coincidence rather than
a correspondence. The Market Risk Signal's columns are labelled ``(1): Cautious`` through
``(25): Aggressive`` -- five named bands of five. The calibration axis is a phase-ordinal
scale running 0.6 to 5.4, derived from the distribution of a 150-year economic cycle.
Mapping column *n* onto state *n* would assert that the two scales are calibrated the
same way, which nobody has shown, and the prototype's own provenance note flags it as
"an assumption someone has to make deliberately".

**So the map is built by quantile instead.** A signal column is located by the share of
history that sits at or below it; the calibration axis is then read at the same share of
*its* history. If the signal spends most of its time in the middle of its range and the
economic cycle spends most of its time in the middle of its own, the two middles line up
-- whatever the labels say.

**Why the centile definition matters.** The reference implementation locates the current
reading with ``100 * (nless + 0.5 * nequal) / n``, and MATLAB's ``prctile`` inverts with
order statistics placed at ``100 * (i - 0.5) / n``. Both conventions are reproduced in
``numerics``. numpy's defaults differ from both, and they differ most in the tails --
which is exactly where crisis lives and where the bridge does its most consequential work.

The map is a versioned artefact with its own id, because a figure produced under one
bridge is not comparable with a figure produced under another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from engines.fund_map import numerics as num
from engines.fund_map.calibrate import PHASE_KNOTS, STATE_COUNT, state_axis
from engines.fund_map.phases import PHASE_VALUES

#: How the bridge was built. Stamped on the artefact so a consumer can tell.
METHOD = "quantile:centile-of-unconditional-mass"


def cycle_sigma_to_axis(sigma: float) -> float:
    """Convert an economic-cycle reading in sigma to a position on the 1..5 phase axis.

    The five phases have representative cycle values of -1.325, -0.6, 0, +0.6 and +1.325
    sigma and sit at axis positions 1 to 5. Between them the map is linear; beyond the
    outermost knots it continues at the slope of the nearest segment, so that a reading
    more extreme than anything in the record still lands somewhere -- inside the 0.6..5.4
    grid if it is within about 1.5 sigma, and clamped to the grid ends beyond that.
    """
    knots = list(PHASE_VALUES)
    if sigma <= knots[0]:
        span = knots[1] - knots[0]
        return max(state_axis()[0], 1.0 + (sigma - knots[0]) / span)
    if sigma >= knots[-1]:
        span = knots[-1] - knots[-2]
        return min(state_axis()[-1], 5.0 + (sigma - knots[-1]) / span)
    for i in range(len(knots) - 1):
        lo, hi = knots[i], knots[i + 1]
        if lo <= sigma <= hi:
            return (i + 1) + (sigma - lo) / (hi - lo)
    raise AssertionError("unreachable: sigma fell outside every phase segment")


def axis_to_state(axis_value: float) -> int:
    """The nearest state index (1-based) on the 25-point grid to an axis position."""
    grid = state_axis()
    best = min(range(STATE_COUNT), key=lambda i: abs(grid[i] - axis_value))
    return best + 1


@dataclass(frozen=True)
class StateMapEntry:
    signal_state: int      # 1..25 on the Market Risk Signal axis
    centile: float         # where that column sits in the signal's own record, 0..100
    cycle_value: float     # the ec_cycle sigma at the same centile
    axis_value: float      # position on the 1..5 phase axis
    calib_state: int       # nearest state on the calibration's 25-point grid


@dataclass(frozen=True)
class StateMap:
    """A versioned mapping from signal column to calibration axis."""

    method: str
    signal_first: str
    signal_last: str
    entries: tuple[StateMapEntry, ...]

    def axis_for(self, signal_state: int) -> float:
        return self.entries[signal_state - 1].axis_value

    def state_for(self, signal_state: int) -> int:
        return self.entries[signal_state - 1].calib_state

    def as_rows(self) -> list[dict[str, object]]:
        return [
            {
                "signal_state": e.signal_state,
                "centile": e.centile,
                "cycle_value": e.cycle_value,
                "axis_value": e.axis_value,
                "calib_state": e.calib_state,
            }
            for e in self.entries
        ]


def build_state_map(
    monthly_distributions: Sequence[Sequence[float]],
    cycle: Sequence[float],
    *,
    signal_first: str,
    signal_last: str,
) -> StateMap:
    """Build the bridge from the signal's history and the cycle's.

    ``monthly_distributions`` is one normalised 25-vector per month. The unconditional
    mass on each column is the average across months; a column's centile is the mass
    strictly below it plus half its own -- the midpoint convention, matching the
    ``nless + 0.5 * nequal`` device the calibration side uses.
    """
    if not monthly_distributions:
        raise ValueError("the state map needs at least one month of signal")
    months = len(monthly_distributions)
    for row in monthly_distributions:
        if len(row) != STATE_COUNT:
            raise ValueError(f"a signal month has {len(row)} states, expected {STATE_COUNT}")

    mass = [
        sum(row[i] for row in monthly_distributions) / months for i in range(STATE_COUNT)
    ]
    total = sum(mass)
    if total <= 0:
        raise ValueError("the signal carries no probability mass")
    mass = [m / total for m in mass]

    entries: list[StateMapEntry] = []
    cumulative = 0.0
    for i, m in enumerate(mass):
        centile = 100.0 * (cumulative + m / 2.0)
        cumulative += m
        sigma = num.percentile(cycle, centile)
        axis = cycle_sigma_to_axis(sigma)
        entries.append(
            StateMapEntry(
                signal_state=i + 1,
                centile=centile,
                cycle_value=sigma,
                axis_value=axis,
                calib_state=axis_to_state(axis),
            )
        )

    return StateMap(
        method=METHOD,
        signal_first=signal_first,
        signal_last=signal_last,
        entries=tuple(entries),
    )


def expected_return(profile_by_state: Sequence[float], distribution: Sequence[float],
                    state_map: StateMap) -> float:
    """Integrate a 25-state profile against one month's signal distribution.

    **This is a consumer convenience and is deliberately not part of the ReturnSet.**
    Manual section 11.1 refuses to emit a moment, because a moment is a summary over
    states and summarising over states destroys the information everything downstream runs
    on. The function lives here so the test bench can show what a month implies without
    that number ever entering the contract.
    """
    if len(distribution) != STATE_COUNT:
        raise ValueError(f"the distribution has {len(distribution)} states, expected {STATE_COUNT}")
    total = 0.0
    for signal_state, probability in enumerate(distribution, start=1):
        if probability == 0.0:
            continue
        axis = state_map.axis_for(signal_state)
        total += probability * num.pchip_eval(
            list(PHASE_KNOTS), _knots_from_profile(profile_by_state), [axis]
        )[0]
    return total


def _knots_from_profile(profile_by_state: Sequence[float]) -> list[float]:
    """Recover the five phase estimates from a 25-state profile.

    The profile was produced by interpolating five knots onto the grid, and the knots sit
    at grid indices 2, 7, 12, 17 and 22 (zero-based) -- the middle state of each phase
    band. Reading them back is exact, so integrating against a continuous axis position
    reuses the original estimates rather than re-interpolating an interpolation.
    """
    grid = state_axis()
    out: list[float] = []
    for knot in PHASE_KNOTS:
        index = next(i for i, q in enumerate(grid) if abs(q - knot) < 1e-12)
        out.append(profile_by_state[index])
    return out
