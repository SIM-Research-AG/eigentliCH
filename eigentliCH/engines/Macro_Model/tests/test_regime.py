"""Tests for the 25-state regime layer, section 0.8.

Five regimes, per book section 20.2, declared in cautious-to-aggressive order:
crisis, contraction, stagnation, expansion, boom.
"""

import numpy as np
import pytest

from macrofield import config as config_module
from macrofield.model.regime import (
    CRISIS_KERNEL,
    EXTREME_SCENARIOS,
    SCENARIO_ORDER,
    STATE_COUNT,
    SYMMETRIC_KERNEL,
    SYMMETRIC_KERNEL_CORRECTED,
    RegimeError,
    RegimeKernels,
    SegmentAssessment,
    build_distribution,
    to_optimizer_payload,
)

EVEN = 0.2  # an equal weight across five regimes

SEGMENT_NAMES = (
    "business_cycle",
    "investment_environment",
    "market_behaviour",
    "market_stress",
)


def segment(name: str, crisis, contraction, stagnation, expansion, boom):
    return SegmentAssessment(name, crisis, contraction, stagnation, expansion, boom)


def four_segments(crisis=EVEN, contraction=EVEN, stagnation=EVEN, expansion=EVEN, boom=EVEN):
    return [
        segment(name, crisis, contraction, stagnation, expansion, boom)
        for name in SEGMENT_NAMES
    ]


class TestScenarioVocabulary:
    def test_five_regimes_in_cautious_to_aggressive_order(self):
        assert SCENARIO_ORDER == ("crisis", "contraction", "stagnation", "expansion", "boom")

    def test_the_four_scenario_vocabulary_is_gone(self):
        """"Recovery" and "bust" belonged to the superseded four-scenario version."""
        assert "recovery" not in SCENARIO_ORDER
        assert "bust" not in SCENARIO_ORDER

    def test_only_the_two_extremes_are_asymmetric(self):
        assert set(EXTREME_SCENARIOS) == {"crisis", "boom"}

    def test_config_declares_the_same_five(self):
        assert config_module.load().get("regime.scenarios") == list(SCENARIO_ORDER)

    def test_scenario_names_match_the_five_regime_aggregation(self):
        """The point of moving to five: the segments and the regime report share one vocabulary."""
        configured = config_module.load().get("regime.five_regime_bins")
        assert {name.lower() for name in configured} == set(SCENARIO_ORDER)


class TestKernels:
    def test_every_scenario_has_a_normalised_kernel(self):
        kernels = RegimeKernels()
        for scenario in SCENARIO_ORDER:
            assert kernels.kernel_for(scenario).sum() == pytest.approx(1.0)

    def test_boom_kernel_is_the_reverse_of_the_crisis_kernel(self):
        kernels = RegimeKernels()
        assert np.allclose(kernels.kernel_for("boom"), kernels.kernel_for("crisis")[::-1])

    def test_crisis_kernel_is_piled_towards_the_cautious_end(self):
        """This is what keeps live weight on the crisis tail, as the brief requires."""
        kernel = RegimeKernels().kernel_for("crisis")
        assert kernel[0] > kernel[-1]
        assert kernel[:3].sum() > 0.4

    def test_interior_regimes_share_the_symmetric_kernel(self):
        kernels = RegimeKernels()
        interior = [kernels.kernel_for(s) for s in ("contraction", "stagnation", "expansion")]
        for kernel in interior[1:]:
            assert np.allclose(kernel, interior[0])

    def test_kernel_lengths(self):
        assert len(SYMMETRIC_KERNEL) == 14
        assert len(CRISIS_KERNEL) == 10

    def test_source_kernels_sum_to_ninety_nine_not_one_hundred(self):
        """A defect in the source values. Normalisation absorbs it; recorded so it stays visible."""
        assert sum(SYMMETRIC_KERNEL) == pytest.approx(99.0)
        assert sum(CRISIS_KERNEL) == pytest.approx(99.0)

    def test_source_central_kernel_is_not_quite_symmetric(self):
        kernel = np.asarray(SYMMETRIC_KERNEL)
        mismatches = np.flatnonzero(~np.isclose(kernel, kernel[::-1]))
        assert mismatches.size == 2
        assert {kernel[i] for i in mismatches} == {13.0, 12.0}

    def test_the_single_substitution_makes_it_symmetric_and_sum_to_one_hundred(self):
        corrected = np.asarray(SYMMETRIC_KERNEL_CORRECTED)
        assert np.allclose(corrected, corrected[::-1])
        assert corrected.sum() == pytest.approx(100.0)

    def test_crisis_kernel_folds_the_central_kernel_left_tail(self):
        assert sum(CRISIS_KERNEL[:2]) == pytest.approx(sum(SYMMETRIC_KERNEL[:6]))
        assert CRISIS_KERNEL[2:] == SYMMETRIC_KERNEL[6:]

    @pytest.mark.parametrize(
        "scenario,start,length",
        [
            ("crisis", 1, 10),
            ("contraction", 2, 14),
            ("stagnation", 6, 14),
            ("expansion", 11, 14),
            ("boom", 16, 10),
        ],
    )
    def test_placement_fits_the_axis(self, scenario, start, length):
        spread = RegimeKernels().spread(scenario, 1.0)
        support = np.flatnonzero(spread > 0.0)
        assert support[0] + 1 == start
        assert support[-1] + 1 == start + length - 1
        assert spread.sum() == pytest.approx(1.0)

    def test_every_kernel_stays_inside_the_axis(self):
        for scenario in SCENARIO_ORDER:
            assert RegimeKernels().spread(scenario, 1.0).sum() == pytest.approx(1.0)

    def test_kernel_centres_increase_across_the_regimes(self):
        """Cautious to aggressive must actually be monotone in the axis position."""
        kernels = RegimeKernels()
        states = np.arange(1, STATE_COUNT + 1)
        centres = [float((kernels.spread(s, 1.0) * states).sum()) for s in SCENARIO_ORDER]
        assert centres == sorted(centres), centres

    def test_rejects_an_unknown_scenario(self):
        with pytest.raises(RegimeError, match="unknown scenario"):
            RegimeKernels().kernel_for("recovery")

    def test_rejects_a_kernel_that_would_overrun_the_axis(self):
        kernels = RegimeKernels(
            placement={**dict(RegimeKernels().placement), "boom": 20}
        )
        with pytest.raises(RegimeError, match="would discard probability"):
            kernels.spread("boom", 1.0)

    def test_rejects_a_negative_kernel(self):
        with pytest.raises(RegimeError, match="negative weight"):
            RegimeKernels(crisis=(-1.0, 2.0)).kernel_for("crisis")

    def test_loads_from_config(self):
        kernels = RegimeKernels.from_config(config_module.load())
        assert kernels.state_count == STATE_COUNT
        assert len(kernels.symmetric) == 14
        assert len(kernels.crisis) == 10
        assert dict(kernels.placement) == {
            "crisis": 1,
            "contraction": 2,
            "stagnation": 6,
            "expansion": 11,
            "boom": 16,
        }


