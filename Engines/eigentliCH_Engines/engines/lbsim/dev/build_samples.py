"""Freeze the sample artefacts in ``golden/samples`` for the agents building on lbsim (B2, C, D, E).

Run with the family interpreter::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_samples.py [--refresh-upstream]

* ``findings.sample.json``: a real ``LifeBalanceFindings`` from the engine (``lbsim.fast.build``) on the frozen
  lbs case ``lbsim-sample`` (a CHF couple with a property goal and a retirement goal) under calibration 1.1.0.
* ``paths.sample.json``: a ``LifeBalancePaths`` HAND-BUILT here, because the vectorised Monte Carlo is B2's. It
  follows the market rule of LBSIM-07 on the real upstream figures frozen in ``samples/upstream`` (a pcp
  Allocation on the Default Regime, fmre's ReturnSets and inflation for the base and the four scenarios, and
  aggregation's blended state distributions), with yearly steps and a simplified household. Its shape is the
  contract's exactly; its numbers are realistic, not the engine's.
* ``plan.sample.json``: a ``LifeBalancePlan`` HAND-BUILT from the draft model's controls, because the optimiser is
  C's. Costates, solver record and control path are illustrative.

``provenance.made_by`` is ``sample`` on the two hand-built ones and ``provenance.sample_note`` says what is real.
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
    alloc = rd("allocation.json")
    blends = rd("aggregation_blends.json")["blends"]
    request = json.loads((CASES / CASE / "request.json").read_text(encoding="utf-8"))
    sheet = json.loads((CASES / CASE / "sheet.json").read_text(encoding="utf-8"))
    vessel = {k: float(v or 0.0) for k, v in sheet["totals"]["by_vessel"].items()}
    weights = {i["instrument_id"]: i["raw_weight"] for i in alloc["instruments"]}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    def profile(rs: dict) -> np.ndarray:
        prof = {p["key"]: np.array([s["value"] for s in p["states"]]) for p in rs["instrument_profiles"]}
        return sum(w * prof[k] for k, w in weights.items())

    rs = {k: rd(f"return_set_{k}.json") for k in ["base", *SCEN]}
    infl = {k: rd(f"inflation_{k}.json") for k in ["base", *SCEN]}
    r_state = {k: profile(v) for k, v in rs.items()}
    raw_ach = sum(i["raw_weight"] * np.array([s["value"] for s in next(
        p for p in rs["base"]["instrument_profiles"] if p["key"] == i["instrument_id"])["states"]])
        for i in alloc["instruments"])
    max_diff = float(np.max(np.abs(raw_ach - np.array(alloc["curves"]["achieved"]))))
    li = {k: np.array([s["log_inflation"] for s in v["states"]]) for k, v in infl.items()}

    as_of = f.as_of
    goal_dates = {g["goal_id"]: date.fromisoformat(g["target_date"]) for g in request["goals"]}
    horizon = max(d.year for d in goal_dates.values()) - as_of.year
    years = np.arange(horizon + 1)
    ss = np.random.SeedSequence(SEED).spawn(3)
    u = np.random.default_rng(ss[0]).random((N_PATHS, horizon))
    z_prop = np.random.default_rng(ss[1]).standard_normal((N_PATHS, horizon))

    p0 = np.array(blends["base"]["latest"])
    plr = np.array(blends["base"]["long_run"])
    path = next(p for p in f.income_paths if p.code == "today")
    income = np.array([y.gross_chf_per_year for y in path.income] + [0.0] * (horizon + 1))[:horizon]
    free_nom = []
    ledger_free = {n.goal_id: n.free_cash_chf_per_year for n in path.saving_need}
    saving0 = ledger_free["g-home"]
    pi = f.inflation.annual_rate
    partner_income = 92_000.0
    deposit_nom = next(n for n in path.saving_need if n.goal_id == "g-home").target_chf
    ret_target_nom = next(n for n in path.saving_need if n.goal_id == "g-ret").target_chf
    price = float(next(g for g in request["goals"] if g["goal_id"] == "g-home")["target_amount"])
    home_year = goal_dates["g-home"].year - as_of.year
    regimes = []
    mm_prop = ACTIVE_SEED.property
    for key in ["base", *SCEN]:
        W_L = np.full(N_PATHS, vessel.get("free", 0.0))
        W_P = np.full(N_PATHS, vessel.get("pillar_2", 0.0))
        W_3a = np.full(N_PATHS, vessel.get("pillar_3a", 0.0))
        prop = np.zeros(N_PATHS)
        debt = np.zeros(N_PATHS)
        level = np.ones(N_PATHS)
        owns = np.zeros(N_PATHS, dtype=bool)
        series = {"net_worth": [], "deposit_eligible": [], "retirement_capital": []}
        levels = [level.copy()]
        dep_at = None

        def record():
            series["net_worth"].append(W_L + W_P + W_3a + prop - debt)
            series["deposit_eligible"].append(W_L + W_3a + 0.5 * W_P)
            series["retirement_capital"].append(W_L + W_P + W_3a)

        record()
        labels_summary: dict[str, int] = {}
        for s in infl[key]["states"]:
            labels_summary[s["label"]] = labels_summary.get(s["label"], 0) + 1
        for k in range(1, horizon + 1):
            if key != "base" and k <= 5:
                dist = np.array(blends[key]["projected"][12 * k - 1])
                r_s, l_s = r_state[key], li[key]
            else:
                dist = p0 + (plr - p0) * min(k / 5.0, 1.0)
                r_s, l_s = r_state["base"], li["base"]
            cdf = np.cumsum(dist / dist.sum())
            state = np.minimum(np.searchsorted(cdf, u[:, k - 1], side="right"), 24)
            r = r_s[state]
            linf = l_s[state]
            level = level * np.exp(linf)
            # Property: nominal log growth ln(1.03) + 0.8 (log_infl - ln 1.01) plus noise correlated with the state.
            q_state = (cdf[state] - dist[state] / dist.sum() / 2.0)
            z_mkt = np.sqrt(2.0) * _erfinv(2.0 * np.clip(q_state, 1e-6, 1 - 1e-6) - 1.0)
            z = mm_prop.rho_with_market * z_mkt + math.sqrt(1 - mm_prop.rho_with_market ** 2) * z_prop[:, k - 1]
            g_prop = mm_prop.nominal_log_growth + mm_prop.inflation_beta * (linf - mm_prop.inflation_anchor_log) \
                + mm_prop.sigma * z - 0.5 * mm_prop.sigma ** 2
            prop = prop * np.exp(g_prop)
            wage_index = level / (1.0 + pi) ** k
            saving = (saving0 if k <= home_year else ledger_free["g-ret"]) * wage_index + 0.0 * partner_income
            W_L = W_L * np.exp(r) + saving
            W_P = W_P * 1.0125 + 0.12 * 100_000.0 * wage_index
            W_3a = W_3a * 1.015 + 7_258.0
            if k == home_year:
                reach = (W_L + W_3a + 0.5 * W_P) / level >= deposit_nom / (1 + pi) ** home_year
                dep_at = reach
                pay = np.where(reach, deposit_nom, 0.0)
                from_l = np.minimum(pay, W_L)
                W_L = W_L - from_l
                W_P = W_P - np.minimum(pay - from_l, 0.5 * W_P)
                prop = np.where(reach, price * level, 0.0)
                debt = np.where(reach, price * level - deposit_nom, 0.0)
                owns = reach
            debt = np.where(owns, debt * 0.99, 0.0)
            levels.append(level.copy())
            record()
        lv = np.array(levels).T
        bands = {}
        for name, vals in series.items():
            nom = np.array(vals).T
            bands[name] = {"nominal": _quant(nom),
                           "real": {**_quant(nom / lv), "derived": True,
                                    "deflator": "each path's own cumulative inflation from fmre's per-state figures"}}
        ret_real = (np.array(series["retirement_capital"][-1]) / lv[:, -1])
        ret_target_real = ret_target_nom / (1 + pi) ** horizon
        goals = []
        for gid, measure, reached, tgt_nom, tgt_real, gdate, kind, basis_real in (
                ("g-home", "deposit_eligible", dep_at, deposit_nom, deposit_nom / (1 + pi) ** home_year,
                 goal_dates["g-home"], "home", True),
                ("g-ret", "retirement_capital", ret_real >= ret_target_real, ret_target_nom, ret_target_real,
                 goal_dates["g-ret"], "retirement", True)):
            meas = (np.array(series[measure][home_year if kind == "home" else -1])
                    / lv[:, home_year if kind == "home" else -1])
            short = np.maximum(0.0, tgt_real - meas)
            goals.append({"goal_id": gid, "kind": kind, "measure": measure,
                          "target": {"nominal_chf": float(tgt_nom), "real_chf": float(tgt_real),
                                     "amount_basis": "today", "date": gdate.isoformat()},
                          "chance": float(np.mean(reached)), "chance_basis": "real" if basis_real else "nominal",
                          "n_reached": int(np.sum(reached)), "median_shortfall_chf": float(np.median(short))})
        label = ({"de": "Heutige Einschätzung", "en": "Current assessment"} if key == "base" else
                 {p["policy"]: {"de": p["label_de"], "en": p["label_en"]}
                  for p in rd("scenario_policies.json")}[key])
        regimes.append({
            "key": key, "label": label, "regime_id": BASE if key == "base" else SCEN[key],
            "kind": "base" if key == "base" else "scenario", "scenario_years": None if key == "base" else 5,
            "return_set_id": rs[key]["return_set_id"],
            "inflation_pass_through": None if key == "base" else
            rs[key]["provenance"]["inflation_pass_through"]["calibration_version"],
            "inflation": {"source": infl[key].get("source") or f"fmre /v1/inflation?currency=CHF ({key})",
                          "labels_summary": labels_summary},
            "bands": bands, "goals": goals})

    log_infl_base = li["base"]
    target = np.array(alloc["curves"]["target"])
    achieved = np.array(alloc["curves"]["achieved"])
    allocation_view = {
        "allocation_id": alloc["artefact_id"], "mandate_name": alloc["mandate_name"], "currency": "CHF",
        "allocation_basis": alloc.get("basis", "nominal"), "date": alloc["date"], "regime_id": alloc["regime_id"],
        "instruments": [{"instrument_id": i["instrument_id"], "name": i["name"], "role": i["role"],
                         "weight": i["weight"]} for i in alloc["instruments"] if i["weight"] > 1e-9],
        "by_role": {k: (v if abs(v) > 1e-12 else 0.0) for k, v in alloc["weights_by_role"].items()},
        "state_probability": alloc["curves"]["regime"],
        "curves": {"nominal": {"target": list(target), "achieved": list(achieved), "derived": False},
                   "real": {"target": list(target - log_infl_base), "achieved": list(achieved - log_infl_base),
                            "derived": True},
                   "log_inflation": list(log_infl_base),
                   "inflation_labels": [s["label"] for s in infl["base"]["states"]]}}
    market_model = {
        "rule": {"de": "Jedes Jahr wird ein Zustand von 1 bis 25 aus der Verteilung des Regimes gezogen; das erste Jahr "
                       "ist die heutige Einschätzung, danach kehrt sie in fünf Jahren linear zum langjährigen Mittel "
                       "zurück. Die Rendite ist die Summe der Gewichte mal der Rendite jedes Instruments im gezogenen "
                       "Zustand. Ein Szenario bestimmt die ersten fünf Jahre, danach gilt die heutige Einschätzung.",
                 "en": "Each year a state from 1 to 25 is drawn from the Regime's distribution; the first year is the "
                       "current assessment, which then reverts linearly to the long-run mean over five years. The "
                       "return is the sum of the weights times each instrument's return in the drawn state. A "
                       "scenario drives the first five years, then the current assessment applies."},
        "reversion_years": 5.0, "state_persistence": 0.0, "weights": "renormalised",
        "check": {"achieved_reproduced": max_diff <= 1e-9, "max_abs_diff": max_diff},
        "property": {"nominal_log_growth": mm_prop.nominal_log_growth, "inflation_beta": mm_prop.inflation_beta,
                     "inflation_anchor_log": mm_prop.inflation_anchor_log, "sigma": mm_prop.sigma,
                     "rho_with_market": mm_prop.rho_with_market},
        "pass_through": {"wages": 1.0, "spending": 1.0, "debt": "nominal", "bvg_credits": "nominal",
                         "fixed_contribution": "nominal"}}
    key = content_id("IDK", {"kind": "paths", "findings": f.provenance.idempotency_key, "allocation_id":
                             alloc["artefact_id"], "seed": SEED, "n_paths": N_PATHS, "horizon_years": horizon,
                             "income_path": "today", "numpy": ".".join(np.__version__.split(".")[:2])})
    body = {
        "findings_artefact_id": f.artefact_id, "client_ref": f.client_ref,
        "life_balance_sheet_id": f.life_balance_sheet_id, "allocation_id": alloc["artefact_id"],
        "as_of": f.as_of.isoformat(), "calibration_version": ACTIVE_SEED.version, "start_year": f.as_of.year,
        "horizon_years": int(horizon), "n_paths": N_PATHS, "seed": SEED, "income_path": "today",
        "policy": {"kind": "stated_plan", "spending_chf_per_year": float(request["risk"]["spend_now_per_year"]), "spending_indexed": True,
                   "pensum": 1.0, "saving_source": "cash_flow"},
        "regimes": regimes, "allocation_view": allocation_view, "market_model": market_model,
        "provenance": {
            "engine_version": ENGINE_VERSION, "contract_versions": CONTRACT_VERSIONS,
            "calibration_version": ACTIVE_SEED.version, "calibration_hash": calibration_hash(ACTIVE_SEED),
            "idempotency_key": key, "made_by": "sample",
            "sample_note": ("Hand-built by dev/build_samples.py, not by the engine's Monte Carlo (B2's): yearly "
                            "steps, a simplified household (one saving figure from the findings' income path, a "
                            "flat BVG credit, the deposit paid from free wealth first, the mortgage amortised at "
                            "1 % a year), the market rule of LBSIM-07 on real upstream figures. The Allocation is "
                            "pcp's bench Allocation on the Default Regime (client 'bench'), reused for a sample "
                            "household; a real run would refuse the client mismatch (409)."),
            "seeds": {"state_uniforms": SEED, "property_noise": SEED, "spare": SEED},
            "numpy_version": np.__version__,
            "upstream": {"lbs": f.provenance.upstream["lbs"],
                         "pcp": {"artefact_id": alloc["artefact_id"], "contract": "pcp-allocation@1.0.0",
                                 "sha256": sha256(alloc)},
                         "aggregation": {BASE: "see golden/samples/upstream/aggregation_blends.json",
                                         **{rid: "see golden/samples/upstream/aggregation_blends.json"
                                            for rid in SCEN.values()}},
                         "fmre": {"return_set_ids": {k: v["return_set_id"] for k, v in rs.items()},
                                  "inflation_sha256": {k: sha256(v) for k, v in infl.items()},
                                  "ipt": rs["depression"]["provenance"]["inflation_pass_through"]["calibration_id"]}}},
    }
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
    grid = [0.5] * 20 + [1.0] * 10
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
        "horizon": {"solved_years": 20.0, "total_years": float(paths.horizon_years),
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
