"""S-08, The Know. The boundary in place, grounding, citations, and the K3 obligation A36 created.

The model is stubbed throughout. Phase 4's gate is "C-01 enforced server-side and provably not by prompt
alone" — and the proof is that these pass with nothing running.

**This file tests the QUOTING contract, and since 21 September 2026 that is no longer the default.** The
owner reversed C-11 that day: a member now gets an answer the model composed, and `services/compose.py`
states what the reversal costs. The quoting path is not gone — it is one environment variable away, it is
what a deployment that wants C-11 back will run, and every check it ran as a gate it still runs as a gate.
So these tests keep it honest rather than describing history, and the autouse fixture below is what makes
them tests of that path rather than of whatever the default happens to be.

The composing contract is `test_compose.py`.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from eigentlich import llm
from eigentlich.models import Curator, CuratorSession, CuratorSessionEvent
from eigentlich.services.directory import NoSuchCurator
from eigentlich.services import store_item
from eigentlich.services.know import (
    MAX_PASSAGES,
    MAX_QUOTES,
    Passage,
    action_items,
    ask,
    open_curator_session,
    quotable_sentences,
    render,
    retrieve,
    unquoted_sentences,
)
from eigentlich.services.vault import VaultStore, action_item_for_expiry


@pytest.fixture(autouse=True)
def quoting(monkeypatch):
    """Every test in this file asserts the quoting contract, so every test in this file runs in it.

    Autouse and module-wide rather than per test: the alternative is thirty-eight decorators and one of
    them missing, which is the shape of defect this suite keeps finding. A test here that wants the
    composing path should move to `test_compose.py`, not opt out.
    """
    from eigentlich.services import know

    monkeypatch.setattr(know, "ANSWER_MODE", "quote")



# ------------------------------------------------------------------------------------------------------
# **Why these questions are phrased in the first person.**
#
# Item 1's router (3 September 2026) splits a question by regulatory status: a question about the world is
# branch 1 and is answered WITHOUT the member's vault; a question about the member is branch 2 and reads
# it. Most of the tests below are about the answering machinery — selection, quoting, the citation
# markers, the cap, the outbound gate — and use vault items as convenient passages. They ask "was steht in
# meinem …" rather than "was ist ein …" so that their own fixtures are in scope.
#
# That is a change of question, not a weakening of the test: "Was ist ein Freizügigkeitskonto?" is a fact
# about the world and quoting the member's own bank statement at it was the behaviour item 1 removes.
# `tests/test_router.py` is where the branch decision itself is pinned.
# ------------------------------------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def vault(session, store, member):
    items = [
        store_item(session, store, member_id=member.id, kind="policy",
                   title="Freizügigkeitskonto bei der Bank Y", source="upload", data=b"x",
                   notes="Guthaben aus der Pensionskasse, in bar gehalten."),
        store_item(session, store, member_id=member.id, kind="statement",
                   title="Steuererklärung 2026", source="upload", data=b"y"),
    ]
    session.commit()
    return items


@pytest.fixture()
def answering(monkeypatch):
    """Stub the model with a fixed raw reply.

    Still here, and still meaningful, after the answer became extractive: `ask` runs C-01's outbound gate
    on the model's **raw** reply before anything is parsed out of it, so a stub that argues a case instead
    of naming sentence numbers is exactly the "the model ignored its instructions" path.
    """
    def install(text):
        monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply(text=text, model="stub"))
    return install


@pytest.fixture()
def selecting(monkeypatch):
    """Stub the model the way the extractive path actually uses it: it answers with sentence numbers.

    `install([1])` makes every source offer its first quotable sentence; `install([])` makes every source
    choose nothing, which is a right answer and has to be testable as one.
    """
    def install(numbers):
        import json

        monkeypatch.setattr(
            llm, "chat",
            lambda *a, **k: llm.Reply(text=json.dumps({"saetze": numbers}), model="stub"),
        )
    return install


# ============================================================ the boundary, in place
def test_the_specs_acceptance_example_is_now_answered_rather_than_refused(session, member, vault):
    """**Build-spec §S-08's acceptance example no longer holds, and this is where that is recorded.**

    The spec says of "Should I buy fund X with my 10,000?" that the system "explains the boundary and
    offers a curator; it does not answer". That was C-01's inbound gate, and it was the specification's
    single most concrete statement about the boundary. C-01 was withdrawn by the owner on 20 September
    2026 (A160, A164) and the sentence in the spec is now false.

    It is asserted in its new form rather than deleted, because a spec criterion that silently stops
    being tested is one nobody discovers has lapsed. What happens now: the question is routed like any
    other, `asks_about_the_member` sees "I" and "my" and routes it to the member branch, retrieval runs,
    and the member gets whatever the corpus has — here, nothing. No boundary is explained, no curator is
    offered, and nothing in the system treats the question as different from "how does the AHV cap work".

    If the owner ever reinstates a gate, this test is the one that should go red first.
    """
    answer = ask(session, member_id=member.id,
                 question="Should I buy fund X with my 10,000?", language="en")

    assert answer.requires_curator is False, "nothing refuses this question any more"
    assert answer.reason is None, "there is no refusal reason, because there was no refusal"
    # The text may still mention a curator, and that is R-170 rather than C-01: the offer of a human is
    # present on every surface at all times. What is gone is the refusal that made the offer mandatory
    # and the answer impossible. The distinction is the whole of what this test is pinning.
    assert answer.route["branch"] == "member_situation", (
        "the question says 'I' and 'my', so it is about the member and their vault may be read. That is "
        "the surviving split (C-04/C-05), and it is not a judgement about advice."
    )
def test_the_answer_is_the_retrieved_sentence_itself(session, member, vault, selecting):
    """The owner's decision of 1 September 2026, in one assertion.

    The model named a sentence; what the member reads is that sentence, in quotation marks, with the index
    of its citation. Not a summary of it, not a sentence about it. The text is checkable against the
    passage character for character, which is the property the whole change exists to buy.
    """
    selecting([1])
    answer = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert answer.requires_curator is False
    assert answer.text == (
        "„Freizügigkeitskonto bei der Bank Y Guthaben aus der Pensionskasse, in bar gehalten.“ [1]"
    )
    retrieved = retrieve(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")
    assert unquoted_sentences(answer.text, retrieved) == []
    assert answer.quotes[0]["text"] in retrieved[0].text, "the quote is a substring of the passage"


def test_choosing_nothing_says_so_rather_than_quoting_badly(session, member, vault, selecting):
    """Material came back and none of it answers. That is a right answer and it has to be reachable.

    Quoting badly is worse than refusing: a true sentence about something else, wearing a citation, is
    the same trap as a false sentence wearing one — the citation makes it look checked.
    """
    selecting([])
    answer = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert answer.requires_curator is False
    assert answer.citations == []
    assert answer.quotes == []
    assert "kein Satz" in answer.text


def test_a_sentence_number_the_source_does_not_have_is_discarded(session, member, vault, selecting):
    """`interpret.py`'s rule: a value that cannot be traced to the source is dropped, not caveated."""
    selecting([99])
    answer = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert answer.quotes == []
    assert "kein Satz" in answer.text


