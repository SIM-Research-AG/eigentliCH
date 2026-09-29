"""The macro state as a 25-bin market risk signal, and its merge with the short-term TAA.

Phases 4 and 5 of docs/BATTLE_PLAN.md. This is the piece that connects the macrofield apparatus to the
operational allocation machinery:

    TAA (technical, monthly)  +  SAA (this module)  ->  market risk signal  ->  PCP

**The taxonomy is the book's five regimes, everywhere.** Settled by the author on 2026-07-28. The operational
`Scenario_SAA.m` spreads four weights (Boom, Recovery, Contraction, Bust) at bin offsets 1, 3, 10, 16; this
uses the five regimes of book section 20.2 at the placements in `regime.placement`. The four-scenario layout
is superseded, so scenario output will not reproduce that file bin for bin. What it does reproduce is the
file's *scenario definitions* and its *transformation mechanics*, and the four scenario vectors are
re-expressed in five-regime terms in `SCENARIOS` below.

**The tilts are a judgement call and are labelled as one.** Turning a macro state into regime weights is not
in the book. What the book supplies is which quantities matter: the phase, the saturation level against the
band, the real-to-financial ratio, the unsecured-asset gap, the cycle positions, and the interference
between the cycles. How much each should move the weights is a modelling choice with no source, so every
coefficient lives in `config/defaults.yaml` under `saa.tilts`, defaults to something defensible, and is
reported with the result rather than buried. It should be stress-tested, not trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from macrofield.control import Provenance, Segment, Traced
from macrofield.model.regime import (
    RegimeDistribution,
    RegimeError,
    RegimeKernels,
    SegmentAssessment,
    build_distribution,
)

#: The five regimes, in the cautious-to-aggressive order the axis already runs in.
REGIMES = ("crisis", "contraction", "stagnation", "expansion", "boom")

#: The four long-horizon scenarios of `Scenario_SAA.m`, re-expressed in five-regime weights.
#:
#: The source vectors are `[Boom, Recovery, Contraction, Bust]`. Bust maps to Crisis and Boom to Boom;
#: Contraction maps to Contraction; and **Recovery has no five-regime equivalent**, so it is split between
#: Stagnation and Expansion. MODEL_SPEC section 6 already settled why: "Recovery is a transition rather than
#: a regime and gives way to BOOK's Stagnation and Expansion." The split is 50:50 and is configuration.
#:
#: Worth seeing rather than skipping: **Hyperinflation maps entirely to Boom**, because the source vector is
#: in *nominal* terms and a hyperinflation is a nominal boom. That is faithful to the source and it is also
#: the nominal-against-real problem of item 5 surfacing in the signal layer. A portfolio positioned for Boom
#: in a hyperinflation is positioned wrongly in real terms.
SCENARIOS: dict[str, dict[str, float]] = {
    "depression": {"boom": 0.0, "recovery": 0.0, "contraction": 0.25, "bust": 0.75},
    "hyperinflation": {"boom": 1.0, "recovery": 0.0, "contraction": 0.0, "bust": 0.0},
    "stagflation": {"boom": 0.5, "recovery": 0.25, "contraction": 0.25, "bust": 0.0},
    "deferral": {"boom": 0.5, "recovery": 0.0, "contraction": 0.0, "bust": 0.5},
}


class SAASignalError(ValueError):
    """Raised when a signal cannot be produced."""


def scenario_weights(name: str, recovery_split: float = 0.5) -> dict[str, float]:
    """Re-express one of the four scenario vectors as five-regime weights.

    Args:
        name: A key of SCENARIOS.
        recovery_split: Share of the Recovery weight given to Stagnation, the remainder to Expansion.

    Returns:
        Weights over REGIMES, summing to one.

    Raises:
        SAASignalError: If the scenario is unknown or the split is outside the unit interval.
    """
    if name not in SCENARIOS:
        raise SAASignalError(
            f"unknown scenario {name!r}. Available: {', '.join(sorted(SCENARIOS))}"
        )
    if not 0.0 <= recovery_split <= 1.0:
        raise SAASignalError(f"recovery_split must lie in [0, 1], got {recovery_split}")

    source = SCENARIOS[name]
    recovery = float(source["recovery"])
    weights = {
        "crisis": float(source["bust"]),
        "contraction": float(source["contraction"]),
        "stagnation": recovery * recovery_split,
        "expansion": recovery * (1.0 - recovery_split),
        "boom": float(source["boom"]),
    }
    total = sum(weights.values())
    if total <= 0.0:
        raise SAASignalError(f"scenario {name!r} carries no weight")
    return {key: value / total for key, value in weights.items()}


@dataclass
class StateReading:
    """The macro quantities the tilts read, for one period.

    Gathered into one object so the translation has a single, inspectable input rather than a long argument
    list, and so a caller can see exactly what the signal was computed from.

    Attributes:
        period: The period.
        saturation: The credit saturation axis.
        band: The balanced band, lower and upper.
        real_to_financial: K_R over K_I.
        unsecured_change: Period-on-period change in the unsecured-asset gap, or None.
        interference: The cycle superposition total in [-1, 1], or None.
        alignment: The cycle alignment in [0, 1], or None.
        capital_years_overdue: Years past the capital-cycle reordering point, negative if short of it.
        innovation_years_to_trough: Years to the innovation low, negative if past it.
        provenance: What the reading is worth.
    """

    period: Any
    saturation: float
    band: tuple[float, float]
    real_to_financial: float
    unsecured_change: float | None = None
    interference: float | None = None
    alignment: float | None = None
    capital_years_overdue: float | None = None
    innovation_years_to_trough: float | None = None
    provenance: Provenance = Provenance.DERIVED


DEFAULT_TILTS: dict[str, float] = {
    #: Weight on the base prior, before any tilt. Higher makes the signal less responsive.
    "base": 1.0,
    #: Per unit of saturation above the band's upper bound, moved from the aggressive regimes to crisis.
    "saturation_above_band": 1.2,
    #: Per unit of saturation below the band's lower bound, moved the other way.
    "saturation_below_band": 0.8,
    #: Applied when K_R/K_I is below one, the Phase IV condition, scaled by how far below.
    "real_to_financial_below_one": 1.5,
    #: Per unit of period-on-period rise in the unsecured-asset gap.
    "unsecured_rising": 2.0,
    #: Per unit of the cycle superposition total. Negative interference moves weight to crisis.
    "interference": 1.0,
    #: Multiplies the interference tilt by the alignment, so aligned cycles count for more.
    "alignment_gain": 1.0,
    #: Per decade past the capital-cycle reordering point.
    "capital_overdue_per_decade": 0.8,
    #: Per decade to the innovation trough, moving weight to contraction as it approaches.
    "innovation_approach_per_decade": 0.4,
}


@dataclass
class SAASignal:
    """The macro signal for one period.

    Attributes:
        period: The period.
        weights: The five-regime weights the state implied.
        distribution: The 25-bin distribution those weights spread to.
        reading: What it was computed from.
        contributions: How much each tilt moved each regime, so the answer can be taken apart.
        provenance: What the signal is worth, inherited from the state it was read from.
        notes: Anything a reader must know.
    """

    period: Any
    weights: dict[str, float]
    distribution: RegimeDistribution
    reading: StateReading
    contributions: dict[str, dict[str, float]] = field(default_factory=dict)
    provenance: Provenance = Provenance.DERIVED
    notes: list[str] = field(default_factory=list)

    @property
    def probabilities(self) -> np.ndarray:
        return np.asarray(self.distribution.probabilities, dtype=float)

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "weights": dict(self.weights),
            "probabilities": [float(v) for v in self.probabilities],
            "five_regime": self.distribution.aggregate_five_regime(),
            "central_state": self.distribution.central_state,
            "modal_state": self.distribution.modal_state,
            "tail_probability": self.distribution.tail_probability,
            "contributions": {k: dict(v) for k, v in self.contributions.items()},
            "provenance": self.provenance.value,
            "notes": list(self.notes),
        }


def regime_weights_from_state(
    reading: StateReading,
    tilts: Mapping[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Turn a macro state into five-regime weights.

    Each tilt shifts weight between the cautious end (crisis, contraction) and the aggressive end
    (expansion, boom), leaving stagnation as the pivot. The construction is deliberately additive and
    inspectable: every tilt's contribution to every regime is returned, so a surprising signal can be taken
    apart rather than argued with.

    Args:
        reading: The state.
        tilts: Coefficients, defaulting to DEFAULT_TILTS.

    Returns:
        The weights, summing to one, and the per-tilt contributions.

    Raises:
        SAASignalError: If the band is degenerate or every weight is driven to zero.
    """
    coefficients = dict(DEFAULT_TILTS)
    coefficients.update({k: float(v) for k, v in (tilts or {}).items()})

    lower, upper = float(reading.band[0]), float(reading.band[1])
    if upper <= lower:
        raise SAASignalError(f"the balanced band {reading.band} does not increase")

    weights = {name: float(coefficients["base"]) for name in REGIMES}
    contributions: dict[str, dict[str, float]] = {}

    def apply(label: str, cautious: float, aggressive: float) -> None:
        """Move weight toward the cautious or the aggressive end.

        A positive `cautious` adds to crisis and contraction; a positive `aggressive` adds to expansion and
        boom. Contributions are recorded before clamping so the record is of what the tilt asked for.
        """
        moved = {
            "crisis": cautious,
            "contraction": cautious * 0.6,
            "stagnation": 0.0,
            "expansion": aggressive * 0.6,
            "boom": aggressive,
        }
        if any(abs(v) > 0.0 for v in moved.values()):
            contributions[label] = moved
            for name, value in moved.items():
                weights[name] += value

    # Saturation against the band. Above the upper bound is the framework's own saturation signal.
    if reading.saturation > upper:
        apply(
            "saturation_above_band",
            cautious=coefficients["saturation_above_band"] * (reading.saturation - upper),
            aggressive=0.0,
        )
    elif reading.saturation < lower:
        apply(
            "saturation_below_band",
            cautious=0.0,
            aggressive=coefficients["saturation_below_band"] * (lower - reading.saturation),
        )

    # The Phase IV condition. Real capital below financial capital is the condition that classifies an
    # economy as saturated and reordering, and it is invariant to every level adjustment.
    if reading.real_to_financial < 1.0:
        apply(
            "real_to_financial_below_one",
            cautious=coefficients["real_to_financial_below_one"] * (1.0 - reading.real_to_financial),
            aggressive=0.0,
        )

    # A widening unsecured-asset gap is claims growing faster than the output that services them.
    if reading.unsecured_change is not None and np.isfinite(reading.unsecured_change):
        if reading.unsecured_change > 0.0:
            apply("unsecured_rising", coefficients["unsecured_rising"] * reading.unsecured_change, 0.0)
        else:
            apply("unsecured_falling", 0.0, coefficients["unsecured_rising"] * -reading.unsecured_change)

    # Cycle interference, gained by how aligned the cycles are.
    if reading.interference is not None and np.isfinite(reading.interference):
        gain = 1.0
        if reading.alignment is not None and np.isfinite(reading.alignment):
            gain = 1.0 + coefficients["alignment_gain"] * (float(reading.alignment) - 0.5)
        magnitude = coefficients["interference"] * abs(float(reading.interference)) * max(gain, 0.0)
        if reading.interference < 0.0:
            apply("interference_negative", magnitude, 0.0)
        else:
            apply("interference_positive", 0.0, magnitude)

    # Past the reordering point, the framework's expectation is a release rather than a continuation.
    if reading.capital_years_overdue is not None and reading.capital_years_overdue > 0.0:
        apply(
            "capital_overdue",
            coefficients["capital_overdue_per_decade"] * reading.capital_years_overdue / 10.0,
            0.0,
        )

    # Approaching the innovation trough removes the competing real-asset opportunity.
    if reading.innovation_years_to_trough is not None:
        ahead = float(reading.innovation_years_to_trough)
        if 0.0 <= ahead <= 20.0:
            apply(
                "innovation_approaching_trough",
                coefficients["innovation_approach_per_decade"] * (20.0 - ahead) / 10.0,
                0.0,
            )

    clamped = {name: max(0.0, value) for name, value in weights.items()}
    total = sum(clamped.values())
    if total <= 0.0:
        raise SAASignalError(
            "every regime weight was driven to zero, so no distribution can be formed. The tilts are "
            "too strong for this state; raise saa.tilts.base or lower the tilts."
        )
    return {name: value / total for name, value in clamped.items()}, contributions


