"""S-08, The Know. Answers quoted from grounding, and a boundary that code enforces.

**The order of operations is the design.**

    1. classify the question           — if it asks what to do, the model is never called
    2. retrieve grounding              — the member's own material, then the impersonal corpus
    3. ask the local model             — apertus:8b on loopback, and it answers with sentence NUMBERS
    4. check what will be emitted      — before serialisation: it advises, it is not quoted, it invents
    5. cite what was quoted            — R-171, one citation per quote

Steps 1 and 4 are `boundary.py`, which imports no model and is tested with nothing running. A model
cannot be its own gate, so the gate is not made of model.

**The answer is quoted, never composed. This is the owner's decision of 1 September 2026 and it is what
step 3 above changed.** The Know could state Swiss pension law wrongly while citing the correct passages:
asked whether an AHV pension may be *deferred*, apertus:8b answered about the *reduction* for drawing one
*early* and presented the 20–80 % Teilbezug band as a range of reductions — in 3 of 3 runs, with correct
citations attached, and no run stated the correct fact (A103). C-01 passed it, rightly: the boundary asks
whether an answer **advises**, not whether it is **true**. `unverifiable_figures` passed it too, because 20
and 80 are genuinely in the corpus and merely applied to the wrong quantity.

So the model no longer writes the answer. It is shown the retrieved passages split into numbered sentences
and it returns **numbers**. The sentences those numbers name are what the member reads, verbatim. There is
no field in its reply through which a sentence of its own could arrive — the same shape `interpret.py` uses
one layer over, where the model proposes a reading and every value is verified to occur in the member's own
text before it is offered. A model that can only point cannot invert a sign.

**Selecting is a real job and it is not paraphrase.** It is also the job that was measured, because the
alternative had to be ruled out rather than assumed: if the existing lexical scoring could pick the right
sentences, the model could leave the member's answer path altogether, which is a stronger form of the same
guarantee. It cannot. Over six AHV questions against the real index, `grounding`'s own weighted term
overlap put the sentence that answers "wie hoch ist der Mindestbeitrag" **outside its top eight of 142**,
while the sentence it ranked first was a true sentence about the comparison calculation. Scoring finds the
passage; it does not find the sentence. The model is still in the path, and it is in it for one job.

**Choosing nothing is a right answer.** `NOTICE["nothing_answers"]` says the corpus was searched and none
of what came back answers the question. Quoting badly is worse than refusing, and the refusal already
existed.

**Four things run on what will be emitted, and each of them can refuse the whole answer.**

    · `check_answer` on every raw model reply — a reply that argues instead of listing numbers has
      ignored its instructions, and the member sees the boundary rather than the reply
    · `check_answer` on the assembled quotation — the corpus is impersonal so this should be rare, but
      the gate does not get to be skipped because the text came from a book
    · `unquoted_sentences` — every quoted span must occur in a retrieved passage, and nothing carrying a
      word may stand outside the quotation marks. This is the verified property, not an instruction
    · `unverifiable_figures` — kept, and now nearly redundant, since a figure inside a quoted span is by
      construction a figure in a passage

**R-171 is stronger under quoting, not weaker.** `citations[i - 1]` is the source of the span marked
`[i]`: the list is built from the quotes themselves, in their order, so the citation and the quoted text
cannot disagree about where the words came from. A passage quoted twice is cited twice.

**Why the model is called with passages rather than with the vault.** It is given the text of the items
retrieval already selected, and nothing else. There is no parameter through which the whole vault could
be passed, which is the same guarantee `desktop/coach.py` gets from having no household parameter — a
model cannot disclose what it was never given.

**A36 permits K3 here, and that creates an obligation.** The model may read vault contents because it runs
on loopback. So nothing in this module logs a prompt, a completion, or a retrieved passage: the C-04
filter drops K3 by field name, and a prompt is not a field — it is a paragraph containing several. Two
tests hold it: `test_nothing_in_the_know_logs_a_prompt_or_a_completion` runs a real question and asserts
the vault text does not appear in any log record, and `test_the_know_service_contains_no_logging_of_text`
greps this file, so a logger added later has to justify itself.

**R-175: nothing here is proactive.** Every function in this module answers a question that was asked.
Action items are listed when the panel is opened; they do not interrupt.

**Step 2 has two halves and only one of them is the member's.** `own_material` searches their vault and
the learning units; `corpus_material` searches the impersonal ground in `grounding.py` — the estate's
`bge-m3` book index and the German explainers a human has marked approved. A34 deferred the second half
and the consequence was that The Know could answer nothing at all: there are no learning units in the
database and typically no vault items, so retrieval was empty for every member, always, and every
educational question returned an honest refusal in four milliseconds.

The corpus half is gated by a floor measured on 56 probes rather than chosen, and it still refuses most
German questions, because 1 160 of the 1 280 passages are an English manuscript and the only Swiss
regulatory ground in it is eleven AHV passages. That refusal is the corpus telling the truth about itself.
`grounding.py`'s docstring carries the numbers.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..boundary import normalise_language
from ..models import (
    ActionItem,
    CuratorSession,
    CuratorSessionEvent,
    Goal,
    LearningUnit,
    Position,
    VaultItem,
)
from . import computations
from . import compose, grounding, member_ground
from .router import Branch, route as route_question
from .vault import current_items

#: Retrieved passages are capped. A prompt that grows with a member's vault is a prompt that eventually
#: exceeds the context window and silently drops its oldest — and which passage got dropped would be
#: invisible. A cap that is visible is better than a truncation that is not.
MAX_PASSAGES = 6

#: How an answer is produced. `compose` is the owner's ruling of 21 September 2026 and the default;
#: `quote` is C-11 as it stood and restores it exactly.
#:
#: **Both paths are live and both are tested.** The quoting path below is not dead code kept for
#: sentiment: it is one environment variable away, every check it ran as a gate still runs as a gate on
#: it, and the tests that pinned C-11 now pin it here. What changed is which one a member gets.
#:
#: The reasoning for the change, and what it costs, is in `services/compose.py`. The short version is
#: that on 20 September 2026 forty-two of fifty members were told the product did not know, thirty-six of
#: them had asked something a corpus cannot answer in principle, and the arithmetic that would have
#: answered them was already in the same process.
ANSWER_MODE = os.environ.get("ANDERSCH_ANSWER_MODE", "compose")

#: The floor `grounding` applies when the answer will be composed rather than quoted.
#:
#: A quoted answer puts a passage in front of the member as the answer, so a weak passage is a wrong
#: answer and the floor is a correctness gate. A composed answer reads its passages as context and says
#: what they do not cover, so a weak passage is weak context — and refusing it is how thirty-six
#: questions came back with nothing at all rather than with "dazu ist hier wenig erfasst, aber ...".
#: Retrieval still ranks; what moves is only what is thrown away before ranking.
COMPOSE_FLOOR_RELIEF = int(os.environ.get("ANDERSCH_COMPOSE_FLOOR_RELIEF", "120"))

#: Slots kept for impersonal ground when any of it cleared `grounding`'s measured floor.
#:
#: **Without this a full vault silently removes the corpus.** The member's own material is listed first —
#: it is the material S-08 names first, and a document they uploaded is grounding nothing else can provide
#: — but a member with six vault items matching one word each would fill every slot with their own
#: paperwork and lose the AHV passage that actually answers the question. Two slots are held back for a
#: passage that had to clear a floor to get here.
CORPUS_SLOTS = 2

#: How many quoted sentences a member is shown.
#:
#: Three, because that is what the corpus supports. The AHV passages that answer a pension question state
#: the rule in one or two sentences — "Im Rahmen des flexiblen Rentenalters kann der Bezug … um ein bis
#: höchstens fünf Jahre aufgeschoben werden" is the whole answer to the question that used to fail — and
#: the sentences after the second were, in every measured run, about the neighbourhood of the question
#: rather than about it. A quotation is read; a wall of quotation is skipped, and a member who skips it
#: has been given nothing.
MAX_QUOTES = 3

#: How many one source may contribute.
#:
#: Without it a single authored entry answers out of its own voice and the second source that would have
#: qualified it never gets a slot. Two rather than one because a rule and its bound are often two adjacent
#: sentences, and splitting them across sources would be worse than quoting both.
MAX_QUOTES_PER_SOURCE = 2

#: Shorter than this is a heading, a table label or a fragment of markup rather than a statement a member
#: can read on its own. Not measured against anything: read off what falls out of this corpus at that
#: length — the `**Die Kürzung.**` lead-ins, the bare `Nach Merkblatt 2.03, Stand am 1. Januar 2026:` and
#: the one-word list labels go, and every real sentence in the eleven AHV passages stays.
MIN_QUOTABLE_CHARS = 25

#: The quotation marks the answer is built with, and the reason they are these two.
#:
#: Neither occurs anywhere in the 1 280 book passages or in the 15 authored entries — checked, not assumed
#: — so a closing mark in the answer is always one this module wrote. The corpus uses `«…»` for its own
#: quotations, which is why those were not chosen: a passage that quotes a Merkblatt title would have
#: closed a span this module opened, and `unquoted_sentences` would then be reading its own scaffolding as
#: member-facing text. A candidate sentence carrying either mark is dropped rather than quoted, because a
#: member's own note is the one source this argument cannot make a promise about.
OPEN_QUOTE = "„"
CLOSE_QUOTE = "“"

_WORD = re.compile(r"[a-zäöüéèàç0-9]{3,}", re.IGNORECASE)

#: Words too common in German financial questions to discriminate on.
_STOP = frozenset({
    "und", "der", "die", "das", "den", "dem", "ein", "eine", "einen", "einem", "für", "von", "mit",
    "ist", "sind", "war", "wie", "was", "wer", "wo", "wann", "warum", "bei", "aus", "auf", "meine",
    "mein", "meinem", "meiner", "ich", "sie", "the", "and", "for", "with", "what", "how", "why",
    "does", "was", "are", "my", "mine", "this", "that",
})


def _terms(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")} - _STOP


@dataclass
class Passage:
    """One retrieved piece, with what it came from. R-171's citation is built from this.

    **`score` is only comparable within a `kind`, and the sort below never compares across one.** A vault
    item's score counts how many of the question's words its text carries; a book passage's is a per-mille
    blend of a cosine and a weighted term share (`grounding.py`). Ordering the two against each other would
    be arithmetic on two different quantities that happen to both be integers.
    """

    kind: str          # "vault_item" | "learning_unit" | "book_passage" | "knowledge_entry"
    source_id: str
    title: str
    text: str
    score: int
    #: Where a corpus passage sits inside its document — "Work · Chapter · Section". Empty for the
    #: member's own material, which is cited by its title because that is what they named it.
    where: str = ""
    #: An approved authored entry's own `sources:` list. R-171: the member can follow it to the source.
    sources: tuple[str, ...] = ()

    def citation(self) -> dict:
        cite = {"kind": self.kind, "id": self.source_id, "title": self.title}
        if self.where:
            cite["where"] = self.where
        if self.sources:
            cite["sources"] = list(self.sources)
        return cite


@dataclass
class Answer:
    question: str
    text: str
    citations: list[dict] = field(default_factory=list)
    #: The quoted spans as `{"text": ..., "citation": {...}}`, in the order they appear in `text`.
    #:
    #: `text` is one string because that is what `client/surfaces/know.js` renders, and a string cannot
    #: carry the pairing. This can. It is additive — the panel ignores a key it does not read — and it is
    #: what a client that wanted to render each quotation under its own source would use instead of
    #: parsing the `[1]` markers back out of prose.
    quotes: list[dict] = field(default_factory=list)
    requires_curator: bool = False
    reason: str | None = None
    model: str | None = None
    #: True when the local model was unreachable. The panel says so rather than inventing an answer.
    unavailable: bool = False
    #: How the impersonal corpus behaved: `{"mode": ..., "reason": ...}`. **Never the question and never a
    #: passage** — a path, a mode and a floor. An index that is absent or malformed has to be legible to
    #: whoever installed it, and "it says nothing about everything" is not legible.
    grounding: dict | None = None
    #: Which of the three branches this question took, and which regulatory boundary it crossed. Item 1.
    #: On the response so a client renders the source bar and the caveat fold from the answer itself
    #: rather than re-classifying the question it just sent.
    route: dict | None = None
    #: Branch 2 with an empty Vault: the ONE input that would make this answer personal, as
    #: `{"key": ..., "sentence": ...}`. Composed by code from a fixed phrase, never by the model — the
    #: same rule as the refusal, for the same reason.
    personalisation: dict | None = None
    #: Set when the answer was COMPUTED rather than quoted: `{"key": ..., "inputs": ..., "caveats": ...}`.
    #: A member reading a figure about themselves is entitled to know it was worked out and from what,
    #: and `citations` carries the services and records it read instead of pages.
    computation: dict | None = None

    def as_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.text,
            "citations": self.citations,
            "quotes": self.quotes,
            # C-01's marker on the response object itself, as the specification describes.
            "requires_curator": self.requires_curator,
            "reason": self.reason,
            "model": self.model,
            "answered": not self.unavailable,
            "grounding": self.grounding,
            "route": self.route,
            "personalisation": self.personalisation,
            "computation": self.computation,
        }


def learning_material(session: Session, *, question: str) -> list[Passage]:
    """Keyword retrieval over the learning units. **Impersonal, and therefore available on every branch.**

    Split out of `own_material` on 3 September 2026, when item 1's router made "no member data touched" a
    property that had to be true of the code. `own_material` searched two quite different things in one
    pass — the member's vault (K3, theirs) and `LearningUnit` (K0, the curriculum, identical for every
    member) — and calling the pair "own" material was the confusion: withholding it all from a
    population-fact question would have withheld the curriculum from the questions the curriculum exists
    to answer.

    So the split is by data class, which is the line that actually matters, rather than by which function
    happened to fetch it.
    """
    wanted = _terms(question)
    if not wanted:
        return []

    passages: list[Passage] = []
    for unit in session.execute(select(LearningUnit)).scalars():
        haystack = " ".join(str(p) for p in (unit.title, unit.body_ref) if p)
        score = len(wanted & _terms(haystack))
        if score:
            passages.append(Passage("learning_unit", unit.id, unit.title, haystack, score))
    return passages


def member_material(session: Session, *, member_id: str, question: str) -> list[Passage]:
    """Keyword retrieval over the member's own vault. **Only ever called on a branch that permits it.**

    Deliberately simple and inspectable: the score is a term overlap and the caller can see which terms
    matched. A black-box retrieval that grounds an answer in the wrong document is worse than a crude one
    whose reasoning is visible — the estate reached the same conclusion for its branch matcher.

    **No relevance floor here, and that is deliberate.** `grounding.py` gates the impersonal corpus because
    a wrong citation from it asserts something about the world. A member's own document matching their own
    words is not a claim about the world; it is their paperwork, retrieved because they asked about it. The
    floor would refuse "was steht in meiner Police" for a policy the member is holding in their hand — and
    that question is branch 2, so this is the function that answers it.
    """
    wanted = _terms(question)
    if not wanted:
        return []

    passages: list[Passage] = []

    for item in current_items(session, member_id=member_id):
        haystack = " ".join(
            str(part) for part in (item.title, item.notes, item.kind, item.extracted_fields) if part
        )
        score = len(wanted & _terms(haystack))
        if score:
            passages.append(Passage("vault_item", item.id, item.title, haystack, score))

    passages.sort(key=lambda p: (-p.score, p.title))
    return passages[:MAX_PASSAGES]


def corpus_material(question: str, *, relief: int = 0) -> tuple[list[Passage], grounding.Grounding]:
    """The book corpus and the approved authored explainers, through `grounding`'s measured floor.

    A34 recorded the corpus as unwired and the consequence was that The Know could answer nothing: there
    are no learning units in the database and typically no vault items, so retrieval was empty for every
    member, always. It is wired here — and it is wired *behind a floor*, so that "wired" does not quietly
    become "always returns the closest thing it has".

    The `Grounding` is returned alongside so the caller can say why nothing came back. It carries no
    member data of any kind: this function is not given a member and has no parameter through which one
    could be passed, which is the guarantee `desktop/coach.py` gets from having no household parameter.
    """
    found = grounding.search(question, limit=MAX_PASSAGES, relief=relief)
    return [
        Passage(
            kind=g.kind,
            source_id=g.source_id,
            title=g.title,
            text=g.text,
            score=g.score,
            where=g.where,
            sources=g.sources,
        )
        for g in found.results
    ], found


def assemble(own: list[Passage], corpus: list[Passage]) -> list[Passage]:
    """The two retrievals into one capped list, member's material first.

    One function rather than the same three lines in `retrieve` and in `ask`: two copies of a rule about
    which grounding survives is two copies that can disagree, and the one in `ask` is the one a member
    actually sees.
    """
    if corpus:
        own = own[:max(0, MAX_PASSAGES - min(len(corpus), CORPUS_SLOTS))]
    return (own + corpus)[:MAX_PASSAGES]


def retrieve(session: Session, *, member_id: str, question: str) -> list[Passage]:
    """Everything the model is allowed to see: the member's own material first, then impersonal ground.

    Two retrievals rather than one ranking, because their scores are not the same quantity — see
    `Passage`. The member's material leads because S-08 names it first and because they asked about it;
    `CORPUS_SLOTS` keeps a full vault from silently removing a passage that had to clear a floor.
    """
    corpus, _ = corpus_material(question)
    return assemble(own_material(session, member_id=member_id, question=question), corpus)


# ------------------------------------------------------------------------------------------------
# Splitting a passage into the sentences that may be quoted.
#
# Every unit this produces is a contiguous substring of the passage it came from, apart from a leading
# list marker and the markdown emphasis characters, both of which are removed by prefix and by symmetric
# folding. That is what makes `unquoted_sentences` able to check the answer against the passages at all.

#: Tokens that end in a full stop without ending a sentence. Only the ones this corpus actually carries.
#:
#: `AHV`, `BVG` and `IV` are deliberately NOT here even though the corpus is full of them: they are also
#: perfectly ordinary sentence endings ("… bei der AHV.") and listing them would silently weld two
#: statements into one quoted unit. A digit is handled separately and matters far more — "am 1. Januar
#: 2026" and "ab dem 63. Altersjahr" and "die 13. AHV-Rente" all end a token in a digit and a full stop,
#: and splitting there would quote half a date at a member.
_ABBREVIATION = frozenset({
    "abs", "art", "bsp", "bzw", "ca", "chf", "etc", "evtl", "ff", "fr", "ggf", "inkl", "insb", "lit",
    "mio", "mrd", "nr", "resp", "sog", "usw", "vgl", "ziff", "zzgl",
})

_LINE = re.compile(r"[\r\n]+")
#: A leading `- `, `* `, `> ` or `1. ` on a markdown line. Removed from the front of a quotable sentence,
#: which leaves it a substring of the passage; nothing inside a sentence is touched.
_LIST_MARKER = re.compile(r"^(?:[-*+•>]\s+|\d+[.)]\s+)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_TRAILING_TOKEN = re.compile(r"(\w+)\.\s*$")
#: `[3]` as this module writes it. Stripped from the text OUTSIDE the quotation marks before asking
#: whether anything unquoted is left, so the module's own markers are not read as prose it invented.
_MARKER = re.compile(r"\[\d+\]")
#: Any letter or digit, in any script. `\W` is unicode-aware here, so `ü` counts and `—` does not.
_ANY_WORD = re.compile(r"[^\W_]")
_QUOTED_SPAN = re.compile(f"{OPEN_QUOTE}([^{OPEN_QUOTE}{CLOSE_QUOTE}]+){CLOSE_QUOTE}")


def _ends_in_abbreviation(chunk: str) -> bool:
    """True when the full stop that ended `chunk` was an abbreviation's or an ordinal's, not a sentence's."""
    tail = _TRAILING_TOKEN.search(chunk)
    if not tail:
        return False
    token = tail.group(1)
    return token.isdigit() or token.lower() in _ABBREVIATION


