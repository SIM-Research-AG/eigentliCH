"""The parity targets of the vectorised Monte Carlo: the draft's per-path ``simulate``, one path at a time.

Two things live here, both scalar, both slow, both for tests and for nothing else:

* :func:`draft_simulate` is the draft's ``personal_alm/sim/montecarlo.py`` (``step``, ``simulate``, ``_clamp``)
  line for line on ``lbsim.model``. A test holds it to the draft's own output, frozen under the draft's
  interpreter (``dev/build_golden_mc.py``). It keeps the draft's two gaps exactly: its ``step`` integrates only
  ``W_L, W_R, D, E, N, H, age`` (``dW_res``, ``dW_hol``, ``dW_P``, ``dW_3a`` and ``dKappa`` are computed by
  ``drift`` and dropped), and ``HouseholdWealth.copy`` resets ``W_P`` and ``W_3a`` to zero after the first step
  (port note P-9a).
* :func:`simulate_path` is the step lbsim runs: the same Euler step of ``dynamics.drift`` with every derivative
  integrated, and the three switches of LBSIM-07 (market, prices, income) described in ``lbsim.paths.engine``.
  It is written on the draft's scalar functions (``earning_power``, ``ahv_pension``, ``pillar3a_flow``,
  ``child_costs``, ``income_tax``, ``wealth_tax``, the three time shapes, ``delta_H``, ``debt_gate``), so a test
  can hold its derivative to ``dynamics.drift`` itself at ``P = 1`` under the draft market, and the vectorised
  engine is held to it path by path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from ..model.controls import Control
from ..model.dynamics import (ahv_pension, child_costs, debt_gate, delta_H, diffusion, drift, earning_power,
                              income_tax, learning_effect, network_effect, pension_working_gate, pillar3a_flow,
                              rest_effect, wealth_tax)
from ..model.fiscal import DEFAULT_FISCAL, FiscalModel
from ..model.params import Params
from ..model.state import State
from .engine import GoalEvent, measure_values

ControlPolicy = Callable[[int, State], Control]


# --- the draft's sim/montecarlo.py, verbatim ------------------------------------------------------------

def constant_policy(u: Control) -> ControlPolicy:
    return lambda k, x: u


def _clamp(state: State, p: Params) -> None:
    w = state.wealth
    w.W_L = max(0.0, w.W_L)
    w.W_R = max(0.0, w.W_R)
    w.D = max(0.0, w.D)
    for person in state.persons:
        person.E.components = np.maximum(0.0, person.E.components)
        person.N = max(0.0, person.N)
        person.H = min(p.K_H, max(0.0, person.H))
        for v in person.ventures:
            v.maturity = min(1.0, max(0.0, v.maturity))


def draft_step(state: State, u: Control, p: Params, *, dt: float | None = None,
               rng: np.random.Generator | None = None, fiscal: FiscalModel = DEFAULT_FISCAL,
               regime: int = 0) -> State:
    p = p.at(regime)
    dt = p.dt if dt is None else dt
    f = drift(state, u, p, fiscal)
    nxt = state.copy()
    w, person = nxt.wealth, nxt.person
    w.W_L += f.dW_L * dt
    w.W_R += f.dW_R * dt
    w.D += f.dD * dt
    person.E.components = person.E.components + f.dE * dt
    person.N += f.dN * dt
    person.H += f.dH * dt
    person.age += f.dAge * dt
    for v, dm in zip(person.ventures, f.dMaturity):
        v.maturity += dm * dt
    if rng is not None:
        g = diffusion(state, u, p)
        sqrt_dt = np.sqrt(dt)
        z = rng.standard_normal(2)
        z_W = z[0]
        z_R = p.rho_WR * z[0] + np.sqrt(max(0.0, 1.0 - p.rho_WR**2)) * z[1]
        w.W_L += g.dW_L * sqrt_dt * z_W
        w.W_R += g.dW_R * sqrt_dt * z_R
    _clamp(nxt, p)
    return nxt


def draft_simulate(x0: State, policy: ControlPolicy, p: Params, n_steps: int, *, dt: float | None = None,
                   rng: np.random.Generator | None = None, fiscal: FiscalModel = DEFAULT_FISCAL,
                   regime: int = 0) -> list[State]:
    """The draft's ``simulate``; returns the states (the draft's ``Trajectory.states``)."""
    dt = p.dt if dt is None else dt
    states = [x0.copy()]
    x = x0
    for k in range(n_steps):
        u = policy(k, x)
        x = draft_step(x, u, p, dt=dt, rng=rng, fiscal=fiscal, regime=regime)
        states.append(x)
    return states


# --- the step lbsim runs, one path -----------------------------------------------------------------------

@dataclass(frozen=True)
class PathInputs:
    """One path's market, per simulated year (``None``: the draft market)."""

    log_return: Optional[np.ndarray] = None
    log_inflation: Optional[np.ndarray] = None
    property_growth: Optional[np.ndarray] = None


