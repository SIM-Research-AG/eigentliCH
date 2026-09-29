"""The four-phase classifier and its transition indicators.

Brief section 0.5. The four phases of the capital cycle:

    Phase 1, Foundation:                low total capital, GDP-driven.
    Phase 2, Build-up:                  real-investment and credit-driven, still a production economy.
    Phase 3, Optimisation:              fully financialised.
    Phase 4, Saturation and reordering: the capital-to-GDP ratio corrects not through growth but
                                        through capital destruction, by debt deflation or by
                                        hyperinflation.

A note on scale, because it determines whether this classifier discriminates at all.

The brief states the cut-offs as K/Y below 1 for Phase 1, K/Y below 3 with K_R/Y below 1.5 for
Phase 3, and the production-versus-financial boundary at K_R/Y of 1. Book chapter 10 defines the
empirical proxies such that K_R/Y runs about 3 and K_I/Y about 4 to 6 for an advanced economy, so on
those proxies K_R/Y is never below 1, Phases 1 to 3 are unreachable, and every major economy
classifies as Phase 4 by default with no information in the distance to any boundary.

The resolution, settled with the author on 2026-07-27 and recorded in docs/MODEL_SPEC.md section 3,
is that the saturation axis carrying the 1 and 3 cut-offs and the 250 to 350 percent band is total
credit to the non-financial sector over GDP, which matches published data closely. The Phase 4
condition K_R/K_I below 1 is a ratio of two capital stocks, so it is scale-invariant and is applied
to the chapter 10 proxies literally.

The two conditions the brief states on K_R/Y alone (the production boundary at 1 and the Phase 3
ceiling at 1.5) remain in config at their stated values, and this module reports them as saturated
where the proxies exceed them rather than pretending they discriminate. Nothing is quietly rescaled.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Sequence

import numpy as np


class Phase(enum.IntEnum):
    """The four phases of the capital cycle, brief section 0.5."""

    FOUNDATION = 1
    BUILD_UP = 2
    OPTIMISATION = 3
    SATURATION = 4

    @property
    def label(self) -> str:
        """The phase name as it appears in reporting."""
        return {
            Phase.FOUNDATION: "Foundation",
            Phase.BUILD_UP: "Build-up",
            Phase.OPTIMISATION: "Optimisation",
            Phase.SATURATION: "Saturation and reordering",
        }[self]


class EconomyType(enum.Enum):
    """The production-versus-financial split of brief section 0.5."""

    PRODUCTION = "production"
    FINANCIAL = "financial"


@dataclass
class PhaseThresholds:
    """The cut-offs the classifier applies, from config.

    Attributes:
        foundation_saturation_ceiling: Saturation below which the economy is in Phase 1.
        optimisation_saturation_ceiling: Saturation below which Phase 3 is still available.
        saturation_real_to_financial_ceiling: K_R/K_I below which Phase 4 has begun.
        production_economy_real_capital_ceiling: K_R/Y below which the economy is a production
            economy. Saturated under the chapter 10 proxies, see the module docstring.
        optimisation_real_capital_ceiling: The Phase 3 ceiling on K_R/Y. Also saturated.
        balanced_band: The (lower, upper) balanced band on the saturation axis, 2.5 to 3.5, derived
            in book section 8.5 from the bifurcation analysis.
    """

    foundation_saturation_ceiling: float = 1.0
    optimisation_saturation_ceiling: float = 3.0
    saturation_real_to_financial_ceiling: float = 1.0
    production_economy_real_capital_ceiling: float = 1.0
    optimisation_real_capital_ceiling: float = 1.5
    balanced_band: tuple[float, float] = (2.5, 3.5)

    @classmethod
    def from_config(cls, config) -> "PhaseThresholds":
        """Build the thresholds from a loaded Config."""
        return cls(
            foundation_saturation_ceiling=float(config.get("phases.foundation_saturation_ceiling")),
            optimisation_saturation_ceiling=float(
                config.get("phases.optimisation_saturation_ceiling")
            ),
            saturation_real_to_financial_ceiling=float(
                config.get("phases.saturation_real_to_financial_ceiling")
            ),
            production_economy_real_capital_ceiling=float(
                config.get("phases.production_economy_real_capital_ceiling")
            ),
            optimisation_real_capital_ceiling=float(
                config.get("phases.optimisation_real_capital_ceiling")
            ),
            balanced_band=(
                float(config.get("saturation.balanced_band.lower")),
                float(config.get("saturation.balanced_band.upper")),
            ),
        )


@dataclass
class PhaseClassification:
    """The phase of a single economy at a single period.

    Attributes:
        phase: The classified phase.
        economy_type: Production or financial, per the K_R/Y test.
        saturation: The value on the saturation axis, total credit to the non-financial sector over
            GDP.
        real_capital_intensity: K_R/Y from the chapter 10 proxies.
        real_to_financial: K_R/K_I from the chapter 10 proxies.
        in_balanced_band: Whether saturation sits inside the 250 to 350 percent band.
        distance_to_boundaries: Signed distance on the saturation axis to each cut-off. Negative
            means the cut-off has been passed.
        rules_fired: The conditions that selected this phase, in the order evaluated.
        saturated_conditions: Conditions that could not discriminate because the proxy scale exceeds
            the stated threshold for every developed economy. Reported so a reader is not misled
            into thinking they contributed.
    """

    phase: Phase
    economy_type: EconomyType
    saturation: float
    real_capital_intensity: float
    real_to_financial: float
    in_balanced_band: bool
    distance_to_boundaries: dict[str, float]
    rules_fired: list[str] = field(default_factory=list)
    saturated_conditions: list[str] = field(default_factory=list)


def classify_sequence(
    saturation: Sequence[float],
    real_capital: Sequence[float],
    financial_capital: Sequence[float],
    output: Sequence[float],
    thresholds: "PhaseThresholds | None" = None,
) -> list["PhaseClassification"]:
    """Classify a path, with the exit from Phase 4 held until the Foundation level is reached.

    Directed by the author on 2026-07-28: **the phase changes to Foundation only when saturation reaches
    that level. Otherwise it sits in Saturation.**

    `classify_period` is stateless, so on a falling path it reclassifies as soon as saturation crosses back
    under the Phase 3 ceiling: on United States projected data it read Build-up at 2.31 in the first
    projected period. That is wrong about the framework. Phase 4 is the *reordering*, and an economy in it is
    not in Build-up again the moment its ratio dips; it is part-way through a correction. The reordering ends
    when the capital base has actually come down to the Foundation level, and only then does the cycle
    restart.

    The rule is therefore a one-way latch: once the path is in Phase 4, every later period stays in Phase 4
    until saturation falls below `foundation_saturation_ceiling`, at which point the economy is in Foundation
    and ordinary classification resumes. Entry into Phase 4 is unchanged.

    This also resolves the contradiction the control board was reporting. While the latch holds, the economy
    genuinely is still in the reordering, so a capital cycle past its reordering point and a saturation level
    below the band are no longer two claims that cannot both be true.

    Args:
        saturation: The saturation axis path.
        real_capital: K_R path.
        financial_capital: K_I path.
        output: Y path.
        thresholds: The cut-offs.

    Returns:
        One classification per period.

    Raises:
        ValueError: If the inputs do not share a length.
    """
    t = thresholds or PhaseThresholds()
    lengths = {
        "saturation": len(saturation),
        "real_capital": len(real_capital),
        "financial_capital": len(financial_capital),
        "output": len(output),
    }
    if len(set(lengths.values())) != 1:
        raise ValueError(f"all paths must share a length, got {lengths}")

    out: list[PhaseClassification] = []
    latched = False
    for index in range(lengths["saturation"]):
        classification = classify_period(
            saturation=float(saturation[index]),
            real_capital=float(real_capital[index]),
            financial_capital=float(financial_capital[index]),
            output=float(output[index]),
            thresholds=t,
        )

        if latched:
            if classification.saturation < t.foundation_saturation_ceiling:
                # The reordering has run its course: the capital base is down to the Foundation level.
                latched = False
                classification = replace(
                    classification,
                    phase=Phase.FOUNDATION,
                    rules_fired=[
                        f"saturation = {classification.saturation:.3f} has reached the Foundation level of "
                        f"{t.foundation_saturation_ceiling:.2f}, so the reordering is complete"
                    ]
                    + list(classification.rules_fired),
                )
            elif classification.phase is not Phase.SATURATION:
                classification = replace(
                    classification,
                    phase=Phase.SATURATION,
                    rules_fired=[
                        f"held in Saturation and reordering: saturation = {classification.saturation:.3f} "
                        f"has not yet reached the Foundation level of "
                        f"{t.foundation_saturation_ceiling:.2f}, and the reordering ends only there"
                    ]
                    + list(classification.rules_fired),
                )
        elif classification.phase is Phase.SATURATION:
            latched = True

        out.append(classification)
    return out


def classify_period(
    saturation: float,
    real_capital: float,
    financial_capital: float,
    output: float,
    thresholds: PhaseThresholds | None = None,
) -> PhaseClassification:
    """Classify a single period.

    Precedence, which the brief's conditions require because they overlap rather than partition:

    1. Phase 4 fires first, on either K_R/K_I below its ceiling (the reordering condition, which is
       scale-invariant) or saturation at or above the Phase 3 ceiling. Phase 4 is the terminal phase,
       so it cannot be overridden by a lower-phase condition also holding.
    2. Otherwise Phase 1 if saturation is below the Foundation ceiling.
    3. Otherwise Phase 2 while the economy is still a production economy, Phase 3 once it is not.

    Args:
        saturation: The saturation axis value, total credit to the non-financial sector over GDP.
        real_capital: K_R in currency units.
        financial_capital: K_I in currency units.
        output: Y in currency units.
        thresholds: The cut-offs. Defaults to the values the brief states.

    Returns:
        The classification, including the distances to each boundary and the rules that fired.

    Raises:
        ValueError: If output or financial capital is not positive, since the ratios are then
            undefined and a classification would be meaningless.
    """
    t = thresholds or PhaseThresholds()
    if output <= 0.0:
        raise ValueError(f"Y must be positive to classify a phase, got {output}")
    if financial_capital <= 0.0:
        raise ValueError(f"K_I must be positive to classify a phase, got {financial_capital}")

    real_capital_intensity = real_capital / output
    real_to_financial = real_capital / financial_capital

    economy_type = (
        EconomyType.PRODUCTION
        if real_capital_intensity < t.production_economy_real_capital_ceiling
        else EconomyType.FINANCIAL
    )

    rules: list[str] = []
    saturated: list[str] = []

    # Record where a stated condition cannot discriminate on this proxy scale.
    if real_capital_intensity >= t.production_economy_real_capital_ceiling:
        saturated.append(
            f"K_R/Y = {real_capital_intensity:.2f} exceeds the production-economy ceiling of "
            f"{t.production_economy_real_capital_ceiling:.2f}, so the production-versus-financial "
            f"test cannot select Phase 2 on this proxy scale"
        )
    if real_capital_intensity >= t.optimisation_real_capital_ceiling:
        saturated.append(
            f"K_R/Y = {real_capital_intensity:.2f} exceeds the Phase 3 real-capital ceiling of "
            f"{t.optimisation_real_capital_ceiling:.2f}, so that ceiling does not bind"
        )

    if real_to_financial < t.saturation_real_to_financial_ceiling:
        phase = Phase.SATURATION
        rules.append(
            f"K_R/K_I = {real_to_financial:.3f} is below {t.saturation_real_to_financial_ceiling:.2f}"
        )
    elif saturation >= t.optimisation_saturation_ceiling:
        phase = Phase.SATURATION
        rules.append(
            f"saturation = {saturation:.3f} is at or above the Phase 3 ceiling of "
            f"{t.optimisation_saturation_ceiling:.2f}"
        )
    elif saturation < t.foundation_saturation_ceiling:
        phase = Phase.FOUNDATION
        rules.append(
            f"saturation = {saturation:.3f} is below {t.foundation_saturation_ceiling:.2f}"
        )
    elif economy_type is EconomyType.PRODUCTION:
        phase = Phase.BUILD_UP
        rules.append(
            f"saturation = {saturation:.3f} is at or above {t.foundation_saturation_ceiling:.2f} "
            f"and K_R/Y = {real_capital_intensity:.3f} is still below "
            f"{t.production_economy_real_capital_ceiling:.2f}"
        )
    else:
        phase = Phase.OPTIMISATION
        rules.append(
            f"saturation = {saturation:.3f} is below {t.optimisation_saturation_ceiling:.2f} and "
            f"K_R/Y = {real_capital_intensity:.3f} is at or above "
            f"{t.production_economy_real_capital_ceiling:.2f}"
        )

    lower, upper = t.balanced_band
    distances = {
        "foundation_ceiling": t.foundation_saturation_ceiling - saturation,
        "optimisation_ceiling": t.optimisation_saturation_ceiling - saturation,
        "balanced_band_lower": lower - saturation,
        "balanced_band_upper": upper - saturation,
        "real_to_financial_ceiling": real_to_financial - t.saturation_real_to_financial_ceiling,
    }

    return PhaseClassification(
        phase=phase,
        economy_type=economy_type,
        saturation=float(saturation),
        real_capital_intensity=float(real_capital_intensity),
        real_to_financial=float(real_to_financial),
        in_balanced_band=bool(lower <= saturation <= upper),
        distance_to_boundaries=distances,
        rules_fired=rules,
        saturated_conditions=saturated,
    )


@dataclass
class PhaseTimeline:
    """The phase of an economy over a path, with the transitions located.

    Attributes:
        periods: The period labels, normally years.
        classifications: The per-period classification.
        phases: The phase as an integer array, for export and plotting.
        transitions: The (index, from_phase, to_phase) of each phase change.
        current: The classification at the final period.
    """

    periods: np.ndarray
    classifications: list[PhaseClassification]
    phases: np.ndarray
    transitions: list[tuple[int, Phase, Phase]]
    current: PhaseClassification


def classify_timeline(
    periods: np.ndarray,
    saturation: np.ndarray,
    real_capital: np.ndarray,
    financial_capital: np.ndarray,
    output: np.ndarray,
    thresholds: PhaseThresholds | None = None,
) -> PhaseTimeline:
    """Classify every period of a path and locate the transitions.

    Args:
        periods: The period labels, normally years.
        saturation: The saturation axis path.
        real_capital: The K_R path.
        financial_capital: The K_I path.
        output: The Y path.
        thresholds: The cut-offs.

    Returns:
        The timeline.

    Raises:
        ValueError: If the inputs do not share a length, or if the path is empty.
    """
    arrays = {
        "periods": np.asarray(periods),
        "saturation": np.asarray(saturation, dtype=float),
        "real_capital": np.asarray(real_capital, dtype=float),
        "financial_capital": np.asarray(financial_capital, dtype=float),
        "output": np.asarray(output, dtype=float),
    }
    lengths = {name: array.shape[0] for name, array in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"all inputs must share a length, got {lengths}")
    if arrays["periods"].shape[0] == 0:
        raise ValueError("cannot classify an empty path")

    classifications = [
        classify_period(
            saturation=float(arrays["saturation"][i]),
            real_capital=float(arrays["real_capital"][i]),
            financial_capital=float(arrays["financial_capital"][i]),
            output=float(arrays["output"][i]),
            thresholds=thresholds,
        )
        for i in range(arrays["periods"].shape[0])
    ]

    phases = np.array([int(c.phase) for c in classifications], dtype=int)
    transitions = [
        (i, classifications[i - 1].phase, classifications[i].phase)
        for i in range(1, len(classifications))
        if classifications[i].phase is not classifications[i - 1].phase
    ]

    return PhaseTimeline(
        periods=arrays["periods"],
        classifications=classifications,
        phases=phases,
        transitions=transitions,
        current=classifications[-1],
    )


def phase_four_entry_indicator(real_to_financial: np.ndarray, ceiling: float = 1.0) -> int | None:
    """Return the index at which K_R/K_I first crosses below the Phase 4 ceiling.

    Brief section 0.5 names this as a transition indicator alongside accelerating unsecured assets
    into Phase III (which lives in model/quantity.py).

    Args:
        real_to_financial: The K_R/K_I path.
        ceiling: The ceiling, normally one.

    Returns:
        The index of the first crossing, or None if the path never crosses.
    """
    ratio = np.asarray(real_to_financial, dtype=float)
    below = ratio < ceiling
    hits = np.flatnonzero(below)
    return int(hits[0]) if hits.size else None
