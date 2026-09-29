"""The impersonal ground: the approval gate, the relevance floor, and every way this degrades.

**Nothing here needs Ollama or the estate.** The index is planted in a temporary directory and the
embedding model is stubbed with a fixed vector, so the arithmetic is exact and the assertions are about
the code rather than about this machine. The two tests that do use the real corpus say so in their names
and skip when it is absent — A34's rule for the model, applied to the corpus.

The load-bearing property in this file is the approval gate. Everything else here decides how *well* The
Know answers; the gate decides whether an unreviewed draft can reach a member at all, and there is no
degraded mode in which it should.
"""

from __future__ import annotations

import array
import json
import logging
import math
import pathlib

import re

import pytest

from eigentlich import llm
from eigentlich.services import grounding
from eigentlich.services.know import ask, retrieve

# Passage vectors are the first two axes of a 3-space; a stubbed query vector picks a cosine off each of
# them exactly. 0.75² + 0.50² + 0.4330127² = 1, so both stubs below are unit vectors and the dot product
# with an axis IS the coordinate.
_NEAR_FIRST = [0.75, 0.5, 0.4330127018922193]
_NEAR_SECOND = [0.5, 0.75, 0.4330127018922193]

_AHV = (
    "Die AHV-Beiträge werden vom Lohn abgezogen und je zur Hälfte von Arbeitgeber und "
    "Arbeitnehmerin getragen. Nichterwerbstätige zahlen einen Mindestbeitrag."
)
_BOOK = (
    "Capital saturation describes the point beyond which additional capital ceases to raise output. "
    "The curve flattens and the marginal contribution approaches zero."
)


def _postings(texts: list[str]) -> dict[str, list[int]]:
    """The inverted index the real builder writes, by the same folding rule — ASCII, len > 2."""
    post: dict[str, list[int]] = {}
    for i, text in enumerate(texts):
        for term in set(grounding._WORD.findall(grounding._fold(text))):
            if len(term) > 2:
                post.setdefault(term, []).append(i)
    return post


