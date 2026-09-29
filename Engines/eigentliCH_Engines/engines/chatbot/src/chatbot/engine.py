"""The pure core: the prompt, reading the model's reply, the number check and the text repairs.

No I/O, no HTTP, no clock. ``service.py`` calls these and the model; nothing here calls out.

**The model composes words and does no arithmetic** (prior art ``compose.py``, A175). It is handed the
grounding the caller chose, and the client facts only when the question is about the client, and it is
asked for a small JSON object: a status (answer, or one of the two refusals), the part of the answer drawn
from the notes, the part drawn from general knowledge, and the note ids it used. The code, not the model,
marks the general part for the reader (CHB-18).
Everything a reader could mistake for checked is then checked here:

* every number in the answer is looked up in the sources it was allowed to use (the grounding texts, the
  numeric client facts, the question itself); a number that matches none is listed in
  ``unverified_numbers``. This catches *fabrication*. It does not catch *misattribution*, a correct
  figure under the wrong label (``desktop/prose.py`` measured exactly that), which is why the answer is
  model-derived output and says so;
* the cited ids are kept only where they name a note that was given;
* a reply that leaves the language (another script) is redrafted, and German is written the Swiss way
  (``ss``, never ``ß``) with the polite form repaired where a word swap can repair it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional, Sequence

from .contracts import Calibration, ChatRequest, CheckedNumber, Turn


class EngineError(ValueError):
    """The inputs cannot be answered as given. The message says why."""


class ReplyError(ValueError):
    """The model's reply is not the object it was asked for."""


