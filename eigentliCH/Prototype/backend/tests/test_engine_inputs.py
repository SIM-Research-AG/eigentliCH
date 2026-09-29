"""A39 — the mapping layer. `Position` and `Goal` into each engine's own input names, gaps left visible.

The tests that matter here are the ones that fail if somebody quietly fills a gap in. A39's rule is that
anything the plan cannot answer is left ABSENT and never defaulted, and a defaulted input is invisible
downstream — it arrives at an engine looking exactly like an answer. So the checks are structural:

  * every declared input is either filled or explicitly absent, with nothing falling between;
  * no payload key ever holds a wealth stock or a rate, because the plan holds neither;
  * an absent input is absent from the payload, not present as a zero, an empty string or a None.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.engines import DEFAULT_MARKET_SCOPE, UndeclaredInput, known_engines, load_manifest
from eigentlich.models import Goal, Position
from eigentlich.services import mutate_plan
from eigentlich.services.engine_inputs import (
    GAP_KINDS,
    PLAN_GAP_KINDS,
    AbsentInput,
    funding_liquidity,
    gap_report,
    horizon_years,
    plan_all,
    plan_for,
)

TODAY = date(2026, 8, 30)

#: Names that would be a wealth stock or a rate if they were ever filled. The plan holds neither.
NEVER_FILLED_FROM_THE_PLAN = ("W_L", "W_R", "D", "E", "initial_wealth", "annual_return")


@pytest.fixture()
def member_with_plan(session, member):
    """One dated, funded goal and one undated one. R-020: a plan of two positions is a full plan."""
    house = Goal(
        member_id=member.id,
        name="Wohneigentum",
        target_amount=250_000,
        target_date=date(2031, 6, 1),
    )
    courage = Goal(member_id=member.id, name="Mutgeld", template="courage_money")
    securities = Position(
        member_id=member.id,
        role="growth",
        capital_type="financial",
        label="Wertschriftendepot",
        liquidity="within_months",
        magnitude=12_000,
        magnitude_unit="chf_per_year",
    )
    craft = Position(
        member_id=member.id,
        role="income",
        capital_type="human",
        label="Anstellung als Ingenieurin",
        liquidity="immediate",
    )
    with mutate_plan(session, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        for obj in (house, courage, securities, craft):
            session.add(obj)
        house.funded_by.append(securities)
        decision.linked_positions.extend([securities, craft])
        decision.linked_goals.extend([house, courage])
    session.commit()
    return member, house, courage, [securities, craft]


# ============================================================ the shape of the mapping itself


def test_there_is_a_mapping_for_every_engine():
    """A39 says "one documented module". A mapping that covered five of seven would be a different thing."""
    assert set(plan_all(member_id="M-1", today=TODAY)) == set(known_engines())


@pytest.mark.parametrize("engine_name", sorted(known_engines()))
def test_every_declared_input_is_either_filled_or_explicitly_absent(engine_name):
    """The structural guarantee. Nothing falls between the two.

    This is the test that catches a new engine input being added to a manifest and forgotten here: it would
    be neither in the payload nor in the gap list, and a caller reading `absent` would believe the plan
    answered it.
    """
    plan = plan_for(engine_name, member_id="M-1", today=TODAY)
    declared = set(load_manifest(engine_name).inputs)
    accounted = set(plan.payload) | set(plan.missing())

    assert accounted == declared, (
        f"{engine_name}: unaccounted inputs {sorted(declared - accounted)}, "
        f"invented inputs {sorted(accounted - declared)}"
    )


@pytest.mark.parametrize("engine_name", sorted(known_engines()))
def test_a_payload_is_accepted_by_the_manifest(engine_name):
    """The mapping and the façade agree, checked rather than assumed.

    `call_engine` refuses an undeclared key (R-300). A builder that invented a name would raise there, on a
    machine with engines, in the middle of a run — this catches it here instead.
    """
    plan = plan_for(engine_name, member_id="M-1", today=TODAY)
    manifest = load_manifest(engine_name)
    undeclared = sorted(set(plan.payload) - set(manifest.inputs))
    assert not undeclared, f"{engine_name}: {undeclared}"


@pytest.mark.parametrize("engine_name", sorted(known_engines()))
def test_an_absent_input_is_absent_and_not_a_placeholder(engine_name):
    """A39. "Left explicitly ABSENT, never defaulted."

    An input recorded as absent must not also appear in the payload holding None, 0 or "". Each of those
    reads as an answer one layer down, which is the whole failure this rule exists to stop.
    """
    plan = plan_for(engine_name, member_id="M-1", today=TODAY)
    for name in plan.missing():
        assert name not in plan.payload, f"{engine_name}.{name} is recorded as absent AND present in the payload"


@pytest.mark.parametrize("engine_name", sorted(known_engines()))
def test_every_gap_carries_a_known_kind_and_a_real_reason(engine_name):
    """A gap list is only useful if a caller can act on it, which needs both halves."""
    plan = plan_for(engine_name, member_id="M-1", today=TODAY)
    for gap in plan.absent:
        assert gap.kind in GAP_KINDS
        assert len(gap.reason) > 40, f"{engine_name}.{gap.name} has no reason worth reading: {gap.reason!r}"
        assert gap.declared_as, f"{engine_name}.{gap.name} does not say what the engine expects"


def test_an_unknown_gap_kind_is_refused():
    """The four kinds are the vocabulary. A fifth invented at a call site would not be branchable."""
    with pytest.raises(ValueError):
        AbsentInput(engine="market_signal", name="scope", declared_as="str", kind="probably", reason="x")


def test_an_input_the_manifest_does_not_declare_cannot_be_recorded_as_absent():
    """The manifest is the authority in both directions (R-300)."""
    from eigentlich.services.engine_inputs import _Builder

    with pytest.raises(KeyError):
        _Builder("market_signal").leave_absent("inflation", "not_in_the_plan", "not an input of this engine")


# ============================================================ what is never filled


@pytest.mark.parametrize("engine_name", sorted(known_engines()))
def test_no_wealth_stock_and_no_rate_is_ever_filled_from_the_plan(engine_name, session, member_with_plan):
    """The single most important test in this file.

    Four engines want a wealth stock and one wants a return. `Position.magnitude` is a flow or a fraction
    with an explicit unit (A30), never a stock, and a return is an assumption under C-02. Run with a real,
    populated plan so this is not passing merely because there was nothing to read.
    """
    member, house, _courage, positions = member_with_plan
    plan = plan_for(engine_name, member_id=member.id, goal=house, positions=positions, today=TODAY)

    for name in NEVER_FILLED_FROM_THE_PLAN:
        assert name not in plan.payload, (
            f"{engine_name}.{name} was filled from the plan. It cannot have been read there — it is a wealth "
            f"stock or a rate, and A39 leaves those absent rather than deriving them"
        )


def test_a_return_is_always_an_unpublished_assumption(session, member_with_plan):
    """C-02. The rate never comes from the plan and never from application code — only from a published set."""
    member, house, _courage, positions = member_with_plan
    plan = plan_for("s_curve_trajectory", member_id=member.id, goal=house, positions=positions, today=TODAY)

    gap = next(g for g in plan.absent if g.name == "annual_return")
    assert gap.kind == "needs_an_unpublished_assumption"
    assert "AssumptionSet" in gap.reason


def test_the_life_balance_sheet_cannot_be_filled_at_all(session, member_with_plan):
    """The finding A13 created and A39 makes visible.

    The onboarding schema used to give a direct route into this engine's `state` field names. The rewritten
    plan records what a position is FOR and how quickly it becomes money, not what it is worth — so all four
    wealth inputs are absent, and only the household reference is filled.
    """
    member, house, _courage, positions = member_with_plan
    plan = plan_for("life_balance_sheet", member_id=member.id, goal=house, positions=positions, today=TODAY)

    assert plan.payload == {"household_id": member.id}
    assert set(plan.missing()) == {"W_L", "W_R", "D", "E"}
    assert all(gap.kind == "not_in_the_plan" for gap in plan.absent)
    assert not plan.complete
    # The positions were read, and what was found is reported rather than converted.
    assert any("active position" in note for note in plan.notes)


def test_the_optimiser_has_no_mandate_and_says_why(session, member_with_plan):
    """C-01. A Goal is not an investment mandate, and writing one from it would cross the boundary twice."""
    member, house, *_ = member_with_plan
    plan = plan_for("portfolio_optimiser", member_id=member.id, goal=house, today=TODAY)

    gap = next(g for g in plan.absent if g.name == "mandate")
    assert gap.kind == "not_in_the_plan"
    assert "C-01" in " ".join(plan.notes)
    assert not plan.complete


def test_the_score_engine_is_never_complete(session, member_with_plan):
    """A6 / C-07. Its history inputs are unanswerable here, and the engine would default `months_observed`.

    Incompleteness is the protection: a caller that only runs complete plans never reaches an engine that
    would score a household on twelve months nobody recorded.
    """
    member, *_ = member_with_plan
    plan = plan_for("score_engine", member_id=member.id, today=TODAY)

    assert not plan.complete
    assert "months_observed" in plan.missing("not_in_the_plan")
    assert "C-07" in " ".join(plan.notes)


# ============================================================ what the plan does answer


def test_a_dated_goal_fills_its_own_horizon(session, member_with_plan):
    """The member's date, turned into years. Arithmetic over what they typed, not an assumption."""
    member, house, _courage, positions = member_with_plan
    plan = plan_for("s_curve_trajectory", member_id=member.id, goal=house, positions=positions, today=TODAY)

    assert plan.payload["horizon_years"] == horizon_years(house, today=TODAY)
    assert plan.payload["target"] == house.target_amount
    assert plan.payload["household_id"] == member.id
    assert "horizon_years" not in plan.missing()


