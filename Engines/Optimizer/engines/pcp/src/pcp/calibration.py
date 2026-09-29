"""Calibration: vocabularies, ingest maps, solver settings, the budget check and the instrument
classification table, nothing else.

Every figure of ``1.0.0`` is the eigentliCH PCP draft's, from
``Projects/eigentliCH/engines/PCP/config/defaults.yaml`` (vocabularies, ingest maps, solver: SLSQP from 0.5
everywhere with trust-constr as the fallback, fast ftol 1e-3 / 300 iterations, exact ftol 1e-8 / 3000). The
classification table (``seed_classification.json``) is the prototype's published 54-instrument universe, the
file ``fmre``'s register was imported from (PCP-06).

``1.0.0``
    The draft reproduced, including its budget check ``round(sum(raw), 1) == 1`` (golden layer A).

``1.1.0``
    The active version. 1.0.0 with the budget read from the raw weights to 1e-6 (Manual section 15.2:
    "leverage is read from the raw solution, before renormalisation"; the legacy check accepts any sum from
    0.95 to 1.05), PCP-08.

A seed can never be changed in place. To change a figure, propose a new version through ``PUT /calibration``;
the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources

from .contracts import (
    BudgetCheck,
    Calibration,
    InstrumentClass,
    ObjectiveSpec,
    SolverSpec,
    SpeedSpec,
    Vocabularies,
)

#: The draft's vocabularies (``defaults.yaml``). Order fixes the constraint rows.
VOCABULARIES = Vocabularies(
    currency=("CHF", "USD", "EUR", "RMB", "GBP", "JPY", "HKD", "AUD", "INR", "Others"),
    region=("Switzerland", "Europe", "East Asia", "South Asia", "North America", "South Pacific", "Others"),
    role=("Gain", "Income", "Stabilisation", "Protection"),
    capital_type=("Financial", "Real", "Others"),
    liquidity=("Daily", "Quarterly", "Yearly", "Decade"),
    phase=("Foundation", "Build-up", "Optimisation", "Saturation"),
    asset_class=("Cash", "Fixed Income", "Equity", "Real Assets", "Alternative"),
    scenario=("Crisis", "Contraction", "Stagnation", "Expansion", "Boom"),
)

#: Unknown currencies, regions and capital types fold into ``Others`` (the draft's catch-alls); every other
#: dimension refuses an unknown value.
CATCH_ALL = {"currency": "Others", "region": "Others", "capital_type": "Others"}

#: The draft's ingest maps, plus ``fmre``'s lower-case roles.
INGEST_MAPS = {
    "role": {"Growth": "Gain", "Stabilization": "Stabilisation", "gain": "Gain", "income": "Income",
             "stabilisation": "Stabilisation", "protection": "Protection"},
    "phase": {"Maturing": "Build-up", "Optimizing": "Optimisation"},
    "asset_class": {"Real Estate": "Real Assets"},
}

SOLVER = SolverSpec(start_value=0.5, speeds={"fast": SpeedSpec(ftol=1e-3, maxiter=300),
                                              "exact": SpeedSpec(ftol=1e-8, maxiter=3000)})


def _classification() -> dict[str, InstrumentClass]:
    text = resources.files("pcp").joinpath("seed_classification.json").read_text(encoding="utf-8")
    table = json.loads(text)["instruments"]
    return {k: InstrumentClass(**v) for k, v in sorted(table.items())}


DRAFT = Calibration(
    version="1.0.0",
    note=("The eigentliCH PCP draft reproduced: the per-instrument shortfall objective, the draft's "
          "vocabularies and ingest maps, SLSQP from 0.5, and the legacy budget check round(sum, 1) == 1."),
    objective=ObjectiveSpec(form="per_instrument_shortfall", profile_scale=1.0),
    vocabularies=VOCABULARIES,
    catch_all=CATCH_ALL,
    ingest_maps=INGEST_MAPS,
    solver=SOLVER,
    budget_check=BudgetCheck(mode="rounded", decimals=1),
    classification=_classification(),
)

PRODUCTION = Calibration.model_validate({
    **DRAFT.model_dump(),
    "version": "1.1.0",
    "parent_version": "1.0.0",
    "note": ("1.0.0 with the budget read from the raw weights to 1e-6 (Manual section 15.2; the legacy "
             "check accepted 0.95 to 1.05), PCP-08."),
    "budget_check": {"mode": "absolute", "decimals": 1, "tolerance": 1e-6},
})

SEEDS: tuple[Calibration, ...] = (DRAFT, PRODUCTION)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