class TestSegmentValidation:
    def test_accepts_a_probability_vector(self):
        segment("s", 0.2, 0.2, 0.2, 0.2, 0.2).validate()

    def test_rejects_a_vector_that_does_not_sum_to_one(self):
        with pytest.raises(RegimeError, match="sum to"):
            segment("s", 0.5, 0.5, 0.5, 0.5, 0.5).validate()

    def test_rejects_negative_probability(self):
        with pytest.raises(RegimeError, match="negative probability"):
            segment("s", -0.1, 0.3, 0.3, 0.3, 0.2).validate()

    def test_from_mapping_requires_every_regime(self):
        with pytest.raises(RegimeError, match="missing scenarios"):
            SegmentAssessment.from_mapping("s", {"crisis": 0.5, "boom": 0.5})

    def test_from_mapping_accepts_all_five(self):
        assessment = SegmentAssessment.from_mapping(
            "s",
            {"crisis": 0.1, "contraction": 0.2, "stagnation": 0.3, "expansion": 0.3, "boom": 0.1},
        )
        assessment.validate()
        assert assessment.as_vector().tolist() == [0.1, 0.2, 0.3, 0.3, 0.1]

    def test_vector_order_is_cautious_to_aggressive(self):
        vector = segment("s", 1.0, 0.0, 0.0, 0.0, 0.0).as_vector()
        assert vector[0] == 1.0  # crisis first


