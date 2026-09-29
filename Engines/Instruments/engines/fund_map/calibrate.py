"""The one-off calibration: eight return blocks, five phases, twenty-five states.

A port of ``3_returns.mlx``. For each block, the return realised in each of the five
market phases is averaged; the five means are then read onto the 25-state axis by
shape-preserving monotone interpolation.

**The 25-state axis is an interpolation of five estimates, not twenty-five estimates.**
This is the single most important thing to understand about the artefact. The reference
implementation evaluates the pchip on ``0.6:0.2:5.4`` over knots at ``1..5``, which places
five grid points in each phase band and puts the phase's own estimate at the middle one.
So exactly five of the twenty-five states carry a measured number; sixteen are
interpolated between them; and four -- the two at each end -- fall outside the hull of the
knots and are extrapolated. Each state carries the label that says which it is.

**Two deliberate divergences from System Build Manual section 11**, both recorded in the
emitted artefact rather than hidden:

1. Section 11.7 test 6 asks that extrapolation be impossible by construction. The
   reference extrapolates four states. Those four are reproduced and labelled
   ``extrapolated``, so the manual's intent -- never fill a tail silently -- is met by
   disclosure rather than by construction. Crisis drives CVaR downstream, and flattening
   the crisis tail to satisfy a test would be the more consequential error.
2. Section 11.2 specifies a sufficiency floor of six observations and a 20 % trimmed mean
   at twenty or more. The reference takes a plain mean at every count. Both are
   implemented; :data:`Estimator` selects between them and the choice is stamped on the
   calibration. ``PLAIN_MEAN`` is the default because it is what the published figures
   were produced under and what the regression fixture pins.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from engines.fund_map import numerics as num
from engines.fund_map.phases import PHASE_NAMES, PhaseTimeline
from store.etl.long_record import RawSeries

#: The 25-state grid, in phase-axis coordinates. Knots sit at 1..5; this grid runs from
#: 0.6 to 5.4 in steps of 0.2, so each phase owns five states and the phase estimate lands
#: on the middle one.
STATE_GRID_START = 0.6
STATE_GRID_STEP = 0.2
STATE_COUNT = 25

#: Phase knots on the same axis.
PHASE_KNOTS: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0)

#: Sufficiency floor and trim switch, from manual section 11.4.
SUFFICIENCY_FLOOR = 6
TRIM_SWITCH = 20
TRIM_FRACTION = 0.20


def state_axis() -> list[float]:
    """The 25 query points, in phase-axis coordinates."""
    return [STATE_GRID_START + STATE_GRID_STEP * i for i in range(STATE_COUNT)]


class Estimator(str, Enum):
    """Which per-phase central estimate to take."""

    #: Plain mean at every observation count. Reproduces Steiner (2021).
    PLAIN_MEAN = "plain_mean"
    #: Manual section 11.2: nothing below six, plain mean to nineteen, 20 % trimmed at
    #: twenty and above.
    MANUAL_FLOOR = "manual_floor"


class Method(str, Enum):
    """How a single state's value came to exist. Travels with the number, always.

    The first five are produced by the one-off calibration; ``BORROWED`` and ``SEED`` are
    the last two rungs of the per-instrument cascade in ``estimate.py``. They share one
    enum because they share one contract field: a consumer reading a ReturnSet must be
    able to tell a measurement from a fill without knowing which code path produced it.
    """

    DATA_DRIVEN = "data-driven"
    DATA_DRIVEN_TRIMMED = "data-driven-trimmed"
    INTERPOLATED = "interpolated"
    EXTRAPOLATED = "extrapolated"
    BORROWED = "borrowed"
    #: Shape inherited from the calibrated role profile, level and amplitude fitted from
    #: the instrument's own returns. Two parameters from every month it has, rather than
    #: twenty-five means from roughly two hundred observations. Stronger than a borrow,
    #: because the numbers come from this instrument; weaker than a per-state mean,
    #: because the shape across states was not measured here.
    SHAPE_SCALED = "shape-scaled"
    #: The 12 month forward measurement (per phase, read onto the states by pchip) after
    #: the light smoothing step across neighbouring states in ``forward.smooth_profile``.
    #: The default estimator since 29.09.2026 (FMRE-22). Rests on the instrument's own
    #: measured phases, so stronger than a shape-scaled fill; weaker than an unsmoothed
    #: state, because the smoother moved it (by at most ``SMOOTHING_TOLERANCE`` at a knot).
    FORWARD_SMOOTHED = "forward-12m-smoothed"
    SEED = "seed"
    INSUFFICIENT = "insufficient"


#: Methods ordered weakest to strongest support. A composite -- a role built from blocks,
#: or a profile summarised by its ``coverage`` field -- is labelled by the weakest method
#: it contains, so a single seeded state cannot hide inside an otherwise measured profile.
METHOD_STRENGTH: tuple[Method, ...] = (
    Method.INSUFFICIENT,
    Method.SEED,
    Method.BORROWED,
    Method.SHAPE_SCALED,
    Method.FORWARD_SMOOTHED,
    Method.EXTRAPOLATED,
    Method.INTERPOLATED,
    Method.DATA_DRIVEN,
    Method.DATA_DRIVEN_TRIMMED,
)


@dataclass(frozen=True)
class BlockSpec:
    """One of the eight building blocks of the long record."""

    key: str
    label: str
    role: str | None
    #: ``level`` series are log-differenced into returns; ``rate`` series are already the
    #: quantity of interest and are read straight through.
    kind: str
    note: str


#: The register, in the order manual section 11.3 lists it. ``long_rate`` carries no role:
#: it is a rate, not a holding, and ``gov_bonds`` is what an investor actually earned.
BLOCKS: tuple[BlockSpec, ...] = (
    BlockSpec("short_rate", "1-yr T-bill", "stabilisation", "rate",
              "Falls in crisis, rises as conditions improve. Also the risk-free proxy."),
    BlockSpec("long_rate", "10-year Treasury", None, "rate",
              "A rate, not a return. Carried for completeness; gov_bonds is the holding."),
    BlockSpec("equity", "Equity", "gain", "level",
              "Nearly linear in the market environment."),
    BlockSpec("gov_bonds", "Government bond returns", "protection", "rate",
              "Flight to safety: a jump once contraction tips into crisis."),
    BlockSpec("commodities", "Commodity index", "stabilisation", "level",
              "Peaks in contraction -- it pays before the damage, not during it."),
    BlockSpec("gold", "Gold", "protection", "level",
              "Peaks in crisis, negative in boom. The cleanest Protection case."),
    BlockSpec("agriculture", "Agriculture", "stabilisation", "level",
              "Best in contraction, positive across most phases, with an Income component."),
    BlockSpec("real_estate", "Real estate", "income", "level",
              "Collapses in crisis, otherwise stable. Emphatically not Stabilisation."),
)

BLOCKS_BY_KEY = {b.key: b for b in BLOCKS}


def _log_diff(values: Sequence[float]) -> list[float]:
    if any(v <= 0.0 for v in values):
        raise ValueError("log differences need strictly positive levels")
    return [math.log(b) - math.log(a) for a, b in zip(values, values[1:])]


@dataclass(frozen=True)
class BlockReturns:
    """One block's annual return series, and the years it covers."""

    key: str
    first_year: int
    last_year: int
    values: tuple[float, ...]


