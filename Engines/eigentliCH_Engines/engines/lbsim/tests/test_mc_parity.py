"""Parity of the vectorised Monte Carlo (spec 9.B): the draft's per-path ``simulate``, path by path, to 1e-9.

The chain, each link a test:

1. ``reference.draft_simulate`` (the draft's ``sim/montecarlo.py`` verbatim on ``lbsim.model``) reproduces the
   draft's own output, frozen under the draft's interpreter, at sigma = 0 and with the draft's seeded shocks.
2. ``reference.derivatives`` is ``dynamics.drift`` at ``P = 1`` (every derivative, random states and controls).
3. The vectorised engine equals the draft's ``simulate`` on every path at sigma = 0 and under the same shocks.
4. The vectorised engine equals ``reference.simulate_path`` path by path on fixed state paths under the allocation
   market, with inflation, in both income modes, with the goal events.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from conftest import GOLDEN, load_json

from lbsim.model.controls import Control
from lbsim.model.dynamics import drift
from lbsim.model.params import Params
from lbsim.model.state import State
from lbsim.paths import engine as E
from lbsim.paths import reference as R
from lbsim.paths.market import PathMarket

GOLD = load_json(GOLDEN / "mc" / "draft_simulate.json")
CASES = sorted(GOLD["cases"])
TOL = 1e-9


def _case(name):
    c = GOLD["cases"][name]
    params = {k: (tuple(v) if isinstance(v, list) else v) for k, v in c["params"].items()}
    return c, replace(Params(), **params)


def _close(a, b, what):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    err = np.abs(a - b) / np.maximum(1.0, np.abs(a))
    assert float(np.max(err)) <= TOL, f"{what}: max relative difference {float(np.max(err)):.3e}"


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("mode", ["deterministic", "stochastic"])
def test_the_verbatim_port_is_the_drafts_simulate(name, mode):
    c, p = _case(name)
    x0 = State.individual(**c["state"])
    rng = np.random.default_rng(c["seed"]) if mode == "stochastic" else None
    states = R.draft_simulate(x0, R.constant_policy(Control(**c["control"])), p, c["n_steps"], rng=rng)
    for field in GOLD["fields"]:
        ours = [getattr(s.wealth, field) if hasattr(s.wealth, field) else
                (float(s.person.E.aggregate()) if field == "E" else getattr(s.person, field)) for s in states]
        _close([row[field] for row in c[mode]], ours, f"{name}/{mode}/{field}")


def _x0(c):
    s = dict(c["state"])
    return {"W_L": s["W_L"], "W_R": s["W_R"], "D": s["D"], "E": s["E"], "N": s["N"], "H": s["H"], "age": s["age"],
            "W_res": s.get("W_res", s["W_R"]), "W_hol": 0.0, "W_P": s["W_P"], "W_3a": s["W_3a"],
            "kappa": s["kappa"]}


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("mode", ["deterministic", "stochastic"])
def test_the_vectorised_engine_is_the_drafts_simulate_path_by_path(name, mode):
    """sigma = 0 (the draft's ``rng=None``) and the draft's own seeded shocks, fed to every path."""
    c, p = _case(name)
    n = 4
    u = c["control"]
    ctl = np.tile([u[k] for k in E.CONTROL_NAMES], (c["n_steps"], 1))
    noise = None
    if mode == "stochastic":
        z = np.asarray(c["shocks"])
        noise = np.repeat(z[:, None, :], n, axis=1)
    res = E.simulate(E.Household(x0=_x0(c), p=p), ctl, n_paths=n, market="draft", noise=noise,
                     theta=u["theta"])
    for field in ("W_L", "W_R", "D", "E", "N", "H", "age"):
        expected = [row[field] for row in c[mode]][::12]
        for i in range(n):
            _close(expected, res.states[field][:, i], f"{name}/{mode}/{field}/path {i}")


def test_the_reference_derivative_is_the_drafts_drift():
    rng = np.random.default_rng(7)
    base = replace(Params(), has_partner=True, partner_income=55_000.0, tax_split_factor=2.0, child_ages=(4.0, 9.0),
                   child_reference_age=40.0, pillar3a_contribution=6_000.0, i=0.021)
    for _ in range(200):
        x = {"W_L": rng.uniform(0, 2e6), "W_R": rng.uniform(0, 3e6), "D": rng.uniform(0, 1.5e6),
             "E": rng.uniform(0.05, 3), "N": rng.uniform(0.05, 2), "H": rng.uniform(0.1, 1), "age": rng.uniform(25, 80),
             "W_hol": 0.0, "W_P": rng.uniform(0, 1e6), "W_3a": rng.uniform(0, 2e5), "kappa": rng.uniform(2e4, 2e5)}
        x["W_res"] = x["W_R"] * rng.uniform(0.3, 1.0)
        u = {"tau_Y": rng.uniform(0, 0.7), "tau_E": rng.uniform(0, 0.2), "tau_N": rng.uniform(0, 0.2),
             "tau_H": rng.uniform(0.05, 0.3), "C": rng.uniform(3e4, 2e5), "m_E": rng.uniform(0, 5e3),
             "m_N": rng.uniform(0, 5e3), "p_A": rng.uniform(0, 2e4)}
        theta = rng.uniform(0, 1)
        state = State.individual(W_L=x["W_L"], W_R=x["W_R"], D=x["D"], E=x["E"], N=x["N"], H=x["H"], age=x["age"],
                                 kappa=x["kappa"], W_res=x["W_res"], W_hol=0.0, W_P=x["W_P"], W_3a=x["W_3a"])
        f = drift(state, Control(**u, theta=theta), base)
        d = R.derivatives(x, u, base, P=1.0, income=None, ahv_income=None)
        mu_P = base.r_f + theta * (base.mu_M - base.r_f)
        for ours, theirs in ((d["net"] + mu_P * x["W_L"], f.dW_L), (d["D"], f.dD), (d["E"], float(f.dE[0])),
                             (d["N"], f.dN), (d["H"], f.dH), (d["kappa"], f.dKappa), (d["W_P"], f.dW_P),
                             (d["W_3a"], f.dW_3a)):
            assert abs(ours - theirs) <= TOL * max(1.0, abs(theirs)), (ours, theirs)
        assert abs(base.mu_R * x["W_res"] - f.dW_res) <= TOL * max(1.0, abs(f.dW_res))


def _market(n, years, seed):
    rng = np.random.default_rng(seed)
    return PathMarket(states=rng.integers(0, 25, (n, years)), log_return=rng.normal(0.04, 0.12, (n, years)),
                      log_inflation=rng.normal(0.012, 0.03, (n, years)),
                      property_growth=rng.normal(0.03, 0.08, (n, years)), z_market=np.zeros((n, years)))


HOUSEHOLD = dict(W_L=180_000.0, W_R=900_000.0, D=620_000.0, E=0.9, N=0.7, H=0.85, age=36.0, W_res=900_000.0,
                 W_hol=0.0, W_P=140_000.0, W_3a=35_000.0, kappa=95_000.0)
EVENTS = (E.GoalEvent("home", "home", "deposit_eligible", 4, "real", 150_000.0, price=750_000.0, deposit_share=0.2),
          E.GoalEvent("cap", "capital", "drawable", 7, "nominal", 40_000.0),
          E.GoalEvent("ret", "retirement", "retirement_capital", 12, "real", 600_000.0))


@pytest.mark.parametrize("income_mode", ["model", "stated"])
def test_the_vectorised_engine_is_the_reference_on_fixed_state_paths(income_mode):
    """The allocation market with inflation: every state, the price level and every goal outcome, path by path."""
    p = replace(Params(), has_partner=True, partner_income=60_000.0, child_ages=(2.0,), child_reference_age=36.0,
                pillar3a_contribution=7_000.0, i=0.019)
    years, n = 12, 7
    pm = _market(n, years, 3)
    ctl = np.tile([0.42, 0.02, 0.03, 0.2, 95_000.0, 1_000.0, 500.0, 8_000.0], (years * 12, 1))
    ctl[60:, 0] = 0.3
    income = np.linspace(110_000.0, 150_000.0, years * 12) if income_mode == "stated" else None
    ahv = 120_000.0 if income_mode == "stated" else None
    h = E.Household(x0=HOUSEHOLD, p=p, income=income, ahv_income=ahv, events=EVENTS)
    res = E.simulate(h, ctl, n_paths=n, market="allocation", path_market=pm)
    for i in range(n):
        ref = R.simulate_path(HOUSEHOLD, ctl, p, market="allocation",
                              path=R.PathInputs(pm.log_return[i], pm.log_inflation[i], pm.property_growth[i]),
                              income=income, ahv_income=ahv, events=EVENTS)
        for key in (*E.STATE_NAMES, "P"):
            _close(ref[key], res.states[key][:, i], f"{income_mode}/{key}/path {i}")
        for ev in EVENTS:
            value, reached = ref[f"goal:{ev.goal_id}"]
            _close([value], [res.goals[ev.goal_id]["value"][i]], f"{ev.goal_id} value path {i}")
            assert bool(reached) == bool(res.goals[ev.goal_id]["reached"][i])


def test_sigma_zero_gives_identical_paths():
    """One state, no property noise: every path is the same path, and it is the reference's."""
    p = Params()
    years, n = 8, 5
    pm = _market(1, years, 11)
    same = PathMarket(states=np.repeat(pm.states, n, 0), log_return=np.repeat(pm.log_return, n, 0),
                      log_inflation=np.repeat(pm.log_inflation, n, 0),
                      property_growth=np.repeat(pm.property_growth, n, 0), z_market=np.zeros((n, years)))
    ctl = np.tile([0.4, 0.0, 0.02, 0.2, 80_000.0, 0.0, 0.0, 0.0], (years * 12, 1))
    res = E.simulate(E.Household(x0=HOUSEHOLD, p=p), ctl, n_paths=n, market="allocation", path_market=same)
    ref = R.simulate_path(HOUSEHOLD, ctl, p, market="allocation",
                          path=R.PathInputs(pm.log_return[0], pm.log_inflation[0], pm.property_growth[0]))
    for key in E.STATE_NAMES:
        assert np.all(res.states[key] == res.states[key][:, :1])
        _close(ref[key], res.states[key][:, 0], key)


def test_at_unit_prices_the_allocation_step_is_the_draft_step_with_the_market_swapped():
    """Zero inflation and zero property growth: the allocation market differs from the draft's only in the market
    term, ``W_L (exp(r dt) - 1)`` for ``mu_P W_L dt``; with ``r`` = ln(1 + mu_P dt)/dt the two coincide."""
    p = replace(Params(), mu_R=0.0)
    years, n = 5, 2
    mu_P = p.r_f + (p.mu_M - p.r_f)
    r = math.log1p(mu_P * p.dt) / p.dt
    pm = PathMarket(states=np.zeros((n, years), int), log_return=np.full((n, years), r),
                    log_inflation=np.zeros((n, years)), property_growth=np.zeros((n, years)),
                    z_market=np.zeros((n, years)))
    ctl = np.tile([0.42, 0.02, 0.03, 0.2, 90_000.0, 1_000.0, 500.0, 5_000.0], (years * 12, 1))
    h = E.Household(x0=HOUSEHOLD, p=p)
    a = E.simulate(h, ctl, n_paths=n, market="allocation", path_market=pm)
    b = E.simulate(h, ctl, n_paths=n, market="draft")
    for key in E.STATE_NAMES:
        _close(b.states[key], a.states[key], key)
