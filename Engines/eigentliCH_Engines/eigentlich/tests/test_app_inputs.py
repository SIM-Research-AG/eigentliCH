"""The lbs-request@1.0.0 built from the store (inputs.py), and the repository fix it depends on."""

from __future__ import annotations

from datetime import date

from eigentlich import inputs, store
from eigentlich.store import Decision

from .conftest import TODAY


def test_a_message_body_is_stored_as_text(db, make_client):
    """Regression (EIG-37): ``body`` was adapted as JSON for every table, so a message was stored quoted."""
    c = make_client()
    t = store.open_thread(db, client_id=c["id"], opened_by_kind="client", opened_by_ref=c["id"])
    m = store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body='Säule "3a"?', language="de")
    assert m["body"] == 'Säule "3a"?'
    assert db.execute("SELECT body FROM thread_message WHERE id = %s", (m["id"],)).fetchone()["body"] == 'Säule "3a"?'


def test_the_request_from_a_plan(db, make_client, questionnaire):
    c = make_client(display_name="Nicht Im Request", age_at_registration=44)
    partner = make_client(display_name="Partnerin")
    key, v = questionnaire()
    with store.plan_change(db, decision=Decision(client_id=c["id"], author="client", question="Plan?", choice="So")) as ch:
        hh = ch.insert("household", composition_as_of=TODAY, stated_by="client")
        me = ch.insert("household_member", household_id=hh["id"], client_id=c["id"], label="ich", kind="adult")
        ch.insert("household_member", household_id=hh["id"], client_id=partner["id"], label="Zoe", kind="adult")
        ch.insert("household_member", household_id=hh["id"], label="Kind", kind="dependant")
        pk = ch.insert("position", client_id=c["id"], role="stabilisation", capital_type="financial", label="PK-Guthaben",
                       magnitude=120000.0, magnitude_unit="chf", stock_kind="asset", liquidity="illiquid")
        free = ch.insert("position", client_id=c["id"], role="growth", capital_type="financial", label="Depot",
                         magnitude=80000.0, magnitude_unit="chf", stock_kind="asset", tags={"vessel": "free"})
        wage = ch.insert("position", client_id=c["id"], role="income", capital_type="human", label="Lohn",
                         magnitude=100000.0, magnitude_unit="chf_per_year")
        home = ch.insert("goal", client_id=c["id"], name="Eigenheim am See", target_amount=900000.0,
                         target_date=date(2032, 1, 1))
        ch.insert("goal", client_id=c["id"], name="Rente ab 60", target_amount=60000.0, target_date=date(2042, 1, 1))
        gone = ch.insert("goal", client_id=c["id"], name="Boot", active=False)
        ch.set_goal_funding(home["id"], free["id"])
        ch.set_goal_owner(home["id"], me["id"])
        ch.state_fact(client_id=c["id"], stated_key="canton", stated_value="Zug", stated_on=TODAY, stated_by="client", data_class=1)
    for qkey, value in (("income", 101000), ("health", 0.85)):
        store.put_answer(db, client_id=c["id"], questionnaire_key=key, content_version=v, question_key=qkey, value=value,
                         answered_by_kind="client", answered_by_ref=c["id"])
    g = inputs.gather(db, c["id"])
    g.answers[inputs.INTAKE] = {"canton": "Bern", "max_loss_pct": 250, "esg_exclusions": "Waffen, Tabak\nKohle",
                                "income_gross": "95'000", "crisis_behaviour": "nachgekauft"}
    request, dropped = inputs.build(g, TODAY)

    assert request.client_ref == c["id"] and "Nicht Im Request" not in request.model_dump_json()
    persons = request.household.persons
    assert [(p.person_id, p.kind) for p in persons] == [("p1", "adult"), ("p2", "adult"), ("p3", "dependant")]
    assert persons[0].age == 44 and persons[0].stated_gross_income == 95000.0 and request.household.principal == "p1"
    by_id = {p.position_id: p for p in request.positions}
    assert by_id[pk["id"]].vessel == "pillar_2" and by_id[free["id"]].vessel == "free" and by_id[free["id"]].role == "gain"
    assert by_id[wage["id"]].vessel is None and by_id[free["id"]].funds_goals == (home["id"],)
    assert all(p.owner == "p1" for p in request.positions)
    kinds = {x.goal_id: x.kind for x in request.goals}
    assert kinds[home["id"]] == "property" and gone["id"] not in kinds and sorted(kinds.values()) == ["property", "retirement"]
    assert next(x for x in request.goals if x.goal_id == home["id"]).owners == ("p1",)
    assert request.facts.canton == "Zug"                                      # the stated fact wins over the answer
    assert request.risk.stated_loss is None and any("max_loss_pct" in d for d in dropped)
    assert request.risk.esg_exclusions == ("Waffen", "Tabak", "Kohle") and request.risk.crisis_behaviour == "nachgekauft"
    assert request.mandate.goal_id == home["id"] and request.mandate.annual_contribution is None


