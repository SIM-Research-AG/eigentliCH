"""The paths artefact (``lbsim-paths@1.0.0``): the stated plan simulated in every Regime. Pure: the same inputs
give the same bytes; no clock, no I/O.

* The random numbers are drawn once (``SeedSequence(seed).spawn(3)``) and shared by every Regime, so the base
  Regime is the same whatever scenarios run beside it (common random numbers).
* Bands are stored in both bases (LBSIM-10): the real quantiles are quantiles of each path's own deflated values,
  from the same draws, never deflated quantiles. Paths themselves are not stored; the seed reproduces them.
* One chance per goal and Regime in the goal's own basis (LBSIM-09). The target in the other basis is converted
  at the median path's price level at the goal's date, for the dashed line of chart 3.
* The principal's capitals (``capitals``, DECISIONS P-26, engine 1.1.0): year-end quantiles p10..p90 of the model's
  ``E``, ``N`` and ``H`` from the same draws, on their own scales (the calibration's ``K_E`` and ``K_H``; for the
  network lbs's 0 to 1, raised to the Regime's highest p90 of ``N`` where its paths go beyond it).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

from .. import ENGINE_VERSION
from ..calibration import calibration_hash
from ..contracts import (BAND_SERIES, CAPITAL_QUANTILES, CAPITALS, CONTRACT_VERSIONS, QUANTILES, AllocationView,
                         Calibration, LifeBalanceFindings, LifeBalancePaths, Provenance)
from ..ids import content_id
from ..upstream import MarketBundle
from . import engine as E
from .household import StatedPlan
from .market import draws, path_market, rule_words, year_table

QS = tuple(int(q[1:]) for q in QUANTILES)
CAPITAL_QS = tuple(int(q[1:]) for q in CAPITAL_QUANTILES)
#: The model state behind each capital, and its words (spec VISUALS_INTERFACES, 03.10.2026).
CAPITAL_STATE = {"expertise": "E", "network": "N", "health": "H"}
CAPITAL_LABELS = {"expertise": {"de": "Wissen und Ausbildung", "en": "Expertise and education"},
                  "network": {"de": "Netzwerk", "en": "Network"},
                  "health": {"de": "Gesundheit", "en": "Health"}}
DEFLATOR = "each path's own price level, from the inflation of the market states drawn on that path (fmre, CHF)"


def numpy_minor() -> str:
    return ".".join(np.__version__.split(".")[:2])


def paths_key(findings: LifeBalanceFindings, bundle: MarketBundle, *, horizon_years: int, n_paths: int, seed: int,
              income_path: str) -> str:
    """Section 3.9: the findings key plus the market inputs, the horizon, the draws and numpy's minor version."""
    return content_id("IDK", {"kind": "paths", "findings": findings.provenance.idempotency_key,
                              **bundle.key_parts, "horizon_years": int(horizon_years), "n_paths": int(n_paths),
                              "seed": int(seed), "income_path": income_path, "numpy": numpy_minor()})


def _quantiles(values: np.ndarray) -> dict[str, list[float]]:
    """``values``: ``(years + 1, n_paths)``; one list per quantile over the year ends."""
    q = np.percentile(values, QS, axis=1)
    return {f"p{p:02d}": [float(v) for v in row] for p, row in zip(QS, q)}


def _capital_quantiles(values: np.ndarray) -> dict[str, list[float]]:
    q = np.percentile(values, CAPITAL_QS, axis=1)
    return {f"p{p:02d}": [float(v) for v in row] for p, row in zip(CAPITAL_QS, q)}


def capital_scales(result: "E.Result", plan: StatedPlan) -> dict[str, dict[str, float]]:
    """``K_E`` and ``K_H``: the calibration's ceilings. The network has no fixed ceiling in the model (``K_N``
    moves with expertise, net worth and the habit, and on a wealthy path reaches several times the level), so its
    scale is the one lbs states ``N`` on, 0 to 1, raised to the highest p90 of ``N`` at any year end of this Regime
    where its paths go beyond it (DECISIONS P-26). Per Regime, so a Regime's block does not depend on which other
    Regimes run beside it (common random numbers)."""
    p = plan.params
    top = max(1.0, float(np.max(np.percentile(result.states["N"], 90, axis=1))))
    return {"expertise": {"min": 0.0, "max": float(p.K_E)}, "network": {"min": 0.0, "max": top},
            "health": {"min": 0.0, "max": float(p.K_H)}}


def capitals_block(result: "E.Result", person_id: str, plan: StatedPlan) -> dict[str, Any]:
    out: dict[str, Any] = {"person_id": person_id}
    for name in CAPITALS:
        out[name] = _capital_quantiles(result.states[CAPITAL_STATE[name]])
    out["scale"] = capital_scales(result, plan)
    out["labels"] = CAPITAL_LABELS
    return out


