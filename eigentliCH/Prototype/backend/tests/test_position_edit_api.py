"""R-122 and the second half of R-123: editing a position, and marking one inactive.

**What was missing.** `Position.active` is honoured on six read paths — `services/grid.py` flags it,
`services/befund.py` has a whole sentence for a cell holding only inactive material, `illustration.py`
and `engine_inputs.py` skip it, `derive.py` filters on it, `goals.py` excludes it from a goal's funding —
and it was rendered by the client. **And nothing anywhere set it to `False`.** §6 of the specification
names `PATCH /api/positions/:id` and it did not exist, which also left R-123 half-enforced: "creating *or
editing* a position writes a Decision in the same transaction" was held on creation and there was no
editing for it to be held on.

**The decision the build made, and what this module holds it to.** An in-place UPDATE plus a correcting
`Decision` carrying both the prior and the new values — A86's choice for goals, applied to positions.
Deactivating is its own act on its own route, because the Decision it writes says something different from
an edit's, and because a boolean in the middle of an edit form is how a member deactivates a position by
accident. Deactivating is **not** deleting: the row stays, its links to every Decision that referenced it
stay, and R-122's own word is *inactive*.

**C-09 is the sharp one** and it is proved here in three ways rather than asserted: the routes write a
Decision, a bare `position.active = False` raises in `before_flush`, and a Core `UPDATE` raises at
statement level (A72). The last two are the ones that would have let this change be built wrong.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from eigentlich.api import positions as positions_api
from eigentlich.db import PlanMutationWithoutDecision, make_session_factory
from eigentlich.models import Decision, Position
from eigentlich.services.auth import login, register_with_credentials
from eigentlich.services.befund import render_befund
from eigentlich.services.goals import observations
from eigentlich.services.grid import role_grid
from eigentlich.services.plan import (
    POSITION_REVISABLE_FIELDS,
    PositionNotFound,
    PositionUnchanged,
    mutate_plan,
    revise_position,
    set_position_active,
)
from conftest import session_overrides

PASSWORD = "ein ziemlich langes passwort"

#: The two fields the C-09 request always carries. A member changing their plan states what they decided.
DECIDED = {"question": "Diese Position anpassen?", "choice": "Ja, mit den neuen Angaben."}
STOPPED = {"question": "Diese Position stilllegen?", "choice": "Ja, sie gehört nicht mehr zum Plan."}
RESUMED = {"question": "Diese Position wieder aufnehmen?", "choice": "Ja, sie gehört wieder zum Plan."}


# ============================================================ fixtures


def _position(session, member_id, **overrides) -> Position:
    """One position and the Decision C-09 requires with it, through the same path the create route uses."""
    fields = {
        "role": "income",
        "capital_type": "human",
        "label": "Lohn Arbeitgeber",
        "magnitude": 92000.0,
        "magnitude_unit": "chf_per_year",
        "time_basis": "80% Anstellung",
    }
    fields.update(overrides)
    with mutate_plan(
        session,
        member_id=member_id,
        question="Anstellung als Einkommen im Humankapital erfassen?",
        choice="Ja, mit 92 000 CHF pro Jahr.",
    ) as decision:
        position = Position(member_id=member_id, **fields)
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    return position


@pytest.fixture()
def api(api_engine, fast_kdf):
    """The positions router on its own app. Yields `(client, member_id, session)`.

    **Its own app rather than `eigentlich.api.main.app`**, which is what every router-level test file here
    does: importing `main` opens the developer's real database file to prove something about a payload.
    The route table of the wired application is `test_api_auth.py`'s subject, and these routes are in it.
    `session_overrides` covers `api.auth.get_session`
    as well as this router's — the token is resolved through that one, and overriding only the router's
    would authenticate against the developer's real database (the A68 failure mode).
    """
    with make_session_factory(api_engine)() as db_session:
        member, _ = register_with_credentials(
            db_session,
            email="editing@example.ch",
            password=PASSWORD,
            age_at_registration=44,
            display_name="Editing Member",
        )
        db_session.commit()
        _, token = login(db_session, email="editing@example.ch", password=PASSWORD)
        db_session.commit()

        app = FastAPI()
        app.include_router(positions_api.router)
        app.dependency_overrides.update(session_overrides(db_session))
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, member.id, db_session


# ============================================================ the router's shape


def test_the_router_exposes_exactly_the_routes_it_means_to():
    """§6 names `PATCH /api/positions/:id`. The other two are R-122's own act, in both directions."""
    found = {
        (sorted(route.methods - {"HEAD", "OPTIONS"})[0], route.path)
        for route in positions_api.router.routes
    }
    assert found == {
        ("PATCH", "/api/positions/{position_id}"),
        ("POST", "/api/positions/{position_id}/deactivate"),
        ("POST", "/api/positions/{position_id}/reactivate"),
    }


