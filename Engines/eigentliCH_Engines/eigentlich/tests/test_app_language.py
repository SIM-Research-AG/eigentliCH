"""What the client reads (owner feedback 29.09.2026): balance-sheet gaps in plain words with names instead of
ids (EIG-49), one language throughout, and the AI called MiniMind (EIG-48). Pure: no database."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eigentlich import gaps

ROOT = Path(__file__).resolve().parents[1]
LBS_ENGINE = ROOT.parent / "engines" / "lbs" / "src" / "lbs" / "engine.py"
I18N = (ROOT / "client" / "app" / "i18n.js").read_text(encoding="utf-8")
DE, EN = I18N.split("\nconst en = {", 1)


def _keys(table: str) -> set[str]:
    return set(re.findall(r"'([a-z_][A-Za-z0-9_.\-]*)':", table)) | set(re.findall(r"^\s+([a-z_]+):", table, re.M))


DE_KEYS, EN_KEYS = _keys(DE), _keys(EN)


def lbs_gap_inputs() -> set[str]:
    """Every input lbs's engine can name in a gap: the literal inputs of ``ctx.gap`` (an id prefix taken off)
    and every reason key it appends to a finding's ``undetermined_because`` (those become gap inputs)."""
    src = LBS_ENGINE.read_text(encoding="utf-8")
    found = set()
    for m in re.finditer(r'ctx\.gap\(\s*[^,]+,\s*(f?)"([^"]+)"', src):
        value = m.group(2)
        if m.group(1):                               # f"{person.person_id}.{cap.key}", f"{p.position_id}.vessel"
            value = value.rsplit("}.", 1)[-1]
        found |= {"E", "N", "H"} if value == "{cap.key}" else {value}
    found |= set(re.findall(r'(?:undetermined_because"\]|why)\.append\("([a-z_]+)"\)', src))
    return found


@pytest.mark.skipif(not LBS_ENGINE.is_file(), reason="the lbs engine's source is not beside this package")
def test_every_gap_lbs_can_emit_is_known():
    known_inputs = {k.split(".", 1)[1] for k in gaps.KNOWN}
    missing = sorted(lbs_gap_inputs() - known_inputs)
    assert missing == [], f"lbs can name gaps the app has no sentence for: {missing}"


def test_every_known_gap_has_a_german_and_an_english_sentence():
    for key in gaps.KNOWN:
        assert f"gap.{key}" in DE_KEYS, f"no German text for gap {key}"
        assert f"gap.{key}" in EN_KEYS, f"no English text for gap {key}"
    for kind in ("not_in_the_request", "record_not_approved", "needs_an_unpublished_assumption",
                 "owned_by_another_engine", "past_its_validity_horizon", "unknown"):
        assert f"gapkind.{kind}" in DE_KEYS and f"gapkind.{kind}" in EN_KEYS
    for action in {a for a in gaps.KNOWN.values() if a}:
        assert f"gap.action.{action}" in DE_KEYS and f"gap.action.{action}" in EN_KEYS


def test_both_languages_have_the_same_keys():
    assert sorted(DE_KEYS - EN_KEYS) == [] and sorted(EN_KEYS - DE_KEYS) == []


