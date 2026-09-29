"""The market adapter for the NLP (LBSIM-07), the goal measures, and the numpy twin of the adapted step. No casadi.

**The NLP runs in today's francs.** Wages and spending pass inflation through at 1.0 (the calibration's
``market.wage_pass_through`` and ``spending_pass_through``; the NLP refuses any other value), so the draft's income
law, consumption, habit, taxes (the tariff is indexed, LBSIM-08) and AHV are real quantities and the draft's
drift is used unchanged. What inflation does to the rest is applied per scenario and step, with that scenario's own
drawn inflation:

    liquid wealth   W_L  <- W_L * exp((r_s - pi_s) dt)            the portfolio's per-state log return, deflated
    real assets     W_R, W_res, W_hol  <- * exp(g - pi_s dt)       g the property's nominal log growth over the step
    debt, pillars   D, W_P, W_3a  <- * exp(-pi_s dt)               nominal stocks lose real value (the drift keeps
                                                                    the nominal interest and the credited rates)

and a goal in the francs of its date is compared, per scenario, with that scenario's price level at the goal
(LBSIM-09). The draft's own market (``mu_M``, ``sigma_M``, the tilt ``theta``, ``mu_R``, ``sigma_R``) is taken out
of the drift by zeroing ``mu_M``, ``r_f`` and ``mu_R``; theta is fixed at 1 and keeps its slot.

Each simulated year draws one state from that year's distribution (``MarketInputs.state_distribution``), so the
two half-year steps of a year share it. Property: nominal log growth ``ln 1.03 + 0.8 (pi_s - ln 1.01)`` a year,
less ``sigma^2 / 2``, plus ``sigma sqrt(dt) z`` with ``z = rho z_mkt + sqrt(1 - rho^2) eps``, where ``z_mkt`` is the
normal quantile of the drawn state's mid-position in that year's distribution (the reading of
``dev/build_samples.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from statistics import NormalDist
from typing import Sequence

import numpy as np

from ..contracts import PropertyParameters
from ..model import dynamics as dyn
from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from .types import MarketInputs

#: Goal measures, as weights on the state's stocks (``W_L``, ``W_P``, ``W_3a``). ``drawable`` is liquid wealth,
#: the fast half's ``liquid``; ``deposit_eligible`` counts pillar 3a in full and half of pillar 2 (the paths
#: sample's reading of the WEF withdrawal); ``retirement_capital`` counts all three.
MEASURES: dict[str, dict[str, float]] = {
    "drawable": {"W_L": 1.0, "W_P": 0.0, "W_3a": 0.0},
    "deposit_eligible": {"W_L": 1.0, "W_P": 0.5, "W_3a": 1.0},
    "retirement_capital": {"W_L": 1.0, "W_P": 1.0, "W_3a": 1.0},
}

N_STATES = 25
_NORMAL = NormalDist()


def no_market_params(p: Params) -> Params:
    """``p`` with the draft's market taken out of the drift: no portfolio return, no property appreciation."""
    return replace(p, mu_M=0.0, r_f=0.0, mu_R=0.0)


@dataclass(frozen=True)
class AllocationScenarios:
    """Per scenario ``m`` and step ``k``: the portfolio's log return a year ``r``, the log inflation over the step
    ``infl`` (a rate times dt), the property's nominal log growth over the step ``growth``; per node the price
    level ``level[m, k]`` (``level[:, 0] = 1``) and the drawn state per step ``state``."""

    r: np.ndarray
    infl: np.ndarray
    growth: np.ndarray
    level: np.ndarray
    state: np.ndarray


def year_distribution(market: MarketInputs, year_index: int) -> np.ndarray:
    dists = market.state_distribution
    if not dists:
        raise ValueError("the allocation market needs a state distribution per simulated year")
    d = np.asarray(dists[min(year_index, len(dists) - 1)], dtype=float)
    if d.shape != (N_STATES,) or np.any(d < 0) or d.sum() <= 0:
        raise ValueError("a year's state distribution must be 25 non-negative probabilities")
    return d / d.sum()


