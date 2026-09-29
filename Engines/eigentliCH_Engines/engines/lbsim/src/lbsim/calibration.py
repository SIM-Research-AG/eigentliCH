"""The seed calibrations (LBSIM-13): 1.0.0 reproduces the draft, 1.1.0 is lbsim's behaviour and is active.

``1.0.0``  The draft as it is: the draft's ``Params()`` (``earning_power_at_unit`` 0.75), no inflation, the
           draft's Gaussian market and tilt, and its ``cases.run_case`` solver settings (``M_opt`` 14,
           ``M_eval`` 400, three starts, two restore starts, ``max_iter`` 400, three seed retries, ``cvar_tol``
           1e-3, a half-year step up to ten years and a year beyond). Golden layer A holds the port to it.
``1.1.0``  1.0.0 with the three decisions of lbsim applied, each a switch in ``behaviour``:
           LBSIM-08 (the sheet's own inflation in the findings), LBSIM-11 (``earning_power_at_unit`` from lbs's
           ``human-capital`` record and the one earning-power computation's level), LBSIM-07 (the pcp Allocation
           on fmre's per-state profiles, theta fixed at 1; CHF only, LBSIM-14), the owner's plan confidence of
           0.90 and the variable plan grid of section 5. The withdrawal rate stays 3 % (owner, 29.09.2026), now
           named as an assumption on every figure resting on it.

Both carry the same three records: ``social-insurance`` and ``canton-tax`` (the draft's two tables, LBSIM-12)
and ``findings-text`` (LBSIM-17). The hashes of both seeds are pinned by a test: a changed seed is a new version.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterator

from .contracts import (Behaviour, Calibration, Market, Optimiser, PropertyParameters, Retirement)
from .model import bvg, canton

SEED_RECORDS = Path(__file__).resolve().parent / "seed_records"


def _record(name: str) -> dict[str, Any]:
    return json.loads((SEED_RECORDS / f"{name}.json").read_text(encoding="utf-8"))


def seed_records() -> dict[str, dict[str, Any]]:
    return {name: _record(name) for name in ("social-insurance", "canton-tax", "findings-text")}


#: The draft's solver settings (``cases.run_case`` and ``optim.problem.solve_case``), verbatim.
_DRAFT_OPTIMISER = dict(M_opt=14, M_eval=400, n_starts=3, restore_starts=2, max_iter=400, seed_retries=3,
                        cvar_tol=1e-3)

SEED = Calibration(
    version="1.0.0",
    note=("Reproduces the draft (personal_alm): Params() as shipped, no inflation, the draft's market and its "
          "run_case solver settings. Golden layer A."),
    records=seed_records(),
    params={},
    behaviour=Behaviour(inflation="none", earning_power="draft", market="draft", currencies=("CHF",)),
    retirement=Retirement(withdrawal_rate=0.03),
    market=Market(reversion_years=5.0, state_persistence=0.0, scenario_years=5, wage_pass_through=1.0,
                  spending_pass_through=1.0),
    property=PropertyParameters(nominal_log_growth=math.log(1.03), inflation_beta=0.8,
                                inflation_anchor_log=math.log(1.01), sigma=0.08, rho_with_market=0.30),
    optimiser=Optimiser(confidence=0.90, grid=((10.0, 0.5), (1000.0, 1.0)), grid_rule="draft_single_step",
                        **_DRAFT_OPTIMISER),
)

ACTIVE_SEED = Calibration(
    version="1.1.0",
    parent_version="1.0.0",
    note=("lbsim's behaviour: LBSIM-08 (the sheet's inflation in the findings), LBSIM-11 (earning_power_at_unit "
          "from lbs's human-capital record, the responsibility tier, the model level at the BFS 40-hour week), "
          "LBSIM-07 (the pcp Allocation on fmre's per-state profiles, theta 1; CHF only), the plan confidence "
          "0.90 and the variable grid (0.5-year steps to 10 years, 1-year steps to the 20-year cap). The "
          "withdrawal rate of 3 % is an assumption and named as one."),
    records=seed_records(),
    params={},
    behaviour=Behaviour(inflation="sheet", earning_power="record", market="allocation", currencies=("CHF",)),
    retirement=Retirement(withdrawal_rate=0.03),
    market=Market(reversion_years=5.0, state_persistence=0.0, scenario_years=5, wage_pass_through=1.0,
                  spending_pass_through=1.0),
    property=PropertyParameters(nominal_log_growth=math.log(1.03), inflation_beta=0.8,
                                inflation_anchor_log=math.log(1.01), sigma=0.08, rho_with_market=0.30),
    optimiser=Optimiser(confidence=0.90, grid=((10.0, 0.5), (20.0, 1.0)), grid_rule="variable",
                        **_DRAFT_OPTIMISER),
)

SEEDS: tuple[Calibration, ...] = (SEED, ACTIVE_SEED)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    return json.dumps(calibration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]


def seed(version: str) -> Calibration:
    for cal in SEEDS:
        if cal.version == version:
            return cal
    raise KeyError(f"no seed calibration {version!r}; the seeds are {[c.version for c in SEEDS]}")


def approved(record: dict[str, Any]) -> bool:
    """The prototype's gate: ``_about.provisional`` false and ``_about.published_by`` set."""
    about = record.get("_about") or {}
    return (about.get("provisional", True) is False) and bool(about.get("published_by"))


@contextlib.contextmanager
def tables(calibration: Calibration) -> Iterator[None]:
    """Run the block with the calibration's two tables in place of the draft's missing files (LBSIM-12)."""
    with bvg.use_table(calibration.records["social-insurance"]), \
            canton.use_table(calibration.records["canton-tax"]):
        yield