def test_a_gap_is_named_by_what_the_client_called_it():
    goal, pos = "76658f42b30841b8b3933cc85c03bec8", "a" * 32
    out = gaps.describe([
        {"section": f"property.{goal}", "input": "the_goal_does_not_say_whether_the_member_will_live_in_it",
         "kind": "not_in_the_request", "reason": "..."},
        {"section": f"property.{goal}", "input": f"{pos}.vessel", "kind": "not_in_the_request", "reason": "..."},
        {"section": "human_capital", "input": "p1.E", "kind": "not_in_the_request", "reason": "..."},
        {"section": "pensions.p2", "input": "gross_income", "kind": "not_in_the_request", "reason": "..."},
        {"section": "retirement.4780261fdef94cc2af7ef5269d20ce98", "input": "the_ahv_table_is_not_approved",
         "kind": "record_not_approved", "reason": "..."},
        {"section": "mandate_proposal", "input": "annual_contribution", "kind": "not_in_the_request", "reason": "..."},
        {"section": "totals", "input": "something_new", "kind": "not_in_the_request", "reason": "..."},
    ], goals={goal: "Eigenheim Zug"}, positions={pos: "Sparkonto"}, persons={"p1": "Anna", "p2": "Ben"},
        mandate_goal=goal)
    by_key = {g["key"]: g for g in out}
    assert by_key["property.the_goal_does_not_say_whether_the_member_will_live_in_it"]["name"] == "Eigenheim Zug"
    assert by_key["property.the_goal_does_not_say_whether_the_member_will_live_in_it"]["action"] == "plan"
    assert by_key["property.vessel"]["name"] == "Eigenheim Zug"
    assert by_key["human_capital.E"]["name"] == "Anna" and by_key["pensions.gross_income"]["name"] == "Ben"
    ahv = by_key["retirement.the_ahv_table_is_not_approved"]
    assert ahv["group"] == "us" and ahv["action"] is None and ahv["name"] is None
    assert by_key["mandate_proposal.annual_contribution"]["action"] == "onboarding"
    assert by_key["totals.something_new"]["known"] is False                 # still read: the kind's sentence
    text = repr(out)
    assert goal not in text and pos not in text and "4780261f" not in text


def test_what_the_client_reads_says_minimind_and_no_engine_jargon():
    visible = [v for v in re.findall(r":\s*'((?:[^'\\]|\\.)*)'", I18N)]
    for v in visible:
        assert "spark7" not in v.lower(), v
        assert "(lbs)" not in v and "{id}" not in v and "{lbs}" not in v and "{pcp}" not in v, v
    assert "'thread.spark7': 'MiniMind (Entwurf)'" in DE and "'thread.spark7': 'MiniMind (draft)'" in EN
    js = "\n".join(p.read_text("utf-8") for p in (ROOT / "client" / "surfaces").glob("*.js"))
    code = re.sub(r"//[^\n]*", "", js)
    for raw in ("g.section", "g.input", "g.reason", "s.notice", "artefact_id}", "m.model"):
        assert raw not in code, f"the page shows {raw}"
    assert "draft.error ||" not in code and "r.job.error ||" not in code


def _note(key, title, markdown, topic="vorsorge", approved=True):
    return {"key": f"knowledge/{key}", "version": 1, "body": {"front_matter": {
        "id": key, "title_de": title, "topic": topic, "approved": approved}, "markdown": markdown}}


def test_grounding_is_german_aware():
    """EIG-51: synonyms from reference/search-aliases, stems, compounds, the questions a note answers, and a
    floor so that a question with any overlap is never sent without a note."""
    from eigentlich import grounding
    notes = [
        _note("bvg", "Die berufliche Vorsorge", "Wie das Guthaben entsteht."),
        _note("lohn", "Lohn und Arbeit", "## Fragen, die dieser Text beantwortet\n\n- Wie steigt mein Einkommen?\n\n## Mehr\n\nText."),
        _note("strategie", "Eine Strategie für Wachstum", "Text.", topic="anlegen"),
        _note("geheim", "Einkommen", "Einkommen", approved=False),
    ]
    aliases = grounding.alias_groups({"groups": [{"forms": ["Pensionskasse", "berufliche Vorsorge", "BVG"]}]})
    pick = lambda q, **kw: [c.key.split("/")[1] for c in grounding.choose(
        q, notes, max_notes=4, max_chars_per_note=5800, min_score=kw.pop("min_score", 2), aliases=aliases, **kw)]
    assert pick("Wie rechnet meine Pensionskasse?") == ["bvg"]                   # a synonym, as one term
    assert pick("Was bringt ein Einkommens?")[0] == "lohn"                      # a stem, in the questions list
    assert pick("Meine Wachstumsstrategie") == ["strategie"]                     # a compound split
    assert pick("Einkommen", min_score=9) == ["lohn"]                            # below min_score: the floor
    assert pick("Einkommen", min_score=9, floor=5) == []
    assert pick("xyzzy") == []                                                   # nothing matches: nothing sent
    assert grounding.about_the_asker("Was muss ich machen?") and not grounding.about_the_asker("Was ist ein ETF?")
