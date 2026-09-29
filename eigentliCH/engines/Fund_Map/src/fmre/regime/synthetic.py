"""Synthetic RegimeTimeline builder for testing.

Deterministic Markov-chain of states with high self-persistence. Not a model
of the real macro Regime; a stand-in that satisfies the spec 3.4 contract so
the estimator can be built and tested end-to-end before the real timeline is
wired in.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fmre.regime.timeline import STATE_GRID, RegimeSnapshot, RegimeTimeline


def build_synthetic_timeline(
    start: date = date(1998, 1, 31),
    end: date = date(2024, 12, 31),
    economy_scope: str = "Global",
    persistence: float = 0.9,
    mid_state: int = STATE_GRID // 2,
    seed: int = 20260728,
) -> RegimeTimeline:
    """Build a valid spec-3.4 RegimeTimeline at monthly frequency.

    ``persistence`` is the probability the state is unchanged from one month
    to the next. On a transition, the state random-walks one step in either
    direction, clamped to ``[0, STATE_GRID - 1]``. Determinism is guaranteed
    by the ``seed`` alone.
    """
    if not (0.0 <= persistence <= 1.0):
        raise ValueError(f"persistence must be in [0, 1], got {persistence}")
    if not (0 <= mid_state < STATE_GRID):
        raise ValueError(f"mid_state {mid_state} out of range")

    rng = np.random.default_rng(seed)
    index = pd.date_range(start, end, freq="ME")
    n = len(index)
    if n == 0:
        raise ValueError("build_synthetic_timeline: date range is empty")

    states = np.empty(n, dtype=int)
    states[0] = mid_state
    for t in range(1, n):
        if rng.random() < persistence:
            states[t] = states[t - 1]
        else:
            step = 1 if rng.random() < 0.5 else -1
            states[t] = int(np.clip(states[t - 1] + step, 0, STATE_GRID - 1))

    ser = pd.Series(states, index=index, name="state")
    current = RegimeSnapshot(
        regime_id=f"REG-SYNTHETIC-{seed}",
        state=int(states[-1]),
        phase=None,
        saturation_pct=None,
    )
    return RegimeTimeline(
        regime_timeline_id=f"RTL-SYNTHETIC-{seed}",
        economy_scope=economy_scope,
        model_version="synthetic@0.1.0",
        as_of=index[-1].strftime("%Y-%m-%d"),
        period="M",
        state_grid=STATE_GRID,
        path=ser,
        current=current,
        provenance={
            "data_vintage": index[-1].strftime("%Y-%m"),
            "sources": ["synthetic"],
            "seed": seed,
        },
    )


def timeline_to_dict(timeline: RegimeTimeline) -> dict[str, Any]:
    """Serialise a RegimeTimeline back to the spec-3.4 contract payload."""
    fmt_map = {"M": "%Y-%m", "Q": "%Y-Q%q", "A": "%Y"}
    fmt = fmt_map.get(timeline.period, "%Y-%m")
    if fmt == "%Y-Q%q":
        # pandas doesn't do %q; build manually
        path_dates = [
            f"{d.year}-Q{((d.month - 1) // 3) + 1}" for d in timeline.path.index
        ]
    else:
        path_dates = [pd.Timestamp(d).strftime(fmt) for d in timeline.path.index]

    current: dict[str, Any] = {
        "regime_id": timeline.current.regime_id,
        "state": timeline.current.state,
    }
    if timeline.current.phase is not None:
        current["phase"] = timeline.current.phase
    if timeline.current.saturation_pct is not None:
        current["saturation_pct"] = timeline.current.saturation_pct

    return {
        "regime_timeline_id": timeline.regime_timeline_id,
        "economy_scope": timeline.economy_scope,
        "model_version": timeline.model_version,
        "as_of": timeline.as_of,
        "period": timeline.period,
        "state_grid": timeline.state_grid,
        "path": [
            {"date": d, "state": int(s)}
            for d, s in zip(path_dates, timeline.path.tolist())
        ],
        "current": current,
        "provenance": dict(timeline.provenance),
    }