def content_id(prefix: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return f"{prefix}-{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# The prompt. A change to any text here is a new PROMPT_VERSION; its hash enters the idempotency key.
# ---------------------------------------------------------------------------

PROMPT_VERSION = "chatbot-prompt@1.2.0"

#: ``{assistant}`` is the configured display name (``model.display_name``, CHB-21); it enters the prompt hash.
SYSTEM = {
    "de": (
        "Sie sind {assistant}, die KI von eigentliCH, einer Schweizer Finanzplanungsanwendung. Sie beantworten "
        "die Frage einer Kundin oder eines Kunden, in zwei Teilen:\n"
        "from_notes: was die nummerierten UNTERLAGEN unten zur Frage sagen, nur aus den UNTERLAGEN und den "
        "KUNDENANGABEN. Gibt es keine UNTERLAGEN oder sagen sie zur Frage nichts, bleibt from_notes leer.\n"
        "general: was die UNTERLAGEN nicht abdecken, beantworten Sie aus Ihrem allgemeinen Wissen, praktisch und "
        "konkret, mit Schritten, die die Kundin oder der Kunde selbst gehen kann. Betrifft die Frage die eigene "
        "Situation, gehen Sie auf die KUNDENANGABEN ein. Ist die Frage mit from_notes ganz beantwortet, bleibt "
        "general leer.\n"
        "\n"
        "Regeln ohne Ausnahme:\n"
        "1. RECHNEN SIE NICHT. Übernehmen Sie jede Zahl genau so, wie sie in den UNTERLAGEN, den KUNDENANGABEN "
        "oder der Frage steht. Keine Summen, keine Differenzen, keine Prozentsätze, keine Umrechnung.\n"
        "2. Nennen Sie keine Zahl, die nicht in den UNTERLAGEN, den KUNDENANGABEN oder der Frage steht, auch "
        "nicht im Teil general. Nennen Sie nie eine Zahl zur Situation der Kundin oder des Kunden (Einkommen, "
        "Vermögen, Alter, Beträge), die nicht unter KUNDENANGABEN oder in der Frage steht.\n"
        "3. Keine Empfehlung bestimmter Finanzprodukte, Wertpapiere oder Anbieter und keine Anlageberatung. "
        "Konkrete Schritte, die die Kundin oder der Kunde selbst gehen kann, sind erwünscht.\n"
        "4. status ist \"answer\" für jede Frage aus dem Bereich von eigentliCH: persönliche Finanzen (Geld, "
        "Budget, Sparen, Schulden, Anlegen), Arbeit, Beruf und Einkommen, Vorsorge und Renten (AHV, "
        "Pensionskasse, Säule 3a), Versicherungen, Steuern, Wohnen und Wohneigentum, das Recht rund um Familie, "
        "Ehe, Erbe und Urteilsunfähigkeit (etwa Erbrecht, Pflichtteil, Erbvorbezug, Testament, Vorsorgeauftrag, "
        "Patientenverfügung), Pflege und Betreuung von Angehörigen und ihre Kosten (etwa Betreuungsgutschriften, "
        "Entlastung, Pflegeheim), Gesundheit, soweit sie Arbeit, Einkommen und Geld betrifft, die Wirtschaft und "
        "eigentliCH selbst. Persönliche Fragen zu diesen Bereichen gehören immer dazu. Dass die UNTERLAGEN eine "
        "Frage nicht abdecken, macht sie nie zu \"out_of_domain\": dann antworten Sie im Teil general. "
        "\"out_of_domain\" nur, wenn die Frage mit keinem dieser Bereiche etwas zu tun hat (etwa ein Kochrezept, "
        "ein Sportergebnis, Programmierhilfe, eine medizinische Diagnose). \"unintelligible\" nur, wenn die "
        "Frage nicht zu verstehen ist. In diesen beiden Fällen bleiben from_notes und general leer.\n"
        "5. Siezen Sie durchgehend. Schreiben Sie Schweizer Rechtschreibung (ss statt ß).\n"
        "6. Höchstens 250 Wörter in beiden Teilen zusammen, Fliesstext. Keine Überschriften, keine Tabellen, "
        "keine Aufzählungszeichen, keine Emoji, keine Quellenmarken im Text. Schritte in Sätzen (Erstens, "
        "Zweitens). Keine eigene Kennzeichnung wie \"Allgemein gilt\": die Anwendung kennzeichnet den Teil "
        "general selbst.\n"
        "7. In cited stehen die Kennungen (etwa N1) der Unterlagen, auf die sich from_notes stützt; leer, wenn "
        "from_notes leer ist.\n"
        "Antworten Sie nur mit dem JSON-Objekt {{\"status\": ..., \"from_notes\": ..., \"general\": ..., "
        "\"cited\": [...]}}."
    ),
    "en": (
        "You are {assistant}, the AI of eigentliCH, a Swiss financial planning application. You answer a "
        "client's question, in two parts:\n"
        "from_notes: what the numbered NOTES below say about the question, solely from the NOTES and the CLIENT "
        "FACTS. If there are no NOTES or they say nothing about the question, from_notes stays empty.\n"
        "general: what the NOTES do not cover, you answer from your general knowledge, practically and "
        "concretely, with steps the client can take themselves. Where the question is about the client's own "
        "situation, take the CLIENT FACTS into account. If from_notes answers the question fully, general stays "
        "empty.\n"
        "\n"
        "Rules without exception:\n"
        "1. DO NOT CALCULATE. Copy every number exactly as it stands in the NOTES, the CLIENT FACTS or the "
        "question. No sums, no differences, no percentages, no conversions.\n"
        "2. State no number that is not in the NOTES, the CLIENT FACTS or the question, in the general part "
        "neither. Never state a number about the client's situation (income, wealth, age, amounts) that is not "
        "under CLIENT FACTS or in the question.\n"
        "3. No recommendation of particular financial products, securities or providers, and no investment "
        "advice. Concrete steps the client can take themselves are wanted.\n"
        "4. status is \"answer\" for every question within eigentliCH's domain: personal finances (money, "
        "budget, saving, debt, investing), work, career and income, pensions and retirement (AHV, pension fund, "
        "pillar 3a), insurance, taxes, housing and home ownership, the law around family, marriage, estate and "
        "incapacity (such as inheritance law, compulsory shares, advances on inheritance, wills, advance care "
        "directives, patient decrees), care for relatives and its costs (such as care credits, respite care, "
        "nursing homes), health as it bears on work, income and money, the economy and eigentliCH itself. "
        "Personal questions in these areas always belong here. That the NOTES do not cover a question never "
        "makes it \"out_of_domain\": answer it in the general part. \"out_of_domain\" only when the question "
        "has nothing to do with any of these areas (such as a recipe, a sports result, programming help, a "
        "medical diagnosis). \"unintelligible\" only when the question cannot be understood. In both cases "
        "from_notes and general stay empty.\n"
        "5. British spelling. Address the client as \"you\".\n"
        "6. At most 250 words in both parts together, plain prose. No headings, no tables, no bullet marks, no "
        "emoji, no citation marks in the text. Steps in sentences (First, Second). No marking of your own such "
        "as \"In general\": the application marks the general part itself.\n"
        "7. cited holds the ids (such as N1) of the notes from_notes rests on; empty when from_notes is empty.\n"
        "Reply with the JSON object {{\"status\": ..., \"from_notes\": ..., \"general\": ..., \"cited\": [...]}} "
        "only."
    ),
}

HEADINGS = {
    "de": {"notes": "UNTERLAGEN", "facts": "KUNDENANGABEN", "question": "FRAGE", "none": "keine"},
    "en": {"notes": "NOTES", "facts": "CLIENT FACTS", "question": "QUESTION", "none": "none"},
}

RETRY_LANGUAGE = {
    "de": "Die Antwort muss vollständig auf Deutsch sein, von der ersten bis zur letzten Silbe.",
    "en": "The answer must be entirely in English, from the first word to the last.",
}

STATUSES = ("answer", "out_of_domain", "unintelligible")

#: The object the model returns, enforced by vLLM's guided decoding (``response_format: json_schema``).
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "from_notes": {"type": "string"},
        "general": {"type": "string"},
        "cited": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "from_notes", "general", "cited"],
    "additionalProperties": False,
}