def signal_from_state(
    reading: StateReading,
    kernels: RegimeKernels | None = None,
    tilts: Mapping[str, float] | None = None,
    minimum_tail_probability: float = 0.01,
    tail_bins: int = 5,
) -> SAASignal:
    """Produce the 25-bin signal one macro state implies.

    The weights are spread onto the axis by the existing `regime.build_distribution`, so the kernels, the
    placements and the tail check are the ones already in config and already tested.
    """
    weights, contributions = regime_weights_from_state(reading, tilts)

    # `build_distribution` takes per-segment assessments and averages them. There is one assessment here,
    # the macro state's, so it is passed as a single segment named for what it is.
    assessment = SegmentAssessment(
        segment="macro_state",
        crisis=weights["crisis"],
        contraction=weights["contraction"],
        stagnation=weights["stagnation"],
        expansion=weights["expansion"],
        boom=weights["boom"],
    )
    try:
        distribution = build_distribution(
            [assessment],
            kernels=kernels,
            minimum_tail_probability=minimum_tail_probability,
            tail_bins=tail_bins,
        )
    except RegimeError as error:
        raise SAASignalError(f"the state's weights could not be spread onto the axis: {error}") from error

    notes = list(distribution.notes)
    notes.append(
        "the regime weights are a judgement call. The book supplies which quantities matter, not how much "
        "each should move the weights, so every coefficient is in saa.tilts and should be stress-tested "
        "rather than trusted. The per-tilt contributions are reported so the answer can be taken apart."
    )

    return SAASignal(
        period=reading.period,
        weights=weights,
        distribution=distribution,
        reading=reading,
        contributions=contributions,
        provenance=reading.provenance,
        notes=notes,
    )


