"""WCAG AA, checked against the stylesheet rather than against a screenshot.

**Why static.** A browser run would prove that one rendered page, in one viewport, with one set of data,
looked right. A scan of the sheet proves the rules that produce every page. For contrast in particular the
static form is strictly stronger: the ratios below are *computed* from the token values, so the test fails
the moment someone edits a hex — not the moment someone happens to look at the screen it broke.

The same argument A20 makes about vacuous filters applies here, so every check that iterates asserts it had
something to iterate over, and the contrast helper is itself pinned against known figures.

What this file does not claim to cover: anything that depends on rendered geometry (does this ring actually
get clipped, does this word actually overflow this box) and anything decided in JavaScript. Those were
checked in a browser; these are the parts that can be held.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parent.parent.parent / "client"
TOKENS = (CLIENT / "style" / "tokens.css").read_text(encoding="utf-8")
APP = (CLIENT / "style" / "app.css").read_text(encoding="utf-8")
INDEX = (CLIENT / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- colour arithmetic
#
# WCAG 2.x relative luminance and contrast ratio, written out rather than imported: the project has no
# colour dependency and adding one to compute eight lines of arithmetic would be the wrong trade.


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def over(fg: str, alpha: float, bg: str) -> str:
    """Flatten a translucent colour onto an opaque one.

    Three of the palette's colours are ``rgba()`` over whatever is behind them, and a contrast figure for a
    translucent colour is meaningless until it is composited. ``--wash`` on the tinted page ground is a
    different colour from ``--wash`` on a white card, and both occur.
    """
    f, b = fg.lstrip("#"), bg.lstrip("#")
    out = ""
    for i in (0, 2, 4):
        fv, bv = int(f[i : i + 2], 16), int(b[i : i + 2], 16)
        out += f"{round(fv * alpha + bv * (1 - alpha)):02X}"
    return "#" + out


def test_the_contrast_helper_agrees_with_the_published_figures():
    """A20 again: a ratio function that always returned 21 would pass every test below.

    Pinned to figures from WCAG's own examples and to the two the palette already states about itself.
    """
    assert round(contrast("#000000", "#FFFFFF"), 2) == 21.0
    assert round(contrast("#FFFFFF", "#FFFFFF"), 2) == 1.0
    assert round(contrast("#767676", "#FFFFFF"), 2) == 4.54
    # tokens.css claims these two in prose. If the claim and the arithmetic disagree, one of them is wrong.
    assert round(contrast("#A059C1", "#FFFFFF"), 2) == 4.47, "--primary is not 4.47:1 on white"
    assert contrast("#5d4591", "#FFFFFF") >= 7.5, "--ink-soft is not 7.5:1 on white"


# ---------------------------------------------------------------- the palette, read from the file
#
# Read rather than transcribed. A test holding its own copy of the palette passes forever after someone
# edits tokens.css, which is the one moment it exists to catch.

_TOKEN = re.compile(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", re.MULTILINE)


def _tokens() -> dict[str, str]:
    return {name: value.strip() for name, value in _TOKEN.findall(TOKENS)}


def resolve(name: str) -> str:
    """Follow ``var()`` aliases down to a hex literal."""
    tokens = _tokens()
    seen: set[str] = set()
    value = tokens[name]
    while value.startswith("var("):
        inner = value[4:].split(")")[0].strip()
        assert inner not in seen, f"{name} resolves in a circle"
        seen.add(inner)
        value = tokens[inner]
    assert re.fullmatch(r"#[0-9A-Fa-f]{3,6}", value), f"{name} is not a hex colour: {value!r}"
    return value


def test_the_palette_is_readable_from_the_token_file():
    tokens = _tokens()
    assert len(tokens) >= 30, f"only {len(tokens)} tokens parsed; the regex has stopped matching"
    for name in ("--ink", "--surface", "--surface-tint", "--accent-text", "--accent-line",
                 "--muted-text", "--control-line", "--attention", "--refusal"):
        assert name in tokens, f"{name} is missing from tokens.css"


#: Every foreground/background pair this client actually paints, and where. WCAG would let some of these
#: through at 3:1 as "large text"; none of them is judged that way here. The smallest type in this product
#: is 0.65rem and the member reading it may be doing so on a phone in poor light.
TEXT_PAIRS = [
    ("body ink on the page ground", "--ink", "--surface-tint", "body"),
    ("body ink on a card", "--ink", "--surface", ".cell, .role-name, the forms"),
    ("magnitude figures", "--ink-black", "--surface", ".position-magnitude"),
    ("eyebrow label on the page", "--accent-text", "--surface-tint", ".lbl"),
    ("eyebrow label on a card", "--accent-text", "--surface", ".lbl inside a panel"),
    ("disclosure toggle", "--accent-text", "--surface", ".definition-toggle"),
    ("lede and column headers", "--muted-text", "--surface-tint", ".lede, .grid-head"),
    ("secondary text on a card", "--muted-text", "--surface", ".position-meta, .field-hint, .cell-prompt"),
    ("navigation door", "--muted-text", "--surface", ".door in .chrome"),
    ("provisional badge", "--attention", "--surface-off", ".provisional"),
    ("submit button label", "--surface", "--ink", ".primary"),
    ("submit button label, hovered", "--surface", "--primary-deep", ".primary:hover"),
]

#: Composited pairs. ``--wash`` is rgba over two different grounds and both occur.
WASH_PAIRS = [
    ("notice text on the page ground", "--ink-black", ("--primary", 0.06, "--surface-tint"), ".notice"),
    ("notice text on a card", "--ink-black", ("--primary", 0.06, "--surface"), ".notice in the panel"),
    ("refusal hue on its own wash", "--refusal", ("--primary", 0.06, "--surface-tint"), ".notice.error"),
]


@pytest.mark.parametrize("name,fg,bg,where", TEXT_PAIRS, ids=[p[0] for p in TEXT_PAIRS])
def test_every_text_pair_meets_wcag_aa(name, fg, bg, where):
    """1.4.3, at the 4.5:1 floor for every pair without exception.

    This is the test that found ``--ink-mute``: 4.06:1 on white and 3.72:1 on the tinted ground, carrying
    the lede, every field hint, every position meta line and the navigation. See tokens.css on --ink-quiet.
    """
    a, b = resolve(fg), resolve(bg)
    ratio = contrast(a, b)
    assert ratio >= 4.5, f"{name} ({where}): {fg} {a} on {bg} {b} is {ratio:.2f}:1, under 4.5:1"


@pytest.mark.parametrize("name,fg,wash,where", WASH_PAIRS, ids=[p[0] for p in WASH_PAIRS])
def test_every_text_pair_over_a_translucent_wash_meets_wcag_aa(name, fg, wash, where):
    tint, alpha, ground = wash
    b = over(resolve(tint), alpha, resolve(ground))
    a = resolve(fg)
    ratio = contrast(a, b)
    assert ratio >= 4.5, f"{name} ({where}): {fg} {a} on {b} is {ratio:.2f}:1, under 4.5:1"


#: 1.4.11, non-text contrast: a control's boundary and a focus indicator need 3:1 against what they sit on.
#: The two capital edge hues are deliberately absent — they reinforce a text label rather than replacing
#: one, which tokens.css says and `test_nothing_states_capital_type_by_colour_alone` holds.
NON_TEXT_PAIRS = [
    ("control boundary on a card", "--control-line", "--surface"),
    ("control boundary on the page ground", "--control-line", "--surface-tint"),
    ("focus ring on a card", "--accent-line", "--surface"),
    ("focus ring on the page ground", "--accent-line", "--surface-tint"),
    ("disclosure marker", "--accent-line", "--surface"),
]


@pytest.mark.parametrize("name,fg,bg", NON_TEXT_PAIRS, ids=[p[0] for p in NON_TEXT_PAIRS])
def test_control_boundaries_and_focus_rings_meet_non_text_contrast(name, fg, bg):
    a, b = resolve(fg), resolve(bg)
    ratio = contrast(a, b)
    assert ratio >= 3.0, f"{name}: {fg} {a} on {bg} {b} is {ratio:.2f}:1, under the 3:1 of WCAG 1.4.11"


def test_the_accent_split_is_still_a_split():
    """A51's one accessibility decision, held in place.

    ``--accent-text`` is for words and ``--accent-line`` is for lines, and the point is that they are not
    the same colour. If someone collapses them the product either loses its focus ring's hue or drops its
    purple text under the floor, and neither reads as an obvious mistake in a diff.
    """
    text, line = resolve("--accent-text"), resolve("--accent-line")
    assert text != line, "--accent-text and --accent-line have collapsed to one colour"
    assert contrast(text, resolve("--surface")) >= 4.5
    assert 3.0 <= contrast(line, resolve("--surface")) < 4.5, (
        "--accent-line is no longer the line-only colour the split was built around"
    )


def test_the_same_split_exists_for_the_grey_violet():
    """The second application of the same idea: --ink-mute keeps the site's value, --muted-text is legible."""
    assert contrast(resolve("--ink-mute"), resolve("--surface-tint")) < 4.5, (
        "--ink-mute now passes on its own; the --muted-text indirection may be removable, but check every "
        "usage before deleting it"
    )
    assert contrast(resolve("--muted-text"), resolve("--surface-tint")) >= 4.5
    assert contrast(resolve("--muted-text"), resolve("--surface")) >= 4.5
    assert "var(--ink-mute)" not in APP, (
        "app.css paints text with --ink-mute again; use --muted-text (tokens.css explains why)"
    )


