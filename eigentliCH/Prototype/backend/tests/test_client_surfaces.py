"""The three surfaces that render what phase 4 built: the Befund, the illustration and the engine runs.

**Why this file exists.** Four things were built behind the API — an engine queue, goal projections, the
Befund and plan-derived action items — and all four were tested and worked. The owner opened the
application again and said *"there is still no output"*, and was right: nothing rendered any of it. So the
guards here are not about whether the services are correct. They are about whether the **surface** is still
attached to them, which is the failure this whole day was.

Three shapes of drift, and each has tests below:

  1. **A door that leads nowhere.** `GET /api/befund` returned a complete six-section report and the chrome
     had three doors. Held by `test_the_befund_is_reachable_from_the_chrome`.
  2. **A branch that renders only the empty case.** `containers.js` printed "no projection" over the top of
     a real illustration, because it had been written when there could not be one and nobody came back.
     Held by the illustration tests, which read `services/illustration.py`'s own constants.
  3. **A vocabulary that exists on one side only.** Five of the six illustration reasons had no string, so
     a member read `containers.illustration_the_goal_names_no_amount` off the screen. Every test below that
     walks a service constant against the string table exists for that: the two lists cannot drift, because
     one of them is read from the code that produces it.

**Every guard was verified by planting the violation, watching it fail, and restoring.** What was planted is
recorded on each test. That is not a formality here — A68 records four absence-shaped guarantees that
stopped holding while the suite stayed green.

The word filters, the C-05 scan, the `innerHTML` ban and the "no member id on the wire" check are NOT
repeated here: `test_client_bundle.py` walks every file under `client/app` and `client/surfaces`, so the new
surfaces are already inside all of them. Re-listing any of those vocabularies here would let this file and
that one come to forbid different words.
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eigentlich.engines import known_engines  # noqa: E402
from eigentlich.models import DONE, FAILED, RUNNING, SUBMITTED  # noqa: E402
from eigentlich.services import engine_inputs  # noqa: E402
from eigentlich.services.befund import ENGINES_WITHHELD_FROM_A_MEMBER, SECTIONS  # noqa: E402
from eigentlich.services.illustration import CAVEATS, UNAVAILABLE_REASONS  # noqa: E402
from eigentlich.services.runs import REFUSAL_REASONS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_i18n_parity import _block  # noqa: E402  (the brace-matching scan, not a second copy of it)

CLIENT = BACKEND.parent / "client"
I18N = CLIENT / "app" / "i18n.js"
INDEX = CLIENT / "index.html"

TODAY = date(2026, 8, 31)


# ============================================================ reading the client


def source(name: str) -> str:
    """One client file with its comments stripped.

    Comments out for the reason `test_client_bundle.py` gives at length: every one of these files explains
    in prose what it deliberately does not do, and a check for the thing it says it avoids would find the
    sentence saying so. Case is kept — these checks are about identifiers.
    """
    text = (CLIENT / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.MULTILINE)


#: One entry of the string table: a single-quoted key, then everything up to the next key at line start.
#: The value span is taken whole rather than matched, because three values in the file are `+`-concatenated
#: across lines and a single-line regex silently truncates them — the same class of quiet wrong answer
#: `test_i18n_parity.py` records twice.
_ENTRY = re.compile(r"^[ \t]*'((?:[^'\\]|\\.)*)'[ \t]*:", re.MULTILINE)
_LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")


def strings(language: str) -> dict[str, str]:
    """`{key: value}` for one language block of `i18n.js`."""
    body = _block(I18N.read_text(encoding="utf-8"), language)
    entries = list(_ENTRY.finditer(body))
    table: dict[str, str] = {}
    for index, match in enumerate(entries):
        end = entries[index + 1].start() if index + 1 < len(entries) else len(body)
        span = body[match.end():end]
        # Every string literal in the value span, concatenated: that is what `+` continuation means.
        table[match.group(1)] = "".join(_LITERAL.findall(span)).replace("\\'", "'")
    return table


def test_the_string_scanner_reads_real_values():
    """Guard on the guard. A scanner returning empty values would make every string test below vacuous —
    which is exactly how `test_i18n_parity.py` once claimed 39 keys against 0.

    **Planted violation:** made `_LITERAL` match nothing. Every value came back empty and this failed.
    Restored.
    """
    de = strings("de")
    assert len(de) >= 300, f"only {len(de)} German entries parsed"
    assert de["chrome.door_befund"] == "Befund"
    assert "Ziele teilen Ihr Vermögen nicht auf" in de["containers.lede"]
    # The `+`-concatenated one, whole rather than truncated at the first line.
    assert de["grid.lede"].endswith("weil sie sich gegenseitig ersetzen können.")
    assert all(value.strip() for value in de.values()), "some value parsed as empty"


def both_languages(key: str) -> None:
    for language in ("de", "en"):
        assert key in strings(language), f"{language} does not define {key!r}"


# C-01 over everything a member reads used to sit here: two tests, one scanning all 718 client strings
# through the outbound gate and one proving that scan was not vacuous (A20's pattern). Both went with
# C-01 on 20 September 2026 (A164). Nothing replaced them — the client's copy is no longer examined
# before a member reads it, which is what the cull bought and what A164 records it cost.


# ============================================================ the fourth door


def test_the_befund_is_reachable_from_the_vault():
    """**The defect this whole file is about.** A complete report behind `GET /api/befund` and no way in.

    It was a DOOR until 4 September 2026 and is now a pane inside the Vault, by the owner's decision under
    item 8 — the target navigation has three destinations and the Befund is the report over what the Vault
    holds. **The guarantee this test makes is unchanged**: the whole join still has to be there, and the
    only thing that moved is where the first link lives. A test that had simply been deleted with the door
    would have taken the guarantee with it.

    Checked as the whole join, because any one link missing is the defect back: a door in the markup, a
    route that answers it, a surface behind the route, and a function in `api.js` that reaches the endpoint.
    A door with no route silently falls through to the grid — `route()` does `ROUTES[name] || ROUTES.plan` —
    which is exactly the shape of failure that looks like a working application.

    **Planted violation, three times:** removed the `befund:` entry from `ROUTES` (the door then rendered
    the grid and this failed); removed the `<a>` from `index.html`; renamed `getBefund`. Each failed naming
    the missing half. All restored.
    """
    main_js = source("app/main.js")
    # One tap from every room of the Vault, which is the condition the move was made under.
    assert re.search(r"\['befund', 'nav\.befund'\]", main_js), (
        "the Befund is not in the Vault's own link row, so it is reachable from nowhere"
    )
    both_languages("nav.befund")
    # And it is NOT a door any more: three destinations, per item 8.
    index = INDEX.read_text(encoding="utf-8")
    assert 'data-route="befund"' not in index
    assert re.search(r"\bbefund:\s*renderBefund\b", main_js), "no route answers #/befund"
    assert re.search(r"function renderBefund\s*\(", main_js), "there is no handler behind the route"
    assert "befund.load(" in main_js and "befund.render(" in main_js

    assert "/api/befund" in source("app/api.js"), "api.js does not reach the route"
    assert "getBefund" in source("surfaces/befund.js"), "the surface does not call it"


def test_the_befund_asks_for_the_language_it_is_rendering_in():
    """A12. `api/befund.py` answers 422 for a language the report is not written in rather than falling back
    to German, so the client has to send the language it is actually showing.

    **Planted violation:** dropped the parameter, leaving `request('/api/befund')`. The German default came
    back for an English member and this failed on the missing parameter. Restored.
    """
    api_js = source("app/api.js")
    assert re.search(r"/api/befund\?\$\{new URLSearchParams\(\{ language \}\)\}", api_js), (
        "the Befund is fetched without stating which language it should be written in"
    )
    assert "befund.load(state.language)" in source("app/main.js")


# ============================================================ the Befund's six sections


def test_the_client_renders_the_sections_in_the_services_own_order():
    """The order is editorial and it belongs to `services/befund.py`: what the plan holds, then what it is
    for, then what was decided, then what carries a date, then what is prepared, then what is not known.

    So the client iterates the payload and **holds no list of its own**. Two things are checked, and the
    second is the one that matters: that no section key is a literal anywhere in the surface. A client with
    its own list would render a second ordering that nobody chose and that no test over the payload sees.

    **Planted violation, twice:** `[...report.sections].sort((a, b) => a.key.localeCompare(b.key))` — failed
    on the sort; and a `const ORDER = ['plan', 'goals', ...]` reordering — failed on the section literals.
    Both removed.
    """
    surface = source("surfaces/befund.js")
    assert re.search(r"for \(const section of report\.sections", surface), (
        "the surface no longer walks the payload's sections in order"
    )
    for forbidden in (".sort(", ".reverse(", "sections.filter("):
        assert forbidden not in surface, f"befund.js {forbidden!r} the report's sections"
    present = [key for key in SECTIONS if f"'{key}'" in surface or f'"{key}"' in surface]
    assert not present, (
        f"befund.js names the sections {present} itself; the order and the membership are the service's"
    )


def test_the_surface_states_no_count_of_anything():
    """C-07 / R-113. The service counts nothing and explains why: naming three empty cells is a list,
    telling a member "3 of 8" is a score. A client can still count the array it was handed.

    Checked as the absence of the operations a count is built from, in this file rather than over the whole
    bundle, because `grid.js` legitimately says "Erfasste Positionen: {n}" about what the member typed —
    which is a statement about their plan, not a proportion of a whole.

    **Planted violation:** added a heading of `${section.facts.length} Angaben`. Failed on `.facts.length`.
    Removed.
    """
    surface = source("surfaces/befund.js")
    for forbidden in ("facts.length}", "sections.length", ".length} ", "Math.round(100"):
        assert forbidden not in surface, f"befund.js builds a count from {forbidden!r}"
    # `facts.length` as a truthiness test is fine and is the empty-section guard; used as a *value* is not.
    assert not re.search(r"text:[^,\n]*\.length", surface), (
        "a length is being rendered as text; that is a count with a sentence around it"
    )


# ============================================================ the member's own words


def _quoted_keys_the_service_can_emit() -> set[str]:
    """Every key `services/befund.py` puts into `Fact.quoted`, read out of the module with `ast`.

    A regex over `quoted={` misses `quoted={**quoted_name, ...}` and misses the dict built one line
    earlier and passed by name. The AST sees both: every dict literal that is either the `quoted` keyword
    argument or assigned to a name starting with `quoted`.
    """
    tree = ast.parse((BACKEND / "eigentlich" / "services" / "befund.py").read_text(encoding="utf-8"))
    found: set[str] = set()

    def harvest(node: ast.AST) -> None:
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.add(key.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "quoted":
            harvest(node.value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("quoted"):
                    harvest(node.value)
    return found


def test_the_scan_of_the_services_quoted_keys_found_something():
    """A20 again: an empty set makes the test below pass by having nothing to check."""
    keys = _quoted_keys_the_service_can_emit()
    assert {"goal_name", "position_labels", "question", "title", "prepared_options"} <= keys, keys


@pytest.mark.parametrize("key", sorted(_quoted_keys_the_service_can_emit()))
def test_every_quoted_key_the_service_emits_has_a_label_in_both_languages(key):
    """`Fact.quoted` holds what the member typed and the renderer puts a label in front of each entry. A key
    with no label renders as the identifier — `position_labels` — above the member's own words.

    Read off `befund.py` rather than listed here, so a section that starts quoting something new fails this
    instead of shipping an identifier onto the screen.

    **Planted violation:** deleted `befund.quoted_reasoning` from the English block. Failed naming it.
    Restored.
    """
    both_languages(f"befund.quoted_{key}")


def test_quoted_material_is_rendered_as_a_quotation_and_never_spliced_into_a_sentence():
    """The reason the two travel in separate fields, and it is not squeamishness.

    `Fact.sentence` is what eigentliCH says and it has passed C-01 in the service's constructor.
    `Fact.quoted` is what the member typed and has passed nothing, because it is not eigentliCH speaking. A
    member who names a goal "Ich sollte mehr sparen" would make their own report unrenderable if the two
    were concatenated — the gate would refuse a sentence they wrote themselves.

    So: a `blockquote` element, and the sentence rendered on its own with no interpolation.

    **Planted violation:** changed the sentence node to
    `text: `${quoted[fact.subject]}: ${fact.sentence}`` — which is the natural, tidy-looking thing to write.
    Failed on the interpolation check. Restored.
    """
    surface = source("surfaces/befund.js")
    assert "h('blockquote'" in surface, "the member's own words are no longer marked as a quotation"
    assert re.search(r"class: 'report-quote'", surface)
    # The sentence is rendered alone. Not `${...fact.sentence...}` and not `fact.sentence +`.
    assert re.search(r"text:\s*fact\.sentence\s*\}", surface), (
        "the composed sentence is no longer rendered on its own"
    )
    assert not re.search(r"\$\{[^}]*fact\.sentence", surface), (
        "the composed sentence is being interpolated with something else"
    )
    assert not re.search(r"fact\.sentence\s*\+", surface), "something is concatenated onto the sentence"
    assert not re.search(r"quoted\[[^\]]*\]\s*\+", surface), "quoted material is concatenated onto something"


def test_c02s_stamp_is_rendered_from_the_provenance_and_not_from_the_field():
    """C-02, in the one place the Befund could grow a derived figure.

    The report projects nothing today, so no fact carries `source: "assumption"` — which is precisely why
    the branch has to be written and pinned now rather than noticed later. It keys off `source`, not off
    whether `assumption_set_id` happens to be set: the service makes that a biconditional, so a fact
    claiming assumption provenance without an id cannot exist and one with an id and another provenance
    cannot either.

    **Planted violation:** removed the stamp entirely. Failed on the missing branch. Restored.
    """
    surface = source("surfaces/befund.js")
    assert re.search(r"fact\.source === 'assumption'", surface), (
        "nothing renders the assumption set id for a figure derived from an assumption"
    )
    assert "fact.assumption_set_id" in surface
    both_languages("befund.assumption_set")


# ============================================================ the illustration (R-133 / C-02)


@pytest.mark.parametrize("reason", UNAVAILABLE_REASONS)
def test_every_illustration_reason_has_a_sentence_in_both_languages(reason):
    """**The second defect, held closed.** There was one reason string —
    `no_assumption_set_published` — and six reasons, so a goal without an amount showed the member
    `containers.illustration_the_goal_names_no_amount`.

    Parametrised over the service's own tuple, so a seventh reason fails here rather than appearing on a
    screen as its own identifier.

    **Planted violation:** deleted `containers.illustration_the_goal_names_no_active_funding` from German.
    Failed naming it. Restored.
    """
    both_languages(f"containers.illustration_{reason}")


@pytest.mark.parametrize("caveat", CAVEATS)
def test_every_caveat_the_illustration_carries_has_a_sentence_in_both_languages(caveat):
    """`services/illustration.py` ships caveats as **keys, not sentences**, and says why: prose emitted from
    a service module is prose that exists in one language only. This is the other end of that decision.

    **Planted violation:** deleted `containers.caveat_an_illustration_and_not_a_forecast` from both blocks.
    Failed on both languages. Restored.
    """
    both_languages(f"containers.caveat_{caveat}")


def test_the_illustration_is_rendered_and_not_only_its_absence():
    """**The defect this test is named after.** `containers.js` rendered `illustration_none` plus a reason
    unconditionally, at a line whose own comment still claimed `illustration` was always null.

    Checked as the substance of the illustration rather than as the presence of a function: the per-role
    breakdown, the per-scenario rates, and the change in francs. R-133's payload is worth nothing on a
    screen that shows one number out of it.

    **Planted violation:** restored the old unconditional paragraph. Failed on the missing `by_role` walk
    and on the missing branch. Restored.
    """
    surface = source("surfaces/containers.js")
    assert re.search(r"if \(!illustration\)", surface), (
        "there is no branch for having an illustration and not having one"
    )
    for field in ("by_role", "scenarios", "change_chf", "amount_after_the_horizon_chf",
                  "probability_as_published", "basis", "caveats", "no_trajectory_because"):
        assert field in surface, f"the illustration's {field} is not rendered"
    assert "illustrationNode(goal, language, roles)" in surface, "nothing calls the renderer"


def test_the_illustration_stamps_the_assumption_set_on_its_figures():
    """C-02, verbatim: "every illustration response returns the assumption_set_id used" — and a payload that
    returns it to a screen that drops it has satisfied nothing.

    **Planted violation:** removed the version and the id from the stamp, keeping `effective_from`. Failed
    on both. Restored.
    """
    surface = source("surfaces/containers.js")
    assert "illustration.assumption_set_id" in surface, "the set's id is not shown"
    assert "illustration.assumption_set_version" in surface, "the set's version is not shown"
    assert "illustration.assumption_set_effective_from" in surface
    both_languages("containers.illustration_assumption_set")


def test_the_illustration_states_both_horizons_and_that_the_rates_do_not_reach_the_goal():
    """C-02's specific requirement on this payload.

    The published set estimates its rates for **one year**; a goal's date is usually years further out; and
    `rates_extended_to_the_goal_horizon` is `false` and never anything else. A screen that printed the goal's
    date above a one-year range without saying so would be showing a member a figure their date does not
    reach — which is why the payload carries both numbers rather than one.

    **Planted violation, twice:** dropped `published_years` and rendered only `goal_years`; then dropped the
    `rates_extended_to_the_goal_horizon` sentence. Each failed naming what was missing. Both restored.
    """
    surface = source("surfaces/containers.js")
    assert "horizon.published_years" in surface, "the horizon the rates were estimated at is not stated"
    assert "horizon.goal_years" in surface, "the goal's own horizon is not stated"
    assert "rates_extended_to_the_goal_horizon" in surface, (
        "the screen does not say that the rates are not extended to the goal's date"
    )
    assert "containers.illustration_not_extended" in surface
    for language in ("de", "en"):
        table = strings(language)
        assert "containers.illustration_horizon_one_year" in table
        assert "containers.illustration_horizon_years" in table
        assert "containers.illustration_not_extended" in table


def test_no_scenario_probability_is_multiplied_into_a_rate():
    """**The owner's own decision, and it is one line from being undone.** A69: the role profiles and the
    scenario probabilities are published side by side and nothing multiplies them, because which
    probabilities weight which horizon is a decision with an owner. `services/illustration.py` refuses to
    compose a blended rate and `tests/test_illustration.py` forbids one appearing in the payload later.

    A screen can do it in one multiplication, and it is the most natural thing in the world to write: one
    "expected" column that a member would read as *the* number.

    **Planted violation:** added a cell rendering
    `formatRate(row.rate * row.probability_as_published, language)`. Failed on the multiplication. Removed.
    """
    surface = source("surfaces/containers.js")
    assert "probability_as_published" in surface, "the published probability is no longer shown at all"
    forbidden = (
        r"probability_as_published\s*\*",
        r"\*\s*row\.probability",
        r"\*\s*[A-Za-z_.]*probability",
        r"probability[A-Za-z_.]*\s*\*",
        r"\breduce\s*\(",  # the other way to build a weighted sum
    )
    for pattern in forbidden:
        assert not re.search(pattern, surface), (
            f"containers.js matches {pattern!r}: a rate and a probability are being combined"
        )
    both_languages("containers.illustration_probability_note")


def test_the_role_name_comes_from_the_content_records_and_not_from_the_string_table():
    """R-111 / D-03: the role definitions are content records the server owns and marks provisional. The
    illustration keys its rates by `growth` / `income` / `stabilisation` / `protection`, which are not words
    a member reads — and the grid already carries the name, per kind of capital, from `roles.json`.

    Copying those names into `i18n.js` would put a product statement in the interface's chrome table, where
    it would drift from the definition it names.

    **Planted violation:** added `containers.role_growth` and read the name from it. Failed on the role
    string existing in the table. Removed.
    """
    surface = source("surfaces/containers.js")
    assert "roles[`${cell.role}|${cell.capital_type}`] = cell.display" in surface, (
        "the role names are no longer read from the grid payload"
    )
    assert re.search(r"function roleDisplayName\s*\(", surface)
    for language in ("de", "en"):
        for role in ("growth", "income", "stabilisation", "protection"):
            assert f"containers.role_{role}" not in strings(language), (
                f"{language} names role {role} in the chrome table; the definition is a content record"
            )


# ============================================================ the run surface (R-301)


def _offered_engines() -> list[str]:
    surface = source("surfaces/runs.js")
    block = re.search(r"const OFFERED_ENGINES = \[(.*?)\];", surface, re.DOTALL)
    assert block, "runs.js no longer states which engines it offers"
    return re.findall(r"'([a-z_]+)'", block.group(1))


def test_the_run_surface_offers_exactly_the_engines_a_member_may_ask_for():
    """The offered list and the manifest directory, held against each other.

    A member-facing picker cannot be built from `known_engines()` at runtime — `test_constraints.py` forbids
    the API package from reaching the engine façade at all, which is C-03's strong form — so the list is in
    the client and this is what stops it drifting.

    **The two exclusions are decisions, not omissions**, and they are the Befund's own two:
    `portfolio_optimiser` ranks instruments (C-01, refused server-side before the plan is even consulted)
    and `score_engine` produces a Score — listing the inputs a Score lacks invites "so what would my score
    be", which is the primitive C-07 forbids.

    **Planted violation, twice:** added `'score_engine'` to the list — failed naming it as withheld; and
    removed `'scenario_generator'` — failed naming it as missing. Both restored.
    """
    offered = _offered_engines()
    expected = sorted(set(known_engines()) - set(ENGINES_WITHHELD_FROM_A_MEMBER))
    assert sorted(offered) == expected, (
        f"the run surface offers {sorted(offered)}; the manifests minus the two withheld are {expected}"
    )
    for withheld in ENGINES_WITHHELD_FROM_A_MEMBER:
        assert withheld not in offered, f"{withheld} is offered to a member"
    for name in offered:
        both_languages(f"runs.engine_{name}")


@pytest.mark.parametrize("reason", REFUSAL_REASONS)
def test_every_refusal_reason_the_service_can_give_has_a_sentence(reason):
    """A refusal is the common answer to this screen and `services/runs.py` names its reasons once so that
    "the API, the client and the tests cannot drift". This is the client half of that sentence.

    **Planted violation:** deleted `runs.refused_requires_a_curator` from both blocks. Failed naming it.
    Restored.
    """
    both_languages(f"runs.refused_{reason}")


@pytest.mark.parametrize("status", [SUBMITTED, RUNNING, DONE, FAILED])
def test_every_run_status_has_a_word_in_both_languages(status):
    """Four statuses, and `failed` reads as "not available" rather than as an error — R-302's own wording.

    **Planted violation:** deleted `runs.status_failed`. Failed naming it. Restored.
    """
    both_languages(f"runs.status_{status}")


def _gaps_the_offered_engines_can_report() -> tuple[set[str], set[str]]:
    """Every absent input and every kind a member could meet on the run screen, from the live manifests.

    Walked over the plans themselves rather than listed, which is the practice
    `test_every_reportable_gap_has_a_member_facing_subject` established in `test_befund.py`: a new engine
    input has to fail a test rather than appear on a screen as `W_L`.

    **Filtered to the two sets `submit` actually attaches to a refusal**, which is not all four gap kinds:
    the plan-blocking ones and `supplied_by_the_caller`. `owned_by_the_engine` — `blend_weight` and its
    like — is engine configuration and never reaches a member, so demanding a member-facing name for it
    would be demanding copy for something nobody is ever shown. Found by this test failing on
    `gap.input_blend_weight`, which was the right answer to the wrong question.
    """
    inputs: set[str] = set()
    kinds: set[str] = set()
    for engine in _offered_engines():
        plan = engine_inputs.plan_for(engine, member_id="anybody", positions=(), today=TODAY)
        for gap in plan.absent:
            if not (gap.blocks_the_plan or gap.kind == "supplied_by_the_caller"):
                continue
            inputs.add(gap.name)
            kinds.add(gap.kind)
    return inputs, kinds


def test_the_gap_walk_found_gaps():
    """A20. With no gaps found, the test below checks nothing at all."""
    inputs, kinds = _gaps_the_offered_engines_can_report()
    assert {"W_L", "initial_wealth", "annual_return"} <= inputs, inputs
    assert {"not_in_the_plan", "needs_an_unpublished_assumption"} <= kinds, kinds


def test_every_gap_a_member_can_meet_is_named_in_their_own_vocabulary():
    """The engines speak `W_L` and `base_snapshot_id`; a member does not.

    Both surfaces that show a gap — the run refusal and the illustration's "why there is no trajectory" —
    read one shared `gap.input_*` / `gap.kind_*` family, and the subjects are word for word the Befund's
    (`services/befund.py::GAP_SUBJECTS`), so a member who reads about an absence in the report and again on
    the run screen reads the same name for it.

    **`AbsentInput.reason` is deliberately not among these strings.** It is the considered sentence in the
    mapping layer, it exists in English only, and a DOM run of the first draft of this screen showed a
    German member four paragraphs of English about `Position.magnitude`. A12 makes member copy bilingual;
    forwarding a monolingual service note is the half-translated product it exists to prevent.

    **Planted violation:** deleted `gap.input_base_snapshot_id` from the English block. Failed naming the
    input and the language. Restored.
    """
    inputs, kinds = _gaps_the_offered_engines_can_report()
    for name in sorted(inputs):
        both_languages(f"gap.input_{name}")
    for kind in sorted(kinds):
        both_languages(f"gap.kind_{kind}")


def test_the_gap_lists_english_service_prose_is_not_rendered():
    """The other half of the decision above, as an absence in the source.

    **Planted violation:** put `gap.reason ? h('p', {text: gap.reason}) : null` back into `gapNode`. Failed
    on the reference. Removed.
    """
    for name in ("surfaces/runs.js", "surfaces/containers.js"):
        surface = source(name)
        assert "gap.reason" not in surface, (
            f"{name} renders AbsentInput.reason, which exists in English only"
        )


def test_the_refusal_is_read_as_an_object_and_not_printed_as_one():
    """`NotQueueable.as_dict()` travels in a 422's `detail` as `{queued, engine, reason, absent: [...]}`.

    `ApiError.detail` is therefore an **object** on this route and a string on every other one, and the
    tidy-looking `String(error.detail)` renders `[object Object]` — over the top of the gap list, which is
    the useful half of the answer and the reason `services/runs.py` attaches it at all.

    **Planted violation:** replaced the 422 branch with the generic one that stringifies `detail`. The
    screen showed `[object Object]` and this failed on the missing branch. Restored.
    """
    surface = source("surfaces/runs.js")
    assert re.search(r"error\.status === 422", surface), "the refusal has no branch of its own"
    assert re.search(r"refusalNode\(error\.detail, language\)", surface), (
        "the refusal object is not read as an object"
    )
    assert "detail.absent" in surface, "the gap list is dropped"
    assert "detail.reason" in surface and "detail.engine" in surface
    both_languages("runs.refused_heading")
    both_languages("runs.gaps_heading")


def test_the_screen_says_a_long_run_is_still_working():
    """`market_signal` declares 1800 seconds. A screen that submits and then sits silent for half an hour is
    indistinguishable from one that has hung, and a member who presses the button again has been taught that
    the product does not work.

    Three things are pinned: the declared budget is stated, the waiting state says so in words, and every
    poll writes when it last asked — so the screen is visibly alive rather than merely unchanged.

    **Planted violation:** removed the `runs.last_checked` write from the poll. The card stopped changing
    between polls and this failed. Restored.
    """
    surface = source("surfaces/runs.js")
    assert "runs.budget_minutes" in surface and "run.timeout_s" in surface, (
        "the declared budget is not stated"
    )
    assert "runs.still_working" in surface
    assert "runs.last_checked" in surface, "a poll leaves no trace, so the screen looks frozen"
    assert "runs.check_failed" in surface, (
        "a dropped request is being turned into something else; one blip is not a failed run"
    )
    for key in ("runs.budget_minutes", "runs.budget_seconds", "runs.still_working",
                "runs.last_checked", "runs.check_failed", "runs.elapsed"):
        both_languages(key)


def test_the_poll_widens_its_interval_and_stops_when_the_screen_is_gone():
    """Two properties of the loop, and both are invisible defects when they break.

    Polling every two seconds for half an hour is 900 requests for one run. And a timer that keeps firing
    after the member has navigated away leaks: `main.js` clears `#main` on every route change AND on every
    language change, so two switches would leave three loops running against a screen nobody is looking at.

    The surface mounts a root of its own and asks whether it is still in the document — checking the
    container would not work, because the container IS `#main` and stays connected while its children are
    replaced.

    **Planted violation, twice:** removed the `root.isConnected` check (the harness then polled a finished
    run and the stub threw); and set `MAX_POLL_MS = FIRST_POLL_MS`. Each failed here. Both restored.
    """
    surface = source("surfaces/runs.js")
    first = int(re.search(r"const FIRST_POLL_MS = (\d+);", surface).group(1))
    widest = int(re.search(r"const MAX_POLL_MS = (\d+);", surface).group(1))
    assert widest > first, "the poll interval no longer widens"
    assert surface.count("root.isConnected") >= 2, (
        "the poll does not check whether its screen is still on screen"
    )
    assert "clearTimeout" in surface, "the pending timer is never cancelled"
    assert re.search(r"const root = h\('div', \{ class: 'runs' \}\)", surface), (
        "the surface no longer mounts a root of its own, so isConnected cannot mean anything"
    )


def test_a_failed_run_renders_no_number():
    """R-302. A failed run's payload carries no numeric field at any depth — not the timeout, not a duration,
    not a zero — because "a screen that can read a number out of a failure cannot tell it from a
    measurement". The client half is that every numeric field is read behind a presence check, so an absent
    figure renders as absent rather than as `undefined` or as `0`.

    **Planted violation:** changed the budget line to `run.timeout_s / 60` with no guard. The failed card
    rendered `NaN Minuten` and this failed on the missing check. Restored.
    """
    surface = source("surfaces/runs.js")
    assert re.search(r"if \(typeof run\.timeout_s !== 'number'\) return null", surface), (
        "the declared budget is rendered without checking that there is one"
    )
    assert re.search(r"typeof run\.duration_ms === 'number'", surface), (
        "the duration is rendered without checking that there is one"
    )
    assert "runs.unavailable_lede" in surface
    both_languages("runs.unavailable_lede")


def test_the_polling_loop_can_end_the_session():
    """A run may take half an hour and a session can expire inside one, so a 401 can arrive long after the
    screen finished loading — which is after `guard` has stopped watching.

    `main.js` hands the surface the same one function its own 401 branch uses, so there is one place that
    forgets the token rather than two.

    **Planted violation:** dropped `onExpired` and let the poll swallow the 401. The loop went on polling a
    dead session forever and this failed on the missing handler. Restored.
    """
    surface = source("surfaces/runs.js")
    assert surface.count("onExpired()") >= 2, (
        "the surface does not end the session on a 401 from its own later requests"
    )
    main_js = source("app/main.js")
    assert re.search(r"function sessionExpired\s*\(", main_js), "there is no single place that ends a session"
    assert "onExpired: sessionExpired" in main_js
    assert main_js.count("sessionExpired()") >= 1, "guard no longer routes its 401 through the same place"


# ============================================================ S-08: every key the payload can carry
#
# The three tests below are the shape this file already uses for befund keys, illustration reasons, caveats
# and run statuses — a service constant walked against the string table, so the two lists cannot drift
# because one of them is read from the code that produces it. **The Know panel was missed**, in two places
# at once, and both had the same consequence: the member read a database identifier.


def _constructed_citation_kinds() -> set[str]:
    """The four `kind` values a citation can carry, read from the two modules that construct them.

    There is no constant to import — `Passage.kind` is documented in a comment — so this reads the
    constructor calls themselves. That is deliberate rather than a shortcut: a fifth kind is added by
    writing one of these calls, so the scan sees it on the same edit.
    """
    services = BACKEND / "eigentlich" / "services"
    know = (services / "know.py").read_text(encoding="utf-8")
    grounding = (services / "grounding.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r"Passage\(\s*\"([a-z_]+)\"", know))
    kinds |= set(re.findall(r"kind=\"([a-z_]+)\"[^\n]*source_id=", grounding))
    kinds |= set(re.findall(r"Ground\(\s*\n\s*kind=\"([a-z_]+)\"", grounding))

    # **The two kinds that are module constants rather than literals at the constructor**, which is how
    # both of them reached a member's screen as a database identifier. `computation` has been emitted
    # since the computation registry landed and never had a sentence in either language; `member_record`
    # arrived with composing on 21 September 2026. A scan over constructor calls cannot see either, and
    # the scan not seeing them is precisely why this test passed while the defect it exists to catch was
    # live — so the constants are read as constants.
    for module in ("computations.py", "member_ground.py"):
        found = re.search(r'^KIND = "([a-z_]+)"',
                          (services / module).read_text(encoding="utf-8"), re.MULTILINE)
        assert found, f"{module} no longer declares a module-level KIND; this scan has gone blind"
        kinds.add(found.group(1))
    return kinds


def test_every_citation_kind_has_a_sentence_in_both_languages():
    """R-171. An answer says what it drew on, and `book_passage` is not a thing anybody says.

    `citationKindLabel` named `vault_item` and `learning_unit` and fell through to the raw kind. Every
    corpus-grounded answer carries `book_passage` or `knowledge_entry`, so those two literal strings were
    what a member read under „Gestützt auf" — in both languages, on the requirement whose entire subject is
    telling a member where an answer came from.

    Parametrised over what the services actually construct rather than over a list retyped here, which is
    what makes the client's fallback to the raw kind stay unused.

    **Planted violation:** deleted `know.citation_knowledge_entry` from the German block. Failed naming it.
    Restored. **And the guard on the guard:** the extraction is asserted to have found all four, because a
    regex that matched nothing would make this pass over an empty set.
    """
    kinds = _constructed_citation_kinds()
    assert kinds == {"vault_item", "learning_unit", "book_passage", "knowledge_entry",
                     "computation", "member_record"}, (
        f"the citation kinds the services construct are {sorted(kinds)}; either a kind was added and this "
        "test has not been told, or the extraction above has stopped matching"
    )
    for kind in sorted(kinds):
        both_languages(f"know.citation_{kind}")
    # The two fields that were in the payload and rendered nowhere.
    both_languages("know.citation_where")
    both_languages("know.citation_sources")
    # **Read over the node that builds a citation, and asserted as a property rather than as the presence
    # of a name — the plant is why.** A first version checked that `citation.sources` occurs in the file.
    # It does, twice: once as the condition and once as the data. Replacing only the *condition* with
    # `false` left the name present, the list unreachable, and this green. So the rule is that no branch in
    # this node is constant: every ternary here is keyed on the payload, which is the thing that makes the
    # sources render when there are sources.
    panel = source("surfaces/know.js")
    node = re.search(r"function citationsNode\s*\(.*?\n\}", panel, re.DOTALL)
    assert node, "citationsNode has moved; this guard can no longer find what it is about"
    body = node.group(0)
    assert "citation.sources" in body, "an authored entry's own sources are still not rendered"
    assert "citation.where" in body, "where a passage sits inside its work is still not rendered"
    assert "citation.sources.map(" in body, "the sources are not built into their own list items"
    for literal in ("false", "true"):
        assert not re.search(rf"\b{literal}\b", body), (
            f"a branch in citationsNode is the constant {literal!r}. A citation field that is tested "
            "against a constant is a field that renders always or never, and R-171's whole subject is "
            "that an answer says what it actually drew on."
        )


def test_every_action_item_trigger_kind_has_a_sentence_in_both_languages():
    """R-174. `know.js` translated `vault_expiry` and printed the other five verbatim.

    `services/derive.py` emits `plan_goal_unfunded`, `plan_goal_target_date_passed`,
    `plan_position_unrevised`, `plan_capital_type_empty` and `plan_onboarding_answer_skipped`, and every
    one of them reached the member as its own store key. Read from `DERIVED_TRIGGER_KINDS` rather than
    listed here, so a sixth derivation cannot ship without its sentence.

    **Planted violation:** deleted `know.trigger_plan_capital_type_empty` from English. Failed naming it.
    Restored.
    """
    from eigentlich.services.derive import DERIVED_TRIGGER_KINDS  # noqa: E402

    # 5 until 3 September 2026; item 6 added the household confirmation being due and an inferred change
    # flagged for confirmation. The loop below is what actually holds the guarantee — this line only
    # makes a change to the set visible in the diff.
    assert len(DERIVED_TRIGGER_KINDS) == 8, "the derivation grew or shrank; check this test still fits"
    for kind in (*DERIVED_TRIGGER_KINDS, "vault_expiry"):
        both_languages(f"know.trigger_{kind}")


def test_every_derived_cause_can_be_named_on_the_screen():
    """R-174's other half, and `api/main.py` states it in its own words: *"an item expandable to its options
    is not expandable to anything if it does not say WHICH goal."*

    `derived_from` was joined onto every item by the route and rendered by nothing. The column holds a
    different kind of identifier per trigger kind — a goal id, a position id, a capital type, a question key
    — so naming it needs one resolver per kind, and a kind with no resolver would silently render no "which"
    at all. That is an absence-shaped failure, which is the one this build has been bitten by five times.

    So every kind `derive.py` emits must appear in the surface's dispatch, and every label it can produce
    must have a string.

    **Planted violation:** removed `'plan_goal_target_date_passed'` from `GOAL_TRIGGERS` in `know.js`. The
    item then rendered its trigger sentence and no goal name, and this failed naming the kind. Restored.
    """
    from eigentlich.services.derive import DERIVED_TRIGGER_KINDS  # noqa: E402

    panel = source("surfaces/know.js")
    assert "item.derived_from" in panel, "the cause is not read from the payload at all"
    for kind in DERIVED_TRIGGER_KINDS:
        assert f"'{kind}'" in panel, (
            f"surfaces/know.js has no resolver for {kind!r}, so an item of that kind renders no 'which'"
        )
    for key in ("know.about_goal", "know.about_position", "know.about_capital", "know.about_question",
                "know.about_unnamed"):
        both_languages(key)
    # The capital-type cause is the vocabulary itself, and it is translated through the grid's own keys so
    # a member reads one word for one column rather than two.
    from eigentlich.models import CAPITAL_TYPES  # noqa: E402

    for capital in CAPITAL_TYPES:
        both_languages(f"capital.{capital}")


def test_the_run_surface_is_reachable():
    """The same join as the Befund's door, one level in: a link, a route, a handler and an api function.

    A room behind the Plan door rather than a door of its own — a run reads what the plan records and writes
    nothing back to it — which is the same argument §3 makes for the containers and the vault.

    **Planted violation:** removed `['runs', 'nav.runs']` from `vaultLinks` (named `surfaceLinks` when this was written). The route still answered and
    nothing led to it, which is the defect this whole file is about, so it failed. Restored.
    """
    main_js = source("app/main.js")
    assert "['runs', 'nav.runs']" in main_js, "nothing links to the run surface"
    assert re.search(r"\bruns:\s*renderRuns\b", main_js), "no route answers #/runs"
    assert "vaultLinks('runs')" in main_js
    both_languages("nav.runs")
    api_js = source("app/api.js")
    for path in ("'/api/runs'", "/api/runs/${encodeURIComponent(runId)}"):
        assert path in api_js, f"api.js does not reach {path}"


# ==========================================================================================================
# The Curator button is a product-wide constraint (update script item 2)
# ==========================================================================================================


def test_the_curator_button_is_in_the_chrome_and_not_only_in_the_panel():
    """Item 2: "reachable in one tap from every screen ... never inside a menu".

    **The defect.** R-170 put the Curator button in the panel's own header and reasoned, correctly, that it
    is then "present whatever else the panel is showing". That holds while the panel is DOCKED. Below
    `know.js::DOCK_QUERY` the panel is a drawer behind a launcher, so on a phone the route to a human was
    two taps and lived inside something that closes.

    Checked as the whole join, the same way the Befund door is: a button in the chrome, a handler that
    opens the chooser, and the chooser exposed by the panel for it to call.

    **Planted violation, twice:** removed `openCurator` from `know.js`'s returned object (main.js then
    called a function that does not exist and this failed); removed the `curatorButton` append from
    `main.js`. Both failed naming the missing half. Restored.
    """
    main_js = source("app/main.js")
    know_js = source("surfaces/know.js")

    assert "curator-button" in main_js, "no Curator button in the chrome"
    # **Defined is not attached.** The first version of this test asserted only that the class name
    # appeared, and a plant that removed the append left it green: the button was constructed and never
    # put in the document. A68's four absence-shaped guarantees are this shape exactly.
    assert re.search(r"\.prepend\(curatorButton\)|\.append\(curatorButton\)", main_js), (
        "the Curator button is created and never attached to the chrome"
    )
    assert "panel.openCurator()" in main_js, "the chrome button opens nothing"
    assert re.search(r"\bopenCurator\s*\(\s*\)\s*\{", know_js), (
        "the panel does not expose a chooser for the chrome to open"
    )
    assert "chromeEnd()" in main_js, "the button is not in the chrome's own container"
    # Not a door: `.doors` is what `aria-current` and the print sheet treat as the set of pages.
    assert 'data-route="curator"' not in INDEX.read_text(encoding="utf-8"), (
        "the Curator button was added as a fifth door; it opens a chooser over the current screen"
    )


def test_there_is_one_curator_chooser_and_the_chrome_calls_it():
    """One implementation, two entry points.

    A second copy of the directory fetch, the ordering and the `POST /api/curator/sessions` write is the
    two-lists defect A73 and A91 both are, in a place where the two copies would differ in what they
    recorded as `opened_from`.
    """
    main_js = source("app/main.js")
    know_js = source("surfaces/know.js")

    assert "/api/curator/sessions" not in main_js, (
        "main.js opens a curator session of its own instead of calling the panel's chooser"
    )
    assert "getCurators" not in main_js, "main.js fetches the curator directory a second time"
    assert know_js.count("async function requestCurator") == 1


def test_the_chrome_button_is_hidden_before_there_is_a_member():
    """A button that opened nothing would be worse than an absent one."""
    main_js = source("app/main.js")
    assert "function syncCuratorButton" in main_js
    assert "panel.available()" in main_js, (
        "the chrome button decides its own visibility instead of mirroring the panel's"
    )
    assert re.search(r"panel\.sync\(\);\s*\n\s*syncCuratorButton\(\);", main_js), (
        "the button's visibility is not recomputed after the panel's, so it lags one screen behind"
    )


def test_the_curator_button_is_translated_like_the_rest_of_the_chrome():
    main_js = source("app/main.js")
    assert "'data-i18n': 'know.curator'" in main_js, (
        "the chrome button carries no data-i18n, so applyChrome cannot retranslate it (A12/A70)"
    )
    both_languages("know.curator")


# ==========================================================================================================
# The ask surface (update script item 1)
# ==========================================================================================================


def test_the_ask_screen_is_the_landing_route_and_is_reachable():
    """Item 1: "Replace `tree` as the landing screen with a new `ask` screen. After sign-in, `goto('ask')`."

    Checked as the whole join, the same way the Befund door is: a route, a handler, a surface behind it and
    the sign-in landing.

    **Planted violation, twice:** left the landing at `#/plan` (this failed on the landing assertion);
    removed the `ask:` entry from `ROUTES`, which made the route fall through to the grid via
    `ROUTES[name] || ROUTES.plan` — the shape of failure that looks like a working application. Restored.
    """
    main_js = source("app/main.js")
    assert re.search(r"\bask:\s*renderAsk\b", main_js), "no route answers #/ask"
    assert re.search(r"function renderAsk\s*\(", main_js), "there is no handler behind the route"
    assert "ask.render(" in main_js, "the handler does not call the surface"
    assert re.search(r"location\.hash\s*=\s*'#/ask'", main_js), (
        "sign-in does not land on the ask screen"
    )
    assert "surfaces/ask.js" in main_js, "the surface is not imported"


def test_nothing_but_the_field_is_above_the_fold():
    """Item 1 names four things by name: "No metrics, no cards, no hero number, no onboarding prompt."

    Read off the surface rather than asserted in prose: the section renders a form and one container for
    everything answered, and the container is appended AFTER the form so an answer cannot push the field
    down the screen.
    """
    ask_js = source("surfaces/ask.js")
    assert re.search(r"h\('section',\s*\{\s*class:\s*'ask'\s*\},\s*\[", ask_js)
    # The form comes before the answers container in the section's children.
    body = ask_js[ask_js.index("h('section', { class: 'ask' }"):]
    assert body.index("form,") < body.index("below,"), (
        "the answer region is rendered above the field, so answers push the field down"
    )
    for forbidden in ("formatAmount", "net_worth", "score", "progress", "percent"):
        assert forbidden not in ask_js, (
            f"the entry surface reaches for {forbidden!r}; item 1 rules out metrics and hero numbers here"
        )


def test_enter_submits_and_shift_enter_breaks_the_line():
    """Item 1's field behaviour, taken from the LU OGD portal."""
    ask_js = source("surfaces/ask.js")
    assert "event.key === 'Enter' && !event.shiftKey" in ask_js
    assert "event.isComposing" in ask_js, (
        "Enter is bound without checking isComposing, so an IME candidate submits the question"
    )
    assert "event.preventDefault()" in ask_js


