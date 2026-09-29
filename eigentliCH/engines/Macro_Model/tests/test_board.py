"""Tests for the control board endpoint, phase 1 of the battle plan.

Assembling an economy needs the network, so the live paths are not exercised here. What is tested is the
contract: that every lever the form offers is a parameter the endpoint accepts, that a bad control is a
readable result rather than a crash, and that the board's own front end cannot drift away from the API.
"""

import inspect

import pytest

fastapi = pytest.importorskip("fastapi", reason="the cockpit is optional")
from fastapi.testclient import TestClient  # noqa: E402

from macrofield.cockpit.server import STATIC_DIRECTORY, create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.fixture(scope="module")
def page() -> str:
    return (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")


def endpoint_signature():
    from macrofield.cockpit import server

    source = inspect.getsource(server.create_app)
    start = source.index("def scenario(")
    return source[start : source.index(") -> dict[str, Any]:", start)]


class TestContract:
    def test_it_refuses_before_assembly_with_a_readable_reason(self, client):
        payload = client.post("/api/scenario/us").json()
        assert payload["ok"] is False
        assert "assembled" in payload["error"]

    def test_a_malformed_control_path_names_the_valid_modes(self, client):
        """The board's most likely user error, so it must not surface as a stack trace."""
        client.post("/api/assemble/atlantis")  # ensures the cache is empty for a clean check
        payload = client.post("/api/scenario/us", params={"stimulus": "wibble:1>2@2027"}).json()
        assert payload["ok"] is False
        # Either it refuses on the control or on the missing assembly; both are readable.
        assert "assembled" in payload["error"] or "unknown control mode" in payload["error"]

    def test_every_form_lever_is_an_endpoint_parameter(self, page):
        """The form and the API must not drift apart, since a board state is a URL."""
        import re

        keys = re.findall(r'\{\s*key:\s*"([a-z_]+)"', page)
        assert keys, "the form declares no levers"
        signature = endpoint_signature()
        for key in keys:
            assert f"{key}:" in signature, f"the form offers {key!r} but the endpoint does not accept it"

    def test_the_two_policy_levers_act_forward(self, page):
        """The distinction the board turns on. Scaling the observed window answers a different question."""
        signature = endpoint_signature()
        assert "forward_stimulus_control" in inspect.getsource(
            __import__("macrofield.cockpit.server", fromlist=["server"]).create_app
        )
        assert "stimulus" in signature and "savings" in signature
        assert "act <strong>forward</strong>" in page


class TestForwardLevers:
    """The lever has to reach the projected path, which is where a stimulus programme lives."""

    def test_project_accepts_a_forward_multiplier_per_period(self):
        import numpy as np

        from macrofield.projection import project

        assert "forward_stimulus" in inspect.signature(project).parameters
        assert "forward_savings" in inspect.signature(project).parameters

    def test_a_wrong_length_lever_is_refused(self):
        """One multiplier per projected period, or the lever is silently misaligned.

        Checked on the source rather than by calling `project`, which would need a fitted calibration; the
        guard's presence is the contract. The searched text is deliberately one that does not straddle a
        line break in the message.
        """
        source = inspect.getsource(__import__("macrofield.projection", fromlist=["x"]).project)
        assert "one multiplier per projected period" in source
        assert "values but the horizon is" in source

    def test_the_resilient_wrapper_resolves_the_lever_per_horizon(self):
        """The horizon search changes how many periods there are, so the lever cannot be resolved once."""
        from macrofield.projection import project_resiliently

        parameters = inspect.signature(project_resiliently).parameters
        assert "forward_stimulus_control" in parameters
        assert "forward_savings_control" in parameters
        source = inspect.getsource(project_resiliently)
        assert "def forward_levers(candidate: int)" in source


class TestCapitalCycleRestartsOnTheBoard:
    """The reordering completing restarts the cycle, which is what removed the contradiction.

    Settled by the author on 2026-07-28 as the consequence of the phase rule. Earlier the board could only
    *report* the problem: the anchor stayed at the last observed crossing, so once the projection reached
    Foundation it went on reporting the economy decades late for a correction already behind it, and that tilt
    kept pushing weight to crisis. It now resolves it instead: the reordering completing restarts the cycle.
    """

    @staticmethod
    def source() -> str:
        return inspect.getsource(
            __import__("macrofield.cockpit.server", fromlist=["server"]).create_app
        )

    def test_the_restart_is_computed_from_the_phase_sequence(self):
        source = self.source()
        assert "reordering_end(" in source
        assert "years_into_capital_cycle(" in source
        assert "restart_year=restart_year" in source

    def test_the_overdue_reading_comes_from_the_restarted_count(self):
        """Not from the raw distance to the original anchor, which is what grew without bound."""
        assert "float(capital_into_cycle[index]) - float(capital_cycle.period_years)" in self.source()

    def test_the_old_warning_is_gone(self):
        """A board that resolves the contradiction must not still be warning about it."""
        source = self.source()
        assert "stale_anchor_periods" not in source
        assert "modelling decision this board does not" not in source

    def test_the_restart_is_reported_rather_than_silent(self):
        source = self.source()
        assert '"capital_reanchor"' in source
        assert "the capital cycle restarts there" in source

    def test_the_phase_sequence_is_latched_not_period_by_period(self):
        """The exit from Phase 4 is a sequence property, so the board cannot classify periods separately."""
        source = self.source()
        assert "classify_sequence(" in source
        assert '"phase": [c.phase.label for c in phase_sequence]' in source

    def test_the_front_end_states_the_restart(self, page):
        assert "The capital cycle restarts in" in page
        assert "data.capital_reanchor" in page


class TestBoardFrontEnd:
    def test_the_panel_exists_and_has_a_button(self, page):
        assert 'id="board-panel"' in page
        assert 'el("board")' in page
        assert 'show("board-panel")' in page

    def test_the_board_needs_an_assembled_economy(self, page):
        assert '"board"' in page.split("NEEDS_ASSEMBLY", 1)[1][:200]

    def test_the_projection_label_is_carried(self, page):
        assert 'el("board-label").textContent = data.projection.label' in page

    def test_a_board_state_is_a_shareable_link(self, page):
        assert 'el("board-link")' in page
        assert "/api/scenario/" in page

    def test_changed_levers_are_marked(self, page):
        """A board state has to be readable at a glance, not reconstructed from memory."""
        assert 'className = value === lever.value ? "field" : "field changed"' in page
        assert ".field.changed input" in page

    def test_the_signal_chart_shows_all_three_distributions(self, page):
        for name in ("Macro, SAA", "Technical, TAA", "Merged"):
            assert name in page

