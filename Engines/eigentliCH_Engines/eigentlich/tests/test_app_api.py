"""The consumer app through its HTTP surface, on a throwaway schema seeded from the prototype, with stand-in
engines (httpx.MockTransport). The curator's side is written as role ``curator`` in raw SQL, as the cockpit
writes it (SCHEMA.md section 7)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eigentlich import seed as seeding
from eigentlich import store

from .appkit import Engines, make_app
from .conftest import connect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seeded(settings, st):
    with st.session() as conn:
        report = seeding.seed(conn, settings.prototype_root)
    assert report["ok"]
    return report


@pytest.fixture(scope="module")
def engines():
    return Engines()


@pytest.fixture(scope="module")
def http(settings, seeded, engines):
    with TestClient(make_app(settings, engines)) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset(engines):
    engines.reset()
    yield


@pytest.fixture()
def curator(st):
    with st.session() as conn:
        return store.create_curator(conn, display_name="Kuratorin Test")["id"]


def new_client(http, name="Anna", age=41) -> str:
    r = http.post("/api/clients", json={"display_name": name, "age_at_registration": age})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def as_curator(settings, sql: str, params=()):
    """One statement as role curator, autocommit, names qualified: the cockpit's way."""
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        conn.execute(f"SET search_path TO {settings.database.schema}")
        cur = conn.execute(sql, params)
        return cur.fetchone() if cur.description else None


# ---------------------------------------------------------------------------- standard and picker

def test_health_and_meta(http):
    h = http.get("/health").json()
    assert h["status"] == "ok" and h["store"] == "ok" and h["sign_in"] is False
    assert set(h["engines"]) == {"lbs", "chatbot", "report"} and h["engines"]["lbs"]["reachable"]
    m = http.get("/meta").json()
    assert m["contract_versions"]["ChatRequest(chatbot)"] == "chat-request@1.0.0"
    assert m["settings"]["port"] == 8017 and m["settings"]["store"]["password_set"] in (True, False)
    assert "password" not in json.dumps(m["settings"]).replace("password_set", "")


def test_the_picker_lists_and_creates(http):
    cid = new_client(http, "Picker Test", 30)
    listed = http.get("/api/clients").json()
    row = next(c for c in listed if c["id"] == cid)
    assert row["threads_awaiting_answer"] == 0 and row["onboarding_completed_at"] is None
    assert http.get(f"/api/clients/{cid}").json()["display_name"] == "Picker Test"
    assert http.post("/api/clients", json={"display_name": "Kind", "age_at_registration": 12}).status_code == 422
    assert http.get("/api/clients/" + "0" * 32).status_code == 404
    assert http.patch(f"/api/clients/{cid}", json={"display_name": "Picker Neu"}).json()["display_name"] == "Picker Neu"


def test_no_sign_in_anywhere(http):
    spec = http.get("/openapi.json").json()
    assert not spec.get("components", {}).get("securitySchemes")
    text = json.dumps(spec).lower()
    for word in ("password", "authorization", "bearer", "token", "cookie", "login"):
        assert word not in text, word
    for route in spec["paths"].values():
        for op in route.values():
            assert "security" not in op
    r = http.get("/api/clients")
    assert "set-cookie" not in {k.lower() for k in r.headers}
    client_code = "\n".join(p.read_text("utf-8") for p in (ROOT / "client").rglob("*.js"))
    code = re.sub(r"//[^\n]*", "", client_code)                       # the comments may say what is absent
    for word in ("password", "Authorization", "Bearer", "document.cookie", "credentials", "token"):
        assert word not in code, word
    assert http.get("/").status_code == 200 and "eigentliCH" in http.get("/").text


# ---------------------------------------------------------------------------- questionnaires

def test_every_answer_names_its_version_and_an_edit_makes_a_new_one(http, settings):
    cid = new_client(http, "Versionen")
    q = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()
    v = q["version"]
    assert q["next_question_key"] == "household_composition"
    r = http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/canton", json={"content_version": v, "value": "Bern"})
    assert r.status_code == 200 and r.json()["content_version"] == v

    canton = next(x for x in q["questions"] if x["key"] == "canton")
    edit = {"base_version": v, "question_key": "canton", "question": {"de": "Wo wohnen Sie (Kanton)?"},
            "why": {"en": "For the tax path."}, "note": "Frage kürzer"}
    r = http.post(f"/api/clients/{cid}/questionnaires/onboarding/edit", json=edit)
    assert r.status_code == 201, r.text
    assert r.json()["version"] == v + 1
    history = http.get("/api/questionnaires/onboarding/history").json()
    last = history[-1]
    assert last["version"] == v + 1 and last["saved_by_kind"] == "client" and last["saved_by_ref"] == cid
    assert last["saved_by_name"] == "Versionen"

    q2 = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()
    assert q2["version"] == v + 1 and q2["saved_by_kind"] == "client"
    canton2 = next(x for x in q2["questions"] if x["key"] == "canton")
    assert canton2["question"]["de"] == "Wo wohnen Sie (Kanton)?" and canton2["why"]["en"] == "For the tax path."
    assert canton2["why"]["de"] == canton["why"]["de"] and canton2["options"] == canton["options"]

    r = http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/civil_status",
                 json={"content_version": q2["version"], "value": "verheiratet"})
    assert r.json()["content_version"] == v + 1
    with connect(settings) as conn:
        rows = {a["question_key"]: a["content_version"] for a in store.get_answers(conn, cid, "questionnaire/onboarding")}
    assert rows == {"canton": v, "civil_status": v + 1}

    # a stale edit is refused, never silently overwrites the newer version
    stale = http.post(f"/api/clients/{cid}/questionnaires/onboarding/edit", json={**edit, "question": {"de": "Alt"}})
    assert stale.status_code == 409 and f"version {v + 1}" in stale.json()["detail"]


