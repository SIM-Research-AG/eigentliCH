"""A literal transcription of ``Weights.m`` and the regime part of ``Market_Signal.m``.

Deliberately naive and deliberately independent of ``mrs.engine``: it builds the matrices
the way MATLAB does (33-row padding, fold, delete), takes ``binopdf`` from scipy, and runs
the column-selection loop line for line, NaN semantics and all. The engine is tested
against this, so a shared mistake would have to be made twice in two different ways.

Indices are 0-based here; comments give the MATLAB line they transcribe.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import binom

SCALES = {"defensive": 0.0, "default": 0.4, "aggressive": 0.8, "rogue": 1.2}


def _band(w: np.ndarray) -> np.ndarray:
    wm = np.zeros((33, 11))                    # WM_Macro=zeros(33,11);
    i = 25                                     # i=25;
    for j in range(1, 12):                     # for j=1:11
        wm[i - 3 - 1:i + 5, j - 1] = w         #     WM_Macro(i-3:i+5,j)=W_Macro';
        i -= 2                                 #     i=i-2;
    wm[4, :] = wm[0:4, :].sum(axis=0) + wm[4, :]      # WM_Macro(5,:)=sum(WM_Macro(1:4,:))+WM_Macro(5,:);
    wm[28, :] = wm[29:, :].sum(axis=0) + wm[28, :]    # WM_Macro(29,:)=sum(WM_Macro(30:end,:))+WM_Macro(29,:);
    return np.delete(wm, list(range(0, 4)) + list(range(29, 33)), axis=0)  # WM_Macro([1:4 30:end],:)=[];


def weights_m(opti_scale: str, indi_weights=(0.25, 0.25, 0.25, 0.25)):
    """``[WM_Macro, WM_Fundamental, WM_Technical, WM_Market_Stress, Scale_...] = Weights(...)``."""
    scale = SCALES[opti_scale]
    grid = np.linspace(-2, 2, 11)
    scales = (scale + grid, -scale + grid, -scale + grid, scale + grid)

    w_band = binom.pmf(np.arange(9), 8, 0.5)  # binopdf(0:8,8,0.5)
    w_stress = binom.pmf(np.arange(9), 8, 0.1)  # binopdf(0:8,8,0.1)

    macro, fundamental, technical = _band(w_band), _band(w_band), _band(w_band)

    stress = np.zeros((25, 11))                # WM_Market_Stress=zeros(25,11);
    i = 8                                      # i=8;
    for j in range(1, 12):
        if j > 5:
            stress[i - 7 - 1:i + 1, j - 1] = (j - 5) ** math.sqrt(2) * w_stress
    stress = stress / 11

    return (macro * indi_weights[0], fundamental * indi_weights[1],
            technical * indi_weights[2], stress * indi_weights[3], scales)


def pick(value: float, scale: np.ndarray) -> Optional[int]:
    """The ``for c=1:size(Scale,2)-1`` loop: the column (1-based) the last assignment makes,
    or ``None`` where no branch assigns (MATLAB would keep whatever was there)."""
    picked = None
    for c in range(1, len(scale)):             # c = 1 .. 10
        if value < scale[c]:                   # if TS(t) < Scale(c+1)
            if value > scale[c - 1]:           #     if TS(t) > Scale(c)
                picked = c                     #         WM(:,c)
            elif value < scale[0]:             #     elseif TS(t) < Scale(1)
                picked = 1                     #         WM(:,1)
        elif value > scale[-1]:                # elseif TS(t) > Scale(end)
            picked = len(scale)                #     WM(:,end)
        else:
            picked = 1                         # else WM(:,1)
    return picked


def crs_row(readings: dict[str, float], opti_scale: str) -> tuple[np.ndarray, dict[str, int]]:
    """One ``CRS_Signal_XX(t,:)`` row, and the columns picked, for one economy and date.

    ``readings`` maps business_cycle, investment, market_behaviour, market_stress to a
    float (``nan`` for missing).
    """
    wm_biz, wm_inv, wm_beh, wm_str, (s_biz, s_inv, s_beh, s_str) = weights_m(opti_scale)
    parts = (("business_cycle", wm_biz, s_biz), ("investment", wm_inv, s_inv),
             ("market_behaviour", wm_beh, s_beh), ("market_stress", wm_str, s_str))
    row = np.zeros(25)
    cols = {}
    for name, wm, scale in parts:
        col = pick(readings[name], scale)
        if col is None:
            raise ValueError(f"MATLAB assigns nothing for {name}={readings[name]!r}")
        cols[name] = col
        row = row + wm[:, col - 1]
    return row, cols
