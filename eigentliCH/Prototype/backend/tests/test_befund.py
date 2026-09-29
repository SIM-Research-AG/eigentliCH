"""The Befund — `services/befund.py` and its one route.

**Every guard here was verified by planting the violation, watching the test fail, and restoring.** That
is not a formality in this repository: A68 records four absence-shaped guarantees that stopped holding
while the suite stayed green, and every one of them had a test that could not fail. Each guard below
carries a `Planted:` note saying exactly what was broken and what the failure said.

**The word filters are imported rather than re-listed.** `_whole_words` and the gamification vocabulary
live in `test_content.py`; `GAMIFICATION_IDENTIFIERS` and `_code_only` are `test_constraints.py`'s and
`test_learning.py`'s. Re-typing any of them here would let this file and the rest of the suite come to
forbid different words.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eigentlich import llm  # noqa: E402
from eigentlich.content import LANGUAGES  # noqa: E402
from eigentlich.models import CAPITAL_TYPES, DataClass, Goal, Position, ROLES, VaultItem  # noqa: E402
from eigentlich.models.base import utcnow  # noqa: E402
from eigentlich.services import mutate_plan, record_correction  # noqa: E402
from eigentlich.services import befund as befund_module  # noqa: E402  (the module, not the export)
from eigentlich.services.befund import (  # noqa: E402
    BefundWouldAdvise,
    _introduced_content_words,
    ENGINES_WITHHELD_FROM_A_MEMBER,
    FORBIDDEN_MOODS,
    Fact,
    GAP_SUBJECTS,
    PHRASE,
    PROVENANCE,
    SECTIONS,
    SECTION_TITLE,
    UnknownLanguage,
    render_befund,
    reportable_gaps,
    sentences,
)
from eigentlich.services.vault import action_item_for_expiry  # noqa: E402
from eigentlich.engines import load_manifest  # noqa: E402
from eigentlich.services import engine_inputs  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_constraints import GAMIFICATION_IDENTIFIERS  # noqa: E402
from test_content import GAMIFICATION_WORDS, _whole_words, c07_identifier_offences  # noqa: E402
from test_learning import TALLY_WORDS, _code_only  # noqa: E402

SERVICE = BACKEND / "eigentlich" / "services" / "befund.py"
ROUTE = BACKEND / "eigentlich" / "api" / "befund.py"

TODAY = dt.date(2026, 8, 31)


# ============================================================ fixtures


@pytest.fixture()
def plain(session, member):
    """A member who has recorded nothing. The Befund's hardest case, not its easiest.

    R-110's principle is that an empty cell states what would go there, and a report over an empty plan is
    where that principle either holds everywhere or nowhere.
    """
    return member


@pytest.fixture()
def marc(session, member):
    """A member with a real plan: four positions across both kinds of capital, one of them inactive; two
    goals, one funded and dated, one courage money with neither; a correction in the decision history;
    three vault items, two with expiry dates and one of those already past; one prepared decision.

    Modelled on the persona framework's Marc, 35, family and a mortgage. Seeded through `mutate_plan` so
    every position and goal has the Decision C-09 requires behind it — which is also what gives the
    `decisions` section something true to report.
    """
    positions: dict[str, Position] = {}

    def add(key: str, question: str, choice: str, reasoning: str | None = None, **fields):
        with mutate_plan(
            session, member_id=member.id, question=question, choice=choice, reasoning=reasoning
        ) as decision:
            position = Position(member_id=member.id, tags=fields.pop("tags", {}), **fields)
            session.add(position)
            decision.linked_positions.append(position)
        session.commit()
        positions[key] = position
        return decision

    add(
        "job",
        "Die Anstellung als Humankapital in der Rolle Einkommen erfassen?",
        "Ja, 118'000 CHF pro Jahr, Vollzeit",
        "Der Lohn ist heute die einzige Quelle, aus der alles andere gedeckt wird.",
        role="income",
        capital_type="human",
        label="Anstellung als Projektleiter",
        magnitude=118000.0,
        magnitude_unit="chf_per_year",
        time_basis="Vollzeit, 42 Stunden",
        liquidity="within_months",
        started_on=dt.date(2019, 4, 1),
        tags={"client_type": "Arbeitgeber", "sector": "Bau"},
    )
    savings_decision = add(
        "savings",
        "Das Sparkonto als Stabilisierung erfassen?",
        "Ja, als Anteil am Gesamten",
        role="stabilisation",
        capital_type="financial",
        label="Sparkonto bei der Kantonalbank",
        magnitude=0.30,
        magnitude_unit="share_of_total",
        liquidity="immediate",
        started_on=dt.date(2016, 1, 1),
    )
    add(
        "cas",
        "Die Weiterbildung als Wachstum im Humankapital erfassen?",
        "Ja, ohne Betrag",
        role="growth",
        capital_type="human",
        label="CAS Bauleitung, laufend",
        time_basis="Abende und Samstage",
        started_on=dt.date(2025, 9, 1),
    )
    add(
        "sideline",
        "Die alte Nebentätigkeit stilllegen?",
        "Ja, stillgelegt, bleibt in der Geschichte",
        role="protection",
        capital_type="human",
        label="Nebenerwerb als Statiker, beendet",
        active=False,
        started_on=dt.date(2014, 1, 1),
    )

    with mutate_plan(
        session,
        member_id=member.id,
        question="Ein Ziel für die Amortisation der Hypothek erfassen?",
        choice="Ja, 80'000 CHF bis 2034",
    ) as decision:
        mortgage = Goal(
            member_id=member.id,
            name="Zweite Hypothek amortisieren",
            target_amount=80000.0,
            target_date=dt.date(2034, 6, 30),
            safety="hoch",
            liquidity_need="mittel",
            horizon="lang",
        )
        mortgage.funded_by.append(positions["savings"])
        session.add(mortgage)
        decision.linked_goals.append(mortgage)
    session.commit()

    with mutate_plan(
        session,
        member_id=member.id,
        question="Mutgeld als eigenes Ziel erfassen?",
        choice="Ja, ohne Betrag und ohne Datum",
    ) as decision:
        courage = Goal(member_id=member.id, name="Mutgeld", template="courage_money")
        session.add(courage)
        decision.linked_goals.append(courage)
    session.commit()

    # R-040: a correction is a new record referencing the prior one, and the report says so.
    record_correction(
        session,
        prior=savings_decision,
        choice="Korrektur: als Anteil am Gesamten, nicht als Betrag",
    )
    session.commit()

    policy = VaultItem(
        member_id=member.id,
        kind="policy",
        title="Hausratversicherung, Police 88-42-119",
        source="upload",
        stored_at=utcnow(),
        expiry_date=dt.date(2026, 12, 31),
        extracted_fields={"praemie": {"value": "412", "confidence": "mittel", "provenance": "extraction"}},
    )
    session.add(policy)
    session.add(
        VaultItem(
            member_id=member.id,
            kind="policy",
            title="Motorfahrzeugversicherung 2025",
            source="upload",
            stored_at=utcnow(),
            expiry_date=dt.date(2026, 3, 31),
        )
    )
    session.add(
        VaultItem(
            member_id=member.id,
            kind="note",
            title="Was wir mit den Kindern abgesprochen haben",
            source="manual",
            stored_at=utcnow(),
            notes="Die Grosseltern zahlen die Musikschule bis zur Oberstufe.",
        )
    )
    session.commit()

    session.add(action_item_for_expiry(policy))
    session.commit()
    return member


def _report(session, member, language="de", **kwargs):
    return render_befund(session, member_id=member.id, language=language, today=TODAY, **kwargs)


def _facts(report, section=None):
    return [
        fact
        for block in report["sections"]
        if section is None or block["key"] == section
        for fact in block["facts"]
    ]


def _keys(report, section):
    return [fact["key"] for fact in _facts(report, section)]


# ============================================================ it renders, and it says something


def test_a_member_who_has_recorded_nothing_still_gets_a_report(session, plain):
    """R-110 as prose. An empty plan is where "state what would go there" either holds or does not.

    Every section is present and every one of them says something. A report that renders as six empty
    lists for a new member is the "I don't get anything out of it" the Befund exists to answer.
    """
    report = _report(session, plain)
    assert [block["key"] for block in report["sections"]] == list(SECTIONS)
    for block in report["sections"]:
        assert block["facts"], f"section {block['key']!r} is empty for a member with no data"
        for fact in block["facts"]:
            assert len(fact["sentence"].split()) >= 5, (
                f"{fact['key']} is a label, not a sentence a member can read: {fact['sentence']!r}"
            )


def test_the_report_renders_with_a_single_position(session, member):
    """R-020 / R-110: the grid must be useful at n=1, and so must the report over it."""
    with mutate_plan(
        session, member_id=member.id, question="Die Anstellung erfassen?", choice="Ja"
    ) as decision:
        position = Position(
            member_id=member.id,
            role="income",
            capital_type="human",
            label="Anstellung",
            tags={},
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    report = _report(session, member)
    plan = _keys(report, "plan")
    assert plan.count("cell_filled") == 1
    assert "plan_is_empty" not in plan
    # The other seven cells still say what would go in them, which is the whole of R-110.
    assert plan.count("cell_empty") == len(ROLES) * len(CAPITAL_TYPES) - 1


def test_every_cell_of_the_grid_is_accounted_for(session, marc):
    """One fact per cell, always, so no combination of role and capital type can go unmentioned."""
    report = _report(session, marc)
    seen = {
        (fact["values"]["role"], fact["values"]["capital_type"])
        for fact in _facts(report, "plan")
        if "role" in fact["values"]
    }
    assert seen == {(role, capital) for role in ROLES for capital in CAPITAL_TYPES}


def test_an_empty_cell_states_what_would_go_there_rather_than_no_data(session, marc):
    """R-110 in the words the requirement uses. The sentence carries the role's own definition."""
    report = _report(session, marc)
    empty = [fact for fact in _facts(report, "plan") if fact["key"] == "cell_empty"]
    assert empty, "Marc has empty cells; the report found none"
    for fact in empty:
        assert fact["source"] == "content", "the definition is a content record, not a literal"
        assert len(fact["sentence"]) > len(fact["values"]["display"]) + 40, (
            f"{fact['sentence']!r} does not carry the definition"
        )