def plant_index(directory: pathlib.Path, *, vectors: bool = True, model: str = "stub-embed"):
    """A two-passage index in the shape `desktop/bookindex/` writes, for a test to point at."""
    directory.mkdir(parents=True, exist_ok=True)
    passages = [
        {"text": _AHV, "work": "AHV: Beiträge und flexibler Rentenbezug", "chapter": "2 Die Beiträge",
         "section": "", "source": "ahv.md"},
        {"text": _BOOK, "work": "Capital Saturation", "chapter": "From Theory to Measurement",
         "section": "10.5 The saturation point", "source": "10-05.html"},
    ]
    meta = {
        "passages": passages,
        "dim": 3 if vectors else 0,
        "model": model if vectors else "",
        "postings": _postings([p["text"] for p in passages]),
    }
    (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if vectors:
        rows = array.array("f", [1, 0, 0, 0, 1, 0])
        (directory / "vecs.bin").write_bytes(rows.tobytes())
    return directory


def plant_entry(directory: pathlib.Path, name: str, frontmatter: str, body: str) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # `strip("\n")` and not `strip()`: leading indentation on the first frontmatter line is one of the
    # shapes under test, and a helper that quietly tidies it up tests something other than what it says.
    path.write_text(f"---\n{frontmatter.strip(chr(10))}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return path


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    """A planted index and an empty knowledge directory, both pointed at by the environment."""
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(plant_index(tmp_path / "bookindex")))
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    grounding.reset_caches()
    yield tmp_path
    grounding.reset_caches()


@pytest.fixture()
def embedding(monkeypatch):
    """Stub the embedding model. `install(vector)` fixes what every question embeds to."""
    def install(vector):
        monkeypatch.setattr(llm, "embed", lambda text, **kw: list(vector))
    return install


@pytest.fixture()
def store(tmp_path):
    from eigentlich.services.vault import VaultStore

    return VaultStore(tmp_path / "vault")


@pytest.fixture()
def no_embedding(monkeypatch):
    def boom(*a, **k):
        raise llm.LocalModelUnavailable("nothing listening")

    monkeypatch.setattr(llm, "embed", boom)


# ==================================================================== the approval gate
#
# The one property in this module that is about safety rather than about quality. An entry in
# `content/knowledge/` is a draft until a human says otherwise, and a draft that reaches a member is a
# member reading unreviewed financial writing that looks exactly like reviewed financial writing.


def test_an_unapproved_entry_is_never_retrievable(corpus, no_embedding):
    """Plant a draft that matches the question perfectly. It must not come back.

    Perfectly, deliberately: this is not testing that a weak match is filtered out by the floor. The entry
    carries every content word of the question, so it clears every relevance threshold in the module and
    the ONLY thing that can keep it away from the member is `approved`.
    """
    plant_entry(
        corpus / "knowledge", "saeule-3a.md",
        "title: Die Säule 3a\napproved: false\nlanguage: de\nsources:\n  - Merkblatt 2.03",
        "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.",
    )
    found = grounding.search("Wie funktioniert die gebundene Selbstvorsorge Säule 3a?")

    assert found.results == (), "an unapproved draft was retrievable"
    assert not any("Selbstvorsorge" in g.text for g in found.results)


def test_an_approved_entry_is_retrievable_and_carries_its_sources(corpus, no_embedding):
    """The other half. A gate that refuses everything is not a gate, it is a wall."""
    plant_entry(
        corpus / "knowledge", "saeule-3a.md",
        "title: Die Säule 3a\napproved: true\nlanguage: de\n"
        "sources:\n  - Merkblatt 2.03, Informationsstelle AHV/IV\n  - BVV3 Art. 7",
        "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.",
    )
    found = grounding.search("Wie funktioniert die gebundene Selbstvorsorge Säule 3a?")

    assert [g.kind for g in found.results] == ["knowledge_entry"]
    entry = found.results[0]
    assert entry.title == "Die Säule 3a"
    # R-171: the member can see where it came from, and follow it.
    assert entry.sources == ("Merkblatt 2.03, Informationsstelle AHV/IV", "BVV3 Art. 7")


@pytest.mark.parametrize("declared", [
    "approved: false",
    "approved: no",
    "approved: 0",
    "approved: yes",
    "approved: pending",
    "approved: in review",
    "approved: truthy",
    "approved:",
    "approved:\n  - true",
    "aproved: true",           # a typo in the key is not an approval
    "approved_by: nicolas",    # nor is a different key that starts the same way
    "title: nur ein Titel",    # nor is no statement at all
])
def test_only_the_word_true_approves(corpus, no_embedding, declared):
    """Fail-closed in every direction, because every direction is a way a draft gets published.

    `approved: yes` is the one worth naming: it is what a person writes when they mean it, and it must
    still not work — a gate with two spellings is a gate that can be opened by a habit.
    """
    plant_entry(corpus / "knowledge", "draft.md",
                f"{declared}\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    found = grounding.search("Wie funktioniert die gebundene Selbstvorsorge Säule 3a?")
    assert found.results == (), f"{declared!r} was treated as an approval"


@pytest.mark.parametrize("spelling", ["true", "True", "TRUE", " true ", "'true'", '"true"'])
def test_the_word_true_approves_however_it_is_capitalised_or_quoted(corpus, no_embedding, spelling):
    plant_entry(corpus / "knowledge", "draft.md",
                f"approved: {spelling}\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    found = grounding.search("Wie funktioniert die gebundene Selbstvorsorge Säule 3a?")
    assert len(found.results) == 1


def test_a_file_without_frontmatter_is_not_approved(corpus, no_embedding):
    (corpus / "knowledge").mkdir(parents=True, exist_ok=True)
    (corpus / "knowledge" / "loose.md").write_text(
        "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.",
        encoding="utf-8")
    assert grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen").results == ()


def test_an_unterminated_frontmatter_block_is_not_approved(corpus, no_embedding):
    """A file whose `---` was never closed. The whole document is then frontmatter, or none of it is;
    either reading is a guess, and a guess about approval resolves to no."""
    (corpus / "knowledge").mkdir(parents=True, exist_ok=True)
    (corpus / "knowledge" / "broken.md").write_text(
        "---\napproved: true\nsources:\n  - Merkblatt 2.03\n\n"
        "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.\n",
        encoding="utf-8")
    assert grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen").results == ()


def test_a_frontmatter_line_the_parser_cannot_read_is_not_approved(corpus, no_embedding):
    """A stray line means the parser did not understand the file, and a gate must not act on a file it
    did not understand — the alternative is that the line it skipped was the one that mattered."""
    plant_entry(corpus / "knowledge", "odd.md",
                "approved: true\n{ this is not a key }\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    assert grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen").results == ()


@pytest.mark.parametrize("frontmatter, what", [
    ("approved: true\ntitle: Etwas\n  stray: value\nsources:\n  - Merkblatt 2.03",
     "an indented key under a scalar — a real YAML shape this convention does not use"),
    ("  stray: value\napproved: true\nsources:\n  - Merkblatt 2.03",
     "an indented key before any key at all"),
    ("approved: true\nsources:\n  - label: Merkblatt\n    { not a key }",
     "an unreadable line inside a source mapping"),
])
def test_a_shape_the_parser_does_not_understand_is_not_approved(corpus, no_embedding, frontmatter, what):
    """Each of these was found by planting it, not by reading the parser.

    The first one is the case that got through: the top-level branch was tested and the indented one was
    not, so a file could carry a shape the parser silently discarded and still be published. A guard with
    three branches needs three plantings, which is the practice A66 stated and A68 paid for.
    """
    plant_entry(corpus / "knowledge", "odd.md", frontmatter,
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    found = grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen")
    assert found.results == (), f"{what} was read as an approval"


def test_an_approved_entry_without_sources_is_not_retrievable(corpus, no_embedding):
    """R-171 as a gate rather than as a formatting rule. An answer a member cannot check is a claim."""
    plant_entry(corpus / "knowledge", "nosources.md",
                "title: Die Säule 3a\napproved: true",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    found = grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen")
    assert found.results == ()
    entries, skipped = grounding.approved_entries(corpus / "knowledge")
    assert entries == ()
    assert "sources" in skipped["nosources.md"]


def test_an_approved_entry_with_an_empty_body_is_not_retrievable(corpus, no_embedding):
    plant_entry(corpus / "knowledge", "empty.md",
                "title: Die Säule 3a\napproved: true\nsources:\n  - Merkblatt 2.03", "")
    assert grounding.approved_entries(corpus / "knowledge")[0] == ()


def test_the_gate_holds_in_a_nested_directory(corpus, no_embedding):
    """Drafts arrive in folders. A gate that only watches the top level is not watching."""
    plant_entry(corpus / "knowledge" / "vorsorge" / "entwurf", "draft.md",
                "approved: false\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    plant_entry(corpus / "knowledge" / "vorsorge", "live.md",
                "title: AHV\napproved: true\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge und funktioniert über Einzahlungen.")
    found = grounding.search("gebundene Selbstvorsorge Säule 3a Einzahlungen")
    assert [g.source_id for g in found.results] == ["vorsorge/live.md"]


def test_an_unapproved_draft_never_reaches_the_model_or_the_member(corpus, session, member,
                                                                   no_embedding, monkeypatch):
    """The gate, end to end through `ask()` — the path a member's question actually takes.

    Asserted on three surfaces, because the draft only has to escape through one of them: the prompt the
    model is given, the citations the member is shown, and the answer text itself.
    """
    plant_entry(corpus / "knowledge", "draft.md",
                "title: Die Säule 3a\napproved: false\nsources:\n  - Merkblatt 2.03",
                "Die Säule 3a ist die gebundene Selbstvorsorge. UNGEPRUEFTER ENTWURF.")

    seen = {}

    def capture(prompt, **kwargs):
        seen["prompt"] = prompt
        return llm.Reply(text="Eine Erklärung.", model="stub")

    monkeypatch.setattr(llm, "chat", capture)
    answer = ask(session, member_id=member.id,
                 question="Wie funktioniert die gebundene Selbstvorsorge Säule 3a?")

    assert "UNGEPRUEFTER" not in seen.get("prompt", "")
    assert "UNGEPRUEFTER" not in answer.text
    assert not any("draft.md" in str(c) for c in answer.citations)
    assert answer.citations == []


#: The frontmatter the drafting convention actually writes, as of the first entries to land in
#: `content/knowledge/`: a `title_de`, and `sources:` whose items are mappings of `label` and `where`.
_REAL_SHAPE = """
id: saeule-3a-grundlagen
title_de: "Säule 3a — was sie ist und wie sie rechnet"
language: de-CH
topic: vorsorge
approved: {approved}
reviewed_by: null
reviewed_on: null
sources:
  - label: "Verordnung über die steuerliche Abzugsberechtigung (BVV 3), Art. 1, 3 und 7"
    where: "SR 831.461.3, fedlex.admin.ch"
  - label: "Bundesgesetz über die direkte Bundessteuer (DBG)"
    where: "SR 642.11, fedlex.admin.ch"
"""


def test_the_drafting_conventions_own_shape_is_read_correctly(corpus, no_embedding):
    """A gate that refuses everything is a wall, not a gate.

    The first version of this parser read `sources:` items as scalars, so the real drafts — whose items
    are `- label:` mappings with an indented `where:` — came back as *unreadable*, and unreadable is
    unapproved. It would have failed closed, which is safe, and it would have meant that flipping
    `approved: true` on a reviewed entry changed nothing at all, for a reason nobody would have found.
    """
    plant_entry(corpus / "knowledge", "saeule-3a-grundlagen.md", _REAL_SHAPE.format(approved="true"),
                "# Die Säule 3a\n\nDie Säule 3a ist die gebundene private Vorsorge.")
    found = grounding.search("Was ist die gebundene private Vorsorge Säule 3a?")

    assert len(found.results) == 1
    entry = found.results[0]
    assert entry.title == "Säule 3a — was sie ist und wie sie rechnet"
    # R-171: the legal source and where to find it, in one line the member can act on.
    assert entry.sources[0] == (
        "Verordnung über die steuerliche Abzugsberechtigung (BVV 3), Art. 1, 3 und 7 — "
        "SR 831.461.3, fedlex.admin.ch"
    )
    assert len(entry.sources) == 2


def test_the_drafting_conventions_own_shape_is_still_gated(corpus, no_embedding):
    """The same file, one word different. This is the pair that matters."""
    plant_entry(corpus / "knowledge", "saeule-3a-grundlagen.md", _REAL_SHAPE.format(approved="false"),
                "# Die Säule 3a\n\nDie Säule 3a ist die gebundene private Vorsorge.")
    assert grounding.search("Was ist die gebundene private Vorsorge Säule 3a?").results == ()


_DRAFTS = grounding.DEFAULT_KNOWLEDGE_DIR
_have_drafts = _DRAFTS.is_dir() and any(_DRAFTS.glob("*.md"))
@pytest.mark.skipif(not _have_drafts, reason="no authored content in this working copy")
def test_the_real_directory_agrees_with_what_each_entry_declares(monkeypatch):
    """The gate's verdict on the real files matches what each file says about itself.

    **This test used to assert that every entry was a draft**, which was true on the day it was written
    and stopped being true the moment a human approved the corpus — so it failed for the one reason a test
    must never fail: the thing it was guarding worked. An approval is the expected event here, not a
    regression.

    The durable invariant is agreement: an entry declaring `approved: false` is not retrievable, one
    declaring `approved: true` is, and no file is silently ignored. That holds before any approval, after
    all of them, and half way through.

    **How much this test is doing depends on the corpus, and it is worth being honest about that.** With
    every entry approved, a gate that ignored the field entirely and approved everything would agree with
    the files and pass here — verified by planting exactly that. It is
    `test_flipping_a_real_entry_changes_whether_it_is_retrievable` that catches that case, because it
    forces both values regardless of what the files say. This test earns its keep when the corpus is mixed,
    which is the normal state once a figure goes out of date and one entry is withdrawn.
    """
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(_DRAFTS))
    grounding.reset_caches()
    entries, skipped = grounding.approved_entries()

    declared_true: set[str] = set()
    declared_false: set[str] = set()
    for path in sorted(_DRAFTS.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            continue  # the README documents the convention; it is not an entry
        state = re.search(r"(?m)^approved:\s*(\S+)\s*$", raw)
        if not state:
            continue
        # Keyed on the FILE NAME, because that is what `KnowledgeEntry.entry_id` is. The frontmatter `id`
        # is the author's slug and happens to match today; comparing against it made this test fail on a
        # difference of `.md` while every entry was in fact correct.
        (declared_true if state.group(1).strip().lower() == "true" else declared_false).add(path.name)

    assert declared_true or declared_false, "no entry declared an approval state; the convention moved"

    retrievable = {entry.entry_id for entry in entries}
    assert retrievable == declared_true, (
        f"the gate disagrees with the files. retrievable={sorted(retrievable)}, "
        f"declared approved={sorted(declared_true)}"
    )
    for identifier in declared_false:
        assert identifier not in retrievable, f"{identifier} says approved: false and is being served"


@pytest.mark.skipif(not _have_drafts, reason="no authored content in this working copy")
def test_flipping_a_real_entry_changes_whether_it_is_retrievable(tmp_path, monkeypatch):
    """**The wall check, in both directions, on the real files.**

    If the drafting convention moves and this parser does not, the symptom is that approval stops doing
    anything — silently, and looking exactly like "nothing was relevant". The old version of this test
    detected that by copying every draft and flipping `approved: false` to `true`; once the corpus was
    approved there were no `false` values left to flip and it asserted its way into failing.

    Forcing the value in **both** directions is independent of what the files happen to say today: forced
    to `false` nothing is retrievable, forced to `true` everything is. A parser that ignored the field
    would fail the first half; a gate that had become a wall would fail the second.
    """
    def _rendered(value: str) -> tuple[int, int]:
        target = tmp_path / f"knowledge-{value}"
        target.mkdir()
        written = 0
        for path in sorted(_DRAFTS.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            if not raw.startswith("---") or not re.search(r"(?m)^approved:", raw):
                continue
            forced = re.sub(r"(?m)^approved:.*$", f"approved: {value}", raw, count=1)
            (target / path.name).write_text(forced, encoding="utf-8")
            written += 1
        monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(target))
        grounding.reset_caches()
        entries, _ = grounding.approved_entries()
        return written, len(entries)

    written_false, served_false = _rendered("false")
    assert written_false, "no entry carried an `approved:` line; the convention has changed"
    assert served_false == 0, "an entry forced to `approved: false` was served"

    written_true, served_true = _rendered("true")
    assert served_true == written_true, (
        f"approval did not take effect: {served_true} of {written_true} became retrievable"
    )

    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(tmp_path / "knowledge-true"))
    grounding.reset_caches()
    entries, _ = grounding.approved_entries()
    assert all(e.sources for e in entries), "R-171: every approved entry must cite something"
    assert all(e.title != e.entry_id for e in entries), "every entry carries a title the parser found"


def test_approved_content_is_found_even_with_no_embedding_model(corpus, no_embedding):
    """Reviewed content is the highest-quality ground there is, and the moment the daemon is down is the
    wrong moment for it to disappear. Word overlap is the channel that always works."""
    plant_entry(corpus / "knowledge", "ahv.md",
                "title: AHV-Beiträge\napproved: true\nsources:\n  - Merkblatt 2.03",
                "Die AHV-Beiträge werden vom Lohn abgezogen.")
    found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert found.mode == "lexical"
    assert any(g.kind == "knowledge_entry" for g in found.results)


def test_an_absent_knowledge_directory_is_no_approved_content_and_not_an_error(corpus, no_embedding):
    """A34's deferral and a friend's distribution ZIP land in the same place, and neither is a fault."""
    assert not (corpus / "knowledge").exists()
    assert grounding.approved_entries(corpus / "knowledge") == ((), {})
    assert grounding.search("Wie werden die AHV-Beiträge berechnet?").mode == "lexical"


# ==================================================================== the relevance floor


def test_both_channels_must_clear_their_floor(corpus, embedding):
    """The conjunction, in one test. A passage the embedding loves and the corpus has no word of is
    refused, and so is a passage full of the right words that the embedding puts elsewhere."""
    embedding(_NEAR_FIRST)                     # cosine 0.75 with the AHV passage, 0.50 with the book

    # Right words, and the embedding agrees: through.
    through = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert [g.kind for g in through.results] == ["book_passage"]
    assert through.results[0].semantic >= grounding.SEMANTIC_FLOOR
    assert through.results[0].lexical >= grounding.LEXICAL_FLOOR

    # The embedding still puts the AHV passage at 0.75, but the question shares no word with the corpus.
    # This is the failure the lexical requirement exists for: a German question landing on the only
    # German-looking passage because it is German, not because it is about the same thing.
    refused = grounding.search("Wie repariere ich eine tropfende Mischbatterie?")
    assert refused.results == ()
    assert "relevance floor" in refused.reason


def test_a_passage_below_the_semantic_floor_is_refused_however_many_words_it_shares(corpus, embedding):
    embedding(_NEAR_SECOND)                    # 0.50 with the AHV passage — below the floor
    found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert not any(g.source_id.startswith("ahv") for g in found.results)


def test_the_floor_is_the_number_the_docstring_says_it_is():
    """Pinned, so moving a floor is a deliberate act with the calibration in front of you.

    0.540 is the midpoint between the highest score the corpus cannot answer (0.537) and the lowest it
    can and still keeps (0.542). Both bounds came from the held-out round.
    """
    assert grounding.SEMANTIC_FLOOR == 540
    assert grounding.LEXICAL_FLOOR == 100
    assert grounding.LEXICAL_ONLY_FLOOR == 700


def _share(question: str, text: str) -> int:
    """The lexical channel on its own, at the level it is computed, so the arithmetic is visible."""
    postings = _postings([_AHV, _BOOK])
    terms = grounding._terms(question)
    weights = grounding._term_weights(terms, postings, 2)
    return grounding._lexical_over_text(terms, weights, text)[0]


def test_a_term_the_corpus_has_never_seen_costs_the_question():
    """The correction that turned the lexical channel from noise into a discriminator.

    Normalising over only the terms the index happens to know gave a perfect 1.000 to any passage carrying
    the single in-vocabulary word of a question — "Welche Impfungen brauche ich für eine Reise nach
    Brasilien?" scored 1.000 on a passage that shared the word *Reise*. Every term counts toward the
    denominator now, so a question that is four-fifths unknown vocabulary cannot score as if it had been
    understood in full.
    """
    # 999 and not 1000: every score is truncated rather than rounded, which is the conservative direction
    # for a number a floor is applied to — it can only ever understate how relevant something is.
    assert _share("AHV-Beiträge Lohn abgezogen", _AHV) >= 999
    diluted = _share("AHV Impfungen Sauerteigbrot Mischbatterie Sprachschule", _AHV)
    assert 0 < diluted < 200, "one matching word out of five must not score as a full match"


def test_a_question_of_mostly_unknown_words_is_refused_outright(corpus, embedding):
    """And the consequence at the surface: the dilution drops it below the lexical floor."""
    embedding(_NEAR_FIRST)
    found = grounding.search("AHV Impfungen Sauerteigbrot Mischbatterie Sprachschule")
    assert found.results == ()


def test_a_question_with_no_searchable_term_says_so(corpus, embedding):
    embedding(_NEAR_FIRST)
    found = grounding.search("wie und was?")
    assert found.results == ()
    assert "no term" in found.reason


def test_every_result_carries_the_numbers_that_chose_it(corpus, embedding):
    """An inspectable score beats a black box — `know.py`'s own instinct, and the estate's before it."""
    embedding(_NEAR_FIRST)
    found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    explained = found.results[0].explain()
    assert explained["semantic"] > 0 and explained["lexical"] > 0
    assert "ahv" in explained["matched_terms"]
    assert found.floors == {"semantic": grounding.SEMANTIC_FLOOR, "lexical": grounding.LEXICAL_FLOOR}


# ==================================================================== degradation


def test_an_absent_index_degrades_to_todays_behaviour_with_a_reason(tmp_path, monkeypatch):
    """A friend installing the distribution ZIP may not have the corpus. That is not a crash."""
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(tmp_path / "nothing-here"))
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(tmp_path / "nothing-here-either"))
    grounding.reset_caches()
    found = grounding.search("Wie werden die AHV-Beiträge berechnet?")
    assert found.results == ()
    assert "no book index" in found.reason


def test_an_unreadable_index_degrades_with_a_reason(tmp_path, monkeypatch):
    directory = tmp_path / "bookindex"
    directory.mkdir()
    (directory / "meta.json").write_text("{not json at all", encoding="utf-8")
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(directory))
    grounding.reset_caches()
    found = grounding.search("Wie werden die AHV-Beiträge berechnet?")
    assert found.results == ()
    assert "unreadable" in found.reason


def test_vectors_that_do_not_line_up_with_the_passages_refuse_rather_than_fall_back(tmp_path, monkeypatch):
    """**The one malformation that must not degrade quietly.**

    A truncated `vecs.bin` still parses. If it were allowed to fall through to the lexical channel the
    index would keep answering, and every similarity would have been computed against the wrong text — a
    number that looks exactly like a similarity and means nothing. It refuses instead, and names the fix.
    """
    directory = plant_index(tmp_path / "bookindex")
    (directory / "vecs.bin").write_bytes(array.array("f", [1, 0, 0]).tobytes())   # one row short
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(directory))
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    grounding.reset_caches()

    found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert found.results == ()
    assert "inconsistent" in found.reason and "rebuilt" in found.reason