def sample_allocation(market: MarketInputs, prop: PropertyParameters, dts: Sequence[float], M: int,
                      seed: int) -> AllocationScenarios:
    """The NLP's in-sample scenarios. One ``default_rng(seed)``: first the state uniforms (M x years), then the
    property noise (M x K). The seed is recorded by the caller."""
    r_s = np.asarray(market.log_returns, dtype=float)
    pi_s = np.asarray(market.log_inflation, dtype=float)
    if r_s.shape != (N_STATES,) or pi_s.shape != (N_STATES,):
        raise ValueError("the allocation market needs 25 per-state log returns and 25 per-state log inflations")
    K = len(dts)
    times = np.concatenate([[0.0], np.cumsum(dts)])
    years = [int(math.floor(t + 1e-9)) for t in times[:-1]]
    n_years = max(years) + 1
    rng = np.random.default_rng(seed)
    u = rng.random((M, n_years))
    eps = rng.standard_normal((M, K))
    state_y = np.zeros((M, n_years), dtype=int)
    z_mkt_y = np.zeros((M, n_years))
    for y in range(n_years):
        d = year_distribution(market, y)
        cdf = np.cumsum(d)
        s = np.minimum(np.searchsorted(cdf, u[:, y], side="right"), N_STATES - 1)
        state_y[:, y] = s
        mid = np.clip(cdf[s] - d[s] / 2.0, 1e-6, 1.0 - 1e-6)
        z_mkt_y[:, y] = [_NORMAL.inv_cdf(float(q)) for q in mid]
    st = np.stack([state_y[:, y] for y in years], axis=1)
    zm = np.stack([z_mkt_y[:, y] for y in years], axis=1)
    dt = np.asarray(dts, dtype=float)[None, :]
    r = r_s[st]
    infl = pi_s[st] * dt
    rho = float(prop.rho_with_market)
    z = rho * zm + math.sqrt(max(0.0, 1.0 - rho * rho)) * eps
    growth = ((prop.nominal_log_growth + prop.inflation_beta * (pi_s[st] - prop.inflation_anchor_log)
               - 0.5 * prop.sigma ** 2) * dt + prop.sigma * np.sqrt(dt) * z)
    level = np.ones((M, K + 1))
    level[:, 1:] = np.exp(np.cumsum(infl, axis=1))
    return AllocationScenarios(r=r, infl=infl, growth=growth, level=level, state=st)


# --- the numpy twin of ``symbolic.allocation_step`` (the parity target) -------------------------------------

def state_vector(x: State, p: Params) -> np.ndarray:
    """The NLP's state vector, in ``symbolic``'s order."""
    return np.array([x.wealth.W_L, x.wealth.W_R, x.wealth.D, x.person.E.aggregate(), x.person.N, x.person.H,
                     x.person.age, float(x.wealth.W_res or 0.0), x.wealth.W_hol, x.wealth.W_P, x.wealth.W_3a,
                     dyn.habit_of(x, p)], dtype=float)


def state_from_vector(v: Sequence[float]) -> State:
    v = [float(a) for a in v]
    return State.individual(W_L=v[0], W_R=v[1], D=v[2], E=v[3], N=v[4], H=v[5], age=v[6], W_res=v[7],
                            W_hol=v[8], W_P=v[9], W_3a=v[10], kappa=v[11])


def numpy_drift(x: State, u: Control, p: Params) -> np.ndarray:
    f = dyn.drift(x, u, p)
    return np.array([f.dW_L, f.dW_R, f.dD, f.dE[0], f.dN, f.dH, f.dAge, f.dW_res, f.dW_hol, f.dW_P, f.dW_3a,
                     f.dKappa], dtype=float)


def numpy_allocation_step(x: State, u: Control, p: Params, dt: float, *, r: float, infl: float,
                          growth: float) -> np.ndarray:
    """One adapted step on ``lbsim.model``: the draft's drift without its market, then the per-state terms."""
    v = state_vector(x, p)
    out = v + numpy_drift(x, u, no_market_params(p)) * dt
    out[0] += v[0] * (math.exp((r * dt) - infl) - 1.0)
    real_growth = math.exp(growth - infl) - 1.0
    for i in (1, 7, 8):
        out[i] += v[i] * real_growth
    erosion = math.exp(-infl) - 1.0
    for i in (2, 9, 10):
        out[i] += v[i] * erosion
    return out


def numpy_euler_step(x: State, u: Control, p: Params, dt: float, z: Sequence[float] = (0.0, 0.0)) -> np.ndarray:
    """The draft's Euler-Maruyama step on ``lbsim.model`` (``symbolic.euler_step``'s twin)."""
    v = state_vector(x, p)
    g = dyn.diffusion(x, u, p)
    out = v + numpy_drift(x, u, p) * dt
    out[0] += g.dW_L * math.sqrt(dt) * z[0]
    out[1] += g.dW_R * math.sqrt(dt) * z[1]
    return out


def measure_value(v: Sequence[float], measure: str) -> float:
    w = MEASURES[measure]
    return w["W_L"] * v[0] + w["W_P"] * v[9] + w["W_3a"] * v[10]