# ---------------------------------------------------------------- focus


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)


APP_RULES = _strip_comments(APP)


def test_a_global_focus_ring_exists():
    assert re.search(r":focus-visible\s*\{[^}]*outline\s*:\s*2px solid", APP_RULES), (
        "there is no global :focus-visible ring"
    )


def test_focus_is_not_left_to_focus_visible_alone():
    """``:focus-visible`` is unsupported in Safari before 15.4 and Firefox before 86.

    Without a fallback those browsers show whatever ring the UA draws, which on a control this sheet has
    already restyled is frequently nothing. The @supports block hands them the identical rule on ``:focus``.
    """
    assert re.search(r"@supports\s+not\s+selector\(\s*:focus-visible\s*\)", APP_RULES), (
        "no :focus fallback for browsers without :focus-visible"
    )


#: Every selector in this client that can take focus. `.door` and `.skip` are links, the rest are buttons,
#: a summary, the form controls, and one scroll container.
#:
#: `.figures-scroll` is the odd one and belongs here for a reason worth stating: it is the box the
#: illustration's per-scenario table scrolls inside on a narrow screen, and `containers.js` gives it
#: `tabindex="0"` and a group label because a region that can only be reached by dragging cannot be reached
#: by keyboard at all (WCAG 2.1.1). Having put it in the tab order, it needs a visible ring like everything
#: else in this list.
INTERACTIVE_SELECTORS = (
    ".door",
    ".skip",
    ".add",
    ".lang-choice",
    ".primary",
    ".definition-toggle",
    ".tags summary",
    ".position-form input",
    ".position-form textarea",
    ".position-form select",
    ".figures-scroll",
    # R-103's agreement box, added with the consent capture point. `.position-form input` reaches it
    # through the cascade — the registration form is a `.position-form` — and it is listed anyway, for the
    # reason this test's docstring gives: "the cascade covers it" is an argument and a rule naming the
    # control is a fact. It also needs one of its own: it is the only control in the client resized away
    # from the UA default, and a 24px box inside a 44px label is exactly the shape whose ring gets clipped.
    ".consent-box",
    # R-231's destructive submit. It is a `.primary` and therefore already ringed, but it overrides
    # `background` and `border-color` to carry --refusal, and an override of the border is how a focus ring
    # stated on the border stops being visible.
    ".erasure-submit",
)


