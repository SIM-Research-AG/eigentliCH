"""Mixture recomposition identity (spec 5.2, test 4).

The frequency-weighted per-state sample moments must recompose to the
block's unconditional sample moments EXACTLY on the empirical data.
Floating-point tolerance only.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from fmre.estimate import empirical_mixture_decomposition, mixture_recompose_error
from fmre.ingest.pipeline import ingest_ticker
from fmre.ingest.sources import SyntheticSource
from fmre.regime import build_synthetic_timeline
from fmre.registers.building_blocks import load_seed
from fmre.registers.data_series import build_default_register


def test_mixture_identity_synthetic_random():
    """Pure algebra: for any partition into buckets, the frequency-weighted
    per-bucket sample moments recompose to the overall sample moments."""
    rng = np.random.default_rng(0)
    n = 1000
    rets = rng.standard_normal(n) * 0.02 + 0.01
    states = rng.integers(0, 25, size=n)
    df = pd.DataFrame({"return": rets, "state": states})

    mu_err, var_err = mixture_recompose_error(df)
    assert mu_err < 1e-12
    assert var_err < 1e-12


def test_mixture_identity_variance_decomposition():
    """Explicit within + between decomposition equals total variance."""
    rng = np.random.default_rng(42)
    n = 800
    rets = rng.normal(0.005, 0.03, size=n)
    states = rng.integers(0, 25, size=n)
    df = pd.DataFrame({"return": rets, "state": states})

    d = empirical_mixture_decomposition(df)
    assert (d.var_within + d.var_between) == pytest.approx(d.var_unconditional, abs=1e-12)
    assert d.mu_recomposed == pytest.approx(d.mu_unconditional, abs=1e-12)


def test_mixture_identity_end_to_end_ingested_series():
    """End-to-end: real ingested block, real synthetic timeline. Identity
    must still hold because it is an algebraic identity, independent of the
    data-generating process."""
    blocks = load_seed()
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    tl = build_synthetic_timeline(seed=20260728)

    us_eq = next(b for b in blocks if b.id == 5)
    h = ingest_ticker(us_eq.ticker, src, reg)
    aligned = tl.align_returns(h.returns)

    d = empirical_mixture_decomposition(aligned)
    assert d.mu_error < 1e-10
    assert d.var_error < 1e-10


def test_mixture_variance_within_is_nonneg():
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "return": rng.standard_normal(500) * 0.02,
        "state": rng.integers(0, 25, size=500),
    })
    d = empirical_mixture_decomposition(df)
    assert d.var_within >= 0
    assert d.var_between >= 0


def test_mixture_between_variance_is_zero_when_all_states_equal():
    """If every observation is in one state, between-variance is zero and
    unconditional variance equals within-variance."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "return": rng.standard_normal(200) * 0.02,
        "state": np.full(200, 12, dtype=int),
    })
    d = empirical_mixture_decomposition(df)
    assert d.var_between == pytest.approx(0.0, abs=1e-15)
    assert d.var_within == pytest.approx(d.var_unconditional, abs=1e-12)


def test_mixture_rejects_empty():
    with pytest.raises(ValueError, match="empty input"):
        empirical_mixture_decomposition(pd.DataFrame({"return": [], "state": []}))


def test_mixture_rejects_missing_columns():
    with pytest.raises(ValueError, match="expected columns"):
        empirical_mixture_decomposition(pd.DataFrame({"foo": [1, 2]}))
