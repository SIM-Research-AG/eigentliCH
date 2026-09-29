"""The intake's identities, reimplemented from `andersCH-prototype/onboarding-chat.html`.

===========================================================================================================
WHY THIS IS A REIMPLEMENTATION AND NOT A PORT, AND WHAT WAS DONE ABOUT THAT
===========================================================================================================

Item 3 of the update script says of `derive()`, `goalsFrom()`, `netScale()`, `expertiseScale()` and
`childAges()`: *"Preserve ... as they are — they are tested against the book cases and must not be
rewritten in the move."*

They are JavaScript, in a single-file prototype, computing against fixed assumptions in the browser. This
build is Python, server-side, against published assumption sets. **There is no move that preserves them as
they are**, so the instruction's letter cannot be followed and its intent has to be met another way. The
owner ruled on 3 September 2026: reimplement in Python, with the original as the standard.

**So the standard is differential, not editorial.** `tools/extract_identities.mjs` runs the ORIGINAL
JavaScript over a corpus and writes `tests/fixtures/identities-reference.json`; `tests/test_identities.py`
asserts this module reproduces it exactly. The question "did the port change the behaviour" is therefore
answered by the original itself rather than by whoever wrote the port. The fixture is committed and the
suite needs no Node.

**What that does NOT cover, said here rather than discovered later.** The corpus is 62 cases and is not the
input space. It covers every case the source's own comments call out by name, every boundary each function
turns on, and the shapes the six real submissions contain — which is a great deal better than nothing and
is not a proof. Anything outside it is untested in both languages equally.

===========================================================================================================
JAVASCRIPT SEMANTICS THAT HAD TO BE REPRODUCED, NOT TIDIED
===========================================================================================================

Four places where the obvious Python is subtly different, and each is a defect if "corrected":

  * `Number(x) || 0` returns 0 for null, undefined, "", NaN **and for 0 itself**. It is a coercion with a
    falsy fallback, not a null check, and `_number_or_zero` reproduces it exactly.
  * `d[k] ?? null` is nullish coalescing — it passes 0 and "" through, unlike `||`. `CONF[...] ?? null` in
    `goals_from` therefore yields null only for a confidence string that is not in the table.
  * `Math.round` rounds half toward POSITIVE INFINITY — `floor(x + 0.5)` — while Python's `round` rounds
    half to EVEN. `Math.round(0.125 * 100) / 100` is 0.13 there and 0.12 here. It is also NOT
    half-away-from-zero, which is what this bullet said until `node` was asked: `Math.round(-0.5)` is `-0`.
    `_js_round` is the JavaScript rule.
  * `String(x || '')` renders `None` as `''`, but `String(0)` is `'0'`. `_as_text` reproduces both.

===========================================================================================================
THE NUMBERS ARE IN A CONTENT RECORD, AND THE GUARD IS WHY
===========================================================================================================

`net_scale` and `learning_commitment_scale` turn on numbers — a scale of 8, 0.06 a mandate to a
ceiling of 0.18, a
neutral 0.5 floor — and so does the confidence table. **This module's first version kept them here**, on
the argument that they are declared conventions rather than rates and that C-02's "no literal rate in
application code" therefore did not reach them.

`test_no_literal_rate_in_application_code` disagreed, and it is right to: its own docstring says it "cannot
tell a rate from any other number, so it forbids the whole shape rather than trying to be clever about
intent". Excusing twenty-four values in its allowlist would have been twenty-four holes in the one check
that stops an invented rate reaching a member, in a file that is going to grow.

So they live in `client/content/intake-scales.json`, marked `provisional: true`. That flag is doing real
work: **nobody has calibrated these**, and `roles.json` ships D-03's role definitions marked provisional
for exactly the same reason. Publishing a number is not endorsing it.

What remains in this file as a literal is arithmetic — `0.5` in the rounding rule, `1e6` and `1e3` as the
multipliers behind "Mio" and "tausend", `0.0` as a coercion's floor — and each is named in the guard's
allowlist with that reason.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ..content import intake_scales


def _scales() -> dict:
    """The published record. Read per call rather than cached at import.

    `content._load` is already `lru_cache`d, so this costs a dict lookup; caching it again here would put
    a second copy behind a module global that a test could not clear.
    """
    return intake_scales()


def confidence_table() -> dict[str, float]:
    """The confidence answers as the questionnaire words them, and the epsilon each means."""
    return _scales()["confidence"]["options"]


def partnered() -> tuple[str, ...]:
    """Civil-status answers that mean a second adult is present."""
    return tuple(_scales()["civil_status"]["partnered"])


def married() -> tuple[str, ...]:
    """The subset of `partnered()` that is taxed jointly.

    Kept apart from `partnered()` because "the difference between them is legal rather than cosmetic:
    cohabiting partners share a household and are taxed separately, which is exactly the case a single
    'has a partner?' flag would get wrong."
    """
    return tuple(_scales()["civil_status"]["married"])


# ---------------------------------------------------------------------------
# JavaScript semantics
# ---------------------------------------------------------------------------


def _number_or_zero(value: Any) -> float:
    """JavaScript's `Number(value) || 0`.

    Not a null check: it is a numeric coercion whose falsy results — NaN, 0, "" — all become 0. A Python
    `float(value) if value is not None else 0` would differ on `"abc"` (raises) and on `True`.
    """
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if not math.isnan(float(value)) else 0.0
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        parsed = float(text)
    except ValueError:
        return 0.0
    return 0.0 if math.isnan(parsed) else parsed


def _js_string(value: Any) -> str:
    """JavaScript's bare `String(value)`, for the shapes the questionnaire's answers actually take.

    **`String([])` is `""` and `String(['a', 'b'])` is `"a,b"`** — an array stringifies as its joined
    elements, with no brackets. Python's `str([])` is `"[]"`, which has length 2, and that difference is
    what `learning_commitment_scale`'s "has anything been answered" check turns on: an empty
    multi-select means
    unanswered in the original and would have meant answered here. Caught by the differential fixture, not
    by reading.

    `None` is not handled: every caller checks for it before calling, exactly as the original does.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join("" if item is None else _js_string(item) for item in value)
    return str(value)


