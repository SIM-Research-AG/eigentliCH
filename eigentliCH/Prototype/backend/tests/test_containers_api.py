"""S-04 over HTTP: naming a goal, and — from 31 August 2026 — changing one.

**Why this file exists.** The owner tested the application and reported: *"If I have a Ziel, I can not
change it afterwards."* Verified before anything was built: `/api/goals` carried `GET` and `POST` and
nothing else, and `services/goals.py` contained no function that wrote to a `Goal`. It was not a bug in a
form; the operation did not exist.

**What is checked here rather than in `test_goals.py`.** The service tests hold the semantics — what a
revision does to the record, and why. These hold the things that are only true if the *edge* is right: that
the route exists at all, that a partial body means "leave the rest alone" rather than "clear the rest",
that another member's goal is a 404 and not a 403, and that the request carries its own Decision.

The distinction matters for the second one especially. `exclude_unset` is the mechanism, and a request
model with defaults instead would make an untouched field and a cleared field the same request — a member
who changed the name would lose the target date they never touched.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from eigentlich.models import Decision, Goal, Position
from eigentlich.services import mutate_plan
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides

PASSWORD = "ein ziemlich langes passwort"


@pytest.fixture()
def app(api_session, tmp_path, monkeypatch, fast_kdf):
    """The real application on the fixture database — the same reasoning as `test_api_auth.py::app`.

    Not a hand-assembled sub-app: the route under test is on `main.app`, and a sub-app would let a
    forgotten `include_router` escape every assertion below.
    """
    from eigentlich.api import main, remainder
    from eigentlich.services import VaultStore

    store = VaultStore(tmp_path / "vault")
    monkeypatch.setattr(main, "VAULT_STORE", store)

    overrides = session_overrides(api_session)
    overrides[remainder.get_store] = lambda: store
    main.app.dependency_overrides.update(overrides)
    try:
        yield main.app
    finally:
        for key in overrides:
            main.app.dependency_overrides.pop(key, None)


def _member(session, *, email, name):
    member, _ = register_with_credentials(
        session, email=email, password=PASSWORD, age_at_registration=44, display_name=name
    )
    session.commit()
    return member


@pytest.fixture()
def client(app, api_session):
    member = _member(api_session, email="goals@example.ch", name="Ziel-Mitglied")
    _, token = login(api_session, email="goals@example.ch", password=PASSWORD)
    api_session.commit()
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client, member


@pytest.fixture()
def a_goal(api_session, client):
    """One goal with a name, a date, an amount and a funding position, named through the API.

    Created over HTTP rather than in the ORM, so the fixture also exercises the route that was already
    there — and so the Decision the revision has to correct is a real one written the way a member writes
    it.
    """
    test_client, member = client
    with mutate_plan(
        api_session, member_id=member.id, question="Position?", choice="Ja"
    ) as decision:
        position = Position(
            member_id=member.id, role="growth", capital_type="financial", label="Depot"
        )
        api_session.add(position)
        decision.linked_positions.append(position)
    api_session.commit()

    created = test_client.post("/api/goals", json={
        "name": "Wohneigentum",
        "template": "home_ownership",
        "target_amount": 250000,
        "target_date": "2031-06-01",
        "safety": "eher hoch",
        "funded_by_position_ids": [position.id],
        "question": "Wohneigentum als Ziel erfassen?",
        "choice": "Ja.",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"], position, member


# ============================================================ the operation exists


def test_a_goal_can_be_changed_over_http(client, api_session, a_goal):
    """The whole of the owner's report, answered.

    **Planted violation:** renamed the route so `PUT /api/goals/{goal_id}` was gone — the state the
    application was actually in. Failed with 405. Restored.
    """
    test_client, _ = client
    goal_id, _position, _member = a_goal

    response = test_client.put(f"/api/goals/{goal_id}", json={
        "target_date": "2035-06-01",
        "question": "Zieldatum verschieben?",
        "choice": "Ja, vier Jahre später.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] == ["target_date"]

    api_session.expire_all()
    assert api_session.get(Goal, goal_id).target_date == date(2035, 6, 1)


def test_a_partial_body_leaves_everything_else_alone(client, api_session, a_goal):
    """The reason `GoalRevisionRequest` reads `model_fields_set` instead of taking defaults.

    A member who changes the name has not asked for their target amount to be forgotten. With defaults on
    the model, every absent field would arrive as `None` and this would wipe four values.

    **Planted violation:** replaced `model_dump(exclude_unset=True)` with `model_dump()`. The date, the
    amount, the template and the parameter were all cleared and this failed on the first of them.
    Restored.
    """
    test_client, _ = client
    goal_id, _position, _member = a_goal

    response = test_client.put(f"/api/goals/{goal_id}", json={
        "name": "Wohneigentum in Chur",
        "question": "Umbenennen?", "choice": "Ja.",
    })
    assert response.status_code == 200, response.text

    api_session.expire_all()
    goal = api_session.get(Goal, goal_id)
    assert goal.name == "Wohneigentum in Chur"
    assert goal.target_date == date(2031, 6, 1), "an untouched field was cleared"
    assert goal.target_amount == 250000
    assert goal.template == "home_ownership"
    assert goal.safety == "eher hoch"
    assert len(goal.funded_by) == 1, "the funding was dropped by a request that never mentioned it"


def test_a_stated_null_clears_the_field(client, api_session, a_goal):
    """The other half of the same mechanism: `null` is a value here, so a target date CAN be removed.

    R-020 and R-030 make a goal without a date or an amount a real goal, so "I no longer have a date for
    this" has to be expressible. If it were not, the only way to remove one would be to name a second goal.
    """
    test_client, _ = client
    goal_id, _position, _member = a_goal

    response = test_client.put(f"/api/goals/{goal_id}", json={
        "target_date": None, "target_amount": None,
        "question": "Datum und Betrag entfernen?", "choice": "Ja, beides ist offen.",
    })
    assert response.status_code == 200, response.text

    api_session.expire_all()
    goal = api_session.get(Goal, goal_id)
    assert goal.target_date is None
    assert goal.target_amount is None


def test_the_funding_can_be_replaced_over_http(client, api_session, a_goal):
    test_client, _ = client
    goal_id, _position, _member = a_goal

    response = test_client.put(f"/api/goals/{goal_id}", json={
        "funded_by_position_ids": [],
        "question": "Deckung lösen?", "choice": "Ja.",
    })
    assert response.status_code == 200, response.text
    assert "funded_by" in response.json()["changed"]

    api_session.expire_all()
    assert api_session.get(Goal, goal_id).funded_by == []


# ============================================================ C-09 and R-040 at the edge


def test_the_revision_writes_one_decision_that_corrects_the_prior_one(client, api_session, a_goal):
    """C-09 and R-040 together, over HTTP.

    The response names the corrected Decision, so a client can show "this corrects an earlier record"
    rather than having to know that it does.
    """
    test_client, _ = client
    goal_id, _position, _member = a_goal

    before = api_session.execute(select(Decision)).scalars().all()
    response = test_client.put(f"/api/goals/{goal_id}", json={
        "name": "Wohneigentum, kleiner",
        "question": "Anpassen?", "choice": "Ja.", "reasoning": "Die Preise sind gestiegen.",
    })
    assert response.status_code == 200, response.text
    body = response.json()

    after = api_session.execute(select(Decision)).scalars().all()
    assert len(after) == len(before) + 1, "a plan change without exactly one Decision"

    decision = api_session.get(Decision, body["decision_id"])
    assert decision.corrects_id == body["corrects_decision_id"]
    assert decision.corrects_id is not None, "R-040: the correction references nothing"
    assert decision.reasoning == "Die Preise sind gestiegen."
    assert [goal.id for goal in decision.linked_goals] == [goal_id]


def test_a_revision_without_the_decision_fields_is_refused(client, a_goal):
    """C-09 is not optional at the edge either. The member states what they decided; the server does not
    compose that sentence for them, and a 422 here is the request model refusing to make one up."""
    test_client, _ = client
    goal_id, _position, _member = a_goal
    response = test_client.put(f"/api/goals/{goal_id}", json={"name": "Ohne Entscheid"})
    assert response.status_code == 422, response.text


def test_a_revision_that_changes_nothing_is_refused(client, api_session, a_goal):
    """422 rather than 204. A Decision saying a change was made when none was is permanent (R-040), so
    answering "done" to a no-op would either write a false record or imply one."""
    test_client, _ = client
    goal_id, _position, _member = a_goal
    before = len(api_session.execute(select(Decision)).scalars().all())

    response = test_client.put(f"/api/goals/{goal_id}", json={
        "name": "Wohneigentum",
        "question": "Nichts ändern?", "choice": "Nichts.",
    })
    assert response.status_code == 422, response.text
    assert len(api_session.execute(select(Decision)).scalars().all()) == before


# ============================================================ A11 at this route


def test_another_members_goal_is_a_404(app, api_session, client):
    """A81's rule, at a route addressed by an id: a wrong address and someone else's goal are one refusal.

    404 and not 403, on the same reasoning that makes a wrong password and an unknown address
    indistinguishable — a 403 would confirm that the goal exists and belongs to somebody.

    **Planted violation:** removed the ownership half of the lookup in `revise_goal`. The stranger's goal
    was renamed through this route and the test failed on the 200. Restored.
    """
    test_client, _mine = client
    stranger = _member(api_session, email="stranger@example.ch", name="Fremd")
    with mutate_plan(
        api_session, member_id=stranger.id, question="Ziel?", choice="Ja"
    ) as decision:
        theirs = Goal(member_id=stranger.id, name="Nicht Ihres")
        api_session.add(theirs)
        decision.linked_goals.append(theirs)
    api_session.commit()

    response = test_client.put(f"/api/goals/{theirs.id}", json={
        "name": "Jetzt meines", "question": "Umbenennen?", "choice": "Ja.",
    })
    assert response.status_code == 404, response.text
    api_session.expire_all()
    assert api_session.get(Goal, theirs.id).name == "Nicht Ihres"


def test_an_unknown_template_is_refused_with_the_list(client, a_goal):
    """A key nothing resolves renders as no template while looking like one in the database, so the route
    refuses it and says what it would have accepted."""
    test_client, _ = client
    goal_id, _position, _member = a_goal
    response = test_client.put(f"/api/goals/{goal_id}", json={
        "template": "frugal_maximalism", "question": "Vorlage?", "choice": "Ja.",
    })
    assert response.status_code == 422, response.text
    assert "early_retirement" in response.text


def test_a_bad_target_date_is_a_422_and_not_a_500(client, a_goal):
    test_client, _ = client
    goal_id, _position, _member = a_goal
    response = test_client.put(f"/api/goals/{goal_id}", json={
        "target_date": "1. Juni 2035", "question": "Verschieben?", "choice": "Ja.",
    })
    assert response.status_code == 422, response.text


# ============================================================ the templates, over the wire


def test_the_goal_list_offers_every_template_with_early_retirement_first(client, a_goal):
    """The owner asked for Frühpensionierung and asked for it first, and the client renders the payload's
    order — so the ordering is only real if it survives to here."""
    test_client, _ = client
    payload = test_client.get("/api/goals").json()
    names = [record["de"]["name"] for record in payload["templates"]]
    assert names[0] == "Frühpensionierung", f"the templates arrive in another order: {names}"
    assert len(names) >= 9, f"the template list has shrunk: {names}"
    assert payload["goals_may_be_revised"] is True


def test_german_names_survive_the_json_round_trip(client, a_goal):
    """A German product has to keep German text intact over HTTP as well as in the store — `Frühpensionierung`
    and `Finanzielle Unabhängigkeit` both carry umlauts, and an encoding mistake in the response would show
    up as mojibake on the one screen this change exists for."""
    test_client, _ = client
    payload = test_client.get("/api/goal-templates").json()
    names = {record["de"]["name"] for record in payload["templates"]}
    assert "Frühpensionierung" in names
    assert "Finanzielle Unabhängigkeit" in names
    assert "Weiterbildung oder Umschulung" in names
