"""R-133 / C-02: what a goal actually returns now, and every reason it may give for returning nothing.

**The bug this file exists because of.** `services/goals.py` returned `illustration: None` with the reason
`"no_assumption_set_published"` on every goal, unconditionally — and a set has been published since A69.
So the application told every member a reason that was false, and the test beside it
(`test_no_illustration_is_offered_without_a_published_assumption_set`) passed, because the test database
has no assumption set either. A test can only ever check the case it sets up; the fix is that every reason
is now derived and every derivation is checked here in both directions.

**Every guard was verified by planting the violation, watching it fail, and restoring it.** What was
planted is recorded against each test.

**No estate is required.** These tests write an AssumptionSet by hand in the shape the real one has — the
values below are the real 30 August 2026 figures from `2024-12-31+REG-38d91c1a+RS-874b03c9`, read out of
`backend/eigentlich.db` — and one test additionally checks the illustration against whatever set the
developer's database actually holds, skipping honestly when there is none.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from eigentlich.models import AssumptionSet, Goal, Position, ROLES
from eigentlich.services import mutate_plan
from eigentlich.services.goals import list_goals
from eigentlich.services.illustration import (
    CAVEATS,
    HUMAN_CAPITAL_EXCLUSION_REASON,
    PLAN_ROLE_TO_SET_ROLE,
    UNAVAILABLE_REASONS,
    goal_illustration,
)

TODAY = date(2026, 8, 31)
VINTAGE = date(2024, 12, 31)

#: The real published figures, trimmed to two scenarios and two roles. Copied from the run A69 recorded,
#: so nothing here is a made-up rate — the point of the whole exercise.
RATES = {
    "values_unit": "annualised_decimal",
    "scenarios": ["crisis", "contraction", "stagnation", "expansion", "boom"],
    "role_profiles_by_scenario": {
        "gain": {"crisis": -0.35813067508492946, "boom": 0.09666666666666666},
        "protection": {"crisis": 0.22336290470907294, "boom": -0.0033333333333333327},
    },
    "scenario_probabilities": {"crisis": 0.20957597100996284, "boom": 0.1228892482466044},
    # Present in the real set and forbidden from ever reaching a member (C-03). Kept here so the
    # artefact assertions below are checking something that was genuinely available to leak.
    "state_grid": 25,
    "state_to_scenario": {"0": "crisis", "24": "boom"},
    "source": {
        "market_signal": {
            "regime_id": "REG-38d91c1a0da0ef1e",
            "regime_timeline_id": "RTL-38d91c1a0da0ef1e",
            "replay": "cd Macro_Model && <read> output/regime/Global.json",
        },
        "return_estimation": {"return_set_id": "RS-874b03c95f8f77a8"},
    },
}

HORIZONS = {"return_estimation_years": 1.0, "scope": "Global"}

#: The same set with the `income` profile the real published one carries, and the reason the human-capital
#: defect survived nine fixtures: `RATES` above publishes `gain` and `protection` only, so an income
#: position fell out through `the_funding_roles_are_not_in_the_assumption_set` and looked handled. With
#: `income` present it does not, and the salary gets a market rate — which is what the audit measured.
#:
#: `-0.0593` is the audit's own figure, against the audit's own amount: `-0.0593 * 250_000 == -14825.0`,
#: a market contraction taking fifteen thousand francs out of somebody's job.
RATES_WITH_INCOME = {
    **RATES,
    "role_profiles_by_scenario": {
        **RATES["role_profiles_by_scenario"],
        "income": {"crisis": -0.0593, "boom": 0.041},
    },
}


@pytest.fixture()
def published(session):
    def _publish(*, effective_from=VINTAGE, rates=None, horizons=None, inflation=None, version="v-test"):
        record = AssumptionSet(
            version=version,
            effective_from=effective_from,
            published_by="SIM Research, run 2026-08-30",
            rates=RATES if rates is None else rates,
            horizons=HORIZONS if horizons is None else horizons,
            inflation=inflation,
        )
        session.add(record)
        session.commit()
        return record

    return _publish


def _plan(session, member, *, goals=(), positions=(), link=None):
    with mutate_plan(session, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        for obj in [*positions, *goals]:
            session.add(obj)
        if link:
            link()
        decision.linked_positions.extend(positions)
        decision.linked_goals.extend(goals)
    session.commit()


@pytest.fixture()
def funded_goal(session, member):
    """A dated, priced goal funded by one growth position. The shape a real member has."""
    goal = Goal(
        member_id=member.id,
        name="Wohneigentum",
        target_amount=250_000,
        target_date=TODAY + timedelta(days=1500),
    )
    position = Position(
        member_id=member.id, role="growth", capital_type="financial", label="Depot",
        liquidity="within_months",
    )
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))
    return goal


@pytest.fixture()
def salary_funded_goal(session, member):
    """**The default path, which no fixture had.** `services/onboarding.py` gives every member exactly one
    position — `role="income", capital_type="human"`, the salary from the first conversation — and the
    containers form offers it in the goal's funding multiselect. So this is one click away for a member
    who has answered the intake and named a goal, and it is the shape the audit measured a market rate
    against.

    Same amount and same role as `funded_goal`; the only difference is `capital_type`.
    """
    goal = Goal(
        member_id=member.id,
        name="Wohneigentum",
        target_amount=250_000,
        target_date=TODAY + timedelta(days=1500),
    )
    position = Position(
        member_id=member.id, role="income", capital_type="human", label="Lohn",
        magnitude=120_000, magnitude_unit="chf_per_year", time_basis="42 Std./Woche",
    )
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))
    return goal


@pytest.fixture()
def mixed_funded_goal(session, member):
    """One goal, two kinds of capital: a securities account and the member's salary.

    R-030 makes this ordinary rather than exotic — a goal may be funded by anything the member says funds
    it — so the answer cannot be "refuse the whole goal".
    """
    goal = Goal(
        member_id=member.id,
        name="Wohneigentum",
        target_amount=250_000,
        target_date=TODAY + timedelta(days=1500),
    )
    depot = Position(
        member_id=member.id, role="growth", capital_type="financial", label="Depot",
        liquidity="within_months",
    )
    salary = Position(
        member_id=member.id, role="income", capital_type="human", label="Lohn",
        time_basis="42 Std./Woche",
    )
    _plan(session, member, goals=[goal], positions=[depot, salary],
          link=lambda: goal.funded_by.extend([depot, salary]))
    return goal


def _illustrate(session, goal, member):
    return goal_illustration(session, goal, member_id=member.id, today=TODAY)


def _field_names(value) -> set[str]:
    """Every mapping key in a payload, at any depth, lowercased. For checking a *shape*, not prose."""
    names: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            names.add(str(key).lower())
            names |= _field_names(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            names |= _field_names(inner)
    return names


def _numeric_leaves(value) -> set[float]:
    """Every numeric leaf in a payload, at any depth. Booleans excluded — `False` is not a figure."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    found: set[float] = set()
    if isinstance(value, dict):
        for inner in value.values():
            found |= _numeric_leaves(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            found |= _numeric_leaves(inner)
    return found


def test_the_shape_scanners_find_what_they_look_for():
    """The guard on the two guards above. Without this, `test_no_blended_or_weighted_figure_appears` would
    pass on scanners that returned nothing for everything — A20's exact shape."""
    assert _field_names({"a": [{"Expected_Rate": 1}]}) == {"a", "expected_rate"}
    assert _numeric_leaves({"a": [{"b": 2.5}], "c": True, "d": None}) == {2.5}


# ============================================================ the reason must be true


def test_the_empty_table_is_the_only_route_to_no_assumption_set_published(session, member, funded_goal,
                                                                         published):
    """**The bug, held closed.** That reason may only appear when `assumption_sets` is genuinely empty.

    It was returned unconditionally, from a hardcoded literal, while a real set was published. Both
    directions are checked: empty table gives that reason, and a published set gives a real illustration.

    **Asserted through `list_goals`, not through `goal_illustration`.** The first version of this test
    called the builder directly and **did not catch the planted bug**: re-planting the original hardcoded
    `{"illustration": None, "illustration_unavailable_reason": "no_assumption_set_published"}` in
    `goal_payload` left it green, because the builder was still correct and simply no longer called. The
    defect was never in the arithmetic — it was in the wiring — so the test has to cross the wire.

    **Planted violation:** re-planted that literal in `goal_payload`. Now fails on the second half.
    Restored. Also planted the reverse — dropped the `**goal_illustration(...)` spread entirely — and it
    fails on the missing key.
    """
    #: `today=TODAY`, and it has to be. This read `list_goals(session, member_id=member.id)` with no date
    #: until 1 September 2026, then compared the result against `_illustrate`, which pins `TODAY`. The two
    #: agreed only while the wall clock happened to be 31 August: `horizon.goal_years` is computed from
    #: the date it is called on, so the comparison at the end of this test started failing at midnight on
    #: a difference of one day. A guard that holds on one calendar date is not a guard — A96's point about
    #: a probabilistic guard, with the clock in place of the random ids.
    def payload():
        return next(g for g in list_goals(session, member_id=member.id, today=TODAY)["goals"]
                    if g["id"] == funded_goal.id)

    empty = payload()
    assert empty["illustration"] is None
    assert empty["illustration_unavailable_reason"] == "no_assumption_set_published"

    published()
    filled = payload()
    assert filled["illustration_unavailable_reason"] is None
    assert filled["illustration"] is not None
    assert filled["illustration"]["assumption_set_id"]

    # And the builder agrees with the payload, so the two cannot drift apart silently.
    assert _illustrate(session, funded_goal, member)["illustration"] == filled["illustration"]


def test_a_set_that_is_not_yet_in_effect_gets_its_own_reason(session, member, funded_goal, published):
    """A published set with a future `effective_from` is not "nothing published" — a different fact.

    `assumptions.current` filters on `effective_from <= today`, so the old single reason would have been
    false here too, in the other direction.

    **Planted violation:** collapsed both branches back to `no_assumption_set_published`. Failed here.
    """
    published(effective_from=TODAY + timedelta(days=30))
    outcome = _illustrate(session, funded_goal, member)
    assert outcome["illustration"] is None
    assert outcome["illustration_unavailable_reason"] == "no_assumption_set_in_effect_yet"


def test_a_goal_with_no_amount_says_so(session, member, published):
    """R-132. Courage money is defined by what it is FOR; an amount is not missing data.

    There is nothing to apply a rate to, and the honest output is the reason rather than a figure.
    """
    published()
    goal = Goal(member_id=member.id, name="Mutgeld", template="courage_money")
    position = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))

    outcome = _illustrate(session, goal, member)
    assert outcome["illustration"] is None
    assert outcome["illustration_unavailable_reason"] == "the_goal_names_no_amount"


