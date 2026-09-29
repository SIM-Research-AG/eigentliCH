"""The questionnaires aligned to the scoring maps (EIG-44) and the yearly contribution question (EIG-45), on a
throwaway schema seeded from the prototype."""

from __future__ import annotations

import pytest

from eigentlich import alignment, questionnaires as qn, store
from eigentlich import seed as seeding
from eigentlich.alignment import INTAKE, NOTE, ONBOARDING
from eigentlich.questionnaires import AnswerRefused


@pytest.fixture(scope="module")
def aligned(settings, st):
    with st.session() as conn:
        report = seeding.seed(conn, settings.prototype_root)
        before = conn.execute("SELECT count(*) AS n FROM scoring_bind_check WHERE status <> 'ok'").fetchone()["n"]
        curator = store.create_curator(conn, display_name="Nicolas (Owner)")["id"]
    assert report["ok"]
    with st.session() as conn:
        result = alignment.align(conn, curator_id=curator)
    return {"before": before, "result": result, "curator": curator}


def _mismatches(conn):
    return conn.execute("SELECT scoring_key, question_key, option_value, status FROM scoring_bind_check "
                        "WHERE status <> 'ok'").fetchall()


def test_the_seeded_content_had_19_mismatches_and_the_aligned_has_none(aligned, db):
    assert aligned["before"] == 19
    assert _mismatches(db) == []
    total = db.execute("SELECT count(*) AS n FROM scoring_bind_check").fetchone()["n"]
    assert aligned["result"]["binds"] == {"ok": total} and total == 169


def test_the_new_versions_are_a_curators_with_the_owners_note(aligned, db):
    for key in (INTAKE, ONBOARDING):
        cur = store.content_current(db, key)
        assert cur["version"] == 2 and cur["saved_by_kind"] == "curator" and cur["saved_by_ref"] == aligned["curator"]
        assert cur["note"] == NOTE == "aligned to scoring maps, owner 29.09.2026"
    saved = aligned["result"]["saved"]
    assert set(saved[INTAKE]["questions"]) == {"goal_confidence", "education_hours", "esg_exclusions", "health",
                                               "rest_hours"}
    assert saved[ONBOARDING]["questions"] == ["annual_contribution"]


def test_the_maps_are_unchanged(aligned, db):
    for key in ("scoring/intake-scales", "scoring/risk-profile", "scoring/human-capital"):
        assert store.content_current(db, key)["version"] == 1


def test_a_second_alignment_writes_nothing_and_the_seed_stays_clean(aligned, settings, st):
    with st.session() as conn:
        again = alignment.align(conn, curator_id=aligned["curator"])
        report = seeding.seed(conn, settings.prototype_root)
    assert {k: v["status"] for k, v in again["saved"].items()} == {INTAKE: "unchanged", ONBOARDING: "unchanged"}
    assert report["ok"] and report["counts"]["unchanged"] == 54 and report["binds"]["mismatches"] == []


def test_the_aligned_questions(aligned, db):
    intake = store.content_current(db, INTAKE)["body"]
    q = {x["key"]: x for x in intake["questions"]}
    offered = lambda key: [o["value"] for o in alignment.offered(q[key]["options"])]
    assert offered("goal_confidence") == ["70 % — ich kann nachjustieren", "80 %", "90 % — es muss halten",
                                          "95 % — kein Spielraum"]
    assert offered("rest_hours") == ["kaum welche", "5–10", "10–20", "20–30", "mehr als 30"]
    assert [o["value"] for o in q["rest_hours"]["options"] if o.get("offered") is False] == ["unter 10", "über 30"]
    assert "1" in [o["value"] for o in q["health"]["options"]] and "1" not in offered("health")
    assert q["esg_exclusions"]["type"] == "multi_choice" and len(offered("esg_exclusions")) == 7
    order = [x["key"] for x in qn.ordered(intake)]
    assert order.index("education_hours") == order.index("education_recent") + 1
    assert offered("education_hours") == ["kaum welche", "1–2", "3–5", "5–10", "mehr als 10"]
    assert intake["version"] == "intake@1.2" and len(intake["questions"]) == 114

    onb = store.content_current(db, ONBOARDING)["body"]
    contribution = qn.question(onb, "annual_contribution")
    assert contribution["type"] == "number" and contribution["min"] == 0 and contribution["unit"] == "chf_per_year"
    assert contribution["question"] == {"de": "Wie viel können Sie pro Jahr zur Seite legen?",
                                        "en": "How much can you put aside each year?"}
    assert qn.ordered(onb)[-1]["key"] == "annual_contribution"


def test_multi_choice_and_not_offered_answers(aligned, db):
    q = {x["key"]: x for x in store.content_current(db, INTAKE)["body"]["questions"]}
    assert qn.check(q["esg_exclusions"], ["Tabak", "Waffen", "Tabak"]) == ["Waffen", "Tabak"]
    for bad in ("Waffen", ["Atomwaffen"], []):
        with pytest.raises(AnswerRefused):
            qn.check(q["esg_exclusions"], bad)
    assert qn.check(q["rest_hours"], "über 30") == "über 30"        # the offline form's band stays valid
    assert qn.check(q["health"], "1") == "1"
    contribution = qn.question(store.content_current(db, ONBOARDING)["body"], "annual_contribution")
    assert qn.check(contribution, 12000) == 12000
    with pytest.raises(AnswerRefused):
        qn.check(contribution, -1)


def test_an_edit_keeps_an_option_not_offered(aligned, db):
    body = store.content_current(db, INTAKE)["body"]
    rest = qn.question(body, "rest_hours")
    edited = qn.apply_edit(body, "rest_hours", {"options": [{"value": o["value"], "label": o["label"]}
                                                            for o in rest["options"]]})
    assert qn.question(edited, "rest_hours")["options"] == rest["options"]
    edited = qn.apply_edit(body, "esg_exclusions", {"options": [{"value": "Waffen", "label": {"de": "Rüstung"}}]})
    assert qn.question(edited, "esg_exclusions")["options"] == [{"value": "Waffen", "label": {"de": "Rüstung"}}]


def test_a_revoked_curator_cannot_align(settings, st):
    with st.session() as conn:
        cur = store.create_curator(conn, display_name="Ausgeschieden")
        store.revoke_curator(conn, cur["id"], "test")
    with st.session() as conn:
        with pytest.raises(ValueError, match="revoked"):
            alignment.align(conn, curator_id=cur["id"])
