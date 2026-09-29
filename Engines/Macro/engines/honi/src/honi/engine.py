"""The HoNI model: pure functions, no I/O, no HTTP, no clock.

A direct port of ``HoNI2.m`` and ``Functions/HoNI/*.m`` (Master_Controller, Version 2.0),
following the HoNI Build Manual sections 3.4 to 6. Everything a figure depends on arrives
as an argument, so the same inputs give the same output, bit for bit.

Pipeline::

    Panel (monthly)  ->  annualise  ->  15 indicators + capital saturation   (section 4)
                     ->  ramp / tent scores, 1 to 5                          (section 5)
                     ->  3 sector means  ->  rescale per year                (section 6.1, 6.2)
                     ->  weighted national score  ->  rescale per year       (section 6.3)

Where the port departs from MATLAB, it does so on purpose and the reason is in
``DECISIONS.md``. In short:

* Series are addressed by name, never by row position in a ticker sheet.
* Missing is NaN from end to end. Zero is a number (defects 9.1, 9.2).
* The first growth rate of a series is missing, not zero (D-12).
* Annual values are the December observation (or the calendar-year mean), not "every
  12th month counted from whenever the loader ran" (defect 9.6, D-11).
* No country is special-cased; data patches belong in the feed (defect 9.5).

Arrays are always **years by countries**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

import numpy as np

from .contracts import (
    INDICES,
    SECTORS,
    Calibration,
    CoverageReport,
    DroppedSector,
    Exclusion,
    HoNIScores,
    HoNITrends,
    IndexSpec,
    MissingSeries,
    Panel,
    PeerStatsRow,
    PublicFill,
    TrendSeries,
    UpstreamCoverage,
    Window,
)

#: Score scale. Fixed by the published methodology.
SCORE_MIN = 1.0
SCORE_MAX = 5.0

#: The twenty-one series HoNI reads, by name. The comment is the MATLAB sheet and column
#: the series used to occupy (manual section 3.3), kept only to make the port reviewable.
REQUIRED_SERIES: tuple[str, ...] = (
    "consumer.corruption_freedom",        # Consumer 1
    "consumer.gdp_per_capita",            # Consumer 2
    "consumer.population",                # Consumer 3
    "consumer.wage_growth",               # Consumer 5
    "consumer.household_consumption",     # Consumer 7
    "consumer.labour_force_participation",  # Consumer 8
    "debt.corporate_gdp",                 # Debt 1
    "debt.external",                      # Debt 2
    "debt.government_gdp",                # Debt 3
    "debt.household_gdp",                 # Debt 4
    "debt.financial_sector",              # Debt 5
    "equity.market_cap_gdp",              # Equity 2
    "fx.trade_balance",                   # FX 1
    "fx.terms_of_trade",                  # FX 2
    "fx.reserves",                        # FX 3
    "inflation.cpi_yoy",                  # Inflation 1
    "money.budget_balance_gdp",           # Money 1
    "money.broad_money",                  # Money 2
    "production.gdp_nominal",             # Production 1
    "production.imports",                 # Production 2
    "yields.govt_10y",                    # Yields 1
)


class EngineError(ValueError):
    """The inputs cannot produce a publishable result. The message says why."""


# ---------------------------------------------------------------------------
# Annualisation (manual section 3.4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnnualPanel:
    """Annual values, one years-by-countries array per series."""

    years: tuple[int, ...]
    countries: tuple[str, ...]
    data: Mapping[str, np.ndarray]


def annualise(panel: Panel, countries: Sequence[str], method: str) -> AnnualPanel:
    """Reduce the monthly panel to calendar years.

    ``year_end`` takes the December cell. ``mean`` takes the mean of the twelve months and
    is missing if any month is. Only calendar years whose December lies on the panel's
    date axis are produced, so a partial final year never appears.
    """
    months = [(int(d[:4]), int(d[5:7])) for d in panel.dates]

    def complete(year: int) -> bool:
        return method == "year_end" or (year, 1) >= months[0]

    years = tuple(y for y, m in months if m == 12 and complete(y))
    if not years:
        raise EngineError("the panel covers no complete calendar year")

    lookup = {(s.country, s.series_id): s.values for s in panel.series}
    n_months = len(months)
    data: dict[str, np.ndarray] = {}
    for series_id in REQUIRED_SERIES:
        monthly = np.full((n_months, len(countries)), np.nan)
        for j, country in enumerate(countries):
            values = lookup.get((country, series_id))
            if values is not None:
                monthly[:, j] = [np.nan if v is None else v for v in values]
        annual = np.full((len(years), len(countries)), np.nan)
        for i, year in enumerate(years):
            december = months.index((year, 12))
            if method == "year_end":
                annual[i] = monthly[december]
            else:
                block = monthly[december - 11: december + 1]
                annual[i] = np.where(np.isnan(block).any(axis=0), np.nan, block.mean(axis=0))
        data[series_id] = annual
    return AnnualPanel(years=years, countries=tuple(countries), data=data)


# ---------------------------------------------------------------------------
# Numerical helpers
# ---------------------------------------------------------------------------

def _finite(x: np.ndarray) -> np.ndarray:
    out = np.array(x, dtype=float, copy=True)
    out[~np.isfinite(out)] = np.nan
    return out


def ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a / b, with a non-finite result (division by zero) reported as missing."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return _finite(a / b)


def growth(x: np.ndarray) -> np.ndarray:
    """Year-on-year growth along the year axis. The first year has no predecessor."""
    out = np.full_like(x, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = (x[1:] - x[:-1]) / x[:-1]
    return _finite(out)


def trailing_mean(x: np.ndarray, window: int, min_obs: int) -> np.ndarray:
    """Mean over the current and ``window - 1`` prior years, ignoring missing years.

    The window shrinks at the start of the series, as MATLAB ``movmean(x, [4 0])`` does.
    A cell is missing when fewer than ``min_obs`` years in its window are present.
    """
    out = np.full_like(x, np.nan, dtype=float)
    for t in range(x.shape[0]):
        block = x[max(0, t - window + 1): t + 1]
        present = np.isfinite(block)
        count = present.sum(axis=0)
        total = np.where(present, block, 0.0).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[t] = np.where(count >= min_obs, total / count, np.nan)
    return out


# ---------------------------------------------------------------------------
# Indicators (manual section 4)
# ---------------------------------------------------------------------------

Indicator = Callable[[Mapping[str, np.ndarray], Callable[[np.ndarray], np.ndarray]], np.ndarray]


@dataclass(frozen=True)
class IndicatorDef:
    name: str
    definition: str
    inputs: tuple[str, ...]
    compute: Indicator


def _def(name: str, definition: str, inputs: tuple[str, ...], compute: Indicator) -> IndicatorDef:
    return IndicatorDef(name, definition, inputs, compute)


#: One entry per index. ``m`` is the trailing mean, already bound to the calibration.
INDICATORS: tuple[IndicatorDef, ...] = (
    _def("budget_balance", "Budget balance, % GDP",
         ("money.budget_balance_gdp",),
         lambda s, m: s["money.budget_balance_gdp"].copy()),
    _def("monetary_supply", "Trailing mean of (broad money growth - nominal GDP growth)",
         ("money.broad_money", "production.gdp_nominal"),
         lambda s, m: m(growth(s["money.broad_money"]) - growth(s["production.gdp_nominal"]))),
    _def("government_debt", "Government debt, % GDP",
         ("debt.government_gdp",),
         lambda s, m: s["debt.government_gdp"].copy()),
    _def("real_rate_10y", "Trailing mean of (10y government yield - CPI YoY)",
         ("yields.govt_10y", "inflation.cpi_yoy"),
         lambda s, m: m(s["yields.govt_10y"] - s["inflation.cpi_yoy"])),
    _def("market_cap", "Equity market capitalisation, % GDP",
         ("equity.market_cap_gdp",),
         lambda s, m: s["equity.market_cap_gdp"].copy()),
    _def("external_debt_affordability", "Trailing mean of (trade balance / external debt)",
         ("fx.trade_balance", "debt.external"),
         lambda s, m: m(ratio(s["fx.trade_balance"], s["debt.external"]))),
    _def("external_debt_exposure", "External debt / nominal GDP",
         ("debt.external", "production.gdp_nominal"),
         lambda s, m: ratio(s["debt.external"], s["production.gdp_nominal"])),
    _def("terms_of_trade", "Trailing mean of the terms of trade (commodities)",
         ("fx.terms_of_trade",),
         lambda s, m: m(s["fx.terms_of_trade"])),
    _def("import_reserves", "International reserves / imports",
         ("fx.reserves", "production.imports"),
         lambda s, m: ratio(s["fx.reserves"], s["production.imports"])),
    _def("corruption_freedom", "Freedom from corruption score",
         ("consumer.corruption_freedom",),
         lambda s, m: s["consumer.corruption_freedom"].copy()),
    _def("consumption_power", "Wage growth - CPI YoY",
         ("consumer.wage_growth", "inflation.cpi_yoy"),
         lambda s, m: s["consumer.wage_growth"] - s["inflation.cpi_yoy"]),
    _def("population_growth", "Population growth, YoY",
         ("consumer.population",),
         lambda s, m: growth(s["consumer.population"])),
    _def("gdp_per_capita_growth", "Trailing mean of (GDP per capita growth - CPI YoY)",
         ("consumer.gdp_per_capita", "inflation.cpi_yoy"),
         lambda s, m: m(growth(s["consumer.gdp_per_capita"]) - s["inflation.cpi_yoy"])),
    _def("consumption_dependency", "Household consumption / nominal GDP",
         ("consumer.household_consumption", "production.gdp_nominal"),
         lambda s, m: ratio(s["consumer.household_consumption"], s["production.gdp_nominal"])),
    _def("labour_force", "Labour force participation rate",
         ("consumer.labour_force_participation",),
         lambda s, m: s["consumer.labour_force_participation"].copy()),
)

assert tuple(d.name for d in INDICATORS) == tuple(INDICES), "indicator registry out of order"

CAPITAL_SATURATION_INPUTS = (
    "debt.corporate_gdp", "debt.government_gdp", "debt.household_gdp",
    "debt.financial_sector", "production.gdp_nominal",
)


def capital_saturation(s: Mapping[str, np.ndarray]) -> np.ndarray:
    """Corporate + government + household debt (% GDP) + financial-sector debt / GDP.

    The x-axis of the primary chart. Not part of the score (manual section 4.1).
    """
    return _finite(
        s["debt.corporate_gdp"] + s["debt.government_gdp"] + s["debt.household_gdp"]
        + ratio(s["debt.financial_sector"], s["production.gdp_nominal"])
    )


def compute_indicators(
    annual: Mapping[str, np.ndarray], window: int, min_obs: int
) -> dict[str, np.ndarray]:
    """The fifteen raw indicators, each years by countries."""
    def mean(x: np.ndarray) -> np.ndarray:
        return trailing_mean(x, window, min_obs)

    return {d.name: _finite(d.compute(annual, mean)) for d in INDICATORS}


# ---------------------------------------------------------------------------
# Transfer functions (manual section 5)
# ---------------------------------------------------------------------------

def ramp(x: np.ndarray, rng: Sequence[float]) -> np.ndarray:
    """MATLAB ``sigmycalc``: two linear segments, 1 at min, 2.5 at mid, 5 at max.

    A descending triple (max < min) inverts the direction: less is more.
    """
    r1, r2, r3 = rng
    x = np.asarray(x, dtype=float)
    ml = 1.5 / (r2 - r1)
    sl = 1.0 - r1 * ml
    mu = 2.5 / (r3 - r2)
    su = 2.5 - r2 * mu
    if r3 > r1:
        conditions = [x < r1, x < r2, x < r3]
    else:
        conditions = [x > r1, x > r2, x > r3]
    with np.errstate(invalid="ignore"):
        out = np.select(conditions, [SCORE_MIN, sl + ml * x, su + mu * x], default=SCORE_MAX)
    # The anchors are exact by definition; MATLAB's arithmetic misses them by an ulp.
    out = np.where(x == r2, 2.5, np.clip(out, SCORE_MIN, SCORE_MAX))
    out[~np.isfinite(x)] = np.nan
    return out


def tent(x: np.ndarray, rng: Sequence[float]) -> np.ndarray:
    """MATLAB ``polycalc``: 1 outside [min, max], rising linearly to 5 at mid."""
    r1, r2, r3 = rng
    x = np.asarray(x, dtype=float)
    ml = 4.0 / (r2 - r1)
    sl = 1.0 - r1 * ml
    mu = 4.0 / (r2 - r3)
    su = 1.0 - r3 * mu
    with np.errstate(invalid="ignore"):
        out = np.select([x < r1, x < r2, x < r3], [SCORE_MIN, sl + ml * x, su + mu * x],
                        default=SCORE_MIN)
    out = np.where(x == r2, SCORE_MAX, np.clip(out, SCORE_MIN, SCORE_MAX))
    out[~np.isfinite(x)] = np.nan
    return out


def score_index(raw: np.ndarray, spec: IndexSpec, missing_policy: str) -> np.ndarray:
    """Score one index. Under ``score_worst`` a missing value scores 1, as in MATLAB."""
    scores = (tent if spec.kind == "tent" else ramp)(raw, spec.range)
    if missing_policy == "score_worst":
        scores = np.where(np.isnan(scores), SCORE_MIN, scores)
    return scores


# ---------------------------------------------------------------------------
# Aggregation (manual section 6)
# ---------------------------------------------------------------------------

def rescale_rows(m: np.ndarray, lo: float = SCORE_MIN, hi: float = SCORE_MAX) -> np.ndarray:
    """Rescale each year across countries to [lo, hi], as MATLAB ``rescale``.

    Missing cells stay missing and take no part. A year where every present country has
    the same value maps to ``lo``, which is what MATLAB returns for a constant input.
    """
    out = np.full_like(m, np.nan, dtype=float)
    for i, row in enumerate(m):
        present = np.isfinite(row)
        if not present.any():
            continue
        mn, mx = row[present].min(), row[present].max()
        if mx == mn:
            out[i, present] = lo
        else:
            out[i, present] = lo + (row[present] - mn) / (mx - mn) * (hi - lo)
    return out


@dataclass(frozen=True)
class SectorResult:
    score: np.ndarray        # years by countries, before rescaling
    present: np.ndarray      # indices present per cell
    missing: np.ndarray      # object array: tuple of missing index names per cell


def sector_scores(
    scores: Mapping[str, np.ndarray], raw: Mapping[str, np.ndarray], calibration: Calibration
) -> dict[str, SectorResult]:
    """Weighted mean of the index scores within each sector.

    Missing indices are dropped and the remaining weights renormalised. A sector with
    fewer than ``min_indices_per_sector`` present is not scored. Coverage is judged on the
    *raw* value, so a gap filled by ``score_worst`` is still reported as a gap.
    """
    result: dict[str, SectorResult] = {}
    for sector in SECTORS:
        specs = [s for s in calibration.indices if s.sector == sector]
        stack = np.stack([scores[s.name] for s in specs])
        weights = np.array([s.weight for s in specs])[:, None, None]
        present = np.isfinite(stack)
        weight_sum = (weights * present).sum(axis=0)
        total = np.where(present, weights * stack, 0.0).sum(axis=0)
        count = present.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            value = np.where(count >= calibration.min_indices_per_sector, total / weight_sum, np.nan)
        raw_missing = np.empty(value.shape, dtype=object)
        for i in range(value.shape[0]):
            for j in range(value.shape[1]):
                raw_missing[i, j] = tuple(s.name for s in specs if not np.isfinite(raw[s.name][i, j]))
        result[sector] = SectorResult(score=value, present=count, missing=raw_missing)
    return result


def national_score(sectors: Mapping[str, np.ndarray], calibration: Calibration) -> np.ndarray:
    """Weighted sum of the three sector scores. A missing sector leaves the cell missing."""
    w = calibration.sector_weights
    # MATLAB order: financial, real, international.
    return w["financial"] * sectors["financial"] + w["real"] * sectors["real"] \
        + w["international"] * sectors["international"]


# ---------------------------------------------------------------------------
# The whole model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelOutput:
    years: tuple[int, ...]
    countries: tuple[str, ...]
    national: np.ndarray
    sectors: dict[str, np.ndarray]
    index_scores: dict[str, np.ndarray]
    index_raw: dict[str, np.ndarray]
    capital_saturation: np.ndarray
    coverage: CoverageReport


def resolve_years(available: Sequence[int], window: Optional[Window], default_years: int) -> tuple[int, ...]:
    """The output years: the requested window, or the last ``default_years`` available."""
    available = tuple(available)
    if window is None:
        return available[-default_years:]
    if window.start_year < available[0] or window.end_year > available[-1]:
        raise EngineError(
            f"window {window.start_year}-{window.end_year} lies outside the snapshot's "
            f"complete years {available[0]}-{available[-1]}"
        )
    return tuple(y for y in available if window.start_year <= y <= window.end_year)


def score_annual(
    years: Sequence[int],
    countries: Sequence[str],
    raw: Mapping[str, np.ndarray],
    saturation: np.ndarray,
    calibration: Calibration,
    missing_series: tuple[MissingSeries, ...] = (),
    public_fills: tuple[PublicFill, ...] = (),
    excluded: tuple[Exclusion, ...] = (),
) -> ModelOutput:
    """Sections 5 and 6: score raw indicators and aggregate. Rows of ``raw`` are ``years``.

    Split out from :func:`run_model` so that the MATLAB export, which publishes its raw
    indicator values, can be fed in directly and reconciled.
    """
    scores = {spec.name: score_index(raw[spec.name], spec, calibration.missing_policy)
              for spec in calibration.indices}
    sectors = sector_scores(scores, raw, calibration)
    sector_values = {k: v.score for k, v in sectors.items()}
    if calibration.rescale_sectors:
        sector_values = {k: rescale_rows(v) for k, v in sector_values.items()}
    national = national_score(sector_values, calibration)
    if calibration.rescale_national:
        national = rescale_rows(national)

    dropped = []
    for sector, res in sectors.items():
        for i, year in enumerate(years):
            for j, country in enumerate(countries):
                if res.missing[i, j]:
                    dropped.append(DroppedSector(
                        country=country, year=int(year), sector=sector,
                        indices_missing=res.missing[i, j],
                        scored=bool(np.isfinite(res.score[i, j])),
                    ))
    cells = len(years) * len(countries)
    coverage = CoverageReport(
        country_years=cells,
        index_cells=cells * len(INDICES),
        index_cells_missing=int(sum(np.isnan(v).sum() for v in raw.values())),
        sectors_reweighted=sum(1 for d in dropped if d.scored),
        sectors_unscored=sum(1 for d in dropped if not d.scored),
        national_unscored=int(np.isnan(national).sum()),
        missing_series=missing_series,
        dropped=tuple(dropped),
        public_fills=public_fills,
        excluded=excluded,
    )
    return ModelOutput(
        years=tuple(int(y) for y in years), countries=tuple(countries), national=national,
        sectors=sector_values, index_scores=scores, index_raw=dict(raw),
        capital_saturation=saturation, coverage=coverage,
    )


def run_model(
    panel: Panel,
    calibration: Calibration,
    countries: Sequence[str],
    window: Optional[Window],
    default_years: int,
    excluded: Sequence[Exclusion] = (),
) -> ModelOutput:
    """Panel in, every published figure out. ``excluded`` indices become gaps."""
    present = {s.country for s in panel.series}
    absent = [c for c in countries if c not in present]
    if absent:
        raise EngineError(f"the snapshot holds no series for {', '.join(absent)}")

    annual = annualise(panel, countries, calibration.annualisation)
    raw = compute_indicators(annual.data, calibration.trailing_window, calibration.trailing_min_obs)
    saturation = capital_saturation(annual.data)
    for e in excluded:
        if e.country in countries:
            raw[e.index][:, list(countries).index(e.country)] = np.nan

    years = resolve_years(annual.years, window, default_years)
    rows = [annual.years.index(y) for y in years]
    # Rescaling is per year, so slicing before scoring changes nothing but the output.
    raw = {k: v[rows] for k, v in raw.items()}
    return score_annual(years, countries, raw, saturation[rows], calibration,
                        _missing_series(panel, countries), _public_fills(panel, countries),
                        tuple(e for e in excluded if e.country in countries))


def plausibility_exclusions(coverage: UpstreamCoverage, calibration: Calibration) -> tuple[Exclusion, ...]:
    """Indices to drop, per the calibration, for every country datafeed flags."""
    out = []
    for finding in coverage.plausibility:
        for index in calibration.exclude_on_plausibility.get(finding.check, ()):
            out.append(Exclusion(country=finding.country, index=index,
                                 reason=f"datafeed {finding.check}: {finding.detail}"))
    return tuple(out)


def _public_fills(panel: Panel, countries: Sequence[str]) -> tuple[PublicFill, ...]:
    return tuple(PublicFill(country=s.country, series_id=s.series_id, source=sp.source,
                            first=sp.first, last=sp.last)
                 for s in panel.series if s.country in countries
                 for sp in s.source_spans if sp.source != panel.primary_source)


def _missing_series(panel: Panel, countries: Sequence[str]) -> tuple[MissingSeries, ...]:
    lookup = {(s.country, s.series_id): s for s in panel.series}
    total = len(panel.dates)
    out = []
    for country in countries:
        for series_id in REQUIRED_SERIES:
            s = lookup.get((country, series_id))
            missing = total if s is None else sum(1 for f in s.flags if f == "missing")
            if missing:
                out.append(MissingSeries(country=country, series_id=series_id,
                                         missing_months=missing, total_months=total))
    return tuple(out)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def as_matrix(m: np.ndarray) -> tuple[tuple[Optional[float], ...], ...]:
    """numpy -> contract matrix, NaN -> None."""
    return tuple(tuple(None if not np.isfinite(v) else float(v) for v in row) for row in m)


def peer_stats(scores: HoNIScores) -> tuple[PeerStatsRow, ...]:
    """Cross-sectional spread per index per year, on the scores and on the raw values."""
    rows = []
    for basis, block in (("score", scores.index_scores), ("raw", scores.index_raw)):
        for index in INDICES:
            matrix = block[index]
            for i, year in enumerate(scores.years):
                values = np.array([v for v in matrix[i] if v is not None], dtype=float)
                if values.size:
                    q = np.percentile(values, [0, 25, 50, 75, 100])
                    stats = dict(zip(("min", "p25", "median", "p75", "max"), map(float, q)))
                else:
                    stats = dict.fromkeys(("min", "p25", "median", "p75", "max"))
                rows.append(PeerStatsRow(index=index, year=year, basis=basis,
                                         n=int(values.size), **stats))
    return tuple(rows)


# ---------------------------------------------------------------------------
# Trends (computed on read, like the peer statistics)
# ---------------------------------------------------------------------------

TREND_DEFINITIONS = {
    "latest": "value in the chosen year",
    "base": "value `window` years before the chosen year (year - window)",
    "change": "latest - base; missing if either is missing",
    "slope": "least-squares slope per year over the window years present (the `window` years "
             "ending with the chosen year); missing below `min_obs` present years",
    "level_z": "(latest - mean) / standard deviation (ddof 1) over the same window years: how "
               "unusual the latest value is against the country's own recent history; missing "
               "below `min_obs` present years, when the latest value is missing, or when the "
               "window is flat",
    "n": "number of window years with a value",
}


def trend_min_obs(window: int) -> int:
    """Fewest present years a slope or a z-score is computed from: half the window, at least 3."""
    return max(3, -(-window // 2))


def trend_stats(matrix: Sequence[Sequence[Optional[float]]], years: Sequence[int], year: int,
                window: int) -> dict[str, tuple]:
    """Per country: latest, base, change, slope, level_z and n for one years-by-countries matrix.

    Missing stays missing: nothing is interpolated, and a statistic that cannot be computed
    from what is present is None (Guide section 1, fail loudly).
    """
    years = list(years)
    if year not in years:
        raise EngineError(f"year {year} is not in the artefact ({years[0]} to {years[-1]})")
    if window < 3:
        raise EngineError("window must be at least 3 years")
    m = np.array([[np.nan if v is None else float(v) for v in row] for row in matrix], dtype=float)
    t = years.index(year)
    rows = [i for i, y in enumerate(years) if year - window < y <= year]
    base_row = years.index(year - window) if (year - window) in years else None
    min_obs = trend_min_obs(window)
    x_all = np.array([years[i] for i in rows], dtype=float)
    out: dict[str, list] = {k: [] for k in ("latest", "base", "change", "slope", "level_z", "n")}
    for j in range(m.shape[1]):
        latest = m[t, j]
        base = m[base_row, j] if base_row is not None else np.nan
        col = m[rows, j]
        present = np.isfinite(col)
        n = int(present.sum())
        slope = z = np.nan
        if n >= min_obs:
            x, y = x_all[present], col[present]
            xc = x - x.mean()
            slope = float((xc * (y - y.mean())).sum() / (xc * xc).sum())
            sd = float(y.std(ddof=1))
            if np.isfinite(latest) and sd > 0:
                z = float((latest - y.mean()) / sd)
        out["latest"].append(latest)
        out["base"].append(base)
        out["change"].append(latest - base)
        out["slope"].append(slope)
        out["level_z"].append(z)
        out["n"].append(n)

    def fin(v: float) -> Optional[float]:
        return None if not np.isfinite(v) else float(v)

    return {k: tuple(v) if k == "n" else tuple(fin(x) for x in v) for k, v in out.items()}


def trends(scores: HoNIScores, window: int = 10, year: Optional[int] = None) -> HoNITrends:
    """Every published series of an artefact, summarised over the trailing window."""
    year = scores.years[-1] if year is None else year
    blocks: list[tuple] = [("national", "HoNI", "score", None, None, scores.national)]
    blocks += [(s, f"{s} sector", "score", s, None, scores.sectors[s]) for s in SECTORS]
    blocks.append(("capital_saturation", "capital saturation", "saturation", None, None,
                   scores.capital_saturation))
    blocks += [(f"score:{i}", i.replace("_", " "), "score", INDICES[i], i, scores.index_scores[i])
               for i in INDICES]
    blocks += [(f"raw:{i}", f"{i.replace('_', ' ')} (raw)", "raw", INDICES[i], i,
                scores.index_raw[i]) for i in INDICES]
    series = tuple(TrendSeries(key=k, label=lab, basis=b, sector=sec, index=idx,
                               **trend_stats(m, scores.years, year, window))
                   for k, lab, b, sec, idx, m in blocks)
    return HoNITrends(artefact_id=scores.artefact_id, year=year, window=window,
                      first_year=max(scores.years[0], year - window + 1), base_year=year - window,
                      min_obs=trend_min_obs(window), countries=scores.countries, series=series,
                      definitions=TREND_DEFINITIONS)
