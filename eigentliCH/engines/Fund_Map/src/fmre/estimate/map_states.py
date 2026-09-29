"""Bucket state-tagged returns into per-state groups (spec 5.1).

Every return period is tagged with the state active in that period, then
grouped. No observation is dropped or double-counted; the total observation
count across all state buckets equals the length of the input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def bucket_returns_by_state(aligned: pd.DataFrame, state_grid: int = 25) -> dict[int, np.ndarray]:
    """Group returns by regime state.

    ``aligned`` must have columns ``return`` and ``state`` (as produced by
    ``RegimeTimeline.align_returns``). Returns a dict ``{state: array of
    returns}`` for states that appear at least once. States with zero
    observations do not appear as keys.
    """
    if not {"return", "state"}.issubset(aligned.columns):
        raise ValueError("bucket_returns_by_state: expected columns 'return' and 'state'")
    states = aligned["state"].to_numpy()
    if states.size and (states.min() < 0 or states.max() >= state_grid):
        raise ValueError(
            f"bucket_returns_by_state: states outside 0..{state_grid - 1}: "
            f"min={int(states.min())}, max={int(states.max())}"
        )
    out: dict[int, np.ndarray] = {}
    returns = aligned["return"].to_numpy(dtype=float)
    for s in np.unique(states):
        mask = states == s
        out[int(s)] = returns[mask]
    total_bucketed = sum(v.size for v in out.values())
    assert total_bucketed == len(aligned), (
        f"bucket totals ({total_bucketed}) must equal input length ({len(aligned)})"
    )
    return out
