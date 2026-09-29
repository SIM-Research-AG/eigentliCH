"""The content seed: what goes in, idempotence, the bind report, and the refusal to overwrite an edit."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from eigentlich import seed, store
from eigentlich.intake import IntakeError, extract


@pytest.fixture(scope="module")
def first(settings, st):
    with st.session() as conn:
        return seed.seed(conn, settings.prototype_root)


def test_everything_is_seeded_as_version_1(first, db):
    assert first["ok"]
    assert first["counts"] == {"created": 54, "updated": 0, "unchanged": 0, "conflict": 0}
    assert first["by_kind"] == {"questionnaire": 2, "scoring_map": 3, "reference": 14, "knowledge": 35}
    versions = {k["version"] for k in store.content_keys(db)}
    assert versions == {1}
    assert all(k["saved_by_kind"] == "seed" for k in store.content_keys(db))


def test_the_questionnaires(first, db):
    assert first["questionnaires"] == {
        "questionnaire/onboarding": {"version": "onb2@0.1.0", "questions": 21},
        "questionnaire/intake": {"version": "intake@1.1", "questions": 113},
    }
    intake = store.content_current(db, "questionnaire/intake")["body"]
    assert len(intake["sections"]) == 20
    q = {x["key"]: x for x in intake["questions"]}
    assert q["crisis_behaviour"]["type"] == "choice"
    assert [o["value"] for o in q["crisis_behaviour"]["options"]][:2] == ["nichts, ich blieb investiert", "nachgekauft"]
    assert q["income_gross"]["unit"] == "CHF/Jahr" and q["income_gross"]["section"] == "03"
    assert q["household"]["multiline"] is True
    assert q["properties"]["type"] == "repeat" and len(q["properties"]["fields"]) == 12
    assert all(x["question"]["de"] and x.get("why", {}).get("de") for x in intake["questions"])


def test_the_onboarding_questionnaire_is_verbatim(settings, db):
    source = json.loads((settings.prototype_root / "client/content/onboarding-questions.json").read_text("utf-8"))
    assert store.content_current(db, "questionnaire/onboarding")["body"] == source


def test_a_knowledge_note_keeps_its_front_matter_and_markdown(db):
    body = store.content_current(db, "knowledge/saeule-3a-grundlagen")["body"]
    assert body["front_matter"]["id"] == "saeule-3a-grundlagen"
    assert body["front_matter"]["reviewed_on"] == "2026-08-31"
    assert body["markdown"].startswith("# Die Säule 3a")


def test_a_second_run_adds_nothing(first, settings, st):
    with st.session() as conn:
        again = seed.seed(conn, settings.prototype_root)
        total = conn.execute("SELECT count(*) AS n FROM content_record").fetchone()["n"]
    assert again["counts"] == {"created": 0, "updated": 0, "unchanged": 54, "conflict": 0}
    assert total == 54


def test_binds_are_explicit_and_checked(first, db):
    body = store.content_current(db, "scoring/risk-profile")["body"]
    assert set(body) == {"map", "binds", "source"}
    crisis = [b for b in body["binds"] if b["question"] == "crisis_behaviour"]
    assert {b["option_value"] for b in crisis} == {"nichts, ich blieb investiert", "nachgekauft", "teilweise verkauft",
                                                   "alles verkauft", "ich war nicht investiert", "noch nie investiert"}
    tiers = [b for b in store.content_current(db, "scoring/human-capital")["body"]["binds"]
             if b["path"][:2] == ["responsibility", "tiers"] and len(b["path"]) == 3]
    assert {(b["string"], b["option_value"]) for b in tiers if b["questionnaire"] == "questionnaire/onboarding"} == {
        ("ohne Kaderfunktion", "Keine Führungsfunktion"),
        ("oberes und mittleres Kader", "Oberes oder mittleres Kader"),
        ("topmanagement", "Oberste Führung")}


def test_the_seed_report_names_every_mismatch(first):
    b = first["binds"]
    assert b["total"] == b["ok"] + len(b["mismatches"])
    found = {(m["scoring_key"], m["option_value"], m["question_key"], m["status"]) for m in b["mismatches"]}
    # Real gaps between the maps and the questionnaires, reported rather than hidden:
    assert ("scoring/intake-scales", "80 %", "goal_confidence", "not_an_option") in found
    assert ("scoring/intake-scales", "kaum welche", "education_hours", "no_question") in found
    assert ("scoring/risk-profile", "Waffen", "esg_exclusions", "question_has_no_options") in found
    assert ("scoring/human-capital", "1", "health", "not_an_option") in found
    assert ("scoring/human-capital", "kaum welche", "rest_hours", "not_an_option") in found
    assert not any(m["option_value"] == "midpoint_warning" for m in b["mismatches"]), "a note key is not an answer"
    assert first["unbound_candidates"] == {}
    text = seed.format_report(first)
    assert text.count("MISMATCH") == len(b["mismatches"])


def test_the_live_bind_check_follows_a_questionnaire_edit(first, db, make_curator):
    cur = make_curator()
    body = store.content_current(db, "questionnaire/intake")["body"]
    q = next(x for x in body["questions"] if x["key"] == "goal_confidence")
    q["options"].append({"value": "80 %", "label": {"de": "80 %"}})
    store.save_content(db, key="questionnaire/intake", kind="questionnaire", body=body, saved_by_kind="curator",
                       saved_by_ref=cur["id"], note="Option ergänzt")
    row = db.execute("SELECT status FROM scoring_bind_check WHERE option_value = '80 %' AND question_key = "
                     "'goal_confidence'").fetchone()
    assert row["status"] == "ok"
    db.rollback()


def test_a_changed_source_after_an_edit_is_a_conflict_not_an_overwrite(settings, st, first, make_curator, monkeypatch):
    cur = make_curator()
    with st.session() as conn:
        store.save_content(conn, key="reference/roles", kind="reference", body={"edited": True},
                           saved_by_kind="curator", saved_by_ref=cur["id"])
    original = seed.collect

    def changed(root: Path):
        return [replace(i, body={"changed": True}) if i.key == "reference/roles" else i for i in original(root)]

    monkeypatch.setattr(seed, "collect", changed)
    with st.session() as conn:
        report = seed.seed(conn, settings.prototype_root)
        latest = store.content_current(conn, "reference/roles")
    assert not report["ok"] and report["conflicts"] == ["reference/roles"]
    assert latest["body"] == {"edited": True} and latest["saved_by_kind"] == "curator"


def test_a_changed_source_before_any_edit_is_a_new_seed_version(settings, st, first, monkeypatch):
    original = seed.collect

    def changed(root: Path):
        return [replace(i, body={**i.body, "added": 1}) if i.key == "reference/stages" else i for i in original(root)]

    monkeypatch.setattr(seed, "collect", changed)
    with st.session() as conn:
        report = seed.seed(conn, settings.prototype_root)
        latest = store.content_current(conn, "reference/stages")
    assert report["ok"] and "reference/stages" in [i["key"] for i in report["items"] if i["status"] == "updated"]
    assert latest["version"] == 2 and latest["body"]["added"] == 1


def test_intake_extraction_fails_loudly_when_html_and_fields_disagree(settings, tmp_path):
    html = (settings.prototype_root / "client/intake.html").read_text("utf-8")
    broken = html.replace('name="employer"', 'name="employer_name"', 1)
    path = tmp_path / "intake.html"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(IntakeError, match="disagree"):
        extract(path)


def test_a_bind_to_a_path_that_is_not_in_the_map_fails_loudly():
    with pytest.raises(seed.SeedError, match="not in the map"):
        seed.resolve_binds("risk-profile", {"willingness": {}})
