"""Build the Parameters page's presets once, validate them with pcp, and save them to the content store.

    python dev/build_presets.py                      # build, validate with pcp, print; saves nothing
    python dev/build_presets.py --save --curator ID  # ... and save both keys as a new version each

Two content keys in schema ``eigentlich`` (kind ``reference``), saved with ``save_content()`` as role
curator, so every save is a new version and a curator can edit them later on the Questionnaires page
(DECISIONS C-22):

* ``reference/target-curve-presets``: named 25-state target curves (state 1 crisis .. 25 boom) in
  **percent per year**. The role-based ones take the shape of fmre's four role profiles (the ReturnSet's
  ``role_profiles``, annualised log returns, converted to percent) and rescale it to a stated level and
  amplitude; the others are closed-form shapes. Each carries its formula, its mean, minimum and maximum
  (data, so the cockpit computes none of them) and its provenance (fmre calibration id and ReturnSet).
* ``reference/mandate-presets``: ready mandates in pcp's shape (``pcp-mandate@1.0.0``, fractions, the
  curve as log returns), each naming its curve preset, with its universe drawn from fmre's active
  register, and the result of pcp's ``POST /validate`` against the latest Regime and the ReturnSet fmre
  serves for it in the mandate's currency.

numpy is allowed here: this is a development script, not the cockpit package (C-07 is about
``src/cockpit``). The cockpit reads the stored numbers and never recomputes them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cockpit.mandate import BOUND_SOURCE, BUCKETS, CONTRACT, PRESET_KEYS, pct_to_log  # noqa: E402

N = 25
STATES = np.arange(1, N + 1)
X = (STATES - 13) / 12.0            # -1 at crisis, 0 at state 13, +1 at boom
#: Instruments fmre is deactivating (29.09.2026); never in a preset even if still served.
EXCLUDED = {"INS-short-msci-us", "INS-cs-long-vola"}
ROLE_ORDER = ("gain", "income", "stabilisation", "protection")
#: Every preset holds at least this many active instruments in each role, so lbs's derived role bounds
#: (which replace the preset's role bounds when a client's parameters are applied) always have somewhere to
#: go (C-29).
MIN_PER_ROLE = 2
#: mp@1.0.0 (C-22) left a role empty in four presets; mp@1.1.0 holds every role (C-29).
MANDATE_VERSION = "mp@1.1.0"
#: pcp's /validate is also asked with every role floor at each of these levels, the preset's own role
#: ceilings kept (C-29): lbs derives role floors of about 0.05 to 0.26 in the use cases.
ROLE_FLOOR_LEVELS = (0.05, 0.10, 0.15)


# ---- target curves -----------------------------------------------------------------------------

def rescale(shape: np.ndarray, mean: float, scale: float) -> np.ndarray:
    """A role profile's shape around a new mean: ``mean + scale * (p - mean(p))``."""
    return mean + scale * (shape - shape.mean())


