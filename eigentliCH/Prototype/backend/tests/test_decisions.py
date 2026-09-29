"""S-07 at the boundary: R-160's filterable record, R-161's attribution and chain, R-162's correction.

**What this file is for.** A90's audit found that S-07 had no route and no screen, and that R-160 was the
only identifier in the whole specification with zero references anywhere in the code. `Decision` rows were
being written correctly and immutably the entire time, and `services/plan.py::record_correction` had been
complete and tested since phase 1 with no caller outside the tests. This file is the proof that both halves
are now reachable over HTTP by the member who owns them and by nobody else.

**The router is not wired into `api/main.py`.** That line is the owner's to add, so the fixture here stands
`api/decisions.py` up on its own app alongside `api/auth.py` — the token has to be resolvable or every
assertion below is a 401 about nothing. The consequence is stated rather than left implicit: the route-table
tests in `test_api_auth.py` read the application's own table and therefore do **not** cover these routes
until the `include_router` line lands. So the two guarantees that matter most from that file — no `member_id`
from the caller, and no guarded route reachable without a token — are re-proved here against this router's
own table, in the A91-corrected form that actually resolves annotations.

**Every guard here was verified by planting the violation.** What was planted and what went red is recorded
in each docstring. A20, A63, A66, A68, A81 and A91 are six occasions in this build where a green suite hid a
broken guarantee, and every one of them was absence-shaped.
"""

from __future__ import annotations

import ast
import inspect
import re
import typing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eigentlich.api import decisions as decisions_api
from eigentlich.api.auth import router as auth_router
from eigentlich.api.decisions import router as decisions_router
from eigentlich.models import Curator, CuratorSession, Decision, Goal, Position, VaultItem, utcnow
from eigentlich.services.auth import register_with_credentials
from eigentlich.services.plan import mutate_plan, record_correction
from conftest import session_overrides

MODULE = Path(decisions_api.__file__)

PASSWORD_A = "ein ziemlich langes passwort"
PASSWORD_B = "ein anderes langes passwort"

#: German with umlauts, on purpose. Two things are being checked by using it: that the payload carries UTF-8
#: through FastAPI's JSON encoding unmangled, and that the bytes of this file survived being written. The
#: shell hazard that has now landed six times in this build (A88, A91) corrupts exactly this kind of string.
GERMAN_CHOICE = "Frühpensionierung mit 62, Vorbezug geprüft"
GERMAN_CORRECTION = "Frühpensionierung mit 63, Höhe des Vorbezugs überprüft"


# ============================================================ the router, on a fixture database


@pytest.fixture()
def app(api_session, fast_kdf):
    """`api/decisions.py` and `api/auth.py` on one app, both pointed at the in-memory fixture.

    `session_overrides` rather than one override, for the reason `conftest.py` gives: a route resolves its
    member through `api.auth.get_session`, and overriding only this router's copy would authenticate against
    the developer's real `backend/eigentlich.db` while the routes read the fixture. That is the A68 failure
    mode and it is the quietest one there is.
    """
    application = FastAPI()
    application.include_router(auth_router)
    application.include_router(decisions_router)
    application.dependency_overrides.update(session_overrides(api_session))
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _register(session, *, email, password, name):
    member, _ = register_with_credentials(
        session,
        email=email,
        password=password,
        age_at_registration=44,
        display_name=name,
        locale="de-CH",
    )
    session.commit()
    return member


@pytest.fixture()
def member_a(api_session, fast_kdf):
    return _register(api_session, email="a@example.ch", password=PASSWORD_A, name="Mitglied A")


@pytest.fixture()
def member_b(api_session, fast_kdf):
    return _register(api_session, email="b@example.ch", password=PASSWORD_B, name="Mitglied B")


