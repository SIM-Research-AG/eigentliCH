"""The three-branch router. Item 1, and the two boundaries of Journey & Design page 3.

The split is by regulatory status, not by topic, so the tests are organised by branch and the hardest
cases are the ones where topic and status disagree — a question about a fund that is education, and a
question about the weather-vague "what should I do" that is not.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from eigentlich.models import ADULT, Goal, Position
from eigentlich.services import household as household_service
from eigentlich.services.household import Person
from eigentlich.services.know import ask, missing_personal_input
from eigentlich.services.plan import mutate_plan
from eigentlich.services.router import BOUNDARIES, SPECS, Branch, Route, route
from eigentlich.services.vault import VaultStore

from datetime import date

MARCH = date(2027, 3, 14)


@pytest.fixture()
def store(tmp_path):
    return VaultStore(tmp_path / "vault")


# ============================================================ branch 1 — a fact about the world


@pytest.mark.parametrize(
    "question",
    [
        # The update script's own example.
        "How does the AHV household cap work?",
        "Wie funktioniert der AHV-Plafond für Ehepaare?",
        "Was ist ein Freizügigkeitskonto?",
        "Wie hoch ist der Koordinationsabzug?",
        # A product comparison between two CATEGORIES. Item 1 puts this below both boundaries: the test
        # is whether a comparison site could publish the same sentence, and it could.
        "Ist ein ETF günstiger als ein aktiver Fonds?",
        "Was kostet ein Wertschriften-3a im Vergleich zu einem Konto-3a?",
    ],
)
def test_a_fact_about_the_world_is_branch_one(question):
    routed = route(question)
    assert routed.branch is Branch.POPULATION_FACT
    assert routed.boundary == "below_both"
    assert routed.reads_member_data is False
    assert routed.requires_curator is False


# ============================================================ branch 2 — the member's own situation


@pytest.mark.parametrize(
    "question",
    [
        "What does that mean for us?",
        "Was bedeutet das für uns?",
        "Wie hoch ist mein 3a-Guthaben?",
        "Was steht in meiner Police?",
        "Wann können wir in Rente?",
        "How much have I got in my pillar 3a?",
    ],
)
def test_a_question_about_the_member_is_branch_two(question):
    routed = route(question)
    assert routed.branch is Branch.MEMBER_SITUATION
    assert routed.boundary == "per_member_computation"
    assert routed.reads_member_data is True
    assert routed.requires_curator is False
    assert routed.matched, "a personal route says why it decided the question was personal"


# ============================================================ branch 3 — regulated advice
# ============================================================ the enum is the one place


def test_every_branch_has_a_spec_and_the_module_refuses_to_import_without_one():
    """Item 1: adding a fourth branch requires touching one place."""
    assert set(SPECS) == set(Branch)
    assert all(spec.boundary in BOUNDARIES for spec in SPECS.values())


def test_a_branch_without_a_spec_fails_the_import_check():
    """The guard on the guard. An import-time contract nobody has seen fail is an unproven one."""
    import eigentlich.services.router as router_module

    original = router_module.SPECS
    try:
        router_module.SPECS = {Branch.POPULATION_FACT: original[Branch.POPULATION_FACT]}
        with pytest.raises(RuntimeError) as raised:
            router_module._check_every_branch_is_specified()
        assert "MEMBER_SITUATION" in str(raised.value)
    finally:
        router_module.SPECS = original
    router_module._check_every_branch_is_specified()


def test_the_route_carries_the_patterns_and_never_the_question():
    """A route travels in a payload and a log line. The member's own words do not."""
    question = "Wie hoch ist mein 3a-Guthaben bei der Bank Y?"
    payload = route(question).as_dict()
    blob = str(payload)
    assert "Bank Y" not in blob
    assert "3a-Guthaben" not in blob
    # `reason` left the payload with C-01 (A165): it was the key into the refusal table, and there is
    # no refusal. `requires_curator` stays as a constant False — see the property's own docstring.
    assert set(payload) == {
        "branch",
        "boundary",
        "reads_member_data",
        "requires_curator",
        "matched",
    }