def test_an_unfunded_goal_says_so(session, member, published):
    """R-030. An unfunded goal is a legitimate state, and there is no role to read a rate for."""
    published()
    goal = Goal(member_id=member.id, name="Ferienhaus", target_amount=100_000)
    _plan(session, member, goals=[goal])

    outcome = _illustrate(session, goal, member)
    assert outcome["illustration_unavailable_reason"] == "the_goal_names_no_active_funding"


def test_an_inactive_position_does_not_fund_an_illustration(session, member, published):
    """R-122. A position the member has stood down stays in history and funds nothing.

    **Planted violation:** dropped the `position.active` filter from `_funding_roles`. This test failed by
    producing an illustration over a holding the member had marked inactive. Restored.
    """
    published()
    goal = Goal(member_id=member.id, name="Auto", target_amount=40_000)
    position = Position(
        member_id=member.id, role="growth", capital_type="financial", label="Alt", active=False
    )
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))

    assert _illustrate(session, goal, member)["illustration_unavailable_reason"] == (
        "the_goal_names_no_active_funding"
    )


def test_a_set_with_no_role_profiles_says_so(session, member, funded_goal, published):
    """A set can exist and carry no role profiles — `compose` reads them from the artefact.

    The reason names that rather than blaming the plan.
    """
    published(rates={"values_unit": "annualised_decimal"})
    assert _illustrate(session, funded_goal, member)["illustration_unavailable_reason"] == (
        "the_assumption_set_publishes_no_role_profiles"
    )


