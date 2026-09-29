"""Golden reconciliation (Engine Building Guide section 6.1).

Layer A: the eigentliCH PCP draft's own runs, frozen with their inputs in ``golden/draft``, reproduced by
the pure engine under calibration 1.0.0. Tolerance: weights 1e-9 absolute, objective 1e-12 relative
(measured: 2e-14 and 4e-16, scipy 1.18 against the draft's 1.14). The draft grouped each dimension's
ceilings before its floors; this build pairs them (PCP-10), which moves no weight beyond that tolerance.

Layer C: this build's production cases on the frozen live inputs, calibration 1.1.0, as validated on
28.09.2026. A regression reference.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pcp import engine
from pcp.calibration import DRAFT

from .golden_cases import CASES, GOLDEN, draft_cases, draft_problem, solve_case


@pytest.mark.parametrize("name", draft_cases())
def test_layer_a_reproduces_the_draft(name):
    problem, g = draft_problem(name)
    out = engine.optimise(problem, DRAFT, g["speed"])
    e = g["expected"]
    np.testing.assert_allclose(out.weights, e["weights"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(out.raw_weights, e["raw_weights"], rtol=0, atol=1e-9)
    assert out.objective == pytest.approx(e["objective"], rel=1e-12, abs=1e-15)
    assert out.budget_met == (e["conditions_met"] == "yes")
    np.testing.assert_allclose(out.achieved, e["achieved_curve"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(np.asarray(out.grid), e["portfolio_map"], rtol=0, atol=1e-9)
    for role, total in e["role_allocation"].items():
        assert out.by_role[role] == pytest.approx(total, abs=1e-9)
    ours = sorted(f"{b.dimension}:{b.category}:{'lower' if b.side == 'floor' else 'upper'}" for b in out.binding)
    theirs = sorted(x.replace("esg:portfolio:lower", "esg:portfolio:lower") for x in e["binding"])
    assert ours == theirs


def test_layer_a_covers_the_cases_named_in_the_build_report():
    assert {"fixture_balanced", "derived_onb-1981-sz", "derived_onb-2001-stgallen-20260826"} <= set(draft_cases())


@pytest.mark.parametrize("name", sorted(CASES))
def test_layer_c_production_regression(name):
    expected = json.loads((GOLDEN / "production" / f"{name}.json").read_text(encoding="utf-8"))
    out, date = solve_case(name)
    assert date == expected["date"]
    np.testing.assert_allclose(out.weights, expected["weights"], rtol=0, atol=1e-9)
    assert out.objective == pytest.approx(expected["objective"], rel=1e-12)
    assert sorted(f"{b.row}:{b.dimension}:{b.category}:{b.side}" for b in out.binding) == expected["binding"]
    assert out.budget_met and abs(out.raw_sum - 1.0) <= 1e-6