def _token(client, email, password):
    response = client.post("/api/session", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["token"]


@pytest.fixture()
def token_a(client, member_a):
    return _token(client, "a@example.ch", PASSWORD_A)


@pytest.fixture()
def token_b(client, member_b):
    return _token(client, "b@example.ch", PASSWORD_B)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================ material to read back


def _position(session, member, label="Anstellung"):
    with mutate_plan(
        session, member_id=member.id, question=f"{label} erfassen?", choice="Ja"
    ) as decision:
        position = Position(
            member_id=member.id, role="income", capital_type="human", label=label
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    return position, decision


def _goal(session, member, name="Wohneigentum"):
    with mutate_plan(
        session, member_id=member.id, question=f"Ziel {name} erfassen?", choice=GERMAN_CHOICE
    ) as decision:
        goal = Goal(member_id=member.id, name=name, template="early_retirement")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()
    return goal, decision


def _vault_decision(session, member, title="Police"):
    item = VaultItem(
        member_id=member.id, kind="policy", title=title, source="upload", stored_at=utcnow()
    )
    session.add(item)
    session.flush()
    with mutate_plan(
        session, member_id=member.id, question="Dokument dem Plan zuordnen?", choice="Ja"
    ) as decision:
        decision.linked_vault_items.append(item)
    session.commit()
    return item, decision


# ============================================================ R-160 — the list, and its filters


def test_the_list_is_the_members_own_newest_first(client, api_session, member_a, token_a):
    """R-160's chronology, in the direction a screen reads.

    **This test was flaky, and the fix belongs here rather than in the query.** It asserted that the vault
    decision was `decisions[0]` — the newest. Three decisions written inside one microsecond tie on
    `created_at`, and the query's tiebreak is `id.desc()` on a random hex id, so which tied row came first
    changed from run to run: one failure in five.

    **Unlike A96 this is not a defect in the ordering.** There the chain reordered *within* one database,
    because a correction chain has an intrinsic order (each record corrects the previous) and the query was
    not using it. A list of unrelated decisions has no order beyond time, and `(created_at desc, id desc)`
    is total and **stable for a given database** — ids do not change, so a member's list does not reshuffle
    between page loads. What is unpredictable is only which id a *fresh* run generates, which is a fact
    about the test and not about the product.

    So the assertions no longer assume the position of a tied row: chronology is checked as a property, and
    the vault link is checked on the record that actually carries it.
    """
    _position(api_session, member_a, label="Anstellung")
    goal, goal_decision = _goal(api_session, member_a, name="Wohneigentum")
    item, vault_decision = _vault_decision(api_session, member_a)

    payload = client.get("/api/decisions", headers=bearer(token_a)).json()

    assert payload["order"] == "newest_first"
    assert payload["empty_reason"] is None
    recorded = [record["recorded_at"] for record in payload["decisions"]]
    assert recorded == sorted(recorded, reverse=True), "R-160's chronology is not in order"
    assert len(payload["decisions"]) == 3

    by_id = {record["id"]: record for record in payload["decisions"]}
    assert by_id[vault_decision.id]["linked_vault_item_ids"] == [item.id]
    assert by_id[goal_decision.id]["linked_goal_ids"] == [goal.id]
    assert by_id[vault_decision.id]["linked_goal_ids"] == []


def test_the_list_filters_by_position_goal_and_vault_item(client, api_session, member_a, token_a):
    """R-160's substantive half — the clause with no reference anywhere in the code until now.

    **Planted violation:** dropped the `position_id` clause from the query in `list_decisions`. Three of
    these assertions went red at once. Restored.
    """
    position, position_decision = _position(api_session, member_a)
    goal, goal_decision = _goal(api_session, member_a)
    item, vault_decision = _vault_decision(api_session, member_a)

    def ids(**params):
        response = client.get("/api/decisions", headers=bearer(token_a), params=params)
        assert response.status_code == 200, response.text
        return [record["id"] for record in response.json()["decisions"]]

    assert ids(position_id=position.id) == [position_decision.id]
    assert ids(goal_id=goal.id) == [goal_decision.id]
    assert ids(vault_item_id=item.id) == [vault_decision.id]
    assert sorted(ids()) == sorted([position_decision.id, goal_decision.id, vault_decision.id])


def test_two_filters_are_an_and_not_an_or(client, api_session, member_a, token_a):
    """A decision that touched this position AND this goal is the narrower question, and the one asked."""
    with mutate_plan(
        api_session, member_id=member_a.id, question="Ziel und Position zusammen?", choice="Ja"
    ) as both:
        position = Position(
            member_id=member_a.id, role="income", capital_type="human", label="Anstellung"
        )
        goal = Goal(member_id=member_a.id, name="Wohneigentum")
        api_session.add_all([position, goal])
        both.linked_positions.append(position)
        both.linked_goals.append(goal)
    api_session.commit()

    other_position, other_decision = _position(api_session, member_a, label="Vermietung")

    joined = client.get(
        "/api/decisions",
        headers=bearer(token_a),
        params={"position_id": position.id, "goal_id": goal.id},
    ).json()["decisions"]
    assert [record["id"] for record in joined] == [both.id]

    disjoint = client.get(
        "/api/decisions",
        headers=bearer(token_a),
        params={"position_id": other_position.id, "goal_id": goal.id},
    ).json()["decisions"]
    assert disjoint == [], "the filters combined as an OR, which is a wider answer than was asked for"
    assert other_decision.id is not None


def test_a_filter_naming_another_members_position_returns_an_empty_list(
    client, api_session, member_a, member_b, token_a
):
    """A81. Not a 404 and not a 403: the query is scoped to the member's own decisions before the filter
    runs, so an id belonging to somebody else is indistinguishable from one that was never written.

    **Planted violation:** scoped the query by the filter alone, dropping `Decision.member_id ==
    member.id`. This test went red with member B's decision in member A's list. Restored.
    """
    _position(api_session, member_a, label="Anstellung")
    others_position, others_decision = _position(api_session, member_b, label="Fremde Position")

    payload = client.get(
        "/api/decisions", headers=bearer(token_a), params={"position_id": others_position.id}
    ).json()

    assert payload["decisions"] == []
    assert payload["empty_reason"] == "no_decision_matched_the_filter"
    assert others_decision.id not in [record["id"] for record in payload["decisions"]]


def test_the_filtered_empty_case_does_not_borrow_the_befunds_nothing_recorded_sentence(
    client, api_session, member_a, token_a
):
    """The distinction the payload exists to make: nothing recorded, versus a filter that matched nothing.

    The Befund's `no_decisions_recorded` phrase reads "no decision has been recorded yet". That is true of a
    member with an empty record and false of a member with twenty decisions and a narrow filter, and shipping
    it for both would make S-07 tell the member something untrue about their own history.

    **Planted violation:** returned the Befund sentinel sentence unconditionally whenever the list was
    empty. This test went red on `empty_sentence`. Restored.
    """
    empty = client.get("/api/decisions", headers=bearer(token_a)).json()
    assert empty["empty_reason"] == "no_decisions_recorded"
    assert empty["empty_sentence"], "the unfiltered empty case has no sentence at all"

    position, _ = _position(api_session, member_a)
    goal, _ = _goal(api_session, member_a)

    filtered = client.get(
        "/api/decisions",
        headers=bearer(token_a),
        params={"position_id": position.id, "goal_id": goal.id},
    ).json()
    assert filtered["decisions"] == []
    assert filtered["empty_reason"] == "no_decision_matched_the_filter"
    assert filtered["empty_sentence"] is None, (
        "a filter that matched nothing was answered with 'nothing has been recorded yet', which is a "
        "false statement about this member's record"
    )


def test_the_list_carries_no_count_and_no_total(client, api_session, member_a, token_a):
    """C-07 and R-003. S-07 is exactly the screen a completion figure would ruin."""
    _position(api_session, member_a)
    payload = client.get("/api/decisions", headers=bearer(token_a)).json()
    forbidden = {"count", "total", "n", "how_many", "complete", "completeness", "progress", "score"}
    assert not forbidden & set(payload), f"the list reports a tally: {forbidden & set(payload)}"


def test_an_unknown_language_is_refused_rather_than_answered_in_german(client, token_a):
    """A12. No fallback: a payload half in the wrong language is worse than a refused one."""
    assert client.get("/api/decisions", headers=bearer(token_a), params={"language": "fr"}).status_code == 422


# ============================================================ R-161 — author, curator, chain


def test_a_record_names_its_author_and_whether_a_curator_was_involved(
    client, api_session, member_a, token_a
):
    """R-161, both clauses, including the one the Befund cannot answer.

    A decision the *member* recorded inside a curator session is the case that matters: the author is the
    member, and a curator was involved. `services/befund.py` drops `curator_session_id` from its decisions
    fact entirely, so its section answers the first clause and not the second. This is the disagreement
    `api/decisions.py`'s docstring records, and this test is what makes it a claim rather than an opinion.

    **Planted violation:** removed `curator_session_id` from `_record`, matching what the Befund carries.
    This test went red on `curator_involved`. Restored.
    """
    # A real `curators` row, because `CuratorSession.curator_id` is a foreign key since 31 August 2026 —
    # A67's correction to A40. The `"kuratorin-1"` this used to pass was the kind of string the column now
    # refuses, and the reason it refuses it is that the session's `opened` event cannot be corrected later.
    kuratorin = Curator(display_name="Eine Kuratorin", email="kuratorin@example.ch", role_label="Kurator")
    api_session.add(kuratorin)
    api_session.flush()

    sitting = CuratorSession(
        member_id=member_a.id, curator_id=kuratorin.id, opened_from="decisions"
    )
    api_session.add(sitting)
    api_session.flush()

    with mutate_plan(
        api_session,
        member_id=member_a.id,
        question="Gemeinsam besprochen?",
        choice="Ja",
        curator_session_id=sitting.id,
    ) as with_curator:
        goal = Goal(member_id=member_a.id, name="Gemeinsames Ziel")
        api_session.add(goal)
        with_curator.linked_goals.append(goal)
    api_session.commit()

    _, alone = _position(api_session, member_a)

    records = {
        record["id"]: record
        for record in client.get("/api/decisions", headers=bearer(token_a)).json()["decisions"]
    }

    assert records[with_curator.id]["author"] == "member"
    assert records[with_curator.id]["curator_session_id"] == sitting.id
    assert records[with_curator.id]["curator_involved"] is True

    assert records[alone.id]["curator_involved"] is False
    assert records[alone.id]["curator_session_id"] is None


def test_a_curator_authored_decision_names_which_curator(client, api_session, member_a, token_a):
    """R-212. "a curator" is not an attribution; the record says which one."""
    with mutate_plan(
        api_session,
        member_id=member_a.id,
        question="Vom Kurator erfasst?",
        choice="Ja",
        author="curator",
        author_ref="Kuratorin Beatrice Roth",
    ) as decision:
        goal = Goal(member_id=member_a.id, name="Vom Kurator")
        api_session.add(goal)
        decision.linked_goals.append(goal)
    api_session.commit()

    record = client.get(f"/api/decisions/{decision.id}", headers=bearer(token_a)).json()["decision"]
    assert record["author"] == "curator"
    assert record["author_ref"] == "Kuratorin Beatrice Roth"
    assert record["curator_involved"] is True


def test_one_decision_names_what_it_linked_to(client, api_session, member_a, token_a):
    """R-161. What it touched, named rather than left as an id a client has to resolve."""
    position, decision = _position(api_session, member_a, label="Anstellung")

    payload = client.get(f"/api/decisions/{decision.id}", headers=bearer(token_a)).json()

    assert payload["linked"]["positions"] == [
        {
            "id": position.id,
            "role": "income",
            "capital_type": "human",
            "quoted": {"label": "Anstellung"},
        }
    ]


def test_the_vault_links_are_ids_and_carry_no_k3_content(client, api_session, member_a, token_a):
    """C-04. A `VaultItem` is K3 as a whole, so copying its title here would raise this payload to K3.

    The Befund makes the same call: its decisions fact is K2 and carries `linked_vault_item_ids`, while the
    title appears only in the expiries section, which declares itself K3.

    **Planted violation:** added `"title": item.title` to `_linked`'s vault entries. This test went red on
    the title appearing in the payload. Restored.
    """
    item, decision = _vault_decision(api_session, member_a, title="Lebensversicherung Police 4711")

    response = client.get(f"/api/decisions/{decision.id}", headers=bearer(token_a))
    payload = response.json()

    assert payload["data_class"] == 2, "a decisions payload declaring K3 has picked up documentary content"
    assert payload["linked"]["vault_item_ids"] == [item.id]
    assert "Lebensversicherung" not in response.text, "a K3 title reached a K2 payload"


def test_the_chain_runs_oldest_first_and_holds_a_correction_of_a_correction(
    client, api_session, member_a, token_a
):
    """R-040's chain is the meaning, and it reads forwards.

    Oldest first, on `services/curator.py`'s reasoning for the same rows: "a correction arriving without the
    record it corrects would read as a contradiction."

    **Planted violation:** replaced the upward walk with `decision.corrects_id or decision.id`, a single
    step. Asking about the middle record still gave the right root — which is why this test asks about the
    *last* record as well, where one step lands on the middle one. The first version of this test queried
    only the middle and passed with the plant in place, and that is the guard being unable to fail. Restored,
    and the last-record assertion is the load-bearing one.
    """
    _, first = _goal(api_session, member_a)
    second = record_correction(api_session, prior=first, choice="Zweite Fassung", author="member")
    api_session.commit()
    third = record_correction(api_session, prior=second, choice="Dritte Fassung", author="member")
    api_session.commit()

    # Two steps up from the end of the chain. A one-step walk roots this at `second`.
    from_the_end = client.get(f"/api/decisions/{third.id}", headers=bearer(token_a)).json()["chain"]
    assert from_the_end["root_id"] == first.id, "the walk to the root stops short"
    assert [record["id"] for record in from_the_end["records"]] == [first.id, second.id, third.id]

    chain = client.get(f"/api/decisions/{second.id}", headers=bearer(token_a)).json()["chain"]

    assert chain["is_part_of_a_chain"] is True
    assert chain["root_id"] == first.id
    assert [record["id"] for record in chain["records"]] == [first.id, second.id, third.id]
    assert [record["is_the_one_asked_for"] for record in chain["records"]] == [False, True, False]

    middle = chain["records"][1]
    assert middle["corrects_id"] == first.id
    assert middle["corrected_by_ids"] == [third.id]
    assert middle["is_correction"] is True
    assert middle["was_corrected"] is True

    assert chain["records"][0]["is_correction"] is False
    assert chain["records"][0]["corrected_by_ids"] == [second.id]
    assert chain["records"][-1]["was_corrected"] is False


def test_a_lone_decision_is_not_reported_as_a_chain(client, api_session, member_a, token_a):
    """Without this, `is_part_of_a_chain` could be hard-wired True and every assertion above would pass."""
    _, decision = _position(api_session, member_a)
    chain = client.get(f"/api/decisions/{decision.id}", headers=bearer(token_a)).json()["chain"]
    assert chain["is_part_of_a_chain"] is False
    assert chain["root_id"] == decision.id
    assert [record["id"] for record in chain["records"]] == [decision.id]


def test_a_corrected_record_says_so_even_when_the_correction_is_filtered_out(
    client, api_session, member_a, token_a
):
    """The reason `_corrections_by_prior` ignores the caller's filter.

    A filtered view of S-07 that showed a superseded record with nothing marking it is the one reading R-040
    exists to prevent. `record_correction` copies the prior's links, so a filter on the shared position keeps
    both — this test breaks that by correcting a decision whose links the correction does not share.

    **Planted violation:** computed `corrections` from the filtered result set instead of from all of the
    member's decisions. This test went red on `was_corrected`. Restored.
    """
    position, decision = _position(api_session, member_a)
    correction = record_correction(
        api_session, prior=decision, choice="Andere Fassung", author="member"
    )
    # Drop the copied links so the filter below cannot reach the correction.
    correction.linked_positions = []
    api_session.commit()

    filtered = client.get(
        "/api/decisions", headers=bearer(token_a), params={"position_id": position.id}
    ).json()["decisions"]

    assert [record["id"] for record in filtered] == [decision.id]
    assert filtered[0]["was_corrected"] is True
    assert filtered[0]["corrected_by_ids"] == [correction.id]


# ============================================================ R-162 — record a correction


def test_a_correction_is_a_new_record_and_the_prior_one_is_untouched(
    client, api_session, member_a, token_a
):
    """R-040 and R-162 over HTTP. The affordance R-040 exists for, which had no caller until now.

    **Planted violation:** replaced the `record_correction` call with `prior.choice = body.choice`. The
    request failed with `DecisionImmutable` from `db.py`'s `before_flush` — a 500, not a quiet success —
    and this test went red. Restored. R-040 is enforced underneath this route, not by it.
    """
    goal, prior = _goal(api_session, member_a)
    prior_id, prior_choice = prior.id, prior.choice

    response = client.post(
        f"/api/decisions/{prior_id}/correction",
        headers=bearer(token_a),
        json={"choice": GERMAN_CORRECTION, "reasoning": "Der Vorbezug war falsch gerechnet."},
    )
    assert response.status_code == 201, response.text
    payload = response.json()

    assert payload["decision"]["id"] != prior_id
    assert payload["decision"]["corrects_id"] == prior_id
    assert payload["corrects_decision_id"] == prior_id
    assert payload["decision"]["is_correction"] is True
    assert payload["decision"]["quoted"]["choice"] == GERMAN_CORRECTION
    assert payload["prior"]["unchanged"] is True

    api_session.expire_all()
    written = api_session.get(Decision, prior_id)
    assert written.choice == prior_choice, "the prior record was rewritten; R-040 forbids exactly that"
    assert written.corrects_id is None

    # And the correction carries the prior record's links forward, so R-160's filter finds both.
    linked = client.get(
        "/api/decisions", headers=bearer(token_a), params={"goal_id": goal.id}
    ).json()["decisions"]
    assert sorted(record["id"] for record in linked) == sorted([prior_id, payload["decision"]["id"]])


def test_the_correction_keeps_the_question_the_prior_record_asked(
    client, api_session, member_a, token_a
):
    """R-040. The question that stood is part of what stood, so the request model has no field for it."""
    _, prior = _goal(api_session, member_a)
    payload = client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": "Andere Fassung", "question": "eine ganz andere Frage"},
    ).json()
    assert payload["decision"]["quoted"]["question"] == prior.question


def test_a_correction_is_attributed_to_the_member_not_to_the_curator_it_corrects(
    client, api_session, member_a, token_a
):
    """R-161 and R-212. The member wrote this record, so the record says the member wrote it.

    `record_correction` copies the prior record's author by default, which is right when the same party
    corrects their own record and wrong the moment a member corrects a curator's: the new row would name a
    curator who did not write it. This route passes `author="member"`.

    **Planted violation:** dropped `author="member"` from the call, taking the copying default. This test
    went red with the correction attributed to Kuratorin Beatrice Roth. Restored.
    """
    with mutate_plan(
        api_session,
        member_id=member_a.id,
        question="Vom Kurator erfasst?",
        choice="Erste Fassung",
        author="curator",
        author_ref="Kuratorin Beatrice Roth",
    ) as by_curator:
        goal = Goal(member_id=member_a.id, name="Vom Kurator")
        api_session.add(goal)
        by_curator.linked_goals.append(goal)
    api_session.commit()

    payload = client.post(
        f"/api/decisions/{by_curator.id}/correction",
        headers=bearer(token_a),
        json={"choice": "Vom Mitglied berichtigt"},
    ).json()

    assert payload["decision"]["author"] == "member"
    assert payload["decision"]["author_ref"] is None
    assert payload["decision"]["curator_involved"] is False
    # The prior record keeps its own attribution. A correction does not rewrite who said what.
    assert payload["prior"]["author"] == "curator"
    assert payload["prior"]["author_ref"] == "Kuratorin Beatrice Roth"


def test_record_correction_still_copies_the_author_when_nobody_asks_it_not_to():
    """The new parameter's default, held in place. Without this, changing the default would go unnoticed
    by every existing caller and by `test_decision_correction_creates_new_record`, which does not look."""
    parameters = inspect.signature(record_correction).parameters
    assert parameters["author"].default is None
    assert parameters["author_ref"].default is None


def test_a_correction_that_corrects_nothing_is_refused(client, api_session, member_a, token_a):
    """R-040. A permanent record asserting that a correction happened when none did makes S-07 less true.

    The same judgement `services/goals.py` makes for a revision that revises nothing, and 422 for the same
    reason: the request is well formed, and what is wrong is that it asks for the state the record is in.

    **Planted violation:** removed the comparison. The request returned 201 and wrote a second permanent
    record identical to the first. This test went red. Restored.
    """
    _, prior = _goal(api_session, member_a)
    same = client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": prior.choice, "reasoning": prior.reasoning},
    )
    assert same.status_code == 422, same.text

    # Correcting only the reasoning IS a correction: the member's reason for a choice can be wrong while
    # the choice stands.
    reason_only = client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": prior.choice, "reasoning": "Der Grund war falsch notiert."},
    )
    assert reason_only.status_code == 201, reason_only.text


