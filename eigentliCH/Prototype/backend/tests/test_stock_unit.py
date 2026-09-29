"""A member can state what they HAVE, and a liability cannot be stored ambiguously. 1 September 2026.

**The gap.** `MAGNITUDE_UNITS` was `("chf_per_year", "share_of_total")` — a flow and a fraction, and no unit
for a stock of money. "CHF 45,000 in collectibles" and "CHF 2,000 in cash" were unrepresentable, and four
engine inputs (`W_R`, `W_L`, `initial_wealth`, `D`) plus the whole Life Balance Sheet hung on that absence.
`services/engine_inputs.NO_WEALTH_STOCK` argued that capitalising a flow needs an unpublished rate, which
was true and was doing the work that a third entry in a tuple should have been doing.

**Two decisions this file holds.** `chf` as the stock unit, dimensional like its siblings — and a liability
as its **own field**, `Position.stock_kind`, rather than a negative magnitude. The arguments are in
`models/plan.py`; what is here is the enforcement, in both directions and at both layers.

**Every guard below was verified by planting the violation, watching it fail, and restoring.** What was
planted is recorded against each test. Several of them are assertions that something is ABSENT — a
liability not netted into wealth, a rate not applied to a flow, a figure not defaulted to zero — and an
absence assertion proves nothing unless the thing was reachable, so each one pins the other end first.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from eigentlich.models import (
    ASSET,
    AssumptionSet,
    FLOW_UNIT,
    Goal,
    LIABILITY,
    MAGNITUDE_UNITS,
    Position,
    SHARE_UNIT,
    STOCK_KINDS,
    STOCK_UNIT,
    STOCK_UNITS,
)
from eigentlich.services import mutate_plan
from eigentlich.services.engine_inputs import gap_report, plan_for, stated_stocks
from eigentlich.services.grid import role_grid
from eigentlich.services.illustration import (
    CAVEATS,
    HELD_BALANCE_CAVEAT,
    NOT_COUNTED_REASONS,
    READ_FROM_HELD,
    READ_FROM_TARGET,
    RateAppliedToSomethingThatIsNotABalance,
    STATED_AMOUNT_CAVEAT,
    apply_rate,
    goal_illustration,
)
from eigentlich.services.plan import revise_position, validate_position_state
from conftest import session_overrides

PACKAGE = Path(__file__).resolve().parent.parent / "eigentlich"
TODAY = date(2026, 9, 1)
VINTAGE = date(2024, 12, 31)

#: The real published figures, trimmed. Same source as `tests/test_illustration.py`: the run A69 recorded.
RATES = {
    "values_unit": "annualised_decimal",
    "scenarios": ["crisis", "boom"],
    "role_profiles_by_scenario": {
        "gain": {"crisis": -0.35813067508492946, "boom": 0.09666666666666666},
        "protection": {"crisis": 0.22336290470907294, "boom": -0.0033333333333333327},
        "income": {"crisis": -0.0593, "boom": 0.041},
        "stabilisation": {"crisis": -0.02, "boom": 0.015},
    },
    "scenario_probabilities": {"crisis": 0.20957597100996284, "boom": 0.1228892482466044},
}
HORIZONS = {"return_estimation_years": 1.0, "scope": "Global"}

DECIDED = {"question": "Diese Position erfassen?", "choice": "Ja."}


# ============================================================ helpers


def _plan(session, member, *, goals=(), positions=(), link=None):
    with mutate_plan(session, member_id=member.id, question="Aufbau?", choice="Ja") as decision:
        for obj in [*positions, *goals]:
            session.add(obj)
        if link:
            link()
        decision.linked_positions.extend(positions)
        decision.linked_goals.extend(goals)
    session.commit()


def _position(session, member, **fields) -> Position:
    fields.setdefault("role", "growth")
    fields.setdefault("capital_type", "financial")
    fields.setdefault("label", "Depot")
    position = Position(member_id=member.id, **fields)
    _plan(session, member, positions=[position])
    return position


@pytest.fixture()
def published(session):
    def _publish(**overrides):
        record = AssumptionSet(
            version=overrides.pop("version", "v-test"),
            effective_from=overrides.pop("effective_from", VINTAGE),
            published_by="SIM Research, run 2026-08-30",
            rates=overrides.pop("rates", RATES),
            horizons=overrides.pop("horizons", HORIZONS),
            inflation=overrides.pop("inflation", None),
        )
        session.add(record)
        session.commit()
        return record

    return _publish


# ============================================================ the vocabulary
#
# The unit is `chf`, dimensionally: `chf_per_year` is francs per year, `share_of_total` is dimensionless,
# and francs full stop is `chf`. The name's one hazard is that it is a PREFIX of the flow's name, which the
# grep test below is about.


def test_the_stock_unit_is_in_the_vocabulary_and_the_flow_is_not_a_stock():
    """Both halves. The second is the one that would go wrong silently.

    **Planted violation:** added `FLOW_UNIT` to `STOCK_UNITS` in `models/plan.py`. This failed on the
    second assertion, and so did nine other tests in this file — which is the point of `STOCK_UNITS` being
    the single test every site performs. Restored.
    """
    assert STOCK_UNIT in MAGNITUDE_UNITS, "the member has no unit for a stock of money"
    assert STOCK_UNIT in STOCK_UNITS
    assert FLOW_UNIT not in STOCK_UNITS, "a flow is not a balance and a rate may not be applied to it"
    assert SHARE_UNIT not in STOCK_UNITS, "a fraction is not an amount"
    assert set(STOCK_UNITS) <= set(MAGNITUDE_UNITS)
    assert STOCK_KINDS == ("asset", "liability") and (ASSET, LIABILITY) == STOCK_KINDS


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_no_module_writes_the_stock_unit_as_a_literal():
    """`chf` is a prefix of `chf_per_year`, and that is the one real hazard of the name.

    A site that means "a stock in francs" and writes `unit.startswith("chf")` gets the flow too — which is
    the A105 defect (a market rate on a salary) with the capital-type check replaced by a unit check.
    `STOCK_UNITS` exists so no call site needs the literal at all, and this is what keeps it that way.

    Scanned over the AST rather than as text, so a docstring EXPLAINING the hazard is not mistaken for the
    hazard — the same false-positive class as the C-03 import check, which used to fail a module for a
    comment saying what it must not import. Exact equality, not `in`, for the same reason: prose mentioning
    `chf_per_year` is prose.

    **Planted violation:** changed `illustration.apply_rate` to test `unit != "chf"` instead of
    `unit not in STOCK_UNITS`. This failed naming `services/illustration.py`. Restored.
    """
    #: Where the four letters may appear, each with its reason. An allowlist rather than a scope, in the
    #: shape `PERMITTED_FLOATS` uses in `test_constraints.py`: a scan narrowed to "the modules that deal
    #: with units" stops covering the module that starts dealing with them tomorrow.
    allowed = {
        # Defines `STOCK_UNIT`. Somewhere has to.
        "models/plan.py",
        # A German abbreviation in the sentence-splitter's stopword list ("CHF 45'000.- ist ..."), beside
        # `bzw`, `ca` and `inkl`. Nothing to do with a magnitude unit, and renaming the unit would not
        # touch it.
        "services/know.py",
    }
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        if relative in allowed:
            continue
        if STOCK_UNIT in _string_constants(path):
            offenders.append(relative)

    assert not offenders, (
        f"these modules write {STOCK_UNIT!r} as a literal: {offenders}. Use `STOCK_UNITS` — the literal is "
        f"a prefix of {FLOW_UNIT!r}, and the site that reaches for one reaches for `startswith` next."
    )


def test_the_scan_above_can_see_a_literal():
    """The grep is only worth something if it finds one. Non-vacuous half, checked on the file that is
    ALLOWED to hold the literal: `models/plan.py` really does contain it, so the scan is looking at
    something rather than at nothing."""
    assert STOCK_UNIT in _string_constants(PACKAGE / "models" / "plan.py")


# ============================================================ the store refuses an ambiguous liability
#
# Three rules, held by two CHECK constraints on `positions`. These go through the ORM to the storage layer
# on purpose: the service refuses first (below) and this is what holds for a caller that went round it.


def test_a_franc_stock_cannot_be_stored_without_a_side_of_the_balance_sheet(session, member):
    """`ck_positions_stock_kind_iff_stock`, forward direction.

    There is no default. A default would file every unmarked debt as an asset of the same size, silently,
    which is the ambiguity the field was chosen over a negative magnitude to prevent.

    **Planted violation:** removed `ck_positions_stock_kind_iff_stock` from `Position.__table_args__`. The
    45,000 was stored with `stock_kind` NULL and this failed on the missing raise. Restored.
    """
    with pytest.raises(IntegrityError):
        _position(session, member, label="Sammlung", magnitude=45_000.0, magnitude_unit=STOCK_UNIT)
    session.rollback()


def test_a_flow_cannot_be_marked_as_a_liability(session, member):
    """`ck_positions_stock_kind_iff_stock`, reverse direction — and it is the direction that matters.

    Without it a member could carry `magnitude_unit='chf_per_year', stock_kind='liability'`: an annual flow
    with a side of a balance sheet, which `engine_inputs.stated_stocks` would have to decide what to do
    with. It decides nothing, because the state cannot exist.

    **Planted violation:** rewrote the constraint as the one-directional
    `stock_kind IS NULL OR magnitude_unit IS NOT NULL`. The flow-plus-liability row was accepted and this
    failed. Restored.
    """
    with pytest.raises(IntegrityError):
        _position(
            session,
            member,
            label="Lohn",
            magnitude=92_000.0,
            magnitude_unit=FLOW_UNIT,
            stock_kind=LIABILITY,
        )
    session.rollback()


def test_a_negative_franc_stock_is_refused(session, member):
    """`ck_positions_stock_is_not_negative`. **This is the whole debt decision, enforced.**

    A liability is `magnitude=350000, stock_kind='liability'` and there is no second way to say it. Leaving
    a negative magnitude reachable would restore exactly the encoding the field replaced, and then the two
    would disagree about what `-350000` with `stock_kind='asset'` means.

    **Planted violation:** dropped the constraint. `-350000.0` stored as an asset, `stated_stocks` returned
    `financial_assets=-350000.0`, and `W_R` went negative — a household with negative financial capital and
    `D` absent. This failed on the missing raise. Restored.
    """
    with pytest.raises(IntegrityError):
        _position(
            session,
            member,
            label="Hypothek",
            magnitude=-350_000.0,
            magnitude_unit=STOCK_UNIT,
            stock_kind=ASSET,
        )
    session.rollback()


def test_the_store_accepts_the_two_shapes_that_are_meant_to_exist(session, member):
    """Non-vacuous half of the three above: the constraints refuse what they mean to refuse and nothing
    else. An asset stock and a liability stock both store, and both keep their own side."""
    asset = _position(
        session, member, label="Sammlung", magnitude=45_000.0, magnitude_unit=STOCK_UNIT,
        stock_kind=ASSET,
    )
    debt = _position(
        session, member, role="stabilisation", label="Hypothek", magnitude=350_000.0,
        magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY,
    )
    assert (asset.magnitude, asset.stock_kind) == (45_000.0, ASSET)
    assert (debt.magnitude, debt.stock_kind) == (350_000.0, LIABILITY)


# ============================================================ the service refuses first, with a sentence


@pytest.mark.parametrize(
    "state, expected",
    [
        ({"magnitude": 45_000.0, "magnitude_unit": STOCK_UNIT, "stock_kind": None}, "either owned or owed"),
        (
            {"magnitude": 92_000.0, "magnitude_unit": FLOW_UNIT, "stock_kind": LIABILITY},
            "belongs to a magnitude stated in",
        ),
        (
            {"magnitude": -1.0, "magnitude_unit": STOCK_UNIT, "stock_kind": LIABILITY},
            "is not negative",
        ),
        (
            {"magnitude": 45_000.0, "magnitude_unit": STOCK_UNIT, "stock_kind": "owed"},
            "unknown stock_kind",
        ),
    ],
)
def test_the_service_refuses_every_ambiguous_state_with_a_sentence(state, expected):
    """The same three rules one layer up, so a member gets a sentence rather than a constraint name.

    Both layers exist deliberately: `api/main.py` and `services/plan.py` used to carry two copies of the
    unit list, and this is the one function both now call. If the two layers ever disagree the store wins
    and the member sees `ck_positions_stock_kind_iff_stock`, which is the failure this is the fix for.

    **Planted violation:** deleted the `_validate_stock(after)` call from `validate_position_state`. All
    four cases came back with no raise and this failed four times; the create route then 500'd on the
    IntegrityError instead of answering 422. Restored.
    """
    base = {
        "role": "growth",
        "capital_type": "financial",
        "label": "Depot",
        "description": None,
        "time_basis": None,
        "liquidity": None,
        "started_on": None,
        "tags": {},
    }
    with pytest.raises(ValueError, match=expected):
        validate_position_state({**base, **state})


def test_the_validator_accepts_the_states_that_are_meant_to_exist():
    """Non-vacuous half. Four legitimate shapes pass, so the refusals above are refusals of something."""
    base = {
        "role": "growth",
        "capital_type": "financial",
        "label": "Depot",
        "description": None,
        "time_basis": None,
        "liquidity": None,
        "started_on": None,
        "tags": {},
    }
    for state in (
        {"magnitude": None, "magnitude_unit": None, "stock_kind": None},
        {"magnitude": 92_000.0, "magnitude_unit": FLOW_UNIT, "stock_kind": None},
        {"magnitude": 45_000.0, "magnitude_unit": STOCK_UNIT, "stock_kind": ASSET},
        {"magnitude": 350_000.0, "magnitude_unit": STOCK_UNIT, "stock_kind": LIABILITY},
    ):
        validate_position_state({**base, **state})


def test_changing_the_unit_and_forgetting_the_side_is_refused_on_the_edit_path(session, member):
    """`validate_position_state` checks the state a revision would LEAVE the position in, not the fields it
    names, and the stock unit is the sharpest case of why.

    A member turning a flow into a balance sends `magnitude_unit: "chf"` and nothing else. The merged state
    then has a stock with no side of the balance sheet — a state the CHECK constraint refuses — so the
    service refuses first, naming the field the member has to add.

    **Planted violation:** made `_validate_stock` read the `changes` dict instead of the merged state. The
    revision was accepted, the flush hit `ck_positions_stock_kind_iff_stock`, and the 422 became a 500.
    Restored.
    """
    position = _position(
        session, member, role="income", capital_type="human", label="Lohn",
        magnitude=92_000.0, magnitude_unit=FLOW_UNIT,
    )
    with pytest.raises(ValueError, match="either owned or owed"):
        revise_position(
            session,
            member_id=member.id,
            position_id=position.id,
            changes={"magnitude_unit": STOCK_UNIT},
            **DECIDED,
        )
    session.rollback()

    # And the same revision WITH the side is accepted, so the refusal above is not a refusal of the act.
    result = revise_position(
        session,
        member_id=member.id,
        position_id=position.id,
        changes={"magnitude_unit": STOCK_UNIT, "stock_kind": ASSET},
        **DECIDED,
    )
    session.commit()
    assert result["changed"] == ["magnitude_unit", "stock_kind"]


# ============================================================ one validator, not two


def test_the_create_route_no_longer_keeps_its_own_copy_of_the_unit_list():
    """The documented failure mode: two lists that must agree, maintained separately.

    `api/main.py` used to test `body.magnitude_unit not in MAGNITUDE_UNITS` itself, beside
    `services/plan.py` doing the same. Adding a unit is exactly the edit that hits it — a member offered
    `chf` on `POST` and refused it on `PATCH`, with no test able to see the difference because each half
    was checked against itself. Checked over the AST so the comment explaining the history does not count
    as the history.

    **Planted violation:** put the `if body.magnitude_unit is not None and body.magnitude_unit not in
    MAGNITUDE_UNITS` check back into `create_position`. This failed naming the comparison. Restored.
    """
    source = (PACKAGE / "api" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    create = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_position"
    )
    names = {n.id for n in ast.walk(create) if isinstance(n, ast.Name)}
    assert "MAGNITUDE_UNITS" not in names, (
        "create_position enumerates the units again. It calls validate_position_state, which is the same "
        "function the edit path calls; a second list here is the drift this route was fixed for."
    )
    assert "validate_position_state" in names, "the create route validates nothing shared"


# ============================================================ the API, end to end


@pytest.fixture()
def client(api_session, tmp_path, monkeypatch, fast_kdf):
    """The real application against the fixture database. Yields `(client, member_id)`."""
    from eigentlich.api import main, remainder
    from eigentlich.services import VaultStore
    from eigentlich.services.auth import login, register_with_credentials

    store = VaultStore(tmp_path / "vault")
    monkeypatch.setattr(main, "VAULT_STORE", store)

    password = "ein ziemlich langes passwort"
    member, _ = register_with_credentials(
        api_session,
        email="stock@example.ch",
        password=password,
        age_at_registration=41,
        display_name="Stock Member",
    )
    api_session.commit()
    _, token = login(api_session, email="stock@example.ch", password=password)
    api_session.commit()

    overrides = session_overrides(api_session)
    overrides[remainder.get_store] = lambda: store
    main.app.dependency_overrides.update(overrides)
    try:
        with TestClient(main.app) as test_client:
            test_client.headers["Authorization"] = f"Bearer {token}"
            yield test_client, member.id
    finally:
        for key in overrides:
            main.app.dependency_overrides.pop(key, None)


def _create(client, **fields):
    body = {
        "role": "growth",
        "capital_type": "financial",
        "label": "Depot",
        "tags": {},
        **DECIDED,
        **fields,
    }
    return client.post("/api/positions", json=body)


def test_the_api_accepts_a_stock_and_a_liability_and_refuses_an_ambiguous_one(client):
    """`POST /api/positions`. The member can now say what they have, and what they owe, and cannot say
    something in between.

    **Planted violation:** removed `stock_kind=body.stock_kind` from the `Position(...)` construction in
    `create_position`. The 201 became a 500 on `ck_positions_stock_kind_iff_stock` — the field was accepted
    at the edge and dropped on the way in, which is the shape of defect that reads as "eigentliCH lost my
    entry". Restored.
    """
    test_client, member_id = client

    held = _create(test_client, label="Sammlung", magnitude=45_000.0, magnitude_unit=STOCK_UNIT,
                   stock_kind=ASSET)
    assert held.status_code == 201, held.text

    owed = _create(test_client, role="stabilisation", label="Hypothek", magnitude=350_000.0,
                   magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY)
    assert owed.status_code == 201, owed.text

    ambiguous = _create(test_client, label="Bargeld", magnitude=2_000.0, magnitude_unit=STOCK_UNIT)
    assert ambiguous.status_code == 422
    assert "owned or owed" in ambiguous.json()["detail"]

    negative = _create(test_client, label="Schulden", magnitude=-2_000.0,
                       magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY)
    assert negative.status_code == 422
    assert "not negative" in negative.json()["detail"]

    unknown = _create(test_client, label="X", magnitude=1.0, magnitude_unit="chf_per_month",
                      stock_kind=ASSET)
    assert unknown.status_code == 422


def test_the_edit_route_can_correct_which_side_a_balance_is_on(client):
    """A member who filed a mortgage as a holding has to be able to say so, and it is one statement about
    one position rather than two routes.

    **Planted violation:** removed `"stock_kind"` from `POSITION_REVISABLE_FIELDS`. The PATCH came back 422
    "not a revisable field" and this failed — leaving a member able to CREATE a debt filed as an asset and
    unable to correct it, which is worse than not having the field.
    """
    test_client, member_id = client
    created = _create(test_client, role="stabilisation", label="Hypothek", magnitude=350_000.0,
                      magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]

    fixed = test_client.patch(
        f"/api/positions/{position_id}", json={"stock_kind": LIABILITY, **DECIDED}
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["changed"] == ["stock_kind"]

    grid = test_client.get("/api/positions").json()
    rendered = [p for cell in grid["cells"] for p in cell["positions"] if p["id"] == position_id]
    assert rendered and rendered[0]["stock_kind"] == LIABILITY


def test_the_vocabulary_route_serves_every_unit_the_api_accepts(client):
    """The third site the unit list was maintained at, by not being here.

    `liquidity_bands` has been served from the server's own constant since R-031, for the reason
    `services/grid.py` states — one copy, so a payload cannot carry a second that drifts. The magnitude
    units had no route at all, so the client kept a hand-written pair, and a third unit is what exposes it.
    A client reading this cannot offer a unit the server refuses or miss one it accepts.

    **Planted violation:** hardcoded `["chf_per_year", "share_of_total"]` in the route, as the client's own
    list still reads. This failed on the missing `chf`. Restored.
    """
    test_client, _ = client
    payload = test_client.get("/api/goal-templates").json()
    assert payload["magnitude_units"] == list(MAGNITUDE_UNITS)
    assert payload["stock_kinds"] == list(STOCK_KINDS)
    assert STOCK_UNIT in payload["magnitude_units"], (
        "a form built from this route cannot offer the stock unit, so the member still cannot state what "
        "they have"
    )


def test_the_grid_reports_the_side_of_the_balance_sheet(session, member):
    """`GET /api/positions` carries every field the edit route can change — the rule `liquidity` proved was
    needed. A member cannot be shown a form for a field whose current value they cannot read, and for this
    field the consequence is sharper: a debt whose side the grid did not report would render as a holding.

    **Planted violation:** returned `position.stock_kind or "asset"` from `_position_payload`, which is the
    tempting one-liner for a nullable field. The liability came back as an asset and this failed. Restored.
    """
    _position(session, member, role="stabilisation", label="Hypothek", magnitude=350_000.0,
              magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY)
    _position(session, member, role="income", capital_type="human", label="Lohn",
              magnitude=92_000.0, magnitude_unit=FLOW_UNIT)

    payloads = {
        p["label"]: p for cell in role_grid(session, member_id=member.id)["cells"]
        for p in cell["positions"]
    }
    assert payloads["Hypothek"]["stock_kind"] == LIABILITY
    assert payloads["Lohn"]["stock_kind"] is None, (
        "a flow has no side of a balance sheet, and a default of 'asset' would invent one"
    )


# ============================================================ onboarding: the unit is READ, not typed


def test_onboarding_reads_the_declared_unit_and_checks_it():
    """It was a hardcoded `"chf_per_year"` beside a comment saying the unit came from the question's
    declaration. It did not, and this was the only write path that stored a unit without validating it.

    **Planted violation:** made the content declaration `"chf_per_month"` via monkeypatched
    `onboarding_question`. `declared_magnitude_unit` raised `OnboardingIncomplete` naming the unit, where
    before the change the literal would have been stored regardless of what the file said. Restored.
    """
    from eigentlich.services.onboarding import declared_magnitude_unit

    assert declared_magnitude_unit() in MAGNITUDE_UNITS
    assert declared_magnitude_unit() not in STOCK_UNITS, (
        "the income question would file a salary as a balance, which puts a wage in front of every market "
        "rate that may be applied to one"
    )


@pytest.mark.parametrize("declared", ["chf_per_month", STOCK_UNIT, None])
def test_onboarding_refuses_a_unit_the_build_does_not_accept_or_that_is_a_stock(monkeypatch, declared):
    """Both refusals, and the second is the interesting one. An unknown unit is a broken content file; a
    STOCK unit on the income question is the A105 defect at the point of entry, and it would look correct
    to whoever made the edit."""
    from eigentlich.services import onboarding as onboarding_service

    monkeypatch.setattr(
        onboarding_service,
        "onboarding_question",
        lambda key: {"key": key, "fills": {"magnitude_unit": declared}},
    )
    with pytest.raises(onboarding_service.OnboardingIncomplete):
        onboarding_service.declared_magnitude_unit()


# ============================================================ the engine inputs
#
# `stated_stocks` is the only place a magnitude is read as an amount. Everything below is about what it
# refuses to do with one.


def _stock_plan(session, member):
    """The shape the audit's gap list was about: two asset stocks, a salary, a mortgage, and training."""
    positions = [
        Position(member_id=member.id, role="growth", capital_type="financial", label="Sammlung",
                 magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET),
        Position(member_id=member.id, role="stabilisation", capital_type="financial", label="Bargeld",
                 magnitude=2_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET),
        Position(member_id=member.id, role="income", capital_type="human", label="Lohn",
                 magnitude=92_000.0, magnitude_unit=FLOW_UNIT),
        Position(member_id=member.id, role="stabilisation", capital_type="financial", label="Hypothek",
                 magnitude=350_000.0, magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY),
        Position(member_id=member.id, role="income", capital_type="human", label="Ausbildung",
                 magnitude=500_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET),
    ]
    _plan(session, member, positions=positions)
    return positions


