"""Shared fixtures.

The synthetic universe here is deliberately small and hand-specified, so a constraint test can be reasoned
about rather than merely run. The real-contract fixtures skip when the upstream artefacts have not been
published, so the suite is runnable without them while still exercising the real path when they exist.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pcp.config import load_config
from pcp.contracts import Bound, BuildingBlock, Mandate, RegimeTimeline, ReturnSet

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REGIME_DIR = PROJECT_ROOT.parent / "Macro_Model" / "output" / "regime"
RETURNSET = PROJECT_ROOT.parent / "Fund_Map" / "artifacts" / "rs.json"


@pytest.fixture(scope="session")
def config():
    return load_config()


def _block(
    bb_id: int,
    name: str,
    role: str,
    region_geo: str,
    currency: str,
    asset_class: str,
    scenario: str = "Stagnation",
    phase: str = "Saturation",
    capital_type: str = "Financial",
    liquidity: str = "Daily",
    esg: float = 1.0,
    profile: np.ndarray | None = None,
) -> BuildingBlock:
    if profile is None:
        profile = np.linspace(-0.3, 0.2, 25)
    return BuildingBlock(
        bb_id=bb_id,
        name=name,
        ticker=f"T{bb_id}",
        role=role,
        home_scenario=scenario,
        region_geo=region_geo,
        region_scope="Global",
        currency=currency,
        asset_class=asset_class,
        economic_phase=phase,
        capital_type=capital_type,
        liquidity=liquidity,
        esg=esg,
        profile_by_state=np.asarray(profile, dtype=float),
    )


@pytest.fixture
def blocks() -> tuple[BuildingBlock, ...]:
    """Four instruments spanning enough categories to make bounds meaningful."""
    ascending = np.linspace(-0.35, 0.25, 25)
    flat = np.full(25, 0.02)
    descending = np.linspace(0.10, -0.05, 25)
    return (
        _block(1, "CH Equity", "Gain", "Switzerland", "CHF", "Equity", profile=ascending),
        _block(2, "US Equity", "Gain", "North America", "USD", "Equity", profile=ascending * 1.1),
        _block(3, "CHF Bond", "Income", "Switzerland", "CHF", "Fixed Income", profile=flat, esg=3.0),
        _block(4, "Gold", "Protection", "Others", "USD", "Alternative", profile=descending, esg=2.0),
    )


@pytest.fixture
def mandate(blocks) -> Mandate:
    """A mandate that actually constrains something, so a binding test has something to bind."""
    return Mandate(
        client="Test",
        name="Constrained",
        market="Global",
        currency="CHF",
        benchmark="Swiss",
        max_single_position=0.5,
        esg_min=0.0,
        horizon_years=1.0,
        target_curve=np.linspace(-0.2, 0.3, 25),
        universe=tuple(b.bb_id for b in blocks),
        fixed_allocations={},
        bounds={
            "currency": {"CHF": Bound(0.30, 0.70), "USD": Bound(0.0, 0.50)},
            "role": {"Protection": Bound(0.05, 0.20)},
        },
    )


@pytest.fixture
def regime() -> RegimeTimeline:
    """A three-period regime with a live crisis tail."""
    rows = []
    for shift in (0, 2, 4):
        weights = np.zeros(25)
        weights[shift : shift + 5] = 0.06          # crisis-side mass
        weights[10 + shift : 15 + shift] = 0.14    # central mass
        weights /= weights.sum()
        rows.append(weights)
    return RegimeTimeline(
        regime_timeline_id="RTL-test",
        economy_scope="Global",
        model_version="ms@test",
        as_of="2024-12-31",
        period="M",
        state_grid=25,
        dates=("2024-10", "2024-11", "2024-12"),
        distributions=np.vstack(rows),
        regime_id="REG-test",
        current_state=12,
        phase=3,
        saturation_pct=300.0,
        provenance={"economy_weights": {"us": 1.0}},
    )


@pytest.fixture
def returnset(blocks, regime) -> ReturnSet:
    return ReturnSet(
        return_set_id="RS-test",
        regime_id=regime.regime_id,
        as_of="2024-12-31",
        model_version="re@test",
        universe_version="fm@test",
        state_to_scenario_version="sts@test",
        horizon_years=1.0,
        values_unit="annualised_decimal",
        state_grid=25,
        scenarios=("crisis", "contraction", "stagnation", "expansion", "boom"),
        state_to_scenario={i: "stagnation" for i in range(25)},
        house_view={
            "crisis": 0.15,
            "contraction": 0.2,
            "stagnation": 0.25,
            "expansion": 0.3,
            "boom": 0.1,
        },
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# The real published contracts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_regime_dir() -> Path:
    if not REGIME_DIR.exists() or not any(REGIME_DIR.glob("*.json")):
        pytest.skip(
            f"no Regime timeline published in {REGIME_DIR}. Publish with "
            f"'macrofield regime cn in us ch br gb de fr --scope Global'."
        )
    return REGIME_DIR


@pytest.fixture(scope="session")
def real_returnset_path() -> Path:
    if not RETURNSET.exists():
        pytest.skip(f"no ReturnSet published at {RETURNSET}")
    return RETURNSET


@pytest.fixture(scope="session")
def mandates_dir() -> Path:
    directory = PROJECT_ROOT / "mandates"
    if not directory.exists() or not any(directory.glob("*.yaml")):
        pytest.skip(
            f"no mandates in {directory}. Seed them with 'python -m tools.seed_mandates'."
        )
    return directory
