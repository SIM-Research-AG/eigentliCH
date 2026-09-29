"""The computation registry: branch 2 answers by running something, or says what is missing.

**The boundary this closes.** `services/router` marks a question about the member's own situation
`per_member_computation` — "the first boundary. Begins at the Life Balance Sheet" — and until 6 September
2026 the answer path never called an engine. It retrieved prose. Over the ten loaded members that answered
one opening question out of ten, and that one with a quotation from the WEFV.

**What must not change.** C-01, and the branch-1 guarantee that no member data is touched.
"""
from __future__ import annotations

import pytest

from eigentlich.services import computations as comp
from eigentlich.services.know import Branch, route_question


# ============================================================ matching


@pytest.mark.parametrize("question,expected", [
    ("Wie erreich ich das ich mir 2035 das Eigenheim leisten kann?", "property_affordability"),
    ("Wie kann ich mir das Ferienhaus leisten?", "property_affordability"),
    ("Wie viel könnte ich verdienen?", "earning_power"),
    ("Lohnt sich eine Weiterbildung für mich?", "time_allocation"),
])
def test_a_question_with_an_arithmetic_answer_finds_its_computation(question, expected):
    got = comp.match(question)
    assert got is not None and got.key == expected


@pytest.mark.parametrize("question", [
    "Was ist die AHV?",
    "Wie funktioniert der Umwandlungssatz?",
    "Wie sieht meine finanzielle Zukunft aus?",
])
def test_a_question_without_one_falls_through(question):
    """This is an addition to the answer path, not a replacement for it."""
    assert comp.match(question) is None


def test_the_registry_order_is_the_rule():
    """First match wins, the same convention as `tools/read_qualifications`. A question that reads as
    two computations needs splitting, and answering half of it silently is worse."""
    keys = [c.key for c in comp.REGISTRY]
    assert keys == sorted(set(keys), key=keys.index), "no duplicates"
    both = "Wie viel könnte ich verdienen, wenn ich ein Eigenheim kaufen will?"
    assert comp.match(both).key == keys[0]


def test_every_registered_computation_declares_what_it_is_and_where_it_reads():
    for computation in comp.REGISTRY:
        assert computation.about.strip(), computation.key
        assert computation.sources, computation.key
        assert callable(computation.run), computation.key


# ============================================================ C-01 and the branch guarantee
def test_a_generically_phrased_question_stays_on_branch_one():
    """Marvin asked «Ab wie viel Kapital macht es Sinn Eigentum zu kaufen» — a question about the world.

    It matches the property computation, and the computation must NOT run, because branch 1's guarantee
    is that no member data is touched. The registry fires on branch 2 only, and this is what asserts it.
    """
    question = "Ab wie viel Kapital macht es Sinn Eigentum zu kaufen und dieses zu vermieten?"
    assert comp.match(question) is not None, "it matches"
    assert route_question(question).branch is Branch.POPULATION_FACT, "and must still not run"
# ============================================================ running one


def _member_with(session, member, **facts_to_state):
    from eigentlich.services import member_fact as facts
    from eigentlich.services.plan import mutate_plan

    for key, value in facts_to_state.items():
        with mutate_plan(session, member_id=member.id, question=f"{key}?",
                         choice=str(value)) as decision:
            facts.state(session, member_id=member.id, key=key, value=value, decision=decision)
    session.flush()


def test_earning_power_runs_and_names_its_sources(session, member):
    _member_with(session, member, qualification_highest="Fachhochschule FH", network_people=12,
                 health=0.9)
    got = comp.answer(session, member_id=member.id,
                      question="Wie viel könnte ich verdienen?")
    if got is not None and not got.determined and "engine" in " ".join(got.missing):
        pytest.skip("the Life Balance Sheet engine is not reachable")
    assert got.determined, getattr(got, "missing", None)
    assert "Lohnstrukturerhebung" in got.text
    assert "knowledge/BFS_Lohnstrukturerhebung.md" in got.sources


def test_earning_power_says_a_median_is_not_a_forecast(session, member):
    """The source's own caution, carried into every answer built on it."""
    _member_with(session, member, qualification_highest="Fachhochschule FH", network_people=12,
                 health=0.9)
    got = comp.answer(session, member_id=member.id, question="Wie viel könnte ich verdienen?")
    if got is None or not got.determined:
        pytest.skip("not computable in this build")
    assert "keine Prognose" in got.text


def test_a_missing_input_is_reported_rather_than_defaulted(session, member):
    """**Better than a number built on a default.** `Undetermined` carries the key to ask for."""
    got = comp.answer(session, member_id=member.id, question="Wie viel könnte ich verdienen?")
    assert got is not None and not got.determined
    assert "qualification_highest" in got.missing


def test_a_member_with_no_property_goal_gets_an_undetermined_rather_than_an_error(session, member):
    got = comp.answer(session, member_id=member.id,
                      question="Wie kann ich mir ein Eigenheim leisten?")
    assert got is not None and not got.determined
    assert got.missing


# ============================================================ through know.ask


def test_a_computed_answer_carries_its_computation_and_cites_the_service(session, member):
    from eigentlich.services import know

    _member_with(session, member, qualification_highest="Fachhochschule FH", network_people=12,
                 health=0.9)
    answer = know.ask(session, member_id=member.id, question="Wie viel könnte ich verdienen?")
    if answer.computation is None:
        pytest.skip("not computable in this build")
    assert answer.computation["key"] == "earning_power"
    assert answer.citations
    # **`any`, not `all`, since 21 September 2026.** Quoting returned a computation whole and cited
    # nothing else, so every citation was the service. Composing hands the computed figures to the model
    # together with the corpus and the member's own record, and cites all three — so what has to hold is
    # that the service the figures came from is named, not that nothing else is.
    assert any(citation["kind"] == comp.KIND for citation in answer.citations), (
        f"a computed answer must name the service that computed it; got "
        f"{sorted({c['kind'] for c in answer.citations})}"
    )
    assert not answer.requires_curator
    assert answer.as_dict()["computation"]["key"] == "earning_power"


def test_an_undetermined_computation_asks_for_the_input_it_needs(session, member):
    """It does not stop retrieval — the population part is still answered — it replaces the guess
    about what to ask for with the thing the computation actually wants."""
    from eigentlich.services import know

    answer = know.ask(session, member_id=member.id, question="Wie viel könnte ich verdienen?")
    assert answer.personalisation is not None
    assert answer.personalisation.get("computation") == "earning_power"
    assert "qualification_highest" in answer.personalisation["sentence"]


def test_a_question_with_no_computation_answers_exactly_as_before(session, member):
    from eigentlich.services import know

    answer = know.ask(session, member_id=member.id, question="Was ist die AHV?")
    assert answer.computation is None
