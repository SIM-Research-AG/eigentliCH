"""What a member reads is prose, guaranteed on the string rather than requested in a prompt.

`SYSTEM_DE` asked for at most 200 words, no headings, no tables, no emoji. Asked "kann ich in vier Jahren
aufhören, ohne den Lebensstandard zu ändern?", the model returned 645 words under six numbered headings,
with two tables, sixteen emoji, horizontal rules and a closing "Fazit". Tightening the wording of the
rule made the answer longer. `services/prose.py` is what replaced asking.
"""

from __future__ import annotations

from eigentlich.services import prose


def test_plain_prose_is_returned_untouched():
    """The important half. A repair that rewrites a correct answer is worse than no repair."""
    text = "Ihre Rente beträgt CHF 37'680 im Jahr [2]. Das deckt nicht alles, was Sie angegeben haben."
    out, removed = prose.for_member(text)
    assert out == text
    assert removed == {}


def test_headings_become_their_own_line_and_are_counted():
    out, removed = prose.for_member("## 1. Rente vs. Kapital\nDie Rente zahlt lebenslang.")
    assert out == "1. Rente vs. Kapital\nDie Rente zahlt lebenslang."
    assert removed["headings"] == 1


def test_the_pillars_keep_their_numbers():
    """The reason there is no numbered-list rule, and it is not a style preference.

    «1. Säule», «2. Säule», «3. Säule» are the subject of half this corpus and their numbers are the whole
    of what tells them apart. A de-listing pass that stripped a leading `2. ` turned «2. Säule ist die
    Pensionskasse» into «Säule ist die Pensionskasse», which is not a shorter sentence but a wrong one.

    Planted violation: restoring `_NUMBERED` to `flatten`. This went red on both assertions.
    """
    out, _ = prose.for_member("2. Säule ist die Pensionskasse.\n3. Säule ist freiwillig.")
    assert "2. Säule" in out
    assert "3. Säule" in out


def test_a_table_becomes_one_line_per_row_and_rows_do_not_run_together():
    """Planted violation: the regex version produced `Faktor — WarumUmwandlungssatz — bestimmt die Rente`.

    Removing the divider left its newlines to be collapsed by the blank-line pass afterwards, which
    welded the header row onto the first body row. Walking the lines is what fixed it.
    """
    table = ("| Faktor | Warum |\n"
             "|--------|-------|\n"
             "| Umwandlungssatz | bestimmt die Rente |\n"
             "| Altersguthaben | Grundlage der Rechnung |")
    out, removed = prose.for_member(table)
    assert out.splitlines() == [
        "Faktor — Warum",
        "Umwandlungssatz — bestimmt die Rente",
        "Altersguthaben — Grundlage der Rechnung",
    ]
    assert removed["table_rows"] >= 3


def test_emoji_go_and_swiss_punctuation_stays():
    """Deliberately not "strip everything above U+2500": the quotation marks this product uses live there.

    `«»` are U+00AB/BB, but the em-dash, the apostrophe in `37'680` and `€` are all in ranges a careless
    sweep would take, and every one of them belongs in a Swiss financial sentence.
    """
    out, removed = prose.for_member("📌 Ihre Rente — «lebenslang» — beträgt CHF 37'680. ✅")
    assert out == "Ihre Rente — «lebenslang» — beträgt CHF 37'680."
    assert removed["pictograms"] == 2


def test_bullets_and_rules_lose_their_marks_and_keep_their_words():
    out, _ = prose.for_member("---\n- Die Rente zahlt lebenslang.\n- Das Kapital gehört Ihnen.")
    assert out == "Die Rente zahlt lebenslang.\nDas Kapital gehört Ihnen."


def test_bold_markers_go_without_touching_the_words():
    out, _ = prose.for_member("Die **Rente** zahlt __lebenslang__.")
    assert out == "Die Rente zahlt lebenslang."


def test_no_word_is_added_removed_or_reordered():
    """The property that keeps `unverifiable_figures` meaningful after the repair.

    The audit reads the text the member reads. If this rewrote anything, a figure that was traceable
    before could stop being traceable after, and the audit would be measuring a different string.
    """
    source = ("## Überschrift\n\n- **CHF 37'680** im Jahr [2]\n\n| a | b |\n|---|---|\n| 1'000 | 2'000 |")
    out, _ = prose.for_member(source)
    for figure in ("37'680", "1'000", "2'000", "[2]"):
        assert figure in out


def test_a_passage_is_flattened_before_the_model_sees_it():
    """The cause, not the symptom. The authored corpus is Markdown, so the model was shown a shape.

    Asking a model for plain prose while handing it six passages of headings and bullet lists is asking
    it to ignore everything in front of it, and it does not.
    """
    assert prose.for_prompt("## Titel\n\n- ein Punkt") == "Titel\nein Punkt"


def test_empty_text_survives():
    assert prose.for_member("") == ("", {})
