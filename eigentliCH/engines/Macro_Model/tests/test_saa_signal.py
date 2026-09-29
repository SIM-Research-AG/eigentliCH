"""Tests for the superposition, the macro-to-25-bin translation, and the merge.

Phases 3, 4 and 5 of docs/BATTLE_PLAN.md. The tests that matter most are the ones about what the numbers
*mean*: that the superposition measures phase alignment and not amplitude, that the tilts move weight in the
direction the framework says they should, and that a bimodal merge is reported rather than smoothed.
"""

import numpy as np
import pytest

from macrofield import config as config_module
from macrofield.control import Provenance
from macrofield.data.taa import _prominent_modes, dispersion
from macrofield.model.cycles import CycleBand, CycleEstimate, CycleError, superpose
from macrofield.model.saa_signal import (
    REGIMES,
    SCENARIOS,
    SAASignalError,
    StateReading,
    merge,
    regime_weights_from_state,
    scenario_weights,
    signal_from_state,
)

PERIODS = np.arange(1970, 2025)
BAND = (2.5, 3.5)


def wave(period: float, phase: float = 0.0, amplitude: float = 1.0, n: int = PERIODS.size) -> np.ndarray:
    t = np.arange(n, dtype=float)
    return amplitude * np.sin(2.0 * np.pi * t / period + phase)


def estimate(name: str, component: np.ndarray, period: float = 10.0) -> CycleEstimate:
    return CycleEstimate(
        name=name,
        band=CycleBand.from_prior(name, period),
        identifiable=True,
        component=component,
        estimated_period=period,
        phase=np.zeros_like(component),
        sample_years=float(component.size),
    )


class TestProminentModes:
    """True topographic prominence, not height.

    Using height counted a shoulder on a big peak as a second mode, which reported three to five modes on
    every merged signal. The 25-bin axis is lumpy by construction, since it sums five overlapping kernels.
    """

    def test_a_single_peak_is_one_mode(self):
        assert _prominent_modes(np.array([0.1, 0.5, 1.0, 0.5, 0.1]), 0.25) == [3]

    def test_a_shoulder_is_not_a_mode(self):
        """The defect this replaced: tall but with no valley separating it."""
        values = np.array([0.05, 0.10, 0.40, 0.42, 0.90, 0.40, 0.10, 0.05])
        assert _prominent_modes(values, 0.25) == [5]

    def test_two_peaks_with_a_real_valley_are_two_modes(self):
        values = np.array([0.05, 0.60, 0.10, 0.02, 0.02, 0.10, 0.80, 0.05])
        assert _prominent_modes(values, 0.25) == [2, 7]

    def test_a_flat_distribution_reports_one_mode(self):
        assert len(_prominent_modes(np.full(25, 0.04), 0.25)) == 1

    def test_the_tallest_peak_is_always_a_mode(self):
        values = np.array([0.9, 0.1, 0.1, 0.1])
        assert 1 in _prominent_modes(values, 0.9)

    def test_a_higher_floor_keeps_fewer_modes(self):
        values = np.array([0.05, 0.60, 0.10, 0.02, 0.02, 0.10, 0.80, 0.05])
        assert len(_prominent_modes(values, 0.25)) == 2
        assert len(_prominent_modes(values, 0.95)) == 1


