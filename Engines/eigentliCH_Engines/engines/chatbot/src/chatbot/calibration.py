"""Calibration: generation parameters, limits, the number check, the client markers and the fixed texts.

``1.0.0``
    The first production set. Temperature 0 with a fixed seed: this is description from sources, not
    composition, and a creative model invents figures (prior art ``desktop/prose.py``). 900 tokens of
    output: the answer is at most about 200 words inside a small JSON object, and gemma 4 on vLLM has no
    reasoning preamble (measured on spark7, 28.09.2026: a 20-word answer in 0.3 s). Two drafts, because
    leaving the language or breaking the schema is occasional and a second draw usually fixes it.
    Numbers of one digit are not checked (``Säule 3a``, ``1. Säule``), as in ``know.py``
    (``MINIMUM_CHECKED_DIGITS = 2``). The client markers are the first-person markers of
    ``boundary.asks_about_the_member`` for German and English.

``1.1.0`` (29.09.2026, the owner: "we must be able to answer such questions")
    No refusal for lack of grounding (CHB-18). A question the notes do not cover, or one sent without notes,
    is answered from general knowledge and marked as such by a fixed line (``general.label``); refused are
    only a question outside the system's domain and one that cannot be understood (CHB-19), each with a fixed
    text. 1 200 output tokens instead of 900: an answer may now be 250 words of practical steps, in two parts
    inside the JSON object, and a German answer of that length is about 450 tokens. Everything else as
    1.0.0. The client whose question triggered it asked "was muss ich machen so dass ich eine persönliche
    Wachstumsstrategie habe, also mehr einkommen generieren kann" and received a refusal.

A seed can never be changed in place. To change a value, propose a new version through ``PUT /calibration``;
the store refuses a second, different payload under a used version.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Calibration, GeneralTexts, Generation, Limits, NumberCheck, Texts

PRODUCTION = Calibration(
    version="1.0.0",
    note=("First production set: temperature 0, seed 7, 900 output tokens, two drafts; numbers of two or "
          "more digits checked against the grounding, the client facts and the question."),
    generation=Generation(max_tokens=900, temperature=0.0, seed=7, attempts=2),
    limits=Limits(max_notes=12, max_chars_per_note=6000, max_total_chars=40000, max_client_facts=40,
                  max_turns=6, max_chars_per_turn=2000),
    number_check=NumberCheck(min_checked_digits=2, rounding_decimals=(0, 1, 2), relative_tolerance=1e-9),
    client_markers={
        "de": (r"\bich\b", r"\b(?:mir|mich)\b", r"\bmein(?:e|em|en|er|es)?\b", r"\bwir\b",
               r"\buns(?:er|ere|erem|eren|erer|eres)?\b"),
        "en": (r"\bi\b", r"\b(?:me|my|mine|we|us|our|ours)\b"),
    },
    texts={
        "de": Texts(
            no_grounding=("Zu dieser Frage liegen keine freigegebenen Unterlagen vor, deshalb gibt es hier keine "
                          "Antwort. Eine Beraterin oder ein Berater kann die Frage beantworten."),
            not_covered=("Die freigegebenen Unterlagen zu dieser Frage decken sie nicht ab, deshalb gibt es hier "
                         "keine Antwort. Eine Beraterin oder ein Berater kann die Frage beantworten."),
        ),
        "en": Texts(
            no_grounding=("There are no approved notes for this question, so there is no answer here. An adviser "
                          "can answer it."),
            not_covered=("The approved notes for this question do not cover it, so there is no answer here. An "
                         "adviser can answer it."),
        ),
    },
)

#: 1.0.0: kept as history, not run by this engine version (it has no general texts; CHB-18).
FIRST = PRODUCTION

PRODUCTION = FIRST.model_copy(update=dict(
    version="1.1.0",
    parent_version="1.0.0",
    note=("General answers (CHB-18): no refusal for lack of grounding; a question the notes do not cover is "
          "answered from general knowledge under a fixed marking line; refused only outside the domain or "
          "unintelligible (CHB-19). 1 200 output tokens for answers of up to 250 words."),
    generation=Generation(max_tokens=1200, temperature=0.0, seed=7, attempts=2),
    general={
        "de": GeneralTexts(
            label="Allgemeine Einschätzung von {assistant}, nicht aus den geprüften Unterlagen:",
            out_of_domain=("Diese Frage liegt ausserhalb dessen, wobei {assistant} helfen kann: {assistant} "
                           "beantwortet Fragen zu Geld, Einkommen, Beruf, Vorsorge, Versicherungen, Steuern, "
                           "Wohnen und Anlegen."),
            unintelligible=("Diese Frage konnte {assistant} nicht verstehen. Formulieren Sie sie bitte in einem "
                            "ganzen Satz neu."),
        ),
        "en": GeneralTexts(
            label="General assessment by {assistant}, not drawn from the approved notes:",
            out_of_domain=("This question is outside what {assistant} can help with: {assistant} answers "
                           "questions about money, income, work, pensions, insurance, taxes, housing and "
                           "investing."),
            unintelligible="{assistant} could not understand this question. Please ask it again in a full sentence.",
        ),
    },
))

SEEDS: tuple[Calibration, ...] = (FIRST, PRODUCTION)


def canonical_json(calibration: Calibration) -> str:
    """The byte-stable form a calibration is hashed and stored in. ``general`` is left out when it is absent,
    so a calibration written before the field existed (1.0.0) keeps its bytes and its hash."""
    payload = calibration.model_dump(mode="json")
    if payload.get("general") is None:
        payload.pop("general", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def calibration_hash(calibration: Calibration) -> str:
    """Content hash of the full parameter set, including its version label."""
    return "CAL-" + hashlib.sha256(canonical_json(calibration).encode("utf-8")).hexdigest()[:16]
