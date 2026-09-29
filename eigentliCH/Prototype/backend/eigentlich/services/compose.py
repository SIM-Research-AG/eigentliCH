"""The Know answering in its own words, over everything it is allowed to see.

**This reverses C-11, and the reversal is the owner's, taken on 21 September 2026 with the trade in
front of him.** What C-11 bought was that every word a member read was a word out of a retrieved passage,
mechanically checked. What it cost was measured the day before: of fifty members asked the question they
came with, eight got an answer and forty-two were told some version of "I don't know". Thirty-six of those
forty-two had asked something no corpus could ever answer — "wie gross ist meine Vorsorgelücke wirklich",
"reicht unser Sparen für ein Eigenheim in sieben Jahren" — because the answer is arithmetic over their own
figures and a quotation cannot be arithmetic over anything.

**What is given up, said plainly rather than buried.** A composed answer can state something no source
backs. There is no mechanical check in this module that every clause is true, and there cannot be one —
that is what composition means. `unquoted_sentences` and `unverifiable_figures` still exist and still run,
but they run as an **audit** written into the answer's record rather than as a gate that refuses it: a
curator opening the run can see which sentences left the sources and which figures were not in them, and
that is now a thing to read rather than a thing that stops the answer.

**What is kept.**

- *The boundary is untouched.* The member's own record reaches this only on the branch that permits it,
  and the model is still local: `llm.chat` refuses a non-local host and C-05 has not moved.
- *Arithmetic is still not the model's.* Where `services/computations.py` can answer, its figures are
  handed to the model as settled and the prompt says they are not to be recomputed. A model that is good
  at prose and bad at multiplication should be asked for prose.
- *Citations stay.* Everything retrieved is numbered and the model is asked to mark what it used. A claim
  with no marker is a claim the answer is making on its own, and `audit` counts those.
- *One switch back.* `know.ANSWER_MODE` set to `quote` restores C-11 exactly: the quoting path is not
  deleted, is still tested, and still runs every check as a gate.

**The prompt is in German and the answer is in German**, because the member asked in German and every
string this product shows is. The system prompt carries the product's own posture — say what is not known,
do not invent a figure, do not instruct — because a model's default register is a salesman's and this one
is not selling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Sequence

from .. import llm
from . import prose

#: How long the composing call may take. Longer than a selection call because it is writing rather than
#: returning three integers, and a member waiting for an answer is a better failure than a timeout that
#: reports the corpus as empty.
TIMEOUT_S = float(os.environ.get("ANDERSCH_COMPOSE_TIMEOUT", "180"))

#: The model that writes. **Not `llm.DEFAULT_MODEL`, and the difference is measured rather than assumed.**
#:
#: The configured default is `qwen2.5:14b`, chosen for *reading* a member's text — selecting three
#: sentences, returning three integers — which is what every earlier caller of `llm.chat` did. Asked to
#: write 200 words of German on 21 September 2026 it produced two sentences of German and then switched to
#: Chinese, mid-clause, for the rest of the answer. The same question, same grounding:
#:
#:   - `qwen2.5:14b`  German for one line, then Chinese. Unusable.
#:   - `apertus:8b`   Fluent German, and invented an assumption nobody made ("angenommen, Ihre Ausgaben
#:                    steigen um 10% pro Jahr") plus eleven figures that are in no source. Worst on the
#:                    one axis that matters here.
#:   - `qwen3:8b`     German throughout, named what was missing instead of estimating it, one figure not
#:                    in a source. Chosen.
#:
#: Set `ANDERSCH_COMPOSE_MODEL` to override. The selection and ranking calls in `know.py` are untouched
#: and still use the configured default, because reading is the job it was picked for.
MODEL = os.environ.get("ANDERSCH_COMPOSE_MODEL", "qwen3:8b")

#: Scripts a German answer has no business containing. Checked because a model that drifts out of the
#: language does it mid-sentence and the first half reads perfectly — so a reviewer skimming the opening
#: sees nothing wrong. CJK, Cyrillic, Arabic, Hebrew, Devanagari.
_FOREIGN_SCRIPT = (
    (0x4E00, 0x9FFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF),
    (0x0400, 0x04FF), (0x0600, 0x06FF), (0x0590, 0x05FF), (0x0900, 0x097F),
)

#: Not zero, and deliberately. `llm.chat` defaults to a temperature of 0 because everything that used it
#: before was *reading* a member's text, where variation between runs is a defect. This is writing, and at
#: 0 the local models measured here produce the same four stock sentences for every member — which reads,
#: to fifty people comparing notes, exactly like the template it is.
TEMPERATURE = float(os.environ.get("ANDERSCH_COMPOSE_TEMPERATURE", "0.3"))

#: The posture, not the content. Everything factual comes from the grounding block.
SYSTEM_DE = (
    "Sie sind der Wissensteil von eigentliCH, einer Schweizer Finanzplanungsanwendung. "
    "Sie schreiben für das Mitglied selbst, auf Deutsch.\n"
    "\n"
    "Regeln:\n"
    "1. SIEZEN Sie durchgehend. «Sie», «Ihr», «Ihre» — niemals «du», «dein» oder «deine». Das ist "
    "die Anredeform der gesamten Anwendung und keine Stilfrage.\n"
    "2. Antworten Sie auf die gestellte Frage, nicht auf eine ähnliche.\n"
    "3. Stützen Sie sich auf die unten gegebenen Unterlagen. Wo Sie eine Unterlage verwenden, "
    "setzen Sie ihre Nummer in eckigen Klammern dahinter, etwa [2]. Jeder Satz, der eine Zahl oder "
    "eine Regel nennt, trägt eine solche Nummer.\n"
    "4. RECHNEN SIE NICHT. Übernehmen Sie jede Zahl genau so, wie sie in den Unterlagen steht. "
    "Bilden Sie keine Summen, keine Differenzen und keine Prozentsätze, auch nicht wenn es "
    "naheliegt. Bestände (Vermögen zu einem Zeitpunkt) und Flüsse (Franken pro Jahr) dürfen nie "
    "miteinander verrechnet werden. Wo eine Rechnung nötig wäre und unter BERECHNET keine steht, "
    "sagen Sie, welche Angabe dafür fehlt.\n"
    "5. Wo die Unterlagen die Frage nicht abdecken, sagen Sie das in einem Satz und schreiben Sie "
    "weiter, was sich sagen lässt. Ein offenes «dazu ist hier nichts erfasst» ist besser als eine "
    "glatte Antwort ohne Grundlage.\n"
    "6. Keine Handlungsanweisung und keine Empfehlung, was das Mitglied tun soll. Legen Sie dar, "
    "was gilt, was daraus folgt und wovon es abhängt.\n"
    "7. Antworten Sie in höchstens 200 Wörtern Fliesstext. KEINE Überschriften, KEINE Tabellen, "
    "KEINE Emoji, keine Trennlinien, keine Aufzählung ohne Not, keine Anrede und kein "
    "Abschiedsgruss. Das Mitglied liest einen Absatz, keine Präsentation.\n"
    "8. Wenn die Unterlagen ein Nachbarthema behandeln und nicht die gestellte Frage, sagen Sie "
    "das im ersten Satz, statt das Nachbarthema zu erklären."
)

#: The du-forms that must not survive into a member-facing string, and what each becomes.
#:
#: **A repair, not a gate, and that is the point.** Every local model measured against the prompt above
#: siezt for two sentences and then slips. A slip is not worth refusing an otherwise sound answer over,
#: and it is also not something a member of a Swiss financial application should ever read — so the answer
#: is repaired and the repair is counted in the audit, where a rising count is a sign the prompt has
#: stopped working on whatever model is configured.
#:
#: **Only the forms a word swap can get right.** Each of these is a pronoun or possessive whose polite
#: counterpart takes the same slot in the same sentence, so replacing it in place leaves German that
#: parses: `deinem Ziel` → `Ihrem Ziel`, `ich helfe dir` → `ich helfe Ihnen`.
#:
#: `du` is deliberately absent. It governs the verb — `du hast` is `Sie haben`, not `Sie hast` — and a
#: substitution that cannot conjugate produces a sentence that is worse than the one it replaced. A
#: surviving `du` is counted by `siezen` instead and shows up in the audit as `duzen_unrepaired`, which is
#: the honest report: the prompt failed, here is how often, and nobody papered over it.
#:
#: The targets are capitalised unconditionally, because that is the rule rather than a convention — the
#: polite `Sie`, `Ihr` and `Ihnen` carry a capital wherever they stand in the sentence, and a lower-case
#: `ihre` is a different word meaning "their".
_SIEZEN = {
    "deine": "Ihre", "deiner": "Ihrer", "deinen": "Ihren", "deinem": "Ihrem",
    "deines": "Ihres", "dein": "Ihr", "dich": "Sie", "dir": "Ihnen",
}


def siezen(text: str) -> tuple[str, int, int]:
    """The answer with the repairable du-forms replaced: `(text, repaired, unrepaired)`.

    Word-boundary anchored, so `durch`, `dies` and `Dirigent` are untouched.
    """
    import re

    repaired = 0

    def _one(match):
        nonlocal repaired
        target = _SIEZEN.get(match.group(0).casefold())
        if target is None:
            return match.group(0)
        repaired += 1
        return target

    # Longest first, so `deinen` is not matched as `dein` with a stray `en` left behind.
    pattern = re.compile(
        r"\b(" + "|".join(sorted(_SIEZEN, key=len, reverse=True)) + r")\b", re.IGNORECASE
    )
    out = pattern.sub(_one, text)
    unrepaired = len(re.findall(r"\bdu\b", out, re.IGNORECASE))
    return out, repaired, unrepaired


@dataclass
class Composed:
    """What the model wrote, and everything a reader needs to judge it."""

    text: str
    model: str
    #: Indices (1-based, into the passages given) the answer marked. What it claims to have used.
    used: tuple[int, ...] = ()
    #: The audit that used to be a gate. See the module docstring.
    audit: dict = field(default_factory=dict)


def _block(passages: Sequence, computed) -> tuple[str, list]:
    """The grounding, numbered, with the settled arithmetic first.

    Computed figures lead because they are the only part the model is forbidden to alter, and a constraint
    stated after nine paragraphs of prose is a constraint applied to the last paragraph.
    """
    lines: list[str] = []
    ordered: list = []

    if computed is not None and getattr(computed, "determined", False):
        lines.append("BERECHNET (bereits ausgerechnet, unverändert übernehmen):")
        lines.append(computed.text.strip())
        for caveat in getattr(computed, "caveats", None) or ():
            lines.append(f"  Vorbehalt: {caveat}")
        lines.append("")

    if passages:
        lines.append("UNTERLAGEN:")
        for index, passage in enumerate(passages, start=1):
            ordered.append(passage)
            where = f" — {passage.where}" if getattr(passage, "where", "") else ""
            lines.append(f"[{index}] {passage.title}{where}")
            lines.append(prose.for_prompt(passage.text))
            lines.append("")
    return "\n".join(lines).strip(), ordered


def _markers(text: str, count: int) -> tuple[int, ...]:
    """Which `[n]` the answer carries, in order, ignoring any the model invented."""
    import re

    seen: list[int] = []
    for raw in re.findall(r"\[(\d{1,2})\]", text):
        n = int(raw)
        if 1 <= n <= count and n not in seen:
            seen.append(n)
    return tuple(seen)


def drifted(text: str) -> int:
    """How many characters of the answer are in a script German does not use.

    Zero for every correct answer, which is what makes this usable as a gate. A handful would be a quoted
    name; the failure this catches is not subtle — the measured one was half the answer.
    """
    return sum(
        1 for char in text
        if any(low <= ord(char) <= high for low, high in _FOREIGN_SCRIPT)
    )


def answer(
    passages: Sequence,
    *,
    question: str,
    computed=None,
    model: str | None = None,
    language: str = "de",
    timeout_s: float | None = None,
) -> Composed:
    """One composed answer. Raises `llm.LocalModelUnavailable` exactly as the quoting path does.

    The caller decides what to do with an unavailable model; this does not invent a fallback, because a
    silently degraded answer is the thing this build refuses everywhere.

    **Retried once if the answer leaves German.** One retry rather than a loop: drift is a property of the
    model and the prompt, not of the draw, so a model that does it twice will do it ten times and the
    member is waiting. A second failure returns empty text, which `know.ask` reports as no answer rather
    than showing a member half a page of Chinese.
    """
    ground, ordered = _block(passages, computed)
    prompt = (
        f"FRAGE DES MITGLIEDS:\n{question.strip()}\n\n"
        f"{ground if ground else 'UNTERLAGEN: keine.'}\n\n"
        f"Schreiben Sie die Antwort."
    )
    chosen = model or MODEL
    budget = timeout_s if timeout_s is not None else TIMEOUT_S

    reply = llm.chat(prompt, system=SYSTEM_DE, model=chosen, timeout_s=budget,
                     temperature=TEMPERATURE, think=False)
    text = (reply.text or "").strip()
    drift = drifted(text)
    if drift:
        reply = llm.chat(
            prompt + "\n\nACHTUNG: Die Antwort muss vollständig auf Deutsch sein, von der ersten bis "
                     "zur letzten Silbe. Kein Wort in einer anderen Sprache oder Schrift.",
            system=SYSTEM_DE, model=chosen, timeout_s=budget, temperature=TEMPERATURE,
            think=False,
        )
        text = (reply.text or "").strip()
        if drifted(text):
            return Composed(text="", model=reply.model,
                            audit={"left_german": drift, "left_german_after_retry": drifted(text)})
    text, repaired, unrepaired = siezen(text)
    text, formatting = prose.for_member(text)
    checked = audit(text, ordered, computed)
    if formatting:
        checked["formatting_removed"] = formatting
    if drift:
        checked["left_german_then_retried"] = drift
    if repaired:
        checked["duzen_repaired"] = repaired
    if unrepaired:
        checked["duzen_unrepaired"] = unrepaired
    return Composed(
        text=text,
        model=reply.model,
        used=_markers(text, len(ordered)),
        audit=checked,
    )


def audit(text: str, passages: Sequence, computed=None) -> dict:
    """What the two C-11 checks say about a composed answer, recorded rather than enforced.

    Kept running because the numbers are the honest measure of what the reversal costs: `unquoted` counts
    the sentences that are the model's own rather than the corpus's, and `unverifiable_figures` counts the
    figures that appear in the answer and in no source. Under C-11 either one refused the answer. Here they
    are written into the record so a curator can see, per answer, how far from the sources it went.

    Deliberately tolerant of its own failure. This is instrumentation on the member's answer path, and an
    audit that raises would turn a reporting line into an outage.
    """
    from . import know

    # **The computed block is a source and has to be checked against, or the audit accuses the one part
    # of the answer that is fully derived.** Measured on the run of 60: the answer with the most
    # "unverifiable" figures was a property affordability case whose eight flagged numbers — the deposit,
    # the carrying cost, the multiple of income — were every one of them produced by
    # `services/property` through `computations`. They are the most traceable figures in the whole
    # answer, and the audit was calling them inventions because it only looked at retrieved prose.
    checked = list(passages)
    if computed is not None and getattr(computed, "determined", False):
        checked.append(know.Passage(
            kind="computation", source_id=getattr(computed, "key", "computation"),
            title="Berechnet", text=computed.text, score=1,
        ))

    out: dict = {}
    try:
        out["unquoted"] = len(know.unquoted_sentences(text, checked))
    except Exception as error:  # pragma: no cover - instrumentation must not break the answer
        out["unquoted_error"] = str(error)
    try:
        out["unverifiable_figures"] = know.unverifiable_figures(text, checked)
    except Exception as error:  # pragma: no cover
        out["unverifiable_figures_error"] = str(error)
    return out


__all__ = ["Composed", "SYSTEM_DE", "TEMPERATURE", "TIMEOUT_S", "answer", "audit"]