class TestSuperposition:
    def test_alignment_is_one_when_the_cycles_agree(self):
        wave_a = wave(10.0)
        result = superpose(PERIODS, {"a": estimate("a", wave_a), "b": estimate("b", wave_a)})
        finite = np.isfinite(result.alignment)
        assert np.allclose(result.alignment[finite], 1.0)

    def test_alignment_is_zero_when_they_cancel(self):
        """Two opposed cycles cancel, and where they have amplitude to cancel that reads as alignment zero.

        The zero crossings are the exception and are covered by the next test: there the components are both
        zero, so there is nothing to cancel and the measure is undefined rather than zero.
        """
        wave_a = wave(10.0)
        result = superpose(PERIODS, {"a": estimate("a", wave_a), "b": estimate("b", -wave_a)})
        assert np.allclose(result.total, 0.0, atol=1e-9)
        has_amplitude = ~np.isclose(np.abs(wave_a), 0.0, atol=1e-12)
        assert np.allclose(result.alignment[has_amplitude], 0.0, atol=1e-9)

    def test_alignment_is_undefined_at_a_common_zero_crossing(self):
        """Reporting zero there would read as 'the cycles cancel', which is a finding. It is not."""
        wave_a = wave(10.0)
        result = superpose(PERIODS, {"a": estimate("a", wave_a), "b": estimate("b", wave_a)})
        at_zero = np.isclose(np.abs(wave_a), 0.0, atol=1e-12)
        assert np.all(~np.isfinite(result.alignment[at_zero]))

    def test_amplitude_is_normalised_away(self):
        """The whole design: a cycle of order 0.02 must not be drowned by one of order 1.

        Two cycles in phase but a hundred times apart in size must give the same superposition as two of
        equal size, because the sum is a statement about phase and not about magnitude.
        """
        small = wave(10.0, amplitude=0.02)
        large = wave(14.0, amplitude=1.0)
        scaled = superpose(PERIODS, {"a": estimate("a", small), "b": estimate("b", large)})
        equal = superpose(
            PERIODS,
            {"a": estimate("a", small / 0.02), "b": estimate("b", large)},
        )
        assert np.allclose(scaled.total, equal.total)

    def test_the_total_stays_within_the_unit_interval(self):
        result = superpose(
            PERIODS,
            {name: estimate(name, wave(p, phase=i)) for i, (name, p) in
             enumerate([("a", 7.0), ("b", 18.0), ("c", 47.0), ("d", 90.0)])},
        )
        assert result.total.min() >= -1.0 - 1e-9
        assert result.total.max() <= 1.0 + 1e-9

    def test_stabilising_and_destabilising_partition_the_cycles(self):
        result = superpose(PERIODS, {"a": estimate("a", wave(7.0)), "b": estimate("b", -wave(7.0))})
        for index in range(PERIODS.size):
            both = set(result.stabilising[index]) | set(result.destabilising[index])
            assert not (set(result.stabilising[index]) & set(result.destabilising[index]))
            assert both <= {"a", "b"}

    def test_weights_shift_the_total(self):
        cycles = {"a": estimate("a", wave(7.0)), "b": estimate("b", -wave(7.0))}
        even = superpose(PERIODS, cycles)
        tilted = superpose(PERIODS, cycles, {"a": 3.0, "b": 1.0})
        assert not np.allclose(even.total, tilted.total)

    def test_an_unidentifiable_cycle_is_excluded_and_named(self):
        unusable = CycleEstimate("capital", CycleBand.from_prior("capital", 90.0), False,
                                 notes=["sample too short"])
        result = superpose(PERIODS, {"a": estimate("a", wave(7.0)), "capital": unusable})
        assert "capital" in result.excluded
        assert "capital" not in result.components
        assert any("excluded from the sum" in note for note in result.notes)

    def test_no_usable_cycle_is_an_error_not_an_empty_result(self):
        unusable = CycleEstimate("capital", CycleBand.from_prior("capital", 90.0), False)
        with pytest.raises(CycleError, match="not a finding that"):
            superpose(PERIODS, {"capital": unusable})

    def test_a_length_mismatch_is_refused(self):
        with pytest.raises(CycleError, match="periods were given"):
            superpose(PERIODS, {"a": estimate("a", wave(7.0, n=10))})

    def test_negative_weights_are_refused(self):
        with pytest.raises(CycleError, match="non-negative"):
            superpose(PERIODS, {"a": estimate("a", wave(7.0))}, {"a": -1.0})

    def test_it_says_the_sum_is_about_phase_not_size(self):
        result = superpose(PERIODS, {"a": estimate("a", wave(7.0))})
        assert any("phase alignment" in note for note in result.notes)


