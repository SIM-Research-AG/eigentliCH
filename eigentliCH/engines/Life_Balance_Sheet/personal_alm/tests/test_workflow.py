"""Phase 2 and phase 3: what the submission can produce, and what to ask for next.

**The one test this file exists for, and it runs one way only.** `BLOCKING` is a superset of the refusals in
`case_from_submission`, and each entry says which it is through `refused_by_converter`. The direction worth a
test is the one whose failure a client pays for:

    ready and the converter refuses    a completed interview, then a refusal instead of a report
    blocked and the converter accepts  one extra question, asked because a zero income would be reported
                                       as findings rather than as a gap

So `test_a_ready_submission_is_actually_accepted` is unconditional, and the blocked direction splits: the two
entries the converter does raise on are checked with `pytest.raises`, and the two it does not are asserted to be
accepted, positively rather than skipped. Asserting the reverse direction, that every raise in the converter
appears in this table, would mean enumerating its raises here, which is a second copy of the rules it owns.

The rest is the distinction phase 3 is built on: a household without children is not MISSING the child section,
it does not have one, and every gap in this module becomes a question put to a person. Conflating the two
produces questions nobody should be asked, which is why `applies` and `needs` are tested separately.

The fixture is imported from `test_gameplan` rather than rebuilt. A second bland household would drift from the
first, and then a failure here would not tell you which of the two was wrong.
"""

from __future__ import annotations

import pytest

from personal_alm.app import workflow as W
from personal_alm.app.gameplan import _params_from, assemble
from personal_alm.app.onboarding import SubmissionError, case_from_submission
from personal_alm.tests.test_gameplan import submission

# --- one submission per blocking entry --------------------------------------------------------------------

#: The overrides that trip exactly one `BLOCKING` entry each, by code. Keyed by code rather than listed in
#: order so that adding an entry to `BLOCKING` and forgetting the case here fails loudly in
#: `test_every_blocking_entry_has_a_case_here`, instead of quietly reducing the coverage of the anti-drift
#: test to whatever happened to still be listed.
TRIPS: dict[str, dict] = {
    "no_target_spend": {"params": {"G": None}},
    "no_age": {"state": {"age": None}},
    "no_income": {"raw": {"income_gross": None}},
    "no_spending": {"raw": {"spend_now": None}},
}

BLOCKING_CODES = [b["code"] for b in W.BLOCKING]

# Partitioned on the declared flag rather than on a hand-written list, so the split follows the table. An entry
# whose flag is missing or not a bool falls into neither list and is reported by
# `test_the_asymmetry_is_declared_for_every_entry`, which names the cause instead of failing at collection.
REFUSED_CODES = [b["code"] for b in W.BLOCKING if b.get("refused_by_converter") is True]
ACCEPTED_CODES = [b["code"] for b in W.BLOCKING if b.get("refused_by_converter") is False]


# --- the anti-drift pair ----------------------------------------------------------------------------------

def test_a_ready_submission_is_actually_accepted():
    """A submission the interview declared finished must convert. Otherwise the client is told the calculation
    can run, waits for it, and gets a refusal instead of a report."""
    sub = submission()
    r = W.readiness(sub)
    assert r["ready"] is True, r["blocking"]
    assert r["blocking"] == []
    conv = case_from_submission(sub)          # the assertion is that this does not raise
    assert conv.case is not None


def _blocked_alone(code: str) -> dict:
    """The fixture for one code, with the shared half of both blocked-direction tests already asserted."""
    assert code in TRIPS, f"no case constructed for {code!r}"
    sub = submission(**TRIPS[code])
    r = W.readiness(sub)
    got = [b["code"] for b in r["blocking"]]
    assert got == [code], f"expected this fixture to trip {code!r} alone, tripped {got}"
    assert r["ready"] is False
    return sub


@pytest.mark.parametrize("code", REFUSED_CODES)
def test_a_blocked_submission_the_converter_refuses_is_actually_refused(code: str):
    """Where an entry claims the converter raises, it must raise.

    This is the half of the table that is a restatement of somebody else's rule, and a restatement goes stale
    the moment the rule moves. A raise that is removed, relaxed or renamed would leave an entry here stopping a
    perfectly runnable submission, and the cost of that is paid by a person sent away to fetch an answer nothing
    needed.
    """
    with pytest.raises(SubmissionError):
        case_from_submission(_blocked_alone(code))