def test_a_source_that_names_too_many_sentences_contributes_none(session, member, vault, selecting):
    """A model that named more sentences than a source may contribute has not chosen between them.

    Measured, not hypothetical: a single pass over 142 sentences returned a consecutive run of seventy
    numbers. Truncating such a list to the first two would be this module choosing while reporting that
    the model did.
    """
    selecting([1, 1, 1])
    answer = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert answer.quotes == []


def test_a_reply_that_is_not_a_list_of_numbers_selects_nothing(session, member, vault, monkeypatch):
    """Prose in the numbers slot is not an answer. It is silence — and then the honest notice."""
    monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply(text="Das steht in Absatz zwei.",
                                                               model="stub"))
    answer = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert answer.quotes == []
    assert answer.requires_curator is False
    assert "kein Satz" in answer.text


# ============================================================ R-171 grounding and citations


def test_an_answer_cites_what_it_drew_on(session, member, vault, selecting):
    """R-171. Answers cite which vault items or learning units they drew on."""
    selecting([1])
    answer = ask(session, member_id=member.id, question="Was ist mein Freizügigkeitskonto?")

    assert answer.citations
    assert any(c["kind"] == "vault_item" for c in answer.citations)
    assert any("Freizügigkeitskonto" in c["title"] for c in answer.citations)