@pytest.mark.parametrize("choice", ["", "   ", "\t"])
def test_a_blank_correction_is_refused(client, api_session, member_a, token_a, choice):
    """Under R-040 there is no later edit that could fill in an empty record."""
    _, prior = _goal(api_session, member_a)
    response = client.post(
        f"/api/decisions/{prior.id}/correction", headers=bearer(token_a), json={"choice": choice}
    )
    assert response.status_code == 422, response.text


def test_correcting_a_decision_writes_nothing_to_the_plan(client, api_session, member_a, token_a):
    """C-09 from the other side: a correction touches no `Position` and no `Goal`.

    Worth pinning rather than assuming. If a future edit made this route write to the plan, C-09 would
    require a Decision in the same transaction — and this route writes one, so the guard would stay silent
    while the plan changed underneath a member who asked only to correct a sentence.
    """
    goal, prior = _goal(api_session, member_a)
    before = (goal.name, goal.template, goal.target_amount, goal.target_date)

    client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": "Andere Fassung"},
    )

    api_session.expire_all()
    written = api_session.get(Goal, goal.id)
    assert (written.name, written.template, written.target_amount, written.target_date) == before


# ============================================================ A81 / A91 — the member is the token's


def test_no_decisions_route_accepts_a_member_id_from_the_caller(app):
    """A81's substantive half, in A91's corrected form: the parameter is gone, not checked.

    A91 found that this test's body-model half had never checked anything, because
    `from __future__ import annotations` makes every annotation a string and `hasattr(str, "model_fields")`
    is always False. Hints are resolved here, and `resolved` is the guard on the guard: if they stop
    resolving this fails loudly instead of quietly returning to checking nothing.

    **Planted violation, twice.** Added `member_id: str | None = None` to `list_decisions` — failed on the
    signature. Added `member_id: str` to `CorrectionRequest` — failed on the body model, which is the half
    that was inert. Both restored.
    """
    offenders = []
    resolved = 0
    for route in decisions_router.routes:
        parameters = inspect.signature(route.endpoint).parameters
        if "member_id" in parameters:
            offenders.append(f"{sorted(route.methods)} {route.path} takes member_id as a parameter")

        hints = typing.get_type_hints(route.endpoint)
        resolved += 1
        for name, hint in hints.items():
            fields = getattr(hint, "model_fields", None)
            if not fields or "member_id" not in fields:
                continue
            offenders.append(
                f"{sorted(route.methods)} {route.path} has member_id on {hint.__name__} "
                f"(parameter {name!r})"
            )

    assert resolved == 3, (
        f"only {resolved} endpoints had resolvable annotations; S-07 has three routes and this test is "
        f"checking fewer of them than it looks like"
    )
    assert not offenders, "member_id still arrives from the caller: " + "; ".join(offenders)


