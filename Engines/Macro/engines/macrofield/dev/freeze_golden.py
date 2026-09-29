"""Freeze the old macrofield build's outputs as the golden reference. Development only.

Runs INSIDE the old build (eigentliCH/engines/Macro_Model), with its interpreter, offline
against its own download cache, and writes one JSON per economy:

    cd <Macro_Model>
    set PYTHONPATH=.
    .venv/Scripts/python.exe <this file> <out_dir> [codes...]

The calibration follows the old cockpit path (p_b from population growth). The old CLI
``calibrate`` command omits population growth and so falls back to the flow-ratio p_b, whose
path explodes; that path is not the model of record and is not frozen. Japan fails in the old
build itself (no fiscal balance) and writes an error file instead.

Frozen on 2026-09-27 from the old build's state of 2026-08-03. Re-freezing is only meaningful
if the old build changes, which it should not: it is the reference.
"""

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.simplefilter("ignore")

from macrofield import config as config_module
from macrofield.calibration.fit import calibrate, compute_identity_parameters
from macrofield.model.phases import PhaseThresholds, classify_sequence
from macrofield.model.quantity import unsecured_assets_ratio
from macrofield.pipeline import assemble, build_sources


def arr(a):
    return [None if (v is None or not np.isfinite(v)) else float(v) for v in np.asarray(a, dtype=float)]


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    codes = sys.argv[2:] or ["us", "de", "gb", "fr", "ch", "cn", "in", "br", "jp"]
    for code in codes:
        t0 = time.time()
        cfg = config_module.load(code)
        sources = build_sources(offline=True, config=cfg)
        try:
            eco = assemble(code, sources, config=cfg)
        except Exception as error:  # noqa: BLE001
            (out / f"{code}.error.txt").write_text(repr(error), encoding="utf-8")
            print(code, "ASSEMBLY FAILED", error, flush=True)
            continue
        path = eco.path
        sat = eco.saturation.values.reindex(path.periods).to_numpy(dtype=float)
        ids = compute_identity_parameters(path, population_growth=eco.population_growth)
        res = calibrate(code, path, population_growth=eco.population_growth)
        thresholds = PhaseThresholds.from_config(config_module.load())
        phases = classify_sequence(sat, path.real_capital, path.financial_capital, path.output, thresholds)
        doc = {
            "_source": "eigentliCH/engines/Macro_Model (macrofield), frozen offline from its cache",
            "economy": code,
            "window": list(eco.window),
            "periods": [int(p) for p in path.periods],
            "inputs": {
                "Y": arr(path.output),
                "K_R": arr(path.real_capital),
                "K_I": arr(path.financial_capital),
                "p_s": arr(path.savings_rate),
                "S": arr(path.stimulus_proxy),
                "population_growth": arr(eco.population_growth) if eco.population_growth is not None else None,
                "saturation": arr(sat),
            },
            "capital_normalisation": eco.adjustments["capital_normalisation"],
            "identities": {k: arr(v) for k, v in ids.as_paths().items()},
            "calibration": {
                "free_parameters": res.free_parameters,
                "converged": res.converged,
                "integration_accuracy": res.integration_accuracy,
                "residuals_by_series": res.residuals_by_series,
                "two_body_worst": res.two_body_worst,
                "simulated": {k: arr(v) for k, v in res.simulated.items()},
                "identity_diagnostics": {
                    k: v for k, v in res.identity_diagnostics.items() if not isinstance(v, dict)
                },
            },
            "phases": [int(c.phase) for c in phases],
            "in_balanced_band": [bool(c.in_balanced_band) for c in phases],
            "unsecured_ratio": arr(unsecured_assets_ratio(path.real_capital, path.financial_capital, path.output)),
            "notes": eco.notes,
        }
        (out / f"{code}.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
        print(code, eco.window, f"{time.time() - t0:.1f}s", res.integration_accuracy, flush=True)


if __name__ == "__main__":
    main()
