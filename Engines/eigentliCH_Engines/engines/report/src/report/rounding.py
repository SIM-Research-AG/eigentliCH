"""Display rounding (owner, 03.10.2026, ``review/ROUNDING.md``; REP-44): the report engine's one formatter.

A fact keeps its exact ``value``; its ``display`` is the rounded text made here, and the charts and the model are
handed that display. Only the number of digits is this module's business: the house style stays as it was (German:
a space between thousands, a decimal comma and "−"; English: a comma between thousands and a decimal point).

* CHF amounts: below 1 000 whole francs; 1 000 to 99 999 to the nearest 100; 100 000 to 999 999 to the nearest
  1 000; from 1 000 000 millions with two decimals ("CHF 1,35 Mio." / "CHF 1.35 m").
* Returns, rates, inflation, a required return: one decimal, percent.
* Chances: whole percent; "unter 1 %" / "below 1%" and "über 99 %" / "above 99%" at the ends; 0 % and 100 % only
  for exactly 0 and 1 (every path agrees).
* Weights and shares: whole percent; below 1 % one decimal; 0 as "–".
* Model levels and scores: two decimals. Years, ages, hours and counts: whole numbers.

Rounding is half up on the magnitude, so a negative rounds as its positive does.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

MINUS = "−"
DASH = "–"
#: A weight this small is an optimiser's zero (2e-16), shown as "–" like an exact 0.
ZERO_WEIGHT = 1e-9

#: Fact ids (after any ``change.`` / ``delta.`` prefix) whose share is a return or a rate: one decimal.
RATE_SUFFIXES = (".required_return", ".bvg.conversion")
RATE_IDS = ("lbs.real.inflation",)
#: Fact ids whose share is a chance (a probability over paths): whole percent with the words at the ends.
CHANCE_PREFIXES = ("lbsim.chance.", "lbsim.plan.chance", "lbsim.plan.confidence")
#: Fact ids whose number is a count of years or hours: whole.
WHOLE_IDS = ("lbs.mandate.horizon",)
WHOLE_SUFFIXES = ("_hours_per_week",)


def _q(x: float, places: int) -> Decimal:
    """``|x|`` rounded half up to ``places`` decimals (negative places: tens, hundreds, ...)."""
    return Decimal(repr(abs(float(x)))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _digits(d: Decimal, places: int, lang: str) -> str:
    """A non-negative decimal in the house style: grouped thousands, ``places`` decimals."""
    text = f"{d:,.{max(places, 0)}f}"
    if lang == "de":
        return text.replace(",", " ").replace(".", ",")
    return text


def _sign(x: float, shown: Decimal) -> str:
    return MINUS if x < 0 and shown != 0 else ""


def amount_text(x: float, lang: str) -> str:
    """An amount's magnitude without the currency: 640, 38 200, 579 000, 1,35 Mio. (de) / 1.35 m (en)."""
    a = abs(float(x))
    if a < 1_000:
        r = _q(a, 0)
    elif a < 100_000:
        r = _q(a, -2)
    else:
        r = _q(a, -3)
    if r >= 1_000_000:
        m = _q(a / 1_000_000, 2)
        return _digits(m, 2, lang) + (" Mio." if lang == "de" else " m")
    return _digits(r, 0, lang)


def amount_sign(x: float) -> str:
    """The sign an amount prints with: none for one that rounds to zero."""
    return MINUS if float(x) < 0 and amount_text(x, "en") != "0" else ""


def money(x: float, lang: str) -> str:
    """"CHF 38 200", "−CHF 780 000", "CHF 1,35 Mio."."""
    return amount_sign(x) + "CHF " + amount_text(x, lang)


def _percent(text: str, lang: str) -> str:
    return f"{text} %" if lang == "de" else f"{text}%"


def rate(x: float, lang: str) -> str:
    """A return or rate (a decimal a year) as a percent with one decimal: 4,9 % / 4.9%; −1,3 %."""
    d = _q(float(x) * 100, 1)
    return _sign(x, d) + _percent(_digits(d, 1, lang), lang)


