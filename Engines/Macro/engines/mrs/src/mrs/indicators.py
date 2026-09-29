"""The indicator layer of ``Market_Signal.m``. Pure: arrays in, arrays out; no I/O.

The eleven sub-indicators (``MR_*.m``, with the technical helpers ``ema``, ``kst``,
``macd2``, ``momentum``, ``roc`` and ``sar`` from ``Functions/Market Risk/Models``) and the
four segment signals they combine into, for one economy at a time. ``MR_Key_Stats.m`` does
not enter the distribution and is not ported (MRS-09).

Two modes, chosen by the calibration (``IndicatorParams.mode``):

``matlab``
    Reproduces MATLAB on MATLAB's own view of ``M_TS`` (``inputs.matlab_view``: gaps 0,
    placeholder tickers 1.0): full-sample ``normalize`` and ``detrend``, ``NaN`` set to 0
    where the MATLAB sets it, NaN-ignoring ``min``/``max``, the MATLAB inputs and units.
    Arrays may carry ``NaN`` exactly where MATLAB's did.

``production``
    On the production view (``inputs.matrix``: a gap is ``NaN``, nothing is invented), with
    the owner's rulings of 27.09.2026 (Notion task "mrs: methodology rulings"):

    * z-scores and ``detrend`` use data up to each month only (expanding window); a month
      needs ``min_history_input`` observations for a transform of an input and
      ``min_history_composite`` for a transform of a combination, else it is missing;
    * inside an indicator (and a segment) a missing part reads as 0, the average, as in
      MATLAB; the indicator (segment) is missing only where every part is (MRS-17);
    * ``gradient`` keeps central differences; the gold-window quirk and the ``T./T + T``
      quirk are kept;
    * the replacement inputs (MRS-15) and thresholds in data units (MRS-16).

A missing value is ``NaN`` in and out; the service turns it into ``None`` on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

import numpy as np

from .contracts import INDICATORS, SEGMENT_INDICATORS, IndicatorParams

#: Segments that MATLAB z-scores (``normalize(holdmean)``); stress is a plain weighted sum.
NORMALISED_SEGMENTS = ("business_cycle", "investment", "market_behaviour")


class IndicatorError(ValueError):
    """An input the indicator layer needs is absent. The message names it."""


@dataclass(frozen=True)
class EconomyIndicators:
    indicators: dict[str, np.ndarray]
    segments: dict[str, np.ndarray]
    #: Input series with no observation at all for this economy.
    inputs_missing: tuple[str, ...]


def series_needed(p: IndicatorParams) -> tuple[str, ...]:
    """Every series id the indicators read under ``p``."""
    return tuple(sorted({sid for sids in _inputs(p).values() for sid in sids}))


def _inputs(p: IndicatorParams) -> dict[str, tuple[str, ...]]:
    return {
        "inflation": (p.inflation_fx_series, "inflation.ppi_yoy", "inflation.cpi_yoy"),
        "monetary": ("yields.govt_10y", "yields.govt_2y", "money.m1_yoy",
                     "equity.capital_stock_decrease"),
        "consumer": ("consumer.wage_growth", "consumer.household_consumption",
                     "consumer.unemployment"),
        "company": ("equity.profit_margin", "production.manufacturing_confidence",
                    "equity.debt_to_assets"),
        "bond": (p.bond_hy_series, "yields.govt_10y", "inflation.cpi_yoy", "debt.npl_ratio"),
        "equity": ("equity.pe_long_term", "equity.price_to_sales", "equity.dividend_yield"),
        "trend_osc": ("equity.total_return",),
        "fear_greed": (p.fear_greed_series,),
        "global_stability": ("fx.dxy", "fx.ois_1y", "commodity.gold"),
        "market_stability": ("equity.total_return", "equity.banks_total_return",
                             "volatility.implied", "debt.senior_loan_etf"),
        "monetary_uncertainty": ("money.broad_money", "production.gdp_nominal"),
    }


# ---------------------------------------------------------------------------
# MATLAB primitives (full sample)
# ---------------------------------------------------------------------------

def _quiet(fn: Callable[..., np.ndarray]) -> Callable[..., np.ndarray]:
    def wrapped(*args, **kwargs):
        with np.errstate(all="ignore"):
            return fn(*args, **kwargs)
    return wrapped


@_quiet
def m_normalize(x: np.ndarray) -> np.ndarray:
    """MATLAB ``normalize(x)``: z-score with the sample standard deviation, statistics
    taken over the non-NaN values ('omitnan'); a NaN stays NaN."""
    finite = x[~np.isnan(x)]
    if finite.size == 0:
        return np.full(x.size, np.nan)
    return (x - np.mean(finite)) / (np.std(finite, ddof=1) if finite.size > 1 else np.nan)


@_quiet
def m_detrend(x: np.ndarray) -> np.ndarray:
    """MATLAB ``detrend(x)``: residual from the least-squares line on 1..n."""
    n = x.size
    if n == 0:
        return x.copy()
    if not np.all(np.isfinite(x)):
        return np.full(n, np.nan)
    s = np.arange(1.0, n + 1.0)
    design = np.column_stack([s / n, np.ones(n)])
    coef, *_ = np.linalg.lstsq(design, x, rcond=None)
    return x - design @ coef


def m_clean(x: np.ndarray, inf: bool = True) -> np.ndarray:
    """``x(isnan(x)) = 0`` and, with ``inf``, ``x(isinf(x)) = 0``."""
    out = x.copy()
    out[np.isnan(out)] = 0.0
    if inf:
        out[np.isinf(out)] = 0.0
    return out


@_quiet
def m_movmean(x: np.ndarray, back: int) -> np.ndarray:
    """``movmean(x, [back 0])``: trailing mean, shrinking at the start. NaN propagates."""
    return np.array([np.mean(x[max(0, t - back):t + 1]) for t in range(x.size)])


def m_max(a: float, x: np.ndarray) -> np.ndarray:
    """MATLAB ``max(a, x)``: NaN is ignored, so ``max(a, NaN) = a``."""
    return np.where(np.isnan(x), a, np.maximum(a, x))


def m_min(a: float, x: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(x), a, np.minimum(a, x))


def m_std(x: np.ndarray) -> float:
    with np.errstate(all="ignore"):
        return float(np.std(x, ddof=1)) if x.size > 1 else 0.0


# ---------------------------------------------------------------------------
# Production primitives (data up to each month only)
# ---------------------------------------------------------------------------

@_quiet
def x_zscore(x: np.ndarray, min_obs: int, demean: bool = True) -> np.ndarray:
    """Expanding z-score: month t against the observations up to and including t.

    Missing where x is missing, where fewer than ``min_obs`` observations exist up to t,
    or where their standard deviation is 0. With ``demean=False`` only divides by the
    expanding standard deviation (``x ./ std(x)`` in MATLAB).
    """
    out = np.full(x.size, np.nan)
    for t in range(x.size):
        if not np.isfinite(x[t]):
            continue
        past = x[:t + 1]
        past = past[np.isfinite(past)]
        if past.size < max(min_obs, 2):
            continue
        sd = np.std(past, ddof=1)
        if not sd > 0.0:
            continue
        out[t] = ((x[t] - np.mean(past)) if demean else x[t]) / sd
    return out


def x_detrend(x: np.ndarray, min_obs: int) -> np.ndarray:
    """Residual at t from the least-squares line fitted on the observations up to t."""
    out = np.full(x.size, np.nan)
    s_all = np.arange(1.0, x.size + 1.0)
    for t in range(x.size):
        if not np.isfinite(x[t]):
            continue
        keep = np.isfinite(x[:t + 1])
        if keep.sum() < max(min_obs, 2):
            continue
        s, y = s_all[:t + 1][keep], x[:t + 1][keep]
        sc = s - s.mean()
        denom = float(np.dot(sc, sc))
        slope = float(np.dot(sc, y - y.mean())) / denom if denom > 0 else 0.0
        out[t] = x[t] - (y.mean() + slope * (s_all[t] - s.mean()))
    return out


def x_movmean(x: np.ndarray, back: int) -> np.ndarray:
    """Trailing mean over the observed values of ``[t-back, t]``; missing where x[t] is."""
    out = np.full(x.size, np.nan)
    for t in range(x.size):
        if not np.isfinite(x[t]):
            continue
        w = x[max(0, t - back):t + 1]
        out[t] = float(np.mean(w[np.isfinite(w)]))
    return out


def combine(parts: list[np.ndarray], weights: list[float]) -> np.ndarray:
    """Weighted sum where a missing part reads as 0 (the average); missing where all are."""
    stack = np.vstack(parts)
    present = np.isfinite(stack)
    total = np.sum(np.where(present, stack, 0.0) * np.asarray(weights)[:, None], axis=0)
    return np.where(present.any(axis=0), total, np.nan)


# ---------------------------------------------------------------------------
# Technical helpers (Models/ema.m, roc.m, momentum.m, macd2.m, kst.m, sar.m)
# ---------------------------------------------------------------------------

def ema(price: np.ndarray, days: int) -> np.ndarray:
    """``ema.m``, seeded at the first observed value (MATLAB: at ``Price(1)``)."""
    out = np.full(price.size, np.nan)
    finite = np.flatnonzero(np.isfinite(price))
    if finite.size == 0:
        return out
    first = int(finite[0])
    lam = 2.0 / (days + 1.0)
    out[first] = price[first]
    for t in range(first, price.size - 1):
        out[t + 1] = out[t] + lam * (price[t + 1] - out[t])
    return out


@_quiet
def roc(price: np.ndarray, days: int, lead: float) -> np.ndarray:
    """``roc.m``: ``100*(P(t) - P(t-days+1)) / P(t-days+1)``; ``lead`` for the first days-1."""
    out = np.full(price.size, lead)
    out[days - 1:] = 100.0 * (price[days - 1:] - price[:price.size - days + 1]) / price[:price.size - days + 1]
    return out


@_quiet
def momentum(price: np.ndarray, days: int, lead: float) -> np.ndarray:
    """``momentum.m``: ``100*P(t) / P(t-days+1)``; ``lead`` for the first days-1."""
    out = np.full(price.size, lead)
    out[days - 1:] = 100.0 * price[days - 1:] / price[:price.size - days + 1]
    return out


def macd2(price: np.ndarray, t1: int, t2: int, t3: int) -> np.ndarray:
    ma = ema(price, t1) - ema(price, t2)
    return ema(ma, t3) - ma


def kst(price: np.ndarray, option: int, lead: float) -> np.ndarray:
    if option == 1:
        spec = ((10, 10, 1), (15, 10, 2), (20, 10, 3), (30, 15, 4))
    elif option == 2:
        spec = ((10, 10, 1), (13, 13, 2), (15, 15, 3), (20, 20, 4))
    else:
        spec = ((9, 6, 1), (12, 6, 2), (18, 6, 3), (24, 9, 4))
    return sum(ema(roc(price, r, lead), e) * w for r, e, w in spec)


def sar(price: np.ndarray, days: int) -> np.ndarray:
    """``sar.m`` literally, including ``a`` starting at 1 and the exact-equality test."""
    d = price.size
    out = np.zeros(d)
    a = 1.0
    for t in range(days, d - 1):          # MATLAB t = days+1 .. d-1 (1-based)
        e = float(np.max(price[t - days:t + 1]))
        if e == price[t]:
            a = 0.02
        elif a < 0.2:
            a = a + 0.02
        out[t + 1] = out[t] + a * (e - out[t])
    return out


# ---------------------------------------------------------------------------
# The indicators
# ---------------------------------------------------------------------------

class _Ops:
    """The transforms one mode uses, so each ``MR_*.m`` is written once."""

    def __init__(self, p: IndicatorParams):
        self.p = p
        self.matlab = p.mode == "matlab"

    def z(self, x: np.ndarray) -> np.ndarray:
        """``normalize`` of an input, then ``A(isnan)=0; A(isinf)=0`` in MATLAB."""
        if self.matlab:
            return m_clean(m_normalize(x))
        return x_zscore(x, self.p.min_history_input)

    def zc(self, x: np.ndarray, clean: bool = True) -> np.ndarray:
        """``normalize`` of a combination (``Output = normalize(ndx)``)."""
        if self.matlab:
            out = m_normalize(x)
            return m_clean(out, inf=False) if clean else out
        return x_zscore(x, self.p.min_history_composite)

    def lcl(self, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
        """``ndx = w(1)*A + w(2)*B + w(3)*C`` with the leading/concurrent/lagging weights."""
        w = list(self.p.lcl_weights)
        if self.matlab:
            return w[0] * a + w[1] * b + w[2] * c
        return combine([a, b, c], w)


def inflation(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    a = o.z(s[o.p.inflation_fx_series])
    b = o.z(s["inflation.ppi_yoy"])
    c = o.z(s["inflation.cpi_yoy"])
    return o.zc(o.lcl(a, b, c))


def monetary(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    # -normalize(x) == normalize(-x) bit for bit (mean and std are sign-symmetric).
    a = o.z(-(s["yields.govt_10y"] - s["yields.govt_2y"]))
    b = o.z(-s["money.m1_yoy"])
    c = o.z(-s["equity.capital_stock_decrease"])
    return o.zc(o.lcl(a, b, c))


def consumer(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    a = o.z(s["consumer.wage_growth"])
    b = o.z(s["consumer.household_consumption"])
    c = o.z(-s["consumer.unemployment"])
    return o.zc(o.lcl(a, b, c))


def company(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    a = o.z(s["equity.profit_margin"])
    b = o.z(s["production.manufacturing_confidence"])
    c = o.z(s["equity.debt_to_assets"])
    return o.zc(o.lcl(a, b, c))


def bond(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    ten = s["yields.govt_10y"]
    if o.matlab:
        a = m_clean(-m_normalize(s[o.p.bond_hy_series] - ten))
        b = m_clean(-m_normalize(ten - s["inflation.cpi_yoy"]))
        c = m_clean(-m_normalize(s["debt.npl_ratio"]))
    else:
        a = -o.z(s[o.p.bond_hy_series] - ten)
        b = -o.z(ten - s["inflation.cpi_yoy"])
        c = -o.z(s["debt.npl_ratio"])
    return o.zc(o.lcl(a, b, c))


def equity(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    if o.matlab:   # MR_Equity.m cleans NaN only, not inf
        a = m_clean(-m_normalize(s["equity.pe_long_term"]), inf=False)
        b = m_clean(m_normalize(s["equity.price_to_sales"]), inf=False)
        c = m_clean(-m_normalize(s["equity.dividend_yield"]), inf=False)
        return m_clean(m_normalize(-(o.lcl(a, b, c))), inf=False)
    a = -o.z(s["equity.pe_long_term"])
    b = o.z(s["equity.price_to_sales"])
    c = -o.z(s["equity.dividend_yield"])
    return o.zc(-o.lcl(a, b, c))


def trend_osc(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    raw = s["equity.total_return"]
    if o.matlab:
        return _trend_osc_matlab(raw, o.p)
    return _trend_osc_production(raw, o.p)


@_quiet
def _trend_osc_matlab(raw: np.ndarray, p: IndicatorParams) -> np.ndarray:
    k = p.trend_osc
    t = raw / raw + raw                    # T = T./T + T  (kept: MRS rulings)
    t[np.isnan(t)] = 1.0
    t = 100.0 * t / t[0]
    t[np.isnan(t)] = 0.0
    ti = (ema(t, k.ema[0]) - t) + (ema(t, k.ema[1]) - t) + (ema(t, k.ema[2]) - t) + (sar(t, k.sar) - t)
    osc = [-macd2(t, *k.macd), momentum(t, k.momentum, 0.0), roc(t, k.roc, 0.0),
           kst(t, k.kst_option, 0.0)]
    osc = [x / m_std(x) for x in osc]
    osc = [x - np.mean(x) for x in osc]
    ti = ti / m_std(ti)
    oo = sum(osc)
    oo = oo / m_std(oo)
    to = m_min(k.clip, m_max(-k.clip, oo - ti))
    return -m_normalize(to)


@_quiet
def _trend_osc_production(raw: np.ndarray, p: IndicatorParams) -> np.ndarray:
    """The same chain on each contiguous run of observations; no value is invented.

    The minimum histories apply at the indicator's boundaries (MRS-17): the index needs
    ``min_history_input`` months of observations, and the result ``min_history_composite``
    values of ``TO``. The internal scalings (``x./std(x)``, ``- mean``) use every value up to
    the month, from two on; chaining a full minimum through each of the four internal
    stages would hold the indicator back by some six years.
    """
    out = np.full(raw.size, np.nan)
    finite = np.isfinite(raw)
    if not finite.any():
        return out
    k = p.trend_osc
    ti = np.full(raw.size, np.nan)
    osc = [np.full(raw.size, np.nan) for _ in range(4)]
    for lo, hi in _runs(finite):
        seg = raw[lo:hi]
        t = seg / seg + seg                # the T./T + T quirk, kept (ruling)
        t = 100.0 * t / t[0]
        ti_run = (ema(t, k.ema[0]) - t) + (ema(t, k.ema[1]) - t) + (ema(t, k.ema[2]) - t) + (sar(t, k.sar) - t)
        ti_run[:min(k.sar + 1, ti_run.size)] = np.nan      # sar's zero seed is warm-up
        o_run = [-macd2(t, *k.macd), momentum(t, k.momentum, np.nan), roc(t, k.roc, np.nan),
                 kst(t, k.kst_option, np.nan)]
        ti[lo:hi] = ti_run
        for i, x in enumerate(o_run):
            osc[i][lo:hi] = x
    osc = [x_zscore(x, 2) for x in osc]                        # x./std(x) - mean(x./std(x))
    ti = x_zscore(ti, 2, demean=False)                         # TI./std(TI)
    oo = x_zscore(np.sum(np.vstack(osc), axis=0), 2, demean=False)
    to = np.clip(oo - ti, -k.clip, k.clip)
    out = -x_zscore(to, p.min_history_composite)
    history = np.cumsum(finite)
    out[history < p.min_history_input] = np.nan
    return out


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, mask.size))
    return out


def fear_greed(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    x = s[o.p.fear_greed_series]
    if o.matlab:
        return m_clean(-m_normalize(m_detrend(x)), inf=False)
    # detrend is the input transform (24); the z-score of its residual a combination (12).
    return -x_zscore(x_detrend(x, o.p.min_history_input), o.p.min_history_composite)


@_quiet
def global_stability(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    th = o.p.thresholds
    dxy, ois, gold = s["fx.dxy"], s["fx.ois_1y"], s["commodity.gold"]
    if o.matlab:
        a = (np.abs(np.concatenate([[0.0], np.diff(dxy)])) > th.dxy_move).astype(float)
        b = (ois > th.ois_level).astype(float)
        g = m_clean(np.concatenate([[0.0], np.diff(gold)]))
        w = th.gold_window
        for i in range(w - 1, g.size):     # MATLAB i = 20:n, overwriting in place (kept)
            g[i] = 1.0 if m_std(g[i - w + 1:i + 1]) > th.gold_std else 0.0
        g[:w - 1] = 0.0
        return th.flag_scale * o.lcl(a, b, g)
    a = _flag(np.abs(_diff(dxy)) > th.dxy_move, _diff(dxy))
    b = _flag(ois > th.ois_level, ois)
    g = _diff(gold)
    w = th.gold_window
    for i in range(g.size):                # the in-place window, kept (ruling)
        if i < w - 1 or not np.isfinite(g[i]):
            g[i] = np.nan                  # warm-up or no price change: missing
            continue
        win = g[i - w + 1:i + 1]
        win = win[np.isfinite(win)]
        g[i] = 1.0 if (win.size > 1 and m_std(win) > th.gold_std) else 0.0
    return th.flag_scale * o.lcl(a, b, g)


def _diff(x: np.ndarray) -> np.ndarray:
    return np.concatenate([[np.nan], np.diff(x)])


def _flag(test: np.ndarray, source: np.ndarray) -> np.ndarray:
    """1.0 / 0.0 where ``source`` is observed, missing where it is not."""
    return np.where(np.isfinite(source), test.astype(float), np.nan)


@_quiet
def market_stability(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    th = o.p.thresholds
    index, banks = s["equity.total_return"], s["equity.banks_total_return"]
    vix, loan = s["volatility.implied"], s["debt.senior_loan_etf"]
    back = th.bank_window - 1
    if o.matlab:
        # log of a negative level is complex in MATLAB, and < compares real parts: log|x|.
        di = np.concatenate([[0.0], np.diff(np.log(np.abs(index)))])
        db = np.concatenate([[0.0], np.diff(np.log(np.abs(banks)))])
        di[np.isinf(di)] = 0.0
        db[np.isinf(db)] = 0.0
        bvi = db - di
        bvi[np.isnan(bvi)] = 0.0
        a = (m_movmean(bvi, back) < th.bank_vs_index).astype(float)
        vdot = np.concatenate([[0.0], np.diff(np.gradient(vix))]) if vix.size > 1 else np.zeros(vix.size)
        b = ((vix > th.vix_level) & (vdot > th.vix_accel)).astype(float)
        ly = m_clean(np.gradient(loan) if loan.size > 1 else np.zeros(loan.size))
        if th.loan_change == "relative":
            ly = m_clean(ly / loan)
        c = (np.abs(m_movmean(ly, th.loan_window - 1)) > th.loan_move).astype(float)
        return th.flag_scale * o.lcl(a, b, c)
    bvi = _diff(np.log(banks)) - _diff(np.log(index))
    bvi[np.isinf(bvi)] = np.nan
    a = _flag(x_movmean(bvi, back) < th.bank_vs_index, x_movmean(bvi, back))
    vdot = _diff(_gradient(vix))
    b = _flag((vix > th.vix_level) & (vdot > th.vix_accel), vix + vdot)
    ly = _gradient(loan)
    if th.loan_change == "relative":
        ly = ly / loan
    ly[~np.isfinite(ly)] = np.nan
    lm = x_movmean(ly, th.loan_window - 1)
    c = _flag(np.abs(lm) > th.loan_move, lm)
    return th.flag_scale * o.lcl(a, b, c)


def _gradient(x: np.ndarray) -> np.ndarray:
    """MATLAB ``gradient`` (central differences, one-sided at the ends), NaN-propagating.

    Kept central, one month of look-ahead included, on the owner's ruling of 27.09.2026.
    """
    if x.size < 2:
        return np.full(x.size, np.nan)
    with np.errstate(all="ignore"):
        return np.gradient(x)


@_quiet
def monetary_uncertainty(s: Mapping[str, np.ndarray], o: _Ops) -> np.ndarray:
    k = o.p.monetary_uncertainty
    ratio = s["money.broad_money"] / s["production.gdp_nominal"]
    if o.matlab:
        ratio[np.isinf(ratio)] = 0.0
        body = m_detrend(ratio[k.skip:])
        body = m_movmean(body, k.window - 1)
        r = np.concatenate([np.zeros(k.skip), body])
        r = m_min(k.clip, m_max(-k.clip, r / m_std(r)))
        return k.scale * np.abs(r)
    ratio[~np.isfinite(ratio)] = np.nan
    ratio[:k.skip] = np.nan
    body = x_movmean(x_detrend(ratio, o.p.min_history_input), k.window - 1)
    r = x_zscore(body, o.p.min_history_composite, demean=False)
    return k.scale * np.abs(np.clip(r, -k.clip, k.clip))


_FUNCTIONS: dict[str, Callable[[Mapping[str, np.ndarray], _Ops], np.ndarray]] = {
    "inflation": inflation, "monetary": monetary, "consumer": consumer, "company": company,
    "bond": bond, "equity": equity, "trend_osc": trend_osc, "fear_greed": fear_greed,
    "global_stability": global_stability, "market_stability": market_stability,
    "monetary_uncertainty": monetary_uncertainty,
}


# ---------------------------------------------------------------------------
# One economy
# ---------------------------------------------------------------------------

def compute(series: Mapping[str, np.ndarray], p: IndicatorParams,
            n: Optional[int] = None) -> EconomyIndicators:
    """The eleven indicators and four segment signals for one economy.

    ``series`` maps series id to a 1-D array over the months (``NaN`` where missing in
    production; MATLAB's zeros and ones in ``matlab`` mode). Every series in
    :func:`series_needed` must be present as a key, even if all ``NaN``.
    """
    needed = series_needed(p)
    absent = [sid for sid in needed if sid not in series]
    if absent:
        raise IndicatorError(f"the indicator layer needs {absent}")
    if n is None:
        n = next(iter(series.values())).size
    data = {sid: np.asarray(series[sid], dtype=float).copy() for sid in needed}
    if any(v.shape != (n,) for v in data.values()):
        raise IndicatorError("every input series must have one value per month")
    ops = _Ops(p)
    ind = {name: np.asarray(_FUNCTIONS[name]({k: v.copy() for k, v in data.items()}, ops), dtype=float)
           for name in INDICATORS}
    segments = {}
    weights = p.segment_weights()
    for seg, names in SEGMENT_INDICATORS.items():
        w = [weights[seg][nm] for nm in names]
        if p.mode == "matlab":
            hold = sum(wi * ind[nm] for wi, nm in zip(w, names))
            segments[seg] = m_normalize(hold) if seg in NORMALISED_SEGMENTS else hold
        else:
            hold = combine([ind[nm] for nm in names], w)
            segments[seg] = (x_zscore(hold, p.min_history_composite)
                             if seg in NORMALISED_SEGMENTS else hold)
    empty = tuple(sid for sid in needed if not np.any(np.isfinite(data[sid])))
    return EconomyIndicators(indicators=ind, segments=segments, inputs_missing=empty)