def _clean_markup(sentence: str) -> str:
    """Emphasis characters out, whitespace collapsed. The member reads prose, not markdown.

    This is the only transformation applied between a passage and the member's screen, and it is undone
    on both sides by `_fold_for_quoting`, so a cleaned sentence still verifies against its raw passage.
    """
    return re.sub(r"\s+", " ", sentence.replace("*", "")).strip()


def quotable_sentences(text: str) -> list[str]:
    """One passage split into the sentences a member could be shown, longest-lived first by position.

    Markdown headings are dropped: `# Der Bezug eines 3a-Guthabens` is a label on an argument, not a
    statement of it, and a heading quoted at a member reads as an assertion it was never making.
    """
    found: list[str] = []
    for line in _LINE.split(text or ""):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = _LIST_MARKER.sub("", line).strip()
        if not line:
            continue
        pending = ""
        for part in _SENTENCE_BOUNDARY.split(line):
            pending = f"{pending} {part}" if pending else part
            if not _ends_in_abbreviation(pending):
                found.append(pending)
                pending = ""
        if pending:
            found.append(pending)
    return [
        sentence for sentence in found
        if len(sentence) >= MIN_QUOTABLE_CHARS
        and OPEN_QUOTE not in sentence
        and CLOSE_QUOTE not in sentence
    ]


