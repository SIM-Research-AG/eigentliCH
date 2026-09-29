"""Forward projection: what the calibrated model implies after the window ends.

This is what the model is for. Everything else in the programme establishes a position; this runs it
forward.

**What a projection from this model is, and is not.**

It is a forecast. Saying otherwise would be false modesty and would make the apparatus pointless. But it
is a *conditional, structural* forecast, and the difference is operational rather than rhetorical:

- It says that an economy at this saturation, with these cycle phases and these parameters, evolves along
  a path of a particular shape and resolves in one of a small number of ways.
- It does not say which month. The turning-point hit rate measured in backtesting is between about 0.16
  and 0.52 depending on economy and series, so the *timing* of a projected turn is the weakest part of the
  output. Directional accuracy is 0.73 to 0.95, so the *direction* is the strongest.
- Every projected path is recomputed from the current data vintage. No date is stored anywhere in the
  programme, and a date quoted from a projection must be re-derived rather than carried forward from an
  old note.

`ProjectionResult.reliability` reports the measured backtest figures alongside the projection, so a reader
sees how much weight the timing can bear at the same moment they see the dates. Presenting projected turn
dates without them would be the single most misleading thing this programme could do.

**The forward parameter assumption.** The equations need `p_s`, `p_p`, `p_b`, `alpha` and `S` beyond the
window, and the data end at the window. They are held at their final observed values by default. That is a
strong assumption and it is stated on every result: it means the projection answers "where does this
economy go if the last observed conditions persist", not "where does it go".
"""

from __future__ import annotations

import enum
import warnings
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np

from macrofield.control import Provenance, Segment, Traced

from macrofield.calibration.fit import (
    CalibrationResult,
    ObservedPath,
    P_B_FROM_POPULATION_GROWTH,
    compute_identity_parameters,
)
from macrofield.calibration.validate import (
    ResolutionPath,
    ScenarioResult,
    assess_trend,
    phase_four_scenarios,
)
from macrofield.model.edm import ClosureMode, EDMParameters, simulate
from macrofield.model.phases import Phase, PhaseThresholds, classify_period, classify_sequence
from macrofield.reporting.export import PROJECTION_LABEL

#: Default projection horizon in years. A credit cycle is about eighteen years, so fifteen covers most of
#: one without pretending to reach the capital cycle, which at ninety years is far beyond what a
#: parameter-hold assumption can support.
DEFAULT_HORIZON = 15

#: How the parameter paths are carried beyond the window.
HOLD_LAST = "hold_last"
EXTEND_TREND = "extend_trend"


class ProjectionError(ValueError):
    """Raised when a projection cannot be produced."""


class Confidence(enum.Enum):
    """How much weight a projected feature can bear, from the measured backtest.

    Deliberately coarse. A finer scale would imply a precision the backtest does not support.
    """

    #: Direction of travel. Measured directional accuracy is well above chance.
    DIRECTION = "direction, measured 0.73 to 0.95 against a 0.50 baseline"
    #: Ordering of events. Turns are found but timing is loose.
    SEQUENCE = "sequence, turns are detected but the hit rate is 0.16 to 0.52"
    #: Specific dates. Not supported.
    TIMING = "timing, not supported: quote a range and re-derive from the vintage"


@dataclass
class ProjectedPhase:
    """A projected phase transition."""

    period: int
    from_phase: str
    to_phase: str
    saturation: float
    real_to_financial: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "saturation": self.saturation,
            "real_to_financial": self.real_to_financial,
            "confidence": Confidence.SEQUENCE.value,
        }