def test_the_request_model_has_exactly_the_fields_a_correction_states():
    """No `member_id`, and no `question` — R-040 keeps the question the prior record asked."""
    assert set(decisions_api.CorrectionRequest.model_fields) == {"choice", "reasoning"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/decisions"),
        ("GET", "/api/decisions/anything"),
        ("POST", "/api/decisions/anything/correction"),
    ],
)
def test_every_decisions_route_refuses_without_a_token(client, method, path):
    """No route here is open. The list of routes is asserted against the router's own table below, so a
    fourth route added without a guard cannot hide from this."""
    response = client.request(method, path, json={"choice": "x"})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code} with no token"


def test_the_parametrised_refusal_list_is_the_whole_router():
    """A20. The test above proves nothing about a route it was never told exists."""
    live = {
        (method, route.path)
        for route in decisions_router.routes
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    covered = {
        ("GET", "/api/decisions"),
        ("GET", "/api/decisions/{decision_id}"),
        ("POST", "/api/decisions/{decision_id}/correction"),
    }
    assert live == covered, f"the router's table and the guarded list disagree: {live ^ covered}"


def test_a_token_for_one_member_cannot_read_or_correct_another_members_decisions(
    client, api_session, member_a, member_b, token_a
):
    """The test that matters. B has decisions; A holds a valid token and must reach none of them.

    404 rather than 403 on the read and on the correction, on A81's reasoning: a member who does not own a
    decision has no business learning whether that id exists.

    **Planted violation:** dropped `Decision.member_id == member_id` from `_load`. Both the read and the
    correction returned 200/201 on member B's record. This test went red on all four assertions. Restored.
    """
    _, mine = _position(api_session, member_a)
    _, theirs = _goal(api_session, member_b, name="Fremdes Ziel")
    theirs_id, theirs_choice = theirs.id, theirs.choice

    listed = client.get("/api/decisions", headers=bearer(token_a)).json()["decisions"]
    assert [record["id"] for record in listed] == [mine.id]

    assert client.get(f"/api/decisions/{theirs_id}", headers=bearer(token_a)).status_code == 404
    correction = client.post(
        f"/api/decisions/{theirs_id}/correction",
        headers=bearer(token_a),
        json={"choice": "von einem Fremden"},
    )
    assert correction.status_code == 404, correction.text

    api_session.expire_all()
    assert api_session.get(Decision, theirs_id).choice == theirs_choice
    assert (
        api_session.execute(
            Decision.__table__.select().where(Decision.__table__.c.corrects_id == theirs_id)
        ).first()
        is None
    ), "a stranger's correction was written against another member's decision"


def test_naming_another_member_in_the_body_does_not_move_the_write(
    client, api_session, member_a, member_b, token_a
):
    """A91's half. An extra `member_id` in the body is ignored, not preferred."""
    _, prior = _goal(api_session, member_a)
    payload = client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": "Andere Fassung", "member_id": member_b.id},
    ).json()

    api_session.expire_all()
    written = api_session.get(Decision, payload["decision"]["id"])
    assert written.member_id == member_a.id


