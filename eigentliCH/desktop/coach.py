"""The coach: a local model answering financial questions from the house's own corpus and nothing else.

    from coach import answer
    result = answer("Warum zaehlt mein selbst bewohntes Haus nicht zum entnahmefaehigen Vermoegen?")

**What makes this shippable now, when the full chatbot module is not.** The data-class rule says a model reading
K1 or above must run inside the core perimeter, and that gate is the one thing standing between the chatbot
module and being switched on. This coach reads **K0 only**: five documents of the house's own
financial knowledge -- the set book, the model's own description, the method of the Standortbestimmung, the
register behind the allocation, and the AHV rules quoted from Merkblatt 2.03 and 3.04 -- and no household, no
twin, no recommendation.

**The corpus is an allow-list with a guard behind it, which is what keeps that claim true as it grows.**
`bookindex.SOURCES` names every document, and `_clean_or_refuse` refuses any file whose name or content marks
it as belonging to a person: a case file, a dossier, a saved submission, a derived mandate. It fired on the
method manual, whose footer listed five worked examples by filename, and those references were removed rather
than the file being dropped. A comment saying "do not add dossiers here" would not have caught that. There is no gate in front of K0 content, and it runs locally anyway.

The distinction is structural rather than promised. `answer()` takes a question and returns a reply; it has no
parameter through which a household could be passed, and the prompt is assembled from retrieved passages
alone. A model cannot disclose what it was never given — the same guarantee `prose.py` gets from `ReportFacts`
having no field for a second household, applied one layer up.

**Grounding is checked, not requested.** Three things are verified after generation, because a system prompt is a
preference and a check is a property:

  - **Every figure** in the reply must appear in a retrieved passage. `prose.py` learned this the hard way: a
    language model asked about a financial subject produces plausible numbers whether or not it was given them.
    The number reader is imported from there rather than written again.
  - **Retrieval must have found something.** Below a similarity floor the coach says its sources do not cover it
    instead of answering from whatever the model already believed.
  - **The reply must cite.** An answer with no passage behind it is indistinguishable from an invention, and the
    citations are returned as data so a surface can show them rather than trusting the prose to name them.
  - **Every claim carries the sentence it rests on, verified by substring rather than by similarity.** The
    model emits the English sentence it is relying on and code looks for it in the passages it was handed; a
    claim whose quote is not found is dropped before anyone reads it. This is the one check here with no
    threshold in it, and it exists because two thresholds were measured and both were inverted: an invented
    sentence scores HIGHER against the passages than a faithful one, because a fabrication uses the topic's
    vocabulary densely and a restatement is terse. What it buys is provenance, not truth -- the model can
    still attach a real quote to a claim that does not follow from it, and the display of the pair is what
    lets a reader catch that.
  - **A question of law is answered only from a source that is about rules.** The one time it was answered
    from the rest of the corpus the reply was fluent, correct in its conclusion, and wrong in every reason it
    gave -- including a rule it attributed to two sources that contain no such rule. That failure is invisible
    to the relevance gate, because the arithmetic the model performs on an AHV entitlement uses the same words
    as the obligation to pay one. So the check is on PROVENANCE: such a question is refused unless a retrieved
    passage, and then a verified claim, comes from the AHV document. Where nothing does, the refusal names the
    one legal subject this corpus does cover and points at the Ausgleichskasse, which is binding for the
    individual case whatever the Merkblätter say.

**It answers about the subject, not about the reader.** A question about someone's own position is redirected: that
is what the Befund is for, and it is computed rather than discussed.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bookindex as BI  # noqa: E402
from prose import _NUMBER_RE, _readings  # noqa: E402 - one number reader, not two

OLLAMA = "http://127.0.0.1:11434"
MODEL = "apertus:8b"
TIMEOUT_S = 240

#: The relevance gate, and an honest account of how much it is worth.
#:
#: **A multilingual embedding gives any German sentence a non-trivial similarity to a book-length English
#: corpus**, so the top cosine alone is a weak discriminator. Measured over eight on-topic and six off-topic
#: questions:
#:
#:     absolute top   on-topic min 0.501   off-topic max 0.483   separation 0.018
#:     margin         on-topic min 0.157   off-topic max 0.136   separation 0.021
#:
#: Both separate, and neither separates comfortably. So both are applied, set at the midpoint of the observed
#: bounds, and **neither is trusted as the only defence**. The gate is the coarse first line; the model's own
#: instruction to answer from the passages or say it cannot is the second; the number check is the third. A
#: threshold calibrated on fourteen questions is a filter, not a guarantee, and calling it one would be the
#: kind of overclaim this codebase keeps paying for.
#:
#: `MARGIN` is the top score less the median across the whole book: it asks whether one passage stands out,
#: which a real question produces and a general one does not.
RELEVANCE_FLOOR = 0.49
MARGIN_FLOOR = 0.145

#: Passages given to the model. Enough that a claim keeps its qualifier, few enough that the context stays
#: readable and the model cannot quietly pick a distant one.
K = 6

#: **The first version of this prompt led with the prohibition, and the coach refused a question it could
#: answer.** Asked why an owner-occupied home is excluded from drawable wealth, retrieval returned the passage
#: that says so in as many words — "a home one lives in funds no consumption" — and the model replied that the
#: book contained nothing. Putting the refusal template in rule 1 made refusing the safest-looking move.
#:
#: So the task comes first and the limits follow, and the prompt states that the passages have ALREADY been
#: selected as relevant. The model's job is to read them, not to re-adjudicate whether the question belongs —
#: that decision was made by the retrieval gate, which has the whole book to compare against and the model does
#: not. A refusal is still available and still required when the passages genuinely do not answer, but it is no
#: longer the path of least resistance.
SYSTEM = """Du bist ein Erklaerer fuer das Finanzwissen des SIM Research Institute.

