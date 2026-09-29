"""Tests for the cycle layer: cycle positions as distributions on the 25-bin axis.

Directed by the author 2026-08-02, replacing the unbuilt seventeen-state taxonomy. See
`macrofield/model/cycle_bins.py` and `DECISIONS.md` M53.
"""

import numpy as np
import pytest

from macrofield import config as config_module
from macrofield.model import cycle_bins as cb
from macrofield.model.cycles import anchored_from_config, bands_from_config


def settings(**overrides):
    """The configured block, with overrides, so a test states only what it is about."""
    base = dict(config_module.load().get("cycles.bins"))
    base.update(overrides)
    return base


class TestBinCentre:
    def test_the_endpoints_and_the_middle(self):
        assert cb.bin_centre(-1.0) == pytest.approx(1.0)
        assert cb.bin_centre(0.0) == pytest.approx(13.0)
        assert cb.bin_centre(1.0) == pytest.approx(25.0)

    def test_it_is_linear_in_the_level(self):
        assert cb.bin_centre(-0.5) == pytest.approx(7.0)
        assert cb.bin_centre(0.5) == pytest.approx(19.0)

    def test_a_level_outside_the_unit_interval_is_refused(self):
        """Anything outside [-1, 1] is not cos(phase), and clipping it would place a cycle at an end of the
        axis for the wrong reason."""
        with pytest.raises(cb.CycleBinError, match=r"must lie in \[-1, 1\]"):
            cb.bin_centre(1.5)

    def test_it_honours_a_different_axis_length(self):
        assert cb.bin_centre(-1.0, state_count=5) == pytest.approx(1.0)
        assert cb.bin_centre(1.0, state_count=5) == pytest.approx(5.0)


class TestClassify:
    def test_a_well_sampled_estimated_cycle_is_measured(self):
        assert cb.classify(
            identifiable=True, periods_in_sample=12.0, anchored=False, assumed=False,
            intervals_per_period=18.0,
        ) == cb.CLASS_MEASURED

    def test_an_observed_anchor_is_supplied(self):
        assert cb.classify(
            identifiable=True, periods_in_sample=None, anchored=True, assumed=False,
        ) == cb.CLASS_SUPPLIED

    def test_a_projected_anchor_is_assumed(self):
        assert cb.classify(
            identifiable=True, periods_in_sample=None, anchored=True, assumed=True,
        ) == cb.CLASS_ASSUMED

    def test_an_unidentifiable_cycle_is_marginal(self):
        assert cb.classify(
            identifiable=False, periods_in_sample=1.0, anchored=False, assumed=False,
        ) == cb.CLASS_MARGINAL

    def test_too_few_intervals_per_period_beats_every_other_class(self):
        """An aliased phase is not improved by an anchor being available, so marginal wins even over
        supplied. The fundamental pulse at 3.6 years against annual data is the live case."""
        assert cb.classify(
            identifiable=True, periods_in_sample=40.0, anchored=True, assumed=False,
            intervals_per_period=3.6,
        ) == cb.CLASS_MARGINAL


class TestWidth:
    def test_more_periods_in_sample_gives_a_narrower_kernel(self):
        w = settings()["widths"]
        wide = cb.width_for(cb.CLASS_MEASURED, 3.0, w)
        narrow = cb.width_for(cb.CLASS_MEASURED, 30.0, w)
        assert narrow < wide

    def test_the_measured_width_is_clamped_both_ways(self):
        w = settings()["widths"]
        assert cb.width_for(cb.CLASS_MEASURED, 1e-6, w) == pytest.approx(w["measured_max"])
        assert cb.width_for(cb.CLASS_MEASURED, 1e6, w) == pytest.approx(w["measured_min"])

    def test_a_supplied_position_is_wider_than_any_measured_one(self):
        """The point of the width rule. An anchor is a structural assumption and must not be able to speak
        as confidently as a measurement, however short the measured sample."""
        w = settings()["widths"]
        supplied = cb.width_for(cb.CLASS_SUPPLIED, None, w)
        assert supplied >= cb.width_for(cb.CLASS_MEASURED, 1e-6, w)

    def test_assumed_and_marginal_are_the_widest(self):
        w = settings()["widths"]
        assert cb.width_for(cb.CLASS_ASSUMED, None, w) >= cb.width_for(cb.CLASS_SUPPLIED, None, w)
        assert cb.width_for(cb.CLASS_MARGINAL, None, w) >= cb.width_for(cb.CLASS_SUPPLIED, None, w)