def test_a_funding_role_the_set_does_not_publish_says_so(session, member, published):
    """The set publishes four roles; if the goal's funding names none of them, say that.

    **Planted violation:** returned an illustration with an empty `by_role`. Failed here — an illustration
    with no figures is not an illustration, and a screen would have rendered an empty range.
    """
    published(rates={**RATES, "role_profiles_by_scenario": {"income": {"boom": 0.02}}})
    goal = Goal(member_id=member.id, name="Haus", target_amount=100_000)
    position = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))

    assert _illustrate(session, goal, member)["illustration_unavailable_reason"] == (
        "the_funding_roles_are_not_in_the_assumption_set"
    )


def test_every_reason_returned_is_one_of_the_declared_ones(session, member, funded_goal, published):
    """No reason is invented at a call site. `_unavailable` raises on an unlisted one.

    **Planted violation:** returned `"reason_i_just_made_up"` from one branch. `ValueError` at the source
    rather than a string reaching a client — which is the direction that keeps a client's rendering honest.
    """
    from eigentlich.services.illustration import _unavailable

    with pytest.raises(ValueError):
        _unavailable("not_a_declared_reason")
    assert len(set(UNAVAILABLE_REASONS)) == len(UNAVAILABLE_REASONS)
    assert "no_assumption_set_published" in UNAVAILABLE_REASONS


# ============================================================ what an illustration actually says


def test_the_illustration_is_stamped_with_the_set_it_used(session, member, funded_goal, published):
    """C-02. "Every illustration response returns the assumption_set_id used"."""
    record = published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    assert illustration["assumption_set_id"] == record.id
    assert illustration["assumption_set_version"] == "v-test"
    assert illustration["assumption_set_effective_from"] == VINTAGE.isoformat()
    assert illustration["published_by"] == "SIM Research, run 2026-08-30"


