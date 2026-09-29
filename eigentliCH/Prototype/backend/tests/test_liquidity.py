"""The blocking liquidity finding. Item 4.

"The enforcement is what makes the goal system honest rather than decorative." So the tests that matter are
the ones that would pass if it were decorative: a goal that is short and still says nothing, a menu offered
instead of an option, a lever chosen by cost rather than by order.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.models import Goal, Position
from eigentlich.services import liquidity
from eigentlich.services.goals import goal_payload
from eigentlich.services.liquidity import (
    CLOSES,
    COULD_NOT_BE_DETERMINED,
    DOES_NOT_CLOSE,
    SHORT_ON_DATE,
    assess,
    finding,
    levers,
    prepare,
)
from eigentlich.services.plan import mutate_plan

TODAY = date(2027, 3, 14)
DUE = date(2029, 3, 31)


def _goal(session, member, *, funding=(), target_date=DUE, amount=400_000.0):
    with mutate_plan(session, member_id=member.id, question="Record?", choice="Yes") as decision:
        goal = Goal(
            member_id=member.id, name="Wohneigentum", target_amount=amount, target_date=target_date
        )
        for label, band, magnitude in funding:
            position = Position(
                member_id=member.id,
                role="growth",
                capital_type="financial",
                label=label,
                magnitude=magnitude,
                magnitude_unit="chf" if magnitude is not None else None,
                stock_kind="asset" if magnitude is not None else None,
                liquidity=band,
            )
            session.add(position)
            decision.linked_positions.append(position)
            goal.funded_by.append(position)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()
    return goal


ILLIQUID = [("Beteiligung", "illiquid", 250_000.0)]


# ============================================================ the state


def test_a_dated_goal_funded_only_by_illiquid_holdings_is_short_on_its_date(session, member):
    goal = _goal(session, member, funding=ILLIQUID)
    shortfall = assess(goal, today=TODAY)

    assert shortfall is not None
    assert shortfall.as_dict()["state"] == SHORT_ON_DATE
    assert shortfall.gap_chf == 250_000.0
    assert shortfall.due_date == DUE
    assert shortfall.reason == "funding_is_illiquid"


def test_the_member_sees_three_things_and_no_severity(session, member):
    """Item 4: the gap in francs, the date it falls due, and the reason in one line. "No warning colour
    doing the work of a sentence."
    """
    goal = _goal(session, member, funding=ILLIQUID)
    payload = assess(goal, today=TODAY).as_dict()

    assert set(payload) == {
        "state",
        "gap_chf",
        "due_date",
        "reason",
        "position_ids",
        "blocks_certification",
    }
    for forbidden in ("severity", "level", "colour", "color", "status", "warning", "score"):
        assert forbidden not in payload


def test_the_goal_stays_in_the_list_and_is_not_marked_failed(session, member):
    """"The goal is not hidden, not greyed out, not marked failed. It carries a state and stays in the
    list with everything else."""
    goal = _goal(session, member, funding=ILLIQUID)
    payload = goal_payload(session, goal, today=TODAY)

    assert payload["name"] == "Wohneigentum"
    assert payload["target_amount"] == 400_000.0
    assert payload["short_on_date"]["state"] == SHORT_ON_DATE
    # Nothing anywhere in the payload says the goal failed.
    blob = str(payload)
    for forbidden in ("failed", "gescheitert", "hidden", "disabled"):
        assert forbidden not in blob


def test_it_blocks_certification(session, member):
    """"The goal cannot be marked on track and the plan cannot be certified as funding it."""
    goal = _goal(session, member, funding=ILLIQUID)
    assert assess(goal, today=TODAY).blocks_certification is True


def test_the_key_is_present_even_when_the_goal_is_not_short(session, member):
    """A client reads one key rather than inferring from an absence."""
    goal = _goal(session, member, funding=[("Konto", "immediate", 250_000.0)])
    payload = goal_payload(session, goal, today=TODAY)
    assert "short_on_date" in payload
    assert payload["short_on_date"] is None


# ============================================================ when the question cannot be asked


def test_a_goal_with_no_date_is_not_short(session, member):
    goal = _goal(session, member, funding=ILLIQUID, target_date=None)
    assert assess(goal, today=TODAY) is None


def test_a_goal_whose_funding_liquidity_is_unstated_is_unmeasured_not_short(session, member):
    """"A goal whose funding is unmarked is not short — it is unmeasured." `goals.observations` already
    reports the unstated liquidity as its own fact."""
    goal = _goal(session, member, funding=[("Beteiligung", None, 250_000.0)])
    assert assess(goal, today=TODAY) is None


def test_partly_liquid_funding_is_not_yet_decidable_and_says_nothing(session, member):
    """The general comparison needs `Goal.liquidity_need` to have published answer options, and it does
    not. Approximating it would be inventing the mapping."""
    goal = _goal(
        session,
        member,
        funding=[("Beteiligung", "illiquid", 250_000.0), ("Konto", "immediate", 50_000.0)],
    )
    assert assess(goal, today=TODAY) is None


def test_the_gap_is_absent_rather_than_zero_when_no_balance_is_stated(session, member):
    """"How much" is a different question from "whether"."""
    goal = _goal(session, member, funding=[("Beteiligung", "illiquid", None)])
    shortfall = assess(goal, today=TODAY)
    assert shortfall is not None
    assert shortfall.gap_chf is None