def response_format() -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "chat_answer", "strict": True, "schema": RESPONSE_SCHEMA}}


def system_prompt(language: str, assistant: str) -> str:
    return SYSTEM[language].format(assistant=assistant)


def prompt_hash(assistant: str = "MiniMind") -> str:
    """Hash of every text and structure that shapes the prompt, the display name included: part of the
    idempotency key."""
    return content_id("PRM", {"version": PROMPT_VERSION, "system": SYSTEM, "headings": HEADINGS,
                              "retry": RETRY_LANGUAGE, "schema": RESPONSE_SCHEMA, "assistant": assistant})


def intelligible(question: str) -> bool:
    """Whether a question has any word in it: at least two letters in a row. A question without one (``???``,
    ``123``) is refused without a model call (CHB-19); every other judgement of intelligibility is the model's."""
    return re.search(r"[^\W\d_]{2,}", question) is not None


# ---------------------------------------------------------------------------
# Routing: is the question about the client? (CHB-08)
# ---------------------------------------------------------------------------

def client_markers(question: str, language: str, cal: Calibration) -> list[str]:
    """The markers in ``question`` that make it about the client. Empty means a question about the world.

    A data-protection rule, not a compliance gate (prior art ``boundary.asks_about_the_member``): the client
    facts reach the prompt only for a question about the client. Deliberately generous: misreading a
    question as personal costs an unneeded fact in the prompt, the other way round costs the client an
    answer about their own situation.
    """
    patterns = cal.client_markers.get(language, ())
    return [p for p in patterns if re.search(p, question, flags=re.IGNORECASE)]


# ---------------------------------------------------------------------------
# Building the messages
# ---------------------------------------------------------------------------

