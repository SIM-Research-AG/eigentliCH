"""The model card (``GET /model``): the aggregation layer explained on one economy.

It reads the latest stored Regime (the three components, the effective blend weights and the
published distribution are all in it) and the three input artefacts it names, and recomputes
the in-between steps with the engine's own functions (``readings``, ``placed_kernels``,
``blend_row``, ``shift_distribution``), so every figure is one the Regime was built from.
Pure: the service hands in the artefacts and the calibration.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from . import ENGINE, ENGINE_VERSION
from .contracts import (
    N_STATES,
    OPTIMISM_SCALES,
    REGIMES,
    Calibration,
    Chart,
    ChartSeries,
    CycleState,
    EconomyOption,
    MacroState,
    MarketRiskSignal,
    ModelCard,
    ModelInput,
    ModelOutputField,
    ModelStep,
    Parameter,
    Regime,
)
from .engine import blend_row, modal_state, placed_kernels, shift_distribution

TILT_TEXT = {
    "saturation_above_band": "saturation above the band",
    "saturation_below_band": "saturation below the band",
    "real_to_financial_below_one": "K_R / K_I below one",
    "unsecured_rising": "unsecured ratio rising", "unsecured_falling": "unsecured ratio falling",
    "interference_negative": "cycles interfere negatively", "interference_positive": "cycles interfere positively",
    "capital_overdue": "past the capital reordering point", "innovation_approaching_trough": "innovation trough ahead",
}


def _v(x) -> tuple[Optional[float], ...]:
    return tuple(None if v is None or not math.isfinite(v) else float(v) for v in np.asarray(x, dtype=float))


def _row(d) -> np.ndarray:
    return np.asarray(d, dtype=float)


def build(regime: Regime, mrs: MarketRiskSignal, cycle: CycleState, macro: MacroState, cal: Calibration,
          code: str, economies: Sequence[EconomyOption]) -> ModelCard:
    e = regime.economy(code)
    me = next(x for x in mrs.economies if x.code == code)
    ce = next(x for x in cycle.economies if x.code == code)
    ma = next(x for x in macro.economies if x.code == code)
    t_cal, k_cal, b, opt, rd = cal.tilts, cal.kernels, cal.blend, cal.optimism, cal.reading
    dates = tuple(regime.dates)
    years = tuple(int(y) for y in e.years)

    # ---- data in: what the three engines hand over ------------------------------------
    grid_b = np.arange(1, N_STATES + 1)
    mrs_state = tuple(None if d is None else float(modal_state(_row(d))) for d in me.distribution)
    cyc_mean = tuple(None if d is None else float((grid_b * _row(d)).sum()) for d in ce.layer)
    inputs = (
        ModelInput(key="mrs.state", name="Market risk signal, most likely state", unit="state 1 to 25",
                   frequency="monthly", source=f"mrs, artefact {mrs.artefact_id}",
                   description="The market half: mrs's 25-state distribution per month, at zero shift.",
                   x=tuple(mrs.dates), y=mrs_state),
        ModelInput(key="cycle.layer_mean_bin", name="Cycle layer, mean state", unit="state 1 to 25",
                   frequency="annual", source=f"cycle, artefact {cycle.artefact_id}",
                   description="The cycle model's own 25-state layer per year.",
                   x=tuple(int(y) for y in cycle.years), y=cyc_mean),
        ModelInput(key="cycle.superposition", name="Cycle interference", unit="-1 to 1", frequency="annual",
                   source=f"cycle, artefact {cycle.artefact_id}",
                   description="Superposition of the cycles; one of the macro tilts.",
                   x=tuple(int(y) for y in cycle.years), y=tuple(ce.superposition)),
        ModelInput(key="macrofield.saturation", name="Capital saturation", unit="share of GDP", frequency="annual",
                   source=f"macrofield, artefact {macro.artefact_id}", description="The saturation axis.",
                   x=tuple(int(y) for y in ma.years), y=tuple(ma.inputs.saturation)),
        ModelInput(key="macrofield.real_to_financial", name="Real over financial capital", unit="K_R / K_I",
                   frequency="annual", source=f"macrofield, artefact {macro.artefact_id}",
                   description="Below one, financial capital outweighs real capital.",
                   x=tuple(int(y) for y in ma.years), y=tuple(ma.diagnostics.real_to_financial)),
        ModelInput(key="macrofield.unsecured_ratio", name="Unsecured ratio", unit="multiple of output",
                   frequency="annual", source=f"macrofield, artefact {macro.artefact_id}",
                   description="Financial value the productive economy does not cover.",
                   x=tuple(int(y) for y in ma.years), y=tuple(ma.diagnostics.unsecured_ratio)),
    )

    steps: list[ModelStep] = []
    c = t_cal.coefficients

    # 1. macro tilts -> five regime weights
    weight_series = tuple(ChartSeries(name=r, y=tuple(None if w is None else float(w[r]) for w in e.macro_weights), slot=i)
                          for i, r in enumerate(REGIMES))
    last_i = max((i for i, w in enumerate(e.macro_weights) if w is not None), default=None)
    tilt_note = ""
    if last_i is not None and e.tilts[last_i]:
        tilt_note = f" In {years[last_i]}: " + "; ".join(
            f"{TILT_TEXT.get(k, k)} ({'cautious' if v.get('crisis', 0) else 'aggressive'} "
            f"{max(abs(v.get('crisis', 0)), abs(v.get('boom', 0))):.3g})" for k, v in e.tilts[last_i].items()) + "."
    steps.append(ModelStep(
        key="tilts", title="Macro state to five regime weights",
        text=("Five regimes, crisis to boom, start with equal weight. The macro state moves weight to the "
              "cautious end (saturation above the band, K_R/K_I below one, a rising unsecured ratio, negative "
              "cycle interference, years past the capital reordering point, the innovation trough ahead) or to "
              "the aggressive end (the reverse of the first four). A tilt lands fully on crisis (boom) and "
              f"{t_cal.adjacent_share:g} of it on contraction (expansion). Weights are clipped at zero and "
              "normalised." + tilt_note),
        formulas=(r"w_r=\beta+\sum_{\tau}\Delta_{\tau,r},\qquad \Delta_{\tau,\text{crisis}}=a_\tau\,x_\tau,\quad "
                  r"\Delta_{\tau,\text{contraction}}=\gamma\,a_\tau\,x_\tau\quad(\text{cautious tilts, mirrored for aggressive})",
                  r"x_{\text{sat}}=\sigma-\sigma_{hi},\quad x_{\rho}=1-K^R/K^I,\quad x_{U}=\Delta U,\quad "
                  r"x_{\Sigma}=|\Sigma|\,\big(1+g(\alpha-0.5)\big),\quad x_{\text{cap}}=\tfrac{t-t_{\text{cap}}}{10},\quad "
                  r"x_{\text{inn}}=\tfrac{W-(t_{\text{inn}}-t)}{10}",
                  r"\hat w_r=\frac{\max(w_r,0)}{\sum_{r'}\max(w_{r'},0)}"),
        parameters=(Parameter(symbol=r"\beta", name="Starting weight", value=f"{c['base']:g}"),
                    Parameter(symbol=r"a_\tau", name="Tilt strengths",
                              value=", ".join(f"{k.replace('_', ' ')} {v:g}" for k, v in c.items() if k != "base")),
                    Parameter(symbol=r"\gamma", name="Share on the adjacent regime", value=f"{t_cal.adjacent_share:g}"),
                    Parameter(symbol=r"[\sigma_{lo},\sigma_{hi}]", name="Saturation band",
                              value=f"{t_cal.band_lower:g} to {t_cal.band_upper:g}"),
                    Parameter(symbol="W", name="Innovation window", value=f"{t_cal.innovation_window_years:g} years")),
        charts=(Chart(title="Five regime weights, year by year", x=years, y_label="weight",
                      series=weight_series),),
    ))

    # 2. kernels -> macro layer
    placed = placed_kernels(k_cal)
    bins = tuple(range(1, N_STATES + 1))
    states_desc = tuple(str(s) for s in range(N_STATES, 0, -1))
    steps.append(ModelStep(
        key="macro_layer", title="Regime weights onto the 25 states",
        text=("Each regime owns a kernel on the axis: crisis piled on the cautious states, boom its mirror on the "
              "aggressive ones, the three between symmetric. The macro layer is the weighted sum."),
        formulas=(r"\text{MACRO}_t(b)=\sum_{r}\hat w_{r,t}\,k_r(b)",),
        parameters=tuple(Parameter(symbol=rf"k_{{\text{{{r}}}}}", name=f"{r} kernel starts at state",
                                   value=str(k_cal.placement[r])) for r in REGIMES),
        charts=(Chart(title="The five kernels", x=bins, x_label="state (1 cautious, 25 aggressive)", y_label="weight",
                      series=tuple(ChartSeries(name=r, y=_v(placed[r]), slot=i) for i, r in enumerate(REGIMES))),
                Chart(title="The macro layer, year by year", kind="heatmap", x=years, rows=states_desc,
                      z=tuple(tuple(None if row is None else float(row[s - 1]) for row in e.macro_layer)
                              for s in range(N_STATES, 0, -1)), note="rows: state, 25 at the top")),
    ))

    # 3. blend
    t_last = max((t for t in range(len(dates)) if e.distribution[t] is not None), default=None)
    blend_charts = []
    if t_last is not None:
        i = e.years.index(e.macro_year[t_last])
        mac = _row(e.macro_layer[i])
        mkt = _row(e.market[t_last])
        cyc = None if e.cycle_layer[i] is None else _row(e.cycle_layer[i])
        blended = blend_row(mac, mkt, cyc, b.macro, b.cycle)
        wm, wk, wc = e.weight_macro[t_last], e.weight_market[t_last], e.weight_cycle[t_last]
        blend_charts.append(Chart(
            title=f"What each half contributes, {dates[t_last]}", x=bins, x_label="state", y_label="probability",
            series=(ChartSeries(name="Blend", y=_v(blended.distribution), kind="bar", muted=True),
                    ChartSeries(name=f"Macro x {wm:.3g}", y=_v(mac / mac.sum() * wm), slot=0, dash="dot"),
                    ChartSeries(name=f"Market x {wk:.3g}", y=_v(mkt / mkt.sum() * wk), slot=1, dash="dot"),
                    *((ChartSeries(name=f"Cycle x {wc:.3g}", y=_v(cyc / cyc.sum() * wc), slot=2, dash="dot"),)
                      if cyc is not None and wc else ()))))
    steps.append(ModelStep(
        key="blend", title="Blending macro, market and cycles",
        text=("Per month, the macro layer and the market risk signal are mixed, and the cycle layer is added "
              "with its own share. The annual parts hold for the months of their year"
              + (f", and may be carried up to {cal.carry_months} months past it" if cal.carry_months else "")
              + ". A year without a cycle layer drops that term and re-weights."),
        formulas=(r"B_t=(1-c)\big[m\,\text{MACRO}_{y(t)}+(1-m)\,\text{MRS}_t\big]+c\,\text{CYCLE}_{y(t)}",),
        parameters=(Parameter(symbol="m", name="Macro against market", value=f"{b.macro:g}"),
                    Parameter(symbol="c", name="Cycle share", value=f"{b.cycle:g}"),
                    Parameter(symbol="", name="Carry past the last year", value=f"{cal.carry_months} months")),
        charts=tuple(blend_charts),
    ))

    # 4. optimism
    shift = regime.provenance.optimism_shift
    opt_charts = []
    if t_last is not None:
        published = _row(e.distribution[t_last])
        opt_charts.append(Chart(
            title=f"Before and after the {regime.optimism_scale} shift, {dates[t_last]}", x=bins, x_label="state",
            y_label="probability",
            series=(ChartSeries(name="Blend", y=_v(blended.distribution), muted=True),
                    ChartSeries(name=f"Published ({regime.optimism_scale})", y=_v(published), kind="bar", slot=0))))
        opt_charts.append(Chart(
            title="The same blend at every optimism level", x=bins, x_label="state", y_label="probability",
            series=tuple(ChartSeries(name=lvl, y=_v(shift_distribution(blended.distribution, opt.shift(lvl), opt.keep_tail)),
                                     slot=k) for k, lvl in enumerate(OPTIMISM_SCALES))))
    steps.append(ModelStep(
        key="optimism", title="Optimism",
        text=(f"The optimism level moves the blended distribution along the axis. The {opt.keep_tail} most cautious "
              "states keep their mass, so the crisis regime stays alive at every level; the rest moves, and mass "
              "past the top piles on state 25. A fractional shift mixes the two neighbouring whole shifts."),
        formulas=(r"B^{\text{tail}}=B\cdot\mathbb{1}[b\le k],\qquad B^{\text{body}}=B-B^{\text{tail}}",
                  r"P=\frac{(1-f)\,T_{\lfloor s\rfloor}B^{\text{body}}+f\,T_{\lfloor s\rfloor+1}B^{\text{body}}+B^{\text{tail}}}{\sum(\cdot)},"
                  r"\qquad f=s-\lfloor s\rfloor"),
        parameters=(Parameter(symbol="k", name="States kept in place", value=str(opt.keep_tail)),
                    Parameter(symbol="s", name="Shift per level (states)",
                              value=", ".join(f"{lvl} {opt.shift(lvl):+.3g}" for lvl in OPTIMISM_SCALES)),
                    Parameter(symbol="", name="This Regime", value=f"{regime.optimism_scale}, shift {shift:+.3g}")),
        charts=tuple(opt_charts),
    ))

    # 5. reading the distribution
    steps.append(ModelStep(
        key="reading", title="Reading the distribution",
        text=("The published state is the state nearest the probability-weighted mean; the most likely state is "
              f"reported beside it. The crisis tail is the mass on the {rd.tail_bins} most cautious states; the "
              "five-regime split sums the states each regime covers; separate modes (a swing market) are found by "
              "their prominence."),
        formulas=(r"\bar b_t=\sum_b b\,P_t(b),\qquad \text{state}_t=\operatorname{round}(\bar b_t),\qquad "
                  r"\text{tail}_t=\sum_{b\le " + str(rd.tail_bins) + r"}P_t(b)",),
        parameters=(Parameter(symbol="", name="Five-regime states",
                              value=", ".join(f"{r} {lo}-{hi}" for r, (lo, hi) in rd.five_regime_bins.items())),
                    Parameter(symbol="", name="Mode prominence", value=f"{rd.mode_prominence:g}")),
        charts=(Chart(title="The published distribution over time", kind="heatmap", x=dates, rows=states_desc,
                      z=tuple(tuple(None if d is None else float(d[s - 1]) for d in e.distribution)
                              for s in range(N_STATES, 0, -1)), note="rows: state, 25 at the top"),),
    ))

    cur = e.current
    notes = []
    if cur is not None:
        notes.append(f"{e.name} {cur.date}: state {cur.state} (most likely {cur.modal_state}), crisis tail "
                     f"{cur.crisis_tail:.2f}, {cur.shape}; five regimes "
                     + ", ".join(f"{k} {v:.2f}" for k, v in cur.five_regime.items()) + ".")
    notes.append(f"Regime {regime.regime_id} ({regime.optimism_scale}), built from mrs {mrs.artefact_id}, "
                 f"cycle {cycle.artefact_id}, macrofield {macro.artefact_id}.")
    notes += list(e.notes)
    return ModelCard(
        engine=ENGINE, title="Aggregation layer (the Regime)",
        summary=("Combines the three model engines into the Regime, the combined market risk signal: a macro half "
                 "from macrofield's state tilted across five regimes, the market half from mrs, and the cycle "
                 "layer, blended per month, moved by the optimism level, and published as a 25-state distribution "
                 "with a regime id every downstream engine binds to."),
        engine_version=ENGINE_VERSION, calibration_version=cal.version,
        data=f"Regime {regime.regime_id} ({regime.optimism_scale}) on datafeed snapshot {regime.provenance.snapshot_id}",
        economy=EconomyOption(code=code, name=e.name), economies=tuple(economies),
        inputs=inputs, steps=tuple(steps),
        outputs=(
            ModelOutputField(key="regime_id", name="Regime id", unit="RGM- and a hash",
                             description="Identical inputs, optimism, calibration and version give the identical id."),
            ModelOutputField(key="distribution", name="Regime distribution", unit="25 probabilities summing to 1",
                             description="Per economy and month, and per market blend. Read by fmre, pcp and scenario."),
            ModelOutputField(key="state, modal_state", name="Published and most likely state", unit="1 to 25",
                             description="Per month."),
            ModelOutputField(key="current", name="Current reading", unit="",
                             description="Crisis tail, five-regime split, shape, phase and saturation."),
            ModelOutputField(key="macro_layer, cycle_layer, market, weights, tilts", name="Components", unit="",
                             description="Everything the blend was made from, for the contributions endpoint."),
        ),
        output_charts=(Chart(title=f"{e.name}: published and most likely state", x=dates,
                             y_label="state (1 cautious, 25 aggressive)",
                             series=(ChartSeries(name="State", y=tuple(None if s is None else float(s) for s in e.state), slot=0),
                                     ChartSeries(name="Most likely", y=tuple(None if s is None else float(s) for s in e.modal_state),
                                                 kind="markers", slot=1))),),
        notes=tuple(notes),
    )
