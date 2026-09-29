"""Static charts for the section 6 outputs.

Brief section 6 requires that every chart carry the calibration window, the data vintage, and an
"illustrative or model-derived" label on any projected path, in British spelling with no em-dashes.

Those requirements are enforced by `stamp`, which every chart function here calls. `ChartContext` cannot
be built without a window and a vintage, and a chart declared as projected cannot be stamped without the
label. Requirements that depend on each chart author remembering them are not requirements.

Charts are returned as figures rather than written to disk, so a caller can compose or embed them. `save`
writes one out at a consistent size and resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

# A non-interactive backend, chosen explicitly so that a run on a headless machine or inside a test does
# not depend on whatever display happens to be configured.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from macrofield.reporting.export import DISCLAIMER, PROJECTION_LABEL  # noqa: E402

#: Figure size in inches for a single chart.
FIGURE_SIZE = (9.0, 5.5)

#: Resolution for written figures.
DPI = 150

#: Colours. Chosen once here so that real capital, financial capital and output read consistently across
#: every chart, which matters more than any individual chart looking good.
COLOURS = {
    "output": "#33456b",
    "real_capital": "#14655f",
    "financial_capital": "#6a3d88",
    "observed": "#131720",
    "simulated": "#a13527",
    "band": "#9a6414",
    "below": "#2f6b4f",
    "inside": "#9a6414",
    "above": "#a13527",
    "grid": "#d3d9e3",
}

#: Line style used for anything the model produced rather than observed.
SIMULATED_STYLE = {"linestyle": "--", "linewidth": 1.6}


class ChartError(ValueError):
    """Raised when a chart cannot be produced within the reporting requirements."""


@dataclass
class ChartContext:
    """The provenance every chart must display.

    Attributes:
        economy: The economy's name as it should read on the chart.
        calibration_window: The (first, last) period calibrated over.
        data_vintage: A short vintage description, for example "PWT 10.01, BIS 2026-07".
        adjustments_applied: Whether a standardising level adjustment was applied to the source data.
    """

    economy: str
    calibration_window: tuple[int, int]
    data_vintage: str
    adjustments_applied: bool = False

    def __post_init__(self) -> None:
        first, last = self.calibration_window
        if first > last:
            raise ChartError(f"the calibration window {self.calibration_window} runs backwards")
        if not self.data_vintage.strip():
            raise ChartError(
                "a chart context must carry a data vintage. Brief section 6 requires every chart to "
                "state it, so it cannot be blank."
            )

    def footer(self, projected: bool) -> str:
        """The footer text stamped on every chart."""
        first, last = self.calibration_window
        parts = [
            f"Calibration window {first} to {last}",
            f"data vintage {self.data_vintage}",
        ]
        if self.adjustments_applied:
            parts.append(
                "standardising level adjustment applied, so levels are not published levels "
                "(growth, direction and turning points unaffected)"
            )
        if projected:
            parts.append(PROJECTION_LABEL)
        parts.append(DISCLAIMER)
        return " . ".join(parts)


def stamp(figure: plt.Figure, context: ChartContext, projected: bool = False) -> plt.Figure:
    """Apply the mandatory footer to a figure.

    Every chart function in this module calls this. A chart that skips it is missing the window, the
    vintage and, where relevant, the projection label.
    """
    figure.text(
        0.01,
        0.012,
        context.footer(projected),
        fontsize=6.2,
        color="#4a5364",
        wrap=True,
        va="bottom",
    )
    figure.subplots_adjust(bottom=0.22)
    return figure


def _style(axes: plt.Axes, title: str, ylabel: str, xlabel: str = "Period") -> plt.Axes:
    """Apply the shared axis furniture."""
    axes.set_title(title, fontsize=11, loc="left", pad=10)
    axes.set_ylabel(ylabel, fontsize=9)
    axes.set_xlabel(xlabel, fontsize=9)
    axes.grid(True, color=COLOURS["grid"], linewidth=0.6, alpha=0.8)
    axes.set_axisbelow(True)
    axes.tick_params(labelsize=8)
    for spine in ("top", "right"):
        axes.spines[spine].set_visible(False)
    return axes


def save(figure: plt.Figure, path: Path) -> Path:
    """Write a figure to disk and close it.

    Closing matters: a long comparative run produces dozens of figures, and matplotlib keeps every open
    one in memory until told otherwise.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(figure)
    return path


