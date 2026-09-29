r"""Mixture recomposition identity (spec 5.2).

Validation check, not an estimator. With empirical frequencies ``pi_s`` and
per-state sample moments computed on the SAME observation set:

    mu    = sum_s pi_s * mu_s
    Var(R) = sum_s pi_s * sigma_s^2  +  sum_s pi_s * (mu_s - mu)^2
             \____ within regime ____/   \___ between regimes ___/

Both identities hold EXACTLY on empirical moments up to floating point.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class MixtureDecomposition:
    mu_unconditional: float
    mu_recomposed: float
    var_unconditional: float
    var_within: float
    var_between: float

    @property
    def mu_error(self) -> float:
        return abs(self.mu_unconditional - self.mu_recomposed)

    @property
    def var_error(self) -> float:
        return abs(self.var_unconditional - (self.var_within + self.var_between))


def empirical_mixture_decomposition(aligned: pd.DataFrame) -> MixtureDecomposition:
    """Compute the mixture decomposition on a state-tagged returns DataFrame.

    Uses population moments (ddof=0) so the identity closes exactly.
    """
    if not {"return", "state"}.issubset(aligned.columns):
        raise ValueError("empirical_mixture_decomposition: expected columns 'return' and 'state'")
    if aligned.empty:
        raise ValueError("empirical_mixture_decomposition: empty input")

    returns = aligned["return"].to_numpy(dtype=float)
    states = aligned["state"].to_numpy()
    n_total = returns.size

    mu_unc = float(returns.mean())
    var_unc = float(returns.var(ddof=0))

    var_within = 0.0
    var_between = 0.0
    mu_rec = 0.0
    for s in np.unique(states):
        mask = states == s
        bucket = returns[mask]
        pi = bucket.size / n_total
        mu_s = float(bucket.mean())
        var_s = float(bucket.var(ddof=0))
        mu_rec += pi * mu_s
        var_within += pi * var_s
        var_between += pi * (mu_s - mu_unc) ** 2

    return MixtureDecomposition(
        mu_unconditional=mu_unc,
        mu_recomposed=mu_rec,
        var_unconditional=var_unc,
        var_within=var_within,
        var_between=var_between,
    )


def mixture_recompose_error(aligned: pd.DataFrame) -> tuple[float, float]:
    """Convenience: return ``(mu_error, var_error)`` from the decomposition."""
    d = empirical_mixture_decomposition(aligned)
    return d.mu_error, d.var_error