def test_the_router_is_pure():
    """No session, no corpus, no model. It is safe to call before authentication.

    Asserted over the module's AST rather than by grepping its text: the first version of this test
    grepped for "session" and failed on its own docstring, which is the shape of check that passes or
    fails for reasons unrelated to the property it names.
    """
    import ast
    import inspect

    from eigentlich.services import router as router_module

    tree = ast.parse(inspect.getsource(router_module))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            imported.update(alias.name for alias in node.names)

    for forbidden in ("sqlalchemy", "llm", "requests", "httpx", "Session"):
        assert forbidden not in imported, (
            f"the router imports {forbidden!r}; it classifies and nothing else"
        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
            assert "session" not in names, f"{node.name} takes a session"


# ============================================================ branch 1 touches no member data


def test_a_population_question_does_not_read_the_members_vault(session, store, member):
    """The claim, measured rather than asserted: the retrieval is not called at all.

    Before item 1 `own_material` ran for every question, so a fact about the world was answered with the
    member's vault in front of it. Nothing leaked, but the first boundary was crossed to answer a question
    that sits below it.
    """
    from eigentlich.services import know as know_module

    calls: list[str] = []
    original = know_module.member_material

    def watched(*args, **kwargs):
        calls.append(kwargs.get("question", ""))
        return original(*args, **kwargs)

    know_module.member_material = watched
    try:
        ask(session, member_id=member.id, question="Wie funktioniert der AHV-Plafond?")
        assert calls == [], "branch 1 read the member's vault"

        ask(session, member_id=member.id, question="Wie hoch ist mein AHV-Anspruch?")
        assert len(calls) == 1, "branch 2 must still read it"
    finally:
        know_module.member_material = original


def test_the_curriculum_is_available_on_every_branch(session, member):
    """Learning units are K0 — the same for every member — so withholding them on branch 1 would have
    withheld the curriculum from the questions it exists to answer."""
    from eigentlich.services.know import learning_material, member_material

    import inspect

    assert "current_items" not in inspect.getsource(learning_material)
    assert "LearningUnit" not in inspect.getsource(member_material)


# ============================================================ branch 2 with an empty Vault


def test_branch_two_with_an_empty_vault_does_not_fail(session, store, member):
    """Item 1: it answers the population part, then names the single input that would make it personal."""
    answer = ask(session, member_id=member.id, question="Was bedeutet der AHV-Plafond für uns?")

    assert answer.requires_curator is False
    assert answer.route["branch"] == "member_situation"
    assert answer.personalisation is not None
    assert answer.personalisation["key"] == "household_composition"
    assert answer.personalisation["sentence"].strip()
    assert answer.personalisation["starts_at"] == "intake"


def test_the_named_input_follows_the_intake_order(session, store, member):
    """Household composition, then a position, then a goal — item 3's order and the light-intake floor."""
    assert missing_personal_input(session, member_id=member.id, language="de")["key"] == (
        "household_composition"
    )

    household_service.state(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=MARCH,
    )
    session.commit()
    assert missing_personal_input(session, member_id=member.id, language="de")["key"] == (
        "income_position"
    )

    with mutate_plan(
        session, member_id=member.id, question="Record employment?", choice="Yes"
    ) as decision:
        position = Position(
            member_id=member.id,
            role="income",
            capital_type="human",
            label="angestellt",
            magnitude=69_550.0,
            magnitude_unit="chf_per_year",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()
    assert missing_personal_input(session, member_id=member.id, language="de")["key"] == "first_goal"

    with mutate_plan(
        session, member_id=member.id, question="Record a goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()
    assert missing_personal_input(session, member_id=member.id, language="de") is None


def test_only_one_input_is_named_at_a_time(session, member):
    """Principle 4's shape: a member told three things are missing has been handed a backlog."""
    named = missing_personal_input(session, member_id=member.id, language="de")
    assert isinstance(named, dict)
    assert set(named) == {"key", "sentence", "starts_at"}


def test_no_personalisation_is_offered_on_branch_one(session, store, member):
    """Nothing is missing for a question that was never about them."""
    answer = ask(session, member_id=member.id, question="Wie funktioniert der AHV-Plafond?")
    assert answer.route["branch"] == "population_fact"
    assert answer.personalisation is None


def test_the_named_input_sentence_is_content_and_not_generated(session, member):
    """Composed by code from a fixed phrase, the same rule as the refusal and for the same reason."""
    de = missing_personal_input(session, member_id=member.id, language="de")["sentence"]
    en = missing_personal_input(session, member_id=member.id, language="en")["sentence"]
    assert de != en
    assert "Haushalt" in de
    assert "household" in en


# ============================================================ every answer carries its route


def test_every_answer_says_which_branch_and_boundary_it_took(session, store, member):
    for question in (
        "Wie funktioniert der AHV-Plafond?",
        "Wie hoch ist mein 3a-Guthaben?",
        "Soll ich das Konto auflösen?",
    ):
        payload = ask(session, member_id=member.id, question=question).as_dict()
        assert payload["route"]["branch"] in {b.value for b in Branch}
        assert payload["route"]["boundary"] in BOUNDARIES
