"""Versioned contracts this programme publishes to downstream consumers.

A contract is the boundary at which another programme is allowed to depend on this one. Everything
inside the package may change; what is published here may not, except by a version bump.

The Regime timeline is the only contract at present. It is consumed by the Fund Map and Return
Estimation programme (which estimates return profiles per regime state) and by the Portfolio Creation
Program (which integrates those profiles against the live regime distribution).
"""

from macrofield.contracts.regime_timeline import (
    CONTRACT_VERSION,
    STATE_GRID,
    RegimeTimelineContract,
    RegimeTimelineError,
    build_timeline,
    write_timeline,
)

__all__ = [
    "CONTRACT_VERSION",
    "STATE_GRID",
    "RegimeTimelineContract",
    "RegimeTimelineError",
    "build_timeline",
    "write_timeline",
]
