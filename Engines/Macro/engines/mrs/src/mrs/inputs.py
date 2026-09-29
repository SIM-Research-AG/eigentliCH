"""The input panel as matrices, months by countries. Pure: no I/O.

Two views of one datafeed panel:

* :func:`matrix`: the production view. A gap is ``NaN``; nothing is invented.
* :func:`matlab_view`: what ``Market_Signal.m`` saw in ``M_TS``, for the ``matlab`` mode and
  the golden test. MATLAB's loader stored every gap as 0 (``D(isnan(D)) = 0``), and the
  sheets' placeholder ticker ``USD BGN Curncy`` was pulled as a constant 1.0. datafeed keeps
  both as gaps and records the placeholders in its import conversions, so the view is rebuilt
  here, exactly, from the raw snapshot: 0 for a gap, 1.0 for every month of a placeholder.
  It is only meaningful on a raw snapshot, whose cells are all Bloomberg's.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

from .contracts import ImportConversion, Panel

#: What MATLAB read for a placeholder ticker (USD spot against USD).
PLACEHOLDER_VALUE = 1.0


def matrix(panel: Panel, series_id: str, countries: Sequence[str]) -> np.ndarray:
    """One series, months by ``countries``; ``NaN`` where the cell (or the series) is missing."""
    out = np.full((len(panel.dates), len(countries)), np.nan)
    column = {c: j for j, c in enumerate(countries)}
    for s in panel.series:
        if s.series_id == series_id and s.country in column:
            out[:, column[s.country]] = [np.nan if v is None else v for v in s.values]
    return out


def placeholders(conversions: Iterable[ImportConversion]) -> set[tuple[str, str]]:
    """(country, series_id) pairs whose ticker was a placeholder."""
    return {(c.country, c.series_id) for c in conversions if c.placeholder}


def matlab_view(panel: Panel, series_id: str, countries: Sequence[str],
                conversions: Iterable[ImportConversion]) -> np.ndarray:
    """One series as MATLAB held it in ``M_TS``: gaps as 0, placeholders as 1.0."""
    out = np.nan_to_num(matrix(panel, series_id, countries), nan=0.0)
    blank = placeholders(conversions)
    for j, country in enumerate(countries):
        if (country, series_id) in blank:
            out[:, j] = PLACEHOLDER_VALUE
    return out