def check_limits(request: ChatRequest, cal: Calibration) -> None:
    """Refuse a request over the calibration's limits. Never truncated silently: a cut note is a different
    note, and the answer would cite text the model never saw."""
    lim = cal.limits
    if len(request.grounding) > lim.max_notes:
        raise EngineError(f"{len(request.grounding)} grounding notes, at most {lim.max_notes} are accepted")
    for note in request.grounding:
        if len(note.text) > lim.max_chars_per_note:
            raise EngineError(f"grounding note {note.id} has {len(note.text)} characters, at most "
                              f"{lim.max_chars_per_note} are accepted")
    total = sum(len(n.text) + len(n.title) for n in request.grounding)
    if total > lim.max_total_chars:
        raise EngineError(f"the grounding has {total} characters, at most {lim.max_total_chars} are accepted")
    if len(request.client_facts) > lim.max_client_facts:
        raise EngineError(f"{len(request.client_facts)} client facts, at most {lim.max_client_facts} are accepted")


def recent_history(history: Sequence[Turn], cal: Calibration) -> list[Turn]:
    lim = cal.limits
    if lim.max_turns == 0:
        return []
    turns = list(history)[-lim.max_turns:]
    for t in turns:
        if len(t.content) > lim.max_chars_per_turn:
            raise EngineError(f"a previous turn has {len(t.content)} characters, at most {lim.max_chars_per_turn} "
                              "are accepted")
    return turns


