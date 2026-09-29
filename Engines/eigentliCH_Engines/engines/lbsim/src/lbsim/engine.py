"""Pure functions, no I/O and no HTTP (Engine Building Guide section 2).

``build_findings`` turns a Life Balance Sheet, its request and the lbs records it names into the
``LifeBalanceFindings`` artefact (``lbsim.fast.build``). ``build_paths`` simulates the stated plan in every Regime
into ``LifeBalancePaths`` (``lbsim.paths.build``, on the checked upstream bundle of ``lbsim.upstream``). The plan
(``LifeBalancePlan``) is computed by the workers through ``lbsim.optim`` and ``lbsim.plan``; it is not imported
here, so nothing that imports this module loads casadi (LBSIM-03).
"""

from __future__ import annotations

from .fast.build import build_findings, quantities
from .paths.build import build_paths

__all__ = ["build_findings", "build_paths", "quantities"]