@pytest.mark.parametrize("code", ACCEPTED_CODES)
def test_a_blocked_submission_the_converter_tolerates_is_still_blocked(code: str):
    """The asymmetry, asserted rather than skipped, because it is a decision and not an oversight.

    `case_from_submission` never reads the `raw` block, so it accepts a submission with no income and no current
    spending. It is right to in its own terms: a `Case` can be built. But the report built on it would carry an
    income of zero, and then every tax figure, the whole AHV entitlement and the entire saving rate come out
    zero or negative and are shown to the client as findings. That is a wrong answer rather than a degraded one,
    so the interview insists where the converter does not.

    Asserting the acceptance positively is what makes this a checked claim. A skip would record the same fact as
    an absence, and an absence cannot fail when the converter starts raising here and the flag stops being true.
    """
    sub = _blocked_alone(code)
    conv = case_from_submission(sub)          # must NOT raise: the flag says the converter tolerates this
    assert conv.case is not None
    # And the interview holds the line anyway, which is the whole reason the entry is in the table.
    assert code in {b["code"] for b in W.readiness(sub)["blocking"]}


def test_the_asymmetry_is_declared_for_every_entry():
    """Every entry says whether it mirrors a converter refusal, and at least one still does.

    The flag is what routes an entry into one of the two tests above, so an entry without it is tested by
    neither. A table where nothing was True would mean the anti-drift check had quietly stopped checking
    anything: it would still pass, over an empty parametrisation, and say nothing about the converter at all.
    """
    for b in W.BLOCKING:
        assert "refused_by_converter" in b, f"{b['code']} does not say whether the converter refuses it"
        assert isinstance(b["refused_by_converter"], bool), b["code"]
    assert REFUSED_CODES, "no entry mirrors a converter refusal, so nothing checks the converter any more"
    # Every entry reached exactly one of the two blocked-direction tests.
    assert sorted(REFUSED_CODES + ACCEPTED_CODES) == sorted(BLOCKING_CODES)


def test_every_blocking_entry_has_a_case_here():
    """A new entry in `BLOCKING` without a case above would silently narrow the anti-drift test."""
    assert sorted(TRIPS) == sorted(BLOCKING_CODES)


# --- readiness is cheap and total -------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    submission(),
    submission(raw={}),
    {},
    {"raw": {"income_gross": 100_000.0}},          # no state, no params at all
    {"state": {}, "params": {}},
], ids=["full", "no_raw", "empty", "raw_only", "empty_blocks"])
def test_readiness_never_raises(payload: dict):
    """Phase 2 runs before anything is validated, so a half-filled submission must produce a report of its own
    gaps rather than an exception. A traceback at this point is shown to a client who has answered three
    questions, and there is no gap it could describe.
    """
    r = W.readiness(payload)
    assert set(r) == {"ready", "blocking", "sections", "assumed", "computable_count", "section_count",
                      "not_applicable"}
    assert isinstance(r["ready"], bool)
    assert len(r["sections"]) == len(W.SECTIONS)


# --- the household condition against the answer condition -------------------------------------------------

def test_a_childless_household_is_never_asked_for_the_ages_of_its_children():
    """`applies` and `needs` are different things and phase 3 turns every `needs` gap into a question.

    Reporting `children_ages` as missing for a household that stated no children puts a question about their
    children in front of someone who has none, which is the kind of mismatch that makes a reader stop trusting
    the whole interview.
    """
    r = W.readiness(submission(raw={"children_count": 0}))
    assert "children" in r["not_applicable"]
    kids = next(s for s in r["sections"] if s["key"] == "children")
    assert kids["applies"] is False
    assert kids["missing"] == []
    assert all("children_ages" not in s["missing"] for s in r["sections"])


def test_a_household_with_children_and_no_ages_reports_the_gap():
    """The other half of the same rule: where the section does apply, the missing answer has to surface, or the
    child cost series is silently left out of a report that never says so."""
    r = W.readiness(submission(raw={"children_count": 2}))
    assert "children" not in r["not_applicable"]
    kids = next(s for s in r["sections"] if s["key"] == "children")
    assert kids["applies"] is True and kids["computable"] is False
    assert kids["missing"] == ["children_ages"]
    assert kids["without"].strip()


def test_child_ages_already_in_params_are_not_reported_as_missing():
    """The interview's word and the engine's field differ, and only the engine's field is filled in.

    A check reading `raw` alone would ask a household that already answered, which is the failure `_has`
    exists to prevent.
    """
    r = W.readiness(submission(raw={"children_count": 2},
                               params={"child_ages": [8.0, 12.0], "child_reference_age": 45}))
    kids = next(s for s in r["sections"] if s["key"] == "children")
    assert kids["computable"] is True and kids["missing"] == []


def test_an_answer_that_lands_in_params_counts_as_answered():
    """`spend_later` reaches the engine as `params.G` and `birth_year` as `state.age`.

    A household that answered both would be asked for both again if the check only ever looked at `raw`, and
    being asked twice for a figure already given reads as the system having lost it.
    """
    r = W.readiness(submission(raw={"spend_later": None, "birth_year": None}))
    assert r["ready"] is True, r["blocking"]
    gap = next(s for s in r["sections"] if s["key"] == "gap")
    assert gap["missing"] == [] and gap["computable"] is True


