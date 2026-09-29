"""The binding contract checks, and what they refuse.

The regime_id rule and the unit rule are the two things that stop a run producing a number whose context
is wrong. Each gets a test that the check fires, because a check that silently passes is worse than none.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pcp.contracts import (
    ContractError,
    Mandate,
    RegimeMismatchError,
    RegimeTimeline,
    ReturnSet,
    idempotency_key,
    require_classifiable,
    require_regime_match,
    require_units,
    trace_id_from,
)


class TestRegimeRule:
    def test_matching_identifiers_pass(self, returnset, regime):
        require_regime_match(returnset, regime)

    def test_a_mismatch_is_refused(self, returnset, regime):
        other = replace(regime, regime_id="REG-different")
        with pytest.raises(RegimeMismatchError, match="regime_id mismatch"):
            require_regime_match(returnset, other)

    def test_the_message_names_both_identifiers_and_the_fix(self, returnset, regime):
        other = replace(regime, regime_id="REG-different")
        with pytest.raises(RegimeMismatchError) as caught:
            require_regime_match(returnset, other)
        message = str(caught.value)
        assert "RS-test" in message
        assert "REG-test" in message
        assert "REG-different" in message
        assert "Rebuild" in message

    def test_a_state_grid_disagreement_is_refused(self, returnset, regime):
        mismatched = replace(returnset, state_grid=25)
        object.__setattr__(mismatched, "state_grid", 25)
        # Build a regime whose grid disagrees by bypassing the constructor's own check.
        broken = replace(regime)
        object.__setattr__(broken, "state_grid", 20)
        with pytest.raises(ContractError, match="state grid mismatch"):
            require_regime_match(mismatched, broken)


class TestUnitRule:
    def test_matching_units_pass(self, returnset, mandate, config):
        require_units(returnset, mandate, config)

    def test_a_percent_returnset_is_refused(self, returnset, mandate, config):
        percent = replace(returnset, values_unit="annualised_pct")
        with pytest.raises(ContractError, match="values_unit"):
            require_units(percent, mandate, config)

    def test_the_message_explains_the_consequence(self, returnset, mandate, config):
        percent = replace(returnset, values_unit="annualised_pct")
        with pytest.raises(ContractError) as caught:
            require_units(percent, mandate, config)
        assert "unit ratio" in str(caught.value)

    def test_a_horizon_disagreement_is_refused(self, returnset, mandate, config):
        ten_year = replace(returnset, horizon_years=10.0)
        with pytest.raises(ContractError, match="horizon mismatch"):
            require_units(ten_year, mandate, config)


class TestClassifiability:
    def test_a_classifiable_universe_passes(self, blocks, config):
        require_classifiable(blocks, config)

    def test_an_unknown_asset_class_is_refused(self, blocks, config):
        broken = list(blocks)
        broken[0] = replace(blocks[0], asset_class="Cryptocurrency")
        with pytest.raises(ContractError, match="cannot be classified"):
            require_classifiable(tuple(broken), config)

    def test_an_unknown_home_scenario_is_refused(self, blocks, config):
        broken = list(blocks)
        broken[0] = replace(blocks[0], home_scenario="Recovery")
        with pytest.raises(ContractError, match="cannot be classified"):
            require_classifiable(tuple(broken), config)

    def test_an_unknown_currency_is_tolerated_by_the_catch_all(self, blocks, config):
        """Currency has an `Others` slot, reproducing the reference's else-branch, so an unlisted currency
        is a category rather than a failure."""
        broken = list(blocks)
        broken[0] = replace(blocks[0], currency="SEK")
        require_classifiable(tuple(broken), config)


class TestSubset:
    def test_the_universe_order_is_preserved(self, returnset):
        chosen = returnset.subset([4, 1, 3])
        assert [b.bb_id for b in chosen] == [4, 1, 3]

    def test_a_missing_block_is_refused(self, returnset):
        with pytest.raises(Exception, match="does not contain"):
            returnset.subset([1, 99])

    def test_the_bb_matrix_rows_follow_the_universe_order(self, returnset):
        chosen = returnset.subset([3, 1])
        matrix = ReturnSet.bb_matrix(chosen)
        assert matrix.shape == (2, 25)
        assert matrix[0].tolist() == chosen[0].profile_by_state.tolist()


class TestDeterminismStamps:
    def test_the_key_is_a_pure_function_of_the_inputs(self, mandate, returnset, regime):
        first = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        second = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        assert first == second

    def test_a_different_regime_gives_a_different_key(self, mandate, returnset, regime):
        first = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        other = replace(regime, regime_id="REG-other")
        second = idempotency_key(mandate, returnset, other, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        assert first != second

    def test_a_different_target_curve_gives_a_different_key(self, mandate, returnset, regime):
        first = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        shifted = replace(mandate, target_curve=np.asarray(mandate.target_curve) + 0.01)
        second = idempotency_key(shifted, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        assert first != second

    def test_a_different_engine_version_gives_a_different_key(self, mandate, returnset, regime):
        first = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        second = idempotency_key(mandate, returnset, regime, "pcp@0.2.0", "curve", "exact", 0, {"us": 1.0})
        assert first != second

    def test_the_trace_id_is_derived_from_the_key(self, mandate, returnset, regime):
        key = idempotency_key(mandate, returnset, regime, "pcp@0.1.0", "curve", "exact", 0, {"us": 1.0})
        assert trace_id_from(key) == f"TR-{key[:16]}"
        assert trace_id_from(key) == trace_id_from(key)


class TestRegimeTimelineInvariants:
    def test_a_distribution_that_does_not_sum_to_one_is_refused(self):
        rows = np.full((2, 25), 1.0 / 25)
        rows[1] *= 0.5
        with pytest.raises(ContractError, match="sums to"):
            RegimeTimeline(
                regime_timeline_id="RTL", economy_scope="X", model_version="v", as_of="2024-12-31",
                period="M", state_grid=25, dates=("2024-11", "2024-12"), distributions=rows,
                regime_id="REG", current_state=0, phase=None, saturation_pct=None,
            )

    def test_a_negative_weight_is_refused(self):
        rows = np.full((1, 25), 1.0 / 25)
        rows[0][0] = -0.05
        rows[0][1] = 1.0 / 25 + 0.05
        with pytest.raises(ContractError, match="negative weight"):
            RegimeTimeline(
                regime_timeline_id="RTL", economy_scope="X", model_version="v", as_of="2024-12-31",
                period="M", state_grid=25, dates=("2024-12",), distributions=rows,
                regime_id="REG", current_state=0, phase=None, saturation_pct=None,
            )

    def test_the_crisis_tail_is_the_most_cautious_states(self, regime):
        tail = regime.crisis_tail(bins=5)
        assert tail == pytest.approx(float(regime.current()[:5].sum()))
        assert tail > 0.0


class TestMandateInvariants:
    def test_a_wrong_length_curve_is_refused(self, mandate):
        with pytest.raises(Exception, match="target curve"):
            replace(mandate, target_curve=np.zeros(24))

    def test_pinning_more_than_the_whole_portfolio_is_refused(self, mandate):
        with pytest.raises(Exception, match="exceeds"):
            replace(mandate, fixed_allocations={1: 0.6, 2: 0.6})

    def test_pinning_a_block_outside_the_universe_is_refused(self, mandate):
        with pytest.raises(Exception, match="not in its universe"):
            replace(mandate, fixed_allocations={99: 0.1})

    def test_an_out_of_range_max_position_is_refused(self, mandate):
        with pytest.raises(Exception, match="max_single_position"):
            replace(mandate, max_single_position=1.5)

    def test_a_bound_on_an_unknown_category_is_refused(self, mandate, config):
        broken = replace(mandate, bounds={"currency": {"Bitcoin": mandate.bounds["currency"]["CHF"]}})
        with pytest.raises(Exception, match="not in the currency vocabulary"):
            broken.bounds_for("currency", config.vocabularies.currencies)

    def test_bounds_are_returned_dense_in_vocabulary_order(self, mandate, config):
        bounds = mandate.bounds_for("currency", config.vocabularies.currencies)
        assert len(bounds) == 10
        assert bounds[0].lower == pytest.approx(0.30)   # CHF
        assert bounds[1].upper == pytest.approx(0.50)   # USD
        assert bounds[5].upper == pytest.approx(1.0)    # JPY, unmentioned
