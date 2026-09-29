"""Provenance is not currency. Item 6's contract, and the degradation it forces on the Befund.

The failure being guarded against is specific and quiet: a plan that keeps re-solving and keeps stating
properly-sourced figures, every check green, over a household composition nobody has confirmed in years.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.content import HorizonNotPublished, horizon_provenance
from eigentlich.models import ADULT, DEPENDANT
from eigentlich.services import currency
from eigentlich.services import household as household_service
from eigentlich.services.befund import Fact, render_befund
from eigentlich.services.household import Person

STATED = date(2027, 3, 14)


def _facts(report: dict, section: str) -> list[dict]:
    for block in report["sections"]:
        if block["key"] == section:
            return block["facts"]
    raise AssertionError(f"no section {section!r} in the report")


# ============================================================ no horizon is written in code


def test_the_horizon_comes_from_the_published_record_and_not_from_this_codebase():
    """C-02. The number is twelve, and it is twelve because a file says so."""
    assert currency.of("household_composition", STATED, today=STATED).horizon_months == 12

    provenance = horizon_provenance()
    assert provenance["published_by"].strip()
    assert provenance["effective_from"] == "2026-09-03"


def test_no_module_in_the_currency_path_writes_a_horizon_literal():
    """A grep, because the defect this guards is a plausible number typed in during a hurry."""
    import inspect
    import re

    for module in (currency,):
        source = inspect.getsource(module)
        # Strip docstrings and comments: the essays quote "twelve months" on purpose.
        code = "\n".join(
            line.split("#")[0]
            for line in source.splitlines()
            if not line.strip().startswith(("#", '"', "'"))
        )
        found = [
            match
            for match in re.findall(r"months\s*=\s*(\d+)|(\d+)\s*\*\s*30", code)
            if any(match)
        ]
        assert not found, f"{module.__name__} writes a horizon literal: {found}"


def test_an_input_class_with_no_published_horizon_raises_rather_than_never_expiring():
    """Failing open would present a stale figure as certified, which is the whole defect."""
    with pytest.raises(HorizonNotPublished) as raised:
        currency.of("income", STATED, today=STATED)
    assert "forbids a default" in str(raised.value)


def test_every_input_class_the_application_ages_has_a_published_horizon():
    """So a new entry in INPUT_CLASSES fails the suite rather than raising for a member at render time."""
    assert currency.unpublished_classes() == ()


# ============================================================ the arithmetic


def test_a_value_is_still_valid_on_the_day_it_expires():
    """`>` and not `>=`. A boundary that turned at midnight would depend on the reader's timezone."""
    on_the_day = currency.of("household_composition", STATED, today=date(2028, 3, 14))
    assert on_the_day.expires_on == date(2028, 3, 14)
    assert on_the_day.expired is False
    assert on_the_day.degrades is False

    next_day = currency.of("household_composition", STATED, today=date(2028, 3, 15))
    assert next_day.expired is True
    assert next_day.degrades is True


def test_month_arithmetic_clamps_the_day_rather_than_rolling_forward():
    """31 January plus twelve months is 31 January. 29 February plus twelve is 28 February."""
    assert currency._add_months(date(2027, 1, 31), 12) == date(2028, 1, 31)
    assert currency._add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert currency._add_months(date(2027, 3, 31), 1) == date(2027, 4, 30)
    assert currency._add_months(date(2027, 12, 15), 12) == date(2028, 12, 15)


def test_age_is_measured_from_the_date_the_value_describes():
    one = currency.of("household_composition", STATED, today=date(2027, 3, 24))
    assert one.stated_on == STATED
    assert one.age_days == 10


def test_one_degraded_input_is_enough_and_there_is_no_partial_credit():
    fresh = currency.of("household_composition", STATED, today=STATED)
    stale = currency.of("household_composition", STATED, today=date(2029, 1, 1))

    assert currency.determination([fresh]) == currency.STANDS
    assert currency.determination([fresh, stale]) == currency.COULD_NOT_BE_DETERMINED
    assert currency.determination([]) == currency.STANDS


