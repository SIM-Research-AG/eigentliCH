"""The vectorised Monte Carlo: the draft's Euler step of ``lbsim.model.dynamics``, over every path at once.

One step is the draft's ``sim.montecarlo.step`` (``x += f(x, u) dt``, then the clamps), with every derivative of
``dynamics.drift`` integrated, the twelve states of the symbolic model (``W_L, W_R, D, E, N, H, age, W_res, W_hol,
W_P, W_3a, kappa``), and three changes that are lbsim's (LBSIM-07), each a switch:

* **The market.** ``market="allocation"``: the liquid wealth earns ``W_L * (exp(r_s dt) - 1)`` with ``r_s`` the
  Allocation's per-state log return of the year's drawn state (theta fixed at 1); property grows at the property
  model's nominal log rate. ``market="draft"``: the draft's ``mu_P(theta) W_L`` and ``mu_R W_R`` (the parity mode).
* **Prices.** Under the allocation market every path carries its own price level ``P`` (``exp`` of the drawn
  states' log inflation). Everything is nominal: wages, spending, child costs, the partner's income and the AHV
  rise with ``P`` (pass-through 1.0); debt, amortisation, a fixed pillar-3a payment and the pillar credits are
  nominal; the income tax tariff is indexed (``P * tax(taxable / P)``). Expertise, network and health are real;
  the network ceiling reads real net worth, and the habit ``kappa`` is kept in today's francs. At ``P = 1`` every
  one of these is the draft's expression exactly.
* **Income.** ``income=None`` (the optimiser): labour income is the model's, ``earning_power(E, N, age) tau_Y
  H^c``. Otherwise (the stated plan): ``income`` is the findings' income path, gross in today's francs for each
  monthly step, and the AHV is taken on that path's own averaged income (``ahv_income``), as the fast half does.

Vectorised over paths; the age, the gates and the controls are the same on every path and are Python floats.
``lbsim.paths.reference`` is the same arithmetic one path at a time, built on the draft's scalar functions, and
the parity tests hold the two together path by path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

from ..model.dynamics import (_AHV_GATE_SCALE, _DEBT_GATE_SCALE, _PENSION_GATE_SCALE, _SMOOTH_MIN_EPS,
                              _ahv_individual, age_factor, ahv_pension, child_costs, delta_H, learning_effect,
                              network_effect, rest_effect)
from ..model.params import Params
from .market import PathMarket

STATE_NAMES: tuple[str, ...] = ("W_L", "W_R", "D", "E", "N", "H", "age", "W_res", "W_hol", "W_P", "W_3a", "kappa")
#: The draft's controls less theta (LBSIM-16). ``C``, ``m_E``, ``m_N`` in today's francs a year; ``p_A`` nominal.
CONTROL_NAMES: tuple[str, ...] = ("tau_Y", "tau_E", "tau_N", "tau_H", "C", "m_E", "m_N", "p_A")
MEASURES: tuple[str, ...] = ("net_worth", "drawable", "deposit_eligible", "retirement_capital")
MarketKind = Literal["draft", "allocation"]


@dataclass(frozen=True)
class GoalEvent:
    """A goal judged at a year end: its measure against its target in its own basis (LBSIM-09).

    ``execute``: a reached home goal buys the home (the deposit paid from free wealth, then pillar 3a, then the
    permitted share of pillar 2; the rest becomes mortgage debt); a reached capital goal pays its lump sum out of
    free wealth. A retirement goal is only judged.
    """

    goal_id: str
    kind: Literal["home", "retirement", "capital"]
    measure: Literal["drawable", "deposit_eligible", "retirement_capital"]
    year: int
    basis: Literal["real", "nominal"]
    #: In the goal's basis: today's francs for ``real``, francs of the date for ``nominal``.
    target: float
    execute: bool = True
    #: A home goal: the price in the goal's basis, and the deposit's share of it.
    price: Optional[float] = None
    deposit_share: Optional[float] = None


@dataclass(frozen=True)
class Household:
    x0: dict[str, float]
    p: Params
    #: The stated plan: gross labour income in today's francs per monthly step. ``None``: the model's income.
    income: Optional[np.ndarray] = None
    #: The stated plan: the averaged own income the AHV is computed on, today's francs.
    ahv_income: Optional[float] = None
    events: tuple[GoalEvent, ...] = ()

    def __post_init__(self) -> None:
        missing = [k for k in STATE_NAMES if k not in self.x0]
        if missing:
            raise ValueError(f"the initial state lacks {missing}")


@dataclass
class Result:
    """Year-end values, ``(years + 1, n_paths)`` per state and ``P``; the goal outcomes."""

    years: int
    n_paths: int
    states: dict[str, np.ndarray]
    goals: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)

    def measure(self, name: str) -> np.ndarray:
        return measure_values(self.states, name, self._p)

    _p: Optional[Params] = None


def measure_values(s: dict[str, np.ndarray], name: str, p: Params) -> np.ndarray:
    """A goal measure (or net worth) from the states, nominal."""
    if name == "net_worth":
        return s["W_L"] + s["W_R"] + s["W_P"] + s["W_3a"] - s["D"]
    if name == "deposit_eligible":
        return s["W_L"] + s["W_3a"] + p.pension_deposit_share * s["W_P"]
    if name == "retirement_capital":
        # Pillar 2 is not counted: the retirement target is the gap left after its annuity (P-3).
        return s["W_L"] + s["W_3a"]
    if name == "drawable":
        return drawable(s["W_L"], s["W_R"], s["D"], s["W_res"], s["W_hol"], p)
    raise KeyError(name)


def drawable(W_L, W_R, D, W_res, W_hol, p: Params):
    """``HouseholdWealth.drawable`` with the Params haircuts, vectorised (all three ship at 0: only ``W_L``)."""
    W_R = np.asarray(W_R, dtype=float)
    safe = np.where(W_R > 0.0, W_R, 1.0)
    W_inv = np.maximum(0.0, W_R - W_res - W_hol)
    pos = (W_L + p.q_inv * (W_inv - D * W_inv / safe) + p.q_hol * (W_hol - D * W_hol / safe)
           + p.h_res * (W_res - D * W_res / safe))
    return np.where(W_R > 0.0, pos, W_L - p.h_res * D)


def _smooth_min(a, b, eps: float = _SMOOTH_MIN_EPS):
    d = a - b
    return 0.5 * (a + b - np.sqrt(d * d + eps * eps))


def earning_power_v(E, N, age: float, p: Params):
    skill = p.earning_power_at_unit * (np.maximum(E, 0.0) ** p.a) * (np.maximum(N, 0.0) ** p.b)
    raw = p.earning_power_min * (p.earning_power_max / p.earning_power_min) ** np.minimum(1.0, skill)
    return np.minimum(p.earning_power_max, np.maximum(p.earning_power_min, raw * age_factor(age, p)))


def ahv_v(average_income, age: float, p: Params):
    """``dynamics.ahv_pension`` on an array of averaged incomes."""
    share = np.minimum(1.0, np.maximum(0.0, average_income) / max(p.ahv_income_for_max, 1.0))
    full = p.ahv_full_single * max(0.0, min(1.0, p.ahv_record_share))
    gate = 0.5 * (1.0 + math.tanh((age - (p.ahv_age - 0.5)) / _AHV_GATE_SCALE))
    own = full * (0.5 + 0.5 * share) * gate
    if not p.has_partner:
        return own
    partner = _ahv_individual(p.partner_income, age + p.partner_age_offset, p.partner_ahv_record_share, p)
    return _smooth_min(own + partner, p.ahv_couple_cap_multiple * p.ahv_full_single)


def income_tax_v(taxable, p: Params):
    t = np.maximum(0.0, taxable)
    f = max(1.0, p.tax_split_factor)
    return f * (p.tax_rate_max * (t / f) * (1.0 - np.exp(-(t / f) / p.tax_income_scale)))


def simulate(h: Household, controls: np.ndarray, *, n_paths: int, market: MarketKind,
             path_market: Optional[PathMarket] = None, noise: Optional[np.ndarray] = None,
             steps_per_year: int = 12, dt: Optional[float] = None, theta: float = 1.0) -> Result:
    """Integrate ``len(controls)`` monthly steps over ``n_paths`` paths.

    ``controls``: ``(n_steps, 8)`` in :data:`CONTROL_NAMES` order, the same on every path. ``market="allocation"``
    reads ``path_market`` (its year ``k`` covers steps ``12 k .. 12 k + 11``); ``market="draft"`` optionally reads
    ``noise`` ``(n_steps, n_paths, 2)`` (the draft's correlated shocks; ``None`` is the draft's ``rng=None``) and
    the draft's tilt ``theta`` (the allocation market fixes it at 1, LBSIM-07).
    """
    p = h.p
    controls = np.asarray(controls, dtype=float)
    n_steps = controls.shape[0]
    dt = p.dt if dt is None else dt
    if n_steps % steps_per_year:
        raise ValueError("the controls cover whole years only")
    years = n_steps // steps_per_year
    if market == "allocation":
        if path_market is None or path_market.log_return.shape[1] < years:
            raise ValueError("the allocation market needs a path market covering every year")
    if h.income is not None and len(h.income) < n_steps:
        raise ValueError("the stated income covers fewer steps than the controls")

    x = {k: np.full(n_paths, float(h.x0[k])) for k in STATE_NAMES if k != "age"}
    age = float(h.x0["age"])
    P = np.ones(n_paths)
    rec = {k: np.empty((years + 1, n_paths)) for k in (*STATE_NAMES, "P")}

    def record(k: int) -> None:
        for name, arr in x.items():
            rec[name][k] = arr
        rec["age"][k] = age
        rec["P"][k] = P

    record(0)
    events = {}
    for ev in h.events:
        events.setdefault(ev.year, []).append(ev)
    goals: dict[str, dict[str, np.ndarray]] = {}
    intended_3a = min(p.pillar3a_contribution, p.pillar3a_cap)
    f_tax = max(1.0, p.tax_split_factor)
    lam_habit = p.lambda_kappa / (p.swr * p.W_scale)
    rate_p2 = p.pension_contribution_rate
    Yp_real = p.partner_income if p.has_partner else 0.0
    mu_P = p.r_f + theta * (p.mu_M - p.r_f)        # dynamics.mu_P and sigma_P (only the draft market reads them)
    sig_P = theta * p.sigma_M
    ahv_path = h.ahv_income

    for m in range(n_steps):
        tau_Y, tau_E, tau_N, tau_H, C, m_E, m_N, p_A = (float(v) for v in controls[m])
        k = m // steps_per_year
        W_L, W_R, D, E, N, H = x["W_L"], x["W_R"], x["D"], x["E"], x["N"], x["H"]
        W_res, W_hol, W_P, W_3a, kappa = x["W_res"], x["W_hol"], x["W_P"], x["W_3a"], x["kappa"]

        # -- the cash flow (dynamics.net_cash_to_liquid), nominal
        if h.income is None:
            epw = earning_power_v(E, N, age, p)
            Y = epw * tau_Y * (H ** p.c) * P
            ahv = ahv_v(epw, age, p) * P
        else:
            Y = float(h.income[m]) * P
            ahv = ahv_pension(ahv_path or 0.0, age, p) * P
        W_inv = np.maximum(0.0, W_R - W_res - W_hol)
        asset_yield = p.y_R * W_inv + p.y_hol * W_hol
        interest = p.i * D
        gate_3a = 0.5 * (1.0 - math.tanh((age - p.pillar3a_age) / _PENSION_GATE_SCALE))
        contrib_3a = np.minimum(intended_3a, np.maximum(0.0, Y)) * gate_3a
        gate_p2 = 0.5 * (1.0 - math.tanh((age - p.pension_age) / _PENSION_GATE_SCALE))
        contrib_p2 = rate_p2 * Y * gate_p2
        Yp = Yp_real * P
        kids = child_costs(age, p) * P
        raw = (Y + Yp + ahv + asset_yield - C * P - m_E * P - m_N * P - interest - p_A - contrib_3a
               - contrib_p2 - kids)
        taxable = np.maximum(0.0, Y + Yp + ahv + asset_yield - interest - contrib_3a)
        t_real = taxable / P / f_tax
        income_tax = P * (f_tax * (p.tax_rate_max * t_real * (1.0 - np.exp(-t_real / p.tax_income_scale))))
        wealth_tax = p.wealth_tax_rate * np.maximum(0.0, W_L + W_R - D)
        net = raw - income_tax - wealth_tax

        # -- the capitals and the habit (real)
        growth_E = p.alpha_E * learning_effect(tau_E, p) + p.kappa_E * m_E + p.beta_E * E
        dE = growth_E * (1.0 - E / p.K_E) - p.delta_E * E
        omega = (W_L + W_R - D) / P
        K_N = p.N_0 + p.lambda_E * E + p.lambda_W * (omega / p.W_scale) + lam_habit * kappa
        growth_N = p.alpha_N * network_effect(tau_N, p) + p.kappa_N * m_N + p.beta_N * N
        dN = growth_N * (1.0 - N / K_N) - p.delta_N * N
        dH = p.alpha_H * rest_effect(tau_H, p) * (1.0 - H / p.K_H) - delta_H(tau_Y, p) * H
        dKappa = p.alpha_kappa * (C - kappa)
        dW_P = rate_p2 * Y * gate_p2 + p.pension_interest * W_P
        dW_3a = contrib_3a + p.pillar3a_interest * W_3a
        dD = -p_A * np.tanh(np.maximum(D, 0.0) / _DEBT_GATE_SCALE)

        # -- the step
        if market == "allocation":
            r = path_market.log_return[:, k]
            g = path_market.property_growth[:, k]
            nW_L = W_L + net * dt + W_L * (np.exp(r * dt) - 1.0)
            grow = np.exp(g * dt) - 1.0
            nW_R, nW_res, nW_hol = W_R + W_R * grow, W_res + W_res * grow, W_hol + W_hol * grow
            nP = P * np.exp(path_market.log_inflation[:, k] * dt)
        else:
            nW_L = W_L + (net + mu_P * W_L) * dt
            nW_R = W_R + p.mu_R * W_R * dt
            nW_res = W_res + p.mu_R * W_res * dt
            nW_hol = W_hol + p.mu_R * W_hol * dt
            nP = P
            if noise is not None:
                sq = math.sqrt(dt)
                z_W = noise[m, :, 0]
                z_R = p.rho_WR * z_W + math.sqrt(max(0.0, 1.0 - p.rho_WR ** 2)) * noise[m, :, 1]
                nW_L = nW_L + sig_P * W_L * sq * z_W
                nW_R = nW_R + p.sigma_R * W_R * sq * z_R
        x["W_L"] = np.maximum(0.0, nW_L)
        x["W_R"] = np.maximum(0.0, nW_R)
        x["D"] = np.maximum(0.0, D + dD * dt)
        x["E"] = np.maximum(0.0, E + dE * dt)
        x["N"] = np.maximum(0.0, N + dN * dt)
        x["H"] = np.minimum(p.K_H, np.maximum(0.0, H + dH * dt))
        x["W_res"] = nW_res
        x["W_hol"] = nW_hol
        x["W_P"] = W_P + dW_P * dt
        x["W_3a"] = W_3a + dW_3a * dt
        x["kappa"] = kappa + dKappa * dt
        age = age + 1.0 * dt
        P = nP

        if (m + 1) % steps_per_year == 0:
            year = (m + 1) // steps_per_year
            # The year end is recorded BEFORE any goal of that date is carried out: the band at a goal's date is
            # the value its chance is judged on, not what is left after the deposit or the lump sum is paid.
            record(year)
            for ev in events.get(year, ()):
                goals[ev.goal_id] = _judge(ev, x, P, p)
    res = Result(years=years, n_paths=n_paths, states=rec, goals=goals)
    res._p = p
    return res


def _judge(ev: GoalEvent, x: dict[str, np.ndarray], P: np.ndarray, p: Params) -> dict[str, np.ndarray]:
    """Judge a goal at its year end in its own basis, then, where reached, carry it out (in place)."""
    value = measure_values(x, ev.measure, p)
    in_basis = value / P if ev.basis == "real" else value
    reached = in_basis >= ev.target
    out = {"value": in_basis, "reached": reached, "shortfall": np.maximum(0.0, ev.target - in_basis)}
    if not ev.execute:
        return out
    if ev.kind == "home" and ev.price is not None and ev.deposit_share is not None:
        price = ev.price * P if ev.basis == "real" else np.full_like(P, ev.price)
        deposit = ev.deposit_share * price
        rest = np.where(reached, deposit, 0.0)
        from_l = np.minimum(rest, x["W_L"])
        rest = rest - from_l
        from_3a = np.minimum(rest, x["W_3a"])
        rest = rest - from_3a
        from_p = np.minimum(rest, p.pension_deposit_share * x["W_P"])
        x["W_L"] = x["W_L"] - from_l
        x["W_3a"] = x["W_3a"] - from_3a
        x["W_P"] = x["W_P"] - from_p
        bought = np.where(reached, price, 0.0)
        x["W_R"] = x["W_R"] + bought
        x["W_res"] = x["W_res"] + bought
        x["D"] = x["D"] + np.where(reached, price - deposit, 0.0)
    elif ev.kind == "capital":
        amount = ev.target * P if ev.basis == "real" else np.full_like(P, ev.target)
        x["W_L"] = np.where(reached, np.maximum(0.0, x["W_L"] - amount), x["W_L"])
    return out
