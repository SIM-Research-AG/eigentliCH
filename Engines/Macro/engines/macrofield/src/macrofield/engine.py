"""The engine: observations and a calibration in, economy states out. Pure.

No network, no disk, no clock. Everything testable lives behind this module:

    assembly.py   published series -> observed (Y, K_R, K_I) path
    fitting.py    identities from data, then the least-squares calibration
    dynamics.py   the equations of motion the fit integrates
    phases.py     phase classification and the unsecured-asset diagnostics

An economy that cannot be assembled is returned as ``unavailable`` with the reason and the
missing series; it never stops the other economies, and it is never filled.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

import numpy as np

from .assembly import Annual, Assembled, Unavailable, assemble
from .contracts import (
    PHASE_LABELS,
    Calibration,
    CapitalNormalisation,
    CoverageReport,
    CurrentState,
    Diagnostics,
    EconomyCoverage,
    EconomySpec,
    EconomyState,
    FitReport,
    IdentityPaths,
    InputPaths,
    PhaseHistory,
    StatePaths,
)
from .fitting import FitError, ObservedPath, fit, identities
from .phases import classify_sequence, unsecured_accelerating, unsecured_ratio
from .projection import project, settings_from

#: Observations for one economy: series id -> {year: value or None}.
Observations = Mapping[str, Annual]


class EngineError(RuntimeError):
    """The run as a whole cannot proceed (as opposed to one economy being unavailable)."""


def _num(v: float) -> Optional[float]:
    v = float(v)
    return v if math.isfinite(v) else None


def _path(values: Optional[np.ndarray]) -> tuple[Optional[float], ...]:
    return tuple(_num(v) for v in np.asarray(values, dtype=float))


def phase_sequences(a: Assembled, cal: Calibration):
    """(latched, stateless) phases for the window years, and the full phase history.

    The history runs over every year with a saturation value and a real-capital ratio up to the
    window end. Inside the window it uses the window's own stocks; before it, the scale-free
    equivalents (K_R/Y = ratio x scale, K_I/Y = saturation x scale), which classify identically.
    With ``latch_from_full_history`` the window's phases are read off the history, so a
    saturation episode before the window carries into it; otherwise the latch starts at the
    window (the prototype's rule) and the history is published for information.
    """
    t = cal.phases
    window_at = {int(y): i for i, y in enumerate(a.years)}
    scale = a.normalisation_scale
    sat, kr, ki, y = [], [], [], []
    shares = a.history_commercial_share
    for year, s_h, ratio in zip(a.history_years, a.history_saturation, a.history_ratio):
        i = window_at.get(int(year))
        if i is None:
            sat.append(s_h); kr.append(ratio * scale); ki.append(s_h * scale); y.append(1.0)
        else:
            sat.append(a.saturation[i]); kr.append(a.real_capital[i])
            ki.append(a.financial_capital[i]); y.append(a.output[i])
    h_latched, h_stateless = classify_sequence(np.array(sat), np.array(kr), np.array(ki),
                                               np.array(y), t, commercial_share=shares)
    history = PhaseHistory(
        years=tuple(int(v) for v in a.history_years),
        saturation=_path(a.history_saturation),
        real_to_financial=_path(a.history_ratio / a.history_saturation),
        phase=tuple(c.phase for c in h_latched),  # type: ignore[misc]
        in_window=tuple(int(v) in window_at for v in a.history_years),
        commercial_bank_share=_path(shares),
    )
    if t.latch_from_full_history:
        at = {int(v): i for i, v in enumerate(a.history_years)}
        pick = [at[int(v)] for v in a.years]
        return [h_latched[i] for i in pick], [h_stateless[i] for i in pick], history
    latched, stateless = classify_sequence(a.saturation, a.real_capital, a.financial_capital,
                                           a.output, t, commercial_share=a.commercial_share)
    return latched, stateless, history


def run_economy(spec: EconomySpec, obs: Observations, cal: Calibration,
                resolution_policy: Optional[str] = None) -> EconomyState:
    """One economy, end to end. Deterministic. ``resolution_policy`` selects the Phase IV
    resolution the projection follows (calibrations with a crisis section; default theirs)."""
    try:
        a = assemble(spec, obs, cal)
        path = ObservedPath(periods=a.years, output=a.output, real_capital=a.real_capital,
                            financial_capital=a.financial_capital, savings_rate=a.savings_rate,
                            stimulus=a.stimulus)
        ids = identities(path, a.population_growth, cal)
    except Unavailable as exc:
        return EconomyState(code=spec.code, name=spec.name, status="unavailable",
                            reason=exc.reason, missing_inputs=exc.missing,
                            notes=(spec.note,) if spec.note else ())
    except FitError as exc:
        return EconomyState(code=spec.code, name=spec.name, status="unavailable",
                            reason=f"the observed path cannot be calibrated: {exc}",
                            notes=(spec.note,) if spec.note else ())

    outcome = fit(path, ids, cal)

    latched, stateless, history = phase_sequences(a, cal)
    unsecured = unsecured_ratio(a.real_capital, a.financial_capital, a.output)
    real_to_financial = a.real_capital / a.financial_capital
    capital_saturation = (a.real_capital + a.financial_capital) / a.output
    last = len(a.years) - 1
    band = cal.phases.balanced_band

    notes = [n for n in (spec.note,) if n] + list(a.notes)
    if ids.p_b_source != cal.p_b_source:
        notes.append(f"p_b taken from the {ids.p_b_source} formula, not {cal.p_b_source}")
    notes.extend(outcome.notes)

    simulated = None
    if outcome.simulated is not None:
        simulated = StatePaths(Y=_path(outcome.simulated["Y"]),
                               K_R=_path(outcome.simulated["K_R"]),
                               K_I=_path(outcome.simulated["K_I"]))

    state = EconomyState(
        code=spec.code,
        name=spec.name,
        status="ok",
        phase_history=history,
        years=tuple(int(y) for y in a.years),
        dropped_years=a.dropped_years,
        stimulus_proxy=spec.stimulus_proxy,
        inputs=InputPaths(
            credit_ratio_published=_path(a.credit_published),
            saturation=_path(a.saturation),
            real_capital_ratio=_path(a.real_capital_ratio),
            real_capital_ratio_extended=tuple(bool(x) for x in a.extended),
            p_s=_path(a.savings_rate),
            stimulus_share=_path(a.stimulus_share),
            S=_path(a.stimulus),
            population_growth=(_path(a.population_growth) if a.population_growth is not None
                               else (None,) * len(a.years)),
            commercial_bank_share=_path(a.commercial_share),
        ),
        observed=StatePaths(Y=_path(a.output), K_R=_path(a.real_capital),
                            K_I=_path(a.financial_capital)),
        identities=IdentityPaths(r=_path(ids.r), alpha=_path(ids.alpha), p_p=_path(ids.p_p),
                                 p_b=_path(ids.p_b), p_b_flow_ratio=_path(ids.p_b_flow_ratio)),
        capital_normalisation=CapitalNormalisation(
            scale=a.normalisation_scale, target=cal.capital_target,
            observed_max_ratio=a.normalisation_max_ratio,
            observed_max_year=a.normalisation_max_year),
        fit=FitReport(
            free_parameters=outcome.free_parameters,
            standard_errors={k: _num(v) for k, v in outcome.standard_errors.items()},
            identifiability=outcome.identifiability,
            weakly_identified=tuple(outcome.weakly_identified),
            converged=outcome.converged,
            optimiser_message=outcome.message,
            evaluations=outcome.evaluations,
            integration_accuracy=outcome.integration_accuracy,  # type: ignore[arg-type]
            residuals={k: _num(v) for k, v in outcome.residuals.items()},
            two_body_worst_relative=_num(outcome.two_body_worst),
            identity_diagnostics={k: _num(v) for k, v in outcome.identity_diagnostics.items()},
            identity_corrections=outcome.identity_corrections,
        ),
        simulated=simulated,
        diagnostics=Diagnostics(
            capital_saturation=_path(capital_saturation),
            real_to_financial=_path(real_to_financial),
            unsecured_ratio=_path(unsecured),
            unsecured_accelerating=tuple(bool(x) for x in unsecured_accelerating(
                a.real_capital, a.financial_capital, a.output,
                cal.phases.unsecured_acceleration_periods)),
            phase=tuple(c.phase for c in latched),  # type: ignore[misc]
            phase_unlatched=tuple(c.phase for c in stateless),  # type: ignore[misc]
            in_balanced_band=tuple(c.in_balanced_band for c in latched),
            economy_type=tuple(c.economy_type for c in latched),  # type: ignore[misc]
            phase_rules=tuple(c.rules for c in latched),
        ),
        current=CurrentState(
            year=int(a.years[last]),
            phase=latched[last].phase,  # type: ignore[arg-type]
            phase_label=PHASE_LABELS[latched[last].phase],
            saturation=float(a.saturation[last]),
            saturation_pct=float(a.saturation[last]) * 100.0,
            in_balanced_band=latched[last].in_balanced_band,
            distance_to_band_upper=band.upper - float(a.saturation[last]),
            real_to_financial=float(real_to_financial[last]),
            unsecured_ratio=float(unsecured[last]),
        ),
        notes=tuple(notes),
    )
    return state.model_copy(update={"projection": project(
        state, cal, settings_from(cal, resolution_policy=resolution_policy))})


def coverage(requested: Sequence[str], states: Sequence[EconomyState]) -> CoverageReport:
    return CoverageReport(
        requested=tuple(requested),
        available=tuple(s.code for s in states if s.status == "ok"),
        unavailable={s.code: s.reason or "" for s in states if s.status == "unavailable"},
        economies=tuple(
            EconomyCoverage(
                code=s.code, status=s.status,
                first_year=s.years[0] if s.years else None,
                last_year=s.years[-1] if s.years else None,
                years=len(s.years),
                dropped_years=s.dropped_years,
                extended_years=tuple(
                    y for y, flag in zip(s.years, s.inputs.real_capital_ratio_extended) if flag
                ) if s.inputs is not None else (),
            ) for s in states),
    )


def run(codes: Sequence[str], observations: Mapping[str, Observations],
        cal: Calibration, resolution_policy: Optional[str] = None) -> tuple[EconomyState, ...]:
    """Every requested economy, in the order requested. Serial; see service.py for parallel."""
    unknown = [c for c in codes if c not in {e.code for e in cal.economies}]
    if unknown:
        raise EngineError(f"calibration {cal.version} registers no economy {unknown}")
    return tuple(run_economy(cal.economy(c), observations.get(c, {}), cal, resolution_policy)
                 for c in codes)
