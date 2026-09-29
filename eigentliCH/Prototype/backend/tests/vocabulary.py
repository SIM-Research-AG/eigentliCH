"""The forbidden vocabularies, defined once. R-143 and C-07.

**Why this module exists.** `test_content.py` and `test_client_bundle.py` each carried their own copy of
these lists, and the client's copy said in a comment that it was *"matching the backend's list"*. It was
not: it omitted `hut`, `berg` and `tour` from the mountain vocabulary — two of which principle 10 names
explicitly — and its gamification list was missing `points`, `punkte`, `score`, `badge`, `rang` and `xp`.
So the client half of two constraints was materially weaker than the server half, and a comment asserted
they were the same.

Nothing was leaking when this was found: every occurrence in the client was inside a comment describing the
rule, and both scanners strip comments before matching. That is luck, not a guarantee.

This is the same defect as A73's export-versus-erasure lists and A63's two-places-one-fact: **two lists
that must agree, maintained separately.** The fix is not to top up the shorter one — that leaves the next
divergence free to happen. It is to make divergence unexpressible.

**On what is deliberately absent, because a filter that fires on ordinary prose gets deleted:**

  * `höhe` — the ordinary German word for an amount, as in "in Höhe von". It would fire on half of any
    financial sentence.
  * bare `level` — C-07 names "level-number", and a hyphen is a word boundary, so bare `level` fires on
    "product-level commitment", the manual's own phrase.
  * bare `punkt` — the ordinary German word for a decimal point and for an item on an agenda.

**On German inflection.** These are matched whole-word, and German inflects. `punkte` alone missed the
dative plural in "74 von 100 Punkten", which walked past the gamification list entirely until it was found
by probing. Where a form is realistically used, it is listed explicitly rather than left to a stem.

**And on German COMPOUNDING, which is not the same problem.** A88 gave `GAMIFICATION_WORDS` its
inflections and left `MOUNTAIN_WORDS` exactly as it was. An audit then walked eight forms straight past
R-143: `summits`, `Aufstiegs-`, `Gipfelweg`, `Bergetappe`, `Gipfelsturm`, `Bergführer`, `climbing`, and
`Basislager`, which was not in the vocabulary in any form. Listing inflections could never have closed
that: `\\b` breaks at a hyphen and at a space, it does not break inside `Gipfelweg`, and no list of
literals ever will, because compounding is productive and the next compound has not been written yet.

So the mountain vocabulary is split into STEMS, which `mountain_hits()` matches as `\\bstem\\w*` and which
therefore catch a compound nobody has thought of, and EXACT words, which are matched whole. Two are exact
deliberately, and both were found by running the stem rule over the whole package first:

  * `tour` — `\\btour\\w*` fires on the French *tourne*, which `services/know.py` says to a member whose
    local model is unavailable. A filter that fires on a refusal message is a filter somebody switches off.
  * `hut` — `\\bhut\\w*` fires on the German *Hut*, a hat.

**On accreditation and German adjective endings.** `ACCREDITATION_WORDS` stays a flat whole-word list —
its guard tests pin its exact output, and `eidg` as a stem would fire on *Eidgenossenschaft* and on very
little else worth the risk. The declined adjective forms are appended as literals instead, because
`akkreditiert` does not match *akkreditierter* and that is the form a drafter writes.
"""

from __future__ import annotations

import re

#: R-143 / principle 10. The metaphor belongs to the marketing surfaces, never to the authenticated
#: product. Stems first — see the module docstring on compounding for why the split exists.
MOUNTAIN_STEMS_EN = (
    "mountain",
    "summit",
    "climb",
    "altitude",
    "ascent",
    "basecamp",
)

MOUNTAIN_EXACT_EN = ("hut",)

MOUNTAIN_STEMS_DE = (
    "berg",
    "gipfel",
    "hütte",
    "huette",
    "aufstieg",
    "seilschaft",
    "basislager",
)

MOUNTAIN_EXACT_DE = ("tour",)

#: The compound and inflected forms the audit walked through, listed as literals as well.
#:
#: `mountain_hits()` already catches every one of these from the stems above, so these entries add nothing
#: to any scanner that uses it. They exist for the scanners that can only match a flat list whole-word —
#: `test_client_bundle.py` is one, and it belongs to another owner, so the strengthening has to reach it
#: through the vocabulary rather than through its code. `test_the_stem_rule_and_the_flat_list_agree` in
#: `test_content.py` is what stops the two halves from coming to forbid different words.
MOUNTAIN_FORMS_EN = (
    "mountains",
    "summits",
    "climbing",
    "climber",
    "climbers",
    "ascents",
)

MOUNTAIN_FORMS_DE = (
    "berge",
    "bergetappe",
    "bergführer",
    "bergfuehrer",
    "bergsteigen",
    "gipfelweg",
    "gipfelsturm",
    "aufstiegs",
)

