"""The Regime pane: population-level, readable before sign-in, and never an artefact. Item 5.

The claims worth testing are the ones that would be invisible if they were false: that it touches no member
data, that a nested model artefact cannot leak through it, and that an unpublished assumption set produces
an honest answer rather than a plausible one.
"""

from __future__ import annotations

from datetime import date

import pytest

from eigentlich.models import AssumptionSet
from eigentlich.services import regime as regime_service
from eigentlich.services.regime import read

TODAY = date(2026, 9, 4)


def _publish(session, **rates):
    published = AssumptionSet(
        version="test@1",
        effective_from=date(2026, 1, 1),
        published_by="SIM Research, run 2026-01-01",
        rates=rates,
        horizons={},
    )
    session.add(published)
    session.commit()
    return published


# ============================================================ nothing about anybody


def test_it_takes_no_member_and_reads_no_member_table():
    """The whole claim of the module, asserted over its source rather than trusted to the signature."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(regime_service))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
            assert "member_id" not in names, f"{node.name} takes a member id"
        if isinstance(node, ast.Name):
            assert node.id not in {"Member", "Position", "Goal", "VaultItem", "Household"}, (
                f"the regime read reaches for {node.id}"
            )


def test_the_payload_says_it_is_population_level(session):
    payload = read(session, on=TODAY)
    assert payload["population_level"] is True
    assert payload["carries_member_data"] is False


# ============================================================ a reading, never an artefact


def test_nested_model_material_is_dropped_and_scalars_are_kept(session):
    """C-03 / R-304: the ids travel and the artefacts do not.

    Dropped by SHAPE rather than by name, so a key added upstream is served if it is a reading and dropped
    if it is a piece of the model — with nobody maintaining a whitelist.
    """
    _publish(
        session,
        regime_current={
            "phase": "contraction",
            "confidence": 0.62,
            "as_of": "2026-08-31",
            "is_provisional": True,
            # Artefacts. Every one of these is a piece of the Fund Map or the Regime timeline.
            "state_grid": [[0.1, 0.2], [0.3, 0.4]],
            "role_profiles": {"gain": [0.07, -0.02]},
            "timeline": [{"month": "2026-01"}],
        },
        source={"market_signal": {"regime_id": "REG-1", "scope": "Global"}},
    )

    served = read(session, on=TODAY)["regime"]
    assert served == {
        "phase": "contraction",
        "confidence": 0.62,
        "as_of": "2026-08-31",
        "is_provisional": True,
    }
    for artefact in ("state_grid", "role_profiles", "timeline"):
        assert artefact not in served


def test_the_return_profiles_never_reach_the_payload(session):
    """The `rates` block carries the whole Fund Map beside the regime. None of it is passed through."""
    _publish(
        session,
        regime_current={"phase": "boom"},
        role_profiles_by_scenario={"gain": [0.08]},
        state_grid=[[1, 2]],
        scenario_probabilities={"boom": 0.3},
        source={"market_signal": {"regime_id": "REG-1"}},
    )
    blob = str(read(session, on=TODAY))
    for artefact in ("role_profiles_by_scenario", "state_grid", "scenario_probabilities"):
        assert artefact not in blob


def test_the_provenance_travels_so_a_public_figure_is_traceable(session):
    published = _publish(
        session,
        regime_current={"phase": "boom"},
        source={
            "market_signal": {
                "regime_id": "REG-99",
                "scope": "Global",
                "as_of": "2026-08-31",
                "model_version": "ms@2.1",
            }
        },
    )
    source = read(session, on=TODAY)["source"]
    assert source["regime_id"] == "REG-99"
    assert source["model_version"] == "ms@2.1"
    assert source["assumption_set_id"] == published.id
    assert source["published_by"].startswith("SIM Research")
    assert read(session, on=TODAY)["artefacts_served"] is False


# ============================================================ not available is an answer


def test_an_unpublished_assumption_set_is_reported_rather_than_invented(session):
    """R-302's shape. "A default rate is an invented rate wearing a different hat" — and on a public page
    it would be that defect with a larger audience."""
    payload = read(session, on=TODAY)

    assert payload["available"] is False
    assert payload["regime"] == {}
    assert payload["source"] is None
    assert "no assumption set is in effect" in payload["reason"]


def test_the_shape_is_the_same_whether_or_not_one_is_published(session):
    """A client renders one payload, not two. `available` is the branch, not the presence of a key."""
    absent = set(read(session, on=TODAY))
    _publish(session, regime_current={"phase": "boom"}, source={"market_signal": {}})
    present = set(read(session, on=TODAY))
    assert absent <= present
    assert "available" in absent and "available" in present


# ============================================================ over HTTP, with no token


@pytest.fixture()
def anonymous(api_session):
    """The whole application, over HTTP, with no token and no override of the member guard.

    Built like every other HTTP test in this suite (A11): the routers are mounted on one app and
    `get_session` is redirected at the fixture database. Nothing authenticates, which is the point.
    """
    from fastapi.testclient import TestClient

    from eigentlich.api.main import app
    from conftest import session_overrides

    app.dependency_overrides.update(session_overrides(api_session))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_route_answers_without_a_session(anonymous):
    """Item 5: "can be shown to anyone — including before sign-in"."""
    response = anonymous.get("/api/regime")
    assert response.status_code == 200
    body = response.json()
    assert body["population_level"] is True
    assert body["carries_member_data"] is False


def test_an_unpublished_set_is_a_200_and_not_a_500(anonymous):
    """An honest state of the world, not a broken server. A public page must not look broken when it is
    merely truthful."""
    response = anonymous.get("/api/regime")
    assert response.status_code == 200
    assert response.json()["available"] is False
