"""The state machines: threads, report requests, approvals; parameter sets, engine runs, curators, clients."""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Jsonb

from eigentlich import store

from .conftest import connect, refused


# -- clients and curators ---------------------------------------------------------------------------

def test_a_client_under_18_is_refused(db):
    with refused(db, psycopg.errors.CheckViolation):
        store.create_client(db, display_name="Jung", age_at_registration=17)


def test_a_curator_created_client_names_the_curator(db, make_curator):
    cur = make_curator()
    c = store.create_client(db, display_name="Neu", age_at_registration=30, created_by_kind="curator",
                            created_by_ref=cur["id"])
    assert c["created_by_ref"] == cur["id"]
    with refused(db, psycopg.errors.CheckViolation):
        store.create_client(db, display_name="Neu", age_at_registration=30, created_by_kind="curator")


def test_the_picker_lists_clients_with_their_open_work(db, make_client):
    c = make_client(display_name="Aaa Picker")
    rows = {r["id"]: r for r in store.list_clients(db)}
    assert rows[c["id"]]["threads_awaiting_answer"] == 0
    store.update_client(db, c["id"], archived_at=db.execute("SELECT now() AS t").fetchone()["t"])
    assert c["id"] not in {r["id"] for r in store.list_clients(db)}
    assert c["id"] in {r["id"] for r in store.list_clients(db, include_archived=True)}