def _as_text(value: Any) -> str:
    """JavaScript's `String(value || '')`. `None` and `0` are falsy there, so both render as ''.

    Distinct from `_js_string` on purpose: the original uses `String(x || '')` in three places and a bare
    `String(x)` in one, and the two disagree on `0` — `""` against `"0"`.
    """
    if not value:
        return ""
    return _js_string(value)


def _js_round(value: float) -> int:
    """`Math.round`: half toward POSITIVE INFINITY, which is `floor(x + 0.5)` for every x.

    **Not "half away from zero", and the difference is not academic.** The first version of this function
    said away-from-zero and used `ceil(x - 0.5)` for negatives, which gives -1 for -0.5 where JavaScript
    gives -0. Checked against `node`: `Math.round(-0.5)` is `-0`, `Math.round(-1.5)` is `-1`,
    `Math.round(-2.5)` is `-2` — every one of them the higher of the two neighbours, not the further from
    zero. Python's own `round` is different again (half to even), so neither of the two obvious choices is
    right and this is written out.

    Nothing in this module currently rounds a negative — every quantity here is a count, an amount or a
    0..1 scale. It is correct anyway, because the next function to use it will not check.
    """
    return math.floor(value + 0.5)


def _round2(value: float) -> float:
    """The original's `Math.round(x * 100) / 100`."""
    return _js_round(value * 100) / 100


# ---------------------------------------------------------------------------
# The identities
# ---------------------------------------------------------------------------

_YEAR = re.compile(r"\b(20[2-9]\d)\b")
_MIO = re.compile(r"([\d'’.,]+)\s*(?:mio|million)", re.IGNORECASE)
_TSD = re.compile(r"([\d'’.,]+)\s*(?:k\b|tsd|tausend)", re.IGNORECASE)
_GROUPED = re.compile(r"(\d{1,3}(?:['’ .]\d{3})+)")
_BIG = re.compile(r"\b(\d{5,})\b")
_BIRTH_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _num(raw: str) -> float:
    """The original's `num`: strip apostrophes and spaces, then treat a comma as a decimal point."""
    return _number_or_zero(re.sub(r"['’ ]", "", str(raw)).replace(",", "."))


