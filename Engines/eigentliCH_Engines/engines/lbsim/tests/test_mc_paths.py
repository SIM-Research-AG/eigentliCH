"""The paths artefact (spec 9.B): the market rule, common random numbers, determinism, the properties of chances
and bands in both bases, the stated plan and the section 5 budgets."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from stub import Stub, bundle, stated

from lbsim.calibration import ACTIVE_SEED
from lbsim.contracts import QUANTILES, LifeBalancePaths
from lbsim.paths import engine as E
from lbsim.paths.build import build_paths, fan, paths_key, simulate_regimes
from lbsim.paths.household import resolve_horizon
from lbsim.paths.market import StateCurve, draws, market_quantiles, states_for, year_table

CASE = "lbsim-sample"
_STUB = Stub((CASE,))
SHEET, REQUEST, RECORDS, FINDINGS, PLAN = stated(CASE)
FULL = bundle(_STUB, SHEET)
BASE_ONLY = bundle(_STUB, SHEET, scenarios=())


def _paths(plan=PLAN, b=FULL, *, n=300, seed=7) -> LifeBalancePaths:
    return build_paths(FINDINGS, plan, b, ACTIVE_SEED, n_paths=n, seed=seed)


def _with_inflation(b, fn):
    regimes = tuple(replace(r, curve=StateCurve(log_return=r.curve.log_return,
                                                log_inflation=fn(r.curve.log_inflation))) for r in b.regimes)
    return replace(b, regimes=regimes)


# --- the market rule (LBSIM-07) ------------------------------------------------------------------------------

def test_year_one_is_the_allocations_distribution_reverting_to_the_long_run():
    base = FULL.regimes[0]
    t = year_table(base, base, 10, ACTIVE_SEED.market)
    latest = np.asarray(FULL.allocation.curves.regime) / sum(FULL.allocation.curves.regime)
    long_run = base.long_run / base.long_run.sum()
    assert np.allclose(t.dist[0], latest, atol=1e-15)
    assert np.allclose(t.dist[2], latest + (long_run - latest) * 0.4, atol=1e-15)
    for k in range(5, 10):
        assert np.allclose(t.dist[k], long_run, atol=1e-15)
    assert np.allclose(t.dist.sum(axis=1), 1.0)


def test_a_scenario_is_its_projected_months_for_five_years_then_the_base():
    base = FULL.regimes[0]
    for sc in FULL.regimes[1:]:
        t = year_table(sc, base, 8, ACTIVE_SEED.market)
        assert t.scenario_years == 5
        for k in range(1, 6):
            proj = sc.projected[12 * k - 1]
            assert np.allclose(t.dist[k - 1], proj / proj.sum(), atol=1e-15)
            assert np.array_equal(t.log_return[k - 1], sc.curve.log_return)
            assert np.array_equal(t.log_inflation[k - 1], sc.curve.log_inflation)
        bt = year_table(base, base, 8, ACTIVE_SEED.market)
        assert np.array_equal(t.dist[5:], bt.dist[5:]) and np.array_equal(t.log_return[5:], bt.log_return[5:])


def test_the_state_draws_are_the_shared_uniforms_through_each_cdf():
    base = FULL.regimes[0]
    t = year_table(base, base, 6, ACTIVE_SEED.market)
    d = draws(11, 5000, 6)
    s = states_for(t, d)
    for k in range(6):
        freq = np.bincount(s[:, k], minlength=25) / 5000
        assert np.max(np.abs(freq - t.dist[k])) < 0.03
    z = market_quantiles(t)
    assert np.all(np.diff(z[0][t.dist[0] > 0]) > 0)


def test_the_portfolio_curve_is_the_renormalised_weights_on_fmres_profiles():
    b = FULL
    assert b.max_abs_diff <= 1e-9
    total = sum(i.raw_weight for i in b.allocation.instruments)
    achieved = np.asarray(b.allocation.curves.achieved)
    assert np.allclose(b.regimes[0].curve.log_return, achieved / total, atol=1e-12)


# --- common random numbers, determinism --------------------------------------------------------------------

def test_the_base_is_the_same_whatever_scenarios_run_beside_it():
    a = _paths(b=FULL)
    b = _paths(b=BASE_ONLY)
    two = _paths(b=bundle(_STUB, SHEET, scenarios=("hyperinflation", "deferral")))
    base = [p.regimes[0].model_dump(mode="json") for p in (a, b, two)]
    assert base[0] == base[1] == base[2]
    assert a.regimes[4].model_dump(mode="json") == two.regimes[2].model_dump(mode="json")  # deferral
    assert a.provenance.idempotency_key != b.provenance.idempotency_key


def test_same_seed_same_bytes_different_seed_different_key():
    one, two = _paths(seed=5), _paths(seed=5)
    assert json.dumps(one.model_dump(mode="json")) == json.dumps(two.model_dump(mode="json"))
    other = _paths(seed=6)
    assert other.provenance.idempotency_key != one.provenance.idempotency_key
    assert other.artefact_id != one.artefact_id
    assert one.provenance.idempotency_key == paths_key(FINDINGS, FULL, horizon_years=PLAN.horizon_years, n_paths=300,
                                                       seed=5, income_path=PLAN.income_path)


def test_the_paths_carry_everything_the_contract_asks():
    p = _paths()
    assert [r.key for r in p.regimes] == ["base", "depression", "hyperinflation", "stagflation", "deferral"]
    assert p.regimes[0].label.en == "Current assessment" and p.regimes[3].label.de == "Stagflation"
    assert p.regimes[0].inflation_pass_through is None and p.regimes[1].inflation_pass_through == "ipt@1.1.0"
    assert p.provenance.upstream["fmre"]["ipt"] == "IPT-585c7da4656ead2b"
    assert p.provenance.upstream["pcp"]["artefact_id"] == FULL.allocation.artefact_id
    assert set(p.provenance.seeds) == {"state_uniforms", "property_noise", "spare"}
    assert p.provenance.made_by == "engine" and p.steps_per_year == 12
    for r in p.regimes:
        assert set(r.bands) == {"net_worth", "deposit_eligible", "retirement_capital"}
        assert [g.goal_id for g in r.goals] == ["g-home", "g-ret"]


# --- the properties (hypothesis) ---------------------------------------------------------------------------

def _raw(plan, b, seed, n):
    return simulate_regimes(plan, b, ACTIVE_SEED, n_paths=n, seed=seed)


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 2**31 - 1), shift=st.floats(-0.03, 0.12), horizon=st.integers(1, 12))
def test_chances_bands_and_real_bands(seed, shift, horizon):
    _, _, _, _, plan = stated(CASE, horizon=horizon)
    b = _with_inflation(BASE_ONLY, lambda li: li + shift)
    p = build_paths(FINDINGS, plan, b, ACTIVE_SEED, n_paths=200, seed=seed)
    raw = _raw(plan, b, seed, 200)["base"]
    for r in p.regimes:
        for g in r.goals:
            assert 0.0 <= g.chance <= 1.0 and 0 <= g.n_reached <= 200
            assert abs(g.chance - g.n_reached / 200) < 1e-12
        for name, band in r.bands.items():
            for part in (band.nominal, band.real):
                qs = np.array([getattr(part, q) for q in QUANTILES])
                assert np.all(np.diff(qs, axis=0) >= 0.0)
                assert qs.shape == (7, horizon + 1)
            nominal = E.measure_values(raw.states, name, plan.params)
            deflated = nominal / raw.states["P"]
            expect = np.percentile(deflated, [5, 10, 25, 50, 75, 90, 95], axis=1)
            got = np.array([getattr(band.real, q) for q in QUANTILES])
            assert np.allclose(got, expect, rtol=0, atol=1e-6)
            assert band.real.derived is True


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 2**31 - 1))
def test_zero_inflation_makes_the_two_bases_equal(seed):
    b = _with_inflation(FULL, lambda li: np.zeros_like(li))
    _, _, _, _, plan = stated(CASE, horizon=6)
    p = build_paths(FINDINGS, plan, b, ACTIVE_SEED, n_paths=200, seed=seed)
    for r in p.regimes:
        for band in r.bands.values():
            for q in QUANTILES:
                assert getattr(band.real, q) == getattr(band.nominal, q)
        for g in r.goals:
            assert g.target.real_chf == pytest.approx(g.target.nominal_chf, rel=1e-12)


def test_a_goal_in_todays_francs_is_judged_in_real_terms():
    """LBSIM-09: the chance is per path in the goal's basis; in the other basis the target is converted at the
    median path's price level (the dashed line)."""
    p = _paths(n=400, seed=3)
    raw = _raw(PLAN, FULL, 3, 400)
    for r in p.regimes:
        home = r.goals[0]
        assert home.chance_basis == "real" and home.target.amount_basis == "today"
        res = raw[r.key]
        g = next(x for x in PLAN.goals if x.goal_id == "g-home")
        value = E.measure_values(res.states, "deposit_eligible", PLAN.params)[g.year] / res.states["P"][g.year]
        assert home.n_reached == int(np.sum(value >= g.target_real))
        assert home.target.nominal_chf == pytest.approx(g.target_real * np.median(res.states["P"][g.year]))