def test_the_field_grows_to_a_cap_and_then_scrolls():
    """"In a single-line field people write blind." Growing without a cap is the other failure."""
    ask_js = source("surfaces/ask.js")
    assert "MAX_FIELD_HEIGHT" in ask_js
    assert "Math.min(field.scrollHeight, MAX_FIELD_HEIGHT)" in ask_js
    assert "field.style.height = 'auto'" in ask_js, (
        "the height is set without resetting first, so the field can only ever get taller"
    )
    assert re.search(r"overflowY\s*=\s*field\.scrollHeight > MAX_FIELD_HEIGHT", ask_js)


def test_the_answer_survives_a_route_change_and_is_never_recomputed():
    """Item 1: "A completed answer stays on screen until the person starts a new question. Never recompute
    silently on return: a second run can produce a different figure than the one the person already acted
    on."

    The state is module-level, so `render` on a second arrival draws what is there. The guard is that
    `render` itself contains no call to the API — only `submit` does.
    """
    ask_js = source("surfaces/ask.js")
    assert re.search(r"^let state = \{", ask_js, re.MULTILINE), (
        "the answer is not held at module scope, so it cannot survive a route change"
    )
    render_body = ask_js[ask_js.index("export function render("):]
    submit_start = render_body.index("async function submit()")
    before_submit = render_body[:submit_start]
    assert "askKnow(" not in before_submit, (
        "render() asks the question again on arrival — the silent recompute item 1 forbids"
    )
    assert render_body.count("askKnow(") == 1, "the surface asks from more than one place"


