"""Golden reconciliation against the old ``macrofield`` build (Engine Building Guide 6.1).

``golden/<code>.json`` is the old build's output for one economy, frozen offline from its own
cache by ``dev/freeze_golden.py`` (state of 2026-08-03). ``data/raw`` holds the same cached
files, so this compares like with like.

Declared tolerance: every assembled input, identity, phase and diagnostic reproduces **exactly**
(relative difference 0), and the fitted parameters and simulated paths to a relative 1e-9, the
margin allowed for a different BLAS or scipy patch release. On the build machine they too
reproduce exactly.

One intentional divergence, classified per 6.1: where the fitted path integrates at neither
tolerance, the old build labelled the accuracy ``search`` while reporting no path; this engine
labels it ``none``. Japan and France are not reconciled: Japan fails in the old build itself (no
fiscal balance) and France is outside the HoNI universe.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from macrofield.calibration import V1_0_0
from macrofield.engine import run_economy

from .conftest import GOLDEN

CODES = sorted(p.stem.upper() for p in GOLDEN.glob("*.json"))
FIT_RTOL = 1e-9

pytestmark = pytest.mark.slow


def arr(values) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def exact(a, b) -> None:
    np.testing.assert_array_equal(arr(a), arr(b))


@pytest.fixture(scope="module", params=CODES)
def pair(request, raw_observations):
    code = request.param
    golden = json.loads((GOLDEN / f"{code.lower()}.json").read_text(encoding="utf-8"))
    state = run_economy(V1_0_0.economy(code), raw_observations[code], V1_0_0)
    return state, golden


def test_window_and_inputs_reproduce_exactly(pair):
    s, g = pair
    assert s.status == "ok"
    assert list(s.years) == g["periods"]
    for ours, theirs in ((s.observed.Y, "Y"), (s.observed.K_R, "K_R"), (s.observed.K_I, "K_I"),
                         (s.inputs.p_s, "p_s"), (s.inputs.S, "S"),
                         (s.inputs.saturation, "saturation"),
                         (s.inputs.population_growth, "population_growth")):
        exact(ours, g["inputs"][theirs])
    assert s.capital_normalisation.scale == g["capital_normalisation"]["scale"]


def test_identities_reproduce_exactly(pair):
    s, g = pair
    for name in ("r", "alpha", "p_p", "p_b"):
        exact(getattr(s.identities, name), g["identities"][name])


def test_phases_and_diagnostics_reproduce_exactly(pair):
    s, g = pair
    assert list(s.diagnostics.phase) == g["phases"]
    assert list(s.diagnostics.in_balanced_band) == g["in_balanced_band"]
    exact(s.diagnostics.unsecured_ratio, g["unsecured_ratio"])


def test_fit_reproduces_within_tolerance(pair):
    s, g = pair
    gc = g["calibration"]
    for name, value in gc["free_parameters"].items():
        assert s.fit.free_parameters[name] == pytest.approx(value, rel=FIT_RTOL)
    assert s.fit.converged == gc["converged"]
    if gc["simulated"]["Y"]:
        assert s.fit.integration_accuracy == gc["integration_accuracy"]
        for name in ("Y", "K_R", "K_I"):
            np.testing.assert_allclose(arr(getattr(s.simulated, name)),
                                       arr(gc["simulated"][name]), rtol=FIT_RTOL)
    else:
        # Intentional divergence: the old build said "search" with no path.
        assert s.simulated is None and s.fit.integration_accuracy == "none"
