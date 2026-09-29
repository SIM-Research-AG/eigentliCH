"""Contracts: every model ``chatbot`` consumes or produces. Frozen, extra fields forbidden.

The engine is **stateless with respect to client data**: it never reads the consumer store. The caller
sends, with each question, what the answer may draw on: the approved knowledge notes it chose as
grounding, and optionally the client facts it is willing to show the model. Nothing else reaches the
prompt, so nothing else can reach the answer (the M74 guarantee of the prior art, expressed as a type).

* ``ChatRequest`` (``chat-request@1.0.0``): the question, the language, the grounding, optional client
  facts and the previous turns. Body of ``POST /run`` and ``POST /answer``.
* ``ChatAnswer`` (``chat-answer@1.0.0``): the answer, the grounding ids it cites, what it rests on
  (``basis``: the notes, general knowledge, or both, CHB-18), every number in it checked against the
  grounding and the client facts (``unverified_numbers`` lists the ones that match nothing), the refusal and
  its reason for the few questions that are refused (CHB-19), the model and its display name, the prompt
  version, the latency, the provenance and the notice. ``basis`` and ``model_display_name`` were added in
  calibration 1.1.0 as optional fields, so an answer stored before them still reads (CHB-20).
* ``Calibration`` (``chatbot-calibration@1.0.0``): generation parameters, limits, the number check, the
  client markers and the fixed texts. Immutable per version.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSIONS: dict[str, str] = {
    "ChatRequest": "chat-request@1.0.0",
    "ChatAnswer": "chat-answer@1.0.0",
    "Calibration": "chatbot-calibration@1.0.0",
}

NOTICE = "Model-derived research output. Not investment advice."

Language = Literal["de", "en"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# In
# ---------------------------------------------------------------------------

class GroundingNote(_Frozen):
    """One approved knowledge note the caller chose for this question."""

    id: str
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    #: How the note is cited to a reader, e.g. "eigentliCH Wissen: Säule 3a (2026)".
    source_label: str = Field(min_length=1, max_length=300)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"grounding id {value!r} must be 1 to 80 characters of letters, digits and _.:-")
        return value


class ClientFact(_Frozen):
    """One fact about the client the caller allows the answer to use."""

    key: str
    label: str = Field(min_length=1, max_length=200)
    #: A number is checked against the answer's numbers; text is shown to the model as given.
    value: Union[float, str]
    #: Where the caller has it from, e.g. "lbs LBS-1a2b..." or "onboarding 12.09.2026".
    source: str = Field(min_length=1, max_length=200)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"client fact key {value!r} must be 1 to 80 characters of letters, digits and _.:-")
        return value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: Union[float, str]) -> Union[float, str]:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("a client fact value must be finite")
        return value


class Turn(_Frozen):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(_Frozen):
    contract_version: Literal["chat-request@1.0.0"] = "chat-request@1.0.0"
    question: str = Field(min_length=1, max_length=2000)
    language: Language
    grounding: tuple[GroundingNote, ...] = ()
    client_facts: tuple[ClientFact, ...] = ()
    #: Previous turns, oldest first. Only the last ``history.max_turns`` (calibration) reach the prompt.
    history: tuple[Turn, ...] = ()
    #: ``None`` uses the active calibration from ``config.yaml``.
    calibration_version: Optional[str] = None

    @model_validator(mode="after")
    def _unique(self) -> "ChatRequest":
        ids = [g.id for g in self.grounding]
        if len(set(ids)) != len(ids):
            raise ValueError("grounding ids must be unique")
        keys = [f.key for f in self.client_facts]
        if len(set(keys)) != len(keys):
            raise ValueError("client fact keys must be unique")
        if not self.question.strip():
            raise ValueError("the question is empty")
        return self


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class Generation(_Frozen):
    max_tokens: int = Field(ge=16, le=8192)
    temperature: float = Field(ge=0.0, le=2.0)
    #: Passed to vLLM. Makes a repeat more likely to agree; it is not a guarantee, which is why the
    #: answer is stored and a repeat returns the stored one (CHB-06).
    seed: Optional[int] = None
    #: Drafts per question when a draft leaves the language or breaks the answer schema.
    attempts: int = Field(ge=1, le=4)


class Limits(_Frozen):
    max_notes: int = Field(ge=1)
    max_chars_per_note: int = Field(ge=100)
    max_total_chars: int = Field(ge=1000)
    max_client_facts: int = Field(ge=0)
    max_turns: int = Field(ge=0)
    max_chars_per_turn: int = Field(ge=50)


class NumberCheck(_Frozen):
    """How the numbers in an answer are checked against the sources (CHB-07)."""

    #: Numbers with fewer digits are not checked: "Säule 3a", "1. Säule", "Artikel 2" are labels.
    min_checked_digits: int = Field(ge=1, le=6)
    #: A source value may be quoted rounded to any of these decimals.
    rounding_decimals: tuple[int, ...]
    #: The only tolerance: floating-point representation. Rounding is enumerated, never tolerated.
    relative_tolerance: float = Field(gt=0.0, le=1e-3)


class Texts(_Frozen):
    #: Used by calibration 1.0.0 only (refusal for lack of grounding, withdrawn by CHB-18).
    no_grounding: str
    not_covered: str


class GeneralTexts(_Frozen):
    """The texts of general answers (CHB-18, CHB-19), per language. ``{assistant}`` is replaced by the model's
    configured display name (``model.display_name``, CHB-21)."""

    #: The line that marks the part of an answer drawn from general knowledge, not from the notes.
    label: str = Field(min_length=1, max_length=200)
    #: What the reader sees when the question is outside the system's domain entirely.
    out_of_domain: str = Field(min_length=1)
    #: What the reader sees when the question cannot be understood.
    unintelligible: str = Field(min_length=1)


class Calibration(_Frozen):
    contract_version: Literal["chatbot-calibration@1.0.0"] = "chatbot-calibration@1.0.0"
    version: str
    parent_version: Optional[str] = None
    note: str = ""
    generation: Generation
    limits: Limits
    number_check: NumberCheck
    #: Per language, regular expressions whose presence makes a question about the client (CHB-08).
    client_markers: dict[str, tuple[str, ...]]
    texts: dict[str, Texts]
    #: Since 1.1.0: the texts of general answers. A calibration without them (1.0.0) predates CHB-18 and is
    #: not run by this engine version; it stays in the store as history.
    general: Optional[dict[str, GeneralTexts]] = None

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$", value):
            raise ValueError(f"calibration version {value!r} is not semantic")
        return value

    @model_validator(mode="after")
    def _languages(self) -> "Calibration":
        for lang in ("de", "en"):
            if lang not in self.texts or lang not in self.client_markers:
                raise ValueError(f"the calibration has no texts or client markers for {lang!r}")
            for pattern in self.client_markers[lang]:
                re.compile(pattern)
            if self.general is not None and lang not in self.general:
                raise ValueError(f"the calibration's general texts have no {lang!r}")
        return self


# ---------------------------------------------------------------------------
# Out
# ---------------------------------------------------------------------------

class CheckedNumber(_Frozen):
    #: As written in the answer.
    text: str
    #: The sources it matches: grounding ids, ``fact:<key>``, ``question`` or ``history``. Empty means
    #: unverified.
    matched: tuple[str, ...]


#: ``no_grounding`` is no longer produced (CHB-18) and stays for answers stored before. ``not_covered`` is the
#: code of the remaining refusals, a question outside the system's domain or one that cannot be understood;
#: ``refusal_reason`` says which (CHB-19). No new code, so a caller's mirror of the contract keeps reading.
RefusalCode = Literal["no_grounding", "not_covered"]

#: What an answer rests on (CHB-18): ``grounded`` only the notes, ``general`` only general knowledge (marked
#: as such in the text), ``mixed`` both. ``None`` on a refusal and on answers stored before calibration 1.1.0.
Basis = Literal["grounded", "general", "mixed"]


class ModelUse(_Frozen):
    service: str
    host: str
    model: str
    prompt_version: str
    prompt_hash: str
    finish_reason: str
    attempts: int
    first_byte_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]


class Provenance(_Frozen):
    engine_version: str
    contract_versions: dict[str, str]
    calibration_version: str
    calibration_hash: str
    idempotency_key: str
    #: Content hashes of what the answer was allowed to draw on.
    request_hash: str
    grounding_ids: tuple[str, ...]
    grounding_hash: str
    client_fact_keys: tuple[str, ...]
    #: Whether the client facts reached the prompt: only for a question about the client (CHB-08).
    client_facts_used: bool
    history_turns_used: int
    #: ``None`` when no model was called (a question that cannot be understood; before 1.1.0 also a refusal
    #: for lack of grounding).
    model: Optional[ModelUse]
    label: Literal["model-derived"] = "model-derived"


class ChatAnswer(_Frozen):
    contract_version: Literal["chat-answer@1.0.0"] = "chat-answer@1.0.0"
    artefact_id: str
    question: str
    language: Language
    #: The text a reader sees. A part drawn from general knowledge follows the calibration's marking line
    #: ("Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:"). On a refusal, the fixed
    #: refusal text of the calibration.
    answer: str
    #: Grounding ids the answer cites, in the order the model gave them, unknown ids removed.
    cited_ids: tuple[str, ...]
    #: Every number in ``answer`` (at or above ``min_checked_digits``), each with the sources it matches.
    numbers: tuple[CheckedNumber, ...]
    #: The numbers that match no source. Non-empty means a reader must be warned or the answer withheld.
    unverified_numbers: tuple[str, ...]
    refused: bool
    refusal_code: Optional[RefusalCode] = None
    refusal_reason: Optional[str] = None
    #: ``population_fact`` or ``client_situation``: whether the question is about the client (CHB-08).
    route: Literal["population_fact", "client_situation"]
    #: What the answer rests on (CHB-18). Optional, added after the contract was first published (CHB-20).
    basis: Optional[Basis] = None
    #: What the engine noticed and repaired or dropped, in plain words.
    warnings: tuple[str, ...] = ()
    #: The technical model name (``google/gemma-...``); ``None`` when no model was called.
    model: Optional[str]
    #: The name readers see for the house's AI ("MiniMind", CHB-21): the configured ``model.display_name``.
    #: Optional, added after the contract was first published (CHB-20).
    model_display_name: Optional[str] = None
    prompt_version: str
    #: Wall clock of the model calls for this answer; 0 when none was made.
    latency_ms: float
    provenance: Provenance
    notice: str = NOTICE

    @model_validator(mode="after")
    def _consistent(self) -> "ChatAnswer":
        if self.refused != (self.refusal_code is not None):
            raise ValueError("refused and refusal_code must agree")
        if self.refused and self.basis is not None:
            raise ValueError("a refusal rests on nothing: basis must be None")
        if self.basis == "general" and self.cited_ids:
            raise ValueError("a general answer cites no note")
        unmatched = tuple(n.text for n in self.numbers if not n.matched)
        if tuple(dict.fromkeys(unmatched)) != self.unverified_numbers:
            raise ValueError("unverified_numbers must be exactly the numbers that match no source")
        return self


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

RunState = Literal["queued", "running", "succeeded", "failed"]


class RunAccepted(_Frozen):
    run_id: str
    status: RunState
    artefact_id: Optional[str]
    idempotency_key: str
    cached: bool


class RunStatus(_Frozen):
    run_id: str
    status: RunState
    idempotency_key: str
    started_at: str
    finished_at: Optional[str]
    wall_clock_ms: Optional[float]
    request: ChatRequest
    artefact_id: Optional[str]
    warnings: tuple[str, ...]
    provenance: Optional[Provenance]
    error: Optional[str]
