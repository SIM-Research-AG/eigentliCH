"""Tests for the register classification the ReturnSet publishes per building block.

Added with the re@0.2.0 contract. The consumer cannot assemble an allocation constraint without these
fields, and the two region fields exist because conflating a regime signal scope with a place is the
defect decisions.md D11 fixes. These tests are what stop them being merged back together.
"""

from __future__ import annotations

import pytest

from fmre.contracts.returnset import (
    ALLOWED_HOME_SCENARIO,
    ALLOWED_REGION_GEO,
    ALLOWED_REGION_SCOPE,
    ReturnSetValidationError,
    build_returnset,
    validate_returnset,
)
from fmre.registers.building_blocks import RegionGeo, load_seed

#: Every field a consumer needs in order to place a block in a constraint block or on the portfolio map.
REQUIRED_METADATA = (
    "name",
    "region_geo",
    "region_scope",
    "home_scenario",
    "currency",
    "asset_class",
    "economic_phase",
    "capital_type",
    "liquidity",
    "esg",
)


class TestRegisterCarriesGeography:
    def test_every_seed_block_has_a_geographic_region(self):
        blocks = load_seed()
        assert len(blocks) == 54
        for block in blocks:
            assert isinstance(block.region_geo, RegionGeo)

    def test_geography_and_signal_scope_are_separate_fields(self):
        """Block 1 is the case that proves they differ: a World index scoped to the Europe signal."""
        by_id = {b.id: b for b in load_seed()}
        block = by_id[1]
        assert block.ticker == "MXWO0FD Index"
        assert block.region.value == "Europe"          # the signal scope
        assert block.region_geo is RegionGeo.OTHERS    # the geography

    def test_the_seven_value_vocabulary_is_the_constraint_order(self):
        """Order is load-bearing downstream, so it is pinned here rather than left to the enum."""
        assert tuple(r.value for r in RegionGeo) == ALLOWED_REGION_GEO

    def test_a_geography_is_used_that_the_scope_could_not_have_produced(self):
        """If geography were derived from scope, no block could read Switzerland, East Asia, South Asia,
        North America or South Pacific, because the scope vocabulary has none of those values."""
        geos = {b.region_geo.value for b in load_seed()}
        unreachable_from_scope = geos - set(ALLOWED_REGION_SCOPE)
        assert unreachable_from_scope, "geography looks derivable from the signal scope"
        assert "Switzerland" in geos


class TestPublishedMetadata:
    """Uses the session-scoped `full_returnset_payload` fixture from conftest directly."""

    def test_every_block_publishes_every_required_field(self, full_returnset_payload):
        for block in full_returnset_payload["building_blocks"]:
            missing = [f for f in REQUIRED_METADATA if f not in block]
            assert not missing, f"block {block['bb_id']} is missing {missing}"

    def test_the_ambiguous_region_field_is_gone(self, full_returnset_payload):
        """`region` said neither what it meant nor which vocabulary it used, so it was replaced by two
        named fields. Leaving it in place would let a consumer keep reading the wrong one."""
        for block in full_returnset_payload["building_blocks"]:
            assert "region" not in block

    def test_published_values_are_inside_their_vocabularies(self, full_returnset_payload):
        for block in full_returnset_payload["building_blocks"]:
            assert block["region_geo"] in ALLOWED_REGION_GEO
            assert block["region_scope"] in ALLOWED_REGION_SCOPE
            assert block["home_scenario"] in ALLOWED_HOME_SCENARIO

    def test_esg_is_an_integer_score(self, full_returnset_payload):
        """The consumer's ESG floor is a weighted average of these, so a string would fail there."""
        for block in full_returnset_payload["building_blocks"]:
            assert isinstance(block["esg"], int) and not isinstance(block["esg"], bool)

    def test_metadata_matches_the_register_block_by_block(self, full_returnset_payload):
        """The contract must republish the register, not a transformation of it."""
        by_id = {b.id: b for b in load_seed()}
        for block in full_returnset_payload["building_blocks"]:
            source = by_id[int(block["bb_id"])]
            assert block["name"] == source.name_en
            assert block["region_geo"] == source.region_geo.value
            assert block["region_scope"] == source.region.value
            assert block["home_scenario"] == source.home_scenario.value
            assert block["currency"] == source.currency
            assert block["asset_class"] == source.asset_class.value
            assert block["economic_phase"] == source.economic_phase.value
            assert block["capital_type"] == source.capital_type.value
            assert block["liquidity"] == source.liquidity.value
            assert block["esg"] == int(source.esg)

    def test_the_payload_validates(self, full_returnset_payload):
        validate_returnset(full_returnset_payload)


class TestValidationRejects:
    def test_a_missing_metadata_field_is_refused(self, full_returnset_payload):
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        del blocks[0]["region_geo"]
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="missing field 'region_geo'"):
            validate_returnset(payload)

    def test_an_unknown_region_geo_is_refused(self, full_returnset_payload):
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        blocks[0]["region_geo"] = "Atlantis"
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="region_geo"):
            validate_returnset(payload)

    def test_a_signal_scope_in_the_geography_field_is_refused(self, full_returnset_payload):
        """The specific mistake this contract exists to prevent: `Americas` is a scope, not a place, and
        the regional constraint has no such row."""
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        blocks[0]["region_geo"] = "Americas"
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="region_geo"):
            validate_returnset(payload)

    def test_a_geography_in_the_scope_field_is_refused(self, full_returnset_payload):
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        blocks[0]["region_scope"] = "Switzerland"
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="region_scope"):
            validate_returnset(payload)

    def test_a_non_integer_esg_is_refused(self, full_returnset_payload):
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        blocks[0]["esg"] = "high"
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="esg"):
            validate_returnset(payload)

    def test_an_unknown_home_scenario_is_refused(self, full_returnset_payload):
        payload = {**full_returnset_payload}
        blocks = [dict(b) for b in payload["building_blocks"]]
        blocks[0]["home_scenario"] = "Recovery"
        payload["building_blocks"] = blocks
        with pytest.raises(ReturnSetValidationError, match="home_scenario"):
            validate_returnset(payload)

    def test_a_block_absent_from_the_register_cannot_be_published(self, seed_blocks, estimates_for_seed):
        """The ReturnSet does not carry a block it cannot describe."""
        from fmre.regime import StateToScenario, build_synthetic_timeline

        estimates, _ = estimates_for_seed
        incomplete = {b.id: b for b in seed_blocks if b.id != next(iter(estimates))}
        with pytest.raises(ReturnSetValidationError, match="no register entry"):
            build_returnset(
                estimates=estimates,
                blocks_by_id=incomplete,
                state_to_scenario=StateToScenario.load(),
                timeline=build_synthetic_timeline(),
            )
