"""Calibration: ranges, weights and thresholds, and nothing else.

The fifteen calibration triples are copied from ``HoNI2.m`` (Version 2.0), section "Define
Range Struct", and are unchanged. What *is* new is everything around them: each index
names its transfer function explicitly, the policies that used to be implicit in the
MATLAB code are parameters, and every parameter set is a numbered version that is never
edited.

Three seed versions ship with the engine:

``1.0.0``
    Missing data is excluded and the sector re-weighted (fix for defect 9.1),
    and a sector needs at least three of its five indices to be scored.

``1.1.0``
    The active version: 1.0.0 plus the datafeed gate. An index whose inputs datafeed flags
    as implausible (today: consumption dependency where consumption and GDP are not in the
    same unit) is dropped for that country and re-weighted.

``0.1.0-matlab``
    Reproduces ``HoNI2.m``: a missing index scores 1. It exists so the golden test can
    reconcile this port against the MATLAB export, and so the effect of the fix can be
    shown rather than asserted. It is not meant for production runs.

A seed can never be changed in place. To change a figure, propose a new version through
``PUT /calibration``; the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Calibration, IndexSpec

#: Equal thirds across the sectors, as ``w_model`` in HoNI2.m.
SECTOR_WEIGHTS = {"financial": 1 / 3, "international": 1 / 3, "real": 1 / 3}

#: (index, transfer function, (min, mid, max)). MATLAB "Sigmoid" is the ramp and MATLAB
#: "Poly" is the tent: both are piecewise linear (manual section 5), and they are named for
#: what they are.
_TRIPLES: tuple[tuple[str, str, tuple[float, float, float]], ...] = (
    # Financial economy
    ("budget_balance", "ramp", (-0.10, -0.035, 0.0)),
    ("monetary_supply", "tent", (-0.01, 0.02, 0.05)),
    ("government_debt", "ramp", (1.2, 1.0, 0.3)),          # descending: less is more
    ("real_rate_10y", "ramp", (-0.01, 0.0, 0.03)),
    ("market_cap", "tent", (0.3, 0.7, 1.2)),
    # International resilience
    ("external_debt_affordability", "ramp", (-0.05, 0.0, 0.10)),
    ("external_debt_exposure", "tent", (0.1, 0.5, 5.0)),
    ("terms_of_trade", "ramp", (-25.0, -5.0, 5.0)),
    ("import_reserves", "ramp", (0.0, 0.50, 2.0)),
    ("corruption_freedom", "ramp", (20.0, 40.0, 85.0)),
    # Real economy
    ("consumption_power", "ramp", (-0.05, 0.0, 0.05)),
    ("population_growth", "tent", (0.0, 0.008, 0.015)),
    ("gdp_per_capita_growth", "ramp", (-0.01, 0.03, 0.05)),
    ("consumption_dependency", "tent", (0.40, 0.55, 0.70)),
    ("labour_force", "ramp", (0.5, 0.7, 0.85)),
)


def _indices() -> tuple[IndexSpec, ...]:
    return tuple(IndexSpec(name=n, kind=k, range=r, weight=1.0) for n, k, r in _TRIPLES)


DEFAULT = Calibration(
    version="1.0.0",
    note=(
        "HoNI2.m ranges and weights. Missing indices are excluded and the sector is "
        "re-weighted; a sector needs three of five indices to be scored."
    ),
    indices=_indices(),
    sector_weights=SECTOR_WEIGHTS,
    missing_policy="exclude",
    min_indices_per_sector=3,
)

MATLAB = Calibration(
    version="0.1.0-matlab",
    note=(
        "Reproduces HoNI2.m v2.0 for reconciliation: a missing index scores 1 (defect 9.1, "
        "kept on purpose). Not for production runs."
    ),
    indices=_indices(),
    sector_weights=SECTOR_WEIGHTS,
    missing_policy="score_worst",
    min_indices_per_sector=1,
)

DATAFEED_GATED = Calibration.model_validate({
    **DEFAULT.model_dump(),
    "version": "1.1.0",
    "parent_version": "1.0.0",
    "note": (
        "1.0.0 plus the datafeed gate: where datafeed's consumption_share check finds that "
        "household consumption and GDP are not in the same unit, consumption dependency is "
        "dropped for that country and its sector re-weighted, instead of scoring 1."
    ),
    "exclude_on_plausibility": {"consumption_share": ("consumption_dependency",)},
})

SEEDS: tuple[Calibration, ...] = (MATLAB, DEFAULT, DATAFEED_GATED)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
