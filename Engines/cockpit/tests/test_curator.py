"""The curator workflow (C-16) against a throwaway copy of schema eigentlich, never the real one.

The schema is created as ``t_<hex>`` by its owner role ``eigentlich`` from the store's own
``schema.sql``, and role ``curator`` is granted exactly what provisioning grants it on
``eigentlich`` (USAGE; SELECT, INSERT, UPDATE on tables; USAGE, SELECT on sequences), as the store's
tests do (EIG-26). The cockpit then connects as ``curator`` and nothing else. Needs the PostgreSQL
server at 127.0.0.1:5432; unreachable, the module is skipped with the reason (the rest of the
cockpit's suite needs no database).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from cockpit.api import create_app
from cockpit.settings import ROOT, load
from test_api import aggregation_answer

SCHEMA_SQL = ROOT.parent / "eigentliCH_Engines" / "eigentlich" / "src" / "eigentlich" / "schema.sql"


def _local() -> dict:
    p = ROOT / "config.local.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}


def _owner() -> tuple[str, str]:
    t = _local().get("tests") or {}
    return (os.environ.get("COCKPIT_TEST_OWNER_USER", t.get("owner_user", "eigentlich")),
            os.environ.get("COCKPIT_TEST_OWNER_PASSWORD", t.get("owner_password", "")))


def _curator_password() -> str:
    return os.environ.get("COCKPIT_CURATOR_DB_PASSWORD") or (_local().get("curator_db") or {}).get("password", "")


def owner_conn(schema: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    user, password = _owner()
    conn = psycopg.connect(host="127.0.0.1", port=5432, dbname="simtech", user=user, password=password,
                           connect_timeout=5, row_factory=dict_row, autocommit=autocommit)
    if schema:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        if not autocommit:
            conn.commit()
    return conn


def curator_conn(schema: str) -> psycopg.Connection:
    conn = psycopg.connect(host="127.0.0.1", port=5432, dbname="simtech", user="curator",
                           password=_curator_password(), connect_timeout=5, row_factory=dict_row, autocommit=True)
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    return conn


@pytest.fixture(scope="module")
def schema():
    if not SCHEMA_SQL.is_file():
        pytest.skip(f"the eigentlich store's schema.sql is not at {SCHEMA_SQL}")
    try:
        conn = owner_conn()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable as the schema owner: {str(exc).strip()[:200]}")
    name = f"t_{uuid.uuid4().hex[:12]}"
    with conn:
        s, r = sql.Identifier(name), sql.Identifier("curator")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(s))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(s))
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        # exactly what provisioning grants the curator on schema eigentlich
        owner = sql.Identifier(conn.execute("SELECT current_user AS u").fetchone()["u"])
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(s, r))
        conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}").format(s, r))
        conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(s, r))
        conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT, INSERT, UPDATE ON TABLES "
                             "TO {}").format(owner, s, r))
        conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT USAGE, SELECT ON SEQUENCES "
                             "TO {}").format(owner, s, r))
    conn.close()
    yield name
    assert name.startswith("t_") and name != "eigentlich", f"refusing to drop {name!r}"
    with owner_conn(autocommit=True) as c:
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
        assert c.execute("SELECT count(*) AS n FROM pg_namespace WHERE nspname = %s", (name,)).fetchone()["n"] == 0


QUESTIONNAIRE = {"version": "test@1.0.0", "questions": [
    {"key": "canton", "order": 1, "type": "choice", "question": {"de": "Wohnkanton?"}, "why": {"de": "Steuern."},
     "options": [{"value": "Bern", "label": {"de": "Bern"}}, {"value": "Zug", "label": {"de": "Zug"}}]},
    {"key": "income", "order": 2, "type": "number", "question": {"de": "Einkommen?"}}]}


@pytest.fixture(scope="module")
def world(schema) -> dict:
    """One client with a waiting thread, two AI-drafted answers and a report awaiting approval."""
    w: dict = {}
    with owner_conn(schema) as c:
        one = lambda q, *p: c.execute(q, p).fetchone()  # noqa: E731
        w["curator"] = one("INSERT INTO curator (display_name) VALUES ('Test Kuratorin') RETURNING id")["id"]
        w["revoked"] = one("INSERT INTO curator (display_name) VALUES ('Ehemalig') RETURNING id")["id"]
        c.execute("UPDATE curator SET revoked_at = now(), revoked_reason = 'Test' WHERE id = %s", (w["revoked"],))
        w["client"] = one("INSERT INTO client (display_name, age_at_registration, created_by_kind, created_by_ref) "
                          "VALUES ('Anna Test', 41, 'curator', %s) RETURNING id", w["curator"])["id"]
        w["qkey"] = "questionnaire/cockpit-test"
        one("SELECT save_content(%s, 'questionnaire', %s, 'seed', 'tests') AS v", w["qkey"], Jsonb(QUESTIONNAIRE))
        one("INSERT INTO answer (client_id, questionnaire_key, content_version, question_key, value, answered_by_kind, "
            "answered_by_ref) VALUES (%s, %s, 1, 'canton', '\"Bern\"', 'client', %s) RETURNING id",
            w["client"], w["qkey"], w["client"])
        w["thread"] = one("INSERT INTO thread (client_id, subject, opened_by_kind, opened_by_ref) "
                          "VALUES (%s, 'Säule 3a?', 'client', %s) RETURNING id", w["client"], w["client"])["id"]
        w["question"] = one("INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language) "
                            "VALUES (%s, 'client', %s, 'Wie viel darf ich einzahlen?', 'de') RETURNING id",
                            w["thread"], w["client"])["id"]
        ai_thread = one("INSERT INTO thread (client_id, subject, opened_by_kind, opened_by_ref) "
                        "VALUES (%s, 'AHV', 'client', %s) RETURNING id", w["client"], w["client"])["id"]
        w["ai_thread"] = ai_thread
        for tag in ("ai_approve", "ai_revise"):
            m = one("INSERT INTO thread_message (thread_id, author_kind, author_ref, body, language, model, "
                    "chatbot_artefact_id) VALUES (%s, 'spark7', 'chatbot', %s, 'de', 'minimind', 'CHT-1') RETURNING id",
                    ai_thread, f"Entwurf {tag}")["id"]
            w[tag] = one("INSERT INTO approval_request (client_id, item_kind, item_id, requested_by) "
                         "VALUES (%s, 'answer', %s, %s) RETURNING id", w["client"], m, w["client"])["id"]
        req = one("INSERT INTO report_request (client_id, kind, requested_by_kind, requested_by_ref, language) "
                  "VALUES (%s, 'report', 'client', %s, 'de') RETURNING id", w["client"], w["client"])["id"]
        rep = one("INSERT INTO report (request_id, client_id, report_artefact_id, body_html) "
                  "VALUES (%s, %s, 'RPT-1', '<p>Bericht</p>') RETURNING id", req, w["client"])["id"]
        w["report"] = rep
        w["report_approval"] = one("INSERT INTO approval_request (client_id, item_kind, item_id, requested_by) "
                                   "VALUES (%s, 'report', %s, %s) RETURNING id", w["client"], rep, w["client"])["id"]
    return w


MANDATE = {"client": "c-1", "name": "Wohnung 2031", "currency": "CHF", "target_curve": [0.02] * 25,
           "universe": ["INS-a", "INS-b"], "max_single_position": 0.5, "regime_market": "CH"}


class FakePcp(httpx.AsyncBaseTransport):
    """pcp on 8007: /validate and /run answer; the consumer app on 8017 when ``app`` is set (a callable
    standing in for it, C-20); every other port refuses."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.app = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(await request.aread() or b"{}")
        self.calls.append((request.method, request.url.path, body))
        if request.url.port == 8017 and self.app is not None:
            return self.app(request)
        if request.url.port == 8004:  # aggregation, when the roster names it (C-30)
            return aggregation_answer(request, body)
        if request.url.port == 8006 and request.url.path == "/v1/return-set":  # fmre, stamped for the Regime asked
            q = request.url.params
            return httpx.Response(200, json={"return_set_id": f"RS-{q['regime_id'][4:]}-{q['currency']}",
                                             "provenance": {"regime_id": q["regime_id"]}})
        if request.url.port == 8007:
            if request.url.path == "/validate":
                return httpx.Response(200, json={"ok": True, "problems": [], "notes": []})
            if request.url.path == "/run":
                return httpx.Response(200, json={"run_id": "RUN-p", "status": "succeeded", "artefact_id": "ALC-1",
                                                 "regime_id": body["regime_id"], "idempotency_key": "k", "cached": False})
        raise httpx.ConnectError("refused", request=request)