def test_no_route_here_takes_a_member_id(api):
    """A11's substantive half: the parameter is gone, not checked. Signature and body model both."""
    import inspect
    import typing

    resolved = 0
    for route in positions_api.router.routes:
        assert "member_id" not in inspect.signature(route.endpoint).parameters
        for hint in typing.get_type_hints(route.endpoint).values():
            fields = getattr(hint, "model_fields", None)
            if fields is None:
                continue
            resolved += 1
            assert "member_id" not in fields, f"{route.path} has member_id on {hint.__name__}"
    # A91's lesson: the body half of this check was inert for weeks because the annotations were strings.
    assert resolved >= 3, f"only {resolved} body models resolved, so the body half checks almost nothing"


@pytest.mark.parametrize(
    "method,path",
    [
        ("PATCH", "/api/positions/not-a-position"),
        ("POST", "/api/positions/not-a-position/deactivate"),
        ("POST", "/api/positions/not-a-position/reactivate"),
    ],
)
def test_every_route_refuses_without_a_token(api, method, path):
    """Sent with no body deliberately: the refusal must come from the guard, not from schema validation.

    FastAPI solves dependencies before it parses the body, which is what makes a 422 here a failure.
    """
    client, _, _ = api
    response = client.request(method, path, headers={"Authorization": ""})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


# ============================================================ PATCH — R-123's second half


def test_editing_a_position_writes_a_decision_in_the_same_transaction(api):
    """R-123 / C-09. The half that had no route to be enforced on."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    before = db_session.execute(select(func.count()).select_from(Decision)).scalar_one()

    response = client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "label": "Lohn Arbeitgeber (neu)"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] == ["label"]
    assert db_session.execute(select(func.count()).select_from(Decision)).scalar_one() == before + 1

    decision = db_session.get(Decision, body["decision_id"])
    assert position.id in [p.id for p in decision.linked_positions]
    db_session.expire_all()
    assert db_session.get(Position, position.id).label == "Lohn Arbeitgeber (neu)"


def test_the_decision_names_the_one_it_corrects(api):
    """R-040 in the shape R-040 asks for: a new record referencing the prior one, which is untouched."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    created = db_session.execute(
        select(Decision).join(Decision.linked_positions).where(Position.id == position.id)
    ).scalars().one()

    body = client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "label": "Anders benannt"}
    ).json()
    assert body["corrects_decision_id"] == created.id

    # And the prior record is exactly as it was written.
    db_session.expire_all()
    assert db_session.get(Decision, created.id).choice == "Ja, mit 92 000 CHF pro Jahr."


