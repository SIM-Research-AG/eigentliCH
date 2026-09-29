"""Coverage matrix and resilience (spec 5.5).

Given a set of BlockEstimates and their portfolio weights, and a mandate
scenario profile ``R_E^s``, compute:

    R_P^s   = sum_b w_b * P_{b,s}                (portfolio return in scenario s)
    coverage: R_P^s >= R_E^s                       for every scenario s
    R       = min_s ( R_P^s - R_E^s )              worst funding margin

R >= 0 means every scenario column clears the mandate. R is dominated by
the failing scenario, not by the flattering average.

This module exposes P_{b,s} and R. It does NOT choose weights (that is the
optimiser downstream).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from fmre.estimate.aggregate import ScenarioProfile, aggregate_to_scenarios
from fmre.estimate.block import BlockEstimate
from fmre.regime import RegimeTimeline, StateToScenario


@dataclass(frozen=True, slots=True)
class CoverageReport:
    scenario_order: tuple[str, ...]
    r_p_by_scenario: dict[str, float]        # portfolio return by scenario
    r_e_by_scenario: dict[str, float]        # mandate by scenario
    margins: dict[str, float]                # R_P^s - R_E^s per scenario
    resilience: float                        # min over scenarios of margin
    failing_scenario: str | None             # scenario at the minimum, if margin < 0

    @property
    def passes(self) -> bool:
        return self.resilience >= 0.0


def build_coverage_matrix(
    estimates: Mapping[int, BlockEstimate],
    state_to_scenario: StateToScenario,
    state_frequencies: pd.Series | None = None,
) -> pd.DataFrame:
    """Build the coverage matrix ``P_{b,s}`` as a DataFrame.

    Rows: block_id. Columns: scenario (in ``scenario_order``).
    """
    rows: dict[int, dict[str, float]] = {}
    for bid, est in estimates.items():
        sp = aggregate_to_scenarios(est, state_to_scenario, state_frequencies)
        rows[bid] = dict(sp.profile_by_scenario)
    df = pd.DataFrame.from_dict(rows, orient="index")
    df = df.reindex(columns=list(state_to_scenario.scenario_order))
    df.index.name = "block_id"
    return df


def portfolio_scenario_return(
    weights: Mapping[int, float],
    coverage_matrix: pd.DataFrame,
) -> pd.Series:
    """R_P^s = sum_b w_b * P_{b,s} for every scenario.

    Weights are keyed by ``block_id``. Missing blocks are treated as weight
    zero. Weights need not sum to 1; the caller decides (a cash residual is
    a legitimate block).
    """
    w = pd.Series(weights, dtype=float).reindex(coverage_matrix.index).fillna(0.0)
    return (coverage_matrix.mul(w, axis=0)).sum(axis=0)


def resilience(
    weights: Mapping[int, float],
    coverage_matrix: pd.DataFrame,
    mandate: Mapping[str, float],
) -> CoverageReport:
    """Compute the coverage report against a scenario mandate.

    ``mandate`` maps scenario name to the required scenario return ``R_E^s``.
    Every column of ``coverage_matrix`` must appear in ``mandate``.
    """
    r_p = portfolio_scenario_return(weights, coverage_matrix)
    scenario_order = tuple(coverage_matrix.columns)
    missing = [s for s in scenario_order if s not in mandate]
    if missing:
        raise ValueError(f"resilience: mandate missing scenarios {missing}")

    margins = {s: float(r_p[s]) - float(mandate[s]) for s in scenario_order}
    min_scenario = min(margins, key=margins.get)  # scenario with smallest margin
    r_val = margins[min_scenario]
    failing = min_scenario if r_val < 0 else None

    return CoverageReport(
        scenario_order=scenario_order,
        r_p_by_scenario={s: float(r_p[s]) for s in scenario_order},
        r_e_by_scenario={s: float(mandate[s]) for s in scenario_order},
        margins=margins,
        resilience=r_val,
        failing_scenario=failing,
    )
