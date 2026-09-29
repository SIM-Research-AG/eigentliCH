"""The four-phase classifier and the unsecured-asset diagnostics. Pure.

Phases (brief section 0.5): 1 Foundation, 2 Build-up, 3 Optimisation, 4 Saturation and
reordering. The saturation axis carrying the 1.0 and 3.5 cut-offs and the 2.5 to 3.5 balanced
band is total credit to the non-financial sector over GDP, uplifted (see calibration.py). The
Phase 4 test K_R/K_I < 1 is a ratio of two stocks, so it is invariant to the capital
normalisation and applied to the assembled stocks literally.

Precedence, because the brief's conditions overlap rather than partition: Phase 4 first (on
Genreith's commercial-bank share below its floor where it is published, K_R/K_I below its
ceiling, or saturation at or above the Phase 3 ceiling), then Phase 1 below
the Foundation ceiling, then Phase 2 while K_R/Y is below the production ceiling, else Phase 3.

Exit from Phase 4 is latched (author's direction of 2026-07-28): once in the reordering, an
economy stays there until saturation reaches the Foundation level, rather than reading Build-up
the moment its ratio dips. Both the latched and the stateless phase are published.

Follows ``Macro_Model/macrofield/model/phases.py`` and ``quantity.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .contracts import PhaseThresholds


@dataclass(frozen=True)
class PeriodPhase:
    phase: int
    economy_type: str
    in_balanced_band: bool
    rules: tuple[str, ...]


def classify_period(saturation: float, real_capital: float, financial_capital: float,
                    output: float, t: PhaseThresholds,
                    commercial_share: Optional[float] = None) -> PeriodPhase:
    if output <= 0.0:
        raise ValueError(f"Y must be positive to classify a phase, got {output}")
    if financial_capital <= 0.0:
        raise ValueError(f"K_I must be positive to classify a phase, got {financial_capital}")
    intensity = real_capital / output
    real_to_financial = real_capital / financial_capital
    production = intensity < t.production_economy_real_capital_ceiling

    floor = t.commercial_bank_share_floor
    if floor is not None and commercial_share is not None and commercial_share < floor:
        phase = 4
        rule = (f"loans / bank balance sheet = {commercial_share:.3f} is below {floor:.2f} "
                "(Genreith's Phase IV: commercial banking below half of all bank business)")
    elif real_to_financial < t.saturation_real_to_financial_ceiling:
        phase = 4
        rule = (f"K_R/K_I = {real_to_financial:.3f} is below "
                f"{t.saturation_real_to_financial_ceiling:.2f}")
    elif saturation >= t.optimisation_saturation_ceiling:
        phase = 4
        rule = (f"saturation = {saturation:.3f} is at or above the Phase 3 ceiling of "
                f"{t.optimisation_saturation_ceiling:.2f}")
    elif saturation < t.foundation_saturation_ceiling:
        phase = 1
        rule = f"saturation = {saturation:.3f} is below {t.foundation_saturation_ceiling:.2f}"
    elif production:
        phase = 2
        rule = (f"saturation = {saturation:.3f} is at or above "
                f"{t.foundation_saturation_ceiling:.2f} and K_R/Y = {intensity:.3f} is below "
                f"{t.production_economy_real_capital_ceiling:.2f}")
    else:
        phase = 3
        rule = (f"saturation = {saturation:.3f} is below {t.optimisation_saturation_ceiling:.2f}"
                f" and K_R/Y = {intensity:.3f} is at or above "
                f"{t.production_economy_real_capital_ceiling:.2f}")

    band = t.balanced_band
    return PeriodPhase(
        phase=phase,
        economy_type="production" if production else "financial",
        in_balanced_band=bool(band.lower <= saturation <= band.upper),
        rules=(rule,),
    )


def classify_sequence(saturation: np.ndarray, real_capital: np.ndarray,
                      financial_capital: np.ndarray, output: np.ndarray,
                      t: PhaseThresholds, start_latched: bool = False,
                      commercial_share: Optional[np.ndarray] = None
                      ) -> tuple[list[PeriodPhase], list[PeriodPhase]]:
    """(latched, stateless) classifications, one per period.

    ``start_latched`` enters the sequence already in the reordering, for a sequence that
    continues one whose last phase was 4 (a projection after its window).
    """
    def share(i: int) -> Optional[float]:
        if commercial_share is None or not np.isfinite(commercial_share[i]):
            return None
        return float(commercial_share[i])

    stateless = [classify_period(float(saturation[i]), float(real_capital[i]),
                                 float(financial_capital[i]), float(output[i]), t, share(i))
                 for i in range(len(saturation))]
    latched: list[PeriodPhase] = []
    holding = start_latched
    for i, c in enumerate(stateless):
        sat = float(saturation[i])
        if holding:
            if sat < t.foundation_saturation_ceiling:
                holding = False
                c = PeriodPhase(1, c.economy_type, c.in_balanced_band, (
                    f"saturation = {sat:.3f} has reached the Foundation level of "
                    f"{t.foundation_saturation_ceiling:.2f}, so the reordering is complete",
                ) + c.rules)
            elif c.phase != 4:
                c = PeriodPhase(4, c.economy_type, c.in_balanced_band, (
                    f"held in Saturation and reordering: saturation = {sat:.3f} has not yet "
                    f"reached the Foundation level of {t.foundation_saturation_ceiling:.2f}",
                ) + c.rules)
        elif c.phase == 4:
            holding = True
        latched.append(c)
    return latched, stateless


def unsecured_ratio(real_capital: np.ndarray, financial_capital: np.ndarray,
                    output: np.ndarray) -> np.ndarray:
    """(K_R + K_I - Y) / Y: financial value the productive economy does not cover."""
    y = np.asarray(output, dtype=float)
    return (np.asarray(real_capital, dtype=float) + np.asarray(financial_capital, dtype=float)
            - y) / y


def unsecured_accelerating(real_capital: np.ndarray, financial_capital: np.ndarray,
                           output: np.ndarray, periods: int) -> np.ndarray:
    """True where the unsecured gap's second difference has been positive ``periods`` times running.

    The Phase III signature of section 0.4. A single noisy period does not fire it.
    """
    level = (np.asarray(real_capital, dtype=float) + np.asarray(financial_capital, dtype=float)
             - np.asarray(output, dtype=float))
    acceleration = np.full(level.shape, -np.inf)
    acceleration[2:] = np.diff(level, n=2)
    mask = np.zeros(level.shape, dtype=bool)
    run = 0
    for i, value in enumerate(acceleration > 0.0):
        run = run + 1 if value else 0
        mask[i] = run >= periods
    return mask