def test_the_decision_carries_the_prior_and_the_new_values(api):
    """A86's cost, paid the same way. An UPDATE loses the prior values, so both go into the Decision —
    in C-06's own label/consequence shape, plus a machine-readable map so the earlier state is readable
    rather than reconstructable."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    body = client.patch(
        f"/api/positions/{position.id}",
        json={**DECIDED, "label": "Anders benannt", "liquidity": "within_years"},
    ).json()

    options = db_session.get(Decision, body["decision_id"]).options_considered
    assert len(options) == 2, "C-06: an option set with fewer than two is not a decision"
    for option in options:
        assert option["label"] and option["consequence"], "C-06: every option carries its consequence"
    kept, stated = options[0]["values"], options[1]["values"]
    assert kept == {"label": "Lohn Arbeitgeber", "liquidity": None}
    assert stated == {"label": "Anders benannt", "liquidity": "within_years"}


def test_a_revision_that_changes_nothing_is_refused(api):
    """A86. A Decision saying a change was made when none was is permanent under R-040, so nothing is
    written — including no Decision to have to explain later."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    before = db_session.execute(select(func.count()).select_from(Decision)).scalar_one()

    response = client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "label": "Lohn Arbeitgeber"}
    )
    assert response.status_code == 422, response.text
    assert db_session.execute(select(func.count()).select_from(Decision)).scalar_one() == before


def test_a_field_the_caller_did_not_state_is_left_alone(api):
    """`model_fields_set` is what separates "clear the description" from "do not touch it". A shape where
    those are the same thing silently wipes whatever the member did not retype."""
    client, member_id, db_session = api
    position = _position(db_session, member_id, description="Unbefristete Anstellung")

    client.patch(f"/api/positions/{position.id}", json={**DECIDED, "label": "Neu benannt"})
    db_session.expire_all()
    assert db_session.get(Position, position.id).description == "Unbefristete Anstellung"


def test_a_field_stated_as_null_is_cleared(api):
    """The other half of the same shape: `None` is a value. Without it a member could never remove a note."""
    client, member_id, db_session = api
    position = _position(db_session, member_id, description="Unbefristete Anstellung")

    response = client.patch(f"/api/positions/{position.id}", json={**DECIDED, "description": None})
    assert response.status_code == 200, response.text
    db_session.expire_all()
    assert db_session.get(Position, position.id).description is None


def test_liquidity_can_now_be_stated_which_r031_needed(api):
    """R-031. `goals.observations` reports `liquidity_not_stated` as a fact about a member's own plan, and
    until this route existed there was no way for the member to answer it — `POST /api/positions` does not
    take the field."""
    client, member_id, db_session = api
    position = _position(db_session, member_id, capital_type="financial", time_basis=None)
    assert "liquidity" in POSITION_REVISABLE_FIELDS

    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "liquidity": "illiquid"}
    ).status_code == 200
    db_session.expire_all()
    assert db_session.get(Position, position.id).liquidity == "illiquid"


def test_an_unknown_liquidity_band_is_refused(api):
    """Bands, not numbers. A threshold in years would be an assumption under C-02 and nobody published one."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    response = client.patch(f"/api/positions/{position.id}", json={**DECIDED, "liquidity": "3 years"})
    assert response.status_code == 422, response.text


def test_started_on_is_parsed_and_a_bad_date_is_a_422_about_the_date(api):
    client, member_id, db_session = api
    position = _position(db_session, member_id)

    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "started_on": "2019-04-01"}
    ).status_code == 200
    db_session.expire_all()
    assert db_session.get(Position, position.id).started_on == date(2019, 4, 1)

    bad = client.patch(f"/api/positions/{position.id}", json={**DECIDED, "started_on": "01.04.2019"})
    assert bad.status_code == 422
    assert "ISO-8601" in bad.json()["detail"]


# ============================================================ the invariants an edit could break


def test_moving_a_position_to_financial_capital_with_a_time_basis_is_refused(api):
    """R-121. Hours are the binding constraint on human capital and are not a property of financial.

    **Checked against the resulting state, not against the request.** This request does not mention
    `time_basis` at all — it only moves `capital_type` — and it is the move that leaves the position in a
    state R-121 forbids. A check that read the stated fields would pass it.
    """
    client, member_id, db_session = api
    position = _position(db_session, member_id, capital_type="human", time_basis="80% Anstellung")

    response = client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "capital_type": "financial"}
    )
    assert response.status_code == 422, response.text
    assert "R-121" in response.json()["detail"]

    # Guard: the same move with the time basis cleared in the same request is accepted, so the refusal
    # above is about the state and not about `capital_type` being unrevisable.
    assert client.patch(
        f"/api/positions/{position.id}",
        json={**DECIDED, "capital_type": "financial", "time_basis": None},
    ).status_code == 200


def test_clearing_a_magnitude_unit_alone_is_refused(api):
    """R-120. A magnitude whose unit was dropped is worse than one that is absent — and again, the request
    names only one of the two fields."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    response = client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "magnitude_unit": None}
    )
    assert response.status_code == 422, response.text
    # Guard: both together is accepted.
    assert client.patch(
        f"/api/positions/{position.id}",
        json={**DECIDED, "magnitude": None, "magnitude_unit": None},
    ).status_code == 200