def parse_goal_text(text: Any) -> dict:
    """A year and an amount pulled out of a free-text goal, so a deferred goal can say what it was.

    Deliberately conservative: no match returns None rather than a guess, "because a wrong date on a
    client's goal is worse than none".

    **The year is removed before looking for an amount.** Without it, "2030: 750'000 für die Firma"
    returned 2030 as the amount — a bare four-digit year looks exactly like a small sum, and the year
    appears first. That is the original's own recorded bug fix and it is reproduced, not re-derived.
    """
    text = _as_text(text)
    year_match = _YEAR.search(text)
    rest = text.replace(year_match.group(0), " ", 1) if year_match else text

    amount: int | None = None
    mio = _MIO.search(rest)
    tsd = _TSD.search(rest)
    # A plain figure must LOOK like money: grouped with a separator, or at least five digits. That rules a
    # stray year or a count of children back out again.
    grouped = _GROUPED.search(rest)
    big = _BIG.search(rest)

    if mio:
        amount = _js_round(_num(mio.group(1)) * 1e6)
    elif tsd:
        amount = _js_round(_num(tsd.group(1)) * 1e3)
    elif grouped:
        amount = _js_round(_num(grouped.group(1)))
    elif big:
        amount = _js_round(_num(big.group(1)))

    return {
        "target_year": int(year_match.group(1)) if year_match else None,
        "amount_chf": amount,
    }


def goals_from(data: dict, year: int) -> list[dict]:
    """The goals implied by the answers, whether or not the member phrased them as goals.

    The primary goal is the spending target covered from the reference age onward — "it is what the pension
    questions, the AHV questions and the spending questions are all about". Past the reference age the
    question changes from "will it be funded at 65" to "does it hold from here", which is the independence
    test over a short horizon.

    The free-text goal is kept as `other` so the engine defers it rather than guessing its kind: "a
    Ferienvilla is a consumption good and a company buy-in is not, and that distinction is not something a
    regex should decide."
    """
    birth_year = data.get("birth_year")
    age = year - int(_number_or_zero(birth_year)) if birth_year else None
    spend = _number_or_zero(data.get("spend_later")) or _number_or_zero(data.get("spend_now"))
    # `?? null`, not `|| null`: nullish coalescing passes 0 through, and only an absent key yields None.
    table = confidence_table()
    stated = data.get("goal_confidence")
    confidence = table.get(stated) if stated in table else None

    out: list[dict] = []
    if age is not None and spend > 0:
        if age < 65:
            out.append(
                {
                    "kind": "retirement",
                    "description": "Ausgaben ab 65 aus eigenem Vermögen gedeckt",
                    "target_year": year + (65 - age),
                    "amount_chf": spend,
                    "confidence": confidence,
                    "is_consumption": False,
                }
            )
        else:
            out.append(
                {
                    "kind": "fi",
                    "description": "Ausgaben aus frei verfügbarem Vermögen gedeckt",
                    "target_year": year + 5,
                    "amount_chf": spend,
                    "confidence": confidence,
                    "is_consumption": False,
                }
            )

    if data.get("goals"):
        parsed = parse_goal_text(data["goals"])
        out.append(
            {
                "kind": "other",
                "description": str(data["goals"]),
                "target_year": parsed["target_year"],
                "amount_chf": parsed["amount_chf"],
                "confidence": confidence,
                "is_consumption": None,
            }
        )
    return out