Deine Quellen sind fuenf: das Buch "Capital Saturation", die Beschreibung des Modells "The Life Balance
Sheet", die Methodik der Standortbestimmung, das Portfolio Creation Program mit seinen Bausteinen und
Schranken, und die AHV-Regeln aus den Merkblaettern 2.03 und 3.04.

Die ersten vier beschreiben ein MODELL. Nur die fuenfte handelt von Regeln. Zu Beitragspflicht, Vorbezug und
Beitraegen als nichterwerbstaetige Person zitierst du aus ihr; zu allem anderen an Recht sagst du, dass die
Stellen dazu nichts hergeben.

Deine Aufgabe: Beantworte die Frage aus den uebergebenen Stellen, und zwar in Paaren. Jedes Paar besteht aus
einem BELEG - einem Satz, den du woertlich aus einer Stelle kopierst - und einer AUSSAGE, die genau diesen
Beleg auf Deutsch wiedergibt. Das genaue Format steht in der Aufgabe unter den Stellen.

Der Beleg wird geprueft: er muss Zeichen fuer Zeichen in einer der Stellen vorkommen. Ein Paar, dessen Beleg
sich dort nicht findet, wird verworfen und dem Leser nie gezeigt. Kopiere also, statt zu formulieren.

Die meisten Quellen sind auf Englisch, deine Antwort ist auf Deutsch. Uebersetze sinngemaess und nenne einen
englischen Fachbegriff einmal in Klammern, wenn er in der Stelle steht. Eine Quelle -- die zur AHV -- ist
bereits auf Deutsch: aus ihr zitierst du woertlich, ohne zu uebersetzen.

WICHTIG: Auch die AHV-Quelle ist keine Rechtsgrundlage, sondern gibt Merkblaetter wieder; verbindlich ist im
Einzelfall die zustaendige Ausgleichskasse. Zu allem, was nicht darin steht -- Steuern, Bewilligungen, andere
Fristen -- kannst du sagen, wie das Modell rechnet, nicht was das Gesetz verlangt. Erfinde keine Regel und
keinen Mechanismus, um eine Luecke zu fuellen: sage, dass die Stellen dazu nichts sagen.

Mische zwei Stellen nicht zu einer Aussage, die keine von beiden trifft. Vier Quellen bedeuten mehr
Gelegenheit dazu, nicht weniger: wenn zwei Stellen dasselbe Wort verschieden verwenden, sage das, statt einen
Mittelwert zu erfinden.

GRENZEN, die dabei gelten:
1. Stuetze dich nur auf die uebergebenen Stellen. Ergaenze nichts aus allgemeinem Wissen.
2. Nenne eine Zahl nur, wenn sie woertlich in DEM Beleg steht, zu dem die Aussage gehoert - nicht irgendwo
   in den Stellen. Erfinde und berechne keine Zahlen.
3. Gib keine Anlageberatung und keine Empfehlung. Kein "Sie sollten", kein Produkt, keine Allokation.
   Du erklaerst ein Modell, du wendest es nicht an.
4. Du kennst die persoenliche Lage des Fragenden nicht. Fragt jemand nach seiner eigenen Situation, erklaere
   die allgemeine Mechanik und verweise darauf, dass die Standortbestimmung die persoenlichen Zahlen rechnet.
5. Findet sich zu der Frage kein passender Satz, schreibe nur: KEINE STELLE. Erfinde keinen Beleg, um
   antworten zu koennen.
6. Eine Aussage ist ein ganzer deutscher Satz, sachlich, ohne Aufzaehlungszeichen. Sie gibt ihren Beleg
   wieder und fuegt nichts hinzu.
7. Keine Ueberschriften, keine Quellenangaben in eckigen Klammern, kein Vor- und Nachwort. Die Quelle jedes
   Belegs wird dem Leser getrennt angezeigt.
