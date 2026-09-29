"""Tests for the cockpit API.

Only the endpoints that do not touch the network are exercised here. Assembling an economy fetches from
World Bank, BIS and Penn World Table, which belongs in a live smoke test rather than in a unit suite, so
those paths are checked for their failure behaviour instead: an economy that cannot be assembled must come
back as a readable result rather than a 500.
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="the cockpit is optional")
from fastapi.testclient import TestClient  # noqa: E402

from macrofield import __version__  # noqa: E402
from macrofield.cockpit.server import STATIC_DIRECTORY, create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


class TestHealth:
    def test_reports_the_version_and_the_economies(self, client):
        payload = client.get("/api/health").json()
        assert payload["ok"] is True
        assert payload["version"] == __version__
        assert "us" in payload["economies"]

    def test_carries_the_band_and_the_disclaimer(self, client):
        payload = client.get("/api/health").json()
        assert payload["saturation_band"] == [2.5, 3.5]
        assert "not investment advice" in payload["disclaimer"]


class TestEconomies:
    def test_lists_every_configured_economy(self, client):
        payload = client.get("/api/economies").json()
        codes = {row["code"] for row in payload["economies"]}
        assert {"us", "cn", "jp", "de", "fr", "gb", "in", "eurozone"} <= codes

    def test_each_entry_carries_its_source_codes_and_proxy(self, client):
        rows = client.get("/api/economies").json()["economies"]
        for row in rows:
            assert row["world_bank"]
            assert row["bis"]
            assert row["stimulus_proxy"]

    def test_the_non_default_proxies_are_visible(self, client):
        rows = {row["code"]: row for row in client.get("/api/economies").json()["economies"]}
        assert rows["jp"]["stimulus_proxy"] == "central_bank_assets"
        assert rows["cn"]["stimulus_proxy"] == "net_new_credit"


class TestCache:
    def test_reports_the_cache_state(self, client):
        payload = client.get("/api/cache").json()
        assert "entries" in payload
        assert "stale" in payload
        assert "corrupt" in payload
        assert isinstance(payload["ok"], bool)

    def test_explains_what_a_corrupt_entry_means(self, client):
        assert "reproducible" in client.get("/api/cache").json()["note"]


class TestStockGoldSwitchedOff:
    """The stock-to-gold model is switched off, on the author's instruction of 2026-07-28.

    Switched off, not deleted: the module, its config and its tests are retained and correct, and the
    equation was only settled on 2026-07-27 after a sign error had been carried for some time. Deleting it
    would throw that resolution away along with the Weimar validation target.
    """

    def test_the_config_declares_it_off(self):
        from macrofield import config as config_module

        assert config_module.load().get("stock_gold.enabled") is False

    def test_health_tells_the_front_end_not_to_offer_it(self):
        """The panel is removed rather than rendered and then failing when its endpoint refuses."""
        from fastapi.testclient import TestClient as _TestClient

        from macrofield.cockpit.server import create_app as _create_app

        payload = _TestClient(_create_app()).get("/api/health").json()
        assert payload["panels"]["stock_gold"] is False

    def test_the_front_end_removes_the_panel_when_it_is_off(self):
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert "state.panels.stock_gold" in text
        assert 'el("gold").remove()' in text

    def test_the_model_itself_is_untouched(self):
        """Switching a model off must not quietly degrade it."""
        import numpy as np

        from macrofield.model.stock_gold import DRIVER_KEYS, SOURCE_DRIVER_SIGNS, DriverWeights

        assert np.allclose(
            DriverWeights().as_array(), [SOURCE_DRIVER_SIGNS[key] for key in DRIVER_KEYS]
        )


class TestProjectedDerivedIndicators:
    """The derived indicators are projected, and the index base is the trap.

    Every price level is an index rebased to the first period of whatever series it is given. Computing the
    indicators over the projected state alone therefore restarts the index at 100 in the first projected
    year, which against an observed index in the thousands draws as a collapse to zero, and restarts the
    price-divergence ratio at one. Both are artefacts of the rebasing rather than anything the model said.

    The endpoint therefore computes them once over the observed and projected state together and reports
    where the projected portion starts.
    """

    @staticmethod
    def endpoint_source() -> str:
        import inspect

        from macrofield.cockpit import server

        return inspect.getsource(server.create_app)

    def test_the_endpoint_computes_over_the_joined_path(self):
        source = self.endpoint_source()
        assert "joined_derived = compute(" in source
        assert '"projection_start_index": projection_start_index' in source

    def test_the_endpoint_does_not_compute_over_the_projection_alone(self):
        """The bug this replaced. If it comes back the price levels silently collapse to zero."""
        source = self.endpoint_source()
        assert "projected_derived = compute(" not in source

    def test_the_front_end_splits_one_series_rather_than_stitching_two(self):
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert "state.projectionStartIndex" in text
        # The split overlaps by one point so the two portions meet with no gap.
        assert "values.slice(split - 1)" in text

    def test_the_cached_projection_is_cleared_when_the_economy_changes(self):
        """Otherwise one economy's projection overlays another's observations."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        select_body = text.split("function select(code, button) {", 1)[1].split("\n}", 1)[0]
        assert "state.projectedDerived = null" in select_body
        assert "state.projectionStartIndex = null" in select_body