def test_an_index_with_no_vectors_searches_by_word_overlap_alone(tmp_path, monkeypatch):
    directory = plant_index(tmp_path / "bookindex", vectors=False)
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(directory))
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    grounding.reset_caches()

    found = grounding.search("AHV-Beiträge Lohn abgezogen Arbeitgeber Nichterwerbstätige Mindestbeitrag")
    assert found.mode == "lexical"
    assert found.floors == {"lexical_only": grounding.LEXICAL_ONLY_FLOOR}
    assert found.results and found.results[0].semantic == -1, (
        "-1 is 'nobody looked'; 0 would say the embedding looked and found nothing alike"
    )


def test_no_embedding_model_degrades_to_word_overlap_and_says_so(corpus, no_embedding):
    found = grounding.search("AHV-Beiträge Lohn abgezogen Arbeitgeber Nichterwerbstätige Mindestbeitrag")
    assert found.mode == "lexical"
    assert "no embedding model" in found.reason


def test_an_embedding_of_the_wrong_width_is_refused_rather_than_compared(corpus, monkeypatch):
    """Two models are two coordinate systems. A dot product across them returns a number and means
    nothing, which is the worst of the available outcomes."""
    monkeypatch.setattr(llm, "embed", lambda text, **kw: [0.6, 0.8])      # the index has three
    found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert found.mode == "lexical"
    assert "not the model this index was built with" in found.reason