def test_every_figure_traces_to_the_member_or_to_the_published_set(session, member, funded_goal,
                                                                  published):
    """The whole point: nothing is invented. Each number is either the member's or the engine's.

    The rate is copied from the set, unrounded; the amount is the member's own; the two products are the
    labelled illustrative arithmetic C-02 permits and nothing else appears.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]

    assert illustration["basis"] == {
        "amount_chf": 250_000,
        "read_from": "goal_target_amount",
        # Principle 9. Which inputs the arithmetic accepted, said inside the figure block.
        "capital_types_projected": ["financial"],
    }
    assert illustration["values_unit"] == "annualised_decimal"

    growth = next(entry for entry in illustration["by_role"] if entry["role"] == "growth")
    crisis = next(s for s in growth["scenarios"] if s["scenario"] == "crisis")
    published_rate = RATES["role_profiles_by_scenario"]["gain"]["crisis"]

    assert crisis["rate"] == published_rate, "the rate must be copied, not rounded or transformed"
    assert crisis["change_chf"] == 250_000 * published_rate
    assert crisis["amount_after_the_horizon_chf"] == 250_000 * (1 + published_rate)
    assert crisis["probability_as_published"] == RATES["scenario_probabilities"]["crisis"]


def test_the_scenarios_are_in_the_sets_own_order(session, member, funded_goal, published):
    """Crisis to boom, the way the engine publishes it, rather than alphabetically.

    A screen listing a range wants the engine's order; sorting it would put `boom` first and read as a
    ranking of outcomes.
    """
    published()
    growth = _illustrate(session, funded_goal, member)["illustration"]["by_role"][0]
    assert [s["scenario"] for s in growth["scenarios"]] == ["crisis", "boom"]


def test_a_scenario_the_set_did_not_list_is_still_illustrated(session, member, funded_goal, published):
    """The profile is the authority on what was estimated; the `scenarios` list is only an order.

    **Planted violation:** filtered the profile down to the listed scenarios. A published rate silently
    disappeared from the illustration, which is a number the engine produced and the member did not see.
    """
    published(rates={**RATES, "scenarios": ["crisis"]})
    growth = _illustrate(session, funded_goal, member)["illustration"]["by_role"][0]
    assert [s["scenario"] for s in growth["scenarios"]] == ["crisis", "boom"]


def test_the_role_mapping_is_explicit_and_covers_every_role():
    """A69. The estate calls the first role `gain`; §4 and `models.plan.ROLES` call it `growth`.

    A69 said whatever mapped them first must do it explicitly. This is that mapping, and it is checked
    against `ROLES` at **import** so a fifth role added to the plan cannot silently fall out of every
    illustration.

    **Planted violation:** added a fifth role to `models.plan.ROLES` without a line in the mapping. The
    import raised, which is the only place that failure is cheap. Restored.
    """
    assert set(PLAN_ROLE_TO_SET_ROLE) == set(ROLES)
    assert PLAN_ROLE_TO_SET_ROLE["growth"] == "gain"
    for name in ("income", "stabilisation", "protection"):
        assert PLAN_ROLE_TO_SET_ROLE[name] == name


def test_both_role_names_travel_so_the_translation_is_visible(session, member, funded_goal, published):
    """A69 again: a silent rename inside a provenance record is worse than a mismatch anyone can see."""
    published()
    growth = _illustrate(session, funded_goal, member)["illustration"]["by_role"][0]
    assert growth["role"] == "growth"
    assert growth["assumption_set_role"] == "gain"


def test_two_roles_are_illustrated_separately_and_never_combined(session, member, published):
    """D-02 and A69. Two funding roles give two ranges, not one blended one.

    **Planted violation:** averaged the two profiles into one `expected_rate`. Failed here on the shape and
    on `test_no_blended_or_weighted_figure_appears` below. Restored.
    """
    published()
    goal = Goal(member_id=member.id, name="Haus", target_amount=100_000)
    growth = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    protection = Position(
        member_id=member.id, role="protection", capital_type="financial", label="Versicherung"
    )
    _plan(
        session, member, goals=[goal], positions=[growth, protection],
        link=lambda: (goal.funded_by.append(growth), goal.funded_by.append(protection)),
    )

    illustration = _illustrate(session, goal, member)["illustration"]
    assert [entry["role"] for entry in illustration["by_role"]] == ["growth", "protection"]
    assert all(entry["scenarios"] for entry in illustration["by_role"])


def test_how_many_positions_name_each_role_is_reported(session, member, published):
    """R-130. The member should see which of their own holdings the range is about."""
    published()
    goal = Goal(member_id=member.id, name="Haus", target_amount=100_000)
    one = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot A")
    two = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot B")
    _plan(session, member, goals=[goal], positions=[one, two],
          link=lambda: (goal.funded_by.append(one), goal.funded_by.append(two)))

    growth = _illustrate(session, goal, member)["illustration"]["by_role"][0]
    assert growth["positions_naming_this_role"] == 2


# ============================================================ C-02: nothing blended, nothing extended


def test_no_blended_or_weighted_figure_appears(session, member, funded_goal, published):
    """A69. The profiles and the probabilities are published side by side and nothing multiplies them.

    The same guard `test_no_blended_rate_is_published` puts on the set itself, one layer out — because the
    layer that consumes the set is where the multiplication is one line away.

    **Checked structurally, over field NAMES and numeric VALUES, not as a substring of the document.** The
    first version of this test scanned the rendered JSON for the word "blended" and failed on the prose
    explaining that no blended rate is published — the same false-positive class as the C-03 import check
    in `test_constraints.py`, which used to fail a module for a docstring saying what it must not import. A
    payload that *explains* an absence is the opposite of a payload that contains the thing.

    **Planted violation:** added `"expected_change_chf": sum(rate * probability for ...)` to each role.
    Failed on both halves — the field name, and the value appearing among the numeric leaves. Restored:
    which probabilities weight which horizon is a decision with an owner, and a service module is not
    where it gets made.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]

    names = _field_names(illustration)
    assert names, "no field names were found, so this test proves nothing"
    for forbidden in ("expected", "blended", "weighted", "average", "mean"):
        offending = sorted(name for name in names if forbidden in name)
        assert not offending, f"C-02 / A69: a composed figure appeared as {offending}"

    # And the value itself is absent, not merely unnamed: a probability-weighted change is one
    # multiplication away and would be as wrong under an innocent name.
    profile = RATES["role_profiles_by_scenario"]["gain"]
    probabilities = RATES["scenario_probabilities"]
    blended = sum(profile[name] * probabilities[name] for name in profile)
    leaves = _numeric_leaves(illustration)
    assert leaves, "no numbers were found, so this test proves nothing"
    for value in (blended, blended * 250_000, 250_000 * (1 + blended)):
        assert value not in leaves, f"C-02 / A69: a probability-weighted figure appeared: {value}"