def test_there_is_no_stale_or_needs_review_state():
    """Item 6 says use the Household Optimiser's third answer, not a fourth vocabulary."""
    assert currency.DETERMINATIONS == ("stands", "could_not_be_determined")
    for banned in ("stale", "expired", "warning", "needs_review", "out_of_date"):
        assert banned not in currency.DETERMINATIONS


# ============================================================ the Fact contract


def test_a_fact_that_could_not_be_determined_must_name_the_input_that_made_it_so():
    """Otherwise the state is unfalsifiable: anything could be marked undeterminable."""
    with pytest.raises(ValueError) as raised:
        Fact(
            section="household",
            key="k",
            sentence="Ein Satz.",
            source="member_stated",
            data_class=2,
            determination=currency.COULD_NOT_BE_DETERMINED,
        )
    assert "names no input class" in str(raised.value)


def test_a_fact_cannot_rest_on_an_input_class_nothing_can_age():
    with pytest.raises(ValueError) as raised:
        Fact(
            section="household",
            key="k",
            sentence="Ein Satz.",
            source="member_stated",
            data_class=2,
            input_classes=("the_weather",),
        )
    assert "cannot age" in str(raised.value)


def test_a_rephrased_fact_carries_its_currency_rather_than_recomputing_it():
    """A model rewrote the wording; it did not make a stale input current."""
    original = Fact(
        section="household",
        key="household_could_not_be_determined",
        sentence="Ihr Haushalt ist mit Stand 14.03.2027 erfasst.",
        source="member_stated",
        data_class=2,
        input_classes=("household_composition",),
        determination=currency.COULD_NOT_BE_DETERMINED,
        currency=({"input_class": "household_composition", "expired": True},),
    )
    rewritten = original.rephrased("Der Haushalt wurde am 14.03.2027 erfasst.")

    assert rewritten.determination == currency.COULD_NOT_BE_DETERMINED
    assert rewritten.input_classes == ("household_composition",)
    assert rewritten.currency == original.currency


# ============================================================ the Befund, end to end


@pytest.fixture()
def store(tmp_path):
    from eigentlich.services.vault import VaultStore

    return VaultStore(tmp_path / "vault")


def _state(session, member, *, dependants=0):
    people = [Person(label="Ich", kind=ADULT, member_id=member.id)]
    people += [Person(label=f"Kind {n}", kind=DEPENDANT) for n in range(1, dependants + 1)]
    house = household_service.state(
        session, member_id=member.id, people=people, as_of=STATED
    )
    session.commit()
    return house


def test_an_unstated_household_is_a_fact_and_not_an_empty_section(session, member):
    report = render_befund(session, member_id=member.id, today=STATED)
    facts = _facts(report, "household")

    assert [f["key"] for f in facts] == ["household_not_stated"]
    assert facts[0]["determination"] == currency.STANDS
    assert facts[0]["input_classes"] == []
    assert report["currency"]["any_finding_could_not_be_determined"] is False


def test_a_current_household_is_stated_with_its_as_of_date(session, member):
    _state(session, member, dependants=1)
    report = render_befund(session, member_id=member.id, today=date(2027, 6, 1))
    facts = _facts(report, "household")

    stated = [f for f in facts if f["key"] == "household_stated"][0]
    assert "14.03.2027" in stated["sentence"]
    assert stated["values"]["adults"] == 1
    assert stated["values"]["dependants"] == 1
    assert stated["determination"] == currency.STANDS
    assert stated["input_classes"] == ["household_composition"]
    assert stated["currency"][0]["expired"] is False

    assert any(f["key"] == "household_with_dependants" for f in facts)