def test_each_marker_names_its_own_citation(session, store, member, selecting):
    """R-171 under quoting: the citation and the quoted text agree about where the words came from.

    `[i]` is `citations[i - 1]` by construction — the list is built from the quotes, in their order — so
    there is no arrangement in which a member follows a marker to the wrong document. This plants two
    sources whose sentences are distinguishable and checks the pairing rather than the count.
    """
    store_item(session, store, member_id=member.id, kind="note", title="Notiz Alpha",
               source="manual", notes="Alpha beschreibt das Vorsorgekonto ausführlich genug.")
    store_item(session, store, member_id=member.id, kind="note", title="Notiz Beta",
               source="manual", notes="Beta beschreibt das Vorsorgekonto ebenfalls ausführlich.")
    session.commit()

    selecting([1])
    answer = ask(session, member_id=member.id, question="meine Vorsorgekonto Notiz")

    assert len(answer.quotes) == len(answer.citations) >= 2
    for index, quote in enumerate(answer.quotes):
        marked = f"„{quote['text']}“ [{index + 1}]"
        assert marked in answer.text, f"marker {index + 1} does not carry its own quote"
        assert answer.citations[index] == quote["citation"], (
            "the citation under a marker is not the source the quoted words came from"
        )
        # Alpha's sentence must sit under Alpha's citation and Beta's under Beta's. A vault item's
        # searchable text opens with its own title, so the two are distinguishable by inspection.
        assert quote["citation"]["title"] in quote["text"]


def test_retrieval_prefers_the_relevant_document(session, member, vault):
    passages = retrieve(session, member_id=member.id, question="Freizügigkeitskonto Guthaben")
    assert passages
    assert "Freizügigkeit" in passages[0].title


def test_retrieval_is_capped(session, store, member):
    for i in range(MAX_PASSAGES + 4):
        store_item(session, store, member_id=member.id, kind="note",
                   title=f"Vorsorge Notiz {i}", source="manual", notes="Vorsorge Vorsorge")
    session.commit()
    assert len(retrieve(session, member_id=member.id, question="meine Vorsorge Notiz")) == MAX_PASSAGES


def test_nothing_retrieved_says_so_rather_than_inventing(session, member, vault, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("must not ask a model with no grounding"))
    answer = ask(session, member_id=member.id, question="Wie hoch ist der Goldpreis in Singapur?")
    assert answer.citations == []
    assert answer.requires_curator is False


def test_the_model_receives_only_retrieved_passages(session, member, vault, monkeypatch):
    """A model cannot disclose what it was never given.

    The prompt must contain the retrieved titles and must NOT contain the member's id or any document the
    retrieval did not select. **Every** prompt is checked, not the last one: selection is one call per
    source now, and a test that looked at whichever call happened to be last would have stopped asking the
    question of the other five.
    """
    seen = []

    def capture(prompt, **kwargs):
        seen.append(prompt)
        return llm.Reply(text='{"saetze": []}', model="stub")

    monkeypatch.setattr(llm, "chat", capture)
    ask(session, member_id=member.id, question="mein Freizügigkeitskonto")

    assert seen, "the model was not called at all, so this test proves nothing"
    assert any("Freizügigkeitskonto" in prompt for prompt in seen)
    for prompt in seen:
        assert member.id not in prompt, "the member id has no business in a model prompt"
        assert "Steuererklärung" not in prompt, "an unretrieved document must not be included"


# ============================================================ A36's obligation


