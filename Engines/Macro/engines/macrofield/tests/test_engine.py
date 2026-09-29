"""Unit and property tests of the pure engine. No store, no network.

The properties are the ones the model has to satisfy whatever the data: the two-body identity
holds exactly, Genreith's residual is the stimulus, the closed-form balanced-growth path is
reproduced, the normalisation leaves K_R/K_I alone, the uplift is level only, phases are
exhaustive and the latch only ever holds Phase 4, gaps are dropped and never filled.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from macrofield import assembly, dynamics, phases
from macrofield.calibration import V1_0_0
from macrofield.contracts import EconomySpec, EconomyState, PhaseThresholds
from macrofield.fitting import FitError, numeric_derivative

positive = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)
rate = st.floats(min_value=-0.2, max_value=0.6, allow_nan=False, allow_infinity=False)


def constant(value: float):
    return lambda _t: value


def params(p_s=0.2, p_p=0.05, p_b=0.01, alpha=0.3, stimulus=0.0) -> dynamics.Parameters:
    return dynamics.Parameters(p_s=constant(p_s), p_p=constant(p_p), p_b=constant(p_b),
                               alpha=constant(alpha), stimulus=constant(stimulus))


# ---------------------------------------------------------------------------
# dynamics
# ---------------------------------------------------------------------------

@settings(max_examples=300, deadline=None)
@given(y=positive, k_r=positive, k_i=positive, p_s=rate, p_p=rate, p_b=rate, alpha=rate,
       s=st.floats(min_value=-10, max_value=10), closure=st.sampled_from(["as_written",
                                                                           "identity_closed"]))
def test_two_body_identity_is_exact_and_genreith_residual_is_the_stimulus(
        y, k_r, k_i, p_s, p_p, p_b, alpha, s, closure):
    p = params(p_s, p_p, p_b, alpha, s)
    state = (y, k_r, k_i)
    scale = max(abs(k_r + k_i), abs(y), 1.0) * (1.0 + abs(k_i / y) + abs(s))
    assert abs(dynamics.two_body_residual(0.0, state, p, closure)) <= 1e-12 * scale
    assert dynamics.genreith_residual(0.0, state, p, closure) == pytest.approx(s, abs=1e-12 * scale)


def test_identity_closed_mode_halves_the_output_equation():
    p = params(p_s=0.25, p_b=0.03, stimulus=4.0)
    d = dynamics.derivatives(0.0, (100.0, 50.0, 200.0), p, "identity_closed")
    assert d[0] == pytest.approx(0.5 * ((0.03 - 0.25) * 100.0 + 4.0))


def test_balanced_growth_closed_form_is_reproduced():
    # S = 0, p_s -> 0, K_R = Y, p_b = p_p: every state grows as exp(p_p t).
    p_p = 0.04
    p = params(p_s=1e-12, p_p=p_p, p_b=p_p, alpha=0.0, stimulus=0.0)
    t = np.linspace(0.0, 30.0, 31)
    sim = dynamics.simulate((1.0, 1.0, 2.5), p, (0.0, 30.0), t_eval=t)
    exact = dynamics.balanced_growth_solution((1.0, 1.0, 2.5), p_p, t)
    assert sim.success
    for name in ("Y", "K_R", "K_I"):
        np.testing.assert_allclose(getattr(sim, name), exact[name], rtol=1e-7)


def test_p_p_identity_forces_contraction_in_a_production_economy():
    # r > 0 (K_R < Y) makes every term positive, so the implied output growth is negative.
    implied = dynamics.p_p_implied_output_growth(0.0, (100.0, 60.0, 150.0), params())
    assert implied < 0.0


def test_simulate_refuses_a_non_positive_initial_state():
    with pytest.raises(ValueError):
        dynamics.simulate((0.0, 1.0, 1.0), params(), (0.0, 1.0), t_eval=np.array([0.0, 1.0]))


# ---------------------------------------------------------------------------
# derivatives
# ---------------------------------------------------------------------------

def test_savitzky_golay_derivative_is_exact_on_a_quadratic():
    t = np.arange(12, dtype=float)
    d = numeric_derivative(3.0 * t ** 2 + 2.0 * t + 1.0, t, "savitzky_golay", 5, 2)
    np.testing.assert_allclose(d, 6.0 * t + 2.0, atol=1e-9)


def test_derivative_refuses_to_differentiate_across_a_gap():
    with pytest.raises(FitError):
        numeric_derivative(np.array([1.0, 2.0, np.nan, 4.0, 5.0]), np.arange(5.0),
                           "savitzky_golay", 5, 2)


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------

T = PhaseThresholds()


@settings(max_examples=300, deadline=None)
@given(sat=st.floats(min_value=0.0, max_value=6.0), k_r=positive, k_i=positive, y=positive)
def test_every_period_gets_exactly_one_phase_with_the_documented_precedence(sat, k_r, k_i, y):
    c = phases.classify_period(sat, k_r, k_i, y, T)
    assert c.phase in (1, 2, 3, 4)
    if k_r / k_i < T.saturation_real_to_financial_ceiling or sat >= T.optimisation_saturation_ceiling:
        assert c.phase == 4
    elif sat < T.foundation_saturation_ceiling:
        assert c.phase == 1
    assert c.in_balanced_band == (T.balanced_band.lower <= sat <= T.balanced_band.upper)


def test_phase_four_is_latched_until_the_foundation_level():
    sat = np.array([2.0, 3.6, 3.0, 2.0, 0.9, 1.5])
    k = np.ones_like(sat)
    # K_R/Y = 2 (financial economy) and K_R/K_I = 2, so only saturation moves the phase.
    latched, stateless = phases.classify_sequence(sat, 2 * k, k, k, T)
    assert [c.phase for c in stateless] == [3, 4, 3, 3, 1, 3]
    assert [c.phase for c in latched] == [3, 4, 4, 4, 1, 3]


@settings(max_examples=100, deadline=None)
@given(st.lists(st.floats(min_value=0.0, max_value=5.0), min_size=1, max_size=30))
def test_latch_only_ever_replaces_a_phase_with_four_or_releases_to_one(sats):
    sat = np.array(sats)
    k = np.ones_like(sat)
    latched, stateless = phases.classify_sequence(sat, 2 * k, k, 10 * k, T)
    for held, free in zip(latched, stateless):
        assert held.phase == free.phase or held.phase in (1, 4)


def test_unsecured_acceleration_needs_consecutive_periods():
    # Second differences from index 2: 0.1, 0.1, 0.1, 0.1, -0.3.
    k_i = np.array([1.0, 1.0, 1.1, 1.3, 1.6, 2.0, 2.1])
    mask = phases.unsecured_accelerating(np.zeros(7), k_i, np.zeros(7), periods=3)
    assert mask.tolist() == [False, False, False, False, True, True, False]


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

SPEC = EconomySpec(code="XX", name="Test", world_bank="XXX", bis="XX", pwt="XXX",
                   stimulus_proxy="fiscal_balance", stimulus_reverse_sign=True,
                   depreciation_prior=0.05)
CAL = V1_0_0.model_copy(update={"economies": (SPEC,)})


def synthetic(years=range(2000, 2016), pwt_end=2012, gap: int | None = None) -> dict:
    ys = list(years)
    obs = {
        assembly.GDP: {y: 1e12 * 1.04 ** i for i, y in enumerate(ys)},
        assembly.CREDIT: {y: 150.0 + 3 * i for i, y in enumerate(ys)},
        assembly.SAVINGS: {y: 22.0 for y in ys},
        assembly.FISCAL: {y: -3.0 + 0.1 * i for i, y in enumerate(ys)},
        assembly.POPULATION: {y: 1e7 * 1.01 ** i for i, y in enumerate(ys)},
        assembly.GFCF_SHARE: {y: 20.0 for y in ys},
        assembly.REAL_GROWTH: {y: 2.0 for y in ys},
        assembly.PWT_CN: {y: 3e6 + 1e4 * i for i, y in enumerate(ys) if y <= pwt_end},
        assembly.PWT_CGDPO: {y: 1e6 for y in ys if y <= pwt_end},
        assembly.PWT_DELTA: {y: 0.04 for y in ys if y <= pwt_end},
    }
    if gap is not None:
        obs[assembly.SAVINGS][gap] = None
    return obs


def test_normalisation_puts_the_window_maximum_at_target_and_keeps_k_r_over_k_i():
    a = assembly.assemble(SPEC, synthetic(), CAL)
    assert float(np.max(a.real_capital / a.output)) == pytest.approx(CAL.capital_target)
    unscaled = (a.real_capital_ratio * a.output) / (a.saturation * a.output)
    np.testing.assert_allclose(a.real_capital / a.financial_capital, unscaled, rtol=1e-14)


def test_real_capital_ratio_is_extended_by_perpetual_inventory_in_ratio_space():
    a = assembly.assemble(SPEC, synthetic(), CAL)
    years = a.years.tolist()
    assert a.extended_years == (2013, 2014, 2015)
    k2012 = a.real_capital_ratio[years.index(2012)]
    expected = (1.0 - 0.04) * k2012 / (1.0 + 0.02) + 0.20   # delta carried from 2012
    assert a.real_capital_ratio[years.index(2013)] == pytest.approx(expected, rel=1e-15)


def test_uplift_is_a_pure_level_scale():
    base = assembly.assemble(SPEC, synthetic(), CAL.model_copy(update={"credit_uplift": 1.0}))
    up = assembly.assemble(SPEC, synthetic(), CAL)
    np.testing.assert_allclose(up.saturation, 1.4 * base.saturation, rtol=1e-15)
    np.testing.assert_allclose(np.diff(np.log(up.saturation)), np.diff(np.log(base.saturation)),
                               rtol=1e-12)


def test_a_gap_is_dropped_and_listed_never_filled():
    a = assembly.assemble(SPEC, synthetic(gap=2005), CAL)
    assert 2005 not in a.years.tolist()
    # 2000 goes too: population growth has no value in the first year.
    assert a.dropped_years == (2000, 2005)


def test_missing_required_series_are_named():
    obs = synthetic()
    del obs[assembly.CREDIT], obs[assembly.FISCAL]
    with pytest.raises(assembly.Unavailable) as exc:
        assembly.assemble(SPEC, obs, CAL)
    assert set(exc.value.missing) == {assembly.CREDIT, assembly.FISCAL}


def test_net_new_credit_is_the_change_in_the_credit_stock_over_output():
    share = assembly.net_new_credit_share({1: 1.0, 2: 1.5}, {1: 100.0, 2: 110.0})
    assert math.isnan(share[1])
    assert share[2] == pytest.approx((1.5 * 110.0 - 1.0 * 100.0) / 110.0)


def test_refusal_ceiling_rejects_an_ingestion_fault():
    obs = synthetic()
    obs[assembly.CREDIT][2010] = 900.0
    with pytest.raises(assembly.Unavailable, match="refusal ceiling"):
        assembly.assemble(SPEC, obs, CAL)


def test_the_latch_carries_a_saturation_episode_from_before_the_window():
    from macrofield.engine import phase_sequences

    obs = synthetic(years=range(1990, 2016))
    # Credit peaks above the Phase 3 ceiling in the 1990s and falls back; the window is later.
    obs[assembly.CREDIT] = {y: (300.0 if y < 1996 else 180.0) for y in range(1990, 2016)}
    spec = SPEC.model_copy(update={"window_start": 2000})
    full = CAL.model_copy(update={"phases": CAL.phases.model_copy(
        update={"latch_from_full_history": True})})
    a = assembly.assemble(spec, obs, full)
    latched, stateless, history = phase_sequences(a, full)
    assert history.years[0] == 1990 and history.phase[0] == 4
    assert all(c.phase == 4 for c in latched)          # still in the reordering
    assert all(c.phase != 4 for c in stateless)        # the window alone never saturates
    window_only, _, _ = phase_sequences(a, CAL)
    assert all(c.phase != 4 for c in window_only)      # the prototype's rule forgets it


def test_start_latched_holds_phase_four_until_foundation():
    sat = np.array([2.0, 1.5, 0.8, 2.0])
    k = np.ones_like(sat)
    latched, _ = phases.classify_sequence(sat, 2 * k, k, k, T, start_latched=True)
    assert [c.phase for c in latched] == [4, 4, 1, 3]


# ---------------------------------------------------------------------------
# projection levers
# ---------------------------------------------------------------------------

def test_levers_shape_the_multiplier_over_the_projected_years():
    from macrofield.contracts import ControlSpec
    from macrofield.projection import lever

    years = np.arange(2025, 2033, dtype=float)
    assert lever(ControlSpec(), years).tolist() == [1.0] * 8
    assert lever(ControlSpec(mode="step", target=2.0, start_year=2028), years).tolist() ==         [1, 1, 1, 2, 2, 2, 2, 2]
    assert lever(ControlSpec(mode="pulse", target=2.0, start_year=2027, end_year=2028),
                 years).tolist() == [1, 1, 2, 2, 1, 1, 1, 1]
    ramp = lever(ControlSpec(mode="ramp", target=2.0, start_year=2026, end_year=2028), years)
    np.testing.assert_allclose(ramp, [1, 1, 1.5, 2, 2, 2, 2, 2])


def test_an_incomplete_lever_is_refused():
    from macrofield.contracts import ControlSpec

    with pytest.raises(ValueError):
        ControlSpec(mode="pulse", target=2.0, start_year=2027)


def test_projection_is_unavailable_without_an_integrable_fit(raw_observations):
    from macrofield.engine import run_economy

    de = run_economy(V1_0_0.economy("DE"), raw_observations["DE"], V1_0_0)
    assert de.simulated is None
    assert de.projection.status == "unavailable" and "integrable" in de.projection.reason


# ---------------------------------------------------------------------------
# alternative saturation axes and aggregates (calibrations 1.2.0 and 1.3.0)
# ---------------------------------------------------------------------------

def test_bundesbank_series_are_year_end_values_in_euro():
    from macrofield.sources import bundesbank_year_end

    rows = ['"",BBBK1.M.OU0308', "1998-11,100.0,", "1998-12,195.583,", "1999-01,90.0,",
            "1999-12,120.0,", "2000-06,130.0,"]
    csv = "\n".join(rows).encode()
    assert bundesbank_year_end(csv, "t") == {1998: pytest.approx(100.0), 1999: 120.0}


def test_genreith_axis_uses_the_bank_balance_sheet_and_a_territory_splice():
    obs = synthetic(years=range(1980, 2000))
    obs.update({assembly.BANK_TOTAL: {y: 2000.0 for y in range(1980, 2000)},
                assembly.BANK_LOANS: {y: 900.0 for y in range(1980, 2000)},
                assembly.JST_GDP: {y: 1955.83 for y in range(1980, 1990)},   # DM bn
                assembly.GDP_LCU: {y: 1.25e12 for y in range(1980, 2000)}})
    spec = SPEC.model_copy(update={"saturation_source": "bank_balance_sheet", "bank_area": "XX",
                                   "gdp_splice_year": 1990, "jst_currency_divisor": 1.95583})
    sat, share, _ = assembly.bank_saturation(spec, obs)
    assert sat[1985] == pytest.approx(2.0)        # 2000 bn EUR over 1000 bn EUR (JST, DM)
    assert sat[1995] == pytest.approx(1.6)        # 2000 bn EUR over 1250 bn EUR (World Bank)
    assert share[1995] == pytest.approx(0.45)


def test_the_commercial_bank_share_floor_is_genreiths_phase_iv():
    t = T.model_copy(update={"commercial_bank_share_floor": 0.5})
    assert phases.classify_period(2.0, 2.0, 1.0, 1.0, t, commercial_share=0.49).phase == 4
    assert phases.classify_period(2.0, 2.0, 1.0, 1.0, t, commercial_share=0.51).phase == 3
    assert phases.classify_period(2.0, 2.0, 1.0, 1.0, T, commercial_share=0.10).phase == 3


def test_imf_debt_axis_is_private_plus_government_debt():
    obs = {assembly.IMF_PRIVATE: {2000: 100.0, 2001: 110.0, 2030: 500.0},
           assembly.IMF_GOV_WEO: {2000: 40.0, 2001: 50.0, 2030: 90.0}}
    ratio, notes = assembly.imf_debt_ratio(obs, last_year=2024)
    assert ratio == {2000: pytest.approx(1.4), 2001: pytest.approx(1.6)}   # forecasts cut
    assert "WEO" in notes[0]


def test_pwt_aggregate_sums_members_in_years_all_publish():
    k = assembly.member_key
    obs = {k(assembly.PWT_CN, "A"): {2000: 3.0, 2001: 3.0}, k(assembly.PWT_CGDPO, "A"): {2000: 1.0, 2001: 1.0},
           k(assembly.PWT_DELTA, "A"): {2000: 0.04, 2001: 0.04},
           k(assembly.PWT_CN, "B"): {2001: 1.0}, k(assembly.PWT_CGDPO, "B"): {2001: 1.0},
           k(assembly.PWT_DELTA, "B"): {2001: 0.08}}
    merged = assembly.aggregate_pwt(obs, ("A", "B"))
    assert merged[assembly.PWT_CN] == {2001: 4.0} and merged[assembly.PWT_CGDPO] == {2001: 2.0}
    assert merged[assembly.PWT_DELTA][2001] == pytest.approx(0.05)   # capital-weighted


def test_a_weak_evidence_projection_is_flagged(raw_observations):
    from macrofield.engine import run_economy

    cal = V1_0_0.model_copy(update={"projection": V1_0_0.projection.model_copy(
        update={"require_integrable_fit": False})})
    de = run_economy(cal.economy("DE"), raw_observations["DE"], cal)
    assert de.simulated is None
    assert de.projection.status == "ok" and de.projection.fit_reproduces_window is False
    assert de.projection.notes[0].startswith("WEAK EVIDENCE")
    assert de.projection.directional_accuracy == {"Y": None, "K_R": None, "K_I": None}


# ---------------------------------------------------------------------------
# contracts
# ---------------------------------------------------------------------------

def test_an_unavailable_economy_must_say_why():
    with pytest.raises(ValueError):
        EconomyState(code="US", name="United States", status="unavailable")


def test_non_finite_values_are_rejected():
    from macrofield.contracts import StatePaths

    with pytest.raises(ValueError):
        StatePaths(Y=(1.0, float("nan")), K_R=(1.0, 1.0), K_I=(1.0, 1.0))
