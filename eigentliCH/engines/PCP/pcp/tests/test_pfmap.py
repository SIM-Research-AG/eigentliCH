"""The portfolio map: the 4 by 5 Role by Scenario grid, and its ordering."""

from __future__ import annotations

import numpy as np
import pytest

from pcp.model.pfmap import (
    for_display,
    portfolio_map,
    role_allocation,
    scenario_allocation,
)


class TestGrid:
    def test_the_grid_is_four_by_five(self, blocks, config):
        grid = portfolio_map(np.array([0.25, 0.25, 0.25, 0.25]), blocks, config)
        assert grid.shape == (4, 5)

    def test_weight_lands_in_the_role_and_scenario_cell(self, blocks, config):
        """The fixture's four blocks are Gain, Gain, Income, Protection, all home-scenario Stagnation."""
        weights = np.array([0.4, 0.1, 0.3, 0.2])
        grid = portfolio_map(weights, blocks, config)

        roles = config.vocabularies.roles
        scenarios = config.vocabularies.scenarios
        stagnation = scenarios.index("Stagnation")

        assert grid[roles.index("Gain"), stagnation] == pytest.approx(0.5)
        assert grid[roles.index("Income"), stagnation] == pytest.approx(0.3)
        assert grid[roles.index("Protection"), stagnation] == pytest.approx(0.2)
        assert grid[roles.index("Stabilisation"), stagnation] == pytest.approx(0.0)

    def test_the_grid_totals_the_weights(self, blocks, config):
        weights = np.array([0.4, 0.1, 0.3, 0.2])
        assert portfolio_map(weights, blocks, config).sum() == pytest.approx(weights.sum())

    def test_a_weight_count_mismatch_is_refused(self, blocks, config):
        with pytest.raises(ValueError, match="weights against"):
            portfolio_map(np.array([1.0]), blocks, config)


class TestOrdering:
    def test_columns_run_crisis_low_to_boom_high(self, config):
        """The book order, matching the state index. The reference implementation's matrix was boom-first
        in its column index, not only in its display, and the spec described that as a display convention.
        It was not (decisions.md D4)."""
        assert config.vocabularies.scenarios.labels == (
            "Crisis", "Contraction", "Stagnation", "Expansion", "Boom"
        )

    def test_rows_follow_the_role_vocabulary(self, config):
        assert config.vocabularies.roles.labels == ("Gain", "Income", "Stabilisation", "Protection")

    def test_the_display_helper_reverses_only_for_the_view(self, config):
        grid = np.arange(20, dtype=float).reshape(4, 5)
        displayed = for_display(grid)
        assert displayed[0].tolist() == [4.0, 3.0, 2.0, 1.0, 0.0]
        # The source grid is untouched, so nothing computed from it sees the reversal.
        assert grid[0].tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]


class TestAllocations:
    def test_role_allocation_is_the_row_sums(self, config):
        """Spec section 5 calls these column sums; with roles as rows they are the row sums, which is what
        the reference computed (decisions.md D19)."""
        grid = np.array(
            [
                [0.0, 0.1, 0.2, 0.0, 0.0],
                [0.0, 0.0, 0.3, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.4, 0.0, 0.0, 0.0, 0.0],
            ]
        )
        assert role_allocation(grid, config) == {
            "Gain": pytest.approx(0.3),
            "Income": pytest.approx(0.3),
            "Stabilisation": pytest.approx(0.0),
            "Protection": pytest.approx(0.4),
        }

    def test_scenario_allocation_is_the_column_sums(self, config):
        grid = np.array(
            [
                [0.0, 0.1, 0.2, 0.0, 0.0],
                [0.0, 0.0, 0.3, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.4, 0.0, 0.0, 0.0, 0.0],
            ]
        )
        assert scenario_allocation(grid, config) == {
            "Crisis": pytest.approx(0.4),
            "Contraction": pytest.approx(0.1),
            "Stagnation": pytest.approx(0.5),
            "Expansion": pytest.approx(0.0),
            "Boom": pytest.approx(0.0),
        }

    def test_role_and_scenario_totals_agree(self, blocks, config):
        weights = np.array([0.4, 0.1, 0.3, 0.2])
        grid = portfolio_map(weights, blocks, config)
        assert sum(role_allocation(grid, config).values()) == pytest.approx(
            sum(scenario_allocation(grid, config).values())
        )

    def test_a_wrong_shape_is_refused(self, config):
        with pytest.raises(ValueError, match="rows against"):
            role_allocation(np.zeros((3, 5)), config)
        with pytest.raises(ValueError, match="columns against"):
            scenario_allocation(np.zeros((4, 4)), config)


class TestEmptyBoomColumn:
    def test_an_empty_boom_column_is_expected_not_an_error(self, blocks, config):
        """The register's home-scenario vocabulary has four values and does not use Boom, so with today's
        universe that column is all zeros. The grid keeps its width (decisions.md D9)."""
        grid = portfolio_map(np.array([0.25, 0.25, 0.25, 0.25]), blocks, config)
        boom = config.vocabularies.scenarios.index("Boom")
        assert grid[:, boom].sum() == pytest.approx(0.0)
        assert grid.shape[1] == 5