def test_nothing_in_the_know_logs_a_prompt_or_a_completion(session, member, vault, answering, caplog):
    """A36 permits the model to read K3, and that creates this obligation.

    The C-04 filter drops K3 by FIELD NAME, and a prompt is not a field — it is a paragraph containing
    one. So the rule here is that prompts and completions are never logged at all.
    """
    answering("Ein Freizügigkeitskonto hält Vorsorgeguthaben.")
    with caplog.at_level(logging.DEBUG):
        ask(session, member_id=member.id, question="Was ist mein Freizügigkeitskonto?")

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Freizügigkeitskonto bei der Bank Y" not in logged
    assert "Vorsorgeguthaben" not in logged


def test_the_know_service_contains_no_logging_of_text(session):
    """Enforced by absence, checked in the source. A logger added later should have to justify itself."""
    import pathlib

    source = (pathlib.Path(__file__).parent.parent / "eigentlich" / "services" / "know.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("logger.", "logging.getLogger", "print("):
        assert forbidden not in source, f"know.py contains {forbidden!r}"


# ============================================================ degradation


def test_an_unreachable_model_says_so_and_keeps_the_citations(session, member, vault, monkeypatch):
    def boom(*a, **k):
        raise llm.LocalModelUnavailable("nothing listening")

    monkeypatch.setattr(llm, "chat", boom)
    answer = ask(session, member_id=member.id, question="mein Freizügigkeitskonto")

    assert answer.unavailable is True
    assert answer.as_dict()["answered"] is False
    assert answer.citations, "the documents are still there even when the model is not"
    assert answer.requires_curator is False


def test_one_failed_selection_call_makes_the_whole_answer_unavailable(session, store, member,
                                                                     monkeypatch):
    """Selection is several calls now, and a partial search must not be reported as an answer.

    A member cannot see which source went missing, and the missing one is as likely as not the one that
    answered. So one timeout out of six is "not available" and not "here is what the other five said".
    """
    for index in range(3):
        store_item(session, store, member_id=member.id, kind="note", title=f"Vorsorge Notiz {index}",
                   source="manual",
                   notes="Diese Notiz beschreibt die Vorsorge und ist lang genug zum Zitieren.")
    session.commit()

    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise llm.LocalModelUnavailable("the second source timed out")
        return llm.Reply(text='{"saetze": [1]}', model="stub")

    monkeypatch.setattr(llm, "chat", flaky)
    answer = ask(session, member_id=member.id, question="meine Vorsorge Notiz")

    assert answer.unavailable is True
    assert answer.quotes == [], "a part-searched corpus must not be quoted from"


def test_a_selection_pass_that_runs_past_its_budget_is_unavailable(session, store, member,
                                                                   monkeypatch):
    """Selection is one turn per source, so a per-turn timeout bounds the wait at seven times itself.

    Five minutes in front of a panel reading "Wird gelesen …" is not a degradation, it is an abandonment.
    The whole pass has a budget and blowing it is the same honest notice as a daemon that is not running.

    **Planted violation:** removed the deadline check from the head of `select_quotes`'s loop. The answer
    came back quoted and the budget meant nothing. Restored.
    """
    for index in range(4):
        store_item(session, store, member_id=member.id, kind="note", title=f"Vorsorge Notiz {index}",
                   source="manual",
                   notes="Diese Notiz beschreibt die Vorsorge und ist lang genug zum Zitieren.")
    session.commit()

    monkeypatch.setattr(llm, "SELECTION_BUDGET_S", -1.0)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: llm.Reply(text='{"saetze": [1]}', model="stub"))

    answer = ask(session, member_id=member.id, question="meine Vorsorge Notiz")

    assert answer.unavailable is True
    assert answer.quotes == []
    assert answer.citations, "the documents are still there even when the answer is not"


# ============================================================ the guard the decision rests on
#
# Every one of these was planted, watched to fail, and restored. What was planted is written on each.


def _two_passages():
    return [
        Passage("book_passage", "b#1", "Merkblatt",
                "Der Bezug kann um ein bis höchstens fünf Jahre aufgeschoben werden. "
                "Der Anteil muss zwischen 20 % und 80 % liegen.", 1),
        Passage("book_passage", "b#2", "Anderes", "Das Referenzalter liegt bei 65 Jahren.", 1),
    ]


def test_a_quoted_span_that_is_in_no_passage_is_reported():
    """The half that catches an assembly which stopped quoting.

    **Planted violation:** made `render` wrap `quote.text.replace("aufgeschoben", "gekürzt")` — the exact
    sign inversion A103 recorded, one word changed inside an otherwise verbatim span. It was reported
    here and refused by `ask`. Restored.
    """
    fabricated = "„Der Bezug kann um ein bis höchstens fünf Jahre gekürzt werden.“ [1]"
    assert unquoted_sentences(fabricated, _two_passages()) == [
        "Der Bezug kann um ein bis höchstens fünf Jahre gekürzt werden."
    ]


def test_a_word_standing_outside_the_quotation_marks_is_reported():
    """The half that matters, and the one that makes "nothing unquoted reaches a member" checkable.

    A lead-in, a linking sentence, an "also gilt:" — anything composed rather than quoted stands outside
    the marks by construction, and every one of them is a sentence nobody can trace to a source.
    """
    with_commentary = (
        "Kurz gesagt: „Das Referenzalter liegt bei 65 Jahren.“ [1] Daraus folgt ein Aufschub."
    )
    reported = unquoted_sentences(with_commentary, _two_passages())
    assert len(reported) == 1
    assert "Kurz gesagt" in reported[0] and "Daraus folgt" in reported[0]


def test_the_markers_this_module_writes_are_not_read_as_prose():
    """The false-positive direction. `[1]` is scaffolding, not an invented sentence.

    A guard that reported its own punctuation would refuse every answer and prove nothing, which is the
    failure mode `unverifiable_figures` had to be rescued from twice.
    """
    honest = "„Das Referenzalter liegt bei 65 Jahren.“ [2]"
    assert unquoted_sentences(honest, _two_passages()) == []


def test_markup_and_separators_do_not_defeat_the_check():
    """A quoted span is cleaned of markdown emphasis before a member sees it, and must still verify.

    `_fold_for_quoting` is applied to the answer and to the passage alike, so it can only ever accept a
    difference this module itself introduced. If it stopped doing that, real answers would be refused —
    which is how `unverifiable_figures` learned that `7'258` and `7 258` are one figure.
    """
    passage = Passage("book_passage", "b#3", "Merkblatt",
                      "Der Anteil muss zwischen **20 %  und   höchstens 80 %** der Rente liegen.", 1)
    assert unquoted_sentences(
        "„Der Anteil muss zwischen 20 % und höchstens 80 % der Rente liegen.“ [1]", [passage]
    ) == []


def test_the_quotation_check_is_not_vacuous():
    """Guard on the guard: with no passages, every quoted span is unverifiable.

    If this returned an empty list the function would be incapable of reporting anything and the three
    tests above would pass for the wrong reason.
    """
    assert unquoted_sentences("„Irgendein Satz.“ [1]", []) == ["Irgendein Satz."]


def test_prose_added_to_the_rendered_answer_is_refused_end_to_end(session, member, vault, selecting,
                                                                 monkeypatch):
    """The guard wired into `ask`, proven by planting the violation it exists for.

    **Planted violation:** `render` is replaced with one that appends a sentence of its own — the shape of
    every regression this change could suffer, because "let me just add a lead-in so it reads better" is
    the most natural edit anyone will ever make to this module. The member gets the notice, not the
    sentence.
    """
    selecting([1])
    honest = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")
    assert honest.reason != "not_quoted", "the baseline answer must pass before the plant means anything"

    monkeypatch.setattr(
        "eigentlich.services.know.render",
        lambda quotes: render(quotes) + " Daraus folgt, dass das Guthaben gebunden bleibt.",
    )
    planted = ask(session, member_id=member.id, question="Was steht in meinem Freizügigkeitskonto?")

    assert planted.reason == "not_quoted"
    assert "Daraus folgt" not in planted.text, "the unquoted sentence must not leak through the refusal"
    assert "Guthaben gebunden" not in planted.text
def test_the_answer_is_capped_at_three_quotes(session, store, member, selecting):
    """A quotation is read; a wall of quotation is skipped, and a member who skips it has been given
    nothing. Six sources each offering a sentence must still come out as at most three."""
    for index in range(MAX_QUOTES + 3):
        store_item(session, store, member_id=member.id, kind="note", title=f"Vorsorge Notiz {index}",
                   source="manual",
                   notes="Diese Notiz beschreibt die Vorsorge und ist lang genug zum Zitieren.")
    session.commit()

    selecting([1])
    answer = ask(session, member_id=member.id, question="meine Vorsorge Notiz")

    assert 0 < len(answer.quotes) <= MAX_QUOTES
    assert len(answer.citations) == len(answer.quotes)


# ============================================================ splitting a passage into quotable units


def test_an_ordinal_does_not_end_a_sentence():
    """"am 1. Januar 2026" and "ab dem 63. Altersjahr" are one statement, not two.

    **Planted violation:** removed the `token.isdigit()` arm of `_ends_in_abbreviation`. The Merkblatt
    passages split mid-date and the member would have been quoted the words "Januar 2026, bezogen über
    www.ahv-iv.ch" as a sentence. Restored.
    """
    split = quotable_sentences(
        "Der Beitrag gilt ab dem 1. Januar 2026 und wird jährlich angepasst. "
        "Der Bezug ist ab dem 63. Altersjahr möglich, monatlich abrufbar."
    )
    assert len(split) == 2
    assert split[0].startswith("Der Beitrag gilt ab dem 1. Januar 2026")


def test_a_heading_is_not_quotable():
    """A heading labels an argument; quoted at a member it reads as an assertion it never made."""
    assert quotable_sentences("# Der Bezug eines 3a-Guthabens\nDas Guthaben wird fällig, sobald es "
                              "fällig wird.") == ["Das Guthaben wird fällig, sobald es fällig wird."]


def test_every_quotable_sentence_is_a_substring_of_its_passage():
    """The property `unquoted_sentences` depends on, asserted where it is created rather than where it is
    checked. A list marker is removed from the front, which leaves a substring; nothing inside is."""
    passage = (
        "## Die Beträge\n"
        "- **Mindestbeitrag 530 Franken im Jahr**, bei einem Vermögen unter 350 000 Franken.\n"
        "- Höchstbeitrag 26 500 Franken im Jahr, erreicht bei 8 950 000 Franken.\n"
    )
    for sentence in quotable_sentences(passage):
        assert sentence in passage, f"not a substring of the passage it came from: {sentence!r}"


# ============================================================ R-173, R-174, R-003


@pytest.fixture()
def kuratorin(session):
    """A real `curators` row. Required since 31 August 2026, and that is the point of it.

    `CuratorSession.curator_id` is a foreign key now (A67's correction to A40) and this function resolves
    the id before writing, so the `"curator:nb"` string these tests used to pass is refused twice over.
    """
    row = Curator(display_name="Eine Kuratorin", email="kuratorin@example.ch", role_label="Kurator")
    session.add(row)
    session.commit()
    return row


def test_the_curator_button_records_the_screen_it_was_opened_from(session, member, kuratorin):
    """R-173 / C-10."""
    record = open_curator_session(session, member_id=member.id, curator_id=kuratorin.id,
                                  opened_from="know_panel")
    session.commit()

    assert record.opened_from == "know_panel"
    assert record.curator_id == kuratorin.id
    events = session.query(CuratorSessionEvent).filter_by(session_id=record.id).all()
    assert [e.kind for e in events] == ["opened"]
    assert events[0].detail["opened_from"] == "know_panel"


@pytest.mark.parametrize("named", ["curator:nb", "unassigned", "", "   ", None])
def test_the_curator_button_refuses_a_curator_who_is_not_a_row(session, member, kuratorin, named):
    """C-10 at the service layer, which is where A67 left the hole open.

    A67 closed `POST /api/curator/sessions` by resolving the curator in the route. This function is the
    opener *underneath* that route, and it took the id on trust — so any caller that was not an HTTP
    request could still write an invented curator into the parent row of an append-only audit. It resolves
    now, and the foreign key refuses independently if this ever stops.

    **Planted violation:** removed the `resolve_curator` call from `services/know.open_curator_session`.
    All five cases failed, on `flush()`, with an `IntegrityError` about the column rather than a
    `NoSuchCurator` about the curator — the storage layer holding while the service layer does not, which
    is the arrangement A63 says must never be the only one. Restored.
    """
    with pytest.raises(NoSuchCurator):
        open_curator_session(session, member_id=member.id, curator_id=named, opened_from="know_panel")
    session.rollback()
    assert session.query(CuratorSession).count() == 0, "nothing may reach the table"
    assert session.query(CuratorSessionEvent).count() == 0


def test_action_items_are_listed_with_their_options(session, store, member):
    """R-174. Each expandable to its prepared options and their consequences."""
    # Storing a document with an expiry IS what creates the item now — R-152 calls expiry the primary
    # source of action items, and until this was wired the item had to be inserted by hand here, which is
    # how the gap stayed invisible.
    store_item(session, store, member_id=member.id, kind="policy", title="Police",
               source="upload", data=b"x", expiry_date=date(2027, 3, 31))
    session.commit()

    listed = action_items(session, member_id=member.id)
    assert len(listed) == 1
    assert len(listed[0]["prepared_options"]) >= 2
    assert all(o["consequence"] for o in listed[0]["prepared_options"])


def test_action_items_return_no_count(session, member):
    """R-003. Items in a list, never a count, a dot or a badge on navigation."""
    listed = action_items(session, member_id=member.id)
    assert isinstance(listed, list)
    assert listed == []


def test_storing_a_document_with_an_expiry_raises_an_action_item(session, store, member):
    """R-152. The wire that was missing: nothing outside a test created an ActionItem, so /api/actions was
    empty in the running application forever and the requirement was met on paper only."""
    assert action_items(session, member_id=member.id) == []

    store_item(session, store, member_id=member.id, kind="policy", title="Hausrat",
               source="upload", data=b"x", expiry_date=date(2028, 6, 30))
    session.commit()

    listed = action_items(session, member_id=member.id)
    assert len(listed) == 1
    assert listed[0]["due_date"] == "2028-06-30"
    assert len(listed[0]["prepared_options"]) >= 2


def test_a_document_without_an_expiry_raises_nothing(session, store, member):
    store_item(session, store, member_id=member.id, kind="note", title="Notiz", source="manual",
               notes="kein Ablauf")
    session.commit()
    assert action_items(session, member_id=member.id) == []


def test_superseding_a_document_retires_its_action_item(session, store, member):
    """An item raised by a policy that has since been replaced is not news.

    Filtered at read time from the vault's own notion of "current" rather than by mutating the item's
    status: marking it `acted` would assert the member renewed, and they may simply have uploaded a
    better scan. A query-time fact needs no inference.
    """
    first = store_item(session, store, member_id=member.id, kind="policy", title="Police 2027",
                       source="upload", data=b"x", expiry_date=date(2027, 3, 31))
    session.commit()
    assert len(action_items(session, member_id=member.id)) == 1

    store_item(session, store, member_id=member.id, kind="policy", title="Police 2028",
               source="upload", data=b"y", expiry_date=date(2028, 3, 31), supersedes=first)
    session.commit()

    listed = action_items(session, member_id=member.id)
    assert len(listed) == 1, "the superseded document's item is retired, the new one's stands"
    assert listed[0]["due_date"] == "2028-03-31"


# ============================================================ the numeric faithfulness check


def _ahv_passage():
    from eigentlich.services.know import Passage

    return [
        Passage(
            "book_passage",
            "ahv#1",
            "AHV",
            "Mindestbeitrag 530 Franken. Hoechstbeitrag, erreicht bei 8 950 000 Franken, 26 500 "
            "Franken. Ueber 1 750 000 Franken erhoeht sich der Beitrag um 159 Franken pro 50 000. "
            "Monatliche Abstufung 0,6 %. Teilbezug zwischen 20 % und 80 %. Referenzalter 65. "
            "Saeule 3a. Artikel 2. Stand am 1. Januar 2026.",
            1,
        )
    ]


VERIFIABLE = [
    "Der Mindestbeitrag betraegt 530 Franken.",
    "Der Hoechstbeitrag betraegt 26'500 Franken.",          # apostrophe against a spaced source
    "Ab 8'950'000 Franken.",
    "Die monatliche Abstufung ist 0,6 Prozent.",
    "Teilbezug zwischen 20 und 80 Prozent.",
    "Stand 2026.",
    "Artikel 2. Absatz 3.",                                  # ordinals, not a figure `23`
    "Die Saeule 3a, ein bis fuenf Jahre.",                   # single digits are not quantities
]

INVENTED = [
    ("Der Maximalbetrag ist 7'258 Franken.", "7'258"),
    ("Der Umwandlungssatz betraegt 6,8 Prozent.", "6,8"),    # a rate, and only two digits
    ("Die Grenze liegt bei 500 Franken.", "500"),            # a substring of 26 500, not a figure in it
    ("Ein Betrag von 265 Franken.", "265"),
]


@pytest.mark.parametrize("answer", VERIFIABLE)
def test_a_figure_present_in_the_sources_is_not_flagged(answer):
    """The false-positive direction, which decides whether this check is usable at all.

    A figure written with a different separator is the same figure, an ordinal is not a quantity, and a
    year the corpus states is verifiable. A check that refused these would refuse almost every real answer.
    """
    from eigentlich.services.know import unverifiable_figures

    assert unverifiable_figures(answer, _ahv_passage()) == []


@pytest.mark.parametrize("answer,expected", INVENTED)
def test_a_figure_absent_from_the_sources_is_flagged(answer, expected):
    """The point of the check: a member cannot verify a number that is in none of their sources.

    `500` and `265` are the interesting pair. Both are substrings of `26 500`, and the first version of
    this function matched against the passages' concatenated digits, so both were silently confirmed. A
    figure has to match a figure.

    `6,8` is the other one: the length floor started at three digits, so a hallucinated conversion rate —
    exactly as damaging as a hallucinated amount — passed the check written to catch it.
    """
    from eigentlich.services.know import unverifiable_figures

    assert unverifiable_figures(answer, _ahv_passage()) == [expected]


def test_the_figure_check_is_not_vacuous():
    """Guard on the guard: with no passages, every checked figure must be unverifiable.

    If this returned an empty list the function would be incapable of reporting anything and both tests
    above would pass for the wrong reason.
    """
    from eigentlich.services.know import unverifiable_figures

    assert unverifiable_figures("530 Franken und 26'500 Franken.", []) == ["530", "26'500"]


def test_the_misapplied_figure_is_deliberately_not_caught():
    """**The limit of this check, made executable so it cannot be forgotten.**

    The observed failure was an answer that took the 20–80 % Teilbezug band — genuinely in the corpus —
    and presented it as a range of pension reductions. Every figure verifies and the sentence is false.
    This test exists so that "the numeric check closes the wrong-law problem" cannot be believed by
    anyone reading only the two tests above. Closing it needs an entailment check; see A76 and the open
    note in DECISIONS.md.
    """
    from eigentlich.services.know import unverifiable_figures

    false_but_grounded = "Die Kuerzung liegt zwischen 20 % und 80 % der Altersrente."
    assert unverifiable_figures(false_but_grounded, _ahv_passage()) == [], (
        "if this now reports something, the check has grown beyond arithmetic and this test should be "
        "re-read rather than deleted"
    )
