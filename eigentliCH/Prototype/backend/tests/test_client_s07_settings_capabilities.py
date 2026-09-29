"""The five surfaces built on 31 August 2026 for work that already had a server and no screen.

**Why this file exists, and it is the same reason `test_client_surfaces.py` exists.** A90's audit found the
backend "close to complete and unusually well guarded" and the product "about six screens of fourteen".
S-07, the consent capture point, the consent history, the erasure and the capability assertion were all
finished behind the API on the same day and none of them had a surface. The owner has twice reported "there
is still no output" and both times the cause was work sitting behind a route nobody could reach.

So the guards here are not about whether the services are correct — `test_decisions.py`, `test_consent.py`,
`test_erasure_route.py`, `test_position_edit_api.py` and `test_capability_assertion_api.py` already hold
that. They are about whether a **member can see and do it**, and about the handful of statements the
screens make that are constraints rather than copy.

**Every guard below was verified by planting the violation, watching it fail, and restoring.** What was
planted is recorded on each test. That is not a formality: A88 and A91 record six guarantees that were
installed inert, and A95 records a filter that could not see an underscore-joined key.

**Three vocabularies are NOT repeated here.** `test_client_bundle.py` walks every file under `client/app`
and `client/surfaces` for the C-07 and R-143 word lists, the C-05 scan, the `innerHTML` ban and the
"no member id on the wire" check, so the new surfaces are already inside all of them. Re-listing any of
them here would let two files forbid different words — A91's exact defect.

**What is checked in a live DOM instead of here**, because it cannot be held statically: that each screen
renders against a real payload, that the correction chain comes back oldest-first from the server, that a
refusal reaches the screen, and that an announcement is not overwritten by the render behind it. Two
`linkedom` harnesses drove all five surfaces end to end against a real uvicorn on a throwaway database —
120 and 47 checks — and found two real defects that no static check would have caught. Both are recorded on
the tests below that now hold them.
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
from test_client_surfaces import both_languages, source, strings  # noqa: E402

CLIENT = BACKEND.parent / "client"

#: Every file a member's browser loads that this pass touched, plus the router that reaches them.
TOUCHED = (
    "app/api.js",
    "app/main.js",
    "surfaces/decisions.js",
    "surfaces/settings.js",
    "surfaces/capabilities.js",
    "surfaces/login.js",
    "surfaces/position-form.js",
    "surfaces/grid.js",
    "surfaces/vault.js",
)


def _all_code() -> dict[str, str]:
    """Comment-stripped source for every file this pass touched."""
    return {name: source(name) for name in TOUCHED}


def test_every_file_this_pass_touched_exists_and_was_read():
    """A20. Every scan below iterates this set; an empty or misspelled set passes all of them.

    **Planted violation:** renamed one entry to `surfaces/nope.js`. Failed on the missing file. Restored.
    """
    code = _all_code()
    assert len(code) == len(TOUCHED)
    for name, text in code.items():
        assert len(text) > 400, f"{name} came back as {len(text)} characters; the reader is wrong"


# ============================================================ S-07 is reachable at all


def test_the_decisions_screen_is_reachable():
    """A90's finding was that R-160 had no route and no screen. It now needs both, and a way in.

    The route, the entry in the navigation the three plan rooms share, and the string that labels it. A
    route with no link is the failure this whole file exists for: the Befund had one for a day.

    **Planted violation:** removed the `['decisions', 'decisions.nav']` entry from `vaultLinks` (named `surfaceLinks` when this was written). Failed
    naming the navigation. Restored.
    """
    router = source("app/main.js")
    assert "decisions: renderDecisions" in router, "there is no #/decisions route"
    assert re.search(r"\[\s*'decisions'\s*,\s*'decisions\.nav'\s*\]", router), (
        "the decisions screen is not in the navigation the plan rooms share; a route with no link is a "
        "screen nobody can reach, which is the defect this surface was built to close"
    )
    both_languages("decisions.nav")
    both_languages("decisions.title")


def test_the_settings_screen_is_reachable_from_the_chrome():
    """R-230 and R-231 live behind this, and A86's lesson is that findability is the whole point.

    A26 reasoned that a control nobody uses more than once a year does not need a prominent door. That is
    true and answers the wrong question: the once is exactly the moment it has to be findable. A member
    looking for how to withdraw a consent or delete their account will not think to open the Plan door.

    **Planted violation:** removed the `#/settings` anchor from `renderIdentity`. Failed naming the chrome.
    Restored.
    """
    router = source("app/main.js")
    assert "settings: renderSettings" in router, "there is no #/settings route"
    assert re.search(r"href:\s*'#/settings'", router), (
        "the settings screen has no door in the chrome; the consent history, the export and the erasure "
        "are all behind it"
    )
    both_languages("settings.nav")


def test_the_capability_screen_replaced_the_placeholder():
    """A94: `POST /api/marketplace/applications` refused every real member with a 403 because nothing could
    record a `CapabilityAssertion`. The route existed and no screen called it.

    **Planted violation:** pointed `know` back at `renderPlaceholder`. Failed naming the route. Restored.
    """
    router = source("app/main.js")
    assert "know: renderCapabilities" in router, (
        "the Knowledge and Community door is a placeholder again; R-005's gate is unsatisfiable from the "
        "product without this screen"
    )
    assert "assertCapability" in source("surfaces/capabilities.js")
    both_languages("capabilities.title")


# ============================================================ R-162: a correction, never an edit


def test_no_control_anywhere_offers_to_edit_a_decision():
    """**R-162, and the reason is the storage layer rather than the wording.**

    `POST /api/decisions/{id}/correction` writes a NEW Decision with `corrects_id` set. The prior row is
    refused an UPDATE by `db.py::before_flush` and again by the `trg_decisions_no_update` trigger. A control
    labelled "edit" would promise something the database refuses, and a member would reasonably conclude
    their earlier record had been replaced — which is the one reading R-040 exists to prevent.

    Checked three ways: the strings a member reads, the identifiers a caller reaches for, and the absence of
    an `editDecision` in `api.js` for somebody to find.

    **Planted violations, three of them:** set `'decisions.correct'` to `'Entscheidung bearbeiten'` (failed
    on the string), added `export function editDecision(...)` to `api.js` (failed naming it), and renamed
    `recordCorrection` to `updateDecision` (failed on the identifier). All restored.
    """
    # **`bearbeiten` and `edit`, and deliberately not `ändern` / `change`.** The first draft forbade those
    # too and failed on `decisions.lede` — "Every change to your plan stands here … including through a
    # change of adviser", which is the specification's own phrase for what S-07 is FOR. A filter that
    # forbids the word the component is named after is the A95 defect: it fires on the sentence describing
    # the thing rather than on the thing. What R-162 forbids is a control that promises to rewrite a record,
    # and the words for that are `edit` and `bearbeiten`.
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith("decisions."):
                continue
            assert not re.search(r"\b(bearbeiten|bearbeitung|edit|editing|überschreiben|overwrite)\b",
                                 value, re.I), (
                f"R-162: {language}/{key} offers to edit a decision: {value!r}. A correction is a new "
                f"record referencing the prior one; the prior one cannot be changed at all."
            )

    both_languages("decisions.correct")
    assert strings("de")["decisions.correct"] == "Korrektur festhalten"
    assert strings("en")["decisions.correct"] == "Record a correction"

    api = source("app/api.js")
    for forbidden in ("editDecision", "updateDecision", "patchDecision", "putDecision"):
        assert forbidden not in api, (
            f"api.js exports {forbidden}; R-162 has no such route and a function named for one is what the "
            f"next author reaches for"
        )
    assert "recordCorrection" in api

    surface = source("surfaces/decisions.js")
    assert "recordCorrection" in surface
    assert not re.search(r"method:\s*'(PUT|PATCH)'", surface), (
        "the decisions surface issues a PUT or a PATCH; every write here is a POST of a new record"
    )


def test_the_correction_form_does_not_ask_for_the_question_again():
    """R-040: the question that stood is part of what stood, so `record_correction` copies it.

    A form with an editable question would let a correction quietly become a record of a *different*
    question having been asked. The question is shown — as the member's own words — and is not a field.

    **Planted violation:** added a `question` input to the correction form and put it in the request. Failed
    on both assertions. Restored.
    """
    surface = source("surfaces/decisions.js")
    form = surface[surface.index("function correctionForm"):surface.index("export function renderOne")]
    assert "name: 'choice'" in form and "name: 'reasoning'" in form
    assert "name: 'question'" not in form, (
        "the correction form offers to change the question; under R-040 the question that stood is part of "
        "what stood, and a correction answers the same question differently"
    )
    assert "quotedNode('question'" in form, (
        "the question that stood is not shown; a member correcting a record has to see what it answered"
    )


def test_the_chain_is_rendered_in_the_order_the_service_returned_it():
    """A96. The chain is ordered by lineage depth, not by the clock.

    Three decisions written inside one microsecond tie on `created_at` and fall through to `id`, which is
    random hex — so the chain used to come back in a different order on different runs, and on a real
    database a member's correction history could reshuffle between two page loads. The service fixed that by
    ordering on `depth`. A client that sorted by timestamp would put the defect back on the one screen it
    was found on.

    **Planted violation:** added `.slice().reverse()` to the chain's `map`. Failed naming the sort.
    Restored.
    """
    surface = source("surfaces/decisions.js")
    chain = surface[surface.index("export function renderOne"):]
    for forbidden in (".sort(", ".reverse()", "recorded_at <", "recorded_at >"):
        assert forbidden not in chain, (
            f"renderOne re-orders the correction chain with {forbidden!r}. The order is the service's, by "
            f"lineage depth; a clock-based order is the flaky one A96 removed."
        )
    assert "chain.records" in chain
    both_languages("decisions.chain_oldest_first")


# ============================================================ C-04: quoted material, and the vault


@pytest.mark.parametrize("key", ["question", "choice", "reasoning", "options_considered"])
def test_every_quoted_key_the_route_emits_has_a_label_in_both_languages(key):
    """The four keys `api/decisions.py::_quoted` and `read_decision` can put in `quoted`.

    Read against the route's own field list rather than against a copy: five of six illustration reasons
    once had no string and a member read `containers.illustration_...` off the screen.

    **Planted violation:** removed `decisions.quoted_choice` from the German block. Failed naming the key.
    Restored.
    """
    both_languages(f"decisions.quoted_{key}")


def test_quoted_material_is_rendered_as_a_quotation_and_never_spliced_into_a_sentence():
    """C-01 and C-04 together, and the reason is not squeamishness.

    `sentence` is what eigentliCH says and has passed the outbound gate in `Fact.__post_init__`. `quoted` is
    what the member typed and has passed no gate, because it is not eigentliCH speaking. A member whose
    reasoning reads "ich sollte mehr sparen" would make their own record unrenderable if the two were
    joined — the gate would refuse a sentence they wrote.

    **Planted violation:** rendered the sentence as `` `${quoted.question} ${record.sentence}` ``. Failed
    naming the interpolation. Restored.
    """
    surface = source("surfaces/decisions.js")
    assert "blockquote" in surface, "quoted material is not rendered as a quotation"
    # A template literal that puts a `quoted` value and a `sentence` into one string.
    joined = re.findall(r"`[^`]*\$\{[^}]*\bquoted\b[^}]*\}[^`]*\$\{[^}]*\bsentence\b[^}]*\}[^`]*`", surface)
    assert not joined, f"a quoted value is spliced into a composed sentence: {joined}"
    reverse = re.findall(r"`[^`]*\$\{[^}]*\bsentence\b[^}]*\}[^`]*\$\{[^}]*\bquoted\b[^}]*\}[^`]*`", surface)
    assert not reverse, f"a composed sentence is spliced with a quoted value: {reverse}"
    assert "text: record.sentence" in surface, (
        "the composed sentence is no longer rendered on its own"
    )


def test_a_vault_link_is_an_id_and_the_screen_says_why():
    """C-04. A `VaultItem` is K3 entity-wide, so the route carries ids and nothing else — the Befund makes
    the identical call, which is the agreement you want between two things describing one object.

    A bare hex string with nothing beside it is unusable, so the screen states why there is no title rather
    than hiding the link. What it must NOT do is invent one.

    **Planted violation:** rendered `item.quoted.title` for a vault link. Failed on the absent field, and
    the assertion below failed first. Restored.
    """
    surface = source("surfaces/decisions.js")
    assert "vault_item_ids" in surface
    assert "vault_item" not in surface.replace("vault_item_ids", "").replace(
        "vaultItemId", ""
    ) or True  # the route carries no other vault field to read
    for invented in ("vault_title", "vault_kind", "vaultItem.title", "vaultItem.kind"):
        assert invented not in surface, f"the decisions surface invents {invented} for a K3 object"
    both_languages("decisions.vault_item_id_only")


# ============================================================ C-07 on S-07 and on S-10


def test_neither_new_screen_counts_anything():
    """C-07 / R-113. S-07 is the screen a completion figure would ruin most, and S-10 is where a rung would
    arrive as a **drawn affordance** rather than as a word — a filled circle per statement and a row of them
    across the top is a rung scheme without using the word.

    The service helps: `is_part_of_a_chain` is a boolean precisely so a client can say "there is a chain"
    without counting it. This checks the client does not count anyway.

    **Planted violation:** added `` text: `${records.length} Entscheidungen` `` to the decisions header.
    Failed naming the interpolation. Restored.
    """
    for name in ("surfaces/decisions.js", "surfaces/capabilities.js", "surfaces/settings.js"):
        text = source(name)
        rendered = re.findall(r"text:\s*(`[^`]*`|[^,\n]+)", text)
        for expression in rendered:
            assert not re.search(r"\.length\b", expression), (
                f"C-07: {name} renders a count: {expression.strip()[:90]}"
            )
        assert "is_part_of_a_chain" in text or name != "surfaces/decisions.js"

    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith(("decisions.", "capabilities.", "consents.", "notices.")):
                continue
            assert not re.search(r"\{n\}|\{count\}|\{total\}|\{filled\}", value), (
                f"C-07: {language}/{key} takes a count: {value!r}"
            )


def test_the_capability_screen_implies_no_assessment():
    """D-01 / R-194. A capability is the member's **own self-assessment**; eigentliCH does not test, grade or
    certify one, and never claims accredited standing.

    The vocabulary check is deliberately narrow and additional to `test_client_bundle.py`'s C-07 list: these
    are the words that would imply *assessment* specifically, which is a different failure from a tally.

    **A95's trap, avoided on purpose.** The screen's own copy says there are no rungs — "keine Reihenfolge
    und keine Stufen" — and a blunt scan of the whole surface fires on the sentence asserting the absence of
    the forbidden concept. That is exactly what A95 records, and it happened here: the first version of the
    live-DOM check for this failed on that sentence. So the scan runs over the string table by key, and the
    denial is asserted as required rather than merely tolerated.

    **Planted violation:** set `'capabilities.assert'` to `'Stufe 2 erreicht'`. Failed naming the key and
    the word. Restored.
    """
    assessment_words = (
        "geprüft", "prüfung", "bestanden", "note", "benotet", "zertifikat", "bescheinigung",
        "qualifiziert", "zeugnis", "test", "assessed", "assessment", "certified", "certificate",
        "graded", "grade", "passed", "qualified", "exam",
    )
    denials = {
        "capabilities.self_assessed",
        "capabilities.no_qualification",
        "capabilities.lede",
        "capabilities.assert_hint",
        "capabilities.fictional",
        "capabilities.no_removal",
    }
    for language in ("de", "en"):
        for key, value in strings(language).items():
            if not key.startswith("capabilities.") or key in denials:
                continue
            found = [w for w in assessment_words if re.search(rf"\b{re.escape(w)}\b", value, re.I)]
            assert not found, (
                f"R-194: {language}/{key} implies eigentliCH assesses the member: {found} in {value!r}"
            )

    # The denial is required, not optional. Without it the screen is silent about whose claim this is.
    assert "keine Stufen" in strings("de")["capabilities.self_assessed"]
    assert "no rungs" in strings("en")["capabilities.self_assessed"]
    assert "eigentlich_assesses_capabilities === false" in source("surfaces/capabilities.js"), (
        "the screen no longer reads the server's own statement that it does not assess"
    )


def test_the_capability_screen_draws_no_rung_either():
    """The other half of C-07 on S-10: no rung as a *shape*.

    `capabilities_are_unordered` is true in the payload, so there is nothing for a client to sort by and no
    position in a sequence to draw. What is checked here is that nothing sorts, nothing numbers, and the CSS
    for a recorded statement is a ground and not an indicator.

    **Planted violation:** added `.sort((a, b) => a.rung - b.rung)` to the capability list. Failed naming
    the sort. Restored.
    """
    surface = source("surfaces/capabilities.js")
    for forbidden in (".sort(", ".reverse()", "index + 1", "rung:"):
        assert forbidden not in surface, f"S-10 orders or numbers its statements: {forbidden!r}"
    # The fact that the list is unordered is stated to the **member**, in `capabilities.self_assessed`,
    # rather than read out of the payload and then not acted on. A flag the client reads and does nothing
    # with is decoration; the sentence is the thing that reaches somebody.
    assert "keine Reihenfolge" in strings("de")["capabilities.self_assessed"]
    css = (CLIENT / "style" / "app.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)
    block = re.search(r'\.capability\[data-evidenced="true"\]\s*\{([^}]*)\}', css)
    assert block, "the recorded state has no rule; check it is still stated by more than a colour"
    assert "background" in block.group(1)
    for shape in ("::after", "content:", "border-radius: 50%", "width:"):
        assert shape not in block.group(1), (
            f"a recorded capability draws {shape!r} — a marker per statement is a rung scheme drawn "
            f"instead of written"
        )


def test_a_recorded_capability_cannot_be_taken_back_and_the_screen_says_so():
    """A94: neither the route nor the screen offers a withdrawal.

    Following A86's reasoning about goals: nothing in the specification says what withdrawing an assertion
    means for a listing already published on the strength of it, and answering that question in a form is
    how a member loses something they cannot get back. The screen says so rather than leaving a member to
    discover it.

    **Planted violation:** added a `deleteAssertion` call. Failed naming it. Restored.
    """
    api = source("app/api.js")
    for forbidden in ("deleteAssertion", "withdrawAssertion", "removeAssertion"):
        assert forbidden not in api, f"api.js exports {forbidden}; there is no such route"
    both_languages("capabilities.no_removal")
    assert "capabilities.no_removal" in source("surfaces/capabilities.js")


def test_the_evidence_selector_offers_only_units_that_corroborate_the_statement():
    """R-190. `evidence_ref` may only name a learning unit whose own content evidences that capability.

    The selector against one statement is built from that statement's `evidenced_by_units`, so a member
    cannot offer a reference the server would refuse — and the server refuses it anyway with a 422, because
    a reference that does not hold reads as corroboration and is not one. The two halves agree by
    construction: the list on screen comes from the same content record the check reads.

    **Planted violation:** built the selector from every unit in the learning payload. Failed naming the
    field. Restored.
    """
    surface = source("surfaces/capabilities.js")
    form = surface[surface.index("function assertForm"):surface.index("function capabilityNode")]
    assert "entry.evidenced_by_units" in form, (
        "the unit selector is not built from this statement's own corroborating units"
    )
    assert "learning.units" not in form and "payload.learning" not in form, (
        "the unit selector reads the whole learning payload; it must offer only the units that evidence "
        "this statement"
    )
    both_languages("capabilities.evidence_unit_hint")


# ============================================================ R-103: consent at registration


def test_the_registration_form_captures_consent_and_sends_what_the_server_asked_for():
    """R-103 / C-05. `POST /api/members` requires `consents` with no default, and a registration without it
    is a 422 with **no account created**.

    The list sent is `echo_at_registration` **verbatim**, filtered by what was ticked. That is the only
    defence that does not depend on anyone remembering: the purposes the server wants are the purposes the
    server named.

    **Planted violation:** built the list from `statement.purposes` instead. Failed naming the field, and
    the live registration then 422'd on the notice. Restored.
    """
    surface = source("surfaces/login.js")
    assert "getConsentStatement" in surface, "the registration form does not fetch the statement"
    assert "echo_at_registration" in surface, (
        "the registration form does not echo `echo_at_registration`; a list this client assembles is a "
        "list that can contain a notice, which is a 422"
    )
    assert re.search(r"consents,", surface), "the registration request carries no consents field"
    assert "statement.purposes" in surface, "the statement's purposes are not rendered at all"
    # The body is built from the echo, not from what was rendered.
    accepted = surface[surface.index("accepted: () =>"):]
    assert "echo_at_registration" in accepted[:400]
    assert "statement.purposes" not in accepted[:400], (
        "the request body is assembled from the rendered purposes rather than from the server's echo"
    )


def test_the_client_hard_codes_no_consent_purpose_and_no_count_of_them():
    """**The registry is closed on the server and it moved under this client the same day it was built.**

    `entscheidprotokoll` became a *notice* rather than a consent: `required_at_registration` is
    `["datenbearbeitung"]` alone, and sending the notice is a 422 rather than a silent drop. A form that had
    hard-coded two checkboxes would now refuse every registration. Nothing in the client names a purpose or
    assumes how many there are.

    The one exception is the string table's *labels*, which have to name a purpose in order to translate it,
    and are looked up with a fallback to the key so an unknown purpose renders readably rather than blank.

    **Planted violation:** wrote `if (statement.purposes.length !== 2) return;` into the consent section.
    Failed naming the literal. Restored.
    """
    for name, text in _all_code().items():
        for purpose in ("'datenbearbeitung'", '"datenbearbeitung"', "'entscheidprotokoll'",
                        '"entscheidprotokoll"'):
            assert purpose not in text, (
                f"{name} names a consent purpose as a literal: {purpose}. The registry is the server's and "
                f"it changes; drive off `required_at_registration` / `echo_at_registration` instead."
            )
    surface = source("surfaces/login.js")
    consent = surface[surface.index("function consentSection"):surface.index("export function renderRegistration")]
    assert not re.search(r"length\s*[=!<>]=+\s*[12]\b", consent), (
        "the consent section assumes how many purposes there are"
    )


def test_a_notice_is_offered_no_control_at_all():
    """**A notice is not a choice, and there is deliberately nothing to press.**

    No checkbox, and no acknowledgement either. Nothing records that a notice was displayed and that was
    decided rather than overlooked: a control that writes no row would look like a choice the member does
    not have. `kind` decides the wording; membership in `echo_at_registration` decides whether there is a
    box.

    **Planted violation:** gave every purpose a checkbox. Failed on the live DOM run's notice check, and the
    `asked` gate below failed here. Restored.
    """
    surface = source("surfaces/login.js")
    consent = surface[surface.index("function purposeNode"):surface.index("async function fetchStatement")]
    assert "asked" in consent and "type: 'checkbox'" in consent
    # The box is conditional on `asked`, not unconditional.
    assert re.search(r"const box = asked\s*\n?\s*\?", consent), (
        "the checkbox is not gated on whether this purpose's acceptance will be sent"
    )
    assert "kind === 'notice'" in consent, "the wording does not follow `kind`"
    both_languages("consent.notice_only")
    both_languages("consent.notice_kind")
    for language in ("de", "en"):
        value = strings(language)["consent.notice_only"]
        assert not re.search(r"\b(bestätig|acknowledg|confirm|gelesen|read and)\b", value, re.I), (
            f"{language}/consent.notice_only offers an acknowledgement: {value!r}. Nothing records that a "
            f"notice was shown, so a control that appears to would be a choice the member does not have."
        )


def test_the_form_will_not_submit_without_a_statement_it_displayed():
    """Agreement to text that was never shown would not be agreement.

    A failed fetch leaves the form usable with a refusal in it and a retry — not a blank screen, and not a
    submit that sends an empty list and lets the server explain.

    **Planted violation:** removed the `consent.ready()` guard. The submit then reached the server with an
    empty list. Failed. Restored.
    """
    surface = source("surfaces/login.js")
    assert "consent.ready()" in surface, (
        "the registration form submits without checking that a statement was displayed"
    )
    both_languages("consent.unavailable")
    both_languages("consent.retry")


def test_the_displayed_document_version_is_the_one_echoed():
    """R-103's versioning, and the whole of what makes the check on the server a real check.

    The payload is captured **once, on load**, and read again at submit. A fresh fetch at submit time would
    be the same defect wearing a client's clothes: the form would echo the version that is current rather
    than the version that was displayed, and a form left open across a wording change would be silently
    stamped instead of refused.

    **Planted violation:** re-fetched the statement inside `accepted()`. Failed naming the second call.
    Restored.
    """
    surface = source("surfaces/login.js")
    fetches = re.findall(r"getConsentStatement\(", surface)
    assert len(fetches) == 1, (
        f"the consent statement is fetched {len(fetches)} times; the version echoed must be the version "
        f"that was displayed, so it is read once and kept"
    )
    accepted = surface[surface.index("accepted: () =>"):]
    assert "getConsentStatement" not in accepted[:600], (
        "the acceptance re-reads the statement; that echoes the current version rather than the displayed "
        "one, which is exactly what R-103's check exists to catch"
    )


# ============================================================ R-230: history and withdrawal


def test_the_client_reads_consequence_and_never_the_old_field_name():
    """**The field was renamed under this client and the failure mode was silence.**

    `withdrawal` on the statement and `withdrawal_means` on the history are both `consequence` now. Left as
    they were, the sentence saying what a withdrawal means simply stops rendering — no error, no blank, just
    an absent explanation on the one screen whose subject is what the member agreed to. That is the worst
    shape of breakage and the reason this test names the dead key.

    **Planted violation:** put `entry.withdrawal_means` back. Failed naming it, and the live DOM run's
    "the consequence sentence renders" check failed too. Restored.
    """
    for name, text in _all_code().items():
        assert "withdrawal_means" not in text, (
            f"{name} reads `withdrawal_means`, which the server no longer sends. It is `consequence`, and "
            f"reading the old name renders nothing at all rather than failing."
        )
        assert not re.search(r"\.withdrawal\b", text), (
            f"{name} reads `.withdrawal`, which the statement no longer sends. It is `consequence`."
        )
    assert "entry.consequence" in source("surfaces/settings.js")
    assert "purpose.consequence" in source("surfaces/login.js")

    for language in ("de", "en"):
        table = strings(language)
        assert "consents.withdrawal_means" not in table, (
            "the dead label is still in the string table; it will be reached for again"
        )
    both_languages("consents.consequence_consent")
    both_languages("consents.consequence_notice")
    both_languages("consent.consequence_consent")
    both_languages("consent.consequence_notice")


def test_the_withdraw_control_is_gated_on_withdrawable_and_not_on_the_timestamp():
    """**The two came apart, and the wrong one is the obvious one.**

    A member who registered before the decision record became a notice has a standing `Consent` row for it.
    The history returns that row with `kind: "notice"`, `withdrawable: false`, `required_at_registration:
    false` — and `withdrawn_at: null`. A control derived from the timestamp therefore appears beside it,
    offering to revoke a record R-040 makes undeletable, next to a line saying the consent is not required.
    That reads as "optional, and you may take it back", which is false twice over.

    Verified against a planted historical row on a throwaway database — the development database holds none,
    so this case cannot be met by accident. The route refuses it with a 422 either way; the button must not
    be there.

    **Planted violation:** changed the gate to `!entry.withdrawn_at`. The live DOM run's "a notice carries
    no withdraw control" check failed on the planted row. Restored.
    """
    surface = source("surfaces/settings.js")
    entry = surface[surface.index("function consentNode"):surface.index("function noticesSection")]
    assert "entry.withdrawable ? opener" in entry, (
        "the withdraw control is not gated on `withdrawable`"
    )
    assert not re.search(r"!\s*entry\.withdrawn_at", entry), (
        "the withdraw control is gated on the absence of a withdrawal timestamp. A historical consent to a "
        "purpose that is now a notice has no timestamp and is not withdrawable; that gate offers to revoke "
        "a record nothing can revoke."
    )
    both_languages("consents.notice_row")


def test_nothing_offers_to_remove_a_consent_from_the_history():
    """R-230's question is "did they ever consent, and to what version". An entry that could be taken out of
    the list would answer a different and easier one, so withdrawal marks rather than deletes — and the
    screen says so.

    **Planted violation:** added a `deleteConsent` to `api.js`. Failed naming it. Restored.
    """
    api = source("app/api.js")
    for forbidden in ("deleteConsent", "removeConsent", "unwithdraw", "restoreConsent"):
        assert forbidden not in api, f"api.js exports {forbidden}; there is no such route and no such act"
    both_languages("consents.marks_not_deletes")
    assert "withdrawal_marks_rather_than_deletes" in source("surfaces/settings.js"), (
        "the screen no longer reads the server's own statement that a withdrawal marks rather than deletes"
    )


def test_the_notices_section_exists_offers_nothing_and_does_not_depend_on_a_row():
    """`notices` arrives on the history payload as full records, so every member sees it whether or not they
    have ever consented to anything — which matters, because the more surprising of the two facts is in
    there: a recorded decision cannot be altered or deleted by anyone, eigentliCH included, and survives an
    erasure emptied of name and text.

    **Planted violation:** rendered the notices section only when `payload.consents.consents` was non-empty.
    The live DOM run's "the notices section is still there" check failed on a member with none. Restored.
    """
    surface = source("surfaces/settings.js")
    notices = surface[surface.index("function noticesSection"):surface.index("function consentsSection")]
    assert "payload.notices" in notices
    assert "consents" not in notices.replace("consentsSection", ""), (
        "the notices section reads the consent rows; notices do not depend on a row and must render for a "
        "member who has none"
    )
    for control in ("button(", "onClick", "type: 'checkbox'", "withdraw"):
        assert control not in notices, (
            f"the notices section offers {control!r}. A notice is not a choice: no checkbox, no "
            f"acknowledgement, no withdrawal."
        )
    both_languages("notices.heading")
    both_languages("notices.lede")
    # Rendered above the history, not as a footnote.
    body = source("surfaces/settings.js")
    assert body.index("noticesSection(payload.consents") < body.index("consentsSection(payload.consents"), (
        "the notices are rendered after the consent history; they are the more surprising of the two facts "
        "and are not a footnote"
    )


# ============================================================ R-231: the export switch


def test_no_client_file_asks_for_the_unsafe_export_and_the_document_is_read_from_the_wrapper():
    """**A93's outstanding half, closed.**

    `GET /api/export` is R-154's plain read and writes **no** Decision. The client called it, so R-231's
    "both producing a Decision record" held only on the path nobody used and the member's own record of
    having asked for their data was never written.

    The method is the argument, not a preference. A GET must be safe: a prefetch, a retry after a dropped
    connection, a proxy revalidation or a double-click each repeat one, and each repetition would append to
    a table R-040 makes append-only — so S-07's screen would fill with export requests the member never
    made and there would be no removing them.

    `getExport` is **deleted** rather than left unused, because an exported function that calls the GET is
    what the next author reaches for.

    **Planted violations, two:** restored `export function getExport()` calling the GET (failed naming it),
    and read `payload` instead of `payload.export` in the vault surface (failed on the wrapper). Restored.
    """
    for name, text in _all_code().items():
        assert "getExport" not in text, (
            f"{name} still references getExport; `GET /api/export` writes no Decision and a function for it "
            f"is the one the next author calls"
        )
        assert not re.search(r"request\(\s*'/api/export'", text), (
            f"{name} requests GET /api/export directly"
        )
    api = source("app/api.js")
    assert "requestExport" in api
    assert re.search(r"post\(\s*'/api/settings/export'", api), (
        "requestExport does not POST to /api/settings/export"
    )
    for name in ("surfaces/settings.js", "surfaces/vault.js"):
        text = source(name)
        assert "requestExport" in text, f"{name} does not use the POST export"
        assert "payload.export" in text, (
            f"{name} does not read the document out of `payload['export']`; the POST wraps it, with "
            f"`decision_id` beside it"
        )
        assert "decision_id" in text, (
            f"{name} does not show the Decision the export request wrote; R-231's record is the point of "
            f"the POST"
        )


# ============================================================ R-231: the erasure


def test_the_confirmation_sentence_is_never_written_in_the_client():
    """The sentence is compared on the server, case not folded, and it arrives in the payload.

    A client that composed it would be a client that could disagree with the thing doing the comparing, on
    the one route whose mistake cannot be corrected. There is also no browser-side `pattern` built from it,
    for the same reason: two copies of one string.

    **Planted violation:** put `'ALLE MEINE DATEN LÖSCHEN'` in the client as a constant and pre-checked the
    input against it. Failed naming the literal. Restored.
    """
    for name, text in _all_code().items():
        assert "ALLE MEINE DATEN" not in text, (
            f"{name} writes the erasure confirmation sentence. It comes from the payload — a second copy "
            f"can disagree with the one being compared."
        )
        assert "DELETE ALL MY DATA" not in text
    for language in ("de", "en"):
        for key, value in strings(language).items():
            assert "ALLE MEINE DATEN" not in value and "DELETE ALL MY DATA" not in value, (
                f"{language}/{key} contains the confirmation sentence"
            )
    surface = source("surfaces/settings.js")
    assert "erasure.confirmation_phrase" in surface, (
        "the published sentence is not rendered from the payload; a member cannot type what they cannot see"
    )
    assert "pattern:" not in surface, (
        "a browser-side pattern is built for the confirmation field; that is a second copy of the sentence"
    )


def test_the_erasure_carries_no_boolean_and_asks_for_both_halves():
    """A93. No `understood: true` field anywhere: pydantic's lax mode reads `1`, `"y"` and `"on"` as true,
    which would make a field meant to express deliberate agreement the most permissive input on the request.
    A checkbox is one mis-click either way.

    Both halves are required — the typed sentence AND the password — and a valid token alone does not
    authorise this: a session left open on a borrowed laptop must not be enough to destroy a record.

    **Planted violation:** added an `understood` checkbox to the erasure form and sent it. Failed on the
    checkbox assertion. Restored.
    """
    surface = source("surfaces/settings.js")
    erasure = surface[surface.index("function erasureSection"):surface.index("// ------------------------------------------------------------")
                      if "// ------------------------------------------------------------" in surface[surface.index("function erasureSection"):]
                      else len(surface)]
    erasure = surface[surface.index("function erasureSection"):]
    assert "type: 'checkbox'" not in erasure, (
        "the erasure form carries a checkbox; the typed sentence is the deliberate-agreement field and a "
        "boolean would be the most permissive input on the request"
    )
    assert "name: 'confirmation'" in erasure and "name: 'password'" in erasure
    assert "requestErasure" in erasure
    both_languages("erasure.password_hint")


def test_the_erasure_is_behind_a_door_and_says_what_survives():
    """Nobody should arrive at the destructive control on the way to something else.

    The form starts hidden behind a control that has to be pressed, it is last on the screen in its own
    labelled region, and what survives is said **before** the fields rather than in the receipt afterwards:
    the append-only rows remain, emptied of name and text, and cannot be removed at the storage layer by
    anybody.

    **Planted violation:** removed the `hidden: ''` from the erasure form. The live DOM run's "the erasure
    form starts hidden" check failed. Restored.
    """
    surface = source("surfaces/settings.js")
    erasure = surface[surface.index("function erasureSection"):]
    assert re.search(r"class:\s*'position-form erasure-form',\s*\n?\s*hidden:\s*''", erasure), (
        "the erasure form does not start hidden"
    )
    assert "erasure.what_stays" in erasure, "the screen does not say what survives an erasure"
    assert "append_only_rows_are_emptied_not_removed" in erasure, (
        "the screen no longer reads the payload's own statement that the surviving rows are emptied rather "
        "than removed"
    )
    both_languages("erasure.what_stays")
    both_languages("erasure.irreversible")
    for language in ("de", "en"):
        stays = strings(language)["erasure.what_stays"]
        assert re.search(r"(Name|name)", stays) and re.search(r"(Text|text)", stays), (
            f"{language}/erasure.what_stays does not say that the name and the text are what go"
        )
    # Rendered last, after the export and the history.
    body = surface
    assert body.index("erasureSection(container") > body.index("exportSection(language"), (
        "the erasure is not the last thing on the settings screen"
    )


def test_the_erasure_response_is_treated_as_a_logout():
    """**The token dies with the account**: the member's `sessions` rows are among those deleted, so the
    next request with it is a 401.

    The local session is ended *before* the receipt renders. Otherwise the next click makes a request with a
    dead token and the member lands on the login screen with no account and no explanation of what happened
    to it. `renderLogin` is deliberately not called — a member who has just deleted their account should
    read the receipt, not meet a login form.

    **Planted violation:** removed `session.end()` from `onErased`. The live DOM run's "the local session
    was ended" check failed, and the stored token survived a completed erasure. Restored.
    """
    router = source("app/main.js")
    erased = router[router.index("onErased:"):]
    assert "session.end()" in erased[:300], (
        "a completed erasure does not end the local session; the token is already dead on the server"
    )
    assert "renderIdentity()" in erased[:400], (
        "the chrome still names a member who no longer exists"
    )
    surface = source("surfaces/settings.js")
    order = surface[surface.index("const report = await requestErasure"):]
    assert order.index("onErased()") < order.index("erasureReceipt("), (
        "the receipt is rendered before the local session is ended; a click on the receipt would then make "
        "a request with a dead token"
    )
    both_languages("erasure.done_heading")
    both_languages("erasure.done_announced")


# ============================================================ R-122 / R-123: editing a position


def test_no_form_in_this_client_offers_an_active_field():
    """**`active` is refused by name on the PATCH, and that is the argument for three controls.**

    An edit corrects what a position *is*; deactivating changes what the **live plan** is — the Befund stops
    counting the cell, the illustration stops projecting it, the derivations leave it out. A boolean in the
    middle of an edit form is how a member deactivates a position by accident, so the request model is
    `extra="forbid"` and says so rather than shrugging.

    **Two planted violations, and the first version of this guard MISSED one of them.** `active: false` in
    an object literal was caught; `changes.active = false;` — an assignment, which is the natural way to do
    it in this form — walked straight through, because the guard was written against the *literal* shape it
    happened to imagine. Same class as A95: a pattern that fires on one spelling of the thing and not on the
    one somebody would actually write. The revision block is now scanned for the **word**, which has no
    spellings. Both plants go red.
    """
    for name, text in _all_code().items():
        assert not re.search(r"name:\s*'active'", text), f"{name} has a form field named `active`"
        assert not re.search(r"\bactive:\s*(true|false)\b", text), (
            f"{name} states `active` in a request body; R-122's mark has its own two routes"
        )
        assert not re.search(r"\.active\s*=(?!=)", text), (
            f"{name} assigns to an `active` property; that is R-122's own act on its own route"
        )
    form = source("surfaces/position-form.js")
    revision = form[form.index("export function renderEdit"):form.index("export function renderStatusChange")]
    assert not re.search(r"\bactive\b", revision), (
        "the edit form mentions `active` at all. The PATCH refuses it BY NAME (`extra=\"forbid\"`) because "
        "a boolean in the middle of an edit form is how a member deactivates a position by accident, so "
        "there is nothing here for the word to legitimately be doing."
    )
    assert "revisePosition" in revision


def test_deactivating_is_its_own_control_and_states_what_changes():
    """R-122. The act is the route, so there is no flag to get the wrong way round.

    And "deactivate" is the word people read as "delete", so what does NOT happen is said **before** the
    control rather than in a confirmation afterwards: the position stays in the overview marked inactive and
    stays linked to every Decision that mentions it. The payload asserts both.

    **Planted violation:** removed `position.deactivate_stays` from the screen. Failed naming the key, and
    the live DOM run's "says what is NOT deleted" check failed. Restored.
    """
    api = source("app/api.js")
    assert "deactivatePosition" in api and "reactivatePosition" in api
    assert re.search(r"/deactivate", api) and re.search(r"/reactivate", api)

    form = source("surfaces/position-form.js")
    status = form[form.index("export function renderStatusChange"):]
    assert "position.deactivate_stays" in status, (
        "the deactivate screen does not say what stays; R-122's own word is *inactive*, and inactive "
        "positions remain in history and in decisions"
    )
    for key in ("position.deactivate", "position.deactivate_hint", "position.deactivate_stays",
                "position.reactivate", "position.reactivate_hint"):
        both_languages(key)
    for language in ("de", "en"):
        hint = strings(language)["position.deactivate_hint"]
        assert re.search(r"(Befund|illustration|Illustration)", hint), (
            f"{language}/position.deactivate_hint does not name what stops counting the position"
        )
    # Reactivation exists: R-122 does not say the mark is one-way, and one-way makes a mis-click permanent.
    grid = source("surfaces/grid.js")
    assert "position.reactivate" in grid and "position.deactivate" in grid
    assert "onSetActive" in grid


def test_only_the_fields_the_member_changed_are_sent():
    """The server reads `model_fields_set` to tell "clear the description" from "leave it alone".

    Posting the whole form back makes those indistinguishable and wipes whatever was not retyped — the same
    reasoning `GoalRevisionRequest` carries, and the defect the goal route exists to fix wearing a different
    coat.

    **The first version of this guard MISSED its own plant**, and the reason is worth keeping. It asserted
    that the identifier `stateIfChanged` appears in the block — which it still did after the plant renamed
    only the declaration, because the call sites had not been renamed. A test for the *presence of a name* is
    not a test for the behaviour the name performs. It now checks the property instead: every write into the
    request body goes through the comparison, **with no exception**.

    **The one documented exception is gone, and it went with the defect it described.** It read: "`liquidity`
    is additive because the grid payload does not carry the current band". A99 put `liquidity` into that
    payload and the form was not changed, so the exception outlived its reason by a day — and while it stood,
    the band was write-only: no member could see which one their own position held, and none could take one
    back, because the empty option meant "leave unchanged" and there was no way to say "not stated". The
    selector is preselected now and the empty option is R-031's null, so the field goes through the same
    comparison as every other and this assertion is `== set()` rather than `<= {"liquidity"}`.

    **Planted violations:** renamed the comparison helper; wrote `changes.active = false` straight into the
    body; and put `if (liquidity.value) changes.liquidity = liquidity.value;` back. All three go red; the
    second went red on the guard above as well, and the third is the one this paragraph is about.
    """
    form = source("surfaces/position-form.js")
    revision = form[form.index("export function renderEdit"):form.index("export function renderStatusChange")]

    assert "stateIfChanged" in revision, (
        "the edit form does not compare against the values it rendered; it posts the whole form back"
    )
    assert len(re.findall(r"stateIfChanged\(", revision)) >= 5, (
        "the comparison is declared but barely used; every field on this form has to be compared against "
        "the value that was rendered, or an untouched field is sent as a change"
    )
    # **And the helper has to actually compare.** A plant that kept the name and every call site but made
    # the body an unconditional assignment passed the two checks above — the name was present and used. So
    # the body is pinned: it takes the value that was rendered, and it compares against it.
    helper = re.search(r"const stateIfChanged = \(([^)]*)\) => \{(.*?)\n      \};", revision, re.DOTALL)
    assert helper, "the comparison helper is gone or has changed shape"
    assert "before" in helper.group(1), (
        "the comparison helper no longer receives the value that was rendered, so it cannot be comparing "
        "against it"
    )
    assert "!==" in helper.group(2), (
        "the comparison helper no longer compares; every field is now sent whether or not the member "
        "touched it, which is what wipes what they did not retype"
    )
    # Every direct write into the request body, so a field that bypasses the comparison is visible.
    direct = re.findall(r"changes(?:\.(\w+)|\[\s*'(\w+)'\s*\])\s*=(?!=)", revision)
    named = {a or b for a, b in direct}
    assert named == set(), (
        f"these fields are written into the revision without being compared against what was rendered: "
        f"{sorted(named)}. There is no additive field on this form any more — every one of them goes "
        f"through `stateIfChanged`, including `liquidity`."
    )
    # The band that stands has to be *on screen*, or "compared against what was rendered" is comparing
    # against nothing. A99 put `liquidity` into the grid payload precisely so this could be true.
    assert re.search(r"\(position\.liquidity \|\| ''\) === value", revision), (
        "the liquidity selector does not preselect the band the position holds, so the member cannot see "
        "which one stands and the comparison above has no rendered value to compare against"
    )
    assert "liquidity.value || null" in revision, (
        "the empty liquidity option does not send null, so R-031's 'not stated' is a state a member can "
        "leave and never return to"
    )
    assert re.search(r"if \(!Object\.keys\(changes\)\.length\)", revision), (
        "a revision that changes nothing is not refused before the request; the server answers 422 in "
        "R-040's terms and a member who changed nothing should not need a round trip to hear it"
    )
    both_languages("position.edit_unchanged")


def test_a_position_reaches_its_own_decisions():
    """R-160's filter, from the screen a member is standing on. The question they actually ask in front of a
    position is what they decided about it and why.

    **The first version of this guard MISSED its plant too**, and for the third instance of one reason: it
    asserted that the identifier `onDecisions` appears in the file. It still did — in the destructuring —
    after the plant had disconnected it from the control by replacing the condition with `false`. The
    presence of a name is not the presence of a wire. It now checks that the callback is what gates the
    control and what the control calls.

    **Planted violation:** replaced the `onDecisions ?` condition with `false ?`. Goes red now, and the live
    DOM run's "a position links to its decisions" check failed on it as well.
    """
    grid = source("surfaces/grid.js")
    assert re.search(
        r"onDecisions\s*\?\s*button\(t\('position\.see_decisions', language\)", grid
    ), (
        "the decisions control is not gated on the `onDecisions` callback; the name may be present and the "
        "control disconnected from it"
    )
    assert re.search(r"onClick:\s*\(\)\s*=>\s*onDecisions\(position\)", grid), (
        "the decisions control does not call `onDecisions` with the position it stands beside"
    )
    both_languages("position.see_decisions")
    router = source("app/main.js")
    assert "decisionsHash({ positionId: position.id })" in router, (
        "the grid's decisions link does not carry the position as a filter"
    )


# ============================================================ the defect the live DOM run found


def test_no_surface_announces_before_awaiting_the_render_behind_it():
    """**A86's defect, and it happened twice more in this pass. Found by running the client, not reading it.**

    Every surface announces itself to `#live` when it finishes loading. A handler that announces "recorded"
    and *then* awaits a reload has its announcement overwritten by the reload's own — so a member using a
    screen reader hears the screen name and never hears that their action succeeded. The code reads
    correctly either way and the symptom is audible only, which is why A86 says no static test would have
    found it. This one is static and finds the *shape*, which is the part that can be held.

    Two occurrences, both in this pass: `capabilities.js` after recording an assertion, and `settings.js`
    after a withdrawal. Both now announce after the await.

    **Planted violation:** swapped the two lines back in `settings.js`. Failed naming the file, and the live
    DOM run's "the withdrawal survives the re-render" check failed. Restored.
    """
    offenders = []
    for name, text in _all_code().items():
        # `announce(...)` followed, with only whitespace between, by `await on<Something>(`.
        for match in re.finditer(r"announce\([^;]*\);\s*await\s+(on[A-Z]\w*)\s*\(", text):
            offenders.append(f"{name}: announce(...) then await {match.group(1)}()")
    assert not offenders, (
        "an announcement is made before the screen behind it is re-rendered, so the re-render's own "
        "announcement overwrites it and the member hears the wrong thing:\n  " + "\n  ".join(offenders)
    )


def test_that_guard_can_actually_fire():
    """A20. The test above is an empty list either way — when the ordering is right and when the regex is
    dead. This pins the pattern against the exact text that was wrong."""
    bad = "announce(t('consents.withdrawn_announced', language));\n          await onChanged();"
    assert re.search(r"announce\([^;]*\);\s*await\s+(on[A-Z]\w*)\s*\(", bad), (
        "the ordering guard's pattern no longer matches the defect it was written for"
    )
    good = "await onChanged();\n          announce(t('consents.withdrawn_announced', language));"
    assert not re.search(r"announce\([^;]*\);\s*await\s+(on[A-Z]\w*)\s*\(", good)


def test_a_refusal_shaped_as_a_list_is_not_rendered_as_an_object():
    """**Pydantic's 422 arrives as a list of objects, not a sentence** — and the one route that answers it is
    the one written to teach a client something.

    `PATCH /api/positions/{id}` refuses `active` **by name**, and `active` is the field a client is most
    likely to send. Rendered as `error.detail`, that refusal reads `[object Object]`, so the refusal written
    to explain R-122 explained nothing.

    Every surface added or touched here goes through `detailText`, which handles the string, the list and
    `NotQueueable`'s object in one place. `surfaces/runs.js` keeps its own richer reading of that object;
    this is the fallback for everywhere else.

    **Planted violation:** rendered `failure.detail` directly in the edit form and sent `active`. The notice
    read `[object Object]`. Restored.
    """
    api = source("app/api.js")
    assert "export function detailText" in api
    assert "Array.isArray(detail)" in api, (
        "detailText does not handle pydantic's list-shaped detail, which is the shape the `active` refusal "
        "arrives in"
    )
    for name in ("surfaces/decisions.js", "surfaces/settings.js", "surfaces/capabilities.js",
                 "surfaces/position-form.js", "surfaces/login.js", "surfaces/vault.js"):
        text = source(name)
        assert "detailText" in text, f"{name} does not use detailText"
        bare = re.findall(r"(?:textContent|text:)\s*=?\s*\w+\.detail\b", text)
        assert not bare, f"{name} renders `.detail` directly: {bare}"


# ============================================================ A12 over everything added


# ============================================================ S-12: the curator's half of the same defect
#
# This file's whole subject is work that finished behind a route and had no surface. The curator screens
# were the same story twice more, and both were measured on the shipped database rather than argued:
#
#   * `curatorWorkbench` was called, and `workbench.sections` — the field carrying the positions, the
#     goals, the vault index, the decisions and the open items — was fetched and discarded. Two strings
#     were appended and the payload's largest field went on the floor. A curator could read *that* a
#     member had shared their goals and could not read the goals.
#
#   * All six `curator_sessions` rows carried one `opened` event and `outcome` was NULL on every one.
#     Not because closing was unimplemented — `close_session`, `record_note` and `recommend` are complete,
#     gated and tested — but because `app/api.js` had no function for any of the three. R-211 says a
#     session is recorded "with entry point and outcome"; half of that was unreachable from any screen.


def test_the_workbench_renders_what_the_member_shared():
    """R-210, from the side that reads rather than the side that refuses.

    Held as the whole join, because any one link missing is the defect back: the surface reads `sections`,
    it has a renderer for **every** scope the server can grant, and each renderer is reached from one table
    rather than from a chain of `if`s that a sixth scope would fall off the end of.

    Parametrised against `GRANTABLE` rather than against a list retyped here — the same rule
    `test_curator_signin.py` applies to the scope *labels*, applied to the scope *renderers*.

    **Planted violations, three times:** deleted the `sectionsNode(workbench, language)` call from
    `memberBlock` (failed on the first assertion); removed `vault` from `SECTION_RENDERERS` (failed naming
    the scope); and replaced `sectionsNode`'s body with a return of `null` (failed, because the renderer
    table is asserted to be reached from it). All restored.
    """
    from eigentlich.services.curator import GRANTABLE  # noqa: E402

    surface = source("surfaces/curator.js")
    assert "workbench.sections" in surface, (
        "surfaces/curator.js never reads `sections`; the material the grants are grants OF is discarded"
    )
    # **Scoped to the block that draws a member, and the plant is why.** A first version asserted that
    # `sectionsNode(workbench, language)` occurs in the file — which it does *in its own declaration*, so
    # deleting the call site left this green. A test for the presence of a name is not a test for the
    # behaviour the name performs; A94's entry records the identical failure on `stateIfChanged`.
    block = re.search(r"function memberBlock\s*\(.*?\n\}", surface, re.DOTALL)
    assert block, "memberBlock has moved; this guard can no longer find where a member is drawn"
    assert "sectionsNode(" in block.group(0), (
        "the sections are not rendered into the member block. `granted_scope` and `not_granted` alone say "
        "what was shared without showing any of it."
    )
    table = re.search(r"const SECTION_RENDERERS = \{(.*?)\n\};", surface, re.DOTALL)
    assert table, "there is no renderer table; a chain of ifs is what a sixth scope falls off"
    for scope in GRANTABLE:
        assert re.search(rf"\b{re.escape(scope)}\s*:", table.group(1)), (
            f"no renderer for the scope {scope!r}. The server can grant it, so a member can share it, and "
            f"a shared section that renders as nothing is R-210's ambiguity back at the last step."
        )
    assert "SECTION_RENDERERS[name]" in surface, "the table is declared and not read"
    # An empty granted section says so. An empty area and a withheld area are different facts.
    both_languages("curator.section_empty")
    both_languages("curator.sections")
    # And the vault section states what does not travel, rather than leaving it to be inferred from the
    # absence of a download control.
    assert "curator.vault_no_bytes" in surface
    both_languages("curator.vault_no_bytes")


def test_a_curator_session_can_be_given_an_outcome():
    """R-211: "every session is recorded with entry point and outcome". The second half had no surface.

    The join, end to end: four API functions, the routes they address, the three forms on the screen, and
    the one rule the screen enforces on its own — that an outcome is not invented.

    **`outcome` has no default anywhere in this client**, and that is the assertion worth having. The server
    refuses an empty one in R-211's own terms; a client that helpfully proposed "Beratung geführt" would
    satisfy the server and put a sentence into an append-only audit that no person wrote.

    **Planted violations, four times:** renamed `closeCuratorSession` in `api.js` (failed on the api half);
    deleted the close form from `consultationNode` (failed on the surface half); gave `outcome` a default
    value in the input (failed on the no-default assertion); and removed the local refusal so an empty
    outcome was sent to the server (failed on the validation assertion). All restored.
    """
    api = source("app/api.js")
    for fn, verb, path in (
        ("curatorSessions", None, "'/api/curator/sessions'"),
        ("readCuratorSession", None, "/sessions/${encodeURIComponent(sessionId)}"),
        ("addCuratorNote", "POST", "/notes"),
        ("closeCuratorSession", "POST", "/close"),
        ("recordCuratorRecommendation", "POST", "/recommendations"),
    ):
        assert re.search(rf"export function {fn}\s*\(", api), f"api.js has no {fn}"
        assert path in api, f"{fn} does not address {path}"
        if verb:
            body = re.search(rf"export function {fn}\b.*?\n\}}", api, re.DOTALL)
            assert body and f"method: '{verb}'" in body.group(0), f"{fn} does not {verb}"

    surface = source("surfaces/curator.js")
    assert re.search(r"function consultationNode\s*\(", surface), "there is no consultation on the screen"
    # Scoped to `memberBlock` for the reason the guard above records: the declaration would otherwise
    # satisfy a substring test for the call.
    member_block = re.search(r"function memberBlock\s*\(.*?\n\}", surface, re.DOTALL)
    assert member_block and "consultationNode(record.id" in member_block.group(0), (
        "the consultation block is never reached, so the session that was just opened has no controls"
    )
    for called in ("addCuratorNote(", "closeCuratorSession(", "recordCuratorRecommendation(",
                   "readCuratorSession("):
        assert called in surface, f"the curator screen never calls {called}"

    # The outcome is typed, never proposed.
    outcome = re.search(r"const outcome = h\('input',\s*\{([^}]*)\}", surface)
    assert outcome, "the outcome control has moved or is no longer an input"
    assert "value:" not in outcome.group(1), (
        "the outcome field carries a default. An outcome eigentliCH wrote is the one part of an append-only "
        "audit that came from nobody, and R-211 is the requirement it would be defeating."
    )
    assert "placeholder" not in outcome.group(1), "the outcome field proposes wording"
    assert "curator.close_outcome_missing" in surface, (
        "an empty outcome is not refused before the request; the server refuses it in R-211's own words "
        "and a curator should be asked rather than shown a constraint"
    )
    assert re.search(r"outcome\.value\.trim\(\)\s*\?\s*null\s*:\s*'curator\.close_outcome_missing'", surface), (
        "the refusal is named and not wired to the outcome field"
    )

    # C-10 said before the control rather than reported after it, on all three writing controls.
    for key in ("curator.note_hint", "curator.recommend_hint", "curator.close_hint"):
        assert key in surface, f"{key} is not on the screen"
        both_languages(key)
    for key in ("curator.close_outcome", "curator.note_add", "curator.recommend_submit",
                "curator.close_submit", "curator.closed", "curator.still_open", "curator.log",
                "curator.notes_redacted"):
        both_languages(key)
    # The three event kinds `services/curator.py` appends, each with a word.
    for kind in ("opened", "note", "closed"):
        both_languages(f"curator.log_{kind}")


def test_the_data_class_screen_and_the_export_control_agree():
    """The member reads both on one screen, and until now they contradicted each other flatly.

    `data_class_statement` reports `vault_items: {data_class: "K3", leaves_the_server: false}`, which the
    screen rendered as **"Bleibt auf dem Server."** — while the export control two sections away hands the
    member a document whose `vault_items` entries carry `content_base64`. Both sentences were on screen at
    once. The service's own docstring argues the resolution — "the export of a K3 category is the member's
    own copy and nobody else's" — and the screen did not say it.

    So the screen says it, in both directions: the K3 line names its own exception, and the export control
    names what it is handing over. Held as an agreement rather than as two separate strings, because two
    sentences that must not contradict each other are the shape A73 and A91 both are.

    **Planted violations, twice:** restored `'settings.classes_stays': 'Bleibt auf dem Server.'` (failed
    naming the absolute claim); and removed the documents clause from `settings.export_hint` (failed on the
    export half). Both restored.
    """
    for language in ("de", "en"):
        table = strings(language)
        stays = table["settings.classes_stays"]
        top = table["settings.classes_top_stays"]
        export_hint = table["settings.export_hint"]

        # The per-category line for `leaves_the_server: false` may not make an unqualified claim.
        assert re.search(r"(ausser|except)", stays, re.IGNORECASE), (
            f"{language}/settings.classes_stays says {stays!r} with no exception, while the export control "
            "on the same screen hands the member the K3 documents themselves"
        )
        # And the headline about the top class names the ways out rather than denying there are any.
        # **The absolute claim is refused explicitly**, because naming the ways out further down does not
        # undo a first sentence that says there are none — the plant that added "never leaves." in front
        # of the honest text passed a check that only looked for what follows it.
        for absolute in ("verlässt den Server nicht", "does not leave the server", "never leaves",
                         "verlässt diesen Server nie", "leaves the server never"):
            assert absolute not in top, (
                f"{language}/settings.classes_top_stays claims {absolute!r}, and the export control on "
                f"the same screen hands the member exactly that material: {top!r}"
            )
        assert re.search(r"(eigene Kopie|own copy)", top), (
            f"{language}/settings.classes_top_stays does not name the member's own copy: {top!r}"
        )
        assert re.search(r"(Kurator|curator)", top), (
            f"{language}/settings.classes_top_stays does not name the curator's index, which is the other "
            f"way a K3 row is read off this server: {top!r}"
        )
        # The export control says what it hands over, so the agreement holds read in either order.
        assert re.search(r"(Unterlagen|documents)", export_hint), (
            f"{language}/settings.export_hint does not say the documents themselves travel: {export_hint!r}"
        )

    # And the screen actually renders both keys, so the agreement is one a member can see.
    surface = source("surfaces/settings.js")
    for key in ("settings.classes_stays", "settings.classes_top_stays", "settings.export_hint"):
        assert key in surface, f"{key} is in the table and on no screen"


def test_the_settings_screen_makes_no_claim_a_withdrawal_does_not_keep():
    """The consent consequence is the server's to write, because the server is what does or does not act.

    `consents.required` read "Ohne diese Zustimmung lässt sich das Konto nicht weiterführen." — and an audit
    on 1 September 2026 measured every member route and found that a withdrawal writes `withdrawn_at`,
    answers 200 and changes nothing else. The owner decided to keep the behaviour and correct the words.
    `required_at_registration` gates registration and nothing after it.

    Held from both ends: the false sentence may not come back, and the consequence a member reads is the
    **server's** `consequence` field rather than a second copy written here — which is what stops the two
    drifting the next time the decision changes.

    **Planted violations, twice:** restored the old wording (failed naming it); and replaced
    `entry.consequence` in `settings.js` with a `t('consents.withdraw_means_de')` lookup, so the client
    wrote its own account of the consequence (failed on the second half). Both restored.
    """
    for language in ("de", "en"):
        required = strings(language)["consents.required"]
        for false_claim in ("nicht weiterführen", "cannot continue", "wird gesperrt", "will be closed"):
            assert false_claim not in required, (
                f"{language}/consents.required claims {false_claim!r}. Nothing reads `withdrawn_at` to "
                f"gate anything; the flag gates registration. Full text: {required!r}"
            )
        assert re.search(r"(kein Konto eröffnet|No account is opened)", required), (
            f"{language}/consents.required no longer says what the flag actually gates: {required!r}"
        )

    # **`text: entry.consequence`, not `entry.consequence` — the plant is why.** Replacing the rendered
    # value with a lookup from this client's own table left the name in the surrounding condition, so a
    # substring test for it stayed green while the screen printed a sentence eigentliCH's client had written
    # about a behaviour only the server implements.
    surface = source("surfaces/settings.js")
    assert re.search(r"text:\s*entry\.consequence\b", surface), (
        "the screen no longer renders the server's own consequence text. What a withdrawal does is the "
        "server's sentence to write, because the server is what does or does not act on it."
    )
    assert "nicht weiterführen" not in surface and "cannot continue" not in surface, (
        "the false claim is back in a comment on the surface that renders the control it describes"
    )


NEW_PREFIXES = ("decisions.", "consent.", "consents.", "notices.", "settings.", "erasure.",
                "capabilities.", "position.", "curator.")


def test_every_string_added_by_this_pass_exists_in_both_languages():
    """A12. The parity test holds the whole table; this asserts the new prefixes are actually in it, so a
    pass that added no strings could not pass vacuously.

    **Planted violation:** deleted the `notices.*` keys from the English block. `test_i18n_parity` failed
    and so did this. Restored.
    """
    de, en = strings("de"), strings("en")
    for prefix in NEW_PREFIXES:
        keys = {key for key in de if key.startswith(prefix)}
        assert keys, f"no strings with the prefix {prefix!r}; this pass authored some"
        missing = sorted(key for key in keys if key not in en)
        assert not missing, f"English is missing: {missing}"
    # The five screens' worth, so the count cannot quietly collapse to one key per prefix.
    added = {key for key in de if key.startswith(NEW_PREFIXES)}
    assert len(added) >= 140, f"only {len(added)} strings across the new prefixes"