def test_an_unknown_role_is_refused(api):
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "role": "diversification"}
    ).status_code == 422


def test_a_tag_that_is_not_one_of_the_five_is_refused(api):
    """R-021 / D-02. The five correlation tags are stored and read by nothing; a sixth key would be a
    field nobody decided to have."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "tags": {"vibe": "gut"}}
    ).status_code == 422
    # Guard: one of the five is accepted, so the refusal is about the key and not about tags at all.
    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "tags": {"sector": "Bau"}}
    ).status_code == 200


def test_a_rejected_edit_leaves_nothing_in_the_session_to_be_flushed_later(api):
    """The failure mode the mapping-based check exists to prevent.

    Applying the changes to the row and validating afterwards would leave a rejected edit sitting in
    `session.dirty`, where the **next** commit on that session — a legitimate one, somewhere else
    entirely — would flush it and then be refused by C-09 for a mutation its caller never made.
    """
    client, member_id, db_session = api
    position = _position(db_session, member_id)

    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "capital_type": "financial"}
    ).status_code == 422
    assert not [obj for obj in db_session.dirty if isinstance(obj, Position)], (
        "a refused edit left the position dirty in the session"
    )
    # And a later, unrelated write on the same session goes through rather than being refused for it.
    _position(db_session, member_id, label="Zweite Position")
    db_session.expire_all()
    assert db_session.get(Position, position.id).capital_type == "human"


def test_active_is_not_revisable_here_and_the_refusal_names_it(api):
    """R-122. Marking a position inactive is its own act on its own route.

    **Refused by name rather than ignored.** Pydantic's default is to drop an unrecognised field, and on
    a route whose shape is "state only what you are changing" that turns `{"active": false}` into a
    response that changed nothing — or into "your revision is a no-op", which is a true sentence about the
    wrong thing. A client that sends it must not come away believing it deactivated something.

    **Planted violation:** removed `model_config = ConfigDict(extra="forbid")`. The request was accepted,
    the field silently dropped, and this failed on the 422 becoming a `PositionUnchanged` message that
    never mentions `active`. Restored.
    """
    client, member_id, db_session = api
    position = _position(db_session, member_id)

    response = client.patch(f"/api/positions/{position.id}", json={**DECIDED, "active": False})
    assert response.status_code == 422, response.text
    assert "active" in response.text, (
        "the refusal does not name the field, so a client cannot tell it from a no-op revision"
    )
    assert "active" not in POSITION_REVISABLE_FIELDS
    db_session.expire_all()
    assert db_session.get(Position, position.id).active is True

    # Guard on the refusal: PATCH is not simply refusing everything.
    assert client.patch(
        f"/api/positions/{position.id}", json={**DECIDED, "label": "Anders"}
    ).status_code == 200


def test_a_misspelt_field_is_refused_rather_than_dropped(api):
    """The general case of the rule above. A silently-ignored field is a member who thinks they saved."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    response = client.patch(f"/api/positions/{position.id}", json={**DECIDED, "lable": "Vertippt"})
    assert response.status_code == 422, response.text
    assert "lable" in response.text