def test_answers_are_checked_and_superseded(http, settings):
    cid = new_client(http, "Prüfung")
    v = http.get(f"/api/clients/{cid}/questionnaires/onboarding").json()["version"]
    put = lambda key, value, ver=v: http.put(f"/api/clients/{cid}/questionnaires/onboarding/answers/{key}",
                                             json={"content_version": ver, "value": value})
    assert put("canton", "Atlantis").status_code == 422
    assert put("health", 7).status_code == 422
    assert put("no_such_question", 1).status_code == 404
    assert put("canton", "Zug", ver=999).status_code == 422
    assert put("canton", None).status_code == 422
    assert put("canton", "Zug").status_code == 200
    assert put("canton", "Bern").status_code == 200
    with connect(settings) as conn:
        hist = store.get_answers(conn, cid, "questionnaire/onboarding", include_history=True)
        health = conn.execute("SELECT count(*) AS n FROM answer WHERE client_id = %s AND question_key = 'health'",
                              (cid,)).fetchone()["n"]
    assert [a["value"] for a in hist if a["question_key"] == "canton"] == ["Zug", "Bern"]
    assert sum(1 for a in hist if a["superseded_at"] is None) == 1 and health == 0
    assert put("health", 0.85).status_code == 200
    with connect(settings) as conn:
        assert conn.execute("SELECT data_class FROM answer_current WHERE client_id = %s AND question_key = 'health'",
                            (cid,)).fetchone()["data_class"] == 3


def test_resume_point_and_asked_when(http):
    cid = new_client(http, "Weiter")
    base = f"/api/clients/{cid}/questionnaires/onboarding"
    q = http.get(base).json()
    v = q["version"]
    assert q["asked"]["sector"] is False
    http.put(f"{base}/answers/household_composition", json={"content_version": v, "value": {"adults": ["Ich"], "dependants": []}})
    assert http.get(base).json()["next_question_key"] == "employment_position"
    http.put(f"{base}/answers/kader", json={"content_version": v, "value": "Oberste Führung"})
    assert http.get(base).json()["asked"]["sector"] is True
    intake = http.get(f"/api/clients/{cid}/questionnaires/intake").json()
    assert len(intake["sections"]) == 20 and intake["next_question_key"] == "household_code"
    prop = next(x for x in intake["questions"] if x["type"] == "repeat")
    r = http.put(f"/api/clients/{cid}/questionnaires/intake/answers/{prop['key']}",
                 json={"content_version": intake["version"], "value": [{"kind": "Wohnung", "value": 800000}, {}]})
    assert r.status_code == 200 and r.json()["value"] == [{"kind": "Wohnung", "value": 800000}]
    assert http.get(f"/api/clients/{cid}/questionnaires/nonsense").status_code == 404


def test_completing_the_onboarding_writes_the_plan_under_decisions(http, settings):
    cid = new_client(http, "Abschluss", 38)
    base = f"/api/clients/{cid}/questionnaires/onboarding"
    v = http.get(base).json()["version"]
    assert http.post(f"/api/clients/{cid}/onboarding/complete").status_code == 409     # the first question first
    for key, value in [("household_composition", {"adults": ["Ich", "Mia"], "dependants": ["Lou"]}),
                       ("employment_position", "Anstellung als Ingenieurin"), ("employment_magnitude", 120000),
                       ("employment_time_basis", 42), ("first_goal", {"template": "home_ownership", "name": "Wohnung"}),
                       ("canton", "Bern"), ("health", 0.85)]:
        assert http.put(f"{base}/answers/{key}", json={"content_version": v, "value": value}).status_code == 200
    assert http.get(base).json()["can_complete"] is True
    done = http.post(f"/api/clients/{cid}/onboarding/complete")
    assert done.status_code == 200, done.text
    created = done.json()
    assert set(created["facts"]) == {"canton", "health"}
    plan = http.get(f"/api/clients/{cid}/plan").json()
    assert [m["label"] for m in plan["members"]] == ["Ich", "Mia", "Lou"] and plan["members"][0]["client_id"] == cid
    pos = plan["positions"][0]
    assert (pos["label"], pos["magnitude"], pos["magnitude_unit"], pos["time_basis"]) == \
        ("Anstellung als Ingenieurin", 120000.0, "chf_per_year", "42 Std./Woche")
    assert plan["goals"][0]["name"] == "Wohnung" and plan["goals"][0]["kind"] == "property"
    with connect(settings) as conn:
        decisions = store.decisions_of(conn, cid)
        facts = {f["stated_key"]: f for f in store.plan_of(conn, cid)["facts"]}
        owner = conn.execute("SELECT count(*) AS n FROM goal_owner WHERE goal_id = %s", (created["goal"],)).fetchone()["n"]
    assert len(decisions) == 2 and all(d["author"] == "client" for d in decisions)
    assert decisions[0]["txid"] == decisions[1]["txid"]
    assert facts["health"]["data_class"] == 3 and facts["canton"]["data_class"] == 1 and owner == 1
    assert http.post(f"/api/clients/{cid}/onboarding/complete").status_code == 409
    assert http.get(f"/api/clients/{cid}").json()["onboarding_completed_at"]


