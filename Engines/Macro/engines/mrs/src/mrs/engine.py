"""The model. Pure: typed inputs in, typed outputs out; no network, no disk, no clock.

Port of ``Market_Signal.m`` and ``Weights.m`` (MATLAB Master Controller). The indicator
layer (eleven sub-indicators, four segment signals) is in :mod:`mrs.indicators`; this module
turns the segment signals into the 25-state distribution and assembles the output.

Per economy and month:

1. Each segment reading is binned on its grid, ``linspace(-2, 2, 11)`` at zero optimism
   shift. The bin is the kernel column, 1 .. 11.
2. The column's kernel (25 states) is weighted by the segment weight.
3. The four weighted kernels are summed. That sum is MATLAB's ``CRS`` row; its total is
   kept as ``raw_mass``, and the published distribution is the sum normalised to 1.
4. The modal state is the reported state; ties go to the more cautious state.

A missing reading follows the calibration's missing policy and is never silently read as a
number (decision MRS-04). ``mrs`` publishes at zero shift (MRS-13, MRS-18); ``shifts`` exists
only so the golden test can reproduce a MATLAB export made at a non-zero optimism level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import numpy as np

from . import indicators as ind
from .contracts import (
    INDICATORS,
    N_STATES,
    SEGMENTS,
    BandKernel,
    Calibration,
    CoverageReport,
    EconomyCoverage,
    EconomySignal,
    SegmentSpec,
    TailKernel,
)


class EngineError(ValueError):
    """The inputs cannot produce a MarketRiskSignal. The message says which input and why."""


# ---------------------------------------------------------------------------
# Kernels and grid
# ---------------------------------------------------------------------------

def binomial_pmf(n: int, p: float) -> np.ndarray:
    """``binopdf(0:n, n, p)``."""
    return np.array([math.comb(n, k) * p ** k * (1.0 - p) ** (n - k) for k in range(n + 1)])


def _place(kernel: np.ndarray, first_state: int) -> np.ndarray:
    """``kernel`` on states ``first_state`` onwards, overhang folded onto the end states."""
    out = np.zeros(N_STATES)
    for k, mass in enumerate(kernel):
        state = min(max(first_state + k, 1), N_STATES)
        out[state - 1] += mass
    return out


def kernel_matrix(spec: SegmentSpec, columns: int) -> np.ndarray:
    """States by columns (25 x ``columns``), unweighted. Column ``j`` is ``[:, j-1]``."""
    k = spec.kernel
    base = binomial_pmf(k.binomial_n, k.binomial_p)
    out = np.zeros((N_STATES, columns))
    for j in range(1, columns + 1):
        if isinstance(k, BandKernel):
            out[:, j - 1] = _place(base, k.first_state + k.step * (j - 1))
        elif isinstance(k, TailKernel):
            if j >= k.active_from_column:
                level = float(j - k.active_from_column + 1)
                out[:, j - 1] = _place(base, k.first_state) * (level ** k.intensity_exponent
                                                               / k.intensity_divisor)
        else:  # pragma: no cover - the contract's discriminator admits nothing else
            raise EngineError(f"unknown kernel kind {k!r}")
    return out


def grid(cal: Calibration, shift: float = 0.0) -> np.ndarray:
    """The bin edges, ``shift + linspace(low, high, count)`` (``Weights.m``)."""
    return shift + np.linspace(cal.edges.low, cal.edges.high, cal.edges.count)


def column_for(value: float, edges: np.ndarray) -> int:
    """Kernel column (1-based) for a reading.

    Below ``edges[1]`` is column 1, at or above ``edges[-1]`` is the last column, and
    ``[edges[k], edges[k+1])`` is column ``k+1`` (0-based ``k``). Identical to MATLAB for
    every reading not exactly on an interior edge (decision MRS-01).
    """
    return 1 + int(np.count_nonzero(edges[1:] <= value))


# ---------------------------------------------------------------------------
# One economy: segments to distribution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Assessment:
    state: tuple[Optional[int], ...]
    distribution: tuple[Optional[tuple[float, ...]], ...]
    raw_mass: tuple[Optional[float], ...]
    columns: dict[str, tuple[Optional[int], ...]]
    segment_gaps: dict[str, int]
    dates_unassessed: int


def modal_state(dist: np.ndarray) -> int:
    """1-based index of the largest probability; the first (most cautious) on a tie."""
    return int(np.argmax(dist)) + 1


def assess(signals: Mapping[str, Sequence[Optional[float]]], n_dates: int, cal: Calibration,
           shifts: Optional[Mapping[str, float]] = None, where: str = "") -> Assessment:
    """The distribution path of one economy from its four segment signals.

    ``shifts`` (segment -> grid shift) is for reconciliation with MATLAB exports made at a
    non-zero optimism level only; every published run uses zero.
    """
    specs = [cal.segment(s) for s in SEGMENTS]
    matrices = {s.name: kernel_matrix(s, cal.edges.count) * s.weight for s in specs}
    grids = {s.name: grid(cal, (shifts or {}).get(s.name, 0.0)) for s in specs}
    total_weight = math.fsum(s.weight for s in specs)

    columns: dict[str, list[Optional[int]]] = {s.name: [] for s in specs}
    gaps = {s.name: 0 for s in specs}
    states: list[Optional[int]] = []
    dists: list[Optional[tuple[float, ...]]] = []
    masses: list[Optional[float]] = []
    unassessed = 0

    for t in range(n_dates):
        present: list[tuple[SegmentSpec, int]] = []
        for s in specs:
            series = signals.get(s.name)
            value = None if series is None else series[t]
            if value is not None and not math.isfinite(value):
                value = None
            if value is None:
                gaps[s.name] += 1
                if cal.missing_policy == "fail":
                    raise EngineError(f"{where}{s.name} has no reading at date index {t} and the "
                                      f"calibration's missing policy is 'fail'")
                if cal.missing_policy == "matlab":
                    present.append((s, 1))
                    columns[s.name].append(1)
                    continue
                columns[s.name].append(None)
                continue
            col = column_for(value, grids[s.name])
            present.append((s, col))
            columns[s.name].append(col)

        raw = None
        if len(present) >= cal.min_segments:
            scale = total_weight / math.fsum(s.weight for s, _ in present)
            raw = sum(matrices[s.name][:, col - 1] for s, col in present) * scale
            if not raw.sum() > 0.0:
                raw = None
        if raw is None:
            unassessed += 1
            states.append(None)
            dists.append(None)
            masses.append(None)
            continue
        mass = float(raw.sum())
        dist = raw / mass
        states.append(modal_state(dist))
        dists.append(tuple(float(p) for p in dist))
        masses.append(mass)

    return Assessment(state=tuple(states), distribution=tuple(dists), raw_mass=tuple(masses),
                      columns={k: tuple(v) for k, v in columns.items()},
                      segment_gaps=gaps, dates_unassessed=unassessed)


# ---------------------------------------------------------------------------
# The whole model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EconomyInput:
    """One economy's input: series id -> values over the months (``NaN`` where missing)."""

    code: str
    name: str
    series: Mapping[str, np.ndarray]