def test_the_deactivate_route_refuses_a_body_that_tries_to_state_the_direction(api):
    """R-122. The act is the route. A flag in the body is a flag to get the wrong way round."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    response = client.post(
        f"/api/positions/{position.id}/deactivate", json={**STOPPED, "active": True}
    )
    assert response.status_code == 422, response.text
    db_session.expire_all()
    assert db_session.get(Position, position.id).active is True


def test_a_position_that_is_not_this_members_is_a_404(api):
    """A81's reasoning. "No such position" and "not yours" must be one answer, or the response can be used
    to find out who owns what."""
    client, _, db_session = api
    other, _ = register_with_credentials(
        db_session,
        email="somebody@example.ch",
        password=PASSWORD,
        age_at_registration=33,
        display_name="Somebody Else",
    )
    db_session.commit()
    theirs = _position(db_session, other.id, label="Nicht meine Position")

    assert client.patch(f"/api/positions/{theirs.id}", json={**DECIDED, "label": "Meine"}).status_code == 404
    assert client.post(f"/api/positions/{theirs.id}/deactivate", json=STOPPED).status_code == 404
    # A position that does not exist at all answers identically.
    assert client.patch("/api/positions/nope", json={**DECIDED, "label": "Meine"}).status_code == 404
    db_session.expire_all()
    assert db_session.get(Position, theirs.id).label == "Nicht meine Position"


# ============================================================ R-122 — inactive, and not deleted


def test_deactivating_a_position_marks_it_and_removes_nothing(api):
    """R-122. "Inactive positions remain in history and in decisions." Both halves asserted."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    created = db_session.execute(
        select(Decision).join(Decision.linked_positions).where(Position.id == position.id)
    ).scalars().one()

    response = client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active"] is False
    assert body["changed"] == ["active"]
    assert body["remains_in_history"] is True
    assert body["remains_linked_to_decisions"] is True

    db_session.expire_all()
    row = db_session.get(Position, position.id)
    assert row is not None, "R-122: deactivating deleted the position"
    assert row.active is False
    # Still linked to the Decision that created it, which is the "remain in decisions" half.
    assert position.id in [p.id for p in db_session.get(Decision, created.id).linked_positions]


def test_deactivating_writes_a_decision_because_it_is_a_material_change(api):
    """C-09. Deactivating a position changes what the member's live plan is."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    before = db_session.execute(select(func.count()).select_from(Decision)).scalar_one()

    body = client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED).json()
    assert db_session.execute(select(func.count()).select_from(Decision)).scalar_one() == before + 1

    decision = db_session.get(Decision, body["decision_id"])
    assert decision.corrects_id is not None, "R-040: the correcting record names the prior one"
    assert [option["values"]["active"] for option in decision.options_considered] == [True, False], (
        "the option the member chose goes second, so the pair reads as 'what stands now, and what is "
        "being decided'"
    )


def test_deactivating_twice_is_refused(api):
    """A86's rule. A Decision claiming a change that did not happen is permanent under R-040."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    assert client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED).status_code == 200
    before = db_session.execute(select(func.count()).select_from(Decision)).scalar_one()

    again = client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)
    assert again.status_code == 422, again.text
    assert db_session.execute(select(func.count()).select_from(Decision)).scalar_one() == before


