"""SEAM 3: taxes & institutions (Chapter 20 §3).

Pension pillars, mortgage rules and tax treatment enter as adjustments to the
cash-flow identity — they change the numbers, not the structure. The dynamics
route net cash through a FiscalModel; v1 uses IdentityFiscal (no tax), so the
Swiss-specific layer drops in later without touching the SDEs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .params import Params
from .state import State


@runtime_checkable
class FiscalModel(Protocol):
    def adjust_net_cash(
        self,
        net_cash: float,
        *,
        income: float,
        asset_yield: float,
        state: State,
        params: Params,
    ) -> float:
        """Return net cash to liquid wealth after taxes/institutional flows."""
        ...


class IdentityFiscal:
    """No tax, no institutional adjustment — the v1 default."""

    def adjust_net_cash(
        self,
        net_cash: float,
        *,
        income: float,
        asset_yield: float,
        state: State,
        params: Params,
    ) -> float:
        return net_cash


DEFAULT_FISCAL = IdentityFiscal()
