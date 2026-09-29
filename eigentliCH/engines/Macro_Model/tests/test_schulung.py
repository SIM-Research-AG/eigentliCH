"""Tests for the per-economy Schulung generator and the document it has produced.

Two halves, and the split is deliberate. The pure helpers are tested directly. The *generated document*
is then tested as an artefact, because it is checked in and read by people: a training page is the version
a reader remembers, so the requirements of brief sections 6 and 7 have to hold on the file itself and not
only in the code that wrote it.

Running the generator needs the network, so that is not done here.
"""

import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPOSITORY_ROOT / "tools" / "build_schulung.py"
DOCUMENT = REPOSITORY_ROOT / "docs" / "schulung_us.html"


def load_tool():
    """Load the generator, which lives in tools/ and is not an importable package.

    The module must be registered in `sys.modules` before it is executed. Its dataclasses use
    `from __future__ import annotations`, so their annotations are strings, and the dataclass machinery
    resolves them by looking the defining module up in `sys.modules`. Skipping the registration fails
    inside `@dataclass` rather than anywhere obvious.
    """
    spec = importlib.util.spec_from_file_location("build_schulung", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return load_tool()


@pytest.fixture(scope="module")
def document() -> str:
    if not DOCUMENT.exists():
        pytest.skip(f"{DOCUMENT.name} has not been generated")
    return DOCUMENT.read_text(encoding="utf-8")


class TestNiceTicks:
    """Axis ticks must be round numbers.

    The first version divided the data range linearly, which printed ticks as 0.442222 and 1.42644. That
    is unreadable, and on a training document it undermines everything beside it.
    """

    @pytest.mark.parametrize(
        "lo,hi",
        [(0.44, 4.38), (0.7, 2.3), (79.6, 260.0), (-0.28, 0.34), (1.0, 1.0001)],
    )
    def test_ticks_are_evenly_spaced_and_inside_the_range(self, tool, lo, hi):
        ticks, _ = tool._nice_ticks(lo, hi)
        assert ticks, "an axis must carry at least one tick"
        assert all(lo - 1e-9 <= t <= hi + 1e-9 for t in ticks)
        if len(ticks) > 2:
            steps = np.diff(ticks)
            assert np.allclose(steps, steps[0]), "ticks must be evenly spaced"

    @pytest.mark.parametrize("lo,hi", [(0.44, 4.38), (0.7, 2.3), (79.6, 260.0), (-0.28, 0.34)])
    def test_labels_are_readable_on_a_normal_range(self, tool, lo, hi):
        """Two decimals is as far as an axis label should ever go at these magnitudes."""
        ticks, fmt = tool._nice_ticks(lo, hi)
        for tick in ticks:
            rendered = f"{tick:{fmt}}"
            assert "." not in rendered or len(rendered.split(".")[-1]) <= 2, rendered

    def test_the_step_comes_from_a_round_progression(self, tool):
        ticks, _ = tool._nice_ticks(0.44, 4.38)
        assert ticks == [1.0, 2.0, 3.0, 4.0]

    def test_a_degenerate_range_does_not_loop_forever(self, tool):
        ticks, _ = tool._nice_ticks(2.0, 2.0)
        assert ticks == [2.0]

    def test_zero_is_not_rendered_as_negative_zero(self, tool):
        ticks, fmt = tool._nice_ticks(-0.28, 0.34)
        assert not any(f"{t:{fmt}}".startswith("-0.0") for t in ticks)


class TestClip:
    def test_short_text_is_untouched(self, tool):
        assert tool._clip("a short rationale") == "a short rationale"

    def test_long_text_breaks_on_a_word(self, tool):
        clipped = tool._clip("alpha beta gamma delta epsilon zeta", limit=20)
        assert clipped.endswith(" ...")
        assert "delt ..." not in clipped, "the text was cut mid-word"

    def test_whitespace_is_collapsed(self, tool):
        assert tool._clip("two\n   lines") == "two lines"


class TestChartGeometry:
    def test_a_path_skips_non_finite_points_rather_than_drawing_through_them(self, tool):
        path = tool._path([0.0, 1.0, np.nan, 3.0], [0.0, 1.0, 2.0, 3.0])
        # The break must start a new subpath, so the gap is not bridged by a straight line.
        assert path.count("M") == 2

    def test_an_empty_series_yields_an_empty_path(self, tool):
        assert tool._path([], []) == ""


class TestGeneratedDocument:
    """Brief sections 6 and 7, asserted on the artefact rather than on the generator."""

    def test_it_carries_the_disclaimer(self, document):
        assert "not investment advice" in document

    def test_every_projection_is_labelled(self, document):
        """Section 6: a projected path is labelled wherever it appears."""
        assert "illustrative, model-derived" in document

    def test_it_states_the_calibration_window_and_the_vintage(self, document):
        assert "Calibration window" in document
        assert re.search(r"vintage\s+\w+\s+\d{4}-\d{2}-\d{2}", document)

    def test_it_carries_no_forbidden_dash(self, document):
        for character in ("—", "–"):
            assert character not in document

    def test_no_placeholder_leaked_into_the_prose(self, document):
        """A formatting failure must not ship as text a reader would take for a value.

        The stylesheet is excluded, since CSS braces are not placeholders.
        """
        body = re.sub(r"<style>.*?</style>", "", document, flags=re.DOTALL)
        # Whole words only: "nan" otherwise matches inside "financial" and "None" inside "Nonetheless".
        for leak in ("nan", "NaN", "None", "undefined", "inf"):
            assert not re.search(rf"\b{leak}\b", body), (
                f"{leak!r} appears as a value in the generated document"
            )
        # An unresolved f-string placeholder looks like {name} or {obj.attr}.
        unresolved = re.findall(r"\{[A-Za-z_][\w.\[\]'\"]*\}", body)
        assert not unresolved, f"unresolved placeholders: {unresolved[:5]}"

    def test_every_chart_line_has_geometry(self, document):
        """An empty path renders as a blank chart, which reads as 'no data' rather than 'a bug'."""
        lines = re.findall(r'<path class="c-line[^"]*"([^>]*)>', document)
        assert lines, "the document carries no chart lines"
        for attributes in lines:
            match = re.search(r'd="([^"]*)"', attributes)
            assert match and match.group(1).strip(), "a chart line carries no geometry"

    def test_charts_are_self_contained(self, document):
        """It has to open from disk, so no external request and no script."""
        assert "<script" not in document
        assert "http://" not in document
        assert "https://" not in document

    def test_the_binding_condition_is_stated_before_the_numbers(self, document):
        """The document's own teaching point: never quote a level without the rule that fired."""
        assert "binding condition" in document
        assert document.index("binding condition") < document.index("Where the economy sits")

    def test_it_says_what_is_absent(self, document):
        """An omission a reader cannot see reads as a finding."""
        assert "What this reading does not include" in document
        assert "Health of Nations Indicator is not scored" in document
        assert "regime distribution is not produced" in document

    def test_it_does_not_present_the_reordering_as_a_defect(self, document):
        """The lesson of 2026-07-27: a projection decaying to the foundation phase is the prediction."""
        assert "reordering" in document
        assert "not a contradiction of it" in document

    def test_it_reports_both_calibration_readings(self, document):
        """Section 10: neither the primary criteria nor the level residual may be quoted alone."""
        assert "turning points" in document.lower()
        assert "level residual" in document
        assert "read the ordering of events" in document
