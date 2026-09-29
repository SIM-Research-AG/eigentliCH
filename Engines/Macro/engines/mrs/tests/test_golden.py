"""Golden: the port against the recorded MATLAB output, under the ``matlab`` calibration.

The CIO site exports of one ``MRS_Tester.m`` run (written 03.09.2026): ``assets`` (MATLAB's
``M_TS``, the input), ``stats`` (``Indices``: the sub-indicators and segment series) and
``signal`` (``WM``: the weighted kernel column per segment, economy and month). The run
used MATLAB's "Default" optimism, a +0.4 grid shift with the ``Weights.m`` signs; ``mrs``
publishes at zero shift, so the signal comparison applies that shift through the
reconciliation-only ``shifts`` argument of ``engine.assess``.

Findings (DECISIONS.md, MRS-20 and MRS-01):

* The export does **not** pair with the local ``M_TS.mat`` of 05.01.2026: it is a later
  pull, months 2006-09 to 2026-09 (the OIS flags agree exactly at an offset of 8 months).
  Its own input, ``assets``, is frozen beside it and is what the indicators run on here.
* On that input every sub-indicator and segment value matches ``stats`` to 1e-13
  (tolerance ruled by the owner: 1e-10), and 15,423 of the 15,424 kernel columns match
  ``signal`` to 1e-15. The one divergence is a reading exactly on a grid edge (MRS-01).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from mrs import calibration as seeds, reference, series
from mrs.contracts import INDICATORS, SEGMENTS
from mrs.engine import _wire, assess, grid, kernel_matrix
from mrs.indicators import compute, series_needed
from mrs.reference import sha256

from .conftest import CIO, GOLDEN

CAL = seeds.MATLAB
STATS_TOL = 1e-10          # owner's ruling, 27.09.2026
SIGNAL_TOL = 1e-14

#: mrs name -> (MATLAB segment struct, MATLAB field) in ``Indices``.
STATS_NAMES = {
    "inflation": ("BusinessCycle", "Inflation"), "monetary": ("BusinessCycle", "Monetary"),
    "consumer": ("BusinessCycle", "Consumer"), "company": ("BusinessCycle", "Company"),
    "bond": ("Investment", "Bond"), "equity": ("Investment", "Equity"),
    "trend_osc": ("MarketBehaviour", "Trend_Osc"), "fear_greed": ("MarketBehaviour", "Fear_Greed"),
    "global_stability": ("MarketStress", "Global_Stability"),
    "market_stability": ("MarketStress", "Market_Stability"),
    "monetary_uncertainty": ("MarketStress", "Monetary_Uncertainty"),
}
SEGMENT_FIELDS = {"business_cycle": "BusinessCycle", "investment": "Investment",
                  "market_behaviour": "MarketBehaviour", "market_stress": "MarketStress"}
#: MATLAB's "Default" (+0.4), with the Weights.m sign per segment.
DEFAULT_SHIFTS = {k: 0.4 * v for k, v in seeds.WEIGHTS_M_OPTIMISM_SIGN.items()}

#: The divergences, each classified (DECISIONS.md). Key: (MATLAB economy, segment, month).
CLASSIFIED = {
    ("Spain", "market_stress", 170): "MRS-01: reading exactly 2.0 on the shifted grid edge "
                                     "0.4 + 1.6; MATLAB column 1, port column 10",
}


def matlab_series(assets: dict, economy: str) -> dict[str, np.ndarray]:
    """One economy's input from the ``assets`` export, by datafeed series id."""
    out = {}
    for sid in series_needed(CAL.indicators):
        sheet, col = series.BY_ID[sid].matlab
        block = np.asarray(assets[economy][sheet], dtype=float)
        if block.ndim == 1:
            block = block[:, None]
        out[sid] = block[:, col - 1]
    return out


@pytest.fixture(scope="module")
def layers(cio):
    return {name: compute(matlab_series(cio["assets"], name), CAL.indicators)
            for name in reference.ECONOMIES}


def test_the_exports_are_the_frozen_ones():
    for kind in ("assets", "stats", "signal"):
        manifest = json.loads((CIO[kind].parent / "manifest.json").read_text(encoding="utf-8"))
        assert sha256(CIO[kind]) == manifest["sha256"], kind
        assert manifest["first_month"] == "2006-09" and manifest["months"] == 241