# ---------------------------------------------------------------------------- the plan (C-09)

def test_a_position_edit_writes_its_decision(http, settings):
    cid = new_client(http, "C09")
    r = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Lohn",
                                                         "magnitude": 90000, "magnitude_unit": "chf_per_year"})
    assert r.status_code == 201, r.text
    pos = r.json()
    r = http.patch(f"/api/clients/{cid}/positions/{pos['id']}", json={"magnitude": 96000, "reasoning": "Lohnausweis 2026"})
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["magnitude"] == 96000 and edited["decision_id"] != pos["decision_id"]
    with connect(settings) as conn:
        d = conn.execute("SELECT * FROM decision WHERE id = %s", (edited["decision_id"],)).fetchone()
        links = conn.execute("SELECT decision_id FROM decision_position WHERE position_id = %s", (pos["id"],)).fetchall()
    assert d["client_id"] == cid and d["author"] == "client" and d["reasoning"] == "Lohnausweis 2026"
    assert "magnitude: 90000.0 → 96000.0" in d["choice"] and "«Lohn»" in d["question"]
    assert {x["decision_id"] for x in links} == {pos["decision_id"], edited["decision_id"]}

    r = http.post(f"/api/clients/{cid}/positions/{pos['id']}/deactivate", json={"reasoning": "Stelle gewechselt"})
    assert r.status_code == 200 and r.json()["active"] is False
    assert http.post(f"/api/clients/{cid}/positions/{pos['id']}/deactivate").status_code == 409
    assert http.post(f"/api/clients/{cid}/positions/{pos['id']}/reactivate").json()["active"] is True
    decisions = http.get(f"/api/clients/{cid}/decisions").json()
    assert len(decisions) == 4 and decisions[0]["question"].endswith("wieder in den laufenden Plan?")

    # the database refuses what the rules refuse, and the app says so
    bad = http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "financial", "label": "Konto",
                                                           "magnitude": -5, "magnitude_unit": "chf", "stock_kind": "asset"})
    assert bad.status_code == 422
    other = new_client(http, "Fremd")
    assert http.patch(f"/api/clients/{other}/positions/{pos['id']}", json={"label": "x"}).status_code == 404


def test_goals_funding_and_household(http, settings):
    cid = new_client(http, "Ziele")
    acct = http.post(f"/api/clients/{cid}/positions", json={
        "role": "stabilisation", "capital_type": "financial", "label": "Sparkonto", "magnitude": 50000,
        "magnitude_unit": "chf", "stock_kind": "asset", "liquidity": "immediate", "vessel": "free"}).json()
    assert acct["tags"] == {"vessel": "free"}
    hh = http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich", "Noa"], "dependants": []})
    assert hh.status_code == 200
    g = http.post(f"/api/clients/{cid}/goals", json={"name": "Frühpensionierung mit 60", "target_amount": 400000,
                                                     "target_date": "2040-01-01", "funded_by": [acct["id"]]})
    assert g.status_code == 201, g.text
    goal = g.json()
    plan = http.get(f"/api/clients/{cid}/plan").json()
    pg = plan["goals"][0]
    assert pg["funded_by"] == [acct["id"]] and pg["kind"] == "retirement"
    r = http.patch(f"/api/clients/{cid}/goals/{goal['id']}", json={"funded_by": []})
    assert r.status_code == 200
    assert http.get(f"/api/clients/{cid}/plan").json()["goals"][0]["funded_by"] == []
    hh2 = http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": ["Kim"]}).json()
    with connect(settings) as conn:
        old = conn.execute("SELECT * FROM household WHERE id = %s", (hh.json()["household"],)).fetchone()
        new = conn.execute("SELECT * FROM household WHERE id = %s", (hh2["household"],)).fetchone()
        owner = conn.execute("SELECT count(*) AS n FROM goal_owner WHERE goal_id = %s", (goal["id"],)).fetchone()["n"]
    assert old["closed_on"] is not None and new["succeeds_household_id"] == old["id"] and owner == 1
    assert [m["label"] for m in http.get(f"/api/clients/{cid}/plan").json()["members"]] == ["Ich", "Kim"]
    assert http.put(f"/api/clients/{cid}/household", json={"adults": []}).status_code == 422


