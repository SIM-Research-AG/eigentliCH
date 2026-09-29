"""The datafeed's rules: pure functions, no I/O, no HTTP, no clock.

Three jobs:

1. **Assemble a panel** from stored cells onto a monthly axis. Assembly never invents a
   value: a cell with nothing stored is missing, and says so.
2. **Fit a public-source candidate** against the primary series on the years both cover,
   and accept it only if the fit holds. Levels are fitted by a scale (units, magnitude and
   stable currency differences all show up as a constant ratio), rates by an offset
   (a definitional bias shows up as a constant difference). A candidate that does not fit
   is rejected and the gap stays a gap.
3. **Apply an accepted fill** to missing cells only: the annual value goes to December,
   and is carried into the following months at most ``annual_carry_months``, flagged
   ``carried``. A primary value is never overwritten.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence

from .contracts import (
    CoverageRow,
    Panel,
    PanelSeries,
    PlausibilityFinding,
    SnapshotIn,
    SourceSpan,
    month_index,
)

Cell = tuple[float, str, str]          # value, flag, source


# ---------------------------------------------------------------------------
# Date axis
# ---------------------------------------------------------------------------

def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def axis(first: str, last: str) -> tuple[str, ...]:
    """Every month end from ``first`` to ``last`` inclusive."""
    out = []
    for k in range(month_index(first), month_index(last) + 1):
        out.append(month_end(k // 12, k % 12 + 1))
    return tuple(out)


def normalise_date(d: str) -> str:
    """Any day in a month -> that month's end."""
    return month_end(int(d[:4]), int(d[5:7]))


# ---------------------------------------------------------------------------
# Panel assembly
# ---------------------------------------------------------------------------

def spans(dates: Sequence[str], sources: Sequence[Optional[str]]) -> tuple[SourceSpan, ...]:
    """Runs of consecutive present cells sharing one source."""
    out: list[SourceSpan] = []
    start = None
    for i, src in enumerate(list(sources) + [None]):
        if start is not None and (src is None or src != sources[start]):
            out.append(SourceSpan(source=sources[start], first=dates[start], last=dates[i - 1]))
            start = None
        if src is not None and start is None:
            start = i
    return tuple(out)


def assemble(
    *,
    snapshot_id: str,
    as_of: str,
    primary_source: str,
    dates: Sequence[str],
    units: Mapping[tuple[str, str], str],
    cells: Mapping[tuple[str, str], Mapping[str, Cell]],
    keys: Iterable[tuple[str, str]],
) -> Panel:
    """Lay stored cells onto the axis. ``keys`` are the (country, series) pairs wanted."""
    series = []
    for country, series_id in keys:
        stored = cells.get((country, series_id), {})
        values, flags, sources = [], [], []
        for d in dates:
            cell = stored.get(d)
            if cell is None:
                values.append(None); flags.append("missing"); sources.append(None)
            else:
                values.append(cell[0]); flags.append(cell[1]); sources.append(cell[2])
        series.append(PanelSeries(country=country, series_id=series_id,
                                  unit=units.get((country, series_id), ""),
                                  values=tuple(values), flags=tuple(flags),
                                  source_spans=spans(dates, sources)))
    return Panel(snapshot_id=snapshot_id, as_of=as_of, primary_source=primary_source,
                 dates=tuple(dates), series=tuple(series))


def panel_of(snapshot: SnapshotIn) -> Panel:
    """The full panel a snapshot describes: what its checksum is taken over."""
    cells = {(s.definition.country, s.definition.series_id): {c.date: (c.value, c.flag, c.source) for c in s.cells}
             for s in snapshot.series}
    units = {(s.definition.country, s.definition.series_id): s.definition.unit for s in snapshot.series}
    return assemble(snapshot_id=snapshot.snapshot_id, as_of=snapshot.as_of,
                    primary_source=snapshot.primary_source, dates=axis(snapshot.first_date, snapshot.last_date),
                    units=units, cells=cells, keys=sorted(cells))