@pytest.mark.parametrize("selector", INTERACTIVE_SELECTORS)
def test_every_interactive_selector_has_a_focus_rule_of_its_own(selector):
    """Not because the global rule fails to reach them — because "the cascade covers it" is an argument and
    a rule naming the control is a fact. Two of these needed one anyway: ``.tags summary`` sits inside an
    ``overflow: hidden`` box that clips an offset ring, and ``.add`` states focus on its border as well.
    """
    pattern = re.escape(selector) + r"[^,{}]*:focus(-visible)?"
    assert re.search(pattern, APP_RULES), f"{selector} has no rule matching :focus or :focus-visible"


def test_no_outline_none_without_a_replacement():
    """``outline: none`` is the single most common way a sheet becomes unusable by keyboard.

    It is permitted in exactly one shape: guarded by ``:not(:focus-visible)``, which by definition cannot
    match the focus a keyboard user gets. Anything else has to be argued in the diff, not here.
    """
    offenders = []
    for match in re.finditer(r"([^{}]*)\{([^}]*)\}", APP_RULES):
        selector, body = match.group(1).strip(), match.group(2)
        if not re.search(r"outline\s*:\s*(none|0)\b", body):
            continue
        if ":not(:focus-visible)" in selector:
            continue
        offenders.append(selector[:120])
    assert not offenders, (
        "outline is suppressed without a :not(:focus-visible) guard on: " + "; ".join(offenders)
    )


