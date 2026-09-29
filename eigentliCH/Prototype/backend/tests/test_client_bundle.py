"""C-05 and the client-side half of C-07 and R-143.

`test_authenticated_bundle_makes_no_cross_origin_request` was an xfail through phase 1 because there was
no bundle. There is one now, so it is a real test.

**Checked statically rather than by running a browser.** A headless run would prove that *this* page load
made no external request; a scan proves the source contains nothing that could. For a constraint about
who the data controller is, the second is the stronger claim — it fails when someone adds a font link,
not when someone happens to exercise the code path that fetches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parent.parent.parent / "client"

#: Files a member's browser actually loads. `reference/` and `submissions/` are not served.
BUNDLE_DIRS = ("app", "surfaces", "style")
BUNDLE_FILES = ("index.html", "status.html")


def _bundle_paths() -> list[Path]:
    paths = [CLIENT / name for name in BUNDLE_FILES if (CLIENT / name).exists()]
    for folder in BUNDLE_DIRS:
        paths.extend(sorted((CLIENT / folder).rglob("*")))
    return [p for p in paths if p.is_file()]


def _bundle_text() -> dict[str, str]:
    return {str(p.relative_to(CLIENT)): p.read_text(encoding="utf-8") for p in _bundle_paths()}


def _member_facing(text: str) -> str:
    """Strip comments. A comment explaining why a word is forbidden must not trip the check for it."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return text.lower()


def test_the_bundle_is_not_empty():
    """A vacuous scan passes. Assert there is something to scan — see A20 on filters that cannot fail."""
    files = _bundle_text()
    assert len(files) >= 6, f"expected a real client bundle, found {sorted(files)}"


#: Anything that would reach another origin. `//` catches protocol-relative URLs, which are the form most
#: likely to be pasted in from a snippet without anyone noticing.
EXTERNAL_URL = re.compile(r"""(?:https?:)?//(?!\s)[a-z0-9.-]+\.[a-z]{2,}""", re.IGNORECASE)

#: Same-origin comment references are fine; these are the hosts that would make it a real request.
ALLOWED_SUBSTRINGS = (
    "app.notion.com",      # a provenance note in a comment, not a fetch
    "sim-research.ch",     # schema $id, likewise
    "json-schema.org",
)


@pytest.mark.parametrize("name", sorted(_bundle_text()))
def test_authenticated_bundle_makes_no_cross_origin_request(name):
    """C-05: no external network calls from authenticated pages. Self-host fonts."""
    text = _bundle_text()[name]
    offenders = []
    for match in EXTERNAL_URL.finditer(text):
        url = match.group(0)
        if any(allowed in url for allowed in ALLOWED_SUBSTRINGS):
            continue
        # A URL inside a line comment is documentation, not a request. Anything in an href/src is not.
        line = text[text.rfind("\n", 0, match.start()) + 1 : text.find("\n", match.end())]
        if re.search(r"(href|src|url\(|@import|fetch\(|from\s+['\"])", line, re.IGNORECASE):
            offenders.append(f"{name}: {line.strip()[:120]}")
    assert not offenders, "C-05: the authenticated bundle reaches another origin:\n" + "\n".join(offenders)


def test_no_font_service_is_referenced():
    """C-05 names 'fonts-with-logging' explicitly. System stacks only.

    Comments are stripped first. `index.html` explains *why* there is no font link, and naming the host in
    that explanation must not be the thing that fails the test — the same trap as A20.
    """
    joined = " ".join(_member_facing(t) for t in _bundle_text().values())
    for host in ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit", "fonts.bunny.net"):
        assert host not in joined, f"C-05: {host} is referenced by the authenticated bundle"


def test_no_analytics_or_tag_manager():
    joined = " ".join(_member_facing(t) for t in _bundle_text().values())
    for marker in ("googletagmanager", "google-analytics", "gtag(", "segment.com", "hotjar", "sentry.io",
                   "plausible.io", "matomo", "fullstory", "logrocket"):
        assert marker not in joined, f"C-05: {marker} is referenced by the authenticated bundle"