def curve_presets(return_set: dict) -> list[dict]:
    roles = {p["role"] if "role" in p and p["role"] else p["key"]: p for p in return_set["role_profiles"]}
    pct = {r: np.expm1(np.array([s["value"] for s in roles[r]["states"]])) * 100.0 for r in ROLE_ORDER}
    prov = {"source": "fmre ReturnSet role_profiles", "calibration_id": return_set["provenance"]["calibration_id"],
            "return_set_id": return_set["return_set_id"], "as_of": return_set.get("as_of"),
            "unit_of_source": "annualised_log_return, converted to percent as (exp(v) - 1) x 100"}
    out = []

    def add(key, name, family, desc, points, formula, provenance=None):
        points = np.round(points, 2)
        out.append({"key": key, "name": name, "family": family, "description": desc,
                    "points_pct": [float(v) for v in points], "mean_pct": round(float(points.mean()), 4),
                    "min_pct": float(points.min()), "max_pct": float(points.max()), "formula": formula,
                    "provenance": provenance or {"source": "closed-form shape (dev/build_presets.py)"}})

    role_text = {
        "gain": ("Gain role", "The gain role's shape: deep in crisis, strongest in boom. Scaled to half its "
                 "amplitude around 4 % a year, so the target asks for growth without asking for the full crisis loss."),
        "income": ("Income role", "The income role's shape: a loss in deep crisis, steady carry through the middle "
                   "states, highest in boom; around 3 % a year."),
        "stabilisation": ("Stabilisation role", "The stabilisation role's shape: strongest in the contraction "
                          "states, flat in expansion, around 3 % a year."),
        "protection": ("Protection role", "The protection role's shape: highest in crisis, lowest in stagnation, "
                       "rising gently into boom, around 3 % a year."),
    }
    levels = {"gain": (4.0, 0.5), "income": (3.0, 1.0), "stabilisation": (3.0, 1.0), "protection": (3.0, 1.0)}
    for r in ROLE_ORDER:
        mean, scale = levels[r]
        add(f"role-{r}", *role_text[r][:1], "role", role_text[r][1], rescale(pct[r], mean, scale),
            f"{mean:g} + {scale:g} x (fmre {r} profile in % - its mean)", {**prov, "role": r})
    blend = 0.4 * pct["gain"] + 0.2 * pct["income"] + 0.2 * pct["stabilisation"] + 0.2 * pct["protection"]
    add("balanced-blend", "Balanced blend", "blend",
        "40 % gain, 20 % each of income, stabilisation and protection: the four role shapes mixed and "
        "centred on 3.5 % a year.", rescale(blend, 3.5, 1.0),
        "3.5 + (0.4 gain + 0.2 income + 0.2 stabilisation + 0.2 protection, in % - its mean)",
        {**prov, "weights": {"gain": 0.4, "income": 0.2, "stabilisation": 0.2, "protection": 0.2}})
    growth_income = 0.6 * pct["gain"] + 0.4 * pct["income"]
    add("growth-and-income", "Growth and income", "blend",
        "60 % gain, 40 % income: an equity-led shape softened by carry, centred on 4 % a year at 70 % of "
        "its amplitude.", rescale(growth_income, 4.0, 0.7),
        "4 + 0.7 x (0.6 gain + 0.4 income, in % - its mean)", {**prov, "weights": {"gain": 0.6, "income": 0.4}})
    add("u-profile", "U-profile (barbell)", "shape",
        "Strong in crisis and in boom, weak in the middle: 7 % at both ends, 1 % at state 13.",
        1.0 + 6.0 * X ** 2, "1 + 6 x ((state - 13) / 12)^2")
    add("all-weather", "All-weather", "shape",
        "Gently U-shaped with a low amplitude: 3.8 % at both ends, 2.3 % in the middle.",
        2.3 + 1.5 * X ** 2, "2.3 + 1.5 x ((state - 13) / 12)^2")
    add("steady-return", "Steady return", "shape", "Flat: the same 3.5 % a year in every state.",
        np.full(N, 3.5), "3.5 in every state")
    add("crisis-resilient", "Crisis-resilient", "shape",
        "Rising towards crisis: 5.5 % in state 1 falling to 1.5 % in state 25; asks most when markets are worst.",
        1.5 + 4.0 * (N - STATES) / (N - 1), "1.5 + 4 x (25 - state) / 24")
    add("growth-tilt", "Growth tilt", "shape",
        "Rising towards boom: -2 % in state 1 to 8 % in state 25; accepts a loss in crisis for more in boom.",
        -2.0 + 10.0 * (STATES - 1) / (N - 1), "-2 + 10 x (state - 1) / 24")
    add("capital-preservation", "Capital preservation", "shape",
        "Flat and low, never negative: 1 % a year in every state.", np.full(N, 1.0), "1 in every state")
    add("recovery-seeker", "Recovery seeker", "shape",
        "An S-curve: modest in crisis (0 %), steepest through the middle states, levelling at 6 % in boom.",
        3.0 + 3.0 * np.tanh(2.2 * X) / np.tanh(2.2), "3 + 3 x tanh(2.2 x (state - 13) / 12) / tanh(2.2)")
    for c in out:
        assert len(c["points_pct"]) == N and all(np.isfinite(c["points_pct"]))
    assert min(next(c for c in out if c["key"] == "capital-preservation")["points_pct"]) >= 0
    return out


# ---- mandate presets ----------------------------------------------------------------------------

def b(lo: float, hi: float) -> dict:
    return {"lower": round(lo / 100, 6), "upper": round(hi / 100, 6)}