def test_no_household_is_no_household(db, make_client):
    c = make_client()
    with store.plan_change(db, decision=Decision(client_id=c["id"], author="client", question="?", choice="!")) as ch:
        ch.insert("position", client_id=c["id"], role="income", capital_type="human", label="Lohn")
    request, _ = inputs.build(inputs.gather(db, c["id"]), TODAY)
    assert request.household is None and request.positions[0].owner is None and request.mandate is None


def test_the_prototypes_rules():
    assert inputs.vessel_of({"label": "Säule 3a Konto", "capital_type": "financial", "magnitude_unit": "chf"}) == "pillar_3a"
    assert inputs.vessel_of({"label": "Kunstsammlung", "capital_type": "financial", "magnitude_unit": "chf"}) == "real_asset"
    assert inputs.vessel_of({"label": "3a", "capital_type": "financial", "magnitude_unit": "chf_per_year"}) is None
    assert inputs.goal_kind({"name": "Ferien", "template": "holiday_property"}) == "property"
    assert inputs.goal_kind({"name": "Ausgaben ab 65"}) == "retirement"
    assert inputs.goal_kind({"name": "Weltreise", "occupancy": None}) == "other"


def test_the_yearly_contribution_reaches_the_mandate(db, make_client):
    """EIG-45: the onboarding's annual_contribution is mandate.annual_contribution (a stated 0 is 0); without a
    mandate goal it is named in dropped; the aligned intake's esg_exclusions list is sent as it is (EIG-44)."""
    c = make_client()
    with store.plan_change(db, decision=Decision(client_id=c["id"], author="client", question="?", choice="!")) as ch:
        goal = ch.insert("goal", client_id=c["id"], name="Weltreise", target_amount=40000.0, target_date=date(2030, 6, 1))
    g = inputs.gather(db, c["id"])
    for stated, sent in ((24000, 24000.0), (0, 0.0), ("18'000", 18000.0)):
        g.answers[inputs.ONBOARDING] = {"annual_contribution": stated}
        g.answers[inputs.INTAKE] = {"esg_exclusions": ["Waffen", "Tabak"]}
        request, dropped = inputs.build(g, TODAY)
        assert request.mandate.goal_id == goal["id"] and request.mandate.annual_contribution == sent, stated
        assert request.risk.esg_exclusions == ("Waffen", "Tabak") and dropped == []
    g.answers[inputs.ONBOARDING] = {"annual_contribution": -5}
    request, dropped = inputs.build(g, TODAY)
    assert request.mandate.annual_contribution is None and any("annual_contribution" in d for d in dropped)
    g.goals = []
    g.answers[inputs.ONBOARDING] = {"annual_contribution": 12000}
    request, dropped = inputs.build(g, TODAY)
    assert request.mandate is None and any(d.startswith("annual_contribution: 12000") for d in dropped)


def test_only_an_ai_answer_carries_a_basis(db, make_client):
    """EIG-50 (additive column): ``thread_message.basis`` is grounded, general or mixed, and only on spark7's
    (MiniMind's) messages."""
    import psycopg
    from .conftest import refused
    c = make_client()
    t = store.open_thread(db, client_id=c["id"], opened_by_kind="client", opened_by_ref=c["id"])
    q = store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Frage?", language="de")
    with refused(db, psycopg.errors.CheckViolation):
        store.add_message(db, thread_id=t["id"], author_kind="client", author_ref=c["id"], body="Nochmals", language="de",
                          basis="general")
    with refused(db, psycopg.errors.CheckViolation):
        store.add_message(db, thread_id=t["id"], author_kind="spark7", author_ref="chatbot", body="A", language="de",
                          model="m", chatbot_artefact_id="CHAT-1", basis="guessed")
    ai = store.add_message(db, thread_id=t["id"], author_kind="spark7", author_ref="chatbot", body="Antwort", language="de",
                           model="m", chatbot_artefact_id="CHAT-1", basis="general", in_reply_to_id=q["id"])
    assert ai["basis"] == "general" and q["basis"] is None
