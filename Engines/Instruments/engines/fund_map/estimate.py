"""Estimating one instrument's 25-state profile from its own monthly returns.

The calibration in ``calibrate.py`` is a one-off, run against the long annual record. This
module is the part that runs whenever an instrument is added or its history extends: it
takes whatever monthly returns exist, labels each month with a calibration state through
the quantile bridge, and estimates what it can. What it cannot estimate, it fills through
a strict cascade -- and every filled value says so.

**The cascade, in order, with no silent fills.**

==  ==================  ======================================================
1   own data            Buckets clearing the sufficiency floor. ``data-driven``
                        below the trim switch, ``data-driven-trimmed`` at or above.
2   interpolate         Shape-preserving monotone interpolation across the state
                        axis, known states as knots. **Inside the convex hull only.**
3   borrow              The closest match among registered peers, found by
                        correlation over the overlapping months.
4   seed                The calibrated role profile.
==  ==================  ======================================================

Note that step 2 here *does* respect the no-extrapolation rule, unlike the one-off
calibration. The difference is not inconsistency: the calibration reproduces a published
reference whose tails are part of the published figures, whereas this estimator is new
code with no such obligation, and outside the hull of an instrument's own observed states
lie crisis and boom -- exactly where a fabricated value does the most damage. Outside the
hull the estimator falls through to borrow instead.

**Units.** The calibrated profiles are annual log returns. Instrument feeds arrive as
simple monthly returns, so a bucket's estimate is ``12 * mean(log(1 + r))``. Mixing the
two conventions would be invisible and would misprice every state by roughly half a
variance, so the conversion happens once, here, and :data:`RETURN_UNIT` names the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from engines.fund_map import numerics as num
from engines.fund_map.calibrate import (
    METHOD_STRENGTH,
    STATE_COUNT,
    SUFFICIENCY_FLOOR,
    TRIM_FRACTION,
    TRIM_SWITCH,
    Method,
)
from engines.fund_map.roles import RoleProfile
from engines.fund_map.state_map import StateMap

#: What an emitted profile value means.
RETURN_UNIT = "annualised_log_return"

#: A correlation computed on fewer overlapping months than this is not evidence of
#: similarity. Two years is the shortest window in which a monthly correlation carries
#: any information about behaviour across conditions.
MIN_OVERLAP_MONTHS = 24

#: Below this correlation, the "closest" match is not close, and borrowing from it would
#: dress up a role-level seed as a peer estimate. The cascade falls through to seed.
MIN_MATCH_CORRELATION = 0.30

#: Two instruments are treated as the same evidence when their monthly returns agree to
#: this tolerance over the shared window.
IDENTICAL_TOLERANCE = 1e-12


class ProfileMethod(str, Enum):
    """Which estimator builds an instrument's 25-state profile.

    **CASCADE is what the manual describes** and remains the default: measure each state
    from the months that fell in it, interpolate inside the hull, borrow, then seed.

    **SHAPE_SCALED is option D2 from the September 2026 diagnosis.** The cascade tries to
    read twenty-five conditional means from roughly two hundred monthly observations, so
    most buckets hold a handful of months: the mean jump between adjacent states was
    8.36 % against a mean standard error of 6.21 %, which is to say the curve between
    measured states was mostly noise. It also measures at a monthly horizon while the
    calibration measures at an annual one, and the same crisis months give -12.51 % over
    the month and +11.67 % over the following year -- which is how a gold-bearing
    instrument ended up with an inverted crisis sign.

    D2 estimates two parameters instead of twenty-five. It takes the *shape* across
    states from the 150-year role calibration, which is measured on annual data and has
    every state populated, and fits only a level and an amplitude to the instrument's own
    returns. Fewer parameters, every month used for both, and no state left to a handful
    of observations.

    **FORWARD_12M is the 12 month forward measurement (review R-003, decision D-02).** It
    keeps the per-instrument measurement the cascade stands for but fixes its horizon:
    each month's state is credited with the log return over the 12 months that follow,
    estimated per phase with an honest count of independent years, and read onto the 25
    states by the calibration's own pchip. See ``engines/fund_map/forward.py``.

    **FORWARD_12M_SMOOTHED is the served default since 29 September 2026** (owner's
    decision on review R-002, FMRE-22): FORWARD_12M followed by a light, shape-preserving
    smoother across neighbouring states (``forward.smooth_forward``), each state labelled
    ``forward-12m-smoothed`` or with the fill it rests on.

    All four are implemented; the choice is recorded on every value through the method
    label, so a reader can always tell which produced a number. The engine's default is
    ``service.DEFAULT_PROFILE_METHOD``. The stored profiles (``instrument_profile``) stay
    the cascade's, because they are the cascade's peer basis for borrowing, and this
    function's own default stays CASCADE for the same reason.
    """

    CASCADE = "cascade"
    SHAPE_SCALED = "shape_scaled"
    FORWARD_12M = "forward_12m"
    FORWARD_12M_SMOOTHED = "forward_12m_smoothed"


#: Fewest monthly observations D2 will estimate a level and a volatility from. Two years
#: is the same floor the borrow cascade uses for an overlap.
MIN_SHAPE_MONTHS = 24


class BorrowMode(str, Enum):
    """How a peer's profile is transferred to the target."""

    #: Take the peer's values unchanged. The manual's literal reading of "borrow".
    PROFILE = "profile"
    #: Take the peer's deviations from its own average and re-centre them on the target's
    #: own observed average. Keeps the peer's *shape* -- which is what the match measured
    #: -- while respecting the level the target's own returns actually show.
    SHAPE_ANCHORED = "shape_anchored"