def test_a_liability_is_never_netted_into_wealth(session, member):
    """**The reason `stock_kind` is a field and not a sign.** `W_R` and `D` are two engine inputs, and a
    negative magnitude would have netted them into one number the engine cannot take apart again.

    **Planted violation:** changed `stated_stocks` to add liabilities into `financial` with a minus sign,
    which is precisely what the negative-magnitude design would have produced. `W_R` came back as
    `-303000.0` and `D` was absent; this failed on both. Restored.
    """
    positions = _stock_plan(session, member)
    stocks = stated_stocks(positions)

    assert stocks.financial_assets == 47_000.0, "the two asset stocks, and nothing else"
    assert stocks.liabilities == 350_000.0
    assert stocks.human_assets == 500_000.0

    payload = plan_for(
        "life_balance_sheet", member_id=member.id, positions=positions, today=TODAY
    ).payload
    assert payload["W_R"] == 47_000.0
    assert payload["D"] == 350_000.0
    assert payload["W_L"] == 500_000.0
    assert payload["W_R"] - payload["D"] not in (payload["W_R"], payload["D"]), (
        "netting would make one of these two the difference of the other"
    )


def test_a_flow_never_becomes_a_stock(session, member):
    """C-02, unchanged by the good news. A member with only a salary has stated no balance, and
    capitalising one still needs a discount rate nobody published.

    **Planted violation, and the first version of this test could not see it.** Dropping the
    `magnitude_unit not in STOCK_UNITS` filter from `stated_stocks` left this GREEN, because the
    `stock_kind` branch below it catches a flow too — a flow has no side of the balance sheet, so it
    matches neither `ASSET` nor `LIABILITY` and falls through. Two filters, one test, and the test was
    watching the wrong one.

    So the last block below hands `stated_stocks` the state the CHECK constraint makes unstorable: a
    flow WITH a side. It is reachable in exactly the way that matters — an unflushed object, a future
    migration that loses a constraint, a caller building positions by hand — and it is the only input
    that distinguishes the two filters. With the filter dropped, `W_R` came back as 92,000: a year's
    salary presented to the Life Balance Sheet as the household's financial capital. Restored.
    """
    positions = [
        Position(member_id=member.id, role="income", capital_type="human", label="Lohn", active=True,
                 magnitude=92_000.0, magnitude_unit=FLOW_UNIT),
        Position(member_id=member.id, role="growth", capital_type="financial", label="Anteil",
                 active=True, magnitude=0.4, magnitude_unit=SHARE_UNIT),
    ]
    _plan(session, member, positions=positions)

    stocks = stated_stocks(positions)
    assert stocks.financial_assets is None
    assert stocks.human_assets is None
    assert not stocks.any_stated

    plan = plan_for("life_balance_sheet", member_id=member.id, positions=positions, today=TODAY)
    assert "W_R" not in plan.payload and "W_L" not in plan.payload
    reason = next(gap.reason for gap in plan.absent if gap.name == "W_R")
    assert FLOW_UNIT in reason and "discount rate" in reason

    # **The input that isolates the unit filter from the stock_kind filter.** Not persisted, and it cannot
    # be: `ck_positions_stock_kind_iff_stock` refuses a flow with a side of a balance sheet. Handed straight
    # to `stated_stocks`, because the two filters are defence in depth and a test that only ever sees inputs
    # both of them reject cannot tell which one is doing the work.
    impossible = Position(
        member_id=member.id, role="income", capital_type="human", label="Lohn", active=True,
        magnitude=92_000.0, magnitude_unit=FLOW_UNIT, stock_kind=ASSET,
    )
    assert not stated_stocks([impossible]).any_stated, (
        "the unit filter is gone: an annual flow was summed as a balance because it carried a side of the "
        "balance sheet. A rate applied to that figure is A105 with a unit check instead of a capital check."
    )


