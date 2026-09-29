"""Scenario Regimes: the four Phase IV policies of ``Scenario_SAA.m`` on a base Regime (AGG-19 to AGG-22).

Pure: arrays in, arrays out; no network, no disk, no clock. ``service.build_scenario_regime`` puts
the result into a ``Regime``.

The template is ``SIM_Tech/Master_Controller/Scenario_SAA.m`` (v0.1, Nicolas Buerkler), sha256
``TEMPLATE_SHA256``, frozen in ``golden/scenario_saa/``. The policy ids and target mixes are the
ones macrofield uses (TB-21, ``macrofield.calibration.RESOLUTION_POLICIES``). What this module ports,
statement for statement:

1. **The kernels.** ``Binom`` (14 states), ``Binom_Bust`` (10 states) and ``Binom_Boom`` (``Binom_Bust``
   reversed), in per cent; each sums to 99 %, and the .m file does not normalise them.
2. **The target.** ``M1 = [Boom, Recovery, Contraction, Bust]``, flipped to ``[Bust, Contraction,
   Recovery, Boom]``; ``MRS(T,:) = Bust * Binom_Bust`` on states 1 to 10 ``+ Contraction * Binom`` on
   3 to 16 ``+ Recovery * Binom`` on 10 to 23 ``+ Boom * Binom_Boom`` on 16 to 25. The target
   therefore sums to 0.99.
3. **The stepping.** From the current signal ``MRS_start``, for ``i = 1..T``: ``step = (target -
   current) / (T - i + 1)``, ``current = current + step``, ``current = current / sum(current)``; row
   ``i`` is ``current``. Row ``T`` is the target normalised to 1 whatever the start.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass

import numpy as np

from .contracts import N_STATES, ScenarioPolicy

#: The .m file's ``case`` order (1 to 4), macrofield's ids (TB-21).
SCENARIO_POLICIES: tuple[ScenarioPolicy, ...] = ("depression", "hyperinflation", "stagflation", "deferral")

#: sha256 of ``Scenario_SAA.m`` v0.1 (the same file macrofield froze, TB-21).
TEMPLATE_SHA256 = "37071593f9958cc422e092a03ed0950fd13693af71e4a57f0e39f465d7c7f4de"
TEMPLATE = "SIM_Tech/Master_Controller/Scenario_SAA.m (v0.1, Nicolas Buerkler)"

#: ``T = 60``: the .m file's simulation time in months.
HORIZON_MONTHS = 60

#: Version of this module's rule. It is in the scenario's idempotency key, so a change to the
#: rule gives new scenario ids and never overwrites an issued one.
SCENARIO_RULE_VERSION = "aggregation-scenario@1.0.0"

#: ``Binom`` and ``Binom_Bust`` of the .m file, in per cent (divided by 100 there).
BINOM = (1.5, 2.0, 4.9, 6.0, 8.9, 13.0, 13.7, 13.7, 12.0, 8.9, 6.0, 4.9, 2.0, 1.5)
BINOM_BUST = (14.4, 21.9, 13.7, 13.7, 12.0, 8.9, 6.0, 4.9, 2.0, 1.5)

#: The four phases of the target mix, in the .m file's order ``M1 = [Boom, Recovery, Contraction, Bust]``.
MIX_PHASES: tuple[str, ...] = ("boom", "recovery", "contraction", "bust")


@dataclass(frozen=True)
class PolicySpec:
    case: int
    label_en: str
    label_de: str
    description_en: str
    description_de: str
    #: ``M1`` of the .m file: Boom, Recovery, Contraction, Bust.
    target_mix: tuple[float, float, float, float]


POLICIES: dict[str, PolicySpec] = {
    "depression": PolicySpec(
        1, "Depression", "Depression",
        "Deflationary bust: inflation falls from +2 % to -4 %, 40 % of claims default, valuations halve; "
        "target 75 % Bust, 25 % Contraction.",
        "Deflationärer Einbruch: Inflation fällt von +2 % auf -4 %, 40 % der Forderungen fallen aus, "
        "Bewertungen halbieren sich; Ziel 75 % Bust, 25 % Contraction.",
        (0.0, 0.0, 0.25, 0.75)),
    "hyperinflation": PolicySpec(
        2, "Hyperinflation", "Hyperinflation",
        "Inflation rises from 20 % to 100 % a year while claims are honoured nominally; target 100 % Boom "
        "(nominal boom, real destruction of financial claims).",
        "Inflation steigt von 20 % auf 100 % pro Jahr, Forderungen werden nominal bedient; Ziel 100 % Boom "
        "(nominaler Boom, reale Entwertung der Forderungen).",
        (1.0, 0.0, 0.0, 0.0)),
    "stagflation": PolicySpec(
        3, "Stagflation", "Stagflation",
        "Inflation rises from 2 % to 10 %, 20 % of claims default, valuations fall 30 %; target 50 % Boom, "
        "25 % Recovery, 25 % Contraction.",
        "Inflation steigt von 2 % auf 10 %, 20 % der Forderungen fallen aus, Bewertungen fallen um 30 %; "
        "Ziel 50 % Boom, 25 % Recovery, 25 % Contraction.",
        (0.5, 0.25, 0.25, 0.0)),
    "deferral": PolicySpec(
        4, "Deferral", "Aufschub",
        "The correction is deferred: inflation humps from 2 % to 6 % and back, 10 % of claims default; "
        "target split 50 % Boom, 50 % Bust.",
        "Die Korrektur wird aufgeschoben: Inflation steigt von 2 % auf 6 % und zurück, 10 % der "
        "Forderungen fallen aus; Ziel geteilt 50 % Boom, 50 % Bust.",
        (0.5, 0.0, 0.0, 0.5)),
}


def kernels() -> dict[str, np.ndarray]:
    """``Binom``, ``Binom_Bust`` and ``Binom_Boom = fliplr(Binom_Bust)``, as fractions (not normalised)."""
    binom = np.asarray(BINOM, dtype=float) / 100
    bust = np.asarray(BINOM_BUST, dtype=float) / 100
    return {"binom": binom, "binom_bust": bust, "binom_boom": bust[::-1].copy()}


def target_distribution(policy: str) -> np.ndarray:
    """``MRS(T,:)`` of the .m file for one policy: 25 states, summing to 0.99 as there."""
    k = kernels()
    bust, contraction, recovery, boom = POLICIES[policy].target_mix[::-1]      # M1 = fliplr(M1)
    z = np.zeros
    return (np.concatenate([bust * k["binom_bust"], z(15)])
            + np.concatenate([z(2), contraction * k["binom"], z(9)])
            + np.concatenate([z(9), recovery * k["binom"], z(2)])
            + np.concatenate([z(15), boom * k["binom_boom"]]))


def step_path(start: np.ndarray, target: np.ndarray, months: int = HORIZON_MONTHS) -> np.ndarray:
    """The .m file's gradual transformation: ``months`` rows, each a distribution summing to 1.

    Every row is a convex combination of the previous row and the target, renormalised, so it stays
    non-negative; the last row is ``target / sum(target)``.
    """
    current = np.asarray(start, dtype=float)
    target = np.asarray(target, dtype=float)
    if current.shape != (N_STATES,) or target.shape != (N_STATES,):
        raise ValueError(f"the start and the target are {N_STATES}-state distributions")
    rows = np.zeros((months, N_STATES))
    for i in range(1, months + 1):
        difference = target - current
        step = difference / (months - i + 1)
        current = current + step
        current = current / current.sum()
        rows[i - 1] = current
    return rows


def month_ends_after(date: str, months: int) -> list[str]:
    """The ``months`` month-end ISO dates following the month of ``date`` (``YYYY-MM-DD``)."""
    year, month = int(date[:4]), int(date[5:7])
    out = []
    for _ in range(months):
        month += 1
        if month > 12:
            year, month = year + 1, 1
        out.append(f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}")
    return out


# ---------------------------------------------------------------------------
# The policy's inflation path (AGG-24): nominal and real view
# ---------------------------------------------------------------------------

#: The months whose average is ``inflation_final_12m``: months 49 to 60 of the path (1-based).
FINAL_MONTHS = 12


def inflation_path(policy: str, months: int = HORIZON_MONTHS) -> np.ndarray:
    """``inflation`` of the .m file for one policy: ``months`` annualised rates on ``times =
    linspace(0, 1, T)``, statement for statement. The same values as macrofield's frozen TB-21
    paths (``Macro/engines/macrofield/golden/scenario_saa/scenario_saa.json``, tested to 1e-15).

    * depression: ``fliplr(endVal + range ./ (1 + exp(-steepness * (times - midpoint))))`` with
      +2 % to -4 %, midpoint 0.5, steepness 20;
    * hyperinflation: ``startVal * exp(log(endVal / startVal) * times.^power)``, 20 % to 100 %, power 4;
    * stagflation: ``startVal + range ./ (1 + exp(-steepness * (times - midpoint)))``, 2 % to 10 %,
      midpoint 0.3, steepness 15;
    * deferral: two half Gaussians from 2 % to the peak of 6 % at 0.5 and back, sigma 0.5 / 2.5.
    """
    times = np.linspace(0.0, 1.0, months)
    if policy == "depression":
        start, end, midpoint, steepness = 0.02, -0.04, 0.5, 20.0
        rng = start - end
        return (end + rng / (1 + np.exp(-steepness * (times - midpoint))))[::-1].copy()
    if policy == "hyperinflation":
        start, end, power = 0.2, 1.0, 4.0
        return start * np.exp(np.log(end / start) * times ** power)
    if policy == "stagflation":
        start, end, midpoint, steepness = 0.02, 0.1, 0.3, 15.0
        rng = end - start
        return start + rng / (1 + np.exp(-steepness * (times - midpoint)))
    if policy == "deferral":
        start, peak, position = 0.02, 0.06, 0.5
        rng = peak - start
        sigma1, sigma2 = position / 2.5, (1 - position) / 2.5
        out = np.zeros(months)
        for i, t in enumerate(times):
            sigma = sigma1 if t <= position else sigma2
            out[i] = start + rng * np.exp(-0.5 * ((t - position) / sigma) ** 2)
        return out
    raise ValueError(f"unknown scenario policy {policy!r}")


def inflation_final_12m(path: np.ndarray) -> float:
    """The average annual inflation over the last ``FINAL_MONTHS`` months of the path (months 49 to
    60): the arithmetic mean of the twelve annualised rates."""
    tail = [float(v) for v in np.asarray(path, dtype=float)[-FINAL_MONTHS:]]
    return math.fsum(tail) / len(tail)
