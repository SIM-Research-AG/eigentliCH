"""The 6x2x2 solver-flag matrix: `_ENFORCE_PARTS_LE_WHOLE` x `_SCALE_NLP` x the roster.

Run:  python -m personal_alm.calibrate.flags [--json OUT]

**Kept in the tree rather than in a scratch directory because its verdict is meant to be re-measured, not
inherited.** The same constraint has carried four successive verdicts -- "safe" (M76), "a bad trade" (M77),
"net-positive" (M78), "certifies nothing" (M87) -- and every overturn came from measuring more of the space
than the verdict before it. Any change to the state vector, the dynamics or the shipped constants voids the
last table, which is exactly why M80 decision 6 ordered this to run only after decisions 1, 2 and 5 landed.

**Two scores, and the second is the one that matters.** `success` is what the engine would publish: `outcome ==
"plan"`, which `solve_case` grants only when a candidate both converged AND satisfied the CVaR bound. That is
the column M77 and M78 were scored on. `meets_confidence` then asks whether the action actually clears the
confidence the case states, measured out of sample on `M_eval` fresh draws. A cell can pass the first and fail
the second by the full width of the bar: M87 found `Near-retiree` certified at `p_goal = 0.000` against a
required 0.90, and found no cell in twenty-four that passed both.

Settings follow M78's so the tables stay comparable: each case at its own `dt_opt` (chosen inside `run_case`),
`M_opt = 8`, and `M_opt = 32` for the flagship, which is its calibrated setting and the level at which M70
found the CVaR constraint actually binds. Budget about two and a quarter hours.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

from ..cases import (ENTREPRENEUR, INDEPENDENCE_50, NEAR_RETIREE, NICOLAS, TAIL_SHOCK,
                     YOUNG_PRO, Case, run_case)
from ..optim import problem as prob

CASES: tuple[Case, ...] = (YOUNG_PRO, INDEPENDENCE_50, NEAR_RETIREE, ENTREPRENEUR, TAIL_SHOCK, NICOLAS)


def run_one(case: Case, enforce: bool, scaled: bool, *, M_eval: int = 200, seed: int = 0,
            n_starts: int = 2) -> dict:
    """One cell. A failure to run IS a result here, so an exception is recorded rather than raised."""
    prob._ENFORCE_PARTS_LE_WHOLE = enforce
    prob._SCALE_NLP = scaled
    m_opt = 32 if case.name == NICOLAS.name else 8
    t = time.perf_counter()
    try:
        res = run_case(case, M_opt=m_opt, M_eval=M_eval, seed=seed, n_starts=n_starts)
    except Exception as exc:  # noqa: BLE001 - see docstring
        return {"case": case.name, "M77": enforce, "scaled": scaled, "M_opt": m_opt,
                "seconds": round(time.perf_counter() - t, 1), "success": False,
                "outcome": "raised", "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "case": case.name, "M77": enforce, "scaled": scaled, "M_opt": m_opt,
        "seconds": round(time.perf_counter() - t, 1),
        "success": bool(res.success),
        "outcome": res.outcome,
        "p_goal": round(float(res.p_goal), 4),
        "confidence": case.confidence,
        "meets_confidence": (None if case.confidence is None else bool(res.p_goal >= case.confidence)),
        "shortfall": (None if res.shortfall is None else round(float(res.shortfall), 2)),
        # **Why an `undetermined` cell is undetermined.** False means phase 1 never converged, so nothing
        # numeric may be claimed of that cell. True with `outcome == "undetermined"` means phase 1 says the
        # goal is fundable and phase 2 certified nothing anyway, which is a solver defect rather than a
        # finding about the household -- a distinction the first run of this matrix could not draw.
        "restore_converged": res.stats.get("restore_converged"),
    }


def matrix(out: Path | None = None) -> dict:
    rows: list[dict] = []
    for enforce, scaled in itertools.product((False, True), (False, True)):
        for case in CASES:
            row = run_one(case, enforce, scaled)
            rows.append(row)
            why = {True: "p1 ok ", False: "p1 stall", None: ""}.get(row.get("restore_converged"), "")
            print(f"  {'OK ' if row['success'] else '   '} M77={enforce!s:5s} scaled={scaled!s:5s} "
                  f"{row['case']:24s} {row['outcome']:18s} p={row.get('p_goal', float('nan')):.3f} "
                  f"{why:9s}{row['seconds']:>6.1f}s", flush=True)
        print(flush=True)

    print("\n  M77   scaled   publishable   meets confidence   which cases")
    summary = []
    for enforce, scaled in itertools.product((False, True), (False, True)):
        cell = [r for r in rows if r["M77"] is enforce and r["scaled"] is scaled]
        ok = [r["case"] for r in cell if r["success"]]
        both = [r["case"] for r in cell if r["success"] and r.get("meets_confidence")]
        summary.append({"M77": enforce, "scaled": scaled, "publishable": len(ok),
                        "cases": ok, "publishable_and_confident": both})
        print(f"  {enforce!s:5s} {scaled!s:6s}   {len(ok):^11d}   {len(both):^16d}   {', '.join(ok) or '-'}")

    union = sorted({c for s in summary for c in s["cases"]})
    print(f"\n  union across settings: {len(union)} of {len(CASES)} - {', '.join(union) or '-'}")
    result = {"rows": rows, "summary": summary, "union": union}
    if out is not None:
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwritten {out}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None, help="write the raw rows here")
    args = ap.parse_args()
    matrix(args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