def trajectory_chart(
    context: ChartContext,
    periods: Sequence[Any],
    observed: Mapping[str, Sequence[float]],
    simulated: Mapping[str, Sequence[float]] | None = None,
) -> plt.Figure:
    """The three-body trajectory with the calibration fit shown against the data.

    Brief section 6. Each quantity is rebased to its own first observation, because Y, K_R and K_I differ
    by an order of magnitude and plotting the levels together makes the smallest of them a flat line.
    Rebasing is a multiplicative constant, so it changes nothing about the dynamics being compared.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    labels = {
        "Y": ("Output", COLOURS["output"]),
        "K_R": ("Real capital", COLOURS["real_capital"]),
        "K_I": ("Financial capital", COLOURS["financial_capital"]),
    }

    for name, (label, colour) in labels.items():
        values = np.asarray(observed.get(name, []), dtype=float)
        if values.size == 0:
            continue
        base = values[0] if values[0] != 0.0 else 1.0
        axes.plot(periods, 100.0 * values / base, color=colour, linewidth=1.8, label=f"{label}, observed")

        if simulated:
            fitted = np.asarray(simulated.get(name, []), dtype=float)
            if fitted.size == values.size:
                axes.plot(
                    periods,
                    100.0 * fitted / base,
                    color=colour,
                    label=f"{label}, fitted",
                    **SIMULATED_STYLE,
                )

    _style(axes, f"{context.economy}: three-body trajectory", "Index, first period = 100")
    axes.legend(fontsize=7.5, frameon=False, ncols=2)
    return stamp(figure, context)


def phase_timeline_chart(
    context: ChartContext,
    periods: Sequence[Any],
    saturation: Sequence[float],
    phases: Sequence[int],
    band: tuple[float, float] = (2.5, 3.5),
    ceiling: float = 3.0,
    foundation_ceiling: float = 1.0,
) -> plt.Figure:
    """The saturation path with the phase boundaries and the current phase marked.

    Brief section 6 asks for the phase timeline with transition boundaries and the distance to the next
    boundary, so the current reading is annotated with that distance rather than left to be read off.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    values = np.asarray(saturation, dtype=float)

    lower, upper = band
    axes.axhspan(lower, upper, color=COLOURS["band"], alpha=0.12, label=f"Balanced band {lower} to {upper}")
    axes.axhline(ceiling, color=COLOURS["band"], linestyle=":", linewidth=1.2, label=f"Phase 3 ceiling {ceiling}")
    axes.axhline(
        foundation_ceiling,
        color=COLOURS["below"],
        linestyle=":",
        linewidth=1.2,
        label=f"Foundation ceiling {foundation_ceiling}",
    )
    axes.plot(periods, values, color=COLOURS["output"], linewidth=2.0, label="Credit saturation")

    # Mark each phase transition, which is the information the timeline exists to convey.
    phase_array = np.asarray(phases, dtype=int)
    for index in range(1, phase_array.size):
        if phase_array[index] != phase_array[index - 1]:
            axes.axvline(periods[index], color=COLOURS["simulated"], linewidth=0.9, alpha=0.7)
            axes.annotate(
                f"to phase {phase_array[index]}",
                xy=(periods[index], axes.get_ylim()[1]),
                fontsize=6.5,
                rotation=90,
                va="top",
                ha="right",
                color=COLOURS["simulated"],
            )

    if values.size:
        current = float(values[-1])
        distance = ceiling - current
        axes.annotate(
            f"latest {current:.2f}, {abs(distance):.2f} "
            f"{'below' if distance > 0 else 'above'} the Phase 3 ceiling",
            xy=(periods[-1], current),
            xytext=(-8, 10),
            textcoords="offset points",
            fontsize=7.5,
            ha="right",
            color=COLOURS["output"],
        )

    _style(axes, f"{context.economy}: credit saturation and phase boundaries", "Credit to non-financial sector over GDP")
    axes.legend(fontsize=7.5, frameon=False)
    return stamp(figure, context)


