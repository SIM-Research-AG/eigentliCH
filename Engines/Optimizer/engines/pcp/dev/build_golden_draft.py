"""Freeze golden layer A: the eigentliCH PCP draft's own runs, inputs and outputs. Development only.

Run with the DRAFT's virtual environment, from anywhere::

    <eigentliCH>/engines/PCP/.venv/Scripts/python.exe dev/build_golden_draft.py

It imports the draft package in place, prepares and solves each mandate below exactly as the draft's CLI
does (``pcp.cli optimise --mandate <name> --no-write``), and writes one JSON file per mandate to
``golden/draft/``: the pure inputs the objective and the constraints see (instrument profiles, the
classification of every instrument, the target curve, the regime vector of the solved period, every bound,
the solver settings) and the draft's outputs (raw and renormalised weights, objective, budget check,
binding rows, solver method and iterations). The pcp engine reproduces these from the JSON alone
(``tests/test_golden.py``), so the suite runs on a machine that has never seen the draft.

Model-derived research output. Not investment advice.
"""

from __future__ import annotations

import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "golden" / "draft"
DRAFT = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\engines\PCP")
sys.path.insert(0, str(DRAFT))

from pcp import ENGINE_VERSION  # noqa: E402  (the draft's package, not this engine's)
from pcp.config import load_config  # noqa: E402
from pcp.model.constraints import binding_constraints  # noqa: E402
from pcp.pipeline import prepare, run  # noqa: E402

#: The mandates frozen. The first three are the ones named in the build report; the others widen the
#: fixture across derived mandates of different horizons. Each must reproduce its saved output.
MANDATES = (
    "fixture_balanced",
    "derived_onb-1981-sz",
    "derived_onb-2001-stgallen-20260826",
    "derived_onb-1968-thurgau-20260901",
    "derived_onb-1980-aargau-20260821",
    "derived_onb-2005-thurgau-20260824",
    "derived_onb-chain-ueliw",
)

DIMENSIONS = ("currency", "region", "role", "capital_type", "liquidity", "phase", "asset_class")
ATTRIBUTE = {"currency": "currency", "region": "region_geo", "role": "role",
             "capital_type": "capital_type", "liquidity": "liquidity", "phase": "economic_phase",
             "asset_class": "asset_class"}


def freeze(name: str, config) -> dict:
    prepared = prepare(name, config)
    result = run(name, config, inputs=prepared)
    current = result.current
    m = prepared.mandate
    vocab = config.vocabularies
    vocabularies = {d: list(vocab.by_name(d).labels) for d in DIMENSIONS}
    vocabularies["scenario"] = list(vocab.scenarios.labels)
    binding = binding_constraints(current.weights, prepared.system)
    raw = None
    # The draft keeps the raw solution on the solver result only; re-solve to read it (deterministic).
    from pcp.model.optimiser_curve import solve_curve
    solved = solve_curve(prepared.bb, m.target_curve, current.regime, prepared.system, config,
                         speed=result.speed)
    raw = [float(v) for v in solved.raw_weights]
    return {
        "_note": ("Golden layer A: the eigentliCH PCP draft's run of this mandate, frozen by "
                  "dev/build_golden_draft.py. Inputs are what the objective and constraints saw; outputs "
                  "are the draft's. Model-derived research output; not investment advice."),
        "mandate": name,
        "draft_engine_version": ENGINE_VERSION,
        "libraries": {"numpy": metadata.version("numpy"), "scipy": metadata.version("scipy")},
        "period": current.period,
        "regime_id": result.regime_id,
        "return_set_id": result.return_set_id,
        "speed": result.speed,
        "solver": {
            "method": str(config.get("solver.method")),
            "fallback_method": str(config.get("solver.fallback_method")),
            "start_value": float(config.get("solver.start_value")),
            "speeds": {k: dict(v) for k, v in dict(config.get("solver.speeds")).items()},
            "conditions_met_decimals": int(config.get("solver.conditions_met_decimals")),
        },
        "vocabularies": vocabularies,
        "instruments": [
            {"id": str(b.bb_id), "name": b.name,
             **{d: getattr(b, ATTRIBUTE[d]) for d in DIMENSIONS},
             "home_scenario": b.home_scenario, "esg": float(b.esg),
             "profile": [float(v) for v in b.profile_by_state]}
            for b in prepared.blocks
        ],
        "target_curve": [float(v) for v in m.target_curve],
        "regime": [float(v) for v in current.regime],
        "max_single_position": float(m.max_single_position),
        "esg_min": float(m.esg_min),
        "fixed_allocations": {str(k): float(v) for k, v in m.fixed_allocations.items()},
        "bounds": {d: {label: [b.lower, b.upper] for label, b in cats.items()} for d, cats in m.bounds.items()},
        "expected": {
            "weights": [float(v) for v in current.weights],
            "raw_weights": raw,
            "objective": float(current.objective_value),
            "conditions_met": current.conditions_met,
            "solver_method": current.solver_method,
            "binding": sorted(f"{b.dimension}:{b.category}:{b.side}" for b in binding),
            "achieved_curve": [float(v) for v in current.return_dist_final],
            "role_allocation": dict(current.role_allocation),
            "portfolio_map": [[float(v) for v in row] for row in current.portfolio_map],
            "idempotency_key": result.idempotency_key,
        },
    }


def main() -> int:
    config = load_config(None)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in MANDATES:
        try:
            payload = freeze(name, config)
        except Exception as exc:  # noqa: BLE001 - report and continue; a mandate may be gone
            print(f"skipped {name}: {exc}", file=sys.stderr)
            continue
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        path = OUT / f"{name}.json"
        path.write_text(text, encoding="utf-8")
        manifest.append({"mandate": name, "file": path.name,
                         "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         "objective": payload["expected"]["objective"],
                         "conditions_met": payload["expected"]["conditions_met"]})
        print(f"froze {name}: objective {payload['expected']['objective']:.10g}, "
              f"{len(payload['instruments'])} instruments, conditions_met {payload['expected']['conditions_met']}")
    (OUT / "manifest.json").write_text(json.dumps({"cases": manifest}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
