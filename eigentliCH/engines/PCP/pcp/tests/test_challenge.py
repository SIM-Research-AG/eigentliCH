"""The portfolio challenge: admissibility, comparability, and the refusal to invent a profile."""

from __future__ import annotations

import numpy as np
import pytest

from pcp.model.challenge import (
    ChallengeError,
    challenge,
    equal_weight_proposal,
    load_proposal,
    normalise_proposal,
)


@pytest.fixture
def optimised(mandate, blocks):
    """A compliant reference allocation.

    Blocks 1 and 3 are CHF, blocks 2 and 4 are USD, and block 4 is the only Protection holding. So this
    gives CHF 0.55 (inside [0.30, 0.70]), USD 0.45 (inside [0, 0.50]), Protection 0.10 (inside
    [0.05, 0.20]), and a largest position of 0.40 against the 0.50 cap.
    """
    return {1: 0.40, 2: 0.35, 3: 0.15, 4: 0.10}


def _run(proposal, mandate, returnset, optimised, regime, config):
    return challenge(
        proposal, mandate, returnset, optimised, list(optimised),
        regime.current(), config,
    )


class TestAdmissibility:
    def test_a_compliant_proposal_is_admissible(self, mandate, returnset, optimised, regime, config):
        result = _run(dict(optimised), mandate, returnset, optimised, regime, config)
        assert result.admissible
        assert result.breaches == ()

    def test_a_breached_upper_bound_is_reported(self, mandate, returnset, optimised, regime, config):
        # USD to 0.90, above its 0.50 ceiling. CHF then falls below its 0.30 floor as well.
        proposal = {1: 0.05, 2: 0.85, 3: 0.05, 4: 0.05}
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        assert not result.admissible
        usd = [b for b in result.breaches if b.dimension == "currency" and b.category == "USD"]
        assert usd and usd[0].side == "upper"
        assert usd[0].limit == pytest.approx(0.50)

    def test_a_breached_lower_bound_is_reported(self, mandate, returnset, optimised, regime, config):
        proposal = {1: 0.05, 2: 0.80, 3: 0.05, 4: 0.10}
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        chf = [b for b in result.breaches if b.dimension == "currency" and b.category == "CHF"]
        assert chf and chf[0].side == "lower"

    def test_the_position_cap_is_checked(self, mandate, returnset, optimised, regime, config):
        # Block 1 to 0.60, above the 0.50 cap.
        proposal = {1: 0.60, 2: 0.30, 3: 0.0, 4: 0.10}
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        assert any(b.kind == "position" for b in result.breaches)

    def test_a_short_is_a_breach(self, mandate, returnset, optimised, regime, config):
        proposal = {1: 0.60, 2: 0.50, 3: 0.0, 4: -0.10}
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        assert any(b.kind == "position" and b.side == "lower" for b in result.breaches)
        assert any("negative weight" in note for note in result.notes)

    def test_a_budget_failure_is_a_breach(self, mandate, returnset, optimised, regime, config):
        proposal = {1: 0.30, 2: 0.30, 3: 0.05, 4: 0.05}   # sums to 0.70
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        assert any(b.kind == "budget" for b in result.breaches)

    def test_breaches_are_ordered_largest_first(self, mandate, returnset, optimised, regime, config):
        proposal = {1: 0.02, 2: 0.90, 3: 0.03, 4: 0.05}
        result = _run(proposal, mandate, returnset, optimised, regime, config)
        sizes = [b.size for b in result.breaches]
        assert sizes == sorted(sizes, reverse=True)

    def test_the_esg_floor_is_checked(self, mandate, returnset, optimised, regime, config):
        from dataclasses import replace

        strict = replace(mandate, esg_min=2.5)
        # Blocks 1 and 2 score 1, so a portfolio of those two averages 1, below 2.5.
        proposal = {1: 0.40, 2: 0.50, 3: 0.0, 4: 0.10}
        result = challenge(
            proposal, strict, returnset, optimised, list(optimised), regime.current(), config
        )
        assert any(b.kind == "esg" for b in result.breaches)


class TestComparability:
    def test_both_sides_are_scored_on_the_same_universe(self, mandate, returnset, optimised, regime, config):
        result = _run(dict(optimised), mandate, returnset, optimised, regime, config)
        assert len(result.proposed.weights) == len(result.optimised.weights) == len(result.universe)

    def test_an_identical_proposal_scores_identically(self, mandate, returnset, optimised, regime, config):
        result = _run(dict(optimised), mandate, returnset, optimised, regime, config)
        assert result.objective_gap == pytest.approx(0.0, abs=1e-12)
        assert result.objective_ratio == pytest.approx(1.0)

    def test_an_instrument_outside_the_universe_is_scored_and_flagged(
        self, mandate, returnset, optimised, regime, config
    ):
        from dataclasses import replace

        narrow = replace(mandate, universe=(1, 2, 3), bounds=mandate.bounds, fixed_allocations={})
        proposal = {1: 0.30, 2: 0.50, 3: 0.10, 4: 0.10}   # block 4 is outside
        result = challenge(
            proposal, narrow, returnset, {1: 0.4, 2: 0.5, 3: 0.1}, [1, 2, 3],
            regime.current(), config,
        )
        assert result.outside_universe == (4,)
        assert any(b.kind == "universe" for b in result.breaches)
        # Still scored, so the comparison is complete.
        assert len(result.universe) == 4

    def test_an_unknown_instrument_is_refused_rather_than_dropped(
        self, mandate, returnset, optimised, regime, config
    ):
        with pytest.raises(ChallengeError, match="no profile for"):
            _run({1: 0.5, 999: 0.5}, mandate, returnset, optimised, regime, config)

    def test_the_ratio_is_none_when_the_optimum_is_zero(self, mandate, returnset, regime, config):
        """A meaningless number is not reported in place of saying the optimum is zero."""
        from dataclasses import replace

        # A target curve far below anything achievable downward means no shortfall at all.
        reachable = replace(mandate, target_curve=np.full(25, -10.0))
        result = challenge(
            {1: 0.30, 2: 0.50, 3: 0.10, 4: 0.10}, reachable, returnset,
            {1: 0.30, 2: 0.50, 3: 0.10, 4: 0.10}, [1, 2, 3, 4], regime.current(), config,
        )
        assert result.optimised.objective_value == pytest.approx(0.0)
        assert result.objective_ratio is None


