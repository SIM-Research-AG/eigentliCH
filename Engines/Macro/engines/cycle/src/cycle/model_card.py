"""The model card (``GET /model``): the cycle model explained on one economy's data.

It runs the engine's own functions (``engine.py``) for one economy and keeps what each step
produced, so every chart is a number the model computed, not a re-derivation. Pure: the
service hands in the panel, the calibration and macrofield's output.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

import numpy as np

from . import ENGINE, ENGINE_VERSION
from .contracts import (
    PHASES,
    STATE_COUNT,
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
    phase_of,
)
from .engine import (
    REQUIRED_SERIES,
    MacroOutput,
    annualise,
    capital_saturation,
    economy_contract,
    prepare_inputs,
    reads_macrofield,
    run_economy,
    year_axis,
)

#: Plain names for the series the model reads: (name, unit, description).
INPUTS: dict[str, tuple[str, str, str]] = {
    "production.gdp_nominal": ("GDP, nominal", "bn, local currency",
                               "Gross domestic product at current prices. Annual figure, repeated in every month of its year."),
    "inflation.cpi_yoy": ("Consumer price inflation", "share per year (0.03 = 3%)",
                          "Change of the consumer price index against twelve months before."),
    "debt.corporate_gdp": ("Corporate debt", "share of GDP", "Debt of non-financial companies over GDP."),
    "debt.government_gdp": ("Government debt", "share of GDP", "General government debt over GDP."),
    "debt.household_gdp": ("Household debt", "share of GDP", "Debt of households over GDP."),
    "debt.financial_sector": ("Financial-sector debt", "bn, local currency",
                              "Debt securities issued by the financial sector (BIS)."),
}

GROWTH_INPUTS = {
    "output_growth": "Real output growth (datafeed GDP deflated by CPI)",
    "macrofield_output_growth": "Output growth (Macro Field output Y, current USD)",
    "saturation_change": "Change of capital saturation",
}


def _slot(name: str, cal: Calibration) -> Optional[int]:
    """Each cycle keeps its colour in every chart: its position in the calibration."""
    names = [c.name for c in cal.cycles]
    return names.index(name) % 5 if name in names else None


def _v(x) -> tuple[Optional[float], ...]:
    return tuple(None if v is None or not np.isfinite(v) else float(v) for v in np.asarray(x, dtype=float))


def _num(v: Optional[float], digits: int = 3) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{float(v):.{digits}g}"


def build(panel: Panel, cal: Calibration, code: str, name: str, economies: Sequence[EconomyOption],
          macro: Optional[MacroOutput], horizon: Optional[int]) -> ModelCard:
    annual = annualise(panel, [code], cal.annualisation)
    reads_mf = reads_macrofield(cal)
    observed_axis = year_axis(annual, macro if reads_mf else None)
    observed_until = observed_axis[-1]
    years = year_axis(annual, macro if reads_mf else None, horizon)
    saturation, per_economy = prepare_inputs(annual, cal, macro, years)
    inputs = per_economy[0]
    result = run_economy(years, inputs, saturation[:, 0], cal, code)
    out = economy_contract(code, name, years, result)
    projected_from = observed_until + 1 if years[-1] > observed_until else None
    yrs = tuple(int(y) for y in years)

    # ---- data in -----------------------------------------------------------------
    lookup = {(s.country, s.series_id): s for s in panel.series}
    model_inputs = []
    for key in REQUIRED_SERIES:
        s = lookup.get((code, key))
        label, unit, text = INPUTS[key]
        fills = sorted({sp.source for sp in s.source_spans if sp.source != panel.primary_source}) if s else []
        model_inputs.append(ModelInput(
            key=key, name=label, unit=unit, frequency="monthly axis", description=text,
            source=f"datafeed, {panel.primary_source}" + (f"; gaps filled from {', '.join(fills)}" if fills else ""),
            x=tuple(panel.dates), y=tuple(s.values) if s else tuple(None for _ in panel.dates)))
    mf = (macro or {}).get(code)
    if reads_mf:
        model_inputs.append(ModelInput(
            key="macrofield.Y", name="Output Y (Macro Field)", unit="current USD", frequency="annual",
            source="macrofield engine, latest run", description=(
                "The output path of the three-body model, observed years. The pulse and business "
                "cycles are band-passed from its growth."),
            x=tuple(int(y) for y in mf[0]) if mf else (), y=tuple(mf[1]) if mf else ()))

    steps: list[ModelStep] = []
    ay = tuple(int(y) for y in annual.years)
    col = {k: annual.data[k][:, 0] for k in REQUIRED_SERIES}

    # 1. annual values
    steps.append(ModelStep(
        key="annual", title="From months to years",
        text=("Every series is reduced to one value per calendar year: the December observation "
              "(or, with the mean setting, the average of the twelve months). A year with a missing "
              "December is missing; nothing is filled."),
        formulas=(r"x_t = x_{\text{Dec},\,t}" if cal.annualisation == "year_end"
                  else r"x_t = \tfrac{1}{12}\sum_{m=1}^{12} x_{m,t}",),
        parameters=(Parameter(symbol="", name="Annual value", value=cal.annualisation),),
        charts=(Chart(title="GDP, nominal, December value", x=ay, y_label="bn, local currency",
                      series=(ChartSeries(name="GDP", y=_v(col["production.gdp_nominal"]), kind="bar"),)),
                Chart(title="Consumer price inflation, December value", x=ay, y_label="share per year",
                      series=(ChartSeries(name="CPI inflation", y=_v(col["inflation.cpi_yoy"])),))),
    ))

    # 2. capital saturation
    with np.errstate(divide="ignore", invalid="ignore"):
        fin = col["debt.financial_sector"] / col["production.gdp_nominal"]
    sat = capital_saturation(annual.data)[:, 0]
    steps.append(ModelStep(
        key="saturation", title="Capital saturation",
        text=("Total debt over GDP, the same axis honi publishes. It dates the capital cycle only "
              "for an economy without a historical reset in the calibration."),
        formulas=(r"S_t = D^{\text{corp}}_t + D^{\text{gov}}_t + D^{\text{hh}}_t + \frac{D^{\text{fin}}_t}{Y_t}",),
        charts=(Chart(title="Capital saturation and its parts", x=ay, y_label="share of GDP",
                      series=(ChartSeries(name="Corporate", y=_v(col["debt.corporate_gdp"]), dash="dot"),
                              ChartSeries(name="Government", y=_v(col["debt.government_gdp"]), dash="dot"),
                              ChartSeries(name="Household", y=_v(col["debt.household_gdp"]), dash="dot"),
                              ChartSeries(name="Financial / GDP", y=_v(fin), dash="dot"),
                              ChartSeries(name="Saturation S", y=_v(sat)))),),
    ))

    # 3. growth inputs of the estimated cycles
    estimated = [c for c in cal.cycles if c.kind == "estimated"]
    used = sorted({c.input for c in estimated if c.input})
    formulas = []
    if "macrofield_output_growth" in used:
        formulas.append(r"g_t = \tfrac{1}{2}\left(\ln Y_{t+1} - \ln Y_{t-1}\right)"
                        r"\quad\text{(one-sided at the ends)}")
    if "output_growth" in used:
        formulas += [r"\Delta_t = \ln Y_t - \ln Y_{t-1} - \ln(1+\pi_t)",
                     r"\ell_t = \textstyle\sum_{s\le t}\Delta_s,\qquad g_t = \tfrac{1}{2}(\ell_{t+1}-\ell_{t-1})"]
    if "saturation_change" in used:
        formulas.append(r"g_t = \tfrac{1}{2}(S_{t+1}-S_{t-1})")
    if used:
        steps.append(ModelStep(
            key="growth", title="Growth, the input of the estimated cycles",
            text=("The short cycles are read from the growth of output, on the trailing run of years "
                  "without a gap. Years before a gap carry no phase."),
            formulas=tuple(formulas),
            charts=(Chart(title="Growth input", x=yrs, y_label="log change per year",
                          series=tuple(ChartSeries(name=GROWTH_INPUTS[k], y=_v(inputs[k][0])) for k in used)),),
        ))

    # 4. band-pass and analytic signal
    tracks = {t.spec.name: t for t in result.tracks}
    est_tracks = [tracks[c.name] for c in estimated]
    if est_tracks:
        params, charts = [], []
        for t in est_tracks:
            lo, hi = (t.spec.band if t.spec.band else
                      (t.spec.period_years * (1 - cal.band_fraction), t.spec.period_years * (1 + cal.band_fraction)))
            params.append(Parameter(symbol=rf"[P_{{lo}},P_{{hi}}]_{{\text{{{t.spec.name.replace('_', ' ')}}}}}",
                                    name=f"{t.spec.name.replace('_', ' ')} band, years",
                                    value=f"{lo:g} to {hi:g}; estimated period {_num(t.period_years)}; "
                                          f"sample {t.sample_years:g} years; "
                                          + ("identified" if t.identifiable else "not identified")))
            env = np.asarray(t.amplitude, dtype=float)
            charts.append(Chart(
                title=f"{t.spec.name.replace('_', ' ').capitalize()} cycle: band-passed component",
                x=yrs, y_label="log change per year", projected_from=projected_from,
                series=(ChartSeries(name="Input growth", y=_v(inputs[t.spec.input][0]), muted=True),
                        ChartSeries(name="Cycle component c", y=_v(t.component), slot=_slot(t.spec.name, cal)),
                        ChartSeries(name="Amplitude +A", y=_v(env), dash="dash", slot=_slot(t.spec.name, cal)),
                        ChartSeries(name="Amplitude -A", y=_v(-env), dash="dash", slot=_slot(t.spec.name, cal))),
                note="" if t.identifiable else t.notes[0] if t.notes else ""))
        params.append(Parameter(symbol=r"k_{\min}", name="Periods needed in the sample",
                                value=f"{cal.minimum_periods_in_sample:g}"))
        steps.append(ModelStep(
            key="bandpass", title="Estimated cycles: band-pass filter and phase",
            text=("The Christiano-Fitzgerald filter keeps only the fluctuations whose period lies in the "
                  "cycle's band. The analytic signal of that component (Hilbert transform) gives its "
                  "amplitude and its phase angle, 0 at the peak and plus or minus pi at the trough. The "
                  "dominant period is the peak of the component's spectrum inside the band. A cycle needs "
                  "a sample of at least two of its periods, or it has no position."),
            formulas=(r"a=\frac{2\pi}{P_{hi}},\quad b=\frac{2\pi}{P_{lo}},\quad B_0=\frac{b-a}{\pi},\quad "
                      r"B_j=\frac{\sin(jb)-\sin(ja)}{\pi j}",
                      r"c_t = B_0x_t+\sum_{j=1}^{T-t-1}B_jx_{t+j}+\tilde B_{T-t}\,x_T+\sum_{j=1}^{t-2}B_jx_{t-j}"
                      r"+\tilde B_{t-1}\,x_1",
                      r"z_t = c_t + i\,\mathcal{H}[c]_t,\qquad A_t=|z_t|,\qquad \theta_t=\arg z_t",
                      r"\hat P=\arg\max_{P\in[P_{lo},P_{hi}]}\ \mathrm{Welch}(c)\!\left(1/P\right),"
                      r"\qquad \text{identified iff } T\ge k_{\min}\,\bar P"),
            parameters=tuple(params), charts=tuple(charts),
        ))

    # 5. anchored cycles
    anchored_specs = [c for c in cal.cycles if c.kind != "estimated"]
    if anchored_specs:
        params = []
        formulas = []
        for spec in anchored_specs:
            t = tracks[spec.name]
            nm = spec.name.replace("_", " ")
            if spec.kind in ("anchored_trough", "anchored_peak"):
                year = spec.anchor_years.get(code, spec.anchor_year)
                where = "low" if spec.kind == "anchored_trough" else "high"
                params.append(Parameter(symbol=rf"t_0,\ P\ (\text{{{nm}}})", name=f"{nm}: {where} in, period",
                                        value=f"{_num(year, 6)}, {spec.period_years:g} years"
                                              + ("" if code in spec.anchor_years else " (every economy)")))
            elif code in spec.resets:
                params.append(Parameter(symbol=rf"t_R,\ R,\ P\ (\text{{{nm}}})", name=f"{nm}: reset, turn after, period",
                                        value=f"{spec.resets[code]:g}, {spec.years_into_cycle_at_anchor:g} years, "
                                              f"{spec.period_years:g} years; shape {spec.shape}"))
            else:
                params.append(Parameter(symbol=rf"S^\ast\ (\text{{{nm}}})", name=f"{nm}: saturation that dates it",
                                        value=f"{spec.anchor_saturation:g}; "
                                              + ("anchored" if t.anchored else "not reached: no position")))
        kinds = {c.kind for c in anchored_specs}
        shapes = {c.shape for c in anchored_specs if code in c.resets}
        if kinds & {"anchored_trough", "anchored_peak"}:
            formulas.append(r"\theta_t=\frac{2\pi\,(t-t_0)}{P}+\pi\ \ \text{(low at }t_0\text{)},\qquad"
                            r"\theta_t=\frac{2\pi\,(t-t_0)}{P}\ \ \text{(high at }t_0\text{)}")
        if "fall_rise" in shapes:
            formulas.append(r"\tau=(t-t_R)\bmod P,\qquad \theta_t=\begin{cases}\pi\,\tau/R & \tau<R"
                            r"\\ -\pi+\pi\,(\tau-R)/(P-R) & \tau\ge R\end{cases}"
                            r"\quad\text{(peak at the reset, low }R\text{ years later)}")
        if "rise_fall" in shapes:
            formulas.append(r"\tau=(t-t_R)\bmod P,\qquad \theta_t=\begin{cases}-\pi+\pi\,\tau/R & \tau<R"
                            r"\\ \pi\,(\tau-R)/(P-R) & \tau\ge R\end{cases}"
                            r"\quad\text{(low at the reset, peak }R\text{ years later)}")
        if "anchored_saturation" in kinds and any(code not in c.resets for c in anchored_specs
                                                    if c.kind == "anchored_saturation"):
            formulas.append(r"t^\ast:\ S_{t^\ast}=S^\ast\ \text{(last upward crossing)},\qquad "
                            r"\theta_t=\frac{2\pi\,(t-t^\ast)}{P}")
        steps.append(ModelStep(
            key="anchored", title="Anchored cycles: position from supplied dates",
            text=("The long cycles cannot be estimated from twenty years of data. Their position comes "
                  "from a supplied anchor (a crisis low, a historical reset) and a period, so they are "
                  "defined for every year, including the projected ones. Their amplitude is one: the "
                  "anchor gives the position in the cycle, not its size."),
            formulas=tuple(formulas), parameters=tuple(params),
        ))

    # 5b. every cycle's level, the common picture
    steps.append(ModelStep(
        key="levels", title="Where each cycle stands",
        text=("Each cycle's level is the cosine of its phase angle: +1 at the peak, -1 at the trough. "
              "Band-passed cycles stop where their data stops; anchored ones continue into the projection."),
        formulas=(r"L_{k,t}=\cos\theta_{k,t}",),
        charts=(Chart(title="Cycle levels", x=yrs, y_label="level (peak +1, trough -1)",
                      projected_from=projected_from,
                      series=tuple(ChartSeries(name=t.cycle.replace("_", " "), y=t.level, slot=_slot(t.cycle, cal))
                                   for t in out.cycles)),),
    ))

    # 6. phases
    idx = {p: i for i, p in enumerate(PHASES)}
    steps.append(ModelStep(
        key="phases", title="Phases",
        text="The phase angle is cut into four quarters, in the order a cycle passes through them.",
        formulas=(r"\text{phase}(\theta)=\begin{cases}\text{recovery} & -\pi\le\theta<-\tfrac{\pi}{2}\\"
                  r"\text{expansion} & -\tfrac{\pi}{2}\le\theta<0\\ \text{slowdown} & 0\le\theta<\tfrac{\pi}{2}"
                  r"\\ \text{contraction} & \tfrac{\pi}{2}\le\theta<\pi\end{cases}",),
        charts=(Chart(title="Phase of every cycle, year by year", kind="heatmap", x=yrs,
                      rows=tuple(t.cycle.replace("_", " ") for t in out.cycles),
                      z=tuple(tuple(None if p is None else float(idx[p]) for p in t.phase) for t in out.cycles),
                      categories=PHASES, projected_from=projected_from),),
    ))

    # 7. superposition and synchrony
    members = [t for t in result.tracks if t.spec.in_interference and t.identifiable]
    windows = "; ".join(f"{w.start_year} to {w.end_year} ({', '.join(w.cycles)})" for w in out.synchrony_windows) or "none"
    steps.append(ModelStep(
        key="superposition", title="Superposition and synchrony",
        text=(f"The members ({', '.join(t.spec.name for t in members) or 'none'}) are scaled to unit amplitude and "
              "summed. Alignment says how much they agree: 1 when all point the same way, 0 when they "
              f"cancel. A synchrony window is a run of years in which at least "
              f"{cal.minimum_cycles_in_phase} cycles are within {cal.phase_tolerance_radians:g} rad of "
              f"each other. Windows found: {windows}. The same sum over the anchored members only "
              f"({', '.join(out.anchored_members) or 'none'}), weights re-normalised to their sum, runs through "
              "the projection, where the band-passed members stop (superposition_anchored)."),
        formulas=(r"\tilde c_{k,t}=\frac{c_{k,t}}{\max_s|c_{k,s}|},\qquad "
                  r"\Sigma_t=\frac{\sum_k w_k\,\tilde c_{k,t}}{\sum_k w_k}",
                  r"\alpha_t=\frac{\left|\sum_k w_k\,\tilde c_{k,t}\right|}{\sum_k\left|w_k\,\tilde c_{k,t}\right|}"),
        parameters=(Parameter(symbol=r"\delta", name="Phase tolerance", value=f"{cal.phase_tolerance_radians:g} rad"),
                    Parameter(symbol="m", name="Cycles needed in phase", value=str(cal.minimum_cycles_in_phase)),
                    Parameter(symbol="w_k", name="Weights", value=", ".join(
                        f"{t.spec.name} {t.spec.superposition_weight:g}" for t in members) or "none")),
        charts=(Chart(title="Superposition", x=yrs, y_label="-1 to 1", projected_from=projected_from,
                      series=(ChartSeries(name="Superposition", y=out.superposition),
                              ChartSeries(name="Anchored cycles only", y=out.superposition_anchored, dash="dash",
                                          muted=True))),
                Chart(title="Alignment", x=yrs, y_label="0 (cancel) to 1 (agree)", projected_from=projected_from,
                      series=(ChartSeries(name="Alignment", y=out.alignment),))),
    ))

    # 8. the 25-bin layer
    last = yrs.index(observed_until)
    placed = result.placements[last]
    bins = tuple(range(1, STATE_COUNT + 1))
    w = cal.widths
    kernel_series = tuple(ChartSeries(name=n.replace("_", " "), y=_v(p.distribution), dash="dot", slot=_slot(n, cal))
                          for n, p in placed.items())
    mixed = result.layer[last]
    steps.append(ModelStep(
        key="layer", title="Onto the 25 risk states",
        text=("Each cycle becomes a bell curve over the 25 states (1 cautious, 25 aggressive): centred "
              "where its level puts it, narrow when its position is measured and wide when it is only "
              "supplied or assumed, and leaning towards the way it is moving. The curves are averaged "
              "(never multiplied), so no cycle can wipe out a state another keeps alive."),
        formulas=(r"L_{k,t}=o_k\cos\theta_{k,t},\qquad \mu_{k,t}=1+(25-1)\,\frac{L_{k,t}+1}{2}",
                  r"v_{k,t}=\operatorname{clip}\!\left(\frac{L_{k,t}-L_{k,t-1}}{2\pi/P_k},-1,1\right),\qquad "
                  r"s_{k,t}=\operatorname{clip}(\kappa\,v_{k,t},\,-0.95,\,0.95)",
                  r"\sigma(b)=\begin{cases}w_k(1-s) & b\le\mu\\ w_k(1+s) & b>\mu\end{cases},\qquad "
                  r"p_{k,t}(b)\propto\exp\!\left(-\tfrac12\left(\frac{b-\mu_{k,t}}{\sigma(b)}\right)^{2}\right)",
                  r"p_t(b)=\frac{\sum_k\lambda_k\,p_{k,t}(b)}{\sum_k\lambda_k},\qquad "
                  r"w_k^{\text{measured}}=\operatorname{clip}\!\left(w_0\sqrt{N_{\text{ref}}/N_k},\,w_{\min},\,w_{\max}\right)"),
        parameters=(Parameter(symbol=r"\kappa", name="Lean towards the direction of travel", value=f"{cal.skew_coefficient:g}"),
                    Parameter(symbol=r"w", name="Width, bins (supplied / assumed / marginal)",
                              value=f"{w.supplied:g} / {w.assumed:g} / {w.marginal:g}"),
                    Parameter(symbol=r"w_0,\,N_{\text{ref}},\,w_{\min},\,w_{\max}", name="Width when measured",
                              value=f"{w.measured_base:g}, {w.measured_reference_periods:g} periods, "
                                    f"{w.measured_min:g} to {w.measured_max:g}"),
                    Parameter(symbol=r"o_k", name="Orientation (+1: peak is aggressive)",
                              value=", ".join(f"{c.name} {c.orientation:+d}" for c in cal.cycles)),
                    Parameter(symbol=r"\lambda_k", name="Mixing weights",
                              value=", ".join(f"{c.name} {c.layer_weight:g}" for c in cal.cycles)),
                    Parameter(symbol="", name="Confidence this economy",
                              value=", ".join(f"{k} {v or 'no position'}" for k, v in result.confidence.items()))),
        charts=(Chart(title=f"Each cycle's curve and the mix, {observed_until}", x=bins, x_label="risk state",
                      y_label="probability",
                      series=((ChartSeries(name="Mix", y=_v(mixed), kind="bar", muted=True),) if mixed is not None else ())
                             + kernel_series),
                Chart(title="The mix over time", kind="heatmap", x=yrs, x_label="year",
                      rows=tuple(str(b) for b in reversed(bins)),
                      z=tuple(tuple(None if row is None else float(row[b - 1]) for row in result.layer)
                              for b in reversed(bins)),
                      projected_from=projected_from, note="rows: risk state, 25 at the top")),
    ))

    output_charts = (
        Chart(title="Mean and most likely risk state", x=yrs, y_label="risk state (1 cautious, 25 aggressive)",
              projected_from=projected_from,
              series=(ChartSeries(name="Mean state", y=out.layer_mean_bin),
                      ChartSeries(name="Most likely state", y=tuple(None if v is None else float(v) for v in out.layer_modal_bin),
                                  kind="markers"))),
    )
    current = []
    for t in out.cycles:
        k = next((i for i in range(last, -1, -1) if t.phase[i] is not None), None)
        current.append(f"{t.cycle.replace('_', ' ')}: {t.phase[k] if k is not None else 'no position'}"
                       + (f" ({yrs[k]})" if k is not None else ""))
    return ModelCard(
        engine=ENGINE, title="Cycle Model",
        summary=("Places each economy in five nested cycles (fundamental pulse, business, credit, innovation, "
                 "capital), names the phase each is in, measures how far they move together, and turns "
                 "them into a distribution over 25 risk states, 1 cautious to 25 aggressive, for the "
                 "aggregation layer."),
        engine_version=ENGINE_VERSION, calibration_version=cal.version,
        data=f"datafeed snapshot {panel.snapshot_id} (as of {panel.as_of})"
             + ("; Macro Field output, latest run" if reads_mf else ""),
        economy=EconomyOption(code=code, name=name), economies=tuple(economies),
        inputs=tuple(model_inputs), steps=tuple(steps),
        outputs=(
            ModelOutputField(key="phase", name="Phase", unit="recovery / expansion / slowdown / contraction",
                             description="Per cycle and year."),
            ModelOutputField(key="angle, level", name="Phase angle and level", unit="radians; -1 to +1",
                             description="Per cycle and year: where in the cycle, and its cosine."),
            ModelOutputField(key="years_into_cycle", name="Years into the cycle", unit="years",
                             description="Anchored cycles: years since the anchor."),
            ModelOutputField(key="bin_centre, bin_width, bin_skew", name="Placement on the 25 states", unit="states",
                             description="Per cycle and year: centre, width and lean of its curve."),
            ModelOutputField(key="layer", name="Risk-state distribution", unit="25 probabilities summing to 1",
                             description="Per year: the mix of the cycles' curves. Goes to the aggregation layer."),
            ModelOutputField(key="layer_mean_bin, layer_modal_bin", name="Mean and most likely state", unit="state",
                             description="Per year."),
            ModelOutputField(key="superposition, alignment, synchrony_windows", name="Superposition and synchrony",
                             unit="-1 to 1; 0 to 1; years", description="Per year, and the windows found."),
            ModelOutputField(key="superposition_anchored, anchored_members", name="Superposition, anchored cycles only",
                             unit="-1 to 1", description="Per year, through the projection; weights re-normalised."),
        ),
        output_charts=output_charts,
        notes=tuple(["Current phases: " + "; ".join(current)] + list(out.notes)),
    )
