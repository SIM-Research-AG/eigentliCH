"""Calibration 1.4.0 (DECISIONS P-21 to P-24): the paths' stated household retires as the findings assume.

Found on the live use-case refresh of 29.09.2026, where several designated goals had a chance of exactly 0.0: the
household drew on free wealth alone once work stopped (pillar 2 paid no annuity, pillar 3a was never paid out), a
stated stop age above 65 was dropped (the draft reads it only as an early exit), a stated salary paid the employer's
half of the pillar-2 contribution too, and a reached capital goal paid its amount out, so a second goal of the same
date was judged on what the first left. 1.3.0 and earlier keep the old household.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pytest

from stub import CASES, _rd, snapshot

from lbsim.calibration import ACTIVE_SEED, SEED_1_3
from lbsim.contracts import LbsRequest, LbsSheet
from lbsim.fast import gameplan as G
from lbsim.fast.build import build_findings
from lbsim.ids import sha256
from lbsim.model.params import Params
from lbsim.paths import engine as E
from lbsim.paths import reference as R
from lbsim.paths.household import stated_plan
from lbsim.paths.market import PathMarket

TOL = 1e-9
X0 = dict(W_L=230_000.0, W_R=980_000.0, D=276_000.0, E=1.0, N=0.8, H=0.85, age=63.5, W_res=980_000.0, W_hol=0.0,
          W_P=680_000.0, W_3a=175_000.0, kappa=96_000.0)


def _market(n, years, seed=5):
    rng = np.random.default_rng(seed)
    return PathMarket(states=np.zeros((n, years), int), log_return=rng.normal(0.04, 0.1, (n, years)),
                      log_inflation=rng.normal(0.01, 0.02, (n, years)),
                      property_growth=rng.normal(0.02, 0.08, (n, years)), z_market=np.zeros((n, years)))


def _run(**kw):
    years, n = 6, 5
    p = replace(Params(), pillar3a_contribution=7_258.0)
    ctl = np.tile([0.41, 0.0, 0.02, 0.2, 96_000.0, 0.0, 0.0, 0.0], (years * 12, 1))
    ctl[18:, 0] = 0.0
    income = np.where(np.arange(years * 12) < 18, 148_000.0, 0.0)
    h = E.Household(x0=X0, p=p, income=income, ahv_income=140_000.0, **kw)
    pm = _market(n, years)
    return h, ctl, pm, E.simulate(h, ctl, n_paths=n, market="allocation", path_market=pm)


def test_the_retirement_phase_is_the_reference_path_by_path():
    kw = dict(p2_cash_share=0.5, pension_at_age=65.0, annuity_rate=G.PILLAR2_CONVERSION_RATE)
    h, ctl, pm, res = _run(**kw)
    for i in range(res.n_paths):
        ref = R.simulate_path(X0, ctl, h.p, market="allocation",
                              path=R.PathInputs(pm.log_return[i], pm.log_inflation[i], pm.property_growth[i]),
                              income=h.income, ahv_income=h.ahv_income, **kw)
        for key in (*E.STATE_NAMES, "P"):
            a, b = np.asarray(ref[key]), res.states[key][:, i]
            assert np.max(np.abs(a - b) / np.maximum(1.0, np.abs(a))) <= TOL, key


def test_pillar_2_becomes_an_annuity_and_3a_is_paid_out():
    _, _, _, before = _run()
    _, _, _, after = _run(pension_at_age=65.0, annuity_rate=G.PILLAR2_CONVERSION_RATE)
    # Until the reference age (year 1 end, age 64.5) nothing differs; from 65 pillar 2 and 3a are gone ...
    for key in ("W_L", "W_P", "W_3a"):
        assert np.array_equal(before.states[key][1], after.states[key][1])
    assert np.all(after.states["W_P"][2:] == 0.0) and np.all(after.states["W_3a"][2:] == 0.0)
    assert np.all(before.states["W_P"][-1] > 600_000.0)
    # ... the 3a capital is in free wealth, and the annuity keeps it from draining.
    assert np.all(after.states["W_L"][-1] > before.states["W_L"][-1] + 175_000.0)


def test_a_stated_salary_pays_the_employees_half_of_the_pillar_2_contribution():
    h, ctl, _, _ = _run()
    x, u = dict(X0, age=45.0), dict(zip(E.CONTROL_NAMES, ctl[0]))
    full = R.derivatives(x, u, h.p, P=1.0, income=148_000.0, ahv_income=None)
    half = R.derivatives(x, u, h.p, P=1.0, income=148_000.0, ahv_income=None, p2_cash_share=0.5)
    contribution = h.p.pension_contribution_rate * 148_000.0 * 0.5 * (1.0 - np.tanh(45.0 - h.p.pension_age))
    assert half["net"] - full["net"] == pytest.approx(0.5 * contribution, rel=1e-12)
    assert half["W_P"] == full["W_P"]


def _case(name, **facts):
    raw = _rd(CASES / name / "sheet.json")
    request = copy.deepcopy(_rd(CASES / name / "request.json"))
    request["facts"].update(facts)
    sheet, req = LbsSheet.model_validate(raw), LbsRequest.model_validate(request)
    records = snapshot()["records"]
    return sheet, req, records


def _plan(name, cal, horizon=None, **facts):
    sheet, req, records = _case(name, **facts)
    f = build_findings(sheet, req, records, cal, sheet_sha256=sha256(sheet.model_dump(mode="json")))
    return stated_plan(sheet, req, records, cal, f, income_path=None, horizon_years=horizon, max_horizon_years=60,
                       reference_age=65.0)


def test_1_4_0_reads_the_stated_stop_age_and_retires_then():
    plan = _plan("lbsim-sample", ACTIVE_SEED, horizon=35, stop_work_age=68.0)
    assert plan.stop_age == 68.0 and plan.household.pension_at_age == 68.0
    assert plan.household.p2_cash_share == 0.5 and plan.household.annuity_rate == G.PILLAR2_CONVERSION_RATE
    age0 = plan.household.x0["age"]
    working = [m for m in range(len(plan.household.income)) if plan.household.income[m] > 0]
    assert age0 + (working[-1] + 1) / 12 == pytest.approx(68.0, abs=1 / 12)
    early = _plan("lbsim-sample", ACTIVE_SEED, stop_work_age=60.0)
    assert early.stop_age == 60.0 and early.household.pension_at_age == 65.0


def test_1_3_0_keeps_the_draft_household():
    plan = _plan("lbsim-sample", SEED_1_3, stop_work_age=68.0)
    assert plan.stop_age == 65.0 and plan.household.pension_at_age is None and plan.household.p2_cash_share == 1.0
    assert all(ev.execute for ev in plan.household.events)


def test_capital_goals_are_judged_not_paid_out():
    """Two goals of one date are each judged on the same wealth, as the findings' ledger and the optimiser judge
    them; only a home goal is carried out (it turns free wealth into property and a mortgage)."""
    plan = _plan("lbsim-early", ACTIVE_SEED)
    kinds = {ev.goal_id: (ev.kind, ev.execute) for ev in plan.household.events}
    assert kinds and all(execute == (kind == "home") for kind, execute in kinds.values())
    x0 = dict(X0, age=45.0)
    events = (E.GoalEvent("a", "capital", "drawable", 2, "real", 180_000.0, execute=False),
              E.GoalEvent("b", "capital", "drawable", 2, "real", 120_000.0, execute=False))
    ctl = np.tile([0.4, 0.0, 0.0, 0.2, 90_000.0, 0.0, 0.0, 0.0], (36, 1))
    res = E.simulate(E.Household(x0=x0, p=Params(), income=np.full(36, 120_000.0), ahv_income=120_000.0,
                                 events=events), ctl, n_paths=50, market="allocation", path_market=_market(50, 3))
    a, b = res.goals["a"], res.goals["b"]
    assert np.array_equal(a["value"], b["value"])
    assert np.all(b["reached"] >= a["reached"])
