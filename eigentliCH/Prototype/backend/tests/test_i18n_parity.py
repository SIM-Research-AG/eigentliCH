"""A12: bilingual from the start, so a missing string is a failure now rather than a retrofit later.

The client's UI strings live in `client/app/i18n.js` — a JS module, not JSON, because they are the
client's own chrome and it has no build step to compile them from anything else. That makes them awkward
to assert on from Python, which is exactly why it is worth doing: an unparsed file is an unchecked one,
and a half-translated product ships when nobody can see which half.

Parsed with a brace-matching scan rather than a regex over the whole file. A regex is what produced a
confidently wrong count during development — 6 keys against 33 — and a test that miscounts silently is
the failure mode A20 already cost an hour to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

I18N = Path(__file__).resolve().parent.parent.parent / "client" / "app" / "i18n.js"

KEY = re.compile(r"^\s*'([^']+)'\s*:", re.MULTILINE)


def _block(source: str, language: str) -> str:
    """The body of one language object, by brace matching from a line-anchored marker.

    **The marker is anchored, and that is not fussiness.** An unanchored search for `en: {` matches inside
    the German string `'Erfasste Positionen: {n}.'` — "Position**en: {**n}" — and silently returns a block
    starting mid-value, which parsed as zero keys and made the parity test claim 39 against 0. Third time
    in this build that substring matching has produced a confident wrong answer.
    """
    marker = re.search(rf"^\s*{language}:\s*\{{", source, re.MULTILINE)
    assert marker, f"no {language} block found in {I18N}"
    start = marker.end()
    depth = 1
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
    raise AssertionError(f"unterminated {language} block in {I18N}")


def _keys(language: str) -> set[str]:
    return set(KEY.findall(_block(I18N.read_text(encoding="utf-8"), language)))


def test_the_parser_found_something():
    """Guard on the guard. A vacuous parse would make every assertion below pass."""
    assert len(_keys("de")) >= 20, f"parsed only {len(_keys('de'))} German keys — the scan is broken"


def test_german_and_english_carry_the_same_keys():
    """A12. Neither language may quietly gain a string the other lacks."""
    de, en = _keys("de"), _keys("en")
    assert de == en, (
        f"i18n is out of parity.\n  only in de: {sorted(de - en)}\n  only in en: {sorted(en - de)}"
    )


def test_no_string_is_empty():
    source = I18N.read_text(encoding="utf-8")
    for language in ("de", "en"):
        body = _block(source, language)
        empties = re.findall(r"^\s*'([^']+)'\s*:\s*''\s*,", body, re.MULTILINE)
        assert not empties, f"{language} has empty strings: {empties}"


@pytest.mark.parametrize("language", ("de", "en"))
def test_no_completion_or_gamification_keys_exist(language):
    """C-07 and R-113 as an absence in the string table.

    There is no screen that may say "3 of 8", so there must be no key for one. Checking the key names
    rather than the copy catches the intent a phrase away from being written.
    """
    forbidden = ("progress", "completion", "complete", "percent", "remaining", "streak",
                 "badge", "leaderboard", "level_number", "daily_goal", "score")
    keys = " ".join(sorted(_keys(language))).lower()
    found = [word for word in forbidden if word in keys]
    assert not found, f"{language} defines keys for forbidden concepts: {found}"


INDEX = I18N.parent.parent / "index.html"


def test_every_chrome_hook_has_a_string_in_both_languages():
    """A12 / A70. The chrome is translated at runtime, and this is the join that makes that work.

    `index.html` marks the doors and the skip link with `data-i18n="<key>"`; `main.js::applyChrome` looks
    each key up and rewrites the text. `t()` returns the key itself when a string is missing, and
    `applyChrome` deliberately leaves the served German in place rather than painting `chrome.door_plan`
    onto the header — which is the right failure for a member and an invisible one for a developer. So
    the mismatch has to be caught here instead.

    **Planted violation:** deleted `chrome.door_market` from the English block. Failed naming that key.
    Restored. (Deleting it from both would be caught by the parity test above as well, but only this one
    catches a key that exists in the markup and in neither table.)
    """
    hooks = set(re.findall(r'data-i18n="([^"]+)"', INDEX.read_text(encoding="utf-8")))
    assert hooks, "index.html has no data-i18n hooks; the chrome is hardcoded again"
    for language in ("de", "en"):
        missing = sorted(hooks - _keys(language))
        assert not missing, f"the chrome asks for {missing} and {language} does not define them"