def make_client(tmp_path: Path, schema: str, mode: str = "development",
                extra: str = "") -> tuple[TestClient, FakePcp]:
    cfg = tmp_path / f"config-{mode}.yaml"
    cfg.write_text(f"""
service: {{mode: {mode}}}
data_dir: {tmp_path.as_posix()}/data
cio: {{writable: ["pcp:/validate"]}}
curator_db: {{host: 127.0.0.1, port: 5432, dbname: simtech, schema: {schema}, user: curator}}
engines:
  - {{key: pcp, number: 7, name: Optimiser, url: "http://127.0.0.1:8007", status: built}}
  - {{key: eigentlich, kind: app, name: eigentliCH consumer app, url: "http://127.0.0.1:8017", status: built}}
{extra}""", encoding="utf-8")
    fake = FakePcp()
    settings = load(cfg, env={"COCKPIT_MODE": mode, "COCKPIT_CURATOR_DB_PASSWORD": _curator_password()})
    return TestClient(create_app(settings, transport=fake)), fake


@pytest.fixture
def api(tmp_path, schema, world):
    client, fake = make_client(tmp_path, schema)
    with client:
        yield client, fake, world


# ---- reads ----------------------------------------------------------------------------------

def test_status_curators_and_the_client_list(api):
    client, _, w = api
    st = client.get("/api/curator/status").json()
    assert st["ok"] and st["role"] == "curator" and st["curators_in_service"] == 1
    curators = {c["id"]: c for c in client.get("/api/curator/curators").json()}
    assert curators[w["curator"]]["in_service"] and not curators[w["revoked"]]["in_service"]
    rows = client.get("/api/curator/clients", params={"q": "anna"}).json()
    assert [r["id"] for r in rows] == [w["client"]]
    assert rows[0]["approvals_awaiting_curator"] >= 1 and rows[0]["report_requests_open"] == 0
    detail = client.get(f"/api/curator/clients/{w['client']}").json()
    a = detail["answers"][0]
    assert a["question_key"] == "canton" and a["value"] == "Bern" and a["content_version"] == 1
    assert a["question"] == {"de": "Wohnkanton?"}, "the question as the answered version put it"
    assert client.get("/api/curator/clients/nosuch").status_code == 404