class TestScenarioTranslation:
    def test_every_scenario_becomes_five_regime_weights_summing_to_one(self):
        for name in SCENARIOS:
            weights = scenario_weights(name)
            assert set(weights) == set(REGIMES)
            assert sum(weights.values()) == pytest.approx(1.0)

    def test_depression_is_crisis_and_contraction(self):
        weights = scenario_weights("depression")
        assert weights["crisis"] == pytest.approx(0.75)
        assert weights["contraction"] == pytest.approx(0.25)
        assert weights["boom"] == 0.0

    def test_hyperinflation_is_entirely_boom_which_is_the_nominal_reading(self):
        """Faithful to Scenario_SAA.m, and the nominal-against-real problem showing up in the signal.

        The source vector is in nominal terms and a hyperinflation is a nominal boom. A portfolio positioned
        for Boom in a hyperinflation is positioned wrongly in real terms, which is why this is asserted
        explicitly rather than left as a quiet consequence.
        """
        assert scenario_weights("hyperinflation")["boom"] == pytest.approx(1.0)

    def test_deferral_is_a_barbell(self):
        weights = scenario_weights("deferral")
        assert weights["crisis"] == pytest.approx(0.5)
        assert weights["boom"] == pytest.approx(0.5)
        assert weights["stagnation"] == 0.0

    def test_recovery_splits_between_stagnation_and_expansion(self):
        """Recovery has no five-regime equivalent, per MODEL_SPEC section 6."""
        weights = scenario_weights("stagflation", recovery_split=0.5)
        assert weights["stagnation"] == pytest.approx(weights["expansion"])

    def test_the_split_is_adjustable(self):
        all_stagnation = scenario_weights("stagflation", recovery_split=1.0)
        assert all_stagnation["expansion"] == 0.0
        assert all_stagnation["stagnation"] > 0.0

    def test_an_unknown_scenario_names_the_available_ones(self):
        with pytest.raises(SAASignalError, match="Available"):
            scenario_weights("melt_up")

    def test_a_split_outside_the_unit_interval_is_refused(self):
        with pytest.raises(SAASignalError, match=r"\[0, 1\]"):
            scenario_weights("stagflation", recovery_split=1.5)