def test_nothing_is_defaulted_to_zero(session, member):
    """A member who has stated no liability has not stated that they have no debt.

    `D = 0.0` is a claim about a household, and §12 calls a defaulted input a defect rather than a gap-fill.

    **Planted violation:** made `stated_stocks` return `0.0` instead of `None` for a kind nobody stated. The
    Life Balance Sheet received `W_R: 0.0, W_L: 0.0, D: 0.0` and reported itself COMPLETE for a member who
    had entered nothing at all. This failed on the payload keys being present. Restored.
    """
    plan = plan_for("life_balance_sheet", member_id=member.id, positions=[], today=TODAY)
    for name in ("W_R", "W_L", "D"):
        assert name not in plan.payload, f"{name} was defaulted"
        assert name in plan.missing("not_in_the_plan")
    assert 0 not in plan.payload.values() and 0.0 not in plan.payload.values()


def test_the_human_capital_stock_goes_to_W_L_and_never_to_W_R_or_initial_wealth(session, member):
    """R-121 / Principle 9 at the new layer. A member valuing their own training at 500,000 has stated a
    balance, and it is `W_L` — the engine's own human-capital input — and never part of a portfolio a market
    rate is applied to.

    **Planted violation:** removed the `capital_type` branch from `stated_stocks`, so every asset stock went
    to `financial`. `initial_wealth` came back as 547,000 — a trajectory engine about to grow somebody's
    education at a market rate — and this failed. Restored.
    """
    positions = _stock_plan(session, member)
    trajectory = plan_for(
        "s_curve_trajectory", member_id=member.id, positions=positions, today=TODAY
    ).payload
    assert trajectory["initial_wealth"] == 47_000.0
    assert trajectory["initial_wealth"] != 547_000.0

    scenario = plan_for(
        "scenario_generator", member_id=member.id, positions=positions, today=TODAY
    ).payload
    assert scenario["initial_wealth"] == 47_000.0


