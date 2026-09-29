"""Per-state estimation + fallbacks (spec 5.1, 5.2, 5.3).

The core invariants: no observations lost when bucketing, threshold rules on
n_obs, PCHIP interpolation is monotone-preserving, borrow uses role-and-region
peers, seed is the last resort, coverage grade reflects the worst method used.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from fmre.estimate import (
    BlockEstimate,
    StateEstimate,
    bucket_returns_by_state,
    estimate_block,
    estimate_per_state_from_buckets,
)
from fmre.estimate.fallbacks import (
    borrow_from_peers,
    interpolate_missing_states,
    seed_fallback,
)
from fmre.estimate.per_state import (
    N_MIN_DEFAULT,
    annualise_estimate,
    estimate_state_from_bucket,
)
from fmre.ingest.pipeline import ingest_ticker
from fmre.ingest.sources import SyntheticSource
from fmre.regime import STATE_GRID, build_synthetic_timeline
from fmre.registers.building_blocks import Role, load_seed
from fmre.registers.data_series import build_default_register


# ---------------------------------------------------------------------------
# Bucketing invariants (spec 8, test 3)
# ---------------------------------------------------------------------------


def test_bucketing_no_drop_no_double_count():
    rng = np.random.default_rng(0)
    n = 500
    rets = rng.standard_normal(n) * 0.02
    states = rng.integers(0, STATE_GRID, size=n)
    df = pd.DataFrame({"return": rets, "state": states})
    buckets = bucket_returns_by_state(df)
    total = sum(v.size for v in buckets.values())
    assert total == n
    # Concatenate and match set
    all_returns = np.concatenate([buckets[s] for s in sorted(buckets)])
    assert np.allclose(np.sort(all_returns), np.sort(rets))


def test_bucketing_rejects_out_of_range_state():
    df = pd.DataFrame({"return": [0.1, 0.2], "state": [0, 30]})
    with pytest.raises(ValueError, match="states outside"):
        bucket_returns_by_state(df)


def test_bucketing_rejects_missing_columns():
    with pytest.raises(ValueError, match="expected columns"):
        bucket_returns_by_state(pd.DataFrame({"foo": [1, 2]}))


# ---------------------------------------------------------------------------
# Per-state estimator (spec 5.2)
# ---------------------------------------------------------------------------


def test_estimate_full_bucket_uses_plain_mean():
    rng = np.random.default_rng(42)
    bucket = rng.normal(0.03, 0.01, size=50)
    est = estimate_state_from_bucket(10, bucket)
    assert est is not None
    assert est.method == "data-driven"
    assert est.mu == pytest.approx(float(bucket.mean()))
    assert est.n_obs == 50


def test_estimate_small_bucket_uses_trimmed_mean():
    rng = np.random.default_rng(42)
    bucket = rng.normal(0.02, 0.01, size=10)
    est = estimate_state_from_bucket(10, bucket)
    assert est is not None
    assert est.method == "data-driven-trimmed"
    assert est.n_obs == 10
    # Trimmed mean differs from raw mean by a small amount for a small sample
    assert est.mu != float(bucket.mean())


def test_estimate_thin_bucket_returns_none():
    bucket = np.array([0.01, 0.02, 0.03])  # n=3, below n_min=6
    est = estimate_state_from_bucket(5, bucket)
    assert est is None


def test_estimator_drops_thin_buckets():
    buckets = {
        0: np.array([0.01, 0.02]),                     # n=2, below floor
        5: np.random.default_rng(0).normal(size=30),   # n=30, keeps
        10: np.random.default_rng(1).normal(size=8),   # n=8, keeps (trimmed)
    }
    out = estimate_per_state_from_buckets(buckets)
    assert 0 not in out
    assert 5 in out and out[5].method == "data-driven"
    assert 10 in out and out[10].method == "data-driven-trimmed"


# ---------------------------------------------------------------------------
# PCHIP interpolation (spec 5.3)
# ---------------------------------------------------------------------------


def test_interpolation_fills_gaps_between_known_states():
    # Simulate an ascending Growth-like profile with gaps
    known_states = [0, 4, 8, 12, 16, 20, 24]
    mus = [-30.0, -10.0, -2.0, 2.0, 6.0, 10.0, 15.0]
    ests = {
        s: StateEstimate(state=s, mu=mu, sigma=1.0, n_obs=30, method="data-driven")
        for s, mu in zip(known_states, mus)
    }
    filled = interpolate_missing_states(ests, state_grid=STATE_GRID)
    assert len(filled) == STATE_GRID
    for s in known_states:
        assert filled[s].method == "data-driven"
    for s in [1, 2, 3, 5, 6, 7, 9, 11, 13, 15]:
        assert filled[s].method == "interpolated"
        assert filled[s].n_obs == 0
        assert filled[s].sigma is None


def test_interpolation_preserves_monotonicity_for_ascending_profile():
    known_states = [0, 5, 10, 15, 20, 24]
    mus = [-40.0, -10.0, 0.0, 4.0, 10.0, 16.0]  # strictly ascending
    ests = {
        s: StateEstimate(state=s, mu=mu, sigma=1.0, n_obs=30, method="data-driven")
        for s, mu in zip(known_states, mus)
    }
    filled = interpolate_missing_states(ests, state_grid=STATE_GRID)
    profile = [filled[s].mu for s in range(STATE_GRID)]
    diffs = np.diff(profile)
    assert (diffs >= -1e-9).all(), f"PCHIP broke monotonicity: {diffs.tolist()}"


def test_interpolation_leaves_endpoint_gaps_unfilled():
    # Known only in the middle: 5 through 20
    known_states = list(range(5, 21))
    ests = {s: StateEstimate(state=s, mu=float(s), sigma=1.0, n_obs=30, method="data-driven") for s in known_states}
    filled = interpolate_missing_states(ests, state_grid=STATE_GRID)
    for s in range(0, 5):
        assert s not in filled, f"state {s} should not be interpolated (outside convex hull)"
    for s in range(21, STATE_GRID):
        assert s not in filled


def test_interpolation_no_op_when_fewer_than_two_known_states():
    ests = {12: StateEstimate(state=12, mu=1.0, sigma=1.0, n_obs=30, method="data-driven")}
    filled = interpolate_missing_states(ests)
    assert len(filled) == 1


# ---------------------------------------------------------------------------
# Seed and borrow fallbacks
# ---------------------------------------------------------------------------


def test_seed_fallback_fills_all_missing_from_ret_distribution():
    blocks = load_seed()
    b = next(b for b in blocks if b.id == 5)  # US Equities
    partial = {12: StateEstimate(state=12, mu=0.99, sigma=None, n_obs=30, method="data-driven")}
    filled = seed_fallback(b, partial)
    assert len(filled) == STATE_GRID
    for s in range(STATE_GRID):
        if s == 12:
            assert filled[s].method == "data-driven"
        else:
            assert filled[s].method == "seed"
            assert filled[s].mu == pytest.approx(b.ret_distribution[s])


def test_borrow_from_peers_uses_role_region_average():
    """Peer borrow averages profile_by_state across role-region peers.

    Units are annualised percent throughout (see D4). Peers here are built
    with mu = ret_distribution (already annualised percent), and the target's
    partial estimates are in the same unit.
    """
    blocks = load_seed()
    blocks_by_id = {b.id: b for b in blocks}
    ch = blocks_by_id[2]   # CH Equities, Growth, Europe
    eu = blocks_by_id[3]   # EU Equities, Growth, Europe
    uk = blocks_by_id[4]   # UK Equities, Growth, Europe
    fake_estimates = {}
    for peer in (eu, uk):
        states = tuple(
            StateEstimate(state=s, mu=float(peer.ret_distribution[s]), sigma=15.0, n_obs=30, method="data-driven")
            for s in range(STATE_GRID)
        )
        fake_estimates[peer.id] = BlockEstimate(
            block_id=peer.id, ticker=peer.ticker, canonical_role=peer.canonical_role.value,
            region=peer.region.value, states=states,
        )
    partial = {
        0: StateEstimate(state=0, mu=-35.0, sigma=15.0, n_obs=30, method="data-driven"),
        24: StateEstimate(state=24, mu=16.0, sigma=10.0, n_obs=30, method="data-driven"),
    }
    filled = borrow_from_peers(ch, partial, fake_estimates, blocks_by_id)
    assert len(filled) == STATE_GRID
    for s in range(1, 24):
        assert filled[s].method == "borrowed", f"state {s} was {filled[s].method}"
    expected = (eu.ret_distribution[12] + uk.ret_distribution[12]) / 2.0
    assert filled[12].mu == pytest.approx(expected)


def test_borrow_returns_unchanged_if_no_peers():
    blocks = load_seed()
    b = next(b for b in blocks if b.id == 5)
    partial = {12: StateEstimate(state=12, mu=0.02, sigma=None, n_obs=10, method="data-driven-trimmed")}
    out = borrow_from_peers(b, partial, all_estimates={}, all_blocks={x.id: x for x in blocks})
    assert out == partial


# ---------------------------------------------------------------------------
# End-to-end BlockEstimate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_env():
    """Full synthetic environment: timeline + register + source, all seeded."""
    blocks = load_seed()
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    tl = build_synthetic_timeline(seed=20260728)
    return blocks, reg, src, tl


def test_annualise_estimate_transforms_only_sample_methods():
    """Fallback methods pass through; sample methods get compound-annualised."""
    data_est = StateEstimate(state=10, mu=0.005, sigma=0.02, n_obs=50, method="data-driven")
    seed_est = StateEstimate(state=10, mu=5.0, sigma=None, n_obs=0, method="seed")

    a_data = annualise_estimate(data_est, freq_per_year=12)
    a_seed = annualise_estimate(seed_est, freq_per_year=12)

    # 0.5% monthly -> (1.005)^12 - 1 = 0.0617 -> 6.17%
    assert a_data.mu == pytest.approx(6.16778118, rel=1e-6)
    # 2% monthly sigma -> 2% * sqrt(12) = 6.928% -> 6.928
    assert a_data.sigma == pytest.approx(2.0 * (12 ** 0.5), rel=1e-6)
    assert a_data.q05 is None and a_data.q95 is None and a_data.skew is None
    # Seed passes through
    assert a_seed.mu == 5.0
    assert a_seed.method == "seed"


def test_estimate_block_default_output_is_annualised_pct(synthetic_env):
    blocks, reg, src, tl = synthetic_env
    b = next(x for x in blocks if x.id == 5)
    h = ingest_ticker(b.ticker, src, reg)
    aligned = tl.align_returns(h.returns)
    est = estimate_block(b, aligned)
    assert est.mu_unit == "annualised_pct"


def test_estimate_block_end_to_end(synthetic_env):
    blocks, reg, src, tl = synthetic_env
    b = next(x for x in blocks if x.id == 5)  # US Equities
    h = ingest_ticker(b.ticker, src, reg)
    aligned = tl.align_returns(h.returns)
    est = estimate_block(b, aligned, calibration_window=("1998-01", "2024-12"))

    assert est.block_id == 5
    assert est.canonical_role == "Gain"
    assert len(est.states) == STATE_GRID
    assert all(est.states[i].state == i for i in range(STATE_GRID))
    assert est.n_obs_total == len(aligned)
    # profile_by_state length invariant
    assert len(est.profile_by_state) == STATE_GRID
    assert len(est.n_obs_by_state) == STATE_GRID


def test_estimate_block_coverage_reflects_worst_method(synthetic_env):
    """Under the synthetic Markov timeline (high-persistence, mid-state), most
    outer states have zero observations, so the block should end up at
    ``seed`` coverage after all fallbacks."""
    blocks, reg, src, tl = synthetic_env
    b = next(x for x in blocks if x.id == 5)
    h = ingest_ticker(b.ticker, src, reg)
    aligned = tl.align_returns(h.returns)
    est = estimate_block(b, aligned)
    # Coverage grade is one of the four ranks
    assert est.coverage in ("full", "partial", "borrowed", "seed")
    # Given no peer estimates were passed, tail states must come from seed
    tail_methods = {est.states[s].method for s in (0, 24)}
    assert "seed" in tail_methods


def test_estimate_block_partial_coverage_with_peers(synthetic_env):
    """With hand-crafted peers that have DATA-DRIVEN values across all 25
    states, the target's tail states (unobserved under the synthetic Markov
    timeline) borrow from those peers instead of falling to seed.

    Uses hand-crafted peer estimates rather than re-ingested ones because a
    peer that shares the same timeline will have the same coverage gaps as
    the target — so the borrow step has nothing to contribute. In production
    against real market data, peers with long, complete histories exist and
    do fill the target's tails via ``borrow_from_peers``.
    """
    blocks, reg, src, tl = synthetic_env
    blocks_by_id = {b.id: b for b in blocks}

    # Hand-craft two Europe Growth peers with data-driven values for every
    # state, using their seed ret_distribution as the mu.
    fake_estimates: dict[int, BlockEstimate] = {}
    for peer_id in (2, 3):  # CH Equities, EU Equities
        peer = blocks_by_id[peer_id]
        states = tuple(
            StateEstimate(
                state=s, mu=float(peer.ret_distribution[s]),
                sigma=15.0, n_obs=30, method="data-driven",
            )
            for s in range(STATE_GRID)
        )
        fake_estimates[peer_id] = BlockEstimate(
            block_id=peer.id, ticker=peer.ticker,
            canonical_role=peer.canonical_role.value, region=peer.region.value,
            states=states,
        )

    target = blocks_by_id[46]  # 'Aktien Europe aktiv' — Growth, Europe
    h_t = ingest_ticker(target.ticker, SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31)), reg)
    aligned_t = tl.align_returns(h_t.returns)
    est = estimate_block(target, aligned_t, all_estimates=fake_estimates, all_blocks=blocks_by_id)

    methods = set(est.methods)
    assert "borrowed" in methods, f"expected 'borrowed' with hand-crafted peers, got {methods}"
    # Coverage grade is 'borrowed' — no state falls to seed because every
    # missing state has at least one contributing peer.
    assert est.coverage == "borrowed"


def test_estimate_block_falls_to_seed_when_peers_lack_state(synthetic_env):
    """When peers themselves lack data for a state, that state falls
    through to the target's own seed rather than propagating the peer's
    stale fallback (D12 borrow fix).
    """
    blocks, reg, src, tl = synthetic_env
    blocks_by_id = {b.id: b for b in blocks}
    # Peer with only middle-state data-driven; tails are seed.
    peer = blocks_by_id[2]
    peer_states: list[StateEstimate] = []
    for s in range(STATE_GRID):
        if 10 <= s <= 14:
            peer_states.append(StateEstimate(state=s, mu=5.0, sigma=15.0, n_obs=30, method="data-driven"))
        else:
            peer_states.append(StateEstimate(state=s, mu=float(peer.ret_distribution[s]),
                                             sigma=None, n_obs=0, method="seed"))
    fake_estimates = {
        peer.id: BlockEstimate(
            block_id=peer.id, ticker=peer.ticker,
            canonical_role=peer.canonical_role.value, region=peer.region.value,
            states=tuple(peer_states),
        )
    }

    target = blocks_by_id[46]
    h_t = ingest_ticker(target.ticker, SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31)), reg)
    aligned_t = tl.align_returns(h_t.returns)
    est = estimate_block(target, aligned_t, all_estimates=fake_estimates, all_blocks=blocks_by_id)

    # Target crisis states (peer's crisis is seed) must fall to target's own
    # seed, not to peer's seed.
    for s in range(0, 5):
        assert est.states[s].method == "seed"
        assert est.states[s].mu == pytest.approx(float(target.ret_distribution[s]))


def test_estimate_block_state_ordering_enforced():
    from fmre.estimate.block import BlockEstimate
    states = tuple(
        StateEstimate(state=(i + 1) % STATE_GRID, mu=0.0, sigma=None, n_obs=0, method="seed")
        for i in range(STATE_GRID)
    )
    with pytest.raises(ValueError, match="ordered by index"):
        BlockEstimate(block_id=1, ticker="X", canonical_role="Gain", region="Europe", states=states)