def test_opening_a_client_is_audited(api, schema):
    client, _, w = api
    r = client.post(f"/api/curator/clients/{w['client']}/sessions", json={"curator_id": w["curator"]})
    assert r.status_code == 201
    with owner_conn(schema) as c:
        ev = c.execute("SELECT kind, actor FROM curator_session_event WHERE session_id = %s", (r.json()["id"],)).fetchall()
    assert ev == [{"kind": "opened", "actor": w["curator"]}]
    assert client.post(f"/api/curator/clients/{w['client']}/sessions", json={"curator_id": w["revoked"]}).status_code == 403


# ---- the role's boundary ----------------------------------------------------------------------

def test_the_curator_cannot_delete(api, schema):
    client, _, w = api
    with curator_conn(schema) as c:
        for table in ("thread_message", "client", "content_record", "parameter_set", "engine_run"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        assert not c.execute("SELECT bool_or(has_table_privilege(format('%%I.%%I', table_schema, table_name), 'DELETE')) AS d "
                             "FROM information_schema.tables WHERE table_schema = %s", (schema,)).fetchone()["d"]
    # and the cockpit offers no way to ask
    assert client.delete(f"/api/curator/clients/{w['client']}").status_code in (404, 405)


def test_a_revoked_curator_is_refused_and_nothing_is_written(api, schema):
    client, fake, w = api
    with owner_conn(schema) as c:
        before = c.execute("SELECT count(*) AS n FROM thread_message").fetchone()["n"]
    r = client.post(f"/api/curator/threads/{w['thread']}/messages", json={"curator_id": w["revoked"], "body": "Hallo"})
    assert r.status_code == 403 and "revoked" in r.json()["detail"]
    r = client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["revoked"], "body": MANDATE})
    assert r.status_code == 403
    r = client.post(f"/api/curator/approvals/{w['report_approval']}/approve", json={"curator_id": w["revoked"]})
    assert r.status_code == 403
    r = client.post("/api/curator/content", json={"curator_id": w["revoked"], "key": w["qkey"], "kind": "questionnaire",
                                                  "body": QUESTIONNAIRE})
    assert r.status_code == 403
    with owner_conn(schema) as c:
        assert c.execute("SELECT count(*) AS n FROM thread_message").fetchone()["n"] == before
    assert client.post("/api/curator/threads/x/messages", json={"body": "no curator named"}).status_code == 422


