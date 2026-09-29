"""The model, pure: typed in, typed out, no I/O, no clock, no network.

Three steps, each its own function so each can be tested alone:

1. :func:`classify`: every instrument into one bucket per dimension, plus its home scenario and ESG score.
   Upstream spellings go through the calibration's ingest maps; an unknown value folds into the dimension's
   catch-all where one exists and is refused otherwise.
2. :func:`blend_regime`: the client's regime distribution, the Regime's per-economy distributions at one
   month weighted by the mandate's economy weights (PCP-04). Every weighted economy must be assessed that
   month; none is dropped or re-weighted silently.
3. :func:`optimise`: the constraint block, the solve, and everything the Allocation reports.

``service.py`` gathers the inputs from the upstream engines and calls these; nothing here calls out.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping, Optional, Sequence

import numpy as np

from . import constraints as cons
from . import objective as obj
from .contracts import DIMENSIONS, BindingRow, BudgetCheck, Calibration, InstrumentClass, InstrumentOut, Regime
from .solver import Solve, rescue, solve


class EngineError(ValueError):
    """The inputs cannot produce a meaningful Allocation. The message says why."""


# ---------------------------------------------------------------------------
# 1. Classification
# ---------------------------------------------------------------------------

#: Register field -> dimension; ``None`` where the register carries nothing for it.
REGISTER_FIELD = {"currency": "currency", "region": "region_geo", "role": "role",
                  "capital_type": "capital_type", "liquidity": "liquidity", "phase": None,
                  "asset_class": "asset_class"}


def raw_attributes(register: InstrumentOut, table: Optional[InstrumentClass]) -> tuple[dict, dict]:
    """The unclassified attributes of one instrument and where each came from.

    ``fmre``'s register is the authority for every attribute it carries. The calibration's classification
    table supplies what it does not (economic phase, home scenario, ESG) and fills a register gap (liquidity,
    region) where the register holds nothing (PCP-06). An attribute neither holds is missing, not guessed.
    """
    values: dict[str, Optional[object]] = {}
    sources: dict[str, str] = {}
    for dimension, fname in REGISTER_FIELD.items():
        reg_value = getattr(register, fname) if fname else None
        if reg_value is not None:
            values[dimension], sources[dimension] = reg_value, "fmre"
            continue
        tab_value = getattr(table, dimension, None) if table is not None else None
        values[dimension], sources[dimension] = tab_value, ("calibration" if tab_value is not None else "missing")
    for extra in ("home_scenario", "esg"):
        tab_value = getattr(table, extra) if table is not None else None
        values[extra], sources[extra] = tab_value, ("calibration" if tab_value is not None else "missing")
    return values, sources


def classify(attributes: Sequence[Mapping[str, object]], ids: Sequence[str], cal: Calibration
             ) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...], tuple[float, ...], list[str]]:
    """Buckets per dimension, home scenarios, ESG scores, and the problems found (empty if none)."""
    problems: list[str] = []
    labels: dict[str, list[str]] = {d: [] for d in DIMENSIONS}
    scenarios: list[str] = []
    esg: list[float] = []
    for iid, attrs in zip(ids, attributes):
        for dimension in DIMENSIONS:
            labels[dimension].append(_bucket(dimension, attrs.get(dimension), cal, iid, problems))
        scenarios.append(_bucket("scenario", attrs.get("home_scenario"), cal, iid, problems))
        score = attrs.get("esg")
        if score is None:
            problems.append(f"{iid} has no ESG score")
            esg.append(0.0)
        else:
            esg.append(float(score))  # type: ignore[arg-type]
    return ({d: tuple(v) for d, v in labels.items()}, tuple(scenarios), tuple(esg), problems)


def _bucket(dimension: str, value: object, cal: Calibration, iid: str, problems: list[str]) -> str:
    vocab = cal.vocabularies.of(dimension)
    if value is None:
        problems.append(f"{iid} has no {dimension}")
        return vocab[-1]
    text = cal.ingest_maps.get(dimension, {}).get(str(value), str(value))
    if text in vocab:
        return text
    if dimension in cal.catch_all:
        return cal.catch_all[dimension]
    problems.append(f"{iid} has {dimension} {value!r}, which is not in {list(vocab)}")
    return vocab[-1]


# ---------------------------------------------------------------------------
# 2. The client's regime distribution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlendedRegime:
    vector: np.ndarray
    date: str
    weights: dict[str, float]


def economy_weights(regime: Regime, weights: Optional[Mapping[str, float]], market: Optional[str]) -> dict[str, float]:
    """The mandate's economy weights; a named market stands for the weights ``aggregation`` published."""
    if weights is not None:
        return {k: float(v) for k, v in weights.items() if v > 0}
    for m in regime.markets:
        if m.code.lower() == str(market).lower():
            return {k: float(v) for k, v in m.weights.items() if v > 0}
    raise EngineError(f"regime {regime.regime_id} publishes no market {market!r}; it has "
                      f"{[m.code for m in regime.markets]}")