class TestUnwired:
    """The panel that states what the model computes and the dashboard cannot draw.

    It exists so that a missing chart is a readable statement rather than a silence, so the test is that
    each entry names its module and its blocker rather than merely existing.
    """

    def test_only_the_regime_layer_remains_blocked(self, client):
        """HoNI came off this list on 2026-07-28, when the published export was wired in.

        The regime layer is the last entry, and it stays until something assesses the four segments from
        indicators.
        """
        payload = client.get("/api/unwired").json()
        assert payload["ok"] is True
        modules = {row["module"] for row in payload["unwired"]}
        assert modules == {"model/regime.py"}

    def test_honi_is_no_longer_listed_as_blocked(self, client):
        """A panel that works must not still be advertised as impossible."""
        payload = client.get("/api/unwired").json()
        assert not any("honi" in row["module"] for row in payload["unwired"])
        assert client.get("/api/honi").json()["ok"] is True

    def test_every_entry_states_what_it_is_blocked_on(self, client):
        for row in client.get("/api/unwired").json()["unwired"]:
            assert row["panel"]
            assert len(row["blocked_on"]) > 40, "a blocker must be explained, not labelled"

    def test_the_regime_blocker_names_the_fabrication_risk(self, client):
        """The reason regime is unwired is that charting it would need invented inputs, and the endpoint
        must say so: a distribution built from invented segments would picture the kernels, not the
        economy."""
        rows = {row["module"]: row for row in client.get("/api/unwired").json()["unwired"]}
        assert "inventing" in rows["model/regime.py"]["blocked_on"]


class TestFailureBehaviour:
    """Expected failures must be readable results rather than server errors."""

    def test_the_new_panels_refuse_before_assembly(self, client):
        """Every panel that needs an assembled economy must say so rather than failing obscurely."""
        for endpoint in ("stock-gold", "cycles", "derived", "project"):
            payload = client.post(f"/api/{endpoint}/us").json()
            assert payload["ok"] is False, endpoint
            assert "assembled" in payload["error"], endpoint

    def test_an_unknown_series_for_cycles_lists_the_choices(self, client):
        """A typo must name what was available rather than reporting a bare failure."""
        payload = client.post("/api/cycles/us", params={"series": "wages"}).json()
        assert payload["ok"] is False
        # Reached before the assembly check would fire only if assembled; either message is acceptable,
        # but one of the two must be a readable explanation.
        assert "wages" in payload["error"] or "assembled" in payload["error"]

    def test_an_unknown_economy_is_a_result_not_a_500(self, client):
        response = client.post("/api/assemble/atlantis")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "atlantis" in payload["error"]

    def test_calibrating_before_assembling_explains_the_order(self, client):
        response = client.post("/api/calibrate/us")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "assembled" in payload["error"]

    def test_exporting_before_assembling_explains_the_order(self, client):
        payload = client.post("/api/export/us").json()
        assert payload["ok"] is False
        assert "assembled" in payload["error"]

    def test_comparing_nothing_returns_an_empty_result(self, client):
        payload = client.get("/api/compare").json()
        assert payload["ok"] is True
        assert payload["economies"] == []

    def test_the_comparison_warns_that_windows_differ(self, client):
        assert "windows differ" in client.get("/api/compare").json()["note"]