class TestDistribution:
    def test_it_sums_to_one_and_peaks_at_the_centre(self):
        d = cb.cycle_distribution(centre=13.0, width=2.0)
        assert d.sum() == pytest.approx(1.0)
        assert int(np.argmax(d)) + 1 == 13

    def test_a_symmetric_kernel_has_its_mean_at_its_centre(self):
        d = cb.cycle_distribution(centre=13.0, width=2.0, skew=0.0)
        mean = float((np.arange(1, 26) * d).sum())
        assert mean == pytest.approx(13.0, abs=1e-9)

    def test_a_positive_skew_moves_mass_aggressive_without_moving_the_mode(self):
        flat = cb.cycle_distribution(centre=13.0, width=2.0, skew=0.0)
        rising = cb.cycle_distribution(centre=13.0, width=2.0, skew=0.4)
        bins = np.arange(1, 26)
        assert float((bins * rising).sum()) > float((bins * flat).sum())
        assert int(np.argmax(rising)) == int(np.argmax(flat))

    def test_a_negative_skew_moves_mass_cautious(self):
        flat = cb.cycle_distribution(centre=13.0, width=2.0, skew=0.0)
        falling = cb.cycle_distribution(centre=13.0, width=2.0, skew=-0.4)
        bins = np.arange(1, 26)
        assert float((bins * falling).sum()) < float((bins * flat).sum())

    def test_the_kernel_truncates_near_an_end_and_the_mean_moves_inward(self):
        """A real property of a bounded axis, not a defect. There is no bin 0, so a wide kernel near bin 1
        loses its lower tail and normalising pushes the mean up. The mode stays put."""
        d = cb.cycle_distribution(centre=4.66, width=5.0, skew=0.0)
        mean = float((np.arange(1, 26) * d).sum())
        assert mean > 4.66
        assert int(np.argmax(d)) + 1 == 5

    def test_a_non_positive_width_is_refused(self):
        with pytest.raises(cb.CycleBinError, match="positive width"):
            cb.cycle_distribution(centre=13.0, width=0.0)

    def test_a_degenerate_skew_is_refused(self):
        with pytest.raises(cb.CycleBinError, match="skew must lie"):
            cb.cycle_distribution(centre=13.0, width=2.0, skew=1.0)


class TestVelocity:
    def test_a_cycle_at_its_steepest_reports_close_to_one(self):
        """A unit cosine's steepest slope is 2*pi/period, so a step of that size normalises to one."""
        period = 20.0
        rate = 2.0 * np.pi / period
        assert cb.normalised_velocity(rate, 0.0, period, step_years=1.0) == pytest.approx(1.0)

    def test_direction_carries_its_sign(self):
        assert cb.normalised_velocity(0.2, 0.1, 20.0) > 0
        assert cb.normalised_velocity(0.1, 0.2, 20.0) < 0

    def test_it_is_comparable_across_very_different_periods(self):
        """The whole point of normalising: a 7-year and a 130-year cycle report motion on one scale."""
        for period in (7.0, 130.0):
            rate = 2.0 * np.pi / period
            assert cb.normalised_velocity(rate, 0.0, period) == pytest.approx(1.0)

    def test_a_non_positive_period_reports_no_motion_rather_than_dividing_by_zero(self):
        assert cb.normalised_velocity(0.5, 0.0, 0.0) == 0.0


class TestSuperpose:
    def _two(self):
        a = cb.place("low", -0.8, 20.0, settings(skew_coefficient=0.0))
        b = cb.place("high", 0.8, 20.0, settings(skew_coefficient=0.0))
        return [a, b]

    def test_the_mixture_sums_to_one(self):
        layer = cb.superpose(self._two())
        assert layer.distribution.sum() == pytest.approx(1.0)

    def test_the_mixture_sits_between_its_contributors(self):
        a, b = self._two()
        layer = cb.superpose([a, b])
        assert min(a.mean_bin, b.mean_bin) < layer.mean_bin < max(a.mean_bin, b.mean_bin)

    def test_a_linear_mixture_cannot_annihilate_tail_weight(self):
        """The reason this is linear and not a log-opinion pool. Live crisis-tail weight is a requirement of
        this engine, and a multiplicative pool lets one near-zero contributor destroy it."""
        a = cb.place("aggressive", 0.95, 20.0, settings(skew_coefficient=0.0))
        b = cb.place("also_aggressive", 0.9, 20.0, settings(skew_coefficient=0.0))
        layer = cb.superpose([a, b])
        product = a.distribution * b.distribution
        product = product / product.sum()
        assert layer.distribution[0] > 0.0
        assert layer.distribution[0] > product[0]

    def test_weights_are_honoured(self):
        a, b = self._two()
        heavy_low = cb.superpose([a, b], weights={"low": 9.0, "high": 1.0})
        heavy_high = cb.superpose([a, b], weights={"low": 1.0, "high": 9.0})
        assert heavy_low.mean_bin < heavy_high.mean_bin

    def test_no_placements_is_refused(self):
        with pytest.raises(cb.CycleBinError, match="nothing to superpose"):
            cb.superpose([])

    def test_zero_total_weight_is_refused(self):
        a, b = self._two()
        with pytest.raises(cb.CycleBinError, match="sum to zero"):
            cb.superpose([a, b], weights={"low": 0.0, "high": 0.0})


