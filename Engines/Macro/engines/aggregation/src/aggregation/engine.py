"""The model. Pure: typed inputs in, typed outputs out; no network, no disk, no clock.

The combination rule is the first draft's (``Macro_Model``: ``model/saa_signal.py``,
``model/regime.py``, ``contracts/regime_timeline.py``), ported unchanged as calibration 1.0.0:

1. **The macro half (annual).** Per economy and year, the macro state (``macrofield``: the
   saturation axis against the balanced band, K_R/K_I, the change of the unsecured-asset ratio)
   and the cycle positions (``cycle``: superposition, alignment, the capital and innovation
   anchors) tilt five regime weights, crisis to boom, away from an even start. Each regime's
   weight is spread over the axis by its kernel.
2. **The market half (monthly).** The market risk signal as ``mrs`` publishes it, at zero shift.
3. **The cycle layer (annual).** ``cycle``'s own 25-bin layer.
4. **The blend**, linear in bin space, per month; the annual readings held flat across their
   year's months (a step, never an interpolation)::

       final = (1 - w_cycle) * [w_macro * MACRO + (1 - w_macro) * MARKET] + w_cycle * CYCLE

5. **Optimism** (1.1.0), on the combined distribution: moved by ``target - reference`` states,
   mass past either end piled onto the end state (decision AGG-05).
6. **Markets**: country-weighted blends of the economies' final distributions, published for a
   date only when every weighted economy is assessed on it.

A missing input is never read as a number: a month without a market reading or without a macro
reading is not assessed; a year without a cycle layer drops that term and records it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np

from .contracts import (
    N_STATES,
    REGIMES,
    Calibration,
    CurrentRegime,
    CycleEconomy,
    CycleState,
    EconomyCoverage,
    EconomyRegime,
    Kernels,
    MacroEconomy,
    MacroState,
    MacroTilts,
    MarketCoverage,
    MarketRegime,
    MarketRiskSignal,
    MRSEconomy,
    OptimismScale,
    Reading,
)

#: macrofield's phase vocabulary (``macrofield.contracts.PHASE_LABELS``).
PHASE_LABELS: dict[int, str] = {
    1: "Foundation",
    2: "Build-up",
    3: "Optimisation",
    4: "Saturation and reordering",
}


class EngineError(ValueError):
    """The inputs cannot produce a Regime. The message says which input and why."""


# ---------------------------------------------------------------------------
# Kernels: five regime weights to 25 states (draft regime.py)
# ---------------------------------------------------------------------------

def _normalised(values: Sequence[float]) -> np.ndarray:
    kernel = np.asarray(values, dtype=float)
    return kernel / kernel.sum()


def placed_kernels(kernels: Kernels) -> dict[str, np.ndarray]:
    """Regime -> its unit kernel on the 25 states. Crisis piled at the cautious end, boom its
    mirror at the aggressive end, the three interior regimes symmetric."""
    out: dict[str, np.ndarray] = {}
    for regime in REGIMES:
        if regime == "crisis":
            kernel = _normalised(kernels.crisis)
        elif regime == "boom":
            kernel = _normalised(tuple(reversed(kernels.crisis)))
        else:
            kernel = _normalised(kernels.symmetric)
        start = int(kernels.placement[regime])
        row = np.zeros(N_STATES)
        row[start - 1:start - 1 + kernel.size] = kernel
        out[regime] = row
    return out


def spread(weights: Mapping[str, float], placed: Mapping[str, np.ndarray]) -> np.ndarray:
    """``build_distribution`` of the draft with the single ``macro_state`` segment."""
    total = np.zeros(N_STATES)
    for regime in REGIMES:
        total += placed[regime] * float(weights[regime])
    return total / 1


# ---------------------------------------------------------------------------
# The macro half: tilts (draft saa_signal.regime_weights_from_state)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MacroReading:
    """What the tilts read for one economy and year (draft ``StateReading``)."""

    year: int
    saturation: float
    real_to_financial: float
    unsecured_change: Optional[float] = None
    interference: Optional[float] = None
    alignment: Optional[float] = None
    capital_years_overdue: Optional[float] = None
    innovation_years_to_trough: Optional[float] = None


def regime_weights(reading: MacroReading, tilts: MacroTilts
                   ) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Five regime weights and the per-tilt contributions (recorded before clamping).

    A literal port of ``regime_weights_from_state``, operation for operation, so that the
    floating point result is the draft's.
    """
    c = tilts.coefficients
    adjacent = tilts.adjacent_share
    lower, upper = tilts.band_lower, tilts.band_upper
    weights = {name: float(c["base"]) for name in REGIMES}
    contributions: dict[str, dict[str, float]] = {}

    def apply(label: str, cautious: float, aggressive: float) -> None:
        moved = {
            "crisis": cautious,
            "contraction": cautious * adjacent,
            "stagnation": 0.0,
            "expansion": aggressive * adjacent,
            "boom": aggressive,
        }
        if any(abs(v) > 0.0 for v in moved.values()):
            contributions[label] = moved
            for name, value in moved.items():
                weights[name] += value

    if reading.saturation > upper:
        apply("saturation_above_band",
              cautious=c["saturation_above_band"] * (reading.saturation - upper), aggressive=0.0)
    elif reading.saturation < lower:
        apply("saturation_below_band",
              cautious=0.0, aggressive=c["saturation_below_band"] * (lower - reading.saturation))

    if reading.real_to_financial < 1.0:
        apply("real_to_financial_below_one",
              cautious=c["real_to_financial_below_one"] * (1.0 - reading.real_to_financial),
              aggressive=0.0)

    if reading.unsecured_change is not None and math.isfinite(reading.unsecured_change):
        if reading.unsecured_change > 0.0:
            apply("unsecured_rising", c["unsecured_rising"] * reading.unsecured_change, 0.0)
        else:
            apply("unsecured_falling", 0.0, c["unsecured_rising"] * -reading.unsecured_change)

    if reading.interference is not None and math.isfinite(reading.interference):
        gain = 1.0
        if reading.alignment is not None and math.isfinite(reading.alignment):
            gain = 1.0 + c["alignment_gain"] * (float(reading.alignment) - 0.5)
        magnitude = c["interference"] * abs(float(reading.interference)) * max(gain, 0.0)
        if reading.interference < 0.0:
            apply("interference_negative", magnitude, 0.0)
        else:
            apply("interference_positive", 0.0, magnitude)

    if reading.capital_years_overdue is not None and reading.capital_years_overdue > 0.0:
        apply("capital_overdue",
              c["capital_overdue_per_decade"] * reading.capital_years_overdue / 10.0, 0.0)

    if reading.innovation_years_to_trough is not None:
        ahead = float(reading.innovation_years_to_trough)
        window = tilts.innovation_window_years
        if 0.0 <= ahead <= window:
            apply("innovation_approaching_trough",
                  c["innovation_approach_per_decade"] * (window - ahead) / 10.0, 0.0)

    clamped = {name: max(0.0, value) for name, value in weights.items()}
    total = sum(clamped.values())
    if total <= 0.0:
        raise EngineError(f"{reading.year}: every regime weight was driven to zero; the tilts are "
                          "too strong for this state (raise tilts.base or lower the tilts)")
    return {name: value / total for name, value in clamped.items()}, contributions


