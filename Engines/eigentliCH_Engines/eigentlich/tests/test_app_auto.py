"""lbs runs by itself after a change (EIG-47), the cockpit's button names its curator, and the backfill.

A throwaway schema seeded from the prototype, stand-in engines, the automatic runs switched on with a short
debounce so the tests wait a fraction of a second rather than five."""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from eigentlich import alignment, store
from eigentlich import seed as seeding
from eigentlich.service import AUTO_REF, BACKFILL_REF
from eigentlich.store import Decision

from .appkit import Engines, make_app, wait_for
from .conftest import connect

DEBOUNCE = 0.4


@pytest.fixture(scope="module")
def seeded(settings, st):
    """Seeded, then aligned as the real store is (EIG-44, EIG-45)."""
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
        owner = store.create_curator(conn, display_name="Owner")["id"]
    with st.session() as conn:
        alignment.align(conn, curator_id=owner)


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, seeded, engines):
    with TestClient(make_app(settings, engines, lbs_auto={"enabled": True, "debounce_s": DEBOUNCE})) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


def new_client(http, name="Auto", age=40) -> str:
    return http.post("/api/clients", json={"display_name": name, "age_at_registration": age}).json()["id"]


def lbs_runs(settings, cid):
    with connect(settings) as conn:
        return conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = 'lbs' ORDER BY created_at",
                            (cid,)).fetchall()


def settled(http, cid):
    """Wait until no automatic run is scheduled or running for the client."""
    wait_for(lambda: http.get(f"/api/clients/{cid}/balance-sheet").json().get("pending") is None, timeout=20)


def test_a_burst_of_changes_makes_one_run(http, settings, engines):
    cid = new_client(http, "Burst")
    v = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()["version"]
    for key, value in [("canton", "Bern"), ("civil_status", "ledig"), ("employment_magnitude", 90000),
                       ("employment_time_basis", 40), ("canton", "Zug")]:
        assert http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/{key}",
                        json={"content_version": v, "value": value}).status_code == 200
    assert http.get(f"/api/clients/{cid}/balance-sheet").json()["pending"] == "scheduled"
    settled(http, cid)
    runs = lbs_runs(settings, cid)
    assert len(runs) == 1 and runs[0]["status"] == "succeeded"
    assert (runs[0]["requested_by_kind"], runs[0]["requested_by_ref"]) == ("system", AUTO_REF)
    assert runs[0]["request"]["facts"]["canton"] == "Zug"                 # the last answer, after the burst
    time.sleep(DEBOUNCE * 2)
    assert len(lbs_runs(settings, cid)) == 1                              # and nothing after it


def test_one_run_at_a_time_and_a_change_during_a_run_runs_once_more(http, settings, engines):
    cid = new_client(http, "Einzeln")
    engines.lbs.delay_s = 2.5                    # long enough that both changes land during the run
    body = {"role": "growth", "capital_type": "financial", "label": "Konto", "magnitude": 1000, "magnitude_unit": "chf",
            "stock_kind": "asset"}
    pid = http.post(f"/api/clients/{cid}/positions", json=body).json()["id"]
    wait_for(lambda: http.get(f"/api/clients/{cid}/balance-sheet").json().get("pending") == "running", timeout=10)
    for amount in (2000, 3000):                                           # during the run
        http.patch(f"/api/clients/{cid}/positions/{pid}", json={"magnitude": amount})
        time.sleep(DEBOUNCE * 1.5)
    settled(http, cid)
    runs = lbs_runs(settings, cid)
    assert len(runs) == 2 and all(r["status"] == "succeeded" for r in runs)
    assert runs[1]["started_at"] >= runs[0]["finished_at"]                # never two at once
    assert runs[1]["request"]["positions"][0]["magnitude"] == 3000


def test_the_home_shows_the_latest_sheet_and_its_age(http, settings):
    cid = new_client(http, "Alter")
    http.post(f"/api/clients/{cid}/goals", json={"name": "Reise", "target_amount": 8000, "target_date": "2028-06-30"})
    settled(http, cid)
    bs = http.get(f"/api/clients/{cid}/home").json()["balance_sheet"]
    assert bs["available"] and bs["pending"] is None and bs["plan_changed_since"] is False
    assert 0 <= bs["age_s"] < 30 and bs["requested_by_kind"] == "system"


def test_a_household_change_runs_for_both_partners(http, settings, st):
    a, b = new_client(http, "Partnerin A"), new_client(http, "Partner B")
    with st.session() as conn:
        with store.plan_change(conn, decision=Decision(client_id=a, author="client", question="Haushalt?",
                                                       choice="A und B")) as ch:
            hh = ch.insert("household", composition_as_of=date(2026, 9, 1), stated_by="client")
            ch.insert("household_member", household_id=hh["id"], client_id=a, label="A", kind="adult")
            ch.insert("household_member", household_id=hh["id"], client_id=b, label="B", kind="adult")
    assert http.put(f"/api/clients/{a}/household", json={"adults": ["A", "B"], "dependants": ["Kind"]}).status_code == 200
    settled(http, a)
    settled(http, b)
    for cid in (a, b):
        runs = lbs_runs(settings, cid)
        assert len(runs) == 1 and runs[0]["requested_by_ref"] == AUTO_REF
        assert len(runs[0]["request"]["household"]["persons"]) == 3


