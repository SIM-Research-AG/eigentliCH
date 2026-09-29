"""Nicolas backtest fixture (spec §15).

A realised trajectory through the state space, age 19 → 45, used to validate the
dynamics. We run the deterministic system forward with the epoch control history
(§15.1) and the two leverage/founding events, and check it reproduces the three
hard observables (§15.2):

  1. equity-funded property purchase at ~26  (W_L covers the price at 26);
  2. CHF ~2M leverage taken on at 36          (D ≈ 2M just after the event);
  3. property valuation > CHF 5M by 45        (W_R exceeds 5M).

The parameters below (venture scales, purchase/renovation values) are the
*calibration* choices this backtest pins down — the structural defaults in
Params are illustrative, and reproducing the observables is what disciplines
them (spec §11, §15.2). Values are chosen to land within the tolerance bands
while staying faithful to the biography, not fitted beyond that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..model.controls import Control
from ..model.params import Params
from ..model.state import State
from ..model.venture import Venture
from ..sim.montecarlo import step

AGE_START = 19.0
AGE_END = 45.0
DT = 1.0 / 12.0

# --- Calibration constants (the biography, as numbers) ---------------------------
P_HOME = 1.30e6        # Rigi Maison purchase price at 26 (equity-funded)   [CHF]
RENO_CAPEX = 2.50e6    # renovation capex added to W_R at 36                [CHF]
MORTGAGE_36 = 2.00e6   # the CHF 2M leverage event at 36                    [CHF]

TRADING = Venture(name="trading-system", scale=1.08e6, a_v=0.70, ramp=0.90, maturity=0.05)
SIM_RESEARCH = Venture(name="sim-research", scale=2.60e5, a_v=0.60, ramp=0.60, maturity=0.05)


def initial_state() -> State:
    """Age 19: a strong student, little capital, high health (spec §15.1)."""
    return State.individual(W_L=1.0e4, W_R=0.0, D=0.0, E=0.15, N=0.10, H=0.95)


# --- Epoch control history (spec §15.1) ------------------------------------------
# Each epoch is (age_from, Control). Times τ sum to ≤ 1; the slack is leisure.
def _c(tau_Y, tau_E, tau_N, tau_H, C, m_E, m_N, p_A, theta) -> Control:
    return Control(tau_Y=tau_Y, tau_E=tau_E, tau_N=tau_N, tau_H=tau_H,
                   C=C, m_E=m_E, m_N=m_N, p_A=p_A, theta=theta)


EPOCHS: list[tuple[float, Control]] = [
    # ETH, hardest track, ~60% side work building the trading system.
    (19.0, _c(0.60, 0.30, 0.00, 0.10, C=15_000, m_E=2_000, m_N=0, p_A=0, theta=0.70)),
    # Trading system runs; θ high (the system is the risky engine).
    (24.0, _c(0.50, 0.20, 0.20, 0.10, C=25_000, m_E=2_000, m_N=2_000, p_A=0, theta=0.70)),
    # Post-purchase; property is asset and network/seminar hub.
    (26.0, _c(0.50, 0.20, 0.20, 0.10, C=40_000, m_E=3_000, m_N=5_000, p_A=0, theta=0.55)),
    # Founds SIM Research; keeps part-time education role (E- and N-builder).
    (29.0, _c(0.45, 0.15, 0.25, 0.15, C=60_000, m_E=4_000, m_N=10_000, p_A=0, theta=0.45)),
    # Board seats, mandates; high N deployed; some amortisation.
    (36.0, _c(0.40, 0.10, 0.30, 0.20, C=90_000, m_E=5_000, m_N=15_000, p_A=50_000, theta=0.35)),
]


def control_at(age: float) -> Control:
    chosen = EPOCHS[0][1]
    for age_from, ctrl in EPOCHS:
        if age >= age_from - 1e-9:
            chosen = ctrl
    return chosen


# --- Events (discrete jumps, spec §7.1 / §15.1) ----------------------------------
def _found_trading(state: State) -> None:
    state.person.ventures.append(TRADING.copy())


def _buy_home(state: State) -> None:
    """Equity-funded purchase: W_L → W_R, no debt (the leverage comes at 36)."""
    state.wealth.W_L -= P_HOME
    state.wealth.W_R += P_HOME


def _found_sim(state: State) -> None:
    state.person.ventures.append(SIM_RESEARCH.copy())


def _leverage_and_renovate(state: State) -> None:
    """CHF 2M mortgage; renovation capex lifts W_R (part debt, part liquid)."""
    state.wealth.D += MORTGAGE_36
    state.wealth.W_R += RENO_CAPEX
    state.wealth.W_L -= (RENO_CAPEX - MORTGAGE_36)  # equity share of the capex


EVENTS: list[tuple[float, Callable[[State], None]]] = [
    (20.0, _found_trading),
    (26.0, _buy_home),
    (29.0, _found_sim),
    (36.0, _leverage_and_renovate),
]


@dataclass
class Backtest:
    states: list[State]
    ages: np.ndarray

    def at_age(self, age: float) -> State:
        idx = int(round((age - AGE_START) / DT))
        idx = max(0, min(idx, len(self.states) - 1))
        return self.states[idx]


def run(p: Params | None = None) -> Backtest:
    """Deterministic forward run with epoch controls and events (spec §16.4 step 2/3)."""
    p = p or Params()
    x = initial_state()
    n_steps = int(round((AGE_END - AGE_START) / DT))
    states = [x.copy()]
    fired = [False] * len(EVENTS)
    for k in range(n_steps):
        age = AGE_START + k * DT
        # Fire any event whose age has been reached (once).
        for j, (ev_age, fn) in enumerate(EVENTS):
            if not fired[j] and age >= ev_age - 1e-9:
                fn(x)
                fired[j] = True
        u = control_at(age)
        x = step(x, u, p, dt=DT)
        states.append(x)
    ages = AGE_START + np.arange(n_steps + 1) * DT
    return Backtest(states=states, ages=ages)


# --- Observables & tolerance bands (spec §15.2) ----------------------------------
@dataclass
class Observable:
    name: str
    value: float
    target: str
    ok: bool


def observables(bt: Backtest) -> list[Observable]:
    at26 = bt.at_age(26.0)
    # W_L just BEFORE the purchase must cover the price (equity-funded).
    just_before_26 = bt.at_age(26.0 - DT)
    at36_after = bt.at_age(36.0 + DT)
    at45 = bt.at_age(45.0)

    wl_pre = just_before_26.wealth.W_L
    d36 = at36_after.wealth.D
    wr45 = at45.wealth.W_R

    return [
        Observable("equity-funded purchase @26",
                   wl_pre, f"W_L ≥ {P_HOME:,.0f} before purchase",
                   wl_pre >= P_HOME),
        Observable("CHF ~2M leverage @36",
                   d36, "D ∈ [1.7M, 2.3M] after event",
                   1.7e6 <= d36 <= 2.3e6),
        Observable("valuation > CHF 5M @45",
                   wr45, "W_R > 5.0M", wr45 > 5.0e6),
    ]