# ---------------------------------------------------------------------------- the balance sheet (lbs)

def test_the_balance_sheet_runs_lbs_and_records_the_run(http, settings, engines):
    cid = new_client(http, "Bilanz Name Geheim", 45)
    http.post(f"/api/clients/{cid}/positions", json={"role": "growth", "capital_type": "financial", "label": "Wertschriften",
                                                     "magnitude": 150000, "magnitude_unit": "chf", "stock_kind": "asset"})
    assert http.get(f"/api/clients/{cid}/balance-sheet").json() == {"available": False, "reason": "not_run", "last_failure": None,
                                                                     "pending": None}
    r = http.post(f"/api/clients/{cid}/balance-sheet")
    assert r.status_code == 200, r.text
    bs = r.json()
    assert bs["available"] and len(bs["sheet"]["grid"]) == 8 and bs["plan_changed_since"] is False
    sent = engines.lbs.requests[-2]["body"]
    assert sent["client_ref"] == cid and sent["positions"][0]["role"] == "gain" and sent["positions"][0]["vessel"] == "free"
    assert "Geheim" not in json.dumps(engines.lbs.requests)
    with connect(settings) as conn:
        run = conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = 'lbs'", (cid,)).fetchone()
    assert run["status"] == "succeeded" and run["artefact_id"] == bs["artefact_id"] and run["requested_by_kind"] == "client"
    assert run["request"]["client_ref"] == cid

    engines.lbs.down = True
    down = http.get(f"/api/clients/{cid}/balance-sheet").json()
    assert down["available"] is False and down["reason"] == "engine" and "not reachable" in down["error"]
    r = http.post(f"/api/clients/{cid}/balance-sheet")
    assert r.status_code == 503 and r.json()["detail"]["engine"] == "lbs"
    with connect(settings) as conn:
        failed = conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND status = 'failed'", (cid,)).fetchone()
    assert failed["engine"] == "lbs" and "not reachable" in failed["error"]
    home = http.get(f"/api/clients/{cid}/home").json()
    assert home["balance_sheet"]["available"] is False and home["client"]["id"] == cid


def test_the_home_names_what_is_missing_in_plain_words(http, engines):
    """EIG-49: no id and no lbs key reaches the page; each gap names the goal and where to add what is missing."""
    cid = new_client(http, "Lücken")
    goal = http.post(f"/api/clients/{cid}/goals", json={"name": "Eigenheim Zug", "template": "home_ownership",
                                                        "target_amount": 900000, "target_date": "2031-06-30"}).json()
    bs = http.post(f"/api/clients/{cid}/balance-sheet").json()
    missing = {m["key"]: m for m in bs["missing"]}
    home = missing["property.the_goal_does_not_say_whether_the_member_will_live_in_it"]
    assert home["name"] == "Eigenheim Zug" and home["action"] == "plan" and home["group"] == "you"
    assert missing["mandate_proposal.annual_contribution"]["action"] == "onboarding"
    assert missing["retirement.the_ahv_table_is_not_approved"]["group"] == "us"
    assert goal["id"] not in json.dumps(bs["missing"])


# ---------------------------------------------------------------------------- threads and approval

