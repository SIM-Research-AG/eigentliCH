"""S-01. R-101 resumability and R-102's one Position and first Goal."""

from __future__ import annotations

import pytest

from eigentlich.models import Decision, Goal, OnboardingAnswer, Position
from eigentlich.services import (
    OnboardingIncomplete,
    UnknownQuestion,
    answers,
    complete,
    resume_point,
    record_answer,
)


def test_onboarding_resumes_at_abandoned_question(session, member):
    """R-101's acceptance test, verbatim: abandon at n, return, resume at n.

    Household composition is answered first because it IS first (item 3, order 0). Before that it was
    `employment_position`, and this test read "resume at the second question" as "resume at
    employment_magnitude" — which is the same assertion, one question further along.
    """
    record_answer(
        session,
        member_id=member.id,
        question_key="household_composition",
        value={"adults": ["Ich"], "dependants": []},
    )
    session.commit()
    record_answer(session, member_id=member.id, question_key="employment_position", value="Treuhänderin")
    session.commit()

    # The member closes the tab here. Nothing is flushed on navigate, because nothing needed to be.
    state = resume_point(session, member_id=member.id)
    assert state["next_question_key"] == "employment_magnitude"
    assert state["answered_keys"] == ["employment_position", "household_composition"]


def test_the_first_question_is_the_household(session, member):
    """Item 3: "Household composition is asked first, before anything else. The AHV path, the tax path and
    goal ownership all depend on it."
    """
    assert resume_point(session, member_id=member.id)["next_question_key"] == "household_composition"


def test_a_skipped_question_is_a_recorded_answer_and_the_intake_moves_on(session, member):
    """Item 3: "The onboarding is offered but never forced."

    Household composition is asked first and is NOT required, so a member who declines has to be able to
    get past it. A skip is a row with a null value — which makes it answered, so `resume_point` advances —
    rather than an absence, which would return them to the same question every time they came back. That
    is the difference between a question and a nag (R-175).
    """
    record_answer(session, member_id=member.id, question_key="household_composition", value=None)
    session.commit()

    state = resume_point(session, member_id=member.id)
    assert state["next_question_key"] == "employment_position"
    assert state["answered_keys"] == ["household_composition"]


def test_each_answer_is_its_own_row(session, member):
    """R-101: partial state persists PER QUESTION, not per session."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="A")
    session.commit()
    record_answer(session, member_id=member.id, question_key="employment_magnitude", value=92000)
    session.commit()

    rows = session.query(OnboardingAnswer).filter_by(member_id=member.id).all()
    assert len(rows) == 2
    assert {r.question_key for r in rows} == {"employment_position", "employment_magnitude"}


def test_reanswering_updates_rather_than_appends(session, member):
    """A typo corrected is not a second answer, and two rows would make 'where did they get to' ambiguous."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Treuhanderin")
    session.commit()
    record_answer(session, member_id=member.id, question_key="employment_position", value="Treuhänderin")
    session.commit()

    rows = session.query(OnboardingAnswer).filter_by(member_id=member.id).all()
    assert len(rows) == 1
    assert rows[0].value == "Treuhänderin"


def test_every_answer_stamps_the_question_set_version(session, member):
    """A member resuming after the set changed must not have an answer re-pointed at a new question."""
    record_answer(session, member_id=member.id, question_key="first_goal", value="Haus")
    session.commit()
    row = session.query(OnboardingAnswer).filter_by(member_id=member.id).one()
    assert row.question_set_version == "onb2@0.1.0"


def test_unknown_question_is_refused(session, member):
    with pytest.raises(UnknownQuestion):
        record_answer(session, member_id=member.id, question_key="not_a_question", value=1)


