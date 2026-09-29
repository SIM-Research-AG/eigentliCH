"""The regression that matters most: does the port reproduce the published figures?

Steiner (2021) published a 25-state profile for each of the eight blocks. This engine
recomputes them from the same workbooks through an entirely different implementation --
Python instead of MATLAB, hand-rolled numerics instead of builtins. If the two agree to
floating-point precision then the exponential fit, the seven linear de-trends, the
trailing volatility window, the N-1 standardisation, the phase bounds and the pchip
(including its extrapolated tails) are all correct simultaneously.

That is a stronger statement than any unit test on those pieces individually, and it is
the reason this file exists.
"""

from __future__ import annotations

import pytest

from engines.fund_map.calibrate import BLOCKS
from tests.conftest import needs_sources

#: Floating-point agreement. The observed worst error across all 200 values is about
#: 5e-16; this threshold is three orders of magnitude looser and would still catch any
#: real change of method.
TOLERANCE = 1e-12


@needs_sources
@pytest.mark.parametrize("block", [b.key for b in BLOCKS])
def test_block_profile_matches_published_reference(block, calibration, reference):
    computed = calibration["blocks"][block].profile_by_state
    published = reference[block]
    assert len(computed) == len(published) == 25
    for state, (got, want) in enumerate(zip(computed, published), start=1):
        assert abs(got - want) < TOLERANCE, (
            f"{block} state {state}: computed {got!r}, published {want!r}, "
            f"difference {got - want:.3e}"
        )


@needs_sources
def test_phase_counts_are_the_published_partition(calibration):
    """150 years, split the way the reference splits them."""
    assert calibration["timeline"].counts() == {
        "crisis": 24, "contraction": 16, "stagnation": 25, "expansion": 74, "boom": 11,
    }


@needs_sources
def test_economic_cycle_is_standardised(calibration):
    from engines.fund_map import numerics as num
    cycle = calibration["environment"].cycle
    assert len(cycle) == 150
    assert abs(num.mean(cycle)) < 1e-12
    assert abs(num.std(cycle) - 1.0) < 1e-12


@needs_sources
def test_truncated_blocks_keep_their_own_windows(calibration):
    """Truncation is handled by matching where the series exists, never by back-filling."""
    windows = {
        k: (v.first_year, v.last_year, v.n_obs_total)
        for k, v in calibration["blocks"].items()
    }
    assert windows["gov_bonds"] == (1871, 2015, 145)
    assert windows["real_estate"] == (1891, 2020, 130)
    assert windows["agriculture"] == (1911, 2020, 110)
    assert windows["equity"] == (1871, 2020, 150)


@needs_sources
def test_calibration_is_deterministic(long_record):
    """Identical inputs must produce an identical content id, or the audit story fails."""
    from engines.fund_map.service import run_calibration
    first = run_calibration(long_record)
    second = run_calibration(long_record)
    assert first.calibration_id == second.calibration_id
    assert first.calibration_id.startswith("CAL-")
