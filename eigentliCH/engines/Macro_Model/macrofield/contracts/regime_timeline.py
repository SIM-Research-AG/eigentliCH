"""The Regime timeline contract, at monthly frequency.

What this publishes and why it looks like this.

**The consumers need a distribution, not a state.** The Portfolio Creation Program's objective
integrates each instrument's per-state return profile against a 25-length probability vector, one per
period. A single integer state per period would force the consumer to expand a path into a
distribution, which is a modelling decision the consumer has no basis to make. So the contract carries
the full distribution per period, and the integer `path` alongside it for consumers that only need the
modal reading (the Fund Map estimator aligns return history to a state, not to a distribution).

**Monthly, with the annual macro reading held as a step.** This programme assesses the macro state
annually, because the quantities it rests on (output, capital stocks, credit saturation) are published
annually. The technical TAA signal is monthly. The published timeline is monthly: the TAA enters at
full monthly resolution and each annual macro reading is held flat across the twelve months of its
year.

The hold is not interpolation. Interpolating would manufacture readings between two annual
observations that nobody assessed. Holding asserts only what the annual assessment said, for as long as
it was the standing assessment. Every month of intra-year variation in the published timeline therefore
comes from the TAA, which genuinely is monthly, and the hold is recorded in `provenance` and in the
notes so a consumer can see which half of the blend moves within a year.

**The observed window only.** This contract carries no projection and no scenario lever. The cockpit's
scenario endpoint layers control paths, forward projections and tilt sweeps on top of the same signal
to explore futures; that is exploration, and a published contract that moved when someone dragged a
slider would not be a contract. What is published is the assessed history and the current reading.

**Determinism.** `regime_id` and `regime_timeline_id` are hashes of the payload, so identical inputs
produce identical identifiers and a consumer can tell whether two artefacts are the same Regime. There
is no wall-clock in either, and `as_of` is the last month the data covers rather than the day the file
was written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from macrofield import config as config_module

STATE_GRID: int = 25

#: Bumped when the published shape changes. Consumers pin this.
CONTRACT_VERSION: str = "rtl@0.1.0"

#: How many of the most cautious states constitute the crisis tail, for the reported diagnostic.
DEFAULT_TAIL_BINS: int = 5


class RegimeTimelineError(ValueError):
    """Raised when a Regime timeline cannot be built from the inputs supplied."""


# ---------------------------------------------------------------------------
# The contract object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeTimelineContract:
    """One economy's Regime timeline, in the shape consumers read.

    Attributes:
        regime_timeline_id: Identifies this timeline. A hash of the payload.
        regime_id: Identifies the current reading. A hash of the payload. Downstream artefacts stamp
            this, and a ReturnSet whose regime_id differs from the Regime it is optimised against is
            rejected rather than reconciled.
        economy_scope: The economy code, or `Global` for a blended timeline.
        model_version: This programme's version, so a consumer can tell what produced the numbers.
        contract_version: The shape version.
        as_of: The last month covered, `YYYY-MM-DD` at month end.
        period: Always `M` here. Kept explicit because the consumer's validator checks it.
        state_grid: Always 25.
        dates: One `YYYY-MM` label per row of `distributions`, ascending.
        distributions: Rows by 25. Each row is a probability vector over the states, ordered index 0
            most cautious (crisis-like) to index 24 most aggressive (boom-like).
        path_states: The modal state per period, zero-based, for consumers that need a single state.
        current_state: The state of the last period, as the bin nearest its probability-weighted mean.
            **Not the mode**, deliberately: see `describe_reading`. `path_states[-1]` is the mode and may
            differ, which is legal only when the distribution is bimodal and is validated as such.
        current_modal_state: The modal state of the last period, carried so a consumer that wants the mode
            still has it and can see the margin it won by.
        current_mean_bin: The probability-weighted mean bin of the last period, one-based.
        current_mode_margin: How far the tallest mode leads the runner-up. A small margin on a bimodal
            distribution is exactly when the modal reading should not be trusted.
        current_bimodal: Whether the last period carries more than one prominent mode.
        current_phase: The capital-cycle phase, 1 to 4, or None where it could not be classified.
        current_saturation_pct: Credit saturation as a percentage, or None.
        crisis_tail: Probability mass on the most cautious `DEFAULT_TAIL_BINS` states of the last
            period. Reported because the downstream objective is asymmetric and weights the crisis tail
            directly, so a tail that has been smoothed away changes what the optimiser does.
        provenance: Where the numbers came from and what was held rather than observed.
        notes: Anything a consumer must know.
    """

    regime_timeline_id: str
    regime_id: str
    economy_scope: str
    model_version: str
    contract_version: str
    as_of: str
    period: str
    state_grid: int
    dates: tuple[str, ...]
    distributions: np.ndarray
    path_states: tuple[int, ...]
    current_state: int
    current_phase: int | None
    current_saturation_pct: float | None
    crisis_tail: float
    #: The modal reading and how fragile it is. Defaulted so an older caller still constructs, but every
    #: caller in this module supplies them. See `describe_reading` on why `current_state` is not the mode.
    current_modal_state: int | None = None
    current_mean_bin: float | None = None
    current_mode_margin: float | None = None
    current_bimodal: bool | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_distributions(self.distributions, self.dates)
        # `path_states` is the modal path, because the Fund Map estimator tags a month's return with the state
        # that was active and a mode is the right label for that. `current_state` is the mean-nearest bin,
        # because it is a headline and must not jump on a fraction of a point. They may therefore differ — but
        # only when the distribution is bimodal, which is the only circumstance that justifies it. Anything
        # else means one of the two was computed wrongly.
        if self.path_states and self.current_state != self.path_states[-1]:
            if not self.current_bimodal:
                raise RegimeTimelineError(
                    f"current_state {self.current_state} differs from the modal path's last state "
                    f"{self.path_states[-1]} on a distribution that is not bimodal. The two may only diverge "
                    f"where more than one prominent mode exists; otherwise the mean-nearest bin and the mode "
                    f"agree by construction and a difference is an arithmetic fault."
                )

    @property
    def n_periods(self) -> int:
        return int(np.asarray(self.distributions).shape[0])

    def to_dict(self) -> dict[str, Any]:
        """The published payload.

        `path` and `distributions` are both present by design: the Fund Map estimator tags a monthly
        return with the state that was active, and the Portfolio Optimiser integrates the distribution.
        Publishing only one of them would push a modelling decision onto whichever consumer needed the
        other.
        """
        current: dict[str, Any] = {"regime_id": self.regime_id, "state": int(self.current_state)}
        if self.current_modal_state is not None:
            current["modal_state"] = int(self.current_modal_state)
        if self.current_mean_bin is not None:
            current["mean_bin"] = float(self.current_mean_bin)
        if self.current_mode_margin is not None:
            current["mode_margin"] = float(self.current_mode_margin)
        if self.current_bimodal is not None:
            current["bimodal"] = bool(self.current_bimodal)
        if self.current_phase is not None:
            current["phase"] = int(self.current_phase)
        if self.current_saturation_pct is not None:
            current["saturation_pct"] = float(self.current_saturation_pct)
        current["crisis_tail"] = float(self.crisis_tail)

        return {
            "regime_timeline_id": self.regime_timeline_id,
            "economy_scope": self.economy_scope,
            "model_version": self.model_version,
            "contract_version": self.contract_version,
            "as_of": self.as_of,
            "period": self.period,
            "state_grid": int(self.state_grid),
            "path": [
                {"date": d, "state": int(s)} for d, s in zip(self.dates, self.path_states)
            ],
            "distributions": [
                {"date": d, "weights": [float(w) for w in row]}
                for d, row in zip(self.dates, np.asarray(self.distributions, dtype=float))
            ],
            "current": current,
            "provenance": dict(self.provenance),
            "notes": list(self.notes),
        }


def describe_reading(row: Any, tail_bins: int = DEFAULT_TAIL_BINS) -> dict[str, Any]:
    """The headline statistics for one distribution, with the modal reading's fragility measured.

    **Why `state` is not an argmax.** The published `current.state` used to be `argmax(row)`. Twice now that has
    jumped across the axis on a margin of well under a percentage point, because this system routinely produces
    **bimodal** distributions and an argmax over two near-equal peaks is not a stable statistic:

    - the cycle layer at a blend weight of 0.15 moved China's reported state from 11 to 1 while its mean bin
      moved 0.15 of a bin (M53, which is why that weight is capped at 0.14);
    - wiring the capital-overdue and innovation-approach tilts moved seven of eight economies to state 1 on a
      **0.4 point** margin between bins 2 and 12, while every mean bin moved less than one bin (M57).

    Both times the distribution did something modest and the reported state did something dramatic. So `state`
    is now the bin **nearest the probability-weighted mean**, which moves smoothly with the distribution, and
    the modal reading is carried beside it with the margin that separates the top two modes. A consumer that
    genuinely wants the mode still has it, and can see how much to trust it.

    Returns a dict with zero-based `state`, `modal_state`, `mean_bin` (one-based, as the axis is written),
    `modes` (one-based local maxima above a quarter of the peak), `mode_margin` and `bimodal`.
    """
    weights = np.asarray(row, dtype=float)
    total = weights.sum()
    if total <= 0:
        raise RegimeTimelineError("a distribution row sums to zero, so it has no reading")
    weights = weights / total
    bins = np.arange(1, weights.size + 1)
    mean_bin = float((bins * weights).sum())

    peak = float(weights.max())
    modes: list[int] = []
    for i in range(weights.size):
        left = weights[i - 1] if i > 0 else -np.inf
        right = weights[i + 1] if i < weights.size - 1 else -np.inf
        if weights[i] >= left and weights[i] >= right and weights[i] >= 0.25 * peak:
            modes.append(i + 1)
    ordered = sorted(modes, key=lambda b: -weights[b - 1])
    margin = (
        float(weights[ordered[0] - 1] - weights[ordered[1] - 1]) if len(ordered) > 1 else float(peak)
    )
    return {
        "state": int(round(mean_bin)) - 1,
        "modal_state": int(np.argmax(weights)),
        "mean_bin": mean_bin,
        "modes": modes,
        "mode_margin": margin,
        "bimodal": len(modes) > 1,
        "crisis_tail": float(weights[:tail_bins].sum()),
    }


def _validate_distributions(distributions: Any, dates: Sequence[str]) -> np.ndarray:
    arr = np.asarray(distributions, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != STATE_GRID:
        raise RegimeTimelineError(
            f"distributions must have shape (T, {STATE_GRID}), got {arr.shape}"
        )
    if arr.shape[0] == 0:
        raise RegimeTimelineError(
            "the timeline is empty. The macro window and the TAA history do not overlap, so there is "
            "no month for which both halves of the signal exist."
        )
    if arr.shape[0] != len(dates):
        raise RegimeTimelineError(
            f"{arr.shape[0]} distribution rows against {len(dates)} dates"
        )
    if np.any(~np.isfinite(arr)):
        raise RegimeTimelineError("a distribution carries a non-finite weight")
    if np.any(arr < -1e-12):
        worst = int(np.argmin(arr.min(axis=1)))
        raise RegimeTimelineError(f"the distribution for {dates[worst]} carries a negative weight")
    sums = arr.sum(axis=1)
    bad = np.flatnonzero(np.abs(sums - 1.0) > 1e-6)
    if bad.size:
        i = int(bad[0])
        raise RegimeTimelineError(
            f"the distribution for {dates[i]} sums to {sums[i]:.8f} rather than 1"
        )
    return arr


# ---------------------------------------------------------------------------
# The annual macro signal over the observed window
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnualSAA:
    """The macro signal over the observed window, one distribution per year."""

    periods: tuple[int, ...]
    matrix: np.ndarray                 # (n_years, 25)
    saturation: np.ndarray             # (n_years,), the ratio
    phase_value: int | None
    phase_label: str | None
    tilts_active: tuple[str, ...]
    notes: tuple[str, ...]

    #: The cycle layer over the same years, (n_years, 25), or None where it could not be formed.
    #:
    #: Carried here rather than recomputed in `build_timeline` because this function already has the
    #: band-passed estimates and the anchored cycles in hand, and computing them twice would let the layer
    #: that gets blended drift from the layer whose tilts fired. See `macrofield.model.cycle_bins` and
    #: `DECISIONS.md` M53.
    cycles: np.ndarray | None = None

    #: What the latest period's cycle layer looked like, for a board or a manifest. None with `cycles`.
    cycle_summary: dict | None = None

    #: Years since this economy crossed the capital-cycle reordering point, per period. Negative before it.
    #: Carried so a caller can see the quantity the `capital_overdue_per_decade` tilt reads, which for a long
    #: time nothing populated at all — see `DECISIONS.md` M57.
    capital_overdue: list[float] | None = None

    #: Years until the configured innovation low, per period. Global, so identical for every economy.
    innovation_to_trough: list[float] | None = None

    #: The tilts that fired at the LATEST period, as against `tilts_active` which accumulates over the whole
    #: window. Both are wanted and they answer different questions: the accumulation says what this economy's
    #: history exercised, and this says what explains the distribution a reader is looking at now. Keeping only
    #: the accumulation would put "saturation_below_band" beside a current reading that is nowhere near the
    #: lower band, which is true of the window and misleading about today. Author's decision, 2026-08-02.
    tilts_firing_now: tuple[str, ...] = ()


def saa_over_observed_window(economy, settings=None) -> AnnualSAA:
    """Build the annual macro signal for one assembled economy.

    Uses the observed window only. The cycle superposition is included because `decompose` and
    `superpose` run on the observed path and need no projection, so leaving them out would silence
    tilts that are genuinely available. The two anchored long cycles are included where the
    configuration can anchor them, and omitted (rather than defaulted) where it cannot, since an anchor
    is the entire content of an anchored cycle.

    Raises:
        RegimeTimelineError: If the signal cannot be formed for a period.
    """
    from macrofield.model.cycles import (
        CycleError,
        anchored_from_config,
        bands_from_config,
        decompose,
        interference_members,
        superpose,
    )
    from macrofield.model.cycle_bins import CycleBinError
    from macrofield.model.cycle_bins import layer_matrix as cycle_layer_matrix
    from macrofield.model.phases import PhaseThresholds, classify_period
    from macrofield.model.quantity import unsecured_assets_ratio
    from macrofield.model.regime import RegimeKernels
    from macrofield.model.saa_signal import (
        SAASignalError,
        StateReading,
        signal_from_state,
    )

    resolved = settings if settings is not None else config_module.load(economy.code)
    path = economy.path
    periods = [int(p) for p in path.periods]
    if not periods:
        raise RegimeTimelineError(f"{economy.code}: the observed window is empty")

    band = (
        float(resolved.get("saturation.balanced_band.lower")),
        float(resolved.get("saturation.balanced_band.upper")),
    )
    tilts = dict(resolved.get("saa.tilts"))
    kernels = RegimeKernels.from_config(resolved)
    minimum_tail = float(resolved.get("regime.minimum_tail_probability"))
    tail_bins = int(resolved.get("regime.tail_bins"))

    saturation = (
        economy.saturation.values.loc[economy.window[0] : economy.window[1]]
        .reindex(path.periods)
        .to_numpy(dtype=float)
    )
    real_capital = np.asarray(path.real_capital, dtype=float)
    financial_capital = np.asarray(path.financial_capital, dtype=float)
    output = np.asarray(path.output, dtype=float)
    real_to_financial = real_capital / financial_capital

    unsecured = np.asarray(
        unsecured_assets_ratio(real_capital, financial_capital, output), dtype=float
    )
    # The first period has no prior to difference against, so its change is unavailable rather than
    # zero. `StateReading` takes None for that and the tilt simply does not fire.
    unsecured_change = np.concatenate([[np.nan], np.diff(unsecured)])

    notes: list[str] = []
    tilts_active: set[str] = {"base"}
    tilts_firing_now: tuple[str, ...] = ()

    # ---- the cycle superposition, where it can be formed --------------------
    interference: np.ndarray | None = None
    alignment: np.ndarray | None = None
    capital_overdue: list[float] | None = None
    innovation_to_trough: list[float] | None = None
    cycle_matrix: np.ndarray | None = None
    cycle_summary: dict | None = None
    try:
        growth = np.gradient(np.log(np.where(output > 0.0, output, np.nan)))
        estimates = decompose(growth, bands_from_config(resolved), sampling_per_year=1.0)
        anchored = anchored_from_config(resolved, path.periods, saturation)

        # Only anchored cycles the configuration admits to the interference measure are folded in. Before
        # 2026-08-02 every anchored cycle was, which was correct while every anchored cycle belonged there.
        # The hegemonic cycle does not (`cycles.anchored.hegemonic.in_interference` is false, M52), and
        # without this filter adding it to `anchored_from_config` would have silently given the fragility
        # window a fifth contributor — the precise thing that decision excluded. Caught by tracing the
        # cycle-layer wiring rather than by a test, which is why one now exists.
        admitted = set(interference_members(resolved, anchored))
        for name, cycle in anchored.items():
            if name in admitted:
                estimates[name] = cycle.estimate
        excluded = sorted(set(anchored) - admitted)
        if excluded:
            notes.append(
                f"anchored but held out of the interference measure by configuration: "
                f"{', '.join(excluded)}. They are positioned and reported, and the fragility window is "
                f"computed without them, so their addition moved no published conclusion."
            )

        # ---- the cycle layer, on the axis rather than as a tilt --------------
        #
        # Built from the SAME estimates and anchored cycles the interference tilt uses, and deliberately
        # from all of them: `interference_members` governs the fragility measure, not this. The hegemonic
        # cycle is held out of A(t) and belongs on the axis, which is the distinction M52 drew.
        try:
            bins_settings = dict(resolved.get("cycles.bins", default={}) or {})
            if bins_settings:
                cycle_matrix, cycle_layers = cycle_layer_matrix(
                    estimates,
                    {name: cycle for name, cycle in anchored.items()},
                    bins_settings,
                    len(periods),
                    step_years=1.0,
                )
                cycle_summary = cycle_layers[-1].to_payload() if cycle_layers else None
                notes.extend(cycle_layers[-1].notes if cycle_layers else [])
        except CycleBinError as error:
            notes.append(
                f"the cycle layer could not be placed on the axis ({error}), so the blend runs on the macro "
                f"and technical halves alone. That makes the signal less informed rather than wrong."
            )

        # ---- the two cycle-position quantities the tilts read --------------
        #
        # `capital_overdue_per_decade` and `innovation_approach_per_decade` were configured, implemented in
        # `saa_signal.regime_weights_from_state`, documented — and had **never fired in any published Regime**,
        # because nothing populated the `StateReading` fields they read. Found by sweeping the tilts and seeing
        # two of them move nothing for any of the eight economies (DECISIONS.md M57).
        #
        # capital_years_overdue: years since this economy crossed the reordering point. The anchor's contract is
        # "reaching credit/GDP 3.5 means you are `years_into_cycle_at_anchor` years into the cycle", so the
        # crossing year IS the reordering point and anything after it is overdue. Negative where the crossing
        # has not happened, which the tilt ignores.
        #
        # innovation_years_to_trough: years until the configured low. Global and identical for every economy.
        capital = anchored.get("capital")
        if capital is not None and capital.anchored and capital.reference_year is not None:
            capital_overdue = [float(p) - float(capital.reference_year) for p in periods]
        innovation = anchored.get("innovation")
        if innovation is not None and innovation.reference_year is not None:
            innovation_to_trough = [float(innovation.reference_year) - float(p) for p in periods]

        weights = resolved.get("cycles.superposition.weights")
        superposition = superpose(path.periods, estimates, weights)
        interference = np.asarray(superposition.total, dtype=float)
        alignment = np.asarray(superposition.alignment, dtype=float)
        tilts_active.update({"interference", "alignment_gain"})
        if not anchored:
            notes.append(
                "no long cycle could be anchored, so the capital-overdue and innovation-approach tilts "
                "did not fire. The signal rests on saturation, the real-to-financial ratio and the "
                "estimated short cycles."
            )
    except (CycleError, ValueError) as error:
        notes.append(
            f"the cycle decomposition was unavailable ({error}), so the interference tilt did not fire. "
            f"The signal rests on the saturation and real-to-financial tilts only, which makes it less "
            f"responsive rather than wrong."
        )

    # ---- the phase of the latest reading -----------------------------------
    phase_value: int | None = None
    phase_label: str | None = None
    try:
        classification = classify_period(
            saturation=float(saturation[-1]),
            real_capital=float(real_capital[-1]),
            financial_capital=float(financial_capital[-1]),
            output=float(output[-1]),
            thresholds=PhaseThresholds.from_config(config_module.load()),
        )
        phase_value = int(classification.phase.value)
        phase_label = str(classification.phase.label)
    except Exception as error:  # noqa: BLE001 - the phase is a diagnostic, not a precondition
        notes.append(
            f"the capital-cycle phase could not be classified ({error}), so it is reported as "
            f"unavailable rather than guessed."
        )

    # ---- the per-period signal ---------------------------------------------
    rows: list[np.ndarray] = []
    for index, period in enumerate(periods):
        reading = StateReading(
            period=period,
            saturation=float(saturation[index]),
            band=band,
            real_to_financial=float(real_to_financial[index]),
            unsecured_change=(
                None if not np.isfinite(unsecured_change[index]) else float(unsecured_change[index])
            ),
            interference=(
                None
                if interference is None or not np.isfinite(interference[index])
                else float(interference[index])
            ),
            capital_years_overdue=(
                None if capital_overdue is None else capital_overdue[index]
            ),
            innovation_years_to_trough=(
                None if innovation_to_trough is None else innovation_to_trough[index]
            ),
            alignment=(
                None
                if alignment is None or not np.isfinite(alignment[index])
                else float(alignment[index])
            ),
        )
        try:
            signal = signal_from_state(
                reading,
                kernels=kernels,
                tilts=tilts,
                minimum_tail_probability=minimum_tail,
                tail_bins=tail_bins,
            )
        except SAASignalError as error:
            raise RegimeTimelineError(
                f"{economy.code}: the macro signal could not be formed for {period}: {error}"
            ) from error
        rows.append(signal.probabilities)
        # What actually fired, read off the signal rather than assumed.
        #
        # This used to be seeded with {"base"} and updated with {"interference", "alignment_gain"} when the
        # cycle decomposition succeeded — so it reported the same three tilts for every economy and never
        # mentioned `saturation_above_band`, which moves France's crisis tail by 2.4 points. It was really
        # "which tilt inputs were available", under a name that claimed otherwise. `apply()` in
        # `regime_weights_from_state` already records every tilt it applies; this reads that. DECISIONS.md M57.
        fired = tuple(sorted(str(name) for name in getattr(signal, "contributions", {}) or {}))
        tilts_active.update(fired)
        if index == len(periods) - 1:
            tilts_firing_now = fired
            notes.extend(str(n) for n in signal.notes)

    if np.any(~np.isfinite(saturation)):
        raise RegimeTimelineError(
            f"{economy.code}: the saturation axis has a gap inside the calibration window, so a "
            f"macro reading is missing for at least one period. The Regime is not published on a "
            f"partially observed window."
        )

    # The axis had no upper bound at all until 2026-08-02, so a ratio of 20 would have been accepted and given
    # a phase. Refused rather than classified above the configured ceiling: past that, a value can only be an
    # ingestion fault, and classifying a fault is worse than refusing an economy. See config on why the ceiling
    # is 6.0 rather than the 5.0 first proposed — France's 2020 reading is 5.212, a real denominator effect.
    ceiling = resolved.get("saturation.refuse_above", default=None)
    if ceiling is not None:
        breaches = [
            (p, float(s)) for p, s in zip(periods, saturation) if float(s) > float(ceiling)
        ]
        if breaches:
            raise RegimeTimelineError(
                f"{economy.code}: the saturation axis reaches "
                f"{max(v for _, v in breaches):.3f} at {breaches[0][0]}, above the configured ceiling of "
                f"{float(ceiling):g}. The Regime is refused rather than published: the framework describes "
                f"nothing at that level, so a phase classification there would be an extrapolation presented "
                f"as a reading. {len(breaches)} period(s) breach. Check the credit and GDP series before "
                f"raising saturation.refuse_above."
            )

    return AnnualSAA(
        periods=tuple(periods),
        matrix=np.vstack(rows),
        saturation=saturation,
        phase_value=phase_value,
        phase_label=phase_label,
        tilts_active=tuple(sorted(tilts_active)),
        notes=tuple(notes),
        cycles=cycle_matrix,
        cycle_summary=cycle_summary,
        capital_overdue=capital_overdue,
        innovation_to_trough=innovation_to_trough,
        tilts_firing_now=tilts_firing_now,
    )


# ---------------------------------------------------------------------------
# The monthly hold and the blend
# ---------------------------------------------------------------------------


def _month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _month_end_iso(year: int, month: int) -> str:
    import calendar

    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def hold_annual_to_monthly(
    annual_periods: Sequence[int],
    annual_matrix: np.ndarray,
    months: Sequence[tuple[int, int]],
) -> np.ndarray:
    """Repeat each annual macro distribution across the months of its year.

    A step, not an interpolation: see the module docstring. A month whose year has no annual reading is
    not emitted at all, so the caller must intersect first. This function raises rather than
    forward-filling past the end of the annual panel, because holding a stale macro reading into a year
    it was never assessed for would present an assessment that does not exist.
    """
    matrix = np.asarray(annual_matrix, dtype=float)
    if matrix.shape[0] != len(annual_periods):
        raise RegimeTimelineError(
            f"{matrix.shape[0]} annual rows against {len(annual_periods)} annual periods"
        )
    by_year = {int(p): matrix[i] for i, p in enumerate(annual_periods)}
    missing = sorted({y for y, _ in months if y not in by_year})
    if missing:
        raise RegimeTimelineError(
            f"no annual macro reading for year(s) {missing}, so those months cannot be held. "
            f"Intersect the month range with the annual panel before calling."
        )
    return np.vstack([by_year[int(y)] for y, _ in months])


def build_timeline(
    economy,
    taa_signal,
    settings=None,
    blend_weight: float | None = None,
    economy_scope: str | None = None,
) -> RegimeTimelineContract:
    """Build the monthly Regime timeline for one assembled economy.

    Args:
        economy: An `AssembledEconomy` from `macrofield.pipeline.assemble`.
        taa_signal: A `TAASignal` from `macrofield.data.taa.load_signal`.
        settings: The loaded configuration. Loaded from the economy code if omitted.
        blend_weight: Weight on the macro half. Defaults to the configured `saa.blend_weight`.
        economy_scope: Overrides the published scope label. Defaults to the economy code.

    Returns:
        The contract, ready to write.

    Raises:
        RegimeTimelineError: If the macro window and the TAA history do not overlap, or the signal
            cannot be formed.
    """
    from macrofield.model.saa_signal import SAASignalError, merge

    resolved = settings if settings is not None else config_module.load(economy.code)
    saa = saa_over_observed_window(economy, resolved)
    blend = float(resolved.get("saa.blend_weight") if blend_weight is None else blend_weight)

    # Only months the TAA file actually carries, intersected with years the macro panel assessed.
    # Neither side is extended: a month missing from the TAA is skipped rather than forward-filled, so
    # the published timeline contains no month that both halves did not cover.
    annual_years = set(saa.periods)
    months = [(y, m) for (y, m) in taa_signal.months if y in annual_years]
    if not months:
        taa_first, taa_last = taa_signal.months[0], taa_signal.months[-1]
        raise RegimeTimelineError(
            f"{economy.code}: the macro window {saa.periods[0]} to {saa.periods[-1]} does not overlap "
            f"the TAA history {taa_first[0]}-{taa_first[1]:02d} to {taa_last[0]}-{taa_last[1]:02d}, so "
            f"no month has both halves of the signal."
        )

    taa_index = {m: i for i, m in enumerate(taa_signal.months)}
    taa_matrix = np.vstack([np.asarray(taa_signal.distribution, dtype=float)[taa_index[m]] for m in months])
    saa_matrix = hold_annual_to_monthly(saa.periods, saa.matrix, months)

    # The cycle layer is held to monthly by the SAME step hold as the macro half, and for the same reason:
    # it derives from the annual path, so it asserts one reading per year and nothing between. Interpolating
    # it would manufacture intra-year cycle movement that no annual assessment made.
    cycle_matrix = None
    cycles_weight = 0.0
    if saa.cycles is not None:
        configured = float((resolved.get("cycles.bins", default={}) or {}).get("blend_weight", 0.0) or 0.0)
        if configured > 0.0:
            cycle_matrix = hold_annual_to_monthly(saa.periods, saa.cycles, months)
            cycles_weight = configured

    # `merge` normalises each blended row and reports multi-modality. Integer ordinals are passed as the
    # period labels because merge casts them to int when it names a multi-modal period; the readable
    # month labels are kept alongside and are what the contract publishes.
    ordinals = [y * 12 + (m - 1) for y, m in months]
    try:
        merged = merge(
            ordinals,
            saa_matrix,
            taa_matrix,
            weight=blend,
            config=resolved,
            cycles=cycle_matrix,
            cycles_weight=cycles_weight,
        )
    except SAASignalError as error:
        raise RegimeTimelineError(f"{economy.code}: the blend failed: {error}") from error

    distributions = np.asarray(merged.merged, dtype=float)
    dates = tuple(_month_label(y, m) for y, m in months)
    path_states = tuple(int(np.argmax(row)) for row in distributions)
    crisis_tail = float(distributions[-1][:DEFAULT_TAIL_BINS].sum())

    skipped = [
        _month_label(y, m)
        for (y, m) in taa_signal.months
        if y in annual_years and (y, m) not in set(months)
    ]

    notes = list(saa.notes)
    if cycles_weight > 0.0:
        notes.append(
            f"the macro half is an annual assessment held flat across each year's twelve months, and so is "
            f"the cycle layer, which derives from the same annual path; the technical half is monthly. All "
            f"intra-year variation therefore comes from the technical half. Blended in bin space: the macro "
            f"and technical halves at {blend:.0%} to {1 - blend:.0%}, then the cycle layer contributing "
            f"{cycles_weight:.0%} of the result. The two-stage form keeps the macro-to-technical weight "
            f"meaning what it has always meant."
        )
        notes.append(
            f"the cycle layer places each cycle's position as a distribution on the same 25-bin axis and "
            f"mixes them linearly. Its weight is capped at {cycles_weight:.0%} because the published "
            f"distribution and the layer peak at opposite ends of the axis, so the blend is bimodal and a "
            f"higher weight would relocate the modal bin discontinuously — publishing a change of state that "
            f"no input made. `current.state` is a modal reading, so that matters. DECISIONS.md M53."
        )
    else:
        notes.append(
            f"the macro half is an annual assessment held flat across each year's twelve months; the "
            f"technical half is monthly. All intra-year variation therefore comes from the technical half. "
            f"Blended in bin space at {blend:.0%} macro to {1 - blend:.0%} technical. The cycle layer is "
            f"configured off, so it contributes nothing to this timeline."
        )
    notes.append(
        f"published over {dates[0]} to {dates[-1]} ({len(dates)} months), the overlap of the macro "
        f"window ({saa.periods[0]} to {saa.periods[-1]}) and the TAA history. Neither side is extended "
        f"beyond what it covers."
    )
    if taa_signal.rows_dropped:
        notes.append(
            f"{len(taa_signal.rows_dropped)} published TAA row(s) were left out upstream for not "
            f"totalling 100, so those months are absent from the timeline rather than interpolated."
        )
    if skipped:
        notes.append(
            f"{len(skipped)} month(s) inside the window are absent from the TAA file and are therefore "
            f"absent here: {', '.join(skipped[:12])}"
            + (" and others" if len(skipped) > 12 else "")
        )

    # The blend reports multi-modality against the period labels it was given, which are the integer
    # ordinals. Translate the count into month labels here so a reader is not left decoding an ordinal.
    swing_months = [
        dates[i] for i, shape in enumerate(merged.shapes) if int(shape.get("modes", 1)) > 1
    ]
    if swing_months:
        notes.append(
            f"the blended signal is multi-modal in {len(swing_months)} of {len(dates)} months, first at "
            f"{swing_months[0]} and most recently at {swing_months[-1]}. A multi-modal reading is the "
            f"two horizons disagreeing about direction, which the framework reads as a swing market and "
            f"reports rather than smoothing away. Month labels in the blend notes below are integer "
            f"ordinals (year times twelve plus month minus one), not dates."
        )
    notes.extend(str(n) for n in merged.notes)

    provenance = {
        "data_vintage": dict(economy.vintage),
        "calibration_window": [int(economy.window[0]), int(economy.window[1])],
        "macro_periods": [int(p) for p in saa.periods],
        "macro_frequency": "A",
        "macro_to_monthly": "step hold within each year, no interpolation",
        "taa_source": str(getattr(taa_signal, "path", "")),
        "taa_months_covered": len(taa_signal.months),
        "taa_rows_dropped_upstream": len(taa_signal.rows_dropped),
        "blend_weight_macro": blend,
        # The cycle layer's contribution, and what it looked like at the last period. Both go into the hash,
        # so turning the layer on or changing its weight produces a different regime_id — which is correct: a
        # consumer must be able to tell two Regimes apart when the axis was composed differently.
        "cycle_layer_weight": float(cycles_weight),
        "cycle_layer": saa.cycle_summary if cycles_weight > 0.0 else None,
        "tilts_active": list(saa.tilts_active),
        # What fired at the latest period, beside what ever fired. See AnnualSAA.tilts_firing_now on why both.
        "tilts_firing_now": list(saa.tilts_firing_now),
        "phase_label": saa.phase_label,
        "standardising_adjustments": dict(economy.adjustments),
        "sources": sorted({str(v) for v in economy.vintage.values()}),
    }

    scope = economy_scope or economy.code
    payload_for_hash = {
        "economy_scope": scope,
        "model_version": _model_version(),
        "contract_version": CONTRACT_VERSION,
        "period": "M",
        "state_grid": STATE_GRID,
        "dates": list(dates),
        "distributions": [[round(float(w), 12) for w in row] for row in distributions],
        "provenance": _hashable(provenance),
    }
    digest = _hash_payload(payload_for_hash)

    _reading = describe_reading(distributions[-1], DEFAULT_TAIL_BINS)
    return RegimeTimelineContract(
        regime_timeline_id=f"RTL-{digest[:16]}",
        regime_id=f"REG-{digest[:16]}",
        economy_scope=scope,
        model_version=_model_version(),
        contract_version=CONTRACT_VERSION,
        as_of=_month_end_iso(*months[-1]),
        period="M",
        state_grid=STATE_GRID,
        dates=dates,
        distributions=distributions,
        path_states=path_states,
        current_state=_reading["state"],
        current_modal_state=_reading["modal_state"],
        current_mean_bin=_reading["mean_bin"],
        current_mode_margin=_reading["mode_margin"],
        current_bimodal=_reading["bimodal"],
        current_phase=saa.phase_value,
        current_saturation_pct=(
            float(saa.saturation[-1] * 100.0) if np.isfinite(saa.saturation[-1]) else None
        ),
        crisis_tail=crisis_tail,
        provenance=provenance,
        notes=tuple(notes),
    )


def _model_version() -> str:
    from macrofield import __version__

    return f"ms@{__version__}"


def _hashable(value: Any) -> Any:
    """Reduce a payload to something json can serialise deterministically."""
    if isinstance(value, dict):
        return {str(k): _hashable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_hashable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return round(float(value), 12)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 12)
    return str(value)


def _numerical_stack() -> str:
    """This interpreter and the versions of the packages that do the floating-point work here.

    Read from installed metadata rather than by importing, so a package absent from this environment is
    reported as absent instead of raising. Deliberately not part of any hashed payload: see the note where
    this is used.
    """
    import platform
    from importlib.metadata import PackageNotFoundError, version

    parts = [f"python {platform.python_version()}"]
    for name in ("numpy", "scipy", "pandas", "statsmodels"):
        try:
            parts.append(f"{name} {version(name)}")
        except PackageNotFoundError:
            parts.append(f"{name} absent")
    return ", ".join(parts)


def _month_span(first: str, last: str) -> int:
    """How many months the closed interval `first`..`last` covers, gaps included.

    Distinct from `len(dates)`, which counts the months actually present. Reporting one as the other is what
    made the Global blend describe a three-year hole out of existence.
    """
    y0, m0 = int(first[:4]), int(first[5:7])
    y1, m1 = int(last[:4]), int(last[5:7])
    return (y1 - y0) * 12 + (m1 - m0) + 1


def _gap_runs(dates: Sequence[str]) -> list[str]:
    """The missing months in `dates`, collapsed into contiguous runs and rendered for a note.

    A run of one is written as `2014-02`; a longer one as `2019-01..2021-12 (36 months)`, because a reader
    weighing whether the gap matters needs its size without counting.
    """
    if not dates:
        return []
    present = set(dates)
    y, m = int(dates[0][:4]), int(dates[0][5:7])
    y_end, m_end = int(dates[-1][:4]), int(dates[-1][5:7])

    missing: list[str] = []
    while (y, m) <= (y_end, m_end):
        stamp = f"{y:04d}-{m:02d}"
        if stamp not in present:
            missing.append(stamp)
        m += 1
        if m == 13:
            y, m = y + 1, 1

    runs: list[list[str]] = []
    for stamp in missing:
        if runs and _month_span(runs[-1][-1], stamp) == 2:
            runs[-1].append(stamp)
        else:
            runs.append([stamp])

    return [r[0] if len(r) == 1 else f"{r[0]}..{r[-1]} ({len(r)} months)" for r in runs]


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        _hashable(payload), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Write and read
# ---------------------------------------------------------------------------


def blend_scope(
    scope: str,
    timelines: dict[str, RegimeTimelineContract],
    settings=None,
) -> RegimeTimelineContract:
    """Blend per-economy Regimes into the published timeline for one market scope.

    `M = sum_k w_k * M_k` per period, over the economies the scope weights. This reproduces the blend
    `Dataloader.m` line 18 formed from the per-country signal matrices, and it belongs here rather than in
    a consumer: the Return Estimation programme estimates its profiles under one Regime and the optimiser
    integrates one Regime, so unless the blended scope is itself a published Regime the two carry
    different identifiers and can never be reconciled.

    Args:
        scope: A configured scope name, or `equal` for the fallback vector.
        timelines: The per-economy contracts, keyed by economy code. Only the weighted ones are used.
        settings: A loaded Config. Loaded from defaults if omitted.

    Returns:
        The blended contract, with its own `regime_id`.

    Raises:
        RegimeTimelineError: If the scope is unknown, a weighted economy is absent, or the contributors
            share no month.
    """
    resolved = settings if settings is not None else config_module.load()
    slot_order = list(resolved.get("regime.scopes.slot_order"))
    presets = dict(resolved.get("regime.scopes.presets"))
    members_by_slot = dict(resolved.get("regime.scopes.economies_for_slot"))

    if scope not in presets:
        raise RegimeTimelineError(
            f"unknown market scope {scope!r}. Configured: {sorted(presets)}."
        )
    vector = presets[scope]
    if len(vector) != len(slot_order):
        raise RegimeTimelineError(
            f"the preset for {scope!r} has {len(vector)} weights against {len(slot_order)} slots"
        )

    # Flatten slots onto economies. Exact: a slot at weight w whose members carry m_i contributes w*m_i.
    economy_weights: dict[str, float] = {}
    slot_weights: dict[str, float] = {}
    for slot, weight in zip(slot_order, vector):
        slot_weights[slot] = float(weight)
        if float(weight) <= 0.0:
            continue
        for economy, share in members_by_slot[slot].items():
            economy_weights[economy] = economy_weights.get(economy, 0.0) + float(weight) * float(share)

    if not economy_weights:
        raise RegimeTimelineError(f"market scope {scope!r} puts weight on no economy")

    total = float(sum(economy_weights.values()))
    if abs(total - 1.0) > 1e-9:
        raise RegimeTimelineError(
            f"the economy weights for scope {scope!r} sum to {total}, not 1, so the blend would rescale "
            f"every distribution"
        )

    # A weighted economy without a published Regime is a failure, not a renormalisation. Dropping it and
    # rescaling would answer a differently scoped question while still publishing itself as this scope.
    absent = sorted(code for code in economy_weights if code not in timelines)
    if absent:
        raise RegimeTimelineError(
            f"market scope {scope!r} puts weight on {absent}, which have no Regime timeline. The blend is "
            f"not renormalised over whichever economies happen to be available. Publish them first."
        )

    # Intersected, not unioned: a month one economy does not cover cannot be blended, and holding its last
    # reading into that month would put a value into the blend nobody assessed for it.
    common = set(timelines[next(iter(economy_weights))].dates)
    for code in economy_weights:
        common &= set(timelines[code].dates)
    if not common:
        spans = ", ".join(
            f"{code} {timelines[code].dates[0]} to {timelines[code].dates[-1]}"
            for code in sorted(economy_weights)
        )
        raise RegimeTimelineError(
            f"the economies contributing to scope {scope!r} share no month, so no blend exists. "
            f"Spans: {spans}."
        )
    dates = tuple(sorted(common))

    blended = np.zeros((len(dates), STATE_GRID), dtype=float)
    for code, weight in economy_weights.items():
        contract = timelines[code]
        position = {date: i for i, date in enumerate(contract.dates)}
        rows = np.asarray(contract.distributions, dtype=float)
        blended += weight * np.vstack([rows[position[date]] for date in dates])

    contributors = {
        code: {
            "weight": economy_weights[code],
            "regime_id": timelines[code].regime_id,
            "regime_timeline_id": timelines[code].regime_timeline_id,
            "first": timelines[code].dates[0],
            "last": timelines[code].dates[-1],
            "months": len(timelines[code].dates),
            "phase": timelines[code].current_phase,
            "saturation_pct": timelines[code].current_saturation_pct,
        }
        for code in sorted(economy_weights)
    }

    # Which contributor binds each end of the window, and where the blend has holes.
    #
    # This used to name a single "narrowest" contributor chosen by date *count*, and report its first and
    # last month as the window. That was wrong in two ways at once, and both showed on the published Global
    # blend:
    #
    #   - A count is not a span. A contributor with a hole in the middle can hold the fewest months while a
    #     different one sets the start. Global named `in` (156 dates, 2006-08 to 2022-12) as setting a window
    #     that starts 2010-01 — which is `br`'s first month, not `in`'s.
    #   - Printing `len(dates)` beside `dates[0]` and `dates[-1]` presents a gapped series as a contiguous
    #     one. Global read "2010-01 to 2022-12 (117 months)" for a 156-month span carrying 117 months, with
    #     a 36-month hole (2019-01 to 2021-12) that swallowed all of 2020 — and then said a backtest cannot
    #     run longer than the window, without saying it cannot run *through* it either.
    #
    # The blend needs every contributor in a period and drops the period otherwise, so one contributor's gap
    # is the whole blend's gap. At a 5% weight that is a poor trade, and a reader cannot weigh it unless the
    # artefact says so.
    starts_with = max(economy_weights, key=lambda code: timelines[code].dates[0])
    ends_with = min(economy_weights, key=lambda code: timelines[code].dates[-1])
    span_months = _month_span(dates[0], dates[-1])
    gaps = _gap_runs(dates)

    window_note = (
        f"the window {dates[0]} to {dates[-1]} spans {span_months} months and carries {len(dates)}. Its "
        f"start is set by {starts_with} (which begins {timelines[starts_with].dates[0]}) and its end by "
        f"{ends_with} (which ends {timelines[ends_with].dates[-1]}). A backtest cannot run longer than this."
    )
    if gaps:
        window_note += (
            f" It is NOT contiguous: {span_months - len(dates)} month(s) are absent because the blend "
            f"requires every contributor in a period and drops the period otherwise, so any one "
            f"contributor's gap is the blend's gap. Absent: "
            + "; ".join(gaps)
            + ". A backtest cannot run through these either, and a statistic bucketed by state will be "
            "short by exactly these months."
        )

    notes = [
        f"blended over {len(economy_weights)} economies for market scope {scope!r}: "
        + ", ".join(f"{code} {economy_weights[code]:.0%}" for code in sorted(economy_weights))
        + ". The blend is a weighted sum of per-economy distributions, per period.",
        window_note,
        "each contributing distribution is an annual macro assessment held flat within its year, blended "
        "with a monthly technical signal. All intra-year variation is technical.",
        # Which arithmetic produced these numbers. Not in the hashed payload — identity is about inputs and
        # model version — but recorded because on 2026-07-28 this contract was published, the virtualenv was
        # reinstalled to its pinned versions two hours later, and nothing was republished. Four days on, two
        # files existed with different content hashes and byte-identical metadata, and the only way to tell
        # why was a filesystem timestamp. See the master model's DECISIONS.md M41.
        f"computed under {_numerical_stack()}. The identifiers above are content hashes, so they move when "
        f"this stack moves even though the model version does not: the arithmetic changed, not the model.",
    ]
    phases = {timelines[code].current_phase for code in economy_weights}
    if len(phases) > 1:
        notes.append(
            f"the contributing economies are in different capital-cycle phases ({sorted(p for p in phases if p is not None)}), "
            f"so the blend has no single phase and none is reported. That disagreement is a finding about "
            f"the scope, not a defect."
        )

    provenance = {
        "scope": scope,
        "slot_weights": slot_weights,
        "economy_weights": {k: round(v, 12) for k, v in sorted(economy_weights.items())},
        "contributors": contributors,
        "blend": "weighted sum of per-economy distributions per period",
        "macro_frequency": "A",
        "macro_to_monthly": "step hold within each year, no interpolation",
        "sources": sorted(
            {
                source
                for code in economy_weights
                for source in timelines[code].provenance.get("sources", [])
            }
        ),
    }

    payload_for_hash = {
        "economy_scope": scope,
        "model_version": _model_version(),
        "contract_version": CONTRACT_VERSION,
        "period": "M",
        "state_grid": STATE_GRID,
        "dates": list(dates),
        "distributions": [[round(float(w), 12) for w in row] for row in blended],
        "provenance": _hashable(provenance),
    }
    digest = _hash_payload(payload_for_hash)

    _reading = describe_reading(blended[-1], DEFAULT_TAIL_BINS)
    return RegimeTimelineContract(
        regime_timeline_id=f"RTL-{digest[:16]}",
        regime_id=f"REG-{digest[:16]}",
        economy_scope=scope,
        model_version=_model_version(),
        contract_version=CONTRACT_VERSION,
        as_of=max(timelines[code].as_of for code in economy_weights),
        period="M",
        state_grid=STATE_GRID,
        dates=dates,
        distributions=blended,
        path_states=tuple(int(np.argmax(row)) for row in blended),
        current_state=_reading["state"],
        current_modal_state=_reading["modal_state"],
        current_mean_bin=_reading["mean_bin"],
        current_mode_margin=_reading["mode_margin"],
        current_bimodal=_reading["bimodal"],
        # A blend of economies in different phases has no single phase, and asserting one would claim an
        # agreement that does not exist.
        current_phase=(phases.pop() if len(phases) == 1 else None),
        current_saturation_pct=None,
        crisis_tail=float(blended[-1][:DEFAULT_TAIL_BINS].sum()),
        provenance=provenance,
        notes=tuple(notes),
    )


def write_timeline(contract: RegimeTimelineContract, directory: Path | str) -> Path:
    """Write the contract as canonical JSON, named by economy scope.

    Canonical form (sorted keys, compact separators) so that an unchanged Regime produces a
    byte-identical file and a consumer can diff two vintages meaningfully.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{contract.economy_scope}.json"
    payload = json.dumps(
        contract.to_dict(), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    target.write_text(payload, encoding="utf-8")
    return target


def load_timeline_payload(path: Path | str) -> dict[str, Any]:
    """Read a published timeline back, validating the parts a consumer relies on."""
    source = Path(path)
    if not source.exists():
        raise RegimeTimelineError(f"regime timeline not found: {source}")
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    required = {
        "regime_timeline_id", "economy_scope", "model_version", "as_of", "period", "state_grid",
        "path", "distributions", "current", "provenance",
    }
    missing = required - set(data)
    if missing:
        raise RegimeTimelineError(f"timeline {source} is missing field(s): {sorted(missing)}")
    if data["state_grid"] != STATE_GRID:
        raise RegimeTimelineError(
            f"timeline {source} declares state_grid={data['state_grid']}, expected {STATE_GRID}"
        )
    dates = [row["date"] for row in data["distributions"]]
    _validate_distributions([row["weights"] for row in data["distributions"]], dates)
    return data