def test_an_inactive_only_cell_is_neither_filled_nor_empty(session, marc):
    """R-122. Calling it either would misrepresent what the member did."""
    plan = {fact["key"]: fact for fact in _facts(_report(session, marc), "plan")}
    assert "cell_inactive_only" in plan
    assert "Stillgelegtes" in plan["cell_inactive_only"]["sentence"]


def test_the_goals_section_names_what_funds_each_goal_and_what_does_not(session, marc):
    report = _report(session, marc)
    keys = _keys(report, "goals")
    assert "goal_funded" in keys, "the mortgage goal is funded by the savings position"
    assert "goal_unfunded" in keys, "courage money is unfunded, and that is a legitimate state (R-030)"
    assert "goal_is_courage_money" in keys, "R-132: courage money is a first-class template"


def test_the_decision_history_is_read_back_with_its_corrections(session, marc):
    """S-07 / R-040. The most underused material in the system, and the thing that survives an adviser."""
    facts = _facts(_report(session, marc), "decisions")
    assert any(fact["key"] == "decision_correction" for fact in facts)
    corrections = [fact for fact in facts if fact["key"] == "decision_correction"]
    assert all(fact["values"]["corrects_id"] for fact in corrections)
    # The member's own words are quoted, never composed into the sentence.
    assert all(fact["quoted"]["question"] for fact in facts)


def test_expiries_are_reported_and_the_past_ones_are_distinguished(session, marc):
    """R-152. An expiry that has already passed is a different fact from one that has not."""
    keys = _keys(_report(session, marc), "expiries")
    assert "vault_item_expiry_passed" in keys, "the 2026-03-31 policy is in the past on 2026-08-31"
    assert "vault_item_expires_on" in keys, "the 2026-12-31 policy is not"


def test_a_note_without_an_expiry_date_is_not_reported_as_expiring(session, marc):
    """The vault holds three items and two have dates. The third must not appear with a null date."""
    for fact in _facts(_report(session, marc), "expiries"):
        assert fact["values"]["expiry_date"], f"{fact['key']} reported an item with no expiry date"


def test_prepared_decisions_carry_their_options_and_consequences(session, marc):
    """C-06 read back: an item exists only if it carries the options and their consequences."""
    facts = _facts(_report(session, marc), "prepared_decisions")
    assert facts and facts[0]["key"] != "nothing_prepared"
    for fact in facts:
        options = fact["quoted"]["prepared_options"]
        assert len(options) >= 2
        assert all(option["consequence"] for option in options)


def test_the_not_known_section_reports_the_plan_gaps_engine_inputs_records(session, marc):
    """A39's "gaps left visible", and the most valuable thing in the report.

    Both plan-blocking kinds appear, because both are true of every real plan in prototype2: no position
    holds a wealth stock, and no assumption set has published a return.
    """
    facts = _facts(_report(session, marc), "not_known")
    kinds = {fact["values"]["kind"] for fact in facts}
    assert kinds == set(engine_inputs.PLAN_GAP_KINDS), (
        f"expected both plan-blocking kinds, got {kinds}"
    )
    reasons = {
        (gap["engine"], gap["input"]): gap["reason"]
        for gap in engine_inputs.gap_report(member_id=marc.id, positions=[], today=TODAY)
    }
    for fact in facts:
        assert fact["values"]["inputs"], "a gap with no engine input behind it is not a gap"
        for gap in fact["values"]["inputs"]:
            # The engine's own English reason stays out of the member-facing payload and stays
            # reachable through `engine_inputs` — which is where a curator tracing the gap looks.
            assert "reason" not in gap, (
                "the engine's implementation note reached a member-facing payload"
            )
            assert reasons[(gap["engine"], gap["input"])], (
                f"{gap['engine']}.{gap['input']} has no recorded reason anywhere"
            )


def test_the_report_is_deterministic(session, marc):
    """"Code owns the figures" is only a claim if two calls agree byte for byte."""
    first = json.dumps(_report(session, marc), sort_keys=True, ensure_ascii=False)
    second = json.dumps(_report(session, marc), sort_keys=True, ensure_ascii=False)
    assert first == second


def test_both_languages_produce_the_same_structure(session, marc):
    """A12. A report that is richer in German than in English is a half-translated product."""
    de, en = _report(session, marc, "de"), _report(session, marc, "en")
    assert [f["key"] for f in _facts(de)] == [f["key"] for f in _facts(en)]
    for german, english in zip(_facts(de), _facts(en)):
        assert german["sentence"] != english["sentence"], f"{german['key']} was not translated"
        assert german["values"] == english["values"] or german["key"].startswith("cell_"), (
            f"{german['key']} computed different values in two languages"
        )


def test_an_unwritten_language_is_refused_rather_than_falling_back(session, marc):
    """A12. `refusal_text` used to fall back to German silently (A76); this does not."""
    with pytest.raises(UnknownLanguage):
        render_befund(session, member_id=marc.id, language="rm", today=TODAY)


# ============================================================ C-01
#
# The sharpest edge. A report about someone's own plan is one sentence away from advice.
@pytest.mark.parametrize("language", LANGUAGES)
def test_no_phrase_in_the_copy_table_is_directive_or_evaluative(language):
    """The guard C-01's gate does not provide, and the reason it is needed is a finding.

    C-01's outbound rules conjoin directive force with a financial object from its instrument lexicon.
    The Befund is about `Position`, `Ziel`, `Deckung` and `Gefäss`, none of which are in that lexicon, so
    the gate has nothing to conjoin with. Probed against the live gate — all three of these **pass** it:

        Sie sollten eine Position als Deckung dieses Ziels hinterlegen.
        Für dieses Ziel wäre ein liquideres Gefäss besser.
        Von den beiden Möglichkeiten ist die erste für Sie die geeignetere.

    That is A76's recorded hole in a new place, and it means `test_every_sentence_the_befund_composes_
    passes_c01` above is a weaker guarantee than its name suggests. This test is the strong one, and it
    can be strong because `PHRASE` is a closed table this module owns rather than a model's output.

    **Planted:** each of the three sentences above, one at a time, into the German table. All three
    caught here; **none** of them caught by the C-01 test. Restored.
    """
    offences = []
    for key, template in PHRASE[language].items():
        for pattern in FORBIDDEN_MOODS:
            if re.search(pattern, template, re.IGNORECASE):
                offences.append((key, pattern))
    for key, title in SECTION_TITLE[language].items():
        for pattern in FORBIDDEN_MOODS:
            if re.search(pattern, title, re.IGNORECASE):
                offences.append((key, pattern))
    assert not offences, (
        f"C-01: the Befund states facts about a plan and never what to do about it. Found: {offences}"
    )


