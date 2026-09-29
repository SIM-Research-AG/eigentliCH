"""The market rule of LBSIM-07: which state each simulated year is in, what it returns, what prices do.

Inputs are the upstream figures already checked by ``lbsim.upstream`` (the pcp Allocation, aggregation's state
distributions blended with the Allocation's economy weights, fmre's per-state profiles and inflation). Pure numpy,
no I/O.

The rule, per Regime:

* Each simulated year ``k = 1, 2, ...`` is in one state ``1..25``, drawn from that year's distribution.
* The base Regime: year 1 is the Allocation's own state distribution (``curves.regime``), which reverts linearly
  to the long-run distribution (the mean over every assessed date, same economy weights) over
  ``market.reversion_years``: year ``k`` is ``latest + (long_run - latest) * min((k - 1) / R, 1)``.
* A scenario Regime: year ``k`` takes the scenario's projected month ``12 k`` for ``min(market.scenario_years,
  horizon_months / 12)`` years, with the scenario's own profiles and inflation ("shock"), then the base Regime's
  year ``k`` with the base profiles and inflation ("then normal").
* Common random numbers: one uniform per path and year (stream ``state_uniforms``) goes through every Regime's
  CDF, so a path is the same draw in every Regime and the base is the same whatever scenarios run beside it.
* ``market.state_persistence`` (0 in both seeds): the probability that a path keeps last year's state. At 0 the
  years are independent and the spare stream is never read.
* The portfolio's annual log return in state ``s`` is ``sum_i w_i * profile_i(s)`` with the Allocation's raw
  weights renormalised to sum to one; prices move by ``ln(1 + inflation_s)`` a year.
* Property: nominal log growth ``g = nominal_log_growth + beta * (log_infl_s - anchor) - sigma^2 / 2 + sigma * z``
  with ``z = rho * z_mkt + sqrt(1 - rho^2) * z_prop``; ``z_mkt`` is the standard normal quantile of the drawn
  state's mid-position in that year's CDF and ``z_prop`` the stream ``property_noise``. The ``- sigma^2 / 2`` makes
  ``ln 1.03`` the log of the expected growth factor, the reading of the paths sample and of the optimiser (port
  note P-10); one draw a year, spread evenly over its twelve steps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Optional

import numpy as np

from ..contracts import N_STATES, Market, PropertyParameters, Words

STREAMS: tuple[str, ...] = ("state_uniforms", "property_noise", "spare")
_NORMAL = NormalDist()


@dataclass(frozen=True)
class StateCurve:
    """Per-state figures of one Regime: the portfolio's annual log return and the annual log inflation."""

    log_return: np.ndarray        # (25,)
    log_inflation: np.ndarray     # (25,)

    def __post_init__(self) -> None:
        for name in ("log_return", "log_inflation"):
            arr = getattr(self, name)
            if arr.shape != (N_STATES,):
                raise ValueError(f"{name} has {arr.shape}, not {N_STATES} states")


@dataclass(frozen=True)
class RegimeInputs:
    """One Regime as the Monte Carlo reads it, with what the artefact reports about it."""

    key: str                              # base | depression | hyperinflation | stagflation | deferral
    regime_id: str
    kind: str                             # base | scenario
    label: Words
    return_set_id: str
    curve: StateCurve
    #: base: ``latest`` (Allocation.curves.regime) and ``long_run``; scenario: ``projected`` months (m, 25).
    latest: Optional[np.ndarray] = None
    long_run: Optional[np.ndarray] = None
    projected: Optional[np.ndarray] = None
    horizon_months: Optional[int] = None
    inflation_pass_through: Optional[str] = None
    inflation_source: str = ""
    labels_summary: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class YearTable:
    """What a Regime's year ``k`` (row ``k - 1``) is: its distribution and the curve that applies."""

    dist: np.ndarray                      # (Y, 25), rows sum to one
    log_return: np.ndarray                # (Y, 25)
    log_inflation: np.ndarray             # (Y, 25)
    scenario_years: Optional[int]


def _normalise(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 0.0, None)
    total = p.sum()
    if not total > 0:
        raise ValueError("a state distribution without mass")
    return p / total


def base_weight(k: int, reversion_years: float) -> float:
    """How far year ``k`` (1-based) has reverted from the latest distribution to the long run."""
    if reversion_years <= 0:
        return 0.0 if k == 1 else 1.0
    return min((k - 1) / reversion_years, 1.0)


