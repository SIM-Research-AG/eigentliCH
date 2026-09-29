"""House-view superposition (spec 5.6).

Given the house view ``omega_s`` — a probability weighting over the 5
scenarios with an explicit, non-zero tail weight — collapse the per-role or
per-block scenario profile into a scalar expectation:

    E[R] = sum_s omega_s * P_s

This module is a thin re-export of the same functions living on
``fmre.contracts.returnset``. The contract module owns the definition
because it also owns the ``house_view`` field on the emitted ReturnSet;
this module exists to match the spec section 7 layout.
"""

from __future__ import annotations

from fmre.contracts.returnset import (
    DEFAULT_HOUSE_VIEW,
    superpose_block_expectations,
    superpose_role_expectations,
)

__all__ = [
    "DEFAULT_HOUSE_VIEW",
    "superpose_block_expectations",
    "superpose_role_expectations",
]