def test_a_question_gets_a_spark7_draft_from_approved_notes(http, settings, engines):
    cid = new_client(http, "Fragende")
    engines.chatbot.unverified = ["7258"]
    r = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Wie viel darf ich in die Säule 3a einzahlen?"})
    assert r.status_code == 201, r.text
    tid = r.json()["thread_id"]
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    assert t["state"] == "answered" and [m["author_kind"] for m in t["messages"]] == ["client", "spark7"]
    ai = t["messages"][1]
    assert ai["model"] == "stand-in-model" and ai["chatbot_artefact_id"].startswith("CHAT-") and ai["basis"] == "grounded"
    assert ai["unverified_numbers"] == ["7258"] and ai["in_reply_to_id"] == t["messages"][0]["id"]
    assert ai["sources"] and ai["sources"][0]["key"].startswith("knowledge/saeule-3a")
    sent = engines.chatbot.requests[-1]["body"]
    assert all(re.fullmatch(r"[a-z0-9-]+\.v\d+", g["id"]) for g in sent["grounding"])
    assert sent["grounding"][0]["id"].startswith("saeule-3a") and len(sent["grounding"]) <= 4
    assert all(len(g["text"]) <= 6000 for g in sent["grounding"])
    assert {f["key"] for f in sent["client_facts"]} == {"age"}
    with connect(settings) as conn:
        run = conn.execute("SELECT * FROM engine_run WHERE client_id = %s AND engine = 'chatbot'", (cid,)).fetchone()
    assert run["status"] == "succeeded" and run["artefact_id"] == ai["chatbot_artefact_id"]

    # a follow-up carries the history
    http.post(f"/api/clients/{cid}/threads/{tid}/messages?wait=true", json={"body": "Und als Selbständige?"})
    sent = engines.chatbot.requests[-1]["body"]
    assert [h["role"] for h in sent["history"]] == ["user", "assistant"] and sent["question"] == "Und als Selbständige?"
    assert len(http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"]) == 4


def test_only_approved_notes_ground_an_answer(settings, st):
    from eigentlich import grounding
    with st.session() as conn:
        notes = conn.execute("SELECT * FROM content_current WHERE kind = 'knowledge'").fetchall()
    unapproved = dict(notes[0])
    unapproved["body"] = {**unapproved["body"], "front_matter": {**unapproved["body"]["front_matter"], "approved": False}}
    title = unapproved["body"]["front_matter"]["title_de"]
    chosen = grounding.choose(title, [unapproved], max_notes=4, max_chars_per_note=5800, min_score=1)
    assert chosen == []
    chosen = grounding.choose(title, notes, max_notes=4, max_chars_per_note=5800, min_score=2)
    assert chosen and chosen[0].key == unapproved["key"]
    again = grounding.choose(title, list(reversed(notes)), max_notes=4, max_chars_per_note=5800, min_score=2)
    assert [c.key for c in again] == [c.key for c in chosen]
    long = grounding.choose("Pensionskasse Vorsorge Rente", notes, max_notes=12, max_chars_per_note=500, min_score=1)
    assert long and all(len(c.note.text) <= 500 + 6 for c in long)
    assert grounding.choose("xyzzy", notes, max_notes=4, max_chars_per_note=5800, min_score=2) == []


VORSORGEAUFTRAG = ("Ich bin 67 und verwitwet. Wer entscheidet für mich, wenn ich nach einem Schlaganfall nicht mehr "
                   "urteilsfähig bin, und was gehört in einen Vorsorgeauftrag?")
ERBRECHT = ("Wir wollen das Ferienchalet 2030 unseren zwei Söhnen übertragen und unsere Tochter mit 180 000 Franken "
            "ausgleichen. Ist das im Sinne des Erbrechts gerecht, und was müssen wir beachten?")


def test_numbers_and_inflected_stop_words_do_not_choose_the_notes(seeded, st):
    """Regression (EIG-55): «000», «2030», «unseren», «müssen» scored as terms, and «vorsorge» matched inside
    «vorsorgeauftrag», so the two use-case questions got AHV notes instead of the notes that answer them."""
    from eigentlich import grounding
    with st.session() as conn:
        notes = conn.execute("SELECT * FROM content_current WHERE kind = 'knowledge'").fetchall()
        alias = conn.execute("SELECT body FROM content_current WHERE key = 'reference/search-aliases'").fetchone()
    aliases = grounding.alias_groups(alias["body"]) if alias else []
    pick = lambda q: [c.key.split("/")[1] for c in grounding.choose(
        q, notes, max_notes=4, max_chars_per_note=5800, min_score=2, aliases=aliases)]
    first = pick(VORSORGEAUFTRAG)
    assert first[0] == "vorsorgeauftrag-und-patientenverfuegung", first
    assert not any(k.startswith("ahv-") for k in first[:2])
    second = pick(ERBRECHT)
    assert second and all(k.startswith("erbrecht-") for k in second), second
    assert grounding.words("2030 000 180 unseren unsere müssen gehört Franken zwei") == set()
    assert grounding.words("Säule 3a 2030") == {"saul"}


GROWTH = ("was muss ich machen so dass ich eine persönliche Wachstumsstrategie habe, also mehr einkommen "
          "generieren kann")


def test_the_growth_question_is_grounded_and_carries_the_balance_sheet(http, settings, engines):
    """EIG-51: the owner's question of 29.09.2026 found no note and was refused. Now the best notes above the
    floor are sent, and, since it is about the asker, what the latest sheet says about them; the chatbot's
    general assessment is stored with its basis (EIG-50)."""
    cid = new_client(http, "Wachstum", 38)
    http.put(f"/api/clients/{cid}/household", json={"adults": ["Ich"], "dependants": ["Lou"]})
    http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Anstellung",
                                                     "magnitude": 96000, "magnitude_unit": "chf_per_year"})
    assert http.post(f"/api/clients/{cid}/balance-sheet").status_code == 200
    engines.chatbot.general = True
    r = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": GROWTH})
    assert r.status_code == 201, r.text
    sent = engines.chatbot.requests[-1]["body"]
    assert 1 <= len(sent["grounding"]) <= 4
    facts = {f["key"]: f for f in sent["client_facts"]}
    assert {"age", "human_capital_E", "human_capital_H", "household_income", "household"} <= set(facts)
    assert "human_capital_N" not in facts                                  # absent in the sheet: not sent
    assert facts["household_income"]["value"] == 96000 and facts["household"]["value"] == "1 Erwachsene, 1 Angehörige"
    ai = http.get(f"/api/clients/{cid}/threads/{r.json()['thread_id']}").json()["messages"][-1]
    assert ai["author_kind"] == "spark7" and ai["basis"] == "general" and ai["sources"] == []

    # a question about something general carries no sheet facts
    http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Was ist ein ETF?"})
    assert {f["key"] for f in engines.chatbot.requests[-1]["body"]["client_facts"]} == {"age"}


