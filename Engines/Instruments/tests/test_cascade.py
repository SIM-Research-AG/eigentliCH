"""The per-instrument cascade: own data, interpolate, borrow, seed -- in that order."""

from __future__ import annotations

import math

import pytest

from engines.fund_map.calibrate import METHOD_STRENGTH, Method
from engines.fund_map.estimate import (
    MIN_MATCH_CORRELATION,
    MIN_OVERLAP_MONTHS,
    Candidate,
    MonthlyReturn,
    StateBucket,
    _interpolate_known,
    bucket_by_state,
    correlation,
    estimate_buckets,
    estimate_instrument,
    find_closest_match,
    label_months,
    fit_shape,
)
from engines.fund_map.roles import RoleProfile
from engines.fund_map.state_map import StateMap, StateMapEntry


def make_state_map(mapping: dict[int, int]) -> StateMap:
    return StateMap(
        method="test", signal_first="2000-01", signal_last="2020-12",
        entries=tuple(
            StateMapEntry(s, 0.0, 0.0, float(mapping.get(s, s)), mapping.get(s, s))
            for s in range(1, 26)
        ),
    )


def make_role_profile(value: float = 0.04) -> RoleProfile:
    return RoleProfile(
        role="gain", basis="test", members=("equity",), weights={"equity": 1.0},
        phase_means=(value,) * 5, profile_by_state=(value,) * 25,
        methods_by_state=(Method.DATA_DRIVEN,) * 25, n_obs_by_state=(0,) * 25,
        n_obs_by_phase=(10,) * 5,
    )


class TestLabelling:
    def test_months_without_a_signal_are_dropped(self):
        returns = [MonthlyReturn("2020-01", 0.01), MonthlyReturn("2020-02", 0.02)]
        out = label_months(returns, {"2020-01": 5}, make_state_map({5: 7}))
        assert len(out) == 1
        assert out[0][0] == 7

    def test_returns_are_converted_to_log_space(self):
        out = label_months([MonthlyReturn("2020-01", 0.10)], {"2020-01": 3}, make_state_map({}))
        assert out[0][1] == pytest.approx(math.log(1.10))

    def test_a_total_loss_is_dropped_rather_than_crashing(self):
        out = label_months([MonthlyReturn("2020-01", -1.0)], {"2020-01": 3}, make_state_map({}))
        assert out == []


class TestBuckets:
    def test_a_sub_floor_bucket_yields_nothing_and_reports_its_count(self):
        buckets = bucket_by_state([(5, 0.01)] * 4)
        out = estimate_buckets(buckets)
        assert out[4].value is None
        assert out[4].n_obs == 4
        assert out[4].method is Method.INSUFFICIENT

    def test_estimates_are_annualised_from_monthly_log_returns(self):
        monthly = math.log(1.01)
        out = estimate_buckets(bucket_by_state([(3, monthly)] * 10))
        assert out[2].value == pytest.approx(12 * monthly)
        assert out[2].method is Method.DATA_DRIVEN


class TestInterpolation:
    def test_fills_only_the_interior_of_the_hull(self):
        buckets = [StateBucket(s, 0, None, Method.INSUFFICIENT) for s in range(1, 26)]
        buckets[4] = StateBucket(5, 10, 0.02, Method.DATA_DRIVEN)
        buckets[19] = StateBucket(20, 10, 0.08, Method.DATA_DRIVEN)
        filled = _interpolate_known(buckets)
        assert min(filled) == 6 and max(filled) == 19
        assert 4 not in filled and 21 not in filled

    def test_a_single_known_state_cannot_be_interpolated_around(self):
        buckets = [StateBucket(s, 0, None, Method.INSUFFICIENT) for s in range(1, 26)]
        buckets[9] = StateBucket(10, 10, 0.02, Method.DATA_DRIVEN)
        assert _interpolate_known(buckets) == {}


