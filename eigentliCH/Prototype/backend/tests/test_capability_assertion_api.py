"""D-01's answer as a route (A82), and the R-005 gate it makes satisfiable.

**What was broken.** `services.learning.record_assertion` was the only way a `CapabilityAssertion` could
come into existence and it had no route, because `api/learning.py` was withholding one until D-01 had an
owner. D-01 was answered on 31 August 2026 — A82: the member's own self-assessment — and the reason
expired. The consequence was not cosmetic: `POST /api/marketplace/applications` answered **every** real
member with a 403 `InsufficientCapabilityEvidence`, and `capability_evidence` was permanently 0 in R-203's
ordering inputs. The most carefully guarded module in the build could not be entered by anybody.

**The two halves this module holds.**

  1. *The route records a claim and never an assessment* — D-01, C-07, R-194. `evidence_kind` and
     `assessed_by` come from server constants, `evidence_ref` can only hold a reference the content
     corroborates, and `rung` stays null. Several of those are absence-shaped, so each carries a guard
     that it can still fail.
  2. *R-005 is now satisfiable, and C-08 did not regress* — a real member completes an application end to
     end, `capability_evidence` becomes non-zero for the first time, and the ordering property A74 proved
     over declared/requested pairs still holds when the evidence side of it is real rather than seeded.

**Planted violations, each observed red and restored.** Recorded per test in its own docstring, in the
form this codebase uses: six guarantees here have been found unable to fail (A20, A63, A66, A68, A81, A91)
and all six were absence-shaped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from eigentlich.api import learning as learning_api
from eigentlich.api import marketplace as marketplace_api
from eigentlich.db import make_session_factory
from eigentlich.models import Capability, CapabilityAssertion, Decision, Position
from eigentlich.services.auth import login, register_with_credentials
from eigentlich.services.learning import (
    AlreadyAsserted,
    NoSuchCapability,
    NotEvidencedByThatUnit,
    SELF_ASSERTION_KIND,
    capability_review,
    record_self_assertion,
    self_assessed_by,
)
from eigentlich.services.learning import seed as seed_learning
from eigentlich.services.marketplace import (
    NO_FILTER,
    browse,
    listing_ordering_inputs,
    member_standing,
    role_match_share,
)
from eigentlich.services.plan import mutate_plan
from conftest import session_overrides

# The authorities for the word filters, imported rather than re-listed — the A91 lesson: two lists that
# must agree, maintained separately.
from test_content import GAMIFICATION_WORDS, _whole_words  # noqa: E402
from test_learning import TALLY_WORDS  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
LEARNING_API = BACKEND / "eigentlich" / "api" / "learning.py"

#: One capability, and one unit that genuinely evidences it (R-190).
CAPABILITY = "freizuegigkeitskonto_kosten"
UNIT_THAT_EVIDENCES_IT = "konten_die_liegen_bleiben"
#: A real unit that does NOT evidence the capability above. Read from the content in the guard below, so
#: this pair cannot go stale into a test that passes for the wrong reason.
UNIT_THAT_DOES_NOT = "was_ein_monat_kostet"

PASSWORD = "ein ziemlich langes passwort"


# ============================================================ fixtures


@pytest.fixture()
def api(api_engine, fast_kdf):
    """The learning and market place routers on one app. Yields `(client, member_id, session)`.

    **Both routers, deliberately.** The point of this module is that a route in one of them unblocks a
    route in the other, and an end-to-end test that could only reach half of that would be proving the
    half that was never broken.

    Not `eigentlich.api.main.app`: importing it opens the developer's real database file. `session_overrides`
    covers `api.auth.get_session` as well as both routers' — the token is resolved through that one, and
    overriding only the routers' would authenticate against `backend/eigentlich.db` (the A68 failure mode).
    """
    with make_session_factory(api_engine)() as db_session:
        member, _ = register_with_credentials(
            db_session,
            email="asserting@example.ch",
            password=PASSWORD,
            age_at_registration=39,
            display_name="Asserting Member",
        )
        seed_learning(db_session)
        db_session.commit()
        _, token = login(db_session, email="asserting@example.ch", password=PASSWORD)
        db_session.commit()

        app = FastAPI()
        app.include_router(learning_api.router)
        app.include_router(marketplace_api.router)
        app.dependency_overrides.update(session_overrides(db_session))
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client, member.id, db_session


def _register(db_session, *, email, name, age=41):
    member, _ = register_with_credentials(
        db_session, email=email, password=PASSWORD, age_at_registration=age, display_name=name
    )
    db_session.commit()
    _, token = login(db_session, email=email, password=PASSWORD)
    db_session.commit()
    return member, token


# ============================================================ the content pair this module rests on


def test_the_two_units_in_this_module_are_the_pair_it_claims_they_are():
    """Guard on every assertion below that uses them.

    If `UNIT_THAT_DOES_NOT` ever grew this capability, `test_a_unit_that_does_not_evidence_it_is_refused`
    would be asserting a refusal that should not happen and would fail loudly — but
    `test_a_learning_unit_reference_is_recorded_when_the_content_agrees` would silently start proving
    nothing. Reading the content here is cheaper than either.
    """
    from eigentlich.services.learning import unit

    assert CAPABILITY in unit(UNIT_THAT_EVIDENCES_IT)["capability_keys"]
    assert CAPABILITY not in unit(UNIT_THAT_DOES_NOT)["capability_keys"]


# ============================================================ what a self-assertion records


def test_a_member_asserts_a_capability_and_the_row_says_who_said_so(api):
    """D-01 / A82. The member is the one who says it, and the row records exactly that."""
    client, member_id, _ = api
    response = client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["capability_id"] == CAPABILITY
    assert body["evidence_kind"] == "member_self_assertion"
    assert body["assessed_by"] == f"member:{member_id}"
    assert body["self_asserted"] is True
    assert body["evidence_ref"] is None, "an assertion with no unit named stands on its own"


def test_assessed_by_names_the_member_and_never_andersch(api):
    """R-194 / A82. `assessed_by` is what a reader uses to decide what a claim is worth.

    eigentliCH's own name in it would be eigentliCH vouching for a statement it never examined — the claim of
    accredited standing R-194 forbids, made in a column rather than in copy. An absence-shaped rule, so
    the guard below proves the filter fires.

    **Planted violation:** `self_assessed_by` returning `"eigentlich"`. Failed on
    `assessed_by names eigentliCH`. Restored.
    """
    client, member_id, _ = api
    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    review = client.get("/api/capabilities").json()
    entry = next(c for c in review["capabilities"] if c["key"] == CAPABILITY)
    said_by = entry["evidence"][0]["assessed_by"]

    forbidden = ("eigentlich", "curator", "system", "admin")
    assert not [word for word in forbidden if word in said_by.lower()], (
        f"assessed_by names eigentliCH or one of its people: {said_by!r}"
    )
    assert said_by == self_assessed_by(member_id)
    # Guard on the filter: it has to be able to match. Without this, an empty `forbidden` or a said_by
    # that is somehow not a string would pass the check above silently.
    assert [word for word in forbidden if word in "assessed by eigentlich"] == ["eigentlich"]


def test_the_display_name_is_not_what_assessed_by_holds(api):
    """R-231. A display name is not an identity and the erasure empties it, so an `assessed_by` reading
    `member:Asserting Member` would survive the erasure of that member."""
    client, member_id, _ = api
    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    review = client.get("/api/capabilities").json()
    entry = next(c for c in review["capabilities"] if c["key"] == CAPABILITY)
    assert "Asserting Member" not in entry["evidence"][0]["assessed_by"]
    assert member_id in entry["evidence"][0]["assessed_by"]


def test_the_request_cannot_state_the_kind_the_assessor_or_a_rung(api):
    """C-07 / D-01, structurally **and** over the wire.

    `capability_review` renders `evidence_kind` and `assessed_by` straight back to a client, so a body
    that could set them is a body that could store a graded word and have it displayed. The model has no
    such fields; sending them anyway must change nothing.

    **Planted violation:** added `evidence_kind: str | None = None` to `SelfAssertionRequest` and passed
    it through. Failed on `SelfAssertionRequest accepts evidence_kind`. Removed.
    """
    fields = set(learning_api.SelfAssertionRequest.model_fields)
    for forbidden in ("evidence_kind", "assessed_by", "rung", "evidence_ref", "member_id", "assessed_at"):
        assert forbidden not in fields, f"SelfAssertionRequest accepts {forbidden}"
    # Guard on the scan: a model whose fields could not be read would pass the loop above for free.
    assert {"capability_id", "learning_unit"} <= fields, f"the field scan read {fields}"

    client, member_id, _ = api
    body = client.post(
        "/api/capabilities/assertions",
        json={
            "capability_id": CAPABILITY,
            "evidence_kind": "assessed at level three",
            "assessed_by": "eigentliCH, federally accredited",
            "rung": 3,
            "evidence_ref": "whatever the caller likes",
        },
    ).json()
    assert body["evidence_kind"] == "member_self_assertion"
    assert body["assessed_by"] == f"member:{member_id}"
    assert body["rung"] is None
    assert body["evidence_ref"] is None


def test_the_rung_stays_null_on_the_row_and_on_the_column(api):
    """D-01. `Capability.rung` is nullable with no default and no scheme, and asserting does not write it."""
    client, _, db_session = api
    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    row = db_session.get(Capability, CAPABILITY)
    assert row.rung is None
    # Guard: the column has to exist and be nullable, or "it is null" is a statement about nothing.
    column = Capability.__table__.columns["rung"]
    assert column.nullable is True
    assert column.default is None and column.server_default is None


def test_a_learning_unit_reference_is_recorded_when_the_content_agrees(api):
    """R-190. A member may point at the unit they worked through, and the reference is corroborated."""
    client, _, _ = api
    body = client.post(
        "/api/capabilities/assertions",
        json={"capability_id": CAPABILITY, "learning_unit": UNIT_THAT_EVIDENCES_IT},
    ).json()
    assert body["evidence_ref"] == f"learning.json#units.{UNIT_THAT_EVIDENCES_IT}"


def test_a_unit_that_does_not_evidence_it_is_refused(api):
    """R-190. A reference that does not hold reads as corroboration and is not one, so it is not stored.

    422 rather than 404: both the capability and the unit exist, and what is wrong is the claim that one
    evidences the other.
    """
    client, _, db_session = api
    response = client.post(
        "/api/capabilities/assertions",
        json={"capability_id": CAPABILITY, "learning_unit": UNIT_THAT_DOES_NOT},
    )
    assert response.status_code == 422, response.text
    assert db_session.execute(select(func.count()).select_from(CapabilityAssertion)).scalar_one() == 0


def test_an_unknown_capability_is_a_404_and_not_a_503(api):
    """A key nobody authored is the caller's mistake. 503 would answer "the server is broken" to a typo."""
    client, _, _ = api
    response = client.post("/api/capabilities/assertions", json={"capability_id": "not_a_capability"})
    assert response.status_code == 404, response.text