# ---- the workflow ---------------------------------------------------------------------------

def test_a_thread_answer_appears(api):
    client, _, w = api
    r = client.post(f"/api/curator/threads/{w['thread']}/messages",
                    json={"curator_id": w["curator"], "body": "Bis 7258 CHF im Jahr 2026."})
    assert r.status_code == 201 and r.json()["in_reply_to_id"] == w["question"]
    t = next(t for t in client.get(f"/api/curator/clients/{w['client']}").json()["threads"] if t["id"] == w["thread"])
    assert t["state"] == "answered" and t["messages"][-1]["author_kind"] == "curator"
    assert t["messages"][-1]["author_name"] == "Test Kuratorin"
    assert client.post(f"/api/curator/threads/{w['thread']}/close", json={"curator_id": w["curator"]}).status_code == 200
    r = client.post(f"/api/curator/threads/{w['thread']}/messages", json={"curator_id": w["curator"], "body": "Nachtrag"})
    assert r.status_code == 409 and "closed" in r.json()["detail"]


def test_approve_and_revise_write_one_terminal_event_each(api, schema):
    client, _, w = api
    queue = {a["id"] for a in client.get("/api/curator/approvals").json()}
    assert {w["ai_approve"], w["ai_revise"], w["report_approval"]} <= queue
    r = client.post(f"/api/curator/approvals/{w['ai_approve']}/approve", json={"curator_id": w["curator"], "note": "Geprüft."})
    assert r.status_code == 201 and r.json()["event"] == "approved"
    again = client.post(f"/api/curator/approvals/{w['ai_approve']}/approve", json={"curator_id": w["curator"]})
    assert again.status_code == 409, "every event is terminal: one per request"
    r = client.post(f"/api/curator/approvals/{w['ai_revise']}/revise",
                    json={"curator_id": w["curator"], "note": "Zahl korrigiert", "body": "Korrigierte Antwort."})
    assert r.status_code == 201 and r.json()["event"] == "revision_sent"
    with owner_conn(schema) as c:
        m = c.execute("SELECT author_kind, thread_id, body FROM thread_message WHERE id = %s",
                      (r.json()["revision_item_id"],)).fetchone()
        states = {x["id"]: x["state"] for x in c.execute("SELECT id, state FROM approval_state").fetchall()}
    assert m == {"author_kind": "curator", "thread_id": w["ai_thread"], "body": "Korrigierte Antwort."}
    assert states[w["ai_approve"]] == "approved" and states[w["ai_revise"]] == "revised"
    # a report's revision is produced by the backend; without it there is nothing to name
    r = client.post(f"/api/curator/approvals/{w['report_approval']}/revise", json={"curator_id": w["curator"]})
    assert r.status_code == 422
    assert w["report_approval"] in {a["id"] for a in client.get("/api/curator/approvals").json()}


def test_a_content_save_creates_the_next_version(api):
    client, _, w = api
    before = client.get("/api/curator/content/version", params={"key": w["qkey"]}).json()
    body = json.loads(json.dumps(before["body"]))
    body["questions"][0]["options"].append({"value": "Genf", "label": {"de": "Genf"}})
    body["questions"][0]["why"] = {"de": "Der Kanton bestimmt die Steuern."}
    r = client.post("/api/curator/content", json={"curator_id": w["curator"], "key": w["qkey"], "kind": "questionnaire",
                                                  "body": body, "note": "Option ergänzt"})
    assert r.status_code == 201 and r.json()["version"] == before["version"] + 1
    versions = client.get("/api/curator/content/versions", params={"key": w["qkey"]}).json()
    assert [v["version"] for v in versions][:2] == [before["version"] + 1, before["version"]]
    assert versions[0]["saved_by_kind"] == "curator" and versions[0]["saved_by_ref"] == w["curator"]
    old = client.get("/api/curator/content/version", params={"key": w["qkey"], "version": before["version"]}).json()
    assert len(old["body"]["questions"][0]["options"]) == 2, "the earlier version is kept as it was"
    body["questions"].append(dict(body["questions"][0]))  # a repeated question key
    assert client.post("/api/curator/content", json={"curator_id": w["curator"], "key": w["qkey"], "kind": "questionnaire",
                                                     "body": body}).status_code == 409
    keys = {k["key"]: k for k in client.get("/api/curator/content", params={"kind": "questionnaire"}).json()}
    assert keys[w["qkey"]]["version"] == before["version"] + 1 and keys[w["qkey"]]["questions"] == 2
    assert isinstance(client.get("/api/curator/binds").json(), list)