#: Each preset: its universe (fmre ids, chosen by role, asset class and region; checked against the
#: active register below), the cap, the bounds in percent, the curve preset and the regime blend.
MANDATES = [
    {"key": "conservative-chf", "name": "Conservative CHF", "currency": "CHF", "curve": "capital-preservation",
     "description": "Capital first: a CHF core of cash, hedged bonds and Swiss credit, a little Swiss equity, "
                    "gold and market-neutral strategies. Target 1 % a year in every state.",
     "universe": ["INS-chf-cash", "INS-bloomberg-multiverse-h-chf", "INS-global-governmental-bonds",
                  "INS-precious-metals", "INS-chf-corporate-loans-ig", "INS-sxi-real-estate",
                  "INS-global-high-yields", "INS-bloomberg-market-neutral-hf", "INS-global-macro",
                  "INS-swiss-dividend-equity", "INS-swiss-performance-index", "INS-global-equities"],
     "max": 20, "esg": 0.0,
     "bounds": {"currency": {"CHF": (80, 100)},
                "role": {"Gain": (10, 30), "Income": (15, 40), "Stabilisation": (5, 25), "Protection": (25, 60)},
                "liquidity": {"Daily": (60, 100)},
                "region": {"Switzerland": (30, 80)},
                "asset_class": {"Equity": (10, 30), "Cash": (0, 20)}},
     "regime": {"weights": {"CH": 70, "EU": 20, "US": 10}}},
    {"key": "balanced-chf", "name": "Balanced CHF", "currency": "CHF", "curve": "balanced-blend",
     "description": "The house's balanced mix for a Swiss client: 25 to 50 % equity (home and world), CHF "
                    "credit and Swiss real estate, diversifiers and protection.",
     "universe": ["INS-ch-equities", "INS-swiss-performance-index", "INS-global-equities", "INS-us-equities",
                  "INS-eu-equities", "INS-em-equities", "INS-chf-corporate-loans-ig", "INS-global-high-yields",
                  "INS-sxi-real-estate", "INS-infrastructure", "INS-global-macro", "INS-trend-following",
                  "INS-bloomberg-multiverse-h-chf", "INS-chf-cash", "INS-precious-metals"],
     "max": 15, "esg": 0.0,
     "bounds": {"currency": {"CHF": (50, 100)},
                "role": {"Gain": (30, 50), "Income": (15, 35), "Stabilisation": (5, 25), "Protection": (10, 35)},
                "liquidity": {"Daily": (50, 100)},
                "region": {"Switzerland": (20, 60)},
                "asset_class": {"Equity": (25, 50), "Cash": (0, 15)}},
     "regime": {"weights": {"CH": 50, "EU": 25, "US": 25}}},
    {"key": "growth-global", "name": "Growth global", "currency": "USD", "curve": "growth-tilt",
     "description": "Equity-led and world-wide, in USD: developed and emerging markets, private equity and "
                    "miners, with bonds, real estate, commodities, hedge funds and treasuries as ballast.",
     "universe": ["INS-msci-ac-world-imi", "INS-us-equities", "INS-eu-equities", "INS-japan-equities",
                  "INS-em-equities", "INS-china-equities", "INS-india-equities", "INS-uk-equities",
                  "INS-ch-equities", "INS-private-equity", "INS-mining-equities", "INS-global-bonds",
                  "INS-global-real-estate-indirect", "INS-commodities", "INS-bloomberg-hedge-fund",
                  "INS-us-treasury-tr-index", "INS-usd-cash"],
     "max": 15, "esg": 0.0,
     "bounds": {"currency": {"USD": (30, 80)},
                "role": {"Gain": (60, 85), "Income": (5, 25), "Stabilisation": (0, 15), "Protection": (5, 20)},
                "liquidity": {"Daily": (70, 100)},
                "region": {"North America": (20, 50)},
                "phase": {"Saturation": (0, 75)},
                "asset_class": {"Equity": (40, 85)}},
     "regime": {"market": "global"}},
    {"key": "income-focus", "name": "Income focus", "currency": "CHF", "curve": "role-income",
     "description": "Carry first: investment-grade and high-yield credit, emerging and Asian bonds, private "
                    "debt, real estate and infrastructure, Swiss dividend and world equity sleeves, market-neutral "
                    "and macro strategies as stabilisers.",
     "universe": ["INS-chf-corporate-loans-ig", "INS-eur-corporate-loans-ig", "INS-global-high-yields",
                  "INS-em-government-bonds-lc", "INS-asian-jaci-bond-index", "INS-private-debt",
                  "INS-sxi-real-estate", "INS-real-estate-direct", "INS-infrastructure",
                  "INS-global-real-estate-indirect", "INS-swiss-dividend-equity", "INS-global-equities",
                  "INS-structured-products", "INS-bloomberg-market-neutral-hf", "INS-global-macro",
                  "INS-bloomberg-multiverse-h-chf", "INS-chf-cash"],
     "max": 15, "esg": 0.0,
     "bounds": {"currency": {"CHF": (50, 100)},
                "role": {"Gain": (0, 25), "Income": (45, 80), "Stabilisation": (0, 20), "Protection": (10, 35)},
                "liquidity": {"Daily": (40, 100)},
                "region": {"Switzerland": (25, 70)},
                "asset_class": {"Fixed Income": (30, 70), "Real Assets": (10, 40)}},
     "regime": {"weights": {"CH": 60, "EU": 25, "US": 15}}},
    {"key": "crisis-resilient", "name": "Crisis-resilient", "currency": "CHF", "curve": "crisis-resilient",
     "description": "Built for the bad states: cash, treasuries and hedged bonds, gold, long volatility and "
                    "trend following, market-neutral and arbitrage strategies, a little investment-grade credit "
                    "and global bonds, a small equity sleeve.",
     "universe": ["INS-chf-cash", "INS-usd-cash", "INS-us-treasury-tr-index", "INS-global-governmental-bonds",
                  "INS-bloomberg-multiverse-h-chf", "INS-precious-metals", "INS-long-volatility-index",
                  "INS-trend-following", "INS-global-macro", "INS-bloomberg-market-neutral-hf",
                  "INS-asia-pacific-arbitrage", "INS-chf-corporate-loans-ig", "INS-global-bonds",
                  "INS-swiss-dividend-equity", "INS-global-equities"],
     "max": 20, "esg": 0.0,
     "bounds": {"currency": {"CHF": (60, 100)},
                "role": {"Gain": (5, 25), "Income": (0, 20), "Stabilisation": (15, 40), "Protection": (30, 70)},
                "liquidity": {"Daily": (50, 100)},
                "region": {"North America": (0, 40)},
                "asset_class": {"Cash": (5, 30), "Equity": (5, 25), "Alternative": (15, 45)}},
     "regime": {"weights": {"CH": 50, "EU": 30, "US": 20}}},
    {"key": "swiss-home-bias", "name": "Swiss home bias", "currency": "CHF", "curve": "steady-return",
     "description": "At home in Switzerland: Swiss equities, CHF credit, Swiss real estate (listed and direct), "
                    "CHF cash and hedged bonds, gold, CHF market-neutral and trend strategies, a world-equity and a "
                    "private-equity sleeve.",
     "universe": ["INS-ch-equities", "INS-swiss-performance-index", "INS-swiss-dividend-equity",
                  "INS-chf-corporate-loans-ig", "INS-sxi-real-estate", "INS-real-estate-direct", "INS-chf-cash",
                  "INS-bloomberg-multiverse-h-chf", "INS-global-governmental-bonds", "INS-precious-metals",
                  "INS-bloomberg-market-neutral-hf", "INS-trend-following", "INS-global-equities",
                  "INS-private-equity"],
     "max": 20, "esg": 0.0,
     "bounds": {"currency": {"CHF": (90, 100)},
                "role": {"Gain": (25, 55), "Income": (15, 40), "Stabilisation": (0, 25), "Protection": (10, 35)},
                "liquidity": {"Daily": (50, 100)},
                "region": {"Switzerland": (50, 100)},
                "capital_type": {"Real": (5, 30)},
                "asset_class": {"Equity": (25, 55)}},
     "regime": {"weights": {"CH": 100}}},
    {"key": "sustainable-balanced", "name": "Sustainable balanced", "currency": "EUR", "curve": "all-weather",
     "description": "A balanced European mix with an ESG floor of 0.8: European, Swiss, US and Japanese "
                    "equity, euro and CHF credit, infrastructure, listed real estate, trend and macro.",
     "universe": ["INS-eu-equities", "INS-aktien-europe-aktiv", "INS-ch-equities", "INS-us-equities",
                  "INS-japan-equities", "INS-eur-corporate-loans-ig", "INS-chf-corporate-loans-ig",
                  "INS-infrastructure", "INS-sxi-real-estate", "INS-trend-following", "INS-global-macro",
                  "INS-eur-cash", "INS-bloomberg-multiverse-h-chf", "INS-global-governmental-bonds"],
     "max": 15, "esg": 0.8,
     "bounds": {"currency": {"EUR": (40, 100)},
                "role": {"Gain": (30, 50), "Income": (15, 35), "Stabilisation": (5, 20), "Protection": (10, 30)},
                "liquidity": {"Daily": (50, 100)},
                "region": {"Europe": (30, 70)},
                "asset_class": {"Equity": (25, 50)}},
     "regime": {"market": "europe"}},
    {"key": "barbell-chf", "name": "Barbell CHF", "currency": "CHF", "curve": "u-profile",
     "description": "Both ends, a thin middle: growth equities on one side, cash, treasuries, gold and long "
                    "volatility on the other, with small credit and trend and macro sleeves so every role is held. "
                    "Pairs with the U-profile curve.",
     "universe": ["INS-us-equities", "INS-msci-ac-world-imi", "INS-ch-equities", "INS-em-equities",
                  "INS-india-equities", "INS-private-equity", "INS-chf-cash", "INS-us-treasury-tr-index",
                  "INS-global-governmental-bonds", "INS-precious-metals", "INS-long-volatility-index",
                  "INS-bloomberg-multiverse-h-chf", "INS-chf-corporate-loans-ig", "INS-global-bonds",
                  "INS-trend-following", "INS-global-macro"],
     "max": 15, "esg": 0.0,
     "bounds": {"currency": {"CHF": (40, 100)},
                "role": {"Gain": (30, 60), "Income": (0, 20), "Stabilisation": (0, 20), "Protection": (30, 60)},
                "liquidity": {"Daily": (60, 100)},
                "asset_class": {"Equity": (25, 60)}},
     "regime": {"market": "global"}},
]


