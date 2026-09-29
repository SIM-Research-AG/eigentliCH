"""The deflator: inflation over the following 12 months, per regime state and currency.

**The owner's decisions of 29 September 2026** (``review/REAL_VIEW_INTERFACES.md``; design
note "Design note: nominal and real view"), as built here:

1. **Deflator.** The inflation measured in each regime state over the following 12
   months, the same horizon as the returns (D-02). Every month with a signal is tagged with
   its calibration state, exactly as the 12 month forward measurement tags it (FMRE-01);
   its value is the log price change over ``t+1 .. t+12``, which the monthly year-on-year
   series gives directly: ``log(1 + cpi_yoy(t + 12))``, no price level to rebuild. The
   value is estimated per phase with the sufficiency floor and the honest count of
   FMRE-02 and read onto the 25 states by the calibration's pchip (FMRE-03). **A phase
   below the floor takes today's year-on-year inflation** (the latest observation of the
   index), and the band of five states around its knot is labelled ``fallback``.
2. **Scenario Regimes** use their policy's own inflation, the average over the final 12
   months of the 60 month ``Scenario_SAA.m`` path, applied to every state
   (:func:`scenario_curve`). Never the historical per-state inflation. Since FMRE-33 the
   scenario deflates a profile that was first carried to the scenario by the instrument's
   inflation pass-through beta (``pass_through.py``), so a scenario's real return is the
   historical real return plus ``(beta - 1) * ln(1 + pi_s)``.
3. **Index per currency.** CHF: Swiss CPI; EUR: euro-area HICP from 1999, German CPI before
   (only where data reaches); USD: US CPI-U (:data:`INDEX`).
4. **Ceiling.** Real figures are computed for inflation from -20 % to +100 % a year;
   -10 % to +20 % is labelled ``measured``, the rest of the band ``extrapolated``
   (:func:`band`).
5. **Above the ceiling** (or below -20 %) no real figure in that currency: a hard-currency
   view, first CHF, then USD (:func:`hard_currency`); if neither is inside the band, the
   view is ``not_computable`` with the reason.

Log returns throughout: ``real = nominal - ln(1 + inflation)``, a subtraction per state.
The deflator is not smoothed; it is the measurement.

Pure functions; no storage. The caller reads the series (``service.load_cpi_yoy``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from engines.fund_map import numerics as num
from engines.fund_map.calibrate import (
    PHASE_KNOTS,
    STATE_COUNT,
    SUFFICIENCY_FLOOR,
    TRIM_FRACTION,
    TRIM_SWITCH,
    Method,
    state_axis,
    state_methods,
)
from engines.fund_map.forward import (
    FORWARD_HORIZON_MONTHS,
    add_months,
    effective_observations,
    phase_of_state,
)
from engines.fund_map.state_map import StateMap

#: Decision 4: the band in which a real figure is computed, and the part of it labelled
#: ``measured``, as simple annual inflation. Both edges belong to the inner label
#: (-10 % and +20 % are ``measured``; -20 % and +100 % are ``extrapolated``).
CEILING = 1.00
FLOOR = -0.20
MEASURED_LOW = -0.10
MEASURED_HIGH = 0.20

#: Decision 5: the hard currencies a real view falls back to, in order.
HARD_CURRENCIES: tuple[str, ...] = ("CHF", "USD")

#: The labels, weakest last.
LABELS: tuple[str, ...] = ("measured", "extrapolated", "fallback", "not_computable")

#: The index behind each currency (decision 3): ``(datafeed country code, pull code, name)``
#: of ``inflation.cpi_yoy``. EUR reads the euro-area HICP from 1999 and German CPI before.
CPI_SERIES = "inflation.cpi_yoy"
INDEX: dict[str, tuple[tuple[str, str, str], ...]] = {
    "CHF": (("CH", "SZCPIYOY Index", "Swiss CPI (LIK), year on year"),),
    "EUR": (("EU", "EHPIEU Index", "euro-area HICP, year on year, from 1999"),
            ("DE", "GRCP20YY Index", "German CPI, year on year, before 1999")),
    "USD": (("US", "CPI YOY Index", "US CPI-U, year on year"),),
}
#: The first month the euro-area HICP stands for EUR; German CPI before it.
EUR_HICP_FROM = "1999-01"

METHOD = (
    "forward_12m: each signal month t tagged with its calibration state; value "
    "log(1 + cpi_yoy(t+12)), the log price change over t+1..t+12 (D-02); per phase with the "
    "floor of six effective years (FMRE-02); read onto the 25 states by pchip (FMRE-03); a "
    "phase below the floor takes today's year-on-year inflation, labelled fallback; not "
    "smoothed"
)
SCENARIO_METHOD = (
    "scenario: the policy's own inflation path of Scenario_SAA.m, the average annual "
    "inflation over months 49 to 60 (provenance.scenario.inflation_final_12m), applied to "
    "every state (decision 2)"
)


class NotComputable(ValueError):
    """Raised when no currency's inflation lies inside the band (decision 5)."""