def net_scale(people: Any, mandates: Any) -> float | None:
    """The network capital, 0..1. A DECLARED CONVENTION — see the module docstring.

    The original's own note: "Saturating in the number of people who would actually answer, with mandates
    as visibility on top. The scale of 8 is chosen so the questionnaire's own working range separates:
    1 contact -> 0.12, 3 -> 0.31, 6 -> 0.53, 15 -> 0.84. Mandates add 0.06 each to a ceiling of 0.18,
    because a board seat is a real visibility signal and three of them are not three times one."
    """
    if people is None and mandates is None:
        return None
    published = _scales()["network"]
    base = 1 - math.exp(-_number_or_zero(people) / published["people_scale"])
    seats = min(published["mandate_ceiling"], published["per_mandate"] * _number_or_zero(mandates))
    return _round2(min(published["ceiling"], base + seats))


#: The structured answers around the free-text education question. Presence of ANY of them is what
#: makes a
#: score possible at all.
_EDUCATION_KEYS = (
    "education_recent",
    "education_planned",
    "education_hours",
    "education_budget",
)


def learning_commitment_scale(data: dict) -> float | None:
    """How much a person is currently investing in learning, 0..1. **Not the same thing as E.**

    Renamed from `expertise_scale` on 6 September 2026, because the build now has two numbers that were
    both called expertise and they measure different quantities:

        this one                     what a person is PUTTING IN — recent education, planned education,
                                     hours invested, a training budget. A neutral floor of 0.5 plus
                                     credits, and it never falls below that floor.
        `human_capital.expertise`    what a person HOLDS — the BFS education category, whose rung is the
                                     value that reproduces that qualification's published median wage.

    Only the second reaches the engine's E. This one is a faithful port of the original prototype and is
    frozen: `tests/fixtures/identities-reference.json` still keys it `expertiseScale`, which is what the
    original called it and must stay, because that fixture's whole job is fidelity to the original.

    Not called `willingness_*`: this build already uses willingness as a term of art in the risk profile,
    where it stands opposite capacity, and a second unrelated willingness would collide with it. What is
    measured here is demonstrated investment rather than stated appetite, so commitment is also the more
    accurate word.

    The original's reasoning, carried because it is a boundary rather than a preference: expertise "is
    asked as free text, which cannot be scored deterministically — and a language model scoring it would be
    exactly the line the schema draws ('an LLM that rephrases a question is fine; an LLM that decides what
    W_res means is not'). So this uses the STRUCTURED answers around it instead, and says so."

    **The free-text answer is not read here and must not be.**
    """
    # `d[k] !== null && d[k] !== undefined && String(d[k]).length`. The bare `String` matters: an empty
    # multi-select is `""` and does not count, and a stated `0` budget is `"0"` and does.
    answered = any(
        data.get(key) is not None and len(_js_string(data.get(key))) > 0
        for key in _EDUCATION_KEYS
    )
    if not answered:
        return None

    published = _scales()["learning_commitment"]
    score = published["neutral_floor"]  # the neutral midpoint, as the floor rather than the answer
    recent = _as_text(data.get("education_recent")).lower()
    if recent and recent != "nein":
        score += published["recent_education"]
    if data.get("education_planned"):
        score += published["planned_education"]
    # A band the questionnaire does not offer contributes nothing, which is `hrs` being undefined in the
    # original and falsy at the `if`.
    hours = published["hours"].get(data.get("education_hours"))
    if hours:
        score += hours
    if _number_or_zero(data.get("education_budget")) >= published["budget_threshold_chf"]:
        score += published["budget_credit"]
    return _round2(min(published["ceiling"], score))


def child_ages(text: Any, year: int) -> list[int] | None:
    """Ages today from a free-text list of birth years. `"2020 und 2022"` -> `[6, 4]`.

    Returns None rather than an empty list when nothing matched: "no birth years given" and "birth years
    given, all of them implausible" are different answers, and the original distinguishes them.
    """
    years = _BIRTH_YEAR.findall(_as_text(text))
    matches = _BIRTH_YEAR.finditer(_as_text(text))
    if not years:
        return None
    ages = [year - int(match.group(0)) for match in matches]
    return [age for age in ages if 0 <= age <= 60]


__all__ = [
    "child_ages",
    "confidence_table",
    "learning_commitment_scale",
    "goals_from",
    "married",
    "net_scale",
    "parse_goal_text",
    "partnered",
]