def build_block_returns(record: dict[str, RawSeries]) -> dict[str, BlockReturns]:
    """Assemble the eight annual return series from the long record.

    Three blocks are shorter than the others and say so in their window rather than being
    padded: government bond total returns stop in 2015, real estate starts in 1891, and
    agriculture starts in 1911.

    The series are nominal and are **not** de-trended. The reference computes de-trended
    residuals for each of them and then does not use them -- ``rr_* = rts_*`` -- which is
    the same choice manual section 11.3 states: real is obtained by subtracting current
    inflation at the point of use, so that a figure cannot silently over- or under-state
    the expected return.
    """
    out: dict[str, BlockReturns] = {}

    out["short_rate"] = BlockReturns("short_rate", 1871, 2020,
                                     tuple(record["bill"].window(1871, 2020)))
    out["long_rate"] = BlockReturns("long_rate", 1871, 2020,
                                    tuple(record["bond"].window(1871, 2020)))
    out["equity"] = BlockReturns("equity", 1871, 2020,
                                 tuple(_log_diff(record["spx"].window(1870, 2020))))
    out["gov_bonds"] = BlockReturns("gov_bonds", 1871, 2015,
                                    tuple(record["bondtr"].window(1871, 2015)))

    oil = _log_diff(record["oil"].window(1870, 2020))
    wheat = _log_diff(record["wheat"].window(1870, 2020))
    out["commodities"] = BlockReturns(
        "commodities", 1871, 2020, tuple(0.5 * o + 0.5 * w for o, w in zip(oil, wheat))
    )

    out["gold"] = BlockReturns("gold", 1871, 2020,
                               tuple(_log_diff(record["gold"].window(1870, 2020))))
    out["agriculture"] = BlockReturns("agriculture", 1911, 2020,
                                      tuple(_log_diff(record["ag"].window(1910, 2020))))
    out["real_estate"] = BlockReturns("real_estate", 1891, 2020,
                                      tuple(_log_diff(record["house"].window(1890, 2020))))
    return out


@dataclass(frozen=True)
class PhaseEstimate:
    """The central estimate and spread for one block in one phase."""

    phase: str
    n_obs: int
    mean: float | None
    std: float | None
    method: Method