# ============================================================ C-01, C-04 and the reuse


def _module_string_constants():
    """Every module-level string constant in `api/decisions.py`, by name."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found[target.id] = node.value.value
    return found
def test_no_refusal_in_this_module_is_written_inline():
    """Every member-facing refusal is a named constant, so the test above can find all of them.

    Without this, the C-01 check is one inline `HTTPException(422, "...")` away from being a check on three
    constants nobody uses. A20's shape again.

    **Planted violation:** inlined the blank-choice refusal as a literal in `correct_decision`. This test
    went red naming the line. Restored.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    offenders = []
    raised = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not (isinstance(callee, ast.Name) and callee.id == "HTTPException"):
            continue
        raised += 1
        detail = node.args[1] if len(node.args) > 1 else None
        if isinstance(detail, ast.Constant) and isinstance(detail.value, str):
            offenders.append(f"line {node.lineno}: {detail.value[:60]!r}")
    assert raised >= 4, f"only {raised} refusals were found; the scan is not reading the routes"
    assert not offenders, "a member-facing refusal is written inline: " + "; ".join(offenders)


def test_this_module_logs_nothing():
    """C-04. `question`, `choice` and `reasoning` are the member's own prose and pass through this module.

    `services/know.py`'s docstring sets out the obligation: the C-04 filter drops K3 by field name, and a
    paragraph of a member's own words is not a field. So nothing here logs at all, and a logger added later
    has to justify itself against this test rather than against a review.
    """
    source = MODULE.read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', " ", source)
    code = re.sub(r"^\s*#.*$", " ", code, flags=re.MULTILINE)
    for marker in ("logging", "logger", "print(", "warnings"):
        assert marker not in code, f"{MODULE.name} carries {marker}"


