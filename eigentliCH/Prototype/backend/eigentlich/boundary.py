"""Who a question is about, and which language to answer in. What is left of C-01.

**C-01 was withdrawn by the owner on 20 September 2026 (A160, A164).** Until that day this module was
1,340 lines: a four-language pattern layer that classified every incoming question and scanned every
outgoing sentence for regulated advice, plus the refusal texts that went with it. All of it is gone. The
reasoning is A76's and four rounds of audit confirmed it — a blacklist of phrasings is unbounded by
construction, every round found a class nobody had listed, and the approach does not converge. The owner
ruled that the curator is the gate and the code does not need to decide whether a sentence is advice.

**What is deliberately NOT here any more, so nobody looks for it:** `check_answer`, `classify_question`,
`states_statutory_duty`, `refusal_text`, `REFUSAL`, `Verdict`, and the lexicons behind them. Output is no
longer examined before it reaches a member. `reports/c01-final-measurement.txt` is the record of what the
gate was catching on its last day — 223 probes, 176 refusals — because once the patterns are gone the
question "what did we stop doing" has no other answer.

**What survives, and why it is not compliance.** `asks_about_the_member` decides whether a question is
about the person asking it. That governs whether the member's vault may be read to answer it, which is a
data-protection rule (C-04, C-05) and would be just as necessary in a product nobody regulated. A113's
router keeps its world-question / member-question split on this function alone; the third branch, the
advice refusal, went with C-01 (A165).

`SUPPORTED_LANGUAGES` and `normalise_language` survive because the product is bilingual by A12 and
several surfaces need to agree on what locale they are answering in. They were never C-01's.
"""

from __future__ import annotations

import re

#: The languages this product answers in. Switzerland's official languages are German, French, Italian
#: and Romansh; the product's are German, English, French and Italian (A12).
#:
#: It kept its name through the cull. Until A164 these were the languages C-01's two gates were enforced
#: in, and the tuple was cited in that sense across the build; it now means only what it says.
SUPPORTED_LANGUAGES = ("de", "en", "fr", "it")

#: Named, not inlined, so a test can pin it. An unrecognised locale falls back HERE and nowhere else.
FALLBACK_LANGUAGE = "de"

#: ASCII transliterations, so a pattern matches how people actually type German without umlauts.
#: `fuer`, `waehlen` and `Freizuegigkeitskonto` are ordinary keyboard spellings, not obfuscation.
_TRANSLITERATIONS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}

#: A bracketed character class, or a bare umlaut outside one. Matched together in a single pass so that
#: the umlaut inside a class this function has just rewritten is not rewritten a second time.
_CLASS_OR_UMLAUT = re.compile(r"\[[^\]\\]*\]|[äöüßÄÖÜ]")


def _umlaut_tolerant(pattern: str) -> str:
    """Let every pattern match its ASCII transliteration as well as its proper spelling.

    **The safe direction, and the reason it is this one.** The alternative was to fold the incoming TEXT
    — turn `ue` back into `ü` before matching — and that manufactures false positives out of ordinary
    words: `Steuer` becomes `Stür`, `neue` becomes `nü`. Rewriting the patterns instead can only ever
    make a pattern match a spelling of the thing it already matches. No pattern gains reach over a word
    it did not already describe.

    Character classes are handled rather than skipped: `[üu]` accepts `fur` and `für` but not `fuer`, so
    a hand-written tolerance has exactly the hole this closes. `[üu]` becomes `(?:[üu]|ue)`.

    Kept after the cull for one caller, `_ABOUT_ME`, whose German possessives have the same problem: a
    member typing `fuer unsere Kinder` is asking about themselves either way.
    """

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("["):
            alternatives = [
                ascii_form
                for umlaut, ascii_form in _TRANSLITERATIONS.items()
                if umlaut in token.casefold()
            ]
            if not alternatives:
                return token
            return "(?:" + token + "|" + "|".join(alternatives) + ")"
        return "(?:" + token + "|" + _TRANSLITERATIONS[token.casefold()] + ")"

    return _CLASS_OR_UMLAUT.sub(replace, pattern)


def _compile(patterns: tuple[str, ...]) -> list[re.Pattern[str]]:
    return [re.compile(_umlaut_tolerant(p), re.IGNORECASE) for p in patterns]


def _any(compiled: list[re.Pattern[str]], text: str) -> list[str]:
    return [p.pattern for p in compiled if p.search(text)]


def normalise_language(language: str | None) -> str:
    """The locale this product will actually answer in. Never a silent fallback.

    `de-CH`, `de_CH` and `DE` all resolve to `de`. Anything outside `SUPPORTED_LANGUAGES` — Romansh, or a
    locale nobody has written copy for yet — resolves to `FALLBACK_LANGUAGE`, and a caller that wants to
    know whether that happened can compare this function's result with what it passed in.
    """
    tag = (language or "").strip().lower().replace("_", "-").split("-")[0]
    return tag if tag in SUPPORTED_LANGUAGES else FALLBACK_LANGUAGE


# ==========================================================================================================
# Does the question ask about the person asking it? (update script item 1, branch 2)
# ==========================================================================================================
#
# **This is a data-protection rule and it survived the cull on that basis (A164).** It decides whether the
# member's own vault may be read to answer a question. A question about the world is answered from the
# corpus and never touches their material; a question about them is answered with their material in front
# of it. That distinction is C-04 and C-05's, it protects the member from having their financial position
# read to answer a question that was not about them, and it would be just as necessary if nobody in
# Switzerland were licensed for anything.
#
# **Why it lives here and not in the router.** One file owns the vocabulary of who a sentence is about.
# `services/router.py` decides what to do with the answer; putting a second list of possessives there
# would be the two-lists-that-must-agree defect A73 and A91 both are.
#
# **Deliberately generous.** A question misread as personal is answered with the member's own material in
# front of it, which is at worst unnecessary. A question misread as impersonal is answered without their
# situation when they asked about their situation, which is the failure Principle 1 names. The costs are
# not symmetric, so the ambiguity resolves towards treating the question as personal.
_ABOUT_ME = (
    # German
    r"\bich\b",
    r"\b(?:mir|mich)\b",
    r"\bmein(?:e|em|en|er|es)?\b",
    r"\bwir\b",
    r"\buns(?:er|ere|erem|eren|erer|eres)?\b",
    # English. `I` is matched case-insensitively like everything else here, which also catches it
    # lower-cased in a hurried question.
    r"\bi\b",
    r"\b(?:me|my|we|us|our|ours)\b",
    # French
    r"\bje\b",
    r"\b(?:mon|ma|mes|moi)\b",
    r"\b(?:nous|notre|nos)\b",
    # Italian
    r"\bio\b",
    r"\b(?:mio|mia|miei|mie)\b",
    r"\b(?:noi|nostro|nostra|nostri|nostre)\b",
)

_ABOUT_ME_COMPILED = _compile(_ABOUT_ME)


def asks_about_the_member(question: str) -> list[str]:
    """The first-person markers in a question. Empty means it asks about the world, not about them.

    Returns the matched patterns rather than a bool, so a route can report WHY it decided a question was
    personal — "because you wrote 'unsere'" is inspectable and "true" is not.
    """
    return _any(_ABOUT_ME_COMPILED, question or "")
