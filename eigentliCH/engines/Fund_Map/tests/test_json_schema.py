"""JSON Schema for the ReturnSet contract (documentation-grade).

The hand-coded validator in ``contracts/returnset.py`` is the runtime source
of truth. This schema exists to publish the contract to downstream
consumers and to guard against drift between the two.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def schema() -> dict:
    with resources.files("fmre.contracts").joinpath("schemas/returnset.schema.json").open("r") as fh:
        return json.load(fh)


def test_schema_is_valid_json(schema):
    assert "$schema" in schema
    assert schema["$schema"].startswith("https://json-schema.org/draft/")
    assert schema["type"] == "object"


def test_schema_forbids_extra_top_level_properties(schema):
    assert schema.get("additionalProperties") is False


def test_schema_requires_all_contract_fields(schema):
    required = set(schema["required"])
    expected = {
        "return_set_id", "regime_id", "as_of", "model_version", "universe_version",
        "state_to_scenario_version", "horizon_years", "state_grid", "scenarios",
        "state_to_scenario", "house_view", "role_profiles", "building_blocks",
        "provenance", "values_unit",
    }
    assert required == expected


def test_schema_pins_state_grid_to_25(schema):
    assert schema["properties"]["state_grid"]["const"] == 25


def test_schema_requires_crisis_house_view_strictly_positive(schema):
    crisis = schema["properties"]["house_view"]["properties"]["crisis"]
    assert crisis["exclusiveMinimum"] == 0


def test_schema_scenarios_exactly_five(schema):
    scenarios = schema["properties"]["scenarios"]
    assert scenarios["minItems"] == 5 and scenarios["maxItems"] == 5
    assert set(scenarios["items"]["enum"]) == {"crisis", "contraction", "stagnation", "expansion", "boom"}


def test_schema_role_profiles_only_canonical(schema):
    roles = set(schema["properties"]["role_profiles"]["properties"].keys())
    assert roles == {"gain", "income", "stabilisation", "protection"}


def test_schema_estimation_label_must_be_model_derived(schema):
    label = schema["$defs"]["BuildingBlock"]["properties"]["estimation"]["properties"]["label"]
    assert label["const"] == "model-derived"


def test_schema_state_to_scenario_key_pattern_covers_0_to_24(schema):
    """Key pattern must accept exactly 0..24."""
    import re
    pattern = schema["properties"]["state_to_scenario"]["propertyNames"]["pattern"]
    regex = re.compile(pattern)
    for i in range(25):
        assert regex.fullmatch(str(i)), f"{i} rejected"
    for bad in ("25", "-1", "07", "0a", ""):
        assert regex.fullmatch(bad) is None, f"{bad!r} should not match"


def test_schema_and_runtime_validator_agree_on_required_fields():
    """A payload the runtime validator accepts must satisfy the schema's
    required list too. Guards against silent drift."""
    from datetime import date

    from fmre.contracts import build_returnset, validate_returnset
    from fmre.estimate import estimate_block
    from fmre.ingest.pipeline import ingest_ticker
    from fmre.ingest.sources import SyntheticSource
    from fmre.regime import StateToScenario, build_synthetic_timeline
    from fmre.registers.building_blocks import load_seed
    from fmre.registers.data_series import build_default_register

    blocks = load_seed()
    blocks_by_id = {b.id: b for b in blocks}
    reg = build_default_register(blocks)
    src = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    tl = build_synthetic_timeline()
    sts = StateToScenario.load()
    estimates = {}
    for bid in (5, 20, 33, 35):
        b = blocks_by_id[bid]
        h = ingest_ticker(b.ticker, src, reg)
        aligned = tl.align_returns(h.returns)
        estimates[bid] = estimate_block(b, aligned)

    rs = build_returnset(estimates, blocks_by_id, sts, tl)
    payload = rs.to_dict()

    validate_returnset(payload)

    with resources.files("fmre.contracts").joinpath("schemas/returnset.schema.json").open("r") as fh:
        schema_doc = json.load(fh)
    for field in schema_doc["required"]:
        assert field in payload, f"payload missing schema-required field {field!r}"