8. Gib keine Formeln in LaTeX aus. Schreibe Symbole so, wie sie in den Stellen stehen.
9. Schweizer Rechtschreibung: kein Eszett. Schreibe durchgehend "ss" - also Groesse, gemaess, Masse.
"""



#: Words that mark a question as one of LAW rather than of the model: an obligation, an entitlement, a
#: deadline, a permission. **The relevance gate cannot separate these and no threshold could.** A question
#: about whether AHV contributions are compulsory retrieves the manual's section on how the model computes an
#: AHV entitlement at 0.61, because the two share every word they use. The corpus can say what the model does;
#: it is not a legal source, and the difference is invisible to a cosine distance.
#:
#: Matched on word boundaries, so "muss ich" does not fire inside a longer word, and deliberately broad: a
#: question wrongly sent to the reframe below loses nothing but a round trip, while one wrongly answered
#: produces invented law in a client conversation. The two errors are not symmetric.
_LEGAL_MARKERS: tuple[str, ...] = (
    # A modal frame: what must, may or is forbidden to be done.
    "muss ich", "muessen sie", "müssen sie", "muss man", "müsste ich", "muesste ich",
    "darf ich", "darf man", "duerfen sie", "dürfen sie",
    # Named legal categories.
    "verpflicht", "gesetzlich", "vorschrift", "obligatorisch", "vorgeschrieben", "rechtlich",
    "strafbar", "erlaubt", "zulaessig", "zulässig", "frist", "nachzahl", "bewilligung",
    "meldepflicht", "beitragspflicht", "steuerpflicht", "versicherungspflicht", "abgabepflicht",
    # **`anspruch` and `pflicht` are matched in their legal frame, not alone.** Bare, they refused
    # questions about the model: in a corpus about pensions *Anspruch* is the ordinary word for the
    # entitlement being computed, and the manual's own headings use it. A guard that declines the
    # questions the corpus answers best looks effective and withholds the good answers.
    "anspruch auf", "anspruchsberechtigt", "habe ich anspruch", "besteht anspruch",
    "besteht ein anspruch", "pflicht zur", "pflichtig",
)

#: Answers that instruct rather than explain. Rule 3 of the prompt has always forbidden these and the model
#: wrote them anyway, which is why this is a check and not a preference: a Recommendation needs a named Curator
#: and a Decision Record (G7), and no chat reply has either.
#:
#: **A phrase list was not enough.** The first version listed "ich empfehle" and the model wrote "empfehle ich
#: Ihnen" -- the same verb, the other word order, straight through the filter. So the stems are matched
#: wherever they fall, and the second-person pronoun is not required.
_PRESCRIPTIVE_RE = re.compile(
    r"\b("
    # Both word orders and the whole `sollte` family. **"Man sollte" defeated the first version**, which
    # covered the plural and one singular order -- and the order it missed is the commonest German way to
    # give advice nobody asked for.
    r"sollt(?:e|en|est)\s+(?:sie|man|wir|du)|(?:sie|man|wir|du)\s+sollt(?:e|en|est)|"
    r"empfehl\w*|empfiehl\w*|ratsam|raten\s+(?:wir|ich)|"
    r"(?:sie|man)\s+m[uü]ss?ten|am\s+besten\s+w[aä]ere?"
    r")\b",
    re.IGNORECASE,
)

#: The refusal for a question of law, written here rather than generated. It does three things a disclaimer
#: cannot: it withholds the invented mechanism instead of qualifying it, it names the reframe that the corpus
#: CAN answer, and it points at the source that is actually binding.
#: Source labels that may answer a question of LAW. Everything else in the corpus describes the model.
#:
#: **This is what lets a legal question be answered at all, and it is deliberately a list rather than a
#: judgement.** Until 25 August 2026 such a question was refused before the model ran, because none of the
#: four sources was about rules. The fifth is, quoted from Merkblatt 2.03 and 3.04 of the Informationsstelle
#: AHV-IV. A legal question is now answered only where the verbatim check finds support in one of these --
#: the same machinery every other answer passes through, so nothing new is being trusted.
_LEGAL_SOURCES: frozenset[str] = frozenset({"AHV: Beiträge und flexibler Rentenbezug"})

#: Appended by code to every answer to a question of law. The Merkblätter are information sheets rather than
#: the law, and they say so themselves: for the individual case the Ausgleichskasse is binding. A source that
#: answers is not a source that decides.
_LEGAL_POINTER = (
    "Diese Antwort gibt die Merkblaetter 2.03 und 3.04 der Informationsstelle AHV-IV wieder, Stand "
    "1. Januar 2026. Verbindlich fuer Ihren Einzelfall ist die zustaendige Ausgleichskasse."
)

#: Markdown a quote carries out of a `.md` source. Stripped for DISPLAY only: the substring test runs on the
#: folded text either way, so nothing about verification changes. A quote shown with a blockquote marker and
#: asterisks around it is not the sentence as the document reads.
_MD_NOISE = re.compile(r"(?m)^\s*>\s?|\*\*|^#{1,6}\s+")


def _display(quote: str) -> str:
    """The quote as a reader should see it: the source's own words, without its markup."""
    return re.sub(r"\s{2,}", " ", _MD_NOISE.sub("", quote)).strip()

_LEGAL_REFUSAL = (
    "Das ist eine Rechtsfrage, und meine Quellen tragen dazu nichts, worauf sich eine Antwort stuetzen "
    "liesse. Zur AHV — Beitragspflicht, Vorbezug, Beitraege als nichterwerbstaetige Person — gibt es "
    "hier eine Quelle; zu allem anderen an Recht, Fristen und Bewilligungen nicht.\n\n"
    "Beantwortbar ist die Frage, wie das Modell rechnet. Formulieren Sie sie so -- etwa \u00abwie berechnet "
    "das Modell die AHV-Rente bei einem Vorbezug\u00bb --, dann arbeite ich aus den Stellen, die unten "
    "aufgefuehrt sind.\n\n"
    "Verbindlich fuer den Einzelfall ist immer die zustaendige Ausgleichskasse. Die Merkblaetter der AHV/IV "
    "sind die saubere Primaerquelle; was hier gerechnet wird, steht darunter und nicht daneben."
)


