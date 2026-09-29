"""The System Build Manual's acceptance tests for the Portfolio Optimiser, numbered as the Manual numbers
them (section 15.7), plus the layout checks of Step 25 and the bound-source rule of section 14.2.

Knowing departures are asserted, with the reason in DECISIONS.md:

* test 3 compares the ReturnSet's ``regime_id`` with the requested Regime, not with a ``DerivedMandate``'s
  (the engine page's contracts win, Build Instruction section 1; PCP-11);
* test 6 is on the ``Allocation``, which the engine page publishes in place of the Manual's
  ``Recommendation``.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
from pydantic import ValidationError

from pcp import constraints as cons
from pcp import objective as obj
from pcp.calibration import PRODUCTION
from pcp.contracts import Allocation, Mandate

from .conftest import run_body, stamped_return_set


# ---------------------------------------------------------------------------
# Step 25: the block is exactly 75 rows, row 57 the only one-sided row, each dimension at its index.
# ---------------------------------------------------------------------------

def test_manual_step25_exactly_75_rows():
    assert len(cons.layout(PRODUCTION.vocabularies)) == 75


def test_manual_step25_row_57_is_the_only_one_sided_row():
    rows = cons.layout(PRODUCTION.vocabularies)
    assert [r.row for r in rows if r.dimension == "esg"] == [57]
    assert all(sum(1 for q in rows if (q.dimension, q.category) == (r.dimension, r.category)) == 2
               for r in rows if r.dimension != "esg")


def test_manual_step25_each_dimension_begins_at_its_stated_index():
    rows = cons.layout(PRODUCTION.vocabularies)
    starts = {}
    for r in rows:
        starts.setdefault(r.dimension, r.row)
    assert starts == {"currency": 1, "region": 21, "role": 35, "capital_type": 43, "liquidity": 49,
                      "esg": 57, "phase": 58, "asset_class": 66}


# ---------------------------------------------------------------------------
# Section 15.7
# ---------------------------------------------------------------------------

def test_manual_15_7_1_a_permuted_constraint_block_fails_rather_than_producing_a_portfolio(monkeypatch):
    from .golden_cases import production_problem
    from pcp import engine

    problem, _ = production_problem("balanced_global")
    permuted = ("region", "currency", "role", "capital_type", "liquidity", "phase", "asset_class")
    monkeypatch.setattr(cons, "DIMENSIONS", permuted)
    with pytest.raises(cons.LayoutError):
        engine.optimise(problem, PRODUCTION, "exact")
    rows = list(cons.layout(PRODUCTION.vocabularies))
    swapped = rows[:]
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(cons.LayoutError):
        cons.verify_layout([r.model_copy(update={"row": k + 1}) for k, r in enumerate(swapped)])


def test_manual_15_7_2_a_finite_difference_across_a_kink_disagrees_with_the_exact_gradient():
    """At a kink the exact (sub)gradient treats the term as inactive; a central difference straddling it
    averages both sides. The disagreement is asserted, so nobody swaps in a numerical gradient."""
    bb = np.array([[1.0] * 25]); m = np.full(25, 1.0); c = np.full(25, 0.5)
    x = np.array([0.5])                       # exactly on the kink: c - m * x * bb == 0 in every state
    exact = obj.gradient(x, bb, c, m)[0]
    h = 1e-6
    fd = (obj.objective(x + h, bb, c, m) - obj.objective(x - h, bb, c, m)) / (2 * h)
    assert exact == 0.0                       # inactive side: no shortfall, no slope
    assert fd < exact                         # the left side's slope pulls the average below it
    assert fd != pytest.approx(exact, abs=1e-9)


def test_manual_15_7_3_a_return_set_with_another_regime_id_is_rejected(settings, mandate):
    from .conftest import _client

    with _client(settings, stamped_return_set("RGM-0000000000000000")) as c:
        r = c.post("/run", json=run_body(mandate())).json()
        assert r["status"] == "failed" and r["artefact_id"] is None
        error = c.get(f"/runs/{r['run_id']}").json()["error"]
        assert "RGM-0000000000000000" in error and "refused" in error
        v = c.post("/validate", json=run_body(mandate())).json()
        assert v["ok"] is False and "regime_id" in v["problems"][0]


def test_manual_15_7_3_an_unstamped_return_set_is_rejected_too(unstamped_client, mandate):
    """Strict (owner, 28.09.2026, PCP-11): a ReturnSet with no regime_id is refused like a wrong one."""
    r = unstamped_client.post("/run", json=run_body(mandate(name="unstamped"))).json()
    assert r["status"] == "failed"
    assert "has not stamped" in unstamped_client.get(f"/runs/{r['run_id']}").json()["error"]


def test_manual_15_7_4_an_infeasible_mandate_is_reported_as_infeasible(client, mandate):
    body = mandate(name="infeasible", max_single_position=0.01)       # 54 x 0.01 < 1
    v = client.post("/validate", json=run_body(body)).json()
    assert v["ok"] is False and any("ceilings sum" in p for p in v["problems"])
    r = client.post("/run", json=run_body(body)).json()
    assert r["status"] == "failed" and r["artefact_id"] is None
    assert "infeasible" in client.get(f"/runs/{r['run_id']}").json()["error"]


def test_manual_15_7_4_the_budget_is_read_from_the_raw_weights_before_renormalising():
    from pcp import engine
    from pcp.contracts import BudgetCheck

    # Raw weights summing to 1.04 renormalise to one; the check reads 1.04 and says no.
    assert not engine.budget_met(1.04, BudgetCheck(mode="absolute", tolerance=1e-6))
    assert PRODUCTION.budget_check.mode == "absolute"


@pytest.mark.parametrize("dimension,wrong", [("region", "derived"), ("asset_class", "derived"),
                                             ("role", "policy"), ("currency", "policy")])
def test_manual_15_7_5_a_mislabelled_bound_source_is_refused_in_both_directions(mandate, dimension, wrong):
    body = mandate(bounds={dimension: {}}, bound_sources={dimension: wrong})
    with pytest.raises(ValidationError, match="mislabelled bound source"):
        Mandate.model_validate(body)


def test_manual_14_2_a_bounded_dimension_must_name_its_source(mandate):
    with pytest.raises(ValidationError, match="name no source"):
        Mandate.model_validate(mandate(bound_sources={"role": "derived"}))   # currency bounded, unlabelled


def test_manual_15_7_6_a_constructed_attempt_to_release_raises(client, mandate):
    r = client.post("/run", json=run_body(mandate(name="release"))).json()
    assert r["status"] == "succeeded"
    payload = client.get(f"/allocation/{r['artefact_id']}").json()
    assert payload["release_state"] == "unreleased"
    released = copy.deepcopy(payload)
    released["release_state"] = "released"
    with pytest.raises(ValidationError, match="unreleased"):
        Allocation.model_validate(released)