def test_the_answer_is_not_persisted_across_a_reload():
    """A figure restored from storage would look as though it had just been computed."""
    ask_js = source("surfaces/ask.js")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in ask_js


def test_every_answer_carries_its_sources_and_one_collapsed_fold():
    """R-171 and item 1's visual instruction. One fold: several disclosures in a row are read as none."""
    ask_js = source("surfaces/ask.js")
    assert "function sourceBar(" in ask_js
    assert "payload.citations" in ask_js
    assert ask_js.count("h('details'") == 1, "more than one disclosure on the answer"
    assert "ask.caveat" in ask_js


def test_the_ask_surface_reuses_the_one_curator_chooser():
    """A refusal offering its own curator route would be a third copy of A115's chooser."""
    ask_js = source("surfaces/ask.js")
    main_js = source("app/main.js")
    assert "/api/curator" not in ask_js, "the ask surface opens a curator session of its own"
    assert "getCurators" not in ask_js
    assert "onCurator: () => panel.openCurator()" in main_js


def test_the_branch_and_boundary_have_strings_in_both_languages():
    """The router's vocabulary reaches the screen as sentences, not as `population_fact`.

    Read from `services/router.py`'s own enum and boundary tuple, so a fourth branch cannot ship without
    its copy — the same join every other vocabulary in this file is held by.
    """
    sys.path.insert(0, str(BACKEND))
    from eigentlich.services.router import BOUNDARIES, Branch  # noqa: E402

    for branch in Branch:
        both_languages(f"ask.branch_{branch.value}")
    for boundary in BOUNDARIES:
        both_languages(f"ask.boundary_{boundary}")