def test_the_query_is_embedded_with_the_model_the_index_was_built_with(corpus, monkeypatch):
    asked = {}

    def capture(text, **kwargs):
        asked.update(kwargs)
        return list(_NEAR_FIRST)

    monkeypatch.setattr(llm, "embed", capture)
    grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert asked["model"] == "stub-embed", "the index's own model, not a configured default"


# ==================================================================== C-05, and C-04


@pytest.mark.parametrize("elsewhere", [
    "http://books.example.com/index",
    "https://books.example.com/index",
    "ftp://files.example.com/bookindex",
    "smb://fileserver/bookindex",
    "\\\\fileserver\\share\\bookindex",
    "//fileserver/share/bookindex",
])
def test_a_corpus_that_is_not_on_this_machine_raises(monkeypatch, elsewhere):
    """C-05 for the index. Not configurable, not warned about — raised.

    Whoever serves the corpus decides what a member is told, and there is no deployment in which that is
    somebody else. The exception is an `llm.NotLocal` so the model host and the corpus refuse as one kind.
    """
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", elsewhere)
    grounding.reset_caches()
    with pytest.raises(grounding.CorpusNotLocal):
        grounding.index_dir()
    assert issubclass(grounding.CorpusNotLocal, llm.NotLocal)


def test_a_local_path_is_accepted_in_the_shapes_this_machine_writes(monkeypatch, tmp_path):
    for ok in (str(tmp_path), str(tmp_path).replace("\\", "/"), "relative/bookindex"):
        monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", ok)
        assert grounding.index_dir() is not None