def test_a_change_the_app_did_not_see_runs_when_the_home_opens(http, settings):
    cid = new_client(http, "Cockpit")
    settled(http, cid)
    assert lbs_runs(settings, cid) == []
    with connect(settings) as conn:                                       # as the cockpit would, in SQL
        d = conn.execute("INSERT INTO decision (client_id, author, question, choice) VALUES (%s, 'curator', "
                         "'Lohn?', 'Ja') RETURNING id", (cid,)).fetchone()["id"]
        conn.execute("INSERT INTO position (client_id, role, capital_type, label, magnitude, magnitude_unit, decision_id) "
                     "VALUES (%s, 'income', 'human', 'Lohn', 80000, 'chf_per_year', %s)", (cid, d))
        conn.commit()
    assert http.get(f"/api/clients/{cid}/home").json()["balance_sheet"]["pending"] == "scheduled"
    settled(http, cid)
    assert len(lbs_runs(settings, cid)) == 1


def test_lbs_down_leaves_one_failed_run_and_no_retry_loop(http, settings, engines):
    cid = new_client(http, "Aus")
    engines.lbs.down = True
    http.post(f"/api/clients/{cid}/goals", json={"name": "Auto"})
    settled(http, cid)
    http.get(f"/api/clients/{cid}/home")                                  # the failed run is after the change
    time.sleep(DEBOUNCE * 2)
    runs = lbs_runs(settings, cid)
    assert [r["status"] for r in runs] == ["failed"] and "not reachable" in runs[0]["error"]


def test_the_backfill_runs_lbs_for_every_client_without_a_sheet(http, settings, engines):
    service = http.app.state.service
    with connect(settings) as conn:
        without = conn.execute("SELECT count(*) AS n FROM client c WHERE NOT EXISTS (SELECT 1 FROM engine_run r "
                               "WHERE r.client_id = c.id AND r.engine = 'lbs' AND r.status = 'succeeded')").fetchone()["n"]
    assert without > 0
    assert service.lbs_backfill(dry_run=True)["clients"] == without
    engines.lbs.down = True
    from eigentlich.clients import EngineUnavailable
    with pytest.raises(EngineUnavailable):
        service.lbs_backfill()
    with connect(settings) as conn:
        refs = conn.execute("SELECT count(*) AS n FROM engine_run WHERE requested_by_ref = %s", (BACKFILL_REF,)).fetchone()
    assert refs["n"] == 0                                                 # down: nothing was written
    engines.lbs.down = False
    result = service.lbs_backfill()
    assert len(result["succeeded"]) == without and result["failed"] == {}
    assert service.lbs_backfill()["clients"] == 0


def test_the_yearly_contribution_reaches_the_mandate_and_its_gap_goes(http, settings):
    """EIG-45 end to end: the aligned onboarding's question, answered, is mandate.annual_contribution."""
    cid = new_client(http, "Sparen")
    http.post(f"/api/clients/{cid}/goals", json={"name": "Weltreise", "target_amount": 40000, "target_date": "2030-06-01"})
    settled(http, cid)
    before = {m["key"] for m in http.get(f"/api/clients/{cid}/balance-sheet").json()["missing"]}
    assert "mandate_proposal.annual_contribution" in before
    q = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()
    assert q["version"] == 2 and any(x["key"] == "annual_contribution" for x in q["questions"])
    r = http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/annual_contribution",
                 json={"content_version": q["version"], "value": 24000})
    assert r.status_code == 200, r.text
    assert http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/annual_contribution",
                    json={"content_version": q["version"], "value": -1}).status_code == 422
    settled(http, cid)
    runs = lbs_runs(settings, cid)
    assert runs[-1]["request"]["mandate"]["annual_contribution"] == 24000
    after = {m["key"] for m in http.get(f"/api/clients/{cid}/balance-sheet").json()["missing"]}
    assert "mandate_proposal.annual_contribution" not in after


def test_an_aligned_multi_choice_answer_is_stored_as_a_list(http, settings):
    cid = new_client(http, "Ausschluss")
    v = http.get(f"/api/clients/{cid}/questionnaires/intake").json()["version"]
    base = f"/api/clients/{cid}/questionnaires/intake/answers"
    r = http.put(f"{base}/esg_exclusions", json={"content_version": v, "value": ["Tabak", "Waffen"]})
    assert r.status_code == 200 and r.json()["value"] == ["Waffen", "Tabak"]
    assert http.put(f"{base}/esg_exclusions", json={"content_version": v, "value": "Waffen"}).status_code == 422
    assert http.put(f"{base}/rest_hours", json={"content_version": v, "value": "über 30"}).status_code == 200
    settled(http, cid)
    assert lbs_runs(settings, cid)[-1]["request"]["risk"]["esg_exclusions"] == ["Waffen", "Tabak"]


# ---------------------------------------------------------------------------- the cockpit's button

def test_the_cockpits_run_names_its_curator(http, settings, st):
    cid = new_client(http, "Knopf")
    with st.session() as conn:
        cur = store.create_curator(conn, display_name="Kuratorin Knopf")["id"]
        gone = store.create_curator(conn, display_name="Ehemalig")["id"]
        store.revoke_curator(conn, gone, "test")
    r = http.post(f"/api/clients/{cid}/balance-sheet", json={"curator_id": cur})
    assert r.status_code == 200 and r.json()["available"]
    r = http.post(f"/api/clients/{cid}/balance-sheet")                    # empty body: as before
    assert r.status_code == 200
    kinds = [(x["requested_by_kind"], x["requested_by_ref"]) for x in lbs_runs(settings, cid)]
    assert kinds == [("curator", cur), ("client", cid)]
    for bad in (gone, "0" * 32):
        r = http.post(f"/api/clients/{cid}/balance-sheet", json={"curator_id": bad})
        assert r.status_code == 403, r.text
    assert http.post(f"/api/clients/{cid}/balance-sheet", json={"curator": cur}).status_code == 422
    assert len(lbs_runs(settings, cid)) == 2                              # a refusal runs nothing
