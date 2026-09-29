"""Tests for the TAA signal reader and its forward decay, phase 0.3 and phase 5.

The published file is read where it is present, and skipped where it is not, so the suite still runs on a
machine without it. The pure functions are tested on constructed distributions either way.
"""

import numpy as np
import pytest

from macrofield.control import Provenance
from macrofield.data.taa import (
    DEFAULT_PATH,
    MODE_PROMINENCE,
    STATES,
    TAAError,
    TAASignal,
    decay_forward,
    dispersion,
    load_signal,
    stance_blocks,
)


@pytest.fixture(scope="module")
def signal() -> TAASignal:
    if not DEFAULT_PATH.exists():
        pytest.skip(f"{DEFAULT_PATH.name} is not present")
    return load_signal()


def synthetic(peak: int, width: float = 2.0, states: int = STATES) -> np.ndarray:
    """A unimodal distribution centred on one bin, for testing shape summaries."""
    bins = np.arange(1, states + 1, dtype=float)
    values = np.exp(-0.5 * ((bins - peak) / width) ** 2)
    return values / values.sum()


class TestLoadSignal:
    def test_it_reads_the_published_history(self, signal):
        assert len(signal.months) > 200
        assert signal.distribution.shape[1] == STATES
        assert signal.months == sorted(signal.months), "months must be ascending"

    def test_every_row_is_a_distribution(self, signal):
        totals = signal.distribution.sum(axis=1)
        assert np.allclose(totals, 1.0), "rows are normalised on read"

    def test_the_axis_labels_carry_the_five_stances(self, signal):
        blocks = stance_blocks(signal.labels)
        assert set(blocks) == {"Cautious", "Careful", "Neutral", "Bold", "Aggressive"}

    def test_the_stance_blocks_match_the_five_regime_partition(self, signal):
        """The published labels and config/defaults.yaml five_regime_bins must agree.

        They are the same partition of the same axis under two vocabularies, the stance names and the
        economic ones. If they ever diverge, one of them is describing a different axis.
        """
        from macrofield import config as config_module

        blocks = stance_blocks(signal.labels)
        configured = config_module.load().get("regime.five_regime_bins")
        assert sorted(blocks.values()) == sorted(tuple(v) for v in configured.values())

    def test_incomplete_rows_are_dropped_rather_than_normalised(self, signal):
        """A month is used only when it is a full set, on the author's instruction of 2026-07-28.

        The published file carries five rows several points off 100, three of them about nine points out.
        Normalising them would put a shape into the long-run average that the publisher never asserted, so
        they are left out, and named so the gap in the history is visible.
        """
        assert signal.rows_dropped, "the published file is known to carry rows off 100"
        assert any("were dropped" in note for note in signal.notes)
        dropped_months = {name for name, _ in signal.rows_dropped}
        present = {f"{y}-{m:02d}" for y, m in signal.months}
        for name in dropped_months:
            # The dropped label is as published, for example '2014-Feb'; check no such month survived.
            year, month_name = name.split("-")
            from macrofield.data.taa import _MONTHS

            assert f"{year}-{_MONTHS[month_name[:3].title()]:02d}" not in present

    def test_the_kept_rows_all_totalled_within_tolerance(self, signal):
        """Nothing that survived needed more than rounding to normalise."""
        from macrofield.data.taa import TOTAL_TOLERANCE

        # Rows are stored normalised, so this checks the count rather than the totals: the number kept plus
        # the number dropped must account for every data row the block carries.
        assert len(signal.months) + len(signal.rows_dropped) == 240
        assert TOTAL_TOLERANCE < 1.0, "the tolerance must stay tight enough to catch a real defect"

    def test_a_missing_file_says_what_it_is_for(self):
        with pytest.raises(TAAError, match="short-term half"):
            load_signal(DEFAULT_PATH.parent / "does_not_exist.csv")

    def test_as_of_returns_the_last_month_at_or_before(self, signal):
        year, month = signal.latest_month
        assert np.allclose(signal.as_of(year, month), signal.latest)

    def test_as_of_before_the_history_is_an_error(self, signal):
        with pytest.raises(TAAError, match="which is after"):
            signal.as_of(1990)