def test_answers_are_not_plan_decisions(session, member):
    """Answering is not deciding. S-07 must not fill with keystrokes.

    Also proves the C-09 guard does not fire on an answer — if OnboardingAnswer were PlanMutable, this
    commit would raise.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="A")
    session.commit()
    assert session.query(Decision).filter_by(member_id=member.id).count() == 0


# ============================================================ R-102


def test_completion_writes_one_position_and_one_decision(session, member):
    for key, value in (
        ("employment_position", "Partnerin in einer Treuhandfirma"),
        ("employment_magnitude", 148000),
        ("employment_time_basis", 46),
    ):
        record_answer(session, member_id=member.id, question_key=key, value=value)
    session.commit()

    result = complete(session, member_id=member.id)
    session.commit()

    position = result["position"]
    assert position.role == "income" and position.capital_type == "human"
    assert position.label == "Partnerin in einer Treuhandfirma"
    assert position.magnitude == 148000
    assert position.magnitude_unit == "chf_per_year"
    assert position.time_basis == "46 Std./Woche"
    assert "goal" not in result

    assert session.query(Decision).filter_by(member_id=member.id).count() == 1
    assert result["decision"].linked_positions == [position]


def test_completion_writes_the_goal_only_if_stated(session, member):
    """R-102: '...and the member's first Goal IF STATED'."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    record_answer(session, member_id=member.id, question_key="first_goal", value="Wohneigentum 2031")
    session.commit()

    result = complete(session, member_id=member.id)
    session.commit()

    assert result["goal"].name == "Wohneigentum 2031"
    assert result["decision"].linked_goals == [result["goal"]]


def test_completion_without_a_magnitude_still_writes_a_position(session, member):
    """A30 / R-020. A position without an amount is a full position, and its unit stays absent."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Selbständig")
    session.commit()

    position = complete(session, member_id=member.id)["position"]
    session.commit()

    assert position.magnitude is None
    assert position.magnitude_unit is None, "R-120: a unit is never carried without its magnitude"


def test_completion_refuses_without_the_required_answer(session, member):
    record_answer(session, member_id=member.id, question_key="first_goal", value="Nur ein Ziel")
    session.commit()
    with pytest.raises(OnboardingIncomplete):
        complete(session, member_id=member.id)


def test_the_first_screen_says_something_true_about_the_member(session, member):
    """Principle 2: the first session produces one true, specific statement about the member's situation.

    The forbidden version is 'an onboarding completion screen that only echoes submitted values'. The
    Decision written at completion is the check: it must name what was recorded, not merely that something
    was.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Ärztin")
    record_answer(session, member_id=member.id, question_key="first_goal", value="Praxis 2030")
    session.commit()

    decision = complete(session, member_id=member.id)["decision"]
    session.commit()

    assert "Ärztin" in decision.choice
    assert "Praxis 2030" in decision.choice


def test_resume_point_reports_no_count(session, member):
    """R-113. 'Where to resume' is a question key, never 'n of m'."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="A")
    session.commit()
    state = resume_point(session, member_id=member.id)
    for forbidden in ("total", "count", "remaining", "percent", "completed", "of_total"):
        assert forbidden not in state, f"R-113: resume payload carries {forbidden!r}"


def test_completion_cannot_run_twice(session, member):
    """A double-click must not duplicate the member's plan.

    Found by walking the real flow rather than by a test: completing twice produced two identical
    positions and two Decisions, and R-040 meant neither Decision could be removed afterwards. The guard
    is an explicit timestamp on Member, set inside the same transaction as the writes it protects.
    """
    from eigentlich.services import OnboardingAlreadyComplete

    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    session.commit()

    complete(session, member_id=member.id)
    session.commit()

    with pytest.raises(OnboardingAlreadyComplete):
        complete(session, member_id=member.id)

    assert session.query(Position).filter_by(member_id=member.id).count() == 1
    assert session.query(Decision).filter_by(member_id=member.id).count() == 1


def test_completion_marks_the_member_in_the_same_transaction(session, member):
    """Set outside the transaction, a crash between the two would let a member duplicate their own plan."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    session.commit()
    assert member.onboarding_completed_at is None

    complete(session, member_id=member.id)
    session.commit()
    assert member.onboarding_completed_at is not None


def test_german_text_round_trips_through_the_store(session, member):
    """A German product must keep German text intact.

    Not paranoia: an earlier manual check sent an umlaut as cp1252 and the answer silently did not
    persist. The store was innocent, but nothing was asserting that.
    """
    value = "Unabhängigkeit ab 2038 — Zürich, Grossmünster"
    record_answer(session, member_id=member.id, question_key="first_goal", value=value)
    session.commit()
    session.expire_all()
    assert answers(session, member_id=member.id)["first_goal"] == value