@dataclass(frozen=True)
class MonthlyReturn:
    period: str   # YYYY-MM
    value: float  # simple monthly return, decimal


@dataclass(frozen=True)
class StateBucket:
    state: int            # 1..25
    n_obs: int
    value: float | None   # annualised log return
    method: Method


@dataclass(frozen=True)
class EstimatedProfile:
    instrument_id: str
    role: str
    n_obs_total: int
    profile_by_state: tuple[float, ...]
    methods_by_state: tuple[Method, ...]
    #: Observations *behind* each value. A filled state reports zero, always -- manual
    #: section 11.2 -- so that a reader can tell a measurement from a fill by looking at
    #: either this or the method, rather than having to cross-check both.
    n_obs_by_state: tuple[int, ...]
    #: Observations that existed but fell below the sufficiency floor and were therefore
    #: discarded. Kept because "this state has five observations, which is not enough" and
    #: "this state has none" are different facts about the world, and zeroing ``n_obs``
    #: would erase the difference. Diagnostic only; it is not part of the ReturnSet.
    n_obs_discarded_by_state: tuple[int, ...]
    borrowed_from: str | None
    match_score: float | None
    coverage: Method
    unit: str = RETURN_UNIT

    def as_state_rows(self) -> list[dict[str, object]]:
        return [
            {
                "state": i + 1,
                "value": self.profile_by_state[i],
                "method": self.methods_by_state[i].value,
                "n_obs": self.n_obs_by_state[i],
            }
            for i in range(STATE_COUNT)
        ]


def label_months(
    returns: Sequence[MonthlyReturn],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
) -> list[tuple[int, float]]:
    """Attach a calibration state to each monthly return.

    ``signal_by_period`` maps a period to that month's **modal** Market Risk Signal state.
    The modal reading is used rather than the full distribution because bucketing needs a
    single label per month -- which is exactly the reason the Regime contract publishes an
    integer path alongside its distributions.

    Months with no signal are dropped. A return that cannot be placed on the state axis is
    not evidence about any state.
    """
    out: list[tuple[int, float]] = []
    for item in returns:
        signal_state = signal_by_period.get(item.period)
        if signal_state is None:
            continue
        if item.value <= -1.0:
            continue  # a total loss breaks the log transform; treat as unusable
        out.append((state_map.state_for(signal_state), math.log1p(item.value)))
    return out


def bucket_by_state(labelled: Sequence[tuple[int, float]]) -> list[list[float]]:
    buckets: list[list[float]] = [[] for _ in range(STATE_COUNT)]
    for state, log_return in labelled:
        buckets[state - 1].append(log_return)
    return buckets