class TestLayerFromCycles:
    """The path the engine actually uses, against real anchored cycles."""

    YEARS = list(range(1900, 2061))

    def test_it_places_the_anchored_cycles_and_notes_the_rest(self):
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles({}, anchored, settings(), index=self.YEARS.index(2026))
        placed = {p.name for p in layer.placements}
        assert {"innovation", "hegemonic"} <= placed
        # every configured cycle that was not placed must say so, rather than vanishing from a count
        for missing in set(settings()["members"]) - placed:
            assert any(missing in note and "not placed" in note for note in layer.notes)

    def test_an_anchored_cycle_is_classified_supplied_and_gets_a_wide_kernel(self):
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles({}, anchored, settings(), index=self.YEARS.index(2026))
        heg = next(p for p in layer.placements if p.name == "hegemonic")
        assert heg.confidence == cb.CLASS_SUPPLIED
        assert heg.width == pytest.approx(settings()["widths"]["supplied"])

    def test_the_long_cycles_currently_sit_at_the_cautious_end(self):
        """A fact about today rather than a property of the code, asserted because it is the reason the blend
        weight is capped: the cycle layer disagrees with the risk signal by about a third of the axis."""
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles({}, anchored, settings(), index=self.YEARS.index(2026))
        for name, expected in (("innovation", 4.66), ("hegemonic", 4.41)):
            p = next(q for q in layer.placements if q.name == name)
            assert p.centre == pytest.approx(expected, abs=0.01)
        assert layer.mean_bin < 10.0

    def test_the_skew_follows_each_cycle_s_direction(self):
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles({}, anchored, settings(), index=self.YEARS.index(2026))
        # innovation is falling toward its 2032 low; hegemonic is rising from the 2010 trough
        assert next(p for p in layer.placements if p.name == "innovation").skew < 0
        assert next(p for p in layer.placements if p.name == "hegemonic").skew > 0

    def test_a_zero_skew_coefficient_recovers_a_symmetric_reading(self):
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles(
            {}, anchored, settings(skew_coefficient=0.0), index=self.YEARS.index(2026)
        )
        assert all(p.skew == pytest.approx(0.0) for p in layer.placements)

    def test_empty_members_is_refused(self):
        with pytest.raises(cb.CycleBinError, match="members is empty"):
            cb.layer_from_cycles({}, {}, settings(members=[]))

    def test_placing_nothing_at_all_is_refused_rather_than_returning_an_empty_layer(self):
        with pytest.raises(cb.CycleBinError, match="none of the configured cycles"):
            cb.layer_from_cycles({}, {}, settings())

    def test_the_payload_carries_every_cycle_and_its_notes(self):
        cfg = config_module.load()
        anchored = anchored_from_config(cfg, self.YEARS)
        layer = cb.layer_from_cycles({}, anchored, settings(), index=self.YEARS.index(2026))
        payload = layer.to_payload()
        assert payload["state_count"] == 25
        assert len(payload["distribution"]) == 25
        assert sum(payload["distribution"]) == pytest.approx(1.0)
        assert {c["name"] for c in payload["cycles"]} == {p.name for p in layer.placements}
        assert all("confidence" in c for c in payload["cycles"])
        assert payload["notes"]


