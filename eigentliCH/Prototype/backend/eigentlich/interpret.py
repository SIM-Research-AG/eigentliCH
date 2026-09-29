"""Reading what a member wrote, with the local model — and refusing to accept what it makes up.

A member types "Unabhängigkeit ab 2038 — Zürich" into one free-text box. That contains a goal name and a
target year, and asking for them as three separate fields would be three questions where one was enough.
So the model reads the sentence and proposes a structure.

**The proposal is never applied on its own.** It is returned as a suggestion with its provenance and is
shown back for confirmation. R-151 states the rule for extracted vault fields — "extraction never
overwrites a member-entered value" — and the same rule holds here for the same reason: a disagreement
between what someone said and what a model read is two facts, not one corrected one.

**Extractive, and checked.** Every value the model returns is verified to appear in the member's own text
before it is offered. A year the member did not write is discarded, not surfaced with low confidence. This
is the C-02 instinct applied to reading rather than to arithmetic: a number whose source cannot be shown
does not enter the system.

**It degrades.** No local model running means no suggestions and a form that works exactly as it did
before. R-302's rule for engines — "a failed engine renders as 'not available', never as a zero" — is the
right shape here too.

**It does not advise.** The model is given a member's own sentence and asked to segment it. It has no
route to a recommendation because it is never asked a question and its output is a typed record with no
prose field. C-01's enforcement point is `/api/know/ask` in phase 4; this is deliberately not that.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from . import llm

#: Years a goal could plausibly be dated to. Not a policy number and not an assumption under C-02: it is a
#: sanity bound on a parse, used only to discard a model that returned a page number as a year.
_PLAUSIBLE_YEARS = range(1900, 2200)


@dataclass(frozen=True)
class Suggestion:
    """One reading of one answer. Never authoritative."""

    field_name: str
    value: object
    #: The exact substring of the member's own text this came from. Empty means it was not verified and
    #: the suggestion is dropped before it reaches a caller.
    source_span: str
    model: str

    def as_dict(self) -> dict:
        return {
            "field": self.field_name,
            "value": self.value,
            "source_span": self.source_span,
            "model": self.model,
            # Named so no caller mistakes this for a decision. R-151's shape.
            "requires_confirmation": True,
        }


@dataclass
class Reading:
    text: str
    suggestions: list[Suggestion] = field(default_factory=list)
    #: True when the local model was not reachable. The caller shows the plain form, not an error.
    unavailable: bool = False

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "suggestions": [s.as_dict() for s in self.suggestions],
            "interpreted": not self.unavailable,
        }


_GOAL_SYSTEM = """Du liest einen einzelnen Satz, den ein Mensch über ein finanzielles Ziel geschrieben hat.

Deine einzige Aufgabe ist es, den Satz zu zerlegen. Du gibst NUR JSON zurück, mit genau diesen Feldern:

{"name": string|null, "target_year": number|null, "target_amount": number|null}

Regeln, die ausnahmslos gelten:
- Übernimm nur, was wörtlich dasteht. Erfinde nichts.
- Wenn kein Jahr genannt ist, ist target_year null. Rechne kein Jahr aus.
- Wenn kein Betrag genannt ist, ist target_amount null. Schätze keinen Betrag.
- "name" ist die Sache, um die es geht, in den Worten des Menschen.
- Gib keinen Rat, keine Bewertung, keine Empfehlung. Nur die Zerlegung.
"""

_GOAL_EXAMPLES = [
    (
        "Wohneigentum 2031, etwa 250'000 Eigenkapital",
        {"name": "Wohneigentum", "target_year": 2031, "target_amount": 250000},
    ),
    (
        "Unabhängigkeit ab 2038 — Zürich",
        {"name": "Unabhängigkeit", "target_year": 2038, "target_amount": None},
    ),
    (
        "Einfach mal den Standort bestimmen",
        {"name": "Einfach mal den Standort bestimmen", "target_year": None, "target_amount": None},
    ),
    (
        "Ausbildung der Kinder",
        {"name": "Ausbildung der Kinder", "target_year": None, "target_amount": None},
    ),
]


def _normalise(text: str) -> str:
    """Fold the ways a Swiss amount gets written, so verification compares like with like."""
    folded = unicodedata.normalize("NFKC", text)
    return folded.replace("’", "'").replace("′", "'").lower()


def _digits_in(text: str) -> set[str]:
    """Every run of digits in the text, with Swiss separators removed.

    "250'000" and "250 000" and "250000" are the same figure written three ways, and a verification that
    could not see that would discard correct readings.
    """
    compact = re.sub(r"[\s'’.]", "", _normalise(text))
    return set(re.findall(r"\d+", compact))


def _number_is_in_source(value: float | int, source: str) -> bool:
    digits = _digits_in(source)
    as_int = str(int(value))
    if as_int in digits:
        return True
    # A model may expand "250k" or "1 Mio" into a full figure. Accept only when the leading digits match
    # and the rest are zeros — enough to catch a real expansion, not enough to launder an invention.
    return any(d != "" and as_int.startswith(d) and set(as_int[len(d):]) <= {"0"} for d in digits)


def _text_is_in_source(value: str, source: str) -> bool:
    return _normalise(value).strip() in _normalise(source)


def interpret_goal(text: str, *, model: str | None = None) -> Reading:
    """Read a free-text goal into {name, target_year, target_amount}.

    Returns a `Reading` whose suggestions are all verified against `text`. An empty suggestion list is a
    normal outcome and means the sentence did not carry anything extractable.
    """
    reading = Reading(text=text)
    if not text or not text.strip():
        return reading

    shots = "\n".join(
        f"Eingabe: {example}\nAusgabe: {json.dumps(expected, ensure_ascii=False)}"
        for example, expected in _GOAL_EXAMPLES
    )
    prompt = f"{shots}\nEingabe: {text}\nAusgabe:"

    try:
        reply = llm.chat(
            prompt,
            system=_GOAL_SYSTEM,
            json_mode=True,
            model=model or llm.DEFAULT_MODEL,
        )
    except llm.LocalModelUnavailable:
        reading.unavailable = True
        return reading

    try:
        parsed = json.loads(reply.text)
    except json.JSONDecodeError:
        # A model that did not return JSON has not read anything. Nothing is guessed from prose.
        return reading
    if not isinstance(parsed, dict):
        return reading

    name = parsed.get("name")
    if isinstance(name, str) and name.strip() and _text_is_in_source(name, text):
        reading.suggestions.append(
            Suggestion("name", name.strip(), name.strip(), reply.model)
        )

    for key, field_name in (("target_year", "target_year"), ("target_amount", "target_amount")):
        value = parsed.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if key == "target_year" and int(value) not in _PLAUSIBLE_YEARS:
            continue
        if not _number_is_in_source(value, text):
            # The single most important line in this module. A year or an amount the member did not write
            # is discarded outright rather than offered with a caveat.
            continue
        reading.suggestions.append(
            Suggestion(field_name, int(value), str(int(value)), reply.model)
        )

    return reading


def suggestions_for(question_key: str, value: object, *, model: str | None = None) -> dict:
    """Dispatch by question. Unknown questions get no interpretation rather than a generic one."""
    if question_key == "first_goal" and isinstance(value, str):
        return interpret_goal(value, model=model).as_dict()
    return Reading(text=str(value) if value is not None else "").as_dict()
