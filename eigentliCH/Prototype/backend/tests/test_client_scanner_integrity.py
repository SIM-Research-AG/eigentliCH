"""The guards on the guards, and four prohibitions that had no test able to fail.

**Why this file exists.** An audit planted eleven violations across the client and the suite stayed green
for every one of them. None of the eleven sat behind a *missing* guard — each sat behind a guard that was
written, was passing, and could not fail. That is A20's hazard and A88's list of four inert guarantees,
found for the seventh through eleventh time.

The five findings, each held by a test below:

  1. **One string literal blinds every client scanner.** Every scanner in this suite strips ``/* … */``
     with ``re.DOTALL`` *before* it strips ``//``. A91 and A89 closed the case where the ``/*`` sits in a
     **line comment**, and both meta-guards look only at lines beginning with ``//``. Neither looks inside
     a **string literal**. Putting ``const EXPORT_ROUTE = '/api/vault/export/*';`` near the top of
     ``i18n.js`` opens a block-comment match that runs to the ``/**`` … ``*/`` block at the foot of that
     file, and what every scanner then sees of the string table falls from 147 207 characters to 675.
     Measured, not reasoned: mountain vocabulary and an ``innerHTML`` assignment both passed the whole
     suite afterwards. This is the most serious of the five, because it disables the other guards rather
     than evading one.

  2. **C-05's scan is line-scoped and there is no CSP.** It reads the *line* around a matched URL and asks
     whether that line contains ``fetch(`` or ``href``. A ``fetch()`` split over three lines passes, and
     ``WebSocket``, ``sendBeacon``, ``XMLHttpRequest``, ``EventSource``, ``importScripts`` and dynamic
     ``import()`` are absent from every keyword list in the suite — on the constraint that names session
     recorders explicitly.

  3. **R-113 has no structural guard on the role grid.** A completion ring with the class ``meter-ring``
     and the text ``3/8 · 38%`` passed 180 tests.

  4. **R-003's "no counts, dots or badges on navigation" fires only on the word "badge".**
     ``<span class="door-pip">3</span>`` on the Plan door passed.

  5. **R-031's non-dismissibility is unguarded.** ``class: 'notice warning severity-high'`` and an
     "Ignorieren" button that removed the observation list passed.

**Every test here was verified by planting the violation, watching it fail, and restoring** — the plants
are recorded on each one. Where a plant anchor is a literal, the plant asserted the anchor occurs exactly
once before substituting: this repository is CRLF, and an anchor written with ``\\n`` matches nothing while
looking as though it matched, which is a plant that silently proves the opposite of what it claims.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CLIENT = BACKEND.parent / "client"

#: Every file a member's browser loads. Same definition `test_client_bundle.py` uses, and it is imported
#: from there rather than restated so the two cannot come to scan different sets — A91's defect.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_client_bundle import _bundle_text, _member_facing  # noqa: E402


# ============================================================ a JavaScript reader that knows a string
#
# The strippers everywhere else in this suite are two regexes. That is the right tool for what they do —
# they exist so a comment explaining why a word is forbidden does not trip the check for that word — and it
# is exactly why they cannot be trusted to answer the question *this* file asks, which is whether the
# comment markers they key on are really comment markers.
#
# So this is a small state machine rather than a regex: it walks the file once and knows, at every
# character, whether it is inside code, a line comment, a block comment, a string, a template literal or a
# regular expression. It is not a JavaScript parser and does not need to be. It needs to be right about one
# thing — where a string ends — and that is decidable by counting backslashes.


def _regex_may_start_here(code_so_far: str) -> bool:
    """Whether a `/` at this point opens a regular expression rather than dividing.

    The standard heuristic, and the only genuinely ambiguous case in JavaScript lexing: a `/` is a regex
    start when the previous meaningful character cannot end an expression. `a / b` divides; `x = /re/`,
    `f(/re/)` and `[/re/]` do not.
    """
    for char in reversed(code_so_far):
        if char in " \t\r\n":
            continue
        return char in "(,=:[!&|?{};+-*%~^<>"
    return True


def scan(text: str) -> dict:
    """One pass over a JavaScript source, returning what is code and what is not.

    ``code`` is the source with every comment removed and every string, template and regex body replaced
    by spaces of the same length — so an offset in ``code`` is the same offset in ``text``, which is what
    lets the checks below report a line number.

    ``literals`` is every string and template literal body, with its 1-based line, for the checks that are
    about what the product *says* rather than about what it does.
    """
    code: list[str] = []
    literals: list[tuple[int, str]] = []

    i, n = 0, len(text)
    line = 1
    literal_start_line = 1
    current: list[str] = []

    def blank(chunk: str) -> str:
        return "".join("\n" if c == "\n" else " " for c in chunk)

    while i < n:
        char = text[i]

        # ---- line comment
        if char == "/" and text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            code.append(blank(text[i:end]))
            i = end
            continue

        # ---- block comment
        if char == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            chunk = text[i:end]
            line += chunk.count("\n")
            code.append(blank(chunk))
            i = end
            continue

        # ---- string, template
        if char in "'\"`":
            quote = char
            j = i + 1
            current = []
            literal_start_line = line
            while j < n:
                if text[j] == "\\":
                    current.append(text[j:j + 2])
                    j += 2
                    continue
                if text[j] == quote:
                    break
                # An unescaped newline ends a single- or double-quoted string in JavaScript; only a
                # template may carry one. Treating it as continuing would swallow the rest of the file,
                # which is the very failure this module is about.
                if text[j] == "\n" and quote != "`":
                    break
                current.append(text[j])
                j += 1
            body = "".join(current)
            literals.append((literal_start_line, body))
            chunk = text[i:min(j + 1, n)]
            line += chunk.count("\n")
            code.append(blank(chunk))
            i = min(j + 1, n)
            continue

        # ---- regular expression
        if char == "/" and _regex_may_start_here("".join(code)):
            j = i + 1
            in_class = False
            closed = False
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                elif text[j] == "/" and not in_class:
                    closed = True
                    break
                j += 1
            if closed:
                literals.append((line, text[i + 1:j]))
                code.append(blank(text[i:j + 1]))
                i = j + 1
                continue

        if char == "\n":
            line += 1
        code.append(char)
        i += 1

    return {"code": "".join(code), "literals": literals}


def _js_bundle() -> dict[str, str]:
    return {
        name.replace("\\", "/"): text
        for name, text in _bundle_text().items()
        if name.endswith(".js")
    }


def test_the_reader_reads():
    """Guard on the guard, and the whole file rests on it.

    A state machine that classified everything as code would make every check below vacuous — the exact
    shape A20 names and the reason `test_the_string_scanner_reads_real_values` exists next door. So the
    reader is pinned against known facts about the real files: it finds the string table's entries, it
    does not find the prose of a docstring, and it strips both kinds of comment.

    **Planted violation:** made the string branch fall through to code. `literals` came back nearly empty
    and this failed on the first assertion. Restored.
    """
    i18n = scan((CLIENT / "app" / "i18n.js").read_text(encoding="utf-8"))
    bodies = [body for _line, body in i18n["literals"]]
    assert len(bodies) > 2000, f"the reader found only {len(bodies)} literals in i18n.js"
    assert "Das Wissen" in bodies, "the reader did not find a known German string"
    assert "know.citations" in bodies, "the reader did not find a known key"
    # A sentence that appears only in a comment must NOT survive into code.
    assert "half-translated product" not in i18n["code"], "the reader left a block comment in the code"
    assert "STRINGS[language]" in i18n["code"], "the reader ate real code"

    know = scan((CLIENT / "surfaces" / "know.js").read_text(encoding="utf-8"))
    assert "persistent across all" not in know["code"], "the reader left a line comment in the code"
    assert "function citationKindLabel" in know["code"]


# ============================================================ 1. the scanner-blinding string literal


def test_no_string_literal_in_the_client_contains_a_comment_marker():
    """**The most serious of the eleven, because it disables the other guards rather than evading one.**

    Every client scanner in this suite — `test_client_bundle.py`, `test_client_surfaces.py`,
    `test_client_grants_market_phase8.py`, `test_client_s07_settings_capabilities.py` and
    `test_curator_signin.py` — strips ``/* … */`` with ``re.DOTALL`` before it strips ``//``. They have to
    strip in that order, because a block comment may contain ``//``.

    A91 and A89 both closed the case where the ``/*`` sits in a **line comment**, and their two guards
    look only at lines whose first non-space characters are ``//``. **A string literal is invisible to
    both.** ``const EXPORT_ROUTE = '/api/vault/export/*';`` is ordinary-looking JavaScript; placed near the
    top of `i18n.js` it opens a match that runs to the ``*/`` of the JSDoc block at the foot of that file,
    and every scanner's view of the string table drops from 147 207 characters to 675. Mountain vocabulary
    and an `innerHTML` assignment both passed the full suite behind it.

    So the rule is stated over what a *reader that knows a string* sees, rather than over lines: neither
    ``/*`` nor ``*/`` may occur inside any string literal, template literal or regular expression anywhere
    in the client. Route prefixes are written out — ``/api/vault/export/{id}`` — and a pattern needing a
    literal asterisk after a slash escapes it.

    **Planted violation, three times, each anchor asserted to occur exactly once first:**
    ``const EXPORT_ROUTE = '/api/vault/export/*';`` into `surfaces/vault.js` and separately into
    `app/i18n.js`; and a template literal `` `${base}/*` `` into `surfaces/know.js`. Each failed naming the
    file, the line and the literal. All removed.
    """
    offenders = []
    for name, text in _js_bundle().items():
        for line, body in scan(text)["literals"]:
            for marker in ("/*", "*/"):
                if marker in body:
                    offenders.append(f"{name}:{line}: {marker!r} inside {body[:60]!r}")
    assert not offenders, (
        "a string, template or regex literal contains a block-comment marker. Every client scanner in "
        "this suite strips block comments first and with DOTALL, so this deletes everything up to the "
        "next '*/' from what those tests can see — which is how a whole string table becomes invisible "
        "to every word filter at once:\n  " + "\n  ".join(offenders)
    )


def test_the_naive_stripper_and_a_real_reader_agree_about_every_client_file():
    """The property the test above protects, asserted directly rather than inferred from it.

    The two checks are not redundant. The one above says *why* a file is dangerous and names the literal a
    reviewer has to change; this one says the thing the rest of the suite actually depends on — that what
    `_member_facing` sees is what is really there. If a future author finds a third way to open a
    block-comment match that neither the line-comment guards nor the literal guard anticipate, this fails
    without anyone having predicted the mechanism.

    Compared by the words that survive, not by length: the two strippers differ in whitespace by
    construction, and a length comparison would be a test about spaces.

    **Code AND string bodies, and the plant is why.** A first version compared only the *code* the two
    views contain, and it passed the `i18n.js` plant — because everything the blinding deleted there was
    string data, which the honest reader blanks out of its code anyway. That is precisely the dangerous
    case: the word filters this suite runs for R-143 and C-07 read the **strings**, so a blinding that
    hides only strings hides exactly what those filters exist to read. What the honest reader can see is
    therefore its code plus every literal body, and all of it has to be visible to the naive stripper.

    **Planted violation:** the same `EXPORT_ROUTE` line in `i18n.js`. The naive view lost 4 000+ words and
    this failed naming the file and how many. Restored.
    """
    token = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]{3,}")
    offenders = []
    for name, text in _js_bundle().items():
        naive = set(w.lower() for w in token.findall(_member_facing(text)))
        read = scan(text)
        real = set(w.lower() for w in token.findall(read["code"]))
        for _line, body in read["literals"]:
            real |= {w.lower() for w in token.findall(body)}
        # Everything the honest reader can see must be visible to the naive one.
        missing = real - naive
        if missing:
            offenders.append(f"{name}: {len(missing)} words invisible, e.g. {sorted(missing)[:6]}")
    assert not offenders, (
        "the comment stripper every other client test uses is not seeing code that is really there. "
        "Something in these files opens a block-comment match that is not a block comment:\n  "
        + "\n  ".join(offenders)
    )


# ============================================================ 2. C-05, over statements rather than lines

#: Every way a browser can be made to talk to somewhere else, including the six that were on no list in
#: this suite. C-05 names "no external calls from authenticated pages; no analytics, no fonts-with-logging,
#: no session recorders" — and `WebSocket` and `sendBeacon` are how a session recorder is actually built.
NETWORK_APIS = (
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
    "importScripts",
    "navigator.serviceWorker",
    "SharedWorker",
    "RTCPeerConnection",
)


def test_only_the_documented_network_surface_exists_in_the_client():
    """C-05 as a closed set of mechanisms, not as a list of hostnames.

    `test_authenticated_bundle_makes_no_cross_origin_request` reads the **line** around a matched URL and
    asks whether it contains `fetch(` or `href`. Three defects follow from that and all three were
    measured: a `fetch()` split over three lines is invisible to it; `new WebSocket('wss://…')` matches no
    keyword it knows; and `navigator.sendBeacon(...)` matches none either. There is also no
    `Content-Security-Policy` anywhere in this client, so nothing at runtime would stop any of them.

    This asks the other question — which network *mechanisms* the source contains at all — and the answer
    for this client is one: `fetch`, in `app/api.js`, which `test_only_api_js_talks_to_the_server` already
    pins to that file. Everything else is absent, and absent is a far cheaper thing to keep true than
    audited.

    **Dynamic `import()` is included** and static `import … from` is not. The static form is resolved
    against the module's own URL at load and is the client's entire structure; the dynamic form takes a
    computed string and is a fetch with a different name.

    **Planted violations, four times:** `new WebSocket('wss://recorder.example.invalid/session')` in
    `surfaces/know.js`; `navigator.sendBeacon('/collect', body)` in `app/main.js`; a bare
    `new XMLHttpRequest()` in `app/api.js`; and `await import(chunk)` in `surfaces/market.js`. Each failed
    naming the file and the mechanism. All removed.
    """
    offenders = []
    for name, text in _js_bundle().items():
        code = scan(text)["code"]
        for api in NETWORK_APIS:
            for match in re.finditer(r"\b" + re.escape(api.split(".")[-1]) + r"\b", code):
                offenders.append(f"{name}:{code[:match.start()].count(chr(10)) + 1}: {api}")
        for match in re.finditer(r"(?<![.\w$])import\s*\(", code):
            offenders.append(f"{name}:{code[:match.start()].count(chr(10)) + 1}: dynamic import()")
    assert not offenders, (
        "C-05: the client contains a network mechanism other than the one `fetch` in app/api.js. C-05 "
        "names session recorders explicitly, and a WebSocket or a sendBeacon is how one is built:\n  "
        + "\n  ".join(offenders)
    )


def test_the_only_fetch_is_the_one_in_api_js_and_it_is_same_origin():
    """The other half: `fetch` exists once, and what it is given is a path rather than a URL.

    Checked over the **statement** rather than over the line, which is the defect this replaces: a call
    split across three lines had no `fetch(` on the line the URL sat on and passed. The argument is read
    from the call itself.

    **Planted violation:** `fetch(\\n  'https://example.invalid/x',\\n  options,\\n)` added to `api.js` —
    the shape the line-scoped scan misses. Failed naming the file. Restored.
    """
    files = _js_bundle()
    with_fetch = {}
    for name, text in files.items():
        code = scan(text)["code"]
        found = list(re.finditer(r"(?<![.\w$])fetch\s*\(", code))
        if found:
            with_fetch[name] = (text, code, found)

    assert set(with_fetch) == {"app/api.js"}, (
        f"`fetch` occurs in {sorted(with_fetch)}. api.js says in its first line that it is the only place "
        "this client talks to the server, and that claim is what makes every other C-05 check cheap."
    )

    text, code, found = with_fetch["app/api.js"]
    assert len(found) == 1, f"api.js contains {len(found)} fetch calls; one is the whole point"
    # The argument as written, from the real source rather than from the blanked copy.
    start = found[0].end()
    depth, end = 1, start
    while end < len(text) and depth:
        if text[end] == "(":
            depth += 1
        elif text[end] == ")":
            depth -= 1
        end += 1
    call = text[start:end]
    assert not re.search(r"['\"`](?:https?:)?//", call), (
        f"the one fetch in api.js is given an absolute or protocol-relative URL: {call[:120]!r}"
    )


# ============================================================ 3. R-113 on the role grid


#: Class names, elements and ARIA that exist to render a proportion. A meter is a meter whatever the number
#: behind it is called, so this bans the *shape* rather than a vocabulary of words for it — which is what
#: the existing `test_no_completion_meter_vocabulary_in_the_client` does and why `meter-ring` walked past.
METER_SHAPES = (
    r"<meter\b",
    r"<progress\b",
    r"role\s*[:=]\s*['\"]progressbar",
    r"aria-valuenow",
    r"aria-valuemax",
    r"\bconic-gradient\b",
    r"stroke-dash(?:array|offset)",
)

#: Words that name the thing rather than the number in it. `ring` is here because the plant was a ring.
#:
#: **Read from class attributes only**, not from every literal in the file. `containers.js` passes
#: `style: 'percent'` to `Intl.NumberFormat` to format a published rate from the assumption set — which is
#: a figure C-02 requires be shown with its provenance, and is the opposite of a completion meter. A guard
#: that fired on it would be a guard somebody switches off.
METER_CLASS_WORDS = ("meter", "gauge", "progress", "ring", "dial", "percent", "completion", "tally")

#: Wherever a class name is written in this client: `class: '…'` in `h()`, and `class="…"` in the markup.
CLASS_ATTR = re.compile(r"""class(?:Name)?\s*[:=]\s*['"]([^'"]*)['"]""")


def test_no_meter_exists_anywhere_in_the_client():
    """R-113 and C-07, as a ban on the shape rather than on the arithmetic.

    The payload carries no counts, and the existing word filter forbids "of 8", "% complete" and
    "Fortschritt". A completion ring needs none of those: it needs an arc, a class name and two numbers the
    client already has. `cells_filled_count` added to the grid payload and a ring drawn with
    ``class: 'meter-ring'`` and the text ``3/8 · 38%`` passed 180 tests.

    So this forbids the elements HTML provides for exactly this purpose, the ARIA that makes an arbitrary
    element into one, the two CSS techniques that draw a ring, and class names that say what is being
    drawn. It is deliberately broad: R-113 is a prohibition, and a prohibition whose guard has to be
    extended each time somebody finds a new way to draw an arc is not holding anything.

    **Planted violations, three times:** ``class: 'meter-ring'`` in `surfaces/grid.js`;
    ``role: 'progressbar', 'aria-valuenow': filled`` on the same node; and a `<progress>` element in
    `index.html`. Each failed naming the file. All removed.
    """
    offenders = []
    scanned = 0
    for name, text in _bundle_text().items():
        body = _member_facing(text)
        for shape in METER_SHAPES:
            if re.search(shape, body):
                offenders.append(f"{name}: {shape}")
        for match in CLASS_ATTR.finditer(text):
            scanned += 1
            value = match.group(1).lower()
            for word in METER_CLASS_WORDS:
                if re.search(r"\b" + word + r"[a-z-]*\b", value):
                    line = text[:match.start()].count("\n") + 1
                    offenders.append(f"{name}:{line}: class {value!r} names a {word}")
    # A20. A class scan that found no classes would pass over anything.
    assert scanned > 200, f"only {scanned} class attributes found in the client; the scan is wrong"
    assert not offenders, (
        "R-113 / C-07: the client contains the shape of a completion meter. The payloads carry no counts "
        "and that is deliberate; if a change needs one here, the constraint is the thing to revisit:\n  "
        + "\n  ".join(offenders)
    )


def test_the_role_grid_computes_no_ratio():
    """R-113 where it would actually be built. The grid is the screen with eight cells and a temptation.

    `grid.js` does count the filled cells — once, for `announce`, phrased as a statement of what is there
    rather than as progress toward eight, and A24's entry argues that. What it must never do is *divide*
    one count by another or express one as a percentage, because those two operations are the whole of
    what a completion meter is.

    So: no division operator and no percent sign in this file, read from the code with strings and comments
    blanked so an import path's slashes and a comment's prose are not mistaken for either. It is a narrow,
    file-scoped rule and it is stated as one on purpose — a `%` in a CSS length inside the role grid would
    have to be argued in a diff, which is the correct cost.

    **Planted violations, twice:** ``const share = filled / grid.cells.length;`` and separately
    ``text: `${Math.round((filled / 8) * 100)}%` ``. Both failed naming the operator. Restored.
    """
    read = scan((CLIENT / "surfaces" / "grid.js").read_text(encoding="utf-8"))
    code = read["code"]
    assert "filter(" in code, "the reader blanked grid.js; this check would then be vacuous"

    divisions = [m.start() for m in re.finditer(r"/(?![/*])", code)]
    assert not divisions, (
        f"surfaces/grid.js divides, at line(s) "
        f"{[code[:d].count(chr(10)) + 1 for d in divisions]}. A ratio of filled cells to eight is the "
        "completion meter R-113 forbids, and there is nothing else on this screen a division could be for."
    )
    # **Both sides of the blanking, and the plant is why.** ``Math.round(filled * 12.5) + '%'`` puts the
    # percent sign in a *string*, which `scan` blanks — so a check on `code` alone passed a rendered
    # percentage. The literals are read too.
    assert "%" not in code, (
        "surfaces/grid.js contains a percent sign outside a string. R-006 and R-113 make a percentage of "
        "the grid the one number this screen must not produce."
    )
    percented = [f"{line}: {body[:40]!r}" for line, body in read["literals"] if "%" in body]
    assert not percented, (
        f"surfaces/grid.js builds a string containing a percent sign: {percented}. R-113 forbids the "
        "percentage whatever it is concatenated from."
    )
    assert "Math.round" not in code and "toFixed" not in code, (
        "surfaces/grid.js rounds. The only quantity on this screen worth rounding is a proportion of the "
        "eight cells, which is the completion meter R-113 exists to forbid."
    )


# ============================================================ 4. R-003 on the navigation


def test_no_door_carries_anything_but_its_name():
    """R-003: "no counts, dots or badges on navigation".

    The existing guard is a word filter that fires on "badge". ``<span class="door-pip">3</span>`` inside
    the Plan door contains no forbidden word, and passed.

    Held two ways, because either alone is evadable. **Structurally:** every `.door` in `index.html` holds
    text and nothing else — a door with a child element is a door with something on it, whatever that
    something is called. **And by class vocabulary**, so a surface cannot append one at runtime: no class
    literal anywhere in the client names a pip, a dot, a badge, a count or an indicator.

    **Planted violations, twice:** ``<span class="door-pip" id="open-items">3</span>`` inside the Plan
    door in `index.html` (failed on the structural half, naming the door); and
    ``h('span', { class: 'door-count', text: items.length })`` in `app/main.js` (failed on the vocabulary
    half). Both removed.
    """
    index = (CLIENT / "index.html").read_text(encoding="utf-8")
    doors = re.findall(r"<a\b[^>]*\bclass=\"[^\"]*\bdoor\b[^\"]*\"[^>]*>(.*?)</a>", index, re.DOTALL)
    assert len(doors) >= 3, f"only {len(doors)} doors found in index.html; the scan is wrong"
    carrying = [inner.strip()[:70] for inner in doors if "<" in inner]
    assert not carrying, (
        f"R-003: a navigation door carries a child element rather than only its name: {carrying}. A count, "
        "a dot and a badge are all the same defect and none of them is named in the markup."
    )

    forbidden = ("pip", "dot", "badge", "count", "tally", "indicator", "bubble", "unread")
    offenders = []
    for name, text in _js_bundle().items():
        for line, literal in scan(text)["literals"]:
            low = literal.lower()
            if "door" not in low and "nav" not in low:
                continue
            for word in forbidden:
                if re.search(r"\b" + word + r"\b", low):
                    offenders.append(f"{name}:{line}: {literal[:50]!r}")
    assert not offenders, (
        "R-003: a class or id names a marker on the navigation:\n  " + "\n  ".join(offenders)
    )


# ============================================================ 5. R-031's non-dismissibility


def test_an_observation_is_a_statement_of_fact_and_cannot_be_dismissed():
    """R-031: "surfaced as a statement of fact, not as a warning to be dismissed".

    `containers.js` says so in a comment — "No severity class, no icon, no dismiss button" — and nothing
    checked it. ``class: 'notice warning severity-high'`` on the observation list, plus an "Ignorieren"
    button that removed the list from the DOM, passed the suite.

    Both halves are held, because R-031 forbids two different things and the sentence names them
    separately. **Not a warning:** the node that carries the observations, and the node that builds one,
    may not carry a severity or an alert treatment. **Not dismissible:** nothing in this surface removes a
    node from the document, and no string in the client offers to ignore, hide or dismiss an observation.

    The scan is scoped to the two functions rather than to the file, so it is about the observations and
    not about, say, the goal edit form's own error notice — which is a genuine error and correctly styled
    as one.

    **Planted violations, three times:** ``class: 'notice warning severity-high'`` on the observation
    list; an ``'containers.obs_dismiss': 'Ignorieren'`` string with a button that called
    ``list.remove()``; and ``role: 'alert'`` on the observation `li`. Each failed. All removed.
    """
    text = (CLIENT / "surfaces" / "containers.js").read_text(encoding="utf-8")
    code = scan(text)["code"]
    assert len(code) == len(text), "scan() no longer preserves offsets; every span below would be wrong"

    # **The span is found in the code and read in BOTH copies, and the plant is why.** A first version read
    # only `code`, where `scan` has blanked every string — so ``class: 'notice warning severity-high'``
    # planted onto the observation `li` was invisible and the guard passed its own plant. The class name is
    # a string by construction; that is where it has to be read.
    builder = re.search(r"function observationNode\s*\(.*?\n\}", code, re.DOTALL)
    assert builder, "observationNode has moved; this guard can no longer find what it is about"
    span = text[builder.start():builder.end()]
    assert "h('li'" in span, "the observation is no longer built as a list item; re-check this guard"

    for value in CLASS_ATTR.findall(span):
        for marker in ("notice", "warning", "severity", "alert", "danger", "error"):
            assert marker not in value.lower(), (
                f"R-031: observationNode carries the class {value!r}. An observation is a statement of "
                "fact, and a severity or an alert treatment turns it into a warning to be dealt with."
            )
    for marker in ("role: 'alert'", 'role="alert"', "button(", "onClick"):
        assert marker not in span, (
            f"R-031: observationNode carries {marker!r}. An alert role or a control makes an observation "
            "something to be dealt with and dismissed."
        )

    # The block that renders the list, located by the string every branch of it reads. The anchor is found
    # in the raw source because `scan` blanks string bodies — and the offset is valid in `code` because
    # `scan` replaces rather than deletes, so the two are the same length. The *reading* is done on `code`,
    # so the comment above the block, which contains the word "severity" while forbidding it, is invisible
    # here: that is A20's trap and it would have made this assertion fail on the correct code.
    assert len(code) == len(text), "scan() no longer preserves offsets; the anchor below would be wrong"
    anchor = text.index("containers.observations")
    region = code[max(0, anchor - 400):anchor + 700]
    for marker in ("notice", "severity", "warning"):
        assert marker not in region.lower(), (
            f"R-031: the observations block is rendered with {marker!r} in it"
        )

    # Nothing in this surface takes a node out of the document.
    for remover in (".remove()", "removeChild", "replaceChildren"):
        assert remover not in code, (
            f"R-031 / A45: containers.js calls {remover}. The observations are not dismissible, and the "
            "only mechanism by which they could become so is a control that removes them."
        )

    # And no copy anywhere offers to make them go away.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_client_surfaces import strings  # noqa: E402

    dismissals = ("ignorieren", "ausblenden", "verwerfen", "wegklicken", "dismiss", "ignore this",
                  "hide this", "got it", "verstanden")
    offenders = []
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith(("containers.obs", "containers.observ")):
                continue
            for word in dismissals:
                if word in value.lower():
                    offenders.append(f"{language}/{key}: {word!r}")
    assert not offenders, f"R-031: an observation offers to be dismissed: {offenders}"


# ============================================================ R-002 / R-170: the panel that must be there


def test_every_screen_the_router_can_draw_syncs_the_panel():
    """R-002 and R-170, and this is the architectural centre of S-08.

    The Know is mounted onto `document.body` outside the router, and `panel.sync()` is the single call that
    decides whether it is visible for the member on screen. **Removing all five calls from `main.js` — so
    that the panel never becomes visible on any screen at all — left the suite green.** There was no test
    anywhere that could tell the difference between a client with a persistent panel and one without.

    Held over the *function bodies* rather than over the file, which is the difference between this and a
    check for the presence of a name: `main.js` naming `panel.sync` once somewhere would satisfy a
    substring test while four of the five screens went without it. Every function that can be the last
    thing to run before a member is looking at a screen must call it — the router itself, and the three
    screens that are drawn *before* the router's member gate and therefore never reach it.

    **Planted violations, three times:** deleted the call from `route()` (failed naming `route`); deleted
    it from `renderCurator` (failed naming that); and replaced all five with a call to a no-op with the
    same name (failed, because the assertion is on the call inside each body and the plant removed them).
    All restored.
    """
    code = scan((CLIENT / "app" / "main.js").read_text(encoding="utf-8"))["code"]
    assert "know.mount(" in code, "the Know is no longer mounted at all"
    assert "document.body" in code, "the panel is no longer mounted outside the router"

    def body_of(name: str) -> str:
        start = re.search(rf"\bfunction {re.escape(name)}\s*\(", code)
        assert start, f"{name} has moved; this guard can no longer find it"
        i = code.index("{", start.end() - 1)
        depth, j = 0, i
        while j < len(code):
            if code[j] == "{":
                depth += 1
            elif code[j] == "}":
                depth -= 1
                if depth == 0:
                    return code[i:j + 1]
            j += 1
        raise AssertionError(f"{name} is not brace-balanced")

    # `route` is the one every authenticated screen goes through; the other three are drawn before the
    # member gate and would otherwise be the screens with no panel.
    for name in ("route", "renderLogin", "renderPasswordChange", "renderCurator"):
        assert re.search(r"\bpanel\.sync\s*\(\s*\)", body_of(name)), (
            f"R-002 / R-170: {name}() draws a screen and does not sync the Know panel. The panel is "
            "'persistent across all authenticated screens' and the only thing that makes it appear for a "
            "member is this call."
        )

    # And the panel is not a route: a tab is a place you leave the current screen to visit.
    assert not re.search(r"\bknow:\s*(?:renderKnowPanel|panel)\b", code), (
        "the Know has become a route. R-002 asks for a panel alongside every screen, which is the "
        "opposite of a destination."
    )


# ============================================================ R-222, over every key rather than one prefix


def test_nothing_in_the_interface_calls_anything_but_a_life_event_an_event():
    """R-222: "the word *events* in the interface means life events".

    The existing guard reads `community.js` and the keys beginning `community.` — so `'settings.zz': 'Your
    events and gatherings'` passes, and so did a real violation: `erasure.what_stays` in English said *"the
    recorded decisions and the session events remain as rows"*, on the screen where a member decides
    whether to erase their account.

    **Scoped by the sentence rather than by the key**, which is what the requirement actually says. The
    word may appear where it is qualified as a life event and nowhere else, so `chrome.door_plan`
    ("Plan & life events") and the whole `life_events.*` block are covered by the rule rather than
    exempted from it — and a key added under any prefix at all is covered too.

    **Planted violations, twice:** `'settings.zz': 'Your events and gatherings'` (failed naming the key);
    and the old `erasure.what_stays` wording put back (failed naming that key, which is what this test was
    written for). Both removed.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_client_surfaces import strings  # noqa: E402
    from eigentlich.services.community import FORBIDDEN_GATHERING_WORDS  # noqa: E402

    #: The one qualified form R-222 permits, removed before the scan rather than exempted by key.
    qualified = re.compile(r"\b(?:life|lebens)[- ]?(?:event|events|ereignis|ereignisse)\b", re.IGNORECASE)

    offenders = []
    checked = 0
    for language in ("de", "en"):
        table = strings(language)
        assert len(table) > 300, f"{language} table came back with {len(table)} entries"
        for key, value in table.items():
            checked += 1
            remaining = qualified.sub(" ", value).lower()
            for word in FORBIDDEN_GATHERING_WORDS:
                if re.search(r"\b" + re.escape(word) + r"\b", remaining):
                    offenders.append(f"{language}/{key}: {word!r} — {value[:70]}")
    assert checked > 600, f"only {checked} strings scanned"
    assert not offenders, (
        "R-222: the interface uses the word for an event where it does not mean a life event. Gatherings "
        "are named as lectures, evenings or meet-ups; a curator session has a log, not events:\n  "
        + "\n  ".join(offenders)
    )