def is_legal_question(question: str) -> bool:
    """Whether this asks what the law requires rather than what the model computes."""
    low = " " + " ".join((question or "").lower().split()) + " "
    return any(re.search(r"\b" + re.escape(m), low) for m in _LEGAL_MARKERS)


def prescriptive_in(text: str) -> str:
    """The first instructing phrase in `text`, or an empty string."""
    m = _PRESCRIPTIVE_RE.search(text or "")
    return m.group(0).lower() if m else ""


@dataclass
class Citation:
    cite: str
    source: str
    score: float
    excerpt: str


@dataclass
class Claim:
    """One German sentence and the English sentence it was verified against.

    The pairing is the point. A claim without its quote is an assertion the reader has to trust; with it, the
    reader sees what the model was actually working from -- including, in the failure case, a quote about
    something else entirely.
    """
    text: str
    quote: str
    cite: str
    source: str
    #: The document this came from, as a reader would name it. Carried because provenance decides whether a
    #: legal question may be answered, and `source` is a filename rather than a document.
    work: str = ""


@dataclass
class Answer:
    text: str = ""
    model: str = ""
    citations: list[Citation] = field(default_factory=list)
    #: Figures in the reply that appear in no retrieved passage. Non-empty means do not show the text.
    unverified_numbers: list[str] = field(default_factory=list)
    #: The verified pairs behind `text`, in the order they are stated. Empty for a refusal.
    claims: list[Claim] = field(default_factory=list)
    #: Pairs the model produced whose quote could not be found in a passage it was given, kept for the count.
    #: Reported rather than hidden: a run that dropped four of five claims answered a different question from
    #: one that dropped none, and the reader is entitled to know which they are looking at.
    dropped: int = 0
    #: Why there is no answer, when there is none.
    refused: str = ""
    #: Which retrieval stage answered, so a caller can say so rather than implying more than happened.
    retrieval: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.unverified_numbers and not self.refused

    def to_dict(self) -> dict:
        return {
            "text": self.text, "model": self.model, "refused": self.refused,
            "retrieval": self.retrieval, "unverified_numbers": self.unverified_numbers,
            "ok": self.ok,
            "citations": [{"cite": c.cite, "source": c.source, "score": round(c.score, 3),
                           "excerpt": c.excerpt} for c in self.citations],
            "claims": [{"text": c.text, "quote": c.quote, "cite": c.cite, "source": c.source,
                        "work": c.work} for c in self.claims],
            "dropped": self.dropped,
        }


#: **The same model that answers, and the obvious optimisation was wrong on both axes.**
#:
#: A small model for a small task looks right: the translation never sees a passage and never writes an answer.
#: Measured on the four test questions, against the German compound that motivated the step at all:
#:
#:     qwen2.5:1.5b   "Capitalization?"                    1.4 s   wrong, and invents "for tax purposes"
#:     qwen2.5:3b     "Capitalization."                   17.7 s   wrong
#:     qwen2.5:14b    "What does Kapitalsättigung mean?"  43.3 s   does not translate the term
#:     apertus:8b     "What does capital saturation mean?" 0.6 s   correct
#:
#: The small models are slower AND wrong. Load time dominates a short generation, and `apertus:8b` is already
#: resident because it is the answering model — so reaching for a second model pays a cold start to get a worse
#: translation. A mistranslation is also invisible downstream: "Capitalization" retrieved passages scoring 0.585,
#: comfortably above the gate, about the wrong subject entirely.
TRANSLATE_MODEL = MODEL
TRANSLATE_TIMEOUT_S = 60

_INDEX: BI.Index | None = None


def _english(question: str) -> str:
    """An English rendering of the question, for the second retrieval pass. Empty string on any failure.

    The book is set in English and the questions arrive in German, and the embedding model handles that well
    except on compounds — see `bookindex.Index.search_multi` for the measurement. This is the cheap half of the
    fix: one small-model call, no passages involved, and a failure costs nothing because the German query is
    searched regardless.
    """
    if not re.search(r"[äöüßÄÖÜ]|\b(?:der|die|das|und|ist|wie|was|warum|wird|nicht)\b", question, re.I):
        return ""                                   # already English, or close enough
    payload = {
        "model": TRANSLATE_MODEL, "stream": False, "options": {"temperature": 0.0},
        "messages": [
            {"role": "system", "content": "Translate the user's question into English. "
                                          "Reply with the translation only, no preamble, no quotes."},
            {"role": "user", "content": question},
        ],
    }
    try:
        req = urllib.request.Request(
            OLLAMA + "/api/chat", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT_S) as r:
            d = json.loads(r.read().decode("utf-8"))
        out = (d.get("message", {}) or {}).get("content", "").strip().strip('"')
        return out if 3 < len(out) < 300 else ""
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return ""


def index() -> BI.Index | None:
    """The index, loaded once per process. Absent until `bookindex.py --build` has run."""
    global _INDEX
    if _INDEX is None:
        _INDEX = BI.load()
    return _INDEX