def test_past_the_horizon_the_composition_degrades_and_the_figure_is_withheld(session, member):
    """The heart of item 6. Not a warning beside the number — the number is not stated."""
    _state(session, member, dependants=1)
    report = render_befund(session, member_id=member.id, today=date(2028, 6, 1))
    facts = _facts(report, "household")

    keys = [f["key"] for f in facts]
    assert "household_could_not_be_determined" in keys
    # The composition is NOT also stated beside it.
    assert "household_stated" not in keys
    assert "household_with_dependants" not in keys

    degraded = [f for f in facts if f["key"] == "household_could_not_be_determined"][0]
    assert degraded["determination"] == currency.COULD_NOT_BE_DETERMINED
    assert degraded["input_classes"] == ["household_composition"]
    # It says when, how long, and until when — and carries no count of anybody.
    assert set(degraded["values"]) == {"as_of", "horizon_months", "expires_on"}
    assert "adults" not in degraded["values"]
    assert degraded["values"]["horizon_months"] == 12
    assert degraded["values"]["expires_on"] == "2028-03-14"


def test_the_envelope_reports_which_findings_could_not_be_determined(session, member):
    _state(session, member)
    report = render_befund(session, member_id=member.id, today=date(2028, 6, 1))

    block = report["currency"]
    assert block["any_finding_could_not_be_determined"] is True
    assert block["could_not_be_determined"] == [
        {
            "section": "household",
            "key": "household_could_not_be_determined",
            "input_classes": ["household_composition"],
        }
    ]
    assert block["horizons"]["effective_from"] == "2026-09-03"


def test_the_envelope_carries_no_tally_of_what_is_uncertifiable(session, member):
    """A count of how stale you are is a score. R-113, C-07."""
    _state(session, member)
    report = render_befund(session, member_id=member.id, today=date(2028, 6, 1))

    for key, value in report["currency"].items():
        assert not isinstance(value, (int, float)) or isinstance(value, bool), (
            f"currency.{key} is a bare number: {value!r}"
        )


def test_provenance_and_currency_are_separate_keys_and_neither_implies_the_other(session, member):
    _state(session, member)
    report = render_befund(session, member_id=member.id, today=date(2028, 6, 1))

    # No figure came from an assumption...
    assert report["assumptions"]["any_figure_derived_from_an_assumption"] is False
    # ...and a figure that came from the member is nonetheless uncertifiable.
    assert report["currency"]["any_finding_could_not_be_determined"] is True


def test_a_goal_with_no_owner_recorded_is_reported(session, member):
    """A108: a household that never populated `owners` cannot be divided cleanly."""
    from eigentlich.models import Goal
    from eigentlich.services.plan import mutate_plan

    _state(session, member)
    with mutate_plan(
        session, member_id=member.id, question="Record a goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=1_500_000.0)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    report = render_befund(session, member_id=member.id, today=STATED)
    unowned = [f for f in _facts(report, "household") if f["key"] == "goal_owner_not_recorded"]
    assert len(unowned) == 1
    assert unowned[0]["quoted"]["goal_name"] == "Wohneigentum"


def test_a_goal_with_an_owner_is_not_reported_as_unowned(session, member):
    from eigentlich.models import Goal
    from eigentlich.services.plan import mutate_plan

    house = _state(session, member)
    with mutate_plan(
        session, member_id=member.id, question="Record a goal?", choice="Yes"
    ) as decision:
        goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=1_500_000.0)
        goal.owners.extend(house.members)
        session.add(goal)
        decision.linked_goals.append(goal)
    session.commit()

    report = render_befund(session, member_id=member.id, today=STATED)
    assert not [f for f in _facts(report, "household") if f["key"] == "goal_owner_not_recorded"]


def test_the_household_section_comes_first(session, member):
    """It is the frame the rest is read inside: a figure about a household of two means nothing to a
    reader who has been told the household is one."""
    _state(session, member)
    report = render_befund(session, member_id=member.id, today=STATED)
    assert report["sections"][0]["key"] == "household"


def test_the_report_is_still_deterministic_with_the_new_section(session, member):
    _state(session, member)
    first = render_befund(session, member_id=member.id, today=STATED)
    second = render_befund(session, member_id=member.id, today=STATED)
    assert first == second
