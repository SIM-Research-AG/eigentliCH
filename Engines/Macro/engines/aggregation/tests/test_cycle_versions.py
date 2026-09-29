"""AGG-18: the cycle mirror reads cycle-state 1.1.0 and 1.2.0 and refuses anything else."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aggregation.contracts import CONTRACT_VERSIONS, CYCLE_STATE_ACCEPTED, CycleState
from tests.conftest import INPUTS


def _frozen() -> dict:
    return json.loads((INPUTS / "cycle.json").read_text(encoding="utf-8"))


def test_the_frozen_1_1_0_input_still_validates():
    assert CycleState.model_validate(_frozen()).contract_version == "cycle-state@1.1.0"


def test_a_1_2_0_artefact_with_the_new_fields_validates():
    body = _frozen()
    body["contract_version"] = "cycle-state@1.2.0"
    for e in body["economies"]:
        e["superposition_anchored"] = [0.0] * len(body["years"])
        e["anchored_members"] = ["credit", "innovation", "capital"]
    state = CycleState.model_validate(body)
    assert state.contract_version == "cycle-state@1.2.0"
    assert state == CycleState.model_validate({**_frozen(), "contract_version": "cycle-state@1.2.0"})


@pytest.mark.parametrize("version", ["cycle-state@1.0.0", "cycle-state@2.0.0", "cycle-state"])
def test_any_other_version_is_refused(version):
    body = _frozen()
    body["contract_version"] = version
    with pytest.raises(ValidationError):
        CycleState.model_validate(body)


def test_the_key_keeps_the_version_the_engine_was_written_against():
    assert CONTRACT_VERSIONS["CycleState(cycle)"] == "cycle-state@1.1.0"
    assert CYCLE_STATE_ACCEPTED == ("cycle-state@1.1.0", "cycle-state@1.2.0")