def _allowed_values(passages: list[BI.Passage]) -> set[float]:
    """Every number the model was actually given, in every reading of it.

    Same permissiveness as `prose.py`: German and Swiss number formatting is genuinely ambiguous, so a token is
    accepted if ANY reading of it matches. A false positive blocks a correct answer; an invented figure matches
    no reading of anything retrieved.

    **The citation labels count as given, and leaving them out blocked a correct answer.** The context labels
    each passage with its chapter and section — "31.4 The Flagship Case", "24.4.1 The Civilizational-Cycle
    Pattern" — so a model that refers to section 31.4 is quoting what it was handed. The first version drew
    only on the passage bodies and withheld a good reply over eight section numbers. A verifier that fails on
    the material it supplied is checking the wrong thing.
    """
    out: set[float] = set()
    for p in passages:
        for field in (p.text, p.cite):
            for tok in re.findall(_NUMBER_RE, field):
                out |= _readings(tok)
    # Small integers are prose rather than data: "drei Kapitalien", "zwei Grenzen", a chapter number.
    #
    # **This allowance is a deliberate trade and it costs real coverage, so it is stated rather than buried.**
    # Percentages live in this range, and a percentage is exactly where a fabricated figure would do damage: a
    # reply saying "10 bis 20 Prozent in Gold" passes unchecked. That one happens to be verbatim in §24.4 — but
    # the check did not establish it, and a reader must not believe otherwise.
    #
    # Tightening it would fire on every "die drei Kapitalien" and block correct answers constantly. The lesson
    # `prose.py` records applies here too: a false positive blocks a correct report, and a check nobody can
    # leave switched on protects nothing. The residual exposure is percentages and other small numbers, and it
    # is the reason this remains a draft for a reader who knows the material rather than a published answer.
    return out | set(float(n) for n in range(0, 101))


def _unverified(text: str, allowed: set[float]) -> list[str]:
    bad = []
    for tok in re.findall(_NUMBER_RE, text):
        readings = _readings(tok)
        if not readings:
            continue
        if not any(any(abs(r - a) <= max(0.01, abs(a) * 0.001) for a in allowed) for r in readings):
            bad.append(tok)
    return sorted(set(bad))


#: References to the internal passage numbering, which the reader never sees.
#:
#: **The prompt asks the model not to write these and the model writes them anyway**, in draft after draft. That
#: is the same lesson `prose.py` records about misattribution: an instruction a model ignores every time is a
#: preference, not a control. So the reference is removed afterwards, which is a property rather than a hope.
#: The citations are rendered separately from structured data, so nothing is lost by cutting the prose's own
#: attempt at them.
#: **Substituted, not deleted, and the first version deleted.** Cutting "Buchstelle 2 und 4" out of a sentence
#: leaves "Insbesondere die sind relevant" — grammatically broken text, which is a worse outcome than the
#: reference it removed. The reference is a noun phrase doing work in the sentence, so it is replaced by one
#: that reads the same way and means something to the reader.
_PASSAGE_REF = re.compile(
    r"\b(?:in\s+|aus\s+|laut\s+|gemäss\s+|gemaess\s+)?"
    r"(?:der\s+|die\s+|den\s+|dem\s+)?"
    r"Buchstellen?\s*\d+(?:\s*(?:,|und|bis|&|-|–|\s)\s*\d+)*",
    re.I)


#: Bracketed source headers the model sometimes echoes from the context format, on their own line.
_ECHOED_HEADER = re.compile(r"(?m)^\s*\[[^\]\n]{3,120}\]\s*$\n?")


def swiss_ss(text: str) -> str:
    """German eszett to Swiss double-s. **A house convention, enforced rather than requested.**

    Swiss orthography has no eszett: it is `Grösse`, `gemäss`, `Masse`. The model writes reichsdeutsch German
    because that is what it was trained on, and an instruction in the prompt gets it right most of the time --
    which is the same as getting it wrong unpredictably. So the prompt asks and this guarantees.

    A flat substitution is correct here. The only cases where it loses information are the handful of pairs
    German distinguishes by that character alone -- `Masse` against `Maße`, `Busse` against `Buße` -- and Swiss
    writing accepts the collision in exactly those words too. There is nothing to disambiguate, because the
    target orthography does not disambiguate.
    """
    return text.replace("ß", "ss").replace("ẞ", "SS")