# ============================================================ the goal question fills the goal out
#
# The owner, 31 August 2026: "We have the potential goals already defined and when in the onboarding the
# system ask for a goal, then we should immediately fill that goal out." It did not: the question took free
# text, `complete` stored the sentence as the goal's NAME, and `template` stayed null — so "Frühpensionierung"
# arrived as a goal eigentliCH could not recognise as one of its own kinds.


def test_a_chosen_template_lands_on_the_goal(session, member):
    """The owner's request, in one assertion.

    **Planted violation:** dropped `template=goal_template` from the `Goal(...)` call, which is exactly
    what the code did before. Failed on `template is None`. Restored.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Ärztin")
    record_answer(
        session,
        member_id=member.id,
        question_key="first_goal",
        value={"template": "early_retirement", "name": "Frühpensionierung"},
    )
    session.commit()

    goal = complete(session, member_id=member.id)["goal"]
    session.commit()
    assert goal.template == "early_retirement"
    assert goal.name == "Frühpensionierung"


def test_the_member_may_keep_their_own_words_and_still_carry_the_template(session, member):
    """The template is a shape, not a label the member has to accept. Someone whose early retirement is
    "Praxis mit 58 abgeben" should be able to say so and still have the goal carry the kind."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Ärztin")
    record_answer(
        session,
        member_id=member.id,
        question_key="first_goal",
        value={"template": "early_retirement", "name": "Praxis mit 58 abgeben"},
    )
    session.commit()
    goal = complete(session, member_id=member.id)["goal"]
    session.commit()
    assert (goal.name, goal.template) == ("Praxis mit 58 abgeben", "early_retirement")


def test_a_plain_string_answer_still_works_and_carries_no_template(session, member):
    """Every answer stored before 31 August 2026 is a plain string.

    Mapping one of those onto a template would be choosing a template on the member's behalf from a
    sentence they typed for a different question — R-151's rule about extraction never overwriting a
    member-entered value, one level up.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    record_answer(session, member_id=member.id, question_key="first_goal", value="Wohneigentum 2031")
    session.commit()
    goal = complete(session, member_id=member.id)["goal"]
    session.commit()
    assert goal.name == "Wohneigentum 2031"
    assert goal.template is None, "a free-text answer was assigned a template nobody chose"


def test_an_unknown_template_key_is_dropped_rather_than_mapped(session, member):
    """A key nothing resolves renders as no template while looking like one in the database.

    **Planted violation:** mapped it to `unspecified` instead of None. Failed, because `unspecified` is a
    template the member did not choose — the state the owner reported. Restored.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    record_answer(
        session,
        member_id=member.id,
        question_key="first_goal",
        value={"template": "frugal_maximalism", "name": "Etwas"},
    )
    session.commit()
    goal = complete(session, member_id=member.id)["goal"]
    session.commit()
    assert goal.name == "Etwas"
    assert goal.template is None


