"""The plan run's inputs and outputs around the optimiser (the handshake with agent C, fixed 29.09.2026).

    lbsim.optim.solve(problem: PlanProblem, *, simulate, deadline, should_cancel, progress) -> PlanOutcome

* :func:`plan_problem` builds the ``PlanProblem`` from the paths the plan is for: the adapter's submission (the
  household as the findings read it), the calibration, the base Regime's market as the Monte Carlo reads it
  (per-state returns and inflation, the year-by-year state distribution), the designated goal and every other
  dated goal with their targets in both bases (LBSIM-09) and the path's free cash (the saving at which a goal
  beyond the solve cap is read as a zero-return terminal requirement, section 5).
* :func:`simulate` is lbsim's vectorised Monte Carlo under the planned controls, handed to ``solve`` for the
  out-of-sample chance. It reads the household exactly as the optimiser's ``run.household`` does (the draft's
  converter: the habit starts at ``swr`` times net worth) and the market from ``problem.market``, on the random
  streams of section 3.9.
* :func:`plan_artefact` turns a succeeded ``PlanOutcome`` into ``LifeBalancePlan``; a failed one has no artefact.

Only the worker calls these (LBSIM-03): ``lbsim.optim`` is imported inside the functions, never at module load.
"""

from __future__ import annotations

import math
from importlib import metadata
from typing import Any, Optional

import numpy as np

from . import ENGINE_VERSION
from .calibration import calibration_hash, tables
from .contracts import (CONTRACT_VERSIONS, Calibration, LifeBalanceFindings, LifeBalancePaths, LifeBalancePlan,
                        Provenance, Words)
from .fast import gameplan as _gameplan
from .ids import content_id
from .paths import engine as E
from .paths.household import STATE_DEFAULTS, StatedPlan
from .paths.market import Draws, YearTable, draws, path_market, year_table
from .upstream import MarketBundle

FRAMING = Words(
    de=("Was die Rechnung annimmt: diese Zahlen beschreiben, womit die Planrechnung für diese Periode rechnet. Sie "
        "sind keine Empfehlung."),
    en=("What the calculation assumes: these figures describe what the plan calculation works with for this period. "
        "They are not a recommendation."))


def casadi_version() -> Optional[str]:
    """The installed casadi's version, read from its metadata without importing it (the API never imports it)."""
    try:
        return metadata.version("casadi")
    except metadata.PackageNotFoundError:
        return None


def optimiser_hash(calibration: Calibration) -> str:
    return content_id("CAL", calibration.optimiser.model_dump(mode="json"))


def plan_key(paths: LifeBalancePaths, findings_key: str, calibration: Calibration, seed: int) -> str:
    """Section 3.9: the paths inputs less ``n_paths``, plus the optimiser block's hash, the seed, casadi's version.
    ``requested_by`` is not in the key. Read from the paths artefact alone, so the API can key a request."""
    fmre = paths.provenance.upstream.get("fmre") or {}
    numpy_minor = ".".join(str(paths.provenance.numpy_version or "").split(".")[:2])
    return content_id("IDK", {
        "kind": "plan", "findings": findings_key, "allocation_id": paths.allocation_id,
        "regimes": [[r.key, r.regime_id] for r in paths.regimes], "return_set_ids": fmre.get("return_set_ids"),
        "inflation_sha256": fmre.get("inflation_sha256"), "ipt_id": fmre.get("ipt"),
        "horizon_years": paths.horizon_years, "income_path": paths.income_path, "numpy": numpy_minor,
        "paths_seed": paths.seed, "optimiser": optimiser_hash(calibration), "seed": int(seed),
        "casadi": casadi_version()})


# --- the problem -------------------------------------------------------------------------------------------

def base_table(bundle: MarketBundle, years: int, calibration: Calibration) -> YearTable:
    base = bundle.regimes[0]
    return year_table(base, base, years, calibration.market)