def test_a_parameter_set_supersedes_the_previous_one(api):
    client, _, w = api
    url = f"/api/curator/clients/{w['client']}/parameter-sets"
    previous = [s["id"] for s in client.get(url).json() if s["current"]]
    first = client.post(url, json={"curator_id": w["curator"], "body": MANDATE, "note": "Erstgespräch"})
    second = client.post(url, json={"curator_id": w["curator"], "body": {**MANDATE, "max_single_position": 0.3}})
    assert first.status_code == second.status_code == 201
    assert first.json()["supersedes_id"] == (previous[0] if previous else None)
    assert second.json()["supersedes_id"] == first.json()["id"]
    sets = client.get(url).json()
    assert [s["id"] for s in sets if s["current"]] == [second.json()["id"]]
    assert second.json()["contract_version"] == "pcp-mandate@1.0.0" and second.json()["finalised_by"] == w["curator"]


def test_a_pcp_run_is_recorded_as_an_engine_run(api):
    client, fake, w = api
    ps = client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["curator"], "body": MANDATE}).json()
    r = client.post(f"/api/curator/clients/{w['client']}/runs",
                    json={"curator_id": w["curator"], "regime_id": "RGM-1", "return_set_id": "RS-1", "speed_mode": "fast"})
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "succeeded" and run["artefact_id"] == "ALC-1" and run["run_id"] == "RUN-p"
    assert run["parameter_set_id"] == ps["id"] and run["requested_by_kind"] == "curator"
    sent = [c for c in fake.calls if c[1] == "/run"][-1][2]
    assert sent == {"regime_id": "RGM-1", "return_set_id": "RS-1", "mandate": MANDATE, "speed_mode": "fast"}
    n = len(fake.calls)
    refused = client.post(f"/api/curator/clients/{w['client']}/runs",
                          json={"curator_id": w["revoked"], "regime_id": "RGM-1", "return_set_id": "RS-1"})
    assert refused.status_code == 403 and len(fake.calls) == n, "a revoked curator never reaches pcp"
    runs = client.get(f"/api/curator/clients/{w['client']}").json()["engine_runs"]
    assert runs[0]["id"] == run["id"] and runs[0]["finished_at"] is not None