def test_a_position_can_be_taken_back_into_the_live_plan(api):
    """R-122 does not say the mark is one-way, and making it one-way would make a mis-click permanent on a
    table `db.py` calls legitimately mutable. Its own Decision, like every other material change."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)

    body = client.post(f"/api/positions/{position.id}/reactivate", json=RESUMED).json()
    assert body["active"] is True
    db_session.expire_all()
    assert db_session.get(Position, position.id).active is True

    decision = db_session.get(Decision, body["decision_id"])
    assert [option["values"]["active"] for option in decision.options_considered] == [False, True]


def test_reactivating_an_active_position_is_refused(api):
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    assert client.post(f"/api/positions/{position.id}/reactivate", json=RESUMED).status_code == 422


# ============================================================ the read paths that were waiting for a writer


def test_the_role_grid_returns_a_deactivated_position_flagged_rather_than_dropped(api):
    """`services/grid.py`: "inactive positions are included and flagged rather than filtered out: R-122
    keeps them in history, and a grid that silently drops them would misrepresent what the member has
    done." That sentence had never been true of a position anything had deactivated."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)
    db_session.expire_all()

    grid = role_grid(db_session, member_id=member_id)
    entries = [p for cell in grid["cells"] for p in cell["positions"] if p["id"] == position.id]
    assert len(entries) == 1, "R-122: the grid dropped a deactivated position"
    assert entries[0]["active"] is False


def test_the_befund_says_a_cell_holds_only_inactive_material(api):
    """`services/befund.py` has a sentence for exactly this state — "hier steht nur Stillgelegtes.
    Stillgelegtes bleibt in der Geschichte" — and nothing could put a position in it until now."""
    client, member_id, db_session = api
    position = _position(db_session, member_id)
    client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)
    db_session.expire_all()

    report = render_befund(db_session, member_id=member_id)
    facts = [
        fact
        for block in report["sections"]
        if block["key"] == "plan"
        for fact in block["facts"]
    ]
    inactive = [f for f in facts if f["key"] == "cell_inactive_only"]
    assert inactive, "the Befund does not report a cell holding only inactive material"
    assert "Stillgelegtes" in inactive[0]["sentence"]
    assert "Lohn Arbeitgeber" in (inactive[0]["quoted"] or {}).get("position_labels", [])
    # Guard: the cell is not also reported as filled, which is the fact this replaces.
    filled = [
        f for f in facts
        if f["key"] == "cell_filled" and f["values"]["role"] == "income"
        and f["values"]["capital_type"] == "human"
    ]
    assert not filled


def test_a_goals_funding_stops_counting_a_deactivated_position(api):
    """`goals.observations` filters funding on `p.active`. R-030 makes an unfunded goal a legitimate
    state, so a goal funded only by a position the member stopped reads as dated-but-unfunded."""
    from eigentlich.models import Goal

    client, member_id, db_session = api
    position = _position(db_session, member_id)
    with mutate_plan(
        db_session, member_id=member_id, question="Ziel erfassen?", choice="Ja."
    ) as decision:
        goal = Goal(member_id=member_id, name="Wohneigentum", target_date=date(2031, 6, 1))
        goal.funded_by.append(position)
        db_session.add(goal)
        decision.linked_goals.append(goal)
        decision.linked_positions.append(position)
    db_session.commit()

    kinds = {o["kind"] for o in observations(goal)}
    assert "dated_but_unfunded" not in kinds

    client.post(f"/api/positions/{position.id}/deactivate", json=STOPPED)
    db_session.expire_all()
    goal = db_session.get(Goal, goal.id)
    assert "dated_but_unfunded" in {o["kind"] for o in observations(goal)}
    # And the link itself is intact: R-122 keeps the position, it just leaves the live plan.
    assert position.id in [p.id for p in goal.funded_by]


# ============================================================ C-09, the two guards that are not the route


def test_deactivating_without_a_decision_is_refused_in_before_flush(session, member):
    """C-09, the ORM guard. A one-line fix in a REPL is exactly the case `db.py` says it has to catch.

    **This test is itself the planted violation:** `position.active = False` with no Decision is the
    shortest possible way to build R-122 wrong, and it raises rather than persisting.

    **And it was checked for being unable to fail**, which is the whole point of doing this: an early
    `return` was planted at the top of `db.py::_check`, and this went red on the raise that never came.
    Restored. Without that check, "it raises" would be a claim about a guard nobody had watched work on
    *this* mutation.
    """
    position = _position(session, member.id)
    position.active = False
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()
    session.rollback()