def test_client_uses_no_innerhtml():
    """Not a spec constraint — a consequence of one.

    A member's position label is text they typed. `innerHTML` anywhere in this client would make it markup,
    and the vault (K3) is one phase away. Cheaper to forbid the method than to audit every call site.

    Comments stripped, for the same reason as the font test above: `dom.js` documents that it does not use
    innerHTML, and saying so must not count as using it.
    """
    offenders = [
        name for name, text in _bundle_text().items()
        if name.endswith(".js") and "innerhtml" in _member_facing(text)
    ]
    assert not offenders, f"the client uses innerHTML in {offenders}; build nodes instead"


# The client half of R-143 and C-07 reads the SAME tuples as the server half. This block used to be
# two shorter literals under a comment saying "matching the backend's list", which was false: it
# omitted `hut`, `berg` and `tour`, and its gamification list was missing `points`, `punkte`,
# `score`, `badge`, `rang` and `xp`. Nothing was leaking, because every occurrence in the client
# sat inside a comment and both scanners strip comments — luck, not a guarantee.
from vocabulary import GAMIFICATION_WORDS, MOUNTAIN_WORDS  # noqa: E402


def test_no_mountain_vocabulary_in_the_client():
    """R-143. The metaphor belongs in the marketing surfaces, never in the authenticated product."""
    for name, text in _bundle_text().items():
        body = _member_facing(text)
        found = [w for w in MOUNTAIN_WORDS if re.search(r"\b" + re.escape(w) + r"\b", body)]
        assert not found, f"R-143: {name} uses {found}"


def test_no_gamification_vocabulary_in_the_client():
    """C-07 as interface, not only as schema."""
    for name, text in _bundle_text().items():
        body = _member_facing(text)
        found = [w for w in GAMIFICATION_WORDS if re.search(r"\b" + re.escape(w) + r"\b", body)]
        assert not found, f"C-07: {name} uses {found}"


def test_no_completion_meter_vocabulary_in_the_client():
    """R-113. No "3 of 8 filled", in either language.

    The payload does not carry the numbers, but a client could still count the array it was given. This
    checks the copy that would have to exist for anyone to render the result.
    """
    for name, text in _bundle_text().items():
        body = _member_facing(text)
        for phrase in ("of 8", "von 8", "of eight", "von acht", "% complete", "abgeschlossen von",
                       "progress", "fortschritt", "vollständigkeit"):
            assert phrase not in body, f"R-113: {name} contains {phrase!r}"


# ============================================================ A11 at the client edge
#
# Wired 31 August 2026. The server half is `tests/test_api_auth.py`; these are the four claims that are
# only true if the *client* is also right, and each one is a property a refactor could quietly undo.


def _named() -> dict[str, str]:
    """The bundle keyed by posix-style path.

    `_bundle_paths` yields a Windows separator on Windows and a forward slash elsewhere, and a test that
    only ran on one of the two is not a test.
    """
    return {name.replace("\\", "/"): text for name, text in _bundle_text().items()}