def test_the_named_input_is_offered_with_a_way_to_start():
    """Item 1: branch 2 with an empty Vault "names the single input that would make it personal, and
    offers to start there". The sentence is the server's; this renders it beside a way in."""
    ask_js = source("surfaces/ask.js")
    assert "payload.personalisation" in ask_js
    assert "named.sentence" in ask_js, (
        "the surface composes its own wording instead of rendering the server's fixed phrase"
    )
    assert "ask.start_there" in ask_js


# ==========================================================================================================
# The target navigation (update script item 8)
# ==========================================================================================================


def test_the_chrome_carries_the_three_destinations_and_nothing_else():
    """Item 8: "The `ask` screen carries the other three layers in a persistent header: Vault, Know,
    Market."

    **Planted violation:** left the Plan door in place alongside the Vault door. Failed on the count, which
    is the assertion that matters — a fourth door is how the target IA quietly becomes the old one.
    """
    index = INDEX.read_text(encoding="utf-8")
    doors = re.findall(r'<a href="#/([a-z-]+)"[^>]*class="door"', index)
    assert doors == ["vault", "know", "market"], f"the chrome's doors are {doors}"


def test_ask_is_reachable_from_every_screen_and_is_not_a_door():
    """Item 8: "the same four destinations appear on every screen and `ask` is always reachable."

    The wordmark is the way home. Not a door: `.doors` is the set `aria-current` and the print sheet treat
    as pages, and the entry surface is where you start rather than one of three places you go.
    """
    index = INDEX.read_text(encoding="utf-8")
    assert re.search(r'<a href="#/ask" class="wordmark"', index), (
        "the wordmark does not lead to the ask screen, so there is no way back to it"
    )
    assert 'data-route="ask"' not in index, "ask was added as a fourth door"
    both_languages("chrome.home")


