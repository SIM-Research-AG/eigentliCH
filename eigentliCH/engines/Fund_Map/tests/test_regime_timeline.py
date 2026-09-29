"""Regime timeline contract + state-to-scenario map validation (spec 3.4, 3.2).

Every invalid path is a hard refusal, never a silent repair.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fmre.regime import (
    STATE_GRID,
    RegimeTimeline,
    StateToScenario,
    TimelineValidationError,
    build_synthetic_timeline,
    load_timeline,
    require_scope,
    timeline_to_dict,
)
from fmre.regime.timeline import timeline_from_dict


@pytest.fixture(scope="module")
def synthetic_timeline() -> RegimeTimeline:
    return build_synthetic_timeline(seed=20260728)


@pytest.fixture(scope="module")
def synthetic_dict(synthetic_timeline: RegimeTimeline) -> dict:
    return timeline_to_dict(synthetic_timeline)


# ---------------------------------------------------------------------------
# Synthetic builder
# ---------------------------------------------------------------------------


def test_synthetic_timeline_is_deterministic():
    a = build_synthetic_timeline(seed=1)
    b = build_synthetic_timeline(seed=1)
    pd.testing.assert_series_equal(a.path, b.path)


def test_synthetic_timeline_differs_across_seeds():
    a = build_synthetic_timeline(seed=1)
    b = build_synthetic_timeline(seed=2)
    assert not a.path.equals(b.path)


def test_synthetic_timeline_states_in_range(synthetic_timeline):
    vals = synthetic_timeline.path.to_numpy()
    assert vals.min() >= 0
    assert vals.max() < STATE_GRID


def test_synthetic_timeline_covers_full_window(synthetic_timeline):
    assert synthetic_timeline.path.index[0] == pd.Timestamp("1998-01-31")
    assert synthetic_timeline.path.index[-1] == pd.Timestamp("2024-12-31")


def test_synthetic_timeline_is_monthly(synthetic_timeline):
    diffs = synthetic_timeline.path.index.to_series().diff().dropna()
    assert diffs.min() >= pd.Timedelta("28D")
    assert diffs.max() <= pd.Timedelta("31D")


# ---------------------------------------------------------------------------
# Round-trip via the contract dict shape
# ---------------------------------------------------------------------------


def test_timeline_dict_roundtrip(synthetic_timeline, synthetic_dict):
    tl = timeline_from_dict(synthetic_dict)
    # check_freq=False: the DatetimeIndex freq attribute is a hint (ME vs None
    # when reconstructing from a list of dates), not part of the data payload.
    pd.testing.assert_series_equal(tl.path, synthetic_timeline.path, check_freq=False)
    assert tl.regime_timeline_id == synthetic_timeline.regime_timeline_id
    assert tl.economy_scope == synthetic_timeline.economy_scope
    assert tl.current.state == synthetic_timeline.current.state


def test_load_timeline_from_file(tmp_path, synthetic_dict):
    path = tmp_path / "timeline.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(synthetic_dict, fh)
    tl = load_timeline(path)
    assert tl.state_grid == STATE_GRID
    assert tl.n_observations == 324  # 27 years x 12 months


def test_load_timeline_missing_file_raises(tmp_path):
    with pytest.raises(TimelineValidationError, match="file not found"):
        load_timeline(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# Validation refusals
# ---------------------------------------------------------------------------


def test_reject_wrong_state_grid(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["state_grid"] = 17
    with pytest.raises(TimelineValidationError, match="state_grid must be 25"):
        timeline_from_dict(bad)


def test_reject_out_of_range_state(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["path"][0]["state"] = 99
    with pytest.raises(TimelineValidationError, match="not an int in 0..24"):
        timeline_from_dict(bad)


def test_reject_negative_state(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["path"][0]["state"] = -1
    with pytest.raises(TimelineValidationError, match="not an int in 0..24"):
        timeline_from_dict(bad)


def test_reject_duplicate_dates(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["path"][1]["date"] = bad["path"][0]["date"]
    with pytest.raises(TimelineValidationError, match="duplicate dates"):
        timeline_from_dict(bad)


def test_reject_unsorted_dates(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["path"][0], bad["path"][1] = bad["path"][1], bad["path"][0]
    with pytest.raises(TimelineValidationError, match="not monotonically increasing"):
        timeline_from_dict(bad)


def test_reject_missing_required_field(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    del bad["economy_scope"]
    with pytest.raises(TimelineValidationError, match="economy_scope"):
        timeline_from_dict(bad)


def test_reject_bad_period(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["period"] = "W"
    with pytest.raises(TimelineValidationError, match="period must be one of M/Q/A"):
        timeline_from_dict(bad)


def test_reject_bad_current_state(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["current"]["state"] = 40
    with pytest.raises(TimelineValidationError, match="current.state"):
        timeline_from_dict(bad)


def test_reject_empty_path(synthetic_dict):
    bad = copy.deepcopy(synthetic_dict)
    bad["path"] = []
    with pytest.raises(TimelineValidationError, match="path must be non-empty"):
        timeline_from_dict(bad)


# ---------------------------------------------------------------------------
# Scope refusal (spec 3.4)
# ---------------------------------------------------------------------------


def test_require_scope_passes_on_match(synthetic_timeline):
    require_scope(synthetic_timeline, "Global")


def test_require_scope_refuses_on_mismatch(synthetic_timeline):
    with pytest.raises(TimelineValidationError, match="scope mismatch"):
        require_scope(synthetic_timeline, "Europe")


# ---------------------------------------------------------------------------
# Lookup, frequencies, alignment
# ---------------------------------------------------------------------------


def test_state_at_returns_expected(synthetic_timeline):
    # Snap-to-period-end: '1998-01-15' -> 1998-01-31
    s = synthetic_timeline.state_at("1998-01-15")
    assert 0 <= s < STATE_GRID
    assert s == int(synthetic_timeline.path.iloc[0])


def test_state_at_raises_for_out_of_window(synthetic_timeline):
    with pytest.raises(KeyError):
        synthetic_timeline.state_at("1900-01-01")


def test_state_frequencies_sum_to_one_and_length_25(synthetic_timeline):
    freq = synthetic_timeline.state_frequencies()
    assert len(freq) == STATE_GRID
    assert freq.sum() == pytest.approx(1.0)
    assert (freq >= 0).all()


def test_state_frequencies_window_subset(synthetic_timeline):
    freq = synthetic_timeline.state_frequencies(window=("2020-01-01", "2020-12-31"))
    assert freq.sum() == pytest.approx(1.0)


def test_align_returns_yields_state_column(synthetic_timeline):
    # Build a monthly return series over the timeline window
    idx = pd.date_range("2020-02-29", "2020-12-31", freq="ME")
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.standard_normal(len(idx)) * 0.02, index=idx, name="return")
    aligned = synthetic_timeline.align_returns(rets)
    assert "return" in aligned.columns
    assert "state" in aligned.columns
    assert len(aligned) == len(rets)
    assert (aligned["state"] >= 0).all() and (aligned["state"] < STATE_GRID).all()


def test_align_returns_drops_returns_outside_window(synthetic_timeline):
    # Include one date after the timeline ends
    idx = pd.DatetimeIndex(["2024-11-30", "2024-12-31", "2025-01-31"])
    rets = pd.Series([0.01, -0.02, 0.03], index=idx)
    aligned = synthetic_timeline.align_returns(rets)
    assert len(aligned) == 2
    assert pd.Timestamp("2025-01-31") not in aligned.index


# ---------------------------------------------------------------------------
# State-to-scenario map
# ---------------------------------------------------------------------------


def test_state_to_scenario_load_seed():
    sts = StateToScenario.load()
    assert sts.state_grid == STATE_GRID
    assert sts.scenario_order == ("crisis", "contraction", "stagnation", "expansion", "boom")
    assert sts.scenario_of(0) == "crisis"
    assert sts.scenario_of(24) == "boom"
    assert sts.scenario_of(12) == "stagnation"


def test_state_to_scenario_states_of():
    sts = StateToScenario.load()
    crisis_states = sts.states_of("crisis")
    assert crisis_states == (0, 1, 2, 3, 4)
    boom_states = sts.states_of("boom")
    assert boom_states == (20, 21, 22, 23, 24)


def test_state_to_scenario_rejects_missing_state(tmp_path: Path):
    bad = {
        "version": "sts@bad",
        "state_grid": 25,
        "scenario_order": ["crisis", "contraction", "stagnation", "expansion", "boom"],
        "state_to_scenario": {str(i): "crisis" for i in range(24)},  # missing state 24
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TimelineValidationError, match="exactly 0..24"):
        StateToScenario.load(p)


def test_state_to_scenario_rejects_non_monotone(tmp_path: Path):
    scenario_order = ["crisis", "contraction", "stagnation", "expansion", "boom"]
    mapping = {}
    for i in range(25):
        mapping[str(i)] = "crisis" if i < 5 else "stagnation" if i < 10 else "contraction" if i < 15 else "expansion" if i < 20 else "boom"
    bad = {
        "version": "sts@bad",
        "state_grid": 25,
        "scenario_order": scenario_order,
        "state_to_scenario": mapping,
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TimelineValidationError, match="ordering breaks"):
        StateToScenario.load(p)


def test_state_to_scenario_rejects_unused_scenario(tmp_path: Path):
    scenario_order = ["crisis", "contraction", "stagnation", "expansion", "boom"]
    mapping = {str(i): "stagnation" for i in range(25)}
    bad = {
        "version": "sts@bad",
        "state_grid": 25,
        "scenario_order": scenario_order,
        "state_to_scenario": mapping,
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TimelineValidationError, match="unused scenarios"):
        StateToScenario.load(p)


# ---------------------------------------------------------------------------
# Integration: ingest -> align -> state-tagged returns
# ---------------------------------------------------------------------------


def test_ingest_align_returns_by_state(synthetic_timeline):
    """End-to-end sanity: harmonised returns from the SyntheticSource can be
    aligned against the SyntheticRegimeTimeline and yield 5 scenario buckets."""
    from fmre.ingest.sources import SyntheticSource
    from fmre.ingest.pipeline import ingest_ticker
    from fmre.registers.building_blocks import load_seed
    from fmre.registers.data_series import build_default_register

    blocks = load_seed()
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    h = ingest_ticker("MXUS Index", src, reg)
    assert h.returns is not None
    aligned = synthetic_timeline.align_returns(h.returns)
    # Every return should have a state, and states span most of 0..24
    assert len(aligned) == len(h.returns)
    n_states_seen = aligned["state"].nunique()
    assert n_states_seen >= 5  # synthetic random walk visits at least the mid-band