@dataclass
class ProjectionResult:
    """The projected path and what can be read from it.

    Attributes:
        economy: The economy code.
        from_period: The last observed period, which the projection starts from.
        periods: The projected periods, excluding the starting period.
        output: Projected Y.
        real_capital: Projected K_R.
        financial_capital: Projected K_I.
        saturation: Projected credit saturation.
        real_to_financial: Projected K_R/K_I.
        phase_at_end: The phase at the end of the horizon.
        transitions: Projected phase transitions.
        scenarios: The Phase IV resolution paths, where the projection implies a correction.
        reliability: The measured backtest figures, reported alongside so a reader sees how much weight
            the timing can bear.
        assumptions: What had to be assumed, stated rather than buried.
        label: The mandatory projection label.
        notes: Anything else a reader must know.
    """

    economy: str
    from_period: int
    periods: np.ndarray
    output: np.ndarray
    real_capital: np.ndarray
    financial_capital: np.ndarray
    saturation: np.ndarray
    real_to_financial: np.ndarray
    phase_at_end: str
    transitions: list[ProjectedPhase] = field(default_factory=list)
    scenarios: dict[str, ScenarioResult] = field(default_factory=dict)
    reliability: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    label: str = PROJECTION_LABEL
    notes: list[str] = field(default_factory=list)

    @property
    def horizon(self) -> int:
        return int(self.periods.size)

    def as_dict(self) -> dict[str, Any]:
        return {
            "economy": self.economy,
            "from_period": self.from_period,
            "horizon": self.horizon,
            "label": self.label,
            "periods": [int(p) for p in self.periods],
            "output": [float(v) for v in self.output],
            "real_capital": [float(v) for v in self.real_capital],
            "financial_capital": [float(v) for v in self.financial_capital],
            "saturation": [float(v) for v in self.saturation],
            "real_to_financial": [float(v) for v in self.real_to_financial],
            "phase_at_end": self.phase_at_end,
            "transitions": [t.as_dict() for t in self.transitions],
            "scenarios": {name: s.as_dict() for name, s in self.scenarios.items()},
            "reliability": self.reliability,
            "assumptions": list(self.assumptions),
            "notes": list(self.notes),
        }


def _forward_parameter(values: np.ndarray, mode: str, horizon: int) -> np.ndarray:
    """Extend a parameter path beyond the window.

    `hold_last` repeats the final observed value. `extend_trend` continues the average change of the last
    five observations, clipped so it cannot change sign, because a parameter that crosses zero by
    extrapolation is an artefact of the extrapolation rather than a finding.
    """
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ProjectionError("a parameter path has no finite observations to project from")

    last = float(finite[-1])
    if mode == HOLD_LAST or finite.size < 6:
        return np.full(horizon, last)
    if mode == EXTEND_TREND:
        recent = np.diff(finite[-6:])
        step = float(np.mean(recent))
        extended = last + step * np.arange(1, horizon + 1)
        if last >= 0.0:
            return np.clip(extended, 0.0, None)
        return np.clip(extended, None, 0.0)
    raise ProjectionError(f"unknown parameter mode {mode!r}")