class TestClosestMatch:
    @staticmethod
    def series(seed: float, n: int = 60, flip: bool = False) -> dict[str, float]:
        out = {}
        for i in range(n):
            base = math.sin(i * 0.7 + seed) * 0.03
            out[f"20{10 + i // 12:02d}-{i % 12 + 1:02d}"] = -base if flip else base
        return out

    def test_correlation_is_none_for_a_constant_series(self):
        assert correlation([1.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0]) is None

    def test_picks_the_highest_correlated_peer_in_the_role(self):
        target = self.series(0.0)
        near = Candidate("near", "gain", "Global", self.series(0.05), [0.01] * 25)
        far = Candidate("far", "gain", "Global", self.series(1.9), [0.02] * 25)
        match = find_closest_match(target, [far, near], role="gain")
        assert match is not None and match.instrument_id == "near"

    def test_never_borrows_across_roles(self):
        """CHF Cash must not take its crisis behaviour from Global Equities.

        An earlier version widened the search when no same-role peer qualified, and that
        is exactly what it did. A cross-role match is not a weaker right answer; it is a
        wrong one, and the role seed is preferable.
        """
        target = self.series(0.0)
        other_role = Candidate("equities", "gain", "Global", self.series(0.02), [0.09] * 25)
        assert find_closest_match(target, [other_role], role="protection") is None

    def test_rejects_a_peer_with_too_little_overlap(self):
        target = self.series(0.0, n=MIN_OVERLAP_MONTHS - 1)
        peer = Candidate("p", "gain", "Global", self.series(0.0, n=MIN_OVERLAP_MONTHS - 1),
                         [0.01] * 25)
        assert find_closest_match(target, [peer], role="gain") is None

    def test_rejects_a_peer_below_the_correlation_floor(self):
        target = self.series(0.0)
        opposite = Candidate("inverse", "gain", "Global", self.series(0.0, flip=True), [0.01] * 25)
        match = find_closest_match(target, [opposite], role="gain")
        assert match is None, (
            f"an inversely correlated peer must not qualify; floor is {MIN_MATCH_CORRELATION}"
        )


class TestCascadeOrder:
    def test_with_no_history_everything_seeds_from_the_role(self):
        profile = estimate_instrument(
            "INS-new", "gain", [], {}, make_state_map({}), make_role_profile(0.07),
        )
        assert set(profile.methods_by_state) == {Method.SEED}
        assert profile.profile_by_state == (0.07,) * 25
        assert profile.coverage is Method.SEED
        assert profile.borrowed_from is None

    def test_own_data_outranks_borrowing(self):
        returns = [MonthlyReturn(f"20{10 + i // 12:02d}-{i % 12 + 1:02d}", 0.01)
                   for i in range(30)]
        signal = {r.period: 13 for r in returns}
        peer = Candidate("peer", "gain", "Global",
                         {r.period: 0.01 for r in returns}, [0.99] * 25)
        profile = estimate_instrument(
            "INS-x", "gain", returns, signal, make_state_map({13: 13}),
            make_role_profile(), candidates=[peer],
        )
        # State 13 was measured, so it must not carry the peer's 0.99.
        assert profile.methods_by_state[12] is Method.DATA_DRIVEN_TRIMMED
        assert profile.profile_by_state[12] == pytest.approx(12 * math.log(1.01))

    def test_a_filled_state_reports_no_observations(self):
        """Manual section 11.2, and the bug the contract validator caught."""
        returns = [MonthlyReturn(f"20{10 + i // 12:02d}-{i % 12 + 1:02d}", 0.01)
                   for i in range(4)]
        signal = {r.period: 13 for r in returns}
        profile = estimate_instrument(
            "INS-thin", "gain", returns, signal, make_state_map({13: 13}), make_role_profile(),
        )
        for state, (method, n) in enumerate(
            zip(profile.methods_by_state, profile.n_obs_by_state), start=1
        ):
            if method in (Method.SEED, Method.BORROWED, Method.INTERPOLATED,
                          Method.EXTRAPOLATED):
                assert n == 0, f"state {state} is {method.value} but claims n_obs={n}"

    def test_sub_floor_counts_are_kept_as_a_diagnostic(self):
        """Five observations and none are different facts; zeroing n_obs must not erase it."""
        returns = [MonthlyReturn(f"20{10 + i // 12:02d}-{i % 12 + 1:02d}", 0.01)
                   for i in range(4)]
        signal = {r.period: 13 for r in returns}
        profile = estimate_instrument(
            "INS-thin", "gain", returns, signal, make_state_map({13: 13}), make_role_profile(),
        )
        assert profile.n_obs_by_state[12] == 0
        assert profile.n_obs_discarded_by_state[12] == 4

    def test_coverage_is_the_weakest_method_present(self):
        assert METHOD_STRENGTH.index(Method.SEED) < METHOD_STRENGTH.index(Method.BORROWED)
        assert METHOD_STRENGTH.index(Method.BORROWED) < METHOD_STRENGTH.index(Method.INTERPOLATED)
        assert (METHOD_STRENGTH.index(Method.INTERPOLATED)
                < METHOD_STRENGTH.index(Method.DATA_DRIVEN))