@dataclass
class TiltSweep:
    """How much the signal depends on coefficients that have no source.

    Settled by the author on 2026-07-28: the tilts stay a judgement call and the **spread** is reported rather
    than one number from one chosen setting. This is the same discipline `data/adjustment.py` applies to the
    level adjustments, and for the same reason: replacing an unsourced number with another unsourced number
    and not saying so is worse than leaving it alone.

    Two readings, because they answer different questions:

    - `crisis_weight` and `mean_bin` give the range the whole signal moves over when every tilt is scaled
      together. That is the honest error bar on the level of the signal.
    - `per_tilt` gives how far the crisis weight moves when each tilt is scaled *alone*, which identifies
      which coefficient the answer actually rests on. A signal dominated by one unsourced tilt is a different
      situation from one where five share the load, and only this second reading distinguishes them.

    Attributes:
        scales: The multipliers applied.
        crisis_weight: The crisis weight at each scale.
        mean_bin: The distribution's mean bin at each scale.
        per_tilt: Tilt name to the crisis-weight range it alone produces.
        dominant: The tilt whose own variation moves the crisis weight furthest.
        notes: Anything a reader must know.
    """

    scales: list[float] = field(default_factory=list)
    crisis_weight: list[float] = field(default_factory=list)
    mean_bin: list[float] = field(default_factory=list)
    per_tilt: dict[str, dict[str, float]] = field(default_factory=dict)
    dominant: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def crisis_spread(self) -> float:
        """The width of the crisis weight over the sweep, which is the error bar to quote."""
        return (max(self.crisis_weight) - min(self.crisis_weight)) if self.crisis_weight else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scales": list(self.scales),
            "crisis_weight": list(self.crisis_weight),
            "mean_bin": list(self.mean_bin),
            "crisis_range": (
                [min(self.crisis_weight), max(self.crisis_weight)] if self.crisis_weight else None
            ),
            "crisis_spread": self.crisis_spread,
            "per_tilt": {k: dict(v) for k, v in self.per_tilt.items()},
            "dominant": self.dominant,
            "notes": list(self.notes),
        }


