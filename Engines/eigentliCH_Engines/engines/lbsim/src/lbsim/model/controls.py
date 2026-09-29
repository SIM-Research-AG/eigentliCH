"""Control variables (spec §4): two budgets allocated each period.

The saving rate is deliberately NOT here — it is an output of the money flows,
never an input (spec §3, Chapter 1 "move three").
"""

from __future__ import annotations

from dataclasses import dataclass

_TOL = 1e-9


@dataclass
class Control:
    """The levers the planner actually holds each period."""

    # Time shares of the productive budget, each in [0, 1] (spec §4.1).
    tau_Y: float  # earning / working
    tau_E: float  # learning / building expertise
    tau_N: float  # networking / relationship-building
    tau_H: float  # recovery / health / rest

    # Money flows, CHF/yr (spec §4.2).
    C: float      # consumption (endogenous → sets the saving rate)
    m_E: float    # education / skill spend
    m_N: float    # network spend
    p_A: float    # amortisation payment (reduces D)

    # Financial control (spec §4.3).
    theta: float  # portfolio risk tilt ∈ [0, 1]

    @property
    def tau_leisure(self) -> float:
        """Slack in the time budget τ_L = 1 − Σ τ, which enters utility."""
        return 1.0 - (self.tau_Y + self.tau_E + self.tau_N + self.tau_H)

    def time_budget_ok(self) -> bool:
        """τ_Y + τ_E + τ_N + τ_H ≤ 1, all τ ≥ 0 (spec §4.1, eq. 4.2)."""
        taus = (self.tau_Y, self.tau_E, self.tau_N, self.tau_H)
        return all(t >= -_TOL for t in taus) and sum(taus) <= 1.0 + _TOL

    def money_nonneg(self) -> bool:
        """C, m_E, m_N, p_A ≥ 0 (spec §4.2, §10)."""
        return all(v >= -_TOL for v in (self.C, self.m_E, self.m_N, self.p_A))

    def theta_ok(self) -> bool:
        return -_TOL <= self.theta <= 1.0 + _TOL

    def is_admissible(self) -> bool:
        """Full admissibility short of the liquidity floor (which needs state)."""
        return self.time_budget_ok() and self.money_nonneg() and self.theta_ok()