def test_a_revoked_curator_cannot_act_and_stays(st, make_client, make_curator):
    c, cur = make_client(), make_curator()
    with st.session() as conn:
        store.revoke_curator(conn, cur["id"], "Nicht mehr dabei.")
    with pytest.raises(psycopg.errors.RaiseException, match="revoked"):
        with st.session() as conn:
            store.finalise_parameter_set(conn, client_id=c["id"], engine="pcp", contract_version="pcp-mandate@1.0.0",
                                         body={}, finalised_by=cur["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="set once"):
        with st.session() as conn:
            conn.execute("UPDATE curator SET revoked_at = NULL WHERE id = %s", (cur["id"],))
    with st.session() as conn:
        assert cur["id"] in {r["id"] for r in store.list_curators(conn, in_service_only=False)}
        assert cur["id"] not in {r["id"] for r in store.list_curators(conn)}


# -- threads ------------------------------------------------------------------------------------------

def _thread(conn, client_id):
    return store.open_thread(conn, client_id=client_id, opened_by_kind="client", opened_by_ref=client_id)


def test_thread_state_follows_the_last_message(db, make_client, make_curator):
    c, cur = make_client(), make_curator()
    t = _thread(db, c["id"])
    state = lambda: {r["id"]: r["state"] for r in store.list_threads(db, c["id"])}[t["id"]]  # noqa: E731
    assert state() == "awaiting_answer"
    store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Frage?", language="de")
    assert state() == "awaiting_answer"
    store.add_message(db, thread_id=t["id"], author_kind="spark7", author_ref="chatbot", body="Antwort.",
                      language="de", model="spark7", chatbot_artefact_id="CHAT-1")
    assert state() == "answered"
    store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Und?", language="de")
    assert state() == "awaiting_answer"
    store.add_message(db, thread_id=t["id"], author_kind="curator", author_ref=cur["id"], body="So.", language="de")
    assert state() == "answered"
    store.close_thread(db, t["id"], closed_by_kind="client", closed_by_ref=c["id"])
    assert state() == "closed"
    with refused(db, psycopg.errors.RaiseException, match="closed"):
        store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Noch?", language="de")


def test_a_client_writes_only_in_their_own_thread(db, make_client):
    a, b = make_client(), make_client()
    t = _thread(db, a["id"])
    with refused(db, psycopg.errors.RaiseException, match="own thread"):
        store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=b["id"], body="x", language="de")


@pytest.mark.parametrize("model,artefact,kind", [(None, "CHAT-1", "spark7"), ("m", None, "spark7"),
                                                 ("m", "CHAT-1", "curator")])
def test_spark7_messages_carry_their_provenance_and_only_they_do(db, make_client, make_curator, model, artefact, kind):
    c, cur = make_client(), make_curator()
    t = _thread(db, c["id"])
    with refused(db, psycopg.errors.CheckViolation):
        store.add_message(db, thread_id=t["id"], author_kind=kind, author_ref=cur["id"] if kind == "curator" else "bot",
                          body="x", language="de", model=model, chatbot_artefact_id=artefact)


def test_the_curator_answers_a_thread(settings, make_client, make_curator, st):
    c, cur = make_client(), make_curator()
    with st.session() as conn:
        t = _thread(conn, c["id"])
        q = store.add_message(conn, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="?", language="de")
    s = settings.database.schema
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        conn.execute(f"INSERT INTO {s}.thread_message (thread_id, author_kind, author_ref, body, language, in_reply_to_id) "
                     f"VALUES (%s, 'curator', %s, 'Die Antwort.', 'de', %s)", (t["id"], cur["id"], q["id"]))
        state = conn.execute(f"SELECT state FROM {s}.thread_state WHERE id = %s", (t["id"],)).fetchone()["state"]
    assert state == "answered"


# -- report requests ----------------------------------------------------------------------------------

def test_report_request_states(db, make_client):
    c = make_client()
    r = store.request_report(db, client_id=c["id"], kind="update", requested_by_kind="client",
                             requested_by_ref=c["id"], language="de")
    states = lambda: {x["id"]: x["state"] for x in store.report_requests(db, c["id"])}  # noqa: E731
    assert states()[r["id"]] == "open"
    store.add_report(db, request_id=r["id"], client_id=c["id"], report_artefact_id="REP-1", body_html="<p/>")
    assert states()[r["id"]] == "fulfilled"
    with refused(db, psycopg.errors.RaiseException, match="already fulfilled"):
        store.withdraw_report_request(db, r["id"])


def test_a_withdrawn_request_gets_no_report(db, make_client):
    c = make_client()
    r = store.request_report(db, client_id=c["id"], kind="report", requested_by_kind="client",
                             requested_by_ref=c["id"], language="de")
    store.withdraw_report_request(db, r["id"])
    assert {x["id"]: x["state"] for x in store.report_requests(db, c["id"])}[r["id"]] == "withdrawn"
    with refused(db, psycopg.errors.RaiseException, match="withdrawn"):
        store.add_report(db, request_id=r["id"], client_id=c["id"], report_artefact_id="REP-2", body_html="<p/>")


def test_a_report_belongs_to_its_requests_client(db, make_client):
    a, b = make_client(), make_client()
    r = store.request_report(db, client_id=a["id"], kind="report", requested_by_kind="client",
                             requested_by_ref=a["id"], language="de")
    with refused(db, psycopg.errors.RaiseException, match="another client"):
        store.add_report(db, request_id=r["id"], client_id=b["id"], report_artefact_id="REP-3", body_html="<p/>")


# -- approval -------------------------------------------------------------------------------------------

@pytest.fixture()
def reported(st, make_client, make_curator):
    c, cur = make_client(), make_curator()
    with st.session() as conn:
        r = store.request_report(conn, client_id=c["id"], kind="report", requested_by_kind="client",
                                 requested_by_ref=c["id"], language="de")
        rep = store.add_report(conn, request_id=r["id"], client_id=c["id"], report_artefact_id="REP-A",
                               body_html="<p/>")
    return {"client": c["id"], "curator": cur["id"], "request": r["id"], "report": rep["id"]}


def _state(db, request_id):
    return next(a["state"] for a in store.approvals(db) if a["id"] == request_id)


def test_nothing_waits_without_a_request(db, reported):
    assert [a for a in store.approvals(db, client_id=reported["client"])] == []


def test_approve(db, reported):
    ap = store.request_approval(db, client_id=reported["client"], item_kind="report", item_id=reported["report"])
    assert _state(db, ap["id"]) == "awaiting_curator"
    store.approval_event(db, request_id=ap["id"], event="approved", actor_kind="curator", actor_ref=reported["curator"])
    assert _state(db, ap["id"]) == "approved"


def test_every_event_is_terminal(db, reported):
    ap = store.request_approval(db, client_id=reported["client"], item_kind="report", item_id=reported["report"])
    store.approval_event(db, request_id=ap["id"], event="approved", actor_kind="curator", actor_ref=reported["curator"])
    with refused(db, psycopg.errors.UniqueViolation):
        store.approval_event(db, request_id=ap["id"], event="withdrawn", actor_kind="client",
                             actor_ref=reported["client"])


def test_a_revision_is_a_new_report_for_the_same_request(db, reported):
    ap = store.request_approval(db, client_id=reported["client"], item_kind="report", item_id=reported["report"])
    with refused(db, psycopg.errors.RaiseException, match="not a new report"):
        store.approval_event(db, request_id=ap["id"], event="revision_sent", actor_kind="curator",
                             actor_ref=reported["curator"], revision_item_id=reported["report"])
    new = store.add_report(db, request_id=reported["request"], client_id=reported["client"],
                           report_artefact_id="REP-B", body_html="<p>revidiert</p>")
    store.approval_event(db, request_id=ap["id"], event="revision_sent", actor_kind="curator",
                         actor_ref=reported["curator"], revision_item_id=new["id"], note="Abschnitt 3 präzisiert")
    assert _state(db, ap["id"]) == "revised"


def test_only_the_client_withdraws_and_only_a_curator_approves(db, reported, make_client):
    ap = store.request_approval(db, client_id=reported["client"], item_kind="report", item_id=reported["report"])
    other = make_client()
    with refused(db, psycopg.errors.RaiseException, match="only the requesting client"):
        store.approval_event(db, request_id=ap["id"], event="withdrawn", actor_kind="client", actor_ref=other["id"])
    with refused(db, psycopg.errors.CheckViolation):
        store.approval_event(db, request_id=ap["id"], event="approved", actor_kind="client",
                             actor_ref=reported["client"])
    store.approval_event(db, request_id=ap["id"], event="withdrawn", actor_kind="client", actor_ref=reported["client"])
    assert _state(db, ap["id"]) == "withdrawn"


def test_approval_items_must_exist_and_match(db, reported):
    with refused(db, psycopg.errors.RaiseException, match="no update"):
        store.request_approval(db, client_id=reported["client"], item_kind="update", item_id=reported["report"])
    t = _thread(db, reported["client"])
    human = store.add_message(db, thread_id=t["id"], author_kind="curator", author_ref=reported["curator"],
                              body="Von Hand.", language="de")
    with refused(db, psycopg.errors.RaiseException, match="AI-drafted"):
        store.request_approval(db, client_id=reported["client"], item_kind="answer", item_id=human["id"])


def test_an_ai_answer_is_approved_or_revised_in_its_thread(db, reported):
    t = _thread(db, reported["client"])
    ai = store.add_message(db, thread_id=t["id"], author_kind="spark7", author_ref="chatbot", body="Entwurf.",
                           language="de", model="spark7", chatbot_artefact_id="CHAT-9", unverified_numbers=["7258"])
    ap = store.request_approval(db, client_id=reported["client"], item_kind="answer", item_id=ai["id"])
    fix = store.add_message(db, thread_id=t["id"], author_kind="curator", author_ref=reported["curator"],
                            body="Korrigiert.", language="de", in_reply_to_id=ai["id"])
    store.approval_event(db, request_id=ap["id"], event="revision_sent", actor_kind="curator",
                         actor_ref=reported["curator"], revision_item_id=fix["id"])
    assert _state(db, ap["id"]) == "revised"


def test_the_curator_approves_through_the_cockpit(settings, st, reported):
    with st.session() as conn:
        ap = store.request_approval(conn, client_id=reported["client"], item_kind="report", item_id=reported["report"])
    s = settings.database.schema
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        conn.execute(f"INSERT INTO {s}.approval_event (request_id, event, actor_kind, actor_ref, note) "
                     f"VALUES (%s, 'approved', 'curator', %s, 'Geprüft.')", (ap["id"], reported["curator"]))
        state = conn.execute(f"SELECT state FROM {s}.approval_state WHERE id = %s", (ap["id"],)).fetchone()["state"]
    assert state == "approved"


# -- parameter sets -------------------------------------------------------------------------------------

def test_parameter_sets_form_a_chain_with_one_current(db, make_client, make_curator):
    c, cur = make_client(), make_curator()
    first = store.finalise_parameter_set(db, client_id=c["id"], engine="pcp", contract_version="pcp-mandate@1.0.0",
                                         body={"max_single_position": 0.15}, finalised_by=cur["id"])
    second = store.finalise_parameter_set(db, client_id=c["id"], engine="pcp", contract_version="pcp-mandate@1.0.0",
                                          body={"max_single_position": 0.1}, finalised_by=cur["id"])
    assert second["supersedes_id"] == first["id"]
    assert store.current_parameter_set(db, c["id"], "pcp")["id"] == second["id"]
    lbs = store.finalise_parameter_set(db, client_id=c["id"], engine="lbs", contract_version="lbs-input@1.0.0",
                                       body={}, finalised_by=cur["id"])
    assert lbs["supersedes_id"] is None


def test_a_second_root_or_a_fork_is_refused(db, make_client, make_curator):
    c, cur = make_client(), make_curator()
    first = store.finalise_parameter_set(db, client_id=c["id"], engine="pcp", contract_version="pcp-mandate@1.0.0",
                                         body={}, finalised_by=cur["id"])
    insert = ("INSERT INTO parameter_set (client_id, engine, contract_version, body, finalised_by, supersedes_id) "
              "VALUES (%s, 'pcp', 'pcp-mandate@1.0.0', '{}', %s, %s)")
    with refused(db, psycopg.errors.UniqueViolation):
        db.execute(insert, (c["id"], cur["id"], None))
    db.execute(insert, (c["id"], cur["id"], first["id"]))
    with refused(db, psycopg.errors.UniqueViolation):
        db.execute(insert, (c["id"], cur["id"], first["id"]))


def test_the_curator_finalises_a_parameter_set(settings, make_client, make_curator):
    c, cur = make_client(), make_curator()
    s = settings.database.schema
    with connect(settings, as_curator=True, autocommit=True, search_path=False) as conn:
        conn.execute(f"INSERT INTO {s}.parameter_set (client_id, engine, contract_version, body, finalised_by, "
                     f"supersedes_id, note) SELECT %s, 'pcp', 'pcp-mandate@1.0.0', %s, %s, "
                     f"(SELECT id FROM {s}.parameter_set_current WHERE client_id = %s AND engine = 'pcp'), 'erste'",
                     (c["id"], Jsonb({"max_single_position": 0.15}), cur["id"], c["id"]))
        n = conn.execute(f"SELECT count(*) AS n FROM {s}.parameter_set_current WHERE client_id = %s",
                         (c["id"],)).fetchone()["n"]
    assert n == 1


# -- engine runs ----------------------------------------------------------------------------------------

def test_engine_runs_move_forward_only(db, make_client):
    c = make_client()
    run = store.start_engine_run(db, client_id=c["id"], engine="lbs", request={"x": 1}, requested_by_kind="system",
                                 requested_by_ref="backend")
    store.mark_engine_run_running(db, run["id"], run_id="RUN-1")
    done = store.finish_engine_run(db, run["id"], status="succeeded", artefact_id="LBS-1")
    assert done["status"] == "succeeded"
    with refused(db, psycopg.errors.RaiseException, match="immutable"):
        store.finish_engine_run(db, run["id"], status="failed", error="later")


def test_an_engine_run_cannot_go_back_or_change_its_request(db, make_client):
    c = make_client()
    run = store.start_engine_run(db, client_id=c["id"], engine="lbs", request={"x": 1}, requested_by_kind="system",
                                 requested_by_ref="backend")
    store.mark_engine_run_running(db, run["id"])
    with refused(db, psycopg.errors.RaiseException, match="not a permitted transition"):
        db.execute("UPDATE engine_run SET status = 'queued' WHERE id = %s", (run["id"],))
    with refused(db, psycopg.errors.RaiseException, match="outcome columns"):
        db.execute("UPDATE engine_run SET request = '{}' WHERE id = %s", (run["id"],))


def test_a_failed_run_says_why(db, make_client):
    c = make_client()
    run = store.start_engine_run(db, client_id=c["id"], engine="pcp", request={}, requested_by_kind="system",
                                 requested_by_ref="backend")
    with refused(db, psycopg.errors.CheckViolation):
        store.finish_engine_run(db, run["id"], status="failed")