def test_deactivating_by_core_update_is_refused_at_statement_level(session, member):
    """C-09 / A72. `session.execute(update(...))` is R-123's exact case and it never reaches
    `before_flush` — which is why A72 put a `before_execute` listener underneath it.

    **Checked for being unable to fail**, and the first attempt at that was itself wrong: standing down
    `db.py::_check` left this green, because the guard that catches a Core `UPDATE` is
    `_refuse_unvetted_plan_dml`, a separate listener. Standing *that* down turned it red. Restored. Two
    guards, two plants — which is A72's point stated as a test rather than as a docstring.
    """
    position = _position(session, member.id)
    with pytest.raises(PlanMutationWithoutDecision):
        session.execute(update(Position).where(Position.id == position.id).values(active=False))
    session.rollback()
    session.expire_all()
    assert session.get(Position, position.id).active is True


def test_the_service_functions_are_the_convenient_path_and_not_the_enforcement(session, member):
    """Both write through `mutate_plan`, so the Decision is in the same transaction by construction.

    Guard on the two tests above: if `set_position_active` itself raised, they would pass for the wrong
    reason and the feature would not work at all.
    """
    position = _position(session, member.id)
    result = set_position_active(
        session, member_id=member.id, position_id=position.id, active=False, **STOPPED
    )
    session.commit()
    assert result["position"].active is False
    assert result["decision"].id


# ============================================================ the service's own refusals


def test_the_service_refuses_a_position_that_is_not_the_members(session, member):
    position = _position(session, member.id)
    with pytest.raises(PositionNotFound):
        revise_position(
            session,
            member_id="somebody-else",
            position_id=position.id,
            changes={"label": "Meine"},
            **DECIDED,
        )


def test_the_service_refuses_a_field_that_is_not_revisable(session, member):
    position = _position(session, member.id)
    with pytest.raises(ValueError, match="not a revisable field"):
        revise_position(
            session,
            member_id=member.id,
            position_id=position.id,
            changes={"created_at": None},
            **DECIDED,
        )


def test_the_service_refuses_active_by_name(session, member):
    position = _position(session, member.id)
    with pytest.raises(ValueError, match="R-122"):
        revise_position(
            session,
            member_id=member.id,
            position_id=position.id,
            changes={"active": False},
            **DECIDED,
        )


def test_the_service_refuses_a_revision_that_changes_nothing(session, member):
    position = _position(session, member.id)
    with pytest.raises(PositionUnchanged):
        revise_position(
            session,
            member_id=member.id,
            position_id=position.id,
            changes={"label": "Lohn Arbeitgeber"},
            **DECIDED,
        )


def test_the_revisable_list_names_neither_the_identity_nor_the_owner(session, member):
    """`services/goals.REVISABLE_FIELDS`'s reason: a position does not move between members and does not
    get a new identity, and a field list that could express either is one typo from doing it."""
    for forbidden in ("id", "member_id", "created_at", "active", "data_class"):
        assert forbidden not in POSITION_REVISABLE_FIELDS


# ============================================================ C-01 — every string this change authors


