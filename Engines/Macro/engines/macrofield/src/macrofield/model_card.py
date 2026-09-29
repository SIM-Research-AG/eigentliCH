"""The model card (``GET /model``): the three-body model explained on one economy.

The fit of the equations of motion takes about thirty seconds for sixteen economies, so the card
does not re-run it: it reads the latest stored run (``MacroState``), which already holds every
intermediate the engine computed, the assembled inputs, the identities, the capital
normalisation, the fit, the simulated path, the diagnostics, the phases and the projection.
Pure: the service hands in the artefact and its calibration.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from . import ENGINE, ENGINE_VERSION
from .contracts import (
    PHASE_LABELS,
    Calibration,
    Chart,
    ChartSeries,
    EconomyOption,
    EconomyState,
    MacroState,
    ModelCard,
    ModelInput,
    ModelOutputField,
    ModelStep,
    Parameter,
)

PHASE_NAMES = tuple(f"{k} {v}" for k, v in sorted(PHASE_LABELS.items()))
STIMULUS_SOURCE = {"fiscal_balance": "the government budget deficit (IMF)",
                   "net_new_credit": "net new credit to the non-financial sector (BIS)"}


def _g(v, digits: int = 3) -> str:
    return "n/a" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{float(v):.{digits}g}"


def _ratio(a: Sequence[Optional[float]], b: Sequence[Optional[float]]) -> tuple[Optional[float], ...]:
    return tuple(None if x is None or y in (None, 0) else float(x) / float(y) for x, y in zip(a, b))


def build(state: MacroState, e: EconomyState, cal: Calibration, economies: Sequence[EconomyOption]) -> ModelCard:
    yrs = tuple(int(y) for y in e.years)
    inp, obs, ids, dia, fit, norm = e.inputs, e.observed, e.identities, e.diagnostics, e.fit, e.capital_normalisation
    th = cal.phases
    stim = STIMULUS_SOURCE.get(str(e.stimulus_proxy), str(e.stimulus_proxy or "the stimulus proxy"))

    # ---- data in -------------------------------------------------------------------
    src = f"macrofield snapshot {state.provenance.snapshot_id} (World Bank, BIS, Penn World Table, IMF, Bundesbank, JST)"
    extended = [y for y, x in zip(yrs, inp.real_capital_ratio_extended) if x]
    inputs = [
        ModelInput(key="Y", name="GDP", unit="USD, current prices", frequency="annual", source=src,
                   description="Output Y, gross domestic product at market exchange rates.", x=yrs, y=tuple(obs.Y)),
        ModelInput(key="credit_ratio_published", name="Total credit to the non-financial sector", unit="share of GDP",
                   frequency="annual", source=src, description="BIS: credit to households, companies and government.",
                   x=yrs, y=tuple(inp.credit_ratio_published)),
        ModelInput(key="real_capital_ratio", name="Capital stock over GDP", unit="ratio", frequency="annual", source=src,
                   description="Penn World Table capital stock over output"
                               + (f"; extended past the last published year ({extended[0]} to {extended[-1]})" if extended else "")
                               + ".", x=yrs, y=tuple(inp.real_capital_ratio)),
        ModelInput(key="p_s", name="Savings rate", unit="share of GDP", frequency="annual", source=src,
                   description="Gross savings over GDP.", x=yrs, y=tuple(inp.p_s)),
        ModelInput(key="stimulus_share", name="Stimulus", unit="share of GDP", frequency="annual", source=src,
                   description=f"The exogenous injection S, read from {stim}.", x=yrs, y=tuple(inp.stimulus_share)),
        ModelInput(key="population_growth", name="Population growth", unit="share per year", frequency="annual",
                   source=src, description="Year-on-year change of the population.", x=yrs, y=tuple(inp.population_growth)),
    ]
    if any(v is not None for v in inp.commercial_bank_share):
        inputs.append(ModelInput(key="commercial_bank_share", name="Commercial-bank share", unit="share",
                                 frequency="annual", source=src,
                                 description="Loans to domestic non-banks over the bank balance sheet.",
                                 x=yrs, y=tuple(inp.commercial_bank_share)))

    steps: list[ModelStep] = []

    # 1. assembling the three bodies
    steps.append(ModelStep(
        key="assembly", title="The three bodies: output, real capital, financial capital",
        text=("Output Y is GDP. Financial capital K_I follows the credit ratio, raised by the credit uplift to "
              "the saturation axis. Real capital K_R follows the capital-output ratio. Both capital stocks are "
              "put on one common scale, so that the highest capital-output ratio in the window maps to the "
              "target. The stimulus S is a share of output."),
        formulas=(r"\sigma_t = u\,c_t,\qquad K^I_t=\lambda\,\sigma_t\,Y_t,\qquad K^R_t=\lambda\,(K/Y)_t\,Y_t",
                  r"\lambda=\frac{\kappa}{\max_t (K/Y)_t},\qquad S_t=s_t\,Y_t"),
        parameters=(Parameter(symbol="u", name="Credit uplift", value=f"{cal.credit_uplift:g}"),
                    Parameter(symbol=r"\kappa", name="Capital target", value=f"{norm.target:g}"),
                    Parameter(symbol=r"\lambda", name="Common capital scale",
                              value=f"{norm.scale:.4g} (highest K/Y {norm.observed_max_ratio:.3g} in {norm.observed_max_year})"),
                    Parameter(symbol="s", name="Stimulus proxy", value=stim)),
        charts=(Chart(title="Saturation axis", x=yrs, y_label="share of GDP",
                      series=(ChartSeries(name="Credit / GDP, published", y=tuple(inp.credit_ratio_published), muted=True),
                              ChartSeries(name="Saturation (uplifted)", y=tuple(inp.saturation), slot=0))),
                Chart(title="The three bodies", x=yrs, y_label="USD, current prices",
                      series=(ChartSeries(name="Y output", y=tuple(obs.Y), slot=0),
                              ChartSeries(name="K_R real capital", y=tuple(obs.K_R), slot=1),
                              ChartSeries(name="K_I financial capital", y=tuple(obs.K_I), slot=2)))),
    ))

    # 2. identities
    d = cal.derivative
    steps.append(ModelStep(
        key="identities", title="The identities: parameters read off the data",
        text=("Four parameters of the equations are defined by the observed path itself: the investment "
              "share r, the share of savings that flows into financial capital alpha, the achievable return "
              "p_p and the population term p_b. Time derivatives are smoothed with a Savitzky-Golay filter."),
        formulas=(r"r_t=1-\frac{K^R_t}{Y_t},\qquad \alpha_t=\frac{\dot Y_t}{p_{s,t}\,Y_t},\qquad "
                  r"p_{p,t}=\frac{\dot Y_t+\dot K^R_t}{K^R_t},\qquad p_{b,t}=g(\text{population})_t",
                  r"\dot x_t:\ \text{Savitzky-Golay derivative, window } w,\ \text{polynomial order } q"),
        parameters=(Parameter(symbol="w", name="Derivative window", value=f"{d.window_years} years"),
                    Parameter(symbol="q", name="Polynomial order", value=str(d.polynomial_order)),
                    Parameter(symbol="", name="p_b from", value=cal.p_b_source.replace("_", " "))),
        charts=tuple(Chart(title=t, x=yrs, series=(ChartSeries(name=n, y=tuple(v), slot=k),))
                     for k, (t, n, v) in enumerate((("Investment share r", "r", ids.r),
                                                    ("Savings share to financial capital alpha", "alpha", ids.alpha),
                                                    ("Achievable return p_p", "p_p", ids.p_p),
                                                    ("Population term p_b", "p_b", ids.p_b)))),
    ))

    # 3. equations and fit
    fp, se = fit.free_parameters, fit.standard_errors
    labels = {"p_p_scale": ("c_{p_p}", "Correction on p_p"), "p_b_scale": ("c_{p_b}", "Correction on p_b"),
              "alpha_scale": (r"c_{\alpha}", "Correction on alpha"), "savings_scale": ("c_{s}", "Scale on the savings rate"),
              "stimulus_scale": ("c_{S}", "Scale on the stimulus"), "initial_output": ("Y_0", "Initial output"),
              "initial_real": ("K^R_0", "Initial real capital"), "initial_financial": ("K^I_0", "Initial financial capital")}
    fparams = [Parameter(symbol=labels.get(k, (k, k))[0], name=labels.get(k, (k, k))[1],
                         value=f"{_g(v, 4)} ± {_g(se.get(k), 2)}; {fit.identifiability.get(k, '')}") for k, v in fp.items()]
    fparams.append(Parameter(symbol="", name="Fit", value=(
        f"{'converged' if fit.converged else 'not converged'}; integrates at {fit.integration_accuracy} tolerance; "
        "RMS relative residual " + ", ".join(f"{k} {_g(v, 2)}" for k, v in fit.residuals.items()))))
    sim = e.simulated
    fit_charts = tuple(Chart(title=f"{label}: observed and simulated", x=yrs, y_label="USD, current prices",
                             series=(ChartSeries(name="observed", y=tuple(getattr(obs, key)), muted=True),
                                     ChartSeries(name="simulated", y=tuple(getattr(sim, key)) if sim else tuple(None for _ in yrs),
                                                 slot=k)))
                       for k, (key, label) in enumerate((("Y", "Output Y"), ("K_R", "Real capital K_R"),
                                                         ("K_I", "Financial capital K_I"))))
    steps.append(ModelStep(
        key="dynamics", title="Equations of motion, calibrated to the path",
        text=("The three bodies move by these equations. Eight numbers are fitted by least squares in log "
              "space: a correction on each identity (one means the identity holds as defined), a scale on the "
              "savings rate and on the stimulus, and the starting state. How far a correction departs from one "
              "measures how far the definitions and the equations disagree on this economy."
              + (" The investment share is bounded at zero: once real capital reaches output, financial "
                 "capital stops flowing into real capital instead of the written 1 - K_R/Y turning "
                 "negative, which would drive output to zero in finite time." if cal.share_form == "bounded"
                 else "")),
        formulas=(r"\dot Y=(p_b-p_s)\,Y+\dot K^R-p_p\,K^R+S",
                  r"\dot K^R=(1-\alpha)\,p_s\,Y+p_p\,K^R+r\,K^I",
                  r"\dot K^I=\alpha\,p_s\,Y+p_p\,K^I-r\,K^I+S",
                  *((r"r=\max\!\left(0,\ 1-\frac{K^R}{Y}\right)\quad\text{(bounded investment share, TB-27)}",)
                    if cal.share_form == "bounded" else ()),
                  r"\min_{\theta}\ \sum_t\sum_{x\in\{Y,K^R,K^I\}}\left(\ln x^{\text{sim}}_t(\theta)-\ln x^{\text{obs}}_t\right)^2"),
        parameters=tuple(fparams), charts=fit_charts,
    ))

    # 4. diagnostics
    steps.append(ModelStep(
        key="diagnostics", title="Diagnostics of the state",
        text=("Algebraic functions of the observed state, available whether or not the fit integrates. The "
              "unsecured ratio is financial value that the productive economy does not cover; when its gap "
              f"accelerates for {th.unsecured_acceleration_periods} years running, that is the Phase 3 signature."),
        formulas=(r"C_t=\frac{K^R_t+K^I_t}{Y_t},\qquad \rho_t=\frac{K^R_t}{K^I_t},\qquad U_t=\frac{K^R_t+K^I_t-Y_t}{Y_t}",),
        charts=(Chart(title="Capital saturation and unsecured ratio", x=yrs, y_label="multiple of output",
                      series=(ChartSeries(name="Capital saturation C", y=tuple(dia.capital_saturation), slot=0),
                              ChartSeries(name="Unsecured ratio U", y=tuple(dia.unsecured_ratio), slot=1))),
                Chart(title="Real over financial capital", x=yrs, y_label="K_R / K_I",
                      series=(ChartSeries(name="K_R / K_I", y=tuple(dia.real_to_financial), slot=2),))),
    ))

    # 5. phases
    ph = e.phase_history
    band = th.balanced_band
    if ph is not None:
        hx = tuple(int(y) for y in ph.years)
        const = lambda v: tuple(float(v) for _ in hx)  # noqa: E731
        phase_charts = (
            Chart(title="Saturation over the whole history, with the phase cut-offs", x=hx, y_label="share of GDP",
                  series=(ChartSeries(name="Saturation", y=tuple(ph.saturation), slot=0),
                          ChartSeries(name=f"Foundation ceiling {th.foundation_saturation_ceiling:g}",
                                      y=const(th.foundation_saturation_ceiling), muted=True, dash="dot"),
                          ChartSeries(name=f"Balanced band {band.lower:g}", y=const(band.lower), muted=True, dash="dash"),
                          ChartSeries(name=f"Phase 3 ceiling {th.optimisation_saturation_ceiling:g}",
                                      y=const(th.optimisation_saturation_ceiling), muted=True, dash="dot"))),
            Chart(title="Phase, year by year", kind="heatmap", x=hx, rows=("phase",),
                  z=(tuple(None if p is None else float(p) - 1 for p in ph.phase),), categories=PHASE_NAMES),
        )
    else:
        phase_charts = ()
    steps.append(ModelStep(
        key="phases", title="The four phases",
        text=("Each year is classified on the saturation axis and the capital ratios, first matching rule wins. "
              "Once in Saturation and reordering, an economy stays there until saturation falls back to the "
              "Foundation level."),
        formulas=(r"\text{phase}_t=\begin{cases}4\ \text{Saturation} & \rho_t<\rho^\ast\ \text{or}\ \sigma_t\ge\sigma_3\\"
                  r"1\ \text{Foundation} & \sigma_t<\sigma_1\\ 2\ \text{Build-up} & K^R_t/Y_t<\kappa_2\\"
                  r"3\ \text{Optimisation} & \text{otherwise}\end{cases}",
                  r"\text{latch: } \text{phase}_{t-1}=4\ \wedge\ \sigma_t\ge\sigma_1\ \Rightarrow\ \text{phase}_t=4"),
        parameters=(Parameter(symbol=r"\sigma_1", name="Foundation ceiling", value=f"{th.foundation_saturation_ceiling:g}"),
                    Parameter(symbol=r"\sigma_3", name="Phase 3 ceiling", value=f"{th.optimisation_saturation_ceiling:g}"),
                    Parameter(symbol=r"\rho^\ast", name="K_R / K_I below which saturated",
                              value=f"{th.saturation_real_to_financial_ceiling:g}"),
                    Parameter(symbol=r"\kappa_2", name="K_R / Y below which a production economy",
                              value=f"{th.production_economy_real_capital_ceiling:g}"),
                    Parameter(symbol="", name="Balanced band", value=f"{band.lower:g} to {band.upper:g}"),
                    Parameter(symbol="", name="Latch over the whole history", value=str(th.latch_from_full_history))),
        charts=phase_charts,
    ))

    # 6. projection
    pr = e.projection
    if pr is not None and pr.status == "ok" and ph is not None:
        steps.append(_projection_step(e, pr, ph, cal))

    cur = e.current
    notes = [f"{e.name} {cur.year}: phase {cur.phase} {cur.phase_label}; saturation {cur.saturation:.3g} "
             f"({'inside' if cur.in_balanced_band else 'outside'} the balanced band); K_R/K_I {cur.real_to_financial:.3g}; "
             f"unsecured ratio {cur.unsecured_ratio:.3g}."] + list(e.notes)
    return ModelCard(
        engine=ENGINE, title="Macro Field (three-body model)",
        summary=("Models each economy as three coupled bodies, output Y, real capital K_R and financial capital "
                 "K_I, whose equations of motion are calibrated to the published data. It reports capital "
                 "saturation, which of four phases the economy is in, the diagnostics the model defines, and a "
                 "forward projection, for the aggregation layer and the cycle model."),
        engine_version=ENGINE_VERSION, calibration_version=cal.version,
        data=f"latest run {state.artefact_id} on {src}",
        economy=EconomyOption(code=e.code, name=e.name), economies=tuple(economies),
        inputs=tuple(inputs), steps=tuple(steps),
        outputs=(
            ModelOutputField(key="observed, simulated", name="The three bodies", unit="USD, current prices",
                             description="Y, K_R and K_I per year, observed and as the calibrated model reproduces them."),
            ModelOutputField(key="identities, fit", name="Identities and fit", unit="",
                             description="r, alpha, p_p, p_b per year; fitted corrections with their errors."),
            ModelOutputField(key="diagnostics", name="Diagnostics", unit="multiples of output",
                             description="Capital saturation, K_R/K_I, unsecured ratio, phase and balanced band per year."),
            ModelOutputField(key="current", name="Current state", unit="",
                             description="Phase and saturation in the last observed year. Read by aggregation."),
            ModelOutputField(key="projection", name="Projection", unit="",
                             description="The path forward, phase transitions ahead and the Phase IV resolutions. "
                                         "Its horizon sets how far the cycle model projects."),
        ),
        output_charts=(Chart(title=f"{e.name}: capital saturation and K_R / K_I", x=yrs, y_label="multiple",
                             series=(ChartSeries(name="Capital saturation C", y=tuple(dia.capital_saturation), slot=0),
                                     ChartSeries(name="K_R / K_I", y=tuple(dia.real_to_financial), slot=2))),),
        notes=tuple(notes),
    )


def _projection_step(e: EconomyState, pr, ph, cal: Calibration) -> ModelStep:
    """The projection step. From calibration 1.4.0 (R-005) the charts show the path to the
    display year (2039) with its parts marked, and a second pair shows the full horizon (2080,
    lower confidence after the display year)."""
    s = pr.settings
    trans = "; ".join(f"{t.year}: phase {t.from_phase} to {t.to_phase}" + (" (extrapolated)" if t.extrapolated else "")
                      for t in pr.transitions) or "none within the horizon"
    params = [Parameter(symbol="H", name="Horizon", value=f"{s.get('horizon', pr.requested_horizon)} years"),
              Parameter(symbol="", name="Parameters", value=str(s.get("parameter_mode", "")).replace("_", " ")),
              Parameter(symbol="", name="Integrated / extrapolated years",
                        value=f"{pr.integrated_years} / {sum(pr.extrapolated)}"),
              Parameter(symbol="", name="In-sample direction right",
                        value=", ".join(f"{k} {_g(v, 2)}" for k, v in pr.directional_accuracy.items()))]
    text = ("The calibrated equations run forward from the last observed year, with the last parameters "
            "held (or their trend extended). It says where the economy goes if the last conditions persist: "
            f"direction is the strongest reading, dates the weakest. Phase changes ahead: {trans}."
            + ("" if pr.fit_reproduces_window else " The fit does not reproduce the window, so this rests on weak evidence."))
    formulas = [r"(Y,K^R,K^I)_{t+1}=(Y,K^R,K^I)_t+\int_t^{t+1}f\big(Y,K^R,K^I;\ \hat\theta,\ p(T)\big)\,d\tau,\qquad T=\text{last observed year}"]
    if not pr.segment:
        charts = _projection_charts(ph, pr, None, None)
        return ModelStep(key="projection", title="Projection", text=text, formulas=tuple(formulas),
                         parameters=tuple(params), charts=charts)

    c = pr.ceiling
    policy = pr.resolution_policy
    turn = pr.turns[0] if pr.turns else None
    text += (f" Saturation growth is damped from {c.damping_onset:g} so the path bends and turns inside the "
             f"band {c.lower:g} to {c.upper:g} (soft ceiling around {c.centre:g}, no clamp). ")
    if turn is not None:
        text += (f"Under the {policy} policy it turns in {turn.year} at {turn.level:.2f}"
                 + (" (in the extrapolated tail)" if turn.in_extrapolation else "")
                 + f", then follows the policy's {turn.crisis_months}-month crisis to {turn.crisis_end_level:.2f} "
                 f"({turn.crisis_end_year}) and a {turn.reset_years}-year reset to {turn.reset_target:.2f} "
                 f"({turn.reset_end_year}), after which the model runs again with early-phase parameters. "
                 "Years after the turn are model-derived crisis and reset, not extrapolation.")
    else:
        text += f"Under the {policy} policy it does not reach its turn level by {pr.years[-1]}."
    formulas += [r"\dot x = g\,\sqrt{1-u^2},\quad x=\ln\sigma,\quad u=\frac{x-\ln\sigma_{on}}{\ln\sigma_{turn}-\ln\sigma_{on}}",
                 r"\sigma_{t} = \sigma_{turn}\,\frac{D_t\,V_t}{P_t}\ \text{(crisis)},\qquad \ln\sigma \to \ln\sigma_{reset}\ \text{on a half cosine (reset)}"]
    params += [Parameter(symbol=r"\sigma_{on}", name="Damping onset", value=f"{c.damping_onset:g}"),
               Parameter(symbol="", name="Ceiling band", value=f"{c.lower:g} to {c.upper:g}, centre {c.centre:g}"),
               Parameter(symbol="", name="Resolution policy", value=str(policy)),
               Parameter(symbol="", name="Turns",
                         value="; ".join(f"{t.year} at {t.level:.2f}, reset to {t.reset_end_year}" for t in pr.turns) or "none"),
               Parameter(symbol="", name="Lower confidence after", value=str(pr.display_until))]
    charts = (_projection_charts(ph, pr, pr.display_until, f"to {pr.display_until}")
              + _projection_charts(ph, pr, None, f"to {pr.years[-1]}, lower confidence after {pr.display_until}"))
    return ModelStep(key="projection", title="Projection", text=text, formulas=tuple(formulas),
                     parameters=tuple(params), charts=charts)


def _projection_charts(ph, pr, until: Optional[int], suffix: Optional[str]) -> tuple[Chart, ...]:
    keep = [i for i, y in enumerate(pr.years) if y > ph.years[-1] and (until is None or y <= until)]
    px = tuple(int(y) for y in ph.years) + tuple(int(pr.years[i]) for i in keep)
    n_hist = len(ph.years)
    hist_sat = tuple(ph.saturation) + tuple(None for _ in keep)
    start_year = int(pr.years[keep[0]]) if keep else None
    proj_phase = tuple(None if p is None else float(p) - 1 for p in ph.phase) + \
        tuple(float(pr.phase[i]) - 1 for i in keep)
    title = "Saturation: history and projection" + (f" ({suffix})" if suffix else "")
    lead = tuple(None for _ in range(n_hist - 1)) + (ph.saturation[-1],)
    if not pr.segment:
        series = (ChartSeries(name="observed", y=hist_sat, slot=0),
                  ChartSeries(name="projected", y=lead + tuple(pr.saturation[i] for i in keep), slot=0, dash="dash"))
    else:
        # One series per part, each joined to the previous point so the line is continuous.
        def part(names: tuple[str, ...]) -> tuple:
            vals = list(lead) if keep and pr.segment[keep[0]] in names else [None] * n_hist
            for j, i in enumerate(keep):
                inside = pr.segment[i] in names
                nxt = j + 1 < len(keep) and pr.segment[keep[j + 1]] in names
                vals.append(pr.saturation[i] if inside or nxt else None)
            return tuple(vals)
        policy = pr.resolution_policy
        series = (ChartSeries(name="observed", y=hist_sat, slot=0),
                  ChartSeries(name="projected (model)", y=part(("model", "post_reset")), slot=0, dash="dash"),
                  ChartSeries(name="extrapolated (not a model consequence)", y=part(("extrapolated", "post_reset_extrapolated")),
                              slot=0, dash="dot", muted=True),
                  ChartSeries(name=f"crisis and reset ({policy})", y=part(("crisis", "reset")), slot=3, dash="dash"),
                  ChartSeries(name="ceiling band", y=tuple(pr.ceiling.upper for _ in px), dash="dot", muted=True),
                  ChartSeries(name="ceiling band (lower)", y=tuple(pr.ceiling.lower for _ in px), dash="dot", muted=True))
    return (Chart(title=title, x=px, y_label="share of GDP", projected_from=start_year, series=series),
            Chart(title="Phase: history and projection" + (f" ({suffix})" if suffix else ""), kind="heatmap",
                  x=px, rows=("phase",), z=(proj_phase,), categories=PHASE_NAMES, projected_from=start_year))

