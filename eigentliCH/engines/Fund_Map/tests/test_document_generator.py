"""Worked reading document generator (spec section 9).

Renders a self-contained HTML page from a ReturnSet payload. The document
is a smoke-tested artefact: verify structural pieces (tiles, figures, chips,
provenance) are present and no template variables leak unresolved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fmre.cli import main as cli_main
from tools.build_fundmap import (
    DEFAULT_MANDATE,
    DEFAULT_WEIGHTS,
    _compute_resilience,
    _superpose_role_from_payload,
    render_document,
)
from tools.svg import build_coverage_heatmap_svg, build_profile_curves_svg


@pytest.fixture(scope="module")
def returnset_path(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("rs")
    out = tmp / "rs.json"
    cli_main([
        "build-returnset",
        "--synthetic-timeline",
        # Must stay in step with `build_fundmap.DEFAULT_WEIGHTS`: this fixture and that reference book are a
        # matched pair, and `test_compute_resilience_matches_manual` looks the weights' ids up in this
        # payload. Retargeted 2026-08-02 with the weights (DECISIONS.md M60) — MIMUAWON/SPCHICCT/XAU/PIPCHAI
        # are ids 40/18/33/32. The previous four were ids 5/20/33/35, three of which production no longer has.
        "--tickers", "MIMUAWON Index", "SPCHICCT Index", "XAU BGN Curncy", "PIPCHAI LX Equity",
        "--source", "synthetic",
        "--calibration", "1998-01,2024-12",
        "--out", str(out),
    ])
    return out


@pytest.fixture(scope="module")
def payload(returnset_path):
    return json.loads(returnset_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------


def test_profile_curves_svg_contains_polylines(payload):
    svg = build_profile_curves_svg(payload, block_ids=[18, 32, 33, 40])
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert svg.count("<polyline") == 4  # one per selected block


def test_profile_curves_svg_handles_empty_selection(payload):
    svg = build_profile_curves_svg(payload, block_ids=[999999])  # not present
    assert svg.startswith("<svg")
    assert "<polyline" not in svg


def test_coverage_heatmap_svg_marks_crisis_column(payload):
    svg = build_coverage_heatmap_svg(payload, block_ids=[18, 32, 33, 40])
    assert svg.startswith("<svg")
    # Crisis outline via SIM's hm-mark class (stroke keyed off --above token)
    assert 'class="hm-mark"' in svg
    scenarios_count = len(payload["scenarios"])
    n_cells = 4 * scenarios_count
    # One rect per (block, scenario) plus one outline rect
    assert svg.count("<rect") >= n_cells + 1


def test_coverage_heatmap_labels_all_selected_blocks(payload):
    svg = build_coverage_heatmap_svg(payload, block_ids=[18, 32, 33, 40])
    for ticker in ("SPCHICCT Index", "PIPCHAI LX Equity", "XAU BGN Curncy", "MIMUAWON Index"):
        assert ticker in svg


# ---------------------------------------------------------------------------
# Resilience recomputation
# ---------------------------------------------------------------------------


def test_compute_resilience_matches_manual(payload):
    r_val, failing, r_p_out, margins_out = _compute_resilience(payload, DEFAULT_WEIGHTS, DEFAULT_MANDATE)
    # Manual: sum weights_b * P_{b,s}, subtract mandate, take min
    scenarios = payload["scenarios"]
    blocks = {int(bb["bb_id"]): bb for bb in payload["building_blocks"]}
    r_p = {s: 0.0 for s in scenarios}
    for bid, w in DEFAULT_WEIGHTS.items():
        prof = blocks[bid]["profile_by_scenario"]
        for s in scenarios:
            r_p[s] += w * prof[s]
    margins = {s: r_p[s] - DEFAULT_MANDATE[s] for s in scenarios}
    hand_r = min(margins.values())
    assert r_val == pytest.approx(hand_r)
    for scen in scenarios:
        assert r_p_out[scen] == pytest.approx(r_p[scen])
        assert margins_out[scen] == pytest.approx(margins[scen])
    if hand_r < 0:
        assert failing == min(margins, key=lambda k: margins[k])
    else:
        assert failing is None


def test_superpose_role_expectations_matches_manual(payload):
    exp = _superpose_role_from_payload(payload)
    for role, val in exp.items():
        hand = sum(payload["house_view"][s] * payload["role_profiles"][role][s]
                   for s in payload["scenarios"])
        assert val == pytest.approx(hand)


# ---------------------------------------------------------------------------
# End-to-end document
# ---------------------------------------------------------------------------


def test_render_document_writes_html(tmp_path, returnset_path):
    out = tmp_path / "doc.html"
    path = render_document(returnset_path, out)
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    # HTML5: doctype is case-insensitive; SIM style uses lowercase per schulung_us.html
    assert html.lstrip().lower().startswith("<!doctype html>")
    # Closing </div> of .shell is the last structural element (no <html>...</html>)
    assert "</div>" in html
    assert 'class="shell"' in html


def test_rendered_document_contains_expected_sections(tmp_path, returnset_path):
    out = tmp_path / "doc.html"
    render_document(returnset_path, out)
    html = out.read_text(encoding="utf-8")
    # Masthead in SIM style: eyebrow + h1 + standfirst + stamp
    assert 'class="eyebrow"' in html
    assert "SIM Research Institute" in html
    assert 'class="masthead"' in html
    assert 'class="standfirst"' in html
    assert 'class="stamp"' in html
    # Tiles use SIM's `.tile` with `.k`/`.v`/`.s` structure
    assert 'class="tiles"' in html
    for label in ("Universe", "State grid", "Calibration", "Current regime", "Resilience"):
        assert label in html
    # Binding condition callout (case-insensitive match against SIM's callout style)
    assert 'class="callout"' in html
    assert "binding condition" in html.lower()
    # Two SIM `.fig` figures
    assert html.count('class="fig"') >= 2
    assert html.count("<figure") >= 2
    # Provenance section
    assert "Provenance" in html
    assert "Return set id" in html
    # Model-derived label per house rules
    assert 'class="label-projected"' in html
    assert "Not a forecast" in html
    # SIM footer style
    assert 'class="doc"' in html


def test_rendered_document_has_no_unresolved_template_vars(tmp_path, returnset_path):
    out = tmp_path / "doc.html"
    render_document(returnset_path, out)
    html = out.read_text(encoding="utf-8")
    # Jinja variable delimiters should not leak
    assert "{{" not in html
    assert "}}" not in html
    # Nor block delimiters
    assert "{%" not in html
    assert "%}" not in html


def test_rendered_document_embeds_return_set_id_and_regime_id(tmp_path, returnset_path, payload):
    out = tmp_path / "doc.html"
    render_document(returnset_path, out)
    html = out.read_text(encoding="utf-8")
    assert payload["return_set_id"] in html
    assert payload["regime_id"] in html


def test_rendered_document_is_deterministic_per_input(tmp_path, returnset_path):
    out1 = tmp_path / "d1.html"
    out2 = tmp_path / "d2.html"
    render_document(returnset_path, out1)
    render_document(returnset_path, out2)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")
