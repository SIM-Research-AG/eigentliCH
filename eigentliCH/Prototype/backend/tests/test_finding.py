"""The first-session finding. Principle 2, and the three rules the build enforces.

Principle 2 rules out "onboarding that reflects back what was typed in", so the tests that matter here are
the ones that would pass if the finding were a restatement — and they are written to fail in that case.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.models import ADULT, Goal, Position
from eigentlich.services import finding as finding_service
from eigentlich.services import household as household_service
from eigentlich.services.befund import render_befund
from eigentlich.services.finding import Finding, candidates, compose, verify
from eigentlich.services.household import Person
from eigentlich.services.plan import mutate_plan

TODAY = date(2027, 3, 20)
MARCH = date(2027, 3, 14)


def _house(session, member):
    household_service.state(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=MARCH,
    )
    session.commit()


def _stocks(session, member, *, cash=103_500.0, securities=101_500.0, debt=None):
    with mutate_plan(
        session, member_id=member.id, question="Record the balances?", choice="Yes"
    ) as decision:
        for label, role, amount in (
            ("Bargeld und Kontoguthaben", "stabilisation", cash),
            ("Wertschriften", "growth", securities),
        ):
            if amount is None:
                continue
            position = Position(
                member_id=member.id,
                role=role,
                capital_type="financial",
                label=label,
                magnitude=amount,
                magnitude_unit="chf",
                stock_kind="asset",
                liquidity="immediate",
            )
            session.add(position)
            decision.linked_positions.append(position)
        if debt is not None:
            owed = Position(
                member_id=member.id,
                role="protection",
                capital_type="financial",
                label="Hypothek",
                magnitude=debt,
                magnitude_unit="chf",
                stock_kind="liability",
            )
            session.add(owed)
            decision.linked_positions.append(owed)
    session.commit()


def _salary_only(session, member):
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


# ============================================================ rule 2: not what was typed in


def test_the_finding_states_a_figure_the_member_never_typed(session, member):
    """Principle 2's exclusion, made checkable.

    The member entered two balances and never their sum. A finding that quoted one of the two back would
    be a report; the sum is a statement they could not have made themselves.
    """
    _house(session, member)
    _stocks(session, member)

    found = compose(session, member_id=member.id, today=TODAY)
    assert found is not None
    assert found.fact_key == "stock_financial"
    assert "205'000" in found.sentence or "205000" in found.sentence
    # Neither of the two figures the member actually entered is what is being stated.
    assert "103'500" not in found.sentence
    assert "101'500" not in found.sentence


def test_a_member_stated_fact_can_never_be_the_finding(session, member):
    """The rule is one field, and it is asserted over the pool rather than over one example."""
    _house(session, member)
    _stocks(session, member)
    with mutate_plan(
        session, member_id=member.id, question="Record a goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=1_500_000.0)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    report = render_befund(session, member_id=member.id, today=TODAY)
    # The Befund does hold a member-stated figure for the goal, so this is not vacuous.
    assert any(
        fact["source"] == "member_stated"
        for section in report["sections"]
        for fact in section["facts"]
    )
    assert all(fact["source"] == "computed_from_plan" for fact in candidates(report))


def test_a_content_fact_can_never_be_the_finding(session, member):
    """"A general fact about Swiss mechanics does not satisfy Principle 2 however interesting it is."""
    _house(session, member)
    _stocks(session, member)
    report = render_befund(session, member_id=member.id, today=TODAY)
    assert any(
        fact["source"] == "content" for section in report["sections"] for fact in section["facts"]
    ), "no content fact in the report, so this test proves nothing"
    assert all(fact["source"] != "content" for fact in candidates(report))


# ============================================================ rule 1: read from the Befund


def test_a_finding_with_a_figure_is_offered_before_one_without(session, member):
    """Not a score and not a ranking of the member — a rule over the payload's own shape."""
    _house(session, member)
    _stocks(session, member)
    # A goal gives the report a computed fact with no figure in it — `goal_unfunded` carries a goal id and
    # no amount — so the ordering has two kinds to order and this is not vacuous.
    with mutate_plan(
        session, member_id=member.id, question="Record a goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum")
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    report = render_befund(session, member_id=member.id, today=TODAY)
    pool = candidates(report)

    assert finding_service._has_figure(pool[0])
    # And the structural ones are still in the pool, behind it, rather than filtered away.
    assert any(not finding_service._has_figure(fact) for fact in pool)


def test_the_finding_names_the_fact_it_rests_on(session, member):
    _house(session, member)
    _stocks(session, member)
    found = compose(session, member_id=member.id, today=TODAY)
    assert found.fact_key and found.section
    payload = found.as_dict()
    assert set(payload) == {"sentence", "fact_key", "section", "origin", "computed_sentence"}


# ============================================================ returning nothing is allowed


def test_no_finding_when_the_member_has_said_too_little(session, member):
    """The light-intake floor, from the other side: a missing finding is the floor not being met."""
    assert compose(session, member_id=member.id, today=TODAY) is None


def test_a_salary_alone_grounds_no_finding(session, member):
    """A flow is not a balance, so nothing is summed and nothing is computed about it.

    The member has said something real and it is still not enough to be surprising about — which is the
    honest state, not a failure to paper over.
    """
    _house(session, member)
    _salary_only(session, member)
    found = compose(session, member_id=member.id, today=TODAY)
    assert found is None or found.fact_key != "stock_financial"


def test_the_net_figure_appears_only_when_both_sides_are_stated(session, member):
    """A net figure over an unstated liability is a claim that there is none."""
    _house(session, member)
    _stocks(session, member)
    report = render_befund(session, member_id=member.id, today=TODAY)
    keys = {fact["key"] for section in report["sections"] for fact in section["facts"]}
    assert "stock_net" not in keys

    _stocks(session, member, cash=None, securities=None, debt=400_000.0)
    report = render_befund(session, member_id=member.id, today=TODAY)
    keys = {fact["key"] for section in report["sections"] for fact in section["facts"]}
    assert "stock_net" in keys