def test_a_template_with_no_name_is_no_goal(session, member):
    """R-102 writes the goal only "if stated", and a select opened and closed is not a stated goal."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="Anstellung")
    record_answer(
        session,
        member_id=member.id,
        question_key="first_goal",
        value={"template": "early_retirement", "name": "   "},
    )
    session.commit()
    result = complete(session, member_id=member.id)
    session.commit()
    assert "goal" not in result
    assert session.query(Goal).filter_by(member_id=member.id).count() == 0


def test_the_goal_question_offers_the_templates_in_its_own_payload(api_session, fast_kdf):
    """The client cannot forget a request it does not have to make.

    Also the ordering check on the wire: `GOAL_TEMPLATES` puts Frühpensionierung first at the owner's
    request, and a payload that reordered them would put a different goal at the top of the select.
    """
    from fastapi.testclient import TestClient

    from eigentlich.api import main
    from eigentlich.services.auth import login, register_with_credentials
    from conftest import session_overrides

    register_with_credentials(
        api_session,
        email="onb@example.ch",
        password="ein ziemlich langes passwort",
        age_at_registration=44,
        display_name="Onboarding Member",
    )
    api_session.commit()
    _, token = login(api_session, email="onb@example.ch", password="ein ziemlich langes passwort")
    api_session.commit()

    overrides = session_overrides(api_session)
    main.app.dependency_overrides.update(overrides)
    try:
        with TestClient(main.app) as client:
            payload = client.get(
                "/api/onboarding", headers={"Authorization": f"Bearer {token}"}
            ).json()
    finally:
        for key in overrides:
            main.app.dependency_overrides.pop(key, None)

    goal_question = next(q for q in payload["questions"] if q["key"] == "first_goal")
    assert goal_question["type"] == "goal_template"
    names = [record["de"]["name"] for record in goal_question["templates"]]
    assert names[0] == "Frühpensionierung", f"the templates arrive in another order: {names}"
    assert "Mutgeld" in names, "R-132: courage money is not offered here"
    # Every other question carries the key and null, so a client reads a field rather than matching a
    # `type` string it has to know about.
    for other in payload["questions"]:
        if other["key"] != "first_goal":
            assert other["templates"] is None


# ==========================================================================================================
# The household, the initiator, and the seventh field (update script item 3)
# ==========================================================================================================

from datetime import date as _date  # noqa: E402

from eigentlich.models import ADULT, DEPENDANT  # noqa: E402
from eigentlich.services import household as household_service  # noqa: E402
from eigentlich.services.onboarding import (  # noqa: E402
    HOUSEHOLD_QUESTION,
    InvalidComposition,
    composition_as_of,
)

COUPLE = {"adults": ["Ich", "Anna"], "dependants": ["Lena"]}


def _intake(session, member, *, composition=COUPLE, goal="Wohneigentum"):
    if composition is not None:
        record_answer(
            session, member_id=member.id, question_key=HOUSEHOLD_QUESTION, value=composition
        )
    record_answer(
        session, member_id=member.id, question_key="employment_position", value="angestellt"
    )
    record_answer(session, member_id=member.id, question_key="employment_magnitude", value=69550)
    if goal:
        record_answer(session, member_id=member.id, question_key="first_goal", value=goal)
    session.commit()


def test_completing_writes_the_household_the_member_stated(session, member):
    _intake(session, member)
    complete(session, member_id=member.id, today=_date(2027, 3, 14))
    session.commit()

    house = household_service.current(session, member_id=member.id)
    assert house is not None
    assert house.composition_as_of == _date(2027, 3, 14)
    assert [(p.label, p.kind) for p in house.members] == [
        ("Ich", ADULT), ("Anna", ADULT), ("Lena", DEPENDANT),
    ]


def test_the_member_answering_is_the_first_adult_and_the_server_attaches_the_account(session, member):
    """The client sends labels only. A composition carrying an account id would be one a client could
    point at somebody else's account."""
    _intake(session, member)
    complete(session, member_id=member.id)
    session.commit()

    house = household_service.current(session, member_id=member.id)
    assert house.members[0].member_id == member.id
    assert [p.member_id for p in house.members[1:]] == [None, None]


def test_the_first_goal_carries_its_owner(session, member):
    """A108's seventh field. A household that never populates it cannot be divided cleanly (A112)."""
    _intake(session, member)
    result = complete(session, member_id=member.id)
    session.commit()

    goal = result["goal"]
    assert [o.label for o in goal.owners] == ["Ich"]
    assert goal.owners[0].member_id == member.id


def test_a_skipped_composition_still_completes_and_writes_no_household(session, member):
    """"The onboarding is offered but never forced." A plan without a household is a real plan."""
    record_answer(session, member_id=member.id, question_key=HOUSEHOLD_QUESTION, value=None)
    _intake(session, member, composition=None)
    result = complete(session, member_id=member.id)
    session.commit()

    assert result["position"] is not None
    assert household_service.current(session, member_id=member.id) is None
    # No household, so no owner to give the goal. Reported by the Befund rather than guessed at.
    assert result["goal"].owners == []