class TestIdenticalPeersAreNotEvidence:
    """A candidate with the same returns as the target must not be borrowed from.

    Several register entries share one public proxy, so their monthly returns are equal
    to the last decimal -- 365 of 365 months for the Swiss entries on EWL. Correlation
    cannot reject that: it scores exactly 1.0, the best possible, so the degenerate peer
    wins the ranking and a thin bucket is relabelled `borrowed` while no new information
    has entered.
    """

    @staticmethod
    def _returns(values):
        return {f"20{10 + i // 12:02d}-{i % 12 + 1:02d}": v for i, v in enumerate(values)}

    def test_an_identical_candidate_is_rejected(self):
        target = self._returns([0.01, -0.02, 0.03, -0.01] * 9)
        twin = Candidate(
            instrument_id="INS-twin", role="gain", region_scope="Europe",
            returns=dict(target), profile_by_state=[0.05] * 25,
        )
        assert find_closest_match(target, [twin], role="gain") is None, (
            "borrowed from a candidate carrying the identical series"
        )

    def test_a_genuinely_similar_candidate_is_still_accepted(self):
        """The rejection must be narrow: near-identical is fine, identical is not."""
        base = [0.01, -0.02, 0.03, -0.01] * 9
        target = self._returns(base)
        peer = Candidate(
            instrument_id="INS-peer", role="gain", region_scope="Europe",
            returns=self._returns([v + 0.0005 for v in base]),
            profile_by_state=[0.05] * 25,
        )
        match = find_closest_match(target, [peer], role="gain")
        assert match is not None and match.instrument_id == "INS-peer"
        assert match.score > 0.99

    def test_an_identical_twin_does_not_shadow_a_usable_peer(self):
        """With both on offer, the real peer wins rather than the perfect-scoring copy."""
        base = [0.01, -0.02, 0.03, -0.01] * 9
        target = self._returns(base)
        twin = Candidate(
            instrument_id="INS-twin", role="gain", region_scope="Europe",
            returns=dict(target), profile_by_state=[0.99] * 25,
        )
        peer = Candidate(
            instrument_id="INS-peer", role="gain", region_scope="Europe",
            returns=self._returns([v * 1.2 + 0.001 for v in base]),
            profile_by_state=[0.05] * 25,
        )
        match = find_closest_match(target, [twin, peer], role="gain")
        assert match is not None and match.instrument_id == "INS-peer"


class TestShapeScaledEstimator:
    """D2: shape from the 150-year calibration, level and amplitude from own returns.

    The cascade reads twenty-five conditional means from roughly two hundred monthly
    observations. D2 reads two parameters from the same months. These tests pin the two
    properties that make it worth having, and the one it must not have.
    """

    @staticmethod
    def _months(values):
        return [MonthlyReturn(f"20{10 + i // 12:02d}-{i % 12 + 1:02d}", v)
                for i, v in enumerate(values)]

    def _peer(self, name, values, role="protection"):
        months = self._months(values)
        return Candidate(
            instrument_id=name, role=role, region_scope="Global",
            returns={m.period: m.value for m in months},
            profile_by_state=[0.03] * 25,
        )

    def test_amplitude_is_the_volatility_ratio_not_a_regression(self):
        """Twice its peers' volatility means twice their swing across states."""
        calm = [0.01, -0.01] * 24
        lively = [0.02, -0.02] * 24
        peers = [self._peer("INS-a", calm), self._peer("INS-b", calm)]

        quiet = fit_shape(self._months(calm), peers, role="protection")
        loud = fit_shape(self._months(lively), peers, role="protection")
        assert quiet is not None and loud is not None
        assert quiet.amplitude == pytest.approx(1.0, abs=0.02)
        assert loud.amplitude == pytest.approx(2.0, abs=0.05)

    def test_it_never_inverts_the_role_shape(self):
        """An instrument moving against its role is a role question, not an amplitude one.

        An earlier version fitted the amplitude by regressing bucket means on the role
        shape, and returned -2.83 for Precious Metals and +26 for CS Long Vola: it had
        inherited the noise of the very buckets D2 exists to stop trusting.
        """
        peers = [self._peer("INS-a", [0.01, -0.01] * 24)]
        for values in ([0.05, -0.05] * 24, [-0.03, 0.01] * 24, [0.0001, -0.0001] * 24):
            fit = fit_shape(self._months(values), peers, role="protection")
            assert fit is None or fit.amplitude >= 0.0

    def test_too_little_history_declines_rather_than_guessing(self):
        peers = [self._peer("INS-a", [0.01, -0.01] * 24)]
        assert fit_shape(self._months([0.01] * 12), peers, role="protection") is None

    def test_no_peer_in_the_role_declines(self):
        """Without peers there is no vol_role, and an amplitude cannot be formed."""
        peers = [self._peer("INS-a", [0.01, -0.01] * 24, role="gain")]
        assert fit_shape(self._months([0.01, -0.01] * 24), peers,
                         role="protection") is None
