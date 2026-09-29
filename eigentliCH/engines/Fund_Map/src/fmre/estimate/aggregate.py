"""Aggregate the 25-state profile to the 5-scenario profile, and classify
a block's role from its profile shape (spec 5.4).

Weighting within a scenario uses the empirical state frequencies ``pi_s``
from the Regime timeline. Where all states in a scenario have zero
frequency, we fall back to equal weighting and label the aggregate
``uniform_fallback`` on the block-level metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from fmre.estimate.block import BlockEstimate
from fmre.regime import StateToScenario

if TYPE_CHECKING:
    from fmre.registers.building_blocks import CanonicalRole


@dataclass(frozen=True, slots=True)
class ScenarioProfile:
    """A block's return profile aggregated to the 5 scenarios."""

    block_id: int
    ticker: str
    canonical_role: str
    scenario_order: tuple[str, ...]      # low-rank (crisis) to high-rank (boom)
    profile_by_scenario: dict[str, float]
    weighting_note: str                  # 'pi_s' or 'uniform_fallback'

    def as_ordered(self) -> tuple[float, ...]:
        return tuple(self.profile_by_scenario[s] for s in self.scenario_order)


def aggregate_to_scenarios(
    estimate: BlockEstimate,
    state_to_scenario: StateToScenario,
    state_frequencies: pd.Series | None = None,
) -> ScenarioProfile:
    """Collapse a 25-state profile to a 5-scenario profile.

    ``state_frequencies`` is a length-``state_grid`` Series of ``pi_s`` from
    ``RegimeTimeline.state_frequencies``. When None, equal weighting is used
    within each scenario and the result is labelled ``uniform_fallback``.
    """
    profile = estimate.profile_by_state
    if len(profile) != state_to_scenario.state_grid:
        raise ValueError(
            f"aggregate_to_scenarios: profile length {len(profile)} != "
            f"state_grid {state_to_scenario.state_grid}"
        )

    weighting_note = "pi_s" if state_frequencies is not None else "uniform_fallback"
    out: dict[str, float] = {}
    for scenario in state_to_scenario.scenario_order:
        states = state_to_scenario.states_of(scenario)
        mus = np.array([profile[s] for s in states], dtype=float)
        if state_frequencies is None:
            weights = np.full(len(states), 1.0 / len(states))
        else:
            pi = np.array([float(state_frequencies.iloc[s]) for s in states], dtype=float)
            total = pi.sum()
            if total <= 0.0:
                # Scenario never visited; fall back to uniform for this scenario
                weights = np.full(len(states), 1.0 / len(states))
            else:
                weights = pi / total
        out[scenario] = float((weights * mus).sum())

    return ScenarioProfile(
        block_id=estimate.block_id,
        ticker=estimate.ticker,
        canonical_role=estimate.canonical_role,
        scenario_order=state_to_scenario.scenario_order,
        profile_by_scenario=out,
        weighting_note=weighting_note,
    )


# ---------------------------------------------------------------------------
# Role classification from profile shape (spec 5.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoleClassification:
    """Inferred role vs the block's declared role, with the shape evidence
    that produced the inference. Never overwrites the declared role."""

    block_id: int
    declared: str          # canonical role from the register
    inferred: str          # canonical role from the profile shape
    is_match: bool
    slope: float           # mean(last 5) - mean(first 5)
    mean_level: float      # mean over all 25 states
    dispersion: float      # std over all 25 states


def classify_role(estimate: BlockEstimate) -> RoleClassification:
    """Infer a canonical role from the shape of ``profile_by_state``.

    Rule (annualised percent units):
      - slope > +5:  Gain              (net ascending into boom)
      - slope < -5:  Protection        (net descending into crisis end)
      - |slope| <= 5 AND mean_level >= +1.5:  Income
      - |slope| <= 5 AND mean_level <  +1.5:  Stabilisation

    The thresholds are heuristic; the point of this classification is to
    FLAG mismatches with the declared role for review, not to overrule it.
    """
    profile = np.array(estimate.profile_by_state, dtype=float)
    first5 = float(profile[:5].mean())
    last5 = float(profile[-5:].mean())
    slope = last5 - first5
    mean_level = float(profile.mean())
    dispersion = float(profile.std(ddof=0))

    if slope > 5.0:
        inferred = "Gain"
    elif slope < -5.0:
        inferred = "Protection"
    elif mean_level >= 1.5:
        inferred = "Income"
    else:
        inferred = "Stabilisation"

    return RoleClassification(
        block_id=estimate.block_id,
        declared=estimate.canonical_role,
        inferred=inferred,
        is_match=(inferred == estimate.canonical_role),
        slope=slope,
        mean_level=mean_level,
        dispersion=dispersion,
    )