def test_the_counts_are_taken_over_applicable_sections_only():
    """A childless household told "7 of 9 sections" goes looking for two missing things, one of which was never
    theirs. The denominator has to be what applies to them."""
    r = W.readiness(submission())
    applying = [s for s in r["sections"] if s["applies"]]
    assert r["section_count"] == len(applying)
    assert r["section_count"] < len(W.SECTIONS), "expected the bland fixture to skip at least one section"
    assert r["computable_count"] == sum(1 for s in applying if s["computable"])
    assert r["computable_count"] <= r["section_count"]
    assert sorted(r["not_applicable"]) == sorted(s["key"] for s in r["sections"] if not s["applies"])


@pytest.mark.parametrize("payload", [
    submission(),
    submission(raw={"children_count": 3, "goal_kinds": ["Früher aufhören zu arbeiten"]}),
    submission(raw={}),
    {},
], ids=["full", "children_and_exit", "no_raw", "empty"])
def test_computable_never_exceeds_applicable(payload: dict):
    """The pair is printed as a fraction, and a fraction above one is read as a bug in the report rather than
    in the count."""
    r = W.readiness(payload)
    assert 0 <= r["computable_count"] <= r["section_count"] <= len(W.SECTIONS)


# --- the bridge, which is the one section with a real household condition ----------------------------------

@pytest.mark.parametrize("raw", [
    {"goal_kinds": ["Früher aufhören zu arbeiten"]},
    {"goal_kinds": ["Finanzielle Unabhängigkeit"]},
    {"goals": "Ab 55 nicht mehr arbeiten"},
    {"goals": "Frühpension mit 58, wenn es reicht"},
    {"goals": "irgendwann AUFHÖREN"},
], ids=["kind_early_exit", "kind_independence", "text_stop", "text_early_pension", "text_upper_case"])
def test_the_bridge_applies_where_an_early_exit_is_wanted(raw: dict):
    """The stop age is only worth asking for where somebody wants to stop.

    `goal_kinds` has said so directly since 21 August 2026, and the free text is read as well because the older
    submissions carry no `goal_kinds` at all. Dropping the free-text reading would quietly stop pricing the
    bridge for every household collected before that date, and the most expensive phase of an early-retirement
    plan would go missing without the report saying so.
    """
    r = W.readiness(submission(raw=raw))
    bridge = next(s for s in r["sections"] if s["key"] == "bridge")
    assert bridge["applies"] is True
    assert bridge["missing"] == ["stop_work_age"]
    assert "bridge" not in r["not_applicable"]


@pytest.mark.parametrize("raw", [
    {},
    {"goal_kinds": []},
    {"goal_kinds": ["Eigenheim kaufen"], "goals": "Ein Haus am See"},
    {"goals": "Die Ausbildung der Kinder sichern"},
], ids=["silent", "no_kinds", "other_kind", "other_text"])
def test_the_bridge_does_not_apply_otherwise(raw: dict):
    """Nobody who never mentioned stopping early should be asked for their exit age. It is a question that
    proposes a plan the household did not state, and phase 3 asks it out loud."""
    r = W.readiness(submission(raw=raw))
    bridge = next(s for s in r["sections"] if s["key"] == "bridge")
    assert bridge["applies"] is False
    assert bridge["missing"] == []
    assert "bridge" in r["not_applicable"]


def test_a_stated_stop_age_closes_the_bridge_gap():
    """It arrives as `params.stop_work_age`, so a household that gave it must not be asked again."""
    r = W.readiness(submission(params={"stop_work_age": 55},
                               raw={"goal_kinds": ["Früher aufhören zu arbeiten"]}))
    bridge = next(s for s in r["sections"] if s["key"] == "bridge")
    assert bridge["applies"] is True and bridge["computable"] is True and bridge["missing"] == []


# --- what is assumed rather than missing -------------------------------------------------------------------

def test_an_answered_field_is_not_reported_as_assumed():
    """An assumption named for a figure the household actually gave is a claim the report did not use their
    answer, and the mortgage rate is the field where that was true for real: the interview promised the answer
    would replace the model's rate and for a while nothing consumed it.
    """
    assumed = {a["field"] for a in W.readiness(submission())["assumed"]}
    assert "mortgage_rate" not in assumed
    assert "civil_status" not in assumed
    # And the other direction, on the same submission with the answer taken back out.
    gone = {a["field"] for a in W.readiness(submission(raw={"mortgage_rate": None}))["assumed"]}
    assert "mortgage_rate" in gone