def test_chatbot_down_keeps_the_question_open_and_a_retry_answers(http, settings, engines):
    cid = new_client(http, "Geduld")
    engines.chatbot.down = True
    tid = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Was ist die AHV?"}).json()["thread_id"]
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    assert t["state"] == "awaiting_answer" and len(t["messages"]) == 1
    assert t["draft"]["state"] == "failed" and "not reachable" in t["draft"]["error"]
    listed = http.get(f"/api/clients/{cid}/threads").json()[0]
    assert listed["draft"]["state"] == "failed"
    assert http.get("/api/clients").json() and any(
        c["id"] == cid and c["threads_awaiting_answer"] == 1 for c in http.get("/api/clients").json())
    with connect(settings) as conn:
        run = conn.execute("SELECT * FROM engine_run WHERE client_id = %s", (cid,)).fetchone()
    assert run["status"] == "failed" and "chatbot" in run["error"]
    engines.chatbot.down = False
    r = http.post(f"/api/clients/{cid}/threads/{tid}/draft?wait=true")
    assert r.status_code == 200 and r.json()["state"] == "done"
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    assert t["state"] == "answered" and t["messages"][-1]["author_kind"] == "spark7"
    # nothing left to draft: a second retry writes nothing
    http.post(f"/api/clients/{cid}/threads/{tid}/draft?wait=true")
    assert len(http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"]) == 2


def test_a_refusal_is_stored_as_spark7s_answer(http, engines):
    cid = new_client(http, "Abgelehnt")
    engines.chatbot.refusal = True
    tid = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Wie wird das Wetter morgen?"}).json()["thread_id"]
    ai = http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"][-1]
    assert ai["author_kind"] == "spark7" and ai["model"].startswith("none") and ai["sources"] == []


def test_curator_answers_and_approval_on_request(http, settings, curator):
    cid = new_client(http, "Freigabe")
    tid = http.post(f"/api/clients/{cid}/threads?wait=true", json={"question": "Was ist ein ETF?"}).json()["thread_id"]
    ai = http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"][-1]
    assert ai["approval"] is None                       # nothing waits without a request

    r = http.post(f"/api/clients/{cid}/approvals", json={"item": "answer", "item_id": ai["id"]})
    assert r.status_code == 201, r.text
    req = r.json()
    assert http.post(f"/api/clients/{cid}/approvals", json={"item": "answer", "item_id": ai["id"]}).status_code == 409
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    assert t["messages"][-1]["approval"]["state"] == "awaiting_curator"
    assert http.get(f"/api/clients/{cid}/threads").json()[0]["awaiting_curator"] is True
    assert http.get(f"/api/clients/{cid}").json()["approvals_awaiting_curator"] == 1
    client_msg = t["messages"][0]["id"]
    assert http.post(f"/api/clients/{cid}/approvals", json={"item": "answer", "item_id": client_msg}).status_code == 404

    # the curator approves, in the cockpit, as role curator
    as_curator(settings, "INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, note) "
                         "VALUES (%s, 'approved', 'curator', %s, 'Geprüft.')", (req["id"], curator))
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    a = t["messages"][-1]["approval"]
    assert a["state"] == "approved" and a["event_note"] == "Geprüft." and a["actor_ref"] == curator
    assert http.post(f"/api/clients/{cid}/approvals/{req['id']}/withdraw").status_code == 409

    # a second question: the curator sends a revision, a curator message in the same thread
    http.post(f"/api/clients/{cid}/threads/{tid}/messages?wait=true", json={"body": "Und die Kosten?"})
    ai2 = http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"][-1]
    req2 = http.post(f"/api/clients/{cid}/approvals", json={"item": "answer", "item_id": ai2["id"]}).json()
    as_curator(settings, """
        WITH m AS (INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id)
                   VALUES (%s, 'curator', %s, 'Korrigierte Antwort: die Kosten liegen tiefer.', 'de', %s) RETURNING id)
        INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, revision_item_id, note)
        SELECT %s, 'revision_sent', 'curator', %s, m.id, 'Zahl korrigiert' FROM m""",
               (tid, curator, ai2["id"], req2["id"], curator))
    t = http.get(f"/api/clients/{cid}/threads/{tid}").json()
    last = t["messages"][-1]
    assert last["author_kind"] == "curator" and last["author_name"] == "Kuratorin Test" and last["revises"] == ai2["id"]
    assert t["messages"][-2]["approval"]["state"] == "revised" and t["state"] == "answered"

    # withdrawal by the client
    http.post(f"/api/clients/{cid}/threads/{tid}/messages?wait=true", json={"body": "Noch etwas."})
    ai3 = http.get(f"/api/clients/{cid}/threads/{tid}").json()["messages"][-1]
    req3 = http.post(f"/api/clients/{cid}/approvals", json={"item": "answer", "item_id": ai3["id"]}).json()
    assert http.post(f"/api/clients/{cid}/approvals/{req3['id']}/withdraw").status_code == 200
    states = {a["id"]: a["state"] for a in http.get(f"/api/clients/{cid}/approvals").json()}
    assert states == {req["id"]: "approved", req2["id"]: "revised", req3["id"]: "withdrawn"}
    assert http.post(f"/api/clients/{cid}/threads/{tid}/close").status_code == 200
    assert http.post(f"/api/clients/{cid}/threads/{tid}/messages", json={"body": "zu spät"}).status_code == 409


# ---------------------------------------------------------------------------- reports

def test_report_flow_with_lbs_and_the_curators_allocation(http, settings, engines, curator):
    cid = new_client(http, "Berichtende")
    http.post(f"/api/clients/{cid}/positions", json={"role": "income", "capital_type": "human", "label": "Lohn",
                                                     "magnitude": 80000, "magnitude_unit": "chf_per_year"})
    assert http.post(f"/api/clients/{cid}/reports", json={"kind": "update"}).status_code == 409   # needs a report first
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report", "note": "für die Bank"})
    assert r.status_code == 201 and r.json()["job"]["state"] == "done", r.text
    rows = http.get(f"/api/clients/{cid}/reports").json()
    assert rows[0]["state"] == "fulfilled" and len(rows[0]["reports"]) == 1
    rep = rows[0]["reports"][0]
    assert rep["lbs_artefact_id"].startswith("LBS-") and rep["allocation_artefact_id"] is None
    sent = engines.report.requests[-1]["body"]
    assert sent["client_ref"] == cid and sent["kind"] == "report" and sent["sources"] == [
        {"engine": "lbs", "artefact_id": rep["lbs_artefact_id"]}] and sent["previous_report_id"] is None
    html = http.get(f"/api/clients/{cid}/report/{rep['id']}/html")
    assert html.status_code == 200 and "<h1>Bericht</h1>" in html.text
    assert "script-src" not in html.headers["content-security-policy"] and "default-src 'none'" in html.headers["content-security-policy"]
    assert http.get(f"/api/clients/{new_client(http, 'Neugier')}/report/{rep['id']}/html").status_code == 404

    # the curator ran pcp in the cockpit; the update names it and the previous report
    as_curator(settings, "INSERT INTO engine_run (client_id, engine, request, requested_by_kind, requested_by_ref, "
                         "status, artefact_id, started_at, finished_at) VALUES (%s, 'pcp', '{}', 'curator', %s, "
                         "'running', NULL, now(), NULL)", (cid, curator))
    as_curator(settings, "UPDATE engine_run SET status = 'succeeded', artefact_id = 'ALC-0001', finished_at = now() "
                         "WHERE client_id = %s AND engine = 'pcp'", (cid,))
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "update"})
    assert r.json()["job"]["state"] == "done", r.text
    sent = engines.report.requests[-1]["body"]
    assert sent["kind"] == "update" and {"engine": "pcp", "artefact_id": "ALC-0001"} in sent["sources"]
    assert sent["previous_report_id"] == rep["report_artefact_id"]
    upd = http.get(f"/api/clients/{cid}/reports").json()[0]
    assert upd["kind"] == "update" and upd["reports"][0]["allocation_artefact_id"] == "ALC-0001"
    with connect(settings) as conn:
        engines_run = [r["engine"] for r in conn.execute(
            "SELECT engine FROM engine_run WHERE client_id = %s AND requested_by_kind = 'client' ORDER BY created_at",
            (cid,)).fetchall()]
    assert engines_run == ["lbs", "report", "lbs", "report"]


