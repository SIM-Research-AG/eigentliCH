"""The fix round after the 20 use cases (29.09.2026): the partner stated to lbs (EIG-53), a re-answer that
restates its fact and the route to restate one (EIG-54), the house's role names on every page (EIG-56),
``hours_learning`` dropped (EIG-58) and each goal's share of the yearly saving (EIG-59). On a throwaway schema
seeded from the prototype, aligned (EIG-44) and revised (EIG-53, EIG-58), with stand-in engines."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from eigentlich import alignment, gaps, inputs, store
from eigentlich import seed as seeding
from eigentlich.alignment import INTAKE

from .appkit import Engines, make_app
from .conftest import TODAY, connect


@pytest.fixture(scope="module")
def revised(settings, st):
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
        owner = store.create_curator(conn, display_name="Nicolas (Owner)")["id"]
    with st.session() as conn:
        alignment.align(conn, curator_id=owner)
    with st.session() as conn:
        v2 = store.content_current(conn, INTAKE)["version"]
        result = alignment.revise(conn, curator_id=owner)
    return {"owner": owner, "result": result, "v2": v2}


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, revised, engines):
    with TestClient(make_app(settings, engines)) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


def new_client(http, name="Anna", age=41) -> str:
    r = http.post("/api/clients", json={"display_name": name, "age_at_registration": age})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def answer(http, cid, name, key, value):
    v = http.get(f"/api/clients/{cid}/questionnaires/{name}").json()["version"]
    r = http.put(f"/api/clients/{cid}/questionnaires/{name}/answers/{key}", json={"content_version": v, "value": value})
    assert r.status_code == 200, r.text
    return r.json()


def last_lbs_request(engines):
    return [r["body"] for r in engines.lbs.requests if r["path"] == "/run"][-1]


PARTNER = {"partner_in_plan": "ja", "partner_age": 36, "partner_income_gross": 92000, "partner_hours_per_week": 42,
           "partner_ahv_years_missing": 0, "partner_qualification_highest": "Berufsausbildung (EFZ)",
           "partner_qualification_year": 2008, "partner_years_in_field": 16, "partner_education_recent": "nein",
           "partner_network_people": 8, "partner_network_reach": "in der Branche", "partner_mandates": 1,
           "partner_health": "0.85", "partner_rest_hours": "10–20"}


# ---------------------------------------------------------------------------- the content (EIG-53, EIG-58)

def test_the_intake_gains_the_partner_section_and_drops_hours_learning(revised, db):
    saved = revised["result"]["saved"][INTAKE]
    assert saved["status"] == "saved" and saved["from_version"] == revised["v2"]
    cur = store.content_current(db, INTAKE)
    assert cur["saved_by_kind"] == "curator" and cur["saved_by_ref"] == revised["owner"]
    assert cur["note"] == alignment.REVISION_NOTE and cur["body"]["version"] == "intake@1.3"
    keys = [q["key"] for q in cur["body"]["questions"]]
    assert "hours_learning" not in keys and "education_hours" in keys and "-hours_learning" in saved["questions"]
    assert set(alignment.PARTNER_KEYS) <= set(keys)
    q = {x["key"]: x for x in cur["body"]["questions"]}
    assert all(q[k]["asked_when"] == {"key": "partner_in_plan", "equals": "ja"} for k in alignment.PARTNER_KEYS[1:])
    assert q["partner_health"]["data_class"] == "K3" and any(s["key"] == "21" for s in cur["body"]["sections"])
    rest = float(q["rest_hours"]["order"])
    assert all(rest < float(q[k]["order"]) for k in alignment.PARTNER_KEYS)
    with db.transaction():
        again = alignment.revise(db, curator_id=revised["owner"])
    assert again["saved"][INTAKE]["status"] == "unchanged"
    assert db.execute("SELECT count(*) AS n FROM scoring_bind_check WHERE status <> 'ok'").fetchone()["n"] == 0


def test_an_hours_learning_answer_to_the_earlier_version_stays_and_is_read(http, revised, settings):
    cid = new_client(http, "Altantwort")
    with connect(settings) as conn:
        store.put_answer(conn, client_id=cid, questionnaire_key=INTAKE, content_version=revised["v2"],
                         question_key="hours_learning", value=6, answered_by_kind="client", answered_by_ref=cid)
        conn.commit()
    q = http.get(f"/api/clients/{cid}/questionnaires/intake").json()
    assert q["answers"]["hours_learning"]["value"] == 6 and "hours_learning" not in {x["key"] for x in q["questions"]}
    v = q["version"]
    assert http.put(f"/api/clients/{cid}/questionnaires/intake/answers/hours_learning",
                    json={"content_version": v, "value": 7}).status_code == 404        # no longer asked
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": []})
    with connect(settings) as conn:
        request, _ = inputs.build(inputs.gather(conn, cid), TODAY)
    assert request.household.persons[0].human_capital.hours_learning == 6.0


# ---------------------------------------------------------------------------- the partner (EIG-53)

def test_the_partner_reaches_lbs_with_age_income_and_human_capital(http, engines):
    cid = new_client(http, "Fabienne", 33)
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Fabienne", "Marco"], "dependants": ["Lina"]})
    for key, value in PARTNER.items():
        answer(http, cid, "intake", key, value)
    mine = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Lohn",
                                                            "magnitude": 56000, "magnitude_unit": "chf_per_year"}).json()
    his = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human",
                                                           "label": "Lohn Marco", "magnitude": 92000,
                                                           "magnitude_unit": "chf_per_year", "owner": "partner"}).json()
    assert his["owner"] == "partner" and mine["owner"] is None
    plan = http.get(f"/api/clients/{cid}/plan").json()
    assert plan["partner"] == "Marco"
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    sent = last_lbs_request(engines)
    persons = {p["person_id"]: p for p in sent["household"]["persons"]}
    marco = persons["p2"]
    assert marco["kind"] == "adult" and marco["age"] == 36 and marco["stated_gross_income"] == 92000
    hc = marco["human_capital"]
    assert (hc["qualification_highest"], hc["qualification_year"], hc["years_in_field"], hc["network_people"],
            hc["network_reach"], hc["mandates"], hc["health"], hc["hours_per_week"], hc["rest_hours"],
            hc["education_recent"]) == ("Berufsausbildung (EFZ)", 2008, 16, 8, "in der Branche", 1, "0.85", 42,
                                        "10–20", "nein")
    assert marco["ahv"]["contribution_years_missing"] == 0 and persons["p3"]["age"] is None
    owners = {p["position_id"]: p["owner"] for p in sent["positions"]}
    assert owners[his["id"]] == "p2" and owners[mine["id"]] == "p1"


def test_the_partner_health_answer_is_k3(http, settings):
    cid = new_client(http, "Klasse")
    answer(http, cid, "intake", "partner_in_plan", "ja")
    answer(http, cid, "intake", "partner_health", "0.7")
    with connect(settings) as conn:
        row = conn.execute("SELECT data_class FROM answer WHERE client_id = %s AND question_key = 'partner_health'",
                           (cid,)).fetchone()
    assert row["data_class"] == 3


def test_a_partner_marked_out_of_the_plan_is_sent_by_kind_only(http, settings):
    cid = new_client(http, "Ohne")
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich", "Kim"], "dependants": []})
    answer(http, cid, "intake", "partner_in_plan", "ja")
    answer(http, cid, "intake", "partner_age", 50)
    answer(http, cid, "intake", "partner_in_plan", "nein")
    pos = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human",
                                                           "label": "Lohn Kim", "owner": "partner"}).json()
    with connect(settings) as conn:
        request, dropped = inputs.build(inputs.gather(conn, cid), TODAY)
    kim = request.household.persons[1]
    assert kim.age is None and kim.stated_gross_income is None
    assert next(p for p in request.positions if p.position_id == pos["id"]).owner == "p2"   # still the partner's


def test_a_partners_position_without_a_partner_has_no_owner(http, settings):
    cid = new_client(http, "Allein")
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": ["Kind"]})
    pos = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human",
                                                           "label": "Lohn", "owner": "partner"}).json()
    with connect(settings) as conn:
        request, dropped = inputs.build(inputs.gather(conn, cid), TODAY)
    assert request.positions[0].owner is None and any("partner" in d for d in dropped)
    r = http.patch(f"/api/clients/{cid}/positions/{pos['id']}", json={"owner": "client"})
    assert r.status_code == 200 and r.json()["owner"] is None
    assert http.patch(f"/api/clients/{cid}/positions/{pos['id']}", json={"owner": "Kind"}).status_code == 422


def test_a_gap_about_the_partner_points_to_the_partner_section():
    out = gaps.describe([
        {"section": "human_capital", "input": "p2.E", "kind": "not_in_the_request", "reason": "..."},
        {"section": "human_capital", "input": "p1.E", "kind": "not_in_the_request", "reason": "..."},
        {"section": "pensions.p2", "input": "age", "kind": "not_in_the_request", "reason": "..."},
        {"section": "pensions.p1", "input": "age", "kind": "not_in_the_request", "reason": "..."},
    ], goals={}, positions={}, persons={"p1": "Fabienne", "p2": "Marco"})
    by = {(g["key"], g["name"]): g for g in out}
    assert by[("human_capital.E", "Marco")]["action"] == "intake"
    assert by[("human_capital.E", "Fabienne")]["action"] == "onboarding"
    assert by[("pensions.age", "Marco")]["action"] == "intake" and by[("pensions.age", "Marco")]["group"] == "you"
    assert by[("pensions.age", "Fabienne")]["group"] == "us"


# ---------------------------------------------------------------------------- facts (EIG-54)

def _complete(http, cid):
    for key, value in [("household_composition", {"adults": ["Ich"], "dependants": []}),
                       ("employment_position", "Anstellung"), ("canton", "Bern"), ("health", 0.85),
                       ("civil_status", "ledig")]:
        answer(http, cid, "onboarding", key, value)
    assert http.post(f"/api/clients/{cid}/onboarding/complete").status_code == 200


def test_answering_again_restates_the_fact_so_lbs_reads_the_new_answer(http, settings, engines):
    """Regression: a stated fact wins over an answer, and the app had no way to restate it, so an answer given
    again after the first conversation never reached lbs."""
    cid = new_client(http, "Umzug")
    _complete(http, cid)
    r = answer(http, cid, "onboarding", "canton", "Zürich")
    assert r["restated_fact"] == "canton"
    with connect(settings) as conn:
        request, _ = inputs.build(inputs.gather(conn, cid), TODAY)
        facts = conn.execute("SELECT stated_value, superseded_on, data_class FROM client_fact WHERE client_id = %s "
                             "AND stated_key = 'canton' ORDER BY created_at", (cid,)).fetchall()
        last = conn.execute("SELECT question, choice, author FROM decision WHERE client_id = %s ORDER BY seq DESC "
                            "LIMIT 1", (cid,)).fetchone()
    assert request.facts.canton == "Zürich"
    assert [f["stated_value"] for f in facts] == ["Bern", "Zürich"] and facts[0]["superseded_on"] is not None
    assert facts[1]["data_class"] == facts[0]["data_class"] and last["author"] == "client" and "canton" in last["question"]
    assert answer(http, cid, "onboarding", "canton", "Zürich")["restated_fact"] is None        # the same: nothing
    answer(http, cid, "onboarding", "health", 0.5)
    with connect(settings) as conn:
        choice = conn.execute("SELECT choice FROM decision WHERE client_id = %s ORDER BY seq DESC LIMIT 1",
                              (cid,)).fetchone()["choice"]
        health = conn.execute("SELECT stated_value, data_class FROM client_fact WHERE client_id = %s AND "
                              "stated_key = 'health' AND superseded_on IS NULL", (cid,)).fetchone()
    assert health["stated_value"] == 0.5 and health["data_class"] == 3 and "0.5" not in choice


def test_an_answer_without_a_fact_restates_nothing(http, settings):
    cid = new_client(http, "Vorher")
    assert answer(http, cid, "onboarding", "canton", "Bern")["restated_fact"] is None
    with connect(settings) as conn:
        assert conn.execute("SELECT count(*) AS n FROM client_fact WHERE client_id = %s", (cid,)).fetchone()["n"] == 0


def test_a_fact_is_restated_directly(http, settings):
    cid = new_client(http, "Direkt")
    _complete(http, cid)
    r = http.put(f"/api/clients/{cid}/facts/civil_status", json={"value": "verheiratet", "reasoning": "Heirat"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True and r.json()["fact"]["stated_value"] == "verheiratet"
    again = http.put(f"/api/clients/{cid}/facts/civil_status", json={"value": "verheiratet"})
    assert again.json()["changed"] is False
    assert http.put(f"/api/clients/{cid}/facts/health", json={"value": "gut"}).status_code == 422   # a number
    assert http.put(f"/api/clients/{cid}/facts/Canton", json={"value": "Bern"}).status_code == 422
    assert http.put(f"/api/clients/{cid}/facts/canton", json={"value": ""}).status_code == 422
    new = http.put(f"/api/clients/{cid}/facts/wohnform", json={"value": "Miete"})          # no question fills it
    assert new.status_code == 200 and new.json()["fact"]["data_class"] == 2
    with connect(settings) as conn:
        request, _ = inputs.build(inputs.gather(conn, cid), TODAY)
        d = conn.execute("SELECT reasoning FROM decision WHERE client_id = %s AND reasoning = 'Heirat'", (cid,)).fetchone()
    assert request.facts.civil_status == "verheiratet" and d is not None
    plan = http.get(f"/api/clients/{cid}/plan").json()
    assert plan["fact_labels"]["canton"] and {f["stated_key"] for f in plan["facts"]} >= {"canton", "civil_status"}


# ---------------------------------------------------------------------------- shares of the saving (EIG-59)

def test_each_goals_share_of_the_saving_is_stored_checked_and_sent(http, settings, engines):
    cid = new_client(http, "Anteile")
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": []})
    a = http.post(f"/api/clients/{cid}/goals", json={"name": "Reserve", "target_amount": 30000,
                                                     "target_date": "2029-12-31", "contribution_share": 0.6}).json()
    assert http.get(f"/api/clients/{cid}/plan").json()["shares_asked"] is False
    b = http.post(f"/api/clients/{cid}/goals", json={"name": "Weiterbildung", "target_amount": 9000,
                                                     "target_date": "2028-06-30"}).json()
    plan = http.get(f"/api/clients/{cid}/plan").json()
    assert plan["shares_asked"] is True and plan["shares_total"] == 0.6
    too_much = http.patch(f"/api/clients/{cid}/goals/{b['id']}", json={"contribution_share": 0.5})
    assert too_much.status_code == 422 and "110 %" in too_much.json()["detail"]
    assert http.patch(f"/api/clients/{cid}/goals/{b['id']}", json={"contribution_share": 0.4}).status_code == 200
    assert http.patch(f"/api/clients/{cid}/goals/{b['id']}", json={"contribution_share": 1.5}).status_code == 422
    assert http.post(f"/api/clients/{cid}/goals", json={"name": "Mehr", "contribution_share": 0.1}).status_code == 422
    # a goal out of the plan frees its share; coming back, it must fit again
    assert http.post(f"/api/clients/{cid}/goals/{a['id']}/deactivate").status_code == 200
    c = http.post(f"/api/clients/{cid}/goals", json={"name": "Neu", "contribution_share": 0.3}).json()
    assert http.post(f"/api/clients/{cid}/goals/{a['id']}/reactivate").status_code == 422
    assert http.patch(f"/api/clients/{cid}/goals/{c['id']}", json={"contribution_share": None}).status_code == 200
    assert http.post(f"/api/clients/{cid}/goals/{a['id']}/reactivate").status_code == 200
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    sent = {g["goal_id"]: g["contribution_share"] for g in last_lbs_request(engines)["goals"]}
    assert sent == {a["id"]: 0.6, b["id"]: 0.4, c["id"]: None}


def test_shares_above_one_written_directly_are_left_out(http, settings):
    cid = new_client(http, "Direktschreiber")
    a = http.post(f"/api/clients/{cid}/goals", json={"name": "A", "contribution_share": 0.7}).json()
    b = http.post(f"/api/clients/{cid}/goals", json={"name": "B"}).json()
    with connect(settings) as conn:
        with store.plan_change(conn, decision=store.Decision(client_id=cid, author="client", author_ref=cid,
                                                             question="?", choice="!")) as ch:
            ch.update("goal", b["id"], contribution_share=0.7)
        request, dropped = inputs.build(inputs.gather(conn, cid), TODAY)
        conn.rollback()
    assert all(g.contribution_share is None for g in request.goals) and any("140 %" in d for d in dropped)
    assert a["contribution_share"] == 0.7


# ---------------------------------------------------------------------------- the house's role names (EIG-56)

def test_no_english_role_text_reaches_a_german_page(http, settings, engines):
    """Regression: the home page's grid showed lbs's English names and definitions ("Growth", "A holding that
    pays a steady distribution.") on a German page."""
    cid = new_client(http, "Rollen")
    http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Lohn",
                                                     "magnitude": 90000, "magnitude_unit": "chf_per_year"})
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    with connect(settings) as conn:
        roles = store.content_current(conn, "reference/roles")["body"]["roles"]
    english = {x for r in roles for part in ("display", "definition") for x in
               (r[part]["human"]["en"], r[part]["financial"]["en"])} - {"Income"}
    german = {x for r in roles for part in ("display", "definition") for x in
              (r[part]["human"]["de"], r[part]["financial"]["de"])}
    for page in (http.get(f"/api/clients/{cid}/home?language=de").json()["balance_sheet"],
                 http.get(f"/api/clients/{cid}/balance-sheet?language=de").json(),
                 http.get(f"/api/clients/{cid}/plan?language=de").json()):
        text = json.dumps(page, ensure_ascii=False)
        assert not [e for e in english if e in text], [e for e in english if e in text]
        assert '"Income"' not in text and "gain/" not in text and "income/" not in text
    grid = http.get(f"/api/clients/{cid}/balance-sheet?language=de").json()["sheet"]["grid"]
    cell = {(c["role"], c["capital_type"]): c for c in grid}
    assert cell[("gain", "human")]["display"] == "Wachstum" and cell[("gain", "financial")]["display"] == "Wertsteigerung"
    assert cell[("protection", "financial")]["display"] == "Absicherung"
    assert cell[("income", "financial")]["definition"] == "Eine Anlage, die eine stetige Ausschüttung zahlt."
    assert {c["display"] for c in grid} | {c["definition"] for c in grid} <= german
    en = {(c["role"], c["capital_type"]): c for c in
          http.get(f"/api/clients/{cid}/balance-sheet?language=en").json()["sheet"]["grid"]}
    assert en[("gain", "financial")]["display"] == "Gain" and en[("gain", "human")]["display"] == "Growth"
