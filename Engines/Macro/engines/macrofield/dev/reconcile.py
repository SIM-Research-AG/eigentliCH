"""Compare the pure engine with the frozen macrofield outputs in ``golden/``. Development only.

    python dev/reconcile.py            # every golden economy
    python dev/reconcile.py US DE      # some

Prints the worst relative difference per quantity. ``tests/test_golden.py`` asserts the same
comparisons against declared tolerances.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from observations_from_raw import observations  # noqa: E402

from macrofield.calibration import V1_0_0  # noqa: E402
from macrofield.engine import run_economy  # noqa: E402

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def worst(a, b) -> float:
    a = np.array([np.nan if v is None else v for v in a], dtype=float)
    b = np.array([np.nan if v is None else v for v in b], dtype=float)
    if a.shape != b.shape:
        return float("inf")
    if not np.array_equal(np.isnan(a), np.isnan(b)):
        return float("inf")
    mask = ~np.isnan(a)
    if not mask.any():
        return 0.0
    return float(np.max(np.abs(a[mask] - b[mask]) / np.maximum(np.abs(b[mask]), 1e-300)))


def compare(code: str, obs: dict) -> None:
    g = json.loads((GOLDEN / f"{code.lower()}.json").read_text(encoding="utf-8"))
    t0 = time.time()
    s = run_economy(V1_0_0.economy(code), obs[code], V1_0_0)
    took = time.time() - t0
    print(f"{code}: {s.status} {s.years[0] if s.years else ''}-{s.years[-1] if s.years else ''} "
          f"({took:.1f}s)  golden window {g['window']}")
    if s.status != "ok":
        print("   ", s.reason)
        return
    rows = {
        "years": float(list(s.years) != g["periods"]),
        "Y": worst(s.observed.Y, g["inputs"]["Y"]),
        "K_R": worst(s.observed.K_R, g["inputs"]["K_R"]),
        "K_I": worst(s.observed.K_I, g["inputs"]["K_I"]),
        "p_s": worst(s.inputs.p_s, g["inputs"]["p_s"]),
        "S": worst(s.inputs.S, g["inputs"]["S"]),
        "saturation": worst(s.inputs.saturation, g["inputs"]["saturation"]),
        "pop_growth": worst(s.inputs.population_growth, g["inputs"]["population_growth"]),
        "r": worst(s.identities.r, g["identities"]["r"]),
        "alpha": worst(s.identities.alpha, g["identities"]["alpha"]),
        "p_p": worst(s.identities.p_p, g["identities"]["p_p"]),
        "p_b": worst(s.identities.p_b, g["identities"]["p_b"]),
        "scale": abs(s.capital_normalisation.scale / g["capital_normalisation"]["scale"] - 1),
        "phases": float(list(s.diagnostics.phase) != g["phases"]),
        "unsecured": worst(s.diagnostics.unsecured_ratio, g["unsecured_ratio"]),
    }
    gc = g["calibration"]
    rows["free_params"] = max(abs(s.fit.free_parameters[k] / v - 1) if v else abs(s.fit.free_parameters[k])
                              for k, v in gc["free_parameters"].items())
    for k in ("Y", "K_R", "K_I"):
        rows[f"sim_{k}"] = worst(s.simulated.Y if k == "Y" else getattr(s.simulated, k),
                                 gc["simulated"][k]) if s.simulated else float("inf")
    rows["accuracy"] = float(s.fit.integration_accuracy != gc["integration_accuracy"])
    for name, value in rows.items():
        flag = "" if value == 0.0 else ("  <-- " if value > 1e-12 else "")
        print(f"    {name:<12} {value:.3e}{flag}")


def main() -> None:
    codes = [c.upper() for c in sys.argv[1:]] or sorted(
        p.stem.upper() for p in GOLDEN.glob("*.json"))
    obs = observations()
    for code in codes:
        compare(code, obs)


if __name__ == "__main__":
    main()