def test_a_composition_that_is_not_one_is_refused_rather_than_half_read(session, member):
    _intake(session, member, composition={"adults": [], "dependants": ["Lena"]})
    with pytest.raises(InvalidComposition) as raised:
        complete(session, member_id=member.id)
    assert "at least one adult" in str(raised.value)
    session.rollback()

    _intake(session, member, composition="Anna und ich")
    with pytest.raises(InvalidComposition):
        complete(session, member_id=member.id)
    session.rollback()


# ---------------------------------------------------------------- one code path, two initiators


def test_a_curator_driven_intake_produces_the_same_rows_and_records_who_drove_it(session, member):
    """Item 3: "One code path, two initiators — record which one."

    The rows have to be identical or the two paths do not produce the same plan; only the attribution
    differs.
    """
    _intake(session, member)
    result = complete(
        session,
        member_id=member.id,
        initiated_by="curator",
        author_ref="curator:weber",
        today=_date(2027, 3, 14),
    )
    session.commit()

    house = household_service.current(session, member_id=member.id)
    assert house.stated_by == "curator"
    assert [(p.label, p.kind) for p in house.members] == [
        ("Ich", ADULT), ("Anna", ADULT), ("Lena", DEPENDANT),
    ]
    assert result["position"].label == "angestellt"
    assert result["decision"].author == "curator"
    assert result["decision"].author_ref == "curator:weber"


def test_the_two_initiators_write_the_same_plan(session, member):
    """Measured on the rows rather than asserted: the same answers, driven either way, agree on
    everything except who is recorded as having driven it."""
    from eigentlich.services import register_member

    other = register_member(session, age_at_registration=41, display_name="Zweite")
    session.commit()

    _intake(session, member)
    mine = complete(session, member_id=member.id, initiated_by="member", today=_date(2027, 3, 14))
    _intake(session, other)
    theirs = complete(session, member_id=other.id, initiated_by="curator", today=_date(2027, 3, 14))
    session.commit()

    def shape(result, member_id):
        house = household_service.current(session, member_id=member_id)
        return {
            "people": [(p.label, p.kind) for p in house.members],
            "as_of": house.composition_as_of,
            "position": (result["position"].label, result["position"].magnitude),
            "goal": result["goal"].name,
            "owners": [o.label for o in result["goal"].owners],
        }

    assert shape(mine, member.id) == shape(theirs, other.id)


def test_an_unknown_initiator_is_refused(session, member):
    _intake(session, member)
    with pytest.raises(OnboardingIncomplete):
        complete(session, member_id=member.id, initiated_by="the_app")
    session.rollback()


def test_nothing_in_the_module_branches_on_who_drove_it():
    """The moment it does, the two initiators stop producing the same plan."""
    import inspect

    from eigentlich.services import onboarding as module

    offending = [
        line.strip()
        for line in inspect.getsource(module).splitlines()
        if "initiated_by" in line
        and ("if " in line or "elif " in line)
        and "not in INITIATORS" not in line
    ]
    assert not offending, f"`initiated_by` is a record, not a condition. Branching on it: {offending}"


# ---------------------------------------------------------------- the as-of date


def test_the_composition_date_defaults_to_today_and_is_overridable(session):
    """A member answering in the app is describing today. A curator recording last week's session is not."""
    today = _date(2026, 9, 3)
    assert composition_as_of({"adults": ["Ich"]}, today=today) == today
    assert composition_as_of(
        {"adults": ["Ich"], "as_of": "2026-08-27"}, today=today
    ) == _date(2026, 8, 27)


# ==========================================================================================================
# Progress as consequence, not reward (update script item 3)
# ==========================================================================================================

from eigentlich.content import intake_findings  # noqa: E402
from eigentlich.services.onboarding import locked_findings  # noqa: E402


def test_everything_is_locked_before_anything_is_answered(session, member):
    report = locked_findings(session, member_id=member.id)
    assert report["unlocked"] == []
    assert [f["key"] for f in report["locked"]] == [f["key"] for f in intake_findings()]
    for finding in report["locked"]:
        assert finding["needs"], "a locked finding that needs nothing is locked for no reason"
        assert finding["sentence"].strip()