def checksum(panel: Panel) -> str:
    """sha256 of the panel's canonical JSON."""
    blob = json.dumps(panel.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Fitting public-source candidates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fit:
    accepted: bool
    reason: str
    overlap: int
    scale: Optional[float] = None
    offset: Optional[float] = None
    deviation: Optional[float] = None


def december_values(dates: Sequence[str], stored: Mapping[str, Cell]) -> dict[int, float]:
    """The year-end value of each calendar year that has one."""
    return {int(d[:4]): stored[d][0] for d in dates if d[5:7] == "12" and d in stored}


def fit_level(primary: Mapping[int, float], candidate: Mapping[int, float],
              min_overlap: int, tolerance: float) -> Fit:
    """Scale fit: k = median(primary / candidate). Accept if every overlap ratio lies
    within ``tolerance`` (relative) of k."""
    years = sorted(y for y in primary if y in candidate and candidate[y] not in (0, None)
                   and primary[y] != 0)
    if len(years) < min_overlap:
        return Fit(False, f"{len(years)} overlapping years, {min_overlap} needed", len(years))
    ratios = [primary[y] / candidate[y] for y in years]
    k = median(ratios)
    if k <= 0:
        return Fit(False, "the series move in opposite signs", len(years), scale=k)
    deviation = max(abs(r / k - 1.0) for r in ratios)
    if deviation > tolerance:
        return Fit(False, f"overlap deviates {deviation:.1%} from the fitted scale "
                          f"(tolerance {tolerance:.1%})", len(years), scale=k, deviation=deviation)
    return Fit(True, "fits", len(years), scale=k, deviation=deviation)


def fit_rate(primary: Mapping[int, float], candidate: Mapping[int, float],
             min_overlap: int, tolerance: float) -> Fit:
    """Offset fit: b = median(primary - candidate). Accept if every residual lies within
    ``tolerance`` (absolute) of b. ``candidate`` is already in the primary's unit."""
    years = sorted(y for y in primary if y in candidate)
    if len(years) < min_overlap:
        return Fit(False, f"{len(years)} overlapping years, {min_overlap} needed", len(years))
    diffs = [primary[y] - candidate[y] for y in years]
    b = median(diffs)
    deviation = max(abs(d - b) for d in diffs)
    if deviation > tolerance:
        return Fit(False, f"residual {deviation:.4f} after the fitted offset exceeds "
                          f"{tolerance:.4f}", len(years), offset=b, deviation=deviation)
    return Fit(True, "fits", len(years), offset=b, deviation=deviation)


# ---------------------------------------------------------------------------
# Applying a fill
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Applied:
    cells: dict[str, Cell]
    years: tuple[int, ...]
    observed: int
    carried: int


def apply_annual(dates: Sequence[str], stored: Mapping[str, Cell], annual: Mapping[int, float],
                 source: str, carry_months: int) -> Applied:
    """Place annual values into the missing December cells, then carry each into the next
    ``carry_months`` months while those are missing. Primary cells are never touched."""
    on_axis = {d: i for i, d in enumerate(dates)}
    out = dict(stored)
    years, observed, carried = [], 0, 0
    for year in sorted(annual):
        december = month_end(year, 12)
        if december not in on_axis or december in out:
            continue
        out[december] = (float(annual[year]), "observed", source)
        years.append(year)
        observed += 1
        i = on_axis[december]
        for step in range(1, carry_months + 1):
            if i + step >= len(dates) or dates[i + step] in out:
                break
            out[dates[i + step]] = (float(annual[year]), "carried", source)
            carried += 1
    return Applied(cells=out, years=tuple(years), observed=observed, carried=carried)


# ---------------------------------------------------------------------------
# Coverage and plausibility
# ---------------------------------------------------------------------------

def cell_sources(panel: Panel, s: PanelSeries) -> list[Optional[str]]:
    """The source of every cell of ``s`` (None where missing)."""
    first = month_index(panel.dates[0])
    out: list[Optional[str]] = [None] * len(panel.dates)
    for sp in s.source_spans:
        for i in range(month_index(sp.first) - first, month_index(sp.last) - first + 1):
            if s.values[i] is not None:
                out[i] = sp.source
    return out


def coverage(panel: Panel) -> tuple[CoverageRow, ...]:
    rows = []
    for s in panel.series:
        public = sum(1 for src in cell_sources(panel, s)
                     if src is not None and src != panel.primary_source)
        rows.append(CoverageRow(
            country=s.country, series_id=s.series_id, months=len(s.values),
            observed=sum(f == "observed" for f in s.flags),
            carried=sum(f == "carried" for f in s.flags),
            missing=sum(f == "missing" for f in s.flags),
            from_public_sources=public,
        ))
    return tuple(rows)


def consumption_share_check(panel: Panel, bounds: tuple[float, float]) -> tuple[PlausibilityFinding, ...]:
    """Household consumption over nominal GDP should be a share of GDP. Reported, not fixed:
    a failure means the two series are not in the same unit."""
    lookup = {(s.country, s.series_id): s.values for s in panel.series}
    out = []
    for country in sorted({s.country for s in panel.series}):
        c = lookup.get((country, "consumer.household_consumption"))
        g = lookup.get((country, "production.gdp_nominal"))
        if not c or not g:
            continue
        shares = [a / b for a, b, d in zip(c, g, panel.dates)
                  if a is not None and b not in (None, 0) and d[5:7] == "12"]
        if not shares:
            continue
        lo, hi = min(shares), max(shares)
        if lo < bounds[0] or hi > bounds[1]:
            out.append(PlausibilityFinding(
                country=country, check="consumption_share",
                detail=f"household consumption / GDP spans {lo:.3g} to {hi:.3g}, outside "
                       f"{bounds[0]}-{bounds[1]}: the two series are not in the same unit"))
    return tuple(out)
