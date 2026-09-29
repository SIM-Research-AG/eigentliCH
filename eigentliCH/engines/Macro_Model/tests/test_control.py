"""Tests for control paths and provenance, phase 0 of the battle plan."""

import numpy as np
import pytest

from macrofield.control import (
    ControlError,
    ControlMode,
    ControlPath,
    Provenance,
    Segment,
    Traced,
)

YEARS = np.arange(2020, 2036)


class TestProvenance:
    """The ordering is the point: a mixed series takes the weakest of its parts."""

    def test_the_order_runs_from_measured_to_invented(self):
        ranks = [p.rank for p in (
            Provenance.OBSERVED,
            Provenance.DERIVED,
            Provenance.INTEGRATED,
            Provenance.EXTRAPOLATED,
            Provenance.ASSUMED,
        )]
        assert ranks == sorted(ranks)

    def test_a_mixed_series_is_as_weak_as_its_weakest_part(self):
        assert Provenance.weakest_of([Provenance.OBSERVED, Provenance.EXTRAPOLATED]) is (
            Provenance.EXTRAPOLATED
        )
        assert Provenance.weakest_of([Provenance.ASSUMED, Provenance.OBSERVED]) is Provenance.ASSUMED

    def test_only_extrapolated_and_assumed_count_as_invented(self):
        """An integrated value is a model consequence of observed inputs, not an invention."""
        assert Provenance.EXTRAPOLATED.is_invented
        assert Provenance.ASSUMED.is_invented
        assert not Provenance.OBSERVED.is_invented
        assert not Provenance.DERIVED.is_invented
        assert not Provenance.INTEGRATED.is_invented

    def test_weakest_of_nothing_is_an_error(self):
        with pytest.raises(ControlError, match="no provenance"):
            Provenance.weakest_of([])


class TestTraced:
    def test_the_series_provenance_is_the_weakest_segment(self):
        traced = Traced(
            values=np.arange(10.0),
            segments=[
                Segment(0, 6, Provenance.INTEGRATED, "integrated"),
                Segment(7, 9, Provenance.EXTRAPOLATED, "past the singularity"),
            ],
        )
        assert traced.provenance is Provenance.EXTRAPOLATED

    def test_the_split_point_is_where_invention_starts(self):
        """A chart needs this to draw the invented tail differently."""
        traced = Traced(
            values=np.arange(10.0),
            segments=[
                Segment(0, 6, Provenance.INTEGRATED),
                Segment(7, 9, Provenance.ASSUMED),
            ],
        )
        assert traced.first_invented_index() == 7

    def test_a_wholly_observed_series_has_no_split(self):
        traced = Traced(np.arange(5.0), [Segment(0, 4, Provenance.OBSERVED)])
        assert traced.first_invented_index() is None
        assert traced.provenance is Provenance.OBSERVED


class TestControlPathShapes:
    def test_constant_is_flat(self):
        path = ControlPath.constant(1.3)
        assert np.allclose(path.to_array(YEARS), 1.3)

    def test_step_holds_then_jumps(self):
        path = ControlPath(ControlMode.STEP, base=1.0, target=1.5, start_period=2027)
        values = path.to_array(YEARS)
        assert values[YEARS < 2027].tolist() == [1.0] * int((YEARS < 2027).sum())
        assert np.allclose(values[YEARS >= 2027], 1.5)

    def test_ramp_interpolates_then_holds(self):
        path = ControlPath(ControlMode.RAMP, base=1.0, target=1.5, start_period=2027, end_period=2031)
        values = path.to_array(YEARS)
        assert values[int(np.flatnonzero(YEARS == 2027)[0])] == pytest.approx(1.0)
        assert values[int(np.flatnonzero(YEARS == 2029)[0])] == pytest.approx(1.25)
        assert values[int(np.flatnonzero(YEARS == 2031)[0])] == pytest.approx(1.5)
        assert np.allclose(values[YEARS > 2031], 1.5)

    def test_pulse_returns_to_base(self):
        """The shape a time-limited stimulus programme takes."""
        path = ControlPath(ControlMode.PULSE, base=1.0, target=1.03, start_period=2027, end_period=2030)
        values = path.to_array(YEARS)
        inside = (YEARS >= 2027) & (YEARS <= 2030)
        assert np.allclose(values[inside], 1.03)
        assert np.allclose(values[~inside], 1.0)

    def test_a_zero_length_ramp_behaves_as_a_step(self):
        path = ControlPath(ControlMode.RAMP, base=1.0, target=2.0, start_period=2027, end_period=2027)
        values = path.to_array(YEARS)
        assert np.allclose(values[YEARS >= 2027], 2.0)

    def test_an_empty_period_range_gives_an_empty_array(self):
        assert ControlPath.constant().to_array([]).size == 0