def _strip_js_comments(text: str) -> str:
    """Comments out, **case kept**.

    Deliberately not `_member_facing`, which also lowercases: that helper exists for word filters over
    copy, and using it to look for `applyChrome` finds `applychrome` and nothing. The checks below are
    about identifiers, so they need the source as written — with the comments gone, because every one of
    these files explains in prose what it deliberately does not do, which is the A20 trap.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)


def _code(name: str) -> str:
    return _strip_js_comments(_named()[name])


def test_the_client_sends_no_member_id_anywhere():
    """A11's substantive half, on this side of the wire.

    The server no longer accepts `member_id` from a caller, so a client still sending one would be
    sending a field that is ignored — harmless today and exactly the thing someone re-wires the day a
    route grows the parameter back. Removing it from both ends at once is what makes the parameter gone
    rather than deprecated.

    `memberId` as a local variable is fine and still occurs: `vault.js` puts it in the export's filename
    and `know.js` uses it to decide whether the panel has anybody to talk about. So is *reading*
    `payload.member_id` off a response — `session.js` does exactly that, because `member_id` is what the
    server calls the field it returns. What may not occur is the wire name going the other way: an object
    key, a quoted key, or a query parameter.

    **Planted violation, three times:** `member_id: memberId` back into `position-form.js`'s payload;
    `new URLSearchParams({ member_id: id })` in `api.js`; and `'member_id'` as a quoted key. Each failed
    with the file named. All removed.

    **One occurrence is argued for rather than banned, and it is named here.** A40's curator routes are
    addressed *by* member id — `/api/curator/members/{member_id}` — and `POST
    /api/curator/workbench/sessions` takes the member in its body, because the caller is a curator and not
    that member. A11's rule is that *which member is asking* comes from the token; a curator asking about a
    member is a different sentence, and `services/curator.py` refuses it without a live scoped grant
    (R-210). `test_no_guarded_route_accepts_a_member_id_from_the_caller` already records the same exception
    on the server side.

    So the ban stays absolute for every module except `app/api.js`, which is allowed **exactly one**
    occurrence, and the test then checks that the one is inside `openWorkbenchSession`. A blanket file
    exemption would have let a second one in beside it; naming the function is what keeps this a guard.

    **Planted violation, twice more:** `member_id: memberId` added to `openSession`'s payload in `api.js`
    (failed on the count: two occurrences where one is allowed), and the body of `openWorkbenchSession`
    replaced with a call that sent no member at all while a stray `member_id:` was left elsewhere in the
    file (failed on the occurrence not being in that function). Both restored.
    """
    #: An object key, a quoted key, or a query parameter. `.member_id` — reading the field off a
    #: response — is deliberately not matched, and a bare word-boundary match would catch it.
    sending = re.compile(r"""(?<![.\w])member_id\s*[:=]|['"]member_id['"]""")
    offenders = [name for name, text in _named().items()
                 if name.endswith(".js") and name != "app/api.js"
                 and sending.search(_strip_js_comments(text))]
    assert not offenders, (
        f"A11: these client modules still put a member id on the wire: {offenders}. The member is the "
        "token's; see client/app/api.js."
    )

    api = _code("app/api.js")
    occurrences = sending.findall(api)
    assert len(occurrences) == 1, (
        f"api.js puts a member id on the wire {len(occurrences)} times. Exactly one is argued for — the "
        "curator's workbench session opener, which is addressed by member id because the caller is not "
        "that member. Anything else is A11 coming undone."
    )
    opener = re.search(r"export function openWorkbenchSession[^{]*\{(.*?)\n\}", api, re.DOTALL)
    assert opener, "openWorkbenchSession has moved; the one allowed occurrence is no longer locatable"
    assert sending.search(opener.group(1)), (
        "the one member id api.js is allowed to send is no longer the curator workbench session's. Either "
        "that route has stopped naming the member, or something else has started."
    )


def test_only_api_js_talks_to_the_server():
    """`api.js` says in its first line that it is the only place this client talks to the server, and
    that claim is what makes the C-05 scan above cheap to keep true. It is also what makes the bearer
    header impossible to forget: there is one `fetch` and it attaches the token.

    **Planted violation:** called `fetch('/api/session')` directly from `login.js`. Failed with that file
    named. Removed.
    """
    callers = [name for name, text in _named().items()
               if name.endswith(".js") and "fetch(" in _strip_js_comments(text)]
    assert callers == ["app/api.js"], f"something other than api.js reaches the network: {callers}"