def test_every_assumption_states_its_consequence():
    """An assumption without a consequence is a footnote. The point of the list is that the reader can see what
    the substitution cost them."""
    for a in W.readiness({})["assumed"]:
        assert set(a) == {"field", "consequence"}
        assert a["field"].strip() and a["consequence"].strip()


# --- phase 3, and the order that is the whole point --------------------------------------------------------

@pytest.mark.parametrize("code", BLOCKING_CODES)
def test_no_sensitivity_probe_runs_while_something_blocks(code: str):
    """A blocking gap has no franc figure, because without it there is no answer for a probe to move.

    Ranking it beside the measured asks would put a made-up number next to real ones and sort them together, so
    round one has to come back with the blockers and an empty ranking. A single probe leaking out here is a
    franc figure derived from a report that cannot be produced.
    """
    sub = submission(**TRIPS[code])
    out = W.follow_ups(sub, _params_from(sub), assemble)
    assert out["round"] == 1
    assert out["blocking"], "a blocked submission must come back with its blockers named"
    assert [b["code"] for b in out["blocking"]] == [code]
    assert out["ranked"] == []
    assert "summary" not in out, "a summary of nothing measured is a summary of nothing"
    assert out["readiness"]["ready"] is False


def test_round_two_ranks_the_remaining_gaps_by_measured_effect():
    """Once nothing blocks, the asks are ordered by what they move, not by what the manual says usually matters.

    A round two that came back empty would leave the interview with nothing to say after the blockers are
    cleared, which is the state the fixed ranking in the manual was there to avoid.
    """
    sub = submission()
    out = W.follow_ups(sub, _params_from(sub), assemble)
    assert out["round"] == 2
    assert out["blocking"] == []
    assert out["ranked"], "expected the bland household to leave several gaps worth measuring"
    assert "summary" in out
    for ask in out["ranked"]:
        assert ask["code"] and ask["field"]
        assert ask["question"].strip() and ask["why"].strip()
    # Ranked means ranked: the impacts must not be in ascending order by accident of dict iteration.
    impacts = [float(a.get("impact") or 0.0) for a in out["ranked"]]
    assert impacts == sorted(impacts, reverse=True), impacts


def test_follow_ups_always_carries_the_readiness_it_decided_from():
    """The round number is derived from the readiness, so the readiness has to travel with it. A caller that
    has to recompute it can compute a different one."""
    for over in ({}, TRIPS["no_age"]):
        sub = submission(**over)
        out = W.follow_ups(sub, _params_from(sub), assemble)
        assert out["readiness"] == W.readiness(sub)
        assert out["round"] == (1 if out["readiness"]["blocking"] else 2)


# --- the tables themselves ---------------------------------------------------------------------------------

def test_every_blocking_entry_is_well_formed():
    """`why` is printed to the client as the reason they are being asked. An empty one is a demand with no
    justification attached, which is exactly what phase 3 was built to stop producing."""
    seen = set()
    for b in W.BLOCKING:
        assert set(b) == {"code", "refused_by_converter", "field", "why", "test"}, sorted(b)
        assert isinstance(b["code"], str) and b["code"].strip()
        assert isinstance(b["field"], str) and b["field"].strip()
        assert isinstance(b["why"], str) and b["why"].strip()
        assert callable(b["test"])
        assert b["code"] not in seen, f"duplicate blocking code {b['code']!r}"
        seen.add(b["code"])


def test_every_section_is_well_formed():
    """`needs` is iterated as field names and `without` is printed as the cost of the gap.

    A list where a tuple was meant still iterates, so the type is asserted rather than assumed: a bare string
    in `needs` would be walked character by character and report nine missing fields with one-letter names.
    """
    seen = set()
    for s in W.SECTIONS:
        assert set(s) <= {"key", "title", "needs", "applies", "without"}, sorted(s)
        assert {"key", "title", "needs", "without"} <= set(s), sorted(s)
        assert isinstance(s["key"], str) and s["key"].strip()
        assert isinstance(s["title"], str) and s["title"].strip()
        assert isinstance(s["without"], str) and s["without"].strip()
        assert isinstance(s["needs"], tuple), f"{s['key']}.needs is {type(s['needs']).__name__}"
        assert all(isinstance(f, str) and f.strip() for f in s["needs"]), s["key"]
        if "applies" in s:
            assert callable(s["applies"])
        assert s["key"] not in seen, f"duplicate section key {s['key']!r}"
        seen.add(s["key"])


def test_every_assumed_field_is_a_pair_of_non_empty_strings():
    """The table is unpacked as `(field, consequence)`, so a three-element entry would raise inside a function
    documented as never raising."""
    for entry in W.ASSUMED_WHEN_ABSENT:
        assert isinstance(entry, tuple) and len(entry) == 2, entry
        field, consequence = entry
        assert isinstance(field, str) and field.strip()
        assert isinstance(consequence, str) and consequence.strip()