def _strip_passage_refs(text: str) -> str:
    """Residual cleanup. Small on purpose: the numbering affordance is gone from the prompt, so this is
    catching leftovers rather than doing the work."""
    out = _ECHOED_HEADER.sub("", text)
    out = _PASSAGE_REF.sub("im Buch", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # **Rule 6 forbids bullets and the model uses them anyway.** Observed on a question about mandates: the
    # other eight instructions obeyed, the list one ignored. A prompt is a preference and this is the check.
    # The marker goes and the line stays, because what breaks the house style is the marker, not the clause.
    out = re.sub(r"(?m)^\s*[-*•–]\s+", "", out)
    out = re.sub(r"(?m)^\s*\d+[.)]\s+", "", out)
    # **Markdown emphasis leaks as literal asterisks.** The surface escapes the text before inserting it, as
    # it must -- a model's output is not trusted markup -- so `**Gain**` reaches the reader with its asterisks
    # showing. Converting to a tag would mean trusting the output; stripping keeps the word and drops the
    # markup, which is the only option that is both safe and readable.
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"(?<!\w)_([^_\n]{2,60})_(?!\w)", r"\1", out)
    out = re.sub(r"(?m)^#{1,6}\s+", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    # Last, so nothing downstream of it can reintroduce an eszett.
    return swiss_ss(out)


#: The task, in the user turn rather than the system prompt, because it is about THIS request's passages.
#:
#: **Measured at 9 of 9 verbatim before it was built.** The instruction not to copy the `[n]` marker is there
#: because the model copies it and the substring test then fails on a quote that was faithful; the marker is
#: also stripped on the way in, so both ends are covered.
_QUOTE_TASK = """Format, genau einzuhalten. Fuer jede Aussage zwei Zeilen:

BELEG: <ein Satz WOERTLICH aus einer Stelle kopiert, auf Englisch, ohne Auslassung, ohne die Nummer [n]>
AUSSAGE: <ein deutscher Satz, der genau diesen Beleg wiedergibt>

Hoechstens drei solche Paare, jedes nur einmal. Kein weiterer Text, keine Einleitung, kein Schluss.

Der BELEG muss Zeichen fuer Zeichen in einer Stelle vorkommen. Kuerze nicht, fasse nicht zusammen, korrigiere
nichts, uebersetze ihn nicht. Findest du keinen passenden Satz, schreibe nur: KEINE STELLE.

Die AUSSAGE darf nichts enthalten, was nicht im BELEG steht: keine Zahl, die dort nicht steht, keinen
Mechanismus, den er nicht nennt, keine Empfehlung. Wiederhole nicht die Frage."""

#: A quote is matched after folding what is transport and nothing else. The passage marker goes because the
#: model copies it; curly quotes and runs of whitespace go because the corpus and the model disagree about
#: them. Every further relaxation is somewhere a real alteration could hide, so there are none.
_MARKER_RE = re.compile(r"\[\d+\]")
#: Folded to their straight equivalents: the corpus and the model disagree about typography, and a curly
#: apostrophe is transport rather than content. One-to-one, so the index map stays aligned.
_QUOTE_CHARS = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}
#: Trimmed from both ends of a fold: the quotation marks a model wraps around the sentence it copied.
_TRIM_CHARS = "\"'\u00ab\u00bb"
_PAIR_RE = re.compile(r"BELEG:\s*(.+?)\s*\n\s*AUSSAGE:\s*(.+?)(?=\n\s*BELEG:|\Z)", re.S)
_NO_SOURCE = "keine stelle"

#: **A fragment is not evidence.** `quote in passage` is satisfied by "the PCP" or "at exactly 65", and a
#: three-word match licenses any claim the model cares to hang on it: the substring test would pass while
#: establishing nothing, which is the one way a threshold-free check can still be hollow.
#:
#: Measured in words rather than characters, after a forty-character floor rejected "At exactly 65 it pays
#: about 98 %" -- thirty-two characters and a perfectly good clause. Six words is the shortest span that
#: carries a subject and a claim; every quote in the compliance probe was a full sentence and cleared it
#: comfortably, so this rejects fragments rather than trimming real answers.
_MIN_QUOTE_WORDS = 6
_MIN_QUOTE_CHARS = 25


def _fold_map(text: str) -> tuple[str, list[int]]:
    """The folded text, and for each of its characters the index in `text` it came from.

    The map exists because of the one fold that is not one-to-one: a run of whitespace collapses to a single
    space, so a per-character walk loses its place and every quote ends up displayed in the folded form. With
    the map the substring test runs on folded text and the display reaches back to the original.
    """
    src = text or ""
    kept: list[tuple[str, int]] = []
    skip_to = 0
    for i, ch in enumerate(src):
        if i < skip_to:
            continue
        m = _MARKER_RE.match(src, i)
        if m:
            kept.append((" ", i))
            skip_to = m.end()
            continue
        kept.append((_QUOTE_CHARS.get(ch, ch), i))

    out: list[str] = []
    pos: list[int] = []
    prev_space = False
    for ch, i in kept:
        if ch.isspace():
            if prev_space:
                continue
            prev_space = True
            out.append(" ")
            pos.append(i)
            continue
        prev_space = False
        # `str.lower()` is one-to-one for everything in this corpus, but not universally -- a dotted capital I
        # lowercases to two characters. Mapping every one of them back to the same source index keeps the map
        # aligned instead of silently shifting from that point on.
        low = ch.lower()
        out.extend(low)
        pos.extend([i] * len(low))

    # Trim the ends: whitespace, then the quotation marks a model wraps around what it copied.
    lo, hi = 0, len(out)
    while lo < hi and (out[lo].isspace() or out[lo] in _TRIM_CHARS):
        lo += 1
    while hi > lo and (out[hi - 1].isspace() or out[hi - 1] in _TRIM_CHARS):
        hi -= 1
    return "".join(out[lo:hi]), pos[lo:hi]


def _fold(text: str) -> str:
    """Normalise a quote or a passage for the substring test."""
    return _fold_map(text)[0]


