"""Euler–Maruyama integration (spec §5, §10.1).

    x_{k+1} = x_k + f(x_k,u_k)·Δt + g(x_k,u_k)·√Δt·Z_k ,   Z_k ~ N(0, Σ_B)

Deterministic skeleton (spec §16.4 step 1): pass rng=None → the noise term
vanishes and this is a plain forward Euler integration. States are clamped to
their floors after each step (E, N, H ≥ 0; H ≤ K_H; D ≥ 0; W_L, W_R ≥ 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..model.controls import Control
from ..model.dynamics import diffusion, drift
from ..model.fiscal import DEFAULT_FISCAL, FiscalModel
from ..model.params import Params
from ..model.state import State

# A control policy maps (step index, state) → Control. A constant control is the
# common case for the deterministic skeleton and the backtest epochs.
ControlPolicy = Callable[[int, State], Control]


def constant_policy(u: Control) -> ControlPolicy:
    return lambda k, x: u


def _clamp(state: State, p: Params) -> None:
    """Project the state back onto its admissible ranges (spec §5, §16.3)."""
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


def step(
    state: State,
    u: Control,
    p: Params,
    *,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
    fiscal: FiscalModel = DEFAULT_FISCAL,
    regime: int = 0,
) -> State:
    """Advance one period. rng=None ⇒ deterministic (σ contribution suppressed)."""
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
    # Age advances through the same derivative mechanism as everything else, so a caller cannot forget it and a
    # coarser `dt` cannot desynchronise it from the rest of the state. `dAge` is 1.0 in the drift and 0.0 in the
    # diffusion. Added 3 August 2026; nothing reads it yet (PLAN_2026-08.md §0B step 1).
    person.age += f.dAge * dt
    for v, dm in zip(person.ventures, f.dMaturity):
        v.maturity += dm * dt

    if rng is not None:
        g = diffusion(state, u, p)
        # Correlated Brownian increments for the two wealth shocks (Q4:
        # ρ(dB_W, dB_R) = rho_WR); other capitals carry no noise yet.
        sqrt_dt = np.sqrt(dt)
        z = rng.standard_normal(2)
        z_W = z[0]
        z_R = p.rho_WR * z[0] + np.sqrt(max(0.0, 1.0 - p.rho_WR**2)) * z[1]
        w.W_L += g.dW_L * sqrt_dt * z_W
        w.W_R += g.dW_R * sqrt_dt * z_R

    _clamp(nxt, p)
    return nxt


@dataclass
class Trajectory:
    """A realised path: states at each step plus the time grid."""

    states: list[State]
    times: np.ndarray

    @property
    def final(self) -> State:
        return self.states[-1]


def simulate(
    x0: State,
    policy: ControlPolicy,
    p: Params,
    n_steps: int,
    *,
    dt: float | None = None,
    rng: np.random.Generator | None = None,
    fiscal: FiscalModel = DEFAULT_FISCAL,
    regime: int = 0,
) -> Trajectory:
    """Integrate the system forward n_steps. Deterministic when rng is None."""
    dt = p.dt if dt is None else dt
    states = [x0.copy()]
    x = x0
    for k in range(n_steps):
        u = policy(k, x)
        x = step(x, u, p, dt=dt, rng=rng, fiscal=fiscal, regime=regime)
        states.append(x)
    times = np.arange(n_steps + 1) * dt
    return Trajectory(states=states, times=times)