def project(
    economy: str,
    path: ObservedPath,
    calibration: CalibrationResult,
    horizon: int = DEFAULT_HORIZON,
    parameter_mode: str = HOLD_LAST,
    population_growth: np.ndarray | None = None,
    credit_share_of_financial: float | None = None,
    thresholds: PhaseThresholds | None = None,
    closure: ClosureMode = ClosureMode.AS_WRITTEN,
    forward_stimulus: np.ndarray | None = None,
    forward_savings: np.ndarray | None = None,
) -> ProjectionResult:
    """Run the calibrated model forward from the end of the observed window.

    Args:
        economy: The economy code.
        path: The observed trajectory the calibration used.
        calibration: The fitted calibration.
        horizon: Periods to project.
        parameter_mode: How to carry the parameter paths forward.
        population_growth: The observed population growth, needed for p_b.
        credit_share_of_financial: The share of K_I that is credit at the window end, used to project the
            credit saturation axis. Defaults to the observed share implied by the path.
        thresholds: The phase cut-offs.
        closure: Closure mode.
        forward_stimulus: One multiplier per projected period, applied to the forward stimulus path. This is
            how a *future* policy programme is expressed; scaling `path.stimulus_proxy` instead scales the
            observed window, which is a counterfactual about the past.
        forward_savings: One multiplier per projected period, applied to the forward savings path.

    Returns:
        The projection.

    Raises:
        ProjectionError: If the calibration produced no integrable path, since there is then nothing to
            continue, or if the projection itself does not integrate.
    """
    if horizon < 1:
        raise ProjectionError(f"the horizon must be at least one period, got {horizon}")
    if not calibration.simulated["Y"].size:
        raise ProjectionError(
            f"{economy}: the calibration produced no integrable trajectory, so there is nothing to "
            f"project forward. A projection from a model that cannot reproduce the observed window would "
            f"be arithmetic rather than a forecast."
        )

    identities = compute_identity_parameters(
        path,
        p_b_source=P_B_FROM_POPULATION_GROWTH if population_growth is not None else "flow_ratio",
        population_growth=population_growth,
    )
    fitted = calibration.free_parameters

    # Carry the parameter paths forward, with the fitted corrections applied as they were in the fit.
    forward_p_p = _forward_parameter(identities.p_p, parameter_mode, horizon) * fitted["p_p_scale"]
    forward_p_b = _forward_parameter(identities.p_b, parameter_mode, horizon) * fitted["p_b_scale"]
    forward_alpha = _forward_parameter(identities.alpha, parameter_mode, horizon) * fitted["alpha_scale"]
    forward_p_s = (
        _forward_parameter(np.asarray(path.savings_rate, dtype=float), parameter_mode, horizon)
        * fitted["savings_scale"]
    )
    forward_stimulus_path = (
        _forward_parameter(np.asarray(path.stimulus_proxy, dtype=float), parameter_mode, horizon)
        * fitted["stimulus_scale"]
    )

    # Forward policy levers, applied to the projected parameter paths rather than to the observed window.
    #
    # This is the distinction a scenario board turns on. Scaling the *observed* path answers "what if policy
    # had been different", which is a counterfactual about the past; scaling the *forward* path answers "what
    # if we do this from 2027", which is what a stimulus programme is. Without this a future-dated control
    # multiplied nothing at all, because the observed window ends before it starts.
    for name, lever, target in (
        ("forward_stimulus", forward_stimulus, "stimulus"),
        ("forward_savings", forward_savings, "savings"),
    ):
        if lever is None:
            continue
        values = np.asarray(lever, dtype=float)
        if values.size != horizon:
            raise ProjectionError(
                f"{name} has {values.size} values but the horizon is {horizon}. A forward lever must "
                f"supply one multiplier per projected period."
            )
        if target == "stimulus":
            forward_stimulus_path = forward_stimulus_path * values
        else:
            forward_p_s = forward_p_s * values

    from_period = int(path.periods[-1])
    periods = np.arange(from_period + 1, from_period + horizon + 1)
    time = np.arange(0.0, horizon + 1.0)

    def at(values: np.ndarray):
        """Step-hold interpolation over the projected periods."""
        padded = np.concatenate(([values[0]], values))

        def evaluate(t: float) -> float:
            index = int(np.clip(np.floor(t), 0, padded.size - 1))
            return float(padded[index])

        return evaluate

    parameters = EDMParameters(
        p_s=at(forward_p_s),
        p_p=at(forward_p_p),
        p_b=at(forward_p_b),
        alpha=at(forward_alpha),
        stimulus=at(forward_stimulus_path),
        endogenous_r=True,
    )

    # Start from the *observed* end state, not the fitted one.
    #
    # Starting from the fit would project from where the model ended up rather than from where the economy
    # actually is, and since the level fit is imperfect by design those differ. On United States data the
    # fitted K_R/K_I at the window end was 1.06 against an observed 0.71, which put the projection on the
    # wrong side of the Phase 4 boundary and produced a spurious transition in its very first period.
    initial = np.array(
        [
            float(path.output[-1]),
            float(path.real_capital[-1]),
            float(path.financial_capital[-1]),
        ]
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = simulate(
            initial,
            parameters,
            (0.0, float(horizon)),
            t_eval=time,
            closure=closure,
            warn_on_residual=False,
        )

    if not result.success or result.t.shape[0] != time.size:
        raise ProjectionError(
            f"{economy}: the projection does not integrate over {horizon} periods. The trajectory runs "
            f"into the finite-time singularity of the unbounded investment share, which means the model "
            f"cannot say what happens that far ahead under these parameters. Shorten the horizon."
        )

    # Drop the starting period, which is the observed end rather than a projection.
    output = result.Y[1:]
    real_capital = result.K_R[1:]
    financial_capital = result.K_I[1:]
    real_to_financial = real_capital / financial_capital

    # The credit saturation axis is not a state variable, so it is projected by assuming the credit share
    # of financial capital holds. Stated as an assumption because it is one.
    # The default was `path.financial_capital[-1] / path.financial_capital[-1]`, which is one by construction:
    # a self-cancelling expression that looked deliberate and was not. Nothing reached it, because both callers
    # pass the share explicitly, so it never produced a wrong answer. It is now an explicit one with the
    # assumption stated, since a caller that omits the share is assuming the whole of K_I is credit.
    share = (
        float(credit_share_of_financial)
        if credit_share_of_financial is not None
        else 1.0
    )
    saturation = share * financial_capital / output

    thresholds = thresholds or PhaseThresholds()

    # Classify the observed end state together with the projected path, in one sequence.
    #
    # It has to be one sequence because the exit from Phase 4 is latched: the author's rule of 2026-07-28 is
    # that the phase becomes Foundation only when saturation reaches that level, and otherwise sits in
    # Saturation. A projection classified on its own would not know the economy was already in the
    # reordering when it started, and would read a falling ratio as a return to Build-up.
    observed_end_saturation = float(
        share * float(path.financial_capital[-1]) / float(path.output[-1])
    )
    sequence = classify_sequence(
        saturation=[observed_end_saturation] + [float(v) for v in saturation],
        real_capital=[float(path.real_capital[-1])] + [float(v) for v in real_capital],
        financial_capital=[float(path.financial_capital[-1])] + [float(v) for v in financial_capital],
        output=[float(path.output[-1])] + [float(v) for v in output],
        thresholds=thresholds,
    )
    starting, classifications = sequence[0], sequence[1:]

    transitions: list[ProjectedPhase] = []
    previous: Phase = starting.phase
    for index, classification in enumerate(classifications):
        if classification.phase is not previous:
            transitions.append(
                ProjectedPhase(
                    period=int(periods[index]),
                    from_phase=previous.label,
                    to_phase=classification.phase.label,
                    saturation=float(saturation[index]),
                    real_to_financial=float(real_to_financial[index]),
                )
            )
            previous = classification.phase

    # Where the projection ends above the band, both resolution paths are offered, because the model does
    # not choose between them and presenting one would be picking an answer it has not got.
    scenarios: dict[str, ScenarioResult] = {}
    final_capital_ratio = float((real_capital[-1] + financial_capital[-1]) / output[-1])
    band_upper = thresholds.balanced_band[1]
    if final_capital_ratio > band_upper:
        both = phase_four_scenarios(
            start_period=int(periods[-1]),
            initial_capital_ratio=final_capital_ratio,
            target_ratio=band_upper,
            horizon=horizon,
        )
        scenarios = {key.value: value for key, value in both.items()}

    # The measured backtest figures, so timing is read with its reliability in view.
    reliability: dict[str, Any] = {"measured_on": "the calibration window, in sample"}
    for name in ("Y", "K_R", "K_I"):
        if calibration.simulated[name].size:
            verdict = assess_trend(
                name,
                calibration.observed[name],
                calibration.simulated[name],
                periods=path.periods,
            )
            reliability[name] = {
                "turning_point_hit_rate": verdict.turning_points.hit_rate,
                "mean_lead_lag_periods": verdict.turning_points.mean_lead_lag,
                "directional_accuracy": verdict.directional_accuracy,
            }
    reliability["read_as"] = {
        "direction": Confidence.DIRECTION.value,
        "sequence": Confidence.SEQUENCE.value,
        "timing": Confidence.TIMING.value,
    }

    assumptions = [
        f"the parameter paths are carried forward by {parameter_mode!r}, so this answers where the economy "
        f"goes if the last observed conditions persist, not where it goes",
        "the credit share of financial capital is held at its observed value, since the credit saturation "
        "axis is not a state variable of the system",
        "the fitted identity corrections are held at their calibrated values throughout the horizon",
    ]

    notes = [
        "projected turn periods carry the sequence confidence, not the timing confidence. The measured "
        "turning-point hit rate is well below one, so read the ordering of events rather than the dates.",
        "this projection is recomputed from the current data vintage. No date is stored in the programme, "
        "so a date quoted from it must be re-derived rather than carried forward.",
    ]
    if scenarios:
        notes.append(
            f"the projected capital-to-output ratio ends at {final_capital_ratio:.2f}, above the band "
            f"upper bound of {band_upper:.2f}, so both Phase IV resolution paths are included. They reach "
            f"the same destination by opposite routes and the model does not choose between them."
        )

    return ProjectionResult(
        economy=economy,
        from_period=from_period,
        periods=periods,
        output=output,
        real_capital=real_capital,
        financial_capital=financial_capital,
        saturation=saturation,
        real_to_financial=real_to_financial,
        phase_at_end=classifications[-1].phase.label,
        transitions=transitions,
        scenarios=scenarios,
        reliability=reliability,
        assumptions=assumptions,
        notes=notes,
    )


#: Cap on how many integration attempts the horizon search may make.
#:
#: The search is a binary search rather than a fixed ladder, because a ladder wastes real model output: a
#: descending ladder of (12, 10, 8, ...) answered a request for 40 with 12 integrated periods on United
#: States data, where 35 integrates. A single projection costs 30 to 300 milliseconds, so finding the true
#: maximum in about six attempts is affordable and strictly better.
#:
#: The search assumes integrability is **monotonic** in the horizon: if the trajectory survives to period
#: `n` it survived every period before it. That holds because the obstacle is a finite-time singularity at
#: a fixed time, not an intermittent failure. Stated because the search would silently return a shorter
#: horizon than necessary if it were ever false.
MAX_HORIZON_ATTEMPTS = 24

#: How many integrated periods the log-linear extrapolation averages its growth rate over. Five is a
#: business cycle's worth on annual data, short enough to reflect where the trajectory ended up and long
#: enough not to be one period's noise.
EXTRAPOLATION_WINDOW = 5


@dataclass
class ResilientProjection:
    """A projection that reached the requested horizon, by integrating as far as it could and then saying so.

    Phase 2 of docs/BATTLE_PLAN.md. The control board needs an answer for every setting a user can dial in,
    and some of those settings drive the system into the finite-time singularity of the unbounded investment
    share, where `project` correctly refuses. Refusing is right for the function and useless for a board, so
    this descends the horizon to the longest that integrates and continues log-linearly from there.

    **The extrapolated tail is not a projection.** It is a straight line in logs, fitted to where the
    integrated trajectory ended, and it carries `Provenance.EXTRAPOLATED` so no chart or brief can present
    it as a model consequence. The distinction matters most exactly where it is most tempting to ignore: the
    tail is the part a reader looks at.

    Attributes:
        result: The projection, with any extrapolated tail appended.
        requested_horizon: What was asked for.
        integrated_horizon: How far the model actually integrated.
        traces: Provenance per state series, so a chart can split integrated from extrapolated.
        attempts: Each horizon tried and why it failed, so the descent is auditable.
        notes: Anything a reader must know.
    """

    result: ProjectionResult
    requested_horizon: int
    integrated_horizon: int
    traces: dict[str, Traced] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def extrapolated_periods(self) -> int:
        return max(0, self.requested_horizon - self.integrated_horizon)

    @property
    def fully_integrated(self) -> bool:
        return self.extrapolated_periods == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "projection": self.result.as_dict(),
            "requested_horizon": self.requested_horizon,
            "integrated_horizon": self.integrated_horizon,
            "extrapolated_periods": self.extrapolated_periods,
            "fully_integrated": self.fully_integrated,
            "traces": {name: trace.as_dict() for name, trace in self.traces.items()},
            "attempts": list(self.attempts),
            "notes": list(self.notes),
        }


