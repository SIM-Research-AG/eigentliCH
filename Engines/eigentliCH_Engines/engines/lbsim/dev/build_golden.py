"""Freeze golden layer A: the draft's own ``gameplan.assemble`` and ``paths.ledger`` on the draft's cases.

Run with the DRAFT's interpreter, never this family's (it imports the draft, ``personal_alm``)::

    C:\\Users\\nicol\\Desktop\\SIM_NAS\\Projects\\eigentliCH\\engines\\Life_Balance_Sheet\\.venv\\Scripts\\python.exe -X utf8 dev/build_golden.py

Read-only use of the draft, enforced rather than promised:

* the draft reads its two tables from ``Projects/eigentliCH/data``, which does not exist. The module attributes
  ``bvg.TABLE`` and ``canton.TABLE`` are pointed, in memory, at lbsim's seed records ``social-insurance`` and
  ``canton-tax`` (the draft's own loaders read them; the ``_about`` block they carry is a key the draft ignores).
  No folder is created and no draft file is touched;
* nothing is written outside ``golden/draft`` in this engine's folder.

The cases:

* ``gp-*``: the draft's own gameplan fixture (``tests/test_gameplan.py::submission``) and the variants its tests
  run, one per rule and per section;
* ``pa-*``: the draft's own paths fixture (``tests/test_paths.py::household``) and its variants;
* ``uc-*``: use-case-shaped submissions, invented households in the shape ``lbsim.adapter`` builds from a Life
  Balance Sheet (a couple, a young household in education, an early exit, children, a property goal, a rate
  reset, positions outside the model).

Every case is invented. For each, ``assemble(submission)`` and ``ledger(submission, params, stop_age)`` are frozen
exactly as the draft returns them.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

DRAFT = Path(r"C:\Users\nicol\Desktop\SIM_NAS\Projects\eigentliCH\engines\Life_Balance_Sheet")
HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "golden" / "draft"
SEEDS = HERE / "src" / "lbsim" / "seed_records"

sys.path.insert(0, str(DRAFT))

from personal_alm.app import gameplan as G  # noqa: E402
from personal_alm.app import paths as P  # noqa: E402
from personal_alm.app import onboarding as ONB  # noqa: E402
from personal_alm.model import bvg, canton  # noqa: E402
from personal_alm.model.params import Params  # noqa: E402
from personal_alm.tests.test_gameplan import submission  # noqa: E402
from personal_alm.tests.test_paths import household  # noqa: E402

bvg.TABLE = SEEDS / "social-insurance.json"
canton.TABLE = SEEDS / "canton-tax.json"


def cases() -> dict[str, dict]:
    """Every case, by name. The variants are the ones the draft's own tests run, plus a few more per rule."""
    home = [{"kind": "home", "description": "Wohnung", "target_year": 2036, "amount_chf": 300_000.0,
             "confidence": 0.9, "is_consumption": False}]
    out: dict[str, dict] = {
        # -- tests/test_gameplan.py
        "gp-baseline": submission(),
        "gp-no-raw": submission(raw={}),
        "gp-no-property": submission(state={"W_R": 0.0, "W_res": 0.0, "D": 0.0}),
        "gp-children": submission(params={"child_ages": [4.0, 9.0], "child_reference_age": 45}),
        "gp-drawable-thin": submission(state={"W_L": 50_000.0}),
        "gp-spending-doubling": submission(raw={"spend_later": 180_000.0}),
        "gp-undirected-surplus": submission(params={"p_A": None, "pillar3a_contribution": 0.0},
                                            raw={"savings": None}),
        "gp-saving-contradiction": submission(raw={"savings": 300_000.0}),
        "gp-alimony-paid": submission(raw={"alimony_direction": "ich zahle", "alimony_amount": 24_000.0}),
        "gp-alimony-received": submission(raw={"alimony_direction": "ich erhalte", "alimony_amount": 24_000.0}),
        "gp-debt-service": submission(state={"D": 4_500_000.0, "W_R": 9_000_000.0, "W_res": 9_000_000.0}),
        "gp-thin-liquidity": submission(state={"W_L": 20_000.0, "D": 2_000_000.0, "W_R": 4_000_000.0,
                                               "W_res": 4_000_000.0}),
        "gp-pension-small": submission(state={"W_P": 50_000.0}, raw={"work_years_current": 22}),
        "gp-hours": submission(raw={"hours_per_week": 70}),
        "gp-empty-3a": submission(state={"W_3a": 0.0}, params={"pillar3a_contribution": 0.0},
                                  raw={"pillar3a": 0.0}),
        "gp-no-will-widowed": submission(raw={"legal_docs": "nichts", "civil_status": "verwitwet",
                                              "household": "alleine"}),
        "gp-no-will-cohabiting": submission(raw={"legal_docs": [], "civil_status": "ledig, mit Partner",
                                                 "household": "mit Partner"}),
        "gp-sorted": submission(state={"W_L": 10_000.0, "W_3a": 0.0, "D": 2_000_000.0, "W_R": 4_000_000.0,
                                       "W_res": 4_000_000.0},
                                params={"pillar3a_contribution": 0.0},
                                raw={"hours_per_week": 70, "legal_docs": "nichts"}),
        "gp-capital-goal": submission(goals=home),
        "gp-hopeless-goal": submission(goals=[{"kind": "home", "description": "Villa", "target_year": 2028,
                                               "amount_chf": 20_000_000.0, "confidence": 0.9,
                                               "is_consumption": False}]),
        "gp-mortgage-rate": submission(params={"mortgage_rate": 0.0135}, raw={"mortgage_rate": 1.35}),
        "gp-no-rate": submission(raw={"mortgage_rate": None}),
        "gp-bridge-missing": submission(raw={"goals": "Ab 55 nicht mehr arbeiten"}),
        "gp-bridge": submission(params={"stop_work_age": 55}, raw={"goals": "Ab 55 nicht mehr arbeiten"}),
        "gp-deferred-other": submission(goals=[
            {"kind": "retirement", "description": "Ausgaben ab 65 gedeckt", "target_year": 2046,
             "amount_chf": 90_000.0, "confidence": 0.9, "is_consumption": False},
            {"kind": "other", "description": "Eigentum kaufen 2037 2 Mio", "target_year": 2037,
             "amount_chf": 2_000_000.0, "confidence": 0.9, "is_consumption": None}]),
        "gp-rate-reset": submission(raw={"mortgage_fixed_until": 2027}),
        "gp-indirect": submission(params={"amortisation_indirect": 7_258.0, "p_A": None},
                                  raw={"amortisation_mode": "indirekt über 3a"}),
        "gp-outside": submission(raw={"company_value": 800_000.0, "collectibles_value": 60_000.0,
                                      "gold_value": 40_000.0}),
        "gp-own-share": submission(raw={"asset_scope": "nur mein Anteil"}),
        "gp-couple-unmarried": submission(params={"has_partner": True, "partner_income": 120_000.0},
                                          raw={"civil_status": "ledig, mit Partner"}),
        "gp-couple-married": submission(params={"has_partner": True, "partner_income": 90_000.0,
                                                "tax_split_factor": 2.0, "partner_age_offset": 2.0}),
        "gp-ahv-gaps": submission(params={"ahv_record_share": 0.8}),
        "gp-education": submission(raw={"education_hours": "6–10", "education_budget": 8_000.0}),
        "gp-rest": submission(raw={"rest_hours": 10.0}),
        "gp-no-canton": submission(raw={"canton": None}),
        "gp-expected-return": submission(raw={"expected_return_pct": "6,5 %"}),
        # -- tests/test_paths.py
        "pa-household": household(),
        "pa-anchored": household(raw={"income_expected_full": 95_000.0, "education_planned": "Bachelor 2029"}),
        "pa-no-education": household(raw={"education_hours": "keine", "education_budget": None}),
        "pa-full-time": household(raw={"hours_per_week": 42.0, "income_gross": 85_000.0}),
        "pa-no-income": household(raw={"income_gross": None}),
        "pa-stop-60": household(params={"stop_work_age": 60}),
        # -- use-case-shaped
        "uc-couple-property": submission(
            state={"age": 36, "W_L": 180_000.0, "W_R": 0.0, "W_res": 0.0, "D": 0.0, "W_P": 140_000.0,
                   "W_3a": 45_000.0, "E": 0.85, "N": 0.6, "H": 0.9},
            params={"G": 85_000.0, "has_partner": True, "partner_income": 95_000.0, "partner_age_offset": -2.0,
                    "tax_split_factor": 1.0, "pillar3a_contribution": 7_258.0, "p_A": None},
            goals=[{"kind": "home", "description": "Eigentumswohnung", "target_year": 2031,
                    "amount_chf": 240_000.0, "confidence": 0.9, "is_consumption": False},
                   {"kind": "retirement", "description": "Ruhestand", "target_year": 2055,
                    "amount_chf": 85_000.0, "confidence": 0.9, "is_consumption": False}],
            raw={"birth_year": 1990, "canton": "Zürich", "income_gross": 125_000.0, "spend_now": 95_000.0,
                 "spend_later": 85_000.0, "savings": 30_000.0, "hours_per_week": 42, "pillar2": 140_000.0,
                 "pillar3a": 45_000.0, "mortgage": None, "mortgage_rate": None, "property_total": 0.0,
                 "civil_status": "ledig, mit Partner", "household": "mit Partner", "legal_docs": [],
                 "amortisation_mode": None, "work_years_current": 12, "expected_return_pct": "4 %"}),
        "uc-young-education": household(
            state={"age": 27, "W_L": 25_000.0, "W_P": 12_000.0, "W_3a": 3_000.0, "E": 0.7, "N": 0.4},
            params={"G": 60_000.0, "pillar3a_contribution": 0.0},
            raw={"birth_year": 1999, "income_gross": 38_000.0, "spend_now": 34_000.0, "hours_per_week": 21.0,
                 "education_hours": "6–10", "education_budget": 9_000.0,
                 "education_planned": "Master 2028", "income_expected_full": 105_000.0,
                 "canton": "Bern", "civil_status": "ledig", "legal_docs": []}),
        "uc-early-exit": submission(
            state={"age": 54, "W_L": 900_000.0, "W_P": 850_000.0, "W_3a": 160_000.0, "D": 400_000.0,
                   "W_R": 1_400_000.0, "W_res": 1_400_000.0},
            params={"G": 110_000.0, "stop_work_age": 58, "p_A": 10_000.0},
            goals=[{"kind": "retirement", "description": "Ausstieg mit 58", "target_year": 2030,
                    "amount_chf": 110_000.0, "confidence": 0.9, "is_consumption": False}],
            raw={"birth_year": 1972, "income_gross": 240_000.0, "spend_now": 115_000.0, "spend_later": 110_000.0,
                 "hours_per_week": 55, "goals": "Mit 58 nicht mehr arbeiten", "canton": "Luzern",
                 "mortgage_rate": 1.6, "savings": 80_000.0}),
        "uc-family": submission(
            state={"age": 41, "W_L": 60_000.0, "D": 780_000.0, "W_R": 1_150_000.0, "W_res": 1_150_000.0,
                   "W_P": 210_000.0, "W_3a": 30_000.0},
            params={"G": 105_000.0, "child_ages": [3.0, 6.0], "child_reference_age": 41, "has_partner": True,
                    "partner_income": 40_000.0, "tax_split_factor": 2.0, "amortisation_indirect": 7_258.0,
                    "p_A": None},
            raw={"birth_year": 1985, "income_gross": 150_000.0, "spend_now": 110_000.0, "spend_later": 95_000.0,
                 "hours_per_week": 45, "canton": "Aargau", "civil_status": "verheiratet",
                 "household": "mit Partnerin und Kindern", "amortisation_mode": "indirekt",
                 "mortgage_rate": 1.9, "mortgage_fixed_until": 2027, "legal_docs": ["Vorsorgeauftrag"],
                 "children_count": 2}),
        "uc-self-employed": submission(
            state={"age": 48, "W_L": 35_000.0, "W_P": 60_000.0, "W_3a": 0.0, "D": 0.0, "W_R": 0.0, "W_res": 0.0},
            params={"G": 80_000.0, "pillar3a_contribution": 0.0, "p_A": None},
            raw={"birth_year": 1978, "income_gross": 130_000.0, "spend_now": 82_000.0, "spend_later": 80_000.0,
                 "hours_per_week": 60, "canton": "Genf", "company_value": 450_000.0, "loans_given": 30_000.0,
                 "pillar3a": 0.0, "work_years_current": 24, "legal_docs": None, "civil_status": "geschieden"}),
        "uc-let-property": submission(
            state={"W_R": 2_000_000.0, "W_res": 800_000.0, "D": 900_000.0},
            raw={"own_use_pct": 40, "canton": "Basel-Stadt"}),
    }
    return out


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    (OUT / "cases").mkdir(parents=True, exist_ok=True)
    (OUT / "expected").mkdir(parents=True, exist_ok=True)
    built = []
    for name, sub in cases().items():
        q = G.assemble(sub)
        p = G._params_from(sub)
        stop = G._stop_age(sub, p)
        ledger_stated = P.ledger(sub, p, stop_age=stop)
        ledger_60 = P.ledger(sub, p, stop_age=60.0, extra_rates=(0.035,))
        expected = {"assemble": q, "ledger": ledger_stated, "ledger_stop_60_extra_035": ledger_60}
        (OUT / "cases" / f"{name}.json").write_text(
            json.dumps(sub, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        (OUT / "expected" / f"{name}.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        built.append(name)
        print(name, len(q.get("findings") or []), "findings")
    sources = {f"{d}/{f.name}": sha(f) for d in ("app", "model")
               for f in sorted((DRAFT / "personal_alm" / d).glob("*.py"))}
    manifest = {
        "built_by": "dev/build_golden.py",
        "interpreter": sys.executable,
        "python": sys.version.split()[0],
        "numpy": __import__("numpy").__version__,
        "draft": str(DRAFT / "personal_alm"),
        "draft_sources_sha256": sources,
        "tables": {"bvg.TABLE": str(bvg.TABLE), "canton.TABLE": str(canton.TABLE),
                   "social-insurance": sha(bvg.TABLE), "canton-tax": sha(canton.TABLE)},
        "onboarding_param_aliases": ONB._PARAM_ALIASES,
        "params_defaults": {k: (list(v) if isinstance(v, tuple) else v)
                            for k, v in Params().__dict__.items()},
        "cases": built,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