def mandate_presets(curves: list[dict], register: list[dict]) -> list[dict]:
    active = {r["instrument_id"]: r for r in register if r.get("active", True)}
    by_key = {c["key"]: c for c in curves}
    out = []
    for spec in MANDATES:
        uni = spec["universe"]
        assert 8 <= len(uni) <= 20, f"{spec['key']}: {len(uni)} instruments"
        assert len(set(uni)) == len(uni), f"{spec['key']}: repeats an instrument"
        missing = [u for u in uni if u not in active or u in EXCLUDED]
        assert not missing, f"{spec['key']}: not in fmre's active register: {missing}"
        for dim, rows in spec["bounds"].items():
            assert dim in BUCKETS and all(k in BUCKETS[dim] for k in rows), (spec["key"], dim)
        curve = by_key[spec["curve"]]
        mandate = {"contract_version": CONTRACT, "name": spec["name"], "currency": spec["currency"],
                   "horizon_years": 1.0, "curve_unit": "annualised_log_return",
                   "target_curve": pct_to_log(curve["points_pct"]), "universe": uni,
                   "max_single_position": round(spec["max"] / 100, 6), "esg_min": spec["esg"],
                   "fixed_allocations": {},
                   "bounds": {d: {k: b(*v) for k, v in rows.items()} for d, rows in spec["bounds"].items()},
                   "bound_sources": {d: BOUND_SOURCE[d] for d in spec["bounds"]}}
        if "market" in spec["regime"]:
            mandate["regime_market"] = spec["regime"]["market"]
        else:
            mandate["regime_weights"] = {k: round(v / 100, 6) for k, v in spec["regime"]["weights"].items()}
        roles = {}
        for u in uni:
            roles.setdefault(active[u]["role"], []).append(u)
        thin = {r: len(roles.get(r, [])) for r in ROLE_ORDER if len(roles.get(r, [])) < MIN_PER_ROLE}
        assert not thin, f"{spec['key']}: fewer than {MIN_PER_ROLE} active instruments in {thin} (C-29)"
        out.append({"key": spec["key"], "name": spec["name"], "description": spec["description"],
                    "curve_preset": spec["curve"], "curve_shift_pp": 0.0, "curve_tilt_pp": 0.0,
                    "universe_by_role": {r: roles.get(r, []) for r in ROLE_ORDER},
                    "mandate": mandate})
    return out


