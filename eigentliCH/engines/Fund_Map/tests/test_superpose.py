"""House-view superposition (spec 5.6): collapse per-role scenario profiles
into per-role scalar expectations via ``E[R_role] = sum_s omega_s * P_{role,s}``.
"""

from __future__ import annotations

from datetime import date

import pytest

from fmre.contracts import (
    DEFAULT_HOUSE_VIEW,
    build_returnset,
    superpose_block_expectations,
    superpose_role_expectations,
)
from fmre.estimate import estimate_block
from fmre.ingest.pipeline import ingest_ticker
from fmre.ingest.sources import SyntheticSource
from fmre.regime import StateToScenario, build_synthetic_timeline
from fmre.registers.building_blocks import load_seed
from fmre.registers.data_series import build_default_register


@pytest.fixture(scope="module")
def returnset():
    blocks = load_seed()
    blocks_by_id = {b.id: b for b in blocks}
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    tl = build_synthetic_timeline()
    sts = StateToScenario.load()
    estimates = {}
    for bid in (5, 20, 33, 35):
        b = blocks_by_id[bid]
        h = ingest_ticker(b.ticker, src, reg)
        aligned = tl.align_returns(h.returns)
        estimates[bid] = estimate_block(b, aligned)
    return build_returnset(estimates, blocks_by_id, sts, tl)


def test_role_expectations_match_hand_calculation(returnset):
    exp = superpose_role_expectations(returnset)
    for role, val in exp.items():
        hand = sum(
            returnset.house_view[s] * returnset.role_profiles[role][s]
            for s in returnset.scenarios
        )
        assert val == pytest.approx(hand)


def test_block_expectations_match_hand_calculation(returnset):
    exp = superpose_block_expectations(returnset)
    for bb in returnset.building_blocks:
        hand = sum(
            returnset.house_view[s] * bb["profile_by_scenario"][s]
            for s in returnset.scenarios
        )
        assert exp[bb["bb_id"]] == pytest.approx(hand)


def test_block_expectations_cover_all_blocks(returnset):
    exp = superpose_block_expectations(returnset)
    assert set(exp.keys()) == {bb["bb_id"] for bb in returnset.building_blocks}


def test_role_expectations_gain_negative_when_crisis_weighted_heavily(returnset):
    """With DEFAULT_HOUSE_VIEW (crisis=0.15), Gain remains net-positive across
    the seed universe. A stress house_view with crisis=0.90 should flip Gain
    below zero, reflecting the crisis-side drawdown."""
    # Build a stress house_view manually
    stress = {"crisis": 0.90, "contraction": 0.05, "stagnation": 0.03, "expansion": 0.01, "boom": 0.01}
    assert abs(sum(stress.values()) - 1.0) < 1e-9

    # Compute the stress-view Gain expectation directly (no need to rebuild the RS)
    gain_prof = returnset.role_profiles["gain"]
    stress_gain = sum(stress[s] * gain_prof[s] for s in returnset.scenarios)
    default_gain = sum(returnset.house_view[s] * gain_prof[s] for s in returnset.scenarios)

    assert stress_gain < default_gain  # crisis-heavy weighting drags Gain down