def sweep_tilts(
    reading: StateReading,
    tilts: Mapping[str, float] | None = None,
    scale_range: tuple[float, float] = (0.5, 1.5),
    steps: int = 5,
    kernels: RegimeKernels | None = None,
    minimum_tail_probability: float = 0.01,
    tail_bins: int = 5,
) -> TiltSweep:
    """Vary the tilts across a range and report the spread of the conclusion.

    `base` is deliberately **not** swept. It is the weight every regime starts with, so scaling it alongside
    the others would scale the numerator and the denominator together and understate the sensitivity: at a
    common scale of two, doubling every tilt *and* the base leaves the normalised weights almost unchanged,
    which would report a robustness the signal does not have.

    Args:
        reading: The state to sweep around.
        tilts: The coefficients, defaulting to DEFAULT_TILTS.
        scale_range: Multiplier range, matching `validation.sensitivity.range`.
        steps: How many points across it.
        kernels: The spreading kernels.
        minimum_tail_probability: Passed through.
        tail_bins: Passed through.

    Returns:
        The sweep.

    Raises:
        SAASignalError: If the range is not increasing or there are fewer than two steps.
    """
    from macrofield.data.taa import dispersion

    low, high = float(scale_range[0]), float(scale_range[1])
    if high <= low:
        raise SAASignalError(f"the scale range must increase, got {scale_range}")
    if int(steps) < 2:
        raise SAASignalError(f"a sweep needs at least two steps, got {steps}")

    coefficients = dict(DEFAULT_TILTS)
    coefficients.update({k: float(v) for k, v in (tilts or {}).items()})
    swept = [k for k in coefficients if k != "base"]

    def evaluate(candidate: Mapping[str, float]) -> tuple[float, float]:
        signal = signal_from_state(
            reading,
            kernels=kernels,
            tilts=candidate,
            minimum_tail_probability=minimum_tail_probability,
            tail_bins=tail_bins,
        )
        return float(signal.weights["crisis"]), float(dispersion(signal.probabilities)["mean_bin"])

    scales = [float(s) for s in np.linspace(low, high, int(steps))]
    crisis: list[float] = []
    mean_bin: list[float] = []
    for scale in scales:
        scaled = {k: (v * scale if k in swept else v) for k, v in coefficients.items()}
        c, m = evaluate(scaled)
        crisis.append(c)
        mean_bin.append(m)

    per_tilt: dict[str, dict[str, float]] = {}
    for name in swept:
        values = []
        for scale in (low, high):
            scaled = dict(coefficients)
            scaled[name] = coefficients[name] * scale
            values.append(evaluate(scaled)[0])
        per_tilt[name] = {
            "low": min(values),
            "high": max(values),
            "spread": abs(values[1] - values[0]),
        }

    dominant = max(per_tilt, key=lambda k: per_tilt[k]["spread"]) if per_tilt else None

    sweep = TiltSweep(
        scales=scales,
        crisis_weight=crisis,
        mean_bin=mean_bin,
        per_tilt=per_tilt,
        dominant=dominant,
    )
    sweep.notes = [
        f"the tilts have no source, so the spread is reported rather than one number. Scaled together across "
        f"{low:g} to {high:g}, the crisis weight runs {min(crisis):.3f} to {max(crisis):.3f}, a spread of "
        f"{sweep.crisis_spread:.3f}. Quote that range, not a point.",
        "the base weight is not swept: scaling it with the others would move the numerator and denominator "
        "together and report a robustness the signal does not have.",
    ]
    if dominant:
        sweep.notes.append(
            f"the answer rests most on {dominant.replace('_', ' ')}, which alone moves the crisis weight by "
            f"{per_tilt[dominant]['spread']:.3f} across the same range. That is the coefficient to justify "
            f"first if the signal is ever challenged."
        )
    return sweep


