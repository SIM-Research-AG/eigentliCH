"""State-to-scenario map (spec 3.2).

A versioned partition of the 25 ordered regime states into the 5 scenarios
(crisis at the low-index end, boom at the high-index end). Enforced to be
monotone in scenario rank across the state axis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from fmre.regime.timeline import STATE_GRID, TimelineValidationError


@dataclass(frozen=True, slots=True)
class StateToScenario:
    version: str
    provisional: bool
    state_grid: int
    scenario_order: tuple[str, ...]     # low-rank (crisis) to high-rank (boom)
    mapping: tuple[str, ...]            # index i -> scenario name for state i

    def scenario_of(self, state: int) -> str:
        if not (0 <= state < self.state_grid):
            raise ValueError(f"state {state} not in 0..{self.state_grid - 1}")
        return self.mapping[state]

    def states_of(self, scenario: str) -> tuple[int, ...]:
        if scenario not in self.scenario_order:
            raise ValueError(f"unknown scenario {scenario!r}; allowed: {self.scenario_order}")
        return tuple(i for i, s in enumerate(self.mapping) if s == scenario)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "StateToScenario":
        if path is None:
            resource = resources.files("fmre.registers").joinpath("seed/state_to_scenario.json")
            with resource.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        else:
            with Path(path).open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        return _from_dict(data)


def _from_dict(data: dict) -> StateToScenario:
    for k in ("version", "state_grid", "scenario_order", "state_to_scenario"):
        if k not in data:
            raise TimelineValidationError(f"state_to_scenario missing field {k!r}")
    if data["state_grid"] != STATE_GRID:
        raise TimelineValidationError(
            f"state_to_scenario.state_grid must be {STATE_GRID}, got {data['state_grid']}"
        )
    scenario_order = tuple(data["scenario_order"])
    if len(scenario_order) != len(set(scenario_order)):
        raise TimelineValidationError("scenario_order contains duplicates")

    raw = data["state_to_scenario"]
    keys = sorted(int(k) for k in raw.keys())
    if keys != list(range(STATE_GRID)):
        raise TimelineValidationError(
            f"state_to_scenario keys must be exactly 0..{STATE_GRID - 1}, got {keys}"
        )
    mapping = tuple(raw[str(i)] for i in range(STATE_GRID))
    for i, scen in enumerate(mapping):
        if scen not in scenario_order:
            raise TimelineValidationError(f"state {i} maps to unknown scenario {scen!r}")

    rank = {s: i for i, s in enumerate(scenario_order)}
    prev = -1
    for i, scen in enumerate(mapping):
        r = rank[scen]
        if r < prev:
            raise TimelineValidationError(
                f"state_to_scenario ordering breaks at state {i}: "
                f"scenario rank went from {prev} to {r}"
            )
        prev = r

    unused = set(scenario_order) - set(mapping)
    if unused:
        raise TimelineValidationError(f"unused scenarios in mapping: {sorted(unused)}")

    return StateToScenario(
        version=str(data["version"]),
        provisional=bool(data.get("provisional", False)),
        state_grid=STATE_GRID,
        scenario_order=scenario_order,
        mapping=mapping,
    )