def test_api_js_attaches_the_session_token():
    """The header is built in one expression from `session.token()`. Pinned because "the token is sent"
    is the whole of the client's part in A11, and it is one deleted line away from not being true —
    at which point every screen would simply show the login form and look like a server problem."""
    source = _code("app/api.js")
    assert "session.token()" in source, "api.js no longer reads the stored token"
    assert re.search(r"Authorization\s*=\s*`Bearer \$\{token\}`", source), (
        "api.js no longer attaches an Authorization header"
    )


def test_the_member_is_not_read_from_the_url_any_more():
    """`main.js` used to open with `params.get('member')` and a list of member ids in `localStorage`,
    and `store.js` said in its own comment that it "authenticates nothing and must be deleted the moment
    real sessions exist". They exist; it is deleted. `?lang=` and `?curator=` survive and are not member
    identity."""
    files = _named()
    assert "app/store.js" not in files, "store.js is back; the profile list is not a session layer"
    assert "surfaces/welcome.js" not in files, (
        "welcome.js is back; registration lives in surfaces/login.js with the credential fields"
    )
    assert "get('member')" not in _code("app/main.js"), "main.js reads the member from the URL again"


def test_only_the_session_module_touches_browser_storage():
    """One module holds the token, so there is one place to read when asking what this client keeps.

    It also carries the property that matters most: the *password* is never stored. That cannot be
    asserted directly — an absence over every possible expression — but "only session.js writes storage,
    and session.js writes `{token, identity}`" is checkable, and the two together are the argument.
    """
    writers = [name for name, text in _named().items()
               if name.endswith(".js") and "localstorage" in _strip_js_comments(text).lower()]
    assert writers == ["app/session.js"], f"more than one module writes browser storage: {writers}"
    source = _code("app/session.js")
    assert "password" not in source.lower(), "session.js has grown a password"


def test_the_chrome_is_translated_rather_than_hardcoded():
    """A12, and A70's named gap: the three door labels and the skip link were German literals in
    `index.html` and `main.js` retranslated neither, so an English member kept a German header.

    Each of them now carries a `data-i18n` key and `main.js::applyChrome` rewrites it. The German text
    stays in the document as the served default — a member whose script has not run reads a real header
    rather than an empty one — which is why this checks for the hook rather than for the absence of
    German.

    **Planted violation:** removed `data-i18n` from one door. Failed on the count. Restored.

    **The list grew to four doors on 31 August 2026** when `chrome.door_befund` was added, and **fell back
    to three on 4 September 2026** when item 8's navigation landed: Vault, Know, Market. Both movements are
    the substantive half of this test rather than an inconvenience — the assertion that failed when a door
    arrived is the same one that fails when a door leaves, and either way somebody has to say so on purpose.

    Plan and Befund are not gone, they are inside the Vault: `test_the_befund_is_reachable_from_the_vault`
    holds the join that used to end at this header.
    """
    index = _named()["index.html"]
    keys = re.findall(r'data-i18n="([^"]+)"', index)
    assert sorted(keys) == [
        "chrome.door_know",
        "chrome.door_market",
        "chrome.door_vault",
        "chrome.skip",
    ], f"the chrome's translation hooks have changed: {sorted(keys)}"
    main_js = _code("app/main.js")
    assert "data-i18n" in main_js, "main.js no longer looks for the translation hooks"
    # Defined AND called. `"applyChrome" in main_js` was the first version of this line and it stayed
    # green when the function was renamed to `applyChromeDisabled` and never invoked — a substring test
    # over an identifier that is a prefix of another identifier, which is A20's shape in one line.
    assert re.search(r"function applyChrome\s*\(", main_js), "applyChrome is gone"
    calls = len(re.findall(r"(?<!function )(?<![\w.])applyChrome\s*\(", main_js))
    assert calls >= 2, (
        f"applyChrome is defined and called {calls} time(s). It has to run at boot AND on every language "
        "change, which is the whole of A12's gap; one call is a chrome translated once and then frozen."
    )