def _mean_log_growth(values: np.ndarray, window: int | None = None) -> float:
    """Mean period-on-period log growth, over the whole series or its last `window` points."""
    series = np.asarray(values, dtype=float)
    if window is not None:
        series = series[-min(int(window), series.size) :]
    if series.size < 2 or not np.all(series > 0.0):
        return float("nan")
    return float(np.mean(np.diff(np.log(series))))


def _extend_log_linear(anchor: float, rate: float, periods: int) -> np.ndarray:
    """Continue from a level at a fixed log growth rate.

    In logs rather than levels because these are capital stocks and output: a linear continuation of a level
    would imply a decaying growth rate, which is a different claim from the one being made.
    """
    if periods <= 0:
        return np.zeros(0, dtype=float)
    if not np.isfinite(rate) or not np.isfinite(anchor):
        return np.full(periods, anchor)
    return float(anchor) * np.exp(rate * np.arange(1, periods + 1, dtype=float))


def project_resiliently(
    economy: str,
    path: ObservedPath,
    calibration: CalibrationResult,
    horizon: int = DEFAULT_HORIZON,
    extrapolation_window: int = EXTRAPOLATION_WINDOW,
    max_attempts: int = MAX_HORIZON_ATTEMPTS,
    forward_stimulus_control: Any = None,
    forward_savings_control: Any = None,
    **kwargs: Any,
) -> ResilientProjection:
    """Project to `horizon`, integrating as far as possible and extrapolating the rest.

    The horizon search is a binary search for the longest horizon that integrates. See
    MAX_HORIZON_ATTEMPTS for why, and for the monotonicity it assumes.

    Args:
        economy: The economy code.
        path: The observed trajectory.
        calibration: The fitted calibration.
        horizon: The horizon asked for.
        extrapolation_window: Periods of integrated trajectory the growth rate is averaged over.
        max_attempts: Cap on integration attempts, so a pathological case cannot spin.
        **kwargs: Passed to `project` unchanged.

    Returns:
        The projection, its provenance, and the record of what was tried.

    Raises:
        ProjectionError: If no horizon integrates, since there is then nothing to extrapolate *from* and a
            straight line off the observed end state would be a statement about arithmetic rather than
            about the model.
    """
    requested = int(horizon)
    if requested < 1:
        raise ProjectionError(f"the horizon must be at least one period, got {requested}")

    attempts: list[dict[str, Any]] = []
    cache: dict[int, ProjectionResult | str] = {}

    from_period = int(np.asarray(path.periods)[-1])

    def forward_levers(candidate: int) -> dict[str, np.ndarray]:
        """Resolve the forward control paths over the periods this candidate horizon would cover.

        Resolved per attempt rather than once, because the horizon search changes how many projected periods
        there are and a lever must supply exactly one multiplier per period.
        """
        projected = np.arange(from_period + 1, from_period + candidate + 1)
        levers: dict[str, np.ndarray] = {}
        if forward_stimulus_control is not None:
            levers["forward_stimulus"] = forward_stimulus_control.to_array(projected)
        if forward_savings_control is not None:
            levers["forward_savings"] = forward_savings_control.to_array(projected)
        return levers

    def attempt(candidate: int) -> ProjectionResult | None:
        """Try one horizon, recording the outcome. Returns None where it does not integrate."""
        if candidate in cache:
            cached = cache[candidate]
            return cached if isinstance(cached, ProjectionResult) else None
        try:
            outcome = project(
                economy, path, calibration, horizon=candidate,
                **forward_levers(candidate), **kwargs,
            )
        except ProjectionError as error:
            cache[candidate] = str(error)
            attempts.append({"horizon": candidate, "integrated": False, "reason": str(error)})
            return None
        cache[candidate] = outcome
        attempts.append({"horizon": candidate, "integrated": True, "reason": None})
        return outcome

    best = attempt(requested)
    if best is None:
        # Binary search for the longest horizon below the request that integrates.
        low, high = 1, requested - 1
        while low <= high and len(attempts) < max_attempts:
            middle = (low + high) // 2
            outcome = attempt(middle)
            if outcome is None:
                high = middle - 1
            else:
                best = outcome
                low = middle + 1

    if best is not None:
        result = best
        notes = list(result.notes)
        traces: dict[str, Traced] = {}

        integrated = int(result.periods.size)
        missing = requested - integrated

        series_names = ("output", "real_capital", "financial_capital", "saturation", "real_to_financial")

        if missing <= 0:
            for name in series_names:
                values = np.asarray(getattr(result, name), dtype=float)
                traces[name] = Traced(
                    values=values,
                    segments=[
                        Segment(
                            0,
                            values.size - 1,
                            Provenance.INTEGRATED,
                            "integrated forward from the observed end state",
                        )
                    ],
                )
            return ResilientProjection(
                result=result,
                requested_horizon=requested,
                integrated_horizon=integrated,
                traces=traces,
                attempts=attempts,
                notes=notes,
            )

        # Extend. Output and the two capital stocks are extended in logs; the two ratios are recomputed
        # from them rather than extended independently, so the extended tail stays internally consistent.
        #
        # THE SLOPE COMES FROM THE OBSERVED HISTORY, NOT FROM THE INTEGRATED TAIL, and this is the whole
        # design of the extension. The reason the integration stopped is that the trajectory is running into
        # the finite-time singularity of the unbounded investment share, so its last few periods are
        # *diverging*. Continuing that divergence log-linearly compounds it: on United States data it took
        # the saturation axis to 37 over a 40-period request and to 3.7e24 over a 200-period one, which is
        # arithmetic rather than a statement about the economy.
        #
        # So the rule is: take the LEVEL from where the model actually got to, and the SLOPE from the
        # economy's own observed growth. Both halves are stated on the output, and where the two rates
        # differ materially that difference is reported, because it is the measure of how hard the model was
        # diverging when it stopped.
        extended: dict[str, np.ndarray] = {}
        rates: dict[str, tuple[float, float]] = {}
        for name, observed in (
            ("output", path.output),
            ("real_capital", path.real_capital),
            ("financial_capital", path.financial_capital),
        ):
            base = np.asarray(getattr(result, name), dtype=float)
            historical = _mean_log_growth(np.asarray(observed, dtype=float))
            diverging = _mean_log_growth(base, extrapolation_window)
            rates[name] = (historical, diverging)
            extended[name] = np.concatenate(
                [base, _extend_log_linear(float(base[-1]), historical, missing)]
            )

        share = (
            float(result.saturation[-1] * result.output[-1] / result.financial_capital[-1])
            if result.financial_capital[-1]
            else float("nan")
        )
        extended["saturation"] = share * extended["financial_capital"] / extended["output"]
        extended["real_to_financial"] = extended["real_capital"] / extended["financial_capital"]

        last_period = int(result.periods[-1])
        extended_periods = np.concatenate(
            [np.asarray(result.periods), np.arange(last_period + 1, last_period + missing + 1)]
        )

        for name in series_names:
            values = extended[name]
            traces[name] = Traced(
                values=values,
                segments=[
                    Segment(0, integrated - 1, Provenance.INTEGRATED,
                            "integrated forward from the observed end state"),
                    Segment(
                        integrated,
                        values.size - 1,
                        Provenance.EXTRAPOLATED,
                        f"level from the integrated tail at {last_period}, slope from the observed "
                        f"history. Not a model consequence.",
                    ),
                ],
            )

        failed = [a for a in attempts if not a["integrated"]]
        reason = failed[0]["reason"] if failed else "the requested horizon was not attempted"
        notes.append(
            f"the model integrated {integrated} of the {requested} periods requested. The remaining "
            f"{missing} are EXTRAPOLATED: the level continues from where the integration reached in "
            f"{last_period} and the growth rate is the economy's own observed rate. Read them as a "
            f"straight line in logs, not as a projection."
        )
        notes.append(
            "the slope is taken from the observed history rather than from the integrated tail on purpose. "
            "The integration stopped because the trajectory was diverging, so continuing that divergence "
            "would compound it into arithmetic rather than a statement about the economy."
        )
        notes.append(f"the longer horizon failed because: {reason}")

        for name, (historical, diverging) in rates.items():
            if np.isfinite(historical) and np.isfinite(diverging) and abs(diverging) > 3.0 * abs(historical):
                notes.append(
                    f"{name} was growing at {diverging:+.1%} per period over the last "
                    f"{min(extrapolation_window, integrated)} integrated periods against an observed "
                    f"{historical:+.1%}, which is how hard the model was diverging when it stopped. The "
                    f"extrapolation uses the observed rate."
                )

        # Re-classify over the extended path so the phase timeline covers the whole horizon, and mark the
        # transitions that fall in the extrapolated tail.
        thresholds = kwargs.get("thresholds") or PhaseThresholds()
        # One sequence, so the latched exit from Phase 4 carries across the extrapolated tail as well.
        classifications = classify_sequence(
            saturation=[float(v) for v in extended["saturation"]],
            real_capital=[float(v) for v in extended["real_capital"]],
            financial_capital=[float(v) for v in extended["financial_capital"]],
            output=[float(v) for v in extended["output"]],
            thresholds=thresholds,
        )
        transitions: list[ProjectedPhase] = []
        previous = classifications[0].phase
        for index in range(1, len(classifications)):
            phase = classifications[index].phase
            if phase is not previous:
                transitions.append(
                    ProjectedPhase(
                        period=int(extended_periods[index]),
                        from_phase=previous.label,
                        to_phase=phase.label,
                        saturation=float(extended["saturation"][index]),
                        real_to_financial=float(extended["real_to_financial"][index]),
                    )
                )
                previous = phase

        crossed = [t.period for t in transitions if t.period > last_period]
        if crossed:
            notes.append(
                f"transitions at {', '.join(str(p) for p in crossed)} fall in the extrapolated tail, so "
                f"they are consequences of a straight line rather than of the model."
            )

        extended_result = replace(
            result,
            periods=extended_periods,
            output=extended["output"],
            real_capital=extended["real_capital"],
            financial_capital=extended["financial_capital"],
            saturation=extended["saturation"],
            real_to_financial=extended["real_to_financial"],
            phase_at_end=classifications[-1].phase.label,
            transitions=transitions,
            notes=notes,
        )

        return ResilientProjection(
            result=extended_result,
            requested_horizon=requested,
            integrated_horizon=integrated,
            traces=traces,
            attempts=attempts,
            notes=notes,
        )

    tried = ", ".join(str(a["horizon"]) for a in attempts)
    raise ProjectionError(
        f"{economy}: no horizon integrates, having tried {tried}. There is therefore nothing to "
        f"extrapolate from, and continuing in a straight line off the observed end state would be a "
        f"statement about arithmetic rather than about the model. The calibration itself is the thing to "
        f"look at."
    )