def band(inflation: float) -> str:
    """The ceiling rule on one simple annual inflation rate (decision 4).

    ``measured`` inside -10 % .. +20 %, ``extrapolated`` in the rest of -20 % .. +100 %,
    ``not_computable`` outside.
    """
    if MEASURED_LOW <= inflation <= MEASURED_HIGH:
        return "measured"
    if FLOOR <= inflation <= CEILING:
        return "extrapolated"
    return "not_computable"


@dataclass(frozen=True)
class StateInflation:
    state: int
    inflation: float          # simple annual rate, exp(log_inflation) - 1
    log_inflation: float      # what a real log return subtracts
    label: str                # measured | extrapolated | fallback | not_computable
    n_obs: int                # effective independent years of the phase; 0 for a fill
    estimate: str             # how the value came to exist: the profile method vocabulary,
    #                           or "fallback" / "scenario"


@dataclass(frozen=True)
class PhaseInflation:
    phase: int
    windows: int
    n_eff: int
    value: float              # the knot, log inflation
    method: str               # data-driven | data-driven-trimmed | fallback


@dataclass(frozen=True)
class InflationCurve:
    """``pi(s, c)``: one currency's (or one scenario's) inflation over the 25 states."""

    currency: str
    index: str
    method: str
    states: tuple[StateInflation, ...]
    phases: tuple[PhaseInflation, ...]
    as_of: str | None
    source: str
    #: Today's year-on-year inflation: what a thin phase falls back to.
    today: float | None = None
    #: The scenario policy, when this is a scenario's curve.
    scenario: str | None = None

    @property
    def log_inflation(self) -> tuple[float, ...]:
        return tuple(s.log_inflation for s in self.states)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(s.label for s in self.states)

    def outside(self) -> list[int]:
        """The 1-based states whose inflation is outside the band."""
        return [s.state for s in self.states if s.label == "not_computable"]

    def computable(self) -> bool:
        return not self.outside()

    def as_payload(self) -> dict:
        return {
            "currency": self.currency, "index": self.index, "method": self.method,
            "states": [
                {"state": s.state, "inflation": s.inflation, "log_inflation": s.log_inflation,
                 "label": s.label, "n_obs": s.n_obs, "estimate": s.estimate,
                 **({"reason": ceiling_reason(self.currency, s.inflation)}
                    if s.label == "not_computable" else {})}
                for s in self.states
            ],
            "phases": [
                {"phase": p.phase, "windows": p.windows, "n_eff": p.n_eff,
                 "log_inflation": p.value, "method": p.method}
                for p in self.phases
            ],
            "as_of": self.as_of, "source": self.source, "today": self.today,
            "scenario": self.scenario,
        }


def ceiling_reason(currency: str, inflation: float) -> str:
    edge = f"the ceiling of {CEILING:.0%}" if inflation > CEILING else f"the floor of {FLOOR:.0%}"
    side = "above" if inflation > CEILING else "below"
    return (f"{currency} inflation of {inflation:.1%} a year is {side} {edge}; no real "
            f"figure is computed in {currency} (decisions 4 and 5)")


def _label(inflation: float, *, fallback: bool) -> str:
    b = band(inflation)
    if b == "not_computable":
        return b
    return "fallback" if fallback else b


def forward_inflation_windows(
    yoy: Mapping[str, float],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
    *,
    horizon: int = FORWARD_HORIZON_MONTHS,
) -> list[tuple[str, int, float]]:
    """``(tagged month, calibration state, log inflation over t+1 .. t+12)`` per month.

    A month whose year-on-year reading 12 months on is missing is dropped, never filled
    (the December 2025 gap of the Swiss series drops one window, no more).
    """
    out = []
    for period in sorted(signal_by_period):
        rate = yoy.get(add_months(period, horizon))
        if rate is None or rate <= -1.0:
            continue
        out.append((period, state_map.state_for(signal_by_period[period]), math.log1p(rate)))
    return out


def today_rate(yoy: Mapping[str, float]) -> tuple[str, float] | None:
    """The latest year-on-year reading: today's inflation, the fallback of decision 1."""
    if not yoy:
        return None
    last = max(yoy)
    return last, yoy[last]


