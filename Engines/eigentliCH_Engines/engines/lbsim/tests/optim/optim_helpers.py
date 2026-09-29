"""Shared builders for the optimiser tests: a PlanProblem from B1's sample household and the frozen upstream
figures, and a stand-in for B2's Monte Carlo.

How to run the optimiser's tests (agent C). Two lanes. From the lbsim folder:

    default   timeout 900 ../../.venv/Scripts/python -X utf8 -m pytest -q -p no:warnings tests/optim
              (``pyproject.toml`` deselects ``slow``: parity, grid, market, the clock, cancelling, the seeds and
              the wiring of the out-of-sample chance; the solves that run are stopped within seconds)
    slow      ../../.venv/Scripts/python -X utf8 -m pytest -q -p no:warnings -m slow --dist loadfile -n 4 tests/optim
              (every real solve: the draft reproduction, the end-to-end plans, the unfundable goal, the 20-year
              case, the receding-horizon loop; about 2 hours, most of it the 20-year case)

``--dist loadfile`` is required with ``-n``, for the draft's reason: ``test_optim_reproduce_draft.py`` shares one
module-scoped solve (``sol_90``) across its tests, and ``--dist load`` would scatter them over workers and solve it
once per worker. ``-n 4`` because the slow lane has two modules worth spreading. ``-n`` needs pytest-xdist, which
the family venv does not carry (29.09.2026); without it run the slow lane serially, ``-m slow`` alone.
IPOPT with MUMPS uses one core per solve, so four workers use four cores.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np

from lbsim.adapter import adapt
from lbsim.calibration import ACTIVE_SEED, SEED
from lbsim.contracts import Calibration, LbsRequest, LbsSheet
from lbsim.optim.types import GoalInput, MarketInputs, PlanProblem

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "golden"
UPSTREAM = GOLDEN / "samples" / "upstream"
CASES = GOLDEN / "lbs_cases"
OPTIM_GOLDEN = GOLDEN / "optim"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_market() -> MarketInputs:
    """The base Regime of the frozen upstream sample: renormalised Allocation weights on fmre's per-state
    profiles, fmre's CHF log inflation, and year 1 at ``curves.regime`` reverting linearly to the long-run
    distribution over ``market.reversion_years`` (LBSIM-07)."""
    alloc = load(UPSTREAM / "allocation.json")
    rs = load(UPSTREAM / "return_set_base.json")
    infl = load(UPSTREAM / "inflation_base.json")
    blends = load(UPSTREAM / "aggregation_blends.json")["blends"]["base"]
    w = {i["instrument_id"]: float(i["raw_weight"]) for i in alloc["instruments"]}
    total = sum(w.values())
    prof = {p["key"]: np.array([s["value"] for s in p["states"]]) for p in rs["instrument_profiles"]}
    r = sum((v / total) * prof[k] for k, v in w.items())
    li = np.array([s["log_inflation"] for s in infl["states"]])
    p0 = np.array(alloc["curves"]["regime"], dtype=float)
    plr = np.array(blends["long_run"], dtype=float)
    years = ACTIVE_SEED.market.reversion_years
    dists = tuple(tuple(float(a) for a in (p0 + (plr - p0) * min(y / years, 1.0))) for y in range(0, 7))
    return MarketInputs(kind="allocation", log_returns=tuple(float(a) for a in r),
                        log_inflation=tuple(float(a) for a in li), state_distribution=dists,
                        regime_id=alloc["regime_id"], return_set_id=alloc["return_set_id"])


def sample_goals(confidence: float = 0.90) -> tuple[GoalInput, list[GoalInput], float, dict]:
    """The sample's two goals as the paths sample states them, with the fast half's free cash (path ``today``)."""
    paths = load(GOLDEN / "samples" / "paths.sample.json")
    findings = load(GOLDEN / "samples" / "findings.sample.json")
    free = {s["goal_id"]: s["free_cash_chf_per_year"]
            for s in next(p for p in findings["income_paths"] if p["code"] == paths["income_path"])["saving_need"]}
    as_of = date.fromisoformat(findings["as_of"])
    base = next(r for r in paths["regimes"] if r["key"] == "base")
    goals = []
    for g in base["goals"]:
        t = g["target"]
        years = float(date.fromisoformat(t["date"]).year - as_of.year)
        goals.append(GoalInput(goal_id=g["goal_id"], kind=g["kind"], horizon_years=years, confidence=confidence,
                               measure=g["measure"], target_nominal_chf=t["nominal_chf"],
                               target_real_chf=t["real_chf"], amount_basis=t["amount_basis"],
                               planned_saving_chf_per_year=float(free.get(g["goal_id"], 0.0))))
    return goals[0], goals[1:], float(paths["horizon_years"]), {"paths": paths, "findings": findings}


def sample_submission(calibration: Calibration = ACTIVE_SEED) -> dict:
    sheet = load(CASES / "lbsim-sample" / "sheet.json")
    request = load(CASES / "lbsim-sample" / "request.json")
    records = load(CASES / "records.json")["records"]
    return adapt(LbsSheet.model_validate(sheet), LbsRequest.model_validate(request), records,
                 calibration).submission


def with_optimiser(cal: Calibration, **changes) -> Calibration:
    return cal.model_copy(update={"optimiser": cal.optimiser.model_copy(update=changes)})


def sample_problem(*, calibration: Calibration = ACTIVE_SEED, horizon: Optional[float] = None,
                   goal_years: Optional[float] = None, extra: bool = True, seed: int = 20260929,
                   n_out_of_sample: Optional[int] = None, goal_target: Optional[float] = None) -> PlanProblem:
    goal, extras, total, _ = sample_goals(calibration.optimiser.confidence)
    if goal_years is not None:
        goal = replace(goal, horizon_years=goal_years)
    if goal_target is not None:
        goal = replace(goal, target_nominal_chf=goal_target, target_real_chf=goal_target)
    market = sample_market() if calibration.behaviour.market == "allocation" else MarketInputs(kind="draft")
    return PlanProblem(submission=sample_submission(calibration), calibration=calibration, market=market,
                       goal=goal, extra_goals=tuple(extras) if extra else (),
                       horizon_years=float(horizon if horizon is not None else total), seed=seed,
                       n_out_of_sample=n_out_of_sample, client_ref="bench",
                       life_balance_sheet_id=None, paths_artefact_id=None)


class StandInSimulate:
    """B2's Monte Carlo is not the optimiser's to build: this records its calls and answers a fixed figure."""

    def __init__(self, chance: float = 0.8765, shortfall: float = 1234.5):
        self.calls: list[dict] = []
        self.chance = chance
        self.shortfall = shortfall

    def __call__(self, problem, controls, n_paths, seed):
        self.calls.append({"problem": problem, "controls": controls, "n_paths": n_paths, "seed": seed})
        return {"chance": self.chance, "n_reached": int(round(self.chance * n_paths)),
                "shortfall_cvar_chf": self.shortfall}


def no_deadline(hours: float = 3.0) -> float:
    return time.monotonic() + hours * 3600.0


def never() -> bool:
    return False


def quiet(_event: dict) -> None:
    return None


__all__ = ["ACTIVE_SEED", "SEED", "StandInSimulate", "load", "no_deadline", "never", "quiet", "sample_goals",
           "sample_market", "sample_problem", "sample_submission", "with_optimiser"]
