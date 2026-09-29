"""Dependency-free inline SVG builders for the worked reading document.

Two figures: per-state profile curves (line plot with SIM's ``c-line s1..s3``
palette) and coverage heatmap (P_{b,s} grid using the ``--below`` / ``--above``
semantic tokens with fill-opacity for magnitude).

The SVG output uses CSS classes rather than inline colours so that the
document's dark-mode media query flips the palette automatically (design
tokens carried over from ``schulung_us.html``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


_SERIES_CLASSES: tuple[str, ...] = ("s1", "s2", "s3")


@dataclass(frozen=True, slots=True)
class LegendEntry:
    ticker: str
    role: str
    klass: str            # 's1' | 's2' | 's3'


def curve_legend(
    returnset: dict,
    block_ids: Sequence[int],
) -> list[LegendEntry]:
    """Build the legend rows for the profile-curves figure.

    Kept parallel to ``build_profile_curves_svg``: same block order, same
    class assignment. The template renders these into SIM's ``.legend``
    component using the ``.swatch s1/s2/s3`` classes.
    """
    blocks = {int(bb["bb_id"]): bb for bb in returnset["building_blocks"]}
    picked = [bid for bid in block_ids if bid in blocks]
    return [
        LegendEntry(
            ticker=blocks[bid]["ticker"],
            role=blocks[bid]["role"],
            klass=_SERIES_CLASSES[i % len(_SERIES_CLASSES)],
        )
        for i, bid in enumerate(picked)
    ]


def build_profile_curves_svg(
    returnset: dict,
    block_ids: Sequence[int],
    width: int = 720,
    height: int = 280,
) -> str:
    """SVG line plot of ``profile_by_state`` for up to 3 selected blocks.

    Uses SIM's ``c-line s{1..3}`` classes, ``c-grid`` / ``c-axis`` /
    ``c-tick`` / ``c-ylabel``. State axis 0..24, values in annualised
    decimals shown as percent on the y-axis.
    """
    blocks = {int(bb["bb_id"]): bb for bb in returnset["building_blocks"]}
    curves = [(bid, blocks[bid]) for bid in block_ids if bid in blocks]
    if not curves:
        return f'<svg class="chart" viewBox="0 0 {width} {height}"></svg>'

    all_values: list[float] = []
    for _, bb in curves:
        all_values.extend(float(v) for v in bb["profile_by_state"])
    ymin = min(all_values)
    ymax = max(all_values)
    if ymin == ymax:
        ymax = ymin + 1e-6
    span = ymax - ymin
    ymin -= 0.10 * span
    ymax += 0.10 * span

    pad_left, pad_right = 52, 20
    pad_top, pad_bottom = 18, 34
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def x_of(state: int) -> float:
        return pad_left + state * plot_w / 24.0

    def y_of(value: float) -> float:
        return pad_top + (ymax - value) / (ymax - ymin) * plot_h

    parts: list[str] = []
    parts.append(
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Per-state profile curves">'
    )

    # Horizontal grid lines at percent ticks
    for pct in _y_ticks_pct(ymin, ymax):
        val = pct / 100.0
        if ymin <= val <= ymax:
            y = y_of(val)
            parts.append(f'<line class="c-grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}"/>')
            parts.append(f'<text class="c-tick" x="{pad_left - 7}" y="{y + 3.2:.1f}" text-anchor="end">{pct:+d}%</text>')

    # Zero rule (dashed) if within range
    if ymin < 0.0 < ymax:
        y0 = y_of(0.0)
        parts.append(f'<line class="c-rule" x1="{pad_left}" y1="{y0:.1f}" x2="{width - pad_right}" y2="{y0:.1f}"/>')

    # X ticks
    for s in (0, 4, 9, 14, 19, 24):
        x = x_of(s)
        label = "crisis" if s == 0 else "boom" if s == 24 else str(s)
        parts.append(f'<text class="c-tick" x="{x:.1f}" y="{pad_top + plot_h + 16}" text-anchor="middle">{label}</text>')

    # Base x-axis
    parts.append(f'<line class="c-axis" x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}"/>')

    # Y-axis label
    parts.append(
        f'<text class="c-ylabel" x="14" y="{pad_top + plot_h / 2:.1f}" '
        f'transform="rotate(-90 14 {pad_top + plot_h / 2:.1f})" text-anchor="middle">'
        f'annualised return</text>'
    )

    # Curves
    for i, (_, bb) in enumerate(curves):
        klass = _SERIES_CLASSES[i % len(_SERIES_CLASSES)]
        pts = " ".join(
            f"{x_of(s):.1f} {y_of(float(bb['profile_by_state'][s])):.1f}"
            for s in range(25)
        )
        parts.append(f'<polyline class="c-line {klass}" points="{pts}" fill="none"/>')

    parts.append("</svg>")
    return "\n".join(parts)


def _y_ticks_pct(ymin: float, ymax: float) -> list[int]:
    lo_pct = int(ymin * 100) - 5
    hi_pct = int(ymax * 100) + 5
    span = hi_pct - lo_pct
    step = 10 if span > 40 else 5
    lo_pct = (lo_pct // step) * step
    return list(range(lo_pct, hi_pct + step, step))


def build_coverage_heatmap_svg(
    returnset: dict,
    block_ids: Sequence[int] | None = None,
    cell_w: int = 90,
    cell_h: int = 28,
    label_w: int = 210,
) -> str:
    """SVG heatmap of ``profile_by_scenario`` using SIM's semantic tokens.

    Positive cells use ``--below`` (green semantic); negative use ``--above``
    (red); intensity is set via ``fill-opacity``. Crisis column outlined in
    ``--above``.

    Requires the ``.hm-*`` CSS classes in the template stylesheet (added
    alongside the SIM tokens).
    """
    blocks = {int(bb["bb_id"]): bb for bb in returnset["building_blocks"]}
    if block_ids is None:
        block_ids = [int(bb["bb_id"]) for bb in returnset["building_blocks"]]
    scenarios = list(returnset["scenarios"])

    picked = [bid for bid in block_ids if bid in blocks]
    n = len(picked)
    if n == 0 or not scenarios:
        return '<svg class="chart" viewBox="0 0 100 20"></svg>'

    all_values = [
        float(blocks[bid]["profile_by_scenario"][s])
        for bid in picked for s in scenarios
    ]
    vmax = max(abs(v) for v in all_values) or 1.0

    header_h = 26
    footer_h = 6
    width = label_w + cell_w * len(scenarios)
    height = header_h + cell_h * n + footer_h

    def cell_class_and_opacity(v: float) -> tuple[str, float]:
        if abs(v) < 1e-6:
            return "hm-neu", 1.0
        t = min(1.0, abs(v) / vmax)
        klass = "hm-pos" if v > 0 else "hm-neg"
        opacity = 0.15 + 0.7 * t
        return klass, opacity

    parts: list[str] = []
    parts.append(
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Coverage matrix">'
    )
    # Column headers
    for j, scen in enumerate(scenarios):
        cx = label_w + j * cell_w + cell_w / 2
        parts.append(f'<text class="hm-hdr" x="{cx:.1f}" y="18" text-anchor="middle">{scen}</text>')

    # Cells
    y = header_h
    crisis_index = scenarios.index("crisis") if "crisis" in scenarios else -1
    for bid in picked:
        bb = blocks[bid]
        label = f"{bb['ticker']} · {bb['role']}"
        parts.append(
            f'<text class="hm-row" x="{label_w - 8}" y="{y + cell_h / 2 + 4:.1f}" '
            f'text-anchor="end">{label}</text>'
        )
        for j, scen in enumerate(scenarios):
            v = float(bb["profile_by_scenario"][scen])
            x = label_w + j * cell_w
            klass, opacity = cell_class_and_opacity(v)
            parts.append(
                f'<rect class="{klass}" x="{x:.1f}" y="{y:.1f}" '
                f'width="{cell_w}" height="{cell_h}" fill-opacity="{opacity:.2f}"/>'
            )
            parts.append(
                f'<text class="hm-val" x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4:.1f}" '
                f'text-anchor="middle">{v * 100:+.1f}%</text>'
            )
        y += cell_h

    if crisis_index >= 0:
        cx = label_w + crisis_index * cell_w
        parts.append(
            f'<rect class="hm-mark" x="{cx:.1f}" y="{header_h}" '
            f'width="{cell_w}" height="{cell_h * n}" fill="none"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts)
