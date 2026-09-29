"""Freeze the draft's own per-path ``simulate`` (``personal_alm/sim/montecarlo.py``) for the Monte Carlo parity tests.

Run with the DRAFT's interpreter, never this family's (it imports the draft)::

    C:\\Users\\nicol\\Desktop\\SIM_NAS\\Projects\\eigentliCH\\engines\\Life_Balance_Sheet\\.venv\\Scripts\\python.exe -X utf8 dev/build_golden_mc.py

Read-only use of the draft: nothing is written outside ``golden/mc`` in this engine's folder, and the draft's
``simulate`` does not read the two missing tables.

The cases are invented households, each run twice: with ``rng=None`` (the deterministic skeleton, sigma = 0) and
with a seeded generator (the draft's correlated Gaussian shocks, whose draws are frozen too, so lbsim's engine can be
fed the same numbers). Each case sets the two draft parameters whose states the draft's ``step`` never integrates
to values under which they cannot feed back (``alpha_kappa = 0``: the habit stays at its start; ``y_R = 0``: the
un-integrated residence share earns nothing), so lbsim's full integration and the draft's partial one must agree
exactly on ``W_L, W_R, D, E, N, H, age`` (port note P-9).
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

DRAFT = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\engines\Life_Balance_Sheet")
HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "golden" / "mc"
sys.path.insert(0, str(DRAFT))

from personal_alm.model.controls import Control  # noqa: E402
from personal_alm.model.params import Params  # noqa: E402
from personal_alm.model.state import State  # noqa: E402
from personal_alm.sim.montecarlo import constant_policy, simulate  # noqa: E402

CASES = {
    "renter-single": {
        "state": dict(W_L=200_000.0, W_R=0.0, D=0.0, E=0.8, N=0.6, H=0.85, age=38.0, W_P=150_000.0, W_3a=20_000.0,
                      kappa=80_000.0),
        "params": dict(alpha_kappa=0.0, y_R=0.0, pillar3a_contribution=7_000.0),
        "control": dict(tau_Y=0.42, tau_E=0.02, tau_N=0.03, tau_H=0.2, C=48_000.0, m_E=1_000.0, m_N=500.0, p_A=0.0,
                        theta=1.0),
        "years": 20},
    "owner-couple-child": {
        "state": dict(W_L=120_000.0, W_R=1_100_000.0, D=750_000.0, E=1.1, N=0.9, H=0.8, age=42.0, W_P=260_000.0,
                      W_3a=60_000.0, kappa=110_000.0),
        "params": dict(alpha_kappa=0.0, y_R=0.0, has_partner=True, partner_income=75_000.0, tax_split_factor=2.0,
                       child_ages=(6.0,), child_reference_age=42.0, pillar3a_contribution=7_258.0, i=0.018),
        "control": dict(tau_Y=0.45, tau_E=0.01, tau_N=0.05, tau_H=0.18, C=105_000.0, m_E=0.0, m_N=2_000.0,
                        p_A=10_000.0, theta=0.6),
        "years": 30},
    "late-career": {
        "state": dict(W_L=600_000.0, W_R=0.0, D=0.0, E=1.5, N=1.2, H=0.7, age=58.0, W_P=700_000.0, W_3a=90_000.0,
                      kappa=95_000.0),
        "params": dict(alpha_kappa=0.0, y_R=0.0, ahv_record_share=0.9),
        "control": dict(tau_Y=0.6, tau_E=0.0, tau_N=0.02, tau_H=0.15, C=95_000.0, m_E=0.0, m_N=0.0, p_A=0.0,
                        theta=0.8),
        "years": 15},
}

FIELDS = ("W_L", "W_R", "D", "E", "N", "H", "age", "W_P", "W_3a")


def _row(x: State) -> dict[str, float]:
    w, p = x.wealth, x.person
    return {"W_L": w.W_L, "W_R": w.W_R, "D": w.D, "E": float(p.E.aggregate()), "N": p.N, "H": p.H, "age": p.age,
            "W_P": w.W_P, "W_3a": w.W_3a}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"built_by": "dev/build_golden_mc.py (draft interpreter)", "fields": FIELDS, "cases": {}}
    for name, case in CASES.items():
        params = replace(Params(), **case["params"])
        u = Control(**case["control"])
        n = int(case["years"] / params.dt + 0.5)
        x0 = State.individual(**case["state"])
        det = [_row(x) for x in simulate(x0, constant_policy(u), params, n).states]
        seed = 20260929
        rng = np.random.default_rng(seed)
        z = np.random.default_rng(seed).standard_normal((n, 2))
        sto = [_row(x) for x in simulate(x0, constant_policy(u), params, n, rng=rng).states]
        out["cases"][name] = {**case, "params": {k: (list(v) if isinstance(v, tuple) else v)
                                                 for k, v in case["params"].items()},
                              "n_steps": n, "seed": seed, "shocks": z.tolist(), "deterministic": det,
                              "stochastic": sto}
        print(name, n, det[-1]["W_L"], sto[-1]["W_L"])
    (OUT / "draft_simulate.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