def _fold_for_quoting(text: str) -> str:
    """The form two strings are compared in when asking whether one was quoted from the other.

    Applied to the answer and to the passage alike, so it can only ever make the check *accept* a
    difference this module itself introduced — collapsed whitespace, removed emphasis, one spelling of an
    apostrophe. It cannot make it accept a different sentence. `interpret.py::_normalise` is the same idea
    for the same reason: verification has to compare like with like or it discards correct readings.
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    for fancy in ("’", "′", "‘"):
        folded = folded.replace(fancy, "'")
    folded = folded.replace("*", "").replace("_", "")
    return re.sub(r"\s+", " ", folded).strip()


def unquoted_sentences(answer: str, passages: Sequence[Passage]) -> list[str]:
    """Everything in the answer that is not a quotation from a passage the member is being shown.

    **This is the guard the owner's decision rests on, and it is a property of the emitted string rather
    than a promise about the model.** It reports two different failures, and both are the same failure:

    · a span between quotation marks that occurs in none of the passages — the model was asked for
      numbers and the assembly is built from the sentences those numbers name, so this can only fire if
      the assembly is wrong. It is here because "can only fire if the code is wrong" is exactly the class
      of thing that stops being true when someone edits the code.
    · any letter or digit standing OUTSIDE the quotation marks — the half that matters. It is what makes
      "the member reads nothing that is not quoted" checkable rather than assertable. A sentence of
      commentary added between two quotes, a lead-in, an "also gilt:", a summary at the end: all of them
      show up here, and every one of them is a sentence nobody can trace to a source.

    Returns the offending fragments so the caller can report *what* rather than *that*. It never returns
    the passages, and the caller never logs what it returns — C-04, and A36's obligation above.

    **Not vacuous:** with no passages every quoted span is unverifiable, which is the honest reading of
    "nothing was retrieved and something was nevertheless quoted".
    """
    haystacks = [_fold_for_quoting(passage.text) for passage in passages]
    offending: list[str] = []
    outside: list[str] = []
    cursor = 0
    for match in _QUOTED_SPAN.finditer(answer):
        outside.append(answer[cursor:match.start()])
        cursor = match.end()
        needle = _fold_for_quoting(match.group(1))
        if not needle or not any(needle in haystack for haystack in haystacks):
            offending.append(match.group(1))
    outside.append(answer[cursor:])

    remainder = _MARKER.sub(" ", "".join(outside)).strip()
    if _ANY_WORD.search(remainder):
        offending.append(remainder)
    return offending


@dataclass(frozen=True)
class Quote:
    """One quoted sentence and the passage it is a substring of. R-171's citation is built from this one.

    The pairing is the point: the citation the member sees under marker `[i]` is `passage.citation()` of
    the quote that carries that marker, so there is no arrangement in which the text and the citation
    disagree about which document the words came from.
    """

    passage: Passage
    text: str

    def as_dict(self) -> dict:
        return {"text": self.text, "citation": self.passage.citation()}


def render(quotes: Sequence[Quote]) -> str:
    """The quotes as one line of running text, each marked with the index of its own citation.

    **One line, and that is not a stylistic choice.** `client/surfaces/know.js` puts this string into a
    `<p>` as a text node and `.cell-prompt` sets no `white-space`, so a newline written here would be
    rendered as a space and a member would read two quotations run together with no seam. The marker is
    the seam. `[1]` is the first entry of `citations`, which the panel already lists in order.
    """
    return " ".join(
        f"{OPEN_QUOTE}{quote.text}{CLOSE_QUOTE} [{index + 1}]"
        for index, quote in enumerate(quotes)
    )


# ------------------------------------------------------------------------------------------------
# What the model is asked, which is never for a sentence.

_SELECT_SYSTEM = """Du wählst aus nummerierten Sätzen einer einzelnen Quelle diejenigen aus, die eine Frage beantworten.