@dataclass
class MergedSignal:
    """The TAA and SAA combined, with the shape of the result measured.

    Attributes:
        periods: The periods.
        saa: The SAA distributions, rows by 25.
        taa: The TAA distributions, rows by 25.
        merged: The weighted combination, rows by 25.
        weight: The weight on the SAA.
        shapes: The dispersion summary per period.
        traces: Provenance per period, the weaker of the two inputs.
        notes: Anything a reader must know.
    """

    periods: np.ndarray
    saa: np.ndarray
    taa: np.ndarray
    merged: np.ndarray
    weight: float
    shapes: list[dict[str, Any]] = field(default_factory=list)
    traces: list[Traced] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "periods": [int(p) for p in self.periods],
            "weight_saa": self.weight,
            "weight_taa": 1.0 - self.weight,
            "saa": [[float(v) for v in row] for row in self.saa],
            "taa": [[float(v) for v in row] for row in self.taa],
            "merged": [[float(v) for v in row] for row in self.merged],
            "shapes": list(self.shapes),
            "provenance": [t.provenance.value for t in self.traces],
            "latest": {
                "period": int(self.periods[-1]),
                "merged": [float(v) for v in self.merged[-1]],
                "shape": self.shapes[-1] if self.shapes else None,
            },
            "notes": list(self.notes),
        }