# ============================================================ A12 / A26 — the language switch
#
# The owner, 31 August 2026: "English vs German Version - where can I switch" → "Make a switch in the
# browser". There was no control anywhere, no route that could change a locale, and every seeded member was
# de-CH — so `STRINGS.en` was complete and unreachable. These are the four claims that are only true if
# this side of the wire is right.


def test_the_chrome_carries_a_language_switch():
    """It is in the header, not in a panel, because the report was that it could not be found.

    A26 argued against a per-screen switcher on the grounds that nobody changes language more than once a
    year. That is true and beside the point: the once is the moment it has to be findable. A26's substance
    is untouched — the setting is still `Member.locale` and there is still one of it.
    """
    main_js = _code("app/main.js")
    assert re.search(r"function renderLanguageSwitch\s*\(", main_js), "there is no language switch"
    assert "chrome.language" in main_js, "the switch group has no accessible label"
    assert "aria-pressed" in main_js, (
        "the switch does not state which language is in force; two buttons with no state is a pair of "
        "links that both look available"
    )


def test_the_language_switch_is_rebuilt_on_every_language_change():
    """The switch has to follow the language too.

    `applyChrome` rewrites everything carrying `data-i18n`, and the switch is built in JavaScript rather
    than served in `index.html` — it needs a session route to be useful, so it does not exist without
    script. That puts it outside the `data-i18n` sweep, so `applyChrome` has to rebuild it explicitly or it
    becomes the one element in the header still labelled in the language the member just left.

    **Planted violation:** removed the `renderLanguageSwitch(language)` call from `applyChrome`. Failed
    with this test naming it. Restored.
    """
    main_js = _code("app/main.js")
    body = re.search(r"function applyChrome\s*\([^)]*\)\s*\{(.*?)\n\}", main_js, re.DOTALL)
    assert body, "applyChrome has moved"
    assert "renderLanguageSwitch(" in body.group(1), (
        "applyChrome does not rebuild the language switch, so its own label stays in the old language"
    )


def test_the_language_switch_persists_through_the_settings_route():
    """A26: the language is the member's setting, not this tab's mood.

    `PUT /api/settings/language` is the route that did not exist, and the identity is refreshed from its
    response rather than patched by hand — the server owns what `de` becomes.

    **Planted violation:** replaced the `setLanguage` call with a local object, which is what a
    session-only toggle would look like. Failed on the missing call. Restored.
    """
    main_js = _code("app/main.js")
    assert "setLanguage(" in main_js, "the switch changes nothing on the server; a reload would undo it"
    assert "session.refresh(" in main_js, "the stored identity keeps the old language"
    api_js = _code("app/api.js")
    assert "/api/settings/language" in api_js
    assert re.search(r"method:\s*'PUT'", api_js)


def test_the_switch_offers_only_languages_the_table_has_strings_for():
    """`boundary.py` carries refusal texts in de, fr, it and en; `i18n.js` carries strings in de and en.

    Offering French would hand a member a French refusal inside an otherwise German product, and every
    other label as a key name. The list comes from `languages()` — the table itself — so it cannot drift
    from what exists.

    **Planted violation:** hardcoded `['de', 'en', 'fr', 'it']`. Failed naming the literal. Restored.
    """
    main_js = _code("app/main.js")
    assert "languages()" in main_js, "the offered languages are not read from the string table"
    for unspoken in ("'fr'", '"fr"', "'it'", '"it"', "'rm'"):
        assert unspoken not in main_js, (
            f"main.js names {unspoken}, a language the interface has no strings for"
        )


