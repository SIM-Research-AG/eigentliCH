"""The nominal and real view in the app (REAL_VIEW_INTERFACES.md, owner decisions of 29.09.2026), and two bugs:

* the two questions (EIG-60, EIG-61): "Ist der Betrag in heutigen Franken?" per goal, "Steigt der Betrag mit der
  Teuerung?" for the yearly contribution, as the onboarding's next content version, stored per goal and as an
  answer, sent to lbs as ``goals[].amount_basis`` and ``mandate.contribution_indexed`` only when stated;
* the basis of a report (EIG-62) and lbs's real figures on the pages;
* the report's allocation (EIG-63): the current parameter set's run on its base Regime, a scenario only when asked;
* the decision history in plain words (EIG-64).

On a throwaway schema seeded, aligned and revised, with stand-in engines."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eigentlich import alignment, store
from eigentlich import seed as seeding
from eigentlich.alignment import ONBOARDING
from eigentlich.decisions import Renderer

from .appkit import Engines, make_app


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
        before = store.content_current(conn, ONBOARDING)["version"]
        result = alignment.revise_basis(conn, curator_id=owner)
    return {"owner": owner, "result": result, "before": before}


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, world, engines):
    with TestClient(make_app(settings, engines)) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


def new_client(http, name="Vera", age=45) -> str:
    r = http.post("/api/clients", json={"display_name": name, "age_at_registration": age})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def answer(http, cid, name, key, value):
    v = http.get(f"/api/clients/{cid}/questionnaires/{name}").json()["version"]
    return http.put(f"/api/clients/{cid}/questionnaires/{name}/answers/{key}", json={"content_version": v, "value": value})


def lbs_requests(engines):
    return [r["body"] for r in engines.lbs.requests if r["path"] == "/run"]


def sheet_now(http, cid):
    r = http.post(f"/api/clients/{cid}/balance-sheet")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------- the content (EIG-60, EIG-61)

def test_the_onboarding_gains_the_two_questions_saved_by_the_owner(world, db):
    saved = world["result"]["saved"][ONBOARDING]
    assert saved["status"] == "saved" and saved["from_version"] == world["before"]
    assert saved["questions"] == ["contribution_indexed", "goal_amount_basis"]
    cur = store.content_current(db, ONBOARDING)
    assert cur["saved_by_kind"] == "curator" and cur["saved_by_ref"] == world["owner"]
    assert cur["note"] == alignment.BASIS_NOTE and cur["body"]["version"] == "onb2@0.3.0"
    qs = {q["key"]: q for q in cur["body"]["questions"]}
    assert qs["contribution_indexed"]["question"]["de"] == "Steigt der Betrag mit der Teuerung?"
    assert qs["contribution_indexed"]["default"] == "nein"
    assert qs["contribution_indexed"]["order"] > qs["annual_contribution"]["order"]
    assert qs["goal_amount_basis"]["question"]["de"] == "Ist der Betrag in heutigen Franken?"
    assert qs["goal_amount_basis"]["default"] == "today" and qs["goal_amount_basis"]["scope"] == "goal"
    assert [o["value"] for o in qs["goal_amount_basis"]["options"]] == ["today", "future"]
    again = alignment.revise_basis(db, curator_id=world["owner"])
    assert again["saved"][ONBOARDING]["status"] == "unchanged"


def test_the_per_goal_question_is_not_in_the_sequence(http):
    cid = new_client(http, "Sequenz")
    q = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()
    keys = [x["key"] for x in q["questions"]]
    assert "contribution_indexed" in keys and "goal_amount_basis" not in keys
    assert q["goal_questions"] == ["goal_amount_basis"]
    r = answer(http, cid, "onboarding", "goal_amount_basis", "today")
    assert r.status_code == 422 and "asked per goal" in r.json()["detail"]


# ---------------------------------------------------------------------------- what lbs is sent (EIG-60, EIG-61)

def test_a_goals_amount_basis_is_stored_and_sent_only_when_stated(http, engines, settings):
    cid = new_client(http, "Basis")
    r = http.post(f"/api/clients/{cid}/goals", json={"name": "Wohnung", "target_amount": 900000,
                                                    "target_date": "2036-06-30", "amount_basis": "future"})
    assert r.status_code == 201, r.text
    assert r.json()["amount_basis"] == "future"
    plain = http.post(f"/api/clients/{cid}/goals", json={"name": "Reserve", "target_amount": 30000,
                                                        "target_date": "2030-01-31"}).json()
    assert plain["amount_basis"] is None
    assert http.post(f"/api/clients/{cid}/goals", json={"name": "X", "amount_basis": "tomorrow"}).status_code == 422
    sheet_now(http, cid)
    sent = {g["goal_id"]: g for g in lbs_requests(engines)[-1]["goals"]}
    assert sent[r.json()["id"]]["amount_basis"] == "future"
    assert "amount_basis" not in sent[plain["id"]]          # unstated: lbs reads today's francs (decision 7)
    changed = http.patch(f"/api/clients/{cid}/goals/{plain['id']}", json={"amount_basis": "today"})
    assert changed.status_code == 200 and changed.json()["amount_basis"] == "today"
    sheet_now(http, cid)
    assert {g["goal_id"]: g for g in lbs_requests(engines)[-1]["goals"]}[plain["id"]]["amount_basis"] == "today"


def test_the_indexed_contribution_is_sent_only_when_answered(http, engines):
    cid = new_client(http, "Teuerung")
    http.post(f"/api/clients/{cid}/goals", json={"name": "Weltreise", "target_amount": 60000, "target_date": "2032-05-31"})
    assert answer(http, cid, "onboarding", "annual_contribution", 12000).status_code == 200
    sheet_now(http, cid)
    mandate = lbs_requests(engines)[-1]["mandate"]
    assert mandate["annual_contribution"] == 12000 and "contribution_indexed" not in mandate   # fixed (decision 9)
    assert answer(http, cid, "onboarding", "contribution_indexed", "ja").status_code == 200
    sheet_now(http, cid)
    assert lbs_requests(engines)[-1]["mandate"]["contribution_indexed"] is True
    assert answer(http, cid, "onboarding", "contribution_indexed", "nein").status_code == 200
    sheet_now(http, cid)
    assert lbs_requests(engines)[-1]["mandate"]["contribution_indexed"] is False
    assert answer(http, cid, "onboarding", "contribution_indexed", "vielleicht").status_code == 422


# ---------------------------------------------------------------------------- the pages' real figures

def test_the_pages_carry_lbs_s_figures_in_both_bases(http, engines):
    cid = new_client(http, "Beide")
    g = http.post(f"/api/clients/{cid}/goals", json={"name": "Haus", "target_amount": 800000,
                                                    "target_date": "2040-12-31"}).json()
    answer(http, cid, "onboarding", "annual_contribution", 20000)
    bs = sheet_now(http, cid)
    views = bs["views"]
    assert views["available"] is True and views["inflation"]["annual_rate"] == 0.01
    goal = next(x for x in views["goals"] if x["goal_id"] == g["id"])
    assert goal["name"] == "Haus" and goal["nominal"]["amount"] == 1200000 and goal["real"]["amount"] == 800000
    assert views["mandate"]["name"] == "Haus"
    assert views["mandate"]["nominal"]["required_return"] == 0.05 and views["mandate"]["real"]["required_return"] == 0.0396
    plan = http.get(f"/api/clients/{cid}/plan").json()
    assert plan["goal_views"][g["id"]]["real"]["amount"] == 800000
    q = plan["goal_questions"][0]
    assert q["question"] == "Ist der Betrag in heutigen Franken?" and q["default"] == "today" and q["field"] == "amount_basis"
    assert [o["label"] for o in q["options"]] == ["Ja, in heutigen Franken", "Nein, in Franken des Zieldatums"]
    # a sheet without lbs's real view says so; nothing is computed in its place
    engines.lbs.real_view = False
    http.patch(f"/api/clients/{cid}/goals/{g['id']}", json={"target_amount": 810000})
    bs = sheet_now(http, cid)
    assert bs["views"]["available"] is False and bs["views"]["goals"] == []


# ---------------------------------------------------------------------------- the report's basis (EIG-62)

def test_a_report_is_asked_in_its_basis(http, engines):
    cid = new_client(http, "Bericht")
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"})
    assert r.status_code == 201 and r.json()["job"]["state"] == "done", r.text
    assert "basis" not in engines.report.requests[-1]["body"]          # nominal: the request as before
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report", "basis": "real"})
    assert r.status_code == 201 and r.json()["job"]["state"] == "done", r.text
    assert engines.report.requests[-1]["body"]["basis"] == "real"
    rows = http.get(f"/api/clients/{cid}/reports").json()
    assert [x["basis"] for x in rows] == ["real", "nominal"]
    assert http.post(f"/api/clients/{cid}/reports", json={"kind": "report", "basis": "gold"}).status_code == 422


# ---------------------------------------------------------------------------- the allocation (EIG-63)

BASE, OTHER_BASE, STAG, HYPER = ("RGM-00000000000000a1", "RGM-00000000000000a2", "RGM-00000000000000b1",
                                 "RGM-00000000000000b2")


def _pcp_run(conn, cid, owner, pset, regime, artefact):
    run = store.start_engine_run(conn, client_id=cid, engine="pcp", request={"regime_id": regime, "mandate": {}},
                                 requested_by_kind="curator", requested_by_ref=owner, parameter_set_id=pset)
    store.mark_engine_run_running(conn, run["id"])
    return run


@pytest.fixture()
def allocated(http, st, world, engines):
    """A client with a superseded set (a run on a base Regime) and a current set with a run on its base Regime and
    a newer run on a scenario (the order the cockpit leaves them in after a scenario run)."""
    cid = new_client(http, "Allokation")
    owner = world["owner"]
    engines.aggregation.scenarios = [
        {"regime_id": STAG, "policy": "stagflation", "base_regime_id": BASE, "created_at": "2026-09-29T05:00:00+00:00"},
        {"regime_id": HYPER, "policy": "hyperinflation", "base_regime_id": BASE, "created_at": "2026-09-29T05:00:00+00:00"},
    ]
    old = None
    for pset_body, runs in (({"currency": "CHF", "name": "alt"}, [(OTHER_BASE, "PCP-old-set")]),
                            ({"currency": "CHF", "name": "neu"}, [(BASE, "PCP-base"), (STAG, "PCP-stagflation")])):
        with st.session() as conn:
            ps = store.finalise_parameter_set(conn, client_id=cid, engine="pcp", contract_version="pcp-mandate@1.0.0",
                                              body=pset_body, finalised_by=owner)
        for regime, artefact in runs:
            with st.session() as conn:
                run = _pcp_run(conn, cid, owner, ps["id"], regime, artefact)
            with st.session() as conn:
                store.finish_engine_run(conn, run["id"], status="succeeded", artefact_id=artefact)
        old = old if pset_body["name"] == "neu" else ps["id"]
    # the superseded set run once more afterwards (the cockpit can name a set): still not the report's
    with st.session() as conn:
        run = _pcp_run(conn, cid, owner, old, OTHER_BASE, "PCP-old-set-late")
    with st.session() as conn:
        store.finish_engine_run(conn, run["id"], status="succeeded", artefact_id="PCP-old-set-late")
    return cid


def _pcp_source(engines):
    return next((s["artefact_id"] for s in engines.report.requests[-1]["body"]["sources"] if s["engine"] == "pcp"), None)


def test_a_report_takes_the_base_regime_run_of_the_current_set(http, engines, allocated):
    r = http.post(f"/api/clients/{allocated}/reports?wait=true", json={"kind": "report"})
    assert r.json()["job"]["state"] == "done", r.text
    assert _pcp_source(engines) == "PCP-base"                   # not the newer scenario run, not the old set's
    rep = http.get(f"/api/clients/{allocated}/reports").json()[0]["reports"][0]
    assert rep["allocation_artefact_id"] == "PCP-base"
    assert engines.aggregation.requests[-1]["path"] == "/scenarios"


def test_a_scenario_is_taken_only_when_asked_for(http, engines, allocated):
    r = http.post(f"/api/clients/{allocated}/reports?wait=true", json={"kind": "report", "scenario": "stagflation"})
    assert r.json()["job"]["state"] == "done", r.text
    assert _pcp_source(engines) == "PCP-stagflation"
    assert http.get(f"/api/clients/{allocated}/reports").json()[0]["scenario"] == "stagflation"
    r = http.post(f"/api/clients/{allocated}/reports?wait=true", json={"kind": "report", "scenario": "hyperinflation"})
    assert r.json()["job"]["state"] == "failed" and "no pcp run" in r.json()["job"]["error"]
    assert http.post(f"/api/clients/{allocated}/reports", json={"kind": "report", "scenario": "a b"}).status_code == 422


def test_without_aggregation_the_report_waits_rather_than_guess(http, engines, allocated):
    engines.aggregation.down = True
    r = http.post(f"/api/clients/{allocated}/reports?wait=true", json={"kind": "report"})
    job = r.json()["job"]
    assert job["state"] == "failed" and job["engine"] == "aggregation"
    assert http.get(f"/api/clients/{allocated}/reports").json()[0]["state"] == "open"
    assert not [q for q in engines.report.requests if q["body"]["client_ref"] == allocated]


def test_a_real_report_takes_no_nominal_allocation(http, engines, allocated):
    r = http.post(f"/api/clients/{allocated}/reports?wait=true", json={"kind": "report", "basis": "real"})
    assert r.json()["job"]["state"] == "done", r.text
    body = engines.report.requests[-1]["body"]
    assert body["basis"] == "real" and _pcp_source(engines) is None


# ---------------------------------------------------------------------------- the decision history (EIG-64)

ROLES = {"protection": {"human": "Absicherung", "financial": "Absicherung"},
         "growth": {"human": "Wachstum", "financial": "Wertsteigerung"},
         "income": {"human": "Einkommen", "financial": "Einkommen"}}


@pytest.mark.parametrize("stored, plain", [
    ("61,000 CHF, protection", "61’000 CHF, Absicherung"),
    ("Ja: health, network_people", "Ja: Belastbarkeit, Berufliches Netzwerk"),
    ("label: angestellt → Lohn Notarin (80 %)", "Bezeichnung: neu «Lohn Notarin (80 %)», bisher «angestellt»"),
    ("magnitude: 90000.0 → 96000.0; time_basis: — → 40 Std./Woche",
     "Betrag: neu 96’000, bisher 90’000. Zeitbasis: neu «40 Std./Woche»"),
    ("tags: {} → {'vessel': 'pillar_3a'}", "Gefäss: neu Säule 3a"),
    ("contribution_share: — → 0.4", "Anteil am jährlichen Sparbetrag: neu 40 %"),
    ("role: growth → income", "Rolle: neu Einkommen, bisher Wachstum · Wertsteigerung"),
    ("target_amount=62000, target_date=2055-12-31, template=unspecified",
     "Betrag: 62’000 CHF, Bis wann: 31.12.2055, Vorlage: Ein eigenes Ziel"),
    ("Ja, erfassen", "Ja, erfassen"),
])
def test_a_stored_decision_reads_in_plain_german(stored, plain):
    r = Renderer("de", roles=ROLES, templates={"unspecified": "Ein eigenes Ziel"})
    assert r.choice(stored) == plain


def test_a_fact_key_in_a_question_is_named():
    assert Renderer("de").question("Die festgehaltene Angabe «health» nachführen?") == \
        "Die festgehaltene Angabe «Belastbarkeit» nachführen?"
    assert Renderer("de").question("Ziel «haus» ändern?") == "Ziel «haus» ändern?"


def test_the_plan_s_decisions_read_in_plain_words(http, st):
    cid = new_client(http, "Entscheide")
    pos = http.post(f"/api/clients/{cid}/positions", json={"role": "protection", "capital_type": "financial",
                                                           "label": "Säule 3a", "magnitude": 61000,
                                                           "magnitude_unit": "chf", "stock_kind": "asset"}).json()
    http.patch(f"/api/clients/{cid}/positions/{pos['id']}", json={"label": "Säule 3a Bank", "time_basis": "jährlich",
                                                                  "vessel": "pillar_3a"})
    # a decision in the store's raw words, as the earlier builds wrote them
    with st.session() as conn:
        with store.plan_change(conn, decision=store.Decision(
                client_id=cid, author="client", author_ref=cid, question="Säule 3a als Bestand in Franken erfassen?",
                choice="61,000 CHF, protection")) as ch:
            ch.update("position", pos["id"], magnitude=61000.0)
    rows = http.get(f"/api/clients/{cid}/decisions").json()
    assert rows[0]["choice_text"] == "61’000 CHF, Absicherung" and rows[0]["choice"] == "61,000 CHF, protection"
    edit = rows[1]
    assert edit["choice_text"] == edit["choice"]            # written in plain words from the start
    assert edit["choice"].startswith("Bezeichnung: neu «Säule 3a Bank», bisher «Säule 3a»")
    assert "Gefäss: neu Säule 3a" in edit["choice"] and "time_basis" not in edit["choice"]
    en = http.get(f"/api/clients/{cid}/decisions?language=en").json()
    assert en[0]["choice_text"] == "61’000 CHF, Protection"