def test_a_run_against_a_pcp_that_is_down_is_recorded_as_failed(api, schema):
    client, fake, w = api
    client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["curator"], "body": MANDATE})

    class Down(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("refused", request=request)

    settings = client.app.state.settings  # the same store, with a pcp that refuses every connection
    with TestClient(create_app(settings, transport=Down())) as dead:
        r = dead.post(f"/api/curator/clients/{w['client']}/runs",
                      json={"curator_id": w["curator"], "regime_id": "RGM-1", "return_set_id": "RS-1"})
    assert r.status_code == 201 and r.json()["status"] == "failed" and "not running" in r.json()["error"]


# ---- lbs on demand, through the consumer app (C-20) ---------------------------------------------

def stand_in_app(schema: str, lbs_up: bool = True):
    """The consumer app's POST /api/clients/{id}/balance-sheet as the real one behaves: it builds the
    lbs request itself, records the call as an engine_run (requested by the client), and answers with
    the sheet, or 503 naming lbs when lbs is down (the failed run recorded)."""
    def handle(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if request.method != "POST" or parts[:2] != ["api", "clients"] or parts[3:] != ["balance-sheet"]:
            return httpx.Response(404, json={"detail": "Not Found"})
        cid = parts[2]
        with owner_conn(schema) as c:
            if c.execute("SELECT 1 FROM client WHERE id = %s", (cid,)).fetchone() is None:
                return httpx.Response(404, json={"detail": f"no client {cid}"})
            if lbs_up:
                c.execute("""INSERT INTO engine_run (client_id, engine, request, requested_by_kind, requested_by_ref, run_id,
                                                     artefact_id, status, started_at, finished_at)
                             VALUES (%s, 'lbs', %s, 'client', %s, 'RUN-l', 'LBS-9', 'succeeded', now(), now())""",
                          (cid, Jsonb({"built": "by the app"}), cid))
            else:
                c.execute("""INSERT INTO engine_run (client_id, engine, request, requested_by_kind, requested_by_ref,
                                                     status, error, started_at, finished_at)
                             VALUES (%s, 'lbs', %s, 'client', %s, 'failed', 'lbs is not reachable', now(), now())""",
                          (cid, Jsonb({"built": "by the app"}), cid))
        if not lbs_up:
            return httpx.Response(503, json={"detail": {"engine": "lbs", "error": "lbs is not reachable"}})
        return httpx.Response(200, json={"available": True, "artefact_id": "LBS-9", "made_at": "2026-09-29T10:00:00",
                                         "plan_changed_since": False,
                                         "sheet": {"artefact_id": "LBS-9", "as_of": "2026-09-29", "calibration_version": "c1"}})
    return handle


def test_a_balance_sheet_is_computed_through_the_app_and_its_run_shown(api, schema):
    client, fake, w = api
    fake.app = stand_in_app(schema)
    url = f"/api/curator/clients/{w['client']}/balance-sheet"
    n = len(fake.calls)
    refused = client.post(url, json={"curator_id": w["revoked"]})
    assert refused.status_code == 403 and len(fake.calls) == n, "a revoked curator never reaches the app"
    assert client.post("/api/curator/clients/nosuch/balance-sheet", json={"curator_id": w["curator"]}).status_code == 404
    assert len(fake.calls) == n
    r = client.post(url, json={"curator_id": w["curator"]})
    assert r.status_code == 201
    out = r.json()
    assert fake.calls[-1][:2] == ("POST", f"/api/clients/{w['client']}/balance-sheet")
    assert fake.calls[-1][2] == {"curator_id": w["curator"]}, (
        "the cockpit sends only the acting curator, no lbs request: the app builds it from the client's data")
    run = out["engine_run"]
    assert run["engine"] == "lbs" and run["status"] == "succeeded" and run["artefact_id"] == "LBS-9"
    assert run["request"] == {"built": "by the app"} and out["error"] is None
    assert out["balance_sheet"]["sheet"]["as_of"] == "2026-09-29"
    runs = client.get(f"/api/curator/clients/{w['client']}").json()["engine_runs"]
    lbs = next(x for x in runs if x["engine"] == "lbs" and x["status"] == "succeeded")
    assert lbs["id"] == run["id"], "the Parameters page prefills from the latest lbs run"


def test_lbs_down_behind_the_app_shows_the_failed_run(api, schema):
    client, fake, w = api
    fake.app = stand_in_app(schema, lbs_up=False)
    r = client.post(f"/api/curator/clients/{w['client']}/balance-sheet", json={"curator_id": w["curator"]})
    assert r.status_code == 201
    out = r.json()
    assert out["engine_run"]["status"] == "failed" and out["balance_sheet"] is None
    assert "503" in out["error"] and "lbs" in out["error"] and "not reachable" in out["error"]


def test_the_app_down_is_said_plainly_and_nothing_is_recorded(api, schema):
    client, fake, w = api  # fake.app unset: port 8017 refuses every connection
    with owner_conn(schema) as c:
        before = c.execute("SELECT count(*) AS n FROM engine_run").fetchone()["n"]
    r = client.post(f"/api/curator/clients/{w['client']}/balance-sheet", json={"curator_id": w["curator"]})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "consumer app" in detail and "not running" in detail and "http://127.0.0.1:8017" in detail
    with owner_conn(schema) as c:
        assert c.execute("SELECT count(*) AS n FROM engine_run").fetchone()["n"] == before


# ---- modes (C-02, C-16) -----------------------------------------------------------------------

def test_cio_mode_allows_the_curator_writes_and_pcp_validation_only(tmp_path, schema, world):
    client, fake = make_client(tmp_path, schema, mode="cio")
    w = world
    with client:
        r = client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["curator"], "body": MANDATE})
        assert r.status_code == 201, "the curator's production work is allowed in cio mode"
        assert client.post("/api/pcp/validate", json={"regime_id": "R", "return_set_id": "S", "mandate": MANDATE}).status_code == 200
        n = len(fake.calls)
        assert client.post("/api/pcp/run", json={}).status_code == 403
        assert len(fake.calls) == n, "a pcp run through the proxy never reaches pcp in cio mode"
        r = client.post(f"/api/curator/clients/{w['client']}/runs",
                        json={"curator_id": w["curator"], "regime_id": "RGM-1", "return_set_id": "RS-1"})
        assert r.status_code == 201 and r.json()["status"] == "succeeded", "the recorded route runs pcp"
        # lbs on demand (C-20): the curator route in cio mode; the app's write through the proxy stays refused
        fake.app = stand_in_app(schema)
        n = len(fake.calls)
        assert client.post(f"/api/eigentlich/api/clients/{w['client']}/balance-sheet").status_code == 403
        assert len(fake.calls) == n, "the proxy never forwards a write to the app in cio mode"
        r = client.post(f"/api/curator/clients/{w['client']}/balance-sheet", json={"curator_id": w["curator"]})
        assert r.status_code == 201 and r.json()["engine_run"]["status"] == "succeeded"