class TestDistribution:
    def test_has_twenty_five_states_and_sums_to_one(self):
        result = build_distribution(four_segments())
        assert result.probabilities.size == STATE_COUNT
        assert result.probabilities.sum() == pytest.approx(1.0)

    @pytest.mark.parametrize("scenario", SCENARIO_ORDER)
    def test_every_regime_weight_affects_the_distribution(self, scenario):
        """No regime may be silently discarded, which is the defect the four-scenario version had."""
        baseline = build_distribution(four_segments())
        weights = {s: 0.25 if s != scenario else 0.0 for s in SCENARIO_ORDER}
        # Renormalise so the vector is still a probability vector.
        total = sum(weights.values())
        weights = {s: w / total for s, w in weights.items()}
        shifted = build_distribution(four_segments(**weights))
        assert not np.allclose(baseline.probabilities, shifted.probabilities), scenario

    def test_regimes_are_not_interchangeable(self):
        """Swapping two regimes' weights must move the distribution, since their kernels differ."""
        first = build_distribution(four_segments(contraction=0.5, expansion=0.1, stagnation=0.2, crisis=0.1, boom=0.1))
        second = build_distribution(four_segments(contraction=0.1, expansion=0.5, stagnation=0.2, crisis=0.1, boom=0.1))
        assert not np.allclose(first.probabilities, second.probabilities)

    def test_a_crisis_assessment_concentrates_on_the_cautious_end(self):
        result = build_distribution(four_segments(crisis=1.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=0.0))
        assert result.probabilities[:10].sum() == pytest.approx(1.0)
        assert result.central_state < 5.0

    def test_a_boom_assessment_concentrates_on_the_aggressive_end(self):
        result = build_distribution(four_segments(crisis=0.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=1.0))
        assert result.probabilities[15:].sum() == pytest.approx(1.0)
        assert result.central_state > 20.0

    def test_a_stagnation_assessment_concentrates_in_the_middle(self):
        """The regime the four-scenario version had no name for."""
        result = build_distribution(four_segments(crisis=0.0, contraction=0.0, stagnation=1.0, expansion=0.0, boom=0.0))
        assert 10.0 < result.central_state < 16.0
        assert result.probabilities[5:19].sum() == pytest.approx(1.0)

    def test_the_crisis_tail_stays_live_under_an_even_assessment(self):
        result = build_distribution(four_segments())
        assert result.tail_probability > 0.01
        assert not result.notes

    def test_a_thin_tail_is_reported_not_reweighted(self):
        result = build_distribution(four_segments(crisis=0.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=1.0))
        assert result.tail_probability == pytest.approx(0.0)
        assert any("crisis tail" in note for note in result.notes)
        assert result.probabilities.sum() == pytest.approx(1.0)

    def test_modal_and_central_state_are_one_based(self):
        result = build_distribution(four_segments(crisis=1.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=0.0))
        assert 1 <= result.modal_state <= STATE_COUNT
        assert 1.0 <= result.central_state <= float(STATE_COUNT)

    def test_rejects_an_empty_segment_list(self):
        with pytest.raises(RegimeError, match="at least one segment"):
            build_distribution([])

    def test_segments_are_averaged_not_summed(self):
        one = build_distribution([segment("a", 0.2, 0.2, 0.2, 0.2, 0.2)])
        two = build_distribution(
            [segment("a", 0.2, 0.2, 0.2, 0.2, 0.2), segment("b", 0.2, 0.2, 0.2, 0.2, 0.2)]
        )
        assert np.allclose(one.probabilities, two.probabilities)


class TestFiveRegimeAggregation:
    def test_aggregates_to_five_regimes_summing_to_one(self):
        result = build_distribution(four_segments())
        aggregated = result.aggregate_five_regime()
        assert set(aggregated) == {"Crisis", "Contraction", "Stagnation", "Expansion", "Boom"}
        assert sum(aggregated.values()) == pytest.approx(1.0)

    def test_a_crisis_assessment_loads_the_crisis_regime(self):
        result = build_distribution(four_segments(crisis=1.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=0.0))
        aggregated = result.aggregate_five_regime()
        assert aggregated["Crisis"] > aggregated["Boom"]
        assert max(aggregated, key=aggregated.get) == "Crisis"

    def test_a_boom_assessment_loads_the_boom_regime(self):
        result = build_distribution(four_segments(crisis=0.0, contraction=0.0, stagnation=0.0, expansion=0.0, boom=1.0))
        aggregated = result.aggregate_five_regime()
        assert max(aggregated, key=aggregated.get) == "Boom"

    def test_rejects_bins_that_leave_a_state_unassigned(self):
        result = build_distribution(four_segments())
        with pytest.raises(RegimeError, match="unassigned"):
            result.aggregate_five_regime({"Crisis": range(1, 6), "Boom": range(21, 26)})

    def test_rejects_overlapping_bins(self):
        result = build_distribution(four_segments())
        with pytest.raises(RegimeError, match="overlaps"):
            result.aggregate_five_regime(
                {
                    "Crisis": range(1, 6),
                    "Contraction": range(5, 11),
                    "Stagnation": range(11, 16),
                    "Expansion": range(16, 21),
                    "Boom": range(21, 26),
                }
            )

    def test_config_bins_partition_the_axis(self):
        configured = config_module.load().get("regime.five_regime_bins")
        bins = {name: range(lo, hi + 1) for name, (lo, hi) in configured.items()}
        covered = sorted(state for span in bins.values() for state in span)
        assert covered == list(range(1, STATE_COUNT + 1))


class TestOptimizerPayload:
    def test_payload_has_the_shape_the_optimiser_consumes(self):
        result = build_distribution(four_segments())
        payload = to_optimizer_payload("us", 2024, result)
        assert len(payload.distribution) == STATE_COUNT
        assert sum(payload.distribution) == pytest.approx(1.0)
        assert set(payload.five_regime) == {
            "Crisis",
            "Contraction",
            "Stagnation",
            "Expansion",
            "Boom",
        }
        assert payload.economy == "us"
        assert payload.period == 2024

    def test_payload_records_which_construction_produced_it(self):
        payload = to_optimizer_payload("us", 2024, build_distribution(four_segments()))
        assert "five regimes" in payload.construction