def test_the_vault_door_opens_on_the_plan_pane_and_carries_the_rest():
    """Item 4: the four-role grid "is the primary view **inside the Vault**, not the first screen a member
    sees"."""
    main_js = source("app/main.js")
    assert re.search(r"\bvault:\s*renderVaultHome\b", main_js)
    assert re.search(r"function renderVaultHome\(\)\s*\{\s*return renderPlan\(\);", main_js), (
        "the Vault door does not open on the Plan pane"
    )
    for room in ("plan", "containers", "documents", "befund", "decisions"):
        assert re.search(rf"\['{room}',", main_js), f"{room} is not in the Vault's link row"


def test_the_document_route_was_renamed_and_nothing_still_points_at_the_old_one():
    """`vault` now means the container, so the document table could not go on being called it.

    The rename is the kind that leaves a dead link behind, so this checks both halves: the new route
    answers, and no client file still asks for the old one.
    """
    main_js = source("app/main.js")
    assert re.search(r"\bdocuments:\s*renderDocuments\b", main_js)
    assert "renderVault(" not in main_js, "a caller still names the old handler"

    for name in ("app/main.js", "surfaces/vault.js"):
        assert "#/vault'" not in source(name).replace("href: `#/${route}`", ""), (
            f"{name} still links to #/vault as the document table"
        )