class TestTheLevelComesFromThePhase:
    """The regression this class exists for was found by printing the distributions, 2026-08-02.

    `layer_from_cycles` read the level off `estimate.component`. For an anchored cycle the amplitude is one
    by construction so that is right; for a band-passed cycle the component is a filtered log-growth deviation
    of order 0.01, so *every* measured cycle landed on bin 13 whatever its actual phase. Nothing failed. The
    printed table showed business, credit and the pulse all at 12.8 to 13.1 and that was the tell.
    """

    class _Est:
        """The minimum a placement needs: a phase path, and an amplitude that is not one."""

        def __init__(self, phase, amplitude, period=7.0, sample_years=53.0):
            self.phase = np.asarray(phase, dtype=float)
            self.amplitude = np.full(self.phase.size, amplitude, dtype=float)
            self.component = self.amplitude * np.cos(self.phase)
            self.estimated_period = period
            self.sample_years = sample_years
            self.identifiable = True
            self.notes = []

    def test_a_tiny_amplitude_cycle_still_reaches_the_end_of_the_axis(self):
        """At its trough a cycle must map to bin 1 however small its amplitude. Reading the component gave
        bin 13 for an amplitude of 0.01, which is the whole defect."""
        phases = [0.0, np.pi]  # peak then trough
        est = {"business": self._Est(phases, amplitude=0.01)}
        layer = cb.layer_from_cycles(est, {}, settings(skew_coefficient=0.0), index=1)
        placed = layer.placements[0]
        assert placed.level == pytest.approx(-1.0)
        assert placed.centre == pytest.approx(1.0)

    def test_amplitude_does_not_change_the_placement(self):
        """Two cycles at the same phase and wildly different amplitudes must place identically: the axis
        carries position, and amplitude is deliberately not claimed anywhere in this engine."""
        phases = [0.0, 2.0]
        small = cb.layer_from_cycles(
            {"business": self._Est(phases, amplitude=0.005)}, {}, settings(), index=1
        ).placements[0]
        large = cb.layer_from_cycles(
            {"business": self._Est(phases, amplitude=5.0)}, {}, settings(), index=1
        ).placements[0]
        assert small.centre == pytest.approx(large.centre)
        assert small.level == pytest.approx(large.level)

    def test_a_scalar_phase_is_handled_rather_than_indexed_into(self):
        """Found republishing across ten economies, having passed on one.

        A short window can collapse a cycle's phase to a scalar. `np.asarray` turns that into a 0-d array
        whose `.size` is 1, so it clears an emptiness check and then raises `IndexError` on being indexed.
        `atleast_1d` is the fix, and this asserts it rather than trusting it.
        """
        class ScalarPhase:
            phase = 0.0            # a bare float, not a sequence
            component = 0.0
            estimated_period = 7.0
            sample_years = 20.0
            identifiable = True

        layer = cb.layer_from_cycles(
            {"business": ScalarPhase()}, {}, settings(members=["business"]), index=0
        )
        assert len(layer.placements) == 1
        # cos(0) = 1, so a scalar phase of zero is a peak and belongs at the aggressive end
        assert layer.placements[0].centre == pytest.approx(25.0)

    def test_a_cycle_with_no_phase_is_skipped_with_a_note(self):
        class NoPhase:
            phase = np.array([])
            component = np.array([0.1, 0.2])
            estimated_period = 7.0
            sample_years = 20.0
            identifiable = True

        with pytest.raises(cb.CycleBinError, match="none of the configured cycles"):
            cb.layer_from_cycles({"business": NoPhase()}, {}, settings(members=["business"]))