def blend_regime(regime: Regime, weights: Mapping[str, float], date: Optional[str]) -> BlendedRegime:
    """``sum_e w_e * distribution_e(date)``. Every weighted economy must be assessed at ``date``.

    With ``date`` omitted, the latest month in which all of them are assessed. The distributions sum to one
    and so do the weights, so the blend sums to one; that is checked, not assumed.
    """
    by_code = {e.code: e for e in regime.economies}
    unknown = sorted(set(weights) - set(by_code))
    if unknown:
        raise EngineError(f"regime {regime.regime_id} carries no economy {unknown}; it has {sorted(by_code)}")
    candidates = range(len(regime.dates))
    if date is not None:
        candidates = [k for k, d in enumerate(regime.dates) if d == date or d.startswith(date)]
        if not candidates:
            raise EngineError(f"regime {regime.regime_id} has no month {date!r} "
                              f"(range {regime.dates[0]} to {regime.dates[-1]})")
        k = candidates[-1]
        missing = sorted(code for code in weights if by_code[code].distribution[k] is None)
        if missing:
            raise EngineError(f"the mandate weights {missing}, which regime {regime.regime_id} does not assess "
                              f"in {regime.dates[k]}; choose another month or other economy weights")
    else:
        assessed = [k for k in candidates
                    if all(by_code[code].distribution[k] is not None for code in weights)]
        if not assessed:
            raise EngineError(f"no month of regime {regime.regime_id} assesses all of {sorted(weights)}")
        k = assessed[-1]
    vector = np.zeros(len(by_code[next(iter(weights))].distribution[k]))  # type: ignore[arg-type]
    for code, w in weights.items():
        vector += w * np.asarray(by_code[code].distribution[k], dtype=float)
    if abs(vector.sum() - 1.0) > 1e-9 or (vector < -1e-15).any():
        raise EngineError(f"the blended regime distribution sums to {vector.sum()}, not one")
    return BlendedRegime(vector=vector, date=regime.dates[k], weights=dict(weights))


# ---------------------------------------------------------------------------
# 3. The optimisation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    ids: tuple[str, ...]
    labels: Mapping[str, Sequence[str]]
    home_scenarios: tuple[str, ...]
    esg: tuple[float, ...]
    profiles: np.ndarray                     # (n, 25)
    target: np.ndarray                       # (25,)
    regime: np.ndarray                       # (25,)
    bounds: Mapping[str, Mapping[str, tuple[float, float]]]
    esg_min: float
    max_single_position: float
    fixed: tuple[float, ...]


@dataclass(frozen=True)
class Outcome:
    raw_weights: np.ndarray
    weights: np.ndarray
    raw_sum: float
    budget_met: bool
    objective: float
    floor: float
    leverage: Optional[float]
    shortfall: np.ndarray
    achieved: np.ndarray
    binding: tuple[BindingRow, ...]
    exposures: dict[str, dict[str, float]]
    grid: tuple[tuple[float, ...], ...]
    by_role: dict[str, float]
    esg: float
    rows: int
    solve: Solve
    notes: tuple[str, ...] = field(default=())


def constraint_system(problem: Problem, cal: Calibration) -> cons.ConstraintSystem:
    return cons.build(problem.labels, problem.esg, cal.vocabularies, problem.bounds, problem.esg_min,
                      problem.max_single_position, problem.fixed)