def test_a_finding_moves_to_unlocked_when_its_questions_are_answered(session, member):
    record_answer(
        session, member_id=member.id, question_key="household_composition", value={"adults": ["Ich"]}
    )
    record_answer(session, member_id=member.id, question_key="employment_position", value="angestellt")
    session.commit()

    report = locked_findings(session, member_id=member.id)
    assert {f["key"] for f in report["unlocked"]} == {"household_shape", "role_grid_has_a_cell"}
    still = {f["key"]: f["needs"] for f in report["locked"]}
    # A finding that needs two questions and has one reports only what is still missing.
    assert still["income_in_francs"] == ["employment_magnitude"]
    assert still["a_goal_with_an_owner"] == ["first_goal"]


def test_a_skipped_question_does_not_unlock_what_it_would_have(session, member):
    """A skip is a recorded answer so the intake moves on — it is not a stated fact."""
    record_answer(session, member_id=member.id, question_key="household_composition", value=None)
    session.commit()

    report = locked_findings(session, member_id=member.id)
    assert "household_shape" in {f["key"] for f in report["locked"]}


def test_there_is_no_count_anywhere_in_what_it_returns(session, member):
    """R-113, C-07, and item 3's own words: no percentages, no badges, no streaks.

    Asserted on the SHAPE rather than on a vocabulary: any bare number at any level would be a meter
    whatever it were called. The lists are the answer.
    """
    record_answer(session, member_id=member.id, question_key="employment_position", value="A")
    session.commit()
    report = locked_findings(session, member_id=member.id)

    def numbers(node, path="report"):
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                found += numbers(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found += numbers(value, f"{path}[{index}]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            found.append(f"{path}={node}")
        return found

    assert numbers(report) == [], "a bare number reached the progress payload"


def test_the_module_computes_no_ratio_or_percentage():
    """The guard on the guard above: a payload with no number today is one component away from one.

    Asserted over the function's AST rather than by grepping its text. The first version grepped for
    "percent" and failed on its own docstring — the same shape of check that passes or fails for reasons
    unrelated to the property it names, and the second time this session that a text scan did it.
    """
    import ast
    import inspect
    import textwrap

    from eigentlich.services import onboarding as module

    tree = ast.parse(textwrap.dedent(inspect.getsource(module.locked_findings)))
    function = tree.body[0]
    # Drop the docstring: it is prose about the rule, not an implementation of one.
    has_docstring = (
        function.body
        and isinstance(function.body[0], ast.Expr)
        and isinstance(function.body[0].value, ast.Constant)
    )
    body = function.body[1:] if has_docstring else function.body

    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"len", "round", "sum"}, (
                    f"`locked_findings` calls {node.func.id}(); progress here is a consequence, "
                    f"not a measure"
                )
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Div, ast.Mult, ast.FloorDiv)
            ):
                raise AssertionError("`locked_findings` computes a ratio")
            if isinstance(node, ast.Name):
                assert not any(
                    word in node.id.lower() for word in ("percent", "ratio", "total", "score")
                ), f"`locked_findings` binds {node.id!r}"


def test_both_halves_are_reported_not_only_what_is_missing(session, member):
    """A member who has answered something has unlocked something. Reporting only the gap is the backlog."""
    record_answer(session, member_id=member.id, question_key="employment_position", value="A")
    session.commit()
    report = locked_findings(session, member_id=member.id)
    assert set(report) == {"locked", "unlocked"}
    assert report["unlocked"], "nothing is reported as gained, so this reads as a list of failures"


# ---------------------------------------------------------------- the two lists cannot drift


def test_every_question_a_finding_names_exists_in_the_question_set():
    """The join, held from the side that would break first.

    A finding naming a question that was renamed would sit locked forever with no way to unlock it, and
    nothing else in the suite would notice.
    """
    from eigentlich.content import onboarding_questions

    keys = {q["key"] for q in onboarding_questions()}
    for finding in intake_findings():
        unknown = [need for need in finding["needs"] if need not in keys]
        assert not unknown, f"{finding['key']} needs question(s) that do not exist: {unknown}"


def test_every_finding_has_a_sentence_in_both_languages():
    from eigentlich.content import LANGUAGES, intake_finding_sentence

    for finding in intake_findings():
        for language in LANGUAGES:
            assert intake_finding_sentence(finding["key"], language).strip()
