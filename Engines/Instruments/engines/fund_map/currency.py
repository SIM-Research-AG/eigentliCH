"""Currency at the point of use: CHF, EUR or USD, chosen by the reader (decision D-01).

Every return series is stored **nominal in the currency it was measured in** -- CHF for the
returns recovered from the andersCH report, USD for the public proxies -- and converted only
when a caller asks for another currency. Nothing converted is ever written back. The same
reasoning keeps real returns out of the store (manual section 11.3): a conversion is a
consumption choice, not a property of the asset.

**A per-state profile cannot be converted after the fact.** A state value is an average
over the months tagged with that state, and the exchange rate moved differently in each
state; adding one currency drift to every state would misstate exactly the thing a profile
exists to show. So the conversion runs on the monthly returns, before any estimator sees
them, and the profile is then measured in the chosen currency:

    r_target(t) = (1 + r_source(t)) * X(t) / X(t-1) - 1

where ``X(t)`` is the price of one unit of the source currency in the target currency at
the end of month ``t``. A month is dropped when either rate is missing, never filled.

Standard library only, like the rest of the client path.
"""

from __future__ import annotations

from typing import Mapping

#: The currencies a reader may choose. D-01 names these three.
CURRENCIES: tuple[str, ...] = ("CHF", "EUR", "USD")

#: The stored FX series, as ``series_id -> (base, quote)``: the level is the price of one
#: unit of ``base`` in ``quote``. Two rates span all three currencies.
FX_SERIES: dict[str, tuple[str, str]] = {
    "fx.USDCHF": ("USD", "CHF"),
    "fx.EURCHF": ("EUR", "CHF"),
}


class CurrencyError(ValueError):
    """Raised when a conversion cannot be made honestly."""


def _previous(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def cross_rates(levels: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Every currency's month-end value **in CHF**, from the stored series.

    ``levels`` maps a series id from :data:`FX_SERIES` to ``{period: level}``. The result
    maps a currency to ``{period: CHF per unit}``; CHF itself is 1 in every month any rate
    covers. Any pair then follows as a ratio of two CHF values.
    """
    in_chf: dict[str, dict[str, float]] = {}
    for series_id, (base, quote) in FX_SERIES.items():
        if quote != "CHF":
            raise CurrencyError(f"{series_id} is not quoted in CHF")
        values = levels.get(series_id) or {}
        in_chf[base] = {p: v for p, v in values.items() if v and v > 0}
    periods = set().union(*(set(v) for v in in_chf.values())) if in_chf else set()
    in_chf["CHF"] = {p: 1.0 for p in periods}
    return in_chf


def rate(in_chf: Mapping[str, Mapping[str, float]], source: str, target: str,
         period: str) -> float | None:
    """Price of one unit of ``source`` in ``target`` at the end of ``period``."""
    if source == target:
        return 1.0
    a = in_chf.get(source, {}).get(period)
    b = in_chf.get(target, {}).get(period)
    if a is None or b is None or b == 0:
        return None
    return a / b


def convert_returns(
    returns: Mapping[str, float],
    source: str,
    target: str | None,
    in_chf: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """Convert simple monthly returns from ``source`` to ``target`` currency.

    ``target`` of ``None`` means "leave it in its source currency", which is the default
    everywhere and what the published profiles are.
    """
    if target is None or target == source:
        return dict(returns)
    if target not in CURRENCIES:
        raise CurrencyError(f"{target!r} is not one of {list(CURRENCIES)}")
    if source not in in_chf or target not in in_chf:
        raise CurrencyError(
            f"no exchange rate to convert {source} into {target}. The FX series are loaded "
            f"with: python -m store.etl.fx"
        )
    out: dict[str, float] = {}
    for period, value in returns.items():
        now = rate(in_chf, source, target, period)
        before = rate(in_chf, source, target, _previous(period))
        if now is None or before is None or before <= 0:
            continue
        out[period] = (1.0 + value) * now / before - 1.0
    return out


def source_currency(source_label: str | None, register_currency: str) -> str:
    """The currency a stored monthly return was measured in, from its source label.

    The register's own ``currency`` column says what the *instrument* is priced in, which
    is not what the stored history is in: every public proxy is US-listed and quoted in
    USD whatever the register says, and the returns recovered from the andersCH report are
    the CHF portfolio's. Anything else (returns posted through the API) is taken to be in
    the register's currency, because that is what the caller was asked for.
    """
    label = source_label or ""
    if label.startswith(("yahoo:", "cboe:")):
        return "USD"
    if label.startswith("andersch-report:"):
        return "CHF"
    return register_currency
