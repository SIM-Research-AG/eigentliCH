"""The four gaps A90 named that were screens over finished servers, held from the client side.

**What this file is about.** A90's finding was not any single item: *"the backend is close to complete and
unusually well guarded; the product a member can touch is about six screens of fourteen."* Four of those
missing screens closed on 31 August 2026 and this is their guard set:

  * **R-210 / R-213** — a member granting a curator access and revoking it. There was no client function
    for grants at all, so both directions were unreachable and a curator who signed in correctly saw
    nothing, because every read under `/api/curator` refuses without a live grant.
  * **S-11** — the Market Place, over a placeholder whose string was literally "Noch nicht gebaut." in
    front of the most rigorously guarded module in the build.
  * **S-05, S-09, S-13 and S-10's learning path** — four payloads phase 8 composed that no client code
    called.
  * **R-232** — a statement about the schema that was shown to nobody.

**What is checked here and what is not.** The word filters, the C-05 scan, the `innerHTML` ban, the "no
member id on the wire" check and the whole-table C-01 gate are NOT repeated: `test_client_bundle.py` walks
every file under `client/app` and `client/surfaces`, and `test_client_surfaces.py` runs `check_answer` over
every string in both languages, so the new surfaces are already inside all of them. Restating any of those
vocabularies here is A91's exact defect — two lists that must agree, maintained separately.

**What was checked in a live DOM instead of here**, because it cannot be held statically: that each screen
renders against a real payload, that a grant actually opens and then closes on the curator's very next
read, that a refusal reaches the screen, and that an announcement is not overwritten by the render behind
it. A `linkedom` harness imported the real `main.js` and drove all seven surfaces end to end against a real
uvicorn on a throwaway database — 123 checks — and four planted violations were each watched to fail:
`announce` before its `await` (the member heard the screen name instead of "the access is withdrawn"), a
client-side `sort` in the market list, the disclosures dropped from a listing card, and every scope
checkbox preselected. **The fourth plant did not fail on the first attempt**, and that is recorded here
because it is the more useful half: the assertion read `input.checked` only, and `linkedom` does not
reflect a `checked` attribute onto the property, so the most natural way to write the defect was invisible
to it. The repaired form reads the property and the attribute.

**Every guard below was proven the same way** — plant, watch it fail, restore. What was planted is recorded
on each test.

**A95 is the reason several scans here are scoped to the copy this pass authored** rather than to the whole
table. A blunt search for a pending-state word fires on a sentence *denying* that a pending state exists,
which is exactly what `grants.no_pending` is.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_client_accessibility import INTERACTIVE_SELECTORS  # noqa: E402
from test_client_surfaces import both_languages, source, strings  # noqa: E402

from eigentlich.models import GATHERING_KINDS, GRANTABLE  # noqa: E402
from eigentlich.models.base import DataClass  # noqa: E402
from eigentlich.models.marketplace import DOMAINS, PIPELINES  # noqa: E402
from eigentlich.services.community import FORBIDDEN_GATHERING_WORDS  # noqa: E402
from eigentlich.services.marketplace import (  # noqa: E402
    ENTRY_KINDS,
    FILTER_PARAMETER,
    NO_FILTER,
    ORDERING_INPUT_NAMES,
)
from eigentlich.services.stages import LIFE_EVENT_KEYS, MODULE_FIELDS  # noqa: E402

CLIENT = BACKEND.parent / "client"
INDEX = CLIENT / "index.html"

#: Every file a member's browser loads that this pass touched, plus the router that reaches them.
TOUCHED = (
    "app/api.js",
    "app/main.js",
    "app/i18n.js",
    "surfaces/grants.js",
    "surfaces/market.js",
    "surfaces/stages.js",
    "surfaces/life-events.js",
    "surfaces/community.js",
    "surfaces/learning.js",
    "surfaces/settings.js",
    "surfaces/know.js",
)

#: The six surfaces this pass added. Separated from `TOUCHED` because several scans below are about what a
#: *new* screen may contain, and running them over `i18n.js` or the router would say nothing.
NEW_SURFACES = (
    "surfaces/grants.js",
    "surfaces/market.js",
    "surfaces/stages.js",
    "surfaces/life-events.js",
    "surfaces/community.js",
    "surfaces/learning.js",
)


def code(name: str) -> str:
    return source(name)


def test_every_file_this_pass_touched_exists_and_was_read():
    """A20. Every scan below iterates one of these sets; a misspelled entry passes all of them silently.

    **Planted violation:** renamed one entry to `surfaces/nope.js`. Failed on the missing file. Restored.
    """
    for name in TOUCHED:
        text = code(name)
        assert len(text) > 800, f"{name} came back as {len(text)} characters; the reader is wrong"
    for name in NEW_SURFACES:
        assert name in TOUCHED, f"{name} is scanned as new but is not in TOUCHED"


def test_no_line_comment_hides_a_block_from_any_scanner():
    """A91's third finding, applied to the files this pass wrote.

    Every client scanner strips ``/* … */`` before ``//``, so a **line** comment containing ``/*`` deletes
    everything up to the next ``*/`` from what those scanners can see. It once hid a whole surface's imports
    and two functions from every client guard at once. These files talk about route prefixes constantly,
    which is exactly where a ``/api/curator/*`` would get typed.

    **Planted violation:** wrote a route prefix ending in a star inside a line comment in `grants.js`. The
    scan failed naming the line. Restored to a spelled-out prefix.
    """
    offenders = []
    for name in TOUCHED:
        text = (CLIENT / name).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("//") and "/*" in line:
                offenders.append(f"{name}:{number}")
    assert not offenders, (
        "a line comment opens a block comment, which deletes the rest of the file from every scanner "
        f"that strips block comments first: {offenders}"
    )


# ============================================================ R-210 / R-213 — the member's own grants


def test_the_grant_screen_is_reachable_in_both_directions():
    """**A90's fourth finding, checked as the whole join.** Any one link missing is the defect back.

    A route, a handler behind it, a surface behind that, the three API functions, and the three endpoints.
    A route with no entry in `ROUTES` falls through to the grid — `ROUTES[name] || ROUTES.plan` — which is
    the shape of failure that looks like a working application.

    **Planted violation, three times:** removed the `grants:` entry from `ROUTES` (the screen then rendered
    the grid and this failed); renamed `revokeGrant` in `api.js`; deleted the `DELETE` method from it. Each
    failed naming the missing half. All restored.
    """
    router = code("app/main.js")
    assert re.search(r"\bgrants:\s*renderGrants\b", router), "no route answers #/grants"
    assert re.search(r"async function renderGrants\s*\(", router), "there is no handler behind the route"
    assert "grants.load(" in router and "grants.render(" in router

    surface = code("surfaces/grants.js")
    for called in ("getGrants(", "grantAccess(", "revokeGrant(", "grantableScopes(", "getCurators("):
        assert called in surface, f"the grant screen never calls {called}"

    api = code("app/api.js")
    assert "'/api/curator/grants'" in api, "api.js does not reach the grant collection"
    assert re.search(r"/api/curator/grants/\$\{encodeURIComponent\(grantId\)\}", api), (
        "api.js does not address one grant by its id"
    )
    # Read as a window after the function's own name rather than as `revokeGrant[^}]*DELETE`, which cannot
    # work: the body contains a template literal, and `${...}` closes the character class on its own brace.
    revoke = api[api.index("export function revokeGrant"):][:400]
    assert re.search(r"method:\s*'DELETE'", revoke), "R-213: revocation is not sent as a DELETE"
    both_languages("grants.title")


def test_the_grant_screen_has_two_ways_in_and_one_of_them_is_the_moment_it_matters():
    """R-170 meets R-210: opening a curator session shares nothing, and that is where a member finds out.

    Two entrances, and the second is the substantive one. The settings door is where the consent history,
    the export and the erasure already live (A86's argument about findability). The Know panel's is the
    join that closes A90's finding as an *experience* rather than as a route: a member presses Curator, a
    consultation is recorded, and the curator on the other end still sees nothing — so the confirmation
    says so and offers the door.

    **Planted violation, twice:** removed the link from `settings.js` (failed), and removed the sentence and
    the link from `know.js`'s success notice (failed naming that file). Both restored.
    """
    settings = code("surfaces/settings.js")
    assert re.search(r"href:\s*'#/grants'", settings), "the settings screen does not link to the grants"
    assert "settings.grants_heading" in settings
    both_languages("settings.grants_heading")

    panel = code("surfaces/know.js")
    assert "know.curator_sees_nothing" in panel, (
        "the Know panel confirms a curator session without saying that nothing is shared by it"
    )
    assert re.search(r"href:\s*'#/grants'", panel), (
        "the panel says a curator sees nothing and offers no way to change that"
    )
    both_languages("know.curator_sees_nothing")


@pytest.mark.parametrize("key,substance", [
    ("grants.scoped", ("einzelne Bereiche", "individual areas")),
    ("grants.time_limited", ("festen Zeitpunkt", "fixed time")),
    ("grants.immediate", ("diesem Moment", "that moment")),
])
def test_the_screen_makes_r210_and_r213_plain_before_any_control(key, substance):
    """The three facts the screen exists to state: **what**, **for how long**, and that revoking is instant.

    Checked as three things at once, because any of them can be present as a key and absent as a sentence:
    the key is rendered by `grants.js`, it is defined in both languages, and each language's text actually
    carries the substance rather than a heading that gestures at it.

    **Planted violation, three times:** replaced `grants.immediate` with "Der Zugang kann entzogen werden."
    — true, and it drops *immediate*, which is R-213's whole word. Failed on the substance. Then deleted the
    key (failed on the definition), then removed its render from `grants.js` (failed on the render). All
    restored.
    """
    surface = code("surfaces/grants.js")
    assert f"t('{key}'" in surface, f"{key} is defined and never rendered"
    both_languages(key)
    german, english = strings("de")[key], strings("en")[key]
    assert substance[0] in german, f"the German {key} does not say {substance[0]!r}: {german}"
    assert substance[1] in english, f"the English {key} does not say {substance[1]!r}: {english}"


#: Words that would describe a state the route does not have. R-213 commits on the request: `revoke_grant`
#: sets the timestamp, `is_live` consults it before `expires_at`, and the curator's next read is refused.
#:
#: **Scoped to the `grants.*` copy on purpose (A95).** `grants.no_pending` is a sentence *denying* every one
#: of these, and a scan over the whole table would fire on it — the exact shape A95 records, where a blunt
#: filter refuses the sentence that states the rule.
_PENDING_WORDS_DE = ("beantragt", "wird bearbeitet", "in bearbeitung", "ausstehend", "demnächst",
                     "wird wirksam", "wird geschlossen", "wird entzogen", "wird erteilt")
_PENDING_WORDS_EN = ("pending", "requested", "will be", "shortly", "is being", "awaiting")


@pytest.mark.parametrize("language,words", [("de", _PENDING_WORDS_DE), ("en", _PENDING_WORDS_EN)])
def test_the_grant_screen_implies_no_state_the_route_does_not_have(language, words):
    """R-213 is *immediate*, so nothing on this screen may read as a request that has yet to take effect.

    A member who expects an approval step would keep the screen open looking for one, and — worse — would
    have no reason to believe the withdrawal they just made has happened. So the copy says *is withdrawn*,
    never *will be*.

    The one sentence that names these concepts is the one that denies them, and it is excluded by name
    rather than by hoping the scan misses it.

    **Planted violation:** changed `grants.revoked_announced` to "Der Entzug wird bearbeitet." Failed naming
    the key and the phrase. Restored.
    """
    table = strings(language)
    offenders = []
    for key, value in table.items():
        if not key.startswith("grants."):
            continue
        low = value.lower()
        for word in words:
            if word in low:
                offenders.append(f"{key}: {word!r} in {value[:70]}")
    assert not offenders, (
        "R-213 takes effect on the request; this copy describes a state that does not exist:\n  "
        + "\n  ".join(offenders)
    )
    # A20. The scan above is an empty list both when the copy is clean and when the word list has rotted
    # away, so it is run once against a sentence that should fail it.
    #
    # **There is no exemption list here, and there was one in the first draft.** `grants.no_pending` is the
    # sentence that denies every one of these concepts, so A95 says to expect it to trip a blunt scan — and
    # it does not, because it denies them without naming them ("keine Wartezeit, keine Freigabe durch
    # Dritte"). An exemption for a key that does not need one is a hole nobody would notice opening, so it
    # was removed and this probe stands in its place.
    probe = {"de": "Der Entzug wird bearbeitet.", "en": "The withdrawal is pending."}[language]
    assert any(word in probe.lower() for word in words), (
        f"the {language} pending-word list no longer catches {probe!r}, so the scan above cannot fail"
    )


def test_the_scope_vocabulary_is_read_from_the_route_and_never_written_here():
    """R-210's scope is an explicit list drawn from `GRANTABLE`, and a name this client invented would be a
    name nothing checks — which `services/curator.py` says is indistinguishable from full access.

    So `grants.js` builds the label key from the name the payload gave it, and every name the server can
    send has a word in both languages. **A name with no word must render as itself**, which is why the
    lookup falls back rather than dropping: an unlabelled scope is a translation gap, a silently dropped one
    is a member consenting to something invisible.

    **Planted violation, twice:** hardcoded the five names as an array in `grants.js` (failed on the
    literal); deleted `grants.scope_vault` from the English block (failed naming the missing string). Both
    restored.
    """
    surface = code("surfaces/grants.js")
    assert re.search(r"grants\.scope_\$\{name\}", surface), (
        "the scope label is not looked up from the name the payload sent"
    )
    for name in GRANTABLE:
        assert f"'{name}'" not in surface, (
            f"grants.js writes the scope name {name!r} as a literal; the list comes from "
            "GET /api/curator/grantable so that a name nothing checks cannot be offered"
        )
        both_languages(f"grants.scope_{name}")
    assert "scopeLabel(" in surface, "the scope label lookup has gone"
    assert re.search(r"word === key \? name : word", surface), (
        "the label lookup no longer falls back to the scope's own name, so a scope the server adds would "
        "disappear from the screen instead of appearing unlabelled"
    )


def test_nothing_on_the_grant_form_is_chosen_for_the_member():
    """A86's fourth defect, on the one form where the inference would be eigentliCH deciding which of a
    member's material a named person may read.

    A default is an inference — the quietest kind, because nobody sees it happen. So: both placeholder
    options carry no value and come first, and no checkbox is rendered with `checked`.

    **Planted violation, twice:** gave every scope box `checked: ''` (failed here and, after the assertion
    was repaired, in the live run); deleted the curator placeholder option so the first real curator was
    selected (failed on the placeholder). Both restored.
    """
    surface = code("surfaces/grants.js")
    options = re.findall(r"h\('option',\s*\{\s*value:\s*'([^']*)'", surface)
    assert len(options) >= 2, f"the placeholder options have moved: {options}"
    assert all(value == "" for value in options), (
        f"a grant form option carries a value and is therefore preselected: {options}"
    )
    assert "grants.choose_curator_none" in surface and "grants.choose_window_none" in surface
    assert not re.search(r"checked:\s*", surface), (
        "a scope checkbox is rendered pre-ticked; the member has not chosen it"
    )


def test_the_grant_form_asks_again_rather_than_showing_a_constraint_name():
    """Three refusals the screen makes on its own, before anything is sent.

    Not the enforcement — the route refuses an empty scope, an unknown scope and a window of no time — but
    the difference between being asked a question again and reading "a grant lasting no time is a refusal
    wearing a grant's clothes", which is the server's sentence and not one for a member.

    **Planted violation:** replaced the empty-scope check with `if (false)`. The submit went through, the
    server answered 422 with its own wording, and this failed on the missing check. Restored.
    """
    surface = code("surfaces/grants.js")
    assert re.search(r"if\s*\(!curatorSelect\.value\)", surface), "a grant with no curator is sent"
    assert re.search(r"if\s*\(!chosen\.length\)", surface), "a grant with no scope is sent"
    assert re.search(r"if\s*\(!windowSelect\.value\)", surface), "a grant with no window is sent"
    for key in ("grants.no_curator_chosen", "grants.no_scope_chosen", "grants.no_window_chosen"):
        assert key in surface
        both_languages(key)


def test_no_window_offered_to_a_member_is_endless():
    """R-210 "time-limited": every window ends, and the server's own published default is always among the
    choices so this client cannot contradict it.

    **Planted violation:** added `0` to `OFFERED_WINDOWS` (a grant of no time, which the route refuses) and
    then `null`. Failed on the positivity check. Restored.
    """
    surface = code("surfaces/grants.js")
    offered = re.search(r"OFFERED_WINDOWS\s*=\s*\[([^\]]*)\]", surface)
    assert offered, "OFFERED_WINDOWS has moved"
    hours = [value.strip() for value in offered.group(1).split(",") if value.strip()]
    assert hours, "no window is offered at all"
    assert all(re.fullmatch(r"\d+", value) and int(value) > 0 for value in hours), (
        f"a window that is not a positive number of hours is offered: {hours}"
    )
    assert "default_lifetime_hours" in surface, (
        "the server's published default is not folded into the offered windows, so this list can come to "
        "contradict the route"
    )
    assert not re.search(r"unbegrenzt|unlimited|for ?ever|kein Ende", surface, re.IGNORECASE)


def test_the_outcome_is_announced_after_the_screen_behind_it_has_settled():
    """A86 found this on the language switch, A94 found it again on the capability form, and the live run
    found it a third time here — each time by running the client rather than by reading it.

    Every surface announces itself when it finishes loading. `onChanged` re-reads and re-renders, so
    announcing the outcome *first* puts it into `#live` and has it overwritten milliseconds later: a member
    using a screen reader hears the screen name and never hears that their access was withdrawn.

    Held as an ordering inside each handler, which is the property. The live harness holds the symptom.

    **Planted violation:** swapped the two lines in the revoke handler. The live run failed with
    `got "Zugang für Kuratoren geladen."`; this failed on the ordering. Restored.
    """
    for name in ("surfaces/grants.js", "surfaces/community.js"):
        surface = code(name)
        pairs = re.findall(r"await onChanged\(\);\s*announce\(", surface)
        assert pairs, f"{name} does not await the re-read before it announces"
        stray = re.findall(r"announce\([^;]*\);\s*await onChanged\(\)", surface)
        assert not stray, (
            f"{name} announces before the screen behind it has settled; the screen's own announcement "
            "overwrites it and the member hears the wrong thing"
        )


def test_nothing_in_the_client_keeps_a_grant():
    """R-213's word is *immediate*, and a grant read once and kept is a grant that outlives its withdrawal.

    `app/curator.js` states the same discipline from the curator's side. This is the member's: the surface
    holds no mutable module state, and the router's `onChanged` calls the screen again — which re-runs
    `load()` — rather than patching what is on screen.

    **Planted violation:** cached the payload in a module-level `let held = null` in `grants.js` and served
    it back. Failed on the module state. Restored.
    """
    surface = code("surfaces/grants.js")
    module_level = re.findall(r"^(?:let|var)\s+(\w+)", surface, re.MULTILINE)
    assert not module_level, (
        f"grants.js holds mutable module state {module_level}; a grant kept between draws is a grant that "
        "outlives its withdrawal"
    )
    router = code("app/main.js")
    body = re.search(r"async function renderGrants\s*\([^)]*\)\s*\{(.*?)\n\}", router, re.DOTALL)
    assert body, "renderGrants has moved"
    assert "grants.load()" in body.group(1), "the grant screen does not re-read when it changes"
    assert "onChanged: renderGrants" in body.group(1), (
        "a change patches the screen instead of re-reading; a lapsed grant would sit there looking live"
    )


# ============================================================ S-11 — the Market Place


def test_the_market_place_replaced_the_placeholder_and_the_placeholder_is_gone():
    """The route said "Noch nicht gebaut." in front of `services/marketplace.py`.

    **`renderPlaceholder` is deleted rather than left unused**, and that is the substantive half: a
    placeholder renderer with no callers makes "route it to a placeholder for now" a one-line change, and
    `ROUTES[name] || ROUTES.plan` already means an absent route falls through to the grid rather than to a
    claim that a screen does not exist.

    **Planted violation, twice:** pointed `market` back at a placeholder function (failed on both
    assertions); removed the market door from `index.html` (failed naming it). Both restored.
    """
    router = code("app/main.js")
    assert re.search(r"\bmarket:\s*renderMarket\b", router), "the market door is a placeholder again"
    assert "renderPlaceholder" not in router, (
        "renderPlaceholder is back; a placeholder renderer with no callers is an invitation"
    )
    index = INDEX.read_text(encoding="utf-8")
    assert re.search(r'<a href="#/market"[^>]*data-route="market"[^>]*class="door"', index)
    assert 'data-i18n="chrome.door_market"' in index
    for language in ("de", "en"):
        table = strings(language)
        assert "door.market_body" not in table, "the placeholder's copy is back in the string table"
        for value in table.values():
            assert "Noch nicht gebaut" not in value and "Not built yet" not in value


def test_the_market_screen_never_puts_the_entries_in_an_order_of_its_own():
    """**C-08, and this file is where ordering would be sold.**

    The order arrives decided: `ordering_key` is handed three integers and an opaque tiebreak and can reach
    nothing else, and `_in_order` is the only `sorted` call in the service. A client-side sort moves the
    decision out of a guarded function into an unguarded one, which is C-08 defeated without a line of the
    service changing.

    **Planted violation:** sorted `entries` by title before rendering. The live run failed with the payload
    order and the screen order printed side by side; this failed on the `sort` call. Restored.
    """
    surface = code("surfaces/market.js")
    for banned in (".sort(", ".reverse(", "localeCompare("):
        assert banned not in surface, (
            f"market.js calls {banned}; the ordering arrives decided and this client may not have an "
            "opinion about it (C-08)"
        )
    assert re.search(r"const entries = listings\.entries \|\| \[\];", surface), (
        "the entries are no longer taken from the payload as they arrived"
    )
    assert "entries.map(" in surface, "the entries are not rendered in payload order"


#: What a screen would say if placement were for sale. None of it is in the payload and none of it may be
#: in this surface or in its copy.
#
#: **Two words are deliberately absent, and the reason is A95's.** Bare `anzeige` fires on
#: `Kontaktweg anzeigen` — "show the way to get in touch" — which is the R-004 control this screen exists
#: to offer, and bare `empfohlen` is an ordinary German participle. The phrases that actually mean paid
#: placement are listed instead: a filter that fires on ordinary prose gets deleted.
_PLACEMENT_WORDS = (
    "featured", "sponsored", "sponsor", "promoted", "premium", "boost", "priority", "placement",
    "advert", "werbung", "werbeanzeige", "gesponsert", "bezahlte platzierung", "hervorgehoben",
    "top-treffer", "bestes angebot", "unsere empfehlung",
)


def test_nothing_on_the_market_screen_implies_paid_placement():
    """C-08 as what a member reads, not only as what the service computes.

    A screen that *looked* like an advertising rank would make the guarantee worthless however true it
    stayed underneath. Scoped to `market.js` and the `market.*` copy, because "empfohlen" is an ordinary
    German word that appears in other contexts and a whole-table scan would be the A95 shape.

    **Planted violation:** added `'market.featured': 'Unsere Empfehlung'` and rendered it on the first card.
    Failed naming both. Removed.
    """
    surface = code("surfaces/market.js").lower()
    for word in _PLACEMENT_WORDS:
        assert word not in surface, f"C-08: market.js contains {word!r}"
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith("market."):
                continue
            low = value.lower()
            for word in _PLACEMENT_WORDS:
                assert word not in low, f"C-08: {language}/{key} contains {word!r} — {value[:70]}"


def test_no_number_from_the_ordering_reaches_the_screen():
    """R-221 and C-07 where a "relevance" figure looks harmless.

    The three inputs are **named** so a member can read the list as something other than an advertising
    rank. None of them is given a figure: a rendered share would be a standing number beside a supplier,
    and attendance in particular may never be shown back to a member at all.

    **Planted violation:** rendered `entry.role_match` beside each title — a field the payload does not even
    carry, which is the point: nothing stops a client computing one. Failed on the field name. Restored.
    """
    surface = code("surfaces/market.js")
    # **A property access, not the bare word.** `inputs.includes('role_match')` is how the screen decides
    # whether to print A74's sentence about the share — it reads a *name* out of `ordering_inputs`, which is
    # the opposite of rendering a figure. The first form of this test banned the substring and failed on
    # exactly that line: a guard aimed at a number that fires on the name is the A95 shape.
    for field in ORDERING_INPUT_NAMES:
        assert f".{field}" not in surface, (
            f"market.js reads the value of {field!r}; the ordering's inputs are named on screen, never "
            "given a figure"
        )
    for field in ("standing_inputs", "ordering_key", "tiebreak", "ROLE_MATCH_SCALE"):
        assert field not in surface, f"market.js reaches into the ordering's machinery through {field!r}"
    for name in ORDERING_INPUT_NAMES:
        both_languages(f"market.ordering_input_{name}")


def test_every_listing_displays_its_disclosures_rather_than_offering_to():
    """**R-202: displayed, not on request.** "Displays its disclosures" and "offers to show its
    disclosures" are different promises and only one of them is the requirement.

    A `<details>` element is the most natural way to keep the card short and it is the one shape this may
    not take. And an empty list is rendered as the broken promise it would be — `publish` refuses a listing
    with no disclosure, so a published listing carrying none is a fact about the listing, not a gap for the
    screen to leave silent.

    **Planted violation, twice:** replaced the disclosures node with `null` (the live run failed on both the
    screen text and the per-card check; this failed on the call); wrapped it in a `<details>` toggle (failed
    on the element). Both restored.
    """
    surface = code("surfaces/market.js")
    listing = re.search(r"function listingNode\([^)]*\)\s*\{(.*?)\n\}", surface, re.DOTALL)
    assert listing, "listingNode has moved"
    assert "disclosuresNode(entry.disclosures" in listing.group(1), (
        "R-202: a listing card no longer displays its disclosures"
    )
    node = re.search(r"function disclosuresNode\([^)]*\)\s*\{(.*?)\n\}", surface, re.DOTALL)
    assert node, "disclosuresNode has moved"
    for hiding in ("'details'", "'summary'", "aria-expanded", "hidden"):
        assert hiding not in node.group(1), (
            f"R-202: the disclosures are behind {hiding}, which makes them available rather than displayed"
        )
    assert "market.disclosures_absent" in node.group(1), (
        "a listing with no disclosure renders a silent gap; R-202's broken promise has to be legible"
    )
    both_languages("market.disclosures_absent")


def test_the_filter_is_removable_by_the_name_the_payload_prints():
    """R-201. The payload carries `remove_by` precisely so a client sends the name it prints back.

    `services/marketplace.py` says the block exists so that "the filter is visible and removable" is a
    promise about the payload rather than about a button somebody remembers to build. Taking that at its
    word means the removal literal appears nowhere in this client.

    **Planted violation:** replaced `block.remove_by.value` with the literal `'all'`. Failed on the
    literal. Restored.
    """
    surface = code("surfaces/market.js")
    assert "remove_by" in surface, "the removal is not read from the payload"
    assert f"'{NO_FILTER}'" not in surface, (
        f"market.js writes the filter-removal value {NO_FILTER!r} as a literal instead of reading it from "
        "`filter.remove_by`, so the name it sends and the name it prints can drift"
    )
    assert f"'{FILTER_PARAMETER}'" in code("app/main.js") or FILTER_PARAMETER in code("app/main.js"), (
        "the router does not carry the role filter in the hash"
    )
    for key in ("market.filter_from_grid", "market.filter_chosen", "market.filter_removed",
                "market.filter_grid_empty", "market.filter_remove"):
        assert key in surface, f"{key} is defined and never rendered"
        both_languages(key)


def test_a_member_offer_is_a_peer_of_a_provider_listing():
    """R-205. One list, one ordering function, one card treatment — not two sections, which is the
    "beneath" R-205 forbids drawn in layout instead of in code.

    **Planted violation:** rendered the member offers in a second `.grid` below the listings. Failed on the
    single list. Restored.
    """
    surface = code("surfaces/market.js")
    assert surface.count("class: 'cell listing'") == 2, (
        "the two entry kinds no longer share one card treatment"
    )
    for kind in ENTRY_KINDS:
        both_languages(f"market.kind_{kind}")
    assert re.search(r"entries\.map\(\(entry\) => entryNode\(", surface), (
        "the entries are not rendered through one function, so the two kinds can drift apart"
    )
    assert surface.count("class: 'grid market-entries'") == 1, (
        "R-205: there is more than one list, so member offers sit somewhere other than alongside"
    )


def test_the_application_holds_no_copy_of_r204s_pipeline_rule():
    """R-204 makes the pipeline a *declaration* and the server refuses a mismatch. A client that wrote the
    domain-to-pipeline mapping out would be holding a second copy of a server rule — the A73 shape, which
    this build has paid for three times.

    It is derived from the listings the market place is already serving, which cannot contradict the server
    because it is the server's own data. The cost is stated on screen: a domain with no published listing
    cannot be offered.

    **Planted violation:** wrote `{financial: 'capability', health: 'professional_registration', ...}` as a
    constant. Failed naming the pipeline literal. Restored.
    """
    surface = code("surfaces/market.js")
    assert "function pipelinesByDomain(" in surface, "the pipeline is no longer derived from the payload"
    # **Every mention of a pipeline name must be a comparison**, never a value being assigned or a key in a
    # map. A comparison asks "which of the two did the data say"; an assignment decides it here, which is
    # the copy of R-204's rule this test exists to prevent. Counting occurrences was the first form and it
    # was wrong for a boring reason: the comparison legitimately appears three times.
    for pipeline in PIPELINES:
        for match in re.finditer(re.escape(f"'{pipeline}'"), surface):
            before = surface[max(0, match.start() - 24):match.start()]
            assert re.search(r"(===|!==)\s*$", before), (
                f"market.js uses the pipeline name {pipeline!r} as something other than a comparison: "
                f"...{before.strip()}'{pipeline}'"
            )
    for domain in DOMAINS:
        assert f"'{domain}'" not in surface, (
            f"market.js writes the domain {domain!r} as a literal; the offered domains are read off the "
            "market place's own listings"
        )
        both_languages(f"market.domain_{domain}")
    for pipeline in PIPELINES:
        both_languages(f"market.pipeline_{pipeline}")


def test_the_gate_on_being_listed_is_the_servers_and_the_screen_says_which_one():
    """R-004 and R-005 are opposite promises about one surface, so both are named where the gated one is.

    The form does not pre-empt the 403: a client-side check for capability evidence would be a second copy
    of R-005's rule, drifting. What it does instead is say which evidence the chosen domain's pipeline
    reads, so a refusal is legible rather than surprising.

    **Planted violation:** added a client-side check refusing the submit unless the member held an
    assertion. Failed on the assertion count. Restored.
    """
    surface = code("surfaces/market.js")
    assert "applyToBeListed(" in surface, "there is no way for a member to apply"
    assert "market.apply_only_gate" in surface, "the one gated act is not named as the only one"
    assert "market.not_gated" in surface, "R-004's promise is not stated"
    for probe in ("getCapabilities(", "assertCapability(", "capability_evidence"):
        assert probe not in surface, (
            f"market.js reads {probe!r}; R-005's gate is the server's and a second copy here would drift"
        )
    for key in ("market.apply_gate_capability", "market.apply_gate_registration"):
        assert key in surface
        both_languages(key)
    # R-202's write side, which is the only way a draft becomes a listing.
    assert "declareDisclosure(" in surface and "publishApplication(" in surface
    assert "market.draft_only_here" in surface, (
        "the draft is reachable only from the response that created it and the screen does not say so"
    )


# ============================================================ S-05, S-09, S-13, S-10


@pytest.mark.parametrize("route,handler,surface,nav", [
    ("stages", "renderStages", "surfaces/stages.js", "stages.nav"),
    ("life-events", "renderLifeEvents", "surfaces/life-events.js", "life_events.nav"),
    ("community", "renderCommunity", "surfaces/community.js", "community.nav"),
    ("learning", "renderLearning", "surfaces/learning.js", "learning.nav"),
])
def test_the_four_unrendered_payloads_now_have_a_screen_and_a_way_in(route, handler, surface, nav):
    """`api/remainder.py` and `api/learning.py` served these correctly and no client code called them.

    Checked as the whole join, and the last element is the one that matters most: a route with no link is
    the failure `test_client_surfaces.py` exists for — the Befund had one for a day. Both doors these sit
    behind already **named** what was missing: "Plan & Lebensereignisse" and "Wissen & Gemeinschaft".

    **Planted violation, four times, once per screen:** removed the entry from `ROUTES` (the door fell
    through to the grid) and separately removed the nav entry. Each failed naming the missing half. All
    restored.
    """
    router = code("app/main.js")
    # A route name containing a hyphen has to be a quoted key, so the pattern accepts either form. The first
    # version anchored on `\b` before the name and could never match `'life-events':` — a guard that cannot
    # fire on one of the four things it is parametrised over.
    assert re.search(rf"'?{re.escape(route)}'?:\s*{handler}\b", router), f"no route answers {route}"
    assert re.search(rf"async function {handler}\s*\(", router), f"no handler behind {route}"
    assert len(code(surface)) > 800
    assert nav in router, f"{route} has no link in the navigation, so the screen is unreachable"
    both_languages(nav)


def test_the_stage_map_locks_nothing_and_states_no_position():
    """R-140, R-141 and R-006. A stage describes a situation; it is not a grade and not a place on a scale.

    Three properties: nothing is disabled, the age marker is rendered beside the sentence that denies it is
    a condition, and `opens_at` is rendered beside the payload's own denial that it is a position. The
    marked stage gets the same card as the other four, so the words carry the distinction rather than a
    highlight — which cannot say which of the two things it means.

    **Planted violation, twice:** disabled the stages above the member's `opens_at` (failed on `disabled`);
    dropped `stages.age_marker_not_a_condition` so the number stood alone (failed on the key). Both
    restored.
    """
    surface = code("surfaces/stages.js")
    for locking in ("disabled", "hidden", "aria-disabled"):
        assert locking not in surface, f"R-141: the stage map uses {locking!r}; any stage may be opened"
    assert "age_marker_is_not_an_entry_condition" in surface, (
        "the age marker is rendered without the payload's own denial that it gates anything"
    )
    assert "opens_at_is_not_a_position" in surface, (
        "R-140: where the map opens is rendered without the denial that it says where the member is"
    )
    assert "no_stage_after" in surface, "NG-02 is not stated at the end of the list"
    for key in ("stages.age_marker_not_a_condition", "stages.not_a_position", "stages.all_open",
                "stages.no_stage_after", "stages.no_stage_after_reason"):
        assert key in surface
        both_languages(key)


def test_all_seven_life_event_modules_are_listed_and_say_they_are_unwritten():
    """R-183: the content is authored, so the framework ships empty — and the module is **not hidden**
    because it is empty.

    `life_event_modules`'s own docstring gives the reason: a list that dropped the unauthored ones would be
    an empty screen with no explanation on it, and a member who has just been through a separation would be
    looking at nothing.

    **Planted violation, twice:** filtered the list to `record.authored` (all seven vanished; failed on the
    filter); replaced the unwritten sentence with an empty string (failed on parity, then on the key). Both
    restored.
    """
    surface = code("surfaces/life-events.js")
    # **`[^;]` and not `[^)]`, and that is a guard repaired after it failed to fail.** The first form read
    # `\.filter\([^)]*authored`, which cannot cross the closing paren of an arrow function's parameter list
    # — so planting the one thing this test exists to catch, `.filter((record) => record.authored)`, left it
    # green. Second guard in this file found unable to see the natural way to write the defect.
    assert not re.search(r"\.filter\([^;]{0,120}authored", surface), (
        "R-183: unauthored modules are filtered out, which is an empty screen with no explanation on it"
    )
    assert "life_events.not_written" in surface and "life_events.not_written_why" in surface
    for key in LIFE_EVENT_KEYS:
        both_languages(f"life_events.module_{key}")
    # R-180's four fields are framed whether or not anything is written into them.
    for field in MODULE_FIELDS:
        both_languages(f"life_events.{field}")
        assert f"life_events.{field}" in surface, f"R-180's {field} is not framed on the module"
    assert "life_events.field_unwritten" in surface


def test_nothing_invents_life_event_content():
    """R-183's other half, and it is also C-01: generated content in this position is advice with nobody's
    name on it.

    Every authored field is rendered from the payload and there is no fallback list — the frame is a heading
    and a sentence saying it is unwritten, never a plausible-looking example.

    **Planted violation:** gave `first_steps` a default of one invented step. Failed on the fallback.
    Restored.
    """
    surface = code("surfaces/life-events.js")
    assert re.search(r"authoredField\('life_events\.first_steps', payload\.first_steps", surface)
    assert re.search(r"authoredField\('life_events\.do_not_sign', payload\.do_not_sign", surface)
    fields = re.search(r"function authoredField\([^)]*\)\s*\{(.*?)\n\}", surface, re.DOTALL)
    assert fields, "authoredField has moved"
    assert "|| []" in fields.group(1), "the field reader no longer treats an absent list as absent"
    assert not re.findall(r"\[\s*'[^']{12,}'", fields.group(1)), (
        "authoredField carries a literal list of prose; R-183 ships the frame empty"
    )
    # The two absences the payload was careful to keep apart.
    assert "retrieval_unavailable_reason" in surface
    for key in ("life_events.retrieval_unavailable", "life_events.no_documents"):
        assert key in surface
        both_languages(key)


def test_the_community_screen_never_calls_a_gathering_an_event():
    """R-222, at the only place a member reads the word.

    `models/access.py` names the table `Gathering` and says "the name is the enforcement";
    `services/community.py` refuses a gathering whose own title calls itself one. This is the third place
    the rule has to hold, and the list of words is imported from the service rather than retyped — two
    lists that must agree, maintained separately, is A91's defect.

    **Scoped to `community.js` and the `community.*` copy (A95).** S-09 is `life_events.*`, where the word
    *events* is not only allowed but required: R-222 says that in this interface "events" means LIFE events.

    **Planted violation:** renamed the community heading to "Veranstaltungen". Failed naming the word and
    the key. Restored.
    """
    # **Over the file's own string literals, not over its source.** Every DOM handler in this client takes a
    # parameter called `event` — that is the DOM's name for a click, not the product's name for a lecture,
    # and the first form of this test failed on `onClick: async (event) =>`. What R-222 governs is what the
    # product *says*: the string table keys, the class names and any literal that reaches a screen.
    literals = re.findall(r"'((?:[^'\\]|\\.)*)'", code("surfaces/community.js"))
    joined = " ".join(literals).lower()
    for word in FORBIDDEN_GATHERING_WORDS:
        assert not re.search(r"\b" + re.escape(word) + r"\b", joined), (
            f"R-222: a string in community.js calls a gathering {word!r}"
        )
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith("community."):
                continue
            low = value.lower()
            for word in FORBIDDEN_GATHERING_WORDS:
                assert not re.search(r"\b" + re.escape(word) + r"\b", low), (
                    f"R-222: {language}/{key} calls a gathering {word!r} — {value[:70]}"
                )
    for kind in GATHERING_KINDS:
        both_languages(f"community.kind_{kind}")


def test_attendance_is_a_fact_and_never_a_number():
    """R-221. `attended` per gathering is a fact; a count of them would be a standing.

    Attendance is one of R-203's three ordering inputs, so a number here would be a member's own ranking
    input shown back to them. The payload carries no aggregate; this screen computes none, and says where
    the fact goes instead.

    **Planted violation:** rendered the number of gatherings attended above the list. Failed on the
    interpolated length. Restored.
    """
    surface = code("surfaces/community.js")
    assert not re.search(r"\$\{[^}]*\.length", surface), (
        "R-221: the community screen interpolates a count into its copy"
    )
    assert not re.search(r"\.filter\([^)]*attended[^)]*\)\.length", surface), (
        "R-221: the screen counts the gatherings the member was at"
    )
    assert "attendance_is_not_scored" in surface, "R-221's own flag is not read"
    assert "community.not_a_standing" in surface
    both_languages("community.not_a_standing")
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if key.startswith("community."):
                assert "{n}" not in value, f"{language}/{key} carries a quantity placeholder"


def test_the_community_screen_offers_no_way_to_schedule_one():
    """`POST /api/community/gatherings` exists, takes a session, and its own docstring says the session
    "does not make it staff-only — it stops it being world-writable", with who may call it left as "the
    same open question as every other write route in this prototype".

    A form on a member's screen would answer that question in an interface, which is how a permission gets
    granted without anybody deciding to. So there is no form, `api.js` has no function for the route, and
    the screen says who schedules these instead of leaving a member hunting for a control.

    Attendance is different and *is* offered: the route writes it against the token's member and nobody
    else's, so it is a member recording their own fact.

    **Planted violation:** added `scheduleGathering` to `api.js` and a form to `community.js`. Failed on
    both halves. Removed.
    """
    api = code("app/api.js")
    assert not re.search(r"method:\s*'POST'[^}]*community/gatherings", api, re.DOTALL)
    assert "'/api/community/gatherings'" in api, "the listing route is not reached at all"
    assert api.count("/api/community/gatherings") == 1, (
        "api.js reaches the gatherings route more than once; the second is the write"
    )
    surface = code("surfaces/community.js")
    assert "createGathering" not in surface and "scheduleGathering" not in surface
    assert "community.who_schedules" in surface, (
        "there is no scheduling control and the screen does not say why"
    )
    both_languages("community.who_schedules")


def test_the_learning_path_is_not_a_ladder():
    """R-190, R-192, D-01 and C-07 together.

    Nothing is gated, nothing is ordered, `rung` is null and `rung_scheme_reason` says there is **no**
    scheme rather than that one is pending. The temptation on this surface is not the word "level" — it is a
    row of dots across the top, which is a rung scheme drawn instead of written.

    **Planted violation, twice:** disabled every unit whose prerequisite had unasserted capabilities (failed
    on `disabled`); rendered `entry.evidences.filter(e => e.evidenced).length` beside each unit title
    (failed on the tally). Both restored.
    """
    surface = code("surfaces/learning.js")
    for locking in ("disabled", "aria-disabled"):
        assert locking not in surface, f"R-190: learning.js uses {locking!r}; no unit is gated"
    for banned in (".sort(", ".reverse("):
        assert banned not in surface, f"the units are re-ordered with {banned}; the file order is not a path"
    assert not re.search(r"\.filter\([^)]*evidenced[^)]*\)\.length", surface), (
        "C-07: the screen counts how many statements the member has asserted"
    )
    assert not re.search(r"\$\{[^}]*\.length", surface), "C-07: a count is interpolated into the copy"
    assert re.search(r"rung", surface) is None or "rung_scheme" in surface, (
        "learning.js renders a rung"
    )
    for key in ("learning.no_scheme", "learning.not_gated", "learning.unordered",
                "learning.no_qualification", "learning.self_asserted"):
        assert key in surface
        both_languages(key)


def test_r232s_statement_is_rendered_plainly_to_the_member():
    """R-232: "a plain statement of which data class each stored category falls into". It was shown to
    nobody.

    **Plain, so not behind a disclosure.** A `<details>` would make it available rather than stated, and
    this is the screen where a member decides what to export and what to delete. The assignment comes from
    the server — derived from `__data_class__`, so it cannot go stale — and the sentence explaining what
    each class *means* is interface copy, which is where `services/settings.py` says it belongs.

    **Planted violation, twice:** wrapped the categories in a `<details>` (failed on the element); deleted
    `settings.class_k3` (failed naming the missing class). Both restored.
    """
    surface = code("surfaces/settings.js")
    assert "getDataClasses(" in surface, "R-232's statement is fetched by nobody again"
    assert "'/api/settings/data-classes'" in code("app/api.js")
    section = re.search(r"function dataClassesSection\([^)]*\)\s*\{(.*?)\n\}\n", surface, re.DOTALL)
    assert section, "dataClassesSection has moved"
    for hiding in ("'details'", "'summary'", "aria-expanded", "hidden"):
        assert hiding not in section.group(1), (
            f"R-232: the statement is behind {hiding}, which makes it available rather than plain"
        )
    for member in DataClass:
        both_languages(f"settings.class_{member.name.lower()}")
    assert "fields_classified_above_the_row" in surface, (
        "C-04's per-field override is not reported, so a category with a field above its row reads as if "
        "it had none"
    )
    assert "top_class_never_leaves_the_server" in surface


# ============================================================ the accessibility contract


#: The class names the accessibility suite already covers. Derived from its own list rather than retyped,
#: so the two cannot drift — the whole point of A91's one-vocabulary fix.
_COVERED = frozenset(
    selector.lstrip(".") for selector in INTERACTIVE_SELECTORS if selector.startswith(".")
)

#: Where one element's attributes end and the next element's begin.
_NEXT_ELEMENT = re.compile(r"h\('|\bbutton\(")


def test_the_new_surfaces_introduce_no_interactive_treatment_the_suite_does_not_cover():
    """Every new control is `.add`, `.primary` or `.consent-box`, or a field inside `.position-form`.

    All four already carry their 44px narrow target and a focus rule of their own, and
    `test_every_interactive_selector_has_a_focus_rule_of_its_own` holds them. A seventh button treatment is
    where a new hue and an unreachable tap target arrive together — A70's finding, which
    `test_the_language_switch_reuses_the_existing_button_treatment` pins one control further out.

    **The covered set is read from the accessibility suite's own list**, so a control added here without a
    focus rule there fails, and a selector removed there fails here.

    **Planted violation:** gave the grant form's submit `class: 'grant-submit'`. Failed naming the class and
    the file. Restored.
    """
    # **Read as a bounded window of lines, not as a regex over the attribute object.** The first form
    # matched `\{(.*?)\}` with DOTALL, and every one of these calls has an `onClick: async (event) => { … }`
    # inside its attributes — so the lazy match stopped at the arrow function's brace and then swept up the
    # next `class:` it found several nodes later. It reported `field-label` as a button's class, which is
    # nowhere near true. The attributes in this client are written one per line, so the window is exact.
    control = re.compile(r"(?:h\('(button|a|input|select|textarea|summary|details)',|\bbutton\()")
    # The boundary is **any** element, not only an interactive one: a classless `<input>` followed by
    # `h('label', { class: 'field' }` would otherwise borrow the label's class, and `label` is not in the
    # list above. That is the same bug twice, one element wider.
    offenders = []
    found = 0
    for name in NEW_SURFACES:
        surface = code(name)
        creates_field = "class: 'position-form'" in surface
        lines = surface.splitlines()
        for index, line in enumerate(lines):
            match = control.search(line)
            if not match:
                continue
            found += 1
            tag = match.group(1) or "button"
            # The window ends where the next element begins. Without that cut, a classless `<input>` whose
            # very next line is `h('label', { class: 'field' }, [` borrows the label's class — which the
            # second form of this test duly reported as an input's treatment. One element's attributes are
            # exactly the lines between its own marker and the next one.
            window_lines = [lines[index]]
            for following in lines[index + 1:index + 8]:
                if _NEXT_ELEMENT.search(following):
                    break
                window_lines.append(following)
            classes = re.findall(r"class:\s*'([^']*)'", "\n".join(window_lines))
            if not classes:
                # A field with no class of its own is reached through `.position-form input|select|textarea`,
                # which the suite lists. Anything else with no class has no focus rule at all.
                if tag in ("input", "select", "textarea") and creates_field:
                    continue
                offenders.append(f"{name}:{index + 1} <{tag}> with no class")
                continue
            for token in classes[0].split():
                if token not in _COVERED:
                    offenders.append(f"{name}:{index + 1} <{tag}> class {token!r}")
    assert found >= 20, f"only {found} controls were found across six screens; the scan is broken"
    assert not offenders, (
        "these controls use a treatment the accessibility suite does not cover, so they have no focus rule "
        "and no narrow-layout target: " + "; ".join(sorted(set(offenders)))
    )


def test_the_covered_set_is_not_empty():
    """A20 on the test above: an empty `_COVERED` would fail everything and an empty `NEW_SURFACES` would
    pass everything. Both are asserted rather than assumed."""
    assert "add" in _COVERED and "primary" in _COVERED and "consent-box" in _COVERED
    assert len(NEW_SURFACES) == 6


def test_every_new_list_and_card_class_is_styled():
    """A class with no rule is a card with no gap between it and the next one.

    Every class this pass invented for a container or a card is asserted to appear in `app.css`. Not a style
    review — a check that the six new screens were not left to inherit the grid's hairlines with nothing
    else.

    **Planted violation:** removed the `.grants` rule from `app.css`. Failed naming the class. Restored.
    """
    sheet = (CLIENT / "style" / "app.css").read_text(encoding="utf-8")
    for name in ("grants", "grant", "market-filter", "market-ordering", "market-entries",
                 "market-apply", "listing", "disclosures", "disclosure", "draft", "stage",
                 "stage-map", "life-event", "life-event-list", "life-event-entry", "gathering",
                 "gathering-list", "learning-unit", "learning-units", "learning-exit",
                 "learning-exits", "data-classes"):
        assert f".{name}" in sheet, f"the class .{name} is used by a surface and styled nowhere"
