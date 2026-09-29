"""The 25-state regime layer that feeds the Optimizer.

Brief section 0.8. The object is a distribution over 25 states, not a point estimate. A central
estimate is built from leading, current and lagging indicators across four segments (the business
cycle, the investment environment, market behaviour, and market stress), and each segment's
assessment is spread across the 25 states with an explicit probability weighting that deliberately
carries weight on the tail so the crisis regime always has a live probability.

The output shape matches the live interface the Portfolio Creation Program consumes
(SIM_Tech/Master_Controller/convictions.json holds 25-length distributions per economy).

**Five scenarios.** Each segment supplies a probability vector over the five regimes of book section
20.2: Crisis, Contraction, Stagnation, Expansion, Boom. They are declared in that order, which is
already the cautious-to-aggressive order of the axis, so the reversal step the earlier version needed
is gone.

This supersedes a four-scenario version taken from `Team_TAA_Risk_Signal.m`, which used
[boom, recovery, contraction, bust]. That vocabulary never lined up with the book's taxonomy, which
forced the five-regime output to be produced by aggregating bins rather than by naming what the
segments had actually assessed. Five scenarios unify the two: the segment assessment and the regime
report now speak the same language, and "recovery" (which is a transition rather than a regime) drops
out in favour of "stagnation" and "expansion", which the book defines as distinct regimes.

The axis runs 1 cautious to 25 aggressive, and each scenario's weight is spread over a contiguous run
of bins by a kernel:

    crisis       10-bin kernel piled towards the cautious end,  at bins  1 to 10
    contraction  14-bin symmetric kernel,                       at bins  2 to 15
    stagnation   14-bin symmetric kernel,                       at bins  6 to 19
    expansion    14-bin symmetric kernel,                       at bins 11 to 24
    boom         10-bin kernel, the reverse of the crisis one,   at bins 16 to 25

The placements space the five kernel centres roughly evenly across the axis while keeping the two
extreme scenarios asymmetric and piled towards their own ends. The asymmetry of the crisis kernel is
what keeps live weight on the tail, as the brief requires. Kernels and placements are config, not
constants in code.

On the seventeen-state extension of book section 20.3: it is deliberately not derived from these bins,
because it distinguishes variants the axis does not carry (it separates, for example, an asset-price
boom without productive support from a credit-driven boom, which is a qualitative distinction rather
than a position on a cautious-to-aggressive scale). Deriving it from the 25 bins would be invention,
so it is left unimplemented rather than approximated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

#: Number of states on the axis.STATE_COUNT is fixed by the downstream interface.
STATE_COUNT = 25

#: The five regimes of book section 20.2, in cautious-to-aggressive order, which is already the order
#: of the axis. No reversal is applied anywhere.
SCENARIO_ORDER = ("crisis", "contraction", "stagnation", "expansion", "boom")

#: Scenarios whose kernel is piled towards its own end of the axis rather than symmetric.
EXTREME_SCENARIOS = {"crisis": "low", "boom": "high"}

#: The 14-bin central kernel, as percentages, verbatim from the operational implementation.
#:
#: Two properties of these source values are worth knowing, and both are left uncorrected here so
#: that this module reproduces the intended construction rather than a guess at it. Kernels are
#: normalised before use, so neither affects the distribution summing to one.
#:
#: 1. It sums to 99.0, not 100.0.
#: 2. It is very nearly symmetric but not quite: every mirror pair matches except one, which carries
#:    13.0 against 12.0.
#:
#: These look like a single typo rather than two independent quirks. Replacing the 12.0 with 13.0
#: makes the kernel exactly symmetric and makes it sum to exactly 100.0, and the same substitution
#: is consistent with how BUST_KERNEL is built from this one (see below).
#:
#: The substitution WAS adopted on the author's decision, 2026-08-02 (DECISIONS.md M56), and shipped
#: config now carries the corrected sequence at `regime.kernels.symmetric`. This constant deliberately
#: keeps the uncorrected original so the two can be compared, which means it is the value a run gets
#: only when it bypasses config entirely. Do not read it as what the model uses.
SYMMETRIC_KERNEL = (
    1.5, 2.0, 4.9, 6.0, 8.9, 13.0, 13.7, 13.7, 12.0, 8.9, 6.0, 4.9, 2.0, 1.5,
)

#: The 10-bin kernel piled towards the cautious end, as percentages, verbatim from the operational
#: implementation. It is SYMMETRIC_KERNEL with its left tail folded into the first two bins: the
#: first two entries here, 14.4 and 21.9, sum to 36.3, which is exactly the sum of the first six
#: entries of SYMMETRIC_KERNEL. That is what puts the extra weight on the crisis tail. It also sums
#: to 99.0, for the same reason as above.
#:
#: Named for the crisis scenario it now serves. The operational source called it Binom_Bust, from the
#: four-scenario vocabulary this module no longer uses.
#:
#: **The 12.0 at position 5 is the same transcription error as SYMMETRIC_KERNEL's, and was corrected on the
#: author's decision, 3 August 2026.** M56 corrected the symmetric kernel on 2 August and left this one
#: unruled-on, which was an inconsistency rather than a distinction: this kernel is *folded from* the symmetric
#: one, carries the identical 12.0, and sums to the identical 99.0. The argument that stopped the correction
#: transferring automatically was that folding a tail into two bins can legitimately break symmetry — true, and
#: it is why this needed a decision rather than an inference. But the shared 12.0 is either a transcription
#: error in both places or in neither, and only one had been ruled on.
#:
#: This constant keeps the uncorrected original; `CRISIS_KERNEL_CORRECTED` below is what shipped config carries,
#: exactly as with the symmetric pair. So this is the value a run gets only when it bypasses config entirely.
#: Do not read it as what the model uses.
CRISIS_KERNEL = (14.4, 21.9, 13.7, 13.7, 12.0, 8.9, 6.0, 4.9, 2.0, 1.5)

#: The crisis correction: 12.0 -> 13.0 at position 5, which takes the sum from 99.0 to exactly 100.0 — the same
#: two-quirks-one-substitution signature that identified the symmetric kernel's error. Adopted 3 August 2026;
#: shipped config carries this sequence, so this is what a config-driven run actually uses.
#:
#: **This changes the published Regime and therefore `regime_id`**, because the distributions are hashed. All
#: ten files in `output/regime/` need republishing, the ReturnSet needs rebuilding so `require_regime_match`
#: does not refuse the pair, and `tests/golden/shared_path_Global_1y.json` needs re-recording.
CRISIS_KERNEL_CORRECTED = (14.4, 21.9, 13.7, 13.7, 13.0, 8.9, 6.0, 4.9, 2.0, 1.5)

#: The symmetric correction described on SYMMETRIC_KERNEL. Adopted 2026-08-02 (M56): shipped config
#: carries this sequence, so this is what a config-driven run actually uses.
SYMMETRIC_KERNEL_CORRECTED = (
    1.5, 2.0, 4.9, 6.0, 8.9, 13.0, 13.7, 13.7, 13.0, 8.9, 6.0, 4.9, 2.0, 1.5,
)

#: One-based inclusive start bin for each scenario's kernel. Chosen so the five kernel centres are
#: roughly evenly spaced across the 25-bin axis: the crisis and boom kernels are piled at their own
#: ends, and the three symmetric kernels sit at centres near bins 8.5, 12.5 and 17.5.
DEFAULT_PLACEMENT = {
    "crisis": 1,
    "contraction": 2,
    "stagnation": 6,
    "expansion": 11,
    "boom": 16,
}

#: The four segments the brief names.
DEFAULT_SEGMENTS = (
    "business_cycle",
    "investment_environment",
    "market_behaviour",
    "market_stress",
)

#: Default aggregation of the 25 bins onto the book's five-regime taxonomy, five bins each.
FIVE_REGIME_BINS = {
    "Crisis": range(1, 6),
    "Contraction": range(6, 11),
    "Stagnation": range(11, 16),
    "Expansion": range(16, 21),
    "Boom": range(21, 26),
}


class RegimeError(ValueError):
    """Raised when a regime input is unusable."""


def _normalised_kernel(values: Sequence[float]) -> np.ndarray:
    """Return a kernel as probabilities summing to one."""
    kernel = np.asarray(values, dtype=float)
    if kernel.ndim != 1 or kernel.size == 0:
        raise RegimeError("a kernel must be a non-empty one-dimensional sequence")
    if np.any(kernel < 0.0):
        raise RegimeError("a kernel cannot carry negative weight")
    total = kernel.sum()
    if total <= 0.0:
        raise RegimeError("a kernel must carry positive weight")
    return kernel / total


@dataclass
class SegmentAssessment:
    """One segment's probability vector over the five regimes.

    Attributes:
        segment: The segment name.
        crisis: Probability of the Crisis regime.
        contraction: Probability of the Contraction regime.
        stagnation: Probability of the Stagnation regime.
        expansion: Probability of the Expansion regime.
        boom: Probability of the Boom regime.
    """

    segment: str
    crisis: float
    contraction: float
    stagnation: float
    expansion: float
    boom: float

    def as_vector(self) -> np.ndarray:
        """Return the assessment in SCENARIO_ORDER, which is cautious to aggressive."""
        return np.array(
            [self.crisis, self.contraction, self.stagnation, self.expansion, self.boom],
            dtype=float,
        )

    def validate(self, tolerance: float = 1e-6) -> None:
        """Check the assessment is a probability vector.

        Raises:
            RegimeError: If any entry is negative or the vector does not sum to one.
        """
        vector = self.as_vector()
        if np.any(vector < 0.0):
            raise RegimeError(
                f"segment {self.segment!r} carries negative probability: {vector.tolist()}"
            )
        total = float(vector.sum())
        if abs(total - 1.0) > tolerance:
            raise RegimeError(
                f"segment {self.segment!r} probabilities sum to {total:.6f}, not one. An assessment "
                f"must be a probability vector over the {len(SCENARIO_ORDER)} scenarios "
                f"({', '.join(SCENARIO_ORDER)})."
            )

    @classmethod
    def from_mapping(cls, segment: str, values: Mapping[str, float]) -> "SegmentAssessment":
        """Build from a mapping keyed by scenario name."""
        missing = [s for s in SCENARIO_ORDER if s not in values]
        if missing:
            raise RegimeError(f"segment {segment!r} is missing scenarios: {', '.join(missing)}")
        return cls(
            segment=segment,
            crisis=float(values["crisis"]),
            contraction=float(values["contraction"]),
            stagnation=float(values["stagnation"]),
            expansion=float(values["expansion"]),
            boom=float(values["boom"]),
        )


@dataclass
class RegimeKernels:
    """The spreading kernels and their placement on the axis."""

    symmetric: tuple[float, ...] = SYMMETRIC_KERNEL
    crisis: tuple[float, ...] = CRISIS_KERNEL
    placement: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_PLACEMENT))
    state_count: int = STATE_COUNT

    def kernel_for(self, scenario: str) -> np.ndarray:
        """Return the normalised kernel for a scenario.

        The two extreme regimes use the asymmetric kernel, piled towards their own end of the axis.
        The three interior regimes use the symmetric one.
        """
        if scenario not in SCENARIO_ORDER:
            raise RegimeError(
                f"unknown scenario {scenario!r}, expected one of {SCENARIO_ORDER}"
            )
        end = EXTREME_SCENARIOS.get(scenario)
        if end == "low":
            return _normalised_kernel(self.crisis)
        if end == "high":
            return _normalised_kernel(tuple(reversed(self.crisis)))
        return _normalised_kernel(self.symmetric)

    def spread(self, scenario: str, weight: float) -> np.ndarray:
        """Spread a scenario's weight across the axis.

        Raises:
            RegimeError: If the kernel would extend past the end of the axis, which would silently
                discard probability.
        """
        kernel = self.kernel_for(scenario)
        start = int(self.placement[scenario])
        if start < 1:
            raise RegimeError(f"placement for {scenario!r} must be a one-based bin, got {start}")
        end = start + kernel.size - 1
        if end > self.state_count:
            raise RegimeError(
                f"the {scenario!r} kernel of {kernel.size} bins placed at bin {start} would end at "
                f"bin {end}, past the {self.state_count}-bin axis, which would discard probability"
            )
        distribution = np.zeros(self.state_count, dtype=float)
        distribution[start - 1 : end] = kernel * float(weight)
        return distribution

    @classmethod
    def from_config(cls, config) -> "RegimeKernels":
        """Build from a loaded Config."""
        return cls(
            symmetric=tuple(config.get("regime.kernels.symmetric")),
            crisis=tuple(config.get("regime.kernels.crisis")),
            placement=dict(config.get("regime.placement")),
            state_count=int(config.get("regime.states")),
        )


@dataclass
class RegimeDistribution:
    """A distribution over the 25 states.

    Attributes:
        probabilities: The distribution, index 0 being state 1 (most cautious).
        segments: The segment assessments that produced it.
        tail_probability: Probability mass on the crisis tail.
        tail_bins: How many bins the tail comprises.
        central_state: The probability-weighted mean state, a one-based position on the axis.
        modal_state: The one-based state carrying the most probability.
        notes: Anything a consumer must know.
    """

    probabilities: np.ndarray
    segments: list[SegmentAssessment] = field(default_factory=list)
    tail_probability: float = 0.0
    tail_bins: int = 5
    central_state: float = 0.0
    modal_state: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def states(self) -> np.ndarray:
        """One-based state labels."""
        return np.arange(1, self.probabilities.size + 1)

    def aggregate_five_regime(
        self, bins: Mapping[str, range] | None = None
    ) -> dict[str, float]:
        """Aggregate onto the book's five-regime taxonomy.

        The bins are config, and the default splits the axis into five equal groups. This is an
        aggregation of the cautious-to-aggressive axis, not an independent classification.
        """
        mapping = bins or FIVE_REGIME_BINS
        covered: set[int] = set()
        result: dict[str, float] = {}
        for regime, span in mapping.items():
            indices = [state - 1 for state in span]
            overlap = covered.intersection(indices)
            if overlap:
                raise RegimeError(
                    f"regime {regime!r} overlaps bins already assigned: "
                    f"{sorted(state + 1 for state in overlap)}"
                )
            covered.update(indices)
            result[regime] = float(self.probabilities[indices].sum())
        if len(covered) != self.probabilities.size:
            unassigned = sorted(
                state + 1 for state in range(self.probabilities.size) if state not in covered
            )
            raise RegimeError(
                f"the five-regime aggregation leaves states {unassigned} unassigned, so the "
                f"aggregated probabilities would not sum to one"
            )
        return result

    def as_list(self) -> list[float]:
        """Return the distribution as a plain list, the shape the Optimizer consumes."""
        return [float(p) for p in self.probabilities]


def build_distribution(
    segments: Sequence[SegmentAssessment],
    kernels: RegimeKernels | None = None,
    minimum_tail_probability: float = 0.01,
    tail_bins: int = 5,
    validate_segments: bool = True,
) -> RegimeDistribution:
    """Build the 25-state distribution from the segment assessments.

    Each segment's five scenario weights are spread by the kernels and the segments are averaged
    equally.

    Args:
        segments: The segment assessments. The brief names four segments; the count is not fixed.
        kernels: The spreading kernels and placement.
        minimum_tail_probability: The floor the crisis tail is checked against. A breach is reported
            in the notes rather than corrected by reweighting, because silently moving probability
            onto the tail would misrepresent the segments' assessments.
        tail_bins: How many of the most cautious bins constitute the tail.
        validate_segments: Whether to require each assessment to be a probability vector.

    Returns:
        The distribution.

    Raises:
        RegimeError: If no segments are supplied, or a segment is not a probability vector.
    """
    if not segments:
        raise RegimeError("at least one segment assessment is required")

    spreader = kernels or RegimeKernels()
    total = np.zeros(spreader.state_count, dtype=float)

    for assessment in segments:
        if validate_segments:
            assessment.validate()
        vector = assessment.as_vector()
        for scenario, weight in zip(SCENARIO_ORDER, vector):
            total += spreader.spread(scenario, float(weight))

    probabilities = total / len(segments)

    notes: list[str] = []
    mass = float(probabilities.sum())
    if abs(mass - 1.0) > 1e-6:
        notes.append(
            f"the distribution sums to {mass:.6f} rather than one, which indicates a kernel or "
            f"placement problem"
        )

    tail = float(probabilities[:tail_bins].sum())
    if tail < minimum_tail_probability:
        notes.append(
            f"the crisis tail carries {tail:.4f} across the {tail_bins} most cautious states, below "
            f"the floor of {minimum_tail_probability:.4f}. The brief requires the crisis regime to "
            f"retain a live probability, so this reading should be reviewed. No reweighting has been "
            f"applied, because that would misstate the segment assessments."
        )

    states = np.arange(1, probabilities.size + 1)
    central = float((probabilities * states).sum()) if mass > 0.0 else 0.0

    return RegimeDistribution(
        probabilities=probabilities,
        segments=list(segments),
        tail_probability=tail,
        tail_bins=tail_bins,
        central_state=central,
        modal_state=int(states[int(np.argmax(probabilities))]),
        notes=notes,
    )


@dataclass
class OptimizerPayload:
    """The interface the Portfolio Creation Program consumes.

    Shaped to match the live `convictions.json`: a 25-length distribution per economy. Carrying the
    metadata alongside means a consumer can tell which construction produced it, which matters while
    two constructions exist (this one and the operational MATLAB, which differ by the Recovery-weight
    correction).
    """

    economy: str
    period: object
    distribution: list[float]
    central_state: float
    modal_state: int
    tail_probability: float
    five_regime: dict[str, float]
    construction: str = "macrofield.model.regime, five regimes per book section 20.2"
    notes: list[str] = field(default_factory=list)


def to_optimizer_payload(
    economy: str,
    period: object,
    distribution: RegimeDistribution,
    five_regime_bins: Mapping[str, range] | None = None,
) -> OptimizerPayload:
    """Package a distribution for the downstream optimiser."""
    return OptimizerPayload(
        economy=economy,
        period=period,
        distribution=distribution.as_list(),
        central_state=distribution.central_state,
        modal_state=distribution.modal_state,
        tail_probability=distribution.tail_probability,
        five_regime=distribution.aggregate_five_regime(five_regime_bins),
        notes=list(distribution.notes),
    )
