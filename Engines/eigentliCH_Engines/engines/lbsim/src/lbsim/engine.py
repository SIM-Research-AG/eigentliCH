"""Pure functions, no I/O and no HTTP (Engine Building Guide section 2).

The fast half is built (B1): ``build_findings`` turns a Life Balance Sheet, its request and the lbs records it
names into the ``LifeBalanceFindings`` artefact. The vectorised Monte Carlo (``LifeBalancePaths``) is B2's and the
optimiser (``LifeBalancePlan``, ``lbsim.optim``) is C's; they join here.
"""

from __future__ import annotations

from .fast.build import build_findings, quantities

__all__ = ["build_findings", "quantities"]