def test_every_german_string_these_decisions_carry_passes_c01(session, member):
    """C-01. The option labels and consequences are eigentliCH's own words, so they go through the outbound
    scan like any other authored sentence.

    Read off the Decisions the two functions actually write rather than retyped here — a copy would be a
    second list to keep in step, and the first divergence would be silent (A73, A91).
    """
    position = _position(session, member.id)
    written = []

    revised = revise_position(
        session,
        member_id=member.id,
        position_id=position.id,
        changes={"label": "Anders benannt", "liquidity": "within_years"},
        **DECIDED,
    )
    session.commit()
    written.append(revised["decision"])

    stopped = set_position_active(
        session, member_id=member.id, position_id=position.id, active=False, **STOPPED
    )
    session.commit()
    written.append(stopped["decision"])

    resumed = set_position_active(
        session, member_id=member.id, position_id=position.id, active=True, **RESUMED
    )
    session.commit()
    written.append(resumed["decision"])

    strings = [
        value
        for decision in written
        for option in decision.options_considered
        for key, value in option.items()
        if key in ("label", "consequence")
    ]
    assert len(strings) == 12, f"expected six options across three decisions, found {len(strings)}"

    # Every one of these strings used to be run through C-01's outbound gate here, with a planted
    # advisory sentence beside it proving the scan could still refuse something (A20's pattern). Both
    # went with C-01 on 20 September 2026 (A164). The count above is what survives: six options across
    # three decisions, each carrying a label and a consequence, which is C-06's shape and not C-01's.


def test_no_gamification_vocabulary_or_identifier_in_this_changes_source():
    """C-07 over the two files this change wrote. A91: the vocabulary comes from `vocabulary.py`.

    **Comments and docstrings are stripped**, the way `test_learning.py::_code_only` does it, so a
    docstring that has to name the constraint does not trip the check for it. And identifiers as well as
    words, because a payload key named `score` passes a prose filter and is still the primitive C-07
    forbids.

    **Planted violation:** `progress_ratio = len(changed)` inside `set_position_active`. Failed naming
    `plan.py:… progress_ratio`. Removed.
    """
    import ast

    from vocabulary import GAMIFICATION_WORDS as WORDS
    from test_content import _whole_words as words_in
    from test_constraints import GAMIFICATION_IDENTIFIERS
    from test_learning import _code_only

    from pathlib import Path

    sources = [
        Path(positions_api.__file__),
        Path(__import__("eigentlich.services.plan", fromlist=["x"]).__file__),
    ]
    tally = ("progress", "fortschritt", "completion", "ratio", "percent", "prozent")

    for path in sources:
        stripped = _code_only(path)
        found = words_in(WORDS + ("rank", "daily_goal") + tally, stripped)
        assert not found, f"C-07 / R-113: {path.name} carries {found}"

        offences = []
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.arg):
                names = [node.arg]
            elif isinstance(node, ast.keyword) and node.arg:
                names = [node.arg]
            for name in names:
                tokens = set(name.lower().lstrip("_").split("_"))
                if name.lower().lstrip("_") in GAMIFICATION_IDENTIFIERS or tokens & set(tally):
                    offences.append(f"{path.name}:{getattr(node, 'lineno', '?')} {name}")
        assert not offences, f"C-07 forbids gamification primitives. Found: {offences}"

    # Guards on both halves: the stripper has to keep the code, and the filters have to fire.
    stripped = _code_only(sources[0])
    assert "deactivate_position" in stripped, "the stripper removed code as well as prose"
    assert words_in(("score",), "the score was high") == ["score"]
    assert "ratio" in tally and {"ratio"} & set(tally)


def test_the_authored_strings_carry_no_forbidden_vocabulary(session, member):
    """R-143 and C-07 as copy, from the one shared vocabulary (A91)."""
    from vocabulary import GAMIFICATION_WORDS, MOUNTAIN_WORDS
    from test_content import _whole_words

    position = _position(session, member.id)
    result = set_position_active(
        session, member_id=member.id, position_id=position.id, active=False, **STOPPED
    )
    session.commit()
    blob = " ".join(
        f"{option['label']} {option['consequence']}"
        for option in result["decision"].options_considered
    ).lower()
    assert not _whole_words(GAMIFICATION_WORDS, blob)
    assert not _whole_words(MOUNTAIN_WORDS, blob)
    # Guard on the filter, on this blob.
    assert _whole_words(("score",), blob + " score") == ["score"]