def plan_problem(*, paths: LifeBalancePaths, plan: StatedPlan, bundle: MarketBundle, calibration: Calibration,
                 designated: Optional[str], seed: int, max_solve_horizon_years: float):
    from .optim import types as T  # noqa: PLC0415 - the worker only

    if not plan.goals:
        raise ValueError("no dated goal within the horizon, so there is nothing for the plan calculation to fund")
    table = base_table(bundle, plan.horizon_years, calibration)
    base = bundle.regimes[0]
    market = T.MarketInputs(kind="allocation", log_returns=tuple(map(float, base.curve.log_return)),
                            log_inflation=tuple(map(float, base.curve.log_inflation)),
                            state_distribution=tuple(tuple(map(float, row)) for row in table.dist),
                            regime_id=base.regime_id, return_set_id=base.return_set_id)
    ordered = sorted(plan.goals, key=lambda g: (g.goal_id != designated, g.year))
    goals = [T.GoalInput(goal_id=g.goal_id, kind=g.kind, horizon_years=float(g.year),
                         confidence=calibration.optimiser.confidence, measure=g.measure,
                         target_nominal_chf=float(g.target_nominal), target_real_chf=float(g.target_real),
                         amount_basis=g.amount_basis, planned_saving_chf_per_year=float(g.free_cash_real))
             for g in ordered]
    return T.PlanProblem(submission=plan.submission, calibration=calibration, market=market, goal=goals[0],
                         horizon_years=float(plan.horizon_years), seed=int(seed), extra_goals=tuple(goals[1:]),
                         max_solve_horizon_years=float(max_solve_horizon_years), n_out_of_sample=int(paths.n_paths),
                         client_ref=paths.client_ref, life_balance_sheet_id=paths.life_balance_sheet_id,
                         paths_artefact_id=paths.artefact_id)


# --- lbsim's Monte Carlo under the planned controls ----------------------------------------------------------

def household_of(problem) -> E.Household:
    """The optimiser's reading of the household (``optim.run.household``): the submission's state with the draft's
    mid-scale defaults, ``Params`` through the fast half's ``_params_from``, the habit at ``swr`` times net worth."""
    sub = problem.submission
    s = dict(sub.get("state") or {})
    with tables(problem.calibration):
        p = _gameplan._params_from(dict(sub))
    W_L, W_R, D = float(s.get("W_L") or 0.0), float(s.get("W_R") or 0.0), float(s.get("D") or 0.0)
    x0 = {"W_L": W_L, "W_R": W_R, "D": D,
          **{k: float(s[k]) if s.get(k) is not None else v for k, v in STATE_DEFAULTS.items()},
          "age": float(s["age"]), "W_res": float(s.get("W_res") or 0.0), "W_hol": float(s.get("W_hol") or 0.0),
          "W_P": float(s.get("W_P") or 0.0), "W_3a": float(s.get("W_3a") or 0.0),
          "kappa": p.swr * (W_L + W_R - D)}
    return E.Household(x0=x0, p=p)


def monthly_controls(controls, years: int, steps_per_year: int = 12) -> np.ndarray:
    """A ``ControlPath`` (the variable grid, the last step held) as the engine's monthly schedule."""
    out = np.zeros((years * steps_per_year, len(E.CONTROL_NAMES)))
    for m in range(len(out)):
        u = controls.at(m / steps_per_year)
        out[m] = [float(u[n]) for n in E.CONTROL_NAMES]
    return out


def _solved_years(controls) -> float:
    last = controls.steps[-1]
    return float(last.t_years + last.dt_years)


