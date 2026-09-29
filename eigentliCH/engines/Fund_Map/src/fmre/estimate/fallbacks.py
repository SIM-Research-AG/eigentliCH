"""Fallbacks for under-populated state buckets (spec 5.3).

Cascade in order:
    1. Interpolate across the ordered state axis from neighbouring
       estimated states, shape-preserving (PCHIP), labelled ``interpolated``.
    2. Borrow from the role-and-region peer profile, labelled ``borrowed``.
    3. Use the block's seed IC value, labelled ``seed``.

Every filled value carries its method label and ``n_obs = 0``. No silent
fills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.interpolate import PchipInterpolator

from fmre.estimate.per_state import StateEstimate

if TYPE_CHECKING:
    from fmre.registers.building_blocks import BuildingBlock


def interpolate_missing_states(
    estimates: dict[int, StateEstimate],
    state_grid: int = 25,
) -> dict[int, StateEstimate]:
    """Fill missing states by monotone-preserving PCHIP interpolation over
    the ordered state axis, using the mu values of ``estimates`` as knots.

    Only interpolates INSIDE the convex hull of known states (no
    extrapolation). States outside the hull remain unfilled and must be
    handled by ``borrow_from_peers`` or ``seed_fallback``.

    A minimum of 2 known states is required to interpolate. With one or zero
    known states, no interpolation is done.
    """
    known = sorted(estimates.keys())
    if len(known) < 2:
        return dict(estimates)
    mus = np.array([estimates[s].mu for s in known], dtype=float)
    pchip = PchipInterpolator(np.array(known, dtype=float), mus, extrapolate=False)

    out = dict(estimates)
    lo, hi = known[0], known[-1]
    for s in range(state_grid):
        if s in out:
            continue
        if lo <= s <= hi:
            val = float(pchip(s))
            if not np.isnan(val):
                out[s] = StateEstimate(
                    state=s,
                    mu=val,
                    sigma=None,
                    n_obs=0,
                    method="interpolated",
                )
    return out


_BORROWABLE_METHODS = frozenset({"data-driven", "data-driven-trimmed", "interpolated"})


def _select_peers(
    target: "BuildingBlock",
    all_estimates: dict[int, "BlockEstimate"],
    all_blocks: dict[int, "BuildingBlock"],
) -> list["BuildingBlock"]:
    """Pick role-and-region peers that have at least one non-fallback state.

    Fallback tier 1: same role AND same region.
    Fallback tier 2: same role (any region).
    A peer's state counts as "non-fallback" if its method is
    ``data-driven``, ``data-driven-trimmed``, or ``interpolated``.

    **Note on a change that was made here and reverted on 2 August 2026.** Asset class was briefly added
    to both tiers, on the theory that role is a functional label and borrowing a return profile from a
    different asset class has no economic reading. That reasoning still looks sound in the abstract, but
    it was reverted because the defect it claimed to fix did not exist: the published ReturnSet contains
    no ``borrowed`` state at all, at either 54 or 8 blocks, so the change was inert and unmeasurable.
    Whether same-role-different-class borrowing is safe is therefore still an open question — it is
    simply not one this cascade currently exercises. Do not re-tighten it without first constructing a
    register that actually reaches the ``borrowed`` tier, so the effect can be measured.
    """
    def _has_own_data(bb_id: int) -> bool:
        e = all_estimates.get(bb_id)
        return e is not None and any(st.method in _BORROWABLE_METHODS for st in e.states)

    same_role_region = [
        b for b in all_blocks.values()
        if b.id != target.id
        and b.role is target.role
        and b.region is target.region
        and _has_own_data(b.id)
    ]
    if same_role_region:
        return same_role_region
    return [
        b for b in all_blocks.values()
        if b.id != target.id
        and b.role is target.role
        and _has_own_data(b.id)
    ]


def borrow_from_peers(
    target: "BuildingBlock",
    estimates: dict[int, StateEstimate],
    all_estimates: dict[int, "BlockEstimate"],
    all_blocks: dict[int, "BuildingBlock"],
    state_grid: int = 25,
) -> dict[int, StateEstimate]:
    """Fill missing states from role-and-region peers, state-by-state.

    For each missing state ``s``, borrow ONLY from peers whose ``s`` is
    itself data-driven, trimmed, or interpolated — never from a peer's own
    borrow or seed value (which would just propagate stale fallbacks
    laterally across the role). If no peer has a non-fallback value for
    state ``s``, that state stays missing and falls through to the next
    tier of the cascade (usually the target's own seed value).
    """
    peers = _select_peers(target, all_estimates, all_blocks)
    if not peers:
        return dict(estimates)
    out = dict(estimates)
    for s in range(state_grid):
        if s in out:
            continue
        contributing = [
            all_estimates[p.id].states[s]
            for p in peers
            if all_estimates[p.id].states[s].method in _BORROWABLE_METHODS
        ]
        if not contributing:
            continue
        mu_avg = sum(st.mu for st in contributing) / len(contributing)
        out[s] = StateEstimate(
            state=s,
            mu=float(mu_avg),
            sigma=None,
            n_obs=0,
            method="borrowed",
        )
    return out


def seed_fallback(
    target: "BuildingBlock",
    estimates: dict[int, StateEstimate],
    state_grid: int = 25,
) -> dict[int, StateEstimate]:
    """Last-resort fill from the block's seed ret_distribution. Every filled
    state gets ``method='seed'``.
    """
    out = dict(estimates)
    for s in range(state_grid):
        if s not in out:
            out[s] = StateEstimate(
                state=s,
                mu=float(target.ret_distribution[s]),
                sigma=None,
                n_obs=0,
                method="seed",
            )
    return out