def test_initial_wealth_does_not_have_the_debt_subtracted_out_of_it(session, member):
    """A trajectory grows a portfolio at a return. Netting the mortgage out first and then growing the
    remainder is a claim that debt compounds like equity, and nobody published one. `D` is
    `life_balance_sheet`'s input and it stays there."""
    positions = _stock_plan(session, member)
    payload = plan_for(
        "s_curve_trajectory", member_id=member.id, positions=positions, today=TODAY
    ).payload
    assert payload["initial_wealth"] == 47_000.0
    assert payload["initial_wealth"] != 47_000.0 - 350_000.0
    assert "D" not in payload, "D belongs to the balance-sheet engine and is not a trajectory input"


def test_the_gap_reason_no_longer_blames_the_vocabulary(session, member):
    """A85's rule, applied to this module's own reasons: a payload may only give a reason that is still the
    reason.

    `NO_WEALTH_STOCK` said the plan "records Position.magnitude as chf_per_year (a flow) or share_of_total
    (a fraction), never a stock in francs". That sentence became false the moment `chf` shipped, and a
    member reading it would go looking for a field that already exists.

    **Planted violation:** restored the old `NO_WEALTH_STOCK` wording as the reason. This failed on the
    forbidden phrase. Restored.
    """
    plan = plan_for("life_balance_sheet", member_id=member.id, positions=[], today=TODAY)
    for gap in plan.absent:
        if gap.name not in ("W_R", "W_L", "D"):
            continue
        assert "never a stock in francs" not in gap.reason, (
            f"{gap.name} still says the plan cannot hold a stock: {gap.reason!r}"
        )
        assert STOCK_UNIT in gap.reason, "the reason must name the route the member now has"
        assert "stated none" in gap.reason or "stated no liability" in gap.reason