def test_the_wordmark_survives_a_forced_colours_setting():
    """``outline`` is a property forced-colours mode overrides for you, so the ring itself is safe. The
    wordmark is not: a transparent text fill erases it entirely. That rule is the one worth pinning."""
    assert re.search(r"@media\s*\(\s*forced-colors:\s*active\s*\)", APP_RULES)


# ---------------------------------------------------------------- motion, print, layout


def test_reduced_motion_is_honoured():
    """2.3.3. A small sheet with four transitions — and the point is that the answer should not depend on
    the next author remembering the setting exists."""
    block = re.search(
        r"@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{(.*?)\n\}", APP_RULES, re.DOTALL
    )
    assert block, "no prefers-reduced-motion block"
    body = block.group(1)
    assert "transition-duration" in body and "!important" in body
    assert "animation-duration" in body


def _print_block() -> str:
    block = re.search(r"@media print\s*\{(.*)\n\}", APP_RULES, re.DOTALL)
    assert block, "no @media print block"
    return block.group(1)


def test_a_print_stylesheet_exists_and_removes_the_chrome():
    """Members print a plan and take it to somebody. What comes out has to be a document."""
    body = _print_block()
    assert "@page" in body, "the print block sets no page margin"
    assert ".doors" in body, "the navigation is not removed for print"
    assert re.search(r"\bbutton\b[^{}]*\{[^}]*display:\s*none", body), "buttons are not removed for print"
    assert ".wordmark" in body, (
        "the wordmark's gradient text fill is transparent; without a print rule the company name prints as "
        "an empty space"
    )


def test_print_does_not_force_backgrounds_to_be_inked():
    """``print-color-adjust: exact`` over a page of white cards on a tinted ground costs a cartridge."""
    assert "color-adjust" not in _print_block()


def test_print_overrides_the_panels_inline_styles():
    """``know.js`` writes the panel's geometry and the body's right padding as inline declarations, so a
    print rule without ``!important`` loses to them and every sheet prints indented with a blank column."""
    body = _print_block()
    assert re.search(r"padding-right:\s*0\s*!important", body)
    assert re.search(r"body\s*>\s*\*[^{}]*\{[^}]*display:\s*none\s*!important", body)


def test_a24_holds_and_its_two_queries_meet():
    """A24: four role rows by two capital columns above 700px, one card per role below.

    The gap between ``max-width: 699px`` and ``min-width: 700px`` is real — fractional viewport widths
    happen under browser zoom and on scaled displays — and a viewport that lands in it gets the
    three-column grid on a phone.
    """
    narrow = re.search(r"@media\s*\(\s*max-width:\s*([\d.]+)px\s*\)", APP_RULES)
    wide = re.search(r"@media\s*\(\s*min-width:\s*([\d.]+)px\s*\)", APP_RULES)
    assert narrow and wide, "one side of the A24 breakpoint is missing"
    assert float(wide.group(1)) == 700.0
    assert 699.9 <= float(narrow.group(1)) < 700.0, (
        f"the narrow query stops at {narrow.group(1)}px, leaving a gap below 700px where neither applies"
    )
    body = re.search(
        r"@media\s*\(\s*max-width:\s*[\d.]+px\s*\)\s*\{(.*?)\n\}", APP_RULES, re.DOTALL
    ).group(1)
    assert re.search(r"\.role-row\s*\{[^}]*grid-template-columns:\s*1fr", body), (
        "A24: the narrow layout does not collapse .role-row to one column"
    )