Du schreibst keine eigenen Sätze und formulierst nichts um. Du gibst NUR JSON zurück, genau so:

{"saetze": [3]}

Regeln:
- Höchstens zwei Nummern. Einzelne Nummern, niemals ein Bereich.
- Nimm nur Sätze, die die Frage unmittelbar beantworten.
- Fragt die Frage nach einem Betrag, einer Zahl, einer Frist oder einem Alter, dann wähle den Satz, der
  genau diese Grösse nennt. Ein Satz über das Thema, der die Grösse nicht nennt, beantwortet die Frage
  nicht.
- Handelt diese Quelle von etwas anderem als die Frage, gib {"saetze": []} zurück.
- Beantwortet kein Satz die Frage, gib {"saetze": []} zurück. Das ist eine richtige Antwort.
- Gib keinen Rat, keine Empfehlung und keine Bewertung. Nur die Nummern.
"""

#: Two worked examples of the SHAPE, in a domain the corpus knows nothing about.
#:
#: Deliberately about bicycles and dogs. An example drawn from Vorsorge would be a worked answer to a
#: pension question sitting inside the prompt of a pension question, and the failure this whole change
#: exists to stop is a model reproducing a pension sentence in the wrong place. `interpret.py` uses four
#: shots for the same reason and takes the same care with them.
#:
#: The second shot is the one that earns its place: it shows that the empty list is an output, not a
#: failure. Without it the model reliably returned its best near-miss for a question the source did not
#: answer, which under extraction means quoting a true sentence about something else.
_SELECT_EXAMPLES = """Beispiel.
Quelle: Ein Merkblatt über Fahrräder
[1] Ein Velo hat zwei Räder.
[2] Die Beleuchtung ist bei Nacht vorgeschrieben.

Frage: Muss ein Velo bei Nacht beleuchtet sein?
Ausgabe: {"saetze": [2]}

Beispiel.
Quelle: Ein Merkblatt über Fahrräder
[1] Ein Velo hat zwei Räder.

Frage: Was kostet eine Zugfahrkarte?
Ausgabe: {"saetze": []}

"""

_RANK_SYSTEM = """Du ordnest nummerierte Sätze danach, wie unmittelbar sie eine Frage beantworten.

Du schreibst keine eigenen Sätze. Du gibst NUR JSON zurück, genau so:

{"saetze": [3, 1]}