def test_the_gap_count_falls_once_the_member_states_what_they_have(session, member):
    """The measurable half. 21 gaps across the seven engines, 11 of them plan-blocking, with four of the
    eleven being the wealth stock this feature is about — `W_R`, `W_L`, `D` and `initial_wealth`, the last
    counted twice because two engines declare it.

    Both numbers are asserted, and the empty-plan case is asserted too, so a change that filled a gap by
    defaulting it would move the first number without moving the second.

    **Blocking was 12 until 3 September 2026.** `PlanVersion` landed and the Scenario Generator's
    `base_snapshot_id` stopped being `not_in_the_plan` — the build has a numbered baseline now, and the
    recorded reason ("prototype2 has no Snapshot") had become false. It is `supplied_by_the_caller`
    instead, the same kind as that engine's `field` and `to_value`, and caller-supplied gaps do not block.
    The TOTAL is unchanged at 21: the gap did not disappear, it was reclassified, which is exactly the
    distinction asserting both numbers exists to catch.
    """
    blocking = ("not_in_the_plan", "needs_an_unpublished_assumption")

    def counts(positions):
        report = gap_report(member_id=member.id, positions=positions, today=TODAY)
        return len(report), len([g for g in report if g["kind"] in blocking])

    assert counts([]) == (21, 11), "the pre-existing gap report; a member who has stated nothing"
    assert counts(_stock_plan(session, member)) == (16, 6), (
        "stating stocks fills W_R, W_L, D and initial_wealth (twice): five gap entries, all of them "
        "plan-blocking"
    )