# ============================================================ one option, chosen by order


def test_exactly_one_option_is_prepared_and_never_a_menu(session, member):
    """Principle 4. "A list of alternatives is not a prepared decision"."""
    goal = _goal(session, member, funding=ILLIQUID)
    prepared = prepare(goal, assess(goal, today=TODAY), today=TODAY).as_dict()

    assert isinstance(prepared["lever"], str)
    assert prepared["requires_curator"] is False
    # `considered` is the working, not a menu: it carries verdicts, never labels to choose between.
    assert all(set(one) == {"lever", "verdict"} for one in prepared["considered"])


def test_the_levers_are_tried_in_the_published_order(session, member):
    goal = _goal(session, member, funding=ILLIQUID)
    prepared = prepare(goal, assess(goal, today=TODAY), today=TODAY)

    tried = [one["lever"] for one in prepared.considered]
    published = [one["key"] for one in levers()]
    assert tried == published[: len(tried)], "the precedence was not followed"
    # It stops at the first that closes rather than evaluating them all.
    assert prepared.lever == tried[-1]
    assert len(tried) < len(published)


def test_the_order_is_config_and_runs_from_cheapest_to_dearest():
    """Item 4: "Keep the order in config so it can be changed without a rewrite." The order itself is the
    editorial judgement — from what costs nothing the member would notice to what costs part of the goal."""
    published = levers()
    assert [one["key"] for one in published] == [
        "move_funding_to_a_liquid_form",
        "move_the_goal_date",
        "add_a_monthly_contribution",
        "reduce_the_goal_size",
    ]
    assert [one["order"] for one in published] == [1, 2, 3, 4]
    assert all(one["costs"] for one in published)


def test_nothing_minimises_across_francs_months_and_goal_size():
    """"They share no unit, and comparing them would need a utility function over the household's
    preferences that the app does not have."

    Asserted over the module's AST rather than its text — a grep would match the sentence above.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(liquidity))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"min", "max"}, (
                f"{node.func.id}() over the levers is a computed minimum, not a precedence"
            )
        if isinstance(node, ast.Name):
            assert "cheapest" not in node.id and "best" not in node.id


# ============================================================ the third answer, and the curator


def test_a_lever_that_cannot_be_decided_routes_to_a_curator_rather_than_being_skipped(
    session, member, monkeypatch
):
    """Skipping would let a later, dearer lever be prepared while an earlier one might have closed the
    gap — and "the first that closes" would be a claim the code does not keep."""
    goal = _goal(session, member, funding=ILLIQUID)

    def undecidable(lever, *args, **kwargs):
        return COULD_NOT_BE_DETERMINED if lever == "move_the_goal_date" else DOES_NOT_CLOSE

    monkeypatch.setattr(liquidity, "_evaluate", undecidable)
    prepared = prepare(goal, assess(goal, today=TODAY), today=TODAY)

    assert prepared.lever is None
    assert prepared.requires_curator is True
    assert prepared.reason == "a_lever_could_not_be_determined"
    # It stopped THERE rather than carrying on to the levers that would have closed it.
    assert [one["lever"] for one in prepared.considered] == [
        "move_funding_to_a_liquid_form",
        "move_the_goal_date",
    ]


def test_when_no_lever_closes_the_gap_no_option_is_prepared(session, member, monkeypatch):
    """Item 4: "If none closes the gap alone, no option is prepared and it routes to the curator."""
    goal = _goal(session, member, funding=ILLIQUID)
    monkeypatch.setattr(liquidity, "_evaluate", lambda *a, **k: DOES_NOT_CLOSE)

    prepared = prepare(goal, assess(goal, today=TODAY), today=TODAY)
    assert prepared.lever is None
    assert prepared.requires_curator is True
    assert prepared.reason == "no_single_lever_closes_the_gap"
    assert len(prepared.considered) == len(levers())


def test_there_are_three_verdicts_and_not_two():
    """The Household Optimiser's third state, which is what makes an undecidable lever different from a
    lever that fails."""
    assert len({CLOSES, DOES_NOT_CLOSE, COULD_NOT_BE_DETERMINED}) == 3


def test_a_goal_whose_date_has_passed_cannot_be_closed_by_contributing(session, member):
    """There are no months left to contribute in."""
    goal = _goal(session, member, funding=ILLIQUID, target_date=date(2026, 1, 31))
    prepared = prepare(goal, assess(goal, today=TODAY), today=TODAY)
    assert prepared.lever == "reduce_the_goal_size"


# ============================================================ the whole finding


def test_the_finding_carries_the_state_and_the_prepared_option_together(session, member):
    goal = _goal(session, member, funding=ILLIQUID)
    whole = finding(goal, today=TODAY)
    assert whole["state"] == SHORT_ON_DATE
    assert whole["prepared"]["lever"] == "add_a_monthly_contribution"


def test_every_lever_has_a_sentence_in_both_languages():
    from eigentlich.content import LANGUAGES

    for lever in levers():
        for language in LANGUAGES:
            assert liquidity.lever_sentence(lever["key"], language).strip()