def derivatives(x: dict[str, float], u: dict[str, float], p: Params, *, P: float, income: Optional[float],
                ahv_income: Optional[float], p2_cash_share: float = 1.0, annuity: float = 0.0,
                pensioned: bool = False) -> dict[str, float]:
    """The derivative of every state at ``x`` (nominal money, real capitals), without the market terms.

    At ``P = 1``, ``income=None`` and with the draft's market terms added back, this is ``dynamics.drift``.
    """
    age = x["age"]
    ep = earning_power(x["E"], x["N"], age, p)
    if income is None:
        Y = ep * u["tau_Y"] * (x["H"] ** p.c) * P
        ahv = ahv_pension(ep, age, p) * P
    else:
        Y = income * P
        ahv = ahv_pension(ahv_income or 0.0, age, p) * P
    W_inv = max(0.0, x["W_R"] - x["W_res"] - x["W_hol"])
    asset_yield = p.y_R * W_inv + p.y_hol * x["W_hol"]
    interest = p.i * x["D"]
    contrib_3a = 0.0 if pensioned else pillar3a_flow(Y, age, p)
    gate_p2 = 0.0 if pensioned else pension_working_gate(age, p)
    contrib_p2 = p.pension_contribution_rate * Y * gate_p2
    Yp = (p.partner_income if p.has_partner else 0.0) * P
    kids = child_costs(age, p) * P
    raw = (Y + Yp + ahv + annuity + asset_yield - u["C"] * P - u["m_E"] * P - u["m_N"] * P - interest - u["p_A"]
           - contrib_3a - p2_cash_share * contrib_p2 - kids)
    taxable = max(0.0, Y + Yp + ahv + annuity + asset_yield - interest - contrib_3a)
    taxes = income_tax(taxable / P, p) * P + wealth_tax(x["W_L"] + x["W_R"] - x["D"], p)
    net = raw - taxes
    growth_E = p.alpha_E * learning_effect(u["tau_E"], p) + p.kappa_E * u["m_E"] + p.beta_E * x["E"]
    omega = (x["W_L"] + x["W_R"] - x["D"]) / P
    K_N = (p.N_0 + p.lambda_E * x["E"] + p.lambda_W * (omega / p.W_scale)
           + p.lambda_kappa * (x["kappa"] / (p.swr * p.W_scale)))
    growth_N = p.alpha_N * network_effect(u["tau_N"], p) + p.kappa_N * u["m_N"] + p.beta_N * x["N"]
    return {
        "net": net,
        "D": -u["p_A"] * debt_gate(x["D"]),
        "E": growth_E * (1.0 - x["E"] / p.K_E) - p.delta_E * x["E"],
        "N": growth_N * (1.0 - x["N"] / K_N) - p.delta_N * x["N"],
        "H": p.alpha_H * rest_effect(u["tau_H"], p) * (1.0 - x["H"] / p.K_H) - delta_H(u["tau_Y"], p) * x["H"],
        "kappa": p.alpha_kappa * (u["C"] - x["kappa"]),
        "W_P": p.pension_contribution_rate * Y * gate_p2 + p.pension_interest * x["W_P"],
        "W_3a": contrib_3a + p.pillar3a_interest * x["W_3a"],
    }


