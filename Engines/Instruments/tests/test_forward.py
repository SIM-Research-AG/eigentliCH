"""The 12 month forward measurement (R-003, D-02) and point-of-use currency (D-01).

Pure functions, no database: synthetic signals and returns whose right answer is known.
"""

from __future__ import annotations

import math

import pytest

from engines.fund_map.calibrate import SUFFICIENCY_FLOOR, Method
from engines.fund_map.currency import (
    CurrencyError,
    convert_returns,
    cross_rates,
    source_currency,
)
from engines.fund_map.estimate import MonthlyReturn, ProfileMethod, ShapeFit, estimate_instrument
from engines.fund_map.forward import (
    add_months,
    effective_observations,
    estimate_forward,
    forward_windows,
    phase_of_state,
)
from tests.test_cascade import make_role_profile, make_state_map


def months(first: str, n: int) -> list[str]:
    return [add_months(first, i) for i in range(n)]


def identity_map():
    return make_state_map({})


class TestWindows:
    def test_a_window_starts_the_month_after_the_tagged_month(self):
        """The tagged month's own return is not its own forecast."""
        periods = months("2010-01", 14)
        returns = {p: 0.0 for p in periods}
        returns["2010-01"] = 0.50                 # the tagged month: must not count
        returns["2010-02"] = math.expm1(0.12)     # first month of the window
        signal = {"2010-01": 1}
        [w] = forward_windows(returns, signal, identity_map())
        assert w.start == "2010-01" and w.state == 1 and w.phase == 0
        assert w.value == pytest.approx(0.12)

    def test_the_value_is_the_twelve_month_log_return(self):
        periods = months("2010-01", 13)
        returns = {p: 0.01 for p in periods}
        [w] = forward_windows(returns, {"2010-01": 13}, identity_map())
        assert w.value == pytest.approx(12 * math.log1p(0.01))
        assert w.phase == 2

    def test_an_incomplete_window_is_dropped_never_filled(self):
        returns = {p: 0.01 for p in months("2010-02", 12)}
        del returns["2010-07"]
        assert forward_windows(returns, {"2010-01": 1}, identity_map()) == []

    def test_phases_are_bands_of_five_states(self):
        assert [phase_of_state(s) for s in (1, 5, 6, 13, 20, 21, 25)] == [0, 0, 1, 2, 3, 4, 4]


class TestEffectiveObservations:
    def test_consecutive_windows_are_about_months_over_twelve(self):
        """Twelve consecutive starts share eleven months each: about one year of evidence."""
        assert effective_observations(months("2010-01", 12)) == 1
        assert effective_observations(months("2010-01", 72)) == 6

    def test_windows_years_apart_count_one_each(self):
        starts = [f"{2000 + 2 * i}-01" for i in range(6)]
        assert effective_observations(starts) == 6

    def test_never_more_than_the_number_of_windows(self):
        assert effective_observations(["2010-01"]) == 1
        assert effective_observations([]) == 0


def crisis_heavy_history(crisis_return: float, other_return: float):
    """Twenty years: every third year's January to December tagged crisis, else expansion.

    Returns in the twelve months after a crisis month earn ``crisis_return`` per month;
    every other month ``other_return``.
    """
    periods = months("2000-01", 12 * 21)
    signal, returns = {}, {}
    for i, p in enumerate(periods[:-12]):
        year = i // 12
        signal[p] = 1 if year % 3 == 0 else 18
    for i, p in enumerate(periods):
        year = (i - 1) // 12
        returns[p] = crisis_return if year % 3 == 0 else other_return
    return returns, signal