# ---- presets and the run's Regime and currency (C-22, C-23) -------------------------------------

PRESETS = ROOT / "dev" / "presets"


def test_presets_are_saved_and_read_back_versioned(api):
    client, fake, w = api
    first = client.get("/api/curator/presets").json()
    assert first["curves"]["version"] is None and "build_presets.py" in first["curves"]["missing"], "not saved yet"
    curves = json.loads((PRESETS / "target-curve-presets.json").read_text(encoding="utf-8"))
    mandates = json.loads((PRESETS / "mandate-presets.json").read_text(encoding="utf-8"))
    for key, body in (("reference/target-curve-presets", curves), ("reference/mandate-presets", mandates)):
        r = client.post("/api/curator/content", json={"curator_id": w["curator"], "key": key, "kind": "reference", "body": body,
                                                      "note": "built by dev/build_presets.py"})
        assert r.status_code == 201 and r.json()["version"] == 1
    edited = json.loads(json.dumps(curves))
    edited["presets"][0]["name"] = "Gain role (edited)"
    r = client.post("/api/curator/content", json={"curator_id": w["curator"], "key": "reference/target-curve-presets",
                                                  "kind": "reference", "body": edited})
    assert r.status_code == 201 and r.json()["version"] == 2, "every save is a new version"
    got = client.get("/api/curator/presets").json()
    assert got["curves"]["version"] == 2 and got["curves"]["body"]["presets"][0]["name"] == "Gain role (edited)"
    assert got["curves"]["saved_by_ref"] == w["curator"]
    assert got["mandates"]["version"] == 1 and len(got["mandates"]["body"]["presets"]) == len(mandates["presets"])
    v1 = client.get("/api/curator/content/version", params={"key": "reference/target-curve-presets", "version": 1}).json()
    assert v1["body"] == curves, "the earlier version is kept as it was"
    assert not fake.calls, "presets are read from the store, not from an engine"
    # a stored mandate preset becomes a finalised parameter set once the client is filled in
    preset = mandates["presets"][0]["mandate"]
    r = client.post(f"/api/curator/clients/{w['client']}/parameter-sets",
                    json={"curator_id": w["curator"], "body": {**preset, "client": w["client"]}, "note": "preset"})
    assert r.status_code == 201 and r.json()["body"]["universe"] == preset["universe"]