class TestRegimeWeightsFromState:
    """The tilts must move weight the way the framework says, which is the only check available.

    There is no source for the coefficients, so what can be tested is the *direction* each quantity pushes.
    """

    @staticmethod
    def neutral(**overrides) -> StateReading:
        base = dict(period=2024, saturation=3.0, band=BAND, real_to_financial=1.2)
        base.update(overrides)
        return StateReading(**base)

    def test_a_neutral_state_gives_an_even_spread(self):
        weights, contributions = regime_weights_from_state(self.neutral())
        assert not contributions, "a state inside the band with healthy capital should trip no tilt"
        assert all(v == pytest.approx(0.2) for v in weights.values())

    def test_saturation_above_the_band_moves_weight_to_crisis(self):
        inside, _ = regime_weights_from_state(self.neutral(saturation=3.0))
        above, _ = regime_weights_from_state(self.neutral(saturation=4.5))
        assert above["crisis"] > inside["crisis"]
        assert above["boom"] < inside["boom"]

    def test_saturation_below_the_band_moves_weight_to_boom(self):
        inside, _ = regime_weights_from_state(self.neutral(saturation=3.0))
        below, _ = regime_weights_from_state(self.neutral(saturation=1.0))
        assert below["boom"] > inside["boom"]

    def test_real_capital_below_financial_moves_weight_to_crisis(self):
        """The Phase IV condition, and the one invariant to every level adjustment."""
        healthy, _ = regime_weights_from_state(self.neutral(real_to_financial=1.2))
        saturated, _ = regime_weights_from_state(self.neutral(real_to_financial=0.6))
        assert saturated["crisis"] > healthy["crisis"]

    def test_a_widening_unsecured_gap_moves_weight_to_crisis(self):
        narrowing, _ = regime_weights_from_state(self.neutral(unsecured_change=-0.02))
        widening, _ = regime_weights_from_state(self.neutral(unsecured_change=0.02))
        assert widening["crisis"] > narrowing["crisis"]

    def test_negative_cycle_interference_moves_weight_to_crisis(self):
        positive, _ = regime_weights_from_state(self.neutral(interference=0.8, alignment=0.9))
        negative, _ = regime_weights_from_state(self.neutral(interference=-0.8, alignment=0.9))
        assert negative["crisis"] > positive["crisis"]

    def test_alignment_amplifies_the_interference_tilt(self):
        """Aligned cycles are the framework's peak-fragility condition, so they must count for more."""
        scattered, _ = regime_weights_from_state(self.neutral(interference=-0.8, alignment=0.1))
        aligned, _ = regime_weights_from_state(self.neutral(interference=-0.8, alignment=0.95))
        assert aligned["crisis"] > scattered["crisis"]

    def test_being_past_the_reordering_point_moves_weight_to_crisis(self):
        short, _ = regime_weights_from_state(self.neutral(capital_years_overdue=-20.0))
        overdue, _ = regime_weights_from_state(self.neutral(capital_years_overdue=15.0))
        assert overdue["crisis"] > short["crisis"]

    def test_approaching_the_innovation_trough_moves_weight_to_crisis(self):
        far, _ = regime_weights_from_state(self.neutral(innovation_years_to_trough=19.0))
        near, _ = regime_weights_from_state(self.neutral(innovation_years_to_trough=2.0))
        assert near["crisis"] > far["crisis"]

    def test_every_tilt_reports_its_contribution(self):
        """A surprising signal has to be takeable apart rather than argued with."""
        _, contributions = regime_weights_from_state(
            self.neutral(saturation=4.5, real_to_financial=0.6, unsecured_change=0.02,
                         interference=-0.5, alignment=0.8, capital_years_overdue=10.0)
        )
        assert "saturation_above_band" in contributions
        assert "real_to_financial_below_one" in contributions
        assert "capital_overdue" in contributions

    def test_the_weights_always_form_a_distribution(self):
        weights, _ = regime_weights_from_state(
            self.neutral(saturation=9.0, real_to_financial=0.05, unsecured_change=0.5,
                         interference=-1.0, alignment=1.0, capital_years_overdue=60.0)
        )
        assert sum(weights.values()) == pytest.approx(1.0)
        assert all(v >= 0.0 for v in weights.values())

    def test_tilts_strong_enough_to_empty_the_distribution_are_refused(self):
        """A zero base with a state that trips no tilt leaves nothing to normalise."""
        with pytest.raises(SAASignalError, match="driven to zero"):
            regime_weights_from_state(self.neutral(), tilts={"base": 0.0})

    def test_a_zero_base_still_works_where_a_tilt_fires(self):
        """The error above is about an empty distribution, not about the base being zero as such."""
        weights, _ = regime_weights_from_state(
            self.neutral(saturation=4.5), tilts={"base": 0.0}
        )
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["crisis"] > weights["boom"]

    def test_a_degenerate_band_is_refused(self):
        with pytest.raises(SAASignalError, match="does not increase"):
            regime_weights_from_state(self.neutral(band=(3.5, 3.5)))


class TestSignalFromState:
    def test_it_produces_a_distribution_over_the_axis(self):
        signal = signal_from_state(StateReading(2024, 3.48, BAND, 0.94))
        assert signal.probabilities.size == 25
        assert signal.probabilities.sum() == pytest.approx(1.0)

    def test_a_saturated_state_leans_cautious(self):
        """The United States case: Phase IV, past the reordering point, approaching the innovation low."""
        signal = signal_from_state(
            StateReading(2024, 3.48, BAND, 0.94, unsecured_change=0.01,
                         capital_years_overdue=10.5, innovation_years_to_trough=8.0)
        )
        summary = dispersion(signal.probabilities)
        assert summary["mean_bin"] < 13.0
        assert "risky" in summary["shape"] or "balanced" in summary["shape"]

    def test_an_unsaturated_state_leans_aggressive(self):
        signal = signal_from_state(StateReading(2024, 1.2, BAND, 2.5, unsecured_change=-0.01))
        assert dispersion(signal.probabilities)["mean_bin"] > 13.0

    def test_the_crisis_tail_stays_live(self):
        """Brief section 0.8 requires it, and a saturated economy is exactly when it matters."""
        signal = signal_from_state(StateReading(2024, 3.48, BAND, 0.94))
        assert signal.distribution.tail_probability > 0.01

    def test_provenance_is_inherited_from_the_state(self):
        """A signal read off an extrapolated state is not worth more than the state."""
        signal = signal_from_state(
            StateReading(2030, 3.0, BAND, 1.0, provenance=Provenance.EXTRAPOLATED)
        )
        assert signal.provenance is Provenance.EXTRAPOLATED
        assert signal.provenance.is_invented

    def test_it_says_the_tilts_are_a_judgement_call(self):
        signal = signal_from_state(StateReading(2024, 3.48, BAND, 0.94))
        assert any("judgement call" in note for note in signal.notes)