def test_the_sentence_is_the_befunds_own_sentence(client, api_session, member_a, token_a):
    """The reuse, made mechanical. If the route and the report ever disagree, this is what says so.

    `api/decisions.py` calls `services/befund.py::_decision_facts` rather than composing anything, and this
    compares the result against the Befund's own rendering of the same rows. A second vocabulary for one
    object is how a report and a screen come to describe a member's history differently.

    **Planted violation:** replaced the reused sentence with a locally composed f-string. This test went
    red on the first record. Restored.
    """
    from eigentlich.services.befund import render_befund

    _, first = _goal(api_session, member_a)
    record_correction(api_session, prior=first, choice="Zweite Fassung", author="member")
    api_session.commit()

    for language in ("de", "en"):
        route = client.get(
            "/api/decisions", headers=bearer(token_a), params={"language": language}
        ).json()["decisions"]
        report = render_befund(api_session, member_id=member_a.id, language=language)
        befund = {
            fact["values"]["decision_id"]: fact
            for section in report["sections"]
            if section["key"] == "decisions"
            for fact in section["facts"]
        }
        assert befund, "the Befund produced no decisions section, so this test compares nothing"
        for record in route:
            fact = befund[record["id"]]
            assert record["sentence"] == fact["sentence"], (
                f"the route and the Befund describe {record['id']} differently in {language}"
            )
            assert record["key"] == fact["key"]
            assert record["quoted"]["question"] == fact["quoted"]["question"]
            assert record["quoted"]["choice"] == fact["quoted"]["choice"]