#: Plan-directed advice, in the vocabulary a report about a plan actually uses. Every one of these was
#: verified against the live C-01 gate rather than assumed — A76's instruction — and at the time of
#: writing every one **passed** it, because C-01's rules conjoin directive force with a financial object
#: from its instrument lexicon and `Position`, `Ziel`, `Deckung` and `Gefäss` are not in that lexicon.
#:
#: Two probes were written and dropped, and what they showed is the useful part:
#:
#:   "You should record a position that FUNDS this goal."  → refused, but only because `funds` collides
#:       with the instrument word `fund`. Change it to "for this goal" and it passes. The English side is
#:       covered by an accident of vocabulary, not by a rule.
#:   "We recommend recording an amount here."              → refused, correctly. Rule 1 catches a
#:       first-person recommendation and needs no financial object at all. So `we recommend` is held;
#:       it is `you should <plan verb>` that walks through.
PLAN_DIRECTED_ADVICE = (
    "Sie sollten eine Position als Deckung dieses Ziels hinterlegen.",
    "Für dieses Ziel wäre ein liquideres Gefäss besser.",
    "Von den beiden Möglichkeiten ist die erste für Sie die geeignetere.",
    "You should record a position for this goal.",
    "You should state an amount for this goal.",
    "It would be better for you to name a date.",
    "Your plan is on track.",
)


def test_the_mood_filter_catches_plan_directed_advice():
    """Guard on the guard, and it is the important one here: this filter does work C-01 does not.

    **It asserts only what it owns.** An earlier version also asserted that each probe *passes* C-01,
    which would turn an improvement to `boundary.py` into a failure in this file — and `boundary.py` is
    under active work (A83's statutory-duty exemption landed while this module was being written). A test
    that fails because the thing it guards got better is a trap. The C-01 relationship is checked
    separately, below, in the one form where a change there is genuinely worth someone reading.
    """
    for sentence in PLAN_DIRECTED_ADVICE:
        assert any(re.search(p, sentence, re.IGNORECASE) for p in FORBIDDEN_MOODS), (
            f"the mood filter does not catch {sentence!r}"
        )

    # And it does not fire on the copy's own legitimate constructions.
    for allowed in (
        "Keine erfasste Position ist als Deckung dieses Ziels hinterlegt.",
        "Was hier hingehört: Eine Anlage, die mit dem Umfeld steigt.",
        "Your plan does not record this.",
        "Bisher ist keine Entscheidung festgehalten.",
        "Dieses Ziel nennt 80'000 Franken und den 30.06.2034.",
    ):
        assert not any(re.search(p, allowed, re.IGNORECASE) for p in FORBIDDEN_MOODS), (
            f"the mood filter fires on legitimate copy: {allowed!r}"
        )
@pytest.mark.parametrize("language", LANGUAGES)
def test_no_verdict_phrase_reaches_the_payload(session, marc, language):
    """C-07 / R-006 as a phrase rather than a field, because a verdict does not need a number.

    "Ihr Plan ist auf Kurs" and "gut aufgestellt" carry no figure, appear in neither `TALLY_WORDS` nor
    `GAMIFICATION_WORDS`, and pass C-01 — verified. A summary judgement in words is the same thing as one
    in digits, and this is the only check that would catch it.

    **Planted:** appended `" Ihr Plan ist auf Kurs."` to the German `plan_is_empty` phrase. Failed naming
    it. Restored.
    """
    blob = json.dumps(_report(session, marc, language), ensure_ascii=False, default=str).lower()
    verdicts = (
        "auf kurs", "on track", "gut aufgestellt", "well positioned", "im soll", "on schedule",
        "im grünen bereich", "solide aufgestellt", "you are doing well", "sie sind gut",
    )
    found = [phrase for phrase in verdicts if phrase in blob]
    assert not found, f"C-07/R-006: the Befund reached a verdict about the member: {found}"
