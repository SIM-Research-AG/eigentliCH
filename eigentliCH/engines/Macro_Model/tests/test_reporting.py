"""Tests for export and the auto-generated briefs, section 6."""

import json

import numpy as np
import pandas as pd
import pytest

from macrofield.reporting.brief import (
    FORBIDDEN_CHARACTERS,
    UNAVAILABLE,
    BriefError,
    BriefInputs,
    render,
    word_count,
)
from macrofield.reporting.export import (
    DISCLAIMER,
    PROJECTION_LABEL,
    ExportError,
    ResultBundle,
    state_frame,
    write_csv,
    write_json,
)

VINTAGE = {"Y": "World Bank, retrieved 2026-07-27", "K_R": "Penn World Table 10.01"}


def bundle(**overrides) -> ResultBundle:
    payload = {
        "economy": "us",
        "calibration_window": (1995, 2024),
        "data_vintage": VINTAGE,
        "series": {
            "state": state_frame(
                periods=[2020, 2021, 2022],
                observed={"Y": [100.0, 104.0, 107.0], "K_R": [320.0, 328.0, 331.0]},
                simulated={"Y": [99.0, 103.0, 108.0], "K_R": [322.0, 327.0, 333.0]},
            )
        },
        "diagnostics": {"phase": "Optimisation", "saturation": 2.51},
    }
    payload.update(overrides)
    return ResultBundle(**payload)


class TestResultBundle:
    def test_requires_the_data_vintage(self):
        """Brief section 6 requires every table to state it, so it cannot be optional."""
        with pytest.raises(ExportError, match="data vintage"):
            ResultBundle(economy="us", calibration_window=(1995, 2024), data_vintage={})

    def test_rejects_a_backwards_window(self):
        with pytest.raises(ExportError, match="runs backwards"):
            ResultBundle(economy="us", calibration_window=(2024, 1995), data_vintage=VINTAGE)

    def test_header_carries_the_window_vintage_label_and_disclaimer(self):
        header = bundle().header()
        assert header["calibration_window"] == {"first": 1995, "last": 2024}
        assert header["data_vintage"] == VINTAGE
        assert header["projection_label"] == PROJECTION_LABEL
        assert header["disclaimer"] == DISCLAIMER


class TestStateFrame:
    def test_puts_observed_and_simulated_side_by_side(self):
        frame = state_frame([2020, 2021], {"Y": [1.0, 2.0]}, {"Y": [1.1, 2.1]})
        assert list(frame.columns) == ["Y_observed", "Y_simulated"]
        assert frame.index.name == "period"

    def test_omits_an_empty_simulated_series(self):
        """A failed integration must not leave an empty column that reads as zeros."""
        frame = state_frame([2020, 2021], {"Y": [1.0, 2.0]}, {"Y": []})
        assert list(frame.columns) == ["Y_observed"]