def macro_row(reading: MacroReading, tilts: MacroTilts, placed: Mapping[str, np.ndarray]
              ) -> tuple[np.ndarray, dict[str, float], dict[str, dict[str, float]]]:
    weights, contributions = regime_weights(reading, tilts)
    return spread(weights, placed), weights, contributions


# ---------------------------------------------------------------------------
# The blend (draft saa_signal.merge, one row)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Blended:
    distribution: np.ndarray
    weight_macro: float
    weight_market: float
    weight_cycle: float


def blend_row(macro: np.ndarray, market: np.ndarray, cycle: Optional[np.ndarray],
              w_macro: float, w_cycle: float) -> Blended:
    """``(1 - w_cycle) * [w_macro * macro + (1 - w_macro) * market] + w_cycle * cycle``,
    normalised, each part as the draft normalises it. ``cycle`` ``None`` drops that term."""
    combined = w_macro * macro + (1.0 - w_macro) * market
    use_cycle = cycle is not None and w_cycle > 0.0
    if use_cycle:
        cycle_total = cycle.sum()
        cycle_row = cycle / cycle_total if cycle_total > 0.0 else np.zeros_like(cycle)
        inner_total = combined.sum()
        inner = combined / inner_total if inner_total > 0.0 else np.zeros_like(combined)
        combined = (1.0 - w_cycle) * inner + w_cycle * cycle_row
    total = combined.sum()
    if not total > 0.0:
        raise EngineError("a blended row carries no mass")
    wc = w_cycle if use_cycle else 0.0
    return Blended(distribution=combined / total, weight_macro=(1.0 - wc) * w_macro,
                   weight_market=(1.0 - wc) * (1.0 - w_macro), weight_cycle=wc)


