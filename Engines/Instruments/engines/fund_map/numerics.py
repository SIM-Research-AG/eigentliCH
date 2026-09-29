"""The numerical primitives the Fund Map calibration needs, written out in full.

Every function here exists because the reference implementation -- Steiner (2021),
``Model/ecn_model/*.mlx`` -- calls a MATLAB builtin, and the port has to reproduce that
builtin's *exact* convention rather than a plausible one. Where MATLAB and the obvious
Python spelling disagree, the MATLAB convention wins and the docstring says so.

The alternative was numpy plus scipy for two interpolators and a curve fit. The whole of
this module is smaller than that import, it has no build step, and -- the reason that
actually matters -- it is deterministic across platforms, which System Build Manual
section 6 requires of every engine run.
"""

from __future__ import annotations

import math
from typing import Sequence

Vector = Sequence[float]


# ---------------------------------------------------------------------------
# Location and spread
# ---------------------------------------------------------------------------


def mean(xs: Vector) -> float:
    """Arithmetic mean. Raises on an empty sample rather than returning nan."""
    n = len(xs)
    if n == 0:
        raise ValueError("mean of an empty sample")
    return math.fsum(xs) / n


def std(xs: Vector) -> float:
    """Sample standard deviation, normalised by ``N - 1``.

    MATLAB's ``std`` defaults to the N-1 normalisation and the reference implementation
    never passes the flag, so N-1 is the convention the published figures were produced
    under. A population standard deviation here would shift every standardised indicator
    by a factor of ``sqrt(N/(N-1))`` and move the phase boundaries with it.
    """
    n = len(xs)
    if n < 2:
        raise ValueError("standard deviation needs at least two observations")
    m = mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (n - 1))


def standardise(xs: Vector) -> list[float]:
    """Centre on the mean and scale by the sample standard deviation."""
    m = mean(xs)
    s = std(xs)
    if s == 0.0:
        raise ValueError("cannot standardise a constant series")
    return [(x - m) / s for x in xs]


def trimmed_mean(xs: Vector, proportion: float) -> float:
    """Symmetric trimmed mean, trimming ``proportion`` from *each* tail.

    System Build Manual section 11.2 specifies a "20 % trimmed mean" at or above twenty
    observations. This reads that as 20 % from each end -- the usual convention, and the
    one that makes the estimator resistant to a two-sided outlier. The count removed per
    tail is ``floor(n * proportion)``, so twenty observations lose four from each end and
    the estimate is the mean of the middle twelve.
    """
    if not 0.0 <= proportion < 0.5:
        raise ValueError("trim proportion must be in [0, 0.5)")
    ordered = sorted(xs)
    n = len(ordered)
    k = int(n * proportion)
    kept = ordered[k : n - k] if k else ordered
    if not kept:
        raise ValueError("trimming removed every observation")
    return mean(kept)


# ---------------------------------------------------------------------------
# De-trending
# ---------------------------------------------------------------------------


def polyfit1_residuals(ys: Vector) -> list[float]:
    """Residuals from an OLS straight line fitted against ``x = 1..n``.

    This is MATLAB's ``fit(x', y, 'poly1')`` followed by ``mdl.residuals``. Seven of the
    eight economic indicators are de-trended this way; the eighth is exponential, below.
    """
    n = len(ys)
    if n < 2:
        raise ValueError("a linear trend needs at least two observations")
    xs = [float(i + 1) for i in range(n)]
    mx = mean(xs)
    my = mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    return [y - (intercept + slope * x) for x, y in zip(xs, ys)]


