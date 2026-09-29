"""Golden reconciliation (Engine Building Guide section 6.1).

MATLAB is retired as a reference (D-28): the current build is the reference, and layers A
and B below are kept as regression checks on the port, not as the authority.

Declared tolerance for this engine: **1e-12 absolute** on every figure.

There is no input that matches the one MATLAB export we hold: ``HoNI_Export.xlsx``
(2025-11-13) was produced from an ``M_TS.mat`` that has since been overwritten by the
2026-01-05 pull, and MATLAB annualised by taking every 12th month counted from the run
date, so even unrevised series moved (D-11). The reconciliation is therefore split into
three layers, each against the strongest reference available for it:

A. **Scoring and aggregation** (manual sections 5 and 6) against the MATLAB export itself.
   The export publishes its raw indicator values next to its scores, so the raw values
   go in and MATLAB's own scores, sector scores and national scores must come out.

B. **Indicator formulas** (manual section 4) against a line-for-line transliteration of the
   ``HN_*.m`` functions, on the frozen 2026-01-05 panel, on every cell no documented defect
   can touch. The comparison must cover most of the panel, or it proves nothing.

C. **End to end** against the frozen output of this build on the same panel: a regression
   reference that catches any unintended change. It is not evidence of correctness.

Divergences are classified, never patched away: layer A's second test asserts that under
the default calibration the only differences from MATLAB are the cells defect 9.1 covers.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from honi.calibration import DEFAULT, MATLAB
from honi.contracts import INDICES, SECTORS
from honi.engine import REQUIRED_SERIES, compute_indicators, growth, run_model, score_annual

from . import matlab_reference as ref
from .conftest import SNAPSHOT

TOLERANCE = 1e-12


def test_the_frozen_input_is_datafeeds_raw_snapshot(panel):
    """honi's golden input must be exactly what datafeed serves for the raw snapshot."""
    from honi.clients import panel_checksum
    source = json.loads((SNAPSHOT / "source.json").read_text(encoding="utf-8"))
    assert panel_checksum(panel) == source["datafeed_checksum"]


def test_datafeed_still_serves_it(panel, datafeed):
    """The frozen input (the 21-series import) equals what datafeed's current raw snapshot
    serves for honi's series, cell by cell."""
    import httpx

    params = [("snapshot_id", datafeed["raw"])] + [("series", s) for s in REQUIRED_SERIES]
    live = httpx.get(f"{datafeed['url']}/panel", params=params, timeout=60).json()
    assert live["dates"] == list(panel.dates)
    frozen = {(s.country, s.series_id): (list(s.values), list(s.flags)) for s in panel.series}
    served = {(s["country"], s["series_id"]): (s["values"], s["flags"]) for s in live["series"]}
    assert served == frozen


def arr(matrix) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in matrix], dtype=float)


def assert_close(actual: np.ndarray, expected: np.ndarray, what: str) -> None:
    assert actual.shape == expected.shape, what
    both_missing = np.isnan(actual) & np.isnan(expected)
    assert np.array_equal(np.isnan(actual), np.isnan(expected)), f"{what}: missing cells differ"
    diff = np.abs(np.where(both_missing, 0.0, actual - expected))
    assert diff.max() <= TOLERANCE, f"{what}: max abs diff {diff.max():.3e}"


# ---------------------------------------------------------------------------
# A. Scoring and aggregation against the MATLAB export
# ---------------------------------------------------------------------------

class TestMatlabExport:
    @pytest.fixture(scope="class")
    def scored(self, matlab_export):
        raw = {k: arr(v) for k, v in matlab_export["index_raw"].items()}
        return score_annual(matlab_export["years"], matlab_export["countries"], raw,
                            arr(matlab_export["capital_saturation"]), MATLAB)

    def test_the_fixture_is_complete(self, matlab_export):
        assert len(matlab_export["years"]) == 21
        assert len(matlab_export["countries"]) == 16
        assert set(matlab_export["index_raw"]) == set(INDICES)

    @pytest.mark.parametrize("index", list(INDICES))
    def test_index_scores_reconcile(self, scored, matlab_export, index):
        assert_close(scored.index_scores[index], arr(matlab_export["index_scores"][index]), index)

    @pytest.mark.parametrize("sector", SECTORS)
    def test_sector_scores_reconcile(self, scored, matlab_export, sector):
        assert_close(scored.sectors[sector], arr(matlab_export["sectors"][sector]), sector)

    def test_national_scores_reconcile(self, scored, matlab_export):
        assert_close(scored.national, arr(matlab_export["national"]), "national")

    def test_default_calibration_departs_only_where_data_is_missing(self, matlab_export):
        """Defect 9.1, classified: identical scores where the raw value exists; where it
        does not, MATLAB scores 1 and the default calibration leaves a gap."""
        raw = {k: arr(v) for k, v in matlab_export["index_raw"].items()}
        fixed = score_annual(matlab_export["years"], matlab_export["countries"], raw,
                             arr(matlab_export["capital_saturation"]), DEFAULT)
        gaps = 0
        for index in INDICES:
            matlab = arr(matlab_export["index_scores"][index])
            present = np.isfinite(raw[index])
            assert np.abs(fixed.index_scores[index][present] - matlab[present]).max() <= TOLERANCE
            assert np.isnan(fixed.index_scores[index][~present]).all()
            assert (matlab[~present] == 1.0).all(), "MATLAB scored a gap as something other than 1"
            gaps += int((~present).sum())
        assert gaps > 0, "the export has no gaps, so this test would prove nothing"