def estimate_buckets(buckets: Sequence[Sequence[float]]) -> list[StateBucket]:
    """Apply the sufficiency floor and the trim switch to each state bucket."""
    out: list[StateBucket] = []
    for index, values in enumerate(buckets):
        n = len(values)
        if n < SUFFICIENCY_FLOOR:
            # Returned as nothing, never as a noisy estimate.
            out.append(StateBucket(index + 1, n, None, Method.INSUFFICIENT))
        elif n >= TRIM_SWITCH:
            out.append(StateBucket(index + 1, n, 12.0 * num.trimmed_mean(values, TRIM_FRACTION),
                                   Method.DATA_DRIVEN_TRIMMED))
        else:
            out.append(StateBucket(index + 1, n, 12.0 * num.mean(values), Method.DATA_DRIVEN))
    return out


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson correlation, or ``None`` if either side is constant."""
    if len(a) != len(b) or len(a) < 2:
        return None
    ma, mb = num.mean(a), num.mean(b)
    saa = math.fsum((x - ma) ** 2 for x in a)
    sbb = math.fsum((x - mb) ** 2 for x in b)
    if saa <= 0.0 or sbb <= 0.0:
        return None
    sab = math.fsum((x - ma) * (y - mb) for x, y in zip(a, b))
    return sab / math.sqrt(saa * sbb)


@dataclass(frozen=True)
class Candidate:
    """A registered peer that already has a profile, offered as a borrowing source."""

    instrument_id: str
    role: str
    region_scope: str | None
    returns: Mapping[str, float]        # period -> simple monthly return
    profile_by_state: Sequence[float]


@dataclass(frozen=True)
class Match:
    instrument_id: str
    score: float
    overlap_months: int
    same_role: bool


def find_closest_match(
    target_returns: Mapping[str, float],
    candidates: Sequence[Candidate],
    *,
    role: str,
    region_scope: str | None = None,
    min_overlap: int = MIN_OVERLAP_MONTHS,
) -> Match | None:
    """Find the peer whose monthly returns move most like the target's.

    **Role and region narrow the field before correlation ranks it**, which is the order
    manual section 11.2 states: the cascade borrows "the role-and-region peer profile".
    Correlation alone would happily match a long-volatility instrument to an equity index
    with a strongly negative -- and therefore strongly informative -- relationship, and
    borrowing a profile from something that behaves oppositely is worse than seeding.

    **The search does not widen past the role.** An earlier version fell back to every
    role when no same-role peer cleared the thresholds, and the result was CHF Cash
    borrowing its crisis behaviour from Global Equities on a correlation of 0.41 -- a
    number high enough to pass a threshold and meaningless as a statement about cash.
    A cross-role match is not a weaker version of the right answer; it is a different and
    wrong one. When no peer in the role qualifies, this returns ``None`` and the cascade
    falls through to the role seed, which is at least the correct shape.
    """
    def rank(pool: Sequence[Candidate], same_role: bool) -> Match | None:
        best: Match | None = None
        for candidate in pool:
            shared = sorted(set(target_returns) & set(candidate.returns))
            if len(shared) < min_overlap:
                continue
            # **A peer with identical returns is not a second opinion.** Several
            # instruments in the register share one public proxy, so their monthly
            # returns are equal to the last decimal -- 365 of 365 months for the three
            # Swiss entries on EWL. Borrowing across such a pair moves no information at
            # all; it only relabels a bucket that had too little data as `borrowed`,
            # which reads as evidence and is not. Correlation cannot catch this: it is
            # exactly 1.0, the best possible score, so the degenerate peer wins the rank.
            if all(abs(target_returns[p] - candidate.returns[p]) <= IDENTICAL_TOLERANCE
                   for p in shared):
                continue
            score = correlation(
                [target_returns[p] for p in shared],
                [candidate.returns[p] for p in shared],
            )
            if score is None or score < MIN_MATCH_CORRELATION:
                continue
            if best is None or score > best.score:
                best = Match(candidate.instrument_id, score, len(shared), same_role)
        return best

    in_role = [c for c in candidates if c.role == role]
    if region_scope is not None:
        narrowed = [c for c in in_role if c.region_scope == region_scope]
        if narrowed:
            found = rank(narrowed, True)
            if found is not None:
                return found
    return rank(in_role, True)


def _interpolate_known(buckets: Sequence[StateBucket]) -> dict[int, float]:
    """Fill the gaps between known states, inside their convex hull only."""
    known = [(b.state, b.value) for b in buckets if b.value is not None]
    if len(known) < 2:
        return {}
    xs = [float(s) for s, _ in known]
    ys = [v for _, v in known]  # type: ignore[misc]
    lo, hi = xs[0], xs[-1]
    targets = [
        float(b.state) for b in buckets
        if b.value is None and lo < float(b.state) < hi
    ]
    if not targets:
        return {}
    values = num.pchip_eval(xs, ys, targets)
    return {int(t): v for t, v in zip(targets, values)}


@dataclass(frozen=True)
class ShapeFit:
    """The two numbers D2 estimates, and what they were fitted on."""

    level: float        # annualised log return: where the instrument sits
    amplitude: float    # k: how far it swings relative to its role's shape
    own_volatility: float
    role_volatility: float
    observations: int


def _annualised(returns: Sequence[MonthlyReturn]) -> tuple[float, float] | None:
    """Annualised mean and standard deviation of one instrument's monthly log returns."""
    logs = [math.log1p(r.value) for r in returns if r.value > -1.0]
    if len(logs) < MIN_SHAPE_MONTHS:
        return None
    return num.mean(logs) * 12.0, num.std(logs) * math.sqrt(12.0)