def simulate_regimes(plan: StatedPlan, bundle: MarketBundle, calibration: Calibration, *, n_paths: int,
                     seed: int, states: Optional[dict[str, np.ndarray]] = None) -> dict[str, E.Result]:
    """Every Regime's run, on the shared draws. ``states`` fixes a Regime's state path (tests)."""
    years = plan.horizon_years
    d = draws(seed, n_paths, years, persistence=calibration.market.state_persistence)
    base = bundle.regimes[0]
    out = {}
    for regime in bundle.regimes:
        table = year_table(regime, base, years, calibration.market)
        pm = path_market(table, d, calibration.property, persistence=calibration.market.state_persistence,
                         states=None if states is None else states.get(regime.key))
        out[regime.key] = E.simulate(plan.household, plan.controls, n_paths=n_paths, market="allocation",
                                     path_market=pm)
        out[regime.key].table = table  # type: ignore[attr-defined]
        out[regime.key].path_market = pm  # type: ignore[attr-defined]
    return out


def regime_block(regime, result: E.Result, plan: StatedPlan, calibration: Calibration, *,
                 capitals: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    p = plan.params
    series = ["net_worth"] + [s for s in BAND_SERIES[1:] if any(g.measure == s for g in plan.goals)]
    P = result.states["P"]
    bands = {}
    for name in series:
        nominal = E.measure_values(result.states, name, p)
        bands[name] = {"nominal": _quantiles(nominal),
                       "real": {**_quantiles(nominal / P), "derived": True, "deflator": DEFLATOR}}
    goals = []
    for g in plan.goals:
        out = result.goals[g.goal_id]
        med_P = float(np.median(P[g.year]))
        if g.basis == "real":
            real, nominal = g.target_real, g.target_real * med_P
        else:
            nominal, real = g.target_nominal, g.target_nominal / med_P
        reached = out["reached"]
        goals.append({"goal_id": g.goal_id, "kind": g.kind, "measure": g.measure,
                      "target": {"nominal_chf": float(nominal), "real_chf": float(real),
                                 "amount_basis": g.amount_basis, "date": g.date.isoformat()},
                      "chance": float(np.mean(reached)), "chance_basis": g.basis,
                      "n_reached": int(np.sum(reached)), "median_shortfall_chf": float(np.median(out["shortfall"]))})
    return {"key": regime.key, "label": regime.label.model_dump(), "regime_id": regime.regime_id,
            "kind": regime.kind, "scenario_years": result.table.scenario_years,  # type: ignore[attr-defined]
            "return_set_id": regime.return_set_id, "inflation_pass_through": regime.inflation_pass_through,
            "inflation": {"source": regime.inflation_source, "labels_summary": regime.labels_summary},
            "bands": bands, "goals": goals, **({"capitals": capitals} if capitals is not None else {})}


def allocation_view(bundle: MarketBundle) -> dict[str, Any]:
    a = bundle.allocation
    li = bundle.base_log_inflation
    target = np.asarray(a.curves.target, dtype=float)
    achieved = np.asarray(a.curves.achieved, dtype=float)
    if a.basis == "nominal":
        nominal = {"target": list(map(float, target)), "achieved": list(map(float, achieved)), "derived": False}
        real = {"target": list(map(float, target - li)), "achieved": list(map(float, achieved - li)), "derived": True}
    else:
        real = {"target": list(map(float, target)), "achieved": list(map(float, achieved)), "derived": False}
        nominal = {"target": list(map(float, target + li)), "achieved": list(map(float, achieved + li)),
                   "derived": True}
    return {"allocation_id": a.artefact_id, "mandate_name": a.mandate_name, "currency": "CHF",
            "allocation_basis": a.basis, "date": a.date.isoformat(), "regime_id": a.regime_id,
            "instruments": [{"instrument_id": i.instrument_id, "name": i.name, "role": i.role, "weight": i.weight}
                            for i in a.instruments if i.weight > 1e-9],
            "by_role": {k: (float(v) if abs(v) > 1e-12 else 0.0) for k, v in a.weights_by_role.items()},
            "state_probability": list(map(float, a.curves.regime)),
            "curves": {"nominal": nominal, "real": real, "log_inflation": list(map(float, li)),
                       "inflation_labels": list(bundle.base_inflation_labels)}}


def market_model(bundle: MarketBundle, calibration: Calibration) -> dict[str, Any]:
    m, pr = calibration.market, calibration.property
    return {"rule": rule_words(m).model_dump(), "reversion_years": float(m.reversion_years),
            "state_persistence": float(m.state_persistence), "weights": "renormalised",
            "check": {"achieved_reproduced": bundle.max_abs_diff <= 1e-9, "max_abs_diff": bundle.max_abs_diff},
            "property": {"nominal_log_growth": pr.nominal_log_growth, "inflation_beta": pr.inflation_beta,
                         "inflation_anchor_log": pr.inflation_anchor_log, "sigma": pr.sigma,
                         "rho_with_market": pr.rho_with_market},
            "pass_through": {"wages": m.wage_pass_through, "spending": m.spending_pass_through, "debt": "nominal",
                             "bvg_credits": "nominal", "fixed_contribution": "nominal",
                             "income_tax_tariff": "indexed", "scenario_returns": bundle.ipt or None}}


def build_paths(findings: LifeBalanceFindings, plan: StatedPlan, bundle: MarketBundle, calibration: Calibration,
                *, n_paths: int, seed: int) -> LifeBalancePaths:
    if calibration.behaviour.market != "allocation":
        raise ValueError("paths are simulated on the allocation market only (calibration 1.1.0 and later)")
    results = simulate_regimes(plan, bundle, calibration, n_paths=n_paths, seed=seed)
    regimes = [regime_block(r, results[r.key], plan, calibration,
                            capitals=capitals_block(results[r.key], findings.principal, plan))
               for r in bundle.regimes]
    key = paths_key(findings, bundle, horizon_years=plan.horizon_years, n_paths=n_paths, seed=seed,
                    income_path=plan.income_path)
    provenance = Provenance(
        engine_version=ENGINE_VERSION, contract_versions=CONTRACT_VERSIONS, calibration_version=calibration.version,
        calibration_hash=calibration_hash(calibration), idempotency_key=key,
        upstream={"lbs": findings.provenance.upstream["lbs"], "findings": findings.artefact_id, **bundle.upstream},
        records=findings.provenance.records,
        seeds={"state_uniforms": int(seed), "property_noise": int(seed), "spare": int(seed)},
        numpy_version=np.__version__)
    fields = dict(
        client_ref=findings.client_ref, life_balance_sheet_id=findings.life_balance_sheet_id,
        findings_artefact_id=findings.artefact_id, allocation_id=bundle.allocation.artefact_id, as_of=findings.as_of,
        calibration_version=calibration.version, start_year=plan.start_year, horizon_years=plan.horizon_years,
        n_paths=int(n_paths), seed=int(seed), income_path=plan.income_path, policy=plan.policy,
        regimes=tuple(regimes), allocation_view=AllocationView.model_validate(allocation_view(bundle)),
        market_model=market_model(bundle, calibration), provenance=provenance)
    draft = LifeBalancePaths(artefact_id="LSP-" + "0" * 16, **fields)
    body = draft.model_dump(mode="json", exclude={"artefact_id"})
    return LifeBalancePaths(artefact_id=content_id("LSP", body), **fields)


def fan(paths: LifeBalancePaths, *, regime: str, basis: str, series: str) -> dict[str, Any]:
    """One chart's series (``GET /paths/{id}/fan``). ``series=goal_measure``: the designated goal's measure (the
    first goal, the sheet's mandate goal where there is one)."""
    reg = next((r for r in paths.regimes if r.key == regime), None)
    if reg is None:
        raise KeyError(f"regime:{regime}")
    goal = reg.goals[0] if reg.goals else None
    name = series
    if series == "goal_measure":
        if goal is None:
            raise KeyError("goal_measure")
        name = goal.measure
    if name not in reg.bands:
        raise KeyError(f"series:{series}")
    band = getattr(reg.bands[name], basis)
    out: dict[str, Any] = {
        "paths_artefact_id": paths.artefact_id, "regime": reg.key, "label": reg.label.model_dump(),
        "basis": basis, "series": name, "derived": basis == "real",
        "years": [paths.start_year + k for k in range(paths.horizon_years + 1)],
        "bands": {q: list(getattr(band, q)) for q in QUANTILES}}
    if basis == "real":
        out["deflator"] = band.deflator  # type: ignore[attr-defined]
    related = [g for g in reg.goals if g.measure == name]
    if related:
        g = related[0]
        own = g.chance_basis == basis
        out["goal"] = {"goal_id": g.goal_id, "kind": g.kind, "date": g.target.date.isoformat(),
                       "target_chf": g.target.real_chf if basis == "real" else g.target.nominal_chf,
                       "line": "solid" if own else "dashed", "converted": not own,
                       "conversion": None if own else "at the median path's price level at the goal's date",
                       "chance": g.chance, "chance_basis": g.chance_basis}
    return out
