"""Period returns from a harmonised level series."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

ReturnMethod = Literal["simple", "log"]


def period_returns(levels: pd.Series, method: ReturnMethod = "simple") -> pd.Series:
    """Compute period returns from a level series.

    - ``simple``: ``P_t / P_{t-1} - 1``.
    - ``log``:    ``ln(P_t / P_{t-1})``.

    Drops the first observation. Any zero or negative level raises rather
    than silently emitting inf/NaN, per the spec's no-silent-fill rule.
    """
    if (levels <= 0).any():
        n_bad = int((levels <= 0).sum())
        raise ValueError(f"period_returns: {n_bad} non-positive level(s); refusing to emit returns")
    if method == "simple":
        out = levels.pct_change().dropna()
    elif method == "log":
        out = np.log(levels / levels.shift(1)).dropna()
    else:
        raise ValueError(f"period_returns: unknown method {method!r}")
    out.name = levels.name
    out.attrs = {**levels.attrs, "return_method": method}
    return out