def test_an_unknown_learning_unit_is_a_404(api):
    client, _, _ = api
    response = client.post(
        "/api/capabilities/assertions",
        json={"capability_id": CAPABILITY, "learning_unit": "not_a_unit"},
    )
    assert response.status_code == 404, response.text


def test_asserting_the_same_capability_twice_is_refused(api):
    """C-07. R-191 makes the statement the whole progression: it is asserted or it is not.

    A second identical row could only ever be read as a number of them, which is the tally this product
    exists without — and `member_standing` de-duplicates for the ordering anyway, so it could be rendered
    and never used.
    """
    client, _, db_session = api
    assert client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY}).status_code == 201
    second = client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    assert second.status_code == 409, second.text
    assert db_session.execute(select(func.count()).select_from(CapabilityAssertion)).scalar_one() == 1


def test_a_second_capability_is_a_different_assertion(api):
    """The refusal above is per capability, not per member. A member may assert several things."""
    client, _, db_session = api
    for key in (CAPABILITY, "fixkosten_eines_monats", "franchise_rechnung"):
        assert client.post("/api/capabilities/assertions", json={"capability_id": key}).status_code == 201
    assert db_session.execute(select(func.count()).select_from(CapabilityAssertion)).scalar_one() == 3


def test_the_route_refuses_without_a_token(api):
    """A11. The write side of the learning surface is guarded like the read side."""
    client, _, _ = api
    response = client.post(
        "/api/capabilities/assertions",
        json={"capability_id": CAPABILITY},
        headers={"Authorization": ""},
    )
    assert response.status_code == 401, response.text