MOUNTAIN_WORDS_EN = MOUNTAIN_STEMS_EN + MOUNTAIN_EXACT_EN + MOUNTAIN_FORMS_EN
MOUNTAIN_WORDS_DE = MOUNTAIN_STEMS_DE + MOUNTAIN_EXACT_DE + MOUNTAIN_FORMS_DE

MOUNTAIN_STEMS = MOUNTAIN_STEMS_EN + MOUNTAIN_STEMS_DE
MOUNTAIN_EXACT = MOUNTAIN_EXACT_EN + MOUNTAIN_EXACT_DE

MOUNTAIN_WORDS = MOUNTAIN_WORDS_EN + MOUNTAIN_WORDS_DE


def mountain_hits(haystack: str) -> list[str]:
    """R-143's matcher: a stem matches into a compound, an exact word does not.

    Lowercases for the caller, because every existing call site lowercased first and one that forgets is
    a scan that quietly finds nothing.

    Returns the stems and words that fired, sorted, so a failure message names the vocabulary entry rather
    than the compound — `berg` rather than `Bergetappe` — and a reader can go and look at the list.
    """
    low = haystack.lower()
    return sorted(
        {w for w in MOUNTAIN_STEMS if re.search(r"\b" + re.escape(w) + r"\w*", low)}
        | {w for w in MOUNTAIN_EXACT if re.search(r"\b" + re.escape(w) + r"\b", low)}
    )

#: C-07. No gamification vocabulary in member-facing copy either — the constraint is about the product,
#: not only about the schema.
GAMIFICATION_WORDS = (
    "points",
    "punkte",
    "punkten",
    "punktzahl",
    "score",
    "streak",
    "badge",
    "abzeichen",
    "leaderboard",
    "bestenliste",
    "rang",
    "rangliste",
    "ränge",
    "level_number",
    "levelnumber",
    "level up",
    "levelup",
    "xp",
    "daily goal",
    "tagesziel",
)

#: C-07 again, as IDENTIFIERS rather than as copy: the field that has not been rendered yet. Moved here
#: from `test_constraints.py` on the same reasoning that brought the word lists here — `test_befund.py`,
#: `test_learning.py` and `test_position_edit_api.py` all read it, and a set that four files share is a
#: set that belongs to none of them.
#:
#: `level` alone is not here: the constraint names "level-number" specifically, and a hyphen is a word
#: boundary, so bare `level` fires on "product-level commitment".
#:
#: **These are matched as words within a name, not as the whole name.** They were exact-set membership
#: until an audit planted `grid_completion_score`, `points_earned`, `streak_days` and `xp_total` and
#: watched all four pass: `points_earned` is not the string `points`, and a set lookup cannot see that it
#: contains it. `whole_words_in_identifier` in `test_content.py` is the matcher, and it reads `snake_case`
#: as words, so a tally arriving underscore-joined is caught and `underscore` still is not.
GAMIFICATION_IDENTIFIERS = frozenset(
    {
        "points",
        "point_total",
        "score",
        "streak",
        "badge",
        "badges",
        "level_number",
        "levelnumber",
        "leaderboard",
        "daily_goal",
        "dailygoal",
        "xp",
        "rank",
        "ladder_rank",
    }
)

#: R-194 / NG-04. eigentliCH's capability statements are its own, and nothing may suggest otherwise. Both
#: languages, because A12 makes every copy rule a two-language rule.
#:
#: `Ausweis` is deliberately absent: `Vorsorgeausweis` is the ordinary name of the pension statement a
#: member is asked to read, and forbidding the word would force worse copy to satisfy a filter.
#:
#: Moved here from `test_learning.py`, where it was applied to the learning seed content and to two source
#: files and to nothing else. NG-04 says "in code, **copy**, or generated certificates", and an audit
#: planted "Eidgenössisch akkreditierter Fachausweis" into a German block that no reader covered.
#: `test_content.py` now runs it over every member-facing string in the product.
ACCREDITATION_WORDS = (
    "akkreditiert",
    "akkreditierung",
    "eidgenössisch",
    "eidgenoessisch",
    "eidg",
    "accredited",
    "accreditation",
    "certified",
    "certificate",
    "certification",
    "diploma",
    "diplom",
    "zertifikat",
    "zertifiziert",
    "fachausweis",
    "staatlich",
    # Appended, and appended rather than interleaved so the ordered assertions in `test_learning.py` and
    # `test_marketplace.py` keep pinning what they were written to pin. German adjectives decline, and
    # `akkreditiert` does not match "akkreditierter Fachausweis" — the audit's own planted phrase.
    "akkreditierte",
    "akkreditierter",
    "akkreditiertes",
    "akkreditierten",
    "zertifizierte",
    "zertifizierter",
    "zertifiziertes",
    "zertifizierung",
)