def test_an_undated_goal_leaves_the_horizon_absent(session, member_with_plan):
    """R-030: an undated goal is a legitimate state, so this is a finished plan rather than a broken one.

    The horizon is absent rather than defaulted, because any number here would be this layer deciding when
    the member needs their money.
    """
    member, _house, courage, positions = member_with_plan
    plan = plan_for("s_curve_trajectory", member_id=member.id, goal=courage, positions=positions, today=TODAY)

    assert "horizon_years" not in plan.payload
    assert "target" not in plan.payload
    assert {"horizon_years", "target"} <= set(plan.missing("not_in_the_plan"))
    assert horizon_years(courage, today=TODAY) is None


def test_a_past_target_date_is_negative_rather_than_clamped(session, member_with_plan):
    """Clamping to zero would tell an engine the goal is due today, which is not what the member said."""
    member, house, *_ = member_with_plan
    assert horizon_years(house, today=date(2035, 1, 1)) < 0


def test_funding_liquidity_is_reported_and_not_scored(session, member_with_plan):
    """R-031 has no thresholds, so this is a fact about the plan and not an input any engine takes."""
    member, house, _courage, _positions = member_with_plan
    assert funding_liquidity(house) == {"within_months": 1}
    plan = plan_for("s_curve_trajectory", member_id=member.id, goal=house, today=TODAY)
    assert any("funding liquidity" in note for note in plan.notes)


