"""Harmonisation: magnitude scaling, currency handling, periodicity resample.

Each transform is a labelled, invertible level operation. The invariance test
in spec 8.2 requires that magnitude and constant-FX conversion leave period
returns unchanged; multiplicative constants cancel in ``P_t / P_{t-1}``.
"""

from __future__ import annotations

import pandas as pd

from fmre.registers.data_series import Currency, Magnitude, Period, Unit

# Scale to LEVEL. Magnitude label X means "series is expressed in units of X",
# so multiplying by these factors converts the series to unit "1".
MAGNITUDE_SCALE: dict[Magnitude, float] = {
    Magnitude.TN: 1e12,
    Magnitude.BN: 1e9,
    Magnitude.HUNDRED_MN: 1e8,
    Magnitude.MN: 1e6,
    Magnitude.TH: 1e3,
    Magnitude.CRORE: 1e7,     # 1 crore = 10 million (Indian numbering)
    Magnitude.LEVEL: 1.0,
    Magnitude.PCT: 1.0,       # already a level (percent value in the series)
    Magnitude.BSE: 1.0,       # base index
}


def apply_magnitude(series: pd.Series, magnitude: Magnitude) -> pd.Series:
    """Scale a series to LEVEL units. Returns a new series with the same index."""
    scale = MAGNITUDE_SCALE[magnitude]
    out = series * scale
    out.name = series.name
    out.attrs = {**series.attrs, "magnitude_scale": scale, "magnitude_label": magnitude.value}
    return out


def apply_fx(
    series: pd.Series,
    from_currency: str,
    to_currency: str,
    fx_series: pd.Series | float | None = None,
) -> pd.Series:
    """Convert a level series between currencies.

    - If ``from_currency == to_currency`` (or either is 'LCY' with fx_series
      None), the series is passthrough with the FX handling recorded as such.
    - If a scalar ``fx_series`` is given, applies as a constant multiplier
      (this is the invariance test path: constant FX leaves returns unchanged).
    - If a pandas Series is given, aligns on index and multiplies pointwise.
      Missing FX observations are forward-filled with a labelled note.
    """
    attrs = {**series.attrs, "fx_from": from_currency, "fx_to": to_currency}
    if from_currency == to_currency or fx_series is None:
        out = series.copy()
        out.attrs = {**attrs, "fx_handling": "passthrough"}
        return out
    if isinstance(fx_series, (int, float)):
        out = series * float(fx_series)
        out.name = series.name
        out.attrs = {**attrs, "fx_handling": "constant", "fx_value": float(fx_series)}
        return out
    aligned = fx_series.reindex(series.index).ffill()
    out = series * aligned
    out.name = series.name
    out.attrs = {**attrs, "fx_handling": "series_ffill"}
    return out


def resample_to_monthly(series: pd.Series, native_period: Period) -> pd.Series:
    """Resample to month-end. Only supports native <= monthly (daily, monthly).

    Quarterly and annual series are returned at native frequency with a
    labelled attr; the estimation path handles low-frequency blocks
    separately (spec 4.2 and D6). Never silently interpolate to monthly.
    """
    if native_period == Period.MONTHLY:
        out = series.resample("ME").last()
        out.attrs = {**series.attrs, "resample": "month_end_last", "native_period": native_period.value}
        return out
    if native_period == Period.QUARTERLY or native_period == Period.ANNUAL:
        out = series.copy()
        out.attrs = {
            **series.attrs,
            "resample": "native_low_freq_hold",
            "native_period": native_period.value,
        }
        return out
    raise ValueError(f"resample_to_monthly: unknown native_period {native_period!r}")