def test_the_band_at_a_goal_date_is_the_value_before_the_payment():
    """Agent D's finding on the sample: the fan at the home goal's year is the value the chance is judged on."""
    p = _paths(n=400, seed=3)
    raw = _raw(PLAN, FULL, 3, 400)["base"]
    g = next(x for x in PLAN.goals if x.goal_id == "g-home")
    judged = raw.goals["g-home"]["value"] * raw.states["P"][g.year]
    band = p.regimes[0].bands["deposit_eligible"].nominal
    assert band.p50[g.year] == pytest.approx(float(np.percentile(judged, 50)), rel=1e-12)
    assert band.p50[g.year] >= g.target_real


def test_the_fan_route_gives_one_series_with_its_goal_line():
    p = _paths()
    f = fan(p, regime="base", basis="real", series="goal_measure")
    assert f["series"] == "deposit_eligible" and f["derived"] is True and len(f["years"]) == p.horizon_years + 1
    assert f["goal"]["line"] == "solid" and f["goal"]["target_chf"] == p.regimes[0].goals[0].target.real_chf
    n = fan(p, regime="stagflation", basis="nominal", series="goal_measure")
    assert n["goal"]["line"] == "dashed" and n["goal"]["converted"] is True
    w = fan(p, regime="base", basis="nominal", series="net_worth")
    assert "goal" not in w and w["bands"]["p50"] == list(p.regimes[0].bands["net_worth"].nominal.p50)