class TestControlPathValidation:
    @pytest.mark.parametrize("mode", [ControlMode.STEP, ControlMode.RAMP, ControlMode.PULSE])
    def test_every_non_constant_mode_needs_a_target(self, mode):
        with pytest.raises(ControlError, match="needs a target"):
            ControlPath(mode, base=1.0, start_period=2027, end_period=2030)

    @pytest.mark.parametrize("mode", [ControlMode.RAMP, ControlMode.PULSE])
    def test_ramp_and_pulse_need_an_end(self, mode):
        with pytest.raises(ControlError, match="needs an end_period"):
            ControlPath(mode, base=1.0, target=1.5, start_period=2027)

    def test_a_backwards_window_is_refused(self):
        with pytest.raises(ControlError, match="before start_period"):
            ControlPath(ControlMode.RAMP, base=1.0, target=1.5, start_period=2030, end_period=2027)

    def test_non_numeric_periods_are_refused(self):
        """A shape over time needs an ordering, so period labels have to be numbers."""
        with pytest.raises(ControlError, match="numeric periods"):
            ControlPath(ControlMode.STEP, base=1.0, target=2.0, start_period=2027).to_array(
                ["first", "second"]
            )


class TestControlPathParsing:
    def test_a_bare_number_is_a_constant(self):
        """This is what keeps the existing scalar multiplier API working unchanged."""
        path = ControlPath.from_spec(1.4)
        assert path.mode is ControlMode.CONSTANT
        assert path.base == 1.4

    def test_none_is_the_identity(self):
        assert ControlPath.from_spec(None).is_identity

    @pytest.mark.parametrize(
        "spec,mode,base,target,start,end",
        [
            ("constant:1.2", ControlMode.CONSTANT, 1.2, None, None, None),
            ("step:1.0>1.5@2027", ControlMode.STEP, 1.0, 1.5, 2027, None),
            ("ramp:1.0>1.5@2027-2031", ControlMode.RAMP, 1.0, 1.5, 2027, 2031),
            ("pulse:1.0>1.03@2027-2030", ControlMode.PULSE, 1.0, 1.03, 2027, 2030),
        ],
    )
    def test_the_compact_url_form_round_trips(self, spec, mode, base, target, start, end):
        path = ControlPath.from_spec(spec)
        assert path.mode is mode
        assert path.base == pytest.approx(base)
        assert (path.target is None and target is None) or path.target == pytest.approx(target)
        assert path.start_period == start
        assert path.end_period == end

    def test_a_mapping_round_trips_through_as_dict(self):
        original = ControlPath(
            ControlMode.PULSE, base=1.0, target=1.05, start_period=2028, end_period=2031, label="S"
        )
        rebuilt = ControlPath.from_spec(original.as_dict())
        assert rebuilt.to_array(YEARS).tolist() == original.to_array(YEARS).tolist()

    def test_an_unknown_mode_names_the_valid_ones(self):
        with pytest.raises(ControlError, match="unknown control mode"):
            ControlPath.from_spec("wibble:1>2@2027")

    def test_an_incomplete_spec_says_what_is_missing(self):
        with pytest.raises(ControlError, match="incomplete"):
            ControlPath.from_spec("step:1.5")

    def test_nonsense_is_refused_with_the_expected_form(self):
        with pytest.raises(ControlError, match="not a control path"):
            ControlPath.from_spec("later on")


class TestDescription:
    """Every lever has to be able to say what it did, for the manifest and the chart footer."""

    @pytest.mark.parametrize(
        "spec,fragment",
        [
            ("1.0", "held at 1"),
            ("step:1.0>1.5@2027", "steps from 1 to 1.5 in 2027"),
            ("ramp:1.0>1.5@2027-2031", "ramps from 1 to 1.5 between 2027 and 2031"),
            ("pulse:1.0>1.03@2027-2030", "pulses to 1.03 from 2027 to 2030"),
        ],
    )
    def test_the_description_states_the_shape(self, spec, fragment):
        assert fragment in ControlPath.from_spec(spec, label="stimulus").describe()

    def test_the_identity_is_recognisable(self):
        assert ControlPath.constant(1.0).is_identity
        assert not ControlPath.constant(1.4).is_identity
