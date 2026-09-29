"""The member's own record as grounding: what it says, and what it refuses to say.

`services/member_ground.py` is the module that closed the gap measured on 20 September 2026 — thirty-six
of fifty members asked something about themselves and the answer path could not see a single one of their
296 positions or 128 goals. The route gating is tested next door in `test_compose.py`, because it is a
property of `know.ask` rather than of this module. What is tested here is the rendering, and every case
below is one a real member in the development database actually has.

**The rendering is not cosmetic and that is the point of testing it at all.** A language model reads these
strings and nothing else about the member. A heading that does not say whether a number is a balance or a
salary is a heading that invites the model to add them together, which is exactly what happened.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.models import FLOW_UNIT, STOCK_UNIT, Goal, Position
from eigentlich.services import member_ground
from eigentlich.services.plan import mutate_plan


def _add(session, member, *objects, goals=()):
    """Positions and goals with the Decision C-09 requires. Never a bare `session.add`."""
    with mutate_plan(session, member_id=member.id, question="Erfassen?", choice="Ja") as decision:
        for obj in objects:
            session.add(obj)
            decision.linked_positions.append(obj)
        for goal in goals:
            session.add(goal)
            decision.linked_goals.append(goal)
    session.commit()


def _stock(member, label, amount):
    return Position(member_id=member.id, role="growth", capital_type="financial", label=label,
                    magnitude=amount, magnitude_unit=STOCK_UNIT, stock_kind="asset", active=True)


def _flow(member, label, amount):
    return Position(member_id=member.id, role="income", capital_type="human", label=label,
                    magnitude=amount, magnitude_unit=FLOW_UNIT, active=True)


def _section(session, member, key):
    for section in member_ground.sections(session, member_id=member.id):
        if section.key == key:
            return section
    return None


# ---------------------------------------------------------------- stocks are not flows


def test_a_balance_and_a_salary_are_never_under_the_same_heading(session, member):
    """The measured defect, pinned.

    The first composed answer built from this section reported a member's wealth as CHF 840'000 by summing
    a stock list that included a CHF 280'000 salary line. Both figures were real and the sentence was
    false. A model reading a flat list of francs has no way to know which rows may be added.

    Planted violation: rendering one list with the unit in a parenthetical — which is what it did — and
    the model summed them anyway. The headings are the fix, not the parenthetical.
    """
    _add(session, member, _stock(member, "Pensionskasse", 500000), _flow(member, "Anstellung", 280000))

    positions = _section(session, member, "positions")
    text = positions.text
    assert "Vermögen (Bestände" in text
    assert "Einkommen und Ausgaben" in text
    assert "NICHT zum Vermögen addieren" in text

    before, after = text.split("Einkommen und Ausgaben", 1)
    assert "Pensionskasse" in before, "the balance belongs above the flow heading"
    assert "Anstellung" in after, "the salary belongs below it"
    assert "Anstellung" not in before


def test_a_position_whose_role_is_income_is_a_flow_whatever_its_unit_says(session, member):
    """Belt and braces, because the two markers disagree in the real data.

    Some loaded positions carry `FLOW_UNIT` and some carry only `role="income"`. Reading either one alone
    puts a salary in the balance list for half the members, which is the defect with a smaller blast
    radius rather than a different defect.
    """
    # `ck_positions_stock_kind_iff_stock`: `stock_kind` is non-null exactly when the unit is a stock
    # unit, so giving this row the stock unit obliges it to carry a stock kind too.
    position = _flow(member, "Anstellung", 90000)
    position.magnitude_unit = STOCK_UNIT
    position.stock_kind = "asset"
    position.capital_type = "financial"
    _add(session, member, position)

    text = _section(session, member, "positions").text
    assert "Einkommen und Ausgaben" in text
    assert "Vermögen (Bestände" not in text


def test_a_position_recorded_without_an_amount_is_said_rather_than_dropped(session, member):
    """A member reading their own record back should find what they recorded, including the gaps."""
    # Two constraints at once: a unit without a magnitude is refused, and a `stock_kind` without a stock
    # unit is refused. A position with no amount therefore carries neither.
    position = _stock(member, "Beteiligung an der eigenen Firma", None)
    position.magnitude = None
    position.magnitude_unit = None
    position.stock_kind = None
    _add(session, member, position)

    text = _section(session, member, "positions").text
    assert "Ohne Betrag erfasst" in text
    assert "Beteiligung an der eigenen Firma" in text


# ---------------------------------------------------------------- goals


def test_goals_with_and_without_a_date_sort_together_without_raising(session, member):
    """`target_date` is a `date` and `created_at` is a `datetime`; Python refuses to order the two.

    Found by building the sections for all 83 members of the development database, where it raised
    `TypeError` on the fourth — a crash `know.ask` does not catch, so the member's question would have
    returned a 500. Every unit test had given its goals the same shape.
    """
    _add(session, member, goals=[
        Goal(member_id=member.id, name="Eigenheim", target_date=date(2033, 12, 31),
             target_amount=900000),
        Goal(member_id=member.id, name="Reserve"),
    ])

    goals = _section(session, member, "goals")
    assert len(goals.lines) == 2
    assert goals.lines[0].startswith("Eigenheim")
    assert "bis 2033" in goals.lines[0]
    assert "900'000" in goals.lines[0]
    assert goals.lines[1].startswith("Reserve")


# ---------------------------------------------------------------- what it will not do


def test_a_member_with_nothing_recorded_yields_no_sections_rather_than_empty_ones(session, member):
    """An empty heading is worse than no heading: it reads, to a model, as a fact about the member.

    «Ihre erfassten Positionen:» followed by nothing invites an answer about a member who has no money,
    which is a different statement from one about a member who has recorded none.
    """
    sections = member_ground.sections(session, member_id=member.id)
    assert all(section.lines for section in sections), "no section is emitted empty"
    assert not any(section.key in ("positions", "goals") for section in sections)


def test_an_unknown_member_yields_nothing_at_all(session):
    assert member_ground.sections(session, member_id="no-such-member") == []


def test_every_section_becomes_a_passage_of_the_one_kind(session, member):
    """One `kind` rather than four: a citation says «from your own record», and the section is its title."""
    _add(session, member, _stock(member, "Säule 3a", 77000),
         goals=[Goal(member_id=member.id, name="Reserve")])

    passages = member_ground.passages(session, member_id=member.id, question="egal")
    assert passages
    assert {p.kind for p in passages} == {member_ground.KIND}
    assert all(p.title and p.text for p in passages)


def test_the_record_is_returned_whole_and_is_not_filtered_by_the_question(session, member):
    """The difference between this and `member_material`, and the reason the gap existed.

    A member asking «kann ich mit 60 aufhören» shares no word with a row labelled
    `Freizügigkeitsguthaben`, and that row is the answer. Filtering the member's own record by keyword is
    what made thirty-six of fifty questions retrieve nothing.
    """
    _add(session, member, _stock(member, "Freizügigkeitsguthaben", 120000))

    matching = member_ground.passages(session, member_id=member.id,
                                      question="Freizügigkeitsguthaben Höhe")
    unrelated = member_ground.passages(session, member_id=member.id,
                                       question="Kann ich mit 60 aufhören?")
    assert [p.source_id for p in matching] == [p.source_id for p in unrelated]
    assert any("Freizügigkeitsguthaben" in p.text for p in unrelated)


def test_nothing_here_computes_a_figure(session, member):
    """The separation `services/computations.py` exists for.

    A number that appeared here would be a number with no derivation attached to it. Every franc in these
    sections is one the member recorded, rendered; no total, no difference, no share.
    """
    _add(session, member, _stock(member, "Säule 3a", 77000), _stock(member, "Pensionskasse", 95000))

    text = _section(session, member, "positions").text
    assert "77'000" in text and "95'000" in text
    assert "172'000" not in text, "a sum here would be arithmetic nobody can trace to a service"


# ---------------------------------------------------------------- the stated plan


def _submission(session, member, **raw):
    from eigentlich.services.submissions import store

    store(session, member_id=member.id, file={"schema_version": "onb@0.1.3", "raw": raw})
    session.commit()


def test_the_stated_plan_reaches_the_record_with_each_figures_unit(session, member):
    """What the member spends, saves and could bear — the inputs to «reicht es?».

    All 60 members holding a submission stated what they spend now, what they expect to spend after they
    stop, and how much loss they could bear, and none of it reached the model: the answer path had their
    positions and their goals and not one of these. A question about whether their money lasts cannot be
    answered from a balance sheet alone.
    """
    _submission(session, member, spend_now=45000, spend_later=55000, savings=12000,
                max_loss_pct="30 %")

    plan = _section(session, member, "plan")
    assert plan is not None
    text = plan.text
    assert "Ausgaben heute: CHF 45'000 pro Jahr" in text
    assert "Ausgaben nach dem Aufhören: CHF 55'000 pro Jahr" in text
    assert "Sparbetrag: CHF 12'000 pro Jahr" in text
    assert "Maximal tragbarer Verlust (Anteil): 30 %" in text
    assert "Flüsse" in text and "Bestände" in text


def test_a_stock_in_the_plan_is_not_given_a_per_year(session, member):
    """The same discipline as the position list, in the section that states a mortgage next to a saving."""
    _submission(session, member, mortgage=600000, amortisation=8000)

    text = _section(session, member, "plan").text
    assert "Hypothekarschuld: CHF 600'000" in text
    assert "Hypothekarschuld: CHF 600'000 pro Jahr" not in text
    assert "Amortisation: CHF 8'000 pro Jahr" in text


def test_income_variable_is_francs_a_year_and_not_a_yes_or_no(session, member):
    """Planted violation: it was labelled «Schwankt das Einkommen» and rendered plain.

    The stored values are 0, 6'000, 25'000 and 30'000 — the variable PART of the income, in francs. The
    label put «Schwankt das Einkommen: 30000» in front of the model, which is not a sentence about
    anything. Found by reading what the field actually holds rather than what its name suggests.
    """
    _submission(session, member, income_variable=30000)

    text = _section(session, member, "plan").text
    assert "CHF 30'000 pro Jahr" in text
    assert "Schwankt das Einkommen" not in text


def test_a_member_who_stated_no_plan_figures_gets_no_plan_section(session, member):
    assert _section(session, member, "plan") is None
