"""lbsim (Engine 14) in the app (LBSIM_INTERFACES.md section 7, the app side of section 5; EIG-65 to EIG-69):

* the intake's content version 4, saved by the owner's curator record, earlier answers kept and read (EIG-65);
* the mapping to lbs@1.4.0: ``persons[].earning_power`` and the six new facts only when stated, what is left out
  named, the work capacity withheld with health (K3);
* lbsim after a new sheet only (EIG-67); the two outlook routes, the plan's ``engine_run`` and its refresh, the
  curator's priority plan run (EIG-66);
* the page's payload in one language without ids (EIG-68); the report's lbsim sources and the update with the plan
  (EIG-69); the backfill; the configuration; the browser's charts without a library.

On a throwaway schema seeded, aligned, revised (partner, basis) and revised for lbsim, with stand-in engines (lbsim
on its frozen samples)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eigentlich import alignment, inputs, questionnaires as qn, store
from eigentlich import contracts as c
from eigentlich import seed as seeding
from eigentlich.alignment import INTAKE
from eigentlich.appsettings import load_app
from eigentlich.service import AUTO_REF, PLAN_UPDATE_NOTE

from .appkit import Engines, make_app, wait_for
from .conftest import TODAY, connect

ROOT = Path(__file__).resolve().parents[1]
BASE = "RGM-e2658e8e9bbbc81e"
ALLOCATION = "PCP-0ec347ff879ad640"


@pytest.fixture(scope="module")
def world(settings, st):
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
        owner = store.create_curator(conn, display_name="Nicolas (Owner)")["id"]
    with st.session() as conn:
        alignment.align(conn, curator_id=owner)
    with st.session() as conn:
        alignment.revise(conn, curator_id=owner)
    with st.session() as conn:
        alignment.revise_basis(conn, curator_id=owner)
    with st.session() as conn:
        v3 = store.content_current(conn, INTAKE)["version"]
        result = alignment.revise_earning(conn, curator_id=owner)
    return {"owner": owner, "result": result, "v3": v3}


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, world, engines):
    with TestClient(make_app(settings, engines)) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


def new_client(http, name="Lea", age=38) -> str:
    r = http.post("/api/clients", json={"display_name": name, "age_at_registration": age})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def answer(http, cid, name, key, value):
    v = http.get(f"/api/clients/{cid}/questionnaires/{name}").json()["version"]
    r = http.put(f"/api/clients/{cid}/questionnaires/{name}/answers/{key}", json={"content_version": v, "value": value})
    assert r.status_code == 200, r.text


def last_lbs(engines):
    return [r["body"] for r in engines.lbs.requests if r["path"] == "/run"][-1]


def lbsim_calls(engines, path="/run"):
    return [r for r in engines.lbsim.requests if r["path"] == path]


def with_household(http, cid, adults=("Lea",)):
    assert http.put(f"/api/clients/{cid}/household", json={"adults": list(adults), "dependants": []}).status_code == 200


def with_goals(http, cid):
    home = http.post(f"/api/clients/{cid}/goals", json={"name": "Eigenheim in Luzern", "target_amount": 250000,
                                                         "target_date": "2029-12-31", "occupancy": "Ich wohne selbst darin"})
    ret = http.post(f"/api/clients/{cid}/goals", json={"name": "Ausgaben ab 65", "target_amount": 60000,
                                                        "target_date": "2053-12-31", "template": "retirement"})
    assert home.status_code == 201 and ret.status_code == 201
    return home.json()["id"], ret.json()["id"]


def allocate(st, cid, owner, artefact=ALLOCATION, currency="CHF"):
    with st.session() as conn:
        ps = store.finalise_parameter_set(conn, client_id=cid, engine="pcp", contract_version="pcp-mandate@1.0.0",
                                          body={"currency": currency, "name": "Ausgewogen"}, finalised_by=owner)
    with st.session() as conn:
        run = store.start_engine_run(conn, client_id=cid, engine="pcp", request={"regime_id": BASE, "mandate": {}},
                                     requested_by_kind="curator", requested_by_ref=owner, parameter_set_id=ps["id"])
        store.mark_engine_run_running(conn, run["id"])
    with st.session() as conn:
        store.finish_engine_run(conn, run["id"], status="succeeded", artefact_id=artefact)


def lbsim_rows(settings, cid):
    with connect(settings) as conn:
        return conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = 'lbsim' ORDER BY created_at",
                            (cid,)).fetchall()


def ready_client(http, st, world, engines, name="Lea"):
    cid = new_client(http, name)
    with_household(http, cid)
    with_goals(http, cid)
    allocate(st, cid, world["owner"])
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    return cid


# ---------------------------------------------------------------------------- the content (EIG-65)

def test_the_intake_gains_the_earning_questions_saved_by_the_owner(world, db):
    saved = world["result"]["saved"][INTAKE]
    assert saved["status"] == "saved" and saved["from_version"] == world["v3"]
    cur = store.content_current(db, INTAKE)
    assert cur["saved_by_kind"] == "curator" and cur["saved_by_ref"] == world["owner"]
    assert cur["note"] == alignment.EARNING_NOTE and cur["body"]["version"] == "intake@1.4"
    q = {x["key"]: x for x in cur["body"]["questions"]}
    assert set(alignment.EARNING_KEYS) <= set(q) and set(saved["questions"]) == set(alignment.EARNING_KEYS)
    assert q["income_expected_full"]["question"]["de"].startswith("Welchen Bruttolohn erwarten Sie bei vollem Pensum")
    assert q["income_expected_full"]["why"]["de"] == "Ohne Angabe rechnet das Modell mit seinem eigenen Niveau und sagt das."
    assert [o["value"] for o in q["education_status"]["options"]] == ["keine", "läuft", "geplant"]
    assert q["education_end_year"]["asked_when"] == {"key": "education_status", "in": ["läuft", "geplant"]}
    assert [o["value"] for o in q["health_work_capacity"]["options"]] == ["nein", "leicht", "deutlich", "stark"]
    assert q["health_work_capacity"]["data_class"] == "K3" and q["partner_health_work_capacity"]["data_class"] == "K3"
    assert q["partner_kader"]["options"] == [o for o in q["kader"]["options"] if o.get("offered", True)]
    assert all(q[k]["section"] == "21" for k in alignment.EARNING_KEYS if k.startswith("partner_"))
    order = lambda k: float(q[k]["order"])  # noqa: E731
    assert order("education_recent") < order("education_status") < order("education_end_year") < order("education_hours")
    with db.transaction():
        again = alignment.revise_earning(db, curator_id=world["owner"])
    assert again["saved"][INTAKE]["status"] == "unchanged"
    assert db.execute("SELECT count(*) AS n FROM scoring_bind_check WHERE status <> 'ok'").fetchone()["n"] == 0


def test_asked_when_takes_a_list_of_values_and_several_conditions():
    q = {"key": "x", "asked_when": {"key": "education_status", "in": ["läuft", "geplant"]}}
    assert qn.is_asked(q, {"education_status": "läuft"}) and not qn.is_asked(q, {"education_status": "keine"})
    both = {"key": "y", "asked_when": [{"key": "partner_in_plan", "equals": "ja"},
                                       {"key": "partner_education_status", "in": ["geplant"]}]}
    assert qn.is_asked(both, {"partner_in_plan": "ja", "partner_education_status": "geplant"})
    assert not qn.is_asked(both, {"partner_in_plan": "nein", "partner_education_status": "geplant"})
    assert qn.is_asked({"key": "z"}, {})


def test_an_answer_to_the_earlier_version_stays_and_is_read(http, world, settings):
    cid = new_client(http, "Frühere")
    with_household(http, cid)
    with connect(settings) as conn:
        store.put_answer(conn, client_id=cid, questionnaire_key=INTAKE, content_version=world["v3"],
                         question_key="kader", value="Oberes oder mittleres Kader", answered_by_kind="client",
                         answered_by_ref=cid)
        conn.commit()
        request, _ = inputs.build(inputs.gather(conn, cid), TODAY)
    assert request.household.persons[0].earning_power.responsibility == "Oberes oder mittleres Kader"


# ---------------------------------------------------------------------------- the mapping (lbs@1.4.0)

EARNING = {"income_expected_full": 135000, "kader": "Oberes oder mittleres Kader", "education_status": "läuft",
           "education_end_year": 2028, "education_hours": "3–5", "education_budget": 12000,
           "health_work_capacity": "leicht"}
PARTNER = {"partner_in_plan": "ja", "partner_age": 40, "partner_income_expected_full": 90000,
           "partner_education_status": "keine", "partner_kader": "Keine Führungsfunktion",
           "partner_health_work_capacity": "nein"}


def test_stated_answers_reach_lbs_for_both_adults(http, engines):
    cid = new_client(http, "Erwerb")
    with_household(http, cid, ("Erwerb", "Tom"))
    for key, value in {**EARNING, **PARTNER}.items():
        answer(http, cid, "intake", key, value)
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    persons = {p["person_id"]: p for p in last_lbs(engines)["household"]["persons"]}
    assert persons["p1"]["earning_power"] == {
        "expected_full_pensum_income": 135000, "responsibility": "Oberes oder mittleres Kader",
        "education_status": "in_progress", "education_end_year": 2028, "education_hours": "3–5",
        "education_budget_per_year": 12000, "health_work_capacity": 0.8}
    assert persons["p2"]["earning_power"] == {"expected_full_pensum_income": 90000,
                                              "responsibility": "Keine Führungsfunktion", "education_status": "none",
                                              "health_work_capacity": 1.0}


def test_unstated_answers_are_absent_and_the_request_keeps_its_shape(http, engines):
    cid = new_client(http, "Ohne")
    with_household(http, cid)
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    body = last_lbs(engines)
    assert "earning_power" not in body["household"]["persons"][0]
    assert set(body["facts"]) == {"canton", "civil_status", "has_no_liabilities"}


def test_what_does_not_fit_is_left_out_and_named(world, db, make_client):
    c1 = make_client()
    g = inputs.gather(db, c1["id"])
    num = lambda k, **kw: inputs._number(answers.get(k))  # noqa: E731
    answers = {"education_status": "keine", "education_end_year": 2029, "kader": "Chefin"}
    dropped: list[str] = []
    ep = inputs.earning_power("", lambda k: answers.get(k), num, dropped, TODAY)
    assert ep.education_status == "none" and ep.education_end_year is None and ep.responsibility is None
    assert any("education_end_year" in d for d in dropped) and any("kader" in d for d in dropped)
    answers = {"education_status": "geplant", "education_end_year": 2020}
    dropped = []
    ep = inputs.earning_power("", lambda k: answers.get(k), num, dropped, TODAY)
    assert ep.education_end_year is None and "before 2026" in dropped[0]
    assert inputs.earning_power("", lambda k: None, lambda k, **kw: None, [], TODAY) is None
    assert g.client["id"] == c1["id"]


def test_the_work_capacity_is_withheld_with_health(world):
    answers = {"health_work_capacity": "deutlich"}
    dropped: list[str] = []
    ep = inputs.earning_power("", lambda k: answers.get(k), lambda k, **kw: None, dropped, TODAY, health_withheld=True)
    assert ep is None and "K3" in dropped[0]
    with pytest.raises(ValueError, match="withheld"):
        c.LbsPerson(person_id="p1", kind="adult", human_capital=c.HumanCapitalAnswers(health_withheld=True),
                    earning_power=c.EarningPowerAnswers(health_work_capacity=0.5))
    with pytest.raises(ValueError, match="adults only"):
        c.LbsPerson(person_id="p3", kind="dependant", earning_power=c.EarningPowerAnswers(sector="Banken"))


def test_the_work_capacity_answer_is_k3(http, settings):
    cid = new_client(http, "Klasse")
    answer(http, cid, "intake", "health_work_capacity", "stark")
    with connect(settings) as conn:
        row = conn.execute("SELECT data_class FROM answer WHERE client_id = %s AND question_key = 'health_work_capacity'",
                           (cid,)).fetchone()
    assert row["data_class"] == 3


def test_the_new_facts_are_stated_from_the_intake(http, engines):
    cid = new_client(http, "Fakten")
    with_household(http, cid)
    for key, value in {"work_until_age": 62, "legal_will": "ja", "legal_power_of_attorney": "nein",
                       "pillar3a_contribution": 7258,
                       "properties": [{"kind": "Wohnung", "value": 800000, "occupancy": "Ich wohne selbst darin",
                                       "mortgage": 500000, "fixed_until": 2029, "amortisation_kind": "indirekt über Säule 3a"},
                                      {"kind": "Ferienobjekt", "value": 200000, "occupancy": "Ich vermiete es"}]}.items():
        answer(http, cid, "intake", key, value)
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    facts = last_lbs(engines)["facts"]
    assert facts["stop_work_age"] == 62 and facts["legal_documents"] == ["Testament"]
    assert facts["pillar3a_contribution_per_year"] == 7258 and facts["mortgage_fixed_until"] == "2029-12-31"
    assert facts["amortisation_mode"] == "indirect" and facts["own_use_share"] == 0.8
    answer(http, cid, "intake", "legal_will", "nein")
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    assert last_lbs(engines)["facts"]["legal_documents"] == []                 # answered, none in place: a stated none


# ---------------------------------------------------------------------------- after a new sheet (EIG-67)

def test_lbsim_runs_only_on_a_new_sheet_id(settings, world, engines, st):
    with TestClient(make_app(settings, engines, lbsim_auto={"enabled": True})) as http:
        cid = new_client(http, "Auto")
        with_household(http, cid)
        allocate(st, cid, world["owner"])
        before = len(lbsim_calls(engines))
        assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
        wait_for(lambda: len(lbsim_calls(engines)) == before + 1)
        wait_for(lambda: any(r["status"] == "succeeded" for r in lbsim_rows(settings, cid)))
        sent = lbsim_calls(engines)[-1]["body"]
        assert sent["client_ref"] == cid and sent["allocation_id"] == ALLOCATION and sent["optimise"] == "background"
        rows = lbsim_rows(settings, cid)
        assert (rows[0]["requested_by_kind"], rows[0]["requested_by_ref"], rows[0]["artefact_id"][:4]) == (
            "system", AUTO_REF, "LSP-")
        plan = [r for r in rows if r["request"].get("kind") == "plan"]
        assert len(plan) == 1 and plan[0]["status"] == "running" and plan[0]["run_id"].startswith("RUN-")
        assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200   # the same sheet: no lbsim run
        import time
        time.sleep(0.5)
        assert len(lbsim_calls(engines)) == before + 1
        answer(http, cid, "intake", "income_expected_full", 99000)                  # a new sheet: one more
        assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
        wait_for(lambda: len(lbsim_calls(engines)) == before + 2)


# ---------------------------------------------------------------------------- the routes (EIG-66)

def test_the_cockpit_asks_the_outlook_as_its_curator(http, st, world, engines, settings):
    cid = ready_client(http, st, world, engines, "Kurator")
    r = http.post(f"/api/clients/{cid}/outlook", json={"curator_id": world["owner"]})
    assert r.status_code == 200, r.text
    rows = lbsim_rows(settings, cid)
    assert [(x["requested_by_kind"], x["requested_by_ref"]) for x in rows] == [("curator", world["owner"])] * 2
    fast, plan = rows
    assert fast["status"] == "succeeded" and fast["artefact_id"].startswith("LSP-") and fast["run_id"].startswith("RUN-")
    assert plan["status"] == "running" and plan["run_id"] in engines.lbsim.runs
    assert r.json()["available"] and r.json()["plan"]["state"] == "calculating"
    assert r.json()["recorded"]["plan_engine_run_id"] == plan["id"]


def test_restart_the_plan_is_a_priority_run_of_that_curator(http, st, world, engines, settings):
    cid = ready_client(http, st, world, engines, "Neustart")
    r = http.post(f"/api/clients/{cid}/outlook", json={"curator_id": world["owner"], "optimise": "now"})
    assert r.status_code == 200, r.text
    assert lbsim_calls(engines)[-1]["body"]["optimise"] == "no"
    order = lbsim_calls(engines, "/optimise")[-1]["body"]
    assert order["requested_by"] == {"kind": "curator", "ref": world["owner"]}
    plan = lbsim_rows(settings, cid)[-1]
    assert plan["request"]["contract_version"] == "lbsim-optimise@1.0.0" and plan["status"] == "running"
    assert http.post(f"/api/clients/{cid}/outlook", json={"optimise": "later"}).status_code == 422
    with st.session() as conn:
        gone = store.create_curator(conn, display_name="Weg")["id"]
        store.revoke_curator(conn, gone, "left the house")
    assert http.post(f"/api/clients/{cid}/outlook", json={"curator_id": gone}).status_code == 403


def test_without_a_sheet_nothing_is_asked(http):
    cid = new_client(http, "Leer")
    r = http.post(f"/api/clients/{cid}/outlook")
    assert r.status_code == 409 and "balance sheet" in r.json()["detail"]
    assert http.get(f"/api/clients/{cid}/outlook").json() == {"available": False, "language": "de", "basis": "nominal",
                                                             "pending": False, "reason": "no_sheet"}


def test_the_plan_row_is_refreshed_and_the_page_shows_the_plan(http, st, world, engines, settings):
    cid = ready_client(http, st, world, engines, "Plan")
    http.post(f"/api/clients/{cid}/outlook")
    plan = lbsim_rows(settings, cid)[-1]
    engines.lbsim.finish(plan["run_id"])
    page = http.get(f"/api/clients/{cid}/outlook").json()
    row = lbsim_rows(settings, cid)[-1]
    assert row["status"] == "succeeded" and row["artefact_id"].startswith("LSO-")
    ready = page["plan"]["ready"]
    assert page["plan"]["state"] == "ready" and ready["framing"].startswith("Was die Rechnung annimmt")
    assert ready["action_now"]["saving_chf_per_year"] == 33000.0 and ready["confidence"] == 0.9
    assert ready["goal"] == "Eigenheim in Luzern"
    # a failed plan: the row fails with its kind
    cid2 = ready_client(http, st, world, engines, "Planlos")
    http.post(f"/api/clients/{cid2}/outlook")
    engines.lbsim.finish(lbsim_rows(settings, cid2)[-1]["run_id"], "failed", "timed_out")
    assert http.get(f"/api/clients/{cid2}/outlook").json()["plan"]["state"] == "not_possible"
    failed = lbsim_rows(settings, cid2)[-1]
    assert failed["status"] == "failed" and failed["error"].startswith("timed_out:")


def test_the_page_is_in_one_language_and_names_no_id(http, st, world, engines):
    cid = ready_client(http, st, world, engines, "Sprache")
    http.post(f"/api/clients/{cid}/outlook")
    for lang, other in (("en", "Überschuss"), ("de", "surplus")):
        page = http.get(f"/api/clients/{cid}/outlook?language={lang}").json()
        text = json.dumps(page, ensure_ascii=False)
        assert other not in text
        assert not re.search(r"\b(LBS|LSF|LSP|LSO|RUN|PCP|IDK|RGM)-", text), "an id reached the page"
        assert not re.search(r"[0-9a-f]{32}", text), "a store id reached the page"
    page = http.get(f"/api/clients/{cid}/outlook?language=de").json()
    assert page["earning_power"][0]["name"] == "Lea" and page["earning_power"][0]["level_basis"] == "stated"
    f = page["findings"][0]
    assert "CHF 71’600" in f["trigger"] and "71’634" not in f["trigger"] and "{" not in f["trigger"]
    assert {x["role"] for x in page["paths"]["allocation"]["by_role"]} == {"Wertsteigerung", "Einkommen",
                                                                         "Stabilisierung", "Absicherung"}
    base = next(r for r in page["paths"]["regimes"] if r["key"] == "base")
    assert base["label"] == "Heutige Einschätzung" and base["goals"][0]["name"] == "Eigenheim in Luzern"
    assert page["paths"]["designated_goal_id"] == base["goals"][0]["goal_id"] == "goal1"
    assert any(a["value"] == 0.03 and "Entnahmesatz" in a["text"] for a in page["assumptions"])
    assert page["plan"]["state"] == "calculating"
    card = http.get(f"/api/clients/{cid}/home").json()["outlook"]
    assert card["goal"]["name"] == "Eigenheim in Luzern" and card["goal"]["chance"] == 1.0
    assert len(card["actions"]) <= 3 and card["plan"]["state"] == "calculating"


def test_without_an_allocation_the_findings_come_alone(http, engines, settings):
    cid = new_client(http, "Ohne Allokation")
    with_household(http, cid)
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    r = http.post(f"/api/clients/{cid}/outlook").json()
    assert lbsim_calls(engines)[-1]["body"]["allocation_id"] is None
    assert r["paths"] is None and r["plan"]["state"] == "waiting_for_allocation" and r["no_allocation"] == "no_parameter_set"
    rows = lbsim_rows(settings, cid)
    assert len(rows) == 1 and rows[0]["artefact_id"].startswith("LSF-")


def test_lbsim_down_is_said_and_nothing_is_made_up(http, st, world, engines):
    cid = ready_client(http, st, world, engines, "Unten")
    engines.lbsim.down = True
    assert http.get(f"/api/clients/{cid}/outlook").json()["reason"] == "engine"
    r = http.post(f"/api/clients/{cid}/outlook")
    assert r.status_code == 503 and r.json()["detail"]["engine"] == "lbsim"
    assert http.get(f"/api/clients/{cid}/home").json()["outlook"]["available"] is False


# ---------------------------------------------------------------------------- the report (EIG-69)

def _sources(engines):
    return [(s["engine"], s["artefact_id"][:4]) for s in engines.report.requests[-1]["body"]["sources"]]


def test_a_report_draws_on_findings_and_paths_then_an_update_carries_the_plan(http, st, world, engines, settings):
    cid = ready_client(http, st, world, engines, "Bericht")
    http.post(f"/api/clients/{cid}/outlook")
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"})
    assert r.json()["job"]["state"] == "done", r.text
    assert _sources(engines) == [("lbs", "LBS-"), ("pcp", "PCP-"), ("lbsim", "LSF-"), ("lbsim", "LSP-")]
    engines.lbsim.finish(lbsim_rows(settings, cid)[-1]["run_id"])
    http.get(f"/api/clients/{cid}/outlook")                     # the refresh finds the plan: the update is asked
    wait_for(lambda: len(http.get(f"/api/clients/{cid}/reports").json()) == 2
             and http.get(f"/api/clients/{cid}/reports").json()[0]["state"] == "fulfilled")
    update = http.get(f"/api/clients/{cid}/reports").json()[0]
    assert update["kind"] == "update" and update["note"] == PLAN_UPDATE_NOTE
    assert ("lbsim", "LSO-") in _sources(engines)
    http.get(f"/api/clients/{cid}/outlook")                     # asked once only
    assert len(http.get(f"/api/clients/{cid}/reports").json()) == 2


def test_a_real_report_with_lbsim_paths_leaves_the_pcp_source_out(http, st, world, engines):
    cid = ready_client(http, st, world, engines, "Real")
    http.post(f"/api/clients/{cid}/outlook")
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report", "basis": "real"})
    assert r.json()["job"]["state"] == "done", r.text
    kinds = _sources(engines)
    assert ("lbsim", "LSP-") in kinds and not any(e == "pcp" for e, _ in kinds)


def test_the_mirror_takes_one_lbsim_source_per_kind():
    ok = c.ReportRequest(client_ref="c1", kind="report", language="de",
                         sources=(c.SourceRef(engine="lbs", artefact_id="LBS-1"),
                                  c.SourceRef(engine="lbsim", artefact_id="LSF-1"),
                                  c.SourceRef(engine="lbsim", artefact_id="LSP-1")))
    assert len(ok.sources) == 3
    with pytest.raises(ValueError, match="one source per engine"):
        c.ReportRequest(client_ref="c1", kind="report", language="de",
                        sources=(c.SourceRef(engine="lbsim", artefact_id="LSF-1"),
                                 c.SourceRef(engine="lbsim", artefact_id="LSF-2")))


# ---------------------------------------------------------------------------- backfill, configuration

def test_the_backfill_refuses_when_lbsim_is_down_then_runs_each_newest_sheet_once(http, st, world, engines, settings):
    from eigentlich.api import create_app  # noqa: F401 - the app's own Service
    service = http.app.state.service
    ready_client(http, st, world, engines, "Nachtrag")
    engines.lbsim.down = True
    with pytest.raises(Exception, match="not reachable"):
        service.lbsim_backfill()
    engines.lbsim.down = False
    first = service.lbsim_backfill()
    assert first["succeeded"] and not first["failed"]
    assert service.lbsim_backfill()["clients"] == 0


def test_the_lbsim_settings_and_their_environment_override(monkeypatch, settings):
    cfg = load_app(store=settings)
    assert cfg.lbsim_url == "http://127.0.0.1:8014" and cfg.timeouts.lbsim_s == 60 and cfg.lbsim_auto.enabled
    monkeypatch.setenv("EIGENTLICH_LBSIM_URL", "http://lbsim:8014/")
    assert load_app(store=settings).lbsim_url == "http://lbsim:8014"


# ---------------------------------------------------------------------------- the browser (charts.js, outlook.js)

CHARTS = (ROOT / "client" / "app" / "charts.js").read_text(encoding="utf-8")
OUTLOOK = (ROOT / "client" / "surfaces" / "outlook.js").read_text(encoding="utf-8")
DOM = (ROOT / "client" / "app" / "dom.js").read_text(encoding="utf-8")


def test_the_charts_are_svg_built_in_the_browser_without_a_library():
    assert "createElementNS" in DOM and "http://www.w3.org/2000/svg" in DOM
    code = re.sub(r"//[^\n]*", "", CHARTS)
    assert "import { svg" in CHARTS or "svg(" in code
    assert "http" not in code.replace("http://www.w3.org", "") and "<script" not in code and "innerHTML" not in code
    for name in ("weightsChart", "fitChart", "fanChart"):
        assert f"export function {name}" in CHARTS
    assert "role: 'img'" in CHARTS and "viewBox" in CHARTS


def test_the_switch_redraws_every_chart():
    code = re.sub(r"//[^\n]*", "", OUTLOOK)
    body = re.search(r"function drawCharts\([^)]*\)\s*\{(.*?)\n  \}", code, re.S).group(1)
    assert all(name in body for name in ("weightsChart(", "fitChart(", "fanChart("))
    callback = re.search(r"basisSwitch\(L, (\w+)\)", code).group(1)
    handler = re.search(rf"function {callback}\([^)]*\)\s*\{{(.*?)\n  \}}", code, re.S).group(1)
    redraw = re.search(r"function redrawAll\(\)\s*\{(.*?)\n  \}", code, re.S).group(1)
    assert "redrawAll()" in handler and "drawCharts(" in redraw


def test_the_outlook_page_prints_no_raw_key():
    code = re.sub(r"//[^\n]*", "", OUTLOOK)
    for raw in ("artefact_id", "run_id", "goal_id}", ".code}", "question_key"):
        assert raw not in code, raw
