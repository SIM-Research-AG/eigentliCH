"""Constraint assembly: block order, bound signs, and the two blocks that were inert in the reference.

Row order is the contract. These tests pin it explicitly rather than checking that the system merely
solves, because a reordering changes what every bound means while leaving the shapes intact and every
solve still succeeding.
"""

from __future__ import annotations

import numpy as np
import pytest

from pcp.contracts import Bound, Mandate
from pcp.model.constraints import (
    binding_constraints,
    build_constraints,
    realised_exposures,
)


class TestBlockOrder:
    def test_the_rows_are_in_the_specified_order(self, mandate, blocks, config):
        """Currency (10), Region (7), Role (4), Capital Type (3), Liquidity (4), ESG (1), Phase (4),
        Asset Class (5), each classification appearing as upper then negated lower."""
        system = build_constraints(mandate, blocks, config)

        expected: list[str] = []
        for dimension, size in (
            ("currency", 10), ("region", 7), ("role", 4), ("capital_type", 3), ("liquidity", 4),
        ):
            expected += [f"{dimension}:upper"] * size + [f"{dimension}:lower"] * size
        expected += ["esg:lower"]
        for dimension, size in (("phase", 4), ("asset_class", 5)):
            expected += [f"{dimension}:upper"] * size + [f"{dimension}:lower"] * size

        actual = [
            f"{label.split(':')[0]}:{label.split(':')[2]}" for label in system.row_labels
        ]
        assert actual == expected

    def test_the_row_count_is_as_specified(self, mandate, blocks, config):
        # 2 * (10 + 7 + 4 + 3 + 4 + 4 + 5) + 1 = 75
        system = build_constraints(mandate, blocks, config)
        assert system.n_rows == 75

    def test_the_esg_row_sits_between_liquidity_and_phase(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        assert system.row_labels[system.esg_row_index].startswith("esg:")
        assert system.row_labels[system.esg_row_index - 1].startswith("liquidity:")
        assert system.row_labels[system.esg_row_index + 1].startswith("phase:")

    def test_a_reordered_configuration_is_refused(self, mandate, blocks, config):
        """The assembler and the configured order must agree, or every bound would shift."""
        original = list(config.get("constraints.block_order"))
        config.raw["constraints"]["block_order"] = ["region", "currency", "role", "capital_type",
                                                    "liquidity", "esg", "phase", "asset_class"]
        try:
            with pytest.raises(ValueError, match="positional"):
                build_constraints(mandate, blocks, config)
        finally:
            config.raw["constraints"]["block_order"] = original


class TestBoundSigns:
    def test_upper_rows_are_positive_and_lower_rows_negated(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        chf_upper = system.row_labels.index("currency:CHF:upper")
        chf_lower = system.row_labels.index("currency:CHF:lower")

        # CHF members are blocks 1 and 3, at universe positions 0 and 2.
        assert system.a[chf_upper].tolist() == [1.0, 0.0, 1.0, 0.0]
        assert system.a[chf_lower].tolist() == [-1.0, 0.0, -1.0, 0.0]
        assert system.b[chf_upper] == pytest.approx(0.70)
        assert system.b[chf_lower] == pytest.approx(-0.30)

    def test_an_unmentioned_category_is_unconstrained(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        jpy_upper = system.row_labels.index("currency:JPY:upper")
        jpy_lower = system.row_labels.index("currency:JPY:lower")
        assert system.b[jpy_upper] == pytest.approx(1.0)
        assert system.b[jpy_lower] == pytest.approx(0.0)

    def test_every_instrument_lands_in_exactly_one_category_per_dimension(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        for block in system.blocks:
            assert block.indicator.sum(axis=0).tolist() == [1.0] * len(blocks)


class TestInstrumentBounds:
    def test_the_upper_bound_is_the_maximum_single_position(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        assert system.upper_bounds.tolist() == [0.5] * len(blocks)
        assert system.lower_bounds.tolist() == [0.0] * len(blocks)

    def test_a_fixed_allocation_pins_both_ends(self, mandate, blocks, config):
        pinned = Mandate(
            **{
                **{
                    "client": mandate.client, "name": mandate.name, "market": mandate.market,
                    "currency": mandate.currency, "benchmark": mandate.benchmark,
                    "max_single_position": mandate.max_single_position, "esg_min": mandate.esg_min,
                    "horizon_years": mandate.horizon_years, "target_curve": mandate.target_curve,
                    "universe": mandate.universe, "bounds": mandate.bounds,
                },
                "fixed_allocations": {3: 0.12},
            }
        )
        system = build_constraints(pinned, blocks, config)
        # Block 3 sits at universe position 2.
        assert system.lower_bounds[2] == pytest.approx(0.12)
        assert system.upper_bounds[2] == pytest.approx(0.12)


class TestEsgRow:
    def test_the_esg_row_carries_the_per_instrument_scores(self, mandate, blocks, config):
        """The reference implementation used a row of ones, which made the constraint inert
        (decisions.md D16, D24). This asserts it is no longer inert."""
        system = build_constraints(mandate, blocks, config)
        assert system.esg_row.tolist() == [1.0, 1.0, 3.0, 2.0]
        assert not np.allclose(system.esg_row, 1.0)

    def test_the_esg_row_is_negated_against_the_floor(self, mandate, blocks, config):
        constrained = Mandate(
            **{
                **{
                    "client": mandate.client, "name": mandate.name, "market": mandate.market,
                    "currency": mandate.currency, "benchmark": mandate.benchmark,
                    "max_single_position": mandate.max_single_position,
                    "horizon_years": mandate.horizon_years, "target_curve": mandate.target_curve,
                    "universe": mandate.universe, "bounds": mandate.bounds,
                    "fixed_allocations": mandate.fixed_allocations,
                },
                "esg_min": 1.5,
            }
        )
        system = build_constraints(constrained, blocks, config)
        row = system.a[system.esg_row_index]
        assert row.tolist() == [-1.0, -1.0, -3.0, -2.0]
        assert system.b[system.esg_row_index] == pytest.approx(-1.5)

    def test_a_weighted_average_floor_actually_excludes_a_portfolio(self, mandate, blocks, config):
        """An all-ones row could never do this, which is what made the legacy version inert."""
        constrained = Mandate(
            **{
                **{
                    "client": mandate.client, "name": mandate.name, "market": mandate.market,
                    "currency": mandate.currency, "benchmark": mandate.benchmark,
                    "max_single_position": mandate.max_single_position,
                    "horizon_years": mandate.horizon_years, "target_curve": mandate.target_curve,
                    "universe": mandate.universe, "bounds": mandate.bounds,
                    "fixed_allocations": mandate.fixed_allocations,
                },
                "esg_min": 2.5,
            }
        )
        system = build_constraints(constrained, blocks, config)
        # All weight on the two score-1 instruments gives a weighted average of 1, below the floor.
        low = np.array([0.5, 0.5, 0.0, 0.0])
        assert (system.a @ low)[system.esg_row_index] > system.b[system.esg_row_index]
        # All weight on the score-3 instrument clears it.
        high = np.array([0.0, 0.0, 1.0, 0.0])
        assert (system.a @ high)[system.esg_row_index] <= system.b[system.esg_row_index] + 1e-12


class TestRegionBlockIsLive:
    def test_all_seven_region_rows_can_carry_a_member(self, mandate, blocks, config):
        """In the reference, the region column held signal scopes, so only Europe and Others were ever
        populated (decisions.md D22). The geography column added upstream makes the block genuinely
        seven-way, and this asserts the rows are addressable."""
        system = build_constraints(mandate, blocks, config)
        region = next(b for b in system.blocks if b.dimension == "region")
        assert len(region.vocabulary) == 7
        populated = system.indicator_is_populated(region)
        # The fixture spans Switzerland, North America and Others.
        assert populated.sum() == 3
        labels = {region.vocabulary.labels[k] for k in np.flatnonzero(populated)}
        assert labels == {"Switzerland", "North America", "Others"}


class TestExposuresAndBinding:
    def test_realised_exposures_use_the_same_indicators_as_the_constraints(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        weights = np.array([0.25, 0.25, 0.25, 0.25])
        exposures = realised_exposures(weights, system)
        assert exposures["currency"]["CHF"] == pytest.approx(0.50)
        assert exposures["currency"]["USD"] == pytest.approx(0.50)
        assert exposures["role"]["Gain"] == pytest.approx(0.50)
        assert exposures["region"]["Switzerland"] == pytest.approx(0.50)

    def test_a_binding_bound_is_reported_in_the_mandate_s_own_numbers(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        # Put CHF exactly on its 0.30 floor.
        weights = np.array([0.30, 0.50, 0.0, 0.20])
        found = binding_constraints(weights, system)
        chf = [b for b in found if b.dimension == "currency" and b.category == "CHF"]
        assert chf, "the CHF floor should be reported as binding"
        assert chf[0].side == "lower"
        assert chf[0].bound == pytest.approx(0.30)
        assert chf[0].realised == pytest.approx(0.30)


class TestFeasibilityNotes:
    def test_unreachable_upper_bounds_are_reported(self, mandate, blocks, config):
        infeasible = Mandate(
            **{
                **{
                    "client": mandate.client, "name": mandate.name, "market": mandate.market,
                    "currency": mandate.currency, "benchmark": mandate.benchmark,
                    "max_single_position": mandate.max_single_position, "esg_min": mandate.esg_min,
                    "horizon_years": mandate.horizon_years, "target_curve": mandate.target_curve,
                    "universe": mandate.universe, "fixed_allocations": mandate.fixed_allocations,
                },
                "bounds": {"currency": {"CHF": Bound(0.0, 0.2), "USD": Bound(0.0, 0.2)}},
            }
        )
        system = build_constraints(infeasible, blocks, config)
        notes = system.feasibility_notes()
        assert any("cannot reach one" in note for note in notes)

    def test_a_floor_on_an_empty_category_is_reported(self, mandate, blocks, config):
        impossible = Mandate(
            **{
                **{
                    "client": mandate.client, "name": mandate.name, "market": mandate.market,
                    "currency": mandate.currency, "benchmark": mandate.benchmark,
                    "max_single_position": mandate.max_single_position, "esg_min": mandate.esg_min,
                    "horizon_years": mandate.horizon_years, "target_curve": mandate.target_curve,
                    "universe": mandate.universe, "fixed_allocations": mandate.fixed_allocations,
                },
                "bounds": {"currency": {"JPY": Bound(0.2, 1.0)}},
            }
        )
        system = build_constraints(impossible, blocks, config)
        assert any("has no instrument" in note for note in system.feasibility_notes())

    def test_a_feasible_mandate_reports_nothing(self, mandate, blocks, config):
        system = build_constraints(mandate, blocks, config)
        assert system.feasibility_notes() == []
