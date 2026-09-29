"""One row of every table for one client, written through the store the way the backend writes them."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from eigentlich import store
from eigentlich.store import Decision, Store

from .conftest import TODAY, minimal_questionnaire


def build(st: Store, tag: str = "w") -> dict[str, Any]:
    w: dict[str, Any] = {}
    with st.session() as conn:
        cur = store.create_curator(conn, display_name=f"Kuratorin {tag}")
        client = store.create_client(conn, display_name=f"Client {tag}", age_at_registration=45)
        partner = store.create_client(conn, display_name=f"Partner {tag}", age_at_registration=44)
        w.update(curator=cur["id"], client=client["id"], partner=partner["id"])
        w["consent"] = store.grant_consent(conn, client_id=client["id"], purpose="datenbearbeitung",
                                           document_version="dsg@2026-01")["id"]
        key = f"questionnaire/world-{tag}"
        w["questionnaire"] = key
        w["q_version"] = store.save_content(conn, key=key, kind="questionnaire", body=minimal_questionnaire(),
                                            saved_by_kind="seed", saved_by_ref="tests")
        w["answer"] = store.put_answer(conn, client_id=client["id"], questionnaire_key=key,
                                       content_version=w["q_version"], question_key="canton", value="Bern",
                                       answered_by_kind="client", answered_by_ref=client["id"])["id"]
        w["submission"] = conn.execute(
            "INSERT INTO submission (client_id, schema_version, source, received_at, payload, content_hash) "
            "VALUES (%s, 'intake@1.1', 'intake.html', now(), %s, %s) RETURNING id",
            (client["id"], Jsonb({"raw": {"canton": "Bern"}}), "0" * 64)).fetchone()["id"]
        w["session"] = conn.execute("INSERT INTO curator_session (client_id, curator_id, opened_from) "
                                    "VALUES (%s, %s, 'cockpit') RETURNING id", (client["id"], cur["id"])).fetchone()["id"]
        w["session_event"] = conn.execute("INSERT INTO curator_session_event (session_id, kind, actor) "
                                          "VALUES (%s, 'opened', %s) RETURNING id", (w["session"], cur["id"])).fetchone()["id"]

        with store.plan_change(conn, decision=Decision(client_id=client["id"], author="client",
                                                       question="Haushalt und erste Positionen?", choice="So")) as ch:
            hh = ch.insert("household", composition_as_of=TODAY, stated_by="client")
            me = ch.insert("household_member", household_id=hh["id"], client_id=client["id"], label="ich", kind="adult")
            ch.insert("household_member", household_id=hh["id"], client_id=partner["id"], label="Partner", kind="adult")
            pos = ch.insert("position", client_id=client["id"], role="stabilisation", capital_type="financial",
                            label="Konto", magnitude=20000.0, magnitude_unit="chf", stock_kind="asset",
                            liquidity="immediate")
            goal = ch.insert("goal", client_id=client["id"], name="Wohneigentum", target_amount=150000.0)
            fact = ch.state_fact(client_id=client["id"], stated_key="canton", stated_value="Bern", stated_on=TODAY,
                                 stated_by="client", data_class=1)
            ch.set_goal_funding(goal["id"], pos["id"])
            ch.set_goal_owner(goal["id"], me["id"])
            w.update(decision=ch.decision_id, household=hh["id"], household_member=me["id"], position=pos["id"],
                     goal=goal["id"], fact=fact["id"])

        thread = store.open_thread(conn, client_id=client["id"], opened_by_kind="client", opened_by_ref=client["id"],
                                   subject="Säule 3a")
        q = store.add_message(conn, thread_id=thread["id"], author_kind="client", author_ref=client["id"],
                              body="Wie viel darf ich einzahlen?", language="de")
        ai = store.add_message(conn, thread_id=thread["id"], author_kind="spark7", author_ref="chatbot",
                               body="Das hängt davon ab ...", language="de", model="spark7-test",
                               chatbot_artefact_id="CHAT-0001", sources=[{"key": "knowledge/saeule-3a-grundlagen"}],
                               unverified_numbers=["7258"], in_reply_to_id=q["id"])
        w.update(thread=thread["id"], message=q["id"], ai_message=ai["id"])

        req = store.request_report(conn, client_id=client["id"], kind="report", requested_by_kind="client",
                                   requested_by_ref=client["id"], language="de")
        rep = store.add_report(conn, request_id=req["id"], client_id=client["id"], report_artefact_id="REP-0001",
                               body_html="<p>Bericht</p>", lbs_artefact_id="LBS-0001")
        w.update(report_request=req["id"], report=rep["id"])
        ap = store.request_approval(conn, client_id=client["id"], item_kind="report", item_id=rep["id"])
        ev = store.approval_event(conn, request_id=ap["id"], event="approved", actor_kind="curator", actor_ref=cur["id"])
        w.update(approval_request=ap["id"], approval_event=ev["id"])

        ps = store.finalise_parameter_set(conn, client_id=client["id"], engine="pcp", contract_version="pcp-mandate@1.0.0",
                                          body={"max_single_position": 0.15}, finalised_by=cur["id"])
        run = store.start_engine_run(conn, client_id=client["id"], engine="pcp", request={"mandate": "x"},
                                     requested_by_kind="curator", requested_by_ref=cur["id"], parameter_set_id=ps["id"])
        w.update(parameter_set=ps["id"], engine_run=run["id"])
        w["migration_run"] = conn.execute(
            "INSERT INTO migration_run (source_path, source_sha256, alembic_head, reconciliation) "
            "VALUES ('test', %s, 'test', '{}') RETURNING id", ("0" * 64,)).fetchone()["id"]
    return w