class TestDiagnostics:
    def test_weight_differences_are_ordered_by_magnitude(self, mandate, returnset, optimised, regime, config):
        result = _run({1: 0.50, 2: 0.30, 3: 0.10, 4: 0.10}, mandate, returnset, optimised, regime, config)
        diffs = [abs(row["difference"]) for row in result.weight_differences()]
        assert diffs == sorted(diffs, reverse=True)

    def test_exposure_differences_cover_both_sides(self, mandate, returnset, optimised, regime, config):
        result = _run({1: 0.50, 2: 0.30, 3: 0.10, 4: 0.10}, mandate, returnset, optimised, regime, config)
        currency = result.exposure_differences()["currency"]
        # Proposed holds CHF in blocks 1 and 3: 0.50 + 0.10. Optimised holds 0.40 + 0.15.
        assert currency["CHF"]["proposed"] == pytest.approx(0.60)
        assert currency["CHF"]["optimised"] == pytest.approx(0.55)
        assert currency["CHF"]["difference"] == pytest.approx(0.05)

    def test_worst_states_are_reported_only_where_there_is_a_gap(
        self, mandate, returnset, optimised, regime, config
    ):
        identical = _run(dict(optimised), mandate, returnset, optimised, regime, config)
        assert identical.worst_states() == []

    def test_role_allocation_is_reported_for_both_sides(self, mandate, returnset, optimised, regime, config):
        result = _run({1: 0.50, 2: 0.30, 3: 0.10, 4: 0.10}, mandate, returnset, optimised, regime, config)
        assert sum(result.proposed.role_allocation.values()) == pytest.approx(1.0)
        assert sum(result.optimised.role_allocation.values()) == pytest.approx(1.0)


class TestProposalReading:
    def test_percentages_are_converted_and_noted(self):
        weights, notes = normalise_proposal({1: 60.0, 2: 40.0})
        assert weights == {1: pytest.approx(0.6), 2: pytest.approx(0.4)}
        assert notes and "percentages" in notes[0]

    def test_fractions_are_left_alone(self):
        weights, notes = normalise_proposal({1: 0.6, 2: 0.4})
        assert weights == {1: 0.6, 2: 0.4}
        assert notes == []

    def test_yaml_is_read(self, tmp_path):
        target = tmp_path / "p.yaml"
        target.write_text("weights:\n  1: 0.5\n  3: 0.5\n", encoding="utf-8")
        assert load_proposal(target) == {1: 0.5, 3: 0.5}

    def test_a_bare_mapping_is_read(self, tmp_path):
        target = tmp_path / "p.yaml"
        target.write_text("1: 0.5\n3: 0.5\n", encoding="utf-8")
        assert load_proposal(target) == {1: 0.5, 3: 0.5}

    def test_json_is_read(self, tmp_path):
        target = tmp_path / "p.json"
        target.write_text('{"weights": {"1": 0.25, "4": 0.75}}', encoding="utf-8")
        assert load_proposal(target) == {1: 0.25, 4: 0.75}

    def test_csv_is_read(self, tmp_path):
        target = tmp_path / "p.csv"
        target.write_text("bb_id,weight\n1,0.4\n2,0.6\n", encoding="utf-8")
        assert load_proposal(target) == {1: 0.4, 2: 0.6}

    def test_a_missing_file_is_refused(self, tmp_path):
        with pytest.raises(ChallengeError, match="not found"):
            load_proposal(tmp_path / "absent.yaml")

    def test_an_empty_proposal_is_refused(self, tmp_path):
        target = tmp_path / "p.yaml"
        target.write_text("weights: {}\n", encoding="utf-8")
        with pytest.raises(ChallengeError, match="no weights"):
            load_proposal(target)

    def test_the_equal_weight_reference_covers_the_universe(self, mandate):
        proposal = equal_weight_proposal(mandate)
        assert set(proposal) == set(mandate.universe)
        assert sum(proposal.values()) == pytest.approx(1.0)


class TestUniverseSizeEffect:
    def test_a_zero_weight_holding_still_costs_shortfall(self, mandate, returnset, regime, config):
        """D28, asserted so the property is not mistaken for a bug later.

        The shortfall is summed over instruments before squaring, so an instrument at zero weight
        contributes its full target to every state. The objective therefore carries a floor set by the
        universe size, and values are comparable only within one universe.
        """
        from pcp.contracts import ReturnSet
        from pcp.model.objective import curve_objective

        wide = ReturnSet.bb_matrix(returnset.subset([1, 2, 3, 4]))
        narrow = ReturnSet.bb_matrix(returnset.subset([1]))
        c, m = np.asarray(mandate.target_curve), regime.current()

        # The same single position, held in a wide universe and in a narrow one.
        wide_value = curve_objective(np.array([1.0, 0.0, 0.0, 0.0]), wide, c, m)
        narrow_value = curve_objective(np.array([1.0]), narrow, c, m)
        assert wide_value > narrow_value