# ---------------------------------------------------------------------------
# B. Indicator formulas against the MATLAB transliteration
# ---------------------------------------------------------------------------

class TestIndicatorFormulas:
    @pytest.fixture(scope="class")
    def sampled(self, panel):
        """MATLAB's annual view: every 12th month from the first row (HoNI2.m A_TS)."""
        countries = sorted({s.country for s in panel.series})
        lookup = {(s.country, s.series_id): s.values for s in panel.series}
        rows = range(0, len(panel.dates), 12)
        engine_view, matlab_view = {}, {}
        for series_id in REQUIRED_SERIES:
            m = np.array([[lookup[(c, series_id)][t] for c in countries] for t in rows], dtype=object)
            engine_view[series_id] = np.where(m == None, np.nan, m).astype(float)  # noqa: E711
            matlab_view[series_id] = np.where(m == None, 0.0, m).astype(float)     # noqa: E711
        return countries, engine_view, matlab_view

    def test_formulas_match_on_every_untouched_cell(self, sampled):
        countries, engine_view, matlab_view = sampled
        ours = compute_indicators(engine_view, DEFAULT.trailing_window, DEFAULT.trailing_min_obs)
        theirs = ref.indicators(matlab_view, countries)
        compared = total = 0
        for index, (deps, lag) in ref.DEPENDENCIES.items():
            clean = np.ones(ours[index].shape, dtype=bool)
            for series_id in deps:
                ok = np.isfinite(engine_view[series_id]) & (engine_view[series_id] != 0)
                for t in range(clean.shape[0]):
                    clean[t] &= ok[max(0, t - lag): t + 1].all(axis=0)
            for series_id in ref.ZERO_GROWTH_IS_MISSING.get(index, ()):   # defect 9.2
                moved = growth(engine_view[series_id]) != 0
                for t in range(clean.shape[0]):
                    clean[t] &= moved[max(1, t - lag + 1): t + 1].all(axis=0)
            if index in ref.GROWTH_BASED:                   # window reaches the first growth rate
                clean[:lag] = False
            if index == "consumption_dependency":            # defect 9.5, removed on purpose
                for code in ("IN", "GB"):
                    clean[:, countries.index(code)] = False
            clean &= np.isfinite(theirs[index])
            total += clean.size
            compared += int(clean.sum())
            diff = np.abs(ours[index][clean] - theirs[index][clean])
            assert diff.size == 0 or diff.max() <= TOLERANCE, f"{index}: {diff.max():.3e}"
        assert compared / total > 0.75, f"only {compared}/{total} cells were comparable"


# ---------------------------------------------------------------------------
# C. End to end against the frozen build
# ---------------------------------------------------------------------------

class TestFrozenBuild:
    @pytest.fixture(scope="class")
    def output(self, panel, expected_build):
        return run_model(panel, DEFAULT, expected_build["countries"], None, 20)

    def test_years_and_countries(self, output, expected_build):
        assert list(output.years) == expected_build["years"]
        assert list(output.countries) == expected_build["countries"]

    def test_every_figure_matches(self, output, expected_build):
        assert_close(output.national, arr(expected_build["national"]), "national")
        assert_close(output.capital_saturation, arr(expected_build["capital_saturation"]),
                     "capital_saturation")
        for s in SECTORS:
            assert_close(output.sectors[s], arr(expected_build["sectors"][s]), s)
        for i in INDICES:
            assert_close(output.index_scores[i], arr(expected_build["index_scores"][i]), i)
            assert_close(output.index_raw[i], arr(expected_build["index_raw"][i]), i)

    def test_bit_for_bit_deterministic(self, panel, output, expected_build):
        again = run_model(panel, DEFAULT, expected_build["countries"], None, 20)
        assert np.array_equal(output.national, again.national, equal_nan=True)
        for i in INDICES:
            assert np.array_equal(output.index_raw[i], again.index_raw[i], equal_nan=True)
