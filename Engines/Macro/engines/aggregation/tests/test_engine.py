"""Unit and property tests of the pure engine (engine page section 5, Guide 6.2).

Properties: each distribution sums to 1 and is non-negative; exactly 25 states; the same inputs
and optimism level always give the same ``regime_id`` and artefact; a higher optimism level
never reads more cautious; a missing input is never read as a number.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from aggregation import calibration as seeds
from aggregation.contracts import (
    N_STATES,
    OPTIMISM_SCALES,
    Calibration,
    MarketRiskSignal,
)
from aggregation.engine import (
    MacroReading,
    blend_row,
    describe,
    macro_year_for,
    mean_state,
    modal_state,
    placed_kernels,
    regime_weights,
    run_model,
    shift_distribution,
    spread,
)
from aggregation.service import build_regime, content_id, regime_id_for

ACTIVE = seeds.TAIL_KEPT

distributions = st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=N_STATES,
                         max_size=N_STATES).filter(lambda v: sum(v) > 1e-6).map(
    lambda v: np.asarray(v) / np.sum(v))


def _binom(n: int, p: float) -> np.ndarray:
    return np.array([math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)])


def _place(kernel: np.ndarray, first: int) -> np.ndarray:
    out = np.zeros(N_STATES)
    for i, m in enumerate(kernel):
        out[min(max(first + i, 1), N_STATES) - 1] += m
    return out


def neutral_market_row() -> np.ndarray:
    """``mrs`` at neutral readings (every segment 0) and zero shift: the three band segments
    select column 6 (binomial(8, 0.5) on states 8 to 16), the stress tail its first live column
    (binomial(8, 0.1) on states 1 to 9, divided by 11). Modal state 12."""
    row = 0.75 * _place(_binom(8, 0.5), 8) + 0.25 * _place(_binom(8, 0.1), 1) / 11
    return row / row.sum()


# ---------------------------------------------------------------------------
# Kernels and tilts
# ---------------------------------------------------------------------------

def test_kernels_are_unit_and_on_the_axis():
    placed = placed_kernels(ACTIVE.kernels)
    for regime, row in placed.items():
        assert row.shape == (N_STATES,)
        assert abs(row.sum() - 1.0) < 1e-15, regime
    # The crisis kernel is piled at the cautious end, boom is its mirror.
    assert np.allclose(placed["boom"], placed["crisis"][::-1])
    assert placed["crisis"].argmax() == 1 and placed["boom"].argmax() == 23


def test_neutral_macro_reading_is_even():
    reading = MacroReading(year=2020, saturation=3.0, real_to_financial=1.2)
    weights, contributions = regime_weights(reading, ACTIVE.tilts)
    assert contributions == {}
    assert all(abs(w - 0.2) < 1e-15 for w in weights.values())


def test_saturation_above_band_moves_weight_to_the_cautious_end():
    calm, _ = regime_weights(MacroReading(2020, 3.0, 1.2), ACTIVE.tilts)
    hot, moves = regime_weights(MacroReading(2020, 4.0, 1.2), ACTIVE.tilts)
    assert "saturation_above_band" in moves
    assert hot["crisis"] > calm["crisis"] and hot["boom"] < calm["boom"]


@settings(max_examples=200, deadline=None)
@given(sat=st.floats(0.1, 5.9), rtf=st.floats(0.05, 5.0), unsec=st.none() | st.floats(-2, 2),
       inter=st.none() | st.floats(-1, 1), align=st.none() | st.floats(0, 1),
       cap=st.none() | st.floats(-150, 150), inno=st.none() | st.floats(-60, 60))
def test_macro_row_is_a_distribution(sat, rtf, unsec, inter, align, cap, inno):
    reading = MacroReading(2020, sat, rtf, unsec, inter, align, cap, inno)
    weights, _ = regime_weights(reading, ACTIVE.tilts)
    assert abs(sum(weights.values()) - 1.0) < 1e-12 and min(weights.values()) >= 0.0
    row = spread(weights, placed_kernels(ACTIVE.kernels))
    assert row.shape == (N_STATES,) and row.min() >= 0.0 and abs(row.sum() - 1.0) < 1e-12


# ---------------------------------------------------------------------------
# Blend
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None)
@given(a=distributions, b=distributions, c=st.none() | distributions,
       wm=st.floats(0, 1), wc=st.floats(0, 1))
def test_blend_is_a_distribution_and_weights_add_up(a, b, c, wm, wc):
    out = blend_row(a, b, c, wm, wc)
    assert out.distribution.min() >= 0.0 and abs(out.distribution.sum() - 1.0) < 1e-12
    assert abs(out.weight_macro + out.weight_market + out.weight_cycle - 1.0) < 1e-12
    if c is None:
        assert out.weight_cycle == 0.0


def test_blend_is_the_draft_formula():
    a, b, c = (np.eye(N_STATES)[k] for k in (0, 12, 24))
    out = blend_row(a, b, c, 0.5, 0.2)
    assert np.allclose(out.distribution, 0.4 * a + 0.4 * b + 0.2 * c)


# ---------------------------------------------------------------------------
# Optimism
# ---------------------------------------------------------------------------

@settings(max_examples=300, deadline=None)
@given(d=distributions, s=st.floats(-24, 24))
def test_shift_is_a_distribution(d, s):
    out = shift_distribution(d, s)
    assert out.shape == (N_STATES,) and out.min() >= 0.0 and abs(out.sum() - 1.0) < 1e-12


@settings(max_examples=300, deadline=None)
@given(d=distributions, s1=st.floats(-24, 24), s2=st.floats(-24, 24), keep=st.sampled_from((0, 5)))
def test_a_larger_shift_never_reads_more_cautious(d, s1, s2, keep):
    """First-order stochastic dominance: the CDF of the larger shift lies at or below."""
    lo, hi = sorted((s1, s2))
    cdf_lo = np.cumsum(shift_distribution(d, lo, keep))
    cdf_hi = np.cumsum(shift_distribution(d, hi, keep))
    assert np.all(cdf_hi <= cdf_lo + 1e-12)


def test_whole_shift_is_a_translation_with_pile_up():
    d = np.zeros(N_STATES)
    d[[0, 10, 24]] = [0.2, 0.5, 0.3]
    out = shift_distribution(d, 3.0)
    assert out[3] == pytest.approx(0.2) and out[13] == pytest.approx(0.5) and out[24] == pytest.approx(0.3)
    back = shift_distribution(d, -2.0)
    assert back[0] == pytest.approx(0.2) and back[8] == pytest.approx(0.5) and back[22] == pytest.approx(0.3)
    assert np.array_equal(shift_distribution(d, 0.0), d)


def test_neutral_reading_lands_on_the_targets():
    """Task "Aggregation: optimism levels and the Rogue targets": at neutral readings,
    Defensive 10, Default 14, Aggressive 19, Rogue 24 (the published, mean-nearest state), in
    1.1.0 (everything moves) and in 1.2.0 (the crisis tail kept, shifts solved)."""
    row = neutral_market_row()
    assert modal_state(row) == 12 == ACTIVE.optimism.reference_state
    for cal in (seeds.OPTIMISM_LEVELS, seeds.TAIL_KEPT):
        o = cal.optimism
        states = {level: mean_state(shift_distribution(row, o.shift(level), o.keep_tail))
                  for level in OPTIMISM_SCALES}
        assert states == {"defensive": 10, "default": 14, "aggressive": 19, "rogue": 24}, cal.version
        for level in ("defensive", "default"):
            assert modal_state(shift_distribution(row, o.shift(level), o.keep_tail)) == states[level]


@settings(max_examples=200, deadline=None)
@given(d=distributions, s=st.floats(-24, 24), keep=st.integers(0, 10))
def test_a_kept_tail_does_not_move(d, s, keep):
    out = shift_distribution(d, s, keep)
    assert abs(out.sum() - 1.0) < 1e-12 and out.min() >= 0.0
    if s > 0:
        assert np.allclose(out[:keep], d[:keep], atol=1e-12)


def test_the_crisis_tail_stays_live_at_every_level(mrs, cycle, macro):
    """AGG-15: under 1.2.0 no level empties the five most cautious states."""
    for level in OPTIMISM_SCALES:
        out = run_model(mrs, cycle, macro, ACTIVE, level)
        assert not any("crisis tail" in w for w in out.warnings), level


def test_optimism_targets_must_be_ordered():
    bad = ACTIVE.model_dump()
    bad["version"] = "9.9.9"
    bad["optimism"]["targets"] = {"defensive": 14, "default": 10, "aggressive": 19, "rogue": 24}
    with pytest.raises(ValueError, match="more cautious"):
        Calibration.model_validate(bad)


def test_draft_calibration_has_no_shift():
    assert all(seeds.DRAFT.optimism.shift(level) == 0.0 for level in OPTIMISM_SCALES)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_describe_reads_a_bimodal_distribution():
    d = np.zeros(N_STATES)
    d[1], d[15] = 0.45, 0.55
    r = describe(d, ACTIVE.reading, "2026-01-31")
    assert r.bimodal and r.modes == (2, 16) and r.modal_state == 16
    assert r.state == mean_state(d) and r.crisis_tail == pytest.approx(0.45)
    assert sum(r.five_regime.values()) == pytest.approx(1.0)


def test_equal_peaks_are_two_modes():
    """AGG-23: a peak exactly as tall as the tallest, behind a real saddle, is a mode; a flat top
    is still one mode."""
    from aggregation import scenario as sc
    from aggregation.engine import prominent_modes

    d = np.zeros(N_STATES)
    d[1], d[23] = 0.5, 0.5
    r = describe(d, ACTIVE.reading, "2031-01-31")
    assert r.bimodal and r.modes == (2, 24) and r.shape.startswith("swing")
    deferral = sc.target_distribution("deferral") / sc.target_distribution("deferral").sum()
    assert describe(deferral, ACTIVE.reading, "2031-01-31").modes == (2, 24)
    flat = np.zeros(N_STATES)
    flat[10], flat[11] = 0.5, 0.5
    assert prominent_modes(flat, 0.25) == [11]


def test_modal_ties_go_cautious():
    d = np.zeros(N_STATES)
    d[4] = d[20] = 0.5
    assert modal_state(d) == 5


# ---------------------------------------------------------------------------
# Carry and gaps
# ---------------------------------------------------------------------------

def test_macro_year_for_carries_only_past_the_last_reading():
    years = (2019, 2020, 2022, 2023, 2024)
    assert macro_year_for("2024-06-30", years, 24) == (2024, False)
    assert macro_year_for("2021-06-30", years, 24) == (None, False)      # interior gap: never filled
    assert macro_year_for("2025-01-31", years, 0) == (None, False)       # no carry in 1.0.0
    assert macro_year_for("2026-12-31", years, 24) == (2024, True)
    assert macro_year_for("2027-01-31", years, 24) == (None, False)


def test_a_missing_market_month_is_not_assessed(mrs, cycle, macro):
    data = mrs.model_dump(mode="json")
    t = 100
    for e in data["economies"]:
        e["distribution"][t] = None
    gapped = MarketRiskSignal.model_validate(data)
    out = run_model(gapped, cycle, macro, ACTIVE, "default")
    for e in out.economies:
        assert e.distribution[t] is None and e.state[t] is None and e.weight_macro[t] is None
    for m in out.markets:
        assert m.distribution[t] is None


# ---------------------------------------------------------------------------
# The whole model on the frozen inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", OPTIMISM_SCALES)
def test_every_published_distribution_is_valid(mrs, cycle, macro, level):
    out = run_model(mrs, cycle, macro, ACTIVE, level)
    assert out.economies
    for e in list(out.economies) + list(out.markets):
        for d, s in zip(e.distribution, e.state):
            assert (d is None) == (s is None)
            if d is not None:
                assert len(d) == N_STATES and min(d) >= 0.0 and abs(math.fsum(d) - 1.0) <= 1e-12
                assert 1 <= s <= N_STATES


def test_higher_optimism_never_reads_more_cautious(mrs, cycle, macro):
    outs = [run_model(mrs, cycle, macro, ACTIVE, level) for level in OPTIMISM_SCALES]
    for lo, hi in zip(outs, outs[1:]):
        for a, b in zip(lo.economies, hi.economies):
            for da, db in zip(a.distribution, b.distribution):
                if da is None:
                    continue
                assert np.all(np.cumsum(db) <= np.cumsum(da) + 1e-12)


def test_same_inputs_same_regime(mrs, cycle, macro):
    key = content_id("IDK", {"test": 1})
    a = build_regime(mrs, cycle, macro, ACTIVE, "rogue", key, regime_id_for(key))
    b = build_regime(mrs, cycle, macro, ACTIVE, "rogue", key, regime_id_for(key))
    assert a.artefact_id == b.artefact_id and a.regime_id == b.regime_id == regime_id_for(key)
    assert a.regime_id.startswith("RGM-") and a.provenance.regime_id == a.regime_id


def test_snapshot_mismatch_is_warned_not_refused(mrs, cycle, macro):
    key = content_id("IDK", {"test": 2})
    r = build_regime(mrs, cycle, macro, ACTIVE, "default", key, regime_id_for(key))
    assert r.coverage.snapshot_mismatch
    assert any("one datafeed snapshot" in w for w in r.coverage.warnings)


def test_markets_need_every_weighted_economy(mrs, cycle, macro):
    out = run_model(mrs, cycle, macro, ACTIVE, "default", economies=("US", "CN", "EU"))
    by = {m.code: m for m in out.markets}
    assert any(d is not None for d in by["sino"].distribution)          # CN, EU, US: all present
    assert all(d is None for d in by["global"].distribution)            # needs IN, CH, BR, GB too
    cov = {c.code: c for c in out.market_coverage}
    assert set(cov["global"].economies_absent) == {"IN", "CH", "BR", "GB"}


def test_carry_is_flagged(mrs, cycle, macro):
    out = run_model(mrs, cycle, macro, ACTIVE, "default")
    us = next(e for e in out.economies if e.code == "US")
    carried = [d for d, c in zip(out.dates, us.carried) if c]
    assert carried and all(int(d[:4]) > max(us.years) for d in carried)
    assert us.current is not None and us.current.macro_carried
    cov = next(c for c in out.economy_coverage if c.code == "US")
    assert cov.dates_macro_carried == len(carried)