CHANCE_WORDS = {"below": {"de": "unter 1 %", "en": "below 1%"}, "above": {"de": "über 99 %", "en": "above 99%"}}


def chance(p: float, lang: str) -> str:
    """A chance (0 to 1) in whole percent; "unter 1 %" and "über 99 %" at the ends; 0 % and 100 % only when every
    path agrees (exactly 0 or 1)."""
    p = float(p)
    if p <= 0:
        return _percent("0", lang)
    if p >= 1:
        return _percent("100", lang)
    if p < 0.01:
        return CHANCE_WORDS["below"][lang]
    if p > 0.99:
        return CHANCE_WORDS["above"][lang]
    return _percent(_digits(_q(p * 100, 0), 0, lang), lang)


def weight(w: float, lang: str) -> str:
    """A weight or share (0 to 1) in whole percent; below 1 % with one decimal; 0 as "–" (an optimiser's 1e-16 is
    a zero)."""
    w = float(w)
    if abs(w) < ZERO_WEIGHT:
        return DASH
    one = _q(w * 100, 1)
    if one < 1:
        if one == 0:
            return ("unter " if lang == "de" else "below ") + _percent(_digits(Decimal("0.1"), 1, lang), lang)
        return _sign(w, one) + _percent(_digits(one, 1, lang), lang)
    d = _q(w * 100, 0)
    return _sign(w, d) + _percent(_digits(d, 0, lang), lang)


def level(x: float, lang: str) -> str:
    """A model level or score without a unit: two decimals (0,62)."""
    d = _q(x, 2)
    return _sign(x, d) + _digits(d, 2, lang)


def ratio(x: float, lang: str, places: int = 1) -> str:
    """A duration or ratio: one decimal (a beta: ``places=2``)."""
    d = _q(x, places)
    return _sign(x, d) + _digits(d, places, lang)


def whole(x: float, lang: str = "de") -> str:
    """Years, ages, hours and counts: a whole number, ungrouped (2034, 67, 20)."""
    d = _q(x, 0)
    return _sign(x, d) + str(int(d))


def points(x: float, lang: str, kind: str) -> str:
    """A change of a share in percentage points: one decimal for a rate, whole (below one: one decimal) else."""
    pts = abs(float(x)) * 100
    places = 1 if kind == "rate" or _q(pts, 1) < 1 else 0
    d = _q(pts, places)
    head = "+" if x > 0 and d != 0 else MINUS if x < 0 and d != 0 else ""
    return f"{head}{_digits(d, places, lang)} " + ("Prozentpunkte" if lang == "de" else "percentage points")


def kind_of(fact_id: Optional[str], unit: str) -> str:
    """Which rule a fact's figure follows, from its unit and, for a share or a number, its id."""
    fid = fact_id or ""
    for prefix in ("change.", "delta."):
        if fid.startswith(prefix):
            fid = fid[len(prefix):]
    if unit in ("chf", "chf_per_year"):
        return "money"
    if unit == "share":
        if fid in RATE_IDS or fid.endswith(RATE_SUFFIXES):
            return "rate"
        if fid.startswith(CHANCE_PREFIXES):
            return "chance"
        return "weight"
    if unit == "number":
        if fid in WHOLE_IDS or fid.endswith(WHOLE_SUFFIXES):
            return "whole"
        return "level"
    if unit == "count":
        return "whole"
    return unit


def figure(value: float, kind: str, lang: str) -> str:
    """A number by its kind (``kind_of``)."""
    if kind == "money":
        return money(value, lang)
    if kind == "rate":
        return rate(value, lang)
    if kind == "chance":
        return chance(value, lang)
    if kind == "weight":
        return weight(value, lang)
    if kind == "whole":
        return whole(value, lang)
    if kind == "ratio":
        return ratio(value, lang)
    return level(value, lang)
