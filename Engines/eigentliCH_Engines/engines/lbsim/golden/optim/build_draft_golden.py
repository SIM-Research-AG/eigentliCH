"""Build ``golden/optim/draft_test_optim.json``: the draft's slow ``test_optim`` solves, run by the draft itself.

Run under the draft's own interpreter (the draft is read only; nothing is written into it):

    <Life_Balance_Sheet>/.venv/Scripts/python -X utf8 golden/optim/build_draft_golden.py

It records, for each of the three solves ``tests/test_optim.py`` makes (``sol_90`` and the ``tight`` / ``loose``
pair of ``test_relaxing_confidence_raises_consumption``), the first control, the in-sample chance, the CVaR, the
outcome, the costates, the exchange rate and the solver record. ``tests/optim/test_reproduce_draft.py`` holds the
port to them under calibration 1.0.0 with the draft's market term.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

DRAFT = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\engines\Life_Balance_Sheet")
OUT = Path(__file__).resolve().parent / "draft_test_optim.json"

sys.path.insert(0, str(DRAFT))

import casadi  # noqa: E402
import numpy  # noqa: E402
from personal_alm.model.params import Params  # noqa: E402
from personal_alm.model.state import State  # noqa: E402
from personal_alm.optim.problem import solve_fi  # noqa: E402

P = Params()

#: The three solves of the draft's ``tests/test_optim.py``, with its own arguments.
CASES = {
    "sol_90": dict(horizon_years=5.0, epsilon=0.10, psi=1.0, dt_opt=0.5, M=14, seed=0, n_starts=2),
    "tight": dict(horizon_years=5.0, epsilon=0.10, psi=1.0, dt_opt=0.5, M=12, seed=0, n_starts=2),
    "loose": dict(horizon_years=5.0, epsilon=0.50, psi=1.0, dt_opt=0.5, M=12, seed=0, n_starts=2),
}


def nicolas_45() -> State:
    return State.individual(W_L=0.6e6, W_R=5.0e6, D=1.8e6, E=0.90, N=0.90, H=0.70, W_res=1.0e6)


def record(res, wall: float) -> dict:
    st = res.stats
    return {
        "u0": res.u0,
        "p_fi_insample": res.p_fi_insample,
        "cvar_shortfall": res.cvar_shortfall,
        "objective": res.objective,
        "success": res.success,
        "outcome": st.get("outcome"),
        "s_star": st.get("s_star"),
        "cvar_bound": st.get("cvar_bound"),
        "cvar_constrained": st.get("cvar_constrained"),
        "return_status": st.get("return_status"),
        "iter_count": st.get("iter_count"),
        "seed": st.get("seed"),
        "seed_attempt": st.get("seed_attempt"),
        "costates": {"lam_W": res.costates.lam_W, "lam_E": res.costates.lam_E, "lam_N": res.costates.lam_N,
                     "lam_H": res.costates.lam_H},
        "exchange_rate": {"winner": res.exchange_rate.winner, "ratio": res.exchange_rate.ratio,
                          "networking_value": res.exchange_rate.networking_value,
                          "overtime_value": res.exchange_rate.overtime_value},
        "u_path": res.u_path,
        "wall_clock_s": wall,
    }


def main() -> int:
    only = sys.argv[1:] or list(CASES)
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"cases": {}}
    out["made_by"] = "golden/optim/build_draft_golden.py under the draft's interpreter"
    out["draft"] = str(DRAFT / "personal_alm")
    out["versions"] = {"python": platform.python_version(), "casadi": casadi.__version__,
                       "numpy": numpy.__version__}
    out["state"] = {"W_L": 0.6e6, "W_R": 5.0e6, "D": 1.8e6, "E": 0.90, "N": 0.90, "H": 0.70, "W_res": 1.0e6}
    for name in only:
        kw = CASES[name]
        t0 = time.monotonic()
        res = solve_fi(nicolas_45(), params=P, **kw)
        wall = time.monotonic() - t0
        out["cases"][name] = {"arguments": kw, **record(res, wall)}
        OUT.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
        print(name, res.stats.get("outcome"), res.u0["C"], f"{wall:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
