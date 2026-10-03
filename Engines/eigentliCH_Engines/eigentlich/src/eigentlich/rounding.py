"""Display rounding on the server (owner, 03.10.2026, ``review/ROUNDING.md``; EIG-73): the Python twin of the
client's ``client/app/format.js``, for the texts the server writes with a number in them (a finding's figures in
its sentences, the outlook's words). The same rules, the same Swiss style as the browser's de-CH (an apostrophe
between thousands, a decimal point); only the number of digits is this module's business. Engines' values and
what the client stated stay exact: the decision log keeps ``decisions.number`` for the client's own figures.

* amounts: below 1 000 whole francs; 1 000 to 99 999 to the nearest 100; 100 000 to 999 999 to the nearest 1 000;
  from 1 000 000 millions with two decimals ("1.35 Mio." / "1.35 m")
* rate: one decimal, percent; chance: whole percent, "unter 1 %" / "über 99 %" at the ends, 0 % and 100 % only for
  exactly 0 and 1; share: whole percent, below 1 % one decimal, 0 as "–"; level: two decimals; count: whole.

Rounding is half up on the magnitude, so a negative rounds as its positive does. ``None`` stays ``None``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

APOSTROPHE = "’"   # the Swiss thousands mark, as the browser's de-CH format writes it
DASH = "–"


def _q(x: float, places: int) -> Decimal:
    return Decimal(repr(abs(float(x)))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _digits(d: Decimal, places: int) -> str:
    return f"{d:,.{max(places, 0)}f}".replace(",", APOSTROPHE)


def _sign(x: float, shown: Decimal) -> str:
    return "-" if x < 0 and shown != 0 else ""


def _absent(x) -> bool:
    return x is None or isinstance(x, bool) or not isinstance(x, (int, float))


def amount(x: Optional[float], lang: str = "de") -> Optional[str]:
    """An amount's figure without the currency: 640, 38’200, 579’000, 1.35 Mio. (de) / 1.35 m (en)."""
    if _absent(x):
        return None
    a = abs(float(x))
    r = _q(a, 0) if a < 1_000 else _q(a, -2) if a < 100_000 else _q(a, -3)
    if r >= 1_000_000:
        m = _q(a / 1_000_000, 2)
        return f"{_sign(x, m)}{_digits(m, 2)} {'m' if lang == 'en' else 'Mio.'}"
    return f"{_sign(x, r)}{_digits(r, 0)}"


def money(x: Optional[float], lang: str = "de") -> Optional[str]:
    """"CHF 38’200", or ``None``."""
    a = amount(x, lang)
    return None if a is None else f"CHF {a}"


def rate(x: Optional[float], lang: str = "de") -> Optional[str]:
    """A return or rate (a decimal a year): "4.9 %"."""
    if _absent(x):
        return None
    d = _q(float(x) * 100, 1)
    return f"{_sign(x, d)}{_digits(d, 1)} %"


def chance(p: Optional[float], lang: str = "de") -> Optional[str]:
    """A chance (0 to 1): "68 %", "unter 1 %", "über 99 %"; 0 % and 100 % only when every path agrees."""
    if _absent(p):
        return None
    p = float(p)
    if p <= 0:
        return "0 %"
    if p >= 1:
        return "100 %"
    if p < 0.01:
        return "below 1 %" if lang == "en" else "unter 1 %"
    if p > 0.99:
        return "above 99 %" if lang == "en" else "über 99 %"
    return f"{_digits(_q(p * 100, 0), 0)} %"


def share(w: Optional[float], lang: str = "de") -> Optional[str]:
    """A weight or share (0 to 1): "27 %", below 1 % "0.4 %", 0 as "–"."""
    if _absent(w):
        return None
    w = float(w)
    if abs(w) < 1e-9:                      # an optimiser's 2e-16 is a zero
        return DASH
    one = _q(w * 100, 1)
    if one < 1:
        if one == 0:
            return ("below" if lang == "en" else "unter") + " 0.1 %"
        return f"{_sign(w, one)}{_digits(one, 1)} %"
    d = _q(w * 100, 0)
    return f"{_sign(w, d)}{_digits(d, 0)} %"


def level(x: Optional[float], lang: str = "de") -> Optional[str]:
    """A model level or score: two decimals ("0.62")."""
    if _absent(x):
        return None
    d = _q(x, 2)
    return f"{_sign(x, d)}{_digits(d, 2)}"


def count(x: Optional[float], lang: str = "de") -> Optional[str]:
    """Years, ages, hours and counts: a whole number ("20", "1’250")."""
    if _absent(x):
        return None
    d = _q(x, 0)
    return f"{_sign(x, d)}{_digits(d, 0)}"