def test_a_member_cannot_assert_on_behalf_of_anybody_else(api):
    """A11's substantive half: the parameter is gone, not checked. There is nowhere to name someone else."""
    client, member_id, db_session = api
    other, _ = _register(db_session, email="other@example.ch", name="Other Member")
    client.post(
        "/api/capabilities/assertions",
        json={"capability_id": CAPABILITY, "member_id": other.id},
    )
    rows = db_session.execute(select(CapabilityAssertion)).scalars().all()
    assert [row.member_id for row in rows] == [member_id]


# ============================================================ C-09 — an assertion is not a plan mutation


def test_recording_an_assertion_writes_no_decision(api):
    """C-09 covers `positions` and `goals`. A capability assertion is a statement about the member.

    A Decision claiming a plan changed when none did is permanent under R-040 and makes S-07 less true, so
    the honest thing is not to write one. The permanent record is the assertion row itself.

    **Absence-shaped, so the second half is the guard**: a real plan mutation in the same session does
    write a Decision, which is what proves "no Decision" is a fact about this route rather than about a
    broken session.

    **Planted violation:** wrapped `record_self_assertion` in `mutate_plan`. The Decision count went to 1
    and this failed on `a self-assertion wrote a Decision`. Restored.
    """
    client, member_id, db_session = api
    assert client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY}).status_code == 201
    count = db_session.execute(select(func.count()).select_from(Decision)).scalar_one()
    assert count == 0, f"a self-assertion wrote a Decision ({count} of them)"

    with mutate_plan(
        db_session, member_id=member_id, question="Lohn erfassen?", choice="Ja"
    ) as decision:
        position = Position(
            member_id=member_id, role="income", capital_type="human", label="Lohn"
        )
        db_session.add(position)
        decision.linked_positions.append(position)
    db_session.commit()
    assert db_session.execute(select(func.count()).select_from(Decision)).scalar_one() == 1, (
        "the guard on this test: a real plan mutation must write a Decision here, or the count above "
        "proves nothing"
    )