def test_report_engine_down_keeps_the_request_open(http, settings, engines):
    cid = new_client(http, "Offen")
    engines.report.down = True
    r = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"})
    assert r.status_code == 201 and r.json()["job"]["state"] == "failed" and "report" in r.json()["job"]["error"]
    q = http.get(f"/api/clients/{cid}/reports").json()[0]
    assert q["state"] == "open" and q["reports"] == [] and q["job"]["state"] == "failed"
    assert any(c["id"] == cid and c["report_requests_open"] == 1 for c in http.get("/api/clients").json())
    with connect(settings) as conn:
        runs = {r["engine"]: r["status"] for r in conn.execute(
            "SELECT engine, status FROM engine_run WHERE client_id = %s", (cid,)).fetchall()}
    assert runs == {"lbs": "succeeded", "report": "failed"}
    engines.report.down = False
    assert http.post(f"/api/clients/{cid}/reports/{q['id']}/produce?wait=true").json()["state"] == "done"
    assert http.get(f"/api/clients/{cid}/reports").json()[0]["state"] == "fulfilled"
    assert http.post(f"/api/clients/{cid}/reports/{q['id']}/produce?wait=true").status_code == 409
    assert http.post(f"/api/clients/{cid}/reports/{q['id']}/withdraw").status_code == 409

    engines.lbs.down = True
    q2 = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"}).json()
    assert q2["job"]["state"] == "failed" and "lbs" in q2["job"]["error"]
    assert len(engines.report.requests) and http.post(f"/api/clients/{cid}/reports/{q2['request_id']}/withdraw").status_code == 200
    assert http.get(f"/api/clients/{cid}/reports").json()[0]["state"] == "withdrawn"
    assert http.post(f"/api/clients/{cid}/reports/{q2['request_id']}/produce").status_code == 409