# ============================================================ rule 3: the checks run after


def test_a_sentence_carrying_an_invented_figure_is_refused(session, member):
    """"Instructing a model not to invent a number does not hold; checking the number against the source
    does." The check runs over a finished sentence, not as an instruction before one."""
    _house(session, member)
    _stocks(session, member)
    report = render_befund(session, member_id=member.id, today=TODAY)
    truthful = [fact for fact in candidates(report) if fact["key"] == "stock_financial"][0]

    assert verify("Ihr erfasstes Finanzvermögen beträgt 205'000.", report=report, against=truthful)
    assert not verify(
        "Ihr erfasstes Finanzvermögen beträgt 999'999.", report=report, against=truthful
    )
def test_a_figure_verifies_in_either_spelling(session, member):
    """`_amount` renders 205000.0 as `205'000`; a model writing `205000` quotes the same figure."""
    _house(session, member)
    _stocks(session, member)
    report = render_befund(session, member_id=member.id, today=TODAY)
    truthful = [fact for fact in candidates(report) if fact["key"] == "stock_financial"][0]

    assert verify("Das Finanzvermögen beträgt 205000.", report=report, against=truthful)


# ============================================================ the model, and what it is allowed to do


def test_the_default_path_asks_no_model(session, member, monkeypatch):
    """The Befund's own sentence is already deterministic, sourced and C-01-checked."""
    from eigentlich import llm

    def refuse(*args, **kwargs):
        raise AssertionError("the default path called the model")

    monkeypatch.setattr(llm, "chat", refuse)
    _house(session, member)
    _stocks(session, member)

    found = compose(session, member_id=member.id, today=TODAY)
    assert found.origin == "computed"
    assert found.computed_sentence is None


def test_an_unavailable_model_falls_back_to_the_computed_sentence(session, member, monkeypatch):
    """R-302's shape. The finding was true before the model saw it."""
    from eigentlich import llm

    def unavailable(*args, **kwargs):
        raise llm.LocalModelUnavailable("not running")

    monkeypatch.setattr(llm, "chat", unavailable)
    _house(session, member)
    _stocks(session, member)

    found = compose(session, member_id=member.id, today=TODAY, reword=True)
    assert found.origin == "computed"
    assert "205'000" in found.sentence


def test_a_reworded_sentence_is_kept_only_if_it_survives_both_checks(session, member, monkeypatch):
    from eigentlich import llm

    _house(session, member)
    _stocks(session, member)

    monkeypatch.setattr(
        llm, "chat", lambda *a, **k: llm.Reply(text="Zusammen sind es 205'000 Franken.", model="m")
    )
    kept = compose(session, member_id=member.id, today=TODAY, reword=True)
    assert kept.origin == "model"
    assert kept.sentence == "Zusammen sind es 205'000 Franken."
    # The deterministic sentence travels with it — code's version is still in the payload.
    assert "205'000" in kept.computed_sentence

    monkeypatch.setattr(
        llm, "chat", lambda *a, **k: llm.Reply(text="Zusammen sind es 999'999 Franken.", model="m")
    )
    refused = compose(session, member_id=member.id, today=TODAY, reword=True)
    assert refused.origin == "computed"
    assert refused.computed_sentence is None


def test_the_model_is_shown_one_sentence_and_never_the_members_other_facts(session, member):
    """Non-negotiable 10: model chooses, code computes. Here the model does not even choose.

    Asserted on the call rather than on the prompt's wording: whatever it is handed is the sentence code
    already composed, not the report.
    """
    import inspect

    source = inspect.getsource(finding_service.compose)
    assert 'llm.chat(\n            chosen["sentence"],' in source, (
        "the model is handed something other than the one chosen sentence"
    )
    assert "report" not in source.split("llm.chat(")[1].split(")")[0]


def test_there_is_no_curated_library_or_household_type_selector():
    """Item 3 forbids three things by name: a curated library, an eligibility index, a per-household-type
    selector.

    Asserted as a PROPERTY over the module's AST, not by grepping its text — the first version scanned the
    source for "eligibility" and matched the word in the docstring that quotes the prohibition. That is the
    third text scan today to fail on its own prose (the router's purity guard and the progress guard were
    the others), and the lesson each time was the same: assert the property, not the wording.

    The property: the module declares no collection of prepared sentences, and the only closed sets it
    holds are exclusions — sets of fact KEYS, which is the opposite of a library. Adding a fact to the
    Befund adds it to the pool; nothing here has to be extended for a member to get a finding.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(finding_service))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id.startswith("__"):
                continue
            # A library would be a list or dict of sentences. Every module-level collection here is a
            # frozenset of keys or a tuple of source names. `__all__` is a list and is a dunder, not a
            # collection of content.
            if isinstance(node.value, (ast.List, ast.Dict)):
                raise AssertionError(
                    f"{target.id} is a list/dict at module level; a prepared-finding library is what "
                    f"item 3 forbids"
                )

    # The exclusions are exclusions: short, and every entry a bare key.
    assert isinstance(finding_service.NOT_A_FINDING, frozenset)
    assert len(finding_service.NOT_A_FINDING) < 12
    assert all(isinstance(key, str) and " " not in key for key in finding_service.NOT_A_FINDING), (
        "an entry with a space in it is a sentence, not a key — that would be a library"
    )
    assert isinstance(finding_service.NOT_A_FINDING_SECTION, frozenset)

    # And no branch anywhere on a household's shape.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert "household_type" not in node.id, "a per-household-type selector"
