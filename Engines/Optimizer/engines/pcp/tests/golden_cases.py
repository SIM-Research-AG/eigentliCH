"""The golden cases, as pure-engine problems. Shared by tests/test_golden.py and the dev builders.

Layer A: the eigentliCH draft's frozen runs (``golden/draft``), solved with calibration 1.0.0.
Layer C: this build's production cases on the frozen live inputs (``golden/inputs``), calibration 1.1.0.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import TypeAdapter

from pcp import engine
from pcp.calibration import DRAFT, PRODUCTION
from pcp.contracts import DIMENSIONS, InstrumentOut, Mandate, Regime, ReturnSet

GOLDEN = Path(__file__).resolve().parent.parent / "golden"


def draft_cases() -> list[str]:
    return sorted(p.stem for p in (GOLDEN / "draft").glob("*.json") if p.name != "manifest.json")


def draft_problem(name: str) -> tuple[engine.Problem, dict]:
    g = json.loads((GOLDEN / "draft" / f"{name}.json").read_text(encoding="utf-8"))
    ids = tuple(i["id"] for i in g["instruments"])
    attrs = [{**{d: i[d] for d in DIMENSIONS}, "home_scenario": i["home_scenario"], "esg": i["esg"]}
             for i in g["instruments"]]
    labels, scenarios, esg, problems = engine.classify(attrs, ids, DRAFT)
    assert not problems, problems
    problem = engine.Problem(
        ids=ids, labels=labels, home_scenarios=scenarios, esg=esg,
        profiles=np.asarray([i["profile"] for i in g["instruments"]], dtype=float),
        target=np.asarray(g["target_curve"], dtype=float), regime=np.asarray(g["regime"], dtype=float),
        bounds={d: {label: tuple(v) for label, v in c.items()} for d, c in g["bounds"].items()},
        esg_min=g["esg_min"], max_single_position=g["max_single_position"],
        fixed=tuple(g["fixed_allocations"].get(i, 0.0) for i in ids))
    return problem, g


def _inputs():
    regime = Regime.model_validate_json((GOLDEN / "inputs" / "regime.json").read_bytes())
    rs = ReturnSet.model_validate_json((GOLDEN / "inputs" / "return_set.json").read_bytes())
    register = {r.instrument_id: r for r in
                TypeAdapter(list[InstrumentOut]).validate_json((GOLDEN / "inputs" / "instruments.json").read_bytes())}
    return regime, rs, register


def _mandate(**over) -> Mandate:
    _, _, register = _inputs()
    body = {"client": "golden", "name": "balanced", "currency": "CHF", "target_curve": [0.02] * 25,
            "universe": sorted(register), "max_single_position": 0.15,
            "bounds": {"role": {"Gain": {"lower": 0.2, "upper": 0.6}, "Protection": {"lower": 0.05, "upper": 0.4}},
                       "currency": {"CHF": {"lower": 0.3, "upper": 1.0}}},
            "bound_sources": {"role": "derived", "currency": "derived"}, "regime_market": "global"}
    body.update(over)
    return Mandate.model_validate(body)


#: Layer C: name -> mandate overrides.
CASES = {
    "balanced_global": {},
    "swiss_client_blend": {"regime_market": None, "regime_weights": {"CH": 0.5, "EU": 0.3, "US": 0.2},
                           "target_curve": [0.04 - 0.0025 * (12 - s) for s in range(25)]},
    "tight_single_position": {"max_single_position": 0.08, "target_curve": [0.03] * 25},
}


def production_problem(name: str) -> tuple[engine.Problem, str]:
    regime, rs, register = _inputs()
    m = _mandate(**CASES[name])
    profiles = {p.key: p for p in rs.instrument_profiles}
    ids = tuple(m.universe)
    attrs = [engine.raw_attributes(register[i], PRODUCTION.classification.get(i))[0] for i in ids]
    labels, scenarios, esg, problems = engine.classify(attrs, ids, PRODUCTION)
    assert not problems, problems
    weights = engine.economy_weights(regime, m.regime_weights, m.regime_market)
    blend = engine.blend_regime(regime, weights, None)
    problem = engine.Problem(
        ids=ids, labels=labels, home_scenarios=scenarios, esg=esg,
        profiles=np.asarray([[s.value for s in profiles[i].states] for i in ids], dtype=float),
        target=np.asarray(m.target_curve, dtype=float), regime=blend.vector,
        bounds={d: {label: (b.lower, b.upper) for label, b in c.items()} for d, c in m.bounds.items()},
        esg_min=m.esg_min, max_single_position=m.max_single_position,
        fixed=tuple(m.fixed_allocations.get(i, 0.0) for i in ids))
    return problem, blend.date


def solve_case(name: str):
    problem, date = production_problem(name)
    return engine.optimise(problem, PRODUCTION, "exact"), date