# ---------------------------------------------------------------------------
# Optimism: move the combined distribution along the axis (AGG-05)
# ---------------------------------------------------------------------------

def _translate(dist: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros(N_STATES)
    for i, mass in enumerate(dist):
        out[min(max(i + k, 0), N_STATES - 1)] += mass
    return out


def shift_distribution(dist: np.ndarray, shift: float, keep_tail: int = 0) -> np.ndarray:
    """Move ``dist`` by ``shift`` states towards the aggressive end (negative: cautious).

    Mass that runs past either end piles onto the end state, as the stress tail piles at the
    cautious end. A fractional shift is the linear mix of the two neighbouring whole shifts, so
    the mean moves by exactly ``shift`` away from the ends. Zero shift returns the input.

    ``keep_tail`` (AGG-15): the mass on the ``keep_tail`` most cautious states stays where it
    is and only the rest moves, so the crisis regime keeps its probability at every level.
    """
    d = np.asarray(dist, dtype=float)
    if shift == 0.0:
        return d
    tail = np.zeros(N_STATES)
    tail[:keep_tail] = d[:keep_tail]
    body = d - tail
    k = math.floor(shift)
    f = shift - k
    out = _translate(body, k)
    if f > 0.0:
        out = (1.0 - f) * out + f * _translate(body, k + 1)
    out = out + tail
    return out / out.sum()


# ---------------------------------------------------------------------------
# Reading a distribution (draft describe_reading and dispersion)
# ---------------------------------------------------------------------------

def prominent_modes(probability: np.ndarray, prominence: float) -> list[int]:
    """One-based bins of separate modes by topographic prominence (draft
    ``taa._prominent_modes``): the tallest peak, plus any whose height above its key saddle is
    at least ``prominence`` times the tallest."""
    values = np.asarray(probability, dtype=float)
    is_peak = np.zeros(values.size, dtype=bool)
    is_peak[1:-1] = (values[1:-1] >= values[:-2]) & (values[1:-1] >= values[2:])
    is_peak[0] = values[0] >= values[1]
    is_peak[-1] = values[-1] >= values[-2]
    candidates = [int(i) for i in np.flatnonzero(is_peak)]
    if not candidates:
        return [int(np.argmax(values)) + 1]
    tallest = int(max(candidates, key=lambda i: values[i]))
    floor = prominence * float(values[tallest])
    kept = [tallest]
    for index in candidates:
        if index == tallest:
            continue
        # A peak exactly as tall as the tallest is measured against the tallest (AGG-23: the
        # deferral target's two mirrored humps are equal to the last bit).
        higher_left = [j for j in range(index - 1, -1, -1) if values[j] > values[index] or j == tallest]
        higher_right = [j for j in range(index + 1, values.size) if values[j] > values[index] or j == tallest]
        if not higher_left and not higher_right:
            continue
        saddles = []
        if higher_left:
            saddles.append(float(values[higher_left[0]:index + 1].min()))
        if higher_right:
            saddles.append(float(values[index:higher_right[0] + 1].min()))
        if float(values[index]) - max(saddles) >= floor:
            kept.append(index)
    return sorted(i + 1 for i in kept)


def mean_state(dist: np.ndarray) -> int:
    """The bin nearest the probability-weighted mean (draft M57), 1-based."""
    mean = float((np.arange(1, N_STATES + 1) * dist).sum())
    return min(max(int(round(mean)), 1), N_STATES)


def modal_state(dist: np.ndarray) -> int:
    """1-based argmax; the first (most cautious) on a tie."""
    return int(np.argmax(dist)) + 1


def describe(dist: np.ndarray, reading: Reading, date: str) -> CurrentRegime:
    p = np.asarray(dist, dtype=float)
    bins = np.arange(1, N_STATES + 1)
    mean = float((bins * p).sum())
    modes = prominent_modes(p, reading.mode_prominence)
    ordered = sorted(modes, key=lambda b: -p[b - 1])
    margin = float(p[ordered[0] - 1] - p[ordered[1] - 1]) if len(ordered) > 1 else float(p.max())
    centre = (N_STATES + 1) / 2.0
    if len(modes) > 1:
        shape = "swing, participants disagree on direction"
    elif mean < centre - reading.lean_bins:
        shape = "risky, mass at the cautious end"
    elif mean > centre + reading.lean_bins:
        shape = "opportunistic, mass at the aggressive end"
    else:
        shape = "balanced"
    return CurrentRegime(
        date=date, state=mean_state(p), modal_state=modal_state(p), mean_bin=mean,
        modes=tuple(modes), mode_margin=margin, bimodal=len(modes) > 1,
        crisis_tail=float(p[:reading.tail_bins].sum()),
        five_regime={name: float(p[first - 1:last].sum())
                     for name, (first, last) in reading.five_regime_bins.items()},
        shape=shape,
    )


# ---------------------------------------------------------------------------
# Readings from the upstream artefacts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnnualMacro:
    """One economy's macro half and cycle layer, per year."""

    years: tuple[int, ...]
    rows: tuple[Optional[np.ndarray], ...]
    weights: tuple[Optional[dict[str, float]], ...]
    tilts: tuple[dict[str, dict[str, float]], ...]
    cycle_rows: tuple[Optional[np.ndarray], ...]
    phase: tuple[Optional[int], ...]
    saturation: tuple[Optional[float], ...]
    tilt_inputs_missing: dict[str, tuple[int, ...]]


def readings(macro: MacroEconomy, cycle: CycleEconomy, cycle_years: Sequence[int],
             tilts: MacroTilts) -> tuple[list[Optional[MacroReading]], dict[str, list[int]]]:
    """The tilt inputs per macro year. ``None`` where saturation or K_R/K_I is missing.

    The unsecured change is year on year; across a year macrofield dropped it is missing, not
    a two-year difference (the draft refused a gap outright). Interference and alignment are
    the cycle superposition of the same year; the capital overdue and innovation distance come
    from the anchors' reference years, as the draft read them.
    """
    assert macro.inputs is not None and macro.diagnostics is not None
    years = macro.years
    sat, rtf = macro.inputs.saturation, macro.diagnostics.real_to_financial
    unsecured = macro.diagnostics.unsecured_ratio
    by_year = {y: i for i, y in enumerate(cycle_years)}
    tracks = {t.cycle: t for t in cycle.cycles}
    capital = tracks.get(tilts.capital_cycle)
    innovation = tracks.get(tilts.innovation_cycle)
    capital_ref = capital.reference_year if capital is not None and capital.anchored else None
    innovation_ref = innovation.reference_year if innovation is not None else None

    missing: dict[str, list[int]] = {}
    out: list[Optional[MacroReading]] = []
    for i, year in enumerate(years):
        if sat[i] is None or rtf[i] is None:
            missing.setdefault("saturation_or_real_to_financial", []).append(year)
            out.append(None)
            continue
        change = None
        if i > 0 and years[i - 1] == year - 1 and unsecured[i] is not None and unsecured[i - 1] is not None:
            change = float(unsecured[i]) - float(unsecured[i - 1])
        elif i > 0:
            missing.setdefault("unsecured_rising", []).append(year)
        k = by_year.get(year)
        interference = None if k is None else cycle.superposition[k]
        alignment = None if k is None else cycle.alignment[k]
        if interference is None:
            missing.setdefault("interference", []).append(year)
        out.append(MacroReading(
            year=year, saturation=float(sat[i]), real_to_financial=float(rtf[i]),
            unsecured_change=change, interference=interference, alignment=alignment,
            capital_years_overdue=None if capital_ref is None else float(year) - float(capital_ref),
            innovation_years_to_trough=None if innovation_ref is None else float(innovation_ref) - float(year),
        ))
    return out, missing


def annual_macro(macro: MacroEconomy, cycle: CycleEconomy, cycle_years: Sequence[int],
                 cal: Calibration, placed: Mapping[str, np.ndarray]) -> AnnualMacro:
    reads, missing = readings(macro, cycle, cycle_years, cal.tilts)
    by_year = {y: i for i, y in enumerate(cycle_years)}
    rows: list[Optional[np.ndarray]] = []
    weights: list[Optional[dict[str, float]]] = []
    moves: list[dict[str, dict[str, float]]] = []
    cycle_rows: list[Optional[np.ndarray]] = []
    for reading, year in zip(reads, macro.years):
        k = by_year.get(year)
        layer = None if k is None else cycle.layer[k]
        cycle_rows.append(None if layer is None else np.asarray(layer, dtype=float))
        if reading is None:
            rows.append(None)
            weights.append(None)
            moves.append({})
            continue
        row, w, contributions = macro_row(reading, cal.tilts, placed)
        rows.append(row)
        weights.append(w)
        moves.append(contributions)
    assert macro.diagnostics is not None and macro.inputs is not None
    return AnnualMacro(
        years=tuple(macro.years), rows=tuple(rows), weights=tuple(weights), tilts=tuple(moves),
        cycle_rows=tuple(cycle_rows), phase=tuple(macro.diagnostics.phase),
        saturation=tuple(macro.inputs.saturation),
        tilt_inputs_missing={k: tuple(v) for k, v in missing.items()},
    )


def macro_year_for(date: str, years_with_reading: Sequence[int], carry_months: int
                   ) -> tuple[Optional[int], bool]:
    """The annual reading a month uses: its own year, or (past the last reading, within
    ``carry_months`` of that year's December) the last one, flagged carried. Interior gaps are
    never filled."""
    year, month = int(date[:4]), int(date[5:7])
    if year in years_with_reading:
        return year, False
    if carry_months > 0 and years_with_reading:
        last = max(years_with_reading)
        if year > last and (year - last - 1) * 12 + month <= carry_months:
            return last, True
    return None, False


# ---------------------------------------------------------------------------
# The whole model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelOutput:
    dates: tuple[str, ...]
    economies: tuple[EconomyRegime, ...]
    markets: tuple[MarketRegime, ...]
    economy_coverage: tuple[EconomyCoverage, ...]
    market_coverage: tuple[MarketCoverage, ...]
    economies_skipped: dict[str, str]
    warnings: tuple[str, ...] = field(default=())


def _tuple(row: Optional[np.ndarray]) -> Optional[tuple[float, ...]]:
    return None if row is None else tuple(float(v) for v in row)


def select_economies(mrs: MarketRiskSignal, cycle: CycleState, macro: MacroState,
                     requested: Optional[Sequence[str]]) -> tuple[list[str], dict[str, str]]:
    """Economies all three inputs carry, in the market risk signal's order."""
    in_mrs = [e.code for e in mrs.economies]
    in_cycle = {e.code for e in cycle.economies}
    macro_by = {e.code: e for e in macro.economies}
    skipped: dict[str, str] = {}
    if requested:
        universe = list(requested)
    else:
        universe = in_mrs + sorted((in_cycle | set(macro_by)) - set(in_mrs))
    chosen = []
    for code in universe:
        reasons = []
        if code not in in_mrs:
            reasons.append("not in the market risk signal")
        if code not in in_cycle:
            reasons.append("not in the cycle state")
        m = macro_by.get(code)
        if m is None:
            reasons.append("not in the macro state")
        elif m.status != "ok":
            reasons.append(f"macro state unavailable: {m.reason}")
        elif m.inputs is None or m.diagnostics is None:
            reasons.append("macro state carries no inputs or diagnostics")
        if reasons:
            skipped[code] = "; ".join(reasons)
        else:
            chosen.append(code)
    return chosen, skipped


def run_model(mrs: MarketRiskSignal, cycle: CycleState, macro: MacroState, cal: Calibration,
              optimism: OptimismScale, economies: Optional[Sequence[str]] = None) -> ModelOutput:
    if not mrs.dates:
        raise EngineError("the MarketRiskSignal carries no dates")
    dates = mrs.dates
    n = len(dates)
    placed = placed_kernels(cal.kernels)
    shift = cal.optimism.shift(optimism)
    chosen, skipped = select_economies(mrs, cycle, macro, economies)
    mrs_by = {e.code: e for e in mrs.economies}
    cycle_by = {e.code: e for e in cycle.economies}
    macro_by = {e.code: e for e in macro.economies}
    warnings: list[str] = []

    regimes: list[EconomyRegime] = []
    coverage: list[EconomyCoverage] = []
    finals: dict[str, list[Optional[np.ndarray]]] = {}
    for code in chosen:
        m, cy, market = macro_by[code], cycle_by[code], mrs_by[code]
        ceiling = cal.tilts.saturation_ceiling
        if ceiling is not None:
            breaches = [(y, s) for y, s in zip(m.years, m.inputs.saturation) if s is not None and s > ceiling]
            if breaches:
                skipped[code] = (f"refused: the saturation axis reaches {max(s for _, s in breaches):.3f} "
                                 f"in {breaches[0][0]}, above the ceiling {ceiling:g} "
                                 f"({len(breaches)} years); check credit and GDP before raising it")
                continue
        annual = annual_macro(m, cy, cycle.years, cal, placed)
        row_of = {y: i for i, y in enumerate(annual.years) if annual.rows[i] is not None}
        notes: list[str] = []
        band_disagree = [y for y, s, inside in zip(m.years, m.inputs.saturation, m.diagnostics.in_balanced_band)
                         if s is not None and (cal.tilts.band_lower <= s <= cal.tilts.band_upper) != inside]
        if band_disagree:
            warnings.append(f"{code}: the calibration's balanced band disagrees with macrofield's "
                            f"in_balanced_band in {len(band_disagree)} years (first {band_disagree[0]})")

        dist: list[Optional[tuple[float, ...]]] = []
        states: list[Optional[int]] = []
        modals: list[Optional[int]] = []
        used_year: list[Optional[int]] = []
        carried: list[bool] = []
        wm: list[Optional[float]] = []
        wk: list[Optional[float]] = []
        wc: list[Optional[float]] = []
        final_rows: list[Optional[np.ndarray]] = []
        no_market = no_macro = n_carried = 0
        cycle_reweighted: set[int] = set()
        for t, date in enumerate(dates):
            mkt = market.distribution[t]
            year, was_carried = macro_year_for(date, tuple(row_of), cal.carry_months)
            if mkt is None or year is None:
                no_market += mkt is None
                no_macro += mkt is not None and year is None
                for seq in (dist, states, modals, used_year, wm, wk, wc, final_rows):
                    seq.append(None)
                carried.append(False)
                continue
            i = row_of[year]
            cyc = annual.cycle_rows[i]
            if cyc is None and cal.blend.cycle > 0.0:
                if cal.blend.cycle_missing == "fail":
                    raise EngineError(f"{code}: no cycle layer in {year} and the calibration's "
                                      "cycle_missing policy is 'fail'")
                cycle_reweighted.add(year)
            b = blend_row(annual.rows[i], np.asarray(mkt, dtype=float), cyc, cal.blend.macro, cal.blend.cycle)
            final = shift_distribution(b.distribution, shift, cal.optimism.keep_tail)
            final_rows.append(final)
            dist.append(_tuple(final))
            states.append(mean_state(final))
            modals.append(modal_state(final))
            used_year.append(year)
            carried.append(was_carried)
            n_carried += was_carried
            wm.append(b.weight_macro)
            wk.append(b.weight_market)
            wc.append(b.weight_cycle)

        current = None
        last = next((k for k in range(n - 1, -1, -1) if final_rows[k] is not None), None)
        if last is not None:
            reading = describe(final_rows[last], cal.reading, dates[last])
            y = used_year[last]
            i = annual.years.index(y)
            phase = annual.phase[i]
            sat = annual.saturation[i]
            current = reading.model_copy(update={
                "phase": phase, "phase_label": PHASE_LABELS.get(phase),
                "saturation_pct": None if sat is None else float(sat) * 100.0,
                "macro_year": y, "macro_carried": carried[last]})
            if reading.crisis_tail < cal.reading.minimum_tail_probability:
                warnings.append(f"{code}: the crisis tail carries {reading.crisis_tail:.4f} on "
                                f"{dates[last]}, below the floor {cal.reading.minimum_tail_probability:.4f}; "
                                "not reweighted, review the reading")
        if n_carried:
            notes.append(f"{n_carried} months are assessed on the {max(row_of)} macro reading and "
                         f"cycle layer carried past their year (carry_months {cal.carry_months})")
        if cycle_reweighted:
            notes.append(f"no cycle layer in {sorted(cycle_reweighted)}: those months blend the "
                         "macro and market halves only")

        finals[code] = final_rows
        regimes.append(EconomyRegime(
            code=code, name=market.name, distribution=tuple(dist), state=tuple(states),
            modal_state=tuple(modals), macro_year=tuple(used_year), carried=tuple(carried),
            weight_macro=tuple(wm), weight_market=tuple(wk), weight_cycle=tuple(wc),
            years=annual.years, macro_layer=tuple(_tuple(r) for r in annual.rows),
            cycle_layer=tuple(_tuple(r) for r in annual.cycle_rows),
            macro_weights=annual.weights, tilts=annual.tilts,
            market=market.distribution, current=current, notes=tuple(notes)))
        coverage.append(EconomyCoverage(
            code=code, dates_assessed=sum(r is not None for r in final_rows),
            dates_without_market=no_market, dates_without_macro=no_macro,
            dates_macro_carried=n_carried, years_cycle_reweighted=tuple(sorted(cycle_reweighted)),
            tilt_inputs_missing=annual.tilt_inputs_missing))

    markets: list[MarketRegime] = []
    market_cov: list[MarketCoverage] = []
    for mcode, weights in cal.markets.items():
        absent = tuple(c for c in weights if c not in finals)
        mdist: list[Optional[tuple[float, ...]]] = []
        mstate: list[Optional[int]] = []
        mmodal: list[Optional[int]] = []
        rows: list[Optional[np.ndarray]] = []
        for t in range(n):
            if absent or any(finals[c][t] is None for c in weights):
                rows.append(None)
                mdist.append(None)
                mstate.append(None)
                mmodal.append(None)
                continue
            acc = np.zeros(N_STATES)
            for c, w in weights.items():
                acc += w * finals[c][t]
            row = acc / acc.sum()
            rows.append(row)
            mdist.append(_tuple(row))
            mstate.append(mean_state(row))
            mmodal.append(modal_state(row))
        last = next((k for k in range(n - 1, -1, -1) if rows[k] is not None), None)
        markets.append(MarketRegime(
            code=mcode, weights=dict(weights), distribution=tuple(mdist), state=tuple(mstate),
            modal_state=tuple(mmodal),
            current=None if last is None else describe(rows[last], cal.reading, dates[last])))
        assessed = sum(r is not None for r in rows)
        market_cov.append(MarketCoverage(code=mcode, economies_absent=absent,
                                         dates_assessed=assessed, dates_unassessed=n - assessed))

    return ModelOutput(dates=dates, economies=tuple(regimes), markets=tuple(markets),
                       economy_coverage=tuple(coverage), market_coverage=tuple(market_cov),
                       economies_skipped=skipped, warnings=tuple(warnings))