# ---- validation with pcp --------------------------------------------------------------------------

def latest_regime(agg: httpx.Client, optimism: str = "default") -> str:
    """The latest succeeded Regime of one optimism level (C-30): aggregation issues one per level in one
    go, so its newest run is whichever level finished last. Chosen by the Regime's own optimism_scale."""
    runs = [r for r in agg.get("/runs", params={"limit": 200}).json() if r["status"] == "succeeded" and r.get("regime_id")]
    runs.sort(key=lambda r: str(r.get("finished_at") or r.get("started_at") or ""), reverse=True)
    for r in runs:
        if r.get("optimism_scale") not in (None, optimism):
            continue
        if agg.get(f"/regime/{r['regime_id']}/current").json().get("optimism_scale") == optimism:
            return r["regime_id"]
    raise SystemExit(f"aggregation has no succeeded run at optimism level {optimism!r}")


def with_role_floors(mandate: dict, floor: float) -> dict:
    """The mandate with every role floor at ``floor`` and its own role ceilings kept (C-29)."""
    own = mandate["bounds"].get("role", {})
    roles = {r: {"lower": floor, "upper": own.get(r, {}).get("upper", 1.0)} for r in BUCKETS["role"]}
    return {**mandate, "bounds": {**mandate["bounds"], "role": roles},
            "bound_sources": {**mandate["bound_sources"], "role": BOUND_SOURCE["role"]}}