def test_the_export_is_a_later_pull_than_m_ts_mat(cio, frozen):
    """MRS-20: the OIS flags of the export's input agree with datafeed's raw snapshot of
    M_TS.mat (Jan 2006 to Jan 2026) exactly at an offset of 8 months, and at no other."""
    ours = next(s for s in frozen["panel"].series if s.country == "US" and s.series_id == "fx.ois_1y")
    ours = np.array([0.0 if v is None else v for v in ours.values]) > 0.01
    theirs = np.asarray(cio["assets"]["USA"]["FX"], dtype=float)[:, 7] > 0.01
    agree = {k: float(np.mean(ours[k:] == theirs[:241 - k])) for k in range(0, 13)}
    assert agree[8] == 1.0
    assert all(v < 1.0 for k, v in agree.items() if k != 8)


@pytest.mark.parametrize("name", INDICATORS)
def test_every_sub_indicator_matches_stats(cio, layers, name):
    worst = 0.0
    for economy, layer in layers.items():
        sheet, field = STATS_NAMES[name]
        ref = np.asarray(cio["stats"][economy][sheet][field], dtype=float)
        ours = layer.indicators[name]
        assert np.all(np.isfinite(ours)), f"{economy}/{name}: MATLAB exported no NaN here"
        worst = max(worst, float(np.max(np.abs(ours - ref))))
    assert worst <= STATS_TOL, f"{name}: {worst:.3g}"


@pytest.mark.parametrize("segment", SEGMENTS)
def test_every_segment_matches_stats(cio, layers, segment):
    worst = 0.0
    for economy, layer in layers.items():
        ref = np.asarray(cio["stats"][economy][f"TS_{SEGMENT_FIELDS[segment]}"], dtype=float)
        worst = max(worst, float(np.max(np.abs(layer.segments[segment] - ref))))
    assert worst <= STATS_TOL, f"{segment}: {worst:.3g}"


def test_fear_greed_is_zero_throughout_as_matlab_saw_it(layers):
    """The Fear Barometer input is empty in M_TS; MATLAB's NaN-to-0 makes the indicator 0.
    Reproduced, and the reason production reads Cboe SKEW instead (MRS-15)."""
    assert all(np.all(layer.indicators["fear_greed"] == 0.0) for layer in layers.values())


def test_every_kernel_column_matches_signal_but_the_classified(cio, layers):
    kernels = {s.name: kernel_matrix(s, CAL.edges.count) * s.weight for s in CAL.segments}
    found: dict[tuple[str, str, int], str] = {}
    compared = 0
    for economy, layer in layers.items():
        segments = {k: _wire(layer.segments[k]) for k in SEGMENTS}
        a = assess(segments, 241, CAL, shifts=DEFAULT_SHIFTS)
        for seg in SEGMENTS:
            for t in range(241):
                ref = np.asarray(cio["signal"][SEGMENT_FIELDS[seg]][t][economy], dtype=float)
                ours = kernels[seg][:, a.columns[seg][t] - 1]
                compared += 1
                if np.max(np.abs(ours - ref)) > SIGNAL_TOL:
                    found[(economy, seg, t + 1)] = f"column {a.columns[seg][t]}, reading {segments[seg][t]!r}"
    assert compared == 16 * 4 * 241
    assert set(found) == set(CLASSIFIED), found


def test_the_classified_divergence_is_on_an_edge(cio, layers):
    """MRS-01: MATLAB puts a reading exactly on an interior edge in column 1."""
    (economy, seg, month), = CLASSIFIED
    reading = float(layers[economy].segments[seg][month - 1])
    edges = grid(CAL, DEFAULT_SHIFTS[seg])
    assert reading in edges
    ref = np.asarray(cio["signal"][SEGMENT_FIELDS[seg]][month - 1][economy], dtype=float)
    assert np.all(ref == 0.0), "MATLAB's column 1 of the stress tail carries nothing"


def test_matlab_calibration_runs_on_the_frozen_raw_snapshot(frozen):
    """The matlab mode on datafeed's own input (MATLAB's view rebuilt from the raw snapshot):
    it runs end to end; there is no MATLAB output for this pull to compare with."""
    from mrs.engine import EconomyInput, run_model
    from mrs.inputs import matlab_view

    panel = frozen["panel"]
    countries = sorted({s.country for s in panel.series})
    needed = series_needed(CAL.indicators)
    views = {sid: matlab_view(panel, sid, countries, frozen["conversions"]) for sid in needed}
    out = run_model(panel.dates, [EconomyInput(c, c, {s: views[s][:, j] for s in needed})
                                  for j, c in enumerate(countries)], CAL)
    assert all(e.dates_unassessed == 0 for e in out.coverage.economies)
    assert len(out.economies) == 16 and GOLDEN.is_dir()
