"""The pure core: the number check, reading the reply, citations, repairs, routing and the prompt."""

from __future__ import annotations

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from chatbot import engine
from chatbot.calibration import PRODUCTION as CAL
from chatbot.contracts import ChatRequest

from .conftest import NOTES


def req(**over) -> ChatRequest:
    body = {"question": "Wie viel darf ich einzahlen?", "language": "de", "grounding": NOTES}
    body.update(over)
    return ChatRequest.model_validate(body)


def check(answer: str, request: ChatRequest | None = None, use_facts: bool = True):
    request = request or req()
    sources = engine.sources_for(request, CAL, use_client_facts=use_facts, history=request.history)
    return engine.check_numbers(answer, sources, CAL)


# -- the number check -----------------------------------------------------------

@pytest.mark.parametrize("text", ["CHF 7'258", "CHF 7’258", "CHF 7 258", "CHF 7258", "7.258 Franken",
                                  "rund 7,3 Tausend Franken", "36'288", "20 %", "20%"])
def test_a_source_figure_in_any_swiss_spelling_is_verified(text):
    numbers, unverified = check(f"Sie dürfen {text} einzahlen.")
    assert unverified == (), numbers
    assert all(n.matched for n in numbers)


def test_an_invented_figure_is_flagged_and_the_real_one_is_not():
    numbers, unverified = check("Der Maximalbetrag beträgt CHF 7'258, früher CHF 6'883.")
    assert unverified == ("6'883",)
    assert [n.matched for n in numbers] == [("N1",), ()]


def test_a_near_miss_is_not_a_match():
    """Rounding is enumerated, never tolerated: 7'250 is not a rendering of 7'258."""
    assert check("etwa CHF 7'250")[1] == ("7'250",)


def test_single_digits_are_labels_and_not_checked():
    numbers, unverified = check("Die Säule 3a ist die 3. Säule.")
    assert numbers == () and unverified == ()


def test_a_list_is_not_welded_into_one_number():
    """prior art desktop/prose.py: "400.000, 83 %" once matched as one token and passed by coincidence."""
    request = req(grounding=[{"id": "A", "title": "t", "text": "Vermögen 400'000.", "source_label": "s"}])
    numbers, unverified = check("400.000, 83 %", request)
    assert [n.text for n in numbers] == ["400.000", "83"] and unverified == ("83",)


def test_dates_are_one_token_and_checked_as_dates():
    request = req(grounding=[{"id": "D", "title": "t", "text": "Gültig ab 1.1.2026.", "source_label": "s"}])
    numbers, unverified = check("Das gilt seit 01.01.2026, nicht seit 2025-06-30.", request)
    assert [n.text for n in numbers] == ["01.01.2026", "2025-06-30"]
    assert unverified == ("2025-06-30",)


def test_scale_words_are_read():
    request = req(grounding=[{"id": "M", "title": "t", "text": "Das Vermögen beträgt CHF 1'600'000.",
                              "source_label": "s"}])
    assert check("rund 1,6 Millionen Franken", request)[1] == ()
    assert check("rund 1,7 Millionen Franken", request)[1] == ("1,7",)
    assert check("rund 1,6 Franken", request)[1] == ("1,6",)          # no scale word, no scaled match


def test_client_facts_are_sources_only_when_used():
    request = req(client_facts=[{"key": "income", "label": "Einkommen", "value": 98500.0, "source": "lbs"}])
    assert check("Ihr Einkommen von CHF 98'500", request, use_facts=True)[1] == ()
    assert check("Ihr Einkommen von CHF 98'500", request, use_facts=False)[1] == ("98'500",)
    numbers, _ = check("Ihr Einkommen von CHF 98'500", request, use_facts=True)
    assert numbers[0].matched == ("fact:income",)


def test_a_share_fact_may_be_quoted_as_a_percentage():
    request = req(client_facts=[{"key": "rate", "label": "Sparquote", "value": 0.125, "source": "lbs"}])
    assert check("eine Sparquote von 12,5 %", request)[1] == ()
    assert check("eine Sparquote von 13 %", request)[1] == ()        # rounded to 0 decimals
    assert check("eine Sparquote von 14 %", request)[1] == ("14",)
    assert check("eine Sparquote von 13", request)[1] == ("13",)     # a share is a percentage only with %


def test_numbers_in_the_question_may_be_repeated():
    request = req(question="Reichen CHF 250'000 bis 2040?")
    assert check("Ob CHF 250'000 bis 2040 reichen, steht nicht in den Unterlagen.", request)[1] == ()