def _fact_value(value: Any) -> str:
    if isinstance(value, float):
        return repr(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


def build_messages(request: ChatRequest, cal: Calibration, *, use_client_facts: bool,
                   retry_language: bool = False, assistant: str = "MiniMind") -> list[dict[str, str]]:
    lang = request.language
    h = HEADINGS[lang]
    lines = [f"{h['notes']}:"]
    for note in request.grounding:
        lines.append(f"[{note.id}] {note.title} ({note.source_label})")
        lines.append(note.text.strip())
        lines.append("")
    if not request.grounding:
        lines.append(h["none"])
        lines.append("")
    if use_client_facts and request.client_facts:
        lines.append(f"{h['facts']}:")
        for fact in request.client_facts:
            lines.append(f"- {fact.label}: {_fact_value(fact.value)}")
        lines.append("")
    lines.append(f"{h['question']}:")
    lines.append(request.question.strip())
    if retry_language:
        lines.append("")
        lines.append(RETRY_LANGUAGE[lang])
    messages = [{"role": "system", "content": system_prompt(lang, assistant)}]
    for turn in recent_history(request.history, cal):
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": "\n".join(lines).strip()})
    return messages


# ---------------------------------------------------------------------------
# Reading the reply
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reply:
    status: str
    from_notes: str
    general: str
    cited: tuple[str, ...]


def parse_reply(text: str) -> Reply:
    """The model's JSON object. Guided decoding makes it the norm; a fenced or prefixed object is still read,
    anything else is a :class:`ReplyError`."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ReplyError("the reply holds no JSON object")
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError as exc:
        raise ReplyError(f"the reply is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ReplyError("the reply is not a JSON object")
    status, notes, general = data.get("status"), data.get("from_notes"), data.get("general")
    cited = data.get("cited", [])
    if status not in STATUSES:
        raise ReplyError(f"status is not one of {list(STATUSES)}")
    if not isinstance(notes, str) or not isinstance(general, str):
        raise ReplyError("from_notes and general must be strings")
    if not isinstance(cited, list) or not all(isinstance(c, str) for c in cited):
        raise ReplyError("cited is not a list of strings")
    if status == "answer" and not (notes.strip() or general.strip()):
        raise ReplyError("status is answer and both parts are empty")
    return Reply(status=status, from_notes=notes.strip(), general=general.strip(),
                 cited=tuple(c.strip() for c in cited))


@dataclass(frozen=True)
class Composed:
    """The answer a reader sees, assembled by the code from the model's two parts (CHB-18)."""

    text: str
    basis: str
    cited: tuple[str, ...]
    warnings: tuple[str, ...]


def compose(reply: Reply, language: str, known: Sequence[str], label: str) -> Composed:
    """The reader's text: the part from the notes, then the part from general knowledge under the fixed
    marking ``label``. The marking is the code's, never the model's, so a general statement cannot pass as
    one from the notes. A part "from the notes" that cites no given note is not from the notes: it is shown
    as general. Both parts are repaired and their citation marks removed before the number check."""
    warnings: list[str] = []
    notes_text, repairs = repair(reply.from_notes, language) if reply.from_notes else ("", [])
    warnings.extend(repairs)
    notes_text, cited, cite_warnings = take_citations(notes_text, reply.cited, known)
    warnings.extend(cite_warnings)
    general_text, repairs = repair(reply.general, language) if reply.general else ("", [])
    warnings.extend(r for r in repairs if r not in warnings)
    general_text, general_cited, _ = take_citations(general_text, (), known)
    if general_cited:
        warnings.append("citation marks in the general part removed; the general part cites no note")
    if notes_text and not cited:
        warnings.append("the part the model gave as from the notes cites no given note; it is shown as a "
                        "general assessment")
        general_text = (notes_text + " " + general_text).strip()
        notes_text = ""
    if not notes_text:
        cited = ()
    basis = "mixed" if notes_text and general_text else "grounded" if notes_text else "general"
    parts = [notes_text] if notes_text else []
    if general_text:
        parts.append(f"{label}\n{general_text}")
    return Composed(text="\n\n".join(parts), basis=basis, cited=cited, warnings=tuple(dict.fromkeys(warnings)))


def take_citations(answer: str, cited: Iterable[str], known: Sequence[str]) -> tuple[str, tuple[str, ...], list[str]]:
    """Remove inline ``[id]`` marks of known notes from the text (their digits would be read as figures),
    merge them into the citations, and drop cited ids that name no given note."""
    known_set = set(known)
    order: list[str] = [c for c in cited]
    warnings: list[str] = []

    def strip(match: re.Match[str]) -> str:
        inner = [p.strip() for p in match.group(1).split(",")]
        if inner and all(p in known_set for p in inner):
            order.extend(inner)
            return ""
        return match.group(0)

    text = re.sub(r"\s*\[([A-Za-z0-9_.:\-, ]{1,120})\]", strip, answer)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text).strip()
    kept: list[str] = []
    for c in order:
        if c in known_set:
            if c not in kept:
                kept.append(c)
        else:
            warnings.append(f"the model cited {c!r}, which is not among the grounding notes; dropped")
    return text, tuple(kept), list(dict.fromkeys(warnings))


# ---------------------------------------------------------------------------
# Text repairs
# ---------------------------------------------------------------------------

#: Scripts neither German nor English uses: CJK, kana, Hangul, Cyrillic, Arabic, Hebrew, Devanagari.
_FOREIGN_SCRIPT = ((0x4E00, 0x9FFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF), (0x0400, 0x04FF),
                   (0x0600, 0x06FF), (0x0590, 0x05FF), (0x0900, 0x097F))


def drifted(text: str) -> int:
    """Characters in a script the answer's language does not use. Zero for every correct answer."""
    return sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _FOREIGN_SCRIPT))


#: du-forms a word swap can repair (prior art ``compose.siezen``). ``du`` itself governs the verb and is
#: only counted.
_SIEZEN = {"deine": "Ihre", "deiner": "Ihrer", "deinen": "Ihren", "deinem": "Ihrem", "deines": "Ihres",
           "dein": "Ihr", "dich": "Sie", "dir": "Ihnen"}
