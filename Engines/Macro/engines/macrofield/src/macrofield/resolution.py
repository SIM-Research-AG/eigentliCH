"""The four Phase IV resolution policies: inflation, defaults and valuations paths. Pure.

A port of ``SIM_Tech/Master_Controller/Scenario_SAA.m`` (v0.1, Nicolas Buerkler), the template
the author named for R-005 (decided 28.09.2026). The .m file simulates a 60-month acute crisis
under one of four policies; each policy is a target mix over Boom, Recovery, Contraction and
Bust, an **inflation** path (annual rate per month), a **defaults** factor (the share of claims
that survive) and a **valuations** factor. The functional forms below reproduce the .m file
operation for operation: ``times = linspace(0, 1, T)``, the sigmoid, exponential and two-sided
Gaussian inflation shapes, the two-legged defaults curve and the linear valuations ramp. The
parameters are calibration values (``projection.crisis.policies``), frozen against the .m file
in ``golden/scenario_saa/scenario_saa.json`` so Engine 09 (``scenario``) can use the same ids and values.

How the model uses them (projection.py): over the crisis, nominal output follows the price
level the inflation path implies (real output held flat) and financial claims K_I are written
down by defaults times valuations, so saturation = credit share x K_I / Y corrects through the
numerator (claims written down), the denominator (nominal output inflated) or both.
"""

from __future__ import annotations

import numpy as np

from .contracts import DefaultsSpec, InflationSpec, ResolutionPolicy, ValuationsSpec


def times(months: int) -> np.ndarray:
    """``times = linspace(0, 1, T)`` of the .m file."""
    return np.linspace(0.0, 1.0, months)


def inflation(spec: InflationSpec, months: int) -> np.ndarray:
    """Annual inflation rate in each crisis month (0.02 = 2 per cent a year)."""
    t = times(months)
    if spec.form == "sigmoid":
        if spec.reverse:
            # Depression: endVal + range ./ (1 + exp(-steepness * (times - midpoint))), range =
            # startVal - endVal, then fliplr.
            rng = spec.start - spec.end
            path = spec.end + rng / (1.0 + np.exp(-spec.steepness * (t - spec.midpoint)))
            return path[::-1].copy()
        # Stagflation: startVal + range ./ (1 + exp(...)), range = endVal - startVal.
        rng = spec.end - spec.start
        return spec.start + rng / (1.0 + np.exp(-spec.steepness * (t - spec.midpoint)))
    if spec.form == "exponential":
        # Hyperinflation: startVal * exp(log(endVal / startVal) * times.^power).
        return spec.start * np.exp(np.log(spec.end / spec.start) * t ** spec.power)
    # Deferral: a hump of two half Gaussians, sigma = position / 2.5 left, (1 - position) / 2.5
    # right, rising from startVal to peakVal at peakPosition and back.
    rng = spec.end - spec.start
    sigma1 = spec.midpoint / spec.width_divisor
    sigma2 = (1.0 - spec.midpoint) / spec.width_divisor
    out = np.zeros(t.shape)
    for i, ti in enumerate(t):
        sigma = sigma1 if ti <= spec.midpoint else sigma2
        out[i] = spec.start + rng * np.exp(-0.5 * ((ti - spec.midpoint) / sigma) ** 2)
    return out


def defaults(spec: DefaultsSpec, months: int) -> np.ndarray:
    """Share of claims that survive, per month: a root-shaped first leg that takes
    ``first_leg_share`` of the change by the inflection, then a power-shaped second leg."""
    t = times(months)
    total = spec.start - spec.end
    out = np.zeros(t.shape)
    for i, ti in enumerate(t):
        if ti <= spec.inflection:
            out[i] = spec.start - total * (ti / spec.inflection) ** (1.0 / spec.steepness) \
                * spec.first_leg_share
        else:
            t_norm = (ti - spec.inflection) / (1.0 - spec.inflection)
            at_inflection = spec.start - total * spec.first_leg_share
            remaining = at_inflection - spec.end
            out[i] = at_inflection - remaining * t_norm ** spec.steepness
    return out


def valuations(spec: ValuationsSpec, months: int) -> np.ndarray:
    """``[linspace(start, end, ramp) end * ones(1, T - ramp)]``."""
    ramp = min(spec.ramp_months, months)
    return np.concatenate([np.linspace(spec.start, spec.end, ramp),
                           spec.end * np.ones(months - ramp)])


def paths(policy: ResolutionPolicy, months: int) -> dict[str, np.ndarray]:
    """The three monthly paths of one policy, plus the price level they imply.

    ``price_level[m]`` compounds the annual rates month by month, (1 + pi)^(1/12), from 1 before
    the first month. The .m file stops at the paths; the price level is this engine's reading of
    the inflation path as nominal output.
    """
    pi = inflation(policy.inflation, months)
    return {
        "inflation": pi,
        "defaults": defaults(policy.defaults, months),
        "valuations": valuations(policy.valuations, months),
        "price_level": np.cumprod(np.power(1.0 + pi, 1.0 / 12.0)),
    }
