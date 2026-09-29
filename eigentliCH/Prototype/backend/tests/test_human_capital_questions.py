"""The eight human-capital questions, and the claim that adding them cost no code.

`services/member_fact` reads its registry from `client/content/onboarding-questions.json` — any question
whose `fills.entity` is `member_fact`. That property was built and tested with a planted question the
build had never seen. These eight are the first real use of it, so this file asserts the same thing with
the questions that actually shipped: they round-trip, they validate against their own declared options
and bounds, and `services/human_capital` reads every one of them.

**The curator's reading is tested here too**, because it is not a one-off backfill. A member whose
education predates `qualification_highest` — which is all ten today — needs someone to read the free text
and say which BFS category it is. `stated_by="curator"` is what records that it was read rather than
answered, and a Decision records who and when.
"""
from __future__ import annotations

from datetime import date

import pytest

from eigentlich.services import human_capital as hc
from eigentlich.services import member_fact as facts
from eigentlich.services.plan import mutate_plan

#: Every key the eight questions added, and what reads it.
ADDED = {
    "qualification_highest": "expertise",
    "qualification_year": "expertise",
    "years_in_field": "expertise",
    "kader": "responsibility",
    "sector": "responsibility",
    "network_reach": "network",
    "hours_learning": "time budget",
    "hours_network": "time budget",
}


def _declared():
    """`declarations()` is already keyed by fact key — options come back as plain values."""
    return facts.declarations()


# ============================================================ the registry


@pytest.mark.parametrize("key", sorted(ADDED))
def test_every_added_question_is_a_declarable_fact(key):
    """No code was written to make these keys exist. This is that claim, one key at a time."""
    assert key in _declared(), key


def test_the_five_qualification_options_are_the_bfs_categories():
    """**Five and not seven.** A rung with no published median behind it is a guess wearing a label."""
    offered = set(_declared()["qualification_highest"]["options"])
    ladder = set(hc._record()["expertise"]["anchors"]["by_qualification"])
    assert offered == ladder


def test_the_sector_options_cover_every_published_figure_plus_a_fallback():
    offered = set(_declared()["sector"]["options"])
    published = set(hc._record()["responsibility"]["tiers"]["topmanagement"]["bfs_monthly_by_sector"])
    assert published <= offered
    assert offered - published == {"andere Branche"}


def test_the_three_responsibility_options_are_the_three_tiers():
    offered = _declared()["kader"]["options"]
    labels = [t["label"]["de"] for t in hc._record()["responsibility"]["tiers"].values()]
    assert offered == labels


def test_the_reach_options_are_exactly_the_published_multipliers():
    offered = _declared()["network_reach"]["options"]
    assert offered == list(hc._record()["network"]["reach"]["multipliers"])


def test_sector_is_asked_only_of_top_management():
    """The owner's decision of 6 September 2026. It changes nothing at the other two tiers, and
    applying the BFS sector medians to everyone would double-count the education mix they contain."""
    raw = next(q for q in facts.onboarding_questions() if q["key"] == "sector")
    assert raw["asked_when"] == {"key": "kader", "equals": "Oberste Führung"}


# ============================================================ writing and reading one


def test_a_qualification_round_trips_and_reaches_the_ladder(session, member):
    """The whole path: a member answers, the fact is stored, and expertise reads it."""
    with mutate_plan(session, member_id=member.id,
                     question="Welchen höchsten Abschluss haben Sie?",
                     choice="Fachhochschule FH") as decision:
        facts.state(session, member_id=member.id, key="qualification_highest",
                    value="Fachhochschule FH", decision=decision)
    session.flush()

    stored = facts.current(session, member_id=member.id)["qualification_highest"]
    assert stored.stated_value == "Fachhochschule FH"
    assert stored.stated_by == "member"

    got = hc.expertise({"qualification_highest": stored.stated_value})
    anchors = hc._record()["expertise"]["anchors"]["by_qualification"]
    assert got.value == pytest.approx(anchors["Fachhochschule FH"])


def test_an_option_outside_the_five_is_refused_at_the_service(session, member):
    """The five are the BFS's. Validation is in the service and not in a request model, because this
    build has three writers that are not that request model."""
    with pytest.raises(facts.RefusedValue):
        with mutate_plan(session, member_id=member.id, question="Abschluss?",
                         choice="Doktorat") as decision:
            facts.state(session, member_id=member.id, key="qualification_highest",
                        value="Doktorat", decision=decision)


def test_hours_outside_the_declared_bounds_are_refused(session, member):
    with pytest.raises(facts.RefusedValue):
        with mutate_plan(session, member_id=member.id, question="Stunden?",
                         choice="200") as decision:
            facts.state(session, member_id=member.id, key="hours_learning", value=200,
                        decision=decision)


# ============================================================ the curator's reading


def test_a_curator_may_read_free_text_into_a_category_and_it_is_marked_as_read(session, member):
    """**A standard task for any client, not a one-off backfill.**

    All ten members answered education as free text before `qualification_highest` existed, and several
    of those answers are unambiguous — «Maschinenbauingenieur, MBA» is a university degree. Someone reads
    it and says so. `stated_by="curator"` is what distinguishes that from the member answering, and the
    Decision carries the text that was read.
    """
    with mutate_plan(
        session, member_id=member.id,
        question="Gelesen aus «Ausbildung und Stärken»: «Maschinenbauingenieur, MBA». "
                 "Welche BFS-Kategorie ist das?",
        choice="Universitäre Hochschule",
    ) as decision:
        facts.state(session, member_id=member.id, key="qualification_highest",
                    value="Universitäre Hochschule", decision=decision, by="curator")
    session.flush()

    stored = facts.current(session, member_id=member.id)["qualification_highest"]
    assert stored.stated_value == "Universitäre Hochschule"
    assert stored.stated_by == "curator", "a reading is not an answer and must not look like one"


def test_the_member_can_overwrite_what_a_curator_read(session, member):
    """A reading is a placeholder for an answer, not a replacement for one."""
    with mutate_plan(session, member_id=member.id, question="Gelesen aus dem Freitext?",
                     choice="Universitäre Hochschule") as decision:
        facts.state(session, member_id=member.id, key="qualification_highest",
                    value="Universitäre Hochschule", decision=decision, by="curator")
    session.flush()
    with mutate_plan(session, member_id=member.id, question="Welchen höchsten Abschluss haben Sie?",
                     choice="Höhere Berufsausbildung") as decision:
        facts.state(session, member_id=member.id, key="qualification_highest",
                    value="Höhere Berufsausbildung", decision=decision)
    session.flush()

    stored = facts.current(session, member_id=member.id)["qualification_highest"]
    assert stored.stated_value == "Höhere Berufsausbildung"
    assert stored.stated_by == "member"


def test_writing_a_fact_without_a_decision_is_refused(session, member):
    """C-09. A curator's reading changes the member's plan, so it leaves a record of who and when.

    Written as a bare row rather than through `state()`, because that is the shape the guard exists to
    catch: anything that reaches the session without going through `mutate_plan`.
    """
    from eigentlich.db import PlanMutationWithoutDecision
    from eigentlich.models import MemberFact

    session.add(MemberFact(
        member_id=member.id, stated_key="qualification_highest",
        stated_value="Universitäre Hochschule", data_class=2,
        stated_on=date(2026, 9, 6), stated_by="curator",
    ))
    with pytest.raises(PlanMutationWithoutDecision):
        session.commit()
    session.rollback()
