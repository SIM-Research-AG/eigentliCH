"""Coverage matrix and resilience — spec section 8, test 6.

An equities-and-credit-only book scores ``R < 0`` (crisis / contraction
columns empty); a diversified book scores ``R >= 0``. Reproduces the
Roles and Scenarios worked example on the seed values.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fmre.estimate import (
    BlockEstimate,
    StateEstimate,
    build_coverage_matrix,
    portfolio_scenario_return,
    resilience,
)
from fmre.regime import STATE_GRID, StateToScenario
from fmre.registers.building_blocks import load_seed


def _estimate_from_seed(block) -> BlockEstimate:
    """Wrap a seed BuildingBlock's ret_distribution as a BlockEstimate with
    every state labelled ``seed`` (annualised percent by convention).
    """
    states = tuple(
        StateEstimate(state=i, mu=float(block.ret_distribution[i]), sigma=None, n_obs=0, method="seed")
        for i in range(STATE_GRID)
    )
    return BlockEstimate(
        block_id=block.id, ticker=block.ticker, canonical_role=block.canonical_role.value,
        region=block.region.value, states=states,
    )


@pytest.fixture(scope="module")
def blocks_by_id():
    return {b.id: b for b in load_seed()}


@pytest.fixture(scope="module")
def estimates(blocks_by_id):
    # Four representative blocks across all four canonical roles
    ids = [5, 20, 33, 35]  # US Equities, Global Bonds, Gold, USD Cash
    return {bid: _estimate_from_seed(blocks_by_id[bid]) for bid in ids}


@pytest.fixture(scope="module")
def sts():
    return StateToScenario.load()


@pytest.fixture(scope="module")
def mandate():
    """A plausible multi-scenario mandate in annualised percent."""
    return {
        "crisis": -10.0,
        "contraction": -3.0,
        "stagnation": 1.0,
        "expansion": 3.0,
        "boom": 5.0,
    }


# ---------------------------------------------------------------------------
# Coverage matrix P_{b,s}
# ---------------------------------------------------------------------------


def test_coverage_matrix_shape_and_columns(estimates, sts):
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    assert list(matrix.columns) == list(sts.scenario_order)
    assert sorted(matrix.index.tolist()) == sorted(estimates.keys())
    # US Equities (id=5) crisis under uniform weighting: mean(-40,-30,-22,-17,-12) = -24.2
    assert matrix.loc[5, "crisis"] == pytest.approx(-24.2)
    # Gold (id=33) crisis: mean(50,40,33,28,25) = 35.2
    assert matrix.loc[33, "crisis"] == pytest.approx(35.2)
    # USD Cash (id=35) crisis: mean(0,0,0,0,0) = 0
    assert matrix.loc[35, "crisis"] == pytest.approx(0.0)


def test_portfolio_scenario_return_sums_weighted(estimates, sts):
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    # 100% US Equities
    r_p = portfolio_scenario_return({5: 1.0, 20: 0.0, 33: 0.0, 35: 0.0}, matrix)
    for scen in sts.scenario_order:
        assert r_p[scen] == pytest.approx(matrix.loc[5, scen])


def test_portfolio_scenario_return_handles_missing_weights(estimates, sts):
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    # Only supply weight for id=5; others default to 0
    r_p = portfolio_scenario_return({5: 1.0}, matrix)
    for scen in sts.scenario_order:
        assert r_p[scen] == pytest.approx(matrix.loc[5, scen])


# ---------------------------------------------------------------------------
# Resilience — spec 8.6 pass/fail scenario
# ---------------------------------------------------------------------------


def test_equities_only_book_fails_on_crisis(estimates, sts, mandate):
    """An equities-and-credit-only book fails the crisis and contraction
    columns of the mandate."""
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 0.6, 20: 0.4, 33: 0.0, 35: 0.0}   # 60% US Eq + 40% Global Bonds
    report = resilience(weights, matrix, mandate)

    assert not report.passes
    assert report.resilience < 0
    assert report.failing_scenario == "crisis"
    # Sanity: crisis and contraction are the failing columns; stagnation+ pass
    assert report.margins["crisis"] < 0
    # boom, expansion, stagnation should be positive or zero
    assert report.margins["boom"] > 0
    assert report.margins["expansion"] > 0


def test_diversified_book_passes_all_scenarios(estimates, sts, mandate):
    """A diversified book with meaningful Protection and Cash allocations
    clears every mandate column."""
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 0.30, 20: 0.20, 33: 0.30, 35: 0.20}  # Growth / Income / Protection / Cash
    report = resilience(weights, matrix, mandate)

    assert report.passes, f"expected resilience >= 0, got {report.resilience} on {report.margins}"
    assert report.resilience >= 0
    assert report.failing_scenario is None
    for scen in sts.scenario_order:
        assert report.margins[scen] >= 0, (
            f"scenario {scen}: R_P={report.r_p_by_scenario[scen]:.2f} "
            f"< mandate {report.r_e_by_scenario[scen]:.2f}"
        )


def test_resilience_is_min_margin(estimates, sts, mandate):
    """R = min_s (R_P^s - R_E^s), by construction."""
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 0.5, 20: 0.5, 33: 0.0, 35: 0.0}
    report = resilience(weights, matrix, mandate)
    assert report.resilience == pytest.approx(min(report.margins.values()))


def test_resilience_reports_failing_scenario_at_the_min(estimates, sts, mandate):
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 1.0, 20: 0.0, 33: 0.0, 35: 0.0}
    report = resilience(weights, matrix, mandate)
    assert report.failing_scenario == min(report.margins, key=report.margins.get)


def test_resilience_rejects_missing_mandate_scenarios(estimates, sts, mandate):
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 1.0}
    bad_mandate = {k: v for k, v in mandate.items() if k != "crisis"}
    with pytest.raises(ValueError, match="mandate missing scenarios"):
        resilience(weights, matrix, bad_mandate)


def test_resilience_worked_example_matches_hand_calculation(estimates, sts):
    """Spot-check one scenario column against the hand calculation to catch
    silent unit errors."""
    matrix = build_coverage_matrix(estimates, sts, state_frequencies=None)
    weights = {5: 0.30, 20: 0.20, 33: 0.30, 35: 0.20}
    r_p = portfolio_scenario_return(weights, matrix)
    expected_crisis = (
        0.30 * matrix.loc[5, "crisis"]
        + 0.20 * matrix.loc[20, "crisis"]
        + 0.30 * matrix.loc[33, "crisis"]
        + 0.20 * matrix.loc[35, "crisis"]
    )
    assert r_p["crisis"] == pytest.approx(expected_crisis)
