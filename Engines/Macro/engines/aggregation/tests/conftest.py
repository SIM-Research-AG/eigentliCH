"""Shared fixtures: the frozen inputs in ``golden/inputs`` (see ``golden/build_golden.py``).

The pure engine and the golden reconciliation need no server. The store and API tests need a
real PostgreSQL server with the ``aggregation`` role, as every engine's suite does; they are in
``test_api.py`` and say so when the server or the role is not there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aggregation.contracts import CycleState, MacroState, MarketRiskSignal

GOLDEN = Path(__file__).resolve().parent.parent / "golden"
INPUTS = GOLDEN / "inputs"


@pytest.fixture(scope="session")
def mrs() -> MarketRiskSignal:
    return MarketRiskSignal.model_validate_json((INPUTS / "mrs.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def cycle() -> CycleState:
    return CycleState.model_validate_json((INPUTS / "cycle.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def macro() -> MacroState:
    return MacroState.model_validate_json((INPUTS / "macrofield.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def draft() -> dict:
    return json.loads((GOLDEN / "draft_1.0.0.json").read_text(encoding="utf-8"))


def expected(version: str) -> dict:
    return json.loads((GOLDEN / f"expected_{version}.json").read_text(encoding="utf-8"))