def test_the_rates_are_not_extended_to_the_goals_own_horizon(session, member, funded_goal, published):
    """C-02. The set carries rates for ONE horizon and says why they do not compound.

    "A ten-year per-state return is not a one-year return compounded, because the regime does not persist
    for ten years." The goal is dated four years out; both horizons are reported side by side and the
    illustration says in the data that it did not bridge them.

    **Planted violation:** raised the rate to the power of the goal's horizon. Failed here on
    `rates_extended_to_the_goal_horizon`, and it is the single easiest invented number in the build.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    horizon = illustration["horizon"]

    assert horizon["published_years"] == 1.0
    assert horizon["goal_years"] > 4, "the fixture's goal is about four years out"
    assert horizon["rates_extended_to_the_goal_horizon"] is False
    assert "rates_hold_at_the_published_horizon_only" in illustration["caveats"]


def test_an_undated_goal_is_still_illustrated(session, member, published):
    """R-030. An undated goal is a legitimate state, and the illustration does not need a date.

    It reports `goal_years: None` rather than inventing one — the same refusal `engine_inputs.py` makes
    for `horizon_years`.
    """
    published()
    goal = Goal(member_id=member.id, name="Haus", target_amount=100_000)
    position = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    _plan(session, member, goals=[goal], positions=[position],
          link=lambda: goal.funded_by.append(position))

    illustration = _illustrate(session, goal, member)["illustration"]
    assert illustration["horizon"]["goal_years"] is None
    assert illustration["by_role"]


def test_inflation_is_reported_as_unpublished_and_never_as_a_number(session, member, funded_goal,
                                                                   published):
    """A69 / C-02. `inflation` is NULL in the set, so nothing here is in real terms and it says so.

    Reported as a boolean rather than as `inflation: null`, because a null rate on a screen is one careless
    template away from rendering as a zero — R-302's mistake in C-02's clothing.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    assert illustration["inflation_published"] is False
    assert "inflation" not in [key for key in illustration if key != "inflation_published"]
    assert "not_in_real_terms_because_no_inflation_is_published" in illustration["caveats"]

    # And when somebody does publish one with their name against it, the flag flips.
    session.query(AssumptionSet).delete()
    session.commit()
    published(inflation=0.011, version="v-with-inflation")
    assert _illustrate(session, funded_goal, member)["illustration"]["inflation_published"] is True


def test_every_caveat_is_carried(session, member, funded_goal, published):
    """The caveats are keys and not sentences: A12 makes the product bilingual and the wording lives in
    the client's content files beside every other string."""
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    assert illustration["caveats"] == list(CAVEATS)
    for caveat in CAVEATS:
        assert caveat.islower() and " " not in caveat, "a caveat must be a key, not prose"


# ============================================================ why there is no trajectory