_SIEZEN_RE = re.compile(r"\b(" + "|".join(sorted(_SIEZEN, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def repair(text: str, language: str) -> tuple[str, list[str]]:
    """Plain prose in the house orthography. Removes presentation, never a word, so a figure that was
    traceable before is traceable after."""
    notes: list[str] = []
    out = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    out = re.sub(r"^\s{0,4}[-*+•]\s+", "", out, flags=re.M)
    stripped = out.replace("**", "").replace("__", "")
    if stripped != text:
        notes.append("formatting removed from the model's text")
    out = stripped
    if language == "de":
        if "ß" in out:
            out = out.replace("ß", "ss")
            notes.append("ß written as ss (Swiss orthography)")
        count = 0

        def swap(m: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return _SIEZEN[m.group(0).lower()]

        out = _SIEZEN_RE.sub(swap, out)
        if count:
            notes.append(f"{count} informal form(s) replaced by the polite form")
        if re.search(r"\bdu\b", out, re.IGNORECASE):
            notes.append("the answer still uses the informal 'du'")
    return out.strip(), notes


# ---------------------------------------------------------------------------
# The number check (CHB-07)
# ---------------------------------------------------------------------------

#: A date as prose writes it. Matched before numbers, so ``28.09.2026`` is one date and not three figures.
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")

#: A number as Swiss, German and English prose writes it. Space thousands only in groups of three, so a
#: list "400.000, 83 %" is two tokens (prior art ``desktop/prose.py``).
_NUMBER = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,2})?(?!\d)|\d+(?:[.,'’]\d+)*")

#: A scale word after a number: "1,6 Millionen" is 1 600 000.
_SCALE = re.compile(r"\s*(Mrd\.?|Milliarden?|billion|Mio\.?|Millionen|Million|million|Tausend|thousand)(?![A-Za-z])",
                    re.IGNORECASE)
_SCALE_FACTOR = {"mrd": 1e9, "milliarde": 1e9, "milliarden": 1e9, "billion": 1e9, "mio": 1e6,
                 "millionen": 1e6, "million": 1e6, "tausend": 1e3, "thousand": 1e3}

#: A percentage marker after a number.
_PERCENT = re.compile(r"\s*(%|Prozent\b|percent\b|per cent\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Token:
    text: str
    #: The readings of the digits as written, before any scale word.
    readings: frozenset[float]
    digits: int
    #: 1, or the factor of the scale word that follows ("Millionen": 1e6).
    scale: float = 1.0
    #: A percent sign or word follows.
    percent: bool = False
    date: Optional[str] = None


def readings(token: str) -> set[float]:
    """Every plausible numeric reading of one token: German and Swiss formatting are ambiguous
    (``400.000`` is four hundred thousand in German and four tenths in English), so all are generated and a
    figure is accepted if any reading matches."""
    t = token.strip()
    for ch in ("'", "’", " ", " ", " "):
        t = t.replace(ch, "")
    t = t.strip(".,")
    out: set[float] = set()
    if not t:
        return out
    for variant in (t, t.replace(",", "."), t.replace(".", "").replace(",", "."),
                    t.replace(",", "").replace(".", ""), t.replace(",", "")):
        try:
            value = float(variant)
        except ValueError:
            continue
        if math.isfinite(value):
            out.add(value)
    return out


def tokens(text: str) -> list[Token]:
    out: list[Token] = []
    spans: list[tuple[int, int]] = []
    for m in _DATE.finditer(text):
        if m.group(1):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
        out.append(Token(text=m.group(0), readings=frozenset(), digits=8, date=f"{y:04d}-{mo:02d}-{d:02d}"))
        spans.append(m.span())
    masked = list(text)
    for a, b in spans:
        masked[a:b] = " " * (b - a)
    rest = "".join(masked)
    for m in _NUMBER.finditer(rest):
        raw = m.group(0)
        values = readings(raw)
        if not values:
            continue
        scale = _SCALE.match(rest, m.end())
        factor = _SCALE_FACTOR[scale.group(1).rstrip(".").lower()] if scale else 1.0
        percent = bool(_PERCENT.match(rest, m.end()))
        out.append(Token(text=raw.strip(), readings=frozenset(values), digits=sum(c.isdigit() for c in raw),
                         scale=factor, percent=percent))
    return out


def _rounded(f: float, decimals: Sequence[int]) -> set[float]:
    """``f`` and its roundings, half up as prose rounds (12.5 is 13) and half even as Python does."""
    out = {f}
    for d in decimals:
        out.add(round(f, d))
        out.add(float(Decimal(repr(f)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)))
    return out


def _close(a: float, b: float, tol: float) -> bool:
    return a == b or abs(a - b) <= tol * max(abs(a), abs(b))


def matches(tok: Token, value: float, decimals: Sequence[int], tol: float) -> bool:
    """Whether ``tok`` in an answer is a legitimate rendering of the source ``value``.

    The renderings are enumerated, never tolerated (CHB-07): the value itself or rounded to one of
    ``decimals``; in thousands, millions or billions only when the answer writes the scale word
    ("1,6 Millionen" for 1 612 000); as a percentage only when the answer writes a percent sign and the value
    is a share ("12,5 %" for 0.125). A bare "10" is therefore not 9 500 000, and "13" is not 0.13.
    """
    v = abs(float(value))
    targets = [v / tok.scale] if tok.scale > 1 else [v]
    if tok.percent and v <= 1.0:
        targets.append(100.0 * v)
    candidates: set[float] = set()
    for t in targets:
        candidates |= _rounded(t, decimals)
    return any(_close(abs(r), c, tol) for r in tok.readings for c in candidates)


@dataclass(frozen=True)
class Sources:
    """What an answer may quote: values and dates, each with the source ids it came from."""

    values: tuple[tuple[float, str], ...]
    dates: tuple[tuple[str, str], ...]


def sources_for(request: ChatRequest, cal: Calibration, *, use_client_facts: bool,
                history: Sequence[Turn]) -> Sources:
    values: list[tuple[float, str]] = []
    dates: list[tuple[str, str]] = []

    def from_text(text: str, source: str) -> None:
        for tok in tokens(text):
            if tok.date:
                dates.append((tok.date, source))
                continue
            for r in tok.readings:
                values.append((abs(r) * tok.scale, source))
                if tok.scale > 1:
                    values.append((abs(r), source))
                if tok.percent:
                    values.append((abs(r) / 100.0, source))

    for note in request.grounding:
        from_text(note.title + "\n" + note.text, note.id)
    if use_client_facts:
        for fact in request.client_facts:
            if isinstance(fact.value, float):
                values.append((abs(fact.value), f"fact:{fact.key}"))
            else:
                from_text(str(fact.value), f"fact:{fact.key}")
    from_text(request.question, "question")
    for turn in history:
        if turn.role == "user":
            from_text(turn.content, "history")
    return Sources(values=tuple(dict.fromkeys(values)), dates=tuple(dict.fromkeys(dates)))


def check_numbers(answer: str, sources: Sources, cal: Calibration) -> tuple[tuple[CheckedNumber, ...], tuple[str, ...]]:
    """Every number in ``answer`` with the sources it matches, and the ones that match nothing."""
    nc = cal.number_check
    checked: list[CheckedNumber] = []
    for tok in tokens(answer):
        if tok.date:
            matched = tuple(dict.fromkeys(s for d, s in sources.dates if d == tok.date))
        else:
            if tok.digits < nc.min_checked_digits:
                continue
            matched = tuple(dict.fromkeys(s for v, s in sources.values
                                          if matches(tok, v, nc.rounding_decimals, nc.relative_tolerance)))
        checked.append(CheckedNumber(text=tok.text, matched=matched))
    unverified = tuple(dict.fromkeys(n.text for n in checked if not n.matched))
    return tuple(checked), unverified