def test_the_assistant_history_is_not_a_source():
    request = req(history=[{"role": "user", "content": "Ich habe 12'000 gespart."},
                           {"role": "assistant", "content": "Sie haben 99'999 gespart."}])
    assert check("12'000", request)[1] == ()
    assert check("99'999", request)[1] == ("99'999",)


@hsettings(max_examples=200, deadline=None)
@given(st.integers(min_value=10, max_value=9_999_999))
def test_property_every_rendering_of_a_fact_verifies(value):
    request = req(client_facts=[{"key": "x", "label": "x", "value": float(value), "source": "t"}])
    for text in (f"{value:,}".replace(",", "'"), f"{value:,}".replace(",", " "), str(value)):
        assert check(f"Betrag {text}.", request)[1] == (), text


@hsettings(max_examples=200, deadline=None)
@given(st.integers(min_value=10, max_value=9_999_999), st.integers(min_value=10, max_value=9_999_999))
def test_property_a_different_integer_never_verifies(value, other):
    if other == value:
        return
    request = req(grounding=[{"id": "A", "title": "t", "text": "nichts", "source_label": "s"}],
                  client_facts=[{"key": "x", "label": "x", "value": float(value), "source": "t"}])
    assert check(f"Betrag {other}.", request)[1] == (str(other),)


# -- reading the reply ------------------------------------------------------------

def test_parse_reply_reads_the_object_and_a_fenced_one():
    assert engine.parse_reply('{"status": "answer", "from_notes": "x", "general": "", "cited": ["N1"]}') == \
        engine.Reply("answer", "x", "", ("N1",))
    fenced = '```json\n{"status": "out_of_domain", "from_notes": "", "general": "", "cited": []}\n```'
    assert engine.parse_reply(fenced).status == "out_of_domain"


@pytest.mark.parametrize("text", ["", "keine Ahnung", '{"status": "yes", "from_notes": "x", "general": "", "cited": []}',
                                  '{"status": "answer", "from_notes": "", "general": "", "cited": []}',
                                  '{"status": "answer", "from_notes": "x", "general": 1, "cited": []}',
                                  '{"status": "answer", "from_notes": "x", "general": "", "cited": "N1"}', "[1, 2]",
                                  # the reply shape of prompt 1.0.0 is not read any more
                                  '{"covered": true, "answer": "x", "cited": ["N1"]}'])
def test_parse_reply_refuses_anything_else(text):
    with pytest.raises(engine.ReplyError):
        engine.parse_reply(text)


LABEL = "Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:"


def test_compose_marks_the_general_part_and_names_the_basis():
    grounded = engine.compose(engine.Reply("answer", "Es sind CHF 7'258 [N1].", "", ()), "de", ["N1"], LABEL)
    assert grounded.text == "Es sind CHF 7'258." and grounded.basis == "grounded" and grounded.cited == ("N1",)
    general = engine.compose(engine.Reply("answer", "", "Erstens klären Sie Ihre Ziele.", ()), "de", ["N1"], LABEL)
    assert general.text == LABEL + "\nErstens klären Sie Ihre Ziele." and general.basis == "general"
    assert general.cited == ()
    mixed = engine.compose(engine.Reply("answer", "Es sind CHF 7'258.", "Eröffnen Sie ein Konto.", ("N1",)), "de",
                           ["N1"], LABEL)
    assert mixed.text == "Es sind CHF 7'258.\n\n" + LABEL + "\nEröffnen Sie ein Konto." and mixed.basis == "mixed"


def test_a_part_from_the_notes_that_cites_no_note_is_shown_as_general():
    c = engine.compose(engine.Reply("answer", "Das gilt immer.", "", ("N9",)), "de", ["N1"], LABEL)
    assert c.basis == "general" and c.cited == () and c.text == LABEL + "\nDas gilt immer."
    assert any("shown as a general assessment" in w for w in c.warnings)


def test_a_general_part_cites_nothing():
    c = engine.compose(engine.Reply("answer", "", "Siehe Säule 3a [N1].", ()), "de", ["N1"], LABEL)
    assert c.cited == () and "[N1]" not in c.text and c.basis == "general"


@pytest.mark.parametrize("question,ok", [("???", False), ("123 456", False), ("!!! ...", False), ("was?", True),
                                         ("ETF?", True), ("Wie viel darf ich einzahlen?", True)])
def test_only_a_question_without_a_word_is_unintelligible_to_the_code(question, ok):
    assert engine.intelligible(question) is ok