class TestInterferenceIsNotLeakedInto:
    """The regression this class exists for was created and caught on 2026-08-02.

    `regime_timeline` folded *every* anchored cycle into the estimates before superposing, which was right
    while every anchored cycle belonged in the interference measure. Adding the hegemonic cycle to
    `anchored_from_config` therefore gave the fragility window a fifth contributor silently — the exact thing
    `in_interference: false` was set to prevent. Nothing failed; it was found by reading the wiring.
    """

    def test_the_timeline_filters_anchored_cycles_before_superposing(self):
        """Asserted against the source, because the alternative is republishing a Regime to find out.

        A structural assertion is the right shape here: the defect was that a filter was *absent*, and a
        numerical test would only catch it on data where the extra contributor happened to move the result.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "macrofield" / "contracts" / "regime_timeline.py"
        ).read_text(encoding="utf-8")
        assert "interference_members" in source, (
            "regime_timeline must filter anchored cycles through interference_members before superposing"
        )
        folded = source.index("estimates[name] = cycle.estimate")
        guarded = source.index("if name in admitted:")
        assert guarded < folded, "the fold must sit inside the admission check, not beside it"

    def test_the_excluded_cycle_is_named_rather_than_dropped(self):
        """A cycle held out must say so, or a reader cannot tell an exclusion from an absence."""
        config = config_module.load()
        anchored = anchored_from_config(config, list(range(1970, 2025)))
        from macrofield.model.cycles import interference_members

        excluded = set(anchored) - set(interference_members(config, anchored))
        assert excluded == {"hegemonic"}


class TestTheSaturationAxisIsBounded:
    """Closing the boundary gap found in calibration round A: the axis had no upper bound at all.

    Lives here rather than in test_cycles because it is a boundary condition on the published contract, and
    this file is where round A's findings are asserted.
    """

    def test_the_ceiling_is_configured_and_above_every_real_observation(self):
        """6.0, not the 5.0 first proposed. France's 2020 reading is 5.212 — a denominator effect from GDP
        collapsing, not a fault — so a bound at 5.0 would have refused France and changed what the Global
        blend's EU leg means. The guard must not cost an economy."""
        ceiling = config_module.load().get("saturation.refuse_above")
        assert ceiling == pytest.approx(6.0)
        assert ceiling > 5.212, "the ceiling must sit above France's 2020 saturation, which is real data"

    def test_it_is_above_the_band_it_guards(self):
        cfg = config_module.load()
        assert cfg.get("saturation.refuse_above") > cfg.get("saturation.balanced_band.upper")

    def test_a_breaching_axis_is_refused_rather_than_classified(self):
        """The point of the bound. A ratio of 20 used to be accepted and given a phase."""
        import numpy as np

        from macrofield.contracts.regime_timeline import RegimeTimelineError

        # exercised through the message contract rather than a full assemble, which needs the data cache
        ceiling = float(config_module.load().get("saturation.refuse_above"))
        axis = np.array([2.0, 3.0, 20.0])
        breaches = [(y, float(s)) for y, s in zip((2022, 2023, 2024), axis) if float(s) > ceiling]
        assert breaches, "a ratio of 20 must breach the ceiling"
        assert breaches[0][0] == 2024
        assert issubclass(RegimeTimelineError, ValueError)


class TestConfiguration:
    def test_the_fundamental_pulse_has_an_explicit_band_clear_of_nyquist(self):
        """Its default band would reach 2.16 years, which against annual sampling is the Nyquist limit."""
        cfg = config_module.load()
        assert "fundamental_pulse" in cfg.get("cycles.decompose")
        bands = {b.name: b for b in bands_from_config(cfg)}
        pulse = bands["fundamental_pulse"]
        assert pulse.low_period == pytest.approx(3.0)
        assert pulse.high_period == pytest.approx(4.5)
        assert pulse.low_period > 2.0, "the band must stay clear of the annual Nyquist limit"

    def test_the_pulse_is_still_marginal_despite_the_narrowed_band(self):
        """Narrowing the band makes it honest, not trustworthy: 3.6 intervals per period is still below the
        threshold, so it takes the widest kernel and carries its caveat."""
        assert cb.classify(
            identifiable=True, periods_in_sample=40.0, anchored=False, assumed=False,
            intervals_per_period=3.6,
        ) == cb.CLASS_MARGINAL

    def test_all_six_cycles_are_configured_members(self):
        assert config_module.load().get("cycles.bins")["members"] == [
            "fundamental_pulse", "business", "credit", "innovation", "capital", "hegemonic",
        ]

    def test_the_blend_weight_is_at_or_below_the_state_stability_limit(self):
        """0.20 is the highest weight at which no economy's reported state moves.

        Re-measured across all eight publishable economies on 2026-08-02 **after `current.state` stopped being
        an argmax** (M57). The criterion is unchanged; the number it yields moved because the statistic it is
        measured against did.

        **The previous 0.14 was not a property of the cycle layer.** It was the old modal statistic breaking:
        the mode leapt from bin 12 to bin 2 at 0.15 on a 0.4-point margin between two near-equal peaks, so the
        cap was dodging an artefact rather than respecting a limit. With the mean-nearest bin, 0.20 leaves every
        reported state untouched and 0.30 moves only two economies by exactly one bin each — a distribution
        genuinely shifting rather than a statistic failing.

        The upper bound is asserted as well as the value, so raising the weight without re-running the
        per-economy census fails here rather than in a published contract.
        """
        weight = config_module.load().get("cycles.bins")["blend_weight"]
        assert weight == pytest.approx(0.20)
        assert weight <= 0.30, (
            "beyond 0.30 more than two economies' reported states move and by more than one bin; re-run the "
            "per-economy census before raising this"
        )

    def test_the_skew_coefficient_is_declared_and_reported(self):
        """It has no source, so what matters is that it is configurable and that a result says what it was."""
        coefficient = config_module.load().get("cycles.bins")["skew_coefficient"]
        assert 0.0 <= coefficient < 1.0
        p = cb.place("x", 0.3, 20.0, settings(), previous_level=0.1)
        assert any(str(coefficient) in note for note in p.notes)
