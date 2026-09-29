"""Under calibration 1.0.0 with the draft's market term, the port reproduces the draft's slow ``test_optim`` cases.

The draft's ``tests/test_optim.py`` makes three solves on its 45-year-old flagship (``sol_90`` at M = 14, and the
``tight`` / ``loose`` pair at M = 12). ``golden/optim/draft_test_optim.json`` holds what the draft itself returns
for them (built by ``golden/optim/build_draft_golden.py`` under the draft's own interpreter). Each case here is
held twice: to the golden figures (``u0``, the in-sample chance, the CVaR, the outcome, the costates), and to the
draft's own assertions, which are its tolerances.

Slow: about 30 s, 3 min and 30 s. ``pytest -m slow --dist loadfile -n 4`` keeps the module on one worker, so the
``sol_90`` fixture is solved once.
"""

from __future__ import annotations

import pytest

from optim_helpers import OPTIM_GOLDEN, SEED, load
from lbsim.model.params import Params
from lbsim.model.state import State
from lbsim.optim.problem import DRAFT_MARKET, solve_fi

pytestmark = pytest.mark.slow

GOLD = load(OPTIM_GOLDEN / "draft_test_optim.json")["cases"]
#: The port is the draft's arithmetic; on the machine the golden was built on the solves agree to the last bit.
#: The tolerance allows another BLAS or MUMPS build to reorder a sum.
REL, ABS = 1e-6, 1e-6


def _p() -> Params:
    """Calibration 1.0.0 is the draft's ``Params()`` as shipped, with the draft's market."""
    assert SEED.params == {} and SEED.behaviour.market == "draft"
    return Params(**SEED.params)


def _nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


def _solve(name: str):
    kw = dict(GOLD[name]["arguments"])
    return solve_fi(_nicolas_45(), params=_p(), market=DRAFT_MARKET, **kw)


def _assert_matches_golden(res, name: str) -> None:
    g = GOLD[name]
    for k, v in g["u0"].items():
        assert res.u0[k] == pytest.approx(v, rel=REL, abs=ABS), f"{name}: u0[{k}]"
    assert res.p_fi_insample == pytest.approx(g["p_fi_insample"], abs=1e-12), f"{name}: in-sample chance"
    assert res.cvar_shortfall == pytest.approx(g["cvar_shortfall"], rel=REL, abs=ABS)
    assert res.success == g["success"] and res.stats["outcome"] == g["outcome"]
    assert res.stats["return_status"] == g["return_status"] and res.stats["seed"] == g["seed"]
    for k, v in g["costates"].items():
        assert getattr(res.costates, k) == pytest.approx(v, rel=1e-5, abs=1e-9), f"{name}: {k}"
    assert res.exchange_rate.winner == g["exchange_rate"]["winner"]
    assert len(res.u_path) == len(g["u_path"])
    for k_step, (a, b) in enumerate(zip(res.u_path, g["u_path"])):
        for k, v in b.items():
            assert a[k] == pytest.approx(v, rel=1e-5, abs=1e-5), f"{name}: u_path[{k_step}][{k}]"


@pytest.fixture(scope="module")
def sol_90():
    return _solve("sol_90")


def test_sol_90_reproduces_the_draft(sol_90):
    _assert_matches_golden(sol_90, "sol_90")


# --- the draft's own assertions on sol_90 ---------------------------------------------------------------------

def test_solver_converges(sol_90):
    assert sol_90.success


def test_first_action_is_admissible(sol_90):
    u = sol_90.u0
    taus = [u["tau_Y"], u["tau_E"], u["tau_N"], u["tau_H"]]
    assert all(t >= -1e-6 for t in taus) and sum(taus) <= 1.0 + 1e-6
    assert all(u[k] >= -1e-6 for k in ("C", "m_E", "m_N", "p_A"))
    assert -1e-6 <= u["theta"] <= 1.0 + 1e-6


def test_the_cvar_bound_is_actually_met(sol_90):
    stats = sol_90.stats
    assert stats.get("cvar_constrained") is True
    bound = stats.get("cvar_bound")
    assert bound is not None
    assert sol_90.cvar_shortfall <= bound * (1.0 + 1e-6) + 1e-6


def test_costates_positive_and_health_is_scarce(sol_90):
    c = sol_90.costates
    assert c.lam_W > 0 and c.lam_E > 0 and c.lam_N > 0 and c.lam_H > 0
    assert c.lam_H > c.lam_E and c.lam_H > c.lam_N


def test_saturated_capitals_get_no_time(sol_90):
    assert sol_90.u0["tau_E"] < 0.05 and sol_90.u0["tau_N"] < 0.05


def test_overtime_beats_networking_for_nicolas(sol_90):
    xr = sol_90.exchange_rate
    assert xr.winner == "overtime" and xr.ratio > 1.0


def test_relaxing_confidence_raises_consumption():
    tight, loose = _solve("tight"), _solve("loose")
    _assert_matches_golden(tight, "tight")
    _assert_matches_golden(loose, "loose")
    assert tight.success and loose.success
    assert loose.u0["C"] > tight.u0["C"]
    assert loose.p_fi_insample <= tight.p_fi_insample