# --- the stated plan ---------------------------------------------------------------------------------------

def test_the_horizon_rule():
    assert resolve_horizon(None, [3.0, 27.0], 40.0, 65.0, 60) == 27
    assert resolve_horizon(None, [], 40.0, 65.0, 60) == 25
    assert resolve_horizon(12.4, [30.0], 40.0, 65.0, 60) == 13
    assert resolve_horizon(None, [], 2.0, 65.0, 60) == 60
    assert resolve_horizon(None, [], 70.0, 65.0, 60) == 1


def test_the_stated_plan_reads_the_findings_path():
    assert PLAN.income_path == "today" and PLAN.horizon_years == 27
    assert PLAN.policy.spending_chf_per_year == REQUEST.risk.spend_now_per_year
    assert PLAN.policy.saving_source == "cash_flow" and PLAN.policy.fallback is None
    ip = next(i for i in FINDINGS.income_paths if i.code == "today")
    ages = [y.age for y in ip.income]
    assert PLAN.household.income[0] == pytest.approx(ip.income[0].gross_chf_per_year)
    assert len(ages) > 0
    young = stated("lbsim-young")[4]
    assert young.income_path == "education"


def test_spending_not_stated_is_a_named_fallback():
    plan = stated("syn-property-1")[4]
    assert plan.policy.saving_source == "stated_contribution" and plan.policy.fallback.en.startswith("Spending")
    plan = stated("syn-liquidity")[4]
    assert plan.policy.saving_source == "cash_flow" and plan.policy.fallback.en.startswith("Neither")


def test_an_income_path_that_does_not_exist_is_refused():
    from lbsim.paths.household import PlanError  # noqa: PLC0415

    with pytest.raises(PlanError, match="does not exist"):
        stated(CASE, income_path="education")


# --- the section 5 budgets ---------------------------------------------------------------------------------

def test_the_budgets_on_a_forty_year_two_thousand_path_case():
    t0 = time.perf_counter()
    sheet, request, records, findings, plan = stated("lbsim-young", horizon=40)
    t_findings = time.perf_counter() - t0
    assert plan.horizon_years == 40
    t1 = time.perf_counter()
    p = build_paths(findings, plan, FULL, ACTIVE_SEED, n_paths=2000, seed=20260929)
    t_paths = time.perf_counter() - t1
    assert len(p.regimes) == 5 and len(p.regimes[0].bands["net_worth"].nominal.p50) == 41
    print(f"findings {t_findings:.2f} s, paths {t_paths:.2f} s (2000 paths x 40 years x 5 Regimes, monthly)")
    assert t_findings <= 5.0
    assert t_paths <= 20.0
