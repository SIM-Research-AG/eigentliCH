"""Regenerate the worked reading document from a ReturnSet JSON (spec section 9).

    python -m tools.build_fundmap PATH/TO/returnset.json --out PATH/TO/out.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from fmre.contracts import load_returnset, superpose_role_expectations
from fmre.contracts.returnset import ReturnSet
from fmre.version import __version__

from tools.svg import build_coverage_heatmap_svg, build_profile_curves_svg, curve_legend


# Reference mandate in annualised decimal, matching the ReturnSet emit unit.
DEFAULT_MANDATE: dict[str, float] = {
    "crisis": -0.10,
    "contraction": -0.03,
    "stagnation": 0.01,
    "expansion": 0.03,
    "boom": 0.05,
}

# Reference book with meaningful protection and cash exposure, per spec 8.6
# example: diversified passes; equities-only fails.
# Retargeted 2026-08-02 to the eight-instrument register (DECISIONS.md M60). Ids 5, 20 and 35 (US Equities,
# Global Bonds, USD Cash) no longer exist. The shape is preserved: a diversified book with real Gain, Income
# and Protection exposure, which spec 8.6 requires to pass where an equities-only book fails.
DEFAULT_WEIGHTS: dict[int, float] = {
    40: 0.30,  # MSCI AC World IMI (Gain)
    18: 0.20,  # CHF Corporate Loans IG (Income)
    33: 0.30,  # Precious Metals (Protection)
    32: 0.20,  # CHF Cash (Protection)
}


def _template_dir() -> Path:
    return Path(__file__).parent / "templates"


def _compute_portfolio_returns(
    payload: dict[str, Any],
    weights: dict[int, float],
) -> dict[str, float]:
    """R_P^s = sum_b w_b * P_{b,s} for every scenario, computed on the
    decimal payload values."""
    scenarios = payload["scenarios"]
    blocks = {int(bb["bb_id"]): bb for bb in payload["building_blocks"]}
    r_p = {s: 0.0 for s in scenarios}
    for bid, w in weights.items():
        if bid not in blocks:
            continue
        prof = blocks[bid]["profile_by_scenario"]
        for s in scenarios:
            r_p[s] += w * float(prof[s])
    return r_p


def _compute_resilience(
    payload: dict[str, Any],
    weights: dict[int, float],
    mandate: dict[str, float],
) -> tuple[float, str | None, dict[str, float], dict[str, float]]:
    """R = min_s (R_P^s - R_E^s) computed directly on the payload's decimal
    values. Returns (R, failing_scenario_or_None, r_p, margins)."""
    scenarios = payload["scenarios"]
    for scen in scenarios:
        if scen not in mandate:
            raise ValueError(f"mandate missing scenario {scen!r}")
    r_p = _compute_portfolio_returns(payload, weights)
    margins = {s: r_p[s] - mandate[s] for s in scenarios}
    worst_scen = min(margins, key=lambda k: margins[k])
    r_val = margins[worst_scen]
    return r_val, (worst_scen if r_val < 0 else None), r_p, margins


def _superpose_role_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    """Same as ReturnSet.superpose_role_expectations, but computed from a
    validated payload dict (avoids needing to reconstruct the dataclass)."""
    hv = payload["house_view"]
    out: dict[str, float] = {}
    for role, prof in payload["role_profiles"].items():
        out[role] = float(sum(hv[s] * prof[s] for s in payload["scenarios"]))
    return out


def render_document(
    returnset_path: Path | str,
    output_path: Path | str,
    weights: dict[int, float] | None = None,
    mandate: dict[str, float] | None = None,
) -> Path:
    """Load a ReturnSet JSON and write the HTML worked reading document.

    Returns the output path. Every value written is computed on the payload;
    the document is regenerated rather than edited by hand (spec section 0).
    """
    payload = load_returnset(returnset_path)
    mandate = dict(mandate or DEFAULT_MANDATE)
    weights = dict(weights or DEFAULT_WEIGHTS)

    r_val, failing, r_p, margins = _compute_resilience(payload, weights, mandate)

    # Profile curves use SIM's 3-series palette. Pick one representative per
    # canonical role that has the sharpest shape signature.
    representative_ids = [5, 20, 33]  # US Equities (Gain), Global Bonds (Income), Gold (Protection)
    available_ids = {int(bb["bb_id"]) for bb in payload["building_blocks"]}
    curve_ids = [bid for bid in representative_ids if bid in available_ids]
    if len(curve_ids) < 2:
        curve_ids = list(available_ids)[:3]

    # Heatmap: representatives plus a few more so the grid is worth reading
    heatmap_ids = curve_ids + [bid for bid in [35, 32, 51, 37, 53] if bid in available_ids and bid not in curve_ids]
    heatmap_ids = heatmap_ids[:8]

    provenance = payload["provenance"]
    context: dict[str, Any] = {
        "programme_version": __version__,
        "return_set_id": payload["return_set_id"],
        "regime_id": payload["regime_id"],
        "timeline_id": provenance.get("timeline_id", "n/a"),
        "vintage": provenance.get("data_vintage", "n/a"),
        "current_state": provenance.get("current_state", "n/a"),
        "state_grid": payload["state_grid"],
        "universe_size": len(payload["building_blocks"]),
        "calibration_window": provenance.get("calibration_window") or "not specified",
        "sources": provenance.get("series_sources", []),
        "universe_version": payload["universe_version"],
        "model_version": payload["model_version"],
        "state_to_scenario_version": payload["state_to_scenario_version"],
        "house_view": payload["house_view"],
        "scenario_order": payload["scenarios"],
        "resilience_val": r_val,
        "failing_scenario": failing,
        "mandate": mandate,
        "ref_weights": weights,
        "r_p": r_p,
        "margins": margins,
        "role_expectations": _superpose_role_from_payload(payload),
        "curve_legend": curve_legend(payload, curve_ids),
        "svg_profile_curves": build_profile_curves_svg(payload, curve_ids),
        "svg_coverage_heatmap": build_coverage_heatmap_svg(payload, heatmap_ids),
    }

    env = Environment(
        loader=FileSystemLoader(str(_template_dir())),
        autoescape=select_autoescape(["html"]),
        keep_trailing_newline=True,
    )
    template = env.get_template("fundmap.html.j2")
    html = template.render(**context)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-fundmap", description=__doc__)
    parser.add_argument("returnset", type=Path, help="Path to a validated ReturnSet JSON")
    parser.add_argument("--out", type=Path, required=True, help="Output HTML path")
    args = parser.parse_args(argv)
    path = render_document(args.returnset, args.out)
    print(str(path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
