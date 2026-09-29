"""Questionnaires from the content store: what to ask next, whether an answer fits, and a content edit.

Pure functions over a questionnaire body (``questionnaire/onboarding``, ``questionnaire/intake``; SCHEMA.md
section 6). Nothing here writes; ``service`` does.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Optional

NAMES = {"onboarding": "questionnaire/onboarding", "intake": "questionnaire/intake"}

#: The goal templates the onboarding's ``goal_template`` question offers, from the prototype
#: (``services/goals.py`` GOAL_TEMPLATES, names and purposes verbatim). The store holds no template content;
#: a ``reference/goal-templates`` record, when someone adds one, replaces this list (EIG-35).
GOAL_TEMPLATES: list[dict[str, Any]] = [
    {"key": "early_retirement",
     "de": {"name": "Frühpensionierung", "purpose": "Früher aufhören zu arbeiten, als es die Vorsorge vorsieht."},
     "en": {"name": "Early retirement", "purpose": "Stopping work earlier than the pension system assumes."}},
    {"key": "financial_independence",
     "de": {"name": "Finanzielle Unabhängigkeit",
            "purpose": "Vermögen, das so weit trägt, dass Erwerbsarbeit eine Wahl ist und keine Notwendigkeit."},
     "en": {"name": "Financial independence",
            "purpose": "Assets that carry far enough that paid work is a choice rather than a necessity."}},
    {"key": "courage_money", "de": {"name": "Mutgeld", "purpose": "Eine Reserve, die einen Wechsel möglich macht."},
     "en": {"name": "Courage money", "purpose": "A reserve that makes a change possible."}},
    {"key": "home_ownership", "de": {"name": "Wohneigentum", "purpose": "Eine eigene Wohnung oder ein eigenes Haus."},
     "en": {"name": "Home ownership", "purpose": "A flat or a house of your own."}},
    {"key": "holiday_property", "de": {"name": "Ferienobjekt", "purpose": "Eine Zweit- oder Ferienwohnung."},
     "en": {"name": "Holiday property", "purpose": "A second or holiday home."}},
    {"key": "education", "de": {"name": "Weiterbildung oder Umschulung", "purpose": "Eine Ausbildung, die Sie finanzieren."},
     "en": {"name": "Further education or retraining", "purpose": "Training you pay for."}},
    {"key": "own_business", "de": {"name": "Firma aufbauen oder kaufen", "purpose": "Ein eigenes Unternehmen."},
     "en": {"name": "Building or buying a business", "purpose": "A business of your own."}},
    {"key": "estate", "de": {"name": "Nachlass und Erben", "purpose": "Was bleibt, und an wen."},
     "en": {"name": "Estate and inheritance", "purpose": "What remains, and to whom."}},
    {"key": "unspecified", "de": {"name": "Ein eigenes Ziel", "purpose": "Ein Ziel, das Sie selbst benennen."},
     "en": {"name": "A goal of your own", "purpose": "A goal you name yourself."}},
]


class AnswerRefused(ValueError):
    """The value does not fit the question. The message says why, in plain words."""


def ordered(body: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(body.get("questions") or [], key=lambda q: (q.get("order", 0), q["key"]))


def question(body: dict[str, Any], key: str) -> dict[str, Any]:
    for q in body.get("questions") or []:
        if q["key"] == key:
            return q
    raise KeyError(key)


def is_asked(q: dict[str, Any], answers: dict[str, Any]) -> bool:
    """``asked_when: {key, equals}``: the question is asked only when that answer equals the value."""
    cond = q.get("asked_when")
    if not isinstance(cond, dict) or "key" not in cond:
        return True
    return answers.get(cond["key"]) == cond.get("equals")


def next_question(body: dict[str, Any], answers: dict[str, Any]) -> Optional[str]:
    """The first question, in order, that is asked and not answered. Never a count (R-113)."""
    for q in ordered(body):
        if is_asked(q, answers) and q["key"] not in answers:
            return q["key"]
    return None


def check(q: dict[str, Any], value: Any) -> Any:
    """The value as it will be stored, or AnswerRefused. The stored answer is the option's value."""
    kind = q.get("type")
    if value is None or value == "" or value == [] or value == {}:
        raise AnswerRefused("an empty answer is not stored; skip the question instead")
    if kind == "choice":
        values = [o.get("value") for o in q.get("options") or []]
        if values and value not in values:
            raise AnswerRefused(f"{value!r} is not one of the options")
        return value
    if kind == "multi_choice":
        # Several options at once (EIG-44): the stored answer is the list of the chosen values, in the
        # questionnaire's order, each once.
        values = [o.get("value") for o in q.get("options") or []]
        if not isinstance(value, list):
            raise AnswerRefused("a list of options is expected")
        unknown = [v for v in value if v not in values]
        if unknown:
            raise AnswerRefused(f"{unknown[0]!r} is not one of the options")
        return [v for v in values if v in value]
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise AnswerRefused("a number is expected")
        if q.get("min") is not None and value < q["min"]:
            raise AnswerRefused(f"at least {q['min']}")
        if q.get("max") is not None and value > q["max"]:
            raise AnswerRefused(f"at most {q['max']}")
        return value
    if kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise AnswerRefused("a text is expected")
        return value.strip()[:4000]
    if kind == "household":
        if not isinstance(value, dict):
            raise AnswerRefused("a household is {adults: [...], dependants: [...]}")
        adults = [str(a).strip() for a in value.get("adults") or [] if str(a).strip()]
        dependants = [str(a).strip() for a in value.get("dependants") or [] if str(a).strip()]
        if not adults:
            raise AnswerRefused("a household has at least one adult: you")
        out = {"adults": adults, "dependants": dependants}
        if value.get("as_of"):
            out["as_of"] = str(value["as_of"])[:10]
        return out
    if kind == "goal_template":
        if isinstance(value, str):
            value = {"template": None, "name": value}
        if not isinstance(value, dict) or not str(value.get("name") or "").strip():
            raise AnswerRefused("a goal needs a name")
        template = value.get("template")
        if template not in {t["key"] for t in GOAL_TEMPLATES}:
            template = None
        return {"template": template, "name": str(value["name"]).strip()[:200]}
    if kind == "repeat":
        if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
            raise AnswerRefused("a list of entries is expected")
        fields = {f["key"]: f for f in q.get("fields") or []}
        rows = []
        for entry in value:
            row = {}
            for k, v in entry.items():
                if k in fields and v not in (None, "", [], {}):
                    row[k] = check(fields[k], v)
            if row:
                rows.append(row)
        if not rows:
            raise AnswerRefused("an empty list is not stored; skip the question instead")
        return rows
    return value