def summarise(result: ProjectionResult) -> str:
    """A short prose summary of a projection, in the register the briefs use."""
    lines = [
        f"Projection for {result.economy} from {result.from_period}, {result.horizon} periods, "
        f"{result.label}.",
        "",
    ]
    first, last = result.periods[0], result.periods[-1]
    lines.append(
        f"  saturation      {result.saturation[0]:.2f} at {first} to {result.saturation[-1]:.2f} at {last}"
    )
    lines.append(
        f"  K_R / K_I       {result.real_to_financial[0]:.2f} to {result.real_to_financial[-1]:.2f}"
    )
    lines.append(f"  phase at {last}   {result.phase_at_end}")

    if result.transitions:
        lines.append("")
        lines.append("  projected transitions, read as a sequence rather than as dates:")
        for transition in result.transitions:
            lines.append(
                f"    {transition.period}  {transition.from_phase} to {transition.to_phase}"
            )
    else:
        lines.append("")
        lines.append("  no phase transition is projected within the horizon")

    if result.scenarios:
        lines.append("")
        lines.append("  both Phase IV resolution paths are projected, since the model does not choose:")
        for name, scenario in result.scenarios.items():
            lines.append(f"    {name}: {scenario.mechanism}")
            lines.append(f"      implication: {scenario.asset_implication}")

    lines.append("")
    lines.append("  reliability of this projection, measured in sample:")
    for name in ("Y", "K_R", "K_I"):
        entry = result.reliability.get(name)
        if isinstance(entry, dict):
            lines.append(
                f"    {name}: direction {entry['directional_accuracy']:.2f}, "
                f"turning points {entry['turning_point_hit_rate']:.2f}, "
                f"lead {entry['mean_lead_lag_periods']:+.1f} periods"
            )
    lines.append("")
    lines.append("  assumptions:")
    lines.extend(f"    {assumption}" for assumption in result.assumptions)
    return "\n".join(lines)
