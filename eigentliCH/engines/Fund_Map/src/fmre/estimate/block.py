"""Per-block estimator orchestration.

Composes state bucketing, per-state estimation, and the fallback cascade
into one BlockEstimate carrying its coverage grade and method labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pandas as pd

from fmre.estimate.fallbacks import (
    borrow_from_peers,
    interpolate_missing_states,
    seed_fallback,
)
from fmre.estimate.map_states import bucket_returns_by_state
from fmre.estimate.per_state import (
    FREQ_PER_YEAR,
    N_MIN_DEFAULT,
    Method,
    StateEstimate,
    annualise_estimates,
    estimate_per_state_from_buckets,
)

if TYPE_CHECKING:
    from fmre.registers.building_blocks import BuildingBlock


Coverage = Literal["full", "partial", "borrowed", "seed"]

_METHOD_RANK: dict[Method, int] = {
    "data-driven": 0,
    "data-driven-trimmed": 0,
    "interpolated": 1,
    "borrowed": 2,
    "seed": 3,
}


def _coverage_from_methods(methods: list[Method]) -> Coverage:
    worst = max(_METHOD_RANK[m] for m in methods)
    return ("full", "partial", "borrowed", "seed")[worst]


@dataclass(frozen=True, slots=True)
class BlockEstimate:
    block_id: int
    ticker: str
    canonical_role: str
    region: str
    states: tuple[StateEstimate, ...]  # length state_grid, ordered by state index
    calibration_window: tuple[str, str] | None = None
    n_obs_total: int = 0
    mu_unit: str = "annualised_pct"  # after annualisation in estimate_block

    def __post_init__(self) -> None:
        for i, s in enumerate(self.states):
            if s.state != i:
                raise ValueError(
                    f"BlockEstimate id={self.block_id}: states must be ordered by index "
                    f"(states[{i}].state = {s.state})"
                )

    @property
    def profile_by_state(self) -> tuple[float, ...]:
        return tuple(s.mu for s in self.states)

    @property
    def n_obs_by_state(self) -> tuple[int, ...]:
        return tuple(s.n_obs for s in self.states)

    @property
    def methods(self) -> tuple[Method, ...]:
        return tuple(s.method for s in self.states)

    @property
    def coverage(self) -> Coverage:
        return _coverage_from_methods(list(self.methods))


def estimate_block(
    block: "BuildingBlock",
    aligned: pd.DataFrame,
    all_estimates: dict[int, BlockEstimate] | None = None,
    all_blocks: dict[int, "BuildingBlock"] | None = None,
    state_grid: int = 25,
    n_min: int = N_MIN_DEFAULT,
    calibration_window: tuple[str, str] | None = None,
    annualise_from: str | None = "M",
) -> BlockEstimate:
    """Estimate one block end-to-end.

    ``aligned`` is the state-tagged returns DataFrame from
    ``RegimeTimeline.align_returns``. ``all_estimates`` and ``all_blocks``
    are optional; when supplied, the ``borrowed`` fallback uses them to
    average across role-and-region peers already estimated. Without peers,
    the cascade skips to ``seed``.

    ``annualise_from``: source periodicity (``"M"`` / ``"Q"`` / ``"A"``).
    When set, sample per-state estimates are annualised to percent before
    the fallback cascade so all fallbacks operate in the same unit as the
    seed (annualised percent). Pass ``None`` to skip annualisation (test-
    only path; the block's ``mu_unit`` will be flagged as ``"source"``).
    """
    buckets = bucket_returns_by_state(aligned, state_grid=state_grid)
    per_state = estimate_per_state_from_buckets(buckets, n_min=n_min)

    if annualise_from is not None:
        freq = FREQ_PER_YEAR[annualise_from]
        per_state = annualise_estimates(per_state, freq_per_year=freq)
        mu_unit = "annualised_pct"
    else:
        mu_unit = "source"

    filled = interpolate_missing_states(per_state, state_grid=state_grid)

    still_missing = state_grid - len(filled)
    if still_missing > 0 and all_estimates is not None and all_blocks is not None:
        filled = borrow_from_peers(block, filled, all_estimates, all_blocks, state_grid=state_grid)
    if state_grid - len(filled) > 0:
        filled = seed_fallback(block, filled, state_grid=state_grid)

    states = tuple(filled[i] for i in range(state_grid))
    return BlockEstimate(
        block_id=block.id,
        ticker=block.ticker,
        canonical_role=block.canonical_role.value,
        region=block.region.value,
        states=states,
        calibration_window=calibration_window,
        n_obs_total=int(len(aligned)),
        mu_unit=mu_unit,
    )