Regeln:
- Höchstens drei Nummern, die beste zuerst.
- Lass jeden Satz weg, der die Frage nicht beantwortet.
- Beantwortet kein Satz die Frage, gib {"saetze": []} zurück.
- Gib keinen Rat und keine Bewertung. Nur die Nummern.
"""

#: The key the model answers under. ASCII, because it is a JSON key travelling through a model that was
#: asked for JSON, and `saetze` cannot come back subtly re-encoded the way `sätze` can.
_NUMBERS_KEY = "saetze"


#: The two answers this service gives without a model: nothing was retrieved, and the model is not
#: running. They were `if language == "de" else <English>`, which meant a French or Italian member got a
#: correctly localised *refusal* from `boundary.py` and then English for these — the same gap C-01 had
#: before French and Italian were added to the gate, one layer up. Same four languages, and the same
#: fallback rule: `normalise_language` decides, so an unsupported locale lands where it is told to.
NOTICE = {
    "de": {
        "personal_needs_household": "Um das auf Ihre Lage zu beziehen, fehlt die Zusammensetzung Ihres Haushalts. Sie steht am Anfang und setzt den AHV-Weg, den Steuerweg und die Frage, wem ein Ziel gehört.",
        "personal_needs_position": "Um das auf Ihre Lage zu beziehen, fehlt eine erste Position — in der Regel das Einkommen.",
        "personal_needs_goal": "Um das auf Ihre Lage zu beziehen, fehlt ein erstes Ziel: wofür, wie viel und bis wann.",
        "computation_needs_input": "Das lässt sich für Sie ausrechnen, sobald eine Angabe vorliegt: {inputs}.",
        "figure_not_in_sources": "In dieser Antwort stand eine Zahl, die in den angegebenen Quellen nicht vorkommt. Deshalb zeige ich die Antwort nicht — die Quellen unten stehen unverändert da, und eine Kuratorin oder ein Kurator kann die Frage beantworten.",
        "nothing_answers": "Zu Ihrer Frage gibt es Material, aber kein Satz darin beantwortet sie. Hier "
        "steht nur, was wörtlich in einer Quelle steht, und dazu steht dort nichts. Fragen Sie anders, "
        "oder sprechen Sie mit einer Kuratorin oder einem Kurator.",
        "not_quoted": "In dieser Antwort stand ein Satz, der so in keiner der Quellen steht. Deshalb "
        "zeige ich sie nicht. Ihre Unterlagen sind unverändert da, und eine Kuratorin oder ein Kurator "
        "kann die Frage beantworten.",
        "nothing_found": "Dazu finde ich in Ihren Unterlagen und im Lernmaterial nichts. Fragen Sie "
        "anders, oder sprechen Sie mit einer Kuratorin oder einem Kurator.",
        "model_unavailable": "Das lokale Modell läuft gerade nicht, also gibt es hier keine Antwort. "
        "Ihre Unterlagen sind unverändert da.",
        "model_too_slow": "Das lokale Modell hat für diese Frage länger gebraucht als die "
        "vorgesehene Zeit. Es läuft — es war nur nicht rechtzeitig fertig. Versuchen Sie es noch "
        "einmal; Ihre Unterlagen sind unverändert da.",
    },
    "en": {
        "personal_needs_household": "To relate this to your own situation, your household composition is missing. It comes first, and it sets the AHV path, the tax path and whose goal is whose.",
        "personal_needs_position": "To relate this to your own situation, a first position is missing — usually your income.",
        "personal_needs_goal": "To relate this to your own situation, a first goal is missing: what for, how much, and by when.",
        "computation_needs_input": "This can be worked out for you once one answer is there: {inputs}.",
        "figure_not_in_sources": "This answer contained a figure that does not appear in the sources named below. It is therefore not shown. The sources are unchanged, and a curator can answer the question.",
        "nothing_answers": "There is material about your question, but no sentence in it answers the "
        "question. What appears here is only what a source says word for word, and none of it says this. "
        "Try asking differently, or speak to a curator.",
        "not_quoted": "This answer contained a sentence that appears in none of the sources. It is "
        "therefore not shown. Your documents are untouched, and a curator can answer the question.",
        "nothing_found": "I find nothing about that in your documents or in the learning material. Try "
        "asking differently, or speak to a curator.",
        "model_unavailable": "The local model is not running, so there is no answer here. Your "
        "documents are untouched.",
        "model_too_slow": "The local model took longer than the time allowed for this question. It is "
        "running — it simply did not finish in time. Try again; your documents are untouched.",
    },
    "fr": {
        "personal_needs_household": "Pour rapporter cela à votre situation, la composition de votre ménage manque. Elle vient en premier et détermine le parcours AVS, le parcours fiscal et à qui appartient un objectif.",
        "personal_needs_position": "Pour rapporter cela à votre situation, une première position manque — en règle générale le revenu.",
        "personal_needs_goal": "Pour rapporter cela à votre situation, un premier objectif manque: pour quoi, combien, et pour quand.",
        "computation_needs_input": "Cela peut être calculé pour vous dès qu'une indication existe: {inputs}.",
        "figure_not_in_sources": "Cette réponse contenait un chiffre qui ne figure pas dans les sources indiquées ci-dessous. Elle n'est donc pas affichée. Les sources sont intactes, et un curateur ou une curatrice peut répondre à la question.",
        "nothing_answers": "Il existe de la documentation sur votre question, mais aucune phrase n'y "
        "répond. Ici ne figure que ce qu'une source dit mot pour mot, et elle n'en dit rien. Posez la "
        "question autrement, ou parlez à un curateur ou une curatrice.",
        "not_quoted": "Cette réponse contenait une phrase qui ne figure dans aucune des sources. Elle "
        "n'est donc pas affichée. Vos documents sont intacts, et un curateur ou une curatrice peut "
        "répondre à la question.",
        "nothing_found": "Je ne trouve rien à ce sujet dans vos documents ni dans le matériel "
        "d'apprentissage. Posez la question autrement, ou parlez à un curateur ou une curatrice.",
        "model_unavailable": "Le modèle local ne tourne pas en ce moment, il n'y a donc pas de réponse "
        "ici. Vos documents sont intacts.",
        "model_too_slow": "Le modèle local a mis plus de temps que prévu pour cette question. Il tourne — "
        "il n'a simplement pas terminé à temps. Réessayez; vos documents sont intacts.",
    },
    "it": {
        "personal_needs_household": "Per riferire questo alla sua situazione manca la composizione della sua economia domestica. Viene per prima e determina il percorso AVS, quello fiscale e a chi appartiene un obiettivo.",
        "personal_needs_position": "Per riferire questo alla sua situazione manca una prima posizione — di regola il reddito.",
        "personal_needs_goal": "Per riferire questo alla sua situazione manca un primo obiettivo: per che cosa, quanto e entro quando.",
        "computation_needs_input": "Questo può essere calcolato per lei non appena esiste un'indicazione: {inputs}.",
        "figure_not_in_sources": "Questa risposta conteneva una cifra che non compare nelle fonti indicate qui sotto. Per questo non viene mostrata. Le fonti sono intatte, e un curatore o una curatrice può rispondere alla domanda.",
        "nothing_answers": "Sulla sua domanda esiste del materiale, ma nessuna frase vi risponde. Qui "
        "compare soltanto ciò che una fonte dice alla lettera, e in merito non dice nulla. Provi a "
        "formulare la domanda diversamente, oppure parli con un curatore o una curatrice.",
        "not_quoted": "Questa risposta conteneva una frase che non compare in nessuna delle fonti. Per "
        "questo non viene mostrata. I suoi documenti sono intatti, e un curatore o una curatrice può "
        "rispondere alla domanda.",
        "nothing_found": "Non trovo nulla in merito nei suoi documenti né nel materiale didattico. "
        "Provi a formulare la domanda diversamente, oppure parli con un curatore o una curatrice.",
        "model_unavailable": "Il modello locale al momento non è in funzione, quindi qui non c'è "
        "risposta. I suoi documenti sono intatti.",
        "model_too_slow": "Il modello locale ha impiegato più tempo del previsto per questa domanda. "
        "È in funzione — semplicemente non ha finito in tempo. Riprovi; i suoi documenti sono intatti.",
    },
}


def _say(key: str, language: str) -> str:
    """One notice, in the member's language, with `boundary.py`'s fallback rule and not another one."""
    return NOTICE[normalise_language(language)][key]


#: A number as it appears in Swiss prose: `7'258`, `26 500`, `8'950'000`, `0,6`, `6.8`, `150`.
#:
#: **A group separator is only a separator between digits, and only in groups of three.** The first
#: version allowed a bare `.` or space anywhere inside a run of digits, which turned "Artikel 2. Absatz
#: 3" into the figure `23` — two ordinals welded into a quantity that appears nowhere. A decimal comma
#: was missing entirely, so `6,8` parsed as two single digits and was skipped by the length floor: a
#: hallucinated conversion rate walked straight through the check meant to catch it.
_FIGURE = re.compile(r"\d+(?:[’'  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")

#: Single digits are not checked. `3` in "Säule 3a", `2` in "Artikel 2", the `1` in "ein bis fünf" — these
#: are labels and ordinals, not quantities, and requiring each to appear as a figure of its own would
#: refuse constantly while proving nothing. Two digits is low enough to cover a RATE, which is where this
#: floor was first set wrong: at three digits a hallucinated "6,8 Prozent" passed unchecked, and a made-up
#: conversion rate is exactly as damaging as a made-up amount.
MINIMUM_CHECKED_DIGITS = 2


def _digits(text: str) -> str:
    """`7'258` and `7 258` and `7258` all become `7258`. `0,6` becomes `06`."""
    return "".join(character for character in text if character.isdigit())


def unverifiable_figures(answer: str, passages: Sequence[Passage]) -> list[str]:
    """Every figure in the answer that does not occur in any passage the member was shown.

    **What this closes.** The model is grounded, cited, and still capable of producing a number that is in
    none of its sources — a plausible-looking statutory maximum, a contribution rate, a threshold. A
    member has no way to tell that apart from a figure it read correctly, and the citation makes it look
    checked. This is the same instinct the onboarding interpreter already applies one layer over, where
    every value the model returns is verified to appear in the member's own text.

    **What this does NOT close, stated because it was asked directly.** It catches a figure that is
    *absent* from the sources. It does not catch a figure that is present and *misapplied* — the observed
    failure was an answer that took the 20–80 % Teilbezug band, which is genuinely in the corpus, and
    presented it as a range of pension reductions. Both numbers verify here and the sentence is still
    false. Closing that needs an entailment check, not an arithmetic one; see A76 and the open note in
    DECISIONS.md.

    Comparison is on digits only, so `7'258` in a passage verifies `7258` in the answer and the two
    spellings are the same figure. Figures shorter than `MINIMUM_CHECKED_DIGITS` are skipped, for the
    reason given at that constant.

    **Matching is against the SET of figures in the passages, not their concatenated text.** The first
    version of this function joined every passage's digits into one string and asked whether the
    answer's digits appeared anywhere in it. That verifies far too much: a passage containing
    `26 500` would confirm an invented `500`, `265`, `650` and `2650`, because each is a substring.
    A figure has to match a figure.
    """
    known = {
        digits
        for passage in passages
        for digits in (_digits(m.group(0)) for m in _FIGURE.finditer(passage.text))
        if digits
    }
    unverified: list[str] = []
    for match in _FIGURE.finditer(answer):
        raw = match.group(0).strip(" '’. ")
        digits = _digits(raw)
        if len(digits) < MINIMUM_CHECKED_DIGITS:
            continue
        if digits not in known and raw not in unverified:
            unverified.append(raw)
    return unverified


def _numbers_from(prompt: str, system: str, model: str) -> tuple[list[int], str]:
    """One model turn that may only answer with numbers. Returns the numbers and the model's name.

    **`temperature` is the library default of zero, and that is a change from the prose answer this
    replaced.** A grounded prose answer wanted 0.1 because zero produces a stilted register; a selection
    has no register. What it has is the property `interpret.py` states directly — "a reading that varies
    between runs is not a reading" — and the old failure's worst feature was that it appeared in some runs
    and not others. Measured across the six AHV questions, selection at zero returned the same numbers in
    every run of every question.

    Anything that is not a list of numbers is an empty selection, not an error: a model that returned
    prose here has said nothing this function is allowed to hear.
    """
    reply = llm.chat(prompt, system=system, model=model, json_mode=True,
                     timeout_s=llm.SELECTION_TIMEOUT_S)

    # C-01 scanned this raw reply before it was parsed, and raised if the model had argued a case instead
    # of listing numbers. That scan is gone (A164). The parse below is now the only thing that stands
    # between a model that ignored its instructions and this function's return value — and it is
    # sufficient for THIS function, because anything that is not a list of numbers returns an empty
    # selection. A model that argued here says nothing rather than saying something to the member.
    try:
        parsed = json.loads(reply.text)
    except json.JSONDecodeError:
        return [], reply.model
    if not isinstance(parsed, dict):
        return [], reply.model
    picked = parsed.get(_NUMBERS_KEY)
    if not isinstance(picked, list):
        return [], reply.model
    # `isinstance(True, int)` is True in Python, and a stray `true` in the list would silently become
    # sentence 1. Booleans are excluded by name rather than by hoping they never appear.
    return [n for n in picked if isinstance(n, int) and not isinstance(n, bool)], reply.model


def _deadline() -> float:
    """When the selection pass has to be over, on a clock that cannot go backwards.

    `time.monotonic` and not `time.time`: this measures how long a member has been waiting, and a member
    who is waiting when the machine's clock is corrected has not started waiting again.
    """
    return time.monotonic() + llm.SELECTION_BUDGET_S


def select_quotes(passages: Sequence[Passage], *, question: str, model: str,
                  deadline: float | None = None) -> tuple[list[Quote], str]:
    """Which retrieved sentences answer the question, asked of one source at a time.

    **One call per passage rather than one call over all of them, and this was measured rather than
    preferred.** A single pass over every sentence at once was wrong on two of six AHV questions and, on
    the longest candidate list, degenerated into returning a consecutive run of seventy numbers — "select
    everything", which under extraction is a wall of quotation with the answer buried in it. The misses
    all had one shape: a true sentence from the source whose *title* matched the question, chosen over the
    sentence that carried the answer. Asking each source on its own removes the competition, and it went
    to 18 of 18 across three runs of six questions.

    It costs up to `MAX_PASSAGES` model calls where there was one. Measured end to end against apertus:8b
    on this machine: 2.0 s to 18 s, typically about 4 s.

    A passage that yields no quotable sentence is skipped without a call. A number outside the range is
    discarded — `interpret.py`'s rule, that a value which cannot be traced to the source is dropped rather
    than surfaced with a caveat.
    """
    chosen: list[Quote] = []
    named = model
    for passage in passages:
        if deadline is not None and time.monotonic() > deadline:
            # The member has waited long enough. Stopping here and quoting the sources that did answer
            # would be the partial search this function refuses to report as an answer, so it is the same
            # outcome as a daemon that is not running, and it says so.
            raise llm.LocalModelUnavailable(
                "the selection pass ran past its budget before every source had been read"
            )
        sentences = quotable_sentences(passage.text)
        if not sentences:
            continue
        listing = "\n".join(
            f"[{i + 1}] {_clean_markup(sentence)}" for i, sentence in enumerate(sentences)
        )
        prompt = (
            f"{_SELECT_EXAMPLES}Quelle: {passage.title}\n{listing}\n\n"
            f"Frage: {question}\nAusgabe:"
        )
        picked, named = _numbers_from(prompt, _SELECT_SYSTEM, model)
        if len(picked) > MAX_QUOTES_PER_SOURCE:
            # Not a selection. A model that named more sentences than a source is allowed to contribute
            # has not chosen between them, and truncating its list to the first two would be this module
            # choosing while reporting that the model did.
            continue
        for number in picked:
            if 1 <= number <= len(sentences):
                chosen.append(Quote(passage, _clean_markup(sentences[number - 1])))
    return chosen, named


def rank_quotes(quotes: Sequence[Quote], *, question: str, model: str) -> tuple[list[Quote], str]:
    """The union of the per-source selections cut to `MAX_QUOTES`, best first.

    Ordering is the second half of the job the model is kept for, and it is the half that shows: six
    sources each offering their best sentence is six sentences, and the one that answers is not reliably
    the one from the highest-scoring passage. On the Mindestbeitrag question the union carried six quotes
    and this pass reduced them to the one that names the figure, in every run.

    Below the cap there is nothing to rank, so no call is made.
    """
    if len(quotes) <= MAX_QUOTES:
        return list(quotes), model

    listing = "\n".join(f"[{i + 1}] {quote.text}" for i, quote in enumerate(quotes))
    prompt = f"Sätze:\n{listing}\n\nFrage: {question}\nAusgabe:"
    picked, named = _numbers_from(prompt, _RANK_SYSTEM, model)
    if not picked or len(picked) > MAX_QUOTES:
        # The ranking pass said nothing usable. The selections stand in retrieval order rather than being
        # thrown away: they are quoted material either way, and the order is the part that was lost.
        return list(quotes[:MAX_QUOTES]), named
    ordered = [quotes[n - 1] for n in picked if 1 <= n <= len(quotes)]
    return ordered[:MAX_QUOTES], named


#: Item 1: "Branch 2 with an empty Vault does not fail. It answers the population part of the question,
#: then names the single input that would make it personal, and offers to start there."
#:
#: **In the order the intake asks them**, which is item 3's order and not an arbitrary one: household
#: composition first, because it sets the AHV path, the tax path and goal ownership; then a position; then
#: a goal. That is also the light-intake floor — "household composition, one goal, and enough besides to
#: ground one finding" — so naming the first missing one names the next step towards a finding rather than
#: an arbitrary hole.
#:
#: **One, not a list.** Principle 4's shape applied to a prompt: a member who is told three things are
#: missing has been handed a backlog, and a member told one has been handed a next step.
_PERSONAL_INPUT_ORDER = (
    ("household_composition", "personal_needs_household"),
    ("income_position", "personal_needs_position"),
    ("first_goal", "personal_needs_goal"),
)


def missing_personal_input(session: Session, *, member_id: str, language: str) -> dict | None:
    """The one input that would let a branch-2 answer be about this member. `None` when nothing is missing.

    `None` does not mean the answer WAS personal — only that the Vault holds enough that the reason it was
    not is something other than an empty Vault. Saying "you are missing nothing" alongside an impersonal
    answer would be worse than saying nothing.
    """
    # `services/inputs` answers "which of these has the member given" for BOTH directions — the push here
    # and the content hooks' pull in `services/hooks`. Item 5: "One implementation serves both." These
    # predicates lived here first and were extracted rather than copied.
    from .inputs import stated as stated_inputs

    have = stated_inputs(session, member_id=member_id)
    for key, phrase in _PERSONAL_INPUT_ORDER:
        if key not in have:
            return {
                "key": key,
                "sentence": _say(phrase, language),
                # What the client opens. A route, not a rendered button label — the copy is the client's
                # and the destination is the server's.
                "starts_at": "intake",
            }
    return None


def own_material(session: Session, *, member_id: str, question: str) -> list[Passage]:
    """Everything a member may be shown from inside the application: their vault, plus the curriculum.

    Kept because it is what a branch-2 answer wants and what the existing callers mean. It is now a
    composition of the two functions above rather than one loop over two data classes, so a caller that
    must not touch member data has something to call instead of a flag to pass.
    """
    return member_material(session, member_id=member_id, question=question) + learning_material(
        session, question=question
    )


def ask(
    session: Session,
    *,
    member_id: str,
    question: str,
    language: str = "de",
    model: str | None = None,
) -> Answer:
    """S-08. The one entry point, with the boundary on both sides of the model.

    **What reaches a member is the retrieved material itself.** Every sentence they read is a sentence out
    of a passage, marked with the index of the citation it came from; the model chose which ones and in
    what order, and had no way to write one. The reasoning is in this module's docstring and the decision
    is the owner's.
    """
    # -- 1. the two-branch router (item 1) ---------------------------------------------------------
    #
    # **There is no inbound refusal here since A165.** The router had a third branch, decided by C-01's
    # inbound classifier, which refused a question that asked what to do and routed it to a curator
    # without an answer. C-01 was withdrawn (A164) and the branch went with it. What the router still
    # decides is the one thing that was never about licensing: whether this question is about the person
    # asking it, and therefore whether their vault may be read to answer it.
    routed = route_question(question)

    # -- 1b. the computation registry (the member branch only) --------------------------------------
    #
    # **The boundary this branch is named after is `per_member_computation`, and until now nothing on
    # this path computed anything.** A question about the member's own situation went to vector search
    # over prose, which answered one of the ten loaded members' opening questions. The other nine were
    # not missing documents; they were arithmetic this build already had.
    #
    # Placed here deliberately: BEFORE retrieval, so a question with an arithmetic answer is not first
    # answered badly out of a book. It used to sit after the inbound refusal as well, so that a question
    # asking what to do never reached a computation; that refusal is gone (A165) and this placement now
    # rests only on the retrieval argument.
    computed = None
    if routed.branch is Branch.MEMBER_SITUATION:
        computed = computations.answer(session, member_id=member_id, question=question,
                                       language=language)
    if computed is not None and computed.determined and ANSWER_MODE != "compose":
        # The outbound scan that used to run on this text is gone with C-01. Computed text now reaches
        # the member exactly as rendered.
        #
        # **Quoting only, since 21 September 2026.** Composing does not return here: the figures are
        # handed to `compose.answer` as settled and unalterable, and the answer says what they mean for
        # the question that was asked. Returning the rendered computation was right while the only
        # alternative was a quotation, because a computation beats a quotation; it is no longer right
        # when the alternative can use the computation AND the corpus AND the member's record in one
        # answer. The exact figures stay on the `computation` key either way, so a curator reading the
        # record can always see what was computed rather than what was written about it.
        return Answer(
            question=question,
            text=computed.text,
            citations=[{"kind": computations.KIND, "source": source}
                       for source in computed.sources],
            route=routed.as_dict(),
            computation={"key": computed.key, "inputs": computed.inputs,
                         "caveats": computed.caveats},
        )

    # -- 2. grounding -----------------------------------------------------------------------------
    # Retrieval runs HERE and nowhere earlier. C-01's inbound gate is above it, so a question that asks
    # what to do is refused before a single passage is read — including before the corpus is touched.
    #
    # **`own_material` is called only when the route permits it.** Before item 1 it was called for every
    # question, so "how does the AHV household cap work" read the member's vault to answer a fact about
    # the world. Nothing leaked — the corpus outscored it or it did not match — but the first boundary was
    # crossed to answer a question that sits below it, and "no member data touched" was not true of the
    # code. The permission is on the route rather than in an `if` here, so a fourth branch inherits an
    # answer instead of a default.
    composing = ANSWER_MODE == "compose"
    corpus, found = corpus_material(question, relief=COMPOSE_FLOOR_RELIEF if composing else 0)
    # The curriculum is impersonal and is retrieved on every branch. The member's vault is not, and is
    # retrieved only where the route permits it — which is the difference `learning_material` and
    # `member_material` exist to express.
    inside = learning_material(session, question=question)
    if routed.reads_member_data:
        inside = member_material(session, member_id=member_id, question=question) + inside

    # The member's OWN RECORD — positions, goals, household, what they stated about themselves. Same
    # permission as the vault and for the same reason (`services/member_ground.py` argues it at length);
    # retrieved only while composing, because a quoted answer cannot quote a table of francs into a
    # sentence and C-11's shape has no place to put one.
    own_record: list[Passage] = []
    if composing and routed.reads_member_data:
        own_record = member_ground.passages(session, member_id=member_id, question=question)

    # **The record is added to the capped list rather than competing for a slot in it**, which takes the
    # ceiling from `MAX_PASSAGES` to at most four more. Deliberate, and the cap's own reasoning is why:
    # it exists so a prompt cannot grow with a member's vault until it silently overruns the context
    # window. These four are bounded by the shape of the record and not by anything a member can add to,
    # so they cannot be the thing that makes it grow. Making them compete would mean a member's own
    # figures being dropped for a book passage, which is the failure this whole change is about.
    passages = own_record + assemble(inside, corpus)
    ground = {"mode": found.mode, "reason": found.reason, "floors": found.floors}

    # Branch 2 with nothing recorded yet. The population part of the question is still answered below —
    # item 1 is explicit that this case "does not fail" — and what is added is the one input that would
    # make the answer about them.
    personalisation = (
        missing_personal_input(session, member_id=member_id, language=language)
        if routed.branch is Branch.MEMBER_SITUATION
        else None
    )
    # A computation that MATCHED but could not run knows exactly which input is missing, which is a
    # better thing to ask for than the generic next input. It does not stop retrieval — the population
    # part of the question is still answered below — it replaces the guess about what to ask for.
    if computed is not None and not computed.determined and computed.missing:
        personalisation = {
            "key": computed.missing[0],
            "sentence": _say("computation_needs_input", language).format(
                inputs=", ".join(computed.missing)),
            "computation": computed.key,
        }
    carried = {"route": routed.as_dict(), "personalisation": personalisation}

    have_computation = computed is not None and computed.determined
    if not passages and not have_computation:
        return Answer(
            question=question,
            text=_say("nothing_found", language),
            citations=[],
            grounding=ground,
            **carried,
        )

    # -- 3a. composing (the default since 21 September 2026) ----------------------------------------
    #
    # The whole of C-11 is skipped here and its two checks run as an audit inside `compose.answer`
    # instead. `services/compose.py` states what that gives up and what it keeps; the switch back is
    # `ANSWER_MODE`.
    if composing:
        try:
            # `model` and not `model or llm.DEFAULT_MODEL`: composing has its own default, chosen by
            # measurement for writing German rather than for reading it, and defaulting here would
            # silently override it with the model picked for the selection calls. See `compose.MODEL`.
            written = compose.answer(
                passages, question=question, computed=computed,
                model=model, language=language,
            )
        except llm.LocalModelUnavailable as error:
            # Same posture as the quoting path: not available is never a guess. What IS distinguished is
            # a daemon that is running and slow from one that is not there — they were one message until
            # 21 September 2026, when fifty of sixty members were told the model was not running while it
            # was running the whole time and reasoning past the budget. That sentence sends whoever reads
            # it to check an installation that is fine.
            too_slow = isinstance(error, llm.LocalModelTooSlow)
            return Answer(
                question=question,
                text=_say("model_too_slow" if too_slow else "model_unavailable", language),
                citations=[p.citation() for p in passages],
                unavailable=True,
                grounding=ground,
                **carried,
            )
        if not written.text:
            return Answer(
                question=question,
                text=_say("nothing_answers", language),
                citations=[],
                model=written.model,
                grounding=ground,
                **carried,
            )
        return Answer(
            question=question,
            text=written.text,
            # Every passage the answer was given, not only the ones it marked. A member following a
            # citation is checking what the answer was built on, and a source the model used without
            # marking would be invisible in a list of only the marked ones.
            #
            # The computation's own sources lead, where there was one. R-171 is that a member can see
            # where the words came from, and for the figures in a composed answer that is a service and
            # a content record rather than a page — the same citation the quoting path emits when it
            # returns a computation whole.
            citations=([{"kind": computations.KIND, "source": source}
                        for source in (computed.sources if have_computation else ())]
                       + [p.citation() for p in passages]),
            model=written.model,
            grounding={**ground, "mode_of_answer": "compose",
                       "marked": list(written.used), "audit": written.audit},
            computation=({"key": computed.key, "inputs": computed.inputs,
                          "caveats": computed.caveats, "text": computed.text}
                         if have_computation else None),
            **carried,
        )

    # -- 3. the model, which answers with numbers --------------------------------------------------
    try:
        chosen, named = select_quotes(passages, question=question, model=model or llm.DEFAULT_MODEL,
                                      deadline=_deadline())
        quotes, named = rank_quotes(chosen, question=question, model=named or llm.DEFAULT_MODEL)
    except llm.LocalModelUnavailable:
        # R-302's shape again: not available, never a guess. **Any** failed call lands here, including one
        # of six that timed out. A part-searched corpus that quotes confidently out of the four sources it
        # did reach is the silent degradation this build refuses everywhere else: the member cannot see
        # which source went missing, and the missing one is as likely as not the one that answered.
        return Answer(
            question=question,
            text=_say("model_unavailable", language),
            citations=[p.citation() for p in passages],
            unavailable=True,
            grounding=ground,
            **carried,
        )
    if not quotes:
        # Choosing nothing is a right answer, and it is the one the corpus most often has. Said plainly:
        # material came back, none of it answers this. Quoting badly is worse than refusing.
        return Answer(
            question=question,
            text=_say("nothing_answers", language),
            citations=[],
            model=named,
            grounding=ground,
            **carried,
        )

    # -- 4. what will be emitted, before serialisation ---------------------------------------------
    text = render(quotes)
    quoted_from = [quote.passage for quote in quotes]

    # The outbound scan that ran here is gone with C-01 (A164). What is below it is not: every sentence
    # the member reads still has to come out of a retrieved passage, and that check is A106's, not
    # C-01's. With the pattern layer withdrawn it is the only thing left standing between the corpus and
    # the member, which is why A164 promotes it to a constraint in its own right.

    # -- 4b. nothing the member reads may be unquoted ----------------------------------------------
    unquoted = unquoted_sentences(text, quoted_from)
    if unquoted:
        # The verified property, and the whole point of the shape. It is checked against the passages the
        # answer actually quotes rather than against everything retrieved, so a quote cannot be
        # laundered by a passage that was retrieved and then not cited.
        return Answer(
            question=question,
            text=_say("not_quoted", language),
            citations=[q.passage.citation() for q in quotes],
            reason="not_quoted",
            model=named,
            grounding={**ground, "unquoted": len(unquoted)},
            **carried,
        )

    # -- 4c. every figure must be traceable to a passage -------------------------------------------
    invented = unverifiable_figures(text, quoted_from)
    if invented:
        # Kept, and under quoting it is very nearly redundant: a figure inside a quoted span is a figure
        # in the passage that span came from. It is retained because "very nearly" is an argument about
        # the code above it, and this check is an argument about the string itself.
        return Answer(
            question=question,
            text=_say("figure_not_in_sources", language),
            citations=[q.passage.citation() for q in quotes],
            reason="figure_not_in_sources",
            model=named,
            grounding={**ground, "unverifiable_figures": invented},
            **carried,
        )

    # -- 5. cite -----------------------------------------------------------------------------------
    # R-171, one citation per quote and in the quotes' own order, so `[i]` names `citations[i - 1]`.
    return Answer(
        question=question,
        text=text,
        citations=[quote.passage.citation() for quote in quotes],
        quotes=[quote.as_dict() for quote in quotes],
        model=named,
        grounding=ground,
        **carried,
    )


def open_curator_session(
    session: Session, *, member_id: str, curator_id: str, opened_from: str
) -> CuratorSession:
    """R-173 / C-10. The Curator button records the screen it was opened from.

    "Where were they when they needed a human" is the question this product should be able to ask about
    itself, and it can only be asked if the entry point is recorded at the time.

    **The curator is resolved here, not taken on the caller's word.** `CuratorSession.curator_id` is a
    foreign key since 31 August 2026, so the storage layer refuses an invented id on its own — but it
    refuses it as an `IntegrityError` naming a constraint, which tells a caller nothing about what it did
    wrong. This resolution is the second enforcement point every constraint in this build has, and it is
    the one that produces a sentence. Two callers reach this function: `api/main.py`'s
    `POST /api/curator/sessions` and `services/directory.open_identified_session`, and both already
    resolve. Resolving again is a few microseconds against the class of bug A67 recorded — the audit table
    whose whole worth is being true had no layer that could refuse a name.

    Imported inside the body because `services/directory.py` imports this module; at module scope the two
    would be a cycle.
    """
    from .directory import resolve_curator

    curator_id = resolve_curator(session, curator_id).id
    record = CuratorSession(member_id=member_id, curator_id=curator_id, opened_from=opened_from)
    session.add(record)
    session.flush()
    session.add(
        CuratorSessionEvent(session_id=record.id, kind="opened", actor=curator_id,
                            detail={"opened_from": opened_from})
    )
    return record


def action_items(session: Session, *, member_id: str, today: date | None = None) -> list[dict]:
    """R-174. Listed inside The Know, each expandable to its prepared options and their consequences.

    R-003: these are items in a list. They are never a count, a dot or a badge on navigation, and this
    function returns no total for that reason.
    """
    rows = session.execute(
        select(ActionItem).where(ActionItem.member_id == member_id, ActionItem.status == "open")
    ).scalars().all()

    # An item raised by a policy that has since been replaced is not news. Filtered at read time from the
    # vault's own notion of "current" rather than by mutating the item's status when a new version lands:
    # marking it `acted` would assert the member renewed, and they may simply have uploaded a better scan.
    # A query-time fact needs no inference; a status change would have required one.
    current = {item.id for item in current_items(session, member_id=member_id)}
    rows = [
        row for row in rows
        if row.source_vault_item_id is None or row.source_vault_item_id in current
    ]
    rows.sort(key=lambda r: (r.due_date is None, r.due_date))
    return [
        {
            "id": row.id,
            "trigger_kind": row.trigger_kind,
            "due_date": row.due_date.isoformat() if row.due_date else None,
            # C-06: never empty, minimum two, each with its consequence.
            "prepared_options": row.prepared_options,
            "source_vault_item_id": row.source_vault_item_id,
        }
        for row in rows
    ]
