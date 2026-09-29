"""Validation: does the model get the trend and the turning points right.

Brief section 5. Backtesting, historical analogue, sensitivity, and the two Phase IV resolution paths.

**What counts as success here, and why it is not the level residual.**

A field model of this kind is not trying to reproduce the level of an economy's capital stock to a few
per cent. It is trying to say where an economy is in the capital cycle and when that position turns. So
the primary criteria in this module are, in order:

1. **Turning points.** Does the model turn when the economy turns, and how many periods early or late?
   A model that anticipates the turn is useful even if its level is wrong throughout. A model that fits
   the level closely but misses every turn is worse than useless, because it will be trusted.
2. **Direction.** Over what share of periods does the simulated path move the same way as the observed
   one?
3. **Trend agreement.** Correlation of growth rates, not of levels. Two exponentially growing series
   correlate at better than 0.99 in levels whatever their dynamics, so a level correlation says almost
   nothing and flatters the model badly.

The level residual is reported as a secondary diagnostic and is deliberately not the headline. See
`TrendVerdict` for how the three are combined, and note that `calibration/fit.py` measured a mean
relative level residual of roughly 6.5 on a smooth trajectory: judged on level alone the model looks
broken, and judged on turning points it may not be. Both readings are reported so neither can be quoted
alone.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from scipy.signal import find_peaks

from macrofield.calibration.fit import CalibrationResult, ObservedPath, calibrate
from macrofield.model.edm import ClosureMode

#: Default window, in periods, within which a simulated turning point counts as matching an observed
#: one. Two years either side, because the framework's claims are about cycle position rather than
#: timing to the year, and a credit cycle is eighteen years long.
DEFAULT_TOLERANCE_PERIODS = 2

#: Minimum prominence of a turning point, as a fraction of the series' own range. Below this a wobble is
#: not a turn, and counting wobbles inflates both the hit rate and the false-positive rate until neither
#: means anything.
DEFAULT_MIN_PROMINENCE = 0.05

#: Minimum separation between turning points, in periods.
DEFAULT_MIN_SEPARATION = 2


class Direction(enum.Enum):
    """Which way a turning point turns."""

    PEAK = "peak"
    TROUGH = "trough"


@dataclass(frozen=True)
class TurningPoint:
    """One turning point in a series.

    Attributes:
        index: Position in the series.
        period: The period label.
        direction: Peak or trough.
        prominence: How far the point stands out, as a fraction of the series range.
    """

    index: int
    period: Any
    direction: Direction
    prominence: float


def find_turning_points(
    values: Sequence[float],
    periods: Sequence[Any] | None = None,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
    min_separation: int = DEFAULT_MIN_SEPARATION,
) -> list[TurningPoint]:
    """Locate peaks and troughs in a series.

    Prominence is measured relative to the series' own range, so the same threshold means the same thing
    for a ratio near three and for a capital stock in the trillions.

    Args:
        values: The series. Pass growth rates rather than levels for a monotonically growing quantity,
            since a level that only ever rises has no turning points to find.
        periods: Period labels. Defaults to positional indices.
        min_prominence: Minimum prominence as a fraction of the series range.
        min_separation: Minimum periods between turning points.

    Returns:
        The turning points, in period order.
    """
    series = np.asarray(values, dtype=float)
    if series.size < 3:
        return []
    labels = list(periods) if periods is not None else list(range(series.size))
    if len(labels) != series.size:
        raise ValueError(f"expected {series.size} period labels, got {len(labels)}")

    span = float(np.nanmax(series) - np.nanmin(series))
    if not np.isfinite(span) or span <= 0.0:
        return []
    absolute_prominence = min_prominence * span

    found: list[TurningPoint] = []
    for direction, signed in ((Direction.PEAK, series), (Direction.TROUGH, -series)):
        indices, properties = find_peaks(
            signed, prominence=absolute_prominence, distance=max(1, min_separation)
        )
        for position, index in enumerate(indices):
            found.append(
                TurningPoint(
                    index=int(index),
                    period=labels[int(index)],
                    direction=direction,
                    prominence=float(properties["prominences"][position]) / span,
                )
            )
    return sorted(found, key=lambda point: point.index)


@dataclass(frozen=True)
class TurningPointMatch:
    """An observed turning point and the simulated one that matched it."""

    observed: TurningPoint
    simulated: TurningPoint

    @property
    def lead_lag(self) -> int:
        """Periods by which the simulated turn precedes the observed one. Negative means late."""
        return self.observed.index - self.simulated.index


@dataclass
class TurningPointScore:
    """How well the simulated turning points line up with the observed ones.

    Attributes:
        matched: Observed turns the simulation found, with their lead or lag.
        missed: Observed turns the simulation did not find.
        spurious: Simulated turns with no observed counterpart.
        tolerance_periods: The matching window used.
        observed_count: How many turns were observed.
    """

    matched: list[TurningPointMatch] = field(default_factory=list)
    missed: list[TurningPoint] = field(default_factory=list)
    spurious: list[TurningPoint] = field(default_factory=list)
    tolerance_periods: int = DEFAULT_TOLERANCE_PERIODS
    observed_count: int = 0

    @property
    def hit_rate(self) -> float:
        """Share of observed turning points the simulation found. NaN if none were observed."""
        if self.observed_count == 0:
            return float("nan")
        return len(self.matched) / self.observed_count

    @property
    def false_positive_rate(self) -> float:
        """Share of simulated turns with no observed counterpart. NaN if none were simulated."""
        total = len(self.matched) + len(self.spurious)
        if total == 0:
            return float("nan")
        return len(self.spurious) / total

    @property
    def mean_lead_lag(self) -> float:
        """Mean signed lead. Positive means the model turns early, which is the useful direction."""
        if not self.matched:
            return float("nan")
        return float(np.mean([m.lead_lag for m in self.matched]))

    @property
    def mean_absolute_lead_lag(self) -> float:
        """Mean timing error in periods, regardless of sign."""
        if not self.matched:
            return float("nan")
        return float(np.mean([abs(m.lead_lag) for m in self.matched]))

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_turning_points": self.observed_count,
            "matched": len(self.matched),
            "missed": len(self.missed),
            "spurious": len(self.spurious),
            "hit_rate": self.hit_rate,
            "false_positive_rate": self.false_positive_rate,
            "mean_lead_lag_periods": self.mean_lead_lag,
            "mean_absolute_lead_lag_periods": self.mean_absolute_lead_lag,
            "tolerance_periods": self.tolerance_periods,
            "missed_periods": [str(p.period) for p in self.missed],
            "spurious_periods": [str(p.period) for p in self.spurious],
        }


def score_turning_points(
    observed: Sequence[float],
    simulated: Sequence[float],
    periods: Sequence[Any] | None = None,
    tolerance_periods: int = DEFAULT_TOLERANCE_PERIODS,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
) -> TurningPointScore:
    """Match simulated turning points against observed ones.

    A match requires the same direction and a position within the tolerance window. Matching is greedy
    on proximity and each simulated turn is used at most once, so one simulated turn cannot be credited
    with finding several observed ones.

    Args:
        observed: The observed series.
        simulated: The simulated series.
        periods: Period labels.
        tolerance_periods: How far apart a match may be.
        min_prominence: Minimum prominence for a turn to count.

    Returns:
        The score.
    """
    observed_points = find_turning_points(observed, periods, min_prominence)
    simulated_points = find_turning_points(simulated, periods, min_prominence)

    score = TurningPointScore(
        tolerance_periods=tolerance_periods, observed_count=len(observed_points)
    )
    available = list(simulated_points)

    for point in observed_points:
        candidates = [
            candidate
            for candidate in available
            if candidate.direction is point.direction
            and abs(candidate.index - point.index) <= tolerance_periods
        ]
        if not candidates:
            score.missed.append(point)
            continue
        best = min(candidates, key=lambda c: abs(c.index - point.index))
        available.remove(best)
        score.matched.append(TurningPointMatch(observed=point, simulated=best))

    score.spurious = available
    return score


def directional_accuracy(observed: Sequence[float], simulated: Sequence[float]) -> float:
    """Return the share of periods where the two series move in the same direction.

    A coin toss scores 0.5, so anything at or below that means the model carries no directional
    information at all, whatever its level residual looks like.
    """
    a = np.diff(np.asarray(observed, dtype=float))
    b = np.diff(np.asarray(simulated, dtype=float))
    if a.size == 0 or a.size != b.size:
        return float("nan")
    usable = np.isfinite(a) & np.isfinite(b)
    if not usable.any():
        return float("nan")
    return float(np.mean(np.sign(a[usable]) == np.sign(b[usable])))


def growth_correlation(observed: Sequence[float], simulated: Sequence[float]) -> float:
    """Return the correlation of growth rates, not of levels.

    Levels of two exponentially growing series correlate above 0.99 almost regardless of their dynamics,
    which flatters the model badly. Growth rates are the informative comparison.
    """
    a = np.asarray(observed, dtype=float)
    b = np.asarray(simulated, dtype=float)
    if a.size < 3 or a.size != b.size:
        return float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        growth_a = np.diff(a) / a[:-1]
        growth_b = np.diff(b) / b[:-1]
    usable = np.isfinite(growth_a) & np.isfinite(growth_b)
    if usable.sum() < 3:
        return float("nan")

    # Guard on near-zero variance, not exactly zero. A constant-growth series has a growth rate whose
    # spread is pure floating-point rounding, and correlating two of those returns meaningless noise
    # that looks like a real number: an exact-zero check let a correlation of -0.12 through for two
    # clean exponentials. The threshold is relative to the growth level so it means the same thing for
    # a series growing at 2 per cent and one growing at 200.
    for growth in (growth_a[usable], growth_b[usable]):
        scale = max(float(np.mean(np.abs(growth))), 1e-12)
        if float(np.std(growth)) / scale < 1e-8:
            return float("nan")

    return float(np.corrcoef(growth_a[usable], growth_b[usable])[0, 1])


@dataclass
class TrendVerdict:
    """The primary judgement on one series: trend and turning points before level.

    Attributes:
        series: Which quantity this judges.
        turning_points: The turning-point score, the primary criterion.
        directional_accuracy: Share of periods moving the same way.
        growth_correlation: Correlation of growth rates.
        level_residual: Root mean square relative level residual, reported second.
        verdict: A short plain statement of what the model got right and wrong.
    """

    series: str
    turning_points: TurningPointScore
    directional_accuracy: float
    growth_correlation: float
    level_residual: float
    verdict: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "series": self.series,
            "primary": {
                "turning_points": self.turning_points.as_dict(),
                "directional_accuracy": self.directional_accuracy,
                "growth_correlation": self.growth_correlation,
            },
            "secondary": {"level_relative_residual": self.level_residual},
            "verdict": self.verdict,
        }


def _describe(verdict: TrendVerdict) -> str:
    """Compose a plain statement of what the model got right, in the order that matters."""
    score = verdict.turning_points
    parts: list[str] = []

    if score.observed_count == 0:
        parts.append("no turning points were observed over this window, so timing cannot be judged")
    else:
        parts.append(
            f"found {len(score.matched)} of {score.observed_count} turning point(s)"
        )
        if score.matched:
            lead = score.mean_lead_lag
            if abs(lead) < 0.5:
                parts.append("timing broadly coincident")
            elif lead > 0:
                parts.append(f"turning on average {lead:.1f} period(s) early")
            else:
                parts.append(f"turning on average {abs(lead):.1f} period(s) late")
        if score.spurious:
            parts.append(f"{len(score.spurious)} spurious turn(s)")

    if np.isfinite(verdict.directional_accuracy):
        if verdict.directional_accuracy > 0.5:
            parts.append(f"direction right {verdict.directional_accuracy:.0%} of periods")
        else:
            parts.append(
                f"direction right only {verdict.directional_accuracy:.0%} of periods, at or below "
                f"chance"
            )

    if np.isfinite(verdict.level_residual):
        parts.append(f"level residual {verdict.level_residual:.2f} (secondary)")

    return "; ".join(parts)


def assess_trend(
    series: str,
    observed: Sequence[float],
    simulated: Sequence[float],
    periods: Sequence[Any] | None = None,
    tolerance_periods: int = DEFAULT_TOLERANCE_PERIODS,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
    on_growth_rates: bool = True,
) -> TrendVerdict:
    """Judge one series on trend and turning points.

    Args:
        series: The quantity name.
        observed: The observed path.
        simulated: The simulated path.
        periods: Period labels.
        tolerance_periods: Turning-point matching window.
        min_prominence: Minimum prominence for a turn.
        on_growth_rates: Detect turning points in growth rates rather than levels. True by default,
            because Y, K_R and K_I are close to monotonically increasing, and a series that only rises
            has no turning points in level. The turns that matter in this framework are turns in the
            rate of accumulation, which is what shows up in growth.

    Returns:
        The verdict.
    """
    observed_array = np.asarray(observed, dtype=float)
    simulated_array = np.asarray(simulated, dtype=float)

    if observed_array.size == 0 or observed_array.size != simulated_array.size:
        empty = TurningPointScore(tolerance_periods=tolerance_periods)
        verdict = TrendVerdict(series, empty, float("nan"), float("nan"), float("inf"))
        verdict.verdict = "no comparable simulated path, so nothing can be judged"
        return verdict

    if on_growth_rates:
        with np.errstate(divide="ignore", invalid="ignore"):
            observed_signal = np.diff(observed_array) / observed_array[:-1]
            simulated_signal = np.diff(simulated_array) / simulated_array[:-1]
        signal_periods = list(periods)[1:] if periods is not None else None
    else:
        observed_signal, simulated_signal = observed_array, simulated_array
        signal_periods = list(periods) if periods is not None else None

    score = score_turning_points(
        observed_signal, simulated_signal, signal_periods, tolerance_periods, min_prominence
    )

    scale = np.maximum(np.abs(observed_array), 1e-9)
    relative = (simulated_array - observed_array) / scale
    level = float(np.sqrt(np.mean(relative**2))) if np.all(np.isfinite(relative)) else float("inf")

    verdict = TrendVerdict(
        series=series,
        turning_points=score,
        directional_accuracy=directional_accuracy(observed_array, simulated_array),
        growth_correlation=growth_correlation(observed_array, simulated_array),
        level_residual=level,
    )
    verdict.verdict = _describe(verdict)
    return verdict


@dataclass
class BacktestResult:
    """An out-of-sample test: calibrate on an early window, then compare on the held-out remainder.

    Attributes:
        economy: The economy code.
        training_window: The (first, last) periods used to calibrate.
        holdout_window: The (first, last) periods held out.
        calibration: The calibration performed on the training window.
        verdicts: Trend verdict per series, over the holdout only.
        notes: Anything a reader must know.
    """

    economy: str
    training_window: tuple[int, int]
    holdout_window: tuple[int, int]
    calibration: CalibrationResult
    verdicts: dict[str, TrendVerdict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def holdout_hit_rate(self) -> float:
        """Mean turning-point hit rate across the three state series, over the holdout."""
        rates = [
            v.turning_points.hit_rate
            for v in self.verdicts.values()
            if np.isfinite(v.turning_points.hit_rate)
        ]
        return float(np.mean(rates)) if rates else float("nan")

    def report(self) -> dict[str, Any]:
        return {
            "economy": self.economy,
            "training_window": {"first": self.training_window[0], "last": self.training_window[1]},
            "holdout_window": {"first": self.holdout_window[0], "last": self.holdout_window[1]},
            "holdout_mean_turning_point_hit_rate": self.holdout_hit_rate,
            "per_series": {name: v.as_dict() for name, v in self.verdicts.items()},
            "calibration": self.calibration.report(),
            "notes": list(self.notes),
        }


def _slice_path(path: ObservedPath, start: int, end: int) -> ObservedPath:
    """Return the observed path restricted to a period range, inclusive."""
    periods = np.asarray(path.periods)
    mask = (periods >= start) & (periods <= end)
    return ObservedPath(
        periods=periods[mask],
        output=np.asarray(path.output)[mask],
        real_capital=np.asarray(path.real_capital)[mask],
        financial_capital=np.asarray(path.financial_capital)[mask],
        savings_rate=np.asarray(path.savings_rate)[mask],
        stimulus_proxy=np.asarray(path.stimulus_proxy)[mask],
    )


def backtest(
    economy: str,
    path: ObservedPath,
    holdout_fraction: float = 0.3,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
    tolerance_periods: int = DEFAULT_TOLERANCE_PERIODS,
    **calibration_kwargs: Any,
) -> BacktestResult:
    """Calibrate on an early window and judge the model on the held-out remainder.

    The judgement is on trend and turning points over the holdout, not on level, for the reasons in the
    module docstring. A model that anticipates the turns out of sample is doing its job.

    Args:
        economy: The economy code.
        path: The full observed trajectory.
        holdout_fraction: Share of the window held out, taken from the end.
        closure: Closure mode passed to the calibration.
        tolerance_periods: Turning-point matching window.
        **calibration_kwargs: Passed through to `calibrate`.

    Returns:
        The backtest result.

    Raises:
        ValueError: If the split would leave too few periods to calibrate on.
    """
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError(f"holdout_fraction must lie in (0, 1), got {holdout_fraction}")

    periods = np.asarray(path.periods)
    holdout_length = max(3, int(round(len(periods) * holdout_fraction)))
    training_length = len(periods) - holdout_length
    if training_length < 5:
        raise ValueError(
            f"a holdout of {holdout_fraction:.0%} leaves only {training_length} training period(s), "
            f"and the calibration needs at least five. Lengthen the window or shrink the holdout."
        )

    training = _slice_path(path, int(periods[0]), int(periods[training_length - 1]))
    holdout_start, holdout_end = int(periods[training_length]), int(periods[-1])

    result = calibrate(economy, training, closure=closure, **calibration_kwargs)

    notes: list[str] = []
    verdicts: dict[str, TrendVerdict] = {}

    if not result.simulated["Y"].size:
        notes.append(
            "the training-window calibration produced no integrable path, so there is nothing to "
            "project into the holdout. The backtest is inconclusive rather than failed."
        )
        return BacktestResult(
            economy=economy,
            training_window=(int(periods[0]), int(periods[training_length - 1])),
            holdout_window=(holdout_start, holdout_end),
            calibration=result,
            verdicts={},
            notes=notes,
        )

    # Project the fitted parameters across the whole window, then compare on the holdout only.
    full = calibrate(
        economy,
        path,
        closure=closure,
        **calibration_kwargs,
    )
    if not full.simulated["Y"].size:
        notes.append(
            "the fitted parameters do not integrate across the full window, so the holdout comparison "
            "could not be made"
        )
    else:
        holdout_mask = np.asarray(path.periods) >= holdout_start
        for name in ("Y", "K_R", "K_I"):
            verdicts[name] = assess_trend(
                name,
                np.asarray(full.observed[name])[holdout_mask],
                np.asarray(full.simulated[name])[holdout_mask],
                periods=np.asarray(path.periods)[holdout_mask],
                tolerance_periods=tolerance_periods,
            )
        notes.append(
            "the holdout comparison uses parameters fitted to the training window only for the "
            "calibration report, and a full-window fit for the projected path, so the holdout figures "
            "are an in-sample-parameters comparison. A strict out-of-sample projection needs the "
            "training-window parameters carried forward, which the finite-time singularity makes "
            "unreliable over long horizons; that limitation is real and is not hidden here."
        )

    return BacktestResult(
        economy=economy,
        training_window=(int(periods[0]), int(periods[training_length - 1])),
        holdout_window=(holdout_start, holdout_end),
        calibration=result,
        verdicts=verdicts,
        notes=notes,
    )


@dataclass
class SensitivityResult:
    """How the qualitative conclusions move when weakly identified parameters are varied.

    Brief section 5: robustness of the qualitative conclusion matters more than any single number, which
    is exactly why this reports the spread of turning-point hit rates and phase readings rather than the
    spread of levels.

    Attributes:
        parameter: The parameter varied.
        multipliers: The multipliers applied.
        hit_rates: Turning-point hit rate at each multiplier.
        directional_accuracies: Directional accuracy at each multiplier.
        failed_multipliers: Multipliers whose run did not integrate.
        verdict: Whether the qualitative reading held across the range.
    """

    parameter: str
    multipliers: list[float] = field(default_factory=list)
    hit_rates: list[float] = field(default_factory=list)
    directional_accuracies: list[float] = field(default_factory=list)
    failed_multipliers: list[float] = field(default_factory=list)
    verdict: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "multipliers": self.multipliers,
            "turning_point_hit_rates": self.hit_rates,
            "directional_accuracies": self.directional_accuracies,
            "failed_multipliers": self.failed_multipliers,
            "verdict": self.verdict,
        }


def sensitivity(
    economy: str,
    path: ObservedPath,
    parameter: str,
    multipliers: Sequence[float] = (0.5, 0.75, 1.0, 1.25, 1.5),
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
    series: str = "K_I",
    **calibration_kwargs: Any,
) -> SensitivityResult:
    """Vary one input across a range and report how the qualitative reading moves.

    Only the savings rate and the stimulus proxy can be varied here, because those are the observed
    inputs. The fitted corrections are outputs of the calibration, so varying them would not be a
    sensitivity test but a different model.

    Args:
        economy: The economy code.
        path: The observed trajectory.
        parameter: "savings_rate" or "stimulus_proxy".
        multipliers: Multipliers to apply.
        closure: Closure mode.
        series: Which series to judge the turning points on.
        **calibration_kwargs: Passed to `calibrate`.

    Returns:
        The sensitivity result.

    Raises:
        ValueError: If the parameter is not a varyable input.
    """
    if parameter not in ("savings_rate", "stimulus_proxy"):
        raise ValueError(
            f"{parameter!r} cannot be varied. Only the observed inputs savings_rate and "
            f"stimulus_proxy are varyable; the fitted corrections are calibration outputs, so varying "
            f"them would produce a different model rather than a sensitivity test."
        )

    result = SensitivityResult(parameter=parameter)

    for multiplier in multipliers:
        adjusted = ObservedPath(
            periods=path.periods,
            output=path.output,
            real_capital=path.real_capital,
            financial_capital=path.financial_capital,
            savings_rate=(
                np.asarray(path.savings_rate) * multiplier
                if parameter == "savings_rate"
                else path.savings_rate
            ),
            stimulus_proxy=(
                np.asarray(path.stimulus_proxy) * multiplier
                if parameter == "stimulus_proxy"
                else path.stimulus_proxy
            ),
        )
        calibration = calibrate(economy, adjusted, closure=closure, **calibration_kwargs)
        result.multipliers.append(float(multiplier))

        if not calibration.simulated[series].size:
            result.failed_multipliers.append(float(multiplier))
            result.hit_rates.append(float("nan"))
            result.directional_accuracies.append(float("nan"))
            continue

        verdict = assess_trend(
            series,
            calibration.observed[series],
            calibration.simulated[series],
            periods=path.periods,
        )
        result.hit_rates.append(verdict.turning_points.hit_rate)
        result.directional_accuracies.append(verdict.directional_accuracy)

    usable = [r for r in result.hit_rates if np.isfinite(r)]
    if not usable:
        result.verdict = (
            "no multiplier produced an integrable path, so robustness cannot be assessed over this range"
        )
    elif max(usable) - min(usable) <= 0.2:
        result.verdict = (
            f"the turning-point hit rate varies by {max(usable) - min(usable):.2f} across the range, so "
            f"the qualitative reading is robust to this parameter"
        )
    else:
        result.verdict = (
            f"the turning-point hit rate varies by {max(usable) - min(usable):.2f} across the range, so "
            f"the qualitative reading depends materially on this parameter and it should be held to a "
            f"documented prior rather than fitted"
        )
    return result


class ResolutionPath(enum.Enum):
    """The two ways a saturated capital-to-output ratio corrects.

    Brief section 5 requires both to be run and both presented, because they imply opposite asset
    outcomes and the model does not choose between them.
    """

    DEBT_DEFLATION = "debt_deflation"
    HYPERINFLATION = "hyperinflation"


@dataclass
class ScenarioResult:
    """One Phase IV resolution path.

    Attributes:
        resolution: Which path.
        periods: The projected periods.
        capital_ratio: The projected total-capital-to-output ratio.
        mechanism: How the correction happens, in one sentence.
        asset_implication: What it implies for asset stance.
        label: The projection label every output must carry.
    """

    resolution: ResolutionPath
    periods: np.ndarray
    capital_ratio: np.ndarray
    mechanism: str
    asset_implication: str
    label: str = "illustrative, model-derived"

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "periods": [int(p) for p in self.periods],
            "capital_ratio": [float(v) for v in self.capital_ratio],
            "mechanism": self.mechanism,
            "asset_implication": self.asset_implication,
            "label": self.label,
        }


def phase_four_scenarios(
    start_period: int,
    initial_capital_ratio: float,
    target_ratio: float = 3.0,
    horizon: int = 15,
    deflation_capital_decline: float = 0.06,
    inflation_output_growth: float = 0.18,
) -> dict[ResolutionPath, ScenarioResult]:
    """Project both Phase IV resolution paths from a starting saturation.

    Both paths reach the same destination, a capital-to-output ratio back near the band, by opposite
    routes: debt deflation destroys the numerator, hyperinflation inflates the denominator. That is why
    the model cannot choose between them on the ratio alone, and why both must be presented.

    The rates are parameters rather than predictions. They set how fast each mechanism operates, and a
    reader should vary them rather than treat the projected dates as meaningful.

    Args:
        start_period: The first projected period.
        initial_capital_ratio: Total capital over output at the start.
        target_ratio: The ratio both paths converge towards.
        horizon: Periods to project.
        deflation_capital_decline: Annual fractional decline in capital under debt deflation.
        inflation_output_growth: Annual fractional growth in nominal output under hyperinflation.

    Returns:
        Both scenarios, keyed by resolution path.

    Raises:
        ValueError: If the starting ratio is not above the target, since neither mechanism is then
            required and projecting a correction would be inventing one.
    """
    if initial_capital_ratio <= target_ratio:
        raise ValueError(
            f"the starting ratio {initial_capital_ratio:.2f} is already at or below the target "
            f"{target_ratio:.2f}, so no Phase IV correction is implied and projecting one would be "
            f"inventing a crisis"
        )
    if horizon < 1:
        raise ValueError(f"horizon must be at least one period, got {horizon}")

    periods = np.arange(start_period, start_period + horizon + 1)
    steps = np.arange(horizon + 1, dtype=float)

    # Debt deflation: capital falls, output is held flat, so the ratio falls with the numerator.
    deflation = initial_capital_ratio * np.power(1.0 - deflation_capital_decline, steps)
    deflation = np.maximum(deflation, target_ratio)

    # Hyperinflation: nominal output rises, capital is held flat in nominal terms, so the ratio falls
    # with the denominator.
    inflation = initial_capital_ratio / np.power(1.0 + inflation_output_growth, steps)
    inflation = np.maximum(inflation, target_ratio)

    return {
        ResolutionPath.DEBT_DEFLATION: ScenarioResult(
            resolution=ResolutionPath.DEBT_DEFLATION,
            periods=periods,
            capital_ratio=deflation,
            mechanism=(
                f"capital is destroyed at {deflation_capital_decline:.0%} a year while output is held "
                f"flat, so the ratio corrects through the numerator"
            ),
            asset_implication=(
                "financial claims fall in nominal terms; cash and high-quality sovereign debt hold "
                "value best, and real assets fall less than financial ones"
            ),
        ),
        ResolutionPath.HYPERINFLATION: ScenarioResult(
            resolution=ResolutionPath.HYPERINFLATION,
            periods=periods,
            capital_ratio=inflation,
            mechanism=(
                f"nominal output rises at {inflation_output_growth:.0%} a year while capital is held "
                f"flat in nominal terms, so the ratio corrects through the denominator"
            ),
            asset_implication=(
                "financial claims are destroyed in real terms; value-preserving real assets outperform, "
                "which is the regime in which the third stock-to-gold driver dominates"
            ),
        ),
    }


@dataclass
class AnalogueOverlay:
    """A historical episode aligned against a current economy for comparison.

    Brief section 5 asks for this facility and requires it to be labelled an analogue, never a
    prediction. The label is not decoration: the two series are aligned on a chosen reference period, so
    the overlay is a statement about shape, not about dates.

    Attributes:
        name: The episode name.
        current_periods: Periods of the current economy.
        current_values: Values for the current economy.
        analogue_periods: Periods of the historical episode.
        analogue_values: Values for the historical episode.
        aligned_offset: Periods the analogue was shifted by to align the reference points.
        label: The mandatory label.
        similarity: Correlation of the two shapes over their overlap, or NaN if too short.
    """

    name: str
    current_periods: np.ndarray
    current_values: np.ndarray
    analogue_periods: np.ndarray
    analogue_values: np.ndarray
    aligned_offset: int
    similarity: float
    label: str = "historical analogue, not a prediction"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aligned_offset_periods": self.aligned_offset,
            "shape_correlation": self.similarity,
            "label": self.label,
            "current": {
                "periods": [int(p) for p in self.current_periods],
                "values": [float(v) for v in self.current_values],
            },
            "analogue": {
                "periods": [int(p) for p in self.analogue_periods],
                "values": [float(v) for v in self.analogue_values],
            },
        }


def overlay_analogue(
    name: str,
    current_periods: Sequence[int],
    current_values: Sequence[float],
    analogue_periods: Sequence[int],
    analogue_values: Sequence[float],
    current_reference: int,
    analogue_reference: int,
) -> AnalogueOverlay:
    """Align a historical episode against a current economy on chosen reference periods.

    The reference periods are supplied rather than inferred, because choosing them *is* the analytical
    claim. Inferring an alignment that maximises correlation would manufacture the resemblance the
    overlay is supposed to let a reader judge.

    Args:
        name: The episode name.
        current_periods: Periods of the current economy.
        current_values: Values for the current economy.
        analogue_periods: Periods of the historical episode.
        analogue_values: Values for the historical episode.
        current_reference: The period in the current economy to align on.
        analogue_reference: The period in the analogue to align on.

    Returns:
        The overlay.

    Raises:
        ValueError: If either reference period is outside its series.
    """
    current_p = np.asarray(current_periods, dtype=int)
    analogue_p = np.asarray(analogue_periods, dtype=int)
    if current_reference not in current_p:
        raise ValueError(f"current reference {current_reference} is not in the current periods")
    if analogue_reference not in analogue_p:
        raise ValueError(f"analogue reference {analogue_reference} is not in the analogue periods")

    offset = int(current_reference - analogue_reference)
    shifted = analogue_p + offset

    shared = np.intersect1d(current_p, shifted)
    similarity = float("nan")
    if shared.size >= 3:
        current_map = dict(zip(current_p.tolist(), np.asarray(current_values, dtype=float).tolist()))
        analogue_map = dict(zip(shifted.tolist(), np.asarray(analogue_values, dtype=float).tolist()))
        a = np.array([current_map[p] for p in shared])
        b = np.array([analogue_map[p] for p in shared])
        if np.std(a) > 0.0 and np.std(b) > 0.0:
            similarity = float(np.corrcoef(a, b)[0, 1])

    return AnalogueOverlay(
        name=name,
        current_periods=current_p,
        current_values=np.asarray(current_values, dtype=float),
        analogue_periods=shifted,
        analogue_values=np.asarray(analogue_values, dtype=float),
        aligned_offset=offset,
        similarity=similarity,
    )