# ============================================================ the illustration: a rate, and a balance


def test_a_rate_cannot_be_applied_to_anything_that_is_not_a_balance():
    """**The A105 class of defect, closed at the signature.** A105 applied an income rate to a salary
    because nothing read `capital_type`; this would apply a market rate to an annual flow because nothing
    read `magnitude_unit`. Same shape, same reach.

    `apply_rate` is the only multiplication in `services/illustration.py` and it takes the unit as a
    required keyword, so a caller cannot multiply without saying what they are multiplying.

    **Planted violation:** changed `apply_rate` to `return amount * rate` with the check removed. This
    failed on both flow cases, and `test_a_flow_funding_a_goal_is_not_counted_toward_the_balance` then
    showed what the removal buys: `change_chf` on a 92,000 salary. Restored.
    """
    for unit in (FLOW_UNIT, SHARE_UNIT, "chf_per_month", ""):
        with pytest.raises(RateAppliedToSomethingThatIsNotABalance):
            apply_rate(92_000.0, -0.0593, unit=unit)

    # Non-vacuous: the arithmetic it guards really is available for a balance.
    assert apply_rate(45_000.0, -0.0593, unit=STOCK_UNIT) == 45_000.0 * -0.0593


def _goal(session, member, *, amount, positions):
    goal = Goal(
        member_id=member.id, name="Wohneigentum", target_amount=amount,
        target_date=TODAY + timedelta(days=1500),
    )
    _plan(
        session, member, goals=[goal], positions=positions,
        link=lambda: goal.funded_by.extend(positions),
    )
    return goal