def test_the_language_change_waits_for_the_screen_before_it_announces():
    """Found by running the path, not by reading it.

    Every surface announces itself to `#live` when it finishes loading, and four of the five route handlers
    are async. `changeLanguage` re-rendered the screen and then announced — so the announcement was
    overwritten by the one still in flight behind it, and a member using a screen reader heard the position
    count and never heard that the language had changed.

    `route()` returns its handler's promise and `changeLanguage` awaits it. Pinned because dropping the
    `await` restores the bug invisibly: the code reads correctly either way and the symptom is audible only.
    """
    main_js = _code("app/main.js")
    assert re.search(r"return handler\(\);", main_js), (
        "route() drops its handler's promise, so no caller can wait for the screen"
    )
    body = re.search(r"async function changeLanguage[^{]*\{(.*?)\n\}", main_js, re.DOTALL)
    assert body, "changeLanguage has moved"
    assert re.search(r"await route\(\)", body.group(1)), (
        "the language change announces before the screen has settled; the screen's own announcement "
        "overwrites it"
    )


def test_the_language_switch_reuses_the_existing_button_treatment():
    """A51 / A70: no new colours and no third button style.

    Both options are `.add`, the client's one secondary button, which already carries its 44px narrow
    target and its focus ring. A switch drawn from scratch is where a new hue and an unreachable tap
    target arrive together.
    """
    main_js = _code("app/main.js")
    assert re.search(r"class:\s*'add lang-choice'", main_js), (
        "the language buttons are no longer the client's one secondary treatment"
    )


# ============================================================ the unit, at the point of entry
#
# The owner: "Wachstum menschliches Kapital -> Betrag in welcher Frequenz?" The form asked for a Betrag and
# did not say per what — the unit selector was hidden until an amount existed, and `chf_per_year` was
# preselected. Two defensible decisions that were wrong together.


def test_the_unit_is_visible_before_an_amount_is_typed():
    """The frequency has to be readable at the moment it is being decided.

    **Planted violation:** wrapped the unit field in a hidden div again, which is what the file did before.
    Failed on the `hidden` attribute. Restored.
    """
    source = _code("surfaces/position-form.js")
    assert "unitField" in source, "the unit field has moved"
    assert not re.search(r"unitField\s*=\s*h\('div',\s*\{[^}]*hidden", source), (
        "the unit selector is hidden again; a member deciding what to type cannot see whether the field "
        "wants a year or a month"
    )
    # And nothing toggles it back on an input event, which is how it used to appear.
    assert "unitWrap" not in source


def test_no_unit_is_preselected():
    """R-120 says the unit is never inferred, and a default IS an inference — the quietest kind, because
    nobody sees it happen. The first option carries no value.

    **Planted violation:** deleted the placeholder option, leaving `chf_per_year` first and therefore
    selected. Failed on the missing placeholder. Restored.
    """
    source = _code("surfaces/position-form.js")
    options = re.findall(r"h\('option',\s*\{\s*value:\s*'([^']*)'", source)
    assert options, "the unit options have moved"
    assert options[0] == "", f"the first unit option is {options[0]!r}, so it is preselected"
    assert "form.unit_choose" in source


def test_an_amount_without_a_unit_is_refused_before_it_is_sent():
    """The model's CHECK constraint refuses the pair too, so this is not the enforcement — it is the
    difference between being asked a question and being shown a constraint name.

    **Planted violation:** replaced the condition with `if (false)`. The submit went through and the server
    answered with `ck_positions_magnitude_has_unit`; this failed on the missing check. Restored.
    """
    source = _code("surfaces/position-form.js")
    assert re.search(r"if\s*\(\s*amount\s*&&\s*!unit\.value\s*\)", source), (
        "an amount can be submitted with no unit, and the refusal the member sees is a constraint name"
    )
    assert "form.unit_missing" in source


def test_the_rendered_position_states_its_unit():
    """Item 4's second half: entering it explicitly is worth nothing if the plan then shows a bare figure.

    `grid.js` already prints the unit beside the amount. Pinned, because it is one template-string edit
    from not doing so, and the member who typed a monthly figure into an annual field is exactly the
    person who needs to read it back.
    """
    source = _code("surfaces/grid.js")
    assert "unit.chf_per_year" in source and "unit.share_of_total" in source
    assert re.search(r"\$\{amount\}\s*\$\{unit\}", source), (
        "the rendered position no longer states the unit beside the amount"
    )


