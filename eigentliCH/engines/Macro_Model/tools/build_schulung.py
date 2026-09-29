"""Build the per-economy Schulung, a training document that reads one economy through the model.

    python tools/build_schulung.py us docs/schulung_us.html

As of 2026-07-28 this is the programme's **only** training document: the general guide it used to sit beside,
`docs/training.html`, is gone. So it stands alone. It takes one economy, runs the whole pipeline, and lays
out what the model says about it, with every figure traced back to the run that produced it, explaining the
apparatus where the reading needs it rather than deferring to a companion that no longer exists.

**Every number in the output is computed, not transcribed.** That is the whole reason this is a generator
rather than a hand-written page. A training document is the worst place for a stale or mistyped figure,
because it is the version people remember, and the numbers here move with the data vintage.

Requirements this enforces on the output, from brief sections 6 and 7:

- the calibration window and the data vintage appear on the document and beside every chart,
- any projected path carries the "illustrative, model-derived" label,
- the not-investment-advice disclaimer is present,
- British spelling, and no em-dashes or en-dashes.

The charts are inline SVG with no script and no external request, so the file opens from disk and prints.
Their colours are CSS custom properties, so light and dark modes are both selected rather than one being
an automatic inversion of the other.
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from macrofield import __version__, config as config_module  # noqa: E402
from macrofield.calibration.fit import calibrate  # noqa: E402
from macrofield.calibration.validate import assess_trend  # noqa: E402
from macrofield.data.loaders import numeric_derivative  # noqa: E402
from macrofield.model.cycles import (  # noqa: E402
    anchored_from_config,
    bands_from_config,
    decompose,
    detect_synchrony,
)
from macrofield.model.derived import Indicator, compute as compute_derived  # noqa: E402
from macrofield.model.phases import classify_period  # noqa: E402
from macrofield.model.quantity import unsecured_assets_ratio  # noqa: E402
from macrofield.pipeline import assemble, build_sources  # noqa: E402
from macrofield.projection import project  # noqa: E402
from macrofield.reporting.export import DISCLAIMER, PROJECTION_LABEL  # noqa: E402

#: Projection horizon. Fifteen years covers most of a credit cycle without pretending to reach the
#: capital cycle, which a parameter-hold assumption cannot support.
HORIZON = 15


# ----------------------------------------------------------------------------------------- gathering


@dataclass
class Reading:
    """Everything the document says about one economy, gathered in one place."""

    code: str
    name: str
    window: tuple[int, int]
    vintage: dict[str, str]
    periods: np.ndarray
    series: dict[str, np.ndarray]
    classification: Any
    band: tuple[float, float]
    trend: dict[str, Any]
    weakly_identified: list[str]
    derived: Any
    derived_joined: Any
    projection_start: int
    cycles: dict[str, Any]
    anchored: dict[str, Any]
    synchrony: Any
    projection: Any
    adjustments: dict[str, Any]
    notes: list[str]
    gold_enabled: bool


def gather(code: str, offline: bool = False) -> Reading:
    """Run the pipeline and collect the reading. This mirrors what the cockpit does per panel."""
    settings = config_module.load(code)
    sources = build_sources(offline=offline, config=settings)
    economy = assemble(code, sources, config=settings)
    path = economy.path

    band = (
        float(settings.get("saturation.balanced_band.lower")),
        float(settings.get("saturation.balanced_band.upper")),
    )

    saturation = (
        economy.saturation.values.loc[economy.window[0] : economy.window[1]]
        .reindex(path.periods)
        .to_numpy(dtype=float)
    )
    series = {
        "output": np.asarray(path.output, dtype=float),
        "real_capital": np.asarray(path.real_capital, dtype=float),
        "financial_capital": np.asarray(path.financial_capital, dtype=float),
        "saturation": saturation,
        "real_to_financial": np.asarray(path.real_capital, dtype=float)
        / np.asarray(path.financial_capital, dtype=float),
        "unsecured_over_output": unsecured_assets_ratio(
            path.real_capital, path.financial_capital, path.output
        ),
    }

    latest = economy.window[1]
    classification = classify_period(
        saturation=float(economy.saturation.values.loc[latest]),
        real_capital=float(path.real_capital[-1]),
        financial_capital=float(path.financial_capital[-1]),
        output=float(path.output[-1]),
    )

    calibration = calibrate(code, path, population_growth=economy.population_growth)
    trend = {}
    for name in ("Y", "K_R", "K_I"):
        if calibration.simulated[name].size:
            trend[name] = assess_trend(
                name, calibration.observed[name], calibration.simulated[name], periods=path.periods
            ).as_dict()

    derived = compute_derived(
        path.periods, path.output, path.real_capital, path.financial_capital
    )

    # Cycles: two band-passed, two anchored.
    with np.errstate(divide="ignore", invalid="ignore"):
        growth = np.gradient(np.log(series["output"]))
    estimates = decompose(growth, bands_from_config(settings), sampling_per_year=1.0)
    anchored = anchored_from_config(settings, path.periods, saturation)
    for name, cycle in anchored.items():
        estimates[name] = cycle.estimate
    synchrony = detect_synchrony(
        path.periods,
        estimates,
        phase_tolerance_radians=float(settings.get("cycles.synchrony.phase_tolerance_radians")),
        minimum_cycles_in_phase=int(settings.get("cycles.synchrony.minimum_cycles_in_phase")),
    )

    share = float(
        economy.saturation.values.loc[latest] * path.output[-1] / path.financial_capital[-1]
    )
    projection = project(
        code,
        path,
        calibration,
        horizon=HORIZON,
        population_growth=economy.population_growth,
        credit_share_of_financial=share,
    )

    # The derived indicators over the observed and projected state together, on one index base. See the
    # comment in the cockpit's project endpoint for why computing over the projection alone is wrong.
    derived_joined = compute_derived(
        np.concatenate([np.asarray(path.periods), np.asarray(projection.periods)]),
        np.concatenate([series["output"], projection.output]),
        np.concatenate([series["real_capital"], projection.real_capital]),
        np.concatenate([series["financial_capital"], projection.financial_capital]),
    )

    return Reading(
        code=code,
        name=economy.name,
        window=tuple(economy.window),
        vintage=dict(economy.vintage),
        periods=np.asarray(path.periods),
        series=series,
        classification=classification,
        band=band,
        trend=trend,
        weakly_identified=list(calibration.report()["weakly_identified"]),
        derived=derived,
        derived_joined=derived_joined,
        projection_start=int(np.asarray(path.periods).size),
        cycles=estimates,
        anchored=anchored,
        synchrony=synchrony,
        projection=projection,
        adjustments=dict(economy.adjustments),
        notes=list(economy.notes),
        gold_enabled=bool(settings.get("stock_gold.enabled", default=True)),
    )


# --------------------------------------------------------------------------------------------- charts


@dataclass
class Chart:
    """An inline SVG line chart.

    Deliberately plain: a linear y-axis, one x-axis, ticks only where a reader needs them, and no
    second axis ever. Where two quantities differ in scale they are indexed to a common base before
    they share a frame, which is a documented, dynamics-neutral operation, rather than given an axis
    each.
    """

    width: float = 720.0
    height: float = 260.0
    left: float = 52.0
    right: float = 16.0
    top: float = 18.0
    bottom: float = 34.0

    def __post_init__(self) -> None:
        self.x0, self.x1 = self.left, self.width - self.right
        self.y0, self.y1 = self.top, self.height - self.bottom

    def scale_x(self, value: float, lo: float, hi: float) -> float:
        return self.x0 + (self.x1 - self.x0) * (value - lo) / (hi - lo or 1.0)

    def scale_y(self, value: float, lo: float, hi: float) -> float:
        return self.y1 - (self.y1 - self.y0) * (value - lo) / (hi - lo or 1.0)


def _nice_ticks(lo: float, hi: float, target: int = 5) -> tuple[list[float], str]:
    """Round tick values covering the range, and a format string for them.

    Without this, ticks come from a linear division of the data range and print as 0.442222 and 1.42644,
    which is unreadable on an axis. The step is chosen from 1, 2, 2.5 and 5 times a power of ten, so the
    labels are the round numbers a reader expects.

    Returns:
        The tick values and the format specifier to render them with.
    """
    span = hi - lo
    if not np.isfinite(span) or span <= 0:
        return [lo], ".2f"

    rough = span / max(target - 1, 1)
    magnitude = 10.0 ** np.floor(np.log10(rough))
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiple * magnitude
        if rough <= step:
            break

    first = np.ceil(lo / step) * step
    ticks = []
    value = first
    while value <= hi + step * 1e-9:
        # Snap values that are within rounding error of zero, so an axis shows 0 rather than -0.
        ticks.append(0.0 if abs(value) < step * 1e-9 else float(value))
        value += step

    decimals = max(0, int(-np.floor(np.log10(step))) if step < 1 else 0)
    return ticks, f".{decimals}f"


def _path(xs: Sequence[float], ys: Sequence[float]) -> str:
    """An SVG path through the points, skipping any that are not finite."""
    parts: list[str] = []
    drawing = False
    for x, y in zip(xs, ys):
        if not (np.isfinite(x) and np.isfinite(y)):
            drawing = False
            continue
        parts.append(f"{'L' if drawing else 'M'}{x:.2f} {y:.2f}")
        drawing = True
    return " ".join(parts)


def line_chart(
    title: str,
    y_label: str,
    x_values: Sequence[float],
    traces: Sequence[Mapping[str, Any]],
    y_range: tuple[float, float] | None = None,
    bands: Sequence[Mapping[str, Any]] = (),
    rules: Sequence[Mapping[str, Any]] = (),
    marks: Sequence[Mapping[str, Any]] = (),
    x_ticks: Sequence[float] | None = None,
    y_ticks: Sequence[float] | None = None,
    footer: str = "",
) -> str:
    """Render one chart.

    Args:
        traces: Each is `{values, label, slot, dash}`. `slot` selects a validated categorical colour.
        bands: Horizontal shaded ranges, `{lo, hi, label}`.
        rules: Horizontal reference lines, `{at, label}`.
        marks: Vertical annotations, `{at, label}`.
    """
    chart = Chart()
    xs = np.asarray(x_values, dtype=float)
    x_lo, x_hi = float(np.min(xs)), float(np.max(xs))

    finite = np.concatenate(
        [np.asarray(t["values"], dtype=float)[np.isfinite(t["values"])] for t in traces]
    )
    if y_range is None:
        y_lo, y_hi = float(np.min(finite)), float(np.max(finite))
        pad = (y_hi - y_lo) * 0.08 or 1.0
        y_lo, y_hi = y_lo - pad, y_hi + pad
    else:
        y_lo, y_hi = y_range

    out: list[str] = [
        f'<svg class="chart" viewBox="0 0 {chart.width:.0f} {chart.height:.0f}" '
        f'role="img" aria-label="{html.escape(title)}">'
    ]

    for entry in bands:
        top = chart.scale_y(min(entry["hi"], y_hi), y_lo, y_hi)
        bottom = chart.scale_y(max(entry["lo"], y_lo), y_lo, y_hi)
        out.append(
            f'<rect class="c-band" x="{chart.x0:.1f}" y="{top:.1f}" '
            f'width="{chart.x1 - chart.x0:.1f}" height="{max(bottom - top, 0):.1f}"/>'
        )

    # Gridlines and y ticks, on round values rather than a linear division of the data range.
    if y_ticks is not None:
        ticks, tick_format = list(y_ticks), ".2f"
    else:
        ticks, tick_format = _nice_ticks(y_lo, y_hi)
    for value in ticks:
        y = chart.scale_y(float(value), y_lo, y_hi)
        if not chart.y0 - 1 <= y <= chart.y1 + 1:
            continue
        out.append(
            f'<line class="c-grid" x1="{chart.x0:.1f}" y1="{y:.1f}" x2="{chart.x1:.1f}" y2="{y:.1f}"/>'
        )
        out.append(
            f'<text class="c-tick" x="{chart.x0 - 7:.1f}" y="{y + 3.2:.1f}" '
            f'text-anchor="end">{value:{tick_format}}</text>'
        )

    for entry in rules:
        y = chart.scale_y(float(entry["at"]), y_lo, y_hi)
        out.append(
            f'<line class="c-rule" x1="{chart.x0:.1f}" y1="{y:.1f}" x2="{chart.x1:.1f}" y2="{y:.1f}"/>'
        )
        if entry.get("label"):
            out.append(
                f'<text class="c-rule-label" x="{chart.x1:.1f}" y="{y - 5:.1f}" '
                f'text-anchor="end">{html.escape(entry["label"])}</text>'
            )

    for entry in marks:
        x = chart.scale_x(float(entry["at"]), x_lo, x_hi)
        out.append(
            f'<line class="c-mark" x1="{x:.1f}" y1="{chart.y0:.1f}" x2="{x:.1f}" y2="{chart.y1:.1f}"/>'
        )
        if entry.get("label"):
            out.append(
                f'<text class="c-mark-label" x="{x - 4:.1f}" y="{chart.y0 + 2:.1f}" '
                f'transform="rotate(-90 {x - 4:.1f} {chart.y0 + 2:.1f})" '
                f'text-anchor="end">{html.escape(entry["label"])}</text>'
            )

    # x ticks.
    for value in (x_ticks if x_ticks is not None else np.linspace(x_lo, x_hi, 6)):
        x = chart.scale_x(float(value), x_lo, x_hi)
        out.append(
            f'<text class="c-tick" x="{x:.1f}" y="{chart.y1 + 16:.1f}" '
            f'text-anchor="middle">{value:.0f}</text>'
        )

    # Axis lines, drawn after the grid so they sit on top.
    out.append(
        f'<line class="c-axis" x1="{chart.x0:.1f}" y1="{chart.y1:.1f}" '
        f'x2="{chart.x1:.1f}" y2="{chart.y1:.1f}"/>'
    )

    for trace in traces:
        values = np.asarray(trace["values"], dtype=float)
        px = [chart.scale_x(float(v), x_lo, x_hi) for v in xs[: values.size]]
        py = [chart.scale_y(float(v), y_lo, y_hi) for v in values]
        dash = ' stroke-dasharray="7 4"' if trace.get("dash") else ""
        out.append(
            f'<path class="c-line s{trace["slot"]}" d="{_path(px, py)}" fill="none"{dash}/>'
        )

    out.append(f'<text class="c-ylabel" x="14" y="{(chart.y0 + chart.y1) / 2:.1f}" '
               f'transform="rotate(-90 14 {(chart.y0 + chart.y1) / 2:.1f})" '
               f'text-anchor="middle">{html.escape(y_label)}</text>')
    out.append("</svg>")

    legend = ""
    if len(traces) > 1 or any(t.get("dash") for t in traces):
        items = "".join(
            f'<span class="key"><span class="swatch s{t["slot"]}'
            f'{" dashed" if t.get("dash") else ""}"></span>{html.escape(t["label"])}</span>'
            for t in traces
        )
        legend = f'<div class="legend">{items}</div>'

    band_note = "".join(
        f'<span class="key"><span class="swatch band"></span>{html.escape(b["label"])}</span>'
        for b in bands
        if b.get("label")
    )
    if band_note:
        legend = f'<div class="legend">{band_note}</div>' + legend

    return (
        f'<figure class="fig">\n<figcaption class="fig-title">{html.escape(title)}</figcaption>\n'
        f"{''.join(out)}\n{legend}\n"
        f'<p class="fig-note">{footer}</p>\n</figure>'
    )


# ---------------------------------------------------------------------------------------------- style

STYLE = """
  /* Tokens carried over from the programme's earlier training guide, so anything written against that
     house style still matches. The exception is the categorical series palette, which is new: the old
     series colours (slate, teal, violet) fail the contrast and colour-vision floors when they share a
     frame, with a normal-vision separation of 11.1 against a floor of 15. These three clear every gate on
     the all-pairs list in both light and dark modes. */
  :root {
    --ground:#eceff4; --paper:#ffffff; --paper-sunk:#f5f7fa;
    --ink:#131720; --ink-soft:#4a5364; --ink-faint:#77808f;
    --rule:#d3d9e3; --rule-soft:#e4e8ef;
    --accent:#33456b; --signal:#9a6414; --signal-wash:#f7efe0;
    --below:#2f6b4f; --inside:#9a6414; --above:#a13527;
    --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a;
    --serif:ui-serif,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
    --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,monospace;
    --measure:66ch; --wide:60rem;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground:#0e1117; --paper:#171b24; --paper-sunk:#1d222c;
      --ink:#e7eaf1; --ink-soft:#a9b2c2; --ink-faint:#7e8798;
      --rule:#2b323f; --rule-soft:#232935;
      --accent:#9db1e2; --signal:#dda758; --signal-wash:#241d10;
      --below:#6cbb92; --inside:#dda758; --above:#e08175;
      --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
    }
  }
  :root[data-theme="dark"] {
    --ground:#0e1117; --paper:#171b24; --paper-sunk:#1d222c;
    --ink:#e7eaf1; --ink-soft:#a9b2c2; --ink-faint:#7e8798;
    --rule:#2b323f; --rule-soft:#232935;
    --accent:#9db1e2; --signal:#dda758; --signal-wash:#241d10;
    --below:#6cbb92; --inside:#dda758; --above:#e08175;
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  }

  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--ink); font-family:var(--sans);
         font-size:17px; line-height:1.65; -webkit-font-smoothing:antialiased; }
  .shell { max-width:var(--wide); margin:0 auto; padding:0 1.5rem 6rem; }
  p, ul, ol { max-width:var(--measure); }
  h2 { font-family:var(--serif); font-size:1.6rem; line-height:1.25; margin:3.5rem 0 .35rem;
       padding-top:1.5rem; border-top:1px solid var(--rule); }
  h3 { font-size:1.05rem; margin:2rem 0 .3rem; }
  .lede { color:var(--ink-soft); margin:.2rem 0 1.4rem; }
  code, .mono { font-family:var(--mono); font-size:.875em; }
  strong { font-weight:650; }

  .masthead { padding:4.5rem 0 2rem; border-bottom:2px solid var(--ink); }
  .eyebrow { font-family:var(--mono); font-size:.72rem; letter-spacing:.14em; text-transform:uppercase;
             color:var(--ink-faint); margin:0 0 1.4rem; }
  .masthead h1 { font-family:var(--serif); font-size:2.8rem; line-height:1.1; margin:0 0 .8rem;
                 letter-spacing:-.015em; }
  .standfirst { font-size:1.15rem; color:var(--ink-soft); max-width:58ch; margin:0; }
  .stamp { display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; margin:1.8rem 0 0;
           font-family:var(--mono); font-size:.72rem; color:var(--ink-faint); }
  .stamp b { color:var(--ink-soft); font-weight:500; }

  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.7rem; margin:1.6rem 0; }
  .tile { background:var(--paper); border:1px solid var(--rule); border-left:3px solid var(--accent);
          border-radius:3px; padding:.7rem .85rem; }
  .tile.above { border-left-color:var(--above); }
  .tile.inside { border-left-color:var(--inside); }
  .tile.below { border-left-color:var(--below); }
  .tile .k { font-family:var(--mono); font-size:.62rem; letter-spacing:.09em; text-transform:uppercase;
             color:var(--ink-faint); }
  .tile .v { font-size:1.3rem; font-weight:620; margin-top:.15rem; line-height:1.2; }
  .tile .s { font-size:.76rem; color:var(--ink-soft); margin-top:.15rem; }

  table { border-collapse:collapse; width:100%; font-size:.85rem; margin:1.2rem 0; }
  th, td { text-align:left; padding:.42rem .6rem; border-bottom:1px solid var(--rule); vertical-align:top; }
  th { font-family:var(--mono); font-size:.64rem; letter-spacing:.08em; text-transform:uppercase;
       color:var(--ink-faint); font-weight:500; }
  td.n { font-family:var(--mono); text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .scroll { overflow-x:auto; }

  .fig { margin:1.8rem 0 2rem; padding:0; background:var(--paper); border:1px solid var(--rule);
         border-radius:3px; padding:1rem 1.1rem .8rem; }
  .fig-title { font-size:.95rem; font-weight:620; margin-bottom:.5rem; }
  .fig-note { font-size:.74rem; color:var(--ink-faint); margin:.5rem 0 0; max-width:none; }
  svg.chart { width:100%; height:auto; display:block; overflow:visible; }
  .c-band { fill:var(--signal); opacity:.13; }
  .c-grid { stroke:var(--rule-soft); stroke-width:1; }
  .c-axis { stroke:var(--rule); stroke-width:1; }
  .c-rule { stroke:var(--ink-faint); stroke-width:1; stroke-dasharray:4 3; }
  .c-mark { stroke:var(--ink-faint); stroke-width:1; stroke-dasharray:2 3; opacity:.7; }
  .c-line { stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
  .c-line.s1, .swatch.s1 { stroke:var(--series-1); }
  .c-line.s2, .swatch.s2 { stroke:var(--series-2); }
  .c-line.s3, .swatch.s3 { stroke:var(--series-3); }
  .c-tick, .c-ylabel, .c-rule-label, .c-mark-label {
    font-family:var(--mono); fill:var(--ink-faint); font-size:9px; }
  .c-ylabel { font-size:9.5px; }
  .legend { display:flex; flex-wrap:wrap; gap:.3rem 1rem; margin-top:.6rem; font-size:.76rem;
            color:var(--ink-soft); }
  .key { display:inline-flex; align-items:center; gap:.4rem; }
  .swatch { width:18px; height:0; border-top:2px solid currentColor; display:inline-block; }
  .swatch.s1 { border-top-color:var(--series-1); }
  .swatch.s2 { border-top-color:var(--series-2); }
  .swatch.s3 { border-top-color:var(--series-3); }
  .swatch.dashed { border-top-style:dashed; }
  .swatch.band { height:10px; border:0; background:var(--signal); opacity:.3; border-radius:1px; }

  .callout { border-left:3px solid var(--signal); background:var(--signal-wash); padding:.85rem 1rem;
             margin:1.4rem 0; border-radius:0 3px 3px 0; }
  .callout p { margin:.3rem 0; max-width:none; }
  .callout .h { font-family:var(--mono); font-size:.64rem; letter-spacing:.09em; text-transform:uppercase;
                color:var(--signal); }
  .warn { border-left-color:var(--above); background:transparent; }
  .warn .h { color:var(--above); }

  .chip { display:inline-block; font-family:var(--mono); font-size:.62rem; padding:.08rem .38rem;
          border-radius:2px; text-transform:uppercase; letter-spacing:.05em; border:1px solid; }
  .chip.ok { color:var(--below); border-color:var(--below); }
  .chip.warn { color:var(--inside); border-color:var(--inside); }
  .chip.bad { color:var(--above); border-color:var(--above); }
  .label-projected { display:inline-block; font-family:var(--mono); font-size:.62rem;
    letter-spacing:.06em; text-transform:uppercase; color:var(--signal); border:1px solid var(--signal);
    border-radius:2px; padding:.08rem .38rem; margin-left:.5rem; vertical-align:.1em; }

  footer.doc { margin-top:4rem; padding-top:1.2rem; border-top:2px solid var(--ink);
               font-size:.8rem; color:var(--ink-soft); }

  @media print {
    body { background:#fff; font-size:11pt; }
    .fig, .tile { break-inside:avoid; }
    h2 { break-after:avoid; }
  }
"""


# --------------------------------------------------------------------------------------------- render


def _tile(key: str, value: str, sub: str = "", klass: str = "") -> str:
    sub_html = f'<div class="s">{sub}</div>' if sub else ""
    return (
        f'<div class="tile {klass}"><div class="k">{html.escape(key)}</div>'
        f'<div class="v">{value}</div>{sub_html}</div>'
    )


def _clip(text: str, limit: int = 240) -> str:
    """Shorten to a word boundary, with an ellipsis, rather than cutting mid-word.

    A rationale that ends "so t" reads as a rendering bug and invites the reader to distrust the rest of
    the table, which is the opposite of what a provenance table is for.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.")
    return f"{cut} ..."


def _band_class(value: float, band: tuple[float, float]) -> str:
    if value > band[1]:
        return "above"
    return "inside" if value >= band[0] else "below"


def _first_crossing(periods: np.ndarray, values: np.ndarray, level: float) -> int | None:
    above = np.flatnonzero(values >= level)
    return int(periods[above[0]]) if above.size else None


def render(r: Reading) -> str:
    """Render the whole document."""
    p = r.periods
    sat = r.series["saturation"]
    rf = r.series["real_to_financial"]
    unsec = r.series["unsecured_over_output"]
    band = r.band
    stamp = f"Window {r.window[0]} to {r.window[1]} . vintage {r.vintage.get('saturation', 'see table')}"

    peak_index = int(np.argmax(sat))
    peak_year, peak_value = int(p[peak_index]), float(sat[peak_index])
    now_sat = float(sat[-1])
    now_rf = float(rf[-1])
    crossed_upper = _first_crossing(p, sat, band[1])
    crossed_lower = _first_crossing(p, sat, band[0])
    rf_below = np.flatnonzero(rf < 1.0)
    rf_below_year = int(p[rf_below[0]]) if rf_below.size else None

    capital = r.anchored.get("capital")
    innovation = r.anchored.get("innovation")
    proj = r.projection

    # ---------------------------------------------------------------- headline tiles
    tiles = [
        _tile(
            "Phase",
            html.escape(r.classification.phase.label),
            html.escape(r.classification.rules_fired[0]) if r.classification.rules_fired else "",
            _band_class(now_sat, band),
        ),
        _tile(
            "Capital saturation",
            f"{now_sat:.2f}",
            f"band {band[0]:g} to {band[1]:g}, peak {peak_value:.2f} in {peak_year}",
            _band_class(now_sat, band),
        ),
        _tile(
            "Real over financial capital",
            f"{now_rf:.2f}",
            (f"below 1.00 since {rf_below_year}" if rf_below_year else "has not fallen below 1.00"),
            "above" if now_rf < 1.0 else "plain",
        ),
    ]
    if capital is not None and capital.anchored:
        overdue = float(capital.years_into_cycle[-1]) - capital.period_years
        tiles.append(
            _tile(
                "Capital cycle",
                f"{float(capital.years_into_cycle[-1]):.0f} of {capital.period_years:.0f}y",
                (
                    f"{abs(overdue):.0f} years past the reordering point"
                    if overdue > 0
                    else f"{abs(overdue):.0f} years short of it"
                ),
                "above" if overdue > 0 else "inside",
            )
        )
    if innovation is not None and innovation.anchored:
        to_trough = float(innovation.reference_year) - float(p[-1])
        tiles.append(
            _tile(
                "Innovation cycle",
                f"low in {abs(to_trough):.0f}y" if to_trough >= 0 else f"low {abs(to_trough):.0f}y ago",
                f"trough {innovation.reference_year:.0f}, period {innovation.period_years:.0f}y",
                "inside",
            )
        )

    # ---------------------------------------------------------------- charts
    projected_years = np.concatenate([[p[-1]], np.asarray(proj.periods)])
    projected_sat = np.concatenate([[now_sat], np.asarray(proj.saturation)])
    all_years = np.concatenate([p, np.asarray(proj.periods)])

    observed_padded = np.concatenate([sat, np.full(proj.periods.size, np.nan)])
    projected_padded = np.concatenate(
        [np.full(p.size - 1, np.nan), projected_sat]
    )

    marks = [{"at": peak_year, "label": f"peak {peak_value:.2f}"}]
    if crossed_upper:
        marks.insert(0, {"at": crossed_upper, "label": f"{band[1]:g} crossed {crossed_upper}"})

    chart_saturation = line_chart(
        f"Capital saturation, {r.window[0]} to {int(proj.periods[-1])}",
        "Credit to non-financial sector over GDP",
        all_years,
        [
            {"values": observed_padded, "label": "Observed", "slot": 1},
            {"values": projected_padded, "label": "Projected", "slot": 1, "dash": True},
        ],
        bands=[{"lo": band[0], "hi": band[1], "label": f"Balanced band {band[0]:g} to {band[1]:g}"}],
        marks=marks,
        x_ticks=[1980, 1990, 2000, 2010, 2020, 2030, int(proj.periods[-1])],
        footer=(
            f"{stamp}. The projected portion is {PROJECTION_LABEL} and continues from the last "
            f"observation, so the first step is one period of the model's own dynamics."
        ),
    )

    chart_real_financial = line_chart(
        "Real capital against financial capital",
        "K_R over K_I",
        p,
        [{"values": rf, "label": "K_R / K_I", "slot": 2}],
        rules=[{"at": 1.0, "label": "Phase IV condition, 1.00"}],
        x_ticks=[1980, 1990, 2000, 2010, 2020],
        footer=(
            f"{stamp}. This ratio is invariant to the level adjustments, so it is the one phase "
            f"condition the scale problem cannot touch."
        ),
    )

    # Three measures of the financial economy, each indexed to its own first value so they share one
    # axis legitimately. Indexing is multiplicative and therefore dynamics-neutral.
    def indexed(values: np.ndarray) -> np.ndarray:
        base = values[0] if values[0] else 1.0
        return 100.0 * values / base

    divergence = np.asarray(r.derived.series(Indicator.PRICE_DIVERGENCE), dtype=float)

    # Price divergence is deliberately NOT a third trace here. Under the constant-frequency assumption it
    # is the unsecured-asset gap up to a constant, so plotting both would draw one line exactly on top of
    # the other and imply two pieces of evidence where there is one. The identity is stated in the prose
    # instead, and the measured correlation is quoted so the claim is checkable.
    gap_divergence_correlation = float(
        np.corrcoef(indexed(unsec), indexed(divergence))[0, 1]
    )

    chart_two = line_chart(
        "Capital saturation and the unsecured-asset gap, indexed to their first year",
        "Index, first year = 100",
        p,
        [
            {"values": indexed(sat), "label": "Capital saturation", "slot": 1},
            {"values": indexed(unsec), "label": "Unsecured-asset gap", "slot": 2},
        ],
        x_ticks=[1980, 1990, 2000, 2010, 2020],
        marks=[{"at": peak_year, "label": str(peak_year)}],
        footer=(
            f"{stamp}. Indexing is a multiplicative rebasing, so it changes no growth rate, direction "
            f"or turning point. It is used here only so two quantities of different units can share one "
            f"axis rather than being given an axis each."
        ),
    )

    joined_periods = np.asarray(r.derived_joined.periods, dtype=float)
    split = r.projection_start
    real_infl = np.asarray(r.derived_joined.series(Indicator.REAL_INFLATION), dtype=float)
    fin_infl = np.asarray(r.derived_joined.series(Indicator.FINANCIAL_INFLATION), dtype=float)

    def observed_part(values: np.ndarray) -> np.ndarray:
        out = values.astype(float).copy()
        out[split:] = np.nan
        return out

    def projected_part(values: np.ndarray) -> np.ndarray:
        out = values.astype(float).copy()
        out[: split - 1] = np.nan
        return out

    chart_inflation = line_chart(
        "Real against financial inflation, with the projection",
        "Fraction per period",
        joined_periods,
        [
            {"values": observed_part(real_infl), "label": "Real inflation", "slot": 1},
            {"values": projected_part(real_infl), "label": "Real, projected", "slot": 1, "dash": True},
            {"values": observed_part(fin_infl), "label": "Financial inflation", "slot": 3},
            {"values": projected_part(fin_infl), "label": "Financial, projected", "slot": 3, "dash": True},
        ],
        rules=[{"at": 0.0, "label": ""}],
        x_ticks=[1980, 1990, 2000, 2010, 2020, 2030, int(joined_periods[-1])],
        footer=(
            f"{stamp}. The projected portion is {PROJECTION_LABEL}. Both series are computed over the "
            f"observed and projected state together, on one index base, so the rate across the join is "
            f"right rather than an artefact of rebasing."
        ),
    )

    # ---------------------------------------------------------------- tables
    trend_rows = ""
    for name in ("Y", "K_R", "K_I"):
        verdict = r.trend.get(name)
        if not verdict:
            continue
        tp = verdict["primary"]["turning_points"]
        direction = verdict["primary"]["directional_accuracy"]
        growth = verdict["primary"]["growth_correlation"]
        level = verdict["secondary"]["level_relative_residual"]
        chip = "ok" if direction and direction > 0.5 else "bad"
        trend_rows += (
            f"<tr><td>{name}</td>"
            f'<td class="n">{tp["matched"]} of {tp["observed_turning_points"]}</td>'
            f'<td class="n">{tp["mean_lead_lag_periods"]:+.1f}</td>'
            f'<td class="n"><span class="chip {chip}">{direction:.2f}</span></td>'
            f'<td class="n">{growth:+.2f}</td>'
            f'<td class="n">{level:.2f}</td></tr>'
        )

    cycle_rows = ""
    for name, estimate in r.cycles.items():
        anchored = name in r.anchored
        period = (
            f"{estimate.estimated_period:.1f}y" if estimate.estimated_period is not None else "n/a"
        )
        how = "anchored" if anchored else "band pass"
        usable = (
            '<span class="chip ok">yes</span>'
            if estimate.identifiable
            else '<span class="chip bad">no</span>'
        )
        cycle_rows += (
            f"<tr><td>{html.escape(name)}</td>"
            f'<td><span class="chip {"warn" if anchored else "ok"}">{how}</span></td>'
            f'<td class="n">{period}</td><td>{usable}</td></tr>'
        )

    synchrony_rows = ""
    for window in r.synchrony.windows:
        synchrony_rows += (
            f'<tr><td class="n">{window.start_period} to {window.end_period}</td>'
            f"<td>{html.escape(', '.join(window.cycles_in_phase))}</td>"
            f'<td class="n">{len(window.cycles_in_phase)}</td></tr>'
        )
    if not synchrony_rows:
        synchrony_rows = '<tr><td colspan="3">No window detected over the observed span.</td></tr>'

    transition_rows = ""
    for t in proj.transitions:
        transition_rows += (
            f'<tr><td class="n">{t.period}</td>'
            f"<td>{html.escape(t.from_phase)} to {html.escape(t.to_phase)}</td>"
            f'<td class="n">{t.saturation:.2f}</td></tr>'
        )
    if not transition_rows:
        transition_rows = '<tr><td colspan="3">No phase transition over the horizon.</td></tr>'

    vintage_rows = "".join(
        f"<tr><td><code>{html.escape(key)}</code></td><td>{html.escape(value)}</td></tr>"
        for key, value in sorted(r.vintage.items())
    )

    adjustment_rows = ""
    for key, entry in sorted(r.adjustments.items()):
        scale = entry.get("level_scale", entry.get("scale"))
        if scale is None:
            continue
        rationale = (entry.get("rationale") or "").strip()
        adjustment_rows += (
            f"<tr><td><code>{html.escape(key)}</code></td>"
            f'<td class="n">{float(scale):.4g}</td>'
            f"<td>{html.escape(_clip(rationale)) if rationale else 'identity, nothing applied'}</td></tr>"
        )

    # The capital normalisation deserves its own statement rather than a table cell. It is the largest
    # scale the programme applies and it removes one phase condition from view entirely.
    normalisation = r.adjustments.get("capital_normalisation") or {}
    normalisation_callout = ""
    if normalisation.get("scale"):
        normalisation_callout = f"""
<div class="callout warn">
  <p class="h">The capital normalisation, and the condition it hides</p>
  <p>Both capital stocks are scaled by <strong>{float(normalisation['scale']):.4f}</strong>, a common
  factor, so that the highest capital-to-output ratio over the window falls from
  {float(normalisation.get('observed_capital_output_ratio', float('nan'))):.2f} to
  {float(normalisation.get('target_capital_output_ratio', float('nan'))):.2f}. Without it the investment
  share <code>r = 1 - K_R/Y</code> turns negative, the reduced output equation drives output towards zero,
  and the system does not integrate at all.</p>
  <p>Because the factor is applied to <em>both</em> stocks, <code>K_R/K_I</code> is unchanged, which is why
  the phase condition above survives it. Being multiplicative, it also cannot change a growth rate, a
  direction or a turning point.</p>
  <p><strong>What it does cost:</strong> <code>K_R/Y</code> can no longer cross one inside the window, so
  the production-versus-financial transition is <em>not observable</em> on the normalised path. If someone
  asks where this economy sits on that boundary, the honest answer is that this run cannot say.</p>
</div>"""

    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in r.notes)

    derived_rows = ""
    for indicator in (
        Indicator.REAL_INFLATION,
        Indicator.FINANCIAL_INFLATION,
        Indicator.PRICE_DIVERGENCE,
        Indicator.REAL_INTEREST_RATE,
        Indicator.RETURN_ON_CAPITAL,
        Indicator.WAGE_SHARE_GROWTH,
    ):
        if indicator.value not in r.derived.values:
            continue
        values = np.asarray(r.derived.series(indicator), dtype=float)
        derived_rows += (
            f"<tr><td>{html.escape(indicator.label)}</td>"
            f'<td class="n">{values[-1]:+.4f}</td>'
            f"<td>{html.escape(indicator.units)}</td></tr>"
        )

    capital_prose = ""
    if capital is not None and capital.anchored:
        overdue = float(capital.years_into_cycle[-1]) - capital.period_years
        capital_prose = (
            f"<p>The capital cycle cannot be estimated from {int(p.size)} years of data, since a "
            f"{capital.period_years:.0f}-year cycle needs roughly two of its own periods. It is anchored "
            f"instead: reaching a saturation of {band[1]:g} places an economy "
            f"{capital.period_years:.0f} years into the cycle. {html.escape(r.name)} last crossed "
            f"{band[1]:g} in <strong>{capital.reference_year:.1f}</strong>, which puts it "
            f"<strong>{float(capital.years_into_cycle[-1]):.0f} years into a "
            f"{capital.period_years:.0f}-year cycle</strong>, that is about {abs(overdue):.0f} years "
            f"{'past' if overdue > 0 else 'short of'} the reordering point.</p>"
        )
    elif capital is not None:
        capital_prose = (
            f"<p>The capital cycle is <strong>not anchored</strong> for {html.escape(r.name)}: its "
            f"saturation never reaches {band[1]:g} over this window, and that crossing is what dates the "
            f"cycle. No position is reported, because placing a {capital.period_years:.0f}-year cycle "
            f"from a {int(p.size)}-year sample without the anchor would be a guess.</p>"
        )

    gold_line = (
        ""
        if r.gold_enabled
        else (
            "<li><strong>The stock-to-gold model is switched off.</strong> Its module and tests are "
            "retained and correct, and it is simply not part of the current output. Nothing in this "
            "document depends on it.</li>"
        )
    )

    divergence_now = float(divergence[-1])
    divergence_peak_index = int(np.nanargmax(divergence))
    unsec_peak_index = int(np.argmax(unsec))

    # No companion guide to link. This document is the training material, so it says so rather than
    # pointing at a file that is not there: a dead link in a training document is worse than no link.
    guide_reference = "This is the programme's training document. It covers"

    return f"""<title>{html.escape(r.name)}: reading the economy through the field model</title>

<style>{STYLE}</style>

<div class="shell">

<header class="masthead">
  <p class="eyebrow">SIM Research Institute AG &middot; Internal training &middot; Schulung</p>
  <h1>{html.escape(r.name)} through the field model</h1>
  <p class="standfirst">A worked reading of one economy. Every figure on this page was computed by the
  model on the vintage stamped below, not transcribed, so the page can be regenerated and the numbers
  will move with the data.</p>
  <div class="stamp">
    <span><b>Calibration window</b> {r.window[0]} to {r.window[1]}</span>
    <span><b>Periods</b> {int(p.size)}</span>
    <span><b>Projection</b> {int(proj.periods[0])} to {int(proj.periods[-1])}</span>
    <span><b>Programme</b> v{__version__}</span>
  </div>
</header>

<h2>What this document is</h2>
<p class="lede">And what to read first.</p>
<p>{guide_reference} the apparatus where the reading needs it, and it is self-contained: there is no
companion guide to consult. It takes {html.escape(r.name)}, runs the whole pipeline, and lays out what the
model says, in the order a reader should take it.</p>
<p>Read the <strong>binding condition</strong> first and the numbers second. The single most common error
in using this apparatus is to quote a level without saying which rule fired, and the tiles below are
arranged so that cannot happen.</p>

<div class="tiles">{''.join(tiles)}</div>

<div class="callout">
  <p class="h">The one thing to take away</p>
  <p>{html.escape(r.name)} is in <strong>{html.escape(r.classification.phase.label)}</strong>, and it is
  there because <strong>{html.escape(r.classification.rules_fired[0]) if r.classification.rules_fired
  else 'no single rule'}</strong>. Its saturation of {now_sat:.2f} is
  {'inside' if band[0] <= now_sat <= band[1] else 'outside'} the balanced band, so the phase does
  <em>not</em> come from the saturation level. Anyone who reports the phase and the band position without
  saying which of them decided the classification has told half the story.</p>
</div>

<h2>Where the economy sits</h2>
<p class="lede">The saturation axis, its band, and the crossing history.</p>

<p>Saturation ran from {float(sat[0]):.2f} in {int(p[0])} to a peak of <strong>{peak_value:.2f} in
{peak_year}</strong>, and stands at <strong>{now_sat:.2f}</strong> in {int(p[-1])}, that is
{abs(now_sat - peak_value):.2f} below the peak. It first entered the band in
{crossed_lower if crossed_lower else 'n/a'} and first crossed the upper bound of {band[1]:g} in
{crossed_upper if crossed_upper else 'n/a'}, spending {int((sat >= band[1]).sum())} of {int(p.size)}
years at or above it.</p>

{chart_saturation}

<div class="callout warn">
  <p class="h">Read this before quoting the level</p>
  <p>The saturation axis carries a <strong>credit uplift of
  {float(r.adjustments.get('saturation', {}).get('level_scale', 1.0)):.2f}</strong>, because the published
  BIS series omits credit to the financial sector and captures non-bank intermediation incompletely. The
  level on this chart is therefore not a published figure. The uplift is multiplicative and applied
  identically to every economy, so it cannot change a growth rate, a direction, a turning point, or the
  ordering of the cross-section. What it changes is where the economy sits against the band, which is
  exactly its purpose.</p>
</div>

<h2>Why the phase is what it is</h2>
<p class="lede">The condition that actually fired.</p>

<p>Real capital stood at {now_rf:.2f} times financial capital in {int(p[-1])}, against
{float(rf[0]):.2f} in {int(p[0])}.
{f'It fell below one in <strong>{rf_below_year}</strong> and has stayed there for {int(rf_below.size)} of the years since.' if rf_below_year else 'It has not fallen below one.'}
That condition, and not the saturation level, is what places the economy in its current phase.</p>

<p>This ratio matters out of proportion to its simplicity: it is a ratio of two capital stocks, so it is
<strong>invariant to every level adjustment the programme applies</strong>. The credit uplift and the
capital normalisation both scale numerator and denominator alike. It is the one phase condition the scale
problem cannot reach, which is why it is trustworthy where a level is not.</p>

{chart_real_financial}

<h2>The financial economy against the real one</h2>
<p class="lede">Two measures, a common turning point, and one identity worth knowing.</p>

<p>Capital saturation and the unsecured-asset gap measure different things. They agree on when the
financial economy turned: saturation peaks in <strong>{peak_year}</strong> and the gap in
<strong>{int(p[unsec_peak_index])}</strong>, and both have retraced since without returning to their
pre-2000 levels. The gap ran from {float(unsec[0]):.2f} of output in {int(p[0])} to a peak of
{float(unsec.max()):.2f} in {int(p[unsec_peak_index])} and stands at {float(unsec[-1]):.2f}.</p>

{chart_two}

<div class="callout">
  <p class="h">Price divergence is the unsecured-asset gap, not a second opinion on it</p>
  <p>The derived indicator "asset prices against real prices" stands at
  <strong>{divergence_now:.2f}</strong>, against 1.00 in {int(p[0])} and a peak of
  {float(np.nanmax(divergence)):.2f} in {int(p[divergence_peak_index])}. Indexed to its first year it is
  <strong>the same series as the unsecured-asset gap</strong>, with a measured correlation of
  {gap_divergence_correlation:.6f} on this run.</p>
  <p>That is an identity rather than a coincidence, and it follows from the derivation in book chapter 7.
  Splitting the quantity equation into a real and a financial sector and holding both transaction
  frequencies constant gives <code>P_R . H_R = Y</code> and
  <code>P_I . H_I = K_R + K_I - Y</code>, so the ratio of the two price levels is
  <code>(K_R + K_I - Y) / Y</code> up to a constant, which is the definition of the gap.</p>
  <p>The practical consequence: <strong>do not quote both as independent evidence.</strong> They are one
  measurement expressed in two units, and treating them as two agreeing indicators would double-count it.
  Price divergence is therefore omitted from the chart above rather than drawn on top of the gap.</p>
</div>

<div class="scroll"><table>
<tr><th>Derived indicator, latest</th><th>value</th><th>units</th></tr>
{derived_rows}
</table></div>

{chart_inflation}

<h2>Where the economy sits in the cycles</h2>
<p class="lede">Two cycles are estimated. Two are anchored, because they cannot be estimated.</p>

{capital_prose}

<p>The innovation cycle is anchored the same way and for the same reason, on a low in
<strong>{innovation.reference_year:.0f}</strong> with a period of {innovation.period_years:.0f} years,
applied identically to every economy because it is a global technological cycle rather than a national
one. On this vintage that low is
<strong>{abs(float(innovation.reference_year) - float(p[-1])):.0f} years
{'ahead' if float(innovation.reference_year) >= float(p[-1]) else 'behind'}</strong>.</p>

<div class="scroll"><table>
<tr><th>Cycle</th><th>how positioned</th><th>period</th><th>usable</th></tr>
{cycle_rows}
</table></div>

<p>Anchoring the two long cycles is what lets them enter the synchrony analysis at all. While they were
reported as unidentifiable they were excluded from it, which made the synchronisation window a statement
about the business and credit cycles alone.</p>

<div class="scroll"><table>
<tr><th>Synchronisation window</th><th>cycles in phase</th><th>count</th></tr>
{synchrony_rows}
</table></div>

<p class="fig-note">Windows are detected over the observed span only. The anchored cycles could be
evaluated at any future date, but the two band-passed cycles cannot be extrapolated, so a window beyond
{int(p[-1])} would rest mostly on assumption. The distance to each anchor, in the tiles above, is where a
forward reading properly comes from.</p>

<h2>What the model projects<span class="label-projected">{PROJECTION_LABEL}</span></h2>
<p class="lede">A model consequence, recomputed from this vintage.</p>

<p>Run forward {int(proj.periods.size)} periods from the observed end state, with the policy levers at
their base case, saturation goes from {now_sat:.2f} to
<strong>{float(proj.saturation[-1]):.2f}</strong> and the economy ends in
<strong>{html.escape(proj.phase_at_end)}</strong>.</p>

<div class="scroll"><table>
<tr><th>Period</th><th>transition</th><th>saturation</th></tr>
{transition_rows}
</table></div>

<div class="callout">
  <p class="h">This is the reordering, not a failure of the model</p>
  <p>A projection that decays a saturated economy to a low capital base, ending in the least saturated
  phase, is the capital-cycle reordering. Book section 20.3 states it: the capital cycle "is directional.
  It progresses through the phase structure, terminates in saturation, and is followed by a reordering
  that resets the system at a lower capital base rather than returning it to the state it left." Chapter 8
  gives the mechanism, that the claims of financial capital eventually exceed what real output can
  provide and the system must reset them. Reaching the foundation phase after a reset is the framework's
  prediction, not a contradiction of it.</p>
  <p>The two resolutions, debt deflation and hyperinflation, are two routes to that same reset. The model
  does not choose between them.</p>
</div>

<h2>How much weight these numbers bear</h2>
<p class="lede">The criteria, in the order they are meant to be read.</p>

<p>The model is judged on whether it turns when the economy turns, then on direction, then on the
correlation of growth rates. The level residual is a secondary diagnostic and is reported so that neither
reading can be quoted alone.</p>

<div class="scroll"><table>
<tr><th>Series</th><th>turning points</th><th>mean lead</th><th>direction</th><th>growth corr.</th>
<th>level residual</th></tr>
{trend_rows}
</table></div>

<p><strong>Read this table honestly.</strong> Direction is strong. The turning-point hit rate is weak, and
the growth correlation for output is near zero or negative. The operational consequence is stated in the
projection itself: <em>read the ordering of events, not the dates</em>. A projected transition year from
this model is not a forecast of that year, and quoting one as though it were is the error the criteria
exist to prevent.</p>

<p>Weakly identified parameters on this run: {html.escape(', '.join(r.weakly_identified)) if r.weakly_identified else 'none'}.
A weakly identified parameter is held to its prior and stress-tested rather than fitted harder.</p>

<h2>What was adjusted, and what adjustment cannot do</h2>
<p class="lede">Every scale applied to the source data, with its reason.</p>

<div class="scroll"><table>
<tr><th>Quantity</th><th>scale</th><th>rationale</th></tr>
{adjustment_rows}
</table></div>

<p>Every adjustment here is a <strong>multiplicative level scale</strong>, and that is a guarantee rather
than a convention: scaling a series by a constant leaves its growth rates, its direction and its turning
points identical, because the derivative of a log is unchanged by a constant factor. No adjustment this
programme can produce is capable of altering any of the primary criteria above. An additive drift
correction would be capable of it, and is therefore not implemented at all rather than guarded.</p>
{normalisation_callout}

<h2>What this reading does not include</h2>
<p class="lede">Stated, so that its absence is not mistaken for a finding.</p>

<ul>
{gold_line}
<li><strong>The Health of Nations Indicator is not scored here.</strong> Its fifteen indicators are not
derivable from the three-body state and the data layer does not yet read the published export, so no
composite is produced. A composite computed from a thin subset would be worse than none.</li>
<li><strong>The 25-state regime distribution is not produced.</strong> The kernel apparatus is complete,
but nothing yet assesses the four segments from indicators, and inventing the segment assessments would
produce a picture of the kernels rather than of the economy.</li>
<li><strong>Only the two short cycles are estimated.</strong> The other two are anchored from supplied
structure, and the tables above mark which is which.</li>
</ul>

<h3>Data caveats carried by this run</h3>
<ul>{note_items}</ul>

<h2>Provenance</h2>
<p class="lede">Every series and the vintage it came from.</p>

<div class="scroll"><table>
<tr><th>Series</th><th>source and vintage</th></tr>
{vintage_rows}
</table></div>

<footer class="doc">
  <p><strong>{html.escape(DISCLAIMER.strip())}</strong></p>
  <p>Generated by <code>tools/build_schulung.py</code> from the model at programme version
  {__version__}. Regenerate rather than edit: every figure above is computed, and editing the page by hand
  would break the guarantee that it agrees with the model. Projected paths are labelled
  {PROJECTION_LABEL} wherever they appear.</p>
</footer>

</div>
"""


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        print("usage: python tools/build_schulung.py <economy> [output.html] [--offline]")
        return 2

    code = argv[1]
    offline = "--offline" in argv
    positional = [a for a in argv[2:] if not a.startswith("--")]
    destination = Path(positional[0]) if positional else REPOSITORY_ROOT / "docs" / f"schulung_{code}.html"

    if code not in config_module.available_economies():
        print(f"unknown economy {code!r}. Available: {', '.join(config_module.available_economies())}")
        return 2

    print(f"gathering {code} ...")
    reading = gather(code, offline=offline)
    print(f"  window {reading.window[0]} to {reading.window[1]}, phase {reading.classification.phase.label}")

    document = render(reading)
    for forbidden in ("—", "–"):
        if forbidden in document:
            raise SystemExit(
                f"the generated document contains {forbidden!r}, which the house rules forbid"
            )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