def simulate(problem, controls, n_paths: int, seed: int) -> dict[str, Any]:
    """The designated goal's chance under ``controls`` on ``n_paths`` fresh paths from ``seed``.

    A goal within the solved horizon is judged at its date; a goal beyond it at the end of the solved horizon
    against its zero-return terminal requirement (the target less the planned saving over the remaining years).
    Returns ``chance``, ``n_reached`` and ``shortfall_cvar_chf`` (the mean shortfall of the worst ``1 -
    confidence`` share of paths, in the goal's basis), and the base Regime's measure quantiles for the record.
    """
    goal = problem.goal
    cal = problem.calibration
    h = household_of(problem)
    solved = _solved_years(controls)
    at_year = int(max(1, round(min(float(goal.horizon_years), solved + 1e-9))))
    beyond = max(0.0, float(goal.horizon_years) - solved)
    if goal.amount_basis == "today":
        target = goal.target_real_chf if goal.target_real_chf is not None else goal.target_nominal_chf
    else:
        target = goal.target_nominal_chf
    requirement = max(0.0, float(target) - float(goal.planned_saving_chf_per_year) * beyond)
    ctl = monthly_controls(controls, at_year)
    event = E.GoalEvent(goal_id=goal.goal_id, kind=goal.kind if goal.kind in ("home", "retirement", "capital")
                        else "capital", measure=goal.measure or "drawable", year=at_year,
                        basis="real" if goal.amount_basis == "today" else "nominal", target=requirement,
                        execute=False)
    h = E.Household(x0=h.x0, p=h.p, events=(event,))
    if problem.market.kind == "allocation":
        m = problem.market
        dist = [np.asarray(r, dtype=float) for r in m.state_distribution] or [np.full(25, 1 / 25)]
        rows = np.array([dist[min(k, len(dist) - 1)] for k in range(at_year)])
        table = YearTable(dist=rows, log_return=np.tile(np.asarray(m.log_returns, dtype=float), (at_year, 1)),
                          log_inflation=np.tile(np.asarray(m.log_inflation, dtype=float), (at_year, 1)),
                          scenario_years=None)
        d = draws(seed, n_paths, at_year, persistence=cal.market.state_persistence)
        pm = path_market(table, d, cal.property, persistence=cal.market.state_persistence)
        res = E.simulate(h, ctl, n_paths=n_paths, market="allocation", path_market=pm)
    else:
        rng = np.random.default_rng(np.random.SeedSequence(int(seed)).spawn(3)[0])
        noise = rng.standard_normal((len(ctl), n_paths, 2))
        res = E.simulate(h, ctl, n_paths=n_paths, market="draft", noise=noise)
    out = res.goals[goal.goal_id]
    reached = out["reached"]
    eps = max(0.01, min(0.5, 1.0 - float(goal.confidence)))
    tail = np.sort(out["shortfall"])[::-1][:max(1, int(math.ceil(eps * n_paths)))]
    return {"chance": float(np.mean(reached)), "n_reached": int(np.sum(reached)),
            "shortfall_cvar_chf": float(np.mean(tail)), "judged_at_year": at_year,
            "requirement_chf": requirement, "basis": event.basis}


# --- the artefact ---------------------------------------------------------------------------------------------

def plan_artefact(outcome, *, paths: LifeBalancePaths, calibration: Calibration, key: str,
                  findings: LifeBalanceFindings) -> LifeBalancePlan:
    r = outcome.result
    steps = [{"t_years": s.t_years, "dt_years": s.dt_years,
              "controls": {n: float(s.controls[n]) for n in ("tau_Y", "tau_E", "tau_N", "tau_H", "C", "m_E", "m_N",
                                                             "p_A")}}
             for s in r.control_path.steps]
    seeds = {"in_sample": int(r.solver.seed), "out_of_sample": int(r.chance.seed_out)}
    for i, s in enumerate(r.seeds_used):
        seeds[f"used_{i}"] = int(s)
    provenance = Provenance(
        engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS, calibration_version=calibration.version,
        calibration_hash=calibration_hash(calibration), idempotency_key=key,
        upstream={"paths": paths.artefact_id, "findings": findings.artefact_id,
                  "lbs": paths.provenance.upstream.get("lbs"), "pcp": paths.provenance.upstream.get("pcp")},
        records=findings.provenance.records, seeds=seeds, numpy_version=np.__version__)
    fields = dict(
        client_ref=paths.client_ref, life_balance_sheet_id=paths.life_balance_sheet_id,
        paths_artefact_id=paths.artefact_id, calibration_version=calibration.version, outcome=r.outcome,
        goal={"goal_id": r.goal_id, "kind": r.goal_kind, "confidence": r.confidence},
        extra_goals=tuple(r.extra_goals), action_now=_plain(r.action_now), framing=FRAMING,
        chance=_plain(r.chance), shortfall_cvar_chf=float(r.shortfall_cvar_chf),
        reachable=_plain(r.reachable) if r.reachable is not None else None,
        exchange_rate=_plain(r.exchange_rate), costates=_plain(r.costates), control_path=tuple(steps),
        horizon=_plain(r.horizon), solver={**_plain(r.solver), "grid": tuple(r.solver.grid)}, provenance=provenance)
    draft = LifeBalancePlan(artefact_id="LSO-" + "0" * 16, **fields)
    body = draft.model_dump(mode="json", exclude={"artefact_id"})
    return LifeBalancePlan(artefact_id=content_id("LSO", body), **fields)


def _plain(obj) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass  # noqa: PLC0415

    return asdict(obj) if is_dataclass(obj) else dict(obj)
