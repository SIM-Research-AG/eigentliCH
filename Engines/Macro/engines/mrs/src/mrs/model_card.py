"""The model card (``GET /model``): the Market Risk Signal explained on one economy's data.

Each economy is computed on its own, so the card runs the engine's functions
(``indicators.compute``, ``engine.assess``, ``engine.kernel_matrix``) for one economy on the
configured datafeed snapshot and keeps what each step produced. Pure: the service hands in
the panel and the calibration.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from . import ENGINE, ENGINE_VERSION
from . import indicators as ind
from .contracts import (
    INDICATORS,
    N_STATES,
    SEGMENT_INDICATORS,
    SEGMENTS,
    BandKernel,
    Calibration,
    Chart,
    ChartSeries,
    EconomyOption,
    ModelCard,
    ModelInput,
    ModelOutputField,
    ModelStep,
    Panel,
    Parameter,
    TailKernel,
)
from .engine import assess, grid, kernel_matrix
from .inputs import matrix
from .series import BY_ID, PUBLIC_SERIES

UNITS = {"price": "price level", "ratio": "decimal (0.03 = 3%)", "index_level": "index level", "level": "level",
         "index": "index level"}
INDICATOR_NAME = {
    "inflation": "Inflation", "monetary": "Monetary conditions", "consumer": "Consumer", "company": "Companies",
    "bond": "Bonds", "equity": "Equity valuation", "trend_osc": "Trend and oscillators", "fear_greed": "Fear and greed",
    "global_stability": "Global stability", "market_stability": "Market stability",
    "monetary_uncertainty": "Monetary uncertainty",
}
SEGMENT_NAME = {"business_cycle": "Business cycle", "investment": "Investment",
                "market_behaviour": "Market behaviour", "market_stress": "Market stress"}


def _v(x) -> tuple[Optional[float], ...]:
    return tuple(None if v is None or not math.isfinite(v) else float(v) for v in np.asarray(x, dtype=float))


def _names(p) -> dict[str, tuple[str, str]]:
    out = {sid: (BY_ID[sid].description, UNITS.get(BY_ID[sid].unit, BY_ID[sid].unit)) for sid in BY_ID}
    out.update({s.series_id: (s.description.split(";")[0].split(",")[0], UNITS.get(s.unit, s.unit)) for s in PUBLIC_SERIES})
    return out


def build(panel: Panel, cal: Calibration, code: str, name: str, economies: Sequence[EconomyOption]) -> ModelCard:
    p = cal.indicators
    needed = ind.series_needed(p)
    n = len(panel.dates)
    x = tuple(panel.dates)
    series = {sid: matrix(panel, sid, [code])[:, 0] for sid in needed}
    layer = ind.compute(series, p, n)
    segs = {s: _v(layer.segments[s]) for s in SEGMENTS}
    a = assess(segs, n, cal)
    names = _names(p)
    lookup = {(s.country, s.series_id): s for s in panel.series}
    th, lw = p.thresholds, p.lcl_weights
    w = p.segment_weights()

    # ---- data in -------------------------------------------------------------------
    inputs = []
    for sid in needed:
        s = lookup.get((code, sid))
        label, unit = names.get(sid, (sid, ""))
        fills = sorted({sp.source for sp in s.source_spans if sp.source != panel.primary_source}) if s else []
        inputs.append(ModelInput(
            key=sid, name=label, unit=unit, frequency="monthly", description=label,
            source=f"datafeed, {panel.primary_source}" + (f"; filled from {', '.join(fills)}" if fills else ""),
            x=x, y=tuple(s.values) if s else tuple(None for _ in x)))

    def ind_chart(title: str, keys: Sequence[str], y_label: str = "standardised") -> Chart:
        return Chart(title=title, x=x, y_label=y_label,
                     series=tuple(ChartSeries(name=INDICATOR_NAME[k], y=_v(layer.indicators[k]), slot=i % 5)
                                  for i, k in enumerate(keys)))

    lcl = rf"w_L={lw[0]:g},\ w_C={lw[1]:g},\ w_G={lw[2]:g}"
    steps: list[ModelStep] = []
    production = p.mode == "production"

    # 1. standardising
    cpi = series.get("inflation.cpi_yoy")
    steps.append(ModelStep(
        key="standardise", title="Standardising, with data up to each month only" if production else "Standardising (full sample, as MATLAB)",
        text=("Every input is turned into a z-score: how many standard deviations it sits from its own "
              "average. "
              + (f"Only the months up to the one being read count, so nothing is known before it happened. "
                 f"An input needs {p.min_history_input} months, a combination {p.min_history_composite}. "
                 "Inside an indicator a missing part reads as the average (0); an indicator is missing only "
                 "when all its parts are." if production else
                 "The mean and standard deviation are taken over the whole sample, as MATLAB did.")
              + " Each indicator combines a leading, a concurrent and a lagging part."),
        formulas=(r"z_t=\frac{x_t-\bar x_{\le t}}{s_{\le t}},\qquad \bar x_{\le t},\ s_{\le t}\ \text{over the observed months}\ \le t"
                  if production else r"z_t=\frac{x_t-\bar x}{s}",
                  r"I=Z\!\left(w_L\,z(a)+w_C\,z(b)+w_G\,z(c)\right),\qquad " + lcl),
        parameters=(Parameter(symbol=r"n_{\text{in}}", name="Months needed for an input", value=str(p.min_history_input)),
                    Parameter(symbol=r"n_{\text{comb}}", name="Months needed for a combination", value=str(p.min_history_composite)),
                    Parameter(symbol="w_L, w_C, w_G", name="Leading, concurrent, lagging weights",
                              value=" / ".join(f"{v:g}" for v in lw))),
        charts=((Chart(title="Example: consumer price inflation as read", x=x, y_label="decimal",
                       series=(ChartSeries(name="CPI inflation", y=_v(cpi), muted=True),)),
                 Chart(title="... and as a z-score", x=x, y_label="standard deviations",
                       series=(ChartSeries(name="z(CPI inflation)", y=_v(ind.x_zscore(cpi, p.min_history_input)
                                                                         if production else ind.m_normalize(cpi)), slot=0),)))
                if cpi is not None else ()),
    ))

    # 2. business cycle
    fx = names.get(p.inflation_fx_series, (p.inflation_fx_series,))[0]
    steps.append(ModelStep(
        key="business_cycle", title="Business-cycle indicators",
        text="Four indicators of where the real economy stands: prices, money, consumers and companies.",
        formulas=(rf"I_{{\text{{inflation}}}}=Z\big(w_L z(\text{{{fx.split(' (')[0]}}})+w_C z(\text{{PPI}})+w_G z(\text{{CPI}})\big)",
                  r"I_{\text{monetary}}=Z\big(w_L z(-(y_{10}-y_{2}))+w_C z(-\text{M1})+w_G z(-\text{buybacks})\big)",
                  r"I_{\text{consumer}}=Z\big(w_L z(\text{wages})+w_C z(\text{consumption})+w_G z(-\text{unemployment})\big)",
                  r"I_{\text{company}}=Z\big(w_L z(\text{margin})+w_C z(\text{PMI})+w_G z(\text{debt/assets})\big)"),
        charts=(ind_chart("Business-cycle indicators", SEGMENT_INDICATORS["business_cycle"]),),
    ))

    # 3. investment
    hy = "HY yield to worst" if p.bond_hy_series == "yields.high_yield_ytw" else "HY index level"
    steps.append(ModelStep(
        key="investment", title="Investment indicators",
        text="How bonds and equities are priced: credit spreads, real yields and bad loans; valuation multiples.",
        formulas=(rf"I_{{\text{{bond}}}}=Z\big(-w_L z(\text{{{hy}}}-y_{{10}})-w_C z(y_{{10}}-\pi)-w_G z(\text{{NPL}})\big)",
                  r"I_{\text{equity}}=Z\big(-\big(-w_L z(\text{P/E})+w_C z(\text{P/S})-w_G z(\text{dividend yield})\big)\big)"),
        charts=(ind_chart("Investment indicators", SEGMENT_INDICATORS["investment"]),),
    ))

    # 4. market behaviour
    k = p.trend_osc
    fg = names.get(p.fear_greed_series, (p.fear_greed_series,))[0]
    steps.append(ModelStep(
        key="market_behaviour", title="Market-behaviour indicators",
        text=("Trend and oscillators compare the equity index with its moving averages and momentum measures; "
              f"fear and greed reads the detrended {fg.split(',')[0]}."),
        formulas=(r"T_t=100\,\frac{P_t}{P_0},\qquad \mathit{TI}=\sum_{m}\big(\mathrm{EMA}_m(T)-T\big)+\big(\mathrm{SAR}(T)-T\big)",
                  r"O=\tilde{\mathrm{MACD}}+\tilde{\mathrm{MOM}}+\tilde{\mathrm{ROC}}+\tilde{\mathrm{KST}},\qquad "
                  r"I_{\text{trend}}=-Z\big(\operatorname{clip}(O/s_O-\mathit{TI}/s_{TI},\pm c)\big)",
                  r"I_{\text{fear}}=-Z\big(\operatorname{detrend}(\text{" + fg.split(",")[0].replace("&", "and") + r"})\big)"),
        parameters=(Parameter(symbol="m", name="EMA windows", value=", ".join(str(v) for v in k.ema) + " months"),
                    Parameter(symbol="", name="SAR, momentum, ROC windows", value=f"{k.sar}, {k.momentum}, {k.roc} months"),
                    Parameter(symbol="", name="MACD", value="/".join(str(v) for v in k.macd)),
                    Parameter(symbol="c", name="Clip", value=f"{k.clip:g}")),
        charts=(ind_chart("Market-behaviour indicators", SEGMENT_INDICATORS["market_behaviour"]),),
    ))

    # 5. market stress
    mu = p.monetary_uncertainty
    steps.append(ModelStep(
        key="market_stress", title="Market-stress indicators",
        text=("Warning flags, each 0 or 1: large dollar moves, a positive overnight swap, erratic gold, banks "
              "falling behind the index, a volatility spike, stress in leveraged loans; and money growing away "
              "from GDP."),
        formulas=(rf"I_{{\text{{global}}}}={th.flag_scale:g}\big(w_L\,\mathbb{{1}}[|\Delta\mathrm{{DXY}}|>{th.dxy_move:g}]"
                  rf"+w_C\,\mathbb{{1}}[\mathrm{{OIS}}>{th.ois_level:g}]+w_G\,\mathbb{{1}}[s_{{{th.gold_window}}}(\Delta\text{{gold}})>{th.gold_std:g}]\big)",
                  rf"I_{{\text{{market}}}}={th.flag_scale:g}\big(w_L\,\mathbb{{1}}[\overline{{\Delta\ln B-\Delta\ln P}}_{{{th.bank_window}}}<{th.bank_vs_index:g}]"
                  rf"+w_C\,\mathbb{{1}}[V>{th.vix_level:g}\wedge\Delta\nabla V>{th.vix_accel:g}]"
                  rf"+w_G\,\mathbb{{1}}[|\overline{{\nabla L/L}}_{{{th.loan_window}}}|>{th.loan_move:g}]\big)",
                  rf"I_{{\text{{monetary unc.}}}}={mu.scale:g}\,\big|\operatorname{{clip}}\big(\overline{{\operatorname{{detrend}}(M3/Y)}}_{{{mu.window}}}/s,\ \pm{mu.clip:g}\big)\big|"),
        parameters=(Parameter(symbol="V", name="Volatility index (VIX or local), decimal",
                              value=f"above {th.vix_level:g} and accelerating by {th.vix_accel:g}"),
                    Parameter(symbol="L", name="Senior loan ETF", value=f"{th.loan_change} change, threshold {th.loan_move:g}")),
        charts=(ind_chart("Market-stress indicators", SEGMENT_INDICATORS["market_stress"], "flag score"),),
    ))

    # 6. segments
    steps.append(ModelStep(
        key="segments", title="Four segment signals",
        text=("The indicators of each segment are added with their weights. Business cycle, investment and "
              "market behaviour are standardised again; market stress stays a weighted sum of flags. Higher "
              "always reads more cautious."),
        formulas=(r"S_{\text{seg}}=Z\Big(\sum_{k\in\text{seg}}v_k I_k\Big)\ \ (\text{three band segments}),\qquad "
                  r"S_{\text{stress}}=\sum_{k}v_k I_k",),
        parameters=tuple(Parameter(symbol=r"v_k", name=SEGMENT_NAME[s],
                                   value=", ".join(f"{INDICATOR_NAME[nm].lower()} {w[s][nm]:g}" for nm in SEGMENT_INDICATORS[s]))
                         for s in SEGMENTS),
        charts=(Chart(title="Segment signals", x=x, y_label="reading",
                      series=tuple(ChartSeries(name=SEGMENT_NAME[s], y=segs[s], slot=i) for i, s in enumerate(SEGMENTS))),),
    ))

    # 7. binning
    edges = grid(cal)
    cols = tuple(range(1, cal.edges.count + 1))
    steps.append(ModelStep(
        key="binning", title="Binning each reading",
        text=(f"Each segment reading picks one of {cal.edges.count} columns on the grid from "
              f"{cal.edges.low:g} to {cal.edges.high:g}. Column 1 is the lowest reading."),
        formulas=(r"e=\operatorname{linspace}(" + f"{cal.edges.low:g},{cal.edges.high:g},{cal.edges.count}" + r"),\qquad "
                  r"c(S)=1+\#\{k\ge 2:\ e_k\le S\}",),
        parameters=(Parameter(symbol="e", name="Grid", value=", ".join(f"{v:g}" for v in edges)),),
        charts=(Chart(title="Column of each segment, month by month", kind="heatmap", x=x,
                      rows=tuple(SEGMENT_NAME[s] for s in SEGMENTS),
                      z=tuple(tuple(None if c is None else float(c) for c in a.columns[s]) for s in SEGMENTS)),),
    ))

    # 8. kernels
    kcharts, kparams = [], []
    states = tuple(str(sn) for sn in range(N_STATES, 0, -1))
    for s in cal.segments:
        kk = s.kernel
        if isinstance(kk, BandKernel):
            kparams.append(Parameter(symbol=rf"\mathrm{{Bin}}({kk.binomial_n},{kk.binomial_p:g})", name=f"{SEGMENT_NAME[s.name]}: band",
                                     value=f"starts at state {kk.first_state}, moves {kk.step:+d} per column; weight {s.weight:g}"))
        elif isinstance(kk, TailKernel):
            kparams.append(Parameter(symbol=rf"\mathrm{{Bin}}({kk.binomial_n},{kk.binomial_p:g})", name=f"{SEGMENT_NAME[s.name]}: tail",
                                     value=f"on states {kk.first_state} onwards, from column {kk.active_from_column}, "
                                           f"scaled (j-{kk.active_from_column - 1})^{kk.intensity_exponent:.3g}/{kk.intensity_divisor:g}; "
                                           f"weight {s.weight:g}"))
    band = next(s for s in cal.segments if isinstance(s.kernel, BandKernel))
    tail = next((s for s in cal.segments if isinstance(s.kernel, TailKernel)), None)
    for s, title in ((band, "Band kernel (business cycle, investment, behaviour)"), (tail, "Tail kernel (market stress)")):
        if s is None:
            continue
        km = kernel_matrix(s, cal.edges.count)
        kcharts.append(Chart(title=title, kind="heatmap", x=cols, x_label="column", rows=states,
                             z=tuple(_v(km[st - 1]) for st in range(N_STATES, 0, -1)), note="rows: state, 25 at the top"))
    steps.append(ModelStep(
        key="kernels", title="From column to states: the kernels",
        text=("Each column carries a small distribution over the 25 states. For the three band segments it is a "
              "binomial bump that slides two states towards cautious for every column up. For market stress it "
              "is a tail on the cautious states that switches on from column 6 and grows with the column."),
        formulas=(r"K^{\text{band}}_{:,j}=\mathrm{Bin}(n,p)\ \text{on states}\ s_0+\Delta(j-1)\ \text{onwards (overhang folded onto the end states)}",
                  r"K^{\text{tail}}_{:,j}=\mathrm{Bin}(n,p)\ \text{on states}\ 1\ldots\cdot\,\frac{(j-j_0+1)^{\sqrt2}}{11},\qquad j\ge j_0"),
        parameters=tuple(kparams), charts=tuple(kcharts),
    ))

    # 9. the distribution
    last = next((t for t in range(n - 1, -1, -1) if a.distribution[t] is not None), None)
    dist_charts = []
    if last is not None:
        total_w = math.fsum(s.weight for s in cal.segments)
        present = [s for s in cal.segments if a.columns[s.name][last] is not None]
        scale = total_w / math.fsum(s.weight for s in present)
        mass = a.raw_mass[last]
        contrib = [ChartSeries(name=SEGMENT_NAME[s.name],
                               y=_v(kernel_matrix(s, cal.edges.count)[:, a.columns[s.name][last] - 1] * s.weight * scale / mass),
                               slot=SEGMENTS.index(s.name), dash="dot") for s in present]
        dist_charts.append(Chart(title=f"Distribution in {x[last]} and what each segment adds", x=tuple(range(1, N_STATES + 1)),
                                 x_label="state (1 cautious, 25 aggressive)", y_label="probability",
                                 series=(ChartSeries(name="Distribution", y=_v(a.distribution[last]), kind="bar", muted=True),
                                         *contrib)))
    dist_charts.append(Chart(title="The distribution over time", kind="heatmap", x=x, rows=states,
                             z=tuple(tuple(None if d is None else float(d[st - 1]) for d in a.distribution)
                                     for st in range(N_STATES, 0, -1)), note="rows: state, 25 at the top"))
    steps.append(ModelStep(
        key="distribution", title="The 25-state distribution",
        text=("Each segment's column is looked up in its kernel, weighted, and the four are added. A missing "
              f"segment is left out and the others scaled up; a month needs {cal.min_segments} of 4 segments. "
              "The sum is normalised to 1; the reported state is the most likely one, ties to the cautious side."),
        formulas=(r"m_t(b)=\frac{\sum_s w_s}{\sum_{s\ \text{present}}w_s}\sum_{s\ \text{present}}w_s\,K^{s}_{b,\,c_s(t)},\qquad "
                  r"p_t(b)=\frac{m_t(b)}{\sum_{b'}m_t(b')}",
                  r"\text{state}_t=\min\arg\max_b\ p_t(b)"),
        parameters=(Parameter(symbol="w_s", name="Segment weights",
                              value=", ".join(f"{SEGMENT_NAME[s.name].lower()} {s.weight:g}" for s in cal.segments)),
                    Parameter(symbol="", name="Missing segments", value=cal.missing_policy)),
        charts=tuple(dist_charts),
    ))

    assessed = sum(1 for s in a.state if s is not None)
    notes = [f"{name}: {assessed} of {n} months assessed" + (f"; latest {x[last]}: state {a.state[last]}" if last is not None else "") + "."]
    if layer.inputs_missing:
        notes.append("Inputs with no data for this economy: " + ", ".join(names.get(s, (s,))[0] for s in layer.inputs_missing) + ".")
    return ModelCard(
        engine=ENGINE, title="Market Risk Signal",
        summary=(f"Reads {len(needed)} market and macro series per economy, builds eleven indicators in four segments "
                 "(business cycle, investment, market behaviour, market stress), bins each segment reading and "
                 "turns the four into a distribution over 25 risk states, 1 cautious to 25 aggressive, for the "
                 "aggregation layer."),
        engine_version=ENGINE_VERSION, calibration_version=cal.version,
        data=f"datafeed snapshot {panel.snapshot_id} (as of {panel.as_of})",
        economy=EconomyOption(code=code, name=name), economies=tuple(economies),
        inputs=tuple(inputs), steps=tuple(steps),
        outputs=(
            ModelOutputField(key="indicators", name="Eleven indicators", unit="standardised; flags x3",
                             description="Per month."),
            ModelOutputField(key="segments", name="Four segment signals", unit="z-score; stress: weighted flags",
                             description="Per month. Higher reads more cautious."),
            ModelOutputField(key="distribution", name="Risk-state distribution", unit="25 probabilities summing to 1",
                             description="Per month, at zero optimism shift. Read by the aggregation layer."),
            ModelOutputField(key="state", name="Most likely state", unit="1 to 25", description="Per month."),
            ModelOutputField(key="raw_mass", name="Kernel mass before normalising", unit="", description="Per month."),
        ),
        output_charts=(Chart(title=f"{name}: most likely state", x=x, y_label="state (1 cautious, 25 aggressive)",
                             series=(ChartSeries(name="State", y=tuple(None if s is None else float(s) for s in a.state),
                                                 kind="markers", slot=0),)),),
        notes=tuple(notes),
    )