def simulate_path(x0: dict[str, float], controls: np.ndarray, p: Params, *, market: str,
                  path: PathInputs = PathInputs(), income: Optional[np.ndarray] = None,
                  ahv_income: Optional[float] = None, events: tuple[GoalEvent, ...] = (),
                  steps_per_year: int = 12, dt: Optional[float] = None, theta: float = 1.0,
                  p2_cash_share: float = 1.0, pension_at_age: Optional[float] = None, annuity_rate: float = 0.0
                  ) -> dict[str, list[float]]:
    """One path of :func:`lbsim.paths.engine.simulate`, scalar. Returns the year-end values of every state and
    ``P``, and for each goal its value in basis and whether it was reached (``goal:<id>``)."""
    dt = p.dt if dt is None else dt
    x = {k: float(v) for k, v in x0.items()}
    P = 1.0
    names = ("tau_Y", "tau_E", "tau_N", "tau_H", "C", "m_E", "m_N", "p_A")
    out: dict[str, list[float]] = {k: [x[k]] for k in x}
    out["P"] = [P]
    mu_P = p.r_f + theta * (p.mu_M - p.r_f)
    by_year: dict[int, list[GoalEvent]] = {}
    for ev in events:
        by_year.setdefault(ev.year, []).append(ev)

    def rec() -> None:
        for key in x:
            out[key].append(x[key])
        out["P"].append(P)

    annuity = 0.0
    retired = pension_at_age is None
    for m in range(len(controls)):
        if not retired and x["age"] >= pension_at_age - 1e-9:
            retired = True
            annuity = annuity_rate * x["W_P"]
            x["W_L"] = x["W_L"] + x["W_3a"]
            x["W_P"] = 0.0
            x["W_3a"] = 0.0
        u = dict(zip(names, (float(v) for v in controls[m])))
        k = m // steps_per_year
        d = derivatives(x, u, p, P=P, income=None if income is None else float(income[m]),
                        ahv_income=ahv_income, p2_cash_share=p2_cash_share, annuity=annuity,
                        pensioned=pension_at_age is not None and retired)
        if market == "allocation":
            W_L = x["W_L"] + d["net"] * dt + x["W_L"] * (math.exp(path.log_return[k] * dt) - 1.0)
            grow = math.exp(path.property_growth[k] * dt) - 1.0
            W_R = x["W_R"] + x["W_R"] * grow
            W_res = x["W_res"] + x["W_res"] * grow
            W_hol = x["W_hol"] + x["W_hol"] * grow
            nP = P * math.exp(path.log_inflation[k] * dt)
        else:
            W_L = x["W_L"] + (d["net"] + mu_P * x["W_L"]) * dt
            W_R = x["W_R"] + p.mu_R * x["W_R"] * dt
            W_res = x["W_res"] + p.mu_R * x["W_res"] * dt
            W_hol = x["W_hol"] + p.mu_R * x["W_hol"] * dt
            nP = P
        x = {"W_L": max(0.0, W_L), "W_R": max(0.0, W_R), "D": max(0.0, x["D"] + d["D"] * dt),
             "E": max(0.0, x["E"] + d["E"] * dt), "N": max(0.0, x["N"] + d["N"] * dt),
             "H": min(p.K_H, max(0.0, x["H"] + d["H"] * dt)), "age": x["age"] + 1.0 * dt,
             "W_res": W_res, "W_hol": W_hol, "W_P": x["W_P"] + d["W_P"] * dt,
             "W_3a": x["W_3a"] + d["W_3a"] * dt, "kappa": x["kappa"] + d["kappa"] * dt}
        P = nP
        if (m + 1) % steps_per_year == 0:
            year = (m + 1) // steps_per_year
            rec()
            for ev in by_year.get(year, ()):
                arr = {key: np.array([v]) for key, v in x.items()}
                value = float(measure_values(arr, ev.measure, p)[0])
                in_basis = value / P if ev.basis == "real" else value
                reached = in_basis >= ev.target
                out.setdefault(f"goal:{ev.goal_id}", []).extend([in_basis, float(reached)])
                if ev.execute and reached:
                    if ev.kind == "home":
                        price = ev.price * P if ev.basis == "real" else ev.price
                        deposit = ev.deposit_share * price
                        from_l = min(deposit, x["W_L"])
                        rest = deposit - from_l
                        from_3a = min(rest, x["W_3a"])
                        rest -= from_3a
                        from_p = min(rest, p.pension_deposit_share * x["W_P"])
                        x["W_L"] -= from_l
                        x["W_3a"] -= from_3a
                        x["W_P"] -= from_p
                        x["W_R"] += price
                        x["W_res"] += price
                        x["D"] += price - deposit
                    elif ev.kind == "capital":
                        amount = ev.target * P if ev.basis == "real" else ev.target
                        x["W_L"] = max(0.0, x["W_L"] - amount)
    return out