def fit_shape(
    returns: Sequence[MonthlyReturn],
    peers: Sequence[Candidate],
    *,
    role: str,
) -> ShapeFit | None:
    """Fit ``value(s) = level + k * shape(s)``, with ``k = vol_i / vol_role``.

    **Both parameters come from the whole return series, not from the state buckets.**
    That is the point of D2. An earlier version of this function fitted the amplitude by
    regressing the bucket means on the role shape, which reads better on paper and is
    wrong in practice: the bucket means are the noisy quantity the estimator exists to
    stop trusting, so the slope inherited their noise and came back at +26 for CS Long
    Vola and -2.83 for Precious Metals. An instrument does not swing twenty-six times as
    hard as its role.

    ``vol_role`` is the median annualised volatility of the instruments in the same role
    that have their own history. The specification said "vol_role" without pinning it
    down, and this is the reading that keeps the ratio dimensionless and centred near one
    by construction: an instrument more volatile than its role's peers expresses the
    role's state dependence more strongly, and one less volatile expresses it less.

    Note what this deliberately cannot do: it never flips the sign of the role's shape.
    An instrument that genuinely moves against its role is a statement about its role
    assignment, not something an amplitude should quietly encode.
    """
    own = _annualised(returns)
    if own is None:
        return None
    level, own_vol = own

    peer_vols = []
    for peer in peers:
        if peer.role != role:
            continue
        measured = _annualised(
            [MonthlyReturn(p, v) for p, v in peer.returns.items()])
        if measured is not None and measured[1] > 0:
            peer_vols.append(measured[1])
    if not peer_vols:
        return None
    ordered = sorted(peer_vols)
    middle = len(ordered) // 2
    role_vol = (ordered[middle] if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / 2.0)
    if role_vol <= 0:
        return None

    return ShapeFit(level, own_vol / role_vol, own_vol, role_vol, len(returns))


