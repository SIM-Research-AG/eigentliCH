"""The failed solves of 29.09.2026 (PCP-21), from anonymised fixtures (``tests/fixtures/convergence.json``).

Every one of the 18 failed runs (11 distinct mandates) was infeasible as stated: a bucket floor above what
its instruments can hold under ``max_single_position``, or rows of different dimensions in conflict. The
per-dimension checks passed them, so the solver was left to fail with "Inequality constraints incompatible"
or "Positive directional derivative". They are now refused before any solve, naming the rows. On a feasible
but tight block the calibrated fast solve can still leave the raw weights off the budget; the engine-level
rescue then restarts from the phase-1 point with the exact settings.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pcp import constraints as cons
from pcp import engine
from pcp.calibration import DRAFT, PRODUCTION
from pcp.solver import solve

from .conftest import instruments, run_body
from .golden_cases import draft_cases, draft_problem, production_problem

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "convergence.json").read_text(encoding="utf-8"))


def _problem(d: dict) -> engine.Problem:
    return engine.Problem(
        ids=tuple(d["ids"]), labels={k: tuple(v) for k, v in d["labels"].items()},
        home_scenarios=tuple(d["home_scenarios"]), esg=tuple(d["esg"]), profiles=np.asarray(d["profiles"]),
        target=np.asarray(d["target"]), regime=np.asarray(d["regime"]),
        bounds={k: {c: tuple(v) for c, v in b.items()} for k, b in d["bounds"].items()},
        esg_min=d["esg_min"], max_single_position=d["max_single_position"], fixed=tuple(d["fixed"]))


INFEASIBLE = {c["case"]: _problem(c["problem"]) for c in FIXTURES["infeasible"]}
TIGHT = {c["case"]: (_problem(c["problem"]), c["calibrated_fails"]) for c in FIXTURES["tight"]}

#: What each refusal must name.
NAMED = {
    "income-focus": "role floor of 0.1714 on Gain, but the universe's 1 Gain instrument can hold at most 0.1500",
    "growth-chf": "currency floor of 0.5000 on CHF, but the universe's 3 CHF instruments can hold at most 0.4500",
    "growth-usd-equity-floor": "asset_class Equity floor 0.5500 (row 70) misses by 0.0327",
    "swiss-home-bias-gain-ceiling": "role Gain ceiling 0.2929 (row 36) misses by 0.0071",
    "balanced-chf-equity-floor": "asset_class Equity floor 0.3000 (row 70) misses by 0.0071",
}


def test_the_fixtures_hold_every_failed_mandate():
    assert len(INFEASIBLE) == 11 and len(TIGHT) >= 1
    assert all(any(case.startswith(k) for k in NAMED) for case in INFEASIBLE)


@pytest.mark.parametrize("case", sorted(INFEASIBLE))
def test_a_failed_mandate_is_refused_before_solving_naming_the_rows(case):
    problem = INFEASIBLE[case]
    expected = next(v for k, v in NAMED.items() if case.startswith(k))
    problems = engine.constraint_system(problem, PRODUCTION).feasibility_problems()
    assert any(expected in p for p in problems), problems
    with pytest.raises(engine.EngineError, match="infeasible as stated"):
        engine.optimise(problem, PRODUCTION, "fast")


@pytest.mark.parametrize("case", sorted(TIGHT))
def test_a_tight_feasible_mandate_is_rescued_when_the_calibrated_solve_does_not_settle(case):
    problem, fails = TIGHT[case]
    system = engine.constraint_system(problem, PRODUCTION)
    assert system.feasibility_problems() == []
    for speed in fails:
        first = solve(problem.profiles, problem.target, problem.regime, system, PRODUCTION.solver, speed)
        assert not engine.acceptable(first, system, PRODUCTION.budget_check)
        out = engine.optimise(problem, PRODUCTION, speed)
        assert out.solve.success and out.budget_met and abs(out.raw_sum - 1.0) <= 1e-6
        assert cons.max_violation(out.raw_weights, system) <= cons.FEASIBILITY_TOL
        assert out.solve.method == "SLSQP" and any("PCP-21" in n for n in out.notes)
        exact = engine.optimise(problem, PRODUCTION, "exact")
        assert out.objective <= exact.objective * (1 + 1e-6)


@pytest.mark.parametrize("name", draft_cases())
def test_the_rescue_never_engages_on_golden_layer_a(name):
    problem, g = draft_problem(name)
    system = engine.constraint_system(problem, DRAFT)
    first = solve(problem.profiles, problem.target, problem.regime, system, DRAFT.solver, g["speed"])
    assert engine.acceptable(first, system, DRAFT.budget_check)


@pytest.mark.parametrize("name", ["balanced_global", "swiss_client_blend", "tight_single_position"])
def test_the_phase_one_point_is_feasible_and_the_dropped_rows_are_implied(name):
    problem, _ = production_problem(name)
    system = engine.constraint_system(problem, PRODUCTION)
    p1 = cons.phase_one(system)
    assert p1.feasible and p1.margin > 0 and cons.max_violation(p1.point, system) <= 1e-9
    a, b = system.reduced()
    assert 0 < a.shape[0] < system.n_rows
    # A dropped row holds on the whole budget simplex (x >= 0, sum one): its largest coefficient is within b.
    kept = {tuple(r) + (v,) for r, v in zip(a.tolist(), b.tolist())}
    dropped = [i for i in range(system.n_rows) if tuple(system.a[i].tolist()) + (system.b[i],) not in kept]
    assert dropped and all(float(system.a[i].max()) <= system.b[i] + 1e-15 for i in dropped)


def test_validate_names_a_bucket_floor_its_instruments_cannot_hold(client, mandate):
    by_role: dict[str, list[str]] = {}
    for i in instruments():
        by_role.setdefault(str(i["role"]).lower(), []).append(i["instrument_id"])
    universe = sorted(by_role["gain"][:1] + by_role["income"][:4] + by_role["stabilisation"][:4]
                      + by_role["protection"][:4])
    body = mandate(universe=universe, max_single_position=0.15,
                   bounds={"role": {"Gain": {"lower": 0.2, "upper": 0.6}}}, bound_sources={"role": "derived"})
    report = client.post("/validate", json=run_body(body)).json()
    assert not report["ok"]
    assert any("role floor of 0.2000 on Gain" in p and "1 Gain instrument" in p for p in report["problems"])