def test_the_actions_pane_and_the_panel_render_one_list():
    """Item 4 puts an Actions pane in the Vault; R-174 keeps the same items in the Know panel.

    Two places to meet one list, not two lists. A second copy of `actionNode` and the "which goal" join
    would drift in the worst possible place — the panel and the pane would disagree about what a member
    has to do.
    """
    main_js = source("app/main.js")
    know_js = source("surfaces/know.js")

    assert re.search(r"\bactions:\s*renderActions\b", main_js)
    assert "know.renderActionList(" in main_js, "the pane does not use the panel's renderer"
    assert know_js.count("export async function renderActionList") == 1
    assert "actionNode(" not in main_js, "main.js renders an action item itself"


def test_the_regime_is_readable_before_sign_in():
    """Item 5: "population-level ... can be shown to anyone — including before sign-in. This is the
    product's most distinctive output at zero data cost."

    Checked as the whole join: an open route, a client call that carries no token, and a `route()` that
    returns the screen BEFORE the session check. Any one of the three missing puts it behind the gate.
    """
    main_js = source("app/main.js")
    assert re.search(r"routeName\(\) === 'regime'", main_js), (
        "the regime route is not reached before the token check"
    )
    before = main_js.index("routeName() === 'regime'")
    gate = main_js.index("if (!session.token()) return renderLogin();", main_js.index("function route()"))
    assert before < gate, "the regime screen is behind the session gate"

    assert "getRegime" in source("app/api.js")
    assert "getRegime" in source("surfaces/regime.js")
    both_languages("regime.title")


