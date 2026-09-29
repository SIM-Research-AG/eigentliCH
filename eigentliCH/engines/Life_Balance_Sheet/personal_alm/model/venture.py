"""Venture income — the simple v1 form of the entrepreneurial payoff (Q2, spec §18.4).

A founding event seeds a `Venture`: an income stream *seeded by expertise* that
ramps up an S-curve (logistic maturity 0 → 1) after founding. This is what lets
the Nicolas backtest reproduce the trading-system-funds-property arc and the
SIM Research founding — neither of which is expressible on wage income alone.

Kept deliberately minimal: income = scale · E_agg^a_v · maturity. The lumpy /
optionable exit payoff (equity crystallising on a sale) is a later extension;
this captures the ramp and the E-dependence, which is what the backtest needs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Venture:
    name: str
    scale: float          # income at E_agg = 1 and full maturity   [CHF/yr]
    a_v: float = 0.5      # expertise exponent (seeded by E)
    ramp: float = 0.5     # logistic ramp rate toward full maturity  [1/yr]
    maturity: float = 0.0  # STATE: S-curve progress 0 → 1

    def income(self, E_agg: float) -> float:
        return self.scale * (E_agg ** self.a_v) * self.maturity

    def maturity_drift(self) -> float:
        """Logistic ramp: dmaturity/dt = ramp · maturity · (1 − maturity)."""
        return self.ramp * self.maturity * (1.0 - self.maturity)

    def copy(self) -> "Venture":
        return Venture(
            name=self.name, scale=self.scale, a_v=self.a_v,
            ramp=self.ramp, maturity=self.maturity,
        )
