"""Per-state distribution estimation (spec 5.2).

For each state bucket we estimate the central return and its dispersion.
Buckets below the sufficiency floor (``n_min``, default 6) are returned as
``None`` and become candidates for interpolation, borrow, or seed fallback
(see ``fallbacks.py``).

Unit convention: sample estimation is done in the source unit (typically
monthly decimal returns). The block-level orchestrator (see ``block.py``)
converts data-driven estimates to annualised percent immediately after
estimation, so the fallback cascade (interpolate/borrow/seed) operates in a
single consistent unit — annualised percent, matching D4 in decisions.md
and the seed ``ret_distribution`` values.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
from scipy import stats


N_MIN_DEFAULT: int = 6
N_TRIMMED_THRESHOLD: int = 20
TRIM_FRACTION: float = 0.20
FREQ_PER_YEAR: dict[str, int] = {"M": 12, "Q": 4, "A": 1}


Method = Literal[
    "data-driven",
    "data-driven-trimmed",
    "interpolated",
    "borrowed",
    "seed",
]


@dataclass(frozen=True, slots=True)
class StateEstimate:
    """One state's estimate for one building block."""

    state: int
    mu: float
    sigma: float | None       # None when the estimate is not from data
    n_obs: int
    method: Method
    q05: float | None = None  # left-tail quantile, retained for diagnostics
    q95: float | None = None
    skew: float | None = None


def estimate_state_from_bucket(
    state: int,
    bucket: np.ndarray,
    n_min: int = N_MIN_DEFAULT,
    n_trimmed_threshold: int = N_TRIMMED_THRESHOLD,
    trim_fraction: float = TRIM_FRACTION,
) -> StateEstimate | None:
    """Return a StateEstimate for one bucket, or None if under-populated.

    - ``n >= n_trimmed_threshold``: plain sample mean and sample std,
      labelled ``data-driven``.
    - ``n_min <= n < n_trimmed_threshold``: 20%-trimmed mean and MAD-based
      sigma, labelled ``data-driven-trimmed``.
    - ``n < n_min``: returns None; downstream fills via fallback.
    """
    n = int(bucket.size)
    if n < n_min:
        return None
    if n >= n_trimmed_threshold:
        mu = float(np.mean(bucket))
        sigma = float(np.std(bucket, ddof=1)) if n > 1 else 0.0
        method: Method = "data-driven"
    else:
        mu = float(stats.trim_mean(bucket, trim_fraction))
        # MAD scaled to a Gaussian sigma. Fatter tails collapse to smaller
        # dispersion under this estimator, which is what we want for thin
        # buckets: don't let a single outlier inflate the reported sigma.
        mad = float(np.median(np.abs(bucket - np.median(bucket))))
        sigma = 1.4826 * mad
        method = "data-driven-trimmed"

    q05 = float(np.quantile(bucket, 0.05)) if n >= 10 else None
    q95 = float(np.quantile(bucket, 0.95)) if n >= 10 else None
    skew = float(stats.skew(bucket, bias=False)) if n >= 8 else None

    return StateEstimate(
        state=state,
        mu=mu,
        sigma=sigma,
        n_obs=n,
        method=method,
        q05=q05,
        q95=q95,
        skew=skew,
    )


def estimate_per_state_from_buckets(
    buckets: dict[int, np.ndarray],
    n_min: int = N_MIN_DEFAULT,
    n_trimmed_threshold: int = N_TRIMMED_THRESHOLD,
    trim_fraction: float = TRIM_FRACTION,
) -> dict[int, StateEstimate]:
    """Apply ``estimate_state_from_bucket`` to each bucket.

    Returns only the estimates that pass the sufficiency floor; under-populated
    states are dropped and handled downstream by ``fallbacks.py``.
    """
    out: dict[int, StateEstimate] = {}
    for s, bucket in buckets.items():
        est = estimate_state_from_bucket(s, bucket, n_min, n_trimmed_threshold, trim_fraction)
        if est is not None:
            out[s] = est
    return out


def annualise_estimate(est: StateEstimate, freq_per_year: int = 12) -> StateEstimate:
    """Convert a StateEstimate from decimal period-returns to annualised percent.

    - ``mu``: compound annualisation: ``((1 + mu_period) ** freq - 1) * 100``.
    - ``sigma``: sqrt-time scaling, then percent: ``sigma_period * sqrt(freq) * 100``.
    - ``q05``, ``q95``, ``skew``: cleared to None because their annualisation
      requires a distributional assumption we do not want to smuggle in.

    Applies only to sample estimates (``data-driven`` and
    ``data-driven-trimmed``). Fallback methods are passed through unchanged
    because their mu values are already in the target unit (annualised
    percent, matching the seed).
    """
    if est.method not in ("data-driven", "data-driven-trimmed"):
        return est
    mu_pct = ((1.0 + est.mu) ** freq_per_year - 1.0) * 100.0
    sigma_pct = (est.sigma * (freq_per_year ** 0.5) * 100.0) if est.sigma is not None else None
    return replace(est, mu=mu_pct, sigma=sigma_pct, q05=None, q95=None, skew=None)


def annualise_estimates(
    estimates: dict[int, StateEstimate],
    freq_per_year: int = 12,
) -> dict[int, StateEstimate]:
    return {s: annualise_estimate(e, freq_per_year) for s, e in estimates.items()}