# ============================================================ C-07 — the payload the route returns


def test_the_response_carries_no_gamification_or_tally_vocabulary(api):
    """C-07, R-113, R-006. A 201 on an assertion is the single most tempting place for a meter.

    **Two filters, because the prose one has a hole and planting found it.** `_whole_words` matches on
    `\\b`, and `_` is a word character, so `\\bcount\\b` does **not** fire inside `asserted_count` — and a
    payload *key* is exactly where a tally word arrives underscore-joined. The first plant below was
    accepted by the prose filter alone. So the keys are also split on `_` and each token is matched, which
    is what `test_learning.py`'s identifier scan does for source and nothing did for a payload.

    **Planted violations:** `"asserted_count": 1` — passed the prose filter, caught by the key scan;
    `"progress": 0.1` — caught by both. Both removed.
    """
    client, _, _ = api
    body = client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY}).json()
    blob = json.dumps(body, default=str).lower()

    found = _whole_words(GAMIFICATION_WORDS + ("rank", "daily_goal"), blob)
    assert not found, f"C-07: an assertion payload carries {found}"
    found = _whole_words(TALLY_WORDS, blob)
    assert not found, f"R-113: an assertion payload carries {found}"

    forbidden = set(GAMIFICATION_WORDS) | set(TALLY_WORDS) | {"rank"}
    tokens = {token for key in body for token in key.lower().split("_")}
    assert not tokens & forbidden, (
        f"C-07 / R-113: a payload key is built from {sorted(tokens & forbidden)}. `_whole_words` cannot "
        f"see it: `_` is a word character, so `\\bcount\\b` does not fire inside `asserted_count`."
    )

    # Guards on both filters, on this payload's own material rather than on a constructed string.
    assert _whole_words(("score",), blob + " score") == ["score"]
    assert {"count"} & forbidden, "the key filter's vocabulary is empty"
    assert {token for token in "asserted_count".split("_")} & forbidden == {"count"}


