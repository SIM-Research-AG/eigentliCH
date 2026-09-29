"""Freeze the sample artefacts in ``golden/samples`` for the agents building on lbsim (B2, C, D, E).

Run with the family interpreter::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_samples.py [--refresh-upstream]

* ``findings.sample.json``: a real ``LifeBalanceFindings`` from the engine (``lbsim.fast.build``) on the frozen
  lbs case ``lbsim-sample`` (a CHF couple with a property goal and a retirement goal) under the active calibration.
* ``paths.sample.json``: the engine's own ``LifeBalancePaths`` (B2's Monte Carlo, since 29.09.2026) on the
  upstream snapshot ``golden/upstream`` (pcp's bench Allocation served under the sample's client, aggregation's
  Regimes, fmre's ReturnSets and inflation), 2000 paths, the default seed. Until B2 it was hand-built here.
* ``plan.sample.json``: a ``LifeBalancePlan`` HAND-BUILT from the draft model's controls, because the optimiser is
  C's. Costates, solver record and control path are illustrative.

``provenance.made_by`` is ``sample`` on the hand-built plan and ``provenance.sample_note`` says what is real; the
paths sample is ``engine`` with a note on the Allocation's client.
``--refresh-upstream`` re-reads the upstream snapshot from the scratch copies fetched read only on 29.09.2026
(``curl`` GETs to pcp 8007, aggregation 8004 and fmre 8006); without it the frozen snapshot is used.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

from lbsim import ENGINE_VERSION
from lbsim.calibration import ACTIVE_SEED, calibration_hash
from lbsim.contracts import (CONTRACT_VERSIONS, LbsRequest, LbsSheet, LifeBalanceFindings, LifeBalancePaths,
                             LifeBalancePlan)
from lbsim.fast.build import build_findings
from lbsim.ids import content_id, sha256

HERE = Path(__file__).resolve().parents[1]
CASES = HERE / "golden" / "lbs_cases"
OUT = HERE / "golden" / "samples"
UP = OUT / "upstream"
SCRATCH = Path(r"C:\Users\nicol\AppData\Local\Temp\claude\c--Users-nicol-Desktop-SIM-NAS-Projects-Engines"
               r"\3096e42c-035e-4edb-97af-a4545f56ad76\scratchpad\lbsim_b1")
CASE = "lbsim-sample"
BASE = "RGM-e2658e8e9bbbc81e"
SCEN = {"depression": "RGM-1af6968e287768c9", "hyperinflation": "RGM-59eebfaf7744d8ec",
        "stagflation": "RGM-6bb531998bfefc4d", "deferral": "RGM-c0ed086f1916984e"}
WEIGHTS = {"CH": 0.5, "EU": 0.3, "US": 0.2}
N_PATHS = 2000
SEED = 20260929
QS = (5, 10, 25, 50, 75, 90, 95)


def _blend(regime: dict) -> list[list[float] | None]:
    eco = {e["code"]: e for e in regime["economies"]}
    out = []
    for i in range(len(regime["dates"])):
        parts = [(w, eco[c]["distribution"][i]) for c, w in WEIGHTS.items() if eco[c]["distribution"][i]]
        if not parts:
            out.append(None)
            continue
        tot = sum(w for w, _ in parts)
        out.append(list(sum(w / tot * np.array(d) for w, d in parts)))
    return out


def refresh_upstream() -> None:
    UP.mkdir(parents=True, exist_ok=True)
    rd = lambda n: json.loads((SCRATCH / n).read_text(encoding="utf-8"))  # noqa: E731
    (UP / "allocation.json").write_text(json.dumps(rd("pcp_alloc.json"), ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    policies = rd("agg_scen.json")
    blends = {}
    base = rd("agg_base.json")
    b = _blend(base)
    assessed = [d for d in b if d is not None]
    blends["base"] = {"regime_id": BASE, "latest": b[-1], "long_run": list(np.mean(assessed, axis=0)),
                      "dates": [base["dates"][0], base["dates"][-1]], "n_dates": len(assessed)}
    for key, rid in SCEN.items():
        s = rd(f"agg_{rid}.json")
        sb = _blend(s)
        months = s["provenance"]["scenario"]["horizon_months"]
        blends[key] = {"regime_id": rid, "projected": sb[-months:], "horizon_months": months,
                       "projected_from": s["provenance"]["scenario"]["projected_from"]}
    (UP / "aggregation_blends.json").write_text(json.dumps(
        {"about": ("aggregation's state distributions blended with the Allocation's economy weights "
                   f"{WEIGHTS}: the base Regime's latest and its mean over every assessed date, and each "
                   "scenario Regime's projected months. Reduced from GET /regime/{id} (read only, 29.09.2026)."),
         "weights": WEIGHTS, "blends": blends, "scenario_listing": policies}, indent=1), encoding="utf-8")
    labels = [{"policy": "depression", "label_en": "Depression", "label_de": "Depression"},
              {"policy": "hyperinflation", "label_en": "Hyperinflation", "label_de": "Hyperinflation"},
              {"policy": "stagflation", "label_en": "Stagflation", "label_de": "Stagflation"},
              {"policy": "deferral", "label_en": "Deferral", "label_de": "Aufschub"}]
    (UP / "scenario_policies.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, rid in [("base", BASE), *SCEN.items()]:
        rs_name = "rs_base.json" if key == "base" else f"rs_{rid}.json"
        inf_name = "infl_base.json" if key == "base" else f"infl_{rid}.json"
        (UP / f"return_set_{key}.json").write_text(json.dumps(rd(rs_name), ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
        (UP / f"inflation_{key}.json").write_text(json.dumps(rd(inf_name), ensure_ascii=False, indent=1),
                                                  encoding="utf-8")


def rd(name: str) -> dict:
    return json.loads((UP / name).read_text(encoding="utf-8"))


def findings_sample() -> LifeBalanceFindings:
    records = json.loads((CASES / "records.json").read_text(encoding="utf-8"))["records"]
    sheet = json.loads((CASES / CASE / "sheet.json").read_text(encoding="utf-8"))
    request = json.loads((CASES / CASE / "request.json").read_text(encoding="utf-8"))
    return build_findings(LbsSheet.model_validate(sheet), LbsRequest.model_validate(request), records,
                          ACTIVE_SEED, sheet_sha256=sha256(sheet), lbs_url="http://127.0.0.1:8013")


def _quant(x: np.ndarray) -> dict[str, list[float]]:
    q = np.percentile(x, QS, axis=0)
    return {f"p{p:02d}": [float(v) for v in row] for p, row in zip(QS, q)}


def paths_sample(f: LifeBalanceFindings) -> LifeBalancePaths:
    """The engine's own paths (B2's Monte Carlo) on the frozen upstream snapshot ``golden/upstream``.

    The Allocation is pcp's bench Allocation (client ``bench``), served under the sample household's client, as the
    test stand-in does; a real run refuses that mismatch (409). The sample note says so."""
    sys.path.insert(0, str(HERE / "tests"))
    from stub import Stub, bundle  # noqa: PLC0415
    from lbsim.paths.build import build_paths  # noqa: PLC0415
    from lbsim.paths.household import stated_plan  # noqa: PLC0415

    records = json.loads((CASES / "records.json").read_text(encoding="utf-8"))["records"]
    sheet = LbsSheet.model_validate(json.loads((CASES / CASE / "sheet.json").read_text(encoding="utf-8")))
    request = LbsRequest.model_validate(json.loads((CASES / CASE / "request.json").read_text(encoding="utf-8")))
    plan = stated_plan(sheet, request, records, ACTIVE_SEED, f, income_path=None, horizon_years=None,
                       max_horizon_years=60, reference_age=65.0)
    b = bundle(Stub((CASE,)), sheet)
    p = build_paths(f, plan, b, ACTIVE_SEED, n_paths=N_PATHS, seed=SEED)
    note = ("Made by the engine (lbsim.paths.build) on the upstream snapshot golden/upstream "
            "(dev/build_upstream_snapshot.py). The Allocation is pcp's bench Allocation on the Default Regime "
            "(client 'bench'), served under this sample household's client for the sample; a real run would "
            "refuse the client mismatch (409).")
    body = p.model_dump(mode="json", exclude={"artefact_id"})
    body["provenance"]["sample_note"] = note
    return LifeBalancePaths(artefact_id=content_id("LSP", body), **body)


def _erfinv(y: np.ndarray) -> np.ndarray:
    """Inverse error function (Giles 2012 single-precision approximation, refined by two Newton steps)."""
    w = -np.log((1.0 - y) * (1.0 + y))
    small = w < 5.0
    w1 = w - 2.5
    p1 = 2.81022636e-08
    for c in (3.43273939e-07, -3.5233877e-06, -4.39150654e-06, 0.00021858087, -0.00125372503, -0.00417768164,
              0.246640727, 1.50140941):
        p1 = c + p1 * w1
    w2 = np.sqrt(np.maximum(w, 5.0)) - 3.0
    p2 = -0.000200214257
    for c in (0.000100950558, 0.00134934322, -0.00367342844, 0.00573950773, -0.0076224613, 0.00943887047,
              1.00167406, 2.83297682):
        p2 = c + p2 * w2
    x = np.where(small, p1, p2) * y
    for _ in range(2):
        err = np.array([math.erf(v) for v in x]) - y
        x = x - err / (2.0 / math.sqrt(math.pi) * np.exp(-x * x))
    return x


def plan_sample(f: LifeBalanceFindings, paths: LifeBalancePaths) -> LifeBalancePlan:
    base = next(r for r in paths.regimes if r.key == "base")
    home = next(g for g in base.goals if g.goal_id == "g-home")
    controls = {"tau_Y": 0.42, "tau_E": 0.02, "tau_N": 0.03, "tau_H": 0.20, "C": 118_000.0, "m_E": 2_000.0,
                "m_N": 1_000.0, "p_A": 0.0}
    # The active calibration's grid (1.3.0, DECISIONS O-18: 0.5-year steps to the 10-year cap).
    from lbsim.optim.grid import build as _build_grid  # noqa: PLC0415 - casadi-free
    opt = ACTIVE_SEED.optimiser
    g = _build_grid(float(paths.horizon_years), opt.grid, opt.grid_rule,
                    cap=opt.max_solve_horizon_years or opt.grid[-1][0])
    grid = list(g.dts)
    t, steps = 0.0, []
    for dt in grid:
        steps.append({"t_years": t, "dt_years": dt, "controls": controls})
        t += dt
    body = {
        "client_ref": f.client_ref, "life_balance_sheet_id": f.life_balance_sheet_id,
        "paths_artefact_id": paths.artefact_id, "calibration_version": ACTIVE_SEED.version, "outcome": "solved",
        "goal": {"goal_id": "g-home", "kind": "home", "confidence": ACTIVE_SEED.optimiser.confidence},
        "extra_goals": ["g-ret"],
        "action_now": {"work_share": 0.42, "learning_hours_per_week": 2.0, "network_hours_per_week": 3.0,
                       "rest_hours_per_week": 20.0, "consumption_chf_per_year": 118_000.0,
                       "saving_chf_per_year": 33_000.0, "education_spend_chf_per_year": 2_000.0,
                       "network_spend_chf_per_year": 1_000.0, "amortisation_chf_per_year": 0.0},
        "framing": {"de": "Was die Rechnung annimmt: diese Zahlen beschreiben die Annahmen der Planrechnung für diese "
                          "Periode, keine Empfehlung.",
                    "en": "What the calculation assumes: these figures describe the plan calculation's assumptions "
                          "for this period, not a recommendation."},
        "chance": {"in_sample": min(1.0, home.chance + 0.02), "out_of_sample": home.chance, "n_out_of_sample": 2000,
                   "seed_out": SEED + 500_000},
        "shortfall_cvar_chf": 0.0,
        "exchange_rate": {"winner": "networking", "ratio": 1.8, "dominant": "tau_N"},
        "costates": {"W": 1.0e-5, "E": 0.42, "N": 0.31, "H": 0.27},
        "control_path": steps,
        "horizon": {"solved_years": float(g.times[-1]), "total_years": float(paths.horizon_years),
                    "beyond_cap_rule": "zero_return_terminal"},
        "solver": {"return_status": "Solve_Succeeded", "iterations": 212, "wall_clock_s": 2870.0, "seed": SEED,
                   "seed_attempt": 0, "M_opt": 14, "grid": grid, "casadi_version": "3.7.2",
                   "ipopt_version": None},
        "provenance": {"engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
                       "calibration_version": ACTIVE_SEED.version, "calibration_hash": calibration_hash(ACTIVE_SEED),
                       "idempotency_key": content_id("IDK", {"kind": "plan", "paths": paths.provenance.idempotency_key,
                                                             "seed": SEED}),
                       "made_by": "sample",
                       "sample_note": ("Hand-built by dev/build_samples.py, not by the optimiser (C's): the draft's "
                                       "control vector at a plausible working point held over the variable grid; "
                                       "costates, exchange rate and solver record are illustrative; the chance is "
                                       "the paths sample's."),
                       "seeds": {"in_sample": SEED, "out_of_sample": SEED + 500_000},
                       "upstream": {"paths": paths.artefact_id}},
    }
    return LifeBalancePlan(artefact_id=content_id("LSO", body), **body)


def main() -> int:
    if "--refresh-upstream" in sys.argv:
        refresh_upstream()
    OUT.mkdir(parents=True, exist_ok=True)
    f = findings_sample()
    paths = paths_sample(f)
    plan = plan_sample(f, paths)
    for name, art in (("findings.sample.json", f), ("paths.sample.json", paths), ("plan.sample.json", plan)):
        (OUT / name).write_text(json.dumps(art.model_dump(mode="json"), ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
        print(name, art.artefact_id)
    base = next(r for r in paths.regimes if r.key == "base")
    print({r.key: {g.goal_id: round(g.chance, 3) for g in r.goals} for r in paths.regimes})
    print("median net worth end", round(base.bands["net_worth"].nominal.p50[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
