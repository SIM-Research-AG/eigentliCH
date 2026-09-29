"""The flagship at its calibrated setting, on the settled case: the figures §31.4.2 will carry.

M88's sweep ran at `M_opt = 8` to locate the boundary at a cost that allowed six horizons and two rates. Its
own finding 1 says none of it is a final figure, because M87 finding 3 measured that certification at 8 does
not control the out-of-sample score and this case's calibrated setting is 32. A book paragraph may not be
built on the exploratory setting.

So: the settled case -- `own_use_share = 0.2` and `swr = 0.030` per the author's ruling of 26 August, requirement
1 333 333 -- at `M_opt = 32`, `n_starts = 3`, `M_eval = 400`, which is DEFAULT_SETTINGS. Four horizons, chosen
from where the cheap sweep put the boundary: fifty is the book's question, fifty-two was the first plan,
fifty-three scored highest of the short horizons, sixty-five was the only one to clear 0.90.

Expect roughly fifteen to twenty minutes a cell.
"""
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

# Walked up from this module rather than spelled out: an absolute path here named the estate folder,
# and the folder was renamed to eigentliCH on 21 September 2026, which broke this script silently.
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "engines" / "Life_Balance_Sheet"))
OUT = Path(__file__).resolve().parent / "m88_calibrated.json"

from personal_alm import cases as C  # noqa: E402
from personal_alm.ui.output import fi_drawable_requirement  # noqa: E402

HORIZONS = (5.0, 7.0, 8.0, 20.0)


def main() -> int:
    req = fi_drawable_requirement(C.NICOLAS.x0, C.NICOLAS.params(), C.NICOLAS.goal.params["G"])
    print(f"  settled case: swr={C.NICOLAS.goal.params['swr']}  requirement {req:,.0f}  "
          f"confidence {C.NICOLAS.confidence}\n", flush=True)
    rows = []
    for h in HORIZONS:
        case = replace(C.NICOLAS, goal=replace(C.NICOLAS.goal, horizon_years=h))
        t = time.perf_counter()
        res = C.run_case(case, M_opt=32, M_eval=400, seed=0, n_starts=3)
        sf = None if res.shortfall is None else round(float(res.shortfall), 2)
        row = {"h": h, "age": 45.0 + h, "outcome": res.outcome, "success": bool(res.success),
               "p_goal": round(float(res.p_goal), 4),
               "meets_confidence": bool(res.p_goal >= (C.NICOLAS.confidence or 0.0)),
               "shortfall": sf, "binding": str(res.binding),
               "seconds": round(time.perf_counter() - t, 1)}
        rows.append(row)
        print(f"  {'OK ' if row['success'] else '   '}{'conf' if row['meets_confidence'] else '    '} "
              f"age {row['age']:.0f}  {row['outcome']:18s} p={row['p_goal']:.3f}  "
              f"short {'-' if sf is None else format(sf, ',.0f'):>10s}/yr  "
              f"binds {row['binding']:<18s} {row['seconds']:>7.1f}s", flush=True)
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