# ============================================================ the vocabularies the new copy has to obey


@pytest.mark.parametrize("selector", (
    ".position-form input",
    ".position-form textarea",
    ".position-form select",
    ".primary",
    ".add",
    ".consent-box",
))
def test_every_control_this_pass_added_uses_an_already_ringed_treatment(selector):
    """A51 and the accessibility suite's own rule, checked from the other end.

    The curator's consultation forms — the note, the recommendation and the close — added controls but no
    CSS, deliberately: every one of them is a `.position-form` input, textarea, select, `.primary`,
    `.add` or the `.consent-box` checkbox, all six of which are already in
    `test_client_accessibility.py::INTERACTIVE_SELECTORS` and therefore already required to carry a focus
    rule of their own. This asserts the premise that argument rests on — that these six are still listed
    there — so a rename in that file cannot silently drop the new controls out of the accessibility scan.

    **Planted violation:** removed `.consent-box` from `INTERACTIVE_SELECTORS`. Failed naming it.
    Restored.
    """
    from test_client_accessibility import INTERACTIVE_SELECTORS  # noqa: E402

    assert selector in INTERACTIVE_SELECTORS, (
        f"{selector} is no longer in the accessibility suite's list, and the curator consultation forms "
        "rely on it being there rather than shipping CSS of their own"
    )