def expfit1_residuals(ys: Vector, *, max_iter: int = 500, tol: float = 1e-15) -> list[float]:
    """Residuals from ``a * exp(b * x)`` fitted by nonlinear least squares, ``x = 1..n``.

    MATLAB's ``fit(x', y, 'exp1')``. Debt saturation is the one indicator de-trended
    exponentially, because a debt-to-GDP ratio compounds; fitting it with a straight line
    would leave a curved residual and manufacture a trend in the economic cycle.

    Solved by Levenberg-Marquardt from a log-linear starting point. The log-linear fit
    (regressing ``log y`` on ``x``) minimises relative rather than absolute error, so it
    is a starting value and not the answer -- but it is close enough that the descent is
    short and lands in the same basin MATLAB's trust-region method finds.

    Requires strictly positive observations, which a debt-to-GDP ratio always is.
    """
    n = len(ys)
    if n < 2:
        raise ValueError("an exponential trend needs at least two observations")
    if any(y <= 0.0 for y in ys):
        raise ValueError("exp1 starting values require strictly positive observations")

    xs = [float(i + 1) for i in range(n)]

    logs = [math.log(y) for y in ys]
    mx = mean(xs)
    ml = mean(logs)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    b = math.fsum((x - mx) * (l - ml) for x, l in zip(xs, logs)) / sxx
    a = math.exp(ml - b * mx)

    def sse(a_: float, b_: float) -> float:
        return math.fsum((y - a_ * math.exp(b_ * x)) ** 2 for x, y in zip(xs, ys))

    lam = 1e-3
    current = sse(a, b)
    for _ in range(max_iter):
        jaa = jab = jbb = ga = gb = 0.0
        for x, y in zip(xs, ys):
            e = math.exp(b * x)
            r = y - a * e
            da = -e
            db = -a * x * e
            jaa += da * da
            jab += da * db
            jbb += db * db
            ga += da * r
            gb += db * r

        improved = False
        for _ in range(80):
            m00 = jaa * (1.0 + lam)
            m11 = jbb * (1.0 + lam)
            det = m00 * m11 - jab * jab
            if det == 0.0:
                break
            step_a = (-ga * m11 + gb * jab) / det
            step_b = (-gb * m00 + ga * jab) / det
            trial = sse(a + step_a, b + step_b)
            if trial < current:
                a += step_a
                b += step_b
                delta = current - trial
                current = trial
                lam = max(lam * 0.1, 1e-14)
                improved = delta > tol * max(1.0, current)
                break
            lam *= 10.0
            if lam > 1e14:
                break
        if not improved:
            break

    return [y - a * math.exp(b * x) for x, y in zip(xs, ys)]


# ---------------------------------------------------------------------------
# Rolling window
# ---------------------------------------------------------------------------


def movstd_trailing(xs: Vector, back: int) -> list[float]:
    """MATLAB's ``movstd(x, [back 0])`` -- a trailing window of ``back + 1`` observations.

    The window is asymmetric and backward-looking, so the volatility indicator never sees
    the future. MATLAB shrinks the window at the start of the series rather than emitting
    nan, and the first element -- a window of one -- comes back as zero. Both behaviours
    are reproduced.
    """
    if back < 0:
        raise ValueError("the trailing window cannot be negative")
    out: list[float] = []
    for i in range(len(xs)):
        window = xs[max(0, i - back) : i + 1]
        out.append(0.0 if len(window) < 2 else std(window))
    return out


# ---------------------------------------------------------------------------
# Shape-preserving interpolation
# ---------------------------------------------------------------------------


def _pchip_endpoint_slope(h1: float, h2: float, d1: float, d2: float) -> float:
    """MATLAB's one-sided three-point endpoint rule, including both of its clips."""
    d = ((2.0 * h1 + h2) * d1 - h1 * d2) / (h1 + h2)
    if d * d1 <= 0.0:
        return 0.0
    if d1 * d2 < 0.0 and abs(d) > abs(3.0 * d1):
        return 3.0 * d1
    return d


def pchip_slopes(xs: Vector, ys: Vector) -> list[float]:
    """Fritsch-Carlson derivatives, matching MATLAB ``pchip``.

    At an interior knot where the two neighbouring secants disagree in sign -- or either
    is flat -- the derivative is set to zero. That is the whole point of the method and
    the reason manual section 11.2 specifies it over a cubic spline: a spline through
    sparse knots overshoots and can invent a return reversal between two states that
    never reverses in the data.
    """
    n = len(xs)
    if n != len(ys):
        raise ValueError("pchip needs matching abscissa and ordinate counts")
    if n < 2:
        raise ValueError("pchip needs at least two knots")
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("pchip knots must be strictly increasing")

    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]

    if n == 2:
        return [delta[0], delta[0]]

    d = [0.0] * n
    for k in range(1, n - 1):
        dk_1, dk = delta[k - 1], delta[k]
        if dk_1 * dk > 0.0:
            w1 = 2.0 * h[k] + h[k - 1]
            w2 = h[k] + 2.0 * h[k - 1]
            d[k] = (w1 + w2) / (w1 / dk_1 + w2 / dk)
        else:
            d[k] = 0.0

    d[0] = _pchip_endpoint_slope(h[0], h[1], delta[0], delta[1])
    d[n - 1] = _pchip_endpoint_slope(h[n - 2], h[n - 3], delta[n - 2], delta[n - 3])
    return d