# ============================================================ the world engines


@pytest.mark.parametrize("engine_name", ("market_signal", "return_estimation"))
def test_the_world_engines_need_nothing_from_a_member(engine_name):
    """A35's premise. Their plans are complete with no member at all, which is why they can seed C-02."""
    plan = plan_for(engine_name, today=TODAY)
    assert plan.complete
    assert plan.payload["scope"] == DEFAULT_MARKET_SCOPE
    assert not any(gap.kind in PLAN_GAP_KINDS for gap in plan.absent)
    assert any("household-independent" in note for note in plan.notes)


def test_an_engine_default_is_left_to_the_engine():
    """`owned_by_the_engine` is a gap in this call, not a gap in the plan.

    Macro_Model publishes the seven-economy blend and its weights. Omitting the key lets that stand;
    writing one here would produce a Regime the estate never published.
    """
    plan = plan_for("market_signal", today=TODAY)
    assert set(plan.missing("owned_by_the_engine")) == {"economies", "blend_weight"}
    assert plan.complete


def test_the_returnset_takes_the_regime_from_the_run_that_produced_it():
    """A remembered id would check the ReturnSet against the wrong vintage."""
    without = plan_for("return_estimation", today=TODAY)
    assert "regime_id" in without.missing("supplied_by_the_caller")

    with_regime = plan_for("return_estimation", regime_id="REG-abc", today=TODAY)
    assert with_regime.payload["regime_id"] == "REG-abc"


def test_the_score_engine_takes_the_whole_regime_contract_not_its_id():
    """The engine reads `crisis_tail` off the reference, so an id would break inside it."""
    contract = {"regime_id": "REG-abc", "crisis_tail": 0.28}
    plan = plan_for("score_engine", member_id="M-1", regime=contract, today=TODAY)
    assert plan.payload["regime"] == contract


# ============================================================ the report


def test_the_gap_report_is_not_empty_and_reads_as_prose(session, member_with_plan):
    """A39: "return them as a named list so a caller can see what could not be filled and why."

    Not empty, and not passing vacuously — see A20. Every entry names an engine, an input and a reason.
    """
    member, house, _courage, positions = member_with_plan
    report = gap_report(member_id=member.id, goal=house, positions=positions, today=TODAY)

    assert len(report) > 10
    assert {entry["kind"] for entry in report} <= set(GAP_KINDS)
    for entry in report:
        assert entry["engine"] in known_engines()
        assert entry["input"]
        assert entry["reason"]


def test_a_plan_serialises_for_a_screen(session, member_with_plan):
    """R-302's shape at the mapping layer: a screen can render "not available" and say what is missing."""
    member, _house, courage, _positions = member_with_plan
    payload = plan_for("s_curve_trajectory", member_id=member.id, goal=courage, today=TODAY).as_dict()

    assert payload["complete"] is False
    assert payload["engine"] == "s_curve_trajectory"
    assert all(set(gap) == {"engine", "input", "declared_as", "kind", "reason"} for gap in payload["absent"])