def test_the_curator_surface_adds_no_class_of_its_own():
    """A89's rule, restated for the work that just landed on this surface.

    The curator screens are built entirely from treatments every other surface already uses — `.report*`,
    `.field`, `.notice`, `.position-form`, `.primary`, `.add`. That is what let the sign-in screen ship
    with no CSS at all and no new entry in the accessibility suite. The consultation controls hold to it.

    **Planted violation:** `class: 'curator-session-log'` on the log region. Failed naming it. Restored.
    """
    css = (CLIENT / "style" / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"\.curator[a-z-]*\s*[,{]", css), "a .curator* rule has appeared in the stylesheet"

    known = {
        "report", "report-block", "report-heading", "report-status", "report-facts", "report-fact",
        "report-sentence", "report-quote-label", "report-meta", "field", "field-label", "field-hint",
        "lbl", "notice", "notice error", "position-form", "primary", "add", "known", "actions",
        "definition-toggle", "lede", "consent-box", "position", "position-label", "position-meta",
        "cell-prompt",
    }
    used = set()
    for line, literal in scan((CLIENT / "surfaces" / "curator.js").read_text(encoding="utf-8"))["literals"]:
        del line
        if literal in known or not literal:
            continue
        # Only literals that are plausibly class attributes: short, lowercase, hyphen-or-space separated.
        if re.fullmatch(r"[a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*", literal) and len(literal) < 40:
            used.add(literal)
    unknown = {
        value for value in used
        if re.search(r"\b(report|field|notice|curator|panel|log|session)[a-z-]*\b", value)
        and value not in known
    }
    assert not unknown, (
        f"surfaces/curator.js uses class names the stylesheet does not define and this pass did not add "
        f"CSS for: {sorted(unknown)}"
    )
