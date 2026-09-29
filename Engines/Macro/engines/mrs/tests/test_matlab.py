"""The engine against a literal transcription of the MATLAB (``matlab_reference.py``).

It pins the kernels, grids and column selection to ``Weights.m`` and ``Market_Signal.m``
across the input space. ``mrs`` publishes at zero shift; the four MATLAB optimism levels
are exercised through the reconciliation-only ``shifts`` argument, with the ``Weights.m``
signs, so the kernel maths is pinned wherever MATLAB ever ran it. ``test_golden.py`` adds
the recorded MATLAB output.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from mrs import calibration as seeds
from mrs.contracts import SEGMENTS
from mrs.engine import assess, column_for, grid, kernel_matrix

from .matlab_reference import SCALES, crs_row, pick, weights_m

CAL = seeds.PRODUCTION
OPTIMISM_SCALES = tuple(SCALES)


def shifts(optimism: str) -> dict[str, float]:
    """The grid shift per segment MATLAB applied at one ``Opti_Scale`` (Weights.m signs)."""
    return {k: SCALES[optimism] * v for k, v in seeds.WEIGHTS_M_OPTIMISM_SIGN.items()}
TOL = 1e-15

reading = st.floats(min_value=-6.0, max_value=6.0, allow_nan=False, allow_infinity=False)


@pytest.mark.parametrize("optimism", OPTIMISM_SCALES)
def test_kernel_matrices_equal_weights_m(optimism):
    reference = weights_m(optimism)
    for k, name in enumerate(SEGMENTS):
        spec = CAL.segment(name)
        ours = kernel_matrix(spec, CAL.edges.count) * spec.weight
        np.testing.assert_allclose(ours, reference[k], rtol=0, atol=TOL, err_msg=name)


@pytest.mark.parametrize("optimism", OPTIMISM_SCALES)
def test_grids_equal_weights_m(optimism):
    scales = weights_m(optimism)[4]
    for k, name in enumerate(SEGMENTS):
        np.testing.assert_allclose(grid(CAL, shifts(optimism)[name]), scales[k],
                                   rtol=0, atol=TOL, err_msg=name)


@settings(max_examples=400, deadline=None)
@given(value=reading, optimism=st.sampled_from(OPTIMISM_SCALES),
       segment=st.sampled_from(SEGMENTS))
def test_column_equals_matlab_loop_off_the_edges(value, optimism, segment):
    edges = grid(CAL, shifts(optimism)[segment])
    if np.any(edges == value):
        return  # exactly on an edge: see test_on_edge_divergence
    assert column_for(value, edges) == pick(value, edges)


@pytest.mark.parametrize("k", range(11))
def test_on_edge_divergence(k):
    """MRS-01, recorded rather than reproduced. A reading exactly on grid point k:
    MATLAB picks column 1 on an interior or top edge and assigns nothing on the bottom
    edge; the port uses half-open bins, so the point belongs to the bin it opens."""
    edges = grid(CAL, shifts("default")["business_cycle"])
    v = float(edges[k])
    ours = column_for(v, edges)
    theirs = pick(v, edges)
    if k == 0:
        assert theirs is None and ours == 1
    else:
        assert theirs == 1 and ours == k + 1


@settings(max_examples=300, deadline=None)
@given(values=st.tuples(reading, reading, reading, reading),
       optimism=st.sampled_from(OPTIMISM_SCALES))
def test_crs_row_equals_matlab(values, optimism):
    readings = dict(zip(SEGMENTS, values))
    for name, v in readings.items():
        if np.any(grid(CAL, shifts(optimism)[name]) == v):
            return
    expected, cols = crs_row(readings, optimism)
    a = assess({k: [v] for k, v in readings.items()}, 1, CAL, shifts=shifts(optimism))
    raw = np.array(a.distribution[0]) * a.raw_mass[0]
    np.testing.assert_allclose(raw, expected, rtol=0, atol=1e-14)
    assert a.raw_mass[0] == pytest.approx(expected.sum(), abs=1e-14)
    assert {k: v[0] for k, v in a.columns.items()} == cols


def test_matlab_policy_reads_missing_as_column_one():
    readings = {"business_cycle": math.nan, "investment": 0.3, "market_behaviour": -1.2,
                "market_stress": math.nan}
    expected, cols = crs_row(readings, "default")
    a = assess({k: [None if math.isnan(v) else v] for k, v in readings.items()}, 1,
               seeds.MATLAB, shifts=shifts("default"))
    np.testing.assert_allclose(np.array(a.distribution[0]) * a.raw_mass[0], expected,
                               rtol=0, atol=1e-14)
    assert a.columns["business_cycle"] == (1,) and a.columns["market_stress"] == (1,)
    assert cols["business_cycle"] == 1


def test_zero_shift_is_the_published_grid():
    """What mrs publishes: MATLAB's grid at "Defensive" (shift 0), linspace(-2, 2, 11)."""
    np.testing.assert_array_equal(grid(CAL), weights_m("defensive")[4][0])