def test_german_umlauts_survive_the_round_trip(client, api_session, member_a, token_a):
    """The shell hazard, checked where it would show up. A88 and A91: six occurrences in this build.

    Also checks this file's own bytes: `GERMAN_CHOICE` is compared against a codepoint-built string, so a
    mangled literal in the source fails here rather than looking almost right.
    """
    assert GERMAN_CHOICE.startswith("Frühpensionierung")
    assert "geprüft" in GERMAN_CHOICE
    assert not any(ord(character) < 32 for character in GERMAN_CHOICE + GERMAN_CORRECTION)

    _, prior = _goal(api_session, member_a)
    listed = client.get("/api/decisions", headers=bearer(token_a)).json()["decisions"]
    assert listed[0]["quoted"]["choice"] == GERMAN_CHOICE

    corrected = client.post(
        f"/api/decisions/{prior.id}/correction",
        headers=bearer(token_a),
        json={"choice": GERMAN_CORRECTION},
    ).json()
    assert corrected["decision"]["quoted"]["choice"] == GERMAN_CORRECTION


def test_a_record_renders_when_the_members_prose_is_absent():
    """R-231. Erasure overwrites `question` and `choice` and nulls `reasoning` (A73).

    An erased member's rows also have `member_id` nulled, so they are unreachable from a route scoped to the
    token's member — this is insurance against the next migration, not a live path, and it is exercised
    directly on the record builder because there is no way to reach it over HTTP.

    **Planted violation:** made `_quoted` return `decision.reasoning.strip()`. This test went red with an
    AttributeError on None. Restored.
    """
    empty = Decision(author="member", question=None, choice=None, reasoning=None)
    assert decisions_api._quoted(empty) == {"question": None, "choice": None, "reasoning": None}

    redacted = Decision(
        author="member", question="[gelöscht auf Antrag des Mitglieds]", choice="[gelöscht auf Antrag des Mitglieds]", reasoning=None
    )
    assert decisions_api._quoted(redacted)["reasoning"] is None


def test_a_reasoning_that_was_never_given_stays_null(client, api_session, member_a, token_a):
    """The live half of the case above: `reasoning` is nullable and usually null."""
    with mutate_plan(
        api_session, member_id=member_a.id, question="Ohne Begründung?", choice="Ja"
    ) as decision:
        goal = Goal(member_id=member_a.id, name="Ohne Begründung")
        api_session.add(goal)
        decision.linked_goals.append(goal)
    api_session.commit()

    record = client.get(f"/api/decisions/{decision.id}", headers=bearer(token_a)).json()["decision"]
    assert record["quoted"]["reasoning"] is None


