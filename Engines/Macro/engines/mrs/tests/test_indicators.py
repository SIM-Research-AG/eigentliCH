"""The indicator layer (``mrs.indicators``): MATLAB semantics of the primitives, and the
properties the production calibration promises.

Production properties:

* **No look-ahead** except the one ruled in (``gradient`` keeps central differences, so the
  market stability flags read one month ahead): changing the data after month k never
  changes a published value at or before k.
* **A gap is never read as a number:** a missing input is not a 0, and an indicator whose
  every input is missing is missing.
* **Warm-up:** 24 months for an input, 12 more for a combination (ruled 27.09.2026).
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from mrs import calibration as seeds
from mrs import indicators as ind
from mrs.contracts import INDICATORS, SEGMENT_INDICATORS, SEGMENTS

PROD = seeds.PRODUCTION.indicators
MATLAB = seeds.MATLAB.indicators


# ---------------------------------------------------------------------------
# MATLAB primitives
# ---------------------------------------------------------------------------

def test_normalize_ignores_nan_like_matlab():
    x = np.array([1.0, np.nan, 3.0, 5.0])
    z = ind.m_normalize(x)
    assert np.isnan(z[1])
    finite = np.array([1.0, 3.0, 5.0])
    np.testing.assert_allclose(z[[0, 2, 3]], (finite - 3.0) / np.std(finite, ddof=1))
    assert np.all(np.isnan(ind.m_normalize(np.array([np.nan, np.nan]))))


def test_max_min_ignore_nan_like_matlab():
    x = np.array([np.nan, -9.0, 9.0, 0.5])
    np.testing.assert_array_equal(ind.m_max(-3.0, x), [-3.0, -3.0, 9.0, 0.5])
    np.testing.assert_array_equal(ind.m_min(3.0, x), [3.0, -9.0, 3.0, 0.5])


def test_detrend_removes_a_line_exactly():
    s = np.arange(1.0, 21.0)
    np.testing.assert_allclose(ind.m_detrend(3.0 + 0.5 * s), 0.0, atol=1e-12)
    assert np.all(np.isnan(ind.m_detrend(np.array([1.0, np.nan, 2.0]))))


def test_movmean_is_trailing_and_shrinks_at_the_start():
    np.testing.assert_allclose(ind.m_movmean(np.arange(1.0, 6.0), 2), [1.0, 1.5, 2.0, 3.0, 4.0])


def test_technical_helpers_match_the_models_folder():
    p = np.array([10.0, 11.0, 12.0, 11.0, 13.0, 14.0, 13.0, 15.0, 16.0, 15.0])
    e = ind.ema(p, 3)
    assert e[0] == 10.0 and e[1] == pytest.approx(10.0 + 0.5 * 1.0)
    r = ind.roc(p, 3, 0.0)
    assert list(r[:2]) == [0.0, 0.0] and r[2] == pytest.approx(100 * (12 - 10) / 10)
    m = ind.momentum(p, 3, 0.0)
    assert m[2] == pytest.approx(100 * 12 / 10)
    s = ind.sar(p, 3)
    # sar.m: zeros up to days+1, then a = 1 on the first step (a starts at ones).
    # t = 3: E = max(p[0:4]) = 12 is not p[3], a stays 1, SAR jumps to E.
    # t = 4: E = max(p[1:5]) = 13 is p[4], a resets to 0.02.
    assert list(s[:4]) == [0.0] * 4 and s[4] == 12.0 and s[5] == pytest.approx(12.02)


def test_gold_window_keeps_the_matlab_overwrite():
    """MR_Global_Stability.m overwrites the changes with 0/1 flags inside its own window
    (kept on the owner's ruling). One huge move fires once; the flags that follow sit in
    the window and damp it."""
    n = 40
    base = {sid: np.zeros(n) for sid in ind.series_needed(MATLAB)}
    gold = np.full(n, 100.0)
    gold[25:] = 1000.0                           # one jump of 900 in month 26
    base["commodity.gold"] = gold
    out = ind.global_stability(base, ind._Ops(MATLAB))
    flags = out / (3.0 * MATLAB.lcl_weights[2])
    assert flags[:25].sum() == 0 and flags[25] == 1.0


# ---------------------------------------------------------------------------
# Production properties
# ---------------------------------------------------------------------------

def _inputs(n: int, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    out = {}
    for sid in sorted(set(ind.series_needed(PROD)) | set(ind.series_needed(MATLAB))):
        x = 100.0 + np.cumsum(rng.normal(0, 2, n))
        if sid in ("fx.ois_1y", "volatility.implied"):
            x = np.abs(x) / 400.0
        out[sid] = x
    return out


LOOKS_AHEAD = {"market_stability"}          # central gradient, ruled 27.09.2026


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(0, 10_000), cut=st.integers(40, 70), jump=st.floats(-50, 50))
def test_no_look_ahead_beyond_the_ruled_gradient(seed, cut, jump):
    n = 72
    a = _inputs(n, seed)
    b = {k: v.copy() for k, v in a.items()}
    for v in b.values():
        v[cut + 1:] += jump * (1.0 + np.arange(n - cut - 1))
    ra, rb = ind.compute(a, PROD), ind.compute(b, PROD)
    for name in INDICATORS:
        upto = cut if name in LOOKS_AHEAD else cut + 1
        np.testing.assert_array_equal(ra.indicators[name][:upto], rb.indicators[name][:upto],
                                      err_msg=name)
    for seg in SEGMENTS:
        upto = cut if any(i in LOOKS_AHEAD for i in SEGMENT_INDICATORS[seg]) else cut + 1
        np.testing.assert_array_equal(ra.segments[seg][:upto], rb.segments[seg][:upto],
                                      err_msg=seg)


def test_the_matlab_mode_does_look_ahead():
    """The contrast: full-sample normalisation changes the past when the future changes."""
    n = 72
    a = _inputs(n, 1)
    b = {k: v.copy() for k, v in a.items()}
    b["inflation.cpi_yoy"][60:] += 40.0
    ra, rb = ind.compute(a, MATLAB), ind.compute(b, MATLAB)
    assert not np.array_equal(ra.indicators["inflation"][:50], rb.indicators["inflation"][:50])


def test_warm_up_is_24_then_12_then_12():
    r = ind.compute(_inputs(80, 3), PROD)
    first = {k: int(np.flatnonzero(np.isfinite(v))[0]) for k, v in r.indicators.items()}
    assert first["inflation"] == 24 + 12 - 2      # 0-based: 24th input value, 12th combination
    assert first["trend_osc"] >= 23
    seg_first = int(np.flatnonzero(np.isfinite(r.segments["business_cycle"]))[0])
    assert seg_first == first["inflation"] + 11


def test_a_gap_is_missing_not_zero():
    n = 80
    a = _inputs(n, 5)
    gap = {k: v.copy() for k, v in a.items()}
    zero = {k: v.copy() for k, v in a.items()}
    gap["inflation.cpi_yoy"][50:55] = np.nan
    zero["inflation.cpi_yoy"][50:55] = 0.0
    rg, rz = ind.compute(gap, PROD), ind.compute(zero, PROD)
    assert not np.allclose(rg.indicators["inflation"][50:60], rz.indicators["inflation"][50:60],
                           equal_nan=True)
    # The indicator still reads (its other inputs are present): the missing part is the
    # average, as ruled; with every input missing it is missing.
    assert np.all(np.isfinite(rg.indicators["inflation"][50:55]))
    none = {k: v.copy() for k, v in a.items()}
    for sid in ("fx.neer_broad", "inflation.ppi_yoy", "inflation.cpi_yoy"):
        none[sid][:] = np.nan
    rn = ind.compute(none, PROD)
    assert np.all(np.isnan(rn.indicators["inflation"]))
    assert set(rn.inputs_missing) == {"fx.neer_broad", "inflation.ppi_yoy", "inflation.cpi_yoy"}


def test_an_interior_gap_in_the_index_does_not_stop_trend_osc():
    a = _inputs(90, 9)
    a["equity.total_return"][60:62] = np.nan
    r = ind.compute(a, PROD)
    assert np.all(np.isnan(r.indicators["trend_osc"][60:62]))
    assert np.isfinite(r.indicators["trend_osc"][-1])


def test_production_reads_the_replacements_and_matlab_the_originals():
    assert {"volatility.skew", "fx.neer_broad", "yields.high_yield_ytw"} <= set(ind.series_needed(PROD))
    assert not {"volatility.fear_barometer", "fx.beer", "yields.high_yield_index"} & set(ind.series_needed(PROD))
    assert {"volatility.fear_barometer", "fx.beer", "yields.high_yield_index"} <= set(ind.series_needed(MATLAB))


def test_vix_threshold_is_in_data_units():
    """MRS-16: on a decimal VIX, MATLAB's 20 never fires; production's 0.20 does."""
    n = 30
    a = _inputs(n, 2)
    vix = np.full(n, 0.15)
    vix[20:] = [0.18, 0.25, 0.40, 0.55, 0.60, 0.60, 0.60, 0.60, 0.60, 0.60]
    for p, fires in ((MATLAB, False), (PROD, True)):
        s = {k: v.copy() for k, v in a.items()}
        s["volatility.implied"] = vix
        s["debt.senior_loan_etf"] = np.full(n, 20.0)
        s["equity.banks_total_return"] = s["equity.total_return"].copy()
        out = ind.market_stability(s, ind._Ops(p))
        assert bool(np.nanmax(out) > 0) is fires


@settings(max_examples=10, deadline=None)
@given(seed=st.integers(0, 10_000))
def test_deterministic(seed):
    a = _inputs(60, seed)
    r1, r2 = ind.compute(a, PROD), ind.compute(a, PROD)
    for k in INDICATORS:
        np.testing.assert_array_equal(r1.indicators[k], r2.indicators[k])


def test_missing_series_key_fails_loudly():
    a = _inputs(30, 1)
    del a["fx.dxy"]
    with pytest.raises(ind.IndicatorError, match="fx.dxy"):
        ind.compute(a, PROD)