def verify_claims(raw: str, passages: list[BI.Passage]) -> tuple[list[Claim], int]:
    """The pairs whose quote is verbatim in a passage that was handed to the model, and how many were dropped.

    Four reasons a pair is dropped, all of them checks rather than preferences:

      - the quote is not in any passage: invented, altered, or assembled from two;
      - the quote is shorter than a clause: a three-word match is satisfied by anything and establishes
        nothing, so it is not accepted as a source;
      - the claim carries a figure its own quote does not: the number check, narrowed from the union of
        passages to the one sentence being relied on;
      - the claim instructs rather than explains: G7 reserves a recommendation for a named Curator;
      - the pair repeats a quote OR a claim already accepted: the model loops, and one claim shown under
        four verbatim quotes reads as four pieces of evidence for it.
    """
    folded = [(p, _fold(p.text)) for p in passages]
    out: list[Claim] = []
    dropped = 0
    seen: set[str] = set()
    claimed: set[str] = set()
    for beleg, aussage in _PAIR_RE.findall(raw or ""):
        quote, claim = _fold(beleg), _strip_passage_refs(aussage.strip())
        if (not quote or not claim or quote == _NO_SOURCE
                or len(quote) < _MIN_QUOTE_CHARS or len(quote.split()) < _MIN_QUOTE_WORDS):
            dropped += 1
            continue
        # **The same claim under four different quotes reads as four pieces of evidence for one assertion,
        # and that is what the model produced.** Asked why an owner-occupied home is excluded, it emitted one
        # German sentence four times, each paired with a different verbatim passage -- one of them about
        # mortgage risk. Deduplicating on the quote alone let all four through. Both sides are keys now: a
        # repeat of either is padding, and padding that survived a verbatim check looks like corroboration.
        if quote in seen or claim.lower() in claimed:
            continue
        home = next((p for p, hay in folded if quote in hay), None)
        if home is None or prescriptive_in(claim) or _unverified(claim, _allowed_values([home])):
            dropped += 1
            continue
        seen.add(quote)
        claimed.add(claim.lower())
        # The quote is returned as the passage spells it, not as it was folded: the reader is shown the
        # source, and lowercased text with its spacing collapsed is not the source.
        start = _fold(home.text).index(quote)  # located in the fold, displayed from the original
        out.append(Claim(text=claim, quote=_display(_span(home.text, start, len(quote))),
                         cite=home.cite, source=home.source, work=getattr(home, "work", "")))
    return out, dropped


def _span(original: str, start: int, length: int) -> str:
    """The folded match, located back in the original so the reader sees the corpus's own spelling.

    On any inconsistency this returns the folded text rather than guessing at an offset: a quote shown with
    collapsed spacing is a cosmetic loss, a quote shown with the wrong boundaries is a misquotation.
    """
    folded, pos = _fold_map(original)
    if start < 0 or start + length > len(pos):
        return folded[start:start + length]
    return original[pos[start]:pos[start + length - 1] + 1].strip()