def test_the_regime_surface_sends_no_member_id():
    """It has none to send, and a surface that acquired one would have crossed the first boundary."""
    regime_js = source("surfaces/regime.js")
    for forbidden in ("memberId", "member_id", "session."):
        assert forbidden not in regime_js, f"the regime surface reaches for {forbidden!r}"


def test_community_sits_behind_the_market_door_and_not_the_know_door():
    """Item 7 names the Market's four panes — community, services, ventures, build — and item 5 names the
    Know's three, which do not include it."""
    main_js = source("app/main.js")
    assert "function marketLinks(" in main_js
    market_row = main_js[main_js.index("function marketLinks("):]
    market_row = market_row[: market_row.index("}")]
    assert "'community'" in market_row

    know_row = main_js[main_js.index("function knowLinks("):]
    know_row = know_row[: know_row.index("], active)")]
    assert "'community'" not in know_row, "community is still a room behind the Know door"
    assert "'regime'" in know_row, "the Know door lost its Regime pane"


def test_the_community_surface_is_recovered_as_a_shape_and_not_as_a_mock():
    """Item 7: "Recover the community surface from the earlier eigentliCH version rather than rebuilding
    it." The owner ruled on 4 September 2026 that recovery means the shape over the real services.

    The earlier surface placed six named advisers with biographies at hardcoded percentages, with no
    matcher behind any of it. What must survive is the two-ring distinction and the privacy line; what must
    not is the six people.
    """
    network_js = source("surfaces/network.js")

    # Two rings, and the suggested one is allowed to be empty.
    assert "network.connected" in network_js and "network.suggested" in network_js
    assert "network.suggested_empty" in network_js
    both_languages("network.suggested_empty")

    # Item 7's first hard rule, said to the member — the best thing in the original.
    assert "network.privacy" in network_js
    both_languages("network.privacy")

    # None of the earlier version's people came across.
    for invented in ("Anna Weber", "Markus Frei", "Emma Liu", "Thomas", "Sara Keller", "Yves"):
        assert invented not in network_js, f"{invented} was ported from the mock"


