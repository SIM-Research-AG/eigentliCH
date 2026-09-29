"""Score engine. Reads the FDT event stream and the Regime; writes a Score.

Educational, and therefore always decomposable: every component carries its value, weight and a note. A number a
client cannot take apart is a verdict rather than education.

It refuses to score a stream below `MINIMUM_EVENTS`, because a score from a handful of events looks identical to
one from hundreds and presenting them alike would mislead more than saying "not yet scored".
"""

from engines.score.adapter import ScoreAdapter
from engines.score.engine import (
    DEFAULT_WEIGHTS,
    MINIMUM_EVENTS,
    REGIME_ADJUSTMENT_CAP,
    SCALE_MAX,
    SCALE_MIN,
    Component,
    NotEnoughHistory,
    Scored,
    score,
    tier_for,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "MINIMUM_EVENTS",
    "REGIME_ADJUSTMENT_CAP",
    "SCALE_MAX",
    "SCALE_MIN",
    "Component",
    "NotEnoughHistory",
    "ScoreAdapter",
    "Scored",
    "score",
    "tier_for",
]