def test_the_wide_grid_tracks_can_shrink_below_their_content():
    """``1fr`` will not go below min-content, so one long German compound widens the track, the row
    overflows, and ``.role-row { overflow: hidden }`` then clips the text away with no scrollbar and no
    ellipsis — the text simply is not there."""
    for rule in (".role-row", ".grid-head"):
        block = re.search(re.escape(rule) + r"\s*\{([^}]*)\}", APP_RULES)
        assert block, f"{rule} is gone"
        assert "minmax(0, 1fr)" in block.group(1), (
            f"{rule} sizes its columns with a bare 1fr; a long unbroken word will blow the track out"
        )


def test_long_words_are_allowed_to_break():
    """A vault title is capped at 300 characters and nothing caps the spaces in it; German supplies
    Erwerbsunfaehigkeitsversicherung without anyone trying."""
    for selector in (".position-label", ".role-name", ".field-label", ".cell-prompt"):
        assert selector in APP_RULES
    assert APP_RULES.count("overflow-wrap: anywhere") >= 2, "no wrapping defence for long labels"
    assert "hyphens: auto" in APP_RULES, "German prose is not hyphenated"
    assert re.search(r"min-width:\s*0", APP_RULES), (
        "grid and flex children still default to their content's min-width, which re-creates the overflow "
        "one level up"
    )


def test_touch_targets_are_sized_on_the_narrow_layout():
    """2.5.8 asks 24x24; a financial form filled in on a phone deserves the 44 everything else uses."""
    body = re.search(
        r"@media\s*\(\s*max-width:\s*[\d.]+px\s*\)\s*\{(.*?)\n\}", APP_RULES, re.DOTALL
    ).group(1)
    assert body.count("min-height: 44px") >= 2, "the narrow layout does not size its touch targets"
    # `.door` and `.definition-toggle` draw a meaningful border-bottom, so their target is enlarged with a
    # transparent pseudo-element rather than with padding, which would drag the underline off the text.
    assert re.search(r"\.door::before[^{}]*\{[^}]*height:\s*44px", body, re.DOTALL), (
        "the navigation doors are still a 20px tap target on a phone"
    )
    assert ".definition-toggle::before" in body, (
        "the definition toggle is still a 19px tap target on a phone"
    )


def test_nothing_states_capital_type_by_colour_alone():
    """1.4.1. The two capital hues are 2.92:1 and 2.08:1 on white and 1.41:1 against each other — on a
    greyscale screen or a monochrome print they are one colour. The word in each cell carries the meaning,
    so the rule that hides that word must never be broadened past the grid, where a column header states it
    instead.

    The container and vault surfaces reuse ``.role-row`` for a one-column card, and there ``.cell-capital``
    is the goal's template name and the vault item's kind — the only place either appears.
    """
    hide = re.findall(r"([^{}]*\.cell-capital[^{}]*)\{[^}]*display:\s*none", APP_RULES)
    assert hide, "the .cell-capital rule has moved; re-check that it is still scoped to the grid"
    for selector in hide:
        assert ".role-name ~" in selector, (
            f"{selector.strip()!r} hides .cell-capital outside the grid, deleting the vault item's kind and "
            "the goal's template name"
        )


