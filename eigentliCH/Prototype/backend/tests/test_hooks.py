"""Content hooks, and the claim that one implementation serves both directions. Item 5.

    "This is the same mechanism as the first-session finding, running in the other direction ... **One
     implementation serves both.**"

That is a claim about the code, so it is tested as one: the push and the pull are asserted to agree, and
the module that answers "has the member given this" is asserted to be the same module in both.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.models import ADULT, Goal, Position
from eigentlich.services import hooks, inputs
from eigentlich.services.hooks import (
    DECLARATION,
    MAX_DECLARED_INPUTS,
    TooManyInputs,
    UndeclarableInput,
    declared,
    every_declaration,
    hook,
    learning_items,
)
from eigentlich.services.household import Person, state as state_household
from eigentlich.services.plan import mutate_plan

MARCH = date(2027, 3, 14)


def _house(session, member):
    state_household(
        session,
        member_id=member.id,
        people=[Person(label="Ich", kind=ADULT, member_id=member.id)],
        as_of=MARCH,
    )
    session.commit()


def _stock(session, member, magnitude=103_500.0):
    with mutate_plan(session, member_id=member.id, question="q", choice="c") as decision:
        position = Position(
            member_id=member.id, role="stabilisation", capital_type="financial",
            label="Konto", magnitude=magnitude, magnitude_unit="chf", stock_kind="asset",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()


def _income(session, member):
    with mutate_plan(session, member_id=member.id, question="q", choice="c") as decision:
        position = Position(
            member_id=member.id, role="income", capital_type="human",
            label="angestellt", magnitude=69_550.0, magnitude_unit="chf_per_year",
        )
        session.add(position)
        decision.linked_positions.append(position)
    session.commit()


# ============================================================ the declaration


def test_every_declaration_in_the_content_is_one_the_build_can_answer():
    """Walks the whole file, not the units a fixture happens to reach.

    An item declaring something nothing can answer would offer a tap that never completes, and the member
    would be asked a question the plan has nowhere to put.
    """
    for key, wanted in every_declaration().items():
        assert len(wanted) <= MAX_DECLARED_INPUTS, f"{key} declares {len(wanted)}"
        for name in wanted:
            assert name in inputs.INPUT_ORDER, f"{key} declares {name!r}"


def test_more_than_three_inputs_is_an_intake_wearing_a_tap():
    with pytest.raises(TooManyInputs):
        declared({"key": "x", DECLARATION: list(inputs.INPUT_ORDER) + ["household_composition"]})


def test_an_input_nothing_can_answer_is_refused():
    with pytest.raises(UndeclarableInput) as raised:
        declared({"key": "x", DECLARATION: ["favourite_colour"]})
    assert "favourite_colour" in str(raised.value)


def test_a_declaration_is_inputs_and_never_a_sentence():
    """Item 5: "What a content item declares is which inputs are needed, **not a prepared sentence** — the
    finding itself is composed on the go."
    """
    for key, wanted in every_declaration().items():
        for name in wanted:
            assert " " not in name, f"{key} declares {name!r}, which is prose rather than an input"


# ============================================================ the tap, and when there is none


def test_an_item_that_declares_nothing_gets_no_tap(session, member):
    """"That is an editorial constraint, not an engineering one." Exercised on a real unit rather than a
    constructed one, so the content really does carry the case."""
    resolved = {one["key"]: one["hook"] for one in learning_items(session, member_id=member.id)}
    assert "wenn_sie_es_anbieten" in resolved
    assert resolved["wenn_sie_es_anbieten"]["tappable"] is False
    assert resolved["wenn_sie_es_anbieten"]["declares"] == []


def test_an_item_with_nothing_stated_asks_for_everything_it_declares(session, member):
    resolved = hook(
        session, member_id=member.id,
        item={"key": "x", DECLARATION: ["household_composition", "financial_stock"]},
    )
    assert resolved["tappable"] is True
    assert resolved["asks"] == ["household_composition", "financial_stock"]
    assert resolved["ready"] is False


def test_inputs_already_in_the_vault_are_skipped(session, member):
    """Item 5: "Inputs already in the Vault are skipped."""
    _house(session, member)
    resolved = hook(
        session, member_id=member.id,
        item={"key": "x", DECLARATION: ["household_composition", "financial_stock"]},
    )
    assert resolved["asks"] == ["financial_stock"]


def test_a_populated_vault_goes_straight_to_the_finding(session, member):
    """"A member with a populated Vault goes straight to the finding."""
    _house(session, member)
    _stock(session, member)
    resolved = hook(
        session, member_id=member.id,
        item={"key": "x", DECLARATION: ["household_composition", "financial_stock"]},
    )
    assert resolved["asks"] == []
    assert resolved["ready"] is True


def test_the_questions_come_back_in_a_stable_order(session, member):
    """Asked one at a time, so two consecutive reads must not reorder them — a member who comes back to a
    different question has been asked at random."""
    item = {"key": "x", DECLARATION: ["first_goal", "household_composition", "income_position"]}
    first = hook(session, member_id=member.id, item=item)["asks"]
    second = hook(session, member_id=member.id, item=item)["asks"]
    assert first == second
    # And household composition leads, as it does everywhere.
    assert first[0] == "household_composition"


# ============================================================ one implementation, two directions


def test_the_push_and_the_pull_ask_the_same_module(session, member):
    """The claim item 5 makes about the code, tested as one.

    `know.missing_personal_input` (the app having something to say) and `hooks.hook` (the member pulling)
    must agree about what the member has given — two implementations would drift, and the member would be
    asked for something they had already provided.
    """
    import inspect

    from eigentlich.services import know

    assert "stated_inputs" in inspect.getsource(know.missing_personal_input)
    assert "missing_inputs" in inspect.getsource(hooks.hook)


def test_the_two_directions_agree_as_the_vault_fills(session, member):
    """Behaviourally, not by reading: at each step, what the push names is not something the pull thinks
    is already there."""
    from eigentlich.services.know import missing_personal_input

    wanted = ["household_composition", "income_position", "first_goal"]
    for fill in (None, _house, _income):
        if fill:
            fill(session, member)
        pushed = missing_personal_input(session, member_id=member.id, language="de")
        pulled = hook(session, member_id=member.id, item={"key": "x", DECLARATION: wanted})["asks"]
        if pushed is None:
            continue
        assert pushed["key"] in pulled, (
            f"the push names {pushed['key']} as missing and the pull does not ask for it"
        )


def test_an_input_is_satisfied_however_it_arrived(session, member):
    """`financial_stock` is not a question, it is a thing the plan holds. A balance recorded from the role
    grid satisfies it as surely as one from the intake."""
    assert "financial_stock" not in inputs.stated(session, member_id=member.id)
    _stock(session, member)
    assert "financial_stock" in inputs.stated(session, member_id=member.id)


def test_the_input_set_and_its_predicates_cannot_disagree():
    """An import-time contract: an input with no predicate is one nothing can satisfy."""
    assert set(inputs.PREDICATES) == set(inputs.INPUT_ORDER)


def test_a_salary_does_not_count_as_a_balance(session, member):
    """A105 and A122's defect, one layer out: `chf_per_year` is a flow and is not a stock."""
    _income(session, member)
    have = inputs.stated(session, member_id=member.id)
    assert "income_position" in have
    assert "financial_stock" not in have, "a salary was counted as a balance"