class TestTiltSweep:
    """The tilts stay a judgement call and the spread is reported. Settled 2026-07-28.

    Same discipline as the level adjustments in data/adjustment.py: where a number has no source, quote the
    range the conclusion moves over rather than one value from one chosen setting.
    """

    @staticmethod
    def state() -> StateReading:
        return StateReading(
            2024, 3.48, BAND, 0.94, unsecured_change=0.01,
            capital_years_overdue=10.5, innovation_years_to_trough=8.0,
        )

    def test_it_reports_a_range_not_a_point(self):
        from macrofield.model.saa_signal import sweep_tilts

        sweep = sweep_tilts(self.state())
        assert len(sweep.crisis_weight) == 5
        assert sweep.crisis_spread > 0.0, "the signal must be shown to depend on the tilts"

    def test_the_spread_widens_with_the_range(self):
        from macrofield.model.saa_signal import sweep_tilts

        narrow = sweep_tilts(self.state(), scale_range=(0.9, 1.1))
        wide = sweep_tilts(self.state(), scale_range=(0.25, 4.0))
        assert wide.crisis_spread > narrow.crisis_spread

    def test_the_base_weight_is_not_swept(self):
        """Scaling the base with the others moves numerator and denominator together and would report a
        robustness the signal does not have."""
        import inspect

        from macrofield.model import saa_signal

        source = inspect.getsource(saa_signal.sweep_tilts)
        assert 'k != "base"' in source
        assert any("not swept" in note for note in sweep_tilts_notes())

    def test_it_names_the_tilt_the_answer_rests_on(self):
        from macrofield.model.saa_signal import sweep_tilts

        sweep = sweep_tilts(self.state())
        assert sweep.dominant in sweep.per_tilt
        # The dominant tilt must genuinely have the widest own-effect.
        assert sweep.per_tilt[sweep.dominant]["spread"] == max(
            entry["spread"] for entry in sweep.per_tilt.values()
        )

    def test_a_state_that_trips_no_tilt_has_no_spread(self):
        """Nothing unsourced is doing any work there, and the sweep should say so rather than invent one."""
        from macrofield.model.saa_signal import sweep_tilts

        sweep = sweep_tilts(StateReading(2024, 3.0, BAND, 1.2))
        assert sweep.crisis_spread == pytest.approx(0.0)

    def test_every_tilt_gets_its_own_sensitivity(self):
        from macrofield.model.saa_signal import DEFAULT_TILTS, sweep_tilts

        sweep = sweep_tilts(self.state())
        assert set(sweep.per_tilt) == set(DEFAULT_TILTS) - {"base"}

    def test_it_says_to_quote_the_range(self):
        from macrofield.model.saa_signal import sweep_tilts

        assert any("Quote that range, not a point" in n for n in sweep_tilts(self.state()).notes)

    def test_a_backwards_range_is_refused(self):
        from macrofield.model.saa_signal import sweep_tilts

        with pytest.raises(SAASignalError, match="must increase"):
            sweep_tilts(self.state(), scale_range=(1.5, 0.5))

    def test_a_single_step_is_refused(self):
        from macrofield.model.saa_signal import sweep_tilts

        with pytest.raises(SAASignalError, match="at least two steps"):
            sweep_tilts(self.state(), steps=1)

    def test_the_board_quotes_the_range_rather_than_the_point(self):
        from macrofield.cockpit.server import STATIC_DIRECTORY

        page = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert "sweep.crisis_range" in page
        assert "at the configured tilts" in page


def sweep_tilts_notes():
    from macrofield.model.saa_signal import sweep_tilts

    return sweep_tilts(TestTiltSweep.state()).notes


