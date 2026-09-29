"""S-curve Goal-Trajectory engine. Reads a goal, contributions and a return; writes a Trajectory.

Per-goal rather than per-user, which is why it is separate from the Life Balance Sheet: that engine simulates a
household, this one answers whether a single goal lands. Both write a Trajectory; the `model_version`
distinguishes which produced it.

`required_return` is the quantity the derived mandate needs (DECISIONS.md M4): the constant annual return that
funds the goal exactly by its deadline.
"""

from engines.s_curve_trajectory.adapter import SCurveTrajectoryAdapter
from engines.s_curve_trajectory.engine import (
    BAND_Z,
    STEPS_PER_YEAR,
    Curve,
    Point,
    project,
    required_return,
)

__all__ = [
    "BAND_Z",
    "STEPS_PER_YEAR",
    "Curve",
    "Point",
    "SCurveTrajectoryAdapter",
    "project",
    "required_return",
]
