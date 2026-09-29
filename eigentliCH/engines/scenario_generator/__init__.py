"""Scenario Generator. Reads a Snapshot and a change; writes a Scenario.

Applies a change the *client* proposed and reports the consequence. It does not search for a good change, rank
changes, or suggest one: those produce a proposal, a proposal is a Recommendation, and a Recommendation is
regulated. The `Scenario` contract refuses `change_origin="system"` for that reason.
"""

from engines.scenario_generator.adapter import ScenarioGeneratorAdapter
from engines.scenario_generator.engine import (
    CHANGEABLE,
    WORLD_FIELDS,
    Baseline,
    ChangeRefused,
    Outcome,
    apply_change,
)

__all__ = [
    "CHANGEABLE",
    "WORLD_FIELDS",
    "Baseline",
    "ChangeRefused",
    "Outcome",
    "ScenarioGeneratorAdapter",
    "apply_change",
]