def budget_met(raw_sum: float, check: BudgetCheck) -> bool:
    """Read from the raw weights, before renormalising (Manual section 15.2)."""
    if check.mode == "rounded":
        return round(raw_sum, check.decimals) == 1
    return abs(raw_sum - 1.0) <= check.tolerance


def acceptable(solved: Solve, system: cons.ConstraintSystem, check: BudgetCheck) -> bool:
    """Converged, the raw weights meeting the calibration's budget check, and no row, budget or bound
    breached by more than ``FEASIBILITY_TOL``. A solve that is not acceptable goes to :func:`solver.rescue`."""
    return (solved.success and budget_met(float(solved.raw_weights.sum()), check)
            and cons.max_violation(solved.raw_weights, system) <= cons.FEASIBILITY_TOL)


def _rescued(problem: Problem, system: cons.ConstraintSystem, cal: Calibration, first: Solve, speed: str,
             scale: float) -> Solve:
    """PCP-21: the calibrated solve did not settle; restart from the phase-1 point with the exact settings."""
    breach = cons.max_violation(first.raw_weights, system)
    why = (f"the calibrated solve ({first.method} from {cal.solver.start_value}, {speed} settings) did not settle "
           f"({first.status}; raw weights sum to {float(first.raw_weights.sum()):.6f}, largest breach {breach:.2e})")
    p1 = cons.phase_one(system)
    if not p1.feasible or p1.point is None:          # found by feasibility_problems already; kept for safety
        return replace(first, success=False, notes=first.notes + (why, "the phase-1 programme found no feasible point"))
    again = rescue(problem.profiles, problem.target, problem.regime, system, cal.solver, p1.point, scale)
    return replace(again, notes=first.notes + (why,) + again.notes)


def optimise(problem: Problem, cal: Calibration, speed: str) -> Outcome:
    system = constraint_system(problem, cal)
    problems = system.feasibility_problems()
    if problems:
        raise EngineError("the mandate is infeasible as stated: " + "; ".join(problems))
    scale = cal.objective.profile_scale
    solved = solve(problem.profiles, problem.target, problem.regime, system, cal.solver, speed, scale)
    if not acceptable(solved, system, cal.budget_check):
        solved = _rescued(problem, system, cal, solved, speed, scale)
    raw = solved.raw_weights
    total = float(raw.sum())
    if total <= 0.0:
        raise EngineError("the solver returned weights summing to zero or less; the mandate is infeasible")
    weights = raw / total
    notes = list(solved.notes)
    met = budget_met(total, cal.budget_check)
    fl = obj.floor(problem.profiles, problem.target, problem.regime, scale)
    leverage = None if fl <= 0.0 else (fl - solved.objective) / fl
    if leverage is not None and leverage < cal.leverage_note_below:
        notes.append(f"the weights control {leverage:.2%} of the objective (objective {solved.objective:.6g} "
                     f"against a floor of {fl:.6g} with nothing allocated): the allocation is driven mainly by "
                     "the constraints, the curve fit acting as a tie-breaker (per-instrument objective, D28)")
    roles, scenarios = cal.vocabularies.role, cal.vocabularies.scenario
    grid = np.zeros((len(roles), len(scenarios)))
    for w, role, scen in zip(weights, problem.labels["role"], problem.home_scenarios):
        grid[roles.index(role), scenarios.index(scen)] += float(w)
    return Outcome(
        raw_weights=raw, weights=weights, raw_sum=total, budget_met=met, objective=solved.objective,
        floor=fl, leverage=leverage,
        shortfall=obj.shortfall_by_state(weights, problem.profiles, problem.target, problem.regime, scale),
        achieved=obj.achieved_curve(weights, problem.profiles),
        binding=cons.binding(weights, system, cal.binding_tolerance),
        exposures=cons.exposures(weights, system),
        grid=tuple(tuple(float(v) for v in row) for row in grid),
        by_role={r: float(grid[k].sum()) for k, r in enumerate(roles)},
        esg=float(np.asarray(problem.esg) @ weights), rows=system.n_rows, solve=solved, notes=tuple(notes),
    )
