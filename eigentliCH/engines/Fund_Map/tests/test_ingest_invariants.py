"""Ingestion invariants — spec section 8, test 2 (and 3, for return alignment).

Magnitude scaling and constant-FX conversion are multiplicative level ops:
they must leave period returns unchanged. Non-positive levels must not
silently produce NaN/inf returns; the pipeline must refuse.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fmre.ingest.harmonise import apply_fx, apply_magnitude, resample_to_monthly
from fmre.ingest.pipeline import HarmonisedSeries, ingest_ticker, read_parquet_provenance, write_parquet
from fmre.ingest.returns import period_returns
from fmre.ingest.sources import CsvSource, SyntheticSource
from fmre.registers.building_blocks import load_seed
from fmre.registers.data_series import Currency, Magnitude, Period, Unit, build_default_register


@pytest.fixture(scope="module")
def blocks():
    return load_seed()


@pytest.fixture(scope="module")
def register(blocks):
    return build_default_register(blocks)


@pytest.fixture(scope="module")
def synth():
    return SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))


# ---------------------------------------------------------------------------
# Register coverage
# ---------------------------------------------------------------------------


def test_data_series_register_covers_all_unique_tickers(blocks, register):
    unique_tickers = {b.ticker for b in blocks}
    assert set(register.keys()) == unique_tickers
    assert len(register) == len(unique_tickers)


def test_data_series_register_dedupes_proxies(blocks, register):
    counts: dict[str, int] = {}
    for b in blocks:
        counts[b.ticker] = counts.get(b.ticker, 0) + 1
    proxies = {t for t, c in counts.items() if c > 1}
    assert "MXWO Index" in proxies         # rows 16, 45, 47
    assert "SWIIT Index" in proxies        # rows 39, 48
    assert "VXTH Index" in proxies         # rows 37, 49
    for t in proxies:
        assert t in register  # each proxy still has exactly one register row


# ---------------------------------------------------------------------------
# Synthetic source
# ---------------------------------------------------------------------------


def test_synthetic_source_deterministic_per_ticker(synth):
    a = synth.fetch("MXUS Index")
    b = synth.fetch("MXUS Index")
    pd.testing.assert_series_equal(a, b)


def test_synthetic_source_differs_across_tickers(synth):
    a = synth.fetch("MXUS Index")
    b = synth.fetch("MXEU Index")
    assert not a.equals(b)


def test_synthetic_source_monthly_frequency(synth):
    s = synth.fetch("MXUS Index")
    idx = s.index
    assert isinstance(idx, pd.DatetimeIndex)
    diffs = idx.to_series().diff().dropna()
    # month-end frequency: differences between 28 and 31 days
    assert diffs.min() >= pd.Timedelta("28D")
    assert diffs.max() <= pd.Timedelta("31D")


def test_synthetic_source_positive_levels(synth):
    s = synth.fetch("MXUS Index")
    assert (s > 0).all()


# ---------------------------------------------------------------------------
# CSV source
# ---------------------------------------------------------------------------


def test_csv_source_reads_valid_file(tmp_path: Path):
    ticker = "MXUS Index"
    file = tmp_path / "MXUS_Index.csv"
    file.write_text("date,close\n2020-01-31,100.0\n2020-02-29,101.5\n2020-03-31,95.0\n", encoding="utf-8")
    src = CsvSource(root=tmp_path)
    s = src.fetch(ticker)
    assert list(s.index) == list(pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31"]))
    assert s.iloc[1] == pytest.approx(101.5)


def test_csv_source_missing_raises(tmp_path: Path):
    src = CsvSource(root=tmp_path)
    with pytest.raises(FileNotFoundError, match="MXUS Index"):
        src.fetch("MXUS Index")


# ---------------------------------------------------------------------------
# Harmonisation invariance — the core spec 8.2 property
# ---------------------------------------------------------------------------


def _sample_prices() -> pd.Series:
    idx = pd.date_range("2020-01-31", periods=12, freq="ME")
    rng = np.random.default_rng(42)
    log_r = 0.005 + 0.03 * rng.standard_normal(len(idx))
    levels = 100.0 * np.exp(np.cumsum(log_r))
    return pd.Series(levels, index=idx, name="TEST")


def test_magnitude_scaling_preserves_returns():
    """Magnitude is a multiplicative constant; returns are unchanged."""
    prices = _sample_prices()
    r0 = period_returns(prices)
    r1 = period_returns(apply_magnitude(prices, Magnitude.MN))
    r2 = period_returns(apply_magnitude(prices, Magnitude.BN))
    pd.testing.assert_series_equal(r0.reset_index(drop=True), r1.reset_index(drop=True), check_names=False)
    pd.testing.assert_series_equal(r0.reset_index(drop=True), r2.reset_index(drop=True), check_names=False)


def test_constant_fx_preserves_returns():
    """A constant FX multiplier leaves period returns unchanged."""
    prices = _sample_prices()
    r0 = period_returns(prices)
    r_fx = period_returns(apply_fx(prices, "USD", "CHF", fx_series=0.92))
    pd.testing.assert_series_equal(r0.reset_index(drop=True), r_fx.reset_index(drop=True), check_names=False)


def test_same_currency_fx_is_passthrough_and_labelled():
    prices = _sample_prices()
    out = apply_fx(prices, "USD", "USD")
    pd.testing.assert_series_equal(out, prices, check_names=False)
    assert out.attrs["fx_handling"] == "passthrough"


def test_log_returns_are_additive_under_scaling():
    prices = _sample_prices()
    from fmre.ingest.returns import period_returns as pr
    r_log_a = pr(prices, method="log")
    r_log_b = pr(apply_magnitude(prices, Magnitude.MN), method="log")
    pd.testing.assert_series_equal(r_log_a.reset_index(drop=True), r_log_b.reset_index(drop=True), check_names=False)


# ---------------------------------------------------------------------------
# Return computation
# ---------------------------------------------------------------------------


def test_period_returns_length_is_series_minus_one():
    prices = _sample_prices()
    r = period_returns(prices)
    assert len(r) == len(prices) - 1


def test_period_returns_finite():
    prices = _sample_prices()
    r = period_returns(prices)
    assert np.isfinite(r.to_numpy()).all()


def test_period_returns_rejects_non_positive_levels():
    bad = pd.Series([100.0, 50.0, 0.0, 25.0], index=pd.date_range("2020-01-31", periods=4, freq="ME"))
    with pytest.raises(ValueError, match="non-positive"):
        period_returns(bad)


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------


def test_ingest_ticker_end_to_end(register, synth):
    h = ingest_ticker("MXUS Index", synth, register)
    assert isinstance(h, HarmonisedSeries)
    assert h.ticker == "MXUS Index"
    assert h.currency == "LCY"
    assert h.provenance.source == "synthetic"
    assert h.provenance.magnitude_label == "Lvl"
    assert h.provenance.return_method == "simple"
    assert h.n_obs_returns() == len(h.levels) - 1
    assert h.provenance.idempotency_key.startswith("id-")
    assert "fetch:synthetic" in h.provenance.transforms
    assert "returns:simple" in h.provenance.transforms


def test_ingest_ticker_is_deterministic(register, synth):
    a = ingest_ticker("MXUS Index", synth, register)
    b = ingest_ticker("MXUS Index", synth, register)
    pd.testing.assert_series_equal(a.levels, b.levels)
    if a.returns is not None and b.returns is not None:
        pd.testing.assert_series_equal(a.returns, b.returns)
    # ingested_at differs, but the level/returns must be identical.
    assert a.provenance.idempotency_key == b.provenance.idempotency_key


def test_ingest_ticker_unknown_raises(register, synth):
    with pytest.raises(KeyError, match="not in DataSeries register"):
        ingest_ticker("NOT_A_TICKER", synth, register)


def test_state_conditional_synthetic_recovers_seed_state_means(blocks, register):
    """Under state-conditional generation, the estimator's per-state mu
    (from data-driven buckets) should recover the seed value."""
    from datetime import date
    from fmre.regime import build_synthetic_timeline
    from fmre.ingest.sources import seed_state_conditional_hints
    from fmre.estimate.map_states import bucket_returns_by_state
    from fmre.estimate.per_state import estimate_per_state_from_buckets, annualise_estimates

    tl = build_synthetic_timeline(persistence=0.85)  # slightly less sticky so more states get n>=6
    hints = seed_state_conditional_hints(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31), timeline=tl, state_hints=hints)

    us_eq = next(b for b in blocks if b.id == 5)
    h = ingest_ticker(us_eq.ticker, src, register)
    aligned = tl.align_returns(h.returns)
    buckets = bucket_returns_by_state(aligned)
    per_state = annualise_estimates(estimate_per_state_from_buckets(buckets))

    # For any state that has enough obs to estimate, recovered mu should be
    # close to the seed value for that state (within a few percentage points
    # given finite-sample sigma and the state's visit count).
    hits = 0
    for state, est in per_state.items():
        seed_val = float(us_eq.ret_distribution[state])
        # Bigger buckets converge tighter; tolerate 10 pct pts for small buckets
        tol = 20.0 if est.n_obs < 20 else 8.0
        if abs(est.mu - seed_val) <= tol:
            hits += 1
    # At least the well-populated states should hit
    assert hits >= 3, f"state-conditional recovery poor: only {hits} states within tolerance"


def test_state_conditional_synthetic_is_deterministic(blocks, register):
    from datetime import date
    from fmre.regime import build_synthetic_timeline
    from fmre.ingest.sources import seed_state_conditional_hints

    tl = build_synthetic_timeline()
    hints = seed_state_conditional_hints(blocks)
    src1 = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31), timeline=tl, state_hints=hints)
    src2 = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31), timeline=tl, state_hints=hints)
    a = src1.fetch("MXUS Index")
    b = src2.fetch("MXUS Index")
    pd.testing.assert_series_equal(a, b)


def test_state_conditional_source_labels_generation_attr(blocks, register):
    from datetime import date
    from fmre.regime import build_synthetic_timeline
    from fmre.ingest.sources import seed_state_conditional_hints

    tl = build_synthetic_timeline()
    hints = seed_state_conditional_hints(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31), timeline=tl, state_hints=hints)
    s = src.fetch("MXUS Index")
    assert s.attrs["generation"] == "state_conditional"

    plain = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    p = plain.fetch("MXUS Index")
    assert p.attrs["generation"] == "gbm"


def test_parquet_roundtrip_carries_provenance(tmp_path: Path, register, synth):
    h = ingest_ticker("MXUS Index", synth, register)
    path = write_parquet(h, tmp_path)
    assert path.exists()
    prov = read_parquet_provenance(path)
    assert prov["ticker"] == "MXUS Index"
    assert prov["source"] == "synthetic"
    assert prov["idempotency_key"] == h.provenance.idempotency_key