def pchip_eval(xs: Vector, ys: Vector, queries: Vector) -> list[float]:
    """Evaluate the pchip through ``(xs, ys)`` at ``queries``.

    **Queries outside ``[xs[0], xs[-1]]`` are extrapolated** by continuing the cubic of
    the nearest interval, which is what MATLAB's ``ppval`` does and what the reference
    implementation relies on: it evaluates on ``0.6:0.2:5.4`` over knots at ``1..5``, so
    the four outermost states of the 25-state axis are extrapolated, not interpolated.

    That is a deliberate divergence from manual section 11.7 test 6, which asks for
    extrapolation to be impossible by construction. The decision taken here is to
    reproduce the published figures and mark those four states with the method label
    ``extrapolated``, so that nothing is filled silently. See ``calibrate.STATE_METHODS``.
    """
    d = pchip_slopes(xs, ys)
    n = len(xs)
    out: list[float] = []
    for q in queries:
        k = 0
        if q >= xs[n - 1]:
            k = n - 2
        elif q > xs[0]:
            lo, hi = 0, n - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if xs[mid] <= q:
                    lo = mid
                else:
                    hi = mid
            k = lo
        h = xs[k + 1] - xs[k]
        t = q - xs[k]
        secant = (ys[k + 1] - ys[k]) / h
        c3 = (d[k] + d[k + 1] - 2.0 * secant) / (h * h)
        c2 = (secant - d[k]) / h - c3 * h
        out.append(ys[k] + t * (d[k] + t * (c2 + t * c3)))
    return out


# ---------------------------------------------------------------------------
# Empirical distribution
# ---------------------------------------------------------------------------


def centile_of(sample: Vector, value: float) -> float:
    """The centile ``value`` occupies within ``sample``, counting ties at half weight.

    This is the bridge device the reference implementation uses to locate the current
    reading on the historical distribution::

        ncentile = 100 * (nless + 0.5 * nequal) / length(ec_cycle)

    It is reproduced exactly because the Market Risk Signal is mapped onto the calibration
    axis by quantile rather than by column index, and this is the quantile definition the
    calibration side was built with.
    """
    n = len(sample)
    if n == 0:
        raise ValueError("centile of an empty sample")
    nless = sum(1 for s in sample if s < value)
    nequal = sum(1 for s in sample if s == value)
    return 100.0 * (nless + 0.5 * nequal) / n


def percentile(sample: Vector, pct: float) -> float:
    """MATLAB ``prctile``: linear interpolation between order statistics placed at
    ``100 * (i - 0.5) / n``, clamped to the extremes outside that range.

    Note this is *not* numpy's default, which places order statistics at
    ``100 * i / (n - 1)``. The two disagree in the tails, which is exactly where the
    quantile bridge does its most consequential work.
    """
    if not 0.0 <= pct <= 100.0:
        raise ValueError("percentile must be in [0, 100]")
    ordered = sorted(sample)
    n = len(ordered)
    if n == 0:
        raise ValueError("percentile of an empty sample")
    if n == 1:
        return ordered[0]
    positions = [100.0 * (i + 0.5) / n for i in range(n)]
    if pct <= positions[0]:
        return ordered[0]
    if pct >= positions[-1]:
        return ordered[-1]
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if positions[mid] <= pct:
            lo = mid
        else:
            hi = mid
    span = positions[hi] - positions[lo]
    w = 0.0 if span == 0 else (pct - positions[lo]) / span
    return ordered[lo] + w * (ordered[hi] - ordered[lo])