def test_report_approval_and_a_curators_revision(http, settings, curator):
    cid = new_client(http, "Revision")
    rid = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"}).json()["request_id"]
    rep = http.get(f"/api/clients/{cid}/reports").json()[0]["reports"][0]
    assert rep["approval"] is None
    req = http.post(f"/api/clients/{cid}/approvals", json={"item": "report", "item_id": rep["id"]}).json()
    assert req["item_kind"] == "report"
    assert http.get(f"/api/clients/{cid}/reports").json()[0]["reports"][0]["approval"]["state"] == "awaiting_curator"
    # the cockpit asks the backend for the revised report, then names it
    assert http.post(f"/api/clients/{cid}/reports/{rid}/produce?wait=true&revision=true").json()["state"] == "done"
    reports = http.get(f"/api/clients/{cid}/reports").json()[0]["reports"]
    new = next(r for r in reports if r["id"] != rep["id"])
    as_curator(settings, "INSERT INTO approval_event (request_id, event, actor_kind, actor_ref, revision_item_id, note) "
                         "VALUES (%s, 'revision_sent', 'curator', %s, %s, 'Liquidität ergänzt')", (req["id"], curator, new["id"]))
    reports = {r["id"]: r for r in http.get(f"/api/clients/{cid}/reports").json()[0]["reports"]}
    assert reports[rep["id"]]["approval"]["state"] == "revised" and reports[new["id"]]["revises"] == rep["id"]
    assert http.post(f"/api/clients/{cid}/approvals", json={"item": "report", "item_id": "nope"}).status_code == 404


def test_a_revision_is_sent_as_one_and_is_not_the_cached_copy(http, engines, curator):
    """Regression (EIG-57): ``produce?revision=true`` sent the same request again, and the report engine answered
    from its cache: the revised report was the first one's artefact. A revision now names the report it revises
    and carries the curator's note (report-request@1.0.0 ``revision_of`` and ``revision_note``, report 1.2.0)."""
    cid = new_client(http, "Kopie")
    rid = http.post(f"/api/clients/{cid}/reports?wait=true", json={"kind": "report"}).json()["request_id"]
    first = http.get(f"/api/clients/{cid}/reports").json()[0]["reports"][0]
    r = http.post(f"/api/clients/{cid}/reports/{rid}/produce?wait=true&revision=true",
                  json={"revision_note": "Die Liquiditätsreserve ergänzen."})
    assert r.status_code == 200 and r.json()["state"] == "done", r.text
    sent = [x["body"] for x in engines.report.requests if x["path"] == "/report"][-1]
    assert sent["revision_of"] == first["report_artefact_id"] and sent["revision_note"] == "Die Liquiditätsreserve ergänzen."
    reports = http.get(f"/api/clients/{cid}/reports").json()[0]["reports"]
    assert len(reports) == 2 and reports[0]["report_artefact_id"] != first["report_artefact_id"]
    # a second revision revises the latest, or the one named
    http.post(f"/api/clients/{cid}/reports/{rid}/produce?wait=true&revision=true", json={"revision_of": first["id"]})
    sent = [x["body"] for x in engines.report.requests if x["path"] == "/report"][-1]
    assert sent["revision_of"] == first["report_artefact_id"] and "revision_note" not in sent
    # a request that is no revision carries neither field, so a report engine before 1.2.0 still takes it
    plain = [x["body"] for x in engines.report.requests if x["path"] == "/report"][-3]
    assert "revision_of" not in plain and "revision_note" not in plain
    assert http.post(f"/api/clients/{cid}/reports/{rid}/produce?revision=true",
                     json={"revision_of": "0" * 32}).status_code == 404
    assert http.post(f"/api/clients/{cid}/reports/{rid}/produce", json={"revision_note": "x"}).status_code == 422