def unsecured_assets_chart(
    context: ChartContext,
    periods: Sequence[Any],
    ratio: Sequence[float],
    accelerating: Sequence[bool] | None = None,
    collapsing: Sequence[bool] | None = None,
) -> plt.Figure:
    """The unsecured-asset gap with the acceleration and collapse signatures highlighted.

    Brief section 6 names both signatures, so they are shaded rather than left for a reader to infer from
    the curvature.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    values = np.asarray(ratio, dtype=float)
    axes.plot(periods, values, color=COLOURS["financial_capital"], linewidth=2.0, label="Unsecured assets over output")

    period_array = np.asarray(periods)
    if accelerating is not None:
        mask = np.asarray(accelerating, dtype=bool)
        if mask.any():
            axes.fill_between(
                period_array,
                axes.get_ylim()[0],
                values,
                where=mask,
                color=COLOURS["inside"],
                alpha=0.18,
                label="Accelerating, the Phase 3 signature",
            )
    if collapsing is not None:
        mask = np.asarray(collapsing, dtype=bool)
        if mask.any():
            axes.fill_between(
                period_array,
                axes.get_ylim()[0],
                values,
                where=mask,
                color=COLOURS["above"],
                alpha=0.20,
                label="Contracting, the Phase 4 signature",
            )

    _style(axes, f"{context.economy}: unsecured assets", "Ratio to output")
    axes.legend(fontsize=7.5, frameon=False)
    return stamp(figure, context)


def honi_chart(
    context: ChartContext,
    dimensions: Mapping[str, float],
    composite: float | None,
    stage: str | None,
    saturation_percentage: float | None = None,
    band: tuple[float, float] = (250.0, 350.0),
) -> plt.Figure:
    """The HoNI scorecard: the three sub-scores, the composite, and saturation against the band.

    The axis is labelled with its direction, because five being healthiest is counter-intuitive and a
    chart is exactly where somebody reads a score without reading the caption.
    """
    figure, (left, right) = plt.subplots(1, 2, figsize=(FIGURE_SIZE[0], FIGURE_SIZE[1]), width_ratios=[3, 2])

    names = list(dimensions)
    values = [dimensions[name] for name in names]
    positions = np.arange(len(names))
    left.barh(positions, values, color=COLOURS["output"], height=0.55)
    left.set_yticks(positions)
    left.set_yticklabels([name.replace("_", " ").capitalize() for name in names], fontsize=8)
    left.set_xlim(1.0, 5.0)
    left.invert_yaxis()
    _style(left, "Sub-indices", "", xlabel="1 least healthy to 5 healthiest")

    if composite is not None:
        left.axvline(composite, color=COLOURS["simulated"], linewidth=1.6)
        left.annotate(
            f"composite {composite:.2f}" + (f", {stage}" if stage else ""),
            xy=(composite, len(names) - 0.4),
            fontsize=7.5,
            ha="left",
            color=COLOURS["simulated"],
        )

    if saturation_percentage is not None:
        lower, upper = band
        right.axhspan(lower, upper, color=COLOURS["band"], alpha=0.14)
        colour = (
            COLOURS["above"]
            if saturation_percentage > upper
            else COLOURS["inside"]
            if saturation_percentage >= lower
            else COLOURS["below"]
        )
        right.bar([0], [saturation_percentage], color=colour, width=0.5)
        right.set_xticks([])
        right.annotate(
            f"{saturation_percentage:.0f}%",
            xy=(0, saturation_percentage),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=colour,
        )
        _style(right, f"Capital saturation against {band[0]:.0f} to {band[1]:.0f}%", "Per cent of GDP", xlabel="")
    else:
        right.axis("off")
        right.text(0.5, 0.5, "Capital saturation\nnot available", ha="center", va="center", fontsize=8)

    figure.suptitle(f"{context.economy}: Health of Nations scorecard", fontsize=11, x=0.02, ha="left")
    return stamp(figure, context)


def stock_gold_chart(
    context: ChartContext,
    periods: Sequence[Any],
    contributions: Mapping[str, Sequence[float]],
    gold_over_equity: Sequence[float],
    dominant_driver: str | None = None,
) -> plt.Figure:
    """The gold-to-equity path with the three driver contributions shown separately.

    Brief section 6 requires the contributions to be separable and the dominant driver named, so the
    drivers are stacked on their own axis rather than summed into the path.
    """
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(FIGURE_SIZE[0], FIGURE_SIZE[1] + 1.0), height_ratios=[2, 2], sharex=True
    )

    top.plot(periods, np.asarray(gold_over_equity, dtype=float), color=COLOURS["band"], linewidth=2.0)
    _style(top, f"{context.economy}: gold over equities", "Ratio, anchored", xlabel="")
    if dominant_driver:
        top.annotate(
            f"dominant driver: {dominant_driver.replace('_', ' ')}",
            xy=(0.99, 0.06),
            xycoords="axes fraction",
            ha="right",
            fontsize=7.5,
            color=COLOURS["band"],
        )

    palette = [COLOURS["output"], COLOURS["real_capital"], COLOURS["financial_capital"]]
    for position, (name, values) in enumerate(contributions.items()):
        bottom.plot(
            periods,
            np.asarray(values, dtype=float),
            color=palette[position % len(palette)],
            linewidth=1.5,
            label=name.replace("_", " "),
        )
    bottom.axhline(0.0, color=COLOURS["observed"], linewidth=0.8)
    _style(bottom, "Driver contributions to the change in the ratio", "Contribution")
    bottom.legend(fontsize=7.5, frameon=False)

    # This path is integrated forward from an anchor, so it is a projection.
    return stamp(figure, context, projected=True)


def regime_chart(
    context: ChartContext,
    probabilities: Sequence[float],
    tail_bins: int = 5,
    five_regime: Mapping[str, float] | None = None,
) -> plt.Figure:
    """The 25-state distribution with the crisis tail made visible.

    Brief section 0.8 requires the tail to carry live weight and section 6 requires it to be visible, so
    the tail bins are coloured distinctly and the tail mass is annotated rather than left to be summed
    by eye.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    values = np.asarray(probabilities, dtype=float)
    states = np.arange(1, values.size + 1)

    colours = [
        COLOURS["above"] if state <= tail_bins else COLOURS["output"] for state in states
    ]
    axes.bar(states, values, color=colours, width=0.75)

    tail_mass = float(values[:tail_bins].sum())
    axes.annotate(
        f"crisis tail, states 1 to {tail_bins}: {tail_mass:.1%}",
        xy=(tail_bins + 0.5, max(values) * 0.9 if values.size else 0.0),
        fontsize=7.5,
        color=COLOURS["above"],
    )

    if five_regime:
        summary = ", ".join(f"{name} {share:.0%}" for name, share in five_regime.items())
        axes.annotate(
            summary,
            xy=(0.99, 0.94),
            xycoords="axes fraction",
            ha="right",
            fontsize=7,
            color="#4a5364",
        )

    axes.set_xticks([1, 5, 10, 15, 20, 25])
    _style(
        axes,
        f"{context.economy}: regime distribution over 25 states",
        "Probability",
        xlabel="State, 1 cautious to 25 aggressive",
    )
    return stamp(figure, context)


