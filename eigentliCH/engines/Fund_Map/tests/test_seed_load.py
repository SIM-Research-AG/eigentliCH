"""Seed integrity — spec section 8, test 1.

Every ret_distribution has length 25; role-consistent monotonicity holds; all enumerations valid.

**These run against the fixture register, not the production one** — see `conftest.py::_use_fixture_register`
for why. The fixture is the 54 rows of the pre-2026-08-02 register, kept because a rich
register exercises estimator paths that the eight-instrument production register cannot reach.
`test_the_production_register_is_well_formed` at the foot of this module is the one test here that reads the
live file, so a broken production register still fails inside this engine's own suite.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest

from fmre.registers.building_blocks import (
    STATE_GRID,
    AssetClass,
    CanonicalRole,
    CapitalType,
    EconomicPhase,
    Liquidity,
    Region,
    Role,
    Scenario,
    SeedLoadError,
    iter_role_violations,
    load_seed,
)


@pytest.fixture(scope="module")
def blocks():
    return load_seed()


def test_seed_row_count(blocks):
    """54 rows in the fixture register: the bootstrap dataset as it stood before the 2026-08-02 cut."""
    assert len(blocks) == 54


def test_the_production_register_is_well_formed():
    """The live register, by its real path — the one test here that does not use the fixture.

    Repointing this suite at a fixture (2026-08-02) removed the production register from its coverage, which
    would have been a silent loss: a malformed live register would then only fail in the andersCH-level
    suite, one repository level away from the code that defines it. This test closes that hole. It asserts
    shape rather than contents, because the contents are an investment-policy decision and this suite has no
    business pinning them.
    """
    from fmre.registers.building_blocks import _real_seed_path

    production = load_seed(_real_seed_path())
    assert production, "the production register is empty"
    tickers = [b.ticker for b in production]
    assert len(tickers) == len(set(tickers)), f"duplicate tickers in production: {tickers}"
    assert not list(iter_role_violations(production)), (
        f"role-shape violations in production: {[(b.id, r) for b, r in iter_role_violations(production)]}"
    )
    roles = {b.canonical_role for b in production}
    assert roles == set(CanonicalRole), (
        f"the production register does not cover all four roles: has {sorted(r.value for r in roles)}. "
        f"A mandate carrying a floor on a missing role cannot be met."
    )


def test_seed_ids_are_unique_and_ascending(blocks):
    """Ids are unique and ascending, but no longer a contiguous 1..N.

    This asserted `list(range(1, 55))` until 2026-08-02. Two things made a contiguous run the wrong
    invariant. The fixture register retired ids 45 to 49 as duplicate tickers, and the production register
    was cut to eight instruments that kept their original ids (17, 18, 32, 33, 37, 40, 42, 54) precisely so
    a reader can still trace each one back to the row it came from. Renumbering to 1..8 would have destroyed
    that link and silently repointed every stored mandate.

    So contiguity was never the property worth protecting — uniqueness and stable ordering are.
    """
    ids = [b.id for b in blocks]
    assert len(ids) == len(set(ids)), f"duplicate ids in the register: {ids}"
    assert ids == sorted(ids), f"ids are not ascending: {ids}"
    assert all(i >= 1 for i in ids), f"ids must be positive: {ids}"


def test_ret_distribution_length_all_25(blocks):
    """Every ret_distribution has length exactly STATE_GRID."""
    for b in blocks:
        assert len(b.ret_distribution) == STATE_GRID, (
            f"id={b.id} '{b.name_en}': length={len(b.ret_distribution)}"
        )


def test_ret_distribution_values_are_finite(blocks):
    import math

    for b in blocks:
        for i, v in enumerate(b.ret_distribution):
            assert math.isfinite(v), f"id={b.id} state={i}: non-finite value {v}"


def test_all_enums_valid(blocks):
    """load_seed already enforces this; assert type membership for readability."""
    for b in blocks:
        assert isinstance(b.asset_class, AssetClass)
        assert isinstance(b.role, Role)
        assert isinstance(b.home_scenario, Scenario)
        assert isinstance(b.region, Region)
        assert isinstance(b.economic_phase, EconomicPhase)
        assert isinstance(b.capital_type, CapitalType)
        assert isinstance(b.liquidity, Liquidity)


def test_role_shape_invariants_hold_on_seed(blocks):
    """Spec 4.1 role-consistent shape; see D9 for the Cash exception."""
    violations = list(iter_role_violations(blocks))
    if violations:
        msg = "\n".join(f"  id={b.id} role={b.role.value} '{b.name_en}': {reason}" for b, reason in violations)
        pytest.fail(f"role shape violations:\n{msg}")


def test_canonical_role_map_covers_all_roles(blocks):
    """Every seed row exposes a canonical (British) role."""
    seen_canonical = {b.canonical_role for b in blocks}
    assert seen_canonical == set(CanonicalRole)  # all four roles appear in the seed


def test_no_boom_home_scenario_in_seed(blocks):
    """D3: the seed does not use Boom as a home scenario."""
    scenarios = {b.home_scenario for b in blocks}
    assert scenarios <= {Scenario.EXPANSION, Scenario.STAGNATION, Scenario.CONTRACTION, Scenario.CRISIS}


def test_growth_blocks_ascend_into_boom(blocks):
    """D1 evidence: index 0 = crisis, index 24 = boom. Growth blocks ascend."""
    for b in blocks:
        if b.role is Role.GROWTH:
            first5 = sum(b.ret_distribution[:5]) / 5.0
            last5 = sum(b.ret_distribution[-5:]) / 5.0
            assert last5 > first5, f"id={b.id}: last5={last5:.2f} not > first5={first5:.2f}"


def test_protection_hedges_descend_from_crisis(blocks):
    """D1 evidence: protection HEDGE blocks (Gold, Long Vol, Short MSCI) descend from index 0."""
    hedge_ids = {33, 37, 49, 53}
    for b in blocks:
        if b.id in hedge_ids:
            first5 = sum(b.ret_distribution[:5]) / 5.0
            last5 = sum(b.ret_distribution[-5:]) / 5.0
            assert first5 > last5, f"id={b.id} '{b.name_en}': first5={first5:.2f} not > last5={last5:.2f}"


def test_state_to_scenario_map_partitions_25_states():
    with resources.files("fmre.registers").joinpath("seed/state_to_scenario.json").open("r") as fh:
        sts = json.load(fh)
    assert sts["state_grid"] == STATE_GRID
    mapping = sts["state_to_scenario"]
    keys = sorted(int(k) for k in mapping.keys())
    assert keys == list(range(STATE_GRID)), "state indices must be exactly 0..24"
    scenarios = list(sts["scenario_order"])
    assert scenarios == ["crisis", "contraction", "stagnation", "expansion", "boom"]
    for scen in scenarios:
        assert any(v == scen for v in mapping.values()), f"scenario {scen} unused"
    for k, v in mapping.items():
        assert v in scenarios, f"state {k} maps to unknown scenario {v}"


def test_state_to_scenario_map_preserves_ordering():
    """crisis at low indices; boom at high indices; monotone in scenario rank."""
    with resources.files("fmre.registers").joinpath("seed/state_to_scenario.json").open("r") as fh:
        sts = json.load(fh)
    rank = {s: i for i, s in enumerate(sts["scenario_order"])}
    prev_rank = -1
    for k in sorted(int(x) for x in sts["state_to_scenario"].keys()):
        r = rank[sts["state_to_scenario"][str(k)]]
        assert r >= prev_rank, f"scenario ordering breaks at state {k}"
        prev_rank = r


def test_seed_load_error_on_bad_row(tmp_path: Path):
    """load_seed emits a targeted SeedLoadError with row context on a bad enum."""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text(
        "ID,names,Ticker,Asset Class,Portfolio Role,Portfolio Scenario,Ret Distribution,"
        "Risk Signal,Economic Phase,Capital Type,Currency,Liquidity,ESG,Region\n"
        "1,X,T,NotAnAssetClass,Growth,Expansion,"
        "\"0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\","
        "Europe,Saturation,Financial,EUR,Daily,1,Europe\n",
        encoding="utf-8",
    )
    with pytest.raises(SeedLoadError, match="Asset Class"):
        load_seed(bad_csv)


def test_seed_load_error_on_wrong_length(tmp_path: Path):
    """A ret_distribution with the wrong length is rejected with row context."""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text(
        "ID,names,Ticker,Asset Class,Portfolio Role,Portfolio Scenario,Ret Distribution,"
        "Risk Signal,Economic Phase,Capital Type,Currency,Liquidity,ESG,Region\n"
        "1,X,T,Equity,Growth,Expansion,"
        "\"0,0,0,0,0\","
        "Europe,Saturation,Financial,EUR,Daily,1,Europe\n",
        encoding="utf-8",
    )
    with pytest.raises(SeedLoadError, match="length="):
        load_seed(bad_csv)


def test_seed_load_error_on_missing_region_column(tmp_path: Path):
    """The geographic Region column is required, not optional.

    Without it the downstream regional allocation constraint has nothing to classify against, and the
    old `Risk Signal` column is a regime scope rather than a place. Falling back to it would put a
    signal scope into a geographic bound.
    """
    bad_csv = tmp_path / "no_region.csv"
    bad_csv.write_text(
        "ID,names,Ticker,Asset Class,Portfolio Role,Portfolio Scenario,Ret Distribution,"
        "Risk Signal,Economic Phase,Capital Type,Currency,Liquidity,ESG\n"
        "1,X,T,Equity,Growth,Expansion,"
        "\"0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\","
        "Europe,Saturation,Financial,EUR,Daily,1\n",
        encoding="utf-8",
    )
    with pytest.raises(SeedLoadError, match=r"missing columns.*Region"):
        load_seed(bad_csv)


def test_seed_load_error_on_unknown_region(tmp_path: Path):
    """A region outside the seven-value vocabulary is refused rather than bucketed."""
    bad_csv = tmp_path / "bad_region.csv"
    bad_csv.write_text(
        "ID,names,Ticker,Asset Class,Portfolio Role,Portfolio Scenario,Ret Distribution,"
        "Risk Signal,Economic Phase,Capital Type,Currency,Liquidity,ESG,Region\n"
        "1,X,T,Equity,Growth,Expansion,"
        "\"0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\","
        "Europe,Saturation,Financial,EUR,Daily,1,Atlantis\n",
        encoding="utf-8",
    )
    with pytest.raises(SeedLoadError, match="Region"):
        load_seed(bad_csv)