class TestProjectionJoinOffset:
    """The projection continues the calibrated model's trajectory, not the observed series.

    It therefore carries the calibration's level residual as a step at the join, which for the United
    States is 28 per cent on output. That is the intended behaviour and not a defect: see section 12b of
    docs/MODEL_SPEC.md, where an earlier reading of it as a defect is retracted. The step is nonetheless
    stated, because observed and projected share one axis and a reader who took them for one continuous
    series would misread the first projected period as a crash.

    The detection is exercised here without the network: the endpoint's threshold and the register of its
    message are the contract, and the live numbers belong in a smoke test.
    """

    @staticmethod
    def endpoint_source() -> str:
        import inspect

        from macrofield.cockpit import server

        return inspect.getsource(server.create_app)

    def test_the_detector_is_wired_into_the_endpoint(self, client):
        """A projection cannot be requested before assembly, so this asserts the field is part of the
        endpoint's contract rather than something a reader has to know to look for."""
        source = self.endpoint_source()
        assert '"join_break": join_break' in source
        assert "abs(relative) > 0.10" in source, "the threshold must be explicit and reviewable"

    def test_the_message_explains_rather_than_warns(self):
        """The step is expected, so the note must say what the reader is looking at.

        The first version of this told the reader the projection "does not continue the observed path" and
        that the phase "should not be read as a forecast", which framed correct behaviour as a defect. That
        wording must not come back.
        """
        source = self.endpoint_source()
        assert "continues the calibrated model's own trajectory" in source
        for alarm in ("should not be read as a forecast", "until the discontinuity is explained"):
            assert alarm not in source, f"the note has reverted to warning language: {alarm!r}"

    def test_the_front_end_renders_the_note_above_the_chart(self):
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert 'id="projection-break"' in text
        assert "continues the model's trajectory" in text
        # It must be above the chart in document order, or a reader sees the step first.
        assert text.index('id="projection-break"') < text.index('id="chart-projection"')

    def test_the_note_is_not_styled_as_a_failure(self):
        """A red rule would read as a defect. `explain` is the neutral class, `blocked` is the red one."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert 'class="explain" id="projection-break"' in text


class TestFrontEnd:
    def test_the_page_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "macrofield cockpit" in response.text

    def test_the_page_exists_on_disk(self):
        assert (STATIC_DIRECTORY / "index.html").exists()

    def test_the_page_states_the_primary_criteria(self):
        """The cockpit must not present the level fit as the headline."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert "Turning points and direction" in text
        assert "secondary" in text

    def test_the_page_degrades_without_plotly(self):
        """A CDN failure must produce a stated message, not silently empty panels."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert "Plotly did not load" in text

    def test_the_page_carries_no_forbidden_dash(self):
        """The house rules forbid em-dashes and en-dashes in generated material."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        for character in ("—", "–"):
            assert character not in text

    def test_every_panel_has_a_button_that_reveals_it(self):
        """A hidden panel with no way to reach it is dead markup."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        for panel, opener in [
            ("derived-panel", 'el("derived")'),
            ("gold-panel", 'el("gold")'),
            ("cycles-panel", 'el("cycles")'),
            ("projection-panel", 'el("project")'),
        ]:
            assert f'id="{panel}"' in text, panel
            assert opener in text, panel
            assert f'show("{panel}")' in text, panel

    def test_panels_are_revealed_only_through_show(self):
        """Revealing a panel has to happen before its charts are drawn, or Plotly cannot measure the
        container and every chart renders at its default 700px. Keeping that in one function is what
        stops the ordering being got wrong again, so nothing else may unhide a panel directly.

        Narrower elements inside a panel, for example the projection's discontinuity warning, are free to
        toggle their own visibility: they hold no chart, so nothing measures them.
        """
        script = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8").split("<script>", 1)[-1]
        assert '-panel").hidden' not in script, (
            "a panel is being revealed outside `show`, which risks drawing charts into a hidden container"
        )

    def test_charts_are_resized_after_plotting(self):
        """The second half of the same defect: a container that is still settling needs a resize."""
        assert "Plotly.Plots.resize" in (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")

    def test_the_projection_panel_carries_the_label(self):
        """Brief section 6: a projected path is labelled wherever it appears."""
        text = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        assert 'id="projection-label"' in text
        assert 'el("projection-label").textContent = p.label' in text


class TestChartPalette:
    """The series palette is an accessibility requirement, not decoration.

    Plotly cycles its own hues when a trace carries no colour, which breaks two rules at once: a series
    changes colour when the trace count changes, and nothing guarantees the hues are distinguishable. The
    page therefore assigns a colour per entity from a validated three-slot set.
    """

    @staticmethod
    def page() -> str:
        return (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")

    def test_the_palette_is_declared_for_both_modes(self):
        text = self.page()
        for slot in ("--series-1", "--series-2", "--series-3"):
            # Once in the light block and once in the dark media query.
            assert text.count(f"{slot}:") >= 2, slot

    def test_only_three_slots_exist(self):
        """A fourth slot cannot clear the contrast floors, so it must not quietly appear."""
        assert "--series-4" not in self.page()

    def test_colour_is_assigned_by_entity_not_by_position(self):
        text = self.page()
        assert "SERIES_SLOT" in text
        assert "function colourFor(entity)" in text

    def test_financial_capital_keeps_one_hue_across_panels(self):
        """The same entity in different panels must read as the same thing."""
        text = self.page()
        assert "financial_capital: 3" in text
        assert "financial_price_level: 3" in text
        assert "financial_inflation: 3" in text

    def test_no_trace_relies_on_plotly_hue_cycling(self):
        """Every trace sets its colour explicitly.

        Plotly assigns a cycled default to any trace that does not, which breaks two rules at once: a
        series changes colour when the trace count changes, and nothing guarantees the hues are
        distinguishable. Most traces get their colour from `line`; a few, such as the HoNI composite
        marker, are written inline and must set one themselves.

        The check is on the property rather than on where the trace was written, since an earlier version
        counted occurrences and broke the moment a legitimate inline trace was added.
        """
        import re

        script = self.page().split("<script>\n\"use strict\";", 1)[-1]
        traces = list(re.finditer(r'type: "(scatter|bar)"', script))
        assert traces, "the page builds no traces"
        for match in traces:
            window = script[max(0, match.start() - 400) : match.end() + 400]
            assert "color:" in window, (
                f"a {match.group(1)} trace near offset {match.start()} sets no colour, so Plotly would "
                f"give it a cycled default"
            )