def test_the_language_in_force_is_stated_by_more_than_a_hue():
    """1.4.1, on the control added for A12 / A26.

    `.door[aria-current]` states the current page with a 2px rule in --accent-line, and the language switch
    borrows the same token — which on its own would be a state visible only in colour. At 4.47:1 the border
    is findable but two buttons differing by a border hue alone are two buttons on a greyscale screen and on
    a monochrome print.

    **Planted violation:** removed everything but `border-color` from the pressed rule. Failed naming the
    properties it wanted. Restored.
    """
    block = re.search(r"\.lang-choice\[aria-pressed=\"true\"\]\s*\{([^}]*)\}", APP_RULES)
    assert block, "the language switch does not state which language is in force"
    body = block.group(1)
    non_colour = [p for p in ("font-weight", "text-decoration", "border-width") if p in body]
    assert non_colour, (
        "the language in force is stated by colour alone; add a channel that survives greyscale"
    )


def test_the_language_switch_introduces_no_new_colour():
    """A51: the palette is the live site's and nothing is invented.

    Every declaration in the switch's rules resolves to a token that already exists, so the whole rule set
    is checkable rather than merely reviewed.
    """
    tokens = set(_tokens())
    for rule in (r"\.lang\s*\{([^}]*)\}", r"\.lang-choice[^{}]*\{([^}]*)\}"):
        for body in re.findall(rule, APP_RULES):
            for used in re.findall(r"var\(\s*(--[a-z0-9-]+)", body):
                assert used in tokens, f"the language switch uses an undefined token {used}"
            assert not re.search(r":\s*#[0-9A-Fa-f]{3,8}", body), (
                f"the language switch states a literal colour: {body.strip()[:80]}"
            )
            assert "rgb" not in body and "hsl" not in body, (
                f"the language switch states a colour outside the palette: {body.strip()[:80]}"
            )


def test_the_chromes_right_hand_end_is_one_container():
    """Two elements each claiming `margin-left: auto` in a flex row split the free space between them.

    That is what the first draft did, and the switch drifted toward the middle of the header as the window
    widened. `.chrome-end` takes the margin; its children sit together.
    """
    end = re.search(r"\.chrome-end\s*\{([^}]*)\}", APP_RULES)
    assert end, ".chrome-end is gone"
    assert "margin-left: auto" in end.group(1)
    who = re.search(r"^\.who\s*\{([^}]*)\}", APP_RULES, re.MULTILINE)
    assert who, ".who is gone"
    assert "margin-left: auto" not in who.group(1), (
        ".who claims the auto margin again; with .chrome-end also claiming it the two split the free space"
    )


def test_the_language_switch_is_not_printed():
    """A member prints a plan and takes it to somebody. A language switch on paper is furniture."""
    body = _print_block()
    assert ".chrome-end" in body or ".lang" in body, (
        "the language switch prints; the container would leave a gap even with its buttons removed"
    )


def test_the_error_notice_differs_by_more_than_a_hue():
    """1.4.1 again. An informational notice and a refusal used to differ by the colour of a 3px rule and by
    nothing else at all."""
    block = re.search(r"\.notice\.error\s*\{([^}]*)\}", APP_RULES)
    assert block, ".notice.error is gone"
    body = block.group(1)
    non_colour = [p for p in ("border-left-width", "font-weight", "text-decoration") if p in body]
    assert non_colour, (
        ".notice.error is distinguished from .notice by colour alone; add a channel that survives greyscale"
    )


def test_the_error_notice_is_not_pushed_away_from_its_form():
    """Every form holds its error node as a direct flex child, so ``.notice``'s own margin stacks on top of
    the flex gap and the refusal ends up a full line clear of the field it refuses."""
    assert re.search(r"\.position-form\s*>\s*\.notice[^{}]*\{[^}]*margin-top:\s*0", APP_RULES)


def test_empty_nodes_do_not_render_as_artefacts():
    """``grid.js`` writes ``cell.prompt || ''`` into a ``.cell-prompt`` that always exists, and the panel
    builds its answer and action regions before there is anything to put in them."""
    assert re.search(r"\.cell-prompt:empty", APP_RULES), (
        "an empty .cell-prompt still paints its margin, which reads as content that failed to load"
    )


def test_the_observation_list_is_spaced():
    """R-031's observations are a plain ``<ul>`` with no severity and no icon, which is right. At eight
    items and a 1.6 line-height it is a wall of text, and every observation is individually short."""
    assert re.search(r"\.cell li \+ li\s*\{[^}]*margin-top", APP_RULES)


