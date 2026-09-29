"""The acceptance tests from System Build Manual section 11.7, numbered as it numbers them.

Where this build knowingly departs from the manual, the test asserts the departure and
says why, rather than being omitted. A test suite that quietly drops the check it fails is
worse than no suite.
"""

from __future__ import annotations

import pytest

from contracts.return_set import BANNED_KEYS, ContractError, Profile, StateValue, reject_moments
from engines.fund_map.calibrate import (
    SUFFICIENCY_FLOOR,
    TRIM_SWITCH,
    Estimator,
    Method,
    _estimate_phase,
    state_axis,
    state_methods,
)
from engines.fund_map.phases import PHASE_NAMES
from tests.conftest import needs_sources


# --- 1. A misaligned series fails a check rather than producing a plausible profile ----

@needs_sources
def test_1_injected_tagging_offset_breaks_the_shape_assertions(calibration, long_record):
    """Shift the phase timeline by one year and the measured shapes stop holding.

    This is both acceptance test 1 and test 5: the shape assertions are the check that a
    misalignment trips, and a one-period tagging offset is how misalignment happens.
    """
    from engines.fund_map.calibrate import build_block_returns, calibrate_all
    from engines.fund_map.phases import PhaseTimeline

    good = calibration["timeline"]
    # Roll the labels by one year while leaving the returns where they are.
    offset = PhaseTimeline(good.first_year, tuple(good.phases[1:] + good.phases[:1]))
    blocks = calibrate_all(build_block_returns(long_record), offset)

    means = {k: [e.mean for e in v.phase_estimates] for k, v in blocks.items()}
    shapes = [
        all(b >= a for a, b in zip(means["equity"], means["equity"][1:])),
        means["gold"].index(max(means["gold"])) == 0,
        means["commodities"].index(max(means["commodities"])) == 1,
        means["gold"][4] < 0,
    ]
    # The real calibration passes all four; a misaligned one must not.
    assert not all(shapes), (
        "a one-year tagging offset still reproduced every shape, so the shape assertions "
        "are not sensitive enough to catch misalignment"
    )


# --- 2. Five observations return nothing; twenty return a trimmed value ---------------

def test_2a_below_the_floor_returns_nothing():
    estimate = _estimate_phase([0.01] * (SUFFICIENCY_FLOOR - 1), Estimator.MANUAL_FLOOR, "crisis")
    assert estimate.mean is None
    assert estimate.method is Method.INSUFFICIENT
    assert estimate.n_obs == SUFFICIENCY_FLOOR - 1


def test_2b_at_the_trim_switch_the_value_is_labelled_trimmed():
    values = [float(i) for i in range(TRIM_SWITCH)]
    estimate = _estimate_phase(values, Estimator.MANUAL_FLOOR, "boom")
    assert estimate.method is Method.DATA_DRIVEN_TRIMMED
    # 20 % from each end of 20 observations leaves the middle twelve, 4..15, mean 9.5.
    assert estimate.mean == pytest.approx(9.5)


def test_2c_between_the_floor_and_the_switch_the_value_is_a_plain_mean():
    values = [float(i) for i in range(10)]
    estimate = _estimate_phase(values, Estimator.MANUAL_FLOOR, "stagnation")
    assert estimate.method is Method.DATA_DRIVEN
    assert estimate.mean == pytest.approx(4.5)


def test_2d_the_reference_estimator_never_withholds():
    """``PLAIN_MEAN`` reproduces Steiner, which takes a mean at every count.

    The divergence from the manual is deliberate and is recorded on the calibration, so
    the test pins the behaviour rather than pretending the two agree.
    """
    estimate = _estimate_phase([1.0, 2.0], Estimator.PLAIN_MEAN, "crisis")
    assert estimate.mean == pytest.approx(1.5)
    assert estimate.method is Method.DATA_DRIVEN


# --- 3. Every value carries a method; a value with no method fails the boundary --------

def test_3_a_state_without_a_method_is_rejected():
    with pytest.raises(Exception):
        StateValue(state=1, value=0.01, n_obs=10)  # type: ignore[call-arg]


def test_3b_a_filled_value_claiming_observations_is_rejected():
    with pytest.raises(ValueError, match="carries no observations"):
        StateValue(state=4, value=0.01, method="interpolated", n_obs=3)


def test_3c_a_measured_value_claiming_no_observations_is_rejected():
    with pytest.raises(ValueError, match="with no observations"):
        StateValue(state=4, value=0.01, method="data-driven", n_obs=0)


def test_3d_a_profile_must_be_complete_and_ordered():
    states = tuple(
        StateValue(state=i, value=0.0, method="seed", n_obs=0) for i in range(1, 25)
    )
    with pytest.raises(Exception):
        Profile(key="x", kind="role", coverage="seed", states=states)


# --- 4. A payload carrying a mean or a covariance is refused ---------------------------

@pytest.mark.parametrize("key", sorted(BANNED_KEYS))
def test_4_every_banned_key_is_refused(key):
    with pytest.raises(ContractError):
        reject_moments({"profiles": [{"state": 1, key: 0.1}]})


def test_4b_a_clean_payload_passes():
    reject_moments({"states": [{"state": 1, "value": 0.1, "method": "seed", "n_obs": 0}]})


def test_4c_the_check_reaches_arbitrary_depth():
    with pytest.raises(ContractError, match=r"\$\.a\[0\]\.b\.covariance"):
        reject_moments({"a": [{"b": {"covariance": [[1]]}}]})


# --- 6. Extrapolation ------------------------------------------------------------------

def test_6_the_calibration_extrapolates_four_states_and_labels_them():
    """The one-off calibration *does* extrapolate, against the manual's test 6.

    This is the documented divergence: the reference evaluates the interpolant on
    0.6..5.4 over knots at 1..5, and reproducing its published figures means reproducing
    those four out-of-hull values. The manual's intent -- never fill a tail silently -- is
    met by labelling them ``extrapolated`` rather than by refusing to produce them.
    """
    methods = state_methods([Method.DATA_DRIVEN] * len(PHASE_NAMES))
    assert [i + 1 for i, m in enumerate(methods) if m is Method.EXTRAPOLATED] == [1, 2, 24, 25]
    assert sum(1 for m in methods if m is Method.DATA_DRIVEN) == 5
    assert sum(1 for m in methods if m is Method.INTERPOLATED) == 16


def test_6b_the_measured_knots_land_on_states_3_8_13_18_23():
    axis = state_axis()
    knots = [i + 1 for i, q in enumerate(axis) if abs(q - round(q)) < 1e-12 and 1 <= q <= 5]
    assert knots == [3, 8, 13, 18, 23]


def test_6c_the_per_instrument_estimator_refuses_to_extrapolate():
    """Unlike the calibration, the instrument estimator never fills outside the hull.

    It has no published reference to reproduce, and outside an instrument's own observed
    states lie crisis and boom -- where a fabricated value does the most damage. It falls
    through to borrow or seed instead.
    """
    from engines.fund_map.estimate import StateBucket, _interpolate_known

    buckets = [
        StateBucket(s, 0, None, Method.INSUFFICIENT) for s in range(1, 26)
    ]
    buckets[9] = StateBucket(10, 12, 0.05, Method.DATA_DRIVEN)
    buckets[14] = StateBucket(15, 12, 0.07, Method.DATA_DRIVEN)
    filled = _interpolate_known(buckets)
    assert set(filled) == {11, 12, 13, 14}, "only the interior of the hull may be filled"
