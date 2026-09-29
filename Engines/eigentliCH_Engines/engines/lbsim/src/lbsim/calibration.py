"""The seed calibrations (LBSIM-13): 1.0.0 reproduces the draft; 1.1.0 is lbsim's behaviour; 1.2.0 corrects the
draft's income paths (DECISIONS P-9); 1.3.0 carries the owner's plan settings (DECISIONS O-18: 500 iterations, a
10-year solve horizon) and is active.

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

SEED_1_1 = Calibration(
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

#: 1.1.0 with the draft's income paths corrected (DECISIONS P-9, 29.09.2026): the `today` path keeps today's level
#: (it moved to about twice it in five years through the draft's autonomous expertise growth), and a path's
#: pensum applies from today when no education is planned (the draft applied it only after an education, so
#: `full_pensum` and `network` equalled `today` for everyone without one). Active.
SEED_1_2 = SEED_1_1.model_copy(update={
    "version": "1.2.0", "parent_version": "1.1.0",
    "note": ("1.1.0 with the income paths corrected (DECISIONS P-9): a path is credited only with the expertise and "
             "network its own education and networking add, never the draft's autonomous growth, and a path's "
             "pensum applies from today when no education is planned. A network path that adds nothing is left "
             "out, as the draft leaves out education paths without an education."),
    "behaviour": SEED_1_1.behaviour.model_copy(update={"income_paths": "corrected"}),
})
SEED_1_2 = Calibration.model_validate(SEED_1_2.model_dump())

#: 1.2.0 with the owner's plan settings of 29.09.2026 (DECISIONS O-18): at most 500 IPOPT iterations and a solve
#: horizon of 10 years (0.5-year steps throughout; a goal beyond year 10 is the zero-return terminal requirement at
#: the cap). Only the optimiser block differs, so the findings are 1.2.0's. Active.
SEED_1_3 = SEED_1_2.model_copy(update={
    "version": "1.3.0", "parent_version": "1.2.0",
    "note": ("1.2.0 with the owner's plan settings (DECISIONS O-18): at most 500 IPOPT iterations per solve and a "
             "solve horizon of 10 years on 0.5-year steps; a goal beyond year 10 is read as the zero-return terminal "
             "requirement at the cap. The findings and the paths are 1.2.0's."),
    "optimiser": SEED_1_2.optimiser.model_copy(update={"max_iter": 500, "max_solve_horizon_years": 10.0,
                                                       "grid": ((10.0, 0.5),)}),
})
SEED_1_3 = Calibration.model_validate(SEED_1_3.model_dump())

#: 1.3.0 with the paths' household retiring as the findings assume (DECISIONS P-21 to P-24, 29.09.2026): the stated
#: stop age as stated, pillar 2 an annuity and pillar 3a paid out when work stops (not before the reference age),
#: the employee's half of the pillar-2 contribution from a stated salary, capital goals judged and not paid out.
#: Only the paths move; the findings and the plan settings are 1.3.0's. Active.
SEED_1_4 = SEED_1_3.model_copy(update={
    "version": "1.4.0", "parent_version": "1.3.0",
    "note": ("1.3.0 with the paths' household retiring as the findings assume (DECISIONS P-21 to P-24): the stated "
             "stop age as stated; from the later of the stop age and the reference age pillar 2 is an annuity at the "
             "findings' conversion rate and pillar 3a is paid out; a stated salary pays the employee's half of the "
             "pillar-2 contribution; a capital goal is judged, not paid out. The findings are 1.3.0's."),
    "behaviour": SEED_1_3.behaviour.model_copy(update={"paths_household": "pensions"}),
})
SEED_1_4 = Calibration.model_validate(SEED_1_4.model_dump())

#: 1.4.0 with each stated income where it belongs (DECISIONS P-25, 29.09.2026): until an education ends a path runs
#: at today's stated income and pensum, and from the end year the stated expectation applies at the path's pensum,
#: never raised by a pensum above 1 (it is stated at a full pensum). Without a stated education there is no
#: education path. Active.
ACTIVE_SEED = SEED_1_4.model_copy(update={
    "version": "1.5.0", "parent_version": "1.4.0",
    "note": ("1.4.0 with each stated income where it belongs (DECISIONS P-25): until an education ends, and on the "
             "path without one always, today's stated income at today's pensum; from the education's end year the "
             "stated expectation at the path's pensum, never raised by a pensum above 1 because it is stated at a "
             "full pensum; no education path without a stated education."),
    "behaviour": SEED_1_4.behaviour.model_copy(update={"income_levels": "stated"}),
})
ACTIVE_SEED = Calibration.model_validate(ACTIVE_SEED.model_dump())

SEEDS: tuple[Calibration, ...] = (SEED, SEED_1_1, SEED_1_2, SEED_1_3, SEED_1_4, ACTIVE_SEED)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in."""
    payload = calibration.model_dump(mode="json")
    for key in ("income_paths", "paths_household", "income_levels"):
        if payload["behaviour"].get(key) is None:
            payload["behaviour"].pop(key, None)
    if payload["optimiser"].get("max_solve_horizon_years") is None:
        payload["optimiser"].pop("max_solve_horizon_years", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