# ---------------------------------------------------------------- the document


def test_the_viewport_does_not_forbid_zoom():
    """1.4.4. A member reading a franc figure on a phone in poor light pinches."""
    viewport = re.search(r'<meta name="viewport" content="([^"]+)"', INDEX)
    assert viewport, "no viewport meta"
    content = viewport.group(1)
    assert "user-scalable=no" not in content
    assert "maximum-scale" not in content


def test_the_page_declares_a_language_and_a_colour_scheme():
    """A12: de-CH is the default and ``main.js`` rewrites ``lang`` on every language change, so the
    attribute has to be there to be rewritten. A51: light only, said in the document as well as the sheet."""
    assert re.search(r'<html lang="(de|en)"', INDEX)
    assert re.search(r'<meta name="color-scheme" content="light"', INDEX)
    assert "color-scheme: light" in TOKENS


def test_the_skip_link_is_first_and_reaches_the_main_landmark():
    """The skip link must be the first *element* in the body, whatever attributes it has grown.

    **The assertion used to be a literal `<body>\\s*<a class="skip" href="#main">`**, which made it a test
    of the tag's exact text rather than of its position: adding `data-i18n` to the link (A12's chrome
    hook) or a comment above it failed a test about tab order for reasons that have nothing to do with
    tab order. Comments are stripped and the first tag is compared instead, which is the property — and
    it is strictly stronger, because the old form would also have passed with a focusable element added
    on the same line after the anchor.
    """
    body = INDEX[INDEX.index("<body>") + len("<body>"):]
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
    first = re.search(r"<\s*([a-z]+)([^>]*)>", body, re.IGNORECASE)
    assert first, "the body has no elements"
    tag, attributes = first.group(1).lower(), first.group(2)
    assert tag == "a", f"the first element in the body is <{tag}>, not the skip link"
    assert 'class="skip"' in attributes, f"the first element is not the skip link: {attributes.strip()}"
    assert 'href="#main"' in attributes, "the skip link does not point at the main landmark"
    assert re.search(r'<main id="main" tabindex="-1">', INDEX), (
        "the skip link's target cannot take focus"
    )
    assert re.search(r"\.skip:focus\s*\{", APP_RULES), "the skip link never becomes visible"


def test_no_external_resource_was_added_by_the_accessibility_pass():
    """C-05, restated where it is easiest to break: a print stylesheet is the classic place someone reaches
    for a webfont, and a focus ring is the classic place someone reaches for an icon.

    Comments are stripped first, and this is the A20 trap in miniature: tokens.css explains in prose that
    it uses no @import, and saying so must not be the thing that fails the check for one.
    """
    sources = (
        ("app.css", _strip_comments(APP)),
        ("tokens.css", _strip_comments(TOKENS)),
        ("index.html", re.sub(r"<!--.*?-->", " ", INDEX, flags=re.DOTALL)),
    )
    for name, text in sources:
        assert "@import" not in text, f"C-05: {name} uses @import"
        for match in re.finditer(r"url\(([^)]*)\)", text):
            assert "//" not in match.group(1), f"C-05: {name} loads {match.group(1)} off-origin"


def test_the_gradient_still_appears_exactly_once():
    """A51. The brand's signature device is spent on the wordmark and nowhere else; a restyling pass is
    exactly the kind of work that spreads it to a button, a rule and a panel header without deciding to."""
    uses = re.findall(r"(?:linear|radial|conic)-gradient|var\(--grad-[a-z]+\)", APP_RULES)
    assert len(uses) == 1, f"the gradient is used {len(uses)} times in app.css: {uses}"


def test_no_completion_indicator_was_introduced():
    """R-113 / R-006. The friction is the point: there is to be no CSS a bar, a ring, a meter or a
    percentage could be assembled from without someone writing new rules on purpose."""
    for name, text in (("app.css", _strip_comments(APP)), ("tokens.css", _strip_comments(TOKENS))):
        low = text.lower()
        for marker in ("progress", "meter", "conic-gradient", "stroke-dashoffset", "percent"):
            assert marker not in low, f"R-113: {name} contains {marker!r}"
