"""Calibration: blend weights, tilts, kernels, optimism targets and market blends, nothing else.

Every figure of ``1.0.0`` is the first draft's, from
``Projects/eigentliCH/engines/Macro_Model/config/defaults.yaml`` as shipped (the corrected
kernels of decisions M56 and 3 August 2026, the tilts of calibration round A, the cycle weight
0.20 of M53/M57); the market blends are ``Market_Signal.m``'s ``CRS.cw`` keyed by datafeed
country codes, as ``mrs`` carried them, plus ``EMCN`` from ``MRS_Tester.m``.

``1.0.0``
    The first draft's combination rule, reproduced (golden layer A). No optimism shift, no
    carry: a month whose year has no macro reading is not assessed.

``1.1.0``
    1.0.0 with the optimism level applied to the combined distribution
    (AGG-05; targets at neutral readings Defensive 10, Default 14, Aggressive 19, Rogue 24,
    the proposal of the task "Aggregation: optimism levels and the Rogue targets") and the
    last annual macro reading carried for up to 24 months, flagged (AGG-07).

``1.2.0``
    The active version. 1.1.0 with the crisis tail kept in place under optimism (AGG-15);
    targets and carry confirmed by the owner on 28.09.2026.

A seed can never be changed in place. To change a figure, propose a new version through
``PUT /calibration``; the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Blend, Calibration, Kernels, MacroTilts, Optimism, Reading

#: Draft ``regime.kernels`` (percentages), both corrected at position 9 / 5 (12.0 -> 13.0).
SYMMETRIC = (1.5, 2.0, 4.9, 6.0, 8.9, 13.0, 13.7, 13.7, 13.0, 8.9, 6.0, 4.9, 2.0, 1.5)
CRISIS = (14.4, 21.9, 13.7, 13.7, 13.0, 8.9, 6.0, 4.9, 2.0, 1.5)
PLACEMENT = {"crisis": 1, "contraction": 2, "stagnation": 6, "expansion": 11, "boom": 16}

#: Draft ``saa.tilts``.
TILT_COEFFICIENTS = {
    "base": 1.0,
    "saturation_above_band": 1.2,
    "saturation_below_band": 0.8,
    "real_to_financial_below_one": 1.5,
    "unsecured_rising": 2.0,
    "interference": 1.0,
    "alignment_gain": 1.0,
    "capital_overdue_per_decade": 0.8,
    "innovation_approach_per_decade": 0.4,
}

FIVE_REGIME_BINS = {"Crisis": (1, 5), "Contraction": (6, 10), "Stagnation": (11, 15),
                    "Expansion": (16, 20), "Boom": (21, 25)}

#: ``Market_Signal.m``, the ``market`` switch (``CRS.cw``); ``equal`` is its fallback branch.
#: ``EMCN``, emerging markets ex China, from ``MRS_Tester.m``. Zero weights are left out.
MARKETS = {
    "americas": {"CN": 0.1, "EU": 0.2, "US": 0.6, "BR": 0.05, "GB": 0.05},
    "europe": {"CN": 0.1, "EU": 0.4, "US": 0.2, "CH": 0.15, "GB": 0.15},
    "asia": {"CN": 0.55, "EU": 0.05, "IN": 0.25, "US": 0.15},
    "sino": {"CN": 0.7, "EU": 0.1, "US": 0.2},
    "global": {"CN": 0.2, "EU": 0.25, "IN": 0.05, "US": 0.3, "CH": 0.05, "BR": 0.05, "GB": 0.1},
    "equal": {"CN": 0.25, "EU": 0.25, "IN": 0.25, "US": 0.25},
    "EMCN": {"IN": 0.6, "BR": 0.2, "ID": 0.05, "MY": 0.05, "PH": 0.05, "TH": 0.05},
}

#: The modal state of the market risk signal at neutral readings and zero shift (task
#: "Aggregation: optimism levels and the Rogue targets": Defensive, at zero shift, reads 12).
REFERENCE_STATE = 12

DRAFT = Calibration(
    version="1.0.0",
    note=("The first draft's combination rule (Macro_Model saa_signal.merge, regime.py, "
          "regime_timeline.build_timeline): 50% macro to 50% market risk signal, then the cycle "
          "layer at 20%, linear in bin space. No optimism shift, no carry."),
    blend=Blend(macro=0.5, cycle=0.20, cycle_missing="reweight"),
    kernels=Kernels(symmetric=SYMMETRIC, crisis=CRISIS, placement=PLACEMENT),
    tilts=MacroTilts(coefficients=TILT_COEFFICIENTS, adjacent_share=0.6,
                     innovation_window_years=20.0, band_lower=2.5, band_upper=3.5,
                     saturation_ceiling=6.0),
    optimism=Optimism(reference_state=REFERENCE_STATE,
                      targets={"defensive": 12, "default": 12, "aggressive": 12, "rogue": 12}),
    reading=Reading(mode_prominence=0.25, lean_bins=2.0, tail_bins=5,
                    minimum_tail_probability=0.01, five_regime_bins=FIVE_REGIME_BINS),
    carry_months=0,
    markets=MARKETS,
)

OPTIMISM_LEVELS = Calibration.model_validate({
    **DRAFT.model_dump(),
    "version": "1.1.0",
    "parent_version": "1.0.0",
    "note": ("1.0.0 with the optimism level applied to the combined distribution (AGG-05: "
             "Defensive 10, Default 14, Aggressive 19, Rogue 24 at neutral readings) and the "
             "last annual macro reading carried for up to 24 months, flagged (AGG-07)."),
    "optimism": {"reference_state": REFERENCE_STATE,
                 "targets": {"defensive": 10, "default": 14, "aggressive": 19, "rogue": 24}},
    "carry_months": 24,
})

#: AGG-15, owner's ruling of 28.09.2026: the crisis tail (states 1 to 5) stays in place and only
#: the rest of the distribution moves, so the crisis regime stays live at every level.
TAIL_KEPT = Calibration.model_validate({
    **OPTIMISM_LEVELS.model_dump(),
    "version": "1.2.0",
    "parent_version": "1.1.0",
    "note": ("1.1.0 with the crisis tail (the 5 most cautious states) kept in place under "
             "optimism; only the rest of the distribution moves (AGG-15). Targets and carry as 1.1.0, "
             "confirmed by the owner on 28.09.2026."),
    # Solved so that the neutral reading's published state lands on the targets with the tail
    # kept (tests.test_engine.test_neutral_reading_lands_on_the_targets).
    "optimism": {**OPTIMISM_LEVELS.optimism.model_dump(), "keep_tail": 5,
                 "shifts": {"defensive": -1.75, "default": 2.37, "aggressive": 7.52, "rogue": 13.6}},
})

SEEDS: tuple[Calibration, ...] = (DRAFT, OPTIMISM_LEVELS, TAIL_KEPT)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
