"""The model card (``GET /model``): HoNI explained on one economy's data.

HoNI is relative: every year the sector and national scores are rescaled across the peer set.
So the card runs the whole model on the peer set, with the engine's own functions
(``engine.py``), and shows the chosen economy step by step, next to its peers wherever the step
compares them. Pure: the service hands in the panel, the calibration and the exclusions.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

import numpy as np

from . import ENGINE, ENGINE_VERSION
from .contracts import (
    INDICES,
    SECTORS,
    Calibration,
    Chart,
    ChartSeries,
    EconomyOption,
    Exclusion,
    ModelCard,
    ModelInput,
    ModelOutputField,
    ModelStep,
    Panel,
    Parameter,
)
from .engine import (
    INDICATORS,
    REQUIRED_SERIES,
    annualise,
    capital_saturation,
    compute_indicators,
    national_score,
    ramp,
    resolve_years,
    score_annual,
    sector_scores,
    tent,
)

#: Plain names of the 21 inputs: (name, unit, what it is).
INPUTS: dict[str, tuple[str, str, str]] = {
    "consumer.corruption_freedom": ("Freedom from corruption", "index, 0 to 100",
                                    "Heritage Foundation score; higher is cleaner."),
    "consumer.gdp_per_capita": ("GDP per person", "USD, current prices", "IMF, current US dollars."),
    "consumer.population": ("Population", "bn people", "Resident population."),
    "consumer.wage_growth": ("Wage growth", "share per year", "Change of nominal wages against a year before."),
    "consumer.household_consumption": ("Household consumption", "bn, local currency",
                                       "Consumption expenditure of households."),
    "consumer.labour_force_participation": ("Labour force participation", "share of working-age people",
                                            "People working or looking for work."),
    "debt.corporate_gdp": ("Corporate debt", "share of GDP", "Debt of non-financial companies."),
    "debt.external": ("External debt", "bn, USD", "Debt owed to non-residents."),
    "debt.government_gdp": ("Government debt", "share of GDP", "General government debt."),
    "debt.household_gdp": ("Household debt", "share of GDP", "Debt of households."),
    "debt.financial_sector": ("Financial-sector debt", "bn, local currency", "Debt securities of the financial sector (BIS)."),
    "equity.market_cap_gdp": ("Stock market value", "share of GDP", "Market capitalisation of listed shares."),
    "fx.trade_balance": ("Trade balance", "bn, as pulled", "Exports minus imports of goods."),
    "fx.terms_of_trade": ("Terms of trade (commodities)", "index (Citi)",
                          "Export against import commodity prices; above zero is favourable."),
    "fx.reserves": ("Foreign reserves", "bn, USD", "Central bank reserve assets."),
    "inflation.cpi_yoy": ("Consumer price inflation", "share per year", "CPI against twelve months before."),
    "money.budget_balance_gdp": ("Government budget balance", "share of GDP", "Revenue minus spending; negative is a deficit."),
    "money.broad_money": ("Broad money", "bn, local currency", "M3 (M2 where that is the national aggregate)."),
    "production.gdp_nominal": ("GDP, nominal", "bn, local currency", "Gross domestic product at current prices."),
    "production.imports": ("Imports", "bn, as pulled", "Imports of goods."),
    "yields.govt_10y": ("10-year government bond yield", "share per year", "Generic 10-year yield."),
}

#: Plain name and formula of each index. \overline{x}_t is the trailing mean (see the step).
INDEX_TEXT: dict[str, tuple[str, str]] = {
    "budget_balance": ("Budget balance", r"I_t=\mathit{BB}_t"),
    "monetary_supply": ("Money growth over GDP growth", r"I_t=\overline{g(M)-g(Y)}_t"),
    "government_debt": ("Government debt", r"I_t=D^{\text{gov}}_t"),
    "real_rate_10y": ("Real 10-year rate", r"I_t=\overline{r^{10y}-\pi}_t"),
    "market_cap": ("Stock market size", r"I_t=\mathit{MC}_t"),
    "external_debt_affordability": ("External debt affordability", r"I_t=\overline{\mathit{TB}/D^{\text{ext}}}_t"),
    "external_debt_exposure": ("External debt exposure", r"I_t=D^{\text{ext}}_t/Y_t"),
    "terms_of_trade": ("Terms of trade", r"I_t=\overline{\mathit{ToT}}_t"),
    "import_reserves": ("Reserve cover of imports", r"I_t=R_t/M^{\text{imp}}_t"),
    "corruption_freedom": ("Freedom from corruption", r"I_t=\mathit{CF}_t"),
    "consumption_power": ("Consumer purchasing power", r"I_t=w_t-\pi_t"),
    "population_growth": ("Population growth", r"I_t=g(P)_t"),
    "gdp_per_capita_growth": ("Real growth per person", r"I_t=\overline{g(y)-\pi}_t"),
    "consumption_dependency": ("Consumption share of GDP", r"I_t=C_t/Y_t"),
    "labour_force": ("Labour force participation", r"I_t=\mathit{LF}_t"),
}
SECTOR_NAME = {"financial": "Financial economy", "international": "International resilience", "real": "Real economy"}


def _v(x) -> tuple[Optional[float], ...]:
    return tuple(None if v is None or not np.isfinite(v) else float(v) for v in np.asarray(x, dtype=float))


def _median(m: np.ndarray) -> np.ndarray:
    out = np.full(m.shape[0], np.nan)
    for i, row in enumerate(m):
        if np.isfinite(row).any():
            out[i] = float(np.nanmedian(row))
    return out


def _g(v: Optional[float]) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{float(v):.3g}"


def _last(x: np.ndarray) -> Optional[float]:
    finite = np.flatnonzero(np.isfinite(x))
    return float(x[finite[-1]]) if finite.size else None


def transfer_curve(spec, raw_now: Optional[float]) -> tuple[list[float], list[Optional[float]], list[Optional[float]]]:
    """x grid over the range (with the economy's value on it), the score curve, and the point."""
    lo, hi = min(spec.range[0], spec.range[2]), max(spec.range[0], spec.range[2])
    pad = 0.25 * (hi - lo)
    grid = set(np.linspace(lo - pad, hi + pad, 81).round(10).tolist()) | {float(r) for r in spec.range}
    if raw_now is not None:
        grid.add(float(raw_now))
    xs = sorted(grid)
    f = tent if spec.kind == "tent" else ramp
    ys = f(np.asarray(xs), spec.range)
    point = [float(ys[i]) if raw_now is not None and x == float(raw_now) else None for i, x in enumerate(xs)]
    return xs, _v(ys), point


def build(panel: Panel, cal: Calibration, code: str, names: Mapping[str, str], countries: Sequence[str],
          excluded: Sequence[Exclusion], default_years: int) -> ModelCard:
    countries = list(countries)
    j = countries.index(code)
    annual = annualise(panel, countries, cal.annualisation)
    raw_all = compute_indicators(annual.data, cal.trailing_window, cal.trailing_min_obs)
    sat_all = capital_saturation(annual.data)
    for e in excluded:
        if e.country in countries:
            raw_all[e.index][:, countries.index(e.country)] = np.nan
    years = resolve_years(annual.years, None, default_years)
    rows = [annual.years.index(y) for y in years]
    raw = {k: v[rows] for k, v in raw_all.items()}
    out = score_annual(years, countries, raw, sat_all[rows], cal)
    yrs = tuple(int(y) for y in years)
    specs = {s.name: s for s in cal.indices}
    pre = sector_scores(out.index_scores, raw, cal)
    peer_names = [names[c] for c in countries]
    last = len(yrs) - 1

    # ---- data in -------------------------------------------------------------------
    lookup = {(s.country, s.series_id): s for s in panel.series}
    inputs = []
    for key in REQUIRED_SERIES:
        s = lookup.get((code, key))
        label, unit, text = INPUTS[key]
        fills = sorted({sp.source for sp in s.source_spans if sp.source != panel.primary_source}) if s else []
        inputs.append(ModelInput(
            key=key, name=label, unit=unit, frequency="monthly axis", description=text,
            source=f"datafeed, {panel.primary_source}" + (f"; gaps filled from {', '.join(fills)}" if fills else ""),
            x=tuple(panel.dates), y=tuple(s.values) if s else tuple(None for _ in panel.dates)))

    steps: list[ModelStep] = []
    ay = tuple(int(y) for y in annual.years)

    # 1. months to years
    steps.append(ModelStep(
        key="annual", title="From months to years",
        text=("Every input is reduced to one value per calendar year, the December observation. A year "
              "with a missing December is missing: nothing is filled, and a missing input never scores."),
        formulas=(r"x_t = x_{\text{Dec},\,t}" if cal.annualisation == "year_end"
                  else r"x_t = \tfrac{1}{12}\sum_{m=1}^{12} x_{m,t}",),
        parameters=(Parameter(symbol="", name="Annual value", value=cal.annualisation),),
        charts=(Chart(title="Which inputs are present, year by year", kind="heatmap", x=ay,
                      rows=tuple(INPUTS[k][0] for k in REQUIRED_SERIES),
                      z=tuple(tuple(0.0 if np.isfinite(v) else 1.0 for v in annual.data[k][:, j]) for k in REQUIRED_SERIES),
                      categories=("present", "missing")),),
    ))

    # 2. the fifteen indicators
    charts, params = [], []
    for d in INDICATORS:
        label, formula = INDEX_TEXT[d.name]
        mine, med = raw[d.name][:, j], _median(raw[d.name])
        params.append(Parameter(symbol=formula, name=f"{label} ({SECTOR_NAME[INDICES[d.name]].lower()})",
                                value=f"{names[code]} {_g(mine[last])}, peer median {_g(med[last])} ({yrs[last]})"))
        charts.append(Chart(title=f"{label}: {d.definition}", x=yrs,
                            series=(ChartSeries(name=names[code], y=_v(mine), slot=0),
                                    ChartSeries(name="Peer median", y=_v(med), muted=True, dash="dash"))))
    steps.append(ModelStep(
        key="indicators", title="The fifteen indicators",
        text=("Each index is a plain ratio or difference of the inputs. Five of them are smoothed with a "
              f"trailing mean over the last {cal.trailing_window} years (fewer at the start of the data), "
              "so a single year cannot swing them."),
        formulas=(r"g(x)_t=\frac{x_t-x_{t-1}}{x_{t-1}}",
                  r"\overline{x}_t=\frac{1}{|S_t|}\sum_{s\in S_t}x_s,\qquad "
                  r"S_t=\{s:\ t-W+1\le s\le t,\ x_s\ \text{present}\},\qquad |S_t|\ge n_{\min}"),
        parameters=(Parameter(symbol="W", name="Trailing window", value=f"{cal.trailing_window} years"),
                    Parameter(symbol=r"n_{\min}", name="Years needed in the window", value=str(cal.trailing_min_obs)),
                    *params),
        charts=tuple(charts),
    ))

    # 3. scoring
    curves, sparams = [], []
    for d in INDICATORS:
        spec, label = specs[d.name], INDEX_TEXT[d.name][0]
        now = raw[d.name][last, j]
        now = float(now) if np.isfinite(now) else None
        xs, ys, point = transfer_curve(spec, now)
        r1, r2, r3 = spec.range
        sparams.append(Parameter(symbol=r"r_1,r_2,r_3", name=f"{label}: {spec.kind}",
                                 value=f"{r1:g} / {r2:g} / {r3:g}" + (" (descending: less is better)"
                                                                     if spec.kind == "ramp" and r3 < r1 else "")
                                       + f"; {names[code]} scores {_g(out.index_scores[d.name][last, j])} in {yrs[last]}"))
        curves.append(Chart(title=f"{label}: score by value", x=tuple(xs), x_label=d.definition, y_label="score 1 to 5",
                            series=(ChartSeries(name=spec.kind, y=ys, muted=True),
                                    ChartSeries(name=f"{names[code]} {yrs[last]}", y=tuple(point), kind="markers", slot=0))))
    heat = Chart(title=f"{names[code]}: the fifteen scores, year by year", kind="heatmap", x=yrs,
                 rows=tuple(INDEX_TEXT[k][0] for k in INDICES),
                 z=tuple(_v(out.index_scores[k][:, j]) for k in INDICES))
    steps.append(ModelStep(
        key="scoring", title="From value to score, 1 to 5",
        text=("Each index is turned into a score from 1 (worst) to 5 (best) by a piecewise-linear transfer "
              "function with three calibrated points. A ramp rises from 1 to 5 (1 at the first point, 2.5 at "
              "the middle one, 5 at the last; a descending triple means less is better). A tent is best at "
              "its middle point and falls to 1 at either end. "
              + ("A missing value gets no score and its sector is re-weighted." if cal.missing_policy == "exclude"
                 else "A missing value scores 1, as MATLAB did.")),
        formulas=(r"\text{ramp}(x)=\begin{cases}1 & x<r_1\\ 1+1.5\,\frac{x-r_1}{r_2-r_1} & r_1\le x<r_2\\"
                  r" 2.5+2.5\,\frac{x-r_2}{r_3-r_2} & r_2\le x<r_3\\ 5 & x\ge r_3\end{cases}",
                  r"\text{tent}(x)=\begin{cases}1+4\,\frac{x-r_1}{r_2-r_1} & r_1\le x<r_2\\"
                  r" 1+4\,\frac{x-r_3}{r_2-r_3} & r_2\le x<r_3\\ 1 & \text{otherwise}\end{cases}"),
        parameters=tuple(sparams), charts=(heat, *curves),
    ))

    # 4. sectors
    steps.append(ModelStep(
        key="sectors", title="Three sectors",
        text=("The five index scores of each sector are averaged. A missing index is left out and the others "
              f"re-weighted; a sector needs at least {cal.min_indices_per_sector} of its five indices, or it "
              "has no score that year."),
        formulas=(r"S^{\sigma}_t=\frac{\sum_{k\in\sigma,\ s_k\ \text{present}}\omega_k\,s_{k,t}}"
                  r"{\sum_{k\in\sigma,\ s_k\ \text{present}}\omega_k},\qquad "
                  r"\#\{k\in\sigma:\ s_k\ \text{present}\}\ge m",),
        parameters=(Parameter(symbol="m", name="Indices needed per sector", value=str(cal.min_indices_per_sector)),
                    Parameter(symbol=r"\omega_k", name="Index weights",
                              value="equal" if len({s.weight for s in cal.indices}) == 1
                              else ", ".join(f"{s.name} {s.weight:g}" for s in cal.indices))),
        charts=(Chart(title=f"{names[code]}: sector means before rescaling", x=yrs, y_label="score 1 to 5",
                      series=tuple(ChartSeries(name=SECTOR_NAME[s], y=_v(pre[s].score[:, j]), slot=i + 1)
                                   for i, s in enumerate(SECTORS))),),
    ))

    # 5. rescaling across the peers
    if cal.rescale_sectors:
        bars = []
        for i, s in enumerate(SECTORS):
            before, after = pre[s].score[last], out.sectors[s][last]
            order = sorted(range(len(countries)), key=lambda c: (-np.inf if not np.isfinite(after[c]) else after[c]))
            bars.append(Chart(title=f"{SECTOR_NAME[s]}, {yrs[last]}: before and after", x=tuple(peer_names[c] for c in order),
                              y_label="score 1 to 5",
                              series=(ChartSeries(name="Mean score", y=_v(before[order]), kind="bar", muted=True),
                                      ChartSeries(name="Rescaled", y=_v(after[order]), kind="bar", slot=i + 1))))
        steps.append(ModelStep(
            key="rescale", title="Relative to the peers",
            text=("Every year each sector is stretched across the peer set, so the best economy scores 5 and "
                  "the worst 1. The score says where an economy stands among its peers, not how good it is in "
                  "absolute terms."),
            formulas=(r"\hat S^{\sigma}_{c,t}=1+4\,\frac{S^{\sigma}_{c,t}-\min_{c'}S^{\sigma}_{c',t}}"
                      r"{\max_{c'}S^{\sigma}_{c',t}-\min_{c'}S^{\sigma}_{c',t}}",),
            parameters=(Parameter(symbol="", name="Peer set", value=", ".join(countries)),),
            charts=tuple(bars),
        ))

    # 6. national score
    nat_pre = national_score(out.sectors, cal)
    order = sorted(range(len(countries)), key=lambda c: (-np.inf if not np.isfinite(out.national[last, c]) else out.national[last, c]))
    rank_mine = [float(out.national[last, c]) if c == j and np.isfinite(out.national[last, c]) else None for c in order]
    w = cal.sector_weights
    steps.append(ModelStep(
        key="national", title="National score",
        text=("The three sector scores are combined with the sector weights"
              + (", and the result is rescaled across the peers once more." if cal.rescale_national else ".")
              + " A missing sector leaves the national score missing that year."),
        formulas=(r"N_{c,t}=\sum_{\sigma}w_{\sigma}\,\hat S^{\sigma}_{c,t}"
                  + (r",\qquad \hat N_{c,t}=1+4\,\frac{N_{c,t}-\min_{c'}N_{c',t}}{\max_{c'}N_{c',t}-\min_{c'}N_{c',t}}"
                     if cal.rescale_national else ""),),
        parameters=(Parameter(symbol=r"w_{\sigma}", name="Sector weights",
                              value=", ".join(f"{SECTOR_NAME[s].lower()} {w[s]:.3g}" for s in SECTORS)),),
        charts=(Chart(title=f"{names[code]}: national score", x=yrs, y_label="score 1 to 5",
                      series=(ChartSeries(name="Weighted sum", y=_v(nat_pre[:, j]), dash="dash", slot=0),
                              ChartSeries(name="National score", y=_v(out.national[:, j]), slot=0),
                              ChartSeries(name="Peer median", y=_v(_median(out.national)), muted=True, dash="dash"))),
                Chart(title=f"Ranking, {yrs[last]}", x=tuple(peer_names[c] for c in order), y_label="national score 1 to 5",
                      series=(ChartSeries(name="Peers", y=_v(out.national[last][order]), kind="bar", muted=True),
                              ChartSeries(name=names[code], y=tuple(rank_mine), kind="markers", slot=0)))),
    ))

    # 7. capital saturation
    steps.append(ModelStep(
        key="saturation", title="Capital saturation, published beside the score",
        text=("Total debt over GDP. It is not part of the score: it is the x axis of the CIO's chart, next to "
              "the national score."),
        formulas=(r"K_t = D^{\text{corp}}_t + D^{\text{gov}}_t + D^{\text{hh}}_t + \frac{D^{\text{fin}}_t}{Y_t}",),
        charts=(Chart(title="Capital saturation", x=yrs, y_label="share of GDP",
                      series=(ChartSeries(name=names[code], y=_v(out.capital_saturation[:, j]), slot=0),
                              ChartSeries(name="Peer median", y=_v(_median(out.capital_saturation)), muted=True, dash="dash"))),),
    ))

    cov = out.coverage
    dropped = [d for d in cov.dropped if d.country == code]
    notes = [
        f"{names[code]} {yrs[last]}: national {_g(out.national[last, j])}, "
        + ", ".join(f"{SECTOR_NAME[s].lower()} {_g(out.sectors[s][last, j])}" for s in SECTORS)
        + f"; capital saturation {_g(out.capital_saturation[last, j])}.",
        f"Sectors re-weighted for a missing index: {sum(d.scored for d in dropped)} of {len(yrs) * 3} sector-years; "
        f"not scored: {sum(not d.scored for d in dropped)}.",
    ]
    fills = sorted({f"{s.series_id} ({sp.source})" for s in panel.series if s.country == code
                    for sp in s.source_spans if sp.source != panel.primary_source})
    if fills:
        notes.append("Inputs with public-source fills: " + ", ".join(fills) + ".")
    notes += [f"Excluded: {e.index} ({e.reason})." for e in excluded if e.country == code]
    return ModelCard(
        engine=ENGINE, title="Health of Nations Index",
        summary=("Rates how healthy each economy is relative to its peers: fifteen indices scored 1 to 5, "
                 "averaged into three sectors (financial, international, real) and one national score, each "
                 "rescaled every year so the best peer scores 5 and the worst 1. Capital saturation is "
                 "published beside it."),
        engine_version=ENGINE_VERSION, calibration_version=cal.version,
        data=f"datafeed snapshot {panel.snapshot_id} (as of {panel.as_of}); peer set of {len(countries)}",
        economy=EconomyOption(code=code, name=names[code]),
        economies=tuple(EconomyOption(code=c, name=names[c]) for c in countries),
        inputs=tuple(inputs), steps=tuple(steps),
        outputs=(
            ModelOutputField(key="national", name="National score", unit="1 to 5, relative",
                             description="Per economy and year. Read by the CIO for the optimiser's boundary conditions."),
            ModelOutputField(key="sectors", name="Sector scores", unit="1 to 5, relative",
                             description="Financial economy, international resilience, real economy."),
            ModelOutputField(key="index_scores", name="Index scores", unit="1 to 5",
                             description="The fifteen scores before aggregation."),
            ModelOutputField(key="index_raw", name="Index values", unit="as each index",
                             description="The fifteen indicator values before scoring."),
            ModelOutputField(key="capital_saturation", name="Capital saturation", unit="share of GDP",
                             description="Total debt over GDP, not part of the score."),
            ModelOutputField(key="coverage", name="Coverage", unit="",
                             description="Missing inputs, re-weighted and unscored sectors, public fills, exclusions."),
        ),
        output_charts=(Chart(title=f"{names[code]}: what HoNI publishes", x=yrs, y_label="score 1 to 5",
                             series=(ChartSeries(name="National", y=_v(out.national[:, j]), slot=0),
                                     *(ChartSeries(name=SECTOR_NAME[s], y=_v(out.sectors[s][:, j]), slot=i + 1,
                                                   dash="dot") for i, s in enumerate(SECTORS)))),),
        notes=tuple(notes),
    )