def test_the_201_makes_no_claim_of_qualification(api):
    """R-194 / NG-04. A 201 is the moment a member is most likely to read a pass into it."""
    client, _, _ = api
    body = client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY}).json()
    assert body["qualification_claim"] is None
    assert body["qualification_claim_reason"] == "eigentlich_states_capabilities_only"
    assert body["eigentlich_assesses_capabilities"] is False
    assert body["rung_scheme"] is None


def test_the_route_source_names_no_rung_scheme():
    """D-01 structurally. The route may not acquire a vocabulary for grading, in code or in a payload key.

    Docstrings and comments are **not** stripped here, and that is deliberate: this module's docstrings
    argue about D-01 and have to be able to name it, so the check is on the identifiers and string
    literals the AST holds rather than on the prose. `rung` appears as a payload key with a null value,
    which is the one occurrence that is required, so it is named as the sole exception.
    """
    import ast

    tree = ast.parse(LEARNING_API.read_text(encoding="utf-8"), filename=str(LEARNING_API))
    offences = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.keyword) and node.arg:
            names = [node.arg]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "\n" not in node.value:
            names = [node.value]
        for name in names:
            lowered = name.lower().lstrip("_")
            if lowered in {"rungs", "tier", "tiers", "grade", "grades", "stufe", "stufen", "niveau"}:
                offences.append(f"{LEARNING_API.name}:{getattr(node, 'lineno', '?')} {name}")
    assert not offences, f"D-01: the learning router invents a scheme. Found: {offences}"
    # Guard on the walk: it has to be seeing this module at all.
    assert "create_self_assertion" in LEARNING_API.read_text(encoding="utf-8")


# ============================================================ R-005 — the gate, end to end


APPLICATION = {
    "display_name": "Beratung Beispiel",
    "title": "Gespräche über Kontokosten",
    "domain": "financial",
    "qualification_pipeline": "capability",
    "roles": ["growth"],
    "summary": "Ein Gespräch über die Kosten eines Kontos.",
    "contact": "kontakt@example.ch",
}


def test_a_real_member_could_not_be_listed_before_and_can_be_now(api):
    """**The defect, and the fix, in one test.** R-005.

    Before the route existed, `POST /api/marketplace/applications` answered every real member with a 403:
    `record_assertion` had no route, so nobody outside a fixture could hold capability evidence. The first
    half here reproduces that state on a member who has asserted nothing; the second half is the same
    member after one self-assertion.

    **R-005 is not weakened.** The gate still refuses a member with no evidence — that is the first
    assertion below, and it is the reason this test is written in two halves rather than one.
    """
    client, _, _ = api

    refused = client.post("/api/marketplace/applications", json=APPLICATION)
    assert refused.status_code == 403, refused.text
    assert "R-005" in refused.json()["detail"]

    assert client.post(
        "/api/capabilities/assertions", json={"capability_id": CAPABILITY}
    ).status_code == 201

    accepted = client.post("/api/marketplace/applications", json=APPLICATION)
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["status"] == "draft"
    # R-202. A draft, and the payload says what it is waiting for rather than leaving a member to wonder.
    assert body["publishable"] is False
    assert body["publishable_after"] == "at_least_one_disclosure"