class TestWriteJson:
    def test_writes_a_readable_payload(self, tmp_path):
        path = write_json(bundle(), tmp_path / "us.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["header"]["economy"] == "us"
        assert payload["diagnostics"]["phase"] == "Optimisation"

    def test_converts_numpy_types(self, tmp_path):
        result = bundle(diagnostics={"count": np.int64(7), "ratio": np.float64(2.5)})
        payload = json.loads(write_json(result, tmp_path / "us.json").read_text(encoding="utf-8"))
        assert payload["diagnostics"]["count"] == 7
        assert payload["diagnostics"]["ratio"] == 2.5

    def test_non_finite_values_become_null_rather_than_invalid_json(self, tmp_path):
        """A bare NaN produces a file some parsers accept and others reject, which is worse than losing
        the distinction."""
        result = bundle(diagnostics={"residual": float("inf"), "other": float("nan")})
        text = write_json(result, tmp_path / "us.json").read_text(encoding="utf-8")
        assert "Infinity" not in text
        assert "NaN" not in text
        assert json.loads(text)["diagnostics"]["residual"] is None

    def test_refuses_an_unlabelled_projection(self, tmp_path):
        """Brief section 6 requires the label on any projected path, enforced at the write boundary."""
        result = bundle(diagnostics={"scenarios": {"capital_ratio": [4.5, 4.2]}})
        with pytest.raises(ExportError, match="carry no label"):
            write_json(result, tmp_path / "us.json")

    def test_accepts_a_labelled_projection(self, tmp_path):
        result = bundle(
            diagnostics={"scenarios": {"capital_ratio": [4.5, 4.2], "label": PROJECTION_LABEL}}
        )
        assert write_json(result, tmp_path / "us.json").exists()

    def test_checks_every_entry_of_a_projected_list(self, tmp_path):
        result = bundle(
            diagnostics={
                "scenarios": [
                    {"capital_ratio": [4.5], "label": PROJECTION_LABEL},
                    {"capital_ratio": [4.4]},
                ]
            }
        )
        with pytest.raises(ExportError, match="carry no label"):
            write_json(result, tmp_path / "us.json")

    def test_creates_the_parent_directory(self, tmp_path):
        path = write_json(bundle(), tmp_path / "nested" / "deeper" / "us.json")
        assert path.exists()


class TestWriteCsv:
    def test_writes_one_file_per_table(self, tmp_path):
        written = write_csv(bundle(), tmp_path)
        assert len(written) == 1
        assert written[0].name == "us_state.csv"

    def test_the_csv_carries_its_own_provenance(self, tmp_path):
        """A table that travels without its provenance is how a number gets quoted against the wrong
        vintage."""
        written = write_csv(bundle(), tmp_path)
        text = written[0].read_text(encoding="utf-8")
        assert "# economy: us" in text
        assert "# calibration window: 1995 to 2024" in text
        assert "Penn World Table 10.01" in text
        assert PROJECTION_LABEL in text
        assert DISCLAIMER in text

    def test_the_data_survives_the_header(self, tmp_path):
        written = write_csv(bundle(), tmp_path)
        frame = pd.read_csv(written[0], comment="#", index_col=0)
        assert "Y_observed" in frame.columns
        assert len(frame) == 3


class TestBrief:
    def _inputs(self, **overrides) -> BriefInputs:
        payload = {
            "economy": "the United States",
            "window": (1995, 2024),
            "phase": "Optimisation",
            "phase_rule": "credit saturation below the Phase 3 ceiling with real capital past the production boundary",
            "saturation": 2.51,
            "honi_composite": 1.9,
            "honi_stage": "Saturation",
            "dominant_driver": "capital_cycle_currency_stability",
            "asset_stance": "value_preserving",
            "tail_probability": 0.043,
            "turning_point_hit_rate": 0.67,
            "turning_point_lead": 1.2,
            "unsecured_ratio": 4.8,
        }
        payload.update(overrides)
        return BriefInputs(**payload)

    def test_states_the_four_required_facts(self):
        """Section 6: the phase, the saturation level, the dominant driver, and the tail weight."""
        text = render(self._inputs())
        assert "Optimisation" in text
        assert "2.51" in text
        assert "capital-cycle currency stability" in text
        assert "4.3%" in text

    def test_uses_the_first_person_plural_register(self):
        assert render(self._inputs()).startswith("We calibrate")

    def test_ends_with_the_disclaimer(self):
        assert render(self._inputs()).rstrip().endswith(DISCLAIMER)

    @pytest.mark.parametrize("character", FORBIDDEN_CHARACTERS)
    def test_contains_no_forbidden_dash(self, character):
        assert character not in render(self._inputs())

    def test_refuses_to_emit_a_forbidden_character(self):
        """The check is on the rendered output, because a generated document is exactly where a stray
        character slips through."""
        with pytest.raises(BriefError, match="forbidden character"):
            render(self._inputs(caveats=["the data are poor — treat with care"]))

    def test_says_five_is_healthiest_so_the_score_cannot_be_misread(self):
        assert "five is healthiest" in render(self._inputs())

    def test_reports_a_missing_diagnostic_as_missing_rather_than_inventing_one(self):
        text = render(self._inputs(saturation=None, dominant_driver=None, tail_probability=None))
        assert text.count(UNAVAILABLE) >= 3
        assert "2.51" not in text

    def test_names_the_turning_point_agreement_and_the_reading_it_licenses(self):
        text = render(self._inputs())
        assert "67% of turning points" in text
        assert "trend and the turning points rather than the levels" in text

    def test_reports_an_early_turn_as_early(self):
        assert "1.2 periods early" in render(self._inputs(turning_point_lead=1.2))

    def test_reports_a_late_turn_as_late(self):
        assert "1.2 periods late" in render(self._inputs(turning_point_lead=-1.2))

    def test_labels_the_synchronisation_window_as_a_projection(self):
        text = render(self._inputs(synchronisation_window=(2031, 2035)))
        assert "2031 to 2035" in text
        assert PROJECTION_LABEL in text
        assert "recomputed each run" in text

    def test_discloses_a_standardising_adjustment(self):
        text = render(self._inputs(adjustments_applied=True))
        assert "not the published levels" in text
        assert "cannot alter growth rates" in text

    def test_stays_short(self):
        """Section 6 asks for a short brief."""
        assert word_count(render(self._inputs())) < 350

    def test_rejects_a_backwards_window(self):
        with pytest.raises(BriefError, match="runs backwards"):
            render(self._inputs(window=(2024, 1995)))

    def test_includes_supplied_caveats(self):
        text = render(self._inputs(caveats=["the capital stock is extended beyond 2019"]))
        assert "extended beyond 2019" in text