def test_the_projection_uses_the_stated_balance_when_there_is_one(session, member, published):
    """What the stock unit changed about an honest illustration.

    The caveat `the_amount_is_stated_by_the_member_and_is_not_a_holding` was a compromise forced by there
    being no unit for a holding. Where the member has stated one, the rate is applied to THAT, each role on
    its own balance, and the caveat is replaced rather than left standing — a caveat that is false is worse
    than no caveat.

    **Planted violation:** left `on_holdings` hardcoded to `False`. The basis came back as the 250,000
    target amount with the old caveat, and this failed on `read_from`. Restored.
    """
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    cash = Position(member_id=member.id, role="stabilisation", capital_type="financial",
                    label="Bargeld", magnitude=2_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    goal = _goal(session, member, amount=250_000, positions=[depot, cash])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    illustration = outcome["illustration"]

    assert illustration["basis"]["read_from"] == READ_FROM_HELD
    assert illustration["basis"]["amount_chf"] == 47_000.0
    assert illustration["basis"]["amount_chf"] != 250_000, "the target amount is not a holding"

    by_role = {entry["role"]: entry for entry in illustration["by_role"]}
    assert by_role["growth"]["amount_chf"] == 45_000.0
    assert by_role["stabilisation"]["amount_chf"] == 2_000.0
    crisis = next(s for s in by_role["growth"]["scenarios"] if s["scenario"] == "crisis")
    rate = RATES["role_profiles_by_scenario"]["gain"]["crisis"]
    assert crisis["change_chf"] == 45_000.0 * rate
    assert crisis["rate_applied_to_unit"] == STOCK_UNIT

    assert HELD_BALANCE_CAVEAT in illustration["caveats"]
    assert STATED_AMOUNT_CAVEAT not in illustration["caveats"]
    assert len(illustration["caveats"]) == len(CAVEATS), "one caveat was swapped, not added"


def test_without_a_stated_balance_nothing_changes(session, member, published):
    """The other side of the switch, so the change is scoped rather than sweeping. A goal funded by a
    position that states no balance is still projected on the member's target amount, with the caveat that
    says so."""
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot")
    goal = _goal(session, member, amount=250_000, positions=[depot])

    illustration = goal_illustration(
        session, goal, member_id=member.id, today=TODAY
    )["illustration"]
    assert illustration["basis"]["read_from"] == READ_FROM_TARGET
    assert illustration["basis"]["amount_chf"] == 250_000
    assert illustration["caveats"] == list(CAVEATS)


def test_a_flow_funding_a_goal_is_not_counted_toward_the_balance(session, member, published):
    """**The defect this module would have shipped.** `services/onboarding.py` gives every member a
    `chf_per_year` position and the containers form offers it in the funding multiselect, so a goal funded
    by an annual figure is one click off the default path — the same reach A105 had.

    The position still names a role, so it is NOT in `excluded_from_the_projection`: it is only its amount
    that cannot be used, and it says so in its own list with its own key.

    **Planted violation:** made `_held_balances` count every magnitude regardless of unit. The goal was
    projected on a 92,000 balance that is a yearly wage, with `change_chf` beside it, and this failed on
    both the basis and the empty not-counted list. Restored.
    """
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    flow = Position(member_id=member.id, role="protection", capital_type="financial",
                    label="Prämie", magnitude=4_800.0, magnitude_unit=FLOW_UNIT)
    share = Position(member_id=member.id, role="stabilisation", capital_type="financial",
                     label="Anteil", magnitude=0.4, magnitude_unit=SHARE_UNIT)
    silent = Position(member_id=member.id, role="income", capital_type="financial", label="Konto")
    goal = _goal(session, member, amount=250_000, positions=[depot, flow, share, silent])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    illustration = outcome["illustration"]

    assert illustration["basis"]["amount_chf"] == 45_000.0, "only the balance was counted"
    reasons = {e["position_id"]: e["reason"] for e in outcome["not_counted_toward_the_held_balance"]}
    assert reasons[flow.id] == "a_flow_is_not_a_balance"
    assert reasons[share.id] == "a_share_of_a_total_is_not_an_amount"
    assert reasons[silent.id] == "no_magnitude_stated"
    assert depot.id not in reasons
    assert set(reasons.values()) <= set(NOT_COUNTED_REASONS)

    # The flow's own figure never appears, under any name.
    rendered = str(outcome)
    assert "4800.0" not in rendered.replace("4_800", ""), "the premium was projected"

    # And they are NOT reported as excluded from the projection: they contributed their roles.
    assert outcome["excluded_from_the_projection"] == []
    assert {entry["role"] for entry in illustration["by_role"]} >= {"growth"}


def test_a_liability_funding_a_goal_is_neither_projected_nor_netted(session, member, published):
    """A mortgage is a real balance in francs, so nothing dimensional stops the arithmetic — which is why
    the refusal has to be deliberate rather than a side effect of the unit check.

    A market rate on a mortgage is a claim that debt grows like equity. And it is not subtracted from the
    basis either: that would grow a netted figure at an equity rate, which is the same claim with a minus
    sign in front of it.

    **Planted violation:** treated `LIABILITY` as an asset in `_held_balances`. The basis became 395,000 —
    a member's mortgage projected as their savings — and this failed. Then planted the netting version
    (`-= magnitude`), which gave a basis of -305,000 and a crisis figure of +109,000; failed too. Restored.
    """
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    debt = Position(member_id=member.id, role="growth", capital_type="financial", label="Hypothek",
                    magnitude=350_000.0, magnitude_unit=STOCK_UNIT, stock_kind=LIABILITY)
    goal = _goal(session, member, amount=250_000, positions=[depot, debt])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    illustration = outcome["illustration"]

    assert illustration["basis"]["amount_chf"] == 45_000.0
    assert illustration["basis"]["amount_chf"] != 395_000.0, "the mortgage was projected as a holding"
    assert illustration["basis"]["amount_chf"] != 45_000.0 - 350_000.0, "the mortgage was netted out"

    entry = next(
        e for e in outcome["not_counted_toward_the_held_balance"] if e["position_id"] == debt.id
    )
    assert entry["reason"] == "a_liability_is_not_projected_as_a_holding"
    assert entry["stock_kind"] == LIABILITY


def test_a_human_capital_balance_never_reaches_a_market_rate(session, member, published):
    """A105's guarantee, one layer further in. A member who values their own training at 500,000 has stated
    a balance in francs — dimensionally exactly what `apply_rate` accepts — and the published set estimated
    nothing over human capital.

    **This is the case the stock unit created and no earlier test could have caught**, because before it
    there was no way to put a franc balance on a human-capital position at all.

    **Planted violation:** removed the `capital_type != FINANCIAL_CAPITAL` skip from `_held_balances`. The
    training entered the basis, the `income` profile was applied to it, and this failed on the basis amount.
    Restored.
    """
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    training = Position(member_id=member.id, role="income", capital_type="human", label="Ausbildung",
                        magnitude=500_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    goal = _goal(session, member, amount=250_000, positions=[depot, training])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    assert outcome["illustration"]["basis"]["amount_chf"] == 45_000.0
    assert outcome["illustration"]["basis"]["capital_types_projected"] == ["financial"]

    # Reported once, in the list that means "excluded from every figure" — not twice.
    assert [e["position_id"] for e in outcome["excluded_from_the_projection"]] == [training.id]
    assert training.id not in {
        e["position_id"] for e in outcome["not_counted_toward_the_held_balance"]
    }

    # The income profile's crisis figure against that balance, absent under any name.
    forbidden = 500_000.0 * RATES["role_profiles_by_scenario"]["income"]["crisis"]
    assert str(forbidden) not in str(outcome), "the income rate reached the training balance"


def test_a_goal_the_member_never_priced_is_projectable_once_a_balance_is_stated(
    session, member, published
):
    """R-132's courage money, and what the stock unit changes about it. The arithmetic never needed the
    target amount — it needed a balance — so a goal with a purpose and no figure that is funded by a stated
    holding gets a range, and `the_goal_names_no_amount` would be a false reason sending the member to fill
    in a number that changes nothing."""
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    goal = _goal(session, member, amount=None, positions=[depot])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    assert outcome["illustration_unavailable_reason"] is None
    assert outcome["illustration"]["basis"]["amount_chf"] == 45_000.0

    # And a priceless goal funded by nothing statable still says so.
    bare = Position(member_id=member.id, role="protection", capital_type="financial", label="Konto")
    other = _goal(session, member, amount=None, positions=[bare])
    assert goal_illustration(session, other, member_id=member.id, today=TODAY)[
        "illustration_unavailable_reason"
    ] == "the_goal_names_no_amount"


def test_the_illustration_stops_naming_initial_wealth_as_a_gap_once_a_stock_is_stated(
    session, member, published
):
    """`no_trajectory_because` comes straight from the mapping layer, and the mapping layer needs the
    member's positions to answer honestly.

    **Planted violation:** removed `positions=positions` from the `plan_for` call in `_why_no_trajectory`.
    The illustration told a member who had entered 45,000 that no balance was stated — a derived reason that
    is false, which is the A85 defect this module was rebuilt to remove. This failed. Restored.
    """
    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    goal = _goal(session, member, amount=250_000, positions=[depot])

    gaps = {
        gap["input"]
        for gap in goal_illustration(session, goal, member_id=member.id, today=TODAY)[
            "illustration"
        ]["no_trajectory_because"]
    }
    assert "initial_wealth" not in gaps, (
        "the member has stated a balance and the payload still says none was stated"
    )
    assert "annual_return" in gaps, "the rate is still an unpublished assumption and still has to be said"


def test_no_ratio_between_the_balance_and_the_target_appears(session, member, published):
    """R-113 / R-006, at the moment it becomes hard. Until the stock unit there was no holding to compare a
    target against; now both numbers are in one payload and a completion meter is one division away.

    So the payload carries no ratio, no difference and no "still needed" — and this asserts the VALUES are
    absent as well as the names, because a share of a target under an innocent field name is the same meter.
    """
    import json

    published()
    depot = Position(member_id=member.id, role="growth", capital_type="financial", label="Depot",
                     magnitude=45_000.0, magnitude_unit=STOCK_UNIT, stock_kind=ASSET)
    goal = _goal(session, member, amount=250_000, positions=[depot])

    outcome = goal_illustration(session, goal, member_id=member.id, today=TODAY)
    # **Over field NAMES broken into their parts, not as a substring of the document.** The first version
    # of this test scanned the rendered JSON and failed on `"illustration"`, which contains `ratio` —
    # `illust-ratio-n`. That is the same false-positive class as the C-03 import check that used to fail a
    # module for a docstring, and it is worth recording because it took thirty seconds to produce here.
    def names(value):
        found = set()
        if isinstance(value, dict):
            for key, inner in value.items():
                found |= set(str(key).lower().split("_"))
                found |= names(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                found |= names(inner)
        return found

    parts = names(outcome)
    assert parts, "no field names were found, so this test proves nothing"
    for forbidden in ("percent", "ratio", "progress", "completion", "shortfall", "needed", "pct"):
        assert forbidden not in parts, f"R-113: the illustration carries a {forbidden!r} field"

    def leaves(value):
        if isinstance(value, bool) or value is None:
            return set()
        if isinstance(value, (int, float)):
            return {float(value)}
        if isinstance(value, dict):
            return set().union(*(leaves(v) for v in value.values())) if value else set()
        if isinstance(value, (list, tuple)):
            return set().union(*(leaves(v) for v in value)) if value else set()
        return set()

    found = leaves(outcome)
    assert found, "no numbers were found, so this test proves nothing"
    for meter in (45_000.0 / 250_000, 250_000 - 45_000.0, 45_000.0 / 250_000 * 100):
        assert meter not in found, f"R-113: a completion figure appeared: {meter}"


def test_no_module_compares_a_unit_against_a_string_that_is_not_a_unit():
    """The failure the scan above cannot see: the WRONG literal rather than the right one written wrongly.

    `test_no_module_writes_the_stock_unit_as_a_literal` finds a site that types `"chf"` where `STOCK_UNITS`
    belongs. It cannot find a site that types something which is not a unit at all — and on 21 September
    2026 `services/member_ground.py` shipped `magnitude_unit.startswith("flow")`. `FLOW_UNIT` is
    `chf_per_year`, so that test was never once true; the stock/flow split it was written to make was held
    up entirely by a `role == "income"` check beside it, and five positions in the development database
    were rendered to a language model as balances when they are yearly amounts.

    A comparison against a literal that no unit can ever equal is **silent**: it does not raise, it does
    not fail a type check, and it reads as though it works. That is what makes it worth a scan of its own.

    Scanned over the AST so that prose is not mistaken for code, exactly as the test above is.

    **Planted violation:** restored `startswith("flow")` in `member_ground._positions`. This failed naming
    that module and that string. Restored.
    """
    import ast

    interesting = {"magnitude_unit", "unit", "magnitude_units"}

    def _names(node):
        """Every unit-ish name this expression could be reading, seeing through the usual wrappers.

        **`or ""` is the wrapper that matters, because it is the one the real defect wore.** The original
        was `(position.magnitude_unit or "").lower().startswith("flow")`, and a first version of this scan
        looked only at `node.func.value` — which for that expression is a `BoolOp`, not an attribute — so
        it reported nothing. Planting the defect and watching this pass is how that was found, which is
        A20's rule doing its job on the test written to enforce A20's rule.
        """
        found = set()
        for inner in ast.walk(node):
            name = getattr(inner, "attr", None) or getattr(inner, "id", None)
            if name in interesting:
                found.add(name)
        return found

    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # `<...>.unit.startswith("x")` / `.endswith("x")`
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("startswith", "endswith")):
                names = _names(node.func.value)
                if not names:
                    continue
                name = sorted(names)[0]
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if not any(u.startswith(arg.value) for u in MAGNITUDE_UNITS):
                            offenders.append(
                                f"{path.relative_to(PACKAGE).as_posix()}: "
                                f"{name}.{node.func.attr}({arg.value!r})")

            # `<...>.unit == "x"` / `!= "x"`
            if isinstance(node, ast.Compare) and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                names = _names(node.left)
                if not names:
                    continue
                name = sorted(names)[0]
                for other in node.comparators:
                    if isinstance(other, ast.Constant) and isinstance(other.value, str):
                        if other.value not in MAGNITUDE_UNITS:
                            offenders.append(
                                f"{path.relative_to(PACKAGE).as_posix()}: "
                                f"{name} compared to {other.value!r}")

    assert not offenders, (
        "these sites compare a magnitude unit against a string no unit can equal, which is a test that "
        f"never fires: {offenders}. The units are {list(MAGNITUDE_UNITS)}; use the constants."
    )