def test_a_member_who_names_a_position_advisorily_still_gets_a_report(session, member):
    """The reason quoted material is never merged into a composed sentence.

    A member may call a position whatever they like — it is their prose about their own plan, and C-01 has
    nothing to say about it. If it were interpolated into a sentence eigentliCH composes, that sentence
    would fail the gate and this member's whole report would be unrenderable because of what they typed.

    **Planted:** changed `cell_filled` to `"{display} ({capital}): {labels}"` and interpolated the label.
    This test failed with `BefundWouldAdvise`. Restored.
    """
    advisory = "Sie sollten Fonds X kaufen"
    # The probe is an advisory sentence a member typed into a position name. Nothing scans it any more
    # (A164); what this test still proves is that member prose travels in `Fact.quoted` and is never
    # merged into a composed sentence — a separation of authorship, not a regulatory check.

    with mutate_plan(
        session, member_id=member.id, question="Position erfassen?", choice="Ja"
    ) as decision:
        position = Position(
            member_id=member.id,
            role="growth",
            capital_type="financial",
            label=advisory,
            tags={},
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()

    report = _report(session, member)
    filled = [f for f in _facts(report, "plan") if f["key"] == "cell_filled"]
    assert filled, "the report did not render at all"
    assert advisory in filled[0]["quoted"]["position_labels"], "the member's own words were dropped"
    assert advisory not in filled[0]["sentence"], (
        "member-authored text was merged into a composed sentence; C-01 now depends on what a member types"
    )
def test_no_curator_handoff_is_ever_required_by_the_report_itself(session, marc):
    """The Befund is not a `/api/know/ask` response and must never need one.

    If a Befund ever legitimately required a curator, the correct change is to stop composing that
    sentence — not to attach a handoff and ship it.
    """
    report = _report(session, marc)
    assert "requires_curator" not in json.dumps(report)


# ============================================================ C-07 and R-113
#
# No score, no level, no rung, no points, no progress meter, no completion ratio. And R-113's specific
# form: no filled count, no total, no ratio in the payload.


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_payload_carries_a_tally_of_what_the_member_has_recorded(session, marc, language):
    """R-113 / R-006. "3 of 8 filled" is the completion meter this product exists without.

    **Planted:** added `"filled": 3, "total": 8` to the plan section's payload. Failed naming both.
    Then planted only `"cells_filled": 3`. Failed naming `filled`. Restored.
    """
    blob = json.dumps(_report(session, marc, language), ensure_ascii=False, default=str).lower()
    found = _whole_words(TALLY_WORDS + ("filled", "gefüllt", "quote", "erfüllt"), blob)
    assert not found, f"R-113: the Befund payload carries {found}"


#: R-113's own example, as a shape rather than a vocabulary: `3 of 8`, `74 von 100`, `60 %`, `12 Punkten`.
#:
#: **This exists because the vocabulary filters missed the most literal possible violation.** Planting
#: `Ihr Haushalt erreicht 74 von 100 Punkten.` into a phrase every report reaches was caught by NEITHER
#: `TALLY_WORDS` nor `GAMIFICATION_WORDS`: the tally list has no entry for it, and the gamification list's
#: `punkte` is whole-word matched, so the German dative plural **`Punkten` walks straight past `\bpunkte\b`**.
#: That is a hole in a filter five test modules share, and it is reported rather than patched here —
#: widening `GAMIFICATION_WORDS` changes what four other suites forbid, which is not this module's call.
#:
#: A shape is the right guard for this anyway. "3 of 8" is a completion meter whatever the noun is, and
#: a member's own figures never take that form: a magnitude is one number, a date is a date, and nothing
#: the Befund computes is `n out of m`.
SCORE_SHAPES = (
    r"\b\d+\s+(?:von|of|out\s+of|aus)\s+\d+\b",
    r"\b\d+\s*(?:%|prozent\w*|percent\w*)\b",
    r"\bpunkt\w*\b",
    r"\bpoints?\b",
    r"\bnote\s+\d\b",
    r"\b\d+\s*/\s*\d+\b",
)


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_score_shaped_statement_reaches_the_payload(session, marc, language):
    """R-113 as a shape. `3 of 8`, `74 von 100`, `60 %` — a meter whatever it is called.

    **Planted:** `Ihr Haushalt erreicht 74 von 100 Punkten.` into `cell_filled`, which every report
    reaches. Caught here. Not caught by the tally filter, and not by the gamification filter either —
    see `SCORE_SHAPES` for why, and for the inflection hole that finding exposed in a shared list.
    Also planted `Ihr Plan ist zu 60 Prozent vollständig.`; caught by this and by the tally filter.
    Restored.
    """
    report = _report(session, marc, language)
    offences = []
    for one in _facts(report):
        for pattern in SCORE_SHAPES:
            if re.search(pattern, one["sentence"], re.IGNORECASE):
                offences.append((one["key"], pattern, one["sentence"]))
    assert not offences, f"R-113: a score-shaped statement reached the Befund: {offences}"


def test_the_score_shape_filter_is_not_vacuous():
    """Including the case the shared vocabulary filters miss, so the reason this test exists is pinned."""
    def hits(text):
        return [p for p in SCORE_SHAPES if re.search(p, text, re.IGNORECASE)]

    assert hits("Ihr Haushalt erreicht 74 von 100 Punkten.")
    assert hits("3 of 8 cells are filled")
    assert hits("Ihr Plan ist zu 60 Prozent vollständig.")
    assert hits("a 12/20 rating")
    # The finding this filter was written for: the shared list does NOT catch the inflected form.
    assert _whole_words(("punkte",), "74 von 100 punkten") == [], (
        "GAMIFICATION_WORDS now catches the German dative plural; if that was fixed deliberately, say so "
        "here — but do not delete this filter, because the `n of m` shape needs no vocabulary at all"
    )
    # And it does not fire on the member's own figures, which is the whole point.
    for allowed in (
        "Dieses Ziel nennt 80'000 Franken und den 30.06.2034.",
        "Am 31.08.2026 haben Sie eine Entscheidung festgehalten.",
        "Dieses Dokument trägt den 31.12.2026 als Ablaufdatum.",
        "This goal names 80'000 francs and 30.06.2034.",
    ):
        assert not hits(allowed), f"the shape filter fires on a member's own figure: {allowed!r}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_gamification_vocabulary_in_the_befund_payload(session, marc, language):
    """C-07 as copy, in both languages — A12 makes this a two-language rule."""
    blob = json.dumps(_report(session, marc, language), ensure_ascii=False, default=str).lower()
    # "note" is deliberately NOT in this list. German `Note` is a school grade and would belong, but
    # `note` is also the VaultItem kind for member-authored material (R-153) and the key on the
    # `assumptions` block — a whole-word filter cannot tell them apart, and a filter that fires on the
    # thing it protects is worse than no filter (test_content.py records the same lesson).
    found = _whole_words(GAMIFICATION_WORDS + ("rank", "daily_goal", "grade", "bewertung", "zensur"), blob)
    assert not found, f"C-07: found gamification vocabulary in a Befund payload: {found}"


def test_no_gamification_identifiers_in_the_befund_source():
    """C-07's AST walk, extended from the model layer to this service and its route.

    A6 scoped `test_no_gamification_identifiers_in_model_layer` to `eigentlich/models/`, and a report is the
    surface where a `score` would actually be *useful* — which is exactly why the walk has to reach it.

    **Planted:** added `score = len(facts)` to `befund()`. Failed naming `befund.py:… score`. Restored.

    **The walk moved out of this file.** It was a near-copy of `test_constraints.py`'s and shared its two
    holes — no `ast.Constant`, and exact-set membership — so a payload key named by string literal and a
    name like `points_earned` were both invisible here. One walk now, in `test_content.py`.
    """
    offences: list[str] = []
    for path in (SERVICE, ROUTE):
        offences.extend(c07_identifier_offences(path))
    assert not offences, f"C-07 forbids gamification primitives in the member layer. Found: {offences}"


def test_the_befund_code_declares_no_tally_identifier():
    """The concept a phrase away from existing. Comments and docstrings are stripped so they can name it.

    **Planted:** added `ratio = 1` inside `befund()`. Failed naming `ratio`. Restored.
    """
    for path in (SERVICE, ROUTE):
        found = _whole_words(
            ("filled", "percent", "ratio", "completion", "progress", "grade", "tally"),
            _code_only(path),
        )
        assert not found, f"{path.name} declares {found}; R-113 forbids the concept, not only the field"


def test_the_estates_score_engine_is_never_surfaced_to_a_member(session, marc):
    """A6 scoped C-07 to the member layer deliberately. That is not a licence to render the Score.

    **Planted:** removed `"score_engine"` from `ENGINES_WITHHELD_FROM_A_MEMBER`. This test failed on the
    engine name appearing in the payload, and `test_no_gamification_vocabulary_in_the_befund_payload`
    failed on the word `score`. Restored.
    """
    assert "score_engine" in ENGINES_WITHHELD_FROM_A_MEMBER
    blob = json.dumps(_report(session, marc), ensure_ascii=False, default=str)
    for engine in ENGINES_WITHHELD_FROM_A_MEMBER:
        assert engine not in blob, f"{engine} reached a member-facing payload"

    # And the gap really exists — the withholding is a decision, not a description of an empty list.
    withheld = engine_inputs.plan_all(member_id=marc.id, positions=[], today=TODAY)
    for engine in ENGINES_WITHHELD_FROM_A_MEMBER:
        assert any(gap.blocks_the_plan for gap in withheld[engine].absent), (
            f"{engine} has no plan gaps, so withholding it proves nothing"
        )


def test_the_report_reaches_no_summary_judgement(session, marc):
    """No score, no grade, no percentage complete, no "on track". Checked as an absence of shape.

    A single number about the member anywhere at the top level of the payload would be one, whatever it
    were called, so the assertion is on the shape rather than on a vocabulary.
    """
    report = _report(session, marc)
    for key, value in report.items():
        assert not isinstance(value, (int, float)) or isinstance(value, bool), (
            f"the Befund envelope carries a bare number {key}={value!r}; a report that ends in a number "
            f"ends in a verdict"
        )
    assert set(report) == {
        "member_id",
        "language",
        "as_of",
        "delivered_on_request_only",
        "sections",
        "assumptions",
        # Item 6. Provenance is not currency, and the two are separate keys because neither implies the
        # other: `assumptions` says no figure came from an assumption, `currency` says whether the
        # figures that came from the member are still inside their published validity horizon.
        #
        # It carries no bare number and no verdict about the member. `could_not_be_determined` is a LIST
        # of the findings that could not be determined, not a count of them, for the same reason
        # `not_known` is a list — a tally of what is uncertifiable is a score of how stale you are.
        "currency",
        "prose",
    }, f"the envelope grew a key: {sorted(report)}"

    assert isinstance(report["currency"]["could_not_be_determined"], list)


# ============================================================ C-02


def test_no_fact_claims_an_assumption_without_the_set_that_produced_it(session, marc):
    """C-02's biconditional, over a real report."""
    for fact in _facts(_report(session, marc)):
        assert fact["source"] in PROVENANCE
        assert (fact["source"] == "assumption") == (fact["assumption_set_id"] is not None)


def test_the_c02_invariant_is_in_the_constructor_and_fires_in_both_directions():
    """**Planted:** dropped the check from `Fact.__post_init__`; both halves below stopped raising.

    Both directions, because an id attached to a figure that did not come from an assumption is a false
    claim of provenance and it is the one that survives review.
    """
    common = dict(section="plan", key="planted", source="assumption", data_class=int(DataClass.K2))
    with pytest.raises(ValueError, match="C-02"):
        Fact(sentence="Diese Zahl kommt aus einer Annahme.", **common)
    with pytest.raises(ValueError, match="C-02"):
        Fact(
            section="plan",
            key="planted",
            sentence="Diese Zahl kommt aus Ihren eigenen Angaben.",
            source="member_stated",
            data_class=int(DataClass.K2),
            assumption_set_id="not-null",
        )
    # And the legitimate pairing is accepted, so the guard is a gate rather than a wall.
    assert Fact(
        sentence="Diese Zahl kommt aus einer Annahme.", assumption_set_id="set-1", **common
    ).assumption_set_id == "set-1"


def test_the_envelope_states_that_nothing_was_derived_from_an_assumption(session, marc):
    """C-02 explicit rather than absent: a client should not infer from a missing key."""
    assumptions = _report(session, marc)["assumptions"]
    assert assumptions["any_figure_derived_from_an_assumption"] is False
    assert assumptions["assumption_set_id"] is None
    assert assumptions["note"]


def test_a_goal_illustration_never_leaks_into_the_befund(session, marc, monkeypatch):
    """`services/goals.py` gained an illustration while this module was being written.

    The Befund reads a fixed set of keys off that payload and must keep doing so: an illustration's
    figures are assumption-derived, and a report that picked them up would carry them with `source ==
    "member_stated"` and no `assumption_set_id` — a C-02 violation produced by a change in another file.

    **Planted:** added `**payload.get("illustration", {})` into a goal fact's `values`. This test failed
    on `7777777` appearing in the payload. Restored.
    """
    real = befund_module.list_goals

    def with_illustration(session_, **kwargs):
        result = real(session_, **kwargs)
        for goal in result["goals"]:
            goal["illustration"] = {
                "assumption_set_id": "planted-set",
                "final_value": 7777777,
                "annual_return": 777,
            }
            goal["illustration_unavailable_reason"] = None
        return result

    monkeypatch.setattr(befund_module, "list_goals", with_illustration)
    report = _report(session, marc)

    # **Structural, not a substring search.** `new_id()` is 32 random hex characters, so searching a
    # serialised payload for a digit run passes or fails on `uuid4` — the first version of this looked
    # for `7777777` in the blob, which is the same defect another test in this file had and which is
    # worse than no test, because it teaches the next reader to re-run until it goes green.
    illustration_keys = {"assumption_set_id", "final_value", "annual_return"}
    leaked = [
        (one["key"], key)
        for one in _facts(report)
        for key in one["values"]
        if key in illustration_keys
    ]
    assert not leaked, f"an illustration field from the goals payload reached a Befund fact: {leaked}"
    # `planted-set` is alphabetic, so this one cannot collide with a hex id or a timestamp.
    assert "planted-set" not in json.dumps(report, ensure_ascii=False, default=str), (
        "an assumption set id from the goals payload reached the Befund"
    )
    # And the envelope still says nothing was derived from an assumption, which would now be a lie if
    # anything had leaked.
    assert report["assumptions"]["any_figure_derived_from_an_assumption"] is False


def test_no_float_literal_in_the_befund_source():
    """C-02, structurally. `test_constraints.py` covers `services/*.py` already; this fails closer to home.

    **Planted:** changed `PROSE_LENGTH_ALLOWANCE = 2` to `2.0`. Failed naming the line. Restored.
    """
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"), filename=str(SERVICE))
    offences = [
        f"{SERVICE.name}:{node.lineno} {node.value}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert not offences, f"C-02: no literal rate in application code. Found: {offences}"


# ============================================================ C-04


def test_every_fact_declares_the_data_class_it_read(session, marc):
    for fact in _facts(_report(session, marc)):
        assert fact["data_class"] in {int(c) for c in DataClass}


def test_a_fact_quoting_a_vault_title_declares_k3(session, marc):
    """C-04. A report that quotes a vault document's title is quoting K3, and says so on the fact.

    **Planted:** changed `_expiry_facts` to `int(DataClass.K2)`. Failed naming the fact and the class it
    declared. Restored.
    """
    quoting = [fact for fact in _facts(_report(session, marc)) if "title" in fact["quoted"]]
    assert quoting, "Marc has vault items with titles; none were quoted"
    for fact in quoting:
        assert fact["data_class"] == int(DataClass.K3), (
            f"{fact['key']} quotes a vault title at K{fact['data_class']}; a VaultItem is K3 (C-04)"
        )


def test_each_section_declares_the_highest_class_of_its_facts(session, marc):
    for block in _report(session, marc)["sections"]:
        assert block["data_class"] == max(fact["data_class"] for fact in block["facts"])


def test_the_expiries_section_is_k3_and_the_plan_section_is_not(session, marc):
    """The two ends of the classification, so the previous test cannot pass on a payload that is all K3."""
    classes = {block["key"]: block["data_class"] for block in _report(session, marc)["sections"]}
    assert classes["expiries"] == int(DataClass.K3)
    assert classes["plan"] == int(DataClass.K2)


def test_the_befund_narrates_nothing_to_a_log():
    """C-04. The Befund is the module that assembles the most K3 material in the application, and the
    honest way for it to keep that out of the logs is to write none.

    **This test was rewritten because the first version could not fail.** It ran a report with `caplog`
    and asserted no vault title appeared in the records. Planting
    `logging.getLogger("eigentlich.befund").warning("read title=%s", item.title)` in `_expiry_facts` did
    not break it — C-04's own log filter redacts `title=` before the record reaches a handler, so the
    assertion passed while the module was doing precisely the thing it forbids. That is A71's shape
    exactly: a check that was green because something else was working.

    So the guard is now static and about this module. No `logging` import, no logger, no `.warning`,
    `.info`, `.debug`, `.error` or `.exception` call anywhere in the service or its route. C-04's filter
    stays as the backstop; it is not this module's excuse.

    **Planted after the rewrite:** the same `logging.getLogger(...).warning(...)` line. Failed naming the
    import and the call. Restored.
    """
    emitting = ("debug", "info", "warning", "error", "exception", "critical", "log")
    offences: list[str] = []
    for path in (SERVICE, ROUTE):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offences += [
                    f"{path.name}:{node.lineno} import {alias.name}"
                    for alias in node.names
                    if alias.name.split(".")[0] == "logging"
                ]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "logging":
                offences.append(f"{path.name}:{node.lineno} from {node.module} import ...")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in emitting and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in {"logging", "logger", "log", "_logger"}:
                        offences.append(f"{path.name}:{node.lineno} {node.func.value.id}.{node.func.attr}")
                elif node.func.attr == "getLogger":
                    offences.append(f"{path.name}:{node.lineno} getLogger")
    assert not offences, (
        "the Befund reads K3 and must narrate none of it. C-04's filter is a backstop, not a licence. "
        f"Found: {offences}"
    )


def test_a_top_class_field_name_never_reaches_a_log_line(session, marc, caplog):
    """C-04 as a backstop, and honest about being one.

    This cannot detect the Befund logging a K3 title — `log_filter` redacts it first, which is what the
    rewrite of the test above is about. It is kept because it does check something real: that producing a
    report emits nothing about this member under any logger, redacted or not.
    """
    import logging

    with caplog.at_level(logging.DEBUG):
        report = _report(session, marc)
    titles = [
        fact["quoted"]["title"] for fact in _facts(report, "expiries") if "title" in fact["quoted"]
    ]
    assert titles, "no titles were read, so this proves nothing"
    from_befund = [r for r in caplog.records if r.name.startswith("eigentlich.services.befund")]
    assert not from_befund, f"the Befund emitted {[r.getMessage() for r in from_befund]}"
    emitted = "\n".join(record.getMessage() for record in caplog.records)
    for title in titles:
        assert title not in emitted, f"a K3 vault title reached a log line: {title!r}"


# ============================================================ the model, and its absence


def test_the_whole_report_renders_with_the_model_unavailable(session, marc, monkeypatch):
    """The requirement in one sentence: a report that degrades to nothing when Ollama is down is not a
    report.

    `prose=True` with every model call raising. Every sentence must be the computed one, every section
    must be present, and the payload must be identical to the `prose=False` payload except for the
    `prose` block itself.

    **Planted:** made `_rephrase` propagate `LocalModelUnavailable` instead of returning the fact. This
    test failed with that exception rather than an assertion. Restored.
    """

    def refuse(*_args, **_kwargs):
        raise llm.LocalModelUnavailable("planted: the local model is not running")

    monkeypatch.setattr(befund_module.llm, "chat", refuse)

    with_model = _report(session, marc, prose=True)
    without = _report(session, marc, prose=False)

    assert [f["sentence"] for f in _facts(with_model)] == [f["sentence"] for f in _facts(without)]
    assert all(f["sentence_origin"] == "computed" for f in _facts(with_model))
    assert with_model["prose"]["requested"] is True
    assert with_model["prose"]["used"] is False
    assert {entry["reason"] for entry in with_model["prose"]["refused"]} == {"model_unavailable"}
    # Every fact was attempted, so the degradation is complete rather than partial.
    assert len(with_model["prose"]["refused"]) == len(_facts(with_model))

    stripped_a = {k: v for k, v in with_model.items() if k != "prose"}
    stripped_b = {k: v for k, v in without.items() if k != "prose"}
    assert stripped_a == stripped_b


def test_the_default_is_no_model_at_all(session, marc, monkeypatch):
    """It ships off. A report that reaches for a model by default is one that fails when the model does.

    **Planted:** changed `prose: bool = False` to `True` in `befund()`. Failed naming the call. Restored.
    """

    def explode(*_args, **_kwargs):
        raise AssertionError("the Befund called the local model without being asked to")

    monkeypatch.setattr(befund_module.llm, "chat", explode)
    report = render_befund(session, member_id=marc.id, today=TODAY)
    assert report["prose"] == {"requested": False, "used": False, "model": None, "refused": []}


def test_a_model_that_invents_a_figure_is_discarded(session, marc, monkeypatch):
    """"The model only writes sentences" is only true if the code checks that it wrote nothing else.

    **Planted:** removed the `_figures` comparison from `_rephrase`. Failed on `999` reaching the payload.
    Restored.
    """
    monkeypatch.setattr(
        befund_module.llm,
        "chat",
        lambda *a, **k: llm.Reply(text="Ihr Plan hält 424242 Franken fest.", model="planted"),
    )
    report = _report(session, marc, prose=True)
    # The sentences, not the whole blob: `new_id()` is 32 random hex characters, so a short digit run
    # turns up inside an id sooner or later and the blob check was flaky rather than wrong.
    assert not any("424242" in one for one in sentences(report)), "an invented figure survived"
    assert all(f["sentence_origin"] == "computed" for f in _facts(report))
    assert {e["reason"] for e in report["prose"]["refused"]} <= {"figures_changed", "too_long"}
def test_a_model_that_invents_subject_matter_is_discarded(session, marc, monkeypatch):
    """The guard the other four did not provide, and it was found against the real local model.

    apertus:8b was asked to rephrase `Zu diesem Ziel sind einzelne der fünf Parameter noch offen; welche,
    steht daneben.` and returned

        Zu diesem Ziel sind die Parameter für die Zielgruppe, den Zielmarkt, die Zielstrategie und den
        Zielzeitraum noch offen; welche, steht daneben.

    Four invented parameter names. The five real ones are `safety`, `liquidity_need`,
    `volatility_tolerance`, `horizon` and `flexibility` — none of those four exists anywhere in the
    system. It carried no figure, added no sentence, sat inside the length allowance and passed C-01, so
    **every guard that existed at that moment was satisfied by a sentence that had made up its subject.**

    Found by running the feature against the model rather than by reasoning about the checks — A76's
    instruction, and the second time in this module it produced a hole nobody had listed.

    **Planted:** removed the `_introduced_content_words` call from `_rephrase`. Failed on `Zielgruppe`
    reaching the payload. Restored.
    """
    invention = (
        "Zu diesem Ziel sind die Parameter für die Zielgruppe, den Zielmarkt, die Zielstrategie "
        "und den Zielzeitraum noch offen."
    )
    # The probe used to be pinned as something C-01 would NOT catch, so this test could only pass by
    # way of the containment check it is about. With C-01 gone there is one check left and no pin.
    monkeypatch.setattr(
        befund_module.llm, "chat", lambda *a, **k: llm.Reply(text=invention, model="planted")
    )
    report = _report(session, marc, prose=True)
    for word in ("Zielgruppe", "Zielmarkt", "Zielstrategie", "Zielzeitraum"):
        assert not any(word in one for one in sentences(report)), f"{word} survived"
    assert all(one["sentence_origin"] == "computed" for one in _facts(report))
    assert "content_introduced" in {entry["reason"] for entry in report["prose"]["refused"]}


def test_a_model_that_drops_what_would_go_there_is_discarded(session, member, monkeypatch):
    """"No latitude to add, OMIT or reorder" is three verbs, and containment one way covers one of them.

    Also found in the live model's *accepted* output rather than by reasoning. apertus:8b returned

        Stabilisierung (Humankapital): hier steht nichts. Kleinere, voneinander unabhängige
        Einkommensquellen verringern die Schwankungen des Ganzen.

    which quietly dropped `Was hier hingehört:` — and with it R-110's entire point, that an empty cell
    states what would go there rather than that there is nothing. It introduced no word, added no
    sentence, carried no figure and passed C-01, so it was accepted.

    **Planted:** removed the second `_introduced_content_words` call from `_rephrase`. Failed on the
    truncated sentence reaching the payload. Restored.
    """

    def truncate(prompt, **_kwargs):
        # Drop the R-110 clause the way the real model did, keeping everything else.
        return llm.Reply(text=prompt.replace("Was hier hingehört: ", ""), model="planted")

    monkeypatch.setattr(befund_module.llm, "chat", truncate)
    report = _report(session, member, prose=True)
    for one in _facts(report, "plan"):
        if one["key"] == "cell_empty":
            assert "Was hier hingehört" in one["sentence"], (
                "R-110's clause was dropped by the model and the report kept the truncation"
            )
    assert "content_omitted" in {entry["reason"] for entry in report["prose"]["refused"]}


def test_the_containment_check_separates_inflection_from_invention():
    """The boundary this check turns on, pinned in both directions.

    Getting it right took two attempts and both failures are worth keeping visible: a pure prefix rule
    made `Ziel` and `Zielgruppe` the same word, and raising the prefix floor to fix that made `Ziel` and
    `Ziels` different words. The length-difference rule is what separates an ending from a word.
    """
    # Invention — every one of these must be reported.
    assert _introduced_content_words(
        "Zu diesem Ziel sind die Parameter für die Zielgruppe und den Zielmarkt noch offen.",
        "Zu diesem Ziel sind einzelne der fünf Parameter noch offen; welche, steht daneben.",
    ) == ["Zielgruppe", "Zielmarkt"]
    assert _introduced_content_words(
        "Es liegt kein Entscheidungsgegenstand vor.", "Es liegt nichts zur Entscheidung vor."
    ) == ["Entscheidungsgegenstand"], "a compound built on a word that was there is still a new word"
    assert _introduced_content_words(
        "Keine erfasste Position dient als Deckung für dieses Ziel.",
        "Keine erfasste Position ist als Deckung dieses Ziels hinterlegt.",
    ) == ["dient"]

    # Legitimate variation — none of these may be reported.
    for candidate, original in (
        ("In Ihrem Plan steht hier nichts.", "Hier steht nichts in Ihrem Plan."),
        (
            "Ihr Plan hält den Betrag Ihres Humankapitals in Franken nicht fest.",
            "Ihr Humankapital als Betrag in Franken — das hält Ihr Plan nicht fest.",
        ),
        # A78: ASCII-typed German is how German is typed, not an evasion. `_fold` handles it.
        (
            "Die Felder darunter sagen, was in jedes davon gehoert.",
            "Die Felder darunter sagen, was in jedes davon gehört.",
        ),
        ("Your plan records nothing here.", "Nothing here: your plan records nothing."),
    ):
        assert _introduced_content_words(candidate, original) == [], (
            f"the containment check rejected legitimate variation: {candidate!r}"
        )


def test_every_word_the_befund_composes_is_covered_by_the_function_word_list_or_its_own_copy():
    """A guard on `_FUNCTION_WORDS` itself: it must not have grown a content word.

    A function-word list is a place where a content word can hide — put `Rendite` in it and the model may
    introduce `Rendite` anywhere. Checked by requiring that no word in the list appears as a *subject*
    or a figure-bearing term in this module's own copy vocabulary.
    """
    from eigentlich.services.befund import _FUNCTION_WORDS, GAP_SUBJECTS

    substantive = {"rendite", "franken", "francs", "position", "ziel", "goal", "plan", "annahme",
                   "schulden", "debt", "vermoegen", "vermögen", "humankapital", "dokument",
                   "entscheidung", "decision", "assumption", "return", "wealth", "amount", "betrag"}
    leaked = sorted(word for word in _FUNCTION_WORDS if word.lower() in substantive)
    assert not leaked, f"_FUNCTION_WORDS contains content words, which the model could then invent: {leaked}"
    assert len(_FUNCTION_WORDS) > 100, "the function-word list is too small to be the one described"
    # And the gap subjects are all content, so none of them may be freely introducible.
    for subject in set(GAP_SUBJECTS.values()):
        assert subject not in _FUNCTION_WORDS


def test_a_model_that_adds_a_sentence_is_discarded(session, marc, monkeypatch):
    """No latitude to add. A second sentence is an addition whether or not it carries a figure.

    **This test found a real hole and the fix changed the design.** `_rephrase` used to send the whole
    fact and compare sentence counts. A two-sentence computed fact came back as two sentences with the
    second replaced by `Übrigens ist das ein guter Ausgangspunkt` — an opinion, no figures, inside the
    length bound, count satisfied — and it reached the payload. `_rephrase` now sends one sentence at a
    time under a one-in-one-out contract, which makes the addition structurally impossible rather than
    improbable. Written as a probe, not reasoned about: A76's instruction exactly.

    **Planted after the fix:** relaxed the check back to `!= 1` → `> 1`. Still caught. Relaxed it to
    comparing whole-fact counts again: this test failed. Restored.
    """
    monkeypatch.setattr(
        befund_module.llm,
        "chat",
        lambda *a, **k: llm.Reply(
            text="Hier steht nichts. Übrigens ist das ein guter Ausgangspunkt.", model="planted"
        ),
    )
    report = _report(session, marc, prose=True)
    assert "Ausgangspunkt" not in json.dumps(report, ensure_ascii=False)
    assert all(f["sentence_origin"] == "computed" for f in _facts(report))
    assert report["prose"]["refused"], "the addition was accepted silently"
    assert {e["reason"] for e in report["prose"]["refused"]} == {"sentence_added"}


def test_a_faithful_rephrasing_is_accepted(session, member, monkeypatch):
    """A gate, not a wall. If nothing were ever accepted, none of the four checks above would be load-bearing.

    The stub returns the sentence it was handed with one word changed, which is the whole of what the
    model is allowed to do.
    """
    calls: list[str] = []

    def echo(prompt, **_kwargs):
        calls.append(prompt)
        # `hier` → `da` is a function-word swap, which after the containment check is very close to the
        # whole of what a rephrasing may legitimately be. The earlier stub substituted `an dieser
        # Stelle` and is now correctly refused for introducing `Stelle`.
        return llm.Reply(text=prompt.replace("hier", "da").replace("here", "there"), model="planted")

    monkeypatch.setattr(befund_module.llm, "chat", echo)
    report = _report(session, member, prose=True)
    assert calls, "the model was never called"
    assert report["prose"]["used"] is True
    assert any(f["sentence_origin"] == "model" for f in _facts(report))
    assert any(" da " in f["sentence"] for f in _facts(report))
    # Whatever it rewrote used to have to pass C-01 too. That gate is gone (A164); the figure and
    # containment checks are what a model-rewritten sentence still has to survive.


def test_a_model_written_sentence_carries_the_computed_one_beside_it(session, member, monkeypatch):
    """"Code owns the figures and the structure" has to be checkable after the fact.

    Whenever the model replaced a sentence, the deterministic text it replaced is in the payload. An
    auditor compares the two rather than taking the model's word for it — and the invariant is in the
    `Fact` constructor, so a fact cannot claim a model origin without producing what it displaced.

    **Planted:** dropped the `computed_sentence` check from `__post_init__` and had `rephrased` omit it.
    Both halves below stopped raising. Restored.
    """
    monkeypatch.setattr(
        befund_module.llm,
        "chat",
        lambda prompt, **k: llm.Reply(
            text=prompt.replace("hier", "da").replace("here", "there"), model="planted"
        ),
    )
    facts = _facts(_report(session, member, prose=True))
    changed = 0
    for fact in facts:
        if fact["sentence_origin"] == "model":
            assert fact["computed_sentence"], "a model sentence with nothing to compare it against"
            # Equality is legitimate: the stub only rewrites sentences containing "hier", and a faithful
            # rephrasing that changed nothing is still a model-origin sentence. What must hold is that
            # the deterministic text is present, not that it differs.
            changed += fact["computed_sentence"] != fact["sentence"]
        else:
            assert fact["computed_sentence"] is None, (
                "a computed sentence duplicated itself into computed_sentence; a client would render both"
            )
    assert changed, "the model changed nothing anywhere, so this proves nothing about the pairing"

    with pytest.raises(ValueError, match="computed_sentence"):
        Fact(
            section="plan",
            key="planted",
            sentence="Hier steht etwas in Ihrem Plan.",
            source="computed_from_plan",
            data_class=int(DataClass.K2),
            sentence_origin="model",
        )
    with pytest.raises(ValueError, match="computed_sentence"):
        Fact(
            section="plan",
            key="planted",
            sentence="Hier steht etwas in Ihrem Plan.",
            source="computed_from_plan",
            data_class=int(DataClass.K2),
            computed_sentence="Hier steht etwas.",
        )


def test_a_non_local_model_host_is_never_absorbed(session, marc, monkeypatch):
    """`llm.NotLocal` is not a degradation. C-05 makes eigentliCH sole data controller and there is no
    configuration that permits a hosted model — so this propagates rather than falling back to the
    computed sentence, which would make an illegal configuration invisible."""

    def not_local(*_args, **_kwargs):
        raise llm.NotLocal("planted: a hosted model host was configured")

    monkeypatch.setattr(befund_module.llm, "chat", not_local)
    with pytest.raises(llm.NotLocal):
        _report(session, marc, prose=True)


# ============================================================ completeness of the gap layer


def test_every_reportable_gap_has_a_member_facing_subject():
    """The guard that makes `not_known` complete rather than merely populated.

    Walks the live engine manifests through `engine_inputs`, not `GAP_SUBJECTS`. If an engine declares a
    new plan-blocking input and nobody writes a member-facing subject for it, this fails — rather than the
    gap silently vanishing from the one section whose value is that it hides nothing.

    **Planted:** deleted `"D"` from `GAP_SUBJECTS`. Failed naming `D`, and the report itself raised
    `KeyError` with the instruction to add a subject. Restored.
    """
    missing = []
    for gap in reportable_gaps(member_id="probe", positions=[], today=TODAY):
        if gap.name not in GAP_SUBJECTS:
            missing.append(f"{gap.engine}.{gap.name}")
    assert not missing, f"plan-blocking engine inputs with no member-facing subject: {missing}"

    # And every subject has copy in both languages.
    for subject in sorted(set(GAP_SUBJECTS.values())):
        for language in LANGUAGES:
            assert PHRASE[language].get(subject), f"no {language} copy for gap subject {subject!r}"


def test_the_gap_subject_lookup_raises_rather_than_dropping(session, marc, monkeypatch):
    """A silent drop would be the worst failure this module can have.

    **Planted:** replaced the `raise` with `continue`. This test failed. Restored.
    """
    monkeypatch.setitem(befund_module.GAP_SUBJECTS, "W_L", None)
    monkeypatch.delitem(befund_module.GAP_SUBJECTS, "W_L")
    with pytest.raises(KeyError, match="GAP_SUBJECTS"):
        _report(session, marc)


def test_only_the_two_plan_blocking_kinds_are_reported():
    """A gap the caller owns is not a gap in the member's plan — A39 is explicit, and so is this."""
    kinds = {gap.kind for gap in reportable_gaps(member_id="probe", positions=[], today=TODAY)}
    assert kinds <= set(engine_inputs.PLAN_GAP_KINDS)
    assert "supplied_by_the_caller" not in kinds
    assert "owned_by_the_engine" not in kinds


def test_the_manifests_still_declare_the_inputs_this_module_names():
    """`GAP_SUBJECTS` is keyed on engine input names. A renamed input must not become a dead entry."""
    declared = set()
    for engine in engine_inputs._BUILDERS:  # noqa: SLF001 — the registry is the authority
        declared |= set(load_manifest(engine).inputs)
    unknown = sorted(set(GAP_SUBJECTS) - declared)
    assert not unknown, f"GAP_SUBJECTS names inputs no manifest declares: {unknown}"


# ============================================================ i18n parity of this module's own copy


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_copy_tables_carry_the_same_keys_in_both_languages(language):
    """A12. Neither language may quietly gain a phrase the other lacks.

    **Planted:** deleted `goal_unfunded` from the English table. Failed naming it. Restored.
    """
    other = [name for name in LANGUAGES if name != language]
    for name in other:
        assert set(PHRASE[language]) == set(PHRASE[name]), (
            f"copy is out of parity.\n  only in {language}: "
            f"{sorted(set(PHRASE[language]) - set(PHRASE[name]))}\n  only in {name}: "
            f"{sorted(set(PHRASE[name]) - set(PHRASE[language]))}"
        )
        assert set(SECTION_TITLE[language]) == set(SECTION_TITLE[name])


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_phrase_is_empty_and_every_placeholder_is_matched(language):
    for key, template in PHRASE[language].items():
        assert template.strip(), f"{language}.{key} is empty"
        assert template.count("{") == template.count("}"), f"{language}.{key} has an unmatched brace"
    for key, title in SECTION_TITLE[language].items():
        assert title.strip(), f"{language} section title {key} is empty"
    assert set(SECTION_TITLE[language]) == set(SECTIONS)


def test_the_german_copy_round_trips_as_utf8():
    """A20's hazard, and the standing instruction that source is written through the editor.

    Umlauts in this module are precomposed and survive a byte round trip. A file that has been through a
    PowerShell redirect or a bash heredoc fails one of these.
    """
    import unicodedata

    raw = SERVICE.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf", "the source gained a UTF-8 BOM"
    text = raw.decode("utf-8")
    assert unicodedata.normalize("NFC", text) == text, "umlauts were decomposed"
    assert not [c for c in text if 0x300 <= ord(c) <= 0x36F], "combining marks in the source"
    assert sum(text.count(c) for c in "äöüÄÖÜß") > 20, "the German copy lost its umlauts"
    for word in ("hingehört", "Grösse", "fünf", "veröffentlicht", "zurück", "gewöhnliche"):
        assert word in text, f"{word!r} did not survive the round trip"


# ============================================================ R-175


def test_the_report_writes_nothing(session, marc):
    """R-175. Nothing is proactive: the report is produced when asked for and changes no state.

    **Planted:** had `_prepared_decision_facts` persist an `ActionItem` for every undated expiry. Failed
    naming the row count. Restored.
    """
    from sqlalchemy import func, select

    from eigentlich.models import ActionItem, Decision

    def rows(model):
        return session.execute(select(func.count()).select_from(model)).scalar_one()

    before = (rows(ActionItem), rows(Decision), rows(Position), rows(Goal), rows(VaultItem))
    _report(session, marc)
    _report(session, marc, "en")
    _report(session, marc, prose=False)
    assert (rows(ActionItem), rows(Decision), rows(Position), rows(Goal), rows(VaultItem)) == before
    assert not session.new and not session.dirty and not session.deleted


def test_the_payload_states_that_it_is_delivered_on_request(session, marc):
    """A client author reads the payload before the docstring. R-175 is in it."""
    assert _report(session, marc)["delivered_on_request_only"] is True


# ============================================================ the route


@pytest.fixture()
def api(api_session, fast_kdf):
    """The whole application over HTTP, authenticated. A11: the member is the token's."""
    from fastapi.testclient import TestClient

    from eigentlich.api.main import app
    from eigentlich.services.auth import login, register_with_credentials
    from conftest import session_overrides

    member, _credential = register_with_credentials(
        api_session,
        email="befund@eigentli.local",
        password="ein-langes-passwort-fuer-den-test",
        age_at_registration=35,
        display_name="Befund Test",
    )
    api_session.commit()
    _row, token = login(
        api_session, email="befund@eigentli.local", password="ein-langes-passwort-fuer-den-test"
    )
    api_session.commit()

    app.dependency_overrides.update(session_overrides(api_session))
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        yield client, member, api_session
    finally:
        app.dependency_overrides.clear()


def test_the_route_serves_a_report(api):
    client, _member, _session = api
    response = client.get("/api/befund")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [block["key"] for block in payload["sections"]] == list(SECTIONS)
    assert payload["language"] == "de"


def test_the_route_refuses_an_unwritten_language(api):
    client, _member, _session = api
    assert client.get("/api/befund", params={"language": "rm"}).status_code == 422


def test_the_route_takes_no_member_id(api):
    """A11. There is no version of this route that reads somebody else's Befund.

    **Planted:** added `member_id: str | None = None` to the route and passed it through. This test
    failed on the parameter being accepted and honoured. Restored.
    """
    client, member, _session = api
    mine = client.get("/api/befund").json()["member_id"]
    assert mine == member.id
    # A member_id in the query string is ignored, not honoured — FastAPI drops unknown query params.
    other = client.get("/api/befund", params={"member_id": "somebody-else"}).json()["member_id"]
    assert other == member.id

    source = ast.parse(ROUTE.read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {arg.arg for arg in node.args.args + node.args.kwonlyargs}
            assert "member_id" not in names, f"{node.name} takes member_id as a parameter"


def test_the_route_needs_a_credential(api):
    client, _member, _session = api
    del client.headers["Authorization"]
    assert client.get("/api/befund").status_code == 401


def test_the_route_is_a_get_and_there_is_no_post(api):
    """R-175 at the HTTP surface: nothing here schedules or pushes a report."""
    client, _member, _session = api
    assert client.post("/api/befund", json={}).status_code == 405


def test_the_route_is_registered_exactly_once():
    """A router wired twice serves a duplicate that shadows the first, and the shadow is invisible."""
    from eigentlich.api.main import app

    def walk(routes):
        """`app.routes` is not flat in this FastAPI: `include_router` leaves an `_IncludedRouter`
        wrapper whose children hang off `original_router`. A non-recursive scan finds nothing and
        would have made this assertion vacuous in the other direction."""
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                yield path
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk(nested.routes)

    found = [path for path in walk(app.routes) if path == "/api/befund"]
    assert found, "/api/befund is not registered at all"
    assert len(found) == 1, f"/api/befund is registered {len(found)} times"


# ============================================================ guards on the guards


def test_the_word_filters_used_here_are_not_vacuous():
    """A20's hazard, third appearance in this repository: a filter that matches nothing passes everything."""
    assert _whole_words(("filled",), "3 of 8 filled") == ["filled"]
    assert _whole_words(("filled",), "the unfilled cell") == [], "must not fire inside a compound"
    assert _whole_words(("score",), "underscore") == []
    assert _whole_words(("ratio",), "a ratio of two") == ["ratio"]
    assert _whole_words(("count",), "two accounts") == [], "must not fire inside accounts"
    assert TALLY_WORDS, "the tally vocabulary is empty; every payload check above is vacuous"
    assert GAMIFICATION_IDENTIFIERS, "the identifier set is empty; the AST walk above is vacuous"


def test_the_report_scanner_actually_reads_a_populated_report(session, marc):
    """Every payload filter above runs over one blob. An empty one would make all of them pass.

    A68's practice stated for this file: a test that asserts something is absent must be proven able to
    detect its presence, and the first thing to prove is that it looked at anything at all.
    """
    blob = json.dumps(_report(session, marc), ensure_ascii=False, default=str)
    assert len(blob) > 4000, f"the report blob is only {len(blob)} characters; the scan is vacuous"
    assert "Hypothek" in blob, "the member's own goal is missing from the payload"
    assert "Hausratversicherung" in blob, "the vault items are missing from the payload"
    facts = _facts(_report(session, marc))
    assert len(facts) > 25, f"only {len(facts)} facts; the per-fact assertions above prove little"
    assert len({fact["key"] for fact in facts}) > 10, "the report says the same thing repeatedly"


def test_the_source_stripper_keeps_the_code_and_drops_the_prose():
    """`_code_only` is what lets this module's docstrings quote the words they forbid."""
    stripped = _code_only(SERVICE)
    assert "completion meter" not in stripped, "the docstring quoting R-113 was not stripped"
    assert "def render_befund" in stripped, "the stripper removed code as well as prose"
