"""S-13 community: R-220, R-221 and R-222.

Two of the three are absences — no score anywhere a member can see, no gathering ever called an event — so
each filter here carries a guard that it can still fail. `test_content.py` and A20 are the reason that is a
habit in this codebase rather than a precaution.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

import eigentlich.models as models
from eigentlich.api.remainder import get_session, router
from eigentlich.db import create_all, make_session_factory
from eigentlich.models import Attendance, GATHERING_KINDS, Gathering
from eigentlich.services import register_member
from eigentlich.services.auth import login, register_with_credentials
from conftest import session_overrides
from eigentlich.services.community import (
    FORBIDDEN_GATHERING_WORDS,
    GatheringCalledAnEvent,
    _forbidden_words,
    create_gathering,
    gatherings,
    presence_evidence,
    record_attendance,
)

SOURCES = [
    Path(__file__).resolve().parent.parent / "eigentlich" / "services" / "community.py",
    Path(__file__).resolve().parent.parent / "eigentlich" / "api" / "remainder.py",
]

#: R-221. Anything a member could read as a tally. Matched as substrings of the key, because these are
#: identifiers this build chooses and `attendance_total` should fail on either half.
#:
#: `attended` is deliberately absent: whether a member was at a gathering is a fact about that gathering,
#: and R-221 forbids the score, not the memory. The tally is what it forbids.
SCORE_KEY_FRAGMENTS = (
    "count",
    "total",
    "streak",
    "score",
    "points",
    "rank",
    "standing",
    "presence",
    "percent",
    "share_of",
    "tally",
    "badge",
)


def _all_keys(node) -> list[str]:
    if isinstance(node, dict):
        return [k for key, value in node.items() for k in [key, *_all_keys(value)]]
    if isinstance(node, list):
        return [k for value in node for k in _all_keys(value)]
    return []


def _tallies(node) -> list[str]:
    """Keys that look like a score and carry something a member could read as one.

    **A boolean is exempt, and that exemption is the point of the filter rather than a hole in it.**
    `attendance_is_not_scored: true` is a denial — the payload saying out loud what R-221 forbids, the
    same move `learning_path` makes with `units_are_not_gated`. What R-221 forbids reaching a member is a
    *number*: a count, a total, a streak, a share. So a matching key fails on any value except a bool.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if any(f in key.lower() for f in SCORE_KEY_FRAGMENTS) and not isinstance(value, bool):
                found.append(key)
            found.extend(_tallies(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_tallies(value))
    return found


def _identifiers(path: Path) -> list[str]:
    """Every name this module chooses: functions, classes, arguments, variables, attributes.

    **String constants are excluded on purpose.** `community.py` raises an error that quotes R-222, and a
    message explaining a rule has to be able to name the word it forbids — the same allowance `_about`
    gets in the content files and docstrings get from `_code_only`. What a member actually reads is
    checked against the payloads instead, which is where it would reach them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return names


def _all_strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _all_strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _all_strings(value)]
    return []


def _code_only(path: Path) -> str:
    """One module's source with comments and docstrings removed — `test_learning.py`'s helper.

    This module's own docstrings quote the word R-222 forbids; a filter that fired on the explanation of
    the rule would be a filter somebody removes.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    return ast.unparse(tree).lower()


@pytest.fixture()
def programme(session, member):
    """Three gatherings, one of each kind, and the member at two of them."""
    lecture = create_gathering(
        session, kind="lecture", title="Was eine Police wirklich kostet",
        held_on=date(2026, 9, 3), location="Zürich", fictional=True,
    )
    evening = create_gathering(
        session, kind="cafe_evening", title="Café-Abend: Fragen aus dem Vorsorgeausweis",
        held_on=date(2026, 9, 17), fictional=True,
    )
    meetup = create_gathering(
        session, kind="meetup", title="Treffen der Selbständigen",
        held_on=date(2026, 10, 1), fictional=True,
    )
    session.flush()
    record_attendance(session, member_id=member.id, gathering_id=lecture.id)
    record_attendance(session, member_id=member.id, gathering_id=evening.id)
    session.commit()
    return member, lecture, evening, meetup


@pytest.fixture()
def api(fast_kdf):
    """The router on its own app and its own database. Yields `(client, member_id)` — see test_stages.py.

    Authenticated: A11 was wired on 31 August 2026, so `member_id` is no longer a query parameter or a
    body field on any of these routes and the client carries a bearer token instead.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    with make_session_factory(engine)() as api_session:
        member, _ = register_with_credentials(
            api_session,
            email="router@example.ch",
            password="ein ziemlich langes passwort",
            age_at_registration=41,
            display_name="Router Member",
        )
        api_session.commit()
        _, token = login(
            api_session, email="router@example.ch", password="ein ziemlich langes passwort"
        )
        api_session.commit()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update(session_overrides(api_session))
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, member.id
    engine.dispose()


# ============================================================ R-220


def test_three_kinds_of_gathering():
    """R-220. Lectures, café evenings and meet-ups — the three the specification names, and no more."""
    assert GATHERING_KINDS == ("lecture", "cafe_evening", "meetup")


def test_a_gathering_is_scheduled_with_attendance(session, programme):
    member, lecture, evening, meetup = programme
    payload = gatherings(session, member_id=member.id)
    by_title = {g["title"]: g for g in payload["gatherings"]}
    assert by_title["Was eine Police wirklich kostet"]["attended"] is True
    assert by_title["Treffen der Selbständigen"]["attended"] is False


def test_gatherings_come_back_in_date_order(session, programme):
    member, *_ = programme
    held = [g["held_on"] for g in gatherings(session, member_id=member.id)["gatherings"]]
    assert held == sorted(held)


def test_an_unknown_kind_is_refused(session):
    with pytest.raises(ValueError):
        create_gathering(session, kind="webinar", title="Etwas", held_on=date(2026, 9, 3))


def test_attendance_is_recorded_once_per_member_and_gathering(session, programme):
    """Attending twice is not something that happened twice — and a second row is where a tally starts."""
    member, lecture, *_ = programme
    record_attendance(session, member_id=member.id, gathering_id=lecture.id)
    session.commit()
    rows = session.execute(
        select(Attendance).where(
            Attendance.member_id == member.id, Attendance.gathering_id == lecture.id
        )
    ).scalars().all()
    assert len(rows) == 1


def test_attendance_can_be_corrected_to_absent(session, programme):
    member, lecture, *_ = programme
    record_attendance(session, member_id=member.id, gathering_id=lecture.id, attended=False)
    session.commit()
    by_id = {g["id"]: g for g in gatherings(session, member_id=member.id)["gatherings"]}
    assert by_id[lecture.id]["attended"] is False


def test_a_member_without_attendance_sees_the_programme(session, member):
    """Design for one position, not four (principle 3): an empty history renders, it does not throw."""
    payload = gatherings(session, member_id=member.id)
    assert payload["gatherings"] == []
    assert payload["kinds"] == list(GATHERING_KINDS)


# ============================================================ R-221


def test_no_member_facing_payload_carries_a_score(session, programme):
    """R-221. Attendance is recorded and is never shown to the member as a score.

    No count, no total, no streak, no share, no standing — in the keys, at any depth.
    """
    member, *_ = programme
    payload = gatherings(session, member_id=member.id)
    assert not _tallies(payload), f"R-221: the community payload carries {_tallies(payload)}"


def test_the_score_key_filter_actually_matches():
    """A guard on the guard: healthy and broken both look like an empty list."""
    fake = {"gatherings": [{"attendance_count": 4, "presence_score": 0.8, "attended": True}]}
    assert set(_tallies(fake)) == {"attendance_count", "presence_score"}
    # And the denial the payload actually carries is not mistaken for one of them.
    assert _tallies({"attendance_is_not_scored": True}) == []


def test_the_attendance_table_has_no_column_to_build_a_score_from(session):
    """R-221 held by the schema as well as by the payload — see the model's own docstring."""
    columns = set(Attendance.__table__.columns.keys())
    assert not (columns & {"count", "total", "streak", "score", "points", "rank"})


def test_the_http_payloads_carry_no_score(api):
    """The same filter over what actually reaches a browser."""
    client, member_id = api
    created = client.post(
        "/api/community/gatherings",
        json={"kind": "lecture", "title": "Was eine Police kostet", "held_on": "2026-09-03"},
    ).json()
    recorded = client.post(
        "/api/community/attendance",
        json={"member_id": member_id, "gathering_id": created["id"]},
    ).json()
    listed = client.get("/api/community/gatherings", params={"member_id": member_id}).json()

    for payload in (created, recorded, listed):
        assert not _tallies(payload), f"R-221: {_tallies(payload)} reached the browser"
    assert listed["attendance_is_not_scored"] is True


def test_presence_evidence_is_recorded_facts_and_is_not_exposed_over_http(session, programme):
    """R-221's other half, and C-08's third permitted ranking input.

    It exists — attendance really is an input to Market Place standing — and it returns the attendances
    rather than a number, so that the one function standing depends on has no tally in it for a payload to
    pick up. And no route returns it: the router does not import it.
    """
    member, lecture, evening, _meetup = programme
    evidence = presence_evidence(session, member_id=member.id)
    assert {e["gathering_id"] for e in evidence} == {lecture.id, evening.id}
    assert all(set(e) == {"gathering_id", "kind", "held_on"} for e in evidence)

    assert "presence_evidence" not in _code_only(SOURCES[1]), (
        "R-221: standing is not a member-facing payload, so it has no route. (Checked against the code "
        "rather than the file: the router's docstring says where the ranking side lives, and should.)"
    )


# ============================================================ R-222


def test_the_model_is_not_called_an_event():
    """R-222 in the schema. `models/access.py` says it: the name is the enforcement."""
    assert not hasattr(models, "Event")
    assert Gathering.__tablename__ == "gatherings"


def test_no_community_payload_uses_the_word_event(session, programme):
    """R-222. "Events" in the interface means LIFE events (S-09). A gathering is a lecture, an evening or
    a meet-up — in the keys and in the strings, at any depth."""
    member, *_ = programme
    payload = gatherings(session, member_id=member.id)
    haystack = " ".join(_all_keys(payload) + _all_strings(payload)).lower()
    found = _forbidden_words(haystack)
    assert not found, f"R-222: the community payload calls a gathering {found}"


def test_no_http_community_payload_uses_the_word_event(api):
    client, member_id = api
    created = client.post(
        "/api/community/gatherings",
        json={"kind": "meetup", "title": "Treffen der Selbständigen", "held_on": "2026-10-01"},
    ).json()
    client.post("/api/community/attendance",
                json={"member_id": member_id, "gathering_id": created["id"]})
    listed = client.get("/api/community/gatherings", params={"member_id": member_id}).json()

    haystack = " ".join(_all_keys(listed) + _all_strings(listed)).lower()
    assert not _forbidden_words(haystack)


def test_a_gathering_titled_as_an_event_is_refused(session):
    """R-222 enforced where the words actually come from: whoever schedules the gathering names it.

    Refused rather than rewritten — only the person scheduling it knows what it should be called instead.
    """
    for title in ("Event: Vorsorge", "Anlass für Mitglieder", "Veranstaltung im Herbst"):
        with pytest.raises(GatheringCalledAnEvent):
            create_gathering(session, kind="lecture", title=title, held_on=date(2026, 9, 3))


def test_a_description_calling_it_an_event_is_refused_too(session):
    with pytest.raises(GatheringCalledAnEvent):
        create_gathering(
            session, kind="lecture", title="Was eine Police kostet", held_on=date(2026, 9, 3),
            description="Ein Event für alle Mitglieder.",
        )


def test_the_api_refuses_it_with_422(api):
    client, _ = api
    response = client.post(
        "/api/community/gatherings",
        json={"kind": "lecture", "title": "Event im Herbst", "held_on": "2026-09-03"},
    )
    assert response.status_code == 422
    assert "R-222" in response.json()["detail"]


def test_the_forbidden_word_filter_matches_whole_words_only():
    """A guard on the guard, and on its boundaries.

    Substring matching would fire on `Eventualverbindlichkeit` and on any compound built from `Anlass`,
    and a filter that damages good copy is one somebody eventually deletes — the three false positives
    `test_content.py` records are the precedent.
    """
    assert _forbidden_words("ein Event im Herbst") == ["event"]
    assert _forbidden_words("Anlass für Mitglieder") == ["anlass"]
    assert _forbidden_words("die Eventualverbindlichkeit") == [], "must not fire inside a compound"
    assert _forbidden_words("Veranstaltungsreihe") == [], "must not fire inside a compound"
    assert _forbidden_words(None) == []
    assert "event" in FORBIDDEN_GATHERING_WORDS


def test_the_word_life_events_is_still_available_to_life_events():
    """The rule is about what a gathering is called, not a ban on the word.

    S-09's modules are life events and the route that serves them says so. This test exists so that a
    later, blunter reading of R-222 does not rename the thing the requirement is protecting.
    """
    router_source = SOURCES[1].read_text(encoding="utf-8")
    assert "/life-events" in router_source


def test_nothing_in_the_phase_eight_source_is_named_after_an_event():
    """The same rule over the names this phase's own code chooses.

    A variable called `event` would put the word into every stack trace and, eventually, into a payload.
    Names only: see `_identifiers` for why the error message that quotes R-222 is allowed to quote it.
    """
    for path in SOURCES:
        # The life-event routes legitimately carry the word; strip those names before checking.
        body = re.sub(r"life[_-]event[s]?", " ", " ".join(_identifiers(path)).lower())
        found = [
            w for w in FORBIDDEN_GATHERING_WORDS if re.search(r"\b" + re.escape(w) + r"\b", body)
        ]
        assert not found, f"R-222: {path.name} names something {found}"


def test_the_identifier_scan_actually_reads_the_module():
    """A guard on the guard: an empty name list would make the test above pass on any source at all."""
    names = _identifiers(SOURCES[0])
    assert "create_gathering" in names and "record_attendance" in names
    assert _identifiers(SOURCES[1]), "the router yielded no identifiers"


# ============================================================ A41


def test_a_seeded_gathering_marks_itself_fictional(session, programme):
    """A41. Demonstration content says so in the data, so a screenshot cannot be mistaken for a programme."""
    member, *_ = programme
    assert all(g["fictional"] is True for g in gatherings(session, member_id=member.id)["gatherings"])


def test_a_real_gathering_is_not_marked_fictional(session):
    gathering = create_gathering(
        session, kind="lecture", title="Was eine Police kostet", held_on=date(2026, 9, 3)
    )
    session.commit()
    assert gathering.fictional is False


def test_the_payload_is_json_serialisable(session, programme):
    """It travels over HTTP; a date object that never serialised would be found by a member, not by us."""
    member, *_ = programme
    json.dumps(gatherings(session, member_id=member.id))
