"""The app and its stand-in engines on real sockets (uvicorn), and a concurrent burst against the app.

What must hold under concurrency: one current answer per question; one decision per plan change; content
edits from the same base version: exactly one wins, the rest are told to reload; background drafts and
reports each written exactly once; nothing half-written."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from eigentlich import seed as seeding
from eigentlich.api import create_app

from .appkit import Engines, app_settings, serve, wait_for
from .conftest import connect


@pytest.fixture(scope="module")
def world(settings, st):
    with st.session() as conn:
        assert seeding.seed(conn, settings.prototype_root)["ok"]
    engines = Engines()
    with serve(engines.lbs.asgi()) as lbs, serve(engines.chatbot.asgi()) as chat, serve(engines.report.asgi()) as rep,             serve(engines.aggregation.asgi()) as agg, serve(engines.lbsim.asgi()) as sim:
        cfg = app_settings(settings, lbs_url=lbs, chatbot_url=chat, report_url=rep, aggregation_url=agg, lbsim_url=sim)
        with serve(create_app(cfg)) as base:
            yield {"base": base, "engines": engines}


def call(base: str, method: str, path: str, json=None) -> httpx.Response:
    with httpx.Client(base_url=base, timeout=60) as c:
        return c.request(method, path, json=json)


def test_the_app_runs_on_a_socket_and_sees_its_engines(world):
    h = call(world["base"], "GET", "/health").json()
    assert h["status"] == "ok" and all(e["reachable"] for e in h["engines"].values())
    assert call(world["base"], "GET", "/").status_code == 200
    assert call(world["base"], "GET", "/app/main.js").headers["content-type"].startswith(("text/javascript", "application/javascript"))


def test_a_concurrent_burst(world, settings):
    base = world["base"]
    ids = [call(base, "POST", "/api/clients", {"display_name": f"Burst {i}", "age_at_registration": 30 + i}).json()["id"]
           for i in range(5)]
    a, b, c, d, e = ids
    q = call(base, "GET", f"/api/clients/{a}/questionnaires/onboarding").json()
    v = q["version"]
    cantons = [o["value"] for o in next(x for x in q["questions"] if x["key"] == "canton")["options"]][:12]

    jobs = []
    jobs += [("PUT", f"/api/clients/{a}/questionnaires/onboarding/answers/canton", {"content_version": v, "value": x})
             for x in cantons]
    jobs += [("POST", f"/api/clients/{b}/positions", {"role": "income", "capital_type": "human", "label": f"Mandat {i}",
                                                      "magnitude": 1000.0 * (i + 1), "magnitude_unit": "chf_per_year"})
             for i in range(10)]
    jobs += [("POST", f"/api/clients/{e}/questionnaires/onboarding/edit",
              {"base_version": v, "question_key": "civil_status", "why": {"en": f"Draft {i}"}}) for i in range(8)]
    jobs += [("POST", f"/api/clients/{who}/threads", {"question": f"Was ist die Säule 3a? ({who[:4]} {i})"})
             for who in (c, d, e) for i in range(3)]
    jobs += [("POST", f"/api/clients/{c}/reports?wait=true", {"kind": "report"}) for _ in range(3)]
    jobs += [("POST", f"/api/clients/{d}/reports", {"kind": "report"})]
    jobs += [("GET", f"/api/clients/{x}/home", None) for x in ids]

    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(lambda j: (j, call(base, *j)), jobs))
    for (method, path, _), r in results:
        assert r.status_code < 500, (method, path, r.status_code, r.text)

    # answers: twelve rows, exactly one current, each naming its version
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM answer WHERE client_id = %s AND question_key = 'canton'", (a,)).fetchall()
    assert len(rows) == 12 and sum(r["superseded_at"] is None for r in rows) == 1 and {r["content_version"] for r in rows} == {v}

    # positions: ten, each under its own decision of the same client, each linked
    with connect(settings) as conn:
        pos = conn.execute("SELECT * FROM position WHERE client_id = %s", (b,)).fetchall()
        decs = conn.execute("SELECT * FROM decision WHERE client_id = %s", (b,)).fetchall()
        links = conn.execute("SELECT count(*) AS n FROM decision_position dp JOIN position p ON p.id = dp.position_id "
                             "WHERE p.client_id = %s", (b,)).fetchone()["n"]
    assert len(pos) == 10 and len(decs) == 10 and links == 10 and len({p["decision_id"] for p in pos}) == 10

    # content edits from one base version: one new version, the rest refused
    edits = [r for (m, p, _), r in results if p.endswith("/edit")]
    assert sorted(r.status_code for r in edits) == [201] + [409] * 7
    history = call(base, "GET", "/api/questionnaires/onboarding/history").json()
    assert history[-1]["version"] == v + 1 and history[-1]["saved_by_ref"] == e

    # threads: every question gets exactly one spark7 draft, in the background
    def all_answered():
        states = []
        for who in (c, d, e):
            threads = call(base, "GET", f"/api/clients/{who}/threads").json()
            states += [t["state"] for t in threads]
        return len(states) == 9 and all(s == "answered" for s in states)
    wait_for(all_answered, timeout=60)
    with connect(settings) as conn:
        per_thread = conn.execute(
            "SELECT t.id, count(*) FILTER (WHERE m.author_kind = 'spark7') AS ai FROM thread t JOIN thread_message m "
            "ON m.thread_id = t.id WHERE t.client_id = ANY(%s) GROUP BY t.id", ([c, d, e],)).fetchall()
    assert len(per_thread) == 9 and all(r["ai"] == 1 for r in per_thread)

    # reports: the waited ones are made, the background one appears
    wait_for(lambda: call(base, "GET", f"/api/clients/{d}/reports").json()[0]["state"] == "fulfilled", timeout=60)
    reqs = call(base, "GET", f"/api/clients/{c}/reports").json()
    assert len(reqs) == 3 and all(r["state"] == "fulfilled" and len(r["reports"]) == 1 for r in reqs)
    with connect(settings) as conn:
        unfinished = conn.execute("SELECT count(*) AS n FROM engine_run WHERE client_id = ANY(%s) "
                                  "AND status NOT IN ('succeeded', 'failed')", (ids,)).fetchone()["n"]
    assert unfinished == 0


def test_an_engine_that_stops_mid_run_is_reported_not_papered_over(world, settings):
    base, engines = world["base"], world["engines"]
    cid = call(base, "POST", "/api/clients", {"display_name": "Ausfall", "age_at_registration": 50}).json()["id"]
    engines.chatbot.refuse = True
    try:
        tid = call(base, "POST", f"/api/clients/{cid}/threads?wait=true", {"question": "Was ist eine Hypothek?"}).json()["thread_id"]
    finally:
        engines.chatbot.refuse = False
    t = call(base, "GET", f"/api/clients/{cid}/threads/{tid}").json()
    assert t["state"] == "awaiting_answer" and t["draft"]["state"] == "failed" and "refused" in t["draft"]["error"]
    assert len(t["messages"]) == 1