def test_the_grounding_service_contains_no_logging_of_text():
    """C-04 and A36's obligation, extended to the module that now reads a member's question.

    `know.py` has carried this since phase 4 and the same rule has to hold one file over, or the question
    simply gets logged from the other side of the call.
    """
    source = (pathlib.Path(__file__).parent.parent / "eigentlich" / "services" / "grounding.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("logger.", "logging.getLogger", "print("):
        assert forbidden not in source, f"grounding.py contains {forbidden!r}"


def test_nothing_logs_the_question_or_a_retrieved_passage(corpus, embedding, caplog):
    embedding(_NEAR_FIRST)
    with caplog.at_level(logging.DEBUG):
        found = grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert found.results
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "AHV-Beiträge vom Lohn" not in logged
    assert "Arbeitnehmerin" not in logged


def test_the_search_is_given_no_member_and_has_no_parameter_for_one():
    """`desktop/coach.py`'s guarantee, in this module: a function cannot disclose what it cannot be told.

    Checked on the signature rather than asserted in prose, because a keyword argument added later is
    exactly how the guarantee would stop holding.
    """
    import inspect

    names = set(inspect.signature(grounding.search).parameters)
    assert names == {"question", "limit", "index_path", "relief"}, (
        "a parameter was added to or removed from `search`. Adding one is allowed and `relief` is one "
        "that was added, on 21 September 2026, to lower the floors for a composed answer — it is an "
        "integer of per mille and carries nothing about anybody. What this test exists to stop is a "
        "parameter through which a MEMBER could be passed, so read the new one and decide, rather than "
        "updating the set to make the suite green."
    )


def test_nothing_here_writes_to_the_estate(corpus, embedding, tmp_path):
    """§9. The index is read; the directory holding it is not touched."""
    directory = corpus / "bookindex"
    before = {p.name: p.stat().st_mtime_ns for p in directory.iterdir()}
    embedding(_NEAR_FIRST)
    grounding.search("Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    after = {p.name: p.stat().st_mtime_ns for p in directory.iterdir()}
    assert before == after


# ==================================================================== the wire into The Know


def test_a_corpus_passage_reaches_retrieval_and_is_cited_with_its_place(corpus, session, member,
                                                                       embedding):
    """R-171 for the corpus. The member sees the document, not just a title."""
    embedding(_NEAR_FIRST)
    passages = retrieve(session, member_id=member.id,
                        question="Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    assert [p.kind for p in passages] == ["book_passage"]
    cite = passages[0].citation()
    assert cite["where"].startswith("AHV: Beiträge und flexibler Rentenbezug · 2 Die Beiträge")


def test_a_full_vault_cannot_silently_remove_the_corpus(corpus, session, store, member, embedding):
    """`CORPUS_SLOTS`. Six vault items matching one word each would otherwise fill every slot."""
    from eigentlich.services import store_item

    for i in range(8):
        store_item(session, store, member_id=member.id, kind="note", title=f"AHV Notiz {i}",
                   source="manual", notes="AHV AHV")
    session.commit()
    embedding(_NEAR_FIRST)

    passages = retrieve(session, member_id=member.id,
                        question="Wie werden die AHV-Beiträge vom Lohn abgezogen?")
    kinds = [p.kind for p in passages]
    assert len(passages) == 6
    assert kinds.count("book_passage") >= 1, "the corpus was crowded out by the member's own paperwork"
    assert kinds[0] == "vault_item", "the member's own material still leads"


def test_the_member_never_reaches_the_corpus_search(corpus, session, member, embedding, monkeypatch):
    """A34's shape: the corpus is impersonal, and it stays impersonal by not being given anybody."""
    seen = []
    real = grounding.search
    monkeypatch.setattr(grounding, "search", lambda q, **kw: seen.append((q, kw)) or real(q, **kw))
    embedding(_NEAR_FIRST)
    retrieve(session, member_id=member.id, question="Wie werden die AHV-Beiträge abgezogen?")
    assert seen and all(member.id not in str(call) for call in seen)


def test_the_answer_reports_how_the_corpus_behaved(corpus, session, member, no_embedding, monkeypatch):
    """An index that says nothing about everything has to be legible to whoever installed it."""
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("nothing was retrieved"))
    answer = ask(session, member_id=member.id, question="Wie hoch ist der Goldpreis in Singapur?")
    assert answer.as_dict()["grounding"]["mode"] == "lexical"
    assert "no embedding model" in answer.as_dict()["grounding"]["reason"]
    # C-04: a mode and a floor, never the question and never a passage.
    assert "Goldpreis" not in json.dumps(answer.as_dict()["grounding"])


def test_the_honest_refusal_is_unchanged_when_nothing_clears_the_floor(corpus, session, member,
                                                                      embedding, monkeypatch):
    """In the quoting mode, where the floor decides whether there is an answer at all.

    Composing lowers the floor by `know.COMPOSE_FLOOR_RELIEF` and is able to say "dazu ist wenig
    erfasst, aber —" over a weak passage, which is the whole point of the relief and is tested in
    `test_compose.py`. Here the floor is the gate, and a question the corpus cannot touch must not
    reach a model at all.
    """
    from eigentlich.services import know

    monkeypatch.setattr(know, "ANSWER_MODE", "quote")
    embedding(_NEAR_SECOND)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("must not ask a model with no grounding"))
    answer = ask(session, member_id=member.id, question="Wie repariere ich eine tropfende Mischbatterie?")
    assert answer.citations == []
    assert answer.text.startswith("Dazu finde ich in Ihren Unterlagen")
    assert answer.requires_curator is False
# ==================================================================== against the real corpus
#
# Two tests, and they skip rather than fail where the estate's index or the daemon is absent. They exist
# because everything above this line proves the code is right about a planted index, and nothing above
# this line would notice if the real one had been rebuilt with a different model.

_REAL = grounding.DEFAULT_INDEX_DIR
_have_corpus = (_REAL / "meta.json").exists() and (_REAL / "vecs.bin").exists()
real_corpus = pytest.mark.skipif(not _have_corpus, reason="the estate's book index is not on this machine")


@pytest.fixture()
def estate(monkeypatch):
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(_REAL))
    grounding.reset_caches()
    if not llm.available():
        pytest.skip("the local daemon is not running")
    yield
    grounding.reset_caches()


@real_corpus
def test_the_real_corpus_answers_an_ahv_question_and_cites_the_ahv_document(estate):
    """What the wiring bought, stated as a fact about the corpus rather than about the code.

    AHV is the only Swiss regulatory ground in 1 280 passages, and it is the one thing a German-speaking
    member can currently be answered about.
    """
    found = grounding.search("Wie hoch ist der Mindestbeitrag an die AHV für Nichterwerbstätige?")
    assert found.mode == "vector"
    assert found.results, "the corpus stopped answering the question it exists to answer"
    assert found.results[0].where.startswith("AHV")
    assert found.results[0].semantic >= grounding.SEMANTIC_FLOOR


@real_corpus
@pytest.mark.parametrize("question, answerable", [
    # The two boundary probes the floor was set between. Both from the held-out round; see the module
    # docstring. If either moves, the floor was calibrated against something that has changed.
    ("Was ist entnehmbares Vermögen?", True),
    ("Was ist die Amortisation einer Hypothek?", False),
    # What the corpus cannot answer, and must not pretend to.
    #
    # **The 3a line flipped to True on 5 September 2026** and that is the test doing its job in the
    # pleasant direction: four rule sources went into the index (BVG, the AHV Altersrente leaflet, the
    # WEFV and the BSV amounts sheet), and the 3a maxima are now in it at semantic 566, above the 540
    # floor. The entry stays here rather than moving to the answerable block so the reason is visible.
    ("Wie funktioniert die Säule 3a?", True),
    ("Was ist ein ETF?", False),
    # Still empty, and now for a more interesting reason than absence: since 5 September the corpus
    # holds a whole BVG document that answers this. The question does not reach it. The document says
    # "berufliche Vorsorge" and "Vorsorgeeinrichtung" where the member says "Pensionskasse", the lexical
    # channel shares no token, and the similarity alone stays under the floor. A139's compound problem,
    # in German-to-German rather than English-to-German. Recorded here rather than fixed by sprinkling
    # the synonym into the source text, which would be tuning the corpus to the test.
    ("Wie funktioniert die Pensionskasse?", False),
    ("Wie wird der Eigenmietwert besteuert?", False),
    ("Was kostet eine Kinderkrippe in Zürich?", False),
    ("Wie hoch ist der Goldpreis in Singapur?", False),
    # And what it can.
    ("Wie werden die AHV-Beiträge berechnet?", True),
    ("Kann ich den Bezug der AHV-Rente aufschieben?", True),
    ("What is capital saturation?", True),
])
def test_the_real_corpus_refuses_what_it_does_not_hold(estate, question, answerable):
    found = grounding.search(question)
    assert bool(found.results) is answerable, (
        f"{question!r} -> {[(g.semantic, g.lexical, g.where) for g in found.results]}"
    )


@real_corpus
def test_the_german_compounds_the_corpus_cannot_reach_are_recorded_as_open(estate):
    """**A hole, asserted open rather than papered over.** This test instructs its own deletion.

    The book defines capital saturation, human capital and the life balance sheet, in English. A German
    member asking for any of them by its German compound gets nothing: the compound shares no token with
    the English text, so the lexical requirement is never met, and the similarity alone is not allowed to
    carry a passage. The fix is a second query — the estate's `bookindex.search_multi` translates the
    question and keeps each passage's best score, which lifts "Was bedeutet Kapitalsättigung?" from 0.536
    to 0.648 — and it costs a model call inside retrieval, which was not taken here.

    When that lands, this test starts failing and should be deleted rather than adjusted.
    """
    for question in ("Was bedeutet Kapitalsättigung?", "Was ist Humankapital?", "Was ist die Lebensbilanz?"):
        found = grounding.search(question)
        assert found.results == (), (
            f"{question!r} is answerable now — the cross-lingual hole is closed and this test should go"
        )


@real_corpus
def test_the_real_index_is_the_shape_this_module_expects(estate):
    """A34's index, checked rather than assumed: 1 024 dimensions, built with bge-m3.

    The passage count was 1 280 when this was written and is 1 325 since the four rule sources landed on
    5 September 2026. It is deliberately not asserted: the count is expected to grow, and a test that
    pinned it would fail every time the corpus was improved.
    """
    loaded = grounding._load_index(str(_REAL))
    assert loaded.index is not None and loaded.reason is None
    assert loaded.index.dim == 1024
    assert loaded.index.model.startswith("bge-m3")
    assert len(loaded.index.vectors) == len(loaded.index.passages) * loaded.index.dim
    # Passage vectors are unit vectors, which is what makes a dot product a cosine.
    first = loaded.index.vector(0)
    assert math.isclose(math.sqrt(sum(x * x for x in first)), 1, rel_tol=1e-3)


# ============================================================ alias groups (query-side only)


def test_a_group_is_one_term_slot_and_does_not_dilute_the_denominator():
    """**The whole safety argument for aliases, asserted rather than described.**

    The obvious implementation -- append synonyms to the question's term list -- is wrong here and
    measurably so. `_term_weights` normalises over every term including ones the corpus has never seen,
    which is the correction that made the lexical channel a discriminator rather than noise. Appending
    seven forms of "Pensionskasse" would multiply the denominator by seven and shrink every real match.

    So the weights a question produces must be identical whether or not aliases exist.
    """
    postings = {"vorsorgeeinrichtung": [1], "berufliche": [1], "vorsorge": [1]}
    terms = grounding._terms("Wie funktioniert die Pensionskasse?")
    weights = grounding._term_weights(terms, postings, 100)
    assert set(weights) == set(terms), "an alias must never become a term in its own right"


def test_an_alias_lets_a_passage_earn_the_terms_weight_without_carrying_the_word(monkeypatch):
    monkeypatch.setattr(grounding, "_alias_groups",
                        lambda: {"pensionskasse": (("vorsorgeeinrichtung",),)})
    postings = {"vorsorgeeinrichtung": [7]}
    assert grounding._passages_for("pensionskasse", postings, grounding._alias_groups()) == {7}


def test_a_term_earns_its_weight_once_however_many_forms_a_passage_carries(monkeypatch):
    """A group is a slot, not a bonus. A passage naming three forms of one thing is not three matches."""
    monkeypatch.setattr(grounding, "_alias_groups",
                        lambda: {"pensionskasse": (("vorsorgeeinrichtung",), ("bvg",))})
    postings = {"pensionskasse": [3], "vorsorgeeinrichtung": [3], "bvg": [3]}
    terms = ["pensionskasse"]
    weights = grounding._term_weights(terms, postings, 100)
    scored = grounding._lexical(terms, weights, postings)
    # the single term is the whole question, so its share is the whole of it -- never more
    assert scored[3][0] == 1000
    assert scored[3][1] == ("pensionskasse",)


def test_a_multi_word_form_matches_only_when_every_token_does(monkeypatch):
    """Conservative on purpose: «berufliche Vorsorge» is a phrase, and either word alone is not it."""
    monkeypatch.setattr(grounding, "_alias_groups",
                        lambda: {"pensionskasse": (("berufliche", "vorsorge"),)})
    aliases = grounding._alias_groups()
    both = {"berufliche": [1, 2], "vorsorge": [2, 3]}
    assert grounding._passages_for("pensionskasse", both, aliases) == {2}
    only_one = {"berufliche": [1, 2]}
    assert grounding._passages_for("pensionskasse", only_one, aliases) == set()


def test_a_missing_or_broken_record_reproduces_the_behaviour_without_it(monkeypatch):
    """**Fails open, and the record argues why that is the right direction here.**

    Unlike `property-funding.json` this decides which paragraph is shown beside a citation the member can
    open, not what a lender would say. Failing open fails toward showing a real source; failing closed
    would take the Know back to refusing questions it can answer.
    """
    def boom(_name):
        raise RuntimeError("no such record")

    monkeypatch.setattr("eigentlich.content._load", boom)
    assert grounding._alias_groups() == {}


@real_corpus
def test_an_alias_reaches_a_document_the_bare_word_could_not(estate):
    """«Rentenalter» is in no passage; «Referenzalter» is in twelve. AHV 21 renamed it and both are used."""
    loaded = grounding._load_index(str(_REAL))
    assert loaded.index is not None
    assert not loaded.index.postings.get("rentenalter"), "the corpus does not use this word"
    assert loaded.index.postings.get("referenzalter"), "and this is the word it does use"
    found = grounding.search("Was ist das Rentenalter?")
    assert found.results, "the alias record should reach the passage the bare word cannot"
    # `rentenalter` among the matched terms is the assertion that matters: the word the member typed
    # earned its weight, from a passage that does not contain it. Which of the several Referenzalter
    # passages ranks first is a scoring question and deliberately not pinned here -- BVG Art. 13 and the
    # AHV leaflet are both right answers.
    assert "rentenalter" in found.results[0].matched
    assert any("Referenzalter" in g.where or "Referenzalter" in g.text or "BVG" in g.where
               for g in found.results)


@real_corpus
@pytest.mark.parametrize("question", [
    "Wie hoch ist der Goldpreis in Singapur?",
    "Was kostet eine Kinderkrippe in Zürich?",
])
def test_aliases_do_not_make_the_corpus_answer_what_it_does_not_hold(estate, question):
    """The floor that matters. Widening reach must not widen it to noise."""
    assert grounding.search(question).results == ()