class TestDispersion:
    """The shape carries meaning, per the Master Deck: risky, opportunistic, or swing."""

    def test_a_cautious_distribution_reads_as_risky(self):
        assert "risky" in dispersion(synthetic(peak=3))["shape"]

    def test_an_aggressive_distribution_reads_as_opportunistic(self):
        assert "opportunistic" in dispersion(synthetic(peak=23))["shape"]

    def test_a_central_distribution_reads_as_balanced(self):
        assert dispersion(synthetic(peak=13))["shape"] == "balanced"

    def test_two_separated_peaks_read_as_a_swing(self):
        both = synthetic(peak=3) + synthetic(peak=22)
        summary = dispersion(both / both.sum())
        assert summary["modes"] == 2
        assert "swing" in summary["shape"]

    def test_a_wiggle_beside_a_tall_peak_is_not_a_second_mode(self):
        """Without a prominence floor every noisy distribution reads as a swing market.

        The published 2026-07 row has bare local maxima at 1.7 and 3.1 per cent against a peak of 15.1;
        counting those would report disagreement about a distribution with one obvious peak.
        """
        values = synthetic(peak=16, width=2.0)
        values[6] = values[16] * (MODE_PROMINENCE * 0.5)  # a bump well under the floor
        summary = dispersion(values / values.sum())
        assert summary["modes"] == 1
        assert "swing" not in summary["shape"]

    def test_a_prominent_second_peak_still_counts(self):
        values = synthetic(peak=16, width=2.0)
        values[3] = values[16] * (MODE_PROMINENCE * 2.0)
        summary = dispersion(values / values.sum())
        assert summary["modes"] == 2

    def test_the_tails_are_reported(self):
        summary = dispersion(synthetic(peak=2, width=1.0))
        assert summary["cautious_tail"] > 0.8
        assert summary["aggressive_tail"] < 0.01

    def test_an_empty_distribution_is_an_error(self):
        with pytest.raises(TAAError, match="empty distribution"):
            dispersion(np.zeros(STATES))

    def test_the_floor_is_configuration_not_a_constant(self):
        """Every threshold lives in config, per section 7 of the brief.

        The module constants are fallbacks so the function stays pure; the values of record are in
        `regime.shape`, and a config that loosens the floor must change the verdict.
        """
        from macrofield import config as config_module

        settings = config_module.load()
        assert settings.get("regime.shape.mode_prominence") == pytest.approx(MODE_PROMINENCE)
        assert settings.get("regime.shape.lean_bins") is not None

        values = synthetic(peak=16, width=2.0)
        values[6] = values[16] * 0.12  # under the 0.25 floor, over a 0.05 one
        values = values / values.sum()

        class Loose:
            def get(self, key, default=None):
                return 0.05 if key == "regime.shape.mode_prominence" else settings.get(key, default=default)

        assert dispersion(values, config=settings)["modes"] == 1
        assert dispersion(values, config=Loose())["modes"] == 2


class TestDecayForward:
    def test_periods_inside_the_history_are_observed(self, signal):
        last_year = signal.latest_month[0]
        matrix, traces = decay_forward(signal, [last_year - 2, last_year - 1, last_year])
        assert all(t.provenance is Provenance.OBSERVED for t in traces)
        assert np.allclose(matrix.sum(axis=1), 1.0)

    def test_periods_past_the_history_are_extrapolated(self, signal):
        last_year = signal.latest_month[0]
        _, traces = decay_forward(signal, [last_year + 1, last_year + 5])
        assert all(t.provenance is Provenance.EXTRAPOLATED for t in traces)
        assert all(t.provenance.is_invented for t in traces)

    def test_the_forward_path_converges_on_the_long_run_average(self, signal):
        """The decision of 2026-07-28: a technical signal fades rather than asserting.

        Beyond roughly two years the merge should be the SAA alone, which means the TAA contribution has to
        be indistinguishable from its unconditional average by then.
        """
        last_year = signal.latest_month[0]
        periods = [last_year + n for n in (1, 2, 3, 6)]
        matrix, _ = decay_forward(signal, periods, half_life_months=6.0)
        average = signal.long_run_average()
        distances = [float(np.abs(row - average).sum()) for row in matrix]
        assert distances == sorted(distances, reverse=True), "the path must converge monotonically"
        assert distances[-1] < 0.01

    def test_a_longer_half_life_keeps_more_of_the_signal(self, signal):
        last_year = signal.latest_month[0]
        average = signal.long_run_average()
        near, _ = decay_forward(signal, [last_year + 2], half_life_months=24.0)
        far, _ = decay_forward(signal, [last_year + 2], half_life_months=3.0)
        assert float(np.abs(near[0] - average).sum()) > float(np.abs(far[0] - average).sum())

    def test_every_projected_row_stays_a_distribution(self, signal):
        last_year = signal.latest_month[0]
        matrix, _ = decay_forward(signal, list(range(last_year, last_year + 16)))
        assert np.allclose(matrix.sum(axis=1), 1.0)
        assert (matrix >= 0).all(), "a decayed distribution must stay non-negative"

    def test_the_reason_is_recorded_on_each_extrapolated_row(self, signal):
        last_year = signal.latest_month[0]
        _, traces = decay_forward(signal, [last_year + 3])
        detail = traces[0].segments[0].detail
        assert "weight on the observed signal" in detail

    def test_a_non_positive_half_life_is_refused(self, signal):
        with pytest.raises(TAAError, match="half-life must be positive"):
            decay_forward(signal, [2030], half_life_months=0.0)
