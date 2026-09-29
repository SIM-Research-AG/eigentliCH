"""Text that is UTF-8 read as a code page (EIG-46): found, reversed, and corrected by each table's rule."""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich import encoding, store
from eigentlich.settings import load
from eigentlich.store import Decision, Store


@pytest.mark.parametrize("garbled, right", [
    ("C├⌐line B.", "Céline B."),            # CP437, the migrated name
    ("ElsbethH├╝rlimann", "ElsbethHürlimann"),
    ("SimonN├ñf", "SimonNäf"),
    ("C├®line", "Céline"),                  # CP850
    ("CÃ©line", "Céline"),                  # CP1252
    ("MÃ¼ller und ZÃ¼rich", "Müller und Zürich"),
    ("Grüsse, C├⌐line", "Grüsse, Céline"),   # a correct umlaut beside a garbled one
])
def test_the_pattern_is_found_and_reversed(garbled, right):
    assert encoding.misdecoded(garbled)
    assert encoding.repair(garbled) == right
    assert not encoding.misdecoded(right)


@pytest.mark.parametrize("text", ["Céline B.", "Müller", "Zürich – Genf", "Glücksspiel", "70 % — ich kann nachjustieren",
                                  "Frühpensionierung", "Ærø", "5–10", "", "plain"])
def test_correct_text_is_never_touched(text):
    assert not encoding.misdecoded(text) and encoding.repair(text) == text


def test_the_fix_follows_each_tables_rule(st):
    with st.session() as conn:
        c = store.create_client(conn, display_name="C├⌐line B.", age_at_registration=40)
        other = store.create_client(conn, display_name="Partner", age_at_registration=41)
        with store.plan_change(conn, decision=Decision(client_id=c["id"], author="client", question="Haushalt?",
                                                       choice="Ja", reasoning="Aus der Aufnahme vom C├⌐lineBornand")) as ch:
            hh = ch.insert("household", composition_as_of=date(2026, 9, 1), stated_by="client")
            member = ch.insert("household_member", household_id=hh["id"], client_id=c["id"], label="C├⌐line B.",
                               kind="adult")
            ch.insert("household_member", household_id=hh["id"], client_id=other["id"], label="Partner", kind="adult")
            pos = ch.insert("position", client_id=c["id"], role="income", capital_type="human", label="Anstellung Z├╝rich")
            goal = ch.insert("goal", client_id=c["id"], name="Wohnung")
            fact = ch.state_fact(client_id=c["id"], stated_key="education", stated_value="Universit├ñt",
                                 stated_on=date(2026, 9, 1), stated_by="client")
            original_decision = ch.decision_id
        t = store.open_thread(conn, client_id=c["id"], opened_by_kind="client", opened_by_ref=c["id"], subject="Fr├╝h")
        store.add_message(conn, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Gr├╝ezi",
                          language="de")
    with st.session() as conn:
        found = {(h["table"], h["column"]) for h in encoding.scan(conn)}
    assert found >= {("client", "display_name"), ("household_member", "label"), ("position", "label"),
                     ("client_fact", "stated_value"), ("decision", "reasoning"), ("thread", "subject"),
                     ("thread_message", "body")}

    with st.session() as conn:
        result = encoding.fix(conn, today=date(2026, 9, 29))
    with st.session() as conn:
        assert store.get_client(conn, c["id"])["display_name"] == "Céline B."
        m = conn.execute("SELECT * FROM household_member WHERE id = %s", (member["id"],)).fetchone()
        assert m["label"] == "Céline B."
        d = conn.execute("SELECT * FROM decision WHERE id = %s", (m["decision_id"],)).fetchone()
        assert d["question"] == encoding.DECISION_QUESTION == "encoding correction, owner 29.09.2026"
        assert d["client_id"] == c["id"] and d["author"] == "system" and not encoding.misdecoded(d["choice"])
        assert conn.execute("SELECT label, decision_id FROM position WHERE id = %s", (pos["id"],)).fetchone() == \
            {"label": "Anstellung Zürich", "decision_id": d["id"]}
        assert conn.execute("SELECT decision_id FROM goal WHERE id = %s", (goal["id"],)).fetchone()["decision_id"] \
            == original_decision                                           # untouched
        facts = conn.execute("SELECT * FROM client_fact WHERE client_id = %s AND stated_key = 'education' ORDER BY "
                             "created_at, id", (c["id"],)).fetchall()
        assert [f["stated_value"] for f in facts] == ["Universit├ñt", "Universität"]
        assert facts[0]["id"] == fact["id"] and facts[0]["superseded_on"] == date(2026, 9, 29)
        correction = conn.execute("SELECT * FROM decision WHERE corrects_id = %s", (original_decision,)).fetchone()
        assert correction["reasoning"] == "Aus der Aufnahme vom CélineBornand" and correction["choice"] == "Ja"
        assert conn.execute("SELECT subject FROM thread WHERE id = %s", (t["id"],)).fetchone()["subject"] == "Früh"
        body = conn.execute("SELECT body FROM thread_message WHERE thread_id = %s", (t["id"],)).fetchone()["body"]
        assert body == "Gr├╝ezi"                                          # append-only: listed, not changed
    assert [(h["table"], h["why"]) for h in result["left"]] == [("thread_message", "thread_message is append-only")]
    assert [(h["table"], h["column"]) for h in result["remaining"]] == [("thread_message", "body")]
    with st.session() as conn:
        again = encoding.fix(conn)
    assert again["changed"] == [] and len(again["left"]) == 1


def test_the_real_store_holds_no_misdecoded_text():
    """The owner's correction of 29.09.2026 holds: nothing in the real store's migrated text fields reads
    like UTF-8 taken for a code page, except what an append-only table keeps (none on that day)."""
    with Store(load().database).session() as conn:
        hits = encoding.scan(conn)
    assert [(h["table"], h["id"], h["column"]) for h in hits] == []