def state_curve(
    currency: str,
    yoy: Mapping[str, float],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
    *,
    index: str,
    source: str,
) -> InflationCurve:
    """The historical deflator of one currency (decision 1)."""
    windows = forward_inflation_windows(yoy, signal_by_period, state_map)
    phases = len(PHASE_KNOTS)
    by_phase: list[list[tuple[str, int, float]]] = [[] for _ in range(phases)]
    for w in windows:
        by_phase[phase_of_state(w[1])].append(w)
    today = today_rate(yoy)

    knots: list[float] = []
    methods: list[str] = []
    n_eff: list[int] = []
    for p in range(phases):
        values = [w[2] for w in by_phase[p]]
        n = effective_observations([w[0] for w in by_phase[p]])
        n_eff.append(n)
        if n >= SUFFICIENCY_FLOOR:
            if n >= TRIM_SWITCH:
                knots.append(num.trimmed_mean(values, TRIM_FRACTION))
                methods.append(Method.DATA_DRIVEN_TRIMMED.value)
            else:
                knots.append(num.mean(values))
                methods.append(Method.DATA_DRIVEN.value)
        else:
            if today is None:
                raise NotComputable(
                    f"no {currency} inflation series is loaded ({source}); the deflator "
                    f"cannot be measured and has nothing to fall back to")
            knots.append(math.log1p(today[1]))
            methods.append("fallback")

    profile = num.pchip_eval(list(PHASE_KNOTS), knots, state_axis())
    grid = state_methods([Method.DATA_DRIVEN if m == "fallback" else Method(m)
                          for m in methods])
    states = []
    for i, value in enumerate(profile):
        p = phase_of_state(i + 1)
        filled = methods[p] == "fallback"
        rate = math.expm1(value)
        states.append(StateInflation(
            state=i + 1, inflation=rate, log_inflation=value,
            label=_label(rate, fallback=filled),
            n_obs=0 if filled else n_eff[p],
            estimate="fallback" if filled else grid[i].value,
        ))
    return InflationCurve(
        currency=currency, index=index, method=METHOD, states=tuple(states),
        phases=tuple(PhaseInflation(p, len(by_phase[p]), n_eff[p], knots[p], methods[p])
                     for p in range(phases)),
        as_of=max(yoy) if yoy else None, source=source,
        today=today[1] if today else None,
    )


def scenario_curve(currency: str, inflation_final_12m: float, *, policy: str,
                   regime_id: str) -> InflationCurve:
    """A scenario Regime's deflator: its policy's final-year inflation in every state."""
    if inflation_final_12m <= -1.0:
        raise NotComputable(f"scenario inflation {inflation_final_12m!r} is not a rate")
    value = math.log1p(inflation_final_12m)
    label = _label(inflation_final_12m, fallback=False)
    return InflationCurve(
        currency=currency, index=f"scenario:{policy}", method=SCENARIO_METHOD,
        states=tuple(StateInflation(s, inflation_final_12m, value, label, 0, "scenario")
                     for s in range(1, STATE_COUNT + 1)),
        phases=(), as_of=None, source=f"aggregation:{regime_id}", scenario=policy,
    )


def hard_currency(wanted: str, curves: Mapping[str, InflationCurve]) -> tuple[str, dict | None]:
    """Decision 5: the currency a real view is computed in, and the fallback it took.

    ``wanted`` when its curve lies inside the band in every state; otherwise CHF, then USD,
    whichever is inside the band first. Raises :class:`NotComputable` with the reason if
    none is.
    """
    first = curves[wanted]
    if first.computable():
        return wanted, None
    reasons = [curve_reason(first)]
    for candidate in HARD_CURRENCIES:
        if candidate == wanted:
            continue
        curve = curves.get(candidate)
        if curve is None:
            continue
        if curve.computable():
            return candidate, {
                "from": wanted, "to": candidate,
                "states": first.outside(),
                "reason": f"real in {candidate}: " + reasons[0],
            }
        reasons.append(curve_reason(curve))
    raise NotComputable("; ".join(reasons) + ". No hard currency is inside the band.")


def curve_reason(curve: InflationCurve) -> str:
    worst = max((s for s in curve.states if s.label == "not_computable"),
                key=lambda s: abs(s.inflation))
    return (ceiling_reason(curve.currency, worst.inflation)
            + f" (states {curve.outside()})")


def deflate(values: Sequence[float], curve: InflationCurve) -> list[float]:
    """``real = nominal - ln(1 + inflation)``, state by state."""
    if len(values) != STATE_COUNT:
        raise ValueError(f"a profile has {len(values)} states, expected {STATE_COUNT}")
    if not curve.computable():
        raise NotComputable(curve_reason(curve))
    return [v - d for v, d in zip(values, curve.log_inflation)]


def weakest_labels(curves: Sequence[InflationCurve]) -> tuple[str, ...]:
    """Per state, the weakest label over several curves (``LABELS`` order)."""
    return tuple(max((c.states[i].label for c in curves), key=LABELS.index)
                 for i in range(STATE_COUNT))