# ---------------------------------------------------------------------------
# Editing the shared content (owner decision: client and curator both edit it)
# ---------------------------------------------------------------------------

EDITABLE_TEXTS = ("question", "why", "placeholder")


def apply_edit(body: dict[str, Any], question_key: str, edit: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``body`` with one question's wording changed.

    ``edit`` may carry ``question``, ``why``, ``placeholder`` (each ``{de, en}``; a missing language keeps its
    text, an empty string removes it) and ``options`` (a list of ``{value, label: {de, en}}``). The question
    key, type and order never change here: answers already given refer to them. Option **values** may be
    added; an existing value may be relabelled or removed, never renamed, since a stored answer is the value.
    """
    new = copy.deepcopy(body)
    q = question(new, question_key)
    for field in EDITABLE_TEXTS:
        if field not in edit or edit[field] is None:
            continue
        given = edit[field]
        if not isinstance(given, dict):
            raise ValueError(f"{field} is {{de, en}}")
        current = dict(q.get(field) or {}) if isinstance(q.get(field), dict) else {}
        for lang in ("de", "en"):
            if lang in given:
                text = str(given[lang] or "").strip()
                if text:
                    current[lang] = text[:4000]
                    if lang == "en":
                        current.pop("en_draft", None)
                else:
                    current.pop(lang, None)
        if field == "question" and not current.get("de"):
            raise ValueError("a question keeps its German wording")
        if current:
            q[field] = current
        else:
            q.pop(field, None)
    if edit.get("options") is not None:
        if q.get("type") not in ("choice", "multi_choice"):
            raise ValueError("only a choice question has options")
        # An option kept for earlier answers but no longer offered (``offered: false``, EIG-44) stays so
        # unless the edit says otherwise: the edit box sends values and labels only.
        was_offered = {o.get("value"): o.get("offered", True) for o in q.get("options") or []}
        options = []
        seen = set()
        for o in edit["options"]:
            value = o.get("value")
            if isinstance(value, str):
                value = value.strip()
            if value in (None, "") or value in seen:
                raise ValueError("every option has its own value")
            seen.add(value)
            label = {k: str(v).strip() for k, v in (o.get("label") or {}).items() if k in ("de", "en") and str(v).strip()}
            if "de" not in label:
                label["de"] = str(value)
            option: dict[str, Any] = {"value": value, "label": label}
            offered = o.get("offered", was_offered.get(value, True))
            if offered is False:
                option["offered"] = False
            options.append(option)
        if not options:
            raise ValueError("a choice question keeps at least one option")
        q["options"] = options
    return new
