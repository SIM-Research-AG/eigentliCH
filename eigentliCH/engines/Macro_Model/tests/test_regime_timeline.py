"""Tests for the Regime timeline contract.

The contract is the boundary two other programmes depend on, so these tests are about the promises made
to a consumer rather than about internal shape: the distribution is a distribution, the monthly hold is
a hold and not an interpolation, identical inputs give an identical `regime_id`, and a partially covered
window is refused rather than filled.

The heavy end-to-end case runs from the cache offline, so the suite needs no network.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from macrofield.contracts.regime_timeline import (
    CONTRACT_VERSION,
    STATE_GRID,
    RegimeTimelineContract,
    RegimeTimelineError,
    build_timeline,
    hold_annual_to_monthly,
    load_timeline_payload,
    write_timeline,
)


def _uniform(n: int = 1) -> np.ndarray:
    """`n` rows of a flat distribution over the states."""
    return np.full((n, STATE_GRID), 1.0 / STATE_GRID)


def _contract(rows: int = 3, **overrides) -> RegimeTimelineContract:
    dates = tuple(f"2020-{m:02d}" for m in range(1, rows + 1))
    distributions = _uniform(rows)
    defaults = dict(
        regime_timeline_id="RTL-test",
        regime_id="REG-test",
        economy_scope="test",
        model_version="ms@test",
        contract_version=CONTRACT_VERSION,
        as_of="2020-03-31",
        period="M",
        state_grid=STATE_GRID,
        dates=dates,
        distributions=distributions,
        path_states=tuple(int(np.argmax(row)) for row in distributions),
        current_state=0,
        current_phase=3,
        current_saturation_pct=250.0,
        # Guarded so the empty case reaches the contract's own validation rather than failing here.
        crisis_tail=float(distributions[-1][:5].sum()) if rows else 0.0,
    )
    defaults.update(overrides)
    return RegimeTimelineContract(**defaults)


# ---------------------------------------------------------------------------
# The distribution is a distribution
# ---------------------------------------------------------------------------


class TestValidation:
    def test_a_valid_contract_is_accepted(self):
        contract = _contract()
        assert contract.n_periods == 3

    def test_rows_that_do_not_sum_to_one_are_refused(self):
        bad = _uniform(2)
        bad[1] *= 0.5
        with pytest.raises(RegimeTimelineError, match="sums to"):
            _contract(rows=2, distributions=bad)

    def test_a_negative_weight_is_refused(self):
        bad = _uniform(1).copy()
        bad[0][0] = -0.1
        bad[0][1] = 1.0 / STATE_GRID + 0.1
        with pytest.raises(RegimeTimelineError, match="negative weight"):
            _contract(rows=1, distributions=bad)

    def test_the_wrong_width_is_refused(self):
        with pytest.raises(RegimeTimelineError, match=r"shape \(T, 25\)"):
            _contract(rows=1, distributions=np.full((1, 24), 1.0 / 24))

    def test_an_empty_timeline_is_refused_with_a_reason(self):
        with pytest.raises(RegimeTimelineError, match="do not overlap|empty"):
            _contract(rows=0, dates=(), distributions=np.zeros((0, STATE_GRID)), path_states=())

    def test_a_row_count_that_disagrees_with_the_dates_is_refused(self):
        with pytest.raises(RegimeTimelineError, match="rows against"):
            _contract(rows=2, dates=("2020-01",), distributions=_uniform(2))

    def test_a_non_finite_weight_is_refused(self):
        bad = _uniform(1).copy()
        bad[0][0] = np.nan
        with pytest.raises(RegimeTimelineError, match="non-finite"):
            _contract(rows=1, distributions=bad)


# ---------------------------------------------------------------------------
# The monthly hold
# ---------------------------------------------------------------------------


class TestMonthlyHold:
    def test_each_year_is_repeated_across_its_months(self):
        annual = np.vstack([np.full(STATE_GRID, 1.0 / STATE_GRID), np.eye(STATE_GRID)[7]])
        months = [(2020, m) for m in range(1, 13)] + [(2021, 1), (2021, 2)]
        held = hold_annual_to_monthly([2020, 2021], annual, months)

        assert held.shape == (14, STATE_GRID)
        # Every month of 2020 carries the 2020 reading, unchanged.
        for row in held[:12]:
            assert np.allclose(row, annual[0])
        for row in held[12:]:
            assert np.allclose(row, annual[1])

    def test_the_hold_introduces_no_intermediate_value(self):
        """A hold repeats; an interpolation would produce values between the two readings."""
        annual = np.vstack([np.eye(STATE_GRID)[0], np.eye(STATE_GRID)[24]])
        months = [(2020, m) for m in range(1, 13)] + [(2021, m) for m in range(1, 13)]
        held = hold_annual_to_monthly([2020, 2021], annual, months)

        # Only the two authored readings appear. Nothing between them was manufactured.
        distinct = {tuple(np.round(row, 12)) for row in held}
        assert distinct == {tuple(np.round(annual[0], 12)), tuple(np.round(annual[1], 12))}

    def test_a_month_whose_year_was_never_assessed_is_refused(self):
        annual = _uniform(1)
        with pytest.raises(RegimeTimelineError, match="no annual macro reading"):
            hold_annual_to_monthly([2020], annual, [(2020, 1), (2021, 1)])

    def test_a_row_count_mismatch_is_refused(self):
        with pytest.raises(RegimeTimelineError, match="annual rows against"):
            hold_annual_to_monthly([2020, 2021], _uniform(1), [(2020, 1)])


# ---------------------------------------------------------------------------
# The published payload
# ---------------------------------------------------------------------------


class TestPayload:
    def test_it_carries_both_the_distribution_and_the_state_path(self):
        """Both, deliberately: the estimator needs a state, the optimiser needs a distribution."""
        payload = _contract().to_dict()
        assert len(payload["path"]) == len(payload["distributions"]) == 3
        assert set(payload["path"][0]) == {"date", "state"}
        assert set(payload["distributions"][0]) == {"date", "weights"}
        assert len(payload["distributions"][0]["weights"]) == STATE_GRID

    def test_the_state_path_is_within_the_grid(self):
        payload = _contract().to_dict()
        assert all(0 <= row["state"] < STATE_GRID for row in payload["path"])

    def test_the_current_block_carries_the_regime_id(self):
        payload = _contract().to_dict()
        assert payload["current"]["regime_id"] == "REG-test"
        assert payload["current"]["phase"] == 3
        assert payload["current"]["saturation_pct"] == 250.0
        assert "crisis_tail" in payload["current"]

    def test_an_unavailable_phase_is_omitted_rather_than_defaulted(self):
        payload = _contract(current_phase=None, current_saturation_pct=None).to_dict()
        assert "phase" not in payload["current"]
        assert "saturation_pct" not in payload["current"]

    def test_dates_agree_between_the_path_and_the_distributions(self):
        payload = _contract().to_dict()
        assert [r["date"] for r in payload["path"]] == [r["date"] for r in payload["distributions"]]

    def test_write_then_read_round_trips(self, tmp_path):
        written = write_timeline(_contract(), tmp_path)
        assert written.name == "test.json"
        payload = load_timeline_payload(written)
        assert payload["regime_timeline_id"] == "RTL-test"
        assert payload["period"] == "M"
        assert payload["state_grid"] == STATE_GRID

    def test_the_written_form_is_canonical_and_stable(self, tmp_path):
        first = write_timeline(_contract(), tmp_path).read_bytes()
        second = write_timeline(_contract(), tmp_path).read_bytes()
        assert first == second

    def test_a_missing_field_is_reported_on_read(self, tmp_path):
        target = tmp_path / "broken.json"
        payload = _contract().to_dict()
        del payload["current"]
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RegimeTimelineError, match="missing field"):
            load_timeline_payload(target)

    def test_a_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(RegimeTimelineError, match="not found"):
            load_timeline_payload(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# End to end, from the cache
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def offline_us():
    """Assemble the United States from the cache, or skip if it has not been populated."""
    from macrofield import config as config_module
    from macrofield.data.sources import SourceError
    from macrofield.pipeline import PipelineError, assemble, build_sources

    settings = config_module.load("us")
    try:
        sources = build_sources(offline=True, config=settings)
        economy = assemble("us", sources, config=settings)
    except (PipelineError, SourceError, OSError) as error:
        pytest.skip(f"the cache does not cover a full offline assembly of us: {error}")
    return economy, settings


@pytest.fixture(scope="module")
def taa():
    from macrofield.data.taa import TAAError, load_signal

    try:
        return load_signal()
    except TAAError as error:
        pytest.skip(f"the TAA signal is unavailable: {error}")


class TestEndToEnd:
    def test_the_published_timeline_is_monthly_and_well_formed(self, offline_us, taa):
        economy, settings = offline_us
        contract = build_timeline(economy, taa, settings=settings)

        assert contract.period == "M"
        assert contract.state_grid == STATE_GRID
        assert contract.n_periods > 24
        assert np.allclose(np.asarray(contract.distributions).sum(axis=1), 1.0)
        # Ascending, and one label per row.
        assert list(contract.dates) == sorted(contract.dates)
        assert len(contract.dates) == contract.n_periods

    def test_identical_inputs_give_an_identical_regime_id(self, offline_us, taa):
        economy, settings = offline_us
        first = build_timeline(economy, taa, settings=settings)
        second = build_timeline(economy, taa, settings=settings)
        assert first.regime_id == second.regime_id
        assert first.regime_timeline_id == second.regime_timeline_id
        assert first.as_of == second.as_of

    def test_a_different_blend_weight_gives_a_different_regime(self, offline_us, taa):
        """The identifier must move when the signal moves, or a consumer cannot detect a change."""
        economy, settings = offline_us
        half = build_timeline(economy, taa, settings=settings, blend_weight=0.5)
        macro_only = build_timeline(economy, taa, settings=settings, blend_weight=1.0)
        assert half.regime_id != macro_only.regime_id

    def test_the_crisis_tail_stays_live(self, offline_us, taa):
        """The downstream objective weights the crisis tail directly, so a zero tail would silently
        turn the asymmetric fit into something else."""
        economy, settings = offline_us
        contract = build_timeline(economy, taa, settings=settings)
        assert contract.crisis_tail > 0.0

    def test_the_hold_is_recorded_in_the_provenance(self, offline_us, taa):
        economy, settings = offline_us
        contract = build_timeline(economy, taa, settings=settings)
        assert contract.provenance["macro_frequency"] == "A"
        assert "step hold" in contract.provenance["macro_to_monthly"]
        assert any("held flat" in note for note in contract.notes)

    def test_every_published_month_lies_inside_the_macro_window(self, offline_us, taa):
        """Neither side is extended past what it covers."""
        economy, settings = offline_us
        contract = build_timeline(economy, taa, settings=settings)
        assessed = set(contract.provenance["macro_periods"])
        published_years = {int(d.split("-")[0]) for d in contract.dates}
        assert published_years <= assessed

    def test_the_monthly_rows_within_a_year_differ_only_by_the_technical_half(self, offline_us, taa):
        """With all the weight on the macro half, every month of a year must be identical, because the
        macro reading is held. That is the check that the hold is a hold."""
        economy, settings = offline_us
        contract = build_timeline(economy, taa, settings=settings, blend_weight=1.0)
        frame = pd.DataFrame(
            np.asarray(contract.distributions),
            index=[int(d.split("-")[0]) for d in contract.dates],
        )
        for year, rows in frame.groupby(level=0):
            assert rows.nunique().max() == 1, f"{year} varies within the year at full macro weight"
