"""The Portfolio Map: a 4 by 5 Role by Scenario grid of allocated weight.

`PF_Map[role, scenario] += weight` for each instrument, placed by its role and its home scenario. It
answers a question the weight vector cannot: how much of the portfolio is held for each purpose, in each
state of the world it is held against.

**Column order is the book order**, crisis-low to boom-high, matching the state index. The reference
implementation's `pf_map.m` assigned `Boom -> column 1 ... Crisis -> column 5`, so its matrix was
boom-first in the data and not only in the display. The spec described that as a display convention; it
was not. This build standardises the matrix on the book order and reverses only in the view layer. See
decisions.md D4.

**An empty Boom column is expected, not a bug.** The Fund Map register's home-scenario vocabulary has
four values and does not use Boom, so with today's universe that column is all zeros. The grid keeps its
width so it stays stable if a Boom-scenario block appears (decisions.md D9).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from pcp.config import Config
from pcp.contracts import BuildingBlock


def portfolio_map(
    weights: np.ndarray,
    blocks: Sequence[BuildingBlock],
    config: Config,
) -> np.ndarray:
    """The 4 by 5 Role by Scenario grid.

    Rows follow the role vocabulary (Gain, Income, Stabilisation, Protection); columns follow the scenario
    vocabulary (Crisis, Contraction, Stagnation, Expansion, Boom).
    """
    x = np.asarray(weights, dtype=float).ravel()
    if x.shape[0] != len(blocks):
        raise ValueError(
            f"{x.shape[0]} weights against {len(blocks)} instruments"
        )

    roles = config.vocabularies.roles
    scenarios = config.vocabularies.scenarios
    grid = np.zeros((len(roles), len(scenarios)), dtype=float)
    for weight, block in zip(x, blocks):
        grid[roles.index(block.role), scenarios.index(block.home_scenario)] += float(weight)
    return grid


def role_allocation(grid: np.ndarray, config: Config) -> dict[str, float]:
    """Per-role totals: the row sums of the portfolio map.

    Spec section 5 calls these the column sums. With roles as rows, per-role totals are the row sums, and
    the reference implementation computed `sum(PF_Map')`, which is the row sums. The intent is per-role
    totals; the wording was wrong (decisions.md D19).
    """
    matrix = np.asarray(grid, dtype=float)
    roles = config.vocabularies.roles
    if matrix.shape[0] != len(roles):
        raise ValueError(
            f"the portfolio map has {matrix.shape[0]} rows against {len(roles)} roles"
        )
    return {label: float(matrix[k].sum()) for k, label in enumerate(roles.labels)}


def scenario_allocation(grid: np.ndarray, config: Config) -> dict[str, float]:
    """Per-scenario totals: the column sums. How much is held against each state of the world."""
    matrix = np.asarray(grid, dtype=float)
    scenarios = config.vocabularies.scenarios
    if matrix.shape[1] != len(scenarios):
        raise ValueError(
            f"the portfolio map has {matrix.shape[1]} columns against {len(scenarios)} scenarios"
        )
    return {label: float(matrix[:, k].sum()) for k, label in enumerate(scenarios.labels)}


def for_display(grid: np.ndarray) -> np.ndarray:
    """The grid with its columns reversed, boom-first, for the heatmap only.

    The single place the legacy display order is reproduced. Nothing computed from the map should use
    this: it exists so the cockpit's axis reads Boom at the top, as the reference figure did.
    """
    return np.asarray(grid, dtype=float)[:, ::-1]