class TestTheEstimator:
    def test_a_phase_below_the_floor_is_not_measured(self):
        returns = {p: 0.01 for p in months("2010-01", 30)}
        signal = {p: 1 for p in months("2010-01", 12)}  # one year of crisis: n_eff 1 or 2
        result = estimate_forward("x", "protection", returns, signal, identity_map(),
                                  make_role_profile())
        crisis = result.phases[0]
        assert crisis.n_eff < SUFFICIENCY_FLOOR
        assert crisis.method is Method.SEED  # no D2 fit supplied: the role seed, labelled
        assert result.profile.methods_by_state[:5] == (Method.SEED,) * 5
        assert result.profile.n_obs_by_state[:5] == (0,) * 5

    def test_measured_phases_report_their_effective_count_at_the_knot(self):
        returns, signal = crisis_heavy_history(0.02, 0.0)
        result = estimate_forward("x", "protection", returns, signal, identity_map(),
                                  make_role_profile())
        crisis, expansion = result.phases[0], result.phases[3]
        assert crisis.method is Method.DATA_DRIVEN and crisis.n_eff >= SUFFICIENCY_FLOOR
        assert expansion.method in (Method.DATA_DRIVEN, Method.DATA_DRIVEN_TRIMMED)
        counts = result.profile.n_obs_by_state
        assert counts[2] == crisis.n_eff          # the crisis knot, state 3
        assert counts[0] == counts[1] == 0        # extrapolated: a fill carries none
        assert result.profile.methods_by_state[0] is Method.EXTRAPOLATED

    def test_a_hedge_that_pays_over_the_year_after_crisis_is_positive_in_crisis(self):
        """The R-003 fault in miniature: the forward year after crisis months pays."""
        returns, signal = crisis_heavy_history(0.02, -0.002)
        result = estimate_forward("x", "protection", returns, signal, identity_map(),
                                  make_role_profile())
        p = result.profile.profile_by_state
        assert p[2] > 0 and p[2] > p[17]

    def test_a_thin_phase_is_filled_from_the_scaled_role_shape_and_says_so(self):
        returns, signal = crisis_heavy_history(0.02, 0.0)
        fit = ShapeFit(level=0.05, amplitude=2.0, own_volatility=0.2, role_volatility=0.1,
                       observations=240)
        result = estimate_forward("x", "protection", returns, signal, identity_map(),
                                  make_role_profile(), fit=fit)
        boom = result.phases[4]
        assert boom.method is Method.SHAPE_SCALED
        assert result.profile.methods_by_state[20:] == (Method.SHAPE_SCALED,) * 5
        assert result.profile.n_obs_by_state[22] == 240
        assert result.profile.coverage is Method.SHAPE_SCALED

    def test_estimate_instrument_dispatches_on_the_method(self):
        returns, signal = crisis_heavy_history(0.02, 0.0)
        monthly = [MonthlyReturn(p, v) for p, v in sorted(returns.items())]
        profile = estimate_instrument("x", "protection", monthly, signal, identity_map(),
                                      make_role_profile(),
                                      profile_method=ProfileMethod.FORWARD_12M)
        assert profile.methods_by_state[2] is Method.DATA_DRIVEN

    def test_the_pure_estimators_default_is_still_the_cascade(self):
        """``estimate_instrument`` builds the stored profiles, which stay the cascade's
        (the served default is ``service.DEFAULT_PROFILE_METHOD``, FMRE-22)."""
        import inspect
        default = inspect.signature(estimate_instrument).parameters["profile_method"].default
        assert default is ProfileMethod.CASCADE