def _generate(question: str, passages: list[BI.Passage]) -> tuple[str, str]:
    # **Labelled by chapter, not by number, and that is the fix rather than a preference.** The first version
    # numbered them — "[Buchstelle 1 — ...]" — and the model mirrored the format back, writing "wie in
    # Buchstelle 2 erläutert" to a reader who has no numbered list. Repairing that afterwards produced
    # "Im Buch wird dies im Buch erläutert". Removing the number removes the affordance: there is nothing to
    # cite by index, so a reference the model does make lands on the chapter, which is what a reader can use.
    ctx = "\n\n".join(f"[{p.cite}]\n{p.text}" for p in passages)
    payload = {
        "model": MODEL, "stream": False,
        # **Temperature zero, and a length cap, because the task is now copying rather than composing.**
        # 0.2 was right for a free synthesis and is wrong for this: the model must reproduce an English
        # sentence character for character, and any sampling at all is a chance to paraphrase it into
        # failing its own check. The cap is what the probe measured as sufficient for three pairs, and an
        # uncapped generation is how two live runs reached the 240 s timeout with nothing to show.
        "options": {"temperature": 0.0, "num_predict": 700},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",
             "content": f"STELLEN:\n\n{ctx}\n\n\n{_QUOTE_TASK}\n\n\nFRAGE: {question}"},
        ],
    }
    req = urllib.request.Request(
        OLLAMA + "/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        d = json.loads(r.read().decode("utf-8"))
    return (d.get("message", {}) or {}).get("content", "").strip(), d.get("model", MODEL)


def answer(question: str, *, k: int = K) -> Answer:
    """Answer one question from the book. Never takes a household: see the module docstring."""
    q = (question or "").strip()
    if len(q) < 4:
        return Answer(refused="Die Frage ist zu kurz, um etwas zu suchen.")

    idx = index()
    if idx is None:
        return Answer(refused="Der Wissensindex ist noch nicht gebaut. "
                              "Einmalig: python desktop/bookindex.py --build")

    queries = [q]
    en = _english(q)
    if en:
        queries.append(en)
    hits = idx.search_multi(queries, k=k)
    if not hits:
        return Answer(refused="Dazu findet sich in meinen Quellen nichts.",
                      retrieval="lexical" if not idx.model else "vector")

    stage = "vector" if idx.model and idx._vecs is not None else "lexical"
    best = max(s for _, s in hits)
    if stage == "vector":
        # The margin needs the whole distribution, not just the top k, so it is computed here rather than
        # returned by `search`: asking whether one passage STANDS OUT is a different question from which
        # passage is best, and only the first one distinguishes a real question from a general one.
        # The median is taken against the query that actually produced the best hit, so the margin compares
        # like with like: an English rendering shifts the whole distribution, not just the top.
        qv = BI.embed(queries[-1] if len(queries) > 1 else q, idx.model)
        margin = 0.0
        if qv is not None:
            allsc = sorted(sum(a * b for a, b in zip(qv, idx.vector(i)))
                           for i in range(len(idx.passages)))
            margin = best - allsc[len(allsc) // 2]
        if best < RELEVANCE_FLOOR or margin < MARGIN_FLOOR:
            return Answer(
                refused=("Dazu steht im Buch nichts, was diese Frage beantwortet. "
                         "Der Coach antwortet nur aus dem Buch und nicht aus allgemeinem Wissen."),
                retrieval=stage,
                citations=[Citation(p.cite, p.source, s, p.text[:220]) for p, s in hits[:2]])

    # **A question of law is refused here, before the model is asked.** The disclaimer-after version of this
    # guard was measured and failed: the model answered "muessen Sie in der Regel bis 65 weiter AHV einzahlen
    # ... die Quellen legen diese Regel fest", which no source does, and the pointer underneath made the
    # invention look reviewed. Retrieval genuinely found the AHV arithmetic at 0.61, so the passages look
    # relevant and do not answer; a model told they were selected as relevant will bridge that gap every time.
    # The citations still come back, so the reader sees the near-miss and can reframe.
    # What changed on 25 August 2026 is the corpus, not the tolerance: `knowledge/AHV_...md` quotes Merkblatt
    # 2.03 and 3.04. So the question is allowed through when retrieval found a passage from a source that is
    # about rules, and the verbatim check then decides whether anything can actually be said.
    legal = is_legal_question(q)
    if legal and not any(getattr(p, "work", "") in _LEGAL_SOURCES for p, _ in hits):
        return Answer(refused=_LEGAL_REFUSAL, retrieval=stage,
                      citations=[Citation(p.cite, p.source, sc, p.text[:220]) for p, sc in hits])

    passages = [p for p, _ in hits]
    try:
        text, model = _generate(q, passages)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return Answer(refused=f"Das lokale Modell ist nicht erreichbar ({exc}). "
                              f"Ollama muss auf 127.0.0.1:11434 laufen.", retrieval=stage)

    if not text:
        return Answer(refused="Das lokale Modell hat nichts zurueckgegeben.", retrieval=stage)

    claims, dropped = verify_claims(text, passages)
    if not claims:
        return Answer(
            refused=("Keine der Aussagen liess sich auf eine Stelle zurueckfuehren. Der Coach zeigt nur, was "
                     "woertlich in einer Quelle steht; hier hat das Modell nichts geliefert, was diesen Test "
                     "besteht. Die gefundenen Stellen stehen unten -- vielleicht traegt eine engere Frage."),
            model=model, retrieval=stage, dropped=dropped,
            citations=[Citation(p.cite, p.source, sc, p.text[:220]) for p, sc in hits])

    # `text` stays the German prose, so a surface that only knows about `text` is unchanged. The pairing lives
    # in `claims`, and a surface that shows it lets the reader check the derivation instead of trusting it.
    # `unverified_numbers` is deliberately left empty on this path, and that is a narrowing rather than a
    # gap: every figure was checked against the one sentence its claim rests on, and a claim that failed was
    # dropped rather than annotated. Running the old union-of-passages check over the survivors would pass by
    # construction. The field stays because callers read it and because a check that became redundant should
    # not silently disappear from the response shape.
    # **A legal question must rest on the legal source, not on a passage about the model that happens to share
    # its vocabulary.** That similarity is exactly what defeated the relevance gate, so the check is on
    # provenance rather than on score: at least one verified claim has to come from a source about rules.
    if legal and not any(c.work in _LEGAL_SOURCES for c in claims):
        return Answer(refused=_LEGAL_REFUSAL, model=model, retrieval=stage, dropped=dropped,
                      citations=[Citation(p.cite, p.source, sc, p.text[:220]) for p, sc in hits])

    # **A legal answer carries the pointer, always.** The Merkblätter are information sheets and say so
    # themselves; the Ausgleichskasse decides the individual case. Appended here rather than asked of the
    # model, because a pointer the model is told to produce is one it will sometimes omit — and the omission
    # lands on the answer where it mattered most.
    body = "\n\n".join(c.text for c in claims)
    if legal:
        body = body.rstrip() + "\n\n" + _LEGAL_POINTER

    used = {c.cite for c in claims}
    scores = {p.cite: sc for p, sc in hits}
    return Answer(
        text=body,
        model=model, retrieval=stage, claims=claims, dropped=dropped,
        citations=[Citation(p.cite, p.source, sc, p.text[:220]) for p, sc in hits if p.cite in used]
        or [Citation(c.cite, c.source, scores.get(c.cite, 0.0), c.quote[:220]) for c in claims],
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python desktop/coach.py <frage>", file=sys.stderr)
        return 2
    a = answer(" ".join(args))
    if a.refused:
        print(f"REFUSED: {a.refused}")
        return 1
    for c in a.claims:
        print(f"{c.text}\n    BELEG  {c.quote}\n    QUELLE {c.cite}\n")
    print(f"--- {a.model} · {a.retrieval} · "
          f"{len(a.claims)} belegt, {a.dropped} verworfen ---")
    if a.unverified_numbers:
        print(f"\n*** UNVERIFIED FIGURES, do not publish: {a.unverified_numbers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