def test_the_chosen_regime_and_currency_go_into_the_run(api):
    client, fake, w = api
    mandate = {**MANDATE, "currency": "EUR"}
    client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["curator"], "body": mandate})
    body = {"curator_id": w["curator"], "regime_id": "RGM-scn", "return_set_id": "RS-eur", "currency": "EUR",
            "regime_policy": "stagflation", "base_regime_id": "RGM-base"}
    r = client.post(f"/api/curator/clients/{w['client']}/runs", json=body)
    assert r.status_code == 201, r.text
    sent = [c for c in fake.calls if c[1] == "/run"][-1][2]
    assert sent == {"regime_id": "RGM-scn", "return_set_id": "RS-eur", "mandate": mandate}, \
        "pcp gets the scenario Regime and the EUR ReturnSet, and nothing it does not know"
    run = r.json()
    assert run["request"] == sent, "the engine_run records exactly what pcp was sent"
    assert run["context"] == {"regime_id": "RGM-scn", "regime_policy": "stagflation", "base_regime_id": "RGM-base",
                              "return_set_id": "RS-eur", "currency": "EUR"}
    # a ReturnSet fetched in another currency than the finalised mandate's is refused before pcp is asked
    n = len(fake.calls)
    r = client.post(f"/api/curator/clients/{w['client']}/runs", json={**body, "currency": "USD"})
    assert r.status_code == 409 and "EUR" in r.json()["detail"] and len(fake.calls) == n
    assert client.post(f"/api/curator/clients/{w['client']}/runs", json={**body, "currency": "eur"}).status_code == 422


AGG_AND_FMRE = """  - {key: aggregation, number: 4, name: Aggregation, url: "http://127.0.0.1:8004", status: built}
  - {key: fmre, number: 6, name: Fund Map, url: "http://127.0.0.1:8006", status: built, api: v1}
"""


def test_a_run_naming_no_regime_uses_the_default_optimism_level_even_when_another_is_newer(tmp_path, schema, world):
    """The run route makes the Parameters page's choice (C-30): a caller that names no Regime gets the
    latest succeeded Regime of the default optimism level, although aggregation's newest run is the rogue
    one; a named level, and a scenario derived from the chosen level's Regime, are honoured; the ReturnSet
    is the one fmre serves for that Regime in the mandate's currency."""
    client, fake = make_client(tmp_path, schema, extra=AGG_AND_FMRE)
    w = world
    with client:
        client.post(f"/api/curator/clients/{w['client']}/parameter-sets", json={"curator_id": w["curator"], "body": MANDATE})
        url = f"/api/curator/clients/{w['client']}/runs"
        r = client.post(url, json={"curator_id": w["curator"]})
        assert r.status_code == 201, r.text
        sent = [c for c in fake.calls if c[1] == "/run"][-1][2]
        assert sent == {"regime_id": "RGM-default", "return_set_id": "RS-default-CHF", "mandate": MANDATE},             "the default level's latest Regime, not aggregation's newest run (rogue)"
        assert r.json()["context"] == {"regime_id": "RGM-default", "regime_policy": None, "base_regime_id": None,
                                       "return_set_id": "RS-default-CHF", "currency": "CHF", "optimism": "default"}
        r = client.post(url, json={"curator_id": w["curator"], "optimism": "aggressive", "regime_policy": "stagflation"})
        assert r.status_code == 201, r.text
        ctx = r.json()["context"]
        assert ctx["regime_id"] == "RGM-scn-stagflation-aggressive" and ctx["base_regime_id"] == "RGM-aggressive"
        assert ctx["optimism"] == "aggressive" and ctx["regime_policy"] == "stagflation"
        assert r.json()["request"]["return_set_id"] == "RS-scn-stagflation-aggressive-CHF"
        # a named Regime is used as it is, and its level said; a named level it is not at is refused
        r = client.post(url, json={"curator_id": w["curator"], "regime_id": "RGM-rogue", "return_set_id": "RS-x"})
        assert r.status_code == 201 and r.json()["context"]["optimism"] == "rogue"
        n = len(fake.calls)
        r = client.post(url, json={"curator_id": w["curator"], "regime_id": "RGM-rogue", "return_set_id": "RS-x",
                                   "optimism": "default"})
        assert r.status_code == 409 and "rogue" in r.json()["detail"] and not [c for c in fake.calls[n:] if c[1] == "/run"]
        assert client.post(url, json={"curator_id": w["curator"], "return_set_id": "RS-x"}).status_code == 422
        n = len(fake.calls)
        assert client.post(url, json={"curator_id": w["revoked"]}).status_code == 403 and len(fake.calls) == n,             "a revoked curator asks no engine"