def _ask(pcp: httpx.Client, body: dict) -> tuple[bool, int, dict, list]:
    r = pcp.post("/validate", json=body)
    answer = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text}
    ok = r.status_code == 200 and answer.get("ok") is True
    problems = answer.get("problems") if r.status_code == 200 else [json.dumps(answer.get("detail", answer))[:1500]]
    return ok, r.status_code, answer, list(problems or [])


def validate(presets: list[dict], fmre: httpx.Client, pcp: httpx.Client, regime_id: str) -> None:
    engine_version = pcp.get("/health").json().get("engine_version")
    sets: dict[str, dict] = {}
    for p in presets:
        cur = p["mandate"]["currency"]
        if cur not in sets:
            r = fmre.get("/v1/return-set", params={"regime_id": regime_id, "include_instruments": "true",
                                                   "include_blocks": "false", "currency": cur})
            r.raise_for_status()
            sets[cur] = r.json()
        rs = sets[cur]
        body = {"regime_id": regime_id, "return_set_id": rs["return_set_id"],
                "mandate": {**p["mandate"], "client": "preset-validation"}}
        ok, status, answer, problems = _ask(pcp, body)
        floors = []
        for level in ROLE_FLOOR_LEVELS:
            f_ok, f_status, _, f_problems = _ask(pcp, {**body, "mandate": with_role_floors(body["mandate"], level)})
            floors.append({"role_floor": level, "ok": f_ok, "status_code": f_status, "problems": f_problems})
        p["validation"] = {"ok": ok, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           "pcp_engine": engine_version,
                           "regime_id": regime_id, "return_set_id": rs["return_set_id"], "currency": cur,
                           "status_code": status, "problems": problems,
                           "notes": list(answer.get("notes") or []), "universe_size": answer.get("universe_size"),
                           "constraint_rows": answer.get("constraint_rows"), "date": answer.get("date"),
                           "role_floor_checks": floors}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fmre", default="http://127.0.0.1:8006")
    ap.add_argument("--pcp", default="http://127.0.0.1:8007")
    ap.add_argument("--aggregation", default="http://127.0.0.1:8004")
    ap.add_argument("--regime-id", help="validate against this Regime (default: aggregation's latest succeeded Regime "
                                         "of the --optimism level)")
    ap.add_argument("--optimism", default="default", choices=("defensive", "default", "aggressive", "rogue"),
                    help="the optimism level of the Regime validated against (C-30)")
    ap.add_argument("--no-validate", action="store_true", help="skip pcp /validate (recorded as pending)")
    ap.add_argument("--save", action="store_true", help="save both keys to the content store as role curator")
    ap.add_argument("--curator", help="the acting curator's id (required with --save)")
    ap.add_argument("--out", type=Path, help="also write the chosen bodies to this folder as JSON")
    ap.add_argument("--keys", choices=("both", "curves", "mandates"), default="both",
                    help="which keys to write and save (default both); 'mandates' leaves the curve presets as saved")
    a = ap.parse_args()

    with httpx.Client(base_url=a.fmre, timeout=120) as fmre:
        rs = fmre.get("/v1/return-set", params={"include_instruments": "false", "include_blocks": "false"}).json()
        register = fmre.get("/v1/instruments").json()
    curves = curve_presets(rs)
    presets = mandate_presets(curves, register)
    if a.no_validate:
        for p in presets:
            p["validation"] = {"ok": None, "pending": "not validated: run dev/build_presets.py with pcp up"}
    else:
        with httpx.Client(base_url=a.aggregation, timeout=120) as agg, \
                httpx.Client(base_url=a.fmre, timeout=300) as fmre, httpx.Client(base_url=a.pcp, timeout=300) as pcp:
            validate(presets, fmre, pcp, a.regime_id or latest_regime(agg, a.optimism))

    built = dt.date.today().isoformat()
    curve_body = {
        "version": "tcp@1.0.0", "built": built, "unit": "percent_per_year",
        "states": "25 states, 1 crisis (most cautious) to 25 boom (most aggressive), as pcp and fmre number them",
        "stored_unit": "pcp's Mandate stores the curve as annualised_log_return, ln(1 + p/100); the cockpit "
                       "converts on save (DECISIONS C-21)",
        "adjust": "point i = preset_i + shift_pp + tilt_pp x (i - 13) / 12; the tilt leaves the mean unchanged",
        "provenance": {"script": "cockpit/dev/build_presets.py", "fmre_calibration_id": rs["provenance"]["calibration_id"],
                       "fmre_return_set_id": rs["return_set_id"], "fmre_as_of": rs.get("as_of")},
        "presets": curves,
        "_about": "Named target curves for the Parameters page. Data, not computed by the cockpit. "
                  "Model-derived research output; not investment advice.",
    }
    mandate_body = {
        "version": MANDATE_VERSION, "built": built, "contract_version": CONTRACT,
        "min_instruments_per_role": MIN_PER_ROLE, "role_floor_levels": list(ROLE_FLOOR_LEVELS),
        "curve_presets": {"key": PRESET_KEYS["curves"], "version": "tcp@1.0.0"},
        "excluded_instruments": sorted(EXCLUDED),
        "presets": presets,
        "_about": "Ready mandates for the Parameters page, in pcp's shape (fractions; the curve as annualised log "
                  "returns from the named curve preset). The client is filled in when a preset is applied. "
                  "Model-derived research output; not investment advice.",
    }
    for p in presets:
        v = p["validation"]
        state = "pending" if v.get("ok") is None else ("ok" if v["ok"] else "PROBLEMS")
        print(f"{p['name']:<22} {p['mandate']['currency']} {len(p['mandate']['universe']):>2} instruments  "
              f"curve {p['curve_preset']:<20} pcp /validate: {state}")
        for msg in v.get("problems") or []:
            print("    -", msg)
        for f in v.get("role_floor_checks") or []:
            print(f"    role floors {f['role_floor']:.2f}: {'ok' if f['ok'] else 'PROBLEMS'}")
            for msg in f.get("problems") or []:
                print("      -", msg)
    for c in curves:
        print(f"  curve {c['key']:<22} mean {c['mean_pct']:6.2f}  min {c['min_pct']:6.2f}  max {c['max_pct']:6.2f}")
    do_curves, do_mandates = a.keys in ("both", "curves"), a.keys in ("both", "mandates")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        if do_curves:
            (a.out / "target-curve-presets.json").write_text(json.dumps(curve_body, indent=1), encoding="utf-8")
        if do_mandates:
            (a.out / "mandate-presets.json").write_text(json.dumps(mandate_body, indent=1), encoding="utf-8")
    if a.save:
        if not a.curator:
            ap.error("--save needs --curator (the acting curator's id)")
        from cockpit.curator import CuratorStore
        from cockpit.settings import load
        store = CuratorStore(load().curator_db)
        if do_curves:
            v1 = store.save_content(PRESET_KEYS["curves"], "reference", curve_body, a.curator,
                                    f"target-curve presets tcp@1.0.0 ({len(curves)}), built {built} from fmre "
                                    f"{rs['provenance']['calibration_id']}")
            print(f"saved {PRESET_KEYS['curves']} v{v1}")
        if do_mandates:
            v2 = store.save_content(PRESET_KEYS["mandates"], "reference", mandate_body, a.curator,
                                    f"mandate presets {MANDATE_VERSION} ({len(presets)}), at least {MIN_PER_ROLE} "
                                    "active instruments per role, validated with pcp /validate, also with every role "
                                    f"floor at {', '.join(f'{x:g}' for x in ROLE_FLOOR_LEVELS)} (C-29)")
            print(f"saved {PRESET_KEYS['mandates']} v{v2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
