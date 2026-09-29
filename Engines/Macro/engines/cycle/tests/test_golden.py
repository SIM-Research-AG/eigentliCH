"""Golden reconciliation (Engine Building Guide section 6.1; engine page section 5).

Declared tolerance for this engine: **1e-12 absolute** on every figure.

A. **Against the first draft.** ``draft_1.0.0.json`` is the output of the draft's own
   ``cycles.py`` and ``cycle_bins.py`` (with statsmodels' filter) on inputs this engine
   prepared from the frozen production snapshot. The port must reproduce every figure the
   draft publishes, on every economy the draft can run. The one classified divergence is
   C-09: where a cycle has no position, the draft voids the first year of the layer (a flat
   row); this build leaves that cycle off instead.

C. **Against this build.** ``expected_1.0.0.json``, and ``expected_1.1.0.json`` for the active
   calibration on the frozen macrofield state: regression references that catch any
   unintended change. They are not evidence of correctness.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from cycle.calibration import DEFAULT, HISTORICAL_RESETS
from cycle.clients import panel_checksum, state_checksum
from cycle.contracts import STATE_COUNT
from cycle.engine import run_model

from .conftest import MACROFIELD_ARTEFACT, SNAPSHOT

TOLERANCE = 1e-12
ECONOMIES = ["BR", "CH", "CN", "EU", "IN", "ID", "MY", "PH", "TH", "GB", "US", "JP", "BD", "VN", "DE", "ES"]


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= TOLERANCE)))


@pytest.fixture(scope="module")
def built(panel):
    return run_model(panel, DEFAULT, ECONOMIES, {c: c for c in ECONOMIES})


def test_the_frozen_input_is_datafeeds_production_snapshot(panel):
    source = json.loads((SNAPSHOT / "source.json").read_text(encoding="utf-8"))
    assert panel.snapshot_id == source["snapshot_id"] == "matlab-m_ts-2026-01-05.public-8e90be47"
    assert panel_checksum(panel) == source["datafeed_checksum"]


class TestAgainstTheDraft:
    def test_it_covers_every_economy_with_complete_inputs(self, draft, built):
        complete = {e.code for e in built.economies
                    if all(p is not None for t in e.cycles if t.kind == "estimated" and t.identifiable
                           for p in t.phase)}
        assert set(draft["economies"]) == complete
        assert len(draft["economies"]) >= 14

    def test_the_estimated_and_anchored_cycles(self, draft, built):
        for e in built.economies:
            ref = draft["economies"].get(e.code)
            if ref is None:
                continue
            for t in e.cycles:
                r = ref["cycles"][t.cycle]
                assert t.identifiable == r["identifiable"], (e.code, t.cycle)
                if not t.identifiable:
                    continue
                assert close(t.component, r["component"]), (e.code, t.cycle, "component")
                assert close(t.angle, r["phase"]), (e.code, t.cycle, "phase")
                assert close(t.amplitude, r["amplitude"]), (e.code, t.cycle, "amplitude")
                assert close(t.period_years, r["estimated_period"]), (e.code, t.cycle, "period")
                if t.anchored:
                    a = ref["anchored"][t.cycle]
                    assert close(t.reference_year, a["reference_year"])
                    assert close(t.years_into_cycle, a["years_into_cycle"])

    def test_superposition_alignment_and_synchrony(self, draft, built):
        for e in built.economies:
            ref = draft["economies"].get(e.code)
            if ref is None:
                continue
            assert close(e.superposition, ref["superposition"]), e.code
            assert close(e.alignment, ref["alignment"]), e.code
            assert len(e.synchrony_windows) == len(ref["synchrony_windows"]), e.code
            for w, r in zip(e.synchrony_windows, ref["synchrony_windows"]):
                assert (w.start_year, w.end_year, list(w.cycles)) == (r["start_year"], r["end_year"], r["cycles"])
                assert close(w.mean_absolute_phase_spread, r["mean_absolute_phase_spread"]), e.code

    def test_the_layer_differs_only_where_c09_says(self, draft, built):
        voided = 0
        for e in built.economies:
            ref = draft["economies"].get(e.code)
            if ref is None:
                continue
            assert close(e.layer[1:], ref["layer"][1:]), e.code
            if all(t.identifiable for t in e.cycles):
                assert close(e.layer[0], ref["layer"][0]), e.code
            else:
                # C-09: the draft's first row is flat, the port's is the mixture of the rest.
                assert close(ref["layer"][0], [1.0 / STATE_COUNT] * STATE_COUNT), e.code
                voided += 1
        assert voided > 0


def test_the_frozen_macrofield_state_is_intact(macrofield_frozen):
    from cycle.contracts import UpstreamMacroState
    state = UpstreamMacroState.model_validate(macrofield_frozen["state"])
    assert state.artefact_id == MACROFIELD_ARTEFACT
    assert state_checksum(state) == macrofield_frozen["state_sha256"]


def _unchanged(built, expected):
    assert list(built.years) == expected["years"]
    assert built.coverage.model_dump(mode="json") == expected["coverage"]
    for e, ref in zip(built.economies, expected["economies"]):
        got = e.model_dump(mode="json")
        for key in ("layer", "superposition", "alignment", "layer_mean_bin"):
            assert close(got[key], ref[key]), (e.code, key)
        for t, rt in zip(got["cycles"], ref["cycles"]):
            assert t["phase"] == rt["phase"], (e.code, t["cycle"])
            for key in ("angle", "level", "component", "bin_centre", "bin_width", "bin_skew"):
                assert close(t[key], rt[key]), (e.code, t["cycle"], key)


def test_this_build_is_unchanged(built, expected_build):
    _unchanged(built, expected_build)


def test_the_active_calibration_is_unchanged(panel, macro, expected_active):
    assert expected_active["macrofield_artefact"] == MACROFIELD_ARTEFACT
    _unchanged(run_model(panel, HISTORICAL_RESETS, ECONOMIES, {c: c for c in ECONOMIES}, macro), expected_active)
