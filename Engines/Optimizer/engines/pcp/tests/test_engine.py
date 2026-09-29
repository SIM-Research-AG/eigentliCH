"""Unit and property tests of the pure core (Engine Building Guide section 6.2)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from pcp import constraints as cons
from pcp import engine, objective as obj
from pcp.calibration import DRAFT, PRODUCTION
from pcp.contracts import DIMENSIONS, BudgetCheck

from .golden_cases import draft_problem, production_problem

floats = st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)


def _random_inputs(seed: int, n: int = 6):
    rng = np.random.default_rng(seed)
    bb = rng.normal(0.03, 0.08, size=(n, 25))
    c = rng.normal(0.02, 0.03, size=25)
    m = rng.dirichlet(np.ones(25))
    x = rng.dirichlet(np.ones(n))
    return bb, c, m, x


@given(st.integers(0, 10_000))
@settings(max_examples=60, deadline=None)
def test_objective_is_non_negative_and_zero_only_without_shortfall(seed):
    bb, c, m, x = _random_inputs(seed)
    y = obj.objective(x, bb, c, m)
    assert y >= 0.0
    assert (y == 0.0) == bool(np.all(obj.shortfall_by_state(x, bb, c, m) == 0.0))


@given(st.integers(0, 10_000))
@settings(max_examples=60, deadline=None)
def test_exact_gradient_matches_a_central_difference_away_from_kinks(seed):
    bb, c, m, x = _random_inputs(seed)
    gap = c[None, :] - m[None, :] * bb * x[:, None]
    h = 1e-7
    if np.min(np.abs(gap)) < 1e-4:          # too close to a kink for a finite difference to mean anything
        return
    g = obj.gradient(x, bb, c, m)
    fd = np.array([(obj.objective(x + h * e, bb, c, m) - obj.objective(x - h * e, bb, c, m)) / (2 * h)
                   for e in np.eye(len(x))])
    np.testing.assert_allclose(g, fd, rtol=1e-5, atol=1e-7)


def test_the_shortfall_is_summed_over_instruments_before_squaring():
    bb = np.zeros((2, 25)); c = np.full(25, 0.1); m = np.full(25, 1 / 25)
    # Two zero-return instruments: each state's summed shortfall is 2 * 0.1, squared.
    assert obj.objective(np.array([0.5, 0.5]), bb, c, m) == pytest.approx(25 * (2 * 0.1) ** 2)


def test_exceeding_the_target_costs_nothing():
    bb = np.full((1, 25), 10.0); c = np.full(25, 0.01); m = np.full(25, 1 / 25)
    assert obj.objective(np.array([1.0]), bb, c, m) == 0.0


def test_the_floor_is_the_objective_with_nothing_allocated():
    bb, c, m, _ = _random_inputs(1)
    assert obj.floor(bb, c, m) == pytest.approx(obj.objective(np.zeros(bb.shape[0]), bb, c, m))


def test_profile_scale_multiplies_the_profiles_inside_the_objective():
    bb, c, m, x = _random_inputs(2)
    assert obj.objective(x, bb, c, m, scale=100.0) == pytest.approx(obj.objective(x, bb * 100.0, c, m))


@pytest.mark.parametrize("name", ["balanced_global", "swiss_client_blend", "tight_single_position"])
def test_weights_sum_to_one_and_respect_every_bound(name):
    problem, _ = production_problem(name)
    out = engine.optimise(problem, PRODUCTION, "exact")
    system = engine.constraint_system(problem, PRODUCTION)
    assert out.weights.sum() == pytest.approx(1.0, abs=1e-12)
    assert np.all(out.raw_weights >= system.lower_bounds - 1e-9)
    assert np.all(out.raw_weights <= system.upper_bounds + 1e-9)
    assert np.all(system.a @ out.raw_weights <= system.b + 1e-7)


def test_the_run_is_deterministic():
    problem, _ = production_problem("balanced_global")
    a = engine.optimise(problem, PRODUCTION, "exact")
    b = engine.optimise(problem, PRODUCTION, "exact")
    assert np.array_equal(a.raw_weights, b.raw_weights) and a.objective == b.objective


def test_the_portfolio_map_sums_to_the_weights_and_roles_are_its_row_sums():
    problem, _ = production_problem("balanced_global")
    out = engine.optimise(problem, PRODUCTION, "exact")
    grid = np.asarray(out.grid)
    assert grid.shape == (4, 5) and grid.sum() == pytest.approx(1.0)
    for k, role in enumerate(PRODUCTION.vocabularies.role):
        assert out.by_role[role] == pytest.approx(grid[k].sum())


def test_the_budget_check_is_read_from_the_raw_sum():
    rounded = BudgetCheck(mode="rounded", decimals=1)
    absolute = BudgetCheck(mode="absolute", tolerance=1e-6)
    assert engine.budget_met(1.04, rounded) and not engine.budget_met(1.04, absolute)
    assert engine.budget_met(1.0 + 5e-7, absolute) and not engine.budget_met(1.0 + 5e-6, absolute)


def test_classification_maps_folds_and_refuses():
    attrs = [{"currency": "SEK", "region": "Global", "role": "gain", "capital_type": "Human",
              "liquidity": "Daily", "phase": "Maturing", "asset_class": "Real Estate",
              "home_scenario": "Crisis", "esg": 1.0}]
    labels, scen, esg, problems = engine.classify(attrs, ("X",), PRODUCTION)
    assert not problems
    assert (labels["currency"][0], labels["region"][0], labels["role"][0], labels["capital_type"][0],
            labels["phase"][0], labels["asset_class"][0]) == ("Others", "Others", "Gain", "Others",
                                                             "Build-up", "Real Assets")
    bad = [{**attrs[0], "liquidity": "Hourly", "phase": None}]
    _, _, _, problems = engine.classify(bad, ("X",), PRODUCTION)
    assert any("liquidity" in p for p in problems) and any("no phase" in p for p in problems)


@given(st.lists(st.floats(0.01, 1.0), min_size=2, max_size=5))
@settings(max_examples=30, deadline=None)
def test_a_blend_of_distributions_sums_to_one(raw):
    from .golden_cases import _inputs

    regime, _, _ = _inputs()
    codes = ["CH", "EU", "US", "DE", "GB"][:len(raw)]
    total = sum(raw)
    out = engine.blend_regime(regime, {c: w / total for c, w in zip(codes, raw)}, None)
    assert out.vector.sum() == pytest.approx(1.0, abs=1e-9) and np.all(out.vector >= 0)


def test_a_weighted_economy_that_is_not_assessed_is_refused_not_dropped():
    from .golden_cases import _inputs

    regime, _, _ = _inputs()
    with pytest.raises(engine.EngineError, match="does not assess"):
        engine.blend_regime(regime, {"IN": 0.5, "US": 0.5}, "2026-01")


def test_structural_infeasibility_is_found_before_solving():
    problem, _ = draft_problem("fixture_balanced")
    tight = engine.Problem(**{**problem.__dict__, "max_single_position": 0.1})   # 8 x 0.1 < 1
    with pytest.raises(engine.EngineError, match="ceilings sum"):
        engine.optimise(tight, DRAFT, "exact")


def test_the_layout_of_the_default_vocabulary():
    rows = cons.layout(PRODUCTION.vocabularies)
    cons.verify_layout(rows)
    assert [d for d in dict.fromkeys(r.dimension for r in rows)] == \
        ["currency", "region", "role", "capital_type", "liquidity", "esg", "phase", "asset_class"]
    assert set(DIMENSIONS) == {d for d in dict.fromkeys(r.dimension for r in rows)} - {"esg"}
