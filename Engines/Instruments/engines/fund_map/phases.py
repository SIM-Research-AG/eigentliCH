"""The five market phases, and the bounds that cut the cycle into them.

A port of the classifier at the foot of ``2_market.mlx``. The bounds are stated in
standard deviations of the economic cycle and they are not symmetric in the way one might
expect -- boom opens at ``>= +1.00`` while crisis opens at ``<= -1.00``, and stagnation
owns the closed interval ``[-0.20, +0.20]``. The inequalities below are transcribed
exactly, because a boundary year moving from one phase to another moves it between two
estimation buckets and changes both.

**Why these numbers.** ``2_market.mlx`` derives them from the cycle's own tail frequency:
``occ = n / (1 - erf(S / sqrt(2)))`` is how long it takes for ``n`` events beyond ``S``
sigma to occur, and 1.65 sigma is the level at which the leverage cycle shows up in the
150-year record. The business-cycle bound sits at 1 sigma and the recession bound at 0.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: Phase boundaries in sigma of the economic cycle, from ``2_market.mlx``.
BOUND_INNOVATION = 1.65  # the leverage/innovation threshold; sets the phase *values*
BOUND_BUSINESS = 1.00    # boom opens here, crisis opens at its negative
BOUND_RECESSION = 0.20   # the stagnation band is the interval inside this

#: The ordered phase names, worst to best. Index 0 is crisis.
PHASE_NAMES: tuple[str, ...] = ("crisis", "contraction", "stagnation", "expansion", "boom")

#: The representative cycle value the reference implementation assigns to each phase.
#: These are the midpoints between the bounds -- crisis and boom take the midpoint of the
#: business and innovation bounds, contraction and expansion the midpoint of the recession
#: and business bounds, stagnation zero. They are what ``hist(phase, unique(phase))``
#: buckets on, and they appear in the published workbook as the row labels
#: ``-1.325 / -0.6 / 0 / 0.6 / 1.325``.
PHASE_VALUES: tuple[float, ...] = (
    -(BOUND_INNOVATION + BOUND_BUSINESS) / 2.0,   # -1.325  crisis
    -(BOUND_RECESSION + BOUND_BUSINESS) / 2.0,    # -0.600  contraction
    0.0,                                          #  0.000  stagnation
    +(BOUND_RECESSION + BOUND_BUSINESS) / 2.0,    # +0.600  expansion
    +(BOUND_INNOVATION + BOUND_BUSINESS) / 2.0,   # +1.325  boom
)


def classify(cycle_value: float) -> int:
    """Return the phase index ``0..4`` for one economic-cycle reading, in sigma.

    The inequalities mirror ``2_market.mlx`` exactly, including the asymmetry: boom and
    crisis are closed at the business-cycle bound, expansion and contraction are open at
    both of theirs, and everything left over is stagnation.
    """
    if cycle_value >= BOUND_BUSINESS:
        return 4
    if cycle_value <= -BOUND_BUSINESS:
        return 0
    if BOUND_RECESSION < cycle_value < BOUND_BUSINESS:
        return 3
    if -BOUND_BUSINESS < cycle_value < -BOUND_RECESSION:
        return 1
    return 2


def classify_series(cycle: Sequence[float]) -> list[int]:
    """Classify a whole cycle series into phase indices."""
    return [classify(v) for v in cycle]


@dataclass(frozen=True)
class PhaseTimeline:
    """A run of years with the phase each one was in."""

    first_year: int
    phases: tuple[int, ...]

    @property
    def last_year(self) -> int:
        return self.first_year + len(self.phases) - 1

    def years(self) -> list[int]:
        return list(range(self.first_year, self.last_year + 1))

    def slice_years(self, first: int, last: int) -> list[int]:
        """The phase indices covering ``first..last``, for aligning a truncated block.

        Three of the eight return blocks are shorter than the state timeline. Truncation
        is handled by matching only where the series exists -- never by back-filling --
        so a block asks for the window it actually covers and gets exactly that.
        """
        if first < self.first_year or last > self.last_year:
            raise KeyError(
                f"the phase timeline covers {self.first_year}..{self.last_year}; "
                f"{first}..{last} was asked for"
            )
        lo = first - self.first_year
        hi = last - self.first_year + 1
        return list(self.phases[lo:hi])

    def counts(self) -> dict[str, int]:
        """How many years each phase holds. The acceptance tests read this."""
        return {name: self.phases.count(i) for i, name in enumerate(PHASE_NAMES)}

    def transition_matrix(self) -> list[list[float]]:
        """Year-on-year phase transition probabilities, row-normalised.

        Not used by the ReturnSet, which is conditional on a state rather than on a path.
        It is carried because ``3_returns.mlx`` computes it and the published workbook
        records it, so it is available as a cross-check against the reference.
        """
        counts = [[0 for _ in PHASE_NAMES] for _ in PHASE_NAMES]
        for a, b in zip(self.phases, self.phases[1:]):
            counts[a][b] += 1
        matrix: list[list[float]] = []
        for row in counts:
            total = sum(row)
            matrix.append([c / total if total else 0.0 for c in row])
        return matrix