def merge(
    periods: Sequence[Any],
    saa: np.ndarray,
    taa: np.ndarray,
    weight: float = 0.5,
    saa_provenance: Sequence[Provenance] | None = None,
    taa_provenance: Sequence[Provenance] | None = None,
    config=None,
    cycles: np.ndarray | None = None,
    cycles_weight: float = 0.0,
) -> MergedSignal:
    """Combine the signals in bin space.

    **In bin space, not regime space**, and deliberately. Bins carry no vocabulary, so the question of which
    regime taxonomy each side used does not propagate into the merge or onward to the PCP.

    **A bimodal result is a finding, not an artefact.** Settled by the author on 2026-07-28. Mixing two
    unimodal distributions at different locations produces a bimodal one, which the Master Deck reads as a
    swing market, where participants disagree about direction. TAA and SAA disagreeing genuinely *is*
    dispersion of view, so the shape is measured and reported rather than smoothed away by blending in
    stance space.

    Args:
        periods: The periods, one per row.
        saa: The macro signal, rows by 25.
        taa: The technical signal, rows by 25.
        weight: Weight on the SAA against the TAA. The board's default is 0.5.
        saa_provenance: Per period, what the SAA row is worth.
        taa_provenance: Per period, what the TAA row is worth.
        config: A loaded Config, for the shape thresholds.
        cycles: The cycle layer, rows by 25, or None. See `macrofield.model.cycle_bins`.
        cycles_weight: How much of the final distribution the cycle layer contributes.

    Returns:
        The merged signal.

    Raises:
        SAASignalError: If the shapes disagree or either weight is outside the unit interval.

    **The cycle layer enters as an outer mixture, not as a third term in the inner one.** The composition is

        final = (1 - w_cycles) * [w_saa * SAA + (1 - w_saa) * TAA] + w_cycles * CYCLES

    which keeps `weight` meaning exactly what it meant before — macro against technical — and makes
    `cycles_weight` read as "how much of the final view the cycle layer contributes". Folding all three into
    one three-way weight would have silently changed the meaning of an existing configured number, and
    `saa.blend_weight` is quoted on boards and in change reports.

    Linear, like the two-way blend and for the same reason: live crisis-tail weight is a requirement of this
    engine rather than an outcome, and a multiplicative pool lets one contributor's near-zero annihilate a tail
    another keeps alive.
    """
    from macrofield.data.taa import dispersion

    if not 0.0 <= weight <= 1.0:
        raise SAASignalError(f"the SAA weight must lie in [0, 1], got {weight}")
    if not 0.0 <= cycles_weight <= 1.0:
        raise SAASignalError(f"the cycle weight must lie in [0, 1], got {cycles_weight}")
    if cycles_weight > 0.0 and cycles is None:
        raise SAASignalError(
            f"a cycle weight of {cycles_weight} was given with no cycle layer to apply it to. Refusing "
            f"rather than silently ignoring the weight: a configured contribution that does not arrive is "
            f"the kind of thing nobody notices."
        )

    saa_array = np.atleast_2d(np.asarray(saa, dtype=float))
    taa_array = np.atleast_2d(np.asarray(taa, dtype=float))
    period_array = np.asarray(list(periods))

    if saa_array.shape != taa_array.shape:
        raise SAASignalError(
            f"the two signals must share a shape, got {saa_array.shape} and {taa_array.shape}"
        )
    if saa_array.shape[0] != period_array.size:
        raise SAASignalError(
            f"{saa_array.shape[0]} signal rows against {period_array.size} periods"
        )

    combined = weight * saa_array + (1.0 - weight) * taa_array

    if cycles is not None and cycles_weight > 0.0:
        cycle_array = np.atleast_2d(np.asarray(cycles, dtype=float))
        if cycle_array.shape != saa_array.shape:
            raise SAASignalError(
                f"the cycle layer must share the signals' shape, got {cycle_array.shape} against "
                f"{saa_array.shape}"
            )
        # Normalise each cycle row before mixing, so a row that does not sum to one cannot change the
        # effective weight. The inner blend is already normalised below, but doing it here as well means the
        # stated weight is the weight applied.
        cycle_totals = cycle_array.sum(axis=1, keepdims=True)
        cycle_array = np.divide(
            cycle_array, cycle_totals, out=np.zeros_like(cycle_array), where=cycle_totals > 0.0
        )
        inner_totals = combined.sum(axis=1, keepdims=True)
        inner = np.divide(combined, inner_totals, out=np.zeros_like(combined), where=inner_totals > 0.0)
        combined = (1.0 - cycles_weight) * inner + cycles_weight * cycle_array

    totals = combined.sum(axis=1, keepdims=True)
    combined = np.divide(combined, totals, out=np.zeros_like(combined), where=totals > 0.0)

    shapes = [dispersion(row, config=config) for row in combined]

    traces: list[Traced] = []
    for index in range(period_array.size):
        parts = []
        if saa_provenance is not None:
            parts.append(saa_provenance[index])
        if taa_provenance is not None:
            parts.append(taa_provenance[index])
        provenance = Provenance.weakest_of(parts) if parts else Provenance.DERIVED
        traces.append(
            Traced(
                values=combined[index],
                segments=[
                    Segment(
                        0,
                        combined.shape[1] - 1,
                        provenance,
                        f"{weight:.0%} macro, {1 - weight:.0%} technical",
                    )
                ],
            )
        )

    notes = [
        f"merged in bin space at {weight:.0%} macro to {1 - weight:.0%} technical. Bins carry no "
        f"vocabulary, so the regime taxonomy each side used does not propagate downstream.",
        "a bimodal result is reported as a swing market rather than smoothed away. Two horizons "
        "disagreeing is dispersion of view, which is what that shape means.",
    ]
    swings = [int(p) for p, s in zip(period_array, shapes) if s["modes"] > 1]
    if swings:
        notes.append(
            f"the merged signal is multi-modal in {len(swings)} of {period_array.size} periods, first at "
            f"{swings[0]}. Where that is driven by the two horizons disagreeing rather than by either one, "
            f"it is the merge reporting genuine disagreement."
        )

    return MergedSignal(
        periods=period_array,
        saa=saa_array,
        taa=taa_array,
        merged=combined,
        weight=float(weight),
        shapes=shapes,
        traces=traces,
        notes=notes,
    )