def cycle_chart(
    context: ChartContext,
    spectrum_periods: Sequence[float],
    spectrum_power: Sequence[float],
    priors: Mapping[str, float] | None = None,
    synchronisation_window: tuple[Any, Any] | None = None,
) -> plt.Figure:
    """The cycle spectrum with the prior periods marked.

    The priors are drawn as reference lines rather than as results, because they are inputs to the
    band-pass extraction. Where a synchronisation window was detected it is named in the annotation and
    labelled a projection, since it is recomputed from the vintage each run.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    axes.semilogx(
        np.asarray(spectrum_periods, dtype=float),
        np.asarray(spectrum_power, dtype=float),
        color=COLOURS["output"],
        linewidth=1.6,
    )

    if priors:
        for name, period in priors.items():
            axes.axvline(period, color=COLOURS["band"], linestyle=":", linewidth=1.0)
            axes.annotate(
                f"{name} {period:g}y",
                xy=(period, axes.get_ylim()[1]),
                fontsize=6.5,
                rotation=90,
                va="top",
                ha="right",
                color=COLOURS["band"],
            )

    projected = synchronisation_window is not None
    if projected:
        first, last = synchronisation_window
        axes.annotate(
            f"cycles in phase over {first} to {last} on this vintage",
            xy=(0.99, 0.06),
            xycoords="axes fraction",
            ha="right",
            fontsize=7.5,
            color=COLOURS["simulated"],
        )

    _style(axes, f"{context.economy}: cycle spectrum", "Power", xlabel="Period, years, log scale")
    return stamp(figure, context, projected=projected)


def comparative_chart(
    context: ChartContext,
    values: Mapping[str, float],
    band: tuple[float, float] = (2.5, 3.5),
    title: str = "Credit saturation across economies",
) -> plt.Figure:
    """A comparative bar chart across economies, with the band shaded.

    Brief section 0.6 requires the scorer to be comparative, and this is the chart that carries it. Bars
    are coloured by band position so the reading is legible without consulting the axis.
    """
    figure, axes = plt.subplots(figsize=FIGURE_SIZE)
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in ordered]
    heights = [value for _, value in ordered]
    lower, upper = band

    colours = [
        COLOURS["above"] if v > upper else COLOURS["inside"] if v >= lower else COLOURS["below"]
        for v in heights
    ]
    positions = np.arange(len(names))
    axes.bar(positions, heights, color=colours, width=0.62)
    axes.axhspan(lower, upper, color=COLOURS["band"], alpha=0.12)
    axes.set_xticks(positions)
    axes.set_xticklabels(names, fontsize=8, rotation=30, ha="right")

    for position, value in zip(positions, heights):
        axes.annotate(
            f"{value:.2f}",
            xy=(position, value),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=7.5,
        )

    _style(axes, title, "Ratio to GDP", xlabel="")
    return stamp(figure, context)