class TestTheSmoothing:
    """FMRE-22: the served default is the forward measurement, lightly smoothed."""

    #: A pchip-like profile with one sharp dip (the Mining Equities pattern) and a sign
    #: change near zero, so both guards have something to do.
    PROFILE = ([0.12, 0.10, 0.08, 0.00, -0.12, -0.22, -0.24, -0.25, -0.24, -0.15,
                -0.05, 0.004, 0.02, 0.03, 0.04, 0.05, 0.05, 0.05, 0.08, 0.12,
                0.18, 0.24, 0.26, 0.27, 0.28])

    def test_no_phase_value_moves_by_more_than_the_tolerance(self):
        from engines.fund_map.forward import KNOT_INDEX, SMOOTHING_TOLERANCE, smooth_profile
        out, _ = smooth_profile(self.PROFILE)
        for k in KNOT_INDEX:
            assert abs(out[k] - self.PROFILE[k]) <= SMOOTHING_TOLERANCE + 1e-12
        # The dip is the knot's own measurement; the kernel alone would lift it further.
        unguarded, _ = smooth_profile(self.PROFILE, tolerance=1.0)
        assert abs(unguarded[7] - self.PROFILE[7]) > SMOOTHING_TOLERANCE

    def test_no_state_changes_sign(self):
        from engines.fund_map.forward import smooth_profile
        out, held = smooth_profile(self.PROFILE)
        assert all((a > 0) == (b > 0) and (a < 0) == (b < 0)
                   for a, b in zip(self.PROFILE, out))
        assert 12 in held, "state 12 (+0.4 %) would have been pulled below zero"

    def test_it_smooths(self):
        """The largest step between neighbouring states comes down."""
        from engines.fund_map.forward import smooth_profile
        out, _ = smooth_profile(self.PROFILE)
        steps = lambda p: max(abs(b - a) for a, b in zip(p, p[1:]))  # noqa: E731
        assert steps(out) < steps(self.PROFILE)

    def test_labels_counts_and_the_measured_values_stay(self):
        from engines.fund_map.forward import smooth_forward
        returns, signal = crisis_heavy_history(0.02, -0.002)
        fit = ShapeFit(level=0.01, amplitude=1.0, own_volatility=0.1, role_volatility=0.1,
                       observations=240)
        raw = estimate_forward("x", "protection", returns, signal, identity_map(),
                               make_role_profile(), fit=fit)
        result = smooth_forward(raw)
        methods = result.profile.methods_by_state
        assert result.unsmoothed == raw.profile, "the measured profile stays on the result"
        assert result.phases == raw.phases, "and so do the five measured phase values"
        for before, after, n in zip(raw.profile.methods_by_state, methods,
                                    result.profile.n_obs_by_state):
            if before in (Method.SHAPE_SCALED, Method.SEED):
                assert after is before, "a fill keeps its own, weaker label"
            else:
                assert after is Method.FORWARD_SMOOTHED
                assert n > 0, "a smoothed state is not a fill and names its evidence"
        assert result.profile.coverage is Method.SHAPE_SCALED  # the boom phase is a fill
        assert result.smoothing is not None and len(result.smoothing.knot_shift) == 5

    def test_a_profile_with_nothing_measured_is_the_role_seed_unchanged(self):
        from engines.fund_map.forward import smooth_forward
        role = make_role_profile()
        raw = estimate_forward("x", "protection", {}, {}, identity_map(), role)
        result = smooth_forward(raw)
        assert result.profile == raw.profile
        assert set(result.profile.methods_by_state) == {Method.SEED}

    def test_estimate_instrument_dispatches_on_the_smoothed_method(self):
        returns, signal = crisis_heavy_history(0.02, 0.0)
        monthly = [MonthlyReturn(p, v) for p, v in sorted(returns.items())]
        profile = estimate_instrument("x", "protection", monthly, signal, identity_map(),
                                      make_role_profile(),
                                      profile_method=ProfileMethod.FORWARD_12M_SMOOTHED)
        assert profile.methods_by_state[2] is Method.FORWARD_SMOOTHED

    def test_the_served_default_is_the_smoothed_forward_measurement(self, monkeypatch):
        from engines.fund_map import service
        monkeypatch.delenv(service.PROFILE_METHOD_VAR, raising=False)
        assert service.configured_profile_method() is ProfileMethod.FORWARD_12M_SMOOTHED
        assert service.STORED_PROFILE_METHOD is ProfileMethod.CASCADE

    def test_the_label_is_in_the_contract(self):
        from typing import get_args
        from contracts.return_set import MethodLabel
        assert "forward-12m-smoothed" in get_args(MethodLabel)


class TestCurrency:
    LEVELS = {
        "fx.USDCHF": {"2020-01": 1.00, "2020-02": 0.90, "2020-03": 0.90},
        "fx.EURCHF": {"2020-01": 1.10, "2020-02": 1.10, "2020-03": 1.21},
    }

    def test_a_usd_return_in_chf_carries_the_dollar(self):
        rates = cross_rates(self.LEVELS)
        out = convert_returns({"2020-02": 0.10}, "USD", "CHF", rates)
        assert out["2020-02"] == pytest.approx(1.10 * 0.90 / 1.00 - 1)

    def test_cross_rates_convert_between_the_two_non_franc_currencies(self):
        rates = cross_rates(self.LEVELS)
        out = convert_returns({"2020-03": 0.0}, "USD", "EUR", rates)
        # USD in EUR: 0.90/1.10 in February, 0.90/1.21 in March.
        assert out["2020-03"] == pytest.approx((0.90 / 1.21) / (0.90 / 1.10) - 1)

    def test_a_round_trip_returns_the_original(self):
        rates = cross_rates(self.LEVELS)
        there = convert_returns({"2020-02": 0.05, "2020-03": -0.02}, "CHF", "USD", rates)
        back = convert_returns(there, "USD", "CHF", rates)
        assert back["2020-02"] == pytest.approx(0.05)
        assert back["2020-03"] == pytest.approx(-0.02)

    def test_a_month_without_a_rate_is_dropped_not_filled(self):
        rates = cross_rates(self.LEVELS)
        assert convert_returns({"2020-01": 0.1}, "USD", "CHF", rates) == {}

    def test_no_target_or_the_same_currency_leaves_the_series_alone(self):
        series = {"2020-02": 0.1}
        assert convert_returns(series, "USD", None, {}) == series
        assert convert_returns(series, "CHF", "CHF", {}) == series

    def test_an_unknown_currency_is_refused(self):
        with pytest.raises(CurrencyError):
            convert_returns({"2020-02": 0.1}, "USD", "GBP", cross_rates(self.LEVELS))

    def test_the_stored_series_currency_follows_its_source_not_the_register(self):
        assert source_currency("yahoo:GLD:close", "CHF") == "USD"
        assert source_currency("andersch-report:recovered", "USD") == "CHF"
        assert source_currency("api", "EUR") == "EUR"