def year_table(regime: RegimeInputs, base: RegimeInputs, years: int, market: Market) -> YearTable:
    """Every simulated year's distribution and curve for one Regime."""
    if base.latest is None or base.long_run is None:
        raise ValueError("the base Regime needs its latest and long-run distributions")
    latest, long_run = _normalise(base.latest), _normalise(base.long_run)
    dist = np.empty((years, N_STATES))
    ret = np.empty((years, N_STATES))
    infl = np.empty((years, N_STATES))
    shock = 0
    if regime.kind == "scenario":
        if regime.projected is None or regime.horizon_months is None:
            raise ValueError(f"scenario {regime.key} carries no projected months")
        shock = min(int(market.scenario_years), int(regime.horizon_months) // 12, len(regime.projected) // 12)
    for k in range(1, years + 1):
        if k <= shock:
            dist[k - 1] = _normalise(regime.projected[12 * k - 1])
            ret[k - 1] = regime.curve.log_return
            infl[k - 1] = regime.curve.log_inflation
        else:
            w = base_weight(k, market.reversion_years)
            dist[k - 1] = _normalise(latest + (long_run - latest) * w)
            ret[k - 1] = base.curve.log_return
            infl[k - 1] = base.curve.log_inflation
    return YearTable(dist=dist, log_return=ret, log_inflation=infl,
                     scenario_years=shock if regime.kind == "scenario" else None)


@dataclass(frozen=True)
class Draws:
    """The random numbers of one run: shared by every Regime (common random numbers)."""

    uniforms: np.ndarray                  # (n_paths, years), stream state_uniforms
    property_noise: np.ndarray            # (n_paths, years), stream property_noise
    keep: Optional[np.ndarray] = None     # (n_paths, years), stream spare, read only when persistence > 0


def draws(seed: int, n_paths: int, years: int, *, persistence: float = 0.0) -> Draws:
    """``SeedSequence(seed).spawn(3)``: uniform state draws, property noise and a spare, in that order."""
    ss = np.random.SeedSequence(int(seed)).spawn(3)
    u = np.random.default_rng(ss[0]).random((n_paths, years))
    z = np.random.default_rng(ss[1]).standard_normal((n_paths, years))
    keep = np.random.default_rng(ss[2]).random((n_paths, years)) if persistence > 0 else None
    return Draws(uniforms=u, property_noise=z, keep=keep)


def states_for(table: YearTable, d: Draws, persistence: float = 0.0) -> np.ndarray:
    """The state index (0..24) of every path in every year: the shared uniform through this Regime's CDF."""
    n, years = d.uniforms.shape
    out = np.empty((n, years), dtype=np.int64)
    for k in range(years):
        cdf = np.cumsum(table.dist[k])
        s = np.minimum(np.searchsorted(cdf, d.uniforms[:, k], side="right"), N_STATES - 1)
        if persistence > 0 and k > 0 and d.keep is not None:
            s = np.where(d.keep[:, k] < persistence, out[:, k - 1], s)
        out[:, k] = s
    return out


def market_quantiles(table: YearTable) -> np.ndarray:
    """``z_mkt`` per year and state: the standard normal quantile of the state's mid-position in the CDF."""
    years = table.dist.shape[0]
    z = np.zeros((years, N_STATES))
    for k in range(years):
        before = 0.0
        for s in range(N_STATES):
            p = float(table.dist[k, s])
            mid = min(max(before + p / 2.0, 1e-12), 1.0 - 1e-12)
            z[k, s] = _NORMAL.inv_cdf(mid)
            before += p
    return z


@dataclass(frozen=True)
class PathMarket:
    """Per path and year: the portfolio's annual log return, the annual log inflation, property log growth."""

    states: np.ndarray                    # (n, Y) int, 0..24
    log_return: np.ndarray                # (n, Y)
    log_inflation: np.ndarray             # (n, Y)
    property_growth: np.ndarray           # (n, Y), nominal annual log growth
    z_market: np.ndarray                  # (n, Y)


def path_market(table: YearTable, d: Draws, prop: PropertyParameters, *, persistence: float = 0.0,
                states: Optional[np.ndarray] = None) -> PathMarket:
    """Everything the household simulation reads from the market, for every path. ``states`` fixes the state path
    (the parity tests); otherwise the shared uniforms choose it."""
    s = states_for(table, d, persistence) if states is None else np.asarray(states, dtype=np.int64)
    n, years = s.shape
    rows = np.arange(years)[None, :]
    lr = table.log_return[rows, s]
    li = table.log_inflation[rows, s]
    zq = market_quantiles(table)[rows, s]
    rho = prop.rho_with_market
    z = rho * zq + math.sqrt(max(0.0, 1.0 - rho * rho)) * d.property_noise[:, :years]
    g = (prop.nominal_log_growth + prop.inflation_beta * (li - prop.inflation_anchor_log)
         - 0.5 * prop.sigma * prop.sigma + prop.sigma * z)
    return PathMarket(states=s, log_return=lr, log_inflation=li, property_growth=g, z_market=zq)


def portfolio_curve(weights: dict[str, float], profiles: dict[str, np.ndarray]) -> np.ndarray:
    """``sum_i w_i * profile_i(s)`` for weights that are already what they should be (raw or renormalised)."""
    out = np.zeros(N_STATES)
    for iid, w in weights.items():
        if iid not in profiles:
            raise KeyError(iid)
        out = out + float(w) * profiles[iid]
    return out


def renormalised(raw: dict[str, float]) -> dict[str, float]:
    total = float(sum(raw.values()))
    if not total > 0:
        raise ValueError("the Allocation's raw weights do not sum to a positive total")
    return {k: float(v) / total for k, v in raw.items()}


def rule_words(market: Market) -> Words:
    """The sampling rule in words, for the artefact's ``market_model.rule``."""
    r = int(market.reversion_years) if float(market.reversion_years).is_integer() else market.reversion_years
    s = market.scenario_years
    return Words(
        de=("Jedes simulierte Jahr liegt in einem von 25 Marktzuständen, gezogen aus der Verteilung des Regimes. Das "
            f"erste Jahr ist die heutige Einschätzung der Allokation; sie kehrt in {r} Jahren linear zum "
            "langjährigen Mittel zurück. Die Rendite des Jahres ist die Summe der Gewichte mal der Rendite jedes "
            "Instruments im gezogenen Zustand, die Teuerung die des Zustands. Ein Szenario bestimmt die ersten "
            f"{s} Jahre mit seinen eigenen Zuständen, Renditen und Teuerungen, danach gilt die heutige "
            "Einschätzung. Jeder simulierte Verlauf zieht in jedem Regime dieselben Zufallszahlen."),
        en=("Each simulated year is in one of 25 market states, drawn from the Regime's distribution. The first year "
            f"is the allocation's current assessment, which reverts linearly to the long-run mean over {r} years. "
            "The year's return is the sum of the weights times each instrument's return in the drawn state, and "
            f"the inflation is that state's. A scenario drives the first {s} years with its own states, returns and "
            "inflation, then the current assessment applies. Every simulated path uses the same random numbers in "
            "every Regime."))