def test_inline_citation_marks_are_taken_out_and_unknown_ids_dropped():
    text, cited, warnings = engine.take_citations("Es sind CHF 7'258 [N1]. Das gilt ab 65 [N2, N1].",
                                                  ["N9"], ["N1", "N2"])
    assert text == "Es sind CHF 7'258. Das gilt ab 65."
    assert cited == ("N1", "N2") and warnings and "N9" in warnings[0]


# -- repairs, routing, the prompt ---------------------------------------------------

def test_swiss_orthography_and_the_polite_form():
    text, notes = engine.repair("## Titel\n- Das ist gemäß deiner Frage für dich **wichtig**.", "de")
    assert text == "Titel\nDas ist gemäss Ihrer Frage für Sie wichtig."
    assert len(notes) == 3


def test_english_is_left_alone():
    assert engine.repair("Straße", "en")[0] == "Straße"


def test_foreign_script_is_counted():
    assert engine.drifted("Das ist 很好") == 2 and engine.drifted("Grüezi, ça va?") == 0


@pytest.mark.parametrize("question,about_client", [
    ("Wie hoch ist meine Lücke?", True), ("Was ist die Säule 3a?", False), ("Reicht unser Sparen?", True),
    ("Wie funktioniert die AHV?", False)])
def test_the_route_follows_the_first_person(question, about_client):
    assert bool(engine.client_markers(question, "de", CAL)) is about_client


def test_client_facts_reach_the_prompt_only_when_used():
    request = req(client_facts=[{"key": "income", "label": "Einkommen", "value": 98500.0, "source": "lbs"}])
    with_facts = engine.build_messages(request, CAL, use_client_facts=True)[-1]["content"]
    without = engine.build_messages(request, CAL, use_client_facts=False)[-1]["content"]
    assert "Einkommen: 98500" in with_facts and "Einkommen" not in without
    assert "[N1] Säule 3a" in without and without.rstrip().endswith("Wie viel darf ich einzahlen?")


def test_the_prompt_is_bounded_not_truncated():
    long = [{"id": "L", "title": "t", "text": "x" * (CAL.limits.max_chars_per_note + 1), "source_label": "s"}]
    with pytest.raises(engine.EngineError, match="characters"):
        engine.check_limits(req(grounding=long), CAL)


def test_the_history_is_the_most_recent_turns():
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"} for i in range(10)]
    messages = engine.build_messages(req(history=turns), CAL, use_client_facts=False)
    assert [m["content"] for m in messages[1:-1]] == [f"t{i}" for i in range(4, 10)]


def test_the_prompt_hash_is_stable():
    assert engine.prompt_hash() == engine.prompt_hash() and engine.prompt_hash().startswith("PRM-")


def test_the_display_name_is_in_the_prompt_and_its_hash():
    messages = engine.build_messages(req(), CAL, use_client_facts=False, assistant="MiniMind")
    assert messages[0]["content"].startswith("Sie sind MiniMind, die KI von eigentliCH")
    assert "spark7" not in messages[0]["content"]
    assert engine.prompt_hash("MiniMind") != engine.prompt_hash("Other")


def test_a_question_without_notes_says_so_in_the_prompt():
    content = engine.build_messages(req(grounding=[]), CAL, use_client_facts=False)[-1]["content"]
    assert content.startswith("UNTERLAGEN:\nkeine")


def test_the_domain_names_care_incapacity_and_inheritance():
    """CHB-23: the domain rule names family, estate and incapacity law, care and its costs, and health as it
    bears on work and money, and says a question the notes do not cover is never out of domain; the refused
    examples stay the four narrow ones."""
    de, en = engine.system_prompt("de", "MiniMind"), engine.system_prompt("en", "MiniMind")
    for word in ("Erbrecht", "Pflichtteil", "Erbvorbezug", "Urteilsunfähigkeit", "Vorsorgeauftrag",
                 "Patientenverfügung", "Pflege und Betreuung von Angehörigen", "Betreuungsgutschriften",
                 "Entlastung", "Gesundheit, soweit sie Arbeit", "macht sie nie zu \"out_of_domain\""):
        assert word in de, word
    for word in ("inheritance law", "compulsory shares", "incapacity", "advance care directives",
                 "care for relatives and its costs", "health as it bears on work",
                 "never makes it \"out_of_domain\""):
        assert word in en, word
    assert "Kochrezept, ein Sportergebnis, Programmierhilfe, eine medizinische Diagnose" in de
    assert "a recipe, a sports result, programming help, a medical diagnosis" in en
    assert engine.PROMPT_VERSION == "chatbot-prompt@1.2.0"