def test_the_community_surface_reads_the_real_directory_and_no_member_data():
    """It lists curators, who exist. It touches nothing of the member's — which is the rule the page's own
    privacy line promises, and it should be true of the code as well as of the sentence."""
    network_js = source("surfaces/network.js")
    assert "getCurators" in network_js
    for forbidden in ("getGoals", "getPositions", "getVault", "getBefund", "getRoleGrid"):
        assert forbidden not in network_js, f"the community surface calls {forbidden}"


def test_the_feed_carries_the_reading_rooms_three_sections():
    """Item 5: "it organises around pinned groups, pinned follows and pinned vaults, and that is the shape
    to reuse rather than a generic article list."

    The page at https://stk.sim-tech.ch/ was read on 4 September 2026 and carries exactly those labels.
    """
    sys.path.insert(0, str(BACKEND))
    from eigentlich.services.feed import SECTIONS  # noqa: E402

    assert SECTIONS == ("groups", "follows", "vaults")
    for name in SECTIONS:
        both_languages(f"feed.section_{name}")

    main_js = source("app/main.js")
    assert re.search(r"\bfeed:\s*renderFeed\b", main_js)
    assert re.search(r"\['feed', 'feed\.title'\]", main_js), "the Feed is not a pane behind the Know door"


def test_an_empty_section_says_why_rather_than_being_dropped():
    """A missing section looks like a build error; a section of placeholders is a lie. Both structural
    reasons carry a string, and a section that is merely empty for this member says something different."""
    sys.path.insert(0, str(BACKEND))
    from eigentlich.services.feed import NO_OBJECT  # noqa: E402

    for reason in NO_OBJECT.values():
        both_languages(f"feed.empty_{reason}")
    both_languages("feed.empty_for_you")

    feed_js = source("surfaces/feed.js")
    assert "empty_reason" in feed_js
    assert "feed.empty_for_you" in feed_js, (
        "the surface cannot tell a structurally empty section from one this member has nothing in"
    )


def test_the_feed_does_not_claim_an_ordering_it_does_not_have():
    """Item 5 asks for the feed to be ordered by what follows from what the member has read. Nothing
    records what they have read, so the payload says how it IS ordered and the screen shows it."""
    sys.path.insert(0, str(BACKEND))
    from eigentlich.services import feed as feed_service  # noqa: E402
    import inspect

    source_text = inspect.getsource(feed_service)
    assert "content_order" in source_text
    assert "no_read_history_recorded" in source_text
    both_languages("feed.ordering_note")
    assert "feed.ordering_note" in source("surfaces/feed.js")


def test_an_item_that_declares_nothing_renders_without_a_tap():
    """Item 5: "An item that cannot be personalised within its declared inputs gets no tap." Not a
    disabled control — a greyed-out tap is a promise the product is not keeping."""
    feed_js = source("surfaces/feed.js")
    assert "if (!hook.tappable) return null;" in feed_js
    assert "disabled" not in feed_js
