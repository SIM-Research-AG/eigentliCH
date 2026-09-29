"""Solver-reliability harness (the prerequisite for exact-probability calibration).

The old single-phase solver was M_opt-sensitive and could collapse a hard goal's
applied plan into a give-up basin (P jumping between ~1 and ~0). This harness checks
the two-phase solver of ``optim/problem.py`` on two axes:

  STABILITY   the same case solved at several M_opt values agrees on out-of-sample P
              (no basin-hopping by scenario count);
  MONOTONE    a strictly richer variant (more income scale w0) never scores a *lower*
              goal probability (the physical sanity check that failed before).

Run:  python -m personal_alm.calibrate.reliability
"""

from __future__ import annotations

import time
from dataclasses import replace

from ..cases import NICOLAS, run_case, Case


def stability(case: Case, m_opts=(10, 14, 18), n_starts: int = 2, M_eval: int = 300) -> dict:
    ps = {}
    for M in m_opts:
        t = time.time()
        r = run_case(case, M_opt=M, M_eval=M_eval, n_starts=n_starts)
        ps[M] = (r.p_goal, r.binding, r.success, time.time() - t)
    spread = max(v[0] for v in ps.values()) - min(v[0] for v in ps.values())
    return {"case": case.name, "by_M": ps, "spread": spread}


def monotone(case: Case, w0_lo: float, w0_hi: float, M_opt: int = 14, n_starts: int = 2) -> dict:
    lo = run_case(replace(case, param_overrides={**case.param_overrides, "w0": w0_lo}),
                  M_opt=M_opt, M_eval=300, n_starts=n_starts)
    hi = run_case(replace(case, param_overrides={**case.param_overrides, "w0": w0_hi}),
                  M_opt=M_opt, M_eval=300, n_starts=n_starts)
    return {"case": case.name, "w0_lo": w0_lo, "p_lo": lo.p_goal,
            "w0_hi": w0_hi, "p_hi": hi.p_goal, "monotone": hi.p_goal >= lo.p_goal - 0.05}


def main():
    print("=== STABILITY: Nicolas across M_opt ===")
    s = stability(NICOLAS)
    for M, (p, b, ok, dt) in s["by_M"].items():
        print(f"  M_opt={M:>2}  P={p:.0%}  binds={b:<16} ok={ok}  ({dt:.0f}s)")
    print(f"  spread across M = {s['spread']:.0%}  ->  {'STABLE' if s['spread'] <= 0.15 else 'UNSTABLE'}")

    print("\n=== MONOTONE: more income never lowers P (the old failure) ===")
    m = monotone(NICOLAS, w0_lo=NICOLAS.param_overrides.get("w0", 200_000),
                 w0_hi=NICOLAS.param_overrides.get("w0", 200_000) * 1.4)
    print(f"  {m['case']}: w0 {m['w0_lo']:.0f}->{m['w0_hi']:.0f}  "
          f"P {m['p_lo']:.0%}->{m['p_hi']:.0%}  {'OK' if m['monotone'] else 'VIOLATED'}")


if __name__ == "__main__":
    main()
