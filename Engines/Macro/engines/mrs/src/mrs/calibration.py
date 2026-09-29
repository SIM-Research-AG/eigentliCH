"""Calibration: weights, kernels, grid, indicator windows and thresholds, and nothing else.

Every MATLAB figure is transcribed from the Master Controller and is unchanged:

* ``Weights.m``: the grid ``linspace(-2, 2, 11)``, the band kernel ``binopdf(0:8, 8, 0.5)``
  sliding two states per column, and the stress tail ``binopdf(0:8, 8, 0.1)`` on states 1
  to 9, live from column 6, scaled by ``(j-5)^sqrt(2) / 11``.
* ``Controller_Test.xlsx``, sheet ``Market_Settings`` (hardcoded identically in
  ``MRS_Tester.m``): segment weights 0.25 each; ``w_Biz`` 0.25 each, ``w_Invst`` 0.5 each,
  ``w_Behav`` 0.8 / 0.2, ``w_Stress`` 1/3 each, ``w_all`` 0.5 / 0.25 / 0.25.
* ``MR_*.m``: every window and threshold (``IndicatorParams``).

No optimism and no market weights (MRS-13, MRS-18): ``mrs`` publishes at zero shift and
``aggregation`` owns both. Two live seeds:

``2.0.0`` (active)
    Production. The indicator layer on data up to each month only, gaps kept as gaps, the
    replacement inputs (MRS-15) and thresholds in data units (MRS-16). A missing segment is
    dropped for that date and the others re-weighted; three of four segments needed.

``2.0.0-matlab``
    Reproduces ``Market_Signal.m`` on MATLAB's view of ``M_TS``: full-sample normalisation,
    the MATLAB inputs and units, and a missing segment reading selects column 1 (what the
    MATLAB comparisons do with NaN). For the golden reconciliation only.

``RETIRED`` keeps the three v0.1.0 seeds (``mrs-calibration@1.0.0``, with optimism levels
and market blends) as the record; they are no longer loadable for a run.

A seed can never be changed in place. To change a figure, propose a new version through
``PUT /calibration``; the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json
import math

from .contracts import (BandKernel, Calibration, Edges, IndicatorParams, SegmentSpec,
                        StressThresholds, TailKernel)

SEGMENTS = (
    SegmentSpec(name="business_cycle", weight=0.25, kernel=BandKernel()),
    SegmentSpec(name="investment", weight=0.25, kernel=BandKernel()),
    SegmentSpec(name="market_behaviour", weight=0.25, kernel=BandKernel()),
    SegmentSpec(name="market_stress", weight=0.25,
                kernel=TailKernel(intensity_exponent=math.sqrt(2.0))),
)

#: ``w_Biz``, ``w_Invst``, ``w_Behav``, ``w_Stress`` (MRS_Tester.m, Market_Settings).
INDICATOR_WEIGHTS = {
    "business_cycle": {"inflation": 0.25, "monetary": 0.25, "consumer": 0.25, "company": 0.25},
    "investment": {"bond": 0.5, "equity": 0.5},
    "market_behaviour": {"trend_osc": 0.8, "fear_greed": 0.2},
    "market_stress": {"global_stability": 1 / 3, "market_stability": 1 / 3,
                      "monetary_uncertainty": 1 / 3},
}

MATLAB_INDICATORS = IndicatorParams(
    mode="matlab",
    weights=INDICATOR_WEIGHTS,
    fear_greed_series="volatility.fear_barometer",
    inflation_fx_series="fx.beer",
    bond_hy_series="yields.high_yield_index",
    thresholds=StressThresholds(vix_level=20.0, vix_accel=2.0, loan_move=0.10,
                                loan_change="price"),
)

PRODUCTION_INDICATORS = IndicatorParams(
    mode="production",
    weights=INDICATOR_WEIGHTS,
    min_history_input=24,
    min_history_composite=12,
    fear_greed_series="volatility.skew",
    inflation_fx_series="fx.neer_broad",
    bond_hy_series="yields.high_yield_ytw",
    thresholds=StressThresholds(vix_level=0.20, vix_accel=0.02, loan_move=0.005,
                                loan_change="relative"),
)

PRODUCTION = Calibration(
    version="2.0.0",
    note=("Production. Market_Signal.m with the owner's rulings of 27.09.2026: z-scores and "
          "trends on data up to each month (24 months for inputs, 12 for combinations), gaps "
          "kept as gaps and read as the average inside an indicator, the replacement inputs "
          "(MRS-15) and thresholds in data units (MRS-16). Zero optimism shift. A missing "
          "segment is dropped and the others re-weighted; three of four segments needed."),
    edges=Edges(low=-2.0, high=2.0, count=11),
    segments=SEGMENTS,
    missing_policy="reweight",
    min_segments=3,
    indicators=PRODUCTION_INDICATORS,
)

MATLAB = Calibration(
    version="2.0.0-matlab",
    note=("Reproduces Market_Signal.m (MRS_Tester.m) on MATLAB's view of M_TS: full-sample "
          "normalisation, MATLAB inputs, units and thresholds, and a missing segment reading "
          "selects column 1, as the MATLAB comparisons do with NaN. Zero optimism shift. "
          "For the golden reconciliation only, not for publication."),
    edges=Edges(low=-2.0, high=2.0, count=11),
    segments=SEGMENTS,
    missing_policy="matlab",
    min_segments=1,
    indicators=MATLAB_INDICATORS,
)

SEEDS: tuple[Calibration, ...] = (MATLAB, PRODUCTION)

#: The v0.1.0 seeds (``mrs-calibration@1.0.0``), kept for the record only. Their grid and
#: kernels are those of the live seeds; they carried optimism shifts and market blends,
#: which moved to ``aggregation`` (MRS-13, MRS-18). ``optimism_sign`` is the direction the
#: optimism shift moved each segment's grid: ``Weights.m`` for 0.1.0-matlab and 1.0.0, all
#: +1 in 1.1.0 (MRS-12).
_OPTIMISM = {"defensive": 0.0, "default": 0.4, "aggressive": 0.8, "rogue": 1.2}
_MARKETS = {
    "americas": {"CN": 0.1, "EU": 0.2, "US": 0.6, "BR": 0.05, "GB": 0.05},
    "europe": {"CN": 0.1, "EU": 0.4, "US": 0.2, "CH": 0.15, "GB": 0.15},
    "asia": {"CN": 0.55, "EU": 0.05, "IN": 0.25, "US": 0.15},
    "sino": {"CN": 0.7, "EU": 0.1, "US": 0.2},
    "global": {"CN": 0.2, "EU": 0.25, "IN": 0.05, "US": 0.3, "CH": 0.05, "BR": 0.05, "GB": 0.1},
    "equal": {"CN": 0.25, "EU": 0.25, "IN": 0.25, "US": 0.25},
}
#: ``Weights.m``: ``scale + grid`` for business cycle and stress, ``-scale + grid`` for
#: investment and market behaviour.
WEIGHTS_M_OPTIMISM_SIGN = {"business_cycle": 1, "investment": -1, "market_behaviour": -1,
                           "market_stress": 1}
RETIRED: dict[str, dict] = {
    version: {
        "contract_version": "mrs-calibration@1.0.0", "version": version,
        "parent_version": parent, "missing_policy": policy, "min_segments": min_segments,
        "optimism": _OPTIMISM, "markets": _MARKETS, "min_market_weight": 0.5,
        "optimism_sign": signs,
    }
    for version, parent, policy, min_segments, signs in (
        ("0.1.0-matlab", None, "matlab", 1, WEIGHTS_M_OPTIMISM_SIGN),
        ("1.0.0", None, "reweight", 3, WEIGHTS_M_OPTIMISM_SIGN),
        ("1.1.0", "1.0.0", "reweight", 3, {k: 1 for k in WEIGHTS_M_OPTIMISM_SIGN}),
    )
}


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
