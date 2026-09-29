"""Freeze the lbs inputs lbsim's adapter and layer B run on: Life Balance Sheets and the requests they came from.

Run with the family interpreter (``eigentliCH_Engines/.venv``)::

    ..\\..\\.venv\\Scripts\\python -X utf8 dev/build_lbs_cases.py

lbs is used as a library, read only, and only here: the engine never imports it (it reads lbs over HTTP through
mirrors). Each case is a ``lbs-request@1.0.0`` request, the sheet ``lbs.service.build_sheet`` makes of it under
lbs's active calibration, and the two records of that calibration the adapter reads (``human-capital``,
``property-funding``). The requests are lbs's own golden cases (``engines/lbs/golden/cases``, the ``db-*`` and
``syn-*`` households) and five invented households in the shape the consumer app sends from lbs@1.4.0 on, with
the new ``persons[].earning_power`` answers and facts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from lbs import ENGINE_VERSION as LBS_VERSION
from lbs.calibration import CORRECTED_1_5
from lbs.contracts import LifeBalanceSheetRequest
from lbs.service import build_sheet

HERE = Path(__file__).resolve().parents[1]
LBS = HERE.parent / "lbs"
OUT = HERE / "golden" / "lbs_cases"
AS_OF = "2026-09-28"


def _person(pid, age, income, **hc):
    return {"person_id": pid, "kind": "adult", "age": age, "stated_gross_income": income,
            "human_capital": hc}


def _stock(pid, role, amount, vessel, owner="p1", kind="asset", liquidity="immediate"):
    return {"position_id": pid, "role": role, "capital_type": "financial", "magnitude": amount, "unit": "chf",
            "stock_kind": kind, "liquidity": liquidity, "vessel": vessel if kind == "asset" else None,
            "owner": owner}


def invented() -> dict[str, dict]:
    """Households in the shape the app sends, with the lbs@1.4.0 answers."""
    base_hc = {"qualification_highest": "Fachhochschule FH", "education_recent": "nein", "network_people": 10.0,
               "mandates": 0.0, "health": "0.85", "hours_per_week": 42.0, "rest_hours": "10–20"}
    couple = {
        "client_ref": "lbsim-couple", "as_of": AS_OF,
        "household": {"composition_as_of": "2026-09-01", "principal": "p1", "persons": [
            {**_person("p1", 38, 128_000.0, **base_hc),
             "earning_power": {"expected_full_pensum_income": 135_000.0, "responsibility": "Oberes oder mittleres "
                               "Kader", "sector": "Informationstechnologie", "education_status": "none"}},
            {**_person("p2", 36, 92_000.0, qualification_highest="Universitäre Hochschule", network_people=6.0,
                       mandates=0.0, health="1", hours_per_week=34.0)},
            {"person_id": "c1", "kind": "dependant", "age": 4}]},
        "positions": [_stock("a1", "stabilisation", 60_000.0, "free"),
                      _stock("a2", "gain", 190_000.0, "free"),
                      _stock("a3", "protection", 165_000.0, "pillar_2", liquidity="illiquid"),
                      _stock("a4", "protection", 48_000.0, "pillar_3a", liquidity="illiquid"),
                      _stock("a5", "protection", 70_000.0, "pillar_2", owner="p2", liquidity="illiquid")],
        "goals": [{"goal_id": "g-home", "kind": "property", "target_amount": 1_150_000.0,
                   "target_date": "2030-06-30", "occupancy": "owner_occupied_primary"},
                  {"goal_id": "g-ret", "kind": "retirement", "target_amount": 95_000.0,
                   "target_date": "2053-12-31"}],
        "facts": {"canton": "Zürich", "civil_status": "verheiratet", "has_no_liabilities": True,
                  "legal_documents": ["Vorsorgeauftrag"], "pillar3a_contribution_per_year": 7_258.0},
        "risk": {"stated_loss": 0.2, "spend_now_per_year": 118_000.0, "gross_income_per_year": 220_000.0,
                 "plan_until_age": 90.0, "mortgage": 0.0},
        "mandate": {"goal_id": "g-home", "annual_contribution": 36_000.0},
    }
    young = {
        "client_ref": "lbsim-young", "as_of": AS_OF,
        "household": {"composition_as_of": "2026-09-01", "principal": "p1", "persons": [
            {**_person("p1", 27, 38_000.0, qualification_highest="Höhere Berufsausbildung",
                       education_recent="Master 2028", network_people=5.0, mandates=0.0, health="1",
                       hours_per_week=21.0, rest_hours="10–20"),
             "earning_power": {"expected_full_pensum_income": 105_000.0, "education_status": "in_progress",
                               "education_end_year": 2028, "education_hours": "6–10",
                               "education_budget_per_year": 9_000.0}}]},
        "positions": [_stock("a1", "stabilisation", 25_000.0, "free"),
                      _stock("a2", "protection", 12_000.0, "pillar_2", liquidity="illiquid")],
        "goals": [{"goal_id": "g-home", "kind": "property", "target_amount": 800_000.0,
                   "target_date": "2037-12-31"},
                  {"goal_id": "g-ret", "kind": "retirement", "target_amount": 60_000.0,
                   "target_date": "2064-12-31"}],
        "facts": {"canton": "Bern", "civil_status": "ledig", "has_no_liabilities": True, "legal_documents": []},
        "risk": {"stated_loss": 0.25, "spend_now_per_year": 34_000.0, "gross_income_per_year": 38_000.0,
                 "plan_until_age": 90.0},
        "mandate": {"goal_id": "g-home", "annual_contribution": 3_000.0},
    }
    early = {
        "client_ref": "lbsim-early", "as_of": AS_OF,
        "household": {"composition_as_of": "2026-09-01", "principal": "p1", "persons": [
            {**_person("p1", 54, 240_000.0, qualification_highest="Universitäre Hochschule", education_recent="nein",
                       network_people=20.0, mandates=2.0, health="0.85", hours_per_week=55.0, rest_hours="5–10"),
             "earning_power": {"responsibility": "topmanagement", "sector": "Banken",
                               "health_work_capacity": 0.8}}]},
        "positions": [_stock("a1", "gain", 900_000.0, "free"),
                      _stock("a2", "protection", 850_000.0, "pillar_2", liquidity="illiquid"),
                      _stock("a3", "protection", 160_000.0, "pillar_3a", liquidity="illiquid"),
                      _stock("a4", "income", 1_400_000.0, "real_asset", liquidity="illiquid"),
                      _stock("d1", "protection", 400_000.0, None, kind="liability", liquidity=None)],
        "goals": [{"goal_id": "g-ret", "kind": "retirement", "target_amount": 110_000.0,
                   "target_date": "2030-12-31"},
                  {"goal_id": "g-gift", "kind": "other", "target_amount": 200_000.0, "target_date": "2029-06-30"}],
        "facts": {"canton": "Luzern", "civil_status": "verwitwet", "stop_work_age": 58.0,
                  "legal_documents": ["Testament", "Vorsorgeauftrag"], "mortgage_fixed_until": "2027-03-31",
                  "amortisation_mode": "direct", "own_use_share": 1.0, "pillar3a_contribution_per_year": 7_258.0},
        "risk": {"stated_loss": 0.15, "spend_now_per_year": 115_000.0, "gross_income_per_year": 240_000.0,
                 "plan_until_age": 90.0, "mortgage": 400_000.0, "mortgage_rate_pct": 1.6,
                 "amortisation_per_year": 10_000.0},
        "mandate": {"goal_id": "g-ret", "annual_contribution": 80_000.0},
    }
    family = copy.deepcopy(couple)
    family["client_ref"] = "lbsim-family"
    family["household"]["persons"][0]["earning_power"] = {"responsibility": "Keine Führungsfunktion"}
    family["household"]["persons"].append({"person_id": "c2", "kind": "dependant", "age": 7})
    family["positions"].append(_stock("a6", "income", 1_150_000.0, "real_asset", liquidity="illiquid"))
    family["positions"].append(_stock("d1", "protection", 780_000.0, None, kind="liability", liquidity=None))
    family["facts"] = {"canton": "Aargau", "civil_status": "verheiratet", "amortisation_mode": "indirect"}
    family["risk"] = {"stated_loss": 0.1, "spend_now_per_year": 110_000.0, "mortgage": 780_000.0,
                      "mortgage_rate_pct": 1.9, "amortisation_per_year": 7_258.0}
    family["goals"] = [{"goal_id": "g-ret", "kind": "retirement", "target_amount": 95_000.0,
                        "target_date": "2053-12-31", "amount_basis": "today"}]
    family["mandate"] = {"goal_id": "g-ret", "annual_contribution": 12_000.0}
    thin = {
        "client_ref": "lbsim-thin", "as_of": AS_OF,
        "household": {"composition_as_of": "2026-09-01", "principal": "p1", "persons": [
            _person("p1", 45, 150_000.0, qualification_highest="Berufsausbildung (EFZ)", network_people=4.0,
                    mandates=0.0, health="0.7", hours_per_week=48.0)]},
        "positions": [_stock("a1", "stabilisation", 20_000.0, "free"),
                      _stock("a2", "income", 2_400_000.0, "real_asset", liquidity="illiquid"),
                      _stock("a3", "gain", 80_000.0, None),
                      _stock("d1", "protection", 1_900_000.0, None, kind="liability", liquidity=None)],
        "goals": [{"goal_id": "g-cap", "kind": "other", "target_amount": 150_000.0, "target_date": "2031-12-31"}],
        "facts": {"canton": "Genf", "civil_status": "ledig, mit Partner", "own_use_share": 0.4,
                  "legal_documents": []},
        "risk": {"spend_now_per_year": 95_000.0, "mortgage": 1_900_000.0},
        "mandate": {"goal_id": "g-cap", "annual_contribution": 10_000.0},
    }
    sample = copy.deepcopy(couple)
    sample["client_ref"] = "lbsim-sample"
    sample["positions"] = [_stock("a1", "stabilisation", 40_000.0, "free"),
                           _stock("a2", "gain", 60_000.0, "free"),
                           _stock("a3", "protection", 95_000.0, "pillar_2", liquidity="illiquid"),
                           _stock("a4", "protection", 22_000.0, "pillar_3a", liquidity="illiquid"),
                           _stock("a5", "protection", 40_000.0, "pillar_2", owner="p2", liquidity="illiquid")]
    sample["goals"] = [{"goal_id": "g-home", "kind": "property", "target_amount": 1_350_000.0,
                        "target_date": "2029-12-31", "occupancy": "owner_occupied_primary"},
                       {"goal_id": "g-ret", "kind": "retirement", "target_amount": 120_000.0,
                        "target_date": "2053-12-31"}]
    sample["risk"] = {"stated_loss": 0.2, "spend_now_per_year": 118_000.0, "gross_income_per_year": 220_000.0,
                      "plan_until_age": 90.0, "mortgage": 0.0}
    sample["mandate"] = {"goal_id": "g-home", "annual_contribution": 30_000.0}
    # The shape of a live household that exposed the draft's income paths (B2's live check, 29.09.2026),
    # anonymised: a reduced pensum (30 hours), no stated expectation, a partner, two children, four goals.
    reduced = {
        "client_ref": "lbsim-reduced-pensum", "as_of": AS_OF,
        "household": {"composition_as_of": "2026-09-01", "principal": "p1", "persons": [
            _person("p1", 33, None, qualification_highest="Fachhochschule FH", qualification_year=2016.0,
                    years_in_field=10.0, education_recent="Weiterbildung ab 2027", network_people=8.0,
                    mandates=0.0, network_reach="im eigenen Unternehmen", health="0.85", hours_per_week=30.0,
                    rest_hours="5–10", hours_learning=2.0, hours_network=1.0),
            _person("p2", 35, None, qualification_highest="Berufsausbildung (EFZ)", qualification_year=2011.0,
                    years_in_field=14.0, education_recent="nein", network_people=6.0, mandates=0.0,
                    network_reach="im eigenen Unternehmen", health="1 — sehr gut", hours_per_week=42.0,
                    rest_hours="10–20"),
            {"person_id": "c1", "kind": "dependant"}, {"person_id": "c2", "kind": "dependant"}]},
        "positions": [
            {"position_id": "i1", "role": "income", "capital_type": "human", "magnitude": 56_000.0,
             "unit": "chf_per_year", "owner": "p1"},
            _stock("a1", "protection", 61_000.0, "pillar_2", liquidity="illiquid"),
            _stock("a2", "gain", 22_000.0, "free"),
            _stock("a3", "stabilisation", 48_000.0, "free"),
            _stock("a4", "protection", 22_000.0, "pillar_3a", liquidity="illiquid"),
            _stock("d1", "stabilisation", 14_000.0, None, kind="liability", liquidity=None),
            _stock("d2", "stabilisation", 11_500.0, None, kind="liability", liquidity=None),
            {"position_id": "i2", "role": "income", "capital_type": "human", "magnitude": 92_000.0,
             "unit": "chf_per_year", "owner": "p2"},
            _stock("a5", "protection", 78_000.0, "pillar_2", owner="p2", liquidity="illiquid")],
        "goals": [{"goal_id": "g-ret", "kind": "retirement", "target_amount": 84_000.0, "target_date": "2058-12-31",
                   "amount_basis": "today", "contribution_share": 0.0},
                  {"goal_id": "g-home", "kind": "property", "target_amount": 850_000.0, "target_date": "2032-12-31",
                   "occupancy": "owner_occupied_primary", "amount_basis": "today", "contribution_share": 0.6},
                  {"goal_id": "g-cap1", "kind": "other", "target_amount": 60_000.0, "target_date": "2039-08-31",
                   "amount_basis": "today", "contribution_share": 0.25},
                  {"goal_id": "g-cap2", "kind": "other", "target_amount": 9_800.0, "target_date": "2028-07-31",
                   "amount_basis": "today", "contribution_share": 0.15}],
        "facts": {"canton": "Bern", "civil_status": "verheiratet"},
        "risk": {"stated_loss": 0.15, "employment": "angestellt", "liquidity_reserve_months": 6.0,
                 "spend_now_per_year": 96_000.0, "gross_income_per_year": 56_000.0, "mandates": 0,
                 "plan_until_age": 90.0},
        "mandate": {"goal_id": "g-home", "annual_contribution": 18_000.0, "contribution_indexed": True},
    }
    return {"lbsim-reduced-pensum": reduced, "lbsim-couple": couple, "lbsim-young": young, "lbsim-early": early, "lbsim-family": family,
            "lbsim-thin": thin, "lbsim-sample": sample}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cal = CORRECTED_1_5
    requests: dict[str, dict] = {}
    for path in sorted((LBS / "golden" / "cases").glob("*.json")):
        requests[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    requests.update(invented())
    built = []
    for name, body in requests.items():
        request = LifeBalanceSheetRequest.model_validate(body)
        sheet = build_sheet(request, cal)
        folder = OUT / name
        folder.mkdir(exist_ok=True)
        req_json = request.model_dump(mode="json")
        (folder / "request.json").write_text(json.dumps(req_json, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
        (folder / "sheet.json").write_text(json.dumps(sheet.model_dump(mode="json"), ensure_ascii=False,
                                                      indent=1) + "\n", encoding="utf-8")
        built.append(name)
        print(name, sheet.artefact_id)
    records = {name: cal.records[name] for name in ("human-capital", "property-funding")}
    (OUT / "records.json").write_text(json.dumps({"calibration_version": cal.version, "records": records},
                                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    manifest = {"built_by": "dev/build_lbs_cases.py", "lbs_engine_version": LBS_VERSION,
                "lbs_calibration": cal.version, "cases": built,
                "records_sha256": hashlib.sha256((OUT / "records.json").read_bytes()).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