@dataclass(frozen=True)
class ModelOutput:
    economies: tuple[EconomySignal, ...]
    coverage: CoverageReport


def _wire(x: np.ndarray) -> tuple[Optional[float], ...]:
    """NaN (and inf) to ``None``; everything else a plain float."""
    return tuple(float(v) if math.isfinite(v) else None for v in x)


def run_model(dates: Sequence[str], economies: Sequence[EconomyInput],
              cal: Calibration) -> ModelOutput:
    """Indicators, segments and distribution for every economy, at zero optimism shift."""
    n = len(dates)
    if n == 0:
        raise EngineError("the input has no dates")
    if not economies:
        raise EngineError("the input has no economies")
    out: list[EconomySignal] = []
    cover: list[EconomyCoverage] = []
    for e in economies:
        try:
            layer = ind.compute(e.series, cal.indicators, n)
        except ind.IndicatorError as exc:
            raise EngineError(f"{e.code}: {exc}") from exc
        segments = {s: _wire(layer.segments[s]) for s in SEGMENTS}
        a = assess(segments, n, cal, where=f"{e.code}: ")
        assessed = [i for i, s in enumerate(a.state) if s is not None]
        out.append(EconomySignal(
            code=e.code, name=e.name,
            indicators={k: _wire(layer.indicators[k]) for k in INDICATORS},
            segments=segments, distribution=a.distribution, raw_mass=a.raw_mass,
            state=a.state))
        cover.append(EconomyCoverage(
            code=e.code, dates_assessed=n - a.dates_unassessed,
            dates_unassessed=a.dates_unassessed,
            first_assessed=dates[assessed[0]] if assessed else None,
            last_assessed=dates[assessed[-1]] if assessed else None,
            segment_gaps=a.segment_gaps,
            indicator_gaps={k: int(np.count_nonzero(~np.isfinite(layer.indicators[k])))
                            for k in INDICATORS},
            inputs_missing=layer.inputs_missing))
    coverage = CoverageReport(
        economies=tuple(cover), indicator_mode=cal.indicators.mode,
        missing_policy=cal.missing_policy, min_segments=cal.min_segments,
        inputs=ind.series_needed(cal.indicators))
    return ModelOutput(economies=tuple(out), coverage=coverage)
