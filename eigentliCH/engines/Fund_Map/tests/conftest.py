import sys
from datetime import date
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for path in (_SRC, _ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# ---------------------------------------------------------------------------
# This suite runs against its own fixture register, not the production one
#
# `tests/fixtures/fund_map_seed_fixture.csv` is the 54-instrument register as
# it stood on 2026-08-02, kept verbatim as a test fixture. On that date the
# production register was cut to the eight instruments the CIO actually holds
# (DECISIONS.md M60), which broke 38 tests here and errored 41 more — almost
# all of them `StopIteration` from looking up an id that no longer exists.
#
# Repointing the suite is the fix rather than rewriting those tests, because
# the breakage exposed the real problem: this engine's unit tests are about the
# *estimator* — the fallback cascade, the scenario aggregation, the contract
# shape — and none of that is a claim about which instruments a CIO currently
# holds. Coupling them to the live register meant every investment-policy
# decision broke the estimator's tests, which trains a reader to edit tests
# when policy changes. A rich 54-block fixture also exercises paths eight
# blocks cannot reach: peer borrowing needs same-role peers, and duplicate
# tickers and shared authored profiles only exist at that size.
#
# The production register is still covered, deliberately and in two places:
# `test_seed_load.py::test_the_production_register_is_well_formed` loads it by
# its real path, and the andersCH-level `tests/` exercise all eight blocks end
# to end through the published ReturnSet. So a broken production register still
# fails loudly; it just no longer fails as thirty-eight estimator tests.
# ---------------------------------------------------------------------------

FIXTURE_SEED = Path(__file__).resolve().parent / "fixtures" / "fund_map_seed_fixture.csv"


@pytest.fixture(scope="session", autouse=True)
def _use_fixture_register():
    """Point the bare `load_seed()` at the fixture register for this whole suite.

    Autouse and session-scoped so the ~20 existing bare `load_seed()` calls need no edit. Tests that mean
    the production register must pass its path explicitly — `load_seed()` still honours an argument, and
    that argument is the only way to reach the live file from here.
    """
    from fmre.registers import building_blocks

    original = building_blocks._seed_path
    building_blocks._seed_path = lambda: FIXTURE_SEED
    try:
        yield
    finally:
        building_blocks._seed_path = original


@pytest.fixture(scope="session")
def seed_blocks():
    from fmre.registers.building_blocks import load_seed

    return load_seed()


@pytest.fixture(scope="session")
def estimates_for_seed(seed_blocks):
    """`(estimates, timeline)` for the whole seed register."""
    from fmre.estimate import estimate_block
    from fmre.ingest.pipeline import ingest_ticker
    from fmre.ingest.sources import SyntheticSource
    from fmre.regime import build_synthetic_timeline
    from fmre.registers.data_series import build_default_register

    blocks_by_id = {b.id: b for b in seed_blocks}
    register = build_default_register(seed_blocks)
    source = SyntheticSource(start=date(1998, 1, 31), end=date(2024, 12, 31))
    timeline = build_synthetic_timeline()

    estimates: dict = {}
    for block in seed_blocks:
        harmonised = ingest_ticker(block.ticker, source, register)
        aligned = timeline.align_returns(harmonised.returns)
        estimates[block.id] = estimate_block(
            block,
            aligned,
            all_estimates=estimates,
            all_blocks=blocks_by_id,
            calibration_window=("1998-01", "2024-12"),
        )
    return estimates, timeline


@pytest.fixture(scope="session")
def full_returnset_payload(seed_blocks, estimates_for_seed):
    """The emitted ReturnSet payload for the whole seed register."""
    from fmre.contracts import build_returnset
    from fmre.regime import StateToScenario

    estimates, timeline = estimates_for_seed
    returnset = build_returnset(
        estimates=estimates,
        blocks_by_id={b.id: b for b in seed_blocks},
        state_to_scenario=StateToScenario.load(),
        timeline=timeline,
        calibration_window=("1998-01", "2024-12"),
    )
    return returnset.to_dict()