def test_a_real_member_completes_the_whole_path_and_appears_in_the_market_place(api):
    """R-005, R-202, R-203, end to end over HTTP: assert, apply, disclose, publish, browse.

    Every step is a route, in the order a member takes them, and the last step is a member seeing the
    listing — which is the thing that was impossible for anybody who was not a test fixture.
    """
    client, member_id, db_session = api

    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    client.post("/api/capabilities/assertions", json={"capability_id": "fixkosten_eines_monats"})

    listing_id = client.post("/api/marketplace/applications", json=APPLICATION).json()["id"]

    disclosed = client.post(
        f"/api/marketplace/applications/{listing_id}/disclosures",
        json={
            "kind": "none_declared",
            "statement": "Es bestehen keine wirtschaftlichen Beziehungen zu Anbietern.",
            "declared_by": "Beratung Beispiel",
        },
    )
    assert disclosed.status_code == 201, disclosed.text

    published = client.post(f"/api/marketplace/applications/{listing_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    entries = client.get("/api/marketplace/listings", params={"roles": NO_FILTER}).json()["entries"]
    assert listing_id in [entry["id"] for entry in entries], (
        "a member who went through every route is not in the market place"
    )

    # R-203. The two earned inputs are now real for a listing the application itself created.
    standing = member_standing(db_session, member_id)
    assert sorted(standing["capability_evidence"]) == ["fixkosten_eines_monats", CAPABILITY]


def test_capability_evidence_was_zero_and_is_not_any_more(api):
    """C-08's point. `capability_evidence` is an ordering input R-203 names, and it was structurally zero.

    A74 fixed the derivation — `standing_inputs` was written once, empty, and never revisited — and it
    remained zero in practice for every real member because no route could create an assertion. This
    asserts both states, in order, on the same listing.
    """
    client, _, db_session = api
    from eigentlich.models.marketplace import Listing

    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    listing_id = client.post("/api/marketplace/applications", json=APPLICATION).json()["id"]
    listing = db_session.get(Listing, listing_id)
    assert listing_ordering_inputs(listing, ("growth",)).capability_evidence == 1

    # And a second assertion, published, moves it — so the input is live rather than written once.
    client.post("/api/capabilities/assertions", json={"capability_id": "franchise_rechnung"})
    client.post(
        f"/api/marketplace/applications/{listing_id}/disclosures",
        json={"kind": "none_declared", "statement": "Keine.", "declared_by": "Beratung Beispiel"},
    )
    client.post(f"/api/marketplace/applications/{listing_id}/publish")
    db_session.expire_all()
    listing = db_session.get(Listing, listing_id)
    assert listing_ordering_inputs(listing, ("growth",)).capability_evidence == 2


# ============================================================ C-08 — the ordering, with real evidence


def _list_and_publish(client, *, roles, title):
    listing_id = client.post(
        "/api/marketplace/applications",
        json={**APPLICATION, "roles": roles, "title": title},
    ).json()["id"]
    client.post(
        f"/api/marketplace/applications/{listing_id}/disclosures",
        json={"kind": "none_declared", "statement": "Keine.", "declared_by": title},
    )
    published = client.post(f"/api/marketplace/applications/{listing_id}/publish")
    assert published.status_code == 200, published.text
    return listing_id


def test_declaring_every_role_still_cannot_beat_real_evidence(api_engine, fast_kdf):
    """C-08 / A74, with the evidence side real for the first time.

    A74 made `role_match` a **share** so that "no declaration can beat another declaration; the most it
    can do is tie, and ties fall to capability evidence and community presence". That was proved over all
    225 declared/requested pairs — arithmetic about a function. It could not be proved end to end, because
    the only way a listing got non-zero `capability_evidence` was the seed fixture. It can now.

    Two members, two published listings, both through the routes:

      * a **specialist** declaring one role, with three self-asserted capabilities;
      * a **generalist** declaring all four, with the one assertion R-005 requires.

    On a single-role query the specialist wins on the share alone (12 twelfths against 3). On a query
    naming all four the shares **tie** at 12, and the tie falls to evidence — which is the property A74
    argued for, now driven by rows a member created rather than by a fixture.
    """
    from eigentlich.services.marketplace import NO_FILTER as ALL

    with make_session_factory(api_engine)() as db_session:
        seed_learning(db_session)
        db_session.commit()

        app = FastAPI()
        app.include_router(learning_api.router)
        app.include_router(marketplace_api.router)
        app.dependency_overrides.update(session_overrides(db_session))

        specialist, specialist_token = _register(
            db_session, email="specialist@example.ch", name="Specialist"
        )
        generalist, generalist_token = _register(
            db_session, email="generalist@example.ch", name="Generalist"
        )

        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {specialist_token}"
            for key in (CAPABILITY, "fixkosten_eines_monats", "franchise_rechnung"):
                assert client.post(
                    "/api/capabilities/assertions", json={"capability_id": key}
                ).status_code == 201
            narrow = _list_and_publish(client, roles=["growth"], title="Nur Wertsteigerung")

            client.headers["Authorization"] = f"Bearer {generalist_token}"
            assert client.post(
                "/api/capabilities/assertions", json={"capability_id": CAPABILITY}
            ).status_code == 201
            wide = _list_and_publish(
                client,
                roles=["growth", "income", "stabilisation", "protection"],
                title="Alles gleichzeitig",
            )

            # The shares are what the docstring claims they are, before anything is asserted about order.
            assert role_match_share(["growth"], ("growth",)) == 12
            assert role_match_share(
                ["growth", "income", "stabilisation", "protection"], ("growth",)
            ) == 3
            assert role_match_share(
                ["growth", "income", "stabilisation", "protection"],
                ("growth", "income", "stabilisation", "protection"),
            ) == 12

            one_role = [
                entry["id"]
                for entry in client.get(
                    "/api/marketplace/listings", params={"roles": ["growth"]}
                ).json()["entries"]
            ]
            assert one_role.index(narrow) < one_role.index(wide), (
                "breadth of declaration outranked a narrower listing on a single-role query"
            )

            every_role = [
                entry["id"]
                for entry in client.get(
                    "/api/marketplace/listings",
                    params={"roles": ["growth", "income", "stabilisation", "protection"]},
                ).json()["entries"]
            ]
            assert every_role.index(narrow) < every_role.index(wide), (
                "the shares tie at 12 and the tie did not fall to capability evidence — C-08"
            )

            unfiltered = [
                entry["id"]
                for entry in client.get(
                    "/api/marketplace/listings", params={"roles": ALL}
                ).json()["entries"]
            ]
            assert unfiltered.index(narrow) < unfiltered.index(wide), (
                "an unfiltered browse asks for no role, so the order rests entirely on the two earned "
                "inputs — and the member with three assertions is behind the one with one"
            )

        # Guard on all three: the evidence really differs, so "the order follows evidence" is a result
        # rather than an accident of two equal rows and a lucky tiebreak.
        assert len(member_standing(db_session, specialist.id)["capability_evidence"]) == 3
        assert len(member_standing(db_session, generalist.id)["capability_evidence"]) == 1


def test_the_ordering_still_reads_nothing_commercial_once_evidence_is_real(api):
    """C-08. `test_listing_ranking_cannot_read_fee_fields` in `test_marketplace.py` is the acceptance
    check the build spec names, and it stays green and non-vacuous.

    This is the narrower claim that belongs with *this* change: making `capability_evidence` real did not
    put a provider in scope for any ordering function. Asserted on the projection actually used by the
    route the application serves, with a fee written on the provider first, so it is behavioural rather
    than a second reading of the same source.
    """
    from eigentlich.models.marketplace import Listing, Provider

    client, _, db_session = api
    client.post("/api/capabilities/assertions", json={"capability_id": CAPABILITY})
    listing_id = _list_and_publish(client, roles=["growth"], title="Mit Rechnung")

    listing = db_session.get(Listing, listing_id)
    supplier = db_session.get(Provider, listing.provider_id)
    before = listing_ordering_inputs(listing, ("growth",))
    supplier.billing_fee_chf = 24000.0
    supplier.billing_plan = "the_most_expensive_thing_we_sell"
    db_session.commit()
    # Guard: the fee was really written, or "nothing moved" is a statement about an empty column.
    assert db_session.get(Provider, listing.provider_id).billing_fee_chf == 24000.0
    assert listing_ordering_inputs(db_session.get(Listing, listing_id), ("growth",)) == before


# ============================================================ the service, without HTTP


def test_the_service_refuses_an_unknown_capability(session, member):
    seed_learning(session)
    session.commit()
    with pytest.raises(NoSuchCapability):
        record_self_assertion(session, member_id=member.id, capability_id="not_a_capability")


def test_the_service_refuses_a_unit_that_does_not_evidence_it(session, member):
    seed_learning(session)
    session.commit()
    with pytest.raises(NotEvidencedByThatUnit):
        record_self_assertion(
            session,
            member_id=member.id,
            capability_id=CAPABILITY,
            learning_unit=UNIT_THAT_DOES_NOT,
        )


def test_the_service_refuses_a_second_self_assertion(session, member):
    seed_learning(session)
    session.commit()
    record_self_assertion(session, member_id=member.id, capability_id=CAPABILITY)
    session.commit()
    with pytest.raises(AlreadyAsserted):
        record_self_assertion(session, member_id=member.id, capability_id=CAPABILITY)


def test_a_curator_recorded_assertion_is_not_blocked_by_the_members_own(session, member):
    """The duplicate refusal matches on the self-assertion kind alone.

    If the owner ever corrects A82's reading to mean the curators rather than the members — A82 names that
    as the one line to change — a differently-sourced assertion must not be refused because a member has
    already made their own. `record_assertion` is still the open, un-enumerated path it always was.
    """
    from eigentlich.services.learning import record_assertion

    seed_learning(session)
    session.commit()
    record_self_assertion(session, member_id=member.id, capability_id=CAPABILITY)
    record_assertion(
        session,
        member_id=member.id,
        capability_id=CAPABILITY,
        evidence_kind="conversation_with_a_curator",
        assessed_by="curator:demo",
    )
    session.commit()

    review = capability_review(session, member_id=member.id)
    entry = next(c for c in review["capabilities"] if c["key"] == CAPABILITY)
    assert sorted(e["self_asserted"] for e in entry["evidence"]) == [False, True]
    assert {e["evidence_kind"] for e in entry["evidence"]} == {
        SELF_ASSERTION_KIND,
        "conversation_with_a_curator",
    }


def test_one_capability_evidenced_twice_is_still_one_ordering_input(session, member):
    """C-07 and C-08 at once: `member_standing` de-duplicates, so a count of rows cannot move an order.

    This is why refusing the duplicate is about what gets *rendered* rather than about the ordering — and
    it is worth a test, because if this ever stopped being a set the duplicate refusal would become the
    only thing standing between C-08 and a purchasable input.
    """
    from eigentlich.services.learning import record_assertion

    seed_learning(session)
    session.commit()
    record_self_assertion(session, member_id=member.id, capability_id=CAPABILITY)
    for index in range(3):
        record_assertion(
            session,
            member_id=member.id,
            capability_id=CAPABILITY,
            evidence_kind=f"conversation_{index}",
            assessed_by="curator:demo",
        )
    session.commit()
    assert member_standing(session, member.id)["capability_evidence"] == [CAPABILITY]


def test_browse_reads_no_assertion_of_the_browsing_member(session, member):
    """R-004, unchanged by any of this. Browsing is not gated, and a member's own assertions do not
    change what they are shown."""
    seed_learning(session)
    session.commit()
    before = browse(session, member_id=member.id, roles=NO_FILTER)
    record_self_assertion(session, member_id=member.id, capability_id=CAPABILITY)
    session.commit()
    after = browse(session, member_id=member.id, roles=NO_FILTER)
    assert [e["id"] for e in before["entries"]] == [e["id"] for e in after["entries"]]
    assert after["browsing_is_not_gated"] is True