class TestMerge:
    @staticmethod
    def peaked(bin_index: int, width: float = 2.0) -> np.ndarray:
        bins = np.arange(1, 26, dtype=float)
        values = np.exp(-0.5 * ((bins - bin_index) / width) ** 2)
        return values / values.sum()

    def test_a_fifty_fifty_merge_sits_between_the_two(self):
        saa, taa = self.peaked(4), self.peaked(20)
        merged = merge([2024], saa[None, :], taa[None, :], weight=0.5)
        mean = dispersion(merged.merged[0])["mean_bin"]
        assert dispersion(saa)["mean_bin"] < mean < dispersion(taa)["mean_bin"]

    def test_full_weight_on_one_side_reproduces_it(self):
        saa, taa = self.peaked(4), self.peaked(20)
        assert np.allclose(merge([2024], saa[None, :], taa[None, :], weight=1.0).merged[0], saa)
        assert np.allclose(merge([2024], saa[None, :], taa[None, :], weight=0.0).merged[0], taa)

    def test_every_merged_row_is_a_distribution(self):
        periods = [2024, 2025, 2026]
        saa = np.vstack([self.peaked(4)] * 3)
        taa = np.vstack([self.peaked(18)] * 3)
        merged = merge(periods, saa, taa, weight=0.5)
        assert np.allclose(merged.merged.sum(axis=1), 1.0)

    def test_disagreement_is_reported_as_a_swing(self):
        """The author's decision of 2026-07-28: a bimodal merge is a finding, not an artefact."""
        merged = merge([2024], self.peaked(3, 1.2)[None, :], self.peaked(22, 1.2)[None, :], weight=0.5)
        assert merged.shapes[0]["modes"] == 2
        assert "swing" in merged.shapes[0]["shape"]
        assert any("dispersion of view" in note for note in merged.notes)

    def test_agreement_is_not_reported_as_a_swing(self):
        same = self.peaked(13)
        merged = merge([2024], same[None, :], same[None, :], weight=0.5)
        assert merged.shapes[0]["modes"] == 1

    def test_provenance_is_the_weaker_of_the_two_inputs(self):
        saa, taa = self.peaked(4), self.peaked(20)
        merged = merge(
            [2030],
            saa[None, :],
            taa[None, :],
            saa_provenance=[Provenance.INTEGRATED],
            taa_provenance=[Provenance.EXTRAPOLATED],
        )
        assert merged.traces[0].provenance is Provenance.EXTRAPOLATED

    def test_a_weight_outside_the_unit_interval_is_refused(self):
        saa, taa = self.peaked(4), self.peaked(20)
        with pytest.raises(SAASignalError, match=r"\[0, 1\]"):
            merge([2024], saa[None, :], taa[None, :], weight=1.5)

    def test_mismatched_shapes_are_refused(self):
        with pytest.raises(SAASignalError, match="share a shape"):
            merge([2024], np.ones((1, 25)) / 25, np.ones((1, 20)) / 20)

    def test_a_period_count_mismatch_is_refused(self):
        with pytest.raises(SAASignalError, match="signal rows against"):
            merge([2024, 2025], np.ones((1, 25)) / 25, np.ones((1, 25)) / 25)

    def test_the_merge_happens_in_bin_space(self):
        """Stated in the notes because it is what keeps the taxonomy question from propagating."""
        saa, taa = self.peaked(4), self.peaked(20)
        merged = merge([2024], saa[None, :], taa[None, :])
        assert any("bin space" in note for note in merged.notes)


class TestConfigWiring:
    def test_every_tilt_is_configured(self):
        from macrofield.model.saa_signal import DEFAULT_TILTS

        configured = config_module.load().get("saa.tilts")
        assert set(configured) == set(DEFAULT_TILTS)

    def test_the_blend_weight_and_half_life_are_configured(self):
        settings = config_module.load()
        assert settings.get("saa.blend_weight") == pytest.approx(0.5)
        assert settings.get("saa.taa.half_life_months") > 0

    def test_the_superposition_weights_cover_the_four_cycles(self):
        weights = config_module.load().get("cycles.superposition.weights")
        assert set(weights) == {"business", "credit", "innovation", "capital"}
        assert len(set(weights.values())) == 1, "the default must assert nothing about importance"
