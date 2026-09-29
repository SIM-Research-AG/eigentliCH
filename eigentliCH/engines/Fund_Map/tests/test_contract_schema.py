"""ReturnSet contract schema — spec section 8, test 7.

Every emitted ReturnSet validates against the schema. No mu, sigma, or
covariance fields appear anywhere. regime_id and state_to_scenario are
present and internally consistent.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from fmre.contracts import (
    CANONICAL_ROLES,
    DEFAULT_HOUSE_VIEW,
    ReturnSet,
    ReturnSetValidationError,
    build_returnset,
    load_returnset,
    to_canonical_json,
    validate_returnset,
    write_returnset,
)
from fmre.estimate import BlockEstimate, StateEstimate, estimate_block
from fmre.ingest.pipeline import ingest_ticker
from fmre.ingest.sources import SyntheticSource
from fmre.regime import STATE_GRID, StateToScenario, build_synthetic_timeline
from fmre.registers.building_blocks import load_seed
from fmre.registers.data_series import build_default_register


@pytest.fixture(scope="module")
def env():
    blocks = load_seed()
    blocks_by_id = {b.id: b for b in blocks}
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    tl = build_synthetic_timeline(seed=20260728)
    sts = StateToScenario.load()

    # Estimate a small representative set: one block from each canonical role
    ids = [5, 20, 33, 35]  # US Eq (Gain), Global Bonds (Income), Gold (Protection), USD Cash (Protection)
    estimates: dict[int, BlockEstimate] = {}
    for bid in ids:
        b = blocks_by_id[bid]
        h = ingest_ticker(b.ticker, src, reg)
        aligned = tl.align_returns(h.returns)
        estimates[bid] = estimate_block(b, aligned, calibration_window=("1998-01", "2024-12"))
    return blocks_by_id, sts, tl, estimates


@pytest.fixture(scope="module")
def returnset(env):
    blocks_by_id, sts, tl, estimates = env
    return build_returnset(
        estimates=estimates,
        blocks_by_id=blocks_by_id,
        state_to_scenario=sts,
        timeline=tl,
        calibration_window=("1998-01", "2024-12"),
    )


# ---------------------------------------------------------------------------
# Structural correctness
# ---------------------------------------------------------------------------


def test_returnset_has_required_top_level_fields(returnset):
    payload = returnset.to_dict()
    validate_returnset(payload)  # will raise on any missing


def test_returnset_state_grid_is_25(returnset):
    assert returnset.state_grid == STATE_GRID


def test_returnset_state_to_scenario_partitions_25_states(returnset):
    keys = sorted(int(k) for k in returnset.state_to_scenario.keys())
    assert keys == list(range(25))
    scenarios = set(returnset.state_to_scenario.values())
    assert scenarios == {"crisis", "contraction", "stagnation", "expansion", "boom"}


def test_returnset_house_view_sums_to_one_with_nonzero_tail(returnset):
    total = sum(returnset.house_view.values())
    assert abs(total - 1.0) < 1e-9
    assert returnset.house_view["crisis"] > 0


def test_returnset_scenarios_matches_state_to_scenario_map(returnset):
    assert set(returnset.scenarios) == set(returnset.state_to_scenario.values())


def test_returnset_regime_id_matches_timeline(env, returnset):
    _, _, tl, _ = env
    assert returnset.regime_id == tl.current.regime_id


def test_returnset_versions_stamped(returnset):
    assert returnset.model_version.startswith("re@")
    assert returnset.universe_version.startswith("fm@")
    assert returnset.state_to_scenario_version.startswith("sts@")


def test_returnset_building_blocks_have_length_25_profile(returnset):
    for bb in returnset.building_blocks:
        assert len(bb["profile_by_state"]) == 25
        assert set(bb["profile_by_scenario"].keys()) == {"crisis", "contraction", "stagnation", "expansion", "boom"}


def test_returnset_building_blocks_use_canonical_role_names(returnset):
    for bb in returnset.building_blocks:
        assert bb["role"] in CANONICAL_ROLES


def test_returnset_role_profiles_contain_all_declared_roles(env, returnset):
    _, _, _, estimates = env
    declared_roles = {est.canonical_role.lower() for est in estimates.values()}
    assert set(returnset.role_profiles.keys()) == declared_roles


def test_returnset_estimation_block_labels_are_model_derived(returnset):
    for bb in returnset.building_blocks:
        assert bb["estimation"]["label"] == "model-derived"


def test_returnset_estimation_carries_methods_and_n_obs_per_state(returnset):
    for bb in returnset.building_blocks:
        est = bb["estimation"]
        assert len(est["methods_by_state"]) == 25
        assert len(est["n_obs_by_state"]) == 25
        assert est["coverage"] in ("full", "partial", "borrowed", "seed")


def test_returnset_values_unit_is_annualised_decimal(returnset):
    assert returnset.values_unit == "annualised_decimal"
    # Sanity: seed values (percent) divided by 100 -> decimals in a plausible range
    # US Eq boom = 16 percent = 0.16 decimal
    us_eq = next(bb for bb in returnset.building_blocks if bb["bb_id"] == 5)
    boom_val = us_eq["profile_by_state"][24]  # crisis-at-0, boom-at-24
    assert 0.05 < boom_val < 0.25


# ---------------------------------------------------------------------------
# No-moments guard (spec 3.5 rule)
# ---------------------------------------------------------------------------


def test_returnset_contains_no_moment_keys(returnset):
    payload = returnset.to_dict()

    def _search(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in {"mu", "sigma", "cov", "covariance", "variance"}, (
                    f"forbidden moment key {k!r} at {path}"
                )
                _search(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _search(v, f"{path}[{i}]")

    _search(payload)


def test_validate_rejects_payload_with_mu_key(returnset):
    payload = returnset.to_dict()
    payload["building_blocks"][0]["mu"] = 0.05  # inject a forbidden key
    with pytest.raises(ReturnSetValidationError, match="forbidden moment key 'mu'"):
        validate_returnset(payload)


def test_validate_rejects_payload_with_sigma_key(returnset):
    payload = returnset.to_dict()
    payload["sigma"] = 0.15
    with pytest.raises(ReturnSetValidationError, match="forbidden moment key 'sigma'"):
        validate_returnset(payload)


def test_validate_rejects_payload_with_covariance_key(returnset):
    payload = returnset.to_dict()
    payload["provenance"]["covariance"] = [[1, 0], [0, 1]]
    with pytest.raises(ReturnSetValidationError, match="forbidden moment key 'covariance'"):
        validate_returnset(payload)


# ---------------------------------------------------------------------------
# Schema refusals
# ---------------------------------------------------------------------------


def test_validate_rejects_missing_required_field(returnset):
    payload = returnset.to_dict()
    del payload["regime_id"]
    with pytest.raises(ReturnSetValidationError, match="missing required top-level fields"):
        validate_returnset(payload)


def test_validate_rejects_wrong_state_grid(returnset):
    payload = returnset.to_dict()
    payload["state_grid"] = 17
    with pytest.raises(ReturnSetValidationError, match="state_grid must be 25"):
        validate_returnset(payload)


def test_validate_rejects_bad_state_to_scenario_keys(returnset):
    payload = returnset.to_dict()
    del payload["state_to_scenario"]["24"]
    with pytest.raises(ReturnSetValidationError, match="exactly 0..24"):
        validate_returnset(payload)


def test_validate_rejects_house_view_not_summing_to_one(returnset):
    payload = returnset.to_dict()
    payload["house_view"]["crisis"] = 0.99
    with pytest.raises(ReturnSetValidationError, match="sum to 1"):
        validate_returnset(payload)


def test_validate_rejects_zero_crisis_house_view(returnset):
    payload = returnset.to_dict()
    payload["house_view"]["crisis"] = 0.0
    payload["house_view"]["expansion"] = 0.45  # rebalance to keep sum at 1
    with pytest.raises(ReturnSetValidationError, match="crisis weight must be > 0"):
        validate_returnset(payload)


def test_validate_rejects_non_canonical_role_in_block(returnset):
    payload = returnset.to_dict()
    payload["building_blocks"][0]["role"] = "growth"  # US spelling / non-canonical
    with pytest.raises(ReturnSetValidationError, match="not canonical"):
        validate_returnset(payload)


def test_validate_rejects_missing_estimation_label(returnset):
    payload = returnset.to_dict()
    payload["building_blocks"][0]["estimation"]["label"] = "forecast"  # forbidden by house rules
    with pytest.raises(ReturnSetValidationError, match="'model-derived'"):
        validate_returnset(payload)


def test_validate_rejects_wrong_profile_length(returnset):
    payload = returnset.to_dict()
    payload["building_blocks"][0]["profile_by_state"] = [0.0] * 20
    with pytest.raises(ReturnSetValidationError, match="expected 25"):
        validate_returnset(payload)


# ---------------------------------------------------------------------------
# House view build-time refusals
# ---------------------------------------------------------------------------


def test_build_rejects_house_view_missing_scenario(env):
    blocks_by_id, sts, tl, estimates = env
    bad_hv = {k: v for k, v in DEFAULT_HOUSE_VIEW.items() if k != "boom"}
    with pytest.raises(ReturnSetValidationError, match="missing scenarios"):
        build_returnset(estimates, blocks_by_id, sts, tl, house_view=bad_hv)


def test_build_rejects_house_view_with_negative_weight(env):
    blocks_by_id, sts, tl, estimates = env
    bad_hv = dict(DEFAULT_HOUSE_VIEW)
    bad_hv["crisis"] = -0.1
    bad_hv["expansion"] = 0.55
    with pytest.raises(ReturnSetValidationError, match="negative"):
        build_returnset(estimates, blocks_by_id, sts, tl, house_view=bad_hv)


# ---------------------------------------------------------------------------
# Round-trip through disk
# ---------------------------------------------------------------------------


def test_returnset_write_and_load_roundtrip(tmp_path: Path, returnset):
    path = tmp_path / "rs.json"
    write_returnset(returnset, path)
    payload = load_returnset(path)  # validates
    assert payload["return_set_id"] == returnset.return_set_id
    assert payload["state_grid"] == 25
