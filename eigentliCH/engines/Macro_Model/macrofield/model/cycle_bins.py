"""The cycle layer: each cycle's position as a distribution on the 25-bin axis, superposed.

Directed by the author on 2026-08-02, replacing an earlier intention to implement book section 20.3's
seventeen-state taxonomy. That taxonomy needed a qualitative distinction the cautious-to-aggressive axis does
not carry, so deriving it from the bins would have been invention and it was left unbuilt (`regime.py`). This
does something better and simpler: it puts the **cycles themselves** into the same 25-bin space the market risk
signal already lives in, so they can be combined as distributions rather than needing a parallel vocabulary.

## The mapping

Each cycle carries a phase, and its level is ``u = cos(phase)`` in [-1, +1]. **Taken from the phase, never
from the component.** `extract_cycle` builds the analytic signal ``z = A*exp(i*phi)``, so the component is
``A*cos(phi)``: for an anchored cycle the amplitude is one by construction and the two agree, but for a
band-passed cycle the amplitude is whatever the data carries — log-output growth deviations of order 0.01 —
and using the component would pin every measured cycle to the middle of the axis whatever its actual position.
This is the same normalisation `cycles.superpose` applies before summing, and for the same reason.

## Orientation: a peak in a cycle's own variable is not always the aggressive end

`cycles.py` defines every phase **in the cycle's own variable** — "two cycles count as in phase when both are
peaking in their own variable". That is the right convention for synchrony, and it does *not* transfer to a
cautious-to-aggressive axis without a per-cycle statement of which way round the variable runs.

For the growth-based cycles it happens to line up: a peak in band-passed log-output growth is an aggressive
condition. For the **capital** cycle it is exactly backwards. Its phase 0 is the credit-to-GDP crossing at 3.5,
which is where *saturation peaks* — maximum fragility, the point at which the reordering occurs. Mapping that
to bin 25 said the economy was at its most risk-tolerant precisely when it was at its most saturated.

So each cycle carries an **orientation** in config: ``+1`` when a peak in its own variable belongs at the
aggressive end, ``-1`` when it belongs at the cautious end. The level becomes ``u = orientation * cos(phase)``.
Corrected for the capital cycle on the author's instruction, 2026-08-02, after the printed distributions put it
at bin 21.9 while the economy was reading near-crisis. Nothing in the phase machinery changed; only the
statement of which end of the risk axis its peak means.

Onto the axis, whose bin 1 is cautious and bin 25 aggressive:

    centre = 1 + (n - 1) * (u + 1) / 2          which for n = 25 is  13 + 12u

so a trough lands on bin 1, a mid-cycle level on bin 13 and a peak on bin 25. The mapping is through the
*level* rather than the phase, because the axis means risk stance and a cycle's stance is its level. Mapping
phase linearly would sweep the axis once per cycle and put the trough at both ends, which the axis does not
mean.

## The width, which is the honest part

A cycle's position is not a point and must not be drawn as one. The width of each cycle's kernel comes from
**what its position is worth**, using signals the engine already tracks rather than a number per cycle:

- **Measured.** An estimated, identifiable cycle. Width scales as ``1 / sqrt(periods in sample)``, the ordinary
  standard-error scaling, clamped. A cycle observed over thirty of its periods speaks more precisely than one
  observed over three.
- **Supplied.** An anchored cycle whose anchor was observed — innovation, capital at a real crossing, hegemonic.
  Wide, and deliberately: the anchor says *where* in the cycle we are and is a structural assumption, not a
  measurement. A supplied anchor must not be able to speak as confidently as a measured cycle.
- **Assumed.** An anchored cycle whose anchor was projected forward from a trend rather than observed. Widest,
  matching the ``Provenance.ASSUMED`` it already carries.
- **Marginal.** A cycle whose period is too few sampling intervals to band-pass cleanly. Widest. The
  fundamental pulse at 3.6 years against annual data is the live case: 3.6 samples per cycle, so its phase is
  the least trustworthy of the set and its kernel says so.

The consequence worth stating: the three long cycles contribute **broad gentle tilts** rather than sharp
claims, which is the correct weight for a position nobody measured.

## The skew, which is the least defensible part and is configurable

Level alone loses direction: a cycle rising through mid and one falling through mid both land on bin 13. So the
kernel is a **split normal** — same mode, different widths either side — leaning cautious when the cycle is
falling and aggressive when it is rising, in proportion to how fast it is moving relative to the fastest it
could move at its own period.

**The skew coefficient has no source.** It is a modelling choice in exactly the sense the regime tilts are
(see `regime.py` on that): the framework says direction matters, not how much. So it lives in config, defaults
to something defensible, and is reported with the result rather than buried. Set it to zero to recover a
symmetric kernel and the pure level reading.

## A boundary effect, which is real and not a bug

The axis is bounded at 1 and 25, so a cycle sitting near an extreme has its kernel **truncated**: part of the
mass that would fall below bin 1 or above bin 25 has nowhere to go, and normalising redistributes it inward.
The mode stays where the level put it; the *mean* is pulled toward the centre.

Innovation at level -0.6952 is the live example: centre bin 4.66, mean bin 5.33. That is not a skew failure and
not an arithmetic error — the axis genuinely has no bin 0, and a wide kernel near an end cannot be symmetric.
It matters because it means a deeply-troughed cycle reads slightly less extreme in its mean than its level
implies, and the effect is stronger the wider the kernel. Read the centre for position and the mean for
contribution.

## The superposition, and why it is linear

The cycle distributions are mixed **linearly** and then blended into the SAA/TAA merge as a third contributor,
at `cycles.bins.blend_weight`. Linear rather than multiplicative, for a reason that is a hard requirement
elsewhere in this engine: the brief requires that weight never vanishes at the crisis end, and the kernels in
`regime.py` guarantee live tail weight by construction. A multiplicative or log-opinion pool lets one
contributor's near-zero annihilate a tail another keeps alive. A linear mixture cannot.

## What a reader must know about the weight

At the configured 0.15 the cycle layer moves the published distribution materially — on the 2026-07 Global
Regime, the crisis tail from 23.39% to about 26.85% and the mean bin from 10.92 to 10.23 — while leaving the
**modal** bin at 12, so the reported current state does not move.

**Above about 0.20 the mode stops being a safe statistic.** The published Regime and the cycle layer have peaks
at opposite ends of the axis, so the blend is bimodal, and as the weight rises the cycle peak overtakes the
other one and the mode relocates **discontinuously from bin 12 to bin 2** — the entire axis — with nothing
having changed in the world. Since the Regime contract reports its current state as the modal state, that
would publish a crash that is an artefact of an argmax over two humps. 0.15 is the highest weight that avoids
it. Raising it further should be done only together with a bimodality-aware reported state; `saa_signal.merge`
already computes the dispersion needed for one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

#: The axis this module writes onto. Fixed by the downstream interface, same as `regime.STATE_COUNT`.
STATE_COUNT = 25

#: Confidence classes, worst to best, which is the order the width rule reads them in.
CLASS_MARGINAL = "marginal"
CLASS_ASSUMED = "assumed"
CLASS_SUPPLIED = "supplied"
CLASS_MEASURED = "measured"

#: How few sampling intervals per period counts as too few to band-pass. Below this a cycle is `marginal`.
#:
#: Four rather than the Nyquist two, deliberately. Nyquist says a period of two intervals is the theoretical
#: limit for detecting a cycle at all; recovering its *phase* well enough to place it on a 25-bin axis needs
#: more than the theoretical minimum. The fundamental pulse at 3.6 years against annual data sits below this
#: and is classified marginal, which is the honest answer.
MINIMUM_INTERVALS_PER_PERIOD = 4.0


class CycleBinError(ValueError):
    """Raised when a cycle cannot be placed on the axis, or the configuration is inconsistent."""


@dataclass(frozen=True)
class Placement:
    """One cycle's position on the axis, as a distribution rather than a point.

    Attributes:
        name: The cycle name.
        level: The cycle's level, cos(phase), in [-1, +1].
        centre: The bin the level maps to, one-based and not rounded.
        width: The kernel's base width in bins, before skew.
        skew: The applied skew, positive when rising. Zero when the coefficient is zero.
        velocity: The normalised rate of change in [-1, +1], which the skew is drawn from.
        confidence: One of the four classes above.
        distribution: The 25-bin distribution, summing to one.
        notes: Why this width and this class, so a chart can carry its own caveat.
    """

    name: str
    level: float
    centre: float
    width: float
    skew: float
    velocity: float
    confidence: str
    distribution: np.ndarray
    notes: list[str] = field(default_factory=list)

    @property
    def mean_bin(self) -> float:
        return float((np.arange(1, self.distribution.size + 1) * self.distribution).sum())

    @property
    def modal_bin(self) -> int:
        return int(np.argmax(self.distribution)) + 1


@dataclass
class CycleLayer:
    """Every cycle placed, and their mixture.

    Attributes:
        placements: Per cycle, in the order supplied.
        distribution: The linear mixture over the placements, summing to one.
        weights: The mixing weight used per cycle.
        notes: What a reader of the mixture must know.
    """

    placements: list[Placement]
    distribution: np.ndarray
    weights: dict[str, float]
    notes: list[str] = field(default_factory=list)

    @property
    def mean_bin(self) -> float:
        return float((np.arange(1, self.distribution.size + 1) * self.distribution).sum())

    @property
    def modal_bin(self) -> int:
        return int(np.argmax(self.distribution)) + 1

    def to_payload(self) -> dict[str, Any]:
        """A serialisable summary, for a manifest or a board."""
        return {
            "state_count": int(self.distribution.size),
            "mean_bin": self.mean_bin,
            "modal_bin": self.modal_bin,
            "distribution": [float(v) for v in self.distribution],
            "weights": dict(self.weights),
            "cycles": [
                {
                    "name": p.name,
                    "level": p.level,
                    "centre_bin": p.centre,
                    "width_bins": p.width,
                    "skew": p.skew,
                    "velocity": p.velocity,
                    "confidence": p.confidence,
                    "mean_bin": p.mean_bin,
                    "modal_bin": p.modal_bin,
                }
                for p in self.placements
            ],
            "notes": list(self.notes),
        }


def bin_centre(level: float, state_count: int = STATE_COUNT) -> float:
    """Map a cycle level in [-1, +1] onto the one-based bin axis.

    Raises:
        CycleBinError: If the level is outside [-1, +1] by more than floating-point slack. A level outside
            that range means the caller passed something other than cos(phase), and silently clipping it would
            place a cycle at an end of the axis for the wrong reason.
    """
    value = float(level)
    if not -1.0 - 1e-9 <= value <= 1.0 + 1e-9:
        raise CycleBinError(f"a cycle level must lie in [-1, 1], got {value}")
    value = min(1.0, max(-1.0, value))
    return 1.0 + (state_count - 1) * (value + 1.0) / 2.0


def classify(
    *,
    identifiable: bool,
    periods_in_sample: float | None,
    anchored: bool,
    assumed: bool,
    intervals_per_period: float | None = None,
) -> str:
    """Which confidence class a cycle falls in. Worst class wins.

    The order is deliberate: a cycle that is marginal on sampling grounds is marginal however well anchored,
    because an aliased phase is not improved by a supplied one being available.
    """
    if intervals_per_period is not None and intervals_per_period < MINIMUM_INTERVALS_PER_PERIOD:
        return CLASS_MARGINAL
    if anchored:
        return CLASS_ASSUMED if assumed else CLASS_SUPPLIED
    if not identifiable or not periods_in_sample:
        return CLASS_MARGINAL
    return CLASS_MEASURED


def width_for(
    confidence: str,
    periods_in_sample: float | None,
    settings: Mapping[str, Any],
) -> float:
    """The kernel's base width in bins, from what the position is worth.

    A measured cycle's width scales as ``base * sqrt(reference / periods_in_sample)``, the ordinary
    standard-error scaling, clamped to the configured range. Every other class takes a flat configured width,
    because there is no sample size to scale against: their position was supplied, projected, or recovered
    near the sampling limit.
    """
    if confidence == CLASS_MEASURED:
        base = float(settings.get("measured_base", 2.0))
        reference = float(settings.get("measured_reference_periods", 10.0))
        low = float(settings.get("measured_min", 1.5))
        high = float(settings.get("measured_max", 5.0))
        observed = float(periods_in_sample or reference)
        if observed <= 0.0:
            return high
        return float(min(high, max(low, base * np.sqrt(reference / observed))))
    key = {CLASS_SUPPLIED: "supplied", CLASS_ASSUMED: "assumed", CLASS_MARGINAL: "marginal"}[confidence]
    return float(settings.get(key, 5.0))


def normalised_velocity(level: float, previous_level: float, period_years: float, step_years: float = 1.0) -> float:
    """How fast the cycle is moving, as a fraction of the fastest it could move at its own period.

    A unit-amplitude cosine's steepest slope is ``2*pi/period`` per year, at its zero crossings. Dividing by
    that makes the result comparable across cycles of very different length, which is the whole point: a
    business cycle and a 130-year cycle both report their motion on the same [-1, +1] scale.
    """
    if period_years <= 0.0 or step_years <= 0.0:
        return 0.0
    rate = (float(level) - float(previous_level)) / float(step_years)
    fastest = 2.0 * np.pi / float(period_years)
    if fastest <= 0.0:
        return 0.0
    return float(min(1.0, max(-1.0, rate / fastest)))


def cycle_distribution(
    centre: float,
    width: float,
    skew: float = 0.0,
    state_count: int = STATE_COUNT,
) -> np.ndarray:
    """A split-normal kernel over the bins: same mode, different widths either side.

    `skew` in (-1, 1) widens the aggressive side when positive and the cautious side when negative, which is
    how direction of travel enters without moving the mode. The result is normalised, so the split changes the
    distribution's shape and mean but not where its peak sits.

    Raises:
        CycleBinError: If the width is not positive, or the skew would make a side non-positive.
    """
    if width <= 0.0:
        raise CycleBinError(f"a cycle kernel needs a positive width, got {width}")
    if not -0.95 <= skew <= 0.95:
        raise CycleBinError(f"the skew must lie in [-0.95, 0.95], got {skew}")

    bins = np.arange(1, state_count + 1, dtype=float)
    lower = width * (1.0 - skew)
    upper = width * (1.0 + skew)
    sigma = np.where(bins <= centre, lower, upper)
    kernel = np.exp(-0.5 * ((bins - centre) / sigma) ** 2)
    total = kernel.sum()
    if total <= 0.0:
        raise CycleBinError(f"the kernel vanished for centre {centre} and width {width}")
    return kernel / total


def place(
    name: str,
    level: float,
    period_years: float,
    settings: Mapping[str, Any],
    *,
    previous_level: float | None = None,
    identifiable: bool = True,
    periods_in_sample: float | None = None,
    anchored: bool = False,
    assumed: bool = False,
    intervals_per_period: float | None = None,
    step_years: float = 1.0,
    state_count: int = STATE_COUNT,
) -> Placement:
    """Place one cycle on the axis as a distribution."""
    widths = settings.get("widths", {}) or {}
    confidence = classify(
        identifiable=identifiable,
        periods_in_sample=periods_in_sample,
        anchored=anchored,
        assumed=assumed,
        intervals_per_period=intervals_per_period,
    )
    width = width_for(confidence, periods_in_sample, widths)
    centre = bin_centre(level, state_count)

    coefficient = float(settings.get("skew_coefficient", 0.0))
    velocity = 0.0
    if previous_level is not None:
        velocity = normalised_velocity(level, previous_level, period_years, step_years)
    skew = float(min(0.95, max(-0.95, coefficient * velocity)))

    notes = [
        f"{name}: level {level:+.4f} maps to bin {centre:.2f} on a {state_count}-bin axis "
        f"(trough 1, mid {1 + (state_count - 1) / 2:.0f}, peak {state_count}).",
        f"{name}: confidence class {confidence}, kernel width {width:.2f} bins.",
    ]
    if confidence == CLASS_SUPPLIED:
        notes.append(
            f"{name}: the position is supplied by an anchor rather than measured, so the kernel is "
            f"deliberately wide. It contributes a broad tilt, not a sharp claim."
        )
    if confidence == CLASS_MARGINAL:
        notes.append(
            f"{name}: fewer than {MINIMUM_INTERVALS_PER_PERIOD:g} sampling intervals per period, so its "
            f"phase is recovered near the sampling limit and is the least trustworthy in the set. Widest "
            f"kernel, and this note travels with it."
        )
    if coefficient and previous_level is not None:
        direction = "rising" if velocity > 0 else ("falling" if velocity < 0 else "flat")
        notes.append(
            f"{name}: {direction}, normalised velocity {velocity:+.3f}, so the kernel is skewed {skew:+.3f} "
            f"toward the {'aggressive' if skew > 0 else 'cautious'} end. The skew coefficient "
            f"{coefficient:g} is a modelling choice with no source and is reported for that reason."
        )

    return Placement(
        name=name,
        level=float(level),
        centre=centre,
        width=width,
        skew=skew,
        velocity=velocity,
        confidence=confidence,
        distribution=cycle_distribution(centre, width, skew, state_count),
        notes=notes,
    )


def superpose(
    placements: Sequence[Placement],
    weights: Mapping[str, float] | None = None,
) -> CycleLayer:
    """Mix the placed cycles linearly into one distribution over the axis.

    Equal weights unless told otherwise. Linear rather than multiplicative: see the module docstring on why a
    log-opinion pool is not permitted here.

    Raises:
        CycleBinError: If no placements were given, or the distributions disagree on length.
    """
    if not placements:
        raise CycleBinError("no cycles were placed, so there is nothing to superpose")
    sizes = {p.distribution.size for p in placements}
    if len(sizes) != 1:
        raise CycleBinError(f"the placed cycles disagree on axis length: {sorted(sizes)}")

    supplied = dict(weights or {})
    used = {p.name: float(supplied.get(p.name, 1.0)) for p in placements}
    total_weight = sum(used.values())
    if total_weight <= 0.0:
        raise CycleBinError("the cycle weights sum to zero, so no mixture exists")

    stacked = np.vstack([p.distribution for p in placements])
    mixed = np.array([used[p.name] for p in placements], dtype=float) @ stacked
    mixed = mixed / mixed.sum()

    classes = sorted({p.confidence for p in placements})
    notes = [
        f"{len(placements)} cycles mixed linearly on a {mixed.size}-bin axis: "
        + ", ".join(f"{p.name} at bin {p.centre:.2f} (width {p.width:.2f})" for p in placements)
        + ".",
        f"confidence classes present: {', '.join(classes)}. A supplied or marginal position carries a wide "
        f"kernel by construction, so it tilts the mixture without dominating it.",
        "mixed linearly, never multiplicatively: a log-opinion pool would let one cycle's near-zero "
        "annihilate tail weight another cycle keeps alive, and live crisis-tail weight is a requirement of "
        "this engine rather than an outcome.",
    ]
    return CycleLayer(placements=list(placements), distribution=mixed, weights=used, notes=notes)


def layer_matrix(
    estimates: Mapping[str, Any],
    anchored: Mapping[str, Any],
    settings: Mapping[str, Any],
    n_periods: int,
    *,
    step_years: float = 1.0,
    state_count: int = STATE_COUNT,
) -> tuple[np.ndarray, list[CycleLayer]]:
    """The cycle layer for every period, as a matrix the merge can blend.

    Returns the (n_periods, state_count) matrix and the per-period layers, because the matrix is what the
    blend consumes and the layers are what a reader needs in order to see why a row looks as it does.

    The first period is skipped for velocity purposes — there is no previous level to difference against — so
    its kernel is unskewed. That is stated rather than hidden: the first row of a blended timeline carries
    slightly less information than the rest, and pretending otherwise would mean inventing a velocity.

    Raises:
        CycleBinError: If no period can be placed at all.
    """
    if n_periods <= 0:
        raise CycleBinError(f"a cycle matrix needs at least one period, got {n_periods}")

    rows: list[np.ndarray] = []
    layers: list[CycleLayer] = []
    failures: list[str] = []
    for position in range(n_periods):
        try:
            layer = layer_from_cycles(
                estimates,
                anchored,
                settings,
                index=position,
                step_years=step_years,
                state_count=state_count,
            )
        except CycleBinError as error:
            failures.append(f"period {position}: {error}")
            # A period that cannot be placed contributes a flat row, which is the identity for a linear
            # mixture in the sense that it adds no information rather than adding a claim. It is recorded.
            rows.append(np.full(state_count, 1.0 / state_count))
            layers.append(
                CycleLayer(
                    placements=[],
                    distribution=np.full(state_count, 1.0 / state_count),
                    weights={},
                    notes=[f"no cycle could be placed for this period: {error}"],
                )
            )
            continue
        rows.append(layer.distribution)
        layers.append(layer)

    if len(failures) == n_periods:
        raise CycleBinError(
            "no period could be placed, so the cycle layer carries nothing: " + failures[0]
        )
    return np.vstack(rows), layers


def layer_from_cycles(
    estimates: Mapping[str, Any],
    anchored: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    index: int = -1,
    step_years: float = 1.0,
    state_count: int = STATE_COUNT,
) -> CycleLayer:
    """Build the whole cycle layer from the engine's own estimates and anchored cycles.

    Args:
        estimates: Band-pass `CycleEstimate` objects by name, as `decompose` returns.
        anchored: `AnchoredCycle` objects by name, as `anchored_from_config` returns.
        settings: The `cycles.bins` configuration block.
        index: Which period to read, defaulting to the last.
        step_years: Years per sample, for the velocity.
        state_count: Axis length.

    Only cycles named in `settings['members']` are placed, and a named cycle that is absent is **skipped with
    a note** rather than silently dropped or defaulted: a missing cycle is a fact about the data, and a layer
    that quietly contains fewer cycles than configured is a layer nobody can check.
    """
    members = list(settings.get("members") or [])
    if not members:
        raise CycleBinError("cycles.bins.members is empty, so no cycle layer can be built")

    placements: list[Placement] = []
    skipped: list[str] = []
    for name in members:
        source = estimates.get(name)
        anchor = anchored.get(name)
        if source is None and anchor is None:
            skipped.append(f"{name}: not present in either the estimated or the anchored set, so not placed")
            continue

        if anchor is not None:
            estimate = anchor.estimate
            is_anchored, is_assumed = True, bool(getattr(anchor, "assumed", False))
            period = float(getattr(anchor, "period_years", 0.0)) or float(estimate.estimated_period or 0.0)
        else:
            estimate = source
            is_anchored, is_assumed = False, False
            period = float(estimate.estimated_period or estimate.band.prior_period)

        # The level is taken from the PHASE, not from the component, and the difference is not cosmetic.
        #
        # `extract_cycle` builds the analytic signal z = A*exp(i*phi), so component = A*cos(phi). For an
        # anchored cycle the amplitude is one by construction and the two are identical. For a band-passed
        # cycle the amplitude is whatever the data has — log-output growth deviations of order 0.01 — so
        # passing the component as a level put every measured cycle at bin 13 regardless of where in its
        # cycle it actually sat. cos(phase) is the normalised position for both kinds, exactly, and it is
        # the same normalisation `superpose` already applies before summing.
        #
        # Found by reading the printed distributions rather than by a test, which is why one now asserts a
        # small-amplitude cycle still reaches the ends of the axis.
        # `atleast_1d`, not `asarray`, and the difference is a real bug rather than defensiveness. A cycle
        # can carry a *scalar* phase — an economy whose window is short enough that the extraction collapses
        # to one reading. `asarray` makes that a 0-d array whose `.size` is 1, so it clears an emptiness
        # check and then raises on being indexed. Found republishing across all ten economies, having passed
        # on `us` alone.
        phase = np.atleast_1d(np.asarray(getattr(estimate, "phase", []), dtype=float))
        if phase.size == 0:
            skipped.append(f"{name}: carries no phase, so its position cannot be normalised; not placed")
            continue
        position = index if index >= 0 else phase.size + index
        if not 0 <= position < phase.size:
            skipped.append(f"{name}: index {index} is outside its {phase.size} periods, so not placed")
            continue

        # Orientation: +1 when a peak in this cycle's own variable is the aggressive end of the risk axis,
        # -1 when it is the cautious end. Capital is -1 because its phase 0 is peak saturation, which is
        # maximum fragility. Absent from config means +1, which is the growth-cycle convention.
        orientation = float((settings.get("orientation") or {}).get(name, 1.0))
        if orientation not in (1.0, -1.0):
            raise CycleBinError(
                f"cycles.bins.orientation[{name!r}] must be +1 or -1, got {orientation}. It states which end "
                f"of the risk axis a peak in this cycle's own variable belongs at; a magnitude other than one "
                f"would silently rescale the cycle as well as orient it."
            )
        level = orientation * float(np.cos(phase[position]))
        previous = orientation * float(np.cos(phase[position - 1])) if position >= 1 else None
        identifiable = bool(getattr(estimate, "identifiable", True))
        sample_years = float(getattr(estimate, "sample_years", 0.0) or 0.0)
        periods_in_sample = (sample_years / period) if period > 0 else None
        intervals = (period / step_years) if step_years > 0 else None

        placements.append(
            place(
                name,
                level,
                period,
                settings,
                previous_level=previous,
                identifiable=identifiable,
                periods_in_sample=periods_in_sample,
                anchored=is_anchored,
                assumed=is_assumed,
                intervals_per_period=intervals,
                step_years=step_years,
                state_count=state_count,
            )
        )

    if not placements:
        raise CycleBinError(
            "none of the configured cycles could be placed: " + "; ".join(skipped)
        )

    layer = superpose(placements, settings.get("weights"))
    layer.notes.extend(skipped)
    if skipped:
        layer.notes.append(
            f"{len(skipped)} of {len(members)} configured cycles were not placed, listed above. The mixture "
            f"is over the {len(placements)} that were, and this note exists so that is visible rather than "
            f"inferred from a count."
        )
    return layer