@dataclass(frozen=True)
class BlockProfile:
    """One block's 25-state profile, with the provenance of every value."""

    key: str
    label: str
    role: str | None
    first_year: int
    last_year: int
    n_obs_total: int
    phase_estimates: tuple[PhaseEstimate, ...]
    profile_by_state: tuple[float, ...]
    methods_by_state: tuple[Method, ...]
    n_obs_by_state: tuple[int, ...]

    @property
    def phase_means(self) -> tuple[float, ...]:
        return tuple(e.mean for e in self.phase_estimates)  # type: ignore[misc]


def _estimate_phase(values: list[float], estimator: Estimator, phase: str) -> PhaseEstimate:
    n = len(values)
    if n == 0:
        return PhaseEstimate(phase, 0, None, None, Method.INSUFFICIENT)
    spread = num.std(values) if n >= 2 else 0.0

    if estimator is Estimator.PLAIN_MEAN:
        return PhaseEstimate(phase, n, num.mean(values), spread, Method.DATA_DRIVEN)

    if n < SUFFICIENCY_FLOOR:
        # Returned as nothing, never as a noisy estimate.
        return PhaseEstimate(phase, n, None, spread, Method.INSUFFICIENT)
    if n >= TRIM_SWITCH:
        return PhaseEstimate(
            phase, n, num.trimmed_mean(values, TRIM_FRACTION), spread,
            Method.DATA_DRIVEN_TRIMMED,
        )
    return PhaseEstimate(phase, n, num.mean(values), spread, Method.DATA_DRIVEN)


def state_methods(phase_methods: Sequence[Method]) -> list[Method]:
    """Label each of the 25 states by how its value was produced.

    A state that sits exactly on a phase knot inherits that phase's own label. A state
    inside the hull of the knots is ``interpolated``. A state outside it -- the two at
    each end -- is ``extrapolated``.
    """
    axis = state_axis()
    lo, hi = PHASE_KNOTS[0], PHASE_KNOTS[-1]
    out: list[Method] = []
    for q in axis:
        knot = next((i for i, k in enumerate(PHASE_KNOTS) if abs(q - k) < 1e-12), None)
        if knot is not None:
            out.append(phase_methods[knot])
        elif q < lo or q > hi:
            out.append(Method.EXTRAPOLATED)
        else:
            out.append(Method.INTERPOLATED)
    return out


def state_observation_counts(phase_counts: Sequence[int]) -> list[int]:
    """``n_obs`` per state: the phase's count at a knot, zero everywhere else.

    Manual section 11.2 requires every filled value to carry ``n_obs = 0``, so that a
    reader can tell a measurement from a fill without consulting the method label as well.
    """
    axis = state_axis()
    out: list[int] = []
    for q in axis:
        knot = next((i for i, k in enumerate(PHASE_KNOTS) if abs(q - k) < 1e-12), None)
        out.append(phase_counts[knot] if knot is not None else 0)
    return out


def calibrate_block(
    returns: BlockReturns,
    timeline: PhaseTimeline,
    *,
    estimator: Estimator = Estimator.PLAIN_MEAN,
) -> BlockProfile:
    """Bucket one block's returns by phase and interpolate onto the 25-state axis."""
    spec = BLOCKS_BY_KEY[returns.key]
    phases = timeline.slice_years(returns.first_year, returns.last_year)
    if len(phases) != len(returns.values):
        raise ValueError(
            f"block {returns.key!r} has {len(returns.values)} returns but its window "
            f"covers {len(phases)} phase-labelled years"
        )

    buckets: list[list[float]] = [[] for _ in PHASE_NAMES]
    for phase_index, value in zip(phases, returns.values):
        buckets[phase_index].append(value)

    estimates = tuple(
        _estimate_phase(buckets[i], estimator, PHASE_NAMES[i]) for i in range(len(PHASE_NAMES))
    )

    missing = [e.phase for e in estimates if e.mean is None]
    if missing:
        raise ValueError(
            f"block {returns.key!r} has no usable estimate for phase(s) {', '.join(missing)}. "
            f"The 25-state axis is interpolated from all five phase knots, so a missing knot "
            f"cannot be interpolated around -- this block needs the cascade, not calibration."
        )

    means = [e.mean for e in estimates]
    profile = num.pchip_eval(list(PHASE_KNOTS), means, state_axis())  # type: ignore[arg-type]

    return BlockProfile(
        key=returns.key,
        label=spec.label,
        role=spec.role,
        first_year=returns.first_year,
        last_year=returns.last_year,
        n_obs_total=len(returns.values),
        phase_estimates=estimates,
        profile_by_state=tuple(profile),
        methods_by_state=tuple(state_methods([e.method for e in estimates])),
        n_obs_by_state=tuple(state_observation_counts([e.n_obs for e in estimates])),
    )


def calibrate_all(
    block_returns: dict[str, BlockReturns],
    timeline: PhaseTimeline,
    *,
    estimator: Estimator = Estimator.PLAIN_MEAN,
) -> dict[str, BlockProfile]:
    """Calibrate every registered block."""
    return {
        spec.key: calibrate_block(block_returns[spec.key], timeline, estimator=estimator)
        for spec in BLOCKS
    }