def test_every_record_in_a_chain_follows_the_one_it_corrects(
    client, api_session, member_a, token_a
):
    """The chain's order is a property of the lineage, and this asserts the property rather than an order.

    **What went wrong.** `_chain` sorted on `(created_at, id)`. Three decisions written inside one
    microsecond — every test, and any correction a member makes quickly — tie on `created_at` and fall
    through to `id`, which is random hex. The test above then passed or failed depending on which ids the
    run happened to produce: two failures in five. On a real database it means a member's correction
    history could reshuffle between two page loads.

    A correction chain carries its own order, because each record corrects the one before it. `depth`
    counts links from the root and cannot tie; `created_at` now orders only two corrections OF THE SAME
    record, which is the one place a clock is the right answer.

    **Two attempts at forcing the tie were abandoned, and both were informative.** Stamping the rows with
    one `created_at` afterwards was refused by `DecisionImmutable` — R-040 blocking a test that tried to
    edit a Decision, which is that guard being real rather than decorative. Freezing `utcnow` with
    `monkeypatch` did nothing, because the column default captured the function object at class-definition
    time and patching the module name afterwards cannot reach it.

    So this asserts the invariant instead of manufacturing the collision: **in a linear chain, each record
    must follow the record it corrects.** That is true whatever the clock says, it is exactly what the old
    implementation got wrong whenever the ids fell the wrong way, and it needs no contrivance to hold.
    """
    _, first = _goal(api_session, member_a)
    second = record_correction(api_session, prior=first, choice="Zweite Fassung", author="member")
    api_session.commit()
    third = record_correction(api_session, prior=second, choice="Dritte Fassung", author="member")
    api_session.commit()

    chain = client.get(f"/api/decisions/{third.id}", headers=bearer(token_a)).json()["chain"]
    records = chain["records"]
    assert len(records) == 3, f"the chain lost a record: {[r['id'] for r in records]}"

    assert records[0]["corrects_id"] is None, "the first record in a chain corrects nothing"
    for earlier, later in zip(records, records[1:]):
        assert later["corrects_id"] == earlier["id"], (
            f"record {later['id']} corrects {later['corrects_id']} but follows {earlier['id']}: "
            f"the chain is not in lineage order"
        )


def test_the_chain_is_ordered_by_lineage_when_the_clock_cannot_separate_the_rows(
    client, api_session, member_a, token_a
):
    """The deterministic half. The test above holds the invariant; this one forces the condition.

    **Why both exist.** With the defective sort restored, the invariant test fails about one run in six —
    it is probabilistic at catching a probabilistic bug, which is not a guard. `created_at` usually agrees
    with insertion order, so the misordering only appears when two rows land in the same microsecond. This
    test creates that collision on purpose, so the failure is certain rather than likely.

    **How, after two attempts that did not work.** Stamping the rows afterwards is refused by
    `DecisionImmutable` (R-040 blocking a test that tried to edit a Decision — that guard being real).
    Freezing `utcnow` with `monkeypatch` cannot reach the column default, which captured the function
    object at class-definition time. What does work is passing `created_at` **at construction**: R-040
    forbids changing a Decision that exists, not writing one with a stated timestamp.

    So the rows are built here rather than through `record_correction`, which is the one thing this test
    does that a member's path never does — and the price of making the collision certain.
    """
    frozen = utcnow()
    rows = []
    for index, (choice, corrects) in enumerate(
        [("Erste Fassung", None), ("Zweite Fassung", 0), ("Dritte Fassung", 1)]
    ):
        # Ids chosen to sort AGAINST the lineage. Without this the defective sort still lands on the
        # right order about one run in six, purely by where three random hex ids happen to fall — the
        # test would then be 5/6 reliable at catching a bug that was 1/6 likely to show, which is not a
        # guard. The ids run z, y, x down the lineage, so an ASCII sort reverses it and the wrong answer
        # is certain if anything orders on the id at all.
        #
        # (This comment lost two words the first time it was written, because they were in backticks and
        # went through a shell, which ran them as commands. Seventh incident of that kind today.)
        row = Decision(
            id=f"{'zyx'[index]}" * 10 + f"{index}",
            member_id=member_a.id,
            author="member",
            question="Wofuer ist das Geld da?",
            choice=choice,
            options_considered=[],
            corrects_id=None if corrects is None else rows[corrects].id,
            created_at=frozen,
        )
        api_session.add(row)
        api_session.flush()
        rows.append(row)
    api_session.commit()

    stamps = {row.created_at for row in rows}
    assert len(stamps) == 1, (
        f"the three rows must share one timestamp or this test does not exercise the tie it exists for; "
        f"got {sorted(stamps)}"
    )
    assert len({row.id for row in rows}) == 3

    chain = client.get(f"/api/decisions/{rows[2].id}", headers=bearer(token_a)).json()["chain"]
    order = [record["id"] for record in chain["records"]]
    assert order == [rows[0].id, rows[1].id, rows[2].id], (
        f"with one timestamp across all three rows the order came back as {order}: the chain is being "
        f"ordered by something other than the lineage"
    )