def estimate_instrument(
    instrument_id: str,
    role: str,
    returns: Sequence[MonthlyReturn],
    signal_by_period: Mapping[str, int],
    state_map: StateMap,
    role_profile: RoleProfile,
    *,
    candidates: Sequence[Candidate] = (),
    region_scope: str | None = None,
    borrow_mode: BorrowMode = BorrowMode.SHAPE_ANCHORED,
    profile_method: ProfileMethod = ProfileMethod.CASCADE,
) -> EstimatedProfile:
    """Build one instrument's 25-state profile, by whichever estimator is selected."""
    if profile_method in (ProfileMethod.FORWARD_12M, ProfileMethod.FORWARD_12M_SMOOTHED):
        # Imported here: forward.py builds on this module's types.
        from engines.fund_map.forward import estimate_forward, smooth_forward
        result = estimate_forward(
            instrument_id, role, {r.period: r.value for r in returns}, signal_by_period,
            state_map, role_profile, fit=fit_shape(returns, candidates, role=role),
        )
        if profile_method is ProfileMethod.FORWARD_12M_SMOOTHED:
            result = smooth_forward(result)
        return result.profile

    labelled = label_months(returns, signal_by_period, state_map)
    buckets = estimate_buckets(bucket_by_state(labelled))

    values: list[float | None] = [b.value for b in buckets]
    methods: list[Method] = [b.method for b in buckets]
    # An estimated bucket reports its count; a bucket that fell below the floor reports
    # zero and its count moves to the discarded column.
    counts: list[int] = [b.n_obs if b.value is not None else 0 for b in buckets]
    discarded: list[int] = [b.n_obs if b.value is None else 0 for b in buckets]

    if profile_method is ProfileMethod.SHAPE_SCALED:
        fit = fit_shape(returns, candidates, role=role)
        if fit is not None:
            centre = num.mean(list(role_profile.profile_by_state))
            scaled = [
                fit.level + fit.amplitude * (role_profile.profile_by_state[i] - centre)
                for i in range(STATE_COUNT)
            ]
            return EstimatedProfile(
                instrument_id=instrument_id,
                role=role,
                n_obs_total=len(labelled),
                profile_by_state=tuple(scaled),
                methods_by_state=tuple([Method.SHAPE_SCALED] * STATE_COUNT),
                # Every state rests on the whole sample, not on the months that landed in
                # it, so reporting a per-state count would misdescribe the estimator.
                n_obs_by_state=tuple([fit.observations] * STATE_COUNT),
                n_obs_discarded_by_state=tuple(discarded),
                borrowed_from=None,
                match_score=fit.amplitude,
                coverage=Method.SHAPE_SCALED,
            )
        # Too little of its own data to fit even two parameters. Fall through to the
        # cascade rather than invent a shape, and the method labels will say so.

    # Step 2 -- interpolate inside the hull.
    for state, value in _interpolate_known(buckets).items():
        values[state - 1] = value
        methods[state - 1] = Method.INTERPOLATED

    # Step 3 -- borrow from the closest match.
    by_period = {r.period: r.value for r in returns}
    match = find_closest_match(
        by_period, candidates, role=role, region_scope=region_scope
    ) if candidates else None

    borrowed_profile: Sequence[float] | None = None
    if match is not None:
        peer = next(c for c in candidates if c.instrument_id == match.instrument_id)
        borrowed_profile = list(peer.profile_by_state)
        if borrow_mode is BorrowMode.SHAPE_ANCHORED:
            observed = [v for v in values if v is not None]
            if observed:
                shift = num.mean(observed) - num.mean(borrowed_profile)
                borrowed_profile = [v + shift for v in borrowed_profile]

    for index in range(STATE_COUNT):
        if values[index] is not None:
            continue
        if borrowed_profile is not None:
            values[index] = borrowed_profile[index]
            methods[index] = Method.BORROWED
        else:
            # Step 4 -- seed from the calibrated role profile.
            values[index] = role_profile.profile_by_state[index]
            methods[index] = Method.SEED

    resolved = [v for v in values if v is not None]
    if len(resolved) != STATE_COUNT:
        raise AssertionError("the cascade left a state unfilled, which it cannot do")

    coverage = min(methods, key=METHOD_STRENGTH.index)

    return EstimatedProfile(
        instrument_id=instrument_id,
        role=role,
        n_obs_total=len(labelled),
        profile_by_state=tuple(resolved),
        methods_by_state=tuple(methods),
        n_obs_by_state=tuple(counts),
        n_obs_discarded_by_state=tuple(discarded),
        borrowed_from=match.instrument_id if match else None,
        match_score=match.score if match else None,
        coverage=coverage,
    )