def test_the_goals_target_amount_states_its_currency():
    """The same defect was on the goal screen, in a line that read "Zielbetrag: 250000" and left the reader
    to assume both the currency and that it was not a yearly figure."""
    source = _code("surfaces/containers.js")
    assert "formatAmount(" in source, "the target amount is printed unformatted"
    i18n = _named()["app/i18n.js"]
    assert "'containers.target_amount': 'Zielbetrag in CHF'" in i18n
    assert "'containers.target_amount': 'Target amount in CHF'" in i18n


# ============================================================ changing a goal, client side


def test_the_goal_screen_offers_a_way_to_change_a_goal():
    """The owner: "If I have a Ziel, I can not change it afterwards." There was no form and no route.

    Checked as the join: a control on the card, a form behind it, and the API function it calls. Any one of
    the three missing is the defect back.
    """
    source = _code("surfaces/containers.js")
    assert re.search(r"function editForm\s*\(", source), "there is no form for changing a goal"
    assert "containers.edit" in source, "there is no control to open it"
    assert "reviseGoal(" in source, "the form does not reach the route"
    assert "reviseGoal" in _code("app/api.js")


def test_only_the_changed_fields_are_sent():
    """The server tells "clear this field" from "leave it alone" by which keys are present, so the form
    compares each control against what it was prefilled with. Sending the whole form back would wipe
    whatever the member did not retype."""
    source = _code("surfaces/containers.js")
    body = re.search(r"function editForm\s*\([^)]*\)\s*\{(.*?)\n\}\n", source, re.DOTALL)
    assert body, "editForm has moved"
    assert "const changes = {}" in body.group(1), (
        "the edit form no longer builds a difference; it is posting every field on every save"
    )


def test_the_edit_form_says_what_happens_to_the_record():
    """R-040 and C-09 made visible before the member commits, not afterwards.

    The same reason C-09's question and choice are a visible fieldset rather than something the save button
    does quietly: a member should be able to see that they are leaving a trail before they leave it.
    """
    source = _code("surfaces/containers.js")
    assert "containers.edit_lede" in source
    i18n = _named()["app/i18n.js"]
    for language_marker in ("Der frühere Entscheid bleibt bestehen", "The earlier decision stands"):
        assert language_marker in i18n, f"the edit form does not say {language_marker!r}"


def test_nothing_offers_to_delete_a_goal():
    """Not an omission. R-122 keeps an inactive *position* rather than deleting it, nothing in the
    specification says what removing a goal means for the Decisions that reference it, and inventing an
    answer to that in a form is how a member loses the record of a decision they made."""
    source = _code("surfaces/containers.js")
    for verb in ("deleteGoal", "removeGoal", "method: 'DELETE'"):
        assert verb not in source, f"containers.js offers {verb!r}"


def test_no_template_is_chosen_for_the_member():
    """There were two templates and there are nine, with Frühpensionierung first at the owner's request —
    so whichever is first would otherwise be assigned to every goal named by a member who never opened the
    control. The placeholder carries no value and maps to no template."""
    for name in ("surfaces/containers.js", "surfaces/onboarding.js"):
        source = _code(name)
        assert "containers.template_choose" in source, f"{name} has no template placeholder"


def test_the_onboarding_goal_question_offers_the_templates_and_names_the_goal():
    """The owner's second sentence: "when in the onboarding the system ask for a goal, then we should
    immediately fill that goal out." The answer is an object now, which is why the control returns
    `{ node, read, focus }` rather than an input whose `.value` is a string."""
    source = _code("surfaces/onboarding.js")
    assert "goal_template" in source, "the goal question is a plain text field again"
    assert re.search(r"function goalControl\s*\(", source)
    assert "control.read()" in source, "the answer is read as a string again, so a template cannot travel"
    assert "readValue(" not in source, "the old string-only reader is back"