def test_the_illustration_says_why_no_trajectory_is_offered(session, member, funded_goal, published):
    """A39 / A69 / §12. The gaps come straight from `engine_inputs.py`, in its own words.

    A trajectory needs `initial_wealth` — not in the plan at all — and `annual_return`, which needs one
    blended rate the set deliberately does not publish. Naming both is the honest alternative to inventing
    either, and it tells the member what would have to exist rather than "not available".

    **Planted violation:** summarised the gaps into a single string here. The considered reasons in
    `engine_inputs.py` were replaced by a shorter, less true copy — which is the drift A39 exists to stop.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    gaps = {gap["input"]: gap for gap in illustration["no_trajectory_because"]}

    assert "initial_wealth" in gaps
    assert gaps["initial_wealth"]["kind"] == "not_in_the_plan"
    assert "chf_per_year" in gaps["initial_wealth"]["reason"], "the reason must be the mapping layer's own"

    assert "annual_return" in gaps
    assert gaps["annual_return"]["kind"] == "needs_an_unpublished_assumption"
    assert "no single blended" in gaps["annual_return"]["reason"].lower() or (
        "blended" in gaps["annual_return"]["reason"]
    )


def test_no_absent_input_is_ever_defaulted(session, member, funded_goal, published):
    """§12 / A69. The ten inputs A69 left absent stay absent. Nothing here fills one in.

    Checked against the mapping layer rather than against a list in this file: whatever `engine_inputs.py`
    calls a plan gap must appear as a gap, so the two cannot disagree.
    """
    from eigentlich.services.engine_inputs import plan_for

    published()
    plan = plan_for("s_curve_trajectory", member_id=member.id, goal=funded_goal, today=TODAY)
    blocking = {gap.name for gap in plan.absent if gap.blocks_the_plan}
    assert blocking, "the mapping layer reports no plan gaps, so this test proves nothing"

    illustration = _illustrate(session, funded_goal, member)["illustration"]
    reported = {gap["input"] for gap in illustration["no_trajectory_because"]}
    assert reported == blocking

    # And none of them is in the payload as a value.
    rendered = json.dumps(illustration)
    for name in blocking:
        assert f'"{name}":' not in rendered, f"§12: {name} was defaulted into the illustration"


# ============================================================ Principle 9: only financial capital
#
# **The defect.** `_funding_roles` grouped `goal.funded_by` by `Position.role` and never read
# `capital_type` — `grep capital_type services/illustration.py` returned nothing at all. So a goal funded
# by a human-capital income position had the ReturnSet's `income` market profile applied to the member's
# stated income, with no caveat and no mention of human capital anywhere in the payload. The audit
# measured `rate -0.0593 -> change_chf -14825.0` on a salary.
#
# Zero of the nine fixtures above used `capital_type="human"`, which is exactly why every guard in this
# file passed over it: the file only ever illustrated securities accounts and insurance policies.


def test_the_income_profile_would_reach_a_salary_without_the_filter(session, member, salary_funded_goal,
                                                                   published):
    """**The non-vacuous half, and it has to come first.** Every assertion below is about a rate NOT being
    applied, and an assertion that a number is absent proves nothing unless the number was available.

    So this pins the other end: the published set really does carry an `income` profile, the salary really
    does occupy the `income` role, and the mapping really would find it. What stops the rate is the capital
    type and nothing else.

    **Planted violation:** removed `income` from `RATES_WITH_INCOME`. The reason came back as
    `the_funding_roles_are_not_in_the_assumption_set` instead, and this failed — which is the whole point:
    with the old `RATES` fixture the defect hid behind a different reason and looked handled.
    """
    from eigentlich.services.illustration import PLAN_ROLE_TO_SET_ROLE

    published(rates=RATES_WITH_INCOME)
    position = salary_funded_goal.funded_by[0]
    assert position.capital_type == "human"
    assert position.role == "income"
    assert position.active
    set_role = PLAN_ROLE_TO_SET_ROLE[position.role]
    assert set_role in RATES_WITH_INCOME["role_profiles_by_scenario"], (
        "the set publishes no profile for this role, so nothing below is testing an exclusion"
    )
    assert RATES_WITH_INCOME["role_profiles_by_scenario"][set_role]["crisis"] == -0.0593


def test_a_goal_funded_only_by_human_capital_gets_no_figure_and_says_why(session, member,
                                                                        salary_funded_goal, published):
    """Principle 9. A salary is not a security, and the published set estimated nothing over it.

    The reason is its **own** key. `the_goal_names_no_active_funding` would have been the easy reuse and it
    would have been false — this goal *is* funded, by a position the member entered on purpose — which is
    the A85 defect exactly: a derived reason that reads as a gap in the member's record when the record is
    complete and it is the arithmetic that declines.

    **Planted violation:** dropped the `capital_type` check from `_funding_roles`, restoring the code as it
    was. The goal came back with a full illustration and `change_chf: -14825.0` against the member's
    salary — the audit's own figure — and this failed on the illustration being present. Restored.
    """
    published(rates=RATES_WITH_INCOME)
    outcome = _illustrate(session, salary_funded_goal, member)

    assert outcome["illustration"] is None
    assert outcome["illustration_unavailable_reason"] == "the_goal_is_funded_only_by_human_capital"
    assert outcome["illustration_unavailable_reason"] != "the_goal_names_no_active_funding", (
        "the goal is funded; a reason saying it is not would send the member to correct a record that "
        "is already right"
    )
    # C-02 holds on the unavailable path too: the answer still names the set it was decided against.
    assert outcome["assumption_set_id"]

    # And it says what it left out, rather than leaving it out quietly.
    excluded = outcome["excluded_from_the_projection"]
    assert [entry["position_id"] for entry in excluded] == [salary_funded_goal.funded_by[0].id]
    assert excluded[0]["capital_type"] == "human"
    assert excluded[0]["role"] == "income"
    assert excluded[0]["reason"] == HUMAN_CAPITAL_EXCLUSION_REASON

    # Not zeroed, and not illustrated at zero: no figure of any kind was produced for it.
    assert -14825.0 not in _numeric_leaves(outcome), "the market rate reached the salary anyway"
    assert 0 not in {entry.get("rate") for entry in excluded}, (
        "a zero rate is a claim that a salary is expected not to move, and nobody published it"
    )


def test_a_goal_funded_by_both_projects_the_financial_part_and_says_what_it_left_out(
    session, member, mixed_funded_goal, published
):
    """R-030 makes mixed funding ordinary, so refusing the whole goal would be the wrong answer too.

    The financial position is projected; the salary is excluded and named. The two facts travel together,
    because an illustration that silently dropped half the funding would be a figure the member cannot
    check against what they entered.

    **Planted violation:** dropped the `capital_type` check from `_funding_roles`. `by_role` came back with
    two entries instead of one and the excluded list was empty; this failed on both. Restored.
    """
    published(rates=RATES_WITH_INCOME)
    outcome = _illustrate(session, mixed_funded_goal, member)
    illustration = outcome["illustration"]

    assert illustration is not None, "the financial half is projectable and was not projected"
    assert outcome["illustration_unavailable_reason"] is None

    # Only the financial role is illustrated, and the set publishes a profile for both.
    assert [entry["role"] for entry in illustration["by_role"]] == ["growth"]
    assert illustration["basis"]["capital_types_projected"] == ["financial"]

    # The salary is named, once, with its stable reason key.
    salary = next(p for p in mixed_funded_goal.funded_by if p.capital_type == "human")
    excluded = outcome["excluded_from_the_projection"]
    assert [entry["position_id"] for entry in excluded] == [salary.id]
    assert excluded[0]["reason"] == HUMAN_CAPITAL_EXCLUSION_REASON

    # And the income rate reached nothing: the only rates present are the growth profile's.
    rates_used = {
        scenario["rate"]
        for entry in illustration["by_role"]
        for scenario in entry["scenarios"]
    }
    assert -0.0593 not in rates_used, "the income profile was applied to a human-capital position"
    assert rates_used == set(RATES_WITH_INCOME["role_profiles_by_scenario"]["gain"].values())


def test_an_inactive_salary_is_not_reported_as_excluded(session, member, published):
    """R-122 again, on the new list. A position the member has stood down is not funding anything, so it
    is not something the projection "left out" — listing it would put a position they retired back on the
    screen with a reason beside it.

    **Planted violation:** dropped the `active` check from the human-capital branch of `_funding_roles`.
    The retired salary appeared in `excluded_from_the_projection` and this failed. Restored.
    """
    published(rates=RATES_WITH_INCOME)
    goal = Goal(member_id=member.id, name="Wohneigentum", target_amount=250_000)
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    retired = Position(
        member_id=member.id, role="income", capital_type="human", label="Alte Stelle", active=False
    )
    _plan(session, member, goals=[goal], positions=[depot, retired],
          link=lambda: goal.funded_by.extend([depot, retired]))

    outcome = _illustrate(session, goal, member)
    assert outcome["illustration"] is not None
    assert outcome["excluded_from_the_projection"] == []


def test_every_answer_carries_the_excluded_list_including_when_nothing_was_excluded(
    session, member, funded_goal, salary_funded_goal, published
):
    """The key is on every path, empty list included — the same argument
    `illustration_unavailable_reason` itself rests on: a client that had to infer "nothing was excluded"
    from a missing key would be inferring from absence.

    Checked across an illustrated answer, an unavailable answer that has nothing to do with capital type,
    and the human-capital answer, so the key cannot be present only where it is interesting.

    **Planted violation:** returned the illustrated payload without the key. Failed on the first case.
    Then dropped the default from `_unavailable` so only the human-capital branch passed one, and the
    empty-table case failed. Restored.
    """
    # 1. No set published at all — the earliest return in the function.
    empty = _illustrate(session, funded_goal, member)
    assert empty["illustration_unavailable_reason"] == "no_assumption_set_published"
    assert empty["excluded_from_the_projection"] == []

    published(rates=RATES_WITH_INCOME)

    # 2. A full illustration, nothing excluded.
    illustrated = _illustrate(session, funded_goal, member)
    assert illustrated["illustration"] is not None
    assert illustrated["excluded_from_the_projection"] == []

    # 3. The human-capital answer.
    salary = _illustrate(session, salary_funded_goal, member)
    assert salary["excluded_from_the_projection"], "the one case that has something to report reports it"


def test_the_capital_type_filter_names_every_capital_type_the_plan_has(session, member,
                                                                      salary_funded_goal, published):
    """A69's argument about `PLAN_ROLE_TO_SET_ROLE`, applied to the other vocabulary.

    A third capital type added to `models.plan.CAPITAL_TYPES` must not fall silently into whichever branch
    happens to catch it — and the branch that catches an unknown type is the one that applies a market
    rate, so the failure mode is the defect this section exists to close, arriving again through a column
    nobody thought about.

    **Planted violation:** added `"reputational"` to `CAPITAL_TYPES` and reimported. The import-time
    contract raised `RuntimeError`, so the whole module failed rather than one goal quietly getting a
    market rate on somebody's reputation. Restored.
    """
    from eigentlich.models import CAPITAL_TYPES
    from eigentlich.services.illustration import FINANCIAL_CAPITAL, HUMAN_CAPITAL

    assert {FINANCIAL_CAPITAL, HUMAN_CAPITAL} == set(CAPITAL_TYPES)
    # And the reason key is a key, not a sentence (A12): the client holds the wording.
    assert HUMAN_CAPITAL_EXCLUSION_REASON.islower()
    assert " " not in HUMAN_CAPITAL_EXCLUSION_REASON


def test_the_human_capital_reason_is_declared_like_every_other_reason(session, member,
                                                                     salary_funded_goal, published):
    """`_unavailable` raises on an unlisted reason, so the new one has to be in the tuple — and the tuple
    is what `tests/test_client_surfaces.py` parametrises over to require a sentence in both languages.

    **Planted violation:** removed it from `UNAVAILABLE_REASONS`. `ValueError` at the source rather than
    an undeclared string reaching a client.
    """
    assert "the_goal_is_funded_only_by_human_capital" in UNAVAILABLE_REASONS
    assert len(set(UNAVAILABLE_REASONS)) == len(UNAVAILABLE_REASONS)

    published(rates=RATES_WITH_INCOME)
    outcome = _illustrate(session, salary_funded_goal, member)
    assert outcome["illustration_unavailable_reason"] in UNAVAILABLE_REASONS


# ============================================================ C-03 at the last boundary


def test_the_illustration_carries_no_engine_artefact(session, member, funded_goal, published):
    """C-03 / R-304. The set stores `regime_timeline_id`, `return_set_id`, `state_grid` and `replay`.

    The illustration is built field by field from a named allowlist, so none of them travels — and the
    payload is checked rather than trusted, because the way one would arrive is a future edit copying
    `rates` through in one line.

    **Planted violation:** added `"rates": assumption_set.rates` to the illustration.
    `EngineArtefactWouldBeServed` was raised by the guard, naming four markers — the guard firing rather
    than this test noticing afterwards, which is the right order. Restored.
    """
    published()
    illustration = _illustrate(session, funded_goal, member)["illustration"]
    rendered = json.dumps(illustration)
    for marker in ("regime_timeline_id", "return_set_id", "state_grid", "state_to_scenario", "replay"):
        assert marker not in rendered, f"C-03: the illustration carries {marker!r}"
    # Non-vacuous: the set's markers really were available to leak.
    assert "regime_timeline_id" in json.dumps(RATES)


def test_the_goal_payload_carries_the_illustration_and_no_completion_meter(session, member, funded_goal,
                                                                          published):
    """R-113 with figures present, which is when it gets hard.

    The old payload had no numbers in it at all, so R-113 was easy. Now that a goal returns francs, the
    check matters: no share of a target reached, no ratio, nothing a screen can render as a meter.
    """
    published()
    payload = list_goals(session, member_id=member.id)
    blob = json.dumps(payload)
    for forbidden in ("percent", "funded_ratio", "on_track", "progress", "completion", "shortfall_pct"):
        assert forbidden not in blob, f"R-113: the goal payload carries {forbidden!r}"

    goal = next(g for g in payload["goals"] if g["id"] == funded_goal.id)
    assert goal["illustration"]["assumption_set_id"]
    assert goal["illustration_unavailable_reason"] is None


# ============================================================ against the real published set


def test_the_illustration_works_on_the_set_the_developers_database_actually_holds(session, member,
                                                                                 funded_goal):
    """A69's real set, not a fixture. Skipped honestly when the database has none.

    `test_a_set_published_from_the_real_engines_matches_what_they_produced` does the same for the set
    itself. The point here is the consumer: a shape mismatch between what `compose` writes and what this
    module reads would be exactly the "blocker lifted and nothing propagated" defect again, one layer on.
    """
    from pathlib import Path
    from sqlalchemy import select as sa_select

    from eigentlich.db import make_engine, make_session_factory

    db_path = Path(__file__).resolve().parent.parent / "eigentlich.db"
    if not db_path.exists():
        pytest.skip("no development database on this machine")

    real_engine = make_engine(f"sqlite:///{db_path}")
    try:
        with make_session_factory(real_engine)() as real:
            live = real.execute(
                sa_select(AssumptionSet).order_by(AssumptionSet.effective_from.desc()).limit(1)
            ).scalar_one_or_none()
            if live is None:
                pytest.skip("no assumption set is published in the development database")
            fields = {
                "version": live.version,
                "effective_from": live.effective_from,
                "published_by": live.published_by,
                "rates": live.rates,
                "horizons": live.horizons,
                "inflation": live.inflation,
            }
    finally:
        real_engine.dispose()

    session.add(AssumptionSet(**fields))
    session.commit()

    illustration = _illustrate(session, funded_goal, member)["illustration"]
    assert illustration is not None, (
        f"the real published set {fields['version']} produced no illustration for a funded, priced, "
        f"growth-role goal — which is the defect this module was written to close"
    )
    assert illustration["assumption_set_version"] == fields["version"]
    assert illustration["by_role"][0]["assumption_set_role"] == "gain"
    assert illustration["values_unit"] == "annualised_decimal"
    assert illustration["horizon"]["published_years"] == 1.0
    rendered = json.dumps(illustration)
    for marker in ("regime_timeline_id", "return_set_id", "state_grid", "replay"):
        assert marker not in rendered, f"C-03: the real set leaked {marker!r} into an illustration"
