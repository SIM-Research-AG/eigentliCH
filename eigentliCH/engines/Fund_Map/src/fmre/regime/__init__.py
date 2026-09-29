"""Regime timeline contract loader and helpers (spec 3.4)."""

from fmre.regime.state_to_scenario import StateToScenario
from fmre.regime.synthetic import build_synthetic_timeline, timeline_to_dict
from fmre.regime.timeline import (
    STATE_GRID,
    RegimeSnapshot,
    RegimeTimeline,
    TimelineValidationError,
    load_timeline,
    require_scope,
)

__all__ = [
    "STATE_GRID",
    "RegimeSnapshot",
    "RegimeTimeline",
    "TimelineValidationError",
    "StateToScenario",
    "load_timeline",
    "require_scope",
    "build_synthetic_timeline",
    "timeline_to_dict",
]
